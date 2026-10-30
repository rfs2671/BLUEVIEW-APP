"""A DRAWING-SET ANSWER IS READ BEFORE THE ASSISTANT, AND THE ASSISTANT NEVER
SAYS ONE WAS RECORDED UNLESS THE STORE DOES (Roy, 10-29, bugs 1 and 2).

What happened on 10-29 (the WhatsApp log, 588 Boyland, after /ask):
  21:21  "Q1 no"                                   -> parsed, stored. Fine.
  21:22  "Q2 it's the final roof plan so changes the original ar one"
                                                   -> the assistant: "I couldn't log it"
  21:23  "Gas change govern since it was latest.\\nQ1 no"
                                                   -> the assistant: "Q1 logged as *no*"
         (true only because of 21:21 - it never read the store)
  21:25  -> the assistant: "the set still reads back as *not decided* on both
         questions" (false for Q1: stored, applied at the next pass)

Rules under test:
  1. Every line of a message is read: "Qn YES/NO" on any line is the answer;
     "Qn <words>" is an answer to confirm (a note, and how to record it),
     never a chat message; a question already answered gets its stored state.
  2. An outgoing sentence saying an answer was logged / recorded / saved is
     replaced by the store's own words; with no store, it confirms nothing.
  3. The evidence says an answered-after-the-pass question is answered and
     applied at the next pass, never "Not decided".
  4. The DM path reads set answers before the assistant identity is resolved.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_set_questions as psq  # noqa: E402
from tests import test_the_system_never_picks_a_set as T  # noqa: E402

CHAT = "15550008154@c.us"


def _need(*names):
    """Fail by assertion, not AttributeError, on a tree without the fix."""
    missing = [n for n in names if not hasattr(psq, n) and not hasattr(server, n)]
    assert not missing, f"not built: {missing}"


def _asked():
    """The project's two questions stored and asked of the PM on record."""
    _need("_handle_set_question_message", "split_reply")
    db, wire = T._db(), T._NoWire()
    t = T.StoredOnceAskedOnce()
    t._with(db, wire, lambda: server._store_set_questions(T.PID, T._detected(), [], "op"))
    t._with(db, wire, lambda: server._ask_set_questions(T.PID, "op"))
    return db, wire, t


async def _optin(phone):
    return {"user_id": T.PM_ID, "phone": phone}


class EveryLineIsRead(unittest.TestCase):

    def test_the_three_10_29_messages(self):
        _need("split_reply")
        self.assertEqual(psq.split_reply("Q1 no"), ([("Q1", psq.EXCLUDE)], [], ""))
        self.assertEqual(psq.split_reply("Gas change govern since it was latest. \nQ1 no"),
                         ([("Q1", psq.EXCLUDE)], [], "Gas change govern since it was latest."))
        self.assertEqual(psq.split_reply("Q2 it's the final roof plan so changes the original ar one"),
                         ([], [("Q2", "it's the final roof plan so changes the original ar one")], ""))
        self.assertEqual(psq.split_reply("Yes. Gas change is the govern set"), ([], [], "Yes. Gas change is the govern set"),
                         "a bare yes names no question: never an answer here")

    def test_q1_no_on_the_second_line_is_recorded(self):
        db, wire, t = _asked()
        with patch.object(server, "_active_optin_for_phone", _optin):
            ok = t._with(db, wire, lambda: server._handle_set_question_message(
                CHAT, "Gas change govern since it was latest. \nQ1 no"))
        self.assertTrue(ok)
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual((q["code"], q["status"], q["answer"]), ("Q1", psq.ANSWERED, psq.EXCLUDE))
        self.assertEqual(len(wire.messages), 1)
        self.assertIn("not part of the filed set", wire.messages[0][1])
        self.assertTrue(any(a["action"] == "plan_set_question_note" for a in db.audit_logs.docs),
                        "the other line is kept as a note")

    def test_free_words_after_a_code_are_to_confirm_not_recorded(self):
        db, wire, t = _asked()
        with patch.object(server, "_active_optin_for_phone", _optin):
            ok = t._with(db, wire, lambda: server._handle_set_question_message(
                CHAT, "Q1 they're the second architect's, not ours"))
        self.assertTrue(ok, "handled here: the assistant never sees it")
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual(q["status"], psq.OPEN, "nothing is recorded from free words")
        self.assertEqual(len(wire.messages), 1)
        self.assertIn("Nothing is recorded for Q1", wire.messages[0][1])
        self.assertIn('"Q1 YES"', wire.messages[0][1])

    def test_an_answered_question_gets_its_stored_state(self):
        db, wire, t = _asked()
        with patch.object(server, "_active_optin_for_phone", _optin):
            t._with(db, wire, lambda: server._handle_set_question_message(CHAT, "Q1 no"))
            ok = t._with(db, wire, lambda: server._handle_set_question_message(CHAT, "q1 YES"))
        self.assertTrue(ok)
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual(q["answer"], psq.EXCLUDE, "answered once: a second reply changes nothing")
        self.assertTrue(wire.messages[-1][1].startswith("Q1 is recorded:"))
        self.assertIn("not part of the filed set", wire.messages[-1][1])

    def test_someone_not_asked_goes_on_to_normal_handling(self):
        db, wire, t = _asked()

        async def other(phone):
            return {"user_id": "someone-else", "phone": phone}
        with patch.object(server, "_active_optin_for_phone", other):
            ok = t._with(db, wire, lambda: server._handle_set_question_message(CHAT, "Q1 no"))
        self.assertFalse(ok)
        self.assertEqual(db[psq.COLLECTION].docs[0]["status"], psq.OPEN)
        self.assertEqual(wire.messages, [])


THE_2123_REPLY = ("Q1 logged as *no* — A.1.1–A.1.7 not part of the filed set. Nothing waiting "
                  "to confirm, so no change on my side.")


class NeverRecordedUnlessTheStoreSaysSo(unittest.TestCase):

    def _gate(self, db, ident):
        _need("_dm_set_answer_claims", "recorded_claims")
        t = T.StoredOnceAskedOnce()
        return t._with(db, T._NoWire(), lambda: server._dm_set_answer_claims(THE_2123_REPLY, ident))

    def test_the_10_29_reply_is_the_stores_words(self):
        db, wire, t = _asked()
        ident = {"company_id": T.CID, "projects": [{"_id": T.PID}]}
        open_ = self._gate(db, ident)
        self.assertNotIn("logged", open_)
        self.assertTrue(open_.startswith('Q1 is not recorded yet: reply "Q1 YES" or "Q1 NO"'))
        with patch.object(server, "_active_optin_for_phone", _optin):
            t._with(db, wire, lambda: server._handle_set_question_message(CHAT, "Q1 no"))
        done = self._gate(db, ident)
        self.assertTrue(done.startswith("Q1 is recorded: "), done)
        self.assertIn("not part of the filed set", done)

    def test_with_no_store_it_confirms_nothing(self):
        out = self._gate(T._db(), {"company_id": T.CID, "projects": []})
        self.assertTrue(out.startswith("I can't confirm Q1 was recorded"))

    def test_other_sentences_are_left_alone(self):
        _need("recorded_claims")
        for s in ("I couldn't log it as an answer on my end, so nothing is changed yet.",
                  "Got it — gas change roof plan governs, A.1.x stays out.",
                  "The roof has 3 WH-1."):
            self.assertEqual(psq.recorded_claims(s), [], s)


class TheEvidenceSaysAnsweredNotNotDecided(unittest.TestCase):

    def test_an_answer_recorded_after_the_pass(self):
        books = SimpleNamespace(tracks={"filed": SimpleNamespace(questions={"q1": "the A.1.x plans"})},
                                labels={"filed": "the filed set"})
        stored = {"record_type": "set_question", "_id": "q1", "code": "Q1", "status": psq.ANSWERED,
                  "answer": psq.EXCLUDE, "label": "the A.1.x plans", "answered_by_name": "Roey Fishman",
                  "answered_via": "whatsapp", "answered_at": "2026-10-30T01:21:30"}
        lines = S.render_set_questions([stored], books)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("Not decided", lines[0])
        self.assertIn("answered not part of the filed set by Roey Fishman", lines[0])
        self.assertIn("applied at the next drawing check", lines[0])

    def test_a_replacement_recorded_after_the_pass_reads_as_a_replacement(self):
        """Roy, 10-30: Q2 is REPLACES, not part of / not part of. The render
        says which sheets it replaces, never "not part of the filed set"."""
        _need("REPLACES", "replaces_phrase")
        books = SimpleNamespace(tracks={"filed": SimpleNamespace(questions={"q2": "the unnumbered Roof Plan"})},
                                labels={"filed": "the filed set"})
        stored = {"record_type": "set_question", "_id": "q2", "code": "Q2", "status": psq.ANSWERED,
                  "answer": psq.REPLACES, "label": "the unnumbered Roof Plan",
                  "answered_by_name": "Roy", "answered_via": "admin", "answered_at": "2026-10-30T10:00:00",
                  "replacements": [
                      {"file_name": "AR - 6.9.26 (Gas change).pdf", "page_number": 2, "sheet_number": None,
                       "sheet_title": "Roof Plan", "replaces": {"sheet_number": "A-105.01"}},
                      {"file_name": "AR - 6.9.26 (Gas change).pdf", "page_number": 1,
                       "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN",
                       "replaces": {"sheet_number": "A-100.01"}}]}
        lines = S.render_set_questions([stored], books)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("Not decided", lines[0])
        self.assertNotIn("not part of", lines[0])
        self.assertIn("replaces A-105.01", lines[0])
        self.assertIn("A-100.00 (AR - 6.9.26 (Gas change).pdf, page 1) replaces A-100.01", lines[0])
        self.assertIn("applied at the next drawing check", lines[0])

    def test_the_evidence_reads_answered_questions_too(self):
        import inspect
        src = inspect.getsource(server._glyph_evidence)
        self.assertRegex(src, r'"status":\s*\{"\$in":\s*\[_psq\.OPEN,\s*_psq\.ANSWERED\]\}',
                         "an answer stored after the pass must reach the render")


class TheDmPathReadsSetAnswersFirst(unittest.TestCase):

    def test_before_the_assistant(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("await _handle_set_question_message(dm_chat", src)
        i = src.index("await _handle_set_question_message(dm_chat, parsed.get(\"body\"))")
        j = src.index("ident = await _dm_assistant_identity(dm_chat)", i)
        self.assertLess(i, j)
        self.assertNotRegex(src[i - 2000:j], r"_psq\.parse_reply\(parsed")

    def test_both_outgoing_paths_are_gated(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"await _dm_set_answer_claims\(", src)), 2)


if __name__ == "__main__":
    unittest.main()
