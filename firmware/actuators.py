"""
Actuator drivers: relays (valve, fans) and the BTS7960 window H-bridge.

MicroPython (uses machine). Kept thin — all *decisions* live in control.py; this
only turns pins on/off and drives PWM. Fail-safe: window disable coasts the motor.
"""

import time
from machine import Pin, PWM, ADC

import config as C


class Relay:
    def __init__(self, pin_no, active_high=True):
        self._pin = Pin(pin_no, Pin.OUT)
        self._active_high = active_high
        self.off()

    def set(self, on):
        self._pin.value(1 if (on == self._active_high) else 0)
        self._on = on

    def on(self):
        self.set(True)

    def off(self):
        self.set(False)

    @property
    def is_on(self):
        return getattr(self, "_on", False)


class Window:
    """BTS7960 window actuator with internal endstops. Direction via which PWM
    channel is active; the other is held low. EN gates the bridge (low = coast).

    Position model (no position sensor needed — endstops handle the limits):
      pos in {CLOSED, OPEN, UNKNOWN}; state in {STOPPED, OPENING, CLOSING}.
    A timed move (>= real travel time) drives into the endstop, then we mark the
    position. toggle() picks the sensible next action:
      moving      -> stop (and pos becomes UNKNOWN)
      open        -> close
      closed      -> open
      unknown     -> close (safe default: seek the closed endstop)
    """

    STOPPED, OPENING, CLOSING = "stopped", "opening", "closing"
    OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"

    def __init__(self):
        self._rpwm = PWM(Pin(C.PIN_WIN_RPWM), freq=C.WIN_PWM_FREQ)
        self._lpwm = PWM(Pin(C.PIN_WIN_LPWM), freq=C.WIN_PWM_FREQ)
        self._en = Pin(C.PIN_WIN_EN, Pin.OUT)
        self._is = ADC(Pin(C.PIN_WIN_IS)) if C.PIN_WIN_IS is not None else None
        self.state = self.STOPPED
        self.pos = self.UNKNOWN
        self._target = None  # OPEN/CLOSED the current move is heading to
        self._move_deadline = 0
        self.stop()

    def _duty(self, pwm, frac):
        pwm.duty_u16(int(max(0.0, min(1.0, frac)) * 65535))

    def stop(self):
        self._duty(self._rpwm, 0)
        self._duty(self._lpwm, 0)
        self._en.value(0)  # coast — fail-safe
        self.state = self.STOPPED
        self._target = None

    def open(self, duty=None):
        d = C.WIN_DUTY if duty is None else duty
        self._duty(self._lpwm, 0)
        self._en.value(1)
        self._duty(self._rpwm, d)
        self.state = self.OPENING

    def close(self, duty=None):
        d = C.WIN_DUTY if duty is None else duty
        self._duty(self._rpwm, 0)
        self._en.value(1)
        self._duty(self._lpwm, d)
        self.state = self.CLOSING

    def current_raw(self):
        """Raw ADC of the BTS7960 IS pins (proportional to motor current), or
        None if current sense is disabled. Use for stall detection."""
        return self._is.read_u16() if self._is else None

    def start_move(self, target, ms=None):
        """Begin a NON-blocking timed move to target (OPEN or CLOSED). Call
        service() each loop pass; it stops the motor and marks pos when done.
        Non-blocking keeps buttons/web responsive and stays inside the watchdog
        window during long actuator travel."""
        ms = C.WIN_TRAVEL_MS if ms is None else ms
        self._target = target
        if target == self.OPEN:
            self.open()
        else:
            self.close()
        self._move_deadline = time.ticks_add(time.ticks_ms(), ms)

    def command_open(self):
        if self.pos != self.OPEN or self.moving:
            self.start_move(self.OPEN)

    def command_close(self):
        if self.pos != self.CLOSED or self.moving:
            self.start_move(self.CLOSED)

    def toggle(self):
        """Single-press behaviour: stop if moving, else drive to the far end."""
        if self.moving:
            self.stop()
            self.pos = self.UNKNOWN
            return
        if self.pos == self.OPEN:
            self.start_move(self.CLOSED)
        elif self.pos == self.CLOSED:
            self.start_move(self.OPEN)
        else:  # UNKNOWN -> seek closed endstop as a safe default
            self.start_move(self.CLOSED)

    def service(self):
        """Advance a non-blocking move. Returns True while still moving. On
        completion, marks pos to the move's target (drove into the endstop)."""
        if self.state == self.STOPPED:
            return False
        if time.ticks_diff(self._move_deadline, time.ticks_ms()) <= 0:
            reached = self._target
            self.stop()
            if reached in (self.OPEN, self.CLOSED):
                self.pos = reached
            return False
        return True

    @property
    def moving(self):
        return self.state != self.STOPPED

    def status(self):
        """Human/web-friendly status string."""
        if self.moving:
            return self.state  # "opening"/"closing"
        return self.pos  # "open"/"closed"/"unknown"
