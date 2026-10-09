"""The attention / chase dry run (scripts/attention_dry_run.py), in CI.

Every shipped scenario runs through the real webhook parser, the attention
worker and the chase worker, with the model scripted from the expected
labels (what is tested is the code around the model). The real model runs
the same scenarios by hand: `railway run python scripts/attention_dry_run.py
<scenario>`. Nothing is written to a real database and nothing is sent.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from scripts import attention_dry_run as dry  # noqa: E402

DIR = Path(dry.__file__).parent / "dry_run"
SCENARIOS = sorted(p for p in DIR.glob("*.json"))


def _run(sc, scripted=True):
    out = asyncio.run(dry.run(sc, scripted=scripted))
    return out, dry.report(sc, out)


class EveryScenario(unittest.TestCase):

    def test_the_shipped_scenarios(self):
        self.assertGreaterEqual(len(SCENARIOS), 3)
        ran = 0
        for path in SCENARIOS:
            raw = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(scenario=path.name):
                if raw.get("placeholder"):
                    with self.assertRaises(dry.ScenarioError):
                        dry.load(str(path))
                    continue
                sc = dry.load(str(path))
                real_db = server.db
                out, r = _run(sc)
                self.assertIs(server.db, real_db, "server.db restored")
                self.assertEqual(r["sent"], [], "nothing sent")
                self.assertEqual(r["chase"]["missing"], [])
                self.assertEqual(r["chase"]["unexpected"], [])
                bad = [(ln["n"], ln["notes"]) for ln in r["lines"] if not ln["hard"]]
                self.assertEqual(bad, [])
                self.assertEqual(dry.exit_code(r), 0)
                ran += 1
        self.assertGreaterEqual(ran, 2)


class TheHarness(unittest.TestCase):

    def setUp(self):
        self.sc = dry.load(str(DIR / "pass3_2026_10.json"))

    def test_a_wrong_chase_expectation_fails_the_run(self):
        sc = copy.deepcopy(self.sc)
        sc["chase"]["expect"].append({"day": "2026-10-12", "slot": "morning",
                                      "owner": "P", "items": [6]})
        _out, r = _run(sc)
        self.assertEqual(len(r["chase"]["missing"]), 1)
        self.assertEqual(dry.exit_code(r), 1)
        sc = copy.deepcopy(self.sc)
        sc["chase"]["expect"] = sc["chase"]["expect"][1:]
        _out, r = _run(sc)
        self.assertEqual(len(r["chase"]["unexpected"]), 1)
        self.assertEqual(dry.exit_code(r), 1)

    def test_a_reschedule_to_the_wrong_date_is_not_hard_correct(self):
        want = {"kind": "state", "of": 6, "to": "rescheduled", "due_text": "Monday"}
        got = {"kind": "state", "of": 6, "to": "rescheduled", "also": [], "due_text": "Tuesday"}
        hard, soft, notes = dry.score_line(want, got)
        self.assertFalse(hard)
        self.assertTrue(soft)
        self.assertIn("due 'Monday' → got 'Tuesday'", notes)
        self.assertTrue(dry.score_line(want, {**got, "due_text": "Monday"})[0])

    def test_the_payload_is_waapis_and_the_webhook_parser_reads_the_reply(self):
        reply = next(m for m in self.sc["messages"] if m.get("reply_to"))
        p = dry.payload(self.sc, reply)
        data = p["data"]["message"]["_data"]
        self.assertIn("quotedStanzaID", data)
        self.assertNotIn("id", data["quotedMsg"])          # as WaAPI sends it
        parsed = server.parse_inbound_message(p, vendor="waapi")
        q = self.sc["messages"][reply["reply_to"] - 1]
        self.assertEqual(parsed["quoted_message_id"], dry._hash(self.sc, q["n"]))
        self.assertEqual(parsed["quoted_author"], dry._jid(self.sc, q["from"]))
        self.assertEqual(parsed["quoted_body"], q["text"])
        self.assertTrue(parsed["is_group"])
        self.assertEqual(parsed["sender"], dry._jid(self.sc, reply["from"]))

    def test_a_reply_with_only_its_quoted_words_is_linked_by_them(self):
        # What WaAPI sent on 2026-10-09: quotedMsg, no quotedStanzaID.
        sc = copy.deepcopy(self.sc)
        for m in sc["messages"]:
            if m.get("reply_to"):
                m["reply_shape"] = "missing"
        out, r = _run(sc)
        replies = [(m, out["rows"][m["n"]]) for m in sc["messages"] if m.get("reply_to")]
        self.assertTrue(replies)
        for m, row in replies:
            q = sc["messages"][m["reply_to"] - 1]
            self.assertEqual(row["quoted_message_id"], dry._hash(sc, q["n"]))
            self.assertEqual(row["quoted_link"], "body_match")
        self.assertEqual(r["score"]["hard"], r["score"]["lines"])
        self.assertEqual(dry.exit_code(r), 0)

    def test_the_same_words_twice_link_nothing(self):
        # "ok" quoted when two messages say "ok": no guess, no link.
        sc = {"name": "dup", "tz": "America/New_York", "project": {"name": "X"},
              "senders": {"R": {"name": "Roy Admin", "lid": "401", "user": {"role": "admin"}},
                          "P": {"name": "Pat Lee", "lid": "402"}},
              "messages": [
                  {"from": "P", "at": "2026-10-09 10:00:00", "text": "ok"},
                  {"from": "P", "at": "2026-10-09 10:05:00", "text": "ok"},
                  {"from": "R", "at": "2026-10-09 10:06:00", "text": "thanks",
                   "reply_to": 2, "reply_shape": "missing"},
                  {"from": "R", "at": "2026-10-09 10:07:00", "text": "Sunday works",
                   "reply_to": 1, "reply_shape": "missing", "quoted_text": "something else"}],
              "chase": {"days": [], "expect": []}}
        sc = dry.load_dict(sc)
        out, _r = _run(sc)
        self.assertEqual(out["rows"][3]["quoted_message_id"], "")
        self.assertEqual(out["rows"][3]["quoted_body"], "ok")
        self.assertNotIn("quoted_link", out["rows"][3])
        self.assertEqual(out["rows"][4]["quoted_message_id"], "")

    def test_only_the_last_7_days(self):
        from datetime import datetime, timedelta, timezone
        from tests._fake_mongo import FakeDb
        from unittest.mock import patch
        now = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
        db = FakeDb(whatsapp_messages=[
            {"_id": "a", "group_id": "G", "message_id": "OLD", "body": "Sure I'll get it",
             "created_at": now - timedelta(days=8)},
            {"_id": "b", "group_id": "G", "message_id": "NEW", "body": "Sure I\u2019ll get it ",
             "created_at": now - timedelta(days=1), "sender_jid": "9@lid"}])
        with patch.object(server, "db", db):
            hit = asyncio.run(server._quoted_by_body("G", "Sure I'll get it", now))
            self.assertEqual(hit["message_id"], "NEW")            # curly quote, trailing space
            db.whatsapp_messages.rows[0]["created_at"] = now - timedelta(days=2)
            self.assertIsNone(asyncio.run(server._quoted_by_body("G", "Sure I'll get it", now)))
            self.assertIsNone(asyncio.run(server._quoted_by_body("G", "  ", now)))

    def test_mentions_arrive_as_ids_in_the_text(self):
        m = self.sc["messages"][0]
        body = dry.wire_body(self.sc, m)
        self.assertTrue(body.startswith("@" + self.sc["senders"]["P"]["lid"]))
        p = dry.payload(self.sc, m)
        self.assertEqual(p["data"]["message"]["mentionedIds"], [dry._jid(self.sc, "P")])

    def test_the_real_model_needs_a_key(self):
        from unittest.mock import patch
        with patch.object(server, "OPENAI_API_KEY", None):
            with self.assertRaises(dry.ScenarioError):
                asyncio.run(dry.run(self.sc, scripted=False))

    def test_a_placeholder_exits_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "placeholder.json"
            f.write_text(json.dumps({"placeholder": True, "name": "x", "senders": {},
                                     "messages": [], "chase": {"days": [], "expect": []}}))
            self.assertEqual(dry.main([str(f)]), 2)

    def test_tagged_under_another_name(self):
        """Roy's phone shows Chris as "Patricia": the wire still carries
        Chris's id."""
        sc = dry.load(DIR / "pass4_2026_10.json")
        m = next(m for m in sc["messages"] if m["text"].startswith("@Patricia"))
        self.assertEqual(dry.wire_body(sc, m),
                         "@" + sc["senders"]["C"]["lid"] + m["text"][len("@Patricia"):])


class TheParser(unittest.TestCase):
    """WaAPI's raw data carries a reply's id and author at the top of _data."""

    def test_quoted_stanza_id_at_the_top_of_data(self):
        msg = {"id": {"fromMe": False, "id": "AAA", "_serialized": "x"},
               "from": "1203@g.us", "author": "5@lid", "body": "Actually Monday",
               "type": "chat", "timestamp": 1760000000,
               "_data": {"quotedMsg": {"type": "chat", "body": "I'll do it Friday"},
                         "quotedStanzaID": "3EB0QUOTED",
                         "quotedParticipant": {"server": "lid", "user": "7",
                                               "_serialized": "7@lid"}}}
        parsed = server.parse_inbound_message({"event": "message", "data": {"message": msg}})
        self.assertEqual((parsed["quoted_message_id"], parsed["quoted_author"],
                          parsed["quoted_body"]),
                         ("3EB0QUOTED", "7@lid", "I'll do it Friday"))
        msg["_data"]["quotedParticipant"] = "8@lid"
        parsed = server.parse_inbound_message({"event": "message", "data": {"message": msg}})
        self.assertEqual(parsed["quoted_author"], "8@lid")

    def test_the_webhook_stores_the_row_the_dry_run_stores(self):
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertIn("_store_group_message(", src)


if __name__ == "__main__":
    unittest.main()


def _line(r, n):
    return next(ln for ln in r["lines"] if ln["n"] == n)


class TheThreeGaps(unittest.TestCase):
    """Live dry runs on 2026-10-09: a handover, a close from the asking side,
    and an ack under a question."""

    def setUp(self):
        self.busy = dry.load(str(DIR / "busy_group_2026_10.json"))

    def test_an_ack_under_a_question_takes_its_date(self):
        # The real model read "can you confirm the dampers shipped tomorrow?"
        # as a question and gave it no date; "Np" under it is still due
        # tomorrow.
        sc = copy.deepcopy(dry.load(str(DIR / "pass3_2026_10.json")))
        m = sc["messages"][2]
        m["model"] = [{"type": "question", "quote": m["text"], "due_text": None}]
        m["expect"] = {"kind": "item", "type": "question"}
        out, r = _run(sc)
        self.assertEqual(_line(r, 3)["got"]["type"], "question")
        np = _line(r, 4)["got"]
        self.assertEqual((np["type"], np["due_text"], np["owner_possibly"]),
                         ("commitment", "tomorrow", True))
        it = next(i for i in out["db"].attention_items.rows if str(i["_id"]) == np["id"])
        self.assertEqual((it["due"]["due_at"], it["due"]["due_source"]), ("2026-10-10", "parent"))

    def test_the_handover_moves_the_item_and_its_chase(self):
        out, r = _run(self.busy)
        self.assertTrue(_line(r, 17)["hard"])
        it = next(i for i in out["db"].attention_items.rows
                  if i["evidence"]["message_id"] == out["rows"][3]["message_id"])
        self.assertEqual((it["owner"]["name"], it["owner"]["source"]), ("Jose Zarate", "handover"))
        self.assertEqual((it["due"]["due_text"], it["due"]["due_at"]), ("Friday", "2026-10-16"))
        h = it["history"][-1]
        self.assertEqual((h["kind"], h["owner_from"]["name"], h["owner_to"]["name"]),
                         ("handover", "Patricia Lee", "Jose Zarate"))
        # Jose's words are the handover, not a second commitment.
        self.assertFalse([i for i in out["db"].attention_items.rows
                          if i["evidence"]["message_id"] == out["rows"][17]["message_id"]])
        self.assertFalse([c for c in r["chase"]["got"] if c["owner"] == "P"])
        # Nudges quote Jose's words and reply to his message; Patricia's stay
        # the item's evidence.
        self.assertEqual(it["evidence"]["quote"], "Yes, I'll send them tomorrow AM")
        jose = out["rows"][17]["message_id"]
        rows = [c for c in out["db"]["chase_shadow"].rows if c["owner_name"] == "Jose Zarate"
                and c["day"] == "2026-10-16"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["text"], "@Jose Zarate morning — this is due today:\n"
                                          "“Patricia's out sick, I'll send the risers Friday”")
        for c in rows:
            self.assertEqual(c["items"][0]["message_id"], jose)
            if c["kind"] == "group":
                self.assertEqual(c["reply_to"], jose)

    def test_after_a_handover_only_who_took_it_on_stops_the_chase(self):
        raw = json.loads((DIR / "busy_group_2026_10.json").read_text(encoding="utf-8"))

        def with_(sender):
            sc = copy.deepcopy(raw)
            sc["messages"].append({"from": sender, "at": "2026-10-16 09:00:00",
                                   "text": "Morning all", "expect": {"kind": "none"}})
            return dry.load_dict(sc)
        # Patricia, back Friday morning, says something: Jose is still chased.
        _out, r = _run(with_("P"))
        self.assertEqual(dry.exit_code(r), 0)
        # Jose says something after the morning nudge: his chase stops.
        _out, r = _run(with_("J"))
        self.assertEqual(sorted(c["slot"] for c in r["chase"]["missing"] if c["owner"] == "J"),
                         ["admin_dm", "eod", "midday"])

    def test_a_handover_that_is_not_clear_is_flagged_and_nobody_is_chased(self):
        # Jose at another company, words that do not say what: possibly a
        # handover. Patricia's item is flagged; so is Jose's commitment.
        sc = copy.deepcopy(self.busy)
        sc["senders"]["J"]["people"]["sub_company"] = "Other Plumbing Co"
        m = sc["messages"][16]
        m["text"] = "Patricia's out sick, I'll take care of it Friday"
        m["expect"] = {"kind": "item", "type": "commitment", "owner": "J", "due_text": "Friday"}
        m["model"] = [{"type": "commitment", "quote": m["text"], "due_text": "Friday"}]
        sc["chase"]["expect"] = [e for e in sc["chase"]["expect"] if e["owner"] != "J"]
        out, r = _run(sc)
        items = out["db"].attention_items.rows
        hers = next(i for i in items if i["evidence"]["message_id"] == out["rows"][3]["message_id"])
        his = next(i for i in items if i["evidence"]["message_id"] == out["rows"][17]["message_id"])
        self.assertTrue(hers["needs_review"])
        self.assertEqual(hers["owner"]["name"], "Patricia Lee")
        self.assertEqual(hers["history"][-1]["note"], "possible_handover")
        self.assertTrue(his["needs_review"])
        self.assertEqual(his["history"][-1]["note"], "possible_handover")
        ask = next(i for i in items if i["evidence"]["message_id"] == out["rows"][1]["message_id"])
        self.assertTrue(ask["needs_review"])          # the ask her item answers, too
        self.assertFalse([c for c in r["chase"]["got"] if c["owner"] in ("P", "J")])
        self.assertEqual(dry.exit_code(r), 0)

    def test_a_sub_who_did_not_ask_cannot_close_it(self):
        sc = copy.deepcopy(self.busy)
        m = sc["messages"][27]
        m["from"] = "A"                      # Ana: a sub, asked nothing
        m["expect"] = {"kind": "none"}
        sc["chase"]["expect"] += [{"day": "2026-10-15", "slot": s, "owner": "M", "items": [7]}
                                  for s in ("morning", "midday", "eod", "admin_dm")]
        _out, r = _run(sc)
        self.assertTrue(_line(r, 28)["hard"])
        self.assertEqual(dry.exit_code(r), 0)

    def test_the_asker_closes_it_too(self):
        sc = copy.deepcopy(self.busy)
        sc["messages"][27]["from"] = "K"     # Kevin asked for the panel confirm
        _out, r = _run(sc)
        self.assertTrue(_line(r, 28)["hard"])
        self.assertEqual(dry.exit_code(r), 0)

    def test_sets_not_order_for_items_closed_together(self):
        want = {"kind": "state", "of": 1, "also": [2], "to": "done"}
        self.assertTrue(dry.score_line(want, {"kind": "state", "of": 2, "also": [1],
                                              "to": "done"})[0])
        self.assertFalse(dry.score_line(want, {"kind": "state", "of": 2, "also": [],
                                               "to": "done"})[0])
