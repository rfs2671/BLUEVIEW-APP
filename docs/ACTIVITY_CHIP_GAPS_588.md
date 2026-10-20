# Activity chips: what 588 Thomas S Boyland's crews logged that their cards did not offer

Evidence: `backend/scripts/activity_backtest.py` on 588's filed daily logs, 2026-07-29 to 2026-10-20
(77 crew-days, 107 activities). Real data, replayed day by day knowing only earlier days.

## The result in one line
Work a crew continues from the day before is already offered first (100% in the first four chips).
**Work that is new for the crew is found in the first four chips only 48% of the time** (54% in six, 65% in eight).
Neither the crew's own history nor next-activity counts learned from this job changed that, so the remaining
misses are not a ranking problem. They are the catalogue's shape.

## Where the misses are (every new activity outside the first four chips)

| Crew (roster trade) | Logged | Taxonomy owner of the node | Where it sat on the crew's card |
|---|---|---|---|
| Concrete / Cement | shoring, piles | `foundation` | not on the card at all |
| Concrete / Cement | site prep | `excavation` | not on the card at all |
| Concrete / Cement | under-slab MEP | `plumbing` | not on the card at all |
| Concrete / Cement | slab on grade, mesh | `taxonomy` | positions 25 and 28 |
| Concrete / Cement | pour slab | `concrete` | position 15 |
| Concrete / Cement | columns / shear wall rebar, formwork, pour, strip | `concrete` | positions 6-9 |
| Framers | sheathing | `taxonomy` | position 11 |
| Framers | wall framing | `taxonomy` | position 7 |
| Electrician | switchgear | `taxonomy` | position 13 |
| Plumber | water heater | `taxonomy` | position 11 |
| Plumber | domestic water rough | `taxonomy` | position 7 |
| HVAC / Mechanical | ductwork rough | `taxonomy` | position 4 |

When an activity was not reachable the crews typed it: "Foundation pile", "Rebar installation", "Concrete pouring",
"Cement", "Gravel", "Slab gravel", "Wall framing". Those are free text: no ranking, report or later suggestion can
use them as activities.

## Why
A card offers only its own roster trade's work (operator ruling, `composeChipBands`). The concrete roster trade
resolves to `Foundation / Concrete`, whose node list excludes the foundation-phase nodes owned by `foundation`,
`excavation` and `plumbing`. A foundation crew does all of those on this job.

## Done
**Search every activity** (daily log screen, under each crew's activity chips). Nothing is listed until two letters are
typed; it never changes the four chips or the trade's list; a result is the same chip with the same id, so it is
recorded as an activity, not as free text. `frontend/src/utils/chipSearch.test.cjs`.

## Decisions for the operator (not changed)
The taxonomy and sequence rules are signed-off content, so none of these was changed:

1. **Concrete / Cement crews:** also offer the foundation-phase nodes (`shoring`, `piles`, `site_prep`, `under_slab_mep`)?
2. **Order within a trade's list:** `slab on grade` and `mesh` (positions 25, 28) come long after `pour slab` in the
   concrete crew's real order. Put the trade's nodes in the order the work is done.
3. **Sequence edges for framing and plumbing:** `layout -> wall framing -> sheathing`, `MEP rough-in -> domestic water
   rough -> water heater -> fixtures`: the rule table has none, so nothing is suggested next.
4. **Names:** a framer's "layout" (new activity) and "framing (layout, track and studs)" read as different activities.

## Decided by the operator (2026-10) and built
1. **Concrete / foundation crews** now also offer excavation, shoring and piles (site prep, shoring, piles ...).
   **Under-slab MEP is not foundation work** and was not added: it stays with the plumbers, electricians and HVAC.
2. **The list follows where each trade left off.** A crew back after a week (last logged under-slab MEP) is ranked
   from there -- MEP rough-in, then the rest of that stage and the stage after -- not from the project's latest day.
3. **Trade sequences** (`app/scheduling/trade_sequence.py`): stages for excavation, shoring, piles, concrete, wood /
   CFS / interior framing, plumbing, electrical, HVAC, drywall. A **confirmed schedule's** activities planned for the date
   lift too, in the file's own words (`schedule_hints.py`; strict name match, nothing inferred).
4. **Framing is three activities**: structural framing, interior framing, ceiling drops. "Layout" is no longer a
   framing step (marking track and studs is part of framing); other trades keep their own layout.
