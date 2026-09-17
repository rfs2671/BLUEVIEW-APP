"""AN INSURANCE EXPIRY NOBODY CAN READ IS NOT A COMPANY WITHOUT INSURANCE.

── WHAT WAS SILENT, AND WHERE ──────────────────────────────────────────────

`companies.gc_insurance_records[].expiration_date` had two readers and both
answered `None` for a string they could not parse — the same answer they give
for a date that is absent:

  lib/renewal_digest.py   `if not exp: continue`. No T-30/T-14/T-7/T-5/T-0
                          alert for that policy, for the life of the record.
                          Not a late alert. No alert, and no line saying a
                          record had been skipped.

  lib/eligibility_v2.py   the record is not a candidate in the `min()` over
                          GL/WC/DBL/licence/issuance+365. When another
                          candidate existed the permit still resolved a
                          strategy and could read AUTO_EXTEND — a confident
                          answer computed with a required input missing.

And one more, in a different shape: `permit_renewal.check_renewal_eligibility`
built every record in ONE comprehension inside ONE `try`, so a single record
whose `source` fell outside the Literal set the whole list to `[]` and the
company read as having no insurance at all. `bis_scraper` is such a value, and
server.py's own BIS debug dump queries for it.

── WHAT THIS FILE ASSERTS ──────────────────────────────────────────────────

Behaviour, at each of the four seams, and never the presence of source text.
The one place it reads a file is to pin two constants to a third copy of them
that lives in JavaScript, which is a fact about two files agreeing and cannot
be expressed any other way.

THE CONTROL IS RECORDED IN THE PR: renewal_digest.py, eligibility_v2.py,
permit_renewal.py and server.py reverted to 5213e2c4 with lib/
insurance_expiry.py left in place, which is how the failures below were
produced before the fix.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.insurance_expiry import (  # noqa: E402
    INSURANCE_DATE_UNREADABLE,
    INSURANCE_TYPES,
    MAX_YEAR,
    MIN_YEAR,
    ExpiryRead,
    normalise_stored_expiry,
    quote,
    read_expiry,
    unreadable_blocking_reason,
    unreadable_records,
)


def _run(coro):
    return asyncio.run(coro)


#: Strings no reader in this system can turn into a calendar day, and the
#: reason each one is refused rather than guessed at. These are the values the
#: strict writer refuses; `read_expiry` is wider (see its own tests).
UNREADABLE = {
    "illegible":  "what an OCR pass writes when it cannot read the box",
    "see attached": "free text in a date field",
    "":           "handled as blank, not unreadable — asserted separately",
    "7/2/29":     "two-digit year, unpadded month: a dropped digit and a "
                  "short year are indistinguishable",
    "2029":       "a year is not a day",
    "21/07/2029": "no month 21, and the digits are never reordered to DD/MM",
    "2029-02-30": "February has no 30th",
    "2027-02-29": "2027 is not a leap year",
    "1899-01-01": "outside the year bound the typed field applies",
}


class TheReaderTellsBlankFromUnreadable(unittest.TestCase):
    """`read_expiry` — for the two READERS. Acceptance unchanged (dateutil);
    what changed is that a failure is reported instead of returning None."""

    def test_a_readable_date_still_reads_in_both_stored_formats(self):
        """THE FIRST THING TO CHECK, because a deploy that started calling
        stored values unreadable would raise alerts about data that is fine."""
        for raw in ("2029-07-21", "07/21/2029"):
            with self.subTest(raw=raw):
                read = read_expiry(raw)
                self.assertFalse(read.unreadable)
                self.assertFalse(read.blank)
                self.assertEqual(read.at.date().isoformat(), "2029-07-21")
                self.assertEqual(read.at.tzinfo, timezone.utc)

    def test_absent_is_blank_and_is_not_unreadable(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=repr(raw)):
                read = read_expiry(raw)
                self.assertTrue(read.blank)
                self.assertFalse(read.unreadable)
                self.assertIsNone(read.at)

    def test_nonsense_is_unreadable_and_is_not_blank(self):
        """THE DISTINCTION THIS WHOLE PR IS ABOUT. Before it, both of these
        came back as the same `None` that an absent date gives."""
        for raw in ("illegible", "see attached", "2029-02-30"):
            with self.subTest(raw=raw):
                read = read_expiry(raw)
                self.assertTrue(read.unreadable, raw)
                self.assertFalse(read.blank, raw)
                self.assertIsNone(read.at)

    def test_it_LOGS_an_error_naming_the_record_and_the_value(self):
        """A log line saying only that some date somewhere was unreadable
        cannot be acted on. The company, the type and the stored string."""
        with self.assertLogs("lib.insurance_expiry", level="ERROR") as cap:
            read_expiry("illegible", where="company=co1 general_liability")
        joined = "\n".join(cap.output)
        self.assertIn(INSURANCE_DATE_UNREADABLE, joined)
        self.assertIn("company=co1 general_liability", joined)
        self.assertIn("illegible", joined)

    def test_a_readable_date_logs_NOTHING(self):
        """An instrument that fires on everything reports nothing. A nightly
        cron over every company must not log an error per good record."""
        logger = logging.getLogger("lib.insurance_expiry")
        with self.assertLogs(logger, level="DEBUG") as cap:
            logger.debug("sentinel")          # assertLogs needs one record
            read_expiry("2029-07-21", where="company=co1 general_liability")
        self.assertEqual([r for r in cap.records if r.levelno >= logging.WARNING], [])

    def test_a_datetime_already_on_the_record_passes_through(self):
        """Mongo can hold a BSON date, and that is not a parse failure. Naive
        is treated as UTC, exactly as the `_utc` helpers did."""
        naive = datetime(2029, 7, 21, 0, 0, 0)
        read = read_expiry(naive)
        self.assertFalse(read.unreadable)
        self.assertEqual(read.at, datetime(2029, 7, 21, tzinfo=timezone.utc))

    def test_the_result_cannot_be_used_as_a_BOOLEAN(self):
        """`if read:` reads exactly like the `if exp:` it replaces and would
        put an unreadable record straight back on the silent path. So it is an
        error, not a convenience."""
        with self.assertRaises(TypeError):
            bool(read_expiry("illegible"))
        with self.assertRaises(TypeError):
            if read_expiry("2029-07-21"):      # noqa: SIM102 - the point
                pass

    def test_the_quote_is_bounded(self):
        """The refusal is rendered in a phone-width blocking reason, and this
        field has held free text."""
        self.assertLessEqual(len(quote("x" * 500)), 64)
        self.assertEqual(quote("  2029-07-21  "), "2029-07-21")


class TheWriterIsStrictAndNormalisesToIso(unittest.TestCase):
    """`normalise_stored_expiry` — for a WRITER. Narrower than the reader on
    purpose: a writer decides what goes onto the record."""

    def test_it_returns_iso_for_both_accepted_shapes(self):
        for raw in ("2029-07-21", "07/21/2029", "07212029",
                    "07/212029", "0721/2029"):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_stored_expiry(raw), "2029-07-21")

    def test_it_refuses_rather_than_guessing(self):
        for raw, why in UNREADABLE.items():
            if raw == "":
                continue
            with self.subTest(raw=raw, why=why):
                with self.assertRaises(ValueError):
                    normalise_stored_expiry(raw)

    def test_the_refusal_names_the_value_and_the_format(self):
        """"invalid date" sends the admin back to guess. The message is what
        he reads."""
        with self.assertRaises(ValueError) as cm:
            normalise_stored_expiry("7/2/29")
        self.assertIn("7/2/29", str(cm.exception))
        self.assertIn("MM/DD/YYYY", str(cm.exception))

    def test_blank_is_refused_here_and_the_caller_handles_it(self):
        """A writer with nothing to write must not store ''. The COI handler
        maps absent to None before calling this; see its own test."""
        with self.assertRaises(ValueError):
            normalise_stored_expiry("")

    def test_what_it_returns_is_what_the_FILED_LOG_GATE_would_accept(self):
        """ONE CALENDAR, ASSERTED AS AN IDENTITY rather than by trusting two
        implementations of the Gregorian rule to agree.

        `server.logbook_date_is_real` is the SUBMIT_INVALID_DATE gate's reader
        and it applies the rule with a month-length table. This module uses
        `strptime`. Every value one accepts, the other must."""
        import server
        for raw in ("2029-07-21", "07/21/2029", "2028-02-29", "1900-01-01",
                    "2199-12-31", "12/31/2199"):
            with self.subTest(raw=raw):
                self.assertTrue(server.logbook_date_is_real(
                    normalise_stored_expiry(raw)), raw)
        for raw in ("2029-02-30", "2027-02-29", "1899-01-01", "2200-01-01"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    normalise_stored_expiry(raw)
                # and the gate refuses the same day, reached as ISO directly
                self.assertFalse(server.logbook_date_is_real(raw), raw)

    def test_the_year_bound_is_the_SAME_NUMBER_in_all_three_places(self):
        """The typed field (dateEntry.js), the filed-log gate (server.py) and
        this module. A server that accepted a year the screen marks tells the
        admin to fix a value the record was happy to take."""
        import server
        self.assertEqual((MIN_YEAR, MAX_YEAR),
                         (server.LOGBOOK_DATE_MIN_YEAR, server.LOGBOOK_DATE_MAX_YEAR))
        js = (_BACKEND.parent / "frontend" / "src" / "utils" / "dateEntry.js").read_text(
            encoding="utf-8")
        self.assertIn(f"export const MIN_YEAR = {MIN_YEAR};", js)
        self.assertIn(f"export const MAX_YEAR = {MAX_YEAR};", js)

    def test_the_unreadable_sentence_is_the_SAME_STRING_as_the_screens_use(self):
        """An admin told about it in the nightly email and then on the badge
        must be able to tell it is one problem."""
        js = (_BACKEND.parent / "frontend" / "src" / "utils"
              / "insuranceExpiry.js").read_text(encoding="utf-8")
        m = re.search(r"export const INSURANCE_DATE_UNREADABLE = '([^']+)';", js)
        self.assertIsNotNone(m, "INSURANCE_DATE_UNREADABLE not found in the JS")
        self.assertEqual(m.group(1), INSURANCE_DATE_UNREADABLE)


class TheCompanyCensusNamesEveryBadRecord(unittest.TestCase):

    def _company(self, *records):
        return {"_id": "co1", "name": "Acme GC", "gc_insurance_records": list(records)}

    def test_a_clean_company_has_no_reason(self):
        c = self._company(
            {"insurance_type": "general_liability", "expiration_date": "2029-07-21"},
            {"insurance_type": "workers_comp", "expiration_date": "07/21/2029"},
            {"insurance_type": "disability", "expiration_date": None},
        )
        self.assertEqual(unreadable_records(c), [])
        self.assertIsNone(unreadable_blocking_reason(c))

    def test_every_bad_record_is_named_in_ONE_reason(self):
        c = self._company(
            {"insurance_type": "general_liability", "expiration_date": "illegible"},
            {"insurance_type": "workers_comp", "expiration_date": "2029-07-21"},
            {"insurance_type": "disability", "expiration_date": "see attached"},
        )
        bad = unreadable_records(c)
        self.assertEqual([t for t, _, _ in bad], ["general_liability", "disability"])
        reason = unreadable_blocking_reason(c)
        self.assertIn(INSURANCE_DATE_UNREADABLE, reason)
        self.assertIn("General Liability", reason)
        self.assertIn("Disability", reason)
        self.assertIn("illegible", reason)
        # AND IT SAYS WHAT IT IS NOT. The whole point is that this must never
        # be mistaken for an empty record.
        self.assertIn("NOT the same as no insurance", reason)

    def test_a_record_of_an_UNKNOWN_type_is_still_censused(self):
        """Derived from the company's own records, not from the three known
        types — skipping a fourth type would be a new silence in the place the
        old one was just removed."""
        c = self._company({"insurance_type": "umbrella", "expiration_date": "illegible"})
        self.assertEqual([t for t, _, _ in unreadable_records(c)], ["umbrella"])

    def test_a_nondict_in_the_list_does_not_raise(self):
        c = self._company("not a record", None)
        self.assertEqual(unreadable_records(c), [])

    def test_the_three_types_and_labels_are_one_list(self):
        from lib import eligibility_v2
        self.assertIs(eligibility_v2.INSURANCE_TYPES, INSURANCE_TYPES)
        self.assertEqual([t for t, _ in INSURANCE_TYPES],
                         ["general_liability", "workers_comp", "disability"])


class TheDigestSaysSoInsteadOfSkipping(unittest.TestCase):

    def setUp(self):
        from lib.renewal_digest import (
            AlertKind, compute_company_alerts, digest_html, digest_subject,
        )
        self.AlertKind = AlertKind
        # KEYWORD-ONLY, as the function declares.
        self.compute = (lambda company, permits, today:
                        compute_company_alerts(company=company, permits=permits,
                                               today=today))
        self.html = digest_html
        self.subject = digest_subject
        self.today = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)

    def _company(self, exp):
        return {"_id": "co1", "name": "Acme GC", "gc_license_expiration": None,
                "gc_insurance_records": [
                    {"insurance_type": "general_liability", "expiration_date": exp}]}

    def test_an_unreadable_expiry_produces_an_alert(self):
        """IT USED TO PRODUCE NOTHING — `if not exp: continue` — for the life
        of the record."""
        alerts = self.compute(self._company("illegible"), [], self.today)
        kinds = [a.kind for a in alerts]
        self.assertEqual(kinds, [self.AlertKind.INSURANCE_UNREADABLE])
        self.assertEqual(alerts[0].expiry_label, "General Liability")
        self.assertEqual(alerts[0].expiry_date, "illegible")
        self.assertEqual(alerts[0].extra["insurance_type"], "general_liability")

    def test_an_ABSENT_expiry_still_produces_nothing(self):
        """The skip was right for this case and stays. There is nothing to
        remind anyone about."""
        for exp in (None, ""):
            with self.subTest(exp=repr(exp)):
                self.assertEqual(self.compute(self._company(exp), [], self.today), [])

    def test_a_readable_expiry_still_fires_its_threshold_alert(self):
        """T-30 on 2026-10-17, read from today 2026-09-17."""
        alerts = self.compute(self._company("2026-10-17"), [], self.today)
        self.assertEqual([a.kind for a in alerts], [self.AlertKind.INSURANCE])
        self.assertEqual(alerts[0].threshold_days, 30)

    def test_the_legacy_format_still_fires_the_same_alert(self):
        """No mixed-format period is needed because this keeps working."""
        alerts = self.compute(self._company("10/17/2026"), [], self.today)
        self.assertEqual([a.kind for a in alerts], [self.AlertKind.INSURANCE])
        self.assertEqual(alerts[0].threshold_days, 30)

    def test_the_idempotency_key_is_the_STORED_STRING(self):
        """So the alert repeats daily until the value is fixed — the cron's key
        includes sent_date — and correcting one typo into another still alerts,
        because the key changed."""
        a = self.compute(self._company("illegible"), [], self.today)[0]
        b = self.compute(self._company("see attached"), [], self.today)[0]
        self.assertNotEqual(a.idempotency_key(), b.idempotency_key())
        self.assertEqual(a.idempotency_key()["expiry_date"], "illegible")

    def test_the_SUBJECT_does_not_claim_the_policy_expired_today(self):
        """threshold_days is 0 so the alert sorts first, and the line that
        turns 0 into "action expired TODAY" would then assert an expiry we
        could not read in the first place. The subject is the part most people
        read."""
        alerts = self.compute(self._company("illegible"), [], self.today)
        subject = self.subject(alerts, "Acme GC")
        self.assertNotIn("expired TODAY", subject)
        self.assertIn(INSURANCE_DATE_UNREADABLE, subject)

    def test_the_ROW_says_what_it_does_not_know(self):
        alerts = self.compute(self._company("illegible"), [], self.today)
        body = self.html(alerts, "Acme GC")
        self.assertIn(INSURANCE_DATE_UNREADABLE, body)
        self.assertIn("illegible", body)
        self.assertIn("NOT the same as no insurance on file", body)
        # It must not count days it does not have.
        self.assertNotIn("expires in 0 days", body)
        self.assertNotIn("EXPIRED TODAY", body)

    def test_EVERY_alert_kind_is_rendered_by_the_body(self):
        """A KIND MISSING FROM `digest_html`'S ORDER LIST IS DROPPED SILENTLY:
        the loop iterates a hand-written list and consults `by_kind` per entry,
        so such an alert passes idempotency, counts towards the total, and
        appears nowhere. Derived from the enum, so the next kind cannot be
        added without appearing in the email."""
        from lib import renewal_digest
        src_kinds = set(self.AlertKind)
        rendered = set()
        for kind in src_kinds:
            alert = renewal_digest.RenewalAlert(
                company_id="co1", company_name="Acme GC", kind=kind,
                threshold_days=7, expiry_date="2026-10-17", expiry_label="Probe")
            if "Probe" in self.html([alert], "Acme GC"):
                rendered.add(kind)
        self.assertEqual(rendered, src_kinds,
                         f"not rendered anywhere in the digest body: "
                         f"{sorted(k.value for k in src_kinds - rendered)}")

    def test_the_unreadable_kind_has_NO_cadence(self):
        """A cadence is a list of days-until-expiry. This alert exists because
        days-until cannot be computed, so an entry would be a number nothing
        could have produced."""
        from lib.renewal_digest import CADENCES
        self.assertNotIn(self.AlertKind.INSURANCE_UNREADABLE, CADENCES)


class ThePermitExpiryRefusesRatherThanGuessing(unittest.TestCase):

    def _evaluate(self, exp, **company_kw):
        from lib import eligibility_v2
        from lib.fee_schedule import bust_fee_cache

        class _StubDb:
            class fee_schedule:
                @staticmethod
                def find(_q):
                    class _Cursor:
                        async def to_list(self, _n):
                            return [{
                                "effective_from": datetime(2025, 12, 21, tzinfo=timezone.utc),
                                "effective_until": None,
                                "applies_to": ["ALL"],
                                "min_renewal_fee_cents": 13_000,
                                "split_rules": {"all": {"at_filing_pct": 100}},
                            }]
                    return _Cursor()

        bust_fee_cache()
        permit = {
            "_id": "permit_1", "record_type": "permit", "filing_system": "DOB_NOW",
            "permit_class": "standard", "work_type": "GC",
            "issuance_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "expiration_date": datetime(2027, 9, 1, tzinfo=timezone.utc),
            "job_number": "B12345-I1",
        }
        company = {
            "_id": "co1", "name": "Acme GC",
            # A LICENCE EXPIRY FAR IN THE FUTURE, deliberately: it is the
            # OTHER candidate, and it is what made the old behaviour
            # dangerous rather than merely incomplete. With it present the
            # `min()` still returns something and the permit read as
            # AUTO_EXTEND while an unreadable insurance date sat on the
            # record.
            "gc_license_expiration": datetime(2030, 1, 1, tzinfo=timezone.utc),
            "gc_insurance_records": [
                {"insurance_type": "general_liability", "expiration_date": exp}],
        }
        company.update(company_kw)
        return _run(eligibility_v2.evaluate(
            _StubDb(), permit, {"_id": "proj1"}, company,
            today=datetime(2026, 9, 17, tzinfo=timezone.utc)))

    def test_an_unreadable_expiry_BLOCKS_and_says_why(self):
        from lib.eligibility_v2 import severity_tier
        result = self._evaluate("illegible")
        reasons = " ".join(result["blocking_reasons"])
        self.assertIn(INSURANCE_DATE_UNREADABLE, reasons)
        self.assertIn("General Liability", reasons)
        self.assertEqual(severity_tier(result), 3)

    def test_it_is_NOT_reported_as_no_insurance_on_file(self):
        """THE SENTENCE FROM THE RULING. The soft prompt means "you have not
        told us yet"; this means "you told us and we cannot read it"."""
        result = self._evaluate("illegible")
        self.assertFalse(result["insurance_not_entered"])
        self.assertIn("NOT the same as no insurance",
                      " ".join(result["blocking_reasons"]))

    def test_the_unreadable_reason_comes_FIRST(self):
        """It is the only reason here an admin can fix in thirty seconds, and
        a phone shows the first one."""
        result = self._evaluate("illegible")
        self.assertIn(INSURANCE_DATE_UNREADABLE, result["blocking_reasons"][0])

    def test_a_readable_expiry_adds_no_such_reason(self):
        result = self._evaluate("2026-10-17")
        self.assertNotIn(INSURANCE_DATE_UNREADABLE,
                         " ".join(result["blocking_reasons"]))
        self.assertEqual(result["limiting_factor"]["kind"], "insurance")

    def test_both_stored_formats_give_the_SAME_effective_expiry(self):
        """The invariant the storage switch rests on."""
        iso = self._evaluate("2026-10-17")
        legacy = self._evaluate("10/17/2026")
        self.assertEqual(iso["effective_expiry"], legacy["effective_expiry"])
        self.assertEqual(iso["blocking_reasons"], legacy["blocking_reasons"])

    def test_a_company_with_NO_records_still_gets_the_soft_prompt(self):
        result = self._evaluate("2026-10-17", gc_insurance_records=[])
        self.assertTrue(result["insurance_not_entered"])
        self.assertNotIn(INSURANCE_DATE_UNREADABLE,
                         " ".join(result["blocking_reasons"]))


class OneBadRecordDropsOnlyItself(unittest.TestCase):
    """permit_renewal.InsuranceRecord, and the loop that builds the list."""

    def test_bis_scraper_is_an_allowed_source(self):
        """server.py queries `{"gc_insurance_records.source": "bis_scraper"}`
        for the BIS debug dump — a value the Literal did not allow, so a
        record carrying it raised."""
        from permit_renewal import InsuranceRecord
        rec = InsuranceRecord(insurance_type="general_liability", source="bis_scraper")
        self.assertEqual(rec.source, "bis_scraper")

    def test_all_four_sources_validate(self):
        from permit_renewal import InsuranceRecord
        for source in ("manual_entry", "coi_ocr", "dob_now_portal", "bis_scraper"):
            with self.subTest(source=source):
                self.assertEqual(
                    InsuranceRecord(insurance_type="workers_comp", source=source).source,
                    source)

    def test_an_UNKNOWN_source_is_still_a_validation_error(self):
        """The Literal is the point — it is what stops a typo becoming a fifth
        provenance nobody declared. Only the blast radius changed."""
        from permit_renewal import InsuranceRecord
        with self.assertRaises(Exception):
            InsuranceRecord(insurance_type="disability", source="typo_source")

    def test_the_other_records_SURVIVE_a_bad_one(self):
        """THE DEFECT, AS BEHAVIOUR. Three valid certificates used to be thrown
        away because of a fourth record's provenance string."""
        import permit_renewal
        raw = [
            {"insurance_type": "general_liability", "expiration_date": "2029-07-21",
             "source": "manual_entry"},
            {"insurance_type": "workers_comp", "expiration_date": "2029-07-21",
             "source": "not_a_declared_source"},
            {"insurance_type": "disability", "expiration_date": "2029-07-21",
             "source": "bis_scraper"},
        ]
        parsed = []
        for idx, rec in enumerate(raw):
            try:
                parsed.append(permit_renewal.InsuranceRecord(**rec))
            except Exception:
                pass
        # The shape the fixed loop produces: two of three, not zero of three.
        self.assertEqual([p.insurance_type for p in parsed],
                         ["general_liability", "disability"])

    def test_the_eligibility_reader_keeps_the_good_records(self):
        """Through the real function, so the loop inside it is what is
        measured rather than a copy of it in this file."""
        import permit_renewal
        company = {
            "_id": "co1", "name": "Acme GC", "gc_license_number": "GC-1",
            "gc_license_status": "Active",
            "gc_insurance_records": [
                {"insurance_type": "general_liability",
                 "expiration_date": "2029-07-21", "source": "manual_entry"},
                {"insurance_type": "workers_comp",
                 "expiration_date": "2029-07-21", "source": "not_a_declared_source"},
                {"insurance_type": "disability",
                 "expiration_date": "2029-07-21", "source": "bis_scraper"},
            ],
        }
        permit = {"_id": "permit_1", "job_number": "B12345-I1",
                  "permit_type": "EW", "filing_system": "DOB_NOW",
                  "expiration_date": "2027-09-01", "issuance_date": "2026-09-01"}
        # `_check_renewal_eligibility_legacy_inner`, NOT the public
        # `check_renewal_eligibility`: the public one is the shadow-mode
        # dispatcher and fetches its own docs from `db`. The inner function is
        # where the loop under test lives and it takes the docs.
        permit["record_type"] = "permit"
        result = _run(permit_renewal._check_renewal_eligibility_legacy_inner(
            MagicMock(), permit, {"_id": "proj1"}, "Acme GC", company,
            today=datetime(2026, 9, 17, tzinfo=timezone.utc)))
        types = {r.insurance_type
                 for r in (result.gc_license.insurance_records
                           if result.gc_license else [])}
        self.assertEqual(types, {"general_liability", "disability"})
        self.assertFalse(result.insurance_not_entered)
        # AND THE FLAGS SAY THE TRUE THING. `required_types - found_types`
        # turns a dropped record into "<type> insurance not entered in
        # Settings." — so with the whole list emptied, all THREE certificates
        # were reported to the admin as never entered. Now only the one that
        # really failed validation is.
        not_entered = [f for f in result.insurance_flags
                       if "not entered in Settings" in f]
        self.assertEqual(not_entered,
                         ["Workers Comp insurance not entered in Settings."])


class TheCoiConfirmEndpointValidatesAndNormalises(unittest.TestCase):
    """Item 4 — done while nothing calls this endpoint. It stored
    `body.expiration_date` raw, whatever the client sent."""

    ADMIN = {"id": "admin_1", "role": "admin"}

    def _client(self, *, draft_type="general_liability"):
        import server
        from fastapi.testclient import TestClient

        company = {"_id": "co1", "name": "Acme GC", "license_class": "GC_LICENSED",
                   "is_deleted": False, "gc_insurance_records": []}

        async def _fake_admin():
            return self.ADMIN

        server.app.dependency_overrides[server.get_admin_user] = _fake_admin
        server.app.dependency_overrides[server.get_current_user] = _fake_admin
        original_get_company = server.get_user_company_id
        server.get_user_company_id = lambda _u: "co1"

        db_mock = MagicMock()
        db_mock.companies.find_one = AsyncMock(return_value=company)
        db_mock.coi_ocr_drafts.find_one = AsyncMock(return_value={
            "_id": "draft_1", "company_id": "co1", "insurance_type": draft_type,
            "ocr_result": {"min_confidence": 0.9}, "pdf_url": "https://r2/x.pdf",
        })
        db_mock.coi_ocr_drafts.delete_one = AsyncMock(return_value=MagicMock())
        self.updates = []

        async def _update_one(flt, upd, **kw):
            self.updates.append((flt, upd))
            return MagicMock(matched_count=1, modified_count=1)

        db_mock.companies.update_one = AsyncMock(side_effect=_update_one)
        db_mock.audit_logs.insert_one = AsyncMock(return_value=MagicMock())
        original_db = server.db
        server.db = db_mock

        def restore():
            server.db = original_db
            server.get_user_company_id = original_get_company
            server.app.dependency_overrides.clear()

        return TestClient(server.app), restore

    def _confirm(self, client, **fields):
        body = {"draft_id": "507f1f77bcf86cd799439011",
                "insurance_type": "general_liability"}
        body.update(fields)
        return client.put("/api/admin/company/insurance/upload-coi/confirm", json=body)

    def test_an_unreadable_date_is_REFUSED_with_the_reason(self):
        client, restore = self._client()
        try:
            for raw in ("illegible", "7/2/29", "2029-02-30", "21/07/2029"):
                with self.subTest(raw=raw):
                    r = self._confirm(client, expiration_date=raw)
                    self.assertEqual(r.status_code, 422, r.text)
                    self.assertIn("Expiration date", r.text)
                    self.assertIn("MM/DD/YYYY", r.text)
        finally:
            restore()

    def test_an_unreadable_EFFECTIVE_date_is_refused_too(self):
        """It is rendered on the Settings card beside the expiry and shifts the
        same way."""
        client, restore = self._client()
        try:
            r = self._confirm(client, effective_date="illegible",
                              expiration_date="2029-07-21")
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("Effective date", r.text)
        finally:
            restore()

    def test_a_legacy_MDY_date_is_STORED_AS_ISO(self):
        client, restore = self._client()
        try:
            r = self._confirm(client, effective_date="07/21/2026",
                              expiration_date="07/21/2029")
            self.assertEqual(r.status_code, 200, r.text)
            record = self.updates[0][1]["$set"]["gc_insurance_records"][-1]
            self.assertEqual(record["expiration_date"], "2029-07-21")
            self.assertEqual(record["effective_date"], "2026-07-21")
        finally:
            restore()

    def test_an_iso_date_is_stored_unchanged(self):
        client, restore = self._client()
        try:
            r = self._confirm(client, expiration_date="2029-07-21")
            self.assertEqual(r.status_code, 200, r.text)
            record = self.updates[0][1]["$set"]["gc_insurance_records"][-1]
            self.assertEqual(record["expiration_date"], "2029-07-21")
        finally:
            restore()

    def test_an_ABSENT_date_stays_absent_and_does_not_refuse(self):
        """OCR legitimately fails to find an effective date on some
        certificates. Refusing an absent value would make such a COI
        unconfirmable and push the admin back to manual entry for the whole
        record."""
        client, restore = self._client()
        try:
            r = self._confirm(client, expiration_date="2029-07-21")
            self.assertEqual(r.status_code, 200, r.text)
            record = self.updates[0][1]["$set"]["gc_insurance_records"][-1]
            self.assertIsNone(record["effective_date"])
        finally:
            restore()

    def test_what_it_stores_is_readable_by_both_readers(self):
        """THE IDENTITY THAT MATTERS: a value this endpoint writes must not be
        a value the digest then calls unreadable."""
        client, restore = self._client()
        try:
            self._confirm(client, expiration_date="07/21/2029")
            record = self.updates[0][1]["$set"]["gc_insurance_records"][-1]
            read = read_expiry(record["expiration_date"])
            self.assertFalse(read.unreadable)
            self.assertEqual(read.at.date().isoformat(), "2029-07-21")
        finally:
            restore()


class TheManualEndpointStoresIso(unittest.TestCase):
    """Item 5 — the storage switch, at the only endpoint that has a client."""

    ADMIN = {"id": "admin_1", "role": "admin"}

    def test_it_writes_YYYY_MM_DD_for_both_date_fields(self):
        import server
        from fastapi.testclient import TestClient

        company = {"_id": "co1", "name": "Acme GC", "is_deleted": False,
                   "gc_insurance_records": []}

        async def _fake_admin():
            return self.ADMIN

        server.app.dependency_overrides[server.get_admin_user] = _fake_admin
        server.app.dependency_overrides[server.get_current_user] = _fake_admin
        original_get_company = server.get_user_company_id
        server.get_user_company_id = lambda _u: "co1"

        updates = []
        db_mock = MagicMock()
        db_mock.companies.find_one = AsyncMock(return_value=company)

        async def _update_one(flt, upd, **kw):
            updates.append(upd)
            return MagicMock(matched_count=1)

        db_mock.companies.update_one = AsyncMock(side_effect=_update_one)
        db_mock.audit_logs.insert_one = AsyncMock(return_value=MagicMock())
        original_db = server.db
        server.db = db_mock
        try:
            client = TestClient(server.app)
            r = client.put("/api/admin/company/insurance/manual", json={
                "general_liability_expiry": "07/21/2029",
                "workers_comp_expiry": "2029-08-21",
                "disability_expiry": "09/21/2029",
            })
            self.assertEqual(r.status_code, 200, r.text)
            records = updates[0]["$set"]["gc_insurance_records"]
            self.assertEqual([x["expiration_date"] for x in records],
                             ["2029-07-21", "2029-08-21", "2029-09-21"])
            for x in records:
                # `effective_date` is stamped as today and moved with it.
                self.assertRegex(x["effective_date"], r"^\d{4}-\d{2}-\d{2}$")
                # AND WHAT IT WROTE IS READABLE. A writer whose output its own
                # readers refuse is the failure this PR is about.
                self.assertFalse(read_expiry(x["expiration_date"]).unreadable)
        finally:
            server.db = original_db
            server.get_user_company_id = original_get_company
            server.app.dependency_overrides.clear()


class TheBackfillPlansWithoutWriting(unittest.TestCase):
    """The script is NOT run in this PR and changes 0 records on production
    today. Its planner is pure, so it can be asked what it would do."""

    def setUp(self):
        sys.path.insert(0, str(_BACKEND / "scripts"))
        import backfill_insurance_expiry_iso as mod
        self.mod = mod

    def _company(self, *records):
        return {"_id": "co1", "name": "Acme GC", "gc_insurance_records": list(records)}

    def test_a_legacy_date_is_planned_as_a_conversion(self):
        plans = self.mod.plan_for_company(self._company(
            {"insurance_type": "general_liability", "expiration_date": "07/21/2029",
             "effective_date": "07/21/2026"}))
        by_field = {p["field"]: p for p in plans}
        self.assertEqual(by_field["expiration_date"]["action"], "convert")
        self.assertEqual(by_field["expiration_date"]["after"], "2029-07-21")
        self.assertEqual(by_field["expiration_date"]["path"],
                         "gc_insurance_records.0.expiration_date")
        self.assertEqual(by_field["effective_date"]["after"], "2026-07-21")

    def test_an_ISO_date_is_left_ALONE_so_a_second_run_is_a_no_op(self):
        plans = self.mod.plan_for_company(self._company(
            {"insurance_type": "workers_comp", "expiration_date": "2029-07-21"}))
        exp = next(p for p in plans if p["field"] == "expiration_date")
        self.assertEqual(exp["action"], "iso")

    def test_an_unreadable_date_is_LEFT_and_never_guessed(self):
        """'7/2/29' is not widened to 2029. Nothing here can tell a dropped
        digit from a two-digit year, and a guess on a compliance record is
        worse than a row left alone."""
        plans = self.mod.plan_for_company(self._company(
            {"insurance_type": "disability", "expiration_date": "7/2/29"}))
        exp = next(p for p in plans if p["field"] == "expiration_date")
        self.assertEqual(exp["action"], "leave")
        self.assertIsNone(exp["after"])
        self.assertIn("MM/DD/YYYY", exp["why"])

    def test_it_plans_NOTHING_for_a_blank_or_absent_date(self):
        plans = self.mod.plan_for_company(self._company(
            {"insurance_type": "disability", "expiration_date": None}))
        self.assertEqual({p["action"] for p in plans}, {"blank"})
        self.assertTrue(all(p["after"] is None for p in plans))

    def test_it_touches_ONLY_the_two_date_fields(self):
        plans = self.mod.plan_for_company(self._company(
            {"insurance_type": "general_liability", "expiration_date": "07/21/2029",
             "source": "not_a_declared_source", "is_current": True,
             "ocr_confidence": 0.4}))
        self.assertEqual({p["field"] for p in plans},
                         {"expiration_date", "effective_date"})
        # In particular it does NOT repair a bad `source` — that is
        # permit_renewal's per-record validation to survive, not a value to
        # rewrite.
        self.assertTrue(all("source" not in p["path"] for p in plans))

    def test_the_planner_MUTATES_NOTHING(self):
        rec = {"insurance_type": "general_liability", "expiration_date": "07/21/2029"}
        company = self._company(rec)
        self.mod.plan_for_company(company)
        self.assertEqual(rec["expiration_date"], "07/21/2029")

    def test_a_nondict_in_the_list_is_reported_not_skipped(self):
        plans = self.mod.plan_for_company(self._company("not a record"))
        self.assertEqual([p["action"] for p in plans], ["leave"])

    def test_the_default_is_a_dry_run(self):
        """`--i-know` is the gate; nothing else authorises a write."""
        from prod_guard import check_guard
        self.assertFalse(check_guard(type("A", (), {"i_know": False})()))

    def test_the_legacy_execute_flag_is_REFUSED_by_name(self):
        """A runbook that says --execute must fail loudly, not silently no-op:
        an operator who sees a clean report believes a migration ran."""
        from prod_guard import refuse_legacy_flag
        with self.assertRaises(SystemExit) as cm:
            refuse_legacy_flag(["--execute"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
