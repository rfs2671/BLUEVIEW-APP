""""mute B<permit> <reason>" / "unmute B<permit>" in a WhatsApp DM (Roy,
2026-11-11): an ADMIN takes a permit's expired line out of the morning
brief's daily part - it stays in Monday's weekly section, with the reason.
Admin only, audit-logged, undone by "unmute". Answered in code, never by
the model."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import wa_brief  # noqa: E402
from tests.test_whatsapp_gc_alerts import synced_state  # noqa: E402
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    ADMIN_PHONE, CO_A, PM_PHONE, THOMAS, _Ctx, _db, _Harness, _optin, _run,
)

PERMIT = "B23173802-S5"
TUE_8 = datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)


def _world():
    db = _db()
    # Every job's sources first synced long ago (lib/source_sync.py).
    db[server.SOURCE_SYNC_STATE].rows.extend(
        synced_state(str(p["_id"]), (str(p["_id"]), p.get("company_id")))
        for p in db.projects.rows)
    db.dob_logs.rows.append({
        "_id": "p_s5", "project_id": THOMAS, "record_type": "permit",
        "raw_dob_id": f"permit:{PERMIT}", "job_number": PERMIT,
        "work_type": "General Construction", "expiration_date": "2026-09-01",
        "permit_status": "ISSUED", "current_status": "ISSUED", "previous_status": None,
        "detected_at": TUE_8 - timedelta(days=300)})
    _optin(db, "u_admin", ADMIN_PHONE)
    _optin(db, "u_pm", PM_PHONE)
    return db


def _mutes(db):
    return db[server.BRIEF_PERMIT_MUTES].rows


def _audits(db, action):
    return [r for r in db.audit_logs.rows if r.get("action") == action]


def _daily(db):
    """The permit's lines in a Tuesday brief of THOMAS (not the weekly one)."""
    with _Ctx(db=db):
        job = _run(server._brief_job({"_id": THOMAS, "name": "Thomas",
                                      "address": "588 Thomas S Boyland St"},
                                     CO_A, TUE_8 - timedelta(days=1), TUE_8, None, False))
    return [i["text"] for i in job["items"] if PERMIT in i["text"]]


class TheCommand(_Harness, unittest.TestCase):

    def test_an_admin_mutes_and_unmutes_it_audited(self):
        db = _world()
        self.assertEqual(len(_daily(db)), 1)                       # said every morning
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", f"mute {PERMIT} sign-off pending", "m1")
        self.assertTrue(reply.startswith(f"Muted {PERMIT}"), reply)
        self.assertEqual(self.agent_calls, [])                     # code, not the model
        row = _mutes(db)[0]
        self.assertEqual((row["company_id"], row["permit"], row["active"], row["reason"],
                          row["muted_by"]), (CO_A, PERMIT, True, "sign-off pending", "u_admin"))
        audit = _audits(db, "brief_permit_mute")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["details"]["reason"], "sign-off pending")
        self.assertEqual(_daily(db), [])                           # not daily any more
        with _Ctx(db=db):
            weekly = _run(server._brief_job({"_id": THOMAS, "name": "Thomas",
                                             "address": "588 Thomas S Boyland St"},
                                            CO_A, TUE_8 - timedelta(days=1), TUE_8, None, True))
        self.assertIn("Muted: sign-off pending.", "\n".join(i["text"] for i in weekly["items"]))

        with _Ctx(db=db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us", f"unmute {PERMIT}", "m2")
        self.assertTrue(reply.startswith(f"Unmuted {PERMIT}"), reply)
        row = _mutes(db)[0]
        self.assertFalse(row["active"])
        self.assertEqual([h["action"] for h in row["history"]], ["mute", "unmute"])
        self.assertEqual(len(_audits(db, "brief_permit_unmute")), 1)
        self.assertEqual(len(_daily(db)), 1)                       # daily again

    def test_a_pm_cannot(self):
        db = _world()
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{PM_PHONE}@c.us", f"mute {PERMIT} not ours", "m1")
        self.assertEqual(reply, "Only an admin can mute or unmute a permit in the brief.")
        self.assertEqual((_mutes(db), _audits(db, "brief_permit_mute")), ([], []))
        self.assertEqual(len(_daily(db)), 1)

    def test_a_reason_is_required_and_the_permit_must_be_theirs(self):
        db = _world()
        with _Ctx(db=db) as c:
            no_reason = self._send(c, f"{ADMIN_PHONE}@c.us", f"mute {PERMIT}", "m1")
            unknown = self._send(c, f"{ADMIN_PHONE}@c.us", "mute B77777777-I1 not ours", "m2")
            not_muted = self._send(c, f"{ADMIN_PHONE}@c.us", f"unmute {PERMIT}", "m3")
        self.assertEqual(no_reason, f"Say why, so the team can see it: mute {PERMIT} <reason>")
        self.assertEqual(unknown, "I can't find permit B77777777-I1 on your jobs.")
        self.assertEqual(not_muted, f"{PERMIT} isn't muted.")
        self.assertEqual(_mutes(db), [])

    def test_spanish(self):
        db = _world()
        with _Ctx(db=db) as c:
            reply = self._send(c, f"{ADMIN_PHONE}@c.us",
                               f"mute {PERMIT} el trabajo ya terminó, falta la inspección final", "m1")
        self.assertTrue(reply.startswith(f"Silenciado {PERMIT}"), reply)

    def test_another_companys_mute_does_not_apply(self):
        db = _world()
        db[server.BRIEF_PERMIT_MUTES].rows.append({
            "_id": f"co_b:{PERMIT}", "company_id": "co_b", "permit": PERMIT,
            "active": True, "reason": "theirs"})
        self.assertEqual(len(_daily(db)), 1)
        with _Ctx(db=db):
            self.assertEqual(_run(server._permit_mutes(CO_A)), {})
            self.assertEqual(_run(server._permit_mutes("co_b")), {PERMIT: "theirs"})


if __name__ == "__main__":
    unittest.main()
