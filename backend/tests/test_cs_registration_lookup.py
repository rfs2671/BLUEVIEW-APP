"""The CS attribution reads the ACTIVE registration, deterministically.

THE DEFECT. cs_attribution_for looked the registration up like this:

    reg = await db_.cs_registrations.find_one({
        "project_id": str(project_id),
        "is_deleted": {"$ne": True},
    })

No `is_active` filter and no sort. A project accumulates registrations —
`register_construction_superintendent` deactivates the predecessor and inserts
a new row rather than editing in place, and an admin can switch one off — so
`find_one` returned whichever Mongo handed back first. When that was the
DEACTIVATED predecessor, attribute_signer read its `deactivated_at`, and a
project with a live registered CS reported as having none.

THAT IS THE FAILURE THE LINKING EXISTS TO PREVENT. The whole point of naming
the CS on the record is that the log can say the signer was the registered
superintendent; a lookup that picks the wrong row makes the answer arbitrary,
and it degrades in the direction of accusing a named person on a statutory
document of not being registered.

DETERMINISTIC, NOT MERELY FILTERED. Two active rows should not exist — the
registration path deactivates the predecessor — but "should not" is not
"cannot", and a lookup whose answer depends on Mongo's return order is one
migration away from being wrong. Newest `created_at` wins, ties broken on
`_id`, the same ordering _filed_log and open_amendment_head use.

A FAILED READ STILL REPORTS "no registration", NEVER a mismatch. That posture
is unchanged: the one thing this must not do is turn an outage into a finding
against a named person.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib.logbook import cs_attribution as A  # noqa: E402

DAY = "2026-09-01"
T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _reg(**over):
    doc = {
        "_id": "r1", "project_id": "P1", "full_name": "Michael Cespedes",
        "license_number": "CS 12345", "license_number_normalized": "CS12345",
        "user_id": None, "is_active": True, "is_deleted": False,
        "created_at": T0,
    }
    doc.update(over)
    return doc


class _Cursor:
    """Applies the sort spec for real.

    A double whose `sort()` is a no-op cannot test ordering — it returns
    insertion order and the determinism assertion passes on the fake rather
    than on the code. This one honours [(field, -1|1), ...] the way Mongo
    does, so a lookup that forgets to sort actually fails here.
    """

    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, spec, *a, **k):
        for field, direction in reversed(list(spec)):
            self.docs.sort(key=lambda d: d.get(field),
                           reverse=(direction == -1))
        return self

    async def to_list(self, *a, **k):
        return self.docs


class _Coll:
    """Returns rows in a DELIBERATELY HOSTILE order — the deactivated one
    first, which is exactly what an unsorted find_one could hand back."""

    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    async def find_one(self, query, *a, **k):
        self.queries.append(query)
        for d in self.docs:
            if all(d.get(k2) == v for k2, v in query.items()
                   if not isinstance(v, dict)):
                return d
        return None

    def find(self, query, *a, **k):
        self.queries.append(query)
        out = [d for d in self.docs
               if all(d.get(k2) == v for k2, v in query.items()
                      if not isinstance(v, dict))]
        return _Cursor(out)


class _DB:
    def __init__(self, docs):
        self.cs_registrations = _Coll(docs)


SIGNER = {"id": "u-michael", "name": "Michael Cespedes"}


def _run(docs, signer=SIGNER, project="P1"):
    db = _DB(docs)
    out = asyncio.run(server.cs_attribution_for(db, project, DAY, signer))
    return out, db.cs_registrations.queries


class TheActiveRegistrationWins(unittest.TestCase):
    def test_a_deactivated_predecessor_is_not_returned(self):
        """THE BUG. Deactivated row first in the collection — the order an
        unsorted find_one is entitled to hand back."""
        dead = _reg(_id="old", is_active=False,
                    deactivated_at=T0 + timedelta(days=1), user_id="u-old")
        live = _reg(_id="new", is_active=True, user_id="u-michael",
                    created_at=T0 + timedelta(days=2))
        out, _ = _run([dead, live])
        self.assertEqual(out["state"], A.MATCHED_ACCOUNT,
                         "the LIVE registration must be the one consulted")

    def test_the_query_filters_on_is_active(self):
        _, queries = _run([_reg()])
        self.assertTrue(any(q.get("is_active") is True for q in queries),
                        f"is_active not in any query: {queries}")

    def test_two_active_rows_resolve_deterministically(self):
        """Should not happen — the registration path deactivates the
        predecessor — but the answer must not depend on return order."""
        a = _reg(_id="a", user_id="u-a", created_at=T0)
        b = _reg(_id="b", user_id="u-michael", created_at=T0 + timedelta(days=5))
        first = _run([a, b])[0]["state"]
        second = _run([b, a])[0]["state"]
        self.assertEqual(first, second)
        self.assertEqual(first, A.MATCHED_ACCOUNT, "newest created_at wins")


class WhatMustNotChange(unittest.TestCase):
    """PASSES EITHER WAY — the posture this lookup already had."""

    def test_no_registration_at_all_is_NO_REGISTRATION(self):
        out, _ = _run([])
        self.assertEqual(out["state"], A.NO_REGISTRATION)

    def test_a_missing_project_checks_nothing(self):
        out, _ = _run([_reg()], project=None)
        self.assertEqual(out["state"], A.NO_REGISTRATION)

    def test_an_unlinked_registration_still_corroborates_on_licence(self):
        """The state the linking upgrades: without user_id the best available
        answer is the weaker one, and it is still given."""
        out, _ = _run([_reg(user_id=None)],
                      signer={"id": "u-michael", "name": "Michael Cespedes",
                              "cs_license_number": "CS-12345"})
        self.assertEqual(out["state"], A.MATCHED_LICENCE)

    def test_a_read_failure_reports_no_registration_not_a_mismatch(self):
        class _Boom:
            def find(self, *a, **k):
                raise RuntimeError("mongo down")

            async def find_one(self, *a, **k):
                raise RuntimeError("mongo down")

        class _BoomDB:
            cs_registrations = _Boom()

        out = asyncio.run(server.cs_attribution_for(_BoomDB(), "P1", DAY, SIGNER))
        self.assertEqual(out["state"], A.NO_REGISTRATION,
                         "an outage must never become a finding against a person")

    def test_it_still_writes_nothing(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.cs_attribution_for))))
        for write in ("update_one", "insert_one", "delete_one", "$set"):
            self.assertNotIn(write, code)


if __name__ == "__main__":
    unittest.main()
