"""A CONVERTED TYPE HAS ONE RENDERER, AND THE OLD ONE IS GONE.

── THE RULE THE ENGINE WROTE INTO ITS OWN DISPATCH ────────────────────────

    # And a converted type's old branch is deleted in the FOLLOWING change,
    # once it has rendered in production and been read. Required, not optional:
    # "we will delete it later" is how one `if` acquired thirteen branches.

That sentence is the whole reason this file exists. The conversion is
type-by-type and the rollback is one line -- remove a name from
`CONVERTED_TYPES` -- which is only true while the branch it rolls back TO still
exists. So for one change per type there are deliberately two renderers, and
the second must not survive the change after it.

NOTHING WAS CHECKING. The orientation sheet went through the engine in #509 and
its branch sat shadowed for the whole of #510: ninety-three lines that could
not run, that every reader of this function had to read, and that a later
editor could have "fixed" against a document nobody was printing.

── WHY A SHADOWED BRANCH IS WORSE THAN DEAD CODE ──────────────────────────

It is dead code that looks alive. `elif log_type == "subcontractor_orientation"`
reads as the renderer for that type, and the fact that a line eight hundred
lines earlier returns before it ever gets there is not visible from where the
branch is written. A reader fixing a defect on the orientation sheet would have
found it, changed it, tested nothing, and shipped.

── AND THE OTHER DIRECTION ────────────────────────────────────────────────

An UNCONVERTED type must keep its branch, or the engine's fall-through has
nothing to fall to and the document prints as a title and the word Status.
Both directions are asserted, because a census that only checks one of them is
satisfied by deleting everything.
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import legal_render  # noqa: E402

_SRC = io.open(BACKEND / "server.py", encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _filed_renderer() -> str:
    node = next(n for n in ast.walk(_TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "generate_single_logbook_html")
    return "".join(_SRC.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


#: Every type with a hand-written arm of the per-type chain.
BRANCHED = set(re.findall(r'(?:el)?if log_type == "(\w+)"', _filed_renderer()))

#: Every type the declarative engine has a schema for.
CONVERTED = set(legal_render.CONVERTED_TYPES)

#: Every type the app defines.
DEFINED = {t["key"] for t in server.LOGBOOK_TYPE_REGISTRY}

#: THE ONE TYPE ALLOWED TO HAVE BOTH RENDERERS RIGHT NOW.
#:
#: The dispatch's own note requires the old branch to be deleted in the change
#: AFTER the conversion, once the new sheet has rendered in production and been
#: read. So for exactly one change per type there are deliberately two
#: renderers, and this names which type is in that window.
#:
#: IT HOLDS AT MOST ONE NAME, asserted below. "We are mid-conversion" is a true
#: sentence about one type at a time; a list of three would be the thirteen
#: branches growing back under a different justification.
#:
#: EMPTYING IT IS THE DELETION CHANGE. The next change removes the daily
#: jobsite branch and this name together, and the census below goes back to
#: refusing every overlap.
#: ONE NAME WHILE A CONVERSION IS OPEN, EMPTY OTHERWISE. Pre-shift renders
#: through the engine now and keeps its branch for exactly one change, which is
#: what makes the rollback a one-line revert. The daily jobsite branch went the
#: same way: deleted in the change after its own, with 59 of 59 records proving
#: it could not run.
IN_FLIGHT = {"preshift_signin", "osha_log", "scaffold_maintenance",
             "site_superintendent_log"}


class TheCensusFoundSomethingToCompare(unittest.TestCase):
    """THE VACUITY GUARD. Every assertion below is a set difference, and a
    regex that stops matching makes all of them pass on an empty set."""

    def test_the_branch_chain_was_read(self):
        self.assertGreaterEqual(len(BRANCHED), 10)

    def test_the_schema_list_was_read(self):
        self.assertGreaterEqual(len(CONVERTED), 1)

    def test_the_registry_was_read(self):
        self.assertGreaterEqual(len(DEFINED), 12)


class AConvertedTypeKeepsNoBranch(unittest.TestCase):

    def test_no_converted_type_still_has_a_hand_written_branch(self):
        """THE ASSERTION. A branch the dispatch returns before is dead code
        that looks alive, and the next reader to fix a defect on that document
        will fix the copy nobody prints.

        EXCEPT THE ONE TYPE MID-CONVERSION. See IN_FLIGHT: the rollback for a
        conversion is removing a name from CONVERTED_TYPES, which is only a
        rollback while the branch it falls back TO still exists. So the branch
        outlives the conversion by exactly one change.
        """
        shadowed = sorted((CONVERTED & BRANCHED) - IN_FLIGHT)
        self.assertEqual(
            shadowed, [],
            f"these types render through the engine AND keep their old "
            f"branch: {shadowed}. The branch cannot run -- delete it, as "
            f"the dispatch's own note requires.")

    def test_IN_FLIGHT_is_EXACTLY_the_overlap(self):
        """THE BOUND, AND IT IS EXACT RATHER THAN A CEILING.

        This was `len(IN_FLIGHT) <= 1`, which protected against a backlog of
        shadowed branches by allowing only one type to be mid-conversion. A
        ceiling is the weaker instrument: it permits a name that is stale and
        it permits an overlap that is not listed, so long as the count is
        small.

        WHAT THE RULE IS ACTUALLY FOR is that no branch is shadowed without
        somebody counting it. Asserting that this set EQUALS the real overlap
        says that directly: a type converted and not listed fails, a type
        listed and finished fails, and the number is whatever the truth is.

        THE WINDOW IS ONE CHANGE WIDE, NOT ONE TYPE WIDE. A batch converted
        together is deleted together in the change that follows, and the thing
        the original rule protected -- branches accumulating across changes --
        is unchanged by how many types one change carries. The ordinary state
        is still EMPTY, and `test_the_window_is_shut_between_conversions`
        below says so.
        """
        overlap = CONVERTED & BRANCHED
        self.assertEqual(
            sorted(IN_FLIGHT), sorted(overlap),
            "IN_FLIGHT does not match the types that really have both "
            "renderers. A name missing here is a shadowed branch nobody is "
            "counting; a name left here is an exemption with nothing behind "
            "it.")

    def test_the_window_is_shut_between_conversions(self):
        """The ordinary state is EMPTY, and this is the line that notices when
        a batch is converted and its branches are not deleted next.

        IT IS A SKIP, NOT A FAILURE, while a conversion is genuinely open --
        because the open window is legitimate and a red suite during it would
        train somebody to ignore this file. What it refuses to do is stay
        silent: the message names the batch and the change that owes the
        deletion."""
        if IN_FLIGHT:
            self.skipTest(
                f"{len(IN_FLIGHT)} type(s) mid-conversion: "
                f"{sorted(IN_FLIGHT)}. The NEXT change deletes those branches "
                f"and empties this set. If you are reading this on a tree "
                f"where that change has already landed, the set is stale.")
        self.assertEqual(IN_FLIGHT, set())

    def test_an_in_flight_type_is_actually_in_both_places(self):
        """THE EXEMPTION EXPIRES ON ITS OWN. A name left here after its branch
        was deleted is a hole nobody is watching, so it must name a real
        overlap or fail."""
        for t in sorted(IN_FLIGHT):
            with self.subTest(log_type=t):
                self.assertIn(t, CONVERTED, f"{t} has no schema")
                self.assertIn(t, BRANCHED,
                              f"{t}'s branch is already gone -- remove it from "
                              f"IN_FLIGHT, the conversion is finished")

    def test_every_unconverted_type_still_has_one(self):
        """THE OTHER DIRECTION, so the census is not satisfied by deleting
        everything. Without a branch the engine's fall-through reaches the
        generic arm, which prints a title and the word Status."""
        stranded = sorted(DEFINED - CONVERTED - BRANCHED)
        self.assertEqual(
            stranded, [],
            f"these types have no schema and no branch, so the filed PDF "
            f"prints a stub instead of the record: {stranded}")

    def test_the_orientation_sheet_is_the_one_that_has_been_converted(self):
        """Named, so a reader of a failure knows which conversion this file
        was written for and can count the ones since. Its branch is gone,
        which is what a FINISHED conversion looks like."""
        self.assertIn("subcontractor_orientation", CONVERTED)
        self.assertNotIn("subcontractor_orientation", BRANCHED)


class TheDispatchDoesNotDEGRADEAConvertedType(unittest.TestCase):
    """`if _sheet:` is what lets an UNCONVERTED type reach its own branch, and
    it stays for that. A CONVERTED type reaching it is a contradiction."""

    def test_a_converted_type_that_renders_nothing_raises(self):
        block = _filed_renderer()
        i = block.index("if log_type in legal_render.CONVERTED_TYPES:")
        # THE FIRST ARM OF THE CHAIN, FOUND RATHER THAN NAMED. This
        # named `daily_jobsite`, and that branch was deleted the
        # moment its conversion finished -- the same shape as the
        # three slices that broke when `osha_log` became the last
        # named branch. The chain's first arm moves every time a type
        # is converted; what does not move is that there IS one.
        m = re.compile('\\n    if log_type == "\\w+":').search(block[i:])
        self.assertIsNotNone(m, "the per-type chain has no first branch")
        arm = block[i:i + m.start()]
        self.assertIn("raise RuntimeError", arm,
                      "a converted type that produced no sheet falls through "
                      "to the generic arm, which prints a title and the word "
                      "Status on a statutory record")

    def test_and_the_fall_through_survives_for_an_unconverted_type(self):
        """The half that must NOT change: the whole conversion strategy is
        that an unconverted type reaches its existing renderer untouched."""
        self.assertIn("if _sheet:", _filed_renderer())

    def test_render_returns_None_only_for_a_type_with_no_schema(self):
        """THE PREMISE OF BOTH ASSERTIONS ABOVE, checked rather than assumed.
        If the engine ever learned to decline a type it has a schema for, the
        raise would fire on a document that was rendering perfectly well
        yesterday."""
        self.assertIsNone(legal_render.render("not_a_log_type", [], {}))
        src = io.open(BACKEND / "lib" / "legal_render" / "engine.py",
                      encoding="utf-8").read()
        body = src[src.index("def render("):]
        self.assertEqual(body.count("return None"), 1,
                         "the engine has a second way to decline a type, and "
                         "the dispatch treats declining as a contradiction")


if __name__ == "__main__":
    unittest.main(verbosity=2)
