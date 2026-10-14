"""Walkthrough -> punch list -> chase in the server: the shipped dry run
(scripts/punch_dry_run.py), the draft staying with the walker until "send",
shadow posting nothing and live posting one message per assignee with the
photos, who may close an item, the 24-hour draft reminder, and Project ->
Punch list (read, filters, admin-only edits that the chase follows)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
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
from tests import _punch_detailed  # noqa: E402
from lib import punch  # noqa: E402
from scripts import punch_dry_run as dry  # noqa: E402

DIR = Path(dry.__file__).parent / "dry_run_punch"
WALK = DIR / "walk_588_2026_10.json"


def _sc():
    return json.loads(WALK.read_text(encoding="utf-8"))


LOCS = ("{n:faucet} Apt 6C, {n:door closer} 5A, {n:stain on ceiling} 5B, "
        "{n:bathroom no light} 5D, {n:lavamanos} 4B, {n:enchufe} 4C")


def _upto(sc, text):
    """The scenario cut right after the DM line `text` (no group, no asks)."""
    i = next(k for k, l in enumerate(sc["dm"]) if l.get("text") == text)
    sc["dm"] = [{k: v for k, v in l.items() if k != "expect"} for l in sc["dm"][:i + 1]]
    sc["group"], sc["dm_after"], sc["expect"] = [], [], {}
    return sc


def _run(sc):
    return asyncio.run(dry.run(sc))


setUpModule, tearDownModule = _punch_detailed.module_hooks()


class ShippedScenarios(unittest.TestCase):

    def test_every_scenario_as_expected_and_nothing_posted(self):
        files = sorted(DIR.glob("*.json"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(f.name):
                sc = dry.load(str(f))
                res = _run(sc)
                bad = [w for ok, w in res["checks"] if not ok]
                self.assertEqual(bad, [])
                self.assertEqual(res["group_posts"], [])
                with patch("builtins.print"):
                    self.assertEqual(dry.report(res), 0)

    def test_a_placeholder_scenario_refuses_to_run(self):
        p = Path(self.id().replace(".", "_") + ".json")
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / p.name
        tmp.write_text(json.dumps({"placeholder": True, "about": "fill me"}))
        try:
            with patch("builtins.print"):
                self.assertEqual(dry.main([str(tmp)]), 2)
        finally:
            tmp.unlink()


class TheDraftStaysWithTheWalker(unittest.TestCase):

    def test_capture_is_one_thumbs_up_per_item_and_no_words(self):
        res = _run(_upto(_sc(), LOCS))           # the locations, in the draft
        self.assertEqual(res["reacts"], ["👍"] * 12)       # the 12 photos; words are answered in words
        said_all = "\n".join(res["transcript"])
        # The voice note after the wordless 12th photo: its words, for that
        # photo only (the photos since the previous text with no own words).
        self.assertIn("Got it — #12 (1 photo): 4th floor (kitchen) — Falta un enchufe", said_all)
        self.assertIn("12. 📷 Falta un enchufe en la cocina", said_all)    # the voice after one (10:46 AM: never only 👍)
        self.assertEqual(len(res["uploads"]), 12)
        self.assertTrue(all(k.startswith("wa-photos/p588/") for k in res["uploads"]))
        # Every item has a floor at least: no location question at all (Tue
        # Oct 13: a location is never a blocker); the draft.
        said = [l for l in res["transcript"] if l.startswith("  ") and l.strip()]
        self.assertEqual(sum("no location" in l or "Where " in l for l in said), 0)
        self.assertTrue(any("(draft)" in l for l in said))

    def test_nothing_is_made_or_posted_before_send(self):
        res = _run(_upto(_sc(), "send"))
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["group_posts"], [])

    def test_the_draft_is_marked_and_grouped(self):
        res = _run(_upto(_sc(), LOCS))
        text = "\n".join(res["transcript"])
        self.assertIn("588 Thomas St · walkthrough · 12 items (draft)", text)
        self.assertIn("2 have no trade — fine to send as is.", text)
        # "piso 6 … en el pasillo": its place -- a heading, floor then area.
        self.assertIn("*Floor 6 · hallway*\n  _paint_\n  3. 📷🎤 Falta pintura — paint", text)
        self.assertLess(text.index("*Floor 4*"), text.index("*Floor 5*"))


class Sending(unittest.TestCase):

    def test_live_posts_one_message_per_assignee_with_the_photos(self):
        sc = _sc()
        sc["punch_sends"] = "live"
        sc["dm"][-1]["expect"] = {"items": 11}
        sc["group"], sc["dm_after"] = [], []
        res = _run(sc)
        texts = [t for n, chat, t in res["group_posts"] if n == "send_whatsapp_message"]
        photos = [t for n, chat, t in res["group_posts"] if n == "_punch_send_photo"]
        self.assertEqual(len(texts), 4)
        self.assertTrue(all(chat == dry.GROUP for _n, chat, _t in res["group_posts"]))
        mike = next(t for t in texts if t.startswith("@Mike Rivera"))
        self.assertIn("P-588-", mike)
        self.assertIn("due Mon", mike)
        self.assertEqual(len(photos), 11)                  # 10 items' photos + 1 merged in
        self.assertTrue(all(r["send_mode"] == "live" for r in res["rows"]))

    def test_no_group_linked_keeps_the_draft(self):
        sc = _upto(_sc(), "ok")
        db, proj = dry.world(sc)
        db.notification_preferences.rows[0]["whatsapp_project"].pop("gc_group_id")
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            res = _run(sc)
        self.assertEqual(res["rows"], [])
        self.assertIn("no WhatsApp group linked", "\n".join(res["transcript"]))

    def test_sent_items_are_chased_like_any_confirmed_request(self):
        sc = _upto(_sc(), "ok")
        db, proj = dry.world(sc)
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            _run(sc)
        att = db.attention_items.rows
        self.assertEqual(len(att), 11)
        for a in att:
            self.assertEqual((a["type"], a["status"]), ("request", "open"))
            self.assertEqual(a["owner"]["status"], "resolved")
            # A phone or a WhatsApp privacy id (Ana and Luis write from one).
            self.assertRegex(a["owner"]["jid"], r"@(c\.us|lid)$")
            self.assertRegex(a["due"]["due_at"], r"^\d{4}-\d{2}-\d{2}")
            self.assertGreaterEqual(a["extraction"]["prompt_version"], "att-v1.2")
            self.assertFalse(a.get("needs_review"))
            self.assertEqual(a["group_id"], dry.GROUP)


class Closing(unittest.TestCase):

    def _sent(self):
        sc = _upto(_sc(), "ok")
        db, proj = dry.world(sc)
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            _run(sc)
        return db

    def _group(self, db, phone, text):
        msg = {"body": text, "sender": phone, "sender_jid": f"{phone}@c.us", "message_id": "gx"}
        ctx = {"company_id": dry.COMPANY, "project_id": "p588", "group_id": dry.GROUP, "cache": {}}
        with patch.object(server, "db", db):
            return asyncio.run(server._punch_group_message(msg, ctx))

    def test_a_sub_cannot_close_and_done_is_only_ready_to_check(self):
        db = self._sent()
        row = db[punch.COLLECTION].rows[0]
        self.assertFalse(self._group(db, "17185550201", f"{row['pid']} ok"))
        self.assertEqual(row["status"], "open")
        self.assertTrue(self._group(db, "17185550201", f"done {row['pid']}"))
        self.assertEqual(row["status"], "ready_to_check")
        self.assertIsNone(row["closed_by"])
        att = next(a for a in db.attention_items.rows if a["punch_id"] == row["pid"])
        self.assertEqual(att["status"], "possibly_done")   # not chased

    def test_a_stranger_saying_ok_closes_nothing(self):
        db = self._sent()
        row = db[punch.COLLECTION].rows[0]
        self.assertFalse(self._group(db, "19995550000", f"{row['pid']} ok"))
        self.assertEqual(row["status"], "open")

    def test_the_super_closes_in_a_dm_too(self):
        db = self._sent()
        row = db[punch.COLLECTION].rows[0]
        sc = _sc()
        _db, proj = dry.world(sc)
        sent = []

        async def rec(chat, text, *a, **k):
            sent.append(text)
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", rec):
            asyncio.run(server._punch_dm_turn(dry._ident(proj, sc), "17185550100@c.us",
                                              {"has_image": False, "message_id": "x"},
                                              f"{row['pid']} ok"))
        self.assertEqual(sent, [f"{row['pid']} closed."])
        self.assertEqual((row["status"], row["closed_by"]), ("closed", dry.WALKER_ID))
        att = next(a for a in db.attention_items.rows if a["punch_id"] == row["pid"])
        self.assertEqual(att["status"], "done")


class CodexRound1(unittest.TestCase):
    """Who may move an item, ids per project, live sends that fail."""

    def _sent(self):
        return Closing._sent(self)

    def test_another_subs_done_changes_nothing(self):
        db = self._sent()
        mike_row = next(r for r in db[punch.COLLECTION].rows if r["assignee"]["name"] == "Mike Rivera")
        self.assertFalse(Closing._group(self, db, "17185550202", f"done {mike_row['pid']}"))  # Jose
        self.assertFalse(Closing._group(self, db, "19995550000", f"done {mike_row['pid']}"))  # stranger
        self.assertEqual(mike_row["status"], "open")

    def test_a_company_user_who_is_not_admin_or_pm_cannot_close(self):
        db = self._sent()
        db.users.rows.append({"_id": "u_cp", "company_id": dry.COMPANY, "name": "Carl",
                              "phone": "17185550999", "role": "cp", "account_status": "approved"})
        row = db[punch.COLLECTION].rows[0]
        self.assertFalse(Closing._group(self, db, "17185550999", f"{row['pid']} ok"))
        self.assertEqual(row["status"], "open")

    def test_a_dm_verdict_needs_admin_or_pm(self):
        db = self._sent()
        row = db[punch.COLLECTION].rows[0]
        sc = _sc()
        _db, proj = dry.world(sc)
        ident = {**dry._ident(proj, sc), "role": "cp"}
        sent = []

        async def rec(chat, text, *a, **k):
            sent.append(text)
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", rec):
            asyncio.run(server._punch_dm_turn(ident, "17185550100@c.us",
                                              {"has_image": False, "message_id": "x"}, f"{row['pid']} ok"))
        self.assertIn("Only an admin or PM", sent[0])
        self.assertEqual(row["status"], "open")

    def test_stored_ids_are_scoped_to_the_project(self):
        db = self._sent()
        for r in db[punch.COLLECTION].rows:
            self.assertEqual(r["_id"], f"p588:{r['pid']}")

    def test_a_failed_live_post_is_not_called_sent_and_can_be_resent(self):
        sc = _upto(_sc(), "ok")
        sc["punch_sends"], sc["fail_posts_for"] = "live", ["Ana Ortiz"]
        db, proj = dry.world(sc)
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            res = _run(sc)
        said = "\n".join(res["transcript"])
        self.assertIn("Couldn't send the list for Ana Ortiz", said)
        self.assertIn("Reply 'resend'", said)
        self.assertNotIn("@Ana Ortiz", "\n".join(t for _n, _c, t in res["group_posts"]))
        sess = db[punch.SESSIONS].rows[0]
        self.assertEqual(sess["status"], "resend")
        self.assertEqual(len(sess["undelivered"]), 3)          # Ana's three paint items
        posts, dm = [], []

        async def ok_now(chat, text, *a, **k):
            if str(chat) == dry.GROUP:
                posts.append({"text": text, **k})
            else:
                dm.append(text)
            return True

        async def photo(group_id, key, caption):
            return True
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", ok_now), \
                patch.object(server, "_punch_send_photo", photo):
            asyncio.run(server._punch_dm_turn(dry._ident(proj, sc), "17185550100@c.us",
                                              {"has_image": False, "message_id": "r"}, "resend"))
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0]["display_text"].startswith("@Ana Ortiz"))
        # A real mention: Ana's number in the text and in mentions.
        self.assertTrue(posts[0]["text"].startswith("@17185550203 "))
        self.assertEqual(posts[0]["mentions"], ["17185550203@c.us"])
        self.assertIn("Posted in the job group, mentioning Ana Ortiz: 3 items.", dm[-1])   # where it went (11:07 PM)
        self.assertEqual((sess["status"], sess["undelivered"]), ("sent", []))


class DraftReminder(unittest.TestCase):

    def test_one_reminder_after_24_hours(self):
        from tests._fake_mongo import FakeDb
        now = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)
        db = FakeDb(**{punch.SESSIONS: [
            {"_id": "s1", "chat": "17185550100@c.us", "status": "draft", "job_name": "588 Thomas St",
             "reminded_at": None, "updated_at": now - timedelta(hours=25)},
            {"_id": "s2", "chat": "17185550101@c.us", "status": "draft", "job_name": "9 Main",
             "reminded_at": None, "updated_at": now - timedelta(hours=2)},
            {"_id": "s3", "chat": "17185550102@c.us", "status": "sent", "job_name": "1 Elm",
             "reminded_at": None, "updated_at": now - timedelta(days=3)}]})
        sent = []

        async def rec(chat, text, *a, **k):
            sent.append((chat, text))
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", rec):
            self.assertEqual(asyncio.run(server._punch_remind_tick(now)), 1)
            # Later: the other draft is now old too; the first is not reminded again.
            self.assertEqual(asyncio.run(server._punch_remind_tick(now + timedelta(hours=30))), 1)
            self.assertEqual(asyncio.run(server._punch_remind_tick(now + timedelta(hours=60))), 0)
        self.assertEqual([c for c, _t in sent], ["17185550100@c.us", "17185550101@c.us"])
        self.assertIn("588 Thomas St", sent[0][1])


class PunchListScreen(unittest.TestCase):

    ADMIN = {"id": "u_walker", "_id": "u_walker", "role": "admin", "company_id": dry.COMPANY}
    PM = {"id": "u_pm", "_id": "u_pm", "role": "pm", "company_id": dry.COMPANY}

    def _db(self):
        return Closing._sent(self)

    def _call(self, db, coro_fn, *a, **k):
        async def scope(project_id, user):
            return dry.COMPANY
        with patch.object(server, "db", db), patch.object(server, "_memory_project", scope):
            return asyncio.run(coro_fn(*a, **k))

    def test_list_filters_and_hides_phones(self):
        db = self._db()
        out = self._call(db, server.get_project_punch, "p588", floor="6", trade="", status="",
                         current_user=self.ADMIN)
        # A merge keeps the lower (stable) number: the 6B outlet (#1) took the
        # 5D light (#6), so it stays on floor 6.
        self.assertEqual(len(out["items"]), 4)
        self.assertEqual(out["floors"], ["3", "4", "5", "6"])
        self.assertIn("electrical", out["trades"])
        self.assertEqual(out["statuses"], ["open", "ready_to_check", "closed"])
        self.assertNotIn("1718555", json.dumps(out))
        out = self._call(db, server.get_project_punch, "p588", floor="", trade="paint",
                         status="", current_user=self.ADMIN)
        self.assertEqual({i["trade"] for i in out["items"]}, {"paint"})

    CP = {"id": "u_cp", "_id": "u_cp", "role": "cp", "company_id": dry.COMPANY}

    def test_only_admins_and_pms_edit_and_the_chase_follows(self):
        # As in WhatsApp ("P23 ok"): only an admin or PM closes (live 588,
        # Oct 12: the app let admins only).
        db = self._db()
        pid = db[punch.COLLECTION].rows[0]["pid"]
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.patch_project_punch, "p588", pid, {"status": "closed"},
                       current_user=self.CP)
        self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.patch_project_punch, "p588", pid, {"assignee": "x"},
                       current_user=self.ADMIN)
        self.assertEqual(e.exception.status_code, 422)
        out = self._call(db, server.patch_project_punch, "p588", pid,
                         {"status": "closed", "floor": "7"}, current_user=self.PM)
        self.assertEqual((out["status"], out["floor"]), ("closed", "7"))
        att = next(a for a in db.attention_items.rows if a["punch_id"] == pid)
        self.assertEqual(att["status"], "done")
        out = self._call(db, server.patch_project_punch, "p588", pid, {"status": "open"},
                         current_user=self.PM)                       # reopen
        self.assertEqual(out["status"], "open")
        self.assertEqual(att["status"], "open")

    def test_photo_link_is_short_lived_and_scoped(self):
        db = self._db()
        pid = next(r["pid"] for r in db[punch.COLLECTION].rows if r.get("photo_key"))
        with patch.object(server, "_presign_r2_get", lambda key, ttl: f"https://r2.invalid/{key}?ttl={ttl}"):
            out = self._call(db, server.get_project_punch_photo, "p588", pid, which="item",
                             current_user=self.PM)
        self.assertTrue(out["url"].endswith("?ttl=900"))
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.get_project_punch_photo, "other", pid, which="item",
                       current_user=self.PM)
        self.assertEqual(e.exception.status_code, 404)


    # ── Live 588, Oct 12: assignee filter, counts, detail actions ─────────

    def _list(self, db, **k):
        k = {"floor": "", "trade": "", "status": "", "assignee": "", **k}
        return self._call(db, server.get_project_punch, "p588", current_user=self.PM, **k)

    def test_status_counts_and_the_assignee_filter(self):
        db = self._db()
        rows = db[punch.COLLECTION].rows
        rows[0]["status"] = "ready_to_check"
        out = self._list(db)
        self.assertEqual(out["counts"], {"open": len(rows) - 1, "ready_to_check": 1, "closed": 0})
        self.assertTrue(out["can_act"])
        mike = next(a for a in out["assignees"] if a["name"] == "Mike Rivera")
        mine = self._list(db, assignee=mike["key"])
        want = [r["pid"] for r in rows if r["assignee"]["name"] == "Mike Rivera"]
        self.assertEqual([i["pid"] for i in mine["items"]], want)
        # The chips count under the other filters, whatever status is picked.
        self.assertEqual(sum(mine["counts"].values()), len(want))
        ready = self._list(db, status="ready_to_check")
        self.assertEqual([i["pid"] for i in ready["items"]], [rows[0]["pid"]])
        self.assertEqual(ready["counts"], out["counts"])
        self.assertNotIn("1718555", json.dumps(out))

    def test_reassign_from_the_list_only_and_the_chase_owner_follows(self):
        db = self._db()
        row = db[punch.COLLECTION].rows[0]
        people = self._call(db, server.get_project_punch_people, "p588", current_user=self.PM)
        self.assertNotIn("1718555", json.dumps(people))
        other = next(p for p in people["people"] if p["name"] not in ("", row["assignee"]["name"]))
        out = self._call(db, server.patch_project_punch, "p588", row["pid"],
                         {"assignee": other["key"]}, current_user=self.PM)
        self.assertEqual(out["assignee"]["name"], other["name"])
        self.assertEqual(out["assignee_key"], other["key"])
        self.assertEqual(out["history"][-1]["action"], "reassigned")
        att = next(a for a in db.attention_items.rows if a["punch_id"] == row["pid"])
        self.assertEqual(f"{att['owner']['kind']}:{att['owner']['id']}", other["key"])
        with self.assertRaises(HTTPException) as e:          # a checked-in worker / nobody
            self._call(db, server.patch_project_punch, "p588", row["pid"],
                       {"assignee": "worker:w1"}, current_user=self.PM)
        self.assertEqual(e.exception.status_code, 422)

    def test_change_the_due_and_the_chase_follows(self):
        db = self._db()
        row = db[punch.COLLECTION].rows[0]
        now = datetime.now(timezone.utc)
        out = self._call(db, server.patch_project_punch, "p588", row["pid"], {"due": "tomorrow"},
                         current_user=self.PM)
        self.assertEqual(out["due"], "tomorrow")
        att = next(a for a in db.attention_items.rows if a["punch_id"] == row["pid"])
        self.assertEqual(att["due"]["due_at"], out["due_at"])
        self.assertIsNotNone(out["due_at"])
        out = self._call(db, server.patch_project_punch, "p588", row["pid"], {"due": "no due date"},
                         current_user=self.PM)
        self.assertEqual((out["due"], out["due_at"]), ("", None))
        self.assertIsNone(att["due"]["due_at"])               # never chased
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.patch_project_punch, "p588", row["pid"], {"due": "someday"},
                       current_user=self.PM)
        self.assertEqual(e.exception.status_code, 422)
        self.assertTrue(now)

    def test_a_bad_field_saves_nothing_of_the_patch(self):
        # Codex review on #763: a valid assignee with a bad due was saved,
        # then the call said 422.
        db = self._db()
        row = db[punch.COLLECTION].rows[0]
        people = self._call(db, server.get_project_punch_people, "p588", current_user=self.PM)
        other = next(p for p in people["people"] if p["name"] not in ("", row["assignee"]["name"]))
        before = (dict(row["assignee"]), row.get("floor"), len(row.get("history") or []))
        for patch_ in ({"assignee": other["key"], "due": "someday"},
                       {"floor": "9", "assignee": "worker:w1"},
                       {"floor": "9", "due": "someday", "status": "closed"}):
            with self.assertRaises(HTTPException) as e:
                self._call(db, server.patch_project_punch, "p588", row["pid"], patch_,
                           current_user=self.PM)
            self.assertEqual(e.exception.status_code, 422, patch_)
            self.assertEqual((row["assignee"], row.get("floor"), len(row.get("history") or [])),
                             before, patch_)
            self.assertEqual(row["status"], "open")

    def test_every_photo_of_an_item(self):
        db = self._db()
        row = next(r for r in db[punch.COLLECTION].rows if r.get("photo_key"))
        row["extra_photos"] = ["wa-photos/p588/x/extra.jpg"]
        row["completion"] = {"photo_key": "wa-photos/p588/msg/done.jpg", "quote": "done"}
        out = self._list(db)
        self.assertEqual(next(i for i in out["items"] if i["pid"] == row["pid"])["photos"], 2)
        with patch.object(server, "_presign_r2_get", lambda key, ttl: key):
            get = lambda w: self._call(db, server.get_project_punch_photo, "p588", row["pid"],  # noqa: E731
                                       which=w, current_user=self.PM)["url"]
            self.assertEqual(get("item"), row["photo_key"])
            self.assertEqual(get("item:2"), "wa-photos/p588/x/extra.jpg")
            self.assertEqual(get("done"), "wa-photos/p588/msg/done.jpg")
            with self.assertRaises(HTTPException):
                get("item:3")

if __name__ == "__main__":
    unittest.main()
