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


class _UrlWire:
    """Captures (action, payload); answers each action as told."""

    def __init__(self, refuse=()):
        self.calls = []
        self.refuse = set(refuse)

    async def post_raw(self, url, payload, headers):
        action = url.rsplit("/", 1)[-1]
        self.calls.append((action, payload))
        if action in self.refuse:
            return 400, {"error": "bad"}, None
        return 200, {"data": {"status": "success"}}, None


def _ctx(wire):
    c = _Ctx(wire=wire)
    c._ps.append(patch.object(server, "_wa_bot_digits", lambda: BOT))
    return c


def _dm(phone, body, msg_id="M1"):
    _run(server._process_whatsapp_message(_dm_payload(phone, body, msg_id)))


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
        o = wa_contact.waapi_vcard(BOT)
        self.assertEqual((o["fullName"], o["phoneNumber"]),
                         ("Levelog Assistant", "+15165494475"))


class CardSent(unittest.TestCase):

    def test_any_sender_gets_the_card_and_nothing_else(self):
        wire = _UrlWire()
        with _ctx(wire):
            _dm(STRANGER, "contact")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"])
        action, payload = wire.calls[0]
        self.assertEqual(payload["chatId"], f"{STRANGER}@c.us")
        self.assertEqual(payload["vCard"]["fullName"], "Levelog Assistant")

    def test_an_opted_in_admin_gets_only_the_card_no_assistant_reply(self):
        wire = _UrlWire()
        with _ctx(wire) as c:
            _dm(ADMIN_PHONE, "START", "S1")
            wire.calls.clear()
            _dm(ADMIN_PHONE, "Contact", "S2")
        self.assertEqual([a for a, _p in wire.calls], ["send-vcard"])

    def test_refused_vcard_falls_back_to_the_vcf_document(self):
        wire = _UrlWire(refuse={"send-vcard"})
        with _ctx(wire):
            _dm(STRANGER, "contact")
        self.assertEqual([a for a, _p in wire.calls][-1], "send-media")
        media = wire.calls[-1][1]
        self.assertTrue(media["mediaUrl"].endswith("/api/whatsapp/levelog-assistant.vcf"))
        self.assertEqual(media["chatId"], f"{STRANGER}@c.us")

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


class RateLimit(unittest.TestCase):

    def test_once_per_sender_per_hour(self):
        wire = _UrlWire()
        with _ctx(wire) as c:
            _dm(STRANGER, "contact", "A1")
            _dm(STRANGER, "contact", "A2")          # same hour: nothing
            _dm("15558880000", "contact", "B1")     # another sender: sent
            self.assertEqual([a for a, _p in wire.calls], ["send-vcard", "send-vcard"])
            # An hour later the sender may have it again.
            c.db[server.WA_CONTACT_CARD_LOG].rows[0]["sent_at"] = (
                datetime.now(timezone.utc) - timedelta(hours=1, minutes=1))
            _dm(STRANGER, "contact", "A3")
        self.assertEqual(len(wire.calls), 3)

    def test_rate_limited_message_gets_no_other_reply(self):
        wire = _UrlWire()
        with _ctx(wire):
            _dm(STRANGER, "contact", "A1")
            wire.calls.clear()
            _dm(STRANGER, "contact", "A2")
        self.assertEqual(wire.calls, [])


if __name__ == "__main__":
    unittest.main()
