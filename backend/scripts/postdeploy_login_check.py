#!/usr/bin/env python3
"""Post-deploy gate: a real account must be able to sign in on the deployed SHA.

WHY THIS EXISTS. On 2026-08-31 every authenticated request returned 500 for any
install that sends X-Client-Version, and it ran all day. Nothing caught it:

  * the backend suite was green -- no test sent the header, so the branch that
    raised KeyError was never entered;
  * /api/version was healthy -- the process was up, it just could not serve an
    authenticated request;
  * POST /api/auth/login returned 200 THE WHOLE TIME. The failure was the
    SECOND call the app makes, GET /api/auth/me, which the user experiences as
    "Login Failed" because AuthContext.login() awaits both.

So a check that logs in and stops would have passed cleanly all day. This one
does not stop there.

BOTH HALVES ARE MANDATORY:

  1. POST /api/auth/login   with X-Client-Version  -> 200
  2. GET  /api/auth/me      with X-Client-Version  -> 200

and the header must be SET, because omitting it skips the exact branch that
broke. The no-header call is checked too, so a repair to one path cannot
silently break the other -- that gap is what hid this for a weekend.

USAGE
  API_BASE=https://api.levelog.com \\
  SMOKE_EMAIL=... SMOKE_PASSWORD=... \\
  [EXPECT_SHA=<full or short sha>] \\
  python backend/scripts/postdeploy_login_check.py

Exits 0 if every assertion holds, 1 otherwise. Prints no secret: not the
password, not the token, not the response bodies.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

CLIENT_VERSION = "postdeploy-check/1"
TIMEOUT = 20


# ── the part worth testing ──────────────────────────────────────────────────
def evaluate(*, version_status, sha, login_status, me_status,
             me_status_no_header, expect_sha=None):
    """Return a list of failure strings. Empty list means the deploy is good.

    Kept pure so the gate's own logic is tested rather than trusted. The
    network shell below is the only untested part, and it only fetches.
    """
    out = []

    if version_status != 200:
        out.append(f"/api/version returned {version_status}, expected 200")
    elif not sha:
        out.append("/api/version returned no commit sha")

    if expect_sha and sha:
        if not (sha.startswith(expect_sha) or expect_sha.startswith(sha)):
            out.append(
                f"deployed sha {sha[:12]} does not match expected "
                f"{expect_sha[:12]} -- the deploy did not land")

    # THE HALF THAT ALWAYS PASSED
    if login_status != 200:
        out.append(f"POST /api/auth/login returned {login_status}, expected 200")

    # THE HALF THAT WOULD HAVE CAUGHT 2026-08-31
    if me_status != 200:
        out.append(
            f"GET /api/auth/me with X-Client-Version returned {me_status}, "
            "expected 200 -- login succeeds but the app cannot load the user, "
            "which presents to the operator as 'Login Failed'")

    if me_status_no_header != 200:
        out.append(
            f"GET /api/auth/me WITHOUT X-Client-Version returned "
            f"{me_status_no_header}, expected 200")

    return out


# ── network shell ───────────────────────────────────────────────────────────
def _call(method, url, *, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, {}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:  # DNS, TLS, timeout
        print(f"  !! {method} {url}: {type(e).__name__}", file=sys.stderr)
        return 0, {}


def main():
    base = os.environ.get("API_BASE", "https://api.levelog.com").rstrip("/")
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    expect = (os.environ.get("EXPECT_SHA") or "").strip() or None

    if not email or not password:
        print("SMOKE_EMAIL and SMOKE_PASSWORD must be set.", file=sys.stderr)
        return 2

    hdr = {"X-Client-Version": CLIENT_VERSION}

    vs, vbody = _call("GET", f"{base}/api/version")
    sha = (vbody or {}).get("commit") or ""

    ls, lbody = _call("POST", f"{base}/api/auth/login",
                      body={"email": email, "password": password}, headers=hdr)
    token = (lbody or {}).get("token") or ""

    if token:
        auth = dict(hdr, Authorization=f"Bearer {token}")
        ms, _ = _call("GET", f"{base}/api/auth/me", headers=auth)
        mn, _ = _call("GET", f"{base}/api/auth/me",
                      headers={"Authorization": f"Bearer {token}"})
    else:
        ms = mn = 0

    print(f"  base   {base}")
    print(f"  sha    {sha[:12] or '(none)'}")
    print(f"  login  {ls}")
    print(f"  me     {ms}  (with X-Client-Version)")
    print(f"  me     {mn}  (without)")

    failures = evaluate(version_status=vs, sha=sha, login_status=ls,
                        me_status=ms, me_status_no_header=mn,
                        expect_sha=expect)
    if failures:
        print("\nDEPLOY CHECK FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\nDEPLOY CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
