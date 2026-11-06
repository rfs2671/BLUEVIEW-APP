"""`@levelog checklist` in a group: the sender is looked up in THE GROUP'S
company, never in whichever company's contact row comes first.

THE BUG (scope report 2026-11-06, item a#15). The trigger took
_find_whatsapp_contact(sender), a find_one across every company, and only
then checked that the user it named belongs to the group's company. One
person may hold an account in two companies with the same phone (Roy's
ruling, 2026-11-06). When the other company's contact row came first, an
admin of THIS company was told "You need admin or manager access".

The test runs the real group pipeline (_process_whatsapp_message) with the
WaAPI send, the group agent and the extraction itself patched out.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase0_security import (  # noqa: E402
    BOT_NUMBER, CO_A, CO_B, GROUP, HUMAN, PROJ_A, PROJ_B, _group_row, _payload,
)

REFUSAL = "You need admin or manager access to request a checklist."


def _db(contacts):
    return FakeDb(
        projects=[PROJ_A, PROJ_B],
        whatsapp_groups=[_group_row(CO_A, "proj_a", checklist_extraction_enabled=True)],
        users=[
            # The same person, one account in each company, the same phone.
            {"_id": "u_b", "company_id": CO_B, "role": "pm", "phone": "+" + HUMAN,
             "name": "Sam at B"},
            {"_id": "u_a", "company_id": CO_A, "role": "admin", "phone": "+" + HUMAN,
             "name": "Sam at A"},
        ],
        whatsapp_contacts=contacts,
    )


def _run_group(db, body):
    sent, extracted = [], []

    async def _send(chat_id, message, reply_to=None, **k):
        sent.append((chat_id, message))
        return {"ok": True}

    async def _extract(project_id, group_id, convo, company_id=None):
        extracted.append((project_id, group_id, company_id))

    async def _quiet(*a, **k):
        return None

    with patch.object(server, "db", db), \
            patch.object(server, "send_whatsapp_message", _send), \
            patch.object(server, "_react_to_message", _quiet), \
            patch.object(server, "_extract_whatsapp_checklist", _extract), \
            patch.object(server, "_detect_material_request", _quiet), \
            patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT_NUMBER}):
        asyncio.run(server._process_whatsapp_message(_payload(body)))
    return sent, extracted


class TheSenderIsReadInTheGroupsCompany(unittest.TestCase):

    def test_another_companys_row_first_does_not_refuse_this_companys_admin(self):
        """Company B's contact row is stored first. The sender is company A's
        admin in A's group: the checklist is built, nobody is refused."""
        db = _db([
            {"_id": "c_b", "company_id": CO_B, "phone": HUMAN, "user_id": "u_b"},
            {"_id": "c_a", "company_id": CO_A, "phone": HUMAN, "user_id": "u_a"},
        ])
        sent, extracted = _run_group(db, "@levelog checklist")
        self.assertFalse(any(REFUSAL in m for _g, m in sent), sent)
        self.assertEqual(extracted, [("proj_a", GROUP, CO_A)])

    def test_a_number_with_no_row_in_this_company_is_still_refused(self):
        """Only company B knows this number: an admin of B is not an admin of
        A's group, whatever the rank on B's row."""
        db = _db([{"_id": "c_b", "company_id": CO_B, "phone": HUMAN, "user_id": "u_b"}])
        db.users.rows[0]["role"] = "admin"
        sent, extracted = _run_group(db, "@levelog checklist")
        self.assertEqual(extracted, [])
        self.assertTrue(any(REFUSAL in m for g, m in sent if g == GROUP), sent)

    def test_the_lookup_takes_a_company(self):
        db = _db([
            {"_id": "c_b", "company_id": CO_B, "phone": HUMAN, "user_id": "u_b"},
            {"_id": "c_a", "company_id": CO_A, "phone": HUMAN, "user_id": "u_a"},
        ])
        with patch.object(server, "db", db):
            any_row = asyncio.run(server._find_whatsapp_contact(HUMAN))
            a_row = asyncio.run(server._find_whatsapp_contact(HUMAN, company_id=CO_A))
            none = asyncio.run(server._find_whatsapp_contact(HUMAN, company_id=""))
        self.assertEqual(any_row["_id"], "c_b")          # unchanged: the first row
        self.assertEqual(a_row["_id"], "c_a")
        self.assertIsNone(none)


if __name__ == "__main__":
    unittest.main()
