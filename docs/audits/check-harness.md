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

---

> **If you read one section, read §10 — "Verify the pointer, not the report of
> the action".** It is last only because `server.py` and
> `test_weasyprint_break_inside_semantics.py` cite section numbers by number and
> renumbering would break them. It generalises further than anything above it:
> *a tool reporting its own success is describing its intent, not the world.*


## 1. Three patterns that work

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
- [ ] Can anything written AFTER your refusal overwrite it? A guard expressed as
      a value is only as good as the last assignment to that key.
- [ ] Does the guard you are relying on enforce in THIS environment? Read the
      deployed value of any flag it consults before trusting it — or before
      reporting that it is hollow.
