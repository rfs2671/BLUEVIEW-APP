"""DM assistant, device report 2026-10-09 9:41-9:47.

1. The job picker lost the question: "Any updates on worker count?" ->
   "Which job? 1) 588 … 2) 8 Walworth" -> "588" -> "Could you provide more
   context…". A reply-to the menu, or "." under the question, got a generic
   answer. Now an open menu (10 min) takes "1"/"2", the house number, part of
   the address, or a reply-to the menu, and the ORIGINAL question is
   answered. A reply-to uses the quoted message as context. No generic
   greeting while a question is pending or quoted.

2. Headcount was invented: 20 workers an hour after the brief said 18, then
   "the 2 added" named twice, differently. Now a headcount answer is built
   only from this turn's check-ins (count by company; who checked in since
   the brief, with times; who is on site); the model may only rephrase and
   every number / name it writes is checked against the data; a challenge
   re-reads the records; every answer is logged with its data.
"""

from __future__ import annotations

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

import server  # noqa: E402
from lib import wa_assistant, wa_headcount  # noqa: E402
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    THOMAS, WALWORTH, _Harness, _db, _optin, _run,
)
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

CHAT = f"{ADMIN_PHONE}@c.us"
MENU = "Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St"


def _et_today(h, m):
    """Today at h:m New York, in UTC."""
    now_local = wa_headcount._local(datetime.now(timezone.utc))
    return now_local.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)


def _payload(chat, body, mid, quoted=None, quoted_from_bot=False):
    msg = {"id": {"id": mid, "fromMe": False, "_serialized": f"false_{chat}_{mid}"},
           "from": chat, "body": body, "type": "chat"}
    if quoted is not None:
        msg["quotedMsg"] = {"body": quoted, "type": "chat",
                            "id": {"fromMe": quoted_from_bot, "id": "Q" + mid}}
        msg["contextInfo"] = {"stanzaId": "Q" + mid}
    return {"event": "message", "data": {"message": msg}}


# The brief at 8:07 said 18: Arkon 11, Quality Plumbing 4, Power Direct 3.
# Two more came after it.
BEFORE = ([("Arkon", f"Arkon Worker {i}") for i in range(1, 12)]
          + [("Quality Plumbing", f"QP Worker {i}") for i in range(1, 5)]
          + [("Power Direct", f"PD Worker {i}") for i in range(1, 4)])
# The real 9:44 picture: the two added were Quality Plumbing, in at 9:12 and 9:30.
AFTER = [("Quality Plumbing", "Jose Zarate", (9, 12)), ("Quality Plumbing", "Pablo Sen", (9, 30))]


def _site(db):
    rows = []
    for i, (co, name) in enumerate(BEFORE):
        rows.append({"_id": f"c{i}", "project_id": THOMAS, "company_id": CO_A,
                     "worker_id": f"w{i}", "worker_name": name, "worker_company": co,
                     "worker_phone": f"171855501{i:02d}",
                     "check_in_time": _et_today(6, 30) + timedelta(minutes=i),
                     "status": "checked_in"})
    for j, (co, name, (h, m)) in enumerate(AFTER):
        rows.append({"_id": f"a{j}", "project_id": THOMAS, "company_id": CO_A,
                     "worker_id": f"x{j}", "worker_name": name, "worker_company": co,
                     "worker_phone": f"171855502{j:02d}",
                     "check_in_time": _et_today(h, m), "status": "checked_in"})
    # Same worker checking in twice counts once (the brief's rule).
    rows.append({**rows[0], "_id": "dup", "check_in_time": _et_today(10, 0)})
    db.checkins.rows.extend(rows)
    db[server.WA_LEDGER].rows.append({
        "_id": "brief1", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
        "status": "sent", "created_at": _et_today(8, 7)})


class _Chat(_Harness):
    def setUp(self):
        super().setUp()
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _site(self.db)
        self.n = 0

    def say(self, c, body, quoted=None, from_bot=False, llm=None, key=None):
        """One DM; returns the reply sent (or None)."""
        self.n += 1
        before = len([p for p in c.wire.calls if "message" in p])

        async def agent(**kw):
            self.agent_calls.append(kw)
            return f"answer for {kw['project_id']}"

        async def dm_llm(system, user_text):
            self.llm_calls.append((system, user_text))
            return llm(user_text) if llm else "general"

        async def react(*a, **k):
            return True

        async def scope(body):
            return wa_assistant.question_scope(body) or wa_assistant.SCOPE_PROJECT
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_dm_llm", dm_llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", scope), \
                patch.object(server, "OPENAI_API_KEY", key):
            _run(server._process_whatsapp_message(
                _payload(CHAT, body, f"m{self.n}", quoted, from_bot)))
        sends = [p["message"] for p in c.wire.calls if "message" in p]
        return sends[-1] if len(sends) > before else None


class ThePicker(_Chat, unittest.TestCase):

    def test_588_picks_and_the_original_question_is_answered(self):
        with _Ctx(db=self.db) as c:
            self.assertEqual(self.say(c, "Any updates on worker count?"), MENU)
            reply = self.say(c, "588")
        self.assertIn("20 on site at 588 Thomas S Boyland St now", reply)
        self.assertNotIn("Could you provide more context", reply)

    def test_a_number_picks(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open?")
            self.assertEqual(self.say(c, "2"), f"answer for {WALWORTH}")
        self.assertEqual(self.agent_calls[0]["body"], "what's open?")

    def test_a_reply_to_the_menu_picks(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Any updates on worker count?")
            reply = self.say(c, "U asked which address I said 588", quoted=MENU, from_bot=True)
        self.assertIn("20 on site at 588 Thomas S Boyland St now", reply)

    def test_part_of_the_address_picks(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open?")
            self.assertEqual(self.say(c, "walworth"), f"answer for {WALWORTH}")

    def test_a_failed_pick_asks_again_and_keeps_the_question(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Any updates on worker count?")
            again = self.say(c, "the one on 58")
            self.assertTrue(again.startswith(MENU))
            self.assertIn(wa_assistant.MENU_AGAIN_TEXT, again)
            reply = self.say(c, "1")
        self.assertIn("20 on site at 588 Thomas S Boyland St now", reply)
        self.assertEqual(self.llm_calls, [])          # never a generic answer

    def test_a_reply_to_an_expired_menu_says_so(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "588", quoted=MENU, from_bot=True)
        self.assertEqual(reply, wa_assistant.MENU_EXPIRED_TEXT)


class ReplyTo(_Chat, unittest.TestCase):

    def test_a_dot_under_your_own_question_is_that_question(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, ".", quoted="what's open at 8 walworth?")
        self.assertEqual(reply, f"answer for {WALWORTH}")
        self.assertEqual(self.agent_calls[0]["body"], "what's open at 8 walworth?")
        self.assertEqual(self.llm_calls, [])

    def test_a_dot_under_your_headcount_question_counts(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, ".", quoted="how many workers at 588 thomas?")
        self.assertIn("20 on site at 588 Thomas S Boyland St now", reply)

    def test_a_reply_to_an_answer_carries_it_as_context(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "and the permits?", quoted="Open items at 8 Walworth St: 2",
                     from_bot=True)
        body = self.agent_calls[0]["body"]
        self.assertTrue(body.startswith("and the permits?"))
        self.assertIn("Open items at 8 Walworth St: 2", body)
        self.assertEqual(self.agent_calls[0]["project_id"], WALWORTH)

    def test_a_lone_dot_is_not_a_greeting(self):
        with _Ctx(db=self.db) as c:
            self.assertEqual(self.say(c, "."), wa_assistant.NUDGE_TEXT)
        self.assertEqual(self.llm_calls, [])


class TheExchange(_Chat, unittest.TestCase):
    """9:44-9:47, replayed. Every number and name must be the records'."""

    def test_count_then_who_was_added_then_the_challenge(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Any updates on worker count?")
            count = self.say(c, "588")
            added = self.say(c, "Who are the 2 added?")
            again = self.say(c, "That doesn't make sense", quoted=added, from_bot=True)
        on_site = ("20 on site at 588 Thomas S Boyland St now — Arkon 11, "
                   "Quality Plumbing 6, Power Direct 3.")
        two = ("2 since your 8:07 brief — Jose Zarate and Pablo Sen (Quality Plumbing), "
               "in at 9:12 and 9:30.")
        self.assertEqual(count, on_site + "\n" + two)
        self.assertEqual(added, two + "\n" + on_site)
        self.assertEqual(again, "Rechecked the check-ins.\n" + added)
        for invented in ("Juan Lopez", "Power Direct, Juan"):
            self.assertNotIn(invented, count + added + again)
        self.assertEqual(self.agent_calls, [])         # never the free agent

    def test_an_invented_name_from_the_model_is_never_sent(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "who came in after the brief at 588 thomas",
                             llm=lambda t: "2 added: Juan Lopez (Arkon) and Jose Zarate.",
                             key="sk-test")
        self.assertNotIn("Juan Lopez", reply)
        self.assertIn("Jose Zarate and Pablo Sen (Quality Plumbing), in at 9:12 and 9:30", reply)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual(log["wording"], "fixed_after_check_failed")

    def test_a_faithful_rephrase_is_used(self):
        def rephrase(t):
            return ("2 since your 8:07 brief: Jose Zarate and Pablo Sen, both Quality "
                    "Plumbing, in at 9:12 and 9:30. 20 on site now.")
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "who came in after the brief at 588 thomas",
                             llm=rephrase, key="sk-test")
        self.assertTrue(reply.startswith("2 since your 8:07 brief: Jose Zarate"))
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["wording"], "phrased")

    def test_a_wrong_number_from_the_model_is_never_sent(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "how many workers at 588 thomas",
                             llm=lambda t: "20 workers — 13 from Arkon.", key="sk-test")
        self.assertIn("Arkon 11", reply)
        self.assertNotIn("13", reply)

    def test_since_a_time_said_in_the_question(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "who checked in since 9 at 588 thomas")
        self.assertIn("2 since 9:00 — Jose Zarate and Pablo Sen", reply)

    def test_every_answer_is_logged_with_its_data_and_no_phone_numbers(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "how many workers at 588 thomas")
            self.say(c, "what's open at 8 walworth")
        logs = self.db[server.DM_ANSWERS].rows
        self.assertEqual([r["path"] for r in logs], ["headcount", "job_agent"])
        hc = logs[0]["tool_data"]
        self.assertEqual((hc["total"], hc["added"]), (20, ["Jose Zarate", "Pablo Sen"]))
        self.assertEqual(len(hc["workers"]), 20)
        import json
        blob = json.dumps(logs, default=str)
        self.assertNotIn("171855501", blob)
        self.assertNotIn(ADMIN_PHONE, blob)


class TheConversation(_Chat, unittest.TestCase):
    """2026-10-09 9:41-9:47, the messages as sent. It used to act like each
    message was a new chat; now each one is read in the conversation."""

    def setUp(self):
        super().setUp()
        # The morning brief it sent, in this chat's history.
        self.db.whatsapp_messages.rows.append({
            "_id": "brief_msg", "group_id": CHAT, "is_dm": True, "sender": "bot",
            "body": "Good morning. 588 Thomas S Boyland St — On site so far: 18 — "
                    "Arkon 11, Quality Plumbing 4, Power Direct 3",
            "created_at": datetime.now(timezone.utc) - timedelta(hours=1)})

    def test_the_exchange_as_sent(self):
        two = ("2 since your 8:07 brief — Jose Zarate and Pablo Sen (Quality Plumbing), "
               "in at 9:12 and 9:30.")
        with _Ctx(db=self.db) as c:
            menu = self.say(c, "Any updates on worker count?")                # 9:41
            self.assertEqual(menu, MENU)
            first = self.say(c, "588")                                        # answers it
            self.assertTrue(first.startswith("20 on site at 588 Thomas S Boyland St now"))
            self.assertIn(two, first)
            again = self.say(c, "U asked which address I said 588", quoted=MENU, from_bot=True)
            self.assertEqual(again, first)                                    # same question, same job
            dot = self.say(c, ".", quoted="Any updates on worker count?")
            self.assertEqual(dot, first)
            added = self.say(c, "Who's the 2 added workers")                  # first try
            self.assertTrue(added.startswith(two))
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.llm_calls, [])       # no generic model answer, ever

    def test_since_the_morning_means_since_the_brief(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "how many workers at 588 thomas")
            reply = self.say(c, "and since the morning?")
        self.assertTrue(reply.startswith("2 since your 8:07 brief — Jose Zarate"))

    def test_those_refers_to_the_last_answer(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Who's the 2 added workers at 588")
            reply = self.say(c, "when did those come in")
        self.assertIn("in at 9:12 and 9:30", reply)

    def test_an_ambiguous_since_gets_one_short_question(self):
        with _Ctx(db=self.db) as c:
            q = self.say(c, "who came in since earlier at 588 thomas")
            self.assertEqual(q, "Since 8:07 (your brief) or since 7am?")
            reply = self.say(c, "8:07")
        self.assertTrue(reply.startswith("2 since your 8:07 brief"))
        self.assertEqual(self.llm_calls, [])

    def test_the_other_option(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "who came in since earlier at 588 thomas")
            reply = self.say(c, "7am")
        # Everyone else was in before 7 (6:30-6:48).
        self.assertTrue(reply.startswith("2 since 7:00 — Jose Zarate and Pablo Sen"))

    def test_the_current_job_holds_no_picker(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "how many workers at 588 thomas")
            reply = self.say(c, "what's open?")
        self.assertEqual(reply, f"answer for {THOMAS}")

    def test_the_history_reaches_the_model_with_the_brief(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "how many workers at 588 thomas")
            self.say(c, "what's open there?")
        hist = self.agent_calls[0]["dm_history"]
        texts = [m["content"] for m in hist]
        self.assertTrue(any("On site so far: 18" in t for t in texts))       # the brief
        self.assertIn("how many workers at 588 thomas", texts)               # their side
        self.assertTrue(any(t.startswith("20 on site at") for t in texts))   # its side
        self.assertEqual({m["role"] for m in hist}, {"user", "assistant"})

    def test_a_question_mark_follows_up_instead_of_a_greeting(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open at 8 walworth?")
            reply = self.say(c, "?")
        self.assertEqual(reply, f"answer for {WALWORTH}")
        self.assertEqual(self.agent_calls[-1]["body"], "what's open at 8 walworth?")
        self.assertEqual(self.llm_calls, [])

    def test_a_vague_message_with_history_is_never_a_generic_answer(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open at 8 walworth?")
            self.say(c, "hmm ok and the rest")
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.agent_calls[-1]["project_id"], WALWORTH)


class TheAgentsNumbersAreChecked(_Chat, unittest.TestCase):

    def test_a_number_not_in_the_tool_results_is_not_sent(self):
        async def agent(**kw):
            kw["tool_trace"].append({"tool": "open_items", "result": "Open items: 3"})
            return "You have 7 open items."
        with _Ctx(db=self.db), patch.object(server, "_run_group_agent", agent):
            reply = _run(server._dm_answer_job(
                {"company_id": CO_A}, {"_id": WALWORTH, "address": "8 Walworth St"},
                CHAT, "what's open?", "m1", []))
        self.assertEqual(reply, "From the records:\nOpen items: 3")

    def test_numbers_from_the_tools_pass(self):
        async def agent(**kw):
            kw["tool_trace"].append({"tool": "open_items", "result": "Open items: 3"})
            return "3 open items at 8 Walworth."
        with _Ctx(db=self.db), patch.object(server, "_run_group_agent", agent):
            reply = _run(server._dm_answer_job(
                {"company_id": CO_A}, {"_id": WALWORTH, "address": "8 Walworth St"},
                CHAT, "what's open?", "m1", []))
        self.assertEqual(reply, "3 open items at 8 Walworth.")


class ReviewFindings(_Chat, unittest.TestCase):
    """Codex review of #712."""

    def test_swapped_counts_are_caught(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "how many workers at 588 thomas",
                             llm=lambda t: "11 on site now — Arkon 20, Quality Plumbing 6, "
                                           "Power Direct 3.", key="sk-test")
        self.assertTrue(reply.startswith("20 on site at 588 Thomas S Boyland St now — Arkon 11"))
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["wording"],
                         "fixed_after_check_failed")

    def test_a_lowercase_invented_name_is_caught(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "who came in after the brief at 588 thomas",
                             llm=lambda t: "2 since your 8:07 brief: juan lopez and "
                                           "pablo sen, in at 9:12 and 9:30.", key="sk-test")
        self.assertNotIn("juan lopez", reply.lower())
        self.assertIn("Jose Zarate and Pablo Sen (Quality Plumbing)", reply)

    def test_checked_out_workers_are_not_on_site_now(self):
        for r in self.db.checkins.rows:
            if r["worker_name"] in ("Arkon Worker 1", "Arkon Worker 2"):
                r["status"] = "checked_out"
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "how many workers at 588 thomas")
        # Worker 1 checked in twice; the later row is still checked out.
        self.assertTrue(reply.startswith("18 on site at 588 Thomas S Boyland St now — Arkon 9,"),
                        reply)
        # Who checked in since the brief still counts anyone who came, gone or not.
        self.assertIn("2 since your 8:07 brief", reply)

    def test_all_my_jobs_stays_all_jobs(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "how many workers across all my jobs?")
        self.assertEqual(reply, "general")                     # the all-jobs answer (stub)
        self.assertEqual(self.llm_calls[-1][0], wa_assistant.CROSS_SYSTEM_PROMPT)

    def test_a_challenge_naming_another_job_recounts_that_job(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "how many workers at 588 thomas")
            reply = self.say(c, "the count at 8 walworth is wrong")
        self.assertIn("8 Walworth St", reply)
        self.assertNotIn("588 Thomas", reply)


class TheRules(unittest.TestCase):

    def test_intents(self):
        H = wa_headcount
        for text, want in (("Any updates on worker count?", H.COUNT),
                           ("Who are the 2 added?", H.ADDED),
                           ("That doesn't make sense", H.CHALLENGE),
                           ("who's on site", H.LIST),
                           ("how many permits expire", None),
                           ("who's on site with an expired SST card", None)):
            self.assertEqual(H.intent(text), want, text)

    def test_the_check(self):
        data = wa_headcount.summarize([], None)
        data.update(total=3, by_company=[("Arkon", 3)],
                    workers=[{"name": "Luis Ortega", "company": "Arkon", "at": None}])
        ok = wa_headcount.verify
        self.assertTrue(ok("There are 3 on site now, all Arkon. Luis Ortega is one.", data, "588 Main St"))
        self.assertFalse(ok("4 on site", data, "588 Main St"))
        self.assertFalse(ok("3 on site incl. Juan Lopez", data, "588 Main St"))


if __name__ == "__main__":
    unittest.main()
