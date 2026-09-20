"""The eval harness, held to the rules it enforces on everything else.

A harness that is wrong is worse than none: it produces a rate, and a rate is
believed. Its first real run found four of its own mistakes before it found
anything about the pipeline:

  * a forbidden-word check read the render's HEADER, which repeats the
    caller's question, and reported 'Solar panels — on the drawings:' as a leak
  * 'R19' was expected as the number 19; the gate rightly reads a number with
    a letter in front of it as an identifier
  * '10 PERSONS' was expected in a record whose table cells split it
  * a case built on the text layer called PACKAGED TERMINAL AIR CONDITIONERS
    absent; EN-001.00 prints it in an outlined table

And one about stale data: the first count of "stale" elements was 16. Three
were promoted from a vision-read schedule; thirteen were correct text-layer
counts that the pre-#585 writer had stamped `source: text_layer`.

These tests pin each of those.
"""

import ast
import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_eval as ev  # noqa: E402
from lib import plan_extract as pe  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def rec(**kw):
    base = {"page_id": "p9", "record_type": "text", "ordinal": 0,
            "tier": pe.TIER_TEXT_LAYER, "source": "text_layer", "quote": "",
            "label": None, "subject_terms": [], "payload": {},
            "sheet_number": "M-200.00", "page_number": 9}
    base.update(kw)
    return base


def schedule(source, ordinal, rows=(("PTAC-1", "21"),)):
    return rec(record_type="schedule", ordinal=ordinal, source=source,
               tier={"vision": pe.TIER_VISION, "ocr_grid": pe.TIER_OCR_GRID}
               .get(source, pe.TIER_SCHEDULE_CELL),
               quote="ROOMS PTAC UNITS SCHEDULE\nUNIT NO. | QTY\n"
                     + "\n".join(" | ".join(r) for r in rows),
               payload={"name": "ROOMS PTAC UNITS SCHEDULE",
                        "rows": [list(r) for r in rows]})


def element(ordinal=0, tag="PTAC-1", qty=21, basis="schedule_qty",
            tier=pe.TIER_SCHEDULE_CELL):
    return rec(record_type="element", ordinal=ordinal, tier=tier,
               quote=f"{tag} — count {qty} — ROOMS PTAC UNITS SCHEDULE",
               subject_terms=[tag],
               payload={"name": tag, "tag": tag, "count_if_stated": qty,
                        "count_basis": basis,
                        "location_hint": "ROOMS PTAC UNITS SCHEDULE"})


def suite(**over):
    s = {"schema": 1,
         "project": {"id": "p", "baseline": {"pages": 129}},
         "cases": [{"id": "c1", "kind": "answer", "subject": "ptac",
                    "expect": {"sheets": ["M-200.00"], "values": [21]},
                    "truth": {"how": "by_eye", "evidence": "read it"}}]}
    s.update(over)
    return s


class TheSuiteCannotClaimWhatItCannotJustify(unittest.TestCase):

    def test_the_shipped_suite_is_valid(self):
        s = ev.load_suite(str(BACKEND / "eval" / "boyland.json"))
        self.assertEqual(s["project"]["baseline"]["pages"], 129)
        self.assertGreaterEqual(len(s["cases"]), 20)

    def test_every_case_says_how_its_truth_was_established(self):
        s = suite()
        s["cases"][0]["truth"] = {"how": "by_eye"}
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)

    def test_truth_cannot_come_from_the_records(self):
        s = suite()
        s["cases"][0]["truth"] = {"how": "plan_records", "evidence": "the index said so"}
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)

    def test_an_answer_names_its_sheets_and_what_must_be_said(self):
        for bad in ({"values": [21]}, {"sheets": ["M-200.00"]}):
            s = suite()
            s["cases"][0]["expect"] = bad
            with self.subTest(expect=bad), self.assertRaises(ev.SuiteError):
                ev.validate_suite(s)

    def test_an_absent_case_rests_on_absence(self):
        s = suite()
        s["cases"][0]["kind"] = "absent"
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)

    def test_ids_are_unique_and_tiers_are_real(self):
        s = suite()
        s["cases"].append(dict(s["cases"][0]))
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)
        s = suite()
        s["cases"][0]["expect"]["tier_at_least"] = "pretty_sure"
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)

    def test_nothing_in_the_suite_schema_names_a_project(self):
        # A second project is a second file. The module must not know Boyland.
        src = inspect.getsource(ev)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        tree = ast.parse(code)
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for lit in literals:
            with self.subTest(literal=lit[:40]):
                self.assertNotIn("6a5f63bc", lit)


class OnlyTheVisionPromotedCountsAreStale(unittest.TestCase):

    def test_a_count_whose_only_schedule_was_read_off_the_image(self):
        recs = [schedule("vision", 0), element()]
        self.assertEqual(ev.stale_elements_from_vision(recs),
                         {ev.record_key(recs[1])})

    def test_a_count_from_a_text_layer_table_is_not_stale(self):
        # The 13 RCP-001.00 counts: source text_layer on the element, a real
        # table_finder schedule behind it.
        recs = [schedule("table_finder", 0), element()]
        self.assertEqual(ev.stale_elements_from_vision(recs), set())

    def test_an_ocr_reading_of_the_same_row_does_not_rescue_it(self):
        # PTAC-1 and PTAC-3 on M-200.00: both the vision and the OCR schedule
        # print the row. OCR produces ocr_schedule_qty, never schedule_qty, so
        # the schedule_cell element can only have come from the vision copy.
        recs = [schedule("vision", 0), schedule("ocr_grid", 1), element()]
        self.assertEqual(len(ev.stale_elements_from_vision(recs)), 1)

    def test_a_table_finder_copy_does_rescue_it(self):
        recs = [schedule("vision", 0), schedule("table_finder", 1), element()]
        self.assertEqual(ev.stale_elements_from_vision(recs), set())

    def test_the_join_is_on_the_row_not_just_the_schedule_name(self):
        recs = [schedule("vision", 0, rows=(("PTAC-2", "9"),)), element()]
        self.assertEqual(ev.stale_elements_from_vision(recs), set())

    def test_an_ocr_count_is_never_in_this_class(self):
        recs = [schedule("ocr_grid", 0),
                element(basis="ocr_schedule_qty", tier=pe.TIER_OCR_GRID)]
        self.assertEqual(ev.stale_elements_from_vision(recs), set())

    def test_the_other_classes_are_detected(self):
        idx = ev.stale_index([
            element(ordinal=1, basis=None, tier=pe.TIER_TEXT_LAYER),
            rec(record_type="tag", ordinal=2, payload={"tag": "1"}),
            rec(record_type="tag", ordinal=3, payload={"tag": "PTAC-1"}),
        ])
        self.assertEqual(sorted(idx.values()),
                         ["element_without_a_count_basis", "tag_that_is_not_a_mark"])


PTAC_SCHED = schedule("ocr_grid", 0, rows=(("PTAC-1", "21"), ("PTAC-2", "9")))
CASE = {"id": "ptac", "kind": "answer", "subject": "PTAC units",
        "expect": {"sheets": ["M-200.00"], "values": [21, 9], "text": ["PTAC-1"]},
        "truth": {"how": "by_eye", "evidence": "x"}}


class ACaseIsScoredOnWhatCameBack(unittest.TestCase):

    def test_the_right_sheet_and_the_right_numbers_pass(self):
        r = ev.score_case(CASE, [PTAC_SCHED], {})
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertTrue(r["checks"]["gate_allows_the_true_answer"])
        self.assertTrue(r["checks"]["gate_refuses_an_invented_number"])

    def test_the_wrong_sheet_fails_and_says_where_the_right_one_was(self):
        other = dict(PTAC_SCHED, sheet_number="A-100.01")
        r = ev.score_case(CASE, [other] * 4 + [PTAC_SCHED], {})
        self.assertEqual(r["outcome"], "fail")
        self.assertTrue(any("further down" in x for x in r["reasons"]))

    def test_nothing_returned_fails(self):
        r = ev.score_case(CASE, [], {})
        self.assertEqual(r["outcome"], "fail")

    def test_a_number_nothing_prints_is_a_failure(self):
        case = dict(CASE, expect=dict(CASE["expect"], values=[41]))
        r = ev.score_case(case, [PTAC_SCHED], {})
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["gate_allows_the_true_answer"])

    def test_the_tier_floor_is_checked_against_the_supporting_record(self):
        seen = dict(PTAC_SCHED, tier=pe.TIER_VISION, source="vision")
        case = dict(CASE, expect=dict(CASE["expect"], tier_at_least=pe.TIER_OCR_GRID))
        r = ev.score_case(case, [seen], {})
        self.assertEqual(r["outcome"], "fail")


class TheRenderHeaderIsTheQuestionNotALeak(unittest.TestCase):

    def test_a_forbidden_word_in_the_callers_own_question_is_not_a_leak(self):
        panels = rec(quote="PLYWOOD PANELS", sheet_number="SSP-013.00")
        case = {"id": "solar", "kind": "absent", "subject": "solar panels",
                "expect": {"forbid_text": ["SOLAR"]},
                "truth": {"how": "absent", "evidence": "x"}}
        r = ev.score_case(case, [panels], {})
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        # The render no longer opens with the caller's words at all - the
        # header was removed on 2026-09-19 because a GC would not read it -
        # so the risk this class was written for cannot occur. What still
        # matters, and is what is asserted, is that the case PASSES and the
        # forbidden word appears nowhere in what would be sent.
        # Checked as WORDS. assertNotIn on a bare word is a substring test
        # that anything containing it satisfies or breaks, which
        # test_absence_literals_are_specific bans - and caught here, on an
        # assertion written minutes earlier. Third time in one session.
        self.assertNotIn("SOLAR", r["render"].upper().split())

    def test_a_forbidden_word_in_a_returned_quote_is(self):
        vision = rec(quote="PACKAGE TERMINAL AIR CONDITIONER", tier=pe.TIER_VISION,
                     source="vision", record_type="schedule")
        case = {"id": "p", "kind": "answer", "subject": "air conditioner",
                "expect": {"sheets": ["M-200.00"], "text": ["AIR CONDITIONER"],
                           "forbid_text": ["PACKAGE TERMINAL AIR CONDITIONER"]},
                "truth": {"how": "by_eye", "evidence": "x"}}
        r = ev.score_case(case, [vision], {})
        self.assertEqual(r["outcome"], "fail")


class AnAnswerThatRestsOnlyOnALabelFails(unittest.TestCase):

    KE = [rec(record_type="legend_entry", ordinal=i, tier=pe.TIER_VISION,
              source="vision", quote=f"KE {i}", subject_terms=[f"KE {i}"],
              label=f"KICKER EXHAUST {i}", sheet_number="M-104.00")
          for i in (1, 2)]
    CASE = {"id": "kicker", "kind": "absent", "subject": "kicker",
            "expect": {"forbid_text": ["KICKER"]},
            "truth": {"how": "absent", "evidence": "printed nowhere"}}

    def test_the_kicker_case(self):
        r = ev.score_case(self.CASE, self.KE, {})
        self.assertEqual(r["outcome"], "fail")
        self.assertTrue(any("only through a vision label" in x for x in r["reasons"]))
        self.assertEqual(r["checks"]["lead_matched_only_through_labels"], 2)

    def test_the_fallback_it_would_send_asserts_nothing(self):
        r = ev.score_case(self.CASE, self.KE, {})
        self.assertEqual(r["render"], "Not found.")


class StaleDataIsMarkedNotScored(unittest.TestCase):

    STALE_EL = element()

    def stale(self):
        return {ev.record_key(self.STALE_EL): ev.VISION_PROMOTED}

    def test_a_case_that_leads_with_stale_data_is_not_scored(self):
        r = ev.score_case(CASE, [self.STALE_EL, PTAC_SCHED], self.stale())
        self.assertEqual(r["outcome"], "stale")
        self.assertEqual(r["stale"][0][2], ev.VISION_PROMOTED)

    def test_a_case_never_passes_on_the_strength_of_a_stale_record(self):
        # With only the stale element, the numbers are 'supported' — by the
        # record that is wrong. That must not count as a pass.
        r = ev.score_case(dict(CASE, expect=dict(CASE["expect"], values=[21])),
                          [self.STALE_EL], self.stale())
        self.assertNotEqual(r["outcome"], "pass")

    def test_a_failure_that_survives_removing_the_stale_data_is_scored(self):
        # 'wall electric unit heater' led with the stale PTAC elements and
        # never returned WH-1. Hiding that as STALE would hide a defect.
        case = {"id": "wh", "kind": "answer", "subject": "wall electric unit heater",
                "expect": {"sheets": ["M-200.00"], "values": [9], "text": ["WH-1"]},
                "truth": {"how": "by_eye", "evidence": "x"}}
        unrelated = rec(quote="DWELLING UNITS", sheet_number="GN-001.00",
                        tier=pe.TIER_SCHEDULE_CELL, source="table_finder",
                        record_type="schedule", ordinal=5)
        r = ev.score_case(case, [self.STALE_EL, unrelated], self.stale())
        self.assertEqual(r["outcome"], "fail")
        self.assertEqual(r["without_stale"], "fail")

    def test_stale_cases_are_left_out_of_the_rate(self):
        results = [{"outcome": "pass", "kind": "answer"},
                   {"outcome": "fail", "kind": "answer"},
                   {"outcome": "stale", "kind": "answer"}]
        s = ev.summarise(results)
        self.assertEqual((s["scored"], s["passed"], s["stale"]), (2, 1, 1))
        self.assertEqual(s["pass_rate"], 0.5)


class TheCorpusMustBeTheOneTheSuiteWasWrittenFor(unittest.TestCase):

    BASE = {"pages": 129, "current_pages": 111, "records": 15369,
            "newest_page_indexed_at": "2026-09-17 06:28:32.342000",
            "newest_record_created_at": "2026-09-17 06:29:02.230000"}

    def test_the_same_corpus_has_no_drift(self):
        self.assertEqual(ev.check_baseline(self.BASE, dict(self.BASE)), [])

    def test_one_page_written_since_is_drift(self):
        now = dict(self.BASE, newest_page_indexed_at="2026-09-18 09:00:00")
        self.assertEqual(len(ev.check_baseline(self.BASE, now)), 1)

    def test_a_deleted_page_is_drift(self):
        self.assertTrue(ev.check_baseline(self.BASE, dict(self.BASE, pages=128)))

    def test_the_runner_refuses_rather_than_caveats(self):
        src = (BACKEND / "scripts" / "plan_eval.py").read_text(encoding="utf-8")
        self.assertIn("REFUSING", src)
        self.assertIn("return 3", src)
        # And it checks again after the run: a write DURING it invalidates it.
        self.assertIn("after = await observe(server, pid)", src)

    def test_the_runner_writes_nothing_to_the_database(self):
        from tests.test_every_prod_writer_is_guarded import _writes_in
        tree = ast.parse((BACKEND / "scripts" / "plan_eval.py")
                         .read_text(encoding="utf-8"))
        self.assertEqual(_writes_in(tree), [])

    def test_the_runner_calls_the_shipped_search(self):
        src = (BACKEND / "scripts" / "plan_eval.py").read_text(encoding="utf-8")
        self.assertIn("await server.search_plans(", src)


class AKnownFailureIsStillAFailure(unittest.TestCase):
    """ac-type fails because generic boilerplate ('EACH AC UNIT SHALL HAVE A
    MINI-CONDENSATE PUMP', printed on M-100.00-M-105.00) matches more of the
    question than the PTAC schedule does. Boyland has PTACs only. The class is
    recorded; the case is not excused."""

    def test_the_shipped_suite_records_the_class(self):
        s = ev.load_suite(str(BACKEND / "eval" / "boyland.json"))
        known = ev.known_failure_classes(s)
        self.assertEqual(known.get("ac-type"), "boilerplate_outranks_specific")

    def test_a_known_failure_still_counts_against_the_rate(self):
        results = [{"outcome": "pass", "kind": "answer"},
                   {"outcome": "fail", "kind": "answer",
                    "known_failure": "boilerplate_outranks_specific"}]
        s = ev.summarise(results)
        self.assertEqual((s["scored"], s["passed"], s["failed"]), (2, 1, 1))
        self.assertEqual(s["pass_rate"], 0.5)
        self.assertEqual(s["failed_in_known_classes"], 1)

    def test_a_known_failure_must_name_a_real_case_and_its_evidence(self):
        s = suite(known_failures=[{"class": "x", "cases": ["nope"], "evidence": "e"}])
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)
        s = suite(known_failures=[{"class": "x", "cases": ["c1"]}])
        with self.assertRaises(ev.SuiteError):
            ev.validate_suite(s)

    def test_the_runner_labels_it_and_does_not_skip_it(self):
        src = (BACKEND / "scripts" / "plan_eval.py").read_text(encoding="utf-8")
        self.assertIn("known_failure_classes(suite)", src)
        self.assertNotIn("if case[\"id\"] in known", src)


if __name__ == "__main__":
    unittest.main()
