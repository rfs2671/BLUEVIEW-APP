# Writing a check that can fail

Everything here was learned on this codebase, from checks that passed while the
thing they described was broken. Each entry names a real instance so it can be
read rather than taken on trust.

The one question worth asking of every assertion you write:

> **What is the smallest edit that breaks this test without breaking the
> behaviour?**

If such an edit exists, the test is pinned to a location, a spelling or a count
rather than to the property. It will fail on a correct change and pass on a
wrong one, and both of those have happened here.

And the one rule worth carrying out of this whole document, because it
generalises past this codebase entirely:

> **Design the failure so a broken CHECK and a broken SUBJECT look the same.
> Then you cannot be reassured by an instrument that is not working.**

It is stated here rather than only in §12, where it was learned. The strip
migration is the worked example: any failed verification aborts the entire run,
so when its own R2 client turned out to be `None` — a broken instrument, not
unreadable objects — it refused to delete anything and said so loudly. Had it
skipped the rows it could not check, it would have printed a clean finish over
a check that never ran.

---

> **If you read one section, read §10 — "Verify the pointer, not the report of
> the action".** It is last only because `server.py` and
> `test_weasyprint_break_inside_semantics.py` cite section numbers by number and
> renumbering would break them. It generalises further than anything above it:
> *a tool reporting its own success is describing its intent, not the world.*

> **And read §12 second.** §1 to §11 are about checks that ask the wrong
> question. §12 is about checks that ask the right question of the wrong thing —
> where the code is correct, the reasoning is correct, and the instrument is
> pointed somewhere else. Thirteen instances in two days, and they fail toward
> *"fine"*.

> **THESE RULES ARE NOT BEING FORGOTTEN. THEY ARE BEING OUTRUN.** Three rules
> written this week were each broken by their own author within hours of being
> written: §12's *do not assert on prose*, §12's *do not let an assertion print
> its container*, and §14's *every path must end in an assertion*. The last two
> in the same day as the sentence that forbids them — an `assertIn` against a
> multi-thousand-character `ast.dump`, and a probe that defined its work and
> exited zero without running it.
>
> Knowing a trap by name does not slow the hand down. The reflex reaches for
> `assertIn` before the knowledge arrives, which means a rule that lives only in
> this file is a rule that will be broken again. **Anything here worth obeying
> under time pressure needs a gate, a lint or a checklist item — something that
> fires at the moment of writing rather than a paragraph that fires when
> somebody reads back.** The checklist at the end is that mechanism for as long
> as it is actually run; the bare-literal gate is the better one, because
> nothing has to remember it.
>
> **THE COUNT IS NOW THE FINDING, NOT THE INSTANCES.** By the end of that same
> day the tally was FOUR: the unreadable-failure rule alone was broken three
> times after being written — an `assertIn` against an `ast.dump`, one against
> a 2.3MB source string in a new test, and one found in an existing test while
> repairing it — plus the probe that never ran. Every one by the author of the
> rule, on the day it was written.
>
> Four is not a run of bad luck and it will not be fixed by care. It is a
> measurement of what a paragraph is worth against a reflex, and the answer is
> nothing. **A rule that has been broken by its own author on its own day is
> not a rule yet. It is a note about a gate somebody still has to build.**


## 1. Four patterns that work

Named, so they can be cited instead of re-derived.

### `test_the_two_halves_agree` — assert a PROPERTY, not a case

Sealing a row and asking for a signature on it must be **complements**. A test
per case checks the cases somebody thought of; a test that the two halves agree
checks the relationship, and fails whichever half moves.

Reach for this whenever two pieces of code must stay in step: a writer and a
reader, a gate and its message, a projection and the guard that reads it.

### The PRECONDITION assertion — prove the bug was there

`test_the_old_form_is_the_one_that_crashed` asserts the *pre-fix* condition
before asserting the fix. It cannot pass by accident, because it fails if either
side moves.

Without it you get the control run's usual failure: the test passes, and nobody
knows whether it would have failed before.

### THE REMOVAL'S OWN REGRESSION — the first test to write when you go near it again

> **When you reintroduce anything in the neighbourhood of a thing that was
> removed, the FIRST test to write is the regression the removal was made
> for.** The history already names the failure and the shape of it. You are not
> guessing what might break; you are being told, by the last person who was
> here.

The worked example. An idle "keep the picture alive" crawl was removed from the
marketing site's flight because it walked the film forward on its own: thirty-
odd seconds of standing still advanced it three segments, so somebody who
paused came back to a different part of the flight with the wrong caption up.
The replacement was blunt and correct — scroll stops, video pauses.

Months later the request was "settle to the nearest caption when scrolling
stops". Which is a different feature, and is also *the film moving on its own*.

The test written first, before any of it worked, was the removal's own: scroll,
stop, wait thirty seconds, assert the film has not moved. **It failed on the
first attempt** — pos 1 to pos 7, the whole film, because `onEnded` handed off
to the next clip unconditionally, so any playback at all became
self-sustaining and a stray scroll event could cancel the settle's deadline
while leaving the chain running.

Nothing else would have caught it. The feature's own tests all passed: the
targets were right, the arithmetic was right, the settle went where it was
asked. It was correct and it walked the film to the end.

> A removal is a **claim about a failure mode**. Re-entering that
> neighbourhood re-opens the claim, whatever the new feature is called.

**And the commit that first recorded this pattern demonstrated it.** The new
section was inserted immediately before `### The CALL-GRAPH WALK` and consumed
that heading, leaving its body dangling under the new one and §1 reading
"Four patterns" over three headings — in the section about checks that verify
the wrong thing. The verification was that the new text was present. It was.
Nothing asserted that what was already there still was.

> **AN INSERTION IS ALSO A CHECK THAT NOTHING WAS DISPLACED.** Adding is not
> a safe operation. Whatever you write at a boundary, the assertion is not
> *"my text is there"* — it is *"my text is there AND the neighbours are
> unchanged"*. Diff the whole region, not the insertion.

### The CALL-GRAPH WALK — for "every X reachable from Y"

`backend/tests/test_report_legal_vs_investor.py`. From
`generate_combined_report`, take the transitive closure of direct calls and
require every `render_signature_html` reached along the way to pass
`show_affirmation=False` or forward the flag.

**And it asserts the walk itself is non-empty and reaches the shared builder**,
because a closure that returns only its root satisfies every downstream
assertion vacuously. That guard is not decoration — it is the whole difference
between a check and a green light.

---

## 2. The general rule

> **Any check that can be satisfied without running must count its own
> executions and fail at zero.**

A loop over an empty set passes. A filter that matches nothing passes. A
closure that walked nowhere passes. A scan whose classifier stopped recognising
its subject passes. In every case the output is a clean green that means
"nothing was examined".

Instances on this codebase:

| check | how it came back empty |
|---|---|
| `db.audit_log` | collection is `audit_logs`; a nonexistent collection returns zero |
| `db.workers.find({project_id})` | no writer sets the field; the query was well-formed and matched nothing |
| Query D | compared 0 to 0 on 27 of 35 groups |
| `test_the_gate_actually_asks_the_predicate` | the first control run PASSED — ten tests were driving the predicate directly and none noticed the call site had been reverted |
| `inserted_doc_keys` | now RAISES rather than returning an empty set, which is the fix in code |
| `db.report_numbers` | **the same miss as row 1, later.** Numbers live on `report_emails.report_number`; the zero it returned was also the answer a working gate would give (§14) |

Cheapest habit that catches most of them: **run the query once with the filter
removed.** If that is also zero, the filter was never the question.

---

## 3. A keyword count cannot distinguish a deliberate omission from an accidental one

The worked example, because it is the subtlest thing in this file.

The affirmation banner was ruled off the investor report. Thirteen
`render_signature_html` call sites in `generate_combined_report` were given
`show_affirmation=False`. Verification was `grep -c show_affirmation` → sixteen,
and the item was reported closed.

**It was still rendering.** A fourteenth call site sits inside
`_superintendent_log_html`, a builder shared by the legal PDF and the combined
report, and passed no flag at all.

The obvious lesson — "a count cannot find a call site that omits the keyword" —
is true and is **not what happened**. `test_report_document_layout.py` named
that exact call site and asserted it KEPT its banner, with a written reason:
the section shares its builder with the legal renderer and "is the one signature
here that is also its own filed legal record". Somebody found it, thought about
it, and decided *for* it.

So the real rule is narrower and worse:

> Sixteen occurrences was consistent with **both** a complete fix and a
> deliberate exception. A count cannot tell them apart. Only a structural check
> forces every reachable call site to state its intent.

**And the decision had never rendered.** `_filed_log(logbooks,
"site_superintendent_log")` returned nothing until the first superintendent log
was ever filed, so no report anyone had read contained the section. A design
decision nobody can look at is not reviewable, however well argued — and it was
argued well.

---

## 4. The synthetic-specimen rule

> **A check whose subject is production code stops working the day production
> is correct.**

Drive the rule on a fixture you made, with a positive case and a negative one
beside it, so the check keeps testing the rule rather than testing today's
codebase.

Corollary found the hard way in `test_answers_render_as_answers.py`: a synthetic
specimen must actually reach the code under test. The first draft used an
invented item key, never got past an earlier presence guard, and asserted
nothing — **and that failure is what found the real root** (§7). A specimen that
passes nothing is as useless as a scan that matches nothing, and looks the same.

---

## 5. Fixtures assert fidelity that nothing checks

`backend/tests/test_preshift_affirmation_record.py` carries:

```python
# A row as the filed sheet actually stores it: no affirmation field anywhere.
STORED = { ... "had_injury": "No", "inspected_ppe": "Yes" ... }
```

The clause after the colon is true. **The clause before it is not.** The filed
sheet stores lowercase `'yes'` / `'no'` / `null` and always has — one writer,
one component, unchanged across sixteen commits, and 329 worker rows in
production with zero capitalised and zero boolean values.

Two other fixtures carry real booleans. No test asserts on any of those values,
so nothing has ever compared a fixture against production.

This nearly caused a data migration. The proposal was to normalise stored values
so the renderer could rely on them; the evidence for the wider domain was
**invented by fixture authors**. Had it shipped, it would have rewritten filed
answers — and the editor compares with strict lowercase equality, so a rewritten
`"Yes"` renders as unselected and the CP's first tap silently overwrites it.

> A comment claiming a fixture mirrors production is a claim about data, and it
> belongs to whoever can query the data. Write the query, or drop the claim.

Same family as **a comment citing code as precedent**: `_r2_delete_prefix`'s
docstring described a sweep that deleted nothing, `docCache`'s comment said "every
extension" while the code added one, and `pdfjsViewer` bought an oversample to
make zoom free after zoom had stopped being free. A comment cannot fail, so it
goes stale silently and is then cited as authority by the next reader.

---

## 6. Re-read a clean rebase

Twice this week a rebase applied with no conflict and lost the point of the
change. Both were found by reading the resolved file, and neither by any test.

**`docCache` keep-set.** A comment said the sweep kept "every extension"; the
code added only `pdf`. Both parents were correct on their own terms; the child
inherited an assumption that was true in both and false once thumbnails wrote
`.jpg`. Merge tools resolve text. Nothing resolves an assumption.

**The signature block, spelled twice by hand.** `generate_combined_report`
duplicates `render_signature_html`'s structure for the daily log's
superintendent and competent-person signatures. Fixing the shared renderer
removed the border and normalised the name in one place — and left the identical
border and the identical two spellings one screen further down **the same
document the operator was reading**. Both items would have been reported closed.

> A clean rebase preserves TEXT, not REFERENCES and not INTENT. Read what you
> replayed, and grep once more broadly than feels necessary.

The corollary, from the same session: line numbers cited in prose go stale
silently. Seven `server.py:NNNN` references drifted under six commits — one by
4,221 lines — and one named a function that no longer existed. Cite the symbol;
let the number be a hint.

### The third payoff came from OVERLAP, not from replay

The two above were caught by re-reading something that had already been
combined. The third was caught before there was anything to re-read, and the
mechanism is worth separating out.

Two workers ran against disjoint assignments that both touched report
rendering. One was porting the combined report's print block to
`generate_single_logbook_html`. The other was measuring, in a container where
WeasyPrint actually loads, why the combined report's cover page prints blank.

The second measured that an unqualified `tr { break-inside: avoid }` matches the
**outer layout table's single content row** — the one holding the whole document
body. WeasyPrint will not split that row, so it relocates it to a fresh sheet
and page 1 is left carrying only the header. Deleting that one rule moved a
461px section off page 2 and back onto page 1: page-1 content bottom 265px →
794px, seven pages → six.

The first was, at that moment, copying that exact rule into a renderer whose
shell is the same three-row shape. The port would have installed a measured
defect on the inspector's PDF, and it would have read as a faithful port —
because it *was* a faithful port.

Neither worker could have found it alone. The measuring one was not touching the
single-logbook renderer and had no reason to look at it. The porting one had no
way to measure page geometry at all: WeasyPrint does not import on the authoring
machine. **Running them in sequence would have shipped the defect and then found
it.** Running them concurrently, on overlapping subject matter, found it before
it landed.

> Replay preserves text, not intent — so re-read. Concurrency surfaces what
> neither party would have looked for — so let assignments overlap on subject
> even when they are disjoint on files, and read the other one's result before
> your own change lands.

---

## 7. Absent versus empty — and the mirror, in the query that was checking

The most productive single family on this codebase. In each case a value that
*was* an answer was treated as an absence:

| site | the shape |
|---|---|
| `.get(k, "N/A")` over a stored empty string | the two-argument default fires only on a MISSING key, so `""` passes through |
| `.get(k, "Superintendent")` over a stored `null` | same: `None` is present, so the default never held |
| `_has_content` / `_cs_item_body` on `False` | `False == 0` in Python, so `value not in (None, "", False)` drops an answered "no" |
| `"null"` as a truthy string | a name the model failed to read became a live dedupe key and collapsed distinct men |

**The sharpest instance**, and the one to cite: `unsafe_conditions` with
`{"corrected": False}` — a superintendent's answer to a statutory question —
rendered as "— Not recorded" on a BC 3301.13.13 record. He answered, and the
filed document said he had not.

It was also **two bugs stacked**. `_cs_item_body` had the guard; fixing it alone
changed nothing, because `_has_content` one level up made the identical mistake
and refused the block before the renderer ever saw it. Only writing the test
found that.

> Ask of every default and every truthiness check: **is the falsy value a real
> answer here?** If it is, `is None` and `key in d` are the tests you want, and
> `or` and `not` are the ones that will lose it.

### The mirror: an absent key read as a VALUE

The four above are a stored value treated as an absence. One day produced the
reverse three times, and twice inside the diagnostic rather than the code.

**`{is_locked: false}` on a population of 32.** Asked to verify a claim about
submitted-but-unlocked logbooks, that query returned **0**. Not one submitted
log has `is_locked` set to `false`; on all 32 the key is **absent**, and
`{field: false}` matches an explicit `false` and never a missing key. The
verification reported a clean bill of health on a population that existed.

**`{is_locked: {$ne: true}}` returning 66.** The query on the other side matched
the missing keys correctly and then swept in 34 *drafts*, which are supposed to
be unlocked. That is where the number 65 came from. Neither query was wrong
about Mongo; both were wrong about the field.

**`.get("amends_logbook_id")` on a key that never existed.** A probe script
invented a plausible field name, `.get()` returned `None`, and the result was
reported as "an amendment with no pointer to what it amends". The real field is
`parent_logbook_id`, and it was set correctly. A dict `.get()` cannot
distinguish *absent*, *null*, and *misspelled by the person asking*.

> Before writing a query **about** a field, read the field's **distribution**.
> One group-by over the whole collection catches all three: the `is_locked`
> split is `True: 249 / absent: 32 / False: 29`, and `amends_logbook_id` has no
> values at all because it has no keys.

---

## 8. A docstring is a claim about a relationship, and nothing checks it

`generate_single_logbook_html` opened with:

```python
"""Generate standalone HTML for a single logbook entry.
Reuses the same styling as the combined report."""
```

The second sentence was false for the whole life of the function, and it is what
made the defect survive every read. A reader checking whether the print fix had
reached both renderers had the answer handed to them in the docstring, and the
answer was wrong.

The defect it hid: the wrapper was `max-width:700px` on a ~794px A4 page, a dead
strip down the right of every page of the PDF an inspector downloads. The
combined report had found and fixed exactly this. The docstring asserted the
relationship under which that fix would have applied here too.

**And the 700px was itself borrowed from a medium this document does not have.**
The combined report is genuinely dual-medium — it is emailed *and* handed to
WeasyPrint — so its 680px column is a real constraint and the `@media print`
release is a real compromise. `generate_single_logbook_html` has exactly one
caller, which returns `application/pdf`. Nothing emails it. The column was a
constraint inherited by resemblance, and the docstring is what carried the
resemblance forward.

This is the same family as §5's *fixtures assert a fidelity nothing checks* and
the stale-comment corollary in §6: **prose that states a relationship, sitting
where the next reader will trust it, with no mechanism that fails when the
relationship stops holding.** A comment citing code as precedent, a fixture
claiming to be production-shaped, a docstring claiming a shared implementation —
one shape.

> A docstring that says *this is like that* is an assertion. Either make it one
> — a test that fails when the two diverge — or say what the code does and stop.

### The worked example: nine seconds of measurement against a sound inference

The docstring above was *stale* — a claim that may once have been true. This one
was **never** true, and it is the better example precisely because the reasoning
that produced it was good.

A comment in `generate_combined_report` read:

> A section taller than a page cannot honour it, and WeasyPrint drops the
> request rather than leaving the sheet blank — which is what makes this safe on
> a sixty-man pre-shift sheet.

It is plausible. An unsatisfiable constraint being dropped is what a reasonable
engine would do. It is also wrong: WeasyPrint relocates the block to a fresh
sheet first and splits it there only when it has run out of anywhere else to put
it. The blank sheet is exactly what you get, and it is worst on the case the
comment called safe — the 2026-08-31 report's first section is ~1715px, taller
than a whole page, and still began on page 2 with page 1 carrying the header
alone.

**And the same shape happened again, in the fix, in the same hour.** The question
was whether CI could render a page at all, so that geometry could be asserted
rather than described. The evidence said probably not: this repo's own
mount-smoke job runs `playwright install --with-deps`, which apt-installs
`libpango`, `libcairo2` and `libgdk-pixbuf` — the same libraries — implying the
base image does not carry them. That inference was reported as strong but not
settled, with an estimated cost of a 20–40s apt step.

One throwaway branch, one probe workflow, **nine seconds**: `ubuntu-latest`
renders WeasyPrint 69.0 with no apt step at all. `--with-deps` is passed
unconditionally by Playwright and implies nothing about what was missing.

> Reasoning from real evidence produced a wrong answer twice on one afternoon,
> and measuring cost nine seconds both times. When the thing is measurable at
> all, measure it. An inference is a hypothesis with a citation attached.

A footnote from that probe, kept because it will otherwise bite the next person:
`dpkg -s libglib2.0-0` reports **absent** on Ubuntu 24.04 while the library is
present, because the time_t transition renamed the package `libglib2.0-0t64`
and it merely *provides* the old name. A census run with production's package
names reports a false negative — a measurement that is itself an inference about
naming.

The port that fixed it also refused to copy the combined report's `h2` and
`.doc-section` rules, because this renderer emits neither. A rule for a selector
that never appears reads on the next audit as a protection that is in place —
the same defect as the false docstring, spelled in CSS.

### THE POSITIVE CASE: a comment that says what a thing must NOT be used for

Every instance above is a claim that was false, or that went stale. This one is
a **true claim, written by someone who anticipated the misuse, doing its job on
the day.** The section needs it, or it reads as an argument for writing fewer
comments.

`is_registered_cs` in `lib/logbook/cs_attribution.py` answers "does this
attribution say the signer IS the registered CS". Its docstring ends:

> THIS IS SAFE ONLY BECAUSE IT GATES A SHORTCUT. The log stays reachable from
> the CP dashboard for anyone assigned to the project, so a superintendent whose
> registration an admin has not yet filled in loses a menu entry, not the
> ability to record his visit. **If this predicate is ever used to REFUSE a
> filing, that reasoning collapses and the module's first rule — IT NEVER
> BLOCKS — is broken.**

Months later a role gate was ruled for the superintendent's log: a competent
person could file a BC 3301.13.13 record, and only the registered construction
superintendent should. `is_registered_cs` is the obvious predicate — named for
the question, already imported, returning a boolean that reads correctly at the
call site.

**It returns `False` for `NO_REGISTRATION`.** Using it would have refused every
filing on a project whose registration an admin had not yet created, blocking a
log that must be completed before a man leaves the site over a missing office
field. The ruling that commissioned the gate had named that exact failure as the
one to avoid, and the obvious implementation would have caused it.

**Nothing else would have caught it.** There is no check for "this predicate was
used somewhere its author excluded". The type is right, the name is right, and
on the one live project the two answers coincide, so the tests would have been
green. The docstring was the only thing between a correct ruling and its
opposite.

> **A COMMENT THAT STATES WHAT A THING MUST NOT BE USED FOR IS WORTH MORE THAN
> ONE THAT STATES WHAT IT DOES.**
>
> What it does is recoverable by reading it. What its author knew would break if
> it were used elsewhere is not.

The fix was a **second predicate** — `cs_filing_refused`, with the opposite
answer on exactly that state — rather than a widening of the first. Widening it
would have silently changed what it means for its existing menu caller, which is
the rest of this section: that caller's claim would have become false without one
line of it changing.

---

## 9. A mechanism is not an incident. A population is not an incident.

Section 2 is about a check that can pass without examining anything. This is its
twin one level up: a **finding** that can be believed without anything having
been counted. Four instances in one day, and they cost real work.

### A code path is not evidence of harm

**The empty-phone write-attractor.** `format_phone("")` returns `""`, so a
phone-less submission built `{"phone": {"$in": ["", "", ""]}}` and matched the
one live worker whose stored phone is the empty string. `submit_checkin` then
writes the submitter's name onto whatever worker the lookup returned. Two
corruptions from one empty text field, on a public unauthenticated endpoint.
Every word of that is true, and it was relayed as *"check-ins are attaching to
the wrong worker today"* — which was not.

Queried before the fix: **0 check-ins, 0 enrollments, `updated_at ==
created_at`.** The row had not been written to since it was created. The
endpoint's only client is a screen that is not the live gate. Reachable by
anyone with the URL; never reached.

**And the canonical example is this doc's own neighbour.**
`logbookEditable.js` opens with an incident: *"Two records at 588 Thomas were
overwritten that way — and the CP changed nothing."* Its commit (`8c792aa8`,
#215) names no ids, runs no query, and lists its verification as *"26
assertions, behavioural… frontend suite green, backend green"* — every one of
them about the module. When the claim was finally checked, ten candidate rows
came back and **every one had `updated_at` exactly equal to `finalized_at`**:
the only write after filing was the overnight lock. No `daily_jobsite` at that
project shows a post-filing content write.

The mechanism is real and the helper is right. The harm was asserted, never
established, and then quoted as fact in a docstring that justified the fix —
and cited onward from there.

### The third: a fix ruled FIRST on a report nobody had checked

**#428**, "a filed sheet called signed men unsigned". Its premise: every man who
signed through the gate printed NO SIGNATURE ON FILE on a filed compliance
document while his signature sat in the card-audit bucket. It was ruled *the
worst item on the list — a filed document lying about a man* and sequenced
ahead of everything else.

The chain it resolves is `signin_id -> sign_ins -> daily_signatures -> the
card-audit bucket`. All three collections hold **zero rows**, because their only
writers live in a module whose routes are route-shadowed. The
`/checkins-today` branch that produces `signin_id` rows iterates ids derived
from `sign_ins`, so it has never produced a row. Across 44 filed sheets and 329
worker rows, **not one carries a truthy `signin_id`**; 231 carry an inline
signature and render from it, which is what has always put images on that page.

Every line the fix added is unreachable. The code is correct, it broke nothing,
and it found a real crash on the way in. But the harm it was ruled first for
required a row that has never existed — and whether the men in the original
report were the hand-typed rows, which correctly print NO SIGNATURE ON FILE,
cannot now be established, because the pre-fix rendering is gone.

**Three shipped fixes in one week, all correct code, none of the harm
measured.** This entry was written from the first two. The third was already in
the tree when the priority ruling was made.

### The step, and whose it is

The missing step is one query, and it kept being nobody's:

> **The person ruling on priority is the one who must have seen the count.**
> Not the person reporting it, and not "someone". Whoever says *do this first*
> owns the number that justified it — because a report can be honest about a
> mechanism and silent about its reach, and priority is exactly the decision
> that reach should drive.

### A count is not a description of a set, and the number decides nothing

"65 stranded logs" was carried for hours and repeated in briefs. The
verification query said 0. The real figure was 31, and neither number counted
the thing anyone cared about — see §7's mirror for why both were wrong.

**Then reading the set made the question go away.** The 31 cluster in two
blocks: fifteen filed in March on two projects, sixteen in the week `is_locked`
was introduced. Zero submitted logs created after the feature landed have failed
to lock. There is no code path to repair — they are records filed under the
rules that existed at the time, and setting the flag now would assert a fact
about their history that is not true.

**The ruling was BUILD NOTHING, and no count would have produced it.** Not 65,
not 31, not 0. The dates, the types and the field-set diff did.

A worker had already been assigned to build a button for that population.
Nothing was built, because that worker had not been started yet. That is luck,
not diligence, and it is why this entry exists.

### What the miss actually was

Not judgment, and not care. In every instance one mechanical step was skipped:

| the claim | the step not taken |
|---|---|
| "check-ins are attaching to the wrong worker" | count the check-ins on that worker |
| "two records were overwritten" | one query for a post-filing content write |
| "65 stranded logs" | read the field's distribution before querying it |
| "so build the button" | read the set — dates, types, what distinguishes it |

> **A mechanism is a hypothesis about harm. A count is not a description of a
> set.** Establish the harm with a query and read the set before anyone builds,
> and the person relaying the number runs the query. A finding that travels
> without its measurement gets acted on by the next person.

### AN INSTRUCTION IS NOT AN OUTCOME

The same shape, applied to one's own actions rather than to a population. On
2026-09-07 a PR was described as *"Merged."* in the same message that had asked
for it to be merged. It was still `OPEN`. The change was a playback-rate
increase, so the operator would have gone and watched the OLD speed and reported
back on it — and the report would have been sincere, specific, and about the
wrong build.

Nobody lied and nothing was careless. The instruction was given, and the memory
of giving it was stored as the memory of it having happened. It is the fifth
time in a week, which is what makes it a pattern rather than a slip.

| the claim | the step not taken |
|---|---|
| "merged" | `gh pr view N --json state` |
| "deployed" | read `/api/version` and compare the commit |
| "the env var is set" | fetch something that fails loudly without it |

> **The person who gave an instruction is the worst-placed person to confirm it
> was carried out**, because they hold a vivid memory of the request and none at
> all of the result. Confirmation has to come from the system: a state query, a
> version endpoint, a status field — something that was not in the room when the
> instruction was given.
>
> And say WHICH: "I merged it" and "I asked for it to be merged" are different
> claims, and only one of them can be checked by the person reading.

---

## 10. Verify the pointer, not the report of the action

Three instances, one shape: an operation reports success, and the only evidence
it worked is the operation's own output.

**`git push` said "Everything up-to-date".** It was — for the branch named. The
commit had gone onto a *different* branch, because another agent switched the
shared checkout between `checkout -b` and `commit`. `git log --oneline
origin/<branch> -1` says where the branch actually points, and it costs two
seconds. See followups.md for the arrangement that stops this at the source.

**A merge is confirmed by `/api/version` reporting the squash SHA**, not by
green CI. Green CI says the code would work if it were deployed.

**A listing that returns 200 is not a listing.** `_r2_delete_prefix` read a
`GET` that returned a CORS document as an empty page of results, and reported a
successful sweep of nothing.

> Ask what the OBSERVABLE STATE is after the action, and read that. A tool
> reporting its own success is describing its intent, not the world.

### The corollary: the test that already existed is the one that catches you

Extracting `roster_for_window` out of `_roster_for_period` left `year` and
`month` interpolated in an orphan-count warning — parameters that no longer
existed on the function they were now inside. A `NameError` inside the LL196
statutory attestation's own roster build, on any month with an orphaned
check-in.

Nothing in the new work would have found it: the picker never reaches that
branch. `test_ll196_population` did, immediately — a test written for the defect
that filing *already had*, catching a refactor that would have broken the filing
a different way.

> The argument for a test is rarely the bug it was written for. It is the next
> person, changing something else.

---

## 11. A refusal must be the LAST thing written, and its enforcement is a fact to check

Two rules from one sweep, both about a guard that looks right and is not.

### Caller-supplied narrowing first; the refusal last

`get_projects_dob_summary` scopes a query two ways: the tenant filter, and an
optional `project_id` **query parameter** that writes `_id`. The tenant refusal
is also written to `_id`, as an unsatisfiable `_id: None`.

Written in the obvious order — refusal, then the caller's narrowing — the second
assignment **overwrites the first**. A company-less caller would have turned the
guard off by supplying the very parameter it exists to stop:

```python
# WRONG
if company_id:      q["company_id"] = company_id
elif not operator:  q["_id"] = None
if project_id:      q["_id"] = to_query_id(project_id)   # ← guard gone
```

```python
# RIGHT
if project_id:      q["_id"] = to_query_id(project_id)
if company_id:      q["company_id"] = company_id
elif not operator:  q["_id"] = None                      # ← nothing follows it
```

The two are compatible in the ordinary case: a scoped caller naming a project
gets both keys, ANDed. It is only the refusal that must be unreachable by a
later write. Where the order cannot be arranged — a filter built in a helper, a
query assembled by a caller — use `$and` instead of merging, for the same
reason: a merge lets a key be replaced, and `$and` does not.

> A refusal expressed as a **value** can be overwritten. Write it last, or
> express it as a **conjunction** that cannot be.

### A gate's enforcement is a fact about the environment, not the code

`require_platform_operator` reads as a hard gate. It is not, unconditionally:

```python
if not PLATFORM_GATES_ENFORCED:
    logger.warning("[platform-gate SHADOW] would have blocked …")
    return current_user
```

`PLATFORM_GATES_ENFORCED` defaults to `"false"`. In that mode the gate logs and
**returns the caller**.

A census written the same afternoon accepted that dependency as a guard equal to
`require_project_access`. Reading only the default, the conclusion was that the
census accepts a no-op — an alarm about a security check being hollow. Checking
the deployed environment first: production sets it to `true`, and the gate does
enforce there. The alarm was wrong.

But the caveat is real for any environment that does not set it, so it is
written into the test that depends on it rather than left to be rediscovered.

> §9 applies to your own alarm. A guard's code says what it *would* do; the
> environment says what it *does*. Read the deployed value before reporting that
> a gate is hollow — and when it is conditional, put the condition in the test
> that relies on it.

---


## 12. A check whose TARGET or CHANNEL is wrong fails toward "fine"

Every section above is about a check that asks the wrong QUESTION. This one is
about checks that ask the right question **of the wrong thing**, or whose answer
never arrives. None is a logic error, which is why none of the sections above
holds them, and why they are hard to see: the code is correct, the reasoning is
correct, and the check is pointed somewhere else.

They almost all fail in the direction of *nothing is wrong*.

All thirteen below were found in two days, by one author, on this codebase.

### The sharpest instance: a control run that was correct, complete, and answered a different question

Put first because it is the clearest example of the whole class, and because it
cost the most.

The orientation sheet was the first log type moved onto the declarative
renderer. Before its old branch was deleted, a control run rendered all **92
production records** through the live build and compared each whole document
against the engine's sheet. **92 of 92 byte-for-byte identical.** No skips, no
gaps, every record, run against production data.

It proved that the old branch was unreachable. That was a real question and the
answer was right.

**It said nothing about whether the sheet still said what the old sheet said,
because both sides of the comparison were the new engine.** The document was
being diffed against itself.

Three things were gone, and they had been gone in production for three days:

| | lost | measured |
|---|---|---|
| the signature affirmation banner | AFFIRMED, with a claimed and a server-received time | 89 records |
| the same banner's other half | **UNAFFIRMED — no affirmation record for this document** | 79 records |
| the AMENDED RECORD banner | who amended it, when, and why | 15 records |
| the record's status | **DRAFT** or SUBMITTED in the old header | 3 draft records |

**The second row is the one to read twice.** UNAFFIRMED is a deficiency
marker: it states that no affirmation record exists for that mark. Removing it
does not make a document look broken. It makes a **deficient document look
clean**, on a filed BC 3301.13.13 record about a named man. The fourth row is
the same shape — a draft that no longer announces itself as one.

A loss that fails toward looking *better* is the one nobody reports.

**Why it was invisible to a reviewer.** All three live *outside* the per-type
branch, in the function that wraps it, below the line where a converted type
has already returned. Reading the schema, the engine and the old branch side by
side — which is exactly what review does — shows nothing missing.

**The rule this sets for every conversion that follows.** The comparison is
**old branch output against new engine output, on the same record, captured
before the branch is deleted.** Not new against new. For every type still
unconverted the baseline is capturable today, because the branch is still the
renderer — and it is never cheaper than now.

*(Two smaller traps inside the diff itself, worth knowing before running one: a
case-sensitive word diff reported the job address as missing when the engine had
merely uppercased it, and base64 image payloads must be replaced by a token or
the diff is megabytes of ink.)*

### The instances

| # | the check | what was actually wrong |
|---|---|---|
| 1 | deploy poll on `/api/version` | pointed at a dead host. Twelve polls returned `?`; the loop simply ran out |
| 2 | `pytest tests/ \| tail -4` | the pipeline returned **tail's** status. A run with `1 failed` was reported `exit code 0` |
| 3 | `assertNotIn("superintendentLogModel.test.cjs", …)` | failed on the correction that **retracts** the name |
| 4 | `assertNotIn("SignaturePad", …)` | a bare substring, in a file whose subject is why no `SignaturePad` is there |
| 5 | `assertIn("cannot run \`explain()\`", doc)` | defeated by a **line wrap** — the docstring reads `cannot run\n\`explain()\`` |
| 6 | `get_workers`' own comment | *"what rescues that path is the projection"* — a check-shaped claim with nothing that could fail when it stopped being true |
| 7 | `card_image_may_be_replaced` | read `osha_card_image`; the migration **removed that field** |
| 8 | the strip's verifier | verified the data perfectly and never asked what the **running code** expected to find |
| 9 | `_signed_by` stamped in `update_cp_profile` | the right check, applied to the wrong function — a user's signature *profile*, not a logbook |
| 10 | `grep "ALLOWED_ORIGINS" tests/ \| head -10` | ten unrelated matches filled the window. `TheOriginListIsExactAndNarrow` was line eleven, and the report read **"no test pins this list"** |
| 11 | every read of `server.py` for a day | the checkout was 785 commits behind `origin/main`. `/api/version` was reported **absent**; it has existed for weeks, and instance 1 above is about polling it |
| 12 | `<ReportFrame />` removed as "the duplicate" | there were two. The one removed was the one a stop-focus CSS rule had been written for, leaving `.stage.report-focus .sheet-front` matching nothing and firing against nothing |
| 13 | PII scan of a report PDF, `\b\d{7,}\b` for card numbers | SST cards are ALPHANUMERIC — `KSPNNWEFJ4`. The scan reported clean on a document carrying ten of them. Reading page 9 found them |
| 14 | the orientation control run, 92 of 92 byte-identical | both sides were the new engine. See the lead above — it proved the old branch was unreachable and never asked whether the sheet still said what it used to |

### Five shapes, and the fourth is the one to fear

**THE TARGET IS WRONG.** 1, 4, 9. The check runs, answers honestly, and is
looking at something else. A dead hostname returns `?` forever and `?` is not
`false`.

**THE CHANNEL SWALLOWS THE ANSWER.** 2, 5. The subject is fine and the verdict
is lost in transit — a pipeline's exit status, a paragraph reflowed by an
editor.

> **An assertion about PROSE must not depend on formatting the author does not
> control.** Reflowing a comment is not a change of meaning. Normalise
> whitespace, or anchor to a construct.

**THE CHECK CANNOT DISCUSS ITS OWN SUBJECT.** 3, 4. A ban on a literal fails on
the sentence that retracts it, or on the comment explaining why the thing is
absent — in a codebase that writes exactly those comments constantly.

> Ask whether an occurrence is **marked as retracted**, not whether it occurs.
> And *keep* the dead name inside the retraction: a correction that erases the
> word the next person will grep for leaves their search empty, which reads as
> **"no such problem"** rather than "already handled".

**THE SUBJECT MOVED OUT FROM UNDER IT.** 6, 7, 8. The worst, because the check
was right when written and nothing touched it. `card_image_may_be_replaced` was
correct for a year and became wrong the moment an unrelated migration removed
the field it reads — and *nothing in the migration's own checks could have seen
it*. It was found by chance while reading the write path for another reason.

> **A MIGRATION HAS TWO SUBJECTS AND THE VERIFIER ONLY EVER SEES ONE.** It
> verifies the data. It does not verify the code that reads the data.
>
> Which gives the rule instance 8 cost: **a migration that changes a stored
> shape is not done when the data is verified. It is done when the code that
> reads the data is DEPLOYED. Strip last, never first.**

Instance 8 is the sharpest illustration in this document of a check that was
true and useless. Every verification run against the database was correct: 46
objects HEADed, sizes matched at 0.75×, inline copies confirmed gone. And for
the minutes between the strip and the merge, both card screens told an admin
**"No card image on file"** for 46 workers who had one — on the screen where he
decides whether to admit a man on an expired SST. The check was correct, the
data was correct, and the two were correct **at different times**.

**THE ANCHOR IS A LOCATION, AND LOCATIONS MOVE.** Four instances of its own,
and it is the target-is-wrong shape at the smallest scale. A source-reading
check slices its subject out of a file by naming a landmark; when the landmark
moves, or when a second thing matches it, the slice holds something ADJACENT to
the subject and answers honestly about that.

| the anchor | what the slice actually held |
|---|---|
| `.slice(0, 400)` from `label={t('departedAt')}` | ran past the closing `/>` into the `departedNextDay` Pressable, which carries `disabled={locked}` and always has |
| `braceBlock(src, 'const CollapsibleItem = (')` | the component's parameter is a DESTRUCTURED OBJECT, so the first `{` opened the prop list and the balanced block closed on it — the signature, not the render |
| "the offer effect ends at the next `useEffect(`" | the DOB effect that follows opens identically, so the slice ended INSIDE the effect it was slicing |
| `slice(pickerSrc, 'export const ROLE_LABELS', …)` | the declaration it needed had moved ABOVE that landmark, so the lifted source did not contain the function its own `module.exports` tail names |
| `assertIn("generate_combined_report(project_id, today)", src)` | the emailed report's render, pinned VERBATIM. It broke the day that call gained a third argument — and the thing it protects, that the email is rendered by the function the leak proof tests, had not changed at all |

None is a logic error, and none of the SUBJECTS was wrong.

**THE LAST ONE NAMES THE RULE THE OTHER THREE ALSO BREAK.** An assertion bound
to a SIGNATURE or a LOCATION fails when either moves, and neither is what the
check is about. `report_html = await generate_combined_report(` is the claim —
that the email still goes through that renderer. `(project_id, today)` is who
it passes, which is the caller's business and changes when the caller's
business changes.

> **Assert the RELATIONSHIP, not the shape it currently has.** Ask what
> sentence the check is defending. If the sentence survives the edit and the
> check does not, the check was pinned to the wrong thing.

**Three of the four were caught by the control run, by a specific tell: an
assertion failing that describes code nobody touched, or a block of assertions
splitting in a way the change cannot explain.** The `braceBlock` one is
clearest — every "it takes prop `x`" passed while every assertion about the
render failed, which is not what a missing feature looks like. The fourth did
not fail at all: it threw a `ReferenceError`, which is this section's own
lesson about a broken check and a broken subject needing to look different.

> **A CHECK MUST BE ABLE TO SAY IT FOUND ITS SUBJECT**, as its own assertion,
> before anything is asserted ABOUT the subject. `ok(slice.length > 800 &&
> slice.includes('onPress={onToggle}'))` is one line, and it converts every
> silent wrong answer above into a named failure.
>
> Prefer an anchor the subject cannot drift past — a closing tag, a dependency
> array, the next top-level declaration. **A character count is not an anchor,
> and a landmark that appears twice is not an anchor.**

### DO NOT ASSERT ON PROSE — and this one removes the shape rather than describing it

Everything above about anchors is a preference: *prefer structure to location*.
**A prose assertion has no structure to prefer.** The text IS the subject, so
there is nothing else to anchor to, and every technique in this section fails
against it.

THE EVIDENCE IS THE RATE, NOT THE INSTANCES. Five anchor failures landed in one
session. **Three of them were written AFTER the section describing the failure,
two of them by its author while writing it** — and not carelessly. Each was an
attempt to preserve a reason:

| the assertion | what defeated it |
|---|---|
| `"bare siblings" in above.lower()` | the phrase wrapped across two comment lines |
| the same, whitespace-flattened | the `#` on the continuation line — `bare # siblings` |
| `assertNotIn("Generate email-safe HTML report", d)` | the docstring **quotes** the sentence in order to retract it |

Knowing about the shape did not prevent it, twice in a row, minutes apart. That
is the signal: **a rule that has to be remembered at the moment of writing is
not a rule, it is a hope.**

#### The resolution

> **If a claim matters enough to check, it is a NAMED CONSTANT, and the
> assertion checks the constant. A sentence in a comment or a docstring cannot
> be pinned by any means that survives reformatting.**

Which splits every "assert the words" case cleanly in two:

**PROSE THAT IS THE PRODUCT — assert it, at its constant.** A refusal message,
a button label, a consent paragraph, an i18n value. The sentence is the
deliverable; changing it *is* a change of meaning, and it already lives in a
table (`en.js`, `CS_LOG_ATTESTATION_HTML`, `_PHOTO_ADDED_AFTER_FILING_LABEL`).
Assert against **the constant**, never against a rendered blob and never
against the source file that happens to contain it.

**PROSE THAT IS RATIONALE — do not assert it at all.** A comment explaining
*why* a rule exists has no constant, cannot have one, and is not the product.
There is no correct way to check it. That a reason stays written down is a
**review** responsibility, and pretending otherwise buys a check that fails on
a reflow while never once catching a deleted rationale.

#### The population is small, which is why this is cheap

Measured across the repo — every `assertIn`/`assertNotIn` whose needle is two
or more words of English with no code punctuation:

    552  backend/tests/*.py          }  672 total
    120  frontend **/*.test.cjs      }

    512  search RENDERED OUTPUT, an i18n table or an API payload   <- correct
     26  search SOURCE TEXT (_SRC, src, body, code)                <- the shape

And most of those 26 are not prose at all — the scan counts
`except DuplicateKeyError:`, `const TRANSLATIONS` and `--execute requires
--keep`, which are constructs that happen to contain a space. **The genuine
population is about a dozen.**

So the shape does not recur because the codebase is full of it. It recurs
because writing one is the natural reflex when you want a reason to survive,
and it gets written **fresh** every time. The rule is nearly free to adopt and
it is the only item in this section that removes the failure instead of
teaching people to spot it.

### A correction QUOTES what it corrects, and never deletes it

Stated once here because it is now the pattern for every correction in this
codebase, arrived at three separate times:

- `test_absence_literals_are_specific` flagged a ban on a filename that failed
  on the sentence retracting that filename
- `_photo_added_after_filing_caption` keeps the dead field name inside its own
  note
- `generate_combined_report`'s docstring now **quotes** "Generate email-safe
  HTML report … Fits in email box" and marks it `USED TO SAY THE OPPOSITE` /
  `NONE OF IT IS NOW`

> A correction that ERASES the words it corrects leaves the next person's grep
> empty — and **an empty result reads as "no such problem", not as "already
> handled".**

The corollary for checks: assert that an occurrence is **marked as retracted**,
not that it is absent. A ban on the old words fails on the paragraph that
retracts them, which is how this rule keeps being rediscovered.

### An assertion's failure output is part of the assertion

A check nobody will run twice is not a check, and the fastest way to earn that
is to make its failure unreadable.

`assertIn(needle, haystack)` **prints the haystack.** Two assertions searching
all of `server.py` turned one-line failures into **2.3MB** of escaped source
with the fact buried somewhere inside it — enough to blow a terminal, a CI log
pane and a context window at once. The same pair repaired reported **28KB**.

    self.assertIn("{_report_no_line}", _SRC)               # 2.3MB on failure
    self.assertTrue("{_report_no_line}" in _SRC,           # one line
                    "the header does not render the report-number line")

`assertTrue(x in y, "…")` is the whole fix: the boolean carries no container,
so the message is all that prints. The same choice
`siteSuperintendentSign.test.cjs` had already made against a haystack a hundred
times smaller — *"printing it buries the one fact that matters."*

> **If the container is bigger than a screen, do not let the assertion print
> it.** Say what is wrong instead. The reader already has the file.

AND A FILE-WIDE BAN IS THE SAME MISTAKE ONE STEP EARLIER.
`assertNotIn("locals().get", _SRC)` was written to say "the send block stopped
reading that name reflectively". It failed on **four unrelated pre-existing
uses** elsewhere in the file — the bare-literal shape §12's instances 3 and 4
already carry, arriving through the scope of the search rather than the
specificity of the string. Scope the slice to the block the claim is about,
then assert.

### An error from the PROBE is not evidence about the SUBJECT

Three in one sitting, and the tell is what saves you:

- `AttributeError: module 'server' has no attribute 'worker_card_image_fields'`
  — the probe ran from a checkout that did not have the change
- `403` on `/workers/{id}/osha-card` — authenticated as the CP on an
  admin-only route. **The gate working.**
- `404` on a route path guessed rather than read

Read as results, the first would have reported a broken reader on a migration
that had just deleted 37.8MB.

**All three failed toward ALARM, which is why they were caught.** The dangerous
half of this family is the one that fails toward reassurance — instances 1 and
2 above, where a broken check and a healthy system are the same output.

### A SCAN FOR A FORMAT IS NOT A SCAN FOR THE THING

Instance 13, and it is the one that mattered most in the exercise it came from.

Two filed compliance PDFs were checked for personal data before any of it could
reach a public marketing page. The scan looked for phone numbers, emails, long
digit runs, Mongo ObjectIds and URLs — a careful list, written by someone
thinking about PII. **It reported clean.**

The document carried ten SST card numbers. They look like `KSPNNWEFJ4` and
`6UF0B6KSQR`: alphanumeric, no fixed length, no separator, nothing a
digit-run pattern can see. It also carried ten worker names, which no regex was
ever going to find. Reading page 9 found all of it in about four seconds.

> **The scan encoded what the author expected the thing to LOOK like, and the
> subject was defined by what it MEANS.** A card number is not a number. A name
> has no format at all. Any check written as "find things shaped like X" is
> only as good as the guess about X, and it returns the same confident empty
> result whether the guess was wrong or the document was clean.

Two rules that fall out of it:

> When the question is *"is there anything sensitive in here"*, a pattern scan
> is a FIRST pass and never the answer. Read the artifact. For anything with a
> page count small enough to read, reading it is both cheaper and correct.

> A negative result from a pattern scan must be reported as **"no matches for
> these patterns"**, never as "clean". The first is true and invites the next
> question; the second closes the subject on the strength of a guess.

### THE WORKSPACE IS WRONG, so every answer inside it is true and irrelevant

Instances 10 and 11, and the shallow clone the day before. A fifth shape, and it
does not look like the other four: nothing here is a check at all. It is a
**read** — a grep, a file opened, a route looked for — answering honestly about
a workspace that is not the subject.

- A `--depth=1` clone was used to author a change against `main`. It could not
  see `flight-rebuild`, so a link it added in good faith was a blind duplicate
  of one that already existed on another branch.
- A branch was cut from a local `main` **785 commits behind** `origin/main`.
  Every read inside it was accurate about a tree nobody deploys. It produced a
  written, confident claim that `/api/version` is not a route — in a repository
  where §12 instance 1 above is a story about polling it.
- `grep … | head -10` truncated the one match that mattered. Same family as
  instance 2's `tail -4` and the `tail -2` on the mount smoke: **the shell
  discarded the answer and the exit status said nothing was wrong.**

> **FETCH BEFORE YOU BRANCH, AND VERIFY THE BASE.** `git fetch` then
> `git rev-list --left-right --count main...origin/main` before cutting a
> branch. A clone is not current because it is a clone, and a checkout that
> was correct last week answers this week's questions with last week's file.

> **NEVER PIPE A SEARCH FOR ABSENCE THROUGH `head` OR `tail`.** "I found
> nothing" and "I stopped looking" are the same output. If a claim is *no
> occurrence exists*, the search that backs it must be unbounded — or counted
> (`-c`, `-l`) so the number itself shows the window was not the limit.

The tell is the same in all three: **the finding was about the workspace and was
reported as being about the system.** Both halves of instance 11 were caught by
something outside the workspace — CI ran the test the grep had missed, and the
rebase pulled in the route the checkout did not have. Neither was caught by
looking harder inside it, because inside it nothing was wrong.

### THE WORKSPACE SUBSTITUTES ITS OWN BEHAVIOUR AND RETURNS THAT

The sixth shape, and the worst, because it is the fifth with a plausible
number attached. The workspace does not merely fail to observe the subject.
It answers in place of the subject, in the subject's own units.

Measured, on the marketing flight's parked settle. The question was whether a
scroll-driven film holds still for thirty idle seconds. Two browser surfaces
were available, and both were hidden tabs:

| probe | what the code asks for | what the workspace returned |
|---|---|---|
| `requestAnimationFrame` | ~60 fps | **0 frames in 2 seconds**, both surfaces |
| `setTimeout(fn, 100)` | 100 ms | **~1000 ms**, both surfaces |
| `video.play()` | the film advances | resolved with **no error**; `readyState` 4; advanced **0.000 s in 3 s** |
| `lenis.scrollTo(3000, {immediate: true})` | scroll to 3000 | stayed at **0** — Lenis commits inside the rAF loop |
| `window.scrollTo(0, 3000)` | the flight advances | `scrollY` 3000, `lenis.scroll` **0**, `flight.pos` **0** |

`IDLE_MS` is 140. In that workspace it cannot fire before ~1000 ms, so every
duration measurable there is the browser's hidden-tab clamp wearing the code's
name. A settle that looked correct in it would have been reporting on
throttling.

And the last two rows are why this shape is not merely §12 but §2 as well.
**The idle test would have PASSED.** `pos` 0 before, `pos` 0 after, the film
did not move — a green that means *the film cannot move here*, because the
input path itself is rAF-gated: the flight reads Lenis, Lenis advances only
inside a frame loop, and there are no frames. The assertion could not have
failed, so it was never a test.

Note also that `play()` is a clean instance of §10 in the small: it reported
its own success and described its intent, not the world.

> **BEFORE TRUSTING A TIMING OR MOTION RESULT, MEASURE THE INSTRUMENT'S OWN
> CLOCK.** One `setTimeout` you know the answer to, and one rAF count. If the
> workspace cannot reproduce the quantity the code is written in, the run is
> about the workspace. And if the subject cannot move there at all, an
> assertion that it did not move is not evidence — it is the empty set.

The correct outcome was to leave it parked and say so, rather than ship a
green from a room where the experiment cannot run.

### THE SCOPE OF THE QUERY WAS NARROWER THAN THE SCOPE OF THE CLAIM

The seventh shape, and it needs no broken tooling at all. The database was
reachable, the query ran, the counts were exact, and the sentence built out of
them was false.

A census of stored signatures in production counted three fields —
`cp_signature`, `data.superintendent_signature` and `data.presence.signature` —
across 303 filed logbooks, and reported: *"every real signature is vector
stroke paths, 297 of 303, zero base64."* That was TRUE of the three fields it
counted. A fourth field, `data.worker_signature`, was never in the query. It
holds **72 raster signatures stored as full data URIs**, 14KB to 33KB each.

The conclusion drawn from the census was that base64 handling was effectively
dead code and the transparency work was therefore cheap. It was wrong, and it
was wrong in the direction of reassurance: the raster path turned out to carry
a live rendering defect on 72 filed legal records.

Same shape as the sweep that missed a directory, the clone that fetched one
branch, and the query against a collection that does not exist — the answer was
true about what was examined and irrelevant to what was asserted. The only
difference is where the narrowing sat. Here it was in the FIELD LIST rather
than in the tree or the connection, which is what makes it invisible: a field
the query never named cannot come back as a zero, it comes back as nothing at
all, and nothing looks the same as none.

> **A census must report the SCOPE IT ACTUALLY COVERED in the same sentence as
> its result.** "297 of 303 `cp_signature` values are vector" is true and
> useful. "Every signature is vector" is a different claim, and the same query
> cannot support it.

> When the subject is *all X*, ENUMERATE WHERE X CAN LIVE BEFORE COUNTING, and
> say which of those places were searched. The enumeration is the work; the
> count is the easy part.

### The positive case: make the failure LOUD and TOTAL

The one place this went right is worth as much as the nine that went wrong.

`strip_inline_worker_image.py` verifies every object before unsetting any, and
**any failure aborts the whole run** — including the rows that already passed.
On its first dry run, 26 of 26 HEADs reported *"R2 is not configured"* in an
environment where all five `R2_*` variables were set: `server._r2_client` is
assigned in `startup_event`, which a script never runs. **The verifier itself
was broken.**

It aborted having touched nothing.

Had the rule been *"skip the rows that fail"*, it would have skipped all thirty,
stripped nothing, and printed a clean finish — a silent success over a check
that never ran, **on a job whose only safety IS that check**. Because any
failure aborts, a broken verifier is indistinguishable from unreadable objects:
loud, and refusing to delete.

> Design the failure so a broken CHECK and a broken SUBJECT look the same. Then
> you cannot be reassured by an instrument that is not working.

That rule is repeated at the top of this document, because it is the one here
that generalises past this codebase. This is where it was learned.

And when a cross-check falls out of the data for free, **make it an assertion
rather than a note**. The 0.75× size ratio between a base64 payload and its
stored object was noticed by accident on one run and is now a required step: a
HEAD proves an object is *there*, the ratio proves it is *this row's*
photograph.

### Why the bare-literal gate is the most productive check in this repo

`test_absence_literals_are_specific.py` caught instances 3, 4 and 9's sibling,
and a fourth the same day. Its failures are **almost all true** — every one was
a real ambiguity, none was noise. That is rare enough to name: a check with a
near-zero false-positive rate is one whose output people keep reading, which is
the property §9 says a security check lives or dies by.

---


## 13. A tool that follows links destroys things outside what you asked it to remove

§12 is about a check pointed at the wrong subject. This is its operational
twin: a COMMAND pointed at the wrong subject, where the wrong subject is a
shared resource and the blast radius is everything else in the checkout.

### The instance

Worktrees have no `node_modules`, so the mount-smoke recipe junctions the main
checkout's:

```bash
cmd //c mklink //J <worktree>/frontend/node_modules <main>/frontend/node_modules
```

Cleaning up afterwards:

```bash
git worktree remove <worktree> --force     # and `rm -rf` behaves identically
```

**Git-bash `rm -rf` and `git worktree remove --force` both RECURSE THROUGH a
Windows junction.** They do not unlink it. They walk into the target and delete
the real packages, in the main checkout, which every other worktree and every
other session is also using. `@babel/core` went, among others.

### The tell is the finding, not the deletion

Sixty test files failed at once, immediately after a source edit.

That reads as **"the edit broke everything"**. It is not: the edit was fine and
the dependency tree was gone. The real signature is `MODULE_NOT_FOUND` on a
build-time package across many unrelated files simultaneously — as against an
assertion failure in one. Minutes go to reading a diff that has nothing wrong
with it, which is the same cost §12's instances impose and for the same reason:
**the failure points at the wrong cause.**

It is also the mechanism behind "work reverting between passes". A shared
mutable resource, clobbered by the cleanup of something unrelated, produces
regressions in things previously reported done — and nothing in the reverted
work's own history explains it.

### The rule

**Unlink before you remove.** `cmd //c rmdir` on a junction removes the LINK
and leaves the target alone; nothing else here does.

```bash
cmd //c rmdir "$(cygpath -w <worktree>/frontend/node_modules)"   # unlink ONLY
git worktree remove <worktree> --force
```

Then verify the shared resource survived, because the whole point is that the
command reports success either way:

```bash
ls <main>/frontend/node_modules/@babel/core && ls <main>/frontend/node_modules | wc -l
```

`npm install` in the main checkout restores it. Check `package.json` and
`package-lock.json` are still clean afterwards — a repair that edits the
manifest has changed the repo, not just the environment.

### The general shape

A junction is one instance. The rule is about any tool whose reach exceeds its
argument:

- **symlinks and junctions** — `rm -rf`, `--force`, and most recursive walkers
  follow them; the argument names a link and the damage lands somewhere else
- **`git clean -xdf`** in a worktree whose ignored paths point outward
- **a bind mount or a shared volume** removed with the container that mounted it
- **a `--force` push** to a branch another worktree has checked out

The question to ask before any destructive command: **is every path this will
touch inside the thing I named?** If any of them is a link, the answer is no
until you have unlinked it.

And the corollary, which is what makes this a harness section rather than a
shell tip: **a destructive command reports on what it was asked to do, never on
what it reached.** `git worktree remove` said it removed the worktree. It had.
That statement was true and useless. This is §10 — verify the pointer, not the
report of the action — applied to deletion, where the observable state is the
resource you did not name.

---


## 14. An assertion that can crash before it asserts has two outcomes and only one of them is informative

A check exists to return a verdict about its subject: pass, or fail with a
reason. Three things it can return instead, all of which have now happened
here:

- it can **raise**, and print a stack trace about its own plumbing
- it can **answer a different question**, and return the reassuring answer
- it can **not run at all**, and exit zero

None of these is a verdict. All three are indistinguishable, at a glance, from
a healthy subject — which is the only moment the distinction matters.

The third is the sharpest, so it goes first.

### The probe that defined its work and never did it

A verification script for the production thumbnail path: connect, initialise
the R2 client, count the cache rows before and after a render, print the render
time and the delta. Roughly 800 bytes of correct code. It ended like this:

```python
async def main():
    ...
    print('SECOND RENDER  seconds: %.1f  thumbs: %d  rows: %d -> %d' % ...)

#  ← asyncio.run(main()) was never written
```

`RC=0`. Nothing on stdout. Nothing on stderr. The output was being piped
through a `grep` that dropped WeasyPrint's logging, so the silence read as "the
filter is too tight" — and three further runs went into loosening the filter,
capturing stderr separately, and shipping the script a different way, before
anyone read the script's last line.

**It ran green, in the same session as §2's rule about checks that pass without
running.** The empty-set guard is written for precisely this and was not
applied, because a hand-run probe does not feel like a check. It is one. It
produces a fact that a decision is then made on, which is the whole definition.

The repair is one line, and it is not the missing call:

```python
asyncio.run(main())
print("PROBE REACHED THE END")
```

A terminal marker converts "no output" from ambiguous to decisive: silence now
means the probe did not finish, and anything else means it did. Every probe in
that session afterwards carried one. None of them has yet failed silently, so
the marker is a guard that has not been tested in anger — which is worth saying
plainly rather than claiming a save it did not make.

### The wrong collection returned exactly the answer that would have confirmed the gate

The question was whether GENERATING a report burns a report number. The rule is
that a number is issued at send and never at generation, and three test renders
had just been run against production — so if the rule were wrong, three numbers
were gone.

The probe read `db.report_numbers`, found nothing, and printed:

    total issued: 0

Which is precisely what a working gate looks like. Issued numbers live on
`report_emails.report_number`; `report_numbers` is a collection that has never
existed, and **Mongo does not object to a query against a collection that was
never created** — a missing collection and an empty one return the same cursor.

**This is the first row of §2's table, hit again.** `db.audit_log` against
`audit_logs` sits at the top of this document, and the shape was repeated
anyway — in the same week as, and by the same hand as, two new sections of the
document that records it. Knowing a trap by name does not stop you walking into
it. So the misspelt-collection half is not what makes this instance worth a
section of its own.

What is new is the COINCIDENCE. In the `audit_log` case the zero was merely
uninformative. Here the zero was *the answer being hoped for* — the gate
holding, no numbers burned by three test renders — which is the one condition
under which nobody looks twice at a query. A wrong check is most dangerous when
its wrong answer is also the welcome one.

The only reason it was caught is that the line above it disagreed. The counter
document said `issued: 1`, the probe said zero, and two numbers that cannot
both be true are worth four minutes. What settled it was not the probe at all:
`_next_report_number` has exactly one call site and it is in the send path,
while `generate_combined_report` calls only `_issued_report_number`, which
reads. **The call graph answered a question the query could not.**

### The anchor moved, and four assertions raised instead of failing

`_tiles()` parsed the cover's tile strip by matching `font-size:26px`. The
tiles then moved onto the report's declared type scale, the pattern matched
nothing, and the helper returned `[]`. Downstream:

```python
self.assertEqual(_tiles(self.html)[0][0], "16")
```

`IndexError: list index out of range`. Not *"the cover no longer reports 16
workers onsite"* — a stack trace about a subscript, raised from a file whose
entire subject is what the cover says. The anchor repair is §12's (bind to
`<td width="25%">`, the structure, not to a type size, a shape). The outcome
repair is separate and is this section: the helper can legitimately return
nothing, and every caller indexed it as though it could not.

### The rule

> **Every path through a check must end in an assertion.** If it can raise,
> return early, or terminate without asserting, it has outcomes that are
> neither pass nor fail — and a check with a third outcome is not a check on
> the runs where it takes it.

Three forms it takes, and the repair for each:

- **Indexing a parse result.** Assert the shape before you read into it, in the
  same test that reads into it. A sibling `test_there_are_exactly_four` does
  not protect `test_workers_onsite`; unittest runs them independently and one
  can pass while the other raises.

  ```python
  tiles = _tiles(self.html)
  self.assertEqual(len(tiles), 4, "the tile strip did not parse")
  self.assertEqual(tiles[0][0], "16")
  ```

- **A probe or script.** Print a terminal marker and require it. No output is
  then a finding rather than an ambiguity.

- **A query standing in for a gate.** Ask whether the empty result has a second
  cause. A collection that does not exist, a filter that matches nothing and a
  subject with nothing to report are one answer; prefer the call graph, the
  index, or a deliberate non-empty control that proves the query can see
  anything at all.

**The relationship to the rest of this document.** §2 asks whether a check can
pass on an empty set. §12 asks whether it is pointed at the right thing. This
section asks a narrower question that neither covers: *when this check goes
wrong, does it produce a verdict?* A check can be aimed correctly and guarded
against vacuity and still, on the day the subject changes, hand you a
traceback — and a traceback is read as "the test is broken", which is the one
conclusion that stops the investigation.

> A broken check and a broken subject must not look the same. A crash looks
> like neither, which is worse: it looks like the harness's problem, not the
> product's.

### A FOURTH OUTCOME: the subject was removed between the commit and the run

The three above are a check that raises, a check that answers the wrong
question, and a check that never runs. Here is one where the check ran
perfectly and the SUBJECT was gone.

A tenancy fix was written in a worktree and NOT committed. The control run
then swapped in the pre-fix file the ordinary way:

```bash
git checkout origin/main -- backend/server.py    # control: expect failures
# ... run, see the failures, good ...
git checkout HEAD      -- backend/server.py      # restore
```

`HEAD` was still `origin/main`, because nothing had been committed. So the
second command did not restore the fix, it re-applied the defect, and the
uncommitted work was destroyed by the step meant to put it back. The full suite
then ran for eight minutes and reported **6213 passed, 2 failed** — and the two
failures were the new tests, correctly reporting a defect that was present
again.

**The green was real and it was about the wrong tree.** A suite that passes
against code you believe you fixed, because the fix is no longer there, is the
most expensive version of this family: it costs a full run, and the two red
lines read as "my new tests are wrong" rather than "my change is missing".

> **COMMIT BEFORE THE CONTROL RUN.** The control run's whole method is to put
> the old code back and then take it away again, and `git checkout HEAD -- <f>`
> can only restore what a commit holds. Uncommitted work has no restore point,
> so the technique that proves the fix is also the technique that deletes it.

This is `git stash`'s hazard arriving through a different door, and the
standing rule against stash does not cover it. The tell is the same one §12
gives for the workspace family: **before believing a result, ask what tree it
was produced from.** `git status --short` after a restore answers it in one
line — a working tree that is clean when it should carry your change is the
finding.

### The population, measured rather than asserted

Seventeen assertions across four backend test files index a parse helper's
result inside the assertion itself — `test_the_cover_is_four_tiles_and_two_columns.py`,
`test_checkins_today_resolves_pairing.py`, `test_filed_log_photo_append.py` and
`test_no_cross_project_trade_bleed.py`. Each raises rather than fails if its
helper stops matching. They are listed here because a rule whose own repository
has seventeen live counterexamples is a rule with an exemption nobody wrote
down, and naming the count is the difference between a known gap and an
unknown one.

---


## 15. Work that is DONE and not PROPOSED does not exist

Every other section in this document is about a check that fails to detect
something. This one is not a check failing. The code was correct, the tests
were written and passing, and the work simply left the system.

A complete fix for a live defect — a doubled `data:image/png;base64,` prefix
that made every worker acknowledgment signature a broken image on 72 filed
orientation PDFs — was written and committed on 2 September 2026 on
`fix/orientation-pdf-signature`, together with 289 lines of tests. **No pull
request was ever opened.** The branch sat 136 commits behind main. The defect
stayed live for nine days and was found only because unrelated design work
happened to render one of those documents and read the image source back.

### It is not one branch

A survey found **26 remote branches** carrying commits whose patches are
genuinely absent from main — verified with `git cherry`, not a commit count, so
squash-merged work is not miscounted — and which never had a pull request.
**18 of the 26 share a single date, 2 September 2026.** That is one session's
output committed and abandoned, not 26 independent oversights.

### Nothing in this document covers it, and the reason is structural

Eleven workflows live in `.github/workflows/`. Their triggers are exhaustively
`pull_request`, `push` to `main`, and `workflow_dispatch`. The three that gate
anything — `tests.yml`, `architectural-rules.yml`, `backend-import-smoke.yml` —
are each `push: branches: [main]` plus `pull_request`. There is no `schedule:`
key in any of the eleven.

Two consequences, and the second is the whole section:

- A push to `fix/orientation-pdf-signature` ran **nothing**. Not the suite, not
  the architectural rules, not the import smoke. Its 289 lines of tests have
  never executed in CI.
- **A gate that runs on a pull request cannot see work that never became one.**
  There is no event to hang it on. Every rule above this line assumes a change
  arrives for review; this failure is defined by the change never arriving.

So the only mechanism that can observe it is one that runs on a clock and reads
the whole ref namespace rather than one event's payload.

### The detection

Verified, and in this order:

```sh
git for-each-ref --format='%(refname:short)' refs/remotes/origin
gh pr list --state all --limit 500 --json headRefName
git cherry origin/main <branch>
```

Enumerate the remote refs, drop every branch that appears as a `headRefName` on
any pull request — open, closed or merged — then run `git cherry` on what is
left and keep only the branches with `+` lines. **The `git cherry` step is not
optional.** A commit count reports a squash-merged branch as ahead of main
forever; patch equivalence is the only thing that separates work that landed
under a different SHA from work that never landed at all.

### A branch title is not a finding

Of the branches spot-checked, one's defect had **already been fixed in main by
an entirely different commit**, and another's premise no longer matched main's
text. A branch name and a commit subject describe what their author believed on
the day they wrote them, about a tree that has moved since.

> **An unproposed branch is a QUESTION, not a finding.** The sweep's output is
> *these need a look*; the look is `git cherry` and then reading main, never
> reading the title.

### Where it belongs: a periodic sweep, not CI

It cannot be a failing check, and the reason is false positives rather than
mechanism. Experiment branches, probes and abandoned spikes are the normal
output of working, and on the wire they are indistinguishable from the
orientation fix: commits not in main, no pull request. No query can tell them
apart, because the difference is intent and intent is not in the ref.

A gate that fails on all of them fails constantly and correctly-but-uselessly,
and §12 already names the property that kills such a check: the bare-literal
gate earns its keep because almost every failure it raises is real. Invert that
and you get a red mark people learn to click past.

> A sweep of this kind reports a **LIST TO TRIAGE** and never a failure.

That is what places it outside CI. CI answers pass/fail about a change under
review; here there is no change under review and no defensible fail. The right
home is a scheduled job — a `schedule:` workflow, which this repository does
not yet have, or a command someone runs on a cadence — whose output is the
list, dated, for a human to sort into *land it*, *already landed*, or *delete
it*.

---


## 16. Which of these can become a gate, and what each one would cost

> **TWO THIRDS OF THIS DOCUMENT CANNOT BE ENFORCED, AND THAT IS THE FINDING.**
> Three of the nine paragraph-only rules below can become gates. The other six
> are judgement: a keyword count cannot be distinguished from intent, a
> docstring's claim is prose by definition, and §13 established that the
> destructive commands fire no hook at all.
>
> Read the gated ones as gates and the rest as **judgement you have to exercise
> yourself**, because nothing else will exercise it for you. A document that
> knows which of its own rules are enforceable is more useful than one that
> implies all of them are, since the second kind lets a reader believe the
> suite is watching where it is not.
>
> **And do not answer a broken judgement rule by writing it more forcefully.**
> All six are already written forcefully. Four were broken by their own author
> on the day they were written.


§15 says work that is never proposed does not exist. This says something
narrower and more uncomfortable: a rule that lives only in this document is
obeyed only when nobody is in a hurry, and the preamble now carries a measured
rate for that — four breaches in one day, all by the author, all of rules
written that day.

So the useful question is not "which rules matter" but **which can be made to
fire while somebody is typing**. Two already do, and they have not recurred:
the bare-literal gate reads every `assertNotIn` in the backend suite, and the
frontend's assertions-can-fail check reads every marker-derived subject. The
commit-message guard (§14) joined them, and it is the model: pure logic in a
script, a hook that only execs it, and a refusal measured against real history
before it was allowed to refuse anything.

### The next conversion, and it is not a close call

**The unreadable-failure rule.** It is the most-broken rule in this document —
three times in one day — and it is the most mechanically detectable thing here.
`assertIn(needle, haystack)` prints the haystack; the defect is an assertion
whose second argument is a whole source file and whose third argument is
missing.

MEASURED BEFORE PROPOSING, which is the standard the commit-msg guard set:

    assertIn / assertNotIn against a whole-source haystack, no message
      sites : 78
      files : 37

So it cannot ship as "fail at zero" without 78 hand-written messages, and a
generated message is worse than none — it would satisfy the gate while telling
the reader nothing, which is the shape §12 calls a check that fails toward
"fine".

**It ships as a total that can only FALL**, which this repository has already
proven twice: the bypass sweep and the bare-literal allowlist are both pinned
in exactly one place, with every other file asserting agreement rather than
restating the number. A new site fails immediately; the existing 78 come down
on touch, the way the seventeen indexing sites do.

### The rest, honestly

| rule | gateable? |
|---|---|
| do not let an assertion print its container | **yes** — 78 sites, pinned-falling total |
| every path ends in an assertion | **partly** — the indexing shape is detectable (17 sites); a probe that never runs is not |
| do not assert on PROSE | **yes, and expensive** — `code_of` exists and is used in 33 of 348 backend test files; requiring it means auditing the other 315, most of which are merely unconverted rather than wrong |
| a keyword count cannot distinguish deliberate from accidental | no — it is a judgement about intent |
| a docstring is a claim about a relationship | no — the claim is prose by definition |
| verify the pointer, not the report of the action | no — it is about what you do next, not what you wrote |
| an error from the PROBE is not evidence about the SUBJECT | no — only the reader can tell which is which |
| unlink before remove | no — §13 established that a pathspec checkout and a recursive delete fire no hook |
| commit before the control run | **already done, indirectly** — the restore itself cannot be hooked, but the commit whose message outruns its diff can, and §14's guard does that |

Three of the nine are convertible and one of those is nearly free. That is the
honest ceiling: most of this document is judgement, and judgement cannot be
gated. Which is the argument for converting the three that can be, rather than
for writing the paragraphs more forcefully.

---


## Checklist

Before a check is worth having:

- [ ] Does it fail on the pre-fix code? Run it and see — do not assume.
- [ ] Can it pass on an empty set, an empty walk, or a scan that matched
      nothing? If so, assert the count.
- [ ] Is it pinned to a location, a spelling, or a total that could move
      without the behaviour moving?
- [ ] Does it assert the CALL or the EFFECT? Against an API that reports
      success for a no-op, only the effect distinguishes them.
- [ ] If it reads source text, does it read stripped code (`code_of`) or the
      raw file? A docstring that explains the rule will satisfy an assertion
      about the rule.
- [ ] If it asserts an absence, is the literal ANCHORED to a construct rather
      than a bare word?
- [ ] If it names a fixture as production-shaped, has anyone queried
      production?
- [ ] Does any prose in the change assert a RELATIONSHIP — "same as", "reuses",
      "mirrors", "production-shaped"? If nothing fails when that stops being
      true, either write the check or delete the claim.
- [ ] Does the thing you are about to reuse say what it must NOT be used for?
      A predicate named for your question can still answer a different one —
      `is_registered_cs` returns False for "nobody is registered", which is
      right for a menu and catastrophic for a gate.
- [ ] Does the change add a rule for a selector, key or branch this code does
      not actually emit? Dead protection reads as protection.
- [ ] Are you reporting HARM, or a code path that could cause it? If harm, name
      the query that established it. If you have not run one, say "mechanism,
      unmeasured".
- [ ] Before querying a field, have you read its DISTRIBUTION? `{f: false}` and
      `{f: {$ne: true}}` disagree about every absent key, and one group-by
      settles it.
- [ ] If a population justifies the work, have you READ the set rather than
      only counted it? A real population can still be the wrong thing to act on.
- [ ] After a push, a merge or a deploy, did you read the OBSERVABLE STATE —
      the branch pointer, `/api/version`, the row count — or the command's own
      report of itself?
- [ ] Is the check pointed at the RIGHT THING? A dead host, a stale checkout, a
      neighbouring function — each answers honestly about something else. An
      error from your PROBE is not evidence about the subject.
- [ ] If it SLICES its subject out of a file, does it assert that it FOUND the
      subject before asserting anything about it? An anchor is a location, and
      locations move — prefer a closing tag or the next top-level declaration
      over a character count or a landmark that appears twice.
- [ ] Is the assertion bound to a RELATIONSHIP or to the shape that
      relationship currently has? A pinned signature fails when an argument is
      added and the claim it defends never moved.
- [ ] Will its FAILURE be readable? `assertIn` prints its container — if that
      is a whole source file, use `assertTrue(x in y, "short message")`. A
      check that makes its own failure unreadable is one nobody runs twice. This
      one has been broken three times in a day BY THE AUTHOR OF THE RULE, so
      treat it as a reflex to be gated rather than a habit to be kept — see §16.
- [ ] Is it asserting on PROSE? If the sentence is the PRODUCT, assert it at
      its named constant. If it is RATIONALE in a comment, do not assert it at
      all — no anchoring survives a reflow, and that is a review
      responsibility.
- [ ] If the change CORRECTS something, does the correction still contain the
      words it corrects? An erased claim leaves the next grep empty, and empty
      reads as "no such problem".
- [ ] Can the verdict be swallowed in transit? `cmd | tail` returns tail's exit
      status. A prose assertion breaks on a line wrap. A search for ABSENCE
      piped through `head`/`tail` cannot tell "found nothing" from "stopped
      looking" — leave it unbounded, or count with `-c`/`-l`.
- [ ] Is the WORKSPACE the subject? `git fetch`, then
      `git rev-list --left-right --count main...origin/main`, BEFORE cutting a
      branch. A clone is not current because it is a clone, and every read
      inside a stale tree is accurate about a tree nobody deploys.
- [ ] If it bans a literal, can the correction that RETRACTS that literal still
      be written near it? Ask whether an occurrence is marked as retracted.
- [ ] Does anything ELSE read the field this change moves or removes? A
      migration has two subjects and the verifier only ever sees one — verify
      the data, then verify the code that reads it is DEPLOYED.
- [ ] If the check fails, does a broken CHECK look different from a broken
      SUBJECT? If they look the same, good. If a broken check looks like
      success, it is not a check.
- [ ] Did a cross-check fall out of the data for free? Make it an assertion,
      not a note.
- [ ] Can anything written AFTER your refusal overwrite it? A guard expressed as
      a value is only as good as the last assignment to that key.
- [ ] Does the guard you are relying on enforce in THIS environment? Read the
      deployed value of any flag it consults before trusting it — or before
      reporting that it is hollow.
- [ ] Before a destructive command: is every path it will touch INSIDE the
      thing you named? A junction or symlink means no. Unlink first, then
      remove, then read the shared resource back — the command reports on what
      it was asked to do, never on what it reached.
- [ ] When many unrelated checks fail at once right after one edit, ask whether
      the ENVIRONMENT moved before reading the diff. MODULE_NOT_FOUND across
      files with nothing in common is a deleted dependency tree, not sixty
      broken tests.
- [ ] Before a CONTROL RUN, is the work COMMITTED? The control swaps the old
      file in and then restores — and `git checkout HEAD -- <file>` restores
      only what a commit holds, so on an uncommitted tree the restore step
      deletes the fix and the next full run is green about the wrong code.
- [ ] Does EVERY path through it end in an assertion? A check that can raise,
      return early or exit without asserting has a third outcome, and a
      traceback reads as "the test is broken" — the one conclusion that stops
      the investigation. Assert the shape before indexing a parse result; give
      a probe a terminal marker so silence is a finding; and ask what ELSE
      could make a query come back empty.
- [ ] Is the work PROPOSED? Every workflow in this repository triggers on
      `pull_request`, `push` to `main`, or by hand — so a branch with commits
      and no pull request runs no gate at all, and finished-and-unmerged is
      indistinguishable from never written. Before you close out a session,
      check `git for-each-ref refs/remotes/origin` against
      `gh pr list --state all --json headRefName`.

---

## The frontend runner reported on a subset, 2026-09-12

`tests.yml`'s JS suite looped over the test files under `set -euo pipefail` and
let the first non-zero exit halt the job. **It reported ONE broken file when
five were broken**, and said nothing about the other 152.

That is the same failure mode the step's own comment already describes for the
two files that needed `@babel/core` and had therefore never executed in CI even
once: **a gate reporting on a subset and saying nothing about the rest.** The
cost of that shape is not the missed failure, it is the sequence — every fix is
followed by another red build and nobody can know how many are left.

**WHAT IT COST TO RUN THEM ALL: nothing.** Measured on the branch:

| | |
|---|---:|
| all 157 files, sequentially | 12s |
| the CI job's total wall time | 35s–67s |

The job spends most of its time on `npm ci` and the two parse sweeps. Halting
early bought no time at all.

The loop now collects failures and prints the count with the list:

    FAILED: 62 of 157 file(s)

It still exits non-zero, so nothing about the gate's strictness changes — only
what it is able to tell you when it fails.
