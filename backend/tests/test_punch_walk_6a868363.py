"""The repair dry run of walk 6a868363 (588) misread it (Wed Oct 14).

1. "Correction. 3rd floor interior" + "Last 3 photos" (11:52, one message
   split in two) hit 8 photos (#1, 6, 7, 9-13) and set "Correction" as their
   description. Texts within 60 s with nothing between them are ONE
   annotation: the last 3 photos -> Floor 3 · interior. "Correction" is never
   a description.
2. "1st floor", "Back of building is location" (12:02-12:03, after "Done",
   answering "Where is #3 'Back of building'?") went to #41-44. They are #3's.
3. "Same for the last batch of pics" (11:59): placed by the model, else listed
   under "Couldn't place -- tell me which photos" -- never guessed or dropped.
4. A caption that is only a place ("Cellar", "Back of building", "Backyard",
   "5th floor staircase", "Front") is the location; the description comes
   from vision "(auto)". "Roof missing coping" -> Roof · "Missing coping".
5. Floor + area ("Floor 3 · interior"), never a group named "3rd interior";
   the draft by floor, then area.
6. The dry run shows the vision descriptions, "(auto)".
7. The 11:46 / 11:47 voice notes: what they said, and where they went.

THE MESSAGES. Rebuilt from the dry run's report of this walk: every text,
time and question above is as reported; the photo counts between them are
not known here. `scripts/repair_punch_walk.py --walk 6a868363 --dump-events
walk.json` writes the exact log; saved as tests/fixtures/punch_walk_6a868363.json
it replaces TIMELINE below (the same checks run on it).
"""

from __future__ import annotations

import json
import re
import unittest
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import punch, punch_batch  # noqa: E402
from tests.test_punch_batch_588 import _Batch, _seen  # noqa: E402
from tests.test_punch_walkthrough_2031 import CHAT, CO  # noqa: E402

NY = ZoneInfo("America/New_York")
FIXTURE = Path(__file__).parent / "fixtures" / "punch_walk_6a868363.json"


def _t(h, m, s=0):
    return datetime(2026, 10, 14, h, m, s, tzinfo=NY)


#: (time, kind, caption / text / transcript). A photo's caption is its own.
TIMELINE = [
    (_t(11, 40, 0), "photo", "Cellar"),                     # 1
    (_t(11, 40, 30), "photo", ""),                          # 2
    (_t(11, 41, 0), "photo", "Back of building"),           # 3
    (_t(11, 41, 30), "photo", ""),                          # 4
    (_t(11, 42, 0), "photo", ""),                           # 5
    (_t(11, 42, 30), "photo", ""),                          # 6
    (_t(11, 43, 0), "photo", ""),                           # 7
    (_t(11, 43, 30), "photo", ""),                          # 8
    (_t(11, 46, 10), "voice", "Sheetrock not finished in the hallway"),
    (_t(11, 47, 5), "voice", "Missing outlet covers"),
    (_t(11, 48, 0), "photo", ""),                           # 9
    (_t(11, 49, 0), "photo", ""),                           # 10
    (_t(11, 50, 0), "photo", ""),                           # 11
    (_t(11, 50, 30), "photo", ""),                          # 12
    (_t(11, 51, 0), "photo", ""),                           # 13
    (_t(11, 52, 5), "text", "Correction. 3rd floor interior"),
    (_t(11, 52, 40), "text", "Last 3 photos"),
    (_t(11, 54, 0), "photo", "Backyard"),                   # 14
    (_t(11, 54, 30), "photo", ""),                          # 15
    (_t(11, 55, 0), "photo", "5th floor staircase"),        # 16
    (_t(11, 55, 30), "photo", ""),                          # 17
    (_t(11, 56, 0), "photo", "Front"),                      # 18
    (_t(11, 56, 30), "photo", ""),                          # 19
    (_t(11, 57, 0), "photo", "Roof missing coping"),        # 20
    (_t(11, 58, 0), "text", "Compound and sheetrock not done"),
    (_t(11, 59, 0), "text", "Same for the last batch of pics"),
] + [(_t(12, 0, 0) + timedelta(seconds=2 * i), "photo", "") for i in range(24)] + [  # 21-44
    (_t(12, 1, 0), "text", "Done"),
    (_t(12, 1, 20), "bot", "Where is #3 'Back of building'? (floor + unit, or a named area)"),
    (_t(12, 2, 10), "text", "1st floor"),
    (_t(12, 3, 30), "text", "Back of building is location"),
]


def _timeline():
    """The exact log when it is saved; else the rebuilt one."""
    if FIXTURE.exists():
        rows = json.loads(FIXTURE.read_text())
        return [(datetime.fromisoformat(r["at"]), r["kind"], r.get("text") or "") for r in rows]
    return TIMELINE


def _old_walk():
    """The walk as the old rule left it: each text and voice note was the
    last photo's words (its caption_ids say so), the 11:47 voice note an
    item of its own; sent in shadow."""
    items, events = [], []
    n = 0
    for i, (at, kind, said) in enumerate(_timeline()):
        mid = f"false_{CHAT}_E{i:03d}"
        if kind == "photo":
            n += 1
            it = {"n": n, "captured": n, "photo_key": f"wa-photos/p588/w6a/{n:03d}.jpg",
                  "message_id": mid, "floor": punch.UNKNOWN, "area": punch.UNKNOWN,
                  "trade": punch.UNKNOWN, "trade_guess": False, "at": at, "text": ""}
            if said:
                fresh = punch.new_item(n, said, photo_key=it["photo_key"], message_id=mid)
                it.update({k: fresh[k] for k in ("text", "floor", "area", "trade", "trade_guess")},
                          caption_ids=[mid])
            items.append(it)
            events.append({"kind": "photo", "message_id": mid, "at": at, "text": "", "quoted": ""})
        elif kind == "bot":
            events.append({"kind": "bot", "message_id": "", "at": at, "text": said, "quoted": ""})
        elif kind == "voice":
            events.append({"kind": "voice", "message_id": mid, "at": at, "text": "", "quoted": ""})
            if at.minute == 47:
                items.append({"n": 90, "captured": n + 0.5, "photo_key": None, "message_id": mid,
                              "text": said, "voice": {"transcript": said, "lang": "en"},
                              "floor": punch.UNKNOWN, "area": punch.UNKNOWN, "trade": punch.UNKNOWN})
            else:
                last = items[-1]
                last.update(text=said, voice={"transcript": said, "lang": "en"},
                            caption_ids=[mid])
        else:
            events.append({"kind": "text", "message_id": mid, "at": at, "text": said, "quoted": ""})
            if said.lower() != "done" and n:
                last = [it for it in items if it.get("photo_key")][-1]
                if last.get("text"):
                    # The last photo had its own caption: the text became an
                    # item of its own (no photo) -- the repair removes it.
                    items.append({"n": 100 + i, "captured": n + 0.5, "photo_key": None,
                                  "message_id": mid, "text": said, "floor": punch.UNKNOWN,
                                  "area": punch.UNKNOWN, "trade": punch.UNKNOWN})
                else:
                    last.update(text=said, caption_ids=[mid])
    sess = {"_id": "w6a8", "user_id": "u_roy", "company_id": CO, "chat": CHAT, "project_id": "p588",
            "job_name": "588 Thomas St", "job_code": "588", "status": "sent", "items": items,
            "created_at": _t(11, 39), "sent_at": _t(12, 10), "send_mode": "shadow",
            "detail": "simple", "group_loc_v2": True}
    return sess, events


class Walk6a868363(_Batch):

    def _load(self):
        sess, events = _old_walk()
        self.db[punch.SESSIONS].rows[:] = [sess]           # a dry run, then an apply: one walk
        return events

    def dry(self, **kw):
        events = self._load()
        lines = []
        out = self._run(server.punch_walk_rebatch("w6a8", apply=False, events=events,
                                                  say=lines.append, **kw))
        self.assertTrue(out["ok"], out)
        return out, "\n".join(lines)

    def applied(self):
        events = self._load()
        out = self._run(server.punch_walk_rebatch("w6a8", apply=True, events=events))
        self.assertTrue(out["ok"], out)
        return out, {it["n"]: it for it in self.sess()["items"]}

    # 1 ───────────────────────────────────────────────────────────────────
    def test_correction_plus_last_3_photos_is_one_annotation(self):
        out, log = self.dry()
        self.assertIn("'Correction. 3rd floor interior. Last 3 photos'", log)
        self.assertIn("-> #11–#13: Floor 3 · interior", log)
        _out, by_n = self.applied()
        for n in (11, 12, 13):
            self.assertEqual((by_n[n]["floor"], by_n[n]["area"]), ("3", "interior"), n)
        # "Correction" is never anyone's words, as a word or a start.
        said = [str(it.get("text") or "") for it in by_n.values()]
        self.assertEqual([w for w in said if re.match(r"(?i)correction\b", w)], [])
        for n in (1, 6, 7, 9, 10):
            self.assertNotEqual(by_n[n].get("floor"), "3", n)

    # 2 ───────────────────────────────────────────────────────────────────
    def test_answers_after_done_are_for_the_item_asked_about(self):
        out, log = self.dry()
        self.assertIn("-> answer about #3: Floor 1", log)
        self.assertIn("-> answer about #3: Back of building", log)
        _out, by_n = self.applied()
        self.assertEqual((by_n[3]["floor"], by_n[3]["area"]), ("1", "Back of building"))
        for n in (41, 42, 43, 44):
            self.assertEqual(by_n[n]["floor"], punch.UNKNOWN, n)
            self.assertIn(by_n[n]["area"], (punch.UNKNOWN, None), n)

    # 3 ───────────────────────────────────────────────────────────────────
    def test_same_for_the_last_batch_is_listed_when_it_cannot_be_placed(self):
        out, log = self.dry()
        self.assertEqual(out["unplaced"], ['11:59 AM "Same for the last batch of pics"'])
        self.assertIn(punch.UNPLACED_HEADING, out["draft"])
        self.assertIn('• 11:59 AM "Same for the last batch of pics"', out["draft"])
        self.assertIn("-> couldn't place -- listed in the draft", log)
        # Never anyone's words.
        self.assertEqual(out["draft"].count("Same for the last batch of pics"), 1)

    def test_the_walker_places_it_in_the_draft(self):
        # Codex on #793: the listed reference is answered in the draft --
        # "photos 9 and 10" copies the batch words before it onto them.
        _out, _by_n = self.applied()
        saved = self.sess()["unplaced"]
        self.assertEqual([u["label"] for u in saved], ['11:59 AM "Same for the last batch of pics"'])
        self.assertEqual(saved[0]["copy"]["description"], "Compound and sheetrock not done")
        said = self.turn("photos 9 and 10")
        self.assertTrue(said[0].startswith('Applied 11:59 AM "Same for the last batch of pics" '
                                           'to #9, #10.'), said[0])
        self.assertNotIn(punch.UNPLACED_HEADING, said[0])
        self.assertEqual(self.sess()["unplaced"], [])
        for n in (9, 10):
            self.assertEqual(self.n_of(n)["text"], "Compound and sheetrock not done", n)

    def test_a_number_not_in_the_walk_keeps_it_listed(self):
        self.applied()
        said = self.turn("99")
        self.assertEqual(said, ["No photo #99 in this walkthrough. " + punch.UNPLACED_FOOT])
        self.assertEqual(len(self.sess()["unplaced"]), 1)

    def test_skip_lets_it_go_and_send_never_carries_it(self):
        self.applied()
        said = self.turn("skip")
        self.assertTrue(said[0].startswith('Skipped 11:59 AM "Same for the last batch of pics".'))
        self.assertEqual(self.sess()["unplaced"], [])
        self.applied()
        self.turn("send")
        self.assertEqual(self.sess()["unplaced"], [])

    def test_reading_the_answer(self):
        r = punch_batch.unplaced_reply
        self.assertEqual(r("9 10"), {"ns": [9, 10]})
        self.assertEqual(r("photos 9 and 10"), {"ns": [9, 10]})
        self.assertEqual(r("#9-12"), {"ns": [9, 10, 11, 12]})
        self.assertEqual(r("Skip"), {"skip": True})
        for edit in ("3 electrical", "drop 4", "9 roof", "send"):
            self.assertIsNone(r(edit), edit)

    def test_same_for_placed_by_the_model(self):
        async def place(ref):
            return {"ns": [9, 10], "ann": dict(ref["copy"], last_n=None, correction=False)}
        with patch.object(server, "_punch_place_reference", place):
            out, log = self.dry()
        self.assertEqual(out["unplaced"], [])
        self.assertIn("same as batch -> #9, #10: Compound and sheetrock not done", log)

    # 4 ───────────────────────────────────────────────────────────────────
    def test_a_caption_that_is_a_place_is_the_location(self):
        _out, by_n = self.applied()

        def where(n):
            return punch.place_label(by_n[n].get("floor"), by_n[n].get("area"))
        self.assertEqual({n: where(n) for n in (1, 14, 16, 18, 20)},
                         {1: "Cellar", 14: "Backyard", 16: "Floor 5 · staircase", 18: "Front",
                          20: "Roof"})
        self.assertEqual(by_n[20]["text"], "Missing coping")
        # A place is never the words: the batch's text, or vision "(auto)".
        for n in (1, 14, 16, 18):
            self.assertNotIn(by_n[n]["text"], ("Cellar", "Backyard", "5th floor staircase", "Front"), n)
        self.assertEqual((by_n[18]["text"], by_n[18]["text_auto"]),
                         (_seen(by_n[18]["photo_key"]), True))           # vision, "(auto)"

    def test_reading_places_and_mixed_words(self):
        r = punch_batch.read_batch
        self.assertEqual((r("Roof missing coping")["area"], r("Roof missing coping")["description"]),
                         ("roof", "Missing coping"))
        for place in ("Cellar", "Interior", "Back of building", "Backyard", "Front",
                      "5th floor staircase", "Back of building is location"):
            self.assertIsNone(r(place)["description"], place)
        self.assertIsNone(r("Correction")["description"])
        got = punch_batch.clean_batch_model(
            {"kind": "annotation", "floor": "3rd", "area": "interior", "description": "Correction"},
            "Correction. 3rd floor interior")
        self.assertEqual((got["floor"], got["area"], got["description"]), ("3", "interior", None))

    # 5 ───────────────────────────────────────────────────────────────────
    def test_floor_then_area_never_3rd_interior(self):
        out, _log = self.dry()
        d = out["draft"]
        self.assertIn("*Floor 3 · interior*", d)
        self.assertIn("*Floor 1 · Back of building*", d)
        self.assertNotIn("3rd interior", d)
        heads = [l for l in d.splitlines() if l.startswith("*") and l.endswith("*")]
        floors = [h for h in heads if h.startswith("*Floor ")]
        self.assertEqual(floors, sorted(floors, key=lambda h: int(h.split()[1].strip("*"))))

    # 6 ───────────────────────────────────────────────────────────────────
    def test_the_dry_run_shows_the_vision_descriptions(self):
        out, log = self.dry()
        self.assertTrue(self.described)
        self.assertIn("(auto)", out["draft"])
        self.assertIn(f"vision #9: {_seen('wa-photos/p588/w6a/009.jpg')} (auto)", log)
        self.assertEqual(self.sess()["status"], "sent")           # nothing saved
        self.assertFalse(any(it.get("text_auto") for it in self.sess()["items"]))

    def test_no_vision(self):
        out, log = self.dry(vision=False)
        self.assertEqual(self.described, [])
        self.assertIn("would describe", log)

    # 7 ───────────────────────────────────────────────────────────────────
    def test_the_voice_notes_are_shown_with_where_they_went(self):
        out, log = self.dry()
        self.assertIn("11:46 AM  voice 'Sheetrock not finished in the hallway'", log)
        self.assertIn("11:47 AM  voice 'Missing outlet covers'", log)
        lines = log.splitlines()
        for said in ("Sheetrock not finished", "Missing outlet covers"):
            i = next(k for k, l in enumerate(lines) if said in l and "voice" in l)
            self.assertTrue(lines[i + 1].strip().startswith("-> #"), lines[i + 1])


class MergingTexts(unittest.TestCase):

    def test_only_close_texts_with_nothing_between(self):
        ev = [{"kind": "text", "text": "Correction. 3rd floor interior", "at": _t(11, 52, 5)},
              {"kind": "text", "text": "Last 3 photos", "at": _t(11, 52, 40)},
              {"kind": "photo", "at": _t(11, 53)},
              {"kind": "text", "text": "Cellar", "at": _t(11, 54)},
              {"kind": "text", "text": "Interior", "at": _t(11, 56)},          # 2 min later
              {"kind": "text", "text": "done", "at": _t(11, 56, 10)}]
        got = punch_batch.merge_texts(ev, is_command=lambda t: t == "done")
        self.assertEqual([e.get("text", "") for e in got],
                         ["Correction. 3rd floor interior. Last 3 photos", "", "Cellar", "Interior", "done"])


if __name__ == "__main__":
    unittest.main()
