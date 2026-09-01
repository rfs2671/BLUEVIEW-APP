# CP rebuild — Phase A research

Read-only research. **No source file was created or modified in Phase A.** This
document is the only artifact produced.

Six parallel read-only agents (no Write/Edit tools). Their findings are merged
below. Claims marked **[V]** were independently re-verified by the orchestrator
against source after the agent reported them; claims marked **[U]** are
agent-reported and NOT independently verified. Nothing here is asserted without
a `file:line`.

No production database was touched. Operator queries are in §1.5 for the
operator to run.

---

## 0. BLOCKER — the approved spec does not exist

The task names `docs/specs/activity-sequence-rules-v2.pdf` as "operator-approved
and the authority on activity sequencing."

**[V] It does not exist, and never has.**

| Check | Result |
|---|---|
| `docs/specs/` directory | does not exist |
| `find . -iname "*.pdf"` (excl. `node_modules`) | zero results |
| `find . -iname "*activity-sequence*" -o -iname "*sequence-rules*"` | zero results |
| `git ls-files \| grep -i "\.pdf$"` | zero results |
| `git log --all --oneline -- '*specs*'` | zero commits |
| `git log --all --diff-filter=A --name-only \| grep -i "\.pdf$"` | zero — **no PDF has ever been committed on any branch** |

`docs/` contains only: `architecture/`, `audits/`, `design/`, `features/`,
`investigations/`, `operations/`, `runbooks/`, `coi-retention-guarantee.md`.

**Consequence:** no construction-sequencing rule content can be authored. Agent 5
was scoped to codebase feasibility only and explicitly forbidden from inventing
rules. **Phase B Step 3 has no authority to build against.** See §5 and UNKNOWNS.

---

## 1. COMPANY / SUBCONTRACTOR DATA REALITY (Agent 1)

### 1.1 There are zero subcontractor foreign keys

**[V]** `subcontractor_id` and `subcontractorId` return **zero hits** across
`backend/` and `frontend/`. The 8 `sub_id` hits are all route path parameters on
the admin CRUD (`backend/server.py:5428`–`5459`).

| Entity | FK? | Evidence |
|---|---|---|
| Worker | **absent** | `WorkerCreate` `backend/server.py:2022-2027` — `company: str` only. `company_id` (`:2035`) is the GC tenant, set from `get_user_company_id` (`:10373`) / `project.get("company_id")` (`:9490`) |
| Check-in row | **absent** | insert dicts `:9733-9782`, `:10122-10143`, `:10471-10487`, `:10564-10580` |
| Activity row | **absent** | `EMPTY_ACTIVITY` `frontend/app/logbooks/daily_jobsite.jsx:98-105` = `{crew_id, company, num_workers, work_description, work_locations, photos[]}` |
| Observation row | **absent — and no company at all** | `EMPTY_OBSERVATION` `daily_jobsite.jsx:107-112` = `{description, responsible_party, remedy, corrected_immediately}` |
| Photo | **absent** | built at `daily_jobsite.jsx:501`, `:554`; company is inherited *positionally* from the parent activity |
| Worker enrollment | **absent** | `backend/card_audit.py:278` — `sub_name: str  # denormalized from project trade_assignments` |
| `daily_logs.subcontractor_cards[]` | **absent** | `backend/server.py:2144`, `:2178` — untyped `Optional[List[Dict]]` |

### 1.2 The subcontractor entity is orphaned

**[V]** `db.subcontractors` exists with full CRUD (`backend/server.py:5392-5464`)
and a unique email index (`:28548`). But:

- **`assigned_projects` is written exactly once**, as `[]` at
  `backend/server.py:5418`. `ALLOWED_SUB_FIELDS` (`:5437`) =
  `{name, company_name, email, phone, trade, license_number, insurance_info, password}`
  — **`assigned_projects` is not in it**, so the PUT cannot set it either. The
  subcontractor→project link is permanently empty by construction.
- **Zero frontend callers.** `admin/subcontractors` appears **0 times** in
  `frontend/app` + `frontend/src`; there is no `subcontractorsAPI` in
  `frontend/src/utils/api.js`. No screen creates, lists, or edits a subcontractor.
- **[U]** `workers_count` is written once as `0` (`:5417`) and never incremented.

**The real project↔sub link** is an embedded string array on the project:
`trade_assignments: [{trade, company}]`, built at `backend/server.py:9176-9178`
and `:10005-10007`, edited via a free `TextInput` in
`frontend/app/project/[id]/trades.jsx:138`, `:171-177` — which never queries the
subcontractor collection.

> **Scoping consequence for Step 1a.** This is not "add an FK to an existing
> relationship." The entity the FK would point at has no UI to populate it, no
> project linkage, and no product reader. Step 1a is: build the relationship and
> its admin surface, *then* migrate strings onto it.

### 1.3 Five spellings for one concept

**[U]** `company`, `company_name`, `worker_company`, `sub_name`, `workerCompany`
— across `workers`, `checkins`, `logbooks.data.*`, `worker_enrollments`,
`daily_logs.subcontractor_cards[]`, `projects.trade_assignments[]`.

**[U]** The four `checkins` insert sites disagree with each other: `:9737`/`:9739`
and `:10126`/`:10128` write **both** `company` and `worker_company`; `:10474` and
`:10567` write **only** `worker_company`. Readers coalesce defensively
(`:22144`, `:22179`).

Which forms carry company as text: `daily_jobsite` (per activity row),
`toolbox_talk` (header + per attendee), `preshift_signin` (header + per worker),
`osha_log` (per entry), `subcontractor_orientation` (`worker_company`). The other
six forms have **no** company field at all.

### 1.4 Normalization is inconsistent — and one divergence is a live bug

**[V]** Check-in matches the roster case-insensitively via `_roster_key`
(`.strip().casefold()`, `backend/server.py:9344-9352`), whose docstring calls
itself "the ONE roster-match normalization rule":

```python
# backend/server.py:9447-9448
allowed_pairs.add((_roster_key(t), _roster_key(c)))
submitted_pair = (_roster_key(trade), _roster_key(company))
```

But **assign-trade compares raw tuples**:

```python
# backend/server.py:10809
if (trade, company) not in allowed_pairs:
    raise HTTPException(status_code=400, ...)
```

A worker admitted at the gate under `"ACME Drywall"` against a roster entry
`"Acme Drywall"` will **400 when the CP tries to assign their trade** — and
`/logbooks/review` is exactly where the CP resolves `needs_trade_assignment`.
This is the mechanism the "pre-fill who was on site" goal depends on.

**[U]** Other divergences: `/checkin/submit` matches on `.lower()` only
(`:10023-10024`); dedupe/bucket keys use `.lower()` with no strip (`:15084`,
`:15131`, `:15188`, `:15279`, `:15306`).

### 1.5 Operator queries — RUN THESE YOURSELF

Not run by any agent; no Atlas access. Copy-pasteable. Change the DB name.

```javascript
use('blueview');   // <-- change to your actual database name
```

**Distinct company values + counts**

```javascript
// workers
db.workers.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $group: { _id: "$company", n: { $sum: 1 } } },
  { $sort: { n: -1, _id: 1 } }
]);

// checkins — unified across BOTH spellings, mirroring server.py:22144
db.checkins.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $project: { co: { $ifNull: [ "$worker_company",
                     { $ifNull: [ "$company", "$company_name" ] } ] } } },
  { $group: { _id: "$co", n: { $sum: 1 } } },
  { $sort: { n: -1, _id: 1 } }
]);

// checkin docs that disagree with themselves
db.checkins.countDocuments({
  is_deleted: { $ne: true },
  worker_company: { $exists: true }, company: { $exists: true },
  $expr: { $ne: [ "$worker_company", "$company" ] }
});

// checkin docs missing `company` entirely (the :10474 / :10567 insert paths)
db.checkins.countDocuments({ is_deleted: { $ne: true }, company: { $exists: false } });

// daily_jobsite activity rows
db.logbooks.aggregate([
  { $match: { log_type: "daily_jobsite", is_deleted: { $ne: true } } },
  { $unwind: "$data.activities" },
  { $group: { _id: "$data.activities.company", n: { $sum: 1 } } },
  { $sort: { n: -1, _id: 1 } }
]);

// the authoritative roster
db.projects.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $unwind: "$trade_assignments" },
  { $group: { _id: "$trade_assignments.company", n: { $sum: 1 },
              projects: { $addToSet: "$name" } } },
  { $sort: { n: -1, _id: 1 } }
]);
```

**Collision detection — applies the exact `_roster_key` rule (strip + lower)**

```javascript
// Any group with >1 raw spelling would collide under normalization.
// Run per collection; this is the workers variant.
db.workers.aggregate([
  { $match: { is_deleted: { $ne: true }, company: { $type: "string" } } },
  { $project: { raw: "$company", key: { $toLower: { $trim: { input: "$company" } } } } },
  { $group: { _id: "$key", variants: { $addToSet: "$raw" }, total: { $sum: 1 } } },
  { $addFields: { variantCount: { $size: "$variants" } } },
  { $match: { variantCount: { $gt: 1 } } },
  { $sort: { total: -1 } }
]);
```

**Which worker companies are absent from every project roster** (drives the
Step 1a backfill's unmatched report)

```javascript
const rosterKeys = new Set(
  db.projects.aggregate([
    { $match: { is_deleted: { $ne: true } } },
    { $unwind: "$trade_assignments" },
    { $project: { k: { $toLower: { $trim: { input: "$trade_assignments.company" } } } } }
  ]).toArray().map(d => d.k).filter(Boolean)
);
db.workers.aggregate([
  { $match: { is_deleted: { $ne: true }, company: { $type: "string", $ne: "" } } },
  { $project: { raw: "$company", key: { $toLower: { $trim: { input: "$company" } } } } },
  { $group: { _id: "$key", variants: { $addToSet: "$raw" }, n: { $sum: 1 } } },
  { $sort: { n: -1 } }
]).toArray().filter(d => !rosterKeys.has(d._id));
```

**UNASSIGNED sentinel audit** (sentinel set at `backend/server.py:9458-9462`,
`:9471-9474`; rendered "Pending assignment" by `_display_sub_company` `:15537-15547`)

```javascript
db.workers.countDocuments({ is_deleted: { $ne: true }, company: /^\s*unassigned\s*$/i });
db.checkins.countDocuments({ is_deleted: { $ne: true }, needs_trade_assignment: true });
```

Also available in the agent transcript: `worker_enrollments.sub_name`,
`daily_logs.subcontractor_cards[]`, `subcontractors.company_name`,
`preshift_signin`/`toolbox_talk`/`osha_log`/`subcontractor_orientation` variants.

---

## 2. CHECK-IN TRUTH (Agent 2)

### 2.1 Four insert paths, not one

**[U]** `checkins` is written at `backend/server.py:9784`
(`register-and-checkin`), `:10145` (`checkin/submit`), `:10489` (`POST /checkins`),
`:10582` (`POST /checkin`), plus an offline sync push at `:3462` that inserts
**client-authored rows with client timestamps** (`:3444`).

**Only `register_and_checkin` writes** `sst_*`, `cert_cleared`,
`needs_trade_assignment`, `toolbox_talk_*`, or presence evidence. Rows from the
other three are indistinguishable from resolved ones.

### 2.2 What the backend can answer for project+date with no CP input

| Question | Verdict | Evidence |
|---|---|---|
| Which workers present | **PARTIAL** | Every insert writes `worker_id`/`worker_name`/`check_in_time`. But a cert-blocked worker is **never inserted** — early return at `:9662-9669` precedes the insert at `:9784` |
| Company / subcontractor | **PARTIAL** | Free string from `worker.get("company")`; literally `"UNASSIGNED"` on the no-roster and not-listed branches (`:9458-9462`, `:9471-9474`) |
| Trade | **PARTIAL** | Same source; `needs_trade_assignment` (`:9756`) marks it unresolved. Resolution needs human action via `assign-trade` (`:10744`) |
| SST/OSHA status | **PARTIAL (path A) / UNPOPULATED (B, C, D)** | `sst_card_number`/`sst_expiration`/`sst_status`/`sst_unknown_reason` exist only at `:9759-9763`. `sst_status` has an explicit `unknown` bucket (`:9692-9701`) |
| Check-in time | **RELIABLE** | Server-generated `datetime.now(timezone.utc)` (`:9488`→`:9746`); EST day ranges for queries (`:15015-15024`). Caveat: client-supplied on the sync path (`:3444`) |
| **Check-out time** | **UNPOPULATED** | see §2.3 |

**[V] Staleness bug.** For a returning worker the DB is updated at
`backend/server.py:9560`, but the in-memory `worker` dict is never re-read —
**zero** `worker = await db.workers.find_one` calls between `:9560` and the
`checkin_record` literal at `:9733`. So `:9737-9740` freeze the **pre-update**
company/trade. **A worker who switches subcontractors is recorded under the old
one** — which directly undercuts deriving a `subcontractor_id` from the check-in row.

**[U]** `cert_cleared` is always `True` on any row that exists (blocked workers
return before insert), so it carries no discriminating information.

### 2.3 Checkout: reachable in code, unreachable in product

**[V]** `POST /api/checkins/{checkin_id}/checkout` at `backend/server.py:10599`
sets a real timestamp at `:10604`. Full chain:

- wrapper `frontend/src/utils/api.js:427-430`
- hook `frontend/src/hooks/useCheckIns.js:14-16`, exported `:61`
- three screens import the hook: `app/nfc/index.jsx:28` (uses `createCheckIn`
  `:45`), `app/index.jsx:41` (`getActiveCheckIns` `:235`), `app/project/[id].jsx:64`
  (`getActiveCheckIns` `:194`)

**None destructures `checkOut`.** `check_out_time` is written as literal `None`
at all four inserts (`:9747`, `:10136`, `:10480`, `:10573`). **[U]** The
ON-SITE/DONE badges in `app/workers.jsx:343-356` and `app/site/checkins.jsx:483-496`
are therefore permanently "on-site" for anyone who checked in that day.

### 2.4 `checkins-today` contract

**[U]** `GET /api/logbooks/project/{project_id}/checkins-today` —
`backend/server.py:14994-15208`. Carries `require_project_access` (`:14995`).
Returns a **bare JSON array** (`:15208`), no envelope.

Three passes with **non-uniform** shapes:

- **Pass 1** (new gate system, `:15097-15108`): `worker_id` (the *enrollment* id),
  `worker_name`, `company` (from `sub_name`), `trade`, `check_in_time`,
  `osha_number`, `certifications: []` (hardcoded), `worker_signature: None`
  (hardcoded), `signin_id`, `source: "gate_checkin"`.
  **Missing:** `toolbox_talk_confirmed`, `blocked`, `cert_cleared`, `blocks`.
- **Pass 2** (legacy `checkins`, `:15136-15159`): adds `toolbox_talk_confirmed`
  (`:15155`) and `toolbox_talk_confirmed_at`. `osha_number` and `certifications`
  come from the **live worker doc** (`:15141-15142`), not the check-in row.
  **Missing:** `blocked`, `cert_cleared`, `blocks`.
- **Pass 3** (turned-away workers from `compliance_alerts`, `:15193-15205`): adds
  `blocked: True`, `cert_cleared: False`, `blocks[]`. **Missing:** `toolbox_talk_*`.

**Hazards [U]:** no `sst_*` field is ever returned — the frozen per-check-in
compliance snapshot written at `:9672-9677` is read by nothing here. Two silent
`except` branches (`:15109-15110`, `:15119-15120`) return **HTTP 200 with a
partial roster**. Dedupe key is `(name.lower(), company.lower())` — two workers
with the same name at the same sub collapse. Pass 2 keeps one row per `worker_id`
with **no `.sort()`** (`:15114-15118`), so which same-day check-in survives is
undefined. Limits truncate silently (1000/500/500). N+1 worker read at `:15128`.

### 2.5 Consumers

**[U]** Exactly three screens call it (`logbooksAPI.getCheckinsForDate`,
`frontend/src/utils/api.js:875-879`):

- `osha_log.jsx:98` — filters `c.blocked` (`:132`), reads `c.certifications`
  (`:150`) using **`cert.expiry`**
- `preshift_signin.jsx:116` — `buildWorkerList` `:168-183`; **no `blocked` filter**
- `toolbox_talk.jsx:170` — filters `c.blocked !== true && c.source !== 'cert_block'`
  (`:194`)

`daily_jobsite.jsx:272` deliberately uses `getDailyHeadcount` instead
(`GET /api/projects/{id}/daily-headcount`, `backend/server.py:15211`).

**[V] Two live bugs here:**

1. **OSHA log expiration never autofills.** `osha_log.jsx:158` reads
   `cert.expiry`; the backend writes `expiration_date`
   (`backend/server.py:1779`, `:1834`). The string `"expiry"` appears **0 times**
   as a key in `server.py`. The CP retypes every expiry by hand.
2. **Pre-shift auto-adds turned-away workers.** `preshift_signin.jsx` contains
   `blocked` **0 times** and `cert_block` **0 times** (control:
   `toolbox_talk.jsx` has 1). A cert-blocked worker who never got on site is
   auto-filled onto the signed pre-shift roster.

**[U]** Because `toolbox_talk_confirmed` exists only on Pass 2 rows, every
gate-system (Pass 1) attendee renders `gate_confirmed: false` regardless of what
they tapped.

---

## 3. LOGBOOK WRITE AND READ PATHS (Agent 3)

### 3.1 One model, one endpoint, no per-type schema

**[V]** All 11 forms hit the same surface:

```python
# backend/server.py:2491-2498
class LogbookCreate(BaseModel):
    project_id: str
    log_type: str
    date: str                    # YYYY-MM-DD
    data: Dict[str, Any]         # flexible per log type
    cp_signature: Optional[Dict] = None
    cp_name: Optional[str] = None
    status: str = "draft"
```

`create_logbook` `:14371-14510` writes `data.data` verbatim (`:14449` upsert,
`:14473` insert); `update_logbook` `:14512-14562` at `:14540-14541`.

Per-form `data` keys and nested row constructors **[U]** (all
`frontend/app/logbooks/`):

| Form | `data` keys | Nested rows |
|---|---|---|
| `daily_jobsite` | `project_address, weather, weather_temp, weather_wind, general_description, activities, equipment_on_site, checklist_items, observations, visitors_deliveries, time_in, time_out, areas_visited` (`:739-753`) | `EMPTY_ACTIVITY` `:98-105`; `EMPTY_OBSERVATION` `:107-112` |
| `preshift_signin` | `company, project_location, workers, total_count` (`:209-214`) | `EMPTY_WORKER` `:33-43` |
| `toolbox_talk` | `location, company_name, type_of_work, meeting_time, performed_by, checked_topics, attendees` (`:292-300`) | `addAttendee` `:269-281` |
| `osha_log` | `entries` (`:200`) | `EMPTY_ENTRY` `:28-37` |
| `subcontractor_orientation` | `worker_id, worker_name, worker_company, worker_trade, osha_number, orientation_number, checklist, completed_at, worker_signature, language_provided` (`:472-483`) | — |
| `scaffold_maintenance` | `general_info, answers` (`:194`) | 19 questions `:40-60` |
| `concrete_operations` | `pour_location, concrete_supplier, mix_design, volume_ordered, slump_tests, formwork_checklist, weather_conditions, temperature` (`:171-180`) | `EMPTY_SLUMP_TEST` `:33-37` |
| `crane_operations` | `crane_type, crane_id, operator_name, operator_license, pre_operation_checklist, load_entries` (`:174-181`) | `EMPTY_LOAD_ENTRY` `:42-47` |
| `excavation_monitoring` | `excavation_depth, soil_type, adjacent_buildings, vibration_threshold, vibration_current, vibration_over_threshold, protection_system, groundwater_observed, atmospheric_testing` (`:184-194`) | `EMPTY_ADJACENT_BUILDING` `:27-31` + a `delta` key added at save (`:180-183`) |
| `hot_work` | `work_type, location, worker_name, worker_cert_number, start_time, end_time, fire_watch_end_time, fire_watch_name, precautions` (`:189-199`) | — |
| `ssc_daily_safety_log` | 13 keys (`:192-206`) | — |

**[U]** `subcontractor_orientation` has a **second writer** that bypasses
`create_logbook` entirely — the check-in endpoint inserts orientation docs
directly into `db.logbooks` at `backend/server.py:9572-9596`.

### 3.2 Validation today: none on content

**[V]** `grep -cE '@field_validator|@validator|@model_validator' backend/server.py`
→ **0**. No Pydantic validators exist anywhere in `server.py`.

**[U]** No `REQUIRED_FIELDS` / `required_fields` / `validate_logbook` /
per-`log_type` schema exists (the only hits are unrelated:
`backend/lib/statistical_engine/baselines.py:307`).
`backend/lib/logbook/schema.py` is **not** a validator for these forms — its
consumers all query `db.logbook_entries`, never `db.logbooks`.

**[U]** `log_type` is never validated against a whitelist —
`logbook_timing_class` defaults unknown types to `"end_of_day"`
(`:2687-2688`) rather than rejecting. `date` is a bare `str` with no format check
on create.

**[V] `finalize_logbook` (`:14565-14598`) performs no completeness check.** It
validates 404, CP scope (403), and idempotency-if-locked — then sets
`is_locked: True`. It never reads `data` and never requires `cp_signature`.
**A logbook with `data: {}` can be finalized and locked immutable.**

**[U]** The only content requirement in the whole logbook path is `amend`'s
non-empty `reason` (`:14610-14612`). Client-side guards exist only in
`daily_jobsite.jsx:861-864` and `subcontractor_orientation.jsx:461-464`; neither
is enforced server-side.

**Validation chokepoints [U]:** `LogbookCreate` `:2491`, `LogbookUpdate` `:2500`,
`create_logbook` upsert `:14446-14458` and insert `:14467-14497`,
`update_logbook` `:14540-14541` and submit transition `:14550-14557`,
`finalize` `:14565`, `amend` `:14601`, the orientation bypass `:9572-9596`, and
the client drain `frontend/src/utils/draftSync.js:68-101`.

### 3.3 Consumers — and the read path is missing for most forms

**[V] The per-type PDF is content-free for 8 of 11 forms.**
`generate_single_logbook_html` (`backend/server.py:11984-12209`) branches on only
three types — `daily_jobsite` (`:12029`), `toolbox_talk` (`:12099`),
`preshift_signin` (`:12144`) — and the `else` at `:12179-12181` emits only
`bold_para("Status", ...)`.

**[V] The kiosk screen is the same.** `frontend/app/site/logbooks.jsx:629-634`:

```js
if (log.log_type === 'daily_jobsite')   return renderDailyJobsite(log);
if (log.log_type === 'toolbox_talk')    return renderToolboxTalk(log);
if (log.log_type === 'preshift_signin') return renderPreshiftSignin(log);
return <Text style={s.logField}>No data available</Text>;
```

**On the screen an inspector reads on site, 8 of 11 compliance logs show
"No data available."**

> **Scoping consequence for Step 5.** "Port the remaining 10 forms onto the same
> pattern" is not a UI refactor — for 8 of them the read path does not exist.

**[U] `generate_combined_report` (`:15687-16806`) is the one full consumer.**
Per-type key lists are in the agent transcript; notable never-read fields:
`toolbox_talk.type_of_work`; `preshift_signin.company`, `.project_location`,
`.total_count`, `workers[].signed`, `.worker_signature`, `.auto_filled`;
`osha_log entries[].date`, `.blocked`, `.blocks`;
`subcontractor_orientation.checklist`, `.osha_number`, `.orientation_number`,
`.language_provided`.

**[U] Other consumers:** `GET /reports/logbook/{id}/pdf` `:11947`;
**public, unauthenticated** photo endpoint `:14178-14223` (positional
`data.activities[ai].photos[pi]`); `_enhance_logbook_photos` `:160-208` (same
positional path); `get_report_preview` `:16840` (envelope only);
`GET /logbooks/project/{pid}/submitted` `:16910`; admin viewer `:17020`;
`get_logbook_notifications` `:14673` (reads `data.attendees[].worker_id` only);
`nightly_compliance_check` `:19620` (existence only).

### 3.4 Phantom keys — read by renderers, written by nobody

**[V] `crew_name`.** Two of three renderers read a key that is never written:

| Reader | Key | Correct? |
|---|---|---|
| `backend/server.py:12041` (per-logbook PDF) | `crew_name` | ✗ never written |
| `frontend/app/site/logbooks.jsx:445` (kiosk) | `act.crew_name` | ✗ never written |
| `backend/server.py:15811` (combined report) | `crew_id` | ✓ |

The CP types into `crew_id` (`daily_jobsite.jsx:99`, `:316`, `:1026-1027`). The
crew column is blank in the per-logbook PDF **and** on the inspector screen.

**[V, partial] `superintendent_signature`.** Read by the kiosk
(`site/logbooks.jsx:485`); `daily_jobsite.jsx` writes it **0 times** — `:753`
explicitly omits superintendent fields. Every write in the repo targets the
separate `daily_logs` collection. *(Agent 3 cited two further backend readers at
`:12074` and `:15848`; my grep output was truncated, so that part is
**unverified**.)*

### 3.5 Blast radius of changing the activity row

**Adding `subcontractor_id` — additive, nothing breaks, but [U]:**
- The `daily_jobsite` report branch is hardcoded (`:15809-15817`), so a new key
  is **silently invisible** in the report; only unhandled `log_type`s hit the
  generic dump (`:16681-16693`).
- **Two independent row constructors** must both change: `EMPTY_ACTIVITY`
  (`:98-105`) and the autofill seed (`:315-327`).
- No migration, no server default — existing rows won't have it.
- The seeding source has no id to give: `/projects/{id}/daily-headcount` returns
  only `{sub_name, trade, worker_count_today}` (`backend/server.py:15222`,
  built `:15286`, `:15313`).
- Photos are indexed **positionally** — any reorder/filter of `activities[]`
  invalidates already-emailed photo URLs (`:15791`).

**[V] Removing `company` produces an affirmatively wrong statement, not a blank.**
`_display_sub_company(None)` returns **`"Pending assignment"`**
(`backend/server.py:15537-15547`). Every activity row in every emailed report and
PDF would read "Pending assignment"; the kiosk renders `"Unknown"`
(`site/logbooks.jsx:445`). **[U]** Six read sites break; **no test covers any of
them** — the only test touching activities
(`backend/tests/test_orientation_upsert_worker_key.py:257`, `:265`) uses
`crew_id` and asserts on `weather`. Historical documents are never migrated —
reports render live from stored `data`.

---

## 4. FRONTEND DESIGN SYSTEM (Agent 4)

### 4.1 Tokens that exist

**[U]** `frontend/src/styles/theme.js` (248 lines): module-private `_dark`
(`:2-103`) and `_light` (`:105-194`) palettes — **not exported**. Exported:
`spacing` `:217-224` (`xs:4, sm:8, md:16, lg:24, xl:32, xxl:48`), `borderRadius`
`:226-233` (`sm:8, md:12, lg:16, xl:24, xxl:32, full:9999`), `typography`
`:235-245` (`sizes: xs:11, sm:14, md:16, lg:18, xl:24`, plus `hero/h1/h2/h3/body/small/label/stat`).
**No exported `shadows` group** — `shadow` exists only inside the private
palettes (`:23-28`, `:127-132`).

`semanticColors.js` (153 lines): `withAlpha(hex, opacity)` `:79-87`; `semantic`
`:97-119`, `chrome` `:124-128`, `border` `:130-134`, `surface` `:136-143`,
`text` `:145-150` — all **live getters** off the mutable `colors`.
Constants `STATE_FILL = 0.12`, `STATE_BORDER = 0.3` (`:94-95`).

`useTheme` is at `frontend/src/context/ThemeContext.js:43-47`; `colors` handed to
consumers is a deep JSON clone re-created per `themeKey` (`:34`).

### 4.2 [V] The mutable-`colors` mechanism has a key-leak bug

```python
# theme.js:197-205  (_deepAssign)
for (const key of Object.keys(source)) { ... target[key] = source[key]; }
# theme.js:209-214
export const colors = {};  _deepAssign(colors, _dark);
export function applyTheme(mode) { _deepAssign(colors, mode === 'light' ? _light : _dark); }
```

`_deepAssign` **only assigns — it never deletes**. `glass.cardGradientEnd` exists
only in `_light` (`:124`). So after `light → dark` it **persists with a stale
light value**, and `applyTheme('dark')` cannot remove it.

**[U]** `globalStyles.js:9` calls `StyleSheet.create` at import, freezing every
color to the dark palette. No CP screen imports it.

### 4.3 Literals in the CP screens (16 files)

**[U]** 175 hex total, of which **101 are `withAlpha()` arguments** — the
sanctioned token-helper idiom, not drift. The honest figure is **121 non-helper
literals**: 74 opaque hex + 47 raw `rgba()`. **Zero named CSS colors.**

Of 18 distinct opaque hex values, **9 already have exact token equivalents**
(`#3b82f6`, `#fff`, `#fbbf24`, `#f87171`, `#4ade80`, `#ef4444`, `#94a3b8`,
`#93c5fd`, `#000000`). Genuinely new: `#60a5fa`, `#06b6d4`, `#22d3ee`, `#8b5cf6`,
`#6b7280`, `#f59e0b`, `#f472b6`, `#ec4899`, `#10b981`.

**[V] Font sizes — 192 occurrences, 13 distinct:**

```
43 × 13   ← no token        31 × 14   ← sizes.sm
43 × 12   ← no token        25 × 11   ← sizes.xs
20 × 15   ← no token         8 × 16   ← sizes.md
 8 × 10   ← no token         5 × 20, 3 × 17, 2 × 32, 2 × 18, 1 × 48, 1 × 22
```

The two heaviest sizes (12 and 13, **86 occurrences**) have **no token**, while
`sizes.xl: 24` is used **zero** times. The existing scale covers 66/192 (34%).

**[U]** Radii: 17 literals, 9 distinct, only 1 occurrence maps to a token — the
gap is entirely at the small end (2–5px), below `sm: 8`. Spacing: 81 literals, 12
distinct; 34 already have an exact token; genuine gaps are the sub-4px micro-scale
and a nav-clearance constant written four ways (100 / 120 / 140 / `globalStyles.js:19`).
Shadows: exactly one declaration, `daily_jobsite.jsx:1475-1476`.

**[V]** `login.jsx` is the compliant reference — **0 color literals, 0 radius
literals, 3 font sizes**.

### 4.4 [V] i18n does not exist — but there is an unwired bilingual surface

No i18n directory, no `i18next`/`react-i18next`/`react-intl` in `package.json`,
zero `useTranslation`/`LanguageContext` occurrences outside `node_modules`.

Three independent hand-rolled EN/ES implementations, **no shared machinery**:

1. `backend/checkin.html:456-647` — `TRANSLATIONS`, **87 keys each**, lookup with
   fallback chain at `:653-654`.
2. `frontend/app/logbooks/review.jsx:57-160` — **47 keys each**; header comment at
   `:17` states the app has no i18n framework and this mirrors `checkin.html`.
   Toggle at `:361`.
3. **`frontend/src/components/SignaturePad.js:53-67`** — `SIG_STRINGS` with 5 keys
   each, selected by a `lang` prop defaulting to `'en'` (`:88`).

**[V] The SignaturePad Spanish is unreachable.** **13 screens render
`<SignaturePad>`; zero pass `lang=`.** The ES half is dead code today — on the
component where a legal signature is affirmed.

**[U]** `subcontractor_orientation.jsx:44-47` `LANGUAGE_LABELS` is a display map
for the `language_provided` **data field**, not UI localization.

### 4.5 Component inventory

**[U]** All 16 CP screens use `AnimatedBackground`, `GlassCard`, `GlassButton`,
`useToast`. `SignaturePad` + `LogbookLockBar` on all 11 forms. `GlassInput` only
in `login.jsx:8` and `settings.jsx:37` — **no logbook form uses it**.
`OfflineNotice` on 5 screens. `CameraCaptureModal` only in `daily_jobsite.jsx:24`.
`InfoTooltip` exists but **no CP screen uses it**. `GlassCard`, `GlassInput`,
`IconPod`, `InfoTooltip`, `Toast` all call `useTheme()` internally — the
components are theme-correct; the screens' inline literals are not.

---

## 5. SEQUENCE ENGINE FEASIBILITY (Agent 5)

### 5.1 [V] A rules-as-data sequence engine already exists

`backend/app/scheduling/` — **1,231 lines across 5 modules**:

```
aggregator.py 487 | engine.py 360 | graph_v1.py 172
project_model.py 136 | schedule_models.py 76
```

Wired at `backend/server.py:28344` (`model/aggregate`), `:28352` (`model`),
`:28365` (`model/confirm`), `:28385` (`model/unconfirmed`), `:28405`
(`schedule/generate`). Six test files:
`test_scheduling_engine.py`, `test_scheduling_endpoints.py`,
`test_project_model_aggregator.py`, `test_project_model_autotrigger.py`,
`test_project_model_endpoints.py`.

**[V] Its rule content is explicitly unsigned-off**, verbatim at
`backend/app/scheduling/graph_v1.py:3-11`:

> RULE CONTENTS PENDING NYC DOB DOMAIN-EXPERT SIGN-OFF — architecture stable,
> sequence VALUES PROVISIONAL. … Treat every node and edge as provisional until
> sign-off. The engine … is the stable part; these contents are data and are
> expected to change.

**[U]** It already has: ranking via edge-type-aware topological layering
(`engine.py:225` `_soft_rank_within`, `:246` `_layer`, `:291` `generate_schedule`)
with a documented determinism guarantee (`:8-16`); a `version` key
(`schedule_models.py:57`, `GRAPH_VERSION` `graph_v1.py:33`); a
`proposed`→`confirmed` provenance flow (`project_model.py:67-77`, `:123-136`);
non-blocking `schedule_input_warnings` (`engine.py:320-336`); and
`ScheduleCycleError` → HTTP 422 (`server.py:28419-28423`).

**[U] It has no path from `db.logbooks`.** `grep logbooks backend/app/scheduling/`
→ **zero hits**; `generate_schedule` is explicitly pure and reads nothing from
`db` (`engine.py:4-6`). The aggregator reads only `document_page_index`
(`aggregator.py:5-7`). Free-text `work_description`/`work_locations` have **no
normalizer** to any node id or trade vocabulary.

### 5.2 Prior-day query is feasible

**[U]** `backend/server.py:28596` creates
`logbooks{project_id:1, log_type:1, date:-1}` — a
`{project_id, log_type:"daily_jobsite", date:{$gte,$lte}}` range query is fully
index-backed and returns date-ordered without a sort stage. `date` is
`YYYY-MM-DD` (`:2494`, produced at `:9577`).

**No endpoint serves prior-day activity today.** `GET /logbooks/project/{id}`
filters `date` by **exact equality** (`:14301-14302`).
`GET /logbooks/project/{id}/submitted` (`:16910`) returns full `data` but with
**no date bound**, capped at 500. The only true date-range query
(`/projects/{id}/logbook/audit`, `:4503`) hits a **different collection**
(`logbook_entries`) and returns counts only.

**[U]** No index exists on `project_models`, `project_schedules`, or
`sequence_graph`; `load_latest_schedule` sorts unindexed (`engine.py:353-356`).

### 5.3 [V] `structural_system` does not exist

Nor `construction_type` nor `building_type`, anywhere in the repo.
`superstructure` and `framing` exist only as phase labels / scheduling node ids /
LLM enum strings.

**What does exist** on the project (`ProjectCreate` `backend/server.py:1466`):
`building_stories` `:1472`, `building_height` `:1473`, `footprint_sqft` `:1474`,
`has_full_demolition` `:1475`, `demolition_stories` `:1476`, `project_class`
`:1477`. Consumed by `get_required_logbooks` `:1148-1160` and `classify_project`
`:1108`.

**[U] Two latent defects here:** `adjacent_to_occupied` is *read* at `:1156` but
**declared on no model** — it can never be set through the API and is always
falsy. Registry conditionals `has_crane_permit` (`:2639`) and `has_excavation`
(`:2650`) are declared but **never evaluated**, so `crane_operations` can never
be marked required.

### 5.4 Rules-as-data storage precedent

**[U]** The repo's convention is **typed Python constants next to a pure
function**; if runtime identity is needed, Pydantic-modelled and upserted into
Mongo with a `version` key. Precedents: `LOGBOOK_TYPE_REGISTRY`
(`server.py:2537-2652`, served by `GET /logbook-types` `:14804`),
`LOGBOOK_TIMING_CLASS` (`:2670-2684`), `SPECIAL_INSPECTION_VOCAB`
(`project_model.py:33-63`), `build_graph_v1` → `upsert_seed_graph`
(`engine.py:340-345`, invoked `server.py:28416`), `db.feature_flags`
(`lib/feature_flags.py:139`).

**There is no file-based-config precedent** — no JSON/YAML config anywhere
outside test fixtures.

**Rule CONTENT cannot be authored until the operator supplies the approved PDF.**
No sequencing rule, ordering, precedence, or ranking heuristic was proposed,
inferred, or exemplified by any agent.

---

## 6. CONFLICTS

Ranked. Each is a place a proposed change collides with existing behavior.

### C1 — CRITICAL: Step 1a's premise is wrong about the subcontractor entity
The FK target has no UI, no project link (`assigned_projects` unsettable —
`server.py:5418` + `ALLOWED_SUB_FIELDS` `:5437`), and no product reader (0
frontend callers). §1.2. **Step 1a must be resized before approval.**

### C2 — CRITICAL: [V] `POST/PUT /api/daily-logs` have no tenant guard, and are the kiosk write path
`create_daily_log(log_data: DailyLogCreate, current_user)` `backend/server.py:11198-11199`
— `project_id` arrives in the **body**, no `require_project_access`, no
`require_approved`. `update_daily_log` `:11249-11252` loads by `_id` alone.
Client: `frontend/app/site/daily-logs.jsx:358`, `:362`.
Already an open finding: `docs/audits/followups.md:327-340` — *"A site device
registered to project A can write a daily log to project B."*
**[U]** `:11217-11220` inserts even when the project lookup returns `None`,
orphaning the row with no `company_id`.

### C3 — CRITICAL: [V] `GET /api/logbooks/{logbook_id}` returns any logbook to any authenticated user
`backend/server.py:14306-14311` — `find_one({"_id": to_query_id(logbook_id)})`.
No company, no project, no `is_deleted`, no guard. Every field Step 1a adds is
exfiltrated by ObjectId enumeration. Same class: `GET /reports/logbook/{id}/pdf`
`:11947` (also an unguarded CPU-bearing WeasyPrint render).

### C4 — CRITICAL: Step 3 duplicates an existing engine
§5.1. Two engines writing the same `sequence_graph` / `project_schedules`
collections is a correctness risk. **Decide: replace, or feed the existing one.**

### C5 — HIGH: [U] Step 2 validation vs. the documented 400-outage pattern
The repo already hit this and chose **mint, don't reject**:
`backend/server.py:14424-14432` — *"a 400 would break manual orientation creation
on the live site until a rebuild."* Compounding: `draftSync.js:102-105` has **no
retry cap** (contrast `offlineQueue.js:205-208` which caps at 3), so a
server-rejected draft stays pending forever and silently; and
`logbookDrafts.js:132-138` means a **finalized** legacy draft can never be
content-patched to add a newly-required field. **A legacy draft can become
permanently un-pushable.**

### C6 — HIGH: [U] A required `subcontractor_id` on check-in re-introduces a removed hard block
The live gate is entirely public/unauthenticated (`:9355`, `:9970`, `:10498`,
`:9193`) and every mitigation there is **fail-open by explicit design**:
`:9410-9412` (company deliberately not required), `:9450-9456` (*"a pure config
gap became a hard block on a real person"*), `:2932-2933` and `:3171-3177` (guards
bypassed so check-in "must never break").

### C7 — HIGH: Step 4's premise conflicts with §2.2/§2.4
"Pre-fill who was on site from gate check-in, locked and uneditable" rests on
data that is PARTIAL: company/trade may be `"UNASSIGNED"`, are **stale for
returning workers** (§2.2 [V]), and `checkins-today` can return HTTP 200 with a
silently partial roster. **Locking a field the CP cannot correct, over data the
system knows is unresolved, needs an operator decision.**

### C8 — HIGH: Step 5 is not a refactor — the read path is missing
8 of 11 forms have no PDF renderer and render "No data available" on the kiosk.
§3.3 [V].

### C9 — MEDIUM-HIGH: [U] `assigned_projects` is an authorization mint
`require_project_access` branch 4 (`:3214-3215`) honors it **cross-company**.
`POST /admin/users/{id}/assign-projects` (`:5352`) carries `require_approved`
only. `docs/audits/followups.md:305-323` rates this **SEV-0**. Any new
project-scoped endpoint inherits the hole.

### C10 — MEDIUM: [U] The public photo endpoint cannot be guarded
`GET /reports/logbook-photo/{id}/{ai}/{pi}` `:14178-14181` — no auth at all, and
`:14182-14188` documents it must never 404 (email reports). A per-photo
`subcontractor_id` becomes publicly enumerable by index.

### C11 — MEDIUM: [U] Offline drafts have no schema version and no migration hook
`writeDraft`'s merged object (`logbookDrafts.js:139-147`) has no `version` key;
there is no migration anywhere in `logbookDrafts.js` or `draftSync.js`.
`readDraft` returns exactly six fields (`:96-107`) — **anything else stored is
dropped on read**, and `draftSync.pushOne` rebuilds the body from four literals
(`:68-73`). **Design constraint: a new FK must live *inside* `data`, or
`readDraft`/`writeDraft`/`pushOne` must all change in lockstep.**

### C12 — MEDIUM: [U] Two daily-log surfaces, two backends
`frontend/app/logbooks/daily_jobsite.jsx` → `/api/logbooks` (nested `data`)
vs `frontend/app/site/daily-logs.jsx` → `/api/daily-logs` (flat payload,
`:320-341`). Rebuilding one does not rebuild the other; validation written for
one will reject the other. The kiosk log is also in `SKIP_LOG_TYPES`
(`draftSync.js:35`) so it **never auto-drains**.

### C13 — MEDIUM: [V] CI pins route-bucket counts
`backend/tests/test_tenant_isolation_writes.py:268-270` asserts
`TIER1_DESTRUCTIVE == 6`, `TIER2_SETTINGS == 6`, `TIER3_ACTIONS == 13`.
**[U]** `:249` and `:297` pin both guards on all 25 CLEAN_ROUTES via AST **and**
live dependant-tree walk. Any new guarded endpoint fails CI unless the constants
are bumped; refactoring guards to a router-level dependency fails the AST pin
even if runtime behavior is identical.

### C14 — MEDIUM: [U] OTA / runtimeVersion trap
`frontend/app.json:12-15` uses `"runtimeVersion": {"policy": "appVersion"}` with
`"version": "1.1.3"` (`:6`). `.github/workflows/ota-update.yml:3-12` triggers on
push to `main` **including `frontend/app.json`**. So a commit that bumps
`version` publishes an OTA with a runtimeVersion **no installed build matches** —
a silent no-op delivery that orphans every device.

### C15 — MEDIUM: [U] Step 4's camera work may force a native rebuild
`daily_jobsite.jsx` is the camera screen —
`react-native-vision-camera@^4.7.3` (`frontend/package.json:61`), config plugin
`frontend/app.json:90-99`, Android permissions `:129-140`. Touching the plugin
block or the permissions array = **native build, not OTA**. `expo-localization`
for Step 1b would likewise be native; `i18next`/`react-i18next` is pure JS and
OTA-safe.

### C16 — LOW-MEDIUM: [U] Kiosk surface is untestable in CI
`frontend/scripts/smoke-mount.cjs:67-83` mounts **no `/site/*` route**. Camera
interaction surfaces are listed "Unverified without a phone" at
`docs/audits/followups.md:412-416`.

### C17 — Pre-existing defects found in passing (not caused by the proposal)

| Defect | Status |
|---|---|
| OSHA log expiration never autofills — `osha_log.jsx:158` reads `cert.expiry`; backend writes `expiration_date`; `"expiry"` appears 0× as a key | **[V]** |
| Pre-shift auto-adds cert-blocked workers — `preshift_signin.jsx` has 0 occurrences of `blocked`/`cert_block` | **[V]** |
| Returning worker's company/trade is stale on the check-in row (`:9560` → `:9733`, 0 re-reads) | **[V]** |
| `assign-trade` raw-tuple match vs check-in's casefold — 400s on case mismatch | **[V]** |
| `crew_name` phantom in 2 of 3 renderers | **[V]** |
| Empty `data: {}` can be finalized and locked immutable | **[V]** |
| `theme.js` `_deepAssign` never deletes → `glass.cardGradientEnd` leaks stale light value into dark | **[V]** |
| SignaturePad ES strings unreachable — 13 users, 0 pass `lang=` | **[V]** |
| `superintendent_signature` read by kiosk, written by nobody | **[V, partial]** |
| `adjacent_to_occupied` read but declared on no model | **[U]** |
| `has_crane_permit` / `has_excavation` declared but never evaluated | **[U]** |
| Offline-synced photos lose `base64` → fail enhancement and 404 the public photo endpoint | **[U]** |
| `checkins-today` returns 200 with a silently partial roster on either pass failing | **[U]** |

---

## 7. UNKNOWNS

Things that must be answered by the operator, or verified before Phase B.

**U1 — The approved spec.** `docs/specs/activity-sequence-rules-v2.pdf` does not
exist and never has (§0). **Blocking for Step 3's rule content.** Supply the PDF
or its location.

**U2 — Replace or feed the existing engine?** `backend/app/scheduling/` already
does rules-as-data ranking, with its own unsigned-off banner (§5.1). Operator
decision required before Step 3. Note its rules are *also* awaiting DOB sign-off,
so it may be blocked on the same document.

**U3 — Is cross-company project assignment intended?** `require_project_access`
branch 4 allows it (`:3214-3215`); `docs/audits/followups.md:270-289` flags this
as an open product question. Determines whether C9 is a bug or a feature.

**U4 — Null-`company_id` deployment count.** `docs/audits/followups.md:366-368`
marks this **"DO THIS BEFORE DEPLOYING"** and it is still open. The falsy-company
pattern at `:8737-8738` and `:14292-14298` passes when the caller's `company_id`
is falsy, and `frontend/app/_layout.jsx:237-256` proves such users exist.

**U5 — Locked pre-fill policy.** If check-in data is locked and uneditable
(Step 4) but is `"UNASSIGNED"`, stale, or partial (§2.2, C7), what does the CP
do? Needs an operator answer before Step 4.

**U6 — Production data shape.** All §1.5 queries are unrun. The distinct-company
counts, collision groups, and unmatched set are unknown, and they determine
whether the Step 1a EXACT-match backfill matches 5% or 95% of rows.

**U7 — Which `require_approved` tier (if any) new endpoints belong to**, given
C13's hardcoded counts.

**U8 — Unverified [U] claims.** Everything marked [U] above is agent-reported and
was not independently re-checked. The highest-value ones to verify before relying
on them: the offline base64-loss path (§C17), the `checkins-today` silent-failure
branches, and Agent 3's full per-type report key lists.

**U9 — `crane_operations` is never required** (`has_crane_permit` never
evaluated, §5.3). Is that intended?

---

## 8. What Phase A did not do

- No file was created or modified except this document.
- No production database operation was run; §1.5 queries are for the operator.
- No sequencing rule content was authored, inferred, or exemplified.
- No branch, no commit, no PR.
