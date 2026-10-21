"""The Levelog Assistant welcome: the first thing a person ever gets from it.

  * Their first START: "Hey <first name>", what they can ask (live features
    only), then the bot's contact card. Once per person, even with two STARTs
    racing; a later START gets the plain intro.
  * A card that fails still counts as welcomed; a welcome text that fails
    does not (their next START welcomes them).
  * A @lid chat gets both, in that chat.
  * Someone opted in before the welcome existed is welcomed on their first
    message, which is still answered.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_dm, wa_welcome  # noqa: E402
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    _Harness, _db as _assistant_db, _optin,
)
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, PM_PHONE, _Ctx, _Wire, _dm_payload, _run,
)
from tests.test_whatsapp_start_lid import LID, LID_CHAT, _mint, _process  # noqa: E402

BOT = "+15165494475"
OK = (200, {"status": "success"}, None)
CARD_OK = (200, {"status": "success", "data": {"status": "success"}}, None)
REFUSED = (200, {"status": "error", "message": "nope"}, None)
WITH_CARD = wa_welcome.welcome_text("Ada Admin", with_card=True)
NO_CARD = wa_welcome.welcome_text("Ada Admin", with_card=False)


def _start(c, phone=ADMIN_PHONE, mid="D1"):
    _run(server._process_whatsapp_message(_dm_payload(phone, "START", mid)))


def _texts(c):
    return [p["message"] for p in c.wire.calls if "message" in p]


def _bot_number():
    return patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT})


class TheText(unittest.TestCase):

    def test_it_opens_with_their_first_name(self):
        self.assertTrue(wa_welcome.welcome_text("Meilich Gross").startswith("Hey Meilich 👋\n"))
        self.assertTrue(wa_welcome.welcome_text("  ").startswith("Hey there 👋\n"))
        self.assertTrue(wa_welcome.welcome_text(None).startswith("Hey there 👋\n"))

    def test_it_names_live_features_and_how_to_stop(self):
        text = WITH_CARD
        for live in ("You're connected", "Levelog Assistant", "on site", "days a sub worked",
                     "daily log", "open items", "DOB / DOT violations", "permits", "hearings",
                     "show me", "report PDF", "photos", "punch list", "add a job",
                     "remind me", "reply yes", "GC WhatsApp group", "Spanish", "Yiddish",
                     "voice note", "Reply STOP"):
            self.assertIn(live, text)
        self.assertIn("Save my contact below", text)
        self.assertNotIn("Save my contact", NO_CARD)
        self.assertTrue(NO_CARD.endswith("Reply STOP anytime to turn me off."))

    def test_the_features_it_names_are_tools_the_dm_brain_has(self):
        extra = {t["name"] for t in server._DM_BRAIN_EXTRA_TOOLS}
        for tool in ("who_on_site", "sub_attendance", "daily_log", "open_items",
                     "dob_status", "active_permits", "search_plans"):
            self.assertIn(tool, server._DM_BRAIN_JOB_TOOLS)
        for tool in ("headcount", "dot_status", "send_sheet", "send_report",
                     "propose_change", "set_sub_trade", "remind_me"):
            self.assertIn(tool, extra)

    def test_it_promises_nothing_that_does_not_exist(self):
        low = WITH_CARD.lower()
        for not_live in ("summar", "blueview", "invoice", "payroll", "schedule",
                         "email", "inspection"):
            self.assertNotIn(not_live, low)

    def test_it_is_short_enough_to_read_on_a_phone(self):
        lines = [ln for ln in WITH_CARD.splitlines() if ln.strip()]
        self.assertLessEqual(len(lines), 15)
        self.assertLess(len(WITH_CARD), 900)


class TheFirstStart(unittest.TestCase):

    def test_the_welcome_then_the_card(self):
        wire = _Wire(responses=[OK, CARD_OK])
        with _Ctx(wire=wire) as c, _bot_number():
            _start(c)
        self.assertEqual(c.wire.calls[0]["message"], WITH_CARD)
        self.assertEqual(c.wire.calls[0]["chatId"], f"{ADMIN_PHONE}@c.us")
        self.assertIn("vCard", c.wire.calls[1])
        self.assertEqual(c.wire.calls[1]["chatId"], f"{ADMIN_PHONE}@c.us")
        self.assertEqual(len(c.wire.calls), 2)
        self.assertNotIn(wa_dm.INTRO_TEXT, _texts(c))
        row = c.db[server.WA_DM_WELCOMES].rows[0]
        self.assertEqual((row["_id"], row["card"]), ("u_admin", "vcard"))

    def test_a_pm_is_welcomed_by_name(self):
        with _Ctx() as c:
            _start(c, PM_PHONE)
        self.assertEqual(_texts(c), [wa_welcome.welcome_text("Pat PM", with_card=False)])
        self.assertTrue(_texts(c)[0].startswith("Hey Pat 👋"))

    def test_a_second_start_gets_the_intro_and_no_card(self):
        wire = _Wire(responses=[OK, CARD_OK])
        with _Ctx(wire=wire) as c, _bot_number():
            _start(c, mid="D1")
            c.wire.calls.clear()
            _start(c, mid="D2")
        self.assertEqual([p.get("message") for p in c.wire.calls], [wa_dm.INTRO_TEXT])

    def test_after_stop_and_start_again_it_is_not_repeated(self):
        with _Ctx() as c:
            _start(c, mid="D1")
            _run(server._process_whatsapp_message(_dm_payload(ADMIN_PHONE, "STOP", "D2")))
            c.wire.calls.clear()
            _start(c, mid="D3")
        self.assertEqual(_texts(c), [wa_dm.INTRO_TEXT])

    def test_two_starts_racing_welcome_once(self):
        with _Ctx() as c:
            async def both():
                await server._open_dm_reply_window(ADMIN_PHONE)
                await asyncio.gather(server._handle_dm_start(f"{ADMIN_PHONE}@c.us"),
                                     server._handle_dm_start(f"{ADMIN_PHONE}@c.us"))
            _run(both())
        self.assertEqual(sorted(_texts(c)), sorted([NO_CARD, wa_dm.INTRO_TEXT]))
        self.assertEqual(len(c.db[server.WA_DM_WELCOMES].rows), 1)

    def test_a_card_that_fails_still_counts(self):
        # send-vcard refused, the .vcf document refused too.
        wire = _Wire(responses=[OK, REFUSED, REFUSED])
        with _Ctx(wire=wire) as c, _bot_number():
            _start(c, mid="D1")
            self.assertEqual(_texts(c), [WITH_CARD])
            self.assertEqual(c.db[server.WA_DM_WELCOMES].rows[0]["card"], "not_sent")
            c.wire.calls.clear()
            _start(c, mid="D2")
        self.assertEqual(_texts(c), [wa_dm.INTRO_TEXT])

    def test_a_welcome_that_did_not_go_is_sent_next_time(self):
        real = server.send_whatsapp_message
        calls = []

        async def first_fails(chat, message, *a, **k):
            calls.append(message)
            if len(calls) == 1:
                return None
            return await real(chat, message, *a, **k)
        with _Ctx() as c, patch.object(server, "send_whatsapp_message", first_fails):
            _start(c, mid="D1")
            self.assertEqual(c.db[server.WA_DM_WELCOMES].rows, [])
            c.wire.calls.clear()
            _start(c, mid="D2")
        self.assertEqual(_texts(c), [NO_CARD])
        self.assertEqual(len(c.db[server.WA_DM_WELCOMES].rows), 1)

    def test_a_lid_chat_gets_the_welcome_and_the_card_there(self):
        # The first post is the WaAPI contact lookup for the @lid (no phone).
        wire = _Wire(responses=[OK, OK, CARD_OK])
        with _Ctx(wire=wire) as c, _bot_number():
            _process(c, LID_CHAT, f"START {_mint(c)}")
        sends = [p for p in c.wire.calls if "chatId" in p]
        self.assertEqual([(p["chatId"], "vCard" in p) for p in sends],
                         [(LID_CHAT, False), (LID_CHAT, True)])
        self.assertEqual(sends[0]["message"], WITH_CARD)
        self.assertEqual(c.db[server.WA_DM_WELCOMES].rows[0]["card"], "vcard")


class OptedInBeforeTheWelcome(_Harness, unittest.TestCase):

    def test_their_first_message_is_welcomed_then_answered(self):
        db = _assistant_db()
        _optin(db, "u_admin", ADMIN_PHONE, welcomed=False)
        with _Ctx(db=db) as c:
            self._send(c, f"{ADMIN_PHONE}@c.us", "open items at 8 walworth", "M1")
            first = _texts(c)
            c.wire.calls.clear()
            self._send(c, f"{ADMIN_PHONE}@c.us", "open items at 8 walworth", "M2")
            second = _texts(c)
        self.assertEqual(first[0], NO_CARD)
        self.assertGreaterEqual(len(first), 2, "the message is still answered")
        self.assertNotIn(NO_CARD, second)
        self.assertTrue(second)

    def test_someone_welcomed_already_just_gets_the_answer(self):
        db = _assistant_db()
        _optin(db, "u_admin", ADMIN_PHONE)
        with _Ctx(db=db) as c:
            self._send(c, f"{ADMIN_PHONE}@c.us", "open items at 8 walworth")
        self.assertNotIn(NO_CARD, _texts(c))
        self.assertTrue(_texts(c))


if __name__ == "__main__":
    unittest.main()
