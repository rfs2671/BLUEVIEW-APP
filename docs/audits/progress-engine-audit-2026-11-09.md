# Progress and schedule engine: repository audit, 2026-11-09

Read from the code at main 2324925f. No production data was read; every statement about production is marked.

## The end-goal question, today

"What's holding up drywall on Floor 3?" needs five kinds of evidence. Status of each:

| Evidence | In Levelog today | Consequence |
|---|---|---|
| Work reported, by sub and place | Yes: filed daily logs. Place is free text, often "floors 1-4" together | Reported, but usually not for one floor alone |
| The sequence | Yes: `app/scheduling/graph_v1.py`, operator-approved template, five gates before drywall. Nothing reads it for status | Reused as "what normally comes first" |
| Inspections and approvals | **No.** DOB inspection ingest was removed (`server.py:41964`); RFIs, submittals and holds have no records | Every gate is unknown. This is the largest gap |
| Schedule | Parser and confirmed-baseline store exist. **Predecessor links are discarded at import** (`schedule_import.py:508-536,700-707`). 588's last report says none is confirmed | No planned date, delay or forecast without a confirmed file |
| Quantities | **No verified installed quantity anywhere.** Takeoff is design counts | No percent can be computed, and none is |

## What exists and is reused

- **Place:** `(project, level token, optional space)`. Level tokens are `lib/plans/level_suggestion.py`'s closed set; `space` is the printed tag in `plan_records.unit`. There is no unit or room collection, and five naming vocabularies exist. `progress_report.floors_in` and `punch.read_location` are reused to read free text.
- **Filed logs:** `_report_rows` with `collapse_amendment_chains`: the report's own loader, so amendments and withdrawals behave identically.
- **Photos:** `photo_index` (shipped in #991).
- **Stop-work:** `report_regulatory.build`.
- **Schedule:** `project_schedules` confirmed row. Baseline stays in the file document; nothing here writes to it.
- **Model plumbing:** `vision_meter`, `_vision_jpeg`, the DM brain's tool list and number guard.

## Actual gaps, in the order they block the end goal

1. **No inspection or approval record.** No code can close this: someone has to enter results, or a feed has to exist. Needs a product decision.
2. **Logs rarely name one floor.** Measured only by the probe below.
3. **No per-photo place.** No GPS or EXIF is kept, no per-photo tag exists; the crew row's location is the only signal.
4. **Predecessors dropped at import.** Fixable; the original file is in R2 when storage succeeded.
5. **Two writers share `project_schedules`.** `app/scheduling/engine.py:350` writes status-less rows and its reader has no status filter. Must be separated before a forecast is added.
6. **`open_items` reads `db.daily_logs`,** which the code calls April test data (`server.py:65773`). A live assistant tool reading a dead collection; separate fix.
7. **`photo_index` is keyed to originals,** so a superseded original can be indexed. `work_state` filters by effective log; `find_photos` does not yet.

## Built in this change (stage 1)

- `lib/work_state.py`: places, whole-word work classification, per-package state (reported / observed / verified / unknown, never a percent), prerequisites from `graph_v1`, text for the assistant. Computed at read time: no stored state.
- `lib/photo_relations.py`: targeted pair selection and a checked two-photo comparison. **Off** unless `PHOTO_RELATIONS_ENABLED=1`.
- WhatsApp tool `work_status`.
- `backend/scripts/work_state_probe.py`: read-only check on real data.

## What cannot be verified yet

| Claim | Why not | How to verify |
|---|---|---|
| How many log rows name one floor; which phrases don't classify | No production access from here | Run the probe |
| The vision model can tell one place from another | Never run on real photos; no API key or photos here | Enable on one job, review 20 pairs by hand before trusting |
| The `graph_v1` sequence fits a given job | It is a template; the file itself notes no signed sign-off | Superintendent review |
| The assistant phrases this correctly | The model was scripted in tests | Ask it live |

## Not built, on purpose

- **Delay, downstream impact, lookahead, forecast** need a confirmed schedule with its logic. Building them on no schedule would be invention.
- **Production rates** need measured quantities.
- **Dashboard** waits for the probe. A floor-by-sub grid is only honest if logs name floors.
- **Correction learning** waits until there is an answer people can correct.

## Proposed order

1. Stage 1 (this change), then run the probe on 588.
2. Inspection and approval records: the smallest entry a super will actually use.
3. Per-floor capture on the log row or photo, if the probe shows rows are mostly shared.
4. Keep predecessors at import; separate the two `project_schedules` writers; plan-versus-actual and lookahead from a confirmed file.
5. Dashboard by floor and sub; report integration.
6. Superintendent corrections, append-only with an audit trail and regression cases.
