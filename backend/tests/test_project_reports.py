"""Project reports -- every number from the job's records.

  * The numbers match the underlying records for a fixture job (counted
    here again, independently, from the same rows).
  * Sections with nothing in them are left out; branding, GC name, page
    numbers, generated time and "Source: Levelog records"; no phone numbers.
  * Scheduled: bi-weekly Monday 8 AM (even ISO weeks) / monthly 1st 8 AM,
    New York; sent once per recipient; held over Shabbos; retried on the
    shared schedule when WhatsApp fails.
  * DM phrasings: "send me a report for 588 for the last 2 weeks", "monthly
    report 588", "report all jobs September".
"""

from __future__ import annotations

import os
import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import project_report as R, wa_dm  # noqa: E402
from lib.logbook.daily_jobsite_source import as_daily_log_row  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _Harness, _optin  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx, _Wire, _run  # noqa: E402

NY = R.NY
START, END = date(2026, 10, 1), date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)      # Wed 4 PM New York


def _at(d: date, h=7, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(timezone.utc)


def fixture():
    """A job's records for Oct 1-14 (and the 14 days before)."""
    ck = []
    for i in range(28):
        d = START - timedelta(days=14) + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        arkon = 8 + (i % 3)                      # 8, 9, 10
        for w in range(arkon):
            ck.append({"worker_id": f"a{w}", "worker_company": "Arkon Builders",
                       "check_in_time": _at(d), "sst_status": "valid" if w < 6 else "missing"})
        ck.append({"worker_id": "a0", "worker_company": "Arkon Builders",        # twice: once
                   "check_in_time": _at(d, 13), "sst_status": "valid"})
        if d.day % 2 == 0:
            for w in range(3):
                ck.append({"worker_id": f"p{w}", "worker_company": "Power Direct",
                           "check_in_time": _at(d, 8), "sst_status": "expired" if w == 2 else "valid"})
    in_p = [r for r in ck if START <= r["check_in_time"].astimezone(NY).date() <= END]
    prev = [r for r in ck if r not in in_p]
    records = [
        {"record_type": "violation", "violation_number": "35123456", "violation_date": "2026-10-06",
         "detected_at": _at(date(2026, 10, 7)), "resolution_state": "open", "current_status": "ACTIVE"},
        {"record_type": "complaint", "complaint_number": "1234567", "complaint_date": "2026-10-09",
         "detected_at": _at(date(2026, 10, 9)), "complaint_status": "CLOSED", "current_status": "CLOSED"},
        {"record_type": "violation", "violation_number": "OLD1", "detected_at": _at(date(2026, 9, 1))},
        {"record_type": "violation", "violation_number": "SEED", "detected_at": _at(date(2026, 10, 3)),
         "is_seed_transition": True},
    ]
    events = [
        {"date": "2026-10-08", "time": "10:00 AM", "kind": "hearing", "title": "ECB hearing 35123456",
         "agency": "OATH", "status": "open"},
        {"date": "2026-10-20", "time": "9:00 AM", "kind": "inspection", "title": "Plumbing inspection",
         "agency": "DOB", "status": "open"},
        {"date": "2026-10-27", "kind": "pour", "title": "Slab pour 4th floor", "status": "open"},
        {"date": "2026-11-30", "kind": "inspection", "title": "Too far", "status": "open"},
        {"date": "2026-10-22", "kind": "inspection", "title": "Cancelled", "status": "cancelled"},
    ]
    commitments = [
        {"created_at": _at(date(2026, 10, 2)), "status": "open", "owner": {"name": "Dave"},
         "due": {"due_at": "2026-10-08"}},                                           # made, late, open
        {"created_at": _at(date(2026, 10, 3)), "status": "done", "owner": {"name": "Ana"},
         "history": [{"to": "done", "at": _at(date(2026, 10, 5))}]},                 # made, done
        {"created_at": _at(date(2026, 9, 20)), "status": "open", "owner": {"name": "Dave"},
         "due": {"due_at": "2026-10-30"}},                                           # open
        {"created_at": _at(date(2026, 9, 10)), "status": "cancelled", "owner": {"name": "Ana"}},
    ]
    punch_items = [
        {"status": "open", "assignee": {"name": "Dave"}, "created_at": _at(date(2026, 10, 2))},
        {"status": "open", "assignee": {"name": "Dave"}, "created_at": _at(date(2026, 9, 25))},
        {"status": "ready_to_check", "assignee": {"name": "Sam"}, "created_at": _at(date(2026, 10, 4))},
        {"status": "closed", "assignee": {"name": "Sam"}, "created_at": _at(date(2026, 10, 2)),
         "closed_at": _at(date(2026, 10, 6))},                                       # 4 days
        {"status": "closed", "assignee": {"name": "Ana"}, "created_at": _at(date(2026, 10, 1)),
         "closed_at": _at(date(2026, 10, 3))},                                       # 2 days
        {"status": "dropped", "created_at": _at(date(2026, 10, 2))},
    ]
    # Filed daily_jobsite logbooks, adapted exactly as the server reads them.
    def _book(d, *observations):
        return as_daily_log_row({"date": d, "project_id": "p588", "log_type": "daily_jobsite",
                                 "status": "submitted",
                                 "data": {"observations": [{"description": t} for t in observations],
                                          "activities": [{"company": "Arkon Builders", "num_workers": 9}]}})
    logs = [_book("2026-10-01", "Worker cut hand, first aid. Call Dave 718-555-0100"),
            _book("2026-10-02", "N/A"),
            _book("2026-10-05"),
            _book("2026-09-20", "Outside the period")]
    return dict(checkins=in_p, prev_checkins=prev, records=records, events=events,
                commitments=commitments, punch_items=punch_items, daily_logs=logs)


def rep():
    return R.compute(job="588 Thomas St", address="588 Thomas S Boyland St, Brooklyn",
                     gc="Blueview Construction", start=START, end=END, now=NOW, **fixture())


class TheNumbersAreTheRecords(unittest.TestCase):

    def test_manpower_counted_again_independently(self):
        f, r = fixture(), rep()
        per = defaultdict(lambda: defaultdict(set))
        for c in f["checkins"]:
            per[c["check_in_time"].astimezone(NY).date()][c["worker_company"]].add(c["worker_id"])
        totals = {d: sum(len(w) for w in v.values()) for d, v in per.items()}
        mp = r["manpower"]
        self.assertEqual(mp["days_worked"], len(totals))
        self.assertEqual(mp["man_days"], sum(totals.values()))
        self.assertEqual([row["total"] for row in mp["table"]], [totals[d] for d in sorted(totals)])
        self.assertEqual(mp["max"], max(totals.values()))
        self.assertEqual(mp["avg"], round(sum(totals.values()) / len(totals), 1))
        subs = {s["name"]: s for s in mp["sub_rows"]}
        for name in ("Arkon Builders", "Power Direct"):
            days = [d for d in per if per[d].get(name)]
            self.assertEqual(subs[name]["days"], len(days))
            self.assertEqual(subs[name]["man_days"], sum(len(per[d][name]) for d in days))
            self.assertEqual((subs[name]["first"], subs[name]["last"]), (min(days), max(days)))

    def test_dob_dot_new_in_the_period_with_number_and_status(self):
        recs = rep()["records"]
        self.assertEqual([(x["kind"], x["number"], x["open"]) for x in recs],
                         [("DOB violation", "35123456", True), ("DOB complaint", "1234567", False)])
        self.assertEqual([h["title"] for h in rep()["hearings"]], ["ECB hearing 35123456"])

    def test_phones_go_record_numbers_stay(self):
        for phone in ("718-555-0100", "(718) 555 0100", "+1 718 555 0100", "7185550100",
                      "+44 20 7946 0958"):
            self.assertEqual(R.no_phone(f"Call {phone} now"), "Call [number] now", phone)
        for record in ("35123456", "1234567", "V*071519LL1234", "B00123456-I1", "321456789"):
            self.assertEqual(R.no_phone(f"Record {record}"), f"Record {record}", record)

    def test_upcoming_is_the_next_two_weeks(self):
        self.assertEqual([e["title"] for e in rep()["upcoming"]],
                         ["Plumbing inspection", "Slab pour 4th floor"])

    def test_commitments(self):
        c = rep()["commitments"]
        self.assertEqual((c["made"], c["done"], c["late"], c["open"]), (2, 1, 1, 2))
        self.assertEqual(c["by_person"][0], {"name": "Dave", "made": 1, "done": 0, "late": 1, "open": 2})

    def test_punch(self):
        p = rep()["punch"]
        self.assertEqual((p["opened"], p["closed"], p["ready"], p["open"]), (4, 2, 1, 2))
        self.assertEqual(p["avg_days_to_close"], 3)
        self.assertEqual(p["by_assignee"], [{"name": "Dave", "open": 2}])

    def test_daily_logs_and_safety(self):
        r = rep()
        self.assertEqual((r["logs"]["logged"], r["logs"]["worked"]), (3, r["manpower"]["days_worked"]))
        self.assertEqual([(n["kind"], n["date"]) for n in r["logs"]["notable"]],
                         [("Observation", date(2026, 10, 1))])
        workers = {(c["worker_company"], c["worker_id"]) for c in fixture()["checkins"]}
        s = r["safety"]
        self.assertEqual(s["workers"], len({w for _, w in workers}))
        self.assertEqual(s["on_file"] + s["unverified"], s["workers"])
        self.assertEqual(s["unverified"], 5)            # a6-a9 missing + p2 expired

    def test_the_summary(self):
        lines = R.summary_lines(rep())
        mp = rep()["manpower"]
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith(f"588 Thomas St · Oct 1–14, 2026: {mp['days_worked']} days "
                                            f"worked, {mp['man_days']} man-days"), lines[0])
        self.assertIn("vs the period before", lines[0])
        self.assertEqual(lines[2], "DOB/DOT: 1 new DOB complaint, 1 new DOB violation.")
        self.assertEqual(lines[3], "Open: 2 commitments (1 late), 2 punch items, 1 ready to check.")
        self.assertEqual(lines[4], f"Daily logs: 3 of {mp['days_worked']} worked days.")


class ThePdf(unittest.TestCase):

    def test_branded_footer_no_phone(self):
        h = R.render_html([rep()], gc="Blueview Construction", title=R.title_for([rep()]), now=NOW)
        for want in ("LEVELOG", "Blueview Construction", "Source: Levelog records",
                     "counter(page)", "Generated Oct 14, 2026 4:00 PM ET",
                     "1. Summary", "2. Manpower", "3. Subs", "4. DOB / DOT", "5. Upcoming",
                     "6. Commitments", "7. Punch", "8. Daily logs", "9. Safety", "<svg"):
            self.assertIn(want, h, want)
        self.assertNotIn("718-555-0100", h)
        self.assertIn("[number]", h)

    def test_empty_sections_are_left_out(self):
        f = fixture()
        only = R.compute(job="J", address="A", gc="G", start=START, end=END, now=NOW,
                         checkins=f["checkins"])
        h = R.render_html([only], gc="G", title="t", now=NOW)
        self.assertIn("2. Manpower", h)
        for gone in ("4. DOB / DOT", "5. Upcoming", "6. Commitments", "7. Punch"):
            self.assertNotIn(gone, h, gone)

    def test_it_renders(self):
        pdf = server._report_pdf(R.render_html([rep()], gc="G", title="t", now=NOW))
        self.assertTrue(pdf.startswith(b"%PDF"))


class WhenScheduled(unittest.TestCase):

    def ny(self, y, mo, d, h, mi=5):
        return datetime(y, mo, d, h, mi, tzinfo=NY).astimezone(timezone.utc)

    def test_biweekly_monday_8am_even_weeks(self):
        self.assertEqual(R.scheduled_period("biweekly", self.ny(2026, 10, 12, 8)),   # ISO week 42
                         (date(2026, 9, 28), date(2026, 10, 11)))
        self.assertIsNone(R.scheduled_period("biweekly", self.ny(2026, 10, 19, 8)))  # week 43
        self.assertIsNone(R.scheduled_period("biweekly", self.ny(2026, 10, 12, 9)))
        self.assertIsNone(R.scheduled_period("biweekly", self.ny(2026, 10, 13, 8)))

    def test_monthly_first_8am(self):
        self.assertEqual(R.scheduled_period("monthly", self.ny(2026, 11, 1, 8)),
                         (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertIsNone(R.scheduled_period("monthly", self.ny(2026, 11, 2, 8)))
        self.assertIsNone(R.scheduled_period("off", self.ny(2026, 11, 1, 8)))


class _Reports:

    def setUp(self):
        self.media = []
        self.pdfs = 0

    def patches(self):
        async def media(chat, doc):
            self.media.append((chat, doc["_id"]))
            return True

        def pdf(html_text):
            self.pdfs += 1
            return b"%PDF-fake"
        return [patch.object(server, "_send_report_media", media),
                patch.object(server, "_report_pdf", pdf),
                patch.object(server, "_upload_to_r2", lambda data, key, ct="": f"https://r2/{key}")]


class TheSchedule(_Reports, unittest.TestCase):

    def world(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        db[server.PROJECT_REPORT_SETTINGS].rows.append(
            {"_id": THOMAS, "company_id": CO_A, "schedule": "biweekly", "pm_ids": []})
        return db

    def tick(self, c, at, *ps):
        with patch.object(server, "_send_report_media", self.patches()[0].new), \
                patch.object(server, "_report_pdf", self.patches()[1].new), \
                patch.object(server, "_upload_to_r2", self.patches()[2].new):
            return _run(server._report_schedule_tick(at))

    def test_sent_once_to_the_admin(self):
        db = self.world()
        at = datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)
        with _Ctx(db) as c:
            r1 = self.tick(c, at)
            r2 = self.tick(c, at + timedelta(minutes=15))
        self.assertEqual((r1["built"], r1["sent"]), (1, 1))
        self.assertEqual(r2["sent"], 0)
        self.assertEqual(self.pdfs, 1)                         # built once, reused
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 1)
        self.assertIn("Sep 28 – Oct 11, 2026", msgs[0])
        self.assertIn("Full report (PDF, link works 30 days): https://", msgs[0])
        self.assertEqual(len(self.media), 1)

    def test_over_shabbos_it_waits(self):
        db = self.world()
        db[server.PROJECT_REPORT_SETTINGS].rows[0]["schedule"] = "monthly"
        sat = datetime(2026, 8, 1, 8, 5, tzinfo=NY).astimezone(timezone.utc)   # Saturday the 1st
        with _Ctx(db) as c:
            r = self.tick(c, sat)
        self.assertEqual((r["queued"], r["sent"]), (1, 0))
        self.assertEqual([p for p in c.wire.calls if "message" in p], [])
        self.assertEqual(db[server.WA_QUIET_QUEUE].rows[0]["send"]["via"], "report_dm")

    def test_a_whatsapp_failure_is_retried(self):
        db = self.world()
        at = datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)
        with _Ctx(db, wire=_Wire([(500, {}, None)] * wa_dm.DM_SEND_ATTEMPTS)):
            r = self.tick(None, at)
        self.assertEqual(r["retrying"], 1)
        row = db[server.WA_QUIET_QUEUE].rows[0]
        self.assertEqual((row["retry"], row["send"]["via"]), (True, "report_dm"))


class InTheDm(_Reports, _Harness, unittest.TestCase):

    def setUp(self):
        _Reports.setUp(self)
        _Harness.setUp(self)

    def ask(self, text):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c:
                reply = self._send(c, f"{ADMIN_PHONE}@c.us", text)
        finally:
            for p in reversed(ps):
                p.stop()
        return reply, db

    def test_send_me_a_report_for_588_for_the_last_2_weeks(self):
        reply, db = self.ask("send me a report for 588 for the last 2 weeks")
        self.assertTrue(reply.startswith("588 Thomas S Boyland St · "), reply)
        self.assertEqual(len(reply.splitlines()), 6)
        self.assertIn("Full report (PDF, link works 30 days): https://", reply)
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(doc["project_ids"], [THOMAS])
        self.assertEqual((date.fromisoformat(doc["end"]) - date.fromisoformat(doc["start"])).days, 13)
        self.assertEqual(len(self.media), 1)
        self.assertEqual(self.agent_calls, [])

    def test_monthly_report_588(self):
        reply, db = self.ask("monthly report 588")
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(date.fromisoformat(doc["start"]).day, 1)

    def test_report_all_jobs_september(self):
        reply, db = self.ask("report all jobs September")
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(sorted(doc["project_ids"]), sorted([THOMAS, WALWORTH]))
        self.assertEqual(doc["start"][5:], "09-01")
        self.assertTrue(doc["title"].startswith("Project report — 2 jobs —"))

    def test_not_a_report_request(self):
        for t in ("daily report for 588", "what did the report say"):
            self.assertFalse(R.is_request(t), t)


if __name__ == "__main__":
    unittest.main()
