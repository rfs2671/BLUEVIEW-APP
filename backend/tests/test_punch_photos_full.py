"""Live 588, Mon Oct 12 (PR 2 of 4).

  3. Punch photos in the app were blurry: the stored image was WhatsApp's
     ~100 px preview (jpegThumbnail), not the photo. download_image now keeps
     only the original (download-media's media node, decrypted with the
     mediaKey from the answer or the webhook), never a preview, retrying
     while WaAPI has only that. Completion photos ("done P1" as a photo's
     caption, in the group or a DM) are downloaded and kept the same way.
     scripts/punch_photo_backfill.py re-fetches the originals (P-588-1..3).
  4. Punch items are not the model's guesses: they stay out of the
     Attention review queue and its precision (filtered, not deleted).
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from PIL import Image  # noqa: E402

import server  # noqa: E402
from lib import punch  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_attention import ADMIN, CO_A, G_A  # noqa: E402

KEY = base64.b64encode(bytes(range(32))).decode()


def _jpeg(w, h, color=(200, 80, 40)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG", quality=90)
    return b.getvalue()


FULL = _jpeg(1600, 1200)
THUMB = _jpeg(96, 72, (10, 10, 10))


def _b64(b):
    return base64.b64encode(b).decode()


def _encrypt(plain: bytes, key_b64: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    keys = HKDF(algorithm=hashes.SHA256(), length=112, salt=b"\x00" * 32,
                info=b"WhatsApp Image Keys").derive(base64.b64decode(key_b64))
    pad = 16 - len(plain) % 16
    enc = Cipher(algorithms.AES(keys[16:48]), modes.CBC(keys[0:16])).encryptor()
    return enc.update(plain + bytes([pad]) * pad) + enc.finalize() + b"\x07" * 10


def _parsed(caption="", thumb=THUMB, key=None, mid="false_g_ABC_1@c.us"):
    """A webhook photo: its preview rides in the body (_data.body)."""
    data = {"type": "image", "body": _b64(thumb) if thumb else caption,
            "caption": caption}
    if key:
        data["mediaKey"] = key
    return {"has_image": True, "message_id": "ABC", "message_id_serialized": mid,
            "body": caption or (_b64(thumb) if thumb else ""), "raw": {"_data": data}}


class _Resp:
    def __init__(self, status, j):
        self.status_code, self._j, self.content = status, j, b"x"

    def json(self):
        return self._j


def _client(answers):
    calls = []

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None, **k):
            calls.append(json)
            a = answers[min(len(calls), len(answers)) - 1]
            return a if isinstance(a, _Resp) else _Resp(200, a)
    return C, calls


def _answer(media=None, msg_body=None):
    """download-media's answer: the message (with its preview in the body,
    first) and the media node."""
    d = {}
    if msg_body is not None:
        d["message"] = {"_data": {"body": _b64(msg_body)}}
    if media is not None:
        d["media"] = {"mimetype": "image/jpeg", "data": _b64(media), "filename": None}
    return {"data": {"status": "success", "data": d}}


def _download(parsed, answers):
    C, calls = _client(answers)

    async def no_sleep(*a, **k):
        return None
    with patch.object(server, "ServerHttpClient", C), \
            patch.object(server, "WAAPI_INSTANCE_ID", "inst"), \
            patch.object(server, "WAAPI_TOKEN", "tok"), \
            patch.object(server.asyncio, "sleep", no_sleep):
        return asyncio.run(server.download_image(parsed)), calls


class TheOriginalNotThePreview(unittest.TestCase):

    def test_the_media_node_wins_over_the_preview_listed_first(self):
        img, calls = _download(_parsed(), [_answer(media=FULL, msg_body=THUMB)])
        self.assertEqual(img, FULL)
        self.assertEqual(Image.open(io.BytesIO(img)).size, (1600, 1200))
        self.assertEqual(calls, [{"messageId": "false_g_ABC_1@c.us"}])

    def test_only_a_preview_is_never_kept_and_is_tried_again(self):
        img, calls = _download(_parsed(), [_answer(msg_body=THUMB)] * 5)
        self.assertIsNone(img)
        self.assertEqual(len(calls), len(server._PHOTO_TRIES))

    def test_a_small_media_node_is_a_preview_too(self):
        img, _ = _download(_parsed(), [_answer(media=THUMB)] * 3)
        self.assertIsNone(img)

    def test_the_webhooks_own_thumbnail_is_never_the_photo(self):
        big_thumb = _jpeg(640, 480, (1, 2, 3))      # even a large one
        img, _ = _download(_parsed(thumb=big_thumb), [_answer(media=big_thumb)] * 3)
        self.assertIsNone(img)

    def test_the_original_arrives_on_a_later_try(self):
        img, calls = _download(_parsed(), [_answer(msg_body=THUMB), _Resp(500, {}),
                                           _answer(media=FULL)])
        self.assertEqual(img, FULL)
        self.assertEqual(len(calls), 3)

    def test_still_encrypted_decrypted_with_the_webhooks_media_key(self):
        enc = _encrypt(FULL, KEY)
        img, _ = _download(_parsed(key=KEY), [_answer(media=enc)])
        self.assertEqual(img, FULL)

    def test_a_walk_photo_stores_the_original(self):
        db = FakeDb()
        sess = {"_id": "w1", "user_id": "u_admin", "project_id": "proj_a",
                "status": "capturing", "items": []}
        db[punch.SESSIONS].rows.append(dict(sess))
        up = []
        C, _ = _client([_answer(media=FULL, msg_body=THUMB)])

        async def no_sleep(*a, **k):
            return None
        with patch.object(server, "db", db), \
                patch.object(server, "ServerHttpClient", C), \
                patch.object(server, "WAAPI_INSTANCE_ID", "inst"), \
                patch.object(server, "WAAPI_TOKEN", "tok"), \
                patch.object(server.asyncio, "sleep", no_sleep), \
                patch.object(server, "_upload_to_r2", lambda b, k, t: up.append((k, b)) or k):
            it = asyncio.run(server._punch_photo_item(
                dict(sess, items=[]), _parsed(), "tile chipped", None, "MID",
                datetime.now(timezone.utc)))
        self.assertEqual(up, [("wa-photos/proj_a/w1/1.jpg", FULL)])
        self.assertEqual(it["photo_key"], "wa-photos/proj_a/w1/1.jpg")


def _punch_db(**row):
    db = FakeDb()
    r = {"_id": "proj_a:P-588-1", "pid": "P-588-1", "seq": 1, "company_id": CO_A,
         "project_id": "proj_a", "group_id": G_A, "status": "open", "sent_via": "dm",
         "assignee": {"kind": "sender_map", "id": "s1", "name": "Chris",
                      "jid": "17185550199@c.us"},
         "photo_key": "wa-photos/proj_a/w1/1.jpg", "walk_id": "w1", "history": []}
    r.update(row)
    db[punch.COLLECTION].rows.append(r)
    return db


class CompletionPhotos(unittest.TestCase):

    def _with(self, db, fn):
        up = []

        async def full(parsed):
            return FULL
        with patch.object(server, "db", db), \
                patch.object(server, "download_image", full), \
                patch.object(server, "_upload_to_r2", lambda b, k, t: up.append((k, b)) or k):
            out = asyncio.run(fn())
        return out, up

    def test_done_as_a_dm_photos_caption_keeps_the_photo(self):
        db = _punch_db()
        p = _parsed(caption="done P-588-1", mid="false_17185550199@c.us_DONE1")
        p["message_id"] = "DONE1"
        reply, up = self._with(db, lambda: server._punch_dm_done_by_number(
            "17185550199@c.us", punch.parse_done_ref("done P-588-1"), p))
        self.assertEqual(reply, "P-588-1 marked done — ready to check.")
        row = db[punch.COLLECTION].rows[0]
        self.assertEqual(row["status"], "ready_to_check")
        self.assertEqual(row["completion"]["photo_key"], "wa-photos/proj_a/msg/DONE1.jpg")
        self.assertEqual(row["completion"]["quote"], "done P-588-1")
        self.assertEqual(up, [("wa-photos/proj_a/msg/DONE1.jpg", FULL)])

    def test_a_caption_that_names_an_item_is_a_completion_photo(self):
        for cap, want in (("done P1", True), ("done P-588-1", True), ("done 1", True),
                          ("tile chipped", False), ("", False)):
            self.assertEqual(server._punch_photo_caption_ref(_parsed(caption=cap), cap), want, cap)
        self.assertFalse(server._punch_photo_caption_ref({"has_image": False}, "done P1"))

    def test_the_group_message_carries_it_to_the_item(self):
        db = _punch_db(sent_via="group")
        p = _parsed(caption="done P1")
        p.update(sender="17185550199@c.us", photo_key="wa-photos/proj_a/msg/ABC.jpg",
                 has_audio=False, timestamp=0)

        async def run():
            row = await server._store_group_message(
                p, G_A, "proj_a", CO_A, "done P1", datetime.now(timezone.utc))
            self.assertEqual(row["photo_key"], "wa-photos/proj_a/msg/ABC.jpg")
            return await server._punch_group_message(
                row, {"project_id": "proj_a", "company_id": CO_A, "group_id": G_A, "cache": {}})
        handled, _ = self._with(db, run)
        self.assertTrue(handled)
        self.assertEqual(db[punch.COLLECTION].rows[0]["completion"]["photo_key"],
                         "wa-photos/proj_a/msg/ABC.jpg")


    def test_a_group_photo_is_kept_only_for_its_assignees_done(self):
        # Codex review on #762: any "photo of P1" was uploaded and never used.
        def ok(cap, sender="17185550199@c.us", **row):
            db = _punch_db(sent_via="group", **row)
            p = _parsed(caption=cap)
            p["sender"] = sender
            with patch.object(server, "db", db):
                return asyncio.run(server._punch_group_completion_ok(p, cap, "proj_a", CO_A))
        self.assertTrue(ok("done P1"))
        self.assertTrue(ok("done P-588-1"))
        self.assertFalse(ok("photo of P1"))                       # not a "done"
        self.assertFalse(ok("done P2"))                           # no such item
        self.assertFalse(ok("done P1", sender="19995550000@c.us"))  # not the assignee
        self.assertFalse(ok("done P1", status="closed"))          # not open
        self.assertFalse(ok("done P-999-1"))                      # another job's

    def test_a_refused_group_photo_is_never_downloaded(self):
        db = _punch_db(sent_via="group")
        calls = []

        async def dl(p):
            calls.append(p)
            return FULL
        p = _parsed(caption="photo of P1")
        p["sender"] = "17185550199@c.us"
        with patch.object(server, "db", db), patch.object(server, "download_image", dl):
            if asyncio.run(server._punch_group_completion_ok(p, "photo of P1", "proj_a", CO_A)):
                asyncio.run(server._punch_message_photo(p, "proj_a"))
        self.assertEqual(calls, [])
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        i = src.index("_punch_photo_caption_ref(parsed, body)")
        self.assertLess(src.index("_punch_group_completion_ok", i), src.index("_punch_message_photo", i))


class Backfill(unittest.TestCase):

    def _run(self, *argv):
        import scripts.punch_photo_backfill as bf
        db = _punch_db(extra_photos=["wa-photos/proj_a/w1/2.jpg"])
        db[punch.COLLECTION].rows.append(dict(
            db[punch.COLLECTION].rows[0], _id="proj_a:P-588-9", pid="P-588-9", seq=9,
            photo_key="wa-photos/proj_a/w1/9.jpg", extra_photos=[]))
        db[punch.SESSIONS].rows.append({
            "_id": "w1", "items": [{"n": 1, "photo_key": "wa-photos/proj_a/w1/1.jpg",
                                    "message_id": "false_x_M1@c.us"}],
            "photos": [{"key": "wa-photos/proj_a/w1/1.jpg", "message_id": "false_x_M1@c.us"},
                       {"key": "wa-photos/proj_a/w1/2.jpg", "message_id": "false_x_M2@c.us"}]})
        r2 = {"wa-photos/proj_a/w1/1.jpg": THUMB, "wa-photos/proj_a/w1/2.jpg": FULL,
              "wa-photos/proj_a/w1/9.jpg": THUMB}
        fetched, up = [], []

        async def dl(p):
            fetched.append(p["message_id_serialized"])
            return FULL

        class R2:
            def get_object(self, Bucket, Key):
                return {"Body": io.BytesIO(r2[Key])}
        with patch.object(server, "download_image", dl), \
                patch.object(server, "_r2_client", R2()), \
                patch.object(server, "_upload_to_r2", lambda b, k, t: up.append(k) or k):
            bf.main(["--pid", "P-588-1", *argv], db=db, server=server)
        return db, fetched, up

    def test_a_run_stopped_after_the_walk_is_finished_by_the_next(self):
        # Codex review on #762: the walk is written first, the item last; a
        # failure in between leaves the item on its preview, and a rerun
        # finds its message through the walk's new key and finishes it.
        import scripts.punch_photo_backfill as bf
        db, _f, _u = self._run("--i-know", "--reason", "test", "--session", "s")
        row = db[punch.COLLECTION].rows[0]
        row["photo_key"] = "wa-photos/proj_a/w1/1.jpg"       # the item write was lost
        row.pop("photo_quality", None)                        # (one write: key and quality)
        fetched, up = [], []

        async def dl(p):
            fetched.append(p["message_id_serialized"])
            return FULL

        class R2:
            def get_object(self, Bucket, Key):
                return {"Body": io.BytesIO(FULL if Key.endswith("-full.jpg") or Key.endswith("2.jpg")
                                           else THUMB)}
        with patch.object(server, "download_image", dl), patch.object(server, "_r2_client", R2()), \
                patch.object(server, "_upload_to_r2", lambda b, k, t: up.append(k) or k):
            bf.main(["--pid", "P-588-1", "--i-know", "--reason", "t", "--session", "s"],
                    db=db, server=server)
        self.assertEqual(fetched, ["false_x_M1@c.us"])
        self.assertEqual(row["photo_key"], "wa-photos/proj_a/w1/1-full.jpg")

    def test_dry_run_reports_and_writes_nothing(self):
        db, fetched, up = self._run()
        self.assertEqual(fetched, ["false_x_M1@c.us"])   # the preview only; #2 is full
        self.assertEqual(up, [])
        self.assertEqual(db[punch.COLLECTION].rows[0]["photo_key"], "wa-photos/proj_a/w1/1.jpg")

    def test_applied_the_item_and_its_walk_point_at_the_original(self):
        db, _f, up = self._run("--i-know", "--reason", "test", "--session", "s")
        self.assertEqual(up, ["wa-photos/proj_a/w1/1-full.jpg"])
        row = db[punch.COLLECTION].rows[0]
        self.assertEqual(row["photo_key"], "wa-photos/proj_a/w1/1-full.jpg")
        self.assertEqual(row["extra_photos"], ["wa-photos/proj_a/w1/2.jpg"])
        walk = db[punch.SESSIONS].rows[0]
        self.assertEqual(walk["items"][0]["photo_key"], "wa-photos/proj_a/w1/1-full.jpg")
        self.assertEqual(walk["photos"][0]["key"], "wa-photos/proj_a/w1/1-full.jpg")
        self.assertEqual(db[punch.COLLECTION].rows[1]["photo_key"],
                         "wa-photos/proj_a/w1/9.jpg")          # not asked for


class PunchIsNotAttention(unittest.TestCase):

    def _db(self):
        db = FakeDb()
        db.projects.rows.append({"_id": "proj_a", "company_id": CO_A, "name": "588"})
        db.whatsapp_groups.rows.append({"_id": "g1", "wa_group_id": G_A, "project_id": "proj_a",
                                        "company_id": CO_A, "group_name": "588"})
        base = {"company_id": CO_A, "project_id": "proj_a", "group_id": G_A, "status": "open",
                "owner": {}, "due": {}, "evidence": {"quote": "q"}, "history": [], "review": None,
                "created_at": datetime(2026, 10, 12, tzinfo=timezone.utc)}
        db.attention_items.rows += [
            {**base, "_id": "punch1", "type": "request", "summary": "P-588-1: tile",
             "tags": ["punch"], "extraction": {"source": "punch"}, "punch_id": "P-588-1",
             "review": {"verdict": "wrong"}},
            {**base, "_id": "punch2", "type": "request", "summary": "P-588-2: paint",
             "tags": ["punch"], "extraction": {"source": "punch"}, "punch_id": "P-588-2"},
            {**base, "_id": "ai1", "type": "request", "summary": "send the RFI",
             "tags": [], "extraction": {"source": "live"}},
        ]
        return db

    def test_not_in_the_queue_nor_in_precision(self):
        db = self._db()
        with patch.object(server, "db", db):
            out = asyncio.run(server.get_project_attention("proj_a", status="all",
                                                           current_user=ADMIN))
        self.assertEqual([v["id"] for v in out["items"]], ["ai1"])
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["precision"]["request"]["wrong"], 0)
        self.assertEqual(len(db.attention_items.rows), 3)        # filtered, not deleted

    def test_a_punch_item_cannot_be_reviewed_there(self):
        db = self._db()
        from fastapi import HTTPException
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as e:
                asyncio.run(server.review_project_attention(
                    "proj_a", "punch2", {"verdict": "correct"}, current_user=ADMIN))
        self.assertEqual(e.exception.status_code, 404)
        self.assertIsNone(db.attention_items.rows[1]["review"])
