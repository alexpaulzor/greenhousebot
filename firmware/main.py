"""
Greenhouse controller — MicroPython entry point (Pico 2 W). MANUAL-ONLY MVP.

Behaviour:
  * 3 buttons single-press TOGGLE window / fans / mister.
  * LCD shows temp + humidity (+ status line).
  * LAN web page mirrors readings + status and offers remote toggles.
  * Every actuation and periodic sample is logged (in-RAM ring buffers, JSON at /data).
  * No automation yet — control.py is parked for the future two-sensor rules.

Structure: `Actions` is the single place that performs an actuation (from a button
OR the web) and logs it, so both input paths behave identically. The main loop is
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
                C.I2C1_ID, sda=Pin(C.PIN_SDA1), scl=Pin(C.PIN_SCL1), freq=C.I2C_FREQ
            )
            print("I2C1 devices:", [hex(a) for a in i2c1.scan()])
            out_sensor = AHT21(i2c1, C.ADDR_AHT21)
        except Exception as e:
            print("outdoor sensor init failed:", e)

    valve = Relay(C.PIN_RELAY_VALVE, C.RELAY_ACTIVE_HIGH)
    fans = Relay(C.PIN_RELAY_FANS, C.RELAY_ACTIVE_HIGH)
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
    actions = Actions(window, fans, valve, log, _clock, C.AUTOMATION_DEFAULT)
    controller = Controller()

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

        # buttons -> toggles (logged as source="manual")
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
                    fans=fans.is_on,
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


def _draw(lcd, actions):
    s = actions.status()

    def fx(v):
        return "--" if v is None else "{:.0f}".format(v)

    # Line 0: indoor + outdoor temp/humidity, e.g. "I25/60 O15/80"
    lcd.line(
        0,
        "I{}/{} O{}/{}".format(
            fx(s["temp"]), fx(s["humid"]), fx(s["out_temp"]), fx(s["out_humid"])
        ),
    )
    # Line 1: actuator status
    win = {"open": "O", "closed": "C", "opening": ">", "closing": "<", "unknown": "?"}
    lcd.line(
        1,
        "W:{} F:{} M:{}".format(
            win.get(s["window"], "?"),
            "1" if s["fans"] else "0",
            "1" if s["mister"] else "0",
        ),
    )


if __name__ == "__main__":
    main()
