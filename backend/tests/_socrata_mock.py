"""Shared SocrataClient test double for the V2.3 lazy-query tests.

Used by test_v2_3_baselines.py / test_v2_3_triggers.py /
test_v2_3_calibration.py. Filename starts with ``_`` so pytest's
default collector skips it.

Two ergonomic modes for seeding mock responses:

  • ``seed(dataset_id, rows)`` — register a row pool. Calls to
    ``query`` / ``query_all`` filter that pool by interpreting the
    SoQL WHERE clause that production code emitted. Tests stay
    intent-focused — they declare the data shape, not the SoQL.

  • ``add_handler(dataset_id, match=..., rows=...)`` — register a
    custom response keyed on a predicate over the call kwargs.
    Use when a test needs to assert exact-call shape or distinguish
    two queries to the same dataset based on their WHERE.

The internal WHERE evaluator supports the SoQL subset the V2.3
production code emits:

  • ``field = 'value'`` / ``field = value``
  • ``field > 'value'`` (and ``>=``, ``<``, ``<=``, ``!=``)
  • ``field IN ('v1','v2',...)``
  • ``starts_with(field, 'prefix')``
  • Conjunction via ``AND`` only (no OR, no NOT, no parens)
  • Aggregation: ``$group=bbl`` + ``$select=bbl,count(*) AS n``
    is handled by collapsing matched rows by group key.

Anything outside that subset raises so a test doesn't silently
pass with wrong data. If you find the production code emitting
new SoQL syntax, extend the evaluator here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── WHERE clause evaluator ────────────────────────────────────────


_RE_STARTS_WITH = re.compile(
    r"starts_with\(\s*(\w+)\s*,\s*'([^']*)'\s*\)", re.IGNORECASE,
)
_RE_IN = re.compile(
    r"(\w+)\s+in\s+\(([^)]+)\)", re.IGNORECASE,
)
_RE_COMPARE_STR = re.compile(
    r"(\w+)\s*(>=|<=|!=|=|>|<)\s*'([^']*)'",
)
_RE_COMPARE_NUM = re.compile(
    r"(\w+)\s*(>=|<=|!=|=|>|<)\s*(-?\d+(?:\.\d+)?)",
)
_RE_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)


def _coerce_dt(s: str) -> Optional[datetime]:
    """If a SoQL literal looks like an ISO-8601 timestamp, parse it
    to a UTC datetime so date comparisons work against datetime
    fields in the seeded rows. Otherwise return None."""
    if not isinstance(s, str):
        return None
    if not re.match(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        s_clean = s.rstrip("Z")
        dt = datetime.fromisoformat(s_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _compare(actual: Any, op: str, expected_str: str) -> bool:
    """Apply a SoQL comparator. Special-cases timestamps so a
    datetime field in the seeded row compares correctly against
    an ISO-8601 string in the WHERE clause."""
    if actual is None:
        return False
    # Try timestamp comparison first.
    expected_dt = _coerce_dt(expected_str)
    actual_dt = actual if isinstance(actual, datetime) else _coerce_dt(actual)
    if expected_dt is not None and actual_dt is not None:
        if actual_dt.tzinfo is None:
            actual_dt = actual_dt.replace(tzinfo=timezone.utc)
        a, e = actual_dt, expected_dt
    else:
        a, e = str(actual), expected_str
    return _eval_op(a, op, e)


def _eval_op(a: Any, op: str, e: Any) -> bool:
    if op == "=":  return a == e
    if op == "!=": return a != e
    if op == ">":  return a > e
    if op == ">=": return a >= e
    if op == "<":  return a < e
    if op == "<=": return a <= e
    raise AssertionError(f"unsupported op: {op!r}")


def _eval_clause(clause: str, row: Dict[str, Any]) -> bool:
    clause = clause.strip()
    if not clause:
        return True

    m = _RE_STARTS_WITH.match(clause)
    if m:
        field, prefix = m.group(1), m.group(2)
        val = row.get(field)
        return isinstance(val, str) and val.startswith(prefix)

    m = _RE_IN.match(clause)
    if m:
        field, items_str = m.group(1), m.group(2)
        # Items are single-quoted strings OR bare numbers.
        items: List[str] = []
        for q, n in re.findall(r"'([^']*)'|(-?\d+(?:\.\d+)?)", items_str):
            items.append(q if q else n)
        actual = row.get(field)
        return str(actual) in items

    m = _RE_COMPARE_STR.match(clause)
    if m:
        field, op, val = m.group(1), m.group(2), m.group(3)
        return _compare(row.get(field), op, val)

    m = _RE_COMPARE_NUM.match(clause)
    if m:
        field, op, val_str = m.group(1), m.group(2), m.group(3)
        actual = row.get(field)
        if actual is None:
            return False
        try:
            return _eval_op(float(actual), op, float(val_str))
        except (TypeError, ValueError):
            return False

    raise AssertionError(
        f"_socrata_mock WHERE evaluator can't parse clause: {clause!r}",
    )


def evaluate_where(where: Optional[str], row: Dict[str, Any]) -> bool:
    """Apply a SoQL WHERE to one row. None / empty → match-all."""
    if not where:
        return True
    parts = _RE_AND.split(where)
    return all(_eval_clause(p, row) for p in parts)


# ── Mock client ───────────────────────────────────────────────────


_Handler = Tuple[str, Optional[Callable[[Dict[str, Any]], bool]], List[Dict[str, Any]]]


class MockSocrataClient:
    """Drop-in test double for ``lib.statistical_engine.socrata_client.SocrataClient``.

    Implements the same async surface (``query`` / ``query_all``)
    so production code passes through unchanged. Seeded data is
    filtered by interpreting the WHERE clause the production code
    emits; aggregation ($group + count(*)) is collapsed in Python.

    Attributes for assertions:
      • ``calls`` — every (dataset_id, kwargs) tuple, in order.
    """

    def __init__(self) -> None:
        self._datasets: Dict[str, List[Dict[str, Any]]] = {}
        self._handlers: List[_Handler] = []
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    # ── Seeding API ────────────────────────────────────────────

    def seed(self, dataset_id: str, rows: List[Dict[str, Any]]) -> None:
        """Register a row pool for a dataset. Multiple seed() calls
        for the same dataset append."""
        self._datasets.setdefault(dataset_id, []).extend(rows)

    def add_handler(
        self,
        dataset_id: str,
        *,
        match: Optional[Callable[[Dict[str, Any]], bool]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
        raises: Optional[BaseException] = None,
    ) -> None:
        """Register a custom-response handler. The first matching
        handler wins; falls through to the seeded row pool if
        none match. ``match`` receives the call kwargs dict
        (where / select / order / limit / offset / group). Pass
        ``raises`` to make the handler raise an exception
        (typically ``SocrataQueryError``)."""
        if raises is not None:
            def _raising(_kw: Dict[str, Any]) -> List[Dict[str, Any]]:
                raise raises
            # Stash the raising thunk via the handler tuple; we
            # detect the special case at call time.
            self._handlers.append((dataset_id, match, [_RAISE_SENTINEL, raises]))
            return
        self._handlers.append((dataset_id, match, list(rows or [])))

    # ── Async surface that production code calls ───────────────

    async def query(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[List[str]] = None,
        order: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        kw = {
            "where": where, "select": select, "order": order,
            "limit": limit, "offset": offset, "group": group,
        }
        self.calls.append((dataset_id, kw))

        # Custom handlers take precedence.
        for d_id, match, response in self._handlers:
            if d_id != dataset_id:
                continue
            if match is None or match(kw):
                if response and response[0] is _RAISE_SENTINEL:
                    raise response[1]
                return list(response)

        rows = list(self._datasets.get(dataset_id, []))
        filtered = [r for r in rows if evaluate_where(where, r)]

        # $group + count() handling. Production code uses this
        # shape only for the peer-count aggregation:
        #   select=["bbl", "count(*) AS n"], group="bbl"
        if group:
            buckets: Dict[Any, int] = {}
            for r in filtered:
                key = r.get(group)
                buckets[key] = buckets.get(key, 0) + 1
            agg_rows = [
                {group: k, "n": str(v)} for k, v in buckets.items()
            ]
            agg_rows.sort(key=lambda r: str(r.get(group)))
            return agg_rows[offset:offset + limit]

        # Apply $select projection (best-effort — we don't try to
        # parse aggregate functions if no group was supplied).
        if select:
            plain_fields = [
                f for f in select if "(" not in f and " AS " not in f.upper()
            ]
            if plain_fields and len(plain_fields) == len(select):
                filtered = [
                    {f: r.get(f) for f in plain_fields} for r in filtered
                ]

        return filtered[offset:offset + limit]

    async def query_all(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[List[str]] = None,
        order: Optional[str] = None,
        page_size: int = 5000,
        max_pages: Optional[int] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # For the mock, paginate over the full filtered set so
        # tests can also exercise the page-size logic if they want
        # to. Mirrors SocrataClient.query_all's loop.
        all_rows: List[Dict[str, Any]] = []
        offset = 0
        pages_fetched = 0
        while True:
            page = await self.query(
                dataset_id,
                where=where, select=select, order=order,
                limit=page_size, offset=offset, group=group,
            )
            all_rows.extend(page)
            pages_fetched += 1
            if len(page) < page_size:
                return all_rows
            if max_pages is not None and pages_fetched >= max_pages:
                return all_rows
            offset += page_size


# Sentinel used by add_handler(raises=...) to flag a raising response
# without leaking a real exception object through the tuple's row slot.
class _RaiseSentinel:
    pass


_RAISE_SENTINEL = _RaiseSentinel()
