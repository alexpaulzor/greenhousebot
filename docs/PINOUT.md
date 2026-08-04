# Pinout & Wiring — Greenhouse Controller (Pico 2 W / RP2350)

This is the single source of truth for pin assignments. Firmware follows this table
(mirrored in `firmware/config.py`). Pin numbers are **GPxx** (GPIO), physical pin # noted.

> **Two I2C buses.** The AHT21's I2C address (0x38) is fixed, so the **indoor** sensor
> shares I2C0 with the LCD, and the **outdoor** sensor gets its own bus, **I2C1** (GP2/3).
> Both run at 3.3 V; LCD at 3.3 V means the whole thing needs **no level shifter**.
> The outdoor bus is a **long run (>3 m)** → twisted pair, **external 2.2 kΩ pull-ups at
> the Pico end**, and I2C1 clocked at **50 kHz** (`I2C1_FREQ`). See `docs/WIRING.md`.

## Power rails

| Rail | Source | Feeds |
|------|--------|-------|
| 12 V | 12 V 5 A PSU (fused 7.5 A) | Relay CH1 common, H-bridge B+ (Vmot), buck input |
| 5 V  | Buck converter (set 5.1 V) | Pico **VSYS** (pin 39) via Schottky diode |
| 3V3  | Pico **3V3(OUT)** (pin 36) | both AHT21s, LCD, relay VCC, H-bridge VCC(logic) |
| GND  | Common | All module grounds + button common tie back to PSU GND (lever-nut bus) |

> The Schottky diode (BOM #14) sits between buck 5 V and Pico VSYS so you can also plug in
> USB for firmware flashing without back-feeding the buck. Do **not** tie buck 5 V directly
> to the Pico's 5 V/VBUS pin.

## Signal assignments

| Function | Pico pin | Physical | Direction | Notes |
|----------|----------|----------|-----------|-------|
| I2C0 SDA (LCD + **indoor** AHT21) | **GP4** | 6 | bidir | Straight to indoor AHT21 SDA + LCD SDA (shared 3.3 V bus) |
| I2C0 SCL (LCD + **indoor** AHT21) | **GP5** | 7 | out | Straight to indoor AHT21 SCL + LCD SCL |
| I2C1 SDA (**outdoor** AHT21) | **GP2** | 4 | bidir | Outdoor AHT21 on its OWN bus — AHT21 addr 0x38 is fixed, so two can't share |
| I2C1 SCL (**outdoor** AHT21) | **GP3** | 5 | out | Outdoor AHT21 SCL |
| *(spare)* | **GP15** | 20 | — | Free — old DHT single-wire pin. Use for a limit switch or status LED. |
| Relay 1 — mister valve | **GP16** | 21 | out | Native-3.3 V relay IN1 → 12 V DC solenoid valve |
| Relay 2 — **vent** (exhaust) fan | **GP17** | 22 | out | Native-3.3 V relay IN2 → switches mains fan outlet |
| Relay 3 — **circ** (circulation) fan | **GP21** | 27 | out | Native-3.3 V relay IN3 → switches mains fan outlet |
| H-bridge RPWM (open window) | **GP18** | 24 | out | BTS7960 RPWM. PWM slice 1A — see PWM note. |
| H-bridge LPWM (close window) | **GP19** | 25 | out | BTS7960 LPWM. PWM slice 1B. |
| H-bridge R_EN + L_EN | **GP20** | 26 | out | Tie both enables together to one GPIO (BTS7960). Drive HIGH to enable, LOW = coast/brake-off (fail-safe). |
| Button — **window** mode | **GP10** | 14 | in | Active-low, internal `PULL_UP`. Press CYCLES mode: AUTO→OFF→OPN→CLS. |
| Button — **fans** mode | **GP11** | 15 | in | Active-low, `PULL_UP`. Press CYCLES mode: AUTO→OFF→VNT→CIR→ALL. |
| Button — **mister** mode | **GP12** | 16 | in | Active-low, `PULL_UP`. Press CYCLES mode: AUTO→OFF→ON→TIM. |
| (Optional) actuator current sense | **GP26/ADC0** | 31 | in | BTS7960 IS pins → ADC, for stall detection. Optional. |

### PWM note (RP2350)

GP18 and GP19 are the **A and B channels of the same PWM slice (slice 1)**. That's fine for
the BTS7960 direction-PWM scheme: to move, PWM the active-direction pin and hold the other
**LOW** (never PWM both at once). Both channels share one frequency; set the slice to
~20 kHz (above audible) for the actuator. R_EN/L_EN (GP20) is a plain digital enable, not
PWM — drive it HIGH only while moving, LOW at rest so the bridge coasts (fail-safe).

### Relay drive (native-3.3 V, 3-channel mechanical relays)

Three relay channels, each triggered straight from a GPIO (GP16/17/21) — use a board whose
input stage is designed for **3.3 V logic** (e.g. a JESSINIE-style native-3.3 V module), so
**no JD-VCC jumper fiddling, buffer transistors, or level shifting on the relay lines.**
Power the module VCC from **3V3**; grounds common with the Pico.

The relays are **mechanical, rated 10 A @ 125 V** — well above the fan/valve draw. **There is
no AC SSR** (removed): CH2/CH3 switch the mains fan outlets directly, CH1 switches the 12 V DC
valve feed. The relay board lives in a **mains-rated relay J-box** between the low-voltage
logic box and the mains-outlet J-box, so **only the low-voltage coil side** (VCC/GND/IN1-3)
plus the **12 V valve feed** cross into it — mains never enters the logic box. Full box-by-box
wire list: `docs/CONNECTIONS.md`.

> Legacy caveat (only if you ever substitute a plain "5 V" opto module): such modules may
> not trigger reliably at 3.3 V and can back-drive the GPIO toward 5 V. Fix by feeding the
> opto logic VCC from 3V3 with the JD-VCC jumper removed, or buffer with a 2N7000. Not
> needed with the native-3.3 V board.

### I2C bus (AHT21 + LCD, 3.3 V — no level shifter)

Both devices run at 3.3 V, so GP4/GP5 connect **directly** to each device's SDA/SCL.
Addresses: **AHT21 = 0x38**, **PCF8574 LCD = 0x27 (or 0x3F)** — no clash. The Pico's
internal I2C pull-ups (or the LCD backpack's, now referenced to 3.3 V) are sufficient.

> Fallback only if the LCD is too dim at 3.3 V: power **LCD VCC from 5 V** and add a
> BSS138 level shifter on **SDA/SCL only**, keeping AHT21 on the 3.3 V side. Not expected.

## Window actuator end-stops

Most 12 V linear actuators have **internal limit switches** — they stop drawing current at
end of travel, so you can drive open/close for a fixed time or until current drops. If yours
does **not**, add external limit switches on spare GPIOs (GP13/GP14/GP15 free). Report back.

## Module connections summary

```
[12V 5A PSU]--(fuse 7.5A)--+--> Relay CH1 COM (12V valve feed)
                           +--> BTS7960 B+ (Vmot)
                           +--> Buck IN+     Buck OUT+ (5V) --(Schottky)--> Pico VSYS
[Pico 3V3]--> AHT21, LCD, relay VCC, BTS7960 VCC(logic)
[Pico GP4/5]--> AHT21 SDA/SCL + LCD SDA/SCL   (shared 3.3V I2C bus, no shifter)
[Pico GP16/17/21]--> relay IN1/IN2/IN3   (valve / vent fan / circ fan)
[Pico GP18/19/20]--> BTS7960 RPWM/LPWM/EN
[Pico GP26]--> BTS7960 IS (current sense, optional)
[Pico GP10/11/12]--> buttons (screw terminals) --> GND
[GP15]--> spare
```

Mains side (CH2/CH3 NO → fan outlets) stays in the mains-rated J-boxes — see
`docs/CONNECTIONS.md` for the per-wire checklist and `docs/WIRING.md` for the box layout.

Full solderless wiring (buses, terminals, bring-up order): see `docs/WIRING.md`.
