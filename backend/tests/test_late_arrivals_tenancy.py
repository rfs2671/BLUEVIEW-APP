"""Another tenant cannot drive POST /logbooks/project/{id}/daily-jobsite/late-arrivals.

THE ROUTE (#1049) opens a correction of a company's SIGNED Daily Jobsite Log and
answers with the names of the workers who checked in after it was signed. Both
halves are tenant data: the write is a compliance record, the answer is a
roster. Its only project gate is a PARAMETER-STYLE dependency,

    _proj = Depends(require_project_access),

which the project-write census (test_project_writes_authorize_the_project.py)
did not recognise and reported as unguarded. That census was misreading a
guarded route, and this file is the proof that the route really is guarded:
the claim is about who REACHES the handler, so it is tested with requests.

THESE ARE REQUESTS, NOT UNIT CALLS. Every one goes through server.app over
ASGI: the real middleware stack, the real dependencies, the real JWT. Only the
database is replaced (tests/async_fake_mongo.py).

THE SEED IS A ROUTE THAT WOULD WRITE. Company A's project has today's Daily
Jobsite Log signed, and a worker checked in at the gate who is not on it -- so
any caller who reaches the body with write authority opens a correction. The
control (A's own assigned CP) proves the seed does that; without it, "B wrote
nothing" could pass on a route that writes for nobody.

CONTROL RUN. With `_proj = Depends(require_project_access)` deleted from the
route, the three outsiders get 200 and the body names A's late worker (the
write guard inside still stops the insert, so the dependency is what stops the
roster leaking). These tests fail that way; they pass with the dependency.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

CO_A = ObjectId()
CO_B = ObjectId()
PROJ_A = ObjectId()
SIGNED_LOG = ObjectId()
LATE_WORKER = ObjectId()
# A string that exists ONLY in company A's gate record. If it appears in a
# response to an outsider, A's roster was served.
LATE_NAME = "Larkin Latecomer-7f3e"

PW = "pw-late-arrivals-1"

USERS = {
    # Company A's CP, assigned to the project: the one who SHOULD get a
    # correction opened.
    "cp_a": {"role": "cp", "company_id": str(CO_A),
             "assigned_projects": [str(PROJ_A)]},
    # Another tenant's admin and CP.
    "admin_b": {"role": "admin", "company_id": str(CO_B)},
    "cp_b": {"role": "cp", "company_id": str(CO_B)},
    # The default state of every self-serve signup: role owner, no company.
    "owner_none": {"role": "owner", "company_id": None},
}
OUTSIDERS = ("admin_b", "cp_b", "owner_none")


def _seed():
    db = AsyncFakeDB()
    now = datetime.now(timezone.utc)
    today = server.eastern_today()
    db.companies.docs.append({"_id": CO_A, "name": "Acme GC", "is_deleted": False})
    db.companies.docs.append({"_id": CO_B, "name": "Other GC", "is_deleted": False})
    db.projects.docs.append({"_id": PROJ_A, "company_id": str(CO_A),
                             "name": "Tower", "status": "active",
                             "is_deleted": False})
    db.logbooks.docs.append({
        "_id": SIGNED_LOG, "project_id": str(PROJ_A), "company_id": str(CO_A),
        "project_name": "Tower", "log_type": "daily_jobsite", "date": today,
        "status": "submitted", "is_locked": True,
        "cp_signature": "data:image/png;base64,AAAA", "cp_name": "A Cp",
        "data": {"activities": [{"company": "J&P", "worker_ids": ["on-the-log"]}]},
        "created_at": now, "is_deleted": False,
    })
    db.checkins.docs.append({
        "_id": ObjectId(), "project_id": str(PROJ_A), "worker_id": str(LATE_WORKER),
        "worker_name": LATE_NAME, "worker_company": "J&P",
        "status": "checked_in", "check_in_time": now, "is_deleted": False,
    })
    for key, extra in USERS.items():
        db.users.docs.append({
            "_id": ObjectId(), "email": f"{key}@late.test", "name": key,
            "password": server.hash_password(PW), "account_status": "approved",
            "is_deleted": False, **extra,
        })
    return db


async def _scenario():
    db = _seed()
    out = {}
    with patch.object(server, "db", db):
        if hasattr(server.auth_rate_limiter, "requests"):
            server.auth_rate_limiter.requests.clear()
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            tokens = {}
            for key in USERS:
                r = await c.post("/api/auth/login",
                                 json={"email": f"{key}@late.test", "password": PW})
                assert r.status_code == 200, (key, r.status_code, r.text)
                tokens[key] = r.json()["token"]

            url = f"/api/logbooks/project/{PROJ_A}/daily-jobsite/late-arrivals"
            # OUTSIDERS FIRST, while there is no open correction: each of them
            # is asking on a project where the body WOULD write.
            for key in OUTSIDERS:
                before = len(db.logbooks.docs)
                r = await c.post(url, headers={"Authorization": f"Bearer {tokens[key]}"})
                out[key] = (r.status_code, r.text, len(db.logbooks.docs) - before)

            before = len(db.logbooks.docs)
            r = await c.post(url, headers={"Authorization": f"Bearer {tokens['cp_a']}"})
            out["cp_a"] = (r.status_code, r.text, len(db.logbooks.docs) - before)
    return out, db


class AnotherTenantCannotDriveLateArrivals(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out, cls.db = asyncio.run(_scenario())

    def test_the_owning_cp_gets_a_correction_opened(self):
        """THE CONTROL. Without it, every refusal below could pass on a seed
        where the route writes for nobody."""
        status, text, added = self.out["cp_a"]
        self.assertEqual(status, 200, text)
        self.assertIn(LATE_NAME, text)
        self.assertEqual(added, 1, "the correction was not opened for A's own CP")
        child = self.db.logbooks.docs[-1]
        self.assertTrue(child.get("is_amendment"))
        self.assertEqual(child.get("parent_logbook_id"), str(SIGNED_LOG))

    def test_an_outsider_is_refused(self):
        for key in OUTSIDERS:
            with self.subTest(caller=key):
                status, text, _ = self.out[key]
                self.assertIn(status, (403, 404), text)

    def test_an_outsider_writes_nothing(self):
        for key in OUTSIDERS:
            with self.subTest(caller=key):
                self.assertEqual(self.out[key][2], 0, "a logbook was written")
        # Only A's correction exists beyond the seeded log.
        amendments = [d for d in self.db.logbooks.docs if d.get("is_amendment")]
        self.assertEqual(len(amendments), 1)

    def test_an_outsider_is_not_told_who_checked_in(self):
        for key in OUTSIDERS:
            with self.subTest(caller=key):
                self.assertNotIn(LATE_NAME, self.out[key][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
