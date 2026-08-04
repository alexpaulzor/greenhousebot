# Control Rules — greenhouse automation spec

Status: **live** — `firmware/control.py` is wired into `main.py`. Each automation tick
(`AUTO_TICK_MS`) the controller returns a `Decision` and `Actions.apply_decision()` drives
every actuator whose **mode is AUTO** while the **global automation master** is on. Manual
modes are left untouched. Tuned for **_Maxillaria tenuifolia_** in Walnut Creek, CA.

## Actuator model & per-actuator modes

Four actuators, each with a **mode** you cycle from the panel button or set from the web
(`POST /window|/fans|/mister?a=MODE`). `AUTO` hands that actuator to the rules below; any
other mode is a manual override the controller won't touch (manual is **raw** — e.g. manual
`VNT` runs the exhaust fan regardless of the temperature gate).

| Actuator | Modes | Notes |
|----------|-------|-------|
| **window** | `AUTO / OFF / OPN / CLS` | The Pico-controlled linear-actuator window. NOT the passive wax-cylinder auto-vent (the Pico can neither see nor move that). |
| **fans** | `AUTO / OFF / VNT / CIR / ALL` | Two independent relays: **vent** (exhaust) + **circ** (interior circulation). `VNT`=vent only, `CIR`=circ only, `ALL`=both. |
| **mister** | `AUTO / OFF / ON / TIM` | `ON`=continuous; `TIM`=run `MIST_TIMER_MIN` minutes then auto-revert to AUTO. |

> **Two windows, one controllable.** The exhaust **vent fan** blows out *through* the passive
> auto-vent, so it only moves air once that vent has opened. The Pico can't sense the vent, so
> in AUTO the vent fan is **gated on temperature** as a proxy: below `AUTO_VENT_OPEN_C` (24 °C)
> a wanted vent fan is forced **off** (reason `gate-vent-shut`) — running it into a shut vent is
> just noise. The **circ fan** has no such gate; interior circulation works regardless. The
> gate shapes **AUTO decisions only** — a manual `VNT`/`ALL` runs the fan unconditionally.

## Target species: _Maxillaria tenuifolia_ ("coconut orchid")

Warm-to-intermediate epiphyte (Mexico/Central America). Fragrant coconut-scented blooms.
The common reason it **won't bloom**:

1. **No night temperature drop.** It needs a distinct day↔night differential (aim ≥ 6 °C).
2. **No winter rest.** It wants a **cooler, drier period Nov–Feb** to set spring flowers.

Walnut Creek helps: the dry-climate **diurnal swing** delivers free night drops, and mild
winters make a cool rest easy. The controller's job is to *capture* those (open the window
on cool nights) and *enforce the rest* (cooler, drier setpoints Nov–Feb) — while protecting
against WC's summer heat spikes (35–40 °C) and occasional winter frost.

> **Heater:** a separate thermostat-controlled heater handles minimum temperature. The Pico
> does **not** control it. These rules therefore only ever *retain* heat (close the window,
> stop misting) — they never call for heating.

## Framework

- **Inputs:** `Tin, Hin` (inside), `Tout, Hout` (outside), derived **dew points** `DPin,
  DPout`, plus **hour** (day/night) and **month** (growing vs winter rest).
- **Dew point, not RH, gates venting.** Opening the window only dries the air if outside
  holds *less absolute moisture*: `DPout < DPin`. RH alone misleads (cool foggy 90%-RH air
  can hold less water than warm 65%-RH inside air). If the outdoor sensor is missing, vent
  rules stay conservative (won't open on unknown outside).
- **Priority tiers, resolved per actuator.** Each actuator (window / vent fan / circ fan /
  mister) takes its state from the **highest-priority matching rule**; lower tiers can't
  override a locked actuator. **Safety > temperature > humidity > optimization.** Nothing
  matches → resting.
  - *Temperature outranks humidity* because heat/cold is the faster killer and humidity is
    cheaply recoverable (just run the mister). This only changes the **window** in a genuine
    conflict — the mister is never set by a temperature rule, so humidity still fully governs
    misting. E.g. hot+dry day → window OPENs to cool (temp wins) while the mister still runs.
- **Time & timezone.** Season (month) and day/night (hour) come from the RTC, set by **NTP
  over WiFi** on boot (UTC), then shifted to **local** time by `TZ_OFFSET_S` in `config.py`
  (Walnut Creek: −25200 PDT / −28800 PST). A ~1 h DST error only nudges the day/night edge
  and never crosses a month boundary, so a fixed offset is fine. **Log** timestamps stay in
  UTC (unambiguous for scraping). If WiFi is down at boot, season is wrong until it syncs.
- **Global guards (implemented in `control.py`):**
  - **Vent-fan temperature gate** — `AUTO_VENT_OPEN_C` proxy for "passive auto-vent open"
    (above).
  - **Mister burst duty-cycle** — a steady "want mist" becomes short pulses: `MIST_BURST_S`
    on, then at least `MIST_GAP_S` off, repeating while still wanted (reason `burst-gap`
    during the off phase). Prevents constant-on dripping while keeping humidity topped up.
  - **Hourly circulation** — the circ fan runs ~`CIRC_RUN_S` every `CIRC_PERIOD_S` (rule A1).
- **Not implemented (deferred):** threshold **hysteresis**. Thresholds are currently bare
  comparisons, so an actuator can chatter right at a setpoint; the `AUTO_TICK_MS` cadence and
  the mister burst cycle blunt this in practice. Add per-threshold deadbands if chatter shows
  up in the logs.

## Setpoints (seasonal)

| Setpoint | Growing (Mar–Oct) | Winter rest (Nov–Feb) | Notes |
|----------|------------------:|----------------------:|-------|
| Day temp ceiling (vent above) | 27 °C | 24 °C | Rest runs cooler |
| Night temp band | 15–19 °C | 11–16 °C | Rest nights cooler → bloom trigger |
| Humidity floor (mist below) | 60 % | 50 % | Rest is **drier** on purpose |
| Humidity ceiling (vent above) | 85 % | 80 % | Rot prevention |
| Cold protection (close window) | 12 °C | 8 °C | Warm grower; rest tolerates cooler |
| Hard freeze (all closed/off) | 4 °C | 4 °C | WC frost nights |
| Heat emergency | 30 °C | 30 °C | Summer spikes |
| Night-drop goal | ≥ 6 °C below day | ≥ 6 °C | The key bloom lever |

> These setpoints (and the vent/mist timings + safety limits) are **web-adjustable at
> runtime** — the `&#9881; Settings` panel edits them live and persists to flash, overlaid
> on these defaults at boot. See `firmware/README.md` → "Settings". The values above are the
> shipped defaults sourced from `control.py`.

## Rules (evaluated top-down; higher tier wins per actuator)

| # | Tier | Rule | When | Then | Why (for _M. tenuifolia_ / WC) |
|---|------|------|------|------|-------------------------------|
| S1 | 🔴 Safety | Hard freeze | `Tin ≤ 4` | window **CLOSE**, mister **OFF**, both fans **OFF** | Retain heater's warmth; no ice/wet leaves. |
| S2 | 🔴 Safety | Cold protect | `Tin ≤ cold_protect` | window **CLOSE**, mister **OFF** | Chill damage; let the heater hold the floor, don't vent it away. |
| S3 | 🔴 Safety | Heat emergency | `Tin ≥ 30` | **vent + circ ON**; window **OPEN** if `Tout<Tin`; mister **pulse** if `Hin<ceiling` | Survive summer spikes via airflow + evaporative cooling. |
| T1 | 🟡 Temp | Day cooling | `day AND Tin > day_ceiling` | **vent ON**; window **OPEN** if `Tout < Tin−2` | Vent-cool before misting; only if outside is actually cooler. |
| T2 | 🟡 Temp | **Capture night drop** | `night AND Tin > night_hi AND Tout < Tin−2` | window **OPEN** + **vent ON** | The bloom trigger — exploit WC's diurnal swing. (Vent usually gates off at these night temps.) |
| T3 | 🟡 Temp | Retain night heat | `night AND Tin ≤ night_lo` | window **CLOSE** | Don't overshoot the cold end of the night band. |
| H3 | 🟠 Humidity | No wet leaves at night | `night` | mister **OFF** | Water on leaves into a cool night → crown/leaf rot. |
| H1 | 🟠 Humidity | Too dry | `Hin < floor` | mister **ON** (burst-cycled); **by day** window **CLOSE** if `DPout<DPin` | Dry WC summers; hold moisture by day. Temp rules (T1/T2/T3) already own the window when they fire, so cooling always wins the conflict. |
| H2 | 🟠 Humidity | Too humid | `Hin > ceiling` | **vent + circ ON**; window **OPEN** if `DPout<DPin`; mister **OFF** | Airflow + real drying prevents rot (top orchid killer). Circ runs even when the vent gates off. |
| A1 | 🟢 Optimize | Air circulation | every hour | **circ ON** ~5 min | Stagnant air breeds fungus; orchids want constant gentle airflow. |
| A2 | 🟢 Optimize | Midday humidity retention | `day AND DPout<DPin AND Hin<ceiling` | window **CLOSE** | Don't bleed humidity into hot dry afternoons; mist instead. |
| — | ⚪ Default | Resting | nothing matches | window **CLOSE**, both fans **OFF**, mister **OFF** | Quiescent. |

> **Vent vs circ.** `vent` (exhaust, GP17) is gated on `AUTO_VENT_OPEN_C`; `circ` (interior,
> GP21) never is. Rules that must *move air out* (S3 heat, T1/T2 cooling) call the vent fan;
> rules that just need *air moving inside* (A1 hourly, and the always-on half of H2) call circ.
> H2 and S3 call both, so on a hot/humid day you get exhaust + circulation together.

**Blooming strategy in one line:** enforce the **winter rest** (cooler + drier Nov–Feb via
seasonal setpoints) and **capture every night drop** (T2) — the two things _M. tenuifolia_
needs and that a stable indoor environment usually denies it.

Numbers are starting points; adjust once your wife confirms the rest of the collection.
