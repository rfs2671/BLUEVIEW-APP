"""The affirmation is its own signed record; the sheet stops claiming it.

REPLACES test_preshift_affirmation_overlay.py, and the history it documented is
kept here because the new design exists to answer it.

THE ORIGINAL DEFECT. The Signature column printed NOT AFFIRMED from
`signature_affirmed`, a key `preshift_signin.jsx` has NEVER written. Every filed
sheet accused every worker. On 2026-08-28 six men affirmed between 10:36 and
11:57, correctly recorded on their check-in rows, and the sheet said NOT
AFFIRMED for all sixteen.

THE FIRST FIX WAS AN OVERLAY: resolve the affirmation from the day's check-ins
at render time. It corrected the falsehood, and it left the printed document
saying something the stored document did not. Bulletin 2024-007 sec V.6 asks
that a signature's integrity be maintained with "any changes detectable after
signing", and a column whose content changes between two renderings of one
stored sheet cannot be validated against a single moment.

THE SECOND FIX, HERE, IS THAT THE COLUMN GIVES UP THE CLAIM. The affirmation
becomes a signature event written AT THE GATE at the moment it happens, with a
content hash, a signer, a capacity, a device and the exact wording read. The
sheet points at those records in a footer and asserts nothing about any named
man's affirmation -- because the stored sheet carries nothing about it.

AND NOTHING IS MIGRATED. Writing an event for an affirmation that happened
before the ledger existed would mean inventing a content hash over a snapshot
nobody hashed and a timestamp the ledger did not witness. The six from
2026-08-28 stay where they are and are counted from there -- which is possible
only because the footer counts rather than claims.
"""

import asyncio
import ast
import inspect
import os
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from tests.document_renderers import (  # noqa: E402
    N_DOCUMENT_RENDERERS as N_RENDERERS, assert_is_current)
from tests.filed_sheet import cells, sheet, visible  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")

CHECKIN_HTML = (BACKEND / "checkin.html").read_text(encoding="utf-8")

AFFIRMED_AT = datetime(2026, 8, 28, 15, 13, 12, tzinfo=timezone.utc)

# A row as the filed sheet actually stores it: no affirmation field anywhere.
STORED = {
    "worker_id": "w1",
    "name": "Cristian B Rojas",
    "company": "Arkon Builders",
    "osha_number": "JH447TBBXG",
    "worker_signature": "iVBORw0KGgo=",
    "had_injury": "No",
    "inspected_ppe": "Yes",
}


def _run(coro):
    return asyncio.run(coro)


def _code_only(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(node)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


def _db(checkins=(), events=()):
    db = MagicMock()
    db.checkins = MagicMock()
    db.checkins.find = MagicMock(return_value=_Cursor(checkins))
    db.signature_events = MagicMock()
    db.signature_events.find = MagicMock(return_value=_Cursor(events))
    return db


class TheColumnMakesNoAffirmationClaim(unittest.TestCase):
    """Neither direction. Both are claims about a record kept elsewhere."""

    def test_a_signature_on_file_prints_the_image_and_says_so(self):
        cell = server._preshift_signature_cell(STORED)
        self.assertIn("<img", cell)
        self.assertIn("Signature on file", cell)

    def test_it_NEVER_prints_NOT_AFFIRMED_again(self):
        """The original defect: a finding against a named man from a field
        nobody wrote."""
        for row in (STORED, dict(STORED, signature_affirmed=False),
                    dict(STORED, signature_affirmed=True)):
            self.assertNotIn("NOT AFFIRMED", server._preshift_signature_cell(row))

    def test_and_it_never_prints_AFFIRMED_either(self):
        """The overlay's claim. The sheet does not own it."""
        for row in (STORED, dict(STORED, signature_affirmed=True)):
            cell = server._preshift_signature_cell(row)
            self.assertNotIn("Affirmed", cell)

    def test_no_signature_on_file_is_unchanged(self):
        """Still the strongest statement this column makes, and a DIFFERENT
        fact from anything about affirmation."""
        row = {k: v for k, v in STORED.items() if k != "worker_signature"}
        self.assertIn("NO SIGNATURE ON FILE",
                      server._preshift_signature_cell(row))

    def test_the_cell_takes_no_AFFIRMATION_overlay(self):
        """THE BAN IS ON THE CLAIM, NOT ON THE ARITY, and this test now says so.

        It used to assert `params == ["w"]`. That was the right guard for the
        defect it was written against -- a render-time overlay that resolved
        AFFIRMATION from the day's check-ins and printed a claim the stored row
        did not make. Nothing may pass that again.

        A second parameter now exists and carries something different in kind:
        `resolved`, a map of signin_id -> signature IMAGE bytes. It resolves
        WHICH PICTURE TO DRAW, never whether a man affirmed. The filed sheet was
        printing NO SIGNATURE ON FILE for men whose signature was in R2, because
        the new gate stores a `signin_id` rather than an inline image -- an
        accusation against a named man produced by a lookup this function never
        made.

        So the arity assertion is replaced by the two that carry the actual
        rule: the parameter list is CLOSED at these two, and the affirmation
        fields stay unreadable (test_it_reads_only_the_signature) with no
        affirmation string printable in any state (the two tests above)."""
        params = list(inspect.signature(
            server._preshift_signature_cell).parameters)
        self.assertEqual(params, ["w", "resolved"])

    def test_a_junk_value_in_the_map_cannot_take_down_the_sheet(self):
        """WRITTEN AS AN AFFIRMATION TEST AND IT FOUND A CRASH INSTEAD.

        The first draft fed "AFFIRMED"/True/1 into the map to prove the overlay
        could not sneak back through it. `True` reached `.startswith` and raised
        AttributeError -- and a renderer that raises does not drop one row, it
        takes down the entire filed PDF. The cell now accepts only a non-empty
        string and falls through to the honest third state otherwise.

        Kept as the crash guard it turned out to be."""
        for value in (True, 1, None, [], {}, b"bytes", ""):
            cell = server._preshift_signature_cell(
                {"signin_id": "s1"}, {"s1": value})
            self.assertIn("Signature on file", cell)
            self.assertNotIn("NOT AFFIRMED", cell)

    def test_a_resolved_image_still_renders(self):
        cell = server._preshift_signature_cell(
            {"signin_id": "s1"}, {"s1": "iVBORw0KGgo"})
        self.assertIn("<img", cell)
        self.assertNotIn("Affirmed", cell)

    def test_it_reads_only_the_signature(self):
        code = _code_only(server._preshift_signature_cell)
        for frozen in ("name", "had_injury", "inspected_ppe", "company",
                       "osha_number", "signature_affirmed"):
            self.assertNotIn(f"'{frozen}'", code)


class TheFooterCountsRatherThanClaims(unittest.TestCase):
    def test_a_count_is_stated_as_a_fact_about_a_separate_record(self):
        html = server.preshift_affirmation_footer(6)
        self.assertIn("held separately", html)
        self.assertIn("not part of this sheet", html)
        self.assertIn("6 affirmations are on record", html)

    def test_one_affirmation_reads_as_one(self):
        self.assertIn("1 affirmation is on record",
                      server.preshift_affirmation_footer(1))

    def test_zero_says_NOTHING(self):
        """A sheet with no affirmations on record must not carry a line
        implying it looked and found none against anybody."""
        self.assertEqual(server.preshift_affirmation_footer(0), "")

    def test_the_footer_names_nobody(self):
        """A count is safe where a per-row mark is not, precisely because it
        attaches to no one. Anchored on the sheet's own row data rather than a
        bare word: `assertNotIn("worker", ...)` is the kind of substring ban
        test_absence_literals_are_specific exists to refuse, and it would be
        satisfied or broken by anything containing it."""
        html = server.preshift_affirmation_footer(6)
        for named in (STORED["name"], STORED["company"], STORED["osha_number"]):
            self.assertNotIn(named, html)


class TheCountSpansTheCutover(unittest.TestCase):
    """Which is what makes a permanent legacy path unnecessary."""

    def test_it_counts_pre_ledger_affirmations_from_checkin_rows(self):
        """The six from 2026-08-28 have no signature event and never will."""
        db = _db(checkins=[{"worker_id": f"w{i}"} for i in range(6)])
        self.assertEqual(
            _run(server.preshift_affirmation_count(db, "p1", "2026-08-28")), 6)

    def test_it_counts_events_for_dates_after_the_cutover(self):
        db = _db(events=[{"signer": {"user_id": f"w{i}"}} for i in range(3)])
        self.assertEqual(
            _run(server.preshift_affirmation_count(db, "p1", "2026-09-01")), 3)

    def test_a_worker_in_BOTH_sources_is_counted_ONCE(self):
        """Going forward the gate writes both, naming the same man. Double
        counting would inflate a number printed on a compliance record."""
        db = _db(checkins=[{"worker_id": "w1"}, {"worker_id": "w2"}],
                 events=[{"signer": {"user_id": "w1"}},
                         {"signer": {"user_id": "w2"}}])
        self.assertEqual(
            _run(server.preshift_affirmation_count(db, "p1", "2026-09-01")), 2)

    def test_a_failed_read_counts_ZERO_and_the_footer_says_nothing(self):
        """It must never turn a read failure into a claim."""
        db = MagicMock()
        db.checkins.find = MagicMock(side_effect=RuntimeError("down"))
        db.signature_events.find = MagicMock(side_effect=RuntimeError("down"))
        n = _run(server.preshift_affirmation_count(db, "p1", "2026-08-28"))
        self.assertEqual(n, 0)
        self.assertEqual(server.preshift_affirmation_footer(n), "")

    def test_a_missing_project_or_date_is_zero(self):
        self.assertEqual(_run(server.preshift_affirmation_count(_db(), "", "")), 0)
        self.assertEqual(_run(server.preshift_affirmation_count(None, "p", "d")), 0)

    def test_it_is_scoped_to_the_SHEETS_date(self):
        db = _db()
        _run(server.preshift_affirmation_count(db, "p1", "2026-08-28"))
        clause = db.checkins.find.call_args[0][0]["check_in_time"]
        self.assertIn("$gte", clause)
        self.assertIn("$lt", clause)

    def test_nothing_writes(self):
        code = _code_only(server.preshift_affirmation_count)
        for write in ("update_one", "insert_one", "update_many", "$set"):
            self.assertNotIn(write, code)


class TheGateWritesTheEventWhenItHappens(unittest.TestCase):
    """The only contemporaneous moment. Anything later is a record ABOUT the
    act rather than the act."""

    CODE = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = _code_only(server.register_and_checkin)

    def test_the_gate_creates_a_signature_event(self):
        self.assertIn("create_signature_event", self.CODE)
        self.assertIn("PRESHIFT_AFFIRMATION_DOC_TYPE", self.CODE)

    def test_only_when_he_actually_affirmed(self):
        self.assertIn("if _sig_affirmed:", self.CODE)

    def test_it_is_keyed_on_project_and_date_not_a_logbook_id(self):
        """A worker affirms at 06:40 and the CP files the sheet at 08:00. THE
        SHEET DOES NOT EXIST YET, so binding to a logbook id would mean either
        delaying the event past the act or inventing an id."""
        self.assertIn("preshift_affirmation_document_id", self.CODE)
        self.assertEqual(
            server.preshift_affirmation_document_id("p1", "2026-08-31"),
            "p1:2026-08-31")

    def test_the_snapshot_holds_THE_EXACT_WORDING_HE_READ(self):
        """The strongest part of this change, asserted rather than incidental:
        a signature event carrying its own text needs no external document to
        be understood years later."""
        self.assertIn("'affirmation_text': preshift_affirmation_text(_sig_lang)",
                      self.CODE)
        self.assertIn("'language': _sig_lang or None", self.CODE)

    def test_the_wording_comes_from_the_SERVER_never_the_request(self):
        """A consent whose text the client chooses is evidence of nothing."""
        self.assertNotIn("data.get('affirmation_text')", self.CODE)
        self.assertNotIn('data.get("affirmation_text")', self.CODE)

    def test_it_carries_who_where_and_on_what_device(self):
        for field in ("signer_user_id", "device_info", "ip_address",
                      "acting_capacity"):
            self.assertIn(field, self.CODE)

    def test_the_signature_is_REFERENCED_not_copied(self):
        """Duplicating the stroke would create two artefacts that can disagree
        about one signature."""
        self.assertIn("'affirmed_signature_of'", self.CODE)

    def test_it_FAILS_SOFT_and_never_costs_a_man_his_checkin(self):
        """The turnstile is not a compliance gate. An affirmation that failed
        to record is a gap on a sheet, not a locked door -- and the check-in row
        still carries signature_affirmed, so nothing is lost."""
        i = self.CODE.index("create_signature_event")
        window = self.CODE[max(0, i - 400):i + 900]
        self.assertIn("try:", window)
        self.assertIn("except Exception", window)

    def test_the_event_is_written_AFTER_the_checkin_exists(self):
        self.assertLess(self.CODE.index("checkins.insert_one"),
                        self.CODE.index("create_signature_event"))


class TheWordingHasOneDefinitionOnEachSide(unittest.TestCase):
    """Two copies of a sentence are two sentences the moment one is edited."""

    def test_the_server_carries_both_languages(self):
        self.assertEqual(set(server.PRESHIFT_AFFIRMATION_TEXTS), {"en", "es"})

    def test_each_matches_checkin_html_VERBATIM(self):
        """The gate renders its own copy client-side. If they drift, the
        snapshot records wording the worker did not read."""
        for lang, text in server.PRESHIFT_AFFIRMATION_TEXTS.items():
            self.assertIn(text, CHECKIN_HTML,
                          f"the {lang} affirmation text differs from checkin.html")

    def test_an_unknown_language_falls_back_rather_than_storing_nothing(self):
        """He read SOMETHING, and English is what the gate shows when it has no
        better answer. The language actually recorded is stored beside it."""
        self.assertEqual(server.preshift_affirmation_text("fr"),
                         server.PRESHIFT_AFFIRMATION_TEXTS["en"])
        self.assertEqual(server.preshift_affirmation_text(None),
                         server.PRESHIFT_AFFIRMATION_TEXTS["en"])

    def test_the_version_is_dated(self):
        self.assertRegex(server.PRESHIFT_AFFIRMATION_VERSION,
                         r"^\d{4}-\d{2}-\d{2}\.\d+$")


class NothingElseOnTheSheetMoved(unittest.TestCase):
    def test_every_other_cell_still_reads_the_stored_row(self):
        # THE FIELD, NOT ITS DEFAULT FORM. These pinned `w.get("name", "")`
        # and `w.get("osha_number", "")` — the two-argument spelling. That
        # THE FIELD, NOT ITS DEFAULT FORM, AND NOT ITS SOURCE SPELLING. These
        # pinned `w.get("name", "")` and `w.get("osha_number", "")` — the
        # two-argument spelling. That spelling returns the default only on an
        # ABSENT key, so a stored `name: None` reached `.strip()` and raised,
        # and a stored None interpolated into the cell as the four characters
        # "None". Fixing both took the literals with them.
        #
        # AND THEN THE BRANCH ITSELF WENT. The invariant was always "every cell
        # reads the STORED ROW" — which object is read, not how the default is
        # spelled and not which file spells it. A recognisable value in each
        # field of the fixture, found in that column of the document, is the
        # same claim with no spelling in it at all.
        html = sheet("preshift_signin")
        for column, expected in (("Name", "Wilmer carrillo"),
                                 ("Injury", "No"),
                                 ("PPE", "Yes"),
                                 ("OSHA #", "11112222")):
            with self.subTest(column=column):
                self.assertIn(expected, cells(html, column)[0])

    def test_the_sheet_shows_the_footer(self):
        """The footer points at the affirmation records instead of overlaying
        the Signature column. Asserted on the page: this counted a call in
        `server.py`, and the branch that made the call is deleted.

        AND IT WAS PASSING ON THE DEFECT. It read

            assertIn("affirmation record", visible(sheet("preshift_signin")))

        against a fixture carrying NO affirmations -- so the section is omitted
        by `requires`, exactly as designed, and the only "affirmation record"
        on the page was the per-row banner: "no affirmation record for this
        document", stamped on the worker whose absence from this footer the
        test believed it was checking. Removing the banner turned it red, which
        is the first time it had anything to say.

        A SHEET WITH A COUNT IS WHAT SHOWS A FOOTER, so the fixture now carries
        the gate check-ins the count reads, and the assertion is on the
        section's own wording rather than a substring two things share.
        """
        html = sheet("preshift_signin",
                     rows={"checkins": [{"worker_id": f"w{i}"}
                                        for i in range(6)]})
        text = visible(html)
        self.assertIn("Affirmation Records", text)
        self.assertIn("6 workers affirmed their sign-in at the gate", text)

    def test_and_a_sheet_with_no_affirmations_carries_NO_such_section(self):
        """The other half, and the reason the one above could hide. Zero is a
        silence, not a finding against the day."""
        self.assertNotIn("Affirmation Records", visible(sheet("preshift_signin")))

    def test_the_cell_still_takes_the_resolved_map_and_nothing_else(self):
        """THE CALL FORM IS STILL PINNED, because the defect this guards is an
        AFFIRMATION OVERLAY smuggled into the Signature column — a cell that
        decides, from a picture, whether a man affirmed.

        THE CALL MOVED INTO THE ENGINE. The row formatter is handed ONE ROW and
        the render context, and the resolved map is inlined onto the row before
        it gets there; there is no second argument to smuggle anything into.
        So the claim is asserted where it now lives, and the OUTCOME is
        asserted on the sheet: a drawn mark says nothing about affirmation.

        AND THE SECOND ASSERTION HERE USED TO SAY THE OPPOSITE. It read

            self.assertIn("UNAFFIRMED", signed,
                          "a drawn mark with no affirmation record must say so")

        which is exactly the sentence the class docstring above forbids, and it
        was written during the engine migration against the engine's own
        output rather than against the rule. It certified the re-introduced
        defect as correct and would have failed anybody who fixed it. See
        AWorkersMarkIsNotAThingThatCanBeAffirmed below for the rule it is
        replaced by, and for the CP signature that still does carry the banner.
        """
        from lib.legal_render import primitives
        self.assertIn("preshift_signature", primitives.ROW_FORMATTERS)
        html = sheet("preshift_signin")
        signed, unsigned = cells(html, "Signature")
        self.assertIn("[INK]", signed, "the drawn mark is not on the sheet")
        self.assertNotIn("UNAFFIRMED", signed,
                         "a worker's roster mark has no affirmation state")
        self.assertIn("NO SIGNATURE ON FILE", unsigned)

    def test_the_overlay_resolver_is_gone(self):
        self.assertNotIn("async def preshift_affirmations", SRC)


class AWorkersMarkIsNotAThingThatCanBeAffirmed(unittest.TestCase):
    """THE DEFECT CAME BACK THROUGH THE ENGINE, AND MEASURED ON PRODUCTION.

    Across filed `preshift_signin` rosters: 400 worker rows, 302 carrying a
    mark, and all 302 printed

        UNAFFIRMED -- no affirmation record for this document

    beside a named man who did sign. The route is `ink`, which appends the
    document affirmation banner under every mark it draws, and the roster's
    Signature column reaches it through the `preshift_signature` row formatter.

    NOTHING WRITES AFFIRMATION ONTO A WORKER'S ROSTER MARK. The only writers of
    the key in `server.py` put it on `cp_signature`, the DOCUMENT signature,
    and `_is_affirmed_signature` is that document predicate. So the banner on a
    roster row is a deficiency no action on site can cure: the state it reports
    missing does not exist for him and never will.

    THE FIX IS NOT A TYPE CHECK. Suppressing the banner for a mark stored as a
    string would fix these 302 rows and silently drop a REAL finding the first
    time a CP's document signature is stored as one -- which is a shape
    production holds, and which test_a_CP_signature_stored_as_a_string_... below
    pins. The question is whose mark it is, and `ink` is told.
    """

    def _sigcol(self, html):
        return cells(html, "Signature")

    def test_no_worker_row_on_a_filed_roster_carries_the_banner(self):
        """The 302. The drawn mark stays; the finding against him goes."""
        signed, unsigned = self._sigcol(sheet("preshift_signin"))
        self.assertIn("[INK]", signed)
        self.assertNotIn("UNAFFIRMED", signed)
        self.assertNotIn("UNAFFIRMED", unsigned)

    def test_not_for_the_STRING_mark_production_actually_stores(self):
        """All 302 are a `str`; zero are a dict. The fixture's dict mark alone
        would leave the production shape unasserted."""
        html = sheet("preshift_signin", data={"workers": [
            dict(STORED, worker_signature="iVBORw0KGgo=")]})
        cell, = self._sigcol(html)
        self.assertIn("[IMAGE]", cell)
        self.assertNotIn("UNAFFIRMED", cell)

    def test_nor_for_a_roster_mark_carrying_the_key_set_FALSE(self):
        """WHOSE MARK IT IS, NOT WHAT THE MARK SAYS. If some future writer put
        `affirmed: False` on a roster row the answer is still that the column
        makes no affirmation claim -- otherwise the banner is one write away
        from returning."""
        html = sheet("preshift_signin", data={"workers": [
            dict(STORED, worker_signature={"data": "iVBORw0KGgo=",
                                           "affirmed": False})]})
        cell, = self._sigcol(html)
        self.assertNotIn("UNAFFIRMED", cell)

    def test_and_says_nothing_in_the_OTHER_direction_either(self):
        """An affirmed-looking roster mark must not print a claim the sheet
        does not own. The footer counts; the column does not claim."""
        html = sheet("preshift_signin", data={"workers": [
            dict(STORED, worker_signature={"data": "iVBORw0KGgo=",
                                           "affirmed": True})]})
        cell, = self._sigcol(html)
        self.assertNotIn("AFFIRMED", cell)

    def test_the_CPs_unaffirmed_DOCUMENT_signature_still_says_so(self):
        """THE HALF THAT MUST SURVIVE. The CP can affirm; the app writes it on
        `cp_signature`; a document signed without it is a real deficiency and
        79 filed records once lost exactly this line."""
        from tests.filed_sheet import UNAFFIRMED
        html = sheet("preshift_signin", cp_signature=UNAFFIRMED)
        self.assertIn("UNAFFIRMED", html)
        self.assertIn("no affirmation record for this document", html)
        for cell in self._sigcol(html):
            self.assertNotIn("UNAFFIRMED", cell,
                             "the CP's banner leaked into the roster column")

    def test_a_CP_signature_stored_as_a_STRING_still_says_so(self):
        """THE TEST THAT REFUSES THE CHEAP FIX. `isinstance(sig, str)` inside
        `ink` would pass every assertion above and lose this one -- an
        inherited credential is a bare string too, and that is the object the
        whole mechanism exists to catch."""
        html = sheet("preshift_signin", cp_signature="iVBORw0KGgo=")
        self.assertIn("UNAFFIRMED", html)

    def test_the_CPs_affirmed_signature_still_reports_its_audit_trail(self):
        html = sheet("preshift_signin")
        self.assertIn("AFFIRMED for this document", html)

    def test_ink_still_banners_BY_DEFAULT(self):
        """The safe default is the claim, so a new caller that forgets to think
        about it prints the deficiency rather than hiding it."""
        from lib.legal_render import primitives
        ctx = {"signature_affirmation": server._signature_affirmation_html}
        self.assertIn("UNAFFIRMED", primitives.ink("iVBORw0KGgo=", ctx))

    def test_the_suppression_is_a_NAMED_ARGUMENT_not_a_shape_test(self):
        """The rule is 'is affirmation a state this mark can be in', answered
        by whose mark it is. That has to be readable in the signature of the
        function that draws the mark, not inferred inside it."""
        from lib.legal_render import primitives
        params = inspect.signature(primitives.ink).parameters
        self.assertIn("affirmable", params)
        self.assertIs(params["affirmable"].default, True)

    def test_the_row_formatter_is_what_says_NO(self):
        """And it says it once, at the call, where the reason is legible."""
        from lib.legal_render import primitives
        code = _code_only(primitives.preshift_signature)
        self.assertIn("affirmable=False", code)


if __name__ == "__main__":
    unittest.main()
