"""
Automation brain for the greenhouse — PURE logic, no hardware imports, so it runs and
is unit-tested on CPython (tests/test_control.py).

Tuned for Maxillaria tenuifolia in Walnut Creek per docs/RULES.md. Given the two-sensor
readings + time + settings + prior state, it decides each actuator's desired state using
priority tiers (safety > temperature > humidity > optimization), resolved PER ACTUATOR:
the highest-priority rule that touches an actuator wins; lower tiers can't override it.

main.py calls Controller.tick(...) each automation tick and hands the Decision to
Actions.apply_decision(), which only drives actuators whose mode is AUTO.

Actuators:
  * window   — the Pico-controlled linear-actuator window (independent cooling/humidity
               lever). NOT the passive wax-cylinder auto-vent, which the Pico can't see.
  * vent_fan — exhaust fan; blows out THROUGH the passive auto-vent. Only moves air when
               that vent is open, so its decision is GATED on temperature as a proxy for
               "auto-vent open" (AUTO_VENT_OPEN_C). Below that it's forced off.
  * circ_fan — interior air circulation; works regardless of the vent, never gated.
  * mist     — misting solenoid, run as short bursts (see _apply_mist_guard).

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
AUTO_VENT_OPEN_C = 24.0  # vent fan only useful once the passive auto-vent has opened
MIST_BURST_S = 5  # mister pulse: on for this long...
MIST_GAP_S = 60  # ...then off at least this long before the next burst


def season_for_month(month):
    """Nov-Feb = winter rest, else growing."""
    return "rest" if month in (11, 12, 1, 2) else "growing"


class Decision:
    __slots__ = ("window", "vent_fan", "circ_fan", "mist", "reasons")

    def __init__(self, window, vent_fan, circ_fan, mist, reasons):
        self.window = window  # OPEN | CLOSED
        self.vent_fan = vent_fan  # bool (exhaust fan)
        self.circ_fan = circ_fan  # bool (circulation fan)
        self.mist = mist  # bool
        self.reasons = reasons  # dict: actuator -> rule id that set it

    def __repr__(self):
        return (
            f"Decision(window={self.window}, vent_fan={self.vent_fan}, "
            f"circ_fan={self.circ_fan}, mist={self.mist}, {self.reasons})"
        )


class _Resolver:
    """Per-actuator winner-takes-first: once a rule sets an actuator, later
    (lower-priority) rules can't change it. Rules run highest priority first."""

    def __init__(self):
        self.window = None
        self.vent_fan = None
        self.circ_fan = None
        self.mist = None
        self.reasons = {}

    def set(self, rule_id, window=None, vent_fan=None, circ_fan=None, mist=None):
        if window is not None and self.window is None:
            self.window = window
            self.reasons["window"] = rule_id
        if vent_fan is not None and self.vent_fan is None:
            self.vent_fan = vent_fan
            self.reasons["vent_fan"] = rule_id
        if circ_fan is not None and self.circ_fan is None:
            self.circ_fan = circ_fan
            self.reasons["circ_fan"] = rule_id
        if mist is not None and self.mist is None:
            self.mist = mist
            self.reasons["mist"] = rule_id

    def finalize(self):
        # unset actuators fall back to the resting state
        w = self.window if self.window is not None else CLOSED
        v = self.vent_fan if self.vent_fan is not None else False
        c = self.circ_fan if self.circ_fan is not None else False
        m = self.mist if self.mist is not None else False
        self.reasons.setdefault("window", "default")
        self.reasons.setdefault("vent_fan", "default")
        self.reasons.setdefault("circ_fan", "default")
        self.reasons.setdefault("mist", "default")
        return Decision(w, v, c, m, self.reasons)


class Controller:
    def __init__(
        self,
        settings=None,
        day_start=7,
        night_start=19,
        auto_vent_open_c=AUTO_VENT_OPEN_C,
        mist_burst_s=MIST_BURST_S,
        mist_gap_s=MIST_GAP_S,
    ):
        # A Settings object (settings.py) overrides every setpoint/global LIVE each
        # tick, so web edits take effect without a reboot. When it's None the scalar
        # params + module tables below are used, so tests and offline runs behave
        # exactly as before.
        self.settings = settings
        self.day_start = day_start
        self.night_start = night_start
        self.auto_vent_open_c = auto_vent_open_c
        self.mist_burst_s = mist_burst_s
        self.mist_gap_s = mist_gap_s
        # mist burst-cycle state
        self._mist_on_s = 0.0
        self._mist_off_s = 1e9  # start "rested" so the first wanted burst fires now
        # hourly circulation state
        self._circ_elapsed = 0.0

    def is_day(self, hour):
        ds, ns = self.day_start, self.night_start
        if self.settings is not None:
            ds = self.settings.get("day_start")
            ns = self.settings.get("night_start")
        return ds <= hour < ns

    def _setpoints(self, season):
        """The six seasonal setpoints: live from settings when present, else the
        module GROWING/REST table (identical values)."""
        if self.settings is None:
            return REST if season == "rest" else GROWING
        p = "rest_" if season == "rest" else "growing_"
        g = self.settings.get
        return {
            "day_ceiling": g(p + "day_ceiling"),
            "night_hi": g(p + "night_hi"),
            "night_lo": g(p + "night_lo"),
            "humid_floor": g(p + "humid_floor"),
            "humid_ceiling": g(p + "humid_ceiling"),
            "cold_protect": g(p + "cold_protect"),
        }

    def _g(self, key, default):
        """A tunable global: live from settings when present, else the module default."""
        return self.settings.get(key) if self.settings is not None else default

    def tick(self, tin, hin, tout, hout, hour, month, dt_s):
        """Return a Decision. Indoor readings tin/hin required; outdoor may be None."""
        sp = self._setpoints(season_for_month(month))
        day = self.is_day(hour)
        # tunables resolved once per tick (live from settings, else module defaults)
        vent_margin = self._g("vent_margin", VENT_MARGIN)
        heat_emergency = self._g("heat_emergency", HEAT_EMERGENCY)
        hard_freeze = self._g("hard_freeze", HARD_FREEZE)
        circ_period_s = self._g("circ_period_s", CIRC_PERIOD_S)
        circ_run_s = self._g("circ_run_s", CIRC_RUN_S)
        auto_vent_open_c = self._g("auto_vent_open_c", self.auto_vent_open_c)
        mist_burst_s = self._g("mist_burst_s", self.mist_burst_s)
        mist_gap_s = self._g("mist_gap_s", self.mist_gap_s)

        dpin = dew_point_c(tin, hin)
        dpout = dew_point_c(tout, hout)
        # outside is a usable drying vent only if we know it AND it's absolutely drier
        can_vent_dry = dpout is not None and dpin is not None and dpout < dpin
        cooler_out = tout is not None and tin is not None and tout < tin - vent_margin

        # advance timers
        self._circ_elapsed += dt_s

        r = _Resolver()

        # --- sensor fault: FAIL SAFE (indoor sensor is the critical one) ---
        if tin is None or hin is None:
            return Decision(CLOSED, False, False, False, {"all": "fault-failsafe"})

        # ================= 🔴 SAFETY =================
        # S1 hard freeze
        if tin <= hard_freeze:
            r.set("S1", window=CLOSED, vent_fan=False, circ_fan=False, mist=False)
        # S2 cold protection
        if tin <= sp["cold_protect"]:
            r.set("S2", window=CLOSED, mist=False)
        # S3 heat emergency: pull heat hard — exhaust + circulate + crack the window
        if tin >= heat_emergency:
            r.set(
                "S3",
                vent_fan=True,
                circ_fan=True,
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
            r.set("T1", vent_fan=True, window=OPEN if cooler_out else None)
        # T2 capture the night drop (the bloom lever) — the Pico window does this;
        # the vent fan usually gates off at these night temps (auto-vent still shut).
        if (not day) and tin > sp["night_hi"] and cooler_out:
            r.set("T2", window=OPEN, vent_fan=True)
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
        # H2 too humid: dump moisture via the window (if drier out), extract with the
        # vent fan (gated below), and always circulate to break up stagnant wet air.
        if hin > sp["humid_ceiling"]:
            r.set(
                "H2",
                vent_fan=True,
                circ_fan=True,
                window=OPEN if can_vent_dry else None,
                mist=False,
            )

        # ================= 🟢 OPTIMIZE =================
        # A1 hourly air circulation (~5 min/hr)
        circ_on = (self._circ_elapsed % circ_period_s) < circ_run_s
        if circ_on:
            r.set("A1", circ_fan=True)
        # A2 midday humidity retention
        if day and can_vent_dry and hin < sp["humid_ceiling"]:
            r.set("A2", window=CLOSED)

        decision = r.finalize()

        # --- vent-fan gate: the exhaust fan only moves air once the passive auto-vent
        # is open. We can't see it, so use temperature as the proxy. Below the opening
        # temp, force the vent fan off (running it into a shut vent is just noise).
        if decision.vent_fan and tin < auto_vent_open_c:
            decision.vent_fan = False
            decision.reasons["vent_fan"] = "gate-vent-shut"

        # --- mister burst duty-cycle (applied AFTER resolution) ---
        decision.mist = self._apply_mist_guard(
            decision.mist, dt_s, decision.reasons, mist_burst_s, mist_gap_s
        )
        return decision

    def _apply_mist_guard(self, want_mist, dt_s, reasons, mist_burst_s, mist_gap_s):
        """Turn a steady "want mist" into short bursts: mist_burst_s on, then at
        least mist_gap_s off, repeating while mist is still wanted. Prevents the
        constant-on dripping while keeping humidity topped up."""
        if not want_mist:
            self._mist_on_s = 0.0
            self._mist_off_s = 1e9  # rested: the next wanted burst can fire at once
            return False

        # Mid-burst: keep spraying until we reach the burst length.
        if 0.0 < self._mist_on_s < mist_burst_s:
            self._mist_on_s += dt_s
            return True
        # Burst just completed: begin the gap.
        if self._mist_on_s >= mist_burst_s:
            self._mist_on_s = 0.0
            self._mist_off_s = 0.0
            reasons["mist"] = "burst-gap"
            return False
        # In the gap: wait out mist_gap_s, then start the next burst.
        self._mist_off_s += dt_s
        if self._mist_off_s >= mist_gap_s:
            self._mist_on_s = dt_s
            self._mist_off_s = 0.0
            return True
        reasons["mist"] = "burst-gap"
        return False
