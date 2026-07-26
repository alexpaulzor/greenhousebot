# greenhousebot

Controller for a greenhouse: temperature/humidity-driven **misters** (12 V valve),
**fans** (mains, switched externally), and **window** (12 V linear actuator via
H-bridge), on a **Raspberry Pi Pico 2 W** with a 1602 LCD + 3 buttons.

## Architecture (current)

- **Pico 2 W** brain; pre-made modules for relay / H-bridge / buck / LCD / AHT21 sensor.
- **No PCB — solderless terminal-block build.** The circuit is power-rail fan-out + a
  2-wire I2C bus, so a **Pico screw-terminal expander** + **Wago lever-nuts** do the
  interconnect. Nothing sensitive is soldered. See **[docs/WIRING.md](docs/WIRING.md)**.
- **Mains AC never enters the box**: the Pico closes a dry-contact relay that drives a
  separate, properly-rated external outlet box for the fans.
- **Single 12 V 5 A PSU** → valve + H-bridge + a buck to 5 V for the Pico.
- **Sensor**: AHT21 (I2C 0x38). **LCD run at 3.3 V** → whole I2C bus is 3.3 V, **no
  level shifter**.
- **Buttons**: your panel-mount momentary buttons wire in via screw terminals.
- **Housing**: a purchased sealed plastic bin, mounted outdoors by the door, one gland.
  (Swappable LCD faceplate + MakerBeam module mounts are deferred TODOs.)

## Documents (start here)

| Doc | What |
|-----|------|
| [docs/CONNECTIONS.md](docs/CONNECTIONS.md) | **Logical pin-to-pin** (mermaid + table) — start here |
| [docs/WIRING.md](docs/WIRING.md) | **Solderless build guide** (buses, terminals, bring-up) |
| [docs/BOM.md](docs/BOM.md) | Bill of materials + sizing |
| [docs/PINOUT.md](docs/PINOUT.md) | Pico GPIO assignments (single source of truth) |

## Status

- [x] BOM finalized (AHT21, no level shifter, 12 V 5 A, terminal-block build)
- [x] Pin mappings finalized
- [x] Connectivity / circuit (logical) — `docs/CONNECTIONS.md`
- [x] Interconnect decided: **no PCB**, solderless terminal blocks — `docs/WIRING.md`

### Deferred TODOs
- Firmware (MicroPython) — control logic, menu, PWM for the actuator, I2C for AHT21 + LCD.
- Laser-cut swappable LCD/button faceplate (1602 now, 2004 later).
- MakerBeam (15×15) module-mount plates.
- Confirm whether the window actuator has internal limit switches (else use GP13/14/15).

---

## `pcb/` + `kicad/` — superseded PCB tooling (reference only)

An earlier direction was a milled single-sided carrier PCB. We **dropped the PCB** once
the parts became modular/socketed (a breakout is all that's needed). This tooling is kept
as a **learning artifact**, not part of the build:

- `pcb/*.py` — a from-scratch, reproducible PCB toolchain (footprints → placement →
  netlist → maze router → **polygon DRC gate** → GRBL post). The DRC refused to emit
  shorting G-code, which is what surfaced that a dense single-sided board was marginal.
- `kicad/greenhousebot.kicad_pcb` — a pcbnew-API-generated board. **Note:** it opens via
  the CLI/DRC but **crashes the KiCad GUI** because its custom Pico footprint isn't backed
  by a library table entry (a known limitation of API-built boards). Not worth fixing since
  the PCB is dropped; don't rely on these files for the build.

`CIRCUIT.md` and `KICAD_SETUP.md` document that earlier PCB path.
