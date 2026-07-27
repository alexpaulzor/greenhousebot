"""Host tests for datalog: ring buffer, dual-sensor samples, rotating CSV.
python tests/test_datalog.py"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

import datalog as D  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000

    def __call__(self):
        return self.t


class FakeFs:
    """In-memory fake of the fs interface RotatingCsv needs."""

    def __init__(self):
        self.files = {}  # path -> str

    def open(self, path, mode):
        buf = io.StringIO()
        if mode == "a" and path in self.files:
            buf.write(self.files[path])
        fs, files = self, self.files

        class _F:
            def write(_s, t):
                buf.write(t)

            def close(_s):
                files[path] = buf.getvalue()

        return _F()

    def size(self, path):
        return len(self.files[path]) if path in self.files else None

    def remove(self, path):
        self.files.pop(path, None)

    def rename(self, src, dst):
        self.files[dst] = self.files.pop(src)


def test_ring_wraps_oldest_first():
    r = D.Ring(3)
    for x in (1, 2, 3, 4):
        r.add(x)
    assert r.items() == [2, 3, 4]
    assert len(r) == 3


def test_dual_sensor_sample():
    clk = Clock()
    log = D.DataLog(clk, sample_size=4, event_size=4)
    log.sample(24.5, 60, 15.0, 80, fans=True, mist=False, window="open")
    s = log.samples.items()[0]
    assert s == {
        "t": 1000,
        "in_t": 24.5,
        "in_h": 60,
        "out_t": 15.0,
        "out_h": 80,
        "fans": 1,
        "mist": 0,
        "win": 1,
    }


def test_sample_actuator_state_optional_and_coded():
    clk = Clock()
    log = D.DataLog(clk, sample_size=4)
    log.sample(20, 50)  # no outdoor, no actuator state
    s = log.samples.items()[0]
    assert s["out_t"] is None and s["fans"] is None and s["win"] is None
    log.sample(21, 51, window="closed", fans=False, mist=True)
    s2 = log.samples.items()[1]
    assert s2["win"] == 0 and s2["mist"] == 1 and s2["fans"] == 0


def test_event_with_context():
    clk = Clock()
    log = D.DataLog(clk, event_size=4)
    log.event("button", "fans", "on", 25.0, 55, 12.0, 70)
    e = log.events.items()[0]
    assert e["src"] == "button" and e["act"] == "on" and e["out_t"] == 12.0


def test_snapshot_shape():
    log = D.DataLog(Clock())
    log.sample(20, 50)
    log.event("web", "window", "open")
    snap = log.snapshot()
    assert set(snap.keys()) == {"samples", "events"}


def test_rotating_csv_writes_header_and_row():
    fs = FakeFs()
    csv = D.RotatingCsv("logs/s.csv", D.SAMPLE_HEADER, fs, max_bytes=1000, keep=3)
    csv.append([1000, 24.5, 60, 15.0, 80])
    content = fs.files["logs/s.csv"]
    assert content.startswith(D.SAMPLE_HEADER + "\n")
    assert "1000,24.5,60,15.0,80" in content


def test_rotating_csv_none_becomes_empty():
    fs = FakeFs()
    csv = D.RotatingCsv("logs/s.csv", D.SAMPLE_HEADER, fs)
    csv.append([1000, 24.5, 60, None, None])
    assert "1000,24.5,60,," in fs.files["logs/s.csv"]


def test_rotating_csv_rotates_and_bounds():
    fs = FakeFs()
    # tiny cap forces frequent rotation; keep=2 generations
    csv = D.RotatingCsv("logs/s.csv", "h", fs, max_bytes=40, keep=2)
    for i in range(50):
        csv.append([i, i, i, i, i])
    # only base + .1 + .2 may exist (keep=2), never .3
    paths = set(fs.files.keys())
    assert "logs/s.csv" in paths
    assert "logs/s.csv.3" not in paths
    assert paths <= {"logs/s.csv", "logs/s.csv.1", "logs/s.csv.2"}


def test_datalog_persists_via_sink():
    fs = FakeFs()
    sink = D.RotatingCsv("logs/s.csv", D.SAMPLE_HEADER, fs, max_bytes=10000)
    log = D.DataLog(Clock(), sample_sink=sink)
    log.sample(21.0, 51, 10.0, 61, fans=True, mist=False, window="open")
    content = fs.files["logs/s.csv"]
    assert content.startswith("t,in_t,in_h,out_t,out_h,fans,mist,win\n")
    assert "1000,21.0,51,10.0,61,1,0,1" in content


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
