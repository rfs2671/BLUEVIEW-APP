"""Twelve men flagged because the parser accepted one date format.

THE DEFECT, MEASURED ON PRODUCTION 2026-09-15. All 75 certifications:

    expiry parsed cleanly       : 56
    expiry REFUSED and kept raw : 17
    review_reason  EXPIRY_UNPARSEABLE 17   CLASS_UNVERIFIED 8   (= the 25 flagged)

Every one of the 17 refused strings, verbatim:

    11  '2027-10-03'      ISO
     1  '2026-05-06'      ISO
     1  'illegible'       the model's own word
     1  'null'            pre-fix OCR artefact
     1  '05/35'
     1  '10272029'
     1  '062427'

TWELVE OF SEVENTEEN ARE VALID, UNAMBIGUOUS ISO-8601 DATES. They were thrown
away because the certification date parser was `strptime(s, "%m/%d/%Y")` and
nothing else. Twelve men are flagged for the parser's narrowness, not for
anything wrong with their card.

THE LINE THIS FILE DEFENDS, AND IT IS THE WHOLE POINT OF THE CHANGE:

    ACCEPTED  formats that are unambiguous BY CONSTRUCTION.
    REFUSED   everything that is unambiguous only BY CONVENTION.

`'10272029'`, `'062427'` and `'05/35'` are on the refused side and
`TheAmbiguousShapesStayRefused` below pins them there. They are not refused
because they are hard to read; they are refused because the parser would be
GUESSING, and a guess about an expiry date on a §3301 compliance record is the
thing this product does not do. See the comment at `parse_cert_date`.
"""

import ast
import importlib.util
import inspect
import os
import sys
import textwrap
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from server import (  # noqa: E402
    build_worker_certifications,
    card_image_may_be_replaced,
    parse_cert_date,
    RECOGNIZED_SST_TYPES,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

# The twelve, by name, exactly as production holds them. Named so a reader can
# see that this file is about people and not about a format string.
THE_TWELVE = (
    ("Hector Ramirez", "2026-05-06"),
    ("Samuel Boateng", "2027-10-03"),
    ("Luis Alvarez", "2027-10-03"),
    ("Marcus Bell", "2027-10-03"),
    ("Tomasz Nowak", "2027-10-03"),
    ("Andre Duval", "2027-10-03"),
    ("Kevin O'Rourke", "2027-10-03"),
    ("Ravi Chandra", "2027-10-03"),
    ("Joseph Kim", "2027-10-03"),
    ("Ernesto Diaz", "2027-10-03"),
    ("Patrick Shea", "2027-10-03"),
    ("Owen Bradley", "2027-10-03"),
)

# The five that stay with a human. Build 2's population, and it must not grow.
THE_FIVE = ("illegible", "null", "05/35", "10272029", "062427")


def od(**kw):
    base = {"name": "A WORKER", "card_type": "SST", "card_class": "Worker",
            "sst_number": "SST0000000A"}
    base.update(kw)
    return base


def sst_rows(certs):
    return [c for c in certs if str(c.get("type", "")) in RECOGNIZED_SST_TYPES]


def build(**kw):
    certs, _ = build_worker_certifications(
        [], od(**kw), "SST0000000A", None, NOW)
    return sst_rows(certs)[0]


def _src(fn):
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))


# ── BUILD 1: ISO IS ACCEPTED ────────────────────────────────────────────────
class IsoDatesAreAccepted(unittest.TestCase):

    def test_the_bare_parser_reads_iso(self):
        self.assertEqual(
            parse_cert_date("2027-10-03"),
            datetime(2027, 10, 3, tzinfo=timezone.utc))

    def test_the_bare_parser_still_reads_mdy(self):
        self.assertEqual(
            parse_cert_date("10/03/2027"),
            datetime(2027, 10, 3, tzinfo=timezone.utc))

    def test_each_of_the_twelve_now_parses(self):
        """THE DEFECT AS DATA. Each of these is a real man whose real card
        carries a real, unambiguous date, and each was called unreadable."""
        for name, raw in THE_TWELVE:
            row = build(expiration=raw)
            self.assertEqual(
                row["expiration_date"],
                datetime(*(int(p) for p in raw.split("-")), tzinfo=timezone.utc),
                f"{name}: {raw!r} is an unambiguous ISO-8601 date")
            self.assertIsNone(row["expiration_raw_rejected"], name)
            self.assertNotEqual(row["review_reason"], "EXPIRY_UNPARSEABLE", name)

    def test_the_eleven_identical_rows_come_out_clean(self):
        """'2027-10-03' is in the future and the class is legible, so nothing
        else in the gate has anything to say about it."""
        row = build(expiration="2027-10-03")
        self.assertFalse(row["needs_review"])
        self.assertIsNone(row["review_reason"])

    def test_hector_ramirez_becomes_expired_not_clean(self):
        """HIS DATE IS IN THE PAST. Recovering it does not clear him -- it
        makes his record TRUE. 'unknown, could not read the card' becomes
        'expired', which is a different and more useful sentence. The
        plausibility gate has no objection to a past expiry; that is
        `_sst_cert_state`'s call, and it says 'expired'."""
        row = build(expiration="2026-05-06")
        self.assertEqual(row["expiration_date"],
                         datetime(2026, 5, 6, tzinfo=timezone.utc))
        self.assertIsNone(row["review_reason"])
        self.assertEqual(server._sst_cert_state(row, NOW), "expired")


# ── THE LINE. NOTHING ELSE MOVES ────────────────────────────────────────────
class TheAmbiguousShapesStayRefused(unittest.TestCase):
    """DO NOT RELAX THIS CLASS TO MAKE A ROW GO AWAY.

    `10272029` reads as 27 October 2029 only to someone who ALREADY assumes
    month-day-year; the string itself does not say. `062427` is 06/24/2027 or
    06/24/1927 and one of those is an expired card. `05/35` is May 2035, or
    May the 35th -- itself impossible -- with the year lost. Each needs a human
    with the card in his hand, which is Build 2 and a separate change.
    """

    def test_the_three_convention_only_shapes_are_refused(self):
        for raw in ("10272029", "062427", "05/35"):
            self.assertIsNone(parse_cert_date(raw),
                              f"{raw!r} is unambiguous only BY CONVENTION")
            row = build(expiration=raw)
            self.assertIsNone(row["expiration_date"], raw)
            self.assertEqual(row["expiration_raw_rejected"], raw)
            self.assertEqual(row["review_reason"], "EXPIRY_UNPARSEABLE")
            self.assertTrue(row["needs_review"])

    def test_the_models_own_refusal_is_still_a_refusal(self):
        row = build(expiration="illegible")
        self.assertEqual(row["review_reason"], "EXPIRY_UNPARSEABLE")
        self.assertEqual(row["expiration_raw_rejected"], "illegible")

    def test_prose_dates_are_still_refused(self):
        """Pinned because test_gate_card_not_sst.py depends on it and because
        a month NAME is a fourth format, not a widening of these two."""
        self.assertIsNone(parse_cert_date("MARCH 17 2028"))

    def test_two_digit_years_are_refused_in_both_orders(self):
        for raw in ("10/03/27", "27-10-03", "03-10-2027"):
            self.assertIsNone(parse_cert_date(raw), raw)

    def test_the_parser_accepts_exactly_two_formats(self):
        """A COUNT, so the next widening is a deliberate act. Adding a third
        format breaks this test on purpose -- read the comment at
        parse_cert_date before you change the number."""
        self.assertEqual(tuple(server.CERT_DATE_FORMATS),
                         ("%m/%d/%Y", "%Y-%m-%d"))

    def test_the_rule_is_written_down_at_the_parser(self):
        """The next reader will see an obviously-legible date being sent to a
        human and try to 'fix' it. The reason has to be where he is looking."""
        doc = (parse_cert_date.__doc__ or "") + inspect.getsource(parse_cert_date)
        self.assertIn("10272029", doc)
        self.assertIn("CONSTRUCTION", doc.upper())
        self.assertIn("CONVENTION", doc.upper())


# ── THE `issued` CONSEQUENCE ────────────────────────────────────────────────
class WideningAlsoWidensTheIssueDate(unittest.TestCase):
    """`parse_cert_date` parses BOTH dates on the card. An issue date that
    begins parsing feeds two live tests: the `exp <= issue` sanity check and
    the SST_TEMPORARY ceiling (`_base = issue_dt or now`).

    MEASURED ON PRODUCTION BEFORE SHIPPING: of 75 stored `osha_data.issued`
    strings, 69 are `%m/%d/%Y` (parsing already), 3 are absent, and 3 are
    neither ('10272024', 'null', '06, 24,2022'). **ZERO are ISO.** So no
    existing row gains an issue date from this change and no existing row can
    newly trip EXPIRY_IMPLAUSIBLE. The behaviour below is nonetheless real for
    the next scan, so it is pinned here rather than left to be discovered.
    """

    def test_an_iso_issue_date_now_parses(self):
        row = build(issued="2025-01-02", expiration="01/02/2030")
        self.assertEqual(row["issue_date"],
                         datetime(2025, 1, 2, tzinfo=timezone.utc))

    def test_an_iso_issue_date_after_the_expiry_now_trips_implausible(self):
        """BEFORE THIS CHANGE this row was clean: the issue date did not parse,
        so `exp_dt <= issue_dt` never ran. It is a NEW verdict and it is the
        RIGHT one -- a card cannot expire before it was issued."""
        row = build(issued="2031-01-01", expiration="01/02/2030")
        self.assertEqual(row["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertIsNone(row["expiration_date"])
        self.assertEqual(row["expiration_raw_rejected"], "01/02/2030")

    def test_the_temporary_ceiling_now_sees_an_iso_issue_date(self):
        """A TEMPORARY card lives six months from ISSUE. With an ISO issue date
        parsing, the ceiling moves off `now` and onto the card's own date."""
        row = build(card_class="Temporary", issued="2025-01-01",
                    expiration="12/01/2025")
        self.assertEqual(row["type"], "SST_TEMPORARY")
        self.assertEqual(row["review_reason"], "EXPIRY_IMPLAUSIBLE")

    def test_a_temporary_card_within_six_months_of_an_iso_issue_is_clean(self):
        row = build(card_class="Temporary", issued="2026-08-01",
                    expiration="10/01/2026")
        self.assertEqual(row["type"], "SST_TEMPORARY")
        self.assertIsNone(row["review_reason"])
        self.assertEqual(row["expiration_date"],
                         datetime(2026, 10, 1, tzinfo=timezone.utc))


# ── WIDENING THE PARSER CLEARS NOBODY WHO IS ALREADY FLAGGED ────────────────
class TheFlagIsWrittenOnceAndNeverReDerived(unittest.TestCase):
    """The reason Build 1 is a parser change AND a backfill, stated as a test
    so nobody ships half of it again."""

    def test_a_stored_flagged_row_is_not_healed_by_reading_it(self):
        stored = {"type": "SST_FULL", "card_number": "SST7F6308A7",
                  "expiration_date": None, "verified": False,
                  "needs_review": True, "review_reason": "EXPIRY_UNPARSEABLE",
                  "expiration_raw_rejected": "2027-10-03"}
        worker = {"name": "Samuel Boateng", "certifications": [stored]}
        # Every read path. None of them consults the widened parser.
        self.assertEqual(server._sst_cert_state(stored, NOW), "unknown")
        self.assertTrue(stored["needs_review"])
        v = server.validate_worker_certifications(worker)
        self.assertEqual(v["sst_state"], "unknown")


class TheImageLockIsAConsequenceNotAnAccident(unittest.TestCase):
    """`card_image_may_be_replaced` reads `needs_review or expiration_date is
    None`. Clearing the flag flips it to False -- a card photo can no longer be
    replaced by a later re-scan. Pinned here so the transition is a fact in the
    suite, not a surprise in production.

    MEASURED: none of the twelve has a card image on file today
    (`osha_card_image` and `osha_card_r2_key` both absent on all twelve), so
    the predicate returns True on the no-image branch BEFORE it ever reaches
    the flag -- the backfill moves nothing for them. The transition below is
    what happens to those men LATER, once a card image exists.
    """

    def _worker(self, needs_review, exp):
        return {"osha_card_r2_key": "cards/abc.jpg",
                "certifications": [{"type": "SST_FULL", "verified": False,
                                    "needs_review": needs_review,
                                    "expiration_date": exp}]}

    def test_no_image_on_file_means_replaceable_either_way(self):
        """THE TWELVE, AS THEY STAND TODAY. The backfill changes nothing here."""
        for nr, exp in ((True, None), (False, datetime(2027, 10, 3,
                                                       tzinfo=timezone.utc))):
            w = {"certifications": [{"type": "SST_FULL", "verified": False,
                                     "needs_review": nr,
                                     "expiration_date": exp}]}
            self.assertTrue(card_image_may_be_replaced(w, "newbytes"))

    def test_clearing_the_flag_locks_a_stored_image(self):
        before = self._worker(True, None)
        after = self._worker(False, datetime(2027, 10, 3, tzinfo=timezone.utc))
        self.assertTrue(card_image_may_be_replaced(before, "newbytes"))
        self.assertFalse(card_image_may_be_replaced(after, "newbytes"))


if __name__ == "__main__":
    unittest.main()
