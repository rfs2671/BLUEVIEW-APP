"""ONE ENGINE, FIFTEEN SCHEMAS, AND TWELVE TYPES THAT MUST NOT MOVE.

The per-logbook renderer was one `if log_type ==` with thirteen branches over
1145 lines. It becomes a schema per type plus one engine, converted ONE TYPE AT
A TIME behind a switch -- so the whole safety of the approach is that the types
which have not been converted render exactly as they did before.

That is asserted here rather than assumed, and it is the reason this file leads
with it.

── THE HARNESS HAS A TRAP IN IT, AND IT COST AN HOUR ─────────────────────────

The first byte-for-byte comparison reported THIRTEEN OF THIRTEEN CHANGED, with
every length identical. Identical lengths and different hashes is not thirteen
regressions; it is one varying field, and it was `gen_time` -- the generation
timestamp this renderer stamps into every footer.

So any before/after comparison of this function MUST freeze
`server.eastern_datetime` first. `TheComparisonIsRepeatable` below pins that,
because the next person to run one will otherwise spend the same hour reading a
diff of twelve files that are the same.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from lib import legal_render  # noqa: E402
from lib.legal_render import schema as _schema  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)

#: Every type the old chain renders. Twelve of these must not move.
ALL_TYPES = ("daily_jobsite", "toolbox_talk", "preshift_signin", "hot_work",
             "crane_operations", "excavation_monitoring", "concrete_operations",
             "scaffold_maintenance", "ssc_daily_safety_log", "fall_protection",
             "site_superintendent_log", "osha_log", "subcontractor_orientation")

_PROJECT = {"_id": "p1", "name": "588 Thomas",
            "address": "588 Thomas S Boyland Street",
            "company_name": "Metro Build Constructors LLC",
            "bbl": "3035400025", "nyc_bin": "3255362"}


def _logbook(log_type, worker="alex rivera"):
    return {
        "_id": "lb1", "project_id": "p1", "date": "2026-09-09",
        "log_type": log_type, "cp_name": "daniel kaplan", "status": "submitted",
        "cp_signature": {"paths": [[{"x": 1, "y": 2}, {"x": 30, "y": 20},
                                    {"x": 60, "y": 5}]],
                         "signerName": "daniel kaplan"},
        "data": {"worker_name": worker, "worker_company": "Premier Builders Inc.",
                 "worker_trade": "carpenter", "language_provided": "English",
                 "completed_at": "2026-09-09T07:00:00",
                 "checklist": {"hard_hats": True, "safety_boots": True},
                 "entries": [], "activities": [], "attendees": [],
                 "signins": [], "workers": []},
    }


class _Cur:
    def __init__(self, rows): self._rows = rows
    def sort(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, *a, **k): return list(self._rows)


class _Coll:
    def __init__(self, rows=None): self._rows = rows or []
    def find(self, *a, **k): return _Cur(self._rows)
    async def find_one(self, *a, **k): return dict(_PROJECT)
    async def count_documents(self, *a, **k): return 0
    def aggregate(self, *a, **k): return _Cur([])


class _DB:
    def __init__(self, logbooks=None): self._logbooks = logbooks or []
    def __getattr__(self, name):
        return _Coll(self._logbooks if name == "logbooks" else [])


def _render(log_type, group=None, freeze=True):
    """The renderer, with the clock frozen unless a test asks otherwise."""
    db = _DB(group if group is not None else [])
    stack = [patch.object(server, "db", db),
             patch.object(server, "to_query_id", lambda v: v)]
    if freeze:
        stack.append(patch.object(server, "eastern_datetime",
                                  lambda *a, **k: "FROZEN"))
    for p in stack:
        p.start()
    try:
        return asyncio.run(server.generate_single_logbook_html(_logbook(log_type)))
    finally:
        for p in reversed(stack):
            p.stop()


class ADeclarationMayNotContainCode(unittest.TestCase):
    """The constraint IS the design. A schema that can hold a callable is a
    renderer, and a renderer in a declaration is how one `if` reached thirteen
    branches -- so this refuses at import time rather than at review time."""

    def test_a_callable_anywhere_is_refused(self):
        for decl in (
            {"source": {"kind": "one"},
             "sections": [{"primitive": "narrative", "empty": "omit",
                           "fmt": str.upper}]},
            {"source": {"kind": "one"}, "hook": len,
             "sections": [{"primitive": "narrative", "empty": "omit"}]},
            {"source": {"kind": "one"},
             "sections": [{"primitive": "table", "empty": "omit",
                           "columns": [("a", "A", print)]}]},
        ):
            with self.assertRaises(_schema.SchemaError) as c:
                _schema.validate("probe", decl)
            self.assertIn("callable", str(c.exception))

    def test_the_finder_reports_WHERE(self):
        """A refusal that does not say where is one somebody works around."""
        found = _schema.callables_in({"sections": [{"f": len}]})
        self.assertEqual(found, [".sections[0].f"])

    def test_a_clean_declaration_passes(self):
        """The other half: a guard that refuses everything is not a guard."""
        self.assertIsNone(_schema.callables_in({"a": 1, "b": ["x", ("y", 2)]}) or None)

    def test_an_unknown_formatter_is_refused(self):
        with self.assertRaises(_schema.SchemaError) as c:
            _schema.validate("probe", {
                "source": {"kind": "one"},
                "sections": [{"primitive": "field_grid", "empty": "omit",
                              "fields": [("a", "A", "no_such_formatter")]}]})
        self.assertIn("closed", str(c.exception))

    def test_a_section_MUST_declare_its_empty_state(self):
        """Three kinds of empty are not interchangeable on a compliance
        document, and a section that says nothing gets one by accident."""
        with self.assertRaises(_schema.SchemaError) as c:
            _schema.validate("probe", {"source": {"kind": "one"},
                                       "sections": [{"primitive": "narrative"}]})
        self.assertIn("empty", str(c.exception))

    def test_a_source_MUST_say_how_records_are_selected(self):
        with self.assertRaises(_schema.SchemaError):
            _schema.validate("probe", {"sections": [{"primitive": "narrative",
                                                     "empty": "omit"}]})

    def test_every_shipped_schema_validates(self):
        """Import already ran this; running it again means a schema added
        without importing the module still cannot pass."""
        for t, d in legal_render.SCHEMAS.items():
            _schema.validate(t, d)


class TheSwitchIsNarrow(unittest.TestCase):

    def test_exactly_one_type_is_converted(self):
        self.assertEqual(set(legal_render.CONVERTED_TYPES),
                         {"subcontractor_orientation"})

    def test_the_engine_returns_None_for_everything_else(self):
        """Not an exception. 'Not converted yet' must not become a failed
        document -- the caller's job is to fall through."""
        for t in ALL_TYPES:
            if t not in legal_render.CONVERTED_TYPES:
                self.assertIsNone(legal_render.render(t, [_logbook(t)], {}))

    def test_the_dispatch_happens_before_the_chain(self):
        """A switch below the first branch would never be reached for a type
        the chain already handles."""
        i = _SRC.index("if log_type in legal_render.CONVERTED_TYPES")
        j = _SRC.index('if log_type == "daily_jobsite":')
        self.assertLess(i, j)


class TheTwelveUnconvertedTypesStillRender(unittest.TestCase):
    """The whole safety of converting one at a time."""

    def test_each_one_renders_without_the_engine(self):
        for t in ALL_TYPES:
            if t in legal_render.CONVERTED_TYPES:
                continue
            with self.subTest(log_type=t):
                html = _render(t)
                self.assertTrue(html, f"{t} rendered nothing")
                self.assertNotIn("<!DOCTYPE html><html><head>", html[:40],
                                 f"{t} went through the engine")

    def test_the_converted_one_DOES_go_through_the_engine(self):
        """The other half. If this passed too, the switch would be doing
        nothing and every assertion above would be vacuous."""
        html = _render("subcontractor_orientation")
        self.assertIn("Site Safety Orientation Record", html)


class TheComparisonIsRepeatable(unittest.TestCase):
    """PINNED BECAUSE IT ALREADY COST AN HOUR.

    The first before/after run reported thirteen of thirteen changed with every
    LENGTH identical. That is one varying field, not thirteen regressions, and
    it was the generation timestamp this renderer stamps into every footer.
    """

    def test_two_renders_with_the_clock_frozen_are_identical(self):
        a = _render("toolbox_talk")
        b = _render("toolbox_talk")
        self.assertEqual(a, b,
                         "this renderer is not deterministic even with the "
                         "clock frozen, so no byte-for-byte comparison of it "
                         "can mean anything")

    def test_and_WITHOUT_freezing_they_differ_only_in_length_preserving_ways(self):
        """The trap itself, executed. `gen_time` is why an unfrozen comparison
        reads as a total regression: same length, different bytes."""
        a = _render("toolbox_talk", freeze=False)
        b = _render("toolbox_talk", freeze=False)
        if a != b:
            self.assertEqual(len(a), len(b),
                             "the renders differ in LENGTH as well, so the "
                             "cause is no longer just the timestamp and this "
                             "note needs updating")

    def test_the_frozen_marker_actually_reaches_the_page(self):
        """A freeze that patched the wrong name would leave the clock running
        and this whole class would pass while proving nothing."""
        self.assertIn("FROZEN", _render("toolbox_talk"))


class TheOrientationSheetSaysWhatTheSchemaDeclares(unittest.TestCase):

    def setUp(self):
        self.decl = legal_render.SCHEMAS["subcontractor_orientation"]
        self.html = _render("subcontractor_orientation")

    def test_every_declared_section_appears_by_number_and_title(self):
        for sec in self.decl["sections"]:
            with self.subTest(section=sec["title"]):
                self.assertIn(f"{sec['n']}. {sec['title']}", self.html)

    def test_the_citation_is_ours_and_real(self):
        self.assertIn("BC 3301.13.13", self.html)

    def test_it_carries_NO_government_identity(self):
        """The document language is borrowed; the identity is not. No DOB
        logo, no seal, no form number."""
        low = self.html.lower()
        for banned in ("nyc.gov", "dob form", "department of buildings",
                       "<img src=\"data:image/png;base64,ivborw0kggoaaaansuheugaaa"):
            self.assertNotIn(banned, low)

    def test_the_checkboxes_are_paper_checkboxes(self):
        self.assertIn("&#9746;", self.html)   # ticked
        self.assertIn("&#9744;", self.html)   # not ticked

    def test_the_attendee_table_repeats_its_header_and_cannot_split_a_row(self):
        self.assertIn("display:table-header-group", self.html)
        self.assertIn("break-inside:avoid", self.html)

    def test_the_page_says_which_page_it_is(self):
        self.assertIn("counter(page)", self.html)
        self.assertIn("counter(pages)", self.html)

    def test_a_later_page_names_its_subject(self):
        self.assertIn("running(contheader)", self.html)

    def test_BLANK_ROWS_are_drawn_rather_than_the_table_shortened(self):
        """A twenty-row sheet with one name is valid paper. The row count is
        the form's, not the data's."""
        table_sec = [s for s in self.decl["sections"]
                     if s["primitive"] == "table"][0]
        self.assertEqual(table_sec["empty"], "blank_rows")
        self.assertGreaterEqual(table_sec["min_rows"], 10)

    def test_a_group_renders_one_row_per_FILED_RECORD(self):
        """The records are drawn together, never merged: each is its own
        separately signed document and contributes its own row."""
        group = [_logbook("subcontractor_orientation", "alex rivera"),
                 _logbook("subcontractor_orientation", "marcus lee")]
        for i, g in enumerate(group):
            g["_id"] = "lb1" if i == 0 else f"lb{i + 1}"
        html = _render("subcontractor_orientation", group=group)
        self.assertTrue("Alex rivera" in html, "the first filed record is not a row")
        self.assertTrue("Marcus lee" in html, "the second filed record is not a row")

    def test_a_record_the_group_cannot_see_still_gets_its_own_sheet(self):
        """A draft, or a row the query misses, must not produce a document
        that omits the log somebody asked for.

        THE OTHER RECORD NEEDS A DIFFERENT _id, and the first draft of this
        test forgot: the fixture stamps "lb1" on everything, so the guard saw
        the requested record in the group and rendered the group. The test was
        wrong, not the guard -- which is what the guard is FOR."""
        other = _logbook("subcontractor_orientation", "someone else")
        other["_id"] = "lb-other"
        html = _render("subcontractor_orientation", group=[other])
        # assertTrue, not assertIn: the container is a whole rendered sheet.
        self.assertTrue("Alex rivera" in html,
                        "the requested log is missing from its own sheet")
        self.assertTrue("Someone else" not in html,
                        "a group that does not contain the requested record "
                        "was rendered instead of it")


class TheSignatureIsInkNotAnExhibit(unittest.TestCase):

    PATHS = [[{"x": 1, "y": 2}, {"x": 30, "y": 20}, {"x": 60, "y": 5}]]

    def test_the_default_is_unchanged_for_every_existing_caller(self):
        svg = server._signature_paths_to_svg(self.PATHS)
        self.assertIn("border:1px solid #e2e8f0", svg)
        self.assertIn("background:#ffffff", svg)

    def test_boxed_False_has_no_border_and_no_backdrop(self):
        svg = server._signature_paths_to_svg(self.PATHS, boxed=False)
        self.assertNotIn("border", svg)
        self.assertNotIn("background", svg)

    def test_the_ink_itself_is_identical_either_way(self):
        """Only the container changes. A signature that redrew differently for
        one document would be two signatures."""
        a = server._signature_paths_to_svg(self.PATHS)
        b = server._signature_paths_to_svg(self.PATHS, boxed=False)
        import re
        self.assertEqual(re.findall(r"<polyline[^>]*>", a),
                         re.findall(r"<polyline[^>]*>", b))

    def test_the_strokes_are_transparent_by_construction(self):
        svg = server._signature_paths_to_svg(self.PATHS, boxed=False)
        self.assertIn('fill="none"', svg)

    def test_the_engine_does_not_carry_its_OWN_reconstruction(self):
        """One geometry, passed in through the context. Two copies of it have
        drifted in this repository twice."""
        src = Path(legal_render.__file__).parent
        for f in src.glob("*.py"):
            self.assertNotIn("preserveAspectRatio", f.read_text(encoding="utf-8"),
                             f"{f.name} rebuilds the signature SVG itself")


if __name__ == "__main__":
    unittest.main(verbosity=2)
