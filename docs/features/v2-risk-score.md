# V2.1 — NYC DOB Risk Score (heuristic v1)

> Second v2 feature. Ships behind feature flag `v2_risk_score`
> (default OFF). v1 customers see nothing until the flag is
> enabled for them. Phase E1 documents the rollout patterns;
> this doc covers what the feature is and how it behaves.

> **This is a heuristic v1.** Initial weights are based on public
> DOB violation data analysis, NOT calibrated against
> ex-DOB-inspector ground truth. Accuracy will improve as
> inspector reviews accumulate. After ≥100 reviews land in
> `risk_score_reviews`, evaluate moving to a learned model.

---

## What it does

Synthesizes signals from existing data sources — DOB logs, V2.0
logbook entries, workers, subcontractors, project metadata — into
a single 0–100 risk score per project, with a 95% confidence
interval and a per-factor contribution breakdown.

  • **Top-of-page card** on the project detail screen showing
    score, color band, CI, and the top contributing factors.
  • **Per-day history** — `/api/projects/{id}/risk-score/history`
    feeds a 30-day sparkline.
  • **Inspector review modal** (admin-only) — operators can
    confirm or refute the score; reviews accumulate in
    `risk_score_reviews` and feed the calibration aggregator.

All driven by three new collections (`risk_scores`,
`risk_score_reviews`, `risk_score_calibration`) populated by a
daily 4 AM ET cron tick, with on-demand recalculation via the
`/calculate` endpoint.

---

## Why now

Operators (and their compliance staff) need a single number to
prioritize attention across a portfolio. Pre-V2.1 the workflow
was: open every project, scan the activity feed, mentally tally
violations, expirations, and missing logs. The risk score
collapses that into one card per project.

Side benefit: the contributing-factors breakdown surfaces
problems the operator might not have looked at — "why is this
project orange? Oh, three subs with expired COIs."

---

## Inputs

The model collects 8 signals per project, each on a normalized
[0, 1] scale, weighted to sum to 100. See
[`v2-risk-score-weights.md`](./v2-risk-score-weights.md) for
the full weights table + rationale.

| Input | Source | Cap | Weight |
|---|---|---|---|
| Active DOB violations (90d) | `dob_logs` signal_kind=violation_dob | 5 | 22 |
| Permit days to expiration | `dob_logs` signal_kind=permit_*, min across active | 30 days | 18 |
| Inspection compliance missed | `project.inspection_windows[]` past `by_date` not done | 10 | 15 |
| Logbook deficiencies (30d) | `logbook_entries` category=deficiency | 20 | 12 |
| Subcontractor insurance | `subcontractors` coi_on_file=False or COI expiring ≤30d | 5 | 10 |
| Missing daily logs (30d) | `logbook_entries` category=daily_log status=missing | 22 | 9 |
| SST expirations (next 30d) | `workers` certifications type∈SST_* expiring ≤30d | 50 | 8 |
| Days since last activity | max(latest dob_log, latest daily_log) | 30 days | 6 |

The weight column sums to 100 — a maxed-out project scores
exactly 100, a clean project scores 0. Each input contributes
`weight × normalized_value` where `normalized_value ∈ [0, 1]`.

---

## Confidence interval

**Bootstrap, 1000 samples, 95% CI = (2.5th, 97.5th percentile).**

Every input is independently perturbed by multiplicative
Gaussian noise (σ = 0.10) and the score is recomputed. The CI
captures *measurement* uncertainty — did we miss a violation?
is the SST roster current? did one daily log silently fail to
write? — rather than uncertainty in the weights themselves.

Why bootstrap rather than closed-form variance: the
normalization step is non-linear (clamps at 0 and at the cap),
so analytic propagation would mis-state the interval near the
boundaries. A 1000-sample bootstrap is fast (~5 ms) and handles
boundary cases by construction. Deterministic inputs collapse
the CI to the point estimate.

> **Why a CI at all?** A single number with no uncertainty band
> is misleading: a "57" feels like an objective measurement
> when it's the output of a heuristic with several measurement
> assumptions. The CI tells the operator "we're 95% sure the
> true score is between X and Y" — which informs both the
> confidence with which to act AND the decision to re-measure
> (gather better data) before reacting.

---

## Score bands

| Band | Range | Color | Implied action |
|---|---|---|---|
| LOW | 0–30 | green | No action; routine monitoring |
| MODERATE | 31–60 | yellow | Review the top contributing factors; address in normal cadence |
| ELEVATED | 61–80 | orange | Active intervention recommended |
| HIGH | 81–100 | red | Immediate intervention; expect inspector attention |

Thresholds are pinned in `lib/risk_score/schema.py::score_band`
AND in `frontend/src/components/RiskScoreCard.jsx::bandFor`.
Tests pin both so a future drift between BE and FE is caught.

---

## Calibration framework

Three artifacts:

1. **`risk_score_reviews`** — append-only log of inspector
   verdicts. Schema: `{score_id, project_id, model_version,
   was_high_risk_correct: bool, notes, reviewed_at,
   reviewed_by_user_id}`. Multiple reviews per score are
   intentional — reviewer disagreement is signal.

2. **Aggregator** (`compute_calibration_stats`) — walks every
   review for a model version, joins with the original score,
   computes:
     • **Brier score** — `mean((predicted_prob − observed_label)²)`.
       0 = perfect, 0.25 = chance.
     • **ROC-AUC** — concordant-pair counting. 1.0 = perfect
       separation, 0.5 = chance.
   Computed on demand by `GET /api/admin/risk-score/calibration`.

3. **`risk_score_calibration`** — periodic snapshots of the
   aggregator output. NOT auto-written by the live system; the
   operator inserts a snapshot when they want a versioned record
   of what the calibration looked like at a point in time.

### Manual weight updates only

This is critical. The calibration loop **does NOT** auto-update
weights. The flow is:

1. Inspector reviews accumulate (target: ≥100 before any
   calibration claim is meaningful).
2. Operator opens `GET /api/admin/risk-score/calibration` and
   reviews stats per model version.
3. If Brier score > acceptable threshold (or ROC-AUC < 0.7),
   operator inspects the per-factor distribution of
   misclassifications.
4. Operator manually edits `lib/risk_score/heuristic.py::WEIGHTS`,
   bumps `MODEL_VERSION` in `schema.py`, ships in a commit.

Why manual: a single noisy reviewer ("I like this GC, mark them
OK") could otherwise corrupt the weights. Human in loop.

---

## Endpoints (all flag-gated)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{id}/risk-score` | Latest score |
| GET | `/api/projects/{id}/risk-score/history?days=30` | Time series for charting |
| POST | `/api/projects/{id}/risk-score/calculate` | On-demand recalculation (force=True; bypasses freshness) |
| POST | `/api/projects/{id}/risk-score/calibration` | Log inspector review (any auth'd user) |
| GET | `/api/admin/risk-score/calibration` | Aggregate calibration stats (admin only) |

**Gating contract**: every endpoint calls
`is_feature_enabled('v2_risk_score', user_id, company_id)` and
returns **404** (not 403) when the flag is off — same security
parity as V2.0 endpoints.

---

## Schema

Three new collections, all additive (no schema changes to
existing collections):

```js
// risk_scores — one doc per score calculation
{
  _id, company_id, project_id,
  calculated_at,                       // datetime UTC, indexed desc
  score,                               // 0..100
  confidence_low, confidence_high,     // 95% CI bounds
  contributing_factors: [
    {factor, weight, value, normalized, contribution}
  ],
  model_version,                       // "heuristic-v1" today
  inputs_snapshot,                     // every input value at calc time
  weights_snapshot,                    // weights dict at calc time
}

// risk_score_reviews — one doc per inspector review
{
  _id, score_id, project_id, model_version,
  was_high_risk_correct, notes,
  reviewed_at, reviewed_by_user_id,
}

// risk_score_calibration — one doc per snapshot (manual writes)
{
  _id, model_version, evaluated_at,
  sample_size, brier_score, roc_auc,
  inspector_review_count, notes,
}
```

Indexes (registered at startup via
`_ensure_index_resilient` from
`lib/risk_score/schema.py::*_INDEXES`):

  • `risk_scores`: `(company_id, project_id, calculated_at)` (latest-per-project),
    `(project_id, calculated_at)` (history), `(model_version, calculated_at)` (calibration).
  • `risk_score_reviews`: `(model_version, reviewed_at)`,
    `(score_id)`, `(project_id, reviewed_at)`.
  • `risk_score_calibration`: `(model_version, evaluated_at)`.

---

## Frontend

> **V2.1.2 redesign — circle gauge with click-to-drawer pattern.**
> The original V2.1 implementation mounted a full-width
> `<RiskScoreCard …/>` text card on the project detail page.
> Operator feedback: too visually heavy for what should be a
> side feature, not a full tab. V2.1.2 replaces it with a
> compact circular gauge (`<RiskScoreCircle …/>`) that opens
> the full breakdown in a slide-in side drawer
> (`<RiskScoreDrawer …/>`) on click. The old
> `RiskScoreCard.jsx` is kept as a deprecated reference and
> will be deleted after the redesign is verified in production.

### `<RiskScoreCircle projectId={…} isAdmin={…} size={…} />`

A compact SVG radial gauge (default 84 px, configurable). Mounted in two surfaces:

  • **Project list** (`frontend/app/projects/index.jsx`) —
    inline with each `GlassListItem`, before the delete button,
    at `size={56}`. Each row paints its own circle from
    `GET /api/projects/{id}/risk-score`.
  • **Project detail header** (`frontend/app/project/[id].jsx`) —
    in the right cluster of the project header card, next to
    the QR badge, at `size={84}`.

Behavior:

  • **First hook** is `useFeatureFlag('v2_risk_score')` —
    rules-of-hooks; same C1.3 / V2.0 / V2.1 pattern. Tests pin
    the order via line-position check.
  • **Flag OFF** → returns `null` BEFORE fetching anything.
    v1 users see nothing.
  • **Loading / no score / fetch failure** → renders a greyed
    ring with `—`. Silent fail; never paints an error toast
    (a list with 50 projects on a partial outage shouldn't
    burn 50 toasts).
  • **Score present** → radial fill colored by band, score
    number centered, band label below (LOW / MODERATE / HIGH /
    CRITICAL).
  • **Hover (web)** → tooltip `low–high / 100`.
  • **Click** → opens `<RiskScoreDrawer/>`. Never navigates
    away from the current page.
  • Score-band thresholds match
    `lib/risk_score/schema.py::score_band` exactly. Tests pin
    each boundary case (29, 30, 31, 60, 61, 80, 81, 99).

### `<RiskScoreDrawer projectId={…} visible={…} onClose={…} />`

Slide-in side drawer (460 px desktop / full-width on mobile <768 px). Renders the full breakdown:

  • Big score number with band color + 95% CI prominently
    displayed.
  • Top-5 contributing factors with proportional bars colored
    by band.
  • **Recalculate now** — POSTs to
    `/api/projects/{id}/risk-score/calculate`, updates the
    drawer in place when it returns.
  • **Admin only** — "Was this correct?" button opens the
    same inspector-review modal that posts to
    `/api/projects/{id}/risk-score/calibration`.

Closes on: X button, ESC key (web), backdrop tap.

Hard rules pinned by tests:

  • `useFeatureFlag('v2_risk_score')` is the FIRST hook.
  • Flag OFF → null. `visible === false` → null (no DOM at
    all when closed).
  • ESC keydown listener bound on web, removed on unmount.

---

## Scheduler

**Daily 4 AM ET tick** — `v2_risk_score_daily_tick`. Runs after
the V2.0 logbook 3 AM tick so it sees the freshest missing /
deficiency entries on every run.

**Globally flag-gated**: the tick probes
`is_feature_enabled('v2_risk_score', user_id=None,
company_id=None)` first; if globally off, it returns
immediately without walking any project. This is the
"production while flag is created but not yet enabled" safety
property — even with the flag row inserted but
`enabled_globally: false`, the tick is a no-op.

**Idempotent** via a 12-hour freshness check in
`run_risk_score_for_project` — overlapping ticks (manual rerun
+ cron tick) don't double-write.

**Soft-fails per-project**: one bad doc doesn't kill the run.

---

## Rollout (per `feature-flags.md` §3)

Recommended sequence:

1. **Owner-only**: enable for the operator's user_id, validate
   end-to-end on production.
2. **Canary**: BLUEVIEW (or similar friendly customer). Watch
   Sentry for a week.
3. **Percentage rollout**: 10% → 50% → 100% over two weeks.
4. **Default ON**: only after sustained 100% with no v1-path
   incidents AND ≥100 inspector reviews collected with
   acceptable Brier/AUC.

Kill switch: PATCH `/api/admin/feature-flags/v2_risk_score` with
`{enabled_globally: false, enabled_percentage: 0,
enabled_for_companies: [], enabled_for_users: []}`. Cache
invalidates within 60s; flag-off behavior is full v1 (zero v2
surface area).

---

## Operational concerns

  • **Cron timing**: 4 AM ET tick runs after the 3 AM logbook
    tick. If the logbook timing changes, revisit this offset —
    risk scores read logbook outputs and need them populated
    before the score tick fires.
  • **Storage growth**: each `risk_scores` doc is ~3 KB
    (factors + inputs snapshot). At one project per day per
    customer × 100 customers × 5 projects each = ~500 docs/day
    = ~1.5 MB/day = ~550 MB/year. Atlas Flex tier handles it
    indefinitely; revisit if a customer onboards 500+ projects.
  • **Counter cap**: history endpoint returns max 500 docs. At
    one score per day that's 16 months of history — past which
    the chart truncates. Worth re-tuning if the operator wants
    multi-year trend lines.
  • **Calibration latency**: `compute_calibration_stats` walks
    every review and does a `find_one` per review. With ≥1000
    reviews this becomes slow; if the admin endpoint starts
    timing out, build a `risk_score_calibration` materialization
    job (cron, e.g. weekly) and serve from the snapshot.
