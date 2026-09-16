"""The drawings' own text is searched before any picture is looked at.

Regression, 2026-09-16. After the full v3 re-index the group asked the same
things it had asked the day before and got "not found" back, twice after a
90-second wait. The index was fine: 589 chunks on 121 current pages, with
HELICAL PILES printed on S-001.00 and a PTAC schedule on M-200.00. What went
wrong was upstream of the search — _answer_plan_from_chunks asked
question_kind() first and, when it came back None, never looked at the index
at all. "Whats the helical piles" has no count word, no attribute word and no
leading auxiliary, so it went straight to a vision model.

Most of this file runs against the REAL production chunks, pulled from the
Boyland project on 2026-09-16 and committed as a fixture. Embeddings and the
database ids are stripped; every line of extracted text is exactly what the
indexer wrote. A fixture built by hand would have agreed with whatever the
code did — this one does not know about the code.
"""

import asyncio
import gzip
import json
import os
import sys
import unittest
from functools import lru_cache
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib import plan_extract as pe  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "boyland_page_chunks_2026_09_16.json.gz"


@lru_cache(maxsize=1)
def chunks():
    with gzip.open(FIXTURE, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def answer(question):
    return pe.answer_question(chunks(), question, None)


class TheFixtureIsTheRealIndex(unittest.TestCase):

    def test_it_is_the_whole_current_set(self):
        rows = chunks()
        self.assertEqual(len(rows), 589)
        sheets = {c.get("sheet_number") for c in rows}
        for sheet in ("S-001.00", "A-500.00", "M-200.00", "A-300", "GN-001.00"):
            self.assertIn(sheet, sheets)

    def test_no_production_identifiers_travelled_with_it(self):
        for c in chunks()[:50]:
            for key in ("_id", "project_id", "company_id", "file_id", "page_id",
                        "embedding", "file_hash"):
                self.assertNotIn(key, c)


class TheQuestionsThatWentToVisionAndCameBackEmpty(unittest.TestCase):
    """The five from the 2026-09-16 report. Each must answer from the text,
    naming the sheet the answer is printed on."""

    def test_whats_the_helical_piles(self):
        a = answer("Whats the helical piles")
        self.assertIsNotNone(a, "went to the vision model; S-001.00 prints it")
        self.assertTrue(a["outcome"].startswith("chunk_"))
        self.assertIn("S-001.00", a["text"])
        self.assertIn("HELICAL PILES", a["text"].upper())

    def test_what_piles_used_on_site(self):
        a = answer("What piles used on site?")
        self.assertIsNotNone(a)
        self.assertIn("S-001.00", a["text"])
        self.assertIn("HELICAL PILES", a["text"].upper())

    def test_what_type_of_ac_units_are_in_the_building(self):
        a = answer("what type of AC units are in the building")
        self.assertIsNotNone(a)
        self.assertEqual(a["outcome"], "chunk_schedule")
        self.assertIn("M-200.00", a["text"])
        # The makes and models, not a sentence with the word "type" in it.
        self.assertIn("AMANA", a["text"])
        self.assertIn("PTAC-1", a["text"])
        self.assertNotIn("GN-001.00", a["text"])

    def test_stucco_thickness_leads_with_the_sheet_that_carries_the_assembly(self):
        a = answer("stucco thickness")
        self.assertIsNotNone(a)
        self.assertEqual(a["outcome"], "chunk_attribute_not_stated")
        named = a["text"].split("Mentioned on", 1)[1]
        self.assertTrue(named.strip().startswith("A-500.00"),
                        f"A-500.00 is the wall-type schedule; got {named.strip()}")

    def test_a_bare_subject_still_reaches_the_text(self):
        a = answer("Foundation....")
        self.assertIsNotNone(a, "no count, no attribute, no auxiliary — still a question")
        self.assertTrue(a["outcome"].startswith("chunk_"))


class ClassificationPicksTheShapeNotWhetherToLook(unittest.TestCase):

    def test_the_three_phrasings_classify_as_nothing(self):
        for q in ("Whats the helical piles", "What piles used on site?", "Foundation...."):
            with self.subTest(q=q):
                self.assertEqual(pe.question_kind(q), (None, None))

    def test_and_are_answered_anyway(self):
        for q in ("Whats the helical piles", "What piles used on site?", "Foundation...."):
            with self.subTest(q=q):
                self.assertIsNotNone(answer(q))

    def test_an_unknown_subject_is_still_allowed_to_reach_the_model(self):
        # Not every miss is a bug. Nothing in the set mentions this, so the
        # text honestly has nothing and the caller may go look at a picture.
        self.assertIsNone(answer("Whats the pneumatic caisson"))


class AShortTermMustStartAWord(unittest.TestCase):

    def test_receptacles_is_not_a_ptac(self):
        self.assertFalse(pe._matches("APPROVED TYPE MAIL RECEPTACLES", ["ac"]))
        self.assertTrue(pe._matches("PTAC-1 = PACKAGE TERMINAL AIR CONDITIONER", ["ac"]))

    def test_a_term_still_grows_to_the_right(self):
        self.assertTrue(pe._matches("HELICAL PILES", ["pile"]))
        self.assertTrue(pe._matches("CONDENSING UNIT", ["ac"]))
        self.assertTrue(pe._matches("ROOF DRAINS", ["drain"]))


class AGenericWordIsNotASubject(unittest.TestCase):

    def test_building_drops_out_beside_a_real_subject(self):
        self.assertEqual(pe.question_terms("what type of AC units are in the building"), ["ac"])

    def test_but_survives_when_it_is_the_whole_subject(self):
        self.assertEqual(pe.question_terms("what is the building height"), ["building"])
        a = answer("what is the building height")
        self.assertIsNotNone(a)
        self.assertIn("MAX. BUILDING HEIGHT", a["text"].upper())


class AScheduleNamedForTheThingAnswersIt(unittest.TestCase):

    def test_the_ptac_schedule_is_found_by_its_title(self):
        hits = pe.answer_named_schedule(chunks(), ["ac"])
        self.assertTrue(hits)
        self.assertEqual(hits[0]["sheet"], "M-200.00")
        self.assertIn("PTAC", hits[0]["name"])

    def test_a_schedule_read_from_the_image_says_so(self):
        text = pe.format_named_schedule_answer("ac", [{
            "sheet": "M-200.00", "name": "ROOMS PTAC UNITS SCHEDULE", "via": "vision",
            "columns": ["UNIT NO.", "QTY", "MAKE"], "rows": [["PTAC-1", "21", "AMANA"]]}])
        self.assertIn("read from the drawing image", text)

    def test_nothing_is_claimed_when_no_schedule_is_named_for_it(self):
        self.assertEqual(pe.answer_named_schedule(chunks(), ["sidewalk"]), [])


class ANumberReadOffAPictureSaysSo(unittest.TestCase):
    """M-200.00's PTAC schedule states 21, 9 and 11 units. The whole text layer
    of that page is 47 characters — "HVAC SCHEDULES / AND DETAILS / M-200.00 /
    P: / E: / W: / 9". Nothing on the page confirms 21."""

    def _vision_schedules(self):
        return [c for c in chunks()
                if c.get("chunk_type") == "schedule"
                and (c.get("payload") or {}).get("source") == "vision"]

    def test_the_set_has_seven_of_them_on_five_sheets(self):
        vis = self._vision_schedules()
        self.assertEqual(len(vis), 7)
        self.assertEqual(sorted({c["sheet_number"] for c in vis}),
                         ["M-001.00", "M-200.00", "S-105.00", "S-301.00", "S-302.00"])

    def test_the_ptac_answer_asks_for_the_sheet_to_be_checked(self):
        a = answer("what type of AC units are in the building")
        self.assertIn("read from the drawing image — verify against the sheet", a["text"])

    def test_and_so_does_a_count_taken_off_it(self):
        a = answer("how many ptac units")
        self.assertEqual(a["outcome"], "chunk_count")
        self.assertIn("41", a["text"])          # 21 + 9 + 11, none of them printed
        self.assertIn("verify against the sheet", a["text"])

    def test_a_table_of_words_has_no_number_to_be_wrong_about(self):
        # GENERAL ABBREVIATIONS on M-001.00 is vision-read and states nothing
        # numeric. It still says where it came from; it does not ask for a check.
        abbrev = [c for c in self._vision_schedules()
                  if (c["payload"].get("name") or "") == "GENERAL ABBREVIATIONS"]
        self.assertTrue(abbrev)
        self.assertFalse(pe.schedule_needs_verifying(chunks(), abbrev[0]))

    def test_a_schedule_the_text_layer_read_is_never_flagged(self):
        flagged = [c for c in chunks()
                   if c.get("chunk_type") == "schedule"
                   and (c.get("payload") or {}).get("source") != "vision"
                   and pe.schedule_needs_verifying(chunks(), c)]
        self.assertEqual(flagged, [])

    def test_every_stated_number_has_to_be_printed_somewhere(self):
        page = [{"chunk_type": "text", "sheet_number": "X-1", "page_number": 1,
                 "text": "PUMP SCHEDULE 4 GPM 60 HZ"}]
        confirmed = {"chunk_type": "schedule", "sheet_number": "X-1", "page_number": 1,
                     "payload": {"source": "vision", "rows": [["P-1", "4", "60"]]}}
        self.assertFalse(pe.schedule_needs_verifying(page + [confirmed], confirmed))
        # One cell the page does not print is enough. A proportion would have to
        # be argued for every future sheet; a single incidental digit matching
        # out of thirty-seven is not confirmation.
        partial = {"chunk_type": "schedule", "sheet_number": "X-1", "page_number": 1,
                   "payload": {"source": "vision", "rows": [["P-1", "4", "99"]]}}
        self.assertTrue(pe.schedule_needs_verifying(page + [partial], partial))

    def test_the_models_own_reading_never_confirms_itself(self):
        # notes and legend on a scanned page are the model's words too. Only
        # the raw text chunk counts as printed text.
        notes = [{"chunk_type": "notes", "sheet_number": "X-2", "page_number": 1,
                  "text": "21 UNITS TOTAL"}]
        sched = {"chunk_type": "schedule", "sheet_number": "X-2", "page_number": 1,
                 "payload": {"source": "vision", "rows": [["PTAC-1", "21"]]}}
        self.assertTrue(pe.schedule_needs_verifying(notes + [sched], sched))


class MentionsLeadWithWhatStatesThings(unittest.TestCase):

    def test_a_schedule_outranks_a_floor_plans_text_layer(self):
        hits = [{"sheet": "A-100.00", "source": "text", "line": "x"},
                {"sheet": "A-500.00", "source": "schedule", "line": "y"},
                {"sheet": "A-300", "source": "legend", "line": "z"}]
        out = pe.format_not_stated(hits)
        self.assertIn("Mentioned on A-500.00, A-300, A-100.00.", out)


class WhatTheOtherQuestionsStillDo(unittest.TestCase):
    """The answers that were right on 2026-09-15 stay right."""

    def test_pile_type(self):
        a = answer("what type of piles are used")
        self.assertEqual(a["outcome"], "chunk_attribute")
        self.assertIn("HELICAL PILES", a["text"].upper())

    def test_a_count_nobody_printed_is_not_invented(self):
        a = answer("how many piles total")
        self.assertEqual(a["outcome"], "chunk_count_not_stated")
        self.assertIn("Not stated", a["text"])

    def test_roof_drains_point_at_the_roof_plan(self):
        # Never a number: the RD symbols are drawn, not tallied. The sheet it
        # names has to be a roof plan by its own title — the set has several,
        # and which one leads is not what this is protecting.
        a = answer("how many roof drains")
        self.assertEqual(a["outcome"], "chunk_count_not_stated")
        self.assertIn("count not stated", a["text"])
        roofs = {c.get("sheet_number") for c in chunks()
                 if "roof" in (c.get("sheet_title") or "").lower()}
        self.assertTrue(any(s and s in a["text"] for s in roofs),
                        f"no roof plan named: {a['text']}")

    def test_post_gauge(self):
        a = answer("what gauge are the metal studs")
        self.assertEqual(a["outcome"], "chunk_attribute")
        self.assertIn("20 GAUGE", a["text"].upper())

    def test_chase_walls(self):
        a = answer("are there chase walls")
        self.assertEqual(a["outcome"], "chunk_exists")
        self.assertTrue(a["text"].startswith("Yes"))


# ══════════════════════════════════════════════════════════════════════════
# The order, at the handler
# ══════════════════════════════════════════════════════════════════════════


class _Find:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, *a, **k):
        return self.doc


class _Db:
    def __init__(self, has_chunks):
        self.document_page_chunks = _Find({"_id": "c"} if has_chunks else None)


class TheTextIsSearchedBeforeAnyPicture(unittest.TestCase):

    def _run_one(self, chunk_rows):
        """The call log for one question that reaches the vision model."""
        log = []

        async def current_chunks(project_id):
            log.append("chunks")
            return chunk_rows

        async def retrieve(*a, **k):
            log.append("retrieval")
            return [{"sheet_number": "A-101.00", "sheet_title": "PLAN",
                     "page_jpeg_r2_key": "k1"},
                    {"sheet_number": "A-102.00", "sheet_title": "PLAN",
                     "page_jpeg_r2_key": "k2"}]

        async def fetch(rec):
            return b"jpeg"

        async def vqa(jpeg, question, sheet_number, sheet_title, project_id=None):
            log.append(f"vqa:{sheet_number}")
            return None                      # every sheet answers nothing

        async def send(group_id, text, reply_to=None, **kw):
            log.append("sent")

        async def no_cap(project_id):
            return False

        with mock.patch.object(server, "db", _Db(bool(chunk_rows))), \
                mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "_current_v3_chunks", current_chunks), \
                mock.patch.object(server, "_retrieve_plan_candidates", retrieve), \
                mock.patch.object(server, "_fetch_page_jpeg", fetch), \
                mock.patch.object(server, "_qwen_visual_qa", vqa), \
                mock.patch.object(server, "_vision_budget_exceeded", no_cap), \
                mock.patch.object(server, "send_whatsapp_message", send):
            asyncio.run(server._handle_plan_query(
                "p1", "g1", "structural pile",
                question="how many outlets in apartment 2A",
                parsed_override={"keywords": ["outlets"]},
                user_body="how many outlets in apartment 2A"))
        return log

    def test_the_index_is_read_before_the_model_is_called(self):
        log = self._run_one([])
        self.assertIn("chunks", log)
        self.assertTrue(any(s.startswith("vqa") for s in log))
        self.assertLess(log.index("chunks"),
                        min(i for i, s in enumerate(log) if s.startswith("vqa")),
                        f"a picture was looked at before the text was read: {log}")

    def test_a_timed_out_sheet_leaves_a_second_to_try(self):
        log = self._run_one([])
        self.assertEqual([s for s in log if s.startswith("vqa")],
                         ["vqa:A-101.00", "vqa:A-102.00"])

    def test_the_budget_is_what_a_person_will_wait_for(self):
        self.assertLessEqual(server.PLAN_VQA_TIMEOUT_SECONDS, 30.0)

    def test_no_caller_asks_whether_to_look_before_looking(self):
        import inspect
        src = inspect.getsource(server._answer_plan_from_chunks)
        # Statements only. The comments above the call explain the bug this
        # replaced and name the function that caused it.
        code = [ln.strip() for ln in src.split('"""', 2)[-1].splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse([ln for ln in code if "question_kind" in ln],
                         "classification decides the shape of the answer, not "
                         "whether the index is searched")
        self.assertIn("chunks = await _current_v3_chunks(project_id)", code)
        self.assertLess(code.index("chunks = await _current_v3_chunks(project_id)"),
                        next(i for i, ln in enumerate(code) if "return" in ln))


if __name__ == "__main__":
    unittest.main()
