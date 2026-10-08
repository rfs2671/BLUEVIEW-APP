"""Switching the CS log on requires a registration that someone could file under.

THE LOCKOUT THIS CLOSES. `ACTIVATION_REQUIRES_CS_REGISTRATION` asked only
whether a non-deleted `cs_registrations` row EXISTED. A row with no `user_id`
passed -- and that row is a total lockout. The filing gate matches the signer
by account id, then by a licence key nothing in this repository writes, so an
unlinked row answers `not_registered_cs` for every caller and the log becomes
required, counted as missing, and fileable by nobody. A switched-off row passed
too, while `cs_attribution_for` reads only active rows.

The operator's ruling: activation requires a row that is BOTH active and linked
to an account.

THESE CALL THE REAL ENDPOINT. The neighbouring source-text tests
(`ActivationRequiresARegistration`) prove the gate is spelled in the handler;
these prove what it lets through.
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from fastapi import HTTPException  # noqa: E402

PROJECT = "p588"
MICHAEL = "6a68b16ebe9c27dedf5cf47f"
ADMIN = {"id": "admin1", "role": "admin", "full_name": "An Admin"}


def _match(doc, query):
    for k, v in (query or {}).items():
        got = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and got == v["$ne"]:
                return False
            continue
        if got != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield copy.deepcopy(d)
        return gen()

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self):
        self.docs = []
        self.writes = []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def distinct(self, field, query=None):
        return []

    async def count_documents(self, query=None, *a, **k):
        return len([d for d in self.docs if _match(d, query or {})])

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert=False):
        self.writes.append({"query": copy.deepcopy(query),
                            "update": copy.deepcopy(update)})
        for d in self.docs:
            if _match(d, query or {}):
                d.update(update.get("$set") or {})
                return


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


def _reg(**over):
    row = {"_id": "r1", "project_id": PROJECT, "full_name": "Michael Cespedes",
           "license_number": "32299", "user_id": MICHAEL, "is_active": True,
           "is_deleted": False, "created_at": "2026-09-01T12:13:32"}
    row.update(over)
    return row


def _switch(registrations, active=True):
    """Call the real handler. Returns (result_or_None, error_detail_or_None, db)."""
    db = _DB()
    db.projects.docs = [{"_id": PROJECT, "project_class": "regular",
                         "superintendent_log_active": not active}]
    db.cs_registrations.docs = [dict(r) for r in registrations]
    with patch.object(S, "db", db), \
         patch.object(S, "to_query_id", lambda x: x):
        try:
            out = asyncio.run(S.set_logbook_activation(
                PROJECT,
                {"log_type": "site_superintendent_log", "active": active},
                current_user=ADMIN))
            return out, None, db
        except HTTPException as e:
            return None, e.detail, db


def _flag_writes(db):
    return [w for w in db.projects.writes
            if "superintendent_log_active" in (w["update"].get("$set") or {})]


class AnActiveLinkedRowSwitchesItOn(unittest.TestCase):
    """The ordinary case: Michael's 588 registration, as it is stored."""

    def test_michaels_registration_is_enough(self):
        out, err, db = _switch([_reg()])
        self.assertIsNone(err)
        self.assertIs(out["active"], True)
        self.assertEqual(len(_flag_writes(db)), 1)

    def test_one_good_row_among_bad_ones_is_enough(self):
        """A project accumulates rows -- a predecessor is deactivated, not
        edited. One active, linked row is the registration."""
        out, err, _ = _switch([
            _reg(_id="old", is_active=False),
            _reg(_id="stray", user_id=None),
            _reg(_id="live"),
        ])
        self.assertIsNone(err)
        self.assertIs(out["active"], True)


class AnythingLessRefusesAndSaysWhy(unittest.TestCase):

    def _refused(self, regs, reason):
        out, err, db = _switch(regs)
        self.assertIsNone(out)
        self.assertEqual(err["code"], "ACTIVATION_REQUIRES_CS_REGISTRATION")
        self.assertEqual(err["reason"], reason)
        self.assertEqual(err["message"],
                         S.CS_ACTIVATION_REFUSAL_MESSAGES[reason])
        self.assertEqual(_flag_writes(db), [],
                         "a refused activation still wrote the flag")

    def test_no_row_at_all(self):
        self._refused([], "none")

    def test_a_deleted_row_is_no_row(self):
        self._refused([_reg(is_deleted=True)], "none")

    def test_an_unlinked_row_THE_LOCKOUT(self):
        """The case this change exists for. Before it, this switched the log on
        for a project where nobody could file it."""
        for blank in (None, "", "   "):
            with self.subTest(user_id=repr(blank)):
                self._refused([_reg(user_id=blank)], "unlinked")

    def test_an_unlinked_row_with_the_key_absent(self):
        row = _reg()
        del row["user_id"]
        self._refused([row], "unlinked")

    def test_a_switched_off_row(self):
        self._refused([_reg(is_active=False)], "inactive")

    def test_is_active_must_be_the_boolean(self):
        """The same test `cs_attribution_for` applies: `is_active: True`. A
        truthy string is not a switched-on registration."""
        for junk in ("true", 1, None):
            with self.subTest(is_active=repr(junk)):
                self._refused([_reg(is_active=junk)], "inactive")

    def test_switched_off_AND_unlinked(self):
        self._refused([_reg(is_active=False, user_id=None)], "inactive")


class SwitchingItOffNeverAsks(unittest.TestCase):
    """A gate that could trap a project in the ON state would be worse than
    the one it replaces. Unchanged by this fix, and asserted against the real
    handler rather than its spelling."""

    def test_off_with_no_registration(self):
        out, err, _ = _switch([], active=False)
        self.assertIsNone(err)
        self.assertIs(out["active"], False)

    def test_off_with_an_unlinked_registration(self):
        out, err, _ = _switch([_reg(user_id=None)], active=False)
        self.assertIsNone(err)
        self.assertIs(out["active"], False)


class TheRuleWithNoDatabase(unittest.TestCase):

    def test_reasons(self):
        f = S._cs_activation_refusal
        self.assertEqual(f([]), "none")
        self.assertEqual(f(None), "none")
        self.assertIsNone(f([_reg()]))
        self.assertEqual(f([_reg(user_id="")]), "unlinked")
        self.assertEqual(f([_reg(is_active=False)]), "inactive")

    def test_every_reason_names_where_to_fix_it(self):
        for reason in ("none", "inactive", "unlinked"):
            with self.subTest(reason):
                self.assertIn("User Management",
                              S.CS_ACTIVATION_REFUSAL_MESSAGES[reason])


if __name__ == "__main__":
    unittest.main(verbosity=2)
