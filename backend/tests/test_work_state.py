"""WHAT'S HOLDING UP DRYWALL ON FLOOR 3? WHAT THE RECORDS SAY, AND WHAT THEY DON'T.

The phrases and locations here are real: they are the lines of the Oct 27 - Nov 9
2026 progress report for 588 Thomas S Boyland St. The vision model is stood in
for; how well the real one tells one place from another is not asserted, and
cannot be until scripts/work_state_probe.py has been run against production.

CONTROL: against origin/main's server.py, lib/dm_brain.py and lib/vision_meter.py
7 tests fail: the tool, the sweep and the meter. The tests of the two new pure
modules cannot fail on main (the files exist on both sides), so those were
checked by 9 single mutations of the modules, each caught (2026-11-09).

Pairs need a place (lib/photo_place) and a benchmarked geometry threshold
(photo_relations.GEOMETRY_MIN_INLIERS) that does not exist yet: the tests of the
selection stand one in, here, and only here. See tests/test_photo_place.py.
"""

from __future__ import annotations

import asyncio
import json
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
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

import server  # noqa: E402
from lib import photo_relations as R, vision_meter  # noqa: E402
from lib import work_state as W  # noqa: E402

TODAY = date(2026, 11, 9)
F1_4 = "floors 1-4"


def _act(work, where=F1_4, day=TODAY - timedelta(days=4), company="Quality Plumbing", trade="Plumber", log="L1"):
    return {"date": day, "company": company, "trade": trade, "work": work, "where": where, "log_id": log, "amended": False}


def _pic(key, where="floor 3", work="Domestic water rough", day="2026-11-05", view="interior", quality=8.0,
         description="Copper water piping along open studs.", sub="Quality Plumbing", log="L1"):
    return {"short": key[:8], "photo_key": key, "where": where, "work": work, "date": day, "view": view,
            "quality": quality, "description": description, "tags": [], "sub": sub, "log_id": log,
            "project_id": "p", "kind": "photo"}


def _holds(acts=(), pics=(), **kw):
    return W.what_holds("drywall", "FLOOR_3", list(acts), list(pics), today=TODAY, **kw)


class Places(unittest.TestCase):

    def test_the_real_location_strings(self):
        for raw, levels, space in (("floors 1-4", ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"], None),
                                   ("Roof", ["ROOF"], None), ("3B", ["FLOOR_3"], "3B"), ("cellar", ["CELLAR"], None),
                                   ("sub cellar", ["SUB_CELLAR"], None), ("3rd floor", ["FLOOR_3"], None)):
            with self.subTest(raw=raw):
                self.assertEqual(W.places_in(raw), {"levels": sorted(levels), "space": space})

    def test_an_unknown_place_is_never_guessed(self):
        self.assertEqual(W.places_in("outer bldg"), {"levels": [], "space": None})

    def test_what_a_person_says_is_one_level(self):
        self.assertEqual([W.level_asked(x) for x in ("3", "floor 3", "3rd", "Roof")],
                         ["FLOOR_3", "FLOOR_3", "FLOOR_3", "ROOF"])
        self.assertIsNone(W.level_asked("floors 1-4"), "that is not one level")


class TheKindOfWork(unittest.TestCase):

    def test_the_real_588_phrases(self):
        for phrase, crew, want in (("Blocking", "Arkon Framers", ["framing"]),
                                   ("Interior framing", "Arkon Framers", ["framing"]),
                                   ("Door bucks", "Arkon", ["framing"]),
                                   ("Ceiling drops", "Arkon", ["ceiling_drop"]),
                                   ("Domestic water rough", "Plumber", ["rough_water"]),
                                   ("Ductwork rough", "BreezCo HVAC", ["rough_duct"]),
                                   ("Electrical wiring", "Power Direct", ["rough_electric"]),
                                   ("Pull wire", "Power Direct", ["rough_electric"]),
                                   ("Trim out", "Quality Plumber", ["mep_trim"]),
                                   ("Vapour barrier", "Slate Windows", ["insulation"]),
                                   ("Spray foam", "A1", ["insulation"])):
            with self.subTest(phrase=phrase):
                self.assertEqual(W.classify(phrase, crew), (want, False))

    def test_a_trade_with_no_part_named_is_generic(self):
        self.assertEqual(W.classify("MEP rough-in"), (list(W.ROUGH_MEP), True))
        self.assertEqual(W.classify("Plumbing"), (["rough_dwv", "rough_water"], True))

    def test_work_outside_the_sequence_is_nothing_not_a_guess(self):
        for phrase in ("Excavation", "Stucco", "Cleaning", "Roofing"):
            with self.subTest(phrase=phrase):
                self.assertEqual(W.classify(phrase), ([], False))

    def test_a_carpenters_trim_is_not_mep_trim(self):
        self.assertEqual(W.classify("Door trim", "Arkon Framers"), ([], False))

    def test_a_phrase_naming_its_own_level_leaves_the_rows_floors(self):
        rows = W.evidence_rows([_act("Ductwork rough, Roof MEP", company="BreezCo", trade="HVAC")])
        self.assertEqual(rows[0]["levels"], ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"])
        self.assertEqual(rows[1]["levels"], ["ROOF"])


class TheStateOfAPackage(unittest.TestCase):

    def _state(self, acts, pics=(), node="rough_water", **kw):
        return W.package_state(node, "FLOOR_3", W.evidence_rows(acts), W.photo_rows(pics), kw.get("schedule"), TODAY)

    def test_nothing_reported_is_unknown_and_says_so(self):
        s = self._state([])
        self.assertEqual(s["status"], "unknown")
        self.assertIn("does not mean it wasn't done", W.state_words(s, TODAY))

    def test_a_row_for_four_floors_is_shared_never_this_floor_alone(self):
        s = self._state([_act("Domestic water rough")])
        self.assertTrue(s["shared_with_other_levels"])
        self.assertIn("several floors together", W.state_words(s, TODAY))

    def test_a_row_for_this_floor_alone_is_not_shared(self):
        self.assertFalse(self._state([_act("Domestic water rough", where="floor 3")])["shared_with_other_levels"])

    def test_old_reports_are_not_called_finished(self):
        s = self._state([_act("Domestic water rough", day=TODAY - timedelta(days=30))])
        self.assertEqual(s["status"], "reported_earlier")
        self.assertIn("not the same as finished", W.state_words(s, TODAY))

    def test_a_photo_observes_and_never_verifies(self):
        s = self._state([], [_pic("k/a.jpg")])
        self.assertTrue(s["observed"])
        self.assertIsNone(s["verified"])
        self.assertEqual(s["status"], "unknown", "a photo is not a report of work")

    def test_no_percent_is_ever_computed(self):
        s = self._state([_act("Domestic water rough", day=TODAY - timedelta(days=d)) for d in range(20)])
        self.assertIsNone(s["percent"])

    def test_a_superseded_original_logs_photo_is_left_out(self):
        rows = W.photo_rows([_pic("k/a.jpg", log="old"), _pic("k/b.jpg", log="head")], log_ids={"head"})
        self.assertEqual([r["log_id"] for r in rows], ["head"])


class Coverage(unittest.TestCase):

    def test_it_counts_what_can_be_used_and_lists_what_cannot(self):
        rows = W.evidence_rows([_act("Domestic water rough"), _act("Plumbing", where="floor 3"), _act("Stucco", where="outer bldg")])
        c = W.coverage(rows, W.photo_rows([_pic("a"), _pic("b", where=F1_4)]))
        self.assertEqual((c["phrases"], c["name_a_level"], c["name_one_level"], c["match_sequence"], c["generic_only"]),
                         (3, 2, 1, 2, 1))
        self.assertEqual(c["not_matched"], [("Stucco", 1)])
        self.assertEqual(c["not_placed"], [("outer bldg", 1)])
        self.assertEqual((c["photos"], c["photos_one_level"]), (2, 1))


class TheQuestion(unittest.TestCase):

    def test_the_gates_before_drywall_are_unknown(self):
        ans = _holds()
        self.assertEqual({g["id"] for g in ans["gates"]},
                         {"gate_plumbing_rough", "gate_sprinkler_hydro", "gate_electrical_rough", "gate_firestopping",
                          "gate_nycecc_insulation"})
        self.assertTrue(all(g["status"] == "unknown" for g in ans["gates"]))

    def test_the_rough_ins_and_framing_come_through_the_gates(self):
        ids = [s["node"] for s in _holds()["work"]]
        for n in ("rough_dwv", "rough_water", "rough_electric", "rough_duct", "rough_sprinkler", "framing"):
            self.assertIn(n, ids)

    def test_a_system_the_building_has_no_record_of_is_conditional(self):
        ans = _holds()
        sprinkler = next(g for g in ans["gates"] if g["id"] == "gate_sprinkler_hydro")
        self.assertEqual(sprinkler["requires_unconfirmed"], ["has_sprinkler"])
        self.assertIn("if the building has this system", W.as_text(ans))

    def test_it_says_what_it_cannot_say(self):
        out = W.as_text(_holds([_act("Domestic water rough")]))
        self.assertIn("neither passed nor failed", out)
        self.assertIn("No confirmed schedule is on file", out)
        self.assertIn("Do not name a cause", out)
        self.assertNotIn("%", out)

    def test_a_confirmed_schedules_dates_are_the_files(self):
        sched = {"activities": [{"id": "A1", "name": "Drywall Floor 3", "kind": "task", "baseline_finish": "2026-12-01",
                                 "current_finish": "2026-12-10", "percent_complete": 20}]}
        out = W.as_text(_holds(schedule=sched))
        self.assertIn("baseline finish 2026-12-01", out)
        self.assertIn("the file states 20%", out)
        self.assertNotIn("No confirmed schedule", out)

    def test_an_open_stop_work_is_said_first_among_records(self):
        self.assertIn("OPEN STOP WORK", W.as_text(_holds(stop_work=[{"number": "SWO-1", "kind": "Stop Work Order"}])))

    def test_records_that_could_not_be_checked_are_not_called_clear(self):
        out = W.as_text(_holds(regulatory_note="DOB feed not checked."))
        self.assertNotIn("No open stop-work", out)
        self.assertIn("DOB feed not checked.", out)

    def test_it_prints_how_much_it_read(self):
        out = W.as_text(_holds([_act("Domestic water rough"), _act("Stucco", where="outer bldg")]))
        self.assertIn("2 log entries, 1 naming this level, 1 naming no level", out)


class ThePairs(unittest.TestCase):

    def setUp(self):
        threshold = patch.object(R, "GEOMETRY_MIN_INLIERS", 10)
        threshold.start()
        self.addCleanup(threshold.stop)

    def _rows(self, *pics):
        return W.photo_rows(pics)

    def test_the_newest_against_the_oldest_and_the_one_before(self):
        rows = self._rows(_pic("a", day="2026-10-01"), _pic("b", day="2026-10-20"), _pic("c", day="2026-11-05"))
        got = R.pick_pairs(rows, [], 10)
        self.assertEqual({(p["first"]["photo_key"], p["second"]["photo_key"]) for p in got}, {("a", "c"), ("b", "c")})

    def test_a_photo_filed_for_several_floors_is_never_a_candidate(self):
        self.assertEqual(R.pick_pairs(self._rows(_pic("a", where=F1_4, day="2026-10-01"), _pic("b", where=F1_4)), [], 10), [])

    def test_two_views_are_not_compared(self):
        self.assertEqual(R.pick_pairs(self._rows(_pic("a", day="2026-10-01", view="roof"), _pic("b")), [], 10), [])

    def test_a_pair_is_asked_once_and_the_budget_holds(self):
        rows = self._rows(_pic("a", day="2026-10-01"), _pic("b", day="2026-10-20"), _pic("c", day="2026-11-05"))
        first = R.pick_pairs(rows, [], 1)
        self.assertEqual(len(first), 1)
        again = R.pick_pairs(rows, [first[0]["pair_id"]], 10)
        self.assertNotIn(first[0]["pair_id"], [p["pair_id"] for p in again])

    def test_a_day_apart_is_not_worth_a_call(self):
        self.assertEqual(R.pick_pairs(self._rows(_pic("a", day="2026-11-04"), _pic("b")), [], 10), [])

    def test_only_a_yes_keeps_what_changed(self):
        no = R.parse_compare('{"same_area":"unsure","confidence":0.4,"changes":["board hung"]}')
        self.assertEqual(no["changes"], [])
        yes = R.parse_compare('x {"same_area":"yes","confidence":0.9,"changes":["board hung"],"installed":["gypsum"]} y')
        self.assertEqual((yes["changes"], yes["installed"]), (["board hung"], ["gypsum"]))

    def test_a_bad_answer_is_not_kept(self):
        for said in ("", "sorry", '{"same_area":"maybe"}'):
            with self.subTest(said=said):
                self.assertIsNone(R.parse_compare(said))

    def test_the_prompt_forbids_inspection_and_percent(self):
        self.assertIn("Never say whether anything passed inspection", R.COMPARE_PROMPT)


def _log(_id, *rows, status="submitted", date_s=None):
    return {"_id": _id, "log_type": "daily_jobsite", "project_id": THOMAS, "company_id": CO_A,
            "date": date_s or (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat(), "status": status,
            "data": {"activities": [dict(r) for r in rows]}}


class ThroughTheAssistant(_Brain):

    def test_the_superintendents_question(self):
        self.db.logbooks.rows.append(_log("L1", {"company": "Quality Plumbing", "trade": "Plumber",
                                                 "work_description": "Domestic water rough", "work_locations": F1_4}))

        def check(kw):
            self.result = last_tool_results(kw)[0]
            return resp(text("Nothing on record says what is holding it: five inspections are unknown."))
        llm = FakeLLM(resp(use("work_status", {"job": "588", "work": "drywall", "level": "3"}, "a")), check)
        with _Ctx(db=self.db) as c:
            self.say(c, "What's holding up drywall on Floor 3?", llm)
        self.assertIn("Drywall on Floor 3: no report on this level", self.result)
        self.assertIn("domestic water rough: reported", self.result)
        self.assertIn("Quality Plumbing", self.result)
        self.assertIn("several floors together", self.result)
        self.assertIn("firestopping special inspection", self.result)
        names = {t["function"]["name"] for t in llm.calls[0]["tools"]}
        self.assertIn("work_status", names)

    def test_a_draft_log_is_not_a_report(self):
        self.db.logbooks.rows.append(_log("L1", {"company": "Quality Plumbing", "trade": "Plumber",
                                                 "work_description": "Domestic water rough", "work_locations": "floor 3"},
                                          status="draft"))
        with _Ctx(db=self.db):
            ctx = {"ident": {"company_id": CO_A}}
            out = asyncio.run(server._dm_work_status(ctx, {"id": THOMAS, "label": "588"}, {"work": "drywall", "level": "3"}))
        self.assertIn("domestic water rough: no report on this level", out)

    def test_work_it_cannot_match_says_so(self):
        with _Ctx(db=self.db):
            ctx = {"ident": {"company_id": CO_A}}
            out = asyncio.run(server._dm_work_status(ctx, {"id": THOMAS, "label": "588"}, {"work": "landscaping", "level": "3"}))
        self.assertIn("can't match", out)

    def test_another_companys_job_is_refused(self):
        with _Ctx(db=self.db):
            ctx = {"ident": {"company_id": "c0ffee000000000000000099"}}
            out = asyncio.run(server._dm_work_status(ctx, {"id": THOMAS, "label": "588"}, {"work": "drywall", "level": "3"}))
        self.assertEqual(out, server.wa_security.BOT_SCOPE_REFUSAL)


class TheSweep(_Brain):

    def _seed(self):
        self.db[server.PHOTO_INDEX].rows += [_pic("k/a.jpg", day="2026-10-01", log="L1"), _pic("k/b.jpg", day="2026-11-05", log="L1")]
        for r in self.db[server.PHOTO_INDEX].rows:
            r["project_id"] = THOMAS

    def _tick(self, calls, env="1"):
        async def compare(a, b, pid):
            calls.append(pid)
            return {"same_area": "yes", "confidence": 0.9, "changes": ["board hung"], "installed": [], "possible_rework": []}

        async def raw(row):
            return b"x"
        with patch.dict("os.environ", {"PHOTO_RELATIONS_ENABLED": env}), patch.object(server, "QWEN_API_KEY", "x"), \
                patch.object(server, "_photo_compare_call", compare), patch.object(server, "_photo_log_bytes", raw), \
                patch.object(R, "GEOMETRY_MIN_INLIERS", 10), \
                patch.object(server.photo_geometry, "match", lambda a, b: {"ok": True, "inliers": 50, "ratio": 0.5, "reason": ""}):
            return asyncio.run(server._photo_relations_tick())

    def test_it_is_off_until_it_is_turned_on(self):
        self._seed()
        calls = []
        with _Ctx(db=self.db):
            self._tick(calls, env="0")
        self.assertEqual(calls, [])

    def test_a_pair_is_paid_for_once_and_stored_with_its_provenance(self):
        self._seed()
        calls = []
        with _Ctx(db=self.db):
            self._tick(calls)
            self._tick(calls)
        self.assertEqual(calls, [THOMAS])
        row = self.db[server.PHOTO_RELATIONS].rows[0]
        self.assertEqual((row["level"], row["same_area"], row["prompt_version"]), ("FLOOR_3", "yes", R.PROMPT_VERSION))
        self.assertIn("model", row)

    def test_it_is_scheduled_and_metered(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("id='photo_relations'", src[src.index("async def startup_event"):])
        self.assertIn(server.VISION_PHOTO_COMPARE, vision_meter.VISION_ENDPOINTS)
        body = src[src.index("async def _photo_compare_call("):src.index("async def _photo_log_bytes(")]
        self.assertIn("await record_vision_call(", body)


if __name__ == "__main__":
    unittest.main()
