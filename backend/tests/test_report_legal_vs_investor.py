"""THE INVESTOR REPORT CARRIES NO FILING APPARATUS — CHECKED BY CALL GRAPH.

WHY THIS FILE EXISTS, AND IT IS NOT THE OBVIOUS REASON.

The affirmation banner was ruled off the combined report and the change shipped:
thirteen `render_signature_html` call sites in `generate_combined_report` were
given `show_affirmation=False`. I verified it by counting occurrences of
`show_affirmation` in `server.py` — sixteen — and reported the item closed.

It was rendering. There is a FOURTEENTH call site, inside
`_superintendent_log_html`, a builder SHARED by the legal PDF and the combined
report, which passed no flag at all and took the `True` default.

**AND IT WAS NOT AN OVERSIGHT — CORRECTING MY OWN FIRST ACCOUNT OF THIS.** I
reported it as a call site nobody had seen. `test_report_document_layout.py`
named it explicitly and asserted it KEPT its banner, with a reason: the
superintendent's section shares its builder with the legal renderer and "is the
one signature here that is also its own filed legal record". Somebody found the
fourteenth site, thought about it, and decided for it. The operator has now
decided against it — sharing a builder is a fact about the code, not about the
reader — and the inspector still gets the full audit trail from the per-logbook
PDF.

So the lesson is narrower than "a count missed a call site", and it is still
worth the walk: **a count of a keyword cannot distinguish a call site that omits
it deliberately from one that omits it by accident.** Sixteen occurrences of
`show_affirmation` was consistent with both. The call graph is what makes the
question answerable: from `generate_combined_report`, follow every function it
calls, and require that every `render_signature_html` reached along the way is
passed `show_affirmation=False` — so a new section cannot inherit the default
silently, whichever way anyone meant it.

WHAT WAS GENUINELY INVISIBLE was the rendering. `_filed_log(logbooks,
"site_superintendent_log")` returned nothing until the first superintendent log
was ever filed, so no report anyone had read contained the section at all. The
decision was made in code and never seen on paper until the day it was.

── WHAT THIS FILE DOES NOT COVER, AND WHERE THAT LIVES ───────────────────────

SIGNATURES, NOT MARKERS. This walk works by asserting a keyword argument, so it
can only hold things that take one. "Added after filing" is a photograph
caption produced from a flag on the photograph; it takes no argument, there was
no convention for it to violate, and it rendered on the investor report through
two rulings against it -- eight times on the 2026-09-09 report -- while
rendering zero times on the per-logbook PDF where it was ruled to stay.

`test_the_legal_apparatus_markers.py` holds that class: a registry of markers
checked against RENDERED OUTPUT, each one asserted absent from the investor
render and present on the legal one. Read them together; this file's title
promises more than a call-graph walk can deliver on its own.

THE FLAG. `legal_record=True` on `_superintendent_log_html` gates three things
that are one thing — the AFFIRMED banner, the BC 3301.13.13 citations, and the
attestation paragraph. All are the audit trail of a §3301 filing: what a DOB
inspector needs and a lender does not.
"""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_PATH = Path(server.__file__)
_SRC = _PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
#: The same file with comments and docstrings STRIPPED. The use-count below is
#: of USES; this function's docstring names the flag in order to explain it, and
#: counting the prose as a use is the same mistake as counting a keyword to
#: prove a call site passes it.
_CODE = code_of("server.py")

_FUNCS = {
    n.name: n for n in ast.walk(_TREE)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
}


def _calls_in(fn):
    """Every function NAME called inside `fn`, direct calls only."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            out.add(n.func.id)
    return out


#: THE ONE PLACE THE WALK STOPS, AND WHY IT IS NOT A HOLE.
#:
#: `_logbook_thumbnail_url` renders the PER-LOGBOOK LEGAL PDF and rasterises
#: page one into a PNG for a card on the project record. That PDF is the filed
#: record and MUST carry its full apparatus -- the affirmed banner, the
#: citations, the attestation -- because the card links to exactly that
#: document and a picture showing something else would misrepresent what the
#: reader is about to open.
#:
#: THE WALK FOLLOWS HTML COMPOSITION INTO THE INVESTOR PAGE. This function
#: composes nothing: it returns a URL. Its output reaches the report as
#: `<img src=...>`, and an image of a legal document is not the investor report
#: asserting the apparatus -- it is the index showing what it indexes.
#:
#: EXEMPTED BY NAME, WITH THE CLAIM ASSERTED. The alternative was to render the
#: thumbnail with `legal_record=False`, which would make the picture and the
#: link disagree. A named exemption whose premise is checked is better than a
#: silently weakened rule -- the same structure `find-unpinned-palette-keys`
#: uses for Toast.
_RENDERS_TO_AN_IMAGE = {"_logbook_thumbnail_url"}


def _reachable(root: str, seen=None) -> set:
    """Transitive closure of direct calls from `root`, within this module.

    Stops at `_RENDERS_TO_AN_IMAGE` -- see the note above it.
    """
    seen = seen if seen is not None else set()
    if root in seen or root not in _FUNCS:
        return seen
    seen.add(root)
    if root in _RENDERS_TO_AN_IMAGE:
        return seen
    for name in _calls_in(_FUNCS[root]):
        _reachable(name, seen)
    return seen


def _signature_calls_under(root: str):
    """Every `render_signature_html(...)` call node in `root`'s call graph,
    tagged with the function it sits in."""
    out = []
    for fname in _reachable(root):
        for n in ast.walk(_FUNCS[fname]):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "render_signature_html"):
                out.append((fname, n))
    return out


class NoSignatureIsReachableFromTheInvestorReportAtAll(unittest.TestCase):
    """THE CHECK THAT WOULD HAVE CAUGHT IT, ASKING FOR MORE.

    It required every reachable signature to be SILENCED. The report embeds no
    filed document now, so it reaches no signature renderer whatsoever -- and
    "none" is a property a future section cannot satisfy by accident, whereas
    "all of them pass a flag" is one somebody can break by adding a call that
    forgets it. The walk is unchanged; only what it must find is.

    THE VACUITY PROBLEM IS THE WHOLE POINT OF THIS FILE, so it is not solved
    by lowering the old `>= 13` to `>= 0`. It is solved by running the SAME
    walk from the filed renderer, where the answer must still be many.
    """

    def test_the_call_graph_is_actually_being_walked(self):
        """A closure that returns only the root passes every assertion below
        vacuously. This is the empty-set guard, and it now runs against the
        renderer that still composes filed documents."""
        reached = _reachable("generate_single_logbook_html")
        self.assertIn("generate_single_logbook_html", reached)
        self.assertIn("_superintendent_log_html", reached,
                      "the shared builder is no longer reached — the walk broke")
        self.assertGreater(len(reached), 5)

    def test_the_report_itself_is_still_walked(self):
        """And the report's own closure is non-trivial, so "reaches no
        signature" is a fact about a walk that went somewhere."""
        reached = _reachable("generate_combined_report")
        self.assertIn("generate_combined_report", reached)
        self.assertGreater(len(reached), 5)

    def test_every_reachable_signature_call_passes_show_affirmation_false(self):
        offenders = []
        for fname, call in _signature_calls_under("generate_combined_report"):
            kw = {k.arg: k.value for k in call.keywords}
            v = kw.get("show_affirmation")
            ok = (isinstance(v, ast.Constant) and v.value is False) or (
                # the shared builder forwards the caller's flag; the call site
                # that supplies it is asserted separately below
                isinstance(v, ast.Name) and v.id == "legal_record")
            if not ok:
                offenders.append(f"{fname}:{call.lineno}")
        self.assertEqual(
            offenders, [],
            "these signatures print the AFFIRMED banner on the investor "
            f"report: {offenders}",
        )

    def test_the_report_reaches_no_signature_renderer_at_all(self):
        """THE ASSERTION, INVERTED. Thirteen call sites were reachable and all
        thirteen had to be silenced; zero are reachable now."""
        found = _signature_calls_under("generate_combined_report")
        self.assertEqual(
            [f"{f}:{c.lineno}" for f, c in found], [],
            "the investor report composes a signature again")

    def test_and_the_walk_still_finds_many_from_the_filed_renderer(self):
        """THE GUARD ON THE ASSERTION ABOVE. An empty result is the shape a
        BROKEN WALK produces, which is exactly what this file exists to refuse
        -- so emptiness only counts as evidence while the same walk, on the
        same machinery, still returns a crowd from the document renderer."""
        found = _signature_calls_under("generate_single_logbook_html")
        # 9 -> 7. The orientation branch carried two `render_signature_html`
        # calls -- the worker's and the conducting party's -- and it was
        # deleted when that type's conversion finished. The sheet still prints
        # both, through the engine's `signature` primitive, which this walk
        # cannot see because it looks for one function by name.
        #
        # THE NUMBER IS NOT THE CLAIM. It is the vacuity guard on the assertion
        # above: an empty result from this walk is the shape a BROKEN walk
        # produces, so emptiness only counts as evidence while the same walk
        # still returns a crowd from the document renderer.
        self.assertGreaterEqual(
            len(found), 7,   # measured, 2026-09-12
            f"only {len(found)} signature calls reached from the filed "
            "renderer; the walk is broken, so the empty result above proves "
            "nothing")

    def test_the_exemption_is_ONE_function_and_its_premise_holds(self):
        """A named exemption is only as good as the claim behind it, so the
        claim is checked: it renders to an IMAGE, it is embedded as one, and it
        is the only name on the list."""
        self.assertEqual(_RENDERS_TO_AN_IMAGE, {"_logbook_thumbnail_url"},
                         "a second exemption is the rule being weakened")
        body = _SRC[_SRC.index("async def _logbook_thumbnail_url("):]
        body = body[:body.index("\ndef ")]
        self.assertIn("_render_logbook_thumbnail", body,
                      "the exempt function no longer rasterises anything")
        self.assertIn("return _public_temp_media_url", body,
                      "it no longer returns a URL, so it may be composing "
                      "HTML into the investor page after all")
        # EMBEDDED BY THE RENDERER, NOT BY server.py. The card markup moved
        # into lib/report/renderer.py with the rest of the layout; the claim
        # -- that this URL reaches the page as an image and not as composed
        # document HTML -- is read there.
        _CARDS = (_PATH.parent / "lib" / "report" / "renderer.py").read_text(
            encoding="utf-8")
        self.assertIn('<img src="{esc(card.thumbnail)}"', _CARDS,
                      "its output is not embedded as an image")

    def test_the_exempt_function_IS_reached__it_is_not_dead(self):
        """An exemption for something nothing calls proves nothing. This is
        the vacuity guard on the guard."""
        self.assertIn("_logbook_thumbnail_url",
                      _calls_in(_FUNCS["generate_combined_report"]))

    def test_the_shared_builder_is_the_one_that_broke_it(self):
        """Named, so a future reader knows which call site the walk exists
        for rather than rediscovering it.

        READ OFF THE FILED RENDERER NOW. The builder is shared no longer: the
        report reaches it through nothing, which is the finding above. What is
        worth keeping is the NAME -- a reader who hits a failure here should
        land on the call site that made this file necessary."""
        names = {f for f, _ in
                 _signature_calls_under("generate_single_logbook_html")}
        self.assertIn("_superintendent_log_html", names)


class TheLegalPdfKeepsEverything(unittest.TestCase):
    """The flag must not have taken the apparatus off the filing."""

    def test_the_default_is_the_legal_record(self):
        sig = inspect.signature(server._superintendent_log_html)
        p = sig.parameters["legal_record"]
        self.assertIs(p.default, True)
        self.assertIs(p.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_the_per_logbook_pdf_passes_nothing_and_so_inherits_true(self):
        i = _SRC.index("body_html = _superintendent_log_html(")
        # ANCHORED: the bare identifier would also match a comment
        # mentioning the flag. What must be absent is the ARGUMENT.
        self.assertNotIn("legal_record=", _SRC[i:i + 200])

    def test_nothing_opts_out_any_more_and_that_is_recorded(self):
        """THE OPT-OUT HAS NO CALLER LEFT, and saying so is the point.

        `legal_record=False` existed for exactly one caller: the investor
        report's embedded copy of the superintendent's log. The report embeds
        nothing, so the flag's False branch is now unreached code.

        IT IS KEPT AND PINNED AT ZERO rather than deleted here. Deleting a
        gate that takes the audit apparatus off a §3301 record is a decision
        about the filing, not a tidy-up, and it belongs in its own change with
        its own reading. What must not happen quietly is the opposite: a new
        caller switching the apparatus off without anyone deciding to. This
        assertion fails the moment one appears.
        """
        self.assertEqual(
            _SRC.count("legal_record=False"), 0,
            "something opts the superintendent's log out of its own audit "
            "apparatus again; that was a decision last time and must be one "
            "this time")

    def test_the_flag_gates_all_three_and_nothing_else(self):
        """Counted on STRIPPED code. The first draft counted the raw file and
        got 5 — the docstring names the flag in order to explain it, so the
        prose was being counted as a use. Same shape as the keyword count that
        missed the fourteenth call site in the first place."""
        body = _CODE[_CODE.index("def _superintendent_log_html("):]
        body = body[:body.index("\ndef render_signature_html(")]
        self.assertIn('if legal_record else ""', body)          # citations
        self.assertIn("CS_LOG_ATTESTATION_HTML if legal_record", body)
        self.assertIn("show_affirmation=legal_record", body)
        self.assertEqual(body.count("legal_record"), 4)          # 3 uses + param


class TheRenderedOutputSaysSo(unittest.TestCase):
    """Executed, not read. The three items are asserted on real HTML from the
    real builder, because a source check passes on a flag that is threaded and
    never consulted."""

    LOG = {
        "date": "2026-09-04",
        "data": {
            "presence": {"arrived_at": "7:00 AM", "departed_at": "4:00 PM",
                         "signature": {"data": "iVBORw0KGgo",
                                       "signer_name": "michael cespedes"}},
            "progress": {"summary": "Framing on 1 and 2."},
        },
    }

    def test_the_legal_pdf_prints_citations_the_attestation_and_the_banner(self):
        html = server._superintendent_log_html(self.LOG)
        self.assertIn("BC 3301.13.13", html)
        self.assertIn(server.CS_LOG_ATTESTATION, html)

    def test_the_investor_report_prints_none_of_them(self):
        html = server._superintendent_log_html(self.LOG, legal_record=False)
        self.assertNotIn("BC 3301.13.13", html)
        self.assertNotIn("1 RCNY", html)
        self.assertNotIn(server.CS_LOG_ATTESTATION, html)
        self.assertNotIn("AFFIRMED", html)

    def test_the_content_itself_is_identical_either_way(self):
        """The apparatus comes off; the RECORD does not change. A lender and an
        inspector must read the same facts."""
        for fragment in ("Framing on 1 and 2.", "7:00 AM", "4:00 PM"):
            self.assertIn(fragment, server._superintendent_log_html(self.LOG))
            self.assertIn(fragment, server._superintendent_log_html(
                self.LOG, legal_record=False))

    def test_the_signature_image_survives_on_both(self):
        for legal in (True, False):
            html = server._superintendent_log_html(self.LOG, legal_record=legal)
            self.assertIn("<img", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
