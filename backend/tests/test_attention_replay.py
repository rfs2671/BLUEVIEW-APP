"""One-time cleanup: re-run the attention state engine over a project's
messages since a date (server._attention_replay_state, scripts/
attention_replay.py).

Pinned: an item left open by an older engine is closed by the "done / sent"
reply after it ("Just sent, check ur email"); an item said AFTER that reply is
not touched; the dry run writes nothing; --apply writes; nothing is sent;
nothing new is extracted.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from scripts import attention_replay as replay  # noqa: E402
from tests.test_whatsapp_attention import CO_A, G_A, MIKE, _msg, _world  # noqa: E402

OCT8 = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
OCT9 = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)


def _item(db, iid, quote, at, mid):
    db.attention_items.rows.append({
        "_id": iid, "company_id": CO_A, "project_id": "proj_a", "group_id": G_A,
        "type": "commitment", "status": "open", "summary": quote,
        "owner": {"kind": "user", "id": "u_mike", "name": "Mike Rivera", "status": "resolved",
                  "jid": f"{MIKE}@c.us"},
        "due": {"due_text": "tomorrow", "due_at": "2026-10-10"},
        "evidence": {"message_id": mid, "quote": quote, "sent_at": at, "sender": MIKE},
        "topic": ["door", "hardware"], "history": [{"id": "e0", "kind": "created", "at": at}],
        "extraction": {"source": "live", "prompt_version": "att-v1.2"}})


def _scene():
    db = _world()
    m1 = _msg(db, "I'll send the door hardware submittal tomorrow", at=OCT8, sender=MIKE)
    _item(db, "it_door", "I'll send the door hardware submittal tomorrow", OCT8, m1["message_id"])
    # A WhatsApp reply to the ask (what links it, live as now).
    _msg(db, "Just sent, check ur email", at=OCT9, sender=MIKE,
         quoted_message_id=m1["message_id"], quoted_author=f"{MIKE}@c.us")
    # Said after the reply: not what the reply was about.
    m3 = _msg(db, "I'll send the stair shop drawings Monday", at=OCT9 + timedelta(hours=2), sender=MIKE)
    _item(db, "it_stair", "I'll send the stair shop drawings Monday", OCT9 + timedelta(hours=2),
          m3["message_id"])
    return db


class TheReplay(unittest.TestCase):

    def test_an_old_open_item_is_closed_by_the_reply_after_it(self):
        db = _scene()
        sent = []

        async def no_send(*a, **k):
            sent.append(a)
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", no_send):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        status = {i["_id"]: i["status"] for i in db.attention_items.rows}
        self.assertEqual(status["it_door"], "done")
        self.assertEqual(status["it_stair"], "open")          # said after the reply
        (c,) = out["items"]
        self.assertEqual((c["id"], c["from"], c["to"]), ("it_door", "open", "done"))
        self.assertEqual(c["because"], "Just sent, check ur email")
        self.assertEqual(sent, [])
        self.assertEqual(len(db.attention_items.rows), 2)     # nothing new extracted

    def test_running_it_twice_changes_nothing_more(self):
        db = _scene()
        with patch.object(server, "db", db):
            asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
            again = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        self.assertEqual(again["items"], [])
        door = next(i for i in db.attention_items.rows if i["_id"] == "it_door")
        self.assertEqual(sum(1 for e in door["history"] if e.get("to") == "done"), 1)

    def test_a_done_that_does_not_name_it_is_listed_not_closed(self):
        db = _world()
        m1 = _msg(db, "I'll send the door hardware submittal tomorrow", at=OCT8, sender=MIKE)
        _item(db, "it_door", "I'll send the door hardware submittal tomorrow", OCT8, m1["message_id"])
        _msg(db, "cool", at=OCT8 + timedelta(hours=1), sender="17185550999")
        _msg(db, "Just sent, check ur email", at=OCT9, sender=MIKE)        # not a reply
        with patch.object(server, "db", db):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        self.assertEqual(out["items"], [])
        self.assertEqual(db.attention_items.rows[0]["status"], "open")
        (h,) = out["open_with_done_after"]
        self.assertEqual((h["id"], h["said"]), ("it_door", "Just sent, check ur email"))


class TheScript(unittest.TestCase):

    def _run(self, db, *args):
        buf = io.StringIO()
        with patch.object(server, "db", db), redirect_stdout(buf):
            code = asyncio.run(replay.main_async(replay.argparse.Namespace(
                project="proj_a", since="2026-10-08", apply="--apply" in args)))
        return code, buf.getvalue()

    def test_dry_run_reports_and_writes_nothing(self):
        db = _scene()
        code, out = self._run(db)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("open → done", out)
        self.assertIn("Just sent, check ur email", out)
        self.assertEqual({i["_id"]: i["status"] for i in db.attention_items.rows},
                         {"it_door": "open", "it_stair": "open"})

    def test_apply_writes(self):
        db = _scene()
        code, out = self._run(db, "--apply")
        self.assertEqual(code, 0)
        self.assertIn("APPLIED", out)
        self.assertEqual(next(i for i in db.attention_items.rows if i["_id"] == "it_door")["status"],
                         "done")


if __name__ == "__main__":
    unittest.main()
