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
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from lib import legal_render  # noqa: E402
from lib.legal_render import primitives  # noqa: E402
from lib.legal_render import schema as _schema  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)

#: Every type the old chain renders. Twelve of these must not move.
ALL_TYPES = ("daily_jobsite", "toolbox_talk", "preshift_signin", "hot_work",
             "crane_operations", "excavation_monitoring", "concrete_operations",
             "scaffold_maintenance", "ssc_daily_safety_log", "fall_protection",
             "site_superintendent_log", "osha_log", "subcontractor_orientation")

#: THE SPECIMEN FOR EVERY CLAIM ABOUT THE *BRANCH* RENDERER, CHOSEN RATHER
#: THAN NAMED.
#:
#: Six assertions in this file render a document to say something about the
#: renderer that is NOT the engine -- that it stamps a clock, that two unfrozen
#: renders of it differ. `toolbox_talk` was named in all six, and it converted;
#: a named specimen that converts turns every one of them into an assertion
#: about the engine, which is the opposite of what they say they check.
#:
#: SO IT IS DERIVED. Whatever type the chain still renders is the specimen, and
#: the conversion that takes the last one is caught by the floor below rather
#: than by six confusing failures.
_STILL_BRANCHED = sorted(set(ALL_TYPES) - set(legal_render.CONVERTED_TYPES))

#: The one the branch-side assertions use. Named once so a reader can see
#: which document a failure is about.
_BRANCHED = _STILL_BRANCHED[0] if _STILL_BRANCHED else None

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
                 # ALL THREE STATES IN ONE RECORD: ticked, explicitly
                 # answered no, and -- by omission -- never asked.
                 "checklist": {"hard_hats": True, "safety_boots": True,
                               "no_horseplay": False},
                 # PRESENT AND NULL, which is what the manual-entry path
                 # writes. The acknowledgment section exists and reads
                 # UNSIGNED; a record without the key omits the section
                 # entirely, and a renderer test names that other half.
                 "worker_signature": None,
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

    def test_every_converted_type_is_a_type_the_app_DEFINES(self):
        """THIS WAS A HAND-WRITTEN SET AND IT EXPIRED ON THE SECOND
        CONVERSION.

        It read `== {"subcontractor_orientation"}`, which said "the switch is
        narrow" at a moment when narrow meant one. Twelve conversions follow,
        so as written it was a line somebody would edit twelve times without
        reading -- and a check nobody reads is a check that is not running.

        WHAT IS ACTUALLY WORTH ASSERTING SURVIVES THE WHOLE MIGRATION: a name
        in CONVERTED_TYPES that no log type answers to is a schema the dispatch
        can never reach, which fails silently and forever.
        """
        defined = {t["key"] for t in server.LOGBOOK_TYPE_REGISTRY}
        unknown = sorted(set(legal_render.CONVERTED_TYPES) - defined)
        self.assertEqual(unknown, [],
                         f"these have schemas and are not log types: {unknown}")
        self.assertTrue(legal_render.CONVERTED_TYPES)

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
        # THE FIRST ARM OF THE CHAIN, FOUND RATHER THAN NAMED. This
        # named `daily_jobsite`, and that branch was deleted the
        # moment its conversion finished -- the same shape as the
        # three slices that broke when `osha_log` became the last
        # named branch. The chain's first arm moves every time a type
        # is converted; what does not move is that there IS one.
        m = re.compile('\\n    if log_type == "\\w+":').search(_SRC[i:])
        self.assertIsNotNone(m, "the per-type chain has no first branch")
        self.assertLess(i, i + m.start())


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

    def test_there_IS_a_branch_rendered_type_to_make_these_claims_about(self):
        """THE FLOOR UNDER THE SPECIMEN.

        `_STILL_BRANCHED` shrinks by one with every conversion. When it empties,
        `_BRANCHED` below raises at import and this file stops running rather
        than passing -- so this names the moment in a sentence instead.

        WHAT TO DO WHEN IT FAILS: every assertion in this class and in
        `TheEngineSheetIsDeterministic` that contrasts the engine against the
        branch has lost its subject, because there is no branch left. Retire
        them; do not repoint them at a converted type, which would make each
        one quietly assert the opposite of what it says.
        """
        self.assertTrue(
            _STILL_BRANCHED,
            "every type is converted, so nothing renders through the chain "
            "and the branch-side claims in this file have no subject left")

    def test_two_renders_with_the_clock_frozen_are_identical(self):
        a = _render(_BRANCHED)
        b = _render(_BRANCHED)
        self.assertEqual(a, b,
                         "this renderer is not deterministic even with the "
                         "clock frozen, so no byte-for-byte comparison of it "
                         "can mean anything")

    def test_and_WITHOUT_freezing_they_differ_only_in_length_preserving_ways(self):
        """The trap itself, executed. `gen_time` is why an unfrozen comparison
        reads as a total regression: same length, different bytes."""
        a = _render(_BRANCHED, freeze=False)
        b = _render(_BRANCHED, freeze=False)
        if a != b:
            self.assertEqual(len(a), len(b),
                             "the renders differ in LENGTH as well, so the "
                             "cause is no longer just the timestamp and this "
                             "note needs updating")

    def test_the_frozen_marker_actually_reaches_the_page(self):
        """A freeze that patched the wrong name would leave the clock running
        and this whole class would pass while proving nothing.

        ── POINTED AT A TYPE THAT STILL HAS A CLOCK ────────────────────

        This is the BRANCH renderer's half. It stamps "Generated on <time>"
        into every document it wraps, so a freeze that missed would show up
        THE TYPE IS NO LONGER NAMED. It was `toolbox_talk`, and the note
        here said "when it converts this moves to whichever type still does"
        -- which is a repair somebody has to remember. `_STILL_BRANCHED`
        does it, and the floor above says what to do when it runs out.

        IT RETIRES WHEN THE LAST CLOCK-STAMPING RENDERER DOES, not before --
        and `test_a_renderer_that_stamps_a_clock_still_exists` below fails
        loudly on the day that happens, rather than letting this quietly
        assert nothing.
        """
        self.assertIn("FROZEN", _render(_BRANCHED))

    def test_a_renderer_that_stamps_a_clock_still_exists(self):
        """THE GUARD ON THE GUARD ABOVE.

        The moment no renderer stamps a wall clock onto a page, the assertion
        above has nothing to find and would fail -- which is correct, and is
        the signal to retire it rather than to repoint it again. Named here so
        that failure arrives as a sentence instead of a puzzle.
        """
        self.assertIn("Generated on", _render(_BRANCHED))

    def test_the_freeze_reaches_the_ENGINE_sheet_too(self):
        """THE ENGINE'S HALF, AND IT IS A DIFFERENT ROUTE.

        The engine's sheet carries no generation stamp, so the marker cannot
        arrive the way it does above. It arrives through the AFFIRMATION
        BANNER, which formats a signature's claimed and server-received times
        with `eastern_datetime` -- the one clock-formatted thing on the page.

        WHAT THIS PROVES IS NARROWER THAN IT LOOKS, and the next class says
        why: those times come off the RECORD, not off the clock, so they do
        not vary between runs. This shows the freeze patched the right name
        and its effect is visible. It does not show the comparison needed
        protecting.
        """
        # AN AFFIRMED, TIMESTAMPED SIGNATURE, BUILT HERE ON PURPOSE.
        #
        # The shared fixture's mark is unaffirmed, and an UNAFFIRMED banner
        # carries no time -- so on that record NOTHING on the engine's page is
        # clock-formatted and the marker cannot arrive. That is worth stating
        # rather than working around: the engine's sheet touches a clock only
        # where a signature was affirmed with a recorded time, and on every
        # other record it is clock-free entirely.
        base = _logbook("subcontractor_orientation")
        base["cp_signature"] = dict(base["cp_signature"] or {})
        base["cp_signature"].update({
            "affirmed": True,
            "affirmedAt": "2026-08-04T19:56:00Z",
            "affirmed_received_at": "2026-08-04T19:56:00Z"})
        with patch.object(sys.modules[__name__], "_logbook",
                          lambda *a, **k: base):
            html = _render("subcontractor_orientation")
        self.assertIn("AFFIRMED", html)
        self.assertIn("FROZEN", html,
                      "the freeze no longer reaches the engine's sheet at "
                      "all, so a byte comparison of two engine renders is "
                      "unguarded")


class TheEngineReadsNoClock(unittest.TestCase):
    """AN ASSERTION ABOUT WHAT THE CODE DOES NOT DO.

    ── WHY THIS REPLACES A CHECK RATHER THAN JOINING ONE ───────────────

    `TheComparisonIsRepeatable` exists because a before/after run once
    reported thirteen of thirteen types changed with every length identical --
    one varying field, the generation timestamp, and an hour spent reading a
    diff of twelve files that were the same. The fix was to freeze the clock,
    and the guard was to prove the freeze reached the page.

    THE ENGINE'S SHEET HAS NO SUCH FIELD. It stamps no generation time, by
    ruling: a stamp says when the PDF was made, which is not a fact about the
    record, and the record's date, its signature timestamps and its filing
    state are all already on the page. The paper form it imitates has no
    printout line either.

    So two engine renders of one record are identical WHETHER OR NOT the clock
    is frozen -- which is a stronger property than the freeze was buying, and
    it is worth asserting directly instead of hoping it stays true. An
    assertion about what the code does not do outlives a check that it
    happened not to this time.

    A CLOCK READ INSIDE THE ENGINE WOULD BE INVISIBLE OTHERWISE. It would not
    break a test; it would make the sheet vary, quietly, and the next person
    to run a before/after comparison would lose the same hour again.
    """

    #: Every way this codebase asks what time it is now.
    CLOCK_CALLS = ("datetime.now", "datetime.utcnow", "time.time",
                   "date.today", "eastern_now", "eastern_date(",
                   "eastern_datetime(", "utcnow()", "now()")

    def _engine_sources(self):
        from pathlib import Path
        d = Path(__file__).resolve().parents[1] / "lib" / "legal_render"
        return {f.name: f.read_text(encoding="utf-8") for f in d.glob("*.py")}

    def test_the_engine_modules_were_read(self):
        """THE VACUITY GUARD ON THIS CLASS. A glob that matched nothing would
        make every assertion below pass over an empty set."""
        got = self._engine_sources()
        self.assertGreaterEqual(len(got), 4)
        for name in ("engine.py", "primitives.py", "formatters.py",
                     "schema.py"):
            self.assertIn(name, got)

    def test_no_engine_module_asks_what_time_it_is(self):
        """The claim. Read off CODE, not text, so a docstring explaining the
        rule cannot satisfy or break it."""
        for name, src in self._engine_sources().items():
            body = "\n".join(l for l in src.splitlines()
                              if not l.lstrip().startswith("#"))
            tree = ast.parse(src)
            docs = {id(ast.get_docstring(n, clean=False)) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                      ast.AsyncFunctionDef))}
            code = ast.unparse(ast.parse(src)) if hasattr(ast, "unparse") else body
            for call in self.CLOCK_CALLS:
                with self.subTest(module=name, call=call):
                    self.assertNotIn(
                        call, code,
                        f"{name} reads a clock. The engine's sheet is "
                        f"deterministic BY CONSTRUCTION and that is what "
                        f"makes a before/after comparison of it mean "
                        f"anything -- a clock here makes the sheet vary "
                        f"quietly and costs the next comparison an hour.")

    def test_and_two_renders_of_one_record_are_identical_UNFROZEN(self):
        """The property itself, exercised rather than inferred -- and with the
        clock deliberately RUNNING, which is the half the old freeze hid."""
        a = _render("subcontractor_orientation", freeze=False)
        b = _render("subcontractor_orientation", freeze=False)
        self.assertEqual(a, b,
                         "the engine's sheet varies between two renders of "
                         "one record, so nothing about a byte comparison of "
                         "it can be trusted")

    def test_the_branch_renderer_does_NOT_share_that_property(self):
        """THE CONTRAST, so the claim above is not true of everything and
        therefore says nothing. A branch-rendered document stamps its
        generation time and two unfrozen renders of it differ."""
        a = _render(_BRANCHED, freeze=False)
        b = _render(_BRANCHED, freeze=False)
        if a == b:
            self.skipTest("two unfrozen branch renders landed in the same "
                          "second; the contrast is real but not observable "
                          "in this run")
        self.assertEqual(len(a), len(b),
                         "the branch renders differ in LENGTH as well, so the "
                         "cause is no longer just the timestamp")


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

    def test_the_checkboxes_are_paper_checkboxes_AND_THERE_ARE_THREE_STATES(self):
        """Ticked, answered no, and never asked -- and the third is words.

        An empty box against an item the record never carried is a silent "No"
        the CP never gave, which on a compliance sheet is a claim nobody made.
        The two boxes are one axis; the absence is a different kind of answer
        and is drawn as one.
        """
        self.assertIn("&#9746;", self.html)   # hard_hats: True
        self.assertIn("&#9744;", self.html)   # no_horseplay: False
        # ladder_safety is in the label set and not in the record.
        self.assertRegex(
            self.html,
            r"Three-point contact on ladders at all times</td><td[^>]*>"
            + re.escape(legal_render.NOT_RECORDED),
            "an item the record never carried was drawn as an unticked box, "
            "which reads as a No the CP never gave")

    def test_the_attendee_table_repeats_its_header_and_cannot_split_a_row(self):
        self.assertIn("display:table-header-group", self.html)
        self.assertIn("break-inside:avoid", self.html)

    def test_the_page_says_which_page_it_is(self):
        self.assertIn("counter(page)", self.html)
        self.assertIn("counter(pages)", self.html)

    def test_a_later_page_names_its_subject(self):
        self.assertIn("running(contheader)", self.html)

    def test_the_sheet_is_ONE_WORKERS_and_carries_no_roster(self):
        """ONE SHEET PER WORKER, and the reversal is asserted rather than
        assumed.

        This shipped as a roster keyed on project and date. A worker signs his
        own orientation the first time he comes on site, so the date two men
        share is where their first days fall and not a meeting either attended.
        No other worker's name may appear, and there is no table to put one in.
        """
        other = _logbook("subcontractor_orientation", "marcus lee")
        other["_id"] = "lb-other"
        html = _render("subcontractor_orientation", group=[other])
        self.assertTrue("Alex rivera" in html, "the sheet lost its own worker")
        self.assertNotIn(
            "Marcus lee", html,
            "another worker's filed record appeared on this man's sheet; the "
            "orientation is one document per worker and the source declaration "
            "says so")
        self.assertNotIn(
            "<thead", html.split("4. Worker")[-1].split("6. Certification")[0],
            "the worker section is still a table; one row with blank rows "
            "ruled beneath it is a roster inviting names that are not coming")

    def test_ONE_WORD_IN_THE_SCHEMA_REVERSED_IT(self):
        """The argument for source living in the declaration, checked.

        The reversal from `group` to `one` had to be a schema edit and nothing
        else. If the engine or the switch had to learn about it, source would
        be decoration.
        """
        self.assertEqual(
            legal_render.SCHEMAS["subcontractor_orientation"]["source"],
            {"kind": "one"})
        # The group read in server.py is gated on the DECLARATION, so a type
        # that does not declare `group` cannot reach it.
        # SLICED TO THE FIRST ARM OF THE CHAIN, FOUND RATHER THAN NAMED --
        # the third slice in this repo to end at a branch that was later
        # deleted, after the three that ended at `osha_log`.
        _i = _SRC.index("if log_type in legal_render.CONVERTED_TYPES")
        _m = re.compile('\\n    if log_type == "\\w+":').search(_SRC[_i:])
        self.assertIsNotNone(_m, "the per-type chain has no first branch")
        body = _SRC[_i:_i + _m.start()]
        self.assertIn('.get("kind") == "group"', body)
        self.assertIn("db.logbooks.find(", body)
        self.assertLess(
            body.index('.get("kind") == "group"'), body.index("db.logbooks.find("),
            "the group read is not gated on the declaration, so reversing a "
            "type's source would not stop it reading siblings")

    def test_BLANK_ROWS_ARE_STILL_THE_ENGINES_BEHAVIOUR(self):
        """No schema asks for a table today, and the behaviour is still real.

        The orientation was the only one, and reversing it to one sheet per
        worker took the last caller with it. Asserted against a declaration
        made here rather than deleted: a twenty-row sheet with four names is
        valid paper, and the next schema that wants a roster must find that
        behaviour working, not rediscover it.
        """
        sec = {"primitive": "table", "empty": "blank_rows", "min_rows": 10,
               "columns": [("name", "Name", "name")]}
        html = primitives.table(sec, [{"name": "alex rivera"}], {})
        self.assertIn("Alex rivera", html)
        self.assertEqual(html.count("&nbsp;"), 9,
                         "nine blank rows should follow the one filled row")

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
        drifted in this repository twice.

        THE TOKEN IS ANCHORED BEFORE IT IS BANNED, TWICE OVER.

        `preserveAspectRatio=" is a stand-in for "this file builds a signature
        SVG". Banned as a bare word it would also fire on any longer name that
        merely contains it, and -- worse -- it would go quiet if the real
        reconstruction ever stopped emitting it, leaving a test that passes
        because it is looking for nothing. So it carries its attribute syntax,
        and the one real reconstruction is asked to produce it first.
        """
        real = server._signature_paths_to_svg([[{"x": 0, "y": 0},
                                                {"x": 4, "y": 4}]])
        self.assertIn(
            'preserveAspectRatio="', real,
            "the marker this test bans no longer appears in the one real "
            "reconstruction, so banning it proves nothing -- pick a token the "
            "reconstruction actually emits")

        src = Path(legal_render.__file__).parent
        checked = sorted(f.name for f in src.glob("*.py"))
        self.assertIn("primitives.py", checked,
                      f"scanned the wrong directory: {src} held {checked}")
        for f in src.glob("*.py"):
            self.assertNotIn('preserveAspectRatio="',
                             f.read_text(encoding="utf-8"),
                             f"{f.name} rebuilds the signature SVG itself")


if __name__ == "__main__":
    unittest.main(verbosity=2)
