"""TWO WRITERS AT ONCE: nothing either wrote is lost.

588, Sun Oct 11 8:31 PM: three photos picked together were three webhooks in
the same second; each read the walkthrough, appended its photo to its own
copy of the item list and wrote that copy back -- the last write won and a
photo was on no item. Every place that did that (read a document, change an
array or a dict in Python, write the whole thing back) on a path that can run
twice at once now writes atomically ($push / $addToSet / $set on one key /
a compare-and-set) or holds a lease. Each is tested here with two writers
that really interleave: `_Yielding` makes every database call give way to the
other coroutine first, which is what a real round trip to Mongo does.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import punch, wa_chase  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

NOW = datetime(2026, 10, 12, 0, 31, tzinfo=timezone.utc)


class _YieldingCollection:
    def __init__(self, col):
        self._col = col

    def __getattr__(self, name):
        attr = getattr(self._col, name)
        if not asyncio.iscoroutinefunction(attr):
            return attr

        async def call(*a, **k):
            await asyncio.sleep(0)            # a round trip: the other writer runs
            return await attr(*a, **k)
        return call


class _Yielding:
    """FakeDb whose every call yields first."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return _YieldingCollection(getattr(self._db, name))

    def __getitem__(self, name):
        return _YieldingCollection(self._db[name])


def _both(db, *coros):
    async def go():
        return await asyncio.gather(*coros)
    with patch.object(server, "db", _Yielding(db)):
        return asyncio.run(go())


class Checklists(unittest.TestCase):

    def _db(self):
        return FakeDb(whatsapp_checklists=[{
            "_id": "c1", "company_id": "co", "group_id": "g", "project_id": "p",
            "items": [{"text": f"item {i}", "completed": False} for i in range(6)]}])

    def test_done_3_and_done_5_in_the_same_second(self):
        db = self._db()
        _both(db, server._checklist_mark_done("c1", 2, NOW, "1111"),
              server._checklist_mark_done("c1", 4, NOW, "2222"))
        items = db.whatsapp_checklists.rows[0]["items"]
        self.assertEqual([it["completed"] for it in items],
                         [False, False, True, False, True, False])
        self.assertEqual((items[2]["completed_by"], items[4]["completed_by"]), ("1111", "2222"))

    def test_two_taps_in_the_app_and_a_tick_from_the_group(self):
        db = self._db()
        user = {"_id": "u", "company_id": "co", "name": "Roy", "role": "admin"}
        _both(db,
              server.update_whatsapp_checklist_item("c1", 0, {"completed": True}, user),
              server.update_whatsapp_checklist_item("c1", 1, {"completed": True}, user),
              server._checklist_mark_done("c1", 5, NOW, "3333"))
        self.assertEqual([it["completed"] for it in db.whatsapp_checklists.rows[0]["items"]],
                         [True, True, False, False, False, True])

    def test_an_item_past_the_end_writes_nothing(self):
        db = self._db()
        _both(db, server._checklist_mark_done("c1", 9, NOW, "1111"))
        self.assertEqual(len(db.whatsapp_checklists.rows[0]["items"]), 6)


class PunchWalks(unittest.TestCase):
    """The in-process lock covers one container; the lease covers two."""

    def test_two_containers_one_walker(self):
        # Each "container" has its own in-process lock (patched apart); only
        # the lease in Mongo keeps their turns from interleaving.
        db = FakeDb(projects=[{"_id": "p588", "name": "588 Thomas St", "company_id": "co"}])
        ident = {"user_id": "u_roy", "company_id": "co", "role": "admin",
                 "user": {"_id": "u_roy"}, "projects": [{"_id": "p588", "name": "588 Thomas St"}]}

        async def nothing(*a, **k):
            return True

        async def image(parsed):
            await asyncio.sleep(0.01)
            return b"\xff\xd8" + b"\x00" * 8

        def msg(i):
            return {"has_image": True, "message_id": f"M{i}",
                    "message_id_serialized": f"false_x_M{i}"}

        class _Separate(dict):
            def setdefault(self, k, v):        # a new lock every time: no sharing
                return asyncio.Lock()
        with patch.object(server, "_PUNCH_LOCKS", _Separate()), \
                patch.object(server, "send_whatsapp_message", nothing), \
                patch.object(server, "_react_to_message", nothing), \
                patch.object(server, "download_image", image), \
                patch.object(server, "_upload_to_r2", lambda *a, **k: True):
            _both(db, *(server._punch_dm_turn(ident, "c@c.us", msg(i), f"Item {i} 4F")
                        for i in range(3)))
        (s,) = db[punch.SESSIONS].rows
        self.assertEqual(sorted(it["text"] for it in s["items"]), ["Item 0 4F", "Item 1 4F", "Item 2 4F"])
        self.assertEqual(len(s["photos"]), 3)
        self.assertEqual(db[punch.LEASES].rows, [])            # every lease given back

    def test_a_crashed_turns_lease_is_taken_over(self):
        db = FakeDb()
        db[punch.LEASES].rows.append({"_id": "walker:u", "token": "old",
                                      "expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
        (tok,) = _both(db, server._punch_lease("u", wait=1))
        self.assertTrue(tok)
        self.assertEqual(db[punch.LEASES].rows[0]["token"], tok)

    def test_a_slow_turn_is_waited_for_never_run_beside(self):
        # Codex review on #757: past a 20 s wait the next turn ran unlocked
        # beside a slow photo turn (a download can take 45 s). The holder
        # renews its lease, so the waiter waits however long it runs.
        db = FakeDb()
        log = []

        async def turn(ident, dm_chat, parsed, body, voice=None):
            log.append(("start", body))
            await asyncio.sleep(0.5 if body == "slow" else 0)     # > the lease's life
            log.append(("end", body))
            return True

        class _Separate(dict):
            def setdefault(self, k, v):        # two containers: no shared lock
                return asyncio.Lock()

        async def go():
            first = asyncio.create_task(server._punch_dm_turn({"user_id": "u"}, "c", {}, "slow"))
            await asyncio.sleep(0.05)
            await server._punch_dm_turn({"user_id": "u"}, "c", {}, "next")
            await first
        with patch.object(server, "db", db), patch.object(server, "_PUNCH_LOCKS", _Separate()), \
                patch.object(server, "_punch_dm_turn_locked", turn), \
                patch.object(punch, "LEASE_SECONDS", 0.15):
            asyncio.run(go())
        self.assertEqual(log, [("start", "slow"), ("end", "slow"), ("start", "next"), ("end", "next")])
        self.assertEqual(db[punch.LEASES].rows, [])

    def test_a_turn_past_the_longest_wait_is_not_run(self):
        db = FakeDb(**{punch.LEASES: [{"_id": "walker:u", "token": "live",
                                       "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)}]})
        ran, said = [], []

        async def turn(*a, **k):
            ran.append(1)

        async def send(chat, text, *a, **k):
            said.append(text)
        with patch.object(server, "db", db), patch.object(server, "_punch_dm_turn_locked", turn), \
                patch.object(server, "send_whatsapp_message", send), \
                patch.object(server, "PUNCH_LEASE_MAX_WAIT", 0.3), \
                patch.object(server._punch_lease, "__defaults__", (0.3,)):
            self.assertTrue(asyncio.run(server._punch_dm_turn({"user_id": "u"}, "c", {}, "x")))
        self.assertEqual(ran, [])
        self.assertIn("Send that one again", said[0])
        self.assertEqual(db[punch.LEASES].rows[0]["token"], "live")   # never taken

    def test_orphans_asked_are_added_not_replaced(self):
        db = FakeDb(**{punch.SESSIONS: [{"_id": "w", "orphans_asked": ["a"]}]})

        async def add(ids):
            await server.db[punch.SESSIONS].update_one(
                {"_id": "w"}, {"$addToSet": {"orphans_asked": {"$each": ids}}})
        _both(db, add(["b"]), add(["c", "a"]))
        self.assertEqual(sorted(db[punch.SESSIONS].rows[0]["orphans_asked"]), ["a", "b", "c"])


class ChaseNoNumber(unittest.TestCase):

    def test_two_items_of_one_owner_the_same_day(self):
        db = FakeDb()

        def item(i):
            return {"_id": f"it{i}", "company_id": "co", "project_id": "p", "group_id": "g",
                    "type": "commitment", "summary": f"thing {i}",
                    "owner": {"kind": "user", "id": "u_kev", "name": "Kevin"},
                    "due": {"due_text": "today"}, "evidence": {"message_id": f"M{i}", "quote": "q"}}
        day = NOW.date()
        _both(db, server._chase_no_number(item(1), day, NOW), server._chase_no_number(item(2), day, NOW),
              server._chase_no_number(item(1), day, NOW))          # and a repeat: once
        (row,) = db[wa_chase.COLLECTION].rows
        self.assertEqual(sorted(row["item_ids"]), ["it1", "it2"])
        self.assertEqual(len(row["items"]), 2)


class GcProposal(unittest.TestCase):

    def _db(self):
        return FakeDb(notification_preferences=[{
            "_id": "np", "user_id": None, "scope": "project", "project_id": "p", "company_id": "co",
            "whatsapp_project": {"gc_declined": ["g_old"],
                                 "gc_proposal": {"status": "pending", "group_id": "g1",
                                                 "admin_user_id": "u"}}}])

    def test_a_dm_answer_and_an_in_app_pick_at_once_one_wins(self):
        db = self._db()
        row = dict(db.notification_preferences.rows[0])
        prop = row["whatsapp_project"]["gc_proposal"]
        won = _both(db,
                    server._gc_answer(row, prop, "declined", NOW, decline="g1"),
                    server._gc_answer({"project_id": "p"}, prop, "answered_in_app", NOW))
        self.assertEqual(sorted(won), [False, True])                # exactly one
        wp = db.notification_preferences.rows[0]["whatsapp_project"]
        self.assertEqual(wp["gc_proposal"]["status"], "declined")   # the first to land
        self.assertEqual(wp["gc_proposal"]["group_id"], "g1")       # the rest of it kept
        self.assertEqual(sorted(wp["gc_declined"]), ["g1", "g_old"])  # added, not replaced

    def test_an_answered_proposal_is_never_reopened_or_overwritten(self):
        db = self._db()
        row = dict(db.notification_preferences.rows[0])
        prop = row["whatsapp_project"]["gc_proposal"]
        _both(db, server._gc_answer(row, prop, "confirmed", NOW, also={"gc_group_id": "g1"}))
        (late,) = _both(db, server._gc_answer(row, prop, "expired", NOW))
        self.assertFalse(late)
        self.assertEqual(db.notification_preferences.rows[0]["whatsapp_project"]["gc_proposal"]["status"],
                         "confirmed")


class NotificationPreferences(unittest.TestCase):

    def test_two_saves_with_different_keys_keep_both(self):
        db = FakeDb(notification_preferences=[{
            "_id": "pref", "user_id": "u", "project_id": None,
            "signal_kind_overrides": {"permit_issued": {"delivery": "immediate"}},
            "channel_routes_default": {"critical": ["email"]},
            "digest_window": {"daily_at": "07:00"}}])
        _both(db,
              server._apply_prefs_patch(user_id="u", project_id=None, body={
                  "signal_kind_overrides": {"violation_dob": {"delivery": "digest_daily"}}}),
              server._apply_prefs_patch(user_id="u", project_id=None, body={
                  "signal_kind_overrides": {"permit_expired": {"delivery": "digest_weekly"}}}))
        got = db.notification_preferences.rows[0]["signal_kind_overrides"]
        self.assertEqual(sorted(got), ["permit_expired", "permit_issued", "violation_dob"])


    def test_an_empty_stored_map_keeps_its_defaults(self):
        # Codex review on #757: {} plus a "warning" key per path lost the
        # default "critical" route.
        db = FakeDb(notification_preferences=[{
            "_id": "pref", "user_id": "u", "project_id": None,
            "signal_kind_overrides": {}, "channel_routes_default": {}, "digest_window": {}}])
        _both(db, server._apply_prefs_patch(user_id="u", project_id=None, body={
            "channel_routes_default": {"warning": ["email"]}}))
        got = db.notification_preferences.rows[0]["channel_routes_default"]
        self.assertEqual(got["critical"], ["email"])
        self.assertEqual(got["warning"], ["email"])


class TradeRoster(unittest.TestCase):

    def test_two_admins_save_at_once_neither_row_is_lost(self):
        db = FakeDb(projects=[{"_id": "p", "company_id": "co", "trade_assignments": [
            {"id": "r1", "trade": "Electrical", "company": "Power Direct"}]}])
        base = [{"trade": "Electrical", "company": "Power Direct"}]
        with patch.object(server, "to_query_id", lambda x: x):
            _both(db,
                  server._save_roster("p", base + [{"trade": "Plumbing", "company": "Good Plumbing"}]),
                  server._save_roster("p", base + [{"trade": "Painting", "company": "Pro Paint"}]))
        rows = db.projects.rows[0]["trade_assignments"]
        # Both new rows are on the roster (the later save, not listing the
        # other's row, keeps it as inactive -- never drops it).
        self.assertEqual(sorted(r["company"] for r in rows),
                         ["Good Plumbing", "Power Direct", "Pro Paint"])
        self.assertEqual(next(r for r in rows if r["company"] == "Power Direct")["id"], "r1")


if __name__ == "__main__":
    unittest.main()
