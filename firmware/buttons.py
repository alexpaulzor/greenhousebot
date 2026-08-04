"""
Button input: 3 momentary buttons to GND (internal pull-ups). Each press CYCLES that
actuator's mode (window/fans/mister — see actions.py). Poll-based with debounce; one
event per press (falling edge), no auto-repeat so a hold can't advance twice.

Events: "window", "fans", "mister" — main.py maps each to actions.<name>(None), which
advances that actuator's mode by one step.
"""

import time
from machine import Pin

import config as C

WINDOW, FANS, MISTER = "window", "fans", "mister"


class Buttons:
    def __init__(self):
        self._pins = {
            WINDOW: Pin(C.PIN_BTN_WINDOW, Pin.IN, Pin.PULL_UP),
            FANS: Pin(C.PIN_BTN_FANS, Pin.IN, Pin.PULL_UP),
            MISTER: Pin(C.PIN_BTN_MISTER, Pin.IN, Pin.PULL_UP),
        }
        self._down = {k: False for k in self._pins}
        self._t_change = {k: 0 for k in self._pins}

    def _pressed(self, name):
        return self._pins[name].value() == 0  # active-low

    def poll(self):
        """Return a list of press events this tick (may be empty). One per press."""
        now = time.ticks_ms()
        events = []
        for name in self._pins:
            pressed = self._pressed(name)
            if pressed != self._down[name]:
                if time.ticks_diff(now, self._t_change[name]) < C.BTN_DEBOUNCE_MS:
                    continue  # bounce
                self._t_change[name] = now
                self._down[name] = pressed
                if pressed:  # falling edge = press
                    events.append(name)
        return events
