"""The two cost-bearing logbook writes carry the activation gate — and doing
that does not stop a CP filing his day.

WHY THEY NEEDED IT. require_approved is cost control: "blocked from every
cost-bearing endpoint (AI, uploads, live external APIs)". POST /logbooks and
PUT /logbooks/{id} both fire _enhance_logbook_photos, which is AI image work on
the platform's bill, and they were the only two spending endpoints in the
codebase without the gate. The inconsistency was visible inside one family:
PUT /logbooks/project/{id}/scaffold-info has carried it all along.

WHY IT REFUSES NOBODY WHO CAN FILE TODAY, which is the thing that had to be
established before adding it. A pending account is, by construction, a
self-registered `owner` with company_id = None:

  * /auth/register is the ONLY writer of "pending", and it forces role="owner"
    and company_id=None on the same path;
  * a CP can only be created by POST /admin/users;
  * account_status is not in ALLOWED_USER_FIELDS, so no admin can set an
    existing CP pending;
  * the only exit from pending is PATCH /admin/users/{id}/approve.

A CP is therefore never pending. Each of those four is asserted below, because
the safety of the gate rests on all four and any one of them could be edited
away without anyone connecting it to a CP being locked out.

AND THE WINDOW THAT WAS LEFT. POST /admin/users wrote no account_status at
all, so an admin-created CP had none until the next restart backfilled it.
They passed only because ALLOW_LEGACY_NULL_STATUS admits a null — a flag
documented as temporary. Now that a gate sits on a CP's daily work, that flag
turning off would stop him filing. The field is stamped at creation instead.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def _fn_body(name: str) -> str:
    """A whole handler, to its next route decorator. A fixed-length slice is
    not enough: create_logbook runs to ~250 lines and the enhancement call
    sits near the end of it."""
    start = SRC.index(f"async def {name}(")
    nxt = SRC.find(chr(10) + "@api_router.", start)
    return SRC[start:nxt if nxt != -1 else len(SRC)]


def _route_line(method: str, path: str) -> str:
    needle = f'@api_router.{method}("{path}"'
    i = SRC.index(needle)
    return SRC[i:SRC.index("\n", i)]


class TheGateIsOnBothSpendingEndpoints(unittest.TestCase):
    def test_create_carries_require_approved(self):
        self.assertIn("Depends(require_approved)", _route_line("post", "/logbooks"))

    def test_update_carries_require_approved(self):
        self.assertIn("Depends(require_approved)",
                      _route_line("put", "/logbooks/{logbook_id}"))

    def test_they_are_the_ones_that_actually_SPEND(self):
        """The justification, not a restatement of the decorator: the gate is
        cost control, so it belongs where the money goes."""
        for fn in ("create_logbook", "update_logbook"):
            with self.subTest(fn=fn):
                self.assertIn("_enhance_logbook_photos", _fn_body(fn))

    def test_the_three_NON_spending_writes_are_left_alone(self):
        """finalize, amend and delete fire no enhancement. Gating them would
        be a scope decision about what require_approved means, which is the
        operator's, and this PR does not make it."""
        for fn in ("finalize_logbook", "amend_logbook", "delete_logbook"):
            with self.subTest(fn=fn):
                self.assertNotIn("_enhance_logbook_photos", _fn_body(fn))
        for method, path in (("post", "/logbooks/{logbook_id}/finalize"),
                             ("post", "/logbooks/{logbook_id}/amend"),
                             ("delete", "/logbooks/{logbook_id}")):
            with self.subTest(route=path):
                self.assertNotIn("require_approved", _route_line(method, path))


class APendingAccountIsAlwaysCompanyLess(unittest.TestCase):
    """The four facts the gate's safety rests on. Each is load-bearing: edit
    any one away and a CP could become pending, at which point the gate above
    stops a man on site from filing."""

    def test_register_is_the_only_writer_of_pending(self):
        writes = [l.strip() for l in SRC.splitlines()
                  if 'account_status"] = "pending"' in l
                  or "account_status': 'pending'" in l]
        self.assertEqual(len(writes), 1, writes)
        reg = SRC[SRC.index("async def register("):]
        reg = reg[:reg.index("result = await db.users.insert_one(user_dict)")]
        self.assertIn('user_dict["account_status"] = "pending"', reg)

    def test_and_that_same_path_forces_owner_with_no_company(self):
        reg = SRC[SRC.index("async def register("):]
        reg = reg[:reg.index("result = await db.users.insert_one(user_dict)")]
        self.assertIn('user_dict["role"] = "owner"', reg)
        self.assertIn('user_dict["company_id"] = None', reg)

    def test_an_admin_cannot_set_an_existing_user_pending(self):
        """account_status is not writable through the user-update allow-list,
        so an approved CP cannot be pushed back to pending mid-shift."""
        i = SRC.index("ALLOWED_USER_FIELDS = {")
        allow = SRC[i:SRC.index("}", i)]
        self.assertNotIn("account_status", allow)

    def test_the_only_exit_from_pending_is_the_approve_route(self):
        self.assertIn('"account_status": "approved",', SRC)
        approve = SRC[SRC.index("/admin/users/{user_id}/approve"):][:1500]
        self.assertIn('"account_status": "approved"', approve)


class TheGateRefusesTheRightPerson(unittest.TestCase):
    """require_approved executed, rather than its decorator read."""

    def _check(self, user):
        import asyncio
        return asyncio.new_event_loop().run_until_complete(
            server.require_approved(current_user=user))

    def test_a_pending_account_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            self._check({"_id": "u1", "role": "owner", "account_status": "pending"})
        self.assertEqual(c.exception.status_code, 403)
        self.assertEqual(c.exception.detail, {"error": "account_pending"})

    def test_an_approved_cp_passes(self):
        got = self._check({"_id": "u1", "role": "cp", "company_id": "coA",
                           "account_status": "approved"})
        self.assertIsNotNone(got)

    def test_an_unknown_status_fails_CLOSED(self):
        for status in ("suspended", "revoked", "aproved", ""):
            with self.subTest(status=status):
                with self.assertRaises(HTTPException):
                    self._check({"_id": "u1", "account_status": status})

    def test_a_site_device_bypasses_it_entirely(self):
        """The gate sits in front of check-in and must never break it."""
        got = self._check({"_id": "d1", "role": "site_device", "site_mode": True})
        self.assertIsNotNone(got)


class TheNullStatusWindowIsClosed(unittest.TestCase):
    """The hazard this PR had to remove before it could add the gate."""

    def test_an_admin_created_user_is_stamped_at_creation(self):
        create = SRC[SRC.index("async def create_user_by_admin(")
                     if "async def create_user_by_admin(" in SRC
                     else SRC.index('@api_router.post("/admin/users"'):]
        create = create[:create.index("result = await db.users.insert_one(user_dict)")]
        self.assertIn('user_dict["account_status"] = "approved"', create,
                      "an admin-created CP would have no status until a restart")

    def test_the_stamp_matches_what_the_startup_backfill_already_does(self):
        """So this is deterministic, not a policy change: the migration
        resolves every field-less user to approved at every boot anyway."""
        mig = SRC[SRC.index("async def run_account_status_startup_migration"):][:900]
        self.assertIn('{"account_status": {"$exists": False}}', mig)
        self.assertIn('{"$set": {"account_status": "approved"}}', mig)

    def test_the_gate_no_longer_depends_on_the_temporary_grace_flag(self):
        """The point of the stamp. With the field present, a CP passes on the
        field itself — flipping ALLOW_LEGACY_NULL_STATUS cannot lock him out
        of filing. Executed with the grace OFF, which is the future state its
        own removal procedure describes."""
        import asyncio
        original = server.ALLOW_LEGACY_NULL_STATUS
        server.ALLOW_LEGACY_NULL_STATUS = False
        try:
            loop = asyncio.new_event_loop()
            stamped = {"_id": "cp1", "role": "cp", "company_id": "coA",
                       "account_status": "approved"}
            self.assertIsNotNone(
                loop.run_until_complete(server.require_approved(current_user=stamped)),
                "a stamped CP must pass with the grace flag off")
            with self.assertRaises(HTTPException):
                loop.run_until_complete(
                    server.require_approved(current_user={"_id": "cp2", "role": "cp"}))
            loop.close()
        finally:
            server.ALLOW_LEGACY_NULL_STATUS = original

    def test_the_grace_flag_is_still_on_today_so_nothing_breaks_on_deploy(self):
        self.assertTrue(server.ALLOW_LEGACY_NULL_STATUS,
                        "if this is off, every field-less legacy CP is already locked out")


if __name__ == "__main__":
    unittest.main()
