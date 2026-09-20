"""THE FIFTH SHAPE: an absence assertion whose literal is not the thing.

tests/source_text.py already closed one way an absence test can be about the
wrong text — it read the PROSE describing a rule instead of the code
implementing it, four times, twice after the shape had been written up. That
fix was mechanical rather than a reminder, and this is the same treatment for
the other half of the problem.

    self.assertNotIn("Pass", html)

`in` on a string is SUBSTRING containment, so this bans four characters, not a
result cell. It is satisfied — or broken — by anything that happens to contain
them: "Passed", "Bypass", "Password", a CSS class, an aria-label, a worker
called Passarelli. The assertion says one thing and checks another, and which
way it goes is luck:

  * A legitimate future addition containing the substring breaks a correct
    build, and the fix that gets reached for under time pressure is deleting
    the assertion.
  * A spelling the code actually uses but the literal does not match — "PASS"
    for "Pass" — leaves the banned thing on the page with the test green.

Neither happens when the literal is ANCHORED: `render_pass_cell(`, `>Pass<`,
`"result": "Pass"`, `pass_label =`. A syntactic anchor is the difference
between banning a construct and banning a word.

WHAT THIS FILE DOES. It reads the backend suite with `ast`, finds every
`assertNotIn` whose haystack it can PROVE is a string, and requires the needle
literal to carry an anchor or to be named below with a reason. Nothing here
inspects behaviour; it audits how the other tests are written, which is the
only place this defect lives.

WHAT IT DELIBERATELY DOES NOT COVER, and says so rather than implying
otherwise: an `assertNotIn` against a dict, a list or a set is EXACT membership
and is not this shape at all, so a bare key name there is correct and is not
flagged. The classifier only flags haystacks it can prove are strings, which
makes its reach a LOWER BOUND — `unclassified_count` is asserted so the number
is visible and a future refactor that hides every haystack behind a helper
cannot quietly empty this file out.

A NEIGHBOUR, REPORTED AS A LEAD AND NOT ADDRESSED HERE. Six assertions across
five files still hand-roll their own comment stripper instead of going through
tests/source_text.py — test_audit_production, test_notification_presets_shape,
test_ranker_reads_what_the_editor_writes (three), test_report_print_width. Each
strips ONE comment syntax, which is the half-covered shape that helper exists to
stop being re-derived per file; test_logbook_renderers' crew_name check was the
seventh and is converted in this change because its own docstring claimed
docstrings were handled and its stripper only removed `#` lines. The remaining
six are a different guard's job — several strip a partial slice deliberately —
and they are named here so the count is on the record rather than implied to be
zero.

Run:  python -m pytest tests/test_absence_literals_are_specific.py -q

THE SCANNER NOW LIVES IN `tests/absence_literals.py`, because the same
rule is enforced by `.githooks/pre-commit` on the staged files and two
copies of a classifier drift. This file keeps the checks that need the
WHOLE suite in hand -- the allowlist not rotting, and the floors that stop
a refactor quietly emptying the scan out -- which a hook cannot do.
"""

from __future__ import annotations

import ast
import unittest

from tests.absence_literals import (
    _ANCHORS,
    _BARE_BY_DESIGN,
    _haystack_is_string,
    _string_names,
    offenders,
    scan as _scan,
)


class AbsenceLiteralsAreSpecific(unittest.TestCase):
    """Every string-haystack assertNotIn bans a construct, not a word."""

    def test_no_unjustified_bare_literal(self):
        """Through `offenders()` DELIBERATELY, because that is the function
        the pre-commit hook calls. Re-deriving the filter here would leave the
        hook's actual code path unproven by the gate."""
        found = offenders()
        self.assertEqual(
            [], found,
            "assertNotIn against a STRING bans a substring, so a bare word is "
            "satisfied — or broken — by anything that happens to contain it. "
            "Anchor the literal (>Pass<, render_pass_cell(, \"result\": \"Pass\") "
            "or add it to _BARE_BY_DESIGN with a reason: " + repr(found),
        )

    def test_the_allowlist_does_not_rot(self):
        """An entry that no longer matches anything is a stale rule."""
        bare, _anchored, _unclassified, _total = _scan()
        live = {(f.file, f.literal) for f in bare}
        stale = sorted(_BARE_BY_DESIGN - live)
        self.assertEqual(
            [], stale,
            "these _BARE_BY_DESIGN entries no longer match any assertNotIn — "
            "the assertion was anchored, moved or deleted: " + repr(stale),
        )

    def test_the_scanner_is_still_finding_things(self):
        """Every assertion above is vacuously true against an empty scan.

        The classifier only flags haystacks it can PROVE are strings, so a
        refactor that routes every source read through a helper it does not
        recognise would silently empty this file out and leave it green. These
        two floors fail loudly instead.
        """
        bare, anchored, unclassified, total = _scan()
        self.assertGreater(
            anchored, 15,
            f"the scanner found only {anchored} anchored assertNotIn calls "
            "against a string — it has stopped recognising source-text bindings",
        )
        self.assertGreater(
            len(bare) + anchored, 20,
            "the scanner classified almost nothing as a string haystack",
        )
        # A LOWER BOUND, stated. Most of these are dict / list membership,
        # which is exact and not this shape — but the count is asserted so a
        # sudden jump is visible rather than silent.
        #
        # 400 -> 410 with test_filed_log_photo_append.py, which asserts that a
        # server-minted photo row carries no `base64` and no `enhance_status`
        # key. That is dict membership — exact, and precisely the kind this
        # bucket exists to hold. The ceiling moves; the shape of the rule does
        # not.
        # 410 -> 440 AS HEADROOM, and THE NUMBER IS THE DEBT, not the fix.
        #
        # test_r2_listing_cannot_be_trusted.py took this from 408 to 410 against
        # a ceiling of 410 -- one file tripping a limit that has nothing to do
        # with what it tests. That file later shrank and the count is 409 again,
        # so this raise is NOT covering a current breach; it is headroom, and it
        # is recorded as such rather than left to read as a response to one. The
        # previous bump documented its own cause the same way. Same shape this
        # log keeps recording: a hand-maintained number standing in for a
        # structural property, going stale in the direction nobody watches.
        #
        # WHAT MAKING IT STRUCTURAL WOULD ACTUALLY TAKE, so the next reader does
        # not assume it is cheap: `unclassified` counts assertNotIn haystacks
        # `_haystack_is_string` cannot PROVE are strings. Today it resolves
        # literals, f-strings, joins, slices of known strings, and a short list
        # of string-returning calls. The remainder are bound through helper
        # returns, fixture attributes, method calls on test objects and
        # cross-module imports — so eliminating the bucket means real type
        # inference across the whole test corpus, not another special case.
        # That is a project, not an afternoon, and it buys a count nobody reads.
        #
        # The honest alternative, if this trips again: assert the RATE rather
        # than the total (unclassified / total assertNotIn), which does not move
        # when the suite merely grows. Recorded rather than built.
        # BUILT, ON THE THIRD TRIP. The note above recorded the alternative and
        # left it unbuilt; the ceiling has now been tripped a third time, again
        # by ONE assertion in a file with nothing to do with this one -- which
        # is the shape the note itself complains about. A total is a
        # hand-maintained number standing in for a structural property, and it
        # goes stale in the direction nobody watches: every raise is invisible
        # progress toward a guard that means nothing.
        #
        # THE RATE DOES NOT MOVE WHEN THE SUITE MERELY GROWS. What it still
        # catches is the thing the total was for: a refactor that hides
        # haystacks behind helpers, which raises unclassified WITHOUT raising
        # total and so pushes the rate up. The floor is set from the measured
        # value with headroom, and the measurement is printed in the failure so
        # the next reader is not left computing it.
        rate = unclassified / total if total else 0.0
        self.assertLess(
            rate, 0.60,
            f"{unclassified} of {total} assertNotIn haystacks ({rate:.1%}) could "
            "not be classified; a RISING RATE means haystacks are moving behind "
            "helpers, not that the suite grew. The classifier needs the new "
            "binding shape.",
        )

    def test_the_rate_has_a_denominator(self):
        """The empty-set guard. A scan that matched nothing gives rate 0.0 and
        satisfies the assertion above, which is exactly the vacuous pass this
        file exists to refuse elsewhere."""
        _b, _a, _u, total = _scan()
        self.assertGreater(total, 600, f"only {total} assertNotIn calls found")

    def test_an_anchored_literal_is_recognised_as_anchored(self):
        """The control: the rule must be able to tell the two apart."""
        self.assertTrue(any(c in _ANCHORS for c in 'render_pass_cell('))
        self.assertTrue(any(c in _ANCHORS for c in '>Pass<'))

    def test_a_slice_of_a_string_is_classified_as_a_string(self):
        """The control for the shape _haystack_is_string was extended to see.

        Without this the extension is invisible: it would silently stop
        recognising slices again and the only symptom would be `unclassified`
        drifting back up, which is exactly the kind of quiet emptying-out
        test_the_scanner_is_still_finding_things exists to prevent.

        The negative half matters as much as the positive: INDEXING must stay
        unclassified. `docs[0]` is a list element and `d["k"]` a dict value,
        and treating either as a string would flag correct exact-membership
        assertions as substring bans.
        """
        tree = ast.parse(
            "SRC = read_text()\n"
            "i = 0\n"
            "sliced = SRC[i:9]\n"
            "indexed = SRC[0]\n"
        )
        names = _string_names(tree)
        self.assertIn("SRC", names)
        body = {t.targets[0].id: t.value for t in tree.body}
        self.assertTrue(_haystack_is_string(body["sliced"], names))
        self.assertFalse(_haystack_is_string(body["indexed"], names))
        # A slice of something NOT known to be a string stays unclassified.
        other = ast.parse("x = unknown[1:2]\n").body[0].value
        self.assertFalse(_haystack_is_string(other, names))
        self.assertTrue(any(c in _ANCHORS for c in 'db.logbooks'))
        self.assertTrue(any(c in _ANCHORS for c in 'OSHA 40hr'))
        self.assertFalse(any(c in _ANCHORS for c in 'Pass'))
        self.assertFalse(any(c in _ANCHORS for c in 'crew_name'))

    def test_a_dict_haystack_is_not_flagged(self):
        """A bare key against a mapping is EXACT membership and is correct.

        Asserted by running the classifier over a synthetic module rather than
        by trusting the description of it.
        """
        mod = ast.parse(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        body = {'a': 1}\n"
            "        self.assertNotIn('company', body)\n"
        )
        names = _string_names(mod)
        self.assertNotIn("body", names, "a dict literal is not a string binding")

    def test_a_source_haystack_is_flagged(self):
        """And the same classifier DOES see a source read."""
        mod = ast.parse(
            "from tests.source_text import code_of\n"
            "SRC = code_of('server.py')\n"
            "CODE = SRC.replace('x', 'y')\n"
        )
        names = _string_names(mod)
        self.assertIn("SRC", names)
        self.assertIn("CODE", names, "a derived string is still a string")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
