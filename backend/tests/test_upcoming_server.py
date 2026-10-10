"""Upcoming v1 in the server: the chat worker (new event, move, cancel,
vague/past skipped, bot-off groups and other companies untouched, never a
group post), the city sync, Project → Upcoming (list, dismiss, edit), the
private calendar feed, the brief section, the day-before DM and personal
reminders, "remind me" in a DM, and the kill switch."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    ADMIN, CO_A, CO_B, G_A, G_B, G_OFF, MIKE, PM, T0, _msg, _world,
)

# T0: Thursday Oct 8 2026, 10 AM New York.


def _run(coro):
    return asyncio.run(coro)


class _Model:
    """Stands in for gpt-4o-mini: `answers` maps a phrase in the >>> line to
    the events to return. "$OPEN" in an event_id is the first OPEN EVENTS id
    in the prompt (what a real model reads there)."""

    def __init__(self, answers=None, fail=False):
        self.answers, self.calls, self.fail = answers or {}, [], fail

    async def __call__(self, messages):
        user = messages[-1]["content"]
        self.calls.append(user)
        if self.fail:
            return None
        target = user.split(">>> ", 1)[1]
        ids = re.findall(r"event_id=(\S+):", user)
        for phrase, events in self.answers.items():
            if phrase in target:
                out = [{**e, "event_id": (ids[0] if ids else "none")
                        if e.get("event_id") == "$OPEN" else e.get("event_id")} for e in events]
                return {"content": json.dumps({"events": out}),
                        "prompt_tokens": 900, "completion_tokens": 60}
        return {"content": json.dumps({"events": []}), "prompt_tokens": 800,
                "completion_tokens": 5}


class _Sends:
    def __init__(self):
        self.group, self.dm = [], []

    async def message(self, chat, text, *a, **k):
        (self.dm if str(chat).endswith("@c.us") or "@" not in str(chat) else self.group).append(
            (chat, text))
        return {"ok": True}

    async def dm_send(self, uid, text, **k):
        self.dm.append((uid, text, k))
        return {"ok": True}


def _ctx(db, sends, env=None):
    return [patch.object(server, "db", db),
            patch.object(server, "send_whatsapp_message", sends.message),
            patch.object(server, "send_whatsapp_dm", sends.dm_send),
            patch.dict(os.environ, {"UPCOMING_DISABLED": "", **(env or {})})]


def _with(db, fn, env=None):
    sends = _Sends()
    ps = _ctx(db, sends, env)
    for p in ps:
        p.start()
    try:
        return fn(), sends
    finally:
        for p in reversed(ps):
            p.stop()


def _chat_tick(db, model, now):
    return _with(db, lambda: _run(server._upcoming_chat_tick(now=now, llm=model)))


def _events(db, **match):
    return [r for r in db[server.UPCOMING].rows
            if all(r.get(k) == v for k, v in match.items())]


CON_ED = {"action": "new", "kind": "utility", "agency": "Con Ed",
          "title": "Con Ed meter set", "date_text": "Oct 15 at 9am",
          "quote": "Con Ed coming Oct 15 at 9am"}


class TheChatWorker(unittest.TestCase):

    def setUp(self):
        self.db = _world()
        _chat_tick(self.db, _Model(), T0)                  # first sight: cursors start

    def test_no_backfill(self):
        db = _world()
        _msg(db, "Con Ed coming Oct 15 at 9am", at=T0 - timedelta(hours=1))
        model = _Model({"Con Ed": [CON_ED]})
        _chat_tick(db, model, T0)
        _chat_tick(db, model, T0 + timedelta(minutes=5))
        self.assertEqual(model.calls, [])
        self.assertEqual(_events(db), [])

    def test_new_moved_cancelled_with_history(self):
        model = _Model({
            "Con Ed coming": [CON_ED],
            "moved to": [{"action": "reschedule", "event_id": "$OPEN", "kind": "utility",
                          "date_text": "Oct 20", "quote": "Con Ed moved to Oct 20"}],
            "cancelled": [{"action": "cancel", "event_id": "$OPEN",
                           "quote": "Con Ed cancelled"}],
        })
        _msg(self.db, "Heads up, Con Ed coming Oct 15 at 9am for the meter",
             sender_name="Roy Fishman")
        rep, sends = _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        (ev,) = _events(self.db, source="chat")
        self.assertEqual((ev["date"], ev["time"], ev["title"], ev["status"], ev["project_id"],
                          ev["company_id"]),
                         ("2026-10-15", "09:00", "Con Ed meter set", "open", "proj_a", CO_A))
        self.assertEqual(ev["quote"], "Con Ed coming Oct 15 at 9am")
        self.assertEqual(ev["evidence"]["sender_name"], "Roy Fishman")

        _msg(self.db, "Con Ed moved to Oct 20, same time")
        _chat_tick(self.db, model, T0 + timedelta(minutes=20))
        (ev,) = _events(self.db, source="chat")
        self.assertEqual((ev["date"], ev["status"]), ("2026-10-20", "open"))
        self.assertEqual([h["action"] for h in ev["history"]], ["created", "rescheduled"])
        self.assertEqual((ev["history"][1]["frm"], ev["history"][1]["to"]),
                         ("2026-10-15", "2026-10-20"))

        _msg(self.db, "Con Ed cancelled, will rebook")
        _chat_tick(self.db, model, T0 + timedelta(minutes=30))
        (ev,) = _events(self.db, source="chat")
        self.assertEqual(ev["status"], "cancelled")
        self.assertEqual(ev["history"][-1]["action"], "cancelled")
        self.assertEqual(sends.group, [])                  # never posts in a group

    def test_an_echo_of_a_move_moves_nothing(self):
        model = _Model({
            "Con Ed coming": [CON_ED],
            "moved to": [{"action": "reschedule", "event_id": "$OPEN", "kind": "utility",
                          "date_text": "Oct 20", "quote": "Con Ed moved to Oct 20"}],
            "Reminder": [{"action": "reschedule", "event_id": "$OPEN", "kind": "utility",
                          "date_text": "Oct 20", "quote": "Con Ed Oct 20"}],
        })
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        _msg(self.db, "Con Ed moved to Oct 20")
        _msg(self.db, "Reminder Con Ed Oct 20 for the meter")
        rep, _ = _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        (ev,) = _events(self.db, source="chat")
        self.assertEqual(ev["date"], "2026-10-20")
        self.assertEqual([h["action"] for h in ev["history"]], ["created", "rescheduled"])
        self.assertEqual(rep["unchanged"], 1)

    def test_the_same_event_twice_is_one_event(self):
        model = _Model({"Con Ed": [CON_ED]})
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        _msg(self.db, "reminder: Con Ed coming Oct 15 at 9am")
        _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        (ev,) = _events(self.db, source="chat")
        self.assertEqual(len(ev["also_seen"]), 1)

    def test_a_repeat_never_brings_back_a_dismissed_event(self):
        model = _Model({"Con Ed": [CON_ED]})
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        (ev,) = _events(self.db, source="chat")
        ev["status"] = "dismissed"
        _msg(self.db, "again: Con Ed coming Oct 15 at 9am")
        _chat_tick(self.db, model, T0 + timedelta(minutes=20))
        self.assertEqual([e["status"] for e in _events(self.db, source="chat")], ["dismissed"])

    def test_vague_ambiguous_past_and_made_up_are_skipped(self):
        model = _Model({
            "next week": [{**CON_ED, "date_text": "next week", "quote": "Con Ed next week"}],
            "the 5th": [{**CON_ED, "date_text": "the 5th", "quote": "Con Ed the 5th"}],
            "Oct 1": [{**CON_ED, "date_text": "Oct 1", "quote": "Con Ed came Oct 1"}],
            "DOB inspection": [{**CON_ED, "kind": "inspection", "date_text": "Oct 22",
                                "quote": "DOB inspection is on Oct 22"}],
        })
        for body in ("Con Ed next week", "Con Ed the 5th", "Con Ed came Oct 1",
                     "DOB inspection coming soon Oct sometime"):
            _msg(self.db, body)
        rep, _ = _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        self.assertEqual(_events(self.db), [])
        self.assertEqual(rep["skipped"], {"vague": 1, "ambiguous": 1, "past": 1,
                                          "quote_not_in_message": 1})

    def test_bot_off_groups_and_other_companies(self):
        model = _Model({"Con Ed": [CON_ED]})
        _msg(self.db, "Con Ed coming Oct 15 at 9am", group=G_OFF)
        _msg(self.db, "Con Ed coming Oct 15 at 9am", group=G_B, project="proj_b", company=CO_B)
        _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        self.assertTrue(all(">>>" in c for c in model.calls))
        self.assertEqual([e["project_id"] for e in _events(self.db)], ["proj_b"])
        self.assertEqual(_events(self.db)[0]["company_id"], CO_B)

    def test_the_cheap_filter_saves_the_call(self):
        model = _Model()
        _msg(self.db, "thanks guys")
        rep, _ = _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        self.assertEqual((model.calls, rep["filtered_out"]), ([], 1))

    def test_a_failed_call_is_retried_then_skipped(self):
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        for i in range(3):
            _chat_tick(self.db, _Model(fail=True), T0 + timedelta(minutes=10 + i))
        rep, _ = _chat_tick(self.db, _Model({"Con Ed": [CON_ED]}), T0 + timedelta(minutes=20))
        self.assertEqual(_events(self.db), [])

    def test_a_failed_write_keeps_the_message_for_the_next_run(self):
        model = _Model({"Con Ed": [CON_ED]})
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        real = server._upcoming_apply

        async def broken(*a, **k):
            raise RuntimeError("primary stepped down")
        with patch.object(server, "_upcoming_apply", broken):
            rep, _ = _chat_tick(self.db, model, T0 + timedelta(minutes=10))
        self.assertEqual((rep["write_failed"], _events(self.db)), (1, []))
        with patch.object(server, "_upcoming_apply", real):
            _chat_tick(self.db, model, T0 + timedelta(minutes=15))
        self.assertEqual(len(_events(self.db, source="chat")), 1)

    def test_kill_switch(self):
        model = _Model({"Con Ed": [CON_ED]})
        _msg(self.db, "Con Ed coming Oct 15 at 9am")
        (rep, _) = _with(self.db, lambda: _run(server._upcoming_chat_tick(
            now=T0 + timedelta(minutes=10), llm=model)), env={"UPCOMING_DISABLED": "1"})
        self.assertTrue(rep["disabled"])
        self.assertEqual(model.calls, [])


def _city_world():
    db = _world()
    db.dob_logs.rows.extend([
        {"_id": "p1", "project_id": "proj_a", "record_type": "permit", "raw_dob_id": "permit:1",
         "job_number": "B0001", "expiration_date": "2026-10-20", "permit_status": "ISSUED",
         "updated_at": T0},
        {"_id": "p2", "project_id": "proj_a", "record_type": "permit", "raw_dob_id": "permit:2",
         "job_number": "B0002", "expiration_date": "2026-09-01", "updated_at": T0},  # passed
        {"_id": "v1", "project_id": "proj_a", "record_type": "violation",
         "raw_dob_id": "ecb:9", "violation_number": "35099999", "hearing_date": "20261022",
         "updated_at": T0},
        {"_id": "v2", "project_id": "proj_a", "record_type": "violation",
         "raw_dob_id": "ecb:10", "violation_number": "35000000", "hearing_date": "20261023",
         "resolution_state": "paid", "updated_at": T0},                         # settled
    ])
    db.dot_logs.rows.extend([
        {"_id": "d1", "project_id": "proj_a", "company_id": CO_A, "record_type": "dot_permit",
         "raw_id": "dotp:7", "number": "X77", "status": "ISSUED - PERMIT",
         "expiration_date": "2026-10-30T00:00:00.000"},
        {"_id": "d2", "project_id": "proj_a", "company_id": CO_A,
         "record_type": "dot_violation", "raw_id": "oath:5", "number": "0123",
         "hearing_date": "2026-10-13T00:00:00.000"},
        {"_id": "d4", "project_id": "proj_a", "company_id": CO_A,
         "record_type": "dot_violation", "raw_id": "oath:8", "number": "0888",
         "hearing_date": "2026-10-14T00:00:00.000", "status": "PAID IN FULL"},   # settled
        {"_id": "d3", "project_id": "proj_b", "company_id": CO_B,
         "record_type": "dot_violation", "raw_id": "oath:6", "number": "0999",
         "hearing_date": "2026-10-13T00:00:00.000"},
    ])
    return db


class CityRecords(unittest.TestCase):

    def test_hearings_and_expirations(self):
        db = _city_world()
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0)))
        got = sorted((e["project_id"], e["kind"], e["agency"], e["date"])
                     for e in _events(db, source="city"))
        self.assertEqual(got, [
            ("proj_a", "hearing", "DOB", "2026-10-22"),
            ("proj_a", "hearing", "OATH", "2026-10-13"),
            ("proj_a", "permit_expiration", "DOB", "2026-10-20"),
            ("proj_a", "permit_expiration", "DOT", "2026-10-30"),
            ("proj_b", "hearing", "OATH", "2026-10-13"),
        ])
        self.assertTrue(all(e["company_id"] == {"proj_a": CO_A, "proj_b": CO_B}[e["project_id"]]
                            for e in _events(db)))

    def test_one_record_one_event_its_date_moved(self):
        db = _city_world()
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0)))
        db.dot_logs.rows[1]["hearing_date"] = "2026-11-03T00:00:00.000"
        rep, _ = _with(db, lambda: _run(server._upcoming_city_tick(now=T0 + timedelta(hours=2))))
        (ev,) = [e for e in _events(db, source="city") if e["key"] == "city:hearing:dot:oath:5"]
        self.assertEqual(ev["date"], "2026-11-03")
        self.assertEqual(ev["history"][-1]["action"], "rescheduled")
        self.assertEqual(rep["created"], 0)
        self.assertEqual(len(_events(db, source="city")), 5)

    def test_a_record_that_stops_qualifying_closes_and_can_reopen(self):
        db = _city_world()
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0)))
        db.dot_logs.rows[1]["status"] = "PAID IN FULL"
        rep, _ = _with(db, lambda: _run(server._upcoming_city_tick(now=T0 + timedelta(hours=2))))
        (ev,) = [e for e in _events(db, source="city") if e["key"] == "city:hearing:dot:oath:5"]
        self.assertEqual((ev["status"], ev["closed_by"], rep["closed"]), ("cancelled", "city", 1))
        self.assertEqual(ev["history"][-1]["action"], "cancelled")
        db.dot_logs.rows[1]["status"] = "DOCKETED"
        db.dot_logs.rows[1]["hearing_date"] = "2026-11-03T00:00:00.000"
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0 + timedelta(hours=4))))
        self.assertEqual((ev["status"], ev["date"], ev["history"][-1]["action"]),
                         ("open", "2026-11-03", "reopened"))

    def test_a_dismissed_record_stays_dismissed(self):
        db = _city_world()
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0)))
        for e in _events(db, source="city"):
            e["status"] = "dismissed"
        _with(db, lambda: _run(server._upcoming_city_tick(now=T0 + timedelta(hours=2))))
        self.assertEqual({e["status"] for e in _events(db, source="city")}, {"dismissed"})


def _seed_chat_event(db, date="2026-10-15", project="proj_a", company=CO_A, **kw):
    row = {"_id": f"e{len(db[server.UPCOMING].rows)}", "company_id": company,
           "project_id": project, "user_id": None, "source": "chat", "kind": "utility",
           "agency": "Con Ed", "title": "Con Ed meter set", "date": date, "time": "09:00",
           "status": "open", "key": "k", "quote": "Con Ed coming Oct 15 at 9am",
           "evidence": {"sender_name": "Roy"}, "history": [], "created_at": T0,
           "updated_at": T0}
    row.update(kw)
    db[server.UPCOMING].rows.append(row)
    return row


class ProjectUpcoming(unittest.TestCase):

    def setUp(self):
        self.db = _city_world()
        _with(self.db, lambda: _run(server._upcoming_city_tick(now=T0)))
        self.chat = _seed_chat_event(self.db)

    def _call(self, coro_fn):
        with patch.object(server, "datetime", _Frozen):
            return _with(self.db, coro_fn)[0]

    def test_list_is_the_jobs_open_events_sorted(self):
        out = self._call(lambda: _run(server.list_project_upcoming("proj_a", current_user=ADMIN)))
        self.assertEqual([e["date"] for e in out["events"]],
                         ["2026-10-13", "2026-10-15", "2026-10-20", "2026-10-22", "2026-10-30"])
        chat = next(e for e in out["events"] if e["source"] == "chat")
        self.assertEqual((chat["chip"], chat["quote"], chat["who"], chat["can_edit"]),
                         ("from chat", "Con Ed coming Oct 15 at 9am", "Roy", True))
        city = next(e for e in out["events"] if e["source"] == "city")
        self.assertFalse(city["can_edit"])

    def test_a_pm_only_on_assigned_jobs(self):
        with self.assertRaises(HTTPException):
            self._call(lambda: _run(server.list_project_upcoming(
                "proj_b", current_user={**PM, "assigned_projects": ["proj_a"]})))

    def test_dismiss_and_edit(self):
        eid = str(self.chat["_id"])
        self._call(lambda: _run(server.edit_project_upcoming(
            "proj_a", eid, server.UpcomingEdit(date="2026-10-16", time=""), current_user=ADMIN)))
        self.assertEqual((self.chat["date"], self.chat["time"]), ("2026-10-16", None))
        self.assertEqual(self.chat["key"], server.upcoming.event_key(
            "proj_a", "utility", "Con Ed", server._Date(2026, 10, 16)))
        self.assertEqual(self.chat["history"][-1]["action"], "edited")
        self._call(lambda: _run(server.dismiss_project_upcoming("proj_a", eid,
                                                                current_user=ADMIN)))
        self.assertEqual(self.chat["status"], "dismissed")
        out = self._call(lambda: _run(server.list_project_upcoming("proj_a", current_user=ADMIN)))
        self.assertNotIn(eid, [e["id"] for e in out["events"]])

    def test_a_city_date_is_not_editable(self):
        city = _events(self.db, source="city")[0]
        with self.assertRaises(HTTPException) as cm:
            self._call(lambda: _run(server.edit_project_upcoming(
                city["project_id"], str(city["_id"]), server.UpcomingEdit(date="2026-12-01"),
                current_user=ADMIN if city["company_id"] == CO_A else ADMIN)))
        self.assertIn(cm.exception.status_code, (404, 409))

    def test_another_companys_event_is_not_found(self):
        b = _seed_chat_event(self.db, project="proj_b", company=CO_B)
        with self.assertRaises(HTTPException):
            self._call(lambda: _run(server.dismiss_project_upcoming("proj_a", str(b["_id"]),
                                                                    current_user=ADMIN)))
        self.assertEqual(b["status"], "open")


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return T0 if tz else T0.replace(tzinfo=None)


class TheCalendarFeed(unittest.TestCase):

    def setUp(self):
        self.db = _city_world()
        self.db.users.rows.append({**ADMIN, "name": "Ann Admin"})
        _seed_chat_event(self.db)

    def _do(self, fn):
        with patch.object(server, "datetime", _Frozen):
            return _with(self.db, fn)[0]

    def test_make_read_revoke(self):
        made = self._do(lambda: _run(server.make_calendar_feed(current_user=ADMIN)))
        token = made["url"].rsplit("/", 1)[1][:-len(".ics")]
        self.assertTrue(made["url"].endswith(".ics"))
        self.assertNotIn(token, json.dumps([r for r in self.db[server.CALENDAR_FEEDS].rows],
                                           default=str))          # only its hash is kept
        resp = self._do(lambda: _run(server.public_calendar_feed(token)))
        body = resp.body.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("SUMMARY:Con Ed meter set · Main St", body)
        self.assertEqual(resp.media_type, "text/calendar; charset=utf-8")
        self._do(lambda: _run(server.revoke_calendar_feed(current_user=ADMIN)))
        with self.assertRaises(HTTPException) as cm:
            self._do(lambda: _run(server.public_calendar_feed(token)))
        self.assertEqual(cm.exception.status_code, 404)

    def test_the_platform_operator_can_read_the_link_it_made(self):
        op = {**ADMIN, "_id": "u_op", "id": "u_op", "role": "owner",
              "is_platform_operator": True}
        self.db.users.rows.append(op)
        made = self._do(lambda: _run(server.make_calendar_feed(current_user=op)))
        resp = self._do(lambda: _run(server.public_calendar_feed(
            made["url"].rsplit("/", 1)[1][:-4])))
        self.assertIn("BEGIN:VCALENDAR", resp.body.decode())

    def test_a_new_link_retires_the_old(self):
        a = self._do(lambda: _run(server.make_calendar_feed(current_user=ADMIN)))["url"]
        self._do(lambda: _run(server.make_calendar_feed(current_user=ADMIN)))
        with self.assertRaises(HTTPException):
            self._do(lambda: _run(server.public_calendar_feed(a.rsplit("/", 1)[1][:-4])))

    def test_unknown_token_and_a_demoted_user(self):
        with self.assertRaises(HTTPException):
            self._do(lambda: _run(server.public_calendar_feed("x" * 43)))
        made = self._do(lambda: _run(server.make_calendar_feed(current_user=ADMIN)))
        for u in self.db.users.rows:
            if u["_id"] == ADMIN["_id"]:
                u["role"] = "cp"
        with self.assertRaises(HTTPException):
            self._do(lambda: _run(server.public_calendar_feed(made["url"].rsplit("/", 1)[1][:-4])))


class OutToPeople(unittest.TestCase):

    def setUp(self):
        self.db = _city_world()
        _with(self.db, lambda: _run(server._upcoming_city_tick(now=T0)))
        _seed_chat_event(self.db, date="2026-10-09")       # tomorrow
        _seed_chat_event(self.db, date="2026-10-09", project="proj_b", company=CO_B,
                         title="B thing")
        self.admin = {**ADMIN, "name": "Ann"}
        self.db.users.rows.append(self.admin)

    def test_brief_section_this_week_without_what_the_brief_already_says(self):
        lines, _ = _with(self.db, lambda: _run(server._upcoming_brief_lines(
            self.admin, CO_A, "admin", T0)))
        self.assertEqual(lines[0], "Upcoming this week")
        self.assertEqual(lines[1:], [
            "• Fri Oct 9, 9am — Con Ed meter set · Main St (from chat)"])
        # The DOB ECB hearing on Oct 22 is past the week; DOT's OATH hearing
        # and the permit expirations are the brief's own lines already.

    def test_day_before_dm_from_5pm_once(self):
        pm = next(u for u in self.db.users.rows if u["_id"] == "u_pm")
        pm["assigned_projects"] = ["proj_a"]
        five = T0.replace(hour=21, minute=5)                # 5:05 PM New York
        rep, sends = _with(self.db, lambda: _run(server._upcoming_notify_tick(now=five)))
        self.assertEqual(rep["day_before_sent"], 1)
        uid, text, kw = sends.dm[0]
        self.assertEqual(uid, "u_pm")
        self.assertEqual(text, "Tomorrow, Fri Oct 9:\n• 9am — Con Ed meter set · Main St "
                               "(from chat)")
        self.assertEqual((kw["kind"], kw["window"]), ("upcoming_day_before", "2026-10-09"))
        _, early = _with(self.db, lambda: _run(server._upcoming_notify_tick(now=T0)))
        self.assertEqual(early.dm, [])                      # 10 AM: not yet

    def test_the_day_before_switch(self):
        pm = next(u for u in self.db.users.rows if u["_id"] == "u_pm")
        pm["assigned_projects"] = ["proj_a"]
        self.db.notification_preferences.rows.append(
            {"_id": "np", "user_id": "u_pm", "project_id": None,
             "whatsapp": {"upcoming_reminders": False}})
        rep, sends = _with(self.db, lambda: _run(server._upcoming_notify_tick(
            now=T0.replace(hour=21, minute=5))))
        self.assertEqual((rep["pref_off"], sends.dm), (1, []))

    def test_a_personal_reminder_the_morning_of(self):
        self.db[server.UPCOMING].rows.append(
            {"_id": "r1", "company_id": CO_A, "project_id": None, "user_id": "u_pm",
             "source": "dm", "kind": "reminder", "title": "call the inspector",
             "date": "2026-10-08", "time": None, "status": "open", "history": []})
        rep, sends = _with(self.db, lambda: _run(server._upcoming_notify_tick(now=T0)))
        self.assertIn(("u_pm", "Reminder: call the inspector"),
                      [(u, t) for u, t, _k in sends.dm])


class RemindMeInADm(unittest.TestCase):

    def setUp(self):
        self.db = _world()
        self.ident = {"user_id": "u_pm", "company_id": CO_A, "role": "pm", "projects": []}
        self.chat = "17185550303@c.us"

    def _turn(self, text, now=T0):
        async def go():
            return await server._upcoming_dm_turn(self.ident, self.chat, text, now)
        return _with(self.db, lambda: _run(go()))

    def test_confirm_once_then_saved(self):
        handled, sends = self._turn("Remind me Oct 15 at 8am to call the inspector")
        self.assertTrue(handled)
        self.assertEqual(sends.dm[-1][1], "Remind you Thu Oct 15, 8am: call the inspector?\n"
                                          "Reply YES to save it, or NO.")
        self.assertEqual(_events(self.db), [])
        handled, sends = self._turn("yes")
        (ev,) = _events(self.db, source="dm")
        self.assertEqual((ev["user_id"], ev["date"], ev["time"], ev["title"], ev["project_id"]),
                         ("u_pm", "2026-10-15", "08:00", "call the inspector", None))
        self.assertEqual(sends.dm[-1][1], "Saved. I'll remind you the morning of Thu Oct 15.")
        handled, _ = self._turn("yes")                      # nothing pending now
        self.assertFalse(handled)

    def test_no_and_unpinnable_days(self):
        self._turn("remind me tomorrow to order rebar")
        handled, sends = self._turn("No")
        self.assertEqual((handled, sends.dm[-1][1], _events(self.db)), (True, "OK, not saved.", []))
        handled, sends = self._turn("remind me next week to order rebar")
        self.assertIn("one day", sends.dm[-1][1])
        handled, sends = self._turn("remind me on the 5th to pay Con Ed")
        self.assertIn("month", sends.dm[-1][1])

    def test_anything_else_is_not_ours(self):
        handled, _ = self._turn("how many guys on site?")
        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()
