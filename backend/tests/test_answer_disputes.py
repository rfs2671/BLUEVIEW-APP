"""Answer disputes (lib/answer_disputes.py, L6 step 2: capture only).

  * The detector: "that's wrong" / "eso está mal" is a dispute; a question
    or a sentence that merely contains the word is not.
  * WhatsApp DM: a reply-to on a bot answer (its WhatsApp id is on the
    answer_log row), or a dispute right after one, is recorded against that
    row; the reply is exactly "Flagged for review"; the brain never runs.
  * Per company: a dispute names an answer of the disputer's company only.
  * One row per (answer, person); the second dispute gets the same reply.
  * App: POST /api/answers/{id}/dispute answers {"status": "Flagged for
    review"} and nothing else; another company's answer is a 404.
"""

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

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from lib import answer_disputes as ad  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_dm_brain import FakeLLM, resp, text, use  # noqa: E402
from tests.test_dm_subs_on_site import _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _optin  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx, _Wire  # noqa: E402

CO_B = "co_b"
CHAT = f"{ADMIN_PHONE}@c.us"
#: What a person sees, and nothing more. Review words never appear.
_REVIEW_FIELD = re.compile(r"\b(?:approved?|denied|deny|reviewer|pending|review_status)\b", re.I)


def _run(coro):
    return asyncio.run(coro)


class _IdWire(_Wire):
    """WaAPI that answers each send-message with the id it went out as."""

    def __init__(self):
        super().__init__()
        self.n = 0

    async def post_raw(self, url, payload, headers):
        self.calls.append(payload)
        if "message" in payload:
            self.n += 1
            mid = f"BOT{self.n}"
            return 200, {"data": {"status": "success", "data": {"id": {
                "fromMe": True, "remote": CHAT, "id": mid,
                "_serialized": f"true_{CHAT}_{mid}"}}}}, None
        return 200, {"status": "success"}, None


def _payload(body, mid, *, quoted_id=None, quoted_body=None, from_bot=True):
    msg = {"id": {"id": mid, "fromMe": False, "_serialized": f"false_{CHAT}_{mid}"},
           "from": CHAT, "body": body, "type": "chat"}
    if quoted_id or quoted_body:
        msg["quotedMsg"] = {"body": quoted_body or "", "type": "chat",
                            "id": {"fromMe": from_bot, "id": quoted_id or ""}}
        if quoted_id:
            msg["contextInfo"] = {"stanzaId": quoted_id}
    return {"event": "message", "data": {"message": msg}}


# ══════════════════════════════════════════════════════════════════════════
# The detector
# ══════════════════════════════════════════════════════════════════════════

class Detector(unittest.TestCase):
    POSITIVE = [
        "that's wrong", "That’s wrong.", "thats not right", "Not right", "incorrect",
        "Incorrect!", "no it's not", "No, it's not", "nope that's not it", "wrong",
        "that is wrong", "That is incorrect", "you're wrong", "no that's wrong",
        "not correct", "that's not true", "totally wrong", "wrong answer",
        "that's wrong, the door is 3'-6\"", "Incorrect - it's on A-102",
        "that's not what the plans say",
        # Spanish
        "eso está mal", "Está mal", "mal", "eso no es correcto", "no es correcto",
        "incorrecto", "no es cierto", "no es verdad", "no es así", "te equivocas",
        "estás equivocado", "es falso", "No, eso está mal", "eso está mal, es el piso 3",
    ]
    NEGATIVE = [
        "", "is that right?", "is that wrong?", "what's wrong with the pump?",
        "not right now", "the wrong door was installed", "something is wrong with the pump",
        "no", "no thanks", "ok", "what about level 2?", "thanks", "that's right",
        "correct", "no, that's right", "that's not wrong", "nothing wrong here",
        "it's not ready", "no it's not ready yet", "wrong job lol", "false alarm",
        "how many on site", "¿está mal?", "que esta mal?", "es correcto", "no, es correcto",
        "mal tiempo hoy", "la puerta está mal instalada", "Update on 588",
        "that's wrong " + "x" * 300,
    ]

    def test_disputes(self):
        for t in self.POSITIVE:
            self.assertTrue(ad.is_dispute(t), t)

    def test_not_disputes(self):
        for t in self.NEGATIVE:
            self.assertFalse(ad.is_dispute(t), t)

    def test_a_bot_question_or_marker_is_not_disputable(self):
        self.assertFalse(ad.disputable({"final_text": "Which job? 1) 588 2) Walworth",
                                        "path": "menu"}))
        self.assertFalse(ad.disputable({"final_text": "Which job do you mean?", "path": "brain"}))
        self.assertTrue(ad.disputable({"final_text": "31 on site.\nWant the names?"}))
        self.assertFalse(ad.disputable({"final_text": "[cancelled]"}))
        self.assertFalse(ad.disputable(None))
        self.assertTrue(ad.disputable({"final_text": "31 on site."}))

    def test_sent_ids_are_short_and_carry_no_chat(self):
        r = {"data": {"status": "success", "data": {"id": {
            "fromMe": True, "remote": CHAT, "id": "3EB0X", "_serialized": f"true_{CHAT}_3EB0X"}}}}
        self.assertEqual(ad.sent_ids(r), ["3EB0X"])
        self.assertEqual(ad.sent_ids({"status": "success"}), [])
        self.assertEqual(ad.sent_ids(None), [])


# ══════════════════════════════════════════════════════════════════════════
# WhatsApp DM
# ══════════════════════════════════════════════════════════════════════════

ANSWER = ("588: 31 on site — Arkon Builders 17, Quality Plumbing 6, J&G 4, Power Direct 4.\n"
          "DOB: no new violations.")


class Dm(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0

    def say(self, c, payload, llm):
        before = len([p for p in c.wire.calls if "message" in p])

        async def on(ident):
            return True

        async def react(chat, mid, emoji):
            return True
        with patch.object(server, "_dm_brain_on", on), \
                patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "LLM_API_KEY", None):
            _run(server._process_whatsapp_message(payload))
        return [p["message"] for p in c.wire.calls if "message" in p][before:]

    def answer(self, c):
        llm = FakeLLM(resp(use("headcount", {"job": "588"})), resp(text(ANSWER)))
        out = self.say(c, _payload("Update on 588", "m1"), llm)
        self.assertEqual(out, [ANSWER])
        row = self.db.answer_log.rows[-1]
        self.assertEqual(row["wa_message_ids"], ["BOT1"])
        return row

    def test_a_reply_to_dispute_is_flagged_and_the_brain_never_runs(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            row = self.answer(c)
            llm = FakeLLM()
            out = self.say(c, _payload("that's wrong, call 212 555 0199", "m2",
                                       quoted_id="BOT1", quoted_body=ANSWER), llm)
        self.assertEqual(out, ["Flagged for review"])
        self.assertEqual(llm.calls, [])
        [d] = self.db[ad.COLLECTION].rows
        self.assertEqual((d["answer_log_id"], d["company_id"], d["user_id"], d["surface"],
                          d["status"]), (row["_id"], CO_A, "u_admin", "dm", "pending"))
        self.assertEqual(d["text"], "that's wrong, call […0199]")
        # The dispute is not an answer: no new answer_log row for it.
        self.assertEqual(len(self.db.answer_log.rows), 1)

    def test_a_dispute_right_after_an_answer_is_that_answer(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            row = self.answer(c)
            out = self.say(c, _payload("eso está mal", "m2"), FakeLLM())
        self.assertEqual(out, ["Flagged for review"])
        self.assertEqual([d["answer_log_id"] for d in self.db[ad.COLLECTION].rows], [row["_id"]])

    def test_a_late_dispute_with_no_reply_to_is_not_placed(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            row = self.answer(c)
            for r in self.db.answer_log.rows:
                r["created_at"] = datetime.now(timezone.utc) - timedelta(minutes=30)
            llm = FakeLLM(resp(text("Which one do you mean?")))
            out = self.say(c, _payload("that's wrong", "m2"), llm)
        self.assertEqual(out, ["Which one do you mean?"])
        self.assertEqual(self.db[ad.COLLECTION].rows, [])
        self.assertTrue(row)

    def test_a_question_goes_to_the_brain(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            self.answer(c)
            llm = FakeLLM(resp(text("Yes, from the sign-ins today.")))
            out = self.say(c, _payload("is that right?", "m2", quoted_id="BOT1",
                                       quoted_body=ANSWER), llm)
        self.assertEqual(out, ["Yes, from the sign-ins today."])
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(self.db[ad.COLLECTION].rows, [])

    def test_the_same_dispute_twice_is_one_row_and_the_same_reply(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            self.answer(c)
            one = self.say(c, _payload("that's wrong", "m2", quoted_id="BOT1",
                                       quoted_body=ANSWER), FakeLLM())
            two = self.say(c, _payload("incorrect", "m3", quoted_id="BOT1",
                                       quoted_body=ANSWER), FakeLLM())
        self.assertEqual((one, two), (["Flagged for review"], ["Flagged for review"]))
        self.assertEqual(len(self.db[ad.COLLECTION].rows), 1)

    def test_another_companys_answer_is_never_disputed(self):
        self.db.answer_log.rows.append({
            "_id": "b1", "company_id": CO_B, "user_id": "u_admin", "surface": "dm",
            "final_text": "B's answer.", "wa_message_ids": ["BOTB"],
            "created_at": datetime.now(timezone.utc)})
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            llm = FakeLLM(resp(text("Which answer do you mean.")))
            out = self.say(c, _payload("that's wrong", "m2", quoted_id="BOTB",
                                       quoted_body="B's answer."), llm)
        self.assertEqual(out, ["Which answer do you mean."])
        self.assertEqual(self.db[ad.COLLECTION].rows, [])

    def test_the_log_line_has_no_phone_and_no_words(self):
        with _Ctx(db=self.db, wire=_IdWire()) as c:
            self.answer(c)
            with self.assertLogs(server.logger, level="INFO") as logs:
                self.say(c, _payload("that's wrong", "m2", quoted_id="BOT1",
                                     quoted_body=ANSWER), FakeLLM())
        [line] = [m for m in logs.output if "[answer-dispute]" in m]
        self.assertIsNotNone(re.search(r"\[answer-dispute\] company=co_a surface=dm$", line))
        self.assertIsNone(re.search(ADMIN_PHONE[-7:], line))
        self.assertIsNone(re.search(r"that's wrong", line))


class Capture(unittest.TestCase):
    ROWS = [{"_id": "a1", "company_id": CO_A, "surface": "dm", "user_id": "u1",
             "final_text": "31 on site.", "created_at": datetime.now(timezone.utc)}]

    def test_cross_company_is_refused(self):
        db = FakeDb(answer_log=[dict(r) for r in self.ROWS])
        with patch.object(server, "db", db):
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="dm", company_id=CO_B, user_id="u9", answer_log_id="a1", text="wrong")))
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="dm", company_id=None, user_id="u9", answer_log_id="a1", text="wrong")))
            self.assertFalse(_run(server._answer_dispute_capture(
                surface="dm", company_id=CO_A, user_id=None, answer_log_id="a1", text="wrong")))
            self.assertIsNone(_run(server._answer_dispute_target(
                CO_B, "u1", {}, datetime.now(timezone.utc))))
        self.assertEqual(db[ad.COLLECTION].rows, [])

    def test_two_people_are_two_rows(self):
        db = FakeDb(answer_log=[dict(r) for r in self.ROWS])
        with patch.object(server, "db", db):
            for uid in ("u1", "u2", "u1"):
                self.assertTrue(_run(server._answer_dispute_capture(
                    surface="dm", company_id=CO_A, user_id=uid, answer_log_id="a1", text="x")))
        self.assertEqual(sorted(r["user_id"] for r in db[ad.COLLECTION].rows), ["u1", "u2"])


# ══════════════════════════════════════════════════════════════════════════
# The app
# ══════════════════════════════════════════════════════════════════════════

class App(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb(answer_log=[
            {"_id": "a1", "company_id": CO_A, "surface": "app", "user_id": "u1",
             "final_text": "The slab pour moved to Friday.",
             "created_at": datetime.now(timezone.utc)},
            {"_id": "b1", "company_id": CO_B, "surface": "app", "user_id": "u9",
             "final_text": "B.", "created_at": datetime.now(timezone.utc)}])
        self.user = {"id": "u1", "company_id": CO_A, "role": "admin"}

    def call(self, log_id, note=None, user=None):
        with patch.object(server, "db", self.db):
            return _run(server.dispute_answer(log_id, server.AnswerDisputeIn(note=note),
                                              current_user=user or self.user))

    def test_it_answers_the_status_string_only(self):
        out = self.call("a1", note="It moved to Monday")
        self.assertEqual(out, {"status": "Flagged for review"})
        self.assertIsNone(_REVIEW_FIELD.search(json.dumps(out)))
        [d] = self.db[ad.COLLECTION].rows
        self.assertEqual((d["surface"], d["text"], d["status"]), ("app", "It moved to Monday", "pending"))
        # Again: the same answer, one row.
        self.assertEqual(self.call("a1"), {"status": "Flagged for review"})
        self.assertEqual(len(self.db[ad.COLLECTION].rows), 1)

    def test_another_companys_answer_is_not_found(self):
        with self.assertRaises(HTTPException) as e:
            self.call("b1")
        self.assertEqual(e.exception.status_code, 404)
        with self.assertRaises(HTTPException) as e:
            self.call("nope")
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(self.db[ad.COLLECTION].rows, [])

    def test_no_company_is_forbidden(self):
        with self.assertRaises(HTTPException) as e:
            self.call("a1", user={"id": "u1", "company_id": None})
        self.assertEqual(e.exception.status_code, 403)
        self.assertEqual(self.db[ad.COLLECTION].rows, [])

    def test_the_memory_answer_carries_its_answer_log_id(self):
        db = FakeDb()

        async def project(pid, user):
            return CO_A

        async def answer(*a, **k):
            return {"text": "Friday.", "mode": "answer", "claims": [], "sources": []}
        with patch.object(server, "db", db), \
                patch.object(server, "_memory_project", project), \
                patch.object(server, "_memory_disabled", lambda: False), \
                patch.object(server, "_memory_answer", answer):
            out = _run(server.search_project_memory("p1", q="slab pour", answer=True,
                                                    current_user=self.user))
        self.assertEqual(out["answer"]["answer_log_id"], db.answer_log.rows[0]["_id"])
        self.assertIsNone(_REVIEW_FIELD.search(json.dumps(out, default=str)))


class Surface(unittest.TestCase):
    def test_no_writer_changes_a_dispute(self):
        """Capture only: the one write is the insert; status is never set
        after it (the operator's review is L6.4)."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        mut = re.compile(r"(?:answer_disputes|answer_disputes\.COLLECTION\])\s*\.\s*"
                         r"(update_one|update_many|replace_one|delete_one|delete_many|"
                         r"find_one_and_\w+|bulk_write)\b")
        self.assertIsNone(mut.search(src))
        self.assertEqual(len(re.findall(r"db\[answer_disputes\.COLLECTION\]\.insert_one", src)), 1)


if __name__ == "__main__":
    unittest.main()
