# What the matcher's tests were holding, and where each part went

The keyword matcher is deleted: `question_kind`, `QUERY_SYNONYMS`,
`ATTRIBUTE_PATTERNS`, `TAG_SYNONYMS`, `_one_edit_apart`, the `answer_*`
functions, `_classify_plan_question`, `_pages_with_element`, the VQA candidate
loop and the RRF retrieval. Its tests went with it, and this file is the
receipt: every test that encoded a **real observed failure** is named here with
where that failure is guarded now, or with a plain statement that it is not.

Nothing was dropped because it was inconvenient. Where a behaviour is gone, it
says so, and the eval asks the question anyway so the loss stays measurable.

## 1. Live failures, now eval cases

These came from live tests in the group chat. The eval asks the same question
of the same project and checks the records that come back against what the
sheets print.

| observed, and when | was held by | is held by |
|---|---|---|
| "How many PTAC units" answered **41** — the sum of a quantity column, printed on no cell | `test_plan_live_defects_2026_09_15` (D5b), `test_plan_chunks_first`, `test_plan_index_v3` | eval `ptac-count` (expects 21, 9, 11), plus the gate. The D5b test now asserts the opposite: `answer_is_grounded` REFUSES 41 and allows the three stated quantities |
| "What type of AC units in this project?" answered from a boilerplate note | `test_plan_live_defects_2026_09_15` (D5), `test_plan_chunks_first` | eval `ac-type` — the suite's one failing case, known failure class `boilerplate_outranks_specific` |
| "How many roof drains?" found nothing, then found the FLOOR drain count | `test_plan_chunks_first`, `test_plan_live_defects_2026_09_15` (D8, D4) | eval `roof-drain-count`; coverage ranking keeps both words in play (tested in D4) |
| "Whats the helical piles" / "What piles used on site?" never reached the index | `test_plan_chunks_first` | eval `pile-type`. There is no classifier left to decide whether to look |
| "What's the stucco thickness?" answered with a scale bar | `test_plan_live_defects_2026_09_15` (D6), `test_plan_index_v3` | eval `stucco-wall-assembly` — the drawings state the assembly and no thickness |
| "post guage" — stud gauge not found | `test_plan_live_defects_2026_09_15` (D4), `test_plan_index_v3`, `test_plan_chunks_first` | eval `stud-gauge` — **new**. A-500.00 prints `3 1/2" METAL STUD 16" O.C. 20 GAUGE MIN.` |
| "What's the hight of the sidewalk shed?" | `test_plan_live_defects_2026_09_15` (D4) | eval `sidewalk-shed-height` — **new, and it FAILS**: four records that print the phrase crowd out the one that prints `8' HIGH SHED`. Known class `a_mention_outranks_the_measurement` — see §5 |
| "What about roof protection?" | `test_plan_live_defects_2026_09_15` (D4) | eval `roof-protection` — **new**. SSP-003.00/004.00/005.00/009.00/011.00 |
| "are there chase walls" → "Yes — … A-105.01", quoting `CONC. WALL`, citing `?` | `test_an_answer_says_where_it_came_from`, `test_plan_chunks_first` | eval `chase-walls-absent` — **new**. CHASE is on no current page and in no record quote of the 12,040 on them. The old test asserted the answer "Yes" |
| An answer cited `?` for a page with no sheet number | `test_an_answer_says_where_it_came_from` | the same file, rewritten against `plan_search.cite` and both renders. It found two live bugs while being rewritten — see §4 |
| An answer cited a drawing that had been deleted | `test_plan_query_skips_deleted_files` | the same file, rewritten against `search_plans` → `_current_record_page_ids` |
| "show me s-001" sent S-002 and M-001 | `test_plan_live_defects_2026_09_15` (D1) | unchanged — `_find_named_sheet`, still an exact lookup, still tested through the handler |
| A bare "show me" sent the agent's guessed sheet | `test_plan_live_defects_2026_09_15` (D2) | unchanged — `_is_bare_show_request`. The rewritten handler dropped this guard and D2 caught it |

New cases were verified against the text layer of all 111 current pages and
every record quote on them, read on 2026-09-17 — not against the pipeline's
own answers.

## 2. Rules that moved rather than went

| rule | was | is |
|---|---|---|
| A short term must start a word — `air` is not STAIRS, `ac` is not SPACE | `_pages_with_element`, `test_plan_chunks_first` | `plan_search.term_pattern`, tested in `test_live_defects_2026_09_14_2102` and D5 |
| A plural finds the singular — `drains` finds ROOF DRAIN | same | `plan_search.term_forms`, same tests. The `gas` → `GA` guard is kept, at the same three-letter floor |
| Stopwords are stripped from the subject | `_element_terms` | `plan_search.search_terms` |
| Every term must appear before any term does | `_pages_with_element`'s `$and` | `search_plans` fetches all-term matches in full before any-term ones, and coverage is the first thing `rank` sorts on |
| A number read off a picture says so | `schedule_needs_verifying` — a heuristic comparing a vision schedule's cells against the page text | the record's tier. A vision-read record is `vision_read` and both renders say so. Tier follows source is enforced in `emit` (#585), so it cannot be claimed away |
| A tag count is never a stated total | `answer_tag_count`'s wording | `count_basis: tag_occurrences`, tiered at `tag_legend`, which says on its face what it is |
| Three pile TYPES is not three piles | `answer_count`'s `schedule_rows` | a schedule's rows are quoted as rows; nothing sums them, and the gate refuses a total no cell prints |
| A sheet is sent only when it mentions the thing | `_pages_with_element` | `_pages_for_records` — the sheet sent is the sheet the returned records are on |
| The readers exclude superseded and deleted pages | four readers, one filter each | `_current_record_page_ids`, one place, `test_plan_index_v3` |

## 3. Behaviour that is gone, and not replaced

**Typo tolerance.** `_one_edit_apart` accepted one edit against a small
attribute vocabulary: `guage`→gauge, `thicknes`→thickness, `hight`→height.
`search_terms` matches words as the sheet prints them, with plurals and
nothing else. **A misspelt question now returns less, or nothing.**

Both live questions that were misspelt are in the eval under their correct
spelling, so the eval does not paper over the loss either. The honest options
if it is worth restoring are a spell-check on the way in or an agent that
rephrases and asks again — neither belongs in the ranker.

**A compound written apart.** The matcher normalised `SIDE WALK` to
`sidewalk`. Nothing does now; asserted as a loss in D4. SSP-013.00 prints
`8' HIGH SIDE WALK SHED`, and three other sheets print the same height with
the word closed up — so this is not what made the case fail. See §5.

**The head-noun retry.** "sidewalk shed" falling back to "shed" when the
phrase found nothing. Coverage ranking does most of that job without a second
query: a record matching both words outranks one matching either, and the one
matching only "shed" ranks below it rather than being dropped. What the eval
showed is that "below it" and "returned" are not the same thing — with a limit
of 8 and five sheets printing the phrase, the shed's HEIGHT never came back.
See §5.

**Question classification.** `question_kind` decided whether a question was a
count, an existence check or an attribute lookup, and that decided the shape
of the answer. The agent composes now, so the shape is its business. `intent`
is passed to `search_plans` as a hint that only ORDERS records; it never
filters them, and nothing decides whether to look.

**The synonym table.** `QUERY_SYNONYMS` mapped `ac`→`ptac` and others by hand.
Nothing replaces it. The eval shows the cost precisely: `ac-type` fails, and
the printed route to that answer — EN-001.00's
`PACKAGED TERMINAL AIR CONDITIONERS` — is found without any synonym, by the
case that asks for it in the words the sheet uses.

**The WhatsApp vision budget.** `_vision_budget_exceeded` capped
`_qwen_visual_qa` at 300 calls per project per day. There is no per-question
vision call left to cap. Indexing was always metered separately and is
untouched; `lib/vision_meter` keeps the `VISION_WHATSAPP_VQA` endpoint name so
the rows already written can still be read.

**The chunk fixture.** `tests/fixtures/boyland_page_chunks_2026_09_16.json.gz`
was 121 pages of real production chunks, and the eight questions
`test_plan_chunks_first` asked of it are the eight in §1. It is deleted with
that file: it was written before the 2026-09-17 re-index, so it is a snapshot
of a corpus that no longer exists, and the eval asks the same questions of the
corpus that does.

## 4. Two live bugs the migration found

Rewriting `test_an_answer_says_where_it_came_from` against the renders that
ship today failed twice before it passed:

1. `render_records` treated a whitespace sheet number as a sheet number, so a
   page with `"   "` in its title block cited an empty string. `cite` strips.
2. `_render_records_for_model` fell back to `p{page_number}` with no file
   name, and printed `pNone` when there was no page number either — handed to
   the model as evidence, which is how `?` reached a person in the first
   place. It uses the same `cite` now, and a record that cannot say where it
   is is not offered as evidence at all.

## 5. What the eval said, and the one thing it did not carry

Run 2026-09-17 against the frozen corpus, `eval/results/boyland-2026-09-17-matcher-deleted.json`:
**20 of 22 scored cases pass.** Every one of the 18 cases scored before the
deletion returned the same verdict, case for case — nothing regressed. Of the
four migrated cases, three pass on the first run: `stud-gauge`,
`roof-protection`, `chase-walls-absent`.

`sidewalk-shed-height` fails, and it is worth being exact about why, because
it is the one behaviour the matcher had that nothing here replaces.

Asked how high the sidewalk shed is, the reader returned four records that
print the phrase — `SIDEWALK SHED`, `SIDEWALK SHED PARAPET PANEL LAYOUT`,
`TYPICAL SIDEWALK SHED ELEVATION`, and a permit note — and never returned
`8' HIGH SHED`, which is printed on three sheets. Coverage counts words, and a
record that merely names the subject covers the subject perfectly.

The matcher answered this by looking for a VALUE NEAR THE TERM
(`answer_attribute`), off a hand-written vocabulary of attribute words that
also forgave the typo. The vocabulary is what made it unextendable. The idea
that an attribute question wants a record STATING a value is not, and the
records carry enough to act on it without a word list. Recorded as known
failure class `a_mention_outranks_the_measurement`, with the lead for a
principled fix beside it in `eval/boyland.json`, and deliberately not tuned:
the ranking rule it would bend is the one that fixed the boilerplate cases.
