# Wiring Guide — solderless, terminal-block build (no PCB)

Decision: **no PCB.** The circuit is just power-rail fan-out + a 2-wire I2C bus, so we
distribute it with screw terminals and lever-nuts. Nothing sensitive is soldered.

Reflects: **two AHT21 sensors** (indoor on I2C0 with the LCD; outdoor on I2C1 — separate
bus, fixed 0x38 address), **LCD at 3.3 V** (**no level shifter**), **Pico in a screw-
terminal expander**, **panel buttons via terminals as toggles**, **12 V 5 A PSU**.

## Key hardware that makes this solderless

- **Pico screw-terminal expander** — the Pico (with headers) plugs in; every pin becomes
  a labelled screw terminal. Search "Raspberry Pi Pico GPIO terminal block expander".
  → No soldering the Pico. Serviceable.
- **Wago 221 lever-nuts** (2/3/5-conductor) — for the nets that fan out to many places
  (GND, 3V3, 12V). Solderless, reopenable, humidity-tolerant.
- The pre-made modules (buck, relay, BTS7960, AHT21, LCD) already have screw terminals or
  pin headers — wire to them with **ferruled hookup wire or Dupont leads**.

## Power distribution (lever-nuts)

Make three lever-nut "buses". Wire gauge: **18 AWG for 12 V / motor**, 22–24 AWG signals.

### 12 V bus (from PSU +12V) — 3-way lever-nut
| Terminal | Goes to |
|----------|---------|
| in | PSU **+12 V** |
| out | **Buck IN+** |
| out | **BTS7960 B+** (motor supply) |
| out | **Relay CH1 COM** (valve switching) |

### GND bus (from PSU GND) — 5-way + 3-way lever-nuts chained
| Terminal | Goes to |
|----------|---------|
| in | PSU **GND** |
| out | **Buck IN−** and **Buck OUT−** |
| out | **BTS7960 B−** and **BTS7960 GND** |
| out | **Pico GND** (any GND terminal, e.g. p38/p23/p3) |
| out | **Relay GND** |
| out | **indoor AHT21 GND** and **outdoor AHT21 GND** |
| out | **LCD GND** |
| out | **Button common** (one wire feeds all 3 buttons' return) |
| out | **Valve −** |

### 3V3 bus (from Pico "3V3" terminal) — 6-way lever-nut
| Terminal | Goes to |
|----------|---------|
| in | **Pico 3V3 (p36)** |
| out | **indoor AHT21 VIN** |
| out | **outdoor AHT21 VIN** |
| out | **LCD VCC** |
| out | **Relay VCC** |
| out | **BTS7960 VCC** (logic) |

### 5 V (single link, no bus)
| From | To |
|------|----|
| **Buck OUT+** (set to 5.1 V) | **Pico VSYS (p39)** |

> Set the buck to **5.1 V before** connecting the Pico. Powering VSYS is correct; do
> **not** feed the Pico's VBUS/5V pin. USB can still be plugged in for flashing.

## Signal wiring (Pico terminal → module terminal)

| Pico terminal | Module terminal | Function |
|---------------|-----------------|----------|
| **GP4 (p6)**  | **indoor** AHT21 **SDA** + LCD **SDA** | I2C0 data |
| **GP5 (p7)**  | **indoor** AHT21 **SCL** + LCD **SCL** | I2C0 clock |
| **GP2 (p4)**  | **outdoor** AHT21 **SDA** | I2C1 data (own bus) |
| **GP3 (p5)**  | **outdoor** AHT21 **SCL** | I2C1 clock |
| **GP16 (p21)**| Relay **IN1** | mister valve |
| **GP17 (p22)**| Relay **IN2** | mains-box trigger (fans) |
| **GP18 (p24)**| BTS7960 **RPWM** | window open |
| **GP19 (p25)**| BTS7960 **LPWM** | window close |
| **GP20 (p26)**| BTS7960 **R_EN + L_EN** (jumper both) | H-bridge enable |
| **GP26 (p31)**| BTS7960 **R_IS + L_IS** | current sense (optional) |
| **GP10 (p14)**| Window button (other leg → GND bus) | toggle window open/close |
| **GP11 (p15)**| Fans button (other leg → GND bus) | toggle fans on/off |
| **GP12 (p16)**| Mister button (other leg → GND bus) | toggle mister on/off |

The indoor I2C0 lines each land on **two** module terminals (indoor AHT21 + LCD) —
daisy-chain or use a small lever-nut per line. The **outdoor AHT21 needs its own bus
(I2C1)** because its address (0x38) is identical to the indoor unit's. LCD = 0x27/0x3F.

## Loads (out to the greenhouse)

| From | To |
|------|----|
| **Relay CH1 NO** | valve **+** (valve **−** → GND bus) |
| **Relay CH2 COM + NO** | external mains-box **trigger input** (dry contact) |
| **BTS7960 M+ / M−** | window actuator leads |

## Buttons (your panel-mount momentary + flying leads)

Three buttons, each a single-press **toggle** (window / fans / mister). Each button =
two wires: one to its **Pico GP terminal** (GP10/GP11/GP12), one to the **GND bus**. The
Pico uses internal pull-ups (`Pin.PULL_UP`), so **no resistors** and polarity doesn't
matter. Land all three GND legs on one 3-way lever-nut into the GND bus if you like.

## Build order (safe bring-up)

1. Set buck to **5.1 V** on the bench (meter it) — before anything else is connected.
2. Wire the **GND bus** first, then **12 V**, then **5 V → VSYS**, then **3V3** fan-out.
3. Power on with **only the Pico** populated; confirm it enumerates over USB.
4. Add I2C0 (indoor AHT21 + LCD); run `machine.I2C(0).scan()` — expect **0x38** and
   **0x27/0x3F**. Then wire I2C1 (outdoor AHT21) and `machine.I2C(1).scan()` — expect **0x38**.
5. Add relay, then H-bridge (test window jog at low PWM), then valve.
6. Buttons last.

## Spare / notes

- **GP15 is free** (old DHT single-wire pin) — spare for a limit switch or status LED.
- If the LCD is too dim at 3.3 V: power **LCD VCC from 5 V** and add a BSS138 level
  shifter on the **I2C0 SDA/SCL only**; keep both AHT21s on 3.3 V. (Optional fallback.)
