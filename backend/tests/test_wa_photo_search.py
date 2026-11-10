"""EVERY DAILY-LOG PHOTO, SEARCHABLE BY WHAT IT SHOWS.

Nov 9, the owner, for an insurance file: "Any nice pics from the front of the
building". The assistant had "4 photo(s)" per crew and no way to look, and
answered that the logs record only counts. The images were all in R2.

Asserted here, the model scripted (tests/test_dm_brain.py's FakeLLM) and the
vision call stood in for: each filed photo is described once; a search finds
the front of the building and not the interior; the photo goes out through the
DM gate; and a photo from a withdrawn log or another job does not.

Not asserted, because no model runs here: how well the real vision model tells
a street face from a side wall (lib/photo_search.INDEX_PROMPT).

CONTROL: against origin/main's server.py, lib/dm_brain.py and lib/vision_meter.py
the sweep, the tools and the slow-notice wording all fail. The tests of the
pure search (TheSearch) exercise a new file and so pass on both.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

import server  # noqa: E402
from lib import photo_search, vision_meter  # noqa: E402

TODAY = datetime.now(timezone.utc).date()
DAY = (TODAY - timedelta(days=2)).isoformat()
FRONT, WALL, DRAFT = "k/front.jpg", "k/wall.jpg", "k/draft.jpg"
SAID = {
    FRONT: {"view": "building_front", "quality": 9.0, "tags": ["concrete", "frame", "sidewalk"],
            "description": "Six-story concrete frame seen from the street, sidewalk shed along it."},
    WALL: {"view": "interior", "quality": 9.5, "tags": ["framing", "studs"],
           "description": "Metal stud framing on an upper floor."},
}


def _jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (90, 90, 90)).save(out, "JPEG")
    return out.getvalue()


def _log(_id, photos, *, status="submitted", project=THOMAS, date=DAY, company="Arkon Builders"):
    return {"_id": _id, "log_type": "daily_jobsite", "project_id": project, "company_id": CO_A,
            "date": date, "status": status,
            "data": {"activities": [{"company": company, "work_locations": "Site",
                                     "photos": [{"enhanced_r2_key": k} for k in photos]}]}}


class _Vision:
    def __init__(self):
        self.calls = 0

    async def __call__(self, raw, project_id):
        self.calls += 1
        for key, v in SAID.items():
            if raw == key.encode():
                return dict(v)
        return None


def _sweep(vision=None, **kw):
    vision = vision or _Vision()
    with patch.object(server, "QWEN_API_KEY", "x"), \
            patch.object(server, "_photo_index_call", vision), \
            patch.object(server, "_report_photo_bytes", lambda c: c["key"].encode()):
        return _run(server._photo_index_tick(**kw))


def _photos(db):
    return [r for r in db[server.PHOTO_INDEX].rows if r.get("kind") == "photo"]


class TheSearch(unittest.TestCase):
    ROWS = [dict(v, short=k, date=DAY) for k, v in SAID.items()]

    def test_the_front_of_the_building_is_the_front(self):
        hits = photo_search.search(self.ROWS, "any nice pics from the front of the building")
        self.assertEqual([r["short"] for r in hits], [FRONT], "the better interior is not a match")

    def test_a_plural_finds_a_singular(self):
        self.assertEqual([r["short"] for r in photo_search.search(self.ROWS, "studs")], [WALL])
        self.assertEqual([r["short"] for r in photo_search.search(self.ROWS, "stud")], [WALL])

    def test_nothing_asked_is_the_best_photos_never_a_document_or_a_blurry_one(self):
        rows = self.ROWS + [dict(view="document", quality=10, description="a permit", short="d"),
                            dict(view="interior", quality=1, description="dark", short="b")]
        self.assertEqual([r["short"] for r in photo_search.search(rows)], [WALL, FRONT])

    def test_no_match_is_no_match(self):
        self.assertEqual(photo_search.search(self.ROWS, "crane"), [])

    def test_a_bad_answer_from_the_model_is_not_stored(self):
        for said in ("", "sorry", "[1]", '{"view": "roof"}', "{not json"):
            with self.subTest(said=said):
                self.assertIsNone(photo_search.parse_index(said))

    def test_the_answer_is_cleaned(self):
        v = photo_search.parse_index('x {"view":"Space","quality":99,"description":" a  wall ","tags":"no"} y')
        self.assertEqual(v, {"view": "other", "quality": 10.0, "description": "a wall", "tags": [],
                             "visible_text": [], "room_type": "unknown"})


class TheSweep(_Brain):

    def test_a_filed_photo_is_described_once_and_a_draft_never(self):
        self.db.logbooks.rows += [_log("L1", [FRONT, WALL]), _log("L2", [DRAFT], status="draft")]
        v = _Vision()
        with _Ctx(db=self.db):
            _sweep(v)
            _sweep(v)
        self.assertEqual(v.calls, 2, "two filed photos, once each")
        rows = {r["photo_key"]: r for r in _photos(self.db)}
        self.assertEqual(set(rows), {FRONT, WALL})
        self.assertEqual((rows[FRONT]["project_id"], rows[FRONT]["sub"], rows[FRONT]["log_id"]),
                         (THOMAS, "Arkon Builders", "L1"))
        self.assertEqual(rows[FRONT]["view"], "building_front")

    def test_a_tick_is_bounded(self):
        self.db.logbooks.rows.append(_log("L1", [FRONT, WALL]))
        v = _Vision()
        with _Ctx(db=self.db):
            out = _sweep(v, budget=1)
        self.assertEqual((v.calls, out["backlog"]), (1, 1))

    def test_a_photo_the_model_cannot_read_is_given_up_on(self):
        self.db.logbooks.rows.append(_log("L1", ["k/unreadable.jpg"]))
        v = _Vision()
        with _Ctx(db=self.db):
            for _ in range(server.PHOTO_INDEX_TRIES + 2):
                _sweep(v)
        self.assertEqual(v.calls, server.PHOTO_INDEX_TRIES)
        self.assertEqual(_photos(self.db), [])

    def test_the_history_is_read_a_slice_at_a_time(self):
        old = (TODAY - timedelta(days=server.PHOTO_INDEX_RECENT_DAYS + 3)).isoformat()
        older = (TODAY - timedelta(days=server.PHOTO_INDEX_RECENT_DAYS + 20)).isoformat()
        self.db.logbooks.rows += [_log("L1", [FRONT], date=old), _log("L2", [WALL], date=older)]
        with _Ctx(db=self.db):
            _sweep()
            self.assertEqual([r["photo_key"] for r in _photos(self.db)], [FRONT])
            _sweep()
        self.assertEqual({r["photo_key"] for r in _photos(self.db)}, {FRONT, WALL})

    def test_the_switch_stops_the_spend(self):
        self.db.logbooks.rows.append(_log("L1", [FRONT]))
        v = _Vision()
        with _Ctx(db=self.db), patch.dict("os.environ", {"PHOTO_INDEX_DISABLED": "1"}):
            _sweep(v)
        self.assertEqual(v.calls, 0)

    def test_it_is_scheduled_and_metered(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("id='photo_index'", src[src.index("async def startup_event"):])
        self.assertIn(server.VISION_PHOTO_INDEX, vision_meter.VISION_ENDPOINTS)
        body = src[src.index("async def _photo_index_call("):src.index("async def _photo_index_window(")]
        self.assertIn("await record_vision_call(", body)


class TheOwnersQuestion(_Brain):
    """What was asked on Nov 9, through the whole DM pipeline."""

    def _indexed(self, *logs):
        self.db.logbooks.rows += list(logs)
        _sweep()

    def _sent(self, c):
        return [p for p in c.wire.calls if "mediaUrl" in p]

    def _patches(self):
        async def url(chat, jpeg, ref):
            self.assertTrue(jpeg.startswith(b"\xff\xd8"), "a real JPEG goes out")
            return "https://media.test/p.jpg"
        return (patch.object(server, "_temp_jpeg_media_url", url),
                patch.object(server, "_report_photo_bytes", lambda c: _jpeg()))

    def _ask(self, c, ids=None, what="front of the building"):
        def pick(kw):
            self.found = json.loads(last_tool_results(kw)[0])
            chosen = ids or [m["id"] for m in self.found["matches"]] or ["none"]
            return resp(use("send_photos", {"job": "588", "ids": chosen}, "b"))

        def done(kw):
            self.result = last_tool_results(kw)[0]
            return resp(text("Sent you the street side of the building."))
        llm = FakeLLM(resp(use("find_photos", {"job": "588", "what": what}, "a")), pick, done)
        a, b = self._patches()
        with a, b:
            out = self.say(c, "Any nice pics from the front of the building", llm)
        self.llm = llm
        return out

    def test_it_finds_the_front_and_sends_it(self):
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", [FRONT, WALL]))
            out = self._ask(c)
            sent = self._sent(c)
        self.assertEqual([m["shows"] for m in self.found["matches"]], [SAID[FRONT]["description"]])
        self.assertEqual(self.found["photos_searched"], 2)
        self.assertEqual(len(sent), 1)
        self.assertIn("Arkon Builders", sent[0]["caption"])
        self.assertIn("Sent 1 photo(s)", self.result)
        self.assertEqual(out[-1], "Sent you the street side of the building.")

    def test_the_tools_and_the_instruction_reach_the_model(self):
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", [FRONT]))
            self._ask(c)
        names = {t["function"]["name"] for t in self.llm.calls[0]["tools"]}
        self.assertLessEqual({"find_photos", "send_photos"}, names)
        system = next(m["content"] for m in self.llm.calls[0]["messages"] if m["role"] == "system")
        self.assertIn("You CAN find and send daily-log photos", system)

    def test_a_withdrawn_log_is_not_sent(self):
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", [FRONT]))
            self.db.logbooks.rows[-1]["status"] = server.WITHDRAWN_STATUS
            self._ask(c)
            self.assertEqual(self._sent(c), [])
        self.assertIn("No photo was sent", self.result)

    def test_a_photo_taken_off_the_log_is_not_sent(self):
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", [FRONT]))
            self.db.logbooks.rows[-1]["data"]["activities"][0]["photos"] = []
            self._ask(c)
            self.assertEqual(self._sent(c), [])

    def test_another_jobs_photo_cannot_be_sent_by_its_id(self):
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", [WALL], project=WALWORTH), _log("L2", [FRONT]))
            other = next(r["short"] for r in _photos(self.db) if r["project_id"] == WALWORTH)
            self._ask(c, ids=[other])
            self.assertEqual(self._sent(c), [])
        self.assertNotIn(SAID[WALL]["description"], json.dumps(self.found))

    def test_at_most_four_go_out(self):
        keys = [f"k/{i}.jpg" for i in range(6)]
        for k in keys:
            SAID[k] = {"view": "building_front", "quality": 8.0, "description": f"Front {k}", "tags": []}
        self.addCleanup(lambda: [SAID.pop(k) for k in keys])
        with _Ctx(db=self.db) as c:
            self._indexed(_log("L1", keys))
            self._ask(c)
            self.assertEqual(len(self._sent(c)), server.PHOTO_SEND_MAX)
        self.assertIn("were not sent", self.result)

    def test_nothing_read_yet_says_so_in_the_numbers(self):
        with _Ctx(db=self.db):
            ctx = {"ident": {"company_id": CO_A}}
            out = json.loads(_run(server._dm_find_photos(ctx, {"id": THOMAS, "label": "588"}, {"what": "front"})))
        self.assertEqual((out["photos_searched"], out["matches"]), (0, []))

    def test_the_slow_notice_is_about_any_question(self):
        self.assertEqual(server.DM_SLOW_NOTICE_TEXT, "Still working on it.")


if __name__ == "__main__":
    unittest.main()
