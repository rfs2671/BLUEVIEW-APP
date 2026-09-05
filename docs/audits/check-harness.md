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

---

## 7. Absent versus empty — four instances, one shape

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
