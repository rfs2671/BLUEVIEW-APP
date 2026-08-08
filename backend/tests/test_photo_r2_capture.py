"""PHOTOS LEAVE THE DOCUMENT: uploaded to R2 at CAPTURE, keyed on the row.

THE DEFECT. Activity photos were inlined as base64 into
logbooks.data.activities[].photos[] at SAVE time. base64 inflates the client's
own 150KB compression cap to ~200KB, so ten subcontractors at ten photos each
is ~20.5MB against MongoDB's 16MB document ceiling. The save that fails is the
END-OF-DAY one, on a signed record, after the CP has done the whole day's work.
test_activity_identity_photo_budget.py measures that peak and pins it: at the
client cap, 100 full-size inline copies DO NOT FIT. The finalize purge cannot
rescue it either — the purge runs after the save it would have to protect.

THE FIX MEASURED HERE. The bytes never enter the document. Each photo is
uploaded when it is TAKEN, under a key that does not depend on anything a save
would have to mint first, and the row carries only that key.

  THE KEY   logbook-photos/{project_id}/{activity_id}/{photo_id}.jpg
            logbook_id does not exist at capture time (the editor's
            existingLogId is null until the first push, and an offline photo
            may have no server document for hours), and (ai, pi) are positions
            that stop naming the same photo the moment a row moves.

  BOTH SCHEMES COEXIST. The positional keys the enhance pass wrote before this
  change are read OFF the photo document and never recomputed, so every old
  photo keeps resolving. Nothing is migrated by this code.

  THE RETAINED THUMBNAIL SURVIVES. A capture-uploaded photo never has an inline
  copy for the finalize purge to trade, so the purge skips it — which would
  leave thumb_base64 permanently absent, and thumb_base64 is what the KIOSK
  draws for an inspector on site with no signal. The enhance pass writes it
  instead. Asserted here, not assumed.

Run:  python -m pytest tests/test_photo_r2_capture.py -q
"""

from __future__ import annotations

import base64 as _b64
import io
import os
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

import asyncio  # noqa: E402

from bson import BSON  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  The real numbers
# ══════════════════════════════════════════════════════════════════════════

MONGO_MAX_BSON = 16 * 1024 * 1024          # 16,777,216 bytes, the hard ceiling

SUBS = 10
PHOTOS_PER_SUB = 10
TOTAL_PHOTOS = SUBS * PHOTOS_PER_SUB       # 100

# compressPhoto.js caps a capture at 150KB of JPEG; base64 inflates it by 4/3.
# This is the WORST case a compliant client can produce, and the worst case is
# the one that has to fit. Used only for the CONTROL below.
FULL_JPEG_BYTES = 150 * 1024
FULL_B64 = "A" * (((FULL_JPEG_BYTES + 2) // 3) * 4)

# The retained copy: long edge 400, ~25-40KB. 32KB is the middle of the range.
THUMB_JPEG = b"T" * (32 * 1024)
THUMB_B64 = _b64.b64encode(THUMB_JPEG).decode("ascii")

PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_test",
           "is_deleted": False}

# A real, decodable 1x1 JPEG. Small enough to inline, valid enough that the
# endpoint's magic-byte check and Pillow both accept it.
TINY_JPEG = _b64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
)


# ══════════════════════════════════════════════════════════════════════════
#  Fakes
# ══════════════════════════════════════════════════════════════════════════

def _set_path(doc, dotted, value):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _unset_path(doc, dotted):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    cur.pop(parts[-1], None)


class _Result:
    def __init__(self, _id="lb1"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, *a, **k):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, one=None, docs=None):
        self.one = one
        self.docs = list(docs or [])
        self.inserted = []

    async def find_one(self, *a, **k):
        return self.one

    def find(self, *a, **k):
        return _Cursor(self.docs)

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(doc)
        return _Result()

    async def update_one(self, *a, **k):
        return _Result()

    async def count_documents(self, *a, **k):
        return 0


class _Logbooks(_FakeCollection):
    """Holds the one document and APPLIES updates to it, so a test can measure
    the document the server actually left behind."""

    def __init__(self):
        super().__init__()
        self.doc = None

    async def find_one(self, query=None, *a, **k):
        if self.doc is None:
            return None
        # The create endpoint's dedupe lookup must miss so the insert happens.
        if query and "log_type" in query and "_id" not in query:
            return None
        return self.doc

    async def insert_one(self, doc, *a, **k):
        self.doc = dict(doc)
        self.doc["_id"] = "lb1"
        return _Result()

    async def update_one(self, q, u, *a, **k):
        if self.doc is not None:
            for path, val in (u.get("$set") or {}).items():
                _set_path(self.doc, path, val)
            for path in (u.get("$unset") or {}):
                _unset_path(self.doc, path)
        return _Result()


class _FakeDb:
    def __init__(self, logbooks=None, project=PROJECT):
        self._c = {
            "logbooks": logbooks if logbooks is not None else _Logbooks(),
            "projects": _FakeCollection(one=project),
        }

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


class _FakeR2:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.gets = []
        self.heads = []

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, **k):
        self.puts.append((Key, ContentType, len(Body or b"")))
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket=None, Key=None, **k):
        self.gets.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket=None, Key=None, **k):
        self.heads.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"ContentLength": len(self.objects[Key])}


CP_USER = {
    "_id": "cp_1", "id": "cp_1", "role": "cp", "company_id": "co_test",
    "account_status": "approved", "full_name": "Casey CP",
    "assigned_projects": ["proj1"],
}


def _client(user=CP_USER):
    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_approved] = _fake_user
    return TestClient(server.app), ov.clear


async def _no_enhance(*a, **k):
    return None


def _bson_size(doc):
    return len(BSON.encode(doc))


# ══════════════════════════════════════════════════════════════════════════
#  The day: ten subcontractors, ten photos each
# ══════════════════════════════════════════════════════════════════════════

def _activity_id(ai):
    return f"act_1754500000000_{ai}"


def _photo_id(ai, pi):
    return f"cap_1754500000000_{ai}_{pi}"


def _capture_key(ai, pi):
    return server._logbook_capture_photo_r2_key(
        "proj1", _activity_id(ai), _photo_id(ai, pi),
    )


def _activities(inline: bool):
    """The 100-photo day, in either storage shape.

    inline=False  what the client sends AFTER this track: the key only.
    inline=True   the CONTROL, what it sent before: the full-size base64 too.
    """
    out = []
    for ai in range(SUBS):
        photos = []
        for pi in range(PHOTOS_PER_SUB):
            p = {
                "activity_id": _activity_id(ai),
                "photo_id": _photo_id(ai, pi),
                "original_r2_key": _capture_key(ai, pi),
                "uri": f"file:///data/user/0/logbook_photos/{ai}_{pi}.jpg",
                "timestamp": "2026-08-07T13:00:00.000Z",
            }
            if inline:
                p["base64"] = FULL_B64
            photos.append(p)
        out.append({
            "activity_id": _activity_id(ai),
            "subcontractor_id": f"srv_{ai:032x}",
            "crew_id": f"C{ai + 1}",
            "company": f"Sub {ai}",
            "num_workers": "4",
            "work_description": "shoring",
            "work_locations": "cellar",
            "photos": photos,
        })
    return out


def _payload(inline=False):
    return {
        "project_id": "proj1",
        "log_type": "daily_jobsite",
        "date": "2026-08-07",
        "data": {
            "project_address": "1 Test Plaza, Brooklyn NY",
            "weather": "Sunny",
            "general_description": "Shoring and slab prep.",
            "activities": _activities(inline),
            "equipment_on_site": {"hoist": True},
            "checklist_items": {"fire_safety": True},
            "observations": [],
            "visitors_deliveries": "",
            "time_in": "07:00", "time_out": "15:30", "areas_visited": "Cellar",
        },
        "cp_signature": {"paths": [[1, 2]], "signed_at": "2026-08-07T15:31:00Z"},
        "cp_name": "Casey CP",
        "status": "submitted",
    }


def _save_day(inline=False):
    logbooks = _Logbooks()
    client, cleanup = _client()
    try:
        with patch.object(server, "db", _FakeDb(logbooks)), \
             patch.object(server, "_enhance_logbook_photos", _no_enhance):
            resp = client.post("/api/logbooks", json=_payload(inline))
    finally:
        cleanup()
    return resp, logbooks.doc


# ══════════════════════════════════════════════════════════════════════════
#  1. THE DOCUMENT — the save that fails today
# ══════════════════════════════════════════════════════════════════════════

class HundredPhotoSaveTest(unittest.TestCase):
    """The end-of-day save of a 100-photo log, measured in BSON bytes.

    Deliberately measured AT THE SAVE and not after finalize. The purge is a
    finalize-time reclaim; the byte peak that actually breaks a CP's day is the
    write itself, and no amount of later reclaiming can rescue a write that was
    rejected. If this is under the ceiling, the day is safe.
    """

    @classmethod
    def setUpClass(cls):
        cls.resp, cls.doc = _save_day(inline=False)
        cls.size = _bson_size(cls.doc) if cls.doc else 0
        _, control = _save_day(inline=True)
        cls.control_size = _bson_size(control) if control else 0

    def test_one_hundred_photos_save(self):
        self.assertEqual(self.resp.status_code, 200, self.resp.text[:400])
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        self.assertEqual(len(photos), TOTAL_PHOTOS)
        self.assertEqual(len(self.doc["data"]["activities"]), SUBS)

    def test_the_saved_document_is_under_the_16mb_ceiling(self):
        """THE assertion this file exists for."""
        self.assertLess(
            self.size, MONGO_MAX_BSON,
            f"100-photo logbook is {self.size:,} bytes at SAVE "
            f"(ceiling {MONGO_MAX_BSON:,})",
        )

    def test_it_is_not_under_the_ceiling_by_a_hair(self):
        """A day also carries observations, a signature bitmap and, once the
        enhance pass has run, a ~32KB retained thumbnail per photo. The photo
        metadata alone must leave room for all of it."""
        self.assertLess(
            self.size, MONGO_MAX_BSON // 8,
            f"100-photo logbook is {self.size:,} bytes — under the ceiling but "
            f"with no margin for the retained thumbnails",
        )

    def test_no_photo_carries_full_size_image_data(self):
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        with_bytes = [p for p in photos if p.get("base64")]
        self.assertEqual(
            with_bytes, [], f"{len(with_bytes)} photos still inline full-size data",
        )
        self.assertTrue(all(p.get("original_r2_key") for p in photos))

    def test_every_photo_has_its_own_key(self):
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        keys = {p["original_r2_key"] for p in photos}
        self.assertEqual(len(keys), TOTAL_PHOTOS, "two photos share one object")

    # ── the control ──────────────────────────────────────────────────────

    def test_the_same_day_inline_does_not_fit(self):
        """WHY THIS TRACK EXISTS, in bytes. The identical day, with the
        full-size base64 the client used to inline, is over the ceiling — so
        the save is rejected outright and the CP's whole day is refused.

        Pinned as a CONTROL rather than inherited from a docstring: if the
        client cap changes, this number has to be re-measured.
        """
        self.assertGreater(
            self.control_size, MONGO_MAX_BSON,
            f"inline control is {self.control_size:,} bytes — expected over "
            f"the {MONGO_MAX_BSON:,} ceiling",
        )

    def test_the_saving_is_the_overwhelming_majority_of_the_document(self):
        saved = 1 - (self.size / self.control_size)
        self.assertGreater(
            saved, 0.95,
            f"keys instead of bytes saved only {saved:.1%} "
            f"({self.control_size:,} -> {self.size:,})",
        )


# ══════════════════════════════════════════════════════════════════════════
#  2. THE KEY
# ══════════════════════════════════════════════════════════════════════════

class CaptureKeyTest(unittest.TestCase):

    def test_shape(self):
        self.assertEqual(
            server._logbook_capture_photo_r2_key("proj1", "act_7", "cap_3"),
            "logbook-photos/proj1/act_7/cap_3.jpg",
        )

    def test_it_shares_the_cascade_prefix_with_the_positional_scheme(self):
        """hard_delete_project sweeps `logbook-photos/{project_id}/` with ONE
        unconditional prefix. A key outside it would be orphaned storage."""
        prefix = "logbook-photos/proj1/"
        self.assertTrue(
            server._logbook_capture_photo_r2_key("proj1", "a", "p").startswith(prefix),
        )
        self.assertTrue(
            server._logbook_photo_r2_key("proj1", "lb1", 0, 0, "thumb").startswith(prefix),
        )

    def test_it_does_not_depend_on_position(self):
        """The whole point: reordering rows must not rename the object."""
        first = server._logbook_capture_photo_r2_key("proj1", "act_7", "cap_3")
        # Same row, now third in the array, second photo instead of first.
        again = server._logbook_capture_photo_r2_key("proj1", "act_7", "cap_3")
        self.assertEqual(first, again)

    def test_it_does_not_depend_on_a_logbook_id(self):
        """There isn't one at capture time. Stated as a signature fact so a
        future edit cannot quietly reintroduce the dependency."""
        import inspect
        params = inspect.signature(server._logbook_capture_photo_r2_key).parameters
        self.assertEqual(list(params), ["project_id", "activity_id", "photo_id"])

    # ── untrusted ids ────────────────────────────────────────────────────

    def test_traversal_cannot_escape_the_prefix(self):
        """Traversal needs a SEPARATOR. Dots survive the sanitiser (they are
        legal in a key) but no `/` does, so `../../etc` collapses into one inert
        segment and the key cannot leave logbook-photos/{project_id}/."""
        key = server._logbook_capture_photo_r2_key("proj1", "../../etc", "../passwd")
        self.assertTrue(key.startswith("logbook-photos/proj1/"))
        self.assertEqual(key.count("/"), 3, "a segment was injected")
        self.assertNotIn("..", key.split("/"), "a bare '..' segment survived")
        self.assertEqual(key, "logbook-photos/proj1/.._.._etc/.._passwd.jpg")

    def test_an_injected_slash_cannot_add_a_segment(self):
        key = server._logbook_capture_photo_r2_key("proj1", "a/b/c", "p")
        self.assertEqual(key, "logbook-photos/proj1/a_b_c/p.jpg")

    def test_an_empty_id_is_not_an_empty_segment(self):
        key = server._logbook_capture_photo_r2_key("proj1", "", "")
        self.assertEqual(key, "logbook-photos/proj1/unknown/unknown.jpg")

    def test_segments_are_length_capped(self):
        key = server._logbook_capture_photo_r2_key("proj1", "a" * 500, "b" * 500)
        self.assertEqual(len(server._logbook_photo_key_segment("a" * 500)), 80)
        self.assertLess(len(key), 200)

    # ── derivatives ──────────────────────────────────────────────────────

    def test_derivative_keys_hang_off_the_original(self):
        orig = "logbook-photos/proj1/act_7/cap_3.jpg"
        self.assertEqual(
            server._logbook_photo_derivative_key(orig, "enhanced"),
            "logbook-photos/proj1/act_7/cap_3-enhanced.jpg",
        )
        self.assertEqual(
            server._logbook_photo_derivative_key(orig, "thumb"),
            "logbook-photos/proj1/act_7/cap_3-thumb.jpg",
        )

    def test_the_positional_scheme_is_untouched(self):
        """Old photos must keep naming the objects they already have."""
        self.assertEqual(
            server._logbook_photo_r2_key("proj1", "lb1", 0, 0, "enhanced"),
            "logbook-photos/proj1/lb1/0-0-enhanced.jpg",
        )


# ══════════════════════════════════════════════════════════════════════════
#  3. THE UPLOAD ENDPOINT
# ══════════════════════════════════════════════════════════════════════════

def _upload(r2, activity_id="act_7", photo_id="cap_3", content=TINY_JPEG,
            project_id="proj1", user=CP_USER, bucket="bv-bucket"):
    client, cleanup = _client(user)
    try:
        with patch.object(server, "db", _FakeDb()), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", bucket):
            return client.post(
                f"/api/projects/{project_id}/logbook-photo",
                data={"activity_id": activity_id, "photo_id": photo_id},
                files={"file": ("shot.jpg", content, "image/jpeg")},
            )
    finally:
        cleanup()


class UploadEndpointTest(unittest.TestCase):

    def test_a_capture_lands_in_r2_under_the_capture_key(self):
        r2 = _FakeR2()
        resp = _upload(r2)
        self.assertEqual(resp.status_code, 200, resp.text[:400])
        key = "logbook-photos/proj1/act_7/cap_3.jpg"
        self.assertEqual(resp.json()["original_r2_key"], key)
        self.assertIn(key, r2.objects)
        self.assertEqual(r2.objects[key], TINY_JPEG)

    def test_the_field_name_is_the_one_the_serving_ladder_already_reads(self):
        """`original_r2_key` was the ladder's ORIGINAL rung, documented as inert
        because nothing wrote it. This is what writes it — so no reader had to
        change to serve a capture-uploaded photo."""
        resp = _upload(_FakeR2())
        self.assertIn("original_r2_key", resp.json())
        srcs = server._logbook_photo_sources(
            {"original_r2_key": resp.json()["original_r2_key"]},
        )
        self.assertEqual(srcs, [("r2", resp.json()["original_r2_key"])])

    def test_a_retry_overwrites_the_same_object(self):
        """Idempotence is what lets the offline drain retry forever without
        leaking one orphaned object per failed attempt."""
        r2 = _FakeR2()
        a = _upload(r2)
        b = _upload(r2)
        self.assertEqual(a.json()["original_r2_key"], b.json()["original_r2_key"])
        self.assertEqual(len(r2.objects), 1)
        self.assertEqual(len(r2.puts), 2)

    def test_it_stores_image_jpeg(self):
        r2 = _FakeR2()
        _upload(r2)
        self.assertEqual(r2.puts[0][1], "image/jpeg")

    # ── refusals ─────────────────────────────────────────────────────────

    def test_an_empty_body_is_refused(self):
        self.assertEqual(_upload(_FakeR2(), content=b"").status_code, 400)

    def test_a_non_image_is_refused(self):
        """The endpoint is the one place arbitrary bytes could be parked in the
        bucket under an image's name. The content type is decided by the BYTES,
        never by the client-controlled multipart header."""
        r2 = _FakeR2()
        resp = _upload(r2, content=b"#!/bin/sh\nrm -rf /\n" * 8)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(r2.objects, {})

    def test_an_oversize_photo_is_refused(self):
        big = TINY_JPEG + b"\x00" * (server._LOGBOOK_PHOTO_MAX_BYTES + 1)
        self.assertEqual(_upload(_FakeR2(), content=big).status_code, 400)

    def test_a_missing_id_is_refused(self):
        self.assertEqual(_upload(_FakeR2(), activity_id="  ").status_code, 400)
        self.assertEqual(_upload(_FakeR2(), photo_id="").status_code, 422)

    def test_unconfigured_storage_is_a_5xx_the_device_will_retry(self):
        """THE STATUS CODE IS PART OF THE OFFLINE CONTRACT. A device that
        cannot upload keeps the file and its pending marker; it must be able to
        tell 'this photo is unacceptable' (4xx, stop) from 'storage is
        unavailable' (5xx, keep trying). A 400 here would read as a reason to
        give up on a photo that is perfectly good."""
        resp = _upload(None, bucket="")
        self.assertEqual(resp.status_code, 503)

    def test_an_r2_failure_is_a_5xx_the_device_will_retry(self):
        class _Broken(_FakeR2):
            def put_object(self, **k):
                raise RuntimeError("R2 unreachable")
        self.assertEqual(_upload(_Broken()).status_code, 502)

    # ── guards ───────────────────────────────────────────────────────────

    def test_it_declares_both_project_guards(self):
        """Pinned here as well as in test_tenant_isolation_writes.py's TIER3
        bucket, so this file states its own authorization contract."""
        import ast
        src = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))
        found = None
        for node in ast.walk(src):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if (dec.args and isinstance(dec.args[0], ast.Constant)
                        and dec.args[0].value == "/projects/{project_id}/logbook-photo"):
                    found = dec
        self.assertIsNotNone(found, "the upload route was not found")
        deps = ""
        for kw in found.keywords:
            if kw.arg == "dependencies":
                deps = ast.unparse(kw.value)
        self.assertIn("require_approved", deps)
        self.assertIn("require_project_access", deps)

    def test_the_guards_are_actually_wired_on_the_route(self):
        """A decorator can be textually correct and never take effect."""
        route = next(
            r for r in server.app.routes
            if getattr(r, "path", "") == "/api/projects/{project_id}/logbook-photo"
        )

        def _names(dep, seen=None):
            seen = seen if seen is not None else set()
            if dep.call is not None:
                seen.add(getattr(dep.call, "__name__", ""))
            for sub in dep.dependencies:
                _names(sub, seen)
            return seen

        names = _names(route.dependant)
        self.assertIn("require_approved", names)
        self.assertIn("require_project_access", names)

    def test_a_cross_company_caller_is_refused(self):
        outsider = {**CP_USER, "_id": "cp_x", "id": "cp_x",
                    "company_id": "co_other", "assigned_projects": []}
        r2 = _FakeR2()
        self.assertEqual(_upload(r2, user=outsider).status_code, 403)
        self.assertEqual(r2.objects, {})

    def test_an_assigned_cp_is_admitted(self):
        """require_project_access branch 3. The CP's own company is not the
        project's, which is the normal shape of a contractor engagement — this
        must not be over-gated or the feature does not work for its only user."""
        cp = {**CP_USER, "company_id": "co_contractor",
              "assigned_projects": ["proj1"]}
        self.assertEqual(_upload(_FakeR2(), user=cp).status_code, 200)


# ══════════════════════════════════════════════════════════════════════════
#  4. THE READERS
# ══════════════════════════════════════════════════════════════════════════

def _logbook_with(photo):
    return {
        "_id": "lb1", "project_id": "proj1", "company_id": "co_test",
        "log_type": "daily_jobsite", "date": "2026-08-07",
        "cp_signature": {"paths": [[1, 2]]}, "cp_name": "Casey CP",
        "data": {"activities": [{
            "activity_id": "act_7", "crew_id": "C1", "company": "Acme",
            "num_workers": 3, "work_description": "shoring",
            "work_locations": "cellar", "photos": [dict(photo)],
        }]},
    }


def _serve(photo, r2, v="", headers=None):
    logbooks = _Logbooks()
    logbooks.doc = _logbook_with(photo)

    class _Only(_Logbooks):
        async def find_one(self, *a, **k):
            return logbooks.doc

    db = _FakeDb(_Only())
    with patch.object(server, "db", db), \
         patch.object(server, "_r2_client", r2), \
         patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
        c = TestClient(server.app)
        url = "/api/reports/logbook-photo/lb1/0/0" + (f"?v={v}" if v else "")
        return c.get(url, headers=headers or {})


CAPTURE_KEY = "logbook-photos/proj1/act_7/cap_3.jpg"
CAPTURE_BYTES = b"CAPTURED-ORIGINAL-JPEG"
OLD_ENH = "logbook-photos/proj1/lb1/0-0-enhanced.jpg"
OLD_THUMB = "logbook-photos/proj1/lb1/0-0-thumb.jpg"


class PublicPhotoEndpointTest(unittest.TestCase):
    """The people reading an emailed daily report have no login here."""

    def test_a_capture_uploaded_photo_serves_to_a_caller_with_no_login(self):
        resp = _serve(
            {"original_r2_key": CAPTURE_KEY, "activity_id": "act_7"},
            _FakeR2({CAPTURE_KEY: CAPTURE_BYTES}),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, CAPTURE_BYTES)
        self.assertEqual(resp.headers["content-type"], "image/jpeg")

    def test_no_authorization_header_is_sent_or_required(self):
        """Stated explicitly: the app's dependency overrides are NOT installed
        for this call, so nothing here could be authenticating by accident."""
        server.app.dependency_overrides.clear()
        resp = _serve(
            {"original_r2_key": CAPTURE_KEY},
            _FakeR2({CAPTURE_KEY: CAPTURE_BYTES}),
            headers={},
        )
        self.assertEqual(resp.status_code, 200)

    def test_a_photo_under_the_OLD_POSITIONAL_KEY_still_resolves(self):
        """Nothing is migrated. A photo whose only copies are the positional
        objects the enhance pass wrote before this change must keep serving,
        forever, with no rewrite of any kind."""
        old = {"enhance_status": "done",
               "enhanced_r2_key": OLD_ENH, "thumb_r2_key": OLD_THUMB}
        r2 = _FakeR2({OLD_ENH: b"OLD-ENHANCED", OLD_THUMB: b"OLD-THUMB"})
        self.assertEqual(_serve(old, r2, v="enhanced").content, b"OLD-ENHANCED")
        self.assertEqual(_serve(old, r2, v="thumb").content, b"OLD-THUMB")
        self.assertEqual(_serve(old, r2).status_code, 200)

    def test_both_schemes_serve_from_the_same_document(self):
        """They coexist; the resolver reads whichever key the photo carries and
        never recomputes either one."""
        new = {"original_r2_key": CAPTURE_KEY}
        old = {"enhanced_r2_key": OLD_ENH, "thumb_r2_key": OLD_THUMB}
        r2 = _FakeR2({CAPTURE_KEY: CAPTURE_BYTES,
                      OLD_ENH: b"OLD-ENHANCED", OLD_THUMB: b"OLD-THUMB"})
        self.assertEqual(_serve(new, r2).content, CAPTURE_BYTES)
        self.assertEqual(_serve(old, r2).content, b"OLD-ENHANCED")

    def test_a_thumb_request_falls_back_to_the_original_before_enhancement(self):
        """A photo uploaded seconds ago has no derivatives yet. The report must
        show it anyway rather than 404 while the enhance pass catches up."""
        resp = _serve({"original_r2_key": CAPTURE_KEY},
                      _FakeR2({CAPTURE_KEY: CAPTURE_BYTES}), v="thumb")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, CAPTURE_BYTES)

    def test_the_retained_thumbnail_still_serves_when_r2_is_unreachable(self):
        class _Down(_FakeR2):
            def get_object(self, **k):
                raise RuntimeError("R2 unreachable")
        resp = _serve(
            {"original_r2_key": CAPTURE_KEY, "thumb_base64": THUMB_B64}, _Down(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_JPEG)


class ReportEmitGateTest(unittest.TestCase):
    """server.py's report gate emits on ANY surviving copy. A photo skipped
    there does not render broken — it VANISHES, and the report then reads as
    'no photos taken' on a day photos were taken."""

    def test_a_capture_uploaded_photo_is_renderable(self):
        self.assertTrue(server._logbook_photo_is_renderable(
            {"original_r2_key": CAPTURE_KEY},
        ))

    def test_a_photo_with_a_uri_and_no_key_is_not(self):
        """The pending-upload state. Honest: there is nothing the SERVER can
        serve yet, and claiming otherwise would emit a broken <img>."""
        self.assertFalse(server._logbook_photo_is_renderable(
            {"uri": "file:///data/user/0/cap_1.jpg", "upload_pending": True},
        ))

    def test_the_daily_report_emits_a_capture_uploaded_photo(self):
        db = _FakeDb()
        db.projects.one = PROJECT

        db._c["logbooks"] = _FakeCollection(
            docs=[_logbook_with({"original_r2_key": CAPTURE_KEY})],
        )
        with patch.object(server, "db", db):
            html = asyncio.new_event_loop().run_until_complete(
                server.generate_combined_report("proj1", "2026-08-07"),
            )
        self.assertIn("/api/reports/logbook-photo/lb1/0/0", html)


# ══════════════════════════════════════════════════════════════════════════
#  5. THE ENHANCE PASS, sourced from R2
# ══════════════════════════════════════════════════════════════════════════

class EnhanceFromR2Test(unittest.TestCase):

    def _run(self, photo, r2):
        logbooks = _Logbooks()
        logbooks.doc = _logbook_with(photo)

        class _Only(_Logbooks):
            def __init__(_s):
                super().__init__()
                _s.doc = logbooks.doc

            async def find_one(_s, *a, **k):
                return _s.doc

        coll = _Only()
        db = _FakeDb(coll)
        with patch.object(server, "db", db), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
            asyncio.new_event_loop().run_until_complete(
                server._enhance_logbook_photos("lb1", "proj1"),
            )
        return coll.doc["data"]["activities"][0]["photos"][0]

    def test_it_reads_the_bytes_back_out_of_r2(self):
        r2 = _FakeR2({CAPTURE_KEY: TINY_JPEG})
        out = self._run({"original_r2_key": CAPTURE_KEY}, r2)
        self.assertIn(CAPTURE_KEY, r2.gets)
        self.assertEqual(out["enhance_status"], "done")

    def test_the_derivatives_hang_off_the_capture_key(self):
        r2 = _FakeR2({CAPTURE_KEY: TINY_JPEG})
        out = self._run({"original_r2_key": CAPTURE_KEY}, r2)
        self.assertEqual(
            out["enhanced_r2_key"], "logbook-photos/proj1/act_7/cap_3-enhanced.jpg",
        )
        self.assertEqual(
            out["thumb_r2_key"], "logbook-photos/proj1/act_7/cap_3-thumb.jpg",
        )
        self.assertIn(out["enhanced_r2_key"], r2.objects)
        self.assertIn(out["thumb_r2_key"], r2.objects)

    def test_it_writes_the_retained_thumbnail_the_kiosk_needs(self):
        """THE KIOSK RULING. A capture-uploaded photo never had an inline copy
        for the finalize purge to trade, so the purge skips it and would leave
        thumb_base64 permanently absent. Nothing else would ever write it, and
        without it an inspector on site with no signal sees a blank tile on a
        signed record."""
        r2 = _FakeR2({CAPTURE_KEY: TINY_JPEG})
        out = self._run({"original_r2_key": CAPTURE_KEY}, r2)
        self.assertTrue(out.get("thumb_base64"))
        # The SAME bytes that went to R2, not a second independent render.
        self.assertEqual(
            _b64.b64decode(out["thumb_base64"]), r2.objects[out["thumb_r2_key"]],
        )

    def test_the_retained_thumbnail_is_small_enough_to_be_worth_keeping(self):
        out = self._run({"original_r2_key": CAPTURE_KEY},
                        _FakeR2({CAPTURE_KEY: TINY_JPEG}))
        size = len(_b64.b64decode(out["thumb_base64"]))
        self.assertLess(
            size * TOTAL_PHOTOS, MONGO_MAX_BSON // 2,
            "a hundred retained thumbnails must sit well inside the ceiling",
        )

    def test_the_inline_path_still_does_NOT_write_a_retained_thumbnail(self):
        """The purge materialises that one, from the bytes R2 really returns,
        in the same update that removes the full-size copy. The writer must not
        be the thing that verifies the writer."""
        b64 = _b64.b64encode(TINY_JPEG).decode("ascii")
        out = self._run({"base64": b64}, _FakeR2())
        self.assertEqual(out["enhance_status"], "done")
        self.assertNotIn("thumb_base64", out)
        self.assertEqual(out["enhanced_r2_key"], OLD_ENH)

    def test_the_inline_path_wins_when_a_photo_carries_both(self):
        """What the backfill script leaves behind mid-migration. It must keep
        taking the route whose derivatives the finalize purge knows how to
        prove, or the inline copy could never be reclaimed."""
        b64 = _b64.b64encode(TINY_JPEG).decode("ascii")
        out = self._run({"base64": b64, "original_r2_key": CAPTURE_KEY}, _FakeR2())
        self.assertEqual(out["enhanced_r2_key"], OLD_ENH)

    def test_a_missing_object_is_recorded_and_never_loses_the_photo(self):
        out = self._run({"original_r2_key": CAPTURE_KEY}, _FakeR2())
        self.assertEqual(out["enhance_status"], "failed")
        self.assertEqual(out["original_r2_key"], CAPTURE_KEY)
        self.assertTrue(server._logbook_photo_is_renderable(out))

    def test_an_already_enhanced_photo_is_skipped(self):
        r2 = _FakeR2({CAPTURE_KEY: TINY_JPEG})
        self._run({"original_r2_key": CAPTURE_KEY, "enhance_status": "done"}, r2)
        self.assertEqual(r2.gets, [])


# ══════════════════════════════════════════════════════════════════════════
#  6. TRACK P — what stays, and what goes quiet
# ══════════════════════════════════════════════════════════════════════════

class PurgeCoexistenceTest(unittest.TestCase):

    def _purge(self, photo, r2):
        doc = _logbook_with(photo)
        coll = _Logbooks()
        coll.doc = doc
        with patch.object(server, "db", _FakeDb(coll)), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
            n = asyncio.new_event_loop().run_until_complete(
                server._purge_finalized_photo_base64("lb1", doc),
            )
        return n, coll.doc["data"]["activities"][0]["photos"][0]

    def test_the_purge_is_INERT_on_a_capture_uploaded_photo(self):
        """It has no inline full-size copy to reclaim. Not deleted, not
        disabled — it simply has nothing to do, which is the correct outcome
        and the one worth pinning."""
        r2 = _FakeR2({CAPTURE_KEY: TINY_JPEG})
        n, out = self._purge(
            {"original_r2_key": CAPTURE_KEY, "enhance_status": "done",
             "thumb_base64": THUMB_B64}, r2,
        )
        self.assertEqual(n, 0)
        self.assertEqual(r2.heads, [])
        self.assertEqual(out["thumb_base64"], THUMB_B64)
        self.assertEqual(out["original_r2_key"], CAPTURE_KEY)

    def test_the_purge_is_STILL_LIVE_on_an_inline_photo(self):
        """Every existing log still needs it, and so does any photo that falls
        back to inlining. Nothing here is deleted."""
        r2 = _FakeR2({OLD_ENH: b"E", OLD_THUMB: THUMB_JPEG})
        n, out = self._purge(
            {"base64": _b64.b64encode(TINY_JPEG).decode("ascii"),
             "enhance_status": "done",
             "enhanced_r2_key": OLD_ENH, "thumb_r2_key": OLD_THUMB}, r2,
        )
        self.assertEqual(n, 1)
        self.assertNotIn("base64", out)
        self.assertEqual(out["thumb_base64"], THUMB_B64)

    def test_the_retained_thumbnail_is_never_removed_by_anything(self):
        photo = {"original_r2_key": CAPTURE_KEY, "thumb_base64": THUMB_B64}
        _, out = self._purge(photo, _FakeR2({CAPTURE_KEY: TINY_JPEG}))
        self.assertEqual(out["thumb_base64"], THUMB_B64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
