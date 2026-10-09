"""Sub chasing v1, SHADOW MODE (lib/wa_chase.py, server._chase_tick).

Nothing is sent: every test checks that no send function was called. Each
rule, the stop conditions, batching, alert hours, the kill switch and the
review endpoints.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_chase  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    ADMIN, ADMIN_B, CO_A, G_A, MIKE, PM, _run, _world,
)

DAY = "2026-10-08"                      # Thursday
G_2 = "120363000000000309@g.us"
PAT = "17185550303"


def _et(h, m=0, day=8):
    """2026-10-<day> h:m New York (EDT), in UTC."""
    return datetime(2026, 10, day, h, m, tzinfo=timezone.utc) + timedelta(hours=4)


_n = [0]


def _item(db, quote="I'll send the stair RFI today", **over):
    _n[0] += 1
    it = {
        "_id": f"it{_n[0]}", "company_id": CO_A, "project_id": "proj_a",
        "group_id": G_A, "type": "commitment", "status": "open",
        "summary": quote,
        "owner": {"kind": "sender_map", "id": "u_mike", "name": "Mike Rivera",
                  "sub_company": "Rivera Electric", "status": "resolved", "jid": f"{MIKE}@c.us", "source": "sender"},
        "due": {"due_text": "today", "due_at": DAY, "due_source": "parsed"},
        "evidence": {"message_id": f"M{_n[0]}", "quote": quote,
                     "sent_at": _et(7, 0), "sender": MIKE},
        "history": [{"id": "e0", "kind": "created", "at": _et(7, 0)}],
        "extraction": {"source": "live", "prompt_version": "att-v1.2"},
        "review": None,
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(it.get(k), dict):
            it[k] = {**it[k], **v}
        else:
            it[k] = v
    db.attention_items.rows.append(it)
    return it


def _db():
    db = _world()
    db.users.rows.append({"_id": "u_ana", "company_id": CO_A, "name": "Ana Admin",
                          "role": "admin"})
    db.whatsapp_groups.rows.append({
        "_id": "g9", "wa_group_id": G_2, "group_name": "Main St Electric",
        "project_id": "proj_a", "company_id": CO_A, "active": True})
    return db


class _Base(unittest.TestCase):

    def setUp(self):
        self.db = _db()
        self.sent = []

    def chase(self, now):
        async def no_send(*a, **k):
            self.sent.append((a, k))
        patches = [patch.object(server, n, no_send) for n in (
            "send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
            "_react_to_message")]
        with patch.object(server, "db", self.db):
            for p in patches:
                p.start()
            try:
                return _run(server._chase_tick(now))
            finally:
                for p in patches:
                    p.stop()

    def rows(self, slot=None):
        rs = self.db[wa_chase.COLLECTION].rows
        return [r for r in rs if slot is None or r["slot"] == slot]

    def tearDown(self):
        self.assertEqual(self.sent, [], "shadow mode: nothing may be sent")

    def say(self, body, at, sender=MIKE, group=G_A):
        self.db.whatsapp_messages.rows.append({
            "_id": f"w{len(self.db.whatsapp_messages.rows)}", "group_id": group,
            "project_id": "proj_a", "company_id": CO_A, "sender": sender,
            "body": body, "created_at": at})


class WhatIsChased(_Base):

    def test_the_morning_nudge(self):
        it = _item(self.db)
        self.chase(_et(8, 35))
        (r,) = self.rows()
        self.assertEqual(r["slot"], "morning")
        self.assertEqual(r["kind"], "group")
        self.assertEqual(r["group_id"], G_A)
        self.assertEqual(r["text"], "@Mike Rivera morning — this is due today:\n"
                                    "“I'll send the stair RFI today”")
        self.assertEqual(r["mention_jid"], f"{MIKE}@c.us")
        self.assertEqual(r["reply_to"], it["evidence"]["message_id"])   # quotes it
        self.assertEqual(r["reason"], "Due today (today); owner confirmed; "
                                      "no update since it was said at 7:00.")

    def test_a_request_with_a_confirmed_owner(self):
        _item(self.db, type="request", quote="@Mike send the RFI by Thursday",
              due={"due_text": "by Thursday"})
        self.chase(_et(8, 35))
        self.assertEqual(len(self.rows()), 1)

    def test_a_mapped_sender_is_chased(self):
        _item(self.db, owner={"kind": "sender_map", "id": "sm1", "name": "Jose",
                              "jid": "123@lid"})
        self.chase(_et(8, 35))
        self.assertTrue(self.rows()[0]["text"].startswith("@Jose morning"))

    def test_gc_staff_are_never_chased(self):
        """Subs only: a company user, or someone mapped in People to "GC
        team", is never nudged in a group (and so never reaches the admin
        DM)."""
        for label, owner in {
                "a company user": {"kind": "user", "id": "u_kev", "sub_company": None},
                "mapped GC team": {"kind": "sender_map", "id": "sm9", "sub_company": "GC team"},
                "mapped gc  TEAM": {"kind": "sender_map", "id": "sm9", "sub_company": " gc  TEAM "},
        }.items():
            self.db.attention_items.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            it = _item(self.db, owner=owner)
            self.assertEqual(wa_chase.skip_reason(it, date.fromisoformat(DAY)), "gc_staff", label)
            for h, m in ((8, 35), (12, 35), (15, 5), (16, 5)):
                self.chase(_et(h, m))
            self.assertEqual(self.rows(), [], label)

    def test_skipped(self):
        cases = {
            "possibly": dict(owner={"possibly": True}),
            "unresolved": dict(owner={"status": "unresolved", "kind": "none", "id": None}),
            "a worker, not a user or mapped": dict(owner={"kind": "worker", "id": "w1"}),
            "no explicit due date": dict(due={"due_text": "", "due_at": None}),
            "a date the code could not read": dict(due={"due_text": "soon", "due_at": None}),
            "due another day": dict(due={"due_at": "2026-10-09"}),
            "flagged for review": dict(needs_review=True),
            "the item marked Wrong": dict(review={"verdict": "wrong"}),
            "an older prompt (att-v1.1)": dict(extraction={"prompt_version": "att-v1.1"}),
            "no prompt version": dict(extraction={"prompt_version": None}),
            "an unclear-update review entry": dict(type="update_review"),
            "a question": dict(type="question"),
            "an issue": dict(type="issue"),
            "done": dict(status="done"),
            "cancelled": dict(status="cancelled"),
            "possibly done": dict(status="possibly_done"),
        }
        for label, over in cases.items():
            self.db.attention_items.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            _item(self.db, **over)
            self.chase(_et(8, 35))
            self.assertEqual(self.rows(), [], label)

    def test_rescheduled_to_today_is_chased(self):
        _item(self.db, status="rescheduled")
        self.chase(_et(8, 35))
        self.assertEqual(len(self.rows()), 1)


class TheGroup(_Base):

    def test_not_in_a_group_with_the_bot_off_or_unlinked(self):
        from tests.test_whatsapp_attention import G_OFF
        _item(self.db, group_id=G_OFF)                      # bot switched off
        _item(self.db, group_id="120363000000000999@g.us")  # not linked
        self.chase(_et(8, 35))
        self.assertEqual(self.rows(), [])


    def test_a_group_bound_to_two_projects_is_not_chased(self):
        self.db.whatsapp_groups.rows.append({
            "_id": "gdup", "wa_group_id": G_A, "group_name": "Dup",
            "project_id": "proj_b", "company_id": "co_b", "active": True})
        _item(self.db)
        self.chase(_et(8, 35))
        self.assertEqual(self.rows(), [])


class AnAskAndItsAnswer(_Base):
    """A request and the commitment answering it are one thing to chase:
    the commitment (its words, its date)."""

    def test_both_due_today_one_entry(self):
        ask = _item(self.db, type="request", quote="@Mike send the RFI today")
        _item(self.db, quote="on it", parent_id=ask["_id"])
        self.chase(_et(8, 35))
        (r,) = self.rows()
        self.assertEqual([i["quote"] for i in r["items"]], ["on it"])

    def test_the_answer_moved_the_ask_is_not_chased_on_its_old_date(self):
        ask = _item(self.db, type="request", quote="@Mike send the RFI today")
        _item(self.db, quote="on it", parent_id=ask["_id"], status="rescheduled",
              due={"due_text": "Monday", "due_at": "2026-10-12"})
        self.chase(_et(8, 35))
        self.assertEqual(self.rows(), [])

    def test_a_tentative_answer_does_not_hide_the_ask(self):
        for over in (dict(needs_review=True), dict(owner={"possibly": True}),
                     dict(status="possibly_done")):
            self.db.attention_items.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            ask = _item(self.db, type="request", quote="@Mike send the RFI today")
            _item(self.db, quote="ok", parent_id=ask["_id"], **over)
            self.chase(_et(8, 35))
            self.assertEqual([i["quote"] for i in self.rows()[0]["items"]],
                             ["@Mike send the RFI today"], over)

    def test_a_closed_answer_does_not_hide_the_ask(self):
        ask = _item(self.db, type="request", quote="@Mike send the RFI today")
        _item(self.db, quote="on it", parent_id=ask["_id"], status="cancelled")
        self.chase(_et(8, 35))
        self.assertEqual([i["quote"] for i in self.rows()[0]["items"]],
                         ["@Mike send the RFI today"])


class TheSlots(_Base):

    def test_the_day(self):
        _item(self.db)
        self.chase(_et(8, 20))
        self.assertEqual(self.rows(), [])                      # before 8:30
        self.chase(_et(8, 35))
        self.chase(_et(8, 40))                                 # same slot: once
        self.assertEqual(len(self.rows("morning")), 1)
        self.chase(_et(12, 35))
        mid = self.rows("midday")[0]
        self.assertEqual(mid["text"], "@Mike Rivera checking in — still on for today?\n"
                                      "“I'll send the stair RFI today”")
        self.assertIn("since the 8:35 nudge", mid["reason"])
        self.chase(_et(15, 5))
        self.assertEqual(self.rows("eod")[0]["text"].split("\n")[0],
                         "@Mike Rivera end of day — did this get done?")
        self.chase(_et(16, 5))
        dm = self.rows("admin_dm")[0]
        self.assertEqual(dm["kind"], "admin_dm")
        self.assertEqual(dm["to"], ["Ana Admin"])
        self.assertEqual(dm["text"],
                         "Mike Rivera hasn't answered on this, due today in Main St Project:\n"
                         "“I'll send the stair RFI today”\n"
                         "Nudged in the group at 8:35, 12:35 and 3:05.")
        self.chase(_et(18, 0))
        self.assertEqual(len(self.rows()), 4)

    def test_a_missed_slot_is_not_sent_late(self):
        _item(self.db)
        self.chase(_et(12, 40))
        self.assertEqual([r["slot"] for r in self.rows()], ["midday"])

    def test_said_after_a_slot_waits_for_the_next(self):
        _item(self.db, evidence={"sent_at": _et(10, 0)})
        self.chase(_et(10, 5))
        self.assertEqual(self.rows(), [])
        self.chase(_et(12, 35))
        self.assertEqual([r["slot"] for r in self.rows()], ["midday"])

    def test_no_admin_dm_without_the_end_of_day_nudge(self):
        _item(self.db)
        self.chase(_et(16, 5))
        self.assertEqual(self.rows(), [])

    def test_not_on_another_day(self):
        _item(self.db, due={"due_at": "2026-10-07"})          # yesterday's
        self.chase(_et(8, 35))
        self.assertEqual(self.rows(), [])


class StopConditions(_Base):

    def test_the_owner_says_anything_in_the_group(self):
        _item(self.db)
        self.chase(_et(8, 35))
        self.say("on it", _et(9, 10))
        self.chase(_et(12, 35))
        self.chase(_et(15, 5))
        self.chase(_et(16, 5))
        self.assertEqual([r["slot"] for r in self.rows()], ["morning"])

    def test_the_owner_in_another_group_does_not_stop_it(self):
        _item(self.db)
        self.chase(_et(8, 35))
        self.say("on it", _et(9, 10), group=G_2)
        self.chase(_et(12, 35))
        self.assertEqual(len(self.rows("midday")), 1)

    def test_someone_else_talking_does_not_stop_it(self):
        _item(self.db)
        self.chase(_et(8, 35))
        self.say("any news?", _et(9, 10), sender=PAT)
        self.chase(_et(12, 35))
        self.assertEqual(len(self.rows("midday")), 1)

    def test_owner_message_before_the_first_nudge_does_not_stop_it(self):
        _item(self.db)
        self.say("morning all", _et(8, 0))
        self.chase(_et(8, 35))
        self.assertEqual(len(self.rows("morning")), 1)

    def test_a_state_change_after_a_nudge(self):
        for kind in ("rescheduled", "possibly_done", "part_done", "flag"):
            self.db.attention_items.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            it = _item(self.db)
            self.chase(_et(8, 35))
            it["history"].append({"id": "e1", "kind": kind, "at": _et(10, 0)})
            self.chase(_et(12, 35))
            self.assertEqual([r["slot"] for r in self.rows()], ["morning"], kind)

    def test_done_or_cancelled_after_a_nudge(self):
        for status in ("done", "cancelled"):
            self.db.attention_items.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            it = _item(self.db)
            self.chase(_et(8, 35))
            it["status"] = status
            self.chase(_et(12, 35))
            self.assertEqual(len(self.rows()), 1, status)

    def test_rescheduled_to_another_day(self):
        it = _item(self.db)
        self.chase(_et(8, 35))
        it.update(status="rescheduled", due={"due_text": "Monday", "due_at": "2026-10-12"})
        self.chase(_et(12, 35))
        self.assertEqual(len(self.rows()), 1)


class Batching(_Base):

    def test_one_message_per_owner_per_group_per_slot(self):
        _item(self.db, quote="I'll send the stair RFI today")
        _item(self.db, quote="Shop drawings by Thursday",
              due={"due_text": "by Thursday"})
        self.chase(_et(8, 35))
        (r,) = self.rows()
        self.assertEqual(r["text"], "@Mike Rivera morning — these are due today:\n"
                                    "“I'll send the stair RFI today”\n"
                                    "“Shop drawings by Thursday”")
        self.assertEqual(len(r["item_ids"]), 2)
        self.assertEqual(r["reason"], "Due today (by Thursday, today); owner confirmed; no update.")

    def test_other_owners_and_other_groups_are_separate(self):
        _item(self.db)
        _item(self.db, quote="I'll do the lift today", group_id=G_2)
        _item(self.db, quote="Panels today", owner={"id": "u_pm", "name": "Pat PM",
                                                    "jid": f"{PAT}@c.us"},
              evidence={"sender": PAT})
        self.chase(_et(8, 35))
        self.assertEqual(len(self.rows()), 3)

    def test_a_batched_admin_dm_lists_each_nudge_once(self):
        _item(self.db)
        _item(self.db, quote="Anchors today")
        for t in (_et(8, 35), _et(12, 35), _et(15, 5), _et(16, 5)):
            self.chase(t)
        dm = self.rows("admin_dm")[0]
        self.assertEqual(dm["text"].split("\n")[0],
                         "Mike Rivera hasn't answered on these 2, due today in Main St Project:")
        self.assertTrue(dm["text"].endswith("Nudged in the group at 8:35, 12:35 and 3:05."))

    def test_an_owner_already_nudged_this_slot_gets_no_second_message(self):
        _item(self.db)
        self.chase(_et(8, 35))
        _item(self.db, quote="Anchors today", evidence={"sent_at": _et(8, 0)})
        self.chase(_et(8, 45))
        self.assertEqual(len(self.rows("morning")), 1)
        self.chase(_et(12, 35))
        (mid,) = self.rows("midday")
        self.assertEqual(len(mid["item_ids"]), 2)           # both, in one message


class AlertHours(_Base):

    def _window(self, window):
        self.db.notification_preferences.rows.append({
            "_id": "np1", "user_id": None, "project_id": "proj_a", "scope": "project",
            "whatsapp_project": {"send_window": window}})

    def test_a_slot_before_the_window_waits_for_it(self):
        self._window({"mode": "custom", "start": "09:00", "end": "17:00"})
        _item(self.db)
        self.chase(_et(8, 35))
        self.assertEqual(self.rows(), [])
        self.chase(_et(9, 5))
        self.assertEqual([r["slot"] for r in self.rows()], ["morning"])

    def test_after_the_window_nothing(self):
        self._window({"mode": "custom", "start": "09:00", "end": "15:30"})
        _item(self.db)
        for t in (_et(9, 5), _et(12, 35), _et(15, 5), _et(16, 5)):
            self.chase(t)
        self.assertEqual([r["slot"] for r in self.rows()], ["morning", "midday", "eod"])

    def test_work_hours_and_anytime(self):
        for window in ({"mode": "work_hours"}, {"mode": "anytime"}):
            self.db.notification_preferences.rows = []
            self.db[wa_chase.COLLECTION].rows = []
            self.db.attention_items.rows = []
            self._window(window)
            _item(self.db)
            self.chase(_et(16, 5))
            self.chase(_et(15, 5))
            self.chase(_et(16, 5))
            self.assertEqual([r["slot"] for r in self.rows()], ["eod", "admin_dm"], window)


class Weekends(_Base):
    """Saturday and Sunday: only with the project's "Chase on weekends" on
    (default off). All four slots."""

    SAT = "2026-10-10"

    def _on(self, value=True):
        self.db.notification_preferences.rows.append({
            "_id": "npw", "user_id": None, "project_id": "proj_a", "scope": "project",
            "whatsapp_project": {"chase_weekends": value}})

    def _day(self):
        for t in (_et(8, 35, day=10), _et(12, 35, day=10), _et(15, 5, day=10),
                  _et(16, 5, day=10)):
            self.chase(t)
        return [r["slot"] for r in self.rows()]

    def test_off_by_default_no_slot_runs(self):
        _item(self.db, due={"due_text": "Saturday", "due_at": self.SAT},
              evidence={"sent_at": _et(7, 0, day=10)})
        self.assertEqual(self._day(), [])

    def test_on_all_four_slots_run(self):
        self._on()
        _item(self.db, due={"due_text": "Saturday", "due_at": self.SAT},
              evidence={"sent_at": _et(7, 0, day=10)})
        self.assertEqual(self._day(), ["morning", "midday", "eod", "admin_dm"])

    def test_sunday_too(self):
        _item(self.db, due={"due_text": "Sunday", "due_at": "2026-10-11"},
              evidence={"sent_at": _et(7, 0, day=11)})
        self.chase(_et(8, 35, day=11))
        self.assertEqual(self.rows(), [])
        self._on()
        self.chase(_et(12, 35, day=11))
        self.assertEqual([r["slot"] for r in self.rows()], ["midday"])

    def test_weekdays_ignore_the_switch(self):
        self._on(False)
        _item(self.db)
        self.chase(_et(8, 35))                                 # Thursday
        self.assertEqual(len(self.rows()), 1)

    def test_the_rule(self):
        from datetime import date
        self.assertTrue(wa_chase.chases_on(date(2026, 10, 9), {}))
        self.assertFalse(wa_chase.chases_on(date(2026, 10, 10), {}))
        self.assertFalse(wa_chase.chases_on(date(2026, 10, 11), {"chase_weekends": False}))
        self.assertTrue(wa_chase.chases_on(date(2026, 10, 11), {"chase_weekends": True}))


class TheWeekendSwitch(_Base):

    def test_admin_sets_it_and_the_view_shows_it(self):
        with patch.object(server, "db", self.db):
            v = _run(server.get_project_whatsapp_settings("proj_a", current_user=ADMIN))
            self.assertIs(v["chase_weekends"], False)
            v = _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"chase_weekends": True}, current_user=ADMIN))
            self.assertIs(v["chase_weekends"], True)
            for bad in ({"chase_weekends": "yes"}, {"chase_weekend": True}):
                with self.assertRaises(HTTPException) as e:
                    _run(server.patch_project_whatsapp_alerts("proj_a", bad,
                                                              current_user=ADMIN))
                self.assertEqual(e.exception.status_code, 422)
            with self.assertRaises(HTTPException) as e:
                _run(server.patch_project_whatsapp_alerts(
                    "proj_a", {"chase_weekends": False}, current_user=PM))
            self.assertEqual(e.exception.status_code, 403)
        settings = self.db.notification_preferences.rows[0]["whatsapp_project"]
        self.assertIs(settings["chase_weekends"], True)


class The588Migration(_Base):

    def _projects(self, *rows):
        self.db.projects.rows = [dict(r) for r in rows]

    def _migrate(self):
        with patch.object(server, "db", self.db):
            return _run(server._chase_weekends_for_588_thomas())

    def _value(self, pid):
        for r in self.db.notification_preferences.rows:
            if r.get("project_id") == pid:
                return (r.get("whatsapp_project") or {}).get("chase_weekends")
        return None

    THOMAS = {"_id": "p588", "company_id": CO_A, "name": "588 Thomas",
              "address": "588 Thomas S Boyland St, Brooklyn, NY 11212"}
    WALWORTH = {"_id": "p8", "company_id": CO_A, "name": "8 Walworth",
                "address": "8 Walworth St, Brooklyn, NY"}

    def test_on_for_588_only(self):
        self._projects(self.THOMAS, self.WALWORTH)
        self.assertEqual(self._migrate(), "p588")
        self.assertIs(self._value("p588"), True)
        self.assertIsNone(self._value("p8"))

    def test_turning_it_off_in_the_app_sticks(self):
        self._projects(self.THOMAS)
        self._migrate()
        self.db.notification_preferences.rows[0]["whatsapp_project"]["chase_weekends"] = False
        self.assertIsNone(self._migrate())
        self.assertIs(self._value("p588"), False)

    def test_an_existing_row_without_the_switch_gets_it(self):
        self._projects(self.THOMAS)
        self.db.notification_preferences.rows.append({
            "_id": "np588", "user_id": None, "project_id": "p588", "scope": "project",
            "whatsapp_project": {"gc_group_id": "g", "violation_alerts": False}})
        self.assertEqual(self._migrate(), "p588")
        wp = self.db.notification_preferences.rows[0]["whatsapp_project"]
        self.assertIs(wp["chase_weekends"], True)
        self.assertEqual((wp["gc_group_id"], wp["violation_alerts"]), ("g", False))
        self.assertEqual(len(self.db.notification_preferences.rows), 1)

    def test_a_false_saved_meanwhile_is_not_overwritten(self):
        # The write itself is conditional: a row carrying false is left alone,
        # and no second row is made.
        self._projects(self.THOMAS)
        self.db.notification_preferences.rows.append({
            "_id": "np588", "user_id": None, "project_id": "p588", "scope": "project",
            "whatsapp_project": {"chase_weekends": False}})
        self.assertIsNone(self._migrate())
        self.assertIs(self._value("p588"), False)
        self.assertEqual(len(self.db.notification_preferences.rows), 1)

    def test_two_matches_or_a_deleted_one_set_nothing(self):
        self._projects(self.THOMAS, {**self.THOMAS, "_id": "p588b"})
        self.assertIsNone(self._migrate())
        self._projects({**self.THOMAS, "is_deleted": True})
        self.assertIsNone(self._migrate())
        self.assertEqual(self.db.notification_preferences.rows, [])

    def test_it_runs_at_startup(self):
        import inspect
        self.assertIn("_chase_weekends_for_588_thomas()",
                      inspect.getsource(server.run_whatsapp_startup_migrations))


class KillSwitch(_Base):

    def test_off(self):
        _item(self.db)
        with patch.dict(os.environ, {"WA_CHASE_DISABLED": "1"}):
            report = self.chase(_et(8, 35))
        self.assertTrue(report["disabled"])
        self.assertEqual(self.rows(), [])


class TheScreen(_Base):

    def test_list_review_precision(self):
        _item(self.db)
        _item(self.db, quote="Panels today", owner={"id": "u_pm", "name": "Pat PM",
                                                    "jid": f"{PAT}@c.us"})
        self.chase(_et(8, 35))
        with patch.object(server, "db", self.db):
            out = _run(server.get_project_chase("proj_a", current_user=ADMIN))
            self.assertTrue(out["shadow_mode"])
            self.assertEqual(len(out["entries"]), 2)
            e = out["entries"][0]
            for k in ("at", "owner", "items", "text", "reason", "slot", "group_name"):
                self.assertIn(k, e)
            blob = json.dumps(out)
            self.assertNotIn(MIKE, blob)
            self.assertNotIn(PAT, blob)
            self.assertNotIn("@c.us", blob)
            self.assertIsNone(out["precision"]["precision"])
            ids = [x["id"] for x in out["entries"]]
            v = _run(server.review_project_chase("proj_a", ids[0], {"verdict": "correct"},
                                                 current_user=ADMIN))
            self.assertEqual(v["verdict"], "correct")
            _run(server.review_project_chase("proj_a", ids[1], {"verdict": "wrong"},
                                             current_user=ADMIN))
            out = _run(server.get_project_chase("proj_a", current_user=ADMIN))
        p = out["precision"]
        self.assertEqual((p["correct"], p["wrong"], p["precision"]), (1, 1, 0.5))
        self.assertEqual(p["by_slot"]["morning"]["precision"], 0.5)

    def test_admins_of_this_company_only(self):
        _item(self.db)
        self.chase(_et(8, 35))
        rid = self.rows()[0]["_id"]
        with patch.object(server, "db", self.db):
            for user, code in ((PM, 403), (ADMIN_B, 404)):
                with self.assertRaises(HTTPException) as e:
                    _run(server.get_project_chase("proj_a", current_user=user))
                self.assertEqual(e.exception.status_code, code)
                with self.assertRaises(HTTPException) as e:
                    _run(server.review_project_chase("proj_a", rid, {"verdict": "wrong"},
                                                     current_user=user))
                self.assertEqual(e.exception.status_code, code)
            with self.assertRaises(HTTPException) as e:
                _run(server.review_project_chase("proj_a", rid, {"verdict": "maybe"},
                                                 current_user=ADMIN))
            self.assertEqual(e.exception.status_code, 422)
        self.assertIsNone(self.rows()[0]["review"])


class Wiring(unittest.TestCase):

    def test_scheduled_and_never_sends_or_calls_a_model(self):
        import inspect
        src = Path(server.__file__).read_text()
        self.assertIn("id='whatsapp_chase_shadow'", src)
        body = inspect.getsource(server._chase_tick) + inspect.getsource(wa_chase)
        for banned in ("send_whatsapp", "_waapi_post", "_dm_llm", "_attention_llm",
                       "openai", "chat.completions"):
            self.assertNotIn(banned, body)

    def test_not_in_the_webhook(self):
        import inspect
        self.assertNotRegex(inspect.getsource(server._process_whatsapp_message),
                            r"\b_chase_\w+\(")


class TheRules(unittest.TestCase):

    def test_slots(self):
        C = wa_chase
        self.assertIsNone(C.current_slot(_et(8, 29)))
        self.assertEqual(C.current_slot(_et(8, 30)), "morning")
        self.assertEqual(C.current_slot(_et(12, 29)), "morning")
        self.assertEqual(C.current_slot(_et(13, 0)), "midday")
        self.assertEqual(C.current_slot(_et(14, 59)), "midday")
        self.assertEqual(C.current_slot(_et(15, 0)), "eod")
        self.assertEqual(C.current_slot(_et(15, 59)), "eod")
        self.assertEqual(C.current_slot(_et(16, 0)), "admin_dm")
        self.assertEqual(C.current_slot(_et(23, 0)), "admin_dm")

    def test_long_quotes_are_cut(self):
        q = wa_chase.quote({"evidence": {"quote": "x " * 300}})
        self.assertLessEqual(len(q), wa_chase.QUOTE_MAX)
        self.assertTrue(q.endswith("…"))


if __name__ == "__main__":
    unittest.main()
