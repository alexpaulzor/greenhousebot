"""
Actions — the shared actuation + logging surface used by BOTH physical buttons and
the web UI, and the interface webapp.route() expects (status/snapshot/window/fans/
mister/auto/apply_decision).

Per-actuator MODE model. Each actuator has a mode; a button press (or web POST with
no arg) CYCLES it, and a web POST with ?a=<MODE> sets it directly:

  window : AUTO -> OFF -> OPN -> CLS         (OFF = hold, motor idle)
  fans   : AUTO -> OFF -> VNT -> CIR -> ALL  (VNT=vent only, CIR=circ only, ALL=both)
  mister : AUTO -> OFF -> ON  -> TIM         (ON=continuous, TIM=run N min then AUTO)

AUTO hands the actuator to the controller (see apply_decision). Any other mode is a
manual override the controller won't touch. Manual modes are raw: manual VNT runs the
exhaust fan regardless of the temperature gate — that gate only shapes AUTO decisions.

Hardware-free by design: it only talks to injected objects (window, vent, circ, valve,
log, clock). That lets the desktop simulator drive the exact same logic with fakes.

Every actuation is logged with a `source` tag:
  "manual" = physical panel button   "web" = LAN web page   "auto" = the controller
"""

WIN_MODES = ("AUTO", "OFF", "OPN", "CLS")
FAN_MODES = ("AUTO", "OFF", "VNT", "CIR", "ALL")
MIS_MODES = ("AUTO", "OFF", "ON", "TIM")


class Actions:
    def __init__(
        self,
        window,
        vent,
        circ,
        valve,
        log,
        clock,
        automation=False,
        temp_unit="C",
        mist_timer_min=10,
        settings=None,
        save_settings=None,
    ):
        self._win = window
        self._vent = vent
        self._circ = circ
        self._valve = valve
        self._log = log
        self._clock = clock
        self.temp = None
        self.humid = None
        self.out_temp = None
        self.out_humid = None
        self.automation = automation  # global master; per-actuator AUTO still applies
        self.temp_unit = temp_unit  # display hint for the web UI; readings stay C
        self.mist_timer_min = mist_timer_min
        # optional live settings store (settings.py) + a persister callback. When
        # present, temp_unit + mist_timer_min are derived from it so web edits stick.
        self._settings = settings
        self._save_settings = save_settings
        if settings is not None:
            self.temp_unit = settings.get("temp_unit")
            self.mist_timer_min = settings.get("mist_timer_min")
        self.win_mode = "AUTO"
        self.fan_mode = "AUTO"
        self.mis_mode = "AUTO"
        self._mis_tim_deadline = None  # epoch when TIM reverts to AUTO

    # -- called by the loop after each sensor read --
    def set_readings(self, temp, humid, out_temp=None, out_humid=None):
        self.temp, self.humid = temp, humid
        self.out_temp, self.out_humid = out_temp, out_humid

    # -- status surface --
    def status(self):
        return {
            "temp": self.temp,
            "humid": self.humid,
            "out_temp": self.out_temp,
            "out_humid": self.out_humid,
            "window": self._win.status(),
            "vent": self._vent.is_on,
            "circ": self._circ.is_on,
            "mister": self._valve.is_on,
            "win_mode": self.win_mode,
            "fan_mode": self.fan_mode,
            "mis_mode": self.mis_mode,
            "mis_left": self._mis_left_min(),
            "auto": self.automation,
            "unit": self.temp_unit,
            "time": self._clock(),
        }

    def _mis_left_min(self):
        """Whole minutes left on the mister TIM timer, or None when not in TIM."""
        if self.mis_mode != "TIM" or self._mis_tim_deadline is None:
            return None
        left = self._mis_tim_deadline - self._clock()
        return int(left // 60) + 1 if left > 0 else 0

    def snapshot(self):
        return self._log.snapshot()

    def _ctx(self):
        return (self.temp, self.humid, self.out_temp, self.out_humid)

    @staticmethod
    def _advance(modes, current, a):
        """a=None -> next mode in the cycle; a in modes -> set it; else -> unchanged."""
        if a is None:
            i = modes.index(current) if current in modes else 0
            return modes[(i + 1) % len(modes)]
        return a if a in modes else current

    # -- actuations (source tags the log). a=None cycles; a=<MODE> sets. --
    # source defaults to "web" since webapp.route() calls these positionally with only
    # the action arg; main.py passes source="manual" for physical buttons.
    def window(self, a=None, source="web"):
        self.win_mode = self._advance(WIN_MODES, self.win_mode, a)
        self._apply_window_mode()
        self._log.event(source, "window", self.win_mode, *self._ctx())
        return self.status()

    def fans(self, a=None, source="web"):
        self.fan_mode = self._advance(FAN_MODES, self.fan_mode, a)
        self._apply_fan_mode()
        self._log.event(source, "fans", self.fan_mode, *self._ctx())
        return self.status()

    def mister(self, a=None, source="web"):
        self.mis_mode = self._advance(MIS_MODES, self.mis_mode, a)
        self._apply_mister_mode()
        self._log.event(source, "mister", self.mis_mode, *self._ctx())
        return self.status()

    def _apply_window_mode(self):
        m = self.win_mode
        if m == "OPN":
            self._win.command_open()
        elif m == "CLS":
            self._win.command_close()
        elif m == "OFF":
            self._win.stop()  # coast + hold where it is
        # AUTO: leave the window to the controller

    def _apply_fan_mode(self):
        m = self.fan_mode
        if m == "OFF":
            self._vent.off()
            self._circ.off()
        elif m == "VNT":
            self._vent.on()
            self._circ.off()
        elif m == "CIR":
            self._vent.off()
            self._circ.on()
        elif m == "ALL":
            self._vent.on()
            self._circ.on()
        # AUTO: leave the fans to the controller

    def _apply_mister_mode(self):
        m = self.mis_mode
        if m == "OFF":
            self._valve.off()
            self._mis_tim_deadline = None
        elif m == "ON":
            self._valve.on()
            self._mis_tim_deadline = None
        elif m == "TIM":
            self._valve.on()
            self._mis_tim_deadline = self._clock() + self.mist_timer_min * 60
        else:  # AUTO
            self._mis_tim_deadline = None

    # -- called every loop pass: expire the mister TIM timer back to AUTO --
    def service(self):
        if (
            self.mis_mode == "TIM"
            and self._mis_tim_deadline is not None
            and self._clock() >= self._mis_tim_deadline
        ):
            self.mis_mode = "AUTO"
            self._mis_tim_deadline = None
            self._valve.off()  # hand back to AUTO in a known-off state
            self._log.event("auto", "mister", "AUTO", *self._ctx())

    # -- web-adjustable settings (web /settings GET+POST) --
    def get_settings(self):
        """UI payload: every spec with its current value (empty if no store wired)."""
        return {"specs": self._settings.specs() if self._settings else []}

    def set_settings(self, incoming, source="web"):
        """Validate+apply incoming {key:value}, re-derive the display unit + mist
        timer, persist to flash, and log the change. Returns the fresh specs +
        the dict of values actually applied."""
        if not self._settings:
            return self.get_settings()
        applied = self._settings.update(incoming)
        self.temp_unit = self._settings.get("temp_unit")
        self.mist_timer_min = self._settings.get("mist_timer_min")
        if applied and self._save_settings:
            try:
                self._save_settings()
            except Exception as e:  # persistence is best-effort; never crash the loop
                print("settings save failed:", e)
        if applied:
            self._log.event(source, "settings", str(len(applied)), *self._ctx())
        out = self.get_settings()
        out["applied"] = applied
        return out

    # -- automation master on/off (web /auto). Logged as source="web". --
    def auto(self, a=None, source="web"):
        if a == "on":
            self.automation = True
        elif a == "off":
            self.automation = False
        else:
            self.automation = not self.automation
        self._log.event(
            source, "automation", "on" if self.automation else "off", *self._ctx()
        )
        return self.status()

    # -- apply a control.Decision (called by the loop when the master is on) --
    def apply_decision(self, decision):
        """Drive only the actuators whose mode is AUTO, logging just the actual
        CHANGES (source='auto') so the event log stays meaningful, not spammy."""
        if self.win_mode == "AUTO":
            want_win_open = decision.window == "open"
            is_open = self._win.status() in ("open", "opening")
            if want_win_open != is_open and not self._win.moving:
                (self._win.command_open if want_win_open else self._win.command_close)()
                self._log.event("auto", "window", decision.window, *self._ctx())
        if self.fan_mode == "AUTO":
            if decision.vent_fan != self._vent.is_on:
                self._vent.set(decision.vent_fan)
                self._log.event(
                    "auto", "vent", "on" if decision.vent_fan else "off", *self._ctx()
                )
            if decision.circ_fan != self._circ.is_on:
                self._circ.set(decision.circ_fan)
                self._log.event(
                    "auto", "circ", "on" if decision.circ_fan else "off", *self._ctx()
                )
        if self.mis_mode == "AUTO":
            if decision.mist != self._valve.is_on:
                self._valve.set(decision.mist)
                self._log.event(
                    "auto", "mister", "on" if decision.mist else "off", *self._ctx()
                )
