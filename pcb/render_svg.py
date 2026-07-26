"""
Render the carrier layout to SVG and validate the netlist against placements.

  python render_svg.py           -> writes ../docs/diagrams/pcb_layout.svg
                                    + prints validation report

Validation catches the classic hand-layout mistakes:
  * a netlist pad that doesn't exist on the placed footprint (typo / wrong pin)
  * pads on the same net + a rough ratsnest so you can eyeball routability
This is a placement/ratsnest view, NOT the milled copper (that's cam.py).
"""

import svgwrite

import layout as L
import netlist as N

SCALE = 4  # px per mm


def collect_pads(placements):
    """ref -> {pad -> (x,y,w,h,drill,shape)}"""
    return {pl.ref: pl.placed_pads() for pl in placements}


def validate(pads_by_ref):
    errors, npads = [], 0
    for net, pins in N.NETS.items():
        for ref, pad in pins:
            npads += 1
            if ref not in pads_by_ref:
                errors.append(f"NET {net}: ref {ref} not placed")
            elif pad not in pads_by_ref[ref]:
                have = ",".join(sorted(pads_by_ref[ref]))
                errors.append(f"NET {net}: {ref}.{pad} missing (have: {have})")
    return errors, npads


def render(placements, pads_by_ref, path):
    W, H = L.BOARD_W * SCALE, L.BOARD_H * SCALE

    def X(x):
        return x * SCALE

    def Y(y):  # SVG y is top-down; flip
        return H - y * SCALE

    dwg = svgwrite.Drawing(path, size=(f"{W}px", f"{H}px"))
    dwg.add(dwg.rect((0, 0), (W, H), fill="#0b3d0b"))  # board green
    dwg.add(
        dwg.rect(
            (X(L.MARGIN), Y(L.BOARD_H - L.MARGIN)),
            ((L.BOARD_W - 2 * L.MARGIN) * SCALE, (L.BOARD_H - 2 * L.MARGIN) * SCALE),
            fill="none",
            stroke="#2f2",
            stroke_dasharray="4,4",
        )
    )

    # ratsnest: straight line between consecutive pads on each net
    net_colors = {}
    palette = [
        "#ff5555",
        "#ffcc00",
        "#55aaff",
        "#ff88ff",
        "#88ff88",
        "#ffffff",
        "#ffaa55",
        "#00ffcc",
    ]
    for i, (net, pins) in enumerate(N.NETS.items()):
        col = palette[i % len(palette)]
        net_colors[net] = col
        pts = []
        for ref, pad in pins:
            if ref in pads_by_ref and pad in pads_by_ref[ref]:
                x, y, *_ = pads_by_ref[ref][pad]
                pts.append((x, y))
        for a, b in zip(pts, pts[1:]):
            dwg.add(
                dwg.line(
                    (X(a[0]), Y(a[1])),
                    (X(b[0]), Y(b[1])),
                    stroke=col,
                    stroke_width=0.7,
                    opacity=0.5,
                )
            )

    # pads
    for pl in placements:
        for name, (x, y, w, h, drill, shape) in pl.placed_pads().items():
            if shape == "rect":
                dwg.add(
                    dwg.rect(
                        (X(x) - w * SCALE / 2, Y(y) - h * SCALE / 2),
                        (w * SCALE, h * SCALE),
                        fill="#e8b923",
                    )
                )
            else:
                dwg.add(dwg.circle((X(x), Y(y)), max(w, h) * SCALE / 2, fill="#e8b923"))
            if drill:
                dwg.add(dwg.circle((X(x), Y(y)), drill * SCALE / 2, fill="#111"))
        # ref label
        dwg.add(
            dwg.text(
                pl.ref,
                insert=(X(pl.x), Y(pl.y) - 2),
                fill="#fff",
                font_size=10,
                font_family="monospace",
            )
        )
    dwg.save()


def main():
    placements = L.build()
    pads_by_ref = collect_pads(placements)
    errors, npads = validate(pads_by_ref)
    render(placements, pads_by_ref, "../docs/diagrams/pcb_layout.svg")

    print(f"placements: {len(placements)}   net pins checked: {npads}")
    print(f"nets: {len(N.NETS)}")
    if errors:
        print(f"\n!! {len(errors)} VALIDATION ERRORS:")
        for e in errors:
            print("  -", e)
    else:
        print("VALIDATION OK — every netlist pad exists on a placed footprint")
    # keep-out check (pads must sit inside the MARGIN keep-out)
    m = L.MARGIN
    off = 0
    for pl in placements:
        for name, (x, y, *_) in pl.placed_pads().items():
            if not (m <= x <= L.BOARD_W - m and m <= y <= L.BOARD_H - m):
                print(f"  !! {pl.ref}.{name} outside keep-out at ({x:.1f},{y:.1f})")
                off += 1
    if not off:
        print(f"KEEP-OUT OK — all pads inside {m} mm margin")


if __name__ == "__main__":
    main()
