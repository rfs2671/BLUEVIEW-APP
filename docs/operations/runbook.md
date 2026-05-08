# LeveLog Operations Runbook

> Internal-only document. Not user-facing — for the LeveLog operator
> on call. Captures incident-response patterns from the MR.14 +
> Phase A/B development arc so future operators don't have to
> reverse-engineer the system.

**Last reviewed:** 2026-05-07 (Phase V2.0 — feature/v2-logbook)
**Test count baseline:** 1020 backend tests passing
(966 prior on develop + 54 new V2.0).
Production (`main`) is at 996 tests; the develop baseline excludes the
main-only C2.1/C2.2 hotfixes.

> **See also:**
> • [`backup-restore.md`](./backup-restore.md) — Atlas backup, restore drill, DR procedure, migration safety.
> • [`branching.md`](./branching.md) — main / develop / feature/* strategy, staging environment, Mongo refresh.
> • [`feature-flags.md`](./feature-flags.md) — runtime flag system, rollout patterns (canary / percentage / kill switch), audit log.
> • [`../features/v2-logbook.md`](../features/v2-logbook.md) — V2.0 compliance logbook (feature/v2-logbook branch, gated by `v2_logbook` flag). Operational notes below in §14.

> _(top-of-doc cross-links above were updated for Phase E1; the
> standalone backup-restore see-also that previously lived here
> is now in the consolidated list.)_

---

## Table of contents

1. [How to handle email-flood incidents](#1-how-to-handle-email-flood-incidents)
2. [How to investigate a customer issue](#2-how-to-investigate-a-customer-issue)
3. [How to add a new signal_kind](#3-how-to-add-a-new-signal_kind)
4. [How to debug DOB API failures](#4-how-to-debug-dob-api-failures)
5. [Production deploy](#5-production-deploy)
6. [Database migration](#6-database-migration)
7. [Audit script](#7-audit-script)
8. [Onboarding flow](#8-onboarding-flow)
9. [Sentry — how to read events](#9-sentry--how to read events)
10. [Sentry source maps](#10-sentry-source-maps)
11. [Rate limiting](#11-rate-limiting)
12. [WhatsApp voice note ingestion](#12-whatsapp-voice-note-ingestion)
13. [V2.0 — Compliance logbook (operational notes)](#13-v20--compliance-logbook-operational-notes)
14. [Environment variables reference](#14-environment-variables-reference)

---

## 1. How to handle email-flood incidents

**Symptom:** Customer reports a flood of emails, or our `notification_log`
collection shows >100 emails sent to one user in <1 hour.

**First action — kill the bleed.** Do not investigate yet.

### Step 1.1 — Activate the kill switch

The kill switch is environment-variable-driven. Setting it to `true`
on Railway suspends ALL outbound notifications globally — across every
user, every project, every signal kind, every channel.

```
Railway → backend service → Variables → NOTIFICATIONS_KILL_SWITCH=true
→ Save & redeploy
```

The kill switch is checked as Step 0 inside `send_notification`
(`backend/lib/notifications.py`) — it short-circuits before any
preference lookup, idempotency check, or Resend call. Records still
land in `notification_log` with `status="suppressed_kill_switch"` so
you have an audit trail of what would have been sent.

> **Why we have this:** during MR.14 we discovered the renewal
> notification path could enter a tight loop on certain BIS-legacy
> permits, sending the same email every 5 minutes. The kill switch
> was the rip-cord we needed to stop the bleeding while we
> investigated. If you find yourself wondering "should I activate
> it?" — yes, activate it. Better to have a 30-minute outage than
> 1000 angry customer emails.

### Step 1.2 — Investigate

```
> mongo $MONGO_URL/$DB_NAME
> use $DB_NAME
> db.notification_log.find({
    sent_at: { $gte: ISODate("2026-05-05T00:00:00Z") },
    status: "sent",
  }).count()
```

Cluster by `recipient_email` to find the affected user(s):

```
> db.notification_log.aggregate([
    { $match: { sent_at: { $gte: ISODate("2026-05-05T00:00:00Z") }, status: "sent" } },
    { $group: { _id: "$recipient_email", count: { $sum: 1 } } },
    { $sort: { count: -1 } },
    { $limit: 10 },
  ])
```

Cluster by `entity_id` to find the runaway record:

```
> db.notification_log.aggregate([
    { $match: { sent_at: { $gte: ISODate("2026-05-05T00:00:00Z") } } },
    { $group: { _id: "$entity_id", count: { $sum: 1 } } },
    { $sort: { count: -1 } },
    { $limit: 10 },
  ])
```

Common runaway patterns:
- **Idempotency hash collision** — two different records hashing to
  the same `idempotency_key`. Look at the records' raw payloads to
  confirm they're actually different.
- **Stale `dob_alert_sent` flag** — the 24h throttle in
  `_dob_alert_recently_sent` (server.py ~12346) keys on
  `(project_id, raw_dob_id)`. If `raw_dob_id` is regenerating each
  poll (e.g. timestamp-based), the throttle never matches.
- **Renewal loop** — a permit whose `renewal_strategy` resolves to a
  notify-eligible state on every sync. Inspect
  `db.permit_renewals.find({_id: ObjectId(...)})` for that permit.

### Step 1.3 — Fix the root cause

Don't just clear the symptom. The kill switch is a circuit breaker;
it's only safe to flip back ON after the underlying bug is patched
and tested. Patches should land with a test that pins the throttle
or idempotency invariant — see existing tests under
`backend/tests/test_notification_*.py` for the patterns.

### Step 1.4 — Re-enable

Once the fix is deployed and verified:

```
Railway → NOTIFICATIONS_KILL_SWITCH=false → Save & redeploy
```

The first 5 minutes after re-enable, watch `notification_log` for
the same recipient / entity_id pattern. If it recurs, kill the
switch again immediately.

---

## 2. How to investigate a customer issue

The customer reaches out with one of these vague reports:
- "I'm not seeing signals."
- "I'm getting too many emails."
- "Activity feed is empty."
- "My permit isn't showing as expiring."

### Step 2.1 — Identify the project

Get from the customer:
- Their email address (we'll resolve to user_id).
- The project name OR address.

```
> db.users.findOne({ email: "customer@example.com" })
{ _id: ObjectId("..."), company_id: "...", role: "admin", ... }

> db.projects.find({
    company_id: "<company_id>",
    is_deleted: { $ne: true },
  }).pretty()
```

Note the `nyc_bin`, `address`, `track_dob_status`,
`first_poll_completed_at`, and `created_at` fields.

### Step 2.2 — Common diagnostic queries

**"I'm not seeing signals."**
```
# Confirm dob_logs landed for this project at all.
> db.dob_logs.count_documents({ project_id: "<project_id>" })

# If 0:
#   - Is track_dob_status: true on the project? If false, polling is off.
#   - Is nyc_bin set or a placeholder? Run db.projects.findOne to inspect.
#   - Is address well-formed? Try fetch_nyc_bin_from_address on it.

# If >0 but customer says no:
#   - Are they checking the activity feed UI vs. the legacy /dob-logs detail?
#   - Are filters hiding their data? Check filters.signal_kinds, filters.severity_kind.
```

**"I'm getting too many emails."**
```
> db.notification_log.aggregate([
    { $match: { recipient_email: "customer@example.com", status: "sent" } },
    { $group: { _id: "$signal_kind", count: { $sum: 1 } } },
    { $sort: { count: -1 } },
  ])
```

Identify which signal_kinds are noisy. Recommend they switch to
"Critical only" preset, or use Advanced to silence those specific
kinds.

**"Activity feed is empty."**
```
# Confirm the 15-min poller has run for this project.
> db.system_config.findOne({ key: "initial_scan_done:dob:<project_id>" })

# If NULL: the poller hasn't completed yet. Wait a cycle or trigger
# manually via the admin sync endpoint.
```

### Step 2.3 — Cross-reference notification_log

For any "didn't get an email" / "got too many emails" issue, the
audit trail is in `db.notification_log`:

```
> db.notification_log.find({
    recipient_email: "customer@example.com",
    sent_at: { $gte: ISODate("2026-04-30T00:00:00Z") },
  }).sort({ sent_at: -1 }).limit(20).pretty()
```

Each row has:
- `status` — "sent" / "suppressed_kill_switch" / "suppressed_idempotent" / "suppressed_disabled" / "failed"
- `signal_kind` — what triggered the email
- `entity_id` — the record being notified about (dob_log id, permit_renewal id, etc.)
- `idempotency_key` — for tracing duplicates
- `metadata` — caller-supplied context

If `status="suppressed_idempotent"`, the customer DID NOT get an
email but it's because we already sent one for this entity_id within
the throttle window. Tell them to check inbox + spam from earlier.

### Step 2.4 — Don't promise fixes you can't deliver

Common issues that LOOK like LeveLog bugs but aren't:
- DOB's data is wrong / stale. We mirror DOB; we don't correct it.
- The customer's project address is in another borough or jurisdiction.
- The customer's email provider classified our mail as spam.
- DOB hasn't yet reflected a filing the customer says they made
  yesterday — DOB's own indexing lags 24-48 hours for some datasets.

If you're not sure, say "let me investigate further" rather than
"that's a bug." Get a customer's permission before pushing manual
fixes (e.g. force-syncing their project, re-running an audit).

---

## 3. How to add a new signal_kind

Adding a new signal_kind touches several files. Order matters — the
classifier and templates can land before the FE updates without
breakage; the FE updates can land after.

### Step 3.1 — Add the kind to the canonical list

In `backend/lib/notification_preferences.py`, add the new kind to
`ALL_DEFAULT_SIGNAL_KINDS`. This is the single source of truth.

In `frontend/src/utils/notificationPresets.js`, add the same kind to
`ALL_KINDS`. The two lists must match — there's a comment in
`notificationPresets.js` calling out the friction.

### Step 3.2 — Update the classifier

In `backend/lib/dob_signal_classifier.py`, add the rule that maps
incoming DOB record fields to your new kind. Look at how nearby
kinds (e.g. `permit_revoked`, `complaint_311`) are classified for
the pattern.

Add a unit test in `backend/tests/test_dob_signal_classifier.py`
asserting your rule produces the new kind for the matching input
shape.

### Step 3.3 — Update the templates

In `backend/lib/dob_signal_templates.py`, add the title / body /
action_text templates for the new kind. Minimum: a `default`
template per severity (info / warning / critical).

Add a test in `backend/tests/test_dob_signal_templates.py` asserting
the template renders for the new kind across severities.

### Step 3.4 — Add the help copy

In `frontend/src/utils/signalKindHelp.js`, add a one-sentence
plain-English explanation of the new kind. The
`test_b3_frontend_invariants.TestSignalKindHelpCoverage` test pins
this — it'll fail until you add the entry, which is the right
friction.

### Step 3.5 — Add to a filter group

In `frontend/src/components/ActivityFeed.jsx`, add the new kind to
the appropriate `SIGNAL_KIND_GROUPS` entry. If it's a brand-new
category, add a new group label and add it to the family taxonomy
test in `test_b01_activity_feed_design_pins.py`.

### Step 3.6 — Update presets

In `frontend/src/utils/notificationPresets.js`, decide whether the
new kind belongs in `CRITICAL_EMAIL_KINDS` (the 6 always-immediate
emails), `STANDARD_DIGEST_KINDS` (the 4 daily-digest warnings), or
neither (feed-only by default). Match the corresponding backend
defaults in `notification_preferences.py`.

### Step 3.7 — Run the suite

```
> cd backend && python -m pytest tests/ -q
```

A green run means classifier + templates + presets + help copy are
all in lockstep. Push the change.

---

## 4. How to debug DOB API failures

DOB's public datasets (NYC Open Data Socrata + 311 Service Requests
+ BIS) have varying reliability. Failures we've seen and what to do:

### 4.1 — 400 / 429 errors

```
> tail -100 /var/log/levelog/server.log | grep "DOB API"
```

Look for:
- **400 Bad Request** — usually a malformed query. Check if
  `_query_dob_apis` (server.py ~11732) is sending an invalid
  `$where` or address-LIKE clause. Most common cause: an address
  with single quotes that didn't escape.
- **429 Too Many Requests** — Socrata rate limit. We don't yet
  back off automatically; the next 15-min cycle generally clears.
  If sustained, check whether the `nightly_dob_scan` interval
  collided with a manual sync triggered by an admin — running both
  in parallel doubles the request rate.

### 4.2 — DOB endpoints slow / timing out

`_query_dob_apis` runs four endpoint queries in parallel via
`asyncio.gather`. If one hangs:
- **httpx default timeout** is 30s. Hangs longer than that surface
  as `httpx.ReadTimeout`. We catch and continue with partial
  results.
- **Socrata maintenance windows** are typically Sunday 02:00 ET.
  Check status.cityofnewyork.us if you suspect outage.

### 4.3 — Records pulled but signal_kind = "(none)"

The classifier didn't find a matching rule. The record still lands
in `dob_logs` with `signal_kind: null` so it shows in the feed but
doesn't trigger preset-based notifications. This is by design — we
fail gracefully on unknown record shapes rather than dropping data.

To investigate: `db.dob_logs.findOne({ signal_kind: null })` and
inspect the raw record's `record_type` and other fields. If it's
a recurring shape we should classify, follow the "How to add a new
signal_kind" runbook above.

### 4.4 — BIN auto-heal didn't backfill

The auto-heal logic in `run_dob_sync_for_project` (server.py
~13617) requires DOB to return at least one record with a real BIN
in the `bin` field for an address-based query. If DOB returns
records but none have a BIN, the heal can't run. Manual fix:
operator enters the BIN in the project's DOB Compliance settings.

---

## 5. Production deploy

We deploy the backend to Railway (Docker) and the frontend to
Cloudflare Pages (Vercel for staging). Pushing to `main` triggers
both.

### Step 5.1 — Pre-deploy verification

```
> cd backend && python -m pytest tests/ -q
```

The test suite must pass byte-for-byte against the prior baseline.
Current baseline as of Phase B4: **734 passed**. Note the count in
your commit body so the next deploy can spot regressions.

```
> cd frontend && for f in $(git diff --name-only HEAD~1 HEAD | grep '\.jsx$'); do
    npx esbuild "$f" --loader:.jsx=jsx --target=es2020 --bundle=false > /dev/null
  done
```

esbuild is a syntax-check, not a type-check — but it catches the
cheap regressions (JSX typos, unclosed tags, bad imports).

### Step 5.2 — Push

```
> git push origin main
```

Railway picks up the push and starts a new deployment. Watch the
deploy logs for any startup error in `_verify_resend_domain_at_startup`
or the index-creation block.

### Step 5.3 — Post-deploy smoke

After Railway reports green:
- Hit `https://api.levelog.com/api/health` — should return `{"status": "ok"}`.
- Log in to www.levelog.com with a test account. Confirm dashboard
  loads, activity feed loads, settings page loads.
- Check `notification_log` for any entries with
  `status="failed"` in the last 5 minutes — startup hiccups
  sometimes blip here.

### Step 5.4 — Rollback

If a deploy goes sideways:

```
Railway → Deployments → click prior green deployment → "Redeploy"
```

This redeploys the last-known-good Docker image. Frontend rollback
is via Cloudflare Pages "previous deployment" button.

DO NOT roll back via `git revert` and re-push if a fix is in
flight — Railway will deploy the revert AND the fix in sequence
and you'll get a brief window where the fix is live, then the
revert overwrites it.

---

## 6. Database migration

We do NOT run schema migrations as a separate phase. Mongo is
schemaless; document shape changes are additive. Where we DO need
discipline:

### 6.1 — Adding indexes

Use `_ensure_index_resilient` (server.py ~336) inside a startup
handler. The helper retries on conflict and logs cleanly.

Pattern:
```python
@app.on_event("startup")
async def _ensure_b4_indexes():
    await _ensure_index_resilient(
        db.your_collection,
        keys=[("user_id", 1), ("project_id", 1)],
        name="user_id_project_id",
        unique=True,
    )
```

DO NOT use `db.your_collection.create_index` directly — it crashes
the app on first conflict.

### 6.2 — Backfilling fields

For new fields with sensible defaults, prefer reading-time fallback
over a backfill. Example from B3:
```python
# In GET /api/users/me/onboarding-status:
step = user_doc.get("onboarding_step")
if step is None:  # pre-B3 user
    return {"show_onboarding": False, ...}
```

Only run a backfill script when read-time fallback isn't tractable.
Place backfill scripts under `backend/scripts/` with a `--dry-run`
flag that defaults to True. Pattern:
- Run with `--dry-run` first; print what would change.
- Inspect the dry-run output for unexpected matches.
- Re-run with `--execute` only after manual approval.

### 6.3 — Pre-migration snapshot (Phase C3 hard rule)

Before running ANY `backend/scripts/migrate_*.py` against
production, take an on-demand Atlas snapshot. The full
checklist + rollback procedure lives in
[`backup-restore.md`](./backup-restore.md) §5; the short version:

1. Atlas → production cluster → Backup → **Take Snapshot Now**.
   Name it after the migration: `pre-mr14-foo-YYYY-MM-DD`.
2. Wait for the snapshot row to turn green.
3. Run with `--dry-run` first; inspect the change set.
4. Run with `--execute`; capture stdout to a log.
5. Run `audit_production.py` post-migration to verify counts.

If the migration corrupts data, restore from the snapshot you
took in step 1 — see `backup-restore.md` §4.

### 6.4 — Soft-delete vs hard-delete

We default to soft-delete (`is_deleted: true` flag). Hard-delete is
reserved for:
- GDPR / customer-deletion requests.
- Test data cleanup.
- Demonstrably one-off junk records (e.g. a 10x-duplicated row from
  an aborted import).

Every hard-delete needs a 1-line audit-log entry written via
`audit_log()` so we can trace who deleted what.

---

## 7. Audit script

`backend/scripts/audit_production.py` runs a read-only health check
across the whole production database. Recommend running it monthly,
or after any incident, or before any major release.

### 7.1 — How to run

```
> cd backend
> MONGO_URL=<prod-uri> DB_NAME=<prod-db> python scripts/audit_production.py > audit-$(date +%Y-%m-%d).md
```

Output is markdown. Review section by section.

### 7.2 — How to read the output

The script emits 8 sections. Most useful:
- **Section 1 (Companies)** — count, GC license coverage, insurance
  coverage. False positives are companies created via legacy paths
  before insurance fields existed.
- **Section 4 (Projects)** — project count, BIN resolution rate,
  track_dob_status distribution. False positives are projects with
  intentionally-empty BIN (placeholder demos).
- **Section 5 (DOB logs)** — total count, signal_kind=null rate.
  A rising null rate is a signal that DOB introduced a new record
  shape we should classify.
- **Section 7 (Filing-rep credentials canary)** — MUST be 0.
  Anything >0 is a critical incident — the script aborts with
  exit code 1 in that case. We must never store filing-rep
  credentials.

### 7.3 — Common false positives

- Older test accounts on the prod database surface as "orphan
  users". Filter by created_at >= MR.10 launch date to ignore.
- Companies with no projects are not a bug — onboarded users who
  skipped step 2.
- Deleted projects (is_deleted: true) still show in dob_logs counts.
  That's by design — we keep historical signals queryable.

---

## 8. Onboarding flow

### 8.1 — What state to expect from a new GC

After signup + completing the onboarding flow, you should see:

```
db.users.findOne({ email: "newgc@example.com" })
  • role: "admin"
  • company_id: <set>
  • company_name: <set>
  • onboarding_step: "completed"
  • onboarding_completed_at: <recent datetime>

db.companies.findOne({ _id: ObjectId(<company_id>) })
  • name: <user's company name>
  • gc_license_number: <user-supplied>
  • office_address: <user-supplied>
  • filing_reps: [<one or more reps if they filled step 3>]

db.projects.find({ company_id: <company_id> })
  • At least 1 project, with track_dob_status: true.

db.notification_preferences.findOne({ user_id: <user_id>, project_id: null })
  • If user picked Standard or Everything: doc exists with
    those overrides + routes.
  • If user kept Critical only: NO doc exists — synthesized
    backend defaults match Critical only exactly, so we don't
    bother writing.
```

### 8.2 — How to debug "onboarding doesn't appear"

Symptom: a new user logs in but the RouteGuard never redirects to
/onboarding.

Check, in order:
1. **Is `onboarding_step` set on the user doc?** Pre-B3 users
   (created before Phase B3 shipped) don't have the field. The GET
   status endpoint synthesizes `show_onboarding=False` for them.
   This is by design — the production user base shouldn't suddenly
   see the flow.
2. **Did they sign up via /api/auth/register?** Users created via
   admin tooling (`/api/owner/admins`, etc.) don't get the step
   stamped. This is a known gap; add `onboarding_step="1"` to those
   paths if you want them onboarded too.
3. **Is the user's role one we don't redirect?** RouteGuard
   excludes site_device and CP roles from the onboarding gate —
   their existing role guards win. If the user's role is `cp`,
   they'll never see /onboarding regardless of state.

### 8.3 — Manual completion if needed

If onboarding is broken for one user but you've already created
their company and project elsewhere, mark them complete manually:

```
db.users.update_one(
  { email: "stuck@example.com" },
  { $set: {
      onboarding_step: "completed",
      onboarding_completed_at: new Date(),
      updated_at: new Date(),
  } },
)
```

Don't do this in bulk without confirming each user has a company
and at least one project — a "completed" user with no company will
land on a broken dashboard with no projects, which is a worse UX
than the onboarding flow itself.

### 8.4 — Resetting a user's onboarding (rare)

If you need to put a user back through the flow (e.g. a test
account, or a customer who explicitly asked):

```
db.users.update_one(
  { email: "test@example.com" },
  { $set: { onboarding_step: "1", onboarding_completed_at: null } },
)
```

Their next login will redirect to /onboarding. Note: this does NOT
delete their existing company, projects, or preferences. The flow
will detect existing artifacts and redirect to the dashboard mid-
flow (Step 1 sees company_id is set → 409s the company-create
endpoint, which is what the FE expects).

---

## 9. Sentry — how to read events

Phase C1 wired Sentry into the backend (FastAPI) and the frontend
(React via @sentry/react). When a real production bug occurs, an
event lands in the Sentry dashboard within seconds — with stack
trace, request context, and the `user_id` / `company_id` /
`environment` tags attached.

### 9.1 — DSN setup

Create a Sentry project at https://sentry.io (the free tier is
sufficient for v1 — 5k events/month, 30-day retention). One
project per service is the convention; pick names like
`levelog-backend` and `levelog-frontend`.

Copy the DSN from each project's Settings → Client Keys:

```
Backend  → SENTRY_DSN              → Railway → Variables
Frontend → EXPO_PUBLIC_SENTRY_DSN  → Cloudflare Pages → Environment Variables
```

Both env vars are read at app startup. **Missing DSN is graceful:**
the app starts, just without error tracking. We log a one-line
info message at startup so it's visible in Railway / Cloudflare
deploy logs.

### 9.2 — Environment scoping

Events are tagged with `environment` so a deploy to staging
doesn't pollute production's issue list:

- Backend reads `RAILWAY_ENVIRONMENT` (Railway sets this
  automatically per environment), falling back to
  `SENTRY_ENVIRONMENT`, then `"development"`.
- Frontend reads `EXPO_PUBLIC_ENVIRONMENT` (set explicitly per
  Cloudflare Pages build), falling back to `NEXT_PUBLIC_ENVIRONMENT`,
  then `NODE_ENV`, then `"development"`.

Filter the Sentry issue list by `environment:production` to ignore
local-dev noise.

### 9.3 — Common error patterns to expect

The patterns we've seen during MR.14 + Phase A/B development —
useful as a reading guide for the first few weeks of production:

- **Mongo connection blips** (`pymongo.errors.AutoReconnect` /
  `ServerSelectionTimeoutError`). Almost always a Railway → Atlas
  network burp; resolves on retry. If sustained, check Atlas
  status page.
- **`HTTPException` 401 / 403** — these get filtered out by the
  bot/404 hook; they shouldn't appear in Sentry. If they do,
  something's wrong with the filter.
- **`KeyError` / `AttributeError` inside DOB sync** — usually a
  new DOB record shape we haven't classified. Fix per Section 3
  ("How to add a new signal_kind").
- **`httpx.ReadTimeout` / `httpx.ConnectTimeout`** — DOB API or
  GeoSearch slow. Acceptable at low volume; alarming if sustained.
- **Frontend `TypeError: Cannot read property … of undefined`** —
  almost always an API response shape change that leaked through.
  Check the matching backend endpoint diff.
- **Frontend `Network Error`** — the @sentry/react beforeSend hook
  drops these because they're usually misconfigured CORS preflights
  or browser-blocked fetches. If you're missing real network
  bugs, widen the filter.

### 9.4 — Alert rules to configure

In Sentry → Alerts → Issue Alerts:

1. **Notify on first occurrence of any new issue** — paged via
   email (or Slack if you wire the integration). Catches new
   bugs the moment they reach a single user.
2. **Notify on issue reaching 10+ occurrences/hour** — triggers
   when one bug starts hitting many users. Distinguishes "weird
   one-off" from "all users see it." Prefer Slack here so it
   doesn't drown your inbox.

For both rules set the project filter to `environment:production`
so staging deploys don't page you. Severity-based routing (only
page on `level:error` and above) is also worth setting up once
you have a few months of baseline data — it lets warnings flow
to a low-priority channel.

### 9.5 — Verifying integration after deploy

Backend smoke:

```
> curl -H "Authorization: Bearer <your-admin-token>" \
       https://api.levelog.com/api/admin/_sentry_test
```

Returns a 500 with body
`"Phase C1 Sentry health-check exception (intentional)…"` and
captures one event in the backend's Sentry project. The exception
message is fixed so re-runs deduplicate to a single Sentry issue
rather than spamming new ones.

Frontend smoke: open DevTools on www.levelog.com, paste:

```js
throw new Error("Sentry frontend integration smoke test")
```

The throw lands in the global `error` listener (or, if it bubbles
through React, in the ErrorBoundary's `componentDidCatch`).
Either way the event appears in the frontend Sentry project
within 5 seconds.

### 9.6 — PII scrubbing — what's redacted

Backend (server.py `_sentry_before_send`):

- Request bodies are redacted for paths matching:
  - `/api/auth/*` (login + register payloads carry plain-text
    passwords).
  - `/api/users/me/notification-preferences*` (defensive — these
    docs may carry future PII fields).
- Authorization, Cookie, Set-Cookie, X-API-Key headers are
  always stripped, regardless of path.
- Query strings are redacted on sensitive paths (defensive against
  reset-token-in-URL leaks).
- 404s and known-bot user-agents (Googlebot, Ahrefs, headless
  Chrome, etc.) are dropped entirely — they're not bugs and
  burning the free-tier quota on them is a waste.

Frontend (`src/lib/sentry.js`):

- `sendDefaultPii: false` keeps Sentry from auto-attaching IP
  addresses or cookies.
- `setSentryUser` pushes `email` + `company_name` + `role` after
  login. Email IS PII; we tag it because it's the unique-id
  ops actually use to find a user. Cleared on logout.
- "Network Error" and "Failed to fetch" exceptions are dropped
  in beforeSend because they're almost always browser-side
  noise (CORS preflights, ad blockers).

### 9.7 — When to capture explicitly

Most exceptions auto-capture via the FastAPI / starlette
integrations on the backend and the React ErrorBoundary on the
frontend. For the rare case where you want to log a non-throwing
event (e.g. "user hit an unexpected edge case but we recovered
gracefully"):

```python
# Backend
import sentry_sdk
sentry_sdk.capture_message("Unexpected edge case in frob_widget", level="warning")
```

```js
// Frontend
import { captureException } from '../src/lib/sentry';
captureException(new Error("Manual capture"), { someContext: "value" });
```

Don't overuse — every captured event counts toward the free-tier
quota. If you're tempted to capture a recoverable warning, ask
yourself: would I want to be paged about this at 3am? If no, log
it and move on.

---

## 10. Sentry source maps

Phase C1.2 wired source-map upload to Sentry so production stack
traces resolve to readable `file:line:column` references instead
of the minified `t.j(z, 17)` gibberish. Without source maps a
React error #310 (or any production crash) is essentially
undebuggable from Sentry alone — you'd need to reproduce locally,
which for hook-order bugs is often impossible.

### 10.1 — How it works

`frontend/scripts/build-with-sourcemaps.js` is a Node wrapper
around `expo export` that runs at every Vercel build:

1. Copies `VERCEL_GIT_COMMIT_SHA` → `EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA`
   so the runtime bundle's `Sentry.init({ release: ... })`
   matches the release we upload maps under. The two MUST agree —
   Sentry can't surface source maps for an event whose `release`
   tag doesn't match an uploaded release.
2. Runs `expo export --platform web --clear --source-maps`. The
   `--source-maps` flag is **load-bearing**: Expo's CLI does NOT
   emit source maps by default, and without them the upload step
   below has nothing to ship. C1.2 shipped without this flag and
   the upload reached Sentry with zero artifacts (the Vercel build
   log said `removed 0 .map file(s)` and Sentry events still came
   back minified). The flag has been part of `@expo/cli`'s export
   command since SDK 50 — legacy alias `--dump-sourcemap`,
   shorthand `-s`.
3. If `SENTRY_AUTH_TOKEN` is set:
     `npx @sentry/cli sourcemaps inject ./dist`
     `npx @sentry/cli sourcemaps upload --org levelog \
        --project levelog-frontend --release "$VERCEL_GIT_COMMIT_SHA" ./dist`
4. **Always** deletes every `*.map` file under `./dist`, regardless
   of whether the upload ran. Source maps must NEVER be served
   from `www.levelog.com` — they reveal pre-mangled identifiers
   and (depending on bundler config) embedded source. The `dist/`
   tree that Cloudflare Pages serves contains zero `.map` files
   after the build.

Forks / preview deploys without `SENTRY_AUTH_TOKEN` build cleanly
but skip the upload step. Step 4 still runs, so no `.map` files
leak even when the upload was skipped.

### 10.2 — How to get a Sentry auth token

1. Visit `https://levelog.sentry.io/settings/account/api/auth-tokens/`.
2. Click "Create New Token".
3. Name: `vercel-source-maps`.
4. Scopes — minimum needed:
   - `project:releases` (create + finalize releases, upload artifacts)
   - `project:read` (look up the project slug)
5. Copy the token. It's shown ONCE; if you lose it, revoke and
   create a new one.

### 10.3 — How to set it on Vercel

1. Vercel dashboard → `levelog` (frontend project) → Settings →
   Environment Variables.
2. Add:
     Name:        `SENTRY_AUTH_TOKEN`
     Value:       (paste the token from step 10.2)
     Environments: **Production only** — preview deploys don't
                   need to upload, and exposing the token to
                   preview env increases the blast radius if a
                   bad PR gets the token.
3. Save. The next push to `main` picks it up.

### 10.4 — How to verify upload worked

1. Push a commit to `main`. Vercel auto-deploys.
2. Open Vercel → Deployments → click the live deploy → Build Logs.
3. Search for `[c1.2-build]` lines. You should see:
     `[c1.2-build] release tag: <sha>`
     `[c1.2-build] uploading source maps to Sentry for release <sha>`
     `[c1.2-build] Uploaded source maps for release <sha>`
     `[c1.2-build] removed N .map file(s) from .../dist`
   If you see "SENTRY_AUTH_TOKEN not set — skipping" instead, the
   token isn't set on Vercel. Re-do step 10.3.
4. Visit `https://levelog.sentry.io/releases/`. The new release
   should appear at the top with the same SHA.
5. Click into the release. The "Source Maps" tab should show one
   row per JS chunk (typically 5-15 entries depending on bundle
   splitting).

### 10.5 — How to test end-to-end

1. Open `www.levelog.com` in DevTools.
2. Console:
     `throw new Error("Sentry source-map smoke test")`
3. Open the corresponding event in Sentry (filter by your user
   email tag).
4. Stack trace should show:
     `at MyComponent (frontend/app/some/file.jsx:42:10)`
   instead of:
     `at t.j (chunk-abc.js:1:1234)`
5. If you see the latter, source maps didn't apply. Check:
   - Build log shows "Uploaded source maps" (step 10.4).
   - The event's `release` tag matches an uploaded release.
   - The `release` tag is NOT `"development"` (= the
     `EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA` env var didn't propagate
     to the runtime bundle).

### 10.6 — Common failure modes

- **Build log says `removed 0 .map file(s)` AND
  `could not determine a source map reference`** — the Expo
  export ran without the `--source-maps` flag, so the dist/
  tree never contained any maps to upload. The `sentry-cli
  sourcemaps upload` step succeeds but ships nothing. Fix:
  ensure `frontend/scripts/build-with-sourcemaps.js` passes
  `--source-maps` to `expo export`. C1.2.1 (commit 92ad71a's
  follow-up) added this; a regression would re-trip the same
  trap.
- **"release not found" warning in Sentry event** — the runtime
  `release` doesn't match any uploaded release. Almost always
  because `VERCEL_GIT_COMMIT_SHA` wasn't set during build.
- **Sentry events still show minified stacks even after upload** —
  the `release` value at `Sentry.init()` time and the `--release`
  flag at upload time don't match. The build script enforces this
  (both read from the same env var) but if you customize either,
  re-verify they agree.
- **`Authorization Required (401)` in build log** — token is wrong
  or expired. Re-create per 10.2.
- **Build fails with `command not found: @sentry/cli`** — devDep
  not installed. Make sure `npm install` ran and `frontend/node_modules/@sentry/cli/`
  exists. On Vercel this happens automatically; locally run
  `npm install` in `frontend/`.

---

## 11. Rate limiting

Phase C2 introduced a single-process, in-memory rate-limit
middleware in `backend/lib/rate_limits.py`. Pre-launch hardening
to keep brute-force, signup spam, and accidental-loop clients
from chewing through the public surface. `slowapi` and `limits`
are pinned in `requirements.txt` for the eventual swap to a
Redis-backed limiter; the current middleware is custom because
slowapi's decorator-per-endpoint model would touch ~40 routes
and create N points of regression risk. One config table, one
matcher, one identifier resolver — easier to audit.

### 11.1 — Per-endpoint limits

Pin all changes in `lib/rate_limits.RATE_LIMITS`. The table is
match-in-order — declare more-specific patterns above catch-alls.

| Method  | Path | Limit | Identifier |
|---|---|---|---|
| POST    | `/api/auth/login` | 5 / 5 minutes | IP |
| POST    | `/api/auth/register` | 3 / 1 hour | IP |
| POST    | `/api/auth/forgot-password` | 3 / 1 hour | IP |
| POST    | `/api/auth/reset-password` | 5 / 1 hour | IP |
| POST    | `/api/onboarding/company` | 30 / 5 minutes | user |
| POST    | `/api/onboarding/project` | 30 / 5 minutes | user |
| POST    | `/api/onboarding/filing-reps` | 30 / 5 minutes | user |
| PATCH   | `/api/users/me/onboarding-step` | 30 / 5 minutes | user |
| GET     | `/api/users/me/notification-preferences` | 60 / 1 minute | user |
| PATCH/PUT | `/api/users/me/notification-preferences` | 30 / 5 minutes | user |
| POST    | `/api/users/me/notification-preferences/preview` | 60 / 1 minute | user |
| GET     | `/api/projects/{id}/notification-preferences/{user_id}` | 60 / 1 minute | user |
| PATCH/PUT | `/api/projects/{id}/notification-preferences/{user_id}` | 30 / 5 minutes | user |
| DELETE  | `/api/projects/{id}/notification-preferences/{user_id}` | 10 / 5 minutes | user |
| POST    | `/api/projects` | 10 / 5 minutes | user |
| PUT/PATCH | `/api/projects/{id}` | 30 / 5 minutes | user |
| DELETE  | `/api/projects/{id}` | 10 / 5 minutes | user |
| GET     | `/api/admin/_sentry_test` | 5 / 5 minutes | IP |
| ANY     | `/api/admin/*` (catch-all) | 60 / 1 minute | IP |
| ANY     | other `/api/*` (default) | 100 / 1 minute | user |

Identifier semantics:

- **user** — JWT `sub` claim. If the request has no Bearer
  token, an expired token, or a malformed token, the limiter
  DOWNGRADES to IP — an unauthenticated caller hitting a
  user-scoped endpoint is still rate limited, just by the
  weaker IP key.
- **IP** — `X-Forwarded-For` leftmost entry (Vercel /
  Cloudflare set this to the real client IP) → fallback to
  `request.client.host`.

### 11.2 — When to add a new endpoint

1. Pick a limit that's tight enough to block abuse but loose
   enough that the legitimate FE never hits it. Read endpoints
   often want 60/min; mutating endpoints often want 10-30 /
   5 minutes.
2. Pick the identifier kind. Public/unauthenticated endpoints
   = IP. Authenticated endpoints = user. (Multi-user GCs share
   a `company_id` but each user has their own counter — that's
   intentional. Per-tenant rate limiting is v1.1 work.)
3. Add a row to `RATE_LIMITS` in `lib/rate_limits.py`. Keep
   most-specific patterns above catch-alls.
4. Add a `TestConfigTable` assertion to
   `tests/test_c2_rate_limits.py` so the limit + kind are
   pinned. A future "tidy the table" patch can't drop the row.

### 11.3 — How to read Sentry warnings for rate-limit hits

Every blocked request fires `sentry_sdk.capture_message(...,
level="warning")` with a body like:

```
rate_limit_exceeded route=/api/auth/login kind=ip
```

Sentry's own dedup folds repeats under one issue with a count.
Filter by `level:warning` + the literal string
`rate_limit_exceeded` in the issue title.

What to do when you see a spike:
- **Sustained spike on `/api/auth/login`** — likely a
  credential-stuffing attempt. Verify via `notification_log`
  (failed login attempts may correlate). Don't disable the
  limiter; let it do its job. If the source IP is targeting
  a known-good user, escalate to the user's owner.
- **Spike on `/api/onboarding/*`** — usually a bug in the FE
  that's hitting a step submit in a loop. Reproduce locally;
  fix the FE; don't widen the limit.
- **Spike on `/api/users/me/notification-preferences`** — same
  story; FE polling bug.
- **Spike on the `/api/admin/{rest:path}` catch-all** — only
  admin tooling reaches these endpoints; usually means an
  internal script forgot to throttle. Identify the caller via
  the X-Forwarded-For tag in the Sentry event and ping them.

### 11.4 — Bypass for emergencies

If the limiter itself has a bug (false positives blocking a
real customer, or a config mistake locking out the operator
trying to debug), set on Railway:

```
Railway → backend service → Variables → RATE_LIMITS_DISABLED=true
→ Save & redeploy
```

The middleware reads the env var at every request, so the
flip takes effect immediately on the next request after the
new deploy boots.

**Hard rule:** unset within 4 hours. The kill switch is for
incident response, not for indefinite operation. Production
must run with limits ON.

### 11.5 — Single-instance limitation (v1)

This middleware uses an in-process dict-of-counters. When we
scale Railway horizontally to N instances, each instance gets
its own counter and the effective cap becomes N×limit. v1
ships single-instance so this is currently safe. v1.1 should
swap to a Redis-backed limiter (slowapi's MovingWindowRateLimiter
+ RedisStorage; both already in `requirements.txt`).

---

## 12. WhatsApp voice note ingestion

Phase F1 wired voice notes into the same WhatsApp agent that
already processed text. A voice note webhook arrives → audio
bytes are fetched once via WaAPI's `download-media` endpoint →
Whisper transcribes (capturing `no_speech_prob` so we can detect
silence/background noise) → GPT-4o-mini translates to English →
the existing extraction layer runs as if the input were text.
Audio is **never** persisted: no R2, no disk, no logging of the
bytes. The bytes are released as soon as Whisper returns.

### 12.1 — Pipeline at a glance

```
WaAPI inbound webhook (message.type ∈ {"ptt","audio"})
    │
    ▼
download_audio (server.py)            ← WaAPI POST + decrypt if needed
    │  ogg/opus bytes
    ▼
process_voice_note (lib/voice_ingest.py)
    │  ┌── Whisper verbose_json
    │  │     captures: transcript, language, duration_sec, no_speech_prob
    │  ├── short-circuit if  len(transcript) < 5  OR  no_speech_prob > 0.6
    │  │     → reply "I didn't catch that — can you resend?"  + skip extraction
    │  └── translate_to_english (GPT-4o-mini)
    │        falls back to original transcript on API failure
    ▼
extraction layer (existing, unchanged)
    ▼
agent reply  +  "\n\nReply CORRECT to confirm or describe what's wrong."
```

### 12.2 — Idempotency

WaAPI may re-deliver a webhook (network blip, partial 5xx, etc.).
The server.py call site checks the `whatsapp_voice_events`
collection by `message_id` BEFORE downloading audio:

  • Hit (already processed) → reuse the prior English transcript
    for downstream extraction OR re-send the prior user-facing
    error reply. No second Whisper call, no second translate
    call, no second audit row.
  • Miss → fetch + transcribe + translate + insert audit row.

Each `whatsapp_voice_events` row carries:

```
{ message_id, sender, english_transcript, original_transcript,
  language_detected, no_speech_prob, user_reply, error_kind,
  telemetry: {whisper_*, translate_*, audio_bytes_size, ...},
  received_at }
```

### 12.3 — Cost telemetry + projections

OpenAI public pricing as of 2026-Q1 (verify quarterly; PRICING
constant in `lib/voice_ingest.py` is the single source of truth):

  • Whisper:     **$0.006 / audio minute**, billed in 1-second granularity.
  • GPT-4o-mini: **$0.150 / 1M input tokens**, **$0.600 / 1M output tokens**.

A typical 30-second jobsite voice note hits:

  • Whisper:    30s ÷ 60 × $0.006 = **$0.003**
  • Translate:  ~150 tokens in / ~150 tokens out ≈ **$0.0001125**
  • Per-note total: **≈ $0.0031**

Cost projection at a steady cadence of 20 voice notes per PM per
working day (~22 weekdays/month):

| PMs | Daily notes | Monthly notes | Monthly Whisper $ | Monthly translate $ | Monthly total $ |
|---|---|---|---|---|---|
| 1 | 20 | 440 | $1.32 | $0.05 | **$1.37** |
| 10 | 200 | 4,400 | $13.20 | $0.50 | **$13.70** |
| 100 | 2,000 | 44,000 | $132 | $5 | **$137** |

Assumptions: 30s avg voice length; ~150 tokens per direction in
translate. Real numbers will skew if voice notes are routinely
longer or non-English (translate token count rises). Run a
quarterly check by aggregating `whatsapp_voice_events.telemetry`
sums per company.

### 12.4 — Aggregating costs per company per month

```
> db.whatsapp_voice_events.aggregate([
    { $match: {
        received_at: {
          $gte: ISODate("2026-05-01"), $lt: ISODate("2026-06-01")
        },
        "telemetry.whisper_cost_usd": { $exists: true }
    }},
    { $lookup: {
        from: "whatsapp_contacts", localField: "sender",
        foreignField: "phone", as: "_c"
    }},
    { $unwind: { path: "$_c", preserveNullAndEmptyArrays: true } },
    { $group: {
        _id: "$_c.company_id",
        notes: { $sum: 1 },
        whisper_usd: { $sum: "$telemetry.whisper_cost_usd" },
        translate_usd: { $sum: "$telemetry.translate_cost_usd" },
        total_usd: { $sum: {
          $add: [
            "$telemetry.whisper_cost_usd",
            "$telemetry.translate_cost_usd"
          ]
        }}
    }},
    { $sort: { total_usd: -1 } }
  ])
```

Use this for monthly billing review. Companies whose voice cost
materially exceeds their plan tier are candidates for tier-up
or per-overage charge per the billing model.

### 12.5 — Common error patterns

When Sentry surfaces a `voice_ingest_*` warning:

- **`voice_ingest_whisper_failed`** — OpenAI 5xx or timeout.
  The orchestrator already retried once; if it surfaces here,
  Whisper's actually flapping. Check Sentry's "first seen"
  timestamp against OpenAI's status page. Soft-fail: the user
  got "Voice note couldn't be processed, please retype as text."
- **`voice_ingest_download_failed`** — WaAPI's `download-media`
  returned no usable bytes. Most common cause: the messageId
  passed wasn't the SERIALIZED form (per Step 1 verification —
  WaAPI requires `false_chatId_hash_sender@lid`, not the short
  hash). Inspect `whatsapp_audio_probe` collection for the
  exact response WaAPI returned.
- **High `no_speech_prob` rate** — if `whatsapp_voice_events`
  shows >20% of voice notes shorting on `no_speech_prob > 0.6`,
  the threshold may be too aggressive for jobsite background
  noise. Re-tune `NO_SPEECH_PROB_THRESHOLD` in
  `lib/voice_ingest.py` (currently 0.6, conservative).

### 12.6 — When to add new external models

If OpenAI deprecates Whisper or the org swaps to a self-hosted
ASR (`faster-whisper`, `whisperX`, etc.):

1. The `whisper_fn` parameter on `process_voice_note` is the
   injection point. Pass a function with the same signature
   that returns a `WhisperResult` and the orchestrator works
   unchanged.
2. Update `PRICING` constants in `lib/voice_ingest.py` if the
   per-minute rate differs.
3. Update the cost projection table in §12.3 to match.

The orchestrator pattern (whisper_fn / translate_fn injection)
is specifically for this future swap. Don't rewrite the
orchestrator — wrap a new ASR / translator behind the same
function shape and inject it.

---

## 13. V2.0 — Compliance logbook (operational notes)

> Full feature documentation: [`../features/v2-logbook.md`](../features/v2-logbook.md).
> This section covers what the on-call operator needs to know
> when something goes sideways with the logbook surface.

### 13.1 — How to confirm the feature is OFF (production)

Default: `v2_logbook` flag absent from `feature_flags` collection
→ `is_feature_enabled` returns False → endpoints 404, FE returns
null. v1 customers see nothing.

```js
// In Mongo:
db.feature_flags.findOne({flag: "v2_logbook"})
// expected: null  (or {enabled_globally: false} after creation)
```

If a v1 customer reports seeing a v2 surface, check the audit
log:

```js
db.feature_flag_audit_log.find({flag: "v2_logbook"})
  .sort({changed_at: -1}).limit(10)
```

### 13.2 — How to roll out per `feature-flags.md` patterns

```bash
# 1. Create the flag (default OFF — first-touch is benign).
curl -X POST https://api.levelog.com/api/admin/feature-flags \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"flag":"v2_logbook","description":"Compliance logbook system"}'

# 2. Self-test: enable for the operator's own user_id only.
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_logbook \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled_for_users":["<operator-user-id>"]}'

# 3. Canary: BLUEVIEW.
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_logbook \
  -d '{"enabled_for_companies":["<blueview-company-id>"]}'

# 4. Percentage rollout.
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_logbook \
  -d '{"enabled_percentage": 10}'   # then 50, then 100

# 5. Kill switch (if anything goes sideways at any rollout step).
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_logbook \
  -d '{"enabled_globally": false, "enabled_percentage": 0,
       "enabled_for_companies": [], "enabled_for_users": []}'
```

Cache invalidates within 60s; the next `/api/feature-flags/me`
read picks up the new state.

### 13.3 — What the nightly tick does

Cron job `v2_logbook_nightly_tick` runs at 3 AM ET. Two phases:

  1. `run_missing_detector_for_all_projects(db)` — fills
     `logbook_entries` with `status=missing` for every weekday
     gap in `db.daily_logs`.
  2. `run_deficiency_detector_for_all_projects(db)` — re-runs
     the rules engine against the last 30 days of daily logs.

Both are idempotent via the `(project_id, entry_date, category)`
unique index. Re-runs produce no duplicates.

If the tick fails, check Sentry first — the wrapper catches any
exception and logs to `logger.error` (the Sentry integration
captures level=error). Common failures:

- Index missing — `_ensure_index_resilient` failed at startup.
  Confirm via `db.logbook_entries.getIndexes()`.
- Project query slow — too many active projects without an
  `is_deleted` index. Look at the existing
  `db.projects.getIndexes()`.

### 13.4 — How to manually trigger the missing detector

The nightly tick is the production path; for one-off operator
runs:

```python
# In a Python REPL on Railway:
from server import db
from lib.logbook.missing_detector import run_missing_detector_for_all_projects
import asyncio
result = asyncio.run(run_missing_detector_for_all_projects(db))
print(result)
# {'projects_scanned': N, 'missing_entries_written': M, 'errors': K}
```

### 13.5 — How to manually trigger an LL196 attestation

The endpoint is admin-callable per project per month:

```bash
curl -X POST \
  https://api.levelog.com/api/projects/<project-id>/logbook/attestations/generate \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"year": 2026, "month": 5}'
```

R2 key is deterministic (`ll196/{company_id}/{project_id}/YYYY-MM.pdf`)
so re-generation overwrites the prior PDF in place.

### 13.6 — Common operator questions

- **"Why does my brand-new project show 30 days of missing
  entries?"** It doesn't. The `created_at` floor in
  `detect_missing_for_project` clamps the start date to the
  project's creation date. Pre-creation days are never flagged.
- **"My project is on a 7-day-a-week schedule and the missing
  detector is wrong."** Add `weekend_work: true` to the project
  doc; the detector picks it up on the next tick.
- **"The kill switch is on but I still see v2 in the FE."** The
  FE flag map is per-session and the `useFeatureFlag` hook reads
  from it without re-fetching. A logged-in user keeps the prior
  state until they log out + back in (or call
  `validateSession`). If you need an immediate flip, push a
  notification asking affected users to log out and back in.

---

## 14. Environment variables reference

The full set of env vars the production deployment reads. Add new
ones here when you wire them.

| Variable | Service | Required? | What it does |
|---|---|---|---|
| `MONGO_URL` | backend | yes | Mongo Atlas connection string. |
| `DB_NAME` | backend | yes | Database name (production: `levelog`). |
| `JWT_SECRET` | backend | yes | HS256 signing key for auth tokens. Rotate on a security incident; users get logged out. |
| `JWT_EXPIRATION_HOURS` | backend | no | Session lifetime; default 168 (7 days). |
| `ALLOWED_ORIGINS` | backend | no | Comma-separated CORS allowlist. Defaults to a built-in production list if unset. |
| `RESEND_API_KEY` | backend | yes (for emails) | Outbound transactional email via Resend. |
| `RESEND_FROM_EMAIL` | backend | yes (for emails) | Sender address shown to recipients. |
| `NOTIFICATIONS_KILL_SWITCH` | backend | no | Set to `true` to suspend ALL outbound notifications. See Section 1. |
| `NOTIFICATIONS_ENABLED` | backend | no | Set to `false` to suppress non-critical notifications globally. Coarser than the kill switch. |
| `RATE_LIMITS_DISABLED` | backend | no | Set to `true` to bypass the C2 rate-limit middleware entirely. Emergency lever — see Section 11.4. Unset within 4 hours; production must run with limits ON. |
| `ATLAS_PUBLIC_KEY` | backup-cron | no | Atlas Programmatic API key (public). Used by `backend/scripts/verify_backup_freshness.py` (Phase C3). Project Read Only role. |
| `ATLAS_PRIVATE_KEY` | backup-cron | no | Atlas Programmatic API key (private). Paired with `ATLAS_PUBLIC_KEY`. Stored in 1Password. |
| `ATLAS_GROUP_ID` | backup-cron | no | Atlas Project (group) ID — 24-char hex from the Atlas dashboard URL. |
| `ATLAS_CLUSTER_NAME` | backup-cron | no | Production cluster name, e.g. `levelog-prod`. |
| `ATLAS_BACKUP_MAX_AGE_HOURS` | backup-cron | no | Threshold for the freshness check. Default 24. Set to 168 if running weekly. |
| `SENTRY_DSN` | backend | no | Sentry project DSN. Missing → error tracking disabled (graceful). |
| `SENTRY_ENVIRONMENT` | backend | no | Override for the environment tag. Falls back to `RAILWAY_ENVIRONMENT`, then `"development"`. |
| `RAILWAY_ENVIRONMENT` | backend | auto | Set automatically by Railway per environment. Used as Sentry environment fallback. |
| `RAILWAY_GIT_COMMIT_SHA` | backend | auto | Set automatically by Railway. Used as Sentry release tag. |
| `R2_*` | backend | yes (for files) | Cloudflare R2 credentials for project file storage. |
| `QWEN_API_KEY` | backend | no | OCR backend for COI uploads. |
| `OPENAI_API_KEY` | backend | yes (for voice ingest) | Powers Whisper transcription + GPT-4o-mini translation in the WhatsApp voice pipeline (Phase F1). Without it, voice notes still get downloaded but the orchestrator returns a "couldn't process" reply and skips extraction. See Section 12. |
| `WAAPI_BASE_URL` | backend | no | WaAPI base URL. Defaults to `https://waapi.app/api/v1`. |
| `WAAPI_INSTANCE_ID` | backend | yes (for WhatsApp) | WaAPI instance numeric id. |
| `WAAPI_TOKEN` | backend | yes (for WhatsApp) | WaAPI Bearer JWT token. |
| `EXPO_PUBLIC_API_URL` | frontend | yes | Backend API base URL. Without it the SPA can't talk to the API. |
| `EXPO_PUBLIC_SENTRY_DSN` | frontend | no | Sentry frontend project DSN. Missing → error tracking disabled. |
| `EXPO_PUBLIC_ENVIRONMENT` | frontend | no | Frontend Sentry environment tag. Falls back to `NEXT_PUBLIC_ENVIRONMENT`, then `NODE_ENV`, then `"development"`. |
| `EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA` | frontend | auto (build script) | Sentry release tag at runtime. Set automatically by `frontend/scripts/build-with-sourcemaps.js` from `VERCEL_GIT_COMMIT_SHA`. MUST match the release that source maps are uploaded under. |
| `VERCEL_GIT_COMMIT_SHA` | build | auto | Set automatically by Vercel during build. Read by the build wrapper. |
| `SENTRY_AUTH_TOKEN` | build | no (recommended for prod) | Auth token used by `@sentry/cli` to upload source maps. Production-environment-only on Vercel. Without it the build still completes, just no source map upload — Sentry events render with minified stacks. |

> **Hard rule:** never check any of these into git. The repo's
> `.gitignore` covers `.env` and `.env.*`, but a moment of
> inattention can leak secrets in a commit message or a debug
> dump. If you suspect a leak, rotate the affected key
> immediately.

---

## Notes for next operator

- **Tests are the safety net.** Every behavioral change should land
  with a test pinning the contract. Look at how Phase B3 added
  ~60 new tests across 4 files — that pattern keeps regressions
  out.
- **Static-source pin tests** (e.g.
  `test_b3_frontend_invariants.py`) are cheap and catch the
  "someone unwired the design system" class of regression. Use
  them aggressively — they don't need a JS test runner.
- **The kill switch is your friend.** Don't be heroic; flip it
  the moment something looks runaway and investigate calmly.
- **Read `lib/notification_preferences.py` head-to-toe at least
  once.** It's the most subtle module in the codebase; the
  invariants there determine email behavior for every customer.
