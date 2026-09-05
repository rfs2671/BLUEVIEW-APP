"""The combined report as a DOCUMENT: pages, banners, columns, type.

Four changes to what the investor report prints, none of which any existing
test covered, and every one of them asserted here against RENDERED HTML rather
than against the source that produces it:

  1. EVERY FILED DOCUMENT ON ITS OWN PAGE. There was exactly one page break in
     the report, between the investor cover and everything after it, so
     fourteen separate statutory filings ran together down a continuous
     column.

  2. NO WEATHER ON THE COVER. It is a field of the daily jobsite log and it is
     printed in that log's section; on the cover it was a second copy of the
     same string with no document behind it.

  3. THE AFFIRMATION BANNER IS FOR THE LEGAL RECORD. "AFFIRMED for this
     document", a claimed time and a server-received time under each of
     thirteen signatures is the audit trail of a §3301 filing. The per-logbook
     PDF and the superintendent's log keep it; the investor report does not.

  4. NO Confirmed / Present COLUMNS on the toolbox roster. Neither is a legal
     attestation -- the CP signature over the whole sheet is -- and the stored
     fields are untouched.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

DATE = "2026-08-11"
PROJECT = "proj_layout"

BREAK = '<div style="page-break-after:always;"></div>'
WRAPPER = '<div class="doc-section" style="page-break-inside:avoid;">'


def _match(doc, query):
    for k, v in (query or {}).items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query))


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


_SIG = {"affirmed": True, "affirmedAt": "2026-08-11T21:10:00Z",
        "signer_name": "Carl Cespedes", "data": "aGk="}


def lb(_id, log_type, data, sig=None):
    return {"_id": _id, "project_id": PROJECT, "date": DATE,
            "log_type": log_type, "is_deleted": False, "is_locked": True,
            "status": "submitted", "cp_name": "Carl Cespedes",
            "cp_signature": copy.deepcopy(_SIG if sig is None else sig),
            "data": data}


JOBSITE = lb("lb_dj", "daily_jobsite", {
    "weather": "Partly cloudy", "weather_temp": "78F",
    "weather_fetch_state": "ok",
    "general_description": "pile caps poured on the east half.",
    "activities": [{"crew_id": "C-1", "company": "Kestrel Electric",
                    "trade": "Electrical", "num_workers": 6,
                    "work_description": "branch rough-in",
                    "work_locations": "3rd floor", "photos": []}],
    "equipment_on_site": {"man_lift": True},
    "checklist_items": {"permits": {"result": "pass", "note": ""}},
    "observations": [],
})

TOOLBOX = lb("lb_tb", "toolbox_talk", {
    "location": "north gate", "company_name": "AAZ", "performed_by": "Carl",
    "meeting_time": "07:30 AM", "checked_topics": {"hard_hats": True},
    "attendees": [
        # BOTH FLAGS TRUE, so the absence of the two columns is about the
        # columns and not about a fixture that never set them.
        {"name": "wilmer carrillo", "title": "foreman", "company": "aaz",
         "time": "2026-08-11T10:47:05Z", "signed": True,
         "gate_confirmed": True, "added_from": "gate"},
    ],
})

PRESHIFT = lb("lb_ps", "preshift_signin", {
    "company": "AAZ", "project_location": "588 Boyland", "total_count": 1,
    "workers": [{"name": "wilmer carrillo", "company": "aaz",
                 "osha_number": "12345678", "had_injury": "No",
                 "inspected_ppe": "Yes"}],
})

SUPER = lb("lb_cs", "site_superintendent_log", {
    "presence": {"printed_name": "Michael Cespedes",
                 "arrived_at": "06:45", "departed_at": "16:30",
                 "signature": copy.deepcopy(_SIG)},
})


class Base(unittest.TestCase):
    DOCS = [JOBSITE, TOOLBOX, PRESHIFT, SUPER]

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs = [{
            "_id": PROJECT, "name": "588 Thomas S Boyland Street",
            "address": "588 Thomas S Boyland St, Brooklyn",
            "project_class": "regular",
        }]
        self.db.logbooks.docs = [copy.deepcopy(d) for d in self.DOCS]
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        self.loop.close()

    def rendered(self):
        """NAMED FOR THE SCANNER as well as for the reader.
        test_absence_literals_are_specific classifies a haystack as source text
        from the NAME of the call that produced it, and `run_until_complete`
        told it nothing -- so every assertNotIn below was landing in the
        unclassified bucket and going unaudited. Its own history says to teach
        the classifier rather than raise its ceiling; this is the cheap half of
        that: call the helpers what they are.
        """
        return self.loop.run_until_complete(
            server.generate_combined_report(PROJECT, DATE))

    def rendered_single(self, logbook):
        return self.loop.run_until_complete(
            server.generate_single_logbook_html(logbook))

    def rendered_content(self, html=None):
        """The CONTENT cell only -- not the shell, whose <style> block now
        legitimately contains the words page-break-after."""
        h = html if html is not None else self.rendered()
        return h[h.index("<!-- CONTENT -->"):h.index("<!-- FOOTER -->")]


# ══════════════════════════════════════════════════════════════════════════
#  1e  EVERY DOCUMENT ON ITS OWN PAGE
# ══════════════════════════════════════════════════════════════════════════

class EveryFiledDocumentStartsASheet(Base):
    def test_a_break_between_every_pair_of_sections(self):
        """N sections, N-1 breaks. Counted rather than pinned, so this stays
        true when a section is added."""
        c = self.rendered_content()
        wrappers = c.count(WRAPPER)
        self.assertGreaterEqual(wrappers, 5,
                                "the fixture should render several sections")
        self.assertEqual(c.count(BREAK), wrappers - 1)

    def test_the_document_does_NOT_end_on_a_break(self):
        """A break after the last section ends the PDF on a blank sheet, and a
        blank final page on a compliance record reads as a page somebody
        removed."""
        c = self.rendered_content().rstrip()
        self.assertFalse(c.endswith(BREAK))
        tail = c[c.rindex(BREAK) + len(BREAK):]
        self.assertTrue(tail.startswith(WRAPPER), tail[:120])
        self.assertIn("Pre-Shift Sign-In", tail)

    def test_every_section_asks_not_to_be_split(self):
        c = self.rendered_content()
        self.assertEqual(c.count("page-break-inside:avoid"), c.count(WRAPPER))

    def test_an_UNFILED_log_claims_no_sheet(self):
        """A section with no document behind it renders "" -- it must not take
        a blank page with it, or a three-document day prints as sixteen sheets
        with thirteen of them looking like filings that went missing."""
        full = self.rendered_content()
        self.db.logbooks.docs = [copy.deepcopy(JOBSITE)]
        one = self.rendered_content()
        self.assertEqual(one.count(BREAK), 1)      # cover, then the log
        self.assertEqual(one.count(WRAPPER), 2)
        self.assertGreater(full.count(WRAPPER), one.count(WRAPPER))

    def test_the_cover_is_still_the_first_page(self):
        c = self.rendered_content()
        self.assertIn("Daily Progress Report", c[:c.index(BREAK)])
        self.assertNotIn("Daily Jobsite Log", c[:c.index(BREAK)])

    def test_every_break_is_immediately_followed_by_the_next_section(self):
        """A break with anything but a section wrapper after it is a sheet
        break in the middle of one document."""
        c = self.rendered_content()
        self.assertEqual(c.count(BREAK + WRAPPER), c.count(BREAK))


class ThePrintSheetCarriesTheRestOfIt(Base):
    """The @media print block released the wrapper width and stopped."""

    def setUp(self):
        super().setUp()
        h = self.rendered()
        # SLICED FORWARD FROM THE BLOCK, not to the first "</style>": the
        # document opens with an mso-only <style> block, so the first close tag
        # sits BEFORE this one and the slice came back empty -- an assertNotIn
        # would have passed on it, silently.
        _i = h.index("@media print")
        raw = h[_i:h.index("</style>", _i)]
        self.block = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)

    def test_a_heading_is_never_the_last_thing_on_a_page(self):
        self.assertIn("page-break-after: avoid", self.block)
        self.assertIn(".doc-section-title", self.block)

    def test_a_table_row_is_never_split_across_the_fold(self):
        self.assertIn("tr {", self.block)
        self.assertIn("page-break-inside: avoid", self.block)

    def test_the_section_header_loses_its_top_margin_on_its_own_sheet(self):
        self.assertIn("margin-top: 0 !important", self.block)

    def test_the_width_release_is_still_there(self):
        """The control: this block already did one thing and must keep doing
        it."""
        self.assertIn("max-width: 100% !important", self.block)


# ══════════════════════════════════════════════════════════════════════════
#  1g  THE AFFIRMATION MARKER IS FOR THE LEGAL RECORD
# ══════════════════════════════════════════════════════════════════════════

class TheInvestorReportDropsTheAffirmationBanner(Base):
    def test_no_affirmation_banner_on_the_thirteen_call_sites(self):
        """Everything EXCEPT the superintendent's log, which shares its builder
        with the legal renderer and deliberately keeps its banner -- see
        test_the_superintendents_log_KEEPS_its_banner below."""
        c = self.rendered_content()
        # THE SUPERINTENDENT'S SECTION IS NO LONGER CUT OUT. It used to be
        # excised here because it kept its banner by design; the ruling removed
        # that exception, so the whole document is now asserted at once and the
        # sibling test below covers the section specifically.
        self.assertNotIn("AFFIRMED for this document", c)
        self.assertNotIn("claimed ", c)
        self.assertNotIn("server-received", c)

    def test_and_the_UNAFFIRMED_warning_goes_with_it(self):
        """The operator has accepted this for THIS document. Asserted on a log
        whose signature is genuinely unaffirmed, so the absence is the
        parameter and not the fixture."""
        self.db.logbooks.docs[0]["cp_signature"] = {"data": "aGk="}
        c = self.rendered_content()
        self.assertNotIn("UNAFFIRMED", c)

    def test_THE_SIGNATURE_ITSELF_IS_STILL_THERE(self):
        """The whole risk of this change. Only the banner goes."""
        c = self.rendered_content()
        self.assertIn("CP Signature", c)
        self.assertIn("data:image/png;base64,", c)

    def test_the_superintendents_log_DROPS_its_banner_TOO(self):
        """REVERSED BY RULING, AND THE OLD REASONING IS KEPT BECAUSE IT WAS NOT
        AN OVERSIGHT.

        This test used to assert the opposite, with a written rationale: the
        superintendent's section shares its builder with the legal renderer, so
        its affirmation "carries on the investor report too ... deliberate: it
        is the one signature here that is also its own filed legal record."

        The operator read a filed investor report and ruled against that. The
        argument that lost is worth stating: sharing a builder is a fact about
        the code, not about the reader. A lender does not need the §3301 audit
        trail because the same bytes also serve an inspector -- the inspector
        gets it from the per-logbook PDF, which still prints every banner.

        So the fourteenth call site now forwards `legal_record`, and this is
        the one section whose behaviour changed."""
        c = self.rendered_content()
        cs = c[c.index("Superintendent Signature"):]
        self.assertNotIn("AFFIRMED for this document", cs)

    def test_the_per_logbook_PDF_keeps_every_banner(self):
        html = self.rendered_single(copy.deepcopy(TOOLBOX))
        self.assertIn("AFFIRMED for this document", html)

    def test_the_default_is_STILL_to_show_it(self):
        """A new call site inherits the legal record's behaviour, never the
        investor report's. Opting out has to be typed."""
        html = server.render_signature_html({"data": "aGk="}, "CP Signature")
        self.assertIn("UNAFFIRMED", html)

    def test_it_is_ONE_renderer_with_a_parameter_not_two(self):
        tree = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and "signature_html" in n.name and n.name != "_signature_affirmation_html"]
        self.assertEqual([f.name for f in fns], ["render_signature_html"])
        args = [a.arg for a in fns[0].args.args]
        self.assertIn("show_affirmation", args)

    def test_every_combined_report_call_site_opts_out(self):
        """Thirteen of them. A section added later without the flag puts the
        audit trail back on the lender's copy, and this says so."""
        tree = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "generate_combined_report")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "render_signature_html"]
        self.assertEqual(len(calls), 13)
        for c in calls:
            self.assertTrue(
                any(k.arg == "show_affirmation" and k.value.value is False
                    for k in c.keywords),
                f"line {c.lineno} still prints the affirmation banner")

    def test_and_the_legal_renderers_do_NOT(self):
        """The control. Passing the flag everywhere would satisfy the test
        above and destroy the audit trail on the document an inspector reads."""
        tree = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))
        # `_superintendent_log_html` is no longer in this list: it now FORWARDS
        # `legal_record` rather than passing nothing, so the legal PDF still
        # gets the banner (default True) while the investor report does not.
        # The control's point is unchanged -- a hardcoded False anywhere here
        # would destroy the audit trail on the document an inspector reads --
        # and it is asserted below in the form the code now takes.
        for name, n_expected in (("generate_single_logbook_html", 8),):
            fn = next(n for n in ast.walk(tree) if getattr(n, "name", None) == name)
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name)
                     and n.func.id == "render_signature_html"]
            self.assertEqual(len(calls), n_expected, name)
            for c in calls:
                self.assertEqual([k.arg for k in c.keywords], [], f"{name}:{c.lineno}")
        fn = next(n for n in ast.walk(tree)
                  if getattr(n, "name", None) == "_superintendent_log_html")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "render_signature_html"]
        self.assertEqual(len(calls), 1)
        kw = {k.arg: k.value for k in calls[0].keywords}
        self.assertIsInstance(kw.get("show_affirmation"), ast.Name)
        self.assertEqual(kw["show_affirmation"].id, "legal_record")


# ══════════════════════════════════════════════════════════════════════════
#  1h  THE TOOLBOX ROSTER'S TWO TICK COLUMNS
# ══════════════════════════════════════════════════════════════════════════

class TheToolboxRosterHasNoTickColumns(Base):
    def _rendered_roster(self):
        c = self.rendered_content()
        c = c[c.index("Tool Box Talk"):]
        return c[:c.index("</table>", c.index("Added by"))]

    def test_neither_column_is_in_the_header(self):
        head = self._rendered_roster()
        self.assertNotIn(">Confirmed<", head)
        self.assertNotIn(">Present<", head)

    def test_and_no_row_carries_a_tick(self):
        self.assertNotIn("&#10003;", self._rendered_roster())

    def test_the_columns_that_remain(self):
        head = self._rendered_roster()
        for col in (">Name<", ">Title<", ">Company<", ">In<", ">Added by<"):
            self.assertIn(col, head)

    def test_added_by_STAYS_because_provenance_is_the_real_question(self):
        self.assertIn("Gate", self._rendered_roster())

    def test_the_FIELDS_are_untouched_in_storage(self):
        """A rendering change, not a data change. Both flags are still on the
        stored document after a render, and toolboxTalkModel.js still writes
        and defaults them."""
        self.rendered()
        stored = self.db.logbooks.docs[1]["data"]["attendees"][0]
        self.assertTrue(stored["signed"])
        self.assertTrue(stored["gate_confirmed"])
        model = (_BACKEND.parent / "frontend" / "src" / "utils"
                 / "toolboxTalkModel.js").read_text(encoding="utf-8")
        self.assertIn("gate_confirmed", model)
        self.assertIn("signed", model)


# ══════════════════════════════════════════════════════════════════════════
#  1i  A SCALE, NOT FOUR SIZES WITHIN A POINT OF EACH OTHER
# ══════════════════════════════════════════════════════════════════════════

class TheTypeHasRanks(Base):
    def test_a_section_header_is_substantially_larger_than_the_body(self):
        c = self.rendered_content()
        head = c[c.index("Daily Jobsite Log") - 400:c.index("Daily Jobsite Log")]
        m = re.search(r"font-size:(\d+)px", head)
        self.assertIsNotNone(m, head)
        self.assertGreaterEqual(int(m.group(1)), 22,
                                "a section header is not a bolder sentence")

    def test_the_header_is_bold_and_not_merely_semibold(self):
        c = self.rendered_content()
        i = c.index("Daily Jobsite Log")
        self.assertIn("font-weight:700", c[i - 400:i])

    def test_the_gaps_say_which_boundary_they_are(self):
        """A section header, its description and its content were separated by
        12, 12 and 12 -- three different relationships rendered identically."""
        c = self.rendered_content()
        i = c.index("Daily Jobsite Log")
        section = c[i - 400:i + 900]
        self.assertIn("margin:40px 0 0 0", section)   # between documents
        self.assertIn("margin:14px 0 0 0", section)   # header to description
        self.assertIn("margin:8px 0 0 0", section)    # label to its table

    def test_the_table_label_is_a_caption_not_a_smaller_heading(self):
        c = self.rendered_content()
        i = c.index("Activity Details")
        self.assertIn("text-transform:uppercase", c[i - 300:i])
        self.assertIn("letter-spacing:0.08em", c[i - 300:i])


# ══════════════════════════════════════════════════════════════════════════
#  FOUND WHILE RENDERING THE BEFORE/AFTER PAIR
# ══════════════════════════════════════════════════════════════════════════

class ItemOneDoesNotPrintTheSignatureAsText(unittest.TestCase):
    """The Construction Superintendent Log printed the signature OBJECT into
    item 1's Record cell.

    superintendentLogModel.js lists `signature` among the presence FIELDS, so
    _cs_item_body reached it like any other field and fell through to
    `str(value)`. SignaturePad stores strokes, so a filed BC 3301.13.13 log
    rendered a Python dict repr as the superintendent's record of his own
    presence -- on both renderers, because they share the builder. A legacy
    base64 signature is a STRING, so that branch pasted the whole blob in as
    body text instead.

    Found by rendering the document and looking at it, which is the whole
    argument for the rendered-HTML tests in this file and in
    test_eastern_clock.py: nothing about the code looked wrong.
    """

    def _rendered_item_one(self, signature):
        html = server._superintendent_log_html({
            "date": DATE, "cp_name": "Carl",
            "data": {"presence": {
                "printed_name": "Michael Cespedes",
                "arrived_at": "06:45", "departed_at": "16:30",
                "signature": signature,
            }},
        })
        i = html.index("Superintendent presence")
        return html[i:html.index("</tr>", i)]

    STROKES = {"paths": [[{"x": 1, "y": 2}, {"x": 3, "y": 4}]],
               "signerName": "Michael Cespedes"}

    def test_the_stroke_object_is_not_printed(self):
        cell = self._rendered_item_one(self.STROKES)
        # ANCHORED AS THEY PRINT. str() of the stroke dict renders the keys
        # quoted -- `{'paths': [[{'x': 1, ...`  -- so the quotes are part of
        # the thing being banned, and a legitimate future word "paths" in the
        # prose of this cell is not.
        self.assertNotIn("'paths'", cell)
        self.assertNotIn("'x'", cell)

    def test_a_legacy_base64_signature_is_not_printed_either(self):
        """The branch a type check would have missed."""
        cell = self._rendered_item_one("iVBORw0KGgoAAAANSUhEUgAAA" * 40)
        self.assertNotIn("iVBORw0KGgo", cell)

    def test_the_REST_of_item_one_still_renders(self):
        """The control. Skipping the field must not empty the item."""
        cell = self._rendered_item_one(self.STROKES)
        self.assertIn("Michael Cespedes", cell)
        self.assertIn("06:45", cell)
        self.assertIn("16:30", cell)

    def test_and_the_signature_is_STILL_on_the_document(self):
        """It has a renderer of its own at the foot of the same section, which
        is why removing this copy loses nothing."""
        html = server._superintendent_log_html({
            "date": DATE, "cp_name": "Carl",
            "data": {"presence": {"printed_name": "Michael Cespedes",
                                  "signature": copy.deepcopy(_SIG)}},
        })
        self.assertIn("Superintendent Signature", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("AFFIRMED for this document", html)


if __name__ == "__main__":
    unittest.main()
