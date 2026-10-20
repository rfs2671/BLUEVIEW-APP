"""The DM brain (lib/dm_brain.py, flag dm_brain_v2): one model with tools
answers every free-text DM; code keeps only the guardrails.

The model here is scripted (FakeClaude): each test says which tools it
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
    stop = stop or ("tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn")
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class FakeClaude:
    """client.beta.messages.create, scripted. Each step is a response or a
    function of the request (to look at the tool results)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.beta = self
        self.messages = self

    async def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda o: getattr(o, "__dict__", str(o)))))
        step = self.script.pop(0)
        return step(kw) if callable(step) else step


def last_tool_results(call):
    m = call["messages"][-1]
    return [c["content"] for c in m["content"]] if isinstance(m["content"], list) else []


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

    def say(self, c, body, claude, quoted=None):
        self.n += 1
        before = len([p for p in c.wire.calls if "message" in p])

        async def on(ident):
            return True

        async def react(chat, mid, emoji):
            self.reactions.append(emoji)
            return True
        with patch.object(server, "_dm_brain_on", on), \
                patch.object(server, "_dm_brain_client", lambda: claude), \
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
        claude = FakeClaude(resp(use("headcount", {"job": "588"})), answer_from)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Update on 588", claude)
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
        claude = FakeClaude(resp(use("list_subs", {}, "a"), use("dot_status", {"job": "588"}, "b")),
                            answer)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Dot and Akron", claude)
        self.assertEqual(out, ["DOT: permit M01-2026123, issued. Arkon Builders is on 588."])

    def test_arkon_is_framer_saved_only_on_yes(self):
        def proposed(kw):
            res = json.loads(last_tool_results(kw)[0])
            self.assertEqual(res["status"], "waiting_for_their_yes")
            self.assertIn("Arkon Builders", res["would_change"])
            return resp(text("Got it — save Arkon Builders as Framing on 588? Reply yes."))
        claude = FakeClaude(resp(use("set_sub_trade", {"company": "Akron", "trade": "framer"})), proposed)
        with _Ctx(db=self.db) as c:
            out = self.say(c, "Arkon is framer", claude)
            self.assertEqual(self.trade("Arkon Builders"), "General Construction")   # nothing saved yet
            self.assertEqual(out, ["Got it — save Arkon Builders as Framing on 588? Reply yes."])
            done = self.say(c, "yes", FakeClaude())                  # the model is not asked
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
        claude = FakeClaude(resp(text("ok")))
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open", claude)
        call = claude.calls[0]
        context = call["system"][1]["text"]
        self.assertIn("Their jobs", context)
        self.assertIn("588 Thomas", context)
        self.assertIn("Open flows: none.", context)
        self.assertEqual(call["system"][0]["cache_control"], {"type": "ephemeral"})
        bodies = "\n".join(m["content"] for m in call["messages"] if isinstance(m["content"], str))
        self.assertIn("old 24", bodies)
        self.assertNotIn("old 4\n", bodies + "\n")                  # only the last 20
        self.assertEqual(call["messages"][-1]["role"], "user")
        self.assertTrue(call["messages"][-1]["content"].endswith("what's open"))
        self.assertEqual(call["model"], dm_brain.MODEL)

    def test_an_open_change_is_in_the_context(self):
        _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                  step="ask:trade", options=[], asked="What trade is J&G?", misses=0))
        claude = FakeClaude(resp(text("Which trade?")))
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                      step="ask:trade", options=[], asked="What trade is J&G?", misses=0))
            self.say(c, "hmm", claude)
        self.assertIn("What trade is J&G?", claude.calls[0]["system"][1]["text"])


class TheGuardrails(_Brain):
    def test_a_number_no_tool_gave_is_asked_again_not_cut(self):
        claude = FakeClaude(
            resp(use("headcount", {"job": "588"})),
            resp(text("588: 45 on site.")),                       # 45 is nowhere
            lambda kw: (self.assertIn("45", kw["messages"][-1]["content"]),
                        resp(text("588: 31 on site.")))[1])
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many at 588", claude)
        self.assertEqual(out, ["588: 31 on site."])
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["verify_retries"], 1)

    def test_still_unverified_after_retries_is_said_plainly(self):
        claude = FakeClaude(resp(text("45 on site.")), resp(text("46 on site.")), resp(text("47 on site.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, "how many at 588", claude)
        self.assertEqual(out, [dm_brain.UNVERIFIED_TEXT])
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["draft"], "47 on site.")

    def test_no_phone_numbers(self):
        claude = FakeClaude(resp(text("Call him at 718-555-0123.")))
        with patch.object(dm_brain, "unverified", lambda r, s: []):
            with _Ctx(db=self.db) as c:
                out = self.say(c, "who's the super's number", claude)
        self.assertEqual(out, ["Call him at [number]."])

    def test_another_companys_job_is_not_theirs(self):
        def answer(kw):
            self.assertIn("None of their jobs matches", last_tool_results(kw)[0])
            return resp(text("That job isn't one of yours."))
        claude = FakeClaude(resp(use("open_items", {"job": "99 Bedford"})), answer)
        with _Ctx(db=self.db) as c:
            self.say(c, "what's open at 99 bedford", claude)

    def test_a_proposed_change_changes_nothing(self):
        def proposed(kw):
            res = json.loads(last_tool_results(kw)[0])
            self.assertIn(res["status"], ("waiting_for_their_yes", "needs_an_answer"))
            return resp(text("Add Power Direct to 588 as Electrical? Reply yes."))
        claude = FakeClaude(resp(use("propose_change", {"action": "add_sub", "company": "Power Direct",
                                                        "trade": "Electrical", "job": "588"})), proposed)
        before = [dict(r) for r in self.db.projects.rows[0]["trade_assignments"]]
        with _Ctx(db=self.db) as c:
            out = self.say(c, "put power direct on 588 as electrician", claude)
        self.assertEqual(self.db.projects.rows[0]["trade_assignments"], before)
        self.assertEqual(out, ["Add Power Direct to 588 as Electrical? Reply yes."])

    def test_the_model_cannot_answer_its_own_confirm(self):
        _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                  step="confirm", options=[], asked="Add it?", misses=0))

        def refused(kw):
            self.assertIn("theirs", last_tool_results(kw)[0])
            return resp(text("Reply yes to add it."))
        claude = FakeClaude(resp(use("answer_pending_change", {"answer": "yes"})), refused)
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set(server.DM_ACTION_STATE, CHAT, 600, p={"action": "add_sub"},
                                      step="confirm", options=[], asked="Add it?", misses=0))
            self.say(c, "go for it i guess", claude)

    def test_undo_needs_a_yes_too(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Arkon is framer", FakeClaude(
                resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                resp(text("Save it? Reply yes."))))
            self.say(c, "yes", FakeClaude())
            self.assertEqual(self.trade("Arkon Builders"), "Framing")
            self.say(c, "undo that", FakeClaude(resp(use("undo_last_change", {})),
                                                resp(text("Undo it? Reply yes."))))
            self.assertEqual(self.trade("Arkon Builders"), "Framing")
            self.say(c, "yes", FakeClaude())
        self.assertEqual(self.trade("Arkon Builders"), "General Construction")

    def test_no_after_a_proposal_cancels(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "Arkon is framer", FakeClaude(
                resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                resp(text("Save it? Reply yes."))))
            out = self.say(c, "no", FakeClaude())
        self.assertEqual(self.trade("Arkon Builders"), "General Construction")
        self.assertEqual(len(out), 1, out)                          # one plain "won't do it"


class TheWalkthrough(_Brain):
    def test_photo_talk_goes_to_the_brain_not_a_regex(self):
        q = ("I'm going to show you some pictures, I need to do a checklist, it's not going to be "
             "sent to anyone, just for me.")
        claude = FakeClaude(resp(text("Send them here with a caption each; nothing goes out until you say send.")))
        with _Ctx(db=self.db) as c:
            out = self.say(c, q, claude)
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(out, ["Send them here with a caption each; nothing goes out until you say send."])

    def test_exact_walk_commands_stay_in_code(self):
        claude = FakeClaude()
        with _Ctx(db=self.db) as c:
            out = self.say(c, "start walkthrough at 588", claude)
        self.assertEqual(claude.calls, [])
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
        claude = FakeClaude(resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                            resp(text("Save it?")))
        with _Ctx(db=db), patch.object(server, "_dm_brain_client", lambda: claude):
            out = _run(server._dm_brain_answer(ident, CHAT, "Arkon is framer", history=[],
                                               now=datetime.now(timezone.utc), dry_run=True,
                                               flows=[], active=None))
        self.assertEqual(out["reply"], "Save it?")
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
            with patch.object(server, "ANTHROPIC_API_KEY", "k"):
                self.assertTrue(_run(server._dm_brain_on(mine)))
                self.assertFalse(_run(server._dm_brain_on(other)))
            with patch.object(server, "ANTHROPIC_API_KEY", ""):
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

    def test_exact_yes_no_only(self):
        for t in ("yes", "Yes!", "ok", "sí", "👍"):
            self.assertTrue(dm_brain.is_yes(t), t)
        for t in ("yes but change the trade", "go for it i guess", "no idea"):
            self.assertFalse(dm_brain.is_yes(t), t)
        self.assertTrue(dm_brain.is_no("cancel"))
        self.assertFalse(dm_brain.is_no("no idea"))


if __name__ == "__main__":
    unittest.main()
