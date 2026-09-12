"""A FILED DOCUMENT KEEPS ITS APPARATUS WHEN ITS RENDERER CHANGES.

── WHAT HAPPENED, BECAUSE IT IS THE WHOLE REASON THIS FILE EXISTS ────────────

The orientation sheet was the first type through the declarative engine. It
rendered, it was read, its old branch was deleted, and the control run showed
92 of 92 production records byte-for-byte identical between the whole document
and the engine's sheet.

That control run was correct, complete, and answered a different question than
the one that mattered. Byte-identical proved the OLD BRANCH WAS UNREACHABLE. It
proved nothing whatever about whether the sheet still said what the old sheet
said, because BOTH SIDES OF THE COMPARISON WERE THE NEW ENGINE.

Two things were gone, and they were gone in production for three days:

    92 of 92 orientation sheets carried neither AFFIRMED nor UNAFFIRMED
    89 CP signatures had said AFFIRMED, with a claimed and a received time
    79 worker signatures had said UNAFFIRMED
    15 amended records had said AMENDED RECORD and said nothing

THE THIRD LINE IS THE ONE THAT SHOULD DECIDE HOW THIS FILE IS MAINTAINED.
UNAFFIRMED is a DEFICIENCY MARKER: it states that no affirmation record exists
for that mark. Removing it does not make a document look broken. It makes a
deficient document look clean, on a filed BC 3301.13.13 record about a named
man. A loss that fails toward looking BETTER is the one nobody reports.

── WHY NEITHER PIECE WAS VISIBLE FROM ANYWHERE A REVIEWER WOULD LOOK ─────────

Both live OUTSIDE the per-type branch, and the dispatch returns:

    generate_single_logbook_html
      the per-type switch      ->  return _sheet        <-- a converted type
      the per-type chain            exits here             exits HERE
      the AMENDED RECORD banner is composed BELOW the chain
      the document is wrapped BELOW that

So reading the schema, the engine and the branch side by side -- which is what a
reviewer does -- shows nothing missing. The missing things are in the function
that WRAPS all three, after the point a converted type has already left.

That is the class of defect this file is written against, and the last class
below is the general guard rather than the two specific instances.
"""

from __future__ import annotations

import ast
import asyncio
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import legal_render  # noqa: E402
from lib.legal_render import primitives  # noqa: E402

_SRC = io.open(BACKEND / "server.py", encoding="utf-8").read()
_TREE = ast.parse(_SRC)

_PROJECT = {"_id": "p1", "name": "588 Thomas",
            "address": "588 Thomas S Boyland Street",
            "company_name": "Metro Build Constructors LLC",
            "bbl": "3035400025", "nyc_bin": "3255362"}

#: A stroke, so the mark itself renders and the banner has something to sit
#: under. Shape and provenance are what the tests vary, never the geometry.
_STROKES = [[{"x": 1, "y": 2}, {"x": 30, "y": 20}, {"x": 60, "y": 5}]]

#: AFFIRMED and UNAFFIRMED differ by ONE KEY, which is the point: the two
#: objects are otherwise indistinguishable, and a renderer that loses the
#: distinction loses it silently.
#: THE KEY NAMES ARE THE BANNER'S, NOT PLAUSIBLE ONES. This fixture first said
#: `affirmed_at` and `received_at`, which read perfectly well and are not what
#: `_signature_affirmation_html` looks for -- so the banner printed with no
#: times in it and the test asserting the times failed against correct code.
AFFIRMED = {"paths": _STROKES, "signerName": "daniel kaplan", "affirmed": True,
            "affirmedAt": "2026-08-04T19:56:00Z",
            "affirmed_received_at": "2026-08-04T19:56:00Z"}
UNAFFIRMED = {"paths": _STROKES, "signerName": "alex rivera"}


def _logbook(log_type="subcontractor_orientation", *, amended=False,
             cp_sig=AFFIRMED, worker_sig=UNAFFIRMED):
    lb = {
        "_id": "lb1", "project_id": "p1", "date": "2026-09-09",
        "log_type": log_type, "cp_name": "daniel kaplan", "status": "submitted",
        "cp_signature": cp_sig,
        "data": {"worker_name": "alex rivera",
                 "worker_company": "Premier Builders Inc.",
                 "worker_trade": "carpenter", "language_provided": "English",
                 "completed_at": "2026-09-09T07:00:00",
                 "checklist": {"hard_hats": True, "safety_boots": True,
                               "no_horseplay": False},
                 "worker_signature": worker_sig,
                 "entries": [], "activities": [], "attendees": [],
                 "signins": [], "workers": []},
    }
    if amended:
        lb["is_amendment"] = True
        lb["amendment_reason"] = "the crew count was transcribed wrong"
        lb["created_by_name"] = "Rosa Delgado"
        lb["created_at"] = "2026-09-11T14:02:00Z"
    return lb


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


def _render(logbook):
    """The whole filed document, clock frozen. See
    test_the_legal_render_engine.py's note on why the freeze is mandatory."""
    stack = [patch.object(server, "db", _DB([])),
             patch.object(server, "to_query_id", lambda v: v),
             patch.object(server, "eastern_datetime", lambda *a, **k: "FROZEN")]
    for p in stack:
        p.start()
    try:
        return asyncio.run(server.generate_single_logbook_html(logbook))
    finally:
        for p in reversed(stack):
            p.stop()


def _ctx():
    return {"project": dict(_PROJECT), "contractor": "Metro Build",
            "address": "588 Thomas", "date": "2026-09-09",
            "date_line": "Date: 2026-09-09",
            "signature_svg": server._signature_paths_to_svg,
            "signature_affirmation": server._signature_affirmation_html}


def _verdict(html: str) -> str:
    """Which claim a rendering makes about a mark. UNAFFIRMED is checked first
    because AFFIRMED is a substring of it -- the bare-literal trap this harness
    has been caught by before."""
    if "UNAFFIRMED" in html:
        return "unaffirmed"
    if "AFFIRMED" in html:
        return "affirmed"
    return "silent"


# ══════════════════════════════════════════════════════════════════════════
#  THE AFFIRMATION BANNER
# ══════════════════════════════════════════════════════════════════════════

class TheSheetSaysWhetherTheMarkWasAffirmed(unittest.TestCase):

    def setUp(self):
        self.html = _render(_logbook())

    def test_an_affirmed_signature_says_so_on_the_engines_sheet(self):
        self.assertIn("AFFIRMED for this document", self.html)

    def test_and_carries_the_two_times_that_make_it_an_audit_trail(self):
        """The banner is not a badge. It is a claimed time and a
        server-received time, which is what an inspector reads it for."""
        self.assertIn("claimed", self.html)
        self.assertIn("server-received", self.html)

    def test_an_unaffirmed_signature_prints_its_deficiency(self):
        """THE ASSERTION THIS FILE EXISTS FOR. 79 filed records lost exactly
        this line, and a record with the warning removed reads as a clean
        one."""
        self.assertIn("UNAFFIRMED", self.html)
        self.assertIn("no affirmation record for this document", self.html)

    def test_both_appear_on_ONE_sheet(self):
        """The two marks on this document disagree, and the sheet has to say
        so per-mark rather than reach a verdict about the page."""
        self.assertIn("AFFIRMED for this document", self.html)
        self.assertIn("UNAFFIRMED", self.html)


class TheTwoRenderersOfOneSignatureMakeTheSameClaim(unittest.TestCase):
    """THE DRIFT GUARD, AND THE ONE THAT GENERALISES.

    `render_signature_html` draws a mark for the twelve unconverted types and
    `ink` draws it for the converted ones. While both exist they are two
    renderers of one object, and this repo's standing lesson is that two
    renderers of one section drift -- it has had to pull this exact pair back
    twice already.

    So the test is not "does the banner appear". It is "do the two functions
    reach the SAME VERDICT about the same signature", across every shape
    production actually holds.
    """

    #: Every shape the collection carries, including the two that look alike.
    SHAPES = {
        "affirmed vector": AFFIRMED,
        "unaffirmed vector": UNAFFIRMED,
        "affirmed raster": {"data": "iVBORw0KGgo=", "affirmed": True,
                            "affirmedAt": "2026-08-04T19:56:00Z"},
        # AFFIRMED, AND THE CLAIMED TIME FAILED VALIDATION. A fourth state the
        # banner draws: it prints the affirmation and refuses to present the
        # claimed time as fact.
        "affirmed with an unverified claim": {
            "paths": _STROKES, "affirmed": True,
            "affirmedAt": "1999-01-01T00:00:00Z",
            "affirmed_received_at": "2026-08-04T19:56:00Z",
            "affirmation_flag": "CLAIM_BEFORE_RECORD"},
        "unaffirmed raster": {"data": "iVBORw0KGgo="},
        # `not {}` is False, which is how an empty dict satisfied every
        # presence gate in the app while every document it signed printed
        # UNAFFIRMED. Named in _is_affirmed_signature's own docstring.
        "the empty dict production held": {},
        "a bare base64 string": "iVBORw0KGgo=",
    }

    def test_every_shape_gets_the_same_verdict_from_both(self):
        for name, sig in self.SHAPES.items():
            with self.subTest(shape=name):
                old = server.render_signature_html(sig, "X")
                new = primitives.ink(sig, _ctx(), present=True)
                self.assertEqual(
                    _verdict(old), _verdict(new),
                    f"the branch renderer and the engine disagree about a "
                    f"{name}: the filed document says one thing about this "
                    f"mark and the same document under the other renderer "
                    f"says another")

    def test_the_shapes_do_not_all_reach_the_same_verdict(self):
        """THE VACUITY GUARD. Two renderers that both print nothing agree
        perfectly, and the assertion above would pass on a pair of functions
        that had each lost the banner."""
        got = {_verdict(server.render_signature_html(s, "X"))
               for s in self.SHAPES.values()}
        self.assertIn("affirmed", got)
        self.assertIn("unaffirmed", got)


class NoMarkMeansNoBanner(unittest.TestCase):
    """The banner is a statement ABOUT A SIGNATURE. Over an absent one it would
    be a statement about nothing, and the branch renderer returns early rather
    than make it."""

    def test_an_absent_key_draws_neither_mark_nor_banner(self):
        self.assertEqual(primitives.ink(None, _ctx(), present=False), "")

    def test_a_present_and_empty_key_says_UNSIGNED_and_nothing_else(self):
        """UNSIGNED is a claim about the RECORD -- it was asked for and not
        signed -- and it stands alone. A missing affirmation on a missing
        signature is not a second deficiency."""
        out = primitives.ink(None, _ctx(), present=True)
        self.assertIn("UNSIGNED", out)
        self.assertEqual(_verdict(out), "silent")

    def test_and_the_old_renderer_agrees(self):
        self.assertEqual(server.render_signature_html(None, "X"), "")


class TheBannerIsNotCOPIEDINTOTheEngine(unittest.TestCase):
    """ONE SPELLING OF THE CLAIM.

    `_signature_affirmation_html` carries an argument about what this product
    may assert about a mark: that it says UNAFFIRMED and no longer says
    "inherited", because nothing on a signature records its origin. A second
    copy inside the engine is a second place for that argument to be
    half-remembered, which is precisely how `signature_svg` came to be passed
    in rather than reimplemented.
    """

    #: Wording only `_signature_affirmation_html` is allowed to produce.
    ITS_WORDS = ("affirmation record for this document", "server-received",
                 "AFFIRMED for this document")

    def test_the_engine_holds_no_wording_of_its_own(self):
        """ASKED OF THE STRINGS THE MODULE EMITS, not of its text. The first
        version of this test grepped the file and failed on the docstring that
        explains the rule -- which is the bare-literal trap in a new costume: a
        claim about OUTPUT, checked against SOURCE, catches the prose."""
        for name in ("primitives.py", "engine.py"):
            src = io.open(BACKEND / "lib" / "legal_render" / name,
                          encoding="utf-8").read()
            tree = ast.parse(src)
            docs = {id(ast.get_docstring(n, clean=False))
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.ClassDef,
                                      ast.FunctionDef, ast.AsyncFunctionDef))}
            emitted = [n.value for n in ast.walk(tree)
                       if isinstance(n, ast.Constant)
                       and isinstance(n.value, str)
                       and id(n.value) not in docs]
            for word in self.ITS_WORDS:
                with self.subTest(module=name, word=word):
                    self.assertFalse(
                        [t for t in emitted if word in t],
                        f"{name} emits the affirmation banner's own wording. "
                        f"One function is allowed to make that claim, and a "
                        f"second spelling of it will drift from the argument "
                        f"written into the first.")

    def test_the_words_are_the_ones_that_function_ACTUALLY_emits(self):
        """THE VACUITY GUARD. A renamed banner would leave the census above
        asserting the absence of three strings nothing produces any more."""
        both = (server._signature_affirmation_html(AFFIRMED)
                + server._signature_affirmation_html(UNAFFIRMED))
        for word in self.ITS_WORDS:
            with self.subTest(word=word):
                self.assertIn(word, both)

    def test_it_arrives_through_ctx_like_the_stroke_reconstruction(self):
        # assertTrue, NOT assertIn: the haystack is the whole of server.py and
        # assertIn prints its haystack. test_an_assertion_may_not_print_a_
        # source_file caught this one the first time it ran, which is the
        # entire purpose of that gate and worth leaving the note for.
        self.assertTrue(
            '"signature_affirmation": _signature_affirmation_html' in _SRC,
            "the affirmation renderer is not handed to the engine, so every "
            "converted type draws marks with no claim attached to them")

    def test_and_an_engine_with_no_affirmation_in_ctx_still_draws_the_mark(self):
        """A caller without the machinery -- a preview, a test -- renders
        exactly what it rendered before rather than failing."""
        bare = {k: v for k, v in _ctx().items()
                if k != "signature_affirmation"}
        out = primitives.ink(AFFIRMED, bare, present=True)
        self.assertTrue(out.strip(), "the mark itself disappeared")
        self.assertEqual(_verdict(out), "silent")


# ══════════════════════════════════════════════════════════════════════════
#  THE AMENDMENT BANNER
# ══════════════════════════════════════════════════════════════════════════

class AnAmendedRecordSaysSoWhicheverRendererDrawsIt(unittest.TestCase):

    def test_the_engines_sheet_carries_it(self):
        html = _render(_logbook(amended=True))
        self.assertIn("AMENDED RECORD", html)
        self.assertIn("the crew count was transcribed wrong", html)

    def test_and_names_who_and_when(self):
        """Not just that it changed. Somebody changed it."""
        html = _render(_logbook(amended=True))
        self.assertIn("Rosa Delgado", html)

    def test_a_branch_rendered_type_still_carries_it(self):
        """The half that must not break: twelve types still render through the
        chain and the banner was already reaching them."""
        html = _render(_logbook("daily_jobsite", amended=True))
        self.assertIn("AMENDED RECORD", html)

    def test_an_unamended_record_says_nothing(self):
        self.assertNotIn("AMENDED RECORD", _render(_logbook()))

    def test_a_reasonless_amendment_is_its_own_state(self):
        """amend_logbook refuses one, but a script or a migration can write
        one, and collapsing it into "not amended" hides a correction."""
        lb = _logbook(amended=True)
        lb["amendment_reason"] = ""
        html = _render(lb)
        self.assertIn("AMENDED RECORD", html)
        self.assertIn("NO REASON WAS RECORDED", html)


# ══════════════════════════════════════════════════════════════════════════
#  THE GENERAL GUARD
# ══════════════════════════════════════════════════════════════════════════

class ApparatusComposedBelowTheDispatchCannotReachAConvertedType(
        unittest.TestCase):
    """THE TEST THAT WOULD HAVE CAUGHT BOTH, AND CATCHES THE NEXT ONE.

    Neither loss was a bug in the engine or in the schema. Both were pieces of
    the document composed in the WRAPPING function, below the line where a
    converted type returns. Nothing about reading the engine, the schema or the
    branch reveals them, which is why three people read the conversion and
    shipped it.

    So the guard is positional. Anything on this list is apparatus that belongs
    on EVERY filed document regardless of type, and it must be composed above
    the dispatch and handed over -- not composed below it, where only the
    twelve unconverted types will ever see it.

    ADD TO THIS LIST when a new piece of whole-document apparatus arrives. The
    cost of forgetting is not a broken page; it is a filed statutory record
    that quietly stops saying something.
    """

    #: name -> the assignment that composes it.
    #:
    #: ONE CANDIDATE IS DELIBERATELY NOT ON THIS LIST YET. The old document's
    #: header carried STATUS: SUBMITTED or STATUS: DRAFT and the engine's
    #: letterhead carries neither, so 3 of 92 orientation records are drafts
    #: that no longer say so (defect A17). It is the same shape as the two
    #: below and it is left off on purpose: the status sat in the dark header
    #: the redesign replaced, so where it belongs on a sheet designed to look
    #: like filed paper is a decision, not a restoration. Add it here when that
    #: decision is made -- this comment is the reminder, and the defect
    #: document is the record.
    WHOLE_DOCUMENT_APPARATUS = {
        "the amendment banner": "amendment_html = (",
    }

    def setUp(self):
        node = next(n for n in ast.walk(_TREE)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "generate_single_logbook_html")
        self.fn = "".join(
            _SRC.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
        self.exit = self.fn.index("return _sheet")

    def test_the_dispatch_still_returns_where_this_test_thinks_it_does(self):
        """THE VACUITY GUARD. A renamed dispatch would make every assertion
        below compare against an index of -1 and pass."""
        self.assertGreater(self.exit, 0)
        self.assertIn("legal_render.CONVERTED_TYPES", self.fn[:self.exit])

    def test_every_piece_is_composed_above_the_line_that_returns(self):
        for name, anchor in self.WHOLE_DOCUMENT_APPARATUS.items():
            with self.subTest(apparatus=name):
                at = self.fn.find(anchor)
                self.assertGreater(at, 0, f"{name}: {anchor!r} not found; "
                                          f"this guard is out of date")
                self.assertLess(
                    at, self.exit,
                    f"{name} is composed BELOW the dispatch, which returns. "
                    f"Every converted type will render a document without it, "
                    f"and nothing about that document will look wrong.")

    def test_and_each_one_is_actually_handed_to_the_engine(self):
        """Composing it above the line is half. An engine that is never given
        it is the same silence with a tidier cause."""
        arm = self.fn[:self.exit]
        i = arm.index("legal_render.render(")
        self.assertIn('"amendment_html": amendment_html', arm[i:])

    def test_the_engine_places_what_it_is_given(self):
        src = io.open(BACKEND / "lib" / "legal_render" / "engine.py",
                      encoding="utf-8").read()
        self.assertIn('ctx.get("amendment_html")', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
