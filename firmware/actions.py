"""
Actions — the shared actuation + logging surface used by BOTH physical buttons and
the web UI, and the interface webapp.route() expects (status/snapshot/window/fans/
mister/auto/apply_decision).

Hardware-free by design: it only talks to injected objects (window, fans, valve, log,
clock). That lets the desktop simulator (sim/simulate.py) drive the exact same logic
with fake actuators — no `machine` import here.

Every actuation is logged with a `source` tag so the event log distinguishes who acted:
  "manual" = physical panel button
  "web"    = LAN web page
  "auto"   = the automation controller
"""


class Actions:
    def __init__(
        self, window, fans, valve, log, clock, automation=False, temp_unit="C"
    ):
        self._win = window
        self._fans = fans
        self._valve = valve
        self._log = log
        self._clock = clock
        self.temp = None
        self.humid = None
        self.out_temp = None
        self.out_humid = None
        self.automation = automation
        self.temp_unit = temp_unit  # display hint for the web UI; readings stay C

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
            "fans": self._fans.is_on,
            "mister": self._valve.is_on,
            "auto": self.automation,
            "unit": self.temp_unit,
            "time": self._clock(),
        }

    def snapshot(self):
        return self._log.snapshot()

    def _ctx(self):
        return (self.temp, self.humid, self.out_temp, self.out_humid)

    # -- actuations (source tags the log). a=None means toggle. --
    # source defaults to "web" since webapp.route() calls these positionally with
    # only the action arg; main.py passes source="manual" for physical buttons.
    def window(self, a=None, source="web"):
        if a == "open":
            self._win.command_open()
        elif a == "close":
            self._win.command_close()
        elif a == "stop":
            self._win.stop()
        else:
            self._win.toggle()
        self._log.event(source, "window", a or "toggle", *self._ctx())
        return self.status()

    def fans(self, a=None, source="web"):
        self._set_relay(self._fans, a)
        self._log.event(source, "fans", a or "toggle", *self._ctx())
        return self.status()

    def mister(self, a=None, source="web"):
        self._set_relay(self._valve, a)
        self._log.event(source, "mister", a or "toggle", *self._ctx())
        return self.status()

    def _set_relay(self, relay, a):
        if a == "on":
            relay.on()
        elif a == "off":
            relay.off()
        else:
            relay.set(not relay.is_on)

    # -- automation on/off (web /auto). Logged as source="web". --
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

    # -- apply a control.Decision (called by the loop when automation is on) --
    def apply_decision(self, decision):
        """Drive actuators from the controller, logging only actual CHANGES
        (source='auto') so the event log stays meaningful, not spammy."""
        want_win_open = decision.window == "open"
        is_open = self._win.status() in ("open", "opening")
        if want_win_open != is_open and not self._win.moving:
            (self._win.command_open if want_win_open else self._win.command_close)()
            self._log.event("auto", "window", decision.window, *self._ctx())
        if decision.fans != self._fans.is_on:
            self._fans.set(decision.fans)
            self._log.event(
                "auto", "fans", "on" if decision.fans else "off", *self._ctx()
            )
        if decision.mist != self._valve.is_on:
            self._valve.set(decision.mist)
            self._log.event(
                "auto", "mister", "on" if decision.mist else "off", *self._ctx()
            )
