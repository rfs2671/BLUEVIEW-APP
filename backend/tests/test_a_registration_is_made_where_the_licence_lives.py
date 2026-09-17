"""A superintendent's CS registrations are set from his own user record.

── WHAT MOVED, AND WHAT DID NOT ────────────────────────────────────────────

MOVED: the DATA ENTRY. The old admin tab asked for the man's NAME and his DOB
LICENCE NUMBER again for every project he is on — the same two facts retyped per
jobsite with nothing reconciling the copies. They are facts about a PERSON, they
live on his user document, and `PUT /admin/users/{id}/cs-registrations` now
writes the rows from them. The request body carries PROJECT IDS AND NOTHING
ELSE; a licence arriving off the wire would be the old screen with a new URL.

DID NOT MOVE: the row, and what it decides. `cs_registrations` is still the
FILING GATE for BC 3301.13.13 — lib/logbook/superintendent_log.py explains at
length why that gate keys on the registration and never on `role` — and the
one-job rule and its compliance alert are the SAME CODE, extracted into
`_register_cs_on_project` and called by both routes rather than written twice.

── THE THREE WAYS THIS COULD DESTROY A STATUTORY RECORD ────────────────────

Each has a section below, because each is silent:

  A HARD DELETE. The row is the provenance of every log filed under it —
  `attribute_signer` reads `created_at`, `deactivated_at` and `deleted_at` to
  decide what a document signed months ago can say about who signed it. Removing
  it does not un-register him going forward; it makes a FILED record unable to
  account for itself.

  A SAVE THAT DE-SELECTS WHAT THE SCREEN NEVER SHOWED. The multi-select offers
  his ASSIGNED projects. A registration on a project he is not assigned to
  cannot appear there, so a de-selection pass over every row would delete
  something the admin was never shown. That is Michael Cespedes's row on 588
  Thomas the day anybody unassigns him from it.

  A NO-OP SAVE THAT RE-REGISTERS. Re-running the registration for a project he
  is already on supersedes his own row with an identical one and moves
  `created_at` forward. `attribute_signer` returns REGISTERED_LATER for a
  registration that postdates the log — so pressing Save and changing nothing
  would make every log he has already filed stop being attributable to him.
"""

import ast
import asyncio
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

COMPANY = "company-a"
MICHAEL = "6a68b16ebe9c27dedf5cf47f"
THOMAS = "6a5f63bc147407d3261df2c7"   # 588 Thomas
OTHER = "project-other"
UNASSIGNED = "project-he-is-not-on"


# ── stand-in database ───────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return list(self.rows)[:n]

    def __aiter__(self):
        async def gen():
            for r in self.rows:
                yield r
        return gen()


def _match(row, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        actual = row.get("_id") if k == "_id" else row.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$in" in v and actual not in v["$in"]:
                return False
            if "$ne" not in v and "$in" not in v:
                return False
        elif actual != v:
            return False
    return True


class _Coll:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.inserted = []
        self.hard_deletes = 0

    def find(self, q=None, projection=None):
        return _Cursor([r for r in self.rows if _match(r, q or {})])

    async def find_one(self, q=None, projection=None):
        for r in self.rows:
            if _match(r, q or {}):
                return r
        return None

    async def insert_one(self, doc):
        d = dict(doc)
        d.setdefault("_id", f"new-{len(self.inserted)}")
        self.inserted.append(d)
        self.rows.append(d)
        return type("R", (), {"inserted_id": d["_id"]})()

    async def update_one(self, q, u):
        for r in self.rows:
            if _match(r, q):
                r.update(u.get("$set") or {})
                return type("R", (), {"matched_count": 1, "modified_count": 1})()
        return type("R", (), {"matched_count": 0, "modified_count": 0})()

    async def update_many(self, q, u):
        n = 0
        for r in self.rows:
            if _match(r, q):
                r.update(u.get("$set") or {})
                n += 1
        return type("R", (), {"matched_count": n, "modified_count": n})()

    async def delete_one(self, q):
        self.hard_deletes += 1
        return type("R", (), {"deleted_count": 1})()

    async def delete_many(self, q):
        self.hard_deletes += 1
        return type("R", (), {"deleted_count": 1})()


class _DB:
    def __init__(self, users, projects, regs):
        self.users = _Coll(users)
        self.projects = _Coll(projects)
        self.cs_registrations = _Coll(regs)
        self.compliance_alerts = _Coll([])
        self.audit_logs = _Coll([])


ADMIN = {"id": "u-admin", "_id": "u-admin", "role": "admin",
         "company_id": COMPANY}


def _michael(role="superintendent", assigned=(THOMAS, OTHER), licence="CS-0001"):
    return {
        "_id": MICHAEL, "id": MICHAEL, "name": "Michael Cespedes",
        "email": "michaelcespedes99@gmail.com", "role": role,
        "company_id": COMPANY, "assigned_projects": list(assigned),
        "dob_superintendent_number": licence, "is_deleted": False,
    }


def _his_row_on_thomas():
    """As it stands in production: bound by ACCOUNT ID, active, created 2026."""
    return {
        "_id": "reg-thomas", "project_id": THOMAS, "user_id": MICHAEL,
        "full_name": "Michael Cespedes", "license_number": "CS-0001",
        "license_number_normalized": "CS-0001", "is_active": True,
        "is_deleted": False, "company_id": COMPANY,
        "created_at": "2026-01-01",
    }


def _db(user=None, regs=None, projects=None):
    return _DB(
        users=[user or _michael()],
        projects=projects or [
            {"_id": THOMAS, "name": "588 Thomas", "company_id": COMPANY,
             "is_deleted": False},
            {"_id": OTHER, "name": "Other Job", "company_id": COMPANY,
             "is_deleted": False},
            {"_id": UNASSIGNED, "name": "Not His", "company_id": COMPANY,
             "is_deleted": False},
        ],
        regs=regs if regs is not None else [_his_row_on_thomas()],
    )


async def _noop_audit(*a, **k):
    return None


def _put(db, project_ids, admin=None):
    async def go():
        with patch.object(server, "db", db), \
             patch.object(server, "audit_log", _noop_audit), \
             patch.object(server, "to_query_id", lambda v: v):
            return await server.set_user_cs_registrations(
                MICHAEL,
                server.UserCSRegistrationsSet(project_ids=project_ids),
                admin or ADMIN,
            )
    return asyncio.run(go())


def _get(db, admin=None):
    async def go():
        with patch.object(server, "db", db), \
             patch.object(server, "to_query_id", lambda v: v):
            return await server.get_user_cs_registrations(MICHAEL, admin or ADMIN)
    return asyncio.run(go())


# ── THE ONE-JOB RULE IS REUSED, NOT REWRITTEN ───────────────────────────────

class OneRuleAndOneAlert(unittest.TestCase):
    def test_both_routes_call_the_same_writer(self):
        for fn in (server.register_construction_superintendent,
                   server.set_user_cs_registrations):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            self.assertIn("_register_cs_on_project", code, fn.__name__)

    def test_there_is_exactly_one_writer_of_the_conflict_alert(self):
        """A second implementation of the one-job rule is the thing the ruling
        forbids, and it would be invisible: both would pass their own tests."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('"alert_type": "cs_one_job_conflict"'), 1)

    def test_neither_route_reimplements_the_conflict_query(self):
        """CODE, NOT PROSE. `ast.unparse` keeps docstrings, and both handlers
        EXPLAIN the conflict query at length — the first version of this
        assertion matched its own explanation. `strip_python` removes
        docstrings and comments, which is the whole reason tests/source_text.py
        exists."""
        from tests.source_text import strip_python
        for fn in (server.register_construction_superintendent,
                   server.set_user_cs_registrations):
            code = strip_python(inspect.getsource(fn))
            # ANCHORED ON THE DICT KEY. A bare identifier bans the word, and
            # the word appears in prose about the rule; `"...":` bans the
            # query, which is the construct that must live in one place.
            self.assertNotIn('"license_number_normalized":', code, fn.__name__)

    def test_the_rule_still_warns_rather_than_refusing(self):
        """NYC DOB limits a CS to one active job. The system makes the breach
        visible to the office; it does not block a registration an admin may be
        making because the other job has finished."""
        db = _db(regs=[
            _his_row_on_thomas(),
            {"_id": "reg-someone-else", "project_id": OTHER,
             "user_id": "somebody", "license_number_normalized": "CS-0001",
             "is_active": True, "is_deleted": False},
        ])
        out = _put(db, [THOMAS, OTHER])
        self.assertTrue(out["conflict_warnings"])
        self.assertIn("one-job rule", out["conflict_warnings"][0])
        # AND IT STILL WROTE THE ROW.
        self.assertEqual([a["project_id"] for a in out["added"]], [OTHER])


# ── THE LICENCE IS READ, NEVER SENT ─────────────────────────────────────────

class TheLicenceComesOffTheRecord(unittest.TestCase):
    def test_the_body_carries_project_ids_and_nothing_else(self):
        fields = set(server.UserCSRegistrationsSet.model_fields)
        self.assertEqual(fields, {"project_ids"})

    def test_the_row_is_written_with_the_users_own_number(self):
        db = _db(regs=[])
        _put(db, [THOMAS])
        row = db.cs_registrations.inserted[0]
        self.assertEqual(row["license_number"], "CS-0001")
        self.assertEqual(row["full_name"], "Michael Cespedes")
        self.assertEqual(row["user_id"], MICHAEL)

    def test_it_refuses_when_he_has_no_licence_number(self):
        """`license_number_normalized` is what the one-job conflict query joins
        on. A registration with no number is invisible to the check that exists
        to catch double-jobbing."""
        db = _db(user=_michael(licence=""), regs=[])
        with self.assertRaises(HTTPException) as ctx:
            _put(db, [THOMAS])
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.cs_registrations.inserted, [])

    def test_it_refuses_a_user_who_is_not_a_superintendent(self):
        db = _db(user=_michael(role="cp"), regs=[])
        with self.assertRaises(HTTPException) as ctx:
            _put(db, [THOMAS])
        self.assertEqual(ctx.exception.status_code, 422)

    def test_it_refuses_another_companys_user(self):
        """`get_user_admin` proved a RANK, not a company — the same split that
        was a SEV-0 on update_admin_user."""
        db = _db(regs=[])
        foreign = {**ADMIN, "company_id": "company-b"}
        with self.assertRaises(HTTPException) as ctx:
            _put(db, [THOMAS], admin=foreign)
        self.assertEqual(ctx.exception.status_code, 403)


# ── HIS COMPANY'S PROJECTS, AND THE TENANT CHECK THAT USED TO BE IMPLIED ────

class ThePickerOffersTheCompanysProjects(unittest.TestCase):
    """THIS CLASS WAS `OnlyProjectsHeIsAssignedTo` AND THE RULING WITHDREW IT.

    Registration now does both: registering him on a project writes the row AND
    assigns it, so `assigned_projects` is an OUTPUT of this screen rather than
    the gate on its input. Left as it was, the picker would offer exactly the
    set already ticked — and a superintendent created this morning, with no
    assignments and no Assign button on his card, could never be registered on
    anything at all.

    THE HALF THAT MUST SURVIVE IS THE TENANT CHECK, AND IT WAS INVISIBLE.
    `foreign = wanted - assigned` was doing two jobs: enforcing the withdrawn
    rule, and INHERITING the company check, because everything in
    `assigned_projects` had already been through `validate_assignable_projects`
    on the way in. Dropping the first without restating the second would have
    made this endpoint a way to mint cross-tenant access — the add writes the
    id straight into `assigned_projects`, which `require_project_access`
    honours. So it is asked here now, by name, and asserted here too.
    """

    def test_a_project_in_another_company_is_refused(self):
        db = _db(regs=[], projects=[
            {"_id": THOMAS, "name": "588 Thomas", "company_id": COMPANY,
             "is_deleted": False},
            {"_id": UNASSIGNED, "name": "Another Tenant's Job",
             "company_id": "company-b", "is_deleted": False},
        ])
        with self.assertRaises(HTTPException) as ctx:
            _put(db, [UNASSIGNED])
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(db.cs_registrations.inserted, [])

    def test_and_an_unknown_project_id_is_refused_the_same_way(self):
        """One message for foreign AND unknown: distinguishing them would
        confirm the existence of another tenant's project id."""
        db = _db(regs=[])
        with self.assertRaises(HTTPException) as ctx:
            _put(db, ["no-such-project"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_the_picker_offers_every_project_in_his_company(self):
        """Including the one he is NOT assigned to — which is the whole point:
        that is how he gets assigned to it."""
        out = _get(_db())
        self.assertEqual({p["project_id"] for p in out["selectable"]},
                         {THOMAS, OTHER, UNASSIGNED})

    def test_he_can_be_registered_on_a_project_he_was_never_assigned_to(self):
        db = _db(user=_michael(assigned=()), regs=[])
        out = _put(db, [THOMAS])
        self.assertEqual([a["project_id"] for a in out["added"]], [THOMAS])

    def test_and_that_registration_is_what_assigns_it(self):
        """THE INVARIANT. His assigned projects ARE his active registrations —
        one act, both writes, so a project cannot appear on one side only."""
        db = _db(user=_michael(assigned=()), regs=[])
        _put(db, [THOMAS])
        him = next(u for u in db.users.rows if u["_id"] == MICHAEL)
        self.assertEqual(him["assigned_projects"], [THOMAS])

    def test_unregistering_removes_the_assignment_too(self):
        """The direction that matters for access. An assignment left behind is
        a live authorization grant: `require_project_access` honours
        `assigned_projects`, so he would go on reaching a job he is no longer
        the registered CS on."""
        db = _db()
        _put(db, [])
        him = next(u for u in db.users.rows if u["_id"] == MICHAEL)
        self.assertEqual(him["assigned_projects"], [])

    def test_the_picker_is_seeded_from_the_ROWS_not_from_the_assignments(self):
        """THE SEED DECIDES WHAT A SAVE DELETES. He is assigned to two projects
        and registered on one; if the client seeded from assignments, the first
        save would silently register him on the second.

        STILL TRUE, AND NOW LOAD-BEARING IN A SECOND WAY: under the invariant
        the two sets agree, so a seed taken from the wrong one would be right
        almost always — and wrong exactly on the account somebody had edited by
        hand."""
        out = _get(_db())
        self.assertEqual(out["registered_project_ids"], [THOMAS])


# ── THE THREE WAYS IT COULD DESTROY A RECORD ────────────────────────────────

class ARemovedRegistrationIsSoftDeleted(unittest.TestCase):
    def test_unticking_a_project_retires_the_row(self):
        db = _db()
        out = _put(db, [])
        self.assertEqual(out["removed"], [THOMAS])
        row = db.cs_registrations.rows[0]
        self.assertTrue(row["is_deleted"])
        self.assertFalse(row["is_active"])
        self.assertIn("deactivated_at", row)

    def test_the_row_is_still_there(self):
        """SOFT, NEVER HARD. It is the provenance of every log filed under it."""
        db = _db()
        _put(db, [])
        self.assertEqual(len(db.cs_registrations.rows), 1)
        self.assertEqual(db.cs_registrations.hard_deletes, 0)

    def test_the_endpoint_contains_no_hard_delete_at_all(self):
        """The stand-in above counts hard deletes, which catches the call this
        endpoint makes today. This catches the one a future edit adds down a
        branch no test drives. Comments stripped, for the reason above."""
        from tests.source_text import strip_python
        code = strip_python(inspect.getsource(server.set_user_cs_registrations))
        self.assertNotIn("delete_one(", code)
        self.assertNotIn("delete_many(", code)


class ItNeverTouchesWhatTheScreenCannotShow(unittest.TestCase):
    """A live row the picker cannot draw. A de-selection pass over EVERY row
    would retire something the admin was never shown.

    ── THE SET IS NEW; THE RULE IS NOT ─────────────────────────────────────

    This used to be "registered on 588, no longer assigned to it" — invisible
    because the picker showed his assignments. Under the ruling his assignments
    ARE his registrations, so that shape cannot occur and, more importantly,
    scoping the delete to a list this endpoint itself writes would make its own
    previous output the boundary of its next write. That is not a boundary.

    The set that survives is "outside what the picker offers", which is now the
    company's projects: a registration on another tenant's job, or on one that
    has been deleted. Michael holds none today — the invariant is intact in
    production — which is exactly why `registered_elsewhere` is worth keeping.
    It is empty forever, so a non-empty one is the divergence reporting itself.
    """

    def setUp(self):
        # Registered on 588 Thomas, which now belongs to another company — the
        # shape a project transfer or a mis-set company_id would produce.
        self.db = _db(
            user=_michael(assigned=(OTHER,)),
            projects=[
                {"_id": THOMAS, "name": "588 Thomas", "company_id": "company-b",
                 "is_deleted": False},
                {"_id": OTHER, "name": "Other Job", "company_id": COMPANY,
                 "is_deleted": False},
            ],
        )

    def test_a_save_that_omits_it_leaves_it_alone(self):
        out = _put(self.db, [OTHER])
        self.assertEqual(out["removed"], [])
        row = next(r for r in self.db.cs_registrations.rows
                   if r["project_id"] == THOMAS)
        self.assertTrue(row["is_active"])
        self.assertFalse(row.get("is_deleted"))

    def test_an_empty_save_leaves_it_alone_too(self):
        _put(self.db, [])
        row = next(r for r in self.db.cs_registrations.rows
                   if r["project_id"] == THOMAS)
        self.assertTrue(row["is_active"])

    def test_the_read_route_names_it_rather_than_hiding_it(self):
        """A list that silently omits a live registration reads as the whole
        truth."""
        out = _get(self.db)
        self.assertEqual([r["project_id"] for r in out["registered_elsewhere"]],
                         [THOMAS])


class ANoOpSaveDoesNotReRegister(unittest.TestCase):
    """`attribute_signer` returns REGISTERED_LATER for a registration that
    postdates the log. Superseding his own row with an identical one moves
    `created_at` forward, so pressing Save and changing nothing would make every
    log he has already filed stop being attributable to him."""

    def test_saving_the_same_selection_writes_nothing(self):
        db = _db()
        out = _put(db, [THOMAS])
        self.assertEqual(out["added"], [])
        self.assertEqual(out["removed"], [])
        self.assertEqual(db.cs_registrations.inserted, [])

    def test_his_original_row_is_untouched(self):
        db = _db()
        before = dict(db.cs_registrations.rows[0])
        _put(db, [THOMAS])
        self.assertEqual(db.cs_registrations.rows[0], before)

    def test_adding_a_SECOND_project_does_not_disturb_the_first(self):
        db = _db()
        before = dict(db.cs_registrations.rows[0])
        out = _put(db, [THOMAS, OTHER])
        self.assertEqual([a["project_id"] for a in out["added"]], [OTHER])
        self.assertEqual(db.cs_registrations.rows[0], before)


class MichaelStillGoverns588(unittest.TestCase):
    """The operator's condition on the whole change: his row must still be
    there and still govern. Driven through the real attribution predicate, not
    asserted about the document."""

    def test_the_filing_gate_still_matches_him_after_a_save(self):
        from lib.logbook.cs_attribution import (
            attribute_signer, cs_filing_refused, MATCHED_ACCOUNT,
        )
        db = _db()
        _put(db, [THOMAS])          # the admin opens the screen and saves
        row = next(r for r in db.cs_registrations.rows
                   if r["project_id"] == THOMAS and r["is_active"])
        signer = _michael()
        result = attribute_signer(signer, row, "2026-09-16")
        self.assertEqual(result["state"], MATCHED_ACCOUNT)
        self.assertFalse(cs_filing_refused(result))


if __name__ == "__main__":
    unittest.main()
