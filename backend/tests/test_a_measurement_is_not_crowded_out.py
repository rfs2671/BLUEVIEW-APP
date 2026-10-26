"""An attribute question gets the records that state its value, appended
(ruling 2026-10-26, option B).

Asked how high the sidewalk shed is, the eight results were mentions -
SIDEWALK SHED, TYPICAL SIDEWALK SHED ELEVATION, a permit note, a letterhead -
and 8' HIGH SHED, which prints one word of the subject and the answer, ranked
ninth to eleventh.

The rule: when fewer than two of the results state a value, up to two more
records that state one AND print a word of the subject - never only the
attribute's word - follow them as a ninth and tenth. Nothing is moved or
dropped: the first ruling's version replaced the last two slots and pushed
out S-102.00's beam size and S-401.00's boxed header details, which answer
their questions without a number.

The records are 588 Boyland's as production returns them (2026-10-25).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")


def _r(sheet, quote, rt="text"):
    return {"sheet_number": sheet, "quote": quote, "record_type": rt, "tier": "text_layer"}


SHED_SHOWN = [_r("SSP-009.00", "SIDEWALK SHED"),
              _r("SSP-010.00", "SIDEWALK SHED PARAPET PANEL LAYOUT SCALE: N.T.S."),
              _r("SSP-013.00", "TYPICAL SIDEWALK SHED ELEVATION"),
              _r("SSP-002.00", "5. PERMITS FOR SIDEWALK SHEDS SHALL BE OBTAINED AS REQUIRED", "note"),
              _r("SSP-013.00", "DIAGONAL BRACING EVERY 4th BAY, ADD'L BRACING TO BE PROVIDED"),
              _r("SSP-002.00", "6. SIDEWALK SHED AND PROTECTION FOR ALL PUBLIC/PEDESTRIANS", "note"),
              _r("SSP-002.00", "44. CLOSE OUT INSTRUCTIONS: PARTIAL REMOVING SIDEWALK SHEDS", "note"),
              _r(None, "72-41 Burchell Ave, Far Rockaway NY 11692 SIDEWALK SHED")]
SHED_REST = [_r("SSP-003.00", "8' HIGH SHED", "legend_entry"),
             _r("SSP-004.00", "8' HIGH SHED", "legend_entry"),
             _r("SSP-005.00", "8' HIGH SHED", "legend_entry")]

BEAM_SHOWN = [_r("S-002.00", "BEAM"), _r("S-301.00", "BOX BEAM SEE SCHED."),
              _r("S-402.00", "BOX BEAM, SEE PLANS FOR DETAILS"),
              _r("SSP-013.00", "BEAM (HEADER) W10X26"), _r("SSP-013.00", "SECONDARY BEAMS, S4X7.7"),
              _r("SSP-013.00", "BEAM (HEADER) W12X30"),
              _r("SSP-013.00", "SECONDARY BEAMS, S4X7.7 2'-0\" ON CENTER"),
              _r("S-102.00", "4. INDICATES (2) 800S162-54 BOX BEAM U.O.N.", "note")]
BEAM_REST = [_r("S-104.00", "4. INDICATES (2) 800S162-118 BOX BEAM U.O.N.", "note"),
             _r("SSP-013.00", "BEAM (2-IEADEFE)1@ 8'-0\" O.C FOR SEE TABLE 1")]


def _ps():
    from lib import plan_search as ps
    assert hasattr(ps, "value_records"), "no value records are appended (main)"
    return ps


class TheMeasurementComesBack(unittest.TestCase):

    def test_the_shed_height_is_appended(self):
        ps = _ps()
        got = ps.value_records(SHED_SHOWN, SHED_REST, "sidewalk shed", "height")
        self.assertEqual([r["quote"] for r in got], ["8' HIGH SHED", "8' HIGH SHED"])
        self.assertEqual([r["sheet_number"] for r in got], ["SSP-003.00", "SSP-004.00"])

    def test_at_most_two_and_only_when_fewer_than_two_state_a_value(self):
        ps = _ps()
        self.assertEqual(len(ps.value_records(SHED_SHOWN, SHED_REST, "sidewalk shed", "height")), 2)
        two = SHED_SHOWN[:6] + [_r("SSP-005.00", "8'-0\""), _r("SSP-006.00", "8'-0\" SHED")]
        self.assertEqual(ps.value_records(two, SHED_REST, "sidewalk shed", "height"), [])


class NothingIsPushedOut(unittest.TestCase):

    def test_the_beam_size_stays_and_one_more_follows_it(self):
        # Asked the beam SIZE: one of the eight states a value (2'-0" ON
        # CENTER), so one more may follow - and S-102.00's beam size, eighth,
        # is still there.
        ps = _ps()
        got = ps.value_records(BEAM_SHOWN, BEAM_REST, "beam", "size")
        self.assertEqual([r["quote"] for r in got], ["BEAM (2-IEADEFE)1@ 8'-0\" O.C FOR SEE TABLE 1"])
        self.assertIn("800S162-54", BEAM_SHOWN[-1]["quote"])

    def test_the_header_details_stay(self):
        # S-401.00's header types, seventh and eighth, state no value: asked
        # the header TYPE, the two value records go after them, not over them.
        ps = _ps()
        shown = [_r("S-401.00", t) for t in ("HEADER MEMBERS", "HEADER TRACKS", "HEADER ATTACHMENT",
                                              "HEADER TRACK")] + [
            _r("SSP-013.00", "BEAM (HEADER) W10X26"), _r("SSP-013.00", "BEAM (HEADER) W12X30"),
            _r("S-401.00", "5 SCALE: N.T.S. TYPICAL BOXED HEADER DETAIL CONNECTION"),
            _r("S-401.00", "4 SCALE: N.T.S. WINDOW - LOAD BEARING BACK TO BACK SINGLE HEADER SINGLE JAM")]
        rest = [_r("S-101.00", "PROVIDE A DISTRIBUTION HEADER CONSISTING OF (2) 12J12 @ 16\" O.C.", "dimension")]
        got = ps.value_records(shown, rest, "header", "type")
        self.assertEqual(len(got), 1)
        out = shown + got
        self.assertEqual(out[6:8], shown[6:8])
        self.assertIn("BOXED HEADER", out[6]["quote"])

    def test_the_search_appends_and_never_replaces(self):
        import inspect
        import server
        src = inspect.getsource(server.search_plans)
        self.assertIn("plan_search.value_records(", src)
        self.assertIn("out += plan_search.value_records(", src)


class NoAttributeNoAppend(unittest.TestCase):
    """Ruling 2026-10-26: a call that names no attribute gets nothing
    appended, and the question text is never read to infer one."""

    def test_without_an_attribute_nothing_is_appended(self):
        ps = _ps()
        for attribute in ("", None, "   "):
            self.assertEqual(ps.value_records(SHED_SHOWN, SHED_REST, "sidewalk shed", attribute), [], repr(attribute))
        self.assertEqual(ps.value_records(BEAM_SHOWN, BEAM_REST, "beam"), [])

    def test_the_question_text_is_not_read(self):
        # A subject that carries the attribute word is still not an attribute
        # slot: "sidewalk shed height" with no attribute appends nothing.
        ps = _ps()
        self.assertEqual(ps.value_records(SHED_SHOWN, SHED_REST, "sidewalk shed height"), [])
        self.assertEqual(len(ps.value_records(SHED_SHOWN, SHED_REST, "sidewalk shed height", "height")), 2)


class TheSharedWordIsTheSubjects(unittest.TestCase):

    def test_a_record_sharing_only_the_attribute_word_is_not_appended(self):
        # Asked the ceiling height: 50'-0" BUILDING & BASE HEIGHT states a
        # value and prints HEIGHT - the attribute, not the subject.
        ps = _ps()
        shown = [_r("A-500.00", "TABLE PARTITION TYPE 1 CEILING ASSEMBLY"), _r("A-302.00", "6 CEILING DETAIL")]
        rest = [_r("A-200.01", "50'-0\" BUILDING & BASE HEIGHT"), _r("A-300.00", "50'-0\" BUILDING & BASE HEIGHT"),
                _r("A-302.00", "CEILING W/ ONE LAYER OF 5/8\" GYP. BD.")]
        got = ps.value_records(shown, rest, "ceiling height", "height")
        self.assertEqual([r["quote"] for r in got], ["CEILING W/ ONE LAYER OF 5/8\" GYP. BD."])

    def test_the_attribute_comes_from_the_slot_in_either_number(self):
        ps = _ps()
        self.assertEqual(ps.subject_words("ceiling heights", "height"), ["ceiling"])
        self.assertEqual(ps.subject_words("insulation type", "type"), ["insulation"])
        # With no slot, every subject word counts: nothing is stripped by a list.
        self.assertEqual(ps.subject_words("ceiling height"), ["ceiling", "height"])

    def test_a_subject_that_is_only_the_attribute_gets_nothing(self):
        ps = _ps()
        self.assertEqual(ps.value_records([], [_r("A-200.01", "50'-0\" BUILDING HEIGHT")], "height", "height"), [])


class WhatStatesAValue(unittest.TestCase):

    def test_values(self):
        ps = _ps()
        for q in ("8' HIGH SHED", "ROOF 2112 SF.", "1HR FIRE RATED", "3.57gpm", "2\"X4\" STUD", "\"0-'7 FINISHED FLOOR"):
            self.assertTrue(ps.states_a_value({"quote": q}), q)
        for q in ("SIDEWALK SHED", "(2) 800S162-54 BOX BEAM", "PTAC-1", "SEE NOTE 4", "A-400.00"):
            self.assertFalse(ps.states_a_value({"quote": q}), q)


if __name__ == "__main__":
    unittest.main()


class TheSearchItself(unittest.TestCase):
    """search_plans over a fake database: the shed records as production
    holds them. Only an attribute call that names its attribute gets the
    ninth and tenth."""

    def _search(self, **kw):
        import asyncio
        from unittest.mock import patch
        import server
        from tests.async_fake_mongo import AsyncFakeDB
        _ps()
        db = AsyncFakeDB()
        for i, r in enumerate(SHED_SHOWN + SHED_REST):
            db[server.PLAN_RECORDS].docs.append(dict(r, project_id="p", page_id=f"pg{i}", ordinal=i,
                                                     label="", subject_terms=[]))

        async def _ids(project_id, **_kw):
            return [f"pg{i}" for i in range(len(SHED_SHOWN + SHED_REST))]

        with patch.object(server, "db", db), patch.object(server, "_current_record_page_ids", _ids):
            return asyncio.run(server.search_plans("p", "sidewalk shed", **kw))

    def test_an_attribute_call_gets_the_ninth_and_tenth(self):
        got = self._search(intent="attribute", attribute="height")
        self.assertEqual(len(got), 10)
        self.assertEqual([r["quote"] for r in got[8:]], ["8' HIGH SHED", "8' HIGH SHED"])

    def test_no_attribute_or_another_intent_gets_nothing_appended(self):
        for kw in ({"intent": "attribute"}, {"intent": "attribute", "attribute": ""},
                   {"intent": "identify", "attribute": "height"}, {"intent": "count", "attribute": "height"}):
            got = self._search(**kw)
            self.assertFalse(any("HIGH SHED" in r["quote"] for r in got[8:]), kw)
            self.assertLessEqual(len([r for r in got if not r.get("tier") == "registered_glyph"]), 8, kw)
