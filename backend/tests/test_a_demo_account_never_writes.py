"""A demo account never writes — and the proof is a census, not a sample.

OPERATOR RULING: "Server rejects every write from a demo account (one guard at
the auth layer, not per route)." Plus: "/onboarding/company refuses demo and
pending now", and restore the password complexity that was cut for demo day.

── WHY THE FIRST TEST IS A CENSUS ─────────────────────────────────────────

A write guard that is checked against three endpoints proves nothing about
the fourth somebody adds next week, and "somebody adds a route and forgets the
decorator" is the exact failure a middleware exists to make impossible. So the
population is not a hand-written list: it is enumerated from `server.app`
itself, every route carrying POST/PUT/PATCH/DELETE, and every one of them is
called with a demo principal's token and required to come back refused.

That census is cheap for the same reason it is strong — the guard
short-circuits ABOVE the router, so no handler runs and no fixture is needed
for 153 different request bodies. What it costs is one line of care: the
exemptions have to be named and justified, not discovered.

── WHAT ELSE IS PINNED HERE ───────────────────────────────────────────────

  * the refusal SHAPE, because a client branches on it
  * the middleware's POSITION in the stack, because a refusal outside CORS is
    a refusal the browser reports as a CORS fault (see the note in
    lib/demo_guard.py)
  * that the DOCUMENT and not the token claim decides, in both directions
  * that the safe paths — sign in, /auth/me, every GET — still work
  * the two DIFFERENT refusals on /onboarding/company, and that a reader can
    tell which one fired
  * the restored password rule, on all three endpoints that write a password
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from lib import demo_guard  # noqa: E402
from lib import rate_limits  # noqa: E402


SAFE = ("GET", "HEAD", "OPTIONS", "TRACE")
NON_SAFE = ("POST", "PUT", "PATCH", "DELETE")

# SPELLED OUT HERE, NOT READ FROM demo_guard.EXEMPT_PATHS.
#
# The census below has to skip the exempt paths, and the obvious way to decide
# which those are is to ask `demo_guard.is_exempt`. That was the first draft
# and it was wrong: adding "/api/projects" to the product's exemption list then
# made the census SKIP /api/projects and stay green while a demo could create
# projects. A census that asks the code under test which rows to count is not
# a census.
#
# So the population is read off the app and the exclusions are written down
# here by hand. Widening the product's list turns this file red twice: once in
# the census, because a route it still expects to be refused is not, and once
# in the equality test that names the same two paths.
EXPECTED_EXEMPT = frozenset({
    "/api/auth/login",
    "/api/auth/register",
})


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────


def _token(role, user_id="demo-user-1", **kw):
    """A REAL token from server's own minter, not a hand-rolled one.

    The guard decodes with the app's secret and algorithm; a token built any
    other way would test the test's idea of a JWT rather than the product's.
    """
    import server
    return server.create_token(user_id, f"{user_id}@example.com", role, **kw)


def _db_returning_user(doc):
    """A db double whose users.find_one answers `doc`.

    `find_one` takes the projection the guard passes as a second positional
    argument; AsyncMock swallows it, which is what we want — this double is
    standing in for Mongo, not re-implementing it.
    """
    db = MagicMock()
    db.users = MagicMock()
    db.users.find_one = AsyncMock(return_value=doc)
    return db


class _Patched:
    """server.db swapped for the duration of a with-block, then restored.

    Written out rather than using monkeypatch so the non-pytest call paths in
    this file (the census loop) can use it too.
    """

    def __init__(self, db):
        self._db = db
        self._orig = None

    def __enter__(self):
        import server
        self._orig = server.db
        server.db = self._db
        return self._db

    def __exit__(self, *exc):
        import server
        server.db = self._orig
        return False


def _client():
    """raise_server_exceptions=False so an EXEMPT route that reaches its
    handler and blows up on a mocked db surfaces as a 500 we can assert about,
    instead of a raised exception that hides whether the guard let it through
    — which is the only thing the exempt half of the census is asking."""
    import server
    return TestClient(server.app, raise_server_exceptions=False)


def _concrete(path: str) -> str:
    """A route template with its placeholders filled in.

    `/api/projects/{project_id}/nfc-tags/{tag_id}` -> `/api/projects/x/nfc-tags/x`.
    A `:path` converter gets a segment too; it matches one just as happily as
    it matches several.
    """
    out = []
    for seg in path.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            out.append("x")
        else:
            out.append(seg)
    return "/".join(out)


def _non_safe_routes():
    """(method, path_template) for every non-safe route the app declares.

    THE POPULATION IS READ OFF THE APP, which is the whole point: a route
    added next week joins this census without anybody editing this file.
    """
    import server
    rows = []
    for route in server.app.routes:
        for method in sorted(getattr(route, "methods", None) or []):
            if method in NON_SAFE:
                rows.append((method, getattr(route, "path", "")))
    return sorted(set(rows))


def _refusal(response):
    """The demo refusal in `response`, or None if it is not one."""
    if response.status_code != 403:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    if body.get("error") != demo_guard.DEMO_REFUSAL_ERROR:
        return None
    return body


# ──────────────────────────────────────────────────────────────────
# 1. THE CENSUS
# ──────────────────────────────────────────────────────────────────


def test_the_app_still_has_non_safe_routes_to_census():
    """The census is only evidence if the population is not empty.

    A `_non_safe_routes()` that silently returned [] would make every
    assertion below vacuously true — an instrument that cannot fail. The
    floor is deliberately far below today's count (153) so an ordinary
    deletion does not trip it; it catches the enumeration BREAKING, not the
    app shrinking.
    """
    rows = _non_safe_routes()
    assert len(rows) > 100, (
        f"only {len(rows)} non-safe routes enumerated — the route walk is "
        f"probably broken, and every census assertion below is vacuous"
    )


def test_no_non_safe_route_is_reachable_by_a_demo_principal():
    """EVERY declared write, refused. Not three of them."""
    import server

    token = _token("demo")
    headers = {"Authorization": f"Bearer {token}"}
    reached = []

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "demo"})):
        client = _client()
        for method, template in _non_safe_routes():
            path = _concrete(template)
            rate_limits.reset_counter()
            response = client.request(method, path, json={}, headers=headers)
            if path in EXPECTED_EXEMPT:
                # The exempt half of the census asserts the OPPOSITE property:
                # the guard let it through. What the handler then did with a
                # mocked db is not this test's business.
                assert _refusal(response) is None, (
                    f"{method} {path} is on the exemption list but was "
                    f"refused as a demo write")
                continue
            if _refusal(response) is None:
                reached.append(
                    f"{method} {template} -> {response.status_code}")

    assert not reached, (
        "a demo principal was NOT refused on these writes:\n  "
        + "\n  ".join(reached))


def test_the_exemption_list_is_exactly_the_two_auth_paths():
    """The list is short and it is checked, because every entry is a hole.

    Stated as an equality and not a superset: a test that only asserts login
    is present would go green on an exemption list that had quietly grown to
    twenty.
    """
    assert demo_guard.EXEMPT_PATHS == EXPECTED_EXEMPT


def test_every_exempt_path_is_a_real_route():
    """An exemption for a path that does not exist is a dead entry that reads
    as protection. (The forgot/reset-password routes are exactly such a
    temptation — lib/rate_limits.py carries config for two of them that have
    never been built.)"""
    declared = {path for _m, path in _non_safe_routes()}
    for path in demo_guard.EXEMPT_PATHS:
        assert path in declared, (
            f"{path} is exempted from the demo write guard but is not a "
            f"non-safe route in this app")


# ──────────────────────────────────────────────────────────────────
# 2. THE REFUSAL SHAPE
# ──────────────────────────────────────────────────────────────────


def test_the_refusal_shape_is_stable():
    """The client raises "Demo mode, nothing is saved" off this body. It is a
    contract, so it is spelled out here in full rather than probed field by
    field — a new key is fine, a renamed one is a broken toast."""
    import server

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "demo"})):
        rate_limits.reset_counter()
        client = _client()
        response = client.post(
            "/api/projects", json={},
            headers={"Authorization": f"Bearer {_token('demo')}"})

    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "demo_read_only"
    assert body["detail"] == "Demo mode, nothing is saved."
    assert body["method"] == "POST"
    assert body["path"] == "/api/projects"


def test_the_refusal_is_flat_and_not_nested_under_detail():
    """`require_approved` answers {"detail": {"error": ...}} and the limiter
    answers {"error": ...}. This one is the limiter's shape, for the reason in
    the module docstring — and a client reading `data.detail` for a message to
    show gets a SENTENCE here, not a dict it would render as [object Object].
    """
    body = demo_guard.refusal_body("DELETE", "/api/workers/7")
    assert isinstance(body["detail"], str)
    assert body["error"] == "demo_read_only"


def test_the_refusal_carries_cors_headers():
    """OUTSIDE THIS, THE TOAST CANNOT FIRE. A short-circuited response that
    does not pass back out through CORS reaches the browser as "Response to
    preflight request doesn't pass access control check" — the exact failure
    the CORS block in server.py was reordered to fix for the 429. Same trap,
    same fix, so it gets the same test."""
    import server

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "demo"})):
        rate_limits.reset_counter()
        client = _client()
        response = client.post(
            "/api/projects", json={},
            headers={
                "Authorization": f"Bearer {_token('demo')}",
                "Origin": "https://levelog.com",
            })

    assert response.status_code == 403
    assert response.headers.get("access-control-allow-origin") == \
        "https://levelog.com"


def test_the_guard_sits_inside_cors_and_inside_the_rate_limiter():
    """Position, asserted directly rather than inferred from a header.

    Starlette's `user_middleware` is ordered outermost-first. CORS must come
    before this guard (so refusals leave through it) and the rate limiter must
    too (so a flood is throttled before it reaches this guard's db read).
    """
    import server

    names = [m.cls.__name__ for m in server.app.user_middleware]
    assert "DemoWriteGuardMiddleware" in names, \
        "the demo write guard is not installed at all"
    guard = names.index("DemoWriteGuardMiddleware")
    assert names.index("CountingCORSMiddleware") < guard, \
        "the demo guard is OUTSIDE CORS — its 403 will read as a CORS failure"
    assert names.index("RateLimitMiddleware") < guard, \
        "the demo guard is outside the rate limiter — its db read is unthrottled"


# ──────────────────────────────────────────────────────────────────
# 3. THE SAFE PATHS — a demo that cannot sign in is not a demo
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", SAFE)
def test_safe_methods_are_never_refused(method):
    assert not demo_guard.is_write(method)


def test_an_unknown_verb_is_treated_as_a_write():
    """The default for a method nobody has thought about, on a security
    boundary, is refuse. A deny-list would admit it."""
    assert demo_guard.is_write("REPORT")
    assert demo_guard.is_write("")


def test_login_is_not_refused_even_with_a_stale_demo_token_attached():
    """THE TRAP THIS CLOSES. frontend/src/utils/api.js attaches the stored
    token to EVERY request, so a phone whose last session was a demo sends
    that demo's JWT to the login screen. Without the exemption the guard would
    refuse the sign-in of the REAL account the person is reaching for, and the
    product would look like it lets nobody in."""
    import server

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "demo"})):
        rate_limits.reset_counter()
        client = _client()
        response = client.post(
            "/api/auth/login",
            json={"email": "someone@example.com", "password": "Passw0rdy"},
            headers={"Authorization": f"Bearer {_token('demo')}"})

    assert _refusal(response) is None, (
        "the demo write guard refused a LOGIN — a demo account that cannot "
        "sign in is not a demo")


def test_auth_me_is_readable_by_a_demo():
    """There is no logout route in this app — logout is client-side
    `clearAuth()` — so /auth/me is the read that stands in for "the session
    still works"."""
    import server

    doc = {"_id": "demo-user-1", "id": "demo-user-1", "role": "demo",
           "email": "d@example.com", "name": "Demo", "account_status": "pending"}
    with _Patched(_db_returning_user(doc)):
        rate_limits.reset_counter()
        client = _client()
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_token('demo')}"})

    assert _refusal(response) is None
    assert response.status_code != 403


# ──────────────────────────────────────────────────────────────────
# 4. WHAT DECIDES "IS A DEMO" — the document, not the claim
# ──────────────────────────────────────────────────────────────────


def test_a_promoted_demo_may_write_on_a_token_that_still_says_demo():
    """THE DRIFT THAT MATTERS. A demo the operator upgrades to a paying CP
    keeps a token claiming "demo" for up to thirty days — the term is 720
    hours and `_reissue_token_if_stale` copies the old claims forward instead
    of re-reading the account. Trusting the claim would refuse that customer
    every write until somebody thought to tell him to log out."""
    import server

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "cp"})):
        rate_limits.reset_counter()
        client = _client()
        response = client.post(
            "/api/projects", json={},
            headers={"Authorization": f"Bearer {_token('demo')}"})

    assert _refusal(response) is None, (
        "a promoted account was refused on the strength of a stale role "
        "claim — the document is supposed to decide")


def test_a_demo_document_is_refused_under_a_non_demo_claim():
    """The other direction. No API path can write ROLE_DEMO onto an existing
    account today (it is not in ASSIGNABLE_ROLES), so this covers a seed
    script or a console edit — the cases that do not go through a route."""
    import server

    with _Patched(_db_returning_user({"_id": "demo-user-1", "role": "demo"})):
        rate_limits.reset_counter()
        client = _client()
        response = client.post(
            "/api/projects", json={},
            headers={"Authorization": f"Bearer {_token('cp')}"})

    assert _refusal(response) is not None


def test_a_site_device_is_never_a_demo():
    """The gate tablet is the most write-heavy caller in the product and its
    `sub` is a db.site_devices id. Looking that id up in db.users would find
    nothing and read as "not a demo" by ACCIDENT; the branch is explicit so
    the tablet's safety does not depend on a lookup missing."""
    # The db double answers "demo" for EVERY lookup on purpose: if the site
    # device branch were removed, this test would find that document and the
    # tablet would be refused. Without it, the test would pass on a lookup
    # that merely happened to miss.
    assert _run(_evaluate_with(
        method="POST", path="/api/checkin",
        payload_role="site_device", site_mode=True, user_id="device-1",
        doc={"_id": "device-1", "role": "demo"})) is None, (
        "a site device was treated as a demo principal")


def _evaluate_with(*, method, path, payload_role, doc, site_mode=False,
                   user_id="u1"):
    """Drive lib.demo_guard.evaluate through server's real principal reader.

    Used where a full TestClient round-trip would say less than it costs —
    the site-device branch and the Mongo-outage fallback.
    """
    import server

    token = _token(payload_role, user_id=user_id, site_mode=site_mode)
    request = MagicMock()
    request.headers = {"authorization": f"Bearer {token}"}

    async def _go():
        with _Patched(_db_returning_user(doc)):
            return await demo_guard.evaluate(
                method=method, path=path, request=request,
                jwt_secret=server.JWT_SECRET,
                jwt_algorithm=server.JWT_ALGORITHM,
                demo_principal_check=lambda p:
                    server._demo_write_guard_principal(p),
            )

    return _go()


def test_an_anonymous_write_is_not_the_guards_business():
    """No token: `get_current_user` answers 401 for this request a moment
    later. Refusing here would replace that 401 with a 403 saying "Demo mode,
    nothing is saved" about a request with no account behind it."""
    request = MagicMock()
    request.headers = {}
    import server
    body = _run(demo_guard.evaluate(
        method="POST", path="/api/projects", request=request,
        jwt_secret=server.JWT_SECRET, jwt_algorithm=server.JWT_ALGORITHM,
        demo_principal_check=lambda p: _true()))
    assert body is None


def test_an_undecodable_token_is_not_the_guards_business():
    request = MagicMock()
    request.headers = {"authorization": "Bearer not-a-jwt"}
    import server
    body = _run(demo_guard.evaluate(
        method="POST", path="/api/projects", request=request,
        jwt_secret=server.JWT_SECRET, jwt_algorithm=server.JWT_ALGORITHM,
        demo_principal_check=lambda p: _true()))
    assert body is None


async def _true():
    return True


def test_a_failed_lookup_falls_back_to_the_signed_claim():
    """Mongo unreachable. The claim is weaker but it is AUTHENTIC — this
    server signed it — and for a demo the honest answer is still refusal. It
    can deny a real customer nothing they could otherwise have done: if this
    read failed, the write behind it was going to fail too."""
    import server

    db = MagicMock()
    db.users = MagicMock()
    db.users.find_one = AsyncMock(side_effect=RuntimeError("mongo is down"))

    async def _go():
        with _Patched(db):
            demo = await server._demo_write_guard_principal(
                {"sub": "u1", "role": "demo"})
            real = await server._demo_write_guard_principal(
                {"sub": "u1", "role": "cp"})
            return demo, real

    demo, real = _run(_go())
    assert demo is True
    assert real is False


def test_a_vanished_user_is_not_a_demo():
    import server

    async def _go():
        with _Patched(_db_returning_user(None)):
            return await server._demo_write_guard_principal(
                {"sub": "gone", "role": "demo"})

    assert _run(_go()) is False


# ──────────────────────────────────────────────────────────────────
# 5. /onboarding/company — two refusals, two reasons
# ──────────────────────────────────────────────────────────────────


def _onboarding_client(user, db=None):
    """A client whose get_current_user is `user`, and NO Authorization header.

    The header is deliberately absent so the MIDDLEWARE no-ops and the route's
    OWN gates are what answers. That is the point of these four tests: the
    route has to be correct on its own, because the middleware is one object
    registered in one place and its failure mode is not being there.
    """
    import server

    async def _fake_user():
        return user

    orig_db = server.db
    if db is not None:
        server.db = db
    server.app.dependency_overrides[server.get_current_user] = _fake_user

    def _restore():
        server.db = orig_db
        server.app.dependency_overrides.clear()

    return TestClient(server.app), _restore


def test_onboarding_company_refuses_a_demo():
    demo = {"id": "u1", "role": "demo", "account_status": "approved",
            "onboarding_step": "1"}
    client, restore = _onboarding_client(demo)
    try:
        rate_limits.reset_counter()
        r = client.post("/api/onboarding/company", json={"name": "Acme"})
    finally:
        restore()
    assert r.status_code == 403
    assert r.json()["error"] == "demo_read_only"


def test_onboarding_company_refuses_a_pending_account():
    """THE LIVE HOLE. In production a pending account completed onboarding and
    owns a company, because this route carried no `require_approved` at all.
    Approval is meant to be the moment a human says this account may exist as
    a tenant; it was being granted by the signup form."""
    pending = {"id": "u1", "role": "cp", "account_status": "pending",
               "onboarding_step": "1"}
    client, restore = _onboarding_client(pending)
    try:
        rate_limits.reset_counter()
        r = client.post("/api/onboarding/company", json={"name": "Acme"})
    finally:
        restore()
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "account_pending"}


def test_the_two_onboarding_refusals_are_told_apart():
    """Two different refusals with two different reasons — the person reading
    the error must be able to say which happened. Asserted as an INEQUALITY so
    a future edit that collapses them into one message goes red."""
    demo = {"id": "u1", "role": "demo", "account_status": "approved",
            "onboarding_step": "1"}
    pending = {"id": "u2", "role": "cp", "account_status": "pending",
               "onboarding_step": "1"}

    bodies = []
    for user in (demo, pending):
        client, restore = _onboarding_client(user)
        try:
            rate_limits.reset_counter()
            bodies.append(client.post(
                "/api/onboarding/company", json={"name": "Acme"}).json())
        finally:
            restore()

    assert bodies[0] != bodies[1]
    assert bodies[0].get("error") == "demo_read_only"
    assert bodies[1].get("detail") == {"error": "account_pending"}


def test_onboarding_company_still_works_for_an_approved_non_demo():
    """THE GATE HAS TO LET SOMEBODY THROUGH. A refusal test pair passes just
    as happily on a route that refuses everyone, which is a route that has
    been broken rather than gated."""
    import server

    db = MagicMock()
    db.companies = MagicMock()
    db.companies.find_one = AsyncMock(return_value=None)
    db.companies.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="c1"))
    db.users = MagicMock()
    db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    approved = {"id": "u1", "role": "cp", "account_status": "approved",
                "onboarding_step": "1"}
    client, restore = _onboarding_client(approved, db=db)
    try:
        rate_limits.reset_counter()
        r = client.post("/api/onboarding/company", json={"name": "Acme"})
    finally:
        restore()

    assert r.status_code == 200, r.text
    assert r.json()["company_id"] == "c1"


# ──────────────────────────────────────────────────────────────────
# 6. THE PASSWORD RULE, RESTORED
# ──────────────────────────────────────────────────────────────────


WEAK = [
    ("", "empty"),
    ("abc1", "under eight"),
    ("abcdefg1", None),          # exactly eight — the boundary, ACCEPTED
    ("abcdefgh", "no digit"),
    ("12345678", "no letter"),
    ("       1", "no letter, spaces are not letters"),
]


@pytest.mark.parametrize("pwd,why", [(p, w) for p, w in WEAK if w])
def test_the_password_rule_refuses(pwd, why):
    import server
    with pytest.raises(HTTPException) as ei:
        server.assert_password_complexity(pwd)
    assert ei.value.status_code == 422, why


def test_the_password_rule_accepts_eight_with_a_letter_and_a_digit():
    import server
    assert server.assert_password_complexity("abcdefg1") == "abcdefg1"


def test_the_password_rule_accepts_a_non_ascii_alphabet():
    """"пароль1234" is a letter-and-digit password. Restricting the letter
    class to ascii_letters would refuse a strong password for being written in
    the wrong alphabet, which is not a security property."""
    import server
    assert server.assert_password_complexity("пароль1234")


def test_the_empty_message_names_the_field_it_came_from():
    """PUT /auth/password has two password boxes on the form in front of it;
    telling somebody changing their password that a "Password" is required
    points at the wrong one."""
    import server
    with pytest.raises(HTTPException) as ei:
        server.assert_password_complexity("", field="New password")
    assert ei.value.detail == "New password is required"


def test_register_refuses_a_weak_password_before_it_touches_the_database():
    """BEFORE the email lookup and before bcrypt, so a refused password costs
    no query and no hash round."""
    import server

    db = MagicMock()
    db.users = MagicMock()
    db.users.find_one = AsyncMock(return_value=None)
    db.users.insert_one = AsyncMock(return_value=MagicMock(inserted_id="x"))

    async def _go():
        with _Patched(db):
            with pytest.raises(HTTPException) as ei:
                await server.register(server.UserCreate(
                    email="new@example.com", password="pw", name="New"),
                    request=None)
            return ei.value

    err = _run(_go())
    assert err.status_code == 422
    assert not db.users.find_one.await_count
    assert not db.users.insert_one.await_count


def test_every_password_writer_that_carried_the_regression_now_checks():
    """THREE COPIES WERE CUT, NOT ONE. `register`, `PUT /auth/password` and
    `POST /admin/users` each carried the identical "SECURITY REGRESSION
    (intentional, temporary) ... restore before production rollout" comment.
    Restoring one and leaving two is how a hole survives the fix that was
    supposed to close it, so all three call the one validator — asserted by
    calling each of them with a weak password, not by reading the source.
    """
    import server

    results = {}

    async def _go():
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value={
            "_id": "u1", "id": "u1", "role": "admin",
            "password": server.hash_password("Current1pass"),
        })
        db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        with _Patched(db):
            try:
                await server.register(server.UserCreate(
                    email="a@example.com", password="weak", name="A"),
                    request=None)
                results["register"] = "ACCEPTED"
            except HTTPException as e:
                results["register"] = e.status_code

            try:
                await server.create_admin_user(
                    server.UserCreate(email="b@example.com", password="weak",
                                      name="B", role="cp"),
                    admin={"id": "u1", "role": "admin",
                           "company_id": "c1"})
                results["create_admin_user"] = "ACCEPTED"
            except HTTPException as e:
                results["create_admin_user"] = e.status_code

            try:
                await server.update_password(
                    server.UpdatePasswordRequest(
                        current_password="Current1pass", new_password="weak"),
                    current_user={"id": "u1", "role": "admin"})
                results["update_password"] = "ACCEPTED"
            except HTTPException as e:
                results["update_password"] = e.status_code

    _run(_go())

    assert results == {
        "register": 422,
        "create_admin_user": 422,
        "update_password": 422,
    }, results
