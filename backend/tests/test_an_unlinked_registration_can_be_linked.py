"""The account link on a CS registration is WRITABLE, and both directions work.

── THE DEFECT ──────────────────────────────────────────────────────────────

`CSRegistrationUpdate` declares `user_id` and says why: "the commonest real
sequence is a registration typed for DOB first and the account created later".
`frontend/app/admin/superintendent.jsx` sends it, and its own comment says "an
edit form that silently dropped the field would make an unlinked registration
permanently unlinkable". `update_cs_registration` built its `$set` dict from
six of the model's seven settable fields and NEVER COPIED `user_id`.

So the form sent it, the model accepted it, the handler returned 200 with the
re-read row — and the link was unchanged. The one repair that screen exists to
make did nothing, silently, and the 200 said it had worked.

── WHY THE THREE STATES ARE NOT TWO ────────────────────────────────────────

    user_id: "<id>"   LINK     — this registration is that account's
    user_id: null     UNLINK   — it belongs to no account
    field absent      LEAVE    — this request is not about the link

`null` is a VALUE here, not an omission. A handler that keyed on
`data.user_id is not None` — the shape every other field in this model uses —
would be the same defect one direction over: it could link and never unlink,
and unlinking is how an admin corrects a link made to the wrong man. Pydantic's
`model_fields_set` is the only thing that separates "sent null" from "not
sent", so that is what the handler asks.

── WHAT A RE-LINK MOVES, WHICH IS WHY IT IS VALIDATED ──────────────────────

`cs_registrations.user_id` is the primary key `attribute_signer` matches on. A
re-link moves, for the two accounts either side of it:

  * `_refuse_if_not_the_superintendent` — 403 NOT_THE_REGISTERED_SUPERINTENDENT
    on the write path for BC 3301.13.13.
  * `_logbook_filing_rights` / the logbook tile — `may_file`.
  * `superintendent_projects_for` — the CP nav's superintendent-log slot.
  * `cs_attribution_for` — READ TIME, so it changes the attribution sentence
    printed on sheets ALREADY FILED.

Writing an arbitrary id in is therefore a false statement about a DOB-facing
role, so the id is checked the way `_assert_superintendent_under_admin` checks
one: the account must exist, must not be soft-deleted, and must be in the
caller's company. Plus the registration's own company, which that sibling has
no equivalent of because it starts from the user rather than from the row.

NOT THE ROLE, AND THAT IS DELIBERATE. See `_refuse_if_not_the_superintendent`,
which states it at length: `role == "superintendent"` is not the question, the
registration is, and this screen's entire purpose is the superintendent who is
not carried as one. A role equality test here would refuse the only case the
screen is kept for.
"""

import asyncio
import inspect
import os
import sys
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
from tests.source_text import strip_python  # noqa: E402

COMPANY = "6a5e153cc7ac7a6451aa2d32"       # BLUEVIEW CONSTRUCTION INC
OTHER_COMPANY = "6a32a11051c7a54c476d2149"  # the second live tenant
MICHAEL = "6a68b16ebe9c27dedf5cf47f"
REG = "reg-on-588-thomas"
THOMAS = "6a5f63bc147407d3261df2c7"


# ── stand-in database, the same shape the sibling screen's tests use ────────

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

    def find(self, q=None, projection=None):
        return _Cursor([r for r in self.rows if _match(r, q or {})])

    async def find_one(self, q=None, projection=None):
        for r in self.rows:
            if _match(r, q or {}):
                # A COPY. `serialize_id` deletes `_id` from the dict it is
                # handed and the handler calls it on the read-back row; a live
                # reference would let the response shape eat the fixture.
                return dict(r)
        return None

    async def update_one(self, q, u):
        for r in self.rows:
            if _match(r, q):
                self.updates.append(dict(u.get("$set") or {}))
                r.update(u.get("$set") or {})
                return type("R", (), {"matched_count": 1, "modified_count": 1})()
        return type("R", (), {"matched_count": 0, "modified_count": 0})()


class _DB:
    def __init__(self, users, regs):
        self.users = _Coll(users)
        self.cs_registrations = _Coll(regs)
        self.projects = _Coll([{"_id": THOMAS, "name": "588 Thomas",
                                "company_id": COMPANY, "is_deleted": False}])
        self.audit_logs = _Coll([])


ADMIN = {"id": "u-admin", "_id": "u-admin", "role": "admin",
         "company_id": COMPANY}


def _account(uid=MICHAEL, role="superintendent", company=COMPANY,
             deleted=False):
    return {
        "_id": uid, "id": uid, "name": "Michael Cespedes",
        "email": "michaelcespedes99@gmail.com", "role": role,
        "company_id": company, "is_deleted": deleted,
        "dob_superintendent_number": "32299",
    }


def _registration(user_id=None, company=COMPANY):
    """The live row's shape: active, company-stamped, on 588 Thomas."""
    return {
        "_id": REG, "project_id": THOMAS, "user_id": user_id,
        "full_name": "Michael Cespedes", "license_number": "32299",
        "license_number_normalized": "32299", "is_active": True,
        "is_deleted": False, "company_id": company,
        "phone": "+16463065657", "nyc_id_email": None, "sst_number": None,
        "created_at": "2026-09-01",
    }


def _db(accounts=None, reg=None):
    return _DB(
        users=accounts if accounts is not None else [_account()],
        regs=[reg if reg is not None else _registration()],
    )


_audited = []


async def _capture_audit(*a, **k):
    _audited.append((a, k))


def _put(db, payload, admin=None, reg_id=REG):
    """PUT /admin/cs-registrations/{id} with exactly the keys in `payload`.

    THE KEYS ARE THE POINT. `CSRegistrationUpdate(**payload)` records which
    fields arrived in `model_fields_set`, so a payload without `user_id` is
    the "leave the link alone" request and one with `user_id=None` is the
    unlink — the same two requests the edit form actually sends.
    """
    del _audited[:]

    async def go():
        with patch.object(server, "db", db), \
             patch.object(server, "audit_log", _capture_audit), \
             patch.object(server, "to_query_id", lambda v: v):
            return await server.update_cs_registration(
                reg_id, server.CSRegistrationUpdate(**payload), admin or ADMIN,
            )
    return asyncio.run(go())


def _stored(db):
    return db.cs_registrations.rows[0]


# ── LINKING, WHICH IS THE WHOLE POINT OF THE FIELD ──────────────────────────

class LinkingAnUnlinkedRegistration(unittest.TestCase):
    def test_the_link_is_persisted(self):
        """THE DEFECT. Every assertion below this one was already green."""
        db = _db()
        out = _put(db, {"user_id": MICHAEL})
        self.assertEqual(_stored(db)["user_id"], MICHAEL)
        self.assertEqual(out.get("user_id"), MICHAEL)

    def test_the_id_is_stored_as_a_string(self):
        """`_cs_rows_are_for` carries a two-spelling selector because rows hold
        either an ObjectId or a string, and `attribute_signer` compares
        `str(...)` on both sides. A new write has no excuse to add to that."""
        db = _db()
        _put(db, {"user_id": f"  {MICHAEL}  "})
        self.assertEqual(_stored(db)["user_id"], MICHAEL)
        self.assertIsInstance(_stored(db)["user_id"], str)

    def test_a_cp_role_account_can_be_linked(self):
        """THE CASE THE SCREEN IS KEPT FOR, and a role gate would refuse it.

        `_refuse_if_not_the_superintendent` says it in its own words: the
        filing right keys on the registration and never on `role`, because a
        role gate "would refuse the only man who must file". Linking is the act
        that grants that right, so it cannot be stricter than the gate it feeds.
        """
        db = _db(accounts=[_account(role="cp")])
        _put(db, {"user_id": MICHAEL})
        self.assertEqual(_stored(db)["user_id"], MICHAEL)


# ── AND UNLINKING, WHICH IS THE SAME DEFECT ONE DIRECTION OVER ──────────────

class UnlinkingIsNotTheSameAsNotSupplied(unittest.TestCase):
    def test_an_explicit_null_clears_the_link(self):
        db = _db(reg=_registration(user_id=MICHAEL))
        _put(db, {"user_id": None})
        self.assertIsNone(_stored(db)["user_id"])

    def test_a_request_that_omits_the_field_leaves_the_link_alone(self):
        """The edit form sends only what changed. If an absent field read as
        `null` this handler would unlink the registration every time an admin
        corrected a phone number."""
        db = _db(reg=_registration(user_id=MICHAEL))
        _put(db, {"phone": "+15550000000"})
        self.assertEqual(_stored(db)["user_id"], MICHAEL)
        self.assertEqual(_stored(db)["phone"], "+15550000000")
        # AND THE KEY IS NOT IN THE WRITE AT ALL, so this cannot pass by
        # happening to re-write the same value.
        self.assertNotIn("user_id", db.cs_registrations.updates[0])

    def test_an_empty_string_unlinks_rather_than_storing_it(self):
        """'' IS A USER ID THAT MATCHES NOBODY. The create payload's own
        comment says so: `superintendent_projects_for` would see a truthy
        `user_id` and query on it, so the row would read as linked to the
        screen and as linked to nothing to the gate."""
        db = _db(reg=_registration(user_id=MICHAEL))
        _put(db, {"user_id": ""})
        self.assertIsNone(_stored(db)["user_id"])

    def test_the_handler_does_not_use_the_is_not_none_shape_for_the_link(self):
        """STRUCTURAL, because the behavioural tests above cannot tell a
        correct handler from one that happens to agree today. Every other field
        in this model is copied under `if data.X is not None:`, which is
        precisely the shape that cannot unlink. CODE ONLY — this file's own
        docstring names the banned construct."""
        code = strip_python(inspect.getsource(server.update_cs_registration))
        self.assertNotIn("data.user_id is not None", code)
        self.assertIn("model_fields_set", code)


# ── THE ID IS CHECKED, BECAUSE IT NAMES A MAN ON A STATUTORY RECORD ─────────

class TheTargetAccountIsValidated(unittest.TestCase):
    def _refused(self, db, payload, status, admin=None):
        before = dict(_stored(db))
        with self.assertRaises(HTTPException) as ctx:
            _put(db, payload, admin=admin)
        self.assertEqual(ctx.exception.status_code, status)
        # NOTHING ELSE LANDED EITHER. A handler that wrote the other fields and
        # then refused would be a partial success reported as a failure.
        self.assertEqual(_stored(db), before)
        return ctx.exception

    def test_a_user_in_another_company_is_refused(self):
        """TENANCY. `get_admin_user` proves a RANK, not a company — the split
        that was a SEV-0 on `update_admin_user` and that
        `_assert_superintendent_under_admin` restates. A registration asserts
        who is responsible for a jobsite; pointing one at another tenant's
        account is a false statement about a DOB-facing role."""
        db = _db(accounts=[_account(company=OTHER_COMPANY)])
        self._refused(db, {"user_id": MICHAEL}, 403)

    def test_a_user_outside_the_registrations_own_company_is_refused(self):
        """THE CHECK THE SIBLING HAS NO EQUIVALENT OF.
        `_assert_superintendent_under_admin` starts from the USER and compares
        him to the admin. This handler starts from the ROW, and the row carries
        its own `company_id` — so an admin editing a registration that is not
        his company's must not be able to point it at his own people."""
        db = _db(reg=_registration(user_id=None, company=OTHER_COMPANY))
        self._refused(db, {"user_id": MICHAEL}, 403)

    def test_a_nonexistent_user_id_is_refused(self):
        db = _db(accounts=[])
        self._refused(db, {"user_id": "nobody-at-all"}, 404)

    def test_a_soft_deleted_account_is_refused(self):
        """A LINK TO A DELETED USER IS THE THIRD STATE THE SCREEN CALLS OUT:
        "Linked to a user who no longer exists" — it looks linked until
        somebody tries to use it. The screen can show that about a legacy row;
        this handler must not create one."""
        db = _db(accounts=[_account(deleted=True)])
        self._refused(db, {"user_id": MICHAEL}, 404)

    def test_the_platform_operator_may_link_across_companies(self):
        """The one deliberate cross-company path, by the same predicate
        `_assert_superintendent_under_admin` uses — `is_platform_operator`, and
        never the `owner` role, which every self-serve signup receives."""
        db = _db(accounts=[_account(company=OTHER_COMPANY)],
                 reg=_registration(company=OTHER_COMPANY))
        operator = {"id": "u-op", "_id": "u-op", "role": "owner",
                    "company_id": None, "is_platform_operator": True}
        _put(db, {"user_id": MICHAEL}, admin=operator)
        self.assertEqual(_stored(db)["user_id"], MICHAEL)


# ── AND IT IS RECORDED, BECAUSE THE SIBLING RECORDS ITS OWN ─────────────────

class TheLinkChangeIsAudited(unittest.TestCase):
    def test_a_link_change_writes_an_audit_row_naming_both_sides(self):
        """`set_user_cs_registrations` audits the registrations it adds and
        removes. This moves the same fact — who may file BC 3301.13.13 — so it
        is recorded the same way, with the id it came FROM as well as the one it
        went to: "who may file changed" is unanswerable from the new value."""
        db = _db(reg=_registration(user_id=None))
        _put(db, {"user_id": MICHAEL})
        self.assertEqual(len(_audited), 1, _audited)
        args, _ = _audited[0]
        details = args[4]
        self.assertIsNone(details["user_id_was"])
        self.assertEqual(details["user_id_now"], MICHAEL)

    def test_an_edit_that_does_not_touch_the_link_writes_no_row(self):
        """Audit noise is the thing that makes an audit unreadable. The other
        six fields are not the filing gate."""
        db = _db(reg=_registration(user_id=MICHAEL))
        _put(db, {"phone": "+15550000000"})
        self.assertEqual(_audited, [])

    def test_a_no_op_link_write_is_not_recorded_as_a_change(self):
        db = _db(reg=_registration(user_id=MICHAEL))
        _put(db, {"user_id": MICHAEL})
        self.assertEqual(_audited, [])


# ── THE NEXT DROPPED FIELD, CAUGHT WITHOUT ANYBODY NOTICING IT ─────────────

class EverySettableFieldIsActuallyCopied(unittest.TestCase):
    """THE CENSUS IS DERIVED, NOT TYPED.

    The defect was one field of seven missing from a hand-written copy block,
    and nothing could see it: the model declared it, the client sent it, the
    handler returned 200. This asks the MODEL what its fields are and requires
    the handler to mention each one, so the eighth field cannot be added to
    `CSRegistrationUpdate` and silently ignored the way the seventh was.

    IT IS NOT A SUBSTITUTE for the behavioural tests above — "the handler
    mentions the name" is weaker than "the value lands". It is the net under
    the fields nobody has written a behaviour test for.
    """

    def test_the_handler_reads_every_field_the_model_declares(self):
        code = strip_python(inspect.getsource(server.update_cs_registration))
        missing = [f for f in server.CSRegistrationUpdate.model_fields
                   if f"data.{f}" not in code]
        self.assertEqual(missing, [], f"declared and never copied: {missing}")

    def test_a_missing_registration_is_still_a_404(self):
        """The handler used to learn this from `matched_count == 0`. It now
        reads the row FIRST — it needs the old link to audit and the row's
        company to check tenancy — so the 404 has a new source and the same
        meaning."""
        db = _db()
        with self.assertRaises(HTTPException) as ctx:
            _put(db, {"phone": "+15550000000"}, reg_id="no-such-registration")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
