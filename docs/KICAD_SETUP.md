# KiCad Setup — milling the carrier board

You chose the KiCad path for the PCB. There are now **two** ways in; use the first.

## 0. Ready-made board (recommended)

`pcb/build_kicad.py` builds a complete, **DRC-clean** `kicad/greenhousebot.kicad_pcb`
directly via KiCad's `pcbnew` API — real footprints, a **custom Pico footprint with
correct physical pin numbering**, all nets assigned, board outline, and a B.Cu GND
zone. Just open it and route.

```sh
KCPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
"$KCPY" pcb/build_kicad.py            # -> kicad/greenhousebot.kicad_pcb
kicad-cli pcb drc kicad/greenhousebot.kicad_pcb   # 0 violations (48 unconnected = ratsnest)
```

Footprints are **shelf-packed** with clearance (a legal starting arrangement) — drag
them into your preferred layout, then route. The custom Pico footprint means U1's pad
numbers already match `docs/PINOUT.md`, so **the pin-numbering gotcha below does NOT
apply to this path.**

Regenerate any time the netlist/layout changes; re-run DRC to confirm clean.

---

## 1. Alternative: import the netlist (only if you want to start from scratch)

1. New project in KiCad → open **Pcbnew** (the board editor).
2. **File → Import → Netlist…** → select `greenhousebot.net`.
3. KiCad drops all footprints stacked at the origin. Spread them out and place.
4. Footprints resolve from **stock libraries** (PinHeader, TerminalBlock_Phoenix,
   Resistor_THT, Capacitor_THT, Button_Switch_THT, Diode_THT) so no custom libs
   are required.

### ⚠️ The one gotcha: the Pico footprint + pin mapping

- `netlist.py` names Pico pads by **physical pin number** (6=GP4, 7=GP5, 20=GP15…).
- The seed maps U1 to a stock **PinHeader_2x20** whose pads number 1→40 down one
  row then continue — which is **not** the Pico's physical pin order (Pico numbers
  1–20 down the left, 21–40 up the right… actually 1-20 left top-to-bottom, 21-40
  right bottom-to-top). **Verify U1 pad numbers against the Pico pinout after import**
  and fix any mismatch, or install a proper Raspberry Pi Pico footprint library
  (e.g. the `RPi_Pico` library) and re-assign U1 to it before routing.
- This is exactly the kind of silent error a milled board can't tolerate, so
  double-check U1's ratsnest against `docs/PINOUT.md` before routing.

## 2. Net classes (for V-bit isolation milling)

KiCad applies net classes in **File → Board Setup → Net Classes**. Set:

| Class | Nets | Track width | Clearance |
|-------|------|-------------|-----------|
| Power | 12V, 5V_BUCK, 5V_VSYS, 3V3, VALVE_SW | 0.8 mm | 0.3 mm |
| Default (signal) | everything else | 0.4 mm | 0.3 mm |

- **Clearance 0.3 mm** is comfortable for a V-bit (0.2 mm tip). Tighten to 0.25 mm
  only if your mill/leveling is dialed in.
- Single-sided: route **everything on B.Cu (bottom copper)**. Use the front copper
  only for the occasional wire jumper, or place explicit jumper wires.
- Add a **GND copper pour (filled zone) on B.Cu** covering the whole board — this is
  your ground plane; every GND pad connects to it, matching the milled-pour design.

## 3. Design-rule check

Run **Inspect → Design Rules Checker**. Zero clearance errors before export.
This replaces the Python DRC gate — KiCad's is authoritative from here on.

## 4. Export G-code for the GRBL mill

KiCad doesn't emit isolation G-code directly; use one of:

**Option A — via Gerbers + a CAM tool (recommended, most control):**
1. **File → Plot** → plot **B.Cu** and **Edge.Cuts** as Gerber; **File →
   Fabrication Outputs → Drill Files** for the Excellon drill file.
2. Feed those into **FlatCAM** or **pcb2gcode**:
   - Isolation: V-bit, 1 pass (or 2 for wider isolation), cut depth 0.05–0.10 mm.
   - Drill: 0.9 mm bit (matches `PAD_D` drills).
   - Cutout: 1.6 mm endmill, tabs on.
3. Post to GRBL dialect. Load in Candle/bCNC/UGS.

**Option B — reuse this repo's CAM for reference geometry:**
The `pcb/cam.py` GRBL post (feeds/depths/tabs) is a working reference for your
machine parameters even if you route in KiCad — copy the header/feeds into FlatCAM.

## 5. Machine parameters (starting points — tune to your mill)

From `pcb/cam.py`, proven to generate valid GRBL:

```
V-bit tip           0.2 mm
Isolation depth     0.05–0.10 mm
Drill bit           0.9 mm,  depth 1.9 mm (through 1.6 mm board)
Cutout endmill      1.6 mm,  depth 2.0 mm, 0.5 mm/pass, 4 tabs
Safe Z              3.0 mm
Feeds               XY 120, plunge 40, drill 30 mm/min
Spindle             12000 rpm
```

**Always** surface-level your copper (auto-level / height map in bCNC or a
leveling probe) before isolation milling — copper-clad is never flat enough for a
V-bit at 0.05 mm depth without it.
