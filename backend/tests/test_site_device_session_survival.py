"""A GATE TABLET THAT IS EVER ONLINE MUST NEVER RUN OUT OF SESSION.

JWT_EXPIRATION_HOURS is 720 — thirty days — and there is no refresh route:
`create_token` is called from `POST /api/auth/login` and nowhere else. So the
clock on a site device starts at the one moment somebody typed the kiosk
password into it, and nothing in the product has ever moved it again. Day 31
the tablet wakes up, decides locally that it is expired, and lands on a login
screen whose credentials live in an admin's head, not on the jobsite.

THE MECHANISM HERE IS THE SMALLEST ONE THAT FIXES THAT: every authenticated
request that reaches `get_current_user` with a token older than
JWT_REISSUE_AFTER_HOURS carries a fresh one back in a response header. No new
route, no new state, no second round trip. A device that talks to the API at
all — once a month is enough — never reaches day 30.

AND IT FAILS SAFE, WHICH OUTRANKS THE FEATURE. Every way this can fail —
a payload with no `iat`, an `iat` that is not a number, a `sub` that vanished,
`create_token` itself raising — resolves to "no header", which is byte-for-byte
the behaviour that shipped before it. A re-issue that cannot happen must never
be able to turn a working request into a failed one, because the request it
would break is a CP filing his day. These tests enumerate that sentence.

Run:  python -m pytest backend/tests/test_site_device_session_survival.py
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import jwt  # noqa: E402
import server  # noqa: E402


def _payload(*, age_hours=0.0, **over):
    """A decoded token body, as `jwt.decode` would hand it back."""
    issued = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    body = {
        "sub": "dev1",
        "email": "gate-01",
        "role": "site_device",
        "site_mode": True,
        "project_id": "proj1",
        "company_id": "co_a",
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(hours=server.JWT_EXPIRATION_HOURS)).timestamp()),
    }
    body.update(over)
    return body


def _encode(body):
    return jwt.encode(body, server.JWT_SECRET, algorithm=server.JWT_ALGORITHM)


def _decode(token):
    return jwt.decode(token, server.JWT_SECRET, algorithms=[server.JWT_ALGORITHM])


# ── The re-issue decision ──────────────────────────────────────────────────

class TheTokenIsReissuedBeforeItCanRunOut(unittest.TestCase):

    def test_a_fresh_token_is_not_reissued(self):
        """A re-issue per request would re-sign on every read in the product
        and make the device write its credentials to disk hundreds of times a
        day. The device only needs the clock moved forward, not restarted."""
        self.assertIsNone(server._reissue_token_if_stale(_payload(age_hours=1)))

    def test_a_token_older_than_the_threshold_is_reissued(self):
        fresh = server._reissue_token_if_stale(
            _payload(age_hours=server.JWT_REISSUE_AFTER_HOURS + 1))
        self.assertIsNotNone(
            fresh,
            "a device that has been talking to this API for a day still holds "
            "its original 30-day token; nothing else in the product will ever "
            "move that clock")

    def test_the_reissued_token_carries_every_claim_forward(self):
        """A token that comes back missing project_id logs the tablet into a
        session that authenticates and can see nothing — worse than expiring,
        because it looks like it worked."""
        old = _payload(age_hours=200)
        fresh = _decode(server._reissue_token_if_stale(old))
        for claim in ("sub", "email", "role", "site_mode", "project_id", "company_id"):
            self.assertEqual(fresh[claim], old[claim], f"claim {claim} was dropped")

    def test_the_reissued_token_expires_a_full_term_from_now(self):
        old = _payload(age_hours=700)          # 29 days in, about to strand
        fresh = _decode(server._reissue_token_if_stale(old))
        remaining = datetime.fromtimestamp(fresh["exp"], tz=timezone.utc) - \
            datetime.now(timezone.utc)
        self.assertGreater(
            remaining, timedelta(hours=server.JWT_EXPIRATION_HOURS - 1),
            "the point of the exercise is a FULL term from the moment of "
            "contact; a re-issue that inherits the old exp buys nothing")

    def test_site_mode_survives_as_a_boolean(self):
        """`site_mode` is read as a boolean everywhere downstream and the
        string "False" is truthy — the same trap _jwt_claim already documents
        for the nullable claims."""
        fresh = _decode(server._reissue_token_if_stale(
            _payload(age_hours=200, site_mode=False, role="cp")))
        self.assertIs(fresh["site_mode"], False)

    def test_a_null_claim_stays_null_rather_than_becoming_the_string_None(self):
        fresh = _decode(server._reissue_token_if_stale(
            _payload(age_hours=200, company_id=None, project_id=None)))
        self.assertIsNone(fresh["company_id"])
        self.assertIsNone(fresh["project_id"])


class ItFailsSafeOnEveryInputThereIs(unittest.TestCase):
    """Every one of these must answer None. None means "no header", and no
    header is exactly what every deploy did before this existed."""

    def test_no_iat(self):
        body = _payload(age_hours=200)
        del body["iat"]
        self.assertIsNone(server._reissue_token_if_stale(body))

    def test_iat_is_not_a_number(self):
        self.assertIsNone(server._reissue_token_if_stale(
            _payload(age_hours=200, iat="yesterday")))

    def test_iat_is_in_the_future(self):
        """A device with a wrong clock, or a token minted by a server whose
        clock is ahead. Age is negative, so it is not due — and it must not
        crash on the way to deciding that."""
        self.assertIsNone(server._reissue_token_if_stale(_payload(age_hours=-500)))

    def test_no_sub(self):
        self.assertIsNone(server._reissue_token_if_stale(
            _payload(age_hours=200, sub=None)))

    def test_not_a_dict(self):
        for junk in (None, "", [], 7):
            self.assertIsNone(server._reissue_token_if_stale(junk), repr(junk))

    def test_create_token_raising_is_swallowed(self):
        """If signing itself breaks, the request the caller made must still
        succeed. A broken re-issue is a device that expires in 30 days; a
        re-issue that raises is a device that cannot do anything at all."""
        with patch.object(server, "create_token", side_effect=RuntimeError("boom")):
            self.assertIsNone(server._reissue_token_if_stale(_payload(age_hours=200)))


# ── The wiring ─────────────────────────────────────────────────────────────

class ItIsWiredWhereEveryAuthenticatedRequestPassesThrough(unittest.TestCase):

    def test_get_current_user_offers_the_reissue(self):
        body = inspect.getsource(server.get_current_user)
        self.assertIn("_reissue_token_if_stale(", body)

    def test_get_current_user_can_write_a_response_header(self):
        """FastAPI injects the outgoing Response into a dependency that asks
        for one. That is the whole mechanism — no middleware, no new route."""
        params = inspect.signature(server.get_current_user).parameters
        self.assertIn("response", params)
        self.assertIs(params["response"].default, None,
                      "the direct get_current_user(token=...) call paths pass "
                      "no Response; the default has to make that a no-op")

    def test_the_header_is_exposed_through_cors(self):
        """The web build reads response headers through the browser, which
        hides every header not named in Access-Control-Expose-Headers. Ship
        the header without this and the re-issue silently never lands."""
        exposed = None
        for mw in server.app.user_middleware:
            if mw.cls is server.CORSMiddleware:
                exposed = mw.kwargs.get("expose_headers")
        self.assertIsNotNone(exposed, "CORS middleware not found")
        self.assertIn(server.REISSUED_TOKEN_HEADER, exposed)

    def test_the_threshold_is_well_inside_the_term(self):
        """Re-issuing only in the last hour of a 30-day token would mean a
        device has to be online in one specific hour a month."""
        self.assertLess(server.JWT_REISSUE_AFTER_HOURS,
                        server.JWT_EXPIRATION_HOURS / 2)


class ItReachesTheWire(unittest.TestCase):
    """"Returns a string" and "the tablet receives a header it can store" are
    different claims and only the second one matters to the tablet."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(server.app)

    def _device_db(self):
        mock_db = MagicMock()
        mock_db.site_devices = MagicMock()
        mock_db.site_devices.find_one = AsyncMock(return_value={
            "_id": "dev1", "username": "gate-01", "project_id": "proj1",
            "is_active": True,
        })
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(
            return_value={"_id": "proj1", "company_id": "co_a"})
        return mock_db

    def _get_me(self, token):
        with patch.object(server, "db", self._device_db()), \
             patch.object(server, "to_query_id", side_effect=lambda x: x):
            return self.client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    def test_an_aging_device_gets_a_fresh_token_back(self):
        r = self._get_me(_encode(_payload(age_hours=400)))
        self.assertEqual(r.status_code, 200, r.text)
        handed_back = r.headers.get(server.REISSUED_TOKEN_HEADER)
        self.assertTrue(
            handed_back,
            "the tablet asked the API a question and the API had the one "
            "chance it gets to move the clock")
        self.assertEqual(_decode(handed_back)["sub"], "dev1")

    def test_a_device_that_just_logged_in_gets_no_header(self):
        r = self._get_me(_encode(_payload(age_hours=0)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.headers.get(server.REISSUED_TOKEN_HEADER))

    def test_the_token_handed_back_actually_authenticates(self):
        """The round trip, because a re-issued token that the API then
        refuses is a tablet that locks itself out on purpose."""
        first = self._get_me(_encode(_payload(age_hours=400)))
        again = self._get_me(first.headers[server.REISSUED_TOKEN_HEADER])
        self.assertEqual(again.status_code, 200, again.text)

    def test_a_reissue_that_explodes_does_not_break_the_request(self):
        with patch.object(server, "_reissue_token_if_stale",
                          side_effect=RuntimeError("boom")):
            r = self._get_me(_encode(_payload(age_hours=400)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.headers.get(server.REISSUED_TOKEN_HEADER))

    def test_an_expired_token_is_still_refused(self):
        """Survival on the DEVICE is a client-side decision about cached
        reading. The API's own answer to a dead token does not soften."""
        dead = _payload(age_hours=1000)
        dead["exp"] = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        r = self._get_me(_encode(dead))
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(r.headers.get(server.REISSUED_TOKEN_HEADER))


if __name__ == "__main__":
    unittest.main()
