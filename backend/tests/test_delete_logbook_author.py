"""THE AUTHOR OF A LOGBOOK COULD NOT DELETE IT — the one case the rule exists for.

delete_logbook's docstring says "only by admins or the user who created it".
The second half never worked:

    user_id = str(current_user.get("_id", ""))
    if user_role not in ("admin", "owner") and logbook.get("created_by") != user_id:
        raise HTTPException(status_code=403, ...)

`current_user` is whatever `get_current_user` returns, and that is
`serialize_id(user)` — which does `obj['id'] = str(obj['_id']); del obj['_id']`.
**There is no `_id` on `current_user`.** So `user_id` was the empty string on
every request, `logbook.get("created_by") != ""` was true for every logbook,
and every non-admin was refused — the author included.

The writer says so plainly. create_logbook stores

    "created_by": current_user.get("id"),

and the reader compared it against a key that had been deleted two frames
earlier. A reader naming a field no writer produces: the failure is total and
silent, and it presents as "delete is admin-only", which is a plausible enough
product rule that nobody questioned it.

THE AUDIT TRAIL WAS WRONG TOO, and would have stayed wrong even if the gate
had been bypassed by an admin: `audit_log(..., user_id, ...)` recorded that
same empty string as the actor, so every admin deletion in the ledger names
nobody.

WHAT THE FIX IS. Not a new accessor — the file already has one idiom for this,
used at ~17 authorization sites (9489, 15459, 30884, 14437, 36822, ...):

    str(current_user.get("id") or current_user.get("_id") or "")

`id` first because that is the key that actually exists; `_id` retained
because a caller that hands the handler a raw Mongo document (tests, internal
call sites) still resolves. `annotation` delete/resolve — the same
creator-may-delete shape, at 31897/31934 — reads the id exactly this way and
has always worked, which is the control this test is written against.

WHAT WOULD MAKE THIS FILE WRONG: `serialize_id` keeping `_id`, or
`create_logbook` storing something other than `current_user.get("id")` in
`created_by`. Both are asserted below, so the test fails at the cause rather
than at the symptom.

NOT A REGRESSION IN DISGUISE — the refusals are asserted just as hard as the
permission. A non-author CP on the same project, who was refused for the wrong
reason before, must still be refused for the right one.

    python backend/tests/test_delete_logbook_author.py
"""

import asyncio
import inspect
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

PROJ_A = {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"}

# ── The callers, in the SHAPE get_current_user actually hands the handler ────
# `id`, and NO `_id`. This is the whole point of the file: a fixture carrying
# both keys — which is what most of the suite uses — passes against the broken
# code and proves nothing.
AUTHOR_CP = {"id": "u-author", "role": "cp", "company_id": "companyA",
             "account_status": "approved", "name": "Author CP",
             "assigned_projects": ["projA"]}
OTHER_CP = {"id": "u-other", "role": "cp", "company_id": "companyA",
            "account_status": "approved", "name": "Colleague CP",
            "assigned_projects": ["projA"]}
ADMIN_A = {"id": "u-admin", "role": "admin", "company_id": "companyA",
           "account_status": "approved", "name": "Admin A",
           "assigned_projects": []}

LOGBOOK = {
    "_id": "lb1", "id": "lb1",
    "project_id": "projA",
    "company_id": "companyA",
    "log_type": "daily_jobsite",
    "date": "2026-09-01",
    "created_by": "u-author",
    "is_deleted": False,
}

# What the NFC gate writes: nobody authenticated authored it.
GATE_ORIENTATION = dict(LOGBOOK, log_type="subcontractor_orientation",
                        created_by=None)


def _db(logbook, project=PROJ_A):
    state = {"updates": [], "audits": []}

    async def lb_find_one(q, *a, **kw):
        return dict(logbook) if logbook else None

    async def lb_update_one(q, upd, *a, **kw):
        state["updates"].append(upd)
        r = MagicMock()
        r.matched_count = 1
        return r

    async def proj_find_one(q, *a, **kw):
        return dict(project) if project else None

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(side_effect=lb_find_one)
    db.logbooks.update_one = AsyncMock(side_effect=lb_update_one)
    db.projects.find_one = AsyncMock(side_effect=proj_find_one)
    return db, state


def _delete(user, logbook=LOGBOOK, project=PROJ_A):
    """Call the real handler. Returns (result, state)."""
    db, state = _db(logbook, project)

    async def fake_audit(action, actor, entity, entity_id, meta=None):
        state["audits"].append({"action": action, "actor": actor,
                                "entity": entity, "entity_id": entity_id})

    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock(side_effect=fake_audit)):
        result = asyncio.run(server.delete_logbook(
            logbook_id="lb1", current_user=user))
    return result, state


# ── The premise, asserted so a failure lands on the cause ───────────────────

class ThePremise(unittest.TestCase):
    def test_serialize_id_DELETES_underscore_id(self):
        """If this ever stops being true the whole defect evaporates — and so
        should this file."""
        out = server.serialize_id({"_id": "abc", "role": "cp"})
        self.assertEqual(out.get("id"), "abc")
        self.assertNotIn("_id", out)

    def test_get_current_user_returns_serialize_id_output(self):
        src = inspect.getsource(server.get_current_user)
        self.assertIn("serialize_id(user)", src)

    def test_create_logbook_stamps_created_by_from_dot_id(self):
        """The writer half of the pair. `created_by` is `.get("id")`, so the
        reader must resolve to the same string."""
        src = inspect.getsource(server.create_logbook)
        self.assertIn('"created_by": current_user.get("id")', src)


# ── The permission that never worked ────────────────────────────────────────

class TheAuthorMayDeleteHisOwnLogbook(unittest.TestCase):
    """THE BUG. Pre-fix this raises 403 — the exact case the rule permits."""

    def test_the_author_is_allowed(self):
        result, state = _delete(AUTHOR_CP)
        self.assertEqual(result, {"message": "Logbook deleted"})

    def test_and_the_row_is_actually_soft_deleted(self):
        _, state = _delete(AUTHOR_CP)
        self.assertEqual(len(state["updates"]), 1)
        self.assertIs(state["updates"][0]["$set"]["is_deleted"], True)

    def test_the_audit_names_the_actor_and_not_the_empty_string(self):
        """The same broken read fed the ledger. An audit row whose actor is ''
        is worse than no row: it looks like a record."""
        _, state = _delete(AUTHOR_CP)
        self.assertEqual(len(state["audits"]), 1)
        self.assertEqual(state["audits"][0]["actor"], "u-author")


class AndNobodyElseMay(unittest.TestCase):
    """The refusals. These passed before the fix FOR THE WRONG REASON — every
    non-admin was refused — so they are the half that proves the fix did not
    open anything."""

    def test_a_project_colleague_who_did_not_write_it_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _delete(OTHER_CP)
        self.assertEqual(c.exception.status_code, 403)

    def test_nothing_is_written_when_a_colleague_is_refused(self):
        try:
            _, state = _delete(OTHER_CP)
        except HTTPException:
            return
        self.fail(f"the delete went through: {state}")

    def test_an_admin_of_the_project_company_may_delete_any(self):
        result, state = _delete(ADMIN_A)
        self.assertEqual(result, {"message": "Logbook deleted"})
        self.assertEqual(state["audits"][0]["actor"], "u-admin")

    def test_a_gate_written_orientation_has_no_author_so_no_CP_may_delete_it(self):
        """`created_by: None`. There is no author, so the author branch must
        match NOBODY — in particular it must not start matching a caller whose
        id resolved to '' under some future accessor."""
        with self.assertRaises(HTTPException) as c:
            _delete(AUTHOR_CP, logbook=GATE_ORIENTATION)
        self.assertEqual(c.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            _delete(OTHER_CP, logbook=GATE_ORIENTATION)

    def test_but_an_admin_still_can(self):
        result, _ = _delete(ADMIN_A, logbook=GATE_ORIENTATION)
        self.assertEqual(result, {"message": "Logbook deleted"})

    def test_the_tenant_gate_still_runs_first(self):
        """`_authorize_logbook_write` is unchanged and still decides WHICH
        project. An author whose assignment was revoked is out before the
        created_by rule is ever consulted."""
        unassigned = dict(AUTHOR_CP, assigned_projects=[])
        with self.assertRaises(HTTPException) as c:
            _delete(unassigned)
        self.assertEqual(c.exception.status_code, 403)
        self.assertIn("Not authorized for this logbook", str(c.exception.detail))


class TheAccessorIsTheFileSAndNotANewOne(unittest.TestCase):
    def test_delete_logbook_no_longer_reads_underscore_id_alone(self):
        src = inspect.getsource(server.delete_logbook)
        self.assertNotIn('current_user.get("_id", "")', src)

    def test_it_uses_the_established_idiom(self):
        src = inspect.getsource(server.delete_logbook)
        self.assertIn(
            'str(current_user.get("id") or current_user.get("_id") or "")', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
