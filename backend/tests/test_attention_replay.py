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


def _naive(db):
    """Every stored datetime as motor returns it: naive, UTC."""
    def strip(v):
        if isinstance(v, datetime) and v.tzinfo is not None:
            return v.astimezone(timezone.utc).replace(tzinfo=None)
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items()}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    for name in ("whatsapp_messages", "attention_items", "whatsapp_groups"):
        rows = db[name].rows
        rows[:] = [strip(r) for r in rows]
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


    def test_an_item_changed_after_the_message_is_left_alone(self):
        # The Oct 9 "Just sent" was missed, but an Oct 10 move was applied:
        # replaying Oct 9 must not overwrite the newer state.
        db = _scene()
        door = next(i for i in db.attention_items.rows if i["_id"] == "it_door")
        oct10 = OCT9 + timedelta(days=1)
        door.update(status="rescheduled", due={"due_text": "Monday", "due_at": "2026-10-12"})
        door["history"].append({"id": "e1", "kind": "state", "from": "open",
                                "to": "rescheduled", "at": oct10, "quote": "Actually Monday"})
        with patch.object(server, "db", db):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        self.assertEqual(door["status"], "rescheduled")
        self.assertEqual(len(door["history"]), 2)
        self.assertEqual(out["items"], [])

    def test_a_change_that_keeps_the_status_is_reported(self):
        # An already-moved item moved again: still "rescheduled", a new date.
        db = _world()
        m1 = _msg(db, "I'll send the door hardware submittal tomorrow", at=OCT8, sender=MIKE)
        _item(db, "it_door", "I'll send the door hardware submittal tomorrow", OCT8, m1["message_id"])
        door = db.attention_items.rows[0]
        door["status"] = "rescheduled"
        _msg(db, "Actually give me till Tuesday", at=OCT9, sender=MIKE,
             quoted_message_id=m1["message_id"], quoted_author=f"{MIKE}@c.us")
        with patch.object(server, "db", db):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        (c,) = out["items"]
        self.assertEqual((c["from"], c["to"]), ("rescheduled", "rescheduled"))
        self.assertIn("due", c["changed"])
        self.assertIn("history", c["changed"])


class Live588DryRun(unittest.TestCase):
    """The 588 replay dry run, Oct 11: two engine bugs, these exact lines."""

    def test_a_cancel_must_name_the_items_subject(self):
        # "Never mind the load calcs" came right after the core drill question
        # and cancelled it: the message just before is not its subject.
        db = _world()
        m1 = _msg(db, "Need confirmation on core drill locations.", at=OCT8, sender=MIKE)
        db.attention_items.rows.append({
            "_id": "it_core", "company_id": CO_A, "project_id": "proj_a", "group_id": G_A,
            "type": "question", "status": "open",
            "summary": "Confirm core drill locations",
            "owner": {"kind": "none", "status": "unresolved"},
            "evidence": {"message_id": m1["message_id"], "sender": MIKE, "sent_at": OCT8,
                         "quote": "Need confirmation on core drill locations."},
            "topic": ["confirmation", "core", "drill", "location"],
            "history": [{"id": "e0", "kind": "created", "at": OCT8}],
            "extraction": {"source": "live", "prompt_version": "att-v1.2"}})
        _msg(db, "Never mind the load calcs, owner changed scope",
             at=OCT8 + timedelta(minutes=3), sender=MIKE)
        with patch.object(server, "db", db):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        self.assertEqual(db.attention_items.rows[0]["status"], "open")
        self.assertEqual(out["items"], [])

    def test_the_cancel_rule_itself(self):
        from lib import wa_attention_state as st
        core = {"id": "c", "type": "question", "status": "open", "requester": MIKE,
                "key": "K1", "topic": st.topic_terms("Need confirmation on core drill locations.")}
        upd = {"kind": "cancel", "sender": MIKE, "previous_key": "K1", "reply_key": ""}

        def run(text, **kw):
            own = st.topic_terms(text)
            return st.decide({**upd, "terms": own, "own_terms": own, **kw}, [core])
        self.assertEqual(run("Never mind the load calcs, owner changed scope"), [])
        self.assertEqual(run("Never mind the load calcs", reply_key="K1"), [])
        # A bare "never mind" right after it, or one naming it: cancelled.
        self.assertEqual(run("Never mind")[0]["to"], "cancelled")
        self.assertEqual(run("Never mind the core drill locations")[0]["to"], "cancelled")
        # Codex, #742: every phrase the classifier reads as a cancel is the
        # cancel, not a subject -- bare, these call off the ask just before.
        for bare in ("Hold off", "Hold off on that", "Olvídalo", "Farges es",
                     "Scope changed", "Nvm"):
            self.assertEqual(st.classify(bare), {"kind": "cancel"}, bare)
            self.assertEqual(st.cancel_subject(bare), set(), bare)
            got = st.decide({**upd, "terms": st.topic_terms(bare),
                             "own_terms": st.topic_terms(bare), "body": bare}, [core])
            self.assertEqual(got[0]["to"], "cancelled", bare)
        body = "Never mind the load calcs, owner changed scope"
        self.assertEqual(st.decide({**upd, "terms": st.topic_terms(body),
                                    "own_terms": st.topic_terms(body), "body": body}, [core]), [])

    def test_a_reply_by_its_quoted_words_closes_the_door_hardware(self):
        # "Just sent, check ur email" was a reply to the door hardware ask, but
        # WaAPI sent only the quoted words: quoted_body, no quoted_message_id
        # (stored before the webhook matched them).
        db = _world()
        m1 = _msg(db, "I'll send the door hardware submittal tomorrow", at=OCT8, sender=MIKE)
        _item(db, "it_door", "I'll send the door hardware submittal tomorrow", OCT8,
              m1["message_id"])
        _msg(db, "cool", at=OCT8 + timedelta(hours=1), sender="17185550999")
        _msg(db, "Just sent, check ur email", at=OCT9, sender=MIKE,
             quoted_body="I'll send the door hardware submittal tomorrow")
        with patch.object(server, "db", db):
            out = asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        self.assertEqual(db.attention_items.rows[0]["status"], "done")
        (c,) = out["items"]
        self.assertEqual((c["id"], c["to"], c["because"]),
                         ("it_door", "done", "Just sent, check ur email"))


class QuotedWordsOrder(unittest.TestCase):
    """Codex, #742: receipt order is not send order."""

    def _replay(self, quoted_at, reply_at, quoted_ts, reply_ts):
        db = _world()
        m1 = _msg(db, "I'll send the door hardware submittal tomorrow", at=quoted_at,
                  sender=MIKE, timestamp=quoted_ts)
        _item(db, "it_door", "I'll send the door hardware submittal tomorrow", quoted_ts,
              m1["message_id"])
        _msg(db, "Just sent, check ur email", at=reply_at, sender=MIKE, timestamp=reply_ts,
             quoted_body="I'll send the door hardware submittal tomorrow")
        with patch.object(server, "db", db):
            asyncio.run(server._attention_replay_state("proj_a", OCT8 - timedelta(days=1)))
        return db.attention_items.rows[0]["status"]

    def test_stored_in_the_same_millisecond(self):
        t = OCT9
        self.assertEqual(self._replay(t, t, t - timedelta(minutes=5), t), "done")

    def test_webhooks_out_of_order(self):
        # The quoted message's webhook landed 2 minutes after the reply's.
        self.assertEqual(self._replay(OCT9 + timedelta(minutes=2), OCT9,
                                      OCT9 - timedelta(minutes=5), OCT9), "done")

    def test_a_later_message_with_those_words_is_not_what_it_quotes(self):
        # Sent AFTER the reply (WhatsApp time), within the slack: no link.
        self.assertEqual(self._replay(OCT9 + timedelta(minutes=2), OCT9,
                                      OCT9 + timedelta(minutes=1), OCT9), "open")


class TestCleanup(unittest.TestCase):
    """--dismiss-open-before: one-time test cleanup of what is still open."""

    def _scene(self):
        db = _naive(_scene())                 # it_door (Oct 8), it_stair (Oct 9), both open
        door = next(i for i in db.attention_items.rows if i["_id"] == "it_door")
        stair = next(i for i in db.attention_items.rows if i["_id"] == "it_stair")
        door["created_at"] = OCT8.replace(tzinfo=None)
        stair["created_at"] = (OCT9 + timedelta(hours=2)).replace(tzinfo=None)
        done = dict(door, _id="it_done", status="done", history=list(door["history"]))
        late = dict(door, _id="it_late", status="open", type="request",
                    created_at=datetime(2026, 10, 12, 14, 0), history=list(door["history"]))
        db.attention_items.rows += [done, late]
        return db

    def _run(self, db, *args):
        buf = io.StringIO()
        with patch.object(server, "db", db), redirect_stdout(buf):
            code = asyncio.run(replay.main_async(replay.argparse.Namespace(
                project="proj_a", since=None, dismiss_open_before="2026-10-11",
                apply="--apply" in args)))
        return code, buf.getvalue()

    def test_dry_run_counts_and_writes_nothing(self):
        db = self._scene()
        code, out = self._run(db)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("created before 2026-10-11: 2 would be dismissed", out)
        self.assertIn("by status: open 2", out)
        self.assertIn("by type: commitment 2", out)
        self.assertEqual({i["_id"]: i["status"] for i in db.attention_items.rows},
                         {"it_door": "open", "it_stair": "open", "it_done": "done",
                          "it_late": "open"})

    def test_apply_dismisses_only_what_is_open_and_older(self):
        db = self._scene()
        code, out = self._run(db, "--apply")
        self.assertEqual(code, 0)
        self.assertIn("2 dismissed", out)
        rows = {i["_id"]: i for i in db.attention_items.rows}
        self.assertEqual({k: v["status"] for k, v in rows.items()},
                         {"it_door": "dismissed", "it_stair": "dismissed", "it_done": "done",
                          "it_late": "open"})
        door = rows["it_door"]
        self.assertEqual((door["review"]["verdict"], door["review"]["reason"],
                          door["dismissed_reason"], door["excluded_from_metrics"]),
                         ("dismissed", "test cleanup", "test cleanup", True))
        last = door["history"][-1]
        self.assertEqual((last["kind"], last["from"], last["to"], last["note"]),
                         ("state", "open", "dismissed", "test cleanup"))
        # Again: nothing left to dismiss.
        code, out = self._run(db, "--apply")
        self.assertIn(": 0 dismissed", out)

    def test_left_out_of_precision_and_chase(self):
        from lib import wa_attention, wa_attention_state, wa_chase
        db = self._scene()
        self._run(db, "--apply")
        rows = {i["_id"]: i for i in db.attention_items.rows}
        self.assertNotIn("commitment", wa_attention.precision([rows["it_door"], rows["it_stair"]]))
        self.assertEqual(wa_attention_state.state_precision([rows["it_door"]]), {})
        self.assertEqual(wa_chase.skip_reason(rows["it_door"], OCT9.date()), "status")
        # An admin's own Dismiss still shows in the dismissed column.
        admin = dict(rows["it_late"], review={"verdict": "dismissed"})
        self.assertEqual(wa_attention.precision([admin])["request"]["dismissed"], 1)

    def test_needs_a_date(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            replay.main(["--project", "proj_a"])


class TheScript(unittest.TestCase):

    def _run(self, db, *args):
        buf = io.StringIO()
        with patch.object(server, "db", db), redirect_stdout(buf):
            code = asyncio.run(replay.main_async(replay.argparse.Namespace(
                project="proj_a", since="2026-10-08", dismiss_open_before=None,
                apply="--apply" in args)))
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

    def test_production_rows_are_replayed(self):
        # Live, 588 since Oct 9: "replayed: 0" over ~60 messages. Motor hands
        # back NAIVE datetimes (UTC); the dry run's in-memory copy compared
        # them with the aware --since and matched nothing.
        db = _naive(_scene())
        code, out = self._run(db)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"replayed: [1-9]")
        self.assertIn("open → done", out)

    def test_apply_writes(self):
        db = _scene()
        code, out = self._run(db, "--apply")
        self.assertEqual(code, 0)
        self.assertIn("APPLIED", out)
        self.assertEqual(next(i for i in db.attention_items.rows if i["_id"] == "it_door")["status"],
                         "done")


if __name__ == "__main__":
    unittest.main()
