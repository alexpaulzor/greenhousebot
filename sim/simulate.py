"""
Desktop simulator — run the greenhouse web UI locally in your browser with fake
sensors + generated history. NO hardware, NO Pico. Uses the REAL webapp.route,
Actions, DataLog, and Controller so what you see is the actual firmware logic.

    python sim/simulate.py            # serves http://localhost:8080
    python sim/simulate.py --port 9000 --hours 12 --screenshot out.png

Fake actuators mimic the firmware drivers' interface (Relay.is_on/set/on/off,
Window.status/toggle/command_open/command_close/stop/moving/service). A background
thread advances simulated sensors and (when automation is on) runs the control
rules, so the chart animates and toggles work — exactly like the device.
"""

import argparse
import http.server
import math
import os
import sys
import threading
import time as _time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))

import webapp  # noqa: E402
import config as C  # noqa: E402
from actions import Actions  # noqa: E402
from datalog import DataLog  # noqa: E402
from control import Controller  # noqa: E402
from settings import Settings  # noqa: E402


# ----- fake hardware (same interface the real drivers expose) -----
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
    OPEN, CLOSED = "open", "closed"

    def __init__(self):
        self.pos = self.CLOSED
        self._moving = False

    def status(self):
        return self.pos

    @property
    def moving(self):
        return self._moving

    def command_open(self):
        self.pos = self.OPEN

    def command_close(self):
        self.pos = self.CLOSED

    def stop(self):
        self._moving = False

    def toggle(self):
        self.pos = self.OPEN if self.pos == self.CLOSED else self.CLOSED

    def service(self):
        return False


# ----- simulated environment -----
class SimEnv:
    """Generates plausible inside/outside temp+humidity that also RESPOND to the
    actuators, so toggling fans/window/mister visibly changes the greenhouse."""

    def __init__(self, t0):
        self.t0 = t0
        self.tin = 22.0
        self.hin = 65.0

    def outside(self, t):
        # diurnal swing: warmest ~15:00, coolest ~05:00
        hod = (t % 86400) / 3600.0
        tout = 16 + 9 * math.sin((hod - 9) / 24 * 2 * math.pi)
        hout = 70 - 25 * math.sin((hod - 9) / 24 * 2 * math.pi)
        return round(tout, 1), round(max(20, min(99, hout)), 1)

    def step(self, t, fans_on, mist_on, win_open):
        """Advance the environment by ONE fixed 60 s sub-step (callers sub-step
        large intervals so the relaxation stays numerically stable)."""
        tout, hout = self.outside(t)
        # inside relaxes toward outside; faster with window open / fans on.
        # Coefficients are per-minute and well under 1 -> always stable.
        k = 0.03 + (0.10 if win_open else 0) + (0.05 if fans_on else 0)
        self.tin += (tout - self.tin) * k
        self.hin += (hout - self.hin) * k
        self.tin += 0.02  # small internal heat bias per minute
        if mist_on:
            self.hin += 3.0
        if fans_on:
            self.hin -= 1.0
        self.tin = max(-5, min(50, self.tin))
        self.hin = max(20, min(99, self.hin))
        return round(self.tin, 1), round(self.hin, 1), tout, hout


# ----- shared sim state (module-level so the HTTP handler + thread share it) -----
class Sim:
    def __init__(self, hours_history):
        self.start_wall = _time.time()
        # simulated clock starts `hours_history` in the past so there's a chart on load
        self.sim_t = self.start_wall - hours_history * 3600
        self.win = FakeWindow()
        self.vent = FakeRelay()
        self.circ = FakeRelay()
        self.valve = FakeRelay()
        self.log = DataLog(self._now, sample_size=1000, event_size=200)
        # a live (in-memory) settings store so the web UI's Settings panel is
        # exercisable in the sim; changes drive the controller but aren't persisted.
        self.settings = Settings()
        self.actions = Actions(
            self.win,
            self.vent,
            self.circ,
            self.valve,
            self.log,
            self._now,
            automation=False,
            temp_unit=C.TEMP_UNIT,
            settings=self.settings,
        )
        self.controller = Controller(settings=self.settings)
        self.env = SimEnv(self.sim_t)
        self.lock = threading.Lock()
        self._seed(hours_history)

    def _now(self):
        return int(self.sim_t)

    def _seed(self, hours):
        """Pre-fill the ring buffer with `hours` of 1/min samples, automation ON so
        the history shows realistic actuator activity."""
        self.actions.automation = True
        self._advance(hours * 60)  # minutes

    def _advance(self, minutes):
        """Advance the sim by `minutes`, one stable 60 s sub-step at a time. One
        sensor sample + one controller tick per simulated minute."""
        for _ in range(minutes):
            fans_on = self.vent.is_on or self.circ.is_on
            tin, hin, tout, hout = self.env.step(
                self.sim_t,
                fans_on,
                self.valve.is_on,
                self.win.status() == "open",
            )
            self.sim_t += 60
            self.actions.set_readings(tin, hin, tout, hout)
            self.actions.service()
            if self.actions.automation:
                lt = _time.localtime(self.sim_t)
                d = self.controller.tick(
                    tin,
                    hin,
                    tout,
                    hout,
                    hour=lt.tm_hour,
                    month=lt.tm_mon,
                    dt_s=60,
                )
                self.actions.apply_decision(d)
            self.log.sample(
                tin,
                hin,
                tout,
                hout,
                vent=self.vent.is_on,
                circ=self.circ.is_on,
                mist=self.valve.is_on,
                window=self.win.status(),
            )

    def run_live(self, speed):
        """Advance the sim in real wall time: `speed` sim-minutes per real second."""
        while True:
            _time.sleep(1.0)
            with self.lock:
                self._advance(max(1, speed))


SIM = None  # set in main()


class Handler(http.server.BaseHTTPRequestHandler):
    def _route(self):
        with SIM.lock:
            status, ctype, body = webapp.route(self.command, self.path, SIM.actions)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _route
    do_POST = _route

    def log_message(self, *a):
        pass  # quiet


def main():
    global SIM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--hours", type=int, default=6, help="hours of seeded history")
    ap.add_argument(
        "--speed", type=int, default=60, help="sim minutes advanced per real second"
    )
    args = ap.parse_args()

    SIM = Sim(args.hours)
    t = threading.Thread(target=SIM.run_live, args=(args.speed,), daemon=True)
    t.start()

    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"greenhouse simulator: http://localhost:{args.port}/")
    print(
        f"  seeded {args.hours}h history, advancing {args.speed} sim-min/sec, "
        f"automation ON. Ctrl-C to stop."
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
