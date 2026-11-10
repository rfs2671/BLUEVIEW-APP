"""THE TRUTH FIXES, ONE TEST CLASS PER FINDING.

tests/test_truth_regressions.py holds the adversarial reviewer's reproductions
exactly as found. This file pins each fix from the side the reproduction did not
cover: the honest behaviour that must survive the fix (a plain pass is still a
pass, a one-level sheet still places a photo), and the second shape of each
defect. Pure, except the loader test, which runs server._progress_evidence over
the fake db.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

from lib import dob_signoffs as DS  # noqa: E402
from lib import evidence as E  # noqa: E402
from lib import evidence_sources as ES  # noqa: E402
from lib import forecast as F  # noqa: E402
from lib import inspection_reports as IR  # noqa: E402
from lib import photo_place as PL  # noqa: E402
from lib import progress_plan as PP  # noqa: E402
from lib import project_progress as PPG  # noqa: E402
from lib import work_state as W  # noqa: E402

TODAY = date(2026, 11, 10)
F3 = "FLOOR_3"


def _at(day, hour=15):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def _row(result, said_at, inspected_on=None, rid="r", status="attested", levels=(F3,), **kw):
    return {"_id": rid, "status": status, "gate": IR.PLUMBING_ROUGH, "levels": list(levels), "result": result,
            "validated_result": result, "inspected_on": inspected_on, "created_at": said_at,
            "reporter_name": "Joe", "quote": kw.pop("quote", "x"), **kw}


def _item(kind, claim, on=None, said_at=None, ref="i"):
    return E.item(kind, claim, source="inspection_reports", ref=ref, project_id="p", node=IR.PLUMBING_ROUGH,
                  levels=[F3], on=on, said_at=said_at)


# 1 ─────────────────────────────────────────────────────────────────────────
class OneOrderOfNewest(unittest.TestCase):

    def test_an_undated_failure_said_later_beats_a_dated_pass(self):
        items = [_item("attested", "done", on=date(2026, 11, 3), said_at=_at(3), ref="a"),
                 _item("attested", "failed", said_at=_at(9), ref="b")]
        self.assertEqual(E.status(items), "failed_attested")
        self.assertEqual(E.newest(items)["ref"], "b")

    def test_within_a_day_the_undated_one_is_last(self):
        items = [_item("attested", "failed", said_at=_at(9, 13), ref="b"),
                 _item("attested", "done", on=date(2026, 11, 9), said_at=_at(9, 20), ref="a")]
        self.assertEqual(E.status(items), "failed_attested")

    def test_two_of_the_same_date_go_by_when_they_were_said(self):
        items = [_item("attested", "failed", on=date(2026, 11, 3), said_at=_at(4), ref="b"),
                 _item("attested", "done", on=date(2026, 11, 3), said_at=_at(5), ref="a")]
        self.assertEqual(E.status(items), "done_attested")

    def test_the_record_date_still_orders_first(self):
        # A retest: failed on the 1st (reported late), passed on the 7th.
        items = [_item("attested", "done", on=date(2026, 11, 7), said_at=_at(7), ref="a"),
                 _item("attested", "failed", on=date(2026, 11, 1), said_at=_at(9), ref="b")]
        self.assertEqual(E.status(items), "done_attested")

    def test_a_later_undated_failure_is_a_conflict(self):
        rows = [_row("passed", _at(3), "2026-11-03", "a"), _row("failed", _at(9), None, "b")]
        items, _ = ES.from_inspections(rows, "p")
        model = PPG.build(items, today=TODAY, project={"building_stories": 3}, job="588")
        kinds = [c["type"] for c in model["conflicts"] if c["node"] == IR.PLUMBING_ROUGH and c["level"] == F3]
        self.assertIn("done_then_failed", kinds)
        self.assertIn("date not stated", PPG.as_text(model))

    def test_inspection_reports_use_the_same_rule(self):
        s = IR.current_state([_row("passed", _at(3), "2026-11-03", "a"), _row("failed", _at(9), None, "b")])
        self.assertEqual(s[(IR.PLUMBING_ROUGH, F3)]["result"], "failed")
        # Undated last within its day, though said before the dated pass:
        s = IR.current_state([_row("passed", _at(9, 20), "2026-11-09", "a"), _row("failed", _at(9, 13), None, "b")])
        self.assertEqual(s[(IR.PLUMBING_ROUGH, F3)]["result"], "failed")
        # A retest: the late report of an earlier failure does not undo it, and is shown.
        s = IR.current_state([_row("passed", _at(7), "2026-11-07", "a"), _row("failed", _at(9), "2026-11-01", "b")])
        self.assertEqual(s[(IR.PLUMBING_ROUGH, F3)]["result"], "passed")
        self.assertFalse(IR.gate_read(s, IR.PLUMBING_ROUGH, F3)["settled"])

    def test_the_forecast_marker_is_the_newest_too(self):
        rows = [_row("passed", _at(3), "2026-11-03", "a"), _row("failed", _at(9), None, "b")]
        m = F.markers(F.items_from_inspection_reports(rows, "p"))
        self.assertIsNone(m["done"])
        self.assertEqual(m["failed"]["ref"], "b")


# 2 ─────────────────────────────────────────────────────────────────────────
class TheWholeMessageIsRead(unittest.TestCase):

    def test_a_plain_pass_is_still_a_pass(self):
        v = IR.validate_statement("Plumbing rough on 3 passed.", "Plumbing rough on 3 passed", "passed")
        self.assertEqual(v["result"], "passed")

    def test_saying_it_twice_is_not_a_correction(self):
        v = IR.validate_statement("Plumbing rough on 3 passed. It passed!", "Plumbing rough on 3 passed", "passed")
        self.assertEqual(v["result"], "passed")

    def test_a_correction_in_another_sentence(self):
        for own in ("Plumbing rough on 3 passed. Wait, it failed.", "Plumbing rough on 3 passed. No it didn't pass",
                    "Plumbing rough on 3 passed. I doubt it passed though."):
            with self.subTest(own=own):
                v = IR.validate_statement(own, "Plumbing rough on 3 passed", "passed")
                self.assertIsNone(v["result"])
                self.assertIn("another sentence", v["reason"])

    def test_another_inspection_it_names_is_its_own_report(self):
        v = IR.validate_statement("Plumbing rough on 3 passed. Electrical rough failed.",
                                  "Plumbing rough on 3 passed", "passed")
        self.assertEqual(v["result"], "passed")

    def test_a_question_after_it_is_not_a_correction(self):
        v = IR.validate_statement("Plumbing rough on 3 passed. Did electrical pass?", "Plumbing rough on 3 passed",
                                  "passed")
        self.assertEqual(v["result"], "passed")


# 3 ─────────────────────────────────────────────────────────────────────────
class FloorsAsLevels(unittest.TestCase):

    def test_a_count_is_not_a_floor(self):
        for t in ("3 guys from the plumber", "passed with 3 inspectors", "588 Boyland", "on the 3rd"):
            with self.subTest(t=t):
                self.assertFalse(W.level_said(F3, t))

    def test_a_level_said_as_one(self):
        for t in ("passed on 3", "floor 3", "3rd floor", "3rd fl", "third floor", "floors 2-4", "floors 2, 3 and 4",
                  "levels 3 & 5", "3rd and 4th floors"):
            with self.subTest(t=t):
                self.assertTrue(W.level_said(F3, t))

    def test_each_floor_in_its_own_sentence_and_the_call_matches(self):
        own = "Plumbing rough passed on 2. Floor 3 failed."
        ok = IR.validate_statement(own, "Plumbing rough passed on 2", "passed", levels=["FLOOR_2"])
        self.assertEqual(ok["result"], "passed")
        both = IR.validate_statement(own, "Plumbing rough passed on 2", "passed", levels=["FLOOR_2", F3])
        self.assertIsNone(both["result"])

    def test_two_floors_in_one_sentence_stay_unresolved(self):
        v = IR.validate_statement("Plumbing rough passed on 2, floor 3 failed", "Plumbing rough passed on 2",
                                  "passed", levels=["FLOOR_2"])
        self.assertIsNone(v["result"])


# 4 ─────────────────────────────────────────────────────────────────────────
class HedgesAndHearsay(unittest.TestCase):

    def test_never_a_plain_pass(self):
        for own in ("I doubt plumbing rough passed", "nothing passed today, plumbing rough",
                    "nobody passed plumbing rough", "whether plumbing rough passed I can't say",
                    "unless plumbing rough passed we wait", "plumbing rough passed (not)", "plumbing rough passed lol jk",
                    "plumbing rough was anything but passed", "I wish plumbing rough passed",
                    "plumbing rough passed with corrections", "plumbing rough conditionally approved",
                    "plumbing rough passed conditionally", "conditional pass on plumbing rough",
                    "plumbing rough passed, just kidding"):
            with self.subTest(own=own):
                v = IR.validate_statement(own, own, "passed")
                self.assertIsNone(v["result"])
                self.assertNotIn("passed", v["read"])

    def test_nothing_failed_is_not_a_failure_either(self):
        self.assertIsNone(IR.validate_statement("nothing failed on 3", "nothing failed on 3", "failed")["result"])

    def test_hearsay_names_who_said_it(self):
        v = IR.validate_statement("Joe said plumbing rough passed on 3", "plumbing rough passed on 3", "passed")
        self.assertEqual((v["result"], v["hearsay_from"]), ("passed", "Joe"))
        self.assertEqual(IR.hearsay_from("the inspector told me it passed"), "the inspector")
        self.assertEqual(IR.hearsay_from("I heard it passed"), "someone not named")
        self.assertIsNone(IR.hearsay_from("Plumbing rough passed on 3"))
        self.assertIsNone(IR.hearsay_from("I said it passed"))

    def test_hearsay_is_reported_never_attested_or_a_marker(self):
        row = _row("passed", _at(9), None, "h", hearsay_from="Joe")
        items, _ = ES.from_inspections([row], "p")
        self.assertEqual(items[0]["kind"], "reported")
        self.assertIn("Joe said it", items[0]["note"])
        self.assertNotEqual(E.status(items), "done_attested")
        self.assertEqual(F.items_from_inspection_reports([row], "p"), [])
        w = IR.words(IR.gate_read(IR.current_state([row]), IR.PLUMBING_ROUGH, F3))
        self.assertIn("hearsay: Joe reports that Joe said it", w)
        line = IR.noted_line("Ana", "plumbing rough", ["Floor 3"], "passed", None, hearsay="Joe")
        self.assertIn("Kept as hearsay: Ana reports that Joe said it", line)


# 5 ─────────────────────────────────────────────────────────────────────────
class SignOffPages(unittest.TestCase):
    FORM = "PLUMBING ROUGH INSPECTION\nFLOOR 3\n[{p}] PASSED\n[{f}] FAILED\nINSPECTOR J. SMITH"

    def test_the_ticked_box_decides(self):
        page = self.FORM.format(p="X", f=" ")
        self.assertEqual(IR.validate_document(page, "PASSED", "passed")["result"], "passed")
        self.assertIsNone(IR.validate_document(page, "FAILED", "failed")["result"])

    def test_no_box_or_both_boxes_is_unresolved(self):
        for p, f in (("X", "X"), (" ", " ")):
            with self.subTest(p=p, f=f):
                v = IR.validate_document(self.FORM.format(p=p, f=f), "PASSED", "passed")
                self.assertIsNone(v["result"])
                self.assertIn("ticked", v["reason"])

    def test_a_page_that_reads_one_result_still_reads(self):
        self.assertEqual(IR.validate_document("SPRINKLER HYDRO\nRESULT: APPROVED", "RESULT: APPROVED",
                                              "passed")["result"], "passed")

    def test_no_text_cannot_check_itself(self):
        v = IR.validate_document("   ", "RESULT: PASSED", "passed")
        self.assertIsNone(v["result"])
        self.assertIn("cannot check itself", v["reason"])


# 6 ─────────────────────────────────────────────────────────────────────────
class DobRowsSignedThemselves(unittest.TestCase):

    def test_one_vocabulary(self):
        for s in ("LOC Issued", "Signed-off", "QA Review for LOC", "NOT SIGNED OFF", "Complete", "Permit Issued"):
            with self.subTest(s=s):
                self.assertEqual(ES.signoff_words(s), DS.is_signed_off(s))

    def test_a_signed_row_still_gives_its_work(self):
        rows = [{"record_type": "permit", "job_number": "B0001-I1", "raw_dob_id": "p1", "work_type": "Plumbing",
                 "permit_status": "Signed-off", "signoff_date": "2026-10-01"}]
        items, _ = ES.from_dob(rows, "p")
        self.assertEqual(sorted(i["node"] for i in items), ["rough_dwv", "rough_water"])


# 7 ─────────────────────────────────────────────────────────────────────────
class StandingRecordsHaveNoWindow(unittest.TestCase):
    POUR = {"_id": "L1", "log_type": "concrete_operations", "status": "submitted", "date": "2026-07-01",
            "data": {"pour_location": "3rd floor slab"}, "cp_name": "CP"}

    def test_the_jul_1_pour_is_read_and_its_activity_is_not_late(self):
        items, cov = ES.collect("p", start=TODAY - timedelta(days=89), end=TODAY, logbooks=[self.POUR])
        self.assertEqual([(i["node"], i["claim"]) for i in items], [("superstructure", "done")])
        self.assertEqual(cov["concrete_operations"]["outside_window"], 0)
        sched = {"activities": [{"id": "A1", "name": "Floor 3 slab", "baseline_finish": "2026-07-05"}]}
        self.assertFalse(F.forecast(sched, items, [], today=TODAY, project_id="p")
                         ["plan_vs_actual"][0]["past_planned_finish_no_done"])

    def test_reported_activity_is_still_windowed(self):
        sup = {"_id": "S1", "log_type": "site_superintendent_log", "status": "submitted", "date": "2026-07-01",
               "data": {"daily_inspection": {"location": "floor 3", "result": "ok"}}}
        items, _ = ES.collect("p", start=TODAY - timedelta(days=89), end=TODAY, logbooks=[sup])
        self.assertEqual(items, [])

    def test_the_loader_reads_pour_logs_older_than_the_window(self):
        from tests._fake_mongo import FakeDb
        from tests.test_evidence_sources import PID, _pour
        import server
        db = FakeDb()
        db.logbooks.rows += [_pour("3rd floor slab", day="2026-07-01", lid="old"),
                             {**_pour("x", day="2026-07-01", lid="sup"), "log_type": "site_superintendent_log",
                              "data": {"daily_inspection": {"location": "floor 3", "result": "ok"}}}]
        src = {"logbooks": [], "checkins": [], "dob_rows": [], "project_bins": [], "schedule": None}

        async def rows(*a, **k):
            return src

        async def place(pid):
            return {}, {}
        with patch.object(server, "db", db), patch.object(server, "_report_rows", rows), \
                patch.object(server, "_photo_place_context", place):
            items, cov = asyncio.run(server._progress_evidence({"_id": PID, "company_id": "co"}, "co",
                                                               date(2026, 10, 27), date(2026, 11, 9)))
        self.assertEqual([i["ref"] for i in items if i["source"] == "concrete_operations"], ["old"])
        self.assertEqual([i for i in items if i["source"] == "superintendent_log"], [])


# 8 ─────────────────────────────────────────────────────────────────────────
class DatesFromTheirWords(unittest.TestCase):

    def test_a_date_they_said(self):
        for words, d in (("passed yesterday", "2026-11-09"), ("passed today", "2026-11-10"), ("passed Nov 3", "2026-11-03"),
                         ("passed on 11/3", "2026-11-03"), ("passed monday", "2026-11-09"),
                         ("passed November 3rd", "2026-11-03"), ("passed on the 3rd", "2026-11-03")):
            with self.subTest(words=words):
                self.assertEqual(IR.clean_date(d, TODAY, "passed", words=words), (d, None))

    def test_a_date_they_did_not_say(self):
        for words in ("plumbing rough on 3 passed", "passed yesterday", "passed friday", None):
            with self.subTest(words=words):
                self.assertEqual(IR.clean_date("2026-11-03", TODAY, "passed", words=words), (None, "not_in_their_words"))

    def test_the_reply_says_the_date_is_unknown(self):
        line = IR.noted_line("Joe", "plumbing rough", ["Floor 3"], "passed", None, date_unknown=True)
        self.assertIn("inspection date is unknown", line)

    def test_the_forecast_prints_no_report_day_as_the_inspection_day(self):
        it = F.items_from_inspection_reports([_row("passed", _at(9))], "p")[0]
        self.assertIsNone(it["on"])
        self.assertIn("date not stated", F._marker_words(F._marker(it)))
        self.assertNotIn("Nov 9", F._marker_words(F._marker(it)))


# 9 ─────────────────────────────────────────────────────────────────────────
class NoFloorIsNotTheBuilding(unittest.TestCase):

    def test_place_unknown(self):
        items, _ = ES.from_inspections([_row("passed", _at(9), levels=())], "p")
        model = PPG.build(items, today=TODAY, project={"building_stories": 4}, job="588")
        txt = PPG.as_text(model)
        self.assertEqual([c["node"] for c in model["place_unknown"]], [IR.PLUMBING_ROUGH])
        self.assertEqual([c["node"] for c in model["building"] if c["bucket"] != "unknown"], [])
        self.assertIn("place unknown", txt)
        self.assertIsNone(re.search(r"\bon\s*(?:[.;,]|$)", txt, re.M))

    def test_a_dob_filing_with_no_level_is_still_the_buildings(self):
        it = E.item("verified", "done", source="dob_logs", ref="B1", project_id="p", node="rough_sprinkler")
        model = PPG.build([it], today=TODAY, project={"building_stories": 2}, job="588")
        self.assertEqual([c["node"] for c in model["building"] if c["bucket"] != "unknown"], ["rough_sprinkler"])
        self.assertEqual(model["place_unknown"], [])


# 10 ────────────────────────────────────────────────────────────────────────
class ALaterUnresolvedStatementIsShown(unittest.TestCase):

    def test_not_settled(self):
        rows = [_row("passed", _at(3), "2026-11-03", "a"),
                _row(None, _at(9), None, "b", status=IR.UNRESOLVED, quote="failed today on retest")]
        r = IR.gate_read(IR.current_state(rows), IR.PLUMBING_ROUGH, F3)
        self.assertFalse(r["settled"])
        w = IR.words(r)
        self.assertTrue(w.startswith("NOT SETTLED"))
        self.assertIn('a later statement is unresolved: "failed today on retest"', w)

    def test_an_older_unresolved_one_does_not_unsettle(self):
        rows = [_row(None, _at(2), None, "b", status=IR.UNRESOLVED), _row("passed", _at(3), "2026-11-03", "a")]
        self.assertTrue(IR.gate_read(IR.current_state(rows), IR.PLUMBING_ROUGH, F3)["settled"])


# 11 ────────────────────────────────────────────────────────────────────────
class AnInspectionActivityIsTheGate(unittest.TestCase):

    def test_gate_first_work_otherwise(self):
        self.assertEqual(PP.activity_place({"name": "Plumbing rough inspection floor 3"})["nodes"], [IR.PLUMBING_ROUGH])
        self.assertEqual(PP.activity_place({"name": "Sprinkler hydro test floor 3"})["nodes"], [IR.SPRINKLER])
        self.assertNotIn(IR.PLUMBING_ROUGH, PP.activity_place({"name": "Plumbing rough floor 3"})["nodes"])


# 12 ────────────────────────────────────────────────────────────────────────
class APastPeriodDoesNotKnowTheFuture(unittest.TestCase):

    def test_said_after_the_end_is_left_out(self):
        rows = [_row("passed", _at(3), "2026-11-01", "a"), _row("failed", _at(9), "2026-11-01", "b")]
        items, _ = ES.collect("p", start=date(2026, 10, 1), end=date(2026, 11, 5), inspections=rows)
        self.assertEqual([i["ref"] for i in items], ["a"])

    def test_the_evening_of_the_last_day_is_inside(self):
        late = _row("passed", datetime(2026, 11, 6, 2, tzinfo=timezone.utc), None, "a")   # Nov 5, 9 pm New York
        items, _ = ES.collect("p", start=date(2026, 10, 1), end=date(2026, 11, 5), inspections=[late])
        self.assertEqual([i["ref"] for i in items], ["a"])


# 13 ────────────────────────────────────────────────────────────────────────
class ATypicalSheetPinsNoLevel(unittest.TestCase):

    def test_stair_on_cellar_and_typical(self):
        spaces = PL.spaces_from_plan_rows([
            {"unit": "non-unit:STAIR 1", "sheet_title": "CELLAR FLOOR PLAN", "sheet_number": "A-100"},
            {"unit": "non-unit:STAIR 1", "sheet_title": "TYPICAL FLOOR PLAN 2-6", "sheet_number": "A-102"}])
        p = PL.infer({"where": "", "work": "framing", "visible_text": ["STAIR 1"]}, spaces)
        self.assertFalse(PL.is_sufficient(p))
        self.assertEqual(p["certainty"], PL.SUGGESTED)

    def test_a_tag_on_one_level_sheet_only_still_places(self):
        spaces = PL.spaces_from_plan_rows([{"unit": "non-unit:STAIR 1", "sheet_title": "CELLAR FLOOR PLAN",
                                            "sheet_number": "A-100"}])
        p = PL.infer({"where": "", "work": "framing", "visible_text": ["STAIR 1"]}, spaces)
        self.assertEqual((p["certainty"], p["level"]), (PL.INFERRED, "CELLAR"))


# 14 ────────────────────────────────────────────────────────────────────────
class UnreadableReachesTheAnswer(unittest.TestCase):

    def test_progress_says_not_read(self):
        model = PPG.build([], today=TODAY, project={"building_stories": 2}, job="588", unreadable=["inspection_reports"])
        for scope, name in (("overall", None), ("floor", "2")):
            with self.subTest(scope=scope):
                txt = PPG.as_text(model, scope, name)
                self.assertIn("Could not be read just now: inspection reports", txt)
        model["by_level"]["FLOOR_1"]["bottleneck"]["gates"] = [{"node": "g", "label": "g", "bucket": "unknown",
                                                                 "conditional": False}]
        words = PPG._bottleneck_words(model, "FLOOR_1")
        self.assertIn("inspection reports could not be read", words)
        self.assertNotIn("with no record", words)

    def test_the_forecast_says_not_read(self):
        fc = F.forecast({"activities": []}, [], [], today=TODAY, project_id="p", unreadable=["inspection_reports"])
        self.assertIn("Could not be read just now: inspection reports", F.status_text(fc))


# 15 ────────────────────────────────────────────────────────────────────────
class AFilingDateIsNotASignOffDate(unittest.TestCase):

    def test_said_as_a_filing_date(self):
        r = {"record_type": "job_status", "job_filing_number": "B0002-I1", "raw_dob_id": "j",
             "filing_status": "LOC Issued", "filing_date": "2025-01-03"}
        (e,) = DS.signoffs([r])
        self.assertIsNone(e["date"])
        line = DS.signoff_line(e)
        self.assertIn("status date unknown; filing date 2025-01-03", line)
        self.assertNotIn("on 2025-01-03", line)

    def test_a_real_signoff_date_still_reads(self):
        r = {"record_type": "job_status", "job_filing_number": "B0002-I1", "raw_dob_id": "j",
             "filing_status": "LOC Issued", "filing_date": "2025-01-03", "signoff_date": "2026-11-05"}
        self.assertIn("on 2026-11-05", DS.signoff_line(DS.signoffs([r])[0]))


if __name__ == "__main__":
    unittest.main()
