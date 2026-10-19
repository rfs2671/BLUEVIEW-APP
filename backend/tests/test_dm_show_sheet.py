"""Mon 10:21 AM, 588 (DM): "Show me" sends the sheet.

  "Any info about window protection at ssp for 588?"
      -> "Window protection details are on SSP-011.00. It specifies ..."
  "Show me"          -> the same words again (it took "Want the names?")
  "Show me details"  -> the same words again (the agent has no sheet tool
                        in a DM: query_plan sends outside the DM gate)

A show request in a DM now sends the sheet image -- the one it names, else
the one Levelog's last message cites -- through the DM gate (opt-in or the
reply window, paced, in the ledger).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import server  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx, _run  # noqa: E402

WINDOW = ("Window protection details are on SSP-011.00. It specifies using MAGZO Adjustable "
          "Window Screen, 48x99 Inch Durable Fiberglass Screen Mesh or an accepted equal.")
SHEETS = {
    "SSP-011.00": {"_id": "pg11", "project_id": THOMAS, "sheet_number": "SSP-011.00",
                   "sheet_title": "Window Protection Details", "page_jpeg_r2_key": "k/11.jpg"},
    "SSP-013": {"_id": "pg13", "project_id": THOMAS, "sheet_number": "SSP-013.00",
                "sheet_title": "Fence Details", "page_jpeg_r2_key": "k/13.jpg"},
    "SSP-001": {"_id": "pg1", "project_id": THOMAS, "sheet_number": "SSP-001.00",
                "sheet_title": "General Notes", "is_spec_page": True},
}
MEDIA_URL = "https://api.levelog.test/api/temp-media/tok.jpg"


class _Sheets(_Site):
    def setUp(self):
        super().setUp()
        self.looked_up = []

    def say(self, c, body, quoted=None, from_bot=False, llm=None, key=None):
        async def agent(**kw):
            self.agent_calls.append(kw)
            kw["tool_trace"].append({"tool": "search_plans", "result": WINDOW})   # its records
            return WINDOW

        async def find(project_id, sheet_q):
            self.looked_up.append((project_id, sheet_q))
            row = SHEETS.get(sheet_q.upper())
            return [row] if row else []

        async def media(chat, page):
            return MEDIA_URL
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_find_named_sheet", find), \
                patch.object(server, "_plan_media_url", media):
            return self._say(c, body, quoted, from_bot, llm, key)

    @staticmethod
    def media_sent(c):
        return [p for p in c.wire.calls if "mediaUrl" in p]


class MondayAt588(_Sheets, unittest.TestCase):

    def test_the_conversation(self):
        with _Ctx(db=self.db) as c:
            first = self.say(c, "Any info about window protection at ssp for 588?")
            self.say(c, "Show me")
            after_show = len(self.media_sent(c))
            self.say(c, "Show me details")
            sent = self.media_sent(c)
        self.assertTrue(first.startswith("Window protection details are on SSP-011.00."), first)
        self.assertEqual(after_show, 1)
        self.assertEqual(len(sent), 2)
        for p in sent:
            self.assertEqual(p, {"chatId": f"{ADMIN_PHONE}@c.us", "mediaUrl": MEDIA_URL,
                                 "caption": "SSP-011.00 — Window Protection Details"})
        self.assertEqual(len(self.agent_calls), 1)            # the words, once
        self.assertEqual({p for p, _ in self.looked_up}, {THOMAS})
        logs = [r for r in self.db[server.DM_ANSWERS].rows if r.get("path") == "sheet"]
        self.assertEqual([r["tool_data"] for r in logs],
                         [{"sheet": "SSP-011.00", "sent": True}] * 2)
        # Kept in the chat, so the next "show me" has it.
        self.assertTrue(any(r.get("body") == "[Sheet] SSP-011.00 — Window Protection Details"
                            for r in self.db.whatsapp_messages.rows))

    def test_a_sheet_named(self):
        with _Ctx(db=self.db) as c:
            self.say(c, "show me SSP-013 for 588")
            sent = self.media_sent(c)
        self.assertEqual([p["caption"] for p in sent], ["SSP-013.00 — Fence Details"])
        self.assertEqual(self.agent_calls, [])

    def test_an_open_menu_is_dropped(self):
        """Codex on #808: a sheet request of its own drops an open "Which
        job?" menu, so a later "1" or "yes" doesn't answer the old question."""
        chat = f"{ADMIN_PHONE}@c.us"
        with _Ctx(db=self.db) as c:
            _run(server._dm_state_set("dm_menu", chat, 600, options=[THOMAS], question="what's open"))
            _run(server._dm_state_set("dm_clarify", chat, 600, project_id=THOMAS, options=[]))
            self.say(c, "show me SSP-013 for 588")
            menu = _run(server._dm_state_get("dm_menu", chat))
            clarify = _run(server._dm_state_get("dm_clarify", chat))
            sent = self.media_sent(c)
        self.assertEqual([p["caption"] for p in sent], ["SSP-013.00 — Fence Details"])
        self.assertIsNone(menu)
        self.assertIsNone(clarify)

    def test_not_in_the_drawings(self):
        self.assertEqual(self.ask("show me SSP-099 for 588"),
                         "SSP-099 isn't in the indexed drawings for 588.")

    def test_a_notes_sheet(self):
        self.assertEqual(self.ask("pull up SSP-001 at 588"),
                         "SSP-001.00 is a notes sheet — indexed, can't render yet.")

    def test_the_image_could_not_be_made(self):
        async def none(chat, page):
            return None
        with _Ctx(db=self.db) as c, patch.object(server, "_plan_media_url", none):
            async def find(project_id, sheet_q):
                return [SHEETS["SSP-013"]]
            with patch.object(server, "_find_named_sheet", find):
                reply = self._say(c, "show me SSP-013 for 588", None, False, None, None)
        self.assertEqual(reply, "Found SSP-013.00 but couldn't send the image. "
                                "It may still be rendering.")

    def test_show_me_with_no_sheet_cited_still_takes_the_offer(self):
        reply = self.ask("How many arkon workers in 588 · show me")
        self.assertTrue(reply.startswith("Arkon: 15 on site at 588 — Arkon Worker"), reply)


class TheGate(unittest.TestCase):

    def test_no_optin_and_no_window_sends_nothing(self):
        async def media(chat, page):
            raise AssertionError("no image is made for a refused send")
        with _Ctx(db=_db()) as c, patch.object(server, "_plan_media_url", media):
            ok = _run(server._dm_send_sheet(f"{ADMIN_PHONE}@c.us", SHEETS["SSP-013"]))
        self.assertFalse(ok)
        self.assertEqual(c.wire.calls, [])

    def test_a_waapi_error_is_not_a_send(self):
        from tests.test_whatsapp_dm_assistant import _optin
        from tests.test_whatsapp_phase1_foundations import _Wire
        db = _db()
        _optin(db, "u_admin", ADMIN_PHONE)

        async def media(chat, page):
            return MEDIA_URL
        wire = _Wire([(200, {"data": {"status": "error"}}, None)])
        with _Ctx(db=db, wire=wire), patch.object(server, "_plan_media_url", media):
            ok = _run(server._dm_send_sheet(f"{ADMIN_PHONE}@c.us", SHEETS["SSP-013"]))
        self.assertFalse(ok)
        self.assertFalse(any(str(r.get("body", "")).startswith("[Sheet]")
                             for r in db.whatsapp_messages.rows))


class TheWords(unittest.TestCase):

    def test_show_requests(self):
        for t in ["Show me", "show me details", "Show me the drawing", "send it", "let me see",
                  "pull it up", "can I see it", "show me the sheet please", "@levelog show me"]:
            self.assertTrue(server._dm_show_request(t), t)

    def test_not_show_requests(self):
        for t in ["show me the open items", "see you tomorrow", "send me a report for 588",
                  "show me who's on site", "what's open at 588", "details"]:
            self.assertFalse(server._dm_show_request(t), t)

    def test_the_sheet_cited(self):
        history = [{"sender": "bot", "body": "Fence is on SSP-013.00."},
                   {"sender": "them", "body": "ok"},
                   {"sender": "bot", "body": WINDOW}]
        self.assertEqual(server._dm_cited_sheet(history), "SSP-011.00")
        # Only Levelog's last message: an older answer is not "it".
        self.assertIsNone(server._dm_cited_sheet(history + [{"sender": "bot", "body": "Ok."}]))
        # A reply-to names the message.
        self.assertEqual(server._dm_cited_sheet(history, "Fence is on SSP-013.00.", True),
                         "SSP-013.00")


if __name__ == "__main__":
    unittest.main()
