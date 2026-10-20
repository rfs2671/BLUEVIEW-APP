"""scripts/dm_brain_eval.py: every logged DM replayed through the brain --
read-only (writes dropped and counted), dry-run, nothing sent."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server  # noqa: E402
from scripts import dm_brain_eval as ev  # noqa: E402
from tests.test_dm_brain import FakeClaude, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx  # noqa: E402


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
        claude = FakeClaude(resp(use("set_sub_trade", {"company": "Arkon", "trade": "Framing"})),
                            resp(text("Save Arkon Builders as Framing on 588? Reply yes.")))
        with _Ctx(db=db):
            ro = ev.ReadOnlyDb(server.db)
            with patch.object(server, "db", ro), patch.object(server, "_dm_brain_client", lambda: claude):
                rows = _run(ev._rows(server, 30, 100))
                out = _run(ev._replay_one(server, rows[0], {}))
        self.assertEqual(out["old_answer"], "I don't have that in the records.")
        self.assertEqual(out["new_answer"], "Save Arkon Builders as Framing on 588? Reply yes.")
        self.assertEqual(out["history_turns"], 1)                      # "hi", not the question
        self.assertTrue(out["tools"][0].startswith("set_sub_trade("))
        self.assertEqual(db[server._DM_STATE].rows, [])                # nothing pending stored
        self.assertEqual(db.projects.rows[0]["trade_assignments"][0]["trade"], "General Construction")
        md = ev._md([out], "claude-sonnet-5-5", ro.dropped,
                    {"input": 1, "output": 2, "cache_read": 0, "cache_write": 0})
        self.assertIn("**Old** (job_agent)", md)
        self.assertIn("Save Arkon Builders as Framing", md)


    def test_fixed_cases_with_checks(self):
        from tests.test_dm_brain_tue1228 import SAID, _days, answer
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE, chat=CHAT)
        for p in db.projects.rows:
            if p["_id"] == THOMAS:
                p["trade_assignments"] = [{"id": "r9", "company": "Cool Air Corp", "trade": "HVAC"}]
        _days(db, "Cool Air Corp", (3, 4, 6))
        db.whatsapp_dm_answers.rows.append({
            "_id": "a1", "user_id": "u_admin", "path": "job_agent",
            "question": "How many days hvac worked in 588",
            "answer": "I don't have that. Check with the site manager.",
            "created_at": datetime.now(timezone.utc) - timedelta(hours=1)})

        def walk(kw):
            self.assertIn(SAID, kw["messages"][-1]["content"])
            return answer({"actions": [{"do": "location", "items": "since_last", "place": "3rd floor"},
                                       {"do": "default_location", "place": "4th floor"}], "reply": ""})

        def hvac(kw):
            res = kw["messages"][-1]["content"][0]["content"]
            line = next(ln for ln in res.splitlines() if ln.startswith("Cool Air Corp:"))
            return resp(text(line))
        claude = FakeClaude(walk, resp(use("sub_attendance", {"job": "588", "trade": "hvac"})), hvac,
                            resp(use("sub_attendance", {"job": "588", "trade": "elevator"})),
                            resp(text("No elevator sub on 588's list, and none checked in by name.")))
        with _Ctx(db=db):
            ro = ev.ReadOnlyDb(server.db)
            with patch.object(server, "db", ro), patch.object(server, "_dm_brain_client", lambda: claude), \
                    patch.object(server, "ANTHROPIC_API_KEY", "k"):
                fixed = _run(ev._fixed(server, [], {}, ""))
        by = {r["id"]: r for r in fixed}
        self.assertEqual({k: r.get("pass") for k, r in by.items()},
                         {"walk_location": True, "hvac_days": True, "no_deflect": True}, fixed)
        self.assertIn("#1 Floor 3", by["walk_location"]["detail"])
        self.assertIn("next photo #5: Floor 4", by["walk_location"]["detail"])
        self.assertEqual(by["hvac_days"]["old_answer"], "I don't have that. Check with the site manager.")
        self.assertEqual(db.projects.rows[0]["trade_assignments"][0]["company"], "Cool Air Corp")
        md = ev._md([], "claude-sonnet-5-5", ro.dropped,
                    {"input": 1, "output": 2, "cache_read": 0, "cache_write": 0}, fixed)
        self.assertIn("## Fixed cases", md)
        self.assertIn("### walk_location: PASS", md)
        self.assertIn("**Expected:**", md)
        self.assertIn("## Can't answer (new)", md)


if __name__ == "__main__":
    unittest.main()
