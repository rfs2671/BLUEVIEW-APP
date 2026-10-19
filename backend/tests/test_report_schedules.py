"""Project → Reports: schedules, recipients, delivery, presets, the list.

  * Any combination per job: daily (the daily report), weekly (Monday), bi-
    weekly (Monday, even weeks), monthly (the 1st), quarterly (Jan / Apr /
    Jul / Oct 1st) -- each due report built once per job, kind and period.
  * Recipients: the admins and PMs picked (a row from before the picker:
    every admin and the PMs chosen). Delivery: WhatsApp DM and / or email,
    each on its own toggle.
  * Generate now: last 7 days, last 2 weeks, this month, last month, this
    quarter, the whole project (from its start), a custom range.
  * The list: every report of the job -- scheduled or asked for, in the app
    or in WhatsApp -- with its period, when, who asked.
  * Admins and full-access PMs set it; anyone on the job sees it.
"""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import project_report as R  # noqa: E402
from tests.test_project_reports import _Reports  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _optin  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, PM_PHONE, _Ctx, _run  # noqa: E402

NY = R.NY
ADMIN = {"_id": "u_admin", "id": "u_admin", "company_id": CO_A, "role": "admin",
         "account_status": "approved"}
PM = {"_id": "u_pm", "id": "u_pm", "company_id": CO_A, "role": "pm", "account_status": "approved",
      "assigned_projects": [THOMAS]}


def ny(y, mo, d, h=8, mi=5):
    return datetime(y, mo, d, h, mi, tzinfo=NY).astimezone(timezone.utc)


class WhenEachIsDue(unittest.TestCase):

    def test_weekly_monday_the_week_before(self):
        self.assertEqual(R.scheduled_period("weekly", ny(2026, 10, 19)),
                         (date(2026, 10, 12), date(2026, 10, 18)))
        self.assertIsNone(R.scheduled_period("weekly", ny(2026, 10, 20)))
        self.assertIsNone(R.scheduled_period("weekly", ny(2026, 10, 19, 9)))

    def test_quarterly_the_quarter_before(self):
        self.assertEqual(R.scheduled_period("quarterly", ny(2026, 10, 1)),
                         (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(R.scheduled_period("quarterly", ny(2027, 1, 1)),
                         (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertIsNone(R.scheduled_period("quarterly", ny(2026, 11, 1)))

    def test_presets(self):
        now = ny(2026, 10, 15, 16)
        got = {k: R.preset_period(k, now, date(2026, 3, 2))[:2] for k in R.PRESETS}
        self.assertEqual(got, {
            "last_7_days": (date(2026, 10, 9), date(2026, 10, 15)),
            "last_2_weeks": (date(2026, 10, 2), date(2026, 10, 15)),
            "this_month": (date(2026, 10, 1), date(2026, 10, 15)),
            "last_month": (date(2026, 9, 1), date(2026, 9, 30)),
            "this_quarter": (date(2026, 10, 1), date(2026, 10, 15)),
            "whole_project": (date(2026, 3, 2), date(2026, 10, 15))})
        self.assertIsNone(R.preset_period("yesterday", now))

    def test_a_row_from_before_reads_as_its_one_choice(self):
        old = R.settings_from({"schedule": "monthly", "pm_ids": ["u_pm"]})
        self.assertEqual((old["schedules"], old["recipient_ids"], old["delivery"]),
                         (["monthly"], None, {"whatsapp": True, "email": False}))
        self.assertEqual(R.schedule_summary(R.settings_from(
            {"schedules": ["quarterly", "weekly"], "delivery": {"email": True, "whatsapp": False}})),
            "Weekly and quarterly — by email")


class _World(_Reports):

    def world(self, **settings):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        _optin(db, "u_pm", PM_PHONE)
        db[server.PROJECT_REPORT_SETTINGS].rows.append({"_id": THOMAS, "company_id": CO_A, **settings})
        return db

    def patched(self):
        sent = []

        async def notify(db, **kw):
            sent.append((kw["recipient"], kw["trigger_type"], bool(kw.get("attachments")), kw["subject"]))
            return {"status": "sent"}
        ps = self.patches() + [patch("lib.notifications.send_notification", notify),
                               patch.object(server, "_r2_bytes", lambda k: b"%PDF-fake")]
        return ps, sent


class TheSchedule(_World, unittest.TestCase):

    def tick(self, db, at):
        ps, sent = self.patched()
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c:
                r = _run(server._report_schedule_tick(at))
        finally:
            for p in reversed(ps):
                p.stop()
        return r, c, sent

    def test_weekly_and_biweekly_on_the_same_monday_are_two_reports(self):
        db = self.world(schedules=["weekly", "biweekly", "monthly", "quarterly"],
                        recipient_ids=["u_admin"], delivery={"whatsapp": True, "email": True})
        r, c, sent = self.tick(db, ny(2026, 10, 12))          # ISO week 42: both
        docs = db[server.PROJECT_REPORTS].rows
        self.assertEqual(sorted(d["kind"] for d in docs), ["biweekly", "weekly"])
        self.assertEqual(sorted((d["start"], d["end"]) for d in docs),
                         [("2026-09-28", "2026-10-11"), ("2026-10-05", "2026-10-11")])
        self.assertEqual((r["built"], r["sent"], r["emailed"]), (2, 2, 2))
        self.assertEqual({s[0] for s in sent}, {"a@a"})             # the one picked
        self.assertTrue(all(s[1] == "project_progress_report" and s[2] for s in sent))  # PDF attached
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 2)
        self.assertEqual(len(self.media), 2)

    def test_monthly_and_quarterly_on_october_1st(self):
        db = self.world(schedules=["monthly", "quarterly"], delivery={"whatsapp": True, "email": False})
        r, c, sent = self.tick(db, ny(2026, 10, 1))
        self.assertEqual(sorted((d["kind"], d["start"]) for d in db[server.PROJECT_REPORTS].rows),
                         [("monthly", "2026-09-01"), ("quarterly", "2026-07-01")])
        self.assertEqual(sent, [])                                 # email is off
        # A row from before the picker: every admin and the PMs chosen -- none
        # here, so the admin only.
        to = {p.get("chatId") for p in c.wire.calls if "message" in p}
        self.assertEqual(to, {f"{ADMIN_PHONE}@c.us"})

    def test_email_only(self):
        db = self.world(schedules=["weekly"], recipient_ids=["u_admin", "u_pm"],
                        delivery={"whatsapp": False, "email": True})
        r, c, sent = self.tick(db, ny(2026, 10, 19))
        self.assertEqual(sorted(s[0] for s in sent), ["a@a", "p@a"])
        self.assertEqual([p for p in c.wire.calls if "message" in p], [])

    def test_built_once_per_period(self):
        db = self.world(schedules=["weekly"], delivery={"whatsapp": True, "email": True})
        self.tick(db, ny(2026, 10, 19))
        r, c, sent = self.tick(db, ny(2026, 10, 19, 8, 20))
        self.assertEqual(len(db[server.PROJECT_REPORTS].rows), 1)
        self.assertEqual(r["sent"], 0)                             # the ledger: once a person

    def test_a_row_from_before_keeps_its_report_key(self):
        db = self.world(schedule="biweekly", pm_ids=[])
        self.tick(db, ny(2026, 10, 12))
        self.assertEqual(db[server.PROJECT_REPORTS].rows[0]["key"],
                         f"sched:{THOMAS}:2026-09-28:2026-10-11")


class TheDailyReport(_World, unittest.TestCase):
    """Daily in Project → Reports: the daily report also goes to the people
    picked -- by email with the list's, and by WhatsApp (the PDF)."""

    def run_daily(self, db, at, resend_key=""):
        ps, sent = self.patched()
        ps += [patch.object(server, "RESEND_API_KEY", resend_key),
               patch.object(server, "generate_combined_report",
                            lambda *a, **k: _async("<html><body>Daily</body></html>")),
               patch.object(server, "_next_report_number", lambda pid: _async(7)),
               patch.object(server, "resend", type("R", (), {"api_key": None})())]
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c:
                _run(server.check_and_send_reports(at))
        finally:
            for p in reversed(ps):
                p.stop()
        return c, sent

    def daily_world(self, **delivery):
        db = self.world(schedules=["daily"], recipient_ids=["u_admin"], delivery=delivery)
        proj = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        proj.update(report_send_time="18:00", report_email_list=["owner@x.com"])
        db.checkins.rows.append({"_id": "ck", "project_id": THOMAS, "worker_id": "w1",
                                 "check_in_time": ny(2026, 10, 15, 7)})
        return db

    def test_by_whatsapp_the_pdf_and_kept_in_the_list(self):
        db = self.daily_world(whatsapp=True, email=False)
        c, sent = self.run_daily(db, ny(2026, 10, 15, 18, 0))
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual((doc["kind"], doc["start"], doc["source"]), ("daily", "2026-10-15", "schedule"))
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 1)
        self.assertIn("Daily report · Thu Oct 15", msgs[0])
        self.assertTrue(msgs[0].endswith("Full report (PDF) attached."), msgs[0])
        self.assertEqual(len(self.media), 1)

    def test_by_email_with_the_list(self):
        db = self.daily_world(whatsapp=False, email=True)
        c, sent = self.run_daily(db, ny(2026, 10, 15, 18, 0), resend_key="k")
        self.assertEqual(sorted(s[0] for s in sent), ["a@a", "owner@x.com"])
        self.assertTrue(all(s[1] == "project_daily_report" for s in sent))
        # Email only: still kept in the job's reports list (Codex on #805).
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual((doc["kind"], doc["start"], bool(doc["r2_key"])), ("daily", "2026-10-15", True))
        self.assertEqual([p for p in c.wire.calls if "message" in p], [])

    def test_not_at_its_time(self):
        db = self.daily_world(whatsapp=True, email=False)
        c, sent = self.run_daily(db, ny(2026, 10, 15, 17, 0))
        self.assertEqual(db[server.PROJECT_REPORTS].rows, [])


async def _async(v):
    return v


class TheApp(_World, unittest.TestCase):

    def call(self, fn, *a, db=None, **k):
        async def scope(company_id, project_id):
            return next((p for p in db.projects.rows if p["_id"] == project_id), None)
        ps = self.patches() + [patch.object(server, "_bot_project_scope", scope)]
        for p in ps:
            p.start()
        try:
            with _Ctx(db):
                return _run(fn(*a, **k))
        finally:
            for p in reversed(ps):
                p.stop()

    def test_settings_any_combination_people_delivery(self):
        db = self.world(schedule="monthly", pm_ids=[])
        body = server.ProjectReportSettingsIn(schedules=["quarterly", "daily", "weekly"],
                                              recipient_ids=["u_pm", "u_cp", "u_b"],
                                              delivery={"email": True, "whatsapp": False})
        out = self.call(server.put_project_report_settings, THOMAS, body, current_user=ADMIN, db=db)
        self.assertEqual(out["schedules"], ["daily", "weekly", "quarterly"])
        self.assertEqual(out["recipient_ids"], ["u_pm"])        # never a CP, never another company
        self.assertEqual(out["delivery"], {"whatsapp": False, "email": True})
        self.assertEqual(out["summary"], "Daily, weekly and quarterly — by email")
        self.assertEqual({p["id"] for p in out["people"]}, {"u_admin", "u_pm"})
        self.assertEqual([k["key"] for k in out["kinds"]], list(R.KINDS))

    def test_the_daily_email_list_is_on_the_reports_screen(self):
        """Report Settings is folded into Reports: the daily report's send
        time and its addresses come with the job's report settings -- the
        addresses to an admin only, who can change them."""
        db = self.world()
        proj = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        proj.update(report_send_time="17:00", report_email_list=["owner@example.com", "pm@example.com"])
        out = self.call(server.get_project_report_settings, THOMAS, current_user=ADMIN, db=db)
        self.assertEqual(out["daily"], {"send_time": "17:00", "email_list": 2,
                                        "emails": ["owner@example.com", "pm@example.com"]})
        out = self.call(server.get_project_report_settings, THOMAS, current_user=PM, db=db)
        self.assertEqual(out["daily"], {"send_time": "17:00", "email_list": 2})
        self.assertFalse(out["can_edit"])

    def test_bad_kind_and_not_an_admin(self):
        db = self.world()
        with self.assertRaises(HTTPException):
            self.call(server.put_project_report_settings, THOMAS,
                      server.ProjectReportSettingsIn(schedules=["hourly"]), current_user=ADMIN, db=db)
        with self.assertRaises(HTTPException) as e:
            self.call(server.put_project_report_settings, THOMAS,
                      server.ProjectReportSettingsIn(schedules=["weekly"]), current_user=PM, db=db)
        self.assertEqual(e.exception.status_code, 403)

    def test_an_app_build_from_before_still_saves(self):
        db = self.world()
        out = self.call(server.put_project_report_settings, THOMAS,
                        server.ProjectReportSettingsIn(schedule="biweekly", pm_ids=["u_pm"]),
                        current_user=ADMIN, db=db)
        self.assertEqual((out["schedules"], out["schedule"], sorted(out["recipient_ids"])),
                         (["biweekly"], "biweekly", ["u_admin", "u_pm"]))

    def test_generate_now_presets_and_the_list(self):
        db = self.world()
        proj = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        proj["created_at"] = datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
        with patch.object(server, "datetime", _Frozen):
            made = self.call(server.create_project_report, THOMAS,
                             server.ProjectReportRequest(preset="whole_project"), current_user=ADMIN, db=db)
        self.assertEqual((made["start"], made["requested_by"], made["source_label"]),
                         ("2026-06-01", "Ada Admin", "Made in the app"))
        with self.assertRaises(HTTPException):
            self.call(server.create_project_report, THOMAS,
                      server.ProjectReportRequest(preset="forever"), current_user=ADMIN, db=db)
        db[server.PROJECT_REPORTS].rows.append({
            "_id": "s1", "company_id": CO_A, "project_ids": [THOMAS], "start": "2026-10-05",
            "end": "2026-10-11", "title": "t", "source": "schedule", "kind": "weekly",
            "created_at": datetime(2026, 10, 12, 12, tzinfo=timezone.utc)})
        db[server.PROJECT_REPORTS].rows.append({
            "_id": "d1", "company_id": CO_A, "project_ids": [THOMAS], "start": "2026-10-01",
            "end": "2026-10-14", "title": "t", "source": "dm", "created_by": "u_pm",
            "created_at": datetime(2026, 10, 14, 12, tzinfo=timezone.utc)})
        out = self.call(server.list_project_reports, THOMAS, current_user=PM, db=db)
        by = {r["id"]: r for r in out["reports"]}
        self.assertEqual((by["s1"]["requested_by"], by["s1"]["kind_label"], by["s1"]["period"]),
                         ("Schedule", "Weekly", "Oct 5–11, 2026"))
        self.assertEqual((by["d1"]["requested_by"], by["d1"]["source_label"]),
                         ("Pat PM", "Asked in WhatsApp"))
        self.assertEqual([p["key"] for p in out["presets"]], list(R.PRESETS))


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
