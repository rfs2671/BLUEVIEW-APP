# Product marketing constraints

Audience: any Claude session writing LeveLog code or copy.
Audited at `blueview-app@7f4a448` and `homepage@b4838d7`, 2026-11-03. Use symbols and paths, not line numbers: `backend/server.py` moves constantly.

## Status tags

- **SHIPPED**: on a live code path. Not proof of field reliability.
- **TARGET**: a founder-set goal. No revenue evidence exists.
- **NOT BUILT**: absent from the code. Never describe it as available.

## 1. ICP

| Role | Who | Function | Loss they own |
|---|---|---|---|
| Economic buyer | NYC GC owner or principal | Signs the deal, receives DOB alerts | Penalties, stop-work cost, delay, insurance position |
| Daily user | Site superintendent | Files the super log, runs the site | Unfiled or wrong record under their name and license |
| Daily user | CP / safety staff | Files logs, reviews flagged check-ins | Missing record at inspection |
| Field actor, not ICP | Worker | Taps at the gate | None to sell to. See `behavioral-psychology.md` section 4 |

Rules:
- Write for the two ICP roles: GC principal and superintendent. Other roles get usable product, not targeted marketing.
- Out of ICP for copy and funnel design: owner-developers, subcontractors, lenders, inspectors.
- Superintendents and CPs receive no email (operator ruling). Reach them in the app, at the gate, and on site devices. Reach the principal by email and WhatsApp.
- Fit filter until evidence replaces it: 3 to 15 concurrent NYC jobs, with Construction Superintendent (§3301.13.13) or Major Building (§3310) obligations. This is a hypothesis from `docs/LEVELOG_PRODUCT_DUE_DILIGENCE.md` G.3.

## 2. Unit economics anchor

**TARGET, not fact:**
- Free app frontend for the customer.
- Backend fintech and insurtech monetization.
- $1,500+ per site per month.
- $35,000 LTV per project.

**Current state:**
- Revenue: none. `stripe` is pinned in `requirements.txt` and never imported. `server.py` states billing does not exist.
- Fintech: NOT BUILT. No lending, payment, draw, or financing code.
- Insurtech: NOT BUILT. Insurance code tracks the GC's own COI for permit-renewal eligibility (`lib/coi_ocr.py`, `lib/insurance_expiry.py`). No subcontractor COI tracking. `/admin/insurance` is a redirect.

**The targets imply:**

| Project revenue length | Monthly revenue needed for $35,000 |
|---|---|
| 12 months | $2,917 |
| 18 months | $1,944 |
| 23.3 months | $1,500 |
| 24 months | $1,458 |

These are revenue figures with no COGS, churn, or discounting. If $35,000 means gross-margin LTV, every figure rises.

The app is free, so the full $1,500 must come from financial products:

| Take rate (illustrative, no market data) | Premium or financed volume per site per month |
|---|---|
| 5% | $30,000 |
| 10% | $15,000 |
| 15% | $10,000 |

Rules:
- Evaluate every roadmap item by which financial product it feeds, or which risk data it produces for one. Label anything else as retention or compliance core.
- Never show $1,500, $35,000, or a take rate in customer-facing copy.
- Never call a product "free forever." Say "free" only after the activation path in `marketing-analysis.md` P0 ships.
- A free account must have a measured per-site cost ceiling. Today `account_status: pending` and `require_approved` hold cost-bearing endpoints at zero, and per-site variable cost is unmeasured. Measure it before opening free activation.
- Unit-economics inputs still needed: per-site COGS, project duration, take rates from a real partner, attach rate.

## 3. Positioning: the enterprise risk engine

**Position:** LeveLog is the risk engine for NYC jobsites. Field mechanics generate evidence. The engine turns evidence and public DOB records into exposure the GC can act on.

Sell the engine and its losses. Do not sell check-ins or logbooks as stand-alone features.

| Layer | Mechanic | Risk function | Status |
|---|---|---|---|
| Field input | NFC tap or QR at the gate (`backend/checkin.html`) | Who checked in, plus card state: expired or unknown SST is flagged | SHIPPED. Identity assurance is weak |
| Field input | 13 logbook types, signed, locked, amended | The record that exists when an inspector asks | SHIPPED. 6 types had zero field use as of 2026-09-13 |
| Public input | DOB, DOT, 311 monitoring (`db.dob_logs`) | Violations, complaints, SWOs on the job's BIN | SHIPPED |
| Engine | DEFCON tiers (`lib/statistical_engine/defcon.py`) | Rule-based urgency: NORMAL, ELEVATED, IMMEDIATE | SHIPPED. Hand-set thresholds |
| Engine | Risk score (`lib/statistical_engine/score.py`, `RiskScoreCircle`) | 0 to 100 composite | SHIPPED. No validity evidence |
| Output | Dashboard exposure, alerts, morning brief | Tells the right person what is open | SHIPPED |
| Financial output | Underwriting data, premium, financing | The revenue line | NOT BUILT |

Rules:
- Lead with the engine, then show the mechanic as its input. Example order: "open violation on your BIN" before "tap at the gate."
- Name a mechanic only with the risk it covers.
- "Enterprise" describes the system's scope, not its procurement readiness. Do not imply SSO, SOC 2, an SLA, or multi-company security review. None are evidenced.
- Keep the v1 wedge: compliance records, gate, DOB alerts. Plan reader, takeoffs, and WhatsApp memory are supporting proof, not the headline.

## 4. Claim gate

The product rule stands: the app never asserts anything it cannot verify. Loss framing runs on verified facts only.

| Claim | Status | Rule |
|---|---|---|
| Shows open violations, complaints, SWOs from public DOB data | Allowed | State the data source and sync time where shown |
| Alerts admins and assigned PMs | Allowed | Do not say "everyone" |
| Signed logs lock; corrections are amendments | Allowed | |
| Who checked in, by tap or QR | Allowed | Say "checked in," not "was on site" or "proof of presence" |
| A penalty amount on a real record | Allowed | Must use `lib/dob_penalty.py` so "(hearing pending)" is applied |
| Avoids, prevents, or stops violations or SWOs | **Banned** | No outcome evidence |
| Predicts violations, or "predictive" | **Banned** until score validation exists | Inputs had contamination history; no validity study |
| Reduces fines or premiums by any amount | **Banned** | No data |
| Tamper-proof, immutable, cryptographic, court-admissible, DOB-approved | **Banned** | Hash is unkeyed and stored beside its data; no DOB or counsel acceptance on record |
| Geofenced, face-matched, identity-verified check-in | **Banned** | Not on the live path. `card_audit.py` is dead code |
| Insured, underwritten, financing available, premium quotes | **Banned** until section 5 clears | NOT BUILT |
| Customer counts, sites, savings, testimonials | **Banned** unless verified and permissioned | One real company is evidenced |

Status changes require a code citation or measured data in the PR that changes the claim.

## 5. Gates before financial products reach code or copy

1. **Licensing and counsel.** Selling, soliciting, or negotiating insurance in New York requires a license (N.Y. Insurance Law § 2102). Commission and referral flows need counsel sign-off or a licensed partner. Lending and money handling need the same review.
2. **Data rights.** Terms and privacy policy must cover use of company, worker, and compliance data for financial products. Worker card images, selfies, and signatures need an explicit decision. Default: excluded.
3. **Evidence.** Validate the risk score against real enforcement outcomes before offering it to any insurer, lender, or customer as a risk signal.
4. **Proof of adoption.** Arm's-length GCs beyond the first customer.
5. **Security and record integrity.** Close the open items in the diligence risk register, re-verified at current HEAD.

Do not scaffold quote, bind, payment, or financing UI before gate 1 clears. Data-model groundwork is allowed if it stores nothing new about workers.

## 6. Message hierarchy

1. Loss: violation, penalty, stop-work order, missing record.
2. Evidence: where it comes from, on this job, as of when.
3. Action: the single next step.
4. Mechanism: gate, logbooks, DOB watcher.
5. Efficiency: last, and only as a subordinate clause.

Keep the existing disclaimer on the marketing site: LeveLog keeps records and reports what the city publishes, and does not decide what an inspector, an insurer, or a court accepts.
