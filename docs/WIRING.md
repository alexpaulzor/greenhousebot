# Wiring Guide — solderless, terminal-block build (no PCB)

Decision: **no PCB.** The circuit is just power-rail fan-out + a 2-wire I2C bus, so we
distribute it with screw terminals and lever-nuts. Nothing sensitive is soldered.

Reflects: **AHT21 (I2C)** sensor, **LCD at 3.3 V** → single 3.3 V I2C bus (**no level
shifter**), **Pico in a screw-terminal expander**, **panel buttons via terminals**,
**12 V 5 A PSU**.

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
| out | **AHT21 GND** |
| out | **LCD GND** |
| out | **Button common** (one wire feeds all 3 buttons' return) |
| out | **Valve −** |

### 3V3 bus (from Pico "3V3" terminal) — 5-way lever-nut
| Terminal | Goes to |
|----------|---------|
| in | **Pico 3V3 (p36)** |
| out | **AHT21 VIN** |
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
| **GP4 (p6)**  | AHT21 **SDA** + LCD **SDA** (both) | I2C data |
| **GP5 (p7)**  | AHT21 **SCL** + LCD **SCL** (both) | I2C clock |
| **GP16 (p21)**| Relay **IN1** | mister valve |
| **GP17 (p22)**| Relay **IN2** | mains-box trigger (fans) |
| **GP18 (p24)**| BTS7960 **RPWM** | window open |
| **GP19 (p25)**| BTS7960 **LPWM** | window close |
| **GP20 (p26)**| BTS7960 **R_EN + L_EN** (jumper both) | H-bridge enable |
| **GP26 (p31)**| BTS7960 **R_IS + L_IS** | current sense (optional) |
| **GP10 (p14)**| Button **"+"** (other leg → GND bus) | menu up |
| **GP11 (p15)**| Button **"−"** (other leg → GND bus) | menu down |
| **GP12 (p16)**| Button **"OK"** (other leg → GND bus) | menu select |

The two I2C wires each land on **two** module terminals — either daisy-chain
(Pico→AHT21→LCD) or use a small lever-nut per line. AHT21 = 0x38, LCD = 0x27/0x3F; no clash.

## Loads (out to the greenhouse)

| From | To |
|------|----|
| **Relay CH1 NO** | valve **+** (valve **−** → GND bus) |
| **Relay CH2 COM + NO** | external mains-box **trigger input** (dry contact) |
| **BTS7960 M+ / M−** | window actuator leads |

## Buttons (your panel-mount momentary + flying leads)

Each button = two wires: one to its **Pico GP terminal**, one to the **GND bus**. The
Pico uses internal pull-ups (`Pin.PULL_UP`), so **no resistors** and polarity doesn't
matter. If you prefer, land all three GND legs on one 3-way lever-nut into the GND bus.

## Build order (safe bring-up)

1. Set buck to **5.1 V** on the bench (meter it) — before anything else is connected.
2. Wire the **GND bus** first, then **12 V**, then **5 V → VSYS**, then **3V3** fan-out.
3. Power on with **only the Pico** populated; confirm it enumerates over USB.
4. Add I2C (AHT21 + LCD); run an `i2c.scan()` — expect **0x38** and **0x27/0x3F**.
5. Add relay, then H-bridge (test window jog at low PWM), then valve.
6. Buttons last.

## Spare / notes

- **GP15 is now free** (old DHT single-wire pin) — spare for a limit switch or status LED.
- If the LCD is too dim at 3.3 V: power **LCD VCC from 5 V** and add a BSS138 level
  shifter on **SDA/SCL only**; keep AHT21 on 3.3 V. (Optional fallback, not expected.)
