"""THE DEMO ACCOUNT NEVER WRITES — one guard, at the auth layer.

OPERATOR RULING: "Server rejects every write from a demo account (one guard at
the auth layer, not per route)."

──────────────────────────────────────────────────────────────────
Why a middleware and NOT a per-route dependency
──────────────────────────────────────────────────────────────────

A `Depends(refuse_demo)` on each mutating route is the shape this explicitly
is not, for a reason that survives the ruling: THE NEXT ROUTE ANYBODY ADDS IS
UNGUARDED BY DEFAULT. There are 153 non-safe routes in this app today; a rule
that has to be remembered 154 times has already failed. A middleware is the
one place that cannot be forgotten, because a route does not opt into it.

The precedent is `lib/rate_limits.py` — same shape, same file layout: a pure
`evaluate()` that decides, a `make_middleware()` that glues, and the
application wiring in server.py. Tests exercise `evaluate()` without an app,
and the middleware stays small enough to read in one screen.

──────────────────────────────────────────────────────────────────
WHERE IT SITS IN THE STACK, AND WHY THAT IS NOT ARBITRARY
──────────────────────────────────────────────────────────────────

Starlette's `add_middleware` PREPENDS, so the LAST registration is the
OUTERMOST layer. server.py registers, in source order:

    demo write guard   (this module)   <- innermost
    rate limiter       (lib/rate_limits.py)
    X-Request-Id       (@app.middleware)
    CORS               (CountingCORSMiddleware)   <- outermost

which makes the runtime order CORS -> request-id -> rate limit -> this -> app.
Three properties are bought by that position, and each was paid for once
already elsewhere in this codebase:

  1. INSIDE CORS, BECAUSE A SHORT-CIRCUIT RETURNS ITS OWN RESPONSE. The
     comment on the CORS block records what happens otherwise: the rate
     limiter used to sit outside CORS, its 429 carried no
     Access-Control-Allow-Origin, and the browser reported a CORS
     misconfiguration instead of the real status. A demo refusal that the web
     build cannot read is a refusal the "Demo mode, nothing is saved" toast
     can never fire on — it would surface as a network error instead.

  2. INSIDE THE REQUEST-ID MIDDLEWARE, so a refusal gets an id and its own
     `[req] id=... POST /api/... -> 403` line. A write that was refused is
     exactly the kind of request a support call asks about.

  3. INSIDE THE RATE LIMITER, because this guard does a DATABASE READ (see
     below) and a layer that reads Mongo must not be reachable faster than
     the limiter allows. A demo account hammering writes burns its
     rate-limit window before it reaches this find_one.

──────────────────────────────────────────────────────────────────
THE REFUSAL SHAPE
──────────────────────────────────────────────────────────────────

    HTTP 403 Forbidden
    {
      "error":  "demo_read_only",
      "detail": "Demo mode, nothing is saved.",
      "method": "POST",
      "path":   "/api/projects"
    }

FLAT, like the limiter's 429 body and unlike `require_approved`'s
`{"detail": {"error": "account_pending"}}`. Both idioms already exist in this
app and the client has a reader for each; flat is the one chosen here because
this body is produced by a MIDDLEWARE, which builds its own JSONResponse and
is not passed through FastAPI's HTTPException wrapper. Nesting it by hand
would imitate a wrapper that is not running.

`error` is the stable key a client branches on, and it is a CONSTANT STRING,
not a sentence — the sentence is `detail`, which is where the generic axios
error extractor already looks, so a screen with no demo-specific handling
still shows the right words instead of "Request failed with status code 403".

`method` and `path` are there so the toast can be quiet about the routine
case and a log can name the specific one. They are NOT a contract for
behaviour; nothing should branch on them.

──────────────────────────────────────────────────────────────────
WHAT IS EXEMPT, AND WHY THE LIST IS THIS SHORT
──────────────────────────────────────────────────────────────────

A demo account that cannot sign in is not a demo. `POST /api/auth/login` is a
non-safe method and it is the ONE thing a demo principal must be able to do.

`POST /api/auth/register` is on the list for a subtler reason: the client's
request interceptor (frontend/src/utils/api.js) attaches
`Authorization: Bearer <token>` to EVERY request when a token is on disk. A
device whose last session was a demo therefore sends that demo's token to the
login and signup screens. Without these two entries, a stale demo token on a
phone would refuse the login of the REAL account the person is trying to
reach — the failure would look like "this app will not let anybody sign in",
and it would be caused by an account that is not the one signing in.

NOTHING ELSE IS EXEMPT, INCLUDING THE READS THAT ARE SPELLED AS POSTS. Two
exist and are named here rather than quietly admitted:

    POST /api/permit-renewals/check-eligibility   a declared dry-run
    POST /api/users/me/notification-preferences/preview   replays history

Both compute and return; neither persists. They are refused anyway, because
every entry on an exemption list is a hole that has to be re-audited forever,
and neither is needed to sign in or to read. The cost of refusing them is a
toast on a demo screen that does not exist yet — the demo data provider is a
separate change, and whoever builds it can revisit these two DELIBERATELY
with the reason written down, which is the point of naming them here.

──────────────────────────────────────────────────────────────────
WHAT DECIDES "IS A DEMO", AND WHY IT IS NOT THE TOKEN
──────────────────────────────────────────────────────────────────

The JWT carries a `role` claim, and reading it would make this guard free.
The user DOCUMENT is read instead, and the claim is only a fallback for when
the document cannot be read at all. The reason is one direction of drift:

  * A demo who is PROMOTED to a paying CP keeps a token that still says
    "demo" for up to thirty days (JWT_EXPIRATION_HOURS is 720, and
    `_reissue_token_if_stale` COPIES the old claims forward rather than
    re-reading the account). Trusting the claim would refuse every write that
    customer makes until somebody thought to tell them to log out.
  * The reverse drift — a document that says demo under a token that does not
    — cannot happen through any API path today (ROLE_DEMO is not in
    ASSIGNABLE_ROLES) but would be a silent bypass if it ever did.

Reading the document makes this guard's answer IDENTICAL to
`is_demo(current_user)` as every route sees it, which is the invariant the
census test asserts rather than re-deriving the answer twice.

The cost is one indexed `find_one` per non-safe authenticated request. Writes
are a minority of traffic and every one of these handlers already makes
several queries, so this is a small addition to a request that was never
cheap — and it is on the write path only: a GET never reaches the lookup.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import jwt

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Vocabulary
# ──────────────────────────────────────────────────────────────────


# RFC 9110's safe methods, plus OPTIONS and TRACE. A method not in here is a
# write as far as this guard is concerned — which deliberately includes any
# method somebody invents later, because the default for an unknown verb on a
# security boundary must be "refuse".
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# The value a client branches on. Never a sentence, never localised, never
# reworded — a client that compares this string is the whole reason it exists.
DEMO_REFUSAL_ERROR = "demo_read_only"

# The words the operator asked for, verbatim, because this is what the toast
# shows. It lives here and not on the client so the server and the toast can
# never disagree about what a demo refusal says.
DEMO_REFUSAL_MESSAGE = "Demo mode, nothing is saved."

DEMO_REFUSAL_STATUS = 403

# See the module docstring. This is EXACTLY the set of non-safe paths a demo
# principal may still reach, and its shortness is the feature. Exact match on
# the full request path — no prefixes, because `/api/auth/` as a prefix would
# silently admit `/api/auth/password`, `/api/auth/profile` and
# `/api/auth/me/deletion-request`, which are three real writes.
EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
})


def is_write(method) -> bool:
    """True for a method this guard refuses a demo principal.

    NORMALISES, because `request.method` is upper-case from Starlette but this
    is also called directly by tests and by the census with whatever the route
    table holds.
    """
    return str(method or "").strip().upper() not in SAFE_METHODS


def is_exempt(path) -> bool:
    return str(path or "") in EXEMPT_PATHS


def refusal_body(method, path) -> Dict:
    """The 403 body. One builder, so the middleware and any route that refuses
    for the same reason cannot drift into two shapes."""
    return {
        "error": DEMO_REFUSAL_ERROR,
        "detail": DEMO_REFUSAL_MESSAGE,
        "method": str(method or "").strip().upper(),
        "path": str(path or ""),
    }


def build_403_response(body: Dict):
    """Starlette imported lazily, so this module stays importable in a test
    environment that has no FastAPI — same reason lib/rate_limits.py does it."""
    from fastapi.responses import JSONResponse  # local import

    return JSONResponse(body, status_code=DEMO_REFUSAL_STATUS)


# ──────────────────────────────────────────────────────────────────
# Decision
# ──────────────────────────────────────────────────────────────────


def bearer_token(request) -> Optional[str]:
    """The raw JWT off the Authorization header, or None.

    Header lookup is case-insensitive in Starlette, but the second form is
    kept for the plain dict-headers objects the unit tests hand in.
    """
    auth = request.headers.get("authorization") or request.headers.get(
        "Authorization")
    if not auth:
        return None
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


def decode_principal(
    request, *, jwt_secret: Optional[str], jwt_algorithm: str = "HS256",
) -> Tuple[Optional[Dict], str]:
    """(payload, why) for the caller's token.

    `why` is one of "ok", "no_token", "undecodable", "site_device" and exists
    so the caller does not have to distinguish None-because-anonymous from
    None-because-broken by inspecting a bare None.

    AN UNDECODABLE TOKEN IS NOT A DEMO, AND LETTING IT THROUGH IS NOT A HOLE.
    This guard does not authenticate anybody: `get_current_user` runs after it
    and answers 401 for the same token. Refusing here instead would replace
    that 401 with a 403 saying "Demo mode, nothing is saved" — a false
    statement about a request that had no account behind it at all.
    """
    token = bearer_token(request)
    if not token:
        return None, "no_token"
    if not jwt_secret:
        # No secret configured means no token in this process can be verified.
        # server.py refuses to run in that state; this branch exists so a unit
        # test constructing the middleware without one gets a defined answer.
        return None, "undecodable"
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[jwt_algorithm])
    except Exception:
        return None, "undecodable"
    # A SITE DEVICE IS NEVER A DEMO, and its `sub` is a db.site_devices id, not
    # a user id — looking it up in db.users would find nothing and read as
    # "not a demo" by accident rather than on purpose. The gate tablet is the
    # single most write-heavy caller in the product; it gets a named branch.
    if payload.get("site_mode"):
        return payload, "site_device"
    return payload, "ok"


async def evaluate(
    *, method: str, path: str, request,
    jwt_secret: Optional[str], jwt_algorithm: str = "HS256",
    demo_principal_check,
) -> Optional[Dict]:
    """None if the request may proceed; the 403 body if it may not.

    `demo_principal_check` is an awaitable callable taking the decoded JWT
    payload and returning True for a demo account. It is injected rather than
    imported because the answer lives in server.py — it is a read of
    `db.users` through `is_demo`, and this module must not import the app.
    """
    if not is_write(method):
        return None
    if is_exempt(path):
        return None

    payload, why = decode_principal(
        request, jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm)
    if why != "ok":
        return None

    if not await demo_principal_check(payload):
        return None

    return refusal_body(method, path)


# ──────────────────────────────────────────────────────────────────
# Middleware glue
# ──────────────────────────────────────────────────────────────────


def make_middleware(*, jwt_secret: Optional[str],
                    jwt_algorithm: str = "HS256",
                    demo_principal_check):
    """A Starlette BaseHTTPMiddleware subclass wired to this app's secret.

    Registered FIRST in server.py so it ends up innermost — see the module
    docstring for what each enclosing layer is doing for it.
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # local

    class DemoWriteGuardMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            body = await evaluate(
                method=request.method,
                path=request.url.path,
                request=request,
                jwt_secret=jwt_secret,
                jwt_algorithm=jwt_algorithm,
                demo_principal_check=demo_principal_check,
            )
            if body is None:
                return await call_next(request)
            logger.info(
                "[demo] refused %s %s", body["method"], body["path"])
            return build_403_response(body)

    return DemoWriteGuardMiddleware
