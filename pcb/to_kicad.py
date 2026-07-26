"""
Emit a KiCad netlist (.net, s-expression) from the authoritative netlist.py.

This is the professional handoff: import this into KiCad Pcbnew (File > Import >
Netlist) onto a blank board, and KiCad places the footprints ready to route with
its real router. No schematic capture needed — the netlist carries refs, values,
footprints, and net membership.

Net classes for V-bit isolation milling are written to docs/KICAD_SETUP.md (KiCad
applies net classes via the board setup, not the netlist, so we document them).

Footprints use stock KiCad libraries so the import resolves with no custom libs.
Module "footprints" are represented by the pin-header/terminal you actually solder
to on the carrier (the modules plug into those), matching the milled-board design.
"""

import layout as L
import netlist as N

# ref -> (value, KiCad footprint). Stock libs only.
FOOTPRINTS = {
    "U1": ("Pico_2W", "MountingHole:MountingHole_2.7mm_M2.5"),  # placeholder; see note
    "U2": ("Buck_5V", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"),
    "U3": ("BTS7960", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical"),
    "U4": ("BSS138_LS", "Connector_PinHeader_2.54mm:PinHeader_2x04_P2.54mm_Vertical"),
    "K1": ("Relay2ch", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"),
    "LCD1": ("LCD_I2C", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"),
    "J1": (
        "12V_IN",
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    ),
    "J2": (
        "VALVE",
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    ),
    "J3": (
        "ACTUATOR",
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    ),
    "J4": (
        "MAINS_TRIG",
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    ),
    "J5": (
        "DHT22",
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3_1x03_P5.00mm_Horizontal",
    ),
    "R1": ("10k", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"),
    "C1": ("1000uF", "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"),
    "C2": ("470uF", "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"),
    "D1": ("SS14", "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"),
    "D2": ("1N4007", "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"),
    "SW1": ("BTN-", "Button_Switch_THT:SW_PUSH_6mm"),
    "SW2": ("BTN_OK", "Button_Switch_THT:SW_PUSH_6mm"),
    "SW3": ("BTN+", "Button_Switch_THT:SW_PUSH_6mm"),
}

# Note: KiCad has no stock "Pico 2 W" footprint in all installs. We emit U1 with a
# 2x20 header footprint (the socket you actually mill pads for). Override in KiCad
# if you have the RPi Pico footprint library installed.
PICO_FP = "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"


def ref_pads():
    """ref -> ordered list of pad names, from netlist membership + footprints."""
    pads = {}
    for net, pins in N.NETS.items():
        for ref, pad in pins:
            pads.setdefault(ref, [])
            if pad not in pads[ref]:
                pads[ref].append(pad)
    return pads


# Stock KiCad footprints number their pads 1..N. Our netlist names header pins
# ("IN-", "SDA", "a"…). KiCad matches nodes to pads BY NAME, so we must translate
# each named pin to the pad NUMBER of the assigned footprint, or connectivity is
# silently lost. Build name->number from the footprints.py pin order (same order
# the physical module presents), which is a stable 1:1 map. Screw terminals and
# the Pico already use numeric names, so they pass through unchanged.
import footprints as fp

_FP_ORDER = {
    "U2": fp.buck_module(),
    "U3": fp.bts7960(),
    "U4": fp.level_shifter(),
    "K1": fp.relay_module(),
    "LCD1": fp.lcd_conn(),
    "R1": fp.header(2, names=["t", "b"]),
    "D1": fp.header(2, names=["a", "k"]),
    "D2": fp.header(2, names=["a", "k"]),
    "SW1": fp.button(),
    "SW2": fp.button(),
    "SW3": fp.button(),
}

# Explicit pin-name -> stock-footprint pad-number overrides where the stock
# footprint's numbering has a fixed meaning we must respect:
#   Polarized cap (CP_Radial): pad 1 = +, pad 2 = -
#   Diode (D_DO-41):           pad 1 = cathode (K), pad 2 = anode (A)  [polarity!]
#   Resistor (R_Axial):        pads 1/2 (non-polar)
_PAD_OVERRIDE = {
    "C1": {"+": "1", "-": "2"},
    "C2": {"+": "1", "-": "2"},
    "D1": {"k": "1", "a": "2"},
    "D2": {"k": "1", "a": "2"},
    "R1": {"t": "1", "b": "2"},
}


def pad_number(ref, pin):
    """Translate a named pin to its stock-footprint pad number (str)."""
    if ref in _PAD_OVERRIDE and pin in _PAD_OVERRIDE[ref]:
        return _PAD_OVERRIDE[ref][pin]
    order = _FP_ORDER.get(ref)
    if order is None:
        return pin  # numeric already (Pico, screw terminals)
    names = [p.name for p in order]
    if pin in names:
        return str(names.index(pin) + 1)
    return pin


def emit():
    out = ['(export (version "E")']
    # components
    out.append("  (components")
    all_refs = sorted(set(r for pins in N.NETS.values() for r, _ in pins))
    for ref in all_refs:
        val, footp = FOOTPRINTS.get(ref, (ref, PICO_FP))
        if ref == "U1":
            footp = PICO_FP
        out.append(f'    (comp (ref "{ref}")')
        out.append(f'      (value "{val}")')
        out.append(f'      (footprint "{footp}"))')
    out.append("  )")
    # nets
    out.append("  (nets")
    for i, (net, pins) in enumerate(N.NETS.items(), start=1):
        out.append(f'    (net (code "{i}") (name "{net}")')
        for ref, pad in pins:
            out.append(f'      (node (ref "{ref}") (pin "{pad_number(ref, pad)}"))')
        out.append("    )")
    out.append("  )")
    out.append(")")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import os

    os.makedirs("../kicad", exist_ok=True)
    path = "../kicad/greenhousebot.net"
    open(path, "w").write(emit())
    refs = sorted(set(r for pins in N.NETS.values() for r, _ in pins))
    print(f"wrote {path}")
    print(f"components: {len(refs)}   nets: {len(N.NETS)}")
    missing = [r for r in refs if r not in FOOTPRINTS and r != "U1"]
    if missing:
        print("!! no footprint mapping for:", missing)
    else:
        print("all refs have footprint assignments")
