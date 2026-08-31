"""Every authenticated request, from an install that reports its version.

THE DEFECT LIVES ENTIRELY IN THE GAP BETWEEN TWO HEADERS. get_current_user
stamps which client build is calling, and the stamp is guarded by

    if reported and _client_version_needs_stamp(user, reported)

where `reported` is the X-Client-Version header. Send the header and the branch
runs; omit it and nothing does. Every test in the suite omitted it, so the
entire suite passed while the branch it never entered raised KeyError on every
authenticated request in production.

That is why this file asserts BOTH halves. A test that only sends the header
would miss a regression that breaks the header-less path; a test that only
omits it is what already existed, and it proved nothing.

WHAT ACTUALLY BROKE. serialize_id MUTATES ITS ARGUMENT:

    obj["id"] = str(obj["_id"]); del obj["_id"]; return obj

It returns the same dict it was handed, so it reads like a pure function at the
call site and is not one. Eleven lines after `user_data = serialize_id(user)`,
get_current_user read `user["_id"]` -- a key that call had just deleted. It
could never succeed. Not data-dependent, not user-dependent: every account,
every request, 500, for any install sending the header.

THE REPAIR THAT WOULD HAVE BEEN WORSE. Swapping in user_data["id"] -- the
string serialize_id just produced -- stops the KeyError and then silently never
writes, because _record_client_version filters {"_id": user_id} with no
to_query_id and a string never matches an ObjectId _id. A crash that names
itself would have become a stamp that does nothing, on the field the admin
surface reads to answer whose phone is stranded. The type is asserted below
for that reason, not for tidiness.
"""

import ast
import inspect
import os
import sys
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from bson import ObjectId
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

PW = "correct-horse-battery-staple"
EMAIL = "stamp@blueviewbuilders.com"
UID = ObjectId("66f0a1b2c3d4e5f607182999")
_IP = [0]


class _Coll:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, *a, **k):
        return self.doc

    async def update_one(self, *a, **k):
        return MagicMock(matched_count=1, modified_count=1)

    async def count_documents(self, *a, **k):
        return 0


class _DB:
    def __init__(self, user):
        self._user = user

    def __getattr__(self, name):
        return _Coll(self._user if name == "users" else None)


def _user(**over):
    doc = {
        "_id": UID, "email": EMAIL, "password": server.hash_password(PW),
        "role": "cp", "company_id": "68a1b2c3d4e5f60718293a11",
        "name": "Stamp", "full_name": "Stamp",
    }
    doc.update(over)
    return doc


class _Harness:
    """Runs the real two-call login sequence the app performs."""

    def __init__(self, user):
        self.captured = []
        server.db = _DB(user)
        _IP[0] += 1
        # TWO RATE LIMITERS SIT IN FRONT OF /auth/login and both must be
        # stepped around, without depending on a TestClient(client=...) kwarg
        # that exists only in newer Starlette than requirements.txt pins:
        #   - lib/rate_limits middleware, keyed on X-Forwarded-For
        #     (rate_limits.py:350) -> a distinct forwarded IP per harness;
        #   - check_auth_rate_limit, keyed on request.client.host, 10/min
        #     -> overridden, since the limiter is not what is under test.
        self.fwd = f"198.51.100.{_IP[0] % 250}"
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def __enter__(self):
        self._real = server._record_client_version
        server.app.dependency_overrides[
            server.check_auth_rate_limit] = lambda: None

        async def _noop():
            return None

        def _fake(uid, ver):
            # captured at CALL time, before create_task ever awaits it
            self.captured.append((uid, ver))
            return _noop()

        server._record_client_version = _fake
        return self

    def __exit__(self, *exc):
        server._record_client_version = self._real
        server.app.dependency_overrides.pop(server.check_auth_rate_limit, None)

    def sequence(self, version="1.2.3"):
        h = {"X-Forwarded-For": self.fwd}
        if version is not None:
            h["X-Client-Version"] = version
        r1 = self.client.post("/api/auth/login",
                              json={"email": EMAIL, "password": PW}, headers=h)
        if r1.status_code != 200:
            return r1.status_code, None
        h["Authorization"] = f"Bearer {r1.json()['token']}"
        r2 = self.client.get("/api/auth/me", headers=h)
        return r1.status_code, r2.status_code


class WithTheHeader(unittest.TestCase):
    """THE HALF THAT WAS BROKEN IN PRODUCTION."""

    def test_auth_me_returns_200(self):
        with _Harness(_user()) as h:
            self.assertEqual(h.sequence("1.2.3"), (200, 200))

    def test_it_is_200_for_every_account_shape(self):
        """Not data-dependent. The KeyError fired on all of them."""
        for label, doc in (
            ("superintendent", _user(role="superintendent")),
            ("pending", _user(account_status="pending")),
            ("no company", {k: v for k, v in _user().items()
                            if k != "company_id"}),
            ("seen_at naive", _user(client_version="1.2.3",
                                    client_version_seen_at=datetime(2026, 8, 1))),
            ("seen_at aware", _user(client_version="1.2.3",
                                    client_version_seen_at=datetime.now(timezone.utc)
                                    - timedelta(days=3))),
        ):
            with self.subTest(label), _Harness(doc) as h:
                self.assertEqual(h.sequence("1.2.3"), (200, 200))

    def test_the_stamp_actually_fires(self):
        with _Harness(_user()) as h:
            h.sequence("1.2.3")
            self.assertEqual(len(h.captured), 1)
            self.assertEqual(h.captured[0][1], "1.2.3")

    def test_the_stamp_is_handed_an_ObjectId_NOT_the_string_id(self):
        """THE TRAP. user_data["id"] would stop the crash and never match."""
        with _Harness(_user()) as h:
            h.sequence("1.2.3")
            uid = h.captured[0][0]
            self.assertIsInstance(uid, ObjectId)
            self.assertNotIsInstance(uid, str)
            self.assertEqual(uid, UID)

    def test_WHY_the_type_matters_is_pinned_in_the_writer(self):
        """_record_client_version filters on the raw value with no
        to_query_id, so a string id would match no document and the write
        would silently do nothing. If this ever gains a conversion, the
        assertion above stops being load-bearing and this says so."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server._record_client_version))))
        self.assertIn("'_id': user_id", code)
        self.assertNotIn("to_query_id", code)

    def test_a_long_version_string_is_truncated_not_rejected(self):
        with _Harness(_user()) as h:
            self.assertEqual(h.sequence("v" * 200), (200, 200))
            self.assertLessEqual(len(h.captured[0][1]), 32)


class WithoutTheHeader(unittest.TestCase):
    """THE HALF THE OLD SUITE ALREADY COVERED, kept so a fix to the other
    half cannot break this one."""

    def test_auth_me_returns_200(self):
        with _Harness(_user()) as h:
            self.assertEqual(h.sequence(None), (200, 200))

    def test_nothing_is_stamped(self):
        with _Harness(_user()) as h:
            h.sequence(None)
            self.assertEqual(h.captured, [])

    def test_an_empty_header_stamps_nothing_either(self):
        with _Harness(_user()) as h:
            self.assertEqual(h.sequence(""), (200, 200))
            self.assertEqual(h.captured, [])


class TheMutationIsWhatMadeItPossible(unittest.TestCase):
    def test_serialize_id_deletes_the_key_it_was_given(self):
        """Stated here because the call site cannot see it."""
        doc = {"_id": UID, "name": "x"}
        out = server.serialize_id(doc)
        self.assertIs(out, doc)
        self.assertNotIn("_id", doc)
        self.assertEqual(doc["id"], str(UID))

    def test_the_id_is_captured_BEFORE_that_call(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.get_current_user))))
        self.assertLess(code.index("user_oid = user.get('_id')"),
                        code.index("user_data = serialize_id(user)"))

    def test_no_read_of_user_id_survives_after_the_call(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.get_current_user))))
        after = code[code.index("user_data = serialize_id(user)"):]
        self.assertNotIn("user['_id']", after)


if __name__ == "__main__":
    unittest.main()
