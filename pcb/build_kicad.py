#!/usr/bin/env python3
"""
Build greenhousebot.kicad_pcb directly from the Python layout + netlist, using
KiCad's pcbnew API. Run with KiCad's bundled Python:

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
      pcb/build_kicad.py

Produces kicad/greenhousebot.kicad_pcb with:
  * all footprints placed at the coordinates from layout.py
  * a CUSTOM Pico 2 W footprint whose pad numbers match the PHYSICAL pinout
    (1..20 down the left, 21..40 up the right) so netlist.py pin numbers are correct
  * nets assigned from netlist.py (via the name->pad-number map in to_kicad.py)
  * board outline on Edge.Cuts and a GND zone (pour) on B.Cu
Then you route in KiCad (single-sided on B.Cu) and export G-code per KICAD_SETUP.md.

This replaces the fragile netlist-import step with a direct, correct board.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcbnew

import layout as L
import netlist as N
import to_kicad as TK

FPBASE = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    # layout.py uses +Y up; KiCad uses +Y down. Flip Y about board height.
    return pcbnew.VECTOR2I(mm(x), mm(L.BOARD_H - y))


def load_fp(board, spec):
    lib, name = spec.split(":")
    fp = pcbnew.FootprintLoad(f"{FPBASE}/{lib}.pretty", name)
    if fp is None:
        raise RuntimeError(f"could not load {spec}")
    board.Add(fp)
    return fp


def make_pico(board):
    """Custom RPi Pico 2 W footprint: 40 THT pads numbered by physical pin.
    Left column pins 1..20 (x=0), right column 21..40 (x=17.78), 2.54 pitch.
    Right side counts UP the board (pin 21 nearest pin 20's end) per the Pico."""
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference("U1")
    fp.SetValue("Pico_2W")
    pitch = 2.54
    row = 7 * pitch  # 17.78 mm between the two pin rows
    for i in range(20):
        # left: pin 1 at bottom (y=0) going up
        _add_pad(fp, str(i + 1), 0, i * pitch)
        # right: pin 40 at top, 21 at bottom -> pin (21+i) at y=i*pitch
        _add_pad(fp, str(21 + i), row, i * pitch)
    board.Add(fp)
    return fp


def _add_pad(fp, number, x, y):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(number)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(pcbnew.VECTOR2I(mm(1.6), mm(1.6)))
    pad.SetDrillSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
    pad.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    lset = pcbnew.LSET()
    for ly in (pcbnew.F_Cu, pcbnew.B_Cu):
        lset.AddLayer(ly)
    pad.SetLayerSet(lset)
    fp.Add(pad)


def main():
    board = pcbnew.BOARD()

    # --- create footprints (positions set after we know real bounding boxes) ---
    fps = {}
    for pl in L.build():
        if pl.ref == "U1":
            fp = make_pico(board)
        else:
            val, spec = TK.FOOTPRINTS[pl.ref]
            fp = load_fp(board, spec)
            fp.SetReference(pl.ref)
            fp.SetValue(val)
        if pl.rot:
            fp.SetOrientationDegrees(pl.rot)
        fps[pl.ref] = fp

    # --- shelf-pack by REAL bounding box so nothing overlaps ---
    # layout.py used abstract 2-pin stand-ins; the real KiCad footprints are much
    # bigger (DO-41 = 10 mm, radial caps 8-10 mm, Pico 48 mm), so we can't trust the
    # abstract XY. Pack left->right, wrap to a new shelf, with a fixed gap. This is a
    # legal, non-overlapping START; route/rearrange to taste in KiCad.
    GAP = 3.0
    margin = L.MARGIN
    cx, cy, shelf_h = margin, margin, 0.0
    # Pico first (largest), then the rest in a stable order
    order = ["U1"] + [r for r in fps if r != "U1"]
    for ref in order:
        fp = fps[ref]
        bb = fp.GetBoundingBox()  # includes courtyard/silk
        w = pcbnew.ToMM(bb.GetWidth())
        h = pcbnew.ToMM(bb.GetHeight())
        if cx + w > L.BOARD_W - margin:
            cx = margin
            cy += shelf_h + GAP
            shelf_h = 0.0
        # place so the footprint's bbox top-left lands at (cx, cy)
        pos = fp.GetPosition()
        off_x = pcbnew.ToMM(pos.x - bb.GetLeft())
        off_y = pcbnew.ToMM(pos.y - bb.GetTop())
        fp.SetPosition(pcbnew.VECTOR2I(mm(cx + off_x), mm(cy + off_y)))
        cx += w + GAP
        shelf_h = max(shelf_h, h)
    packed_h = cy + shelf_h + margin
    if packed_h > L.BOARD_H:
        print(
            f"  note: packed height {packed_h:.0f}mm > board {L.BOARD_H}mm "
            f"- board auto-grows"
        )

    # --- nets ---
    netmap = {}
    for i, net in enumerate(N.NETS, start=1):
        ni = pcbnew.NETINFO_ITEM(board, net, i)
        board.Add(ni)
        netmap[net] = ni
    # assign each pad to its net
    for net, pins in N.NETS.items():
        for ref, pin in pins:
            padnum = TK.pad_number(ref, pin)
            fp = fps.get(ref)
            if not fp:
                continue
            pad = fp.FindPadByNumber(str(padnum))
            if pad is None:
                print(f"  !! {ref}.{pin} (pad {padnum}) not found on footprint")
                continue
            pad.SetNet(netmap[net])

    # --- board outline on Edge.Cuts (native coords; sized to packed content) ---
    bw = L.BOARD_W
    bh = max(L.BOARD_H, packed_h)
    corners = [(0, 0), (bw, 0), (bw, bh), (0, bh)]

    def nvec(x, y):
        return pcbnew.VECTOR2I(mm(x), mm(y))

    for a, b in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(nvec(*a))
        seg.SetEnd(nvec(*b))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.15))
        board.Add(seg)

    # --- GND zone (pour) on B.Cu covering the board ---
    gnd = netmap["GND"]
    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.B_Cu)
    zone.SetNet(gnd)
    zone.SetIsFilled(False)
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in corners:
        v = nvec(x, y)
        outline.Append(v.x, v.y)
    board.Add(zone)

    # --- design settings for V-bit milling (net classes) ---
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)  # we route B.Cu; F.Cu only for jumpers

    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "kicad"), exist_ok=True)
    out = os.path.join(
        os.path.dirname(__file__), "..", "kicad", "greenhousebot.kicad_pcb"
    )
    board.Save(out)
    print(f"wrote {out}")
    print(f"footprints: {len(fps)}  nets: {len(netmap)}")


if __name__ == "__main__":
    main()
