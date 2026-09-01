"""A correct password must never produce a 500.

WHAT THIS IS ABOUT. create_token builds the JWT payload from values taken
straight off the user document -- email, role, company_id -- and hands them to
jwt.encode, which JSON-serialises them. `sub` is stringified by every caller;
`company_id` is not. The moment one user's company_id is a BSON ObjectId rather
than a string, jwt.encode raises

    TypeError: Object of type ObjectId is not JSON serializable

which nothing catches, so POST /api/auth/login returns 500.

THE SHAPE OF THE BUG IS WHY IT WENT UNNOTICED FOR SIX MONTHS. company_id has
been in the login token since 2026-02-06. It is not a regression and there is
nothing to revert; it is a landmine that arms itself the instant a company_id
stops being a string, which no application writer does -- every one of them
stores str(result.inserted_id). It takes a script or a console edit to arm, and
then it fires only for the users it was armed on.

AND IT FIRES ONLY ON A CORRECT PASSWORD. verify_password runs first and returns
a clean False for a wrong one, so the request 401s long before create_token.
That asymmetry is the sharper half of this finding:

    wrong password, or no such account  ->  401
    CORRECT password                    ->  500

which makes an unauthenticated, public endpoint into an ACCOUNT ENUMERATION AND
CREDENTIAL ORACLE. A 500 is a positive confirmation that the account exists and
that the password just tried was right. An attacker spraying credentials reads
the status code, not the body. This is a live disclosure independent of whether
anybody is locked out, and it is closed here by making token creation not throw
-- NOT by catching exceptions in login and calling them 401, which would bury
genuine server faults as authentication failures.

None IS PRESERVED, AND THAT IS THE POINT OF HALF THESE TESTS. str(None) is
"None" -- a five-character string that looks like a company_id, matches no
company, and fails silently everywhere instead of loudly in one place. A blanket
str() over the payload would be a worse bug than the one being fixed, so the
tests below pin None on every nullable claim.
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bson import ObjectId

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import jwt  # noqa: E402

import server  # noqa: E402

OID = ObjectId("66f0a1b2c3d4e5f60718293a")
OID_STR = "66f0a1b2c3d4e5f60718293a"


def decode(token):
    return jwt.decode(token, server.JWT_SECRET,
                      algorithms=[server.JWT_ALGORITHM])


class AnObjectIdMustNotCrashTokenCreation(unittest.TestCase):
    """The four claims that carry an id. Each one fails pre-fix."""

    def test_company_id(self):
        self.assertEqual(
            decode(server.create_token("u", "e@x.com", "cp",
                                       company_id=OID))["company_id"],
            OID_STR)

    def test_project_id(self):
        self.assertEqual(
            decode(server.create_token("u", "e@x.com", "site_device",
                                       project_id=OID))["project_id"],
            OID_STR)

    def test_sub(self):
        """Callers pass str(user["_id"]) today. Coerced anyway, because the
        one caller that forgets is the one that 500s."""
        self.assertEqual(decode(server.create_token(OID, "e@x.com", "cp"))["sub"],
                         OID_STR)

    def test_the_stringified_id_is_the_SAME_24_hex_stored_elsewhere(self):
        """Not a cosmetic coercion. Every other document stores
        str(inserted_id), so str(ObjectId) is exactly the value downstream
        company_id comparisons already match against."""
        self.assertEqual(str(OID), OID_STR)
        self.assertEqual(len(OID_STR), 24)

    def test_the_WHOLE_payload_is_json_serialisable(self):
        """Guards the next field added to the payload, not just today's four.
        exp/iat are datetimes that PyJWT converts itself, so they are checked
        through jwt.encode rather than json.dumps."""
        token = server.create_token(OID, "e@x.com", "cp",
                                    project_id=OID, company_id=OID)
        claims = decode(token)
        json.dumps(claims)


class NoneIsPreservedNotStringified(unittest.TestCase):
    """PASSES EITHER WAY. These do not detect the bug -- they exist so the fix
    cannot be "str() everything", which would put the literal "None" into a
    claim that every downstream comparison treats as an id."""

    def test_company_id_none(self):
        claims = decode(server.create_token("u", "e@x.com", "cp"))
        self.assertIsNone(claims["company_id"])
        self.assertNotEqual(claims["company_id"], "None")

    def test_project_id_none(self):
        claims = decode(server.create_token("u", "e@x.com", "cp"))
        self.assertIsNone(claims["project_id"])
        self.assertNotEqual(claims["project_id"], "None")

    def test_an_empty_string_stays_an_empty_string(self):
        """"" and None are different states and both reach here."""
        claims = decode(server.create_token("u", "e@x.com", "cp", company_id=""))
        self.assertEqual(claims["company_id"], "")


class TheOtherClaimsAreUnchanged(unittest.TestCase):
    """PASSES EITHER WAY. Proves the fix closed nothing legitimate."""

    def test_a_plain_string_company_id_is_untouched(self):
        claims = decode(server.create_token("u", "e@x.com", "cp",
                                            company_id="68a1b2c3d4e5f60718293a11"))
        self.assertEqual(claims["company_id"], "68a1b2c3d4e5f60718293a11")

    def test_site_mode_stays_a_BOOL(self):
        """It is read as a boolean. "False" is truthy."""
        for value in (True, False):
            claims = decode(server.create_token("u", "e@x.com", "cp",
                                                site_mode=value))
            self.assertIs(claims["site_mode"], value)

    def test_email_and_role_survive(self):
        claims = decode(server.create_token("u", "m@blueviewbuilders.com", "cp"))
        self.assertEqual(claims["email"], "m@blueviewbuilders.com")
        self.assertEqual(claims["role"], "cp")

    def test_exp_and_iat_are_still_there_and_still_verify(self):
        claims = decode(server.create_token("u", "e@x.com", "cp"))
        self.assertIn("exp", claims)
        self.assertIn("iat", claims)
        self.assertGreater(claims["exp"], claims["iat"])

    def test_the_token_still_verifies_against_the_secret(self):
        token = server.create_token("u", "e@x.com", "cp", company_id=OID)
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, "not-the-secret",
                       algorithms=[server.JWT_ALGORITHM])

    def test_a_coerced_role_cannot_ESCALATE(self):
        """str() on a non-string role produces something that matches no role
        check, so the failure mode of coercion is denial, never elevation."""
        claims = decode(server.create_token("u", "e@x.com", ["admin"]))
        self.assertNotEqual(claims["role"], "admin")


class _FakeCollection:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, *a, **k):
        return self.doc

    async def update_one(self, *a, **k):
        return MagicMock()


class _FakeDB:
    def __init__(self, user):
        self.users = _FakeCollection(user)
        self.site_devices = _FakeCollection(None)
        self.projects = _FakeCollection(None)


class TheEnumerationOracleIsClosed(unittest.TestCase):
    """END-TO-END, THROUGH login ITSELF. This is the finding: the status code
    a stranger gets tells them whether the password they tried was correct."""

    PASSWORD = "correct-horse-battery-staple"

    def setUp(self):
        self._real_db = server.db
        self.user = {
            "_id": ObjectId("66f0a1b2c3d4e5f607182999"),
            "email": "m@blueviewbuilders.com",
            "password": server.hash_password(self.PASSWORD),
            "role": "cp",
            "company_id": OID,          # <-- the armed landmine
        }
        server.db = _FakeDB(self.user)

    def tearDown(self):
        server.db = self._real_db

    def _login(self, password):
        req = MagicMock()
        req.client.host = "203.0.113.7"
        creds = server.UserLogin(email=self.user["email"], password=password)
        return asyncio.run(server.login(creds, req, None))

    def test_the_CORRECT_password_returns_a_token_not_a_500(self):
        """PRE-FIX THIS RAISES TypeError, which FastAPI renders as a 500."""
        out = self._login(self.PASSWORD)
        self.assertEqual(decode(out.token)["company_id"], OID_STR)

    def test_a_wrong_password_still_401s(self):
        """PASSES EITHER WAY. The credential check must be untouched."""
        with self.assertRaises(server.HTTPException) as cm:
            self._login("wrong")
        self.assertEqual(cm.exception.status_code, 401)

    def test_BOTH_ANSWERS_ARE_NOW_INDISTINGUISHABLE_TO_A_STRANGER(self):
        """The oracle, stated as one assertion.

        Pre-fix: wrong password raises HTTPException(401), correct password
        raises TypeError(500). Two different observable outcomes for an
        unauthenticated caller, which is the disclosure. Post-fix the only way
        to tell them apart is to hold the right password and read the body.
        """
        try:
            self._login(self.PASSWORD)
            correct = 200
        except server.HTTPException as e:
            correct = e.status_code

        with self.assertRaises(server.HTTPException) as cm:
            self._login("wrong")
        wrong = cm.exception.status_code

        self.assertEqual(correct, 200)
        self.assertEqual(wrong, 401)
        self.assertNotEqual(correct, 500)

    def test_a_user_with_a_STRING_company_id_was_never_affected(self):
        """PASSES EITHER WAY -- and is why only some accounts broke."""
        self.user["company_id"] = OID_STR
        self.assertEqual(decode(self._login(self.PASSWORD).token)["company_id"],
                         OID_STR)

    def test_a_user_with_NO_company_gets_a_null_claim(self):
        """PASSES EITHER WAY. Workers have no company and must keep logging in
        with company_id null -- the case a blanket str() would break."""
        self.user["company_id"] = None
        self.assertIsNone(decode(self._login(self.PASSWORD).token)["company_id"])


if __name__ == "__main__":
    unittest.main()
