"""A demo account reads fiction — and the proof is that the database explodes.

OPERATOR RULING: "Real admin screens, rendered from canned payloads. Not only
/demo/*. Every other endpoint returns an empty or canned result, never real
data. Test: a demo token hitting every GET route returns zero real documents
(route census, not a sample)."

── HOW THIS FILE PROVES "ZERO REAL DOCUMENTS" ─────────────────────────────

Not by reading the bodies and looking for something that seems real. A body
check can only catch the leaks somebody imagined, and it goes green on a route
that returned a real row this test did not know how to recognise.

So the census swaps `server.db` for an object that RAISES on contact with any
collection except `users`, and then asks every declared GET route, with a demo
token, for its answer. If one handler had run, it would have touched a
collection and the double would have said so by name. Zero real documents is
therefore not a property of the assertions below — it is a property of there
having been no documents available to return.

`users` is the one exception and it is not a hole: deciding "is this caller a
demo" is a read of the caller's own user row, which is the design
lib/demo_guard.py established for writes and lib/demo_provider.py reuses. The
double records every `users` query and a test asserts each one is scoped to
the caller's own `_id`.

── WHY THE POPULATION IS READ OFF THE APP, AND THE EXPECTATIONS ARE NOT ───

The same lesson test_a_demo_account_never_writes.py paid for. Its first draft
asked `demo_guard.is_exempt()` which routes to skip, so adding a route to the
product's exemption list made the census skip it and stay green. A census that
asks the code under test which rows to count is not a census.

So: routes come from `server.app`, and nothing in this file imports
`demo_provider.CANNED` to decide what to expect. The allow-list is written out
by hand below and asserted equal to the product's, which turns any widening
red in two places at once.

── WHAT ELSE IS PINNED HERE ───────────────────────────────────────────────

  * that a REAL account is never intercepted — without which a provider that
    blanked the whole product would pass the census perfectly
  * that the interception is STRUCTURAL: no `call_next` is reachable from the
    demo branch, asserted on behaviour and again on the module's syntax tree
  * the empty SHAPES, derived from server.py's own returns rather than
    remembered
  * that /auth/me still answers a demo with their own account, minus secrets,
    and answers it IDENTICALLY to the real handler
  * the plan placeholder: a real, parseable PDF that says it is a demo
  * that the read guard and the write guard never disagree about one account
"""

import ast
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
from fastapi.testclient import TestClient  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from lib import demo_provider  # noqa: E402
from lib import rate_limits  # noqa: E402


# THE ALLOW-LIST, SPELLED OUT. Not imported from demo_provider.CANNED and then
# compared with itself — that is the census-consults-its-subject mistake in
# miniature. Adding a route to the product's table turns
# `test_the_allow_list_is_exactly_the_demo_project_set` red until somebody
# writes it here too and says why, which is the only review this table gets.
#
# This is the "_DEMO_PROJECT set" the ruling names: one project, its logbooks,
# its crew, its day at the gate, its DOB record, its documents — plus the
# three that are not fiction about a project at all, each justified where it is
# built: /auth/me (the caller's OWN account; an empty one is a demo that cannot
# start), the plan placeholder (an operator decision, not a 404), and
# /logbook-types (the product's own static registry, holding no tenant data and
# reading no collection, canned through an accessor so a demo's logbook screens
# carry the product's labels instead of title-cased keys).
EXPECTED_CANNED = frozenset({
    "/api/auth/me",
    "/api/logbook-types",
    "/api/projects",
    "/api/projects/{project_id}",
    "/api/demo/project",
    "/api/projects/{project_id}/required-logbooks",
    "/api/projects/{project_id}/dob-logs",
    "/api/projects/dob-summary",
    "/api/projects/{project_id}/dropbox-files",
    "/api/projects/{project_id}/files/{file_id}/content",
    "/api/logbooks/project/{project_id}",
    "/api/logbooks/{logbook_id}",
    "/api/workers",
    "/api/workers/{worker_id}",
    "/api/workers/{worker_id}/certifications",
    "/api/checkins",
    "/api/checkins/project/{project_id}",
})

DEMO_USER_ID = "demo-user-1"

# A demo's row, with a secret on it. The secret is here so the /auth/me test is
# about something: a document with no password_hash cannot prove the strip.
DEMO_DOC = {
    "_id": DEMO_USER_ID,
    "role": "demo",
    "email": "dana@demo.example",
    "name": "Dana Demo",
    "company_id": None,
    "onboarding_step": "completed",
    "password_hash": "THIS-MUST-NEVER-REACH-A-CLIENT",
}


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────


def _token(role, user_id=DEMO_USER_ID, **kw):
    """A REAL token from server's own minter. The provider decodes with the
    app's secret; a hand-rolled JWT would test this file's idea of one."""
    import server
    return server.create_token(user_id, f"{user_id}@example.com", role, **kw)


class ExplodingDB:
    """A database that answers `users` and RAISES for everything else.

    THIS OBJECT IS THE WHOLE CENSUS. A MagicMock would have absorbed every
    query silently and returned a Mock, so a handler that ran would have
    produced a 200 full of Mock repr and the census would have called it
    "not real data". Raising is what makes "no handler ran" observable.

    It covers BOTH spellings server.py uses — `db.projects` and
    `db["some_collection"]` — because a guard that only watches one of them is
    a guard a handler walks around.
    """

    def __init__(self, user_doc=None):
        self.touched = []        # collections other than users
        self.users_queries = []  # every filter passed to users.find_one
        self._user_doc = user_doc

        users = MagicMock()

        async def _find_one(*args, **kwargs):
            self.users_queries.append(args[0] if args else None)
            return dict(self._user_doc) if self._user_doc else None

        users.find_one = _find_one
        self._users = users

    def _refuse(self, name):
        self.touched.append(name)
        raise AssertionError(
            f"a demo request reached db.{name} — a route handler ran, which "
            f"means the demo read provider did not intercept it")

    def __getattr__(self, name):
        if name == "users":
            return self.__dict__["_users"]
        return self._refuse(name)

    def __getitem__(self, name):
        if name == "users":
            return self._users
        return self._refuse(name)


class Patched:
    """server.db swapped for the duration of a with-block, then restored.

    Written out rather than using monkeypatch so the census loop — which is
    not a pytest fixture consumer — can use it too. Same shape as the one in
    test_a_demo_account_never_writes.py, deliberately.
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
    """raise_server_exceptions=False so a route that DOES reach a handler and
    hits ExplodingDB comes back as a 500 this file can name, instead of an
    exception that aborts the census on its first bad row."""
    import server
    return TestClient(server.app, raise_server_exceptions=False)


def _concrete(path: str) -> str:
    """A route template with its placeholders filled in.

    The filler is "x" and NOT "demo": a census whose ids all happened to be
    the one id the fiction knows would be measuring the canned path only. "x"
    is the id of nothing, which is the case that has to stay empty.
    """
    out = []
    for seg in path.split("/"):
        out.append("x" if seg.startswith("{") and seg.endswith("}") else seg)
    return "/".join(out)


def _get_routes():
    """Every GET route template the app declares.

    THE POPULATION IS READ OFF THE APP. A route added next week joins this
    census without anybody editing this file — which is the only reason the
    census means anything about next week.
    """
    import server
    rows = []
    for route in server.app.routes:
        if "GET" in (getattr(route, "methods", None) or ()):
            rows.append(getattr(route, "path", ""))
    return sorted(set(rows))


# ──────────────────────────────────────────────────────────────────
# 1. THE CENSUS
# ──────────────────────────────────────────────────────────────────


def test_the_app_still_has_get_routes_to_census():
    """The census is only evidence if the population is not empty.

    A `_get_routes()` that silently returned [] would make every assertion
    below vacuously true. The floor is far below today's count (172) so an
    ordinary deletion does not trip it; it catches the ENUMERATION breaking.
    """
    rows = _get_routes()
    assert len(rows) > 100, (
        f"only {len(rows)} GET routes enumerated — the route walk is probably "
        f"broken, and every census assertion below is vacuous")


def test_no_get_route_reaches_the_database_for_a_demo_principal():
    """EVERY declared GET, and not one of them touches a collection.

    This is the ruling's test. It does not inspect bodies for things that look
    real, because it does not have to: the database raises, so a handler that
    ran would have left its collection's name in `touched` or produced a 500.
    """
    headers = {"Authorization": f"Bearer {_token('demo')}"}
    db = ExplodingDB(DEMO_DOC)
    failures = []

    with Patched(db):
        client = _client()
        for template in _get_routes():
            path = _concrete(template)
            rate_limits.reset_counter()
            response = client.get(path, headers=headers)
            if response.status_code >= 500:
                failures.append(
                    f"{template} -> {response.status_code} (a handler ran)")

    assert not db.touched, (
        "a demo GET reached these collections, which means a real handler "
        "executed:\n  " + "\n  ".join(sorted(set(db.touched))))
    assert not failures, (
        "these GET routes did not come back cleanly for a demo:\n  "
        + "\n  ".join(failures))


def test_the_only_collection_a_demo_get_reads_is_its_own_user_row():
    """The one query that IS allowed, pinned to its scope.

    `users` is exempt from the exploding double because deciding "is a demo"
    is a read of the caller's own row. That exemption would be worth nothing
    if the provider could use it to read SOMEBODY ELSE's row, so every filter
    the census produced is checked for the caller's own id.
    """
    headers = {"Authorization": f"Bearer {_token('demo')}"}
    db = ExplodingDB(DEMO_DOC)

    with Patched(db):
        client = _client()
        for template in _get_routes()[:25]:
            rate_limits.reset_counter()
            client.get(_concrete(template), headers=headers)

    assert db.users_queries, (
        "no users lookup happened at all — the provider is deciding from the "
        "token claim, not the document, and a promoted demo would be stuck")
    import server
    want = server.to_query_id(DEMO_USER_ID)
    for q in db.users_queries:
        assert isinstance(q, dict) and q.get("_id") == want, (
            f"a demo GET queried users with {q!r}, which is not scoped to the "
            f"caller's own document")


def _is_empty_answer(body) -> bool:
    """Is this body carrying zero rows?

    "EMPTY" IS NOT "len() == 0", and that distinction is the point of the
    EMPTY_SHAPES table. A pagination envelope with no rows has five keys and
    is as empty as `[]`; the ruling's own words are that the two are not
    interchangeable. So this recognises all three legitimate forms and
    nothing else:

        {}                              the default
        []                              a bare-list route
        {items: [], total: 0, ...}      a paginated route
        {"detail": ...}                 FastAPI's own refusal body

    `null` is deliberately not among them.
    """
    if body is None:
        return False
    if isinstance(body, list):
        return len(body) == 0
    if not isinstance(body, dict):
        return False
    if len(body) == 0:
        return True
    if set(body) <= {"detail"}:
        return True
    if set(body) == {"items", "total", "limit", "skip", "has_more"}:
        return body["items"] == [] and body["total"] == 0
    return False


def test_an_unlisted_get_returns_an_empty_shape_and_never_null():
    """The routes with no canned payload still have to answer something a
    screen can render, and it has to carry zero rows."""
    import json
    headers = {"Authorization": f"Bearer {_token('demo')}"}
    db = ExplodingDB(DEMO_DOC)
    bad = []

    with Patched(db):
        client = _client()
        for template in _get_routes():
            if template in EXPECTED_CANNED:
                continue
            rate_limits.reset_counter()
            r = client.get(_concrete(template), headers=headers)
            if not r.content:
                continue  # a 204/HEAD-ish empty body is not a null
            try:
                body = json.loads(r.content)
            except ValueError:
                bad.append(f"{template} -> non-JSON body")
                continue
            if not _is_empty_answer(body):
                shown = sorted(body)[:6] if isinstance(body, dict) else body
                bad.append(f"{template} -> not empty: {shown}")

    assert not bad, (
        "unlisted GET routes answered a demo with something other than an "
        "empty shape:\n  " + "\n  ".join(bad))


# ──────────────────────────────────────────────────────────────────
# 2. THE MIRROR — a provider that blanked the product would pass above
# ──────────────────────────────────────────────────────────────────


def test_no_get_route_is_intercepted_for_a_real_account():
    """THE CENSUS IS NOT EVIDENCE WITHOUT THIS.

    A provider that intercepted EVERY authenticated GET would satisfy every
    assertion above — 172 routes, no database contact, all green, product
    dead. Most of the backend suite cannot catch that either, because it
    overrides `get_current_user` and sends no Authorization header at all, so
    this middleware never engages for those tests.

    ── WHY THIS ONE DOES NOT GO THROUGH THE APP ────────────────────────────

    The demo census can drive real HTTP because the provider short-circuits
    ABOVE the router and not one of its 172 requests reaches a handler. The
    mirror is the opposite by construction: every request it makes is meant to
    get PAST the provider, so a full-stack version would execute 172 handlers
    against a mock database. test_a_demo_account_never_writes.py records what
    that cost the last time somebody tried it — a reproducible failure in
    test_a_filed_record_opens_without_a_login.py, whose one-second expiry
    margin is sensitive to anything that slows the process down.

    So the sweep asks the DECISION directly, and the wiring is proved
    separately by the test below on a path that matches no route.
    """
    import server

    request = MagicMock()
    request.headers = {
        "authorization": f"Bearer {_token('cp', user_id='cp-user-1')}"}
    intercepted = []

    async def _sweep():
        with Patched(ExplodingDB({"_id": "cp-user-1", "role": "cp"})):
            templates = _get_routes()
            for template in templates:
                answer = await demo_provider.evaluate(
                    method="GET", path=_concrete(template), request=request,
                    query={}, today="2026-09-17",
                    jwt_secret=server.JWT_SECRET,
                    jwt_algorithm=server.JWT_ALGORITHM,
                    demo_principal_document=server._demo_principal_document,
                    templates=templates,
                )
                if answer is not None:
                    intercepted.append(template)

    _run(_sweep())

    assert not intercepted, (
        "the demo read provider intercepted a REAL account on these GETs:\n  "
        + "\n  ".join(intercepted))


def test_the_middleware_is_wired_in_both_directions():
    """THE SWEEP ABOVE TESTS A FUNCTION; THIS TESTS THAT IT IS INSTALLED.

    Both halves run against a path that matches NO route, which is the point:
    the provider acts before routing, so the demo arm proves it is in the
    stack and the real arm proves a live account still reaches the router's
    404 — and neither executes a line of application code.
    """
    with Patched(ExplodingDB(DEMO_DOC)):
        rate_limits.reset_counter()
        demo = _client().get(
            "/api/__no_such_route__",
            headers={"Authorization": f"Bearer {_token('demo')}"})

    with Patched(ExplodingDB({"_id": "cp-user-1", "role": "cp"})):
        rate_limits.reset_counter()
        real = _client().get(
            "/api/__no_such_route__",
            headers={"Authorization":
                     f"Bearer {_token('cp', user_id='cp-user-1')}"})

    assert demo.status_code == 200 and demo.json() == {}, (
        f"the provider is not installed — a demo GET reached the router "
        f"({demo.status_code} {demo.text[:120]})")
    assert real.status_code == 404, (
        f"a real account was not let through to the router (got "
        f"{real.status_code})")


def test_an_anonymous_get_is_not_this_modules_business():
    """No Authorization header, no lookup, no interception.

    The gate pages, the public share links and the health probes are all
    anonymous GETs. Answering them with canned fiction would turn every
    unauthenticated request in the app into a demo.
    """
    with Patched(ExplodingDB(DEMO_DOC)) as db:
        rate_limits.reset_counter()
        r = _client().get("/api/__no_such_route__")
    assert r.status_code == 404
    assert db.users_queries == [], \
        "an anonymous GET cost a users lookup it did not need"


def test_an_undecodable_token_is_not_this_modules_business():
    """A junk token gets `get_current_user`'s 401, not an empty demo body.

    Answering fiction here would replace every "your session expired" in the
    app with a silently empty screen.
    """
    with Patched(ExplodingDB(DEMO_DOC)):
        rate_limits.reset_counter()
        r = _client().get("/api/__no_such_route__",
                          headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 404, \
        "an undecodable token was treated as a demo principal"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_is_not_this_modules_business(method):
    """The write half is lib/demo_guard.py's. This module must not answer a
    POST with a canned 200 — that would tell a demo its write succeeded."""
    import server
    request = MagicMock()
    request.headers = {"authorization": f"Bearer {_token('demo')}"}

    async def _go():
        with Patched(ExplodingDB(DEMO_DOC)):
            return await demo_provider.evaluate(
                method=method, path="/api/projects", request=request,
                query={}, today="2026-09-17",
                jwt_secret=server.JWT_SECRET,
                jwt_algorithm=server.JWT_ALGORITHM,
                demo_principal_document=server._demo_principal_document,
                templates=_get_routes())

    assert _run(_go()) is None, \
        f"{method} was answered by the READ provider"


def test_an_options_preflight_is_never_intercepted():
    """A CORS preflight must reach the CORS layer's own handler. Answering it
    here breaks the browser's check on every demo request, which reads as
    "the API is down" rather than as anything about demos."""
    assert "OPTIONS" not in demo_provider.READ_METHODS


# ──────────────────────────────────────────────────────────────────
# 3. THE INTERCEPTION IS STRUCTURAL, NOT A LIST
# ──────────────────────────────────────────────────────────────────


def test_the_demo_branch_has_no_path_to_call_next():
    """The safety property, read off the module's syntax tree.

    The behavioural proof is the census, and it is the stronger of the two.
    This one is here for the change that has not happened yet: somebody adding
    an `if path in SOMETHING: return await call_next(request)` to let one
    route through "just for now". The census would catch that only if the
    route it let through happened to read a collection; this catches it on
    sight.

    `call_next` must be awaited exactly once in the module, and that one call
    must be guarded by the answer being None — the value `evaluate` returns
    only for a caller it has established is not a demo.
    """
    src = Path(demo_provider.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "call_next"]
    assert len(calls) == 1, (
        f"{len(calls)} call_next calls in demo_provider — there must be "
        f"exactly one, and it must be the non-demo pass-through")

    # The one call sits inside `if answer is None:` and nothing else.
    guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if any(c is calls[0] for c in ast.walk(node)):
            guards.append(ast.unparse(node.test))
    assert "answer is None" in guards, (
        f"call_next is not guarded by `answer is None`; its guards are "
        f"{guards!r}. A demo request can reach the router.")


def test_the_provider_makes_no_network_or_storage_call():
    """ZERO EXTERNAL SPEND, asserted on the one module that runs for a demo.

    The property mostly falls out of the shape — a paid call lives inside a
    handler and no handler runs — but this module is the code that DOES run,
    so it is the one place a vision client could be added by hand.
    """
    src = Path(demo_provider.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"requests", "httpx", "boto3", "botocore", "aiohttp", "urllib",
              "smtplib", "socket", "motor", "pymongo"}
    assert not (imported & banned), (
        f"demo_provider imports {sorted(imported & banned)} — a demo request "
        f"must not reach the network, storage or a database")


def test_the_provider_sits_inside_cors_and_inside_the_rate_limiter():
    """Position in the stack, for lib/demo_guard.py's two recorded reasons: a
    short-circuit outside CORS loses Access-Control-Allow-Origin and the
    browser reports a CORS fault instead of the real status, and a layer that
    reads Mongo must not be reachable faster than the limiter permits."""
    import server
    names = [m.cls.__name__ for m in server.app.user_middleware]
    assert "DemoReadProviderMiddleware" in names, \
        "the demo read provider is not installed at all"
    provider = names.index("DemoReadProviderMiddleware")
    assert names.index("CountingCORSMiddleware") < provider, \
        "the read provider is OUTSIDE CORS; its responses lose CORS headers"
    assert names.index("RateLimitMiddleware") < provider, \
        "the read provider is outside the rate limiter, and it reads db.users"


# ──────────────────────────────────────────────────────────────────
# 4. THE TABLES
# ──────────────────────────────────────────────────────────────────


def test_the_allow_list_is_exactly_the_demo_project_set():
    """Stated as an equality, not a superset.

    A test that only asserted /api/projects was present would go green on an
    allow-list that had quietly grown to forty — and every entry on it is a
    route serving canned data where a reader would expect the real handler.
    """
    assert set(demo_provider.CANNED) == EXPECTED_CANNED


def test_every_canned_route_is_a_real_get_route():
    """An entry for a path that does not exist is a dead line that reads as
    coverage — and, worse here, a typo'd template silently demotes a canned
    screen to the empty default."""
    declared = set(_get_routes())
    for template in demo_provider.CANNED:
        assert template in declared, (
            f"{template} has a canned demo payload but is not a GET route in "
            f"this app")


def test_every_empty_shape_is_a_real_get_route():
    declared = set(_get_routes())
    for template in demo_provider.EMPTY_SHAPES:
        assert template in declared, (
            f"{template} has a demo empty shape but is not a GET route")


def test_no_route_is_in_both_tables():
    """CANNED wins in `payload_for`, so an overlap is a shape entry that can
    never fire — dead, and misleading to the next reader."""
    assert not (set(demo_provider.CANNED) & set(demo_provider.EMPTY_SHAPES))


# ── The empty shapes, DERIVED from server.py rather than remembered ────────
#
# A route whose real answer is a bare list or a pagination envelope cannot be
# handed `{}`: the screen does `data.map(...)` or `data.items.map(...)` and
# throws. That is per-route information, so the scan below re-derives it from
# server.py's own return statements and requires an entry for everything it
# can classify.
#
# IT IS HONEST ABOUT WHAT IT CANNOT SEE. ~72 GET handlers end in
# `return await _something(...)` and this scan classifies them as unknown;
# they are not asserted, they take the `{}` default, and the failure mode for
# all of them is a visibly broken demo screen rather than a leaked row. That
# residual is written down in lib/demo_provider.py's docstring too.


def _returns_by_route():
    """{route template: {"list"|"envelope"|"dict"|"unknown"}} from the AST."""
    import server
    src = Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        paths = []
        for d in fn.decorator_list:
            if not isinstance(d, ast.Call):
                continue
            f = d.func
            if not isinstance(f, ast.Attribute) or f.attr != "get":
                continue
            if d.args and isinstance(d.args[0], ast.Constant):
                p = d.args[0].value
                if getattr(f.value, "id", None) == "api_router":
                    p = "/api" + p
                paths.append(p)
        if not paths:
            continue
        kinds = set()
        for n in ast.walk(fn):
            if not isinstance(n, ast.Return) or n.value is None:
                continue
            v = n.value
            while isinstance(v, ast.Await):
                v = v.value
            if isinstance(v, (ast.List, ast.ListComp)):
                kinds.add("list")
            elif isinstance(v, ast.Dict):
                kinds.add("dict")
            elif isinstance(v, ast.Call):
                name = (v.func.attr if isinstance(v.func, ast.Attribute)
                        else getattr(v.func, "id", ""))
                if name == "paginated_query":
                    kinds.add("envelope")
                elif name in ("list", "sorted"):
                    kinds.add("list")
                else:
                    kinds.add("unknown")
            elif isinstance(v, ast.Constant) and v.value is None:
                pass
            else:
                kinds.add("unknown")
        for p in paths:
            out[p] = kinds
    return out


def test_the_scan_that_derives_the_shapes_still_works():
    """An instrument that classified nothing would make the test below
    vacuous — it would demand an entry for zero routes and pass forever."""
    rows = _returns_by_route()
    assert len(rows) > 100, \
        f"the return-shape scan found only {len(rows)} GET handlers"
    classified = [p for p, k in rows.items()
                  if k & {"list", "envelope"}]
    assert len(classified) >= 8, (
        f"the scan classified only {len(classified)} list/envelope routes; it "
        f"has probably stopped recognising server.py's idioms")


def test_every_list_or_envelope_route_has_a_shape_the_client_can_render():
    """A GET whose real answer is a list or an envelope may not be handed {}.

    When this goes red for a route you just added, the fix is one line in
    lib/demo_provider.EMPTY_SHAPES — `[]` for a bare list, `"envelope"` for a
    paginated one — not a change here.
    """
    missing = []
    for path, kinds in _returns_by_route().items():
        if not (kinds & {"list", "envelope"}):
            continue
        if path in demo_provider.CANNED:
            continue  # it has a real canned payload of the right shape
        want = "envelope" if "envelope" in kinds else []
        got = demo_provider.EMPTY_SHAPES.get(path, "MISSING")
        if got == "MISSING":
            missing.append(f"{path} returns a {'envelope' if want else 'list'}"
                           f" and has no demo empty shape")
        elif got != want:
            missing.append(f"{path} wants {want!r} and the table says {got!r}")
    assert not missing, "\n  " + "\n  ".join(missing)


def test_the_empty_envelope_is_paginated_querys_envelope():
    """Keys AND arithmetic. `has_more` is False here and would also be False
    if somebody wrote `total > 0`, so the formula is what is pinned."""
    e = demo_provider.empty_envelope(limit=25, skip=50)
    assert e == {"items": [], "total": 0, "limit": 25, "skip": 50,
                 "has_more": False}


def test_the_default_empty_is_an_object_and_not_null():
    assert demo_provider.DEFAULT_EMPTY == {}


# ──────────────────────────────────────────────────────────────────
# 5. ROUTE MATCHING — the aliasing that would serve the wrong fiction
# ──────────────────────────────────────────────────────────────────


def test_a_literal_route_wins_over_a_parameter_route():
    """`/api/projects/dob-summary` and `/api/projects/{project_id}` both match
    that path. The router picks the literal one and so must this — matching
    against the canned table alone resolved `/api/projects/pending-deletion`
    onto the canned PROJECT builder, which is the bug this ordering fixes."""
    templates = _get_routes()
    for path, want in [
        ("/api/projects/dob-summary", "/api/projects/dob-summary"),
        ("/api/projects/pending-deletion", "/api/projects/pending-deletion"),
        ("/api/projects/demo", "/api/projects/{project_id}"),
        ("/api/workers/demo-worker-01", "/api/workers/{worker_id}"),
    ]:
        got = demo_provider.resolve_template(path, templates)
        assert got is not None and got[0] == want, \
            f"{path} resolved to {got and got[0]!r}, expected {want!r}"


def test_a_path_converter_swallows_the_tail():
    params = demo_provider.match_template(
        "/api/annotations/p1/plans/a/b.pdf",
        "/api/annotations/{project_id}/{document_path:path}")
    assert params == {"project_id": "p1", "document_path": "plans/a/b.pdf"}


def test_a_shorter_path_does_not_match_a_longer_template():
    assert demo_provider.match_template(
        "/api/workers", "/api/workers/{worker_id}") is None
    assert demo_provider.match_template(
        "/api/workers/a/b", "/api/workers/{worker_id}") is None


def test_an_unknown_path_falls_to_the_default_and_not_to_a_canned_builder():
    """No route match at all must mean the default empty, never the last
    builder that happened to look close."""
    r = demo_provider.payload_for(None, demo_provider.Ctx({}, {}, None, {}))
    assert r.body == {} and r.status == 200


# ──────────────────────────────────────────────────────────────────
# 6. THE CANNED PAYLOADS ARE THE FICTION, AND ONLY THE FICTION
# ──────────────────────────────────────────────────────────────────


def _demo_get(path, query=""):
    headers = {"Authorization": f"Bearer {_token('demo')}"}
    with Patched(ExplodingDB(DEMO_DOC)):
        rate_limits.reset_counter()
        return _client().get(path + query, headers=headers)


def test_the_project_list_is_the_one_demo_project():
    body = _demo_get("/api/projects").json()
    assert body["total"] == 1 and len(body["items"]) == 1
    assert body["items"][0]["id"] == "demo"
    assert set(body) == {"items", "total", "limit", "skip", "has_more"}


def test_a_project_id_that_is_not_the_demo_is_a_404_whether_or_not_it_exists():
    """The same answer for every id but one, which is what stops this being a
    probe: a demo cannot learn that a real project exists by asking for it."""
    a = _demo_get("/api/projects/68f0c1a2b3c4d5e6f7a8b9c0")
    b = _demo_get("/api/projects/definitely-not-an-id")
    assert a.status_code == 404 and b.status_code == 404
    assert a.json() == b.json()


def test_the_project_checkins_route_is_a_bare_list_and_the_other_is_not():
    """The two check-in endpoints disagree about their shape and a client
    written against one crashes on the other — shaping.py says so, and wiring
    them to the same builder is the mistake that note exists to prevent."""
    assert isinstance(_demo_get("/api/checkins/project/demo").json(), list)
    assert isinstance(_demo_get("/api/checkins").json(), dict)


def test_the_query_string_reaches_the_shaping_function():
    """A canned payload that ignored `limit` would page forever on a screen
    that asks for two rows at a time."""
    body = _demo_get("/api/workers", "?limit=2&skip=0").json()
    assert body["limit"] == 2 and len(body["items"]) <= 2
    assert body["total"] >= len(body["items"])


def test_a_junk_limit_is_the_default_and_not_a_500():
    """The real handler gets FastAPI's validation and answers 422; a 422 here
    would be about a route the request never reached."""
    body = _demo_get("/api/workers", "?limit=abc").json()
    assert body["limit"] == 50


def test_the_canned_logbook_types_are_the_products_own_registry():
    """ASSERT THE IDENTITY. The point of canning this route is that a demo sees
    the product's labels; a canned list that had drifted from the registry
    would defeat the whole reason it is on the allow-list, and it would drift
    silently because both sides look plausible.
    """
    import server
    canned = _demo_get("/api/logbook-types").json()
    real = server._demo_logbook_type_catalog()
    assert canned, "the demo got an empty logbook registry"
    assert [e["key"] for e in canned] == [e["key"] for e in real]
    assert canned == real, \
        "the demo's logbook registry is not the one the product serves"


def test_the_logbook_registry_carries_no_tenant_data():
    """The one non-fiction entry in CANNED, checked for the property that
    justifies it: it is static app metadata. A key that looked like a company
    or project id would mean the registry had stopped being that."""
    import server
    for entry in server._demo_logbook_type_catalog():
        assert "company_id" not in entry
        assert "project_id" not in entry


def test_the_dates_track_the_caller_day_and_are_not_frozen():
    """`today` is injected, never read from a clock inside the dataset. A demo
    whose logbooks are all stamped with an anchor day in 2026 is the defect
    lib/demo/shaping.py refuses a clock to prevent."""
    from lib import demo
    a = demo.demo_logbooks("2026-03-02")
    b = demo.demo_logbooks("2026-09-17")
    assert a != b, "the dataset ignored `today`"


def test_a_demo_get_returns_no_object_id_shaped_ids():
    """A cheap independent read on "zero real documents": every id in the
    fiction is visibly invented, so a 24-character hex id in a demo response
    would mean a real Mongo row got through some path this file did not model.
    """
    import json
    import re
    oid = re.compile(r"^[0-9a-f]{24}$")
    for path in ("/api/projects", "/api/workers", "/api/checkins",
                 "/api/logbooks/project/demo", "/api/projects/demo"):
        text = json.dumps(_demo_get(path).json())
        for value in re.findall(r'"([0-9a-f]{24})"', text):
            assert not oid.match(value), \
                f"{path} returned an ObjectId-shaped id: {value}"


# ──────────────────────────────────────────────────────────────────
# 7. /auth/me — the one response that is about the caller
# ──────────────────────────────────────────────────────────────────


def test_auth_me_answers_a_demo_with_their_own_account():
    body = _demo_get("/api/auth/me").json()
    assert body["id"] == DEMO_USER_ID
    assert body["role"] == "demo"
    assert body["name"] == "Dana Demo"


def test_auth_me_never_carries_a_secret():
    """The denylist is applied upstream, in server.py, with the REAL constant.
    This asserts the outcome rather than the mechanism, so it keeps working if
    the mechanism moves."""
    import server
    body = _demo_get("/api/auth/me").json()
    for field in server._PRINCIPAL_PRIVATE_FIELDS:
        assert field not in body, f"/auth/me leaked {field} to a demo"
    assert "THIS-MUST-NEVER-REACH-A-CLIENT" not in str(body)


def test_the_canned_auth_me_is_what_the_real_handler_would_have_said():
    """ASSERT THE IDENTITY, NOT BOTH SIDES SEPARATELY.

    The canned /auth/me exists because the real one reads `db.projects` for
    `superintendent_projects` — a tenant collection, on a demo request. The
    thing that could silently rot is the two answers drifting, so this derives
    the real handler's output for the same principal and asserts equality
    rather than restating the canned shape by hand.
    """
    import server

    async def _real():
        db = MagicMock()
        # superintendent_projects_for is given a db of its own; a demo holds
        # no registrations, so the real answer is [].
        db.cs_registrations = MagicMock()
        db.cs_registrations.find = MagicMock(
            return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        principal = await server._demo_principal_document(
            {"sub": DEMO_USER_ID, "role": "demo"})
        with Patched(db):
            return await server.get_me(current_user=principal), principal

    with Patched(ExplodingDB(DEMO_DOC)):
        real, principal = _run(_real())

    canned = demo_provider.CANNED["/api/auth/me"](
        demo_provider.Ctx({}, {}, None, principal)).body
    assert canned == real, (
        "the canned /auth/me and the real handler disagree for a demo "
        f"principal:\n  canned={canned}\n  real={real}")


# ──────────────────────────────────────────────────────────────────
# 8. THE PLAN PLACEHOLDER — an operator decision, not a 404
# ──────────────────────────────────────────────────────────────────


def test_a_demo_plan_opens_as_a_pdf_that_says_it_is_a_demo():
    """OPERATOR DECISION: a placeholder page, not a 404. A prospect who taps a
    plan and gets an error learns that the product cannot open plans."""
    r = _demo_get("/api/projects/demo/files/demo-file-01/content")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "inline" in r.headers.get("content-disposition", "")
    assert r.content.startswith(b"%PDF-")


def test_the_placeholder_pdf_actually_parses_and_says_demo():
    """A PDF that a reader refuses is the 404 with extra steps. The client
    hands this to WKWebView on iOS and an <iframe> on web; both need a file a
    parser accepts, so the test uses one."""
    pypdf = pytest.importorskip("pypdf")
    import io
    reader = pypdf.PdfReader(io.BytesIO(demo_provider.placeholder_pdf()))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text().lower()
    assert "demo" in text, \
        "the placeholder does not say it is a demo, so it reads as a bug"


def test_every_demo_file_row_points_at_the_route_that_serves_the_placeholder():
    """The dataset's file rows carry a proxy URL and the provider answers it.
    A row pointing anywhere else is a plan that 404s in the demo."""
    from lib import demo
    templates = _get_routes()
    for row in demo.demo_files("2026-09-17"):
        resolved = demo_provider.resolve_template(row["r2_url"], templates)
        assert resolved is not None, f"{row['r2_url']} matches no route"
        assert resolved[0] in demo_provider.CANNED, (
            f"{row['r2_url']} resolves to {resolved[0]}, which has no canned "
            f"payload — a demo tapping this plan gets an empty body")


# ──────────────────────────────────────────────────────────────────
# 9. THE TWO GUARDS NEVER DISAGREE ABOUT ONE ACCOUNT
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("doc,expected", [
    ({"_id": "u1", "role": "demo"}, True),
    ({"_id": "u1", "role": " Demo "}, True),
    ({"_id": "u1", "role": "cp"}, False),
    ({"_id": "u1", "role": "admin"}, False),
    (None, False),
])
def test_the_read_and_write_guards_agree_on_every_account(doc, expected):
    """Two derivations of "is a demo" that can disagree are a demo that writes
    nothing and reads everything, or the reverse. So the answer is asserted as
    an IDENTITY between the two functions, not as two separate expectations.
    """
    import server
    payload = {"sub": "u1", "role": "cp"}  # claim deliberately NOT demo

    async def _both():
        with Patched(ExplodingDB(doc)):
            w = await server._demo_write_guard_principal(payload)
            r = await server._demo_principal_document(payload)
        return bool(w), bool(r)

    write, read = _run(_both())
    assert write == read, (
        f"the write guard says {write} and the read provider says {read} for "
        f"{doc!r} — one of them is wrong about this account")
    assert read is expected


def test_a_demo_document_is_intercepted_under_a_non_demo_claim():
    """THE DOCUMENT DECIDES. A token whose `role` claim says anything else
    must still be intercepted when the row says demo — otherwise the claim is
    the boundary, and a claim is a thirty-day snapshot.

    ASSERTED AT BOTH LEVELS, and the second one is the one that matters. A
    first draft checked only `_demo_principal_document`, so replacing the
    middleware's read with `payload["role"]` — the exact shortcut this
    docstring argues against — left this test green while a demo document
    under a stale non-demo claim walked through to the real handlers. The
    property belongs to the request path, so it is asserted on the request
    path.
    """
    import server

    async def _helper():
        with Patched(ExplodingDB({"_id": "u1", "role": "demo"})):
            return await server._demo_principal_document(
                {"sub": "u1", "role": "cp"})

    assert _run(_helper()), "a demo row under a non-demo claim was let through"

    request = MagicMock()
    request.headers = {
        "authorization": f"Bearer {_token('cp', user_id='u1')}"}

    async def _through_the_provider():
        with Patched(ExplodingDB({"_id": "u1", "role": "demo"})):
            return await demo_provider.evaluate(
                method="GET", path="/api/projects", request=request,
                query={}, today="2026-09-17",
                jwt_secret=server.JWT_SECRET,
                jwt_algorithm=server.JWT_ALGORITHM,
                demo_principal_document=server._demo_principal_document,
                templates=_get_routes())

    assert _run(_through_the_provider()) is not None, (
        "the provider read the token claim instead of the document — a demo "
        "account whose claim says otherwise reaches the real handlers")


def test_a_promoted_demo_reads_real_data_on_a_token_that_still_says_demo():
    """The other direction, and the reason the claim is not trusted. A demo
    promoted to a paying CP carries the string "demo" in their token for up to
    thirty days; serving them canned fiction for a month would look like their
    account was empty."""
    import server

    async def _go():
        with Patched(ExplodingDB({"_id": "u1", "role": "cp"})):
            return await server._demo_principal_document(
                {"sub": "u1", "role": "demo"})

    assert _run(_go()) is None, \
        "a promoted customer was served demo fiction on a stale token"


def test_a_failed_lookup_falls_back_to_the_signed_claim():
    """Mongo unreachable is the one case where the claim is used, and it fails
    CLOSED: a claim that says demo is treated as a demo. Passing a possible
    demo through to the router is the one direction that leaks."""
    import server

    class _Broken:
        @property
        def users(self):
            raise RuntimeError("mongo is down")

    async def _go(role):
        with Patched(_Broken()):
            return await server._demo_principal_document(
                {"sub": "u1", "role": role, "email": "d@e.com"})

    demo = _run(_go("demo"))
    real = _run(_go("cp"))
    assert demo and demo["role"] == "demo", \
        "a demo was let through to the router while the database was down"
    assert real is None


def test_a_vanished_user_is_not_a_demo():
    """No such row is not the provider's business; `get_current_user` answers
    401 for the same token immediately after."""
    import server

    async def _go():
        with Patched(ExplodingDB(None)):
            return await server._demo_principal_document({"sub": "u1"})

    assert _run(_go()) is None


def test_a_site_device_is_never_a_demo():
    """The gate tablet's `sub` is a db.site_devices id, not a user id. Looking
    it up in db.users would find nothing and read as "not a demo" by accident
    rather than on purpose — and the gate is the most read-heavy caller in the
    product."""
    import server
    request = MagicMock()
    request.headers = {"authorization":
                       f"Bearer {_token('site_device', site_mode=True)}"}

    async def _go():
        with Patched(ExplodingDB(DEMO_DOC)):
            return await demo_provider.evaluate(
                method="GET", path="/api/projects", request=request,
                query={}, today="2026-09-17",
                jwt_secret=server.JWT_SECRET,
                jwt_algorithm=server.JWT_ALGORITHM,
                demo_principal_document=server._demo_principal_document,
                templates=_get_routes())

    assert _run(_go()) is None, "a site device was served demo fiction"


# ──────────────────────────────────────────────────────────────────
# 10. FAILING CLOSED
# ──────────────────────────────────────────────────────────────────


def test_a_broken_builder_answers_empty_and_never_the_real_handler():
    """A bug in a shaping function must not fall back to `call_next`. That
    would turn "the logbook builder raised" into "the demo was served the real
    company's logbooks"."""
    import server

    request = MagicMock()
    request.headers = {"authorization": f"Bearer {_token('demo')}"}

    def _boom(ctx):
        raise RuntimeError("shaping blew up")

    original = demo_provider.CANNED["/api/projects"]
    demo_provider.CANNED["/api/projects"] = _boom
    try:
        async def _go():
            with Patched(ExplodingDB(DEMO_DOC)):
                return await demo_provider.evaluate(
                    method="GET", path="/api/projects", request=request,
                    query={}, today="2026-09-17",
                    jwt_secret=server.JWT_SECRET,
                    jwt_algorithm=server.JWT_ALGORITHM,
                    demo_principal_document=server._demo_principal_document,
                    templates=_get_routes())

        answer = _run(_go())
    finally:
        demo_provider.CANNED["/api/projects"] = original

    assert answer is not None, \
        "a builder that raised let the request through to the real handler"
    assert answer.body == {}
