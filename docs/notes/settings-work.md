# Task #28 — web-adjustable settings (autonomous /makeitso run)

Goal: promote the behavioral tuning constants to a **web-editable, reboot-persistent**
store, per the user's note "many of these constant vars will become settings I adjust via
the webui."

## Design (decided, proceeding)

- New **pure** `firmware/settings.py`: `Settings` class driven by a `SPEC` list (single
  source of truth for defaults + validation metadata + UI order). Host-testable.
  - Defaults sourced from `config.py` (auto_vent_open_c, mist_*, temp_unit) and
    `control.py` (seasonal setpoint tables + control-only globals). No duplication of
    default *values* — settings SPEC pulls them from those modules.
  - `get / as_dict / specs / update / load(store,path) / save(store,path)`.
  - `update()` coerces + **clamps** numbers to [min,max]; rejects unknown keys + bad
    choices. (Clamp chosen over reject: friendly for a hobby web UI; the input widgets
    also carry min/max.)
- `control.Controller(settings=...)`: reads setpoints/globals **live** from the settings
  object each tick. When `settings is None` (all 18 existing control tests), behavior is
  byte-identical to today (falls back to the module constants). One-way dep: settings →
  control/config; control never imports settings (avoids circular import).
- `actions.Actions(..., settings=None, save_settings=None)`: exposes `get_settings()` /
  `set_settings(incoming)`; on update re-derives its two derived scalars (`temp_unit`,
  `mist_timer_min`) and calls the injected `save_settings` persister. Hardware-free.
- `webapp`: `GET /settings` (specs+values), `POST /settings?k=v&...` (update). Settings
  UI = a collapsible `<details>` that renders grouped number/select inputs + Save.
- `main.py`: build `Settings`, load from flash (`FsAdapter`), pass to Controller+Actions,
  persist on change. `config.SETTINGS_FILE = "settings.json"`.

## Adjustable settings (24)

Growing (6) + Winter rest (6) setpoints; Safety (hard_freeze, heat_emergency);
Venting (auto_vent_open_c, vent_margin); Circulation (circ_period_s, circ_run_s);
Misting (mist_burst_s, mist_gap_s, mist_timer_min); Schedule (day_start, night_start);
Display (temp_unit F/C).

Deliberately NOT web-adjustable: pins, I2C freqs, log ring/file sizes, web port, WiFi,
tz offset, PWM/travel timing — infra, not day-to-day tuning. (Revisit if asked.)

## Decisions / assumptions (flag for user)

- D1: clamp out-of-range values silently rather than reject. Assumption: friendlier.
- D2: **REVISED after adversarial review.** Added *ordering* guards (a change that would
  invert a low/high pair snaps back): `day_start < night_start` (else `is_day()` is always
  false → all daytime cooling silently disarmed), and `night_lo <= night_hi`,
  `humid_floor <= humid_ceiling` for both seasons. Other cross-field checks (hard_freeze vs
  cold_protect) left out — S1/S2 both just retain heat, so no real hazard.
- D3: settings.json lives at flash root (survives a logs-dir wipe).
- D4: settings POST reuses the query-string convention the mode buttons already use (no
  request-body parsing in webserver.py), so the form submits `?k=v&...`.
- D5: which constants to expose — chose the 24 behavioral knobs above; left infra out.

## Adversarial review — findings addressed
Reviewer (subagent) ranked 6 findings; verdict "safe to ship for a hobby build." Actions:
- #1 cross-field day/night silently disarms cooling → **fixed** (ORDER_CONSTRAINTS guard).
- #2 non-atomic save wipes tuning on brownout → **fixed** (temp file + rename).
- #3 every Save rewrites flash even with no change → **fixed** (update() applies only keys
  that actually changed; no-op Save writes nothing).
- #4 heat_emergency clamp allowed 45 °C (plant-lethal) → **fixed** (max lowered to 40).
- #5 `_qs` didn't URL-decode values → **fixed** (added `_unquote`; latent, now covered).
- #6 single recv(1024), no drain loop → **documented** (request line ~0.5 KB, well under;
  comment marks the ceiling; restructuring the non-blocking recv wasn't worth the risk).
- Confirmed-fine (no change): settings=None parity, MicroPython JSON round-trip, dict
  ordering (specs() iterates SPEC), offline JS panel, FsAdapter mkdir(".").

## Open questions (batch at end)
- Q1: OK to expose exactly these 24? Want AUTO_TICK_MS / SAMPLE_MS / OUTDOOR_ENABLED too?
- Q2: clamp vs reject on out-of-range (D1)?
- Q3: cross-field guards — I added ordering guards for day/night + bands + humidity (D2).
  Want more (hard_freeze<=cold_protect), or fewer?
- Q4: commit these WIP changes? (not pushing.)

## Status
- [x] settings.py + tests (15 tests)
- [x] control.py settings-aware + tests (settings-override + settings-none-parity)
- [x] actions.py get/set_settings + tests (derive/persist/log/no-op/empty)
- [x] webapp routes + UI + tests (GET/POST /settings, qs decode)
- [x] main.py wiring + config.SETTINGS_FILE + LCD unit-aware
- [x] sim/simulate.py wired with a live Settings (UI exercisable in the sim)
- [x] docs (firmware/README, README TODO, RULES.md note)
- [x] full suite green: control 20, actions 9, datalog 9, webapp 15, settings 15 = **68**
- [x] headless smoke: sim seed + GET/POST /settings + live controller re-read = OK
- [x] adversarial review — 5 of 6 findings fixed, 1 documented (see section above)

Final count of adjustable settings is **24**: growing 6 + rest 6 + safety 2 + venting 2 +
circulation 2 + misting 3 + schedule 2 + display 1.

