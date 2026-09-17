# Recorded plan-eval results

Each JSON file here is the unedited output of `scripts/plan_eval.py`, run against the production corpus. Each section says which CODE produced it — a deployed build, or a working tree run through `railway run` — because the two are not the same claim. A result is only recorded if the run was valid: the corpus matched the suite's baseline before and after scoring. `tests/test_recorded_eval_results.py` enforces this.

## 588 Thomas S Boyland Street, 2026-09-17 — after the matcher was deleted

| | |
|---|---|
| file | `boyland-2026-09-17-matcher-deleted.json` |
| code | the working tree of the matcher-deletion branch, **not a deployed build** — run with `railway run`, so production environment and production corpus, local code. The deployed build at the time was `d3e80a43` (#589) |
| ran | 19:39:54Z |
| corpus | 129 pages, 111 current, 15,369 records; newest write 06:29:02Z; **identical to the run below, and unchanged across this run** |
| suite | `eval/boyland.json`, 24 cases — the 20 of the run below plus four migrated from the deleted matcher's tests |

**20 of 22 scored cases pass (0.909). 2 are stale and not scored. Both failures are in known classes.**

| kind | scored | passed |
|---|---|---|
| answer | 17 | 15 |
| absent | 5 | 5 |

**Nothing regressed.** The 18 cases the run below scored returned the same verdicts, case for case: 17 pass, `ac-type` fails, the two PTAC cases are stale. What moved is the denominator.

**The four new cases** come from `eval/migrated-from-the-matcher.md`, each one a question that failed live in the group chat and was pinned by a test that is now deleted:

| case | verdict |
|---|---|
| `stud-gauge` — "what gauge are the metal studs" | PASS, A-500.00, text_layer |
| `roof-protection` — "what roof protection is on the drawings" | PASS, SSP-003.00, tag_legend |
| `chase-walls-absent` — "are there chase walls" | PASS, nothing quotes it |
| `sidewalk-shed-height` — "how high is the sidewalk shed" | **FAIL** |

**The new failure, and why it is not tuned away.** `sidewalk-shed-height` returned four records that print the phrase — `SIDEWALK SHED`, `SIDEWALK SHED PARAPET PANEL LAYOUT`, `TYPICAL SIDEWALK SHED ELEVATION`, and a permit note — and never returned `8' HIGH SHED`, which is printed on SSP-003.00, SSP-004.00 and SSP-005.00. Coverage counts words, and a record that merely names the subject covers the subject perfectly. Recorded as class `a_mention_outranks_the_measurement`; the lead for a principled fix is in the suite beside it.

The matcher answered this one, by looking for a value near the term — with a hand-written attribute vocabulary that also forgave the live typo "hight". Both halves are gone. This is the half worth rebuilding, with its own cases.

**An open item this run leaves.** `chase-walls-absent` passes — nothing quotes "chase wall", and the gate refuses an invented number — but the fallback render for it still opens `Chase wall — on the drawings:` over four records whose only tie to the question is the word "wall". That header is the 2026-09-16 defect in miniature: it asserts the subject is on the drawings when only part of the subject matched. The composing model is the usual path and is shown the quotes, so this is the fallback only; the fix is to make the header conditional on a record matching every term of the subject. Not done here — it is a render change and belongs with its own cases.

**Known limits** are unchanged from the run below, plus one: this result is from the working tree rather than a deployed build. The path it scores — `search_plans`, `rank`, the gate, `render_records` — differs from `d3e80a43` only in `plan_search.cite`, which changes a citation for a page whose sheet number is blank or whitespace and nothing else.

---

## 588 Thomas S Boyland Street, 2026-09-17

*(the run this one is compared against)*

| | |
|---|---|
| file | `boyland-2026-09-17-d3e80a43.json` |
| build | `d3e80a43` (#589), deployed 17:28:57Z |
| ran | 17:59:12Z, inside the Railway container |
| corpus | 129 pages, 111 current, 15,369 records; newest write 06:29:02Z; unchanged across the run |
| suite | `eval/boyland.json`, 20 cases |

**17 of 18 scored cases pass (0.944). 2 are stale and not scored.**

| kind | scored | passed |
|---|---|---|
| answer | 14 | 13 |
| absent | 4 | 4 |

**The failure.** `ac-type` fails and is a known failure (class `boilerplate_outranks_specific`). The notes printed on M-100.00 through M-105.00, which read "EACH AC UNIT SHALL HAVE A MINI-CONDENSATE PUMP", match both words of the question, while the PTAC schedule matches only one. Boyland has PTACs only; those notes are engineer boilerplate that was never stripped. The case is still counted as a failure.

**The two stale cases.** `ptac-count` and `ptac-make-and-model` both lead with PTAC-1, PTAC-2 and PTAC-3 on M-200.00. Those three elements were promoted to `schedule_cell` from a vision-read schedule, which is the defect #585 fixes in code but which is still in this corpus. They are the only stale records; the other two stale classes measure 0.

**How the score got here**, over the same frozen corpus:

| build | scored | passed | stale | rate |
|---|---|---|---|---|
| #587 (harness + label rule) | 17 | 13 | 3 | 0.765 |
| #589 (ranking), run locally before merge | 18 | 17 | 2 | 0.944 |
| **#589, deployed, this record** | **18** | **17** | **2** | **0.944** |

**Known limits of this result:**
- It covers a single project.
- It scores `search_plans` and the answer gate, not the composing model.
- For absent cases, the ground truth is the text layer plus every stored record's quote.
- Seven current pages have no sheet number.

**Open items this run leaves:**
- **Duplicate roof-drain count.** The count is stored twice: once on A-105.01, and once on the AR gas-change page, which reissues the same roof plan. That page has no sheet number, so supersession never retired it. Fixing this means changing extraction.
- **Boilerplate in vision-read notes.** They are never checked for boilerplate. A note repeated verbatim across one discipline's sheets could be handled the same way `boilerplate_lines` handles repeated text-layer lines.
- **Stale PTAC elements.** The three leave only with a full Boyland re-index under #585. A partial re-index would mix the corpus.
