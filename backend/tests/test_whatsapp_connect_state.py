"""GET /whatsapp/me: the one state the Integrations screen shows.

Each blocked state must name the first thing to fix, and the Connect link is
offered only when pressing it can work. "Phone shared" is START's own refusal
rule seen from the screen: if another live account carries the number, START
opts nobody in, so offering Connect would send the user into a neutral
"not available" reply with no explanation.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_dm  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

BOT = "+15550000000"
PHONE = "15550001001"


def _admin(**kw):
    u = {"_id": "u_admin", "id": "u_admin", "company_id": "co_a",
         "role": "admin", "phone": "+" + PHONE, "email": "a@a"}
    u.update(kw)
    return u


def _me(user, *, users=None, optins=None, bot=BOT):
    db = FakeDb(unique={server.WA_OPTINS: ("phone",)},
                users=users if users is not None else [_admin()])
    for row in optins or []:
        db[server.WA_OPTINS].rows.append(row)
    with patch.object(server, "db", db), \
            patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": bot}):
        return asyncio.run(server.whatsapp_me(current_user=user))


def _optin(phone=PHONE, status="active", user_id="u_admin"):
    return {"_id": f"o_{phone}_{status}", "phone": phone, "user_id": user_id,
            "status": status, "updated_at": datetime.now(timezone.utc)}


class TheStates(unittest.TestCase):

    def test_not_connected_offers_the_link(self):
        out = _me(_admin())
        self.assertEqual(out["state"], "not_connected")
        self.assertEqual(out["connect_url"], "https://wa.me/15550000000?text=START")
        self.assertFalse(out["connected"])

    def test_connected_shows_the_number_and_no_link(self):
        out = _me(_admin(), optins=[_optin()])
        self.assertEqual(out["state"], "connected")
        self.assertTrue(out["connected"])
        self.assertEqual(out["phone"], "+" + PHONE)
        self.assertIsNone(out["connect_url"])

    def test_phone_missing(self):
        out = _me(_admin(phone=""), users=[_admin(phone="")])
        self.assertEqual(out["state"], "phone_missing")
        self.assertIsNone(out["connect_url"])

    def test_phone_on_another_account_is_shared(self):
        other = {"_id": "u_other", "company_id": "co_b", "role": "cp",
                 "phone": PHONE}
        out = _me(_admin(), users=[_admin(), other])
        self.assertEqual(out["state"], "phone_shared")
        self.assertIsNone(out["connect_url"])

    def test_a_deleted_account_on_the_number_does_not_count(self):
        gone = {"_id": "u_gone", "company_id": "co_b", "phone": PHONE,
                "is_deleted": True}
        self.assertEqual(_me(_admin(), users=[_admin(), gone])["state"],
                         "not_connected")

    def test_a_changed_phone_needs_reconnecting(self):
        out = _me(_admin(phone="+15557770000"),
                  users=[_admin(phone="+15557770000")], optins=[_optin()])
        self.assertEqual(out["state"], "reconnect_needed")
        self.assertTrue(out["connect_url"])
        self.assertFalse(out["connected"])

    def test_opted_out_is_not_connected(self):
        out = _me(_admin(), optins=[_optin(status="opted_out")])
        self.assertEqual(out["state"], "not_connected")
        self.assertTrue(out["connect_url"])

    def test_no_bot_number_is_unavailable(self):
        out = _me(_admin(), bot="")
        self.assertEqual(out["state"], "unavailable")
        self.assertIsNone(out["connect_url"])

    def test_ineligible_roles_get_nothing(self):
        for role in ("cp", "superintendent", "worker", "owner", "demo", ""):
            out = _me(_admin(role=role))
            self.assertEqual(out["state"], "not_eligible", role)
            self.assertFalse(out["eligible"])
            self.assertIsNone(out["connect_url"])
            self.assertIsNone(out["phone"])

    def test_a_pm_is_eligible(self):
        self.assertEqual(_me(_admin(role="pm"))["state"], "not_connected")

    def test_no_company_is_not_eligible(self):
        self.assertEqual(_me(_admin(company_id=""))["state"], "not_eligible")


class TheOrder(unittest.TestCase):
    """The first thing to fix is reported, not the last."""

    def test_order(self):
        def st(**kw):
            base = dict(eligible=True, bot_configured=True, has_phone=True,
                        phone_shared=False, optin_status="none")
            base.update(kw)
            return wa_dm.connect_state(**base)
        self.assertEqual(st(eligible=False, has_phone=False), "not_eligible")
        self.assertEqual(st(bot_configured=False, has_phone=False), "unavailable")
        self.assertEqual(st(has_phone=False, phone_shared=True), "phone_missing")
        self.assertEqual(st(phone_shared=True, optin_status="phone_changed"),
                         "phone_shared")
        self.assertEqual(st(optin_status="phone_changed"), "reconnect_needed")
        self.assertEqual(st(optin_status="active"), "connected")
        self.assertEqual(st(optin_status="superseded"), "not_connected")


if __name__ == "__main__":
    unittest.main()
