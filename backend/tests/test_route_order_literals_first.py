"""A parameterised route must never be registered before a literal sibling.

FastAPI matches in REGISTRATION order and returns the FIRST match. So

    @api_router.get("/permit-renewals/{renewal_id}")     # declared first
    @api_router.get("/permit-renewals/dashboard-alerts") # declared 600 lines later

makes the second one DEAD. A call to /permit-renewals/dashboard-alerts ran
get_renewal with renewal_id="dashboard-alerts", matched no document, and
returned 404 "Renewal not found" -- which a dashboard reads as "no alerts"
rather than as a bug. `health-status` was dead the same way.

THIS FILE GUARDS THE CLASS, NOT THOSE TWO. The failure is silent by
construction: the shadowed route returns a plausible answer, nothing logs, and
no import breaks. It is only ever found by someone enumerating routes, which is
how these were found -- by accident, alongside two other dead endpoints
(GET /checkin/{id}/companies and POST /workers/register).

WHAT IS DELIBERATELY ALLOWED, and why an exact-duplicate check is not enough:
a parameterised route may precede a literal one on a DIFFERENT method, because
FastAPI matches the method too. The check below is per (method, path).

    python backend/tests/test_route_order_literals_first.py
"""

import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402


def _registered():
    """(index, method, path, name) for every mounted route, in order."""
    out = []
    for i, r in enumerate(server.app.routes):
        path = getattr(r, "path", None)
        if not path:
            continue
        for m in (getattr(r, "methods", None) or set()):
            if m in ("HEAD", "OPTIONS"):
                continue
            out.append((i, m, path, getattr(r, "name", "?")))
    return out


def _matcher(path):
    """A regex for what this path pattern actually matches.

    `{x}` consumes ONE segment; `{x:path}` consumes the rest. Anything else is
    a literal and is escaped -- so a path containing regex metacharacters
    cannot accidentally widen the match.
    """
    parts = []
    for seg in path.strip("/").split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            parts.append(".+" if ":path" in seg else "[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "$")


# ── KNOWN AND ACCEPTED, each with a reason on the record ────────────────────
#
# An exemption list can hide the next regression, so this is an EXACT allowlist
# of (dead, eater) pairs. Anything not named here fails, including a new
# shadowing of one of these same paths.
#
# These three are card_audit's gate landing pages, shadowed by
# GET /checkin/{project_id}/{tag_id} in server.py -- a decorator that runs at
# import (line ~20163) while app.include_router(gate_router) runs much later
# (~33948).
#
# THEY ARE DEAD CODE, NOT BROKEN BEHAVIOUR, and that is why they are exempt
# rather than fixed here. The live handler serves backend/checkin.html, which
# IS the gate page workers actually use -- the language toggle, the trade/company
# roster select, the OSHA capture, all of it. card_audit's landing page is an
# alternative implementation that has never run in production.
#
# Un-shadowing them would SWITCH THE GATE to a different implementation on a
# live jobsite. That is a product decision, not a route-ordering cleanup, and it
# is reported separately.
KNOWN_SHADOWED = {
    ("GET /checkin/{project_id}/{gate_id}", "GET /checkin/{project_id}/{tag_id}"),
    ("GET /checkin/success/{sign_in_id}", "GET /checkin/{project_id}/{tag_id}"),
    # gate_landing is itself dead, so its shadowing of checkin_success is
    # theoretical -- but it is real in the registration table and is named so
    # the allowlist stays exact.
    ("GET /checkin/success/{sign_in_id}", "GET /checkin/{project_id}/{gate_id}"),
}


def find_shadowed(include_known=False):
    """Every route that can never be reached, with the route that eats it."""
    routes = _registered()
    out = []
    for a_i, a_m, a_p, a_n in routes:
        if "{" not in a_p:
            continue                      # a literal shadows nothing
        rx = _matcher(a_p)
        for b_i, b_m, b_p, b_n in routes:
            if b_i <= a_i or b_m != a_m or b_p == a_p:
                continue
            if rx.match(b_p):
                pair = (f"{b_m} {b_p}", f"{a_m} {a_p}")
                if not include_known and pair in KNOWN_SHADOWED:
                    continue
                out.append({
                    "dead": pair[0], "dead_name": b_n,
                    "eater": pair[1], "eater_name": a_n,
                })
    return out


class TheCheckItselfWorks(unittest.TestCase):
    """A sweep that silently matches nothing passes forever."""

    def test_the_app_actually_mounted_routes(self):
        self.assertGreater(len(_registered()), 200)

    def test_the_matcher_treats_a_param_as_one_segment(self):
        rx = _matcher("/a/{id}")
        self.assertTrue(rx.match("/a/literal"))
        self.assertFalse(rx.match("/a/b/c"))

    def test_the_matcher_lets_path_params_span_segments(self):
        rx = _matcher("/a/{rest:path}")
        self.assertTrue(rx.match("/a/b/c/d"))

    def test_the_matcher_escapes_literals(self):
        """A dot in a real path must not act as a wildcard."""
        rx = _matcher("/files/report.pdf")
        self.assertTrue(rx.match("/files/report.pdf"))
        self.assertFalse(rx.match("/files/reportXpdf"))

    def test_it_detects_a_KNOWN_bad_ordering(self):
        """The detector, proved against the exact shape it exists to catch --
        rather than trusting that a clean sweep means a working sweep."""
        from fastapi import FastAPI
        probe = FastAPI()

        @probe.get("/things/{thing_id}")
        async def _get_thing(thing_id: str):
            return thing_id

        @probe.get("/things/summary")
        async def _summary():
            return {}

        real, server.app = server.app, probe
        try:
            found = find_shadowed()
        finally:
            server.app = real
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["dead"], "GET /things/summary")

    def test_it_does_NOT_flag_a_correct_ordering(self):
        """Literal first is the fix, and must not be reported as the defect."""
        from fastapi import FastAPI
        probe = FastAPI()

        @probe.get("/things/summary")
        async def _summary():
            return {}

        @probe.get("/things/{thing_id}")
        async def _get_thing(thing_id: str):
            return thing_id

        real, server.app = server.app, probe
        try:
            found = find_shadowed()
        finally:
            server.app = real
        self.assertEqual(found, [])

    def test_it_does_NOT_flag_a_different_METHOD(self):
        """FastAPI matches the method too, so GET /{id} does not shadow
        POST /literal. Flagging it would train people to ignore this test."""
        from fastapi import FastAPI
        probe = FastAPI()

        @probe.get("/things/{thing_id}")
        async def _get_thing(thing_id: str):
            return thing_id

        @probe.post("/things/summary")
        async def _summary():
            return {}

        real, server.app = server.app, probe
        try:
            found = find_shadowed()
        finally:
            server.app = real
        self.assertEqual(found, [])


class NoRouteIsUnreachable(unittest.TestCase):

    def test_no_parameterised_route_shadows_a_literal_sibling(self):
        """THE CLASS. Not the two permit-renewals routes -- any of them, now or
        later. A shadowed route returns a plausible answer and logs nothing, so
        nothing else in CI can catch it."""
        found = find_shadowed()
        if found:
            lines = [
                f"  {f['dead']}  ({f['dead_name']}) is DEAD"
                f"\n      eaten by earlier {f['eater']}  ({f['eater_name']})"
                for f in found
            ]
            self.fail(
                "unreachable route(s) — a parameterised route is registered "
                "before a literal sibling:\n" + "\n".join(lines)
            )

    def test_every_KNOWN_shadowed_pair_is_still_real(self):
        """AN ALLOWLIST THAT OUTLIVES ITS SUBJECT IS A LIE. If one of these is
        fixed or deleted, the entry must go with it -- otherwise the set quietly
        grants a future route the same exemption."""
        actual = {(f["dead"], f["eater"]) for f in find_shadowed(include_known=True)}
        stale = KNOWN_SHADOWED - actual
        self.assertEqual(stale, set(),
                         "allowlist entries no longer describe a real shadowing")

    def test_the_known_set_is_exactly_the_card_audit_gate_pages(self):
        """Named, so the exemption cannot silently grow."""
        self.assertEqual(len(KNOWN_SHADOWED), 3)
        for dead, _eater in KNOWN_SHADOWED:
            self.assertTrue(dead.startswith("GET /checkin/"), dead)

    def test_no_exact_duplicate_method_path_pairs(self):
        """The cruder sibling of the same defect: the second registration of an
        identical (method, path) can never run."""
        seen = {}
        dups = []
        for _i, m, p, n in _registered():
            if (m, p) in seen:
                dups.append(f"{m} {p}: {seen[(m, p)]} then {n}")
            else:
                seen[(m, p)] = n
        self.assertEqual(dups, [])


class ThePermitRenewalRoutesAreReachable(unittest.TestCase):
    """The two instances that prompted this, pinned by ORDER rather than by
    absence-from-a-list, so a future move re-breaks the test."""

    def _index(self, path):
        for i, m, p, _n in _registered():
            if m == "GET" and p == path:
                return i
        self.fail(f"route disappeared: GET {path}")

    def test_dashboard_alerts_registers_before_the_id_route(self):
        self.assertLess(self._index("/api/permit-renewals/dashboard-alerts"),
                        self._index("/api/permit-renewals/{renewal_id}"))

    def test_health_status_registers_before_the_id_route(self):
        self.assertLess(self._index("/api/permit-renewals/health-status"),
                        self._index("/api/permit-renewals/{renewal_id}"))

    def test_all_three_are_still_mounted(self):
        paths = {p for _i, m, p, _n in _registered() if m == "GET"}
        for p in ("/api/permit-renewals",
                  "/api/permit-renewals/dashboard-alerts",
                  "/api/permit-renewals/health-status",
                  "/api/permit-renewals/{renewal_id}"):
            self.assertIn(p, paths)

    def test_the_handlers_were_MOVED_not_rewritten(self):
        """This PR reorders registration. It does not change behaviour, and in
        particular it does not touch the conditional company_id check inside
        get_renewal -- that is the next PR, reported before building."""
        src = (BACKEND / "permit_renewal.py").read_text(encoding="utf-8")
        self.assertIn('if company_id and renewal.get("company_id") != company_id:', src)
        self.assertIn('"""Latest DOB NOW health check result (admin only)."""', src)
        self.assertIn('"""Active renewal alerts for the dashboard."""', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
