# The permit-expiry claim: where it is rendered, what it is built on, and what comes out

Trigger: the daily report email for 588 Thomas asserts "3 permits expiring within 30 days."
Report only — no code changed in this pass.

---

## 0. What the number actually is

`_count_permits_expiring_soon` (backend/server.py:27210-27259) counts **rows in
`permit_renewals`**, not permits. It opens a cursor, parses `current_expiration`
per row, and increments once per row that lands in the 0..30 day band. There is
no grouping by `permit_dob_log_id`, no grouping by `job_number` (which is null
anyway), and no dedupe of any kind.

So "3" means *three rows*. It does not mean three permits.

### Why the rows multiply

`permit_renewals` rows are keyed to `permit_dob_log_id` — the **ObjectId of a
`dob_logs` row**, not a stable permit identity.

- `dob_logs` **inserts a new document with a new `_id`** every time a permit's
  `current_status` changes (backend/server.py:25983-26010: `if existing and
  existing.get("current_status") == current_status:` → update in place, `else:`
  → insert). The old row is not soft-deleted. One real permit therefore
  accumulates N `dob_logs` rows over its life, each with a distinct `_id`.
- `nightly_renewal_scan` (backend/permit_renewal.py:1110-1260) iterates
  **every** `record_type: "permit"` row in `dob_logs` and dedupes with
  `find_one({"permit_dob_log_id": permit_id, "status": {"$nin": [FAILED,
  COMPLETED]}})` (backend/permit_renewal.py:1146-1153). That key is
  per-`dob_logs`-row, so each status-change row of the same permit passes the
  guard and gets its own `permit_renewals` insert at
  backend/permit_renewal.py:1258.
- The manual DOB reset-resync endpoint (backend/server.py:27170-27196)
  **deletes** a project's `dob_logs` rows and re-ingests them, minting all-new
  `_id`s. Every resync therefore orphans the existing `permit_renewals` rows
  (still `eligible` / `needs_insurance`, never `COMPLETED`/`FAILED`, so never
  excluded) and the next sweep writes a fresh set alongside them.
- The dedupe guard also omits `is_deleted`, so a soft-deleted row still blocks —
  the guard is wrong in both directions.

### Why the fields are null

The eligibility dispatcher is running in `live` mode (v2). Its adapter
`_v2_to_renewal_eligibility` (backend/lib/eligibility_dispatcher.py:164-200)
**hardcodes**:

```
backend/lib/eligibility_dispatcher.py:178   job_number=None,
backend/lib/eligibility_dispatcher.py:179   permit_type=None,
```

Both writers copy those straight through (backend/permit_renewal.py:1199-1200,
backend/permit_renewal.py:2025-2026). That is the whole explanation for
`job_number: null` and `permit_type: null` on every row — it is not a data gap,
it is a hardcoded `None` in the adapter.

### Why `days_until_expiry` disagrees with `current_expiration`

Same adapter, backend/lib/eligibility_dispatcher.py:172 and 181:

```
days_until = (v2_result.get("limiting_factor") or {}).get("expires_in_days")
...
expiration_date=v2_result.get("calendar_expiry"),
days_until_expiry=days_until,
```

`current_expiration` is written from `calendar_expiry`. `days_until_expiry` is
written from the v2 **effective/limiting-factor** expiry — a different date
(auto-extension, the 1-year-since-issuance ceiling, etc.). The two fields are
measured against different anchors by construction, which is exactly the
"358 on a permit expiring in two weeks" signature. Neither field is wrong in
isolation; the pair is incoherent, and every consumer that reads one and labels
it with the other's meaning is asserting something false.

By contrast, the **legacy** path (`off` mode) computed
`days_left = (exp_date - today).days` against the same `expiration_date` it
stored (backend/permit_renewal.py:658-667). The incoherence arrived with the
`live` cutover.

### On the Akamai claim — one correction

The Akamai-blocked hosts are `a810-dobnow`, `a810-bisweb`, `a810-dobnowtor`,
`a810-efiling` (backend/lib/server_http.py:68-72). Those gate the **GC license
and insurance** lookups (backend/permit_renewal.py:38, 356, 509, 547), which is
why eligibility/insurance data is dead.

Permit expiration data does **not** come from there. It comes from Socrata
(`data.cityofnewyork.us`, datasets `rbx6-tga4` / `dm9a-ab7w` / `ipu4-2q9a`,
backend/server.py:23690-23745), which is explicitly **not** on the blocklist
(backend/lib/server_http.py:74-77,
backend/lib/statistical_engine/socrata_client.py:7-8).

This does not rescue the number. It narrows the defect: the expiry dates are
fetchable, and the fabrication is in the `permit_renewals` layer sitting on top
of them — the row multiplication and the adapter's `None`s — not in the fetch.
It also means the fix is not "the source is down," which would be a defensible
"data unavailable." It is "we compute this wrong," which is not.

---

## 1. Every surface rendering a permit-expiry count or list

### A. Built on `permit_renewals` — fabricated

| # | Surface | Line | What it asserts |
|---|---|---|---|
| A1 | Daily report email — count | backend/server.py:27370 `expiring_permits = await _count_permits_expiring_soon(project_id)` | The row count |
| A2 | Daily report email — count fn | backend/server.py:27210-27259 | Counts rows, no dedupe |
| A3 | Daily report email — HTML sentence | backend/lib/email_templates.py:413-416, rendered at 440-444 | "3 permits on this project expire within 30 days." |
| A4 | Daily report email — HTML detail row | backend/lib/email_templates.py:431 | "Permits expiring (30d): 3" |
| A5 | Daily report email — plaintext | backend/lib/email_templates.py:472 and 479 | Same two claims in the text part |
| A6 | In-app card, project screen (desktop) | frontend/app/project/[id].jsx:1084 `<RenewalAlertCard projectId={projectId} />` | Mounts A8-A10 |
| A7 | In-app card, project screen (mobile) | frontend/app/project/[id].jsx:1195 | Mounts A8-A10 |
| A8 | RenewalAlertCard — fetch | frontend/src/components/RenewalAlertCard.js:49 `GET /api/permit-renewals?project_id=…&limit=10` | Reads the rows directly |
| A9 | RenewalAlertCard — headline | frontend/src/components/RenewalAlertCard.js:103-113 | "N days until permit expires" / "N permits eligible for renewal" |
| A10 | RenewalAlertCard — mini bars | frontend/src/components/RenewalAlertCard.js:185-193 | `J-{job_number.slice(-4)} · {days}d` — renders the literal `Permit` because `job_number` is null, and `days` from the mismatched field |
| A11 | List endpoint | backend/permit_renewal.py:1379-1409 `GET /api/permit-renewals` | Serves A8; also serves the permit-renewal detail screen |
| A12 | Dashboard-alerts endpoint | backend/permit_renewal.py:1426-1462 `GET /api/permit-renewals/dashboard-alerts` | Emits `job_number`, `permit_type`, `days_until_expiry` verbatim, sorted by `days_until_expiry`. **No frontend caller** — `permitRenewalAPI.getDashboardAlerts` (frontend/src/utils/api.js:1224) is defined and never invoked. Reachable over HTTP, dark in the app. |
| A13 | Permit-renewal detail screen | frontend/app/project/[id]/permit-renewal.jsx:56 | The parked module's own screen |
| A14 | Reminder email cron (T-30/14/7) | backend/server.py:34817-34877 | Sends per-renewal reminder emails off the same rows. Reads `current_expiration` (not the broken field), but fires **once per duplicate row**; `send_notification` dedupes on `(renewal_id, trigger, recipient)` and each duplicate has its own `renewal_id`, so the 23h idempotency window does **not** collapse them |
| A15 | Notification resend (owner) | backend/server.py:7784-7800 | Re-renders a reminder from current row state |

### B. Built on `dob_logs` — a different, defensible source

These are **not** fabricated and are **not** part of this removal. Listed so the
inventory is complete and so nobody removes the wrong thing.

| # | Surface | Line | Source |
|---|---|---|---|
| B1 | DOB summary aggregation, `permits_expiring` facet | backend/server.py:9995-10014 | `db.dob_logs`, deduped by `raw_dob_id`, `$dateFromString` with `onError: null` (undercount, never miscount) |
| B2 | Project screen tile "Permits expiring <30d" | frontend/app/project/[id].jsx:747 | B1; renders `—` not `0` when the read fails (`dobUnknown`) |
| B3 | Portfolio dashboard tile | frontend/app/index.jsx:84, 556 | B1 |
| B4 | Projects table column | frontend/src/components/ProjectsTable.jsx:66, 92 | B1 |
| B5 | DOB logs screen Permits tile | frontend/app/project/[id]/dob-logs.jsx:211-215 | B1 |
| B6 | `next_action` strings on permit rows | backend/server.py:26608-26646 | `check_permit_expirations` writes `"Permit expires in N days (…). File renewal on DOB NOW."` onto `dob_logs`, computed against that row's own `expiration_date`. Self-consistent. |
| B7 | Renewal digest email (T-30/60/90 cadences) | backend/server.py:26308-26360, backend/lib/renewal_digest.py | Pulls `permits` from **`db.dob_logs`** (backend/server.py:26352-26362), not `permit_renewals`. Independent of this defect. |

The two families disagree with each other, which is its own problem: B2's tile
and A9's card sit on the **same screen**, sourced from different collections
with different dedupe rules.

---

## 2. Does anything else customer-facing read `permit_renewals`?

**No compliance score or risk number reads it.** Verified by exhaustive grep:
the string `permit_renewals` appears in exactly these production files —

- backend/server.py
- backend/permit_renewal.py
- backend/lib/filing_readiness.py:410
- backend/lib/pw2_field_mapper.py:260
- backend/scripts/{audit_production,backfill_renewal_v2_keys,migrate_clean_stranded_renewals}.py

and in **zero** frontend files (the app only reaches it through the endpoints in
table A). `backend/lib/statistical_engine/` — which is what produces
`risk_scores` — does not reference it at any point. The risk score is built from
Socrata datasets and `dob_logs`. It is not contaminated.

`filing_readiness.py` and `pw2_field_mapper.py` read a single renewal by id for
the parked filing pipeline; they are admin/worker-facing, gated behind
`get_admin_user` or the readiness 409, and produce no customer-visible number.

**So the blast radius of the fabricated rows is exactly: the daily report email
(A1-A5), the in-app RenewalAlertCard (A6-A10), the parked module's own screen
(A13), and the reminder/resend emails (A14-A15).**

---

## 3. Is ANY production row sound?

Two questions, two queries. Run against production, read-only.

### 3a. Does any row have a non-null `job_number` at all?

```js
db.permit_renewals.countDocuments({
  is_deleted: { $ne: true },
  job_number: { $nin: [null, ""] }
})
```

Prediction from the code: any row written **after** the `live` cutover is null by
construction (backend/lib/eligibility_dispatcher.py:178). A non-zero count means
pre-cutover legacy rows survive. Split them:

```js
db.permit_renewals.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $group: {
      _id: { has_job:  { $in: ["$job_number",  [null, ""]] },
             has_type: { $in: ["$permit_type", [null, ""]] } },
      n: { $sum: 1 },
      oldest: { $min: "$created_at" },
      newest: { $max: "$created_at" } } },
  { $sort: { n: -1 } }
])
```

The `newest` timestamp on the has-job bucket dates the cutover.

### 3b. Of the rows that have a `job_number`, is `days_until_expiry` correct?

Correctness test: `days_until_expiry` was computed at write time, so it must
equal `current_expiration - created_at` in whole days. Tolerance ±1 for the
tz/rounding boundary.

```js
db.permit_renewals.aggregate([
  { $match: {
      is_deleted: { $ne: true },
      job_number: { $nin: [null, ""] },
      days_until_expiry: { $ne: null },
      current_expiration: { $nin: [null, ""] } } },

  // current_expiration is mixed-format (ISO and M/D/YYYY both in prod).
  // Try ISO, fall back to MDY, else null.
  { $addFields: { _exp: { $ifNull: [
      { $dateFromString: { dateString: "$current_expiration",
                           onError: null, onNull: null } },
      { $dateFromString: { dateString: "$current_expiration",
                           format: "%m/%d/%Y", onError: null, onNull: null } } ] } } },
  { $match: { _exp: { $ne: null } } },

  { $addFields: { _expected: { $floor: { $divide: [
      { $subtract: ["$_exp", "$created_at"] }, 86400000 ] } } } },
  { $addFields: { _drift: { $abs: {
      $subtract: ["$days_until_expiry", "$_expected"] } } } },

  { $facet: {
      sound:  [ { $match: { _drift: { $lte: 1 } } }, { $count: "n" } ],
      broken: [ { $match: { _drift: { $gt:  1 } } }, { $count: "n" } ],
      worst:  [ { $sort: { _drift: -1 } }, { $limit: 10 },
                { $project: { _id: 1, job_number: 1, permit_type: 1, status: 1,
                              current_expiration: 1, days_until_expiry: 1,
                              _expected: 1, _drift: 1, created_at: 1,
                              permit_dob_log_id: 1 } } ]
  } }
])
```

**A row is sound only if it appears in `sound`.** `sound: []` (or the facet
empty) is the answer that ends the argument: no row in production has both a job
number and a coherent expiry, and there is nothing to salvage.

### 3c. Reproduce the "3" for 588 Thomas, and show what the rows are

```js
const p = db.projects.findOne({ name: /588\s*Thomas/i }, { _id: 1, name: 1 });
const pids = [p._id.toString(), p._id];   // writers store both forms

db.permit_renewals.find({
  project_id: { $in: pids },
  status: { $in: ["eligible", "needs_insurance", "ineligible_insurance",
                  "ineligible_license", "draft_ready", "awaiting_gc"] },
  is_deleted: { $ne: true }
}, { permit_dob_log_id: 1, job_number: 1, permit_type: 1, current_expiration: 1,
     days_until_expiry: 1, status: 1, created_at: 1 })
  .sort({ created_at: 1 })
```

Then collapse them to real permits — resolve each `permit_dob_log_id` back to
its `dob_logs.raw_dob_id`, which **is** the stable per-permit key:

```js
db.permit_renewals.aggregate([
  { $match: { project_id: { $in: pids }, is_deleted: { $ne: true },
              status: { $in: ["eligible","needs_insurance","ineligible_insurance",
                              "ineligible_license","draft_ready","awaiting_gc"] } } },
  { $addFields: { _log_oid: { $toObjectId: "$permit_dob_log_id" } } },
  { $lookup: { from: "dob_logs", localField: "_log_oid",
               foreignField: "_id", as: "_log" } },
  { $addFields: { raw_dob_id: { $first: "$_log.raw_dob_id" } } },
  { $group: { _id: "$raw_dob_id", rows: { $sum: 1 },
              expirations: { $addToSet: "$current_expiration" },
              days_values: { $addToSet: "$days_until_expiry" },
              renewal_ids: { $push: "$_id" } } },
  { $sort: { rows: -1 } }
])
```

`rows: 3` against a single `_id` is the proof that "3 permits" is one permit
counted three times. Distinct values in `expirations` for one `raw_dob_id` show
the rows also disagree with each other about the date.

---

## 4. The claim comes out

**Status: implemented.** §4.1 and §4.2 shipped as the "the daily report stops
claiming permits are expiring" PR. §4.3 (unschedule the reminder cron) shipped
earlier, alongside the health-check removal. The writer stop — §11, which was
not in the original proposal — shipped in between. The adapter, the dedupe
guard, and the collection are untouched, as scoped.

Not "0 permits expiring." Zero is an assertion, and we cannot make it — we do not
know how many permits are expiring, we only know the number we were printing was
not it. Silence is the only honest output while the module is parked.

### 4.1 Daily report email — remove the claim entirely

The template already omits the whole block when `expiring` is falsy
(backend/lib/email_templates.py:416, 431, 443, 472, 479 are each guarded by
`if expiring`). So a recipient who has been getting the line stops getting it,
and a recipient who never had it sees no change. There is no "0" state to leak
and no layout hole.

1. **backend/server.py:27370** — delete the
   `expiring_permits = await _count_permits_expiring_soon(project_id)` call.
2. **backend/server.py:27380** — delete `"expiring_permits": expiring_permits,`
   from the `render_for_trigger("project_daily_report", {...})` context.
3. **backend/server.py:27210-27259** — delete `_count_permits_expiring_soon`.
   It has exactly one caller. Leaving it is leaving a loaded gun.
4. **backend/lib/email_templates.py:398, 413-416, 431, 440-444, 472, 479** —
   delete `expiring`, `expiring_line`, the amber `<p>`, the detail row, and both
   plaintext lines. The renderer must not read `expiring_permits` at all, so a
   stale caller passing it cannot resurrect the claim.
5. **New test** — `backend/tests/test_daily_report_no_permit_claim.py`: render
   `project_daily_report` with `expiring_permits` set to 0, 3, and absent, and
   assert none of `"expir"`, `"permit"`, `"30 days"` appears in subject, html, or
   text. Pin it to the *string*, not the variable, so a future re-add fails the
   suite. (backend/tests/test_daily_report_email_has_no_login_link.py:37 passes
   `expiring_permits: 0` in its fixture — that key becomes inert, no edit needed,
   but worth a comment.)

The PDF attachment needs no change: `generate_combined_report`
(backend/server.py:21665+) never carried a permit-expiry section. Its "permit"
strings are hot-work-permit checkboxes and scaffold general-info fields from the
logbook forms — unrelated, correctly sourced from the logbook itself.

### 4.2 In-app RenewalAlertCard — unmount

This is the same false assertion, rendered inside the app. It carries no
`isAdmin` guard. "N days until permit expires" is `days_until_expiry` under a
label that means the other date, and the mini-bars render the literal string
`Permit` because `job_number` is null.

**Correction to an earlier draft of this report: a CP does NOT see it.** See §7.
The audience is `admin` / `owner` / `pm` / `user`, not CPs.

1. **frontend/app/project/[id].jsx:1084** — remove the mount.
2. **frontend/app/project/[id].jsx:1195** — remove the mount.
3. Remove the now-unused `import RenewalAlertCard` at
   frontend/app/project/[id].jsx:50.
4. **Leave frontend/src/components/RenewalAlertCard.js on disk**, unreferenced,
   with a header comment saying why it is unmounted and what must be true before
   it goes back. The module is parked; deleting the component is a decision about
   the module, and that is not this change.

The B2 tile at frontend/app/project/[id].jsx:747 stays. It is `dob_logs`-sourced,
deduped by `raw_dob_id`, and already renders `—` rather than `0` when the read
fails — it is the honest surface, and removing it would be removing the good one.

### 4.3 Reminder emails — stop the cron, do not fix it

`renewal_reminder_cron` (backend/server.py:34817, scheduled at
backend/server.py:35626-35628) fires T-30/T-14/T-7 emails **per duplicate row**.
`send_notification`'s 23h idempotency keys on `renewal_id`, and each duplicate
carries a different one, so a permit with three rows sends three identical
"expires in N days" emails to every filing rep and company admin.

Proposal: remove the `renewal_reminder_cron` job registration
(backend/server.py:35625-35630) and leave the function body in place,
unscheduled. Same reasoning as 4.2 — parking the emission, not deleting the
module.

`dob_approval_watcher` (backend/server.py:34422, scheduled 35609-35612) can stay:
it only promotes `AWAITING_DOB_APPROVAL → COMPLETED` and sends on that
transition. With the module parked nothing reaches that status, so it is a no-op
cycle, and it is the one job that *reduces* the live row count.

### 4.4 Explicitly out of scope

- **Do not fix the dispatcher adapter.** `job_number=None` / `permit_type=None` /
  the `days_until_expiry` anchor mismatch at
  backend/lib/eligibility_dispatcher.py:164-200 is the real bug. Fixing it is
  unparking the module. File it; do not touch it here.
- **Do not fix the dedupe guard** at backend/permit_renewal.py:1146.
- **Do not delete the `permit_renewals` collection.** The rows are evidence for
  §3, and `migrate_clean_stranded_renewals.py` establishes soft-delete as this
  collection's convention.
- **Do not touch `dob_logs` or anything in table B.**
- **`GET /api/permit-renewals/dashboard-alerts`** (A12) stays as-is. It is dark —
  no caller — and removing an endpoint is a module decision. Noted, not actioned.

### 4.5 If a line is wanted instead of silence

If the daily report must acknowledge the gap rather than say nothing, the only
defensible wording asserts the state of our knowledge, not the state of the
permits:

> Permit expiry tracking is unavailable for this project. This report makes no
> claim about permit status.

Static text, no count, no date, not conditional on any query. My recommendation
is still removal (4.1): a standing "unavailable" notice on every daily email to
every customer is a durable admission with no expiry date on it, and the B2 tile
already tells the in-app story from a source we trust.

---

## 5. Order of operations

1. Run §3a, §3b, §3c against production. Paste results here.
2. If §3b returns an empty `sound` bucket — which the code predicts — the removal
   in §4 is unconditional and needs no further judgment call.
3. If §3b returns a non-empty `sound` bucket, those rows are pre-`live`-cutover
   legacy survivors. They still do not rescue the email, because
   `_count_permits_expiring_soon` cannot tell them apart from the fabricated ones
   at count time. Removal stands; the finding just changes what a future unpark
   can reuse.

Runnable queries: docs/audits/permit-expiry-queries-2026-08-27.js

---

## 6. Has `renewal_reminder_cron` actually sent anything?

### Where a send is recorded

`notification_log`, written by `_write_log_entry`
(backend/lib/notifications.py:477-513) on **every** outcome — sent, failed, and
each suppression reason. It is the complete audit trail; there is no other
record. Schema:

```
permit_renewal_id   str       the renewal _id (also the idempotency key)
trigger_type        str       renewal_t_minus_30 / _14 / _7
recipient           str       lowercased email
subject             str
status              str       sent | failed | suppressed_*
sent_at             datetime  written on every outcome, not just sends
resend_message_id   str|null  present only on status == "sent"
error_detail        str|null
metadata            obj       {days_until_expiry: N}
```

`status: "sent"` with a non-null `resend_message_id` is the only outcome that
reached a person. Queries: §0, §1a-§1e of the query file.

### Three gates it had to pass, and what each records

1. **`NOTIFICATIONS_KILL_SWITCH`** (backend/lib/notifications.py:52-58, checked
   first at 264-279) → `suppressed_kill_switch`. This is the lever the operator
   flipped in the 2026-05-03 incident, when a customer received 20+ emails.
2. **Idempotency**, 23h window keyed on `(permit_renewal_id, trigger_type,
   recipient)` (backend/lib/notifications.py:191-206) → `suppressed_idempotent`.
   **This is the gate that does not hold.** Duplicate renewal rows carry
   different `_id`s, so N duplicates produce N distinct keys and N sends.
3. **`NOTIFICATIONS_ENABLED`**, which **defaults to `"false"`**
   (backend/lib/notifications.py:61-63) → `suppressed_flag_off`. If that env var
   was never set on Railway, nothing was ever delivered and every reminder is
   sitting in the log as `suppressed_flag_off`.

Gate 3 is the likely answer and §0 settles it in one query. But it is a
**config-shaped** protection, not a code-shaped one: one env var away from
firing, on a cron that is registered and running every day
(backend/server.py:35626-35628). The cycle executes, builds candidates, and
calls `send_notification` per duplicate per recipient regardless — only the last
step is stopped.

### What the emails would say

Worth stating precisely, because it cuts against my earlier framing in two
directions.

`_renewal_reminder_context` (backend/server.py:34688-34726) loads the `dob_log`
and prefers **its** `job_number` and `work_type` over the renewal's:

```
backend/server.py:34716   "permit_job_number": ((dob_log or {}).get("job_number")
backend/server.py:34717                          or renewal.get("job_number") or "—"),
```

and the day count is `days_until`, freshly recomputed from `current_expiration`
at backend/server.py:34850-34857 — **not** the broken stored field.

So an individual reminder email is internally coherent: real job number, real
work type, a day count that matches the expiration it prints. It looks right.
That makes it worse, not better — it is a credible-looking email, sent N times,
about a permit that may be one permit.

**Except for orphans.** After a reset-resync the old renewals point at deleted
`dob_logs` rows, so `dob_log` is `None` and the fallback lands on
`renewal.get("job_number")`, which is null → the email renders the job number as
**`—`**. Query §1d isolates those (null `raw_dob_id`).

### Recipients

`collect_notification_recipients` (backend/lib/notifications.py:127-169):
every `companies.filing_reps[].email`, plus the first `admin`/`owner` user on
the company. Filing reps are **external** addresses — expediters, not LeveLog
account holders. There is no opt-out on this path.

---

## 7. Does a CP see the RenewalAlertCard? No.

**A CP cannot reach the screen.** `frontend/app/_layout.jsx:221-232` confines
`role === 'cp'` to an allowlist:

```
frontend/app/_layout.jsx:223   pathname.startsWith('/logbooks') ||
frontend/app/_layout.jsx:224   pathname === '/documents' ||
frontend/app/_layout.jsx:225   pathname === '/settings' ||
frontend/app/_layout.jsx:226   pathname === '/login'
```

anything else → `router.replace('/logbooks')`. `/project/{id}` is not on it.
`site_device` is confined the same way (frontend/app/_layout.jsx:199-218).

My §4.2 draft said "the project screen both roles land on." That was wrong, and
it was the load-bearing half of the claim. Correcting it.

**What is true:** the mounts carry no role guard of their own. The route guard
confines `cp` and `site_device` and nothing else, so **`admin`, `owner`, `pm`,
and `user`** all reach `/project/{id}` and all render the card. `pm` and `user`
are real roles in this system (backend/server.py:26455 routes digests to
`{"$in": ["pm", "cp"]}`; backend/server.py:11101 creates `role: "user"`), and
neither is an operator — a PM is a customer.

Entry points to the screen, none admin-gated: the desktop dashboard's on-site
list (frontend/app/index.jsx:715) and its project tiles
(frontend/app/index.jsx:589), plus the admin projects table
(frontend/app/projects/index.jsx:282, 288).

### The card renders twice

Both mounts sit at the top level of the shared body, after the
`isDesktop ? renderDesktopTop() : (…)` ternary closes at
frontend/app/project/[id].jsx:983:

- frontend/app/project/[id].jsx:1084 — between `)}` (1082) and `{isAdmin && (` (1087)
- frontend/app/project/[id].jsx:1195 — between `)}` (1192) and `{isAdmin && (` (1198)

Neither is inside a branch. The component returns `null` when there are no rows
(frontend/src/components/RenewalAlertCard.js:73), so today it is invisible on
clean projects — and on a project with fabricated rows the **same false alert
appears twice on one screen**. Removing both mounts fixes the duplication as a
side effect; no separate change needed.

### The class of defect the user named

Confirmed and worth recording as the general rule, not the instance.
frontend/src/components/RenewalAlertCard.js:185-193:

```
{a.job_number ? `J-${a.job_number.slice(-4)}` : 'Permit'} · {days}d
```

The ternary's false branch is a **cosmetic fallback in front of a control
surface**. When identity is missing it substitutes a category noun and keeps
rendering the urgency bar, the colour, and the day count — so the control
asserts "this specific thing is N days from expiring" while being unable to say
which thing. Same shape as the blank certification rows: the absence of the
identifying field is rendered as a styling problem rather than as a reason not
to make the claim.

Two nearby surfaces get this right and are worth citing as the house pattern:
the DeskTile at frontend/app/project/[id].jsx:747 renders `—` rather than `0`
when the read fails, and frontend/app/project/[id].jsx:1047-1050 comments that
the NFC fallback is "a real (possibly cached) fallback, not a fabricated empty."

The removal in §4.2 takes the card out, so no fix to the ternary is proposed —
fixing it would be unparking the module. Recorded here so the rule survives the
removal.

---

## 8. Why `NOTIFICATIONS_ENABLED` did not suppress

It was deliberately turned on in production, and has been all along.

docs/architecture/v1-monitoring-architecture.md:301:

> `NOTIFICATIONS_ENABLED` | `1` (default in production) — global enable. Pair
> with `NOTIFICATIONS_KILL_SWITCH=1` for emergency halt.

and the deploy runbook at v1-monitoring-architecture.md:463 sets
`NOTIFICATIONS_ENABLED=1` with `NOTIFICATIONS_KILL_SWITCH` unset. So zero
`suppressed_flag_off` rows across 221 sends is the **correct and expected**
result, not an anomaly. The code default at
backend/lib/notifications.py:61-63 is `"false"`, and that default has never
applied to this deployment.

**My §6 was wrong to lean on it.** I cited the code default as the likely
production state without checking the deploy documentation, which says the
opposite in plain terms. The flag was never a brake. Correcting it here rather
than editing §6, so the error and the correction both stay on the record.

What this leaves:

- `NOTIFICATIONS_ENABLED` is read **once at module load**
  (backend/lib/notifications.py:61, called out in the comment at line 41), so
  turning it off requires a redeploy — and it halts *all* outbound email,
  including the alerts that are working correctly. It is not a targeted tool.
- `NOTIFICATIONS_KILL_SWITCH` reads env on every call
  (backend/lib/notifications.py:52-58) and needs no restart, but is equally
  indiscriminate.
- So the only two global brakes are both all-or-nothing, and the per-trigger
  brake — idempotency — is the one that failed. That is why the remediation is
  per-cron unscheduling rather than a flag flip.

---

## 9. `dob_now_health_check` — 60 sends, structurally guaranteed false

**Confirmed exactly as described.** backend/permit_renewal.py:42:

```
DOB_NOW_BUILD_URL = "https://a810-dobnow.nyc.gov/publish/Index.html"
```

That host is **first** on `AKAMAI_BLOCKED_HOSTS`
(backend/lib/server_http.py:68-72). `run_dob_now_health_check` fetches it
through `ServerHttpClient` (backend/permit_renewal.py:929-930), which raises
`EgressViolation` at backend/lib/server_http.py:151-153 before any packet
leaves — the message being *"Server-side request to Akamai-protected host
'a810-dobnow.nyc.gov' is forbidden… route through the worker queue instead."*

The blanket handler at backend/permit_renewal.py:937-942 catches it and files:

```
f"DOB NOW UNREACHABLE: Could not connect to DOB NOW. Error: {str(e)}"
```

which is then emailed under the subject *"⚠️ DOB NOW Health Check Alert"* with
the body *"Permit renewal portal may be unavailable."* The alert quotes our own
egress guard's refusal and presents it as a DOB outage. It could never have
reported anything else — every run since the guard landed has failed
identically, which is why it is exactly daily rather than intermittent.

**Decision: unscheduled, not routed through the queue.** Three reasons:

1. The check guards an RPA filing pipeline that is parked. Nothing consumes a
   "DOB NOW is up" signal; the only reader is the admin-only
   `GET /permit-renewals/health-status`.
2. Its **success** path is unbacked too — it logs "✅ … all selectors valid"
   (backend/permit_renewal.py:949-951) for a selector check that was never
   implemented; `js_hash` is persisted as `None` and the comment at
   backend/permit_renewal.py:953-959 says the compute step never landed. Both
   branches assert more than they know. Same class as §7.
3. Routing it through the worker queue means standing up worker-mediated fetch
   for a parked module. That is new infrastructure, not a stop.

One nuance worth recording: the recipient is `OWNER_ALERT_EMAIL`
(backend/permit_renewal.py:36, 990) — the operator, **not** a customer. Of the
221 sends, these 60 are the only ones that never reached a customer. They are
noise and a false signal about our own infrastructure, not a customer-facing
false claim.

Note the delivery path: it was not its own scheduled job. It was Job 3 inside
`nightly_renewal_scan`, self-throttled to once per 23h by a `system_config`
read. Removing the Job 3 block is the unschedule.

---

## 10. `critical_dob_alert` — 25 sends, structurally sound

**It does not touch `permit_renewals`.** The 25 are not suspect.

- **Trigger:** `_send_critical_dob_alert_throttled`, from two callsites in the
  DOB sync — backend/server.py:26009 (existing record whose severity escalated
  to `Action`) and backend/server.py:26036 (new record inserted at `Action`) —
  plus backend/server.py:24560 for the 311 poll.
- **Data read:** the `dob_logs` document only — `ai_summary`, `next_action`,
  `record_type`, `dob_link`, `detected_at`, `raw_dob_id`, `severity`
  (backend/server.py:24050-24056). No renewal lookup anywhere in the path.
- **Recipients:** company `admin`/`owner` users (backend/server.py:24036-24044).
- **Idempotency:** keyed on `dob_log:{raw_dob_id}`
  (backend/server.py:24130-24131) — **`raw_dob_id` is the stable per-permit
  key**, the one thing `permit_renewals` should have keyed on and didn't. So one
  alert per record per recipient per 23h actually holds here.
- **Two further gates** the reminder cron had no equivalent of
  (backend/server.py:24251-24287): initial-scan suppression, so a backfill
  doesn't blast; and a 24h per-record throttle in `dob_alert_sent`.

This is the same defect's mirror image, and the contrast is the useful part:
identical email machinery, three working gates instead of one broken one, and
the difference is entirely that the idempotency key names a real thing.

**One caveat, not a defect.** `check_permit_expirations`
(backend/server.py:26608-26646) stamps `severity: "Action"` and
`next_action: "Permit expires in N days…"` onto `dob_logs` permit rows, so some
of the 25 may be permit-expiry alerts. Those are table-B-sourced and
self-consistent — the day count is computed against that same row's
`expiration_date`. They make a claim we can support. Worth spot-checking which
of the 25 were `record_type: "permit"`, but nothing here needs removing.

---

## 11. Why the rows are accelerating: the scan is not nightly

12 → 18 → 16 → 34 needed an explanation. Here it is.

`nightly_dob_scan` is scheduled on `IntervalTrigger(minutes=15)`
(backend/server.py:35592-35597) — **96 times a day**, not once. Its own
docstring still says *"Cron job: runs daily at 04:00 AM EST"*
(backend/server.py:26283); the comment above the scheduler entry
(backend/server.py:35588-35590) records the cadence change to 15 minutes for the
v1 monitoring product and the docstring was never updated.

The last two lines of that function (backend/server.py:26305-26306):

```
await check_permit_expirations()
await nightly_renewal_scan(db)
```

So `nightly_renewal_scan` — the writer that creates `permit_renewals` rows — is
**not a nightly job**. It runs every 15 minutes. Every tick re-walks every
`record_type: "permit"` row in `dob_logs` and inserts a renewal for any whose
`permit_dob_log_id` isn't already covered by a live row. Combined with
`dob_logs` minting a new `_id` per status change, the row count is driven by
DOB status churn × 96 daily passes.

This is why removal is the right call and a fix is not a small one: **the
duplicate rows keep multiplying after this PR.** Unscheduling the reminder cron
and removing the email stops the *assertions*; it does not stop the *writes*.
Nothing customer-facing reads them once §4 lands, so the growth becomes
inert — but it is growth, and it should be on the backlog with the adapter fix,
not left implicit.

Not actioned here: removing backend/server.py:26306 would stop the writes, but
it is a change to the parked module's writer and outside what was authorized.
Flagged for the decision.
