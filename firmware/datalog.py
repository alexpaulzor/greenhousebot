"""
Data logging: an in-RAM ring buffer of temp/humidity samples + an event log of
interventions, with an optional bounded, rotating CSV persistence sink on flash.

Pure logic where it matters (host-tested). Time is supplied by a `now()` callable so
tests are deterministic and we don't care whether NTP synced or we're boot-relative.

Samples carry BOTH sensors:
    {"t", "in_t", "in_h", "out_t", "out_h"}   (any value may be None on fault)
Events:
    {"t", "src", "dev", "act", "in_t", "in_h", "out_t", "out_h"}

Persistence (RotatingCsv) appends CSV rows and rotates files at a byte cap, keeping a
fixed number of generations so flash never fills. It's dependency-injected (open/
listdir/remove/stat via an `fs` object) so it runs under host tests with a fake FS.
"""


class Ring:
    """Fixed-size ring buffer of arbitrary items, oldest overwritten first."""

    def __init__(self, size):
        self.size = size
        self._buf = [None] * size
        self._i = 0
        self._n = 0

    def add(self, item):
        self._buf[self._i] = item
        self._i = (self._i + 1) % self.size
        if self._n < self.size:
            self._n += 1

    def items(self):
        """Return items oldest -> newest."""
        if self._n < self.size:
            return self._buf[: self._n]
        return self._buf[self._i :] + self._buf[: self._i]

    def __len__(self):
        return self._n


class RotatingCsv:
    """Append CSV rows to <path>; when it exceeds max_bytes, rotate to
    <path>.1, <path>.2, ... keeping `keep` generations (oldest deleted).

    `fs` provides: open(path, mode), size(path)->int|None, remove(path),
    rename(src,dst). On MicroPython pass FsAdapter(); tests pass a fake."""

    def __init__(self, path, header, fs, max_bytes=65536, keep=4):
        self.path = path
        self.header = header
        self.fs = fs
        self.max_bytes = max_bytes
        self.keep = keep
        # ensure header exists on a fresh file
        if self.fs.size(path) is None:
            self._write(header + "\n", mode="w")

    def append(self, row_fields):
        line = ",".join("" if v is None else str(v) for v in row_fields) + "\n"
        if (self.fs.size(self.path) or 0) + len(line) > self.max_bytes:
            self._rotate()
            self._write(self.header + "\n", mode="w")
        self._write(line, mode="a")

    def _write(self, text, mode):
        f = self.fs.open(self.path, mode)
        try:
            f.write(text)
        finally:
            f.close()

    def _rotate(self):
        # delete oldest, shift the rest up, current -> .1
        oldest = "{}.{}".format(self.path, self.keep)
        if self.fs.size(oldest) is not None:
            self.fs.remove(oldest)
        for i in range(self.keep - 1, 0, -1):
            src = "{}.{}".format(self.path, i)
            if self.fs.size(src) is not None:
                self.fs.rename(src, "{}.{}".format(self.path, i + 1))
        self.fs.rename(self.path, "{}.1".format(self.path))


SAMPLE_HEADER = "t,in_t,in_h,out_t,out_h,fans,mist,win"
EVENT_HEADER = "t,src,dev,act,in_t,in_h,out_t,out_h"


def _b(v):
    """bool -> 1/0, None stays None (empty CSV cell)."""
    return None if v is None else (1 if v else 0)


def _win_code(window):
    """Window status string -> 1 if open/opening else 0; None stays None."""
    if window is None:
        return None
    return 1 if window in ("open", "opening") else 0


class DataLog:
    def __init__(
        self, now, sample_size=240, event_size=100, sample_sink=None, event_sink=None
    ):
        """now: zero-arg callable returning epoch seconds.
        sample_sink / event_sink: optional RotatingCsv for flash persistence."""
        self._now = now
        self.samples = Ring(sample_size)
        self.events = Ring(event_size)
        self._sample_sink = sample_sink
        self._event_sink = event_sink

    def sample(
        self, in_t, in_h, out_t=None, out_h=None, fans=None, mist=None, window=None
    ):
        """Record a periodic reading + actuator state at that instant.
        Actuator state lets the chart draw on/open bars and enriches analysis.
        fans/mist are bools (or None); window is "open"/"closed"/... (or None)."""
        win = _win_code(window)
        row = {
            "t": self._now(),
            "in_t": in_t,
            "in_h": in_h,
            "out_t": out_t,
            "out_h": out_h,
            "fans": _b(fans),
            "mist": _b(mist),
            "win": win,
        }
        self.samples.add(row)
        if self._sample_sink:
            self._sample_sink.append(
                [row["t"], in_t, in_h, out_t, out_h, row["fans"], row["mist"], win]
            )

    def event(
        self, source, device, action, in_t=None, in_h=None, out_t=None, out_h=None
    ):
        """Record an intervention with the sensor context at that moment.
        source: "manual" | "web" | "auto"; device: "window"|"fans"|"mister"."""
        row = {
            "t": self._now(),
            "src": source,
            "dev": device,
            "act": action,
            "in_t": in_t,
            "in_h": in_h,
            "out_t": out_t,
            "out_h": out_h,
        }
        self.events.add(row)
        if self._event_sink:
            self._event_sink.append(
                [row["t"], source, device, action, in_t, in_h, out_t, out_h]
            )

    def snapshot(self):
        """Dict suitable for json.dumps -> served by the web layer."""
        return {"samples": self.samples.items(), "events": self.events.items()}
