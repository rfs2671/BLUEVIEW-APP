# Recorded plan-eval results

Each JSON file here is the unedited output of `scripts/plan_eval.py`, run inside the production container against the deployed build. A result is only recorded if the run was valid: the corpus matched the suite's baseline before and after scoring. `tests/test_recorded_eval_results.py` enforces this.

## 588 Thomas S Boyland Street, 2026-09-17

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
