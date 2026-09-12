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
