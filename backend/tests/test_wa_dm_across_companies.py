"""The DM assistant for one person with an account in each of two companies.

Roy's rulings (2026-11-06):
  * Reads / answers range across all the person's connected accounts'
    projects, each answer tied to its own project's company.
  * A WRITE whose job is in 2+ of the person's companies (or names no job)
    asks which one first -- the companies / jobs named, a numbered reply.
  * The morning brief is ONE summary covering every connected account.
  * Chat history must not feed one company's content into another
    company's answer.
  * A person with ONE account is answered exactly as before.

Ada is an admin at Acme (co_a: 12 Main St, and 588 Thomas S Boyland St) and
a PM at Brick (co_b: 40 Oak Ave, and -- the same building, as the sub --
588 Thomas S Boyland St), one phone, both accounts connected. Nothing
reaches the network or a model: WaAPI is the phase-1 _Wire, and the DM
assistant / the brain's model are recorded stand-ins.
"""

from __future__ import annotations

import asyncio
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

import server  # noqa: E402
from lib import wa_brief, wa_dm  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, CO_B, _Ctx  # noqa: E402

CHAT = f"{ADMIN_PHONE}@c.us"
NAME_A, NAME_B = "Acme Builders", "Brick & Co"
MAIN, BOYLAND_A, OAK, BOYLAND_B = "p_main", "p_boy_a", "p_oak", "p_boy_b"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


def _db(*, two=True):
    users = [{"_id": "u_a", "company_id": CO_A, "role": "admin", "phone": "+" + ADMIN_PHONE,
              "name": "Ada", "account_status": "approved"},
             {"_id": "u_b", "company_id": CO_B, "role": "pm", "phone": ADMIN_PHONE,
              "name": "Ada", "account_status": "approved", "pm_access": "full"}]
    optins = [{"_id": "o_a", "phone": ADMIN_PHONE, "user_id": "u_a", "company_id": CO_A,
               "chat_id": CHAT, "chat_digits": ADMIN_PHONE, "phone_verified": True,
               "status": "active", "opted_in_at": T0}]
    if two:
        optins.append({"_id": "o_b", "phone": ADMIN_PHONE, "user_id": "u_b",
                       "company_id": CO_B, "chat_id": CHAT, "chat_digits": ADMIN_PHONE,
                       "phone_verified": True, "status": "active",
                       "opted_in_at": T0 + timedelta(days=1)})
    else:
        users[1]["phone"] = "+15550002001"
    return FakeDb(
        unique={server.WA_OPTINS: (("phone", "user_id"),)},
        users=users,
        companies=[{"_id": CO_A, "name": NAME_A}, {"_id": CO_B, "name": NAME_B}],
        projects=[
            {"_id": MAIN, "company_id": CO_A, "name": "Main", "address": "12 Main St, Brooklyn"},
            {"_id": BOYLAND_A, "company_id": CO_A, "name": "Boyland GC",
             "address": "588 Thomas S Boyland St, Brooklyn"},
            {"_id": OAK, "company_id": CO_B, "name": "Oak", "address": "40 Oak Ave, Queens"},
            {"_id": BOYLAND_B, "company_id": CO_B, "name": "Boyland sub",
             "address": "588 Thomas S Boyland St, Brooklyn"},
        ],
        whatsapp_optins=optins,
        whatsapp_dm_welcomes=[{"_id": o["user_id"], "company_id": o["company_id"],
                               "card": "vcard"} for o in optins],
    )


def _var(name):
    var = getattr(server, name, None)
    return var.get() if var is not None else None


class _Turn:
    """The DM pipeline up to the assistant: what it was handed, as whom."""

    def __init__(self, brain=True):
        self.calls = []
        self.brain = brain

    async def reply(self, ident, dm_chat, body, message_id, **kw):
        self.calls.append({"as": ident["user_id"], "company": ident["company_id"],
                           "body": body, "person": [a["user_id"] for a in kw.get("person") or []],
                           # (getattr: the control run reads the code before the change)
                           "scope": _var("_DM_SCOPE"), "history": _var("_DM_HISTORY_SCOPE")})

    async def no_punch(self, *a, **k):
        return False

    async def brain_on(self, ident):
        return self.brain

    def say(self, c, body, mid):
        payload = {"event": "message", "data": {"message": {
            "id": {"id": mid, "fromMe": False}, "from": CHAT, "body": body, "type": "chat"}}}
        with patch.object(server, "_dm_assistant_reply", self.reply), \
                patch.object(server, "_punch_dm_turn", self.no_punch), \
                patch.object(server, "_dm_brain_on", self.brain_on):
            _run(server._process_whatsapp_message(payload))


def _texts(c):
    return [p["message"] for p in c.wire.calls if "message" in p]


class EachMessageGoesToTheRightAccount(unittest.TestCase):

    def test_a_job_named_in_one_company_is_that_account(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "how many on site at 12 main", "m1")
            t.say(c, "how many on site at 40 oak", "m2")
        self.assertEqual([(x["as"], x["company"], x["person"]) for x in t.calls],
                         [("u_a", CO_A, []), ("u_b", CO_B, [])])
        self.assertEqual([x["history"] for x in t.calls], [CO_A, CO_B])

    def test_a_question_about_all_jobs_reads_across_both(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "what's open across all my jobs?", "m1")
        self.assertEqual(t.calls[0]["person"], ["u_a", "u_b"])
        self.assertEqual(t.calls[0]["scope"], server.DM_SCOPE_MULTI)

    def test_the_same_street_in_both_a_question_reads_across(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "who is on site at 588 boyland?", "m1")
            self.assertEqual(_texts(c), [])
        self.assertEqual(t.calls[0]["person"], ["u_a", "u_b"])

    def test_a_change_at_the_same_street_asks_which_one_by_number(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add Arkon as the plumber at 588 boyland", "m1")
            self.assertEqual(t.calls, [], "nothing is done before they pick")
            asked = _texts(c)[-1]
            self.assertEqual(asked, "Which one?\n"
                             f"1) 588 Thomas S Boyland St ({NAME_A})\n"
                             f"2) 588 Thomas S Boyland St ({NAME_B})")
            t.say(c, "2", "m2")
            job = _run(server._dm_state_get("dm_job", CHAT))
        self.assertEqual([(x["as"], x["body"]) for x in t.calls],
                         [("u_b", "add Arkon as the plumber at 588 boyland")])
        self.assertEqual((job["project_id"], job["acct"]), (BOYLAND_B, "u_b"))

    def test_a_change_with_no_job_asks_which_company(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            self.assertEqual(_texts(c)[-1],
                             f"Which company is this for?\n1) {NAME_A}\n2) {NAME_B}")
            t.say(c, "brick", "m2")
        self.assertEqual([(x["as"], x["body"]) for x in t.calls],
                         [("u_b", "add a new job at 9 Menahan St")])

    def test_asked_in_spanish_in_spanish(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "agrega un trabajo nuevo en 9 Menahan St para la compañía", "m1")
            self.assertTrue(_texts(c)[-1].startswith("¿Para qué compañía es?"))

    def test_a_new_message_instead_of_a_pick_is_routed_as_new(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            t.say(c, "how many at 40 oak", "m2")
            t.say(c, "1", "m3")
        self.assertEqual((t.calls[0]["as"], t.calls[0]["body"]), ("u_b", "how many at 40 oak"))
        self.assertEqual(len(t.calls), 2)
        self.assertNotIn("add a new job at 9 Menahan St", [x["body"] for x in t.calls],
                         "the held change is dropped once they moved on: never done later")

    def test_the_answer_to_an_open_question_goes_to_the_account_that_asked(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            brick = next(a for a in _run(server._dm_identities(CHAT)) if a["user_id"] == "u_b")
            toks = server._dm_enter(brick, CO_B, True)
            try:
                _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, step="confirm",
                                          p={"action": "add_sub"}))
            finally:
                server._dm_leave(toks)
            t.say(c, "yes", "m1")
        self.assertEqual(t.calls[0]["as"], "u_b")

    def test_the_old_pipeline_never_reads_across_it_asks(self):
        t = _Turn(brain=False)
        with _Ctx(_db()) as c:
            t.say(c, "what's open across all my jobs?", "m1")
            self.assertEqual(t.calls, [])
            self.assertTrue(_texts(c)[-1].startswith("Which company is this for?"))

    def test_one_account_is_answered_exactly_as_before(self):
        t = _Turn()

        async def never(*a, **k):
            raise AssertionError("a one-account person is never routed")
        with _Ctx(_db(two=False)) as c,                 patch.object(server, "_dm_route_accounts", never, create=True):
            t.say(c, "what's open across all my jobs?", "m1")
        self.assertEqual((t.calls[0]["as"], t.calls[0]["person"], t.calls[0]["history"]),
                         ("u_a", [], None))


class HistoryStaysWithItsCompany(unittest.TestCase):

    def _rows(self, db):
        now = datetime.now(timezone.utc)
        db.whatsapp_messages.rows += [
            {"group_id": CHAT, "is_dm": True, "sender": "bot", "body": "legacy",
             "created_at": now - timedelta(minutes=9)},
            {"group_id": CHAT, "is_dm": True, "sender": "bot", "body": "acme answer",
             "dm_company": CO_A, "created_at": now - timedelta(minutes=8)},
            {"group_id": CHAT, "is_dm": True, "sender": "bot", "body": "brick answer",
             "dm_company": CO_B, "created_at": now - timedelta(minutes=7)},
            {"group_id": CHAT, "is_dm": True, "sender": "bot", "body": "both",
             "dm_company": server.DM_SCOPE_MULTI, "created_at": now - timedelta(minutes=6)},
            {"group_id": CHAT, "is_dm": True, "sender": "bot", "body": "which company?",
             "dm_company": server.DM_SCOPE_NEUTRAL, "created_at": now - timedelta(minutes=5)},
        ]
        return now

    def _bodies(self, db, scope, multi, brain=False):
        now = datetime.now(timezone.utc)
        toks = server._dm_enter({"user_id": "u"}, scope, multi)
        try:
            with patch.object(server, "db", db):
                rows = _run(server._dm_brain_history(CHAT, now) if brain
                            else server._dm_history(CHAT, now))
        finally:
            server._dm_leave(toks)
        return [r["body"] for r in rows]

    def test_a_company_turn_reads_its_own_company_only(self):
        db = _db()
        self._rows(db)
        for brain in (False, True):
            self.assertEqual(self._bodies(db, CO_B, True, brain), ["brick answer", "which company?"])
            self.assertEqual(self._bodies(db, CO_A, True, brain), ["acme answer", "which company?"])
            self.assertEqual(self._bodies(db, server.DM_SCOPE_MULTI, True, brain),
                             ["both", "which company?"])

    def test_one_account_reads_the_whole_chat_as_before(self):
        db = _db(two=False)
        self._rows(db)
        self.assertEqual(self._bodies(db, CO_A, False),
                         ["legacy", "acme answer", "brick answer", "both", "which company?"])

    def test_the_turns_rows_carry_its_company(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            brick = next(a for a in _run(server._dm_identities(CHAT)) if a["user_id"] == "u_b")
            toks = server._dm_enter(brick, CO_B, True)
            try:
                _run(server._open_dm_reply_window(ADMIN_PHONE))
                _run(server._dm_store_inbound(brick, CHAT, "how many at oak", "m1"))
                _run(server.send_whatsapp_message(CHAT, "3 on site at 40 Oak Ave"))
            finally:
                server._dm_leave(toks)
            toks = server._dm_enter(None, server.DM_SCOPE_MULTI, True)
            try:
                _run(server._dm_store_inbound(brick, CHAT, "across everything?", "m2"))
            finally:
                server._dm_leave(toks)
            rows = [(r["body"], r.get("dm_company"), r.get("company_id"))
                    for r in c.db.whatsapp_messages.rows]
        self.assertEqual(rows, [("how many at oak", CO_B, CO_B),
                                ("3 on site at 40 Oak Ave", CO_B, None),
                                ("across everything?", server.DM_SCOPE_MULTI, None)])


class TheBrainReadsAcrossAsEachJobsAccount(unittest.TestCase):

    def _ctx(self, db, text="x"):
        person = _run(server._dm_identities(CHAT))
        jobs = _run(server._dm_person_jobs(person))
        return {"ident": person[0], "person": person, "dm_chat": CHAT, "text": text,
                "jobs": jobs, "by_id": {j["id"]: j for j in jobs}, "active": None,
                "dry_run": False, "sent": [], "used_job": None, "t0": None}

    def test_a_job_tool_acts_as_that_jobs_company(self):
        seen = []

        async def dispatch(name, args, *, project_id, company_id, **k):
            seen.append((project_id, company_id))
            return "ok"
        with _Ctx(_db()), patch.object(server, "_dispatch_agent_tool", dispatch):
            db_ctx = self._ctx(None)
            _run(server._dm_brain_exec(db_ctx, "punch_status", {"job": "40 oak"}))
            _run(server._dm_brain_exec(db_ctx, "punch_status", {"job": "12 main"}))
            self.assertEqual(db_ctx["ident"]["user_id"], "u_a", "put back after the call")
        self.assertEqual(seen, [(OAK, CO_B), (MAIN, CO_A)])

    def test_the_same_street_is_named_with_each_company(self):
        with _Ctx(_db()):
            out = _run(server._dm_brain_exec(self._ctx(None), "punch_status",
                                             {"job": "588 boyland"}))
        self.assertIn(f"588 Thomas S Boyland St ({NAME_A})", out)
        self.assertIn(f"588 Thomas S Boyland St ({NAME_B})", out)

    def test_a_change_with_no_one_company_writes_nothing_and_asks(self):
        with _Ctx(_db()) as c:
            ctx = self._ctx(None, text="add a job at 9 Menahan St")
            out = json.loads(_run(server._dm_brain_exec(
                ctx, "propose_change", {"action": "add_job", "address": "9 Menahan St"})))
            pick = _run(server._dm_state_get(server.DM_ACCT_PICK_STATE, CHAT))
            pending = _run(server._dm_state_get(server.DM_ACTION_STATE, CHAT))
        self.assertEqual(out["status"], "needs_an_answer")
        self.assertEqual(out["options"], [NAME_A, NAME_B])
        self.assertIsNone(pending)
        self.assertEqual((pick["held"], pick["user_ids"]), ("add a job at 9 Menahan St",
                                                            ["u_a", "u_b"]))

    def test_the_subs_list_is_each_companys_under_its_name(self):
        seen = []

        async def subs(ident, name, args, project):
            seen.append(ident["company_id"])
            return f"subs of {ident['company_id']}"
        with _Ctx(_db()), patch.object(server, "_dm_subs_tool", subs):
            out = _run(server._dm_brain_exec(self._ctx(None), "list_subs", {}))
        self.assertEqual(seen, [CO_A, CO_B])
        self.assertEqual(out, f"{NAME_A}:\nsubs of {CO_A}\n\n{NAME_B}:\nsubs of {CO_B}")

    def test_the_model_is_told_every_job_with_its_company(self):
        seen = {}

        async def run(ctx, messages, system, model=None):
            seen["system"], seen["jobs"] = system, [j["id"] for j in ctx["jobs"]]
            return {"reply": "ok", "trace": []}
        with _Ctx(_db()), patch.object(server, "_dm_brain_run", run):
            person = _run(server._dm_identities(CHAT))
            _run(server._dm_brain_answer(person[0], CHAT, "what's open?", history=[],
                                         now=datetime.now(timezone.utc), person=person))
        self.assertEqual(sorted(seen["jobs"]), sorted([MAIN, BOYLAND_A, OAK, BOYLAND_B]))
        self.assertIn(f"admin at {NAME_A}; project manager at {NAME_B}", seen["system"])
        self.assertIn(f"{OAK}: 40 Oak Ave ({NAME_B})", seen["system"])

    def test_a_group_tool_for_the_second_company_acts_as_that_account(self):
        """find_sub / list_subs from a DM for a Brick job: before, the DM's
        one identity (Acme) was compared with Brick and refused."""
        seen = []

        async def subs(ident, name, args, project):
            seen.append((ident["user_id"], str(project.get("_id"))))
            return "ok"
        with _Ctx(_db()), patch.object(server, "_dm_subs_tool", subs):
            out = _run(server._dispatch_agent_tool(
                "list_subs", {}, project_id=OAK, group_id=CHAT, company_id=CO_B,
                sender=ADMIN_PHONE))
        self.assertEqual((out, seen), ("ok", [("u_b", OAK)]))


class OneBriefPerPerson(unittest.TestCase):
    THU_7 = datetime(2026, 10, 8, 11, 5, tzinfo=timezone.utc)     # Thu 7:05 AM ET

    def _world(self):
        from tests.test_whatsapp_gc_alerts import synced_state
        from tests.test_whatsapp_morning_brief import _violation
        db = _db()
        # A new violation on every job, so each job has its own message.
        for i, (pid, co) in enumerate(((MAIN, CO_A), (BOYLAND_A, CO_A), (OAK, CO_B),
                                       (BOYLAND_B, CO_B))):
            db.dob_logs.rows.append(_violation(pid, f"3512345{i}", _id=f"v_{pid}"))
            db[server.SOURCE_SYNC_STATE].rows.append(synced_state(pid, (pid, co)))
        # Acme's brief at 8, Brick's at 7: the person's ONE brief is at 7.
        db.notification_preferences.rows += [
            {"_id": "np_a", "user_id": "u_a", "project_id": None,
             "whatsapp": {"brief_time": "08:00"}},
            {"_id": "np_b", "user_id": "u_b", "project_id": None,
             "whatsapp": {"brief_time": "07:00"}}]
        return db

    def test_one_brief_with_both_companies_jobs_sent_once(self):
        with _Ctx(self._world()) as c:
            r = _run(server._morning_brief_tick(now=self.THU_7))
            texts = _texts(c)
            ledger = sorted(row["_id"] for row in c.db[server.WA_LEDGER].rows)
            logs = {row["_id"]: row["status"] for row in c.db[server.wa_facts.BRIEF_LOG].rows}
            again = _run(server._morning_brief_tick(now=self.THU_7 + timedelta(minutes=5)))
        self.assertEqual((r["sent"], r.get("merged")), (1, 1))
        self.assertEqual(again["sent"], 0)
        body = "\n".join(texts)
        for label in (f"12 Main St ({NAME_A})", f"40 Oak Ave ({NAME_B})",
                      f"588 Thomas S Boyland St ({NAME_A})",
                      f"588 Thomas S Boyland St ({NAME_B})"):
            self.assertIn(label, body)
        # Every message went out once, as the lead (Acme, connected first);
        # Brick's account is marked as briefed (its brief_status, "since").
        parts = [k for k in ledger if k.count(":") > 3]
        self.assertEqual(len(parts), 4)
        self.assertTrue(all(k.startswith("u_a:") for k in parts), ledger)
        self.assertIn("u_b:-:morning_brief:2026-10-08", ledger)
        self.assertEqual(logs, {"u_a:2026-10-08": "sent", "u_b:2026-10-08": "sent"})

    def test_each_job_message_is_its_own_companys_history(self):
        with _Ctx(self._world()) as c:
            _run(server._morning_brief_tick(now=self.THU_7))
            rows = [(r["body"].split("\n", 1)[0], r.get("dm_company"))
                    for r in c.db.whatsapp_messages.rows]
        companies = {body: co for body, co in rows}
        self.assertTrue(any(co == CO_B and "40 Oak Ave" in b for b, co in companies.items()), rows)
        self.assertTrue(any(co == CO_A and "12 Main St" in b for b, co in companies.items()), rows)

    def test_a_company_in_shabbos_is_left_out(self):
        async def quiet(company_id, project_id, now):
            return now + timedelta(hours=10) if str(company_id) == CO_A else None
        with _Ctx(self._world()) as c, patch.object(server, "_shabbos_quiet", quiet):
            r = _run(server._morning_brief_tick(now=self.THU_7))
            body = "\n".join(_texts(c))
        self.assertEqual(r["sent"], 1)
        self.assertIn("40 Oak Ave", body)
        self.assertNotIn("12 Main St", body)

    def test_each_accounts_own_reminders_are_in_the_one_brief(self):
        db = self._world()
        for uid, co, title in (("u_a", CO_A, "call Acme's inspector"),
                               ("u_b", CO_B, "order Brick's rebar")):
            db.upcoming_events.rows.append(
                {"_id": f"r_{uid}", "company_id": co, "project_id": None, "user_id": uid,
                 "source": "dm", "kind": "reminder", "title": title, "date": "2026-10-08",
                 "status": "open", "history": []})
        with _Ctx(db) as c:
            r = _run(server._morning_brief_tick(now=self.THU_7))
            body = "\n".join(_texts(c))
        self.assertEqual(r["sent"], 1)
        self.assertEqual((body.count("call Acme's inspector"), body.count("order Brick's rebar")),
                         (1, 1))

    def test_send_me_my_brief_from_either_account_is_the_one_brief(self):
        with _Ctx(self._world()) as c:
            _run(server._open_dm_reply_window(ADMIN_PHONE))
            brick = c.db.users.rows[1]
            out = _run(server._brief_resend(brick, CHAT, self.THU_7))
            body = "\n".join(_texts(c))
        self.assertEqual(out, "sent")
        self.assertIn(f"12 Main St ({NAME_A})", body)
        self.assertIn(f"40 Oak Ave ({NAME_B})", body)


if __name__ == "__main__":
    unittest.main()
