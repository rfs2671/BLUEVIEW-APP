# Behavioral psychology constraints

Audience: any Claude session writing LeveLog UI, flows, notifications, or copy.
Audited at `blueview-app@7f4a448` and `homepage@b4838d7`, 2026-11-03. Read with `product-marketing.md`; its claim gate overrides every copy rule here.

## 1. Loss Aversion rules

**L1. Loss outranks efficiency.** All UI and marketing copy leads with financial penalties, DOB violations, stop-work orders, or missing records. Time saved, convenience, and "streamlining" may appear only after the loss, in a subordinate clause.

**L2. Fixed order:** consequence, evidence, action.
Bad: `Stay on top of your logs.`
Good: `Today's superintendent log is unsigned. Open record at inspection: 1. Sign now.`

**L3. Every loss is sourced.** A loss statement must bind to one of:
- a real record, shown with job address and date
- a state computed from real records
- a cited public rule, with the citation in a code comment

**L4. Dollar rules.**
- Per-record amounts come from `penalty_amount` through `lib/dob_penalty.py`. "(hearing pending)" is mandatory when it applies. Never render imposed, paid, and balance as the same number.
- Never hardcode a fine or a stop-work daily cost in UI.
- Marketing may use a dollar figure only with a primary-source URL in a comment beside it.
- A customer's cost estimate is labeled as their own input, using their own rate.
- Example records carry the existing "example" label.

**L5. Unknown is never zero.** Keep the dashboard rule: show "—" with the reason when data is unavailable. Never turn a sync failure into a risk.

**L6. Clear is not safe.** With no open items, state the fact and its time: `No open DOB items on this BIN as of 7:02 AM.` Never write "You're compliant," "All clear," or "Protected." LeveLog does not decide compliance.

**L7. No manufactured loss.** Banned:
- countdowns and deadlines without a real date behind them
- severity inflated above the source record
- invented scarcity
- peer comparisons without cohort data ("Comparison not yet available" stays)
- alerts for records not new that day

False alarms destroy the signal. The 285 false "missing" flags in `docs/LEVELOG_PRODUCT_DUE_DILIGENCE.md` (R18) are the precedent.

**L8. Severity vocabulary.** Use DOB's terms: SWO, ECB/OATH, Class 1, Class 2, complaint category. Add a short plain-English line. Do not use "critical" or red for anything the source does not support.

**L9. Risk score language.** "Risk score" and DEFCON tiers describe current signals. Never "likelihood you will be violated." See the claim gate.

## 2. Fogg Behavior Model (B = MAP)

Behavior happens only when Motivation, Ability, and a Prompt converge. Every feature spec names the target behavior, then all three. A feature missing any one is incomplete.

**Motivation** comes from the loss rules above. Do not add badges, streaks, or points.

**Ability.** When a behavior fails, fix ability before adding motivation or prompts.

| Target behavior | Actor | Ability limit |
|---|---|---|
| Returning check-in | Worker | 1 tap, no typing, under 10 seconds from page load |
| New worker registration | Worker | One decision per screen; progress kept on retry; measure median time |
| Sign a log | Super, CP | Reach signature from today's log list in 2 taps or fewer |
| Resolve a flagged check-in | CP | 1 tap per decision from the queue |
| See exposure | GC principal | Visible on first dashboard paint with no navigation |
| Activate a site | GC principal | Address entered, DOB result shown, in one session |

**Prompt.** Use the channel where the person already is.

| Actor | Allowed prompt |
|---|---|
| Worker | Physical NFC sticker or QR at the gate |
| Super, CP | In-app and site device, at the moment of the duty. No email (operator ruling). No DMs for now |
| Admin, assigned PM | Email for critical DOB alerts; WhatsApp at the admin-set time; on by default after START; STOP turns it off |
| Prospect | One primary CTA per screen |

Every prompt must open the exact screen for the action. Prompts carry job address, never raw IDs.

## 3. Cognitive and physical friction rules

Assume gloves, sun glare, noise, one free hand, poor signal, and interruption.

Required on field screens:
1. Touch targets use `touchTarget` from `src/styles/theme.js`: 56 minimum, 72 for the primary action.
2. One primary action per screen. It is identifiable in three seconds.
3. Body text 15 or larger; no meaning conveyed by color alone. Use the `outdoor` tokens where applicable.
4. Tap over type. Prefill, default, or derive every field the server already knows. Numeric keypad for numeric fields.
5. Autosave drafts. Interruption never loses input.
6. State network status plainly. Failed writes never look successful.
7. Errors name the fix and keep the input. No toast-only errors for a blocking state.
8. Maximum one consequence sentence per screen. Density is not urgency.
9. Bilingual EN/ES on every user-facing string, including errors and blocks (standing ruling). WhatsApp replies stay English for now (standing ruling).

Avoid in field flows: hover, long-press-only actions, small icon-only controls, modals over forms, scroll-jacking, and animation that delays input.

## 4. Where the rules conflict

Resolved so that future sessions do not re-decide this:

| Conflict | Ruling |
|---|---|
| "All UI emphasizes penalties" vs worker gate | Workers do not own DOB penalties and need speed. Success path has no penalty copy. A flagged state may show one line about the worker's own action, below the primary button |
| Loss framing vs "never block a worker" | Flag, record, and alert. Never turn a warning into a stop at the gate |
| Friction removal vs legal integrity | Section 5 wins |
| Urgency vs verified facts | Claim gate wins. If it cannot be verified, it is not said |
| Loss copy vs Inspector Mode | Inspector-facing screens show records only. No sales or risk copy |

## 5. Friction that must stay

Do not remove or weaken these to improve conversion:
- signatures, the affirm text, and ESRA consent
- the freeze taxonomy: 9 immediate-signature logs, 2 end-of-day batch logs
- the orientation content and acknowledgement
- operator confirmation of compliance-critical fields
- authentication, tenant scoping, rate limits, demo write guard, `require_approved`
- amendment over edit on filed records

Make these faster to complete. Do not make them optional.

## 6. Copy rewrites at this baseline

Apply when the surface is next touched. Check against the claim gate first.

| Surface | Current | Replacement |
|---|---|---|
| Homepage H1, `OpeningV8.jsx` | Your jobsite has a thousand moving parts. Now it has a brain. | One open violation can stop a job. See yours today. |
| Homepage sub, `OpeningV8.jsx` | The intelligence behind your jobsite. Drawings, workers, conversations, records and city notices—connected in one place. | LeveLog tracks DOB records on every job and keeps signed logs on file for inspection. |
| Hero CTA, `OpeningV8.jsx` | See how it works | Check a job's DOB record |
| Lead H2, `TalkV8.jsx` | Request a walkthrough. See how it connects. | See your jobs' open DOB exposure. |
| Onboarding step 2, `onboarding.jsx` | Add your first project | Which job should we check for DOB exposure? |
| Onboarding step 4, `onboarding.jsx` | How should we notify you? | Who hears about a violation first? |
| Pending screen, `demo.jsx` | Your account is pending activation | Your jobs are not being monitored yet. |
