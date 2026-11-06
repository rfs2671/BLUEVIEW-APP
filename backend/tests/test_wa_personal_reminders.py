"""A "remind me" with no job is the PERSON's (Roy, 2026-11-06, ruling c).

One person may hold an account in several companies, all on one phone. A
reminder they ask for in the DM names no job, so it belongs to no company:
it is saved under their phone (`person`), with no company; each of their
accounts sees it (the brief, the private calendar feed), it goes out ONCE
on its morning, and the chat's history keeps it neutral. Reminders saved
before keep working under their account's company.

Ada: admin at Acme (co_a), PM at Brick (co_b), one phone, both connected
(the fixture of tests/test_wa_dm_across_companies.py). No network: WaAPI
is the phase-1 _Wire.
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

import server  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, CO_B, _Ctx  # noqa: E402
from tests.test_wa_dm_across_companies import CHAT, _db, _texts, _Turn  # noqa: E402

THU_10 = datetime(2026, 10, 8, 14, 5, tzinfo=timezone.utc)     # Thu 10:05 AM New York
FRI_8 = datetime(2026, 10, 9, 12, 5, tzinfo=timezone.utc)      # Fri 8:05 AM New York


def _run(coro):
    return asyncio.run(coro)


def _ident(c, uid):
    return next(a for a in _run(server._dm_identities(CHAT)) if a["user_id"] == uid)


def _ask(c, ident, text, now=THU_10):
    _run(server._open_dm_reply_window(ADMIN_PHONE))
    return _run(server._upcoming_dm_turn(ident, CHAT, text, now))


def _reminders(c):
    return [r for r in c.db.upcoming_events.rows if r.get("source") == "dm"]


class SavedAsThePersons(unittest.TestCase):

    def test_saved_under_the_phone_with_no_company(self):
        with _Ctx(_db()) as c:
            brick = _ident(c, "u_b")
            _ask(c, brick, "remind me friday to call the inspector")
            _ask(c, brick, "yes")
            (r,) = _reminders(c)
        self.assertEqual((r["company_id"], r["project_id"], r["person"], r["date"]),
                         (None, None, ADMIN_PHONE, "2026-10-09"))

    def test_each_account_sees_it_and_the_brief_lists_it_once(self):
        with _Ctx(_db()) as c:
            _ask(c, _ident(c, "u_b"), "remind me friday to call the inspector")
            _ask(c, _ident(c, "u_b"), "yes")
            users = {u["_id"]: u for u in c.db.users.rows}
            day = date(2026, 10, 9)
            for uid, co, role in (("u_a", CO_A, "admin"), ("u_b", CO_B, "pm")):
                rows = _run(server._upcoming_for(users[uid], co, role, day, day))
                self.assertEqual([r["title"] for r in rows], ["call the inspector"], uid)
            person = _run(server._brief_accounts(users["u_a"]))
            msgs = _run(server._brief_for_accounts(person, FRI_8, lead_uid="u_a"))
        body = "\n".join(t for _p, t in msgs)
        self.assertEqual(body.count("call the inspector"), 1, body)

    def test_a_reminder_saved_before_still_shows_under_its_company(self):
        db = _db()
        db.upcoming_events.rows.append(
            {"_id": "old", "company_id": CO_A, "project_id": None, "user_id": "u_a",
             "source": "dm", "kind": "reminder", "title": "old one", "date": "2026-10-09",
             "status": "open", "history": []})
        with _Ctx(db) as c:
            users = {u["_id"]: u for u in c.db.users.rows}
            day = date(2026, 10, 9)
            a = _run(server._upcoming_for(users["u_a"], CO_A, "admin", day, day))
            b = _run(server._upcoming_for(users["u_b"], CO_B, "pm", day, day))
        self.assertEqual(([r["title"] for r in a], b), (["old one"], []))


class SentOnceToThePerson(unittest.TestCase):

    def _saved(self, c, uid="u_b"):
        _ask(c, _ident(c, uid), "remind me friday to call the inspector")
        _ask(c, _ident(c, uid), "yes")
        c.wire.calls.clear()

    def test_once_on_its_morning_neutral_in_the_history(self):
        with _Ctx(_db()) as c:
            self._saved(c)
            r1 = _run(server._upcoming_notify_tick(now=FRI_8))
            r2 = _run(server._upcoming_notify_tick(now=FRI_8 + timedelta(minutes=30)))
            sent = [t for t in _texts(c) if t.startswith("Reminder")]
            rows = [r for r in c.db.whatsapp_messages.rows if r["body"].startswith("Reminder")]
        self.assertEqual((r1["reminders_sent"], r2["reminders_sent"]), (1, 0))
        self.assertEqual(sent, ["Reminder: call the inspector"])
        self.assertEqual(rows[0].get("dm_company"), server.DM_SCOPE_NEUTRAL)

    def test_held_while_any_of_their_companies_keeps_shabbos(self):
        async def quiet(company_id, project_id=None, now=None):
            return (now + timedelta(hours=10)) if str(company_id) == CO_B else None
        with _Ctx(_db()) as c:
            self._saved(c, "u_a")              # asked as Acme; Brick keeps Shabbos
            with patch.object(server, "_shabbos_quiet", quiet):
                r = _run(server._upcoming_notify_tick(now=FRI_8))
            sent = [t for t in _texts(c) if t.startswith("Reminder")]
        self.assertEqual((r["shabbos_queued"], sent), (1, []))

    def test_no_account_connected_on_the_number_nothing_goes(self):
        with _Ctx(_db()) as c:
            self._saved(c)
            for o in c.db[server.WA_OPTINS].rows:
                o["status"] = "opted_out"
            r = _run(server._upcoming_notify_tick(now=FRI_8))
        self.assertEqual((r["reminders_sent"], r["refused"]), (0, 1))


class NeverAskedWhichCompany(unittest.TestCase):

    def test_remind_me_is_not_a_company_question_even_in_the_old_pipeline(self):
        t = _Turn(brain=False)
        with _Ctx(_db()) as c:
            t.say(c, "remind me friday to call the inspector", "m1")
            asked = [x for x in _texts(c) if x.startswith("Which company")]
        self.assertEqual(asked, [])
        self.assertEqual((t.calls[0]["as"], t.calls[0]["scope"]),
                         ("u_a", server.DM_SCOPE_NEUTRAL))


if __name__ == "__main__":
    unittest.main()
