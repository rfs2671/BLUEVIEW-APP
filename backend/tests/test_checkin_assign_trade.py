"""Phase 3 — closing the needs_trade_assignment dead-end.

POST /checkins/{id}/assign-trade must:
  • set trade/company on the check-in and CLEAR needs_trade_assignment
  • derive attribution SERVER-SIDE (never from the client body)
  • write an audit_log entry (mirroring review_checkin / checkout)
  • enforce the same per-project auth helper as the review endpoint
  • enforce the project's strict trade roster (no back door around the rule
    register_and_checkin applies)
  • store the CP's answer as the worker's pairing for THIS project in
    worker_project_trades, and write nothing to the global worker document
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


def _catalogue_entries(locale, namespace):
    """{key: literal} DEFINED under one namespace of a catalogue.

    The assign-trade strings used to be declared in a `const TRANSLATIONS`
    map inside app/logbooks/review.jsx. They now live in
    frontend/src/i18n/{en,es}.js under the `review` namespace — see
    frontend/src/i18n/index.js. The screen reaches them via `useT('review')`.
    """
    src = _catalogue_src(locale)
    block = re.search(
        r"\n  %s: \{(.*?)\n  \}," % re.escape(namespace), src, re.S,
    )
    assert block is not None, f"namespace {namespace!r} not found in {locale}.js"
    return dict(re.findall(r"^    (\w+): '(.*)',$", block.group(1), re.M))


class _Result:
    def __init__(self, _id):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.inserted = []
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    async def insert_one(self, doc, *a, **k):
        rec = dict(doc)
        self.inserted.append(rec)
        return _Result("x")

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result("x")

    def last_set(self, field):
        for _q, u in reversed(self.updated):
            s = u.get("$set") or {}
            if field in s:
                return s[field]
        return None


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


_ROSTER = [{"trade": "Carpenter", "company": "Acme Co"}]

_PAIRINGS = "worker_project_trades"


def _pairing_writes(db):
    """The (query, update) upserts server made against worker_project_trades.

    _store_worker_project_trade goes through db[COLLECTION].update_one, which
    the fake records in `.updated` — so the pairing IS observable here.
    """
    return db[_PAIRINGS].updated


def _mk_db(*, roster=None, worker=None):
    db = _FakeDb()
    db.checkins.set_find_one({
        "_id": "chk1", "project_id": "proj1", "worker_id": "w1",
        "worker_name": "Jane Worker", "needs_trade_assignment": True,
        "check_in_time": datetime(2026, 7, 20, tzinfo=timezone.utc),
    })
    db.projects.set_find_one({
        "_id": "proj1", "name": "Test Tower", "company_id": "co_a",
        "trade_assignments": _ROSTER if roster is None else roster,
    })
    db.workers.set_find_one(
        worker if worker is not None else {"_id": "w1", "name": "Jane", "trade": ""},
    )
    return db


def _client(*, role="admin", company_id="co_a", user_id="u1",
            assigned_projects=None, name="Ada Admin"):
    user = {
        "_id": user_id, "id": user_id, "role": role, "company_id": company_id,
        "full_name": name, "assigned_projects": assigned_projects or [],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


def _post(db, body, **kw):
    client, cleanup = _client(**kw)
    try:
        with patch.object(server, "db", db):
            return client.post("/api/checkins/chk1/assign-trade", json=body)
    finally:
        cleanup()


_GOOD = {"trade": "Carpenter", "company": "Acme Co"}


class AssignTradeTest(unittest.TestCase):

    def test_assigns_and_clears_flag(self):
        db = _mk_db()
        resp = _post(db, _GOOD)
        self.assertEqual(resp.status_code, 200, resp.text)

        self.assertEqual(db.checkins.last_set("trade"), "Carpenter")
        self.assertEqual(db.checkins.last_set("company"), "Acme Co")
        self.assertEqual(db.checkins.last_set("worker_trade"), "Carpenter")
        # The flag is cleared — this is what makes the row leave the queue.
        self.assertIs(db.checkins.last_set("needs_trade_assignment"), False)
        self.assertFalse(resp.json()["needs_trade_assignment"])

    def test_attribution_is_server_derived(self):
        db = _mk_db()
        resp = _post(db, {**_GOOD, "trade_assigned_by": "HACKER",
                          "trade_assigned_by_name": "Not Me"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.checkins.last_set("trade_assigned_by"), "u1")
        self.assertEqual(
            db.checkins.last_set("trade_assigned_by_name"), "Ada Admin",
        )
        self.assertIsInstance(db.checkins.last_set("trade_assigned_at"), datetime)

    def test_writes_audit_log(self):
        db = _mk_db()
        _post(db, _GOOD)
        self.assertEqual(len(db.audit_logs.inserted), 1)
        entry = db.audit_logs.inserted[0]
        self.assertEqual(entry["action"], "checkin_assign_trade")
        self.assertEqual(entry["resource_type"], "checkin")
        self.assertEqual(entry["resource_id"], "chk1")
        self.assertEqual(entry["details"], _GOOD)

    # ── roster enforcement ───────────────────────────────────────────────

    def test_pair_must_be_on_the_roster(self):
        db = _mk_db()
        resp = _post(db, {"trade": "Plumber", "company": "Rogue LLC"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(db.checkins.updated, [])

    def test_empty_roster_rejected_with_409(self):
        db = _mk_db(roster=[])
        resp = _post(db, _GOOD)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(db.checkins.updated, [])

    def test_missing_fields_rejected(self):
        db = _mk_db()
        self.assertEqual(_post(db, {"trade": "Carpenter"}).status_code, 400)
        self.assertEqual(_post(db, {}).status_code, 400)

    # ── authorization (shared helper) ────────────────────────────────────

    def test_wrong_company_admin_forbidden(self):
        db = _mk_db()
        resp = _post(db, _GOOD, company_id="co_other", assigned_projects=[])
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(db.checkins.updated, [])

    def test_assigned_cp_allowed(self):
        db = _mk_db()
        resp = _post(db, _GOOD, role="cp", company_id="co_other",
                     user_id="cp1", assigned_projects=["proj1"], name="Carl CP")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.checkins.last_set("trade_assigned_by"), "cp1")

    def test_missing_checkin_404(self):
        db = _mk_db()
        db.checkins.set_find_one(None)
        self.assertEqual(_post(db, _GOOD).status_code, 404)

    # ── per-project pairing side effect ──────────────────────────────────

    def test_answer_is_stored_as_this_projects_pairing(self):
        """The CP's answer lands in worker_project_trades keyed on
        (worker_id, project_id) — the only place trade/company live."""
        db = _mk_db(worker={"_id": "w1", "name": "Jane", "trade": ""})
        _post(db, _GOOD)
        writes = _pairing_writes(db)
        self.assertEqual(len(writes), 1, "no pairing was written")
        query, update = writes[-1]
        self.assertEqual(query, {"worker_id": "w1", "project_id": "proj1"})
        self.assertEqual(update["$set"]["trade"], "Carpenter")
        self.assertEqual(update["$set"]["company"], "Acme Co")

    def test_nothing_is_written_to_the_global_worker_document(self):
        """A worker who already carries a trade from another project keeps it
        untouched — the assignment is scoped to this project's pairing, so the
        global worker document is never written at all."""
        db = _mk_db(worker={"_id": "w1", "name": "Jane", "trade": "Electrician"})
        _post(db, _GOOD)
        self.assertIsNone(db.workers.last_set("trade"))
        self.assertIsNone(db.workers.last_set("company"))
        # The answer still had to go somewhere — the pairing, not the worker.
        self.assertEqual(len(_pairing_writes(db)), 1)


class AssignTradeFrontendTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = (_BACKEND.parent / "frontend" / "app" / "logbooks"
                   / "review.jsx").read_text(encoding="utf-8")

    def test_assign_ui_wired(self):
        self.assertIn("checkinsAPI.assignTrade", self.src)
        self.assertIn("handleAssign", self.src)
        # Options come from the project's roster, not free text.
        self.assertIn("roster.map", self.src)

    def test_assign_strings_are_english_only(self):
        """The assign-trade copy exists in EN, and DELIBERATELY not in ES.

        FLIPPED, not deleted. A logbook is a legal record filed with the DOB, so
        it is written in English; Spanish belongs where a WORKER must understand
        what he is signing. `review` is the CP's approve / send-home /
        assign-trade decision surface, so it is EN-only by operator ruling.

        The half of this that actually protects the feature is unchanged: every
        key the screen needs must EXIST, or the CP sees a raw key. What changed
        is that ES is now asserted ABSENT rather than translated, so a
        well-meant translation cannot quietly reappear.
        """
        en = _catalogue_entries("en", "review")
        # Absence is checked on the raw source: _catalogue_entries asserts the
        # namespace EXISTS, which is the opposite of what we need here.
        es_src = _catalogue_src("es")
        self.assertIsNone(
            re.search(r"^\s*review:\s*\{", es_src, re.M),
            "review must not be translated — EN-only by ruling",
        )
        for key in ("assignTrade", "chooseTrade", "assigned", "assignFailed",
                    "noRoster", "cancel"):
            self.assertIn(key, en, f"missing EN {key}")
        # Was: es["assignTrade"] == "Asignar oficio", plus EN/ES key parity.
        # Both asserted the rule that has been reversed. The surviving check is
        # the one that still protects the CP — the EN copy is real prose, not a
        # placeholder or the key echoed back.
        self.assertEqual(en["assignTrade"], "Assign trade")

    def test_assign_screen_consumes_the_translation_layer(self):
        """The keys above must be reached through src/i18n, not re-declared."""
        self.assertIn("from '../../src/i18n'", self.src)
        self.assertIn("useT('review')", self.src)
        for key in ("assignTrade", "chooseTrade", "noRoster"):
            self.assertIn(f"t('{key}')", self.src, f"{key} never rendered")

    def test_api_client_method_exists(self):
        api = (_BACKEND.parent / "frontend" / "src" / "utils"
               / "api.js").read_text(encoding="utf-8")
        self.assertIn("assignTrade:", api)
        self.assertIn("/assign-trade", api)


if __name__ == "__main__":
    unittest.main()
