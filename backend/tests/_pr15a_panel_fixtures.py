"""PR #15A test stub collections — daily_panels + prediction_validation_ledger.

Filename starts with ``_`` so pytest's default collector skips this
module — it carries class stubs that mirror the Motor async Mongo
API surface PR #15A's production code will call against the real
``db`` handle.

Two stubs:

  • ``_StubDailyPanels`` — supports ``insert_many``, ``find``,
    ``delete_many``, and a minimal aggregate pipeline matching what
    the panel-build cron and the rolling-30d Brier computation
    actually invoke.

  • ``_StubPredictionValidationLedger`` — supports ``insert_one``,
    ``update_one`` with ``upsert=True`` (the T7 canonical-per-day
    pattern), ``find``, and the rolling-30d Brier aggregation.

Both stubs deliberately mirror ``test_pr14c_wiring._StubProjects`` so
PR #15A tests can compose them through a single ``_StubDb`` wrapper
that exposes ``.projects``, ``.daily_panels``, and
``.prediction_validation_ledger`` attributes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock


class _StubDailyPanels:
    """Mock Mongo collection for the ``daily_panels`` collection PR
    #15A nightly cron will write into.

    Mirrors ``_StubProjects`` patterns (test_pr14c_wiring.py +
    test_pr14e_unified_cohort.py): keeps an in-memory ``docs`` list,
    records every mutation call for assertion replay.
    """

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.insert_many_calls: List[Dict[str, Any]] = []
        self.delete_many_calls: List[Dict[str, Any]] = []

    async def insert_many(self, rows, **_kwargs):
        # rows may be a generator or list; materialize so we don't
        # exhaust the iterator before downstream tests inspect it.
        materialized = list(rows)
        self.insert_many_calls.append({"rows": materialized})
        self.docs.extend(materialized)
        r = MagicMock()
        r.inserted_ids = [None] * len(materialized)
        return r

    async def delete_many(self, filter_, **_kwargs):
        self.delete_many_calls.append({"filter": filter_})
        kept: List[Dict[str, Any]] = []
        deleted = 0
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                deleted += 1
            else:
                kept.append(d)
        self.docs = kept
        r = MagicMock()
        r.deleted_count = deleted
        return r

    def find(self, filter_, projection=None):
        """Synchronous returning an iterable. PR #15A's panel reader
        is expected to use ``.to_list()`` patterns or ``async for``;
        this stub returns ``_AsyncFindResult`` to support both."""
        matched = [
            dict(d) for d in self.docs
            if all(d.get(k) == v for k, v in (filter_ or {}).items())
        ]
        return _AsyncFindResult(matched)

    async def count_documents(self, filter_=None):
        if not filter_:
            return len(self.docs)
        return sum(
            1 for d in self.docs
            if all(d.get(k) == v for k, v in filter_.items())
        )

    async def find_one(self, filter_, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                return dict(d)
        return None


class _StubPredictionValidationLedger:
    """Mock Mongo collection for ``prediction_validation_ledger``.

    Supports the T7 upsert-per-(project_id, calendar_date) pattern
    via ``update_one(upsert=True)`` AND the rolling-30d Brier
    aggregation pipeline via ``aggregate``.
    """

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.insert_one_calls: List[Dict[str, Any]] = []
        self.update_one_calls: List[Dict[str, Any]] = []

    async def insert_one(self, doc, **_kwargs):
        self.insert_one_calls.append({"doc": dict(doc)})
        self.docs.append(dict(doc))
        r = MagicMock()
        r.inserted_id = None
        return r

    async def update_one(self, filter_, update, upsert=False, **_kwargs):
        self.update_one_calls.append({
            "filter":  dict(filter_),
            "update":  dict(update),
            "upsert":  upsert,
        })
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock()
                r.matched_count = 1
                r.upserted_id = None
                return r
        if upsert:
            new_doc = dict(filter_)
            if "$set" in update:
                new_doc.update(update["$set"])
            self.docs.append(new_doc)
            r = MagicMock()
            r.matched_count = 0
            r.upserted_id = "new"
            return r
        r = MagicMock()
        r.matched_count = 0
        r.upserted_id = None
        return r

    async def find_one(self, filter_, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                return dict(d)
        return None

    def find(self, filter_=None, projection=None):
        """Supports the validation_audit_sweep filter shape:
        {"target_horizon_at": {"$lt": now}, "observed_outcome": None}."""
        matched = [
            dict(d) for d in self.docs
            if _match_doc(d, filter_ or {})
        ]
        return _AsyncFindResult(matched)

    async def count_documents(self, filter_=None):
        if not filter_:
            return len(self.docs)
        return sum(
            1 for d in self.docs
            if _match_doc(d, filter_)
        )

    def aggregate(self, pipeline, **_kwargs):
        """Minimal aggregation evaluator. Supports the rolling-30d
        Brier query shape:

          [
            {"$match": {"project_id": ..., "scored_at": {"$gte": ...},
                        "observed_outcome": {"$ne": None}}},
            {"$group": {"_id": None, "brier_mean": {"$avg": "$brier_score_delta"},
                        "n": {"$sum": 1}}},
          ]

        Returns an ``_AsyncFindResult`` so callers can ``async for``
        the result rows.
        """
        rows = [dict(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                rows = [r for r in rows if _match_doc(r, stage["$match"])]
            elif "$group" in stage:
                rows = [_group_docs(rows, stage["$group"])]
        return _AsyncFindResult(rows)


# ── Internal helpers ──────────────────────────────────────────────


class _AsyncFindResult:
    """Iterable supporting ``async for`` and ``.to_list(limit)``.
    Mirrors Motor's AsyncIOMotorCursor minimal surface."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows
        self._idx = 0

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._idx]
        self._idx += 1
        return row

    async def to_list(self, length=None):
        if length is None:
            return list(self._rows)
        return list(self._rows[:length])

    def sort(self, key, direction=1):
        rev = direction == -1
        self._rows.sort(key=lambda r: r.get(key), reverse=rev)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self


def _match_doc(doc: Dict[str, Any], match: Dict[str, Any]) -> bool:
    for key, criterion in match.items():
        val = doc.get(key)
        if isinstance(criterion, dict):
            for op, target in criterion.items():
                if op == "$gte" and not (val is not None and val >= target):
                    return False
                if op == "$lte" and not (val is not None and val <= target):
                    return False
                if op == "$gt" and not (val is not None and val > target):
                    return False
                if op == "$lt" and not (val is not None and val < target):
                    return False
                if op == "$ne" and val == target:
                    return False
                if op == "$eq" and val != target:
                    return False
                if op == "$in" and val not in target:
                    return False
                if op == "$nin" and val in target:
                    return False
                if op == "$exists":
                    has_key = key in doc
                    if target and not has_key:
                        return False
                    if (not target) and has_key:
                        return False
        else:
            if val != criterion:
                return False
    return True


def _group_docs(rows: List[Dict[str, Any]], group: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"_id": group.get("_id")}
    for key, expr in group.items():
        if key == "_id":
            continue
        if not isinstance(expr, dict):
            continue
        op, target = next(iter(expr.items()))
        if op == "$avg":
            field = target.lstrip("$")
            vals = [r.get(field) for r in rows if r.get(field) is not None]
            out[key] = (sum(vals) / len(vals)) if vals else 0.0
        elif op == "$sum":
            if target == 1 or target == "1":
                out[key] = len(rows)
            else:
                field = str(target).lstrip("$")
                out[key] = sum(
                    r.get(field, 0) for r in rows
                    if r.get(field) is not None
                )
        elif op == "$min":
            field = target.lstrip("$")
            vals = [r.get(field) for r in rows if r.get(field) is not None]
            out[key] = min(vals) if vals else None
        elif op == "$max":
            field = target.lstrip("$")
            vals = [r.get(field) for r in rows if r.get(field) is not None]
            out[key] = max(vals) if vals else None
    return out


class _StubPredictionModels:
    """PR #15B stub for ``prediction_models`` collection.

    Supports the per-(project_id, fit_at) write pattern used by the
    nightly refit cron and the model-hash lookup used by live
    mutation. Mirrors _StubPredictionValidationLedger semantics —
    find_one + update_one(upsert=True) + insert_one + find.
    """

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.insert_one_calls: List[Dict[str, Any]] = []
        self.update_one_calls: List[Dict[str, Any]] = []

    async def insert_one(self, doc, **_kwargs):
        self.insert_one_calls.append({"doc": dict(doc)})
        self.docs.append(dict(doc))
        r = MagicMock()
        r.inserted_id = None
        return r

    async def update_one(self, filter_, update, upsert=False, **_kwargs):
        self.update_one_calls.append({
            "filter": dict(filter_),
            "update": dict(update),
            "upsert": upsert,
        })
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock()
                r.matched_count = 1
                r.upserted_id = None
                return r
        if upsert:
            new_doc = dict(filter_)
            if "$set" in update:
                new_doc.update(update["$set"])
            self.docs.append(new_doc)
            r = MagicMock()
            r.matched_count = 0
            r.upserted_id = "new"
            return r
        r = MagicMock()
        r.matched_count = 0
        r.upserted_id = None
        return r

    async def find_one(self, filter_, projection=None, sort=None):
        matched = [
            d for d in self.docs
            if all(d.get(k) == v for k, v in (filter_ or {}).items())
        ]
        if sort:
            for key, direction in sort:
                matched.sort(key=lambda r: r.get(key) or 0,
                             reverse=(direction == -1))
        return dict(matched[0]) if matched else None

    def find(self, filter_, projection=None):
        matched = [
            dict(d) for d in self.docs
            if all(d.get(k) == v for k, v in (filter_ or {}).items())
        ]
        return _AsyncFindResult(matched)

    async def count_documents(self, filter_=None):
        if not filter_:
            return len(self.docs)
        return sum(
            1 for d in self.docs
            if all(d.get(k) == v for k, v in filter_.items())
        )


class _StubProjectsForCache:
    """PR #15B stub of db.projects supporting find_one + update_one
    with $set on prediction_cache sub-document. Used by live mutation
    tests that need to write back to projects.prediction_cache."""

    def __init__(self, projects: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(projects or [])
        self.update_one_calls: List[Dict[str, Any]] = []

    async def find_one(self, filter_, projection=None):
        for d in self.docs:
            ok = True
            for k, v in (filter_ or {}).items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                return dict(d)
        return None

    async def update_one(self, filter_, update, upsert=False, **_kwargs):
        self.update_one_calls.append({
            "filter": dict(filter_),
            "update": dict(update),
            "upsert": upsert,
        })
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        # support dotted "prediction_cache.foo" keys
                        if "." in k:
                            head, tail = k.split(".", 1)
                            sub = d.setdefault(head, {})
                            sub[tail] = v
                        else:
                            d[k] = v
                r = MagicMock()
                r.matched_count = 1
                r.upserted_id = None
                return r
        r = MagicMock()
        r.matched_count = 0
        r.upserted_id = None
        return r

    def find(self, filter_=None, projection=None):
        """PR #15B Stage 3.B — supports nightly_refit_for_all_projects
        iterating over active projects. Uses _match_doc to handle
        $ne/$in/$lt/$gt filters."""
        matched = [
            dict(d) for d in self.docs
            if _match_doc(d, filter_ or {})
        ]
        return _AsyncFindResult(matched)


class _StubDb:
    """Composite stub matching the prod ``db`` shape PR #15A reads.

    Carries:
      • ``projects`` — _StubProjects from test_pr14c_wiring (or
        _StubProjectsForCache for PR #15B live-mutation tests)
      • ``daily_panels`` — _StubDailyPanels (this module)
      • ``prediction_validation_ledger`` — _StubPredictionValidationLedger
      • ``prediction_models`` — _StubPredictionModels (PR #15B)
      • ``dob_logs`` — placeholder for the existing dob_logs collection
        (PR #15A may not need to mutate; tests pass a pre-populated
        list of dicts)

    Tests that don't need a particular collection can pass ``None``
    for that arg.
    """

    def __init__(
        self,
        *,
        projects: Optional[Any] = None,
        daily_panels: Optional[Any] = None,
        prediction_validation_ledger: Optional[Any] = None,
        prediction_models: Optional[Any] = None,
        dob_logs: Optional[Any] = None,
    ) -> None:
        self.projects = projects
        self.daily_panels = daily_panels or _StubDailyPanels()
        self.prediction_validation_ledger = (
            prediction_validation_ledger or _StubPredictionValidationLedger()
        )
        self.prediction_models = prediction_models or _StubPredictionModels()
        self.dob_logs = dob_logs
