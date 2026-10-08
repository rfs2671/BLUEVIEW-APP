"""THE LIST COSTS THE INDEX, NOT THE CORPUS — and the old read is untouched.

GET /logbooks/project/{id}/submitted is the gate tablet's only logbook read and
the only way a DOB inspector standing on the site reaches a filed compliance
record. It took ~10 MINUTES to draw a list of dates.

── THE DEFECT, MEASURED ON PRODUCTION 2026-10-07 (588 Thomas, this handler) ──

    page  dates  recs        bytes     ms
       1     10     63     6452999   1546
       2     10     83     4043877    788
       3     10     71     2028208    536
       4     10     57     1598155    463
       5      3     15      240401    121
     TOT     43    289    14363640   3454

14,363,640 bytes to draw a list. 14,122,753 of them — 98.3% — were `data`,
overwhelmingly the kiosk worker-signature images on pre-shift sheets. THE
SERVER WAS NOT SLOW: 3.4 s of handler time for all five pages. The ten minutes
was TRANSFER.

And the list renders none of it. The screen draws its dates off `identityRow`
(frontend/src/utils/siteLogbookHistory.js) — `{date, id, cache_version,
logs:[{id, log_type, status, updated_at}]}` — which for all 43 dates and 289
records is 44,016 bytes. 0.306%. The tablet was moving 326x the bytes its list
needs.

── WHAT THIS FILE GUARDS, AND WHY EACH ONE IS HERE ───────────────────────────

  A. THE OLD READ IS BYTE-FOR-BYTE THE OLD READ. An installed tablet that has
     not taken the OTA still calls this endpoint with no parameters, or with
     `before`/`limit`, and must still receive WHOLE DOCUMENTS through the same
     exclusion projection. There is no update path from a gate; breaking this
     strands an inspector behind a tablet nobody can fix on site.

  B. THE INDEX CARRIES EXACTLY WHAT `identityRow` KEEPS. Derived from that
     function's own SOURCE, not from a list retyped here — a hand-kept copy of
     a nine-line function is a copy that drifts, and the direction it drifts in
     is a field the list needs arriving absent.

  C. THE TWO MODES LIST THE SAME RECORDS. The amendment collapse runs in both,
     so an amended day shows one card either way. If it did not, which records
     an inspector saw would depend on whether his tablet had taken an OTA.
     THIS TEST CAN FAIL: the last case in section C drops one field from the
     projection and asserts the parity check NOTICES.

  D. A `date` READ IS ONE DAY AND NEVER CLAIMS TO BE THE HISTORY. `complete`
     authorises the client to REPLACE its stored list, and
     `siteLogbookHistory`'s rule is that a complete walk may then prune — so a
     one-day body that said `complete: true` would let a tablet replace 43
     dates with 1 and let sweepDocCache delete the rest of the PDFs.

  E. AN UNKNOWN `view` IS A 400. A client that misspells it would otherwise ask
     for 44 KB and be handed 14 MB with nothing anywhere saying why.

Run:  python -m pytest tests/test_the_list_costs_the_index.py -q
"""

from __future__ import annotations

import base64 as _b64
import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

_HISTORY_JS = _REPO / "frontend" / "src" / "utils" / "siteLogbookHistory.js"


# ── the fixture: the shape the measurement describes ─────────────────────────

WORKER_SIG = "data:image/png;base64," + _b64.b64encode(b"W" * 4608).decode("ascii")
THUMB_B64 = _b64.b64encode(b"T" * (32 * 1024)).decode("ascii")
FULL_B64 = "A" * (((150 * 1024 + 2) // 3) * 4)


def _cp_signature(seed: int) -> dict:
    return {
        "paths": [[{"x": (seed + i) % 300 + 0.5, "y": i % 120 + 0.25}
                   for i in range(400)] for _ in range(3)],
        "signerName": "Casey CP",
        "affirmed": True,
    }


def _date(i: int) -> str:
    return f"2026-09-{28 - (i % 28):02d}"


def _preshift(i: int) -> dict:
    """Twelve men on the sheet, eight of whom signed at the kiosk. This is the
    record that makes the list 14 MB."""
    workers = []
    for w in range(12):
        row = {"name": f"Worker {i}-{w}", "company": "Sub A",
               "osha_number": f"SST-{i:03d}{w:02d}"}
        if w < 8:
            row["worker_signature"] = WORKER_SIG
        workers.append(row)
    return {
        "_id": f"lb_ps_{i}",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "preshift_signin", "date": _date(i),
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": _cp_signature(i + 500),
        "created_at": f"{_date(i)}T07:00:00+00:00",
        "updated_at": f"{_date(i)}T07:05:00+00:00",
        "data": {"company": "Sub A", "total_count": 12, "workers": workers},
    }


def _daily(i: int) -> dict:
    return {
        "_id": f"lb_dj_{i}",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "daily_jobsite", "date": _date(i),
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": _cp_signature(i),
        "created_at": f"{_date(i)}T13:00:00+00:00",
        "updated_at": f"{_date(i)}T15:31:00+00:00",
        "data": {
            "weather": "Sunny",
            "activities": [{
                "activity_id": f"act_{i}", "company": "Sub A",
                "photos": [{"base64": FULL_B64, "thumb_base64": THUMB_B64}],
            }],
        },
    }


# A log with NO `updated_at`: the one that proves the index resolves the stamp
# the way the client would rather than shipping whatever field it found.
def _no_updated_at() -> dict:
    return {
        "_id": "lb_submitted_only",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "hot_work", "date": "2026-08-01",
        "status": "submitted", "is_deleted": False,
        "created_at": "2026-08-01T06:00:00+00:00",
        "submitted_at": "2026-08-01T09:30:00+00:00",
        "data": {"work_type": "welding"},
    }


# An undated log: the "unknown" bucket.
def _undated() -> dict:
    return {
        "_id": "lb_undated",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "hot_work", "date": None,
        "status": "submitted", "is_deleted": False,
        "created_at": "2026-07-01T06:00:00+00:00",
        "data": {"work_type": "cutting"},
    }


# ── AN AMENDMENT CHAIN, WHICH IS WHAT MAKES SECTION C MEAN ANYTHING ─────────
#
# Parent filed, child filed later and amending it, grandchild WITHDRAWN. The
# collapse must return ONE row — the child — in both modes. Reaching that
# answer needs `parent_logbook_id` (to group), `status`/`is_locked` (to know
# which links are filed), `created_at` (to break the tie) and `is_amendment`
# (for the sentence). Every one of them is in SUBMITTED_LOGBOOK_INDEX_FIELDS
# because of this fixture.
#
# THE WITHDRAWN ROW NEVER REACHES THE COLLAPSE, AND IT IS HERE TO PROVE THAT.
# The endpoint's own query is `status: "submitted"`, so a withdrawn amendment
# is filtered in Mongo before any of this runs — in BOTH modes. Asserted below
# rather than assumed, because "the collapse drops it" and "the query never
# fetched it" are two different facts and only one of them is true.
AMEND_DATE = "2026-06-15"


def _chain() -> list:
    # `created_at` IS A DATETIME HERE, NOT AN ISO STRING, and that is the
    # fixture being faithful rather than being fussy. `_filed_log._order`
    # tie-breaks on `created_at` only `if isinstance(created, datetime)` and
    # falls back to `datetime.min` otherwise — so a string-dated fixture makes
    # every candidate tie and the head is then decided by `str(_id)`, which
    # picks the ORIGINAL over its correction. Mongo stores these as BSON dates;
    # a fixture that did not would be testing a tie-break production never hits.
    from datetime import datetime, timezone as _tz

    def _at(hour: int):
        return datetime(2026, 6, 15, hour, 0, 0, tzinfo=_tz.utc)

    base = {
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "daily_jobsite", "date": AMEND_DATE,
        "is_deleted": False, "cp_name": "Casey CP",
    }
    return [
        {**base, "_id": "lb_parent", "status": "submitted",
         "created_at": _at(8),
         "updated_at": f"{AMEND_DATE}T08:00:00+00:00",
         "data": {"general_description": "the original"}},
        {**base, "_id": "lb_child", "status": "submitted",
         "is_amendment": True, "parent_logbook_id": "lb_parent",
         "amendment_reason": "wrong crew count",
         "created_by_name": "Avery Admin",
         "created_at": _at(18),
         "updated_at": f"{AMEND_DATE}T18:00:00+00:00",
         "data": {"general_description": "the correction"}},
        {**base, "_id": "lb_withdrawn", "status": server.WITHDRAWN_STATUS,
         "is_amendment": True, "parent_logbook_id": "lb_child",
         "amendment_reason": "filed in error",
         "created_by_name": "Avery Admin",
         "created_at": _at(19),
         "updated_at": f"{AMEND_DATE}T19:00:00+00:00",
         "data": {"general_description": "taken back"}},
    ]


def _docs(n: int = 6) -> list:
    out = []
    for i in range(n):
        out.append(_daily(i))
        out.append(_preshift(i))
    out.append(_no_updated_at())
    out.append(_undated())
    out.extend(_chain())
    return out


# ── a Mongo faithful enough for a projection to mean something ───────────────

def _matches(doc: dict, query: dict) -> bool:
    for key, cond in (query or {}).items():
        val = doc.get(key, None)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$lt" in cond and not (val is not None and val < cond["$lt"]):
                return False
        elif val != cond:
            return False
    return True


def _strip(node, parts):
    if isinstance(node, list):
        for el in node:
            _strip(el, parts)
        return
    if not isinstance(node, dict):
        return
    head, rest = parts[0], parts[1:]
    if not rest:
        node.pop(head, None)
        return
    if head in node:
        _strip(node[head], rest)


def _project(doc: dict, projection) -> dict:
    """BOTH KINDS, AND A MIXED ONE IS A DRIVER ERROR.

    Mongo rejects a projection that mixes inclusion and exclusion (except for
    `_id`), so a fake that quietly accepted one would clear a handler the real
    driver refuses.
    """
    if not projection:
        return copy.deepcopy(doc)
    values = {bool(v) for k, v in projection.items() if k != "_id"}
    if len(values) > 1:
        raise AssertionError(f"mixed inclusion/exclusion projection: {projection}")
    if values == {True}:
        out = {}
        for key, keep in projection.items():
            if keep and key in doc:
                out[key] = copy.deepcopy(doc[key])
        if projection.get("_id", 1) and "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    out = copy.deepcopy(doc)
    for path, keep in projection.items():
        if keep:
            continue
        _strip(out, path.split("."))
    return out


class _Cursor:
    def __init__(self, items):
        self._items = items

    def sort(self, spec, direction=None):
        keys = [(spec, direction if direction is not None else 1)] \
            if isinstance(spec, str) else list(spec)
        for field, direction in reversed(keys):
            self._items.sort(
                key=lambda d, f=field: (d.get(f) is None, d.get(f) or ""),
                reverse=(direction == -1),
            )
        return self

    def skip(self, n):
        self._items = self._items[n:]
        return self

    def limit(self, n):
        self._items = self._items[:n]
        return self

    async def to_list(self, n=None):
        return self._items if n is None else self._items[:n]

    def __aiter__(self):
        async def gen():
            for item in self._items:
                yield item
        return gen()


class _Logbooks:
    def __init__(self, docs):
        self.docs = docs
        self.find_calls = []
        self.distinct_calls = []

    def find(self, query=None, projection=None, *a, **k):
        self.find_calls.append((copy.deepcopy(query), copy.deepcopy(projection)))
        hits = [d for d in self.docs if _matches(d, query or {})]
        return _Cursor([_project(d, projection) for d in hits])

    async def distinct(self, field, query=None, *a, **k):
        self.distinct_calls.append((field, copy.deepcopy(query)))
        vals, seen = [], set()
        for d in self.docs:
            if not _matches(d, query or {}):
                continue
            v = d.get(field, None)
            marker = (type(v).__name__, v)
            if marker in seen:
                continue
            seen.add(marker)
            vals.append(v)
        return vals

    async def count_documents(self, query=None, *a, **k):
        return sum(1 for d in self.docs if _matches(d, query or {}))


class _FakeCollection:
    def __init__(self, one=None):
        self.one = one

    async def find_one(self, query=None, *a, **k):
        return self.one

    def find(self, *a, **k):
        return _Cursor([])

    async def count_documents(self, *a, **k):
        return 0


PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_test",
           "is_deleted": False}


class _FakeDb:
    def __init__(self, logbooks):
        self._c = {"logbooks": logbooks, "projects": _FakeCollection(one=PROJECT)}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


SITE_USER = {
    "_id": "site_1", "id": "site_1", "role": "cp",
    "company_id": "co_test", "account_status": "approved",
    "full_name": "Site Tablet", "assigned_projects": ["proj1"],
}

BASE = "/api/logbooks/project/proj1/submitted"


def _get(docs, query=""):
    logbooks = _Logbooks(docs)
    db = _FakeDb(logbooks)

    async def _fake_user():
        return SITE_USER

    async def _fake_project():
        return PROJECT

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_project_access] = _fake_project
    try:
        with patch.object(server, "db", db):
            r = TestClient(server.app).get(BASE + query)
    finally:
        ov.clear()
    return r, logbooks


def _all_logs(body):
    return [log for logs in (body.get("dates") or {}).values() for log in logs]


def _wire(body) -> int:
    """The body as the client receives it."""
    return len(json.dumps(body, separators=(",", ":"), default=str).encode())


def _ids_by_date(body):
    return {d: sorted(str(l.get("id") or "") for l in logs)
            for d, logs in (body.get("dates") or {}).items()}


# ── B's instrument: identityRow's OWN field list, out of its source ──────────

def _strip_js_comments(src: str) -> str:
    """Comment prose is not code. This repo has had source-text assertions pass
    on a comment that MENTIONED the thing they were looking for, so the prose
    goes before anything is read out of the text."""
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "/*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if two == "//":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        ch = src[i]
        if ch in "'\"`":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == ch:
                    break
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def identity_row_log_fields() -> set:
    """The keys `identityRow` keeps on each LOG, read out of the function.

    NOT A LIST RETYPED HERE. A hand-kept copy of the consumer drifts, and the
    direction it drifts in is a field the list needs arriving absent — which on
    this screen is a compliance record that renders blank to an inspector.
    """
    src = _strip_js_comments(_HISTORY_JS.read_text(encoding="utf-8"))
    m = re.search(r"export function identityRow\s*\([^)]*\)\s*\{", src)
    assert m, "identityRow() is no longer in siteLogbookHistory.js"
    body = src[m.end():]
    m2 = re.search(r"logs:\s*list\.map\(\s*\([^)]*\)\s*=>\s*\(\{(.*?)\}\)\)",
                   body, re.S)
    assert m2, "identityRow no longer maps its logs through an object literal"
    fields = set(re.findall(r"(\w+)\s*:", m2.group(1)))
    assert fields, "no per-log fields found in identityRow"
    return fields


# ═════════════════════════════════════════════════════════════════════════════
# A. THE OLD READ IS THE OLD READ
# ═════════════════════════════════════════════════════════════════════════════

class BackwardCompatibilityTest(unittest.TestCase):
    """An installed tablet cannot be upgraded from a gate. Whatever else this
    endpoint learns to serve, the request it already sends must not change."""

    @classmethod
    def setUpClass(cls):
        cls.response, cls.logbooks = _get(_docs())
        cls.body = cls.response.json()
        cls.logs = _all_logs(cls.body)

    def test_the_parameter_free_read_still_serves_whole_documents(self):
        self.assertEqual(self.response.status_code, 200, self.response.text[:400])
        self.assertTrue(self.logs)
        with_data = [l for l in self.logs if isinstance(l.get("data"), dict)]
        self.assertEqual(
            len(with_data), len(self.logs),
            "a log came back without its `data` on the DEFAULT read — an "
            "installed tablet renders the document from it",
        )

    def test_the_inline_bytes_an_inspector_reads_offline_are_still_there(self):
        """The retained thumbnail and the kiosk worker signatures. Dropping the
        signatures would not blank a picture: renderPreshiftSignin keys
        'Not Signed:' off their ABSENCE."""
        sheets = [l for l in self.logs if l.get("log_type") == "preshift_signin"]
        self.assertTrue(sheets)
        for sheet in sheets:
            workers = (sheet.get("data") or {}).get("workers") or []
            self.assertEqual(len([w for w in workers if w.get("worker_signature")]), 8)
        photos = [p for l in self.logs
                  for a in (l.get("data") or {}).get("activities") or []
                  for p in a.get("photos") or []]
        self.assertTrue(photos)
        self.assertTrue(all(p.get("thumb_base64") == THUMB_B64 for p in photos))
        self.assertEqual([p for p in photos if p.get("base64")], [])

    def test_the_default_read_still_uses_the_exclusion_projection(self):
        projections = [p for _, p in self.logbooks.find_calls if p]
        self.assertTrue(projections, "find() was called with no projection at all")
        for proj in projections:
            self.assertTrue(
                all(v == 0 for v in proj.values()),
                f"the default read is no longer an exclusion projection: {proj}",
            )

    def test_the_keys_an_installed_client_reads_are_all_still_present(self):
        for key in ("dates", "complete", "next_before", "date_count", "log_count"):
            self.assertIn(key, self.body, f"{key} left the body")
        self.assertIs(self.body["complete"], True)
        self.assertIsNone(self.body["next_before"])

    def test_the_default_body_gains_no_key_at_all(self):
        """NOT EVEN `view: null`.

        It was `"view": view` on every response for one commit, and
        test_one_record_with_its_history.py's
        `test_the_payload_shape_an_installed_client_reads_is_unchanged` caught
        it: that test PINS the key set of the body an installed tablet
        receives. The pin is right — it is the backward-compatibility guarantee
        itself — so the echo is present only for a caller that asked for a mode,
        which is the only caller that needs to read it.
        """
        self.assertEqual(
            sorted(self.body.keys()),
            ["complete", "date_count", "dates", "log_count", "next_before"],
            "the default body's key set changed; an installed tablet reads it",
        )

    def test_the_cursor_contract_is_untouched(self):
        r1, _ = _get(_docs(), "?limit=3")
        b1 = r1.json()
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(len(b1["dates"]), 3)
        self.assertIs(b1["complete"], False)
        self.assertTrue(b1["next_before"])
        r2, _ = _get(_docs(), f"?limit=3&before={b1['next_before']}")
        b2 = r2.json()
        self.assertTrue(set(b2["dates"]).isdisjoint(set(b1["dates"])))
        self.assertTrue(all(isinstance(l.get("data"), dict) for l in _all_logs(b2)))

    def test_the_coroutine_called_directly_is_still_the_full_history(self):
        """test_the_cache_key_carries_the_renderer.py and the sort analyser both
        invoke this coroutine with `before=None, limit=30` and nothing else, so
        `view` and `date` arrive as the Query() DEFAULT OBJECT. Truthy. If they
        were read as given, that call would 400 or collapse to one date."""
        import asyncio

        logbooks = _Logbooks(_docs())
        with patch.object(server, "db", _FakeDb(logbooks)):
            out = asyncio.run(server.get_submitted_logbooks(
                project_id="proj1", before=None, limit=30))
        self.assertIs(out["complete"], True)
        self.assertGreater(len(out["dates"]), 1)
        self.assertTrue(all(isinstance(l.get("data"), dict)
                            for l in _all_logs(out)))


# ═════════════════════════════════════════════════════════════════════════════
# B. THE INDEX CARRIES EXACTLY WHAT THE LIST DRAWS FROM
# ═════════════════════════════════════════════════════════════════════════════

class IndexViewTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.response, cls.logbooks = _get(_docs(), "?view=index")
        cls.body = cls.response.json()
        cls.logs = _all_logs(cls.body)
        cls.full = _get(_docs())[0].json()

    def test_the_index_came_back_and_says_it_is_the_index(self):
        self.assertEqual(self.response.status_code, 200, self.response.text[:400])
        self.assertEqual(self.body.get("view"), "index")
        self.assertIs(self.body["complete"], True)
        self.assertTrue(self.logs)

    def test_no_row_carries_data_anywhere(self):
        self.assertEqual(
            [l.get("id") for l in self.logs if "data" in l], [],
            "an index row shipped `data` — 98.3% of the old body was `data`",
        )

    def test_a_row_carries_exactly_identity_rows_own_fields(self):
        wanted = identity_row_log_fields()
        for log in self.logs:
            self.assertEqual(
                set(log.keys()), wanted,
                f"index row {log.get('id')!r} carries {sorted(log.keys())}, "
                f"identityRow keeps {sorted(wanted)}",
            )

    def test_the_projection_reaching_the_driver_is_an_inclusion(self):
        """Named in the query, not filtered in Python: the point is that the
        bytes never leave Mongo."""
        projections = [p for _, p in self.logbooks.find_calls if p]
        self.assertTrue(projections, "find() was called with no projection")
        for proj in projections:
            self.assertTrue(all(v == 1 for v in proj.values()),
                            f"not an inclusion projection: {proj}")
            self.assertNotIn("data", proj)

    def test_the_index_is_a_rounding_error_next_to_the_documents(self):
        """Production says 0.306% on 43 dates. This fixture is smaller, so the
        bar is the shape of the finding rather than its exact value: the list
        must not be in the same ORDER OF MAGNITUDE as the corpus."""
        index_bytes = _wire(self.body)
        full_bytes = _wire(self.full)
        ratio = index_bytes / full_bytes
        self.assertLess(
            ratio, 0.02,
            f"the index is {ratio:.3%} of the full body "
            f"({index_bytes} vs {full_bytes}) — it was 0.306% in production",
        )

    def test_updated_at_is_the_stamp_the_client_would_have_resolved(self):
        """THE FILE NAME DEPENDS ON IT. The client's `pdfVersion` resolves
        `updated_at || submitted_at || created_at` and that string becomes the
        day's `cache_version`, which is the NAME of the full-day PDF on disk. A
        different string here names a second file and lets sweepDocCache delete
        the first."""
        full_by_id = {str(l.get("id")): l for l in _all_logs(self.full)}
        checked = 0
        for log in self.logs:
            doc = full_by_id.get(str(log.get("id")))
            self.assertIsNotNone(doc, f"index listed {log.get('id')} and the "
                                      f"full body did not")
            expected = (doc.get("updated_at") or doc.get("submitted_at")
                        or doc.get("created_at"))
            self.assertEqual(log.get("updated_at"), expected,
                             f"{log.get('id')} would be cached under a "
                             f"different name in index mode")
            checked += 1
        self.assertGreater(checked, 1)

    def test_the_log_with_no_updated_at_is_the_case_that_proves_it(self):
        """A fixture that only ever carried `updated_at` could not tell the
        resolved stamp from the raw field."""
        rows = [l for l in self.logs if l.get("id") == "lb_submitted_only"]
        self.assertEqual(len(rows), 1, "the submitted_at-only fixture vanished")
        self.assertEqual(rows[0]["updated_at"], "2026-08-01T09:30:00+00:00")

    def test_the_undated_log_still_lands_in_the_unknown_bucket(self):
        self.assertIn("unknown", self.body["dates"])
        self.assertEqual([l["id"] for l in self.body["dates"]["unknown"]],
                         ["lb_undated"])

    def test_the_index_still_pages_on_a_date_boundary(self):
        r, _ = _get(_docs(), "?view=index&limit=2")
        b = r.json()
        self.assertEqual(len(b["dates"]), 2)
        self.assertIs(b["complete"], False)
        self.assertTrue(b["next_before"])
        self.assertEqual(b.get("view"), "index")


# ═════════════════════════════════════════════════════════════════════════════
# C. THE TWO MODES LIST THE SAME RECORDS
# ═════════════════════════════════════════════════════════════════════════════

class CollapseParityTest(unittest.TestCase):
    """An amendment chain must collapse to one row in BOTH modes. If it did
    not, which records an inspector saw would depend on whether his tablet had
    taken an OTA."""

    def test_the_chain_collapses_to_one_row_in_both_modes(self):
        full = _get(_docs())[0].json()
        index = _get(_docs(), "?view=index")[0].json()
        self.assertEqual(
            [l["id"] for l in full["dates"][AMEND_DATE]], ["lb_child"],
            "the full body no longer collapses the chain — fixture or "
            "collapse changed",
        )
        self.assertEqual([l["id"] for l in index["dates"][AMEND_DATE]],
                         ["lb_child"])

    def test_the_withdrawn_amendment_is_filtered_by_the_query_in_both_modes(self):
        """Not by the collapse. `status: "submitted"` is in the query, so the
        withdrawn child never leaves Mongo — which is why no index field is
        needed for it and why the parity test above lists two ids, not three."""
        for query in ("", "?view=index", f"?date={AMEND_DATE}"):
            body = _get(_docs(), query)[0].json()
            ids = [l["id"] for logs in body["dates"].values() for l in logs]
            self.assertNotIn("lb_withdrawn", ids, f"leaked on {query!r}")

    def test_every_date_lists_the_same_record_ids_in_both_modes(self):
        full = _get(_docs())[0].json()
        index = _get(_docs(), "?view=index")[0].json()
        self.assertEqual(_ids_by_date(index), _ids_by_date(full))
        self.assertEqual(index["log_count"], full["log_count"])
        self.assertEqual(index["date_count"], full["date_count"])

    def test_the_amendment_apparatus_stays_off_the_list(self):
        """`_chain_length`, `_superseded_ids`, `amendment_sentence` and
        `_competing_records` are rendered from the EXPANDED day, which is a
        `date` read of whole documents. None of it is on a list of dates."""
        full = _get(_docs())[0].json()
        head = next(l for l in full["dates"][AMEND_DATE] if l["id"] == "lb_child")
        self.assertIn("amendment_sentence", head,
                      "the full body lost its amendment sentence")
        index = _get(_docs(), "?view=index")[0].json()
        row = index["dates"][AMEND_DATE][0]
        for key in ("_chain_length", "_superseded_ids", "amendment_sentence",
                    "_competing_records"):
            self.assertNotIn(key, row)

    def test_the_parity_check_can_actually_fail(self):
        """ASK WHAT READING WOULD PROVE THE INSTRUMENT BROKEN.

        `parent_logbook_id` is in the index projection because the collapse
        groups on it. Drop it and the chain's three documents become three
        groups: the index lists rows the full body does not, and the test above
        must NOTICE. A parity assertion that passes with the projection gutted
        is not measuring parity.
        """
        gutted = {k: v for k, v in server.SUBMITTED_LOGBOOK_INDEX_FIELDS.items()
                  if k != "parent_logbook_id"}
        with patch.object(server, "SUBMITTED_LOGBOOK_INDEX_FIELDS", gutted):
            index = _get(_docs(), "?view=index")[0].json()
        full = _get(_docs())[0].json()
        self.assertNotEqual(
            _ids_by_date(index), _ids_by_date(full),
            "the row sets agreed with `parent_logbook_id` REMOVED from the "
            "projection — the parity test is not reading the collapse",
        )
        self.assertEqual(
            sorted(l["id"] for l in index["dates"][AMEND_DATE]),
            ["lb_child", "lb_parent"],
            "without the parent link the chain's two SUBMITTED documents "
            "become two records, and an inspector is shown an original and "
            "its correction as two filed logs with nothing saying which is "
            "the record",
        )


# ═════════════════════════════════════════════════════════════════════════════
# D. ONE DAY ON DEMAND
# ═════════════════════════════════════════════════════════════════════════════

class DayDetailReadTest(unittest.TestCase):

    def test_a_date_read_is_that_date_and_nothing_else(self):
        r, _ = _get(_docs(), f"?date={_date(0)}")
        b = r.json()
        self.assertEqual(r.status_code, 200, r.text[:400])
        self.assertEqual(list(b["dates"]), [_date(0)])
        self.assertEqual(b["date_count"], 1)
        self.assertEqual(
            sorted(l["id"] for l in b["dates"][_date(0)]),
            ["lb_dj_0", "lb_ps_0"],
        )

    def test_it_serves_whole_documents_because_that_is_what_a_day_is(self):
        r, _ = _get(_docs(), f"?date={_date(0)}")
        logs = _all_logs(r.json())
        self.assertTrue(logs)
        self.assertTrue(all(isinstance(l.get("data"), dict) for l in logs))
        sheet = next(l for l in logs if l["log_type"] == "preshift_signin")
        workers = (sheet["data"] or {}).get("workers") or []
        self.assertEqual(len([w for w in workers if w.get("worker_signature")]), 8)

    def test_it_never_claims_to_be_the_whole_history(self):
        """`complete: true` authorises the client to REPLACE its stored list,
        and a complete walk may then prune. One date saying so would let a
        tablet replace 43 dates with 1 and delete the rest of the PDFs."""
        r, _ = _get(_docs(), f"?date={_date(0)}")
        b = r.json()
        self.assertIs(b["complete"], False)
        self.assertIsNone(b["next_before"])

    def test_it_does_not_walk_the_date_index_to_answer(self):
        """A `distinct` over the project's whole filed history to answer one
        day would put the scan back on the path this change shortens."""
        _, logbooks = _get(_docs(), f"?date={_date(0)}")
        self.assertEqual(
            logbooks.distinct_calls, [],
            "a day-detail read ran distinct() over the whole history",
        )
        _, full_books = _get(_docs())
        self.assertEqual(len(full_books.distinct_calls), 1,
                         "the paging read stopped using the date index")

    def test_the_unknown_bucket_is_readable_as_a_day(self):
        """`unknown` is not a date — it is the bucket for a log with none — so
        the read for it has to ask for null/missing/blank rather than for the
        literal string."""
        r, _ = _get(_docs(), "?date=unknown")
        b = r.json()
        self.assertEqual(list(b["dates"]), ["unknown"])
        self.assertEqual([l["id"] for l in b["dates"]["unknown"]], ["lb_undated"])

    def test_a_date_nobody_filed_on_is_an_empty_bucket_not_a_500(self):
        r, _ = _get(_docs(), "?date=1999-01-01")
        b = r.json()
        self.assertEqual(r.status_code, 200, r.text[:400])
        self.assertEqual(b["dates"], {"1999-01-01": []})
        self.assertEqual(b["log_count"], 0)

    def test_a_date_read_costs_one_day_not_the_corpus(self):
        day = _wire(_get(_docs(), f"?date={_date(0)}")[0].json())
        whole = _wire(_get(_docs())[0].json())
        self.assertLess(day * 2, whole,
                        f"one day ({day} B) is not materially smaller than the "
                        f"whole history ({whole} B)")


# ═════════════════════════════════════════════════════════════════════════════
# E. AN UNKNOWN VIEW IS A 400
# ═════════════════════════════════════════════════════════════════════════════

class ViewValidationTest(unittest.TestCase):

    def test_an_unknown_view_is_refused_rather_than_served_as_14_mb(self):
        r, _ = _get(_docs(), "?view=summary")
        self.assertEqual(r.status_code, 400, r.text[:300])
        self.assertIn("summary", r.text)

    def test_the_only_view_is_the_one_the_client_asks_for(self):
        self.assertEqual(server.SUBMITTED_LOGBOOK_VIEWS, {"index"})
        src = _strip_js_comments(_HISTORY_JS.read_text(encoding="utf-8"))
        self.assertIn("view=index", src,
                      "the client no longer asks for the view this serves")
        self.assertIn("body.view !== 'index'", src,
                      "the client no longer checks that the server honoured "
                      "it — see INDEX_PROBE_DATES: an old server ignores an "
                      "unknown query param and serves whole documents")


if __name__ == "__main__":
    unittest.main(verbosity=2)
