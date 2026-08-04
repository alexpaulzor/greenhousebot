"""
Greenhouse controller — MicroPython entry point (Pico 2 W).

Behaviour:
  * 3 buttons cycle per-actuator MODES: window (AUTO/OFF/OPN/CLS), fans
    (AUTO/OFF/VNT/CIR/ALL), mister (AUTO/OFF/ON/TIM). See actions.py.
  * LCD shows indoor+outdoor temp/humidity plus each actuator's mode + state.
  * LAN web page mirrors readings + modes and offers the same controls.
  * Every actuation and periodic sample is logged (in-RAM ring buffers, JSON at /data).
  * Automation is live: when the master is on, each AUTO-mode actuator is driven by
    control.py; manual modes are left alone.

Structure: `Actions` is the single place that performs an actuation (from a button OR
the web) and logs it, so both input paths behave identically. The main loop is
cooperative and non-blocking: sensor read on a timer, window move serviced each pass,
web served each pass, watchdog fed each pass.
"""

import time
from machine import I2C, Pin, WDT

import config as C
from aht21 import AHT21
from lcd import LCD
from actuators import Relay, Window
from actions import Actions
from buttons import Buttons, WINDOW, FANS, MISTER
from datalog import DataLog
from control import Controller
from settings import Settings
import wifi


def _clock():
    """UTC epoch seconds (or boot-relative until NTP syncs). Log timestamps are
    kept in UTC on purpose: unambiguous for later scraping/analysis, no DST gaps.
    LOCAL time (for the controller's season/day-night) comes from wifi.local_now()."""
    return time.time()


def main():
    # --- hardware: I2C0 = indoor sensor + LCD; I2C1 = outdoor sensor ---
    i2c = I2C(C.I2C_ID, sda=Pin(C.PIN_SDA), scl=Pin(C.PIN_SCL), freq=C.I2C_FREQ)
    found = i2c.scan()
    print("I2C0 devices:", [hex(a) for a in found])

    sensor = AHT21(i2c, C.ADDR_AHT21)
    lcd_addr = (
        C.ADDR_LCD if C.ADDR_LCD in found else (found[0] if found else C.ADDR_LCD)
    )
    lcd = LCD(i2c, lcd_addr, C.LCD_COLS, C.LCD_ROWS)

    # outdoor sensor on its own bus (AHT21 addr 0x38 is fixed -> can't share)
    out_sensor = None
    if C.OUTDOOR_ENABLED:
        try:
            i2c1 = I2C(
                C.I2C1_ID, sda=Pin(C.PIN_SDA1), scl=Pin(C.PIN_SCL1), freq=C.I2C1_FREQ
            )
            print("I2C1 devices:", [hex(a) for a in i2c1.scan()])
            out_sensor = AHT21(i2c1, C.ADDR_AHT21)
        except Exception as e:
            print("outdoor sensor init failed:", e)

    valve = Relay(C.PIN_RELAY_VALVE, C.RELAY_ACTIVE_HIGH)
    vent = Relay(C.PIN_RELAY_VENT, C.RELAY_ACTIVE_HIGH)
    circ = Relay(C.PIN_RELAY_CIRC, C.RELAY_ACTIVE_HIGH)
    window = Window()
    buttons = Buttons()

    # --- data log (RAM ring + optional bounded flash persistence) ---
    sample_sink = event_sink = None
    if C.LOG_PERSIST:
        try:
            from fsadapter import FsAdapter
            from datalog import RotatingCsv, SAMPLE_HEADER, EVENT_HEADER

            fs = FsAdapter(C.LOG_DIR)
            sample_sink = RotatingCsv(
                C.LOG_DIR + "/samples.csv",
                SAMPLE_HEADER,
                fs,
                C.LOG_FILE_MAX_BYTES,
                C.LOG_FILE_KEEP,
            )
            event_sink = RotatingCsv(
                C.LOG_DIR + "/events.csv",
                EVENT_HEADER,
                fs,
                C.LOG_FILE_MAX_BYTES,
                C.LOG_FILE_KEEP,
            )
        except Exception as e:
            print("log persistence disabled:", e)

    log = DataLog(_clock, C.SAMPLE_RING, C.EVENT_RING, sample_sink, event_sink)

    # --- web-adjustable settings (persisted to flash, overlaid on defaults) ---
    settings = Settings()
    try:
        from fsadapter import FsAdapter

        settings_fs = FsAdapter(".")  # settings.json at flash root
        settings.load(settings_fs, C.SETTINGS_FILE)

        def _save_settings():
            settings.save(settings_fs, C.SETTINGS_FILE)

    except Exception as e:
        print("settings persistence disabled:", e)
        _save_settings = None

    actions = Actions(
        window,
        vent,
        circ,
        valve,
        log,
        _clock,
        C.AUTOMATION_DEFAULT,
        C.TEMP_UNIT,
        C.MIST_TIMER_MIN,
        settings=settings,
        save_settings=_save_settings,
    )
    controller = Controller(settings=settings)

    lcd.line(0, "Greenhouse")
    lcd.line(1, "starting...")

    # --- network (best effort; controller works fully offline) ---
    server = None
    ip = wifi.connect()
    if ip:
        wifi.sync_time(C.NTP_HOST)
        try:
            from webserver import WebServer

            server = WebServer(actions, C.WEB_PORT)
            print("web: http://%s:%d/" % (ip, C.WEB_PORT))
        except Exception as e:
            print("web: failed to start", e)

    # --- watchdog: loop is non-blocking, fed every pass ---
    wdt = WDT(timeout=8000)

    last_sample = time.ticks_ms()
    last_log = time.ticks_ms()
    last_auto = time.ticks_ms()

    while True:
        # window move progresses without blocking
        window.service()
        # expire the mister TIM timer (reverts to AUTO) if it's running
        actions.service()

        # buttons -> cycle that actuator's mode (logged as source="manual")
        for ev in buttons.poll():
            if ev == WINDOW:
                actions.window(None, source="manual")
            elif ev == FANS:
                actions.fans(None, source="manual")
            elif ev == MISTER:
                actions.mister(None, source="manual")
            _draw(lcd, actions)

        # web (non-blocking)
        if server:
            try:
                server.serve_once()
            except Exception as e:
                print("web error", e)

        now = time.ticks_ms()

        # periodic sensor read + LCD refresh
        if time.ticks_diff(now, last_sample) >= C.SAMPLE_MS:
            last_sample = now
            temp, humid = _read(sensor, "indoor")
            out_temp, out_humid = (
                _read(out_sensor, "outdoor") if out_sensor else (None, None)
            )
            actions.set_readings(temp, humid, out_temp, out_humid)
            _draw(lcd, actions)

            # periodic sample into the ring buffer (+ flash persistence),
            # including current actuator state so the chart can draw on/open bars.
            if time.ticks_diff(now, last_log) >= C.LOG_SAMPLE_MS:
                last_log = now
                log.sample(
                    temp,
                    humid,
                    out_temp,
                    out_humid,
                    vent=vent.is_on,
                    circ=circ.is_on,
                    mist=valve.is_on,
                    window=window.status(),
                )

        # automation tick: run the rules and apply their decision
        if actions.automation and time.ticks_diff(now, last_auto) >= C.AUTO_TICK_MS:
            dt_s = time.ticks_diff(now, last_auto) / 1000.0
            last_auto = now
            lt = wifi.local_now(C.TZ_OFFSET_S)  # (Y, M, D, hh, mm, ss, ...)
            decision = controller.tick(
                actions.temp,
                actions.humid,
                actions.out_temp,
                actions.out_humid,
                hour=lt[3],
                month=lt[1],
                dt_s=dt_s,
            )
            actions.apply_decision(decision)
            _draw(lcd, actions)

        wdt.feed()
        time.sleep_ms(20)


def _read(sensor, label):
    try:
        return sensor.measure()
    except (OSError, ValueError) as e:
        print(label, "sensor fault", e)
        return None, None


def _row(lcd, row, left, right=""):
    """Write one LCD row, right-justifying `right`, padded/truncated to LCD_COLS so
    stale characters from a previous frame are always overwritten."""
    w = C.LCD_COLS
    if right:
        gap = w - len(left) - len(right)
        text = left + (" " * gap if gap >= 1 else " ") + right
    else:
        text = left
    lcd.line(row, text.ljust(w)[:w])


def _draw(lcd, actions):
    s = actions.status()
    unit = s.get("unit", C.TEMP_UNIT)  # live display unit (web-adjustable)

    def ft(c):
        if c is None:
            return "--"
        v = c * 9 / 5 + 32 if unit == "F" else c
        return "{:.0f}".format(v)

    def fh(v):
        return "--" if v is None else "{:.0f}".format(v)

    pos = {
        "open": "OPEN",
        "closed": "CLOSED",
        "opening": "OPENING",
        "closing": "CLOSING",
        "unknown": "?",
    }.get(s["window"], "?")

    if C.LCD_ROWS >= 4:
        # 20x4: readings + every mode at a glance. "+" marks a live relay in AUTO.
        _row(
            lcd,
            0,
            "IN  {}{} {}%".format(ft(s["temp"]), unit, fh(s["humid"])),
            "AUTO" if s["auto"] else "MAN",
        )
        _row(lcd, 1, "OUT {}{} {}%".format(ft(s["out_temp"]), unit, fh(s["out_humid"])))
        _row(lcd, 2, "WIN {}".format(s["win_mode"]), pos)
        fanx = "+" if (s["vent"] or s["circ"]) else ""
        misx = "+" if s["mister"] else ""
        _row(
            lcd,
            3,
            "FAN {}{}".format(s["fan_mode"], fanx),
            "MIS {}{}".format(s["mis_mode"], misx),
        )
    else:
        # 16x2 on the built bezel: IN/OUT and the W/F/M button labels are printed ON
        # the bezel, so the LCD shows only data. Top row = four readings (inside left
        # half, outside right half). Bottom row = three mode fields, each centered in
        # its third directly ABOVE its button. Buttons L->R: red=window, white=fans,
        # blue=mister (matches this field order). The window field appends a position
        # glyph (O/C/>/<) so you can see the sash even while its mode is AUTO.
        half = C.LCD_COLS // 2
        inside = "{}{} {}%".format(ft(s["temp"]), unit, fh(s["humid"]))
        outside = "{}{} {}%".format(ft(s["out_temp"]), unit, fh(s["out_humid"]))
        _row(lcd, 0, inside.ljust(half) + outside)

        posg = {"open": "O", "closed": "C", "opening": ">", "closing": "<"}.get(
            s["window"], "?"
        )
        f_win = s["win_mode"] + posg
        f_fan = s["fan_mode"] + ("+" if (s["vent"] or s["circ"]) else "")
        if s["mis_mode"] == "TIM" and s["mis_left"] is not None:
            f_mis = "TIM{}".format(s["mis_left"])
        else:
            f_mis = s["mis_mode"] + ("+" if s["mister"] else "")
        base = C.LCD_COLS // 3
        rem = C.LCD_COLS % 3
        w0, w1, w2 = base, base + rem, base  # remainder to the middle field
        _row(lcd, 1, f_win.center(w0) + f_fan.center(w1) + f_mis.center(w2))


if __name__ == "__main__":
    main()
