"""
Host tests for the automation brain (firmware/control.py), tuned for
Maxillaria tenuifolia per docs/RULES.md. python tests/test_control.py

Signature under test:
    Controller.tick(tin, hin, tout, hout, hour, month, dt_s) -> Decision
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

import control as ctrl  # noqa: E402

DAY = 12  # noon
NIGHT = 23  # 11pm
GROW_MONTH = 6  # June
REST_MONTH = 12  # December


def test_dew_point_basic():
    # 20C / 50% RH -> ~9.3C dew point
    dp = ctrl.dew_point_c(20.0, 50.0)
    assert 9.0 < dp < 9.6
    assert ctrl.dew_point_c(None, 50) is None
    assert ctrl.dew_point_c(20, 0) is None


def test_season_selection():
    assert ctrl.season_for_month(12) == "rest"
    assert ctrl.season_for_month(1) == "rest"
    assert ctrl.season_for_month(6) == "growing"


def test_sensor_fault_failsafe():
    c = ctrl.Controller()
    d = c.tick(None, None, 15, 60, DAY, GROW_MONTH, 2)
    assert d.window == ctrl.CLOSED and d.fans is False and d.mist is False


def test_hard_freeze_locks_everything():
    c = ctrl.Controller()
    d = c.tick(3.0, 70, 2.0, 80, NIGHT, REST_MONTH, 2)
    assert d.window == ctrl.CLOSED and d.fans is False and d.mist is False
    assert d.reasons["window"] == "S1"


def test_cold_protect_closes_window():
    c = ctrl.Controller()
    # growing cold_protect = 12C; 11C at night -> close
    d = c.tick(11.0, 65, 5.0, 70, NIGHT, GROW_MONTH, 2)
    assert d.window == ctrl.CLOSED
    assert d.reasons["window"] in ("S2", "T3")


def test_heat_emergency_vents_and_cools():
    c = ctrl.Controller()
    # 32C inside, 25C outside, dry-ish inside -> fans + open + mist pulse
    d = c.tick(32.0, 55, 25.0, 40, DAY, GROW_MONTH, 2)
    assert d.fans is True
    assert d.window == ctrl.OPEN  # outside cooler
    assert d.reasons["fans"] == "S3"


def test_heat_emergency_no_open_when_outside_hotter():
    c = ctrl.Controller()
    d = c.tick(32.0, 55, 38.0, 30, DAY, GROW_MONTH, 2)
    assert d.fans is True
    assert d.window == ctrl.CLOSED  # don't let hotter air in


def test_too_dry_mists_daytime():
    c = ctrl.Controller()
    # growing humid_floor = 60; 45% at noon -> mist on
    d = c.tick(24.0, 45, 20.0, 40, DAY, GROW_MONTH, 2)
    assert d.mist is True
    assert d.reasons["mist"] == "H1"


def test_no_mist_at_night():
    c = ctrl.Controller()
    # dry at night -> H3 forbids mist despite low humidity
    d = c.tick(17.0, 40, 12.0, 40, NIGHT, GROW_MONTH, 2)
    assert d.mist is False
    assert d.reasons["mist"] == "H3"


def test_too_humid_vents_when_outside_drier():
    c = ctrl.Controller()
    # 90% inside warm; outside cool & absolutely drier -> open + fans, mist off
    d = c.tick(24.0, 90, 14.0, 55, DAY, GROW_MONTH, 2)
    assert d.fans is True and d.mist is False
    assert d.window == ctrl.OPEN
    assert d.reasons["window"] == "H2"


def test_too_humid_no_vent_when_outside_wetter():
    c = ctrl.Controller()
    # 90% inside; outside fog holds MORE absolute moisture -> don't open
    d = c.tick(20.0, 90, 19.0, 99, DAY, GROW_MONTH, 2)
    assert d.window == ctrl.CLOSED
    assert d.fans is True  # still circulate


def test_capture_night_drop_opens():
    c = ctrl.Controller()
    # growing night_hi=19; 22C inside at night, cool dry outside -> OPEN (bloom lever)
    d = c.tick(22.0, 65, 14.0, 55, NIGHT, GROW_MONTH, 2)
    assert d.window == ctrl.OPEN and d.fans is True
    assert d.reasons["window"] == "T2"


def test_rest_season_cooler_setpoints():
    c = ctrl.Controller()
    # 22C night in REST: night_hi=16, so 22>16 and cool outside -> capture drop
    d = c.tick(22.0, 45, 12.0, 40, NIGHT, REST_MONTH, 2)
    assert d.window == ctrl.OPEN
    # and rest humid_floor=50 but night forbids mist anyway
    assert d.mist is False


def test_day_cooling_opens_if_cooler_out():
    c = ctrl.Controller()
    # growing day_ceiling=27; 28C noon, 22C outside -> fans + open
    d = c.tick(28.0, 65, 22.0, 55, DAY, GROW_MONTH, 2)
    assert d.fans is True and d.window == ctrl.OPEN
    assert d.reasons["fans"] == "T1"


def test_temp_beats_humidity_hot_and_dry():
    # Conflict: hot day (T1 wants OPEN to cool) AND dry (H1 would CLOSE to hoard
    # humidity). Temperature must win the window -> OPEN, and mist still runs.
    c = ctrl.Controller()
    d = c.tick(28.0, 45, 22.0, 30, DAY, GROW_MONTH, 2)  # 28>27 ceiling, 45<60 floor
    assert d.window == ctrl.OPEN
    assert d.reasons["window"] == "T1"
    assert d.mist is True  # humidity still governs the mister
    assert d.reasons["mist"] == "H1"


def test_temp_beats_humidity_cold_and_humid_night():
    # Conflict: cold night (T3 wants CLOSED to retain heat) AND humid (H2 would
    # OPEN to vent). Temperature must win -> CLOSED; fans still handle rot risk.
    c = ctrl.Controller()
    # growing night_lo=15; 14C night, 90% in, cool dry outside (vent-able)
    d = c.tick(14.0, 90, 8.0, 55, NIGHT, GROW_MONTH, 2)
    assert d.window == ctrl.CLOSED
    assert d.reasons["window"] == "T3"
    assert d.fans is True  # H2 still turns fans on for air movement


def test_mist_cooldown_guard():
    c = ctrl.Controller()
    # first dry daytime tick mists; immediately force cooldown by toggling
    d1 = c.tick(24.0, 45, 20.0, 40, DAY, GROW_MONTH, 2)
    assert d1.mist is True
    # simulate humidity satisfied (no mist wanted) for a short time, then dry again
    c.tick(24.0, 70, 20.0, 40, DAY, GROW_MONTH, 2)  # mist off, off-timer resets small
    d3 = c.tick(24.0, 45, 20.0, 40, DAY, GROW_MONTH, 2)  # wants mist but in cooldown
    assert d3.mist is False
    assert d3.reasons["mist"] == "guard-cooldown"


def test_resting_state_default():
    c = ctrl.Controller()
    # everything in-band, daytime, mid humidity -> all resting
    # (use a fresh controller so hourly circulation isn't active at t=0..)
    d = c.tick(24.0, 70, 20.0, 60, DAY, GROW_MONTH, 2)
    # circulation A1 may turn fans on in the first window; check window/mist rest
    assert d.window == ctrl.CLOSED
    assert d.mist is False


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
