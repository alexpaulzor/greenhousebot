# Firmware (MicroPython, Pico 2 W)

Live greenhouse controller: **automation is on** (`control.py` drives each actuator when
it's in AUTO mode), 3 buttons **cycle** each actuator's mode (window / fans / mister), an
LCD shows readings, and a LAN web page mirrors it with remote mode changes, a scrape API,
and a canvas timeline chart. Every actuator has AUTO + manual modes; AUTO hands it to the
controller, any other mode is a manual override the controller leaves alone.

## Modules

| File | Role | Hardware? | Tested |
|------|------|-----------|--------|
| `config.py` | pins, addresses, sizes, timings | no | — |
| `aht21.py` | AHT21 sensor driver (I2C) | yes | on-device |
| `lcd.py` | HD44780 over PCF8574 backpack | yes | on-device |
| `actuators.py` | relays + BTS7960 window (open/close/pos state machine) | yes | on-device |
| `buttons.py` | 3 momentary buttons → mode-cycle events | yes | on-device |
| `wifi.py` | station connect + NTP | yes | on-device |
| `webserver.py` | non-blocking HTTP socket loop | yes | on-device |
| `webapp.py` | **pure** request router + HTML page | no | `tests/test_webapp.py` |
| `datalog.py` | **pure** ring buffer + rotating-CSV persistence | no | `tests/test_datalog.py` |
| `fsadapter.py` | flash FS adapter for datalog | yes | (fake in tests) |
| `actions.py` | **pure** actuator dispatch (mode → device) + logging | no | `tests/test_actions.py` |
| `settings.py` | **pure** web-adjustable tuning store (defaults + validation + persistence) | no | `tests/test_settings.py` |
| `control.py` | **pure** automation brain (Maxillaria tenuifolia / WC, per `docs/RULES.md`) — live behind each actuator's AUTO mode | no | `tests/test_control.py` |
| `main.py` | wiring + cooperative loop | yes | — |
| `secrets.py` | WiFi creds (gitignored; copy from `secrets_example.py`) | — | — |

The "pure" modules import no `machine`, so they run and are tested on desktop Python.

## Sensors: two AHT21s on two buses

AHT21's I2C address (0x38) is fixed, so two can't share a bus:
- **Indoor** AHT21 + LCD on **I2C0** (GP4/GP5)
- **Outdoor** AHT21 on **I2C1** (GP2/GP3)

Set `OUTDOOR_ENABLED = False` in `config.py` if the outdoor unit isn't wired yet.

## Buttons (single-press cycles the mode)

Each press advances that actuator through its mode ring (see `docs/RULES.md`):

- GP10 → **window**: AUTO → OFF → OPN → CLS
- GP11 → **fans**: AUTO → OFF → VNT → CIR → ALL
- GP12 → **mister**: AUTO → OFF → ON → TIM

**AUTO** hands the actuator to `control.py`; any other mode is a manual override the
controller leaves alone (manual is **raw** — it bypasses the temp gate). Buttons L→R on the
bezel are red/white/blue = window/fans/mister.

## Web (LAN)

- `GET /` — control page: in/out readings, a **per-actuator mode selector** (the same rings
  the buttons cycle), an **automation master** on/off, and a **canvas timeline chart** (temp
  in/out + humidity in/out lines, plus vent/circ/window/mister state bars). No external JS
  libs — works with no internet.
- `GET /status` — JSON snapshot (per-actuator modes + states, `auto`, `unit`). **`temp`/
  `out_temp` are always Celsius**; `unit` ("F"/"C") tells the client how to display them.
- `GET /data` — JSON of the in-RAM ring buffers (samples + events)
- `GET /data.csv`, `GET /events.csv` — CSV for scraping/analysis
- `POST /window` — cycle window mode (or `?a=AUTO|OFF|OPN|CLS`)
- `POST /fans` — cycle fans mode (or `?a=AUTO|OFF|VNT|CIR|ALL`)
- `POST /mister` — cycle mister mode (or `?a=AUTO|OFF|ON|TIM`)
- `POST /auto` — toggle the automation master (or `?a=on|off`)
- `GET /settings` — JSON specs + current values of the web-adjustable tuning settings
- `POST /settings?key=value&...` — update settings; returns fresh specs + what applied

## Settings (web-adjustable, reboot-persistent)

The behavioural tuning knobs live in `settings.py` as one ordered `SPEC` list that is the
single source of truth for **defaults** (pulled from `config.py`/`control.py` so nothing is
duplicated), **validation** (each entry's type + range/choices), and the **web UI** (the
`&#9881; Settings` panel renders straight from `GET /settings`). What's adjustable:

- **Seasonal setpoints** — growing + winter-rest: day ceiling, night band hi/lo, humidity
  floor/ceiling, cold-protect close.
- **Safety** — hard-freeze lockout, heat emergency.
- **Venting** — auto-vent open temp (the vent-fan gate), outside-cooler margin.
- **Circulation** — hourly period + run length.
- **Misting** — burst on / gap / TIM-button minutes.
- **Schedule** — day/night start hours. **Display** — °F/°C.

Edits are validated (numbers clamped to range, junk/unknown keys ignored, and a few
low/high pairs are order-guarded — e.g. `day_start` must stay before `night_start`, or a
fat-finger would make it "always night" and disarm daytime cooling; the offending change
just snaps back). They apply **live** (the controller reads the store each tick — no
reboot) and persist **atomically** (temp file + rename) to `settings.json` on flash,
overlaid on the defaults at next boot. The pins / I2C / log-size / WiFi / PWM constants
stay fixed in `config.py` on purpose — build-time, not day-to-day tuning.

## Temperature units

Everything internal is **Celsius** — sensors, dew-point math, and the control rules
(`RULES.md` setpoints). `TEMP_UNIT` in `config.py` (default `"F"`) only changes what
humans see: the **LCD**, the **web readings**, and the **chart axis** convert to °F.
The `/data` JSON and both CSV exports stay Celsius on purpose — one canonical unit for
the dataset you'll scrape/analyze. Set `TEMP_UNIT = "C"` to display Celsius instead.

## Automation

- Two gates: the **automation master** (`AUTOMATION_DEFAULT`, boots off) **and** each
  actuator's mode. An actuator is auto-driven only when the master is on **and** that
  actuator is in **AUTO**.
- When the master is on, the loop evaluates `control.py` every `AUTO_TICK_MS` using **local**
  time (season + day/night) and applies the decision to every AUTO actuator, logging only
  actual changes (`src=auto`).
- A manual mode (anything but AUTO) is an override the controller never touches — set via
  button or web. Manual is **raw**: it skips the temp gate that AUTO applies to the vent fan.
- Turning the master off freezes everything at its last state; flip individual actuators to
  AUTO to hand just those back to the controller.

## Data logging

- In-RAM ring buffers (`SAMPLE_RING`, `EVENT_RING`) always on — served via the web API.
- **Bounded flash persistence** (`LOG_PERSIST`): appends to `logs/samples.csv` and
  `logs/events.csv`, rotating at `LOG_FILE_MAX_BYTES`, keeping `LOG_FILE_KEEP`
  generations — so flash never fills. **Samples** carry indoor + outdoor readings **plus
  actuator state** (`vent,circ,mist,win` as 1/0) so the chart can draw on/open bars and the
  dataset is self-contained; **events** carry the sensor context at each actuation. This
  is the dataset to scrape for later AI-driven automation rules.

## Flash to the Pico

1. Install MicroPython for the Pico 2 W (RP2350) from micropython.org.
2. Copy WiFi creds: `cp firmware/secrets_example.py firmware/secrets.py` and edit.
3. Copy every `firmware/*.py` to the Pico root (e.g. with `mpremote` or Thonny):
   ```sh
   mpremote connect auto fs cp firmware/*.py :
   ```
4. It runs `main.py` on boot (or `import main; main.main()` from the REPL).
5. Watch the REPL for the `web: http://<ip>/` line, or find it via your router.

## Run the tests (desktop)

All five pure-module suites run on desktop Python (no `machine` import) — **68 tests**:

```sh
python tests/test_control.py
python tests/test_actions.py
python tests/test_datalog.py
python tests/test_webapp.py
python tests/test_settings.py
```

## Roadmap (deferred)

- Threshold **hysteresis** (deadbands) if the logs show actuator chatter at a setpoint.
- Optional: stall detection via the BTS7960 IS pin (GP26) instead of pure timed moves.
