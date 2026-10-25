"""The company's subs list in the DM (Tue Oct 13, 10:52 AM).

"Is there low voltage company in subs list?" -> "Which job?" -> 588 ->
"I can't check the full list of subcontractors here. Please use the app."

1. find_sub / list_subs (lib/wa_subs.py): every live job's roster, each sub
   with its trades, the jobs it is on and its punch contact there; low voltage
   is also LV / data / security / fire alarm cabling.
2. A question about the subs list is answered for the company: never "Which
   job?"; an admin's list is every job's, a PM's only their own jobs'.
3. Never "I can't check the subs" / "use the app": the reply is replaced by
   the tool's own words (the company path and the job agent alike).
4. The DM prompt: changes are asked for in the chat, the subs are tools.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_assistant, wa_sender_map, wa_subs  # noqa: E402
from tests.test_dm_routing_order import _Dm  # noqa: E402
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    ADMIN_PHONE, CO_A, PM_PHONE, THOMAS, WALWORTH, _Ctx, _db, _optin, _payload, _run,
)

LIVE_Q = "Is there low voltage company in subs list?"
DENIAL = "I can't check the full list of subcontractors here. Please use the app."


def _world(pm=False):
    db = _db()
    _optin(db, "u_pm" if pm else "u_admin", PM_PHONE if pm else ADMIN_PHONE)
    for p in db.projects.rows:
        if p["_id"] == THOMAS:
            p["trade_assignments"] = [
                {"id": "t1", "company": "Power Direct", "trade": "Electrical"},
                {"id": "t_lv", "company": "Spark Data & Security", "trade": "Low Voltage"}]
        if p["_id"] == WALWORTH:
            p["trade_assignments"] = [
                {"id": "t2", "company": "Arkon", "trade": "Drywall"},
                {"id": "t3", "company": "Power Direct", "trade": "Electrical"},
                {"id": "t4", "company": "Old Sub", "trade": "Painting", "status": "inactive"}]
    db[wa_sender_map.COLLECTION].rows.append(
        {"_id": "m_chris", "company_id": CO_A, "person_name": "Chris Lopez",
         "sub_company": "Spark Data & Security", "sender_jid": "17185550302@c.us",
         "phone": "17185550302"})
    db.notification_preferences.rows.append(
        {"_id": "np1", "user_id": None, "project_id": THOMAS, "scope": "project",
         "whatsapp_project": {"punch_contacts": {"t_lv": "m_chris"}}})
    return db


def _model(*turns):
    """A scripted model: each turn a tool call (name, args) or a reply."""
    calls = []

    async def model(messages, tool_choice):
        calls.append((list(messages), tool_choice))
        turn = turns[len(calls) - 1] if len(calls) <= len(turns) else "done"
        if isinstance(turn, tuple):
            name, args = turn
            return {"content": "", "tool_calls": [{"id": f"c{len(calls)}", "type": "function",
                                                   "function": {"name": name,
                                                                "arguments": json.dumps(args)}}]}
        return None if turn is None else {"content": turn}
    model.calls = calls
    return model


# ── 1. The tools ─────────────────────────────────────────────────────────────

class TheList(unittest.TestCase):

    def rows(self):
        db = _world()
        ident = {"company_id": CO_A, "projects": [p for p in db.projects.rows
                                                  if p["_id"] in (THOMAS, WALWORTH)]}
        with _Ctx(db=db):
            return _run(server._dm_subs_rows(ident)), ident, db

    def test_every_jobs_roster_with_the_punch_contact(self):
        rows, _i, _db_ = self.rows()
        self.assertEqual(sorted((r["company"], r["trade"], r["job"], r["contact"]) for r in rows), [
            ("Arkon", "Drywall", "8 Walworth St", None),
            ("Power Direct", "Electrical", "588 Thomas S Boyland St", None),
            ("Power Direct", "Electrical", "8 Walworth St", None),
            ("Spark Data & Security", "Low Voltage", "588 Thomas S Boyland St", "Chris Lopez"),
        ])                                                  # the inactive row is not on it

    def test_low_voltage_is_lv_data_security_fire_alarm(self):
        rows = [{"company": c, "trade": t, "job": "588", "job_id": "p", "contact": None}
                for c, t in (("Spark", "Low Voltage"), ("Netcom", "Data"), ("Guard Co", "Security"),
                             ("Firewatch", "Fire Alarm"), ("Wire Pros", "Structured Cabling"),
                             ("Power Direct", "Electrical"), ("Arkon", "Plumbing"))]
        for said in ("low voltage", "LV", "lv guys", "data", "security", "fire alarm cabling",
                     "is there low voltage company"):
            with self.subTest(said):
                self.assertEqual(sorted(r["company"] for r in wa_subs.find(said, rows)),
                                 ["Firewatch", "Guard Co", "Netcom", "Spark", "Wire Pros"])
        self.assertEqual([r["company"] for r in wa_subs.find("electrician", rows)], ["Power Direct"])
        self.assertEqual([r["company"] for r in wa_subs.find("plomero", rows)], ["Arkon"])
        self.assertEqual([r["company"] for r in wa_subs.find("arkon", rows)], ["Arkon"])
        self.assertEqual(wa_subs.find("roofer", rows), [])

    def test_find_says_who_and_where(self):
        rows, _i, _db_ = self.rows()
        self.assertEqual(wa_subs.render_find("low voltage", rows), "\n".join([
            "Yes — 1 match for low voltage in your subs list:",
            "• Spark Data & Security (Low Voltage) — on 588 Thomas S Boyland St — "
            "punch contact Chris Lopez"]))
        self.assertEqual(wa_subs.render_find("roofer", rows),
                         "No roofer sub in your subs list. "
                         "Trades on the list: Drywall, Electrical, Low Voltage.")

    def test_list_and_one_jobs_list(self):
        rows, ident, db = self.rows()
        self.assertEqual(wa_subs.render_list(rows), "\n".join([
            "3 subs in your subs list:",
            "• Arkon (Drywall) — on 8 Walworth St",
            "• Power Direct (Electrical) — on 588 Thomas S Boyland St; 8 Walworth St",
            "• Spark Data & Security (Low Voltage) — on 588 Thomas S Boyland St — "
            "punch contact Chris Lopez"]))
        with _Ctx(db=db):
            one = _run(server._dm_subs_tool(ident, "list_subs", {"job": "walworth"}))
        self.assertEqual(one, "\n".join([
            "2 subs on 8 Walworth St:", "• Arkon (Drywall) — on 8 Walworth St",
            "• Power Direct (Electrical) — on 8 Walworth St"]))

    def test_never_a_number(self):
        rows, _i, _db_ = self.rows()
        for text in (wa_subs.render_list(rows), wa_subs.render_find("lv", rows)):
            self.assertNotRegex(text, r"\d{7,}")                  # never a number


# ── 2. A question about the list: answered for the company ──────────────────

class CompanyQuestions(unittest.TestCase):

    def test_what_is_one(self):
        for said in (LIVE_Q, "do we have a plumber?", "who's our electrician?", "list our subs",
                     "any LV company?", "do we have any data guys", "which subs do we have",
                     "is there a fire alarm sub", "who are our subcontractors"):
            with self.subTest(said):
                self.assertTrue(wa_subs.company_question(said))
        for said in ("any electricians on site today?", "how many workers on 588",
                     "is there an inspection today?", "do we have a permit for 588?",
                     "what's open", "who checked in", "is Arkon working today?"):
            with self.subTest(said):
                self.assertFalse(wa_subs.company_question(said))


class TheLiveDm(_Dm, unittest.TestCase):

    def ask(self, model, said=LIVE_Q, pm=False):
        db = _world(pm=pm)
        chat = f"{PM_PHONE if pm else ADMIN_PHONE}@c.us"
        with _Ctx(db=db) as c, patch.object(server, "_dm_subs_model", model):
            self._send(c, chat, said, mid="S1")
            replies = [p["message"] for p in c.wire.calls if "message" in p]
        return replies, db

    def test_the_live_question_answered_for_the_company(self):
        model = _model(("find_sub", {"trade_or_name": "low voltage"}),
                       "Yes — Spark Data & Security (Low Voltage) is on 588 Thomas S Boyland St; "
                       "punch contact Chris Lopez.")
        replies, db = self.ask(model)
        # The short job name (Thu 11:35 AM, lib/wa_style.py).
        self.assertEqual(replies, ["Yes — Spark Data & Security (Low Voltage) is on 588; "
                                   "punch contact Chris Lopez."])
        self.assertEqual(self.agent_calls, [])               # not the job agent
        self.assertEqual(model.calls[0][1], "required")      # a tool first, always
        tool_msg = model.calls[1][0][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn("Spark Data & Security", tool_msg["content"])
        logged = next(r for r in db[server.DM_ANSWERS].rows if r.get("path") == "subs")
        self.assertEqual(logged["tool_data"][0]["tool"], "find_sub")

    def test_never_which_job(self):
        for said in (LIVE_Q, "do we have a plumber?", "who are our subs?"):
            with self.subTest(said):
                replies, _db_ = self.ask(_model(None), said)          # the model is down
                self.assertEqual(len(replies), 1)
                self.assertNotIn("Which job", replies[0])
        replies, _db_ = self.ask(_model(None))
        self.assertTrue(replies[0].startswith("Yes — 1 match for low voltage"), replies[0])
        self.assertIn("on 588", replies[0])                  # the short job name

    def test_a_denial_is_replaced_by_the_tool(self):
        model = _model(("find_sub", {"trade_or_name": "low voltage"}), DENIAL)
        replies, _db_ = self.ask(model)
        self.assertTrue(replies[0].startswith("Yes — 1 match for low voltage"), replies[0])
        self.assertNotIn("app", replies[0])

    def test_a_number_not_in_the_results_is_replaced(self):
        model = _model(("find_sub", {"trade_or_name": "low voltage"}),
                       "Yes, 3 low voltage subs.")
        replies, _db_ = self.ask(model)
        self.assertTrue(replies[0].startswith("Yes — 1 match"), replies[0])

    def test_a_pm_sees_only_their_jobs(self):
        replies, _db_ = self.ask(_model(None), "do we have a drywall sub?", pm=True)
        self.assertEqual(replies, ["No drywall sub in your subs list. "
                                   "Trades on the list: Electrical, Low Voltage."])


class CodexOn780(_Dm, unittest.TestCase):

    def test_a_general_question_is_not_the_list(self):
        for said in ("what is a subcontractor?", "what does a subcontractor do?",
                     "how do subs get paid?"):
            with self.subTest(said):
                self.assertFalse(wa_subs.company_question(said))
        self.assertTrue(wa_subs.company_question("who are our subcontractors?"))

    def test_a_company_by_name(self):
        names = ["Arkon", "Power Direct"]
        for said in ("do we use Arkon?", "do we have power direct?"):
            with self.subTest(said):
                self.assertTrue(wa_subs.company_question(said, names))
        self.assertFalse(wa_subs.company_question("is Arkon working today?", names))
        replies, _db_ = TheLiveDm.ask(self, _model(None), "do we use Arkon?")
        self.assertTrue(replies[0].startswith("Yes — 1 match for arkon"), replies)

    def test_every_sub_never_cut(self):
        rows = [{"company": f"Sub {i:03d}", "trade": "Electrical", "job": "588", "job_id": "p",
                 "contact": None} for i in range(45)]
        text = wa_subs.render_list(rows)
        self.assertEqual(text.count("\n• "), 45)
        self.assertNotIn("more in the Levelog app", text)

    def test_a_pm_naming_a_job_they_are_not_on(self):
        db = _world(pm=True)
        with _Ctx(db=db) as c, patch.object(server, "_dm_subs_model", _model(None)):
            self._send(c, f"{PM_PHONE}@c.us", "which subs do we have on 8 walworth?", mid="S1")
            reply = [p["message"] for p in c.wire.calls if "message" in p][-1]
        self.assertTrue(reply.startswith("You're not on 8 Walworth St"), reply)

    def test_the_job_agent_tools_see_its_job_only(self):
        db = _world()
        with _Ctx(db=db):
            out = _run(server._dispatch_agent_tool(
                "find_sub", {"trade_or_name": "drywall"}, project_id=THOMAS,
                group_id=f"{ADMIN_PHONE}@c.us", company_id=CO_A, sender="x"))
        # Arkon (drywall) is on 8 Walworth only: never a yes for 588.
        self.assertTrue(out.startswith("No drywall sub on 588 Thomas S Boyland St."), out)


# ── 3. The job agent: the tools, and the backstop ───────────────────────────

class TheJobAgent(_Dm, unittest.TestCase):

    def test_a_denial_about_one_jobs_subs_is_replaced(self):
        """"who are the subs on 588?" names a job: the job agent (with
        find_sub / list_subs); its "use the app" is replaced by the list."""
        async def agent(**kw):
            self.agent_calls.append(kw)
            return DENIAL
        with _Ctx(db=_world()) as c, patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_dm_scope", lambda b: _done("project")):
            _run(server._process_whatsapp_message(
                _payload(f"{ADMIN_PHONE}@c.us", "who are the subs on 588?", "S1")))
            reply = [p["message"] for p in c.wire.calls if "message" in p][-1]
        self.assertEqual(self.agent_calls[0]["project_id"], THOMAS)     # never an "add a sub"
        self.assertEqual(reply, "\n".join([
            "2 subs on 588:",
            "• Power Direct (Electrical) — on 588",
            "• Spark Data & Security (Low Voltage) — on 588 — punch contact Chris Lopez"]))

    def test_a_question_is_never_a_request_to_add(self):
        from lib import dm_actions
        for said in ("who are the subs on 588?", "who is the plumber on 588",
                     "which is the electrician on 8 walworth"):
            with self.subTest(said):
                self.assertEqual(dm_actions.rules(said), {"action": "none"})
        self.assertEqual(dm_actions.rules("power direct is the electrician on 588")["action"],
                         "add_sub")

    def test_the_tools_are_offered_in_a_dm_only(self):
        names = [t["function"]["name"] for t in server._AGENT_TOOLS]
        self.assertIn("find_sub", names)
        self.assertIn("list_subs", names)
        db = _world()
        with _Ctx(db=db):
            in_group = _run(server._dispatch_agent_tool(
                "find_sub", {"trade_or_name": "lv"}, project_id=THOMAS, group_id="1@g.us",
                company_id=CO_A, sender="x"))
            in_dm = _run(server._dispatch_agent_tool(
                "find_sub", {"trade_or_name": "lv"}, project_id=THOMAS,
                group_id=f"{ADMIN_PHONE}@c.us", company_id=CO_A, sender="x"))
        self.assertEqual(in_group, "The subs list is read in a direct message only.")
        self.assertTrue(in_dm.startswith("Yes — 1 match for lv"), in_dm)


async def _done_coro(v):
    return v


def _done(v):
    return _done_coro(v)


# ── 4. The prompt: no "use the app" where a tool or the chat does it ────────

class ThePrompt(unittest.TestCase):

    def test_changes_and_subs(self):
        c = wa_assistant.DM_AGENT_CLAUSE
        self.assertNotIn("full worker roster", c)
        self.assertNotIn("change or create anything here", c)
        self.assertIn("find_sub and list_subs", c)
        self.assertIn("never say you cannot check the subs", c)
        self.assertIn("add Arkon to 588 as the plumber", c)
        self.assertIn("Never say you cannot check the subs", wa_subs.SYSTEM_PROMPT)

    def test_the_backstop_reads_denials(self):
        for r in (DENIAL, "I don't have access to the subcontractor list.",
                  "You can check that in the Levelog app.", "I'm unable to see your subs."):
            with self.subTest(r):
                self.assertTrue(wa_subs.denies_subs(r))
        self.assertFalse(wa_subs.denies_subs("Yes — Spark Data & Security is on 588."))


if __name__ == "__main__":
    unittest.main()
