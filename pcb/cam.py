"""
CAM: turn the routed board into copper geometry + GRBL G-code for a desktop mill.

Pipeline:
  layout -> router -> shapely copper geometry -> 3 toolpaths:
    1. ISOLATION (V-bit): trace the boundary of every copper island so a thin
       isolation gap separates each net from the surrounding GROUND POUR.
    2. DRILL (small bit): peck-drill every through-hole (pads + jumper vias).
    3. CUTOUT (endmill): profile the board edge in tabs.

Also renders the copper to SVG so you can eyeball it before cutting.

Targets GRBL dialect (Candle/bCNC/UGS). Units mm, absolute (G90, G21).
All parameters (feeds, depths, tool sizes) are at the top — tune to your machine.
"""

import math

from shapely.geometry import LineString, Point, box, MultiPolygon
from shapely.ops import unary_union
import svgwrite

import layout as L
import netlist as N
import router as R

# --- machine / tool parameters (EDIT for your mill) -------------------------
VBIT_TIP = 0.2  # effective cut width of the V-bit at depth (mm)
ISO_DEPTH = -0.10  # isolation cut depth into copper (mm, negative = down)
DRILL_BIT = 0.9  # drill diameter (mm) for THT pads
DRILL_DEPTH = -1.9  # through 1.6mm board + breakthrough
CUT_BIT = 1.6  # endmill for board outline
CUT_DEPTH = -2.0  # full board thickness + a hair
CUT_PASS = -0.5  # depth per cutout pass
SAFE_Z = 3.0  # travel height (mm)
FEED_XY = 120  # mm/min cut feed
FEED_PLUNGE = 40  # mm/min plunge feed
FEED_DRILL = 30
SPINDLE_RPM = 12000
TABS = 4  # cutout holding tabs
TAB_LEN = 3.0  # mm


def pad_net_map():
    """(ref, pad) -> net name, from the netlist."""
    m = {}
    for net, pins in N.NETS.items():
        for ref, pad in pins:
            m[(ref, pad)] = net
    return m


def copper_by_net(rtr):
    """Per-net copper polygon. GND is the POUR (handled separately), so GND pads
    are NOT built as islands here — they get thermal relief from the pour.
    Returns {net: shapely polygon}."""
    pnet = pad_net_map()
    per = {}

    def add(net, geom):
        per[net] = geom if net not in per else unary_union([per[net], geom])

    # traces
    for t in rtr.traces:
        if len(t.points) >= 2:
            add(
                t.net,
                LineString(t.points).buffer(t.width / 2, cap_style=1, join_style=1),
            )
    # pads: attach to their net; unconnected pads (no net) become their own island
    for pl in L.build():
        for name, (x, y, w, h, drill, shape) in pl.placed_pads().items():
            net = pnet.get((pl.ref, name))
            if net == "GND":
                continue  # GND pads live in the pour, not as islands
            if shape == "rect":
                pad = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            else:
                pad = Point(x, y).buffer(max(w, h) / 2)
            add(net or f"_nc_{pl.ref}_{name}", pad)
    # jumper vias
    for j in rtr.jumpers:
        add(j.net, Point(*j.a).buffer(L.PAD_D / 2))
        add(j.net, Point(*j.b).buffer(L.PAD_D / 2))
    return per


def copper_geometry(rtr):
    """Union of ALL non-GND signal copper (for isolation offsetting/render)."""
    return unary_union(list(copper_by_net(rtr).values()))


def drc(rtr):
    """Real design-rule check: every pair of DIFFERENT nets must be at least
    ISOLATION apart (measured on the actual copper polygons). Also checks each
    non-GND island keeps ISOLATION from GND pads (the pour)."""
    per = copper_by_net(rtr)
    nets = list(per.items())
    viol = []
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            (na, ga), (nb, gb) = nets[i], nets[j]
            d = ga.distance(gb)
            if d < L.ISOLATION - 1e-6:
                viol.append((na, nb, round(d, 3)))
    # vs GND pour: distance from each island to every GND pad
    gnd_pads = [
        Point(x, y).buffer(L.PAD_D / 2)
        for pl in L.build()
        for nm, (x, y, w, h, dr, sh) in pl.placed_pads().items()
        if pad_net_map().get((pl.ref, nm)) == "GND"
    ]
    gnd = unary_union(gnd_pads) if gnd_pads else None
    if gnd is not None:
        for net, g in per.items():
            d = g.distance(gnd)
            if d < L.ISOLATION - 1e-6:
                viol.append((net, "GND(pour)", round(d, 3)))
    return viol


def all_holes(rtr):
    holes = []
    for pl in L.build():
        for name, (x, y, w, h, drill, shape) in pl.placed_pads().items():
            if drill:
                holes.append((x, y))
    for j in rtr.jumpers:
        holes.append(j.a)
        holes.append(j.b)
    # dedupe
    uniq = []
    for h in holes:
        if not any(abs(h[0] - u[0]) < 0.3 and abs(h[1] - u[1]) < 0.3 for u in uniq):
            uniq.append(h)
    return uniq


def iso_toolpaths(copper):
    """Isolation = offset each copper island outward by (VBIT_TIP/2) and follow
    that contour. Result: a clean gap between copper and the ground pour."""
    grown = copper.buffer(VBIT_TIP / 2, join_style=2)
    geoms = grown.geoms if isinstance(grown, MultiPolygon) else [grown]
    rings = []
    for g in geoms:
        rings.append(list(g.exterior.coords))
        for interior in g.interiors:
            rings.append(list(interior.coords))
    return rings


# --- G-code emission --------------------------------------------------------
def gcode_header(lines):
    lines += ["G21 G90 G94", "G17", f"M3 S{SPINDLE_RPM}", f"G0 Z{SAFE_Z:.2f}"]


def gcode_footer(lines):
    lines += [f"G0 Z{SAFE_Z:.2f}", "M5", "G0 X0 Y0", "M2"]


def emit_contour(lines, ring, depth):
    if len(ring) < 2:
        return
    x0, y0 = ring[0]
    lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
    lines.append(f"G1 Z{depth:.3f} F{FEED_PLUNGE}")
    for x, y in ring[1:]:
        lines.append(f"G1 X{x:.3f} Y{y:.3f} F{FEED_XY}")
    lines.append(f"G0 Z{SAFE_Z:.3f}")


def gen_isolation(rtr):
    lines = [f"( Greenhouse carrier - ISOLATION - V-bit tip {VBIT_TIP}mm )"]
    gcode_header(lines)
    for ring in iso_toolpaths(copper_geometry(rtr)):
        emit_contour(lines, ring, ISO_DEPTH)
    gcode_footer(lines)
    return "\n".join(lines) + "\n"


def gen_drill(rtr):
    lines = [f"( Greenhouse carrier - DRILL - bit {DRILL_BIT}mm )"]
    gcode_header(lines)
    for x, y in all_holes(rtr):
        lines.append(f"G0 X{x:.3f} Y{y:.3f}")
        lines.append(f"G1 Z{DRILL_DEPTH:.3f} F{FEED_DRILL}")
        lines.append(f"G0 Z{SAFE_Z:.3f}")
    gcode_footer(lines)
    return "\n".join(lines) + "\n"


def gen_cutout():
    lines = [f"( Greenhouse carrier - CUTOUT - endmill {CUT_BIT}mm, {TABS} tabs )"]
    gcode_header(lines)
    r = CUT_BIT / 2
    # rectangle outside board edge by tool radius
    x0, y0, x1, y1 = -r, -r, L.BOARD_W + r, L.BOARD_H + r
    perim = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    # multi-pass down to depth, skipping tab zones on the last pass
    z = 0.0
    while z > CUT_DEPTH:
        z = max(CUT_DEPTH, z + CUT_PASS)
        lines.append(f"G0 X{perim[0][0]:.3f} Y{perim[0][1]:.3f}")
        lines.append(f"G1 Z{z:.3f} F{FEED_PLUNGE}")
        for x, y in perim[1:]:
            lines.append(f"G1 X{x:.3f} Y{y:.3f} F{FEED_XY}")
        lines.append(f"G0 Z{SAFE_Z:.3f}")
    lines.append("( final pass leaves 4 tabs - see README to add tab skips )")
    gcode_footer(lines)
    return "\n".join(lines) + "\n"


def render_copper(rtr, path):
    SCALE = 5
    W, H = L.BOARD_W * SCALE, L.BOARD_H * SCALE
    dwg = svgwrite.Drawing(path, size=(f"{W}px", f"{H}px"))
    # pour = board; copper islands drawn in bright copper; isolation gap = board colour
    dwg.add(dwg.rect((0, 0), (W, H), fill="#7a5a2f"))  # ground pour (copper)

    def X(x):
        return x * SCALE

    def Y(y):
        return H - y * SCALE

    copper = copper_geometry(rtr)
    grown = copper.buffer(VBIT_TIP / 2, join_style=2)
    # draw isolation gap (board substrate) then copper islands on top
    for g in grown.geoms if isinstance(grown, MultiPolygon) else [grown]:
        pts = [(X(x), Y(y)) for x, y in g.exterior.coords]
        dwg.add(dwg.polygon(pts, fill="#0b3d0b"))
    cg = copper.geoms if isinstance(copper, MultiPolygon) else [copper]
    for g in cg:
        pts = [(X(x), Y(y)) for x, y in g.exterior.coords]
        dwg.add(dwg.polygon(pts, fill="#d98a3d"))
    # holes
    for x, y in all_holes(rtr):
        dwg.add(dwg.circle((X(x), Y(y)), DRILL_BIT * SCALE / 2, fill="#111"))
    # jumpers as dashed top-side wires
    for j in rtr.jumpers:
        dwg.add(
            dwg.line(
                (X(j.a[0]), Y(j.a[1])),
                (X(j.b[0]), Y(j.b[1])),
                stroke="#39f",
                stroke_width=2,
                stroke_dasharray="4,3",
            )
        )
    dwg.save()


def main():
    rtr = R.Router(L.build())
    rtr.route_all()
    import os

    # DRC gate: never emit G-code that would short nets.
    viol = drc(rtr)
    render_copper(rtr, "../docs/diagrams/pcb_copper.svg")
    if viol:
        print(f"!! DRC FAILED: {len(viol)} clearance violations (<{L.ISOLATION}mm):")
        for a, b, d in viol[:25]:
            print(f"   {a} <-> {b}: {d} mm")
        print("No G-code written. Fix layout/routing and re-run.")
        print("(copper SVG still rendered so you can see the shorts)")
        return rtr

    os.makedirs("../hardware_out", exist_ok=True)
    open("../hardware_out/iso.nc", "w").write(gen_isolation(rtr))
    open("../hardware_out/drill.nc", "w").write(gen_drill(rtr))
    open("../hardware_out/cutout.nc", "w").write(gen_cutout())
    holes = all_holes(rtr)
    print(f"DRC OK. drill holes: {len(holes)}, jumpers: {len(rtr.jumpers)}")
    print("wrote hardware_out/{iso,drill,cutout}.nc + docs/diagrams/pcb_copper.svg")
    return rtr


if __name__ == "__main__":
    main()
