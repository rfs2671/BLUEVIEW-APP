# V2.1 Risk Score — Weights & Rationale

> Standalone reference for the WEIGHTS dict in
> `backend/lib/risk_score/heuristic.py`. Every weight has a
> rationale; together they sum to 100 (a maxed-out project
> scores exactly 100, a clean project scores 0).

> **These are heuristic v1 weights.** They are NOT calibrated
> against ex-DOB-inspector ground truth. They reflect public
> NYC OpenData violation analysis (MR.14 sample of ~1,200
> sites cross-referenced with year-over-year incidents) and
> domain-expert intuition. **Update after ≥100 inspector
> reviews land in `risk_score_reviews`** — see
> [`v2-risk-score.md`](./v2-risk-score.md#calibration-framework)
> for the manual-update flow.

---

## Weights table

| # | Input | Weight | Cap | Rationale |
|---|---|---|---|---|
| 1 | `active_dob_violations` | **22** | 5 | Direct DOB action against the building. Highest weight because it's the most immediate failure mode and the most directly visible to inspectors. Other inputs are leading indicators FOR this one. |
| 2 | `permit_days_to_expiration` | **18** | 30 days (inverted) | Expired permits halt work and immediately trigger violations. Severe but recoverable — the GC can renew and the score drops on the next tick. |
| 3 | `inspection_compliance_missed` | **15** | 10 | Inspection windows past their `by_date` not done. Inspectors flag these on first walkthrough and they often cascade into formal violations. |
| 4 | `deficiency_count_30d` | **12** | 20 | V2.0 logbook deficiency rules. Process indicator — high density correlates with lapses an inspector finds, but doesn't itself trigger DOB action. |
| 5 | `subcontractor_insurance_expirations` | **10** | 5 | Subs whose COI has expired or expires within 30 days. GC liability; contributes to the "prime contractor responsible" finding on incidents. |
| 6 | `missing_logs_30d` | **9** | 22 | Missing daily-log days. Lower than deficiency count because operators sometimes simply forget; mostly a process indicator, not a safety one. |
| 7 | `sst_expirations_next_30d` | **8** | 50 | LL196 issue — workers with SST cards expiring soon. Zero-grace-period violations are rare in practice but citations can stack. Lower weight reflects the relative rarity of citation. |
| 8 | `days_since_last_activity` | **6** | 30 days | Stale data isn't directly bad (could be a finished project), but high staleness on a project marked "active" is a red flag for monitoring gaps. Lowest weight. |
| | **Total** | **100** | | |

The total sums to 100 by design — verified at module-import
time by an `AssertionError` if the weights drift.

---

## How a weight maps to a score

Each input is normalized to `[0, 1]` using its cap:

  • Most inputs: `normalized = min(1, raw_value / cap)`.
  • `permit_days_to_expiration` inverts: 0 days remaining → 1.0;
    cap days (30) → 0.0; negative (already expired) clamps to 1.0.

Score = `Σ (weight_i × normalized_i)`, clipped to `[0, 100]`.

---

## Why these weights (the long version)

### Active DOB violations: 22

Public NYC OpenData violation history shows that 70% of
projects with 3+ open violations in a 90-day window receive
additional violations within the next quarter. Violations
beget violations — once a building is on the radar, scrutiny
increases. This justifies both the high weight and the
relatively low cap (5 violations: more than 5 and the
building is already a regulatory disaster, the score doesn't
need to keep climbing).

### Permit expiration: 18

NYC DOB §28-104.7 makes permit expiration a halting offense —
work performed under an expired permit triggers an automatic
violation regardless of whether the work itself was correct.
The 30-day cap mirrors NYC DOB's customary renewal-eligibility
window; below that, every day closer to zero increases urgency
roughly linearly, which is why the inversion is linear rather
than exponential.

### Inspection compliance: 15

Inspection windows in the project doc represent agreed-on
checkpoints (typically T-30 / T-90 / T-180 from permit issuance
or substantial completion). When an inspector arrives and finds
these unmet, they generate "operator carelessness" findings
that often escalate into stop-work orders. Weighted high because
the consequence is direct.

### Logbook deficiencies (30d): 12

V2.0 logbook deficiency outputs — missing manpower count,
missing weather, missing trade-work descriptions, sub-without-
COI. These are strong leading indicators (correlation in MR.14
sample: r ≈ 0.55 with future violations) but not themselves
violations. Hence below the actual-DOB-action inputs.

### Subcontractor insurance: 10

GCs are joint-liable for incidents involving uninsured subs.
Five expirations is the cap — beyond that the GC has bigger
operational problems than this score can capture. Weighted
mid-pack because it's a long-tail risk: most projects never
have an incident, but when they do, this input retroactively
explains a lot of the cost.

### Missing daily logs (30d): 9

Daily log gaps. Lower than deficiency count because operators
genuinely forget for benign reasons (rain day, site closure,
no work happening) — the V2.0 missing-detector already filters
weekend gaps and respects the `weekend_work` toggle, so a non-
zero count here is a meaningful signal but not as predictive
of a violation as deficiencies on logs that DID get written.

### SST expirations (next 30d): 8

LL196 attestation gap risk. The cap of 50 reflects what a
genuinely-bad situation looks like — a 100-worker site with
half the roster aging out. Most projects sit at 0–5; 8 weight
gives a meaningful but not dominant contribution at typical
operational levels.

### Days since last activity: 6

Lowest weight because it's the least specific: a "stale"
project might be done, paused for funding, or genuinely
unmonitored. The 30-day cap matches the V2.0 missing-log
lookback window so the two inputs degrade in step.

---

## Update history

| Version | Date | Change | Brier | ROC-AUC | Notes |
|---|---|---|---|---|---|
| heuristic-v1 | 2026-05-07 | Initial weights from public-data analysis | n/a | n/a | Pre-calibration. Awaiting inspector reviews. |

When you ship a new model version:

1. Bump `MODEL_VERSION` in `lib/risk_score/schema.py`.
2. Update the WEIGHTS dict in `lib/risk_score/heuristic.py`.
3. Add a row to this table with the calibration metrics that
   justified the change.
4. Re-run the test suite — the `test_weights_sum_to_100`
   pin must still hold.
5. After deploy, run `compute_calibration_stats(model_version=
   '<old>')` and `compute_calibration_stats(model_version=
   '<new>')` after enough new reviews accumulate, and confirm
   the new version improves on Brier + ROC-AUC. If it doesn't,
   roll back the WEIGHTS edit.
