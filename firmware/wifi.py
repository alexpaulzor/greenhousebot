"""
WiFi station connect + NTP time sync (MicroPython, Pico 2 W).

connect() is best-effort and non-fatal: if creds are missing or the AP is
unreachable, it returns None and the controller runs offline (buttons + LCD).
"""

import time


def connect(timeout_s=20):
    """Connect to WiFi in station mode. Returns the IP string on success, else None."""
    try:
        import network
        import secrets
    except ImportError:
        print("wifi: no secrets.py or no network module -> offline")
        return None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(hostname="greenhouse")
    except Exception:
        pass  # not all ports support hostname config
    if not wlan.isconnected():
        wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
                print("wifi: connect timeout -> offline")
                return None
            time.sleep_ms(200)
    ip = wlan.ifconfig()[0]
    print("wifi: connected", ip)
    return ip


def sync_time(host="pool.ntp.org"):
    """Best-effort NTP sync. Returns True on success."""
    try:
        import ntptime

        ntptime.host = host
        ntptime.settime()
        print("ntp: time synced")
        return True
    except Exception as e:
        print("ntp: sync failed", e)
        return False


def local_now(tz_offset_s):
    """Return (year, month, day, hour, minute, second) in LOCAL time.

    The RTC holds UTC (set by NTP). We apply the fixed tz offset here so the
    controller's season (month) and day/night (hour) are correct for the site.
    Works before NTP too — just returns the (wrong-but-monotonic) default epoch
    shifted by the offset, so nothing crashes; season is simply off until sync.
    """
    import time

    return time.localtime(time.time() + tz_offset_s)
