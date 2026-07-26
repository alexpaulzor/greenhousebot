# Pinout & Wiring — Greenhouse Controller (Pico 2 W / RP2350)

This is the single source of truth for pin assignments. The PCB generator and firmware
should both follow this table. Pin numbers are **GPxx** (GPIO), with physical pin # noted.

## Power rails

| Rail | Source | Feeds |
|------|--------|-------|
| 12 V | 12 V 5 A PSU (fused 7.5 A) | Relay CH1 common, H-bridge B+ (Vmot), buck input |
| 5 V  | Buck converter (set 5.1 V) | Pico **VSYS** (pin 39) via Schottky diode |
| 3V3  | Pico **3V3(OUT)** (pin 36) | AHT21, LCD, relay VCC, H-bridge VCC(logic) |
| GND  | Common | All module grounds + button common tie back to PSU GND (lever-nut bus) |

> The Schottky diode (BOM #14) sits between buck 5 V and Pico VSYS so you can also plug in
> USB for firmware flashing without back-feeding the buck. Do **not** tie buck 5 V directly
> to the Pico's 5 V/VBUS pin.
>
> **LCD runs at 3.3 V** (not 5 V), so the entire I2C bus is 3.3 V and there is **no level
> shifter**. AHT21 (0x38) and the PCF8574 LCD backpack (0x27/0x3F) share GP4/GP5 directly.

## Signal assignments

| Function | Pico pin | Physical | Direction | Notes |
|----------|----------|----------|-----------|-------|
| I2C0 SDA (LCD + AHT21) | **GP4** | 6 | bidir | Straight to **AHT21 SDA + LCD SDA** (shared 3.3 V bus, no level shifter) |
| I2C0 SCL (LCD + AHT21) | **GP5** | 7 | out | Straight to **AHT21 SCL + LCD SCL** |
| *(spare)* | **GP15** | 20 | — | Free — old DHT single-wire pin. Use for a limit switch or status LED. |
| Relay 1 — mister valve | **GP16** | 21 | out | Native-3.3 V relay IN1 |
| Relay 2 — mains trigger (fans) | **GP17** | 22 | out | Native-3.3 V relay IN2 → external outlet box |
| H-bridge RPWM (open window) | **GP18** | 24 | out | BTS7960 RPWM. PWM slice 1A — see PWM note. |
| H-bridge LPWM (close window) | **GP19** | 25 | out | BTS7960 LPWM. PWM slice 1B. |
| H-bridge R_EN + L_EN | **GP20** | 26 | out | Tie both enables together to one GPIO (BTS7960). Drive HIGH to enable, LOW = coast/brake-off (fail-safe). |
| Button + | **GP10** | 14 | in | Active-low, internal `PULL_UP`. Wired via screw terminal to panel button → GND. |
| Button − | **GP11** | 15 | in | Active-low, `PULL_UP` |
| Button OK | **GP12** | 16 | in | Active-low, `PULL_UP` |
| (Optional) actuator current sense | **GP26/ADC0** | 31 | in | BTS7960 IS pins → ADC, for stall detection. Optional. |

### PWM note (RP2350)

GP18 and GP19 are the **A and B channels of the same PWM slice (slice 1)**. That's fine for
the BTS7960 direction-PWM scheme: to move, PWM the active-direction pin and hold the other
**LOW** (never PWM both at once). Both channels share one frequency; set the slice to
~20 kHz (above audible) for the actuator. R_EN/L_EN (GP20) is a plain digital enable, not
PWM — drive it HIGH only while moving, LOW at rest so the bridge coasts (fail-safe).

### Relay drive (resolved: use a native-3.3 V relay module)

The plan uses a **2-channel relay module with native 3.3 V logic** (e.g. JESSINIE 3.3 V
2-ch). Its input stage is designed to trigger from 3.3 V directly, so GP16/GP17 drive it
straight — **no JD-VCC jumper fiddling, buffer transistors, or level shifting on the relay
lines.** Power the module's VCC from **3V3** (it draws little; the opto/relay-driver handles
coil current from that rail on these modules) or from 5V per the module's silk — check the
board. Grounds common with the Pico.

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
[12V 5A PSU]--(fuse 7.5A)--+--> Relay CH1 COM
                           +--> BTS7960 B+ (Vmot)
                           +--> Buck IN+     Buck OUT+ (5V) --(Schottky)--> Pico VSYS
[Pico 3V3]--> AHT21, LCD, relay VCC, BTS7960 VCC(logic)
[Pico GP4/5]--> AHT21 SDA/SCL + LCD SDA/SCL   (shared 3.3V I2C bus, no shifter)
[Pico GP16/17]--> relay IN1/IN2
[Pico GP18/19/20]--> BTS7960 RPWM/LPWM/EN
[Pico GP26]--> BTS7960 IS (current sense, optional)
[Pico GP10/11/12]--> buttons (screw terminals) --> GND
[GP15]--> spare
```

Full solderless wiring (buses, terminals, bring-up order): see `docs/WIRING.md`.
