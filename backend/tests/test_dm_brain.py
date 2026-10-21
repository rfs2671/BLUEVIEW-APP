"""The DM brain (lib/dm_brain.py, flag dm_brain_v2): one model with tools
answers every free-text DM; code keeps only the guardrails.

The model here is scripted (FakeLLM, the OpenAI-compatible client DeepInfra
is called through): each test says which tools it
calls and what it answers, and checks what the code around it does with
that -- the routing, the context it is given, the tools' scoping, the
number check, the confirm gate. The real model is measured by
scripts/dm_brain_eval.py.

Tue 9:02 AM, live:
  "Update on 588"   -> "588 Update / DOB Status: / Want the full list?" (cut)
  "Dot and Akron"   -> "No Dot or Akron sub"           (keyword sub match)
  "Arkon is framer" -> "I don't have that in the records."
"""

from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_brain  # noqa: E402
from tests.test_dm_short_answers import CHAT, _payload  # noqa: E402
from tests.test_dm_subs_on_site import _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402


def text(t):
    return SimpleNamespace(type="text", text=t)


def use(name, inp, i="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=i)


def resp(*blocks, stop=None):
    """A chat.completions response: the text, and the tool calls."""
    calls = [SimpleNamespace(id=b.id, type="function",
                             function=SimpleNamespace(name=b.name, arguments=json.dumps(b.input)))
             for b in blocks if b.type == "tool_use"]
    words = "\n".join(b.text for b in blocks if b.type == "text")
    msg = SimpleNamespace(content=words or None, tool_calls=calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=stop or ("tool_calls" if calls else "stop"))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, estimated_cost=0.0001))


class FakeLLM:
    """client.chat.completions.create, scripted. Each step is a response or
    a function of the request (to look at the tool results)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.chat = self
        self.completions = self

    async def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda o: getattr(o, "__dict__", str(o)))))
        step = self.script.pop(0)
        return step(kw) if callable(step) else step


def last_tool_results(call):
    """The tool results the request ends with."""
    out = []
    for m in reversed(call["messages"]):
        if m.get("role") != "tool":
            break
        out.insert(0, m["content"])
    return out


class _Brain(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        for p in self.db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"] = [
                    {"id": "r1", "company": "Arkon Builders", "trade": "General Construction"},
                    {"id": "r2", "company": "J&G", "trade": "Scaffolding"},
                    {"id": "r3", "company": "Quality Plumbing", "trade": "Plumbing"},
                ]
        self.n = 0
        self.reactions = []

    def trade(self, company):
        """The sub's trade on 588's ACTIVE roster (what the app shows)."""
        project = next(p for p in self.db.projects.rows if p["_id"] == THOMAS)
        return next(r.get("trade") for r in server._active_assignments(project)
                    if r.get("company") == company)

    def say(self, c, body, llm, quoted=None):
        self.n += 1
        before = len([p for p in c.wire.calls if "message" in p])

        async def on(ident):
            return True

        async def react(chat, mid, emoji):
            self.reactions.append(emoji)
            return True
        with patch.object(server, "_dm_brain_on", on), \
                patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "OPENAI_API_KEY", None):
            _run(server._process_whatsapp_message(_payload(CHAT, body, f"b{self.n}", quoted)))
        sends = [p["message"] for p in c.wire.calls if "message" in p]
        return sends[before:]


class TheTuesdayThree(_Brain):
    def test_update_on_588_goes_out_whole(self):
        """No length cutter: a real multi-line answer is sent as written."""
        answer = ("588: 31 on site — Arkon Builders 17, Quality Plumbing 6, J&G 4, Power Direct 4.\n"
                  "DOB: no new violations.\n"
                  "Open: 2 punch items past due.\n"
                  "Coming up: nothing scheduled this week.\n"
                  "Want the names?")

        def answer_from(kw):
            res = " ".join(last_tool_results(kw))
            self.assertIn('"on_site_now": 31', res)
            return resp(text(answer.replace("2 punch items", "punch items")))
        llm = FakeLLM(resp(use("headcount", {"job": "588"})), answer_from)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Update on 588", llm)
        self.assertEqual(out, [answer.replace("2 punch items", "punch items")])
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["path"], log["tool_data"][0]["tool"]), ("brain", "headcount"))

    def test_dot_and_akron(self):
        """The model reads the subs list and DOT itself; "Akron" is matched
        by the model, not by keywords."""
        self.db.dot_logs.rows.append({"_id": "d1", "project_id": THOMAS, "company_id": CO_A,
                                      "record_type": "permit", "number": "M01-2026123",
                                      "status": "ISSUED", "issue_date": "2026-10-01"})

        def answer(kw):
            res = "\n".join(last_tool_results(kw))
            self.assertIn("Arkon Builders", res)
            self.assertIn("M01-2026123", res)
            return resp(text("DOT: permit M01-2026123, issued. Arkon Builders is on 588."))
        llm = FakeLLM(resp(use("list_subs", {}, "a"), use("dot_status", {"job": "588"}, "b")),
                            answer)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Dot and Akron", llm)
        self.assertEqual(out, ["DOT: permit M01-2026123, issued. Arkon Builders is on 588."])

    def test_arkon_is_framer_saved_only_on_yes(self):
        def proposed(kw):
            res = json.loads(last_tool_results(kw)[0])
            self.assertEqual(res["status"], "waiting_for_their_yes")
            self.assertIn("Arkon Builders", res["would_change"])
            return resp(text("Got it — save Arkon Builders as Framing on 588? Reply yes."))
        llm = FakeLLM(resp(use("set_sub_trade", {"company": "Akron", "trade": "framer"})), proposed)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Arkon is framer", llm)
            self.assertEqual(self.trade("Arkon Builders"), "General Construction")   # nothing saved yet
            self.assertEqual(out, ["Got it — save Arkon Builders as Framing on 588? Reply yes."])
            done = self.say(c, "yes", FakeLLM())                  # the model is not asked
        self.assertEqual(self.trade("Arkon Builders"), "Framing")
        self.assertTrue(done[0].startswith("Saved: Arkon Builders"), done)


class TheContext(_Brain):
    def test_user_jobs_flows_and_history(self):
        now = datetime.now(timezone.utc)
        for i in range(25):
            self.db.whatsapp_messages.rows.append({
                "_id": f"h{i}", "group_id": CHAT, "is_dm": True, "body": f"old {i}",
                "sender": "bot" if i % 2 else "15550001111",
                "created_at": now - timedelta(minutes=60 - i)})
        llm = FakeLLM(resp(text("ok")))
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open", llm)
        call = llm.calls[0]
        context = call["messages"][0]["content"]
        self.assertIn("Their jobs", context)
        self.assertIn("588 Thomas", context)
        self.assertIn("Open flows: none.", context)
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertIn("Levelog Assistant", context)
        bodies = "\n".join(m["content"] for m in call["messages"][1:] if isinstance(m["content"], str))
        self.assertIn("old 24", bodies)
        self.assertNotIn("old 4\n", bodies + "\n")                  # only the last 20
        self.assertEqual(call["messages"][-1]["role"], "user")
        self.assertTrue(call["messages"][-1]["content"].endswith("what's open"))
        self.assertEqual(call["model"], dm_brain.MODEL)

    def test_an_open_change_is_in_the_context(self):
        _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                  step="ask:trade", options=[], asked="What trade is J&G?", misses=0))
        llm = FakeLLM(resp(text("Which trade?")))
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                      step="ask:trade", options=[], asked="What trade is J&G?", misses=0))
            self.say(c, "hmm", llm)
        self.assertIn("What trade is J&G?", llm.calls[0]["messages"][0]["content"])


class TheGuardrails(_Brain):
    def test_a_number_no_tool_gave_is_asked_again_not_cut(self):
        llm = FakeLLM(
            resp(use("headcount", {"job": "588"})),
            resp(text("588: 45 on site right now.")),                       # 45 is nowhere
            lambda kw: (self.assertIn("45", kw["messages"][-1]["content"]),
                        resp(text("588: 31 on site right now.")))[1])
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many at 588", llm)
        self.assertEqual(out, ["588: 31 on site right now."])
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["verify_retries"], 1)

    def test_still_unverified_after_retries_is_said_plainly(self):
        llm = FakeLLM(resp(text("45 on site.")), resp(text("46 on site.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many at 588", llm)
        self.assertEqual(out, [dm_brain.UNVERIFIED_TEXT])
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["draft"], "46 on site.")
        # The one retry is on the same model (Max only writes report summaries).
        self.assertEqual([c_["model"] for c_ in llm.calls], [dm_brain.MODEL, dm_brain.MODEL])

    def test_no_phone_numbers(self):
        llm = FakeLLM(resp(text("Call him at 718-555-0123.")))
        with patch.object(dm_brain, "unverified", lambda r, s: []):
            with _Ctx(db=self.db) as c:
                out = self.say(c, "who's the super's number", llm)
        self.assertEqual(out, ["Call him at [number]."])

    def test_another_companys_job_is_not_theirs(self):
        def answer(kw):
            self.assertIn("None of their jobs matches", last_tool_results(kw)[0])
            return resp(text("That job isn't one of yours."))
        llm = FakeLLM(resp(use("open_items", {"job": "99 Bedford"})), answer)
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open at 99 bedford", llm)

    def test_a_proposed_change_changes_nothing(self):
        def proposed(kw):
            res = json.loads(last_tool_results(kw)[0])
            self.assertIn(res["status"], ("waiting_for_their_yes", "needs_an_answer"))
            return resp(text("Add Power Direct to 588 as Electrical? Reply yes."))
        llm = FakeLLM(resp(use("propose_change", {"action": "add_sub", "company": "Power Direct",
                                                        "trade": "Electrical", "job": "588"})), proposed)
        before = [dict(r) for r in self.db.projects.rows[0]["trade_assignments"]]
        with _Ctx(db=self.db) as c:
            out = self.say(c, "put power direct on 588 as electrician", llm)
        self.assertEqual(self.db.projects.rows[0]["trade_assignments"], before)
        self.assertEqual(out, ["Add Power Direct to 588 as Electrical? Reply yes."])

    def test_the_model_cannot_answer_its_own_confirm(self):
        _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                  step="confirm", options=[], asked="Add it?", misses=0))

        def refused(kw):
            self.assertIn("theirs", last_tool_results(kw)[0])
            return resp(text("Reply yes to add it."))
        llm = FakeLLM(resp(use("answer_pending_change", {"answer": "yes"})), refused)
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                      step="confirm", options=[], asked="Add it?", misses=0))
            self.say(c, "go for it i guess", llm)

    def test_undo_needs_a_yes_too(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Arkon is framer", FakeLLM(
                resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                resp(text("Save it? Reply yes."))))
            self.say(c, "yes", FakeLLM())
            self.assertEqual(self.trade("Arkon Builders"), "Framing")
            self.say(c, "undo that", FakeLLM(resp(use("undo_last_change", {})),
                                                resp(text("Undo it? Reply yes."))))
            self.assertEqual(self.trade("Arkon Builders"), "Framing")
            self.say(c, "yes", FakeLLM())
        self.assertEqual(self.trade("Arkon Builders"), "General Construction")

    def test_no_after_a_proposal_cancels(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Arkon is framer", FakeLLM(
                resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                resp(text("Save it? Reply yes."))))
            out = self.say(c, "no", FakeLLM())
        self.assertEqual(self.trade("Arkon Builders"), "General Construction")
        self.assertEqual(len(out), 1, out)                          # one plain "won't do it"


class TheLoop(_Brain):
    def test_tools_run_one_after_another_and_stop_at_six(self):
        order = []
        real = server._dm_brain_exec

        async def exec_(ctx, name, args):
            order.append(name)
            return await real(ctx, name, args)
        many = [resp(use("list_subs", {}, f"c{i}")) for i in range(6)]
        llm = FakeLLM(*many, lambda kw: (self.assertEqual(kw["tool_choice"], "none"),
                                           resp(text("Arkon Builders is on 588.")))[1])
        with _Ctx(db=self.db) as c, patch.object(server, "_dm_brain_exec", exec_):
            out = self.say(c, "who's on the subs list", llm)
        self.assertEqual(out, ["Arkon Builders is on 588."])
        self.assertEqual(order, ["list_subs"] * dm_brain.MAX_TOOL_CALLS)
        self.assertEqual([c_["tool_choice"] for c_ in llm.calls], ["auto"] * 6 + ["none"])

    def test_two_calls_in_one_response_run_in_order(self):
        order = []
        real = server._dm_brain_exec

        async def exec_(ctx, name, args):
            order.append(name)
            return await real(ctx, name, args)
        llm = FakeLLM(resp(use("dot_status", {"job": "588"}, "a"), use("list_subs", {}, "b")),
                         lambda kw: (self.assertEqual([m["tool_call_id"] for m in kw["messages"][-2:]],
                                                      ["a", "b"]), resp(text("DOT: nothing open.")))[1])
        with _Ctx(db=self.db) as c, patch.object(server, "_dm_brain_exec", exec_):
            self.say(c, "dot?", llm)
        self.assertEqual(order, ["dot_status", "list_subs"])

    def test_thinking_is_not_sent(self):
        llm = FakeLLM(resp(text("<think>they want the subs</think>Arkon Builders is on 588.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "subs?", llm)
        self.assertEqual(out, ["Arkon Builders is on 588."])

    def test_cost_and_time_are_logged(self):
        llm = FakeLLM(resp(text("Arkon Builders is on 588.")))
        with _Ctx(db=self.db) as c:
            self.say(c, "subs?", llm)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["model"], log["usage"]["cost_usd"], log["usage"]["input"]),
                         (dm_brain.MODEL, 0.0001, 100))

    def test_report_summary_on_the_stronger_model(self):
        rep = {"job": "588 Thomas", "period": "Oct 1 – Oct 14"}

        async def on(ident):
            return True
        llm = FakeLLM(resp(text("A quiet two weeks at 588 Thomas.")))
        with patch.object(server, "_dm_brain_on", on), patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server.progress_report, "facts", lambda r: ["Job 588 Thomas"]), \
                patch.object(server.progress_report, "check_summary", lambda t, r: True):
            got = _run(server._report_summary(rep, CO_A))
        self.assertEqual(got, "A quiet two weeks at 588 Thomas.")
        self.assertEqual(llm.calls[0]["model"], dm_brain.ESCALATE_MODEL)


class TheFlashFixes(_Brain):
    """Eval of Oct 20 (Qwen 3.8 Flash): #37 "*Ark" after 26 s; "from you" on
    someone else's voice note; "sent" with no send; the retry on Max."""

    def test_a_cut_reply_is_asked_again_with_a_bigger_budget(self):
        llm = FakeLLM(resp(use("list_subs", {})), resp(text("*Ark"), stop="length"),
                      resp(text("*Arkon Builders* is on 588.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "who's the framer", llm)
        self.assertEqual(out, ["*Arkon Builders* is on 588."])
        self.assertEqual([c_["max_tokens"] for c_ in llm.calls],
                         [dm_brain.MAX_TOKENS] * 2 + [dm_brain.RETRY_MAX_TOKENS])
        self.assertIn("cut off", llm.calls[2]["messages"][-1]["content"])

    def test_cut_twice_is_never_sent(self):
        llm = FakeLLM(resp(use("list_subs", {})), resp(text("*Ark")), resp(text("*Arkon")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "who's the framer", llm)
        self.assertEqual(out, [dm_brain.TRUNCATED_TEXT])
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["stop"], log["draft"]), ("truncated", "*Arkon"))

    def test_a_short_whole_answer_after_one_retry_goes(self):
        llm = FakeLLM(resp(use("list_subs", {})), resp(text("Arkon.")), resp(text("Arkon.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "framer?", llm)
        self.assertEqual(out, ["Arkon."])

    def test_sent_with_no_send_is_rewritten(self):
        def again(kw):
            self.assertIn("no tool this turn did that", kw["messages"][-1]["content"])
            return resp(text("SSP-011.00 is in the drawings for 588. Want me to send it?"))
        llm = FakeLLM(resp(text("Sent you the sheet.")), again)
        with patch.object(dm_brain, "unverified", lambda r, s_: []):
            with _Ctx(db=self.db) as c:
                out = self.say(c, "show me the sheet", llm)
        self.assertEqual(out, ["SSP-011.00 is in the drawings for 588. Want me to send it?"])

    def test_sent_twice_with_no_send_is_never_sent(self):
        llm = FakeLLM(resp(text("Sent you the sheet.")), resp(text("Sent it over.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "show me the sheet", llm)
        self.assertEqual(out, [dm_brain.ACTION_UNVERIFIED_TEXT])

    def test_cancelled_after_the_tool_did_it_goes(self):
        _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                  step="ask:trade", options=[], asked="What trade?", misses=0))
        llm = FakeLLM(resp(use("cancel_pending_change", {})), resp(text("Cancelled — nothing was added.")))
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                      step="ask:trade", options=[], asked="What trade?", misses=0))
            out = self.say(c, "forget the J&G thing", llm)
        self.assertEqual(out, ["Cancelled — nothing was added."])

    def test_from_you_only_when_the_record_is_theirs(self):
        async def notes(company_id, project_id, n=3, sender=""):
            return "🎤 Tue Oct 20, 9:14 AM · Meilich Friedman · 588 Site\nSaid: “core drill on 3”"
        llm = FakeLLM(resp(use("recent_voice_notes", {"job": "588"})),
                      resp(text("Your voice note: core drill on 3.")),
                      lambda kw: (self.assertIn("(you)", kw["messages"][-1]["content"]),
                                  resp(text("Meilich Friedman's voice note: core drill on 3.")))[1])
        with _Ctx(db=self.db) as c, patch.object(server, "_recent_voice_notes", notes):
            out = self.say(c, "what was the last voice note", llm)
        self.assertEqual(out, ["Meilich Friedman's voice note: core drill on 3."])

    def test_from_you_stays_when_marked(self):
        async def notes(company_id, project_id, n=3, sender=""):
            return "🎤 Tue Oct 20, 9:14 AM · Roy (you) · 588 Site\nSaid: “core drill on 3”"
        llm = FakeLLM(resp(use("recent_voice_notes", {"job": "588"})),
                      resp(text("Your voice note: core drill on 3.")))
        with _Ctx(db=self.db) as c, patch.object(server, "_recent_voice_notes", notes):
            out = self.say(c, "what was my last voice note", llm)
        self.assertEqual(out, ["Your voice note: core drill on 3."])

    def test_who_is_the_asker(self):
        tok = server._DM_ASKER.set({"user_id": "u_admin", "phones": ["17185550100"]})
        try:
            self.assertTrue(server._dm_is_asker("17185550100@c.us", None))
            self.assertTrue(server._dm_is_asker("7185550100@s.whatsapp.net", None))   # with or without the 1
            self.assertFalse(server._dm_is_asker("17185550100@lid", None))           # a @lid is no phone
            self.assertTrue(server._dm_is_asker("123@lid", {"kind": "user", "id": "u_admin"}))
            self.assertFalse(server._dm_is_asker("17185550199@c.us", {"kind": "user", "id": "u_meilich",
                                                                      "name": "Meilich Friedman"}))
            self.assertFalse(server._dm_is_asker("", {"kind": "worker", "id": "u_admin"}))
        finally:
            server._DM_ASKER.reset(tok)
        self.assertFalse(server._dm_is_asker("17185550100@c.us", None))      # no asker: never "you"

    def test_typing_while_it_thinks(self):
        seen = []

        async def typing(chat, on=True):
            seen.append(on)
            return True

        class Slow:
            def __init__(self):
                self.chat = self
                self.completions = self

            async def create(self, **kw):
                await asyncio.sleep(0.05)
                return resp(text("Arkon Builders is on 588."))
        with _Ctx(db=self.db) as c, patch.object(server, "_wa_typing", typing), \
                patch.object(server, "DM_TYPING_EVERY_SECONDS", 0.01):
            out = self.say(c, "subs?", Slow())
        self.assertEqual(out, ["Arkon Builders is on 588."])
        self.assertGreaterEqual(seen.count(True), 2)                 # refreshed while it worked
        self.assertEqual(seen[-1], False)                            # and stopped


class TheWalkthrough(_Brain):
    def test_photo_talk_goes_to_the_brain_not_a_regex(self):
        q = ("I'm going to show you some pictures, I need to do a checklist, it's not going to be "
             "sent to anyone, just for me.")
        llm = FakeLLM(resp(text("Send them here with a caption each; nothing goes out until you say send.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, q, llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(out, ["Send them here with a caption each; nothing goes out until you say send."])

    def test_exact_walk_commands_stay_in_code(self):
        llm = FakeLLM()
        with _Ctx(db=self.db) as c:
            out = self.say(c, "start walkthrough at 588", llm)
        self.assertEqual(llm.calls, [])
        self.assertTrue(out[0].startswith("Walkthrough at"), out)


class TheEvalMode(unittest.TestCase):
    def test_dry_run_writes_no_state(self):
        db = _db()
        for p in db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"] = [{"id": "r1", "company": "Arkon Builders", "trade": "General Construction"}]
        ident = {"user": {"name": "Admin"}, "user_id": "u_admin", "company_id": CO_A,
                 "role": "admin", "projects": [p for p in db.projects.rows
                                               if p["_id"] in (THOMAS, WALWORTH)]}
        llm = FakeLLM(resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                            resp(text("Save Arkon as Framing? Reply yes.")))
        with _Ctx(db=db), patch.object(server, "_dm_brain_client", lambda: llm):
            out = _run(server._dm_brain_answer(ident, CHAT, "Arkon is framer", history=[],
                                               now=datetime.now(timezone.utc), dry_run=True,
                                               flows=[], active=None))
        self.assertEqual(out["reply"], "Save Arkon as Framing? Reply yes.")
        self.assertEqual(db[server._DM_STATE].rows, [])


class TheFlag(unittest.TestCase):
    def test_per_company_and_needs_a_key(self):
        from lib import feature_flags
        db = _db()
        db.feature_flags.rows.append({"_id": "f1", "flag": dm_brain.FLAG, "enabled_globally": False,
                                      "enabled_for_companies": [CO_A], "enabled_for_users": [],
                                      "enabled_percentage": 0})
        mine = {"company_id": CO_A, "user_id": "u_admin"}
        other = {"company_id": "co_other", "user_id": "u_x"}
        with _Ctx(db=db):
            feature_flags.cache_invalidate()
            with patch.object(server, "DM_BRAIN_API_KEY", "k"):
                self.assertTrue(_run(server._dm_brain_on(mine)))
                self.assertFalse(_run(server._dm_brain_on(other)))
            with patch.object(server, "DM_BRAIN_API_KEY", ""):
                self.assertFalse(_run(server._dm_brain_on(mine)))      # no key: the old pipeline
            feature_flags.cache_invalidate()


class TheLib(unittest.TestCase):
    def test_unverified(self):
        src = ['{"on_site_now": 31, "by_sub": [{"sub": "Arkon", "on_site": 17}]} brief at 8:01', "588 Thomas"]
        self.assertEqual(dm_brain.unverified("31 on site at 588, Arkon 17, since 8:01.", src), [])
        self.assertEqual(dm_brain.unverified("32 on site.", src), ["32"])
        self.assertEqual(dm_brain.unverified("Permit M01-99 is open.", src), ["M01-99"])
        self.assertEqual(dm_brain.unverified("1,200 sq ft", ["1200"]), [])

    def test_redact(self):
        self.assertEqual(dm_brain.redact_phones("(718) 555-0123 or 7185550123"), "[number] or [number]")
        self.assertEqual(dm_brain.redact_phones("Permit 321234567-01-EW"), "Permit 321234567-01-EW")

    def test_history(self):
        now = datetime.now(timezone.utc)
        rows = [{"sender": "bot", "body": "brief", "created_at": now},
                {"sender": "1", "body": "a", "created_at": now},
                {"sender": "1", "body": "b", "created_at": now},
                {"sender": "bot", "body": "c", "created_at": now},
                {"sender": "1", "body": "old", "created_at": now - timedelta(days=9)}]
        self.assertEqual(dm_brain.history_messages(rows, now),
                         [{"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}])

    def test_an_iso_date_vouches_for_its_parts(self):
        # Oct 20 eval (Dot and Akron): "2026-09-18" in the answer, the tool's
        # "2026-09-18T00:00:00" -- "18" was not found and a right answer blocked.
        src = ['{"issued": "2026-09-18T00:00:00"}']
        self.assertEqual(dm_brain.unverified("Issued 2026-09-18 (Sep 18).", src), [])
        self.assertEqual(dm_brain.unverified("27 on site.", src), ["27"])        # still caught

    def test_only_the_latest_message_is_answered(self):
        # Oct 20 eval #37: an earlier "546 starting checklist" with no reply
        # after it was answered again with "How many arkon guys on 588".
        msgs = dm_brain.turn_messages([{"role": "user", "content": "546 starting checklist"}],
                                      "How many arkon guys on 588")
        self.assertEqual(len(msgs), 1)
        last = msgs[-1]["content"]
        self.assertLess(last.index("546 starting checklist"), last.index(dm_brain.LATEST_MARK))
        self.assertTrue(last.endswith(dm_brain.LATEST_MARK + "\nHow many arkon guys on 588"))
        self.assertIn("LATEST message only", dm_brain.SYSTEM_PROMPT)

    def test_cut_claims_you(self):
        self.assertTrue(dm_brain.truncated("*Ark"))
        self.assertTrue(dm_brain.truncated("All good", "length"))
        self.assertTrue(dm_brain.truncated("Ok", after_tools=True))
        self.assertFalse(dm_brain.truncated("* Arkon\n* J&G\n*2* on site"))
        self.assertFalse(dm_brain.truncated("*Arkon Builders* — 12 on site."))
        self.assertEqual(dm_brain.action_claims("Sent you the sheet."), ["sent"])
        self.assertEqual(dm_brain.action_claims("I've saved it. All done."), ["saved", "done"])
        self.assertEqual(dm_brain.action_claims("Want me to send it? Reply yes to save."), [])
        self.assertEqual(dm_brain.action_claims("3 items done P-588-1 open"), [])
        self.assertTrue(dm_brain.says_from_you("Voice note from you at 9:14"))
        self.assertFalse(dm_brain.says_from_you("Meilich said core drill on 3"))

    def test_final_text_and_json(self):
        self.assertEqual(dm_brain.final_text("<think>x</think>\nok"), "ok")
        self.assertEqual(dm_brain.json_object('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(dm_brain.json_object('<think>hm</think> Sure: {"a": 2} done'), {"a": 2})
        self.assertIsNone(dm_brain.json_object("no json"))

    def test_language(self):
        self.assertEqual(dm_brain.language("וויפל ארבעטער זענען היינט אויף 588?"), "yi")
        self.assertEqual(dm_brain.language("¿Cuántos trabajadores hay hoy?"), "es")
        self.assertEqual(dm_brain.language("How many on site at 588?"), "en")

    def test_deepinfra_defaults(self):
        self.assertEqual(dm_brain.API_BASE, "https://api.deepinfra.com/v1/openai")
        self.assertEqual(dm_brain.MAX_TOOL_CALLS, 6)
        self.assertEqual(server.DM_BRAIN_API_KEY, server.QWEN_API_KEY)     # no new key

    def test_exact_yes_no_only(self):
        for t in ("yes", "Yes!", "ok", "sí", "👍"):
            self.assertTrue(dm_brain.is_yes(t), t)
        for t in ("yes but change the trade", "go for it i guess", "no idea"):
            self.assertFalse(dm_brain.is_yes(t), t)
        self.assertTrue(dm_brain.is_no("cancel"))
        self.assertFalse(dm_brain.is_no("no idea"))


if __name__ == "__main__":
    unittest.main()
