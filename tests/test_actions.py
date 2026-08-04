"""
Host tests for Actions — verifies actuation + the source taxonomy in the log
(manual / web / auto). Uses fakes; imports only firmware/actions.py + datalog.py.
python tests/test_actions.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

from actions import Actions  # noqa: E402
from datalog import DataLog  # noqa: E402
import settings as S  # noqa: E402


class FakeRelay:
    def __init__(self):
        self._on = False

    def set(self, on):
        self._on = bool(on)

    def on(self):
        self._on = True

    def off(self):
        self._on = False

    @property
    def is_on(self):
        return self._on


class FakeWindow:
    def __init__(self):
        self.pos = "closed"
        self.moving = False

    def status(self):
        return self.pos

    def command_open(self):
        self.pos = "open"

    def command_close(self):
        self.pos = "closed"

    def stop(self):
        self.moving = False

    def toggle(self):
        self.pos = "open" if self.pos == "closed" else "closed"


def _mk():
    clk = [1000]
    log = DataLog(lambda: clk[0])
    # window, vent, circ, valve
    a = Actions(
        FakeWindow(), FakeRelay(), FakeRelay(), FakeRelay(), log, lambda: clk[0]
    )
    a.set_readings(24.0, 60, 15.0, 80)
    return a, log


def test_web_default_source():
    a, log = _mk()
    a.fans()  # web is the positional default (webapp calls it this way)
    e = log.events.items()[-1]
    # a bare call CYCLES the mode: AUTO -> OFF, and that new mode IS the logged action
    assert e["src"] == "web" and e["dev"] == "fans" and e["act"] == "OFF"


def test_manual_source_tag():
    a, log = _mk()
    a.window(None, source="manual")
    e = log.events.items()[-1]
    assert e["src"] == "manual" and e["dev"] == "window"


def test_event_carries_both_sensors():
    a, log = _mk()
    a.mister(None, source="manual")
    e = log.events.items()[-1]
    assert e["in_t"] == 24.0 and e["out_t"] == 15.0


def test_auto_toggle_logged_as_web():
    a, log = _mk()
    a.auto()
    assert a.automation is True
    e = log.events.items()[-1]
    assert e["src"] == "web" and e["dev"] == "automation" and e["act"] == "on"


def test_apply_decision_logs_auto_and_only_changes():
    a, log = _mk()

    class D:
        window = "open"
        vent_fan = True
        circ_fan = True
        mist = False

    a.apply_decision(D())
    srcs = {e["src"] for e in log.events.items()}
    assert srcs == {"auto"}
    # window open + both fans on logged; mist was already off -> no mist event
    devs = [e["dev"] for e in log.events.items()]
    assert "window" in devs and "vent" in devs and "circ" in devs
    assert "mister" not in devs
    # calling again with no change -> no new events
    n = len(log.events.items())
    a.apply_decision(D())
    assert len(log.events.items()) == n


def _mk_with_settings():
    clk = [1000]
    log = DataLog(lambda: clk[0])
    st = S.Settings()
    saves = []
    a = Actions(
        FakeWindow(),
        FakeRelay(),
        FakeRelay(),
        FakeRelay(),
        log,
        lambda: clk[0],
        settings=st,
        save_settings=lambda: saves.append(True),
    )
    a.set_readings(24.0, 60, 15.0, 80)
    return a, log, st, saves


def test_settings_derive_display_unit_at_construction():
    a, log, st, saves = _mk_with_settings()
    # temp_unit is derived from the settings store, not the positional default
    assert a.temp_unit == st.get("temp_unit")
    assert a.status()["unit"] == st.get("temp_unit")


def test_set_settings_applies_persists_and_logs():
    a, log, st, saves = _mk_with_settings()
    out = a.set_settings({"mist_timer_min": "20", "temp_unit": "C", "bogus": "1"})
    assert out["applied"] == {"mist_timer_min": 20, "temp_unit": "C"}
    assert st.get("mist_timer_min") == 20
    assert a.mist_timer_min == 20  # re-derived onto the actuator
    assert a.temp_unit == "C" and a.status()["unit"] == "C"
    assert saves == [True]  # persister fired once
    e = log.events.items()[-1]
    assert e["src"] == "web" and e["dev"] == "settings" and e["act"] == "2"


def test_set_settings_no_change_does_not_persist_or_log():
    a, log, st, saves = _mk_with_settings()
    n = len(log.events.items())
    out = a.set_settings({"bogus": "1"})  # nothing valid
    assert out["applied"] == {}
    assert saves == []  # no persist on a no-op
    assert len(log.events.items()) == n  # no event logged


def test_get_settings_empty_without_store():
    a, log = _mk()  # built without a settings store
    assert a.get_settings() == {"specs": []}


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
