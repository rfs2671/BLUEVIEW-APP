"""A page that borrows its sheet number says so (Roy, ruling 136).

Q2 on 588 Boyland: "AR - 6.9.26 (Gas change).pdf" page 2 prints no sheet number
(its title block reads "Roof Plan"); the office recorded that it REPLACES
A-105.01, so the glyph pass writes its rows as sheet A-105.01. A row carries no
marker that the number was lent, and the citation "A-105.01 - AR - 6.9.26 (Gas
change).pdf p2" read as if the sheet printed it. Ruling 136:

    "citations for that page show "A-105.01 (gas-change set, unnumbered)"
    with the printed title visible."

DERIVED AT RENDER OR QUERY TIME from the answered `replaces` questions and the
replacing page's own index record; nothing is stored. A replacing page that
prints its own number (gas A-100.00) is not tagged: its number is its own.

  A. the pure rule (plan_sources): the set's name, which pages are unnumbered;
  B. the three renders: the chat's evidence, the fallback render, the takeoff
     export's `sheets` and `source` columns;
  C. the lookup (server._plan_file_sources) reads the stored answers;
  D. the gate: the tag is removed with the other citations, so a claim that
     cites it binds EXACTLY as the same claim without it.

A control on main fails by AssertionError (the tag is absent there); the
mutations in the report each fail one test here.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_sources as P  # noqa: E402
from lib import plan_takeoff_export as X  # noqa: E402
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402

GAS = "AR - 6.9.26 (Gas change).pdf"
TAG = 'A-105.01 (gas-change set, unnumbered) "Roof Plan"'
MARK = {"sheet": "A-105.01", "title": "Roof Plan", "set": "gas-change set"}


def _src(**kw):
    base = {"file_id": "fg", "file_name": GAS, "track": "filed", "set_name": "filed set",
            "filed": True, "label": "", "unnumbered": {2: dict(MARK)}}
    base.update(kw)
    return base


def _row(sheet="A-105.01", page=2, quote="ROOF DRAIN RD-1", **kw):
    r = {"record_type": "schedule", "page_id": f"pg{page}", "file_id": "fg", "file_name": GAS,
         "page_number": page, "sheet_number": sheet, "quote": quote, "tier": "native_text",
         "payload": {}}
    r.update(kw)
    return r


DECISION = {
    "_id": "ea33f26741467e17", "project_id": "p1", "status": "answered", "answer": "replaces",
    "replacements": [
        {"page_id": "pg2", "file_id": "fg", "page_number": 2, "sheet_number": None,
         "sheet_title": "Roof Plan", "takes_sheet_number": "A-105.01",
         "replaces": {"page_id": "po7", "file_id": "fo", "page_number": 7,
                      "sheet_number": "A-105.01"}},
        {"page_id": "pg1", "file_id": "fg", "page_number": 1, "sheet_number": "A-100.00",
         "sheet_title": "FIRST FLOOR PLAN", "takes_sheet_number": "A-100.00",
         "replaces": {"page_id": "po3", "file_id": "fo", "page_number": 3,
                      "sheet_number": "A-100.01"}}]}
PAGES = {"pg2": {"_id": "pg2", "file_id": "fg", "file_name": GAS, "page_number": 2,
                 "sheet_number": "", "sheet_title": "Roof Plan"},
         "pg1": {"_id": "pg1", "file_id": "fg", "file_name": GAS, "page_number": 1,
                 "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN"}}
FILES = {"fg": {"_id": "fg", "name": GAS}}


class TheSetsName(unittest.TestCase):
    """THE RULE: the set's own label; else the file's name without its
    extension and dates -- the last parenthesised phrase if any -- lower-cased,
    hyphenated, plus " set"."""

    def test_the_gas_change_file(self):
        self.assertEqual(P.set_name(GAS), "gas-change set")

    def test_a_name_without_parentheses_keeps_what_is_left(self):
        self.assertEqual(P.set_name("Mechanical 6.9.26.pdf"), "mechanical set")

    def test_an_admin_label_wins(self):
        self.assertEqual(P.set_name(GAS, "owner's post-CO set"), "owner's post-CO set")

    def test_nothing_left_names_no_set(self):
        self.assertEqual(P.set_name("6.9.26.pdf"), "")
        self.assertEqual(P.unnumbered_tag("A-105.01", {"sheet": "A-105.01", "title": "", "set": ""}),
                         "A-105.01 (unnumbered)")


class WhichPagesAreUnnumbered(unittest.TestCase):

    def test_an_unnumbered_replacing_page_is_marked_and_a_numbered_one_is_not(self):
        got = P.unnumbered_marks([DECISION], PAGES, FILES)
        self.assertEqual(got, {"fg": {2: MARK}})
        self.assertNotIn(1, got["fg"], "gas A-100.00 prints its own number: no tag")

    def test_only_an_answered_replaces_question_marks_a_page(self):
        for change in ({"status": "open"}, {"status": "withdrawn"}, {"answer": "include"},
                       {"answer": "exclude"}):
            self.assertEqual(P.unnumbered_marks([dict(DECISION, **change)], PAGES, FILES), {}, change)

    def test_the_pages_own_record_decides_not_the_stored_answer(self):
        # the answer was stored when the page had no number; the index now has one
        pages = {"pg2": dict(PAGES["pg2"], sheet_number="A-105.01")}
        self.assertEqual(P.unnumbered_marks([DECISION], pages, FILES), {})

    def test_a_record_that_does_not_carry_the_given_number_is_not_tagged(self):
        # a pass that could not apply the answer wrote no A-105.01 for this page
        self.assertEqual(P.tag_sheet("A-105.01", _src(), 2), TAG)
        self.assertEqual(P.tag_sheet("A-999.00", _src(), 2), "A-999.00")
        self.assertEqual(P.tag_sheet("A-105.01", _src(), 3), "A-105.01")
        self.assertEqual(P.tag_sheet("A-105.01", _src(**{"unnumbered": {}}), 2), "A-105.01")


class TheChatEvidenceSaysIt(unittest.TestCase):

    def test_the_record_is_shown_with_the_tag_and_the_title(self):
        text = server._render_records_for_model([_row()], "roof drain", sources={"fg": _src()})
        self.assertIn(f"[{TAG} · {GAS} p2 · filed set]", text)

    def test_a_numbered_replacing_page_keeps_its_plain_citation(self):
        row = _row(sheet="A-100.00", page=1, quote="FIRST FLOOR PLAN")
        text = server._render_records_for_model([row], "first floor", sources={"fg": _src()})
        self.assertIn(f"[A-100.00 · {GAS} p1 · filed set]", text)
        self.assertNotIn("unnumbered", text)

    def test_a_non_filed_set_is_still_named_after_the_tag(self):
        src = _src(track="post_co", set_name="owner's set", filed=False)
        text = server._render_records_for_model([_row()], "roof drain", sources={"fg": src})
        self.assertIn(f'[{TAG} (owner\'s set) · {GAS} p2]', text)


class TheFallbackRenderSaysIt(unittest.TestCase):

    def test_the_gates_fallback_cites_the_tag(self):
        out = S.render_records([_row()], "roof drain", sources=[_src()])
        self.assertIn(f"[{TAG}]", out)

    def test_it_reads_a_dict_of_sources_too(self):
        self.assertIn(TAG, S.render_records([_row()], "roof drain", sources={"fg": _src()}))

    def test_a_numbered_page_is_plain(self):
        out = S.render_records([_row(sheet="A-100.00", page=1)], "roof drain", sources=[_src()])
        self.assertIn("[A-100.00]", out)
        self.assertNotIn("unnumbered", out)

    def test_without_sources_it_is_what_it_was(self):
        self.assertIn("[A-105.01]", S.render_records([_row()], "roof drain"))


class TheTakeoffExportSaysIt(unittest.TestCase):

    def test_sheets_and_source_columns(self):
        sheets, src = X._source([_row(record_type="glyph")], {"fg": _src()})
        self.assertEqual(sheets, TAG)
        self.assertEqual(src, f"{TAG}: {GAS} p2")

    def test_a_numbered_page_beside_it_is_plain(self):
        rows = [_row(record_type="glyph"), _row(record_type="glyph", sheet="A-100.00", page=1)]
        sheets, src = X._source(rows, {"fg": _src()})
        self.assertEqual(sheets, f"A-100.00, {TAG}")
        self.assertEqual(src, f"A-100.00: {GAS} p1; {TAG}: {GAS} p2")

    def test_the_review_queue_still_gets_bare_sheet_numbers(self):
        sheets, _ = X._source([_row(record_type="glyph"),
                               _row(record_type="glyph", sheet="A-100.00", page=1)], {"fg": _src()})
        self.assertEqual(X.sheet_numbers(sheets), ["A-100.00", "A-105.01"])
        self.assertEqual(X.sheet_numbers("A-100.00, M-100.00"), ["A-100.00", "M-100.00"])

    def test_a_built_line_carries_it_end_to_end(self):
        from tests import test_a_takeoff_line_is_one_the_gate_binds as G
        src = dict(G.SOURCES)
        src["f-filed"] = dict(src["f-filed"], **{"unnumbered": {4: {
            "sheet": "A-101.00", "title": "Roof Plan", "set": "gas-change set"}}})
        t = X.build(G._world(), G.AREAS, src)
        tagged = 'A-101.00 (gas-change set, unnumbered) "Roof Plan"'
        mine = [ln for ln in t.lines + t.refused if tagged in ln.sheets]
        self.assertTrue(mine, "no exported line cites the borrowed number with its tag")
        for ln in mine:
            self.assertIn(f"{tagged}: AR - 8.18.26.pdf p4", ln.source)
            # the number printed on the same page is not tagged
            self.assertNotIn("A-100.00 (", ln.sheets)
        # the quantities are those of the build without any mark
        base = X.build(G._world(), G.AREAS, G.SOURCES)
        self.assertEqual([(ln.item, ln.tag, ln.scope, ln.level, ln.qty, ln.set_label)
                          for ln in t.lines],
                         [(ln.item, ln.tag, ln.scope, ln.level, ln.qty, ln.set_label)
                          for ln in base.lines])


class TheLookupReadsTheStoredAnswers(unittest.TestCase):

    def _db(self, decision=DECISION, pages=PAGES):
        db = AsyncFakeDB()
        db.project_files.docs.append({"_id": "fg", "project_id": "p1", "name": GAS})
        db.plan_set_questions.docs.append(dict(decision))
        db.document_page_index.docs.extend(dict(p) for p in pages.values())
        return db

    def test_the_source_of_the_gas_file_carries_the_unnumbered_page(self):
        with patch.object(server, "db", self._db()):
            got = asyncio.run(server._plan_file_sources("p1", ["fg"]))
        self.assertEqual(got["fg"]["unnumbered"], {2: MARK})
        self.assertEqual(got["fg"]["file_name"], GAS)

    def test_no_answer_no_mark(self):
        with patch.object(server, "db", self._db(dict(DECISION, status="open"))):
            got = asyncio.run(server._plan_file_sources("p1", ["fg"]))
        self.assertNotIn("unnumbered", got["fg"])

    def test_an_unreadable_store_is_the_citation_as_it_was(self):
        db = self._db()

        db.plan_set_questions.find = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        with patch.object(server, "db", db):
            got = asyncio.run(server._plan_file_sources("p1", ["fg"]))
        self.assertNotIn("unnumbered", got["fg"])


class TheLocatedEvidenceBlocksSayItToo(unittest.TestCase):
    """The located-symbol, opening and area text names a SHEET with no file or
    page beside it ("ROOF HVAC PLANS [A-105.01 / M-105.00]: WH-1 3"); the number
    is tagged there when every record that gives it comes from the marked page."""

    SRC = {"fg": _src()}
    MECH = _row(sheet="M-105.00", page=7, file_id="fm", file_name="MH.pdf", record_type="glyph",
                payload={"arch": {"sheet_number": "A-105.01", "file_id": "fg", "page_number": 2,
                                  "page_id": "pg2"}})

    def test_a_number_given_by_the_marked_page_only_is_labelled(self):
        got = P.borrowed_labels([_row(record_type="glyph"), self.MECH], self.SRC)
        self.assertEqual(got, {"A-105.01": TAG})

    def test_the_architectural_page_a_mechanical_symbol_sits_on_counts(self):
        got = P.borrowed_labels([self.MECH], self.SRC)
        self.assertEqual(got, {"A-105.01": TAG})
        self.assertNotIn("M-105.00", got)

    def test_the_same_number_on_another_page_is_left_bare(self):
        # A-105.01 of the set the gas roof replaced is still indexed: the block
        # cannot say which page "A-105.01" means, so it does not say.
        other = _row(page=7, file_id="fo", file_name="AR - 8.18.26.pdf")
        self.assertEqual(P.borrowed_labels([_row(), other], self.SRC), {})

    def test_the_block_text_is_relabelled_in_place(self):
        labels = {"A-105.01": TAG}
        self.assertEqual(P.label_borrowed("ROOF HVAC PLANS [A-105.01 / M-105.00]: WH-1 3", labels),
                         f"ROOF HVAC PLANS [{TAG} / M-105.00]: WH-1 3")
        self.assertEqual(P.label_borrowed("on A-105.01.", labels), f"on {TAG}.")
        self.assertEqual(P.label_borrowed("A-105.011 and XA-105.01 and A-105.01.5", labels),
                         "A-105.011 and XA-105.01 and A-105.01.5")

    def test_the_files_a_render_needs_include_the_architectural_page_of_a_mechanical_symbol(self):
        # the chat looked up only each record's own file: the gas file, which
        # holds the page a mechanical symbol sits on, had no source row
        self.assertEqual(server._record_file_ids([self.MECH, _row(record_type="glyph")]), ["fm", "fg"])

    def test_the_chat_render_applies_it_to_the_located_block(self):
        block = "- per the filed set: Roof Plan [A-105.01]: W3 2"
        with patch.object(S, "render_glyph_evidence", lambda recs: block):
            text = server._render_records_for_model([self.MECH], "W3", sources=self.SRC)
        self.assertIn(f"Roof Plan [{TAG}]: W3 2", text)
        with patch.object(S, "render_glyph_evidence", lambda recs: block):
            plain = server._render_records_for_model([self.MECH], "W3", sources={"fg": _src(**{"unnumbered": {}})})
        self.assertIn("Roof Plan [A-105.01]: W3 2", plain)


class TheTagAddsNoFigure(unittest.TestCase):
    """The gate removes the tag and the printed title with the file and set
    citations (#910), so "105.01", a set name's digits and a title's digits are
    never read as figures, and a claim citing the tag binds exactly as the
    same claim citing the bare sheet."""

    def _verdict(self, text, rows, sources):
        return S.answer_is_grounded(text, rows, intent="count", sources=sources)

    def test_a_claim_with_the_tag_binds_as_the_same_claim_without_it(self):
        rows = [_row(quote="RD-1 ROOF DRAIN QTY 4")]
        for claim in ("There are 4 RD-1 on {s}.", "There are 5 RD-1 on {s}.",
                      "There are 4 RD-1 on {s} in {f}.", "There are 105 RD-1 on {s}."):
            plain = self._verdict(claim.format(s="A-105.01", f=GAS), rows, [_src()])
            # a title and a set name that carry digits are the hard case
            for tag in (TAG, 'A-105.01 (588-thomas-boyland set, unnumbered) "ROOF PLAN LEVEL 7"',
                        'A-105.01 (unnumbered)'):
                tagged = self._verdict(claim.format(s=tag, f=GAS), rows, [_src()])
                self.assertEqual(tagged, plain, (claim, tag))

    def test_the_tag_removed_leaves_the_bare_sheet(self):
        self.assertEqual(S.strip_source_citations(f"On {TAG}, 4 drains.", [], []).split(), ["On", "A-105.01,", "4", "drains."])

    def test_digits_in_a_set_name_or_a_title_are_not_figures(self):
        text = 'On A-105.01 (588-thomas-boyland-st set, unnumbered) "ROOF PLAN LEVEL 7" there are 4.'
        out = S.strip_source_citations(text, [], [])
        self.assertNotIn("588", out)
        self.assertNotIn("7", out)
        self.assertIn("4", out)

    def test_the_strip_only_takes_the_tag_shape(self):
        # an ordinary parenthesis, or a figure in quotes elsewhere, is not removed
        text = 'There are 9 (not 4) of "type 7".'
        self.assertEqual(S.strip_source_citations(text, [], []), text)


if __name__ == "__main__":
    unittest.main()
