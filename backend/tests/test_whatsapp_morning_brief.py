"""Morning brief v1 — DMs once a day to each opted-in Admin / PM, one
message per job, then one for their reminders and quiet jobs.

  * Scope: admin → every live job of their company; PM → assigned jobs.
    Another company's records are never read into a brief.
  * When: the time each person picked (Off / 7 / 8 / 9 AM New York),
    Mon–Fri, Saturday only if turned on; once a day (ledger); STOP stops it.
  * What: deterministic lines from stored records with their exact number,
    date and status; inspections only from a real stored date (none exists,
    so none); at most 7 items per job; "No action needed today" when nothing.
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
    PROJ_B, THOMAS, WALWORTH, _db as _base_db, _optin,
)
from tests.test_whatsapp_gc_alerts import synced_state  # noqa: E402


def _db():
    """Every project's sources first synced long ago (lib/source_sync.py)."""
    db = _base_db()
    db[server.SOURCE_SYNC_STATE].rows.extend(
        synced_state(str(p["_id"]), (str(p["_id"]), p.get("company_id")))
        for p in db.projects.rows)
    return db

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


def _texts(c):
    return [p["message"] for p in _sends(c)]


def _compose(now, jobs, own=None):
    """The brief's messages, their texts only."""
    return [text for _part, text in wa_brief.compose_messages(now, jobs, own)]


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
        for day in (SAT_7, SUN_7):
            self.assertFalse(wa_brief.is_due(day, "07:00", False))
            self.assertTrue(wa_brief.is_due(day, "07:00", True))
        self.assertTrue(wa_brief.is_due(THU_7, "07:00", False))

    def test_defaults(self):
        off = {"brief_time": "07:00", "brief_weekend": False, "brief_saturday": False}
        self.assertEqual(wa_brief.clean_settings(None), off)
        self.assertEqual(wa_brief.clean_settings({"brief_time": "10:00",
                                                  "brief_weekend": "yes"}), off)

    def test_an_unmigrated_saturday_counts_as_weekend(self):
        self.assertTrue(wa_brief.clean_settings({"brief_saturday": True})["brief_weekend"])
        # Once brief_weekend is stored it alone decides.
        self.assertFalse(wa_brief.clean_settings(
            {"brief_saturday": True, "brief_weekend": False})["brief_weekend"])


class Headcount(unittest.TestCase):

    def test_grouped_sorted_each_worker_once(self):
        cis = ([_checkin(THOMAS, f"a{i}", "ABC Concrete") for i in range(6)]
               + [_checkin(THOMAS, f"x{i}", "XYZ Plumbing") for i in range(4)]
               + [_checkin(THOMAS, f"g{i}", "GC") for i in range(2)]
               + [_checkin(THOMAS, "a0", "ABC Concrete", minutes=30)])  # back again
        self.assertEqual(wa_brief.headcount_line(cis),
                         "👷 12 on site · ABC Concrete 6 · XYZ 4 · GC 2")

    def test_nobody(self):
        self.assertEqual(wa_brief.headcount_line([]), "No check-ins yet.")

    def test_top_five_then_more(self):
        cis = []
        for n, co in enumerate(["A", "B", "C", "D", "E", "F", "G"]):
            cis += [_checkin(THOMAS, f"{co}{i}", co) for i in range(7 - n)]
        line = wa_brief.headcount_line(cis)
        self.assertTrue(line.endswith("A 7 · B 6 · C 5 · D 4 · E 3 · +2 more"), line)

    def test_no_company_is_said(self):
        line = wa_brief.headcount_line([{"worker_id": "w", "check_in_time": "x"}])
        self.assertEqual(line, "👷 1 on site · No company 1")

    def test_company_names_short(self):
        for full, short in (("Quality Plumbing Corp.", "Quality"), ("Arkon Construction LLC", "Arkon"),
                            ("Power Direct", "Power Direct"), ("MQ Electrical", "MQ"),
                            ("Plumbing", "Plumbing"), ("ABC Concrete", "ABC Concrete")):
            with self.subTest(full):
                self.assertEqual(wa_brief.short_company(full), short)


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

    def test_swo_from_a_violation_dataset_uses_its_violation_number(self):
        row = {"raw_dob_id": "s:2", "record_type": "swo", "violation_number": "V-555",
               "violation_date": "2026-10-07", "resolution_state": "open",
               "detected_at": YESTERDAY, "previous_status": None}
        self.assertEqual(self._items([row]),
                         ["🔴 New stop-work order V-555, issued Oct 7, open. DOB."])

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
             "headcount": "👷 8 on site · ABC Concrete 5 · GC 3"},
            {"label": "8 Walworth St",
             "items": wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                         YESTERDAY - timedelta(hours=1), THU_7),
             "headcount": "No check-ins yet."},
        ]
        self.assertEqual(_compose(THU_7, jobs), [
            "\n".join([
                "*Thu Oct 8* · *8 Walworth St*",
                "",
                "🏛 *DOB / DOT*",
                "🔴 New violation 35123456, issued Oct 7, open. DOB.",
            ]),
            "\n".join([
                "*Thu Oct 8* · *588 Thomas S Boyland St*",
                "",
                "🏛 *DOB / DOT*",
                "🟠 Permit B01141294 (General Construction) expires Oct 14 (6 days). DOB.",
                "",
                "👷 8 on site · ABC Concrete 5 · GC 3",
            ]),
        ])

    def test_each_message_is_one_job_keyed_by_its_id(self):
        viol = wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                  YESTERDAY - timedelta(hours=1), THU_7)
        msgs = wa_brief.compose_messages(THU_7, [
            {"id": THOMAS, "label": "588 Thomas S Boyland St", "items": [],
             "headcount": "👷 3 on site · GC 3"},
            {"id": WALWORTH, "label": "8 Walworth St", "items": viol,
             "headcount": "No check-ins yet."}])
        self.assertEqual([part for part, _t in msgs], [WALWORTH, THOMAS])
        self.assertNotIn("Thomas", msgs[0][1])
        self.assertNotIn("Walworth", msgs[1][1])
        self.assertNotIn("35123456", msgs[1][1])

    def test_nothing_actionable(self):
        msgs = _compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [],
             "headcount": "👷 3 on site · GC 3"},
            {"label": "8 Walworth St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(msgs, [
            "*Thu Oct 8* · *588 Thomas S Boyland St*\n\n👷 3 on site · GC 3",
            "*Thu Oct 8*\nNo action needed today.\n\nNo check-ins yet: 8 Walworth St."])

    def test_quiet_jobs_collapse_into_one_line(self):
        viol = wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                  YESTERDAY - timedelta(hours=1), THU_7)
        msgs = _compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [],
             "headcount": "👷 3 on site · GC 3"},
            {"label": "8 Walworth St", "items": viol, "headcount": "No check-ins yet."},
            {"label": "8 Prescott St", "items": [], "headcount": "No check-ins yet."},
            {"label": "12 Pacific St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(msgs, [
            "\n".join(["*Thu Oct 8* · *8 Walworth St*", "",    # an item: its own message
                       "🏛 *DOB / DOT*",
                       "🔴 New violation 35123456, issued Oct 7, open. DOB."]),
            "*Thu Oct 8* · *588 Thomas S Boyland St*\n\n👷 3 on site · GC 3",
            # the quiet ones: one line, in the last message
            "*Thu Oct 8*\n\nNo check-ins yet: 8 Prescott St, 12 Pacific St."])

    def test_jobs_without_check_in_setup(self):
        viol = wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                  YESTERDAY - timedelta(hours=1), THU_7)
        msgs = _compose(THU_7, [
            {"label": "8 Walworth St", "items": viol,
             "headcount": "No check-ins yet.", "uses_checkins": False},
            {"label": "12 Pacific St", "items": [],
             "headcount": "No check-ins yet.", "uses_checkins": False},
            {"label": "8 Prescott St", "items": [],
             "headcount": "No check-ins yet.", "uses_checkins": True}])
        self.assertEqual(msgs, [
            "\n".join(["*Thu Oct 8* · *8 Walworth St*", "",    # items, no headcount line
                       "🏛 *DOB / DOT*",
                       "🔴 New violation 35123456, issued Oct 7, open. DOB."]),
            "*Thu Oct 8*\n\nNo check-ins yet: 8 Prescott St."])  # 12 Pacific St left out

    def test_every_job_left_out_is_one_line(self):
        self.assertEqual(wa_brief.compose_messages(THU_7, [
            {"label": "12 Pacific St", "items": [],
             "headcount": "No check-ins yet.", "uses_checkins": False}]),
            [(wa_brief.REST, "*Thu Oct 8*\nNo action needed today.")])

    def test_address_casing_is_kept(self):
        msgs = _compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [],
             "headcount": "👷 1 on site · GC 1", "uses_checkins": True}])
        self.assertIn("588 Thomas S Boyland St", msgs[0])

    def test_all_quiet(self):
        msgs = _compose(THU_7, [
            {"label": "8 Walworth St", "items": [], "headcount": "No check-ins yet."},
            {"label": "8 Prescott St", "items": [], "headcount": "No check-ins yet."}])
        self.assertEqual(msgs, ["*Thu Oct 8*\nNo action needed today.\n\n"
                                "No check-ins yet: 8 Walworth St, 8 Prescott St."])

    def test_at_most_seven_items(self):
        rows = [_permit(THOMAS, f"B{i}", f"2026-10-{10 + i}") for i in range(9)]
        msgs = _compose(THU_7, [{
            "label": "588 Thomas S Boyland St",
            "items": wa_brief.job_items(rows, YESTERDAY, THU_7),
            "headcount": "No check-ins yet."}])
        self.assertEqual(len(msgs), 1)
        text = msgs[0]
        self.assertEqual(text.count("🟠"), 7)
        self.assertIn("B0 ", text)                  # the soonest kept
        self.assertNotIn("B8 ", text)
        self.assertTrue(text.endswith("+2 more DOB / DOT in the Levelog app."))
        self.assertNotIn("Here is", text)

    def test_the_seven_are_per_job(self):
        thomas = [_permit(THOMAS, f"B{i}", f"2026-10-{10 + i}") for i in range(9)]
        walworth = [_permit(WALWORTH, f"W{i}", f"2026-10-{10 + i}") for i in range(3)]
        msgs = _compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": wa_brief.job_items(thomas, YESTERDAY, THU_7),
             "headcount": "No check-ins yet.", "uses_checkins": False},
            {"label": "8 Walworth St", "items": wa_brief.job_items(walworth, YESTERDAY, THU_7),
             "headcount": "No check-ins yet.", "uses_checkins": False}])
        self.assertEqual(len(msgs), 2)
        self.assertEqual((msgs[0].count("🟠"), msgs[1].count("🟠")), (7, 3))
        self.assertTrue(msgs[0].endswith("+2 more DOB / DOT in the Levelog app."))
        self.assertNotIn("more DOB / DOT", msgs[1])     # another job's cut is not its own

    def test_reminders_have_their_own_last_message(self):
        msgs = _compose(THU_7, [
            {"label": "588 Thomas S Boyland St", "items": [], "today": ["• 7am Concrete pour"],
             "headcount": "No check-ins yet.", "uses_checkins": True},
            {"label": "8 Walworth St", "items": [], "headcount": "No check-ins yet."}],
            {"today": ["• 9am Call the bank"], "later": ["• Fri Renew insurance"]})
        self.assertEqual(msgs, [
            "*Thu Oct 8* · *588 Thomas S Boyland St*\n\n📅 *Today*\n• 7am Concrete pour",
            "\n".join(["*Thu Oct 8*", "", "*Your reminders*", "📅 *Today*", "• 9am Call the bank",
                       "", "📆 *Later this week*", "• Fri Renew insurance",
                       "", "No check-ins yet: 8 Walworth St."])])

    def test_reminders_alone_are_something_to_do(self):
        self.assertEqual(_compose(THU_7, [], {"today": ["• 9am Call the bank"]}), [
            "*Thu Oct 8*\n\n*Your reminders*\n📅 *Today*\n• 9am Call the bank"])


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
        self.assertEqual(len(sends), 2)             # one message per job
        self.assertEqual({p["chatId"] for p in sends}, {f"{ADMIN_PHONE}@c.us"})
        walworth, thomas = (p["message"] for p in sends)
        self.assertTrue(walworth.startswith("*Thu Oct 8* · *8 Walworth St*"), walworth)
        self.assertIn("🔴 New violation 35123456, issued Oct 7, open. DOB.", walworth)
        self.assertNotIn("Thomas", walworth)
        self.assertTrue(thomas.startswith("*Thu Oct 8* · *588 Thomas S Boyland St*"), thomas)
        self.assertIn("🟠 Permit B01141294 (General Construction) expires Oct 14 (6 days). DOB.",
                      thomas)
        self.assertIn("👷 8 on site · ABC Concrete 5 · GC 3", thomas)
        self.assertNotIn("Walworth", thomas)
        self.assertNotIn("35123456", thomas)
        both = "\n".join((walworth, thomas))
        self.assertNotIn("1 Gone St", both)          # deleted job
        self.assertNotIn("violation 99999999", both)  # company B
        self.assertNotIn("99 Bedford Ave", both)
        self.assertNotIn("B Crew", both)

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
        self.assertEqual(_texts(c), [
            "*Thu Oct 8* · *588 Thomas S Boyland St*\n\n👷 1 on site · ABC Concrete 1",
            "*Thu Oct 8*\nNo action needed today."])


NOTHING = "*Thu Oct 8*\nNo action needed today."


class UsesCheckIns(unittest.TestCase):

    def _brief(self, db):
        _optin(db, "u_pm", PM_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
        return _sends(c)[0]["message"] if _sends(c) else None

    def test_no_setup_and_nothing_to_do_is_left_out(self):
        self.assertEqual(self._brief(_db()), NOTHING)

    def test_an_active_tag_means_it_uses_check_ins(self):
        db = _db()
        db.nfc_tags.rows.append({"_id": "t1", "project_id": THOMAS, "status": "active"})
        self.assertIn("No check-ins yet: 588 Thomas S Boyland St.", self._brief(db))

    def test_an_inactive_tag_does_not(self):
        db = _db()
        db.nfc_tags.rows.append({"_id": "t1", "project_id": THOMAS, "status": "inactive"})
        self.assertEqual(self._brief(db), NOTHING)

    def test_a_site_device_means_it_uses_check_ins(self):
        db = _db()
        db.site_devices.rows.append({"_id": "d1", "project_id": THOMAS, "is_active": True})
        self.assertIn("No check-ins yet: 588 Thomas S Boyland St.", self._brief(db))

    def test_a_check_in_in_the_last_14_days(self):
        db = _db()
        db.checkins.rows.append({**_checkin(THOMAS, "w1", "GC"),
                                 "check_in_time": THU_7 - timedelta(days=10)})
        self.assertIn("No check-ins yet: 588 Thomas S Boyland St.", self._brief(db))
        db = _db()
        db.checkins.rows.append({**_checkin(THOMAS, "w1", "GC"),
                                 "check_in_time": THU_7 - timedelta(days=20)})
        self.assertEqual(self._brief(db), NOTHING)

    def test_items_without_setup_have_no_headcount_line(self):
        db = _db()
        db.dob_logs.rows.append(_permit(THOMAS, "B01141294", "2026-10-14"))
        text = self._brief(db)
        self.assertIn("🟠 Permit B01141294", text)
        self.assertNotIn("check-ins", text.lower())
        self.assertNotIn("on site", text)


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
        self.assertEqual(len(_sends(c)), 2)         # its two jobs, once
        self.assertEqual(r["already"], 1)

    def test_picked_time(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_time="08:00")
        with _Ctx(db) as c:
            _tick(c, THU_7)
            self.assertEqual(_sends(c), [])
            _tick(c, THU_8)
        self.assertEqual(len(_sends(c)), 2)

    def test_off(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_time="off")
        with _Ctx(db) as c:
            _tick(c, THU_7)
            _tick(c, THU_8)
        self.assertEqual(_sends(c), [])

    def test_weekend_toggle(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, SAT_7)
            _tick(c, SUN_7)
            self.assertEqual(_sends(c), [])
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_weekend=True)
        with _Ctx(db) as c:
            _tick(c, SAT_7)
            _tick(c, SUN_7)
        # Sunday only: Saturday 7 AM is Shabbos (the company's "Shabbos /
        # Yom Tov off" is on by default) and the brief is skipped then.
        self.assertEqual(len(_sends(c)), 1)
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_weekend=True)
        db[server.WA_COMPANY_SETTINGS].rows.append({
            "_id": CO_A, "company_id": CO_A, "whatsapp_company": {"shabbos_off": False}})
        with _Ctx(db) as c:
            _tick(c, SAT_7)
            _tick(c, SUN_7)
        self.assertEqual(len(_sends(c)), 2)         # Saturday AND Sunday

    def test_saturday_on_is_migrated_to_weekend(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        self._set(db, "u_admin", brief_time="08:00", brief_saturday=True)
        db.notification_preferences.rows.append(
            {"_id": "np_off", "user_id": "u_pm", "project_id": None,
             "whatsapp": {"brief_saturday": False}})
        with _Ctx(db):
            _run(server.run_whatsapp_startup_migrations())
            _run(server.run_whatsapp_startup_migrations())     # idempotent
        # Person rows only (the chase-weekends migration may add a project row).
        rows = {r["_id"]: r["whatsapp"] for r in db.notification_preferences.rows
                if "whatsapp" in r}
        self.assertEqual(rows["np_u_admin"], {"brief_time": "08:00", "brief_weekend": True})
        self.assertEqual(rows["np_off"], {"brief_weekend": False})

    def test_new_means_since_the_last_brief(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, THU_7)
            n = len(_sends(c))
            fri = THU_7 + timedelta(days=1)
            _tick(c, fri)
        texts = _texts(c)
        thu, fri = "\n".join(texts[:n]), "\n".join(texts[n:])
        self.assertIn("35123456", thu)
        self.assertNotIn("35123456", fri)          # not new any more
        self.assertIn("B01141294", fri)            # still expiring


class TheSettings(unittest.TestCase):

    def test_put_and_read_back(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        admin = dict(next(u for u in db.users.rows if u["_id"] == "u_admin"),
                     id="u_admin")
        with _Ctx(db):
            out = _run(server.put_whatsapp_brief(
                {"brief_time": "09:00", "brief_weekend": True}, current_user=admin))
            on = {"brief_weekend": True, "brief_saturday": True, "upcoming_reminders": True}
            self.assertEqual(out, {"brief_time": "09:00", **on})
            out = _run(server.put_whatsapp_brief({"brief_time": "off"}, current_user=admin))
            self.assertEqual(out, {"brief_time": "off", **on})
            # An app version from before the weekend switch still works.
            out = _run(server.put_whatsapp_brief({"brief_saturday": False},
                                                 current_user=admin))
            self.assertFalse(out["brief_weekend"])
            stored = next(r for r in db.notification_preferences.rows
                          if r.get("user_id") == "u_admin")["whatsapp"]
            self.assertNotIn("brief_saturday", stored)
            # Upcoming's day-before DM rides on the same row.
            out = _run(server.put_whatsapp_brief({"upcoming_reminders": False},
                                                 current_user=admin))
            self.assertFalse(out["upcoming_reminders"])
            for bad in ({"brief_time": "10:00"}, {"brief_weekend": "yes"},
                        {"upcoming_reminders": "no"},
                        {"brief_weekend": True, "brief_saturday": False},
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
                             {"brief_time": "07:00", "brief_weekend": False,
                              "brief_saturday": False, "upcoming_reminders": True})


class Wiring(unittest.TestCase):

    def test_scheduled(self):
        src = Path(server.__file__).read_text()
        self.assertIn("id='whatsapp_morning_brief'", src)


if __name__ == "__main__":
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════
# Follow-ups: due today / overdue, open punch (live 588, Mon Oct 12 8:05:
# "No action needed today." while items were open)
# ══════════════════════════════════════════════════════════════════════════

MON_8 = datetime(2026, 10, 12, 12, 5, tzinfo=timezone.utc)    # Mon 8:05 AM ET
MIKE_JID = "17185550101@c.us"


def _att(_id, quote, due_at, owner=None, requester=None, sender="17185550101",
         type_="commitment", status="open", due_text=None, summary=None, **kw):
    row = {"_id": _id, "company_id": CO_A, "project_id": THOMAS, "type": type_,
           "status": status, "summary": f"SUMMARY {quote}" if summary is None else summary,
           "owner": owner or {"kind": "sender_map", "id": "m1", "name": "Mike Rivera",
                              "status": "resolved", "jid": MIKE_JID},
           "requester": requester,
           "due": {"due_text": due_text or "Sunday", "due_at": due_at},
           "evidence": {"quote": quote, "sender": sender}, "tags": []}
    row.update(kw)
    return row


def _punch_row(seq, name, status="open", days_ago=0):
    return {"_id": f"{THOMAS}:P-588-{seq}", "pid": f"P-588-{seq}", "seq": seq,
            "company_id": CO_A, "project_id": THOMAS, "status": status,
            "assignee": {"kind": "sender_map", "id": name, "name": name} if name else None,
            "assigned_at": MON_8 - timedelta(days=days_ago)}


class FollowUps(unittest.TestCase):

    ME = {"user_id": "u_admin", "digits": {ADMIN_PHONE[-10:]}}
    ADMIN_JID = f"{ADMIN_PHONE}@c.us"

    def test_you_and_waiting_from_the_stored_summary(self):
        items = [
            # asked by me (the requester), owned by Mike, a day late
            _att("a1", "Can you send the calcs by Sunday?", "2026-10-11", summary="Send calcs",
                 requester={"kind": "user", "id": "u_admin", "name": "Ana",
                            "status": "resolved", "jid": self.ADMIN_JID},
                 type_="request", sender=ADMIN_PHONE),
            # owned by me, due today
            _att("a2", "I'll call the inspector Monday", "2026-10-12", due_text="Monday",
                 summary="call the inspector.",
                 owner={"kind": "user", "id": "u_admin", "name": "Ana Admin",
                        "status": "resolved", "jid": self.ADMIN_JID}),
            # owned by me, three days late; and one with no summary stored
            _att("a7", "I'll send the basement photos Friday", "2026-10-09",
                 summary="Send basement photos",
                 owner={"kind": "user", "id": "u_admin", "status": "resolved"}),
            _att("a8", "I will get you the revised drawings asap", "2026-10-12", due_text="ASAP",
                 summary="", owner={"kind": "user", "id": "u_admin", "status": "resolved"}),
            # neither mine nor asked by me
            _att("a3", "I'll fix the railing Friday", "2026-10-09"),
            # mine, but not due yet / done / a punch item
            _att("a4", "tomorrow's thing", "2026-10-13",
                 owner={"kind": "user", "id": "u_admin", "name": "Ana Admin", "status": "resolved"}),
            _att("a5", "done thing", "2026-10-10", status="done",
                 owner={"kind": "user", "id": "u_admin", "name": "Ana Admin", "status": "resolved"}),
            _att("a6", "P-588-1 tile", "2026-10-10", tags=["punch"],
                 owner={"kind": "user", "id": "u_admin", "name": "Ana Admin", "status": "resolved"}),
        ]
        you, waiting = wa_brief.task_sections(items, date(2026, 10, 12), self.ME)
        self.assertEqual(you, [
            "• Send basement photos — ⚠️ 3 days late",
            "• Call the inspector · today",
            "• “I will get you the revised drawings asap” · ASAP",
        ])
        self.assertEqual(wa_brief.waiting_lines(waiting, {}, date(2026, 10, 12)),
                         ["• Mike: Send calcs — ⚠️ 1 day late"])

    def test_punch_per_person_and_ready_to_check(self):
        rows = [_punch_row(1, "Yeyzmar B Bate", days_ago=2), _punch_row(2, "Yeyzmar B Bate"),
                _punch_row(3, "Chris Lopez"), _punch_row(4, None, days_ago=1),
                _punch_row(5, "Chris Lopez", status="ready_to_check"),
                _punch_row(6, "Chris Lopez", status="closed")]
        by, check = wa_brief.punch_sections(rows, date(2026, 10, 12))
        self.assertEqual(wa_brief.waiting_lines([], by, date(2026, 10, 12)), [
            "• Yeyzmar: 2 punch items (oldest 2 days)",
            "• Unassigned: 1 punch item (1 day)",
            "• Chris: 1 punch item (today)"])
        self.assertEqual(check, ["• 1 punch item ready to check"])

    def test_two_people_with_one_first_name_keep_their_full_names(self):
        rows = [_punch_row(1, "Chris Lopez"), _punch_row(2, "Chris Weiss")]
        by, _ = wa_brief.punch_sections(rows, date(2026, 10, 12))
        self.assertEqual(wa_brief.waiting_lines([], by, date(2026, 10, 12)), [
            "• Chris Lopez: 1 punch item (today)", "• Chris Weiss: 1 punch item (today)"])

    def test_no_action_needed_only_when_all_empty(self):
        job = {"label": "588 Thomas S Boyland St", "items": [], "you": [],
               "waiting": ["• Chris: 1 punch item (today)"],
               "headcount": NO_CI, "uses_checkins": False}
        self.assertEqual(_compose(MON_8, [job]), ["\n".join([
            "*Mon Oct 12* · *588 Thomas S Boyland St*", "",
            "⏳ *Waiting on others*", "• Chris: 1 punch item (today)"])])
        job["waiting"] = []
        self.assertEqual(_compose(MON_8, [job]), ["*Mon Oct 12*\nNo action needed today."])

    def test_monday_8_05_on_588(self):
        db = _db()
        db.attention_items.rows.extend([
            _att("a1", "I'll send the calcs Sunday", "2026-10-11", summary="Send calcs",
                 requester={"kind": "user", "id": "u_admin", "name": "Ana",
                            "status": "resolved", "jid": self.ADMIN_JID}),
            _att("ab", "other company's", "2026-10-11", company_id=CO_B,
                 requester={"kind": "user", "id": "u_admin", "status": "resolved"}),
        ])
        db[server.punch.COLLECTION].rows.extend(
            [_punch_row(1, "Yeyzmar B Bate", days_ago=1), _punch_row(2, "Yeyzmar B Bate"),
             _punch_row(3, "Chris Lopez")])
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, MON_8)
        brief = "\n\n".join(_texts(c))
        self.assertNotIn("No action needed", brief)
        self.assertIn("\n".join([
            "*Mon Oct 12* · *588 Thomas S Boyland St*",
            "",
            "⏳ *Waiting on others*",
            "• Mike: Send calcs — ⚠️ 1 day late",
            "• Yeyzmar: 2 punch items (oldest 1 day)",
            "• Chris: 1 punch item (today)"]), brief)
        self.assertNotIn("other company", brief)
        self.assertNotIn("I'll send the calcs Sunday", brief)     # the summary, not the quote


NO_CI = wa_brief.NO_CHECKINS


# ── The target layout: scannable in five seconds ─────────────────────────────

TUE_8 = datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)    # Tue 8:05 AM ET
TUE = date(2026, 10, 13)
ME_ADMIN = {"user_id": "u_admin", "digits": {ADMIN_PHONE[-10:]}}
_MINE = {"kind": "user", "id": "u_admin", "name": "Ana Admin", "status": "resolved"}


def _ci(n, company):
    return [{"_id": f"{company}{i}", "worker_id": f"{company}{i}", "worker_company": company,
             "check_in_time": "2026-10-13T11:00:00Z"} for i in range(n)]


def _target_job(label="588 Thomas S Boyland"):
    you, waiting = wa_brief.task_sections([
        _att("c", "Can you get me the calcs by Sunday??", "2026-10-11", summary="Send calcs.",
             owner=_MINE),
        _att("p", "I'll send the basement photos tomorrow", "2026-10-12",
             summary="send basement photos", owner=_MINE),
    ], TUE, ME_ADMIN)
    by, check = wa_brief.punch_sections(
        [_punch_row(i, "Chris Lopez", days_ago=1 if i == 1 else 0) for i in range(1, 5)]   # from Mon
        + [_punch_row(9, "Chris Lopez", status="ready_to_check")], TUE)
    today, later = wa_brief.event_sections([
        {"date": "2026-10-15", "time": "09:00", "title": "Electrical inspection"},
        {"date": "2026-10-13", "time": "07:00", "title": "Concrete pour"},
    ], TUE)
    return {"label": label, "items": [], "you": you,
            "waiting": wa_brief.waiting_lines(waiting, by, TUE), "check": check,
            "headcount": wa_brief.headcount_line(
                _ci(11, "Arkon Construction LLC") + _ci(6, "Quality Plumbing Corp.")
                + _ci(5, "Power Direct") + _ci(2, "MQ Electrical")),
            "uses_checkins": True, "today": today, "later": later}


TARGET_BLOCK = [
    "*588 Thomas S Boyland*",
    "📅 *Today*",
    "• 7am Concrete pour",
    "",
    "✅ *You*",
    "• Send calcs — ⚠️ 2 days late",
    "• Send basement photos — ⚠️ 1 day late",
    "",
    "⏳ *Waiting on others*",
    "• Chris: 4 punch items (oldest 2 days)",
    "",
    "🔍 *Check*",
    "• 1 punch item ready to check",
    "",
    "👷 24 on site · Arkon 11 · Quality 6 · Power Direct 5 · MQ 2",
    "",
    "📆 *Later this week*",
    "• Thu 9am Electrical inspection",
]


class TargetLayout(unittest.TestCase):

    def test_one_job_is_the_target_exactly(self):
        msgs = _compose(TUE_8, [_target_job()])
        self.assertEqual(len(msgs), 1)
        text = msgs[0]
        self.assertEqual(text, "\n".join(["*Tue Oct 13* · *588 Thomas S Boyland*", ""]
                                         + TARGET_BLOCK[1:]))
        self.assertLess(len(text.split("\n")), 25)
        self.assertNotIn("calcs by Sunday", text)          # the summary, never the quote

    def test_three_jobs_one_message_each_in_order(self):
        jobs = [_target_job("588 Thomas S Boyland"), _target_job("8 Walworth St"),
                _target_job("12 Pacific St")]
        want = ["\n".join([f"*Tue Oct 13* · *{label}*", ""] + TARGET_BLOCK[1:])
                for label in ("588 Thomas S Boyland", "8 Walworth St", "12 Pacific St")]
        self.assertEqual(_compose(TUE_8, jobs), want)

    def test_zero_jobs_no_brief(self):
        db = _db()
        db.projects.rows.clear()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, TUE_8)
        self.assertEqual(_sends(c), [])
        self.assertEqual(_compose(TUE_8, []), ["*Tue Oct 13*\nNo action needed today."])

    def test_empty_sections_are_left_out(self):
        job = _target_job()
        for k in ("today", "waiting", "check", "later"):
            job[k] = []
        job["headcount"] = wa_brief.NO_CHECKINS
        self.assertEqual(_compose(TUE_8, [job]), ["\n".join([
            "*Tue Oct 13* · *588 Thomas S Boyland*", "", "✅ *You*",
            "• Send calcs — ⚠️ 2 days late", "• Send basement photos — ⚠️ 1 day late"])])

    def test_due_today_and_asap(self):
        self.assertEqual(wa_brief.lateness(TUE, TUE, False), " · today")
        self.assertEqual(wa_brief.lateness(TUE, TUE, True), " · ASAP")
        self.assertEqual(wa_brief.lateness(date(2026, 10, 12), TUE, False), " — ⚠️ 1 day late")
        self.assertEqual(wa_brief.lateness(date(2026, 10, 11), TUE, False), " — ⚠️ 2 days late")

    def test_todays_event_is_today_not_later(self):
        today, later = wa_brief.event_sections(
            [{"date": "2026-10-13", "time": "14:30", "title": "Con Ed meter set"},
             {"date": "2026-10-12", "time": "09:00", "title": "yesterday's"},
             {"date": "2026-10-14", "time": None, "title": "Elevator walkthrough"}], TUE)
        self.assertEqual(today, ["• 2:30pm Con Ed meter set"])
        self.assertEqual(later, ["• Wed Elevator walkthrough"])

    def test_a_long_summary_is_clipped_to_one_line(self):
        long = "Send the full set of revised structural calculations for the cellar slab and footings"
        you, _ = wa_brief.task_sections([_att("x", "q", "2026-10-13", summary=long, owner=_MINE)],
                                        TUE, ME_ADMIN)
        self.assertEqual(len(you), 1)
        self.assertLessEqual(len(you[0]), len("• ") + wa_brief.TASK_CHARS + len(" · today"))
        self.assertTrue(you[0].endswith("… · today"), you[0])

    def test_end_to_end_today_event_lands_under_the_job(self):
        db = _db()
        db[server.UPCOMING].rows.append(
            {"_id": "e1", "company_id": CO_A, "project_id": THOMAS, "source": "chat",
             "kind": "event", "title": "Concrete pour", "date": "2026-10-13", "time": "07:00",
             "status": "open", "history": []})
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, TUE_8)
        text = _sends(c)[0]["message"]
        self.assertTrue(text.startswith("*Tue Oct 13*"), text)
        self.assertIn("📅 *Today*\n• 7am Concrete pour", text)
        self.assertNotIn("Later this week", text)


class Budgets(unittest.TestCase):

    def test_later_this_week_is_capped_per_job(self):
        events = [{"project_id": "p0", "date": f"2026-10-{14 + i % 4}", "time": f"0{i}:00",
                   "title": f"J0 event {i}"} for i in range(8)]
        events += [{"project_id": "p1", "date": "2026-10-18", "time": "09:00",
                    "title": f"J1 event {i}"} for i in range(3)]
        events += [{"project_id": None, "date": "2026-10-16", "time": None, "title": f"call {i}"}
                   for i in range(6)]
        events += [{"project_id": "p1", "date": "2026-10-13", "time": "07:00", "title": "pour"}]
        by = wa_brief.events_by_job(events, TUE)
        self.assertEqual(len(by["p0"][1]), wa_brief.MAX_LATER + 1)
        self.assertEqual(by["p0"][1][-1], "• +3 more in the Levelog app")
        self.assertEqual(by["p0"][1][0], "• Wed 12am J0 event 0")      # the soonest first
        # Another job's events never cut this one's.
        self.assertEqual(by["p1"][1], [f"• Sun 9am J1 event {i}" for i in range(3)])
        self.assertEqual(by["p1"][0], ["• 7am pour"])                  # today never cut
        self.assertEqual(by[None][1][-1], "• +1 more in the Levelog app")

    def test_companies_that_shorten_alike_keep_their_names(self):
        line = wa_brief.headcount_line(_ci(2, "ABC Plumbing") + _ci(1, "ABC Electrical")
                                       + _ci(1, "Arkon Construction LLC"))
        self.assertEqual(line, "👷 4 on site · ABC Plumbing 2 · ABC Electrical 1 · Arkon 1")


# ── Mondays: the job's open violations ───────────────────────────────────────

MON = date(2026, 10, 12)


def _swo(pid, num, issued="2026-08-20", **kw):
    row = {"_id": f"s_{num}", "project_id": pid, "record_type": "swo",
           "raw_dob_id": f"swo:{num}", "stop_work_order_number": num,
           "violation_date": issued, "resolution_state": "open", "status": "ACTIVE",
           "previous_status": None, "detected_at": THU_7 - timedelta(days=50),
           "is_seed_transition": False}
    row.update(kw)
    return row


def _summons(pid, num, issued="2026-09-29T00:00:00.000", co=CO_A, **kw):
    row = {"_id": f"d_{num}", "project_id": pid, "company_id": co,
           "record_type": "dot_violation", "raw_id": f"oath:{num}", "number": num,
           "issue_date": issued, "status": "SCHEDULED", "hearing_status": "SCHEDULED",
           "detected_at": THU_7 - timedelta(days=9)}
    row.update(kw)
    return row


def _old(pid, num, issued, **kw):
    """A violation found long ago: never 'new' again."""
    kw.setdefault("detected_at", THU_7 - timedelta(days=120))
    return _violation(pid, num, issued, **kw)


class OpenRule(unittest.TestCase):
    """wa_alerts.open_dob_violations / open_dot_summonses: the newest row of
    each record, resolution_state outside the resolved set -- the app's rule."""

    def test_latest_row_decides(self):
        first = _old(WALWORTH, "34000003", "2026-05-01")
        paid = dict(first, _id="v_34000003b", resolution_state="paid",
                    previous_status="ACTIVE", status_changed_at=THU_7 - timedelta(days=3))
        reopened = _old(WALWORTH, "34000004", "2026-05-01", resolution_state="resolved")
        again = dict(reopened, _id="v_34000004b", resolution_state="hearing_scheduled",
                     status_changed_at=THU_7 - timedelta(days=3))
        got = server.wa_alerts.open_dob_violations([first, paid, reopened, again])
        self.assertEqual([r["_id"] for r in got], ["v_34000004b"])

    def test_closed_states_and_absent(self):
        rows = [_old(WALWORTH, n, "2026-05-01", resolution_state=st)
                for n, st in (("1", "certified"), ("2", "dismissed"), ("3", "paid"),
                              ("4", "resolved"), ("5", "open"), ("6", "cure_pending"),
                              ("7", None), ("8", "Dismissed"))]
        got = {r["violation_number"] for r in server.wa_alerts.open_dob_violations(rows)}
        self.assertEqual(got, {"5", "6", "7"})

    def test_only_violations_and_stop_work_orders(self):
        rows = [_old(WALWORTH, "1", "2026-05-01"), _swo(WALWORTH, "S1"),
                _permit(WALWORTH, "B1", "2026-12-01"),
                {"raw_dob_id": "c:1", "record_type": "complaint", "complaint_status": "ACTIVE"}]
        got = [r["record_type"] for r in server.wa_alerts.open_dob_violations(rows)]
        self.assertEqual(sorted(got), ["swo", "violation"])

    def test_dot_settled_is_closed(self):
        rows = [_summons(THOMAS, "1"), _summons(THOMAS, "2", status="PAID IN FULL"),
                _summons(THOMAS, "3", status="DISMISSED"),
                _summons(THOMAS, "4", status="HEARING COMPLETED", balance_due="250"),
                {"record_type": "dot_permit", "number": "P1", "status": "ISSUED & PRINTED"}]
        got = [r["number"] for r in server.wa_alerts.open_dot_summonses(rows)]
        self.assertEqual(got, ["1", "4"])

    def test_one_closed_set_for_the_app_and_the_brief(self):
        self.assertEqual(server._CLOSED_RESOLUTION_STATES, server.wa_alerts.RESOLVED_STATES)

    def test_the_dm_assistants_facts_count_the_same(self):
        db = _monday_world(MON_8)
        walworth = next(p for p in db.projects.rows if p["_id"] == WALWORTH)
        thomas = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        with _Ctx(db):
            w = _run(server._dm_job_facts(CO_A, walworth, MON_8))
            t = _run(server._dm_job_facts(CO_A, thomas, MON_8))
        self.assertIn("  open violations: 2;", w)   # 35123456, 34000001
        self.assertIn("  open violations: 1;", t)   # the stop-work order


class OpenItems(unittest.TestCase):

    def test_lines_from_stored_fields(self):
        rows = [_old(WALWORTH, "34000001", "2026-06-02", penalty_amount="2500",
                     hearing_date="2026-11-04T00:00:00.000"),
                _swo(WALWORTH, "SWO77")]
        dot = [_summons(WALWORTH, "0123456789", balance_due="1000.50",
                        hearing_date="2026-10-30")]
        self.assertEqual(wa_brief.open_items(rows, dot, MON), [
            "• Stop-work order SWO77 · issued Aug 20",
            "• DOB 34000001 · issued Jun 2 · penalty $2,500 · hearing Nov 4",
            "• DOT 0123456789 · issued Sep 29 · $1,000.50 due · hearing Oct 30"])

    def test_nothing_not_stored_is_said(self):
        rows = [_old(WALWORTH, "34000001", None, penalty_amount="0",
                     hearing_date="2026-10-01")]           # a hearing already past
        self.assertEqual(wa_brief.open_items(rows, [_summons(WALWORTH, "9", issue_date=None)],
                                             MON),
                         ["• DOB 34000001", "• DOT 9"])

    def test_without_a_number_no_line(self):
        rows = [_old(WALWORTH, None, "2026-06-02")]
        self.assertEqual(wa_brief.open_items(rows, [], MON), [])

    def test_stop_work_orders_then_oldest_first(self):
        rows = [_old(WALWORTH, "B", "2026-07-01"), _old(WALWORTH, "A", "2026-03-01"),
                _swo(WALWORTH, "S", "2026-09-01")]
        dot = [_summons(WALWORTH, "D", "2026-05-01")]
        lines = wa_brief.open_items(rows, dot, MON)
        self.assertEqual([ln.split(" · ")[0] for ln in lines],
                         ["• Stop-work order S", "• DOB A", "• DOT D", "• DOB B"])

    def test_capped_with_more(self):
        rows = [_old(WALWORTH, f"3400{i:04d}", f"2026-0{1 + i % 9}-01") for i in range(11)]
        lines = wa_brief.open_items(rows, [], MON)
        self.assertEqual(len(lines), wa_brief.MAX_OPEN + 1)
        self.assertEqual(lines[-1], "+3 more open in the Levelog app.")

    def test_skip_what_is_new_today(self):
        rows = [_old(WALWORTH, "1", "2026-06-02"), _old(WALWORTH, "2", "2026-06-03")]
        dot = [_summons(WALWORTH, "D1")]
        skip = {wa_brief.record_key("dob", "viol:1"), wa_brief.record_key("dot", "oath:D1")}
        self.assertEqual(wa_brief.open_items(rows, dot, MON, skip=skip),
                         ["• DOB 2 · issued Jun 3"])

    def test_new_items_carry_their_record(self):
        items = wa_brief.job_items([_violation(WALWORTH, "35123456")],
                                   YESTERDAY - timedelta(hours=1), THU_7,
                                   [_summons(WALWORTH, "D9", "2026-10-05",
                                             detected_at=YESTERDAY)])
        self.assertEqual({i.get("record") for i in items if i["text"].startswith("🔴")},
                         {"dob:viol:35123456", "dot:oath:D9"})

    def test_a_source_not_yet_synced_gives_no_line(self):
        rows = [_old(WALWORTH, "1", "2026-06-02")]
        self.assertEqual(wa_brief.open_items(rows, [_summons(WALWORTH, "D1")], MON,
                                             synced={}), [])

    def test_monday_in_new_york(self):
        self.assertTrue(wa_brief.is_review_day(MON_8))
        self.assertFalse(wa_brief.is_review_day(TUE_8))
        # Sunday 11 PM in New York is Monday in UTC: not the review day.
        self.assertFalse(wa_brief.is_review_day(
            datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)))

    def test_open_alone_is_something_to_act_on(self):
        job = {"id": "j1", "label": "8 Walworth St", "items": [],
               "open": ["• DOB 34000001 · issued Jun 2"],
               "headcount": NO_CI, "uses_checkins": True}
        self.assertEqual(_compose(MON_8, [job]), ["\n".join([
            "*Mon Oct 12* · *8 Walworth St*", "",
            "📋 *Open violations*", "• DOB 34000001 · issued Jun 2"])])

    def test_the_section_comes_right_after_dob_dot(self):
        job = _target_job()
        job["items"] = [{"rank": 1, "order": (0,),
                         "text": "🔴 New violation 1, issued Oct 9, open. DOB."}]
        job["open"] = ["• DOB 34000001 · issued Jun 2"]
        text = _compose(MON_8, [job])[0]
        self.assertIn("\n".join([
            "🏛 *DOB / DOT*", "🔴 New violation 1, issued Oct 9, open. DOB.", "",
            "📋 *Open violations*", "• DOB 34000001 · issued Jun 2", "", "✅ *You*"]), text)


def _monday_world(now):
    """Walworth: a new violation, an old open one, a dismissed one, one paid
    since. Thomas: open violations only (no check-ins, no permits). Company
    B: an open violation and summons of its own."""
    db = _db()
    first = _old(WALWORTH, "34000003", "2026-05-01")
    db.dob_logs.rows.extend([
        _violation(WALWORTH, "35123456", "2026-10-09", detected_at=now - timedelta(hours=2)),
        _old(WALWORTH, "34000001", "2026-06-02", penalty_amount="2500",
             hearing_date="2026-11-04"),
        _old(WALWORTH, "34000002", "2026-04-01", resolution_state="dismissed"),
        first, dict(first, _id="v_34000003b", resolution_state="paid",
                    previous_status="ACTIVE", status_changed_at=now - timedelta(days=3)),
        _swo(THOMAS, "SWO77"),
        _old(PROJ_B, "99999999", "2026-06-01"),
    ])
    for r in db.dob_logs.rows:
        r["company_id"] = CO_B if r["project_id"] == PROJ_B else CO_A
    db.dot_logs.rows.extend([
        _summons(THOMAS, "0123456789", balance_due="1000"),     # no hearing: no daily line
        _summons(THOMAS, "0123450000", status="PAID IN FULL"),
        _summons(PROJ_B, "0999999999", co=CO_B),
    ])
    return db


class MondayBrief(unittest.TestCase):

    def _brief(self, now):
        db = _monday_world(now)
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, now)
        return _texts(c)

    def test_monday_lists_each_jobs_own_open_violations(self):
        walworth, _thomas = self._brief(MON_8)
        self.assertTrue(walworth.startswith("*Mon Oct 12* · *8 Walworth St*"), walworth)
        self.assertIn("🔴 New violation 35123456, issued Oct 9, open. DOB.", walworth)
        self.assertIn("\n".join([
            "📋 *Open violations*",
            "• DOB 34000001 · issued Jun 2 · penalty $2,500 · hearing Nov 4"]), walworth)
        self.assertNotIn("• DOB 35123456", walworth)        # new today: not twice
        self.assertNotIn("• DOB 34000002", walworth)        # dismissed
        self.assertNotIn("• DOB 34000003", walworth)        # paid since
        self.assertNotIn("• Stop-work order SWO77", walworth)   # Thomas's
        self.assertNotIn("• DOT 0123456789", walworth)

    def test_a_job_with_only_open_violations_gets_its_message(self):
        _walworth, thomas = self._brief(MON_8)
        self.assertEqual(thomas, "\n".join([
            "*Mon Oct 12* · *588 Thomas S Boyland St*", "",
            "📋 *Open violations*",
            "• Stop-work order SWO77 · issued Aug 20",
            "• DOT 0123456789 · issued Sep 29 · $1,000 due"]))

    def test_another_company_never_sees_them(self):
        brief = "\n".join(self._brief(MON_8))
        self.assertNotIn("• DOB 99999999", brief)
        self.assertNotIn("• DOT 0999999999", brief)

    def test_tuesday_has_no_open_list_and_new_still_shows(self):
        brief = "\n".join(self._brief(TUE_8))
        self.assertNotIn("📋 *Open violations*", brief)
        self.assertNotIn("• DOB 34000001", brief)
        self.assertIn("🔴 New violation 35123456, issued Oct 9, open. DOB.", brief)
        # Thomas has nothing else to say on a Tuesday.
        self.assertNotIn("*Tue Oct 13* · *588 Thomas S Boyland St*", brief)

    def test_monday_with_none_open_has_no_section(self):
        db = _db()
        db.dob_logs.rows.append(_old(WALWORTH, "34000002", "2026-04-01",
                                     resolution_state="dismissed"))
        db.checkins.rows.append(_checkin(WALWORTH, "w1", "ABC Concrete"))
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db) as c:
            _tick(c, MON_8)
        brief = "\n".join(_texts(c))
        self.assertNotIn("📋 *Open violations*", brief)
        self.assertIn("No action needed today.", brief)
