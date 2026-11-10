# Progress engine: overnight handoff, Nov 10 2026

Nothing is merged to main, nothing is deployed, and no production data was touched. Every automatic behaviour that has not been validated is off. One PR to main holds everything: **#1007** (`feat/progress-integrated`). Final head and regression numbers are in the last section.

## 1. What was built and tested

| PR | What | State |
|---|---|---|
| #991 | Photo search over daily-log photos | **merged, live** (2324925f) |
| #993 | Report: labels removed, schedule chart | **merged, live** (26413777) |
| #1008 | DOB sign-offs reach the assistant (the "no inspections on 588" bug) | open, base **main**, mergeable alone |
| **#1007** | **The integrated engine**, everything below | open, base main |
| #1000–#1003, #1006 | Stage 1, inspections, schedule logic, photo location, benchmark statistics | inside #1007 |
| #1009–#1018 | Progress model, forecast, evidence sources, report, validation, location matcher, confirmations, 3 fix lanes | merged into #1007's branch |

**How it was tested:**
- Every lane: a control run showing its tests fail on the code before it, plus single planted bugs, each caught (hundreds in total).
- Two independent adversarial reviews, with 22 confirmed defects reproduced and fixed (lanes #1015, #1017, #1018).
- A real PDF render through WeasyPrint in Docker.
- An end-to-end test from evidence to schedule.

## 2. What LeveLog can now understand

Asked over WhatsApp, or printed in the weekly/monthly report, from one model, so the two agree:

- **The whole building:**
  - work done once: demolition, excavation/SOE, foundation;
  - every level by work step, from framing through rough-ins, the five inspections, board and finishes;
  - site and structure steps: superstructure, facade, windows.
- **By subcontractor:** the levels and work each has records on, the span of those records, days present by gate check-in, and what comes next for them in the sequence.
- **By floor:** what is on record, what is "open on the record" (never called a cause), and records that disagree.
- **Against the schedule**, only when a confirmed file exists:
  - planned dates and the file's own predecessor logic;
  - what is past its planned finish with no done evidence;
  - the later work linked to it;
  - estimates only where at least 3 levels have both a start and a done marker, as a labelled range with the sample size.
- **Inspections:** reported by WhatsApp text, voice or a sign-off document.
  - The result is read from the person's own words or the document's text, never the AI's guess.
  - "Didn't pass" stays failed; anything ambiguous stays unresolved and is quoted.
- **DOB:** sign-offs from public data are *verified*. The 4 for 588 were checked live: demolition Jul 8, fence Jul 22, SOE Oct 29, foundation/earthwork Nov 5.
- **Photos:** searched by what they show; placed on a floor only with sufficient evidence.

## 3. How it decides

Every source becomes an evidence item on one ladder: **verified** (DOB, agency) > **confirmed** (signed pour log, super-closed punch) > **attested** (a named person's statement) > **observed** (a photo's description) > **reported** (a daily-log row). **Estimates** stay apart and never count as facts.

| It says | What that needs |
|---|---|
| **Done** | attested or stronger |
| **Underway** | a recent report or photo |
| **Not shown done** | older records with no done record |
| **Unknown** | no record at all, and it **never** means not done |

- **Bottleneck:** the earliest step in sequence order whose prior steps are all done and which has no done record itself, plus inspections with no record or a failure.
- **Percent:** none is computed anywhere. A percent appears only when a source states it, with the source named.

## 4. Measured accuracy and coverage: the honest state

- **Production:** nothing was measured on production data. I have no production access, so every number so far comes from fixtures or the public DOB data. The first real numbers come from your commands below.
- **Location matching:** 12 of 12 on the real 588 strings, but it was written with those strings in view, so that is not a measurement.
- **Photo same-place matching:**
  - unmeasured, and kept OFF;
  - a 2% false-match ceiling needs **at least 149 independently labelled different-place pairs with 0 errors**, two labellers, at least 2 projects and at least 3 construction stages.

**Known weaknesses and data gaps:**
- 588's logs mostly say "floors 1-4", so most work cannot be placed on one floor.
- No inspection results are in public data: DOB NOW, FDNY and DEP all keep them in their own portals.
- 588 has no confirmed schedule, so there are no planned dates and no forecasts.
- No installed quantities exist anywhere, so there are no percents.
- Field roles cannot be messaged first, so targeted confirmations stay in shadow mode.

## 5. To reach dependable accuracy

**Read-only commands to run.** Run them from the repo root on branch `feat/progress-integrated`, each prefixed with `railway run --service Blueview2 --environment production`:
1. `python backend/scripts/progress_validation.py "588"`, then `--all-jobs`. This is the readiness table: placement coverage, inspection and schedule availability, writes attempted (must be 0).
2. `python backend/scripts/location_binder_eval.py dump --project 588 --out locs.csv`. Label the empty columns, then run `score locs.csv --frame locs.frame.json` locally.
3. `python backend/scripts/dm_brain_eval.py --progress-only`, and again with `--cp-email <a CP>`. This runs the real AI in dry-run mode.
4. Locally, no database: `python backend/scripts/dm_brain_eval.py --schedule-file <a real P6/MSP/XLSX export>` and `--signoff <a real sign-off PDF or photo>`.
5. Photo benchmark: `photo_relation_benchmark.py plan --fp-ceiling 0.02 --out pairs.csv`, then `sheet`, then two people label, then `evaluate`.

**Rulings needed:**
- **(a)** Field roles reading DOB data. It is reserved to PM/admin today, yet partly visible through progress answers.
- **(b)** Whether supers and CPs may be messaged first. Confirmations cannot go live without it.
- **(c)** Merge order. #1008 first, alone, is the quick win; then #1007 after your probe output is reviewed.
- **(d)** Upload 588's schedule. CSV uploads were broken on main and are fixed in #1007.
- **(e)** Whether to enable the photo re-read (off; capped at 200 calls a day).

## 6. Final head and full regression

The test run was on head `aa77a772` of `feat/progress-integrated`. Only two commits come after it: this doc, and a test rename (`1af33bbd`). The rename was needed because CI's secret scan read the test name `..._re_pass_said_after...` as a Resend key. No credential was involved.

| Suite | Result | What failed |
|---|---|---|
| Backend `pytest tests` | 15,073 passed, 21 failed, 173 skipped, 8,017 subtests passed | All 21 failures are `test_sheet_tiles`, the Windows pdfium issue that also fails on main |
| Frontend | 220 passed, 5 failed | The 5 files that also fail on main: cardSheenHover, tokens, authScreenFold, navBottomInset, syncCountFromResponse |

No failure was introduced by this branch.

**Highest-value next engineering:**
1. Widen DOB extraction: electrical "Job is complete", elevator and LAA sign-offs.
2. Capture photo time (EXIF) before compression.
3. A one-tap floor on the daily log's crew row, so work can be placed per floor without extra reporting.
