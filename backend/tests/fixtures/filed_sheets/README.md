# What every filed sheet said before its branch was deleted

`before-conversion-2026-09-12.b64` is gzipped JSON: for each unconverted log
type, for each production record, the **visible text** of the document
`generate_single_logbook_html` produced on 2026-09-12, plus its date, status and
a short hash.

## Why it exists

The orientation sheet was the first type moved onto the declarative renderer.
Its control run compared the whole document against the engine's sheet and got
**92 of 92 byte-for-byte identical**. That proved the old branch was
unreachable. It said nothing about content, because both sides of the
comparison were the new engine.

Three things had been lost and stayed lost in production for three days: the
signature affirmation banner on 89 records, its **UNAFFIRMED** half on 79, and
the AMENDED RECORD banner on 15. A fourth — the record's DRAFT status — is
still open as defect A17.

**A restyle can only lose content quietly**, because anything it lost loudly
would not have shipped. So the check cannot be "does it render". It has to be
"does it still say the same things", and that requires knowing what it said.

Recovering the orientation baseline afterwards meant checking out `a9c48678`,
the last commit where that branch ran, and hoping its helpers had not moved.
That worked once. It is not a plan.

## Why it was captured all at once

For every type in here **the branch is still the renderer**, so running the
deployed build *is* the old output — nothing to reconstruct, check out or
patch. That stops being true the moment a type is converted, and it is never
cheaper than before the first one.

Captured on 2026-09-12, against production:

| type | records |
|---|---|
| toolbox_talk | 63 |
| daily_jobsite | 59 |
| preshift_signin | 49 |
| osha_log | 39 |
| scaffold_maintenance | 9 |
| site_superintendent_log | 6 |

**Six types have no production record at all** — `ssc_daily_safety_log`,
`hot_work`, `concrete_operations`, `crane_operations`, `excavation_monitoring`,
`fall_protection`. Their conversions cannot be checked this way, and that is a
fact about those conversions rather than a gap in this file. They need a
different kind of evidence, decided before they are attempted.

`subcontractor_orientation` is absent because it was already converted. That
absence is the whole lesson.

## How to use it

`capture.py` is the script that produced it, kept so the format is not
guesswork. `compare.py` takes a type and renders every record of it through the
current tree, then reports what the old sheet said that the new one does not.

Two traps already paid for, both handled in `compare.py`:

- **Fold case.** The first run reported the job address missing when the engine
  had merely uppercased it.
- **Replace image payloads with a token.** 248 base64 photographs are otherwise
  the entire diff.

And one that is not automatable: **the tool reports missing words, not missing
meaning.** A word that survives in a different sentence still counts as
present. Read the leftovers; do not just count them.

## The corpus that drops what it cannot resolve

**Read this before building any comparison corpus of your own.** It is the
sharpest failure of this kind we have hit, because the instrument was correct
and its INPUT was filtered.

A local corpus of the 59 daily jobsite records was built by pulling each
record's project document and storing **only the projects that resolved**. Two
of those records name a `project_id` that is not in the projects collection at
all. With no entry for it, the test stub's `find_one` fell back to "the first
project I have" — and handed that substitute to **both** renderers. The diff
came back clean.

It was not clean. On production those two sheets were omitting the
project-scoped Site Information section **entirely**, and saying nothing about
why. Nine of 317 filed records across four types are in that state (defect
A18).

Three rules follow, and they apply to every corpus built from here:

1. **Do not silently skip a related document that comes back empty.** Record
   the absence and carry it into the fixture, so the renderer sees what
   production sees.
2. **A stub must never substitute a plausible value for a missing one.** A
   `find_one` that falls back to the first available document makes every
   missing reference look present, in both halves of the comparison at once.
3. **Check what the sheet does when a reference is absent.** `empty: "omit"`
   on a project-scoped section means the section VANISHES, which on the page
   reads identically to a section that does not apply.

## Six types have no production records, and their fixtures are not derived from data

`ssc_daily_safety_log`, `hot_work`, `concrete_operations`, `crane_operations`,
`excavation_monitoring` and `fall_protection` have **zero filed records**.
Nothing in this baseline covers them and nothing ever will.

For those six, a fixture is not a sample of production — it is **constructed**,
and it is the only evidence those conversions will ever have. A field left out
of the fixture is a field nobody will notice is missing from the sheet.

**The substitute for a census is the screen that writes the payload.**
`frontend/app/logbooks/<type>.jsx` is where a field either has a control behind
it or does not. That check is what catches the class of defect a census would
otherwise find: the daily jobsite log carried a field on 50 of 59 records,
non-empty on 0 of 360, printing "N/A" on every filed log ever rendered, because
the screen declared the state and hydrated it and no control ever set it.

Any fixture file added here must say in its own header whether it was taken
from real filed records or constructed. A reader will assume the former.

## It was exercised in both directions before it was needed

`compare.py`'s healthy output is the words *Nothing was lost*.

**That is also exactly what a broken one says.** A baseline that failed to
decode, a regex that stopped matching, a record-id join that silently found
nothing — every one of those produces a clean run, and a clean run is what
everybody wants to see. It is the §12 shape wearing the name of the check
written to prevent §12.

So it was run twice against `daily_jobsite` on 2026-09-12, before any
conversion depended on it:

| | records | reporting loss |
|---|---|---|
| live tree, nothing changed | 59 of 59 joined | **0** |
| renderer with the inspections line removed | 59 of 59 joined | **59** |

In the second run it named the content, not just a count: `inspected` on all
59, then `perimeter`, `fence`, `fire`, `neighbors`, `permits`, `property`,
`plans` — the inspection item labels themselves.

**The join count printed beside the result is load-bearing.** A comparison that
matched no records would report zero losses and look identical to a clean run,
so the number of baselined records actually found in the database is printed on
its own line every time. Read it first.
