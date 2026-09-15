"""Structured page extraction, version 3.

THE DEFECT THIS FILE EXISTS FOR. Index version 2 ran one Qwen call with ten
labelled sections and a 1500-token cap. On project 6a5f63bc147407d3261df2c7
the model looped on DIMENSIONS until the cap and every section after it came
back null: materials, code refs, detail refs and notes were empty on every
row. The index could not answer "stucco thickness" because the model never
wrote the word.

The first class below is that failure, reproduced with a fake model, and the
assertion that one runaway section can no longer take the others with it.
Everything else is the machinery that makes that true and keeps the data
honest: loop detection, JSON repair, caps, number verification, and
title-block boilerplate.

FIXTURES ARE SYNTHETIC. The shapes come from a real structural set, but no
real project's address, firm or sheet content is committed here.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import plan_extract as pe  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# A dimension loop shaped like the one diagnosed: the same value, comma
# separated, until the token budget ran out — never closing the JSON.
LOOP = '{"elements": [], "dimensions": [' + '"3\'-0\\"", ' * 400
GOOD_TITLE = json.dumps({
    "sheet_number": "S-100.00", "sheet_title": "FOUNDATION PLAN",
    "discipline": "Structural", "sheet_type": "plan", "floors": ["CELLAR"],
    "revision": "2", "revision_date": "01/12/2026",
    "contents_summary": "Foundation plan with pile layout and pile schedule.",
})
GOOD_NOTES = json.dumps({
    "notes": [{"number": "1", "text": "ALL PILES SHALL BE 12\" DIA HELICAL."},
              {"number": "2", "text": "PROVIDE 2 HR CHASE WALL AT SHAFT."}],
    "legend": [{"symbol": "P1", "meaning": "HELICAL PILE"}],
    "callouts": [{"text": "SEE DETAIL", "target_sheet": "S-500.00", "detail_number": "3"}],
})
GOOD_SCHED = json.dumps({"schedules": [{
    "name": "PILE SCHEDULE", "columns": ["MARK", "TYPE", "QTY"],
    "rows": [["P1", "HELICAL 12\"", "30"], ["P2", "HELICAL 16\"", "12"]],
}]})
PAGE_TEXT = (
    "FOUNDATION PLAN\nS-100.00\nPILE SCHEDULE\nMARK TYPE QTY\n"
    "P1 HELICAL 12\" 30\nP2 HELICAL 16\" 12\n"
    "1. ALL PILES SHALL BE 12\" DIA HELICAL.\n"
    "2. PROVIDE 2 HR CHASE WALL AT SHAFT.\n(4) ROOF DRAINS\n"
)


def _vlm(responses):
    """A fake model: section name, detected from the prompt, -> (content, finish)."""
    async def call(image_b64, prompt, max_tokens):
        for name, resp in responses.items():
            marker = {
                "title_block": '"sheet_number": str',
                "schedules": '{"schedules": [',
                "notes": '{"notes": [',
                "elements": '{"elements": [',
            }[name]
            if marker in prompt:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return ("{}", "stop")
    return call


class OneRunawaySectionNoLongerStarvesTheRest(unittest.TestCase):
    """The diagnosed failure. A loop until max_tokens used to null every field
    after it, because every field lived in the same response."""

    def setUp(self):
        self.out = _run(pe.extract_page(
            image_b64="x", page_text=PAGE_TEXT,
            vlm_call=_vlm({
                "title_block": (GOOD_TITLE, "stop"),
                "schedules": (GOOD_SCHED, "stop"),
                "notes": (GOOD_NOTES, "stop"),
                "elements": (LOOP, "length"),
            })))

    def test_the_sections_after_the_loop_still_have_their_data(self):
        f = self.out["fields"]
        self.assertEqual(f["sheet_number"], "S-100.00")
        self.assertEqual(len(f["notes"]), 2)
        self.assertEqual(f["schedules"][0]["name"], "PILE SCHEDULE")
        self.assertEqual(f["legend"][0]["symbol"], "P1")

    def test_the_looping_section_is_flagged_not_trusted(self):
        flags = self.out["flags"]["elements"]
        self.assertIn("hit_max_tokens", flags)
        self.assertIn("repetition_truncated", flags)

    def test_the_loop_is_cut_to_one_value_not_four_hundred(self):
        self.assertLessEqual(len(self.out["fields"]["dimensions"]), 1)

    def test_the_other_sections_carry_no_flags_from_it(self):
        for name in ("title_block", "schedules", "notes"):
            with self.subTest(section=name):
                self.assertNotIn("repetition_truncated", self.out["flags"][name])

    def test_a_section_whose_call_raises_costs_only_itself(self):
        out = _run(pe.extract_page(
            image_b64="x", page_text=PAGE_TEXT,
            vlm_call=_vlm({
                "title_block": (GOOD_TITLE, "stop"),
                "schedules": RuntimeError("502"),
                "notes": (GOOD_NOTES, "stop"),
                "elements": ('{"elements": []}', "stop"),
            })))
        self.assertEqual(out["flags"]["schedules"], ["call_failed:RuntimeError"])
        self.assertEqual(len(out["fields"]["notes"]), 2)
        self.assertEqual(out["fields"]["sheet_number"], "S-100.00")

    def test_every_section_is_its_own_call_with_its_own_budget(self):
        self.assertEqual(set(pe.SECTIONS), set(pe.SECTION_MAX_TOKENS))
        seen = []

        async def call(image_b64, prompt, max_tokens):
            seen.append(max_tokens)
            return ("{}", "stop")

        _run(pe.extract_page(image_b64="x", page_text="", vlm_call=call))
        self.assertEqual(len(seen), len(pe.SECTIONS))
        self.assertEqual(sorted(seen), sorted(pe.SECTION_MAX_TOKENS.values()))


class ALoopIsDetectedAndARealRepeatIsNot(unittest.TestCase):

    def test_a_dimension_loop_is_cut_at_its_first_repeat(self):
        text = '"3\'-0\\"", ' * 300
        cut, looped = pe.detect_repetition(text)
        self.assertTrue(looped)
        self.assertLess(len(cut), 20)

    def test_a_repeated_line_is_a_loop(self):
        cut, looped = pe.detect_repetition("PROVIDE BLOCKING\n" * 50)
        self.assertTrue(looped)
        self.assertEqual(cut.strip(), "PROVIDE BLOCKING")

    def test_a_repeating_multi_line_block_is_a_loop(self):
        cut, looped = pe.detect_repetition("A-101\nA-102\nA-103\n" * 20)
        self.assertTrue(looped)
        self.assertEqual(cut.split(), ["A-101", "A-102", "A-103"])

    def test_a_loop_with_no_separators_is_still_caught(self):
        _cut, looped = pe.detect_repetition("HELICALPILE12IN" * 30)
        self.assertTrue(looped)

    def test_five_real_repeats_are_kept(self):
        """A sheet can list one value a handful of times legitimately. A
        threshold that eats real repeats corrupts the data it protects."""
        text = ", ".join(['3\'-0"'] * 5)
        cut, looped = pe.detect_repetition(text)
        self.assertFalse(looped)
        self.assertEqual(cut, text)

    def test_ordinary_text_is_untouched(self):
        text = "1. ALL PILES SHALL BE HELICAL.\n2. PROVIDE CHASE WALL.\n3. SEE S-500."
        self.assertEqual(pe.detect_repetition(text), (text, False))

    def test_the_text_before_the_loop_survives(self):
        text = "PILE SCHEDULE\nP1 HELICAL\n" + "P2 HELICAL\n" * 40
        cut, looped = pe.detect_repetition(text)
        self.assertTrue(looped)
        self.assertIn("PILE SCHEDULE", cut)
        self.assertIn("P1 HELICAL", cut)


class ATruncatedResponseStillYieldsItsCompleteValues(unittest.TestCase):

    def test_fenced_json(self):
        self.assertEqual(pe.parse_json_loose('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_around_the_object(self):
        self.assertEqual(pe.parse_json_loose('Here you go: {"a": 1} hope that helps'), {"a": 1})

    def test_cut_off_mid_array_keeps_the_finished_items(self):
        obj = pe.parse_json_loose('{"materials": ["7/8\\" STUCCO", "18 GA POST", "2 HR RAT')
        self.assertEqual(obj, {"materials": ["7/8\" STUCCO", "18 GA POST"]})

    def test_a_dangling_key_is_dropped_not_guessed(self):
        obj = pe.parse_json_loose('{"sheet_number": "S-100.00", "sheet_title": "FOUND')
        self.assertEqual(obj, {"sheet_number": "S-100.00"})

    def test_garbage_is_None(self):
        for bad in ("", "no json here", "[1, 2, 3]", None):
            with self.subTest(bad=bad):
                self.assertIsNone(pe.parse_json_loose(bad))

    def test_unparseable_output_is_flagged(self):
        out = _run(pe.extract_page(
            image_b64="x", page_text=PAGE_TEXT,
            vlm_call=_vlm({"notes": ("I cannot read this page.", "stop")})))
        self.assertIn("unparseable", out["flags"]["notes"])


class EveryFieldHasACeiling(unittest.TestCase):

    def test_an_over_long_summary_is_capped_and_flagged(self):
        fields, flags = pe.validate_section("title_block", {
            "contents_summary": "Foundation plan showing pile caps. " * 60})
        self.assertLessEqual(len(fields["contents_summary"]), 900)
        self.assertTrue(any(f.startswith("contents_summary:") for f in flags))

    def test_a_list_past_its_maximum_is_capped_and_flagged(self):
        fields, flags = pe.validate_section("elements", {
            "dimensions": [f"{i}'-0\"" for i in range(500)]})
        self.assertEqual(len(fields["dimensions"]), 200)
        self.assertIn("dimensions:list_capped", flags)

    def test_a_looping_list_is_collapsed_and_flagged(self):
        fields, flags = pe.validate_section("elements", {
            "materials": ["18 GA POST"] * 40 + ["7/8\" STUCCO"]})
        self.assertEqual(fields["materials"], ["18 GA POST", "7/8\" STUCCO"])
        self.assertIn("materials:repetition_collapsed", flags)

    def test_an_unknown_sheet_type_becomes_other_and_says_so(self):
        fields, flags = pe.validate_section("title_block", {"sheet_type": "Blueprint"})
        self.assertEqual(fields["sheet_type"], "other")
        self.assertTrue(any("sheet_type:unknown_value" in f for f in flags))

    def test_a_count_must_be_a_whole_number(self):
        fields, _ = pe.validate_section("elements", {"elements": [
            {"name": "PILE", "count_if_stated": "42"},
            {"name": "DRAIN", "count_if_stated": 4.5},
            {"name": "POST", "count_if_stated": "about 20"},
            {"name": "PTAC", "count_if_stated": True},
        ]})
        counts = {e["name"]: e["count_if_stated"] for e in fields["elements"]}
        self.assertEqual(counts, {"PILE": 42, "DRAIN": None, "POST": None, "PTAC": None})

    def test_merge_always_carries_every_field(self):
        merged = pe.merge_sections({"notes": {"notes": [{"number": "1", "text": "X"}]}})
        self.assertEqual(set(merged), set(pe.EMPTY_FIELDS))


class ACountIsOnlyACountIfItIsPrinted(unittest.TestCase):
    """A vision model counting drain symbols by eye is exactly the guess this
    pipeline exists to stop presenting as an answer."""

    def _elements(self, *els):
        fields = pe.merge_sections({"elements": {"elements": list(els)}})
        return fields

    def test_a_count_in_the_page_text_is_verified(self):
        f = self._elements({"name": "ROOF DRAIN", "count_if_stated": 4})
        pe.verify_numbers(f, PAGE_TEXT)
        self.assertTrue(f["elements"][0]["count_verified"])

    def test_a_count_nowhere_in_the_page_text_is_not(self):
        f = self._elements({"name": "ROOF DRAIN", "count_if_stated": 17})
        flags = pe.verify_numbers(f, PAGE_TEXT)
        self.assertFalse(f["elements"][0]["count_verified"])
        self.assertIn("counts_not_in_page_text:1", flags)

    def test_a_number_inside_a_bigger_number_does_not_count(self):
        """"4" must not verify against "42" or "4.5"."""
        self.assertFalse(pe.number_in_text(4, "provide 42 piles and 4.5 ft"))
        self.assertTrue(pe.number_in_text(4, "(4) roof drains"))

    def test_with_no_page_text_nothing_is_claimed_either_way(self):
        f = self._elements({"name": "PILE", "count_if_stated": 42})
        flags = pe.verify_numbers(f, "")
        self.assertIsNone(f["elements"][0]["count_verified"])
        self.assertIn("numbers_unverifiable:no_page_text", flags)

    def test_an_unverified_count_is_never_answered(self):
        chunks = [{"chunk_type": "elements", "sheet_number": "P-100.00", "payload": [
            {"name": "ROOF DRAIN", "count_if_stated": 17, "count_verified": False},
            {"name": "ROOF DRAIN", "count_if_stated": 4, "count_verified": True},
        ]}]
        hits = pe.answer_count(chunks, ["roof", "drains"])
        self.assertEqual([h["count"] for h in hits], [4])

    def test_curly_quotes_do_not_break_dimension_matching(self):
        f = pe.merge_sections({"elements": {"dimensions": ['7/8"']}})
        flags = pe.verify_numbers(f, "STUCCO 7/8″ THICK")
        self.assertFalse(any(x.startswith("dimensions_not_in_page_text") for x in flags))


class TheTitleBlockIsNotContent(unittest.TestCase):
    """Measured on a real 17-page structural set: "GAUGE" appeared on every
    page because the engineering firm's name contains it. A search for "post
    gauge" would match all seventeen sheets for a reason unrelated to posts."""

    PAGES = [
        f"ACME GAUGE ENGINEERING\n100 MAIN ST\nS-{n}00.00\n" + body
        for n, body in enumerate([
            "FOUNDATION PLAN\nPILE CAP",
            "FRAMING PLAN\nBEAM B1",
            "WALL SECTIONS\n18 GA STEEL POST AT 16\" OC",
            "ROOF PLAN\n(4) ROOF DRAINS",
            "DETAILS\nCHASE WALL",
        ], start=1)
    ]

    def test_lines_on_most_pages_are_boilerplate(self):
        lines = pe.boilerplate_lines(self.PAGES)
        self.assertIn("acme gauge engineering", lines)
        self.assertIn("100 main st", lines)

    def test_content_on_one_page_is_not(self):
        lines = pe.boilerplate_lines(self.PAGES)
        self.assertNotIn('18 ga steel post at 16" oc', lines)

    def test_after_stripping_gauge_matches_one_page_not_five(self):
        lines = pe.boilerplate_lines(self.PAGES)
        hits = [p for p in self.PAGES if "gauge" in pe.strip_boilerplate(p, lines).lower()]
        self.assertEqual(hits, [])
        hits_ga = [p for p in self.PAGES if " ga " in pe.strip_boilerplate(p, lines).lower()]
        self.assertEqual(len(hits_ga), 1)

    def test_a_short_file_has_no_boilerplate(self):
        """Two pages cannot tell a title block from content they share."""
        self.assertEqual(pe.boilerplate_lines(self.PAGES[:2]), frozenset())

    def test_the_prompt_text_is_stripped_but_verification_is_not(self):
        """Numbers printed in the title block — a revision date — still count
        as printed."""
        seen = {}

        async def call(image_b64, prompt, max_tokens):
            seen.setdefault("prompt", prompt)
            return ("{}", "stop")

        lines = pe.boilerplate_lines(self.PAGES)
        _run(pe.extract_page(image_b64="x", page_text=self.PAGES[0],
                             vlm_call=call, boilerplate=lines))
        self.assertNotIn("ACME GAUGE ENGINEERING", seen["prompt"])
        self.assertIn("FOUNDATION PLAN", seen["prompt"])


class ChunksAreTheUnitOfRetrieval(unittest.TestCase):

    def setUp(self):
        self.fields = pe.merge_sections({
            "schedules": json.loads(GOOD_SCHED),
            "notes": json.loads(GOOD_NOTES),
            "elements": {"elements": [{"name": "ROOF DRAIN", "count_if_stated": 4,
                                       "location_hint": "roof plan"}],
                         "materials": ["7/8\" STUCCO"]},
        })

    def test_each_schedule_is_its_own_chunk(self):
        kinds = [c["chunk_type"] for c in pe.build_chunks(self.fields)]
        self.assertEqual(kinds.count("schedule"), 1)
        for k in ("notes", "legend", "callouts", "elements", "specs"):
            with self.subTest(kind=k):
                self.assertIn(k, kinds)

    def test_notes_are_split_into_bounded_blocks(self):
        many = pe.merge_sections({"notes": {"notes": [
            {"number": str(i), "text": "PROVIDE FIRESTOPPING AT ALL PENETRATIONS. " * 8}
            for i in range(20)]}})
        blocks = [c for c in pe.build_chunks(many) if c["chunk_type"] == "notes"]
        self.assertGreater(len(blocks), 1)
        for b in blocks:
            with self.subTest(ordinal=b["ordinal"]):
                self.assertLessEqual(len(b["text"]), pe.NOTE_BLOCK_CHARS + 400)

    def test_boilerplate_is_stripped_from_chunk_text(self):
        f = pe.merge_sections({"notes": {"notes": [
            {"number": None, "text": "ACME GAUGE ENGINEERING"},
            {"number": "1", "text": "18 GA POST"}]}})
        chunks = pe.build_chunks(f, frozenset({"acme gauge engineering"}))
        texts = [c["text"] for c in chunks]
        self.assertEqual(texts, ["1. 18 GA POST"])


class CountsAndExistenceAnswerWithoutAVisionModel(unittest.TestCase):

    def _chunks(self, fields, sheet="S-100.00"):
        pe.verify_numbers(fields, PAGE_TEXT)
        chunks = pe.build_chunks(fields)
        for c in chunks:
            c["sheet_number"] = sheet
        return chunks

    def test_a_schedule_with_a_quantity_column_is_summed(self):
        f = pe.merge_sections({"schedules": json.loads(GOOD_SCHED)})
        hits = pe.answer_count(self._chunks(f), ["piles"])
        self.assertEqual(hits[0]["count"], 42)
        self.assertEqual(hits[0]["source"], "schedule_qty")
        self.assertEqual(hits[0]["sheet"], "S-100.00")

    def test_a_schedule_without_one_reports_rows_as_rows(self):
        """Three pile types listed is not three piles, and must not be
        reported as if it were."""
        f = pe.merge_sections({"schedules": {"schedules": [{
            "name": "PILE SCHEDULE", "columns": ["MARK", "TYPE"],
            "rows": [["P1", "HELICAL"], ["P2", "HELICAL"], ["P3", "DRIVEN"]]}]}})
        hits = pe.answer_count(self._chunks(f), ["pile"])
        self.assertEqual(hits[0]["source"], "schedule_rows")
        answer = pe.format_count_answer("piles", hits)
        self.assertIn("lists 3 row(s)", answer)

    def test_a_printed_element_count_is_answered_with_its_sheet(self):
        f = pe.merge_sections({"elements": {"elements": [
            {"name": "ROOF DRAIN", "count_if_stated": 4, "location_hint": "roof plan"}]}})
        hits = pe.answer_count(self._chunks(f, sheet="P-100.00"), ["roof", "drains"])
        self.assertEqual((hits[0]["sheet"], hits[0]["count"]), ("P-100.00", 4))

    def test_nothing_printed_is_no_answer(self):
        f = pe.merge_sections({"elements": {"elements": [{"name": "PTAC UNIT"}]}})
        self.assertEqual(pe.answer_count(self._chunks(f), ["ptac"]), [])
        self.assertIsNone(pe.format_count_answer("PTAC units", []))

    def test_existence_is_found_in_notes_with_the_line_that_matched(self):
        f = pe.merge_sections({"notes": json.loads(GOOD_NOTES)})
        hits = pe.answer_existence(self._chunks(f), ["chase", "walls"])
        self.assertTrue(hits)
        self.assertIn("CHASE WALL", hits[0]["line"])
        self.assertIn("S-100.00", pe.format_existence_answer("chase walls", hits))

    def test_every_term_must_match(self):
        f = pe.merge_sections({"notes": json.loads(GOOD_NOTES)})
        self.assertEqual(pe.answer_existence(self._chunks(f), ["roof", "chase"]), [])


class VersionTwoReadersKeepWorking(unittest.TestCase):
    """Thirteen functions read document_page_index as v2 strings."""

    def test_the_v2_string_fields_are_filled(self):
        fields = pe.merge_sections({
            "title_block": json.loads(GOOD_TITLE),
            "notes": {"notes": [{"number": "1", "text": "PER LL 126/21 AND BC 1705."}],
                      "callouts": [{"text": "SEE", "target_sheet": "S-500.00",
                                    "detail_number": "3"}]},
            "elements": {"materials": ["7/8\" STUCCO", "18 GA POST"],
                         "dimensions": ["12\""]},
        })
        legacy = pe.legacy_fields(fields)
        self.assertEqual(legacy["materials"], '7/8" STUCCO; 18 GA POST')
        self.assertIn("LL 126/21", legacy["code_refs"])
        self.assertIn("BC 1705", legacy["code_refs"])
        self.assertIn("S-500.00", legacy["detail_refs"])
        self.assertIn("PER LL 126/21", legacy["notes"])
        self.assertEqual(legacy["summary"], "Foundation plan with pile layout and pile schedule.")
        self.assertIn("STUCCO", legacy["keywords"])


class AttributeQuestionsFindTheLineThatCarriesTheValue(unittest.TestCase):
    """'stucco thickness', 'post gauge', 'pile type' — the three acceptance
    questions that are neither a count nor a yes/no."""

    CHUNKS = [
        {"chunk_type": "specs", "sheet_number": "A-500.00",
         "text": 'STUCCO SYSTEM PER SPEC\n7/8" CEMENT STUCCO ON LATH\n3 5/8" 20 GA STUD'},
        {"chunk_type": "notes", "sheet_number": "S-001.00",
         "text": "1. POSTS SHALL BE 16 GA COLD FORMED STEEL.\n2. PILES SHALL BE TYPE HP 12x53."},
        {"chunk_type": "notes", "sheet_number": "S-001.00",
         "text": "3. POST INSTALLATION PER MANUFACTURER."},
    ]

    def test_the_kind_of_each_acceptance_question(self):
        cases = {
            "how many piles": ("count", None),
            "roof drain count": ("count", None),
            "PTAC count": ("count", None),
            "pile type": ("attribute", "type"),
            "stucco thickness": ("attribute", "thickness"),
            "post gauge": ("attribute", "gauge"),
            "are there chase walls": ("exists", None),
            "chase walls?": (None, None),
        }
        for q, want in cases.items():
            with self.subTest(q=q):
                self.assertEqual(pe.question_kind(q), want)

    def test_the_attribute_word_is_not_a_search_term(self):
        self.assertEqual(pe.question_terms("stucco thickness"), ["stucco"])
        self.assertEqual(pe.question_terms("what gauge are the posts"), ["posts"])
        self.assertEqual(pe.question_terms("x", ["pile type"]), ["pile"])

    def test_the_line_with_a_value_wins_and_the_bare_mention_does_not(self):
        hits = pe.answer_attribute(self.CHUNKS, ["stucco"], "thickness")
        self.assertEqual([h["line"] for h in hits], ['7/8" CEMENT STUCCO ON LATH'])
        self.assertEqual(hits[0]["sheet"], "A-500.00")

    def test_gauge_and_type(self):
        gauge = pe.answer_attribute(self.CHUNKS, ["posts"], "gauge")
        self.assertEqual(len(gauge), 1)
        self.assertIn("16 GA", gauge[0]["line"])
        kind = pe.answer_attribute(self.CHUNKS, ["piles"], "type")
        self.assertIn("HP 12x53", kind[0]["line"])

    def test_a_mention_without_a_value_is_no_answer(self):
        chunks = [{"chunk_type": "notes", "sheet_number": "A-1",
                   "text": "STUCCO SYSTEM PER SPEC"}]
        self.assertEqual(pe.answer_attribute(chunks, ["stucco"], "thickness"), [])
        self.assertIsNone(pe.format_attribute_answer("stucco", "thickness", []))

    def test_not_stated_names_where_it_is_mentioned(self):
        self.assertEqual(
            pe.format_not_stated([{"sheet": "S-100"}, {"sheet": "S-100"}, {"sheet": "S-101"}]),
            "Not stated on the indexed drawings. Mentioned on S-100, S-101.")
        self.assertEqual(pe.format_not_stated([]), "Not stated on the indexed drawings.")


class AVectorPageMakesOneCall(unittest.TestCase):

    LAYOUT = {
        "page_number": 2, "width": 2592, "height": 1728, "fractions_rebuilt": 1,
        "fractions_unverified": ["7"], "tables": [],
        "blocks": [
            {"bbox": [100, 100, 900, 400], "lines": ["GENERAL CONDITIONS:"], "text": "GENERAL CONDITIONS:"},
            {"bbox": [100, 400, 900, 800], "lines": ["1.", "ALL PILES SHALL BE HELICAL PILES."],
             "text": "1.\nALL PILES SHALL BE HELICAL PILES."},
            {"bbox": [100, 1600, 900, 1700], "lines": ["2S-001.00", "GENERAL NOTES"],
             "text": "2S-001.00\nGENERAL NOTES"},
        ],
    }
    LAYOUT["text"] = "\n".join(b["text"] for b in LAYOUT["blocks"])

    def test_one_call_and_the_sheet_number_is_checked(self):
        prompts = []

        async def vlm(image_b64, prompt, max_tokens):
            prompts.append(prompt)
            return (json.dumps({"sheet_number": "2", "sheet_title": "GENERAL NOTES",
                                "sheet_type": "notes", "revision": "S-001.00",
                                "contents_summary": "General notes."}), "stop")

        out = _run(pe.extract_vector_page(image_b64="x", layout=self.LAYOUT, vlm_call=vlm))
        self.assertEqual(len(prompts), 1)
        self.assertEqual(out["vlm_calls"], 1)
        f = out["fields"]
        self.assertEqual(f["sheet_number"], "S-001.00")
        self.assertIn("sheet_number_corrected", out["flags"]["title_block"])
        self.assertIsNone(f["revision"], "a sheet id is not a revision")
        self.assertEqual(f["notes"][0]["text"], "ALL PILES SHALL BE HELICAL PILES.")
        self.assertEqual(f["dimensions_unverified"], ["7"])
        self.assertIn("SHEET IDS PRINTED IN THE TITLE BLOCK: S-001.00", prompts[0])
        self.assertNotIn("ALL PILES SHALL BE", prompts[0], "notes are chunked, not prompted")

    def test_a_revision_equal_to_the_drawing_list_index_is_cleared(self):
        async def vlm(image_b64, prompt, max_tokens):
            return (json.dumps({"sheet_number": "S-001.00", "revision": "2"}), "stop")

        out = _run(pe.extract_vector_page(image_b64="x", layout=self.LAYOUT, vlm_call=vlm,
                                          drawing_index={"S-001.00": 2}))
        self.assertIsNone(out["fields"]["revision"])
        self.assertIn("revision_was_drawing_list_index", out["flags"]["title_block"])

    def test_a_revision_that_is_not_the_index_is_kept(self):
        async def vlm(image_b64, prompt, max_tokens):
            return (json.dumps({"sheet_number": "S-001.00", "revision": "4"}), "stop")

        out = _run(pe.extract_vector_page(image_b64="x", layout=self.LAYOUT, vlm_call=vlm,
                                          drawing_index={"S-001.00": 2}))
        self.assertEqual(out["fields"]["revision"], "4")

    def test_a_failed_call_still_yields_the_text(self):
        async def vlm(*a):
            raise TimeoutError()

        out = _run(pe.extract_vector_page(image_b64="x", layout=self.LAYOUT, vlm_call=vlm))
        self.assertEqual(out["fields"]["sheet_number"], "S-001.00")
        self.assertEqual(len(out["fields"]["notes"]), 1)
        self.assertIn("call_failed:TimeoutError", out["flags"]["title_block"])


class TagCountsAreNeverATotal(unittest.TestCase):

    CHUNKS = [
        {"chunk_type": "tag_counts", "sheet_number": "A-100.00",
         "payload": [{"tag": "PTAC", "count": 10, "source": "text-layer tag count"}]},
        {"chunk_type": "tag_counts", "sheet_number": "A-201.00",
         "payload": [{"tag": "PTAC", "count": 8, "source": "text-layer tag count"}]},
        {"chunk_type": "tag_counts", "sheet_number": "A-102.00",
         "payload": [{"tag": "PTAC", "count": 6, "source": "text-layer tag count"}]},
    ]

    def test_the_wording(self):
        ans = pe.answer_question(self.CHUNKS, "how many PTAC units")
        self.assertEqual(ans["outcome"], "chunk_tag_count")
        self.assertEqual(ans["text"],
                         "PTAC tag appears 24 times on A-100.00..A-201.00 (not a stated total).")

    def test_a_printed_count_wins_over_a_tag_count(self):
        chunks = self.CHUNKS + [{"chunk_type": "elements", "sheet_number": "M-001.00", "payload": [
            {"name": "PTAC UNITS", "count_if_stated": 22, "count_verified": True}]}]
        ans = pe.answer_question(chunks, "how many PTAC units")
        self.assertEqual(ans["outcome"], "chunk_count")
        self.assertIn("M-001.00: 22", ans["text"])

    def test_a_synonym_finds_the_tag(self):
        chunks = [{"chunk_type": "tag_counts", "sheet_number": "P-104.00",
                   "payload": [{"tag": "RD", "count": 4, "source": "text-layer tag count"}]}]
        ans = pe.answer_question(chunks, "how many roof drains")
        self.assertEqual(ans["text"], "RD tag appears 4 times on P-104.00 (not a stated total).")


class AValueBelongsToTheNounNextToIt(unittest.TestCase):
    """Measured on A-100.00 and A-500.00."""

    def test_a_value_owned_by_concrete_is_not_a_stucco_thickness(self):
        chunks = [{"chunk_type": "text", "sheet_number": "A-100.00",
                   "text": '6" STUD, R19 BATT-R11.5 RIGID INSU.,\nSTUCCO FINISH 12" CONCRETE'}]
        self.assertEqual(pe.answer_attribute(chunks, ["stucco"], "thickness"), [])

    def test_a_value_across_another_assembly_is_not_it_either(self):
        chunks = [{"chunk_type": "schedule", "sheet_number": "A-500.00",
                   "text": 'STUCCO FINISH BOARD 1 LAYERS OF 5/8" EXTERIOR DENS GLASS BOARD'}]
        self.assertEqual(pe.answer_attribute(chunks, ["stucco"], "thickness"), [])

    def test_a_row_count_needs_a_schedule_named_for_the_thing(self):
        chunks = [{"chunk_type": "schedule", "sheet_number": "S-001.00", "text": "x", "payload": {
            "name": "SPECIAL INSPECTION CATEGORIES", "columns": ["", "CATEGORY", "CODE"],
            "rows": [["", "HELICAL PILES", "BC 1705.8"], ["", "WELDING", "BC 1705.2"]]}}]
        self.assertEqual(pe.answer_count(chunks, ["piles"]), [])

    def test_the_value_on_the_next_line_of_the_same_label(self):
        chunks = [{"chunk_type": "text", "sheet_number": "A-500.00",
                   "text": '3 1/2" METAL STUD 16"\nO.C. 20 GAUGE MIN.'}]
        hits = pe.answer_attribute(chunks, ["stud"], "gauge")
        self.assertEqual(hits[0]["line"], '3 1/2" METAL STUD 16" O.C. 20 GAUGE MIN.')


class ItReachesNeitherADatabaseNorTheNetwork(unittest.TestCase):

    def test_no_driver_no_server_no_http(self):
        src = (Path(__file__).resolve().parents[1] / "lib" / "plan_extract.py").read_text(encoding="utf-8")
        for banned in ("import motor", "from motor", "import server", "from server",
                       "import httpx", "import requests", "boto3"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
