"""The report pipeline's reliability: the logs as amended, a PDF that failed
is rebuilt, a missed hour is caught up, one job's failure stays its own, and
the facts are stored with the report.

Each is a defect measured in the 2026-10-19 audit of the progress report:

  * amendments were excluded, so the report printed what the CP had corrected;
  * a PDF failure was cached under the period's key and never rebuilt;
  * a report was built only in the 8 AM hour, with no memory of a miss;
  * one exception stopped every later project's report in the tick;
  * nothing was stored but the PDF, so a report could not be audited.
"""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from tests.test_project_reports import NOW, _Reports  # noqa: E402
from tests.test_report_schedules import _World, ny  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx, _run  # noqa: E402


def _log(_id, day, workers, *, amendment_of=None, status="submitted", locked=True, reason=None, created=None):
    doc = {"_id": _id, "project_id": THOMAS, "log_type": "daily_jobsite", "date": day, "status": status,
           "is_locked": locked, "is_deleted": False, "created_at": created or datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
           "data": {"activities": [{"company": "Arkon Builders", "trade": "Framing", "num_workers": workers,
                                    "work_description": "Framing", "work_locations": "Floor 2", "photos": []}]}}
    if amendment_of:
        doc.update(is_amendment=True, parent_logbook_id=amendment_of, amendment_reason=reason or "headcount corrected")
    return doc


class TheDaysAreAsAmended(_Reports, unittest.TestCase):
    """The daily logs the report reads are the record's current version: the
    original until an amendment is signed and filed, then the amendment. The
    old reader excluded every amendment, so the report printed what the
    Competent Person had formally corrected."""

    def heads(self, *docs):
        db = _world()
        db.logbooks.rows.extend(docs)
        project = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        with _Ctx(db):
            rows = _run(server._report_rows(project, CO_A, date(2026, 10, 1), date(2026, 10, 14), NOW))
        return rows["logbooks"]

    def test_a_filed_amendment_replaces_the_original(self):
        heads = self.heads(_log("o1", "2026-10-06", 5),
                           _log("a1", "2026-10-06", 9, amendment_of="o1",
                                created=datetime(2026, 10, 7, 12, tzinfo=timezone.utc)))
        self.assertEqual([h["_id"] for h in heads], ["a1"])
        self.assertEqual(heads[0]["data"]["activities"][0]["num_workers"], 9)
        self.assertEqual((heads[0]["_chain_length"], heads[0]["_amendment_reason"]), (2, "headcount corrected"))

    def test_an_unsigned_or_withdrawn_amendment_is_not_a_correction(self):
        draft = _log("a1", "2026-10-06", 9, amendment_of="o1", status="draft", locked=False)
        withdrawn = _log("a2", "2026-10-06", 11, amendment_of="o1", status="withdrawn", locked=False)
        heads = self.heads(_log("o1", "2026-10-06", 5), draft, withdrawn)
        self.assertEqual([h["_id"] for h in heads], ["o1"])
        self.assertEqual(heads[0]["data"]["activities"][0]["num_workers"], 5)

    def test_a_day_with_only_a_draft_is_a_day_with_no_filed_log(self):
        self.assertEqual(self.heads(_log("d1", "2026-10-06", 5, status="draft", locked=False)), [])


class TheScheduleIsReliable(_World, unittest.TestCase):

    def tick(self, db, at, pdf=None, alert=None):
        ps, sent = self.patched()
        if pdf is not None:
            ps = [p for p in ps if getattr(p, "attribute", "") != "_report_pdf"] + [patch.object(server, "_report_pdf", pdf)]
        if alert is not None:
            ps.append(patch.object(server, "_send_failed_alert", alert))
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c:
                r = _run(server._report_schedule_tick(at))
        finally:
            for p in reversed(ps):
                p.stop()
        return r, c, sent

    def world1(self, **kw):
        return self.world(schedules=["weekly"], delivery={"whatsapp": True, "email": False}, **kw)

    def test_a_failed_pdf_is_rebuilt_not_kept(self):
        # The old build_project_report returned the PDF-less document for the
        # period's key on every later tick: one transient R2 or WeasyPrint
        # failure lost the report for good.
        calls = []

        def flaky(html_text):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("weasyprint blew up")
            return b"%PDF-fake"
        db = self.world1()
        r1, c1, _ = self.tick(db, ny(2026, 10, 19), pdf=flaky)
        docs = db[server.PROJECT_REPORTS].rows
        self.assertEqual((r1["pdf_failed"], r1["sent"], r1["built"]), (1, 0, 0))
        self.assertEqual((len(docs), docs[0]["status"], docs[0]["r2_key"], docs[0]["attempts"]),
                         (1, "failed", None, 1))
        self.assertEqual([p for p in c1.wire.calls if "message" in p], [])      # nothing goes without its PDF
        rid = docs[0]["_id"]
        r2, c2, _ = self.tick(db, ny(2026, 10, 19, 8, 20), pdf=flaky)
        docs = db[server.PROJECT_REPORTS].rows
        self.assertEqual((len(docs), docs[0]["_id"], docs[0]["status"], docs[0]["attempts"]), (1, rid, "ok", 2))
        self.assertTrue(docs[0]["r2_key"])
        self.assertEqual((r2["built"], r2["sent"]), (1, 1))

    def test_an_operator_is_told_once_after_the_attempts_run_out(self):
        alerts = []

        async def alert(kind, key, **kw):
            alerts.append((kind, kw["attempts"]))

        def boom(html_text):
            raise RuntimeError("no pdf")
        db = self.world1()
        for i in range(server.REPORT_PDF_ATTEMPTS + 2):
            self.tick(db, ny(2026, 10, 19, 8, 5) + timedelta(minutes=15 * i), pdf=boom, alert=alert)
        self.assertEqual(alerts, [("report_pdf", server.REPORT_PDF_ATTEMPTS)])

    def test_a_missed_8am_hour_is_caught_up_once(self):
        db = self.world1()
        r, c, _ = self.tick(db, ny(2026, 10, 19, 11, 30))          # the server was down at 8
        self.assertEqual((r["built"], r["sent"]), (1, 1))
        r2, _, _ = self.tick(db, ny(2026, 10, 20, 9, 0))           # Tuesday: still in the window, still one
        self.assertEqual((len(db[server.PROJECT_REPORTS].rows), r2["sent"]), (1, 0))
        r3, _, _ = self.tick(db, ny(2026, 10, 23, 9, 0))           # Friday: past the window
        self.assertEqual(r3["due"], 0)

    def test_a_schedule_switched_on_after_the_due_time_is_not_owed_that_report(self):
        db = self.world1(updated_at=ny(2026, 10, 19, 9, 0))
        r, _, _ = self.tick(db, ny(2026, 10, 19, 10, 0))
        self.assertEqual((r["due"], r["built"], db[server.PROJECT_REPORTS].rows), (0, 0, []))

    def test_one_jobs_failure_does_not_reach_the_next(self):
        db = self.world1()
        db[server.PROJECT_REPORT_SETTINGS].rows.append(
            {"_id": WALWORTH, "company_id": CO_A, "schedules": ["weekly"],
             "delivery": {"whatsapp": True, "email": False}})
        real = server.build_project_report

        async def picky(cid, projects, *a, **k):
            if str(projects[0]["_id"]) == THOMAS:
                raise RuntimeError("a bad row in one job")
            return await real(cid, projects, *a, **k)
        ps, _ = self.patched()
        ps = ps + [patch.object(server, "build_project_report", picky)]
        for p in ps:
            p.start()
        try:
            with _Ctx(db):
                r = _run(server._report_schedule_tick(ny(2026, 10, 19)))
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(r["failed"], 1)
        self.assertEqual([d["project_ids"] for d in db[server.PROJECT_REPORTS].rows], [[WALWORTH]])

    def test_the_facts_are_stored_with_the_report(self):
        import json
        db = self.world1()
        self.tick(db, ny(2026, 10, 19))
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual((doc["status"], doc["engine"]), ("ok", progress_report_engine()))
        snap = doc["snapshot"][0]
        json.dumps(snap)                                            # storable as it is
        for key in ("subs", "site", "regulatory", "evidence", "limitations", "overview", "start", "end"):
            self.assertIn(key, snap)
        self.assertEqual({e["id"] for e in snap["evidence"]} >= {"G", "L"}, True)


class TheDryRunTouchesNothing(_Reports, unittest.TestCase):

    def setUp(self):
        _Reports.setUp(self)

    def test_it_renders_and_stores_nothing(self):
        db = _world()
        uploads = []
        ps = self.patches() + [patch.object(server, "_upload_to_r2", lambda *a, **k: uploads.append(a) or "x")]
        for p in ps:
            p.start()
        try:
            with _Ctx(db):
                project = _run(db.projects.find_one({"_id": THOMAS}))
                got = _run(server.build_project_report(CO_A, [project], date(2026, 10, 1), date(2026, 10, 14),
                                                       now=NOW, by="dry-run", source="dry_run", dry_run=True))
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(got["pdf"], b"%PDF-fake")
        self.assertEqual(db[server.PROJECT_REPORTS].rows, [])
        self.assertEqual(uploads, [])
        self.assertTrue(got["snapshot"] and got["reports"])


def progress_report_engine():
    from lib import progress_report
    return progress_report.ENGINE_VERSION


class AMultiJobReportIsNotShownToAPmOnOneOfItsJobs(unittest.TestCase):

    def test_summary_lines_name_every_job(self):
        doc = {"_id": "r1", "company_id": CO_A, "project_ids": [THOMAS, WALWORTH], "start": "2026-10-01",
               "end": "2026-10-14", "title": "t", "summary": ["588 Thomas · Oct 1-14", "8 Walworth · Oct 1-14"],
               "source": "dm"}
        self.assertEqual(len(server._report_view(doc)["summary"]), 2)
        self.assertEqual(server._report_view(doc, show_summary=False)["summary"], [])


if __name__ == "__main__":
    unittest.main()
