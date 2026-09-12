# The investor report replacement — migration ledger

`generate_combined_report` went from 2,423 lines to 171. It fetches, resolves,
projects and renders; every judgement moved into `lib/report/`. That deleted a
design, and deleting a design breaks the tests that describe it.

**185 failures across 33 files**, measured on the wiring change before any test
was touched. This is the ledger, and it exists for one reason: when a hundred
tests disappear, somebody has to be able to prove they disappeared because the
design disappeared and not because the suite became inconvenient.

Every file gets exactly one outcome.

| outcome | meaning |
|---|---|
| **DELETE** | the subject is gone; the row names what replaced the rule |
| **MOVE** | the rule survives on the per-logbook legal renderer; the assertion follows it |
| **REWRITE** | the rule survives, the implementation changed; the assertion is re-aimed |
| **STRENGTHEN** | the architecture now guarantees MORE than the old test asked; the assertion gets harder |

**STRENGTHEN is the category to watch.** A test that can only be made green by
weakening it should have become stronger instead. Three files are in it, and
each one is a case where the old report merely promised to be careful and the
new one is structurally incapable of the thing.

## How the classification was made

Not from memory. Each file was read for two facts: how many times it renders
`generate_combined_report`, and how many times it renders
`generate_single_logbook_html`. A file that only ever rendered the report is
describing a design that is gone. A file that renders both was asserting that
two renderers agreed, and there is only one of them now — which is a REWRITE,
because "both carry the guard" becomes "the one that remains carries it".

The dominant failure mode is `ValueError: substring not found`: source-text
tests slicing the old function body by an anchor that no longer exists.

---

## The ledger

| n | file | outcome | replacement assertion |
|---:|---|---|---|
| 26 | `test_investor_page_one.py` | DELETE | the old page 1 is gone. The five-cell rail, the executive block, the activity rows and the collapse rules are asserted in `test_report_view.py` and `test_report_renderer.py` |
| 25 | `test_report_six_defects.py` | MOVE | already half-migrated once; the remaining report-side assertions follow the same six content rules onto the legal render |
| 23 | `test_the_cover_is_four_tiles_and_two_columns.py` | DELETE | the four-tile cover is gone. Its successor is the banner plus the five-cell rail, asserted in `test_report_renderer.py::TheBanner` and `TheRail` |
| 20 | `test_report_document_layout.py` | DELETE | the section/page structure it describes is gone. Page counts on four day shapes are asserted in `test_report_renderer.py::ThePageCount` |
| 16 | `test_the_project_record_indexes_the_filing.py` | DELETE | the old page-4 grid is gone. Card states, equal heights, absent-record panels and the two denominators are asserted in `test_report_renderer.py::TheRegisterReadsLikeARegister` |
| 10 | `test_a_band_never_loses_its_photographs.py` | DELETE | the old band layout is gone. Column shapes, row allocation, the floor and ceiling, and contain-not-crop are asserted in `test_report_renderer.py::ThePhotoBandRules` |
| 8 | `test_osha_review_column.py` | MOVE | the register's review column still exists on the legal render |
| 6 | `test_report_no_double_render.py` | STRENGTHEN | it asserted a document is not printed twice. The report now embeds NO document at all, so the assertion becomes that no filed document's body is reachable from the investor render |
| 6 | `test_preshift_purpose_line.py` | MOVE | the purpose line is on the pre-shift sheet, which the legal renderer still prints |
| 6 | `test_orientation_section.py` | DELETE | the orientation section is gone. Its two surviving figures are asserted as facts on the orientation card |
| 5 | `test_report_legal_vs_investor.py` | STRENGTHEN | it asserted every reachable signature call passes `show_affirmation=False`. The investor render reaches NO signature renderer at all now, and that is what it should say. Its own vacuity guard already fires, correctly |
| 3 | `test_preshift_signature_reads_signin_id.py` | MOVE | the sign-in identity rule is the legal sheet's |
| 2 | `test_the_report_number_is_issued_once.py` | REWRITE | the number is issued once, unchanged; the line moved from the old header into the banner's dateline |
| 2 | `test_the_dead_superintendent_section_is_gone.py` | DELETE | it asserted one section's absence. Every section is absent now, and `test_report_no_double_render.py` asserts that generally |
| 2 | `test_report_cover_signature_and_name.py` | STRENGTHEN | the cover carried a signature and a name. The investor report carries no signature at all, which is the stronger claim and the one to assert |
| 2 | `test_preshift_affirmation_record.py` | MOVE | the affirmation record is the sheet's |
| 2 | `test_photo_purge.py` | REWRITE | **a purged photograph still emits a URL** — the rule that matters, unchanged. Only the rendition token moved, from `?v=thumb` to `?v=enhanced` |
| 2 | `test_osha_ocr_null_boundary.py` | REWRITE | "both pre-shift renderers carry the guard" becomes "the one that remains carries it" |
| 2 | `test_inspection_results_on_filed_documents.py` | MOVE | a failed inspection must not print as a passed one, on the filed document |
| 2 | `test_answers_render_as_answers.py` | MOVE | an answered No must not read as nobody answered |
| 2 | `test_amendment_photos_on_the_report.py` | REWRITE | the photographs belong to the document the report prints. The report prints none, so they belong to the document the index LINKS to — the same rule one click along |
| 2 | `test_amendment_is_visible.py` | REWRITE | an amended record still says it was amended, on the document the card links to |
| 1 | `test_weather_display_and_chip_trade.py` | MOVE | the weather helper is shared; the report half is gone |
| 1 | `test_superintendent_log.py` | MOVE | the log is its own document |
| 1 | `test_submit_no_content_gate.py` | MOVE | the blank-record backstop is the legal render's |
| 1 | `test_signature_block_and_captions.py` | MOVE | the signature block belongs to the filed document |
| 1 | `test_osha_cert_type_is_stored.py` | MOVE | the Cert Type column is the register's |
| 1 | `test_logbook_renderers.py` | MOVE | one remaining report-side assertion in a file that is otherwise already about the legal render |
| 1 | `test_headcount_provenance_on_the_filed_log.py` | MOVE | the filed log says which headcount came from where; the investor side of that is now the five reconciliation states |
| 1 | `test_filed_log_photo_append.py` | REWRITE | already migrated once when the marker moved; one report-side anchor remains |
| 1 | `test_eastern_clock.py` | MOVE | already migrated once; the roster clock is the legal sheet's |
| 1 | `test_cs_attribution.py` | MOVE | the attribution is the superintendent log's |
| 1 | `test_an_assertion_may_not_print_a_source_file.py` | REWRITE | a harness gate, not a report test. Its census of source-slicing assertions changed when the body it sliced disappeared |

**Counts:** DELETE 7 files / 103 tests · MOVE 16 / 57 · REWRITE 7 / 12 ·
STRENGTHEN 3 / 13.

---

## What the new suites already assert

So a row reading "asserted in the renderer tests" can be checked rather than
believed.

| suite | holds |
|---|---|
| `test_location_vocabulary.py` | the normalisation table, the three protections, the four rail shapes, project overrides |
| `test_report_model.py` | the five reconciliation states, the recorded zero, the Eastern-day window across the UTC rollover and daylight saving, safety refusing to infer, the two denominators |
| `test_report_view.py` | nothing raw reaches a template, the five rail cells, sections collapsing, the rendition order, one statement across two pages |
| `test_report_renderer.py` | the input contract by introspection, page counts on four day shapes, contain-not-crop, equal card rows, the palette by class, the banner on Pages 1 and 3 only |
| `test_the_legal_apparatus_markers.py` | every registered filing marker absent from the investor render and present on the legal one |

---

## Rules that must not be lost

Named before the grind, because a careless delete takes these with it. Each
must end up asserted somewhere by the time the ledger is closed.

- **A purged photograph still emits a URL.** It used to render only when
  `base64` was present, so a purged one did not render broken — it VANISHED,
  and the report read as no photographs taken on a day photographs were taken.
- **The report number line says when it is assigned** rather than going blank
  before a send.
- **A nameless roster row does not print**, on the toolbox talk and the OSHA
  register, because the claim there is about a named person.
- **An unrecorded inspection result is not a pass**, and an unanswered
  impact-loaded question is not a No.
- **`answer_label` renders both words**, never a glyph against a word in one
  column.
- **The New York clock on a roster**, including the winter offset.
- **One record, one render.** Now stronger: no record is embedded at all.
- **The two headcounts stay labelled** — the conducting party's and the
  gate's — and neither is silently preferred.

---

## The acceptance bar this ledger is not a substitute for

Six control days through the production entry point: the reference day, a
sparse photograph day, a heavy photograph day, a day with no photographs, a
sitewide-only day and an unmapped-only day. Page counts, and the presence or
absence of the key labels. Plus one assertion that the old report is dead — a
distinctive string from the old cover must not appear in any rendered output.

The ledger explains the deletions. The six days prove the replacement.

---

## What the grind actually found

The classification above was made by reading. Doing the work changed six rows
and turned up four things nobody had asked about. They are recorded here rather
than folded silently into a diff.

### Reclassifications

| file | ledger said | became | why |
|---|---|---|---|
| `test_answers_render_as_answers.py` | MOVE | MOVE, minus one DELETE | sites 4 and 8 moved. **Site 7 had no destination**: it was the report's catch-all, which dumped any unhandled log type as `key: value` pairs, and that is where a nested boolean reached paper as `flag: True`. Nothing renders a dictionary generically any more. Measured: all 13 types in `LOGBOOK_TYPE_REGISTRY` have a branch or a schema, so the filed renderer's own `else` is unreachable |
| `test_report_six_defects.py` | MOVE | MOVE + 3 DELETE + 1 skip | three classes were about the old cover; the per-subcontractor sentence generator is deliberately **not wired** to the new executive summary and its test is skipped with that reason rather than quietly re-pointed |
| `test_amendment_is_visible.py` | REWRITE ("on the document the card links to") | REWRITE, and it needed a code change | see below |
| `test_weather_display_and_chip_trade.py` | MOVE | REWRITE, and it needed a code change | see below |
| `test_report_no_double_render.py` | STRENGTHEN | STRENGTHEN, aimed elsewhere | the two-lists-must-agree defect survives between `LOGBOOK_TYPE_REGISTRY` and the filed renderer's branch chain, which is a sharper target than "no body is reachable" |
| `test_report_legal_vs_investor.py` | STRENGTHEN | STRENGTHEN | the walk is kept and **inverted**: zero signature calls reachable from the report, and the same walk still returns nine from the filed renderer, so an empty result is evidence rather than a broken walk |

### Two defects the migration introduced, found by the tests and fixed

**The cover's weather stopped reading `weather_fetch_state`.** The thin caller
rebuilt the line out of `weather`, `weather_temp` and `weather_wind`, so a day
whose fetch FAILED — which the old cover printed as "Weather could not be
retrieved" — rendered as "Not recorded". Those are different claims about the
same record: one says the instrument broke, the other says nobody looked. Now
routed through `_display_weather`, which is the only thing that reads that
field. Found by the census test that exists for exactly this.

**`amendment_sentence` lost its only reader.** `amendment_reason` being
write-only is the defect `test_amendment_is_visible.py` was written to fix, and
removing the report's header put it straight back — the sentence justifying a
change to a signed 3301.2 record existed only in Mongo again. It now prints at
the top of the **filed document**, which is where the operator's standing ruling
puts filing apparatus, and that placement covers **every log type**: the
report's header read `daily_jobsite` and nothing else, so an amended toolbox
talk, OSHA register or pre-shift sheet announced itself nowhere.

### Three things that are gone from the product

Not defects, not fixed here, and each one is a decision somebody should take
deliberately rather than discover.

1. **The OSHA Review column.** It joined the stored register to the worker's
   card record and existed ONLY on the report's embedded copy — the filed PDF
   never had it. `osha_review_cell` and `osha_review_index` now have no call
   site. Ten tests in `test_osha_review_column.py` are skipped naming this.
2. **`legal_record=False` has no caller.** The flag takes the AFFIRMED banner,
   the BC 3301.13.13 citations and the attestation off the superintendent's
   log, and the report's embedded copy was the only thing that ever asked for
   that. Pinned at zero rather than deleted: removing a gate on a §3301 filing's
   audit apparatus is its own change. The assertion fails the day a new caller
   switches it off without a decision.
3. **Two smaller losses of the redesign**, both visible in the approved
   mockups: photographs are embedded at the enhanced rendition with no
   click-through link to a larger copy, and activity rows print company, trade,
   location and the two headcounts but not `work_description`.

### One inconsistency observed and left alone

The SSC daily safety log's own filed PDF prints its `weather` field raw rather
than through `_display_weather`. That predates this work and is out of its
scope; it is written down so the next reader of the weather census is not
surprised by a fourth call site that isn't there.

---

## What the six control days found

Rendered in the production container, through the real entry point, against
production Mongo. Every helper the report calls is the deployed one; only
`lib/report/` and `generate_combined_report` itself come from the branch.

| shape | date | pages | photographs | banned strings |
|---|---|---:|---:|---|
| reference | 2026-08-27 | 3 | 8 | none |
| heavy photographs | 2026-08-31 | 3 | 13 | none |
| sparse photographs | 2026-08-19 | 3 | 2 | none |
| no photographs | 2026-07-29 | **2** | 0 | none |
| sitewide location present | 2026-08-26 | 3 | 3 | none |
| unmapped location (`J`) | 2026-08-17 | 3 | 2 | none |
| sent and numbered (#29) | 2026-09-10 | 3 | 10 | none |

**Two pages on the no-photograph day is correct**, not a miss: `render_page_2`
returns nothing when there is no evidence, which is the empty-section rule the
redesign exists for.

**THE BANS HOLD.** `WORKERS AT THE GATE` (the old cover's distinctive cell),
`Additional Logbooks` (the sweep's heading) and `Site Superintendent Log
(BC 3301.13.13)` (an embedded section's heading) appear in none of the seven
renders.

**The exclusive location shapes do not exist in production.** Of 32 days on the
reference project, ONE carries a sitewide location and NONE carries an unmapped
one; across all 59 daily jobsite logs there are 85 located rows and 2 unmapped
values, both `J`, both on one day of another project. Those two days were used
rather than synthesised, and labelled for what they are.

### One layout defect, found on paper and fixed

**Safety was indented under a full-width rule.** Attention and Safety share a
row at 58/42. On a day with nothing outstanding the left cell is empty, and a
58% empty cell is not nothing — it pushes Safety into the middle of the sheet
below a rule that spans the page, which reads as a section whose first half
failed to print. Seen on the 10 September report, where 5 of 5 required logs
were filed. The row now collapses to one full-width block, and
`test_report_renderer.py` asserts both the collapse and the control.

### One finding that is not this change's to fix

**Two fifths of every stored photograph is black.** Measured on all three
renditions of one record:

| rendition | stored | black top | black bottom | picture |
|---|---|---:|---:|---|
| original | 1280 × 2849 | 568 | 569 | 1280 × 1712 |
| enhanced | 809 × 1800 | 353 | 354 | 809 × 1093 |
| thumb | 180 × 400 | 78 | 78 | 180 × 244 |

The picture itself is an ordinary 3:4 portrait; it is padded onto a 0.449
canvas — roughly a phone's full screen aspect — with the bars baked in, at
capture. Nothing in `lib/report/` can add a pixel, and `contain` is doing
exactly what it is asked. The consequence is that the evidence page devotes
about 40% of every cell to black, which is most of why Page 2 reads thin.

**The serving ladder is NOT at fault and was checked.** Over HTTP, the path
WeasyPrint actually takes, `?v=enhanced` returns the 809 × 1800 object,
166,982 bytes. An earlier in-process reading that appeared to show a thumbnail
being served was an artefact of a script that never ran the startup event and
so had no R2 client. The operator's ruling — never fall back to a thumbnail for
size alone — is intact.
