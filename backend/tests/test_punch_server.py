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
from lib import punch  # noqa: E402
from scripts import punch_dry_run as dry  # noqa: E402

DIR = Path(dry.__file__).parent / "dry_run_punch"
WALK = DIR / "walk_588_2026_10.json"


def _sc():
    return json.loads(WALK.read_text(encoding="utf-8"))


def _upto(sc, text):
    """The scenario cut right after the DM line `text` (no group, no asks)."""
    i = next(k for k, l in enumerate(sc["dm"]) if l.get("text") == text)
    sc["dm"] = [{k: v for k, v in l.items() if k != "expect"} for l in sc["dm"][:i + 1]]
    sc["group"], sc["dm_after"], sc["expect"] = [], [], {}
    return sc


def _run(sc):
    return asyncio.run(dry.run(sc))


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
        res = _run(_upto(_sc(), "done"))
        self.assertEqual(res["reacts"], ["👍"] * 13)       # 12 photos + the voice after one
        self.assertEqual(len(res["uploads"]), 12)
        self.assertTrue(all(k.startswith("wa-photos/p588/") for k in res["uploads"]))
        # Only the start and the draft were said.
        said = [l for l in res["transcript"] if l.startswith("  ") and l.strip()]
        self.assertTrue(any("(draft)" in l for l in said))

    def test_nothing_is_made_or_posted_before_send(self):
        res = _run(_upto(_sc(), "send"))
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["group_posts"], [])

    def test_the_draft_is_marked_and_grouped(self):
        res = _run(_upto(_sc(), "done"))
        text = "\n".join(res["transcript"])
        self.assertIn("588 Thomas St · walkthrough · 12 items (draft)", text)
        self.assertIn("2 need a trade", text)
        self.assertIn("📷🎤 piso 6 falta pintura en el pasillo", text)
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
        sc = _upto(_sc(), "electrical Mon, everything else Fri")
        db, proj = dry.world(sc)
        db.notification_preferences.rows[0]["whatsapp_project"].pop("gc_group_id")
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            res = _run(sc)
        self.assertEqual(res["rows"], [])
        self.assertIn("no WhatsApp group linked", "\n".join(res["transcript"]))

    def test_sent_items_are_chased_like_any_confirmed_request(self):
        sc = _upto(_sc(), "electrical Mon, everything else Fri")
        db, proj = dry.world(sc)
        with patch.object(dry, "world", lambda _sc: (db, proj)):
            _run(sc)
        att = db.attention_items.rows
        self.assertEqual(len(att), 11)
        for a in att:
            self.assertEqual((a["type"], a["status"]), ("request", "open"))
            self.assertEqual(a["owner"]["status"], "resolved")
            self.assertTrue(a["owner"]["jid"].endswith("@c.us"))
            self.assertRegex(a["due"]["due_at"], r"^\d{4}-\d{2}-\d{2}")
            self.assertGreaterEqual(a["extraction"]["prompt_version"], "att-v1.2")
            self.assertFalse(a.get("needs_review"))
            self.assertEqual(a["group_id"], dry.GROUP)


class Closing(unittest.TestCase):

    def _sent(self):
        sc = _upto(_sc(), "electrical Mon, everything else Fri")
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
        self.assertEqual(len(out["items"]), 3)
        self.assertEqual(out["floors"], ["3", "4", "5", "6"])
        self.assertIn("electrical", out["trades"])
        self.assertEqual(out["statuses"], ["open", "ready_to_check", "closed"])
        self.assertNotIn("1718555", json.dumps(out))
        out = self._call(db, server.get_project_punch, "p588", floor="", trade="paint",
                         status="", current_user=self.ADMIN)
        self.assertEqual({i["trade"] for i in out["items"]}, {"paint"})

    def test_only_admins_edit_and_the_chase_follows(self):
        db = self._db()
        pid = db[punch.COLLECTION].rows[0]["pid"]
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.patch_project_punch, "p588", pid, {"status": "closed"},
                       current_user=self.PM)
        self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException) as e:
            self._call(db, server.patch_project_punch, "p588", pid, {"assignee": "x"},
                       current_user=self.ADMIN)
        self.assertEqual(e.exception.status_code, 422)
        out = self._call(db, server.patch_project_punch, "p588", pid,
                         {"status": "closed", "floor": "7"}, current_user=self.ADMIN)
        self.assertEqual((out["status"], out["floor"]), ("closed", "7"))
        att = next(a for a in db.attention_items.rows if a["punch_id"] == pid)
        self.assertEqual(att["status"], "done")

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


if __name__ == "__main__":
    unittest.main()
