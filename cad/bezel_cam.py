#!/usr/bin/env python3
"""Generate GCode to mill the LCD + button bezel (see lcd_button_bezel.scad).

Uses the code-first CAM library from ~/src/vibes/cnc_vibes (Workflow A — no
FreeCAD). Composes cam.py ops into one file, in cut order:

  1. small holes  (4x 3.4mm LCD + 10x 4.0mm frame-mount) bored to size
     -> pocket_mill
  2. button holes (3x 7mm)                                 -> pocket_mill
  3. outer perimeter WITH TABS                             -> profile_cut_with_tabs

Everything is cut with a SINGLE 1/8" (3.175mm) 2-flute — no tool changes. All
holes are >= 1/8" so the one bit can bore them; a 2-flute (or single-flute) is
what you want in plastic (many-flute bits melt/gum the cut). Holes come before
the perimeter so the part stays anchored; the perimeter is last and leaves tabs
so the freed part can't move on the final pass.

Geometry MIRRORS lcd_button_bezel.scad — keep the two in sync by hand (this is
a one-off part, not a generic pipeline). WCS origin = the part's bottom-left
corner, Z0 = top of stock.

    python cad/bezel_cam.py                       # defaults (PETG, 3mm)
    python cad/bezel_cam.py --thickness-mm 2.6    # your measured sheet
    python cad/bezel_cam.py --material acrylic_3mm --spindle-rpm 8000

Then, from the cnc_vibes repo:
    python cnc.py validate  <path>   # envelope / feed / spindle-mode lint
    python cnc.py preview   <path>   # CAMotics 3D sim — SEE it before cutting
    python cnc.py preflight <path>   # interactive pre-cut checklist
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from shapely.geometry import Point, box
from shapely.affinity import translate

# --- locate the cnc_vibes CAM toolchain (sibling repo) ----------------------
CNC_VIBES = Path(
    os.environ.get("CNC_VIBES_DIR", Path.home() / "src" / "vibes" / "cnc_vibes")
)
if not (CNC_VIBES / "scripts" / "cam.py").exists():
    sys.exit(f"cannot find cnc_vibes at {CNC_VIBES}. Set CNC_VIBES_DIR to its path.")
sys.path.insert(0, str(CNC_VIBES / "scripts"))

from cam import (  # noqa: E402
    CamConfig,
    GcodeOutput,
    load_material,
    load_tool,
    pocket_mill,
    profile_cut_with_tabs,
)

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_DIR = SCRIPT_DIR / "build"

# ---------------------------------------------------------------------------
# Bezel geometry — MIRROR of lcd_button_bezel.scad (keep in sync)
# ---------------------------------------------------------------------------
PANEL_W = 180.0
PANEL_H = 100.0
CORNER_R = 4.0

LCD_CX, LCD_CY = PANEL_W / 2, 60.0
LCD_HOLE_DX, LCD_HOLE_DY = 75.0, 31.0
LCD_HOLE_D = 3.4  # M3 clearance; >= 1/8" so the single 1/8" bit bores it

BTN_CX, BTN_CY = PANEL_W / 2, 30.0
BTN_COUNT = 3
BTN_SPACING = 32.0
BTN_HOLE_D = 7.0  # Twidec PBS-110 panel hole

BEAM_W = 15.0
MOUNT_INSET = BEAM_W / 2  # 7.5
MOUNT_HOLE_D = 4.0  # loose M3 clearance = alignment slop to the 1515 frame

# LCD viewing window (only cut when the material is too opaque to read through).
# Sized to a standard 1602 metal-bezel opening, centered on the mounting pattern.
LCD_WINDOW_W, LCD_WINDOW_H, LCD_WINDOW_R = 71.5, 25.5, 1.5


def _lcd_holes() -> list[tuple[float, float]]:
    return [
        (LCD_CX + sx * LCD_HOLE_DX / 2, LCD_CY + sy * LCD_HOLE_DY / 2)
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]


def _button_holes() -> list[tuple[float, float]]:
    return [
        (BTN_CX + (i - (BTN_COUNT - 1) / 2) * BTN_SPACING, BTN_CY)
        for i in range(BTN_COUNT)
    ]


def _mount_holes() -> list[tuple[float, float]]:
    xs = [
        MOUNT_INSET,
        MOUNT_INSET + BEAM_W,
        PANEL_W / 2,
        PANEL_W - MOUNT_INSET - BEAM_W,
        PANEL_W - MOUNT_INSET,
    ]
    ys = [MOUNT_INSET, PANEL_H - MOUNT_INSET]
    return [(x, y) for x in xs for y in ys]


def _circle(cx: float, cy: float, dia: float):
    return Point(cx, cy).buffer(dia / 2, quad_segs=32)


def _strip_op(lines: list[str]) -> list[str]:
    """Reduce a standalone cam.py op to just its motion + inline comments.

    Each cam.py op is a complete program: a spindle preamble ($32/G21/G90/G94/
    G0 Zsafe/M3) then motion then a footer (G0 Zsafe/M5/G0 X0 Y0). To stitch
    many ops into ONE program we keep only the middle: everything after the
    M3 spindle-on line, up to (not including) the closing M5. The op's own
    final safe-Z retract is preserved, so the tool still lifts between ops.
    """
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("M3"):  # spindle-on ends the preamble
            start = i + 1
            break
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    end = len(lines)
    for i in range(len(lines) - 1, start - 1, -1):
        if lines[i].startswith("M5"):  # spindle-off begins the footer
            end = i
            break
    # Drop the footer's own retract (G0 Zsafe) + blank that precede M5, so we
    # don't accumulate a double retract; the op's real last retract remains.
    if end - 1 >= start and lines[end - 1].startswith("G0 Z"):
        end -= 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    return lines[start:end]


def _rounded_panel():
    # box shrunk by r, then buffered by r -> outer dims PANEL_W x PANEL_H,
    # rounded corners of radius CORNER_R (matches the .scad rrect()).
    return box(CORNER_R, CORNER_R, PANEL_W - CORNER_R, PANEL_H - CORNER_R).buffer(
        CORNER_R, quad_segs=16
    )


def _lcd_window_poly():
    r = LCD_WINDOW_R
    w, h = LCD_WINDOW_W, LCD_WINDOW_H
    return box(
        LCD_CX - w / 2 + r,
        LCD_CY - h / 2 + r,
        LCD_CX + w / 2 - r,
        LCD_CY + h / 2 - r,
    ).buffer(r, quad_segs=16)


def make_bezel_gcode(
    thickness_mm: float = 3.0,
    through_overcut_mm: float = 0.4,
    material_id: str = "petg_3mm",
    small_tool_id: str = "flat_3.175mm_2flute",
    main_tool_id: str = "flat_3.175mm_2flute",
    spindle_rpm: int = 8000,
    tab_count: int = 6,
    tab_width_mm: float = 6.0,
    tab_bridge_mm: float = 0.5,
    lcd_window: bool = False,
    origin_margin_mm: float = 6.0,
    strict: bool = False,
) -> GcodeOutput:
    material = load_material(material_id)
    small_tool = load_tool(small_tool_id)
    main_tool = load_tool(main_tool_id)
    cfg = CamConfig(safe_z_mm=5.0, spindle_rpm=spindle_rpm, strict=strict)

    hole_depth = thickness_mm + through_overcut_mm
    # Tabs remain tab_bridge_mm of material after the through cut.
    tab_height = through_overcut_mm + tab_bridge_mm

    # WCS origin sits at the stock's bottom-left; the part is inset by this
    # margin so the outside-profile pass stays fully positive (no running off
    # the stock edge / into a corner clamp). Labels below stay in PART coords.
    ox = oy = origin_margin_mm

    def oc(cx, cy, dia):  # offset circle at a part coordinate
        return _circle(cx + ox, cy + oy, dia)

    sections: list[tuple[str, str, GcodeOutput]] = []

    # --- Section 1: small holes (LCD 3.4mm, mount 4.0mm) -------------------
    for cx, cy in _lcd_holes():
        sections.append(
            (
                f"LCD hole {LCD_HOLE_D}mm @ ({cx:.1f},{cy:.1f})  [TOOL: {small_tool_id}]",
                small_tool_id,
                pocket_mill(
                    oc(cx, cy, LCD_HOLE_D),
                    depth_mm=hole_depth,
                    tool=small_tool,
                    material=material,
                    cfg=cfg,
                ),
            )
        )
    for cx, cy in _mount_holes():
        sections.append(
            (
                f"mount hole {MOUNT_HOLE_D}mm @ ({cx:.1f},{cy:.1f})  [TOOL: {small_tool_id}]",
                small_tool_id,
                pocket_mill(
                    oc(cx, cy, MOUNT_HOLE_D),
                    depth_mm=hole_depth,
                    tool=small_tool,
                    material=material,
                    cfg=cfg,
                ),
            )
        )

    # --- Section 2: button holes with the 1/8" endmill ---------------------
    for cx, cy in _button_holes():
        sections.append(
            (
                f"button hole 7mm @ ({cx:.1f},{cy:.1f})  [TOOL: {main_tool_id}]",
                main_tool_id,
                pocket_mill(
                    oc(cx, cy, BTN_HOLE_D),
                    depth_mm=hole_depth,
                    tool=main_tool,
                    material=material,
                    cfg=cfg,
                ),
            )
        )

    # --- Section 2b: LCD viewing window (inside cut + tabs) — only for opaque
    #     material. Cut before the outer profile so the part stays anchored;
    #     tabs keep the waste slug from dropping loose mid-cut. 1/8" tool. -----
    if lcd_window:
        sections.append(
            (
                f"LCD WINDOW {LCD_WINDOW_W}x{LCD_WINDOW_H}mm  [TOOL: {main_tool_id}]",
                main_tool_id,
                profile_cut_with_tabs(
                    translate(_lcd_window_poly(), ox, oy),
                    depth_mm=hole_depth,
                    tab_count=4,
                    tab_width_mm=4.0,
                    tab_height_mm=tab_height,
                    tool=main_tool,
                    material=material,
                    side="inside",
                    cfg=cfg,
                ),
            )
        )

    # --- Section 3: outer perimeter with tabs, 1/8" endmill (LAST) ---------
    sections.append(
        (
            f"OUTER PROFILE + tabs  [TOOL: {main_tool_id}]",
            main_tool_id,
            profile_cut_with_tabs(
                translate(_rounded_panel(), ox, oy),
                depth_mm=hole_depth,
                tab_count=tab_count,
                tab_width_mm=tab_width_mm,
                tab_height_mm=tab_height,
                tool=main_tool,
                material=material,
                side="outside",
                cfg=cfg,
            ),
        )
    )

    # --- Assemble ONE continuous spindle program -------------------------
    # cam.py emits each op as a standalone program (its own $32/G21/M3 ... M5
    # /return-to-origin). Concatenating those verbatim restarts the spindle and
    # rapids home between every hole, and the bare `$32=` GRBL setting is not
    # valid RS-274 (CAMotics chokes on it). So we emit a single preamble, strip
    # each op down to motion, and close with a single footer.
    lines: list[str] = [
        "; Greenhouse LCD+button bezel — generated by cad/bezel_cam.py",
        f"; material={material_id} thickness={thickness_mm}mm rpm={spindle_rpm}",
        f"; WCS origin = STOCK bottom-left, Z0 = top of stock. Part inset "
        f"{origin_margin_mm}mm; labels are in part coords (add the margin).",
    ]
    if small_tool_id != main_tool_id:
        lines.append(
            "; TOOL CHANGE mid-job: swap "
            f"{small_tool_id} -> {main_tool_id} at the M0 pause, then re-zero Z (probe)."
        )
    else:
        lines.append(
            f"; SINGLE TOOL: {main_tool_id} for the whole job — no tool changes."
        )
    lines += [
        ";",
        ";HEAD: spindle",  # validator marker (spindle, not laser)
        f";MATERIAL: {material_id}",
        f";TOOL: {sections[0][1]}",
        "; Set GRBL to spindle mode ($32=0) ON THE MACHINE before running — it is",
        "; a GRBL setting, not a G-code word, so it is intentionally NOT emitted here.",
        "G21     ; mm",
        "G90     ; absolute",
        "G94     ; feed/min (mm/min)",
        f"G0 Z{cfg.safe_z_mm:.3f}",
        f"M3 S{spindle_rpm}",
        "",
    ]

    warnings: list[str] = []
    prev_tool = sections[0][1]
    for label, tool_id, out in sections:
        if tool_id != prev_tool:
            # Manual tool change: stop spindle, pause, restart after the swap.
            lines += [
                f"; ---- MANUAL TOOL CHANGE: {prev_tool} -> {tool_id} ----",
                f"G0 Z{cfg.safe_z_mm:.3f}",
                "M5           ; stop spindle for tool change",
                "M0           ; PAUSE — swap tool, re-zero Z, then cycle-start",
                f";TOOL: {tool_id}",  # update validator's current-tool tracking
                f"M3 S{spindle_rpm}",
                "",
            ]
            prev_tool = tool_id
        lines.append(f"; ===== {label} =====")
        lines.extend(_strip_op(out.lines))
        lines.append("")
        warnings.extend(out.warnings)

    lines += [
        f"G0 Z{cfg.safe_z_mm:.3f}",
        "M5",
        "G0 X0 Y0",
        "",
    ]
    return GcodeOutput(lines=lines, warnings=warnings)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--thickness-mm",
        type=float,
        default=3.0,
        help="MEASURE your sheet — 'PET plexiglass' is often 2.0-2.8mm",
    )
    ap.add_argument("--material", default="petg_3mm")
    ap.add_argument(
        "--small-tool",
        default="flat_3.175mm_2flute",
        help='bit for the small holes; defaults to the 1/8" bit = no tool change',
    )
    ap.add_argument("--main-tool", default="flat_3.175mm_2flute")
    ap.add_argument("--spindle-rpm", type=int, default=8000)
    ap.add_argument("--tab-count", type=int, default=6)
    ap.add_argument(
        "--origin-margin-mm",
        type=float,
        default=6.0,
        help="inset the part from WCS origin so the profile stays positive",
    )
    ap.add_argument(
        "--lcd-window",
        action="store_true",
        help="mill out the LCD viewing window (use for opaque/tinted material)",
    )
    ap.add_argument(
        "--strict", action="store_true", help="upgrade all CAM warnings to fatal errors"
    )
    args = ap.parse_args()

    out = make_bezel_gcode(
        thickness_mm=args.thickness_mm,
        material_id=args.material,
        small_tool_id=args.small_tool,
        main_tool_id=args.main_tool,
        spindle_rpm=args.spindle_rpm,
        tab_count=args.tab_count,
        lcd_window=args.lcd_window,
        origin_margin_mm=args.origin_margin_mm,
        strict=args.strict,
    )

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    path = BUILD_DIR / "bezel.gcode"
    path.write_text(out.text)
    print(f"-> {path}  ({len(out.lines)} lines)")
    print(f"   warnings: {len(out.warnings)}")
    for w in out.warnings:
        print(f"     - {w if len(w) <= 100 else w[:97] + '...'}")
    print("\nNext (run from the cnc_vibes repo):")
    print(f"  cd {CNC_VIBES}")
    print(f"  python cnc.py validate  {path}")
    print(f"  python cnc.py preview   {path}")
    print(f"  python cnc.py preflight {path}")


if __name__ == "__main__":
    main()
