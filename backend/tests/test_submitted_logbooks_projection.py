"""GET /logbooks/project/{id}/submitted — THE GATE TABLET'S ONLY LOGBOOK READ.

frontend/app/site/logbooks.jsx is the single caller of this endpoint
(`logbooksAPI.getSubmitted`, src/utils/api.js:1011) and the only way an
inspector standing on the site reaches a filed compliance record. Everything
asserted here is derived from what THAT screen reads off a returned log, not
from what the document happens to contain.

── WHAT THE SCREEN DRAWS, AND WHAT IT CANNOT ────────────────────────────────

`SignatureBlock` (logbooks.jsx:430) is the whole argument:

    base64Data = signature.data || signature.paths || null;
    ...
    {base64Data && typeof base64Data === 'string' ? <Image .../> : ...}

`cp_signature.paths` is an ARRAY of stroke point arrays — SignaturePad.js
:247 writes `paths: pathsRef.current`, one {x, y} appended per PanResponder
move with no simplification. `typeof array !== 'string'`, so the image branch
is unreachable for it: the strokes cross the wire and draw NOTHING. They are
the largest thing on the document after the photos and the only one the screen
provably cannot render.

Worker signatures are the opposite case and are asserted here as a GUARD.
`renderPreshiftSignin` and `renderToolboxTalk` draw `worker_signature` into an
<Image> (logbooks.jsx:717, 749) — those are PNG data URLs from the kiosk
(checkin.html:2096, `canvas.toDataURL('image/png')`), they are strings, and
they render. Worse, removing them would not merely blank a picture: the same
renderer keys "Not Signed:" off `!w.worker_signature`, so a projection that
dropped them would tell a DOB inspector that every worker on the sheet was
unsigned. A record that lies is worse than a record that is large.

Photo `base64` is the full-size original, drawn into an 80x60 view
(styles.activityPhoto, logbooks.jsx:1843). `logbookPhotoUri` prefers it, then
`thumb_base64`, then the served-thumb URL — and the retained ~400px copy is the
one the purge is forbidden to remove. The full-size copy is served by
get_logbook_activity_photo, an endpoint of its own; it is not list content.
Same call, same reasons, as WORKER_LIST_FIELDS (server.py:14138).

── WHY THE SIZE MATTERS AT ALL ──────────────────────────────────────────────

The screen is cache-first: `writeListThrough` stores the whole list under one
AsyncStorage key so a dead zone still shows records. Android AsyncStorage is a
SQLite database with `PRAGMA max_page_count` from a 6MB default
(ReactDatabaseSupplier) and the project is CNG/prebuild with no android/
directory overriding it. A write over that ceiling is REJECTED, and a rejected
write means the offline screen has nothing at all — not a missing photo, an
empty screen, to the one person who is there to read the record.

── WHAT A TRUNCATED RESPONSE DOES TO A CLIENT ───────────────────────────────

`datesToList` declares each day's full-day-report PDF to the cache, and
`sweepDocCache` (src/utils/docCache.js:261) deletes every cached PDF that no
stored list names. So a response that silently drops dates makes the next
sweep DELETE the offline PDFs for those dates. That is why the parameter-free
response must be the COMPLETE set, and why a partial page has to say so.
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
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ── the numbers, and where each one comes from ───────────────────────────────

# frontend/app/site/logbooks.jsx CACHE_DATE_LIMIT. The client stores this many
# dates under one key, so this window — not the whole history — is the unit
# that has to fit the device.
CACHE_DATE_LIMIT = 60

# ReactDatabaseSupplier's default maximum size for the AsyncStorage SQLite
# database, DATABASE-WIDE. Nothing in this project overrides it: it is CNG /
# prebuild and carries no android/ directory.
ASYNC_STORAGE_CEILING = 6 * 1024 * 1024

# compressPhoto.js caps an upload at 150KB of JPEG; base64 inflates by 4/3.
# The same constant test_activity_identity_photo_budget.py measures the
# document against.
FULL_B64 = "A" * (((150 * 1024 + 2) // 3) * 4)

# The retained ~400px copy, 25-40KB (server.py _enhance_bytes_to_r2_sync).
# 32KB is the middle of that documented range, as in the sibling test.
THUMB_B64 = _b64.b64encode(b"T" * (32 * 1024)).decode("ascii")

# One kiosk signature: a 2x-scaled canvas of a single black stroke, PNG.
# ~4.5KB of PNG -> ~6KB of base64 inside a data: URL.
WORKER_SIG = "data:image/png;base64," + _b64.b64encode(b"W" * 4608).decode("ascii")

# A drawn CP signature: three strokes, 400 PanResponder samples each. Nothing
# simplifies the polyline, so this is what a two-second signature really is.
CP_STROKES, CP_POINTS = 3, 400


def _cp_signature(seed: int) -> dict:
    return {
        "paths": [
            [{"x": (seed + i + s) % 300 + 0.5, "y": (i * 7 + s) % 120 + 0.25}
             for i in range(CP_POINTS)]
            for s in range(CP_STROKES)
        ],
        "signerName": "Casey CP",
        "timestamp": "2026-04-01T15:31:00.000Z",
        "affirmed": True,
        "affirmedAt": "2026-04-01T15:31:00.000Z",
        "affirmedLang": "en",
    }


def _date(i: int) -> str:
    """60 consecutive filing dates, newest first at i = 0."""
    day = 28 - (i % 28)
    month = 4 - (i // 28)
    return f"2026-{month:02d}-{day:02d}"


def _daily_jobsite(i: int) -> dict:
    """One activity row carrying one photo — 60 photos over the window."""
    return {
        "_id": f"lb_dj_{i}",
        "project_id": "proj1",
        "company_id": "co_test",
        "log_type": "daily_jobsite",
        "date": _date(i),
        "status": "submitted",
        "is_deleted": False,
        "cp_name": "Casey CP",
        "cp_signature": _cp_signature(i),
        "created_at": f"2026-04-0{(i % 9) + 1}T13:00:00+00:00",
        "updated_at": f"2026-04-0{(i % 9) + 1}T15:31:00+00:00",
        "data": {
            "project_address": "1 Test Plaza, Brooklyn NY",
            "weather": "Sunny",
            "general_description": "Shoring and slab prep.",
            "activities": [{
                "activity_id": f"act_{i}",
                "crew_id": "C1",
                "company": "Sub A",
                "num_workers": "6",
                "work_description": "shoring",
                "work_locations": "cellar",
                "photos": [{
                    "base64": FULL_B64,
                    "thumb_base64": THUMB_B64,
                    "enhance_status": "done",
                    "enhanced_r2_key": f"logbook-photos/proj1/lb_dj_{i}/0-0-enhanced.jpg",
                    "thumb_r2_key": f"logbook-photos/proj1/lb_dj_{i}/0-0-thumb.jpg",
                    "uri": f"file:///data/user/0/logbook_photos/{i}_0.jpg",
                }],
            }],
            "equipment_on_site": {"hoist": True},
            "checklist_items": {"fire_safety": True},
            "observations": [],
            "time_in": "07:00", "time_out": "15:30",
        },
    }


def _preshift(i: int) -> dict:
    """Twelve men on the sheet, eight of whom signed at the kiosk."""
    workers = []
    for w in range(12):
        row = {
            "name": f"Worker {i}-{w}",
            "company": "Sub A",
            "osha_number": f"SST-{i:03d}{w:02d}",
            "had_injury": "No",
            "inspected_ppe": "Yes",
        }
        if w < 8:
            row["worker_signature"] = WORKER_SIG
        workers.append(row)
    return {
        "_id": f"lb_ps_{i}",
        "project_id": "proj1",
        "company_id": "co_test",
        "log_type": "preshift_signin",
        "date": _date(i),
        "status": "submitted",
        "is_deleted": False,
        "cp_name": "Casey CP",
        "cp_signature": _cp_signature(i + 500),
        "created_at": f"2026-04-0{(i % 9) + 1}T07:00:00+00:00",
        "updated_at": f"2026-04-0{(i % 9) + 1}T07:05:00+00:00",
        "data": {
            "company": "Sub A",
            "project_location": "Cellar",
            "total_count": 12,
            "workers": workers,
        },
    }


def _window_docs() -> list:
    """The 60-date window: one daily jobsite log and one pre-shift sheet a day.

    120 submitted logs, 60 activity photos, 120 drawn CP signatures and 480
    kiosk worker signatures — the shape the measurement in the brief describes.
    """
    docs = []
    for i in range(CACHE_DATE_LIMIT):
        docs.append(_daily_jobsite(i))
        docs.append(_preshift(i))
    return docs


def _thin_docs(n: int, first_day: int = 1) -> list:
    """`n` featherweight submitted logs, one per date. For the cap tests."""
    out = []
    for i in range(n):
        d = f"{2020 + (i // 300):04d}-{((i // 28) % 12) + 1:02d}-{(i % 28) + 1:02d}"
        out.append({
            "_id": f"lb_thin_{i}",
            "project_id": "proj1",
            "company_id": "co_test",
            "log_type": "hot_work",
            "date": d,
            "status": "submitted",
            "is_deleted": False,
            "cp_name": "Casey CP",
            "created_at": f"{d}T09:00:00+00:00",
            "data": {"work_type": "welding", "location": f"Floor {i}"},
        })
    # Distinct dates only — the cap is about how much history is REACHABLE.
    seen, uniq = set(), []
    for doc in out:
        if doc["date"] in seen:
            continue
        seen.add(doc["date"])
        uniq.append(doc)
    return uniq[:n]


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
    """Apply one dotted EXCLUSION path, descending through arrays as Mongo does."""
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
    out = copy.deepcopy(doc)
    for path, keep in (projection or {}).items():
        if keep:
            raise AssertionError(
                f"inclusion key {path!r} in an exclusion projection — Mongo "
                f"rejects a mixed projection"
            )
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

    def find(self, query=None, projection=None, *a, **k):
        self.find_calls.append((copy.deepcopy(query), copy.deepcopy(projection)))
        hits = [d for d in self.docs if _matches(d, query or {})]
        return _Cursor([_project(d, projection) for d in hits])

    async def distinct(self, field, query=None, *a, **k):
        vals, seen = [], set()
        for d in self.docs:
            if not _matches(d, query or {}):
                continue
            v = d.get(field, None)
            marker = (type(v).__name__, v) if not isinstance(v, list) else ("list", id(v))
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


def _get(docs, path="/api/logbooks/project/proj1/submitted"):
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
            r = TestClient(server.app).get(path)
    finally:
        ov.clear()
    return r, logbooks


def _all_logs(body):
    return [log for logs in (body.get("dates") or {}).values() for log in logs]


# ── 1. the projection ────────────────────────────────────────────────────────

class ProjectionTest(unittest.TestCase):
    """What the screen cannot draw must not be on the wire; what it draws must."""

    @classmethod
    def setUpClass(cls):
        cls.response, cls.logbooks = _get(_window_docs())
        cls.body = cls.response.json()
        cls.logs = _all_logs(cls.body)

    def test_the_window_came_back_at_all(self):
        self.assertEqual(self.response.status_code, 200, self.response.text[:400])
        self.assertEqual(len(self.logs), CACHE_DATE_LIMIT * 2)

    def test_cp_signature_stroke_paths_are_not_served(self):
        """SignatureBlock can only draw a STRING. `paths` is an array of point
        arrays, so it renders nothing on this screen — while being the second
        largest thing on the document."""
        with_paths = [l["id"] for l in self.logs
                      if isinstance(l.get("cp_signature"), dict)
                      and "paths" in l["cp_signature"]]
        self.assertEqual(
            with_paths, [],
            f"{len(with_paths)} log(s) shipped cp_signature.paths, which this "
            f"screen provably cannot render",
        )

    def test_the_signature_itself_still_says_it_exists(self):
        """`{log.cp_name && !log.cp_signature}` — the screen distinguishes a
        signed record from an unsigned one. Dropping the whole object would
        make a signed log print as 'CP: name' with no attestation."""
        for log in self.logs:
            sig = log.get("cp_signature")
            self.assertIsInstance(sig, dict, "cp_signature must survive as an object")
            self.assertTrue(sig.get("affirmed"), "the affirmation metadata is the record")
            self.assertEqual(sig.get("signerName"), "Casey CP")

    def test_full_size_photo_base64_is_not_served(self):
        """Drawn into an 80x60 view, served in full by an endpoint of its own."""
        photos = [p for l in self.logs
                  for a in (l.get("data") or {}).get("activities") or []
                  for p in a.get("photos") or []]
        self.assertEqual(len(photos), CACHE_DATE_LIMIT, "fixture lost its photos")
        still_full = [p for p in photos if p.get("base64")]
        self.assertEqual(
            still_full, [],
            f"{len(still_full)} full-size inline photo(s) on a list response",
        )

    def test_the_retained_thumbnail_is_still_served(self):
        """logbookPhotoUri is inline-first ON PURPOSE: an inspector in a dead
        zone must still see the photo. thumb_base64 is the last inline copy and
        the purge is forbidden to remove it — so this read may not either."""
        photos = [p for l in self.logs
                  for a in (l.get("data") or {}).get("activities") or []
                  for p in a.get("photos") or []]
        self.assertTrue(photos)
        self.assertTrue(all(p.get("thumb_base64") == THUMB_B64 for p in photos))

    def test_worker_signatures_are_served_because_the_screen_draws_them(self):
        """GUARD, not an optimisation. renderPreshiftSignin draws these into an
        <Image>, and keys 'Not Signed:' off their ABSENCE — dropping them would
        report every signed worker on the sheet as unsigned to an inspector."""
        sheets = [l for l in self.logs if l.get("log_type") == "preshift_signin"]
        self.assertEqual(len(sheets), CACHE_DATE_LIMIT)
        for sheet in sheets:
            workers = (sheet.get("data") or {}).get("workers") or []
            signed = [w for w in workers if w.get("worker_signature")]
            self.assertEqual(
                len(signed), 8,
                "a worker who signed at the kiosk came back unsigned",
            )
            self.assertTrue(all(w["worker_signature"] == WORKER_SIG for w in signed))

    def test_the_projection_is_an_exclusion_and_reaches_the_driver(self):
        """Named in the query, not filtered in Python: the point is that the
        bytes never leave Mongo. Exclusion, so a field this screen starts
        reading tomorrow arrives by default instead of silently missing."""
        projections = [p for _, p in self.logbooks.find_calls if p]
        self.assertTrue(projections, "find() was called with no projection at all")
        for proj in projections:
            self.assertTrue(
                all(v == 0 for v in proj.values()),
                f"not an exclusion projection: {proj}",
            )

    def test_the_fields_the_list_row_reads_all_survive(self):
        """Everything logbooks.jsx reads off a log OUTSIDE `data`."""
        for log in self.logs:
            for field in ("id", "log_type", "date", "status",
                          "created_at", "updated_at", "cp_name"):
                self.assertIn(field, log, f"{field} is read by the list row")


# ── 2. the bytes ─────────────────────────────────────────────────────────────

class DeviceStorageBudgetTest(unittest.TestCase):
    """The response for a photo- and signature-heavy project has to be storable.

    Measured on the real HTTP body, because that is what `cacheDocList`
    JSON-stringifies into one AsyncStorage key.
    """

    @classmethod
    def setUpClass(cls):
        cls.docs = _window_docs()
        cls.response, _ = _get(cls.docs)
        cls.size = len(cls.response.content)

    def test_the_sixty_date_window_fits_the_device(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertLess(
            self.size, ASYNC_STORAGE_CEILING,
            f"a {CACHE_DATE_LIMIT}-date window is {self.size:,} bytes against "
            f"a {ASYNC_STORAGE_CEILING:,} byte database-wide ceiling — the "
            f"write is rejected and the offline screen shows NOTHING",
        )

    def test_the_unprojected_document_would_not_have_fitted(self):
        """The counterfactual, in bytes, so the margin above is not luck."""
        raw = json.dumps({"dates": self.docs}, default=str)
        self.assertGreater(
            len(raw), ASYNC_STORAGE_CEILING,
            f"fixture is only {len(raw):,} bytes unprojected — it no longer "
            f"reproduces the condition this endpoint failed under",
        )

    def test_what_is_left_is_what_the_screen_actually_draws(self):
        """PINNED, so the residual is re-measured rather than inherited.

        After the projection the payload is dominated by the two things the
        renderers put on screen: the retained photo thumbnails and the kiosk
        worker signatures. Neither can be projected away without changing what
        an inspector sees, so the next reduction is not a projection — it is a
        serving endpoint for worker signatures, the same move WORKER_LIST_FIELDS
        made for osha_card_image.
        """
        body = self.response.content.decode()
        thumb_bytes = len(THUMB_B64) * body.count(THUMB_B64)
        sig_bytes = len(WORKER_SIG) * body.count(WORKER_SIG)
        self.assertGreater(
            (thumb_bytes + sig_bytes) / self.size, 0.8,
            f"residual no longer dominated by rendered blobs: thumbs "
            f"{thumb_bytes:,}B + worker signatures {sig_bytes:,}B of "
            f"{self.size:,}B",
        )


# ── 3. the cap ───────────────────────────────────────────────────────────────

class CompletenessTest(unittest.TestCase):
    """`.to_list(500)` silently truncated history, and a client DIFFS this.

    `datesToList` names each day's full-day PDF, and `sweepDocCache` deletes
    every cached file no stored list names. A response that quietly drops dates
    therefore makes the tablet DELETE the offline PDFs for them.
    """

    def test_history_beyond_five_hundred_logs_is_reachable(self):
        docs = _thin_docs(640)
        r, _ = _get(docs)
        self.assertEqual(r.status_code, 200, r.text[:400])
        dates = r.json().get("dates") or {}
        self.assertEqual(
            len(dates), 640,
            f"only {len(dates)} of 640 filed dates came back — the rest are "
            f"unreachable through the tablet's only logbook screen",
        )

    def test_the_default_response_declares_itself_complete(self):
        """An installed client cannot be upgraded. The parameter-free response
        is the one it asks for, so that response must never be a silent
        truncation — it says, in the body, that it is the whole set."""
        r, _ = _get(_thin_docs(640))
        self.assertIs(
            r.json().get("complete"), True,
            "the default response must state that it is the complete set",
        )

    def test_a_page_that_is_not_the_whole_set_says_so_and_names_the_next(self):
        docs = _thin_docs(640)
        r, _ = _get(docs, "/api/logbooks/project/proj1/submitted?limit=100")
        body = r.json()
        self.assertEqual(r.status_code, 200, r.text[:400])
        self.assertEqual(len(body.get("dates") or {}), 100)
        self.assertIs(body.get("complete"), False)
        self.assertTrue(body.get("next_before"), "a partial page must name its cursor")

    def test_paging_the_whole_history_is_gapless_and_repeat_free(self):
        docs = _thin_docs(640)
        expected = sorted({d["date"] for d in docs}, reverse=True)
        seen, cursor, pages = [], None, 0
        while True:
            path = "/api/logbooks/project/proj1/submitted?limit=100"
            if cursor:
                path += f"&before={cursor}"
            body = _get(docs, path)[0].json()
            page = sorted((body.get("dates") or {}).keys(), reverse=True)
            seen.extend(page)
            pages += 1
            self.assertLess(pages, 20, "pagination did not terminate")
            if body.get("complete") or not body.get("next_before"):
                break
            cursor = body["next_before"]
        self.assertEqual(len(seen), len(set(seen)), "a date was served twice")
        self.assertEqual(seen, expected, "paging did not cover the whole history")

    def test_a_day_is_never_split_across_two_pages(self):
        """The client groups by date and caches [{date, logs}]. Half a day in
        one page and half in the next would cache a day that is missing filed
        records, with nothing saying so."""
        docs = _thin_docs(40)
        # The date the page boundary lands on: the 20th newest, i.e. the last
        # one a `limit=20` page can hold. Give it a second filed log.
        boundary = sorted({d["date"] for d in docs}, reverse=True)[19]
        extra = dict(next(d for d in docs if d["date"] == boundary))
        extra["_id"] = "lb_thin_extra"
        docs.append(extra)
        r, _ = _get(docs, "/api/logbooks/project/proj1/submitted?limit=20")
        dates = r.json().get("dates") or {}
        self.assertEqual(len(dates), 20)
        self.assertEqual(
            len(dates[boundary]), 2,
            "a date came back with only part of its filed logs",
        )


# ── 4. the source, not the behaviour ─────────────────────────────────────────

class SourcePinTest(unittest.TestCase):
    """Two facts about this endpoint that no response can show."""

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _handler(self):
        i = self.SRC.index("async def get_submitted_logbooks")
        j = self.SRC.index("\n@api_router", i)
        return self.SRC[i:j]

    def test_the_handler_no_longer_carries_a_bare_five_hundred_cap(self):
        body = self._handler()
        self.assertNotIn(
            "to_list(500)", body,
            "the silent 500-log truncation is still here",
        )

    def test_the_project_access_gate_is_still_declared(self):
        self.assertIn("require_project_access", self._handler())

    # test_stripPhotoBlobs_is_still_the_screens_own_fallback WAS HERE.
    #
    # It grepped frontend/app/site/logbooks.jsx for the name stripPhotoBlobs.
    # That screen no longer stores its list at all -- siteLogbookHistory does,
    # as identity rows -- so the pin named a deleted function in a file that had
    # stopped being the owner, and failed for a move rather than for a
    # regression.
    #
    # The concern outlived the function and is asserted where it can be RUN:
    # siteLogbookHistory.test.cjs section H feeds identityRow a log carrying
    # base64, thumb_base64, a photos[] array and data, and asserts none of the
    # bytes come out. That is stronger than the pin -- identityRow is an
    # allow-list, so a photo field invented tomorrow is excluded without anyone
    # remembering to exclude it, where stripPhotoBlobs was a blacklist already
    # admitted to be a no-op.

if __name__ == "__main__":
    unittest.main()
