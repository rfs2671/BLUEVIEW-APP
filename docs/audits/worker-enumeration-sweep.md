# Worker enumeration sweep

**Date:** 2026-09-03
**Base commit:** `ab99cc5` (`origin/main`)
**Status:** Report only. No product code changed.

## Why this exists

Production holds two `workers` rows for one man. The second was minted because the
returning-worker dedup key is `phone`, and his second registration carried
`phone: ""`. The agreed fix is a `duplicate_of` pointer on the **duplicate worker
record** — not on any filed document — with readers excluding rows that carry it.
Both men's filed orientation documents stay untouched.

The operator's constraint is verbatim: *"build it honoured everywhere or not at
all."* A pointer honoured in one reader and missed in another puts the duplicate
back on whichever surface was skipped. So this document is the list of surfaces,
written before anything is built.

`duplicate_of` does not exist anywhere in the codebase today
(`grep -rn 'duplicate_of' backend/ frontend/` → no hits). Everything below is
about where it would have to be honoured.

---

## 1. Sweep method, and what it cannot prove

### What was done

The brief warned about a previous enumeration that missed `data.worker_id`
because it searched guessed field names (`data.workers.worker_id`,
`data.attendees.worker_id`, `data.activities.crew.worker_id`) while the
top-level field was the one that mattered. So this sweep enumerates by
**collection access**, not by field name.

1. **Every collection name in `server.py`**, by regex over `db.<name>`, counted
   and reviewed as a list (66 distinct collections). This is what identifies
   *which* collections can even yield workers.
2. **Every `db[...]` subscript access**, separately — a `db.name` regex alone
   misses these. The brief expected two variable-accessed collections
   (`DROPBOX_SYNC_RUNS`, `WORKER_PROJECT_TRADES_COLLECTION`); **there are more
   than two**. See §1.3.
3. **Every `db.workers.*` call site** (51 in `server.py`), each resolved to its
   enclosing function and route decorator by an AST-adjacent script rather than
   by eye.
4. **Derived worker lists** — places a worker list is built from `checkins`,
   `sign_ins`, `worker_enrollments`, `logbooks`, `compliance_alerts`, or
   `projects` rather than from `workers`.
5. **Cross-module sweep** — `grep -rn` for worker-collection access across all of
   `backend/`, not just `server.py`. This found two readers outside `server.py`
   that a `server.py`-only sweep would have missed entirely (§3.4, §3.5).
6. **Join sweep** — `$lookup` and `workers.aggregate`. Result: **zero**. There is
   no aggregation-pipeline join into `workers` anywhere in the backend, so no
   worker list is assembled inside Mongo.

### 1.2 Cross-check against the repo's own tooling

`backend/scripts/find_unserved_sorts.py:177` already contains a
`collection_of()` resolver whose docstring is exactly the problem this sweep
faced: *"`db.workers` / `db["workers"]` / `db[SOME_CONST]` -> 'workers'"*. It
also handles `db[other_module.SOME_CONST]`, noting that without the cross-module
form "the notifications inbox and the statistical-engine collections" vanish.
The sweep here was cross-checked against that resolver's three shapes and covers
all three.

### 1.3 The variable-accessed collections — the brief undercounted

The brief said there are "exactly two" variable-accessed collections. There are
more, and one class of them matters:

| Site | Access | Notes |
|---|---|---|
| `server.py:13348`, `13388`, `42847` | `db[WORKER_PROJECT_TRADES_COLLECTION]` | expected |
| `server.py:20696`, `20725`, `35892`, `35897` | `db[DROPBOX_SYNC_RUNS]` | expected |
| `server.py:9809`, `9834`, `9850`, `9885`, `42790` | `db[_notifications_inbox.NOTIFICATIONS_COLLECTION]` | **cross-module constant** — not in the brief |
| `server.py:42487`, `42509`, `42526` | `db[_coll_name]` over `_stat_engine.ALL_*_INDEX_SPECS` | **loop over an imported list** — index creation only |
| `server.py:5955` | `db[collection_name_map.get(table_name, table_name)]` | **fully dynamic dispatch — reads `workers`** (§3.1) |
| `server.py:6060` | `db[collection_name]` over `table_map` | dynamic dispatch, write path |
| `server.py:12283`, `42270` | `db[coll]` / `db[coll_name]` over a name list | project hard-delete / cleanup |

The one that matters for this work is **`server.py:5955`**. It is a fully dynamic
`db[...]` dispatch whose table list includes `"workers"`, and it is the single
largest worker enumeration in the system. No `db.workers` grep finds it, and no
field-name grep finds it either. It is described in §3.1.

### 1.4 Limits — what this sweep cannot prove

Stated plainly, because a list claiming completeness it cannot demonstrate is
worse than one that names its gaps.

- **It is static, not dynamic.** `server.py:5955` is proof that a collection can
  be reached through a runtime-computed string. The sweep found that one by
  reading every `db[...]` subscript, but a name assembled at runtime from
  config, an environment variable, or a database value would not appear in any
  grep. I found no such construction, but "I found none" is weaker than "there
  are none."
- **It does not cover raw Mongo access outside the `db` handle.** If any code
  opens its own `AsyncIOMotorClient` and names the collection off a different
  variable, the `DB_NAMES`-style base-name assumption misses it. Not observed.
- **`backend/scripts/` and `backend/migrations/` were surveyed but not audited
  line by line.** `scripts/audit_fabricated_certs.py:140` and
  `scripts/diag_worker_checkin.py:70` both enumerate workers. They are operator
  tools, run by hand, and are listed in §3 for completeness but were not treated
  as product surfaces.
- **The `checkins` / `sign_ins` / `worker_enrollments` collections were swept for
  *worker-list* derivation, not exhaustively audited.** A surface that lists
  check-ins rather than workers is in scope only where it collapses rows to
  people; where it lists events I noted it and moved on.
- **Frontend coverage is by API-call and local-query enumeration** (§4), which
  depends on screens going through the API client. Direct `fetch` calls were
  swept for, but a screen reaching the network by some third path would be
  missed.
- **`git grep` sees the current tree only.** An installed older bundle can call
  an endpoint whose current caller list is empty.

---

## 2. The distinction the whole fix rests on

Every reader below falls into one of two kinds, and the correct treatment is
opposite in each:

- **Enumeration** — "give me the workers." Produces a list or a count where each
  row is *a person*. A duplicate here is a second person who does not exist.
  **`duplicate_of` must be excluded.**
- **Resolution** — "given this id, who is he?" A hydration keyed on a
  `worker_id` that some other record already committed to. The duplicate's id is
  already written into filed documents and immutable check-in rows.
  **`duplicate_of` must NOT be excluded**, or those records lose their subject.

Getting this backwards in either direction is a defect. Excluding in a
resolution path blanks a name on a signed record; failing to exclude in an
enumeration path is the bug being fixed.

---

## 3. Backend inventory

All line numbers verified against `ab99cc5`.

### 3.1 `GET /sync/pull` — the largest enumeration, and the hardest to honour

| | |
|---|---|
| **File** | `backend/server.py:5994` (`sync_pull`), via `get_table_changes` at `backend/server.py:5949` |
| **Source** | `db[collection_name_map.get(table_name, table_name)]` → `db.workers` |
| **Query** | first sync: `{company_id, is_deleted: {$ne: True}}` `.to_list(10000)`; incremental: three queries on `created_at` / `updated_at` / `is_deleted` |
| **Dedupes?** | **No.** |
| **For** | Replicating the whole roster into the device's local WatermelonDB. `workers` is a declared sync table — `WATERMELON_COLUMNS` at `server.py:5928` lists it first. |
| **Exclude?** | **Yes, but omission is not enough — see below.** |

Two things make this the sharpest instance of "honoured everywhere or not at
all":

**(a) It is unfiltered for the operator.** `sync_pull` sets `company_id = None`
when `current_user["role"] == "owner"` (`server.py:5999-6001`), and
`get_table_changes` then builds `base_query = {}`. Every worker on the platform,
`.to_list(10000)`.

**(b) Omitting the duplicate does NOT remove it from a device that already has
it.** WatermelonDB applies deletions only from the `deleted` array, which is
built at `server.py:5976-5978` as:

```python
deleted_query = {**base_query, "is_deleted": True, "updated_at": {"$gt": last_pulled}}
```

A `duplicate_of` row is **not** `is_deleted`, so it never enters `deleted`. If
the fix only drops it from `created`/`updated`, every device that has already
synced keeps the duplicate in its local database **forever**, and every
offline-rendered roster on that device keeps showing him. The server list would
be right and the phones would be wrong, indefinitely, with no mechanism to
converge.

Whatever shape the fix takes, this path needs a **positive deletion signal**,
not an omission.

### 3.2 `GET /workers` — the canonical roster

| | |
|---|---|
| **File** | `backend/server.py:14870` (`get_workers`) |
| **Source** | `paginated_query(db.workers, query, sort_field="name", ...)` (`server.py:1453`) |
| **Query** | `{is_deleted: {$ne: True}}` + `company_id`, or `{_id: None}` for a caller with no company who is not a platform operator |
| **Dedupes?** | **No.** |
| **For** | The admin roster, and the source for `workersAPI.getAll()` |
| **Exclude?** | **Yes** — and at the query level; see §5. |

Paginated (`limit` 1–500, `skip`), projected to `WORKER_LIST_FIELDS`, sorted on
`name`. The header comment documents a prior 32MB blocking-sort failure on this
exact query — worth knowing before adding a term to it.

### 3.3 `GET /logbooks/project/{project_id}/checkins-today` — the roster three logbooks are built from

| | |
|---|---|
| **File** | `backend/server.py:24879` (`get_project_checkins_today`) |
| **Source** | Three-pass merge: `db.sign_ins` + `db.worker_enrollments` + `db.daily_signatures` (pass 1), `db.checkins` (pass 2), `db.compliance_alerts` (pass 3). Per-row `db.workers.find_one` hydration at **`server.py:25181`**. |
| **Dedupes?** | **Yes, three-tier:** `seen_worker_ids` (exact id) → `seen_name_keys` (`_norm_key(name)`, `_norm_key(company)`) → `seen_names_only` (name alone, used only when company is blank) |
| **For** | Auto-populating `preshift_signin`, `osha_log`, and `toolbox_talk`. Consumed by three screens (`osha_log.jsx:98`, `preshift_signin.jsx:116`, `toolbox_talk.jsx:170`). |
| **Exclude?** | **Mixed** — see below. |

This is the most carefully built reader in the system and its own comments
document the production incident that produced the man in question. From
`server.py:24961-24973`:

> the same man was emitted again … project `6a5f63bc147407d3261df2c7`,
> `preshift_signin`, 2026-08-12: `worker_id 6a79b9f19d8cee518e4712c4` appeared
> TWICE in one stored roster — once complete from pass 2 (company "AAZ", OSHA
> number, signature) and once stripped from pass 3 … There were ZERO
> `worker_enrollments` for him, so pass 1 never ran.

**Why its existing dedupe does not save us.** The id tier is exact-match on
`worker_id`. The real record and the duplicate have **different** `worker_id`s,
so they never collide there. They fall through to the `(name, company)` tier,
which catches them only if both rows carry the same company string — and the
comment above records that pass 3 rows "often carry NO worker_company". The
`seen_names_only` fallback catches a blank-company row, but only when the blank
row arrives *second*.

**The split.** Passes 1–3 read `sign_ins` / `checkins` / `compliance_alerts` —
event rows that legitimately exist for the duplicate. The `db.workers.find_one`
at **`server.py:25181`** is *resolution* (hydrating name, OSHA number,
certifications, signature from an id a check-in row already committed to) and
must not exclude. The **collapse decision** is where `duplicate_of` belongs: a
row whose `worker_id` resolves to a `duplicate_of` record should be folded onto
its target's id rather than emitted as a second person. That is a change to the
dedupe key, not a filter on a query.

Note also `_collapsed` (`server.py:24905-24911`): rows dropped by the string
guard are **counted**, and a non-zero count means the headcount may be short. If
`duplicate_of` folding is added, it should not silently inflate `_collapsed` —
an id-confirmed fold is not the same uncertainty as a string-key guess.

### 3.4 `lib/logbook/ll196.py` — the SST compliance register, and its query is dead

| | |
|---|---|
| **File** | `backend/lib/logbook/ll196.py:297` (`generate_ll196_attestation`) |
| **Route** | `POST /projects/{project_id}/logbook/attestations/generate` — `backend/server.py:7411` |
| **Source** | `db.workers.find({"project_id": project_id, "is_deleted": {"$ne": True}}).to_list(2000)` |
| **Dedupes?** | **No.** |
| **For** | The monthly Local Law 196 SST attestation — rendered to PDF, uploaded to R2, upserted as a `logbook_entries` row. A compliance register. |
| **Exclude?** | Moot as written — **the query matches nothing.** |

**`workers` documents have no top-level `project_id`.** Both insert sites were
checked:

- `server.py:13881` (`register_and_checkin`) writes `project_id` **nested**,
  inside `safety_orientations: [{...}]` — `server.py:13893`. The update path does
  the same at `server.py:13943`.
- `server.py:14697` (`submit_checkin`) writes no `project_id` at all.
- `server.py:15561` (`POST /workers`) builds from `WorkerCreate.model_dump()` and
  sets `company_id`, not `project_id`.

No writer sets a top-level `project_id` on a worker document. So
`db.workers.find({"project_id": ...})` returns **zero rows**, always.

This is the same failure class the brief warned about — top-level versus nested
path — inverted: the *reader* asks for a top-level field that only exists nested.

**It fails toward a false all-clear.** `build_attestation_data`
(`ll196.py`) with `workers = []` produces `deficient_count = 0`, therefore
`overall_status = STATUS_COMPLETE`, and a summary string reading
**"All 0 workers in good standing."** The generated PDF is a clean SST
attestation over an empty roster.

This is independent of the duplicate work and larger than it. It is named here
because a `duplicate_of` exclusion added to this query would be dead code
guarding a dead query, and because anyone touching this file should know the
register is not currently counting anybody.

### 3.5 `lib/statistical_engine/score.py` — SST expiring count, no `is_deleted` filter

| | |
|---|---|
| **File** | `backend/lib/statistical_engine/score.py:469` |
| **Source** | `db.workers.find({"company_id": company_id})` — `async for`, unbounded |
| **Dedupes?** | **No.** |
| **For** | Company-level count of workers whose SST certs expire within 30 days; feeds a project risk score. |
| **Exclude?** | **Yes.** |

Note this query filters on `company_id` **only** — no `is_deleted` guard. It
already counts soft-deleted workers into a risk input. A `duplicate_of` row would
be counted too. Flagged as a pre-existing defect adjacent to this work.

### 3.6 The rest — backend readers, in one table

| # | File:line | Function / route | Source & query | Dedupe | For | Exclude? |
|---|---|---|---|---|---|---|
| 1 | `server.py:15421` | `scan_expiring_certifications` — `POST /admin/certifications/scan-expiring` | `db.workers.find(query).to_list(5000)`; `is_deleted` + `company_id` (or `_id: None`) | **None** | Per-worker compliance verdict — blocked / warning lists | **Yes** |
| 2 | `server.py:18954` | `get_dashboard_stats` — `GET /stats/dashboard` | `db.workers.count_documents(query)` | **None** | `total_workers` tile | **Yes** — count changes, §7 |
| 3 | `server.py:18964` | same | `db.checkins.distinct("worker_id", on_site_query)` | distinct on `worker_id` | `on_site_now` | **No** — derived from `checkins`; distinct id is already the right key |
| 4 | `server.py:32370`, `32374`, `32375` | `nightly_compliance_check` (cron) | three `db.workers.count_documents` — a deliberate coverage probe | **None** | Asserts the indexed filter covers the whole collection; logs a warning if not | **Careful** — see §7 |
| 5 | `server.py:32391` | `nightly_compliance_check` | `async for w in db.workers.find(cert_window_filter)` | **None** | Mints `CERT_EXPIRING_SOON` alerts | **Yes** |
| 6 | `server.py:35067` | `_handle_list_workers` (assistant tool) | `db.workers.find(query).to_list(1000)`; `is_deleted` + `company_id` | **None** | "the full worker roster" rendered as text, grouped by company with counts | **Yes** |
| 7 | `server.py:37860` | `_get_checklist_candidates` | `db.workers.find(wq).to_list(200)`; `is_deleted` + `company_id` | by `(kind, id)` — **id, not name** | Checklist assignee **picker** | **Yes** |
| 8 | `server.py:28089` | `generate_combined_report` (OSHA register branch) | `db.workers.find({"_id": {"$in": qids}}, {"certifications": 1}).to_list(500)` | n/a — keyed hydration | Certification review data for a **filed** `osha_log` | **NO** — resolution, §6 |
| 9 | `server.py:16258` | `get_project_checkins` — `GET /checkins/project/{id}` | `db.workers.find({"_id": {"$in": ...}, is_deleted})` | n/a — keyed hydration | Name/company fill for a check-in list | **NO** — resolution |
| 10 | `server.py:16307` | `get_active_project_checkins` — `.../active` | same shape, `missing_ids` only | n/a | same | **NO** — resolution |
| 11 | `server.py:16355` | `get_today_project_checkins` — `.../today` | same shape | n/a | same | **NO** — resolution |
| 12 | `server.py:15914` | `get_flagged_project_checkins` — `.../flagged` | `db.workers.find({"_id": {"$in": query_ids}, is_deleted})` batch hydration | n/a | Flagged-review roster; the **data-repair** surface | **NO** — §8 |
| 13 | `server.py:15603` | `get_all_checkins` — `GET /checkins` | per-row `db.workers.find_one` when `worker_name` is absent | n/a | Company-wide check-in list | **NO** — resolution |
| 14 | `server.py:24282` | `get_logbook_notifications` | per-row `db.workers.find_one({_id})` | n/a | Notification subject name | **NO** — resolution |
| 15 | `server.py:25471` | `get_project_daily_headcount` — `GET /projects/{id}/daily-headcount` | `db.checkins` + `db.worker_enrollments`; per-row `db.workers.find_one` | **`(name.lower(), company.lower())` — NAME-KEYED, no id tier** | Per-sub headcount on the **Daily Jobsite Log** | **Mixed** — §7, and see the name-key flag below |
| 16 | `server.py:25181` | `get_project_checkins_today` pass 2 | per-row `db.workers.find_one({_id})`, **no `is_deleted` filter** | n/a | Hydration | **NO** — resolution |
| 17 | `server.py:5728` | `_assert_worker_access` | `db.workers.find_one` | n/a | Authorization check | **NO** |
| 18 | `server.py:14514` | `lookup_worker` — `POST /checkin/lookup-worker` | `db.workers.find_one` | n/a | Gate lookup — single worker | **NO** — but see §9 |
| 19 | `server.py:15469` / `15477` / `15520` / `15435` / `15276` / `15315` / `15390` | `GET`/`PUT`/`DELETE /workers/{id}`, osha-card, certifications | `db.workers.find_one({_id})` | n/a | Detail + repair endpoints | **NO** — must still reach the duplicate, §8 |
| 20 | `scripts/audit_fabricated_certs.py:140` | operator script | `db.workers.find({is_deleted, certifications})` | **None** | Cert audit / repair | **No** — repair tool |
| 21 | `scripts/diag_worker_checkin.py:70` | operator script | `db.workers.find(...)` | **None** | Diagnostic | **No** — diagnostic |

### 3.7 Logbook-derived worker lists (not from `db.workers` at all)

The comment at `server.py:15978-15981` documents three distinct storage shapes,
and is the single most useful sentence in the file for this work:

> A preshift sheet stores its roster as `data.workers[]` keyed by name, an
> orientation by `data.worker_id`, and an OSHA register by neither — so any
> single count would be wrong for two of the three.

Verified. `data.workers[]` is read at exactly two sites:

| File:line | Function | Shape | Dedupe | For | Exclude? |
|---|---|---|---|---|---|
| `server.py:18258` | `generate_single_logbook_html`, `preshift_signin` branch | `data.get("workers", [])` — **stored roster**, keyed by name | **None** | The per-logbook PDF | **NO** — §6 |
| `server.py:27901` | `generate_combined_report`, pre-shift section | `pd.get("workers", [])` — same stored roster | **None** | The emailed combined report | **NO** — §6 |

Both iterate the **frozen roster stored on the filed logbook**. Neither queries
`db.workers`. A `duplicate_of` pointer is invisible to both, and correctly so:
these render a signed document exactly as it was filed.

`generate_single_logbook_html` (`server.py:17937`) makes **one** database call in
its entire ~1000-line body — `db.projects.find_one` at `server.py:17944`. The
`subcontractor_orientation` branch (`server.py:18821`) reads only stored `data`.
**A filed orientation therefore renders identically whether or not its subject's
worker row is marked as a duplicate.**

---

## 4. Frontend inventory

*(pending — the frontend sweep is running as a separate pass; see the handback
note at the end of this document)*

---

## 5. `all_orientations` — the reader that is already safe

`backend/server.py:28505`, inside `generate_combined_report`.

```python
all_orientations = await db.logbooks.find(
    {"project_id": project_id, "log_type": "subcontractor_orientation",
     "is_deleted": {"$ne": True}},
    {"data.worker_id": 1, "data.worker_name": 1},
).to_list(5000)
```

**Why it is already safe.** It never produces a list of workers. It builds two
**sets** — `oriented_ids` (keyed on `data.worker_id`) and `oriented_names` (keyed
on a whitespace-normalised, lowercased `data.worker_name`) — and then uses them
only as membership tests while walking `on_site.values()`. A set collapses
duplicates by construction. Two orientation documents naming the same man
contribute one element; the duplicate's `worker_id` landing in `oriented_ids`
alongside the real one is harmless, because the coverage loop asks
*"is this on-site worker oriented?"*, never *"how many workers are there?"*.

The denominator, `n_onsite`, is computed the same way — `on_site` is a dict keyed
`worker_id or "name:"+normalised_name` (`server.py:28489-28496`), so it counts
distinct people, not check-in rows.

**The pattern worth copying.** Both keys are tried and either one suffices:
`if (rid and rid in oriented_ids) or (rname and rname in oriented_names)`. The
id is preferred and the name is a fallback, rather than the name being the only
key. The code says so honestly (`server.py:28502-28504`): manual entries mint a
synthetic `worker_id`, so name matching is a *heuristic* whose
"collisions/spelling can skew it," and it is tracked in followups rather than
presented as sound.

**One caveat.** Safe as a coverage test, but not safe as an identity claim. If
the duplicate is oriented and the real record is not, `oriented_names` still
reports the man as covered — which happens to be the humane answer here (he was
in fact oriented), but it is the name key doing it, not the id.

---

## 6. Query-level exclusion or post-filter?

**Query level. Post-filtering is wrong on every paginated reader, and several
paginate.**

`paginated_query` (`server.py:1453-1477`):

```python
cursor = collection.find(query, projection).sort(...).skip(skip).limit(limit)
items = [...]
total = await collection.count_documents(query)
return {"items": items, "total": total, "limit": limit, "skip": skip,
        "has_more": (skip + limit) < total}
```

`limit` is applied **by Mongo**, before any Python-side filter could run. So a
post-filter:

1. **Returns a short page.** Ask for 50, Mongo returns 50 including the
   duplicate, the filter drops it, the caller gets 49 and cannot tell that from
   the end of the data.
2. **Reports a wrong `total`.** `total` comes from a second
   `count_documents(query)` on the *unfiltered* query — it would still say 55
   while the pages sum to 54. `has_more` is derived from that same wrong total.
3. **Corrupts `skip` arithmetic.** Offsets are computed against the unfiltered
   ordering, so the boundary between page 1 and page 2 shifts relative to what
   the client was shown.

Query-level exclusion makes all three consistent for free, because `total` and
the page are computed from the same `query` dict.

Paginating readers confirmed: `GET /workers` (§3.2), `GET /checkins`
(`server.py:15599-15600`), `GET /checkins/project/{id}/flagged`
(`server.py:15901-15903`).

### The predicate to use

Use **`{"duplicate_of": None}`**, not `{"duplicate_of": {"$exists": False}}`.

In Mongo, `{field: None}` matches documents where the field is **missing OR
explicitly null**; `$exists: False` matches **only missing**. Every one of the
current ~55 rows has no such field, so both work today — but the first survives a
writer that sets the field to `null` to clear a pointer, and the second silently
starts hiding those rows.

This is the same trap `get_workers` already documents for a different field
(`server.py:14894-14896`): `company_id: None` "would match precisely the orphan
rows." Same operator, opposite intent — here matching null is what we want.

### Index note

`get_workers` sorts on `name`, which has **no index** — a blocking in-memory sort
that already produced an `OperationFailure` at 32MB (documented at
`server.py:14903-14917`). Existing worker indexes (`server.py:41493-41690`):
`phone` (unique, sparse), `(company_id, updated_at)`, and two others. Adding a
`duplicate_of` term does not make the sort worse, but this query has a live
history of falling over and should not be modified casually.

---

## 7. Compliance counts that would change

**Naming these loudly, because a roster going from 55 to 54 is a number an
inspector may have seen.**

| Surface | Number | Effect |
|---|---|---|
| `GET /stats/dashboard` → `total_workers` (`server.py:18954`) | Company worker count | **55 → 54.** The most visible number in the app. |
| `GET /workers` → `total` (`server.py:14939`) | Roster total + `has_more` | **55 → 54**, and page boundaries shift. |
| `_handle_list_workers` (`server.py:35067`) | Per-company `_{co}_ (N)` counts in assistant output | Decrements the duplicate's company by one. |
| `POST /admin/certifications/scan-expiring` (`server.py:15421`) | `blocked_workers` / `warning_workers` lengths | Drops a row **if** the duplicate carries certs or lacks them. |
| `nightly_compliance_check` (`server.py:32391`) | `CERT_EXPIRING_SOON` alert volume | One fewer alert if the duplicate is in the window. |
| LL196 attestation (`ll196.py:297`) | `worker_count`, `counts`, `roster` | **No change — already 0.** §3.4. |

### The nightly coverage probe is a trap

`server.py:32370-32387` deliberately runs three counts and warns when they
disagree:

```python
loose_count   = count_documents({is_deleted, certifications.expiration_date: {$gt: now, $lte: +30d}})
covered_count = count_documents(cert_window_filter)
string_typed  = count_documents({is_deleted, certifications.expiration_date: {$type: "string"}})
if loose_count != covered_count or string_typed:
    logger.warning("[cert_expiry] scan does not cover the whole collection: ...")
```

Adding `duplicate_of` to `cert_window_filter` but **not** to `loose_count` makes
the two disagree by exactly one, and the cron logs a coverage warning every night
forever — an alarm that means "the fix is working." Either add the predicate to
all three or to none. This is precisely the "honoured everywhere or not at all"
failure, in miniature, inside a single function.

### `daily-headcount` will NOT be fixed by this

`get_project_daily_headcount` (`server.py:25367`) feeds the **Daily Jobsite Log**
— a signed §3301.2 compliance record. Its dedupe is:

```python
worker_key = (name.lower(), company.lower())     # server.py:25473, and 25446 for enrollments
```

**No `worker_id` tier at all.** But note *what it dedupes*: rows from
`db.checkins` and `db.worker_enrollments`. The `db.workers.find_one` at
`server.py:25471` only supplies a fallback name/company when the check-in row
lacks them.

So: **excluding `duplicate_of` at the `workers` collection does not change this
headcount.** If the duplicate has his own check-in rows, they are already counted
as a second man whenever the company strings differ, and they will keep being
counted after the pointer exists. Fixing this surface requires collapsing on
`worker_id` here, which is a separate change on a different collection.

Do not let a `duplicate_of` rollout be reported as having fixed the Daily
Jobsite Log headcount. It will not have.

---

## 8. Readers where excluding the duplicate would be WRONG

1. **Every `/workers/{worker_id}` endpoint** — `GET` (`server.py:15469`), `PUT`
   (`15477`), `DELETE` (`15520`), `osha-card` (`15435`), and the three
   certifications routes (`15276`, `15315`, `15390`). These are the repair
   surfaces. An operator merging or correcting the duplicate must be able to
   open it. Excluding here makes the duplicate unfixable — the record exists,
   corrupts counts, and cannot be reached.

2. **`GET /checkins/project/{id}/flagged`** (`server.py:15848`) — explicitly a
   data-repair screen. It carries `checkin_id` so a CP can `POST
   /checkins/{id}/review` and `/assign-trade`. If the duplicate's check-ins are
   flagged, hiding them removes the only surface where they can be resolved.

3. **All per-id hydration** — rows 8–19 in §3.6. These answer "who is this
   `worker_id`?" for an id already committed to an immutable check-in row or a
   filed logbook. Excluding blanks a name on a signed record. Specifically
   `server.py:28089`, which pulls `certifications` for a **filed** `osha_log`:
   exclude there and the register's review column goes empty for rows it printed
   correctly last month.

4. **Both `data.workers[]` renderers** (`server.py:18258`, `27901`) and the
   `subcontractor_orientation` branch (`server.py:18821`) — these render frozen
   stored rosters and must not be reinterpreted through current worker state. A
   filed document says what it said.

5. **`POST /sync/pull`** — must not *silently* omit; it must emit a positive
   deletion. §3.1.

6. **Operator scripts** (`audit_fabricated_certs.py`, `diag_worker_checkin.py`)
   — repair and diagnostic tools must see everything.

---

## 9. The filed logbook that names the duplicate

The Aug 4 orientation stores the duplicate's `worker_id` in `data.worker_id`.
**Excluding the worker row does not make that document unreadable or its subject
unresolvable**, for three independently verified reasons:

1. **The orientation renderer never joins `workers`.**
   `generate_single_logbook_html` makes exactly one DB call in its whole body
   (`db.projects.find_one`, `server.py:17944`), and the
   `subcontractor_orientation` branch (`server.py:18821`) reads only stored
   `data`. `worker_name`, `worker_trade`, `worker_company`, `completed_at` and
   the signature are all frozen on the document.

2. **`all_orientations` reads only the logbook.** Projection
   `{"data.worker_id": 1, "data.worker_name": 1}` — no worker join. §5.

3. **The coverage test tries both keys.** Even if the duplicate's id stopped
   resolving, `oriented_names` still matches on the normalised name.

**The requirement this implies:** `duplicate_of` must be a **pointer, not a
tombstone**. The row must remain readable by `_id` so that any future
"who is `6a79b9…`?" lookup resolves — ideally following the pointer to the
surviving record. If the row were instead deleted or made unfindable, the Aug 4
orientation would name an id that resolves to nothing.

---

## 10. Name is not a usable key here — every site that uses one

The brief's warning is confirmed by the code's own comments. One worker is stored
uppercase (`WILMER CARRILLO`); the duplicate proves two records share a name.
`server.py:24957-24959` states it directly: a `worker_id` is an id, and the
`(name, company)` pair "is a STRING STANDING IN for one, and it has now produced
**four separate defects** on this project."

| Site | Key | Risk |
|---|---|---|
| `server.py:25473` `daily-headcount` pass 2 | `(name.lower(), company.lower())` | **No id tier at all.** Feeds a signed compliance record. Highest risk. |
| `server.py:25446` `daily-headcount` pass 1 | `(name.lower(), sub.lower())` | Same. |
| `server.py:25185` `checkins-today` pass 2 | `(_norm_key(name), _norm_key(company))` | Fallback only — id tier runs first. Acceptable. |
| `server.py:25190` `checkins-today` | `seen_names_only` — name alone | Blank-company fallback. Collapses two men who share a name at different subs when one row has no company. Counted in `_collapsed`. |
| `server.py:28511` `all_orientations` | normalised `worker_name` | Membership test only, id tried first. Safe. §5. |
| `server.py:18258`, `27901` | stored `data.workers[]`, keyed by name | Frozen roster; not matched against anything. |

Note the two `daily-headcount` passes use **different normalisation** from
`checkins-today`: plain `.lower()` rather than `_norm_key`'s
`" ".join(str(v).split()).casefold()`. `_norm_key` exists precisely because "a
trailing or doubled space on either side made the raw lowercased pair miss and
emitted the SAME MAN twice" (`server.py:24947-24952`). `daily-headcount` still
uses the raw form the comment describes as broken.

---

## 11. Two adjacent findings

Neither is the duplicate work, both were found by it, and both bear on it.

### 11.1 The duplicate is an active write-attractor, not an inert row

`submit_checkin` (`server.py:14591`) normalises the phone at the top of the
handler:

```python
checkin_data.phone = format_phone(checkin_data.phone)   # server.py ~14594
```

`format_phone` (`server.py`) returns `phone or ""` when the input has no 10-digit
form — so `None` and `""` both become `""`. The returning-worker lookup at
**`server.py:14636`** then runs with **no emptiness guard**:

```python
raw_digits = ''.join(c for c in checkin_data.phone if c.isdigit())
formatted_phone = format_phone(raw_digits)
worker = await db.workers.find_one({"phone": {"$in": [checkin_data.phone, raw_digits, formatted_phone]}, "is_deleted": {"$ne": True}})
```

With no phone this is `{"phone": {"$in": ["", "", ""]}}` — which **matches the
duplicate**, whose `phone` is `""`. `CheckInCreate.phone` is
`Optional[str] = None` (`server.py:3316`), so a phone-less submission is a valid
request.

`register_and_checkin` guards this correctly — `if phone:` at `server.py:13781`.
`submit_checkin` does not.

**Consequence for the fix:** the duplicate is not a dormant row awaiting
cleanup. It is the match target for every phone-less `submit_checkin`. Marking it
`duplicate_of` and excluding it from readers, **without** also fixing this write
path, produces the worst combination: a record that no roster displays but that
new check-ins keep attaching to. Invisible and still accumulating.

The `phone` index is `unique=True, sparse=True` (`server.py:41493`). Sparse skips
*missing* fields, not empty strings, so `""` **is** indexed — meaning at most one
worker document can hold `phone: ""` at a time. The duplicate currently occupies
that slot.

### 11.2 LL196 attests over an empty roster

§3.4. The monthly SST compliance PDF renders "All 0 workers in good standing"
because its query asks for a top-level `project_id` that no writer sets. Larger
than the duplicate issue and unrelated to it, but it sits in the same collection
and should not be discovered a third time.

---

## 12. Summary

- **Enumerating readers that need the exclusion:** 8 — `sync_pull` (§3.1),
  `get_workers` (§3.2), `scan_expiring_certifications`, `get_dashboard_stats`,
  `nightly_compliance_check` (find + all three probe counts as one unit),
  `_handle_list_workers`, `_get_checklist_candidates`, `score.py:469`.
- **Readers that must NOT exclude:** all per-id hydration (11 sites), all seven
  `/workers/{id}` endpoints, the flagged repair screen, both stored-roster
  renderers, and the operator scripts.
- **One reader needs a different change entirely:** `checkins-today` (§3.3) needs
  `duplicate_of` folded into its **dedupe key**, not filtered from a query.
- **One reader will not be fixed by this at all:** `daily-headcount` (§7) dedupes
  on `checkins` by name+company and never consults the pointer.
- **One path cannot be fixed by omission:** `sync_pull` needs a positive
  deletion signal or devices keep the duplicate forever.
- **Two counts an inspector may have seen** move 55 → 54: the dashboard tile and
  the roster total.

The sweep method is collection-access enumeration, cross-checked against the
repo's own `collection_of()` resolver, with `$lookup` and cross-module access
swept separately. Its limits are stated in §1.4; the material one is that it is
static analysis and cannot rule out a collection name assembled at runtime.
