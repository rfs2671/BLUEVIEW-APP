"""Phase C3 — Atlas backup freshness verification script.

Pin every contract `verify_backup_freshness.py` promises:

  • Pure freshness logic — fresh / stale / no-snapshots.
  • Stub HTTP client wired through (so tests don't hit Atlas).
  • Sentry capture on stale + on API failure (NOT on missing-env;
    that's operator config error).
  • Exit codes: 0 fresh, 1 stale-or-API-failure, 2 missing-env.
  • Atlas snapshot doc parsing (createdAt with 'Z' suffix).
  • Most-recent snapshot wins when multiple are returned.
  • Completed snapshots preferred over incomplete ones.

Tests don't need network or a real Atlas project. The script's
public functions (`fetch_latest_snapshot`, `evaluate_freshness`,
`main`) all accept dependency-injected stubs.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from scripts import verify_backup_freshness as vbf  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# Stub helpers
# ──────────────────────────────────────────────────────────────────


class _StubResponse:
    """Mimics enough of httpx.Response for the script's call site."""

    def __init__(self, *, status_code=200, payload=None, raise_exc=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


class _StubClient:
    """Mimics enough of httpx.Client for a single .get(...) call."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, auth=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "auth": auth})
        return self.response


def _make_atlas_payload(snapshots):
    """Atlas's snapshots list endpoint returns
    {"results": [...], "totalCount": N}. Mirror that shape."""
    return {"results": list(snapshots), "totalCount": len(snapshots)}


def _snap(*, id_="s_1", created_at="2026-05-05T12:00:00Z",
          status="completed", type_="onDemand"):
    return {
        "id": id_,
        "createdAt": created_at,
        "status": status,
        "type": type_,
    }


# ──────────────────────────────────────────────────────────────────
# fetch_latest_snapshot
# ──────────────────────────────────────────────────────────────────


class TestFetchLatestSnapshot(unittest.TestCase):

    def test_returns_most_recent_snapshot(self):
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="old", created_at="2026-04-01T00:00:00Z"),
            _snap(id_="new", created_at="2026-05-05T11:00:00Z"),
            _snap(id_="middle", created_at="2026-04-15T00:00:00Z"),
        ])))
        snap = vbf.fetch_latest_snapshot(
            public_key="pk", private_key="sk",
            group_id="g", cluster="c",
            http_client=client,
        )
        self.assertIsNotNone(snap)
        self.assertEqual(snap.id, "new")

    def test_prefers_completed_over_incomplete(self):
        """When the list contains both completed and in-progress
        snapshots, the freshness check should pick the most recent
        COMPLETED one — an in-progress snapshot isn't a usable
        restore point yet."""
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="completed-old", created_at="2026-04-01T00:00:00Z",
                  status="completed"),
            _snap(id_="in-progress",   created_at="2026-05-05T12:00:00Z",
                  status="inProgress"),
        ])))
        snap = vbf.fetch_latest_snapshot(
            public_key="pk", private_key="sk",
            group_id="g", cluster="c",
            http_client=client,
        )
        self.assertEqual(snap.id, "completed-old")

    def test_falls_back_to_any_when_no_completed(self):
        """If Atlas returns ONLY in-progress snapshots, pick the
        most recent one anyway — better than reporting "no
        snapshots" (which would imply the cluster has never been
        backed up)."""
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="ip-1", created_at="2026-05-05T11:00:00Z",
                  status="inProgress"),
            _snap(id_="ip-2", created_at="2026-05-05T12:00:00Z",
                  status="inProgress"),
        ])))
        snap = vbf.fetch_latest_snapshot(
            public_key="pk", private_key="sk",
            group_id="g", cluster="c",
            http_client=client,
        )
        self.assertEqual(snap.id, "ip-2")

    def test_returns_none_when_no_snapshots(self):
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([])))
        snap = vbf.fetch_latest_snapshot(
            public_key="pk", private_key="sk",
            group_id="g", cluster="c",
            http_client=client,
        )
        self.assertIsNone(snap)

    def test_raises_on_http_error(self):
        client = _StubClient(_StubResponse(
            raise_exc=RuntimeError("Atlas API 500"),
        ))
        with self.assertRaises(RuntimeError):
            vbf.fetch_latest_snapshot(
                public_key="pk", private_key="sk",
                group_id="g", cluster="c",
                http_client=client,
            )

    def test_passes_correct_url_and_headers(self):
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([])))
        vbf.fetch_latest_snapshot(
            public_key="pk", private_key="sk",
            group_id="abc123def456",
            cluster="prod-cluster",
            http_client=client,
        )
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertIn("/groups/abc123def456/clusters/prod-cluster/backup/snapshots",
                      call["url"])
        # Pinned API version — see _ATLAS_ACCEPT comment in the
        # script. A future change to this string MUST come with an
        # explicit re-read of the Atlas changelog.
        self.assertEqual(
            call["headers"]["Accept"],
            "application/vnd.atlas.2024-08-05+json",
        )
        self.assertEqual(call["auth"], ("pk", "sk"))


# ──────────────────────────────────────────────────────────────────
# evaluate_freshness — pure logic
# ──────────────────────────────────────────────────────────────────


class TestEvaluateFreshness(unittest.TestCase):

    def _snap_at(self, ts):
        return vbf._Snapshot(
            id="s_1", created_at=ts, status="completed", type="onDemand",
        )

    def test_fresh_when_within_threshold(self):
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        snap = self._snap_at(now - timedelta(hours=2))
        is_fresh, age, msg = vbf.evaluate_freshness(snap, 24, now=now)
        self.assertTrue(is_fresh)
        self.assertAlmostEqual(age, 2.0, places=1)
        self.assertIn("within", msg)

    def test_stale_when_past_threshold(self):
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        snap = self._snap_at(now - timedelta(hours=48))
        is_fresh, age, msg = vbf.evaluate_freshness(snap, 24, now=now)
        self.assertFalse(is_fresh)
        self.assertAlmostEqual(age, 48.0, places=1)
        self.assertIn("threshold", msg)

    def test_no_snapshot_is_stale(self):
        is_fresh, age, msg = vbf.evaluate_freshness(None, 24)
        self.assertFalse(is_fresh)
        self.assertIsNone(age)
        self.assertIn("no snapshots", msg)

    def test_naive_datetime_assumed_utc(self):
        """If a snapshot's createdAt parsed as naive (defensive
        edge case), the comparison should still work — we coerce
        to UTC inside evaluate_freshness."""
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        naive_ts = datetime(2026, 5, 5, 6, 0, 0)  # no tzinfo
        snap = vbf._Snapshot(
            id="s", created_at=naive_ts,
            status="completed", type="onDemand",
        )
        is_fresh, age, _msg = vbf.evaluate_freshness(snap, 24, now=now)
        self.assertTrue(is_fresh)
        self.assertAlmostEqual(age, 6.0, places=1)


# ──────────────────────────────────────────────────────────────────
# Snapshot.from_atlas — Z-suffix parsing
# ──────────────────────────────────────────────────────────────────


class TestSnapshotParsing(unittest.TestCase):

    def test_z_suffix_parsed_as_utc(self):
        snap = vbf._Snapshot.from_atlas({
            "id": "s_1",
            "createdAt": "2026-05-05T12:00:00Z",
            "status": "completed",
            "type": "onDemand",
        })
        self.assertEqual(snap.created_at.tzinfo, timezone.utc)
        self.assertEqual(snap.created_at.year, 2026)
        self.assertEqual(snap.created_at.hour, 12)

    def test_offset_format_parsed(self):
        snap = vbf._Snapshot.from_atlas({
            "id": "s_2",
            "createdAt": "2026-05-05T08:00:00+04:00",
            "status": "completed",
            "type": "onDemand",
        })
        self.assertIsNotNone(snap.created_at.tzinfo)
        # 08:00 +04:00 = 04:00 UTC.
        self.assertEqual(
            snap.created_at.astimezone(timezone.utc).hour, 4,
        )


# ──────────────────────────────────────────────────────────────────
# main() — integration of env reads, I/O, decision, side effects
# ──────────────────────────────────────────────────────────────────


class TestMain(unittest.TestCase):

    def setUp(self):
        self.full_env = {
            "ATLAS_PUBLIC_KEY": "pk",
            "ATLAS_PRIVATE_KEY": "sk",
            "ATLAS_GROUP_ID": "g123",
            "ATLAS_CLUSTER_NAME": "prod",
            "ATLAS_BACKUP_MAX_AGE_HOURS": "24",
        }
        self.sentry_calls = []
        self.exit_code = None

    def _capture_sentry(self, *args, **kwargs):
        self.sentry_calls.append({"args": args, "kwargs": kwargs})

    def _capture_exit(self, code):
        self.exit_code = code

    def test_fresh_backup_exits_zero_no_sentry(self):
        """Happy path: snapshot under threshold → exit 0, no
        Sentry event."""
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="ok", created_at=recent),
        ])))
        rc = vbf.main(
            http_client=client,
            sentry_capture=self._capture_sentry,
            env=self.full_env,
            exit_fn=self._capture_exit,
            now=now,
            stdout=open(os.devnull, "w"),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.exit_code, 0)
        self.assertEqual(self.sentry_calls, [])

    def test_stale_backup_exits_one_with_sentry_warning(self):
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        old = (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="too-old", created_at=old),
        ])))
        rc = vbf.main(
            http_client=client,
            sentry_capture=self._capture_sentry,
            env=self.full_env,
            exit_fn=self._capture_exit,
            now=now,
            stdout=open(os.devnull, "w"),
        )
        self.assertEqual(rc, 1)
        self.assertEqual(self.exit_code, 1)
        self.assertEqual(len(self.sentry_calls), 1)
        msg = self.sentry_calls[0]["args"][0]
        self.assertIn("backup_stale", msg)
        self.assertEqual(self.sentry_calls[0]["kwargs"]["level"], "warning")

    def test_no_snapshots_exits_one_with_sentry(self):
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([])))
        rc = vbf.main(
            http_client=client,
            sentry_capture=self._capture_sentry,
            env=self.full_env,
            exit_fn=self._capture_exit,
            stdout=open(os.devnull, "w"),
        )
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.sentry_calls), 1)
        self.assertIn("no snapshots", self.sentry_calls[0]["args"][0])

    def test_api_failure_exits_one_with_sentry_warning(self):
        """A transient Atlas API failure should warn (not error)
        and exit 1. Persistent failures dedup in Sentry into a
        single grouped issue."""
        client = _StubClient(_StubResponse(
            raise_exc=RuntimeError("Atlas API 500: read timeout"),
        ))
        rc = vbf.main(
            http_client=client,
            sentry_capture=self._capture_sentry,
            env=self.full_env,
            exit_fn=self._capture_exit,
            stdout=open(os.devnull, "w"),
        )
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.sentry_calls), 1)
        msg = self.sentry_calls[0]["args"][0]
        self.assertIn("Atlas API call failed", msg)
        self.assertEqual(self.sentry_calls[0]["kwargs"]["level"], "warning")

    def test_missing_required_env_exits_two_no_sentry(self):
        """Missing config = operator error, NOT a backup problem.
        Don't fire Sentry — that would be noise.

        Verifies each required env var triggers the missing-config
        path independently."""
        for missing_key in ("ATLAS_PUBLIC_KEY", "ATLAS_PRIVATE_KEY",
                            "ATLAS_GROUP_ID", "ATLAS_CLUSTER_NAME"):
            with self.subTest(missing=missing_key):
                env = dict(self.full_env)
                env.pop(missing_key)
                self.sentry_calls = []
                self.exit_code = None
                rc = vbf.main(
                    sentry_capture=self._capture_sentry,
                    env=env,
                    exit_fn=self._capture_exit,
                    stdout=open(os.devnull, "w"),
                )
                self.assertEqual(rc, 2, f"missing {missing_key}")
                self.assertEqual(self.exit_code, 2)
                self.assertEqual(self.sentry_calls, [])

    def test_blank_env_var_treated_as_missing(self):
        """Atlas keys are sensitive — an accidentally-empty value
        in Railway should NOT be treated as 'present' (which would
        make the next call fail with a confusing 401)."""
        env = dict(self.full_env)
        env["ATLAS_PUBLIC_KEY"] = "   "  # whitespace only
        rc = vbf.main(
            sentry_capture=self._capture_sentry,
            env=env,
            exit_fn=self._capture_exit,
            stdout=open(os.devnull, "w"),
        )
        self.assertEqual(rc, 2)

    def test_invalid_max_age_falls_back_to_default(self):
        """Garbage in ATLAS_BACKUP_MAX_AGE_HOURS shouldn't crash —
        fall back to 24h default. A typo'd value is operator
        error but not page-the-on-call worthy."""
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client = _StubClient(_StubResponse(payload=_make_atlas_payload([
            _snap(id_="ok", created_at=recent),
        ])))
        env = dict(self.full_env)
        env["ATLAS_BACKUP_MAX_AGE_HOURS"] = "not-a-number"
        rc = vbf.main(
            http_client=client,
            sentry_capture=self._capture_sentry,
            env=env,
            exit_fn=self._capture_exit,
            now=now,
            stdout=open(os.devnull, "w"),
        )
        # 10h old, default 24h threshold → fresh.
        self.assertEqual(rc, 0)


# ──────────────────────────────────────────────────────────────────
# Backup-restore documentation pins
# ──────────────────────────────────────────────────────────────────


class TestBackupRestoreDocumentation(unittest.TestCase):
    """Static-source pins on docs/operations/backup-restore.md.
    The doc is the operator-facing artifact for C3; a future
    'cleanup' edit can't silently drop the load-bearing
    sections (restore drill, DR procedure, migration safety)."""

    @classmethod
    def setUpClass(cls):
        repo = _BACKEND.parent
        cls.path = repo / "docs" / "operations" / "backup-restore.md"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_covers_required_sections(self):
        for section in (
            "## 1. Backup state",
            "## 2. What's protected",
            "## 3. Restore drill",
            "## 4. Disaster recovery",
            "## 5. Migration safety pattern",
            "## 6. Backup freshness verification",
        ):
            self.assertIn(section, self.text, f"missing: {section}")

    def test_dr_procedure_uses_kill_switch(self):
        # The DR runbook must pause notifications during restore;
        # a flood of "your status changed" emails based on backed-
        # up data would be a second incident on top of the first.
        self.assertIn("NOTIFICATIONS_KILL_SWITCH=true", self.text)

    def test_restore_drill_warns_against_in_place(self):
        # Hard rule: drill MUST use "restore to a new cluster",
        # never in-place. Pin via the operator-facing warning.
        self.assertIn("restore to a new cluster", self.text.lower())
        self.assertIn("never", self.text.lower())

    def test_migration_safety_documents_dry_run_first(self):
        self.assertIn("--dry-run", self.text)
        self.assertIn("--execute", self.text)

    def test_freshness_script_documented(self):
        self.assertIn("verify_backup_freshness", self.text)
        self.assertIn("ATLAS_PUBLIC_KEY", self.text)
        self.assertIn("ATLAS_PRIVATE_KEY", self.text)
        self.assertIn("ATLAS_GROUP_ID", self.text)


if __name__ == "__main__":
    unittest.main()
