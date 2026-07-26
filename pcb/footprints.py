"""
Footprint library for the greenhouse controller carrier board.

Each footprint is a list of pads. A pad is:
    Pad(name, x, y, w, h, drill, shape)
with x,y relative to the footprint origin (mm), w/h the copper pad size,
drill the hole diameter (0 = no hole / SMD), shape "rect" or "round".

All through-hole here (this is a milled single-sided carrier — everything is THT
so you solder from the copper side). Pitch 2.54 mm (0.1") unless noted.

MEASURE your real modules and tweak: mounting-hole spacings especially vary.
These match the common AliExpress/Amazon modules.
"""

from dataclasses import dataclass


@dataclass
class Pad:
    name: str
    x: float
    y: float
    w: float = 1.4  # keep <= PITCH-ISOLATION-TRACE so a trace can pass between rows
    h: float = 1.4
    drill: float = 0.9
    shape: str = "round"  # "round" | "rect"


PITCH = 2.54


def header(n, pins_per_row=1, pitch=PITCH, first_pad_rect=True, names=None):
    """Generic pin header, rows along +Y, columns along +X."""
    pads = []
    idx = 0
    for col in range(pins_per_row):
        for row in range(n):
            nm = names[idx] if names else str(idx + 1)
            shape = "rect" if (idx == 0 and first_pad_rect) else "round"
            pads.append(Pad(nm, col * pitch, row * pitch, drill=1.0, shape=shape))
            idx += 1
    return pads


def screw_terminal(n, pitch=5.08):
    """5.08 mm screw terminal block, n positions along +X. Big pads/drills."""
    return [
        Pad(
            str(i + 1),
            i * pitch,
            0,
            w=2.6,
            h=2.6,
            drill=1.3,
            shape="rect" if i == 0 else "round",
        )
        for i in range(n)
    ]


# --- Module footprints (pad grids matching module pin headers) --------------


def pico_2w():
    """Raspberry Pi Pico 2 W: 2x20, 2.54 pitch, rows 17.78 mm (0.7") apart.
    Pin 1 = GP0 top-left; numbering follows the Pico pinout (1..40)."""
    left = header(20, 1, names=[str(i) for i in range(1, 21)])
    right = header(20, 1, names=[str(i) for i in range(40, 20, -1)])
    for p in right:
        p.x += 7 * PITCH  # 17.78 mm = 7*2.54
    return left + right


def buck_module():
    """Mini buck (MP1584-style): 4 through-holes, IN+ IN- OUT+ OUT- ~ in a row.
    Real modules vary; treat as a 1x4 header at 2.54 you solder wires/pins to."""
    return header(4, 1, names=["IN+", "IN-", "OUT+", "OUT-"])


def bts7960():
    """BTS7960 module: 8-pin logic header (RPWM LPWM R_EN L_EN R_IS L_IS VCC GND)
    plus 4 heavy screw terminals (B+ B- M+ M-) — modeled separately as J."""
    return header(
        8, 1, names=["RPWM", "LPWM", "R_EN", "L_EN", "R_IS", "L_IS", "VCC", "GND"]
    )


def level_shifter():
    """BSS138 4-ch: two 1x4 headers (LV side / HV side) 4-wide, ~15 mm apart.
    We only use 2 channels. LV: GND LV LV1 LV2 ; HV: GND HV HV1 HV2."""
    lv = header(4, 1, names=["GND", "LV", "LV1", "LV2"])
    hv = header(4, 1, names=["HV", "HGND", "HV1", "HV2"])
    for p in hv:
        p.x += 6 * PITCH
    return lv + hv


def relay_module():
    """2-channel native-3.3 V relay module logic header: VCC IN1 IN2 GND (1x4).
    Order per common 2-ch boards; check silk. Heavy load side (COM/NO/NC x2) is
    off-board screw terminals we wire to, modeled as J2/J4 in the layout."""
    return header(4, 1, names=["VCC", "IN1", "IN2", "GND"])


def lcd_conn():
    """LCD I2C backpack connector: GND VCC SDA SCL (1x4)."""
    return header(4, 1, names=["GND", "VCC", "SDA", "SCL"])


def button():
    """6mm tactile button, 2 effective nodes; model as 1x2 (signal, gnd)."""
    return header(2, 1, names=["a", "b"])
