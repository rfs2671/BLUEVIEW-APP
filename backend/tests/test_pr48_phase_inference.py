"""PR #48 — weekly Gemini phase inference tests.

Strategy: the google-genai SDK is mocked at module level
(lib.ai.phase_inference.genai) so no real API calls fire. The
GEMINI_API_KEY module constant is patched per-test to exercise both
the "configured" and "unconfigured" paths.

14 tests covering:

  infer_phase_for_project:
    - None when no API key
    - None when no logs in window
    - None when Gemini raises
    - None on invalid enum response
    - prompt built from log content
    - date window filter applied

  run_weekly_phase_inference:
    - processes all active projects
    - continues on per-project failure
    - returns summary dict

  _resolve_schedule_position priority chain (live_mutation):
    - ai_inferred_phase wins (tier 1)
    - daily_log.phase fallback (tier 2)
    - live inferred fallback (tier 3)

  _format_logs_for_prompt:
    - truncates long text
    - handles empty subcontractor list
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


try:
    from lib.ai import phase_inference as PI
    HAS_PI = True
except ImportError:
    PI = None  # type: ignore
    HAS_PI = False


# ─── In-memory stubs ───────────────────────────────────────────────


class _AsyncCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self._items)
        return list(self._items[:length])


class _StubCollection:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.last_find_filter: Optional[Dict[str, Any]] = None
        self.update_calls: List[Dict[str, Any]] = []

    def find(self, filter_=None, projection=None):
        self.last_find_filter = filter_ or {}
        matched = [d for d in (self.docs) if _match(d, filter_ or {})]
        return _AsyncCursor(matched)

    async def find_one(self, filter_=None, sort=None, projection=None):
        matched = [d for d in self.docs if _match(d, filter_ or {})]
        if sort:
            for field, direction in reversed(sort):
                matched.sort(
                    key=lambda d, f=field: d.get(f) or "",
                    reverse=(direction == -1),
                )
        return matched[0] if matched else None

    async def update_one(self, filter_, update):
        self.update_calls.append({"filter": filter_, "update": update})
        for d in self.docs:
            if _match(d, filter_):
                d.update(update.get("$set", {}))
        return None


def _match(doc, filter_):
    for k, expected in filter_.items():
        actual = doc.get(k)
        if isinstance(expected, dict):
            for op, v in expected.items():
                if op == "$gte" and not (actual is not None and actual >= v):
                    return False
                if op == "$lt" and not (actual is not None and actual < v):
                    return False
                if op == "$ne" and actual == v:
                    return False
                if op == "$nin" and actual in v:
                    return False
        else:
            if actual != expected:
                return False
    return True


class _StubDb:
    def __init__(self):
        self.daily_logs = _StubCollection()
        self.projects = _StubCollection()


def _seed_log(date_str, *, work=None, notes=None, subs=None, workers=None):
    return {
        "project_id": "P1",
        "is_deleted": False,
        "date": date_str,
        "work_performed": work,
        "notes": notes,
        "subcontractor_cards": subs or [],
        "worker_count": workers,
    }


def _fake_gemini_response(json_text):
    """Build a stand-in for the genai response object (only .text used)."""
    r = mock.MagicMock()
    r.text = json_text
    return r


def _patch_gemini(json_text=None, raise_exc=None):
    """Return a mock genai module whose Client().models.generate_content
    returns a fake response (or raises)."""
    fake_client = mock.MagicMock()
    if raise_exc is not None:
        fake_client.models.generate_content.side_effect = raise_exc
    else:
        fake_client.models.generate_content.return_value = (
            _fake_gemini_response(json_text)
        )
    fake_genai = mock.MagicMock()
    fake_genai.Client.return_value = fake_client
    return fake_genai, fake_client


# ═══════════════════════════════════════════════════════════════════
# infer_phase_for_project
# ═══════════════════════════════════════════════════════════════════


class TestInferPhase(unittest.IsolatedAsyncioTestCase):

    def _require(self):
        if not HAS_PI:
            self.fail(
                "lib.ai.phase_inference not implemented. PR #48 Stage 2.A."
            )

    async def test_infer_phase_returns_none_when_no_api_key(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [_seed_log("2026-05-19", work="framing")]
        project = {"_id": "P1"}
        with mock.patch.object(PI, "GEMINI_API_KEY", ""):
            out = await PI.infer_phase_for_project(
                db, project, now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        self.assertIsNone(out)

    async def test_infer_phase_returns_none_when_no_logs_in_window(self):
        self._require()
        db = _StubDb()
        # Only a stale log, 30 days back — outside the 7-day window.
        db.daily_logs.docs = [_seed_log("2026-04-15", work="framing")]
        project = {"_id": "P1"}
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"):
            out = await PI.infer_phase_for_project(
                db, project, now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        self.assertIsNone(out)

    async def test_infer_phase_returns_none_when_gemini_fails(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [_seed_log("2026-05-19", work="MEP rough-in")]
        project = {"_id": "P1"}
        fake_genai, _ = _patch_gemini(raise_exc=RuntimeError("boom"))
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"), \
             mock.patch.object(PI, "genai", fake_genai):
            out = await PI.infer_phase_for_project(
                db, project, now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        self.assertIsNone(out)

    async def test_infer_phase_returns_none_on_invalid_enum_response(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [_seed_log("2026-05-19", work="painting")]
        project = {"_id": "P1"}
        fake_genai, _ = _patch_gemini(json_text='{"phase": "not_a_phase"}')
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"), \
             mock.patch.object(PI, "genai", fake_genai):
            out = await PI.infer_phase_for_project(
                db, project, now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        self.assertIsNone(out)

    async def test_infer_phase_returns_dict_on_valid_response(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [
            _seed_log("2026-05-19", work="MEP rough-in", workers=12),
            _seed_log("2026-05-18", work="electrical conduit"),
        ]
        project = {"_id": "P1"}
        fake_genai, _ = _patch_gemini(
            json_text='{"phase": "mep", "reasoning": "rough-in"}',
        )
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"), \
             mock.patch.object(PI, "genai", fake_genai):
            out = await PI.infer_phase_for_project(db, project, now=now)
        self.assertIsNotNone(out)
        self.assertEqual(out["phase"], "mep")
        self.assertEqual(out["source_log_count"], 2)
        self.assertEqual(out["inferred_at"], now)
        self.assertEqual(out["source_log_window_end"], now)
        self.assertEqual(
            out["source_log_window_start"], now - timedelta(days=7),
        )

    async def test_infer_phase_builds_prompt_from_logs(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [
            _seed_log("2026-05-19", work="UNIQUEMARKER pouring footings"),
        ]
        project = {"_id": "P1"}
        fake_genai, fake_client = _patch_gemini(
            json_text='{"phase": "foundation"}',
        )
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"), \
             mock.patch.object(PI, "genai", fake_genai):
            await PI.infer_phase_for_project(
                db, project, now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        # Capture the contents kwarg passed to generate_content.
        _, kwargs = fake_client.models.generate_content.call_args
        contents = kwargs.get("contents", "")
        self.assertIn("UNIQUEMARKER", contents)

    async def test_infer_phase_filters_window_correctly(self):
        self._require()
        db = _StubDb()
        db.daily_logs.docs = [_seed_log("2026-05-19", work="framing")]
        project = {"_id": "P1"}
        fake_genai, _ = _patch_gemini(json_text='{"phase": "superstructure"}')
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        with mock.patch.object(PI, "GEMINI_API_KEY", "fake-key"), \
             mock.patch.object(PI, "genai", fake_genai):
            await PI.infer_phase_for_project(db, project, now=now)
        flt = db.daily_logs.last_find_filter
        self.assertIn("date", flt)
        self.assertIn("$gte", flt["date"])
        self.assertEqual(
            flt["date"]["$gte"],
            (now - timedelta(days=7)).strftime("%Y-%m-%d"),
        )


# ═══════════════════════════════════════════════════════════════════
# run_weekly_phase_inference
# ═══════════════════════════════════════════════════════════════════


class TestWeeklyCron(unittest.IsolatedAsyncioTestCase):

    def _require(self):
        if not HAS_PI:
            self.fail("lib.ai.phase_inference not implemented. PR #48.")

    async def test_weekly_cron_processes_all_active_projects(self):
        self._require()
        db = _StubDb()
        db.projects.docs = [
            {"_id": "P1", "name": "A", "is_deleted": False},
            {"_id": "P2", "name": "B", "is_deleted": False},
            {"_id": "P3", "name": "C", "is_deleted": True},  # excluded
        ]

        async def _fake_infer(db_, project, now=None):
            return {
                "phase": "mep", "inferred_at": now,
                "source_log_count": 1,
                "source_log_window_start": now,
                "source_log_window_end": now,
            }

        with mock.patch.object(PI, "infer_phase_for_project", _fake_infer):
            result = await PI.run_weekly_phase_inference(
                db, now=datetime(2026, 5, 17, tzinfo=timezone.utc),
            )
        # 2 active projects processed + updated.
        self.assertEqual(result["n_projects_processed"], 2)
        self.assertEqual(result["n_phase_updated"], 2)
        self.assertEqual(result["n_failed"], 0)
        # Both projects got ai_inferred_phase persisted.
        self.assertEqual(len(db.projects.update_calls), 2)

    async def test_weekly_cron_continues_on_per_project_failure(self):
        self._require()
        db = _StubDb()
        db.projects.docs = [
            {"_id": "P1", "name": "A", "is_deleted": False},
            {"_id": "P2", "name": "B", "is_deleted": False},
        ]

        async def _flaky_infer(db_, project, now=None):
            if project["_id"] == "P1":
                raise RuntimeError("gemini exploded")
            return {
                "phase": "interior", "inferred_at": now,
                "source_log_count": 1,
                "source_log_window_start": now,
                "source_log_window_end": now,
            }

        with mock.patch.object(PI, "infer_phase_for_project", _flaky_infer):
            result = await PI.run_weekly_phase_inference(
                db, now=datetime(2026, 5, 17, tzinfo=timezone.utc),
            )
        self.assertEqual(result["n_projects_processed"], 2)
        self.assertEqual(result["n_phase_updated"], 1)  # only P2
        self.assertEqual(result["n_failed"], 1)         # P1

    async def test_weekly_cron_returns_summary_dict(self):
        self._require()
        db = _StubDb()
        db.projects.docs = []

        async def _noop_infer(db_, project, now=None):
            return None

        with mock.patch.object(PI, "infer_phase_for_project", _noop_infer):
            result = await PI.run_weekly_phase_inference(db)
        for key in (
            "n_projects_processed", "n_phase_updated",
            "n_failed", "elapsed_seconds",
        ):
            self.assertIn(key, result)


# ═══════════════════════════════════════════════════════════════════
# _resolve_schedule_position priority chain (live_mutation)
# ═══════════════════════════════════════════════════════════════════


class TestResolverPriority(unittest.IsolatedAsyncioTestCase):

    async def test_resolver_priority_uses_ai_inferred_phase_first(self):
        from lib.statistical_engine import live_mutation as LM
        db = _StubDb()
        # daily_log says foundation (0.10), but AI says mep (0.70).
        db.daily_logs.docs = [
            {"project_id": "P1", "phase": "foundation", "is_deleted": False,
             "date": "2026-05-19"},
        ]
        project = {
            "_id": "P1",
            "ai_inferred_phase": {"phase": "mep"},
        }
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        out = await LM._resolve_schedule_position(db, project, now)
        self.assertAlmostEqual(out, LM.PHASE_TO_RATIO["mep"], places=6)

    async def test_resolver_falls_back_to_daily_log_phase_when_no_ai(self):
        from lib.statistical_engine import live_mutation as LM
        db = _StubDb()
        db.daily_logs.docs = [
            {"project_id": "P1", "phase": "foundation", "is_deleted": False,
             "date": "2026-05-19"},
        ]
        project = {"_id": "P1"}  # no ai_inferred_phase
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        out = await LM._resolve_schedule_position(db, project, now)
        self.assertAlmostEqual(
            out, LM.PHASE_TO_RATIO["foundation"], places=6,
        )

    async def test_resolver_falls_back_to_live_inferred_when_no_phase_signals(self):
        from lib.statistical_engine import live_mutation as LM
        db = _StubDb()
        # No daily_logs, no ai_inferred_phase → live inferred path.
        project = {"_id": "P1"}
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        async def _fake_live(db_, proj, cur_now):
            return 0.42

        with mock.patch.object(
            LM, "_compute_schedule_position_live", _fake_live,
        ):
            out = await LM._resolve_schedule_position(db, project, now)
        self.assertAlmostEqual(out, 0.42, places=6)

    async def test_resolver_ai_invalid_phase_falls_through(self):
        """AI phase not in PHASE_TO_RATIO → fall through to daily_log."""
        from lib.statistical_engine import live_mutation as LM
        db = _StubDb()
        db.daily_logs.docs = [
            {"project_id": "P1", "phase": "interior", "is_deleted": False,
             "date": "2026-05-19"},
        ]
        project = {"_id": "P1", "ai_inferred_phase": {"phase": "garbage"}}
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        out = await LM._resolve_schedule_position(db, project, now)
        self.assertAlmostEqual(
            out, LM.PHASE_TO_RATIO["interior"], places=6,
        )


# ═══════════════════════════════════════════════════════════════════
# _format_logs_for_prompt
# ═══════════════════════════════════════════════════════════════════


class TestFormatLogs(unittest.TestCase):

    def _require(self):
        if not HAS_PI:
            self.fail("lib.ai.phase_inference not implemented. PR #48.")

    def test_format_logs_truncates_long_text(self):
        self._require()
        long_work = "X" * 1000
        out = PI._format_logs_for_prompt([
            _seed_log("2026-05-19", work=long_work),
        ])
        # work_performed truncated to 300 chars per spec.
        self.assertNotIn("X" * 400, out)
        self.assertIn("X" * 300, out)

    def test_format_logs_handles_empty_subcontractor_list(self):
        self._require()
        out = PI._format_logs_for_prompt([
            _seed_log("2026-05-19", work="framing", subs=[]),
        ])
        # No crash, no "Trades:" line when subs empty.
        self.assertIn("framing", out)
        self.assertNotIn("Trades:", out)

    def test_format_logs_empty_returns_placeholder(self):
        self._require()
        out = PI._format_logs_for_prompt([])
        self.assertIn("no logs", out.lower())


if __name__ == "__main__":
    unittest.main()
