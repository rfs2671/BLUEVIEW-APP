"""Live 588, Mon Oct 12, 10:44 AM: P-588-4's photo was not on the assignee's
page at all, and P-588-1..3 were still WhatsApp's blurry preview.

WaAPI's download-media answered with the message -- its ~100 px preview in
the body -- and no media. Before #762 that preview was kept; since, it was
refused and nothing was kept. Now the original is fetched from WhatsApp's
own CDN: the encrypted file at the message's directPath (from the webhook),
checked against its encFilehash, decrypted with its mediaKey, checked
against its filehash. WaAPI is the second try. If no original can be had,
the preview is kept and labelled "Original unavailable — preview only".
Stored previews are repaired once at startup (or labelled).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
from lib import punch, punch_link  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

KEY = base64.b64encode(bytes(range(32, 64))).decode()
PATH = "/v/t62.7118-24/19283746_1029384756_n.enc?ccb=11-4&oh=01_Q5&oe=6733&_nc_sid=5e03e0"
NOW = datetime(2026, 10, 12, 14, 44, tzinfo=timezone.utc)          # 10:44 AM New York


def _jpeg(w, h, c=(120, 60, 30)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), c).save(b, "JPEG", quality=90)
    return b.getvalue()


FULL = _jpeg(1600, 1200)
THUMB = _jpeg(96, 72, (5, 5, 5))


def _b64(b):
    return base64.b64encode(b).decode()


def _sha(b):
    return base64.b64encode(hashlib.sha256(b).digest()).decode()


def _encrypt(plain: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    keys = HKDF(algorithm=hashes.SHA256(), length=112, salt=b"\x00" * 32,
                info=b"WhatsApp Image Keys").derive(base64.b64decode(KEY))
    pad = 16 - len(plain) % 16
    enc = Cipher(algorithms.AES(keys[16:48]), modes.CBC(keys[0:16])).encryptor()
    return enc.update(plain + bytes([pad]) * pad) + enc.finalize() + b"\x07" * 10


ENC = _encrypt(FULL)


def _webhook_photo(caption="tile cracked 4D", mid="3EB0P4"):
    """What WaAPI posts for the 10:44 photo: the preview in the body, and the
    encrypted original's path and key in _data."""
    data = {"type": "image", "body": _b64(THUMB), "caption": caption, "mediaKey": KEY,
            "directPath": PATH, "deprecatedMms3Url": "https://mmg.whatsapp.net" + PATH,
            "encFilehash": _sha(ENC), "filehash": _sha(FULL), "mimetype": "image/jpeg",
            "size": len(FULL)}
    return {"has_image": True, "message_id": mid,
            "message_id_serialized": f"false_17185550100@c.us_{mid}", "body": caption,
            "raw": {"id": {"id": mid}, "type": "image", "_data": data}}


class _Resp:
    def __init__(self, status, j=None, content=b"x"):
        self.status_code, self._j, self.content = status, j or {}, content

    def json(self):
        return self._j


def _net(cdn=None, waapi=None):
    """GET: WhatsApp's CDN. POST: WaAPI download-media (live: the message,
    its preview in the body, no media)."""
    calls = {"get": [], "post": []}
    waapi = waapi if waapi is not None else {"data": {"status": "success", "data": {
        "message": {"_data": {"body": _b64(THUMB), "type": "image"}}}}}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            calls["get"].append(url)
            return cdn if cdn is not None else _Resp(200, content=ENC)

        async def post(self, url, json=None, **k):
            calls["post"].append(json)
            return _Resp(200, waapi)
    return C, calls


def _run(fn, db, C, uploads):
    async def no_sleep(*a, **k):
        return None
    with patch.object(server, "db", db), patch.object(server, "ServerHttpClient", C), \
            patch.object(server, "WAAPI_INSTANCE_ID", "inst"), \
            patch.object(server, "WAAPI_TOKEN", "tok"), \
            patch.object(server.asyncio, "sleep", no_sleep), \
            patch.object(server, "_upload_to_r2", lambda b, k, t: uploads.append((k, b)) or k):
        return asyncio.run(fn())


def _walk_db():
    db = FakeDb()
    db[punch.SESSIONS].rows.append({"_id": "w588", "user_id": "u_roy", "project_id": "p588",
                                    "status": "capturing", "items": [], "photos": []})
    return db


class TheTenFortyFourPhoto(unittest.TestCase):

    def capture(self, **net):
        db = _walk_db()
        sess = dict(db[punch.SESSIONS].rows[0], items=[], photos=[])
        C, calls = _net(**net)
        up = []
        it = _run(lambda: server._punch_photo_item(sess, _webhook_photo(), "tile cracked 4D",
                                                   None, "false_17185550100@c.us_3EB0P4", NOW),
                  db, C, up)
        return it, up, calls, db

    def test_the_original_from_whatsapps_cdn_when_waapi_has_only_the_preview(self):
        it, up, calls, db = self.capture()
        self.assertEqual(up, [("wa-photos/p588/w588/1.jpg", FULL)])     # 1600x1200, not 96x72
        self.assertEqual(it["photo_key"], "wa-photos/p588/w588/1.jpg")
        self.assertEqual(it["photo_quality"], "original")
        self.assertEqual(calls["get"], ["https://mmg.whatsapp.net" + PATH])
        self.assertEqual(calls["post"], [])                       # WaAPI not needed
        rec = it["photo_capture"]
        self.assertEqual((rec["source"], rec["px"], rec["cdn"]), ("whatsapp_cdn", [1600, 1200], "ok"))
        self.assertEqual(it["media_ref"]["directPath"], PATH)     # to fetch it again later
        walk = db[punch.SESSIONS].rows[0]
        self.assertEqual(walk["photos"][0]["quality"], "original")

    def test_cdn_gone_and_waapi_only_a_preview_keeps_the_preview_labelled(self):
        it, up, calls, _db = self.capture(cdn=_Resp(404, content=b""))
        self.assertEqual(up, [("wa-photos/p588/w588/1.jpg", THUMB)])
        self.assertEqual(it["photo_quality"], "preview")          # never no photo at all
        rec = it["photo_capture"]
        self.assertEqual(rec["source"], "webhook_preview")
        self.assertEqual(rec["cdn"], "status 404")
        self.assertEqual(len(rec["waapi"]), len(server._PHOTO_TRIES))
        self.assertIn("no full-size photo", rec["waapi"][0])

    def test_a_file_that_does_not_match_its_hash_is_not_the_photo(self):
        it, up, _c, _db = self.capture(cdn=_Resp(200, content=_encrypt(THUMB)))
        self.assertEqual(it["photo_quality"], "preview")
        self.assertEqual(it["photo_capture"]["cdn"], "the file did not match its hash")

    def test_the_app_and_the_assignee_page_say_preview_only(self):
        row = {"pid": "P-588-4", "status": "open", "text": "Tile cracked", "photo_key": "k",
               "photo_quality": "preview", "assignee": {}, "history": []}
        view = server._punch_view(row)
        self.assertEqual(view["photo_quality"], "preview")
        html = punch_link.page(name="Chris", job="588", tok="t.s",
                               items=[{**row, "photos": 1}])
        self.assertIn("Original unavailable — preview only", html)
        html = punch_link.page(name="Chris", job="588", tok="t.s",
                               items=[{**row, "photo_quality": "original", "photos": 1}])
        self.assertNotIn("preview only", html)

    def test_a_completion_photo_is_the_original_too(self):
        db = FakeDb()
        db[punch.COLLECTION].rows.append({
            "_id": "p588:P-588-4", "pid": "P-588-4", "seq": 4, "project_id": "p588",
            "company_id": "co", "status": "open", "sent_via": "dm", "history": [],
            "assignee": {"kind": "sender_map", "id": "m", "name": "Chris", "jid": "17185550199@c.us"}})
        C, _calls = _net()
        up = []
        p = _webhook_photo(caption="done P-588-4", mid="3EB0D4")
        reply = _run(lambda: server._punch_dm_done_by_number(
            "17185550199@c.us", punch.parse_done_ref("done P-588-4"), p), db, C, up)
        self.assertEqual(reply, "P-588-4 marked done — ready to check.")
        comp = db[punch.COLLECTION].rows[0]["completion"]
        self.assertEqual((comp["photo_key"], comp["photo_quality"]),
                         ("wa-photos/p588/msg/3EB0D4.jpg", "original"))
        self.assertEqual(up[0][1], FULL)
        # How it was captured, and where WhatsApp keeps it, are kept with it
        # (Codex review on #765).
        self.assertEqual(comp["photo_capture"]["source"], "whatsapp_cdn")
        self.assertEqual(comp["media_ref"]["directPath"], PATH)

    def test_a_preview_completion_keeps_its_record_and_the_diag_shows_it(self):
        db = FakeDb()
        db[punch.COLLECTION].rows.append({
            "_id": "p588:P-588-4", "pid": "P-588-4", "seq": 4, "project_id": "p588",
            "company_id": "co", "status": "open", "sent_via": "dm", "history": [],
            "assignee": {"kind": "sender_map", "id": "m", "name": "Chris", "jid": "17185550199@c.us"}})
        C, _calls = _net(cdn=_Resp(404, content=b""))
        _run(lambda: server._punch_dm_done_by_number(
            "17185550199@c.us", punch.parse_done_ref("done P-588-4"),
            _webhook_photo(caption="done P-588-4", mid="3EB0D4")), db, C, [])
        comp = db[punch.COLLECTION].rows[0]["completion"]
        self.assertEqual(comp["photo_quality"], "preview")
        self.assertEqual(comp["photo_capture"]["cdn"], "status 404")
        self.assertEqual(comp["media_ref"]["mediaKey"], KEY)      # to try again after 30 days
        import scripts.punch_photo_diag as diag

        class R2:
            def get_object(s, Bucket, Key):
                return {"Body": io.BytesIO(THUMB)}
        out = []
        with patch.object(server, "_r2_client", R2()), patch("builtins.print", out.append):
            diag.main(["--pid", "P-588-4"], db=db, server=server)
        text = "\n".join(out)
        self.assertIn("WhatsApp CDN: status 404", text)
        self.assertIn("captured from: webhook_preview, 96x72", text)       # the done photo's record
        self.assertNotIn(KEY, text)


class RepairingP588OneToThree(unittest.TestCase):
    """P-588-1..3 were stored on Oct 11 as the preview. Repaired once at
    startup: fetched again from the CDN (the media reference from the
    webhook log), or labelled "preview only" when it cannot be had."""

    def setUp(self):
        self.db = FakeDb()
        rows = self.db[punch.COLLECTION].rows
        for n in (1, 2, 3):
            rows.append({"_id": f"p588:P-588-{n}", "pid": f"P-588-{n}", "seq": n,
                         "project_id": "p588", "walk_id": "w831",
                         "photo_key": f"wa-photos/p588/w831/{n}.jpg", "history": []})
        self.db[punch.SESSIONS].rows.append({"_id": "w831", "items": [], "photos": [
            {"key": f"wa-photos/p588/w831/{n}.jpg", "message_id": f"false_17185550100@c.us_3EB0A{n}"}
            for n in (1, 2, 3)]})
        # The webhook log still has #1's message (30 days); #2's is gone; #3 is full already.
        body = ('{"event":"message","data":{"message":{"id":{"id":"3EB0A1"},"_data":{'
                f'"body":"{_b64(THUMB)[:50]}","mediaKey":"{KEY}","directPath":"{PATH}",'
                f'"encFilehash":"{_sha(ENC)}","filehash":"{_sha(FULL)}"')     # cut at 4000 chars
        self.db.whatsapp_webhook_log.rows.append({"raw_body_preview": body})
        self.r2 = {"wa-photos/p588/w831/1.jpg": THUMB, "wa-photos/p588/w831/2.jpg": THUMB,
                   "wa-photos/p588/w831/3.jpg": FULL}

    def run_startup(self):
        C, calls = _net()
        up = []

        class R2:
            def get_object(s, Bucket, Key):
                return {"Body": io.BytesIO(self.r2[Key])}
        with patch.object(server, "_r2_client", R2()):
            _run(server._punch_photo_repair_startup, self.db, C, up)
        return up, calls

    def test_once_at_startup(self):
        up, calls = self.run_startup()
        rows = {r["pid"]: r for r in self.db[punch.COLLECTION].rows}
        self.assertEqual(rows["P-588-1"]["photo_key"], "wa-photos/p588/w831/1-full.jpg")
        self.assertEqual(rows["P-588-1"]["photo_quality"], "original")
        self.assertEqual(up, [("wa-photos/p588/w831/1-full.jpg", FULL)])
        self.assertEqual(rows["P-588-2"]["photo_quality"], "preview")       # labelled, kept
        self.assertEqual(rows["P-588-2"]["photo_key"], "wa-photos/p588/w831/2.jpg")
        self.assertEqual(rows["P-588-3"]["photo_quality"], "original")      # nothing to do
        self.assertEqual(self.db[punch.SESSIONS].rows[0]["photos"][0]["key"],
                         "wa-photos/p588/w831/1-full.jpg")
        again, _ = self.run_startup()                                       # once
        self.assertEqual(again, [])

    def test_a_merged_in_photo_is_repaired_with_its_own_quality(self):
        # Codex review on #765: P-588-3 took #1's photo in a merge; the extra
        # photo is a preview the startup repair never looked at.
        rows = {r["pid"]: r for r in self.db[punch.COLLECTION].rows}
        rows["P-588-3"]["extra_photos"] = ["wa-photos/p588/w831/1.jpg"]
        rows["P-588-3"]["photo_quality"] = "original"
        self.db[punch.COLLECTION].rows.remove(rows["P-588-1"])
        up, _calls = self.run_startup()
        r3 = rows["P-588-3"]
        self.assertEqual(r3["extra_photos"], ["wa-photos/p588/w831/1-full.jpg"])
        self.assertEqual(r3["extra_quality"], ["original"])
        self.assertIn(("wa-photos/p588/w831/1-full.jpg", FULL), up)
        again, _ = self.run_startup()                                       # once
        self.assertEqual(again, [])
        view = server._punch_view(r3)
        self.assertEqual(view["extra_quality"], ["original"])

    def test_a_merged_in_preview_is_labelled_on_its_own(self):
        rows = {r["pid"]: r for r in self.db[punch.COLLECTION].rows}
        rows["P-588-3"]["extra_photos"] = ["wa-photos/p588/w831/2.jpg"]     # no original to be had
        self.run_startup()
        r3 = rows["P-588-3"]
        self.assertEqual((r3["photo_quality"], r3["extra_quality"]), ("original", ["preview"]))
        items = server._punch_link_items([{**r3, "status": "open"}])
        html = punch_link.page(name="Chris", job="588", tok="t.s", items=items)
        self.assertEqual(html.count("Original unavailable — preview only"), 1)
        self.assertLess(html.index("/photo/P-588-3/2"), html.index("preview only"))

    def test_a_merge_carries_each_photos_quality(self):
        a = {"n": 1, "text": "Tile", "photo_key": "k1", "photo_quality": "original"}
        b = {"n": 2, "text": "Grout", "photo_key": "k2", "photo_quality": "preview"}
        ok, _ = punch.apply_edit([a, b], {"op": "merge", "a": 1, "b": 2}, next_n=3)
        self.assertTrue(ok)
        self.assertEqual((a["extra_photos"], a["extra_quality"]), (["k2"], ["preview"]))

    def test_the_view_labels_the_ones_without_an_original(self):
        self.run_startup()
        views = {r["pid"]: server._punch_view(r) for r in self.db[punch.COLLECTION].rows}
        self.assertEqual(views["P-588-2"]["photo_quality"], "preview")
        self.assertEqual(views["P-588-1"]["photo_quality"], "original")

    def test_the_diag_says_what_happened(self):
        import scripts.punch_photo_diag as diag
        rows = self.db[punch.COLLECTION].rows
        rows[1]["photo_capture"] = {"source": "webhook_preview", "cdn": "status 404",
                                    "waapi": ["answer had other 2 KB 96x72: no full-size photo"]}

        class R2:
            def get_object(s, Bucket, Key):
                return {"Body": io.BytesIO(self.r2[Key])}
        out = []
        with patch.object(server, "_r2_client", R2()), patch("builtins.print", out.append):
            diag.main(["--pid", "P-588-2"], db=self.db, server=server)
        text = "\n".join(out)
        self.assertIn("R2 key wa-photos/p588/w831/2.jpg", text)
        self.assertIn("96x72", text)
        self.assertIn("PREVIEW size", text)
        self.assertIn("WhatsApp CDN: status 404", text)
        self.assertIn("WaAPI try 1: answer had other 2 KB 96x72", text)
        self.assertNotIn(KEY, text)
