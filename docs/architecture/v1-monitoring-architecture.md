# LeveLog v1 — Monitoring Architecture

**Status**: Accepted (canonical product description)
**Date**: 2026-05-04 (MR.14 commit 5 — final cleanup)
**Supersedes**: `akamai-bypass-decision.md` (MR.5–MR.13 renewal-automation work)
**Decider**: Operator (Roy Fisman) + claude-code engineering session

This is the canonical product description for LeveLog v1. It
replaces every prior architecture note that described filing
automation, worker containers, or stored DOB NOW credentials —
none of those exist in v1. If a future v2 revisits filing
automation, write a new ADR. Don't edit this one.

---

## TL;DR

LeveLog v1 is a **DOB compliance monitoring + notification
product** for NYC General Contractors. Four phases, end to end:

```
   ┌────────────┐   ┌─────────┐   ┌────────────┐   ┌───────────────┐
   │  Signals   │ → │ Diffing │ → │  Activity  │ → │   Renewal     │
   │ (Socrata)  │   │  (state │   │   Feed     │   │   Start       │
   │  poll      │   │  change │   │  + email   │   │  (manual @    │
   │  every 15m │   │  detect)│   │  routing)  │   │   DOB NOW)    │
   └────────────┘   └─────────┘   └────────────┘   └───────────────┘
```

LeveLog never files anything. The operator files manually at DOB
NOW; LeveLog tracks the click and detects completion via the same
Open Data feed that drives signal monitoring.

---

## Phase 1 — Signals (Socrata polls)

The backend polls 14 NYC Open Data Socrata datasets every 15 minutes
(`nightly_dob_scan` cron) plus the 311 dataset every 30 minutes
(`dob_311_fast_poll`). All datasets are scoped per-project via the
project's BIN or address; we only fetch records relevant to the
GC's tracked projects.

| signal_kind family | Source dataset(s) | Refresh window |
|---|---|---|
| `permit_issued`, `permit_expired`, `permit_revoked`, `permit_renewed` | `rbx6-tga4` (DOB NOW Build), `dm9a-ab7w` (DOB NOW Electrical), `ipu4-2q9a` (BIS legacy) | 15 min |
| `filing_approved`, `filing_disapproved`, `filing_withdrawn`, `filing_pending` | `w9ak-ipjd` (DOB NOW filings) | 15 min |
| `violation_dob`, `violation_ecb`, `violation_open`, `violation_resolved` | `855j-jady` (DOB NOW Safety), `3h2n-5cm9` (BIS legacy), `6bgk-3dad` (ECB/OATH) | 15 min |
| `stop_work_full`, `stop_work_partial` | `3usq-5cid` (Stop Work Orders) | 15 min |
| `complaint_dob` | `eabe-havv` (DOB Complaints Received) | 15 min |
| `complaint_311` | `erm2-nwe9` (311), filtered to ~14 construction-relevant complaint types | 30 min |
| `inspection_scheduled`, `inspection_passed`, `inspection_failed`, `final_signoff` | `p937-wjvj` (DOB Inspections) | 15 min |
| `cofo_temporary`, `cofo_final`, `cofo_pending` | `pkdm-hqz6` (Certificate of Occupancy) | 15 min |
| `facade_fisp` | `xubg-57si` (FISP façade) | 15 min |
| `boiler_inspection` | `52dp-yji6` (Boiler) | 15 min |
| `elevator_inspection` | `e5aq-a4j2` (Elevator) | 15 min |
| `license_renewal_due` | Internal — derived from filing_reps + GC license metadata | daily 7 AM ET |

Auth: NYC Socrata supports anonymous polling but throttles
aggressively. Set `NYC_SOCRATA_APP_TOKEN` for higher quotas.

## Phase 2 — Diffing (state-change detection)

Every poll compares the incoming record's status against the
most-recent `dob_logs` entry's `current_status`. Two outcomes:

- **Status unchanged** → update mutable fields in place. No new row.
- **Status changed** OR **first time seen** → insert a new transition
  row stamped with `previous_status`, `current_status`,
  `status_changed_at`, and `is_seed_transition`. The transition row
  is what the activity feed surfaces.

`is_seed_transition` (added in MR.14 commit 4a, replacing the
fragile `MR14_SEED_WINDOW_START` time-window heuristic) is `true`
when the existing legacy doc lacked the `current_status` field —
that is, the row exists ONLY because the upgrade introduced status
tracking, not because anything changed at DOB. The activity feed
filters these out by default; admins can opt in via
`?include_seed=true`.

## Phase 3 — Activity feed + notifications

The classifier (`backend/lib/dob_signal_classifier.py`) maps
`record_type + status` → one of ~25 `signal_kind` values. The
templates layer (`backend/lib/dob_signal_templates.py`) renders
each `signal_kind` into a `{title, body, severity, action_text}`
tuple speaking to GC / PM / Site Manager who has never used DOB —
DOB jargon (PAA, FISP, CofO, TCO, OATH) gets inline parenthetical
explanation.

Severity → notification routing
(`backend/lib/dob_signal_notifications.py`) and per-user
preferences (`backend/lib/notification_preferences.py`).

**Defaults — Critical-only-by-default (Phase B1a.1)**: a user
without a saved `notification_preferences` record gets:

| Signal_kind | Delivery |
|---|---|
| `violation_dob`, `violation_ecb`, `stop_work_full`, `stop_work_partial`, `inspection_failed`, `filing_disapproved` | Immediate email |
| All other 20 signal_kinds | Feed-only (Activity tab; no email) |

Channel routing fallback (applies only to FUTURE-added signal_kinds
not in the explicit per-signal default overrides):

| Severity | Channel |
|---|---|
| Critical | `[email]` |
| Warning | `[]` (feed-only) |
| Info | `[]` (feed-only) |

Customers opt in to more aggressive routing via the B1b settings
UI presets (`Standard`, `Everything`) or per-signal customization.
The Critical-only default replaced B1a's "Michael defense-in-depth"
pattern (`critical=[email], warning=[email] (digest), info=[in_app]`)
after customer feedback on the original B1b UI flagged that the
default was still too noisy. Pinned by
`test_default_channel_routes_critical_only_pattern` and
`test_default_signal_kind_overrides_critical_only_pattern` in
`test_notification_preferences.py`.

Every email path routes through `lib.notifications.send_notification`
(MR.14-incident consolidation). Properties:

- **Universal kill switch**: `NOTIFICATIONS_KILL_SWITCH=1` halts
  ALL outbound mail within seconds; no restart required (env read
  fresh on every send).
- **trigger_key idempotency**: the (entity_id, trigger_type,
  recipient) triple dedupes within a 23-hour window; reruns of the
  same scan don't double-send.
- **notification_log audit trail**: every send is recorded with one
  of 6 status values: `sent | suppressed_idempotent |
  suppressed_kill_switch | suppressed_flag_off | suppressed_no_key
  | failed`.

Frontend Activity tab (`/project/{id}/activity`): server-rendered
template output with severity-coded cards, filters (signal_kinds,
severity, date range, unread, search), per-row mark-as-read,
mark-all-read, pull-to-refresh, mobile bottom-sheet filter UI.

TTL retention on `dob_logs`: 90 days for most record_types, 365
days for `violation` + `swo`.

## Phase 4 — Renewal Start (manual file, LeveLog tracks)

When the v2 dispatcher emits `action.kind == "manual_renewal_dob_now"`
(the MANUAL_1YR_CEILING strategy in `backend/lib/eligibility_v2.py`),
the renewal card in the operator UI surfaces the **Start Renewal**
affordance.

```
operator opens permit-renewal page
         │
         ▼
ManualRenewalPanel renders FilingStatusCard
         │
         ▼ (renewal not started yet)
[Start Renewal] button + readiness check
         │
         │ click
         ▼
POST /api/permit-renewals/{id}/start-renewal-clicked
         │
         ├──── records `manual_renewal_audit_log` entry on
         │     the renewal doc (event_type=manual_renewal_started,
         │     timestamp, actor)
         ├──── stamps `manual_renewal_started_at` +
         │     `manual_renewal_started_by` on the renewal doc
         └──── returns the MR.4 PW2 mapper output
                                │
                                ▼
              frontend opens DOB NOW (new tab) +
              renders <StartRenewalPanel/> with grouped
              click-to-copy fields:
                • Applicant Info
                • Job & Permit
                • Renewal Details
                • Required Attachments
                • [warnings] Missing required fields
                • [info]    Informational only
                • Notes
                                │
                                ▼
       operator copies values into DOB NOW manually
                                │
                                ▼
             FilingStatusCard renders the
             "Filing in progress" state (driven by
             renewal.manual_renewal_started_at)
                                │
                                ▼
       operator submits at DOB NOW; the new permit
       lands in NYC Open Data within minutes
                                │
                                ▼
   MR.8 dob_approval_watcher (15-min cron) sees the
   new permit row, computes new_expiration_date,
   flips renewal.status → COMPLETED, stamps
   renewal.new_expiration_date
                                │
                                ▼
        FilingStatusCard renders the "Renewed" state:
        confirmation # + new expiration + "View on DOB NOW"
```

Three render branches in `FilingStatusCard.jsx`, all driven by
fields ON the renewal doc (no polling, no filing_jobs):

1. **Pre-renewal**: `manual_renewal_started_at` is null AND
   `status != 'completed'`. Shows the Start Renewal button +
   readiness check.
2. **In-progress**: `manual_renewal_started_at` is set AND
   `status != 'completed'`. Shows "Filing in progress" reminder +
   a "View values again" link that re-opens the panel without
   re-recording the click.
3. **Renewed**: `status === 'completed'` OR `new_expiration_date`
   is set. Shows the new expiration + DOB confirmation # (if
   present) + a "View on DOB NOW" deep-link.

Detection: same `dob_approval_watcher` that's been in production
since MR.8. It matches by job_filing_number / BIN against NYC
Open Data DOB NOW filings, so the operator's manual filing at
DOB NOW lands in the same dataset the watcher polls. **No new
infrastructure** is needed for "did the user actually file" detection.

---

## Data model

| Collection | Purpose |
|---|---|
| `companies` | One per GC. License + insurance metadata, `filing_reps[]` roster (no credentials post-MR.14 4b). |
| `projects` | Per-jobsite. `track_dob_status` defaults to `true`; polled when BIN or address resolves. |
| `dob_logs` | Append-only stream of DOB signals. One row per (raw_dob_id, transition). Carries `signal_kind`, `current_status`, `previous_status`, `status_changed_at`, `is_seed_transition`, `read_by_user[]`. |
| `permit_renewals` | 30-day-window sweep records. v1 surfaces them through the Start Renewal UX. Click-tracking fields added in MR.14 commit 4c: `manual_renewal_started_at`, `manual_renewal_started_by`, `manual_renewal_audit_log[]`. |
| `notification_log` | Append-only audit of every email send. Status: sent / suppressed_idempotent / suppressed_kill_switch / suppressed_flag_off / suppressed_no_key / failed. |
| `filing_jobs` | Historical pre-MR.14-4a worker queue. Read-only in v1; nothing inserts new rows. Surfaced via `GET /filing-jobs` for the FilingHistorySection (auto-hides when empty). |

Removed in MR.14:

| Collection / field | Removed in | Operator action |
|---|---|---|
| `companies.filing_reps[].credentials` | 4b | Run `migrate_clear_filing_rep_credentials.py` |
| `agent_public_keys` collection | 4b | `db.agent_public_keys.drop()` |

---

## Polling cadences

| Job | Cadence | Source |
|---|---|---|
| `nightly_dob_scan` (function name; runs every 15 min) | 15 min | DOB Socrata datasets (10) |
| `dob_approval_watcher` | 15 min (offset +5 min) | Reads cached dob_logs vs current `permit_renewals.AWAITING_DOB_APPROVAL` |
| `dob_311_fast_poll` | 30 min (offset +7 min) | 311 dataset |
| `renewal_reminder_cron` | daily 7 AM ET | renewal docs |
| `nightly_compliance_check` | daily 10 PM ET | internal logbooks |
| `renewal_digest_daily` | daily 7 AM ET | per-company digest |

---

## Notification kill switch

`NOTIFICATIONS_KILL_SWITCH=1` on Railway halts ALL outbound email
within seconds. No restart required (env read fresh on every send).
The single switch covers all 7 historical email paths (post-
consolidation). See the 2026-05-03 michael@blueviewbuilders.com
incident for context.

---

## What v1 does NOT do

- **File at DOB NOW.** No code path posts to DOB NOW; LeveLog
  surfaces the values, operator types them in.
- **Store DOB NOW credentials.** No `filing_reps[].credentials`
  field, no `agent_public_keys` collection, no browser-side
  encryption helper. Removed in MR.14 commit 4b.
- **Run a worker container.** No `dob_worker/` directory. No
  Playwright on the backend (the dep listing is leftover; backend
  itself doesn't import it). No Docker Compose for a worker.
  Removed in MR.14 commit 4a.
- **Manage filing-job state.** No CAPTCHA / 2FA channels, no
  cancel-filing endpoint, no operator-input route, no
  enqueue-filing endpoint. Removed across MR.14 4a → 5.
- **Operate Bright Data, Webshare, Redis, or cloudflared.** All
  paid services tied to filing automation are dead. Operator
  cancels the subscriptions; the code references are gone.

---

## Required environment variables

After all MR.14 cleanup, the runtime needs only:

| Variable | Purpose |
|---|---|
| `MONGO_URL` | Production Mongo cluster (Railway Mongo add-on or external). |
| `DB_NAME` | Database name within the cluster. |
| `JWT_SECRET` | JWT signing key for user auth tokens. |
| `RESEND_API_KEY` | Outbound email via Resend. |
| `NOTIFICATIONS_ENABLED` | `1` (default in production) — global enable. Pair with `NOTIFICATIONS_KILL_SWITCH=1` for emergency halt. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | Cloudflare R2 storage for COI uploads + photo attachments. |
| `NYC_SOCRATA_APP_TOKEN` | Higher Socrata quota. Optional but recommended in production. |
| `QWEN_API_KEY` | Qwen LLM API for the COI OCR + chat features (only required if those features are exercised). |

Removed env vars (no longer read by any code path):

```
ELIGIBILITY_BYPASS_DAYS_REMAINING
BRIGHT_DATA_CDP_URL
WEBSHARE_PROXY_URL
WORKER_SECRET
REDIS_URL
MR14_SEED_WINDOW_START
MR14_SEED_WINDOW_DURATION_MIN
ELIGIBILITY_REWRITE_MODE       (no enqueue path; flag is read but no longer gates anything)
```

---

## Architecture pin tests

`backend/tests/test_v1_monitoring_invariants.py` enforces the v1
shape via static-source checks. A future commit that accidentally
re-introduces a removed surface fails the suite immediately:

- POST `/permit-renewals/{id}/file` is gone.
- DELETE `/filing-jobs/{id}` is gone.
- POST `/filing-jobs/{id}/operator-input` is gone.
- POST `/start-renewal-clicked` exists.
- `FilingRep` Pydantic model has no `credentials` field.
- No `db.agent_public_keys` access remains in source.
- `nightly_dob_scan` + `dob_311_fast_poll` are still registered
  with the scheduler.
- `lib.notifications.send_notification` exists + reads
  `NOTIFICATIONS_KILL_SWITCH`.

Anyone re-introducing renewal automation in v2 should write a new
ADR + drop these pins explicitly. Don't silently re-enable
removed code paths.

---

## v2 candidates (for reference)

If LeveLog returns to filing automation in v2, the prior art:

- **Bright Data Browser API**: blocked by gov-domain policy
  unless enterprise KYC. See `akamai-bypass-decision.md` Attempt 6.
- **Real Chrome via `channel="chrome"` + Xvfb on operator's
  laptop**: the MR.13 approach. Volume ceiling ~5 filings/day per IP.
- **Operator-fleet model**: multiple operator laptops, one per
  N GCs. Adds a control-plane requirement.
- **Direct DOB integration**: lobby NYC DOB for an API. Years
  not weeks.

The full discarded-options trail lives in
`akamai-bypass-decision.md`. Read it before re-attempting any of
these.

---

## Operator action checklists

### Post-MR.14 commit 4a (worker removal)

```
1. Delete env vars from Railway:
     ELIGIBILITY_BYPASS_DAYS_REMAINING
     BRIGHT_DATA_CDP_URL
     WEBSHARE_PROXY_URL
     WORKER_SECRET
     REDIS_URL  (if Redis is no longer used by anything else)
     MR14_SEED_WINDOW_START
     MR14_SEED_WINDOW_DURATION_MIN

2. Stop dob_worker container if still running on operator laptop:
     docker compose down dob_worker
   (compose service no longer defined; harmless if already stopped)

3. Cancel paid services:
     - Bright Data subscription
     - Webshare residential proxy
     - Railway Redis add-on (if no other consumer)
```

### Post-MR.14 commit 4b (credential storage removal)

```
1. Run backfill migration:
     python -m backend.scripts.migrate_clear_filing_rep_credentials --dry-run
     # inspect; then:
     python -m backend.scripts.migrate_clear_filing_rep_credentials --execute

2. Drop agent_public_keys collection:
     mongosh "$MONGO_URL/$DB_NAME" --eval "db.agent_public_keys.drop()"

3. Verify Owner Portal: rep cards show NO credential pills.
4. Verify backend endpoints return 404:
     POST   /api/owner/companies/{id}/filing-reps/{rep}/credentials
     POST   /api/admin/agent-keys
     GET    /api/agent-public-key
```

### Post-MR.14 commit 4c (Start Renewal UX)

```
1. Smoke-test Start Renewal flow on a real renewal record:
     • Open project's permit-renewal page → expand permit card
     • Click "Start Renewal"
     • Verify DOB NOW opens in new tab + values panel appears
     • Verify each field has a working "Copy" button
     • Close panel, click "View values again" — values re-display

2. Verify audit_log records the click:
     db.permit_renewals.findOne({_id: <id>}, {
       manual_renewal_started_at: 1,
       manual_renewal_started_by: 1,
       manual_renewal_audit_log: 1,
     })

3. End-to-end (optional): file at DOB NOW; wait for next 15-min
   poll; FilingStatusCard flips to "Renewed" with new expiration.

4. Verify legacy /file endpoint returns 404 (was 503 in 4b):
     POST /api/permit-renewals/{id}/file
```

### Post-MR.14 commit 5 (final cleanup) — THIS COMMIT

```
1. Run cleanup migrations (if not run from prior commits):
     python -m backend.scripts.migrate_clear_filing_rep_credentials --dry-run
     python -m backend.scripts.migrate_clear_filing_rep_credentials --execute

     python -m backend.scripts.migrate_clean_stranded_renewals --dry-run
     # Inspect the 24 stranded renewals; confirm they're not legitimate.
     python -m backend.scripts.migrate_clean_stranded_renewals --execute

     python -m backend.scripts.migrate_clean_duplicate_projects --dry-run
     # Pick which "638 Lafayette" project to keep from the IDs printed.
     python -m backend.scripts.migrate_clean_duplicate_projects \
         --keep <project_id> --execute

2. Drop the agent_public_keys collection (if not done):
     mongosh "$MONGO_URL/$DB_NAME" --eval "db.agent_public_keys.drop()"

3. Clean up Railway env vars (full list):
     # Remove these (no code path reads them):
     ELIGIBILITY_BYPASS_DAYS_REMAINING
     BRIGHT_DATA_CDP_URL
     WEBSHARE_PROXY_URL
     WORKER_SECRET
     REDIS_URL              (if no other consumer)
     MR14_SEED_WINDOW_START
     MR14_SEED_WINDOW_DURATION_MIN

     # Required (verify they're set):
     MONGO_URL, DB_NAME, JWT_SECRET, RESEND_API_KEY,
     NOTIFICATIONS_ENABLED, R2_*, NYC_SOCRATA_APP_TOKEN

4. Re-enable notification system per the email-consolidation
   runbook (NOTIFICATIONS_ENABLED=1, NOTIFICATIONS_KILL_SWITCH unset
   or =0).

5. Verify activity feed renders correctly across all production
   projects.

6. Verify Start Renewal UX works on at least one real renewal
   record (not the 24 stranded ones; pick one with credentials
   cleared by 4b's migration).

7. Optional (operational hygiene):
     - Cleanup of dob_alert_sent:* keys in system_config (~35
       entries from the MR.14 incident throttling). Canonical
       idempotency now lives in notification_log; these are
       orphan defense-in-depth keys. Drop with:
         db.system_config.deleteMany({_id:/^dob_alert_sent:/})
```

---

## Future revisits

| Trigger | Action |
|---|---|
| Customer demand for filing automation | Spin up v2 design discussion. Re-read `akamai-bypass-decision.md`. Evaluate operator-fleet vs. direct-integration. |
| New Akamai bypass technique becomes public (e.g. residential CDP service) | Re-evaluate. Likely wraps Bright Data competitors anyway. |
| DOB ships an official API for filing | Skip the bypass debate entirely. Most-likely-fastest path; depends on DOB. |
| `nightly_dob_scan` quota exhaustion at scale | Apply for a higher-tier Socrata token; sub-divide datasets across multiple keys. |
| Notification volume scales beyond Resend free tier | Switch to a paid Resend plan or migrate to Postmark. |
