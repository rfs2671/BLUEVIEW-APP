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
colon, in brackets, or "are 2") is decided by the count rule under attribute:
it binds exactly when the count rule binds it from a counting source, and the
count rule's refusal stands otherwise (the ruling of 2026-10-30 on #931's 867
located counts - see ALocatedCountBindsFromItsCountingSource). A value with a unit, a decimal, a dimension, a word
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


class ALocatedCountBindsFromItsCountingSource(unittest.TestCase):
    """The ruling of 2026-10-30 on #931's 867 located counts (Roy): "verify each
    against its source rows, bind only counting-source-confirmed ones". Under
    attribute a "<plural noun phrase>: <bare integer>" clause is the count
    rule's, and binds exactly when the count rule binds it - from a counting
    source: a located tally whose census matched, at the scope the clause
    names, with nothing unread or refused in it; a schedule's QTY at building
    scope; a door or window book's figure. A count that is true but rests on
    no counting source (a census short of a row, a sheet whose located rows do
    not equal its own sweep) and a wrong figure still refuse. #931's refusals
    stand."""

    # (clause, true) over WH-1 as a question about it returns it: 3 on the
    # first floor, census QTY 3.
    HEATERS = [("wall electric unit heaters on the first floor: 3.", True),
               ("wall electric unit heaters: 3.", True),
               ("WH-1 wall heaters: 3.", True),
               ("The wall electric unit heaters are 3.", True),
               ("wall electric unit heaters on the first floor: 2.", False),
               ("wall electric unit heaters on the first floor: 4.", False),
               ("wall electric unit heaters: 9.", False),
               ("water heaters on the first floor: 3.", False),
               ("WH-1 water heaters: 3.", False)]

    def test_a_true_located_count_binds_under_attribute(self):
        from tests import test_a_count_names_its_own_family as F
        recs = F._heaters()
        for clause, true in self.HEATERS:
            self.assertEqual(gate(clause, recs), true, clause)

    def test_it_binds_exactly_where_the_count_rule_binds_it(self):
        from tests import test_a_count_names_its_own_family as F
        recs = F._heaters()
        for clause, _true in self.HEATERS:
            self.assertEqual(gate(clause, recs), gate(clause, recs, intent="count"), clause)

    def test_per_floor_per_unit_and_per_set_figures(self):
        from tests import test_two_drawing_tracks as T
        recs = T._world()
        for clause in ("PTAC units on the first floor: 5.", "PTAC units on the second floor: 4.",
                       "PTAC-1 units in 2A: 1.", "PTAC units in 1B: 1.",
                       "PTAC units on the second floor per the owner's set: 4."):
            self.assertTrue(gate(clause, recs), clause)
        for clause in ("PTAC units on the first floor: 4.", "PTAC units on the second floor: 5.",
                       "PTAC-1 units in 2A: 2."):
            self.assertFalse(gate(clause, recs), clause)

    def test_a_window_by_its_tag(self):
        from tests import test_a_door_is_counted_by_its_tag as D
        recs = D._world(D._second_floor("filed"), tracks=("filed",))
        self.assertTrue(gate("W1 windows on the second floor: 8.", recs))
        self.assertFalse(gate("W1 windows on the second floor: 7.", recs))
        self.assertFalse(gate("W1 doors on the second floor: 8.", recs))

    def test_a_count_no_counting_source_confirms_stays_refused(self):
        # The census holds one row more than the rows in hand: the count may be
        # true, but nothing checked it. The count rule refuses it under count;
        # under attribute the value path must not bind it instead.
        from tests import test_two_drawing_tracks as T
        recs = T._world(short={"filed": 1, "post_co": 1})
        for clause in ("PTAC units on the first floor: 5.", "PTAC units on the second floor: 4.",
                       "PTAC units: 9."):
            self.assertFalse(gate(clause, recs, intent="count"), clause)
            self.assertFalse(gate(clause, recs), clause)

    def test_a_sheet_whose_rows_disagree_with_its_own_sweep_stays_refused(self):
        from tests import test_two_drawing_tracks as T
        recs = T._world(owner_mech=7)       # the owner's M-100 sweep locates 7; 5 rows
        clause = "PTAC units on the first floor: 5."
        self.assertFalse(gate(clause, recs, intent="count"))
        self.assertFalse(gate(clause, recs))

    def test_a_figure_one_drawing_set_states_and_the_other_set_does_not_is_not_confirmed(self):
        # T._world(): the filed first floor holds one PTAC in each of its four
        # units; the owner's set has two in 1A (PTAC-1 and PTAC-3), so no
        # uniform per-apartment figure. glyph_values binds the filed figure
        # alone (ruling 2026-10-24 "label, don't refuse") - and does under
        # intent=count. Through attribute a located count must be confirmed
        # by every set that located the symbols there.
        from tests import test_two_drawing_tracks as T
        recs = T._world()
        for clause in ("PTAC units in each unit on the first floor: 1.",
                       "PTACs in each unit on the first floor 1."):
            # ruling 150: the count rule refuses it too (it names no set and the
            # owner's 1A holds two); it binds naming the filed set
            self.assertFalse(gate(clause, recs, intent="count"), clause)
            self.assertFalse(gate(clause, recs), clause)
        self.assertTrue(gate("PTAC units in each unit on the first floor in the filed set: 1.", recs))
        # where both sets state one figure it binds
        self.assertTrue(gate("PTAC units in each unit on the second floor: 1.",
                             T._world(filed_101=T.OWNER_101)))

    def test_a_set_that_located_the_symbols_and_withholds_its_count_stops_the_attribute_figure(self):
        # The owner's first floor has a fifth symbol it cannot place: it says
        # NOTHING (no count). Under count the filed figure binds (ruling
        # 2026-10-24, one track alone); a located count bound through
        # attribute must be confirmed by every set that located it (#933).
        from tests import test_two_drawing_tracks as T
        own = [("PTAC-1", "1A"), ("PTAC-2", "1B"), ("PTAC-3", "1C"), ("PTAC-3", "1D"),
               ("PTAC-3", None)]
        recs = T._world(owner_100=own)
        clause = "PTAC units in each unit on the first floor: 1."
        self.assertTrue(gate(clause, recs, intent="count"))
        self.assertFalse(gate(clause, recs))

    def test_a_set_with_nothing_at_the_scope_is_not_silent_there(self):
        # The owner's set draws no first floor: it located nothing there, so
        # it is no track "saying nothing" (the guard needs LOCATED symbols).
        import lib.plan_search as S
        from tests import test_two_drawing_tracks as T
        clause = "PTAC units in each unit on the first floor: 1."
        rows = T._numbered(T._rows("filed", "100", T.FILED_100) + T._rows("filed", "101", T.FILED_101)
                           + T._rows("post_co", "101", T.OWNER_101))
        recs = list(rows) + T._census(rows, "filed") + T._census(rows, "post_co")
        self.assertFalse(S._located_but_silent(clause, S.glyph_books(recs), {"1"}, True))
        withheld = T._world(owner_100=[("PTAC-1", "1A"), ("PTAC-2", "1B"), ("PTAC-3", "1C"),
                                       ("PTAC-3", "1D"), ("PTAC-3", None)])
        self.assertTrue(S._located_but_silent(clause, S.glyph_books(withheld), {"1"}, True))

    def test_floor_drains_and_piles_stay_refused(self):
        for t in FLOOR_DRAIN_FORMS:
            self.assertFalse(gate(t, [PLUMBING]), t)
        self.assertFalse(gate("piles: 7.", [PLUMBING]))

    def test_the_clause_is_left_to_the_value_path_only_when_the_count_rule_refuses_it(self):
        from tests import test_a_count_names_its_own_family as F
        recs = F._heaters()
        text, bad = ps._route_counts("wall electric unit heaters on the first floor: 3.", recs, every=True)
        self.assertNotIn("heaters", text)                         # the count rule's: blanked,
        self.assertEqual(bad, [])                                 # and nothing refused
        text, bad = ps._route_counts("wall electric unit heaters on the first floor: 4.", recs, every=True)
        self.assertIn("heaters", text)                            # refused: kept, with its refusal
        self.assertTrue(bad)
        text, bad = ps._route_counts("floor drains on the roof: 2.", [PLUMBING], every=True)
        self.assertIn("floor drains", text)
        self.assertTrue(bad)

    def test_off_every_nothing_is_asked(self):
        text, bad = ps._route_counts("floor drains on the roof: 2.", [PLUMBING], every=False)
        self.assertIn("floor drains", text)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
