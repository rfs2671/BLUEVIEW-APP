"""dm_eval, Oct 20: "Cancel checklist" and "Done" both got "Checklist
creation or cancellation is done in the app." from the job agent -- the
same claim about a feature, to two different messages, with nothing open.

A bare "Done" / "Cancel <thing>" that no flow took is answered in fixed
words about what is open, never by the agent:
  "Cancel checklist" -> "There's no checklist open here to cancel."
  "Done"             -> "Done with what?" (the open walk named, else
                        Levelog's last message quoted)
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import server  # noqa: E402
from lib import punch, wa_assistant  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402


class TheOct20Messages(_Site, unittest.TestCase):

    def test_cancel_checklist_then_done(self):
        with _Ctx(db=self.db) as c:
            cancel = self.say(c, "Cancel checklist")
            done = self.say(c, "Done")
        self.assertEqual(cancel, "There's no checklist open here to cancel.")
        self.assertEqual(done, "Done with what?")
        self.assertEqual(self.agent_calls, [])                 # never the agent
        self.assertNotIn("in the app", cancel + done)
        logs = [r for r in self.db[server.DM_ANSWERS].rows if r.get("path") == "closer"]
        self.assertEqual([r["answer"] for r in logs], [cancel, done])

    def test_done_after_an_answer_quotes_it(self):
        with _Ctx(db=self.db) as c:
            first = self.say(c, "How many workers on site at 588?")
            done = self.say(c, "Done")
        self.assertTrue(done.startswith(f"Done with what? My last message was: “{first[:20]}"), done)

    def test_done_with_a_walk_open_names_the_walk(self):
        """A walk the punch flow did not take "done" for (it is past capture)
        is the thing they most likely mean: named, never invented."""
        now = datetime.now(timezone.utc)
        self.db[punch.SESSIONS].rows.append({
            "_id": "w1", "user_id": "u_admin", "company_id": "co_a", "project_id": THOMAS,
            "job_name": "588 Thomas", "status": "recap", "items": [], "created_at": now,
            "updated_at": now})
        from tests.test_whatsapp_dm_assistant import _run
        from tests.test_dm_short_answers import CHAT as chat
        ident = {"user_id": "u_admin", "company_id": "co_a"}
        with _Ctx(db=self.db) as c:
            took = _run(server._dm_closer_turn(ident, chat, "Done", []))
            sends = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertTrue(took)
        self.assertEqual(sends, ["Done with what? Your walk at 588 Thomas is still open."])

    def test_cancel_it_is_still_the_drop(self):
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "cancel it")
        self.assertNotIn("open here to cancel", reply or "")


class TheWords(unittest.TestCase):
    def test_closers(self):
        for text, want in [("Done", ("done", "")), ("done.", ("done", "")), ("All done", ("done", "")),
                           ("finished", ("done", "")), ("Done ✅", ("done", "")), ("listo", ("done", "")),
                           ("Cancel checklist", ("cancel", "checklist")),
                           ("cancel the walk", ("cancel", "walk"))]:
            self.assertEqual(wa_assistant.closer(text), want, text)

    def test_not_closers(self):
        for text in ["cancel it", "cancel", "Cancel checklist?", "is it done?",
                     "done with the walk at 588", "stop the brief", "how many done today",
                     "what's done at 588"]:
            self.assertIsNone(wa_assistant.closer(text), text)

    def test_replies(self):
        self.assertEqual(wa_assistant.cancel_reply("checklist"), "There's no checklist open here to cancel.")
        self.assertEqual(wa_assistant.cancel_reply("walk", "588 Thomas"),
                         "Your walk at 588 Thomas is still open — nothing else to cancel.")
        long = "Window protection details are on SSP-011.00. It specifies using MAGZO Adjustable"
        self.assertEqual(wa_assistant.done_reply("", long),
                         "Done with what? My last message was: “Window protection details are on "
                         "SSP-011.00. It specifies…”")
        self.assertEqual(wa_assistant.done_reply("", "There's no checklist open here to cancel."),
                         "Done with what?")


if __name__ == "__main__":
    unittest.main()
