"""RULING 151 (Roy, 2026-10-30): "<singular mark> [scope] [set]: <bare integer>"
under the attribute intent is a count's shape, and a REFUSAL ONLY.

On 588 Boyland's production rows, 168 such claims bound through the value path;
156 were wrong or unconfirmed ("D1: 8.", "W1: 5.", "W3: 4."), because the
identifier-less A-400.00 door and window schedules make every cell a part named
by the header ("W1 NUMBER | W2 NUMBER"), so a stray digit of an OCR'd dimension
"named" W1. The count rule's refusal is now added; the clause is never blanked,
so when the count rule says ok the value path decides as before.

These pin the SHAPE; the production claim diff (exactly the 156 bound->refused,
the 12 correct ones still bound) is in the PR body.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_search as S  # noqa: E402


def _need(name):
    assert hasattr(S, name), f"not built: plan_search.{name}"
    return getattr(S, name)


class AMarkAndABareIntegerIsACountShape(unittest.TestCase):

    def test_the_wrong_claims_are_count_shaped(self):
        f = _need("states_a_mark_integer")
        for c in ("D1: 8.", "D2 1.", "W1: 5.", "W3 in the filed set: 4.", "W2 per the owner's set: 6.",
                  "D1 on the first floor: 3."):
            self.assertTrue(f(c), c)

    def test_a_value_with_a_unit_or_a_dimension_is_not(self):
        f = _need("states_a_mark_integer")
        for c in ("PTAC-1: 9000 BTUH.", "EF-1: 50 CFM.", "W1: 5'-0\".", "PTAC-1: 1.5 kW.",
                  "D1: 3 hours.", "W1 is 36 inches wide."):
            self.assertFalse(f(c), c)

    def test_a_plural_noun_stays_the_plural_rule(self):
        f = _need("states_a_mark_integer")
        self.assertFalse(f("exhaust fans in 1B: 2."))
        self.assertTrue(S.states_a_plural_integer("exhaust fans in 1B: 2."))

    def test_only_a_located_familys_mark(self):
        tags = _need("_located_tags")
        self.assertEqual(tags([]), set(), "no books, no marks: a pump's HWRP-1 13 is a value's")

    def test_the_route_adds_the_refusal_and_never_blanks(self):
        src = Path(S.__file__).read_text(encoding="utf-8")
        i = src.index("states_a_mark_integer(clause)")
        block = src[i:i + 700]
        self.assertIn("bad += refused", block)
        self.assertNotIn("route, decided = True", block, "a mark's count never routes the clause whole")


if __name__ == "__main__":
    unittest.main()
