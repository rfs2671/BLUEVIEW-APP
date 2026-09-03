"""A customer owner cannot see, or purge, another company's project.

THE CHAIN. Two endpoints, one flow, both gated on `get_owner_user` — which is
`role == "owner"`, and role "owner" is what EVERY self-serve signup receives.

  GET  /projects/pending-deletion   listed EVERY company's marked projects
  DELETE /projects/{id}/hard-delete physically purged one, comparing nothing

So any customer owner could read another company's project ids and then
irreversibly purge that project: every document, every storage object, every
config key it owns.

WHY THE DECORATOR DID NOT SAVE IT. hard-delete carries
`Depends(require_platform_operator)`, which looks like a cross-tenant gate and
is not one yet: PLATFORM_GATES_ENFORCED defaults to false, and while it is
false the dependency LOGS the non-operator and RETURNS THEM. The only live
gate was the role check.

That is the trap this file exists to hold shut. Every test below runs with
PLATFORM_GATES_ENFORCED at its default — a fix written on the shadowed
dependency would pass its own tests and protect nothing, so the fix uses
`is_platform_operator`, the pure function, and that is asserted here rather
than assumed.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
# Deliberately NOT set: the whole point is that the guard holds without it.
os.environ.pop("PLATFORM_GATES_ENFORCED", None)

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

A_PROJECT = "6a5f63bc147407d3261df2c7"   # company A
B_PROJECT = "6a5f63bc147407d3261df2c8"   # company B


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict) and "$ne" in v:
            if doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def delete_many(self, query):
        keep = [d for d in self.docs if not _match(d, query)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return type("R", (), {"deleted_count": n})()

    async def delete_one(self, query):
        return await self.delete_many(query)

    async def update_many(self, *a, **k):
        return type("R", (), {"modified_count": 0})()

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))


class _DB:
    def __init__(self):
        self._c = {}
        self.projects = self._mk("projects")

    def _mk(self, n):
        self._c[n] = _Coll()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


def _proj(_id, company, name):
    """A project marked for deletion and cleared past the RETENTION brake.

    `no_completion_attested` is fixture, not decoration. This file is about
    TENANCY — who may purge whose project — and the retention brake
    (lib/project_retention.py) refuses a hard delete on any project with no
    recorded job completion. Without a way past it, the two "CAN still purge"
    tests below would be asserting a 200 they could never get, and the "cannot
    cross companies" tests would pass for the wrong reason entirely: refused by
    retention rather than by the tenancy gate they exist to check.

    The two rules stay separable and both directions are asserted: every
    cross-tenant test below checks for 403 SPECIFICALLY, which retention's 409
    cannot satisfy, and TheRetentionBrakeIsAlsoInThePath at the end of this
    file checks that this fixture flag is still what lets the allowed purges
    through.
    """
    return {"_id": _id, "name": name, "company_id": company,
            "marked_for_deletion": True, "is_deleted": False,
            "marked_at": "2026-08-01", "marked_by": "admin1",
            "no_completion_attested": True,
            "no_completion_reason": "Fixture: never completed, cleared to purge.",
            "no_completion_attested_by": "admin1"}


def _owner(company, **extra):
    """A CUSTOMER owner — role "owner" is every self-serve signup."""
    u = {"_id": f"own_{company}", "id": f"own_{company}", "role": "owner",
         "company_id": company, "email": f"owner@{company}.test",
         "account_status": "approved"}
    u.update(extra)
    return u


def _operator():
    """The platform operator, by the flag rather than by role."""
    return {"_id": "op1", "id": "op1", "role": "owner", "company_id": None,
            "email": "ops@levelog.test", "is_platform_operator": True,
            "account_status": "approved"}


class Base(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs = [
            _proj(A_PROJECT, "coA", "588 Boyland"),
            _proj(B_PROJECT, "coB", "5 Beekman"),
        ]
        self._orig = {"db": server.db, "tqid": server.to_query_id,
                      "r2": server._r2_client}
        server.db = self.db
        server.to_query_id = lambda x: x
        server._r2_client = None

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        server._r2_client = self._orig["r2"]
        self.loop.close()

    def listing(self, user):
        """The route returns {"items": [...], "count": n}."""
        out = self.loop.run_until_complete(
            server.list_pending_deletion_projects(owner=user))
        self.assertEqual(out["count"], len(out["items"]),
                         "count and items must not disagree")
        return out["items"]

    def purge(self, project_id, user):
        return self.loop.run_until_complete(
            server.hard_delete_project(project_id=project_id, owner=user))

    def refused(self, fn, *a):
        with self.assertRaises(HTTPException) as c:
            fn(*a)
        return c.exception


class TheShadowFlagIsOffForEveryTestHere(unittest.TestCase):
    """The premise. If this ever fails, every other assertion in this file is
    measuring a gate that was already closed by the flag."""

    def test_platform_gates_are_NOT_enforced(self):
        self.assertFalse(server.PLATFORM_GATES_ENFORCED)

    def test_and_the_dependency_therefore_lets_a_customer_owner_through(self):
        """Proves the shadow is real, and why the fix cannot be built on it."""
        got = asyncio.new_event_loop().run_until_complete(
            server.require_platform_operator(current_user=_owner("coA")))
        self.assertIsNotNone(got, "shadow mode returns the non-operator")

    def test_the_guards_do_not_use_the_shadowed_dependency(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        for fn in ("async def list_pending_deletion_projects",
                   "async def hard_delete_project"):
            body = src[src.index(fn):]
            body = body[:3000]
            code = "\n".join(l for l in body.splitlines()
                             if not l.strip().startswith("#"))
            with self.subTest(fn=fn):
                self.assertIn("is_platform_operator(owner)", code)


class TheListNoLongerCrossesCompanies(Base):
    def test_a_customer_owner_sees_only_their_own(self):
        got = self.listing(_owner("coA"))
        self.assertEqual([p["name"] for p in got], ["588 Boyland"])

    def test_the_other_companys_project_is_not_named_at_all(self):
        """Not merely filtered from a count — the id and name must not appear
        anywhere in the payload, because the id is the purge key."""
        blob = repr(self.listing(_owner("coA")))
        self.assertNotIn(B_PROJECT, blob)
        self.assertNotIn("5 Beekman", blob)
        self.assertNotIn("coB", blob)

    def test_the_platform_operator_still_sees_both(self):
        got = self.listing(_operator())
        self.assertEqual(sorted(p["name"] for p in got),
                         ["5 Beekman", "588 Boyland"])

    def test_an_owner_with_NO_company_sees_nothing_rather_than_everything(self):
        for empty in (None, "", "   "):
            with self.subTest(company=repr(empty)):
                self.assertEqual(self.listing(_owner(empty)), [])

    def test_an_orphan_project_is_not_claimed_by_a_company_less_owner(self):
        """`company_id: None` as a filter would MATCH a project that has no
        company. Absence is not ownership."""
        self.db.projects.docs.append(
            {"_id": "orphan", "name": "No Company", "marked_for_deletion": True,
             "is_deleted": False, "marked_at": "2026-08-01"})
        self.assertEqual(self.listing(_owner(None)), [])


class TheIrreversiblePurgeCannotCrossCompanies(Base):
    def test_a_customer_owner_cannot_purge_another_companys_project(self):
        e = self.refused(self.purge, B_PROJECT, _owner("coA"))
        self.assertEqual(e.status_code, 403)

    def test_and_the_project_is_still_there_afterwards(self):
        """The DOCUMENT. A 403 that had already deleted things would be no
        better than no 403 at all."""
        before = copy.deepcopy(self.db.projects.docs)
        self.refused(self.purge, B_PROJECT, _owner("coA"))
        self.assertEqual(self.db.projects.docs, before)

    def test_an_owner_with_no_company_cannot_purge_anything(self):
        for empty in (None, ""):
            with self.subTest(company=repr(empty)):
                e = self.refused(self.purge, A_PROJECT, _owner(empty))
                self.assertEqual(e.status_code, 403)
                self.assertEqual(len(self.db.projects.docs), 2)

    def test_an_owner_cannot_purge_an_orphan_project_either(self):
        self.db.projects.docs.append(
            {"_id": "orphan", "name": "No Company", "marked_for_deletion": True,
             "is_deleted": False})
        e = self.refused(self.purge, "orphan", _owner("coA"))
        self.assertEqual(e.status_code, 403)
        self.assertEqual(len(self.db.projects.docs), 3)

    def test_TWO_absences_do_not_authorize_a_purge(self):
        """The case a plain inequality misses: a company-less owner against a
        project with no company. Both normalise to "", so `caller != project`
        is FALSE and the purge proceeds — which is why the guard refuses an
        empty caller company outright rather than only comparing.

        Caught by mutation; every other test here passed without it."""
        self.db.projects.docs.append(
            {"_id": "orphan", "name": "No Company", "marked_for_deletion": True,
             "is_deleted": False})
        for empty in (None, "", "   "):
            with self.subTest(company=repr(empty)):
                e = self.refused(self.purge, "orphan", _owner(empty))
                self.assertEqual(e.status_code, 403)
                self.assertEqual(len(self.db.projects.docs), 3,
                                 "the orphan project was purged")

    def test_the_refusal_names_no_other_tenant(self):
        e = self.refused(self.purge, B_PROJECT, _owner("coA"))
        for leak in ("coB", "5 Beekman"):
            self.assertNotIn(leak, str(e.detail))

    # ── the controls ────────────────────────────────────────────────────
    def test_an_owner_CAN_still_purge_their_own(self):
        self.purge(A_PROJECT, _owner("coA"))
        self.assertEqual([p["_id"] for p in self.db.projects.docs], [B_PROJECT])

    def test_the_platform_operator_can_still_purge_across_companies(self):
        """The carve-out. Narrowing to operator-only was rejected because it
        locks the real operator out until the flag is bootstrapped; narrowing
        to same-company-only would lock them out of the job entirely."""
        self.purge(B_PROJECT, _operator())
        self.assertEqual([p["_id"] for p in self.db.projects.docs], [A_PROJECT])

    def test_a_missing_project_is_still_a_404_not_a_403(self):
        e = self.refused(self.purge, "no_such_project", _owner("coA"))
        self.assertEqual(e.status_code, 404)


class TheOperatorIsNeverInferredFromRole(unittest.TestCase):
    """role "owner" is every self-serve signup. That is the whole reason this
    bug existed, so the fix must not lean on it."""

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_is_platform_operator_reads_the_flag_and_the_allow_list_only(self):
        self.assertTrue(server.is_platform_operator({"is_platform_operator": True}))
        self.assertFalse(server.is_platform_operator({"role": "owner"}))
        self.assertFalse(server.is_platform_operator({"role": "admin"}))
        self.assertFalse(server.is_platform_operator({}))
        self.assertFalse(server.is_platform_operator(None))

    def test_an_empty_email_cannot_match_an_empty_allow_list(self):
        self.assertFalse(server.is_platform_operator({"email": ""}))
        self.assertFalse(server.is_platform_operator({"email": "   "}))

    def test_neither_guard_checks_role_for_the_cross_company_decision(self):
        for fn in ("async def list_pending_deletion_projects",
                   "async def hard_delete_project"):
            body = self.SRC[self.SRC.index(fn):][:3000]
            code = "\n".join(l for l in body.splitlines()
                             if not l.strip().startswith("#"))
            with self.subTest(fn=fn):
                self.assertNotIn('role") == "owner"', code)


class TheRetentionBrakeIsAlsoInThePath(Base):
    """THE FIXTURE CONTROL, and the ordering that keeps this file honest.

    `_proj` carries `no_completion_attested` so the allowed purges can actually
    complete. A fixture flag that quietly stops mattering is how a suite keeps
    passing for a reason nobody chose, so its load-bearing-ness is asserted
    rather than assumed.

    The ORDER also matters and is asserted below: the tenancy gate runs before
    the retention brake, so a cross-tenant caller gets 403 and not 409. If that
    ever inverted, every cross-tenant test in this file would still see "an
    exception" while checking the wrong rule — they all pin 403 specifically,
    and this says why that is the right number."""

    def test_without_the_attestation_an_allowed_purge_is_refused_409(self):
        for p in self.db.projects.docs:
            p.pop("no_completion_attested", None)
        e = self.refused(self.purge, A_PROJECT, _owner("coA"))
        self.assertEqual(e.status_code, 409)
        self.assertIn("no recorded job completion", str(e.detail))

    def test_with_it_the_same_purge_proceeds(self):
        """Without this half, the test above would also pass against a purge
        that refused everything."""
        self.purge(A_PROJECT, _owner("coA"))
        self.assertEqual([p["_id"] for p in self.db.projects.docs], [B_PROJECT])

    def test_tenancy_is_decided_before_retention(self):
        """A cross-tenant caller is told 403 — "not yours" — even against a
        project that retention would also have refused. Answering 409 there
        would leak that the other company's project exists and is unpurgeable,
        and would send the caller off to satisfy a rule that is not the one
        stopping them."""
        for p in self.db.projects.docs:
            p.pop("no_completion_attested", None)
        e = self.refused(self.purge, B_PROJECT, _owner("coA"))
        self.assertEqual(e.status_code, 403)


if __name__ == "__main__":
    unittest.main()
