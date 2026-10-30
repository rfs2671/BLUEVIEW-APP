"""A PLURAL NOUN FOLLOWED BY A BARE INTEGER IS A COUNT, UNDER ATTRIBUTE (ruling 123).

Roy, 2026-10-30: "yes: small separate PR, refusals only". The question: under
the attribute intent, should any "plural noun: bare integer" clause count as a
count, even when the noun names no known family?

The leak (found by the #920 lane): "floor drains on the roof: 2." bound under
intent=attribute in 12 claim forms on main, because P-400.00's PLUMBING
ROUGH-IN SCHEDULE prints a FLOOR DRAIN row whose last cell is a 2 - a PIPE
SIZE. It refused under intent=count. #894's states_a_count did not read
"noun: N" as a count (the integer came AFTER the noun, and the noun named no
family the records know - ruling 51), so the clause took the value path.

Now a clause shaped "<plural noun phrase>: <bare integer>" (also with no
colon, in brackets, or "are 2") is decided by the count rule under attribute,
never by the value path. A value with a unit, a decimal, a dimension, a word
after the integer, a singular tag or a measurement's name keeps the value path.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_search as ps  # noqa: E402


def _rec(name, columns, rows, sheet="P-400.00"):
    return {"page_id": "p1", "record_type": "schedule", "ordinal": 0,
            "tier": "ocr_grid_cell", "source": "ocr_grid", "sheet_number": sheet,
            "file_id": "PL", "subject_terms": [name], "label": None,
            "quote": name + " " + " | ".join(c["header"] for c in columns) + " "
                     + " ".join(" | ".join(r) for r in rows),
            "payload": {"name": name, "columns": columns, "rows": rows}}


# P-400.00's FLOOR DRAIN row: the 2" in the VENT column is a pipe size.
PLUMBING = _rec(
    "ROOF PLUMBING ROUGH-IN SCHEDULE",
    [{"header": "FIXTURES", "role": None}, {"header": "ABBR", "role": "identifier"},
     {"header": "WASTE", "role": None}, {"header": "VENT", "role": None}],
    [["FLOOR DRAINS", "FD", "3\",4\"", "2"], ["ROOF DRAIN", "RD-1", "SEE SD-1", ""]])

# The pump schedule: a GPM value and a tag, which are values.
PUMPS = _rec(
    "HOT WATER PUMP SCHEDULE",
    [{"header": "MARK", "role": "identifier"}, {"header": "GPM", "role": None},
     {"header": "QTY", "role": "quantity"}],
    [["HWRP-1", "13", "2"], ["EF-1", "50 CFM", "2"]], sheet="P-401.00")

# The 12 forms the #920 lane measured (6 shapes x the POST / POST_Q states).
FLOOR_DRAIN_FORMS = [
    "floor drains on the roof: 2.", "floor drains on the roof: 2 in the filed set.",
    "floor drains on the roof 2.", "floor drains on the roof 2 in the filed set.",
    "floor drains on the roof (2).", "floor drains on the roof (2) in the filed set.",
    # and the shapes that say it another way
    "Floor drains on the roof: 2.", "The floor drains on the roof are 2.",
    "There are floor drains on the roof: 2.", "Floor drains: 2.", "The floor drains: 2.",
    "floor drains on the roof: 2",
]


def _states(clause):
    """The shape's own detector; absent on a tree without the rule."""
    return getattr(ps, "states_a_plural_integer", lambda _t: False)(clause)


def gate(text, records, intent="attribute"):
    return ps.answer_is_grounded(text, records, intent=intent)[0]


class APluralNounIntegerIsACount(unittest.TestCase):

    def test_the_floor_drain_forms_refuse_under_attribute(self):
        for t in FLOOR_DRAIN_FORMS:
            self.assertFalse(gate(t, [PLUMBING]), t)

    def test_they_refuse_under_count_too_so_the_two_intents_agree(self):
        for t in FLOOR_DRAIN_FORMS:
            self.assertEqual(gate(t, [PLUMBING]), gate(t, [PLUMBING], intent="count"), t)

    def test_any_plural_noun_phrase_before_a_bare_integer_is_a_count(self):
        for t in ("floor drains: 2.", "Exhaust fans: 13.", "The wall heaters are 4.",
                  "There are sleeves, hangers: 3.", "Fire dampers on the roof 2.",
                  "bollards: 6"):
            self.assertTrue(_states(t), t)

    def test_what_is_left_a_value(self):
        for v in ("HWRP-1: 13.", "EF-1: 50 CFM.", "PTAC-1: 9000.", "PTAC-1: 21.",
                  "The pump is 13 GPM.", "The heater is 15.0 KW.", "The studs are 20 gauge.",
                  "The studs: 20 gauge.", "Floor drains: 2 in.", "The walls are 2 hr.",
                  "occupancy load: 10.", "parapet: 42.", "The parapet is 42 high.",
                  "Ceiling heights: 9.", "There are 42.", "16 O.C.", "studs: 1.5.",
                  "Floors 2-3.", "The roof is 1970 sq ft.", "Slopes are 2%.", "Glass: 2.",
                  "The status: 2.", "The basis: 2."):
            self.assertFalse(_states(v), v)

    def test_the_value_path_still_binds_a_value(self):
        self.assertTrue(gate("HWRP-1: 13.", [PUMPS]))
        self.assertTrue(gate("EF-1: 50 CFM.", [PUMPS]))
        self.assertTrue(gate("The pump HWRP-1 is 13 GPM.", [PUMPS]))

    def test_it_changes_nothing_off_the_attribute_intent(self):
        # Ruling 123 is attribute only, refusals only: under every other
        # intent the clause is decided as it was (the union binds the printed
        # 2). Pinned so a wider change is a decision, not an accident.
        for it in ("", "identify", "existence", "location", "geometry"):
            self.assertTrue(gate("floor drains on the roof: 2.", [PLUMBING], intent=it), it)
            self.assertEqual(ps._route_counts("floor drains on the roof: 2.", [PLUMBING],
                                              every=False)[1], [], it)


class RefusalsOnly(unittest.TestCase):
    """Ruling 123 closes a leak and opens nothing: the clause must satisfy the
    count rule AND the value path. A true located count the value path refuses
    ("wall electric unit heaters on the first floor: 3.") stays refused under
    attribute, though the count rule alone would bind it."""

    def test_the_count_rule_is_asked_and_the_value_path_stays(self):
        text, bad = ps._route_counts("floor drains on the roof: 2.", [PLUMBING], every=True)
        self.assertIn("floor drains", text)    # left for the value path
        self.assertTrue(bad)                   # nothing counts them

    def test_off_every_nothing_is_asked(self):
        text, bad = ps._route_counts("floor drains on the roof: 2.", [PLUMBING], every=False)
        self.assertIn("floor drains", text)
        self.assertEqual(bad, [])

    def test_a_true_count_the_value_path_refuses_is_not_newly_bound(self):
        from tests import test_a_count_names_its_own_family as F
        recs = F._heaters()
        claim = "wall electric unit heaters on the first floor: 3."
        # the control that makes this a test: the count rule alone binds it
        self.assertTrue(gate(claim, recs, intent="count"))
        self.assertFalse(gate(claim, recs))


if __name__ == "__main__":
    unittest.main()
