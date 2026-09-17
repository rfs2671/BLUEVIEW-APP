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
from lib import plan_search as ps  # noqa: E402
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

        db = _Db(FILES, PAGES)
        with mock.patch.object(server, "db", db), \
                mock.patch.object(server, "send_whatsapp_message", send), \
                mock.patch.object(server, "_send_plan_image", send_image), \
                mock.patch.object(server, "search_plans", never):
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
    """Live, "What type of AC units in this project?" was answered off a note.

    The matcher mapped `ac` to `ptac` with a hand-written synonym table, and
    two of its tests pinned that table. There is no table now, and the eval
    measures the cost precisely: `ac-type` is the suite's one failing case and
    its known failure class is `boilerplate_outranks_specific` — a generic
    note matching more of the question's words than the schedule that answers
    it. See eval/boyland.json and eval/migrated-from-the-matcher.md.

    What is kept here is the half that was never about synonyms: a short word
    a person types must not match inside a longer one.
    """

    def test_ac_never_matches_place_or_space(self):
        for hay in ("CROWN MOLDING IN PLACE", "OPEN SPACE", "EACH UNIT"):
            with self.subTest(hay=hay):
                self.assertFalse(re.search(ps.term_pattern("ac"), hay, re.I))

    def test_and_still_finds_the_word_itself(self):
        self.assertTrue(re.search(ps.term_pattern("ac"), "AC UNIT TYPE", re.I))
        self.assertTrue(re.search(ps.term_pattern("ptac"), "PTAC-1", re.I))


class D6_AHeadingIsNotAValue(unittest.TestCase):
    """Live, "What's the stucco thickness?" was answered with a scale bar.

    The three tests that asked answer_attribute for a thickness are eval case
    `stucco-wall-assembly` now: the drawings print the assembly — 6" STUD, R19
    BATT-R11.5 RIGID INSU., STUCCO FINISH — and no thickness at all, so the
    case checks that what comes back is the assembly on the sheets that carry
    it rather than a number lifted off a nearby line.

    The scale reading itself is not the matcher's and stays here.
    """

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

    # The two tests that asked the matcher to WORD a roof-drain answer are
    # eval case `roof-drain-count`. What they were protecting — that a count
    # of printed RD tags is never presented as a stated total — is a property
    # of the record now: it carries count_basis `tag_legend`, which is tiered
    # below a schedule cell and says on its face what it is. The eval checks
    # the answer against the sheets rather than against a sentence.


class D4_SidewalkShedAndRoofProtection(unittest.TestCase):
    """SSP-003/004/005 print "8' HIGH SHED"; SSP-013 prints "8' HIGH SIDE WALK
    SHED"; the legend prints "ADJACENT BLDG. ROOF PROTECTION". Live, both
    questions went to the vision model on one sheet and found nothing.

    ── BOTH QUESTIONS ARE EVAL CASES NOW ──────────────────────────────────

    `sidewalk-shed-height` and `roof-protection`, asked of the real corpus.
    Seven tests here asked the matcher instead, over three hand-written
    chunks, and three of them pinned machinery that is deliberately gone:

      * `question_kind` — the shape of an answer is the agent's business.
      * `_one_edit_apart` — "hight", "guage", "thicknes" were forgiven one
        edit against a small vocabulary. NOTHING REPLACES THIS. A misspelt
        question now returns less, or nothing. The eval asks both questions
        as they are spelt, so it does not paper over the loss either.
      * the head-noun retry — "sidewalk shed" falling back to "shed" when the
        phrase found nothing. Coverage ranking is what does that job now: a
        record matching both words outranks one matching either, and the one
        matching only "shed" is still returned, below it.

    One thing that is genuinely lost with the retry: SIDE WALK, written apart
    on SSP-013, is not the word "sidewalk" to a matcher that reads words as
    the sheet prints them. The height is printed on SSP-003/004/005 as well,
    so the eval case can still pass on the sheets that spell it — but if it
    does not, that is the finding, not a bug in the case.

    eval/migrated-from-the-matcher.md records all of it.
    """

    def test_a_count_does_not_fall_back_to_a_different_element(self):
        """Live: "how many roof drains" was answered with a count of FD, the
        FLOOR drain. The head-noun retry did that — dropping "roof" and asking
        for "drains". Coverage keeps both words in play."""
        fd = {"quote": "FD", "subject_terms": ["FD", "FLOOR DRAIN"],
              "tier": "tag_legend", "payload": {"tag": "FD", "count": 6}}
        rd = {"quote": "ROOF DRAIN", "subject_terms": ["RD", "ROOF DRAIN"],
              "tier": "text_layer"}
        ranked = ps.rank([fd, rd], ps.search_terms("roof drains"))
        self.assertEqual(ranked[0]["quote"], "ROOF DRAIN")

    def test_the_phrase_leads_and_the_height_ranks_below_it(self):
        """No head-noun retry: the record matching both words leads, and the
        line carrying the height ranks under it rather than being dropped.

        RANKING is not RETURNING. Measured on the real corpus the same day
        (eval `sidewalk-shed-height`), five sheets print the phrase and the
        limit of 8 cut the height line off before the crew ever saw it —
        known failure class `a_mention_outranks_the_measurement`. This holds
        the ordering; the eval holds the outcome."""
        phrase = {"quote": "SIDEWALK SHED PARAPET PANEL LAYOUT", "tier": "text_layer"}
        height = {"quote": "8' HIGH SHED", "tier": "text_layer"}
        walk = {"quote": "CONCRETE SIDEWALK", "tier": "text_layer"}
        ranked = ps.rank([walk, height, phrase], ps.search_terms("sidewalk shed"))
        self.assertEqual(ranked[0]["quote"], "SIDEWALK SHED PARAPET PANEL LAYOUT")
        self.assertIn(height, ranked, "the line with the height was dropped")
        ok, missing = ps.answer_is_grounded("The shed is 8 feet high.", ranked)
        self.assertTrue(ok, missing)

    def test_side_walk_written_apart_is_not_the_word_sidewalk(self):
        """THE LOSS, ASSERTED RATHER THAN ASSUMED. The matcher normalised it;
        nothing does now. It is written this way on exactly one sheet of this
        set, and the same fact is printed on three others."""
        self.assertFalse(re.search(ps.term_pattern("sidewalk"),
                                   "8' HIGH SIDE WALK SHED", re.I))
        self.assertTrue(re.search(ps.term_pattern("shed"),
                                  "8' HIGH SIDE WALK SHED", re.I))


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

        # ── AND 41 IS WHERE THIS WHOLE ARC STARTED ────────────────────────
        #
        # This test used to end by asking the matcher how many PTAC units
        # there are, and asserting the answer "M-200.00: 41" — the sum of a
        # quantity column, read off a picture, with a caveat after it. It is
        # the exact sentence that went to the group. 41 is printed nowhere.
        #
        # The same fields, as records: three quantities the schedule states,
        # each one vision-read and saying so, and a gate that refuses the sum.
        from lib import plan_records as pr
        records = pr.build_records(out["fields"],
                                   page={"sheet_number": "M-200.00", "page_number": 9},
                                   raw_text=_m200_layout()["text"])
        sched = [r for r in records if r.get("record_type") == "schedule"]
        self.assertEqual(len(sched), 1)
        # Read off the image, and the record says so rather than wearing the
        # badge of a cell the text layer handed over.
        self.assertEqual((sched[0]["tier"], sched[0]["source"]),
                         (pe.TIER_VISION, "vision"))
        for stated in ("21", "9", "11"):
            with self.subTest(qty=stated):
                self.assertIn(stated, sched[0]["quote"])

        ok, missing = ps.answer_is_grounded("There are 41 PTAC units.", records)
        self.assertFalse(ok, "the gate allowed a total no cell prints")
        self.assertIn("41", missing)
        ok, _ = ps.answer_is_grounded(
            "The schedule lists 21 PTAC-1, 9 PTAC-2 and 11 PTAC-3.", records)
        self.assertTrue(ok, "the gate refused the numbers the schedule states")

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
