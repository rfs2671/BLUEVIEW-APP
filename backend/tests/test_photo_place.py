"""WHERE A PHOTO WAS TAKEN, WHAT MAY BE SAID ABOUT IT, AND WHAT STAYS OFF.

The owner's rulings: nobody has to identify a photo; never a specific location
without sufficient evidence; floor + trade + general view is not same-place
matching; nothing compares automatically before a benchmark on real photos.

The vision model is stood in for throughout. How often the real one reads a door
tag correctly is NOT asserted here and has not been measured.

CONTROL (2026-11-09): against origin/feat/progress-engine's server.py, lib/ and
tests/test_work_state.py, the wiring classes below fail (see the PR). The pure
modules are new, so they were checked by single mutations, each caught.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

import server  # noqa: E402
from lib import photo_place as P, photo_relations as R, photo_search as S  # noqa: E402
from lib import work_state as W  # noqa: E402

TODAY = date(2026, 11, 9)
F3, F4, F6 = "FLOOR_3", "FLOOR_4", "FLOOR_6"
RANGE = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"]
SPACES = P.spaces_from_plan_rows([
    {"unit": "4A", "sheet_title": "FOURTH FLOOR PLAN", "sheet_number": "A-103.00"},
    {"unit": "4A", "sheet_title": "FOURTH FLOOR MECHANICAL PLAN", "sheet_number": "M-104.00"},
    {"unit": "3B", "sheet_title": "THIRD FLOOR PLAN", "sheet_number": "A-102.00"},
    {"unit": "non-unit:BIKE ROOM", "sheet_title": "CELLAR PLAN", "sheet_number": "A-100.00"},
    {"unit": "2C", "sheet_title": "TYPICAL FLOOR PLAN", "sheet_number": "A-101.00"},
])


def infer(where="", visible=(), **kw):
    return P.infer({"where": where, "visible_text": list(visible), **kw}, SPACES)


def answer(level, who="u1", name="Roy", at="2026-11-09T10:00:00", space=None):
    return {"photo_key": "k", "level": level, "space": space, "by_user_id": who, "by_name": name, "at": at}


class ThePlansTags(unittest.TestCase):

    def test_a_tag_takes_its_level_from_a_sheet_titled_for_one_level(self):
        self.assertEqual(SPACES["4A"]["levels"], [F4])
        self.assertEqual(sorted(SPACES["4A"]["sheets"]), ["A-103.00", "M-104.00"])

    def test_a_typical_or_a_range_sheet_says_nothing_about_a_level(self):
        for title in ("TYPICAL FLOOR PLAN", "SECOND THROUGH FIFTH FLOOR PLAN", "SECOND & THIRD FLOOR PLAN", "FLOORS 2-5 PLAN"):
            with self.subTest(title=title):
                self.assertEqual(P.spaces_from_plan_rows([{"unit": "2C", "sheet_title": title}])["2C"]["levels"], [])

    def test_a_title_that_is_not_a_plan_gives_no_level(self):
        self.assertEqual(P.spaces_from_plan_rows([{"unit": "2C", "sheet_title": "ROOF DRAIN DETAILS"}])["2C"]["levels"], [])

    def test_the_prefix_is_dropped_and_a_refusal_is_not_a_place(self):
        rows = P.spaces_from_plan_rows([{"unit": "non-unit:BIKE ROOM"}, {"unit": "sheet:A-101"},
                                        {"unit": "non-unit:PUBLIC"}, {"unit": None}, {"unit": "A"}, {"unit": "12"}])
        self.assertEqual(list(rows), ["BIKE ROOM"])


class TheSources(unittest.TestCase):

    def test_a_row_naming_one_level_assigns_it(self):
        got = infer("floor 3")
        self.assertEqual((got["level"], got["certainty"], got["candidates"]), (F3, P.INFERRED, [F3]))
        self.assertIn("the log row names Floor 3", P.how(got))

    def test_a_row_naming_one_unit_assigns_it(self):
        got = infer("Apt 4A")
        self.assertEqual((got["level"], got["space"], got["certainty"]), (F4, "4A", P.INFERRED))

    def test_floors_1_to_4_constrains_and_assigns_nothing(self):
        got = infer("floors 1-4")
        self.assertEqual((got["level"], got["space"], got["certainty"], got["candidates"]), (None, None, P.CONSTRAINED, RANGE))
        self.assertEqual(P.levels_of(got), RANGE, "shared between them, as work_state has always had it")

    def test_a_legible_plan_tag_settles_a_shared_row(self):
        got = infer("floors 1-4", ["APT 4A"])
        self.assertEqual((got["level"], got["space"], got["certainty"]), (F4, "4A", P.INFERRED))
        self.assertIn("text read in the photo matches the plan tag 4A", P.how(got))

    def test_a_legible_plan_tag_alone_is_enough(self):
        got = infer("", ["4A"])
        self.assertEqual((got["level"], got["space"], got["certainty"]), (F4, "4A", P.INFERRED))

    def test_a_tag_on_no_single_level_gives_the_space_and_no_level(self):
        got = infer("", ["2C"])
        self.assertEqual((got["level"], got["space"], got["certainty"]), (None, "2C", P.INFERRED))

    def test_a_floor_marking_within_the_rows_levels_settles_it(self):
        got = infer("floors 1-4", ["FLOOR 3"])
        self.assertEqual((got["level"], got["certainty"]), (F3, P.INFERRED))

    def test_a_floor_marking_with_no_level_on_the_row_is_only_a_hint(self):
        got = infer("", ["FLOOR 3"])
        self.assertEqual((got["level"], got["certainty"], got["candidates"]), (None, P.SUGGESTED, [F3]))
        self.assertEqual(P.levels_of(got), [])

    def test_a_level_in_the_work_description_is_only_a_hint(self):
        got = P.infer({"where": "", "work": "3rd floor framing"}, SPACES)
        self.assertEqual((got["level"], got["certainty"], P.levels_of(got)), (None, P.SUGGESTED, []))

    def test_nothing_on_record_is_unknown(self):
        got = infer("")
        self.assertEqual((got["level"], got["certainty"], got["candidates"], got["evidence"]), (None, P.UNKNOWN, [], []))

    def test_a_named_room_on_the_plans(self):
        got = infer("bike room")
        self.assertEqual((got["level"], got["space"]), ("CELLAR", "BIKE ROOM"))

    def test_a_row_naming_two_units_assigns_neither(self):
        got = infer("Apt 3B and 3C")
        self.assertEqual(got["space"], None)

    def test_a_tag_the_plans_do_not_have_proves_nothing(self):
        got = infer("floors 1-4", ["7Z"])
        self.assertEqual((got["level"], got["certainty"]), (None, P.CONSTRAINED))

    def test_room_type_is_carried_and_assigns_nothing(self):
        got = P.infer({"where": "floors 1-4", "room_type": "bathroom"}, SPACES)
        self.assertEqual((got["level"], got["room_type"]), (None, "bathroom"))
        self.assertIsNone(P.infer({"room_type": "unknown"}, SPACES)["room_type"])


class WholeTextOnly(unittest.TestCase):
    """Word-boundary at the least, and here the whole item."""

    def test_a_longer_token_is_not_the_tag(self):
        for read in ("14A", "4AB", "4A1"):
            with self.subTest(read=read):
                self.assertEqual(infer("floors 1-4", [read])["certainty"], P.CONSTRAINED)

    def test_spellings_of_one_tag(self):
        for read in ("4A", "4-A", "4 a", "APT 4A", "Apt. 4A", "UNIT 4A", "Door 4A"):
            with self.subTest(read=read):
                self.assertEqual(infer("", [read])["space"], "4A")

    def test_a_sign_about_somewhere_else_is_no_marking(self):
        for read in ("5TH FLOOR EXIT THIS WAY", "ROOF DRAIN", "L3", "3", "FL-2", "FIRST AID"):
            with self.subTest(read=read):
                self.assertEqual(infer("floors 1-4", [read])["certainty"], P.CONSTRAINED)

    def test_the_markings_it_does_read(self):
        for read, want in (("FLOOR 3", F3), ("3RD FLOOR", F3), ("3 FL", F3), ("FL 3", F3), ("FLR. 3", F3), ("LEVEL 3", F3),
                           ("third floor", F3), ("Floor-3", F3)):
            with self.subTest(read=read):
                self.assertEqual(infer("floors 1-4", [read])["level"], want)
        self.assertEqual(infer("roof, floors 1-4", ["ROOF"])["level"], "ROOF")

    def test_a_short_room_name_is_not_found_inside_a_word(self):
        spaces = P.spaces_from_plan_rows([{"unit": "non-unit:GYM", "sheet_title": "CELLAR PLAN"},
                                          {"unit": "non-unit:LOBBY", "sheet_title": "CELLAR PLAN"}])
        self.assertIsNone(P.infer({"where": "gymnasium floor"}, spaces)["space"])
        self.assertEqual(P.infer({"where": "main lobby"}, spaces)["space"], "LOBBY")


class Conflicts(unittest.TestCase):

    def _none(self, got):
        self.assertEqual((got["level"], got["space"], got["certainty"]), (None, None, P.CONFLICT))
        self.assertIn("the evidence disagrees", P.how(got))

    def test_a_marking_outside_the_rows_levels(self):
        self._none(infer("floors 1-4", ["FLOOR 6"]))

    def test_a_marking_against_a_single_level_row(self):
        self._none(infer("floor 3", ["FLOOR 4"]))

    def test_a_plan_tag_against_a_single_level_row(self):
        self._none(infer("floor 3", ["4A"]))

    def test_a_plan_tag_outside_a_shared_row(self):
        spaces = P.spaces_from_plan_rows([{"unit": "9A", "sheet_title": "NINTH FLOOR PLAN"}])
        self._none(P.infer({"where": "floors 1-4", "visible_text": ["9A"]}, spaces))

    def test_a_tag_and_a_marking_that_disagree(self):
        self._none(infer("floors 1-4", ["4A", "FLOOR 3"]))

    def test_two_markings(self):
        self._none(infer("", ["FLOOR 3", "FLOOR 4"]))

    def test_a_loose_marking_against_a_tag(self):
        self._none(infer("", ["4A", "FLOOR 3"]))

    def test_the_rows_unit_against_a_tag_in_the_photo(self):
        self._none(P.infer({"where": "Apt 3B", "visible_text": ["5F"]},
                           {**SPACES, **P.spaces_from_plan_rows([{"unit": "5F", "sheet_title": "THIRD FLOOR PLAN"}])}))

    def test_a_tag_on_no_level_against_the_rows_unit(self):
        self._none(P.infer({"where": "Apt 3B", "visible_text": ["2C"]}, SPACES))

    def test_two_tags_on_one_floor_settle_the_level_and_no_space(self):
        spaces = P.spaces_from_plan_rows([{"unit": "4A", "sheet_title": "FOURTH FLOOR PLAN"},
                                          {"unit": "4B", "sheet_title": "FOURTH FLOOR PLAN"}])
        got = P.infer({"where": "floors 1-4", "visible_text": ["4A", "4B"]}, spaces)
        self.assertEqual((got["level"], got["space"], got["certainty"]), (F4, None, P.INFERRED))

    def test_a_contradicted_single_level_is_not_kept_as_the_rows_level(self):
        self.assertNotEqual(P.levels_of(infer("floor 3", ["FLOOR 4"])), [F3])


class TheAnswerOfAPerson(unittest.TestCase):

    def test_it_is_the_strongest_evidence(self):
        got = P.infer({"where": "floor 3", "visible_text": ["FLOOR 4"]}, SPACES, confirmations=[answer(F6)])
        self.assertEqual((got["level"], got["certainty"]), (F6, P.CONFIRMED))
        self.assertIn("confirmed by Roy", P.how(got))
        self.assertEqual(got["evidence"][0]["by"], "Roy")

    def test_a_person_may_correct_himself(self):
        got = P.infer({}, SPACES, confirmations=[answer(F4, at="2026-11-10T09:00:00"), answer(F3, at="2026-11-09T09:00:00")])
        self.assertEqual(got["level"], F4)

    def test_two_people_who_disagree_assign_nothing(self):
        got = P.infer({}, SPACES, confirmations=[answer(F3), answer(F4, who="u2", name="Mike")])
        self.assertEqual((got["level"], got["certainty"], got["candidates"]), (None, P.CONFLICT, [F3, F4]))


class ALentPlaceIsOff(unittest.TestCase):
    LENT = {"level": F3, "space": None, "inliers": 999}

    def test_disabled_until_a_benchmark_sets_a_threshold(self):
        self.assertIsNone(P.LEND_MIN_INLIERS)
        self.assertEqual(P.infer({"where": "floors 1-4"}, SPACES, lent=self.LENT)["level"], None)

    def test_with_a_threshold_it_must_be_cleared_and_fit_the_row(self):
        with patch.object(P, "LEND_MIN_INLIERS", 100):
            self.assertEqual(P.infer({"where": "floors 1-4"}, SPACES, lent=self.LENT)["certainty"], P.LENT)
            self.assertEqual(P.infer({"where": "floors 1-4"}, SPACES, lent={**self.LENT, "inliers": 99})["level"], None)
            self.assertEqual(P.infer({"where": "floors 5-6"}, SPACES, lent=self.LENT)["level"], None)


class TheSecondRead(unittest.TestCase):

    def _rows(self):
        return [{"_id": "shared", "where": "floors 1-4", "date": "2026-11-01"},
                {"_id": "none", "where": "Site", "date": "2026-11-03"},
                {"_id": "one", "where": "floor 3", "date": "2026-11-05"},
                {"_id": "tried", "where": "", "date": "2026-11-06", "reread_tries": 3}]

    def test_only_rows_naming_several_levels_or_none_newest_first(self):
        self.assertEqual([r["_id"] for r in P.reread_targets(self._rows(), 10, 3)], ["none", "shared"])

    def test_the_budget_holds(self):
        self.assertEqual(len(P.reread_targets(self._rows(), 1, 3)), 1)
        self.assertEqual(P.reread_targets(self._rows(), 0, 3), [])


class TheIndexPrompt(unittest.TestCase):

    def test_v2_asks_for_legible_text_and_never_a_guess(self):
        for piece in ('\\"visible_text\\"', "visible_text: ONLY place markings you can actually read", "never guess"):
            self.assertIn(piece.replace("\\", ""), S.INDEX_PROMPT)
        self.assertEqual(S.PROMPT_V, 2)

    def test_the_new_fields_are_parsed(self):
        v = S.parse_index('{"view":"interior","quality":5,"description":"x","tags":[],'
                          '"visible_text":[" APT 4A ","", 7],"room_type":"Bathroom"}')
        self.assertEqual((v["visible_text"], v["room_type"]), (["APT 4A", "7"], "bathroom"))

    def test_a_room_outside_the_list_is_unknown_and_text_is_capped(self):
        v = S.parse_index('{"view":"interior","description":"x","room_type":"throne room","visible_text":"nope"}')
        self.assertEqual((v["room_type"], v["visible_text"]), ("unknown", []))
        v = S.parse_index('{"view":"interior","description":"x","visible_text":' + str([f"t{i}" for i in range(20)]).replace("'", '"') + "}")
        self.assertEqual(len(v["visible_text"]), 8)


def _key(i):
    return f"k/{i}.jpg"


def _idx(key, where="floor 3", day="2026-11-05", view="interior", project=THOMAS, **kw):
    return {"_id": f"v1:{key}", "kind": "photo", "photo_key": key, "short": S.short_id(key), "where": where, "work": "Drywall",
            "date": day, "view": view, "quality": 8.0, "description": "Board on studs.", "tags": [], "sub": "Arkon",
            "log_id": "L1", "project_id": project, "company_id": CO_A, **kw}


class TheSweep(_Brain):

    def _tick(self, said=None, **kw):
        calls = []

        async def vision(raw, project):
            calls.append(raw)
            return said if said is not None else {"view": "interior", "quality": 1.0, "description": "OTHER", "tags": [],
                                                  "visible_text": ["APT 4A"], "room_type": "kitchen"}

        async def bytes_of(row):
            return b"x"
        with patch.object(server, "QWEN_API_KEY", "x"), patch.object(server, "_photo_index_call", vision), \
                patch.object(server, "_photo_log_bytes", bytes_of):
            return _run(server._photo_index_tick(**kw)), calls

    def _rows(self):
        return {r["photo_key"]: r for r in self.db[server.PHOTO_INDEX].rows if r.get("kind") == "photo"}

    def test_a_new_photo_gets_v2_directly(self):
        self.db.logbooks.rows.append({"_id": "L1", "log_type": "daily_jobsite", "project_id": THOMAS, "company_id": CO_A, "status": "submitted",
                                      "date": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
                                      "data": {"activities": [{"company": "A", "work_locations": "floors 1-4",
                                                               "photos": [{"enhanced_r2_key": "k/new.jpg"}]}]}})

        async def vision(raw, project):
            return {"view": "interior", "quality": 5.0, "description": "d", "tags": [], "visible_text": ["4A"], "room_type": "kitchen"}
        with _Ctx(db=self.db), patch.object(server, "QWEN_API_KEY", "x"), patch.object(server, "_photo_index_call", vision), \
                patch.object(server, "_report_photo_bytes", lambda c: b"x"):
            _run(server._photo_index_tick())
        row = self._rows()["k/new.jpg"]
        self.assertEqual((row["prompt_v"], row["visible_text"], row["room_type"]), (S.PROMPT_V, ["4A"], "kitchen"))

    def test_only_the_rows_that_need_it_and_only_the_new_fields(self):
        self.db[server.PHOTO_INDEX].rows += [_idx(_key(1), where="floors 1-4"), _idx(_key(2), where="floor 3"),
                                             _idx(_key(3), where="Site", prompt_v=S.PROMPT_V)]
        with _Ctx(db=self.db):
            out, calls = self._tick()
        self.assertEqual((len(calls), out["reread"]), (1, 1))
        rows = self._rows()
        self.assertEqual((rows[_key(1)]["prompt_v"], rows[_key(1)]["visible_text"]), (S.PROMPT_V, ["APT 4A"]))
        self.assertEqual(rows[_key(1)]["description"], "Board on studs.", "what a search finds does not move")
        self.assertEqual(rows[_key(1)]["quality"], 8.0)
        self.assertNotIn("prompt_v", rows[_key(2)])

    def test_it_stays_inside_what_the_tick_has_left(self):
        self.db[server.PHOTO_INDEX].rows += [_idx(_key(i), where="floors 1-4") for i in range(5)]
        with _Ctx(db=self.db):
            _o, calls = self._tick(budget=2)
        self.assertEqual(len(calls), 2)

    def test_a_row_the_model_will_not_answer_is_given_up_on(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), where="floors 1-4"))

        async def vision(raw, project):
            calls.append(1)

        async def bytes_of(row):
            return b"x"
        calls = []
        with _Ctx(db=self.db), patch.object(server, "QWEN_API_KEY", "x"), patch.object(server, "_photo_index_call", vision), \
                patch.object(server, "_photo_log_bytes", bytes_of):
            for _ in range(server.PHOTO_INDEX_TRIES + 2):
                _run(server._photo_index_tick())
        self.assertEqual(len(calls), server.PHOTO_INDEX_TRIES)


def _act(work, where, day, company="Arkon", trade="Carpenter"):
    return {"date": day, "company": company, "trade": trade, "work": work, "where": where, "log_id": "L", "amended": False}


class WorkStateUsesIt(unittest.TestCase):

    def _row(self, where, visible=(), **kw):
        return {"short": "s", "photo_key": "k", "where": where, "work": "Drywall", "date": "2026-11-05", "view": "interior",
                "quality": 8.0, "description": "Board.", "tags": [], "sub": "Arkon", "log_id": "L", "project_id": "p",
                "visible_text": list(visible), **kw}

    def test_the_inferred_level_when_it_is_sufficient(self):
        got = W.photo_rows([self._row("floors 1-4", ["4A"])], spaces=SPACES)[0]
        self.assertEqual((got["levels"], got["space"]), ([F4], "4A"))
        self.assertIn("matches the plan tag", got["how_placed"])

    def test_the_shared_levels_when_it_is_not(self):
        self.assertEqual(W.photo_rows([self._row("floors 1-4")], spaces=SPACES)[0]["levels"], RANGE)

    def test_a_conflict_leaves_no_single_level(self):
        got = W.photo_rows([self._row("floor 3", ["FLOOR 4"])], spaces=SPACES)[0]
        self.assertNotEqual(got["levels"], [F3])

    def test_a_confirmation_reaches_it(self):
        got = W.photo_rows([self._row("floors 1-4")], spaces=SPACES, confirmations={"k": [answer(F6)]})[0]
        self.assertEqual(got["levels"], [F6])

    def test_the_answer_says_how(self):
        ans = W.what_holds("drywall", F4, [], [self._row("floors 1-4", ["4A"])], today=TODAY, spaces=SPACES)
        self.assertIn("(placed: text read in the photo matches the plan tag 4A", W.as_text(ans))

    def test_a_shared_photo_is_still_filed_for_several(self):
        ans = W.what_holds("drywall", F3, [], [self._row("floors 1-4")], today=TODAY, spaces=SPACES)
        out = W.as_text(ans)
        self.assertIn("(filed for several floors)", out)
        self.assertNotIn("(placed:", out)


class TheLevelHistory(unittest.TestCase):
    D1, D2, D3 = date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)

    def _h(self, acts, photos=()):
        return W.level_history(W.evidence_rows(acts), W.photo_rows(photos))

    def test_first_and_last_per_level_and_kind_of_work(self):
        h = self._h([_act("Framing", "floor 3", self.D1), _act("Framing", "floor 3", self.D2), _act("Drywall", "floor 3", self.D3)])
        slot = h["levels"][F3]
        self.assertEqual((slot["work"]["framing"]["first"], slot["work"]["framing"]["last"], slot["work"]["framing"]["days"]),
                         (self.D1, self.D2, 2))
        self.assertEqual(slot["stages"], ["framing", "drywall"])
        self.assertEqual(h["out_of_order"], [])

    def test_work_before_its_usual_prerequisite_is_a_fact(self):
        h = self._h([_act("Drywall", "floor 3", self.D1), _act("Framing", "floor 3", self.D2)])
        self.assertEqual([(f["node"], f["prerequisite"], f["first"], f["prerequisite_first"]) for f in h["out_of_order"]],
                         [("drywall", "framing", self.D1, self.D2)])

    def test_a_prerequisite_with_no_report_is_not_compared(self):
        self.assertEqual(self._h([_act("Drywall", "floor 3", self.D1)])["out_of_order"], [])

    def test_one_level_is_not_compared_with_another(self):
        h = self._h([_act("Drywall", "floor 3", self.D1), _act("Framing", "floor 4", self.D2)])
        self.assertEqual(h["out_of_order"], [])

    def test_the_same_day_is_not_out_of_order(self):
        self.assertEqual(self._h([_act("Drywall", "floor 3", self.D1), _act("Framing", "floor 3", self.D1)])["out_of_order"], [])

    def test_a_shared_report_is_marked_so(self):
        h = self._h([_act("Drywall", "floor 3", self.D1), _act("Framing", "floors 1-4", self.D2)])
        self.assertTrue(next(f for f in h["out_of_order"] if f["level"] == F3)["shared"])

    def test_the_photos_are_in_date_order(self):
        pics = [{"short": k, "photo_key": k, "where": "floor 3", "work": "Drywall", "date": d, "view": "interior", "quality": 8.0,
                 "description": "x", "tags": [], "log_id": "L"} for k, d in (("b", "2026-05-01"), ("a", "2026-03-01"))]
        h = self._h([_act("Drywall", "floor 3", self.D1)], pics)
        self.assertEqual([p["id"] for p in h["levels"][F3]["work"]["drywall"]["photos"]], ["a", "b"])

    def test_the_assistant_is_told_it_is_only_about_dates(self):
        ans = W.what_holds("drywall", F3, [_act("Drywall", "floor 3", self.D1), _act("Framing", "floor 3", self.D2)], [], today=TODAY)
        out = W.as_text(ans)
        self.assertIn("this does not say anything was done wrong", out)
        self.assertIn("drywall first reported Mar 1, before the first report of framing on Apr 1", out)


class ThePairs(unittest.TestCase):

    def _rows(self, *pics):
        return W.photo_rows(list(pics), spaces=SPACES)

    def _pic(self, key, where="floor 3", day="2026-11-05", visible=(), room="unknown", view="interior"):
        return {"short": key, "photo_key": key, "where": where, "work": "Drywall", "date": day, "view": view, "quality": 8.0,
                "description": "x", "tags": [], "sub": "A", "log_id": "L", "project_id": "p", "visible_text": list(visible), "room_type": room}

    def test_nothing_is_picked_until_a_threshold_exists(self):
        self.assertIsNone(R.GEOMETRY_MIN_INLIERS)
        self.assertEqual(R.pick_pairs(self._rows(self._pic("a", day="2026-10-01"), self._pic("b")), [], 10), [])

    def test_a_photo_with_a_stale_levels_field_but_no_sufficient_place_is_not_used(self):
        """The place decides, not the row's levels."""
        rows = self._rows(self._pic("a", where="floors 1-4", visible=["FLOOR 6"], day="2026-10-01"), self._pic("b"))
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 10):
            self.assertEqual(R.pick_pairs(rows, [], 10), [])

    def test_the_inferred_place_groups_them(self):
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 10):
            got = R.pick_pairs(self._rows(self._pic("a", where="floors 1-4", visible=["FLOOR 3"], day="2026-10-01"), self._pic("b")), [], 10)
        self.assertEqual(len(got), 1)

    def test_a_photo_with_no_place_is_never_a_candidate(self):
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 10):
            self.assertEqual(R.pick_pairs(self._rows(self._pic("a", where="floors 1-4", day="2026-10-01"), self._pic("b", where="floors 1-4")), [], 10), [])

    def test_two_spaces_are_two_places(self):
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 10):
            got = R.pick_pairs(self._rows(self._pic("a", where="floor 3 apt 3B", day="2026-10-01"),
                                          self._pic("b", where="floor 3 apt 3C")), [], 10)
        self.assertEqual(got, [])

    def test_two_kinds_of_room_are_not_compared(self):
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 10):
            self.assertEqual(R.pick_pairs(self._rows(self._pic("a", day="2026-10-01", room="bathroom"), self._pic("b", room="kitchen")), [], 10), [])
            self.assertEqual(len(R.pick_pairs(self._rows(self._pic("a", day="2026-10-01", room="bathroom"), self._pic("b")), [], 10)), 1)

    def test_geometry_agreement_needs_a_threshold_and_a_measurement(self):
        ok = {"ok": True, "inliers": 500, "ratio": 0.9}
        self.assertFalse(R.geometry_agrees(ok))
        with patch.object(R, "GEOMETRY_MIN_INLIERS", 50), patch.object(R, "GEOMETRY_MIN_RATIO", 0.5):
            self.assertTrue(R.geometry_agrees(ok))
            self.assertFalse(R.geometry_agrees({**ok, "inliers": 49}))
            self.assertFalse(R.geometry_agrees({**ok, "ratio": 0.4}))
            self.assertFalse(R.geometry_agrees({**ok, "ok": False}))
            self.assertFalse(R.geometry_agrees(None))


class TheComparisonSweep(_Brain):

    def _seed(self):
        self.db[server.PHOTO_INDEX].rows += [_idx("k/a.jpg", day="2026-10-01"), _idx("k/b.jpg", day="2026-11-05")]

    def _tick(self, calls, inliers, threshold):
        async def compare(a, b, pid):
            calls.append(pid)
            return {"same_area": "yes", "confidence": 0.9, "changes": [], "installed": [], "possible_rework": []}

        async def raw(row):
            return b"x"
        geometry = lambda a, b: {"ok": True, "reason": "", "inliers": inliers, "ratio": 0.5}  # noqa: E731
        with patch.dict("os.environ", {"PHOTO_RELATIONS_ENABLED": "1"}), patch.object(server, "QWEN_API_KEY", "x"), \
                patch.object(server, "_photo_compare_call", compare), patch.object(server, "_photo_log_bytes", raw), \
                patch.object(server.photo_geometry, "match", geometry), patch.object(R, "GEOMETRY_MIN_INLIERS", threshold):
            return _run(server._photo_relations_tick())

    def test_the_switch_alone_starts_nothing(self):
        self._seed()
        calls = []
        with _Ctx(db=self.db):
            out = self._tick(calls, 500, None)
        self.assertEqual((calls, out["pairs"], self.db[server.PHOTO_RELATIONS].rows), ([], 0, []))

    def test_geometry_that_does_not_agree_costs_no_vision_call_and_is_not_retried(self):
        self._seed()
        calls = []
        with _Ctx(db=self.db):
            first = self._tick(calls, 3, 50)
            second = self._tick(calls, 3, 50)
        self.assertEqual((calls, first["geometry_rejected"], second["geometry_rejected"]), ([], 1, 0))
        self.assertEqual(self.db[server.PHOTO_RELATIONS].rows[0]["same_area"], "not_asked")

    def test_a_rejected_pair_never_reaches_the_answer(self):
        self._seed()
        with _Ctx(db=self.db):
            self._tick([], 3, 50)
        self.assertEqual(self.db[server.PHOTO_RELATIONS].rows[0]["same_area"], "not_asked")
        self.assertNotEqual(self.db[server.PHOTO_RELATIONS].rows[0].get("confidence"), 0.9)

    def test_geometry_that_agrees_is_asked_once_and_kept_with_its_numbers(self):
        self._seed()
        calls = []
        with _Ctx(db=self.db):
            self._tick(calls, 80, 50)
            self._tick(calls, 80, 50)
        self.assertEqual(calls, [THOMAS])
        row = self.db[server.PHOTO_RELATIONS].rows[0]
        self.assertEqual((row["same_area"], row["level"], row["geometry"]["inliers"]), ("yes", F3, 80))


class ThePlaceContext(_Brain):

    def test_it_reads_the_jobs_tags_and_answers_only(self):
        self.db.plan_records.rows += [{"project_id": THOMAS, "unit": "4A", "sheet_title": "FOURTH FLOOR PLAN"},
                                      {"project_id": WALWORTH, "unit": "9Z", "sheet_title": "NINTH FLOOR PLAN"}, {"project_id": THOMAS, "unit": None}]
        self.db.plan_areas.rows.append({"project_id": THOMAS, "unit": "3B", "sheet_title": "THIRD FLOOR PLAN"})
        self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows += [answer(F3) | {"project_id": THOMAS}, answer(F4) | {"project_id": WALWORTH, "photo_key": "other"}]
        with _Ctx(db=self.db):
            spaces, confirmed = _run(server._photo_place_context(THOMAS))
        self.assertEqual(sorted(spaces), ["3B", "4A"])
        self.assertEqual(list(confirmed), ["k"])


class TheApi(_Brain):

    def _call(self, level="floor 6", photo=None, space=None):
        body = server.PhotoPlaceConfirmation(photo=photo or S.short_id(_key(1)), level=level, space=space)
        return _run(server.confirm_photo_place(THOMAS, body, current_user={"id": "u9", "name": "Roy"}))

    def test_an_answer_is_appended_with_who_and_when(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1)))
        with _Ctx(db=self.db):
            self._call()
            self._call(level="FLOOR_4")
        rows = self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows
        self.assertEqual([r["level"] for r in rows], [F6, F4], "append-only: both rows stand")
        self.assertEqual((rows[0]["by_user_id"], rows[0]["by_name"], rows[0]["via"], rows[0]["photo_key"]), ("u9", "Roy", "api", _key(1)))
        self.assertIsInstance(rows[0]["at"], datetime)

    def test_it_feeds_infer(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), where="floors 1-4"))
        with _Ctx(db=self.db):
            self._call(level="6")
            _s, confirmed = _run(server._photo_place_context(THOMAS))
        self.assertEqual(P.infer(self.db[server.PHOTO_INDEX].rows[0], {}, confirmations=confirmed[_key(1)])["level"], F6)

    def test_a_vague_level_is_refused(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1)))
        with _Ctx(db=self.db), self.assertRaises(server.HTTPException) as cm:
            self._call(level="somewhere upstairs")
        self.assertEqual(cm.exception.status_code, 422)

    def test_another_jobs_photo_is_not_found(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), project=WALWORTH))
        with _Ctx(db=self.db), self.assertRaises(server.HTTPException) as cm:
            self._call()
        self.assertEqual(cm.exception.status_code, 404)

    def test_the_route_is_scoped_and_append_only(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        decl = src[src.index('@api_router.post("/projects/{project_id}/photo-place-confirmations"'):]
        self.assertIn("Depends(require_project_access)", decl[:200])
        body = src[src.index("async def _photo_place_record("):src.index("class PhotoPlaceConfirmation(")]
        self.assertIn("insert_one(doc)", body)
        self.assertNotIn("update_one(", body)


JPG = b"\xff\xd8\xff\xd9"


class TheWhatsAppPrompt(_Brain):
    """The caption line, and a reply naming a floor. Nothing else."""
    MEDIA = "mediaUrl"

    def setUp(self):
        super().setUp()
        self.db.logbooks.rows.append({
            "_id": "L1", "log_type": "daily_jobsite", "project_id": THOMAS, "company_id": CO_A, "status": "submitted",
            "date": "2026-11-05", "data": {"activities": [{"company": "Arkon", "work_locations": "floors 1-4",
                                                           "photos": [{"enhanced_r2_key": _key(1)}, {"enhanced_r2_key": _key(2)}]}]}})

    def _send(self, c, shorts, body="send it"):
        def done(kw):
            self.result = last_tool_results(kw)[0]
            return resp(text("Sent."))
        llm = FakeLLM(resp(use("send_photos", {"job": "588", "ids": shorts}, "a")), done)

        async def url(chat, jpeg, ref):
            return "https://media.test/p.jpg"
        with patch.object(server, "_temp_jpeg_media_url", url), patch.object(server, "_report_photo_bytes", lambda c: b"x"), \
                patch.object(server, "_photo_send_jpeg", lambda raw: JPG):
            self.say(c, body, llm)

    def _reply(self, c, body):
        def done(kw):
            self.result = last_tool_results(kw)[0]
            return resp(text("Thanks."))
        llm = FakeLLM(resp(use("confirm_photo_place", {"job": "588"}, "b")), done)
        self.say(c, body, llm)

    def _caption(self, c):
        return [p["caption"] for p in c.wire.calls if self.MEDIA in p]

    def _one(self, **kw):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), where="floors 1-4", **kw))

    def test_a_photo_with_no_floor_says_so_once_and_a_floor_is_recorded(self):
        self._one()
        short = S.short_id(_key(1))
        with _Ctx(db=self.db) as c:
            self._send(c, [short])
            self.assertIn(server.PHOTO_PLACE_ASK, self._caption(c)[0])
            self.assertIn("confirm_photo_place", self.result)
            self._reply(c, "3rd floor")
        self.assertIn("Recorded: that photo is on Floor 3.", self.result)
        row = self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows[0]
        self.assertEqual((row["photo_key"], row["level"], row["via"]), (_key(1), F3, "whatsapp"))

    def test_the_floor_comes_from_their_message_not_the_model(self):
        self._one()
        with _Ctx(db=self.db) as c:
            self._send(c, [S.short_id(_key(1))])
            self._reply(c, "looks good thanks")
        self.assertIn("doesn't name one floor", self.result)
        self.assertEqual(self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows, [])

    def test_no_ask_means_nothing_is_recorded(self):
        self._one()
        with _Ctx(db=self.db) as c:
            self._reply(c, "3rd floor")
        self.assertIn("No photo is waiting", self.result)
        self.assertEqual(self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows, [])

    def test_an_old_ask_has_lapsed(self):
        self._one()
        short = S.short_id(_key(1))
        with _Ctx(db=self.db) as c:
            self._send(c, [short])
            for row in self.db.whatsapp_messages.rows:
                if row.get("photo_place_asked"):
                    row["created_at"] = datetime.now(timezone.utc) - timedelta(minutes=server.PHOTO_PLACE_ASK_MINUTES + 1)
            self._reply(c, "3rd floor")
        self.assertEqual(self.db[server.PHOTO_PLACE_CONFIRMATIONS].rows, [])

    def test_a_photo_with_a_floor_is_not_asked_about(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), where="floor 3"))
        with _Ctx(db=self.db) as c:
            self._send(c, [S.short_id(_key(1))])
            self.assertNotIn(server.PHOTO_PLACE_ASK, self._caption(c)[0])

    def test_two_uncertain_photos_ask_nothing_because_a_floor_would_be_about_neither(self):
        self.db[server.PHOTO_INDEX].rows += [_idx(_key(1), where="floors 1-4"), _idx(_key(2), where="floors 1-4")]
        with _Ctx(db=self.db) as c:
            self._send(c, [S.short_id(_key(1)), S.short_id(_key(2))])
            self.assertEqual(len(self._caption(c)), 2)
            self.assertFalse(any(server.PHOTO_PLACE_ASK in x for x in self._caption(c)))

    def test_the_front_of_a_building_has_no_floor_to_ask_about(self):
        self.db[server.PHOTO_INDEX].rows.append(_idx(_key(1), where="", view="building_front"))
        with _Ctx(db=self.db) as c:
            self._send(c, [S.short_id(_key(1))])
            self.assertNotIn(server.PHOTO_PLACE_ASK, self._caption(c)[0])

    def test_a_person_can_only_answer_for_their_own_company(self):
        self._one()
        out = None
        with _Ctx(db=self.db):
            ctx = {"ident": {"company_id": "c0ffee000000000000000099"}, "dm_chat": "c", "text": "3"}
            out = asyncio.run(server._dm_confirm_photo_place(ctx, {"id": THOMAS, "label": "588"}, {}))
        self.assertEqual(out, server.wa_security.BOT_SCOPE_REFUSAL)

    def test_it_reaches_the_model(self):
        names = {t["function"]["name"] for t in server._dm_brain_tools()}
        self.assertIn("confirm_photo_place", names)
        from lib import dm_brain
        self.assertIn("Never ask for a floor on your own", dm_brain.SYSTEM_PROMPT.replace("\\\n", ""))


if __name__ == "__main__":
    unittest.main()
