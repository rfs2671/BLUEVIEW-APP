"""AN ASSERTION MAY NOT PRINT A WHOLE SOURCE FILE WHEN IT FAILS.

`assertIn(needle, haystack)` PRINTS THE HAYSTACK. When the haystack is
`server.py` that is 2.3MB of escaped source with the one fact that matters
buried somewhere inside it -- enough to blow a terminal, a CI log pane and a
context window at once. The repair is one character of API:

    self.assertIn("x", _SRC)                      # 2.3MB on failure
    self.assertTrue("x" in _SRC, "short message") # one line

── WHY THIS IS A GATE AND NOT A PARAGRAPH ────────────────────────────────────

§12 has said this in prose since it was written. It is the MOST-BROKEN rule in
that document: three times in one day, every one by the author of the rule, on
the day the rule was written. Once against an `ast.dump`, once against a 2.3MB
source string in a brand-new test, and once found sitting in an existing test
while that test was being repaired.

That is the measured rate §16 records, and it is the argument this file exists
to answer: knowing a trap by name does not slow the hand down, so the check has
to fire where the hand is.

── A PINNED TOTAL THAT CAN ONLY FALL, NOT A ZERO ─────────────────────────────

There are 78 of these today across 37 files. Failing at zero would mean writing
78 messages in one sitting, and a GENERATED message is worse than none: it
satisfies the gate while telling the reader nothing, which is exactly the shape
§12 calls a check that fails toward "fine".

So the number is pinned HERE, in one place, and it is designed to FALL. A new
site fails immediately. The existing ones come down on touch, the way §14's
seventeen indexing sites do. If you removed one, lower the number -- being made
to edit it is the point, because that is the line that records the progress.

THE DENOMINATOR IS ASSERTED TOO. 78 means nothing without the 3315 assertions
it is drawn from: a walk that silently stopped seeing `assertIn` calls would
report zero violations and pass every check below except that one.
"""

from __future__ import annotations

import ast
import io
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent

#: Names that hold a whole file's source in this suite. A SLICE of one is fine
#: and is deliberately not matched -- `_SRC[i:i + 400]` prints 400 characters,
#: which is a readable failure and a common, correct idiom here.
BIG_NAMES = {"_SRC", "SRC", "_CODE", "CODE", "_SOURCE", "SOURCE", "_TEXT"}

#: Calls that RETURN a whole file's source, or something as long. `dump` and
#: `unparse` are in this set because they are how the rule was broken twice:
#: an AST dump of one function is thousands of characters and reads, at a
#: glance, like a small value.
BIG_CALLS = {"code_of", "read_text", "unparse", "dump"}


def _haystack_is_whole_source(node) -> bool:
    if isinstance(node, ast.Name):
        return node.id in BIG_NAMES
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in BIG_CALLS:
            return True
        if isinstance(f, ast.Attribute) and f.attr in BIG_CALLS:
            return True
    return False


def scan(tree) -> tuple:
    """(offending call nodes, total assertIn/assertNotIn calls seen).

    THE TOTAL IS RETURNED, NOT JUST THE HITS, so a caller can tell an empty
    result apart from a walk that stopped working. They are the same value
    and they are not the same news.
    """
    hits, total = [], 0
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in ("assertIn", "assertNotIn"):
            continue
        total += 1
        # A THIRD ARGUMENT IS THE MESSAGE. With one, unittest prints that
        # instead of the container, so the assertion is readable and this
        # rule is satisfied without changing the API.
        if len(n.args) >= 2 and _haystack_is_whole_source(n.args[1]) \
                and len(n.args) < 3 and not any(k.arg == "msg" for k in n.keywords):
            hits.append(n)
    return hits, total


def unreadable_failure_sites():
    """`file:line` for every assertion that would print a source file."""
    out, total = [], 0
    for path in sorted(_TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        hits, n = scan(tree)
        total += n
        out.extend(f"{path.name}:{h.lineno}" for h in hits)
    return out, total


#: PINNED IN ONE PLACE, AND DESIGNED TO FALL. 78 across 37 files on the day
#: this gate was written. Lower it when you fix one; never raise it.
#:
#: 78 -> 65 on 2026-09-12. Thirteen went with the report replacement: seven
#: test files were deleted outright and several survivors were re-anchored on
#: a view object or a rendered page instead of all 47,000 lines of server.py.
#: None was "fixed" by weakening an assertion -- the haystacks got smaller
#: because what they read got smaller.
EXPECTED_TOTAL = 65


class AnAssertionMayNotPrintASourceFile(unittest.TestCase):

    def test_the_total_matches_the_single_pinned_number(self):
        sites, _ = unreadable_failure_sites()
        self.assertEqual(
            len(sites), EXPECTED_TOTAL,
            "\n  If this went UP, an assertion was added whose failure prints a\n"
            "  whole source file. Give it a short message instead:\n"
            "      self.assertTrue(x in _SRC, \"what is wrong\")\n"
            "  If it went DOWN, you fixed one -- lower EXPECTED_TOTAL in this\n"
            "  file. Being made to edit that line is the point.\n"
            f"  Now: {len(sites)}, pinned: {EXPECTED_TOTAL}")

    def test_the_scanner_is_still_finding_things(self):
        """The empty-set guard. A walk that matched nothing would pass every
        other assertion here the day someone broke it."""
        sites, _ = unreadable_failure_sites()
        self.assertGreater(len(sites), 0,
                           "the scanner found nothing at all, which after 78 "
                           "is a broken walk rather than a clean suite")

    def test_the_rate_has_a_denominator(self):
        """78 is meaningless without what it is 78 OF. If this collapses, the
        walk stopped seeing assertions and the count above is about nothing."""
        _, total = unreadable_failure_sites()
        self.assertGreater(
            total, 2000,
            f"only {total} assertIn/assertNotIn calls were seen across the "
            "suite; the walk is not reading the tests")


class TheDetectorItself(unittest.TestCase):
    """Executed against synthetic source, because a scanner nobody has seen
    refuse anything is a scanner that might refuse nothing."""

    def _sites(self, src):
        hits, _ = scan(ast.parse(src))
        return len(hits)

    def test_a_whole_source_haystack_with_NO_message_is_caught(self):
        self.assertEqual(self._sites('self.assertIn("x", _SRC)'), 1)
        self.assertEqual(self._sites('self.assertNotIn("x", _CODE)'), 1)
        self.assertEqual(self._sites('self.assertIn("x", code_of("server.py"))'), 1)
        self.assertEqual(self._sites('self.assertIn("x", ast.dump(fn))'), 1)
        self.assertEqual(self._sites('self.assertIn("x", ast.unparse(fn))'), 1)

    def test_a_MESSAGE_makes_it_readable_and_is_accepted(self):
        """The fix this gate is asking for, positionally and by keyword."""
        self.assertEqual(self._sites('self.assertIn("x", _SRC, "why")'), 0)
        self.assertEqual(self._sites('self.assertIn("x", _SRC, msg="why")'), 0)

    def test_a_SLICE_is_not_a_source_file(self):
        """`_SRC[i:i + 400]` prints 400 characters. That is a readable failure
        and the commonest correct idiom in this suite -- flagging it would put
        hundreds of false positives in front of a reader, and a gate at that
        rate is one somebody turns off."""
        self.assertEqual(self._sites('self.assertIn("x", _SRC[i:i + 400])'), 0)
        self.assertEqual(self._sites('self.assertIn("x", body)'), 0)

    def test_assertTrue_is_never_flagged(self):
        """It carries no container, so its failure is the message and nothing
        else. That is the whole repair."""
        self.assertEqual(self._sites('self.assertTrue("x" in _SRC, "why")'), 0)

    def test_the_total_counts_BOTH_kinds(self):
        _, total = scan(ast.parse(
            'self.assertIn("a", b)\nself.assertNotIn("c", d)\n'
            'self.assertTrue("e" in f)'))
        self.assertEqual(total, 2, "assertTrue was counted as an assertIn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
