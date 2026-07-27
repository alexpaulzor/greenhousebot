# Wiring Guide — solderless, terminal-block build (no PCB)

Decision: **no PCB.** The circuit is just power-rail fan-out + a 2-wire I2C bus, so we
distribute it with screw terminals and lever-nuts. Nothing sensitive is soldered.

Reflects: **two AHT21 sensors** (indoor on I2C0 with the LCD; outdoor on I2C1 — separate
bus, fixed 0x38 address, **long >3 m run**), **LCD at 3.3 V** (**no level shifter**),
**Pico in a screw-terminal expander**, **panel buttons via terminals as toggles**,
**fans via a 3V3-relay → 12 V → local AC-SSR chain**, **12 V 5 A PSU**.

There are two views below: **by net/bus** (how to build the power distribution) and
**by component** (every wire per device, with conductor suggestions).

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
| **Relay CH2 COM + NO** | **long run → local AC-SSR input** at the fan enclosure (see below) |
| **BTS7960 M+ / M−** | window actuator leads |

### Fans: two-stage relay chain (why, and how)

You are **not** driving the mains directly, and not driving an SSR's DC input from
3.3 V over a long cable (marginal/flaky — many SSRs want >4 V, ~15 mA). Instead:

```
Pico GP17 --> 3V3 relay CH2 (dry contact) --switches--> +12V signal
     |                                                      |  long run (2 wires)
     |                                                      v
     +--(logic, short)                          local AC SSR DC input (+/-)
                                                            |
                                                 AC SSR switches mains --> fan outlets
```

- The **3V3 mechanical relay CH2** just closes a **dry contact**. Wire its **COM to +12 V**
  (from the 12 V bus) and its **NO to the long-run conductor**; the return is a shared GND.
- At the fan enclosure, that **+12 V (switched) + GND** drives the **AC SSR's DC input**
  (use a 12 V-input SSR, or a 3–32 V DC-input SSR — 12 V sits comfortably in range).
- The SSR (mains-rated, in/adjacent to the mains enclosure) switches the fan outlets.
- Result: robust 12 V signal over distance, full galvanic isolation twice over, and no
  mains anywhere near the logic box. The "double relay" is the *right* call, not overkill.

---

## Connections grouped by component

Every wire, per device, with a suggested conductor. "Run" = short (inside the logic
box, <30 cm) unless a length is called out. Gauge notes matter only for the long/no-
current-sensitive runs; short signal hops can be any 22–26 AWG hookup wire.

### PSU (12 V 5 A)
| Wire | To | Conductor |
|------|----|-----------|
| +12 V | 12 V bus (lever-nut) | 18 AWG |
| GND | GND bus (lever-nut) | 18 AWG |

### Buck converter (12→5.1 V)
| Wire | To | Conductor |
|------|----|-----------|
| IN+ | 12 V bus | 20 AWG |
| IN− | GND bus | 20 AWG |
| OUT+ (5.1 V) | Pico VSYS (p39) | 20 AWG |
| OUT− | GND bus | 20 AWG |

### Pico (in screw-terminal expander)
| Wire | To | Conductor |
|------|----|-----------|
| VSYS (p39) | Buck OUT+ | 20 AWG |
| 3V3 OUT (p36) | 3V3 bus | 22 AWG |
| GND (p38) | GND bus | 22 AWG |
| GP4 / GP5 | indoor AHT21 + LCD SDA/SCL | 24 AWG |
| GP2 / GP3 | outdoor AHT21 SDA/SCL | **see outdoor sensor** |
| GP16 / GP17 | Relay IN1 / IN2 | 24 AWG |
| GP18 / GP19 / GP20 | BTS7960 RPWM / LPWM / EN | 24 AWG |
| GP26 | BTS7960 IS (optional) | 24 AWG |
| GP10 / GP11 / GP12 | window / fans / mister buttons | 24 AWG |

### Indoor AHT21 (I2C0, short)
| Wire | To | Conductor |
|------|----|-----------|
| VIN | 3V3 bus | 24 AWG |
| GND | GND bus | 24 AWG |
| SDA | Pico GP4 (shared w/ LCD) | 24 AWG |
| SCL | Pico GP5 (shared w/ LCD) | 24 AWG |

### Outdoor AHT21 (I2C1, LONG run >3 m) — the one that needs care
| Wire | To | Conductor / cable |
|------|----|-----------|
| VIN | 3V3 bus | one pair of a **Cat5e/shielded** cable |
| GND | GND bus | its pair-mate (VIN+GND twisted together) |
| SDA | Pico GP2 | one pair (SDA+GND-ish); **twisted pair** |
| SCL | Pico GP3 | the other pair |

> **I2C over >3 m — the real issue is capacitance, not conductor thickness.**
> - Use **Cat5e / twisted pair** (~45 pF/m). At 3 m that's ~135 pF + device + stray,
>   under I2C's ~400 pF budget but getting tight — so:
> - Add **external pull-ups ~2.2 kΩ** from SDA→3V3 and SCL→3V3 **at the Pico end**
>   (the sensor's/backpack's internal pull-ups are far too weak for a long line).
> - Firmware runs **I2C1 at 50 kHz** (`I2C1_FREQ`) for extra margin.
> - Pair SDA with a ground and SCL with a ground (or run a 4th "sense" ground) to keep
>   return currents tight; keep this cable away from the 12 V/motor run.
> - **Thicker wire does NOT help** capacitance — it slightly *raises* it. Cat5e's thin
>   conductors are ideal; you only need enough copper for the sensor's ~1 mA (trivial).
> - If it ever misbehaves at length, add a **P82B715 I2C extender** pair (drives tens of
>   metres) — no code change beyond addressing.

### 2-channel 3V3 relay module
| Wire | To | Conductor |
|------|----|-----------|
| VCC | 3V3 bus | 24 AWG |
| GND | GND bus | 24 AWG |
| IN1 | Pico GP16 | 24 AWG |
| IN2 | Pico GP17 | 24 AWG |
| CH1 COM | 12 V bus | 20 AWG |
| CH1 NO | valve **+** | 18–20 AWG (valve run) |
| CH2 COM | 12 V bus | 20 AWG |
| CH2 NO | **long run → AC SSR DC input +** | **18 AWG, 2-cond outdoor cable** |

### Mister solenoid valve (12 V)
| Wire | To | Conductor |
|------|----|-----------|
| + | Relay CH1 NO | 18–20 AWG (length to manifold) |
| − | GND bus | 18–20 AWG |
| (flyback diode 1N4007 across +/−, band → +) | — | — |

### Window actuator (12 V, via BTS7960) — easy run
| Wire | To | Conductor |
|------|----|-----------|
| lead A | BTS7960 M+ | **18 AWG** (stall current) |
| lead B | BTS7960 M− | **18 AWG** |

### BTS7960 H-bridge
| Wire | To | Conductor |
|------|----|-----------|
| B+ | 12 V bus | 18 AWG |
| B− | GND bus | 18 AWG |
| VCC | 3V3 bus | 24 AWG |
| GND | GND bus | 24 AWG |
| RPWM / LPWM | Pico GP18 / GP19 | 24 AWG |
| R_EN + L_EN (tied) | Pico GP20 | 24 AWG |
| R_IS + L_IS | Pico GP26 (optional) | 24 AWG |
| M+ / M− | window actuator | 18 AWG |

### Local AC SSR (at the mains/fan enclosure — long run terminates here)
| Wire | To | Conductor |
|------|----|-----------|
| DC input + | **long run from Relay CH2 NO** (+12 V switched) | 18 AWG (from box) |
| DC input − | GND (run alongside, or local mains-box GND ref) | 18 AWG |
| AC load | fan outlets (mains) | mains-rated, per code |

> ⚠️ Mains wiring on the SSR's load side is done in the **mains-rated enclosure** to
> local electrical code. Only the **low-voltage 12 V pair** enters/leaves that box on the
> long run.

### LCD 1602 (I2C0, panel)
| Wire | To | Conductor |
|------|----|-----------|
| VCC | 3V3 bus | 24 AWG |
| GND | GND bus | 24 AWG |
| SDA | Pico GP4 (shared w/ indoor AHT21) | 24 AWG |
| SCL | Pico GP5 (shared w/ indoor AHT21) | 24 AWG |

### Buttons ×3 (panel momentary)
| Wire | To | Conductor |
|------|----|-----------|
| window: leg A / leg B | Pico GP10 / GND bus | 24 AWG |
| fans: leg A / leg B | Pico GP11 / GND bus | 24 AWG |
| mister: leg A / leg B | Pico GP12 / GND bus | 24 AWG |

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
   **0x27/0x3F**. Then wire I2C1 (outdoor AHT21) with its **2.2 kΩ pull-ups at the Pico
   end**; `machine.I2C(1).scan()` — expect **0x38**. If it doesn't show up, check the
   pull-ups first, then cable length / a P82B715 extender.
5. Add the relay, then the fan chain: verify CH2 closes → 12 V appears on the long run →
   SSR clicks the fans. Then the H-bridge (window jog at low PWM), then the valve.
6. Buttons last.

## Spare / notes

- **GP15 is free** (old DHT single-wire pin) — spare for a limit switch or status LED.
- If the LCD is too dim at 3.3 V: power **LCD VCC from 5 V** and add a BSS138 level
  shifter on the **I2C0 SDA/SCL only**; keep both AHT21s on 3.3 V. (Optional fallback.)
