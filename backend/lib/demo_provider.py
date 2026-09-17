"""THE DEMO READS FICTION — and the router is where the fiction stops, not
where it starts.

OPERATOR RULING: "Real admin screens, rendered from canned payloads. Not only
/demo/*. The demo must feel like the app." And: "Every other endpoint returns
an empty or canned result, never real data. Test: a demo token hitting every
GET route returns zero real documents (route census, not a sample)."

lib/demo_guard.py is the write half of this: every non-safe method from a demo
principal is refused. This module is the READ half, and the two are built the
same way on purpose — a pure decision, a middleware that glues it, and the
application wiring in server.py.

──────────────────────────────────────────────────────────────────────────────
THE ONE THING THIS FILE IS FOR: DEFAULT-DENY, STRUCTURALLY
──────────────────────────────────────────────────────────────────────────────

The obvious shape is an allow-list that ADDS canned responses to some routes
and lets the rest fall through to the real handler. That shape is a data leak
with a to-do list attached. Everything about it looks right on the day it is
written: fourteen routes serve the demo project, every other route serves the
truth, and the truth is a real tenant's rows. The next GET anybody adds serves
real data to demo accounts, nothing goes red, and the person who added it had
no reason to think about demos at all.

So the allow-list here does not decide WHETHER to intercept. It decides only
WHAT to answer with. The interception is unconditional:

    FOR A DEMO PRINCIPAL, ON A GET, `call_next` IS NEVER CALLED.

There is exactly one `call_next` in this module, it is in the pass-through
branch, and there is no path from "this caller is a demo" to it. Because
Starlette's middleware runs ABOVE the router, not calling `call_next` means
the router never matches, which means no handler function is ever entered,
which means no `db.<anything>.find()` inside one can run. "No demo GET reads
Mongo" is therefore not a property of this table being complete — it is a
property of there being no code path. A route added next week is covered
before it is written.

That is the difference worth the file. An allow-list you have to maintain
protects you on the routes you remembered; this protects you on the routes
nobody has thought of yet, and degrades to an empty screen rather than to
somebody else's data.

──────────────────────────────────────────────────────────────────────────────
WHAT IS NOT STRUCTURAL, STATED PLAINLY
──────────────────────────────────────────────────────────────────────────────

Two things are lists, and pretending otherwise would be the same mistake in a
different coat:

  1. WHICH ROUTES GET REAL CANNED DATA (`CANNED`, below). Missing an entry
     costs a blank screen in the demo. It cannot cost a leak, because the
     fallback is empty, not real.

  2. THE EMPTY SHAPE for a route with no canned payload (`EMPTY_SHAPES` plus
     `DEFAULT_EMPTY`). A pagination envelope with zero rows is not `[]` and
     neither is `null`, and a screen handed the wrong one of those crashes or
     renders blank. Getting this wrong costs a broken demo screen. It cannot
     cost a leak either.

Neither list is load-bearing for safety. Both are cosmetic, and the census
test asserts the safety property without consulting either — see
tests/test_a_demo_account_reads_fiction.py, which drives every declared GET
route against a database that RAISES on contact.

THE RESIDUAL RISK, NAMED: a GET route whose real response is a bare list or a
pagination envelope, added later, with no entry here, hands a demo screen `{}`
and that screen breaks. A test re-derives the bare-list and envelope routes
from server.py's own syntax tree and requires an entry for each one it can
classify; 72 of 172 GET handlers return something that scan cannot classify
(`return await _something(...)`), and those are not covered. The failure mode
for all of them is a visibly broken demo screen, never a real row.

AND ONE BEHAVIOUR CHANGE THAT IS NOT A BUG BUT IS A CHANGE. Interception is by
PRINCIPAL, not by path, so it also covers the routes that are not app screens:
`/docs`, `/openapi.json`, the server-rendered gate pages, and the public share
links under `/api/public/`. A person whose device is holding a demo session and
who opens a real tenant's shared report THROUGH THE APP'S HTTP CLIENT — which
attaches the bearer token to every request — gets the empty body rather than
the report. That is the correct answer on the merits (a demo has no business
reading a real company's filed record, grant token or not) and it is narrow in
practice: a share link opened in a browser carries no Authorization header, so
it is anonymous and passes straight through. It is written down here because
"the demo could not open the link I sent him" is otherwise a mystery.

──────────────────────────────────────────────────────────────────────────────
WHY NOT SWAP THE DATABASE INSTEAD
──────────────────────────────────────────────────────────────────────────────

The alternative that is MORE structural than this one: give a demo request a
fake `db` and let the real handlers run against it. "No demo request reads
Mongo" would then be true because there is no Mongo handle to read.

It was rejected, and not on effort. `db` is a module-global in server.py read
by ~150 handlers; swapping it per-request is a process-global mutation under
concurrency, which is a correctness bug, not a design. And the dataset this
change is built on (lib/demo/) was derived as canned RESPONSES — one function
per screen, shaped from the real handler's return statement — not as canned
COLLECTIONS. Feeding it back through the handlers would require a Mongo query
engine faithful enough that `$lookup`, `$facet` and a dozen aggregation
pipelines produced the shapes the screens already expect. That is a larger,
less inspectable surface than the table below, and its failures would be
silent wrong answers rather than a blank panel.

──────────────────────────────────────────────────────────────────────────────
THE ONE MONGO READ A DEMO GET STILL CAUSES, AND WHY IT IS NOT A HOLE
──────────────────────────────────────────────────────────────────────────────

Deciding "is this caller a demo" requires reading the caller's own `users`
document. lib/demo_guard.py already established why the DOCUMENT and not the
`role` claim decides (a promoted demo carries the string "demo" in a token for
up to thirty days), and this module asks the same question through the same
function so the two guards cannot disagree about one account.

So the honest invariant is not "no query at all". It is:

    A DEMO GET TOUCHES NO COLLECTION EXCEPT `users`, AND ON `users` IT READS
    ONLY THE CALLER'S OWN DOCUMENT.

That is what the census asserts, with a db double that raises on any other
collection. `/api/auth/me` is the one route that reads the caller's document
a second time (it IS that document) — see `_auth_me` below.

An authenticated GET by a NON-demo costs that same one indexed `find_one`,
which is the price of asking the document instead of the claim. It is the
trade demo_guard already made for writes, made again here for a heavier path;
the alternative — trusting `role` in the token when it says "not a demo" — is
the one direction of drift that leaks, so it is not available.

An ANONYMOUS GET costs nothing: no Authorization header, no lookup, immediate
pass-through. The gate pages, the public share links and the health probes
never reach the lookup at all.

──────────────────────────────────────────────────────────────────────────────
NO EXTERNAL SPEND, AND IT FALLS OUT OF THE SHAPE RATHER THAN BEING ARRANGED
──────────────────────────────────────────────────────────────────────────────

The dataset's original note asks for ZERO external calls. Nothing in this
module mocks a vision client or short-circuits Socrata, because it does not
have to: a paid call lives inside a handler, and for a demo principal no
handler runs. Reads cannot spend because they do not execute; writes cannot
spend because demo_guard refuses them with a 403 before the router. That
covers `upload-osha`, the known-unmetered paid endpoint in this repo, by
being a POST, and it covers every vision/OCR/R2/WhatsApp/email call site in
the app by construction rather than by enumeration.

The one thing that would break that property is an exemption that passes a
demo request THROUGH to a handler. There are none, and there is no mechanism
in this file to add one.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Vocabulary
# ──────────────────────────────────────────────────────────────────

# The methods this module answers for. NOT all of demo_guard.SAFE_METHODS:
# OPTIONS is a CORS preflight and must reach the CORS layer's own handler
# untouched, and TRACE is not something this app serves. Intercepting a
# preflight would break the browser's check on every demo request, which reads
# as "the API is down" rather than as anything to do with demos.
READ_METHODS = frozenset({"GET", "HEAD"})

# The demo's one project. `lib/demo` owns the value; it is re-read from there
# rather than re-typed, because a second spelling of an id is a second thing
# that can drift.
from lib.demo import DEMO_PROJECT_ID  # noqa: E402  (imported with its subject)


# ──────────────────────────────────────────────────────────────────
# The response envelope this module speaks in
# ──────────────────────────────────────────────────────────────────


class DemoResponse:
    """What a builder returns: a status, a media type and a body.

    NOT a `fastapi.Response`, deliberately. Every builder below is then a pure
    function returning a comparable value, so a test can assert what a route
    answers without an app, a client or an event loop — the same reason
    lib/demo_guard.py keeps `evaluate()` free of Starlette and builds the
    actual response in one place.

    `body` is a dict or list for JSON, or `bytes` for the plan placeholder.
    """

    __slots__ = ("status", "media_type", "body", "headers")

    def __init__(self, body, *, status: int = 200,
                 media_type: str = "application/json",
                 headers: Optional[Dict[str, str]] = None):
        self.body = body
        self.status = status
        self.media_type = media_type
        self.headers = headers or {}

    def __repr__(self):  # pragma: no cover — debugging aid
        shown = f"<{len(self.body)} bytes>" if isinstance(
            self.body, (bytes, bytearray)) else repr(self.body)
        return (f"DemoResponse({shown}, status={self.status}, "
                f"media_type={self.media_type!r})")


def build_response(demo_response: "DemoResponse"):
    """The one place Starlette is imported, and the one place a DemoResponse
    becomes something an ASGI stack can send.

    Lazy import for the reason lib/demo_guard.py gives: this module stays
    importable by a test environment with no FastAPI installed.

    ── `jsonable_encoder` IS NOT OPTIONAL HERE ─────────────────────────────

    A handler that returns a dict gets it run through `jsonable_encoder` by
    FastAPI before anything is serialized; a middleware building its own
    `JSONResponse` does not, and `json.dumps` raises `TypeError` on the first
    `datetime` it meets. The dataset is FULL of them — every logbook date,
    every check-in instant — so without this line the canned project list is a
    500 and the canned DOB summary, which happens to hold only integers, is a
    200. That is the worst possible failure shape: it looks like the feature
    works.

    Calling the same encoder the framework calls also means a demo's dates
    reach the client in the same ISO spelling the real handlers produce, which
    is the whole point of shaping from the real handler in the first place.
    """
    from fastapi.encoders import jsonable_encoder  # local import
    from fastapi.responses import JSONResponse, Response  # local import

    if isinstance(demo_response.body, (bytes, bytearray)):
        return Response(
            content=bytes(demo_response.body),
            status_code=demo_response.status,
            media_type=demo_response.media_type,
            headers=demo_response.headers,
        )
    return JSONResponse(
        jsonable_encoder(demo_response.body),
        status_code=demo_response.status,
        headers=demo_response.headers,
    )


# ──────────────────────────────────────────────────────────────────
# The empty forms
# ──────────────────────────────────────────────────────────────────
#
# WHAT AN UNLISTED GET ANSWERS. The ruling's words are "an empty or canned
# result", and the trap it names is that these three are not interchangeable:
#
#     []                            a bare list endpoint
#     {"items": [], "total": 0,...} a paginated endpoint
#     {}                            everything else
#
# `null` is not on the list at all. A screen that does `data.items.map(...)`
# throws on `[]`; one that does `data.map(...)` throws on the envelope; both
# throw on `null`. So the default has to be a real, well-formed empty
# something, and which one is right is per-route information.
#
# THE DEFAULT IS `{}` BECAUSE THAT IS WHAT THE APP MOSTLY RETURNS. A mechanical
# scan of server.py's GET handlers classifies 76 as returning a dict literal,
# 8 a bare list, 1 the pagination envelope, and 72 as unclassifiable. `{}` is
# the plurality answer and the one that degrades best: a screen reading
# `data.some_key` off it gets `undefined`, which React renders as nothing,
# rather than an exception.


DEFAULT_EMPTY: Dict = {}


def empty_envelope(limit: int = 50, skip: int = 0) -> Dict:
    """`paginated_query`'s envelope with nothing in it.

    Keys and arithmetic copied from server.py's helper, including `has_more`
    being `skip + limit < total` — which is False here and would ALSO be False
    if somebody wrote `total > 0`, so the formula is kept rather than the
    answer. A client that pages on `has_more` must see a well-formed stop.
    """
    return {"items": [], "total": 0, "limit": limit, "skip": skip,
            "has_more": False}


# Routes whose real response is NOT a dict, so `{}` would be the wrong empty.
#
# DERIVED, NOT REMEMBERED: the companion test re-runs the same AST scan over
# server.py and requires an entry here for every GET handler it can classify
# as returning a bare list or the pagination envelope. Adding such a route
# without an entry turns that test red with the route's name in the message.
# Routes that also appear in CANNED below never reach this table.
EMPTY_SHAPES: Dict[str, object] = {
    # bare lists
    "/api/admin/checklists/{checklist_id}/assignments": [],
    "/api/baseline-aggregates": [],
    "/api/checklists/assigned": [],
    "/api/gc/autocomplete": [],
    "/api/projects/{project_id}/checklists": [],
    "/api/projects/{project_id}/nfc-tags": [],
    # the one route that returns paginated_query's envelope directly
    "/api/notifications": "envelope",
}


# ──────────────────────────────────────────────────────────────────
# Query parsing
# ──────────────────────────────────────────────────────────────────


def _int_param(query, name: str, default: int) -> int:
    """A query integer, or the default.

    FAILS TO THE DEFAULT rather than raising. A demo screen sending
    `?limit=abc` gets the first page instead of a 500; the real handlers get
    FastAPI's validation for this and answer 422, but a 422 here would be a
    422 about a request that never reached the route that validates it.
    """
    raw = query.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _str_param(query, name: str) -> Optional[str]:
    raw = query.get(name)
    if raw in (None, ""):
        return None
    return str(raw)


class Ctx:
    """Everything a builder is allowed to know.

    NO REQUEST OBJECT AND NO DATABASE. A builder gets the matched path
    parameters, the query string, the day, and — only because `/api/auth/me`
    IS the caller's own document — the principal. Keeping the request out
    means a builder cannot accidentally grow a header check or a db handle.
    """

    __slots__ = ("params", "query", "today", "user", "logbook_types")

    def __init__(self, params: Dict[str, str], query, today, user,
                 logbook_types=None):
        self.params = params
        self.query = query
        self.today = today
        self.user = user or {}
        # The app's static logbook registry, as a callable. Defaults to an
        # empty list so a Ctx built in a test — or by a caller that has no app
        # — still answers, rather than raising on an attribute that is only
        # there sometimes.
        self.logbook_types = logbook_types or (lambda: [])

    def limit(self, default: int = 50) -> int:
        return _int_param(self.query, "limit", default)

    def skip(self, default: int = 0) -> int:
        # `offset` is what /api/notifications calls it; `skip` is what
        # everything else calls it. Both map onto the envelope's `skip`.
        if self.query.get("skip") not in (None, ""):
            return _int_param(self.query, "skip", default)
        return _int_param(self.query, "offset", default)


# ──────────────────────────────────────────────────────────────────
# The canned payloads
# ──────────────────────────────────────────────────────────────────
#
# One builder per allow-listed route. The SHAPES are not invented here — every
# one of these delegates to lib/demo/shaping.py, whose functions were each
# derived field-by-field from the real handler's return statement and are
# covered by that package's own tests. This file decides only WHICH shaping
# function a route gets and how the query string feeds it.
#
# `today` is passed IN, never read from a clock, because shaping.py refuses to
# hold one: every date in the dataset is an offset from the day of the call, so
# a demo opened in March shows March and the same code in June shows June.


def _not_found(detail: str) -> DemoResponse:
    """FastAPI's own 404 body, `{"detail": ...}`.

    A demo asking for an id the fiction does not contain is a 404, not an
    empty object: the screens already have a not-found path and it is the
    truthful answer. Shaped like HTTPException's body because that is what
    every other 404 in this app looks like and the client has one reader.
    """
    return DemoResponse({"detail": detail}, status=404)


def _projects(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_project_list
    return DemoResponse(demo_project_list(
        ctx.today, limit=ctx.limit(50), skip=ctx.skip(0)))


def _project(ctx: Ctx) -> DemoResponse:
    """GET /api/projects/{project_id}.

    THE DEMO HAS EXACTLY ONE PROJECT, so any other id is a 404 — the same
    answer a real account gets for a project in somebody else's company, and
    the reason this cannot become a probe: every id that is not "demo" gives
    the identical response whether or not a real project by that id exists.
    """
    from lib.demo import demo_project
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return _not_found("Project not found")
    return DemoResponse(demo_project(ctx.today))


def _demo_project_route(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_project
    return DemoResponse(demo_project(ctx.today))


def _required_logbooks(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_required_logbooks
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return _not_found("Project not found")
    return DemoResponse(demo_required_logbooks(ctx.today))


def _dob_logs(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_dob_logs
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return _not_found("Project not found")
    return DemoResponse(demo_dob_logs(
        ctx.today,
        record_type=_str_param(ctx.query, "record_type"),
        severity=_str_param(ctx.query, "severity"),
        limit=ctx.limit(20), skip=ctx.skip(0)))


def _dob_summary(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_dob_summary
    return DemoResponse(demo_dob_summary(ctx.today))


def _files(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_files
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return DemoResponse([])
    return DemoResponse(demo_files(ctx.today))


def _logbooks(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_logbooks
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return DemoResponse(empty_envelope(ctx.limit(50), ctx.skip(0)))
    return DemoResponse(demo_logbooks(
        ctx.today,
        log_type=_str_param(ctx.query, "log_type"),
        date=_str_param(ctx.query, "date"),
        limit=ctx.limit(50), skip=ctx.skip(0)))


def _logbook(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_logbook_by_id
    doc = demo_logbook_by_id(ctx.params.get("logbook_id", ""), ctx.today)
    if doc is None:
        return _not_found("Logbook not found")
    return DemoResponse(doc)


def _workers(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_workers
    return DemoResponse(demo_workers(
        ctx.today, limit=ctx.limit(50), skip=ctx.skip(0)))


def _worker(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_worker
    doc = demo_worker(ctx.params.get("worker_id", ""), ctx.today)
    if doc is None:
        return _not_found("Worker not found")
    return DemoResponse(doc)


def _worker_certifications(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_worker_certifications
    doc = demo_worker_certifications(ctx.params.get("worker_id", ""), ctx.today)
    if doc is None:
        return _not_found("Worker not found")
    return DemoResponse(doc)


def _checkins(ctx: Ctx) -> DemoResponse:
    from lib.demo import demo_checkins
    return DemoResponse(demo_checkins(
        ctx.today, date=_str_param(ctx.query, "date"),
        limit=ctx.limit(50), skip=ctx.skip(0)))


def _project_checkins(ctx: Ctx) -> DemoResponse:
    """A BARE LIST, not an envelope — the two check-in endpoints disagree and
    shaping.py's docstring says so. Wiring this to the envelope builder would
    be a crash on the screen that reads it."""
    from lib.demo import demo_project_checkins
    if ctx.params.get("project_id") != DEMO_PROJECT_ID:
        return DemoResponse([])
    return DemoResponse(demo_project_checkins(
        ctx.today, limit=ctx.limit(200), skip=ctx.skip(0)))


def _auth_me(ctx: Ctx) -> DemoResponse:
    """GET /api/auth/me — the caller's OWN account, canned from their own row.

    THIS ROUTE IS WHY THE PRINCIPAL IS ON `Ctx`. Every other builder invents;
    this one cannot. An empty /auth/me is a client with no session: no name,
    no role, no onboarding step, and a demo that cannot get past the splash
    screen — the demo would not "feel like the app", it would not start.

    It is still not a pass-through, and the distinction matters. The real
    handler also calls `superintendent_projects_for(db, user)`, which reads
    `db.projects` — a tenant collection, on a demo request, which is the exact
    thing this module exists to prevent. So the response is REBUILT here from
    the one document the guard already had to read, and the identity between
    the two is asserted by a test rather than assumed: for a demo principal
    this answer equals what the real handler would have returned, because a
    demo holds no superintendent assignments and is not the platform operator.

    THE SECRET STRIP HAPPENS UPSTREAM, AND THAT IS NOT AN OVERSIGHT HERE. A
    raw `users` row carries `password_hash` and everything else on
    `_PRINCIPAL_PRIVATE_FIELDS`, so `demo_principal_document` in server.py
    applies that denylist — the real one, by name — before the document ever
    reaches this module. Re-deriving the list here would put a second copy of
    it in the repo, and the copy that drifts is the one that ships a hash to a
    client. `ctx.user` is therefore already in `get_current_user`'s own form:
    `_id` serialized to `id`, `site_mode` set, secrets gone.
    """
    user = dict(ctx.user or {})
    # A demo is never the operator and never a superintendent: ROLE_DEMO is
    # not in ASSIGNABLE_ROLES and a demo has no company, so there is no
    # project anybody could have assigned them to. Both values are the real
    # handler's answer for this principal, not a placeholder.
    user["is_platform_operator"] = False
    user["superintendent_projects"] = []
    return DemoResponse(user)


def _logbook_types(ctx: Ctx) -> DemoResponse:
    """GET /api/logbook-types — the app's own static registry, canned.

    THE ONLY ENTRY IN THIS TABLE THAT IS NOT FICTION, and the reason is that
    there is no fiction to tell: the response is `LOGBOOK_TYPE_REGISTRY` plus
    each entry's timing metadata, a module-level constant in server.py with no
    tenant content, no database read and no per-company variation. Every
    account in the product gets byte-identical bytes from this route.

    IT IS STILL NOT A PASS-THROUGH. Letting one "harmless" GET reach its
    handler is how the allow-list stops being structural — the next reader has
    a precedent for the second one, and the second one reads a collection. So
    the registry is INJECTED as a callable (`get_logbook_types`) the same way
    the route table and the clock are, and the handler stays unreachable.

    WHAT IT BUYS. Without it the demo's logbook screens fall back to
    `FALLBACK_LOG_TYPES` and title-case the keys they do not recognise, so a
    prospect reads "Ssc Daily Safety Log" where the product says "SSC Daily
    Safety Log". The logbooks screen is in the middle of the set the ruling
    named, and a mangled label there is exactly the kind of thing the demo is
    supposed to not have.
    """
    types = ctx.logbook_types() if callable(ctx.logbook_types) else []
    return DemoResponse(list(types or []))


def _plan_placeholder(ctx: Ctx) -> DemoResponse:
    """GET /api/projects/{project_id}/files/{file_id}/content.

    OPERATOR DECISION, ALREADY MADE: a placeholder page, not a 404. The demo's
    file rows carry the real proxy URL shape and there is no R2 object behind
    any of them, so the real handler would 404 — and a prospect who taps a plan
    and gets an error learns that the product cannot open plans, which is the
    opposite of what the demo is for.

    IT IS A REAL PDF, because that is what the client is built to receive.
    frontend/src/utils/pdfSrc.js only decorates a URL matching exactly this
    route; iOS hands it to a WKWebView and the web build to an <iframe>, and
    both need an `application/pdf` body with `Content-Disposition: inline`. An
    HTML page saying "demo" would render as a download prompt on one platform
    and as nothing on the other.

    The page SAYS it is a demo. A blank sheet would read as a broken file.
    """
    return DemoResponse(
        placeholder_pdf(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="demo-plan.pdf"',
            # The real route sets no cache header; neither does this, so a
            # client's caching of a demo plan matches its caching of a real one.
        },
    )


# THE ALLOW-LIST. Keys are route templates EXACTLY as server.py declares them,
# including the /api prefix the router adds — a test asserts every one of them
# is a real GET route in the app, because an entry for a path that does not
# exist is a dead line that reads as coverage.
#
# This is the "_DEMO_PROJECT set" the ruling names: the project, its logbooks,
# its crew, its day at the gate, its DOB record, its documents. Nothing here
# is a judgement call about what a demo "should" see — it is the closed
# fiction lib/demo/ already holds, and no route was added to this table that
# the dataset cannot answer.
CANNED: Dict[str, Callable[[Ctx], DemoResponse]] = {
    "/api/auth/me": _auth_me,
    "/api/logbook-types": _logbook_types,
    "/api/projects": _projects,
    "/api/projects/{project_id}": _project,
    "/api/demo/project": _demo_project_route,
    "/api/projects/{project_id}/required-logbooks": _required_logbooks,
    "/api/projects/{project_id}/dob-logs": _dob_logs,
    "/api/projects/dob-summary": _dob_summary,
    "/api/projects/{project_id}/dropbox-files": _files,
    "/api/projects/{project_id}/files/{file_id}/content": _plan_placeholder,
    "/api/logbooks/project/{project_id}": _logbooks,
    "/api/logbooks/{logbook_id}": _logbook,
    "/api/workers": _workers,
    "/api/workers/{worker_id}": _worker,
    "/api/workers/{worker_id}/certifications": _worker_certifications,
    "/api/checkins": _checkins,
    "/api/checkins/project/{project_id}": _project_checkins,
}


# ──────────────────────────────────────────────────────────────────
# The placeholder plan
# ──────────────────────────────────────────────────────────────────


_PLACEHOLDER_LINES = [
    "This is a demo.",
    "",
    "Plan sheets are not included in the demo account.",
    "In the real app this page shows the drawing,",
    "with its markups, indexed pages and revisions.",
    "",
    "Nothing you do in the demo is saved.",
]

_PDF_CACHE: Optional[bytes] = None


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def placeholder_pdf() -> bytes:
    """A one-page US-Letter PDF that says it is a demo.

    BUILT, NOT PASTED. A hand-typed PDF blob carries byte offsets in its xref
    table, and the first person to fix a typo in the text above would shift
    every offset and produce a file that some readers open and others refuse.
    Generating it means the offsets are computed from the bytes that are
    actually there.

    NO DEPENDENCY. Not reportlab, not PIL, not poppler — this runs on the
    request path and a missing wheel would turn a demo's plan viewer into a
    500. Helvetica is one of the 14 fonts every PDF reader is required to
    have built in, so nothing is embedded either.

    Cached after the first build: the bytes never change within a process.
    """
    global _PDF_CACHE
    if _PDF_CACHE is not None:
        return _PDF_CACHE

    y = 640
    parts = ["BT", "/F1 18 Tf", f"1 0 0 1 72 {y} Tm", "22 TL"]
    for i, line in enumerate(_PLACEHOLDER_LINES):
        if i == 0:
            parts.append(f"({_pdf_escape(line)}) Tj")
        else:
            parts.append(f"T* ({_pdf_escape(line)}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
         + stream + b"\nendstream"),
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("ascii")
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii")
            + b" /Root 1 0 R >>\nstartxref\n"
            + str(xref_at).encode("ascii") + b"\n%%EOF\n")

    _PDF_CACHE = bytes(out)
    return _PDF_CACHE


# ──────────────────────────────────────────────────────────────────
# Route matching
# ──────────────────────────────────────────────────────────────────


def _segments(template: str) -> List[str]:
    return template.strip("/").split("/") if template.strip("/") else []


def match_template(path: str, template: str) -> Optional[Dict[str, str]]:
    """The path parameters if `path` matches `template`, else None.

    Segment-by-segment rather than by regex, because the only two things a
    template holds are a literal and a `{name}` — and one special case,
    `{name:path}`, which Starlette lets swallow the remaining segments
    (`/api/annotations/{project_id}/{document_path:path}`). A regex for this
    would need the same two rules written less legibly.
    """
    want = _segments(template)
    got = _segments(path)
    params: Dict[str, str] = {}
    for i, seg in enumerate(want):
        if seg.startswith("{") and seg.endswith("}"):
            name = seg[1:-1]
            if ":path" in name:
                # Greedy tail: matches the rest, and must be last.
                name = name.split(":", 1)[0]
                if i >= len(got):
                    return None
                params[name] = "/".join(got[i:])
                return params
            if i >= len(got):
                return None
            params[name] = got[i]
        else:
            if i >= len(got) or got[i] != seg:
                return None
    if len(got) != len(want):
        return None
    return params


def _literal_count(template: str) -> int:
    return sum(1 for s in _segments(template)
               if not (s.startswith("{") and s.endswith("}")))


def resolve_template(path: str,
                     templates) -> Optional[Tuple[str, Dict[str, str]]]:
    """(template, params) for the declared route `path` belongs to.

    THE CANONICAL TEMPLATE COMES FROM THE APP'S OWN ROUTE TABLE, not from
    CANNED. That is what keeps `/api/projects/dob-summary` out of the hands of
    `/api/projects/{project_id}`: both templates match that path, the app
    declares both, and the one with more literal segments is the one the
    router would pick. Matching against CANNED alone would have resolved
    `/api/projects/pending-deletion` — an unlisted route — onto the canned
    project builder, which is the aliasing bug this function exists to avoid.

    Ties broken toward more literal segments, then longer template, which is
    FastAPI's practical behaviour for the shapes this app declares.
    """
    best: Optional[Tuple[str, Dict[str, str]]] = None
    best_key: Tuple[int, int] = (-1, -1)
    for template in templates:
        params = match_template(path, template)
        if params is None:
            continue
        key = (_literal_count(template), len(template))
        if key > best_key:
            best_key = key
            best = (template, params)
    return best


# ──────────────────────────────────────────────────────────────────
# Decision
# ──────────────────────────────────────────────────────────────────


def payload_for(template: Optional[str], ctx: Ctx) -> DemoResponse:
    """What a demo principal gets for this route. NEVER real data.

    Three outcomes and no fourth: a canned payload, a named empty shape, or
    the default empty. There is no "fall through" return value, which is the
    point — the caller has nothing to do with the answer but send it.
    """
    if template is not None:
        builder = CANNED.get(template)
        if builder is not None:
            return builder(ctx)
        shape = EMPTY_SHAPES.get(template)
        if shape == "envelope":
            return DemoResponse(empty_envelope(ctx.limit(50), ctx.skip(0)))
        if shape is not None:
            # Copied, so a builder or a client cannot mutate the table.
            return DemoResponse(list(shape) if isinstance(shape, list)
                                else dict(shape))
    return DemoResponse(dict(DEFAULT_EMPTY))


async def evaluate(
    *, method: str, path: str, request, query, today,
    jwt_secret: Optional[str], jwt_algorithm: str = "HS256",
    demo_principal_document, templates, logbook_types=None,
) -> Optional[DemoResponse]:
    """None if the request may proceed to the router; the demo's answer if not.

    `demo_principal_document` is an awaitable taking the decoded JWT payload
    and returning the caller's user document when that caller is a demo, and
    None otherwise. Injected rather than imported for lib/demo_guard.py's
    reason: the answer is a read of `db.users` through `is_demo`, and this
    module must not import the app.

    EVERY UNCERTAIN ANSWER IS "NOT A DEMO", which here means "pass through",
    and that is the same fail-open this module's write-side sibling uses for
    the same reason: this is not the authenticator. An anonymous or
    undecodable token reaches `get_current_user` and collects a 401. Answering
    canned fiction to a request with no account behind it would turn every
    unauthenticated 401 in the app into a 200 full of invented data.
    """
    from lib import demo_guard  # local: shares the token reader, one spelling

    if str(method or "").strip().upper() not in READ_METHODS:
        return None

    payload, why = demo_guard.decode_principal(
        request, jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm)
    if why != "ok":
        return None

    user = await demo_principal_document(payload)
    if not user:
        return None

    # ── PAST THIS LINE THE CALLER IS A DEMO AND MUST NOT REACH THE ROUTER ──
    #
    # So everything below fails CLOSED, and closed here means empty. A bug in
    # a shaping function must not fall back to `call_next`: that would turn
    # "the logbook builder raised" into "the demo was served the real
    # company's logbooks". An empty panel and a stack trace in the log is a
    # recoverable Tuesday; a leak is not.
    #
    # THE try STARTS HERE AND NOT AT THE TOP OF THE FUNCTION, deliberately. An
    # earlier failure — decoding, or the principal read — belongs to a caller
    # whose demo-ness is UNKNOWN, and answering those with an empty body would
    # blank the product for every real user over one bug in this file. Those
    # two steps cannot raise: `decode_principal` returns a reason rather than
    # throwing, and `demo_principal_document` catches its own lookup failure
    # and falls back to the signed claim (see server.py).
    try:
        # RESOLVED HERE AND NOT IN THE SIGNATURE, because this is the first
        # line that only a demo reaches. `templates` and `today` may each
        # arrive as a callable; the middleware passes callables so that
        # building the 172-entry route list and reading the New York clock
        # happen on demo requests only. Every other request in the app —
        # anonymous, real customer, gate tablet — returned above without
        # paying for either. A plain value is still accepted so a test can
        # hand in a list.
        templates = templates() if callable(templates) else templates
        today = today() if callable(today) else today
        resolved = resolve_template(path, templates)
        template = resolved[0] if resolved else None
        params = resolved[1] if resolved else {}
        return payload_for(
            template, Ctx(params, query, today, user, logbook_types))
    except Exception as err:
        logger.exception(
            "[demo_provider] building %s failed; answering empty: %r",
            path, err)
        return DemoResponse(dict(DEFAULT_EMPTY))


# ──────────────────────────────────────────────────────────────────
# Middleware glue
# ──────────────────────────────────────────────────────────────────


def make_middleware(*, jwt_secret: Optional[str],
                    jwt_algorithm: str = "HS256",
                    demo_principal_document,
                    get_templates,
                    get_today,
                    get_logbook_types=None):
    """A Starlette BaseHTTPMiddleware subclass wired to this app.

    `get_templates` is a zero-argument callable returning the app's declared
    GET route templates, and `get_today` one returning the New York calendar
    date. Both are callables and not values so this module holds no reference
    to the app and no clock — the same discipline lib/demo/shaping.py keeps,
    for the same reason: a demo that renders a fixed day in 2026 is the defect
    that scheme exists to prevent.

    ── THE WHOLE SAFETY PROPERTY IS THE SHAPE OF `dispatch` ──────────────────

    There is one `await call_next(request)` in this file and it is guarded by
    `answer is None`, which `evaluate` returns only for a caller it has
    established is NOT a demo. No demo GET can reach the router, so no handler
    runs, so nothing queries Mongo and nothing calls a paid API. Read that
    function before changing it; an early `return await call_next(...)` added
    anywhere above the demo branch is a silent, total leak.
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # local

    def _safely(fn, fallback):
        """A zero-arg callable that returns `fn()`, or `fallback` if it raises.

        Applied to the injected accessors only, and it returns a CALLABLE
        rather than a value: `evaluate` invokes these on the demo branch, so
        nothing here costs an anonymous or a real customer's request anything.

        No fallback can make this middleware let a demo through — an empty
        template list resolves every path to the default empty, `today=None`
        renders the dataset's anchor day, and an empty registry is an empty
        registry. A failure here degrades the demo's content, never its
        containment.
        """
        def _call():
            try:
                return fn()
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "[demo_provider] accessor failed; using fallback")
                return fallback
        return _call

    _today = _safely(get_today, None)
    _templates = _safely(get_templates, ())
    _types = _safely(get_logbook_types, []) if get_logbook_types else None

    class DemoReadProviderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            answer = await evaluate(
                method=request.method,
                path=request.url.path,
                request=request,
                query=request.query_params,
                today=_today,
                jwt_secret=jwt_secret,
                jwt_algorithm=jwt_algorithm,
                demo_principal_document=demo_principal_document,
                templates=_templates,
                logbook_types=_types,
            )
            if answer is None:
                return await call_next(request)
            try:
                return build_response(answer)
            except Exception as err:
                # Serializing the answer failed — an un-encodable object in a
                # shaping function. Reached only for a demo (`answer` is not
                # None), so the fallback is the same empty body `evaluate`
                # uses, NOT `call_next`. A render bug must not become a route
                # to the real handler.
                logger.exception(
                    "[demo_provider] rendering %s failed; answering empty: %r",
                    request.url.path, err)
                return build_response(DemoResponse(dict(DEFAULT_EMPTY)))

    return DemoReadProviderMiddleware
