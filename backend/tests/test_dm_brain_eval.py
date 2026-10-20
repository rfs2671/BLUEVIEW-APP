"""scripts/dm_brain_eval.py: every logged DM replayed through the brain on
both DeepInfra models -- read-only (writes dropped and counted), dry-run,
nothing sent; the fixed cases with their checks; the preflight."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import server  # noqa: E402
from scripts import dm_brain_eval as ev  # noqa: E402
from tests.test_dm_brain import FakeLLM, last_tool_results, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests.test_dm_subs_on_site import _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx  # noqa: E402

M = "Qwen/Qwen3.8-Flash"


class Replay(unittest.TestCase):
    def test_old_vs_new_and_nothing_written(self):
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE, chat=CHAT)
        for p in db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"] = [{"id": "r1", "company": "Arkon Builders",
                                           "trade": "General Construction"}]
        at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.whatsapp_messages.rows += [
            {"_id": "m1", "group_id": CHAT, "is_dm": True, "sender": "1", "body": "hi",
             "created_at": at - timedelta(minutes=5)},
            {"_id": "m2", "group_id": CHAT, "is_dm": True, "sender": "1", "body": "Arkon is framer",
             "created_at": at - timedelta(seconds=3)}]
        db.whatsapp_dm_answers.rows.append({
            "_id": "a1", "user_id": "u_admin", "path": "job_agent", "question": "Arkon is framer",
            "answer": "I don't have that in the records.", "created_at": at})
        llm = FakeLLM(resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                      resp(text("Save Arkon Builders as Framing on 588? Reply yes.")),
                      resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                      resp(text("Arkon Builders as Framing on 588 — reply yes to save it.")))
        with _Ctx(db=db):
            ro = ev.ReadOnlyDb(server.db)
            with patch.object(server, "db", ro), patch.object(server, "_dm_brain_client", lambda: llm):
                rows = _run(ev._rows(server, 30, 100))
                out = _run(ev._replay_one(server, rows[0], {}, [M, "Qwen/Qwen3.8-Max"]))
        self.assertEqual([c["model"] for c in llm.calls], [M, M, "Qwen/Qwen3.8-Max", "Qwen/Qwen3.8-Max"])
        self.assertEqual(out["old_answer"], "I don't have that in the records.")
        run = out["runs"][M]
        self.assertEqual(run["answer"], "Save Arkon Builders as Framing on 588? Reply yes.")
        self.assertEqual(run["quality"], {"answered": True, "evidence": True, "language": True})
        self.assertEqual((run["input_tokens"], run["cost_usd"]), (200, 0.0002))
        self.assertEqual(out["history_turns"], 1)                      # "hi", not the question
        self.assertTrue(run["tools"][0].startswith("set_sub_trade("))
        self.assertEqual(db[server._DM_STATE].rows, [])                # nothing pending stored
        self.assertEqual(db.projects.rows[0]["trade_assignments"][0]["trade"], "General Construction")
        md = ev._md([out], [M, "Qwen/Qwen3.8-Max"], ro.dropped)
        self.assertIn("**Old** (job_agent)", md)
        self.assertIn(f"**{M}** — quality 3/3", md)
        self.assertIn("$0.0002", md)
        self.assertIn("| Model | Required fixed cases", md)


def _script():
    """A scripted model for the 8 fixed cases, in order (one model)."""
    from tests.test_dm_brain_tue1228 import answer

    def after(fn):
        return lambda kw: fn(last_tool_results(kw))

    return [
        # update_588
        resp(use("headcount", {"job": "588"}, "a"), use("dob_status", {"job": "588"}, "b")),
        after(lambda res: resp(text("588: crew on site now, Arkon Builders the biggest.\n"
                                    "DOB: nothing new.\nWant the names?"))),
        # dot_and_akron
        resp(use("list_subs", {}, "a"), use("dot_status", {"job": "588"}, "b")),
        resp(text("DOT: nothing open at 588. Arkon Builders is on 588.")),
        # arkon_framer
        resp(use("set_sub_trade", {"company": "Akron", "trade": "framer"})),
        resp(text("Save Arkon Builders as Framing on 588? Reply yes.")),
        # walk
        answer({"actions": [{"do": "location", "items": "since_last", "place": "3rd floor"},
                            {"do": "default_location", "place": "4th floor"}], "reply": ""}),
        # hvac_days
        resp(use("sub_attendance", {"job": "588", "trade": "hvac"})),
        after(lambda res: resp(text(next(ln for ln in res[0].splitlines() if ln.startswith("Cool Air Corp:"))))),
        # no_deflect
        resp(use("sub_attendance", {"job": "588", "trade": "elevator"})),
        resp(text("No elevator sub on 588's list, and none checked in by name.")),
        # spanish
        resp(use("headcount", {"job": "588"})),
        resp(text("Hoy en 588 hay trabajadores de Arkon Builders en la obra.")),
        # yiddish
        resp(use("headcount", {"job": "588"})),
        resp(text("היינט אויף 588 זענען דא ארבעטער פון Arkon Builders.")),
    ]


class Fixed(unittest.TestCase):
    def test_all_eight_pass_with_checks(self):
        from tests.test_dm_brain_tue1228 import _days
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE, chat=CHAT)
        _crew(db)
        for p in db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"] = [{"id": "r1", "company": "Arkon Builders",
                                           "trade": "General Construction"},
                                          {"id": "r9", "company": "Cool Air Corp", "trade": "HVAC"}]
        _days(db, "Cool Air Corp", (3, 4, 6))
        db.whatsapp_dm_answers.rows.append({
            "_id": "a1", "user_id": "u_admin", "path": "job_agent",
            "question": "How many days hvac worked in 588",
            "answer": "I don't have that. Check with the site manager.",
            "created_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        llm = FakeLLM(*_script())
        with _Ctx(db=db):
            ro = ev.ReadOnlyDb(server.db)
            with patch.object(server, "db", ro), patch.object(server, "_dm_brain_client", lambda: llm), \
                    patch.object(server, "DM_BRAIN_API_KEY", "k"):
                fixed = _run(ev._fixed(server, [], {}, "", [M]))
        by = {r["id"]: r["runs"][M] for r in fixed}
        self.assertEqual({k: r.get("pass") for k, r in by.items()}, {k: True for k in by},
                         json.dumps({k: r.get("checks") for k, r in by.items()}, indent=1))
        self.assertEqual(len(fixed), 8)
        self.assertEqual(sum(r["required"] for r in fixed), 6)
        self.assertIn("#1 Floor 3", by["walk_location"]["detail"])
        self.assertIn("next photo #5: Floor 4", by["walk_location"]["detail"])
        self.assertEqual(fixed[4]["old_answer"], "I don't have that. Check with the site manager.")
        self.assertEqual(db.projects.rows[0]["trade_assignments"][0]["trade"], "General Construction")
        md = ev._md([], [M], ro.dropped, fixed)
        self.assertIn("## Fixed cases", md)
        self.assertIn(f"### walk_location (required) — {M}: PASS", md)
        self.assertIn("### yiddish — ", md)
        self.assertIn("| 6/6 | 8/8 |", md)

    def test_a_case_fails_when_it_should(self):
        self.assertFalse(all(ev._case_checks("dot_and_akron", "No Dot or Akron sub", []).values()))
        self.assertFalse(all(ev._case_checks("update_588", "588 Update\nDOB Status:\nWant the full list?",
                                             [{"tool": "headcount"}]).values()))
        self.assertFalse(all(ev._case_checks("spanish", "There are 31 on site.",
                                             [{"tool": "headcount"}]).values()))
        self.assertFalse(all(ev._case_checks("hvac_days", "Check with the site manager.",
                                             [{"tool": "sub_attendance"}]).values()))


class Preflight(unittest.TestCase):
    def client(self, ids, calls_tool=True):
        async def models_list():
            return SimpleNamespace(data=[SimpleNamespace(id=i) for i in ids])

        async def create(**kw):
            tc = [SimpleNamespace(id="p", function=SimpleNamespace(name="ping", arguments='{"ok": true}'))]
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=None if calls_tool else "ok", tool_calls=tc if calls_tool else None),
                finish_reason="tool_calls")])
        return SimpleNamespace(models=SimpleNamespace(list=models_list),
                               chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def test_listed_and_calls_tools(self):
        got = _run(ev.preflight(self.client([M, "Qwen/Qwen3.8-Max", "x/y"]), [M, "Qwen/Qwen3.8-Max"], "b"))
        self.assertTrue(got["ok"])
        self.assertEqual(got["qwen38"], ["Qwen/Qwen3.8-Flash", "Qwen/Qwen3.8-Max"])

    def test_a_missing_id_or_no_tools_fails(self):
        got = _run(ev.preflight(self.client(["Qwen/Qwen3.8-Flash-Next"]), [M], "b"))
        self.assertFalse(got["ok"])
        self.assertEqual(got["qwen38"], ["Qwen/Qwen3.8-Flash-Next"])           # what to set instead
        got = _run(ev.preflight(self.client([M], calls_tool=False), [M], "b"))
        self.assertFalse(got["ok"])
        self.assertFalse(got["tools"][M])


if __name__ == "__main__":
    unittest.main()
