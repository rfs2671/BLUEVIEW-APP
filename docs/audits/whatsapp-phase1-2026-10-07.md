# WhatsApp Phase 1 — foundations (2026-10-07)

Base: `main` @ `feaa0da`. This adds no user-facing feature: no summaries,
alerts, reminders or GC broadcasts are sent. It builds what those features
need, and the rule that constrains them.

## The rule

**No proactive direct message to any phone without an active opt-in.** The
rule is enforced inside `send_whatsapp_message`, so no call site can skip it.
A direct message can leave for exactly two reasons:

1. **A reply.** The person messaged the bot in the last 10 minutes. Their own
   inbound message opens a window of at most 4 sends. It is a database row,
   not a flag a caller can pass.
2. **A proactive send** to a phone with an `active` opt-in row. The ledger
   claims it before WaAPI is called, keyed on (user, project, kind, window).

The intended entry point for proactive sends is `send_whatsapp_dm`. It also
checks that:
- the user is eligible;
- the opt-in phone is still the phone on the user's record;
- the user can see the project (company-scoped; a PM only on assigned
  projects);
- the user's preferences allow that kind of message.

## What applies on deploy

| What | Where | Effect on first boot |
|---|---|---|
| `whatsapp_webhook_log_ttl_30d` (`received_at`, 30 days) | `ensure_whatsapp_phase1_indexes` | **Deletes** webhook-log rows older than 30 days. The TTL monitor runs about once a minute. |
| `whatsapp_messages_ttl_24m` (`created_at`, 730 days) | same | Deletes messages older than 24 months. None are that old yet; the first message is from 2026-04. |
| `scheduler_leases_ttl` (`expires_at`, 0) | same | New collection |
| `whatsapp_dm_reply_windows_ttl` (`expires_at`, 0) | same | New collection |
| `whatsapp_notification_ledger_ttl` (`expires_at`, 0); rows expire after 180 days | same | New collection |
| `whatsapp_notification_ledger_by_user` (`user_id`, `created_at` desc) | same | New collection |
| `whatsapp_optins_phone_unique` (`phone`, unique) | same | New collection |
| `whatsapp_optins_by_user` (`user_id`, `status`) | same | New collection |
| Scheduler lease on all 26 jobs | `lib/scheduler_lease.py` | One small row per job firing in `scheduler_leases`. Each row expires on its own. |
| Job `waapi_instance_monitor`, every 15 min | startup | Two WaAPI `GET` calls at most per run. Emails go only on state changes. |

Nothing else writes production data until a person messages START or STOP,
or an admin sets a GC group.

## Pending checks (read-only)

```js
// What the 30-day webhook-log TTL will remove on first boot
db.whatsapp_webhook_log.countDocuments({received_at: {$lt: new Date(Date.now() - 30*864e5)}})
db.whatsapp_webhook_log.countDocuments({received_at: {$not: {$type: "date"}}})   // never expired
// Messages without a date field (never expired by the TTL)
db.whatsapp_messages.countDocuments({created_at: {$not: {$type: "date"}}})
// Who the disconnect monitor will email
db.users.find({is_platform_operator: true, is_deleted: {$ne: true}}, {email: 1})
// Who can opt in today: eligible roles with a phone, per company
db.users.aggregate([{$match: {is_deleted: {$ne: true}, role: {$in: ["admin", "pm"]}}},
  {$group: {_id: "$company_id", n: {$sum: 1},
            with_phone: {$sum: {$cond: [{$gt: [{$strLenCP: {$ifNull: ["$phone", ""]}}, 0]}, 1, 0]}}}}])
// Phones shared by two live users (START from these is refused as ambiguous)
db.users.aggregate([{$match: {is_deleted: {$ne: true}, phone: {$nin: [null, ""]}}},
  {$group: {_id: "$phone", users: {$push: "$_id"}, n: {$sum: 1}}}, {$match: {n: {$gt: 1}}}])
```

---

## 10. `nyc_inspections` (report only)

**No code writes or reads this collection.** It was the V2.2 local mirror, and
commit `d19a4b9b` ("V2.3 Commit 1 of 7 — remove V2.2 local-mirror
infrastructure", 2026-05-10) removed both its writer and its readers. Every
current hit for the name is a comment or a doc:
- `lib/statistical_engine/schema.py:6, 56-66, 135-148`
- `baselines.py:4`
- runbook `path_a_bbl_keyed_peer_comparison.md`

**What the writer did, from history.** It ingested Socrata `p937-wjvj` with
these fields:
- `record_id`, `bin`, `bbl`, `borough`
- `occurred_date` (from `inspection_date`)
- `inspection_type`, `result`, `job_id`
- `ingested_at`

There was no `source` and no `project_id`; rows joined to projects by BIN or
BBL. The schedule was a weekly Sunday cron covering the last 7 days, plus an
operator backfill. Both are removed.

**Does it give future inspection dates per BIN? No.** There are two reasons:
- The only date it held was the date an inspection *happened*, with a
  result. Nothing scheduled or in the future.
- `p937-wjvj` is NYC DOHMH **rodent** inspection data, not DOB building
  inspections (`server.py`, the "DOB INSPECTIONS — INGEST REMOVED" block).

Read-only queries; the collection may already have been dropped:

```js
db.getCollectionNames().includes("nyc_inspections")
db.nyc_inspections.estimatedDocumentCount()
db.nyc_inspections.aggregate([{$group: {_id: {$ifNull: ["$source", "$dataset"]}, n: {$sum: 1}}}])
db.nyc_inspections.aggregate([{$group: {_id: "$borough", n: {$sum: 1}}}, {$sort: {n: -1}}])
db.nyc_inspections.aggregate([{$group: {_id: null, min: {$min: "$occurred_date"}, max: {$max: "$occurred_date"},
  minIngest: {$min: "$ingested_at"}, maxIngest: {$max: "$ingested_at"}}}])
db.nyc_inspections.aggregate([{$match: {occurred_date: {$gt: new Date()}}},
  {$group: {_id: "$bin", n: {$sum: 1}, next: {$min: "$occurred_date"}}}, {$sort: {n: -1}}, {$limit: 50}])
db.nyc_inspections.find({}, {_id: 0}).sort({occurred_date: -1}).limit(1)
```

## 11. Changing a user's phone: does `whatsapp_contacts` follow? (report only)

There are two paths that change a phone, plus activation.

- **Self-service, `PUT /auth/profile`** (Settings → Save Phone).
  - Normalises to E.164 and checks uniqueness within the company (409).
  - Updates the contact row **only if the company's `whatsapp_config` is
    active**. In that case it nulls `user_id` on the row matching the old
    phone exactly, and upserts a new `+E164` row.
- **Admin edit, `PUT /admin/users/{id}`.**
  - Updates the contact row whether or not WhatsApp is active.
  - Makes the same exact-match null of the old row and the same upsert.
  - Has **no uniqueness check**.
  - The admin screen leaves out an empty phone, so it cannot clear one.
- **Activation backfill, `POST /whatsapp/activate`.**
  - Runs once.
  - Stores **digits with no `+`**, under `name` rather than `display_name`.

**The gap (verified in code):** the old row is matched by the exact E.164
string. A row seeded by activation stores digits, so it is never matched and
keeps its `user_id`. Because `_find_whatsapp_contact` matches every spelling,
**the user's OLD number still resolves to them after the change.** Deleting a
user has the same exact-match problem.

A correction to the research notes: `whatsapp_contacts` **does** have a unique
`(company_id, phone)` index (`company_id_1_phone_1`). The two spellings slip
past it because `15551234567` and `+15551234567` are different values.

**Phase 1 does not depend on this table.** START matches `users.phone`, and
every proactive send checks that the opt-in phone is still the phone on the
user record. So an old number cannot receive a proactive DM after a phone
change. The DM intents and the checklist permission check still use
`whatsapp_contacts`.

## 12. Hard delete of 638 Lafayette Avenue: the script, and why it was needed

**Script:** `backend/scripts/hard_delete_638_lafayette.py`
- It is a dry run by default.
- `--execute` also requires both project ids typed out exactly, plus
  `--i-know --reason --session`.
- Every write goes through `audited()`.
- It refuses if any premise is false:
  - the company has a `companies` document;
  - the company owns another project;
  - the group is bound elsewhere;
  - a project's `company_id` is not the expected one.
- The bot **leaves** `120363424969499174@g.us` first. The WaAPI action is
  `client/action/leave-group` (flag `--waapi-leave-action`). WaAPI's docs are
  not reachable from here, so that action name is **unverified**. If the leave
  fails, the script deletes nothing.
- Order of operations:
  1. Collect every R2 key the rows name.
  2. Delete those objects by key. If any delete fails, the script stops and
     keeps the rows.
  3. Delete the rows.
  4. Recount everything. Any count above 0 exits 4.
- `audit_logs` is kept.
- **It deliberately bypasses** the app's signed-records block and the 7-year
  retention brake. The dry run prints the counts of what those would have
  protected.

**Collections it covers.**
- Every collection in the database, filtered on `project_id ∈ targets OR
  company_id = 69e16add…`. Ids are matched as both string and ObjectId.
- Rows the app's cascade misses, keyed some other way:

| Collection | Matched on |
|---|---|
| `document_page_index`, `document_page_chunks`, `plan_records` | `file_id` |
| `plan_index_jobs` | `_id` = file id |
| `logbook_thumbnails`, `logbook_share_tokens`, `logbook_share_reads` | `logbook_id` |
| `report_number_counters` | `_id` = project id |
| `system_config` | per-project keys |
| WhatsApp group rows | `group_id` |
| `notification_log`, `digest_queue` | `metadata.project_id` / `permit_renewal_id` |
| `filing_jobs` | `permit_renewal_id` |

- Plus `$pull` from `users.assigned_projects` and
  `workers.safety_orientations`.

**What it does not cover, said plainly.**
- R2 objects that no row names. The prefix listing it prints is informational
  only. In this deployment `R2_ENDPOINT_URL` ends in the bucket name, so a
  listing returns the CORS document, not keys.
- Card-audit objects in a dedicated, object-locked bucket. Those deletes may be
  refused, and the script then stops before deleting any rows.

**Why a closed project was never hard-deleted.**
1. **Nothing deletes a project automatically.**
   - `DELETE /projects/{id}` is **tier 1, a soft mark**
     (`marked_for_deletion`); it deletes nothing.
   - The `soft_delete_purge` job never touches `projects`, and is off unless
     `SOFT_DELETE_PURGE_ENABLED` is set.
   - Recording a completion ("closing" a project) writes
     `job_completion_date` and deletes nothing.
2. **Tier 2, `DELETE /projects/{id}/hard-delete`** (platform operator plus the
   typed name), is manual, and it refuses:
   - any project with filed or locked logbooks, or any signature events;
   - (`retention_refusal`) a completed project until completion + 7 years;
   - (`retention_refusal`) a project with no completion, unless
     `no_completion_attested` is set.
3. **When it does run, it misses collections.** Its cascade
   (`_PROJECT_OWNED_COLLECTIONS`) matches the **string** id only, and does not
   include:
   - `plan_records`, `plan_index_jobs`
   - `dropbox_sync_runs`, `worker_project_trades`, `hot_work_days`
   - `logbook_share_reads`, `notification_preferences`
   - `predicted_events`, `prediction_outcomes`, `vision_calls`
   - `report_number_counters`
   - bot WhatsApp rows keyed by `group_id`

   Its R2 prefix sweeps delete 0 objects (the endpoint issue above), so
   logbook photos, report derivatives and card-audit objects leak.
4. **Deleting a company (`DELETE /owner/companies/{id}`) removes only `users`
   and the `companies` row.** That is how `69e16add…` ended up as a
   `company_id` with no company: its projects, `whatsapp_groups` and contacts
   stayed behind.

**Were other closed projects left behind the same way?** That cannot be
answered from code. Run these read-only queries:

```js
// Projects whose company has no companies document
db.projects.aggregate([{$lookup: {from: "companies", let: {c: "$company_id"},
  pipeline: [{$match: {$expr: {$eq: [{$toString: "$_id"}, {$toString: "$$c"}]}}}], as: "co"}},
  {$match: {co: {$size: 0}}}, {$project: {name: 1, address: 1, company_id: 1, job_completion_date: 1, marked_for_deletion: 1}}])
// Projects with no company_id at all
db.projects.find({$or: [{company_id: {$exists: false}}, {company_id: null}, {company_id: ""}]}, {name: 1, address: 1})
// Marked for deletion, or completed, and still present
db.projects.find({$or: [{marked_for_deletion: true}, {job_completion_date: {$nin: [null, ""]}}, {is_deleted: true}]},
  {name: 1, company_id: 1, marked_for_deletion: 1, marked_at: 1, job_completion_date: 1, is_deleted: 1})
// WhatsApp groups whose company has no companies document
db.whatsapp_groups.aggregate([{$lookup: {from: "companies", let: {c: "$company_id"},
  pipeline: [{$match: {$expr: {$eq: [{$toString: "$_id"}, {$toString: "$$c"}]}}}], as: "co"}},
  {$match: {co: {$size: 0}}}, {$project: {wa_group_id: 1, company_id: 1, project_id: 1, active: 1}}])
```

## 13. Proposed cleanups (proposals only; nothing has been run)

Run the reference checks first. Each proposal assumes those checks come back
as described.

**Shared helper:**
```js
function idsOf(v){ const a=[String(v)]; try{ a.push(ObjectId(String(v))) }catch(e){} return {$in:a}; }
```

### a. `whatsapp_contacts` 6aa0e7c28cb050f05e39ff6f (wrong phone on Meilich Friedman)

**What references it:**
- Nothing stores a contact `_id`.
- A contact row resolves by **phone** to its `user_id`.

**Checks:**
```js
const c = db.whatsapp_contacts.findOne({_id: ObjectId("6aa0e7c28cb050f05e39ff6f")}); printjson(c);
printjson(db.users.findOne({_id: idsOf(c.user_id)}, {name: 1, email: 1, phone: 1, company_id: 1, role: 1, is_deleted: 1}));
print("company exists:", db.companies.countDocuments({_id: idsOf(c.company_id)}));
const d = String(c.phone).replace(/\D/g, ""); const v = [d, "+" + d];
if (d.length == 11 && d[0] == "1") { const b = d.slice(1); v.push(b, "+" + b, "+1" + b); } else if (d.length == 10) { v.push("1" + d, "+1" + d); }
printjson(db.whatsapp_contacts.find({phone: {$in: v}}, {company_id: 1, user_id: 1, phone: 1}).toArray());  // anyone else on this number?
printjson(db.users.find({phone: {$in: v}}, {name: 1, company_id: 1, role: 1}).toArray());                   // whose number is it really?
print("pending groups added by it:", db.whatsapp_pending_groups.countDocuments({added_by_phone: {$in: v}}));
print("opt-ins on it:", db.whatsapp_optins.countDocuments({phone: d}));
```

**Proposed write.** This mirrors what the app itself does when a phone
changes: unlink, don't delete.
```js
db.whatsapp_contacts.updateOne({_id: ObjectId("6aa0e7c28cb050f05e39ff6f")}, {$set: {user_id: null}})
```
If his correct number should resolve, and his company's WhatsApp is active,
re-save his phone in the app (Settings or admin edit). The app writes the
correct `+E164` row itself, so nothing is hand-written.

### b. 8 Walworth duplicates 6a5c3d8afc53e22fc785b30c, 6a5e145ac7ac7a6451aa2d25

**Checks:** run this for each id, and for the 8 Walworth project you are
keeping, so you can compare the counts.
```js
const PID = "<id>"; const P = idsOf(PID);
printjson(db.projects.findOne({_id: P}, {name: 1, address: 1, company_id: 1, created_at: 1, marked_for_deletion: 1, job_completion_date: 1, legal_hold: 1, no_completion_attested: 1}));
print("filed logbooks:", db.logbooks.countDocuments({project_id: P, $or: [{status: "submitted"}, {is_locked: true}]}));
print("signature_events:", db.signature_events.countDocuments({project_id: P}));
["checkins","logbooks","daily_logs","dob_logs","project_files","permit_renewals","whatsapp_groups","whatsapp_messages",
 "plan_records","plan_index_jobs","document_page_index","notification_preferences","site_devices","nfc_tags",
 "subcontractors","material_requests","report_emails","reports"].forEach(c => { const n = db[c].countDocuments({project_id: P}); if (n) print(c, n); });
print("users.assigned_projects:", db.users.countDocuments({assigned_projects: P}));
print("workers.safety_orientations:", db.workers.countDocuments({"safety_orientations.project_id": P}));
```

**Proposed action**, if a duplicate holds no filed logbooks, no signatures
and no data worth keeping: use the app's own tier-2 path. It is audited,
needs the platform-operator flag and the typed project name, and enforces the
retention brake:
```
DELETE /api/projects/<id>/hard-delete?confirm_name=<the project's name>
```
- If it refuses on retention because a duplicate has no completion: set
  `no_completion_attested` from the admin screen first. Do not hand-edit it.
- If the checks show rows in `plan_records`, `plan_index_jobs` or
  `notification_preferences`: the app path leaves those behind (item 12, point
  3). They need a follow-up:
  ```js
  db.plan_records.deleteMany({project_id: P}); db.plan_index_jobs.deleteMany({project_id: P});
  db.notification_preferences.deleteMany({project_id: P})
  ```

### c. Old 588 Thomas 69f90c3209947c4967c8074f

**Checks:** run the same project checks as (b). Also confirm that no active
WhatsApp group still points at it, and that the current 588 Thomas project is
a different id:
```js
db.whatsapp_groups.find({project_id: idsOf("69f90c3209947c4967c8074f")}, {wa_group_id: 1, active: 1, company_id: 1})
db.projects.find({name: /588 Thomas/i}, {name: 1, company_id: 1, created_at: 1})
```

**Proposed action:** the same tier-2 app path as (b).
- If an active group still points at the old id: re-link that group to the
  current project from the app first (pending-group link, or the code link).
  Only then delete the old project.
- The `whatsapp_groups` row is in the app's cascade, so deleting the project
  removes the binding. The bot would then treat the chat as an unlinked
  group.
