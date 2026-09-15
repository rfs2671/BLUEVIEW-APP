"""Live test, 2026-09-15 17:05-17:10, 588 Thomas S Boyland St.

One class per reported defect, each pinned to what the group actually saw:
  1. "show me s-001" sent S-002 and M-001
  2. a bare "Show me" after a not-found sent S-402
  3. "helical piles" explained in six sentences
  5. "what type of AC units" found nothing; the M set says PTAC
  6. "stucco thickness" quoted a detail title and its scale
  8. roof drains: "RD tag appears 1 time on SP-003.00" — the engineer's address

No network, no model, no Mongo: the database is a small in-memory stand-in.
"""

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib import plan_extract as pe  # noqa: E402
from lib import plan_text as pt  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


_MISSING = object()


def _get(doc, key):
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _match(doc, q):
    for key, cond in (q or {}).items():
        v = _get(doc, key)
        v = None if v is _MISSING else v
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and v not in arg:
                    return False
                if op == "$nin" and v in arg:
                    return False
                if op == "$ne" and v == arg:
                    return False
                if op == "$regex" and not (isinstance(v, str) and re.search(
                        arg, v, re.I if "i" in (cond.get("$options") or "") else 0)):
                    return False
        elif v != cond:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n=None):
        return [dict(r) for r in self.rows]


class _Coll:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if _match(r, q)])


class _Db:
    def __init__(self, files, pages):
        self.project_files = _Coll(files)
        self.document_page_index = _Coll(pages)


FILES = [{"_id": "st", "project_id": "p1"}, {"_id": "mh", "project_id": "p1"}]
PAGES = [
    {"_id": "s001", "project_id": "p1", "file_id": "st", "sheet_number": "S-001.00",
     "is_spec_page": True, "sheet_title": None, "page_jpeg_r2_key": "", "superseded_by": None},
    {"_id": "s002", "project_id": "p1", "file_id": "st", "sheet_number": "S-002.00",
     "is_spec_page": False, "sheet_title": "GENERAL NOTES", "page_jpeg_r2_key": "k2",
     "superseded_by": None},
    {"_id": "m001", "project_id": "p1", "file_id": "mh", "sheet_number": "M-001.00",
     "is_spec_page": False, "sheet_title": "HVAC NOTES", "page_jpeg_r2_key": "k3",
     "superseded_by": None},
    {"_id": "s402", "project_id": "p1", "file_id": "st", "sheet_number": "S-402.00",
     "is_spec_page": False, "sheet_title": "TYPICAL CFS DETAILS", "page_jpeg_r2_key": "k4",
     "superseded_by": None},
]


class _PlanQuery:
    """Runs _handle_plan_query with everything outbound captured."""

    def _query(self, body, parsed):
        sent, images = [], []

        async def send(group_id, text, reply_to=None, **kw):
            sent.append(text)

        async def send_image(group_id, rec, caption):
            images.append(rec.get("sheet_number"))
            return True

        async def never(*a, **k):
            raise AssertionError("a named sheet must not fall through to the search")

        async def no_cap(project_id):
            return False

        async def no_chunks(*a, **k):
            return True, None

        db = _Db(FILES, PAGES)
        with mock.patch.object(server, "db", db), \
                mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "send_whatsapp_message", send), \
                mock.patch.object(server, "_send_plan_image", send_image), \
                mock.patch.object(server, "_retrieve_plan_candidates", never), \
                mock.patch.object(server, "_vision_budget_exceeded", no_cap), \
                mock.patch.object(server, "_answer_plan_from_chunks", no_chunks):
            _run(server._handle_plan_query("p1", "g1", parsed.get("synth", "plan"),
                                           parsed_override=parsed, user_body=body))
        return sent, images


class D1_ASheetIdIsAnExactLookup(unittest.TestCase, _PlanQuery):

    def test_show_me_s_001_sends_no_neighbours(self):
        sent, images = self._query("Show me s-001", {"sheet_number": "S-001.00", "synth": "S-001.00"})
        self.assertEqual(images, [], "S-002 and M-001 were sent live")
        self.assertIn("S-001.00 is a notes sheet — indexed, can't render yet.", sent)

    def test_a_sheet_not_in_the_index_says_so(self):
        sent, images = self._query("show me S-100", {"sheet_number": "S-100", "synth": "S-100"})
        self.assertEqual(images, [])
        self.assertIn("S-100 isn't in the indexed drawings.", sent)

    def test_a_named_sheet_with_an_image_is_sent_alone(self):
        sent, images = self._query("show me S-002", {"sheet_number": "S-002", "synth": "S-002"})
        self.assertEqual(images, ["S-002.00"])

    def test_the_sheet_id_in_a_message(self):
        cases = {"Show me s-001": "S-001", "pull up SSP-013": "SSP-013", "show me S102": "S-102",
                 "show me the roof plan": None, "on a 4 story building": None,
                 "show me RCP-001.00": "RCP-001.00"}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(server._requested_sheet_id(text), want)


class D2_ABareShowMeShowsNothing(unittest.TestCase, _PlanQuery):

    def test_show_me_with_the_agents_guess_sends_nothing(self):
        sent, images = self._query("Show me", {"sheet_number": "S-402.00", "synth": "S-402.00"})
        self.assertEqual(images, [], "S-402 was sent live")
        self.assertEqual(sent, ["Nothing to show for that — which sheet?"])

    def test_what_counts_as_bare(self):
        for body in ("Show me", "@153906327875707 show me", "show me that", "pull up",
                     "show me please!"):
            with self.subTest(body=body):
                self.assertTrue(server._is_bare_show_request(body))
        for body in ("show me s-001", "show me the roof drains", "what is shown on A-105",
                     "", None):
            with self.subTest(body=body):
                self.assertFalse(server._is_bare_show_request(body))


class D3_GeneralKnowledgeIsTwoSentences(unittest.TestCase):

    LONG = ("Helical piles are a type of deep foundation system. They consist of steel "
            "shafts with helical plates. They are screwed into the ground. Load is carried "
            "by the plates. They install fast. They are common on tight urban lots.")

    def test_the_cap(self):
        self.assertEqual(server._cap_sentences(self.LONG, 2),
                         "Helical piles are a type of deep foundation system. They consist "
                         "of steel shafts with helical plates.")
        self.assertEqual(server._cap_sentences("One. Two.", 2), "One. Two.")

    def test_only_a_reply_with_no_tool_is_cut(self):
        import inspect
        src = inspect.getsource(server._run_group_agent)
        i = src.index("if not tool_calls:")
        block = src[i:src.index("used_tool = True", i)]
        self.assertIn("if not used_tool:", block)
        self.assertIn("_cap_sentences(stripped, AGENT_KNOWLEDGE_MAX_SENTENCES)", block)
        self.assertIn("two sentences at most", server._AGENT_STANCE)


class D5_WhatAPersonSaysMatchesWhatTheDrawingPrints(unittest.TestCase):

    CHUNKS = [
        {"chunk_type": "text", "sheet_number": "M-200.00", "sheet_title": "HVAC SCHEDULES",
         "text": "PTAC UNIT TYPE: THROUGH-WALL, AMANA"},
        {"chunk_type": "text", "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN",
         "text": "CROWN MOLDING IN PLACE\nOPEN SPACE"},
    ]

    def test_the_subject_of_the_question(self):
        self.assertEqual(pe.question_terms("What type of AC units in this project?"), ["ac"])
        self.assertEqual(pe.question_terms("what kind of air conditioning"), ["ac"])
        self.assertEqual(pe.question_terms("how many PTAC units"), ["ptac"])

    def test_ac_finds_ptac_and_never_matches_place_or_space(self):
        ans = pe.answer_question(self.CHUNKS, "What type of AC units in this project?")
        self.assertEqual(ans["outcome"], "chunk_attribute")
        self.assertIn("M-200.00: PTAC UNIT TYPE", ans["text"])
        self.assertNotIn("A-100.00", ans["text"])


class D6_AHeadingIsNotAValue(unittest.TestCase):

    CHUNKS = [{"chunk_type": "text", "sheet_number": "A-302.00", "sheet_title": "SECTION DETAILS",
               "text": "1 FOUNDATION DETAIL STUCCO (UNEXCEVATED) Scale: 3/4\"=1'-0\"\n"
                       "R-11.5 EPS INSULATION WITH STUCCO FINISH"}]

    def test_the_regression_stucco_thickness(self):
        ans = pe.answer_question(self.CHUNKS, "What's the stucco thickness?")
        self.assertEqual(ans["outcome"], "chunk_attribute_not_stated")
        self.assertEqual(ans["text"], "Not stated on the indexed drawings. Mentioned on A-302.00.")
        self.assertNotIn("Scale", ans["text"])

    def test_a_scale_anywhere_on_a_line_is_not_a_thickness(self):
        chunks = [{"chunk_type": "text", "sheet_number": "A-500.00",
                   "text": "STUCCO FINISH SCALE: 1/2\"=1'-0\""}]
        self.assertEqual(pe.answer_attribute(chunks, ["stucco"], "thickness"), [])

    def test_a_real_value_is_still_answered(self):
        chunks = [{"chunk_type": "text", "sheet_number": "A-500.00",
                   "text": "7/8\" CEMENT STUCCO ON LATH"}]
        ans = pe.answer_question(chunks, "stucco thickness")
        self.assertEqual(ans["outcome"], "chunk_attribute")
        self.assertIn('7/8" CEMENT STUCCO', ans["text"])

    def test_scales_are_not_dimensions(self):
        self.assertEqual(pt.dimensions_from_text("DETAIL Scale: 3/4\"=1'-0\"  WALL 6\" STUD"), ['6"'])
        self.assertEqual(pt.dimensions_from_text("1/4\" = 1'-0\" TYP."), [])


class D8_RoofDrains(unittest.TestCase):

    def test_an_address_is_not_an_rd_tag(self):
        d = {"blocks": [
            {"type": 0, "bbox": [0, 0, 1, 1], "lines": [{"spans": [{"text": "128 Museum Village Rd,", "size": 8}]}]},
            {"type": 0, "bbox": [5, 5, 6, 6], "lines": [{"spans": [{"text": "RD", "size": 8}]}]},
        ]}
        L = pt.layout_from_dict(d, width=2592, height=1728, page_number=1)
        self.assertEqual({t["tag"]: t["count"] for t in pt.count_tags(L, pt.SEED_TAGS)}, {"RD": 1})

    def test_a_printed_rd_count_is_given_as_a_tag_count(self):
        chunks = [{"chunk_type": "tag_counts", "sheet_number": "A-105.00",
                   "payload": [{"tag": "RD", "count": 4, "source": "text-layer tag count"}]}]
        ans = pe.answer_question(chunks, "How many roof drains?")
        self.assertEqual(ans["text"], "RD tag appears 4 times on A-105.00 (not a stated total).")

    def test_symbols_only_says_where_they_are_shown_and_how_to_get_the_sheet(self):
        chunks = [
            {"chunk_type": "legend", "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN",
             "text": "= FLOOR/AREA/ROOF DRAIN"},
            {"chunk_type": "legend", "sheet_number": "A-105.00",
             "sheet_title": "ROOF AND BULKHEAD PLAN", "text": "= FLOOR/AREA/ROOF DRAIN"},
        ]
        ans = pe.answer_question(chunks, "How many roof drains?")
        self.assertEqual(ans["outcome"], "chunk_count_not_stated")
        self.assertEqual(ans["text"],
                         'Roof drains: shown on A-105.00 (roof and bulkhead plan) — count not '
                         'stated. Reply "show me A-105.00" for the sheet.')


class D4_SidewalkShedAndRoofProtection(unittest.TestCase):
    """SSP-003/004 print "8' HIGH SHED"; SSP-013 prints "8' HIGH SIDE WALK
    SHED"; the legend prints "ADJACENT BLDG. ROOF PROTECTION". Live, both
    questions went to the vision model on one sheet and found nothing."""

    CHUNKS = [
        {"chunk_type": "text", "sheet_number": "SSP-003.00", "sheet_title": "SITE SAFETY PLAN",
         "text": "CONCRETE SIDEWALK\n8' HIGH SHED"},
        {"chunk_type": "legend", "sheet_number": "SSP-003.00", "sheet_title": "SITE SAFETY PLAN",
         "text": "= ADJACENT BLDG. ROOF PROTECTION\n= EXISTING TREE PROTECTION FENCE"},
        {"chunk_type": "text", "sheet_number": "SSP-013.00", "sheet_title": "SIDEWALK SHED DETAILS",
         "text": "8' HIGH SIDE WALK SHED"},
    ]

    def test_the_questions_as_typed(self):
        self.assertEqual(pe.question_kind("What's the hight of the sidewalk shed?"),
                         ("attribute", "height"))
        self.assertEqual(pe.question_kind("What about roof protection?"), ("exists", None))
        self.assertEqual(pe.question_terms("What's the hight of the sidewalk shed?"),
                         ["sidewalk", "shed"])

    def test_one_typo_is_tolerated_and_a_real_word_is_not_a_typo(self):
        self.assertEqual(pe.question_kind("post guage"), ("attribute", "gauge"))
        self.assertEqual(pe.question_kind("stucco thicknes"), ("attribute", "thickness"))
        self.assertEqual(pe.question_kind("what is the weight of the unit"), (None, None))

    def test_side_walk_is_sidewalk(self):
        self.assertTrue(pe._matches("8' HIGH SIDE WALK SHED", ["sidewalk", "shed"]))
        self.assertTrue(pe._matches("SIDE-WALK SHED", ["sidewalk"]))

    def test_sidewalk_shed_height_is_answered(self):
        ans = pe.answer_question(self.CHUNKS, "What's the hight of the sidewalk shed?")
        self.assertEqual(ans["outcome"], "chunk_attribute")
        self.assertIn("SSP-013.00: 8' HIGH SIDE WALK SHED", ans["text"])

    def test_the_head_noun_finds_the_shed_when_the_phrase_does_not(self):
        chunks = [self.CHUNKS[0]]
        ans = pe.answer_question(chunks, "sidewalk shed height")
        self.assertEqual(ans["outcome"], "chunk_attribute")
        self.assertIn("SSP-003.00: 8' HIGH SHED", ans["text"])

    def test_what_about_roof_protection(self):
        ans = pe.answer_question(self.CHUNKS, "What about roof protection?")
        self.assertEqual(ans["outcome"], "chunk_exists")
        self.assertIn("SSP-003.00", ans["text"])
        self.assertIn("ROOF PROTECTION", ans["text"])

    def test_a_count_does_not_fall_back_to_the_head_noun(self):
        chunks = [{"chunk_type": "tag_counts", "sheet_number": "P-101.00",
                   "payload": [{"tag": "FD", "count": 6, "source": "text-layer tag count"}]},
                  {"chunk_type": "legend", "sheet_number": "P-101.00", "sheet_title": "FLOOR PLAN",
                   "text": "= FLOOR DRAIN"}]
        ans = pe.answer_question(chunks, "how many roof drains")
        self.assertNotIn("FD", ans["text"])


def _m200_layout():
    """M-200.00's shape: title-block text only, and ruled schedule grids whose
    cells are all empty (the schedule text is drawn as shapes)."""
    empty = lambda r, c: [[""] * c for _ in range(r)]
    return {
        "page_number": 9, "width": 2592, "height": 1728, "fractions_rebuilt": 0,
        "fractions_unverified": [],
        "blocks": [{"bbox": [2300, 1600, 2550, 1640], "lines": ["M-200.00"], "text": "M-200.00"},
                   {"bbox": [2300, 1200, 2550, 1240], "lines": ["HVAC SCHEDULES", "AND DETAILS"],
                    "text": "HVAC SCHEDULES\nAND DETAILS"}],
        "text": "M-200.00\nHVAC SCHEDULES\nAND DETAILS",
        "tables": [
            {"bbox": [34, 36, 2558, 1692], "rows": [["", "P: 845.234.4599"]]},       # title frame
            {"bbox": [349, 53, 958, 210], "rows": empty(3, 4)},                      # PTAC schedule
            {"bbox": [1371, 454, 1979, 572], "rows": empty(4, 7)},                   # fan schedule
            {"bbox": [1743, 514, 1854, 531], "rows": empty(1, 2)},                   # too small
        ],
    }


class D5b_SchedulesDrawnAsShapesAreReadFromTheImage(unittest.TestCase):

    def test_empty_grids_are_counted_and_the_title_frame_and_filled_tables_are_not(self):
        L = _m200_layout()
        self.assertEqual(pt.empty_table_grids(L), 2)
        L["tables"].append({"bbox": [100, 100, 400, 200],
                            "rows": [["MARK", "QTY"], ["P1", "30"]]})
        self.assertEqual(pt.empty_table_grids(L), 2)

    def test_the_ptac_schedule_is_read_and_counted(self):
        prompts = []

        async def vlm(image_b64, prompt, max_tokens):
            prompts.append(prompt)
            if '{"schedules": [' in prompt:
                return (json_dumps({"schedules": [{
                    "name": "ROOMS PTAC UNITS SCHEDULE",
                    "columns": ["UNIT NO.", "QTY", "MAKE", "MODEL", "ARRANGEMENT"],
                    "rows": [["PTAC-1", "21", "AMANA", "PTH093K", "WALL"],
                             ["PTAC-2", "9", "AMANA", "PTH123K", "WALL"],
                             ["PTAC-3", "11", "AMANA", "PTH153K", "WALL"]]}]}), "stop")
            if '{"notes": [' in prompt:
                return (json_dumps({"notes": [{"number": "1",
                                               "text": "PROVIDE WALL SLEEVE, THERMOSTAT."}]}), "stop")
            return (json_dumps({"sheet_number": "M-200.00", "sheet_type": "schedule"}), "stop")

        out = _run(pe.extract_vector_page(image_b64="x", layout=_m200_layout(), vlm_call=vlm))
        self.assertEqual(out["vlm_calls"], 3, "title, schedules, notes")
        self.assertIn("schedules_found:1", out["flags"]["schedules_fallback"])
        self.assertEqual(out["fields"]["schedules"][0]["source"], "vision")
        self.assertEqual(out["fields"]["notes_source"], "vision")

        chunks = pe.build_chunks(out["fields"])
        for c in chunks:
            c["sheet_number"] = "M-200.00"
        ans = pe.answer_question(chunks, "how many PTAC units")
        self.assertEqual(ans["text"], "PTAC:\nM-200.00: 41 (ROOMS PTAC UNITS SCHEDULE, qty "
                                      "column, read from the drawing image)")

    def test_no_empty_grid_and_not_a_thin_plan_is_one_call(self):
        calls = []

        async def vlm(image_b64, prompt, max_tokens):
            calls.append(prompt)
            return (json_dumps({"sheet_number": "M-201.00", "sheet_type": "detail"}), "stop")

        L = _m200_layout()
        L["tables"] = [L["tables"][0]]
        L["text"] = "WORD " * 3000
        out = _run(pe.extract_vector_page(image_b64="x", layout=L, vlm_call=vlm))
        self.assertEqual((len(calls), out["vlm_calls"]), (1, 1))

    def test_an_empty_grid_triggers_the_notes_fallback_on_a_non_plan_sheet(self):
        L = _m200_layout()
        self.assertTrue(pe.needs_notes_fallback({"sheet_type": "schedule", "notes": []}, L))
        self.assertFalse(pe.needs_notes_fallback(
            {"sheet_type": "schedule", "notes": [{"text": "x"}]}, L))


def json_dumps(obj):
    import json
    return json.dumps(obj)


if __name__ == "__main__":
    unittest.main()
