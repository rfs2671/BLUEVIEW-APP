"""ONLY THE SUPERINTENDENT AND THE CP FILL IN A LOG. EVERYONE ELSE READS IT
AND ADDS PHOTOGRAPHS.

Operator ruling, 2026-11-18: "only super should have access [to fill in log
books]; sm or pm can only view it and add photos." Confirmed: the
SUPERINTENDENT and the CP may fill and sign a logbook. A Site Manager / PM AT
EITHER ACCESS LEVEL -- "Assigned jobs only" AND "Same as admin" -- and a
company ADMIN may only view a filed log and add photographs to it.

── WHY THE OLD RULE LEAKED ─────────────────────────────────────────────────

The old gate was a DENY-list, `ROLES_WITH_READ_ONLY_LOGBOOKS = (ROLE_PM,)`,
and it exempted a PM on "Same as admin" (`pm_has_full_access`). So the
read-only rule held for exactly one population -- the assigned-jobs PM -- and
everyone else the ruling names (the full PM, the admin) filed and signed. In
production one Daily Jobsite Log was filed by a full-access PM. A deny-list
also admits every role nobody thought to list; an ALLOW-list does not.

── WHAT IS DRIVEN HERE ─────────────────────────────────────────────────────

Real requests through server.app -- every middleware, the route's own
dependencies, a real JWT through get_current_user -- with only the database
replaced (tests/async_fake_mongo.py). Each role is asked to create, update,
finalize, amend and sign a log, and to save the scaffold project memory, and
to append a photograph:

  superintendent, cp        file and sign            (2xx on every act)
  pm assigned, pm full,     refused with 403          (every filing act)
  admin
  all five                  append a photograph       (2xx)

The admin's DELETE of a mistaken log is kept and asserted separately: removing
a log filed in error is an administrative act, not filling one in.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB, _Result  # noqa: E402

CO = "co-filing"
PROJ = ObjectId()
DAY = "2026-11-18"

#: who the request is, as the user document holds it
ROLES = {
    "superintendent": {"role": "superintendent"},
    "cp": {"role": "cp"},
    "pm_assigned": {"role": "pm", "pm_access": "assigned"},
    "pm_full": {"role": "pm", "pm_access": "full"},
    "admin": {"role": "admin"},
}
FILERS = ("superintendent", "cp")
READERS = ("pm_assigned", "pm_full", "admin")

#: the smallest 1x1 PNG; the photo route sniffs the magic number
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
       b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _db():
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": PROJ, "company_id": CO, "name": "Tower",
                             "status": "active", "is_deleted": False})
    users = {}
    for key, extra in ROLES.items():
        uid = ObjectId()
        doc = {"_id": uid, "email": f"{key}@filing.test", "name": key,
               "full_name": key, "company_id": CO,
               "assigned_projects": [str(PROJ)], "account_status": "approved",
               "is_deleted": False, "password": "x", **extra}
        db.users.docs.append(doc)
        users[key] = doc
    return db, users


def _seed_log(db, owner, *, signed=False, locked=False):
    """A daily jobsite log on the project, written by `owner`."""
    lid = ObjectId()
    db.logbooks.docs.append({
        "_id": lid, "project_id": str(PROJ), "company_id": CO,
        "log_type": "daily_jobsite", "date": DAY,
        "status": "submitted" if (signed or locked) else "draft",
        "is_locked": locked, "is_deleted": False,
        "created_by": str(owner["_id"]),
        "data": {"activities": [{"activity_id": "act-1", "photos": []}],
                 "weather": "clear"},
        "cp_signature": {"paths": ["M0 0 L1 1"], "signerName": "x"} if signed else None,
        "cp_name": "x" if signed else None,
    })
    return str(lid)


def _token(user):
    return server.create_token(str(user["_id"]), user["email"], user["role"],
                               company_id=user["company_id"])


async def _send(db, user, method, path, **kw):
    with patch.object(server, "db", db):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                     base_url="http://t") as c:
            r = await c.request(method, path,
                                headers={"Authorization": f"Bearer {_token(user)}"}, **kw)
            return r.status_code, r.text[:300]


def _run(coro):
    return asyncio.run(coro)


def _acts(db, users, who):
    """Every filing act, for one role, each on its own fresh document."""
    user = users[who]
    out = {}
    out["create"] = _run(_send(db, user, "POST", "/api/logbooks", json={
        "project_id": str(PROJ), "log_type": "daily_jobsite", "date": DAY,
        "data": {"made_by_create": who}, "status": "draft"}))
    lid = _seed_log(db, user)
    out["update"] = _run(_send(db, user, "PUT", f"/api/logbooks/{lid}",
                               json={"data": {"weather": "rain"}}))
    lid = _seed_log(db, user, signed=True)
    out["finalize"] = _run(_send(db, user, "POST", f"/api/logbooks/{lid}/finalize"))
    lid = _seed_log(db, user, signed=True, locked=True)
    out["amend"] = _run(_send(db, user, "POST", f"/api/logbooks/{lid}/amend",
                              json={"reason": "a worker was left off the roster"}))
    lid = _seed_log(db, user)
    out["sign"] = _run(_send(db, user, "POST", "/api/signature-events", json={
        "document_type": "logbook", "document_id": lid, "event_type": "cp_sign",
        "signer_name": who, "signer_role": "cp", "acting_capacity": "Competent Person",
        "signature_data": {"paths": ["M0 0 L1 1"]}, "content_snapshot": {"x": 1}}))
    out["scaffold-info"] = _run(_send(
        db, user, "PUT", f"/api/logbooks/project/{PROJ}/scaffold-info",
        json={"permit_number": "P-1"}))
    return out


class OnlyTheSuperAndTheCpFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db, cls.users = _db()
        cls.got = {who: _acts(cls.db, cls.users, who) for who in ROLES}

    def test_the_superintendent_and_the_cp_file_and_sign(self):
        for who in FILERS:
            for act, (status, body) in self.got[who].items():
                self.assertTrue(200 <= status < 300,
                                f"{who} {act}: {status} {body}")

    def test_a_pm_at_either_level_and_an_admin_are_refused_every_filing_act(self):
        """THE LEAK. pm_full and admin were the populations the deny-list
        exempted; pm_assigned is asserted with them so the rule is one rule."""
        for who in READERS:
            for act, (status, body) in self.got[who].items():
                self.assertEqual(status, 403, f"{who} {act}: {status} {body}")

    def test_the_refusal_names_who_files(self):
        status, body = self.got["pm_full"]["create"]
        self.assertEqual(status, 403)
        self.assertIn("superintendent or the CP", body)

    def test_a_refused_act_wrote_nothing(self):
        """A 403 after the insert is a filed log with a refusal attached."""
        readers = {str(self.users[w]["_id"]) for w in READERS}
        filers = {str(self.users[w]["_id"]) for w in FILERS}
        # POST /logbooks DEDUPES onto the day's open row, so a create does not
        # always mint a document; it always leaves its content. Who wrote the
        # content is therefore read from the content, not from `created_by`.
        wrote = {(d.get("data") or {}).get("made_by_create") for d in self.db.logbooks.docs}
        signed = lambda ids: [e for e in self.db.signature_events.docs  # noqa: E731
                              if str((e.get("signer") or {}).get("user_id") or "") in ids]
        # The probe can see a write: a filer's create landed, each filer signed
        # (finalize derives ledger rows of its own, so "at least").
        self.assertTrue(wrote & set(FILERS), wrote)
        self.assertGreaterEqual(len(signed(filers)), len(FILERS))
        self.assertEqual(wrote & set(READERS), set())
        self.assertEqual(signed(readers), [])
        edited = [d for d in self.db.logbooks.docs
                  if d.get("created_by") in readers
                  and (d.get("data") or {}).get("weather") == "rain"]
        self.assertEqual(edited, [])


def _photo(db, user, lid):
    return _run(_send(db, user, "POST", f"/api/logbooks/{lid}/activity-photo",
                      data={"activity_id": "act-1", "photo_id": "ph-1"},
                      files={"file": ("p.png", io.BytesIO(PNG), "image/png")}))


class EveryoneWhoReadsItAddsPhotographs(unittest.TestCase):
    """The one write the ruling grants the reader. Storage is stubbed and the
    positional $push is recorded rather than applied (the fake cannot apply
    it); what is under test is that the request REACHES the write."""

    def test_all_five_append_a_photograph_to_a_filed_log(self):
        db, users = _db()
        lid = _seed_log(db, users["superintendent"], signed=True, locked=True)
        pushes = []
        real_update = db.logbooks.update_one

        async def update_one(flt, update, *a, **k):
            if "$push" in update:
                pushes.append(update)
                return _Result(matched_count=1, modified_count=1)
            return await real_update(flt, update, *a, **k)

        db.logbooks.update_one = update_one
        with patch.object(server, "_r2_client", object()), \
                patch.object(server, "R2_BUCKET_NAME", "bucket"), \
                patch.object(server, "_upload_to_r2", lambda *a, **k: None):
            for who in ROLES:
                status, body = _photo(db, users[who], lid)
                self.assertTrue(200 <= status < 300, f"{who}: {status} {body}")
        self.assertEqual(len(pushes), len(ROLES))


class AnAdminStillRemovesAMistakenLog(unittest.TestCase):
    """Deleting a log filed in error is administration, not filling one in.
    The PM -- at either level -- is refused, as before for the assigned PM."""

    def test_admin_deletes_and_pm_does_not(self):
        db, users = _db()
        for who, want in (("admin", 200), ("pm_full", 403), ("pm_assigned", 403)):
            lid = _seed_log(db, users["cp"])
            status, body = _run(_send(db, users[who], "DELETE", f"/api/logbooks/{lid}"))
            self.assertEqual(status, want, f"{who}: {status} {body}")

    def test_a_filer_deletes_his_own(self):
        db, users = _db()
        lid = _seed_log(db, users["cp"])
        status, body = _run(_send(db, users["cp"], "DELETE", f"/api/logbooks/{lid}"))
        self.assertEqual(status, 200, body)


class TheGateIsAnAllowList(unittest.TestCase):

    def test_the_filers_are_named(self):
        self.assertEqual(set(server.ROLES_THAT_FILE_LOGBOOKS),
                         {server.ROLE_SUPERINTENDENT, "cp"})

    def test_a_role_nobody_listed_is_refused(self):
        """What a deny-list gets wrong: a legacy or future role files by
        default. 'owner' is retired and 'worker' withdrawn; neither files."""
        from fastapi import HTTPException
        for role in ("owner", "worker", "", "Admin"):
            with self.assertRaises(HTTPException, msg=role):
                server.refuse_if_logbooks_are_read_only({"role": role})

    def test_the_site_device_keeps_what_it_had(self):
        """Unchanged by the ruling. The tablet's later gates (project access,
        user_can_act_on_project) still decide what it may touch."""
        server.refuse_if_logbooks_are_read_only({"role": "site_device", "site_mode": True})


if __name__ == "__main__":
    unittest.main()
