# E2 — the untraded nodes, and the day-state query

_2026-08-20. **Report only.** The expander rule change is NOT built: buried beats
unreachable, and these seven have no home yet._

---

# Q1 — the day-state query

## First, a correction I have to make

**I did not produce the evidence attributed to me.** I have had no database
access at any point in this session and have never queried the twelve rows. I do
not know their timestamps, their CP names, or their dates, and I did not observe
"same second, same CP name, sequential dates including a future one."

That analysis may well be right and may well have come from a real query. But it
cannot be credited to me, and it must not be the basis on which a read path
protecting filed records is deleted — because if it is wrong, the failure is
silent and lands on a compliance document.

**The read path is therefore still in place.** `_day_state_label` and its two
call sites are untouched in `backend/server.py`. Run the query below; if it
confirms a fixture, I will remove the read with the field in a follow-up.

## The query

Read-only. Run against production with the read-only Atlas string
(`docs/audits/HOW-TO.md` has the connection recipe).

```js
// Every logbook carrying a day_state, with the fields that distinguish a
// seeded fixture from a CP who opened the app and stated the day.
db.logbooks.find(
  { "data.day_state": { $in: ["rain_no_work", "shutdown"] } },
  {
    _id: 1, project_id: 1, date: 1, log_type: 1,
    "data.day_state": 1,
    cp_name: 1, created_by: 1,
    created_at: 1, updated_at: 1,
    status: 1, is_locked: 1,
    "cp_signature.affirmed": 1,
    "cp_signature.affirmedAt": 1,
  }
).sort({ created_at: 1 })
```

### What each field settles

| Look at | A fixture looks like | A real filing looks like |
|---|---|---|
| `created_at` | All within the same second or two | Spread across days, at working hours |
| `cp_name` / `created_by` | One name across all twelve | Different CPs, or one CP on his own project |
| `date` | Sequential, and **any date in the future** | Past dates, matching real site days |
| `cp_signature.affirmed` | Absent or `false` | `true`, with an `affirmedAt` near `created_at` |
| `is_locked` / `status` | `draft`, unlocked | `submitted` and locked — an immediate type freezes on sign |
| `project_id` | All one project, likely a demo/seed one | Real projects |

**The decisive one is `cp_signature.affirmed`.** A day state that a CP actually
stated was stated on a log he then signed and froze. An unsigned, unlocked row
carrying a day state was never attested by anyone, whatever else is true of it.

### A narrower confirmation, if the above is ambiguous

```js
// Any row that is BOTH signed-and-frozen AND carries a day state is a real
// filing by definition. If this returns zero, nothing was ever stated.
db.logbooks.countDocuments({
  "data.day_state": { $in: ["rain_no_work", "shutdown"] },
  is_locked: true,
  "cp_signature.affirmed": true,
})
```

**Zero → remove the read path with the field.** Nothing was stated, so nothing
is unstated by removing it.

**Non-zero → keep the read path**, for those rows alone. The ruling already says
so, and the dead branch is the cheaper mistake.

---

# Q2 — settled

`Optional[str] = "regular"` is built and tested. Nothing further outstanding.

---

# Q3 — the untraded nodes

## The count is 10, of which 7 are the finding — and 4 of those are a category error

`trade='gc'` is carried by **ten** nodes, not eight. They split three ways:

### Already reachable — 3 nodes, no action

`site_cleanup`, `material_delivery`, `inspection` are in
`ALWAYS_AVAILABLE_ORDER`, so every crew sees them regardless of trade. They are
`gc` in the table but are not trade-gated in practice. **Not part of the
problem.**

### Genuinely trade-gated — 7 nodes

| Node | Scope | Has edges? |
|---|---|---|
| `top_floor_structure_complete` | top floor structure complete | yes |
| `bulkhead` | bulkhead | yes |
| `elevator_overrun` | elevator overrun | yes |
| `building_envelope_closed` | building envelope closed / dried-in | yes |
| `punch_list` | punch list | yes |
| `final_inspection` | final inspection | yes |
| `other` | other | no |

## The thing worth noticing before assigning trades

**Four of the seven are not activities at all. They are states of the building.**

`top_floor_structure_complete`, `building_envelope_closed`, `bulkhead` and
`elevator_overrun` describe *what is true of the structure*, not *what a crew
did today*. That is the same category error that took `rain_no_work` and
`shutdown` out of this table — facts about the day rather than a crew's
activity — and the correction did not go far enough. These are facts about the
**building**.

This matters for the ruling: giving them a trade would make them selectable as
a crew's daily activity, and a CP would then be recording "the top floor
structure is complete" as work a specific crew performed on a specific day.
Assigning a trade *reaches* them but files them wrongly, which is a third
failure mode alongside buried and unreachable.

They also **all have edges**, so they are load-bearing in the sequence graph —
they are milestones the graph sequences *around*. Removing them would change
the 145 and is not on the table.

## Proposed disposition — for ruling, not built

| # | Node | Proposal | Why |
|---|---|---|---|
| 1 | `top_floor_structure_complete` | **Milestone, not a chip.** Keep in the graph; exclude from the crew expander entirely | It is a structural state. No crew "does" it. It sequences other work and that is its whole job |
| 2 | `building_envelope_closed` | **Milestone, not a chip.** Same | Dried-in is a condition, not a day's work |
| 3 | `bulkhead` | **`concrete`** | A real thing a crew builds. Rooftop enclosure — concrete in this taxonomy, which already holds 24 nodes including the structural work |
| 4 | `elevator_overrun` | **`concrete`** | Same: the shaft extension is poured structure |
| 5 | `punch_list` | **Keep `gc`** | Genuinely general-contractor coordination. Not mis-assigned — the problem is whether a GC crew is on the roster (see below) |
| 6 | `final_inspection` | **Add to `ALWAYS_AVAILABLE_ORDER`** | `inspection` is already always-available; a final inspection is the same act at a different moment, and any crew may be the one present for it |
| 7 | `other` | **Add to `ALWAYS_AVAILABLE_ORDER`** | It is the escape hatch. It must be reachable by every crew or the free-text path closes. Note `dailyJobsiteModel.js:314` already special-cases it — the chip is excluded from trade inference precisely because "its trade says nothing about the work", so `gc` on it is already acknowledged as meaningless |

That would leave **`punch_list` as the only trade-gated `gc` node**, and turn the
question from "seven orphans" into one answerable question: *is GC a crew that
appears on rosters?*

## On that question — `gc` is not a roster trade

`DEFAULT_TRADES` (`server.py:1842`) is the roster vocabulary: *General Labor,
Carpenter, Electrician, Plumber, HVAC / Mechanical, Ironworker, Mason,
Concrete / Cement, …*. **There is no "GC" entry.** `trade_taxonomy_v1.py:570`
maps `"gc": ["General conditions"]`, which is a taxonomy label, not something an
admin types on a project roster.

So today a `gc`-traded node is reachable only if a crew's trade resolves to
`gc`, and no roster produces that. **This is the operator's own distinction,
confirmed:** these do not "have no trade" — they belong to a trade nobody types.
For `punch_list` the fix is a roster/taxonomy decision (does GC become a
selectable trade, or does punch list belong to General Labor?), not a graph edit.

## Recommended order

1. **Rule on the seven above.** Four are cheap and uncontroversial (2 milestones,
   2 to `concrete`); two are always-available additions; one is the real
   question.
2. **Then** ship the expander rule change. With `other` and `final_inspection`
   always-available and the milestones excluded, the only node that could go
   unreachable is `punch_list`, and it will have a ruled home.
3. **Until then the expander keeps showing the catalogue**, as ruled. Buried
   beats unreachable.

## One check to run alongside the ruling

`ALWAYS_AVAILABLE_ORDER` is described as "the approved order and the order the
ranker emits". Adding `other` and `final_inspection` puts them in front of every
crew on every project, so their position in that list is a display decision, not
just a membership one. Worth stating where they go rather than appending them.
