"""Phase V2.0 — compliance logbook tests.

Pin every contract the v2 logbook system promises:

  • Schema: categories / statuses / sources match the canonical
    constants; iter_expected_dates honors weekday rules and the
    weekend_work toggle.
  • Missing detector: weekday gap detection, weekend skip,
    idempotency on re-run, multi-project isolation, project
    creation date floor.
  • Deficiency rules: each rule's positive + negative case
    independently verified.
  • LL196: SST status classification, attestation_data shape,
    PDF render contains the right strings, R2 key is
    deterministic, end-to-end orchestrator with stub I/O.
  • Endpoints: flag DISABLED → 404 on every endpoint;
    flag ENABLED → returns the expected shape.
  • Frontend audit screen: feature flag check is the FIRST hook
    (rules-of-hooks); flag-off returns null before fetching.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from lib import logbook  # noqa: E402
from lib.logbook import schema as logbook_schema  # noqa: E402
from lib.logbook import missing_detector, deficiency, ll196  # noqa: E402
from lib import feature_flags  # noqa: E402


def _run(coro):
    """Fresh event loop per async test — same pattern as B3/F1/E1."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _AsyncCursor:
    """Async iterator over a fixed list — mocks motor.find().
    Supports the chain `.find(...).sort(...).limit(...).to_list(...)`
    that the logbook endpoints use; each chained method returns
    self so callers can chain freely."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        # Honor the limit so tests that assert N entries with a
        # cap behave like Mongo would.
        if n is not None and n >= 0:
            self._items = self._items[:n]
        return self

    def to_list(self, _n=None):
        async def _coro():
            if _n is not None and _n >= 0:
                return self._items[:_n]
            return self._items
        return _coro()


# ──────────────────────────────────────────────────────────────────
# Schema invariants
# ──────────────────────────────────────────────────────────────────


class TestSchemaConstants(unittest.TestCase):

    def test_categories_pinned(self):
        # The spec lists the six category values verbatim.
        self.assertEqual(logbook.CATEGORY_DAILY_LOG, "daily_log")
        self.assertEqual(logbook.CATEGORY_LL196, "ll196_attestation")
        self.assertEqual(logbook.CATEGORY_INSPECTION, "inspection")
        self.assertEqual(logbook.CATEGORY_DEFICIENCY, "deficiency")
        self.assertEqual(logbook.CATEGORY_MANPOWER, "manpower")
        self.assertEqual(logbook.CATEGORY_MATERIAL_DELIVERY, "material_delivery")
        self.assertEqual(len(logbook.VALID_CATEGORIES), 6)

    def test_statuses_pinned(self):
        self.assertEqual(logbook.STATUS_COMPLETE, "complete")
        self.assertEqual(logbook.STATUS_MISSING, "missing")
        self.assertEqual(logbook.STATUS_DEFICIENT, "deficient")
        self.assertEqual(len(logbook.VALID_STATUSES), 3)

    def test_sources_pinned(self):
        self.assertEqual(logbook.SOURCE_WHATSAPP, "whatsapp")
        self.assertEqual(logbook.SOURCE_MANUAL, "manual")
        self.assertEqual(logbook.SOURCE_AUTO_DETECTED, "auto_detected")

    def test_indexes_include_unique_dedupe_key(self):
        # The (project, date, category) unique index is what makes
        # the missing/deficiency upserts idempotent. Pin it
        # explicitly so a future cleanup can't drop it.
        names = {idx["name"] for idx in logbook.LOGBOOK_ENTRIES_INDEXES}
        self.assertIn("logbook_project_date_category_unique", names)
        unique_idx = next(
            i for i in logbook.LOGBOOK_ENTRIES_INDEXES
            if i["name"] == "logbook_project_date_category_unique"
        )
        self.assertTrue(unique_idx.get("unique"))


class TestExpectedDates(unittest.TestCase):

    def test_weekdays_only_by_default(self):
        # May 4 2026 is Mon; May 10 2026 is Sun. Five expected days.
        days = list(logbook.iter_expected_dates(
            date(2026, 5, 4), date(2026, 5, 10),
        ))
        self.assertEqual(len(days), 5)
        for d in days:
            self.assertLess(d.weekday(), 5)

    def test_weekend_work_includes_all_days(self):
        days = list(logbook.iter_expected_dates(
            date(2026, 5, 4), date(2026, 5, 10),
            weekend_work=True,
        ))
        self.assertEqual(len(days), 7)

    def test_inverted_range_yields_nothing(self):
        days = list(logbook.iter_expected_dates(
            date(2026, 5, 10), date(2026, 5, 4),
        ))
        self.assertEqual(days, [])


# ──────────────────────────────────────────────────────────────────
# Missing detector
# ──────────────────────────────────────────────────────────────────


def _build_db_with_logs(*, daily_log_dates, project_id, project_created=None):
    """Build a MagicMock db whose daily_logs.find() returns docs
    with the given dates and whose logbook_entries.update_one is
    AsyncMock-counted."""
    db = MagicMock()
    db.daily_logs = MagicMock()
    db.daily_logs.find = MagicMock(return_value=_AsyncCursor([
        {"date": d, "project_id": project_id} for d in daily_log_dates
    ]))
    db.logbook_entries = MagicMock()
    db.logbook_entries.update_one = AsyncMock(
        return_value=MagicMock(matched_count=0, upserted_id="x"),
    )
    db.projects = MagicMock()
    project_doc = {"_id": project_id, "company_id": "co_a", "status": "active"}
    if project_created:
        project_doc["created_at"] = project_created
    db.projects.find = MagicMock(return_value=_AsyncCursor([project_doc]))
    return db


class TestMissingDetector(unittest.TestCase):

    def test_weekday_gap_detected(self):
        # Mon-Fri week, only Mon + Wed have logs → 3 gaps (Tue,
        # Thu, Fri).
        db = _build_db_with_logs(
            daily_log_dates=["2026-05-04", "2026-05-06"],
            project_id="proj_a",
        )
        project = {
            "_id": "proj_a", "company_id": "co_a",
            "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
        now = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
        written = _run(missing_detector.detect_missing_for_project(
            db, project=project,
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 8),
            now=now,
        ))
        # Tue, Thu, Fri = 3 missing.
        self.assertEqual(len(written), 3)
        gap_dates = sorted(e["entry_date"] for e in written)
        self.assertEqual(gap_dates, ["2026-05-05", "2026-05-07", "2026-05-08"])

    def test_weekends_skipped_by_default(self):
        # Mon-Sun with no logs → only 5 missing (Sat + Sun skipped).
        db = _build_db_with_logs(
            daily_log_dates=[],
            project_id="proj_a",
        )
        project = {
            "_id": "proj_a", "company_id": "co_a",
            "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        written = _run(missing_detector.detect_missing_for_project(
            db, project=project,
            start_date=date(2026, 5, 4),  # Monday
            end_date=date(2026, 5, 10),    # Sunday
            now=now,
        ))
        self.assertEqual(len(written), 5)

    def test_weekend_work_flag_includes_weekends(self):
        db = _build_db_with_logs(
            daily_log_dates=[],
            project_id="proj_b",
        )
        project = {
            "_id": "proj_b", "company_id": "co_a",
            "weekend_work": True,
            "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        written = _run(missing_detector.detect_missing_for_project(
            db, project=project,
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 10),
            now=now,
        ))
        self.assertEqual(len(written), 7)

    def test_idempotent_on_rerun(self):
        # Each call upserts; the unique index makes re-runs
        # no-ops Mongo-side. We assert update_one is called with
        # the right shape (upsert=True + dedupe key).
        db = _build_db_with_logs(
            daily_log_dates=[],
            project_id="proj_a",
        )
        project = {
            "_id": "proj_a", "company_id": "co_a",
            "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        _run(missing_detector.detect_missing_for_project(
            db, project=project,
            start_date=date(2026, 5, 4), end_date=date(2026, 5, 8),
            now=now,
        ))
        # Inspect the first call's filter — must be the dedupe key.
        first_call = db.logbook_entries.update_one.call_args_list[0]
        filter_arg = first_call[0][0]
        self.assertEqual(
            sorted(filter_arg.keys()),
            ["category", "entry_date", "project_id"],
        )
        self.assertEqual(filter_arg["category"], logbook.CATEGORY_DAILY_LOG)
        # And upsert=True.
        self.assertTrue(first_call[1]["upsert"])

    def test_project_creation_floor(self):
        # Project created May 5; scan window starts May 1. Only
        # May 5+ should be checked (no false-positive missing rows
        # for dates before the project existed).
        db = _build_db_with_logs(
            daily_log_dates=[],
            project_id="proj_new",
            project_created=datetime(2026, 5, 5, tzinfo=timezone.utc),
        )
        project = {
            "_id": "proj_new", "company_id": "co_a",
            "created_at": datetime(2026, 5, 5, tzinfo=timezone.utc),
        }
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        written = _run(missing_detector.detect_missing_for_project(
            db, project=project,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 8),
            now=now,
        ))
        # May 5 is Tue. May 5-8 = Tue/Wed/Thu/Fri = 4 weekdays.
        self.assertEqual(len(written), 4)
        for e in written:
            self.assertGreaterEqual(e["entry_date"], "2026-05-05")

    def test_multi_project_isolation(self):
        # run_missing_detector_for_all_projects iterates project
        # cursor; each project gets its own pass. We verify by
        # giving two projects and counting calls.
        db = MagicMock()
        db.projects = MagicMock()
        db.projects.find = MagicMock(return_value=_AsyncCursor([
            {"_id": "p1", "company_id": "co_a", "status": "active",
             "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
            {"_id": "p2", "company_id": "co_a", "status": "active",
             "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
        ]))
        db.daily_logs = MagicMock()
        db.daily_logs.find = MagicMock(return_value=_AsyncCursor([]))
        db.logbook_entries = MagicMock()
        db.logbook_entries.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0),
        )
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        result = _run(missing_detector.run_missing_detector_for_all_projects(
            db, now=now,
        ))
        self.assertEqual(result["projects_scanned"], 2)
        self.assertGreater(result["missing_entries_written"], 0)
        self.assertEqual(result["errors"], 0)


# ──────────────────────────────────────────────────────────────────
# Deficiency rules
# ──────────────────────────────────────────────────────────────────


class TestDeficiencyRules(unittest.TestCase):

    def test_missing_manpower_positive(self):
        log = {"worker_count": 0, "notes": "", "work_performed": "rebar"}
        r = deficiency.rule_missing_manpower(log)
        self.assertIsNotNone(r)
        self.assertEqual(r["rule"], "missing_manpower")

    def test_missing_manpower_waived_by_no_work_marker(self):
        for marker in ("no work today", "rain day", "site closed"):
            log = {"worker_count": 0, "notes": marker, "work_performed": ""}
            self.assertIsNone(
                deficiency.rule_missing_manpower(log),
                f"marker {marker!r} should waive rule",
            )

    def test_missing_manpower_negative(self):
        log = {"worker_count": 5, "notes": "", "work_performed": "rebar"}
        self.assertIsNone(deficiency.rule_missing_manpower(log))

    def test_missing_weather_legacy_field(self):
        # Either the legacy `weather` field OR any of the split
        # fields satisfies.
        self.assertIsNone(deficiency.rule_missing_weather({"weather": "sunny"}))
        self.assertIsNone(deficiency.rule_missing_weather({"weather_temp": "72"}))
        # Both empty → deficient.
        r = deficiency.rule_missing_weather({"weather": "", "weather_temp": ""})
        self.assertIsNotNone(r)

    def test_missing_trade_work_positive(self):
        r = deficiency.rule_missing_trade_work({"work_performed": ""})
        self.assertIsNotNone(r)

    def test_missing_trade_work_negative(self):
        self.assertIsNone(
            deficiency.rule_missing_trade_work({"work_performed": "concrete pour"}),
        )

    def test_subcontractor_without_insurance_positive(self):
        log = {
            "subcontractor_cards": [{"company": "ACME Steel"}, {"company": "BetaPlumbing"}],
        }
        subs = [
            {"name": "ACME Steel", "coi_on_file": False},
            {"name": "BetaPlumbing", "coi_on_file": True},
        ]
        r = deficiency.rule_subcontractor_without_insurance(
            log, project_subs=subs,
        )
        self.assertIsNotNone(r)
        self.assertIn("ACME Steel", r["reason"])

    def test_subcontractor_without_insurance_negative(self):
        log = {"subcontractor_cards": [{"company": "ACME Steel"}]}
        subs = [{"name": "ACME Steel", "coi_on_file": True}]
        self.assertIsNone(
            deficiency.rule_subcontractor_without_insurance(
                log, project_subs=subs,
            ),
        )

    def test_subcontractor_rule_abstains_without_subs(self):
        # No project_subs supplied → abstain (don't false-positive
        # on every log).
        log = {"subcontractor_cards": [{"company": "ACME Steel"}]}
        self.assertIsNone(
            deficiency.rule_subcontractor_without_insurance(log),
        )

    def test_inspection_window_missed_positive(self):
        log = {"date": "2026-05-15"}
        project = {
            "inspection_windows": [
                {"label": "Concrete pour", "by_date": "2026-05-10",
                 "completed": False},
            ]
        }
        r = deficiency.rule_inspection_window_missed(
            log, project=project, today=date(2026, 5, 15),
        )
        self.assertIsNotNone(r)
        self.assertIn("Concrete pour", r["reason"])

    def test_inspection_window_completed_negative(self):
        log = {"date": "2026-05-15"}
        project = {
            "inspection_windows": [
                {"label": "Concrete pour", "by_date": "2026-05-10",
                 "completed": True},
            ]
        }
        self.assertIsNone(deficiency.rule_inspection_window_missed(
            log, project=project, today=date(2026, 5, 15),
        ))

    def test_detect_runs_all_rules(self):
        # Empty-ish log triggers manpower + weather + trade_work
        # all at once.
        log = {"worker_count": 0, "weather": "", "work_performed": ""}
        project = {}
        out = deficiency.detect_deficiencies(log, project)
        rule_names = {d["rule"] for d in out}
        self.assertIn("missing_manpower", rule_names)
        self.assertIn("missing_weather", rule_names)
        self.assertIn("missing_trade_work", rule_names)


# ──────────────────────────────────────────────────────────────────
# LL196 attestation
# ──────────────────────────────────────────────────────────────────


class TestLL196Status(unittest.TestCase):

    def test_current_sst(self):
        worker = {
            "name": "Alice", "trade": "Carpenter",
            "certifications": [{
                "type": "SST_FULL",
                "expiration_date": "2027-12-31",
            }],
        }
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        status, expiry = ll196._worker_sst_status(worker, now=now)
        self.assertEqual(status, "current")
        self.assertEqual(expiry, "2027-12-31")

    def test_expired_sst(self):
        worker = {
            "name": "Bob",
            "certifications": [{
                "type": "SST_FULL",
                "expiration_date": "2024-01-01",
            }],
        }
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        status, expiry = ll196._worker_sst_status(worker, now=now)
        self.assertEqual(status, "expired")

    def test_missing_sst(self):
        worker = {
            "name": "Carol",
            "certifications": [{"type": "OSHA_10"}],  # OSHA only
        }
        status, _ = ll196._worker_sst_status(worker)
        self.assertEqual(status, "missing")

    def test_no_expiry_sst(self):
        worker = {
            "name": "Dave",
            "certifications": [{"type": "SST_LIMITED"}],
        }
        status, expiry = ll196._worker_sst_status(worker)
        self.assertEqual(status, "no_expiry")
        self.assertIsNone(expiry)


class TestLL196AttestationData(unittest.TestCase):

    def test_all_current_workers_complete_status(self):
        project = {"_id": "p1", "name": "Test Project", "company_id": "co_a"}
        workers = [
            {"name": "A", "trade": "Carp",
             "certifications": [{"type": "SST_FULL", "expiration_date": "2027-01-01"}]},
            {"name": "B", "trade": "Iron",
             "certifications": [{"type": "SST_SUPERVISOR", "expiration_date": "2027-01-01"}]},
        ]
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        out = ll196.build_attestation_data(
            project=project, workers=workers,
            year=2026, month=5, now=now,
        )
        self.assertEqual(out["worker_count"], 2)
        self.assertEqual(out["counts"]["current"], 2)
        self.assertEqual(out["deficient_count"], 0)
        self.assertEqual(out["overall_status"], logbook.STATUS_COMPLETE)
        self.assertEqual(out["period_label"], "2026-05")

    def test_some_deficient_workers_deficient_status(self):
        project = {"_id": "p1", "name": "Test Project", "company_id": "co_a"}
        workers = [
            {"name": "A", "trade": "Carp",
             "certifications": [{"type": "SST_FULL", "expiration_date": "2027-01-01"}]},
            {"name": "B", "trade": "Iron",
             "certifications": []},
        ]
        out = ll196.build_attestation_data(
            project=project, workers=workers, year=2026, month=5,
        )
        self.assertEqual(out["counts"]["missing"], 1)
        self.assertEqual(out["overall_status"], logbook.STATUS_DEFICIENT)
        self.assertIn("deficien", out["summary"].lower())

    def test_roster_sorts_deficient_first(self):
        project = {"_id": "p1", "name": "X", "company_id": "co_a"}
        workers = [
            {"name": "ZZGood", "trade": "",
             "certifications": [{"type": "SST_FULL", "expiration_date": "2027-01-01"}]},
            {"name": "AABad", "trade": "", "certifications": []},
        ]
        out = ll196.build_attestation_data(
            project=project, workers=workers, year=2026, month=5,
        )
        # The missing worker (AABad) should come BEFORE the
        # current one (ZZGood) regardless of name sort.
        self.assertEqual(out["roster"][0]["sst_status"], "missing")
        self.assertEqual(out["roster"][1]["sst_status"], "current")


class TestLL196HtmlRender(unittest.TestCase):

    def test_html_contains_required_strings(self):
        attestation = ll196.build_attestation_data(
            project={"_id": "p1", "name": "ESB Project", "company_id": "co_a"},
            workers=[
                {"name": "Alice", "trade": "Carp",
                 "certifications": [{"type": "SST_FULL",
                                     "expiration_date": "2027-01-01"}]},
            ],
            year=2026, month=5,
        )
        html = ll196.render_attestation_html(attestation)
        self.assertIn("LL196", html)
        self.assertIn("Site Safety Training", html)
        self.assertIn("ESB Project", html)
        self.assertIn("2026-05", html)
        self.assertIn("Alice", html)

    def test_html_escapes_project_name(self):
        attestation = ll196.build_attestation_data(
            project={"_id": "p", "name": "<script>alert(1)</script>",
                     "company_id": "co_a"},
            workers=[],
            year=2026, month=5,
        )
        html = ll196.render_attestation_html(attestation)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestLL196R2Key(unittest.TestCase):

    def test_deterministic_key(self):
        attestation = {
            "company_id": "co_a", "project_id": "p1",
            "period_label": "2026-05",
        }
        self.assertEqual(
            ll196.r2_key_for(attestation),
            "ll196/co_a/p1/2026-05.pdf",
        )


class TestLL196Orchestrator(unittest.TestCase):
    """End-to-end: stub out R2 + PDF render so the test runs
    without weasyprint native deps or network. Asserts the
    logbook_entries upsert happens with the right shape."""

    def test_full_pipeline_writes_entry_and_uploads(self):
        db = MagicMock()
        project_doc = {"_id": "p1", "name": "X", "company_id": "co_a"}
        db.projects = MagicMock()
        db.projects.find_one = AsyncMock(return_value=project_doc)
        db.workers = MagicMock()
        db.workers.find = MagicMock(return_value=_AsyncCursor([
            {"name": "A", "trade": "C",
             "certifications": [{"type": "SST_FULL",
                                 "expiration_date": "2027-01-01"}]},
        ]))
        db.logbook_entries = MagicMock()
        db.logbook_entries.update_one = AsyncMock(
            return_value=MagicMock(upserted_id="x"),
        )

        upload_calls = []
        def _stub_uploader(b, k, ct):
            upload_calls.append({"size": len(b), "key": k, "ct": ct})
            return f"https://r2.example/{k}"

        render_calls = []
        def _stub_renderer(html):
            render_calls.append(html)
            return b"%PDF-1.7 stub bytes"

        entry = _run(ll196.generate_ll196_attestation(
            db,
            project_id="p1", year=2026, month=5,
            r2_uploader=_stub_uploader,
            pdf_renderer=_stub_renderer,
            triggered_by_user_id="u_admin",
        ))

        # PDF rendered, R2 uploaded, entry upserted.
        self.assertEqual(len(render_calls), 1)
        self.assertEqual(len(upload_calls), 1)
        self.assertEqual(upload_calls[0]["key"], "ll196/co_a/p1/2026-05.pdf")
        self.assertEqual(upload_calls[0]["ct"], "application/pdf")

        self.assertTrue(db.logbook_entries.update_one.called)
        filter_arg = db.logbook_entries.update_one.call_args[0][0]
        self.assertEqual(filter_arg["project_id"], "p1")
        self.assertEqual(filter_arg["category"], logbook.CATEGORY_LL196)
        self.assertEqual(entry["category"], logbook.CATEGORY_LL196)
        self.assertEqual(entry["status"], logbook.STATUS_COMPLETE)


# ──────────────────────────────────────────────────────────────────
# Endpoints — feature-flag gating
# ──────────────────────────────────────────────────────────────────


def _setup_authed_client(*, role="admin", user_id="u_x", company_id="co_a"):
    import server
    user = {"id": user_id, "_id": user_id,
            "role": role, "company_id": company_id}
    async def _fake_user():
        return user
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app, raise_server_exceptions=False), \
        lambda: server.app.dependency_overrides.clear()


def _build_endpoint_db(*, flag_doc=None, logbook_entries=None,
                       project_doc=None, workers=None):
    """db with the feature_flags + logbook_entries surfaces the
    endpoints touch."""
    db = MagicMock()
    db.feature_flags = MagicMock()
    db.feature_flags.find_one = AsyncMock(return_value=flag_doc)

    entries = logbook_entries or []
    db.logbook_entries = MagicMock()

    def _find(*a, **k):
        # Cursor used by every endpoint that lists entries.
        return _AsyncCursor(entries)
    db.logbook_entries.find = MagicMock(side_effect=_find)
    db.logbook_entries.update_one = AsyncMock(
        return_value=MagicMock(upserted_id="x"),
    )

    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(
        return_value=project_doc or {
            "_id": "p1", "name": "Test", "company_id": "co_a",
        },
    )
    db.workers = MagicMock()
    db.workers.find = MagicMock(return_value=_AsyncCursor(workers or []))
    return db


class TestEndpointsFlagDisabled(unittest.TestCase):
    """Every logbook endpoint MUST 404 when the feature flag is off
    — the surface doesn't exist for v1 customers, full stop. No 403,
    no error message — 404 hides the existence of v2 features."""

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def _check_404(self, method, path, **kwargs):
        import server
        # No flag in DB → is_feature_enabled returns False (a) →
        # endpoint returns 404.
        db = _build_endpoint_db(flag_doc=None)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                fn = getattr(client, method.lower())
                r = fn(path, **kwargs)
                self.assertEqual(r.status_code, 404, r.text)
        finally:
            restore()

    def test_audit_404(self):
        self._check_404("GET", "/api/projects/p1/logbook/audit")

    def test_missing_404(self):
        self._check_404("GET", "/api/projects/p1/logbook/missing")

    def test_deficiencies_404(self):
        self._check_404("GET", "/api/projects/p1/logbook/deficiencies")

    def test_attestations_404(self):
        self._check_404("GET", "/api/projects/p1/logbook/attestations")

    def test_generate_attestation_404(self):
        self._check_404(
            "POST", "/api/projects/p1/logbook/attestations/generate",
            json={"year": 2026, "month": 5},
        )

    def test_export_404(self):
        self._check_404("GET", "/api/projects/p1/logbook/export")


class TestEndpointsFlagEnabled(unittest.TestCase):

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def test_audit_returns_calendar_grid(self):
        import server
        flag = {
            "flag": "v2_logbook", "enabled_globally": True,
            "enabled_for_companies": [], "enabled_for_users": [],
            "enabled_percentage": 0,
        }
        entries = [
            {"_id": "e1", "project_id": "p1", "entry_date": "2026-05-04",
             "category": "daily_log", "status": "complete"},
            {"_id": "e2", "project_id": "p1", "entry_date": "2026-05-05",
             "category": "daily_log", "status": "missing"},
        ]
        db = _build_endpoint_db(flag_doc=flag, logbook_entries=entries)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.get(
                    "/api/projects/p1/logbook/audit"
                    "?start_date=2026-05-04&end_date=2026-05-05",
                )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["project_id"], "p1")
                self.assertEqual(len(body["days"]), 2)
                # Day 04: complete → green; Day 05: missing → red.
                day_map = {d["date"]: d["color"] for d in body["days"]}
                self.assertEqual(day_map["2026-05-04"], "green")
                self.assertEqual(day_map["2026-05-05"], "red")
        finally:
            restore()

    def test_missing_endpoint_returns_entries(self):
        import server
        flag = {"flag": "v2_logbook", "enabled_globally": True}
        entries = [
            {"_id": "e1", "project_id": "p1", "entry_date": "2026-05-05",
             "category": "daily_log", "status": "missing"},
        ]
        db = _build_endpoint_db(flag_doc=flag, logbook_entries=entries)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/projects/p1/logbook/missing")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(len(r.json()["entries"]), 1)
        finally:
            restore()

    def test_generate_attestation_validates_month(self):
        import server
        flag = {"flag": "v2_logbook", "enabled_globally": True}
        db = _build_endpoint_db(flag_doc=flag)
        client, restore = _setup_authed_client()
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/projects/p1/logbook/attestations/generate",
                    json={"year": 2026, "month": 13},
                )
                self.assertEqual(r.status_code, 422)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# Frontend audit screen — static-source pins
# ──────────────────────────────────────────────────────────────────


class TestFrontendAuditScreen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (_REPO / "frontend" / "app" / "project" / "[id]"
                    / "audit.jsx")
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_uses_feature_flag_hook(self):
        self.assertIn("useFeatureFlag('v2_logbook')", self.text)

    def test_flag_check_is_first_hook(self):
        """Rules-of-hooks: useFeatureFlag MUST be called before
        any other hook, and at the top of the component body
        (not inside a try/catch, not after an early return).
        Pinned via line-order check."""
        # Find the function's open brace.
        comp_idx = self.text.find("export default function ComplianceAuditScreen()")
        self.assertGreater(comp_idx, 0)
        body_open = self.text.find("{", comp_idx)
        # Find first useFeatureFlag and first OTHER hook.
        flag_idx = self.text.find("useFeatureFlag", body_open)
        # Other built-in hooks used by the screen.
        other_hooks = ("useRouter(", "useLocalSearchParams(", "useAuth(",
                       "useTheme(", "useState(", "useEffect(", "useMemo(")
        first_other = min(
            (self.text.find(h, body_open) for h in other_hooks
             if self.text.find(h, body_open) > 0),
            default=-1,
        )
        self.assertGreater(flag_idx, 0, "useFeatureFlag missing")
        self.assertGreater(first_other, 0)
        self.assertLess(
            flag_idx, first_other,
            "useFeatureFlag must be the FIRST hook called (rules-of-hooks)",
        )

    def test_returns_null_when_flag_disabled(self):
        """The flag-off render path MUST be `return null` — not a
        spinner, not a placeholder, NOTHING. v1 users see no v2
        UI flicker even briefly."""
        self.assertIn("if (!v2LogbookEnabled)", self.text)
        # The literal `return null;` follows.
        flag_check = self.text.find("if (!v2LogbookEnabled)")
        next_return = self.text.find("return null", flag_check)
        self.assertGreater(next_return, flag_check)
        # And it appears before the main JSX return so it short-
        # circuits.
        main_render = self.text.find("return (", flag_check)
        self.assertGreater(main_render, next_return)

    def test_calls_audit_endpoint(self):
        self.assertIn("/api/projects/${projectId}/logbook/audit", self.text)

    def test_uses_design_system(self):
        # AnimatedBackground + GlassCard + useTheme — same chrome
        # as every other v1 screen, just gated.
        self.assertIn("AnimatedBackground", self.text)
        self.assertIn("GlassCard", self.text)
        self.assertIn("useTheme", self.text)


# ──────────────────────────────────────────────────────────────────
# Post-save deficiency hook (server.py wiring)
# ──────────────────────────────────────────────────────────────────


class TestPostSaveHook(unittest.TestCase):

    def test_hook_present_in_create_daily_log(self):
        """Pin: the v2_logbook post-save deficiency hook is wired
        AFTER the daily_logs.insert_one call. A future cleanup
        that drops it would silently regress the deficiency
        feedback loop."""
        text = (_BACKEND / "server.py").read_text(encoding="utf-8")
        anchor = "result = await db.daily_logs.insert_one(log_dict)"
        end_anchor = "return DailyLogResponse(**log_dict)"
        s_idx = text.find(anchor)
        e_idx = text.find(end_anchor, s_idx)
        self.assertGreater(s_idx, 0)
        self.assertGreater(e_idx, s_idx)
        slice_ = text[s_idx:e_idx]
        self.assertIn("run_deficiency_check_post_save", slice_)
        self.assertIn("v2_logbook", slice_)
        # And it's wrapped in try/except so a hook bug never
        # breaks the daily_log save itself.
        self.assertIn("except Exception", slice_)


# ──────────────────────────────────────────────────────────────────
# Scheduler tick
# ──────────────────────────────────────────────────────────────────


class TestSchedulerTick(unittest.TestCase):

    def test_nightly_tick_registered_with_3am_et_cron(self):
        text = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("v2_logbook_nightly_tick", text)
        self.assertIn("CronTrigger(hour=3, minute=0, timezone=\"America/New_York\")", text)

    def test_tick_calls_both_detectors(self):
        text = (_BACKEND / "server.py").read_text(encoding="utf-8")
        # Locate the nightly-tick coroutine.
        s = text.find("async def _logbook_nightly_tick")
        self.assertGreater(s, 0)
        e = text.find("scheduler.add_job", s)
        self.assertGreater(e, s)
        slice_ = text[s:e]
        self.assertIn("run_missing_detector_for_all_projects", slice_)
        self.assertIn("run_deficiency_detector_for_all_projects", slice_)


if __name__ == "__main__":
    unittest.main()
