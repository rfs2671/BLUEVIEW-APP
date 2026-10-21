"""A plans answer in a DM comes with where it came from, on the sheet.

The brain answers from search_plans records; each record says where on its
sheet it is (`bbox`, PDF points). After the words, the DM gets the page image
cropped to that region with it boxed in red (lib/plan_crop) -- every
candidate boxed and numbered when the answer could rest on more than one
place -- or the whole sheet, said so, when the record has no box (notes,
callouts: plan_records KNOWN GAP). The eval sends nothing and records it.
"""

from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from PIL import Image

import server  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _db, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

DPI = 250                                    # _render_dpi_for("A-set.pdf", n)
PAGE_PX = (12 * DPI, 9 * DPI)                # a 12x9 inch page as rendered

PAGES = [
    {"_id": "pgA", "project_id": THOMAS, "file_id": "f1", "file_name": "A-set.pdf",
     "page_number": 3, "sheet_number": "A-201", "sheet_title": "Mechanical Plan",
     "page_jpeg_r2_key": "plans/k/page_3.jpg"},
    {"_id": "pgN", "project_id": THOMAS, "file_id": "f1", "file_name": "A-set.pdf",
     "page_number": 1, "sheet_number": "S-001", "sheet_title": "General Notes",
     "page_jpeg_r2_key": "plans/k/page_1.jpg"},
]


def _rec(page_id, sheet, quote, bbox, ordinal=0, record_type="element"):
    return {"page_id": page_id, "project_id": THOMAS, "sheet_number": sheet,
            "file_name": "A-set.pdf", "page_number": 3, "record_type": record_type,
            "ordinal": ordinal, "quote": quote, "bbox": bbox, "tier": "tag_legend",
            "source": "text_layer", "verified": True}


# 720..792 x 432..468 pt = 2500..2750 x 1500..1625 px at 250 DPI
FAN = _rec("pgA", "A-201", "EF-3 EXHAUST FAN 800 CFM", [720, 432, 792, 468])
FAN_TOO = _rec("pgA", "A-201", "EF-3 EXHAUST FAN 800 CFM", [72, 72, 144, 108], ordinal=1)
NOTE = _rec("pgN", "S-001", "ALL FIRESTOPPING PER UL SYSTEMS", None, record_type="note")


def _page_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", PAGE_PX, (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def _red_pixels(img):
    small = img.convert("RGB").resize((img.width // 4, img.height // 4))
    return sum(1 for r, g, b in small.getdata() if r > 180 and g < 90 and b < 90)


class _Plans(_Brain):
    def setUp(self):
        super().setUp()
        self.db.document_page_index.rows.extend(dict(p) for p in PAGES)
        self.uploads = {}
        self.fetched = []

    def patches(self, records):
        async def search(project_id, subject, **kw):
            return [dict(r) for r in records]

        async def fetch(page):
            self.fetched.append(page.get("sheet_number"))
            return _page_jpeg()

        def upload(data, key, content_type="application/octet-stream"):
            self.uploads[key] = data
            return f"https://r2.test/{key}"

        async def named(project_id, sheet_q):
            return [dict(p) for p in PAGES if p["sheet_number"] == sheet_q.upper()]
        return [patch.object(server, "search_plans", search),
                patch.object(server, "_fetch_page_jpeg", fetch),
                patch.object(server, "_upload_to_r2", upload),
                patch.object(server, "_find_named_sheet", named)]

    def ask(self, c, body, llm, records):
        ps = self.patches(records)
        for p in ps:
            p.start()
        try:
            return self.say(c, body, llm)
        finally:
            for p in reversed(ps):
                p.stop()

    def images(self, c):
        """[(caption, PIL image)] in the order they went out."""
        out = []
        for p in c.wire.calls:
            if "mediaUrl" not in p:
                continue
            token = p["mediaUrl"].rsplit("/", 1)[-1]
            row = next(r for r in self.db.temp_media_tokens.rows if r["token"] == token)
            out.append((p["caption"], Image.open(io.BytesIO(self.uploads[row["r2_key"]]))))
        return out

    @staticmethod
    def order(c):
        return ["text" if "message" in p else "image" for p in c.wire.calls
                if "message" in p or "mediaUrl" in p]


def _search_then(answer, subject="exhaust fan"):
    def check(kw):
        res = last_tool_results(kw)[0]
        assert "No need to call send_sheet" in res, res
        return resp(text(answer))
    return FakeLLM(resp(use("search_plans", {"job": "588", "subject": subject})), check)


class TheAnswerComesWithWhereItCameFrom(_Plans):
    def test_one_record_with_a_box_is_a_marked_crop_after_the_words(self):
        answer = "EF-3 is an exhaust fan, 800 CFM — on A-201."
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "what's EF-3 on 588", _search_then(answer), [FAN])
            imgs = self.images(c)
            order = self.order(c)
        self.assertEqual(out, [answer])
        self.assertEqual(order, ["text", "image"])                      # words first
        self.assertEqual([cap for cap, _i in imgs], ["A-201 — where this comes from"])
        img = imgs[0][1]
        self.assertLess(img.width, PAGE_PX[0])                          # a crop, not the page
        self.assertLess(img.height, PAGE_PX[1])
        self.assertGreater(_red_pixels(img), 0)                         # the box is drawn
        self.assertTrue(all(k.startswith("temp/whatsapp/dm/") for k in self.uploads))
        self.assertTrue(any(r.get("body") == "[Sheet] A-201 — where this comes from"
                            for r in self.db.whatsapp_messages.rows))

    def test_two_candidate_spots_are_both_marked_and_it_asks_which(self):
        answer = "EF-3 is the exhaust fan on A-201."
        with _Ctx(db=self.db) as c:
            self.ask(c, "where's EF-3 on 588", _search_then(answer), [FAN, FAN_TOO])
            imgs = self.images(c)
        self.assertEqual([cap for cap, _i in imgs], ["2 possible spots on A-201 — which one?"])
        # Both boxes are in the one picture: it spans from one (x 250 px)
        # to the other (x 2750 px).
        self.assertGreaterEqual(imgs[0][1].width, 2750 - 250)
        self.assertGreater(_red_pixels(imgs[0][1]), 0)

    def test_a_record_with_no_box_sends_the_whole_sheet_and_says_so(self):
        answer = "Firestopping is per UL systems — S-001."
        with _Ctx(db=self.db) as c:
            self.ask(c, "firestopping on 588?", _search_then(answer, "firestopping"), [NOTE])
            imgs = self.images(c)
        self.assertEqual([cap for cap, _i in imgs],
                         ["S-001 General Notes — full sheet (the exact spot isn't marked in the index)"])
        self.assertEqual(imgs[0][1].size, PAGE_PX)

    def test_send_sheet_and_the_answer_picture_are_one_image(self):
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "exhaust fan"}, "a")),
                      resp(use("send_sheet", {"job": "588", "sheet": "A-201"}, "b")),
                      resp(text("Sent you A-201: EF-3 is the 800 CFM exhaust fan.")))
        with _Ctx(db=self.db) as c:
            self.ask(c, "show me EF-3 on 588", llm, [FAN])
            imgs = self.images(c)
        self.assertEqual(len(imgs), 1)
        cap, img = imgs[0]
        self.assertEqual(cap, "A-201 — where this comes from")          # send_sheet's, marked
        self.assertLess(img.width, PAGE_PX[0])
        self.assertGreater(_red_pixels(img), 0)

    def test_a_failed_picture_leaves_the_answer_standing(self):
        answer = "EF-3 is an exhaust fan, 800 CFM — on A-201."

        async def broken(page):
            raise RuntimeError("r2 down")
        with _Ctx(db=self.db) as c, patch.object(server, "_dm_plan_picture", broken):
            out = self.ask(c, "what's EF-3 on 588", _search_then(answer), [FAN])
            imgs = self.images(c)
        self.assertEqual(out, [answer])
        self.assertEqual(imgs, [])

    def test_a_false_sent_the_report_is_still_caught(self):
        """The coming picture makes "sent" true of the picture only: a
        "sent you the report" with no send_report this turn is rewritten."""
        bad = "EF-3 is the 800 CFM exhaust fan on A-201. I've sent you the September report too."
        good = "EF-3 is an exhaust fan, 800 CFM — on A-201."
        seen = []

        def second(kw):
            seen.append(kw["messages"][-1]["content"])
            return resp(text(good))
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "exhaust fan"})),
                      resp(text(bad)), second)
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "what's EF-3 on 588", llm, [FAN])
        self.assertEqual(out, [good])
        self.assertIn("no tool this turn", seen[0])

    def test_no_plans_search_no_picture(self):
        with _Ctx(db=self.db) as c:
            self.ask(c, "hi", FakeLLM(resp(text("Hi — what do you need?"))), [FAN])
            imgs = self.images(c)
        self.assertEqual(imgs, [])


class TheEvalSendsNothing(unittest.TestCase):
    def test_dry_run_records_the_sheet_and_sends_nothing(self):
        db = _db()
        db.document_page_index.rows.extend(dict(p) for p in PAGES)
        ident = {"user": {"name": "Admin"}, "user_id": "u_admin", "company_id": CO_A,
                 "role": "admin", "projects": [p for p in db.projects.rows
                                               if p["_id"] in (THOMAS, WALWORTH)]}
        uploads, fetched = [], []

        async def search(project_id, subject, **kw):
            return [dict(FAN)]

        async def fetch(page):
            fetched.append(page)
            return _page_jpeg()
        llm = _search_then("EF-3 is an exhaust fan, 800 CFM — on A-201.")
        with _Ctx(db=db) as c, patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "search_plans", search), \
                patch.object(server, "_fetch_page_jpeg", fetch), \
                patch.object(server, "_upload_to_r2", lambda *a, **k: uploads.append(a)):
            out = _run(server._dm_brain_answer(ident, CHAT, "what's EF-3 on 588", history=[],
                                               now=datetime.now(timezone.utc), dry_run=True,
                                               flows=[], active=None))
        self.assertEqual(out["sent"], ["[sheet A-201]"])
        self.assertEqual([s["label"] for s in out["plan_shots"]], ["A-201"])
        self.assertEqual((c.wire.calls, uploads, fetched), ([], [], []))


if __name__ == "__main__":
    unittest.main()
