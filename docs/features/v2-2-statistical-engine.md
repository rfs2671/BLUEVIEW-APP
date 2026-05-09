# V2.2 — Statistical Risk Engine + Event Predictor

> Replaces V2.1 entirely. NO feature flag — V2.2 is the only
> risk-score code path. The V2.1 heuristic module
> (`lib/risk_score/`) was deleted in V2.2 Commit 1; the FE
> surface (`<RiskScoreCircle/>` + `<RiskScoreDrawer/>`) is
> reused unchanged because the endpoint paths stayed
> compatible.

---

## What it does

For every project, V2.2 produces:

  1. **A 0–100 risk score** with 95% CI, broken down into 4
     contributing groups:
     - **Own building** (40%) — events on the project's BIN
       (DOB violations, failed inspections, open complaints).
     - **Peer comparison** (25%) — percentile rank among
       similar projects in the same borough × project_class ×
       use_type.
     - **Active triggers** (25%) — currently-active
       predictions from the 8-trigger event predictor.
     - **Internal compliance** (10%) — V2.0 logbook
       deficiencies + worker-cert gaps.

  2. **Up to 8 forward-looking predictions** of likely
     enforcement events in the next 1–30 days, surfaced when
     confidence ≥ 70% AND peer sample ≥ 20.

  3. **A calibration loop** — every prediction is logged with
     outcome (hit / miss / expired-without-data). The admin
     calibration endpoint shows accuracy + false-positive rate
     per trigger. Weight updates are MANUAL via the admin
     weight-tuning endpoint — the model never adjusts its
     own priors.

Drawer disclosure: "Compared against N projects in [Borough]
over past 2 years" — sample size + tier surfaced so operators
can read the score in context.

---

## Architecture

```
            ┌──────────────────────────────┐
            │ NYC Open Data (Socrata)      │
            │ ─ DOB violations              │
            │ ─ DOB inspections             │
            │ ─ DOB permits                 │
            │ ─ 311 complaints              │
            │ ─ ECB violations              │
            │ ─ HPD violations              │
            │ ─ PLUTO (snapshot)            │
            └──────────────┬───────────────┘
                           │
        ┌──────────────────┴───────────────────┐
        │ ingestion.py                         │
        │ ─ initial 2-yr backfill (manual)     │
        │ ─ weekly delta cron (Sun 2 AM ET)    │
        │ ─ event hooks on existing pollers    │
        └──────────────────┬───────────────────┘
                           ▼
            ┌──────────────────────────────┐
            │ 7 BIN-keyed source           │
            │ collections + PLUTO          │
            └──────────────┬───────────────┘
                           │
        ┌──────────────────┴───────────────────┐
        │ baselines.py (3:30 AM ET cron)       │
        │ ─ peer-set fallback ladder           │
        │ ─ per-peer-set summary stats         │
        │ ─ statistical_baselines collection   │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │ triggers.py (event-driven)           │
        │ ─ 8 trigger detectors (pure)         │
        │ ─ confidence + sample gate           │
        │ ─ predicted_events collection        │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │ score.py (per-project recompute)     │
        │ ─ 4-group weighted model             │
        │ ─ bootstrap CI                       │
        │ ─ risk_scores collection             │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │ calibration.py (5 AM ET cron)        │
        │ ─ daily outcome attribution          │
        │ ─ prediction_outcomes collection     │
        │ ─ admin calibration view             │
        │ ─ admin manual weight tuning         │
        └──────────────────────────────────────┘
```

---

## Collections

11 new (all additive, no V1 schema change):

| Collection | Source | Contains |
|---|---|---|
| `nyc_violations` | DOB violations | BIN-keyed event stream |
| `nyc_inspections` | DOB inspections | BIN-keyed event stream |
| `nyc_permits` | DOB permits | BIN-keyed event stream |
| `nyc_complaints_311` | 311 | BIN- + BBL-keyed event stream |
| `nyc_ecb_violations` | ECB | BIN-keyed event stream |
| `nyc_hpd_violations` | HPD | BIN-keyed event stream |
| `nyc_pluto` | PLUTO snapshot | BIN-unique building characteristics |
| `statistical_baselines` | aggregator | Peer-set summary stats per year_month |
| `predicted_events` | triggers | Active per-project predictions |
| `prediction_outcomes` | calibration | Closed predictions with hit/miss |
| `ingestion_state` | ingestion | Backfill resumability cursor |
| `trigger_priors` | admin | Operator-tuned per-trigger priors |

Indexes (every BIN-keyed source): `record_id` UNIQUE +
`(bin, occurred_date)` + `(borough, occurred_date)` +
`(occurred_date)`. 311 also has `(bbl, occurred_date)` for the
neighbor-trigger BBL-block join. PLUTO has `bin` UNIQUE +
`bbl` + `(borough, bldgclass)`. Aggregation collections have
their own peer-key + sweep indexes.

Storage budget: ~1 GB after the 2-year backfill. Peak
collection: `nyc_violations` + `nyc_inspections` together
~600 MB. PLUTO ~150 MB. Other collections smaller.

---

## Initial weights (operator-tunable)

### Group weights (`score.py::GROUP_WEIGHTS`)

| Group | Weight | Rationale |
|---|---|---|
| `own_building` | 0.40 | Direct evidence of risk on the project's actual BIN. Highest signal-to-noise. |
| `peer_comparison` | 0.25 | How the project compares to its peer set. Useful but less direct than own-building events. |
| `active_triggers` | 0.25 | Forward-looking; active predictions imply imminent enforcement events. Equal weight to peer because the trigger set is already quality-gated (confidence ≥ 0.70, sample ≥ 20). |
| `internal_compliance` | 0.10 | V2.0 logbook deficiencies + SST gaps. Process indicator — internal lapses don't always surface in DOB enforcement. Lowest weight. |

### Per-trigger priors (`triggers.py::_historical_match_rate_for_trigger`)

Initial priors from MR.14 + DOB enforcement-cycle norms:

| Trigger | Prior |
|---|---|
| `cure_deadline_reinspection` | 0.85 |
| `csc_periodic` | 0.81 |
| `311_at_bin` | 0.78 |
| `cse_followup` | 0.75 |
| `borough_sweep` | 0.74 |
| `ssmr_shed_aging` | 0.73 |
| `311_neighbor` | 0.72 |
| `neighbor_swo` | 0.71 |

Operator tunes via `POST /api/admin/risk-score/weights`. The
manual override is persisted in `trigger_priors` and read on
the next score recompute — no deploy required.

---

## Calibration methodology

### What we measure

For each surfaced prediction (one that passed the publication
gate), we record one outcome:

  - **`hit`** — a matching event for the trigger's expected
    kind landed in the prediction's window
    `[predicted_at, expires_at)`.
  - **`miss`** — no matching event landed; the operator was
    notified but nothing happened.
  - **`expired_no_data`** — the project's BIN was unresolvable
    or the source collection was empty for that BIN; we can't
    measure outcome.

### Per-trigger metrics

  - **Accuracy** = `hits / (hits + misses)`.
  - **False positive rate** = `misses / (hits + misses)`.
  - **False negative rate** — NOT measured here. We only see
    predictions the model surfaced; we don't observe events
    that the model failed to predict. A separate retrospective
    analysis (running the model backward over historical event
    streams) would be required to estimate FNR. Documented as
    open work in the runbook.

### Admin endpoint

```
GET /api/admin/risk-score/calibration?model_version=statistical-v1
→ {
    calibration: {
      model_version, sample_size, evaluated_at,
      by_trigger: {
        311_at_bin: {n, hits, misses, accuracy,
                     false_positive_rate, ...},
        ...
      },
      overall: {n, hits, misses, accuracy, ...},
    }
  }
```

### Weight tuning (manual only)

```
POST /api/admin/risk-score/weights
{
  "trigger_kind": "311_at_bin",
  "prior": 0.82,
  "note": "Recalibrated against Q1 2026 outcome data; +0.04"
}
→ {"prior": {trigger_kind, prior, set_by_user_id, updated_at, ...}}
```

Persisted in the `trigger_priors` collection. Effective on the
next score recompute. NO auto-update — the model never adjusts
its own priors, even with abundant outcome data.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{id}/risk-score` | Latest score (FE-facing, unchanged URL from V2.1) |
| GET | `/api/projects/{id}/risk-score/history?days=N` | Time series for charting |
| POST | `/api/projects/{id}/risk-score/calculate` | On-demand recompute (runs all 8 triggers, fires score) |
| GET | `/api/admin/risk-score/calibration` | Per-trigger calibration breakdown (admin only) |
| POST | `/api/admin/risk-score/weights` | Manual per-trigger prior tuning (admin only) |
| POST | `/api/admin/risk-score/backfill` | Operator-triggered initial 2-year backfill (admin only) |

No feature flag on any endpoint. Auth is the same `get_current_user` /
`get_admin_user` pattern as the rest of the v1 API surface.

---

## Cron schedule

| Job | Cron | Purpose |
|---|---|---|
| `v2_2_weekly_ingest` | Sun 2 AM ET | Past 7 days of NYC Open Data deltas (idempotent on `record_id`) |
| `v2_2_baseline_aggregator` | 3:30 AM ET daily | Pre-compute peer-set summary stats |
| `v2_2_calibration_attribution` | 5 AM ET daily | Walk expired predictions, attribute hit/miss |

Initial 2-year backfill is **operator-triggered**, not
auto-fired on first deploy. Operator runs it via the admin
endpoint after the V2.2 main deploy is verified healthy.

---

## Operator action checklist (production deployment)

1. **Database backup before merge.** V2.2 doesn't migrate any
   v1 collections, but the merge is large enough that a
   point-in-time restore is the right insurance.

2. **Merge `feature/v2-2-statistical-engine` → `develop` →
   `main`.** No runbook conflict expected; V2.2 only edits
   `docs/features/v2-2-statistical-engine.md`.

3. **Wait for Railway deploy.** Server boot logs should show
   the V2.1 indexes (`risk_scores_*`) still registered AND the
   11 new V2.2 collection index sets registered via
   `ALL_V22_INDEX_SPECS`. Three new cron jobs visible in
   apscheduler logs: `v2_2_weekly_ingest`,
   `v2_2_baseline_aggregator`, `v2_2_calibration_attribution`.

4. **Run the initial 2-year backfill.** From a long-lived shell
   (or background script), call:

   ```bash
   curl -X POST -H "Authorization: Bearer <admin-token>" \
     https://api.levelog.com/api/admin/risk-score/backfill \
     -H "Content-Type: application/json" \
     -d '{"max_pages_per_dataset": 50}'
   ```

   The endpoint returns after one batch (50 pages × 5000 rows
   per page = 250K records per dataset). Re-invoke until every
   dataset's `ingestion_state.backfill_finished` flips True.
   Can run in parallel with normal traffic — Socrata limits
   are respected via the existing `lib/server_http.py`
   X-App-Token wiring.

5. **Verify baselines populate.** After the backfill, check
   that the next 3:30 AM ET tick produced rows in
   `statistical_baselines`. Sample query:

   ```js
   db.statistical_baselines.find({}).sort({computed_at: -1}).limit(5)
   ```

6. **Verify scores produce.** Hit
   `POST /api/projects/{id}/risk-score/calculate` for any
   project; confirm the response includes `score`,
   `confidence_low/high`, `contributing_factors` (4 groups).

7. **Delete the BLUEVIEW user.** Per spec, operator handles
   user deletion outside this branch:

   ```js
   db.users.deleteOne({email: "michael@blueviewbuilders.com"})
   ```

   The BLUEVIEW projects + company stay under operator
   ownership.

8. **Monitor calibration.** After 2–4 weeks of outcome
   attribution, run the admin calibration endpoint. If any
   trigger's accuracy is below the 70% confidence threshold
   that surfaced its predictions, tune that trigger's prior
   downward via `POST /api/admin/risk-score/weights`.

---

## Operational concerns

- **Storage growth.** The 11 collections add ~1 GB after the
  initial backfill, growing ~50 MB/week from the Sunday delta.
  Atlas Flex tier handles it indefinitely; revisit if a
  customer onboards 500+ projects (drives more
  predicted_events / prediction_outcomes rows).

- **Per-project re-stat speed.** Target: <500 ms.
  `gather_score_inputs` does ~6 Mongo round-trips, all on
  indexed fields. Pre-aggregated baselines mean the peer
  comparison step is one find_one. Bootstrap is ~5 ms.

- **PLUTO refresh.** PLUTO ships quarterly from NYC City
  Planning. The weekly cron's PLUTO branch is a no-op (snapshot,
  not stream); operator manually triggers a PLUTO re-pull
  when a new release lands by calling the backfill endpoint
  with `dataset=pluto` (the `forward_to_v22` hook plus the
  weekly cron continue to handle the 6 event datasets).

- **False negative rate is unmeasured.** The calibration loop
  only sees predictions the model surfaced — events that
  happened without a prediction are invisible. A retrospective
  pass over historical event streams would be needed to
  estimate FNR; tracked as open work.

- **BLUEVIEW user deletion timing.** The `michael@blueviewbuilders.com`
  user is handled outside this branch by the operator. The
  BLUEVIEW company + projects stay under operator ownership
  for QA before re-enabling for the actual BLUEVIEW user
  account.
