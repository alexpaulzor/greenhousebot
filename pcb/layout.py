"""
Carrier board layout for the greenhouse controller.

Single-sided, milled-on-CNC copper board. This is NOT a full auto-router — it's a
deliberate, human-readable placement + orthogonal trace list, the way you'd hand-lay
a simple single-sided board. Everything here is real geometry in millimetres that:

  * renders to an SVG for review (render_svg.py), and
  * feeds the CAM stage that emits GRBL G-code (cam.py).

Design rules (chosen for V-bit isolation milling, single-sided, hand-friendly):
  ISOLATION   0.4 mm  copper-to-copper gap the mill clears
  TRACE_SIG   0.6 mm  signal traces
  TRACE_PWR   2.0 mm  power/ground/motor traces (fat — carries amps)
  Board       up to 100 x 160 mm stock

Coordinate system: origin bottom-left, +X right, +Y up, millimetres.
Single-sided means EVERY trace is on the copper (bottom) layer; where two nets must
cross we use a labelled WIRE JUMPER (0-ohm / insulated wire on the top side). Jumpers
are listed explicitly so there are no hidden shorts.
"""

from dataclasses import dataclass, field

import footprints as fp

# --- design rules (mm) ------------------------------------------------------
# On-board copper carries LOGIC-level current only. The heavy paths (actuator
# motor, valve coil, 12V bus to the H-bridge) run OFF-BOARD via screw terminals
# and heavy wire — see netlist.OFFBOARD_NOTES. So traces can stay thin, which is
# what keeps 0.1" pitch millable with a V-bit.
ISOLATION = 0.25  # copper-to-copper gap the mill clears (V-bit does this well)
TRACE_SIG = 0.4  # signal traces
TRACE_PWR = 0.8  # on-board power distribution (3V3/5V logic rails)
PAD_D = 1.4  # THT pad copper diameter -> 1.14 mm gap on 2.54 pitch
BOARD_W = 160.0
BOARD_H = 100.0
MARGIN = 4.0


@dataclass
class Placement:
    ref: str
    pads: list
    x: float
    y: float
    rot: float = 0  # degrees, 0/90/180/270
    comment: str = ""

    def placed_pads(self):
        """Return (padname -> (abs_x, abs_y, w, h, drill, shape))."""
        import math

        out = {}
        a = math.radians(self.rot)
        ca, sa = math.cos(a), math.sin(a)
        for p in self.pads:
            rx = p.x * ca - p.y * sa
            ry = p.x * sa + p.y * ca
            out[p.name] = (self.x + rx, self.y + ry, p.w, p.h, p.drill, p.shape)
        return out


@dataclass
class Trace:
    net: str
    points: list  # [(x,y), ...] orthogonal polyline centreline
    width: float = TRACE_SIG


@dataclass
class Jumper:
    net: str
    a: tuple
    b: tuple
    comment: str = ""


# ---------------------------------------------------------------------------
# PLACEMENT
# Rough zones (left→right): power in & buck | Pico centre | modules right
#   Bottom edge: screw terminals (wires exit the board edge)
# ---------------------------------------------------------------------------
def build():
    P = []

    # Pico centred-left, oriented vertically (long axis = Y). Rows 17.78mm apart.
    P.append(
        Placement(
            "U1",
            fp.pico_2w(),
            x=58,
            y=28,
            rot=0,
            comment="Pico 2 W, pin1 (GP0) bottom-left",
        )
    )

    # Power input + fuse + bulk cap, bottom-left corner
    P.append(
        Placement("J1", fp.screw_terminal(2), x=8, y=8, rot=0, comment="12V in (+ -)")
    )
    P.append(
        Placement(
            "U2",
            fp.buck_module(),
            x=8,
            y=44,
            rot=0,
            comment="buck 12->5V, IN+ IN- OUT+ OUT-",
        )
    )
    P.append(
        Placement(
            "C1", fp.header(2, names=["+", "-"]), x=24, y=8, comment="1000uF 12V bulk"
        )
    )
    P.append(
        Placement(
            "C2", fp.header(2, names=["+", "-"]), x=24, y=22, comment="470uF 5V bulk"
        )
    )

    # Level shifter just left of Pico's I2C pins (GP4/5 are physical 6/7 = left side low)
    P.append(
        Placement(
            "U4",
            fp.level_shifter(),
            x=40,
            y=70,
            rot=0,
            comment="BSS138 (optional) LV near Pico, HV toward LCD",
        )
    )

    # 2-ch relay module, right-upper
    P.append(
        Placement(
            "K1",
            fp.relay_module(),
            x=110,
            y=68,
            rot=0,
            comment="2-ch 3.3V relay: VCC IN1 IN2 GND",
        )
    )

    # BTS7960 logic header, right-lower (heavy terminals face board edge)
    P.append(
        Placement(
            "U3", fp.bts7960(), x=110, y=30, rot=0, comment="BTS7960 logic header"
        )
    )

    # LCD connector, upper area (cable to panel). 4-pin 0.1" header runs +Y, so
    # keep origin low enough that 3*2.54 mm stays inside the top keep-out.
    P.append(
        Placement(
            "LCD1", fp.lcd_conn(), x=40, y=80, rot=0, comment="LCD I2C: GND VCC SDA SCL"
        )
    )

    # DHT terminal, top-left edge (wire runs into greenhouse)
    P.append(
        Placement("J5", fp.screw_terminal(3), x=8, y=92, comment="DHT22: 3V3 DATA GND")
    )

    # R1 DHT pull-up near J5
    P.append(
        Placement(
            "R1", fp.header(2, names=["t", "b"]), x=26, y=88, comment="10k DHT pullup"
        )
    )

    # Output screw terminals along bottom edge
    P.append(Placement("J2", fp.screw_terminal(2), x=92, y=8, comment="valve out"))
    P.append(Placement("J3", fp.screw_terminal(2), x=112, y=8, comment="actuator out"))
    P.append(
        Placement("J4", fp.screw_terminal(2), x=132, y=8, comment="mains trig out")
    )
    P.append(
        Placement(
            "D1",
            fp.header(2, names=["a", "k"]),
            x=48,
            y=22,
            comment="Schottky buck->VSYS",
        )
    )
    P.append(
        Placement(
            "D2", fp.header(2, names=["a", "k"]), x=92, y=20, comment="valve flyback"
        )
    )

    # Buttons across the bottom-centre
    P.append(Placement("SW1", fp.button(), x=56, y=10, comment="-"))
    P.append(Placement("SW2", fp.button(), x=70, y=10, comment="OK"))
    P.append(Placement("SW3", fp.button(), x=84, y=10, comment="+"))

    return P


if __name__ == "__main__":
    for pl in build():
        pads = pl.placed_pads()
        print(
            f"{pl.ref:4} @ ({pl.x:5.1f},{pl.y:5.1f}) r{pl.rot:3}  "
            f"{len(pads):2} pads  {pl.comment}"
        )
