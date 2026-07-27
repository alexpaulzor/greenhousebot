# Firmware (MicroPython, Pico 2 W) — manual MVP

Manual-only greenhouse controller: 3 buttons toggle window / fans / mister, an LCD
shows readings, and a LAN web page mirrors it with remote toggles + a scrape API.
No automation yet — `control.py` is parked for the future two-sensor rules.

## Modules

| File | Role | Hardware? | Tested |
|------|------|-----------|--------|
| `config.py` | pins, addresses, sizes, timings | no | — |
| `aht21.py` | AHT21 sensor driver (I2C) | yes | on-device |
| `lcd.py` | HD44780 over PCF8574 backpack | yes | on-device |
| `actuators.py` | relays + BTS7960 window (toggle/pos state machine) | yes | on-device |
| `buttons.py` | 3 momentary buttons → toggle events | yes | on-device |
| `wifi.py` | station connect + NTP | yes | on-device |
| `webserver.py` | non-blocking HTTP socket loop | yes | on-device |
| `webapp.py` | **pure** request router + HTML page | no | `tests/test_webapp.py` |
| `datalog.py` | **pure** ring buffer + rotating-CSV persistence | no | `tests/test_datalog.py` |
| `fsadapter.py` | flash FS adapter for datalog | yes | (fake in tests) |
| `control.py` | **pure** automation brain (Maxillaria tenuifolia / WC, per `docs/RULES.md`) — PARKED, not wired in | no | `tests/test_control.py` |
| `main.py` | wiring + cooperative loop | yes | — |
| `secrets.py` | WiFi creds (gitignored; copy from `secrets_example.py`) | — | — |

The "pure" modules import no `machine`, so they run and are tested on desktop Python.

## Sensors: two AHT21s on two buses

AHT21's I2C address (0x38) is fixed, so two can't share a bus:
- **Indoor** AHT21 + LCD on **I2C0** (GP4/GP5)
- **Outdoor** AHT21 on **I2C1** (GP2/GP3)

Set `OUTDOOR_ENABLED = False` in `config.py` if the outdoor unit isn't wired yet.

## Buttons (single-press toggles)

- GP10 → **window** (open↔close; press while moving = stop)
- GP11 → **fans** on/off
- GP12 → **mister** on/off

## Web (LAN)

- `GET /` — control page (readings in/out + status + toggle buttons)
- `GET /status` — JSON snapshot
- `GET /data` — JSON of the in-RAM ring buffers (samples + events)
- `GET /data.csv`, `GET /events.csv` — CSV for scraping/analysis
- `POST /window|/fans|/mister` — toggle (or `?a=open|close|stop|on|off`)

## Data logging

- In-RAM ring buffers (`SAMPLE_RING`, `EVENT_RING`) always on — served via the web API.
- **Bounded flash persistence** (`LOG_PERSIST`): appends to `logs/samples.csv` and
  `logs/events.csv`, rotating at `LOG_FILE_MAX_BYTES`, keeping `LOG_FILE_KEEP`
  generations — so flash never fills. Samples carry indoor + outdoor readings; events
  carry the sensor context at the moment of each actuation. This is the dataset to
  scrape for later AI-driven automation rules.

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

```sh
python tests/test_control.py
python tests/test_datalog.py
python tests/test_webapp.py
```

## Roadmap (deferred)

- Automation using indoor **vs** outdoor comparison (wire up `control.py`, extend rules).
- Web charting of the logged data.
- Optional: stall detection via the BTS7960 IS pin (GP26) instead of pure timed moves.
