"""Morning brief v1 — one DM a day to each opted-in Admin / PM.

  * Scope: admin → every live job of their company; PM → assigned jobs.
    Another company's records are never read into a brief.
  * When: the time each person picked (Off / 7 / 8 / 9 AM New York),
    Mon–Fri, Saturday only if turned on; once a day (ledger); STOP stops it.
  * What: deterministic lines from stored records with their exact number,
    date and status; inspections only from a real stored date (none exists,
    so none); at most 7 items; "No action needed today" when nothing.
  * Headcount per job: workers once each, grouped by company, top 5.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_brief  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, CO_B, CP_PHONE, PM_PHONE, _Ctx,
)
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    PROJ_B, THOMAS, WALWORTH, _db, _optin,
)

THU_7 = datetime(2026, 10, 8, 11, 5, tzinfo=timezone.utc)     # Thu 7:05 AM ET
THU_8 = datetime(2026, 10, 8, 12, 5, tzinfo=timezone.utc)     # Thu 8:05 AM ET
THU_NOON = datetime(2026, 10, 8, 16, 5, tzinfo=timezone.utc)  # Thu 12:05 PM ET
SAT_7 = datetime(2026, 10, 10, 11, 5, tzinfo=timezone.utc)
SUN_7 = datetime(2026, 10, 11, 11, 5, tzinfo=timezone.utc)
YESTERDAY = THU_7 - timedelta(hours=20)
B_PHONE = "15550002001"


def _run(coro):
    return asyncio.run(coro)


def _violation(pid, num, issued="2026-10-07", **kw):
    row = {"_id": f"v_{num}", "project_id": pid, "record_type": "violation",
           "raw_dob_id": f"viol:{num}", "violation_number": num,
           "violation_date": issued, "resolution_state": "open",
           "current_status": "ACTIVE", "previous_status": None,
           "detected_at": YESTERDAY, "is_seed_transition": False}
    row.update(kw)
    return row


def _permit(pid, job, expires, work="General Construction", **kw):
    row = {"_id": f"p_{job}", "project_id": pid, "record_type": "permit",
           "raw_dob_id": f"permit:{job}", "job_number": job, "work_type": work,
           "expiration_date": expires, "permit_status": "ISSUED",
           "current_status": "ISSUED", "previous_status": None,
           "detected_at": THU_7 - timedelta(days=200)}
    row.update(kw)
    return row


def _checkin(pid, worker, company, co=CO_A, minutes=0):
    return {"_id": f"c_{pid}_{worker}_{minutes}", "project_id": pid,
            "company_id": co, "worker_id": worker, "worker_company": company,
            "check_in_time": THU_7 - timedelta(hours=1) + timedelta(minutes=minutes),
            "status": "checked_in"}


def _world():
    db = _db()
    db.dob_logs.rows.extend([
        _violation(WALWORTH, "35123456"),
        _permit(THOMAS, "B01141294", "2026-10-14"),
        _violation(PROJ_B, "99999999"),            # company B: never in A's brief
    ])
    db.checkins.rows.extend(
        [_checkin(THOMAS, f"w{i}", "ABC Concrete") for i in range(5)]
        + [_checkin(THOMAS, f"g{i}", "GC") for i in range(3)]
        + [_checkin(PROJ_B, "wb", "B Crew", co=CO_B)])
    return db


def _sends(c):
    return [p for p in c.wire.calls if "message" in p]


def _tick(c, now):
    return _run(server._morning_brief_tick(now=now))


# ══════════════════════════════════════════════════════════════════════════
# Pure parts
# ══════════════════════════════════════════════════════════════════════════

class WhenItGoes(unittest.TestCase):

    def test_times(self):
        self.assertTrue(wa_brief.is_due(THU_7, "07:00", False))
        self.assertFalse(wa_brief.is_due(THU_7, "08:00", False))
        self.assertTrue(wa_brief.is_due(THU_8, "08:00", False))
        self.assertFalse(wa_brief.is_due(THU_7, "off", False))
        self.assertFalse(wa_brief.is_due(THU_7, "06:00", False))
        self.assertFalse(wa_brief.is_due(THU_NOON, "07:00", False),
                         "a missed brief is not sent at noon")

    def test_days(self):
        self.assertFalse(wa_brief.is_due(SAT_7, "07:00", False))
        self.assertTrue(wa_brief.is_due(SAT_7, "07:00", True))
        self.assertFalse(wa_brief.is_due(SUN_7, "07:00", True))

    def test_defaults(self):
        self.assertEqual(wa_brief.clean_settings(None),
                         {"brief_time": "07:00", "brief_saturday": False})
        self.assertEqual(wa_brief.clean_settings({"brief_time": "10:00",
                                                  "brief_saturday": "yes"}),
                         {"brief_time": "07:00", "brief_saturday": False})


class Headcount(unittest.TestCase):

    def test_grouped_sorted_each_worker_once(self):
        cis = ([_checkin(THOMAS, f"a{i}", "ABC Concrete") for i in range(6)]
               + [_checkin(THOMAS, f"x{i}", "XYZ Plumbing") for i in range(4)]
               + [_checkin(THOMAS, f"g{i}", "GC") for i in range(2)]
               + [_checkin(THOMAS, "a0", "ABC Concrete", minutes=30)])  # back again
        self.assertEqual(wa_brief.headcount_line(cis),
                         "On site so far: 12 — ABC Concrete 6, XYZ Plumbing 4, GC 2")

    def test_nobody(self):
        self.assertEqual(wa_brief.headcount_line([]), "No check-ins yet.")

    def test_top_five_then_more(self):
        cis = []
        for n, co in enumerate(["A", "B", "C", "D", "E", "F", "G"]):
            cis += [_checkin(THOMAS, f"{co}{i}", co) for i in range(7 - n)]
        line = wa_brief.headcount_line(cis)
        self.assertTrue(line.endswith("A 7, B 6, C 5, D 4, E 3, +2 more"), line)

    def test_no_company_is_said(self):
        line = wa_brief.headcount_line([{"worker_id": "w", "check_in_time": "x"}])
        self.assertEqual(line, "On site so far: 1 — No company 1")


class TheItems(unittest.TestCase):

    def _items(self, rows, since=YESTERDAY - timedelta(hours=1), now=THU_7):
        return [i["text"] for i in wa_brief.job_items(rows, since, now)]

    def test_new_violation_with_exact_values(self):
        self.assertEqual(self._items([_violation(THOMAS, "35123456")]),
                         ["🔴 New violation 35123456, issued Oct 7, open. DOB."])

    def test_new_complaint_and_swo(self):
        rows = [
            {"raw_dob_id": "c:1", "record_type": "complaint", "complaint_number": "1234567",
             "complaint_date": "2026-10-06T00:00:00.000", "complaint_status": "ACTIVE",
             "detected_at": YESTERDAY, "previous_status": None},
            {"raw_dob_id": "s:1", "record_type": "swo", "stop_work_order_number": "SWO-77",
             "violation_date": "10/07/2026", "status": "ACTIVE",
             "detected_at": YESTERDAY, "previous_status": None},
        ]
        self.assertEqual(self._items(rows), [
            "🔴 New stop-work order SWO-77, issued Oct 7, ACTIVE. DOB.",
            "🔴 New complaint 1234567, filed Oct 6, ACTIVE. DOB.",
        ])

    def test_not_new_old_closed_seed_or_unsure(self):
        rows = [
            _violation(THOMAS, "1", detected_at=YESTERDAY - timedelta(days=3)),  # before last brief
            _violation(THOMAS, "2", issued="2019-01-05"),        # first scan of history
            _violation(THOMAS, "3", resolution_state="resolved"),
            _violation(THOMAS, "4", is_seed_transition=True),
            _violation(THOMAS, "5", issued=None),                # no date: omit
            _violation(THOMAS, "", raw_dob_id="viol:x"),         # no number: omit
        ]
        self.assertEqual(self._items(rows), [])

    def test_permits(self):
        rows = [
            _permit(THOMAS, "B01141294", "2026-10-14"),
            _permit(THOMAS, "B2", "2026-10-08", work="Plumbing"),
            _permit(THOMAS, "B3", "2026-10-01"),
            _permit(THOMAS, "B4", "2026-12-01"),                # far off
            _permit(THOMAS, "B5", "2025-01-01"),                # long expired
            _permit(THOMAS, "B6", "2026-10-10", permit_status="REVOKED"),
            _permit(THOMAS, "B7", None),                        # no date: omit
        ]
        self.assertEqual(self._items(rows), [
            "🟠 Permit B3 (General Construction) expired Oct 1 (7 days ago). DOB.",
            "🟠 Permit B2 (Plumbing) expires Oct 8 (today). DOB.",
            "🟠 Permit B01141294 (General Construction) expires Oct 14 (6 days). DOB.",
        ])

    def test_status_change_needing_action(self):
        old = {"raw_dob_id": "j:1", "record_type": "job_status", "job_number": "B777",
               "current_status": "APPROVED", "previous_status": None,
               "detected_at": THU_7 - timedelta(days=30)}
        new = {**old, "current_status": "OBJECTIONS", "previous_status": "APPROVED",
               "status_changed_at": YESTERDAY, "detected_at": YESTERDAY,
               "severity": "Action"}
        quiet = {**new, "raw_dob_id": "j:2", "job_number": "B778", "severity": "Info"}
        self.assertEqual(self._items([old, new, {**old, "raw_dob_id": "j:2"}, quiet]),
                         ["🟡 Job B777 changed APPROVED → OBJECTIONS on Oct 7. DOB."])

    def test_regulatory_before_permits(self):
        rows = [_permit(THOMAS, "B1", "2026-10-09"), _violation(THOMAS, "35")]
        self.assertTrue(self._items(rows)[0].startswith("🔴"))


class TheMessage(unittest.TestCase):

    def test_the_example(self):
        jobs = [
            {"label": "588 Thomas S Boyland St",
             "items": wa_brief.job_items([_permit(THOMAS, "B01141294", "2026-10-14")],
                                         YESTERDAY, THU_7),
             "headcount": "On site so far: 8 — ABC Concrete 5, GC 3"},
            {"label": "8 Walworth St",
             "items": wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                         YESTERDAY - timedelta(hours=1), THU_7),
             "headcount": "No check-ins yet."},
        ]
        self.assertEqual(wa_brief.compose(THU_7, jobs), "\n".join([
            "Morning — Thu Oct 8",
            "",
            "8 Walworth St",
            "🔴 New violation 35123456, issued Oct 7, open. DOB.",
            "No check-ins yet.",
            "",
            "588 Thomas S Boyland St",
            "🟠 Permit B01141294 (General Construction) expires Oct 14 (6 days). DOB.",
            "On site so far: 8 — ABC Concrete 5, GC 3",
        ]))

    def test_nothing_actionable(self):
        text = wa_brief.compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [],
             "headcount": "On site so far: 3 — GC 3"},
            {"label": "8 Walworth St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(text, "\n".join([
            "Good morning. No action needed today.", "",
            "588 Thomas S Boyland St", "On site so far: 3 — GC 3", "",
            "No check-ins yet: 8 Walworth St."]))

    def test_quiet_jobs_collapse_into_one_line(self):
        viol = wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                  YESTERDAY - timedelta(hours=1), THU_7)
        text = wa_brief.compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [],
             "headcount": "On site so far: 3 — GC 3"},
            {"label": "8 Walworth St", "items": viol, "headcount": "No check-ins yet."},
            {"label": "8 Prescott St", "items": [], "headcount": "No check-ins yet."},
            {"label": "12 Pacific St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(text, "\n".join([
            "Morning — Thu Oct 8", "",
            "8 Walworth St",                         # an item: its own block
            "🔴 New violation 35123456, issued Oct 7, open. DOB.",
            "No check-ins yet.", "",
            "588 Thomas S Boyland St", "On site so far: 3 — GC 3", "",
            "No check-ins yet: 8 Prescott St, 12 Pacific St."]))

    def test_all_quiet(self):
        text = wa_brief.compose(THU_7, [
            {"label": "8 Walworth St", "items": [], "headcount": "No check-ins yet."},
            {"label": "8 Prescott St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(text, "Good morning. No action needed today.\n\n"
                               "No check-ins yet: 8 Walworth St, 8 Prescott St.")

    def test_at_most_seven_items(self):
        rows = [_permit(THOMAS, f"B{i}", f"2026-10-{10 + i}") for i in range(9)]
        text = wa_brief.compose(THU_7, [{
            "label": "588 Thomas S Boyland St",
            "items": wa_brief.job_items(rows, YESTERDAY, THU_7),
            "headcount": "No check-ins yet."}])
        self.assertEqual(text.count("🟠"), 7)
        self.assertIn("B0 ", text)                  # the soonest kept
        self.assertNotIn("B8 ", text)
        self.assertTrue(text.endswith("+2 more in the Levelog app."))
        self.assertNotIn("Here is", text)


# ══════════════════════════════════════════════════════════════════════════
# The job
# ══════════════════════════════════════════════════════════════════════════

class WhoGetsWhat(unittest.TestCase):

    def test_admin_gets_every_live_company_job(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
        sends = _sends(c)
        self.assertEqual(len(sends), 1)
        text = sends[0]["message"]
        self.assertEqual(sends[0]["chatId"], f"{ADMIN_PHONE}@c.us")
        self.assertIn("588 Thomas S Boyland St", text)
        self.assertIn("8 Walworth St", text)
        self.assertIn("🔴 New violation 35123456, issued Oct 7, open. DOB.", text)
        self.assertIn("🟠 Permit B01141294 (General Construction) expires Oct 14 (6 days). DOB.", text)
        self.assertIn("On site so far: 8 — ABC Concrete 5, GC 3", text)
        self.assertNotIn("1 Gone St", text)          # deleted job
        self.assertNotIn("99999999", text)           # company B
        self.assertNotIn("Bedford", text)
        self.assertNotIn("B Crew", text)

    def test_pm_gets_assigned_jobs_only(self):
        db = _world()
        _optin(db, "u_pm", PM_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
        text = _sends(c)[0]["message"]
        self.assertIn("588 Thomas S Boyland St", text)
        self.assertNotIn("Walworth", text)
        self.assertNotIn("35123456", text)

    def test_another_company_sees_only_its_own(self):
        db = _world()
        db[server.WA_OPTINS].rows.append({
            "_id": "o_b", "phone": B_PHONE, "user_id": "u_b", "company_id": CO_B,
            "status": "active", "chat_id": f"{B_PHONE}@c.us", "chat_digits": B_PHONE})
        with _Ctx(db) as c:
            _tick(c, THU_7)
        text = _sends(c)[0]["message"]
        self.assertIn("99 Bedford Ave", text)
        self.assertIn("99999999", text)
        self.assertNotIn("Thomas", text)
        self.assertNotIn("35123456", text)
        self.assertNotIn("ABC Concrete", text)

    def test_cp_never_gets_one(self):
        db = _world()
        _optin(db, "u_cp", CP_PHONE)
        with _Ctx(db) as c:
            report = _tick(c, THU_7)
        self.assertEqual(_sends(c), [])
        self.assertEqual(report["skipped"], 1)

    def test_stop_means_nothing(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        db[server.WA_OPTINS].rows[-1]["status"] = "stopped"
        with _Ctx(db) as c:
            _tick(c, THU_7)
        self.assertEqual(_sends(c), [])

    def test_nothing_actionable_still_gives_headcount(self):
        db = _db()
        db.checkins.rows.append(_checkin(THOMAS, "w1", "ABC Concrete"))
        _optin(db, "u_pm", PM_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
        self.assertEqual(_sends(c)[0]["message"], "\n".join([
            "Good morning. No action needed today.", "",
            "588 Thomas S Boyland St", "On site so far: 1 — ABC Concrete 1"]))


class TimeAndOnce(unittest.TestCase):

    def _set(self, db, uid, **kw):
        db.notification_preferences.rows.append(
            {"_id": f"np_{uid}", "user_id": uid, "project_id": None,
             "whatsapp": kw})

    def test_once_a_day(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
            r = _tick(c, THU_7 + timedelta(minutes=10))
        self.assertEqual(len(_sends(c)), 1)
        self.assertEqual(r["already"], 1)

    def test_picked_time(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_time="08:00")
        with _Ctx(db) as c:
            _tick(c, THU_7)
            self.assertEqual(_sends(c), [])
            _tick(c, THU_8)
        self.assertEqual(len(_sends(c)), 1)

    def test_off(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_time="off")
        with _Ctx(db) as c:
            _tick(c, THU_7)
            _tick(c, THU_8)
        self.assertEqual(_sends(c), [])

    def test_saturday_toggle(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, SAT_7)
            self.assertEqual(_sends(c), [])
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_saturday=True)
        with _Ctx(db) as c:
            _tick(c, SAT_7)
            _tick(c, SUN_7)
        self.assertEqual(len(_sends(c)), 1)

    def test_new_means_since_the_last_brief(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
            fri = THU_7 + timedelta(days=1)
            _tick(c, fri)
        texts = [p["message"] for p in _sends(c)]
        self.assertEqual(len(texts), 2)
        self.assertIn("35123456", texts[0])
        self.assertNotIn("35123456", texts[1])     # not new any more
        self.assertIn("B01141294", texts[1])       # still expiring


class TheSettings(unittest.TestCase):

    def test_put_and_read_back(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        admin = dict(next(u for u in db.users.rows if u["_id"] == "u_admin"),
                     id="u_admin")
        with _Ctx(db):
            out = _run(server.put_whatsapp_brief(
                {"brief_time": "09:00", "brief_saturday": True}, current_user=admin))
            self.assertEqual(out, {"brief_time": "09:00", "brief_saturday": True})
            out = _run(server.put_whatsapp_brief({"brief_time": "off"}, current_user=admin))
            self.assertEqual(out, {"brief_time": "off", "brief_saturday": True})
            for bad in ({"brief_time": "10:00"}, {"brief_saturday": "yes"},
                        {"other": 1}, {}):
                with self.assertRaises(HTTPException) as e:
                    _run(server.put_whatsapp_brief(bad, current_user=admin))
                self.assertEqual(e.exception.status_code, 422)

    def test_not_for_cp(self):
        db = _world()
        cp = dict(next(u for u in db.users.rows if u["_id"] == "u_cp"), id="u_cp")
        with _Ctx(db):
            with self.assertRaises(HTTPException) as e:
                _run(server.put_whatsapp_brief({"brief_time": "08:00"}, current_user=cp))
        self.assertEqual(e.exception.status_code, 403)

    def test_me_shows_it_only_when_connected(self):
        db = _world()
        admin = dict(next(u for u in db.users.rows if u["_id"] == "u_admin"),
                     id="u_admin", account_status="approved")
        with _Ctx(db), patch.object(server, "_wa_bot_digits", lambda: "15559990000"):
            self.assertIsNone(_run(server.whatsapp_me(current_user=admin))["brief"])
            _optin(db, "u_admin", ADMIN_PHONE)
            self.assertEqual(_run(server.whatsapp_me(current_user=admin))["brief"],
                             {"brief_time": "07:00", "brief_saturday": False})


class Wiring(unittest.TestCase):

    def test_scheduled(self):
        src = Path(server.__file__).read_text()
        self.assertIn("id='whatsapp_morning_brief'", src)


if __name__ == "__main__":
    unittest.main()
