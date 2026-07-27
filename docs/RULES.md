# Control Rules — greenhouse automation spec

Status: **spec + reference implementation** (`firmware/control.py`). Parked, not yet wired
into `main.py` (the shipping MVP is manual-only). Tuned for **_Maxillaria tenuifolia_**
in Walnut Creek, CA.

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
- **Priority tiers, resolved per actuator.** Each actuator (window/fans/mister) takes its
  state from the **highest-priority matching rule**; lower tiers can't override a locked
  actuator. **Safety > temperature > humidity > optimization.** Nothing matches → resting.
  - *Temperature outranks humidity* because heat/cold is the faster killer and humidity is
    cheaply recoverable (just run the mister). This only changes the **window** in a genuine
    conflict — the mister is never set by a temperature rule, so humidity still fully governs
    misting. E.g. hot+dry day → window OPENs to cool (temp wins) while the mister still runs.
- **Time & timezone.** Season (month) and day/night (hour) come from the RTC, set by **NTP
  over WiFi** on boot (UTC), then shifted to **local** time by `TZ_OFFSET_S` in `config.py`
  (Walnut Creek: −25200 PDT / −28800 PST). A ~1 h DST error only nudges the day/night edge
  and never crosses a month boundary, so a fixed offset is fine. **Log** timestamps stay in
  UTC (unambiguous for scraping). If WiFi is down at boot, season is wrong until it syncs.
- **Global guards:** hysteresis on every threshold, mister duty-cycle cap + cooldown,
  hourly circulation. (Implemented in `control.py`.)

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

## Rules (evaluated top-down; higher tier wins per actuator)

| # | Tier | Rule | When | Then | Why (for _M. tenuifolia_ / WC) |
|---|------|------|------|------|-------------------------------|
| S1 | 🔴 Safety | Hard freeze | `Tin ≤ 4` | window **CLOSE**, mister **OFF**, fans **OFF** | Retain heater's warmth; no ice/wet leaves. |
| S2 | 🔴 Safety | Cold protect | `Tin ≤ cold_protect` | window **CLOSE**, mister **OFF** | Chill damage; let the heater hold the floor, don't vent it away. |
| S3 | 🔴 Safety | Heat emergency | `Tin ≥ 30` | fans **ON**; window **OPEN** if `Tout<Tin`; mister **pulse** if `Hin<ceiling` | Survive summer spikes via airflow + evaporative cooling. |
| T1 | 🟡 Temp | Day cooling | `day AND Tin > day_ceiling` | fans **ON**; window **OPEN** if `Tout < Tin−2` | Vent-cool before misting; only if outside is actually cooler. |
| T2 | 🟡 Temp | **Capture night drop** | `night AND Tin > night_hi AND Tout < Tin−2` | window **OPEN** + fans **ON** | The bloom trigger — exploit WC's diurnal swing. |
| T3 | 🟡 Temp | Retain night heat | `night AND Tin ≤ night_lo` | window **CLOSE** | Don't overshoot the cold end of the night band. |
| H3 | 🟠 Humidity | No wet leaves at night | `night` | mister **OFF** | Water on leaves into a cool night → crown/leaf rot. |
| H1 | 🟠 Humidity | Too dry | `Hin < floor` | mister **ON** (duty-limited); **by day** window **CLOSE** if `DPout<DPin` | Dry WC summers; hold moisture by day. Temp rules (T1/T2/T3) already own the window when they fire, so cooling always wins the conflict. |
| H2 | 🟠 Humidity | Too humid | `Hin > ceiling` | fans **ON**; window **OPEN** if `DPout<DPin`; mister **OFF** | Airflow + real drying prevents rot (top orchid killer). |
| A1 | 🟢 Optimize | Air circulation | every hour | fans **ON** ~5 min | Stagnant air breeds fungus; orchids want constant gentle airflow. |
| A2 | 🟢 Optimize | Midday humidity retention | `day AND DPout<DPin AND Hin<ceiling` | window **CLOSE** | Don't bleed humidity into hot dry afternoons; mist instead. |
| — | ⚪ Default | Resting | nothing matches | window **CLOSE**, fans **OFF**, mister **OFF** | Quiescent. |

**Blooming strategy in one line:** enforce the **winter rest** (cooler + drier Nov–Feb via
seasonal setpoints) and **capture every night drop** (T2) — the two things _M. tenuifolia_
needs and that a stable indoor environment usually denies it.

Numbers are starting points; adjust once your wife confirms the rest of the collection.
