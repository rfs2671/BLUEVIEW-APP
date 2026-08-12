"""SUBMIT_NO_CONTENT — the backstop for a record that would print blank.

The client gate (frontend/app/logbooks/osha_log.jsx) is the CP-facing fix: it
names the row and offers the fix on the screen. It is not a backstop. An older
build, a replayed draft or a direct API call still reaches the submit path, and
one of those filed the row this gate exists to stop — project
6a5f63bc147407d3261df2c7, 2026-08-11: an entry with no name, no card number and
no certification, on a signed compliance record.

WHAT IS BEING ASSERTED, and what deliberately is not.

finalize_logbook rules that per-field completeness "differs per log type and
belongs to the editors, not to the lock". This gate does NOT reverse that. It
asks one type-agnostic question of the two records that ARE a list of rows:
would EVERY row be dropped by the renderer that prints it? If so the document
comes out blank, and that is true regardless of what any form ought to contain.

So the tests below check three things:
  1. the rules still match the RENDERERS they were lifted from, field for field
  2. the gate fires on the production shape and not on a real record
  3. every other log type passes through untouched — no per-form rule was
     invented for the nine that have no shipped notion of an empty row
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

# Every log type the shared submit path serves.
ALL_LOG_TYPES = [
    "preshift_signin", "toolbox_talk", "subcontractor_orientation", "osha_log",
    "scaffold_maintenance", "hot_work", "concrete_operations",
    "crane_operations", "excavation_monitoring", "daily_jobsite",
    "ssc_daily_safety_log",
]


class TheRulesAreLiftedFromTheRenderers(unittest.TestCase):
    """Not written here. A rule that drifts from the renderer would refuse a
    record the PDF would happily print, or pass one that comes out blank."""

    def test_all_eleven_types_are_accounted_for(self):
        # The table names two; the other nine must be types this file knows
        # about, so a NEW log type cannot appear without someone deciding
        # which side of the line it falls on.
        timing = re.search(
            r"LOGBOOK_TIMING_CLASS = \{(.*?)\n\}", _SRC, re.S,
        ).group(1)
        declared = set(re.findall(r'"([a-z_]+)":\s*"(?:immediate|end_of_day)"', timing))
        self.assertEqual(declared, set(ALL_LOG_TYPES))

    def test_only_the_two_row_records_are_gated(self):
        self.assertEqual(
            set(S._SUBMIT_ROW_CONTENT_RULES), {"osha_log", "preshift_signin"},
        )

    def test_osha_fields_match_the_renderer(self):
        """render_logbook_html's osha_log branch skips a row with none of five
        fields as 'an untouched EMPTY_ENTRY seed'. Read from the source."""
        branch = _SRC[_SRC.index('elif log_type == "osha_log":'):]
        branch = branch[:branch.index("elif log_type ==", 10)]
        self.assertIn("untouched EMPTY_ENTRY seed", branch)
        m = re.search(r"has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)", branch)
        renderer_fields = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
        self.assertEqual(S._SUBMIT_ROW_CONTENT_RULES["osha_log"][1], renderer_fields)

    def test_preshift_field_matches_both_renderers(self):
        """A worker row is real when it has a NAME — asserted in the single-doc
        renderer and again in generate_combined_report."""
        self.assertEqual(_SRC.count('if w.get("name", "").strip():'), 2)
        self.assertEqual(S._SUBMIT_ROW_CONTENT_RULES["preshift_signin"], ("workers", ("name",)))

    def test_row_has_mirrors_the_renderers_has(self):
        """_row_has is a copy of a nested helper. If they diverge, the gate
        stops agreeing with the document."""
        cases = [
            ({"k": "x"}, True), ({"k": ""}, False), ({"k": "   "}, False),
            ({"k": None}, False), ({}, False),
            ({"k": True}, True), ({"k": False}, True),   # a bool IS an answer
            ({"k": []}, False), ({"k": [1]}, True),
            ({"k": {}}, False), ({"k": {"a": 1}}, True),
            ({"k": 0}, True), ({"k": 3}, True),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertIs(S._row_has(payload, "k"), expected)
        self.assertIs(S._row_has(None, "k"), False)
        self.assertIs(S._row_has("not a dict", "k"), False)


class ItFiresOnTheProductionShape(unittest.TestCase):
    """The row that reached a signed record, and the ones that must not be
    mistaken for it."""

    def test_a_register_of_untouched_seeds_is_refused(self):
        # EMPTY_ENTRY carries a `date`, so "every leaf is blank" would NOT
        # catch this. The renderer's rule does.
        seed = {
            "worker_id": None, "worker_name": "", "company": "",
            "certification_type": "", "card_number": "", "expiration": "",
            "signed": False, "date": "2026-08-11",
        }
        detail = S._submit_no_content_detail("osha_log", {"entries": [seed, dict(seed)]})
        self.assertEqual(detail, {"code": "SUBMIT_NO_CONTENT", "log_type": "osha_log"})

    def test_one_real_row_is_enough(self):
        seed = {"worker_name": "", "company": "", "certification_type": "",
                "card_number": "", "expiration": "", "date": "2026-08-11"}
        real = dict(seed, worker_name="WILMER CARRILLO")
        self.assertIsNone(
            S._submit_no_content_detail("osha_log", {"entries": [seed, real]}),
        )

    def test_the_company_only_row_from_production_is_content(self):
        """The abandoned row carried company 'AAZ' and nothing else. The CP
        typed it, the renderer prints it, so the gate must not refuse it."""
        row = {"worker_name": "", "company": "AAZ", "certification_type": "",
               "card_number": "", "expiration": ""}
        self.assertIsNone(S._submit_no_content_detail("osha_log", {"entries": [row]}))

    def test_an_empty_register_is_refused(self):
        self.assertIsNotNone(S._submit_no_content_detail("osha_log", {"entries": []}))

    def test_a_preshift_sheet_with_no_named_worker_is_refused(self):
        rows = [{"name": "", "company": "AAZ"}, {"name": "   "}]
        detail = S._submit_no_content_detail("preshift_signin", {"workers": rows})
        self.assertEqual(detail["code"], "SUBMIT_NO_CONTENT")

    def test_a_preshift_sheet_with_one_named_worker_passes(self):
        rows = [{"name": ""}, {"name": "Ray Fisher"}]
        self.assertIsNone(S._submit_no_content_detail("preshift_signin", {"workers": rows}))

    def test_the_detail_names_the_log_type_beside_the_code(self):
        """Data alongside the code, never prose — the same shape
        SUBMIT_MISSING_TRADE uses, and finalizeErrorCode reads only `.code`."""
        detail = S._submit_no_content_detail("osha_log", {"entries": []})
        self.assertEqual(set(detail), {"code", "log_type"})
        self.assertNotIn("detail", detail)


class ItDeclinesToAnswerForEverythingElse(unittest.TestCase):
    """The nine types with no shipped notion of an empty row pass through
    untouched. Defining `empty` for them needs the per-form minimum content
    that is still deferred, and inventing one here is exactly what
    finalize_logbook's ruling forbids."""

    def test_the_other_nine_are_never_refused(self):
        for t in ALL_LOG_TYPES:
            if t in S._SUBMIT_ROW_CONTENT_RULES:
                continue
            with self.subTest(log_type=t):
                # Even a payload that is obviously empty for that form.
                self.assertIsNone(S._submit_no_content_detail(t, {}))
                self.assertIsNone(S._submit_no_content_detail(t, {"entries": []}))
                self.assertIsNone(S._submit_no_content_detail(t, {"workers": []}))

    def test_concrete_and_crane_are_deliberately_absent(self):
        """Both DO carry a row seed-skip rule, but the row list is one SECTION
        of the record, not the record. A pour with no slump test is still a
        pour; refusing it would assert a minimum those forms never declared."""
        for t in ("concrete_operations", "crane_operations"):
            self.assertNotIn(t, S._SUBMIT_ROW_CONTENT_RULES)
            self.assertIsNone(S._submit_no_content_detail(t, {"slump_tests": []}))
            self.assertIsNone(S._submit_no_content_detail(t, {"load_entries": []}))

    def test_an_unknown_log_type_passes(self):
        self.assertIsNone(S._submit_no_content_detail("something_new", {"entries": []}))

    def test_a_malformed_body_is_not_this_gates_business(self):
        """SUBMIT_EMPTY_LOG runs first and owns these. Answering here would
        report 'no content' for a body that is the wrong shape entirely."""
        for payload in (None, [], "", 0, "entries"):
            with self.subTest(payload=payload):
                self.assertIsNone(S._submit_no_content_detail("osha_log", payload))
        # Right type, wrong container shape.
        for rows in (None, {}, "x", 5):
            with self.subTest(rows=rows):
                self.assertIsNone(S._submit_no_content_detail("osha_log", {"entries": rows}))
        # A non-dict row among real ones is ignored, not crashed on.
        self.assertIsNone(
            S._submit_no_content_detail("osha_log", {"entries": ["x", {"worker_name": "A"}]}),
        )
        self.assertIsNotNone(
            S._submit_no_content_detail("osha_log", {"entries": ["x", None, 7]}),
        )


class ItIsWiredIntoBothEndpoints(unittest.TestCase):
    """The ordinary flow is create-then-submit, so the submit arrives as a PUT.
    A gate on create alone never sees it."""

    def test_both_submit_paths_call_it(self):
        self.assertEqual(_SRC.count("_submit_no_content_detail("), 3)  # def + 2 sites

    def test_create_logbook_carries_it(self):
        fn = _SRC[_SRC.index("async def create_logbook"):]
        fn = fn[:6000]
        self.assertIn("_submit_no_content_detail(data.log_type, data.data)", fn)

    def test_update_logbook_judges_the_STORED_content(self):
        """_eff_data, not data.data. A submit that patches only `status` must
        still be judged on what is already stored, or a blank register walks
        straight through on the path a CP actually takes."""
        fn = _SRC[_SRC.index("async def update_logbook"):]
        fn = fn[:5000]
        self.assertIn('_submit_no_content_detail(_cur.get("log_type"), _eff_data)', fn)

    def test_it_runs_after_the_signature_check_in_both(self):
        for name in ("async def create_logbook", "async def update_logbook"):
            fn = _SRC[_SRC.index(name):]
            fn = fn[:6000]
            with self.subTest(fn=name):
                self.assertLess(
                    fn.index("SUBMIT_MISSING_CP_SIGNATURE"),
                    fn.index("_submit_no_content_detail"),
                )

    def test_it_runs_before_anything_is_written(self):
        """A refused submit must mutate nothing at all."""
        fn = _SRC[_SRC.index("async def update_logbook"):]
        fn = fn[:6000]
        self.assertLess(
            fn.index("_submit_no_content_detail"), fn.index('update = {"updated_at"'),
        )

    def test_the_client_has_copy_for_the_code(self):
        """An unmapped code renders as the generic message, which tells the CP
        nothing about which row to fix."""
        en = (_BACKEND / ".." / "frontend" / "src" / "i18n" / "en.js").resolve()
        self.assertIn("code_SUBMIT_NO_CONTENT:", en.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
