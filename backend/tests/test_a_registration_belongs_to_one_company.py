"""A cs_registration is its own company's, on the way IN and on the way OUT.

── THE TWO DEFECTS ────────────────────────────────────────────────────────

`#678` made `cs_registrations.user_id` writable on the PUT route and checked
the id it writes, with `_validated_cs_account_link`. It left two holes beside
it, both found while fixing it and both ruled in afterwards:

  1. `POST /admin/cs-registrations` -> `_register_cs_on_project` wrote
     `user_id` STRAIGHT OFF THE WIRE. Same field, same collection, same screen
     as the one #678 closed, one route over -- so the cross-tenant link that
     the PUT route now refuses could simply be made at create time instead.

  2. `PUT` and `DELETE /admin/cs-registrations/{id}` had NO TENANT GATE ON THE
     ROW. `get_admin_user` proves a RANK, not a company -- the split that was a
     SEV-0 on `update_admin_user`. #678's link check stops an admin pointing
     another tenant's row at his own people; it does not stop him editing or
     soft-deleting that row at all. `DELETE` did not even read the row: the
     path id went into `update_one` and the handler returned 200 either way.

── WHAT THE ROW CONTROLS, WHICH IS WHY A STRANGER MUST NOT TOUCH IT ───────

`cs_registrations` is the BC 3301.13.13 statutory path's only answer to "whose
record is this":

  * `_refuse_if_not_the_superintendent` -- 403
    NOT_THE_REGISTERED_SUPERINTENDENT on the write path. Who MAY file.
  * `_logbook_filing_rights` -- `may_file` on the logbook tile.
  * the activation gate -- ACTIVATION_REQUIRES_CS_REGISTRATION tests only that
    a row EXISTS, so a cross-tenant DELETE can switch a superintendent log off.
  * `cs_attribution_for` -- re-derived AT RENDER TIME, so an edit moves what
    sheets ALREADY FILED say about who signed them. 17 `site_superintendent_log`
    records stand on 588 Thomas today.

── "THE REGISTRATION'S OWN COMPANY" ON A CREATE ───────────────────────────

`_validated_cs_account_link` asks three questions, the third being "is the
account in the REGISTRATION's company". On a create there is no stored row to
ask, so the answer is the company the insert is ABOUT TO STAMP --
`_register_cs_on_project` sets `company_id = get_user_company_id(admin)`
unconditionally. That is what the create path passes, and it is not a vacuous
substitution: for a caller with no company it resolves to absent, which is
exactly the legacy-orphan allowance the validator documents, and the SECOND
question (the account is in the CALLER's company) is what carries the refusal
there.

── WHAT PASSED IN THE CONTROL, AND WHY THAT IS CORRECT ────────────────────

Every `..._still_works` assertion in this file passed BEFORE the fix and
passes after. They are not evidence of the fix -- they are the assertions that
would catch a fix that is too tight, which on these routes means an admin who
can no longer correct his own superintendent's registration. The ones that
failed in the control are named in each class's docstring.
"""

import asyncio
import inspect
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from tests.source_text import strip_python  # noqa: E402

# The two live tenants and the one live registration, read-only census
# 2026-10-08: ONE row platform-wide, BLUEVIEW's, company-stamped, linked to
# Michael, on 588 Thomas. ZERO in `test`. So there is no live exploit and no
# orphan row -- this closes the hole before it has a victim.
COMPANY = "6a5e153cc7ac7a6451aa2d32"        # BLUEVIEW CONSTRUCTION INC
OTHER_COMPANY = "6a32a11051c7a54c476d2149"  # the second live tenant, `test`
MICHAEL = "6a68b16ebe9c27dedf5cf47f"
REG = "reg-on-588-thomas"
THOMAS = "6a5f63bc147407d3261df2c7"
OTHER_PROJECT = "proj-of-the-other-tenant"


# ── stand-in database, the shape the sibling screen's tests use ─────────────

class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return [dict(r) for r in list(self.rows)[:n]]


def _match(row, q):
    for k, v in (q or {}).items():
        actual = row.get("_id") if k == "_id" else row.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$ne" not in v:
                return False
        elif actual != v:
            return False
    return True


class _Coll:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.updates = []
        self.inserted = []

    def find(self, q=None, projection=None):
        return _Cursor([r for r in self.rows if _match(r, q or {})])

    async def find_one(self, q=None, projection=None):
        for r in self.rows:
            if _match(r, q or {}):
                # A COPY. `serialize_id` deletes `_id` from the dict it is
                # handed and the handlers call it on a read-back row.
                return dict(r)
        return None

    async def insert_one(self, doc):
        row = dict(doc)
        row.setdefault("_id", f"new-{len(self.rows)}")
        self.rows.append(row)
        self.inserted.append(dict(doc))
        return type("R", (), {"inserted_id": row["_id"]})()

    async def update_one(self, q, u):
        for r in self.rows:
            if _match(r, q):
                self.updates.append(dict(u.get("$set") or {}))
                r.update(u.get("$set") or {})
                return type("R", (), {"matched_count": 1, "modified_count": 1})()
        return type("R", (), {"matched_count": 0, "modified_count": 0})()

    async def update_many(self, q, u):
        # Supersession ends every live row on the project in one write.
        n = 0
        for r in self.rows:
            if _match(r, q):
                self.updates.append(dict(u.get("$set") or {}))
                r.update(u.get("$set") or {})
                n += 1
        return type("R", (), {"matched_count": n, "modified_count": n})()


class _DB:
    def __init__(self, users, regs):
        self.users = _Coll(users)
        self.cs_registrations = _Coll(regs)
        self.projects = _Coll([
            {"_id": THOMAS, "name": "588 Thomas", "company_id": COMPANY,
             "is_deleted": False},
            {"_id": OTHER_PROJECT, "name": "The other tenant's job",
             "company_id": OTHER_COMPANY, "is_deleted": False},
        ])
        self.compliance_alerts = _Coll([])
        self.audit_logs = _Coll([])


ADMIN = {"id": "u-admin", "_id": "u-admin", "role": "admin",
         "company_id": COMPANY, "email": "admin@blueview.test"}
OTHER_ADMIN = {"id": "u-other", "_id": "u-other", "role": "admin",
               "company_id": OTHER_COMPANY, "email": "admin@other.test"}
# NEVER THE `owner` ROLE, which every self-serve signup receives. The flag is
# the predicate `_assert_superintendent_under_admin` uses.
OPERATOR = {"id": "u-op", "_id": "u-op", "role": "owner", "company_id": None,
            "is_platform_operator": True, "email": "op@levelog.test"}


def _account(uid=MICHAEL, role="superintendent", company=COMPANY,
             deleted=False):
    return {
        "_id": uid, "id": uid, "name": "Michael Cespedes",
        "email": "michaelcespedes99@gmail.com", "role": role,
        "company_id": company, "is_deleted": deleted,
        "dob_superintendent_number": "32299",
    }


def _registration(user_id=None, company=COMPANY, project_id=THOMAS):
    """The live row's shape: active, company-stamped, on 588 Thomas."""
    return {
        "_id": REG, "project_id": project_id, "user_id": user_id,
        "full_name": "Michael Cespedes", "license_number": "32299",
        "license_number_normalized": "32299", "is_active": True,
        "is_deleted": False, "company_id": company,
        "phone": "+16463065657", "nyc_id_email": None, "sst_number": None,
        "created_at": "2026-09-01",
    }


def _db(accounts=None, regs=None):
    return _DB(
        users=accounts if accounts is not None else [_account()],
        regs=regs if regs is not None else [_registration()],
    )


_audited = []


async def _capture_audit(*a, **k):
    _audited.append((a, k))


def _run(db, coro_factory):
    del _audited[:]

    async def go():
        with patch.object(server, "db", db), \
             patch.object(server, "audit_log", _capture_audit), \
             patch.object(server, "to_query_id", lambda v: v):
            return await coro_factory()
    return asyncio.run(go())


def _post(db, payload, admin=None):
    """POST /admin/cs-registrations with a full create payload."""
    body = {"project_id": THOMAS, "full_name": "Michael Cespedes",
            "license_number": "32299", **payload}
    return _run(db, lambda: server.register_construction_superintendent(
        server.CSRegistrationCreate(**body), admin or ADMIN,
    ))


def _put(db, payload, admin=None, reg_id=REG):
    return _run(db, lambda: server.update_cs_registration(
        reg_id, server.CSRegistrationUpdate(**payload), admin or ADMIN,
    ))


def _delete(db, admin=None, reg_id=REG):
    return _run(db, lambda: server.delete_cs_registration(
        reg_id, admin or ADMIN,
    ))


def _row(db, reg_id=REG):
    return next(r for r in db.cs_registrations.rows if r["_id"] == reg_id)


# ── FIX 1: THE CREATE PATH VALIDATES THE ACCOUNT LINK ──────────────────────

class TheCreatePathValidatesTheAccountLink(unittest.TestCase):
    """CONTROL: the three refusal tests below FAILED (no exception was raised,
    the row was inserted with the foreign id); `test_a_valid_same_company_link
    _still_works` PASSED, because writing a good id was never the defect."""

    def _refused(self, db, payload, status, admin=None):
        before = len(db.cs_registrations.rows)
        with self.assertRaises(HTTPException) as ctx:
            _post(db, payload, admin=admin)
        self.assertEqual(ctx.exception.status_code, status)
        # NO ROW AT ALL. The link is resolved BEFORE `_register_cs_on_project`
        # runs, so a refusal cannot leave behind a registration, a superseded
        # predecessor or a one-job conflict alert.
        self.assertEqual(len(db.cs_registrations.rows), before)
        self.assertEqual(db.compliance_alerts.rows, [])
        return ctx.exception

    def test_a_cross_tenant_user_id_is_refused(self):
        """THE DEFECT, and the one #678 closed one route over. An id off the
        wire named an account in another company and the insert stored it, so
        `attribute_signer` would have matched a stranger as the registered CS
        of this company's jobsite."""
        db = _db(accounts=[_account(company=OTHER_COMPANY)], regs=[])
        self._refused(db, {"user_id": MICHAEL}, 403)

    def test_a_nonexistent_user_id_is_refused(self):
        db = _db(accounts=[], regs=[])
        self._refused(db, {"user_id": "nobody-at-all"}, 404)

    def test_a_soft_deleted_account_is_refused(self):
        """A row that reads as linked and files as nobody. The edit screen can
        SHOW that about a legacy row; the create route must not mint one."""
        db = _db(accounts=[_account(deleted=True)], regs=[])
        self._refused(db, {"user_id": MICHAEL}, 404)

    def test_a_valid_same_company_link_still_works(self):
        """PASSED IN THE CONTROL TOO, and that is the point of it: it is the
        assertion that fails if the fix is too tight. `user_id` is OPTIONAL by
        design and the commonest real create carries one."""
        db = _db(regs=[])
        out = _post(db, {"user_id": MICHAEL})
        self.assertEqual(db.cs_registrations.rows[0]["user_id"], MICHAEL)
        self.assertEqual(out["project_id"], THOMAS)

    def test_a_create_with_no_link_at_all_still_works(self):
        """ALSO GREEN IN THE CONTROL. The route exists for the superintendent
        with NO account -- another company's super on a joint site -- so a
        validator that refused an absent id would delete the route's purpose."""
        db = _db(accounts=[], regs=[])
        out = _post(db, {})
        self.assertIsNone(db.cs_registrations.rows[0]["user_id"])
        self.assertEqual(out["full_name"], "Michael Cespedes")

    def test_the_create_route_calls_the_validator_rather_than_a_second_one(self):
        """STRUCTURAL. `_validated_cs_account_link` was written to be callable
        from here -- its docstring says so -- and a second validator is how the
        two paths drift apart again. CODE ONLY: this file's docstring names the
        function, so the assertion is made on stripped source."""
        code = strip_python(
            inspect.getsource(server.register_construction_superintendent))
        self.assertIn("_validated_cs_account_link", code)

    def test_the_link_is_checked_against_the_company_the_insert_will_stamp(self):
        """"THE REGISTRATION'S OWN COMPANY" ON A CREATE is the company
        `_register_cs_on_project` is about to stamp.

        ASKED OF THE VALIDATOR'S ARGUMENT, not of the stored row. "The row
        ended up stamped with the caller's company" was true BEFORE the fix as
        well -- `_register_cs_on_project` has always stamped it -- so an
        assertion on the stored value could not fail and would not be evidence.
        What has to be true is that the create hands that company to the third
        question instead of passing an empty dict and skipping it silently.

        AND THE COMPARISON IS DERIVED from the row the insert actually wrote,
        so a create path that invented some other company would fail here even
        if it passed something non-empty.
        """
        seen = {}
        real = server._validated_cs_account_link

        async def spy(*, user_id, registration, admin):
            seen["registration"] = dict(registration or {})
            return await real(user_id=user_id, registration=registration,
                              admin=admin)

        db = _db(regs=[])
        with patch.object(server, "_validated_cs_account_link", spy):
            _post(db, {"user_id": MICHAEL})
        self.assertIn("registration", seen, "the validator was never called")
        stamped = db.cs_registrations.rows[0]["company_id"]
        self.assertEqual(seen["registration"].get("company_id"), stamped)
        self.assertEqual(stamped, server.get_user_company_id(ADMIN))


# ── FIX 2: THE ROW ITSELF IS SCOPED, ON BOTH MUTATING ROUTES ───────────────

class AnotherCompanysRegistrationIsNotEditable(unittest.TestCase):
    """CONTROL: `test_a_put_on_another_companys_registration_is_refused` and
    `test_a_delete_on_another_companys_registration_is_refused` FAILED -- the
    edit landed and the row was soft-deleted. The `..._still_works` pair
    PASSED before and after."""

    def test_a_put_on_another_companys_registration_is_refused(self):
        """THE DEFECT. #678's link check guards where the row may POINT; it
        says nothing about whether this caller may touch the row. An admin of
        `test` could rename the superintendent of 588 Thomas, and
        `cs_attribution_for` re-derives the attribution sentence AT RENDER
        TIME, so the 17 sheets already filed would start saying it."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        before = dict(_row(db))
        with self.assertRaises(HTTPException) as ctx:
            _put(db, {"full_name": "Somebody Else"}, admin=OTHER_ADMIN)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(_row(db), before)

    def test_a_delete_on_another_companys_registration_is_refused(self):
        """WORSE THAN THE EDIT. The activation gate tests only that a row
        EXISTS, so a stranger's soft-delete takes the superintendent log off
        the project -- and the route did not read the row at all, so there was
        nothing to scope and no 404 either."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        with self.assertRaises(HTTPException) as ctx:
            _delete(db, admin=OTHER_ADMIN)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIs(_row(db)["is_deleted"], False)
        self.assertIs(_row(db)["is_active"], True)

    def test_the_gate_is_asked_before_the_link_is_validated(self):
        """ORDER MATTERS, AND NOT ONLY FOR THE MESSAGE. A foreign admin sending
        a `user_id` of his own company IS refused by the link check's third
        question -- so a test that only asserted 403 would pass on the wrong
        reason, and did in the control. The validator is therefore replaced with
        one that cannot be called: the row gate must refuse him before anything
        asks about the account, because the account is not what is wrong.

        It is also the cheaper order -- the gate needs no second read -- but
        correctness is the reason, not that.
        """
        db = _db(accounts=[_account(company=OTHER_COMPANY)],
                 regs=[_registration()])

        async def never(**kwargs):
            raise AssertionError(
                "the link was validated before the row was scoped")

        with patch.object(server, "_validated_cs_account_link", never):
            with self.assertRaises(HTTPException) as ctx:
                _put(db, {"user_id": MICHAEL}, admin=OTHER_ADMIN)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_an_admins_own_company_put_still_works(self):
        """PASSED IN THE CONTROL. The gate must not cost an admin the edit
        screen his own superintendent's registration is corrected from."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        _put(db, {"phone": "+15550000000"})
        self.assertEqual(_row(db)["phone"], "+15550000000")

    def test_an_admins_own_company_delete_still_works(self):
        """PASSED IN THE CONTROL, same reason."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        out = _delete(db)
        # IT ENDS THE REGISTRATION, IT DOES NOT ERASE IT (operator's ruling,
        # 2026-10-08): a dated end, the row kept as the record of who held the
        # role while it stood. There is no is_active to turn off.
        self.assertTrue(_row(db).get("ended_at"))
        self.assertEqual(_row(db).get("ended_reason"), "removed")
        self.assertIsNot(_row(db).get("is_deleted"), True)
        self.assertIn("message", out)

    def test_the_platform_operator_reaches_both_routes(self):
        """THE ONE DELIBERATE CROSS-COMPANY PATH, by the flag and never the
        role. Without the carve-out the operator -- who carries NO company_id
        -- would be the one principal locked out of every tenant's rows."""
        db = _db(accounts=[_account(company=OTHER_COMPANY)],
                 regs=[_registration(company=OTHER_COMPANY)])
        _put(db, {"full_name": "Renamed By Operator"}, admin=OPERATOR)
        self.assertEqual(_row(db)["full_name"], "Renamed By Operator")
        _delete(db, admin=OPERATOR)
        self.assertTrue(_row(db).get("ended_at"))

    def test_a_missing_registration_is_a_404_on_delete_too(self):
        """The PUT learnt this from its read in #678. DELETE sent the path id
        straight into `update_one` and returned "CS registration deleted" for
        an id that never existed -- a 200 that was not true."""
        db = _db()
        with self.assertRaises(HTTPException) as ctx:
            _delete(db, reg_id="no-such-registration")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_soft_deleted_registration_is_still_reachable(self):
        """THE SELECTOR DOES NOT FILTER `is_deleted`, matching the PUT's read,
        which #678 documents: a soft-deleted registration stays editable
        exactly as it was, and deleting one again is idempotent rather than a
        404."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        _row(db)["is_deleted"] = True
        _delete(db)
        self.assertIs(_row(db)["is_deleted"], True)


# ── AND THE DELETE IS RECORDED, BECAUSE IT IS THE DESTRUCTIVE ONE ──────────

class TheDeleteIsAudited(unittest.TestCase):
    """CONTROL: both FAILED -- no audit row was written, because the route had
    no read, no gate and no audit."""

    def test_a_delete_writes_an_audit_row_naming_the_project(self):
        """`logbook_delete` is the house shape for a soft-delete of a statutory
        record, and #678 audited the moved link because
        `set_user_cs_registrations` audits the registrations it adds and
        REMOVES. This removes one outright -- it ends a filing right and can
        switch the superintendent log off the project -- so it is recorded the
        same way. The row the gate already had to read is where the detail
        comes from; nothing extra is fetched for it."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        _delete(db)
        self.assertEqual(len(_audited), 1, _audited)
        args, _ = _audited[0]
        self.assertEqual(args[0], "cs_registration_delete")
        self.assertEqual(args[2], "cs_registration")
        details = args[4]
        self.assertEqual(details["project_id"], THOMAS)
        self.assertEqual(details["user_id"], MICHAEL)
        self.assertEqual(details["license_number"], "32299")

    def test_a_refused_delete_writes_nothing(self):
        """An audit row for an event that did not happen is worse than none:
        it reads as evidence."""
        db = _db(regs=[_registration(user_id=MICHAEL)])
        with self.assertRaises(HTTPException):
            _delete(db, admin=OTHER_ADMIN)
        self.assertEqual(_audited, [])


if __name__ == "__main__":
    unittest.main()
