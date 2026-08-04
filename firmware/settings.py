"""
Settings — the web-adjustable, reboot-persistent tuning store. PURE logic (no hardware
imports) so it runs and is unit-tested on CPython (tests/test_settings.py).

The behavioural constants that a grower actually tunes (seasonal setpoints, vent/mist
timings, safety limits, display unit) live here as one ordered `SPEC` list. That single
list is the source of truth for three things at once:
  * defaults        — pulled from config.py / control.py so nothing is duplicated;
  * validation      — each entry carries a type + range (or choices);
  * the web UI       — webapp renders inputs straight from specs(), in SPEC order.

Wiring: main.py builds one Settings, loads it from flash, and hands the SAME object to
both Controller (which reads setpoints live each tick) and Actions (which re-derives its
display unit + mist-timer on change and persists). Infra constants (pins, I2C, log sizes,
WiFi, PWM/travel timing) stay in config.py on purpose — they're build-time, not tuning.
"""

try:
    import ujson as json
except ImportError:
    import json

import config as C
import control as K


def _num(key, group, label, default, lo, hi, step, is_int=False):
    return {
        "key": key,
        "group": group,
        "label": label,
        "type": "int" if is_int else "float",
        "default": default,
        "min": lo,
        "max": hi,
        "step": step,
    }


def _season_specs(prefix, group, table):
    """The six per-season setpoints, defaults sourced from control's GROWING/REST."""
    p = prefix + "_"
    return [
        _num(
            p + "day_ceiling",
            group,
            "Day ceiling °C",
            table["day_ceiling"],
            15,
            40,
            0.5,
        ),
        _num(
            p + "night_hi", group, "Night band high °C", table["night_hi"], 5, 30, 0.5
        ),
        _num(p + "night_lo", group, "Night band low °C", table["night_lo"], 5, 30, 0.5),
        _num(
            p + "humid_floor",
            group,
            "Humidity floor %",
            table["humid_floor"],
            20,
            90,
            1,
            True,
        ),
        _num(
            p + "humid_ceiling",
            group,
            "Humidity ceiling %",
            table["humid_ceiling"],
            40,
            100,
            1,
            True,
        ),
        _num(
            p + "cold_protect",
            group,
            "Cold-protect close °C",
            table["cold_protect"],
            0,
            20,
            0.5,
        ),
    ]


# Ordered spec — also drives the web UI layout (grouped in this order).
SPEC = (
    _season_specs("growing", "Growing season", K.GROWING)
    + _season_specs("rest", "Winter rest", K.REST)
    + [
        _num(
            "hard_freeze", "Safety", "Hard-freeze lockout °C", K.HARD_FREEZE, 0, 10, 0.5
        ),
        _num(
            "heat_emergency",
            "Safety",
            "Heat emergency °C",
            K.HEAT_EMERGENCY,
            25,
            40,
            0.5,
        ),
        _num(
            "auto_vent_open_c",
            "Venting",
            "Auto-vent open temp °C",
            C.AUTO_VENT_OPEN_C,
            10,
            35,
            0.5,
        ),
        _num(
            "vent_margin",
            "Venting",
            "Outside-cooler margin °C",
            K.VENT_MARGIN,
            0,
            10,
            0.5,
        ),
        _num(
            "circ_period_s",
            "Circulation",
            "Circulate every (s)",
            K.CIRC_PERIOD_S,
            300,
            21600,
            300,
            True,
        ),
        _num(
            "circ_run_s",
            "Circulation",
            "Circulate for (s)",
            K.CIRC_RUN_S,
            30,
            3600,
            30,
            True,
        ),
        _num("mist_burst_s", "Misting", "Burst on (s)", C.MIST_BURST_S, 1, 60, 1, True),
        _num("mist_gap_s", "Misting", "Burst gap (s)", C.MIST_GAP_S, 5, 600, 5, True),
        _num(
            "mist_timer_min",
            "Misting",
            "TIM button run (min)",
            C.MIST_TIMER_MIN,
            1,
            120,
            1,
            True,
        ),
        _num("day_start", "Schedule", "Day starts (hour)", 7, 0, 23, 1, True),
        _num("night_start", "Schedule", "Night starts (hour)", 19, 0, 23, 1, True),
        {
            "key": "temp_unit",
            "group": "Display",
            "label": "Temperature unit",
            "type": "choice",
            "default": C.TEMP_UNIT,
            "choices": ["F", "C"],
        },
    ]
)


# Ordering invariants enforced on every update, as (low_key, high_key, strict).
# Each field is range-clamped independently, so a fat-finger could otherwise reach a
# self-contradictory pair. The sharpest one is day_start >= night_start: is_day() then
# returns False for every hour, silently disarming ALL daytime cooling (rule T1). A
# change that would break an invariant is dropped (the offending key snaps back), the
# same friendly spirit as clamping. See docs/notes/settings-work.md D2.
ORDER_CONSTRAINTS = (
    ("day_start", "night_start", True),
    ("growing_night_lo", "growing_night_hi", False),
    ("rest_night_lo", "rest_night_hi", False),
    ("growing_humid_floor", "growing_humid_ceiling", False),
    ("rest_humid_floor", "rest_humid_ceiling", False),
)


class Settings:
    """Holds the current value of every SPEC key, validates updates, and persists to a
    JSON file. Read with get(); change with update(); render with specs()."""

    def __init__(self, spec=SPEC):
        self._spec = spec
        self._by_key = {s["key"]: s for s in spec}
        self._values = {s["key"]: s["default"] for s in spec}

    def get(self, key):
        return self._values[key]

    def as_dict(self):
        return dict(self._values)

    def specs(self):
        """SPEC metadata with each key's CURRENT value folded in, in display order."""
        out = []
        for s in self._spec:
            item = dict(s)
            item["value"] = self._values[s["key"]]
            out.append(item)
        return out

    def update(self, incoming):
        """Apply {key: value} for known keys only. Numbers are coerced + clamped to
        [min, max]; choices must be valid; unknown keys and junk are ignored. Only keys
        whose value actually CHANGES are applied (so a no-op Save writes nothing). A
        change that would break an ORDER_CONSTRAINT is reverted. Returns the dict of
        values actually applied (post-clamp)."""
        prior = dict(self._values)
        applied = {}
        for key, raw in incoming.items():
            spec = self._by_key.get(key)
            if spec is None:
                continue
            val = self._coerce(spec, raw)
            if val is None or val == self._values[key]:
                continue
            self._values[key] = val
            applied[key] = val
        self._enforce_order(prior, applied)
        return applied

    def _enforce_order(self, prior, applied):
        """Revert any just-applied key that would leave a low/high pair inconsistent, so
        a fat-finger can't silently disarm a control tier (see ORDER_CONSTRAINTS). A
        pre-existing bad pair that this update didn't touch is left alone."""
        for lo_key, hi_key, strict in ORDER_CONSTRAINTS:
            lo, hi = self._values[lo_key], self._values[hi_key]
            if (lo < hi) if strict else (lo <= hi):
                continue
            for k in (lo_key, hi_key):
                if k in applied:
                    self._values[k] = prior[k]
                    del applied[k]

    @staticmethod
    def _coerce(spec, raw):
        if spec["type"] == "choice":
            return raw if raw in spec["choices"] else None
        try:
            val = int(raw) if spec["type"] == "int" else float(raw)
        except (TypeError, ValueError):
            return None
        if val < spec["min"]:
            val = spec["min"]
        elif val > spec["max"]:
            val = spec["max"]
        return val

    # -- persistence (store = anything with open(path, mode); e.g. FsAdapter) --
    def load(self, store, path):
        """Overlay saved values onto the defaults. Missing/corrupt file -> keep
        defaults and return False (never raises on a bad file)."""
        try:
            f = store.open(path, "r")
        except OSError:
            return False
        try:
            data = json.load(f)
        except (ValueError, OSError):
            return False
        finally:
            f.close()
        if isinstance(data, dict):
            self.update(data)
            return True
        return False

    def save(self, store, path):
        """Persist atomically: write a temp file, then rename over the target. A brownout
        mid-write (outdoor build, flaky power) can't leave a half-written settings.json
        that would revert every tuned value to defaults on next boot. littlefs (the Pico's
        default FS) does an atomic replacing rename."""
        tmp = path + ".tmp"
        f = store.open(tmp, "w")
        try:
            json.dump(self._values, f)
        finally:
            f.close()
        store.rename(tmp, path)
        return True
