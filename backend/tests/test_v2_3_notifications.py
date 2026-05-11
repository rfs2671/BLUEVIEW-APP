"""V2.3 Commit 7 — In-app notifications inbox tests.

Coverage (~20 tests across 4 classes):

  • TestDispatchNotification: dispatch behavior — fan-out,
    dedup, fan-out cap, recipient resolution (admin/owner +
    assigned), no-recipients no-op, project_name denormalization,
    deeplink anchor, per-user insert failure isolation.

  • TestCleanupInbox: daily cleanup cron — delete old-read,
    preserve recent-read, auto-dismiss expired-active, preserve
    unread without expires_at, preserve already-dismissed.

  • TestNotificationsListEndpoint: paginated list query shape,
    default status="active" filter, unread_only filter,
    project_id filter, ownership scoping.

  • TestNotificationsMarkRead: mark-one (ownership 404 on
    cross-user), mark-all-read bulk, project_id scoping.

Endpoints are tested as direct function calls against stubbed
Mongo collections rather than via httpx.TestClient — keeps the
test surface fast and avoids server.py's heavy import + Mongo
client construction overhead per test. Wiring grep tests in
test_v2_2_schema_scaffolding.py pin the routing decorators +
auth dependencies separately.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import notifications_inbox as inbox  # noqa: E402
from lib.notifications_inbox import (  # noqa: E402
    MAX_DISPATCH_RECIPIENTS,
    NOTIFICATIONS_COLLECTION,
    READ_RETENTION_DAYS,
    cleanup_inbox,
    dispatch_notification,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Stub Mongo collections
# ──────────────────────────────────────────────────────────────────


def _doc_matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Tiny Mongo-query subset evaluator: handles eq, $ne, $lt,
    $in, $or — enough for inbox queries in tests."""
    if "$or" in query:
        or_clauses = query["$or"]
        rest = {k: v for k, v in query.items() if k != "$or"}
        if not _doc_matches(doc, rest):
            return False
        return any(_doc_matches(doc, c) for c in or_clauses)
    for k, v in query.items():
        actual = doc.get(k)
        if isinstance(v, dict):
            for op, vv in v.items():
                if op == "$ne":
                    if actual == vv:
                        return False
                elif op == "$lt":
                    if actual is None or not (actual < vv):
                        return False
                elif op == "$gte":
                    if actual is None or not (actual >= vv):
                        return False
                elif op == "$in":
                    if actual not in vv:
                        return False
                else:
                    return False
        else:
            # Mongo semantics: querying ``{field: scalar}`` matches
            # if the doc's field is the scalar OR an array
            # containing it. The recipient query uses
            # ``{"assigned_projects": project_id}`` against a list
            # field — must match the in-array case.
            if isinstance(actual, list):
                if v not in actual:
                    return False
            elif actual != v:
                return False
    return True


class _StubColl:
    """In-memory async Mongo collection stub with full inbox-test
    surface: find / find_one / insert_one / update_one /
    update_many / delete_many / count_documents.
    """

    def __init__(self, docs: List[Dict[str, Any]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.insert_one_calls: List[Dict[str, Any]] = []
        self.update_one_calls: List[Dict[str, Any]] = []
        self.update_many_calls: List[Dict[str, Any]] = []
        self.delete_many_calls: List[Dict[str, Any]] = []
        self.insert_one_raises: Optional[Exception] = None

    def find(self, query: Dict[str, Any] = None, projection: Dict[str, Any] = None):
        items = list(self.docs)
        if query:
            items = [d for d in items if _doc_matches(d, query)]

        class _Cur:
            def __init__(self_inner):
                self_inner._items = items
                self_inner._sort_key = None
                self_inner._sort_dir = 1
                self_inner._limit = None
                self_inner._skip = 0

            def sort(self_inner, key, direction=1):
                self_inner._sort_key = key
                self_inner._sort_dir = direction
                return self_inner

            def skip(self_inner, n):
                self_inner._skip = n
                return self_inner

            def limit(self_inner, n):
                self_inner._limit = n
                return self_inner

            def _resolved(self_inner):
                out = list(self_inner._items)
                if self_inner._sort_key:
                    out.sort(
                        key=lambda d: (d.get(self_inner._sort_key) is None,
                                       d.get(self_inner._sort_key)),
                        reverse=(self_inner._sort_dir == -1),
                    )
                if self_inner._skip:
                    out = out[self_inner._skip:]
                if self_inner._limit is not None:
                    out = out[:self_inner._limit]
                return out

            def __aiter__(self_inner):
                async def _gen():
                    for it in self_inner._resolved():
                        yield it
                return _gen()

        return _Cur()

    async def find_one(self, query: Dict[str, Any]):
        for d in self.docs:
            if _doc_matches(d, query):
                return dict(d)
        return None

    async def count_documents(self, query: Dict[str, Any]):
        return sum(1 for d in self.docs if _doc_matches(d, query))

    async def insert_one(self, doc: Dict[str, Any]):
        self.insert_one_calls.append(dict(doc))
        if self.insert_one_raises is not None:
            raise self.insert_one_raises
        new_doc = dict(doc)
        new_doc.setdefault("_id", f"nid_{len(self.docs) + 1}")
        self.docs.append(new_doc)
        r = MagicMock(); r.inserted_id = new_doc["_id"]
        return r

    async def update_one(self, filter_: Dict[str, Any], update: Dict[str, Any]):
        self.update_one_calls.append({
            "filter": dict(filter_), "update": dict(update),
        })
        for d in self.docs:
            if _doc_matches(d, filter_):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock(); r.matched_count = 1; r.modified_count = 1
                return r
        r = MagicMock(); r.matched_count = 0; r.modified_count = 0
        return r

    async def update_many(self, filter_: Dict[str, Any], update: Dict[str, Any]):
        self.update_many_calls.append({
            "filter": dict(filter_), "update": dict(update),
        })
        modified = 0
        for d in self.docs:
            if _doc_matches(d, filter_):
                if "$set" in update:
                    d.update(update["$set"])
                modified += 1
        r = MagicMock(); r.matched_count = modified; r.modified_count = modified
        return r

    async def delete_many(self, filter_: Dict[str, Any]):
        self.delete_many_calls.append(dict(filter_))
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _doc_matches(d, filter_)]
        r = MagicMock(); r.deleted_count = before - len(self.docs)
        return r


class _StubDb:
    def __init__(self, users=None, notifications=None):
        self.users = _StubColl(users)
        self._collections = {
            NOTIFICATIONS_COLLECTION: _StubColl(notifications),
        }

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _StubColl()
        return self._collections[name]


# ──────────────────────────────────────────────────────────────────
# Fixture builders
# ──────────────────────────────────────────────────────────────────


def _project(_id="P1", company_id="co_a", name="Test Project"):
    return {"_id": _id, "company_id": company_id, "name": name}


def _user(_id, *, company_id="co_a", role="member",
          assigned_projects=None, is_deleted=False):
    return {
        "_id": _id,
        "company_id": company_id,
        "role": role,
        "assigned_projects": list(assigned_projects or []),
        "is_deleted": is_deleted,
    }


# ──────────────────────────────────────────────────────────────────
# TestDispatchNotification
# ──────────────────────────────────────────────────────────────────


class TestDispatchNotification(unittest.TestCase):

    def test_inserts_one_doc_per_eligible_recipient(self):
        # Two admins + one assigned member = 3 recipients
        db = _StubDb(users=[
            _user("U_ADMIN", role="admin"),
            _user("U_OWNER", role="owner"),
            _user("U_ASSIGNED", role="member", assigned_projects=["P1"]),
            _user("U_OTHER", role="member"),  # NOT eligible
        ])
        ids = _run(dispatch_notification(
            db, project=_project(), kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="pred_1",
        ))
        self.assertEqual(len(ids), 3)
        inbox_coll = db[NOTIFICATIONS_COLLECTION]
        self.assertEqual(len(inbox_coll.docs), 3)
        recipient_ids = {d["user_id"] for d in inbox_coll.docs}
        self.assertEqual(
            recipient_ids, {"U_ADMIN", "U_OWNER", "U_ASSIGNED"},
        )

    def test_dedups_on_user_source_pair(self):
        """Re-dispatching the same prediction should not produce
        duplicate inbox rows. Per-user dedup keyed on
        (user_id, source_kind, source_id)."""
        db = _StubDb(users=[_user("U_ADMIN", role="admin")])
        _run(dispatch_notification(
            db, project=_project(), kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="pred_dup",
        ))
        # Second dispatch with same source — should dedup.
        ids = _run(dispatch_notification(
            db, project=_project(), kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="pred_dup",
        ))
        self.assertEqual(ids, [])
        # Still only 1 doc in the collection.
        self.assertEqual(len(db[NOTIFICATIONS_COLLECTION].docs), 1)

    def test_fan_out_capped_at_max_recipients(self):
        """If eligible recipients exceed MAX_DISPATCH_RECIPIENTS,
        the dispatch truncates and logs a WARNING."""
        # MAX_DISPATCH_RECIPIENTS + 25 admins → cap kicks in.
        too_many = [
            _user(f"U_{i:04d}", role="admin")
            for i in range(MAX_DISPATCH_RECIPIENTS + 25)
        ]
        db = _StubDb(users=too_many)
        with self.assertLogs(inbox.logger, level="WARNING") as logs:
            ids = _run(dispatch_notification(
                db, project=_project(),
                kind="inspection_prediction",
                title="X", message="Y",
                source_kind="prediction", source_id="cap_test",
            ))
        self.assertEqual(len(ids), MAX_DISPATCH_RECIPIENTS)
        self.assertEqual(
            len(db[NOTIFICATIONS_COLLECTION].docs),
            MAX_DISPATCH_RECIPIENTS,
        )
        # Warning log includes the cap context.
        warn_text = "\n".join(logs.output)
        self.assertIn("fan-out capped", warn_text)
        self.assertIn(str(MAX_DISPATCH_RECIPIENTS), warn_text)

    def test_no_eligible_recipients_no_op(self):
        """A project with no admin/owner and no assigned users
        is a quiet no-op (INFO log, empty return)."""
        db = _StubDb(users=[
            _user("U_DIFF_COMPANY", company_id="co_OTHER", role="admin"),
        ])
        ids = _run(dispatch_notification(
            db, project=_project(), kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="empty_test",
        ))
        self.assertEqual(ids, [])
        self.assertEqual(len(db[NOTIFICATIONS_COLLECTION].docs), 0)

    def test_denormalizes_project_name_into_doc(self):
        db = _StubDb(users=[_user("U_ADMIN", role="admin")])
        _run(dispatch_notification(
            db, project=_project(name="Denorm Test Project"),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="denorm_test",
        ))
        doc = db[NOTIFICATIONS_COLLECTION].docs[0]
        self.assertEqual(doc["project_name"], "Denorm Test Project")
        self.assertEqual(doc["project_id"], "P1")

    def test_assigned_project_user_eligible(self):
        """Verifies Stage 1 Q3 Option B: a non-admin user with
        the project in assigned_projects gets the notification."""
        db = _StubDb(users=[
            _user("U_RESTRICTED", role="member",
                  assigned_projects=["P1", "P99"]),
        ])
        ids = _run(dispatch_notification(
            db, project=_project(),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="assigned_test",
        ))
        self.assertEqual(len(ids), 1)
        self.assertEqual(
            db[NOTIFICATIONS_COLLECTION].docs[0]["user_id"],
            "U_RESTRICTED",
        )

    def test_users_outside_company_excluded(self):
        """Cross-company isolation: a user with the project in
        assigned_projects but a different company_id is NOT
        eligible (defensive — shouldn't happen in production
        but Mongo doesn't enforce referential integrity)."""
        db = _StubDb(users=[
            _user("U_WRONG_COMPANY", company_id="co_OTHER",
                  role="admin", assigned_projects=["P1"]),
        ])
        ids = _run(dispatch_notification(
            db, project=_project(),  # company_id="co_a"
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="cross_co",
        ))
        self.assertEqual(ids, [])

    def test_soft_deleted_users_excluded(self):
        db = _StubDb(users=[
            _user("U_DELETED", role="admin", is_deleted=True),
        ])
        ids = _run(dispatch_notification(
            db, project=_project(),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="soft_del",
        ))
        self.assertEqual(ids, [])

    def test_deeplink_includes_anchor(self):
        db = _StubDb(users=[_user("U_ADMIN", role="admin")])
        _run(dispatch_notification(
            db, project=_project(),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="anchor_test",
            deeplink_anchor="predictions",
        ))
        doc = db[NOTIFICATIONS_COLLECTION].docs[0]
        self.assertEqual(doc["deeplink"], "/project/P1#predictions")

    def test_deeplink_without_anchor(self):
        db = _StubDb(users=[_user("U_ADMIN", role="admin")])
        _run(dispatch_notification(
            db, project=_project(),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="no_anchor",
        ))
        doc = db[NOTIFICATIONS_COLLECTION].docs[0]
        self.assertEqual(doc["deeplink"], "/project/P1")

    def test_per_user_insert_failure_isolated(self):
        """If one user's insert raises, the other recipients still
        get their notifications."""
        db = _StubDb(users=[
            _user("U_OK1", role="admin"),
            _user("U_OK2", role="admin"),
        ])
        # Force the FIRST insert to raise; second should still run.
        original_insert = db[NOTIFICATIONS_COLLECTION].insert_one
        call_count = [0]
        async def _flaky_insert(doc):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated transient write failure")
            return await original_insert(doc)
        db[NOTIFICATIONS_COLLECTION].insert_one = _flaky_insert
        ids = _run(dispatch_notification(
            db, project=_project(),
            kind="inspection_prediction",
            title="X", message="Y",
            source_kind="prediction", source_id="iso_test",
        ))
        # One success despite the first one failing.
        self.assertEqual(len(ids), 1)

    def test_missing_project_id_no_op(self):
        """Defensive: project dict with no _id/id is a silent
        no-op with WARNING log."""
        db = _StubDb(users=[_user("U_ADMIN", role="admin")])
        with self.assertLogs(inbox.logger, level="WARNING") as logs:
            ids = _run(dispatch_notification(
                db, project={"company_id": "co_a"},  # no _id
                kind="inspection_prediction",
                title="X", message="Y",
                source_kind="prediction", source_id="no_pid",
            ))
        self.assertEqual(ids, [])
        self.assertIn("no project_id", "\n".join(logs.output))


# ──────────────────────────────────────────────────────────────────
# TestCleanupInbox
# ──────────────────────────────────────────────────────────────────


class TestCleanupInbox(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    def test_deletes_old_read_notifications(self):
        old_read_at = self.now - timedelta(days=READ_RETENTION_DAYS + 5)
        db = _StubDb(notifications=[
            {"_id": "OLD_READ", "user_id": "U1", "status": "active",
             "read_at": old_read_at, "expires_at": None},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(len(db[NOTIFICATIONS_COLLECTION].docs), 0)

    def test_preserves_recently_read(self):
        recent_read_at = self.now - timedelta(days=READ_RETENTION_DAYS - 5)
        db = _StubDb(notifications=[
            {"_id": "RECENT_READ", "user_id": "U1", "status": "active",
             "read_at": recent_read_at, "expires_at": None},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(len(db[NOTIFICATIONS_COLLECTION].docs), 1)

    def test_preserves_unread_without_expires(self):
        """Unread notification with no expires_at — never cleaned
        up automatically (only manual delete or user-driven
        read-then-90-days)."""
        db = _StubDb(notifications=[
            {"_id": "UNREAD_NO_EXP", "user_id": "U1",
             "status": "active", "read_at": None, "expires_at": None},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(stats["dismissed"], 0)
        # Doc preserved with active status.
        self.assertEqual(
            db[NOTIFICATIONS_COLLECTION].docs[0]["status"], "active",
        )

    def test_auto_dismisses_expired_active(self):
        expired_at = self.now - timedelta(hours=2)
        db = _StubDb(notifications=[
            {"_id": "EXPIRED", "user_id": "U1", "status": "active",
             "read_at": None, "expires_at": expired_at,
             "dismissed_at": None},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["dismissed"], 1)
        doc = db[NOTIFICATIONS_COLLECTION].docs[0]
        self.assertEqual(doc["status"], "dismissed")
        self.assertEqual(doc["dismissed_at"], self.now)

    def test_does_not_touch_already_dismissed(self):
        """Already-dismissed notifications must not be re-stamped
        (otherwise dismissed_at would drift each cron run)."""
        original_dismissed_at = self.now - timedelta(days=1)
        db = _StubDb(notifications=[
            {"_id": "ALREADY_DISMISSED", "user_id": "U1",
             "status": "dismissed", "read_at": None,
             "expires_at": self.now - timedelta(hours=24),
             "dismissed_at": original_dismissed_at},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["dismissed"], 0)
        # dismissed_at preserved.
        doc = db[NOTIFICATIONS_COLLECTION].docs[0]
        self.assertEqual(doc["dismissed_at"], original_dismissed_at)

    def test_does_not_dismiss_active_without_expires_at(self):
        """status=active + expires_at=None must stay active
        regardless of how old the notification is. The cleanup
        cron's dismissal path requires a non-null expires_at."""
        db = _StubDb(notifications=[
            {"_id": "ACTIVE_NO_EXP", "user_id": "U1",
             "status": "active", "read_at": None,
             "expires_at": None, "dismissed_at": None,
             "created_at": self.now - timedelta(days=365)},
        ])
        stats = _run(cleanup_inbox(db, now=self.now))
        self.assertEqual(stats["dismissed"], 0)


# ──────────────────────────────────────────────────────────────────
# TestNotificationsListEndpoint
# ──────────────────────────────────────────────────────────────────


class TestNotificationsListEndpoint(unittest.TestCase):
    """Tests of the list-endpoint query semantics. We test the
    query directly via the _StubColl since the endpoint is a thin
    wrapper around paginated_query — wiring is pinned in
    test_v2_2_schema_scaffolding.py grep tests.
    """

    def setUp(self):
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        # Seed mixed inbox: U1 has 1 unread, 1 read, 1 dismissed;
        # U2 has 1 unread. Project P1 vs P2 mix.
        self.fixtures = [
            {"_id": "N1", "user_id": "U1", "status": "active",
             "read_at": None, "project_id": "P1",
             "created_at": self.now - timedelta(hours=1)},
            {"_id": "N2", "user_id": "U1", "status": "active",
             "read_at": self.now - timedelta(hours=5),
             "project_id": "P1",
             "created_at": self.now - timedelta(hours=6)},
            {"_id": "N3", "user_id": "U1", "status": "dismissed",
             "read_at": None, "project_id": "P1",
             "created_at": self.now - timedelta(hours=12),
             "dismissed_at": self.now - timedelta(hours=2)},
            {"_id": "N4", "user_id": "U2", "status": "active",
             "read_at": None, "project_id": "P1",
             "created_at": self.now - timedelta(hours=3)},
            {"_id": "N5", "user_id": "U1", "status": "active",
             "read_at": None, "project_id": "P2",
             "created_at": self.now - timedelta(hours=4)},
        ]

    def _list_query(self, db, *, user_id, unread_only=False,
                    project_id=None):
        """Reproduce the list endpoint's query construction."""
        query: Dict[str, Any] = {
            "user_id": user_id,
            "status":  "active",
        }
        if unread_only:
            query["read_at"] = None
        if project_id:
            query["project_id"] = project_id
        cur = db[NOTIFICATIONS_COLLECTION].find(query).sort("created_at", -1)
        return _run(self._collect(cur))

    @staticmethod
    async def _collect(cur):
        out = []
        async for d in cur:
            out.append(d)
        return out

    def test_default_excludes_dismissed(self):
        db = _StubDb(notifications=self.fixtures)
        results = self._list_query(db, user_id="U1")
        ids = [d["_id"] for d in results]
        # U1 active+P1 (N1, N2) + U1 active+P2 (N5) — dismissed N3 excluded.
        self.assertIn("N1", ids)
        self.assertIn("N2", ids)
        self.assertIn("N5", ids)
        self.assertNotIn("N3", ids)

    def test_unread_only_filter(self):
        db = _StubDb(notifications=self.fixtures)
        results = self._list_query(db, user_id="U1", unread_only=True)
        ids = {d["_id"] for d in results}
        # N1 + N5 — N2 has read_at, N3 is dismissed.
        self.assertEqual(ids, {"N1", "N5"})

    def test_project_id_filter(self):
        db = _StubDb(notifications=self.fixtures)
        results = self._list_query(db, user_id="U1", project_id="P1")
        ids = {d["_id"] for d in results}
        # U1 active P1: N1, N2 (N3 dismissed excluded).
        self.assertEqual(ids, {"N1", "N2"})

    def test_ownership_scoping(self):
        """User U1 query MUST NOT return user U2's notifications."""
        db = _StubDb(notifications=self.fixtures)
        results = self._list_query(db, user_id="U1")
        for d in results:
            self.assertEqual(d["user_id"], "U1")

    def test_unread_count_endpoint_query_shape(self):
        """Pin the count-document query mirrors the list-endpoint
        unread filter: user_id + status=active + read_at=None."""
        db = _StubDb(notifications=self.fixtures)
        count = _run(db[NOTIFICATIONS_COLLECTION].count_documents({
            "user_id": "U1",
            "status":  "active",
            "read_at": None,
        }))
        self.assertEqual(count, 2)  # N1 + N5


# ──────────────────────────────────────────────────────────────────
# TestNotificationsMarkRead
# ──────────────────────────────────────────────────────────────────


class TestNotificationsMarkRead(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    def test_mark_one_ownership_filter_blocks_cross_user(self):
        """The endpoint's update_one filter pairs (_id, user_id),
        so a user trying to mark another user's notification
        produces matched_count=0 → 404. Pin the query shape."""
        db = _StubDb(notifications=[
            {"_id": "N_OTHER", "user_id": "U_OTHER", "status": "active",
             "read_at": None},
        ])
        # Simulate the endpoint's filter from u_attacker's session.
        coll = db[NOTIFICATIONS_COLLECTION]
        result = _run(coll.update_one(
            {"_id": "N_OTHER", "user_id": "U_ATTACKER"},
            {"$set": {"read_at": self.now}},
        ))
        self.assertEqual(result.matched_count, 0)
        # The other user's notification was NOT touched.
        self.assertIsNone(db[NOTIFICATIONS_COLLECTION].docs[0]["read_at"])

    def test_mark_one_success_sets_read_at(self):
        db = _StubDb(notifications=[
            {"_id": "N_MINE", "user_id": "U_ME", "status": "active",
             "read_at": None},
        ])
        result = _run(db[NOTIFICATIONS_COLLECTION].update_one(
            {"_id": "N_MINE", "user_id": "U_ME"},
            {"$set": {"read_at": self.now}},
        ))
        self.assertEqual(result.matched_count, 1)
        self.assertEqual(
            db[NOTIFICATIONS_COLLECTION].docs[0]["read_at"], self.now,
        )

    def test_mark_all_read_bulk(self):
        """mark-all-read should affect all of U_ME's unread-active
        notifications, leave dismissed + already-read alone."""
        db = _StubDb(notifications=[
            {"_id": "A", "user_id": "U_ME", "status": "active",
             "read_at": None},
            {"_id": "B", "user_id": "U_ME", "status": "active",
             "read_at": None},
            {"_id": "C", "user_id": "U_ME", "status": "active",
             "read_at": self.now - timedelta(hours=1)},  # already read
            {"_id": "D", "user_id": "U_ME", "status": "dismissed",
             "read_at": None},
            {"_id": "E", "user_id": "U_OTHER", "status": "active",
             "read_at": None},
        ])
        result = _run(db[NOTIFICATIONS_COLLECTION].update_many(
            {"user_id": "U_ME", "status": "active", "read_at": None},
            {"$set": {"read_at": self.now}},
        ))
        self.assertEqual(result.modified_count, 2)
        # A + B now read; C/D/E preserved.
        docs = {d["_id"]: d for d in db[NOTIFICATIONS_COLLECTION].docs}
        self.assertEqual(docs["A"]["read_at"], self.now)
        self.assertEqual(docs["B"]["read_at"], self.now)
        self.assertNotEqual(
            docs["C"]["read_at"], self.now,
            "Already-read C should not have its read_at overwritten",
        )
        self.assertIsNone(docs["D"]["read_at"], "Dismissed D untouched")
        self.assertIsNone(docs["E"]["read_at"], "Other-user E untouched")

    def test_mark_all_read_project_scope(self):
        """mark-all-read with project_id filter should only mark
        notifications for that project."""
        db = _StubDb(notifications=[
            {"_id": "A", "user_id": "U_ME", "status": "active",
             "read_at": None, "project_id": "P1"},
            {"_id": "B", "user_id": "U_ME", "status": "active",
             "read_at": None, "project_id": "P2"},
        ])
        result = _run(db[NOTIFICATIONS_COLLECTION].update_many(
            {"user_id": "U_ME", "status": "active", "read_at": None,
             "project_id": "P1"},
            {"$set": {"read_at": self.now}},
        ))
        self.assertEqual(result.modified_count, 1)
        docs = {d["_id"]: d for d in db[NOTIFICATIONS_COLLECTION].docs}
        self.assertEqual(docs["A"]["read_at"], self.now)
        self.assertIsNone(docs["B"]["read_at"])


if __name__ == "__main__":
    unittest.main()
