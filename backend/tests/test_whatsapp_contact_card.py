"""DM "contact" → the Levelog Assistant contact card.

The app's Save to Contacts opens WhatsApp with "contact" typed to the Levelog
number. The bot answers with its contact card: any sender (the number is
public), at most once per sender per hour, and nothing else answers it.
WaAPI send-vcard first; the .vcf as a document if that is refused.
"""

from __future__ import annotations

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
from lib import wa_contact, wa_dm  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, _Ctx, _dm_payload, _run,
)

BOT = "15165494475"
STRANGER = "15557770000"


OK = (200, {"data": {"status": "success", "data": {"sendVcard": True}}}, None)
REFUSED_200 = (200, {"data": {"status": "error", "message": "Invalid vCard",
                              "explanation": "waid is not a WhatsApp number"}}, None)


class _UrlWire:
    """Captures (action, payload); answers each action as told
    (`answers`: action -> (code, body, exc)); success otherwise."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = dict(answers or {})

    async def post_raw(self, url, payload, headers):
        action = url.rsplit("/", 1)[-1]
        self.calls.append((action, payload))
        return self.answers.get(action, OK)


def _ctx(wire):
    c = _Ctx(wire=wire)
    c._ps.append(patch.object(server, "_wa_bot_digits", lambda: BOT))
    return c


def _dm(phone, body, msg_id="M1"):
    payload = _dm_payload(phone, body, msg_id)
    # The serialized id WaAPI sends, which a reaction is addressed to.
    payload["data"]["message"]["id"]["_serialized"] = f"false_{phone}@c.us_{msg_id}"
    _run(server._process_whatsapp_message(payload))


class Keyword(unittest.TestCase):

    def test_exact_word_any_case_trimmed(self):
        for body in ("contact", "Contact", "CONTACT", "  contact \n"):
            self.assertTrue(wa_contact.is_contact_request(body), body)
        for body in ("contact me", "contacts", "send contact", "", None, "contact."):
            self.assertFalse(wa_contact.is_contact_request(body), body)

    def test_the_card(self):
        v = wa_contact.vcard_text(BOT)
        self.assertIn("FN:Levelog Assistant", v)
        self.assertIn("waid=15165494475:+1 516-549-4475", v)
        self.assertTrue(v.endswith("END:VCARD\r\n"))
        self.assertEqual(wa_contact.waapi_vcard(BOT), {
            "waid": "15165494475", "internationalnumber": "+15165494475",
            "firstname": "Levelog", "lastname": "Assistant",
            "displayname": "Levelog Assistant", "organization": "Levelog",
            "website": "https://levelog.com"})

    def test_only_status_success_is_sent(self):
        self.assertTrue(wa_contact.waapi_succeeded(OK[1]))
        self.assertFalse(wa_contact.waapi_succeeded(REFUSED_200[1]))
        self.assertFalse(wa_contact.waapi_succeeded({}))
        self.assertFalse(wa_contact.waapi_succeeded({"status": "success"}))  # top level is not data.status
        self.assertFalse(wa_contact.waapi_succeeded(
            {"status": "error", "message": "Instance not ready"}))   # outer envelope
        self.assertFalse(wa_contact.waapi_succeeded(
            {"status": "error", "data": {"status": "success"}}))    # either envelope fails it
        self.assertEqual(wa_contact.waapi_failure(REFUSED_200[1], None),
                         "status error: Invalid vCard / waid is not a WhatsApp number")


class CardSent(unittest.TestCase):

    def test_any_sender_gets_the_card_and_nothing_else(self):
        wire = _UrlWire()
        with _ctx(wire):
            _dm(STRANGER, "contact")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"])
        action, payload = wire.calls[0]
        self.assertEqual(payload["chatId"], f"{STRANGER}@c.us")
        self.assertEqual(payload["vCard"], wa_contact.waapi_vcard(BOT))

    def test_an_opted_in_admin_gets_only_the_card_no_assistant_reply(self):
        wire = _UrlWire()
        with _ctx(wire) as c:
            _dm(ADMIN_PHONE, "START", "S1")
            wire.calls.clear()
            _dm(ADMIN_PHONE, "Contact", "S2")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"])

    def _send(self, answers):
        wire = _UrlWire(answers)
        with _ctx(wire):
            _dm(STRANGER, "contact")
        return wire, [a for a, _p in wire.calls]

    def test_200_with_status_error_is_not_sent_and_falls_back(self):
        wire, actions = self._send({"send-vcard": REFUSED_200})
        self.assertEqual(actions, ["send-vcard", "send-media"])
        media = wire.calls[-1][1]
        self.assertTrue(media["mediaUrl"].endswith("/api/whatsapp/levelog-assistant.vcf"))
        self.assertEqual(media["chatId"], f"{STRANGER}@c.us")

    def test_422_is_not_retried_and_falls_back_once(self):
        _wire, actions = self._send({"send-vcard": (422, {"message": "bad"}, None)})
        self.assertEqual(actions, ["send-vcard", "send-media"])

    def test_429_is_not_retried_and_sends_nothing_more(self):
        _wire, actions = self._send({"send-vcard": (429, {"message": "slow down"}, None)})
        self.assertEqual(actions, ["send-vcard"])

    def test_outer_status_error_falls_back(self):
        _wire, actions = self._send({"send-vcard": (200, {"status": "error",
                                                          "message": "Instance not ready"}, None)})
        self.assertEqual(actions, ["send-vcard", "send-media"])

    def test_nothing_delivered_gives_the_claim_back(self):
        wire = _UrlWire({"send-vcard": REFUSED_200, "send-media": (503, None, None)})
        with _ctx(wire) as c:
            _dm(STRANGER, "contact", "F1")
            row = c.db[server.WA_CONTACT_CARD_LOG].rows[0]
            self.assertEqual(row["day_count"], 0)          # not counted
            wire.answers = {}
            _dm(STRANGER, "contact", "F2")            # asking again works
        self.assertEqual([a for a, _p in wire.calls],
                         ["send-vcard", "send-media", "send-vcard"])

    def test_a_waapi_429_keeps_the_cooldown(self):
        wire = _UrlWire({"send-vcard": (429, None, None)})
        with _ctx(wire) as c:
            _dm(STRANGER, "contact", "G1")
            self.assertEqual(c.db[server.WA_CONTACT_CARD_LOG].rows[0]["day_count"], 1)
            _dm(STRANGER, "contact", "G2")                 # in the cooldown: 👍
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard", "react-to-message"])

    def test_a_failed_fallback_is_not_retried_either(self):
        _wire, actions = self._send({"send-vcard": REFUSED_200,
                                     "send-media": (503, None, None)})
        self.assertEqual(actions, ["send-vcard", "send-media"])

    def test_the_card_goes_to_the_lid_chat_like_start(self):
        wire = _UrlWire()
        with _ctx(wire):
            _run(server._open_dm_reply_window("215556667778899"))
            _run(server._handle_dm_contact("215556667778899@lid"))
        self.assertEqual(wire.calls[0][1]["chatId"],
                         wa_dm.dm_chat_id("215556667778899@lid"))

    def test_other_words_are_not_the_card(self):
        wire = _UrlWire()
        with _ctx(wire):
            _dm(STRANGER, "contact me please")
        self.assertNotIn("send-vcard", [a for a, _p in wire.calls])

    def test_the_public_vcf(self):
        with patch.object(server, "_wa_bot_digits", lambda: BOT):
            resp = _run(server.whatsapp_public_vcard())
        self.assertEqual(resp.media_type, "text/vcard")
        self.assertIn(b"FN:Levelog Assistant", resp.body)


def _age(c, minutes):
    """Move the sender's last card `minutes` into the past."""
    row = c.db[server.WA_CONTACT_CARD_LOG].rows[0]
    row["sent_at"] = row["sent_at"] - timedelta(minutes=minutes)


class RateLimit(unittest.TestCase):
    """One card per sender per 2 minutes (a 👍 inside it), 10 a day
    (silence past that)."""

    def test_cooldown_reacts_thumbs_up_then_sends_after_two_minutes(self):
        wire = _UrlWire()
        with _ctx(wire) as c:
            _dm(STRANGER, "contact", "A1")
            _dm(STRANGER, "contact", "A2")               # 30s later: 👍
            _dm("15558880000", "contact", "B1")          # another sender: a card
            self.assertEqual([a for a, _p in wire.calls],
                             ["send-vcard", "react-to-message", "send-vcard"])
            react = wire.calls[1][1]
            self.assertEqual(react, {"messageId": f"false_{STRANGER}@c.us_A2",
                                     "reaction": "👍"})
            _age(c, 2)                                   # 2 minutes later: a card again
            _dm(STRANGER, "contact", "A3")
        self.assertEqual([a for a, _p in wire.calls][-1], "send-vcard")

    def test_the_device_case_delete_chat_and_ask_again(self):
        """Card at 2:48, asked again at 2:51 and 2:59: both get a card now."""
        wire = _UrlWire()
        with _ctx(wire) as c:
            _dm(STRANGER, "contact", "D1")
            _age(c, 3)
            _dm(STRANGER, "contact", "D2")
            _age(c, 8)
            _dm(STRANGER, "contact", "D3")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"] * 3)

    def test_ten_a_day_then_silence(self):
        wire = _UrlWire()
        with _ctx(wire) as c:
            for i in range(server.CONTACT_CARD_DAILY_MAX):
                _dm(STRANGER, "contact", f"N{i}")
                _age(c, 3)
            self.assertEqual(len(wire.calls), 10)
            _dm(STRANGER, "contact", "N10")              # 11th: nothing at all
            self.assertEqual(len(wire.calls), 10)
            # A new day starts over.
            c.db[server.WA_CONTACT_CARD_LOG].rows[0]["day"] = "2000-01-01"
            _dm(STRANGER, "contact", "N11")
        self.assertEqual([a for a, _p in wire.calls][-1], "send-vcard")
        self.assertEqual(len(wire.calls), 11)

    def test_limited_is_logged_with_the_reason(self):
        wire = _UrlWire()
        with _ctx(wire) as c, self.assertLogs(server.logger, "INFO") as logs:
            _dm(STRANGER, "contact", "L1")
            _dm(STRANGER, "contact", "L2")
            c.db[server.WA_CONTACT_CARD_LOG].rows[0].update(
                day_count=server.CONTACT_CARD_DAILY_MAX)
            _age(c, 3)
            _dm(STRANGER, "contact", "L3")
        lines = [l for l in logs.output if "[wa-contact] limited" in l]
        self.assertEqual(len(lines), 2)
        self.assertIn("reason=cooldown", lines[0])
        self.assertIn("reason=daily", lines[1])

    def test_a_row_from_the_hourly_limit_still_works(self):
        """Rows written before this change carry only sent_at."""
        wire = _UrlWire()
        with _ctx(wire) as c:
            c.db[server.WA_CONTACT_CARD_LOG].rows.append(
                {"_id": STRANGER, "sent_at": datetime.now(timezone.utc) - timedelta(minutes=5)})
            _dm(STRANGER, "contact", "O1")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"])

    def test_a_limited_message_gets_no_other_reply(self):
        wire = _UrlWire()
        with _ctx(wire):
            _dm(STRANGER, "contact", "A1")
            wire.calls.clear()
            _dm(STRANGER, "contact", "A2")
        self.assertEqual([a for a, _p in wire.calls], ["react-to-message"])


if __name__ == "__main__":
    unittest.main()
