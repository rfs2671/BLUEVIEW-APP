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

---

# The composition pass

The replacement was read on paper and the architecture held. What follows is
composition and typography, in the operator's own order of priority.

## 1. Page 2 — the photographs

**THE PROBLEM WAS INSIDE THE IMAGE.** The capture path writes every photograph
onto a phone-screen canvas, 0.449 wide, with the picture centred and pure black
above and below. Measured across 36 production photographs on five days: two
fifths of every stored file is bar, and the picture inside is an ordinary 3:4
portrait. No grid can fix that.

**`?v=clean`.** A rendition that removes uniformly near-black EDGES from the
enhanced object and caches the result under its own prefix. Every stored key is
untouched, so the filed document keeps the frame the camera wrote and the
investor report gets the composition. Run over all 36: every one trimmed, 39-40%
removed, resulting aspect between 0.737 and 0.749 against a phone portrait's
0.750.

The refusals are the interesting half and they are what `test_the_clean_rendition.py`
is mostly about: a photograph with no padding is served byte-for-byte and never
re-encoded; a genuinely dark photograph is left whole rather than cropped to its
one lit corner; an entirely black frame stays black; anything unreadable is
served exactly as filed. A crop that is too eager edits evidence.

**AND THE GRID FOLLOWED.** Cropping changed the geometry the layout was designed
for, and two things broke at once:

| | before | after |
|---|---|---|
| cell | a fraction of the page wide, whatever was in it | the size of the photograph |
| four photographs | two-by-two | one row of four |
| columns | fixed by count | chosen against the height the page can give |
| band header | four stacked lines, 0.76in | two lines, 0.606in, measured |

The column count is now a small exhaustive search: for every assignment it
computes what each photograph would actually measure -- height from the row
allocation, width from the column's share of the page, whichever binds first --
and keeps the most printed photograph. That fixes both ends of the range at
once. One band of ten went from five across at 1.9in to four across at 2.4in;
four bands of 4/3/2/4 stopped leaving a third of the sheet grey.

## 2. Page 3 — the register

Seven cards in three columns left one card beside two empty cells with the
completeness figures floating below the grid. The figures moved into the empty
cells, at the card's own height and border, so the row reads as a row. Six or
eight cards leave no room for it and it falls back underneath -- the same block,
one row down.

The document window grew a third taller, 0.74in to 0.98in, because at 0.74 every
filed card showed the same navy band and seven cards read as seven identical
rectangles. A card that carries FACTS gives 0.28in of that back: the orientation
card has two fact lines under a two-line title and overflowed its row, printing
its link across the block below. Between a taller picture and a readable figure
the figure wins.

## 3. Page 1 — vertical adaptation

**THE SPACING IS A FUNCTION OF WHAT IS ON THE PAGE.** A single generous set of
paddings cannot satisfy both halves of "fill a sparse page" and "fit a full
one": the same 10-15% increase that filled the 10 September page -- one
activity, nothing outstanding -- pushed the 31 August page onto a second sheet.
Three densities, chosen once in the renderer from the blocks it is about to lay
out:

| | weight | |
|---|---|---|
| `air` | 0-2 | the generous set |
| `mid` | 3-4 | between |
| `tight` | 5+ | the pre-polish page, restored IN FULL |

"In full" is load-bearing: the first attempt rolled the paddings back and left
the type sizes grown, and a five-activity day at 8 Prescott Place still put
Attention and Safety alone on a second sheet. Every number the polish moved is
moved back.

`test_report_renderer.py` renders page 1 at nine activity counts and requires
one sheet each, and asserts the density is monotonic so that one rendered check
per shape is enough.

## 4. The rail, the safety block, and the type

* **The rail** lost its vertical dividers -- space separates the cells now --
  and gained padding, a bigger numeral (27px to 31px) and a quieter label with
  a third less tracking.
* **Safety is a line when it is clear and a panel when it needs explaining.** A
  bordered box whose whole content is the word "Clear" reads as emphasis on
  nothing. "Status not reported", with the sentence saying why, keeps the panel.
* **The smallest text came up about a point** and the extreme letter-spacing
  came back: card citations, photo metadata, the completeness note and the
  secondary rail line were texture rather than information at reading distance.
  The footer went from 6.5px to 8px.
* **Two prose defects, both found on paper.** "across 1 trade" beside "Eleven
  workers" in one sentence, and "AAZ and Arkon Builders and Power Direct and
  Quality Plumbing" from a bare join.

---

# Page 1, recomposed

Operator ruling, 12 September: the semantic architecture of `aa17e483` is
frozen and page 1 is re-dressed against a supplied reference. Skin only.
`model.py` is untouched, the view's resolution is untouched, pages 2 and 3 are
untouched, and everything below is scoped to `.p1` so a bare selector cannot
reach the register.

## What moved

| | before | after |
|---|---|---|
| head | one navy banner, shared with page 3 | a white masthead over a navy hero |
| rail | five cells, no separators | hairline separators, 32px figure, quieter label |
| summary | full width | 64%, with a grey weather panel at 36% |
| activity | a table row per activity | a typographic block per activity |
| gate workforce | a labelled strip row | a caption of the activity section |
| weather under activity | printed again | removed; the panel is the primary presentation |
| footer | none | pinned to the foot of the sheet |

## Two things the reference asked for that the view could not supply

Reported rather than reached for. Both were then ruled on, in opposite
directions, and the answers are recorded here because the reasoning is the
useful part.

### 1. The weather hierarchy — APPROVED, and built

The reference sets condition, temperature and wind apart. The view carried ONE
composed string from `_display_weather`, and splitting it in the renderer would
have been the layout layer deciding what a piece of a resolved string means.

RULED: *"Have `_display_weather` keep returning the exact same composed string
for compatibility, but also expose structured condition, temperature, and wind
values from the same resolved data. That is a justified view-model change
because it improves presentation without changing data resolution."*

`_weather_parts` now holds every rule the helper had — the fetch-state check,
the stripping, the two kinds of absence — and `_display_weather` is one line
that composes from it. There is ONE resolution in two shapes, not two
resolutions that agree today.

**The fetch-failure case offers no parts at all**, and that is the case worth
reading. The helper's rule is that `offline` or `error` wins over whatever
`weather` and `weather_temp` hold, because a stale value beside "could not be
retrieved" is two claims about one reading. Parts that survived that check would
put a temperature on a page whose own panel says there is no reading.

`WeatherView.detailed` is the only question the template may ask. A panel that
tested the three fields itself could assemble a reading out of whichever
happened to be non-empty; it asks whether there is a breakdown and prints the
sentence when there is not.

The compatibility claim is asserted rather than promised: ten record shapes,
each checked that `_display_weather` and `_weather_parts(...).line` agree.

**And the weather census now counts the resolution, not a name.** It counted
`_display_weather(` alone and would have reported the investor page as having
drifted away from the helper when it had only asked for the other shape.

### 2. Trade and work description — DECLINED

RULED: *"Do not add it yet. The current activity block is enough for Page 1.
Don't expand `ActivityRowView` just to imitate the reference unless we later
decide the report actually needs that information."*

`ActivityRowView` is unchanged: company, location, statement, chip.

### And one gate that fired correctly on the way through

`VIEW_TYPES` — the list of things a renderer helper may be handed — was thirteen
names written by hand, and the first view object added after it was written
failed for being absent from the list rather than for being wrong. **A
hand-kept allowlist turns every legitimate addition into a false positive**, and
a reader who has seen two of those starts adding names without reading the gate.
It is derived from `view.py`'s own dataclasses and enums now, with a vacuity
guard and a check that nothing from outside the view layer is admitted.

## The tagline

"Construction Intelligence for a Higher Standard" is struck by name and
replaced with "Site Oversight & Compliance" -- what the company does, which the
document then demonstrates. A test bans the struck line, and "Building Better
Together", from the whole rendered document.

## Page 1 and page 3 no longer share a head

They cannot: page 1 moves and page 3 does not. `render_banner` is byte-for-byte
what it was and is page 3's alone.

WHAT REPLACED THE SHARED-BLOCK TEST is the half that mattered. Two heads may
look different; they may not disagree about the facts. Both read the same
`BannerView`, and address, city, dateline and document title are asserted on
each.

**And the "printed once" rule became "stated once per region".** The old header
printed the address three times and the date twice in one block. The masthead
and the hero are two different statements -- a letterhead at 7.5px and the
document's subject at 35px -- so each states the address once, and the date
belongs to the hero alone because a letterhead carries none.

## The pagination, which took three attempts

`test_page_1_is_ONE_SHEET_on_every_shape_of_day` was **passing vacuously**: it
rendered `render_page_1` as a bare fragment with no stylesheet, so every height,
every padding and the footer's position came from nothing. It renders with the
stylesheet now, across sixteen shapes -- because whether a day has outstanding
records and whether the gate saw anyone the log does not describe each cost
about an activity row, and the airiest densities are only reachable without
them. That is the case the first tuning missed, and it is the 10 September
record.

Three mechanisms were tried for pinning the footer and the two failures are
recorded in the stylesheet beside the one that worked:

* an absolutely positioned footer reserves no space, and the last section ran
  into its rule;
* a hand-measured `min-height` on the body moved the WHOLE body to a second
  sheet the moment the measurement was a tenth of an inch out;
* a fixed-height table shell with a stretching middle row **does not stretch**
  in WeasyPrint 70 -- the table laid out at its content height and the footer
  floated a fifth of a sheet above the bottom edge.

What ships is an absolute footer in a page-height block with a measured reserve,
and a FOURTH density. Seven activities is the measured ceiling for one sheet;
the busiest day in the corpus carries five.

| | weight | |
|---|---|---|
| `air` | 0-1 | the generous set |
| `mid` | 2 | between |
| `tight` | 3-4 | |
| `dense` | 5+ | the floor; past this the page is full and says so |

---

# Page 3, recomposed

Operator ruling, 12 September: *"Keep all existing data, logic, statuses,
links, banner content, and legal-document behavior unchanged. This is a
visual/layout change only."* Pages 1 and 2 are untouched, every string still
comes from the same `CardView` and `CompletenessView`, and
`_logbook_thumbnail_url` is unchanged -- same source document, same
top-anchored clip.

## What moved

| | before | after |
|---|---|---|
| head | the navy banner | page 1's masthead over its hero |
| record | a bordered card | a typographic block in a quiet grid |
| separation | card borders | whitespace and hairlines |
| evidence | 0.98in window inside a card | up to 1.46in, in the grid |
| state | a badge with a tick | small green metadata under the evidence |
| link | "VIEW LOG" under every card | the title and the evidence carry it |
| missing | a dashed placeholder box | nothing at all, then the note, a short amber rule, NOT FILED |
| totals | a panel | a row of the register |
| footer | none; a floating timestamp | a footer, with the timestamp as its metadata |

**A missing record draws nothing where the document would be.** Not a dashed
box, not a grey panel, not an outline of a document that was not filed. Each of
those draws something where nothing exists, which on a compliance register is
the one thing the space must not do. It keeps its height so the rows stay
aligned, and that is all it keeps.

## The eleven-record ceiling, and the check that was lying

The operator set eleven records as the ceiling and said the thumbnail should
shrink to make room. Five densities do that, and the window is the only thing
that gives way: every number, title, citation and state prints at a readable
size whatever the day holds.

**COUNTING SHEETS WAS NOT ENOUGH, and that is the finding worth keeping.** Page
3 is a fixed-height block, and a fixed-height block CLIPS rather than
paginating. The first measurement reported "one sheet" for a register whose
last row and whose footer had fallen off the bottom of it — and the first real
render did exactly that: seven records went in and six came out, with no
footer. The check now counts what LANDED, by element rather than by box,
because every anonymous block inside a record inherits the record's class and
counting boxes reported fourteen records for three.

**The totals row is counted before the window is sized.** It goes in the cells
the last row does not use; with fewer than two of those it needs a row of its
own, and that row costs the same page as a row of records. Leaving the layout
to discover that is what put five records on two sheets.

Measured budget: the head runs to about 3.1in of an 11in sheet and the footer
starts at 10.12in, so the register has roughly 7in for its rows.

## Two collisions found on paper

* **The citation printed over the second line of the title.** "Construction
  Superintendent Log" and "Subcontractor Safety Orientation" both wrap, and the
  title's fixed height was set for one line. Every height is now the two-line
  case computed from the font size rather than guessed.
* **The totals labels wrapped**, and a label broken across two lines beside a
  figure reads as two labels.

## And the banner is gone

`render_banner` and its stylesheet had no caller once page 3 took the masthead
and hero. Both are deleted rather than left behind, and the break rule for the
bordered card went with the card.

---

# Six files the migration missed, and how they were found

**CI found them, not the local suite, and the reason is worth more than the
fixes.** Two independent gaps hid them:

### 1. A local suite that reports green can be skipping the check

`test_report_cover_is_not_blank.py` and `test_report_renderer.py` are
WeasyPrint-gated: they skip where the native libraries are absent, and the
guard turns that skip into a failure under `CI`. Every local run in this
session reported the whole backend suite green while five of those tests had
never executed. The guard is written exactly for this and it worked; what
failed was reading "6,333 passed" as though it were the whole picture. **31
skipped was on the same line and I did not read it.**

### 2. The frontend runner halts on the first failing file

The CI job loops over the test files under `set -euo pipefail` and stops at the
first non-zero exit, so it reported ONE broken file when five were broken.
Running all 157 by hand found the other four. The workflow's own comments
describe this failure mode for a missing `@babel/core` -- two files had never
executed in CI even once for that reason -- and it applies to assertion
failures too.

| file | what it read |
|---|---|
| `test_report_cover_is_not_blank.py` | the email shell, the embedded sections |
| `fallProtectionModel.test.cjs` | the report's fall-protection section |
| `oshaLogModel.test.cjs` | the report's OSHA register |
| `portedFormPayloads.test.cjs` | five types' embedded sections |
| `scaffoldDrawingsOnSite.test.cjs` | a note duplicated across two renderers |
| `toolboxTalkModel.test.cjs` | the report's toolbox roster |

## The shape was the same in all six

"Both renderers agree about this rule" becomes "the one renderer that remains
carries it", plus an absence check on the other -- because "both agree"
becoming "one of them" is only safe while the other really is gone.

`reportBranch` in `portedFormPayloads` became `reportEmbedsNothing` rather than
being deleted: dropping it would have left nothing saying the third reader is
gone, and "every reader opens these keys" quietly becoming "every REMAINING
reader" is the shape that hides a reader nobody counted.

## Two claims that changed rather than moved

* **The SSC switches.** The test argued the payload must seed five flags false
  because the combined report printed a bare Yes/No with no third state. The
  renderer that remains does the OPPOSITE -- an absent flag prints "not
  recorded", because it will not assert a negative finding from a key that is
  not on the record. The requirement is unchanged and the argument is stronger:
  omit the keys and a sheet the CP filled in prints "not recorded" against every
  one. A stale comment in `server.py` still contrasted this renderer with the
  report's behaviour; it is corrected.
* **The blank cover.** "Page 1 is not just the header" is the claim worth
  keeping and is rewritten against the page that exists. The cause cannot recur
  there -- the unqualified `tr` rule matched a row of an email shell, and there
  is no shell -- so the shell rows and their exemption moved to the per-logbook
  PDF, which still is an email-style document and still carries both rules.

## And the fixture renders two pages, not three

The day in that fixture has one activity and no photographs, so the evidence
page collapses entirely. That is the design, and the assertion says so and
checks that page 2 is the register.
