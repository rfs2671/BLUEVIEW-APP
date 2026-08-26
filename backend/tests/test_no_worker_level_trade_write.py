"""Nothing writes trade or company onto the workers document.

THE RULE, stated where the collection is defined (server.py:10949-10981): a
worker's trade and company belong to the {worker, project} PAIR, never to the
worker alone. register_and_checkin repeats it where it builds the document --
"no `trade` / `company` here. Those are per-project and live in
worker_project_trades; a worker-level copy is what bled across jobs" -- and
_get_worker_project_trade refuses to fall back to the worker doc for the same
reason: "a value from another project is worse than no value, because it is
silently wrong instead of visibly absent."

THE HOLE. PUT /workers/{id} admitted both fields, and the worker detail screen
offered an admin two inputs for them -- directly beneath a card reading "No
trade specified / No company". So the screen invited exactly the forbidden
write at the moment an admin was most motivated to make it, and the value it
wrote would have been global: overriding nothing, contradicting every
per-project pairing, and looking correct on the one screen that displayed it.

WHAT THIS DOES NOT DO. It does not change what the card says -- that is the
copy fix, sequenced separately -- and it does not add a pairings endpoint. It
closes the write.

    python backend/tests/test_no_worker_level_trade_write.py
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
         "account_status": "approved"}
WORKER = {"_id": "w1", "id": "w1", "name": "Andre Duval", "company_id": "companyA",
          "phone": "5551234567"}


def _put(body):
    """Drive update_worker against doubles. Returns the captured $set."""
    captured = {}

    async def workers_update_one(q, upd, *a, **kw):
        captured["set"] = upd.get("$set", {})
        r = MagicMock()
        r.matched_count = 1
        r.modified_count = 1
        return r

    db = MagicMock()
    db.workers.find_one = AsyncMock(return_value=dict(WORKER))
    db.workers.update_one = AsyncMock(side_effect=workers_update_one)

    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()):
        asyncio.run(server.update_worker(
            worker_id="w1", worker_data=body, worker=dict(WORKER),
        ))
    return captured.get("set", {})


class TheWriteIsClosed(unittest.TestCase):

    def test_trade_is_not_persisted(self):
        """THE REPORTED PATH. An admin looking at "No trade specified" typed a
        trade in and saved it."""
        setops = _put({"trade": "Framers"})
        self.assertNotIn("trade", setops)

    def test_company_is_not_persisted(self):
        setops = _put({"company": "Arkon Builders"})
        self.assertNotIn("company", setops)

    def test_neither_is_persisted_when_sent_together(self):
        """What the Edit form actually sent: name, trade, company, osha_number
        and certifications in one body."""
        setops = _put({
            "name": "Andre Duval",
            "trade": "Framers",
            "company": "Arkon Builders",
            "osha_number": "12345678",
        })
        self.assertNotIn("trade", setops)
        self.assertNotIn("company", setops)

    def test_and_the_rest_of_that_body_still_saves(self):
        """A guard that refuses the whole request would break renaming a
        worker, which is the edit form's actual job."""
        setops = _put({
            "name": "Andre Duval",
            "trade": "Framers",
            "company": "Arkon Builders",
            "osha_number": "12345678",
        })
        self.assertEqual(setops["name"], "Andre Duval")
        self.assertEqual(setops["osha_number"], "12345678")

    def test_the_allowlist_no_longer_names_them(self):
        """The mechanism, not just the outcome -- an allowlist is only as good
        as what it lists."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("ALLOWED_WORKER_FIELDS = {")
        decl = src[i:src.index("}", i) + 1]
        self.assertNotIn('"trade"', decl)
        self.assertNotIn('"company"', decl)

    def test_company_id_is_still_excluded(self):
        """Unchanged and pinned: moving a worker between tenants is a separate,
        audited operation, not a field edit."""
        setops = _put({"company_id": "companyB"})
        self.assertNotIn("company_id", setops)


class TheOrdinaryEditIsUntouched(unittest.TestCase):
    """A guard that refuses too much is as wrong as one that refuses nothing."""

    def test_a_rename_still_works(self):
        setops = _put({"name": "Andre R. Duval"})
        self.assertEqual(setops["name"], "Andre R. Duval")

    def test_phone_still_works(self):
        setops = _put({"phone": "5559998888"})
        self.assertEqual(setops["phone"], "5559998888")

    def test_certifications_still_save(self):
        """The same screen's other job, and the one an admin actually needs."""
        certs = [{"type": "OSHA_10", "card_number": "123"}]
        setops = _put({"certifications": certs})
        self.assertEqual(setops["certifications"], certs)

    def test_emergency_contact_still_saves(self):
        setops = _put({"emergency_contact": "Marie", "emergency_phone": "5551112222"})
        self.assertEqual(setops["emergency_contact"], "Marie")
        self.assertEqual(setops["emergency_phone"], "5551112222")


class ThePairingIsStillTheSourceOfTruth(unittest.TestCase):
    """Closing the write must not disturb the thing that holds the real value."""

    def test_the_pairing_helper_still_exists(self):
        self.assertTrue(callable(server._get_worker_project_trade))

    def test_it_still_refuses_to_fall_back_to_the_worker_document(self):
        """The invariant this whole design protects. A value from another
        project is worse than no value."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index("async def _get_worker_project_trade")
        body = src[i:src.index("\n\n\n", i)]
        self.assertIn("NEVER falls", body)
        self.assertNotIn("db.workers", body)

    def test_the_gate_writers_still_own_the_pairing(self):
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        self.assertIn("WORKER_PROJECT_TRADES_COLLECTION", src)
        self.assertIn("worker_project_trades", src)


class WhatIsNotClosedYet(unittest.TestCase):
    """Reported rather than fixed silently, and pinned so it cannot be
    mistaken for handled."""

    def test_WorkerCreate_STILL_requires_trade_and_company(self):
        """A THIRD WRITER. POST /workers takes WorkerCreate, which requires
        both fields, and model_dump() puts them straight onto the document.

        It is dead in practice -- its own docstring says "no screen calls this",
        and workersAPI.create reaches only useWorkers.createWorker, which no
        component destructures -- so it is out of scope for a PR about the edit
        path. It is live in the MODEL, and this pins that so the next reader
        does not assume the rule is enforced everywhere.
        """
        fields = server.WorkerCreate.model_fields
        self.assertIn("trade", fields)
        self.assertIn("company", fields)
        self.assertTrue(fields["trade"].is_required())
        self.assertTrue(fields["company"].is_required())

    def test_WorkerResponse_still_declares_them_optional(self):
        """Deliberate and unchanged. The fields exist in the schema so a legacy
        document that carries them still serialises; nothing populates them."""
        fields = server.WorkerResponse.model_fields
        self.assertFalse(fields["trade"].is_required())
        self.assertFalse(fields["company"].is_required())


if __name__ == "__main__":
    unittest.main(verbosity=2)
