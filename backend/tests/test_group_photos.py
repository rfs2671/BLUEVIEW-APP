"""Photos posted in a linked job group are kept (lib/wa_photos.py).

  * A photo sent in a linked group, through the real webhook: the original is
    downloaded and stored in R2 under the company and the job, on its message
    row with the caption, who sent it and their company (People, or the
    company of their check-in at the job, or the GC team for a user), and
    what the vision model saw -- asked once, at ingest.
  * A group that is not linked: nothing downloaded, nothing stored.
  * The progress report picks group photos (from the stored verdict, never
    asking vision again), ahead of walkthrough photos; a preview-only photo
    is not a report photo.
  * The memory search reads its caption and what it shows; never the base64
    thumbnail an uncaptioned image carries as its body.
  * Retention and the project delete remove it from R2, by key; a punch
    completion photo it shares with a punch item is left to the item.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import progress_report as P, project_memory as pm, wa_photos  # noqa: E402
from tests import test_wa_retention as RT  # noqa: E402
from tests.test_memory_live_path import CO, GROUP, JOB, MEILICH, SAT_312PM, _Live, _payload  # noqa: E402

FRAMING = {"ok": True, "kind": "progress", "score": 8, "caption": "Metal stud framing on the 3rd floor"}


def _jpeg(w=1200, h=900):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (150, 160, 170)).save(out, "JPEG")
    return out.getvalue()


def _image(msg_id, caption="", author=MEILICH, at=SAT_312PM, group=GROUP):
    p = _payload(msg_id, caption, at=at, author=author)
    m = p["data"]["message"]
    m.update({"type": "image", "hasMedia": True, "from": group,
              # An image with no caption arrives with its base64 thumbnail
              # as the body.
              "body": caption or base64.b64encode(b"\xff\xd8" + b"t" * 300).decode()})
    m["id"]["remote"] = group
    m["_data"].update({"mediaKey": "k", "directPath": "/v/x", "mimetype": "image/jpeg"})
    return p


class _Capture:
    """R2 and the vision model, faked: what was uploaded, how often vision
    was asked."""

    def __init__(self, verdict=FRAMING, full=True):
        self.up, self.vision, self.verdict = {}, 0, verdict
        self.img = _jpeg() if full else None

    def patches(self):
        async def dl(parsed):
            return self.img

        async def judge(raw, project_id, endpoint):
            self.vision += 1
            self.endpoint = endpoint
            return dict(self.verdict) if self.verdict else None
        return [patch.object(server, "download_image", dl),
                patch.object(server, "_upload_to_r2", lambda b, k, t: self.up.__setitem__(k, b) or k),
                patch.object(server, "_r2_bytes", lambda k: self.up.get(k)),
                patch.object(server, "_photo_verdict", judge)]


def _send(w, cap, payload):
    ps = cap.patches()
    for p in ps:
        p.start()
    try:
        w.webhook(payload)
    finally:
        for p in reversed(ps):
            p.stop()


def _people(db, jid, company):
    db[server.wa_sender_map.COLLECTION].rows.append(
        {"_id": "sm1", "company_id": CO, "sender_jid": jid, "person_name": "Meilich",
         "sub_company": company})


class APhotoInTheGroupIsKept(unittest.TestCase):

    def test_stored_in_r2_and_tagged_with_the_sub(self):
        cap = _Capture()
        with _Live() as w:
            _people(w.db, f"{MEILICH}@c.us", "Arkon Builders")
            _send(w, cap, _image("IMG1", "3rd floor framing done"))
            row = next(r for r in w.db.whatsapp_messages.rows if r.get("message_id") == "IMG1")
        p = row["photo"]
        self.assertEqual(p["key"], f"wa-group-photos/{CO}/{JOB}/IMG1.jpg")
        self.assertIn(p["key"], cap.up)                                  # the original, in R2
        self.assertEqual((p["quality"], p["caption"], p["sender_company"], p["company_how"]),
                         ("original", "3rd floor framing done", "Arkon Builders", "people"))
        self.assertEqual(p["vision"], FRAMING)
        self.assertEqual((cap.vision, cap.endpoint), (1, server.VISION_GROUP_PHOTO))

    def test_a_worker_is_the_company_of_their_check_in(self):
        cap = _Capture()
        with _Live() as w:
            w.db.checkins.rows.append({"_id": "c1", "project_id": JOB, "company_id": CO,
                                       "worker_id": "w9", "worker_name": "Meilich",
                                       "worker_phone": MEILICH, "worker_company": "Power Direct",
                                       "check_in_time": SAT_312PM - timedelta(hours=6)})
            _send(w, cap, _image("IMG2"))
            row = next(r for r in w.db.whatsapp_messages.rows if r.get("message_id") == "IMG2")
        self.assertEqual((row["photo"]["sender_company"], row["photo"]["company_how"]),
                         ("Power Direct", "checkin"))
        self.assertEqual(row["photo"]["caption"], "")           # the thumbnail is not a caption

    def test_an_unlinked_group_stores_nothing(self):
        cap = _Capture()
        with _Live() as w:
            _send(w, cap, _image("IMG3", "framing", group="120363999999999999@g.us"))
            rows = [r for r in w.db.whatsapp_messages.rows if r.get("message_id") == "IMG3"]
        self.assertEqual((rows, cap.up, cap.vision), ([], {}, 0))

    def test_only_the_preview_is_kept_so_and_never_in_the_report(self):
        cap = _Capture(full=False)
        with _Live() as w, patch.object(server, "_webhook_thumbnail", lambda parsed: _jpeg(100, 75)):
            _send(w, cap, _image("IMG4", "framing"))
            row = next(r for r in w.db.whatsapp_messages.rows if r.get("message_id") == "IMG4")
        self.assertEqual(row["photo"]["quality"], server.PHOTO_PREVIEW)
        cands = P.photo_candidates([], [], date(2026, 10, 1), date(2026, 10, 31), [row])
        self.assertEqual(cands, [])

    def test_nothing_to_be_had_is_said(self):
        cap = _Capture(full=False)
        with _Live() as w, patch.object(server, "_webhook_thumbnail", lambda parsed: None):
            _send(w, cap, _image("IMG7", "framing"))
            row = next(r for r in w.db.whatsapp_messages.rows if r.get("message_id") == "IMG7")
        self.assertEqual((row["photo"]["key"], row["photo"]["failed"], cap.vision), (None, True, 0))
        self.assertEqual(wa_photos.log_row(row, who="x", place="", at="")["status"], "not_captured")


class TheReportPicksGroupPhotos(unittest.TestCase):

    def test_webhook_to_report(self):
        cap = _Capture()
        with _Live() as w:
            _people(w.db, f"{MEILICH}@c.us", "Arkon Builders")
            _send(w, cap, _image("IMG5", "framing 3rd floor"))
            project = {"_id": JOB, "company_id": CO, "address": "588 Thomas S Boyland St"}

            async def no_logs(*a, **k):
                return []
            rows = _run(server._report_rows(project, CO, date(2026, 10, 1), date(2026, 10, 14),
                                            SAT_312PM))
            rep = P.compute(job="588 Thomas S Boyland St", address="", gc="G", start=date(2026, 10, 1),
                            end=date(2026, 10, 14), now=SAT_312PM, **rows)
            asked = cap.vision
            with patch.object(server, "_photo_verdict", side_effect=AssertionError("asked again")):
                picked = _run(server._report_photos(rep, JOB))
        self.assertEqual([(c["source"], c["sub"]) for c in rep["photo_candidates"]],
                         [("group chat", "Arkon Builders")])
        self.assertEqual([p["key"] for p in picked], [f"wa-group-photos/{CO}/{JOB}/IMG5.jpg"])
        self.assertEqual(picked[0]["caption"], FRAMING["caption"])
        self.assertEqual(asked, 1)                              # only at ingest

    def test_ahead_of_walkthrough_photos(self):
        d = date(2026, 10, 6)
        at = datetime(2026, 10, 6, 15, tzinfo=timezone.utc)
        group = [{"message_id": f"G{i}", "timestamp": at,
                  "photo": {"key": f"wa-group-photos/c/p/G{i}.jpg", "quality": "original",
                            "caption": f"fl {i + 2}", "sender_company": "Arkon",
                            "vision": dict(FRAMING, score=7)}}
                 for i in range(2)]
        punch_items = [{"photo_key": f"wa-photos/p/s/{i}.jpg", "created_at": at, "floor": "3",
                        "text": "patch", "message_id": f"W{i}"} for i in range(2)]
        cands = P.photo_candidates([], punch_items, d, d, group)
        verdicts = {c["key"]: c.get("verdict") or dict(FRAMING, score=8) for c in cands}
        picked = P.pick_photos(cands, verdicts, most=2)
        self.assertEqual({p["source"] for p in picked}, {"group chat"})

    def test_the_same_photo_is_not_twice(self):
        d = date(2026, 10, 6)
        at = datetime(2026, 10, 6, 15, tzinfo=timezone.utc)
        group = [{"message_id": "M1", "timestamp": at,
                  "photo": {"key": "wa-group-photos/c/p/M1.jpg", "quality": "original", "vision": FRAMING}}]
        walk = [{"photo_key": "wa-photos/p/s/1.jpg", "created_at": at, "message_id": "M1", "text": "x"}]
        self.assertEqual([c["source"] for c in P.photo_candidates([], walk, d, d, group)], ["group chat"])


class MemorySearch(unittest.TestCase):

    def test_caption_and_what_it_shows_never_the_thumbnail(self):
        row = {"project_id": JOB, "sender": MEILICH, "media_type": "image",
               "body": "A" * 400, "photo": {"key": "k", "caption": "rear wall", "vision": FRAMING}}
        self.assertEqual(pm.message_text(row), "rear wall — Photo: Metal stud framing on the 3rd floor")
        self.assertTrue(pm.indexable_message(row))
        bare = {"project_id": JOB, "sender": MEILICH, "media_type": "image", "body": "A" * 400}
        self.assertFalse(pm.indexable_message(bare))           # no caption, no photo kept
        self.assertEqual(server._memory_wa_doc({**row, "_id": "r1"}, "588")["kind"], "photo")

    def test_indexed_first_then_its_words_grow(self):
        cap = _Capture()
        with _Live() as w:
            _send(w, cap, _image("IMG6", "rear wall"))
            w.tick()
            doc = next(d for d in w.db.project_memory.rows if d.get("message_id") == "IMG6")
        self.assertEqual(doc["text"], "rear wall — Photo: Metal stud framing on the 3rd floor")


class Deleted(unittest.TestCase):

    def test_retention_takes_the_photo_by_key(self):
        db = RT._world(completion="2019-03-01")
        db.whatsapp_messages.rows[0]["photo"] = {"key": "wa-group-photos/co1/p1/A.jpg"}
        db.whatsapp_messages.rows[1]["photo"] = {"key": "wa-photos/p1/msg/B.jpg", "shared": True}
        gone = []

        async def delete_keys(client, bucket, keys):
            gone.extend(keys)
            return len(keys)
        with patch.object(server, "_r2_client", object()), \
                patch.object(server, "_r2_delete_keys", delete_keys):
            RT._tick(db)
        self.assertEqual(gone, ["wa-group-photos/co1/p1/A.jpg"])   # never the punch item's

    def test_owned_keys(self):
        self.assertEqual(wa_photos.owned_keys({"photo": {"key": "wa-group-photos/a/b/c.jpg"}}),
                         ["wa-group-photos/a/b/c.jpg"])
        self.assertEqual(wa_photos.owned_keys({"photo": {"key": "wa-photos/b/msg/c.jpg", "shared": True}}), [])

    def test_the_project_delete_names_them(self):
        import inspect
        src = inspect.getsource(server.hard_delete_project)
        self.assertIn("wa_photos.owned_keys", src)


def _run(coro):
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
