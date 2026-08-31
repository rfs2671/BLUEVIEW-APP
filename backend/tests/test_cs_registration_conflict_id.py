"""The CS registration list survives an ACTIVE registration.

SAME HELPER, SAME DEFECT CLASS, DIFFERENT ENDPOINT. list_cs_registrations calls
serialize_id(reg) -- which does obj["id"] = str(obj["_id"]); del obj["_id"] on
the caller's dict and returns that same dict -- and then eleven lines later
builds a conflict query containing

    "_id": {"$ne": reg["_id"]}

on the key that call deleted. Guaranteed KeyError.

IT IS GATED BEHIND `if reg.get("is_active")`, WHICH IS WHY IT SURVIVED. A list
with no active registration never enters the branch, so the endpoint works
until the moment real data exists -- and then GET /api/admin/cs-registrations
500s for the whole company. It shipped before the weekend and was live in
production the entire time, unrelated to the client-version outage that
surfaced the pattern.

THE CONFLICT CHECK IS THE POINT OF THE BRANCH. It answers "is this licence
already registered as active somewhere else", which is the question the
superintendent register exists to answer. Excluding the row being examined is
what makes the count meaningful, so the _id must be the real ObjectId: the
string form serialize_id leaves behind would never match an ObjectId _id,
$ne would exclude nothing, and every active registration would report a
conflict with ITSELF. Stopping the crash is not enough -- the value has to
still be the right one.
"""

import ast
import asyncio
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path

from bson import ObjectId

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

REG_A = ObjectId("66f0a1b2c3d4e5f60718aaa1")
REG_B = ObjectId("66f0a1b2c3d4e5f60718bbb2")
PROJ = ObjectId("66f0a1b2c3d4e5f60718ccc3")
ADMIN = {"id": "ad1", "role": "admin", "company_id": "co1"}


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return self.docs


class _Regs:
    def __init__(self, docs, sink):
        self.docs = docs
        self.sink = sink

    def find(self, *a, **k):
        return _Cursor(self.docs)

    async def count_documents(self, query, *a, **k):
        self.sink.append(query)
        return 0


class _Projects:
    async def find_one(self, *a, **k):
        return {"_id": PROJ, "name": "857 Prescott"}


class _DB:
    def __init__(self, docs, sink):
        self.cs_registrations = _Regs(docs, sink)
        self.projects = _Projects()


def _reg(oid, **over):
    doc = {
        "_id": oid, "company_id": "co1", "project_id": str(PROJ),
        "license_number_normalized": "CS12345", "is_active": True,
        "is_deleted": False,
    }
    doc.update(over)
    return doc


def _run(docs):
    sink = []
    real = server.db
    server.db = _DB(docs, sink)
    try:
        out = asyncio.run(server.list_cs_registrations(
            project_id=None, admin=ADMIN))
    finally:
        server.db = real
    return out, sink


class AnActiveRegistrationDoesNotCrashTheList(unittest.TestCase):
    """PRE-FIX THIS RAISES KeyError: '_id'."""

    def test_one_active_registration(self):
        out, _ = _run([_reg(REG_A)])
        self.assertEqual(len(out), 1)
        self.assertIs(out[0]["has_conflict"], False)

    def test_several_active_registrations(self):
        out, _ = _run([_reg(REG_A), _reg(REG_B)])
        self.assertEqual(len(out), 2)

    def test_the_row_still_serialises(self):
        out, _ = _run([_reg(REG_A)])
        self.assertEqual(out[0]["id"], str(REG_A))
        self.assertNotIn("_id", out[0])
        self.assertEqual(out[0]["project_name"], "857 Prescott")


class TheExclusionMUSTBeTheObjectId(unittest.TestCase):
    """Not merely 'it does not crash'. A string _id matches no document, $ne
    excludes nothing, and every active registration reports a conflict with
    itself -- a wrong answer where the endpoint's whole purpose is the answer.
    """

    def test_the_conflict_query_excludes_by_ObjectId(self):
        _, sink = _run([_reg(REG_A)])
        self.assertEqual(len(sink), 1)
        excluded = sink[0]["_id"]["$ne"]
        self.assertIsInstance(excluded, ObjectId)
        self.assertEqual(excluded, REG_A)

    def test_it_is_not_the_string_serialize_id_leaves_behind(self):
        _, sink = _run([_reg(REG_A)])
        self.assertNotEqual(sink[0]["_id"]["$ne"], str(REG_A))

    def test_each_row_excludes_ITSELF_not_the_first_row(self):
        """The capture has to happen per iteration."""
        _, sink = _run([_reg(REG_A), _reg(REG_B)])
        self.assertEqual([q["_id"]["$ne"] for q in sink], [REG_A, REG_B])

    def test_the_rest_of_the_conflict_query_is_intact(self):
        _, sink = _run([_reg(REG_A)])
        q = sink[0]
        self.assertEqual(q["license_number_normalized"], "CS12345")
        self.assertIs(q["is_active"], True)


class TheInactivePathIsUnchanged(unittest.TestCase):
    """PASSES EITHER WAY -- this is the path that hid the defect."""

    def test_an_inactive_registration_never_enters_the_branch(self):
        out, sink = _run([_reg(REG_A, is_active=False)])
        self.assertIs(out[0]["has_conflict"], False)
        self.assertEqual(sink, [])

    def test_an_empty_list_is_fine(self):
        out, sink = _run([])
        self.assertEqual(out, [])
        self.assertEqual(sink, [])


class TheCaptureIsBeforeTheMutation(unittest.TestCase):
    def test_source_order(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.list_cs_registrations))))
        self.assertLess(code.index("reg_oid = reg.get('_id')"),
                        code.index("serialize_id(reg)"))

    def test_no_read_of_reg_id_survives_the_call(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.list_cs_registrations))))
        after = code[code.index("serialize_id(reg)"):]
        self.assertNotIn("reg['_id']", after)


if __name__ == "__main__":
    unittest.main()
