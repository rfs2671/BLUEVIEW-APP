"""WhatsApp Phase 2 — the GC group and the DOB alerts posted to it.

  * Auto-pick: the one linked group with no trade word in its name.
  * Confirm by DM to the company's main admin (opted in): 1 confirms, 2
    declines, no answer posts nothing.
  * Alerts go to the CONFIRMED group only, inside the project's send window (Anytime by default), once each, ever;
    the first run records what exists and posts nothing.
  * The violation summary may not carry a number, date, amount or code that
    is not in the DOB record; otherwise the fixed template is posted.
  * Another company's group is never picked, confirmed or posted to.
  * The settings endpoints are admin-only and company-scoped.
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
from lib import wa_dm, wa_gc  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, CO_B, _Ctx, _users, _start,
)
from tests._fake_mongo import FakeDb  # noqa: E402

G_GC = "120363000000000101@g.us"
G_PLUMB = "120363000000000102@g.us"
G_B = "120363000000000201@g.us"
NOON = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)     # 11 AM ET
LATER = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
NIGHT = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)          # 10 PM ET
ADMIN = {"_id": "u_admin", "id": "u_admin", "company_id": CO_A,
         "role": "admin", "account_status": "approved"}
PM = {"_id": "u_pm", "id": "u_pm", "company_id": CO_A, "role": "pm",
      "account_status": "approved", "assigned_projects": ["proj_a"]}
ADMIN_B = {"_id": "u_b", "id": "u_b", "company_id": CO_B, "role": "admin",
           "account_status": "approved"}


def _run(coro):
    return asyncio.run(coro)


def _violation(raw, **kw):
    row = {"_id": f"v_{raw}", "project_id": "proj_a", "company_id": CO_A,
           "record_type": "violation", "raw_dob_id": raw,
           "violation_number": f"V{raw}", "description": "Failure to maintain",
           "penalty_amount": "1,200", "violation_date": "2026-10-01",
           "status": "ACTIVE", "resolution_state": "open",
           "dob_link": f"https://dob.example/{raw}",
           "detected_at": NOON}
    row.update(kw)
    return row


def _permit(raw, expires, **kw):
    row = {"_id": f"p_{raw}", "project_id": "proj_a", "company_id": CO_A,
           "record_type": "permit", "raw_dob_id": raw, "job_number": f"J{raw}",
           "work_type": "Plumbing", "expiration_date": expires,
           "dob_link": f"https://dob.example/p{raw}", "detected_at": NOON}
    row.update(kw)
    return row


def _world(**extra):
    groups = [
        {"_id": "g1", "wa_group_id": G_GC, "group_name": "Main St Project",
         "project_id": "proj_a", "company_id": CO_A, "active": True},
        {"_id": "g2", "wa_group_id": G_PLUMB, "group_name": "Main St Plumbing",
         "project_id": "proj_a", "company_id": CO_A, "active": True},
        {"_id": "g3", "wa_group_id": G_B, "group_name": "B site",
         "project_id": "proj_b", "company_id": CO_B, "active": True},
    ]
    cols = dict(
        users=[{**u, "account_status": "approved"} for u in _users()],
        companies=[{"_id": CO_A, "name": "A", "created_by": "u_admin"},
                   {"_id": CO_B, "name": "B", "created_by": "u_b"}],
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "Main St"},
                  {"_id": "proj_b", "company_id": CO_B, "name": "B"}],
        whatsapp_groups=groups,
    )
    cols.update(extra)
    return FakeDb(unique={server.WA_OPTINS: ("phone",)}, **cols)


def _group_sends(c, group=None):
    return [p for p in c.wire.calls if "message" in p
            and str(p.get("chatId", "")).endswith("@g.us")
            and (group is None or p["chatId"] == group)]


def _dm_sends(c):
    return [p for p in c.wire.calls if "message" in p
            and not str(p.get("chatId", "")).endswith("@g.us")]


def _settings(pid="proj_a"):
    return _run(server._whatsapp_project_settings(pid))


def _confirm(pid="proj_a", company=CO_A, group=G_GC):
    _run(server._set_whatsapp_project_fields(
        pid, company, {"gc_group_id": group, "gc_group_confirmed": True}))


def _no_ai():
    async def none(_kind, _facts):
        return None
    return patch.object(server, "_gc_ai_line", none)


# ══════════════════════════════════════════════════════════════════════════
# Pure parts
# ══════════════════════════════════════════════════════════════════════════

class TheAutoPick(unittest.TestCase):

    def test_trade_words_are_excluded(self):
        for name in ("Main St Plumbing", "ELECTRIC crew", "HVAC - 5th fl",
                     "Concrete pour", "Steel erectors", "Framing", "Roofing"):
            with self.subTest(name):
                self.assertTrue(wa_gc.has_trade_word(name))
        self.assertFalse(wa_gc.has_trade_word("Main St Project"))
        self.assertFalse(wa_gc.has_trade_word("Steelman Ave GC"))  # whole words

    def test_exactly_one_non_trade_group_is_the_pick(self):
        g = [{"wa_group_id": G_GC, "group_name": "Main St Project"},
             {"wa_group_id": G_PLUMB, "group_name": "Main St Plumbing"}]
        self.assertEqual(wa_gc.pick_gc_group(g)["wa_group_id"], G_GC)
        two = g + [{"wa_group_id": "x@g.us", "group_name": "Main St Owners"}]
        self.assertIsNone(wa_gc.pick_gc_group(two))
        self.assertIsNone(wa_gc.pick_gc_group(g[1:]))

    def test_the_trade_list_is_a_constant(self):
        self.assertIsInstance(wa_gc.TRADE_WORDS, tuple)
        for w in ("plumbing", "electric", "hvac", "concrete", "steel",
                  "framing", "roofing"):
            self.assertIn(w, wa_gc.TRADE_WORDS)

    def test_replies(self):
        for body, want in (("1", "yes"), (" 1 ", "yes"), ("Yes", "yes"),
                           ("2", "no"), ("no", "no"), ("12", None),
                           ("1 maybe", None), ("", None)):
            with self.subTest(body):
                self.assertEqual(wa_gc.parse_confirm_reply(body), want)


class AroundTheClock(unittest.TestCase):

    def test_there_is_no_posting_window(self):
        self.assertFalse(hasattr(wa_gc, "in_post_window"))
        self.assertFalse(hasattr(wa_gc, "POST_START_HOUR"))


class TheChecker(unittest.TestCase):
    FACTS = {"violation_number": "V9", "penalty_amount": "1,200",
             "violation_date": "2026-10-01", "description": "Failure to maintain"}

    def test_an_invented_amount_is_blocked(self):
        self.assertFalse(wa_gc.check_summary(
            "Levelog: a new DOB violation with a $200 fine.", self.FACTS))
        self.assertFalse(wa_gc.check_summary(
            "Levelog: a new DOB violation; fine $5,000.", self.FACTS))

    def test_invented_dates_numbers_and_codes_are_blocked(self):
        for text in ("Levelog: a new DOB violation issued 2026-09-30.",
                     "Levelog: a new DOB violation under BC 3301.2.",
                     "Levelog: a new DOB violation, fix within 30 days.",
                     "Levelog: a new DOB violation, ECB hearing."):
            with self.subTest(text):
                self.assertFalse(wa_gc.check_summary(text, self.FACTS))

    def test_a_date_is_checked_whole_not_part_by_part(self):
        """Record date 2026-01-10: its 1, 10 and 2026 must not recombine
        into "October 1, 2026" (the Codex finding)."""
        facts = {"violation_date": "2026-01-10", "description": "x"}
        for text in ("Levelog: a new DOB violation issued October 1, 2026.",
                     "Levelog: a new DOB violation issued 1 October 2026.",
                     "Levelog: a new DOB violation issued Oct 1.",
                     "Levelog: a new DOB violation issued 10/01/2026.",
                     "Levelog: a new DOB violation issued 2026-10-01.",
                     "Levelog: a new DOB violation issued in October."):
            with self.subTest(text):
                self.assertFalse(wa_gc.check_summary(text, facts))
        for text in ("Levelog: a new DOB violation issued January 10, 2026.",
                     "Levelog: a new DOB violation issued Jan. 10th.",
                     "Levelog: a new DOB violation issued 10 January 2026.",
                     "Levelog: a new DOB violation issued 01/10/2026.",
                     "Levelog: a new DOB violation issued 2026-01-10.",
                     "Levelog: a new DOB violation; you may need to fix it."):
            with self.subTest(text):
                self.assertTrue(wa_gc.check_summary(text, facts))

    def test_record_values_pass(self):
        self.assertTrue(wa_gc.check_summary(
            "Levelog: a new DOB violation for failure to maintain, issued "
            "October 1, 2026, with a $1,200 penalty.", self.FACTS))

    def test_the_template_carries_only_record_values(self):
        from lib import wa_alerts
        rec = {"record_type": "violation", **self.FACTS,
               "dob_link": "https://dob.example/9"}
        line = wa_alerts.template_line("violation", rec, today=date(2026, 10, 7))
        self.assertTrue(wa_gc.check_summary(line, wa_alerts.facts(rec)))
        msg = wa_alerts.alert_message("violation", rec, address="Main St", what=line)
        self.assertIn("Violation #V9", msg)
        self.assertIn("Source: DOB · https://dob.example/9", msg)
        self.assertNotIn("$", msg)


class PermitThresholds(unittest.TestCase):

    def test_due_threshold(self):
        today = date(2026, 10, 7)
        for days, want in ((31, None), (30, 30), (15, 30), (14, 14), (8, 14),
                           (7, 7), (2, 7), (1, 1), (0, 1), (-1, None)):
            with self.subTest(days):
                self.assertEqual(wa_gc.permit_threshold_due(
                    today + timedelta(days=days), today), want)
        self.assertIsNone(wa_gc.permit_threshold_due(None, today))

    def test_dates_as_dob_writes_them(self):
        for s in ("2026-11-03", "2026-11-03T00:00:00.000", "11/03/2026",
                  "20261103"):
            self.assertEqual(wa_gc.parse_dob_date(s), date(2026, 11, 3))
        self.assertIsNone(wa_gc.parse_dob_date("soon"))


# ══════════════════════════════════════════════════════════════════════════
# Confirm by DM
# ══════════════════════════════════════════════════════════════════════════

class TheConfirmFlow(unittest.TestCase):

    def _ask(self, c, now=NOON):
        return _run(server._gc_propose_tick(now))

    def test_the_main_admin_is_asked_once_with_the_picked_group(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            before = len(_dm_sends(c))
            r = self._ask(c)
            dms = _dm_sends(c)[before:]
            self.assertEqual(r["asked"], 1)
            self.assertEqual(len(dms), 1)
            self.assertIn("'Main St Project'", dms[0]["message"])
            self.assertIn("Main St", dms[0]["message"])
            self.assertIn("Reply 1 Yes / 2 No", dms[0]["message"])
            prop = _settings()["gc_proposal"]
            self.assertEqual((prop["status"], prop["group_id"],
                              prop["admin_user_id"]),
                             ("pending", G_GC, "u_admin"))
            self.assertFalse(_settings()["gc_group_confirmed"])
            self._ask(c)
            self.assertEqual(len(_dm_sends(c)), before + 1)  # not asked again

    def test_no_opt_in_no_question(self):
        with _Ctx(db=_world()) as c:
            r = self._ask(c)
            self.assertEqual((r["asked"], r["not_sent"]), (0, 2))  # A and B
            self.assertEqual(_dm_sends(c), [])
            self.assertIsNone(_settings()["gc_proposal"])

    def test_the_question_goes_out_at_night_too(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            n = len(_dm_sends(c))
            self.assertEqual(self._ask(c, NIGHT)["asked"], 1)
            self.assertEqual(len(_dm_sends(c)), n + 1)

    def test_the_main_admin_is_the_creator_else_the_earliest_admin(self):
        db = _world()
        db.users.rows.append({"_id": "u_admin2", "company_id": CO_A,
                              "role": "admin", "account_status": "approved",
                              "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
        with _Ctx(db=db):
            self.assertEqual(str(_run(server._company_main_admin(CO_A))["_id"]),
                             "u_admin")
            db.companies.rows[0]["created_by"] = "u_gone"
            self.assertEqual(str(_run(server._company_main_admin(CO_A))["_id"]),
                             "u_admin2")
            self.assertIsNone(_run(server._company_main_admin("")))

    def test_reply_1_confirms(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            self._ask(c)
            _run(server._process_whatsapp_message(
                _dm(ADMIN_PHONE, "1")))
            s = _settings()
            self.assertEqual((s["gc_group_id"], s["gc_group_confirmed"]),
                             (G_GC, True))
            self.assertEqual(s["gc_proposal"]["status"], "confirmed")
            self.assertIn("Done.", _dm_sends(c)[-1]["message"])

    def test_reply_2_declines_and_the_admin_picks_in_the_app(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            self._ask(c)
            _run(server._process_whatsapp_message(_dm(ADMIN_PHONE, "2")))
            s = _settings()
            self.assertFalse(s["gc_group_confirmed"])
            self.assertIsNone(s["gc_group_id"])
            self.assertEqual(s["gc_declined"], [G_GC])
            self.assertIn("then WhatsApp", _dm_sends(c)[-1]["message"])
            n = len(_dm_sends(c))
            self._ask(c, LATER)   # never asked again about the same project
            self.assertEqual(len(_dm_sends(c)), n)

    def test_no_answer_posts_nothing(self):
        db = _world(dob_logs=[_violation("1")])
        with _Ctx(db=db) as c:
            _start(ADMIN_PHONE)
            self._ask(c)
            later = NOON + timedelta(hours=server.GC_PROPOSAL_TTL_HOURS + 1)
            self._ask(c, later)
            self.assertEqual(_settings()["gc_proposal"]["status"], "expired")
            with _no_ai():
                r = _run(server._gc_alerts_tick(later))
            self.assertEqual(r["projects"], 0)
            self.assertEqual(_group_sends(c), [])
            # An answer after expiry changes nothing.
            self.assertFalse(_run(server._handle_gc_confirm_reply(
                f"{ADMIN_PHONE}@c.us", "yes")))
            self.assertFalse(_settings()["gc_group_confirmed"])

    def test_a_1_from_someone_without_a_question_is_not_taken(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            self._ask(c)
            self.assertFalse(_run(server._handle_gc_confirm_reply(
                "15550001002@c.us", "yes")))     # the PM, no opt-in
            self.assertFalse(_settings()["gc_group_confirmed"])

    def test_a_group_moved_away_before_the_answer_is_not_confirmed(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            self._ask(c)
            c.db.whatsapp_groups.rows[0]["company_id"] = CO_B
            _run(server._process_whatsapp_message(_dm(ADMIN_PHONE, "1")))
            self.assertFalse(_settings()["gc_group_confirmed"])
            self.assertIn("no longer linked", _dm_sends(c)[-1]["message"])

    def test_another_companys_group_is_never_proposed(self):
        db = _world()
        db.whatsapp_groups.rows[:2] = []           # proj_a has no groups
        db.whatsapp_groups.rows.append(
            {"_id": "gx", "wa_group_id": "120363000000000999@g.us",
             "group_name": "Main St", "project_id": "proj_a",
             "company_id": CO_B, "active": True})  # claims proj_a, wrong company
        with _Ctx(db=db) as c:
            _start(ADMIN_PHONE)
            n = len(_dm_sends(c))
            self.assertEqual(self._ask(c)["asked"], 0)
            self.assertEqual(len(_dm_sends(c)), n)


def _dm(phone, body, msg_id=None):
    import itertools
    _dm.n = getattr(_dm, "n", itertools.count(1))
    return {"event": "message", "data": {"message": {
        "id": {"id": msg_id or f"GC{next(_dm.n)}", "fromMe": False},
        "from": f"{phone}@c.us", "body": body, "type": "chat"}}}


# ══════════════════════════════════════════════════════════════════════════
# Alerts
# ══════════════════════════════════════════════════════════════════════════

class TheAlerts(unittest.TestCase):

    def test_no_backfill_then_each_new_violation_posts_once(self):
        db = _world(dob_logs=[_violation("1")])
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual((r["baselined"], r["posted"]), (1, 0))
            self.assertEqual(_group_sends(c), [])
            db.dob_logs.rows.append(_violation("2"))
            r = _run(server._gc_alerts_tick(NOON))
            sends = _group_sends(c, G_GC)
            self.assertEqual((r["posted"], len(sends)), (1, 1))
            self.assertIn("Violation #V2", sends[0]["message"])
            self.assertIn("Source: DOB · https://dob.example/2", sends[0]["message"])
            self.assertNotIn("V1", sends[0]["message"])
            _run(server._gc_alerts_tick(LATER))
            _run(server._gc_alerts_tick(LATER))
            self.assertEqual(len(_group_sends(c)), 1)      # once, ever
            # A status change is a new dob_logs row, not a new violation.
            db.dob_logs.rows.append(_violation(
                "2", _id="v_2b", status="HEARING",
                detected_at=LATER))
            _run(server._gc_alerts_tick(LATER))
            self.assertEqual(len(_group_sends(c)), 1)
            gc_rows = [r for r in db[server.WA_LEDGER].rows
                       if str(r["_id"]).startswith("gc:")]
            self.assertTrue(gc_rows)
            self.assertFalse([r for r in gc_rows if "expires_at" in r])  # never expire

    def test_resolved_violations_are_not_posted(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("3", resolution_state="dismissed"))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])

    def test_a_violation_found_at_night_posts_at_once(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("4"))
            r = _run(server._gc_alerts_tick(NIGHT))         # 10 PM ET
            self.assertEqual(r["posted"], 1)
            self.assertEqual(len(_group_sends(c)), 1)
            _run(server._gc_alerts_tick(LATER))
            self.assertEqual(len(_group_sends(c)), 1)       # once, ever

    def test_an_invented_fine_falls_back_to_the_template(self):
        async def liar(_kind, _facts):
            return "A new DOB violation with a $500 fine."
        db = _world()
        with _Ctx(db=db) as c, patch.object(server, "_gc_ai_line", liar):
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("5"))
            _run(server._gc_alerts_tick(NOON))
            msg = _group_sends(c)[0]["message"]
            self.assertNotIn("500", msg)
            self.assertIn("Failure to maintain", msg)
            self.assertIn("Violation #V5", msg)

    def test_a_checked_summary_is_used(self):
        async def good(_kind, _facts):
            return ("A new DOB violation for failure to maintain, "
                    "with a $1,200 penalty.")
        db = _world()
        with _Ctx(db=db) as c, patch.object(server, "_gc_ai_line", good):
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("6"))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c)[0]["message"].split("\n")[1],
                             "A new DOB violation for failure to maintain, "
                             "with a $1,200 penalty.")

    def test_permit_reminders_at_thresholds_no_backfill(self):
        today = wa_gc.today_et(NOON)
        exp = (today + timedelta(days=10)).isoformat()
        db = _world(dob_logs=[_permit("1", exp), _permit("2", None),
                              _permit("3", "")])
        with _Ctx(db=db) as c:
            _confirm()
            r = _run(server._gc_alerts_tick(NOON))   # 10 days out: 30, 14 seen
            self.assertEqual(r["permits_no_expiry"], 2)
            self.assertEqual(_group_sends(c), [])
            _run(server._gc_alerts_tick(NOON + timedelta(days=1)))
            self.assertEqual(_group_sends(c), [])          # still inside 14
            r = _run(server._gc_alerts_tick(NOON + timedelta(days=3)))
            sends = _group_sends(c)
            self.assertEqual(len(sends), 1)                # 7 days out
            self.assertIn("expires in 7 days", sends[0]["message"])
            self.assertIn("Permit #J1", sends[0]["message"])
            _run(server._gc_alerts_tick(NOON + timedelta(days=4)))
            self.assertEqual(len(_group_sends(c)), 1)
            _run(server._gc_alerts_tick(NOON + timedelta(days=9)))
            self.assertIn("expires tomorrow", _group_sends(c)[-1]["message"])
            self.assertEqual(len(_group_sends(c)), 2)

    def test_a_baseline_that_did_not_finish_posts_no_history(self):
        """An item write fails during the first run: no marker is written,
        and the next run baselines again instead of posting the history."""
        db = _world(dob_logs=[_violation("20"), _violation("21")])
        real = server._gc_ledger_insert
        calls = {"n": 0}

        async def flaky(lid, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                return "error"
            return await real(lid, **kw)
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            with patch.object(server, "_gc_ledger_insert", flaky):
                r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["baselined"], 0)
            self.assertIsNone(_run(db[server.WA_LEDGER].find_one(
                {"_id": wa_gc.baseline_id("proj_a")})))
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual((r["baselined"], r["posted"]), (1, 0))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])

    def test_revoked_permits_get_no_reminders(self):
        today = wa_gc.today_et(NOON)
        db = _world()
        with _Ctx(db=db) as c:
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows += [
                _permit("30", (today + timedelta(days=5)).isoformat(),
                        permit_status="REVOKED"),
                _permit("31", (today + timedelta(days=5)).isoformat(),
                        permit_status="ISSUED")]
            _run(server._gc_alerts_tick(NOON))
            sends = _group_sends(c)
            self.assertEqual(len(sends), 1)
            self.assertIn("Permit #J31", sends[0]["message"])

    def test_switched_off_is_seen_not_posted_later(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"violation_alerts": False}))
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("7"))
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["seen_while_off"], 1)
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"violation_alerts": True}))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])

    def test_unconfirmed_group_gets_nothing(self):
        db = _world(dob_logs=[_violation("8")])
        with _Ctx(db=db) as c, _no_ai():
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"gc_group_id": G_GC, "gc_group_confirmed": False}))
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("9"))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])

    def test_another_companys_group_is_never_posted_to(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm(group=G_B)               # proj_a pointed at co_b's group
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("10"))
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["skipped_unbound"], 1)
            self.assertEqual(_group_sends(c), [])

    def test_a_settings_row_naming_another_companys_project_posts_nothing(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm(company=CO_B)            # row's company is not proj_a's
            db.dob_logs.rows.append(_violation("11"))
            _run(server._gc_alerts_tick(NOON))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])

    def test_a_failed_send_is_retried_next_run(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            db.dob_logs.rows.append(_violation("12"))
            c.wire.responses = [(500, {}, None)]
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["failed"], 1)
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["posted"], 1)


# ══════════════════════════════════════════════════════════════════════════
# Settings endpoints
# ══════════════════════════════════════════════════════════════════════════

class TheSettingsEndpoints(unittest.TestCase):

    def test_admin_reads_groups_and_switches(self):
        with _Ctx(db=_world()):
            _confirm()
            out = _run(server.get_project_whatsapp_settings("proj_a", ADMIN))
        self.assertEqual(out["gc_group"],
                         {"wa_group_id": G_GC, "group_name": "Main St Project",
                          "confirmed": True})
        self.assertEqual({g["wa_group_id"] for g in out["groups"]},
                         {G_GC, G_PLUMB})
        self.assertEqual((out["violation_alerts"], out["permit_reminders"]),
                         (True, True))
        self.assertEqual(set(out), {"project_id", "gc_group", "gc_pending_question",
                                    "groups", "send_window",
                                    *server.wa_alerts.SWITCHES})

    def test_a_pm_cannot_read_or_change(self):
        with _Ctx(db=_world()):
            for call in (lambda: server.get_project_whatsapp_settings("proj_a", PM),
                         lambda: server.patch_project_whatsapp_alerts(
                             "proj_a", {"violation_alerts": False}, PM),
                         lambda: server.put_project_whatsapp_gc_group(
                             "proj_a", {"gc_group_id": G_GC,
                                        "gc_group_confirmed": True}, PM)):
                with self.assertRaises(HTTPException) as e:
                    _run(call())
                self.assertEqual(e.exception.status_code, 403)

    def test_another_companys_admin_gets_404(self):
        with _Ctx(db=_world()):
            for call in (lambda: server.get_project_whatsapp_settings("proj_a", ADMIN_B),
                         lambda: server.patch_project_whatsapp_alerts(
                             "proj_a", {"violation_alerts": False}, ADMIN_B)):
                with self.assertRaises(HTTPException) as e:
                    _run(call())
                self.assertEqual(e.exception.status_code, 404)
            self.assertTrue(_settings()["violation_alerts"])

    def test_an_admin_cannot_pick_another_companys_group(self):
        with _Ctx(db=_world()):
            with self.assertRaises(HTTPException) as e:
                _run(server.put_project_whatsapp_gc_group(
                    "proj_a", {"gc_group_id": G_B, "gc_group_confirmed": True},
                    ADMIN))
            self.assertEqual(e.exception.status_code, 403)
            self.assertIsNone(_settings()["gc_group_id"])

    def test_switches_validate_and_persist(self):
        with _Ctx(db=_world()):
            for bad in ({}, {"violation_alerts": "no"}, {"summaries": True},
                        {"gc_group_id": G_GC}):
                with self.subTest(bad):
                    with self.assertRaises(HTTPException) as e:
                        _run(server.patch_project_whatsapp_alerts("proj_a", bad, ADMIN))
                    self.assertEqual(e.exception.status_code, 422)
            _confirm()
            out = _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"permit_reminders": False}, ADMIN))
            self.assertFalse(out["permit_reminders"])
            self.assertTrue(out["violation_alerts"])
            self.assertTrue(out["gc_group"]["confirmed"])   # untouched

    def test_change_in_the_app_answers_a_pending_question(self):
        with _Ctx(db=_world()) as c:
            _start(ADMIN_PHONE)
            _run(server._gc_propose_tick(NOON))
            _run(server.put_project_whatsapp_gc_group(
                "proj_a", {"gc_group_id": G_PLUMB, "gc_group_confirmed": True},
                ADMIN))
            s = _settings()
            self.assertEqual((s["gc_group_id"], s["gc_proposal"]["status"]),
                             (G_PLUMB, "answered_in_app"))
            self.assertFalse(_run(server._handle_gc_confirm_reply(
                f"{ADMIN_PHONE}@c.us", "yes")))
            self.assertEqual(_settings()["gc_group_id"], G_PLUMB)


class TheBotText(unittest.TestCase):

    def test_gc_texts_say_levelog_and_name_only_live_features(self):
        for t in (wa_dm.GC_CONFIRM_TEXT, wa_dm.GC_CONFIRMED_TEXT,
                  wa_dm.GC_DECLINED_TEXT, wa_dm.GC_GONE_TEXT, wa_dm.INTRO_TEXT):
            self.assertNotIn("Blueview", t)
            for word in ("summary", "summaries", "reminder to", "reply alert"):
                self.assertNotIn(word, t.lower())


if __name__ == "__main__":
    unittest.main()
