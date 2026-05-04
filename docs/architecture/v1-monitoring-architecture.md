# LeveLog v1 — Monitoring Architecture

**Status**: Accepted
**Date**: 2026-05-03 (MR.14 pivot)
**Supersedes**: `akamai-bypass-decision.md` (MR.5–MR.13 renewal-automation work)
**Decider**: Operator (Roy Fisman) + claude-code engineering session

## Product scope

LeveLog v1 is a **DOB compliance monitoring + notification product**
for NYC General Contractors. We poll public NYC Open Data datasets
on a per-project basis, classify the records into plain-English
signals, and surface them in an activity feed + push critical
ones over email. **LeveLog never files anything.** When a permit
needs renewal, the operator clicks **Start Renewal**, which opens
DOB NOW in a new tab and surfaces a slide-out panel of pre-filled
PW2 values to copy in by hand. The Open Data watcher then detects
the renewed permit on its next 15-minute poll and flips the
renewal status to Completed automatically.

The earlier MR.5–MR.13 effort attempted to automate renewal filing
through the DOB NOW portal (Playwright + warm cookies + various
Akamai bypass strategies). After Bright Data's gov-domain block
closed off the last viable managed-stealth path, the product
direction shifted: rather than fight Akamai, ship monitoring as
the v1 value prop and treat filing automation as a v2 question.

## What's in v1

### Backend (Railway-hosted FastAPI)

- **15-minute DOB poll** (`nightly_dob_scan` despite the name) —
  hits 14 NYC Open Data Socrata datasets per project:
  `w9ak-ipjd` (DOB NOW filings), `855j-jady` + `3h2n-5cm9` +
  `6bgk-3dad` (violations), `rbx6-tga4` + `dm9a-ab7w` + `ipu4-2q9a`
  (permits), `p937-wjvj` (inspections), `eabe-havv` (DOB
  complaints), `3usq-5cid` (Stop Work Orders), `pkdm-hqz6`
  (Certificate of Occupancy), `xubg-57si` (FISP façade),
  `52dp-yji6` (Boiler), `e5aq-a4j2` (Elevator).

- **30-minute 311 poll** — `erm2-nwe9` filtered to ~14
  construction-relevant complaint types.

- **Status-change diffing** — every poll compares the incoming
  record's status against the most-recent dob_logs entry's
  `current_status`. Status unchanged → update mutable fields in
  place. Status changed OR first-time-seen → insert a new
  "transition" row stamped with `previous_status` +
  `status_changed_at` + `is_seed_transition`. The transition row
  is what the activity feed surfaces.

- **signal_kind classifier** (`backend/lib/dob_signal_classifier.py`)
  — derives one of ~25 signal_kind values from record_type +
  status fields (e.g. `permit_expired`, `violation_ecb`,
  `inspection_failed`, `final_signoff`, `cofo_temporary`).

- **Plain-English templates** (`backend/lib/dob_signal_templates.py`)
  — each signal_kind has a renderer producing
  `{title, body, severity, action_text}`. Templates speak to GC /
  PM / Site Manager who has never used DOB; jargon (PAA, FISP,
  CofO, TCO, OATH) gets inline parenthetical explanation.

- **Notification routing** (`backend/lib/dob_signal_notifications.py`)
  — admin defaults per signal_kind: critical → immediate email;
  warning → daily digest; info → weekly digest or feed-only.

- **Email send pipeline** — every email path routes through
  `lib/notifications.send_notification` (post-MR.14-incident
  consolidation). Gives universal kill switch
  (`NOTIFICATIONS_KILL_SWITCH`), trigger_key idempotency, and
  notification_log audit trail.

- **TTL retention** on dob_logs: 90 days for most record_types,
  365 days for `violation` + `swo`.

### Frontend (React Native Web on Cloudflare Pages)

- **Activity tab** at `/project/{id}/activity` — server-rendered
  template output with severity-coded cards, filters
  (signal_kinds, severity, date range, unread, search), per-row
  mark-as-read, mark-all-read, pull-to-refresh, mobile bottom-sheet
  filter UI.

- **Legacy `/dob-logs` route** — kept for raw record inspection.

- **Reuses existing chrome** — Project detail page, sidebar nav,
  notifications tray, settings.

## What's NOT in v1

- **Filing automation**. No worker container, no Playwright, no
  Bright Data, no Webshare proxy, no real Chrome stealth. The
  `dob_worker/` directory was removed in MR.14 commit 4a.
- **Encrypted DOB credentials at rest**. The
  `companies.filing_reps[].credentials` field + the
  `agent_public_keys` collection + the browser-side
  `encryptCredentials` SubtleCrypto path were removed in
  MR.14 commit 4b. Operators can no longer enter or rotate
  DOB NOW credentials through the owner portal — there is no
  longer a credential entry surface anywhere in the product.
  The corresponding backend endpoints (POST/GET/DELETE under
  `/api/owner/companies/{id}/filing-reps/{rep_id}/credentials`,
  plus the `/api/admin/agent-keys` CRUD and the no-auth
  `/api/agent-public-key` read) are gone. Backfill migration:
  `backend/scripts/migrate_clear_filing_rep_credentials.py`
  ($unset of the dead field on every existing rep). MR.10's
  filing-authorization endpoints (GET/POST
  `/api/owner/companies/{id}/authorization`) and the
  `AUTHORIZATION_TEXT_VERSION` constant remain on the backend
  for historical reference; the v1 frontend never reaches them.
- **"File Renewal" button**. Replaced in MR.14 commit 4c by the
  "Start Renewal" UX (described in detail below).
- **Operator agent on operator's laptop**. Pure cloud-hosted
  product; nothing runs locally.

## Start Renewal UX (MR.14 commit 4c)

When a permit hits the one-year ceiling and the v2 dispatcher emits
`action.kind === "manual_renewal_dob_now"`, the renewal card surfaces
the **Start Renewal** affordance instead of the legacy automated
filing button. The flow:

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
         │
         ├──── stamps `manual_renewal_started_at` +
         │     `manual_renewal_started_by` on the renewal doc
         │
         └──── returns the MR.4 PW2 mapper output (Pw2FieldMap +
               critical / non_critical unmappable partitions)
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
             FilingStatusCard now renders the
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
fields ON the renewal doc itself (no polling, no filing_jobs):

1. **Pre-renewal**: `manual_renewal_started_at` is null AND
   status is not 'completed'. Shows the Start Renewal button +
   readiness check.
2. **In-progress**: `manual_renewal_started_at` is set AND status
   is not 'completed'. Shows "Filing in progress" reminder + a
   "View values again" link that re-opens the panel without
   re-recording the click.
3. **Renewed**: status is 'completed' OR `new_expiration_date` is
   set. Shows the new expiration + DOB confirmation number (if
   present) + a "View on DOB NOW" deep-link.

The Open Data watcher path is the v1 detection mechanism — same
`dob_approval_watcher` that's been in production since MR.8. It
matches by job_filing_number / BIN against NYC Open Data DOB NOW
filings, so the operator's manual filing at DOB NOW lands in the
same dataset the watcher polls. No new infrastructure is needed
for "did the user actually file" detection.

## Data model

| Collection | Purpose |
|---|---|
| `companies` | One per GC; carries license + insurance metadata. `filing_reps[].credentials` field REMOVED in MR.14 commit 4b (operator runs `migrate_clear_filing_rep_credentials.py` to strip from existing docs). |
| `agent_public_keys` | REMOVED in MR.14 commit 4b — operator drops via `db.agent_public_keys.drop()`. The collection backed the worker's RSA-4096 hybrid encryption scheme; with the worker container gone (4a) and the credentials field gone (4b), nothing reads or writes it. |
| `projects` | Per-jobsite. `track_dob_status` defaults to True; polled if BIN or address resolves. |
| `dob_logs` | Append-only stream of DOB signals. One row per (raw_dob_id, transition). Carries `signal_kind`, `current_status`, `previous_status`, `status_changed_at`, `is_seed_transition`, `read_by_user[]`. |
| `permit_renewals` | Historical from MR.6 work. The 30-day-window sweep still creates records. v1 surfaces them through the Start Renewal UX. New fields added in MR.14 commit 4c: `manual_renewal_started_at`, `manual_renewal_started_by`, `manual_renewal_audit_log[]`. |
| `notification_log` | Append-only audit of every email send. Status: sent / suppressed_idempotent / suppressed_kill_switch / suppressed_flag_off / suppressed_no_key / failed. |

## Polling cadences

| Job | Cadence | Source |
|---|---|---|
| `dob_nightly_scan` | 15 min | DOB Socrata datasets (10) |
| `dob_approval_watcher` | 15 min (offset +5 min) | reads cached dob_logs |
| `dob_311_fast_poll` | 30 min (offset +7 min) | 311 dataset |
| `renewal_reminder_cron` | daily 7am ET | renewal docs |
| `nightly_compliance_check` | daily 10pm ET | internal logbooks |
| `renewal_digest_daily` | daily 7am ET | per-company digest |

## Notification kill switch

`NOTIFICATIONS_KILL_SWITCH=1` on Railway halts ALL outbound email
within seconds. No restart required (env read fresh on every
send). The single switch covers all 7 historical email paths
(post-consolidation). See the 2026-05-03
michael@blueviewbuilders.com incident for context.

## v2 candidates (for reference)

If LeveLog returns to filing automation in v2, the prior art:

- **Bright Data Browser API**: blocked by gov-domain policy
  unless enterprise KYC. See `akamai-bypass-decision.md` Attempt 6.
- **Real Chrome via `channel="chrome"` + Xvfb on operator's
  laptop**: the MR.13 approach. Would need to be re-enabled with
  the worker container reinstated. Volume ceiling ~5 filings/day
  per IP.
- **Operator-fleet model**: multiple operator laptops, one per
  N GCs. Adds a control-plane requirement.
- **Direct DOB integration**: lobby NYC DOB for an API. Years
  not weeks.

The full discarded-options trail lives in `akamai-bypass-decision.md`.
Read it before re-attempting any of these.

## Operator action checklist (post-MR.14 commit 4a)

```
1. Delete env vars from Railway (no longer used by any code path):
     ELIGIBILITY_BYPASS_DAYS_REMAINING
     BRIGHT_DATA_CDP_URL
     WEBSHARE_PROXY_URL
     WORKER_SECRET
     REDIS_URL  (if Redis is no longer used by anything else)
     MR14_SEED_WINDOW_START
     MR14_SEED_WINDOW_DURATION_MIN

2. Stop dob_worker container if still running on operator laptop:
     docker compose down dob_worker
   (won't exist after pulling 4a; harmless if not running)

3. Cancel paid services tied to filing automation:
     - Bright Data subscription (if not already)
     - Webshare residential proxy
     - Railway Redis add-on (if no other consumer)

4. Verify monitoring product still works:
     - Visit /project/{id}/activity — feed renders
     - Trigger /api/projects/{id}/dob-sync — new dob_logs appear
     - Check notification_log for recent sends
```

## Operator action checklist (post-MR.14 commit 4b)

```
1. Run the backfill migration with MONGO_URL + DB_NAME set:
     python -m backend.scripts.migrate_clear_filing_rep_credentials --dry-run
   Inspect the per-doc breakdown + total ciphertext-bytes-to-free,
   then re-run with --execute when satisfied:
     python -m backend.scripts.migrate_clear_filing_rep_credentials --execute

2. Drop the now-orphaned agent_public_keys collection:
     mongosh "$MONGO_URL/$DB_NAME" --eval "db.agent_public_keys.drop()"

3. Verify no lingering credential field references in Mongo:
     db.companies.find({"filing_reps.credentials": {$exists: true}}).count()
   Should return 0 after the migration.

4. Verify owner portal:
     - Open the Owner Portal → expand a company's filing_reps drawer
     - The rep cards should NOT display credential status pills,
       "Add credentials" / "Rotate" / "Revoke" buttons, or open
       the encrypt-credentials modal
     - The filing-authorization modal should not appear

5. Verify backend endpoints return 404:
     POST   /api/owner/companies/{id}/filing-reps/{rep}/credentials
     GET    /api/owner/companies/{id}/filing-reps/{rep}/credentials
     DELETE /api/owner/companies/{id}/filing-reps/{rep}/credentials/active
     POST   /api/admin/agent-keys
     GET    /api/admin/agent-keys
     DELETE /api/admin/agent-keys/{key_id}
     GET    /api/agent-public-key

6. Verify the legacy "File Renewal" button (still present in 4b)
   returns 503 with code='renewal_automation_deferred' from
     POST /api/permit-renewals/{id}/file
   The button itself goes away in commit 4c.
```

## Operator action checklist (post-MR.14 commit 4c)

```
1. Smoke-test the Start Renewal flow on a real renewal record
   (NOT the 24 stranded ones from the pre-4b ciphertext era —
   pick one with credentials cleared by 4b's migration):

     • Open the project's permit-renewal page
     • Expand the permit card
     • Click "Start Renewal"
     • Verify DOB NOW opens in a new browser tab AND the slide-out
       panel appears with grouped fields
     • Verify each field has a working "Copy" button (click ↦
       value lands on the clipboard, button shows "Copied")
     • Close the panel and click "View values again" — values
       should re-display without recording a second click in the
       audit log

2. Verify audit_log records the click:
     db.permit_renewals.findOne({_id: <renewal_id>}, {
       manual_renewal_started_at: 1,
       manual_renewal_started_by: 1,
       manual_renewal_audit_log: 1,
     })
   Expected:
     • manual_renewal_started_at = ISO timestamp of the click
     • manual_renewal_started_by = operator's user_id / email
     • manual_renewal_audit_log = [{event_type:'manual_renewal_started',
                                    timestamp, actor, renewal_id}]

3. Complete the renewal at DOB NOW during testing if you want
   end-to-end validation. The MR.8 dob_approval_watcher runs every
   15 minutes; once Open Data picks up your new permit row, the
   watcher will:
     • compute the new_expiration_date
     • flip renewal.status → COMPLETED
     • update FilingStatusCard's render to the "Renewed" state
       (no operator action; the next page render reflects it)

4. Verify the legacy /file endpoint is GONE (404, not 503):
     POST /api/permit-renewals/{id}/file
   Should return 404 in commit 4c (was 503 in 4b).

5. (Optional cleanup) The cancel-filing-job and operator-input
   endpoints still exist for historical filing_jobs. They have no
   v1 caller. Decide later whether to remove them; harmless to
   leave.
```

## Future revisits

| Trigger | Action |
|---|---|
| Customer demand for filing automation | Spin up v2 design discussion. Re-read akamai-bypass-decision.md. Evaluate operator-fleet vs. direct-integration. |
| New Akamai bypass technique becomes public (e.g. residential CDP service) | Re-evaluate. Likely wraps Bright Data competitors anyway. |
| DOB ships an official API for filing | Skip the bypass debate entirely. Most-likely-fastest path; depends on DOB. |
