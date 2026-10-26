"""dm_eval, Oct 20, item 5: "I can't …" answers that were not true.

From the export (30 days, 32 answers), each question as it was asked and the
job agent's answer as it went out:

  "What was said on the last voicenote on 588 group"
      -> "I can't find that in the project history."
  "U can't find any voicenotes?"
      -> "I can't access voice notes directly. …"
  "2nd floor Apt 2D" (a reply to a photo)
      -> "I can't access or interpret the content of the message you replied to. …"
  "Is there low voltage company in subs list?"
      -> "I can't check the full list of subcontractors here. …"
  "I'm going to show you some pictures, I need to do a checklist, …"
      -> "I can't create a checklist from images here. Please use the app …"
  "How many days did arkon sub been on 588 Thomas boyland already"
      -> "… data doesn't specify how many days they've been on site."

Voice notes are transcribed and stored, a reply-to carries what it replied
to, the subs list and the days on site are in the records, and photos sent in
this chat are the punch list. Each is replayed here with the agent saying
exactly what it said live; none of those words may reach the user.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import server  # noqa: E402
from lib import project_memory, punch  # noqa: E402
from tests.test_dm_short_answers import CHAT, _Site  # noqa: E402
from tests.test_dm_subs_on_site import _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx  # noqa: E402

# A photo's body as WaAPI sends it in a reply: its base64 thumbnail.
THUMB = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEABsbGxscGx4hIR4qLSgtKj04MzM4PV1CR0JH" * 4
NOTES = "🎤 Sun Oct 11, 2:57 PM · Site super · 588 Site\nPeople speaking in their native language."

LIVE = {
    "what was said on the last voicenote on 588 group": project_memory.NO_SOURCE,
    "u can't find any voicenotes?": ("I can't access voice notes directly. You might want to "
                                     "check the group chat for any recent voice notes."),
    "2nd floor apt 2d": ("I can't access or interpret the content of the message you replied to. "
                         "If you need specific information about the 2nd floor, Apt 2D at 588, "
                         "please let me know what you're looking for."),
    "is there low voltage company in subs list?": ("I can't check the full list of subcontractors "
                                                   "here. Please use the app to view the complete "
                                                   "list of subs for the project."),
    "i'm going to show you some pictures, i need to do a checklist, it's not going to be sent "
    "to anyone, just for me.": ("I can't create a checklist from images here. Please use the app "
                                "to upload the photos and create your checklist."),
    "can you make a punch list from photos at 588?": ("I can't create a checklist from images "
                                                      "here. Please use the app to upload the "
                                                      "photos and create your checklist."),
    "how many days did arkon sub been on 588 thomas boyland already": (
        "Arkon, the framers, are on the job at 588. The data doesn't specify how many days "
        "they've been on site."),
}
FALSE = ("can't access", "can't check", "can't create", "can't find that",
         "doesn't specify", "use the app to")


def _payload(body, mid, quoted_photo=None):
    msg = {"id": {"id": mid, "fromMe": False, "_serialized": f"false_{CHAT}_{mid}"},
           "from": CHAT, "body": body, "type": "chat"}
    if quoted_photo is not None:
        msg["quotedMsg"] = {"body": quoted_photo, "type": "image",
                            "id": {"fromMe": False, "id": "Q" + mid}}
        msg["contextInfo"] = {"stanzaId": "Q" + mid}
    return {"event": "message", "data": {"message": msg}}


class TheExportQuestions(_Site, unittest.TestCase):
    """The 588 crew; the job agent answers as it did live."""

    def setUp(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0
        self.notes_read = []

    def ask(self, c, body, quoted_photo=None):
        async def agent(**kw):
            self.agent_calls.append(kw)
            key = " ".join(str(kw.get("body") or "").split("\n\n(This is a reply")[0].lower().split())
            said = LIVE[key]
            kw["tool_trace"].append({"tool": "replay", "result": said})
            return said

        async def llm(system, user_text):
            return "general"

        async def react(*a, **k):
            return True

        async def scope(body):
            return "project"

        async def action_model(text, jobs):
            return None                                 # no change asked: never the network

        async def notes(company_id, project_id, n=3, sender=""):
            self.notes_read.append(project_id)
            return NOTES
        self.n += 1
        before = len([p for p in c.wire.calls if "message" in p])
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_dm_llm", llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", scope), \
                patch.object(server, "_recent_voice_notes", notes), \
                patch.object(server, "_dm_action_model", action_model), \
                patch.object(server, "LLM_API_KEY", "k"):
            _run(server._process_whatsapp_message(_payload(body, f"m{self.n}", quoted_photo)))
        sends = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertGreater(len(sends), before, f"nothing sent for {body!r}")
        return sends[-1]

    def assertTrue_(self, reply):
        for words in FALSE:
            self.assertNotIn(words, reply.lower().replace("’", "'"), reply)

    def test_the_last_voice_note(self):
        """Live: "I can't find that in the project history." The notes go."""
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, "What was said on the last voicenote on 588 group")
        self.assertEqual(reply, NOTES)
        self.assertEqual(len(self.notes_read), 1)

    def test_cant_find_any_voicenotes(self):
        """Live: "I can't access voice notes directly." On its own (no job
        yet): "Which job?", then the notes."""
        with _Ctx(db=self.db) as c:
            menu = self.ask(c, "U can't find any voicenotes?")
            reply = self.ask(c, "588")
        self.assertTrue(menu.startswith("Which job?"), menu)
        self.assertEqual(reply, NOTES)

    def test_the_follow_up_after_the_notes(self):
        """In the live order the first question now gets the notes, so the
        follow-up would be the same notes again: never sent twice (#820),
        one short question instead -- and never a false claim."""
        with _Ctx(db=self.db) as c:
            first = self.ask(c, "What was said on the last voicenote on 588 group")
            then = self.ask(c, "U can't find any voicenotes?")
        self.assertEqual(first, NOTES)
        self.assertTrue(then.startswith("That's what I just sent."), then)
        self.assertTrue_(then)

    def test_a_reply_to_a_photo(self):
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, "2nd floor Apt 2D", quoted_photo=THUMB)
        self.assertTrue_(reply)
        for kw in self.agent_calls:                     # never the thumbnail as words
            self.assertNotIn(THUMB[:40], kw.get("body") or "")

    def test_the_subs_list(self):
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, "Is there low voltage company in subs list?")
        self.assertTrue_(reply)
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["path"], "subs")

    def test_pictures_for_a_checklist(self):
        """Live: "I can't create a checklist from images here. Please use the
        app …" Now: how, in fixed words; the agent is never asked and no walk
        is opened (the next message is not caught as a caption)."""
        q = ("I'm going to show you some pictures, I need to do a checklist, it's not going to "
             "be sent to anyone, just for me.")
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, q)
        self.assertEqual(reply, punch.WALK_HELP)
        self.assertTrue_(reply)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(self.db[punch.SESSIONS].rows, [])
        self.assertEqual(self.db[server.DM_ANSWERS].rows[-1]["path"], "walk_help")

    def test_the_agents_denial_is_never_sent(self):
        """Asked so it reaches the agent, its "I can't create a checklist
        from images" is replaced by how."""
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, "Can you make a punch list from photos at 588?")
        self.assertEqual(reply, punch.WALK_HELP)

    def test_days_on_site(self):
        with _Ctx(db=self.db) as c:
            reply = self.ask(c, "How many days did arkon sub been on 588 Thomas boyland already")
        self.assertTrue_(reply)
        self.assertIn("day", reply)


class TheWords(unittest.TestCase):
    def test_walk_intent(self):
        for t in ("I'm going to show you some pictures, I need to do a checklist, it's not "
                  "going to be sent to anyone, just for me.",
                  "gonna send pics for the punch list",
                  "Can I send you photos for a checklist?",
                  "voy a mandar fotos para la lista"):
            self.assertTrue(punch.walk_intent(t), t)
        for t in ("send me the punch list photos", "how many photos in the punch list?",
                  "Show me", "list the subs", "start walkthrough at 588",
                  "I need the drawing", "picture",
                  # Codex on #822: a question about photos, not sending them.
                  "Can I get a list of photos in yesterday's daily log?",
                  "I want to see the photos from the punch list"):
            self.assertFalse(punch.walk_intent(t), t)

    def test_denies_walk(self):
        self.assertTrue(punch.denies_walk("I can't create a checklist from images here."))
        self.assertTrue(punch.denies_walk("I can't create a checklist from images here. Please "
                                          "use the app to upload the photos and create your "
                                          "checklist."))
        # With no checklist / punch list beside it, "use the app" may be right.
        self.assertFalse(punch.denies_walk("Please use the app to upload the photos."))
        self.assertFalse(punch.denies_walk("Punch list P-588: 4 items, 2 open."))
        self.assertFalse(punch.denies_walk("I can't find that photo."))
        # Codex on #822: the app is the right answer for a daily log's photos.
        self.assertFalse(punch.denies_walk(
            "To add photos to the daily log, use the Levelog app to add photos under Daily Log."))
        self.assertTrue(punch.denies_walk(
            "Checklists are made in the app: use the app to upload the photos."))
        self.assertFalse(punch.denies_walk("I can't list the photos from that daily log."))


if __name__ == "__main__":
    unittest.main()
