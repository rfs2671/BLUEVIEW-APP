# Risk Score Factors — Production Investigation (2026-05-13)

## Executive summary

Three production-observed risk-score factors return 0 because V2.3
queries a **strict subset** of the NYC Socrata datasets that the
legacy `run_dob_sync_for_project` poller queries. Brooklyn project
69e7c10013506cc459fcd046 (BIN 3325703) has active enforcement
events, but they live in datasets V2.3's `count_own_building_events`
and `gather_trigger_inputs` don't poll — `855j-jady` (DOB NOW
Safety), `6bgk-3dad` (ECB/OATH), `eabe-havv` (DOB Complaints).

**Single root cause** drives all three symptoms (own_building,
active_triggers, predicted_events empty). The proposed fix is
**A3** — widen V2.3's Socrata dataset list to match the legacy
poller's. A single PR resolves all three threads.

The crons named in Railway startup logs
(`_prediction_resolution_sweep_tick`, `_prediction_cleanup_tick`)
are **resolution-only by design** — they close out existing
predictions but never write new ones. Zero predicted_events docs
is consistent with the upstream dataset coverage gap, not a cron
malfunction.

A separate **operational gap**: the V2.2 mirror collections
(`nyc_violations` 15k docs, `nyc_complaints_311` 76k docs, etc.)
still exist in production. V2.3 Commit 1's post-merge action item
to drop them has not been executed. This is unrelated to the
factor-zero symptoms (V2.3 doesn't read those collections) but
worth flagging.

A **parallel P1 risk**: the operator must verify that
`nightly_dob_scan` is actually executing in production (the
scheduler config alone does not guarantee execution). See the
cross-cutting section for the verification procedure.

---

## Thread A — `own_building` factor

### Compute path
- **Recompute entry**: `backend/lib/statistical_engine/score.py:339`
  → `count_own_building_events(socrata, bin_=bin_, bbl=bbl, now=cur_now)`
- **Normalizer**: `score.py:102` `_normalize_own_building` —
  formula `v30*8 + v90*2 + i_failed*12 + open_311*4`,
  clamped `[0,100]`
- **Aux output**: `score.py:282-291` `GROUP_OWN_BUILDING` factor
  detail (rendered in the drawer)

### Read path
- **Helper**: `backend/lib/statistical_engine/baselines.py:1016-1145`
  emits three Socrata queries:

  | Dataset slug | Dataset name | SoQL emitted (Brooklyn / Menahan) |
  |--------------|-------------|-----------------------------------|
  | `3h2n-5cm9` | DOB Violations (BIS legacy) | `bin = '3325703' AND issue_date > '20260211'` |
  | `p937-wjvj` | DOB Inspections | `bin = '3325703' AND inspection_date > '2026-03-13T00:00:00'` |
  | `erm2-nwe9` | 311 Complaints (general) | `bbl = '3033040024' AND created_date > '2026-04-12T00:00:00'` |

### Expected vs. observed

| Project | Operator expectation | Observed | Diagnosis |
|---------|----------------------|----------|-----------|
| Bronx (69e6e6c30b6e05f281e5bb66, BIN 2115914) | 0 (clean project) | 0 | **CORRECT** — genuinely empty in all three datasets |
| Brooklyn Menahan (69e7c10013506cc459fcd046, BIN 3325703) | Non-zero (active SWO + complaint + DOB audit) | 0 | **BUG** — events live in datasets V2.3 doesn't poll |

### The dataset coverage gap

The repository has **two parallel ingestion paths**:

#### LEGACY: `run_dob_sync_for_project` (server.py:15101)
- Calls `_query_dob_apis` (server.py:13192) which polls **ten datasets**
- Writes results into `db.dob_logs` (project-scoped, `record_type` discriminator)
- Wired into `nightly_dob_scan` (server.py:15599) on **15-minute interval** (server.py:24406-24411 — note: function name `nightly_dob_scan` and its docstring "runs daily at 04:00 AM EST" are STALE; actual cadence is `IntervalTrigger(minutes=15)`)
- Also fires at project-create (server.py:16023)

Violations datasets the legacy poller queries:
- `855j-jady` — DOB NOW Safety (modern, post-2024 SWOs live here)
- `3h2n-5cm9` — BIS legacy (older violations only)
- `6bgk-3dad` — ECB/OATH adjudicated summonses

Complaints datasets:
- `eabe-havv` — DOB Complaints Received (primary DOB complaint source)
- `erm2-nwe9` — 311 (general)

Inspections:
- `p937-wjvj`

#### V2.3: `count_own_building_events` (baselines.py:1016)
- Polls **three datasets only**: `3h2n-5cm9`, `p937-wjvj`, `erm2-nwe9`
- ❌ Misses `855j-jady`, `6bgk-3dad`, `eabe-havv`

Brooklyn's "active SWO" is almost certainly in `855j-jady`. Its
"active complaint" may be in `eabe-havv` (a DOB complaint, not a
311 complaint). V2.3 cannot see either.

### first_poll_summary branch (operator's added Thread A item)

**Location**: `server.py:15425-15460`
**Read source**: `db.dob_logs.count_documents({project_id, record_type})`

The 26 violations stamped on Brooklyn's `first_poll_summary` came
from `dob_logs`, populated by `run_dob_sync_for_project` at project
creation. They are NOT in `nyc_violations` because that's the
V2.2-era mirror collection — a different collection, fed by a
different (now-decommissioned) ingestion service.

### Classification

| Finding | Classification | Notes |
|---------|----------------|-------|
| V2.3 own-building queries miss `855j-jady`, `6bgk-3dad`, `eabe-havv` | **TRUE BUG** | Causes any project with modern DOB enforcement to score 0 |
| SoQL construction itself (PR #4/#5 corrections) | **WORKING AS DESIGNED** | Query shapes are correct for the datasets they do hit |
| Bronx scoring 0 | **WORKING AS DESIGNED** | Genuinely empty across all relevant datasets |
| `db.dob_logs` as un-tapped richer source | **DEPRECATION ARTIFACT** | V2.3's "lazy Socrata" design didn't account for the project-scoped collection still being populated nightly |
| `first_poll_summary` reading from `dob_logs` | **WORKING AS DESIGNED** | Unrelated to V2.3; legacy FE banner data path |

---

## Thread B — `active_triggers` factor

### Compute path
- **Recompute entry**: `score.py:368` `active_predictions_for_project(db, project_id, now=cur_now)`
- **Normalizer**: `score.py:174` `_normalize_active_triggers` —
  weighted by confidence with diminishing returns past 4 predictions
- **Aux output**: `score.py:292-298` `GROUP_ACTIVE_TRIGGERS`
  factor detail

### Read path
- **Query**: `triggers.py:505-517` reads
  ```python
  db[PREDICTED_EVENTS_COLLECTION].find({
      "project_id": project_id,
      "expires_at": {"$gt": cur_now},
      "outcome_status": "active",
  })
  ```
- **Collection**: `predicted_events` (`schema.py:64`)

### Observed
- `db.predicted_events.countDocuments({})` = **0** in production
- → `active_predictions_for_project` returns `[]`
- → `_normalize_active_triggers([])` returns `0.0` (early return at line 180)

### Write paths to `predicted_events`

There are exactly TWO writer code paths:

#### Path 1: 311-poll hook (Commit 6)
- **Caller**: `server.py:14151`
  `asyncio.create_task(_stat_engine.try_predict_inspection_from_complaint(db, project, rec))`
- **Wrapper**: `predictions.py:469` → `predict_inspection_from_complaint` → insert at `predictions.py:534`
- **Suppression conditions** (all four must hold per server.py:14145-14148):
  - `existing is None` (truly NEW complaint)
  - `not is_seed_transition_311` (not a synthetic seed row)
  - `severity == "Action"` (non-Action 311 categories don't correlate)
  - `_initial_scan_done(project_id, "311")` (initial scan completed)
- **Net effect**: only fires for new Action 311 complaints arriving AFTER each project's initial 311 scan. Historical / pre-existing complaints never produce predictions.

#### Path 2: Manual /calculate endpoint
- **Caller chain**:
  - `POST /api/projects/{id}/risk-score/calculate` (server.py:3720)
  - → `recompute_and_persist(db, project)` (server.py:3730)
  - → `run_triggers_for_project(db, project, socrata, now)` (score.py:569)
  - → 8 trigger detectors → `upsert_prediction` per qualifying trigger
- **Publication gate** (`triggers.py:417` `passes_publication_gate`): `peer_sample_size >= 20 AND confidence >= 0.70`
- **Trigger inputs source** (`triggers.py:584` `gather_trigger_inputs`): the **same three V2.3 Socrata datasets** as Thread A
- **No cron, no automatic invocation** — fires only when an operator clicks "Recalculate" via the API

### Why production has 0 docs

When the operator manually triggered scores for both test projects:
- `recompute_and_persist` fired → `run_triggers_for_project` fired
- But `gather_trigger_inputs` polled the same narrow dataset set as Thread A → empty inputs (or 311-only inputs for Brooklyn)
- Most trigger detectors return `None` when inputs are empty:
  - `trigger_311_at_bin`, `trigger_311_neighbor` need `recent_311_at_bin`/`recent_311_neighbor` — sourced from `erm2-nwe9` only; misses `eabe-havv` DOB complaints
  - `trigger_neighbor_swo`, `trigger_cse_followup`, `trigger_cure_deadline_reinspection` need violations from `3h2n-5cm9`; miss `855j-jady` (where modern SWOs live)
  - `trigger_borough_sweep` uses `p937-wjvj` (works correctly); but threshold `2σ above 90-day rolling mean` is high
  - `trigger_csc_periodic`, `trigger_ssmr_shed_aging` use project-doc fields (`days_since_last_csc`, `shed_age_days`), not Socrata
- No qualifying triggers → no `upsert_prediction` calls → no writes to `predicted_events`

### Publication-gate secondary risk

Even with A3-widened trigger inputs, individual triggers may not
pass the 0.70 confidence gate at `triggers.py:417`. PR #1 testing
must include a fixture verifying that real-world triggers actually
publish predictions to `predicted_events`, not just generate
non-empty inputs. A non-empty trigger input that produces a
prediction below the confidence threshold is functionally
indistinguishable from an empty input — both yield zero writes to
`predicted_events` and zero active_triggers subscore.

### Operational cadence — automatic recompute required

`run_triggers_for_project` only fires inside `recompute_and_persist`,
which only fires from the manual `POST .../risk-score/calculate`
endpoint. **No cron, no automatic invocation.**

This is a critical observation for operations:

> Without an automatic recompute cron, A3 fixes own_building
> reliably but active_triggers will lag reality by however long
> it takes an operator to manually click Recalculate. For a
> stop-worked site, that's unacceptable — the SWO event itself
> doesn't trigger a recompute, so active_triggers will report 0
> until someone notices and manually recomputes.

A periodic recompute cron is therefore **required** alongside A3,
not optional. See the PR sequencing section for the recommended
landing pattern (bundle with PR #1 OR hard-sequenced PR #2 —
operator's choice on scoping, but it cannot be deferred).

### Q1 — does `dob_logs` have an active/closed status field?

**YES.** `dob_logs` documents carry multiple status fields:
- `status` — generic active/closed (server.py:1754)
- `complaint_status` — 311/DOB complaint status (server.py:1759)
- `closed_date` — complaint closure date (server.py:1761)
- `disposition_date`, `disposition_code`, `disposition_label` — violation disposition (server.py:1751, 1763, 1765)
- `current_status` (canonical, added MR.14 commit 2b — line 14077)
- `resolution_state` — Sprint 2 field (server.py:1774)

Filtering active enforcement from closed enforcement is **feasible**
via any of these. The `current_status` field is the MR.14 canonical
discriminator.

**Implication for A3 fix**: widening V2.3's Socrata dataset list
DOES fix `active_triggers`, because each new dataset (`855j-jady`,
`6bgk-3dad`, `eabe-havv`) carries its own status field at the
Socrata layer. V2.3 trigger inputs can filter active-only directly
against Socrata responses, same way `dob_logs` does after ingestion.
**Same architectural pattern as the own_building fix.**

### Classification

| Finding | Classification | Notes |
|---------|----------------|-------|
| Trigger inputs from V2.3 narrow dataset set return empty for projects with modern enforcement | **TRUE BUG** | Same root cause as Thread A. Fix is A3 widening. |
| `predicted_events` is the correct collection (not `db.triggers`) | **WORKING AS DESIGNED** | `db.triggers` is a typo/red-herring — the canonical collection name was always `predicted_events` per schema.py:64 |
| No automatic recompute cron → trigger detection only fires on manual API call | **TRUE BUG / OPERATIONAL GAP** | Promoted from "optional" to **required**: without this, active_triggers lags reality between operator clicks (SWO event → no recompute → 0 score until operator notices). Must ship with or hard-after A3. |
| `passes_publication_gate` requires `peer_sample_size >= 20 AND confidence >= 0.70` | **WORKING AS DESIGNED** (with verification dependency) | Gate is correct. Verification dependency: PR #1 testing must prove that real-world triggers with non-empty inputs actually pass the gate, not just that inputs become non-empty. |
| `try_predict_inspection_from_complaint` only fires on NEW Action 311 complaints | **WORKING AS DESIGNED** | Per Commit 6 spec; backfill predictions on historical complaints would surface stale alerts |

---

## Thread C — `predicted_events` cron

### Two crons exist, both READ-ONLY relative to writes

| Cron tick (server.py) | Calls | Write semantics |
|----------------------|-------|-----------------|
| `_prediction_resolution_sweep_tick` (server.py:24570-24594, every 30 min) | `sweep_prediction_resolutions` (predictions.py:695) | Walks `outcome_status: "active"` predictions; transitions each to `hit` / `miss` / `expired_no_data` based on subsequent inspection records. **Does NOT insert new predictions.** |
| `_prediction_cleanup_tick` (server.py:24598-..., daily) | `cleanup_resolved_predictions` (predictions.py:851) | Deletes old resolved predictions past the retention window. **Does NOT insert new predictions.** |

### Resolution sweep details
- **Code**: `predictions.py:695-766`
- **Query**: `db.predicted_events.find({outcome_status: "active", method: PREDICTION_METHOD})`
- For each active prediction, calls `_resolve_one_prediction` which:
  - Looks up inspections at the prediction's BIN since predicted_at
  - If found → mark `hit` + record `actual_inspection_date`
  - If expires_at passed → mark `miss` or `expired_no_data`
  - Otherwise → leave `active`
- **Designed-as-intended**: this is a *resolution* sweep, not a *generation* sweep.

### Is the cron design flawed?

**No.** The cron design is intentional per V2.3 Commit 6 spec:
- New predictions are written by the **311-poll hook** (event-driven, low-latency)
- New trigger-based predictions are written inside `run_triggers_for_project` during score recompute (operator-driven, on demand — see Thread B's promotion of the periodic recompute cron to required)
- The crons handle the **lifecycle** of already-written predictions (resolve them, clean them up)

The 0-doc state is consistent with the **upstream gap** (Thread A + B), not a cron malfunction. If A3 widening + the periodic recompute cron land together, the next automatic recompute tick will write rows into `predicted_events`, and these existing crons will then have something to resolve.

### Classification

| Finding | Classification | Notes |
|---------|----------------|-------|
| Resolution + cleanup crons working as designed | **WORKING AS DESIGNED** | They're not the writer; they're the lifecycle manager |
| 0 docs in `predicted_events` | **TRUE BUG (upstream)** | Caused by Thread A + B dataset coverage gap, not by cron failure |
| No automatic generation cron (only manual + 311-hook writers) | **TRUE BUG / OPERATIONAL GAP** | See Thread B's promotion of the periodic recompute cron to required |

---

## Cross-cutting analysis

### Shared root cause

All three threads share **one** code-level root cause:

> V2.3's `count_own_building_events` (baselines.py:1016) and
> `gather_trigger_inputs` (triggers.py:584) poll a **strict subset**
> of the NYC Socrata datasets that the legacy poller queries.
> Brooklyn's active enforcement events live in datasets V2.3
> doesn't poll.

The downstream effects ladder cleanly from this single cause:
- own_building reads only `3h2n-5cm9` violations → misses `855j-jady`/`6bgk-3dad` → 0 violations counted
- own_building reads only `erm2-nwe9` 311 → misses `eabe-havv` DOB complaints → 0 open complaints counted
- trigger inputs share the same narrow source → empty inputs → all 8 detectors return None → 0 writes to `predicted_events`
- `active_triggers` reads `predicted_events` → 0 docs → 0 subscore

### V2.2 → V2.3 → V2.3-current classification

| Symptom | Pre-existing V2.2 issue? | V2.3 regression? | New post-V2.3? |
|---------|--------------------------|------------------|----------------|
| own_building = 0 for Brooklyn | NO (V2.2 read its mirror, which `nightly_dob_scan` populated from the full dataset list) | **YES — introduced by V2.3 Commit 3** (rewired to lazy Socrata with narrower dataset list) | NO |
| active_triggers = 0 | NEW signal in V2.3 Commit 6 (didn't exist in V2.2 in this form) | N/A | **YES — same cause as own_building** |
| `predicted_events` empty | NEW collection in V2.3 Commit 6 | N/A | **YES — same cause** |
| 9 V2.2 mirror collections still extant | N/A | NO | **OPERATIONAL GAP — post-merge action item from V2.3 Commit 1 not yet executed** |

### Q2 — `nightly_dob_scan` execution (PARALLEL P1 RISK)

**Code says YES — scheduled at every 15 minutes** (`server.py:24406-24411`, `IntervalTrigger(minutes=15)`).

**Caveats from code reading alone:**

1. The function name `nightly_dob_scan` and its docstring ("runs daily at 04:00 AM EST", line 15600) are **stale** — the actual scheduler config is 15-minute interval. This is a doc bug, not a behavior bug.
2. The function catches per-project exceptions and continues (`server.py:15621`). A widespread error (e.g. Socrata 4xx on malformed BINs, schema drift) could silently zero out new writes for many projects while emitting warnings. Sentry would alert.
3. I cannot verify actual execution from this sandbox.

**Operator verification — REQUIRED, parallel P1:**

```javascript
// Production Mongo — check newest dob_logs ObjectId timestamp.
// ObjectIds encode creation time in the first 4 bytes.
db.dob_logs.find().sort({_id: -1}).limit(5).forEach(d => print(d._id.getTimestamp()))
```

If Q2 verification shows newest dob_logs ObjectId is older than
48 hours, `nightly_dob_scan` is a P1 operational bug parallel to
A3, independent of the factor-zero symptoms. The 15-min
IntervalTrigger config in code does not guarantee execution.
Operator must verify before assuming `dob_logs` is fresh.

This matters because:
- If A2 had been the chosen fix (read from `dob_logs`), stale
  `dob_logs` would silently propagate stale data into score
  computes. A3 sidesteps this by going directly to Socrata, but
  the operational health of `nightly_dob_scan` is still relevant
  to the activity feed, permit renewal alerts, the DOB approval
  watcher, and the first_poll_summary path — all of which depend
  on fresh `dob_logs`.
- The 15-min interval was set deliberately (MR.14 commit 2a)
  for the v1 monitoring product. If the scheduler is not actually
  firing, all v1 monitoring signals are stale.

### Operational gaps to flag

| Gap | Owner | Priority | Notes |
|-----|-------|----------|-------|
| `nightly_dob_scan` execution unverified | Operator | **P1 parallel** | See Q2 above. Run the Mongo query before proceeding. |
| 9 V2.2 mirror collections still extant in prod | Operator | P2 | V2.3 Commit 1 post-merge action item. Unrelated to factor-zero symptoms but worth executing. |
| `nightly_dob_scan` function name + docstring stale | Engineer | P3 | Function says "daily 4am EST"; scheduler is 15-min interval. Rename or update docstring. |

---

## Proposed fix shapes (high-level only)

### Fix A3 — Widen V2.3's Socrata dataset list (RECOMMENDED)

**What changes**:

1. `count_own_building_events` (baselines.py:1016) gains 3 additional Socrata queries:
   - `855j-jady` (DOB NOW Safety violations) — modern violations; need to verify column names (likely `bin`, `issue_date` shape, status field for active vs closed)
   - `6bgk-3dad` (ECB/OATH violations) — adjudicated summonses; has its own date column `issue_date` + status fields
   - `eabe-havv` (DOB Complaints) — primary DOB complaint feed; has its own status / disposition fields

2. `gather_trigger_inputs` (triggers.py:584) widens the same way:
   - `recent_311_at_bin` / `recent_311_neighbor` union 311 + DOB-complaints
   - `nearby_violations_60d`, `neighbor_swo_count_30d`, `open_violations_with_cure` union three violation sources

3. Add 5–8 new pinning tests covering:
   - Each new dataset queried correctly (column names, date format, status field)
   - Active/closed filtering on each new dataset
   - Aggregated counts from multiple datasets dedupe correctly
   - Brooklyn-Menahan-like fixture produces non-zero own_building
   - **End-to-end fixture proving that A3-widened trigger inputs actually pass `passes_publication_gate` and write a row to `predicted_events`** (not just produce non-empty inputs — see Thread B publication-gate risk)

**Size**: **M** (3 new dataset integrations × 2 helper functions = 6 new SoQL paths; each dataset has its own schema quirks to learn — schema-corrections-hotfix patterns suggest 1-2 surprises per dataset).

**Dependencies**: None. Doesn't depend on Threads B/C fixes (it subsumes them).

**Rationale for choosing A3**: Preserves V2.3's "lazy Socrata, no local mirror" architectural goal. Each score recompute does a few more round trips, but the data flows through one consistent path (Socrata → in-memory aggregation → score). No re-coupling to `dob_logs` or other pre-V2.3 collections.

### Fix A2 — Read from `dob_logs` instead (REJECTED)

**What it would do**: Pivot `count_own_building_events` to read
`db.dob_logs.aggregate([{$match: {project_id, record_type, current_status: {$ne: "closed"}}}, ...])` instead of polling Socrata.

**Why rejected**: Re-couples V2.3's score path to the
`dob_logs` collection — partially undoing V2.3's "lazy Socrata"
architectural goal. The lazy-query principle was: "don't keep a
local mirror; query the source of truth on demand." Reading from
`dob_logs` reintroduces a project-scoped local-mirror dependency
that V2.3 was specifically architected away from.

Also: ties V2.3's per-score-compute latency to whatever cadence
`nightly_dob_scan` happens to run on. A 15-minute window between
real-world enforcement event and score-visible signal is acceptable
under A3 (Socrata's own freshness is also ~15 min), but it adds an
intermediate cache layer.

A2 would be smaller (one Mongo query replaces three Socrata
queries) and faster (one local read vs. three remote calls), but
those wins don't justify the architectural drift. A3's mechanical
cost (more Socrata round trips per recompute) is absorbed by the
PR #3 timeout bump's 30s budget.

### Fix A1 — Minimal: add 855j-jady only (REJECTED)

Would fix Brooklyn's specific symptom (active SWO) but leaves the
gap open for DOB complaints (`eabe-havv`) and ECB
(`6bgk-3dad`). Punts the work to a follow-up PR. Not worth two
PRs when A3 closes the whole gap in one.

### Fix B — Periodic recompute cron (REQUIRED, not optional)

**What**: Add a scheduler job that calls `recompute_and_persist`
for every tracked project every N hours.

**Why required**: Without this, `active_triggers` lags reality
between operator clicks (see Thread B's operational-cadence
analysis). For a stop-worked site, the SWO event itself doesn't
trigger a recompute, so `active_triggers` will report 0 until
someone notices and manually recomputes. That's an unacceptable
operational characteristic for the v1 monitoring product.

**Size**: **S** (one new scheduler entry + a wrapper that
iterates `track_dob_status=true` projects). Cron design pattern
already established by `nightly_dob_scan`.

**Dependency**: Must ship together with A3 OR hard-after A3
(otherwise it just burns Socrata quota producing zero predictions
every N hours).

---

## Recommended PR sequencing

| # | PR | Size | Depends on | Parallelizable? |
|---|----|------|------------|-----------------|
| 1 | **A3 — widen V2.3 Socrata dataset list** | M | None | No — must ship first |
| 2 | **Periodic recompute cron** (REQUIRED, per Thread B operational-cadence analysis) | S | #1 | Hard-sequenced after #1. Optionally bundle into #1 if scope tolerates it. |
| 3 | (Operator) drop the 9 V2.2 mirror collections per V2.3 Commit 1 action item | N/A (operations) | None | Yes — fully independent |
| 4 | (Operator) verify `nightly_dob_scan` is firing in prod via ObjectId timestamps | N/A (operations) | None | **REQUIRED before #1** — parallel P1 risk per Q2 analysis. Do this first so you know whether `dob_logs` is fresh (informs activity feed health, renewal alerts, DOB approval watcher freshness, even though A3 itself doesn't depend on `dob_logs`). |
| 5 | Cleanup: rename `nightly_dob_scan` or update its docstring (15-min interval, not "daily 4am EST") | S | None | Yes — trivial drive-by |

### Critical path

1. **#4 operator verification of `nightly_dob_scan`** — runs in parallel with engineering work on #1. P1 because stale `dob_logs` breaks 4+ other systems (activity feed, renewal alerts, DOB approval watcher, first_poll_summary) independently of score factor zeros.
2. **#1 A3 widening** — fixes own_building immediately; lays groundwork for #2.
3. **#2 periodic recompute cron** — must land with or hard-after #1; without it, active_triggers remains lagged.

### Parallelizable now (no code deps)

- Operator action #3 (V2.2 mirror drops)
- Operator action #4 (Q2 verification) — REQUIRED before #1
- Drive-by doc fix #5

### Bundling decision

PR #2 (periodic recompute cron) can be bundled into PR #1 if scope tolerates it. Recommendation: **bundle** because:
- The cron implementation is mechanically small (~30 lines + tests)
- A3 testing already requires an end-to-end fixture that exercises `recompute_and_persist`; reusing that fixture for cron-tick testing adds minimal incremental work
- Shipping A3 alone (without the cron) creates a transient state where own_building is fixed but active_triggers still lags — confusing for operators reviewing the score-detail drawer

If PR #1 is already long after the dataset-by-dataset additions, split #2 out and ship it within 24 hours of #1.

### Suggested first commit shape for PR #1
1. Stage 1: branch + audit live-Socrata schemas for `855j-jady`, `6bgk-3dad`, `eabe-havv` (column names, date formats, status fields). Document in PR description. **Critical to verify against the live API** — schema-corrections hotfix history shows ~1-2 surprises per dataset.
2. Stage 2: extend `count_own_building_events` + 2-3 unit tests per new dataset.
3. Stage 3: extend `gather_trigger_inputs` analogously + tests.
4. Stage 4: integration test pinning a Brooklyn-Menahan-like fixture producing non-zero own_building AND verifying that a real-world trigger publishes a prediction to `predicted_events` (passing `passes_publication_gate`).
5. Stage 5: (if bundling) add periodic recompute cron + cron-tick test.
6. Stage 6: full backend suite + production verification dry-run.
