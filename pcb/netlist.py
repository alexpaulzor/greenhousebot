"""
Netlist for the greenhouse controller carrier board.

Mirrors docs/CIRCUIT.md (authoritative). Each entry maps a NET name to the list of
(ref, pad) endpoints on that net. Consumed by render_svg.py (ratsnest) and, once
routing strategy is chosen, by cam.py.

Pad names must match footprints.py. Pico pads are numbered 1..40 by physical pin.
Pico physical pin -> function (only the ones we use):
   6=GP4  7=GP5  20=GP15  21=GP16  22=GP17  24=GP18  25=GP19  26=GP20
   14=GP10 15=GP11 16=GP12  31=GP26  36=3V3OUT  39=VSYS
   3,8,13,18,23,28,33,38 = GND (we use 38 & 23 as the nearest ground pins)
"""

NETS = {
    "GND": [
        ("J1", "2"),
        ("C1", "-"),
        ("C2", "-"),
        ("U1", "3"),
        ("U1", "23"),
        ("U1", "38"),
        ("U2", "IN-"),
        ("U2", "OUT-"),
        ("U3", "GND"),
        ("U4", "GND"),
        ("U4", "HGND"),
        ("K1", "GND"),
        ("LCD1", "GND"),
        ("J5", "3"),
        ("SW1", "b"),
        ("SW2", "b"),
        ("SW3", "b"),
        ("D2", "a"),
        ("J2", "2"),
    ],
    "12V": [
        ("J1", "1"),
        ("C1", "+"),
        ("U2", "IN+"),
        ("U3", "VCC"),  # U3.VCC=logic; B+ is heavy term (off-board)
    ],
    "5V_BUCK": [
        ("U2", "OUT+"),
        ("C2", "+"),
        ("D1", "a"),
        ("LCD1", "VCC"),
        ("U4", "HV"),
    ],
    "5V_VSYS": [
        ("D1", "k"),
        ("U1", "39"),
    ],
    "3V3": [
        ("U1", "36"),
        ("U4", "LV"),
        ("K1", "VCC"),
        ("R1", "t"),
        ("J5", "1"),
    ],
    "SDA_3V3": [("U1", "6"), ("U4", "LV1")],
    "SCL_3V3": [("U1", "7"), ("U4", "LV2")],
    "SDA_5V": [("U4", "HV1"), ("LCD1", "SDA")],
    "SCL_5V": [("U4", "HV2"), ("LCD1", "SCL")],
    "DHT_DATA": [("U1", "20"), ("J5", "2"), ("R1", "b")],
    "RLY1_IN": [("U1", "21"), ("K1", "IN1")],
    "RLY2_IN": [("U1", "22"), ("K1", "IN2")],
    "HB_RPWM": [("U1", "24"), ("U3", "RPWM")],
    "HB_LPWM": [("U1", "25"), ("U3", "LPWM")],
    "HB_EN": [("U1", "26"), ("U3", "R_EN"), ("U3", "L_EN")],
    "HB_IS": [("U1", "31"), ("U3", "R_IS"), ("U3", "L_IS")],
    "BTN_PLUS": [("U1", "14"), ("SW3", "a")],
    "BTN_MINUS": [("U1", "15"), ("SW1", "a")],
    "BTN_OK": [("U1", "16"), ("SW2", "a")],
    # valve 12V-switched: J1/12V -> K1 ch1 contacts -> J2. Contacts are off-board on
    # a relay module, so on the carrier these are just the terminal + flyback:
    "VALVE_SW": [("J2", "1"), ("D2", "k")],
}

# Off-board / heavy connections NOT milled as traces (wire directly, screw terminals):
#   U3.B+/B- -> 12V/GND (heavy),  U3.M+/M- -> J3 (actuator),
#   K1 channel contacts (COM/NO) -> 12V, J2, J4  (relay module load side)
OFFBOARD_NOTES = [
    "U3 B+ -> 12V bus (heavy wire), U3 B- -> GND bus (heavy wire)",
    "U3 M+ -> J3.1, U3 M- -> J3.2  (actuator, heavy wire)",
    "K1 CH1: COM->12V, NO->J2.1 (valve+)",
    "K1 CH2: COM & NO -> J4.1/J4.2 (dry contact to external mains box)",
]
