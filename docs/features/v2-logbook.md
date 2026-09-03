# V2.0 — Compliance Logbook

> First v2 feature. Ships behind feature flag `v2_logbook` (default
> OFF). v1 customers see nothing until the flag is enabled for
> them. Phase E1 documents the rollout patterns; this doc covers
> what the feature is and how it behaves.

---

## What it does

Compliance logbook turns three existing data sources — daily logs,
worker certifications, DOB activity — into a single audit surface
for inspectors and compliance staff:

  • **Calendar view** — a Mon-Sun grid showing per-day status
    (green = OK, yellow = deficient, red = missing, grey = no data).
  • **Drawer per day** — clicking a cell shows the missing items,
    deficiencies, and any LL196 attestations that landed that day.
  • **PDF export** — full audit window rendered to a single PDF
    that an inspector can take with them.

All driven by a new collection `logbook_entries` populated by:

  1. **Missing detector** — fills gaps where a daily log was
     expected (Mon-Fri by default; opt-in weekends per project).
  2. **Deficiency detector** — rules engine flagging daily logs
     with missing required fields.
  3. **LL196 attestation generator** — monthly SST-card attestation
     PDF, uploaded to R2, recorded in the logbook. **On demand only.**
     Nothing schedules it: `generate_ll196_attestation` has one caller
     in the repo (`POST …/logbook/attestations/generate`), and no client
     calls that endpoint. Every attestation that exists was produced by
     an operator running the curl in `docs/operations/runbook.md` §14.5.

---

## Why now

Inspectors have been asking GCs to produce their daily-log compliance
record on demand for years. Pre-V2 the operator had to assemble it
from spreadsheets and the LeveLog activity feed manually. The
logbook is a click-once surface: open `/project/{id}/audit`, click
**Export PDF**, hand the inspector the file.

Side benefit: the deficiency detector catches "missing manpower
count" and "missing weather" issues at write time, not 60 days
later when the GC's lawyer is reading the log under a subpoena.

---

## NYC LL196 background

NYC Local Law 196 of 2017 requires construction workers on
sites of 10+ stories OR specific SH/MD permits to hold a
**Site Safety Training (SST) card** — a mix of OSHA-30 +
fall-protection + supervisor-specific training totalling
40+ hours. GCs are responsible for verifying every worker on
their site has a current card and must produce written
attestations on demand.

**Who is on the filing.** Every worker with a check-in on that
project inside the attestation month, in Eastern time. `checkins`
is the only record written unconditionally for every worker on
every visit, which is what "every worker on their site" needs.
The two other joins were considered and rejected:
`safety_orientations[].project_id` records onboarding rather than
presence and is written on only one of the two gate paths;
`worker_project_trades` refuses to store a pairing for an
`UNASSIGNED` trade, so it omits exactly the men whose paperwork is
least complete. See `lib/logbook/ll196.py::_roster_for_period`.

Until this was fixed the roster query was
`db.workers.find({"project_id": …})`, and `workers` documents
carry no top-level `project_id` — so it matched nothing and every
generated attestation read "All 0 workers in good standing".
A month with genuinely nobody on site now files as
`no_site_activity`, not `complete`.

LeveLog's `validate_worker_certifications` already classifies
SST cards (`SST_FULL` / `SST_LIMITED` / `SST_SUPERVISOR`).
LL196 attestation rolls those classifications up into a
monthly PDF:

  • **Current** — has at least one SST cert with a valid
    expiration date.
  • **No expiration on file** — has SST cert(s) but operator
    didn't enter expiration. Treated as current; flagged for
    follow-up.
  • **Expired** — has SST cert(s) but every one's expiration
    is in the past.
  • **Missing** — no SST cert at all (OSHA-only doesn't
    satisfy LL196 for in-scope sites).

The PDF is uploaded to R2 at a deterministic key
(`ll196/{company_id}/{project_id}/{YYYY-MM}.pdf`) so
re-generation overwrites in place. The corresponding
`logbook_entries` row is upserted on the
`(project_id, entry_date, category)` unique index — same dedupe
guarantee.

---

## Deficiency rules

Each rule is a pure function in `backend/lib/logbook/deficiency.py`.
Each has positive + negative tests pinned in
`backend/tests/test_v2_0_logbook.py::TestDeficiencyRules`.

| Rule | Triggers when … | Waived when … |
|---|---|---|
| `missing_manpower` | `worker_count == 0` or absent | `notes` contains "no work" / "rain day" / "site closed" / "shutdown" / "stop work" |
| `missing_weather` | both legacy `weather` AND split (`weather_temp` / `weather_wind` / `weather_condition`) are empty | any of those fields populated |
| `missing_trade_work` | `work_performed` is empty (notes do NOT substitute) | `work_performed` non-empty |
| `subcontractor_without_insurance` | log references a sub on site whose roster entry has `coi_on_file: false` | every referenced sub has COI on file (or rule abstains when subs context not supplied) |
| `inspection_window_missed` | `project.inspection_windows[]` includes an unmet window past its `by_date` | every window completed or in-future |

The detector runs in two places:

  • **Post-save hook** — immediately after `create_daily_log`
    inserts a new daily log. Gated by the feature flag; wrapped
    in try/except so a hook bug never breaks the daily_log save.
  • **Nightly batch** — 3 AM ET cron tick walks every active
    project's last 30 days of daily logs and re-runs the rules.
    Idempotent via the `(project_id, entry_date, category,
    deficiency_reason)` dedupe key — re-runs produce no
    duplicates.

---

## Endpoints (all flag-gated)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{id}/logbook/audit?start_date=&end_date=` | Calendar grid (per-day status colors) |
| GET | `/api/projects/{id}/logbook/missing` | List of `status=missing` entries |
| GET | `/api/projects/{id}/logbook/deficiencies` | List of `category=deficiency` entries |
| GET | `/api/projects/{id}/logbook/attestations` | List of LL196 attestations |
| POST | `/api/projects/{id}/logbook/attestations/generate` | Trigger LL196 PDF generation for `{year, month}` |
| GET | `/api/projects/{id}/logbook/export?format=pdf` | Full audit window as PDF |

**Gating contract**: every endpoint calls
`is_feature_enabled('v2_logbook', user_id, company_id)` and returns
**404** (not 403) when the flag is off — hides the existence of
v2 features from flag-off probes. Audit log of flag changes is
preserved per E1 (`feature_flag_audit_log`).

---

## Schema

Collection `logbook_entries`:

```js
{
  _id, company_id, project_id,
  entry_date,         // YYYY-MM-DD; matches db.daily_logs.date format
  category,           // "daily_log" | "ll196_attestation" |
                      // "inspection" | "deficiency" |
                      // "manpower" | "material_delivery"
  status,             // "complete" | "missing" | "deficient"
  source,             // "whatsapp" | "manual" | "auto_detected"
  linked_dob_log_ids: [ObjectId],
  deficiency_reason: str | null,
  attestation_data:  object | null,    // populated for LL196
  created_at, updated_at, created_by_user_id,
}
```

Indexes (ensured at startup):

- `(company_id, project_id, entry_date)` — primary query path.
- `(project_id, status)` — filter UI.
- `(project_id, category)` — filter UI.
- `(project_id, entry_date, category)` **unique** — dedupe key
  the missing + deficiency + LL196 detectors rely on for
  idempotent re-runs.

No schema changes to `dob_logs` or `daily_logs` — the logbook is
strictly additive.

---

## Frontend

`/project/{id}/audit` (file: `frontend/app/project/[id]/audit.jsx`).

  • The route file IS in the v1 bundle — flipping the flag on
    doesn't require a fresh deploy. Gating is the React render
    guard `useFeatureFlag('v2_logbook')`.
  • When the flag is OFF, the screen returns `null` BEFORE
    fetching anything. v1 users see nothing — no flicker, no
    loading spinner, no API call.
  • The flag check is the FIRST hook in the component (rules-of-
    hooks: must be unconditional; can't live inside a try/catch
    or after an early return). The C1.1 / C1.3 hook-rules tests
    catch any future regression here.
  • Calendar groups days into weeks of 7; each cell is colored
    per the backend's resolved status. Tapping opens an inline
    drawer below the calendar with that day's missing /
    deficient / attestation entries.
  • Export button calls the PDF endpoint and downloads via
    `window.URL.createObjectURL` (RN-Web supported).

---

## Rollout (per `feature-flags.md` §3)

Recommended sequence:

1. **Owner-only**: enable for the operator's user_id, validate
   end-to-end on production.
2. **Canary**: BLUEVIEW (or similar friendly customer). Watch
   Sentry for a week.
3. **Percentage rollout**: 10% → 50% → 100% over two weeks.
4. **Default ON**: only after sustained 100% with no v1-path
   incidents. This is the signal to delete the v1 code paths
   and remove the flag.

Kill switch: PATCH `/api/admin/feature-flags/v2_logbook` with
`{enabled_globally: false, enabled_percentage: 0,
enabled_for_companies: [], enabled_for_users: []}`. Cache
invalidates within 60s; flag-off behavior is full v1 (zero v2
surface area).

---

## Operational concerns

  • **Cron timing**: 3 AM ET tick runs after the daily-log writing
    window closes. If the operator's customers ever shift to a
    24h timezone-spread, revisit.
  • **Storage growth**: each LL196 attestation PDF is ~10-30 KB.
    At one project per company per month, even 100 customers
    + 5 projects each = 500 PDFs / month = ~15 MB / year. R2
    free tier handles it indefinitely.
  • **Counter cap**: `db.logbook_entries.find({}).limit(500)` on
    the list endpoints. Projects past 500 entries (about 18
    months of daily logs at 5/week + nightly deficiencies) will
    truncate. Worth re-tuning if/when v1.1 introduces pagination
    on this surface.
  • **Idempotency relies on the unique index.** If `_ensure_index_resilient`
    fails to create the index at startup (e.g. a duplicate
    pre-existing across two upgraded instances), the detectors
    will start producing duplicates. Worth a one-shot
    `audit_production.py` check after first deploy.
