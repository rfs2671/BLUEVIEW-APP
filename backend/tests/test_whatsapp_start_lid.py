"""START from a WhatsApp privacy id (@lid): the bug, and every reply after it.

THE BUG (2026-10-07, 20:40 UTC). An admin sent START from their phone to the
bot; WhatsApp showed it delivered; nothing came back and no opt-in was
recorded. WhatsApp now identifies many 1:1 senders by a privacy id —
`<digits>@lid` — instead of `<phone>@c.us`. The DM branch took the digits of
that id as a phone number, so:

  * START looked those digits up in users.phone, found nobody, and answered
    with the neutral line, and
  * addressed the reply to `<lid digits>@c.us` — a chat that does not exist.

Opt-in refused, reply lost, nothing in the product saying either. These tests
send START the way WhatsApp now delivers it and fail on the code before the
fix: the reply goes to an @c.us address built from @lid digits.

THE RULE AFTER THE FIX: every START gets exactly one reply, to the chat it
came from — the intro, or one plain line saying what to do.
"""

from __future__ import annotations

import asyncio
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
from lib import wa_dm  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, _Ctx, _db, _Wire,
)

LID = "205842133426370"          # a privacy id, not a phone
LID_CHAT = f"{LID}@lid"
OTHER_LID_CHAT = "998877665544332@lid"
BOT = "+15165494475"


def _run(coro):
    return asyncio.run(coro)


def _payload(chat, body, msg_id="L1", extra=None):
    msg = {"id": {"id": msg_id, "fromMe": False, "remote": chat},
           "from": chat, "body": body, "type": "chat"}
    msg.update(extra or {})
    return {"event": "message", "data": {"message": msg}}


def _process(c, chat, body, msg_id="L1", extra=None):
    _run(server._process_whatsapp_message(_payload(chat, body, msg_id, extra)))


def _sends(c):
    """The send-message posts (the contact lookup posts carry no message)."""
    return [p for p in c.wire.calls if "message" in p]


def _admin(c):
    return dict(next(u for u in c.db.users.rows if u["_id"] == "u_admin"),
                id="u_admin")


def _mint(c, user=None):
    """What the app does before "Turn on alerts": POST /whatsapp/connect-link.
    Returns the code from the link."""
    with patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT}):
        out = _run(server.whatsapp_connect_link(current_user=user or _admin(c)))
    prefix = "https://wa.me/15165494475?text=START%20"
    assert out["url"].startswith(prefix), out["url"]
    return out["url"][len(prefix):]


class TheBugAsReported(unittest.TestCase):

    def test_start_from_a_lid_chat_is_answered_in_that_chat(self):
        """The 20:40 report: plain START from a @lid sender, no phone anywhere
        in the payload. Before the fix the reply went to <lid>@c.us."""
        with _Ctx() as c:
            _process(c, LID_CHAT, "START")
        sends = _sends(c)
        self.assertEqual(len(sends), 1, "exactly one reply")
        self.assertEqual(sends[0]["chatId"], LID_CHAT,
                         "the reply must go back to the @lid chat it came from")
        self.assertEqual(sends[0]["message"], wa_dm.NEED_APP_TEXT)
        self.assertEqual(c.db[server.WA_OPTINS].rows, [])

    def test_the_connect_link_connects_a_lid_sender(self):
        """The fix for the same person: the app's link sends START <code>."""
        with _Ctx() as c:
            _process(c, LID_CHAT, f"START {_mint(c)}")
            rows = c.db[server.WA_OPTINS].rows
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual((row["user_id"], row["status"], row["phone"]),
                             ("u_admin", "active", ADMIN_PHONE))
            self.assertEqual((row["chat_id"], row["chat_digits"]), (LID_CHAT, LID))
            self.assertFalse(row["phone_verified"])
            self.assertEqual([(p["chatId"], p["message"]) for p in _sends(c)],
                             [(LID_CHAT, wa_dm.INTRO_TEXT)])
            with patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT}):
                me = _run(server.whatsapp_me(current_user=_admin(c)))
            self.assertEqual(me["state"], "connected")

    def test_a_phone_in_the_payload_resolves_a_lid_sender(self):
        """When the payload does carry the number, plain START works."""
        with _Ctx() as c:
            _process(c, LID_CHAT, "START",
                     extra={"_data": {"senderPn": f"{ADMIN_PHONE}@s.whatsapp.net"}})
        rows = c.db[server.WA_OPTINS].rows
        self.assertEqual((rows[0]["user_id"], rows[0]["phone_verified"]),
                         ("u_admin", True))
        self.assertEqual(_sends(c)[0]["chatId"], LID_CHAT)

    def test_waapi_contact_lookup_resolves_a_lid_sender(self):
        wire = _Wire(responses=[
            (200, {"data": {"id": {"server": "c.us", "user": ADMIN_PHONE}}}, None)])
        with _Ctx(wire=wire) as c:
            _process(c, LID_CHAT, "START")
        self.assertEqual(c.wire.calls[0], {"contactId": LID_CHAT})
        self.assertEqual(c.db[server.WA_OPTINS].rows[0]["user_id"], "u_admin")
        self.assertEqual(_sends(c)[0]["message"], wa_dm.INTRO_TEXT)


class AfterOptingInFromALid(unittest.TestCase):

    def test_proactive_sends_go_to_the_lid_chat(self):
        with _Ctx() as c:
            _process(c, LID_CHAT, f"START {_mint(c)}")
            c.wire.calls.clear()
            out = _run(server.send_whatsapp_dm(
                "u_admin", "summary", kind="summary", window="2026-10-07"))
        self.assertIsNotNone(out)
        self.assertEqual(_sends(c)[0]["chatId"], LID_CHAT)

    def test_stop_from_the_lid_chat_ends_it(self):
        with _Ctx() as c:
            _process(c, LID_CHAT, f"START {_mint(c)}", "L1")
            _process(c, LID_CHAT, "STOP", "L2")
            self.assertEqual(c.db[server.WA_OPTINS].rows[0]["status"], "opted_out")
            self.assertEqual(_sends(c)[-1]["chatId"], LID_CHAT)
            self.assertEqual(_sends(c)[-1]["message"], wa_dm.STOP_CONFIRM_TEXT)
            self.assertIsNone(_run(server.send_whatsapp_dm(
                "u_admin", "x", kind="summary", window="w")))


class EveryStartGetsAPlainReply(unittest.TestCase):

    def _reply(self, chat, body, db=None, write_fails=False, mint=False):
        with _Ctx(db) as c:
            if mint:
                body = f"{body} {_mint(c)}"
            if write_fails:
                async def boom(*a, **k):
                    raise RuntimeError("db down")
                with patch.object(c.db[server.WA_OPTINS], "update_one", boom):
                    _process(c, chat, body)
            else:
                _process(c, chat, body)
            sends = _sends(c)
        self.assertEqual(len(sends), 1, f"{body!r} from {chat}: one reply")
        self.assertEqual(sends[0]["chatId"], wa_dm.dm_chat_id(chat))
        return sends[0]["message"], c

    def test_an_unknown_code(self):
        msg, c = self._reply(LID_CHAT, "START AAAAAA")
        self.assertEqual(msg, wa_dm.CODE_EXPIRED_TEXT)
        self.assertEqual(msg, "Levelog Assistant here. This link expired. Tap "
                              "Turn on Levelog Assistant again in the app.")
        self.assertEqual(c.db[server.WA_OPTINS].rows, [])

    def test_a_code_sent_from_another_phone(self):
        msg, c = self._reply("15557770000@c.us", "START", mint=True)
        self.assertEqual(msg, wa_dm.WRONG_PHONE_TEXT)
        self.assertEqual(c.db[server.WA_OPTINS].rows, [])

    def test_a_shared_number(self):
        db = _db()
        db.users.rows.append({"_id": "u_dup", "company_id": "co_b",
                              "role": "pm", "phone": "+" + ADMIN_PHONE})
        msg, _ = self._reply(f"{ADMIN_PHONE}@c.us", "START", db=db)
        self.assertEqual(msg, wa_dm.PHONE_SHARED_TEXT)

    def test_a_failed_write_is_said_not_swallowed(self):
        msg, _ = self._reply(f"{ADMIN_PHONE}@c.us", "START", write_fails=True)
        self.assertEqual(msg, wa_dm.TRY_AGAIN_TEXT)

    def test_plain_start_from_a_phone_still_works(self):
        msg, c = self._reply(f"{ADMIN_PHONE}@c.us", "START")
        self.assertEqual(msg, wa_dm.INTRO_TEXT)
        self.assertEqual(c.db[server.WA_OPTINS].rows[0]["chat_id"],
                         f"{ADMIN_PHONE}@c.us")

    def test_a_cp_gets_the_neutral_line(self):
        msg, _ = self._reply("15550001003@c.us", "START")
        self.assertEqual(msg, wa_dm.NOT_ELIGIBLE_TEXT)


class TheCodeIsSingleUseAndShortLived(unittest.TestCase):

    def test_a_reused_code_from_another_chat_is_refused(self):
        """Forwarded or pasted: the first START uses it, the second chat gets
        the expired line and no opt-in."""
        with _Ctx() as c:
            code = _mint(c)
            _process(c, LID_CHAT, f"START {code}", "L1")
            _process(c, OTHER_LID_CHAT, f"START {code}", "L2")
            rows = c.db[server.WA_OPTINS].rows
            self.assertEqual([(r["chat_id"], r["status"]) for r in rows],
                             [(LID_CHAT, "active")])
            last = _sends(c)[-1]
            self.assertEqual((last["chatId"], last["message"]),
                             (OTHER_LID_CHAT, wa_dm.CODE_EXPIRED_TEXT))

    def test_a_code_older_than_15_minutes_is_refused(self):
        with _Ctx() as c:
            code = _mint(c)
            row = c.db[server.WA_CONNECT_CODES].rows[0]
            self.assertAlmostEqual(
                (row["expires_at"] - row["created_at"]).total_seconds(), 900, delta=1)
            row["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            _process(c, LID_CHAT, f"START {code}")
            self.assertEqual(c.db[server.WA_OPTINS].rows, [])
            self.assertEqual(_sends(c)[-1]["message"], wa_dm.CODE_EXPIRED_TEXT)

    def test_each_link_is_its_own_single_use_code(self):
        """A refreshed link does not withdraw the one a START may already be
        carrying; each still works once."""
        with _Ctx() as c:
            old = _mint(c)
            new = _mint(c)
            self.assertNotEqual(old, new)
            _process(c, LID_CHAT, f"START {old}", "L1")
            self.assertEqual(_sends(c)[-1]["message"], wa_dm.INTRO_TEXT)
            _process(c, OTHER_LID_CHAT, f"START {old}", "L2")
            self.assertEqual(_sends(c)[-1]["message"], wa_dm.CODE_EXPIRED_TEXT)

    def test_a_wrong_phone_uses_up_the_code(self):
        with _Ctx() as c:
            code = _mint(c)
            _process(c, "15557770000@c.us", f"START {code}", "L1")
            _process(c, LID_CHAT, f"START {code}", "L2")
            self.assertEqual(c.db[server.WA_OPTINS].rows, [])

    def test_no_link_when_alerts_cannot_be_turned_on(self):
        from fastapi import HTTPException
        db = _db()
        db.users.rows[0]["phone"] = ""
        with _Ctx(db) as c:
            with self.assertRaises(HTTPException) as e:
                _mint(c)
            self.assertEqual(e.exception.status_code, 409)
            self.assertEqual(c.db[server.WA_CONNECT_CODES].rows, [])

    def test_codes_are_random_and_well_formed(self):
        codes = {wa_dm.new_connect_code() for _ in range(200)}
        self.assertGreater(len(codes), 195)
        for code in codes:
            self.assertRegex(code, r"^[A-Z2-7]{6}$")

    def test_the_ttl_index_is_declared(self):
        db = _db()
        with patch.object(server, "db", db):
            _run(server.ensure_whatsapp_phase1_indexes())
        names = {i["name"] for i in db[server.WA_CONNECT_CODES].indexes}
        self.assertIn("whatsapp_connect_codes_ttl", names)


class TheParts(unittest.TestCase):

    def test_reply_addresses(self):
        self.assertEqual(wa_dm.dm_chat_id(LID_CHAT), LID_CHAT)
        self.assertEqual(wa_dm.dm_chat_id("15550001001"), "15550001001@c.us")
        self.assertEqual(wa_dm.jid_kind(LID_CHAT), "lid")
        self.assertEqual(wa_dm.jid_kind("1555@c.us"), "c.us")

    def test_start_with_a_code_is_a_command_and_sentences_are_not(self):
        self.assertEqual(wa_dm.parse_dm_command("START K7Q2MX"), "start")
        self.assertEqual(wa_dm.parse_start_code("start k7q2mx"), "K7Q2MX")
        self.assertIsNone(wa_dm.parse_dm_command("start the pour at 7"))
        self.assertIsNone(wa_dm.parse_start_code("START"))

    def test_a_lid_in_a_phone_field_is_not_a_phone(self):
        self.assertEqual(wa_dm.phone_from_payload({"senderPn": "123@lid"}), "")
        self.assertEqual(wa_dm.phone_from_payload(
            {"x": [{"participantPn": "+1 516 301 8154"}]}), "15163018154")


if __name__ == "__main__":
    unittest.main()
