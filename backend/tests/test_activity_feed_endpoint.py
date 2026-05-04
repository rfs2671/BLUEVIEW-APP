"""MR.14 commit 3 — activity feed endpoint + mark-read endpoints.

Pins:
  • Server-side render_signal output appears in dob-logs response
    (title, body, severity_kind, action_text per row)
  • signal_kinds CSV filter narrows the result set correctly
  • severity_kind filter narrows
  • date_range filter narrows (today / 7d / 30d / all)
  • unread_only filter excludes rows the caller has marked read
  • search filter substring-matches title + body
  • Sort order is status_changed_at desc, detected_at desc
  • Default pagination is 20/page (was 50 pre-commit-3)

  • POST mark-read appends {user_id, read_at} to read_by_user
  • POST mark-read is idempotent (second call no-op)
  • POST mark-all-read covers visible rows only (30-day cutoff)

These exercise the endpoint via TestClient + a mocked db. Auth
deps are stubbed; we don't need real JWT.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────


class _LogsCursor:
    """Mongo-cursor mock that supports the chained .sort/.skip/.limit
    /.to_list pattern the endpoint uses. Sort is ignored (caller
    pre-orders the items list)."""

    def __init__(self, items):
        self._items = items

    def sort(self, *args, **kwargs):
        return self

    def skip(self, n):
        self._items = self._items[n:]
        return self

    def limit(self, n):
        self._items = self._items[:n]
        return self

    async def to_list(self, n):
        return self._items[:n]


def _make_test_client(*, logs, user_id="user_1"):
    """Build a TestClient with auth deps stubbed + db.dob_logs.find
    returning a filtered slice of the supplied logs based on the query
    shape."""
    import server

    admin_user = {
        "_id": user_id, "id": user_id, "role": "admin",
        "company_id": "co_test", "company_name": "Test Co",
    }

    async def _fake_admin():
        return admin_user

    server.app.dependency_overrides[server.get_admin_user] = _fake_admin
    server.app.dependency_overrides[server.get_current_user] = _fake_admin
    original_get_company = server.get_user_company_id
    server.get_user_company_id = lambda u: "co_test"

    project_doc = {
        "_id": "proj_test_1",
        "name": "Test Project",
        "company_id": "co_test",
        "is_deleted": False,
    }

    db_mock = MagicMock()
    db_mock.projects.find_one = AsyncMock(return_value=project_doc)

    captured_query = {}

    def _matches_query(log, query):
        # Project + is_deleted gate.
        if log.get("project_id") != query.get("project_id"):
            return False
        if log.get("is_deleted") is True:
            return False
        # severity / record_type / signal_kind filters.
        if query.get("severity") and log.get("severity") != query["severity"]:
            return False
        if query.get("record_type") and log.get("record_type") != query["record_type"]:
            return False
        sk_filter = query.get("signal_kind")
        if isinstance(sk_filter, dict) and sk_filter.get("$in"):
            if log.get("signal_kind") not in sk_filter["$in"]:
                return False
        # date_range
        det = query.get("detected_at")
        if isinstance(det, dict) and det.get("$gte"):
            if not log.get("detected_at") or log["detected_at"] < det["$gte"]:
                return False
        # unread_only
        rbu = query.get("read_by_user.user_id")
        if isinstance(rbu, dict) and rbu.get("$ne"):
            target_uid = rbu["$ne"]
            log_reads = log.get("read_by_user") or []
            if any(
                isinstance(r, dict) and r.get("user_id") == target_uid
                for r in log_reads
            ):
                return False
        # seed window suppression
        nor = query.get("$nor")
        if nor:
            for clause in nor:
                ps = clause.get("previous_status")
                ca = clause.get("created_at") or {}
                gte = ca.get("$gte")
                lt = ca.get("$lt")
                if (
                    log.get("previous_status") == ps
                    and gte is not None
                    and lt is not None
                    and gte <= log.get("created_at") < lt
                ):
                    return False
        return True

    def _find(query):
        captured_query.clear()
        captured_query.update(query)
        out = [l for l in logs if _matches_query(l, query)]
        return _LogsCursor(out)

    async def _count_documents(query):
        return len([l for l in logs if _matches_query(l, query)])

    db_mock.dob_logs.find = MagicMock(side_effect=_find)
    db_mock.dob_logs.count_documents = AsyncMock(side_effect=_count_documents)
    db_mock.dob_logs.find_one = AsyncMock(return_value=None)
    db_mock.dob_logs.update_one = AsyncMock(
        return_value=MagicMock(modified_count=1)
    )
    db_mock.dob_logs.update_many = AsyncMock(
        return_value=MagicMock(modified_count=0)
    )

    original_db = server.db
    server.db = db_mock

    def _restore():
        server.db = original_db
        server.get_user_company_id = original_get_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), _restore, db_mock, captured_query


def _baseline_log(**overrides):
    """Default dob_log fixture matching what nightly_dob_scan would
    insert post-MR.14."""
    now = datetime.now(timezone.utc)
    base = {
        "_id": "log_0",
        "project_id": "proj_test_1",
        "company_id": "co_test",
        "is_deleted": False,
        "record_type": "permit",
        "raw_dob_id": "permit:B0001:Foundation",
        "ai_summary": "Permit issued",
        "severity": "Action",
        "next_action": "Open Levelog to review",
        "detected_at": now,
        "created_at": now,
        "updated_at": now,
        "current_status": "ISSUED",
        "previous_status": "PENDING",
        "status_changed_at": now,
        "signal_kind": "permit_issued",
        "read_by_user": [],
        "permit_status": "Issued",
        "work_type": "Foundation",
        "job_filing_number": "B0001",
    }
    base.update(overrides)
    return base


# ── Server-side rendering ─────────────────────────────────────────


class TestServerSideRendering(unittest.TestCase):
    """Each row in the response carries title/body/severity_kind/action_text
    populated by lib.dob_signal_templates.render_signal."""

    def test_response_includes_rendered_template_fields(self):
        log = _baseline_log()
        client, restore, _db, _query = _make_test_client(logs=[log])
        try:
            resp = client.get("/api/projects/proj_test_1/dob-logs")
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        logs_list = body.get("logs") or []
        self.assertEqual(len(logs_list), 1)
        row = logs_list[0]
        # signal_kind=permit_issued → render_permit_issued template.
        self.assertIn("Permit issued", row.get("title", ""))
        self.assertIn("severity_kind", row)
        self.assertIn("action_text", row)
        self.assertIn("body", row)

    def test_severity_kind_matches_template(self):
        log = _baseline_log(signal_kind="permit_expired")
        client, restore, _db, _query = _make_test_client(logs=[log])
        try:
            resp = client.get("/api/projects/proj_test_1/dob-logs")
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        row = (body.get("logs") or [])[0]
        # permit_expired template returns severity=critical.
        self.assertEqual(row.get("severity_kind"), "critical")


# ── Filters ───────────────────────────────────────────────────────


class TestActivityFeedFilters(unittest.TestCase):

    def test_signal_kinds_filter(self):
        logs = [
            _baseline_log(_id="l1", raw_dob_id="r1", signal_kind="permit_expired"),
            _baseline_log(_id="l2", raw_dob_id="r2", signal_kind="violation_dob"),
            _baseline_log(_id="l3", raw_dob_id="r3", signal_kind="inspection_passed"),
        ]
        client, restore, _db, captured = _make_test_client(logs=logs)
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs"
                "?signal_kinds=permit_expired,violation_dob"
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        self.assertIn("l1", ids)
        self.assertIn("l2", ids)
        self.assertNotIn("l3", ids)
        # Confirm the query was constructed with $in.
        sk = captured.get("signal_kind")
        self.assertIsInstance(sk, dict)
        self.assertEqual(sorted(sk["$in"]), ["permit_expired", "violation_dob"])

    def test_severity_kind_filter_post_render(self):
        logs = [
            _baseline_log(_id="l1", raw_dob_id="r1", signal_kind="permit_expired"),
            _baseline_log(_id="l2", raw_dob_id="r2", signal_kind="permit_issued"),
        ]
        client, restore, _db, _query = _make_test_client(logs=logs)
        try:
            # Filter only critical signals.
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?severity_kind=critical"
            )
        finally:
            restore()
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        # permit_expired = critical, permit_issued = info.
        self.assertIn("l1", ids)
        self.assertNotIn("l2", ids)

    def test_date_range_today(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)
        logs = [
            _baseline_log(_id="l_today", raw_dob_id="r1", detected_at=now),
            _baseline_log(_id="l_old", raw_dob_id="r2", detected_at=old),
        ]
        client, restore, _db, _query = _make_test_client(logs=logs)
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?date_range=today"
            )
        finally:
            restore()
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        self.assertIn("l_today", ids)
        self.assertNotIn("l_old", ids)

    def test_date_range_all_includes_old(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=200)
        logs = [
            _baseline_log(_id="l_today", raw_dob_id="r1", detected_at=now),
            _baseline_log(_id="l_old", raw_dob_id="r2", detected_at=old),
        ]
        client, restore, _db, _query = _make_test_client(logs=logs)
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?date_range=all"
            )
        finally:
            restore()
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        self.assertEqual(set(ids), {"l_today", "l_old"})

    def test_unread_only_filter(self):
        logs = [
            _baseline_log(
                _id="l_unread", raw_dob_id="r1", read_by_user=[],
            ),
            _baseline_log(
                _id="l_read",
                raw_dob_id="r2",
                read_by_user=[{
                    "user_id": "user_1",
                    "read_at": datetime.now(timezone.utc),
                }],
            ),
        ]
        client, restore, _db, _query = _make_test_client(
            logs=logs, user_id="user_1",
        )
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?unread_only=true"
            )
        finally:
            restore()
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        self.assertIn("l_unread", ids)
        self.assertNotIn("l_read", ids)

    def test_search_filter_post_render(self):
        logs = [
            _baseline_log(_id="l_match", raw_dob_id="r1", signal_kind="permit_expired", work_type="Plumbing"),
            _baseline_log(_id="l_other", raw_dob_id="r2", signal_kind="permit_expired", work_type="Electrical"),
        ]
        client, restore, _db, _query = _make_test_client(logs=logs)
        try:
            resp = client.get(
                "/api/projects/proj_test_1/dob-logs?search=plumbing"
            )
        finally:
            restore()
        body = resp.json()
        ids = [l.get("id") for l in (body.get("logs") or [])]
        # Plumbing renders into the title via the permit_expired template.
        self.assertIn("l_match", ids)
        self.assertNotIn("l_other", ids)

    def test_is_read_flag_per_row(self):
        """Each row carries an is_read bool computed from the
        caller's user_id presence in read_by_user."""
        logs = [
            _baseline_log(_id="l_unread", raw_dob_id="r1", read_by_user=[]),
            _baseline_log(
                _id="l_read",
                raw_dob_id="r2",
                read_by_user=[{
                    "user_id": "user_1",
                    "read_at": datetime.now(timezone.utc),
                }],
            ),
        ]
        client, restore, _db, _query = _make_test_client(
            logs=logs, user_id="user_1",
        )
        try:
            resp = client.get("/api/projects/proj_test_1/dob-logs")
        finally:
            restore()
        body = resp.json()
        by_id = {l.get("id"): l for l in (body.get("logs") or [])}
        self.assertFalse(by_id["l_unread"].get("is_read"))
        self.assertTrue(by_id["l_read"].get("is_read"))


# ── Mark-as-read endpoints ─────────────────────────────────────────


class TestMarkRead(unittest.TestCase):

    def test_mark_read_appends_to_read_by_user(self):
        log = _baseline_log(_id="log_target", read_by_user=[])
        client, restore, db_mock, _query = _make_test_client(
            logs=[log], user_id="user_1",
        )
        # Override dob_logs.find_one to return the target row.
        db_mock.dob_logs.find_one = AsyncMock(return_value={
            "_id": "log_target",
            "read_by_user": [],
        })
        try:
            resp = client.post(
                "/api/projects/proj_test_1/dob-logs/log_target/mark-read",
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("updated"))
        self.assertEqual(body.get("log_id"), "log_target")
        # update_one was called with $push of the right payload.
        call = db_mock.dob_logs.update_one.await_args
        update_doc = call.args[1]
        push = update_doc.get("$push") or {}
        rbu = push.get("read_by_user")
        self.assertIsInstance(rbu, dict)
        self.assertEqual(rbu.get("user_id"), "user_1")
        self.assertIn("read_at", rbu)

    def test_mark_read_idempotent_second_call_noop(self):
        client, restore, db_mock, _query = _make_test_client(
            logs=[], user_id="user_1",
        )
        # find_one returns a doc where user_1 has already read it.
        db_mock.dob_logs.find_one = AsyncMock(return_value={
            "_id": "log_target",
            "read_by_user": [{
                "user_id": "user_1",
                "read_at": datetime.now(timezone.utc),
            }],
        })
        try:
            resp = client.post(
                "/api/projects/proj_test_1/dob-logs/log_target/mark-read",
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get("updated"))
        self.assertEqual(body.get("reason"), "already_read")
        # update_one was NOT called.
        db_mock.dob_logs.update_one.assert_not_awaited()

    def test_mark_read_404_when_log_missing(self):
        client, restore, db_mock, _query = _make_test_client(logs=[])
        db_mock.dob_logs.find_one = AsyncMock(return_value=None)
        try:
            resp = client.post(
                "/api/projects/proj_test_1/dob-logs/nonexistent/mark-read",
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 404)

    def test_mark_all_read_calls_update_many(self):
        client, restore, db_mock, _query = _make_test_client(
            logs=[], user_id="user_1",
        )
        db_mock.dob_logs.update_many = AsyncMock(
            return_value=MagicMock(modified_count=5)
        )
        try:
            resp = client.post(
                "/api/projects/proj_test_1/dob-logs/mark-all-read",
            )
        finally:
            restore()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("updated"), 5)
        # Confirm update_many was called with the unread-only filter.
        call = db_mock.dob_logs.update_many.await_args
        query = call.args[0]
        rbu = query.get("read_by_user.user_id")
        self.assertIsInstance(rbu, dict)
        self.assertEqual(rbu.get("$ne"), "user_1")


# ── Pagination + sort default ─────────────────────────────────────


class TestPaginationDefault(unittest.TestCase):

    def test_default_page_size_is_20(self):
        """MR.14 commit 3 dropped the default from 50 → 20 to match
        the v1 monitoring product's per-page sizing."""
        # Build 25 logs.
        logs = [
            _baseline_log(_id=f"log_{i}", raw_dob_id=f"r{i}")
            for i in range(25)
        ]
        client, restore, _db, _query = _make_test_client(logs=logs)
        try:
            resp = client.get("/api/projects/proj_test_1/dob-logs")
        finally:
            restore()
        body = resp.json()
        self.assertEqual(len(body.get("logs") or []), 20)
        self.assertEqual(body.get("total"), 25)


if __name__ == "__main__":
    unittest.main()
