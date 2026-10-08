"""Levelog Assistant in a direct message.

  * Only an opted-in Admin or PM; everyone else gets one line and no data.
  * Admin: every job of their company. PM: their assigned jobs. Never another
    company's.
  * A named job is used; no job named and more than one → "Which job?" menu,
    answered with a number; the last job is remembered for 30 minutes.
  * Cross-project questions use a facts block of the allowed jobs only.
  * A @lid sender is resolved through the opt-in for that chat.
"""

from __future__ import annotations

import asyncio
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
from lib import wa_assistant  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, CO_B, CP_PHONE, PM_PHONE, SUPER_PHONE, UNKNOWN_PHONE,
    _Ctx, _users,
)

THOMAS, WALWORTH, OTHER_A, PROJ_B = "proj_a", "proj_w", "proj_o", "proj_b"
LID = "205842133426370"


def _run(coro):
    return asyncio.run(coro)


def _db():
    users = _users()
    for u in users:
        if u["_id"] == "u_pm":
            u["assigned_projects"] = [THOMAS]
    return FakeDb(
        unique={server.WA_OPTINS: ("phone",)},
        users=users,
        projects=[
            {"_id": THOMAS, "company_id": CO_A, "name": "Thomas",
             "address": "588 Thomas S Boyland St, Brooklyn, NY"},
            {"_id": WALWORTH, "company_id": CO_A, "name": "Walworth",
             "address": "8 Walworth St, Brooklyn, NY"},
            {"_id": OTHER_A, "company_id": CO_A, "name": "Deleted",
             "address": "1 Gone St", "is_deleted": True},
            {"_id": PROJ_B, "company_id": CO_B, "name": "B job",
             "address": "99 Bedford Ave, Brooklyn"},
        ],
        whatsapp_groups=[{"_id": "g1", "wa_group_id": "1@g.us", "project_id": WALWORTH,
                          "company_id": CO_A, "active": True,
                          "group_name": "Walworth Crew"}],
    )


def _optin(db, user_id, phone, chat=None):
    chat = chat or f"{phone}@c.us"
    db[server.WA_OPTINS].rows.append({
        "_id": f"o_{user_id}", "phone": phone, "user_id": user_id,
        "company_id": CO_A if user_id != "u_b" else CO_B, "status": "active",
        "chat_id": chat, "chat_digits": "".join(c for c in chat if c.isdigit()),
        "phone_verified": True})


def _payload(chat, body, mid="D1"):
    return {"event": "message", "data": {"message": {
        "id": {"id": mid, "fromMe": False, "_serialized": f"false_{chat}_{mid}"},
        "from": chat, "body": body, "type": "chat"}}}


class _Harness:
    def setUp(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []

    def _send(self, c, chat, body, mid="D1", *, agent_delay=0.0):
        async def agent(**kw):
            self.agent_calls.append(kw)
            if agent_delay:
                await asyncio.sleep(agent_delay)
            return f"answer for {kw['project_id']}"

        async def llm(system, user_text):
            self.llm_calls.append((system, user_text))
            return "cross" if system == wa_assistant.CROSS_SYSTEM_PROMPT else "general"

        async def react(chat_id, message_id, emoji):
            self.reactions.append(emoji)
            return True

        async def no_scope_model(body):
            return wa_assistant.question_scope(body) or wa_assistant.SCOPE_PROJECT
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_dm_llm", llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", no_scope_model), \
                patch.object(server.wa_react, "WORKING_AFTER_SECONDS", 0.05):
            _run(server._process_whatsapp_message(_payload(chat, body, mid)))
        sends = [p["message"] for p in c.wire.calls if "message" in p]
        return sends[-1] if sends else None

    def _projects_asked(self):
        return [k["project_id"] for k in self.agent_calls]


class WhoMayUseIt(_Harness, unittest.TestCase):

    def test_unknown_cp_super_and_not_opted_in_get_one_line(self):
        db = _db()
        _optin(db, "u_cp", CP_PHONE)          # even with an opt-in row, a CP is refused
        _optin(db, "u_super", SUPER_PHONE)
        with _Ctx(db=db) as c:
            for phone in (UNKNOWN_PHONE, CP_PHONE, SUPER_PHONE, ADMIN_PHONE):
                with self.subTest(phone):
                    reply = self._send(c, f"{phone}@c.us", "who's on site at 588 Thomas")
                    self.assertEqual(reply, wa_assistant.NOT_FOR_YOU_TEXT)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.llm_calls, [])

    def test_a_changed_profile_phone_fails_closed(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)
        db.users.rows[0]["phone"] = "+15550007777"
        with _Ctx(db=db) as c:
            self.assertEqual(self._send(c, f"{ADMIN_PHONE}@c.us", "who's on site"),
                             wa_assistant.NOT_FOR_YOU_TEXT)
        self.assertEqual(self.agent_calls, [])

    def test_a_lid_sender_is_resolved_through_its_opt_in(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE, chat=f"{LID}@lid")
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{LID}@lid", "who's on site at 8 walworth")
        self.assertEqual(reply, f"answer for {WALWORTH}")
        self.assertEqual(self.agent_calls[0]["company_id"], CO_A)


class Scope(_Harness, unittest.TestCase):

    def test_admin_reaches_every_live_company_job(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db=db) as c:
            self._send(c, f"{ADMIN_PHONE}@c.us", "open items at 8 walworth", "m1")
            self._send(c, f"{ADMIN_PHONE}@c.us", "who is on site at 588 thomas", "m2")
            self._send(c, f"{ADMIN_PHONE}@c.us", "any new violations this week?", "m3")
        self.assertEqual(self._projects_asked(), [WALWORTH, THOMAS])
        facts = self.llm_calls[-1][1]
        self.assertIn("588 Thomas S Boyland St", facts)
        self.assertIn("8 Walworth St", facts)
        self.assertNotIn("Bedford", facts)               # another company
        self.assertNotIn("Gone St", facts)               # deleted

    def test_pm_reaches_only_assigned_jobs(self):
        db = _db()
        _optin(db, "u_pm", PM_PHONE)
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{PM_PHONE}@c.us", "who's on site at 8 walworth", "m1")
            self.assertIn("You're not on 8 Walworth St", reply)
            self.assertIn("588 Thomas S Boyland St", reply)
            reply = self._send(c, f"{PM_PHONE}@c.us", "who's on site", "m2")   # one job: no menu
            self._send(c, f"{PM_PHONE}@c.us", "permits expiring this month?", "m3")
        self.assertEqual(self._projects_asked(), [THOMAS])
        self.assertEqual(reply, f"answer for {THOMAS}")
        facts = self.llm_calls[-1][1]
        self.assertIn("588 Thomas", facts)
        self.assertNotIn("Walworth", facts)

    def test_another_companys_job_is_never_read(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "who's on site at 99 Bedford Ave")
        self.assertTrue(reply.startswith("Which job?"))   # not named among THEIR jobs
        self.assertNotIn(PROJ_B, self._projects_asked())
        self.assertNotIn("Bedford", reply)

    def test_the_job_list_is_company_scoped_at_the_source(self):
        db = _db()
        with _Ctx(db=db):
            ident = {"company_id": CO_A}
            admin = _run(server._dm_assistant_projects(
                db.users.rows[0], CO_A, "admin"))
            pm = _run(server._dm_assistant_projects(
                {**db.users.rows[1], "assigned_projects": [THOMAS, PROJ_B]}, CO_A, "pm"))
        self.assertEqual({str(p["_id"]) for p in admin}, {THOMAS, WALWORTH})
        self.assertEqual({str(p["_id"]) for p in pm}, {THOMAS})   # PROJ_B assigned but not CO_A


class WhichJob(_Harness, unittest.TestCase):

    def _admin(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)
        return db

    def test_no_job_named_gives_the_menu_and_a_number_picks(self):
        db = self._admin()
        with _Ctx(db=db) as c:
            menu = self._send(c, f"{ADMIN_PHONE}@c.us", "who's on site?", "m1")
            self.assertEqual(menu, "Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St")
            self.assertEqual(self.agent_calls, [])
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "2", "m2")
        self.assertEqual(reply, f"answer for {WALWORTH}")
        self.assertEqual(self.agent_calls[0]["body"], "who's on site?")   # the original question

    def test_a_group_name_or_partial_address_names_the_job(self):
        db = self._admin()
        with _Ctx(db=db) as c:
            self._send(c, f"{ADMIN_PHONE}@c.us", "what's open in walworth crew", "m1")
            self._send(c, f"{ADMIN_PHONE}@c.us", "violations at thomas s boyland", "m2")
        self.assertEqual(self._projects_asked(), [WALWORTH, THOMAS])

    def test_the_last_job_is_remembered_for_30_minutes(self):
        db = self._admin()
        with _Ctx(db=db) as c:
            self._send(c, f"{ADMIN_PHONE}@c.us", "who's on site at 8 walworth", "m1")
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "and the open items?", "m2")
            self.assertEqual(reply, f"answer for {WALWORTH}")
            row = next(r for r in db.whatsapp_conversation_state.rows if r["kind"] == "dm_job")
            self.assertAlmostEqual(
                (row["expires_at"] - datetime.now(timezone.utc)).total_seconds(),
                30 * 60, delta=5)
            row["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "and the open items?", "m3")
        self.assertTrue(reply.startswith("Which job?"))

    def test_a_number_without_a_menu_is_just_a_message(self):
        db = self._admin()
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "2", "m1")
        self.assertTrue(reply.startswith("Which job?"))


class KindsOfQuestion(_Harness, unittest.TestCase):

    def _admin(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)
        return db

    def test_general_help_uses_no_data(self):
        with _Ctx(db=self._admin()) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "how do I add a worker?")
        self.assertEqual(reply, "general")
        self.assertEqual(self.llm_calls[0][0], wa_assistant.GENERAL_SYSTEM_PROMPT)
        self.assertEqual(self.agent_calls, [])
        self.assertIn("not legal advice", wa_assistant.GENERAL_SYSTEM_PROMPT)
        self.assertIn("never invent DOB figures", wa_assistant.GENERAL_SYSTEM_PROMPT)

    def test_cross_project_questions(self):
        for q in ("any new violations this week?", "permits expiring this month?",
                  "what happened today on my jobs?"):
            self.assertEqual(wa_assistant.question_scope(q), wa_assistant.SCOPE_ALL, q)

    def test_thanks_gets_a_reaction_not_text(self):
        with _Ctx(db=self._admin()) as c:
            before = len([p for p in c.wire.calls if "message" in p])
            self._send(c, f"{ADMIN_PHONE}@c.us", "thanks!")
            after = len([p for p in c.wire.calls if "message" in p])
        self.assertEqual(self.reactions, ["🙏"])
        self.assertEqual(before, after)

    def test_a_slow_answer_gets_eyes_first(self):
        with _Ctx(db=self._admin()) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", "who's on site at 8 walworth",
                               agent_delay=0.2)
        self.assertEqual(self.reactions, ["👀"])
        self.assertEqual(reply, f"answer for {WALWORTH}")

    def test_a_voice_answer_opens_with_what_was_heard(self):
        sent = []

        async def send(chat, text, **kw):
            sent.append(text)
            return {}

        async def answer():
            return "2 on site."
        with patch.object(server, "send_whatsapp_message", send):
            _run(server._dm_send_answer("c", "m", answer(), heard="who is on site"))
        self.assertEqual(sent, ['Heard: "who is on site"\n\n2 on site.'])

    def test_the_dm_agent_is_read_only(self):
        self.assertEqual(server._DM_WRITE_TOOLS,
                         {"start_permit_renewal", "start_checklist"})
        self.assertIn("cannot file", wa_assistant.DM_AGENT_CLAUSE)


class TheDmAgentRequest(unittest.TestCase):
    """The real _run_group_agent in DM mode: no write tools offered, the DM
    voice in the prompt, no group history, scoped to the job's company."""

    def test_what_the_model_is_sent(self):
        sent = []

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "2 on site.",
                                                 "tool_calls": None}}]}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                sent.append(json)
                return _Resp()
        db = _db()
        db.whatsapp_messages.rows.append(
            {"group_id": "1@g.us", "project_id": WALWORTH, "company_id": CO_A,
             "sender": "15550001111", "body": "GROUP SECRET", "created_at":
             datetime.now(timezone.utc)})
        with patch.object(server, "db", db), \
                patch.object(server, "OPENAI_API_KEY", "k"), \
                patch.object(server, "ServerHttpClient", _Client):
            out = _run(server._run_group_agent(
                project_id=WALWORTH, group_id=f"{ADMIN_PHONE}@c.us", company_id=CO_A,
                sender=ADMIN_PHONE, body="who's on site", features=
                server._default_bot_config()["features"], explicit_mention=True,
                dm=True))
            refused = _run(server._run_group_agent(
                project_id=PROJ_B, group_id=f"{ADMIN_PHONE}@c.us", company_id=CO_A,
                sender=ADMIN_PHONE, body="who's on site", features={}, dm=True))
        self.assertTrue(out)
        self.assertIsNone(refused)                      # another company's job
        req = sent[0]
        names = {t["function"]["name"] for t in req["tools"]}
        self.assertFalse(names & {"start_permit_renewal", "start_checklist"})
        self.assertIn("who_on_site", names)
        self.assertIn("PRIVATE WHATSAPP CHAT", req["messages"][0]["content"])
        self.assertNotIn("GROUP SECRET", str(req["messages"]))


class MatchingRules(unittest.TestCase):

    def test_house_number_beats_a_shared_street(self):
        jobs = [{"id": "b", "aliases": wa_assistant.job_aliases({"address": "8 Walworth St"})},
                {"id": "c", "aliases": wa_assistant.job_aliases({"address": "58 Walworth St"})}]
        self.assertEqual(wa_assistant.match_jobs("8 walworth permits", jobs), ["b"])
        self.assertEqual(wa_assistant.match_jobs("58 walworth", jobs), ["c"])
        self.assertEqual(sorted(wa_assistant.match_jobs("walworth?", jobs)), ["b", "c"])

    def test_menu_choice(self):
        self.assertEqual(wa_assistant.parse_menu_choice("2", 3), 1)
        self.assertEqual(wa_assistant.parse_menu_choice("2.", 3), 1)
        self.assertIsNone(wa_assistant.parse_menu_choice("4", 3))
        self.assertIsNone(wa_assistant.parse_menu_choice("2 please", 3))


class PraiseOncePerDay(unittest.TestCase):

    def test_the_next_day_is_allowed_again(self):
        db = FakeDb(unique={"whatsapp_conversation_state": ("kind",)})  # stand-in for the compound unique
        with patch.object(server, "db", db):
            with patch.object(server, "eastern_today", lambda: "2026-10-08"):
                self.assertTrue(_run(server._praise_reaction_allowed("g", "s")))
                self.assertFalse(_run(server._praise_reaction_allowed("g", "s")))
            with patch.object(server, "eastern_today", lambda: "2026-10-09"):
                self.assertTrue(_run(server._praise_reaction_allowed("g", "s")))
        self.assertEqual(len(db.whatsapp_conversation_state.rows), 1)


if __name__ == "__main__":
    unittest.main()
