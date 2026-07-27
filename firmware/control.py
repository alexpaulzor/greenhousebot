"""
Pure control logic — the decision-making brain. NO hardware imports, so this runs
and is unit-tested on CPython (see tests/test_control.py).

Given the current sensor reading + settings + prior state + elapsed time, decide the
desired actuator states: valve (mist), fans, and window target. Uses hysteresis on
every control so relays/motor don't chatter around a setpoint.

Actuator states are described declaratively; the caller (main.py) applies them to
hardware. The window is expressed as a target ("open"/"closed") plus the controller
tracking whether it's already there, so a windowed/timed move can be issued once.
"""

OPEN = "open"
CLOSED = "closed"


class Decision:
    __slots__ = ("mist", "fans", "window_target", "reasons")

    def __init__(self, mist, fans, window_target, reasons):
        self.mist = mist  # bool: valve on?
        self.fans = fans  # bool: fan outlet on?
        self.window_target = window_target  # OPEN | CLOSED
        self.reasons = reasons  # dict for UI/logging/tests

    def __repr__(self):
        return (
            f"Decision(mist={self.mist}, fans={self.fans}, "
            f"window={self.window_target}, {self.reasons})"
        )


class Controller:
    """Holds control state between ticks (hysteresis latches + mist timer).

    All times are in seconds and passed in via `dt_s` so tests are deterministic
    (no clock dependency).
    """

    def __init__(self, settings):
        self.s = settings
        # latched outputs (hysteresis remembers which side of the band we're on)
        self._cooling = False  # fans/window-open engaged
        self._misting = False
        # mist duty-cycle guard
        self._mist_on_s = 0.0
        self._mist_off_s = 0.0

    def update_settings(self, settings):
        self.s = settings

    def tick(self, temp_c, humidity, dt_s, manual=None):
        """Compute the Decision for this instant.

        temp_c / humidity: latest reading, or None if the sensor failed.
        dt_s: seconds since last tick (for the mist timer).
        manual: optional dict to force outputs in manual mode, e.g.
                {"mist": True, "fans": False, "window": OPEN}.
        """
        s = self.s
        reasons = {}

        # --- sensor fault: FAIL SAFE ---
        # misters off (don't flood), fans off, window CLOSED (don't leave it
        # stuck open in weather). This is the safe resting state.
        if temp_c is None or humidity is None:
            self._cooling = False
            self._misting = False
            reasons["fault"] = "sensor read failed -> fail-safe"
            return Decision(False, False, CLOSED, reasons)

        # --- manual override short-circuits auto logic ---
        if s.get("mode") == "manual" and manual is not None:
            reasons["mode"] = "manual"
            return Decision(
                bool(manual.get("mist", False)),
                bool(manual.get("fans", False)),
                manual.get("window", CLOSED),
                reasons,
            )

        # --- cooling (fans + window) with hysteresis on temperature ---
        hi = s["temp_high"]
        if self._cooling:
            # stay cooling until we drop a full hysteresis band below the setpoint
            if temp_c <= hi - s["temp_hyst"]:
                self._cooling = False
        else:
            if temp_c >= hi:
                self._cooling = True
        reasons["temp"] = temp_c
        reasons["cooling"] = self._cooling

        fans = self._cooling
        window_target = OPEN if self._cooling else CLOSED

        # --- freeze protection overrides window open ---
        if temp_c <= s["temp_low"]:
            window_target = CLOSED
            reasons["freeze_protect"] = True

        # --- misting: humidity hysteresis + wet-cap + duty-cycle guard ---
        mist = self._mist_decision(humidity, dt_s, reasons)

        return Decision(mist, fans, window_target, reasons)

    def _mist_decision(self, humidity, dt_s, reasons):
        s = self.s
        reasons["humidity"] = humidity

        # never mist when already too wet (mold risk) — vent instead
        if humidity >= s["humid_high"]:
            self._misting = False
            self._mist_on_s = 0.0
            reasons["mist_block"] = "too humid"
            return False

        # hysteresis around humid_low
        if self._misting:
            if humidity >= s["humid_low"] + s["humid_hyst"]:
                self._misting = False
                self._mist_on_s = 0.0
        else:
            # respect the minimum-off cooldown before turning back on
            if humidity <= s["humid_low"] and self._mist_off_s >= s["mist_min_off_s"]:
                self._misting = True
                self._mist_on_s = 0.0

        # duty-cycle guard: cap continuous on-time, then force a pause
        if self._misting:
            self._mist_on_s += dt_s
            self._mist_off_s = 0.0
            if self._mist_on_s >= s["mist_max_on_s"]:
                self._misting = False
                self._mist_on_s = 0.0
                reasons["mist_block"] = "max on-time -> forced pause"
                return False
        else:
            self._mist_off_s += dt_s

        reasons["misting"] = self._misting
        return self._misting
