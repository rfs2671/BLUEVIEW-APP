"""Group answer disputes (owner's ruling: groups are the main field use).

  * asker_key: who asked, as a keyed HMAC of the FULL WhatsApp sender id;
    stable per sender, different across senders and across keys, and
    nothing in it reads back to the phone. The key is ANSWER_ASKER_SALT,
    else derived from JWT_SECRET; never a constant.
  * A group answer row carries asker_key and asker_last4 (as before).
  * A group message that REPLIES TO a bot answer and says it is wrong:
    one dispute row, keyed by (answer, asker_key); the reply is exactly
    "Flagged for review", sent as a reply to it; the group agent never
    runs. The same person twice: one row. Two people: two rows.
  * A reply-to that is not a dispute goes to the agent exactly as before.
  * Another company's answer is refused (logged `refused`), never recorded.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import answer_disputes as ad  # noqa: E402
from lib import answer_log  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    CO_A, CP_PHONE, GROUP, PM_PHONE, _Ctx, _db, _run, _Wire,
)

CO_B = "co_b"
ANSWER = "588: 31 on site today, Arkon Builders 17, Quality Plumbing 6."
#: What a person sees, and nothing more. Review words never appear.
_REVIEW_FIELD = re.compile(r"\b(?:approved?|denied|deny|reviewer|pending|review_status)\b", re.I)


class _GroupIdWire(_Wire):
    """WaAPI that answers each group send-message with the id it went out as."""

    def __init__(self):
        super().__init__()
        self.n = 0

    async def post_raw(self, url, payload, headers):
        self.calls.append(payload)
        if "message" in payload:
            self.n += 1
            mid = f"BOT{self.n}"
            return 200, {"data": {"status": "success", "data": {"id": {
                "fromMe": True, "remote": GROUP, "id": mid,
                "_serialized": f"true_{GROUP}_{mid}"}}}}, None
        return 200, {"status": "success"}, None


def _msg(body, mid, phone=PM_PHONE, *, quoted_id=None, quoted_body=None, from_bot=True):
    """A typed group message as WaAPI posts it; optionally a reply-to."""
    author = f"{phone}@c.us"
    m = {"id": {"id": mid, "fromMe": False, "remote": GROUP, "participant": author,
                "_serialized": f"false_{GROUP}_{mid}_{author}"},
         "from": GROUP, "author": author, "body": body, "type": "chat",
         "hasMedia": False, "notifyName": "Roy",
         "timestamp": int(datetime.now(timezone.utc).timestamp()),
         "_data": {"type": "chat", "body": body, "notifyName": "Roy"}}
    if quoted_id or quoted_body:
        m["hasQuotedMsg"] = True
        m["_data"]["quotedMsg"] = {"type": "chat", "fromMe": from_bot,
                                   "body": quoted_body or ""}
        if quoted_id:
            m["_data"]["quotedStanzaID"] = quoted_id
    return {"event": "message", "instanceId": "inst", "data": {"message": m}}


def _group_db():
    cfg = server._default_bot_config()
    cfg["features"]["material_detection"] = False
    return _db(whatsapp_groups=[{
        "_id": "g1", "wa_group_id": GROUP, "company_id": CO_A,
        "project_id": "proj_a", "active": True,
        "linked_at": datetime.now(timezone.utc) - timedelta(days=1),
        "bot_config": cfg}])


# ══════════════════════════════════════════════════════════════════════════
# asker_key
# ══════════════════════════════════════════════════════════════════════════

class AskerKey(unittest.TestCase):
    K1, K2 = b"k" * 32, b"j" * 32

    def test_stable_per_sender_and_only_whitespace_and_case_normalised(self):
        a = answer_log.asker_key(f"{PM_PHONE}@c.us", self.K1)
        self.assertEqual(a, answer_log.asker_key(f"  {PM_PHONE}@C.US ", self.K1))
        self.assertEqual(len(a), 64)
        # The FULL id: the same digits on another domain are another sender.
        self.assertNotEqual(a, answer_log.asker_key(f"{PM_PHONE}@lid", self.K1))

    def test_differs_across_senders_and_keys(self):
        a = answer_log.asker_key(f"{PM_PHONE}@c.us", self.K1)
        self.assertNotEqual(a, answer_log.asker_key(f"{CP_PHONE}@c.us", self.K1))
        self.assertNotEqual(a, answer_log.asker_key(f"{PM_PHONE}@c.us", self.K2))

    def test_no_phone_digit_run_in_it(self):
        for phone in (PM_PHONE, CP_PHONE):
            k = answer_log.asker_key(f"{phone}@c.us", self.K1)
            self.assertIsNone(re.search(phone[-7:], k))
            self.assertIsNone(re.search(phone, k))

    def test_no_sender_or_no_key_is_none(self):
        self.assertIsNone(answer_log.asker_key("", self.K1))
        self.assertIsNone(answer_log.asker_key(f"{PM_PHONE}@c.us", None))
        self.assertIsNone(answer_log.asker_key(f"{PM_PHONE}@c.us", b""))

    def _server_key(self, env):
        with patch.dict(os.environ, env, clear=False), \
                patch.object(server, "_ASKER_KEY", None), \
                patch.object(server, "_ASKER_KEY_READ", False):
            if "ANSWER_ASKER_SALT" not in env:
                os.environ.pop("ANSWER_ASKER_SALT", None)
            return server._answer_asker_key(f"{PM_PHONE}@c.us")

    def test_the_server_key_is_the_salt_else_derived_from_jwt_secret(self):
        sid = f"{PM_PHONE}@c.us"
        salted = self._server_key({"ANSWER_ASKER_SALT": "salt-one"})
        self.assertEqual(salted, answer_log.asker_key(sid, b"salt-one"))
        self.assertNotEqual(salted, self._server_key({"ANSWER_ASKER_SALT": "salt-two"}))
        derived = self._server_key({})
        want = hmac.new(server.JWT_SECRET.encode("utf-8"), b"answer-asker-key-v1",
                        hashlib.sha256).digest()
        self.assertEqual(derived, answer_log.asker_key(sid, want))
        # Not keyed by the bare JWT secret, nor by the label alone.
        self.assertNotEqual(derived, answer_log.asker_key(sid, server.JWT_SECRET.encode()))
        self.assertNotEqual(derived, answer_log.asker_key(sid, b"answer-asker-key-v1"))

    def test_asker_key_is_in_the_content_hash(self):
        self.assertIn("asker_key", answer_log.HASHED)
        row = {"surface": "group", "question": "q", "final_text": "a", "asker_key": "x"}
        self.assertNotEqual(answer_log.content_hash(row),
                            answer_log.content_hash(dict(row, asker_key="y")))
        # A row written before the field still verifies as it was hashed.
        old = {"surface": "group", "question": "q", "final_text": "a"}
        body = {k: answer_log._canon(old.get(k)) for k in answer_log.HASHED if k != "asker_key"}
        self.assertEqual(answer_log.content_hash(old), answer_log._sha(
            json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)))


# ══════════════════════════════════════════════════════════════════════════
# The live group path
# ══════════════════════════════════════════════════════════════════════════

class GroupDisputes(unittest.TestCase):
    def setUp(self):
        self.db = _group_db()
        self.agent_calls = []

    def say(self, c, payload, reply=None):
        async def agent(**kw):
            self.agent_calls.append(kw)
            return reply

        async def live(group_id, sender):
            return False

        async def react(chat, mid, emoji):
            return True
        before = len(c.wire.calls)
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_is_in_bot_session", live), \
                patch.object(server, "_react_to_message", react):
            _run(server._process_whatsapp_message(payload))
        return [p for p in c.wire.calls[before:]
                if p.get("chatId") == GROUP and "message" in p]

    def answer(self, c):
        out = self.say(c, _msg("levelog how many on site at 588", "Q1"), reply=ANSWER)
        self.assertEqual([p["message"] for p in out], [ANSWER])
        self.agent_calls.clear()
        [row] = [r for r in self.db.answer_log.rows if r["surface"] == "group"]
        self.assertEqual(row["wa_message_ids"], ["BOT1"])
        return row

    def disputes(self):
        return self.db[ad.COLLECTION].rows

    def test_a_group_answer_row_has_asker_key_and_last4(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            row = self.answer(c)
        self.assertEqual(row["asker_last4"], PM_PHONE[-4:])
        self.assertEqual(row["asker_key"], server._answer_asker_key(f"{PM_PHONE}@c.us"))
        self.assertEqual(row["group_id"], GROUP)
        self.assertEqual(row["content_hash"], answer_log.content_hash(row))
        self.assertIsNone(re.search(PM_PHONE, json.dumps(row, default=str)))

    def test_a_reply_to_dispute_is_flagged_and_the_agent_never_runs(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            row = self.answer(c)
            out = self.say(c, _msg("that's wrong", "Q2", quoted_id="BOT1",
                                   quoted_body=ANSWER), reply="should not run")
        self.assertEqual([p["message"] for p in out], ["Flagged for review"])
        self.assertEqual(out[0]["replyToMessageId"],
                         f"false_{GROUP}_Q2_{PM_PHONE}@c.us")
        self.assertEqual(self.agent_calls, [])
        [d] = self.disputes()
        key = server._answer_asker_key(f"{PM_PHONE}@c.us")
        self.assertEqual((d["_id"], d["answer_log_id"], d["company_id"], d["surface"],
                          d["asker_key"], d["asker_last4"], d["group_id"], d["status"]),
                         (ad.dispute_id(row["_id"], key), row["_id"], CO_A, "group", key,
                          PM_PHONE[-4:], GROUP, "pending"))
        self.assertIsNone(d["user_id"])
        self.assertIsNone(re.search(PM_PHONE, json.dumps(d, default=str)))
        # The dispute is not an answer: still one group answer row.
        self.assertEqual(len([r for r in self.db.answer_log.rows if r["surface"] == "group"]), 1)

    def test_a_quoted_text_match_without_the_id_is_that_answer(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            row = self.answer(c)
            out = self.say(c, _msg("incorrect", "Q2", quoted_body=ANSWER))
        self.assertEqual([p["message"] for p in out], ["Flagged for review"])
        self.assertEqual([d["answer_log_id"] for d in self.disputes()], [row["_id"]])

    def test_the_same_person_twice_is_one_row(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            one = self.say(c, _msg("that's wrong", "Q2", quoted_id="BOT1", quoted_body=ANSWER))
            two = self.say(c, _msg("not right", "Q3", quoted_id="BOT1", quoted_body=ANSWER))
        self.assertEqual([p["message"] for p in one + two],
                         ["Flagged for review", "Flagged for review"])
        self.assertEqual(len(self.disputes()), 1)
        self.assertEqual(self.agent_calls, [])

    def test_two_people_are_two_rows(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            self.say(c, _msg("that's wrong", "Q2", quoted_id="BOT1", quoted_body=ANSWER))
            self.say(c, _msg("eso está mal", "Q3", CP_PHONE, quoted_id="BOT1",
                             quoted_body=ANSWER))
        rows = self.disputes()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(r["asker_last4"] for r in rows),
                         sorted([PM_PHONE[-4:], CP_PHONE[-4:]]))
        self.assertEqual(len({r["asker_key"] for r in rows}), 2)

    def test_a_reply_to_that_is_not_a_dispute_goes_to_the_agent(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            out = self.say(c, _msg("what about the roof", "Q2", quoted_id="BOT1",
                                   quoted_body=ANSWER), reply="Roof crew is 4.")
        self.assertEqual([p["message"] for p in out], ["Roof crew is 4."])
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.disputes(), [])

    def test_a_dispute_word_without_a_reply_to_is_not_placed(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            self.say(c, _msg("levelog that's wrong", "Q2"), reply="Which answer?")
        self.assertEqual(self.disputes(), [])
        self.assertEqual(len(self.agent_calls), 1)

    def test_another_companys_answer_is_refused(self):
        self.db.answer_log.rows.append({
            "_id": "b1", "company_id": CO_B, "surface": "group", "group_id": GROUP,
            "final_text": "B's answer.", "wa_message_ids": ["BOTB"],
            "created_at": datetime.now(timezone.utc)})
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            with self.assertLogs(server.logger, level="INFO") as logs:
                out = self.say(c, _msg("that's wrong", "Q2", quoted_id="BOTB",
                                       quoted_body="B's answer."), reply="Which answer?")
        self.assertEqual(self.disputes(), [])
        self.assertEqual([p["message"] for p in out], ["Which answer?"])
        [line] = [m for m in logs.output if "[answer-dispute]" in m]
        self.assertIsNotNone(re.search(r"\[answer-dispute\] refused company=co_a surface=group$",
                                       line))

    def test_the_log_line_has_no_phone_key_or_words(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            with self.assertLogs(server.logger, level="INFO") as logs:
                self.say(c, _msg("that's wrong", "Q2", quoted_id="BOT1", quoted_body=ANSWER))
                self.say(c, _msg("incorrect", "Q3", quoted_id="BOT1", quoted_body=ANSWER))
        lines = [m for m in logs.output if "[answer-dispute]" in m]
        self.assertEqual(len(lines), 2)
        self.assertIsNotNone(re.search(r"\[answer-dispute\] company=co_a surface=group$", lines[0]))
        self.assertIsNotNone(re.search(
            r"\[answer-dispute\] company=co_a surface=group duplicate=true$", lines[1]))
        key = server._answer_asker_key(f"{PM_PHONE}@c.us")
        for line in logs.output:
            self.assertIsNone(re.search(PM_PHONE[-7:], line))
            self.assertIsNone(re.search(key, line))
        for line in lines:
            self.assertIsNone(re.search(r"that's wrong", line))

    def test_nothing_review_like_is_sent(self):
        with _Ctx(db=self.db, wire=_GroupIdWire()) as c:
            self.answer(c)
            out = self.say(c, _msg("that's wrong", "Q2", quoted_id="BOT1", quoted_body=ANSWER))
            out += self.say(c, _msg("that's wrong", "Q3", quoted_id="BOT1", quoted_body=ANSWER))
        self.assertEqual(len(out), 2)
        for p in out:
            self.assertEqual(p["message"], ad.REPLY)
            self.assertIsNone(_REVIEW_FIELD.search(json.dumps(p)))


class Capture(unittest.TestCase):
    def test_a_group_dispute_needs_the_same_group(self):
        from tests._fake_mongo import FakeDb
        db = FakeDb(answer_log=[{"_id": "a1", "company_id": CO_A, "surface": "group",
                                 "group_id": GROUP, "final_text": "31 on site.",
                                 "created_at": datetime.now(timezone.utc)}])
        key = answer_log.asker_key(f"{PM_PHONE}@c.us", b"k" * 32)
        with patch.object(server, "db", db):
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="group", company_id=CO_A, answer_log_id="a1", text="wrong",
                asker_key=key, group_id="120363000000000999@g.us")))
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="group", company_id=CO_A, answer_log_id="a1", text="wrong",
                asker_key=None, group_id=GROUP)))
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="group", company_id=CO_B, answer_log_id="a1", text="wrong",
                asker_key=key, group_id=GROUP)))
            self.assertTrue(_run(server._answer_dispute_capture(
                surface="group", company_id=CO_A, answer_log_id="a1", text="wrong",
                asker_key=key, group_id=GROUP)))
        self.assertEqual([r["_id"] for r in db[ad.COLLECTION].rows], [ad.dispute_id("a1", key)])


if __name__ == "__main__":
    unittest.main()
