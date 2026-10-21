# LeveLog — Independent Product, Technology & Business Due Diligence

| | |
|---|---|
| **Baseline** | `main` @ `8af813eacbcce0373c5a9dc401a33e9728476197` ("Report photos: daily logs only…", #806), 2026-10-15 |
| **Report date** | 2026-10-19 |
| **Nature of work** | Read-only repository investigation. No code modified, no server run, no production database, API or message touched, no tests executed. |
| **Intended reader** | An outside business analyst who has never seen the product. |

---

## 0. How to read this report (method, limits, confidence)

**What "baseline" means here.** The task asked for the *deployed* commit. The repository contains no deployment record. The backend exposes `/api/version`, and CI has post-deploy workflows that wait for a deployed SHA, but nothing in the repo says which SHA production runs today. The baseline is therefore the head of `main` (`8af813e`). Production may be behind it. The git history is also shallow: only 56 commits, dated 2026-10-11 to 2026-10-15, are visible, so the track record cannot be reconstructed from git.

**How the evidence was gathered.** Nine parallel read-only investigators each covered one domain: compliance records, workforce and check-in, offline, photos/Dropbox/plans, reporting, WhatsApp core, WhatsApp workflows and DOB monitoring, platform/security/cost, and maturity/claims. I then read all nine sets of notes (about 384 KB) and wrote this report.

I personally re-checked six of the highest-impact claims in the code. All six held:
- `has_current_esra_consent` is defined (`server.py:22270`) and has no callers.
- `stripe` is never imported.
- `GET /signature-events/{id}` and `/document/{type}/{id}` (`server.py:25115`, `25147`) check only login and approval, not tenant.
- Platform feature flags and risk weights are writable through `get_admin_seat_user` (`server.py:7654`), a company-level gate.
- `POST /checkin/upload-osha` (`server.py:19294`) is public.
- `DELETE /logbooks/{id}` (`server.py:33837`) has no filed-record check.

Every other finding rests on an investigator's code reading. Where a claim is load-bearing I say "confirmed by code read" (a reader traced the path) or "suspected" (inferred, not traced).

**What this report is not.**
- It has **no production access**. All usage figures are self-reported by the operator in repo docs and code comments. They are the only usage evidence available and are not independently verifiable.
- It has **no external market research**. Statements about what is "standard" in construction software come from general domain knowledge. No competitor product was examined and no competitor capability is asserted as verified.
- It does **not** conclude that a feature works in the field because it has tests. The test suite is large but mostly structural (see §E and §A.4).

**Status vocabulary** (used throughout):

| Tag | Meaning |
|---|---|
| **PROD** | Implemented and on a live code path by default. This is *code-level* evidence of being enabled, not proof of field reliability. |
| **COND** | Implemented but needs a flag, env var, opt-in, role or per-project setting. The condition is named. |
| **SHADOW** | Logic runs; real outward actions are intentionally suppressed. |
| **PARTIAL** | Works for a subset; important parts are missing. |
| **PLANNED** | Present only as docs, stubs, dead code or an unwired prototype. |
| **UNVERIFIED** | Cannot be determined from the repo. |

Line references are to `backend/server.py` at the baseline unless a path is given. That file is 78,885 lines, so a few references may drift by a line or two.

---

## A. Executive product definition

### A.1 What LeveLog actually is

LeveLog is a **vertical software product for New York City general contractors, built around the DOB-required paper trail of a jobsite and extended with a WhatsApp-based field-operations assistant**. Concretely it is five things bolted together on one backend (FastAPI + MongoDB, a single 78.9k-line `server.py` plus about 100 library modules) with one Expo/React Native app (iOS, Android, web):

1. **A digital logbook and signature system** for 13 NYC site-safety record types. Records are signed, locked and amended rather than edited, and rendered as legal-style PDFs.
2. **A zero-install worker gate.** A worker taps an NFC sticker or scans a QR code and lands on a server-rendered web page. There is no app and no login. The worker registers (phone, photo of the SST/OSHA card read by a vision model, company/trade, a 12-item orientation checklist, a drawn signature) and checks in. Later check-ins take one tap.
3. **An offline-capable site tablet / inspector view** in the native app. It caches submitted logbook PDFs and (conditionally) day-level detail so records can be shown with no internet.
4. **A reporting layer.** There is a deterministic daily site report emailed from the logbooks, plus (new, four days old at baseline) a periodic "progress report" PDF with a short WhatsApp message.
5. **A WhatsApp assistant (unofficial gateway).** It reads linked project groups and answers admins/PMs in private chat, with quote-verified citations of what was said. It also runs a punch-list workflow, a morning brief, DOB/DOT alerts into a GC group, and a plan-drawing Q&A. Its two "follow-up" engines (commitment tracking and sub chasing) are SHADOW only.

Around these sit DOB/DOT/311 public-data monitoring, a Dropbox-to-R2 document mirror, a plan-drawing indexer, a statistical "DEFCON" risk score, and an operator console.

### A.2 What it is *not* (so the analyst does not over-credit it)

- It is **not** a project-management, scheduling, cost or document-control platform. There is no schedule-vs-actual, no % complete, no budget, no change orders, no RFIs/submittals, no pay applications or draw requests.
- It does **not** file anything with DOB. The renewal-filing automation was built and then removed (MR.14). The "Automated filing — coming soon" tile is a permanently disabled button.
- It has **no owner/lender portal**. The code's "owner" screens are the *platform operator's* admin console.
- It has **no billing, no plans, no checkout and no self-serve onboarding**. The operator creates companies and hands passwords over by hand.
- Its AI is **not Claude-based**. Production calls go to OpenAI (gpt-4o, gpt-4o-mini, Whisper, embeddings), a Qwen vision model on DeepInfra, Gemini (weekly jobs) and AWS Textract.

### A.3 Stage of the company, as the repo shows it

| Fact | Evidence | Source type |
|---|---|---|
| The database held **three companies** on 2026-09-15: a seeded `test` company, one real company (62 workers, 2 projects) and one with 0 workers and 1 project | `docs/audits/one-defect-list-2026-09-13.md`, CORRECTION block | Operator self-report |
| That real company shares the operator's "Blueview" branding and appears to be founder-adjacent | same, plus naming in code/docs | **Inference: ask** |
| 248 e-signatures applied 2026-03-10 → 2026-09-01 (240 on customer projects) | `docs/compliance/esra-consent-retrospective-exposure.md` §3 | Self-report |
| 360 filed logbook records on 2026-09-13 across 7 of 13 types; **6 types had zero records** (SSC/SSM, hot work, concrete, crane, excavation, fall protection) | `docs/audits/render-migration-test-list-2026-09-13.md:34-36` | Self-report |
| 7 superintendent logs filed 2026-09-04 → 09-14, all by one account | `six-from-the-operator-2026-09-14.md` | Self-report |
| 505 workers have signed at one project's kiosk | `frontend/src/utils/signatureDeferral.js` header | Code comment |
| Only one live WhatsApp group is repeatedly referenced; "624 webhook deliveries across its entire life to 2026-04-20" | `lib/rate_limits.py` comment | Code comment |
| **No pricing, billing, contract, LOI, invoice or revenue record exists anywhere** | grep; `stripe==14.1.0` pinned, never imported; `server.py:9183` "billing (none exists yet)" | Verified |

**Net read:** this is a **single-operator, AI-assisted build at very high velocity, in design-partner / early-production state, with one visibly active site**. It is not a scaled product with a customer base. Development velocity is real: about 9–12 PRs per day, `server.py` grew from about 41k lines (2026-09-04) to 78.9k (2026-10-15), and 150 AI co-author trailers appear in 56 commits. So is review risk, because there is one human reviewer and no branch protection.

### A.4 One-paragraph honest definition

> LeveLog is a NYC-specific compliance-records and workforce-gate system for general contractors that records signed daily safety logs and worker sign-ins in a locked/amended structure with offline site-tablet access. A WhatsApp assistant layer sits on top. It proves, with unusually careful anti-hallucination engineering, *what was said in project chats* and *who was on site*. It does not yet run a business: there is no billing, no customer onboarding, no financial or schedule content, and no evidence of use beyond roughly one real operating company. Its legal-record claims are strong on process (lock, amend, ledger) and weak on cryptographic and identity assurance, and several tenant-isolation and public-endpoint gaps remain open.

---

## B. Complete product inventory

**Reading the table.** *User* = the daily operator of the feature. *Buyer value* is my judgement (labelled), not customer data. Counts are verified against the registry/code unless marked.

### B.1 Compliance and legal records

| Feature | Status | Target user | What it does / limits | Key evidence |
|---|---|---|---|---|
| **13 logbook types** | PROD (7 types exercised in prod; 6 unexercised) | CP, superintendent, admin | Registry of 13: daily jobsite (§3301.2), pre-shift sign-in, construction superintendent log (§3301.13.13, 11 items), toolbox talk, subcontractor orientation, OSHA/SST worker register, scaffold (§3314), SSC/SSM daily safety (§3310), hot work (FC §3504), concrete (§3310.10/3315), crane (§3319), excavation (§3304), fall protection (no DOB cite, "industry standard"). Timing classes: 10 immediate, 2 end-of-day, 1 visit-scoped. Conditional activation by project class and toggles. | `LOGBOOK_TYPE_REGISTRY` `server.py:6021-6275`; `lib/legal_render/schema.py`; `frontend/app/logbooks/*` (13 editors) |
| **E-signature + lock-on-sign** | PROD | CP / superintendent | Drawn signature (strokes only; no typed/PKI/MFA). Immediate types lock at submit (later PUT → HTTP 423). End-of-day types are 409-protected until the 03:00 ET sweep, then locked. | `:31573`, `:31617`, `:31826`; `sweep_stale_end_of_day_logs :6570` |
| **Amendments** | PROD | CP | Correction = linked child record with reason (≥6 chars), original untouched; one open amendment per parent (app check; unique index may not exist in prod). | `amend_logbook :33128`; `OPEN_AMENDMENT_INDEX_NAME :78036` |
| **Signature ledger (`signature_events`)** | PROD, weak assurance | — | Append-only *by application code*; SHA-256 of a snapshot stored beside it; version-gap detection. Verify endpoint recomputes the hash of the snapshot against itself. | `compute_content_hash :24507`; verify `:25159` |
| **ESRA e-sign consent (BB 2024-007)** | PARTIAL | Signers | Versioned verbatim consent text and endpoints. **Enforced only by the client**; the server never checks it. | `lib/esra_consent.py`; `has_current_esra_consent :22270` (zero callers) |
| **Legal PDF renderer** | PROD | Admin / inspector | Declarative engine, 13 schemas, explicit "Not recorded" handling. PDFs are **regenerated from live data on every request**; no archived copy of what was signed. | `lib/legal_render/*` (4.5k lines) |
| **Required-log engine / missing & deficiency detectors** | PROD (detectors); COND (read side) | Admin | Resolves required logs by project class and toggles; nightly detectors write `logbook_entries`. The reader (audit screen, `/logbook/*`) is behind `v2_logbook`, default OFF. | `get_required_logbooks :2939`; `_logbook_flag_enabled_for :10896` |
| **LL196 attestation PDF** | COND / PARTIAL | Admin / operator | Monthly roster-vs-SST roll-up. **Operator-run endpoint behind a default-off flag; no scheduler, no client caller.** Not a DOB submission. | `lib/logbook/ll196.py` |
| **Audit log** | PARTIAL | — | About 17–20 distinct actions. No row for draft edits, EOD freeze, reads or exports. Write failures are swallowed. | `audit_log :2098` |
| **Retention / legal hold** | PARTIAL | Operator | 7-year brake on operator hard-delete; any filed record blocks purge outright. Display-only `purge_eligible_at`. R2 object lock only for the `coi/` prefix (and that is removable by anyone with Cloudflare edit rights). | `lib/project_retention.py`, `lib/purge_dependencies.py` |
| **Legacy `/daily-logs` API** | PROD (should be dead) | — | Superseded by logbooks but still live and **never locks**. | `:24076-24240` |

### B.2 Workforce and site access

| Feature | Status | Notes | Evidence |
|---|---|---|---|
| **Worker gate** (NFC tag / QR → public web page) | PROD | Server-rendered `backend/checkin.html` (2,894 lines, EN/ES, Spanish default). No app or login. | `GET /checkin/{project}/{tag}` `:35839`; Vercel rewrites |
| **New-worker registration** | PROD | Phone + card photo (Qwen VL read) + trade/company + 12-item orientation + drawn signature; optional selfie (no face match). | `register-and-checkin :20649` |
| **Returning-worker check-in** | PROD | One tap on a remembered device; phone lookup otherwise. | `lookup-worker :21656` |
| **Card/cert logic** | PROD | Color-first class resolution (blue/yellow/red; purple "Worker Wallet" refused); three-state valid/unknown/expired verdict. | `_sst_cert_state :4347`; `resolve_card_class :3880` |
| **Access policy** | PROD | "Flag but allow." The only hard block is no OSHA/SST evidence at all, and a *typed* number satisfies it. Expired SST, unknown class, skipped orientation and off-roster company all admit and flag. | `validate_worker_certifications :5311` |
| **CP review queue** | PROD | Flagged check-ins (expired/unknown SST, trade missing); approve/send-home decisions are recorded only (no must-leave enforcement). | `:23395`, `:23711` |
| **Daily headcount / attendance** | PROD | From `checkins` (one row per worker/project/NY-day). Dedupes by (name, company); admitted collisions. No auto-checkout. | `:35321`, `:34813` |
| **Staff-assisted check-in** | PROD | Admin/CP picks a worker; no card/orientation. | `frontend/app/checkin/index.jsx` |
| **Site devices (kiosk logins)** | PROD | Username/password → `site_device` JWT bound to a project. | `:9722-9753`, `:24310` |
| **SSC/SSM + Construction Superintendent registries** | PROD (simple) | Licence numbers are free text; expiry alert; one-job-rule conflict raises an alert but does not refuse. | `:34630-34695`, `:25237` |
| **`card_audit.py`** (NFC card-chip tap, geofence, fraud flags) | **DEAD in practice** | Its gate page is route-shadowed; code comments cite zero production rows in its collections; nightly jobs run over empty data; no UI reads the flags. | `card_audit.py`; `:35812-35843`, `:37170-37180` |
| **Geofence** | **Not on the live path** | Absent from `checkin.html`. Do not cite. | grep `geolocation` |
| **COI tracking** | PARTIAL, mislabeled | It tracks the **GC's own** certificates (for permit-renewal eligibility). **No subcontractor COI tracking exists.** | `lib/coi_ocr.py`, `lib/insurance_expiry.py` |
| `eligibility_v2` / dispatcher / shadow | SHADOW, default OFF | Permit-renewal eligibility, not worker vetting. | `ELIGIBILITY_REWRITE_MODE` |

### B.3 Offline (native app only)

| Capability | Status | Notes |
|---|---|---|
| Logbook drafts and reconnect drain | PROD (design) | AsyncStorage drafts, push on reconnect |
| Filed-log photo queue | PROD (design) | Moves a photo to a "rejected" list on 401/403 |
| Site manifest and PDF cache (all submitted logbook PDFs) | PROD (design) | Foreground only; 500 downloads per run; disk reserve |
| Day-detail / signature-ink / thumbnails cache | COND | Fills only after someone opens Log Books online |
| Worker check-in offline | **Not supported** | "NOT checked in" |
| Web / PWA offline | **None** | No service worker |

### B.4 Photos, documents, plans

| Feature | Status | Notes |
|---|---|---|
| Logbook photos | PROD | Shrunk on-device to ≤150 KB / 1280 px; uploaded to R2 at capture; server enhancement is deterministic (not AI), tuned on four photos. **No EXIF, GPS or capture time stored.** |
| Photo append to a filed log | PROD | Server stamps sync time, not capture time; window closes 03:00 ET next day |
| WhatsApp group photos | PROD by code (#804, one day old) | Stored and captioned; never used in logs or reports |
| Dropbox → R2 mirror | PARTIAL | See workflow 7; several confirmed defects |
| Plan indexing, Q&A, refusal gate | COND (per-group flag, default ON) | Evaluated on one building: 26/31 = 83.9% |
| Equipment takeoff (counts per apartment) | PLANNED / operator-run | One building, one consultant's drawings |
| Project-memory search | PROD (DM/app) | WhatsApp messages, filed daily reports, photo captions; **not** Dropbox docs or plans |

### B.5 Reporting

| Feature | Status | Notes |
|---|---|---|
| **Daily site report** (3-page PDF, emailed) | PROD | Fully templated; **no generated text.** Recipients are a free-text email list (external addresses OK, no validation). |
| **Periodic progress report** (PDF + short WhatsApp message) | PROD by code, **4 days old, unsoaked** | Daily/weekly/biweekly/monthly/quarterly schedules, presets, custom ranges ≤400 days. GPT-4o summary guarded by a lexical fact-check, with deterministic fallback. |
| Owner / lender portal | **Does not exist** | |
| Financial / schedule content | **Does not exist** | Percentages are *banned in code*. |
| `lib/ai/sub_summary.py` (Gemini per-sub line) | PLANNED, unwired | Imported by no production module |

### B.6 WhatsApp / AI

| Feature | Status | Notes |
|---|---|---|
| Transport (WaAPI WhatsApp-Web gateway, one shared number for all tenants) | PROD | **No official Meta Cloud API code at all** |
| Group ingestion, binding, sender mapping | PROD | Tenant binding enforced in app code; the DB unique index is "proposed, not built" |
| Project memory Q&A (DM / app) | PROD, **best-engineered AI path** | Hybrid retrieval; quote-verified claims; "can't find that" refusal |
| Group agent (gpt-4o + tools) | PROD | Not quote-verified; any member of a linked group can invoke tools |
| Voice notes (Whisper EN/ES/YI) | PROD (cap 200/company/day) | Yiddish always flagged for review; no accuracy figures |
| Morning brief DM | PROD, COND (per-user opt-in) | Deterministic, no LLM |
| GC-group DOB/DOT alerts | PROD, COND (per-project confirmation) | Ledger-once; baselined; template or fact-checked sentence |
| Punch list / walkthrough | COND (default **shadow** send) | Assignment is real; outbound sends need per-project `live` |
| **Attention (commitment tracking)** | **SHADOW** | Records only |
| **Sub chasing / escalation** | **SHADOW** | No send call in the code path |
| DM admin actions (add job, sub, settings by plain words) | PROD, confirmation-gated | LLM-driven write surface |
| Upcoming events / reminders | PROD (opt-in) | |

### B.7 Platform and administration

| Feature | Status | Notes |
|---|---|---|
| Roles | PROD | admin, pm, superintendent, cp, demo, site_device; "owner" retired; platform operator via flag/env |
| Multi-tenancy | PROD, route-by-route | Confirmed gaps remain (§E) |
| Self-signup | PARTIAL | Every signup becomes read-only `demo`; only the operator can approve |
| Billing / plans / limits | **NONE** | |
| Operator console | PROD | About 25 `/owner/*` routes |
| Scheduler | PROD | About 40 in-process APScheduler jobs, de-duplicated by Mongo slot leases (not leader election) |
| Notifications | PARTIAL | Email (Resend) gated by `NOTIFICATIONS_ENABLED` default **false**; in-app inbox; WhatsApp. **No push, no SMS.** |
| Data export | PARTIAL | Per-document PDFs only; no tenant-wide machine-readable export |
| DOB/DOT/311 monitoring | PROD | Socrata polling every 15/30 min and 2 h; email only on severity "Action"; capped at 500 projects per tick |
| DEFCON / risk score | PROD (no flag) | About 16k lines; hand-set thresholds; **no evidence of predictive validity**; inspection inputs were contaminated with rodent-inspection data (the author's own audit) |
| Permit renewal | PARKED | Filing automation removed; daily digest remains |

### B.8 Stale or misleading documentation

The analyst should not rely on these without checking.

| Document | Problem |
|---|---|
| `README.md` | Describes only the old "DOB monitoring" product; says no frontend tests, QWEN optional, no Playwright; omits WhatsApp, OpenAI, DeepInfra, AWS |
| `memory/PRD.md` | Last updated 2026-02-01 |
| `privacy-policy.html` | Names Render as host (code says Railway); lists 3 processors where code calls 13+; omits R2, Resend, OpenAI, DeepInfra, Gemini, WaAPI, selfies/card images/voice |
| `LEVELOG-BRIEF.md` (2026-08-25) | Predates superintendent log, legal renderer, consent, all WhatsApp work. Marks `/nfc` "WORKING" (its API routes don't exist) and lists geofence/fraud as live |
| `docs/compliance/esra-bb2024-007-compliance.md` | Says the superintendent log is "NOT BUILT" (it is built and used) |
| `docs/audits/whatsapp-audit-2026-10-07.md`, `docs/operations/feature-flags.md` | Superseded; feature-flags doc does not govern WhatsApp at all |
| `docs/marketing/homepage-source-of-truth.md` | Most careful document in the repo (has a "NOT DEFENSIBLE" claims firewall) but its line cites have rotted |
| Runbook §8 (onboarding), §14.3 (nightly tick), baseline "734 passed" | Do not match code |

---

## C. Ten end-to-end workflows

Each: **steps → human actions → persistence → failure modes**. "Confirmed" means a code path was traced.

### C.1 A brand-new worker registers and checks in — PROD

1. The worker taps an NFC sticker (URL `https://levelog.com/checkin/{projectId}/{tagId}`) or scans a CP-held QR code. A Vercel rewrite sends it to the backend, which serves `checkin.html`. The Expo screens at the same path are decoys.
2. The page loads `/info` (public). It lists the project and the admin-curated trade/company roster. The language defaults to Spanish.
3. The worker types a phone number. `POST /checkin/lookup-worker` (public, no limiter) returns `found:false`.
4. **Card step.** The worker photographs the SST/OSHA card. `POST /checkin/upload-osha` (public, rate limit removed by operator ruling) downscales it and makes a paid Qwen2.5-VL call (2 attempts × 22 s; client abort at 75 s). Up to 3 retakes, then manual typing. A photo is *not* mandatory: a typed card number or expiry is accepted.
5. Optional selfie (no face match). The worker picks a trade/company from the roster, or "not listed". They tick all 12 generic bilingual orientation statements and draw a signature.
6. `POST /checkin/register-and-checkin` (public, no limiter) creates the `workers` row (the card goes to R2, with an inline base64 fallback). It writes a draft `subcontractor_orientation` logbook for the CP to sign, builds a cert row, and inserts a `checkins` row. That row holds a frozen card snapshot, IP, user agent and a FingerprintJS id (first registration only). It writes the trade pairing and raises compliance alerts and inbox notifications for expired or unknown SST.
7. The client stores `bv_worker_id/phone/name` in localStorage.

**Human involvement.** None at the gate. The CP/admin later signs the orientation draft and works the flagged-check-in queue.

**Persists.** `workers`, `checkins` (permanent; in the never-purge list), `worker_project_trades`, orientation logbook, card and selfie in R2. There is no worker-facing deletion path.

**Failure modes.**
- Tag inactive → error screen.
- Vision provider down → typed entry. A 4-day registration outage happened 2026-09-11 to 09-15 after a model-id env-var swap.
- Missing OSHA/SST evidence → blocked (the only hard block).
- **Fully offline: not supported.** The gate needs signal (no service worker), and underground sites fail on the first tap.

**Abuse risks, confirmed by code read.**
- *Impersonation:* anyone who knows a worker's phone can load his record and check in as him. There is no OTP, GPS or face match.
- *PII leak:* `lookup-worker` returns the worker's name and real card number to anyone who knows a phone number.
- *Record tampering:* posting phone + name to `register-and-checkin` overwrites the stored name.
- *Spend exposure:* the OCR endpoint is unmetered and unauthenticated.
- *Off-site check-in:* a photographed tag URL works from anywhere.
- *Response flag:* `is_new_worker:true` is returned on every success.

### C.2 A returning worker checks in — PROD

The page auto-calls `lookup-worker` with the remembered phone. It returns the worker's name, per-project trade/company and flags: oriented on *this* project, needs card rescan, and the real card number (unmasked). If the worker is not oriented on this project, the button becomes "Complete orientation" (steps 2–4, no card re-photo). "Check In Now" is never removed. The tap posts `register-and-checkin` with no card and no `device_info`.

**Persists.** A new `checkins` row (one per worker/project/NY day; a repeat tap returns "Already checked in").

**Gaps.**
- Returning check-ins store IP and user agent only. The device fingerprint is null, so the "presence evidence" claim in the brief is overstated for daily taps.
- There is no worker-side checkout and no auto-checkout, so "active now" can include stale rows (suspected).
- Drift: a card-number match under a new phone resolves to the old worker without updating the phone.

### C.3 A superintendent / CP creates and signs a legally relevant daily record — PROD

1. Logbooks home lists required logs, resolved server-side by project class and toggles. The CP opens `daily_jobsite.jsx` (4-step stepper; prefill from gate roster, headcount, weather, existing server log).
2. Every step autosaves a draft to device storage. Photos are copied to `documentDirectory` and uploaded to R2 at capture.
3. Sign: draw a mark → `Submit and Sign` → client gates (observation remedies, inspection notes, non-empty description, crews with work) → ESRA consent check (client only) → `POST/PUT /logbooks` with status `submitted`.
4. Server (`create_logbook :31234`): checks project scope, refuses PMs, runs submit gates, stamps `affirmed_received_at` with a flag if the claimed time is >5 min in the future or >2 days before the doc date, sets `cp_name` from the account (not client text), dedupes, and inserts.
5. The client then posts `/signature-events` (a snapshot **supplied by the client**).
6. The log is `submitted` but **unlocked** until 03:00 ET. Data edits get a 409 in the meantime. The nightly sweep locks it (`finalized_by: "system:eod_sweep"`, **no audit or ledger row**). After that a correction is an amendment.

**Offline.** The whole flow works on-device. The drain pushes on reconnect. The signing time is the *client clock*; the server adds a receipt time.

**Failure modes (confirmed by code read).**
- The server's "affirmed" check accepts `affirmed:true` with no ink.
- A thin or placeholder record can be signed through the API, because required content is enforced only by the UI.
- Offline-signed end-of-day logs **never receive a server-derived ledger row** (33 were affected historically and not backfilled).
- The nightly tick runs four stages under one `try/except`. A failure in stage 1 or 2 silently skips the freeze.
- An unsigned stale log stays editable indefinitely.
- `DELETE /logbooks/{id}` soft-deletes a signed or locked log with no filed-record check. It writes an audit row, but the record vanishes from every UI and PDF.
- Only 3 of 13 types print an attestation sentence above the signature (the §3301.2 daily log prints none).
- The pre-shift injury/PPE answers are enforced client-side only (67 of 384 production rows were null).

### C.4 An inspector asks for historical records during an internet outage — COND

*What exists.* On the site tablet, "Hand to Inspector (read-only)" confines the app to the Log Books screen. It is a **client-side toggle with no PIN**, released by one tap. The server control is that a `site_device` token cannot write logbooks.

*What is available offline, for a tablet that was provisioned and synced online:*

| Item | Available offline? | Condition |
|---|---|---|
| Rendered PDFs of **all** submitted logbooks (no date window) | Yes | Manifest fill completed: foreground only, 500 per run, 5-min poll, disk reserve 200 MB |
| Inline day detail (dates, signatures, photo thumbnails) | Only if someone opened Log Books online once | Backfill 60 dates per run, newest first; ink and thumbnails arrive in later passes |
| Check-in roster | **Today only** | Yesterday's roster is deliberately not shown |
| Worker / certification records | **No** | No cache |
| Drafts, anything amended or signed after the last sync | **No** | |
| Non-PDF documents, plan search, AI answers, full-size photos | **No** | |
| Web build | **Nothing** | No service worker |

*Design strengths.* A failed fetch never renders "0 workers" or "No submitted logs" (`offlineState.js`), and a readiness notice states how complete the cache is. These are unit-tested, not device-tested.

*Risks.*
- A newly provisioned tablet that loses connectivity before filling is partial.
- The auth token lasts 30 days with a sliding re-issue. An expired token does not wipe the cache, but nothing can sync until someone re-logs in with the password.
- The token sits in plain AsyncStorage.
- A reinstall or device loss destroys unsynced drafts, signatures and photos with no warning.
- I found **no evidence anywhere that a DOB inspector has ever used this flow**.

### C.5 A site device takes photos offline and syncs later — PROD (design); history of loss

*Framing correction.* The gate tablet has **no capture code**. Photos come from the CP's phone in the daily-log editor, or from the "add photo to filed log" screen.

1. Capture → compress to ≤150 KB → copy to durable storage (throws if the copy fails) → fire-and-forget upload to `POST /projects/{id}/logbook-photo`. The R2 key is a pure function of (project, activity, photo id), so a retry overwrites the same object.
2. On reconnect, `draftSync` uploads pending photos *before* the content. A 4xx marks a photo `upload_rejected` permanently.
3. For a photo added to an already-filed log, `filedPhotoQueue` queues on offline/5xx only. The server dedupes by `$elemMatch` on the R2 key and stamps the **sync time**, not the capture time.

*Failure modes.*
- **Documented past losses.** `photoRecovery.js` exists because filed logs listed photos that never reached the server. 134 filed photos had no thumbnails until 2026-10-08.
- An expired-token 401 demotes queued filed-log photos to "rejected".
- A missing local file may block the queue head (suspected).
- The global "pending sync" count covers only the generic queue (workers, review decisions), not drafts or photos.
- The generic queue's idempotency header (`X-Request-Id`) is **not enforced server-side**, so replays are at-least-once.
- The generic queue replays an offline worker *update* as a POST and an offline *delete* throws.

### C.6 A PM generates a bank / investor progress report — PROD by code, unsoaked

1. **Entry:** Project → Reports (admin or PM on the job), a WhatsApp DM ("send me a report for 588 for last 2 weeks"), or a schedule.
2. `build_project_report` reads Mongo: check-ins, filed daily logs, group chat, DOB/DOT, commitments, punch items, upcoming events. If any read fails the report is refused. It never prints zeros as fact.
3. `progress_report.compute` is pure code: per-sub days on site and average/peak workers (from gate check-ins), work lines from daily logs, observations, new DOB/DOT, late commitments, punch counts, next-14-days events.
4. Up to 40 daily-log photos are screened by the vision model (kind/blur/people/documents), cached, and at most 15 are chosen. **Captions are the sub's own log text, never model text.**
5. A gpt-4o summary of 5–8 sentences is written from a facts list. A lexical check requires every number, date and capitalized word to appear in the facts. Otherwise a deterministic fallback is used. Percentages are banned in code.
6. WeasyPrint builds the PDF → R2 → a 30-day no-login link → a `project_reports` record → delivery (WhatsApp and/or email to the company's own admins/PMs only).

**Human involvement.** The PM clicks Generate and forwards the PDF to the owner or lender. LeveLog does not send to external parties on this path. There is no editing, approval, signature block, logo customization or section choice.

**What it contains and omits.** It has independently sourced gate headcount by sub by day, dated photos, DOB/DOT events, overdue commitments and punch counts. It has **no** % complete, schedule or variance, quantities, cost, change orders, draw request or G702/G703, retainage or inspector sign-off. The PDF literally states "no schedule is on file." A monthly report is the same template over a month window, not a lender draw package.

**Failure modes.**
- **Confirmed:** a report whose PDF failed is cached under its period key with no PDF and is never rebuilt.
- Suspected:
  - The schedule fires only when the New York hour is 8, with no catch-up.
  - Biweekly uses ISO-week parity, which gives a 3-week gap across week 53.
  - The "worked X of Y days" count ignores holidays.
  - Group-chat text is sent to OpenAI.
  - There is no visible rate limit on generation.
- The attribution check is lexical, so a true number given to the wrong sub would pass.

### C.7 A GC connects Dropbox and reaches project documents — PARTIAL

1. Admin → Integrations → "Connect to Dropbox". `GET /dropbox/auth-url` needs only login, with no admin check. The OAuth request carries **no scope parameter**, so the scopes granted are whatever the Dropbox app console holds (not in the repo).
2. The callback stores access and refresh tokens **in plaintext in Mongo**. The Dropbox app key *and secret* have hard-coded default values in `server.py:999-1000`.
3. The admin picks a folder (`POST /projects/{id}/link-dropbox`). **Linking does not start a sync.**
4. Sync (`_sync_project_to_r2`) lists the folder recursively, downloads each changed file into memory, and writes it to R2 key `{company}/{project}/{filename}`. PDFs are queued for plan indexing. Triggers are the manual Sync button, the first open with no cached rows, or a webhook that must be registered by hand and is **unsigned**. There is **no polling cron**.
5. Reads are served from R2 through an authenticated proxy. The documents stay readable after a token dies or the connection is disconnected.

**Confirmed defects.**
- **R2 key collision on basename:** `A/plan.pdf` and `B/plan.pdf` overwrite one object while two rows point to it (a "wrong document, right-looking" failure, open since the 2026-09-13 audit).
- Files deleted in Dropbox are never removed.
- A failed continuation page silently truncates the sync.
- The "force refresh on 401" does not force a refresh.
- No tests cover the webhook, token refresh, collisions or deletion.

**Unknown.** Whether the Dropbox app is in development mode (the `too_many_users` error text suggests a tester cap), and whether the webhook is registered in production.

### C.8 A superintendent / PM completes a photographic walkthrough and assigns punch items — COND

1. A DM-eligible, opted-in admin/PM texts "starting walkthrough at 588" (or just sends a photo). A per-walker lock (in-process plus a Mongo lease) serializes turns. This was added after a real race.
2. Each photo is downloaded in **full** (the 400-px webhook thumbnail is rejected), stored in R2, and becomes an item. Trade, floor and area come from the caption by **regex word lists** (EN/ES). A trade from a caption is a "guess" the walker can override. Photo pixels never choose the trade.
3. Free text is read by an LLM that *proposes* actions; code validates them against real item numbers and trades. A separate reader attaches batch notes ("last 8 pics all interior").
4. "done" → every photo must sit on an item. Blank-caption items get an 8-word vision description marked "(auto)". The bot asks for floor/area, shows a grouped draft, and the walker edits by words.
5. Assignment is suggested from the sub's designated punch contact or the last person that trade went to. The walker names people, and each assignee passes a recipient guard. Unresolved items stay `?` and block sending.
6. "send" creates `punch_items` (P-ids), each linked to an `attention_item`, plus a private no-login assignee link per person.
7. **Outbound delivery depends on `punch_sends`, default `shadow`.** In shadow mode the items still become `open` and appear in the app and brief, **but the subcontractor is never messaged**. In `live` mode the bot posts one @mention message per assignee plus each item's photo. Live requires an admin to type the job address back in a DM.

**Human involvement.** The walker does everything and confirms at the recap. The AI proposes and parses.

**Evidence of use.** Commit messages show live runs on the operator's own job, 2026-10-11 to 10-13. I found no other customer.

**Failure modes.**
- All vocabulary is EN/ES (Yiddish only through voice transcripts).
- Single common words map to trades.
- About 400 punch tests encode dozens of incident-specific cases (evidence of real iteration, and of fragility).
- A draft unsent for 24 h gets one reminder.

### C.9 A subcontractor returns a repair photo and the PM closes the item — PARTIAL

Three entry paths move an item `open → ready_to_check`:

- **Group post** "done P23" with a photo, from the assignee only. The status change happens later in the attention worker's tick.
- **DM** "done P-588-1" from the assigned number.
- **Private web link** → "I fixed it" with camera upload.

**The repair photo is not AI-verified.** The code stores the quote, photo key and actor and does nothing else. The vision model only describes blank captions on the *original* defect photos. The photo is optional on all three paths.

A sub can never close an item. The PM/admin closes or reopens ("P23 ok", "P23 not done — still chipped"), or uses the in-app action.

**Gaps.**
- There is no timer that nags the PM about `ready_to_check`, and no live reminder to the sub (chasing is shadow).
- A "done" from a non-assignee is silently ignored.
- The group-path close lives inside the attention worker, so a bot-off group or `WA_ATTENTION_DISABLED=1` would stop it (suspected coupling).
- The actor recorded for a group "done" is a raw sender id, and for a link it is `link:<key>`, with no authenticated identity.
- A leaked link lets anyone mark that assignee's items ready.
- The module docstring says a bare "done" reply works. The code requires a P-id or "done N" (stale docstring).

### C.10 An owner asks the AI about something discussed in a project WhatsApp group — PROD, narrower than it sounds

**Who can ask.** Only an **opted-in company admin or PM**, by private chat or the app's Project → Search. The "owner" role is retired. **A building owner, lender, subcontractor or client cannot use it.** Anyone else gets an identical non-revealing refusal.

1. **Ingest.** The webhook is authenticated by a shared secret in the URL (≥32 bytes, fail-closed). The group binding (group → company → project) is verified, and `whatsapp_messages` rows are stored. Voice notes are Whisper-transcribed. Nothing from an unlinked group is stored.
2. **Index.** Every 120 s a job copies rows into `project_memory` with embeddings (text-embedding-3-small) and keywords. Atlas Search and vector search are used when available. Otherwise an in-process fallback scans the newest 3,000 rows per project. Which mode production runs is unverified.
3. **Retrieve.** Every query is filtered by both `company_id` and `project_id`. The DM job selector is a fuzzy match on address and street words with a 30-minute "sticky" job.
4. **Answer.** gpt-4o (temperature 0, JSON mode) sees the top 15 records (25 for timeline questions) and must return claims with exact quotes. Deterministic code then drops any claim whose quote does not appear verbatim in a retrieved source. If nothing survives, the answer is "I can't find that in the project history."
5. **Cite.** Each claim is shown with who, group, date/time, the exact quote, "relayed by" and "planned — not confirmed as done" rewrites, and an audio-link flag for unreliable voice transcripts. The app can open the original message.

**Where it can be wrong.**
- A quote can be verbatim but mean something different (negation, subject).
- If retrieval misses the right message the answer is a false "can't find".
- An LLM outage is **indistinguishable from "not in history."**
- Wrong-job selection within the same company.
- Attribution depends on admins manually mapping unknown senders (`@lid` ids).
- A decision spread across several messages may be partial.
- The pre-rendered answer cache is in-process only.

**What prevents cross-project leakage.** The double filter at query time, route-level access re-proving, and 53 + 56 + 20 targeted tests. No bypass was found.

**Evidence of accuracy: none.** The repo has one *synthetic scripted* scenario (12 questions) and no recorded real-model result. **No accuracy number exists and none should be quoted.**

---

## D. Differentiation matrix

Judgements come from general domain knowledge and the code, **not from comparing against competitor products** (not done). The test applied: *if a well-funded construction-software incumbent wanted this, could it copy it in about a quarter?*

| Capability | Classification | Why | Switching cost / data value | Copy difficulty |
|---|---|---|---|---|
| Digital daily log, toolbox talk, sign-in sheets | **Commodity** | Standard in field-management tools | Low | Trivial |
| Check-in / attendance by QR or NFC | **Commodity** (with a good UX twist) | Common category. LeveLog's zero-install, EN/ES, one-tap flow is a better adoption story, but identity is weak | Medium (workforce history) | Easy |
| Photos and daily activity capture | **Commodity** | Common | Low | Easy |
| Dropbox mirror | **Useful integration** | Plain sync, with known defects | Low | Easy |
| Punch lists | **Commodity** | A mature category. The WhatsApp-native assignment path is the new part | Low–Medium | Easy–Moderate |
| **NYC-specific form set** (§3301, §3310, §3314, §3319, ESRA language) with locked/amended records and a legal-style renderer | **Meaningful differentiator** (vertical depth) | Needs local regulatory fluency. Not hard to replicate technically, but incumbents rarely invest in one city's forms | **High once years of signed records exist** | Moderate (domain knowledge, not code) |
| Lock / amend / ledger record model | **Useful, not a moat** | Good process. The hash is unkeyed and stored beside its data (the author says so); PDFs are regenerated. A skilled adversary or expert witness can attack it | Medium | Moderate |
| **Offline site tablet with a full submitted-log cache** | **Meaningful differentiator** if proven in the field | Few products do this well, and the engineering is extensive. Native only; no device-level tests; never shown to an inspector | Medium | Moderate–Hard |
| **Evidence-or-silence AI** (quote-verified memory, fact-checked summaries/headcount, plan refusal gate) | **Possible long-term moat** (as an engineering discipline and trust story) | Unusually careful. The accuracy is not yet measured, and the discipline can be copied | Medium–High (accumulated chat memory) | Moderate |
| WhatsApp as the field interface | **Meaningful adoption differentiator, major dependency** | Meets subs where they are. Built on an unofficial gateway with one shared number | Medium | Easy to copy, hard to do safely |
| Plan-drawing Q&A / takeoff | **Interesting, pilot-grade** | One building, 83.9% on a curated set, takeoff operator-run | Low today | Hard to match quality, but unproven |
| DOB/DOT/311 monitoring and alerts | **Useful integration** | Public data, many players. SWO alerts are valuable. The risk score has no validity evidence | Low | Easy |
| Progress report | **Conventional report with a trustworthy provenance** | Machine-sourced headcount and photos are good. It lacks everything financial | Low | Easy |
| Shabbos / Yom Tov-aware send scheduling | **Niche differentiator** | Matters in this market segment (the pilot base). The Hebrew-calendar correctness is unverified | Low | Easy |
| Combination: gate headcount + signed logs + chat memory + reports in one tenant | **Possible moat via data gravity** | Each part is copyable; the *joined, independently sourced record of a job* is the distinctive asset | **High after adoption** | Hard to get adopted |

**Honest summary:** LeveLog's moat, if one forms, is **vertical depth plus accumulated signed history plus a trusted AI evidence layer**, not any single feature. None of it is yet proven by customers. Feature breadth is wide (and partly shallow), which is not a moat.

**Who buys and who uses.**
- *Buyer:* the GC owner or principal of a mid-sized NYC GC with several concurrent jobs. The cost of being wrong (a stop-work order, a DOB penalty, a dispute) lands on them.
- *Daily users:* the Competent Person / superintendent (logbooks), the PM and admin (WhatsApp, reports), and workers (gate). Subs are indirect users via WhatsApp and the punch link.
- *Not served today:* owners, lenders and inspectors.

---

## E. Technical and compliance risk register

Severity reflects commercial impact if it materializes. Likelihood is my judgement. **C** = confirmed by code read, **S** = suspected / needs verification. IDs are referenced in later sections.

### E.1 Critical / High

| ID | Risk | Sev | Lik | C/S | Evidence | Recommended validation |
|---|---|---|---|---|---|---|
| R1 | **Cross-tenant read gaps at HEAD.** `GET /daily-logs/{id}` and `GET /signature-events/{id}` and `/document/{type}/{id}` (full snapshot and stroke data) have no tenant check. `GET /reports/logbook/{id}/pdf` and several `/projects/{id}/…` stats and v2 audit/export routes lack `require_project_access`. A compliance-alert resolve is unscoped. Needs a known ObjectId. | High | Med | C | `:24222`, `:25115`, `:25147`, `:25940`, `:10913-11300`, `:25927` | Run an authenticated cross-tenant test per route; fix to a central dependency; add a route census that fails CI |
| R2 | **Any customer company admin can change platform-wide feature flags and risk weights.** `get_admin_seat_user` is company-level | High | Low–Med | C | `:7654`, `:10748-10848`, `:11544` | Gate to operator only; audit existing flag rows |
| R3 | **Public unauthenticated endpoints with cost or PII exposure.** `upload-osha` (paid vision, no limit/spend breaker), `lookup-worker` (name and card number by phone), `register-and-checkin` (writes images; limiter removed), `card_audit` POST routes (second VLM path), the logbook-photo route (ObjectId only) | High | Med | C | `:19294`, `:21656`, `:20649`, `:29946` | Add a spend breaker and per-IP/device limits; mask card numbers; consider SMS OTP for returning workers |
| R4 | **WhatsApp transport is one unofficial WhatsApp-Web session on one shared number for all tenants.** A ban, disconnect or ToS action takes every customer's groups, DMs, briefs and alerts down. Detection is email-only, within about 15–30 min. No Cloud-API fallback code exists | High | Med (judgement) | C (architecture) | `server.py:1016`, `lib/waapi_monitor.py`; internal audit lines 569-576 | Get WaAPI's terms and uptime history; plan an official-API migration; per-tenant numbers |
| R5 | **Identity and presence assurance are weak.** Phone-as-identity, no OTP/GPS/face match, "flag but allow" policy, shared-signature carry-over permitted by operator ruling, signatures drawn only, `affirmed:true` accepted without ink | High (legal) | Med | C | §C.1, §C.3 | Counsel review of what the records must prove; add second factor for gate; require ink server-side |
| R6 | **E-sign consent not enforced server-side.** 248 signatures predate any consent. A direct API caller or old build can sign without a recorded agreement. Legal characterization unresolved | High | Med | C | `:22270` zero callers; retrospective doc | Counsel opinion; server gate; log consent state at sign time |
| R7 | **Record integrity weaknesses.** Unkeyed hash beside data; verify compares snapshot to itself; PDFs regenerated, no archived copy; EOD sweep leaves no audit/ledger row; a locked record can be soft-deleted; stale unsigned logs editable forever; client-clock signing time | High | Low–Med | C | §C.3; `:24507`, `:25159`, `:33837` | Archive PDF + hash at lock; HMAC or external anchor; block delete of filed records; add a hard date bound |
| R8 | **Disaster recovery undemonstrated.** The backup doc is dated 2026-05-05, tier cells blank, restore drill "pending". R2 (photos, plans, PDFs, card images) is not backed up. The freshness script is unscheduled. No pager | High | Low (but catastrophic) | C | `docs/operations/backup-restore.md` | Do a restore drill; back up R2; schedule verification |
| R9 | **Security hygiene.** Hard-coded Dropbox app key/secret defaults; a production-signed JWT in git history (rotation not evidenced); `ALLOW_LEGACY_NULL_STATUS=True`; 30-day sliding JWTs, no revocation, token accepted in query string; no MFA, lockout, security headers or password reset; Dropbox tokens in plaintext | High | Med | C | `:999-1000`, `:8680` | Rotate secrets; add headers; reduce token life; add reset/MFA |
| R10 | **A P0 cross-tenant hole (demo `?token=`), P1 cross-company writes and an XSS were found and fixed only on 2026-10-13.** The exposure window predates that | High | n/a | C (history) | commits #786-#789 | Determine whether any real cross-tenant access occurred (log review) |

### E.2 Medium

| ID | Risk | Sev | Lik | C/S | Evidence |
|---|---|---|---|---|---|
| R11 | **Dropbox R2 key collision** (wrong document served), no deletion propagation, unsigned webhook, no polling, plaintext tokens | Med–High | Med | C | `server.py:28603`; one-defect-list T2.1 |
| R12 | **AI cost has no ceiling and no meter** for gpt-4o, DM models and embeddings. Vision is counted, not capped. Only voice is capped (200 notes/company/day) | Med | Med | C | `lib/vision_meter.py` |
| R13 | **Hallucination exposure outside the verified paths.** The group agent (gpt-4o, temp 0.2, tools) is not quote-verified; any member of a linked group (including external subs) can address it and reach roster, SST and DOB tools, including the company-wide worker list | Med | Med | C | F1 §7 |
| R14 | **Offline defects.** Generic queue replays wrong verb or throws; `max_retries` items park forever, invisibly; photo demotion on 401/403; unsynced data lost on reinstall; token in plain storage; "Inspector mode" has no PIN; create-dedupe race with no unique index | Med | Med | C | C-notes §1-§8 |
| R15 | **Single-process monolith.** About 40 jobs, OCR worker, WhatsApp handling, Dropbox syncs and DOB scans share one event loop. 78.9k-line file; in-memory limiters/caches break with >1 replica; replica count is unknown (docs conflict) | Med | Med | S | platform §13 |
| R16 | **Test suite validates structure, not behavior.** About 60% of backend test files read source text; no real MongoDB; frontend 199/203 tests read source; no native E2E; no coverage metric; **no branch protection**; push to main auto-deploys backend and an OTA update to every store install | Med–High | Med | C | maturity §3 |
| R17 | **Privacy policy materially incomplete or wrong** (names Render; omits ~10 processors, voice, worker card photos, selfies). App-store data-safety exposure; worker ID photos go to a third-party VLM | Med | High | C | `privacy-policy.html` |
| R18 | **Missing-log detector history of false alarms** (285 false "missing" flags, since fixed); DEFCON inputs were contaminated by rodent-inspection data; no validity evidence for risk scores | Med | Med | C | `docs/audits/followups.md:4215` |
| R19 | **Real customer data committed to the repo** (sample PDFs, 24 production screenshots, fixtures, filed-sheet snapshots); seed and screenshot scripts target production with embedded credentials | Med | High | C | maturity §6 |
| R20 | **Report scheduling silent-miss** (hour==8 only), cached failed PDF, biweekly parity | Low–Med | Med | C/S | §C.6 |
| R21 | **NOTIFICATIONS_ENABLED defaults to false.** If unset in production, DOB/renewal emails don't send; prior incidents (80 duplicate renewal emails, 60 false "DOB NOW unreachable" alerts) were "fixed" by switching features off | Med | n/a | C | notifications.py |
| R22 | **Bus factor of one.** One operator plus AI agents; docs go stale within weeks | High (company-level) | n/a | C | git/maturity |

### E.3 Production incidents the repo records (self-reported)

2026-08-31 whole-API 500 (an `X-Client-Version` bug); a dependency-resolution outage about May; the 2026-09-11 → 09-15 four-day worker-registration outage (vision model env-var swap); an email flood; report #29 shipped without page 4; wrong permit-expiry counts in a daily email; a 6-month consent gap; the 2026-10-13 security fixes. These show real usage and an honest culture. They also show that failures typically came from environments no mock can see.

---

## F. Unit economics and scalability

### F.1 What the repo verifies about cost

| Cost driver | Figure in repo | Source | Notes |
|---|---|---|---|
| Qwen2.5-VL (DeepInfra) | $0.20 / 1M input, $0.60 / 1M output tokens | `server.py:19647` comment | Repo-stated, may be stale |
| One OSHA/SST card read | **≈ $0.000207** (870 prompt + 55 completion tokens) | same | |
| Card-read canary (every 15 min) | ≈ $0.60 / month | same | |
| Whisper | $0.006 / min | `lib/voice_ingest.py:94`; runbook (2026-Q1, "verify quarterly") | |
| gpt-4o-mini | $0.150 / 1M input, $0.600 / 1M output | same | |
| One 30-second voice note | ≈ $0.0031 | runbook | |
| Voice, 20 notes/day × 22 days | ≈ $1.37 per PM per month | runbook | Illustrative |
| gpt-4o, embeddings, Textract, Gemini | **Not stated anywhere** | — | |
| Atlas, Railway, R2, Resend, WaAPI, Sentry, Expo/EAS, domains | **Not stated** | — | **Unknown** |

**There is no per-tenant or per-month cost total anywhere in the product.** Only voice records per-note cost telemetry. Vision calls are counted per (day, project, endpoint) with no dollars. gpt-4o calls (group agent, memory answers, DM answers, report summaries, punch brain) have no meter at all.

### F.2 Recurring third-party stack (about 15 runtime services)

MongoDB Atlas · Railway · Cloudflare (Pages / R2) · AWS (S3 object-lock for cards, Textract for scanned plan pages) · Resend · Sentry · Dropbox · WaAPI · OpenAI · DeepInfra · Google Gemini · NYC Open Data / DOB BIS / DOB NOW (scraped) / 311 · OpenWeather · Google Places · Apple / Google Play / Expo EAS / GitHub Actions. **Dollar figures for all of these are unknown from the repo.**

### F.3 Variable-cost drivers (what scales with customers)

| Driver | Scales with | Risk |
|---|---|---|
| Plan indexing (≈4 vision calls/page + Textract) | Pages uploaded ("a forty-sheet set is forty calls") | Spiky; no cap |
| gpt-4o on every addressed group message and every DM turn (up to 4 rounds) | Chat volume | Uncapped; unmetered |
| Photos in R2 (original + enhanced + thumbnail, 3 renditions; Mongo inline thumbnail) | Photos per day | Storage growth, no lifecycle rule |
| Voice | Notes/day (capped at 200/company/day) | Bounded |
| Public gate OCR | Worker registrations (and abuse) | Unbounded |
| Report generation (gpt-4o + up to 40 vision calls per job) | Reports × jobs | No rate limit |
| Dropbox sync | Files × projects, with no delta sync | CPU/memory on the single process |
| WaAPI | One instance; per-instance subscription (price unknown) | Concentration |

### F.4 Calculations the analyst needs (formulas)

Define per tenant per month: `P` = active projects, `W` = new worker registrations, `C` = daily check-ins, `G` = addressed group messages, `D` = DM turns, `N` = voice notes, `Pg` = plan pages indexed, `R` = reports, `J` = jobs per report, `Ph` = photos stored, `S` = GB stored.

```
AI_cost  = W·c_card
         + N·(0.006·avg_min + c_translate)
         + (G + D·rounds)·c_gpt4o_turn
         + Pg·(c_vision_per_page·calls_per_page + c_textract)
         + R·J·(c_summary + k·c_vision_call)      # k ≤ 40, cached
         + (messages_indexed)·c_embed
Infra    = Railway_instance(s) + Atlas_tier + R2(S·$/GB-mo + ops) + Resend(emails)
         + WaAPI_instance + Sentry + fixed(apple, google, expo, domains)
Gross margin per tenant = ARPA − (AI_cost + share of Infra + support_hours·rate)
```

**Inputs to collect from production:** `vision_calls` by endpoint/day, OpenAI usage by key, R2 GB and Class A/B ops, Atlas tier and storage, Railway bill and replica count, WaAPI plan, Resend plan, support hours per onboarding (the operator currently does it by hand), and active projects/users per tenant.

### F.5 Scalability limits found in the code

- Single `uvicorn` process (no workers flag); the scheduler, WhatsApp handling, OCR worker and Dropbox syncs share a 1–2 vCPU instance (assumption in code comments).
- DOB sync processes **the first 500 projects** per tick (`.to_list(500)`). Brief and opt-in queries are capped at 5,000 rows. Several roster paths cap at 500–2,000 rows. Project-memory fallback search caps at 3,000 rows per project.
- DEFCON recomputes per project on every project-list call with no caching (suspected DB-heavy).
- About 165 index builds run in the serving process at every boot (cold-start cost).
- 31 `to_list(None)` calls; some sync boto3 calls un-threaded on the event loop (suspected).
- Per-process rate limiters and caches are correct only on one replica.
- No load tests exist.
- **Demonstrated scale:** tens of users per tenant, a handful of tenants. Nothing shows behavior at hundreds of tenants.

---

## G. Commercial assessment

*Everything in this section is judgement built on the evidence above. It is not market data and was not validated with customers.*

### G.1 Three strongest reasons a buyer would adopt

1. **A usable NYC compliance paper trail that does not require training the workforce.** The gate removes the paper sign-in sheet burden with a one-tap, bilingual, no-app flow. Signed, locked, amendable logs with a regulator-style PDF address a real inspection-day fear. The repo's strongest honest proof point is: *"every signed daily log, one tap to PDF"*, plus *"signed logs lock; corrections are amendments."*
2. **Trustworthy answers about "what was said and who was on site."** A quote-verified project memory over the WhatsApp groups subs already use, plus independently sourced headcount, is useful in disputes, back-charges and delay claims. The anti-hallucination design is a genuine differentiator.
3. **Early warning on stop-work orders and DOB events delivered where the team already looks.** SWO and violation alerts into the GC's WhatsApp group (baselined, ledger-once), a morning brief, and a punch workflow are low-friction. The product's own brief ranks "stop-work orders cost X per day" as its most honestly backed headline.

### G.2 Five strongest reasons a buyer might refuse

1. **No evidence it has been used by a second independent company.** Traction is one visible operator-adjacent site. A cautious GC will ask for references that don't exist yet.
2. **Dependence on an unofficial WhatsApp gateway** (one shared number). Any competent technology buyer will ask what happens if it's banned, and there is no fallback.
3. **Records may not carry the weight the buyer needs.** There is no DOB or counsel confirmation of acceptance, weak signer identity, consent enforced only in the client, and six of 13 log types never used in the field. If a log is challenged, the buyer bears the exposure (R5-R7).
4. **Security and tenant-isolation maturity.** Open cross-tenant read gaps, public PII/OCR endpoints, no MFA, and a P0 fixed only days ago. A GC handing over worker ID cards, signatures and DOB history will be asked for a security questionnaire the company cannot yet answer (R1-R3, R9, R10).
5. **Immature commercial plumbing and single-operator risk.** No billing, contract, ToS, self-serve onboarding, SLA, password reset or data export. Support is the founder. Vendor continuity and data retention after cancellation are unaddressed.

*Also relevant:* the progress report lacks the financial/schedule content a lender expects, and the privacy policy is out of date.

### G.3 Ideal customer profile (hypothesis)

A **mid-size NYC GC (roughly 3–15 concurrent jobs) with Major-Building (§3310) or Construction Superintendent (§3301.13.13) obligations**, a subcontractor-heavy workforce that is largely Spanish-speaking, and an owner who personally feels DOB exposure. It should already coordinate subs over WhatsApp. This matches what the product actually supports. Smaller GCs may not need 13 logs; larger GCs will already run an enterprise platform and demand SSO, security reviews and integrations that do not exist.

### G.4 Adoption barriers

- Operator-led onboarding (manual company creation, password handoff, no invite or reset).
- Field adoption depends on a CP filing daily and a super filing the 11-item log. Six log types have never been used.
- Native-only offline; the web build has none.
- Subs must be mapped to WhatsApp identities by an admin.
- English-only CP/admin screens (Spanish is worker-facing only).
- WhatsApp chat content processed by OpenAI and workers' card photos by DeepInfra: a data-processing conversation with every buyer.
- Documentation and privacy policy that do not match the product.

### G.5 Pricing hypotheses

There is **no pricing information, willingness-to-pay evidence or competitor price data** in the repo or this investigation. The following are structures to test, not predictions.

| Hypothesis | Mechanism | What must be true | How to test |
|---|---|---|---|
| **H-A: Per-active-project subscription** (primary) | Monthly fee per active job, with a company platform minimum | The unit of pain and compliance obligation is the job. AI cost scales with jobs | Quote 3–5 NYC GCs; compare to what they spend on the field admin/safety coordinator time the product displaces |
| **H-B: Compliance core + WhatsApp AI add-on** | Base = logs, gate, offline, reports. Add-on = memory, brief, punch, plan Q&A | Buyers value compliance first, and AI cost is uneven | Offer both bundles; observe attach |
| **H-C: Per-worker enrolled / per-seat** | Fee on workers or admin/PM seats | Cost correlates with gate volume and users | Less aligned with the value, so likely a poor fit |

*Cost floor.* Price must exceed per-project variable AI/infra cost (§F) plus onboarding labor. The repo gives neither. Since the founder performs onboarding by hand today, **onboarding labor is probably the dominant unit cost at this stage.**

*Significant annual contract value* would need at least these (analyst to validate with buyers):
- A defensible, counsel-reviewed compliance record.
- Security assurance (tenant isolation, MFA, DR drill, SOC-2-style evidence).
- Official WhatsApp transport.
- Owner/lender-facing deliverables with financial content.
- Demonstrated multi-site operation at a second independent customer.

Without these, the product is more credibly priced as a **low-to-mid-tier operational tool for a design-partner cohort** than as a six-figure enterprise contract. This is judgement, not market data.

### G.6 ROI framework (no savings are asserted)

For each GC, measure before and after on 2–3 live jobs:

```
Admin_time_saved = Σ_roles (minutes/day saved on sign-in sheets, daily log, toolbox/orientation paperwork,
                             report assembly, chasing subs) × working_days × loaded_hourly_rate
Exposure_reduced = (P(missed/incorrect required record) × expected_penalty_and_delay_cost) before − after
Dispute_value    = (disputes/yr × avg_cost_per_dispute × share_resolved_faster_with_evidence)
Delay_avoidance  = (SWO_days/yr avoided or shortened × daily_stop_work_cost)
Report_time      = (reports/month × hours_per_report) before − after
Net_ROI          = (Admin_time_saved + Dispute_value + Delay_avoidance + Report_time + Exposure_reduced)
                   − (subscription + onboarding + internal admin time to run the tool)
```

**Metrics needed:** minutes per day spent on sign-in, logs and reports (time-and-motion); logs filed on time vs required (the product's own `logbook_entries`); flagged check-ins resolved per week; number and cost of SWOs, violations and disputes in the prior 12 months; PM hours on subcontractor chasing; time to answer an inspector's request.

### G.7 Value by dimension

| Dimension | Strength today | Why |
|---|---|---|
| Mandatory compliance / inspection readiness | **Medium–High potential, unproven** | Right forms and process, no inspector validation, record-integrity caveats |
| Labor and admin time savings | **Medium** | Gate and reports are plausible; punch and chase are partly shadow |
| Documentation and dispute defense | **Medium–High potential** | Chat memory with quote verification and independent headcount are unusual |
| Field adoption / training | **High (for the worker gate)** | Zero-install, bilingual, one tap |
| Owner / lender progress reporting | **Low–Medium** | A field digest, not a lender package; no financials, no portal |
| Subcontractor accountability | **Low today** | Chasing is shadow; repair photos are not verified; punch send defaults to shadow |
| AI project memory and management intelligence | **Medium** | Best-engineered path, narrow audience, no measured accuracy |

---

## H. Critical unknowns

These cannot be answered from the repository. They need production access, customer interviews or field testing.

**Business and traction**
1. How many companies, projects and users are active today, and are they arm's-length from the operator? Is any customer paying?
2. Revenue, pricing, contracts, pilots, LOIs, churn, MAU/DAU (none in repo).
3. Are the iOS/Android apps publicly live? (Android config says internal track / draft.)
4. Monthly bills: Atlas, Railway, R2, OpenAI, DeepInfra, WaAPI, Resend, AWS.

**Reliability and operations**
5. Which commit is deployed? Which env values are set (`WAAPI_WEBHOOK_SECRET`, `NOTIFICATIONS_ENABLED`, `RETENTION_PURGE_ENABLED`, `QWEN_*`, `SOFT_DELETE_PURGE_ENABLED`, `PLATFORM_GATES_ENFORCED`)?
6. Replica count; Atlas tier and backup state; whether a restore has ever been drilled; whether R2 is public.
7. Which production flags are on (`v2_logbook`)? Do the unique indexes (open amendment, signature ledger, logbook dedupe) exist in prod?
8. Uptime and error rates; WhatsApp message volume; queue depths; drain success rates; photo loss rate.
9. Whether the exposed JWT secret in git history was rotated.

**Compliance and legal**
10. Has any DOB inspector ever been shown these records? Would DOB accept the format and signature method?
11. Counsel's view on the immediate vs end-of-day freeze model ("counsel-defined" in code; no document), the consent gap and the retention rule.
12. Have any ESRA consents been recorded since 2026-09-01?

**Product accuracy**
13. Real-world accuracy of project-memory answers, voice transcription (especially Yiddish), attention extraction, card OCR and plan Q&A beyond one building.
14. Whether the attention and chase engines would actually be correct enough to switch to live (no precision figures stored).
15. Whether any customer other than the operator's job uses punch in live mode.

**Integration reality**
16. Dropbox app status and granted scopes; whether the webhook is registered; number of customers connected.
17. WaAPI's terms, pricing and ban history; the chance Meta's official API fits the use case.

**Customer interviews**
18. Who actually decides, who uses it daily, and what they would pay. What an owner or lender would want in a progress report. Whether subs accept being addressed by a bot in the group chat.

---

## I. Final independent verdict

### I.1 What is genuinely impressive

- **Evidence-or-silence engineering.** The AI features that matter are built defensively: quote-verified memory with a refusal path, lexical fact-checking of LLM summaries and headcounts, a plan refusal gate, and deterministic fallbacks. The result is a *trust architecture*, rare in early-stage AI products.
- **A real compliance data model** for NYC site safety (13 types, locking, amendments, a declarative legal renderer, server-side stamping of signature receipt times) and unusual honesty about its limits.
- **The worker gate's adoption design:** zero install, bilingual, one tap, card read by vision with a typed fallback. This is the right wedge for a mostly Spanish-speaking subcontractor workforce.
- **Offline site-tablet depth,** including a fail-safe against rendering "0 workers" when a fetch fails.
- **Vertical specificity** (DOB/DOT/311 signals, Shabbos-aware sending) and an audit-driven engineering culture with self-critical documentation.

### I.2 What is mediocre

- Identity and presence assurance; the signature ledger's tamper evidence.
- Test strategy (volume over behavior; no real database; no device tests).
- Security and tenant-isolation hygiene, and documentation drift.
- The progress report as a lender or investor artifact.
- The statistical DEFCON risk score (large, hand-tuned, no validity evidence, with contaminated inputs acknowledged).

### I.3 What is incomplete

Billing, self-serve onboarding, password reset, MFA, owner/lender portal, financial or schedule content, live chasing, repair-photo verification, subcontractor COI tracking, Dropbox correctness, official WhatsApp transport, tenant-wide export, DR evidence, a second customer.

### I.4 What is commonly available elsewhere

Daily logs, digital sign-in and attendance, photo documentation, punch lists, document sync, scheduled reports, public-record alerts. The *combination* with NYC depth and a trustworthy AI layer is what is not.

### I.5 What would make it hard to replace

Once a GC has a year or more of signed, locked logs, worker enrollments and cards, chat memory and punch history in one tenant, switching means losing the dispute and inspection record. That data gravity is the potential moat. It exists only after adoption, which the repo shows for roughly one site. The WhatsApp memory also becomes hard to leave once it holds a job's history.

### I.6 Which description fits best

LeveLog is most defensible today as a **NYC compliance-records and workforce-gate system** (the wedge), with **WhatsApp project memory as the engagement and differentiation layer**. The "integrated construction operating system" framing is an aspiration, not a description: there is no money, schedule or owner side. As a pure "AI assistant" it is narrow (admin/PM audience, accuracy unmeasured, transport-fragile). As a "reporting platform" it is early and lacks lender content.

### I.7 What I would prioritize commercially over the next 90 days

1. **Prove it with 3–5 arm's-length NYC GCs** (paid pilots, not affiliates) on a defined wedge: gate + daily log + superintendent log + SWO alerts. Collect the ROI metrics in §G.6. This answers the biggest unknown.
2. **Close the diligence-blocking security items before onboarding anyone else:** the tenant-isolation gaps (R1), platform-flag write scope (R2), public OCR/PII endpoints (R3), secret rotation and token hardening (R9), a password-reset flow, and a security questionnaire answer pack.
3. **Get a counsel opinion and, ideally, DOB or an expediter's informal feedback** on the record format, signature method, consent and freeze model. Make the consent check server-side. Archive the signed PDF and hash at lock time. Stop soft-deleting filed records.
4. **De-risk WhatsApp:** document WaAPI terms, add per-tenant or official-API paths, add paging-quality alerts, and be explicit with customers about the dependency.
5. **Minimum commercial plumbing:** a ToS and privacy policy that match reality, invoicing (even manual), a self-serve or invite onboarding path, a tenant data export, and a drilled backup and restore (including R2).
6. **Narrow claims to what is evidenced.** Do not market "chasing," "AI-verified repairs," geofencing, "can't be backdated," lender-ready reports or predictive risk until the corresponding code and validation exist. Measure real accuracy for project memory and voice on live data.
7. **Reduce operational concentration:** branch protection and required checks, a staging path before OTA, a second maintainer who can read the code, and cost metering per tenant.

### I.8 Bottom line

The code shows a thoughtful, unusually self-aware builder who has produced a broad and in places deep product in a very short time. The strongest assets are the NYC-specific record model, the worker gate, and a disciplined AI evidence layer. The weakest points are the absence of independent customers, billing and onboarding, several confirmed security gaps, a fragile WhatsApp dependency, and legal-record assurances that stop short of what a litigation or inspection scenario would test. The product is credibly an **early-stage vertical wedge with a promising technical foundation**. Evidence of demand, security hardening and legal validation are what stand between it and a venture-scale compliance business.

---

## Appendix — Index of investigated domains and key source locations

| Domain | Primary files |
|---|---|
| Logbooks / signatures | `server.py:6021-6275` (registry), `:24507-25160` (ledger), `:30399-33900` (logbook CRUD, finalize, amend), `:6570-6760` (EOD sweep); `lib/legal_render/*`, `lib/logbook/*`, `lib/esra_consent.py`, `lib/project_retention.py` |
| Worker gate | `backend/checkin.html`; `server.py:18878`, `:19294`, `:20649`, `:21656`, `:23395`, `:23711`; `card_audit.py` (dead path) |
| Offline | `frontend/src/utils/{offlineQueue,logbookDrafts,draftSync,filedPhotoQueue,siteManifestStore,siteLogbookHistory,docCache,photoRecovery}.js`; `frontend/app/site/*`; `server.py:28204` (manifest) |
| Photos / Dropbox / plans | `server.py:30063`, `:32324`, `:27105-29646` (Dropbox), `:58000-62700` (plans); `lib/plan_*.py`, `lib/vision_*.py`, `lib/photo_enhance.py`; `backend/eval/*` |
| Reporting | `lib/progress_report.py`, `lib/project_report.py`, `lib/report/*`; `server.py:38924`, `:44907`, `:51108-51941` |
| WhatsApp core | `server.py:69496` (ingest), `:70572` (webhook), `:64247` (group agent), `:53130-53900` (memory); `lib/wa_*.py`, `lib/project_memory.py`, `lib/voice_*.py`, `lib/waapi_monitor.py` |
| Punch / attention / monitoring | `lib/punch*.py`, `lib/wa_attention*.py`, `lib/wa_chase.py`, `lib/wa_brief.py`, `lib/wa_gc.py`; `server.py:65461-69500`, `:47550-48960`, `:49496`; `lib/dot_sync.py`, `lib/dob_signal_*.py`; `lib/statistical_engine/*` |
| Platform / security / cost | `server.py:7283-9900` (auth, roles), `:10748-11300`, `:77547-78890` (scheduler); `lib/rate_limits.py`, `lib/scheduler_lease.py`, `lib/vision_meter.py`; `.github/workflows/*`; `docs/operations/*` |
| Self-reported production evidence | `docs/audits/one-defect-list-2026-09-13.md`, `six-from-the-operator-2026-09-14.md`, `render-migration-test-list-2026-09-13.md`, `docs/compliance/esra-consent-retrospective-exposure.md`, `docs/audits/followups.md`, `docs/marketing/homepage-source-of-truth.md` |

*Per-domain working notes (about 384 KB, with additional line-level references and test inventories) were produced during this investigation. They are stored in the session scratchpad, not in the repository, and can be supplied on request.*
