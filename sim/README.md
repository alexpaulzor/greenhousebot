# Simulator — run the greenhouse UI locally, no hardware

Runs the **real** firmware web logic (`webapp.route`, `Actions`, `DataLog`,
`Controller`) against fake sensors/actuators, so you can view and click the control
page in your browser with generated history — no Pico, no wiring.

## Run

```sh
python sim/simulate.py                       # http://localhost:8080
python sim/simulate.py --port 9000 --hours 12 --speed 120
```

Then open the URL. The page is the exact one the device serves: live temp/humidity
in+out, actuator toggles, an automation on/off switch, and the timeline chart. It
updates as the simulated greenhouse evolves.

Options:
- `--hours N` — hours of history pre-seeded into the chart on startup (default 6).
- `--speed N` — sim-minutes advanced per real second (default 60, i.e. 1 h/min).
- `--port P` — listen port (default 8080).

## What it exercises

- **Real** request routing, action + logging code, and control rules — a bug here is
  a bug on the device.
- Fake sensors that **respond to the actuators**: opening the window / running fans
  pulls inside toward outside; the mister raises humidity. So toggling things (or
  letting automation run) visibly changes the chart.
- Log entries are tagged by source — `auto` (controller), `web` (this page's buttons),
  and `manual` would be a physical panel button on the real device.

## Screenshot without a browser window

```sh
python sim/simulate.py --port 8099 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --window-size=680,900 \
  --screenshot=page.png --virtual-time-budget=3000 http://localhost:8099/
```

## Not simulated

WiFi/NTP, the LCD, and real actuator timing (the fake window is instant, not a timed
move). Those are device-only; the sim is for the UI, data, and control logic.
