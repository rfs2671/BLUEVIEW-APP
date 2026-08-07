"""Phase 2 — the CP/admin review area.

Covers GET /checkins/project/{id}/flagged:
  • returns unreviewed expired-SST rows AND needs-trade rows
  • excludes rows already reviewed, and unflagged rows
  • is COMPANY-SCOPED (the sibling project-checkins endpoints are not —
    that gap is deliberately not inherited)
  • an assigned CP is authorized; an unrelated user is not
  • attaches the worker's card image + explicit flag_reasons

Plus a frontend invariant: the review screen lives under /logbooks so the
CP route guard admits it without widening CP access.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

_FRONTEND = _BACKEND.parent / "frontend"
_I18N = _FRONTEND / "src" / "i18n"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


def _catalogue_src(locale):
    """Raw source of one translation catalogue."""
    return (_I18N / f"{locale}.js").read_text(encoding="utf-8")


def _catalogue_keys(locale, namespace):
    """Key names DEFINED under one namespace of a catalogue.

    These definitions used to be a `const TRANSLATIONS` map inside
    app/logbooks/review.jsx. They now live in frontend/src/i18n/{en,es}.js,
    one namespace per screen — see frontend/src/i18n/index.js. Same strings,
    new home; the screen reads them through `useT('review')`.
    """
    src = _catalogue_src(locale)
    block = re.search(
        r"\n  %s: \{(.*?)\n  \},"% re.escape(namespace), src, re.S,
    )
    assert block is not None, f"namespace {namespace!r} not found in {locale}.js"
    return set(re.findall(r"^    (\w+):", block.group(1), re.M))


class _Result:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id
        self.matched_count = 1
        self.modified_count = 1


class _FakeFind:
    """Supports .sort().skip().limit().to_list() and plain .to_list()."""

    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.docs = []
        self.last_query = None

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    def find(self, query=None, *a, **k):
        self.last_query = query
        return _FakeFind(self.docs)

    async def insert_one(self, doc, *a, **k):
        return _Result("x")

    async def update_one(self, q, u, *a, **k):
        return _Result("x")


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


def _mk_db(*, checkin_docs=None, company_id="co_a"):
    db = _FakeDb()
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": company_id,
        "trade_assignments": [{"trade": "Carpenter", "company": "Acme Co"}],
    })
    db.checkins.docs = checkin_docs or []
    db.workers.docs = [{
        "_id": "w1", "name": "Jane Worker", "company": "Acme Co",
        "trade": "Carpenter", "osha_number": "SST999",
        "osha_card_image": "data:image/jpeg;base64,CARD",
    }]
    return db


def _client(*, role="admin", company_id="co_a", user_id="u1",
            assigned_projects=None):
    user = {
        "_id": user_id, "id": user_id, "role": role,
        "company_id": company_id, "full_name": "Ada Admin",
        "assigned_projects": assigned_projects or [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


_EXPIRED_ROW = {
    "_id": "chk_exp", "project_id": "proj1", "worker_id": "w1",
    "worker_name": "Jane Worker", "sst_status": "expired",
    "sst_expiration": datetime(2020, 1, 1, tzinfo=timezone.utc),
    "check_in_time": datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
}
_NEEDS_TRADE_ROW = {
    "_id": "chk_trade", "project_id": "proj1", "worker_id": "w1",
    "worker_name": "Jane Worker", "needs_trade_assignment": True,
    "check_in_time": datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
}


class FlaggedEndpointTest(unittest.TestCase):

    def _get(self, db, **kw):
        client, cleanup = _client(**kw)
        try:
            with patch.object(server, "db", db):
                return client.get("/api/checkins/project/proj1/flagged")
        finally:
            cleanup()

    def test_returns_both_flag_types_with_reasons(self):
        db = _mk_db(checkin_docs=[_EXPIRED_ROW, _NEEDS_TRADE_ROW])
        resp = self._get(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["count"], 2)

        by_id = {i["id"]: i for i in data["items"]}
        self.assertIn("expired_sst", by_id["chk_exp"]["flag_reasons"])
        self.assertIn("needs_trade", by_id["chk_trade"]["flag_reasons"])

    def test_query_targets_unreviewed_expired_or_needs_trade(self):
        db = _mk_db(checkin_docs=[_EXPIRED_ROW])
        self._get(db)
        q = db.checkins.last_query
        self.assertEqual(q["project_id"], "proj1")
        branches = q["$or"]
        expired = next(b for b in branches if b.get("sst_status") == "expired")
        # Unreviewed = field absent OR explicitly null.
        self.assertEqual(
            expired["$or"],
            [{"review_decision": {"$exists": False}}, {"review_decision": None}],
        )
        self.assertIn({"needs_trade_assignment": True}, branches)

    def test_attaches_card_image_and_worker_context(self):
        db = _mk_db(checkin_docs=[_EXPIRED_ROW])
        data = self._get(db).json()
        item = data["items"][0]
        self.assertEqual(item["osha_card_image"], "data:image/jpeg;base64,CARD")
        self.assertEqual(item["worker_company"], "Acme Co")
        self.assertEqual(item["worker_trade"], "Carpenter")

    def test_returns_project_roster_for_trade_assignment(self):
        db = _mk_db(checkin_docs=[_NEEDS_TRADE_ROW])
        data = self._get(db).json()
        self.assertEqual(
            data["trade_assignments"],
            [{"trade": "Carpenter", "company": "Acme Co"}],
        )

    # ── authorization ────────────────────────────────────────────────────

    def test_company_scoped_wrong_company_admin_forbidden(self):
        """The sibling endpoints have NO tenant scoping — this one must."""
        db = _mk_db(checkin_docs=[_EXPIRED_ROW], company_id="co_a")
        resp = self._get(db, company_id="co_other", assigned_projects=[])
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_assigned_cp_allowed(self):
        db = _mk_db(checkin_docs=[_EXPIRED_ROW])
        resp = self._get(
            db, role="cp", company_id="co_other",
            user_id="cp1", assigned_projects=["proj1"],
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unassigned_cp_forbidden(self):
        db = _mk_db(checkin_docs=[_EXPIRED_ROW])
        resp = self._get(
            db, role="cp", company_id="co_other",
            user_id="cp2", assigned_projects=["other_project"],
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_missing_project_404(self):
        db = _mk_db()
        db.projects.set_find_one(None)
        resp = self._get(db)
        self.assertEqual(resp.status_code, 404, resp.text)


class SharedAuthHelperTest(unittest.TestCase):
    """review_checkin and the flagged list must share one auth rule."""

    def test_helper_used_by_every_per_project_endpoint(self):
        """Every per-project check-in endpoint must go through the one shared
        auth helper rather than re-implementing the rule."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("def user_can_act_on_project", src)
        # Definition + one call site per per-project endpoint (flagged,
        # review, assign-trade). Grows as endpoints are added; must never
        # shrink back to inline copies.
        call_sites = src.count("user_can_act_on_project(") - 1
        self.assertGreaterEqual(
            call_sites, 3,
            f"expected >=3 call sites, found {call_sites}",
        )
        # And no endpoint should re-inline the rule.
        self.assertNotIn("is_company_admin = (", src.replace(
            src[src.index("def user_can_act_on_project"):
                src.index("def user_can_act_on_project") + 900], "",
        ), "per-project auth rule re-inlined outside the helper")

    def test_helper_logic(self):
        proj = {"company_id": "co_a"}
        # Company admin.
        self.assertTrue(server.user_can_act_on_project(
            proj, "p1", {"role": "admin", "company_id": "co_a"}))
        # Wrong company.
        self.assertFalse(server.user_can_act_on_project(
            proj, "p1", {"role": "admin", "company_id": "co_b"}))
        # Assigned CP.
        self.assertTrue(server.user_can_act_on_project(
            proj, "p1", {"role": "cp", "company_id": "co_b",
                         "assigned_projects": ["p1"]}))
        # Unassigned CP.
        self.assertFalse(server.user_can_act_on_project(
            proj, "p1", {"role": "cp", "company_id": "co_b",
                         "assigned_projects": ["p2"]}))


class ReviewScreenRoutingTest(unittest.TestCase):

    def test_screen_lives_under_logbooks_for_cp_access(self):
        """The CP guard allows /logbooks/* only. The review screen must sit
        there so a CP can reach it WITHOUT widening the allowlist."""
        screen = _BACKEND.parent / "frontend" / "app" / "logbooks" / "review.jsx"
        self.assertTrue(screen.exists(), "review screen must be under app/logbooks")

    def test_cp_allowlist_not_widened(self):
        layout = (_BACKEND.parent / "frontend" / "app" / "_layout.jsx").read_text(
            encoding="utf-8",
        )
        m = re.search(r"if \(isCp\) \{(.*?)\n    \}", layout, re.S)
        self.assertIsNotNone(m, "CP guard block not found")
        block = m.group(1)
        # Still exactly the original four allowances.
        self.assertIn("pathname.startsWith('/logbooks')", block)
        for extra in ("/project", "/site", "/workers", "/review'"):
            self.assertNotIn(extra, block, f"CP allowlist widened with {extra}")

    def test_review_screen_is_bilingual(self):
        """Every review string exists in BOTH catalogues.

        The definitions moved out of review.jsx into src/i18n/{en,es}.js, so
        the parity check follows them there. The screen half of the invariant
        — that review.jsx actually reads the layer — is asserted below.
        """
        en = _catalogue_keys("en", "review")
        es = _catalogue_keys("es", "review")
        self.assertTrue(en, "review namespace is empty in en.js")
        self.assertEqual(en - es, set(), f"missing ES: {sorted(en - es)}")
        self.assertEqual(es - en, set(), f"missing EN: {sorted(es - en)}")
        # Spot-check that ES is really Spanish and not an English copy.
        self.assertIn("'Revisión de Registros'", _catalogue_src("es"))
        self.assertIn("'Check-In Review'", _catalogue_src("en"))

    def test_review_screen_consumes_the_translation_layer(self):
        """review.jsx must render through src/i18n, not a local string map."""
        src = (_FRONTEND / "app" / "logbooks"
               / "review.jsx").read_text(encoding="utf-8")
        self.assertIn("from '../../src/i18n'", src)
        self.assertIn("useT('review')", src)
        self.assertNotIn("const TRANSLATIONS", src,
                         "review.jsx re-grew a local string map")


if __name__ == "__main__":
    unittest.main()
