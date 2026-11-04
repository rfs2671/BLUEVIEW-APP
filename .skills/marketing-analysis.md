# Marketing analysis and CRO constraints

Audience: any Claude session changing landing pages, UI layouts, or onboarding.
Audited at `blueview-app@7f4a448` and `homepage@b4838d7`, 2026-11-03. The backlog below reflects those commits. Re-verify each item at HEAD before acting.

The marketing site is a separate repo: `rfs2671/homepage`. These rules apply there too, but that repo does not contain this file.

## 1. Mandatory audit: enterprise risk engine pivot

Every change to a landing page, UI layout, or onboarding sequence runs this audit before work starts. Fail on any "no" unless the PR states why.

| # | Test |
|---|---|
| 1 | Does the first screen state a DOB, penalty, or shutdown loss, not a feature or efficiency? |
| 2 | Is the first action tied to real exposure on a real job? |
| 3 | Does it pass the claim gate in `product-marketing.md` section 4? |
| 4 | Do mechanics appear as engine inputs rather than as the headline? |
| 5 | Does copy address a GC principal or superintendent? |
| 6 | Is there one primary CTA per screen, with no competing path? |
| 7 | Is every field required for the next step, and not already known? |
| 8 | Does the flow reach a real DOB result in the first session? |
| 9 | Do field screens meet `behavioral-psychology.md` section 3? |
| 10 | Is the conversion event measured? |

## 2. Mandatory friction pass

When editing any file under `frontend/app/`, `frontend/src/`, or `backend/checkin.html`, or any homepage frontend file:

1. Trace the user path through the code you are touching, from entry to completed action.
2. Count screens, taps, typed fields, required fields, decisions, and waits.
3. Classify each item:
   - **Removable**: delete it.
   - **Deferrable**: move it after first value.
   - **Derivable**: prefill it from data the server has.
   - **Protected**: keep it (`behavioral-psychology.md` section 5).
4. Remove every Removable and Derivable item within the requested scope. List out-of-scope items as findings. Do not widen the PR.
5. Report in the PR body:

```
Path:
Before: screens / taps / fields / required
After:  screens / taps / fields / required
Removed:
Deferred:
Protected, kept:
Findings outside scope:
Device test: yes / no
```

Never report friction removed without a code diff. A green build is not a field test. Anything affecting field operations needs a device test.

## 3. Friction backlog at this baseline

"Trace" means read in code, not run. Reproduce before fixing.

### P0: blocks the funnel

**1. A self-signup appears unable to finish onboarding.** Trace.
- `POST /auth/register` writes `role: demo`, `account_status: pending`, `onboarding_step: "1"`.
- `RouteGuard` in `_layout.jsx` sends step 1 users to `/onboarding`, which has no skip on step 1.
- `POST /onboarding/company` refuses demo and pending accounts (`test_a_demo_account_never_writes.py`).
- `GET /users/me/onboarding-status` is absent from the demo allow-list, so it would return an empty body. `onboarding.jsx` then redirects to `/`, while the guard redirects back. Likely a redirect loop or dead end.
- Fix decision for the operator: route demo accounts straight to `/demo`, or open a real free activation path.

**2. No free path exists.** The strategy assumes a free app. The homepage offers only "Request a walkthrough" and "Log in." The `/demo` screen ends in a `mailto:` to `activate@blueviewbuilders.com`, and activation is manual.

**3. Activation email is off-brand.** `demo.jsx` uses a `blueviewbuilders.com` address and the subject "Activate my Blueview account." Prospects see another company's name.

**4. No funnel measurement.** Neither `package.json` has an analytics dependency. A lead whose email send fails is stored nowhere (`TalkV8.jsx` header comment). See section 4.

### P1: weakens the pivot

**5. Homepage leads with product breadth.** The H1 is "Now it has a brain." In the section order, City, the first dedicated violation section, comes after On site, Records, Drawings, and Walkthroughs.

**6. Hero CTA does not convert.** "See how it works" scrolls down the page. The only form is at the bottom. Add an address-first DOB check as the primary CTA. It uses public data, so it needs rate limiting and caching, and must show the data source and time.

**7. Lead form role list misses the ICP.** `TalkV8.jsx` offers General contractor, Construction manager, Owner / developer, Subcontractor. Superintendent is missing. Add it, and remove out-of-ICP options after the ICP is confirmed in lead data.

**8. Onboarding promises what optional input cannot deliver.** Step 2 says monitoring starts right away, but address is optional and project name is required. Without an address there is no BIN. Require the address, derive the name from it, and keep the dates deferred.

**9. Company name is asked twice.** `register.jsx` collects it, and step 1's `companyForm.name` starts empty. Prefill it, or drop it from register.

**10. Step 3 (filing reps) has no first-session payoff.** Its copy cites permit renewal, while renewal automation was removed (MR.14). Move it to Settings. Confirm what still reads `filing_reps` first.

**11. Onboarding ends on the preference step, not the exposure.** After the address, show the scan result. The account should not leave without seeing its job's DOB state.

### P2: field friction

**12. Gate has no offline path.** `checkin.html` has no service worker, so a tap with no signal fails. Underground sites are affected.

**13. New-worker path is long.** Phone, card photo with up to 75 seconds of OCR wait, optional selfie, trade, 12-item orientation, signature. The orientation and signature are Protected. Measure median time, then cut waits and retakes.

**14. Hard block vs ruling.** The standing ruling is never block a worker. `checkin.html` still has `showBlockedScreen`, and the diligence report says missing OSHA/SST evidence is a hard block. Operator decision needed.

**15. Small dashboard text.** `app/index.jsx` has several `fontSize: 11` labels. Fix any that appear on field-reachable screens.

**16. Field defects recorded as open.** Superintendent log keyboard dismissal and the site device offline test were open in project notes. Confirm on a device. A log nobody can fill is the largest friction in the product.

## 4. Funnel and required events

Do not cite a conversion rate without these events. Do not add a tool that sends worker PII to a third party.

| Stage | Event | Target |
|---|---|---|
| Visit | `landing_view` | Set after baseline |
| Intent | `dob_check_started` | Set after baseline |
| Aha | `dob_result_shown` | Set after baseline |
| Lead | `lead_submitted` (stored server-side even if email fails) | Set after baseline |
| Signup | `account_created` | Set after baseline |
| Activation | `first_project_with_bin` | Set after baseline |
| Field adoption | `first_gate_checkin`, `first_log_signed` | Set after baseline |
| Habit | Logs filed on time per site-week | Set after baseline |
| Revenue | `financial_offer_viewed`, `offer_accepted` | Blocked by `product-marketing.md` section 5 |

Baseline before setting targets. Do not invent benchmarks.

## 5. Experiment rules

- One changed variable and one primary metric per test.
- Low B2B traffic rarely supports A/B significance. Until it does, use sequential before-and-after with the sample size stated, plus session review and buyer interviews.
- Report n and the time window. Never report a percentage without n.
- Never test by weakening a claim gate or a Protected item.
- Decision evidence ranks: paid behavior, signed intent, product behavior, interviews, opinion.

## 6. Review order

When a change touches several rules, resolve in this order:
1. Verified-facts rule and claim gate
2. Legal and Protected friction
3. Standing operator rulings
4. Loss framing
5. CRO changes
6. Visual preference
