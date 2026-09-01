"""Phase C2 — rate limiting + abuse protection.

Single-module, in-memory rate limiter wired as a FastAPI middleware.
Pre-launch hardening for the public-facing endpoints — auth, the
Phase B3 onboarding flow, and the user-scoped data surfaces.

──────────────────────────────────────────────────────────────────
Why custom (not slowapi decorators)
──────────────────────────────────────────────────────────────────

slowapi is in requirements.txt (the spec asked for it; it's the
canonical FastAPI rate-limit shim) but its decorator-per-endpoint
ergonomic would touch ~40 routes and create N points of regression
risk. A middleware that reads from a single config table is a
tighter fit for our scale: one match call per request, one config
edit when adding a new endpoint, identifier resolution centralised
once.

The middleware delegates accounting to a `_FixedWindowCounter` —
an in-process dict-of-(count, window_start) keyed by
(identifier, route_key). Cheap, deterministic, no external state.
The trade-off pinned in the runbook: when we scale Railway
horizontally, each instance gets its own counter, so the effective
cap is N×limit. v1 ships single-instance so this is safe; v1.1
should swap to a Redis-backed slowapi or limits.MovingWindowRateLimiter.

──────────────────────────────────────────────────────────────────
Identifier resolution
──────────────────────────────────────────────────────────────────

For each rule the config picks ``"user"`` or ``"ip"``:

  user — decode the JWT from Authorization: Bearer <token>; use
         the `sub` claim. If the token is missing, malformed, or
         expired, fall back to IP (so an unauthenticated request
         to a user-scoped endpoint is still rate limited, just by
         the weaker IP key).

  ip   — read X-Forwarded-For (Vercel / Cloudflare hand us the
         caller's real IP here) → fall back to request.client.host.

──────────────────────────────────────────────────────────────────
429 response
──────────────────────────────────────────────────────────────────

  HTTP 429 Too Many Requests
  Retry-After: <seconds>
  X-RateLimit-Limit: <human readable>
  X-RateLimit-Remaining: 0
  Body: {
    "error": "rate_limit_exceeded",
    "retry_after_seconds": N,
    "limit": "X requests per Y"
  }

Sentry gets a `capture_message(...level="warning")` on hit so the
ops dashboard can spot abuse. Sentry's own deduplication folds
repeats into a single issue with a count.

──────────────────────────────────────────────────────────────────
Excluded paths
──────────────────────────────────────────────────────────────────

Health probes (`/api/health`, `/health`, `/healthz`), root, and
docs (`/docs`, `/redoc`, `/openapi.json`) bypass the limiter
entirely. Vercel + uptime checks need them.

──────────────────────────────────────────────────────────────────
Disable switch
──────────────────────────────────────────────────────────────────

Setting RATE_LIMITS_DISABLED=true on Railway turns the middleware
into a no-op without redeploying app code. Use only as an
emergency lever — see runbook §11.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────


# Each rule is (METHOD, path_pattern, limit_string, identifier_kind).
#
# METHOD: an HTTP method ("GET", "POST", "PATCH", "PUT", "DELETE")
#         or "ANY" to match every method.
# path_pattern: Express-style; `{name}` or `{name:rest}` placeholders
#               match a single URL segment. The name is ignored —
#               only segment count + literal text matter.
# limit_string: "<count>/<window>" where window is one of
#               "second", "minute", "minutes", "hour", "hours",
#               and an optional integer multiplier ("5/5 minutes").
# identifier_kind: "user" or "ip" — see module docstring.
#
# Order matters. Most-specific patterns must appear before catch-alls
# so the matcher stops at the right rule. We rely on first-match
# semantics — see _match_rule.
RATE_LIMITS: List[Tuple[str, str, str, str]] = [
    # ── Auth (highest abuse risk; brute-force + signup spam) ──────
    ("POST", "/api/auth/login", "5/5 minutes", "ip"),
    ("POST", "/api/auth/register", "3/1 hour", "ip"),
    # The forgot/reset routes don't currently exist (no
    # implementation as of Phase C2) — config entries here so
    # adding them later inherits a sane limit without a separate
    # config edit.
    ("POST", "/api/auth/forgot-password", "3/1 hour", "ip"),
    ("POST", "/api/auth/reset-password", "5/1 hour", "ip"),

    # ── Phase B3 onboarding (user-scoped, prevents step-spam) ─────
    ("POST", "/api/onboarding/company", "30/5 minutes", "user"),
    ("POST", "/api/onboarding/project", "30/5 minutes", "user"),
    ("POST", "/api/onboarding/filing-reps", "30/5 minutes", "user"),
    ("PATCH", "/api/users/me/onboarding-step", "30/5 minutes", "user"),

    # ── Notification preferences (user-scoped) ────────────────────
    # Read endpoints get a higher cap (60/min) since the FE polls
    # them for live state; write endpoints get tighter caps.
    ("GET", "/api/users/me/notification-preferences", "60/1 minute", "user"),
    ("PATCH", "/api/users/me/notification-preferences", "30/5 minutes", "user"),
    ("PUT", "/api/users/me/notification-preferences", "30/5 minutes", "user"),
    ("POST", "/api/users/me/notification-preferences/preview",
     "60/1 minute", "user"),
    ("GET", "/api/projects/{id}/notification-preferences/{user_id}",
     "60/1 minute", "user"),
    ("PATCH", "/api/projects/{id}/notification-preferences/{user_id}",
     "30/5 minutes", "user"),
    ("PUT", "/api/projects/{id}/notification-preferences/{user_id}",
     "30/5 minutes", "user"),
    ("DELETE", "/api/projects/{id}/notification-preferences/{user_id}",
     "10/5 minutes", "user"),

    # ── Project / company management (user-scoped) ────────────────
    ("POST", "/api/projects", "10/5 minutes", "user"),
    # The actual project-update endpoint is PUT in this codebase;
    # spec said PATCH. Pin both so the limit applies regardless of
    # which verb the FE uses.
    ("PUT", "/api/projects/{id}", "30/5 minutes", "user"),
    ("PATCH", "/api/projects/{id}", "30/5 minutes", "user"),
    ("DELETE", "/api/projects/{id}", "10/5 minutes", "user"),

    # ── Admin (IP-scoped — should never get hit hard) ─────────────
    # /api/admin/_sentry_test gets its own tighter rule because it
    # raises by design and we don't want it abused into a
    # never-ending Sentry feed.
    ("GET", "/api/admin/_sentry_test", "5/5 minutes", "ip"),
    # Catch-all for /api/admin/* sits LAST in the admin section so
    # the more-specific rule above wins.
    ("ANY", "/api/admin/{rest:path}", "60/1 minute", "ip"),
]

# Anything under /api/* not matched by an explicit rule above.
# Per-user since most authenticated endpoints will land here.
DEFAULT_LIMIT = "100/1 minute"
DEFAULT_LIMIT_KIND = "user"


# Paths that bypass the limiter entirely. Includes uptime probes,
# docs, and the static-asset root. Match-prefix semantics — any
# request whose path starts with one of these is exempt.
EXCLUDED_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/healthz",
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static/",
)


# ──────────────────────────────────────────────────────────────────
# Limit string parsing
# ──────────────────────────────────────────────────────────────────


_WINDOW_SECONDS = {
    "second": 1,
    "seconds": 1,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
}


def _parse_limit(limit_string: str) -> Tuple[int, int, str]:
    """Parse '<count>/<n> <unit>' or '<count>/<unit>' → (count,
    seconds, human_readable). Examples:

      '5/5 minutes'   → (5, 300, '5 requests per 5 minutes')
      '60/1 minute'   → (60, 60, '60 requests per 1 minute')
      '60/minute'     → (60, 60, '60 requests per 1 minute')
      '3/1 hour'      → (3, 3600, '3 requests per 1 hour')
    """
    parts = limit_string.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Bad limit string: {limit_string!r}")
    count = int(parts[0].strip())
    rhs = parts[1].strip()
    rhs_parts = rhs.split()
    if len(rhs_parts) == 1:
        # Bare unit — '60/minute'.
        unit = rhs_parts[0]
        multiplier = 1
    elif len(rhs_parts) == 2:
        multiplier = int(rhs_parts[0])
        unit = rhs_parts[1]
    else:
        raise ValueError(f"Bad limit string: {limit_string!r}")

    if unit not in _WINDOW_SECONDS:
        raise ValueError(f"Unknown unit {unit!r} in {limit_string!r}")
    seconds = multiplier * _WINDOW_SECONDS[unit]
    human = f"{count} requests per {multiplier} {unit}"
    return count, seconds, human


# ──────────────────────────────────────────────────────────────────
# Path matching
# ──────────────────────────────────────────────────────────────────


def _compile_pattern(pattern: str) -> re.Pattern:
    """Compile an Express-style path pattern into a regex.

      `{name}`        — matches a single URL segment ([^/]+).
                         Use for `{id}`, `{user_id}`, etc.
      `{name:path}`   — matches the remainder of the URL including
                         slashes (.+). Use for catch-all rules
                         like `/api/admin/{rest:path}` that need
                         to span multiple path segments.

    The placeholder name is informational; only the modifier
    (`:path` or absent) and the segment count matter.
    """
    parts = pattern.split("/")
    regex_parts = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            inner = part[1:-1]
            if ":" in inner:
                _name, modifier = inner.split(":", 1)
                if modifier == "path":
                    regex_parts.append(r".+")
                    continue
            regex_parts.append(r"[^/]+")
        else:
            regex_parts.append(re.escape(part))
    return re.compile("^" + "/".join(regex_parts) + "$")


# Compiled rule list — built once at module load.
_COMPILED_RULES: List[Tuple[str, re.Pattern, str, str, str]] = [
    (method, _compile_pattern(pattern), pattern, limit, kind)
    for method, pattern, limit, kind in RATE_LIMITS
]


def _match_rule(method: str, path: str) -> Optional[Tuple[str, str, str]]:
    """Returns (route_key, limit_string, identifier_kind) for the first
    rule that matches the (method, path) pair, or None if nothing
    matches (caller should apply the default).

    route_key is the original pattern string — used as part of the
    counter key so different endpoints with the same identifier
    don't share a counter."""
    method = method.upper()
    for rule_method, regex, pattern, limit, kind in _COMPILED_RULES:
        if rule_method != "ANY" and rule_method != method:
            continue
        if regex.match(path):
            return (pattern, limit, kind)
    return None


# ──────────────────────────────────────────────────────────────────
# In-memory fixed-window counter
# ──────────────────────────────────────────────────────────────────


class _FixedWindowCounter:
    """Per-key fixed-window counter. Cheap, deterministic, no
    external state. Thread-safe (FastAPI may run multiple workers
    per process under uvicorn).

    The fixed-window strategy permits a brief burst at window
    boundaries (worst case 2× the limit in a 1-second crossover).
    For our scale this is acceptable; v1.1 should switch to a
    moving-window strategy via the `limits` package.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: Dict[Tuple[str, str], Tuple[int, float]] = {}

    def hit(self, key: Tuple[str, str], limit: int, window_seconds: float
            ) -> Tuple[bool, int, int]:
        """Try to record one hit against ``key``.

        Returns (allowed, retry_after_seconds, remaining). When
        allowed=True, retry_after_seconds is 0 and remaining is the
        number of hits left in the current window. When allowed=False,
        retry_after_seconds is the integer ceiling of seconds until
        the window rolls over and remaining is 0.
        """
        now = time.monotonic()
        with self._lock:
            count, start = self._counts.get(key, (0, now))
            if now - start >= window_seconds:
                # Window rolled over; reset.
                count, start = 0, now
            new_count = count + 1
            if new_count > limit:
                retry = int(window_seconds - (now - start))
                if retry < 1:
                    retry = 1
                return False, retry, 0
            self._counts[key] = (new_count, start)
            return True, 0, max(limit - new_count, 0)

    def reset(self) -> None:
        """Clear all state. Used by tests; should not be called in
        production."""
        with self._lock:
            self._counts.clear()


# ──────────────────────────────────────────────────────────────────
# Identifier resolution
# ──────────────────────────────────────────────────────────────────


def _client_ip(request) -> str:
    """Best-effort client IP. Vercel / Cloudflare set
    X-Forwarded-For with the original IP at the head; fall back to
    Starlette's request.client.host."""
    xff = request.headers.get("x-forwarded-for") or request.headers.get(
        "X-Forwarded-For"
    )
    if xff:
        # XFF can be a comma-separated chain; the leftmost entry is
        # the original client.
        return xff.split(",", 1)[0].strip() or "unknown"
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip() or "unknown"
    if getattr(request, "client", None) and request.client:
        return request.client.host or "unknown"
    return "unknown"


def _resolve_identifier(
    request, kind: str,
    *, jwt_secret: Optional[str], jwt_algorithm: str = "HS256",
) -> Tuple[str, str]:
    """Returns (identifier, kind_used). When kind=='user' and the
    JWT is missing/invalid, we DOWNGRADE to IP — an unauthenticated
    caller hitting a user-scoped endpoint still gets rate limited
    (by IP) instead of bypassing entirely.
    """
    if kind == "user" and jwt_secret:
        auth = request.headers.get("authorization") or request.headers.get(
            "Authorization"
        )
        if auth and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            try:
                # Local import — keeps the lib module importable in
                # test environments without PyJWT, falls back to IP
                # if not available.
                import jwt  # type: ignore
                payload = jwt.decode(
                    token,
                    jwt_secret,
                    algorithms=[jwt_algorithm],
                )
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}", "user"
            except Exception:
                pass
    # Fall back to IP.
    return f"ip:{_client_ip(request)}", "ip"


# ──────────────────────────────────────────────────────────────────
# Public middleware API
# ──────────────────────────────────────────────────────────────────


def is_excluded_path(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in EXCLUDED_PREFIXES)


def is_disabled() -> bool:
    """Read at every request — flipping the env var on a running
    instance must take effect without a redeploy."""
    return (os.environ.get("RATE_LIMITS_DISABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


# Module-level counter — single shared state for the whole app.
_COUNTER = _FixedWindowCounter()


def reset_counter() -> None:
    """Test helper — clears the shared counter between tests."""
    _COUNTER.reset()


def evaluate(
    *, method: str, path: str, request,
    jwt_secret: Optional[str], jwt_algorithm: str = "HS256",
) -> Optional[Dict]:
    """Decide whether to allow this request. Returns None if allowed
    (caller continues); returns a 429-payload dict if blocked.

    Splitting the decision logic from the FastAPI middleware glue
    lets tests exercise all the code paths without spinning up the
    app — and lets the middleware stay tiny.
    """
    if is_disabled():
        return None
    # A PREFLIGHT IS NOT A REQUEST TO THE RESOURCE. The browser sends OPTIONS
    # before the real call and never sees the body, so counting it means every
    # cross-origin caller spends TWO of its allowance where the native app
    # spends one -- and the one that gets refused is the preflight, which the
    # browser reports as a CORS failure rather than as a rate limit. The
    # request that follows is still counted; this exempts the asking, not the
    # doing.
    if str(method or "").upper() == "OPTIONS":
        return None
    if is_excluded_path(path):
        return None

    matched = _match_rule(method, path)
    if matched is None:
        # Only apply the default to /api/* paths so static asset
        # 404s don't churn through the counter.
        if not path.startswith("/api/"):
            return None
        route_key = "__default__"
        limit_string = DEFAULT_LIMIT
        kind = DEFAULT_LIMIT_KIND
    else:
        route_key, limit_string, kind = matched

    count, window_seconds, human = _parse_limit(limit_string)
    identifier, kind_used = _resolve_identifier(
        request, kind, jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm,
    )
    allowed, retry_after, remaining = _COUNTER.hit(
        (identifier, route_key), count, window_seconds,
    )
    if allowed:
        return None

    return {
        "error": "rate_limit_exceeded",
        "retry_after_seconds": retry_after,
        "limit": human,
        "_route_key": route_key,         # for Sentry breadcrumb
        "_identifier_kind": kind_used,   # for Sentry breadcrumb
    }


def build_429_response(payload: Dict):
    """Convert an evaluate() blocked-payload into a Starlette
    JSONResponse + the spec's headers. Imported lazily so the
    module stays importable in test envs without FastAPI."""
    from fastapi.responses import JSONResponse  # local import

    body = {
        "error": payload["error"],
        "retry_after_seconds": payload["retry_after_seconds"],
        "limit": payload["limit"],
    }
    headers = {
        "Retry-After": str(payload["retry_after_seconds"]),
        "X-RateLimit-Limit": payload["limit"],
        "X-RateLimit-Remaining": "0",
    }
    return JSONResponse(body, status_code=429, headers=headers)


# Lazy import — Starlette only imported when middleware is actually
# instantiated, not at module import time.
def make_middleware(*, jwt_secret: Optional[str],
                    jwt_algorithm: str = "HS256",
                    sentry_capture=None):
    """Return a Starlette BaseHTTPMiddleware subclass configured
    with the supplied secret. Call from server.py:

        app.add_middleware(
            make_middleware(jwt_secret=JWT_SECRET, ...)
        )
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # local

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            payload = evaluate(
                method=request.method,
                path=request.url.path,
                request=request,
                jwt_secret=jwt_secret,
                jwt_algorithm=jwt_algorithm,
            )
            if payload is None:
                return await call_next(request)

            # Best-effort Sentry warning. Sentry's own dedup folds
            # repeats; we don't suppress here.
            if sentry_capture is not None:
                try:
                    sentry_capture(
                        f"rate_limit_exceeded route={payload['_route_key']} "
                        f"kind={payload['_identifier_kind']}",
                        level="warning",
                    )
                except Exception:
                    pass

            return build_429_response(payload)

    return RateLimitMiddleware
