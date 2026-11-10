"""DOB sign-offs reach the assistant, and a signed-off filing is never live.

LIVE, Nov 9 11:37 PM. The owner asked the WhatsApp assistant "What inspections
happened in 588 this far since beginning of the project". It answered that no
inspection history was filed and that DOB passes and sign-offs "aren't in
anything I can read". NYC Open Data (w9ak-ipjd, BIN 3430621) shows four
Letters of Completion:

    B01075600-I1  full demolition            LOC Issued  2026-07-08
    B01074863-I1  construction fence         LOC Issued  2026-07-22
    B01141294-S8  support of excavation      LOC Issued  2026-10-29
    B01141294-S4  foundation + earthwork     LOC Issued  2026-11-05

The rows were in dob_logs (the permit twins say 'Signed-off'); the cause was
three-fold and each part is pinned here:

  1. dob_status printed BIN, BBL and violations only; active_permits keeps
     issued permits only. No DM tool read a sign-off, so the model said it
     could not.
  2. _extract_job_status_fields kept status/date/type/description and dropped
     signoff_date, approved_date, first_permit_date, work_on_floor and the
     work-type flags; and the sync's twin collapse dropped the job-filing row
     of every permit-bearing filing WHOLE, the sign-off date with it.
  3. 'LOC ISSUED' contains ISSUED, so the permit classifier read a sign-off
     as a permit being issued; and a signed-off permit's expiry still drove
     "expiring" reminders (group alert, morning brief, Upcoming, progress
     report).

The fixture is the real public rows (tests/fixtures/dob_588_signoffs.json),
names stripped, run through the SAME extractors and collapse the sync runs.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_brain, dob_signal_classifier, dob_signoffs  # noqa: E402
from lib import report_regulatory, wa_alerts, wa_brief  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

FIX = json.loads((Path(__file__).parent / "fixtures" / "dob_588_signoffs.json")
                 .read_text(encoding="utf-8"))
SEEN = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

#: The four Letters of Completion, as NYC Open Data states them.
SIGNOFFS = {
    "B01075600-I1": "2026-07-08",
    "B01074863-I1": "2026-07-22",
    "B01141294-S8": "2026-10-29",
    "B01141294-S4": "2026-11-05",
}


def _raw(electrical_complete=False):
    """The sync's raw records: w9ak-ipjd as job_status, rbx6-tga4 and
    dm9a-ab7w as permit, tagged the way _query_dob_apis tags them. The
    SYNTHETIC completed electrical job only when asked for."""
    out = []
    for r in FIX["w9ak_ipjd"]:
        out.append(dict(copy.deepcopy(r), _record_type="job_status", _id_field="job_filing_number"))
    keys = ("rbx6_tga4", "dm9a_ab7w") + (("electrical_complete",) if electrical_complete else ())
    for key in keys:
        for r in FIX[key]:
            out.append(dict(copy.deepcopy(r), _record_type="permit", _id_field="job_filing_number"))
    return out


def _stored(raw=None):
    """dob_logs rows as the sync stores them, through the real collapse and
    extractors (run_dob_sync_for_project's insert path, minus the I/O)."""
    records, _ = server._collapse_job_status_twins(raw if raw is not None else _raw())
    rows = []
    for i, rec in enumerate(records):
        rt = rec["_record_type"]
        extra = (server._extract_permit_fields(rec) if rt == "permit"
                 else server._extract_job_status_fields(rec))
        jfn = rec["job_filing_number"]
        rid = f"permit:{jfn}:{rec.get('work_type') or ''}" if rt == "permit" else jfn
        row = {"_id": f"r{i}", "project_id": THOMAS, "company_id": CO_A, "record_type": rt,
               "raw_dob_id": rid, "is_deleted": False, "detected_at": SEEN, **extra}
        row["current_status"] = server._extract_dob_log_status(row)
        rows.append(row)
    return rows


def _by_number(rows, number):
    return [r for r in rows if (r.get("job_number") or r.get("job_filing_number")) == number]


# ── 2. Ingest keeps the sign-off ────────────────────────────────────────────

class TheExtractionKeepsTheSignOff(unittest.TestCase):
    def _filing(self, number):
        return next(r for r in FIX["w9ak_ipjd"] if r["job_filing_number"] == number)

    def test_the_job_filing_keeps_signoff_and_its_dates(self):
        f = server._extract_job_status_fields(self._filing("B01141294-S4"))
        self.assertEqual(f["filing_status"], "LOC Issued")
        self.assertEqual(f["signoff_date"], "2026-11-05T00:00:00.000")
        self.assertEqual(f["approved_date"], "2026-01-13T19:54:45.000")
        self.assertEqual(f["first_permit_date"], "2026-08-04T00:00:00.000")
        self.assertTrue(f["work_on_floor"].startswith("Floor Number(s)-1-SO-5912"))
        self.assertEqual(f["work_types"], "foundation, earthwork")

    def test_the_work_type_flags_name_the_work(self):
        self.assertEqual(server._extract_job_status_fields(
            self._filing("B01075600-I1"))["work_types"], "full demolition")
        self.assertEqual(server._extract_job_status_fields(
            self._filing("B01074863-I1"))["work_types"], "construction fence")
        # S8's flags are all NO (support_of_excavation is 'No'): no invented work.
        self.assertIsNone(server._extract_job_status_fields(
            self._filing("B01141294-S8"))["work_types"])

    def test_the_twin_collapse_folds_the_signoff_onto_every_permit(self):
        records, dropped = server._collapse_job_status_twins(_raw())
        self.assertEqual(dropped, 6)              # every w9ak row with a permit twin
        standalone = [r["job_filing_number"] for r in records if r["_record_type"] == "job_status"]
        self.assertEqual(standalone, ["B01141294-P1"])
        s4 = _by_number(_stored(), "B01141294-S4")
        self.assertEqual(sorted(r["work_type"] for r in s4), ["Earth Work", "Foundation"])
        for r in s4:
            self.assertEqual(r["signoff_date"], "2026-11-05T00:00:00.000")
            self.assertEqual(r["job_filing_status"], "LOC Issued")
            self.assertEqual(r["work_types"], "foundation, earthwork")

    def test_a_permit_without_a_twin_writes_no_signoff_keys(self):
        """A sync whose job-filing query failed must not blank a stored date."""
        raw = [r for r in _raw() if r["_record_type"] == "permit"]
        s4 = _by_number(_stored(raw), "B01141294-S4")[0]
        self.assertNotIn("signoff_date", s4)
        self.assertNotIn("job_filing_status", s4)

    def test_electrical_completion_is_kept_only_once_complete(self):
        done = server._extract_permit_fields(FIX["electrical_complete"][0])
        self.assertEqual(done["electrical_job_status"], "Job is complete")
        self.assertEqual(done["electrical_completion_date"], "2026-10-01T00:00:00.000")
        open_job = server._extract_permit_fields(FIX["dm9a_ab7w"][0])
        self.assertEqual(open_job["electrical_job_status"], "Job in Process")
        # Its completion_date (2030-05-31) is an estimate, not a completion.
        self.assertNotIn("electrical_completion_date", open_job)


# ── 3. One classification of "signed off" ───────────────────────────────────

class TheClassification(unittest.TestCase):
    SIGNED = ("LOC Issued", "Signed-off", "SIGNED-OFF", "Full Demolition Signed-off",
              "TA Certificate of Operation Issued", "PA Certificate of Operation Issued",
              "CO Issued", "Job is complete", "Complete")
    NOT_SIGNED = ("Permit Issued", "PERMIT ISSUED", "Permit Entire", "Approved",
                  "QA Review for LOC", "Inspection not complete due to withdrawal",
                  "Job in Process", "NOT SIGNED OFF", "Filing Withdrawn",
                  "Inspection Complete", "ISSUED & PRINTED", "", None)

    def test_every_dob_signoff_vocabulary_reads_signed_off(self):
        for s in self.SIGNED:
            with self.subTest(status=s):
                self.assertTrue(dob_signoffs.is_signed_off(s))

    def test_open_statuses_do_not(self):
        for s in self.NOT_SIGNED:
            with self.subTest(status=s):
                self.assertFalse(dob_signoffs.is_signed_off(s))

    def test_a_loc_is_not_a_permit_being_issued(self):
        self.assertEqual(dob_signal_classifier.classify_signal_kind(
            {"record_type": "permit", "current_status": "LOC ISSUED"}), "permit")
        self.assertEqual(dob_signal_classifier.classify_signal_kind(
            {"record_type": "permit", "current_status": "PERMIT ISSUED"}), "permit_issued")

    def _db_with(self, rows):
        db = _db()
        db.dob_logs.rows.extend(rows)
        return db

    def test_active_permits_leaves_out_every_signed_off_filing(self):
        rows = _stored()
        # A permit whose own status lags ('Permit Issued') while its job filing
        # already has the LOC is finished work too.
        lag = dict(_by_number(rows, "B01141294-S6")[0], _id="lag", raw_dob_id="permit:LAG",
                   job_number="B09999999-I1", job_filing_status="LOC Issued")
        db = self._db_with(rows + [lag])
        with patch.object(server, "db", db):
            out = _run(server._handle_active_permits(THOMAS, company_id=CO_A))
        for number in list(SIGNOFFS) + ["B09999999-I1"]:
            self.assertNotIn(f"Job {number}", out)
        self.assertIn("Job B01141294-S6", out)                    # Permit Issued, live
        self.assertIn("Job B01141294-I1", out)

    def test_a_signed_off_permit_is_no_expiry_reminder(self):
        fence = _by_number(_stored(), "B01074863-I1")[0]           # expires 2027-01-20
        live = dict(fence, _id="live", raw_dob_id="permit:LIVE", permit_status="Permit Issued",
                    current_status="PERMIT ISSUED", job_filing_status=None)
        kinds = [(i["kind"], i["rec"]["_id"]) for i in
                 wa_alerts.collect([fence, live], [], date(2027, 1, 10))]
        self.assertEqual(kinds, [("permit", "live")])
        brief = wa_brief.job_items([fence, live], SEEN, datetime(2027, 1, 10, 14, tzinfo=timezone.utc))
        self.assertEqual(len([i for i in brief if "expires" in i["text"]]), 1)
        events = server._upcoming_city_events([fence, live], [], date(2027, 1, 10))
        self.assertEqual([e["source_ref"] for e in events], ["dob:permit:LIVE"])

    def test_the_progress_report_never_calls_a_signed_off_permit_expiring(self):
        fence = _by_number(_stored(), "B01074863-I1")[0]
        live = dict(fence, _id="live", raw_dob_id="permit:LIVE", permit_status="Permit Issued",
                    current_status="PERMIT ISSUED", job_number="B07777777-I1")
        sync = {"tracking": True, "dob": datetime(2026, 12, 2, tzinfo=timezone.utc),
                "dob_complete": True, "dot": datetime(2026, 12, 2, tzinfo=timezone.utc)}
        got = report_regulatory.build([fence, live], [], date(2026, 11, 1), date(2026, 11, 30),
                                      today=date(2026, 11, 30), sync=sync,
                                      now=datetime(2026, 12, 2, tzinfo=timezone.utc))
        self.assertEqual([e["number"] for e in got["expiring"]], ["B07777777-I1"])


# ── 1. The assistant's answer ───────────────────────────────────────────────

class TheSignOffsInDobStatus(unittest.TestCase):
    def _status(self, rows):
        db = _db()
        db.dob_logs.rows.extend(rows)
        with patch.object(server, "db", db):
            return _run(server._handle_dob_status(THOMAS, company_id=CO_A))

    def test_all_four_letters_of_completion_with_dates_and_numbers(self):
        out = self._status(_stored())
        self.assertIn("DOB sign-offs (4) — DOB-verified, NYC Open Data:", out)
        self.assertIn("  - B01075600-I1 — full demolition: signed off by DOB "
                      "(Letter of Completion) on 2026-07-08", out)
        self.assertIn("  - B01074863-I1 — construction fence: signed off by DOB "
                      "(Letter of Completion) on 2026-07-22", out)
        self.assertIn("  - B01141294-S8 — support of excavation: signed off by DOB "
                      "(Letter of Completion) on 2026-10-29", out)
        self.assertIn("  - B01141294-S4 — foundation, earthwork: signed off by DOB "
                      "(Letter of Completion) on 2026-11-05", out)
        # Oldest first: "since the beginning of the project" reads in order.
        order = [out.index(n) for n in SIGNOFFS]
        self.assertEqual(order, sorted(order))
        self.assertIn(dob_signoffs.INSPECTIONS_NOT_PUBLIC, out)

    def test_one_entry_per_filing_and_a_deleted_row_is_not_one(self):
        rows = _stored()
        gone = dict(_by_number(rows, "B01141294-S8")[0], _id="gone", raw_dob_id="permit:GONE",
                    job_number="B09999998-I1", is_deleted=True)
        got = [e["number"] for e in dob_signoffs.signoffs(rows + [gone])]
        self.assertEqual(got, list(SIGNOFFS))      # S4's two permits are one entry

    def test_rows_stored_before_this_change_still_answer(self):
        """Today's stored permit rows say 'Signed-off' with no sign-off date
        until the next sync refreshes them: listed, the date not invented."""
        raw = [r for r in _raw() if r["_record_type"] == "permit"]
        out = self._status(_stored(raw))
        self.assertIn("  - B01141294-S4 — earth work, foundation: signed off by DOB "
                      "(DOB's sign-off date is not on the stored record yet)", out)
        self.assertIn("DOB sign-offs (4)", out)

    def test_a_completed_electrical_job_is_listed(self):
        out = self._status(_stored(_raw(electrical_complete=True)))
        self.assertIn("  - B01409251-I1-EL — electrical: installation of lighting for sidewalk "
                      "shed 92 lf: electrical job marked complete by DOB on 2026-10-01", out)
        self.assertIn("DOB sign-offs (5)", out)
        # The job still in process is not a sign-off.
        self.assertIn("B01445590-I1-EL", json.dumps(_stored(), default=str))
        self.assertNotIn("  - B01445590-I1-EL — ", out)

    def test_another_companys_sign_offs_are_not_read(self):
        rows = [dict(r, company_id="co_b") for r in _stored()]
        out = self._status(rows)
        self.assertIn("DOB sign-offs: none on the DOB job filings and permits LeveLog holds", out)
        self.assertIn(dob_signoffs.INSPECTIONS_NOT_PUBLIC, out)


class TheBrainAnswersWhatInspectionsHappened(_Brain):
    QUESTION = "What inspections happened in 588 this far since beginning of the project"

    def test_the_question_reaches_the_sign_offs(self):
        self.db.dob_logs.rows.extend(_stored())
        answer = ("588 DOB sign-offs (DOB-verified):\n"
                  "- B01075600-I1 full demolition, Letter of Completion 2026-07-08\n"
                  "- B01074863-I1 construction fence, 2026-07-22\n"
                  "- B01141294-S8 support of excavation, 2026-10-29\n"
                  "- B01141294-S4 foundation + earthwork, 2026-11-05\n"
                  "DOB NOW: Inspections was not checked, and DEP water-main inspections are not a "
                  "source LeveLog reads.")

        def first(kw):
            system = kw["messages"][0]["content"]
            self.assertIn('For "what inspections happened" call dob_status AND', system)
            self.assertIn("Never say no inspections happened", system)
            tool = next(t for t in kw["tools"] if t["function"]["name"] == "dob_status")
            self.assertIn("'what inspections happened'", tool["function"]["description"])
            return resp(use("dob_status", {"job": "588"}))

        def answer_from(kw):
            res = "\n".join(last_tool_results(kw))
            for number, day in SIGNOFFS.items():
                self.assertIn(f"{number} — ", res)
                self.assertIn(f"(Letter of Completion) on {day}", res)
            self.assertIn("DEP water-main", res)
            return resp(text(answer))
        llm = FakeLLM(first, answer_from)
        with _Ctx(db=self.db) as c:
            out = self.say(c, self.QUESTION, llm)
        self.assertEqual(out, [answer])

    def test_the_prompt_no_longer_lets_a_short_list_become_a_claim(self):
        self.assertIn("Never say no inspections happened, or that sign-offs are not in anything "
                      "you can read", " ".join(dm_brain.SYSTEM_PROMPT.split()))


if __name__ == "__main__":
    unittest.main()
