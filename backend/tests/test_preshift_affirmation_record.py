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

    def test_the_cell_takes_no_overlay_argument_at_all(self):
        """Not merely unused -- gone, so nothing can pass one again."""
        params = list(inspect.signature(
            server._preshift_signature_cell).parameters)
        self.assertEqual(params, ["w"])

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
        # spelling returns the default only on an ABSENT key, so a stored
        # `name: None` reached `.strip()` and raised, and a stored None
        # interpolated into the cell as the four characters "None". Fixing
        # both took the literals with them.
        #
        # The invariant here is "every cell still reads the STORED ROW `w`",
        # which is about WHICH OBJECT is read, not about how the default is
        # spelled. `w.get("<field>")` is the part that carries that meaning.
        for cell in ('w.get("name")', 'w.get("had_injury")',
                     'w.get("inspected_ppe")', 'w.get("osha_number")'):
            self.assertIn(cell, SRC)

    def test_both_renderers_show_the_footer(self):
        self.assertEqual(SRC.count("preshift_affirmation_footer(_affirm_n)"), 2)

    def test_and_neither_passes_an_overlay_to_the_cell(self):
        self.assertNotIn("_preshift_signature_cell(w, ", SRC)
        # THREE: the definition plus two CALL SITES. Counted as the call
        # form, so the definition cannot be mistaken for a third caller.
        self.assertEqual(
            SRC.count("{_preshift_signature_cell(w)}</td></tr>"), 2)
        self.assertEqual(SRC.count("def _preshift_signature_cell(w)"), 1)

    def test_the_overlay_resolver_is_gone(self):
        self.assertNotIn("async def preshift_affirmations", SRC)


if __name__ == "__main__":
    unittest.main()
