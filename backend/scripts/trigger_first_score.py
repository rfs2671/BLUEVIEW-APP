"""Trigger a first risk score for the two live projects.

Scoring is on-demand only: the sole writer of a `risk_scores` row is
`recompute_and_persist`, reachable exclusively through
`POST /api/projects/{id}/risk-score/calculate` (see the risk-scoring
diagnosis). Nothing — not project creation, DOB sync, or a cron — calls it
automatically, so a project that no one has "Recalculate now"'d has no score
and every risk UI renders "Scoring". This script issues that POST for both
live projects, then confirms via `GET /api/projects/{id}/risk-score`.

It does NOT modify any code and does NOT touch the DB — it only calls the
authenticated app API, exactly as the RiskScoreDrawer's "Recalculate now"
button does.

SAFETY
  - Reads LEVELOG_API / LEVELOG_EMAIL / LEVELOG_PASSWORD from the environment.
  - Logs in to obtain a JWT and holds it in memory only; the token is NEVER
    printed, logged, or written anywhere.
  - Nothing is hardcoded.

Usage (PowerShell):
    $env:LEVELOG_API      = 'https://api.levelog.com'   # confirm this is prod
    $env:LEVELOG_EMAIL    = '<admin/owner email>'
    $env:LEVELOG_PASSWORD = '<password>'
    python backend/scripts/trigger_first_score.py

Exit codes: 0 = both projects scored and confirmed; 1 = one or more failed.
"""

import os
import sys

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("requests is required: pip install requests")


# The two live projects to score. Names are for readable output only.
PROJECTS = {
    "6a5f63a8147407d3261df2c5": "8 Walworth",
    "6a5f63bc147407d3261df2c7": "588 Boyland",
}


def band(score):
    """Band label from the score, matching RiskScoreCircle.bandFor /
    schema.py::score_band thresholds ([30, 60, 80]). None/uncomputed is the
    neutral pending state, never a low-risk verdict."""
    if score is None:
        return "Scoring"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "Scoring"
    if s != s:  # NaN
        return "Scoring"
    if s <= 30:
        return "LOW RISK"
    if s <= 60:
        return "MODERATE RISK"
    if s <= 80:
        return "HIGH RISK"
    return "CRITICAL RISK"


def main():
    api = os.environ.get("LEVELOG_API")
    email = os.environ.get("LEVELOG_EMAIL")
    password = os.environ.get("LEVELOG_PASSWORD")
    if not api or not email or not password:
        sys.exit("Set LEVELOG_API, LEVELOG_EMAIL and LEVELOG_PASSWORD first.")
    api = api.rstrip("/")

    # ── 1. Log in → JWT (TokenResponse.token). Token stays in memory only;
    #        it is never printed. ─────────────────────────────────────────
    try:
        r = requests.post(
            f"{api}/api/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
    except requests.RequestException as e:
        sys.exit(f"login request failed: {e!r}")
    if not r.ok:
        # Body may contain a plain error detail; it does not contain a token.
        sys.exit(f"login failed: HTTP {r.status_code} {r.text[:200]}")
    token = r.json().get("token")
    if not token:
        sys.exit("login response had no token field")
    headers = {"Authorization": f"Bearer {token}"}  # never printed

    print(f"api={api}  authenticated OK\n")

    failures = 0
    for pid, name in PROJECTS.items():
        print(f"=== {name} ({pid}) ===")

        # ── 2. POST /calculate — writes the risk_scores row. ────────────
        try:
            c = requests.post(
                f"{api}/api/projects/{pid}/risk-score/calculate",
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as e:
            print(f"  POST /calculate -> request error: {e!r}")
            failures += 1
            print()
            continue

        print(f"  POST /calculate -> {c.status_code}")
        if c.ok:
            doc = (c.json() or {}).get("score", {}) or {}
            sc = doc.get("score")
            print(
                f"    score={sc}  band={band(sc)}  "
                f"model_version={doc.get('model_version')}  "
                f"CI=[{doc.get('confidence_low')}, {doc.get('confidence_high')}]"
            )
        else:
            failures += 1
            print(f"    body: {c.text[:300]}")

        # ── 3. GET /risk-score — confirm it now returns the row. ────────
        try:
            g = requests.get(
                f"{api}/api/projects/{pid}/risk-score",
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"  GET /risk-score -> request error: {e!r}")
            failures += 1
            print()
            continue

        print(f"  GET /risk-score -> {g.status_code}")
        if g.ok:
            gs = (g.json() or {}).get("score", {}) or {}
            print(
                f"    returns score={gs.get('score')}  "
                f"band={band(gs.get('score'))}  "
                f"model_version={gs.get('model_version')}  "
                f"calculated_at={gs.get('calculated_at')}"
            )
        else:
            failures += 1
            print(f"    body: {g.text[:200]}")
        print()

    if failures:
        print(f"DONE with {failures} failure(s).")
        return 1
    print("DONE — both projects scored and confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
