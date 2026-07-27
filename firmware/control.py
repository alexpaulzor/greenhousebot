"""
Automation brain for the greenhouse — PURE logic, no hardware imports, so it runs and
is unit-tested on CPython (tests/test_control.py).

Tuned for Maxillaria tenuifolia in Walnut Creek per docs/RULES.md. Given the two-sensor
readings + time + settings + prior state, it decides each actuator's desired state using
priority tiers (safety > humidity > temperature > optimization), resolved PER ACTUATOR:
the highest-priority rule that touches an actuator wins; lower tiers can't override it.

Still PARKED — not wired into main.py (the shipping MVP is manual-only). main.py will
call Controller.tick(...) once automation is enabled and apply the returned Decision.

Design choices:
  * Venting is gated on DEW POINT, not RH: open only if outside air is absolutely drier
    (DPout < DPin). If the outdoor reading is missing, vent rules stay closed (safe).
  * Seasonal setpoints: a "winter rest" (Nov-Feb) runs cooler + drier to trigger bloom.
  * All time is passed in (hour, month, dt_s) so tests are deterministic.
"""

import math

OPEN = "open"
CLOSED = "closed"


def dew_point_c(temp_c, rh):
    """Magnus-formula dew point (deg C) from temp + relative humidity (%).
    Returns None if inputs are missing/invalid."""
    if temp_c is None or rh is None or rh <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(rh / 100.0) + (a * temp_c) / (b + temp_c)
    return (b * gamma) / (a - gamma)


# Seasonal setpoint tables (see docs/RULES.md). "rest" = Nov-Feb winter rest.
GROWING = {
    "day_ceiling": 27.0,  # vent/cool above this in daytime
    "night_hi": 19.0,  # top of night band (capture drop above this)
    "night_lo": 15.0,  # bottom of night band (retain heat at/below this)
    "humid_floor": 60.0,  # mist below this
    "humid_ceiling": 85.0,  # vent above this
    "cold_protect": 12.0,  # close window at/below this
}
REST = {
    "day_ceiling": 24.0,
    "night_hi": 16.0,
    "night_lo": 11.0,
    "humid_floor": 50.0,
    "humid_ceiling": 80.0,
    "cold_protect": 8.0,
}
# Season-independent
HARD_FREEZE = 4.0
HEAT_EMERGENCY = 30.0
VENT_MARGIN = 2.0  # outside must be this many deg cooler to vent for temp
CIRC_PERIOD_S = 3600  # hourly air circulation
CIRC_RUN_S = 300  # ...for 5 minutes


def season_for_month(month):
    """Nov-Feb = winter rest, else growing."""
    return "rest" if month in (11, 12, 1, 2) else "growing"


class Decision:
    __slots__ = ("window", "fans", "mist", "reasons")

    def __init__(self, window, fans, mist, reasons):
        self.window = window  # OPEN | CLOSED
        self.fans = fans  # bool
        self.mist = mist  # bool
        self.reasons = reasons  # dict: actuator -> rule id that set it

    def __repr__(self):
        return (
            f"Decision(window={self.window}, fans={self.fans}, "
            f"mist={self.mist}, {self.reasons})"
        )


class _Resolver:
    """Per-actuator winner-takes-first: once a rule sets an actuator, later
    (lower-priority) rules can't change it. Rules run highest priority first."""

    def __init__(self):
        self.window = None
        self.fans = None
        self.mist = None
        self.reasons = {}

    def set(self, rule_id, window=None, fans=None, mist=None):
        if window is not None and self.window is None:
            self.window = window
            self.reasons["window"] = rule_id
        if fans is not None and self.fans is None:
            self.fans = fans
            self.reasons["fans"] = rule_id
        if mist is not None and self.mist is None:
            self.mist = mist
            self.reasons["mist"] = rule_id

    def finalize(self):
        # unset actuators fall back to the resting state
        w = self.window if self.window is not None else CLOSED
        f = self.fans if self.fans is not None else False
        m = self.mist if self.mist is not None else False
        self.reasons.setdefault("window", "default")
        self.reasons.setdefault("fans", "default")
        self.reasons.setdefault("mist", "default")
        return Decision(w, f, m, self.reasons)


class Controller:
    def __init__(self, settings=None, day_start=7, night_start=19):
        # settings can override any GROWING/REST/global value if desired later.
        self.day_start = day_start
        self.night_start = night_start
        # mist duty-cycle guard state
        self._mist_on_s = 0.0
        self._mist_off_s = 1e9  # start "cooled down" so first mist can fire
        # hourly circulation state
        self._circ_elapsed = 0.0

    def is_day(self, hour):
        return self.day_start <= hour < self.night_start

    def tick(self, tin, hin, tout, hout, hour, month, dt_s):
        """Return a Decision. Indoor readings tin/hin required; outdoor may be None."""
        sp = REST if season_for_month(month) == "rest" else GROWING
        day = self.is_day(hour)
        dpin = dew_point_c(tin, hin)
        dpout = dew_point_c(tout, hout)
        # outside is a usable drying vent only if we know it AND it's absolutely drier
        can_vent_dry = dpout is not None and dpin is not None and dpout < dpin
        cooler_out = tout is not None and tin is not None and tout < tin - VENT_MARGIN

        # advance timers
        self._circ_elapsed += dt_s

        r = _Resolver()

        # --- sensor fault: FAIL SAFE (indoor sensor is the critical one) ---
        if tin is None or hin is None:
            return Decision(CLOSED, False, False, {"all": "fault-failsafe"})

        # ================= 🔴 SAFETY =================
        # S1 hard freeze
        if tin <= HARD_FREEZE:
            r.set("S1", window=CLOSED, fans=False, mist=False)
        # S2 cold protection
        if tin <= sp["cold_protect"]:
            r.set("S2", window=CLOSED, mist=False)
        # S3 heat emergency
        if tin >= HEAT_EMERGENCY:
            r.set(
                "S3",
                fans=True,
                window=OPEN if cooler_out else None,
                mist=True if hin < sp["humid_ceiling"] else None,
            )

        # ================= 🟡 TEMPERATURE (higher priority than humidity) =====
        # Temperature outranks humidity because heat/cold is the faster killer and
        # humidity is cheaply recoverable (just run the mister). In practice this
        # only matters for the WINDOW -- the mister is never set by a temp rule, so
        # humidity still fully governs misting. See docs/RULES.md.
        # T1 day cooling
        if day and tin > sp["day_ceiling"]:
            r.set("T1", fans=True, window=OPEN if cooler_out else None)
        # T2 capture the night drop (the bloom lever)
        if (not day) and tin > sp["night_hi"] and cooler_out:
            r.set("T2", window=OPEN, fans=True)
        # T3 retain night heat
        if (not day) and tin <= sp["night_lo"]:
            r.set("T3", window=CLOSED)

        # ================= 🟠 HUMIDITY =================
        # H3 no wet leaves at night (lock mist OFF)
        if not day:
            r.set("H3", mist=False)
        # H1 too dry: mist to raise humidity, and by DAY keep the window shut so we
        # don't vent moisture to drier outside air. At NIGHT we deliberately do NOT
        # close for humidity -- misting is off anyway (H3) and the bloom-critical
        # night drop (T2) must be able to open the window. So H1's window action is
        # daytime-only.
        if hin < sp["humid_floor"]:
            r.set(
                "H1",
                mist=True,
                window=CLOSED if (day and can_vent_dry) else None,
            )
        # H2 too humid
        if hin > sp["humid_ceiling"]:
            r.set("H2", fans=True, window=OPEN if can_vent_dry else None, mist=False)

        # ================= 🟢 OPTIMIZE =================
        # A1 hourly air circulation (~5 min/hr)
        circ_on = (self._circ_elapsed % CIRC_PERIOD_S) < CIRC_RUN_S
        if circ_on:
            r.set("A1", fans=True)
        # A2 midday humidity retention
        if day and can_vent_dry and hin < sp["humid_ceiling"]:
            r.set("A2", window=CLOSED)

        decision = r.finalize()

        # --- mister duty-cycle guard (applied AFTER resolution) ---
        decision.mist = self._apply_mist_guard(decision.mist, dt_s, decision.reasons)
        return decision

    def _apply_mist_guard(self, want_mist, dt_s, reasons, max_on_s=120, min_off_s=60):
        if want_mist:
            if self._mist_off_s < min_off_s:
                # still in cooldown -> deny
                reasons["mist"] = "guard-cooldown"
                self._mist_off_s += dt_s
                return False
            self._mist_on_s += dt_s
            self._mist_off_s = 0.0
            if self._mist_on_s >= max_on_s:
                self._mist_on_s = 0.0
                reasons["mist"] = "guard-maxon"
                return False
            return True
        else:
            self._mist_off_s += dt_s
            self._mist_on_s = 0.0
            return False
