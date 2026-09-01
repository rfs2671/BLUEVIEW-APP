# LeveLog — factual build brief for marketing design

App name `LeveLog` (slug `levelog`), v1.3.0 (iOS build 2, Android versionCode 1030001).
Expo / React Native (iOS, Android, web) + FastAPI + MongoDB.
Audited from source at commit `aee8c96`, 2026-08-25.

**Scope of this document.** Everything below is read out of the repo. Where a
claim could not be verified by running the app, it says so. Nothing here is
roadmap.

**Two caveats that affect several sections:**

1. **No screenshots were captured.** See §7. Docker's daemon is not running on
   this machine and there is no local Mongo, so the backend could not be
   started. Pointing the web build at production was rejected — it would put
   real client data in marketing assets.
2. **The compliance-audit layer is behind a feature flag that defaults OFF.**
   `v2_logbook` fails closed (`lib/feature_flags.py`, `is_feature_enabled` returns
   `False` when the flag row is absent). This gates the whole `/project/{id}/audit`
   screen and the only "export the audit window" endpoint. Detail in §1 and §5.

---

## 1. Shipped vs not

### 1a. Every route

67 route files under `frontend/app/`. Status is assigned on evidence: does the
screen call a real API, does it write, is it behind a flag, does it carry
"coming soon" copy.

| Route | Screen | What a user does | Status |
|---|---|---|---|
| `/` | Dashboard | Portfolio exposure, active-by-site counts, admin tools | WORKING |
| `/login` | Sign In | Email + password | WORKING |
| `/register` | Create Your Account | Self-registration; account lands pending | WORKING |
| `/demo` | Pending activation | Read-only holding screen for a pending account | WORKING |
| `/onboarding` | Onboarding | First project creation | WORKING |
| `/logbooks` | Log Books | CP home. Today's logbooks, completion, gaps | WORKING |
| `/logbooks/daily_jobsite` | Daily Jobsite Log | 5-step stepper; the DOB 3301-02 record | WORKING |
| `/logbooks/preshift_signin` | Worker Sign-In | Pre-shift meeting + per-worker signature | WORKING |
| `/logbooks/toolbox_talk` | Toolbox Talk | Talk topic + roster + CP signature | WORKING |
| `/logbooks/osha_log` | OSHA / SST Log | SST card register | WORKING |
| `/logbooks/fall_protection` | Fall Protection | Equipment IDs, defects | WORKING |
| `/logbooks/scaffold_maintenance` | Scaffold Maintenance | Height, condition, sign | WORKING |
| `/logbooks/hot_work` | Hot Work | Permit, fire watch, until-time | WORKING |
| `/logbooks/crane_operations` | Crane Operations | Crane type, ID/serial | WORKING |
| `/logbooks/excavation_monitoring` | Excavation Monitoring | Depth, readings | WORKING |
| `/logbooks/concrete_operations` | Concrete Operations | Slump, pH, time | WORKING |
| `/logbooks/ssc_daily_safety_log` | SSC Daily Safety Log | Site Safety Coordinator log | WORKING |
| `/logbooks/subcontractor_orientation` | Subcontractor Orientation | Orientation + signature | WORKING |
| `/logbooks/review` | Check-In Review | CP reviews flagged gate check-ins | WORKING |
| `/checkin` | Check-In | NFC tag scan or manual worker pick | WORKING |
| `/checkin/[project_id]/[tag_id]` | Gate check-in | Tap-through target for a mounted tag | WORKING |
| `/nfc` | NFC | Write/register a tag to a project | WORKING |
| `/workers` | Sign-In Log | Daily on-site roster | WORKING |
| `/workers/[id]` | Worker detail | Certifications, OSHA card, orientations | WORKING |
| `/projects` | Projects | Project list | WORKING |
| `/project/[id]` | Project detail | DOB exposure, NFC tags, devices, Dropbox, checklists | WORKING |
| `/project/[id]/trades` | Trades | Trade assignments | WORKING |
| `/project/[id]/report-settings` | Report Settings | Email list, send time | WORKING |
| `/project/[id]/activity` | Activity | Wrapper over `ActivityFeed` | WORKING |
| `/project/[id]/notifications` | Notifications | Wrapper over `NotificationsList` | WORKING |
| `/project/[id]/dob-logs` | DOB Logs | Raw DOB record detail | **PARTIAL** — carries "Automated filing — coming soon" |
| `/project/[id]/permit-renewal` | Permit Renewal | Renewal tracking | **PARTIAL** — same "coming soon" tile |
| `/project/[id]/defcon` | DEFCON | Risk posture | **PARTIAL** — renders "Comparison not yet available" when cohort data is absent |
| `/project/[id]/audit` | Compliance audit | Calendar grid, deficiencies, PDF export | **PARTIAL** — every endpoint it calls is behind `v2_logbook`, default OFF |
| `/projects/[id]/construction-plans` | Construction Plans | Dropbox-backed file list | WORKING |
| `/projects/[id]/dropbox-settings` | Dropbox Settings | OAuth link, folder pick | WORKING |
| `/projects/[id]/whatsapp-groups` | WhatsApp Groups | Group link + config | WORKING |
| `/projects/[id]/whatsapp-checklists` | WhatsApp Checklists | Checklist items over WhatsApp | WORKING |
| `/reports` | Reports | Daily Site Log preview + PDF | WORKING |
| `/daily-log` | Daily Site Log | Single-day narrative | WORKING |
| `/documents` | Documents | Document index | WORKING |
| `/checklists` | Checklists | Assigned checklists | WORKING |
| `/settings` | Settings | Profile, CP signature, build card | WORKING |
| `/settings/notifications` | Notification Settings | Per-channel prefs | WORKING |
| `/settings/notifications/project/[project_id]` | Per-project notifications | Per-project prefs | WORKING |
| `/admin/users` | User Mgmt | CPs & workers, deletion requests | WORKING |
| `/admin/checklists` | Checklists admin | Build + assign | WORKING |
| `/admin/site-devices` | Site Devices | Kiosk credentials | WORKING |
| `/admin/integrations` | Integrations | Connect Dropbox | WORKING |
| `/admin/superintendent` | Superintendents | CS one-job rule | WORKING |
| `/admin/safety-staff` | Safety Staff | SSC / SSM registry | WORKING |
| `/admin/insurance` | — | **STUB** — 11-line redirect to `/settings` | STUB |
| `/owner` | Owner console | Companies, admins, authorizations | WORKING |
| `/owner/pending-deletion` | Pending deletion | Projects awaiting purge | WORKING |
| `/site` | Site device home | Kiosk landing; "Hand to Inspector (read-only)" | WORKING |
| `/site/checkins` | Site check-ins | Kiosk roster | WORKING |
| `/site/daily-logs` | Site daily logs | Kiosk read-only logs | WORKING |
| `/site/documents` | Site documents | Kiosk read-only docs | WORKING |
| `/site/logbooks` | Site logbooks | Kiosk read-only logbooks | WORKING |
| `/help`, `/help/faq`, `/help/getting-started`, `/help/permit-renewal`, `/help/troubleshooting` | Help | Static copy, no API | WORKING (static) |
| `/help/notifications` | Help — notifications | Static copy | **PARTIAL** — contains a "SMS — coming soon" section |
| `/+html` | — | Expo web HTML shell, not a screen | n/a |

**Role → landing route** (`app/login.jsx:16`): `site_mode` → `/site`; `role === 'cp'` → `/logbooks`; everything else → `/`.
Roles in the data: `owner`, `admin`, `cp`, `user`, plus a `site_mode` flag for kiosk devices.

### 1b. Referenced in code but not functional

| Thing | Where | State |
|---|---|---|
| Automated DOB filing | `project/[id]/dob-logs.jsx:506`, `permit-renewal.jsx:971` | Tile literally titled "Automated filing — coming soon". Not wired. |
| SMS notifications | `help/notifications.jsx:100` | Documented as "coming soon". No SMS sender in the backend. |
| Cohort peer comparison | `project/[id]/defcon.jsx:253` | Falls back to "Comparison not yet available". |
| LL196 completeness / audit / export | `server.py` `/projects/{id}/logbook/*` | Built, but `v2_logbook` defaults OFF → endpoints return 404 to flag-off callers. |
| `RiskScoreCard` | `project/[id].jsx:51` | Marked deprecated, no longer mounted; file retained as reference. |
| `/admin/insurance` | `app/admin/insurance.jsx` | Redirect only. Insurance moved to Settings → Profile. |
| `audit_logs` purge | `server.py:10325` | `delete_many` on project hard-delete — the audit trail is deletable by design (owner choice). |
| `typography.regular` / `.medium` / `.semibold` | `components/permit-renewal/*` | Referenced but **not defined** in `theme.js`. Resolves to `undefined`; falls back to system font. Cosmetic, not a crash. |
| Docker services | `docker-compose.yml` | `services: {}` — an intentional empty stub. |

---

## 2. Screen detail — the six that matter

> **On the sample rows.** Field names, enums and nesting are read from the source cited under each. The *values* are synthetic but format-correct: `nyc_bin` is a real 7-digit Staten Island BIN shape (leading `5`, not the `X000000` placeholder the code rejects), `bbl` is 10 digits, DOB NOW job filing numbers follow the `B00834550-I1:FE` form found at `server.py:24306`, SSC/SSM licences follow the `S-56-XXXXX` / `S-57-XXXXX` placeholders in `admin/safety-staff.jsx:630`, and complaint categories are real codes from `backend/dob_complaint_codes.py`. **No real client data is used anywhere in this document.**

### 2.1 `/logbooks/daily_jobsite` — Daily Jobsite Log

The flagship record. Form is NYC DOB **3301-02**. 5-step stepper.

**Steps:** `What was on site` · `What each crew did` · `Safety observations` · `Daily inspections walked` · `Review and sign`
**Buttons:** `Back` `Next` `Cancel` `Save` `Take Photo` `Gallery`
**Sections:** Project Information · Activity Details · Equipment on Site · Daily inspections · Safety Observations / Violations · Visitors / Deliveries / Inspections · Competent Person Sign-Off
**Fields:** `Address` · `Weather` · `General Description of Today's Activities`
**Columns:** `COMPANY` `WORK DESCRIPTION` `WORK LOCATIONS`
**Placeholders:** "Company" · "Work performed..." · "Floors, areas..." · "Describe observation..." · "Responsible party" · "Remedy / corrective action" · "Record any visitors or deliveries..."
**Nine inspection items** (`daily_jobsite.jsx:218`): Street Frontage · Fire Safety · Perimeter Fence · Fall Protections · Neighbor's Property · License Spot-Check · Plans · Permits · Other — each **pass / fail / not walked**, not a tick.
**Equipment:** Elevator · Compressor · Pump · Hoist · Boom/Crane · Other
**Weather vocabulary:** Sunny, Cloudy, Rainy, Windy, Snow, Fog, Stormy — *fetched, not picked*.
**Key strings:** "Auto-populated from check-ins. Edit as needed." · "Sign the log before submitting — this is a signed record." · "Submitted & Signed" · "Signed and locked on this device. It will sync when you are back online." · "Signing locks this log. Corrections then need an amendment."

Data shape — `logbooks` document (`server.py:17663`):

```json
{
  "project_id": "68f2a1c94b7e0a0012d4e881",
  "project_name": "857 Prescott Ave",
  "company_id": "68e10b2c4b7e0a0012a10044",
  "log_type": "daily_jobsite",
  "date": "2026-08-24",
  "data": {
    "address": "857 Prescott Ave, Staten Island, NY 10309",
    "weather": "Cloudy",
    "activities": [
      { "company": "Vanguard Concrete Corp", "work_description": "Deck pour, 4th floor east bay",
        "work_locations": "Floors 4-5, east elevation", "workers": 11, "photos": ["…"] }
    ],
    "equipment": { "hoist": true, "boom_crane": true },
    "inspections": {
      "perimeter_fence": "pass", "fall_protections": "pass",
      "street_frontage": "fail", "permits": "not_walked"
    },
    "observations": [
      { "observation": "Sidewalk shed netting torn at NW corner",
        "responsible_party": "Vanguard Concrete Corp", "remedy": "Netting replaced 14:20" }
    ],
    "visitors": "DOB inspector 11:05, complaint 1-1-2026-XXXXX; no violation issued"
  },
  "cp_signature": { "affirmed": true, "affirmedAt": "2026-08-24T21:47:12Z",
                    "affirmed_received_at": "2026-08-24T21:47:14.221Z" },
  "cp_name": "Roy Fishman",
  "status": "submitted",
  "is_locked": true,
  "finalized_at": "2026-08-25T04:00:03Z",
  "finalized_by": "system:eod_sweep",
  "finalized_by_name": "End-of-day sweep",
  "timing_class": "end_of_day",
  "instance_seq": 1,
  "created_by": "68e10b2c4b7e0a0012a10051",
  "created_by_name": "Roy Fishman",
  "created_at": "2026-08-24T13:02:44Z",
  "updated_at": "2026-08-24T21:47:14Z"
}
```

### 2.2 `/logbooks/preshift_signin` — Worker Sign-In

**Titles:** `Worker Sign-In` · `Daily Pre-Shift Safety Meeting` · `Sign-In Sheet` · `Meeting Details`
**Columns:** `NAME` `COMPANY` `OSHA #` `WORKER SIGNATURE` `TOTAL COUNT`
**Fields:** `First & Last Name` · `Company name` · `OSHA card number` · `Inspected PPE today?` · `Injury / Incident last time?`
**Buttons:** `+ Add Row` · `Cancel` · `Competent Person Signature`
**States:** `Auto-filled` · `Not saved` · `Not signed` · `Required field` · "Select this worker's trade & company"

This is one of nine **IMMEDIATE** log types: the signature *is* the freeze — `is_locked` is set the moment `status === "submitted"` (`server.py:17650`). There is no separate finalize step.

Data shape — same `logbooks` envelope as §2.1, `log_type: "preshift_signin"`, rows inside `data`:

```json
{
  "log_type": "preshift_signin",
  "date": "2026-08-24",
  "data": {
    "meeting_topic": "Sidewalk shed netting + fall protection tie-off points",
    "ppe_inspected": true,
    "incident_last_shift": false,
    "total_count": 11,
    "rows": [
      { "name": "Luis Ramos", "company": "Vanguard Concrete Corp",
        "osha_number": "SST 4471", "signature": { "paths": "…", "signed_at": "2026-08-24T06:52:10Z" },
        "auto_filled": true }
    ]
  },
  "cp_name": "Roy Fishman",
  "status": "submitted",
  "is_locked": true,
  "timing_class": "immediate",
  "instance_seq": 1
}
```

### 2.3 `/checkin` — Gate check-in

**Labels:** `Check-In` · `NFC Tag Scan` · `Manual Check-In` · `SELECT PROJECT` · `WORKER` · `Select Worker`
**Copy:** "Tap worker's NFC badge" · "Select worker from list" · "Search workers..." · "Scan NFC Tag" · `Change`
**Empty states:** "No projects available" · "No workers found"

Data shape — `checkins` document (`server.py`, `register_and_checkin`):

```json
{
  "worker_id": "68f3c0114b7e0a0012d4ea19",
  "worker_name": "Luis Ramos",
  "worker_phone": "+19175550142",
  "worker_company": "Vanguard Concrete Corp",
  "worker_trade": "Concrete",
  "project_id": "68f2a1c94b7e0a0012d4e881",
  "project_name": "857 Prescott Ave",
  "tag_id": "GATE-A",
  "check_in_time": "2026-08-24T11:04:31Z",
  "check_out_time": null,
  "status": "checked_in",
  "sst_card_number": "SST •••• 4471",
  "sst_expiration": "2027-03-18",
  "sst_status": "valid",
  "sst_unknown_reason": null,
  "cert_cleared": true,
  "cert_warnings": [],
  "needs_trade_assignment": false,
  "card_ocr_attempts": null,
  "signature_affirmed": true,
  "signature_affirmed_at": "2026-08-24T11:04:31Z",
  "signature_affirmed_lang": "es",
  "toolbox_talk_confirmed": true,
  "toolbox_talk_confirmed_at": "2026-08-24T11:04:31Z",
  "source_ip": "70.23.14.88",
  "user_agent": "Mozilla/5.0 (Linux; Android 15) …",
  "device_fingerprint": "a91f…c3",
  "is_deleted": false
}
```

The SST block is explicitly a **frozen snapshot**, commented in source as "Never overwritten" — what was true about the card at the moment of entry.

### 2.4 `/logbooks` — Log Books (CP home)

**Labels:** `Log Books` · `TODAY'S LOG BOOKS` · `PROJECT` · `COMPLIANCE` · `Today's Completion` · `On site today` · `Completed this week` · `Check-In Review` · `Open Tool Box Talk`
**Chips:** `Done` · `Draft` · `Pending`
**Empty state:** "All caught up! No logbooks needed right now."

Reads `GET /api/logbooks/project/{id}/notifications`, which returns an `attestation_gaps` array — one row per `(log_type, date)` with `state` of `unsigned` or `unaffirmed`. **Not** flag-gated.

Data shape — `GET /api/logbooks/project/{id}/notifications` (`server.py`, `get_logbook_notifications`):

```json
{
  "missing_toolbox_talk": 3,
  "unsigned_orientations": 1,
  "unaffirmed_logbooks": 2,
  "unaffirmed_logbook_refs": [{ "log_type": "daily_jobsite", "date": "2026-08-22" }],
  "stale_unsigned_logbooks": 1,
  "stale_unsigned_logbook_refs": [{ "log_type": "ssc_daily_safety_log", "date": "2026-08-21" }],
  "attestation_gaps": [
    { "log_type": "daily_jobsite",          "date": "2026-08-22", "state": "unaffirmed" },
    { "log_type": "ssc_daily_safety_log",   "date": "2026-08-21", "state": "unsigned"   }
  ],
  "week_start": "2026-08-24"
}
```

`attestation_gaps` is the merged, de-duplicated view — one row per `(log_type, date)`, `unaffirmed` winning an overlap. The older four fields are retained for older app bundles.

### 2.5 `/project/[id]` — Project detail

**Sections:** `DOB EXPOSURE` · `NFC CHECK-IN TAGS` · `DEVICES` · `DROPBOX INTEGRATION` · `CHECKLISTS` · `NOTIFICATIONS`
**Buttons:** `Add Site Device` · `Link Dropbox Folder` · `Link Folder` · `Disconnect` · `Manual Entry` · `Go Back`
**Empty states:** "No BIN" · "No NFC tags registered" · "No site devices registered" · "No Dropbox folder linked" · "No checklists assigned" · "NEVER SYNCED"

Data shape — `dob_logs` document (`server.py:24412`):

```json
{
  "project_id": "68f2a1c94b7e0a0012d4e881",
  "nyc_bin": "5023918",
  "record_type": "violation",
  "raw_dob_id": "V052318X26",
  "dataset": "3h2n-5cm9",
  "ai_summary": "DOB violation issued for failure to maintain sidewalk shed netting.",
  "severity": "Action",
  "next_action": "Certify correction with DOB within 30 days.",
  "current_status": "OPEN",
  "previous_status": null,
  "status_changed_at": "2026-08-19T14:22:00Z",
  "signal_kind": "violation_open",
  "dob_link": "https://a810-bisweb.nyc.gov/bisweb/…",
  "detected_at": "2026-08-19T14:31:07Z",
  "read_by_user": [],
  "is_seed_transition": false,
  "is_deleted": false
}
```

`record_type` ∈ `boiler, cofo, complaint, elevator, facade_fisp, inspection, job_status, permit, swo, violation`.
Complaint categories come from `backend/dob_complaint_codes.py` (603 lines) — e.g. `CS` Site Safety, `C` Construction, `E` Elevator, `B` Boiler, `P` Plumbing, `LL16` Local Law 16/84 — Elevator, `LL5` Local Law 5/73, `Z` Zoning.

Project identifiers: `nyc_bin` (7 digits, first digit = borough; `X000000` treated as *no BIN* — `server.py:1602`), `bbl` (10 digits), `job_number` / `job_filing_number` in DOB NOW form `B00834550-I1:FE` (`server.py:24306`), `ssp_number` + `ssp_filing_date` + `ssp_expiration_date`.

### 2.6 `/reports` — Reports

**Labels:** `Reports` · `SELECT PROJECT` · `Daily Site Log` · `DAILY FIELD` · `LIVE` · `Logbook Status` · `Logbooks` · `Workers` · `Subs`
**Buttons:** `Download as PDF` · `Share Report`
**Empty states:** "No Data Available" · "No logbooks filed yet for this date" · "Loading preview..."

Endpoints: `GET /api/reports/project/{id}/date/{date}` (JSON preview), `…/pdf` (PDF), `GET /api/reports/logbook/{logbook_id}/pdf`, `GET /api/daily-logs/{log_id}/pdf`. Rendered with WeasyPrint. **These are not flag-gated.**

Data shape — `GET /api/reports/project/{id}/date/{date}` (`server.py:21870`):

```json
{
  "project_id": "68f2a1c94b7e0a0012d4e881",
  "project_name": "857 Prescott Ave",
  "date": "2026-08-24",
  "checkin_count": 11,
  "logbooks": [
    { "log_type": "daily_jobsite", "status": "submitted", "has_signature": true,
      "cp_name": "Roy Fishman", "updated_at": "2026-08-24T21:47:14Z", "failed_photo_count": 0 },
    { "log_type": "preshift_signin", "status": "submitted", "has_signature": true,
      "cp_name": "Roy Fishman", "updated_at": "2026-08-24T06:58:02Z", "failed_photo_count": 0 }
  ],
  "failed_photo_count": 0,
  "has_daily_log": true,
  "daily_log_status": "submitted",
  "daily_log_weather": "Cloudy",
  "daily_log_worker_count": 11,
  "subcontractor_count": 3,
  "report_already_sent": true,
  "report_sent_at": "2026-08-24T22:00:04Z",
  "report_send_time": "18:00",
  "report_email_list": ["pm@vanguardconcrete.example", "gc@example.com"]
}
```

---

## 3. Data model

MongoDB. 45+ collections; the ones that matter here.

| Collection | Key fields |
|---|---|
| `logbooks` | `project_id, company_id, log_type, date, data{}, cp_signature{}, cp_name, status, is_locked, finalized_at, finalized_by, finalized_by_name, timing_class, instance_seq, is_amendment, parent_logbook_id, created_by, created_by_name, created_at, updated_at, is_deleted` |
| `signature_events` | `document_type, document_id, event_type, version, signer{user_id,name,role,authenticated_role,acting_capacity}, device{}, content_snapshot{}, content_hash, signature_data{}, timestamp, ip_address, is_deleted` |
| `checkins` | see §2.3 — incl. `sst_card_number, sst_expiration, sst_status, cert_cleared, cert_warnings, source_ip, user_agent, device_fingerprint, signature_affirmed_at, toolbox_talk_confirmed_at` |
| `workers` | `name, phone, company_id, status, osha_number, osha_data{}, osha_card_image, safety_orientations[], certifications[], signature, created_at`. **No worker-level `trade`/`company`** — those are per-project in `worker_project_trades` |
| `worker_enrollments` | SST/Worker-Wallet card enrollment: `card_expiration_date`, card type, enrollment method/status |
| `sign_ins` | Gate sign-ins with `attestation_type`, `within_geofence` |
| `daily_signatures` | Per-day worker signature captures |
| `card_fraud_flags` | `dual_site_same_day, card_shared_across_workers, repeated_mismatch, out_of_geofence, expired_card_signin` |
| `card_audit_log` | `attestation_type` ledger |
| `unexpected_ndef_hosts` | NDEF URL host drift, for fraud vs. legitimate-change discrimination |
| `projects` | `name, address, lat, lng, geofence_radius_m (default 150), gates[], nyc_bin, bbl, building_stories, building_height, footprint_sqft, has_full_demolition, project_class, structural_system, dob_project_type, ssp_number, ssp_filing_date, ssp_expiration_date, report_email_list, report_send_time` |
| `dob_logs` | see §2.5 |
| `logbook_entries` | LL196 completeness. `company_id, project_id, entry_date, category, status, source, deficiency_reason`. Unique index on `(project_id, entry_date, category)`. **Flag-gated.** |
| `audit_logs` | `action, user_id, resource_type, resource_id, details{}, timestamp` |
| `project_files`, `document_page_index`, `document_annotations` | Dropbox-backed docs + page index + annotations |
| `nfc_tags`, `site_devices` | Gate tags and kiosk credentials |
| `safety_staff_registrations`, `cs_registrations` | SSC (`S-56-…`) / SSM (`S-57-…`) and Construction Superintendent one-job rule |
| `reports`, `report_emails` | Generated reports and delivery |

`logbook_entries` categories: `daily_log, inspection, deficiency, manpower, material_delivery`.
Statuses: `complete, missing, deficient`. Sources: `whatsapp, manual, auto_detected`.

Photos are stored in Cloudflare R2 (222 `r2_` references). Base64 payloads are purged from finalized logbooks (`_purge_finalized_photo_base64`).

---

## 4. The defensible claim

### What is real

| Capability | Code | What it actually gives you |
|---|---|---|
| **Server-set timestamps** | `_finalize_cp_signature` (`server.py:17206`) | The client's `affirmedAt` is kept *and* a server-vouched `affirmed_received_at` is stamped beside it. The two are separate fields; the server never presents the client's claim as its own. |
| **Backdate detection** | same function | A claimed signature time in the future (> now + skew) or implausibly older than the document date is stamped `affirmation_flag: FUTURE / IMPLAUSIBLE_OLD / UNPARSEABLE`. The value is preserved and annotated, never silently corrected or dropped. |
| **Lock on sign** | `server.py:17650` | Nine IMMEDIATE log types set `is_locked: true` at submit. A later edit returns **HTTP 423** — "This log is finalized and cannot be edited. Create an amendment instead." |
| **Overnight freeze** | `_eod_freeze_sweep` (`server.py:3586`) | End-of-day logs that were signed are frozen after their date passes, stamped `finalized_by: "system:eod_sweep"`. Logs that were *never signed* are deliberately **not** sealed — they are flagged as an unfinished obligation instead. |
| **Amendment as child** | `POST /logbooks/{id}/amend` | A correction is a linked child record sharing `(project, type, date)`, not an edit. The original stays. |
| **Append-only signature ledger** | `signature_events` | The only operations in the entire codebase are `insert_one`, `find`, `find_one`, `count_documents`. There is **no update and no delete path**. Each event carries a monotonic `version`. |
| **Content hashing** | `compute_content_hash` (`server.py:13446`) | SHA-256 over `json.dumps(content, sort_keys=True)` of the snapshot at signing time. |
| **Integrity + gap check** | `GET /signature-events/verify/{type}/{id}` | Re-computes each hash and reports `integrity_valid` per event, `all_valid`, and `has_version_gaps` (a missing version number implies a deleted event). |
| **Who signed, in what capacity** | `signer.authenticated_role` + `acting_capacity` | Server-verified role stored alongside the client-claimed one, explicitly for §3301.13.13. |
| **Presence evidence** | `checkins.source_ip / user_agent / device_fingerprint` | Commented in source as "Detective, not preventive" — makes a stale-URL or off-site check-in *queryable*, not blocked. |
| **Geofence** | `card_audit.haversine_m` / `compute_geofence`, default radius 150 m | Each sign-in records `within_geofence: true/false/None`. `None` means the project has no coordinates — recorded as unknown, not as pass. |
| **Fraud queries** | `card_fraud_flags` | Same card at two sites same day; one card across workers; repeated mismatch; out of geofence; expired card used. |
| **Frozen cert snapshot** | `checkins.sst_*` | What the card said at the moment of entry, never overwritten. |
| **Server-side validation** | `require_approved` dependency, company-scoped queries, `423` on locked writes | Cost-bearing endpoints refuse pending accounts; cross-tenant logbook writes have their own test suite. |
| **Export** | WeasyPrint PDF per logbook, per day, per project | Real, ungated. |

### What is NOT real — say this plainly

**Tamper-evidence against someone with database access is not implemented.**

`content_hash` is an **unkeyed** SHA-256 stored in the same document as the
`content_snapshot` it hashes. There is no HMAC, no server-held signing key, no
`prev_hash` chain, no Merkle structure, and no external anchoring — I grepped
for all of them and found zero occurrences. Anyone who can write to Mongo can
edit the snapshot, recompute the hash, and `verify` will report `all_valid: true`.

What the hash *does* catch: partial or accidental corruption, a snapshot edited
without recomputing, and — via `has_version_gaps` — a deleted event. That is
integrity checking. It is not cryptographic proof against an insider.

Two further limits worth knowing before anyone writes copy:

- The signature ledger is append-only **by application code**, not by database
  constraint. Nothing at the storage layer prevents a direct write.
- `audit_logs` is explicitly purgeable: project hard-delete calls
  `db.audit_logs.delete_many(...)` (`server.py:10325`), by owner design.
- `audit_log()` is called at only **17 distinct actions** — including
  `logbook_finalize`, `logbook_amend`, `logbook_delete`, `checkin_create`,
  `checkout`, `project_create`, `user_update`. It is not blanket coverage.

### So what can it prove that WhatsApp and a binder cannot?

Concretely, and only this:

1. **That a log was signed, by a named authenticated user, in a stated capacity, at a server-witnessed instant** — and that the claimed time was checked for plausibility and flagged if it was not.
2. **That the log could not be edited after signing** — a later write returns 423, and a correction exists as a separate linked child with its own signature event.
3. **That a specific worker was physically at a specific gate at a specific minute**, with card-validity frozen as of that minute, an IP/user-agent/device fingerprint, and a geofence verdict.
4. **That nothing in the signature sequence is missing**, via version-gap detection.
5. **That the whole window can be produced as a PDF on demand**, rather than reconstructed from a chat scroll.

A WhatsApp thread has none of 1–4 and only an unstructured version of 5.
A binder has an unverifiable version of 1 and none of 2–4.

---

## 5. Which argument holds up

**Ranked by how honestly the product can back it today.**

| Rank | Argument | Reasoning |
|---|---|---|
| **1** | **(c) "Stop Work Orders cost X per day, this shortens them"** | Requires nothing technical, and the product does back the mechanism: `dob_logs` ingests `swo` as a first-class `record_type` from NYC Open Data, classifies severity, and pushes a throttled critical alert on escalation to `Action`. The economic claim itself is an external fact, not a product claim, so nothing in the app has to be true for the headline to be true. |
| **2** | **(a) "Answer any DOB question in under a minute"** | Half-backed. Retrieval is real and fast — logs are indexed by `(project, date, category)` and by `(project, log_type, date)`, and per-logbook / per-day / per-project PDFs are ungated. But the **one "export the audit window" endpoint** (`/projects/{id}/logbook/export`) sits behind `v2_logbook`, which **fails closed by default**, and the whole `/project/{id}/audit` screen with it. It also emits a four-column completeness table — date, category, status, deficiency reason — with **no photos and no signatures**. Defensible if scoped to "pull up any signed daily log as a PDF"; not defensible as "export the audit binder". |
| **3** | **(b) "Your record can't be backdated"** | **Do not run this.** The product detects and *flags* a backdated claim (`affirmation_flag`), locks records at signature, and keeps an append-only ledger — but the hash is unkeyed and stored beside the data it protects. Anyone with DB access can rewrite both and pass verification. "Can't be backdated" is a cryptographic claim the code does not support, and it is the one claim an opposing expert would test first. |

**Recommendation: lead with (c).**

It is the only one of the three that needs nothing from engineering to be true,
it speaks to the buyer's actual loss, and the product genuinely supports the
follow-through — SWO ingestion, severity escalation, alerting, and a signed
daily record you can hand an inspector.

Use **(a) narrowed** as the proof-point directly beneath it: *"Every signed
daily log, one tap to PDF."* That is true today, ungated, and demonstrable.

Keep **(b)** out of the headline. There is an honest version of it —
*"Signed logs lock. Corrections are amendments, not edits."* — which is exactly
what the code does and survives scrutiny. It is a body-copy line, not a promise.

---

## 6. Design tokens

Two themes. Both are complete; the app ships light and dark.

### Dark (default)

| Token | Value |
|---|---|
| Background gradient | `#050a12` → `#0A1929` → `#050a12` |
| Card / glass fill | `rgba(255,255,255,0.06)` (hover `0.10`) |
| Surface / glass bg | `rgba(255,255,255,0.08)` (hover `0.12`) |
| Border subtle / medium / strong | `rgba(255,255,255,0.10)` / `0.20` / `0.30` |
| Glass border | `rgba(255,255,255,0.15)` (hover `0.30`) |
| Primary blue | `#3b82f6` |
| Success / verified | `#4ade80` · state `#22c55e` |
| Warning / attention | `#fbbf24` |
| Error / critical | `#f87171` · icon `#ef4444` · fill `#dc2626` |
| Caution / elevated | `#facc15` / `#fb923c` |
| Text primary | `rgba(255,255,255,0.90)` |
| Text secondary | `rgba(255,255,255,0.60)` |
| Text muted | `rgba(255,255,255,0.55)` |
| Text subtle | `rgba(255,255,255,0.30)` |
| Shadow | `rgba(0,0,0,0.30)`, offset `0 4`, radius `12` |

### Light ("Blueview")

| Token | Value |
|---|---|
| Background gradient | `#d0dcf0` → `#D6E4F7` → `#ccd8ee` |
| Card fill | `rgba(255,255,255,0.92)` → `rgba(219,234,254,0.65)` vertical |
| Surface | `rgba(255,255,255,0.85)` |
| Sunk surface | `rgba(219,234,254,0.45)` |
| Border subtle / medium / strong | `rgba(191,219,254,0.40)` / `0.60` / `rgba(147,197,253,0.70)` |
| Primary blue | `#1565C0` |
| Icon pod | bg `rgba(21,101,192,0.10)`, border `rgba(21,101,192,0.20)`, icon `#1565C0` |
| Success | `#2E7D32` · state verified `#166534` |
| Warning | `#E65100` · state attention `#7A5300` |
| Error | `#C62828` · text `#B91C1C` |
| Caution / elevated | `#FFD54F` / `#EF6C00` |
| Accent | `#60a5fa` |
| Text primary | `#0A1929` |
| Text secondary | `rgba(10,25,41,0.75)` |
| Text muted | `rgba(10,25,41,0.65)` |
| Text subtle | `rgba(10,25,41,0.50)` |
| Scrim | `rgba(10,25,41,0.72)` |
| Shadow | `rgba(30,58,138,0.15)`, offset `0 8`, radius `24`, elevation `6` |

Outdoor-legibility banner colours (used on site screens): warn `#92400e` on `#fef3c7` border `#d97706`; danger `#b91c1c` on `#fee2e2`; ok `#166534` on `#dcfce7` border `#15803d`.

### Radii, spacing, type

| | |
|---|---|
| Border radius | `sm 8` · `md 12` · `lg 16` · `xl 24` · `xxl 32` · `full 9999` |
| Spacing | `xs 4` · `sm 8` · `md 16` · `lg 24` · `xl 32` · `xxl 48` |
| Touch target | min **56 px**, primary **72 px** (not 44 — deliberate; gloved outdoor use) |
| Font sizes | `xs 11` · `fine 12` · `dense 13` · `sm 14` · `md 16` · `lg 18` · `xl 24` |
| hero | 48 / weight 200 / letter-spacing −1 |
| h1 | 36 / 300 / −0.5 |
| h2 | 24 / 400 |
| h3 | 18 / 500 |
| body | 16 / 400 |
| small | 14 / 400 |
| label | 11 / 500 / letter-spacing **2** / UPPERCASE |
| stat | 36 / 200 |

**Wordmark** (`HeaderBrand.js`): 27 px, weight 300, letter-spacing **6**, uppercase, max-width 280.
Font stack — web: `Montserrat, "Gotham", "Futura", "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif`; iOS: `Avenir Next`; Android: `sans-serif-light`.
No custom font files are bundled — there is no `expo-font` plugin in `app.json`. On web, Montserrat is only used if the host page provides it; otherwise it falls through the stack.

**Contrast note for the designer:** the palettes are AA-tuned and the values carry their measured ratios in source comments (e.g. light `attention` `#7A5300` at 4.77:1, chosen at hue 41° specifically to stay 42.5° away from critical red so "expiring" and "violation" stay distinguishable). Substituting prettier hexes will break that.

---

## 7. Screenshots

**Not captured.** Reason, plainly: the six screens all require authenticated,
seeded data behind the API. The frontend defaults to `https://api.levelog.com`
(`src/utils/api.js:5`), and shooting production would put real client data into
marketing assets. The local alternative needs MongoDB — Docker is installed
(v29.5.2) but its daemon is not running on this machine, there is no local
`mongod`, and no `.env` exists in `backend/` or `frontend/`. Starting Docker
Desktop is your call, not mine.

`./screenshots/` was not created.

### To shoot them yourself

Web dev server (verified working — it bundles and serves):

```bash
cd frontend && npx expo start --web --port 8081
```

Backend, once a Mongo is reachable:

```bash
cd backend && MONGO_URL=mongodb://localhost:27017 DB_NAME=levelog JWT_SECRET=dev uvicorn server:app --port 8000
```

Point the app at it:

```bash
cd frontend && EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start --web --port 8081
```

Seed (dry-run by default; goes through the real HTTP endpoints, so the Daily
Jobsite Log's Step 1 reads genuine check-in data):

```bash
python backend/scripts/seed_857_prescott.py --execute --base-url http://localhost:8000
```

There is a matching teardown at `backend/scripts/teardown.js`, scoped to that
project id.

### Routes to capture, at 390×844 and 1440×900

| # | Route | Needs |
|---|---|---|
| 1 | `/logbooks` | CP login |
| 2 | `/logbooks/daily_jobsite` | CP login + a project with check-ins |
| 3 | `/logbooks/preshift_signin` | CP login + roster |
| 4 | `/checkin` | Admin or CP login + a project with NFC tags |
| 5 | `/project/{id}` | Admin login + a project with a real `nyc_bin` |
| 6 | `/reports` | Any login + at least one filed logbook |

### Credentials

**There are no demo credentials in the repo, and I did not create any.** No
`.env`, no seeded users, no fixture accounts. Registration is open
(`POST /api/auth/register`, `/register` in the app), but a new account is
**pending by default** and lands on `/demo` — a read-only holding screen — until
an admin approves it. To shoot the six screens you need an approved `admin` and
an approved `cp` account created against your own database.

**One flag to set before shooting screen 5's audit tab or anything under
`/project/{id}/audit`:** insert a `feature_flags` document with
`flag: "v2_logbook"` and `enabled_globally: true`. Without it those endpoints
return 404 by design.
