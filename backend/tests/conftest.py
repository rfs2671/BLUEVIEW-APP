"""Autouse test-isolation fixture (2026-07-23).

Two process-global singletons leaked state across the suite, making it
order-dependent (see docs/audits/test-isolation-2026-07-23.md):

  1. lib/rate_limits.py::_COUNTER — a single fixed-window request counter
     shared by every TestClient call (100 req / 60s, keyed per client IP;
     the whole suite shares one IP). It was never reset between test files,
     so it saturated mid-run and later HTTP tests received 429 instead of
     their real response. reset_counter() existed but was called only inside
     test_c2_rate_limits.py for that file's own tests.

  2. lib/feature_flags.py::_CACHE — a 60s-TTL module cache. A test that
     resolves a flag left it cached for the next test, which then saw a stale
     value even after patching server.db to a fixture with a different flag
     doc.

  3. server.py::checkin_rate_limiter and server.py::auth_rate_limiter
     (server.py:573-574) — a SECOND, older pair of process-global
     limiters, of a different class (server.py:557 RateLimiter) than
     lib/rate_limits.py's, and entirely unknown to it. checkin_rate_limiter
     caps 30 req / 60s per IP and guards the three public check-in
     endpoints; every TestClient call in the suite shares the IP
     "testclient", so its key is a single suite-wide bucket. Eight test
     files POST to /api/checkin/register-and-checkin; past ~30 such POSTs
     inside one rolling 60s window the endpoint starts returning
     429 {"detail": "Too many requests. Please wait a moment."} to
     whichever file happens to be running then. Because the window is
     wall-clock, WHICH file gets starved varies run to run — this was the
     suite's remaining order-dependence. Resetting the lib/ counter did
     nothing for it: they are two unrelated objects.

This fixture resets ALL of them before every test so no test inherits counter
saturation or a cached flag from a predecessor.

It does NOT set RATE_LIMITS_DISABLED: the limiter stays live so
test_c2_rate_limits.py continues to exercise the real middleware. We clear
the counter's accumulated state, we do not disable the feature. Both reset
calls are idempotent, so they do not conflict with test_c2_rate_limits.py's
own setUp/tearDown reset_counter() calls, nor with tests that intentionally
saturate the counter within their own body (this fixture runs before the
test, not during it).
"""

import os
import sys
from pathlib import Path

import pytest

# conftest is imported before the individual test modules run their own
# sys.path setup, so make the backend package importable here first.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from lib import rate_limits  # noqa: E402
from lib import feature_flags  # noqa: E402


def _reset_server_ip_limiters():
    """Clear server.py's own in-memory RateLimiter instances.

    Looked up through sys.modules rather than imported at conftest load so
    this stays a no-op for tests that never import server (and so conftest
    does not force server's heavy import on collection). server.RateLimiter
    RateLimiter now exposes reset() (added alongside this change), so this
    calls the public method instead of reaching into the private `_hits`
    dict — the reach broke the moment the class changed. No test asserts on these two
    limiters, so clearing them cannot mask a real expectation — the one
    suite test that does assert a 429 (test_c2_rate_limits.py:577) exercises
    the lib/rate_limits.py middleware, a different object with a different
    response body.
    """
    server = sys.modules.get("server")
    if server is None:
        return
    for name in ("checkin_rate_limiter", "auth_rate_limiter",
                 "gate_failure_rate_limiter"):
        limiter = getattr(server, name, None)
        reset = getattr(limiter, "reset", None)
        if callable(reset):
            reset()
        else:  # pragma: no cover — older server.py without RateLimiter.reset
            hits = getattr(limiter, "_hits", None)
            if hits is not None:
                hits.clear()


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Reset the process-global rate-limit counters and null the feature-flag
    cache before every test. Function-scoped + autouse → runs for all tests."""
    rate_limits.reset_counter()
    _reset_server_ip_limiters()
    feature_flags.cache_invalidate(None)
    yield
