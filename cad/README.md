# CAD / CNC — LCD + button bezel

Cutting the front panel that carries the 1602 LCD and the three buttons, on the
Anolex 4030 with the **spindle** (not the laser). This is a flat 2.5D part, so we
use the code-first CAM path from `~/src/vibes/cnc_vibes` (Workflow A) — **no
FreeCAD**.

## Files

| File | What it is |
|------|-----------|
| `lcd_button_bezel.scad` | The geometry / drawing (also the OpenBeam frame model). Source of truth for hole positions + panel size. |
| `bezel_cam.py` | Generates `build/bezel.gcode` from that geometry using `cnc_vibes/scripts/cam.py`. **Keep its constants in sync with the `.scad` by hand.** |
| `build/bezel.gcode` | Generated toolpath (git-ignored). |

## The part

180 × 100 mm panel, cut from ~3 mm plastic sheet, with **one bit — the 1/8″
(3.175 mm) 2-flute — for the whole job, no tool changes**:

- **4 × Ø3.4 mm** LCD mounting holes (M3 clearance)
- **10 × Ø4.0 mm** frame-mount holes (loose M3 = alignment slop to the 1515 extrusion)
- **3 × Ø7 mm** button holes (Twidec PBS-110)
- outer perimeter with **tabs**
- *(optional)* LCD viewing window — only if the material is too opaque to read through (`--lcd-window`)

Every hole is ≥ 1/8″ so the single bit can bore it. In plastic you want a
**2-flute (ideally single-flute "O-flute")** — many-flute bits don't clear
chips and melt/gum the cut. Cut order is holes → perimeter (perimeter last, with
tabs, so the freed part can't shift on the final pass).

## 0. Before you generate — decide two things

1. **Measure the sheet thickness** with calipers. "3 mm plastic" is often
   2.0–2.8 mm. Pass the real number as `--thickness-mm`.
2. **Clear or opaque?** If you can read the LCD through it (clear PET/acrylic),
   no window. If it's the tinted/semi-transparent acrylic, add `--lcd-window`.

Material note: for **milling**, plastic choice affects melt/chip behavior, not
safety (unlike lasering). PET/PETG is gummier/meltier than cast acrylic — same
recipe, just keep RPM low and feed up. The only sheet to avoid milling is rigid
PVC (acrid/chlorine smell while cutting = stop). Profiles live in
`cnc_vibes/profiles/materials.yaml` (`petg_3mm`, `acrylic_3mm`).

## 1. Generate the G-code

```bash
cd ~/src/greenhousebot
# needs shapely + pyyaml; uv pulls them in on the fly.
# clear read-through panel, cut from the PET sheet (measured 2.88 mm):
uv run --with shapely --with pyyaml python cad/bezel_cam.py \
    --material petg_3mm --thickness-mm 2.88

# opaque/tinted acrylic → also mill the LCD window (3 mm or 1/8"=3.18 mm stock):
uv run --with shapely --with pyyaml python cad/bezel_cam.py \
    --material acrylic_3mm --thickness-mm 3.0 --lcd-window
```

Your sheets: **PET 2.88 mm**, scavenged 2.99 mm (unknown — smell-test on scrap;
stop if it's acrid/chlorine = PVC), acrylic in 1/8″ (3.18 mm) and 3 mm. Clear PET
reads through → no window; the tinted acrylic needs `--lcd-window`.

Useful flags: `--spindle-rpm` (default 8000 = the low end, good for plastic),
`--small-tool` / `--main-tool` (swap in your real bit ids), `--tab-count`,
`--origin-margin-mm` (part inset from WCS origin, default 6).

## 2. Check it before cutting

```bash
cd ~/src/vibes/cnc_vibes
uv run --with pyyaml --with shapely python cnc.py validate  ~/src/greenhousebot/cad/build/bezel.gcode
uv run --with pyyaml --with shapely python cnc.py preview   ~/src/greenhousebot/cad/build/bezel.gcode   # CAMotics (if installed)
uv run --with pyyaml --with shapely python cnc.py preflight ~/src/greenhousebot/cad/build/bezel.gcode
```

`validate` must say **ok**. `preview` opens CAMotics for a 3D sim (optional —
skip if not installed). `preflight` walks the pre-cut checklist.

## 3. Stock + workholding

- **Stock size:** at least ~**195 × 115 mm** (part 180×100 + 6 mm origin margin +
  tool clearance). Bigger is fine — leave room to clamp.
- **Workholding:** you chose **tabs**, so the part stays bridged to the stock
  after cutting. Clamp the stock at the corners **outside the toolpath** (the cut
  reaches ~4.4 mm in from the stock edge at closest, plus your clamps must clear
  X 0–188 / Y 0–108 in WCS). Put a **sacrificial spoilboard** underneath — the
  cut goes 0.4 mm past the sheet.
- Tabs are ~0.5 mm thick bridges (6 on the perimeter). After the cut, score with
  a knife and snap the part free, then sand the stubs flush.

## 4. Tooling — one bit, no changes

| Section | Tool | Feed / RPM (PETG default) |
|---|---|---|
| LCD + mount holes (Ø3.4/4.0) | **1/8″ 2-flute** | 960 mm/min @ 8000 rpm, ~1.1 mm/pass |
| Button holes (Ø7) + profile+tabs | **1/8″ 2-flute** | 960 mm/min @ 8000 rpm, ~1.1 mm/pass |

The whole job runs on the **1/8″ (3.175 mm) 2-flute** — the small holes are all
≥ 1/8″ on purpose so there's **no tool change and no re-zeroing mid-cut**. Zero
once, run start to finish. (Your sub-1/8″ bits are many-fluted → they melt/gum
plastic, so they're not used here. A 1/8″ **single-flute** O-flute would cut
plastic even cleaner if you ever pick one up — swap it in with
`--main-tool <its id>` after adding it to `cnc_vibes/profiles/tools.yaml`.)

The file still has `; ===== ... =====` section markers, so you can pause/inspect
between operations — but you never need to touch the bit.

## 5. Zeroing (WCS)

- **X0 Y0 = the stock's bottom-left corner** (the part is inset 6 mm from it).
- **Z0 = top of the stock surface** (probe or paper-feeler).
- **Set GRBL to spindle mode: `$32=0`** before running (it's often left at `1`
  from laser jobs — the validator checks this, but set it on the machine too).

## 6. While cutting — watch for melting

Plastic's failure mode is melting/gumming, not force. If the edge re-welds or you
see stringing/dust instead of chips:

- RPM is already at the 8000 floor → **increase feed** (`--spindle-rpm` can't go
  lower; regenerate with a higher implied chipload by editing the material's
  chipload in `cnc_vibes/profiles/materials.yaml`), or **reduce depth per pass**.
- An air blast / dust shoe to clear chips helps a lot with PETG.
- **Test on the unknown recycled scrap first** to dial it in before the real sheet.

If it chips/cracks instead (brittle cast acrylic): slow the feed slightly and
make sure the bit is sharp.

## Keeping `.scad` and `bezel_cam.py` in sync

Both hard-code the same dimensions (panel 180×100, hole patterns, positions). If
you change one, change the other. This is a deliberate one-off, not a generic
pipeline — see the constants block at the top of `bezel_cam.py`.
