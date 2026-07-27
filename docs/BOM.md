# Bill of Materials — Greenhouse Controller

Architecture (locked with the builder):

- **No PCB — solderless terminal-block build.** The circuit is just power-rail fan-out
  + a 2-wire I2C bus, so a Pico screw-terminal expander + Wago lever-nuts do the job.
  Nothing sensitive is soldered. See `docs/WIRING.md`. (The `pcb/` Python tooling and
  `kicad/` files are kept as a reference/learning artifact but are **not** the build.)
- **Mains AC stays out of the logic box** — the Pico drives an *external, sealed,
  properly-rated outlet box* over a dry-contact trigger. No mains ever enters the box.
- **Single 12 V 5 A supply** feeds the valve, the H-bridge (window actuator), and a buck
  converter that produces 5 V for the Pico.
- **Housing = a purchased, already-sealed plastic bin** mounted outdoors by the door,
  with a single cable gland. (A swappable LCD faceplate + MakerBeam module mounts are
  **deferred TODOs**, not in this BOM.)
- **Sensor confirmed: AHT21** (I2C 0x38) — **two of them**: indoor (I2C0 with the LCD)
  and outdoor (I2C1 on GP2/3; separate bus because the address is fixed). **LCD run at
  3.3 V**, so both buses are 3.3 V and **no level shifter is needed**.

Prices are rough USD ballparks for hobby quantities; use them for sizing, not budgeting.

> ☀️ **Thermal note:** component heat inside the bin is tiny (~1.5 W steady, ~3 W while
> the actuator moves) — **no vent needed**. The real risk is **solar gain**: a sealed bin
> in direct sun can hit 50–70 °C internally. Mount in shade / use a light-colored bin,
> and choose parts rated to ≥85 °C (105 °C caps if you add any).

---

## 1. Core electronics

| # | Item | Qty | Notes | ~$ |
|---|------|-----|-------|----|
| 1 | Raspberry Pi Pico 2 W (with headers) | 1 | RP2350, Wi-Fi. Plugs into a screw-terminal expander (item 26) — **not soldered**. | 7 |
| 2 | Temp/humidity sensor — **AHT21** (I2C, 0x38) ×2 | 2 | Confirmed part; 2.0–5.5 V, runs at 3.3 V. **One indoor** (on I2C0 with the LCD) + **one outdoor** (on I2C1, GP2/3 — needs its own bus because 0x38 is a fixed address). Outdoor unit lets the firmware compare in/out conditions. | 2–4 ea |
| 3 | I2C character LCD — **1602** | 1 | 16×2 with PCF8574 I2C backpack (0x27/0x3F). **Run at 3.3 V** so the whole bus is 3.3 V. 2004 is a firmware-only upgrade later. | 4–9 |
| 4 | ~~2-channel I2C level shifter (BSS138)~~ | 0 | **Not needed** — LCD runs at 3.3 V, so the I2C bus is all 3.3 V. Keep one on hand only as a fallback if the LCD is too dim at 3.3 V. | — |
| 5 | **2-channel relay module, native 3.3 V logic** (opto-isolated, low-level trigger) | 1 | e.g. the JESSINIE 3.3 V 2-ch board. ch1 = 12 V mister valve, ch2 = dry-contact mains trigger for the external outlet box. Native 3.3 V logic drives straight from the Pico. | 3–5 |
| 6 | BTS7960 H-bridge module (43 A) | 1 | Drives the 12 V window linear actuator. Confirmed owned. | 6 |
| 7 | Buck converter 12 V→5 V, ≥3 A, adjustable (e.g. LM2596 / MP1584 / D24V module) | 1 | Set to 5.1 V. Powers Pico VSYS. Prefer a synchronous module (Pololu) for efficiency/heat. | 3 |

## 2. Actuators / loads (you likely already own these)

| # | Item | Qty | Notes |
|---|------|-----|-------|
| 8 | 12 V solenoid valve (overhead misters) | 1 | Normally-closed recommended (fails safe = misters off). Note its current draw. |
| 9 | 12 V linear actuator (window) | 1 | **Report stroke length and rated/stall current** — sizes the PSU and confirms BTS7960 vs DRV8871. Most have internal end-of-travel limit switches. |
| 10 | Fans on A/C outlet | 1+ | Switched by the external outlet box (see §4). |

## 3. Power

| # | Item | Qty | Notes |
|---|------|-----|-------|
| 11 | 12 V DC power supply — **12 V 5 A (60 W)** | 1 | **Confirmed owned; powers the window fine.** Enclosed, sealed if near the greenhouse. |
| 12 | DC barrel jack or 2-pos screw terminal (12 V in) | 1 | Panel-mount or inline. |
| 13 | Inline fuse holder + fuse (**7.5 A**) | 1 | On the 12 V input. ~1.25× the 5 A supply. Cheap insurance. |
| 14 | Schottky diode, 1 A (e.g. SS14 / 1N5819) | 1 | Buck 5 V → Pico VSYS so USB and buck can coexist without back-feeding. |
| 15 | Flyback diode 1N4007 (if relay/valve boards lack one) | 1–2 | Across the valve. Most relay modules include coil flybacks. |
| 16 | Bulk capacitor 470–1000 µF / 25 V, **105 °C** electrolytic | 1–2 | One on 12 V near the H-bridge, one on 5 V. Tames actuator inrush. 105 °C rating for solar heat. |
| 17 | 100 nF ceramic decoupling caps | 3–4 | At Pico 3V3, sensor, LCD. Ceramics are fine to 85–125 °C. |

## 4. External mains outlet box (mains stays HERE, not in the logic box)

> ⚠️ **Mains AC. Do this in a separate, properly-rated enclosure.** Follow local
> electrical code; when in doubt, have it checked.

**Two-stage fan control (chosen design):** the 3V3 relay (item 5, CH2) closes a **dry
contact** that sends a robust **12 V signal** over the long run to a **local AC SSR** at
the mains enclosure, which switches the fan outlets. This avoids driving an SSR's DC
input from 3.3 V over distance (flaky) and keeps mains out of the logic box. See
`docs/WIRING.md` → "Fans: two-stage relay chain".

| # | Item | Qty | Notes |
|---|------|-----|-------|
| 18 | **AC solid-state relay (SSR)**, mains-rated 10–25 A, **DC input 3–32 V** | 1 | Mounted in/adjacent to the mains-rated fan enclosure. 12 V drives its input comfortably. Add a heatsink if near its current rating. |
| 18b | *(alt)* Commercial 12 V-triggered relay outlet / smart plug | — | Least-DIY substitute for items 18 + the outlet box. |
| — | Mains-rated outlet box + duplex receptacle + glands | 1 | Houses the SSR + fan outlets; grounded, to code. |

## 5. Housing & UI hardware

Housing is a **purchased, already-sealed plastic bin** — no laser-cut shell in this build.

| # | Item | Qty | Notes |
|---|------|-----|-------|
| 19 | Sealed plastic bin / junction box (IP65+), **light colored** | 1 | Big enough for the Pico expander + modules + lever-nuts with headroom. Light color to reduce solar gain. Mount in shade if possible. |
| 20 | Cable gland(s), IP68 | 1–2 | One main gland for the bundled 12 V / valve / actuator / sensor / mains-trigger / button wiring, facing **down**. |
| 21 | Momentary push buttons (+ / − / OK), panel-mount w/ leads | 3 | **Confirmed owned.** Mount in the panel; flying leads land on the Pico-expander GP terminals + GND bus. |
| 22 | Standoffs / adhesive mounts | a few | Keep modules off the bin floor / any condensation. |
| 23 | Conformal coating or acrylic lacquer | opt | Optional now (nothing milled). Can coat module boards against condensation. |

> **Deferred (not in this BOM):** swappable laser-cut LCD/button faceplate, MakerBeam
> (15×15) module-mount plates. Parked until the internals are proven.

## 6. Interconnect (solderless — no PCB)

Build is terminal-block / lever-nut based. See `docs/WIRING.md` for the full map.

| # | Item | Qty | Notes |
|---|------|-----|-------|
| 25 | **Raspberry Pi Pico screw-terminal expander** | 1 | Pico plugs in; every GPIO → labelled screw terminal. The key part that makes this solderless. |
| 26 | **Wago 221 lever-nuts** (mix of 2/3/5-way) | ~6 | Fan-out for GND, 3V3, 12V buses. Reopenable, humidity-tolerant. |
| 27 | Hookup wire, 18 AWG (power/motor) / 22–24 AWG (signal) | set | Ferrules recommended for screw terminals. |
| 28 | Dupont / ferruled leads for module terminals | set | AHT21, LCD, relay, buck, BTS7960 headers. |
| 29 | **Cat5e / twisted-pair cable** for the outdoor sensor run (>3 m) | 1 | Twisted pairs keep I2C capacitance low; thin conductors are fine (sensor draws ~1 mA). |
| 30 | **2.2 kΩ resistors** ×2 (I2C1 pull-ups) | 2 | SDA→3V3 and SCL→3V3 **at the Pico end** — required for the long outdoor bus. |
| 31 | 18 AWG 2-conductor outdoor cable (fan SSR run) | 1 | Carries the switched 12 V signal from relay CH2 to the local AC SSR. |
| 32 | *(if needed)* P82B715 I2C extender pair | 0–1 | Only if the outdoor bus is flaky at length; drives tens of metres. |

> Nothing sensitive is soldered: Pico socketed in the expander; modules wire to their
> existing headers/terminals. (The two 2.2 kΩ pull-ups are the only discrete parts — land
> them in a lever-nut or a screw terminal, no soldering needed.)

---

## Sizing — settled

The **12 V 5 A PSU is confirmed and drives the window fine**, so PSU/fuse sizing is
closed (7.5 A fuse). BTS7960 is confirmed owned.

One thing still worth checking (not blocking): whether the actuator has **internal limit
switches** (most do — it stops drawing current at the end of travel, so firmware can
drive-until-current-drops or drive-for-a-fixed-time). If it does **not**, add external
limit switches — GP13/GP14 are free, and GP15 is also now spare.
