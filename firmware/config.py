"""
Hardware + behaviour configuration for the greenhouse controller (manual MVP).

Pins follow docs/PINOUT.md exactly. This is a MANUAL-ONLY build: 3 buttons toggle
window/fans/mister, an LCD shows temp/humidity, and a LAN web page mirrors that with
remote toggles. No automation yet (see control.py, parked for the future two-sensor
rules).

Import-safe on CPython (no `machine` import) so tests can read it.
"""

# --- I2C bus 0: indoor AHT21 sensor + PCF8574 LCD (both 3.3 V) ------------
I2C_ID = 0
PIN_SDA = 4  # GP4  (physical 6)
PIN_SCL = 5  # GP5  (physical 7)
I2C_FREQ = 100_000
ADDR_AHT21 = 0x38
ADDR_LCD = 0x27  # try 0x3F if 0x27 doesn't respond

# --- I2C bus 1: OUTDOOR AHT21 (own bus — AHT21 addr 0x38 is fixed, so two of
#     them cannot share one bus; the outdoor unit gets its own I2C peripheral) --
# This bus runs a LONG cable (>3 m). Use a twisted pair for SDA/SCL, external
# ~2.2 kΩ pull-ups at the Pico end, and a slower clock for capacitance margin.
I2C1_ID = 1
PIN_SDA1 = 2  # GP2  (physical 4)
PIN_SCL1 = 3  # GP3  (physical 5)
I2C1_FREQ = 50_000  # half-speed for the long outdoor run (more capacitance margin)
OUTDOOR_ENABLED = True  # set False if the outdoor sensor isn't wired yet

# --- Relays (native 3.3 V, active-high IN on most 2-ch boards) ------------
# If your board is active-LOW ("low-level trigger"), set RELAY_ACTIVE_HIGH=False.
PIN_RELAY_VALVE = 16  # GP16 -> relay IN1 (mister valve)
PIN_RELAY_FANS = 17  # GP17 -> relay IN2 (dry-contact mains trigger)
RELAY_ACTIVE_HIGH = True

# --- Window: BTS7960 H-bridge (actuator has internal endstops) ------------
PIN_WIN_RPWM = 18  # GP18 open
PIN_WIN_LPWM = 19  # GP19 close
PIN_WIN_EN = 20  # GP20 R_EN + L_EN (tied)
PIN_WIN_IS = 26  # GP26/ADC0 current sense (optional; None to disable)
WIN_PWM_FREQ = 20_000  # Hz, above audible
WIN_DUTY = 0.9  # 0..1 drive duty while moving
# Time to drive fully open<->closed. The actuator's own endstops stop travel, so
# WIN_TRAVEL_MS just needs to be >= real travel time; overshoot is harmless.
WIN_TRAVEL_MS = 12_000  # MEASURE yours and set a bit above it

# --- Buttons: 3 momentary, each a single-press TOGGLE --------------------
# GP10 = window (open<->close, press-while-moving = stop), GP11 = fans, GP12 = mister.
PIN_BTN_WINDOW = 10  # GP10
PIN_BTN_FANS = 11  # GP11
PIN_BTN_MISTER = 12  # GP12
BTN_DEBOUNCE_MS = 40

# --- LCD geometry --------------------------------------------------------
LCD_COLS = 16
LCD_ROWS = 2

# --- Display units -------------------------------------------------------
# Temperatures are stored/computed in Celsius (sensors, dew point, rules). This
# only changes what HUMANS see (LCD + web + chart axis). "F" or "C".
# Note: /data and the CSV exports stay in Celsius (canonical dataset for scraping).
TEMP_UNIT = "F"

# --- Timing --------------------------------------------------------------
SAMPLE_MS = 2000  # how often to read the sensor + refresh LCD
LOG_SAMPLE_MS = 60_000  # how often to push a temp/humidity sample to the ring buffer

# --- Automation ----------------------------------------------------------
# Whether the control rules run at boot. Toggle at runtime via the web (POST
# /auto) or a long-press gesture later. When off, the system is fully manual.
AUTOMATION_DEFAULT = False  # ship manual-first; flip on from the web when ready
AUTO_TICK_MS = 5000  # how often the control rules evaluate

# --- Data log sizes (in-RAM ring buffers) --------------------------------
SAMPLE_RING = 240  # ~4 h at 60 s/sample
EVENT_RING = 100  # last N interventions (button/web actuations)

# --- Data log persistence (bounded files on the Pico flash) --------------
# Samples + events are appended to CSV files that ROTATE at LOG_FILE_MAX_BYTES,
# keeping LOG_FILE_KEEP generations so the log never grows without bound.
LOG_PERSIST = True
LOG_DIR = "logs"
LOG_FILE_MAX_BYTES = 64 * 1024  # per file before rotation
LOG_FILE_KEEP = 4  # rotated generations kept (oldest deleted)

# --- Web server ----------------------------------------------------------
WEB_PORT = 80
HOSTNAME = "greenhouse"  # mDNS-ish hostname hint (best effort)

# --- WiFi ----------------------------------------------------------------
# Credentials live in secrets.py (gitignored). See secrets_example.py.
NTP_HOST = "pool.ntp.org"
# Local time offset from UTC, in seconds. NTP gives UTC; the controller needs
# LOCAL time so "night" and "season" are right for Walnut Creek.
#   PST (winter, Nov-Mar) = -8 h = -28800
#   PDT (summer, Mar-Nov) = -7 h = -25200   <- current default
# A fixed offset is fine here: a 1-hour DST error only nudges the day/night edge
# slightly and never affects the month/season boundary. Flip it twice a year if
# you want day/night exact, or leave it — the rules are robust to ~1 h.
TZ_OFFSET_S = -25200
