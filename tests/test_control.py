"""
Host-runnable tests for the pure control logic. Run:  python -m pytest -q
(or: python tests/test_control.py). Imports firmware/control.py only — no hardware.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

import control as ctrl  # noqa: E402


def base_settings(**over):
    s = {
        "temp_high": 28.0,
        "temp_hyst": 1.5,
        "temp_low": 10.0,
        "humid_low": 55.0,
        "humid_hyst": 8.0,
        "humid_high": 85.0,
        "mist_max_on_s": 120,
        "mist_min_off_s": 60,
        "mode": "auto",
    }
    s.update(over)
    return s


def test_sensor_fault_is_failsafe():
    c = ctrl.Controller(base_settings())
    d = c.tick(None, None, dt_s=2)
    assert d.mist is False
    assert d.fans is False
    assert d.window_target == ctrl.CLOSED
    assert "fault" in d.reasons


def test_cooling_hysteresis():
    c = ctrl.Controller(base_settings())
    # below setpoint: no cooling
    d = c.tick(27.0, 60, dt_s=2)
    assert d.fans is False and d.window_target == ctrl.CLOSED
    # at/above setpoint: cool
    d = c.tick(28.0, 60, dt_s=2)
    assert d.fans is True and d.window_target == ctrl.OPEN
    # small drop within band: still cooling (latched)
    d = c.tick(27.0, 60, dt_s=2)
    assert d.fans is True
    # drop past full band: stop cooling
    d = c.tick(26.4, 60, dt_s=2)  # 28 - 1.5 = 26.5 threshold
    assert d.fans is False and d.window_target == ctrl.CLOSED


def test_freeze_protection_forces_closed():
    c = ctrl.Controller(base_settings())
    # force cooling on first (hot), then simulate a crash to cold
    c.tick(30.0, 60, dt_s=2)
    d = c.tick(9.0, 60, dt_s=2)  # below temp_low
    assert d.window_target == ctrl.CLOSED
    assert d.reasons.get("freeze_protect") is True


def test_misting_starts_dry_stops_wet():
    c = ctrl.Controller(base_settings())
    # need to satisfy the min-off cooldown before first mist
    c.tick(20.0, 40, dt_s=60)  # accrues off-time; humidity low
    d = c.tick(20.0, 50, dt_s=1)  # humidity<=55 and cooldown satisfied -> mist
    assert d.mist is True
    # rises past humid_low + hyst (63): stop
    d = c.tick(20.0, 64, dt_s=1)
    assert d.mist is False


def test_misting_blocked_when_too_humid():
    c = ctrl.Controller(base_settings())
    c.tick(20.0, 40, dt_s=60)
    d = c.tick(20.0, 90, dt_s=1)  # above humid_high
    assert d.mist is False
    assert d.reasons.get("mist_block") == "too humid"


def test_mist_max_on_time_forces_pause():
    c = ctrl.Controller(base_settings(mist_max_on_s=10))
    c.tick(20.0, 40, dt_s=60)  # cooldown satisfied
    c.tick(20.0, 50, dt_s=1)  # mist on
    d = c.tick(20.0, 50, dt_s=15)  # exceed max on-time
    assert d.mist is False
    assert "max on-time" in d.reasons.get("mist_block", "")


def test_manual_mode_overrides():
    c = ctrl.Controller(base_settings(mode="manual"))
    d = c.tick(
        35.0, 30, dt_s=2, manual={"mist": True, "fans": False, "window": ctrl.OPEN}
    )
    assert d.mist is True and d.fans is False and d.window_target == ctrl.OPEN


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
