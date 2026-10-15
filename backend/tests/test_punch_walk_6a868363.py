"""The repair dry run of walk 6a868363 (588) misread it.

Wed Oct 14:
1. "Correction. 3rd floor interior" + "Last 3 photos" (11:52) is ONE
   annotation: the last 3 photos -> Floor 3 · interior.
2. "1st floor", "Back of building is location" (after "Done", answering
   "Where is #3 'Back of building'?") are #3's.
3. "Same for the last batch of pics": placed by the model, else listed under
   "Couldn't place -- tell me which photos".
4. A caption that is only a place is the location; vision describes it.
5. Floor + area, the draft by floor, then area.
6. Vision descriptions in the dry run. 7. The voice notes and where they went.

Thu Oct 15, the dry run at d1e9a11 (new reader), still wrong:
V1. Vision: all 39 "See photo (auto)" -- the script never made the R2
    client, every read failed silently. Now each photo shows the real
    description or the exact error; "See photo" is never a description.
V2. The assistant's reply between "Correction. 3rd floor interior" and
    "Last 3 photos" split them: the first hit #1, 2, 6, 7, 9-13 and "Last 3
    photos" nothing. Bot messages between the walker's texts never split them.
V3. A photo's own caption, or the place the assistant confirmed for it at
    capture ("#1 'Front' (Facade)", "#15 (Floor 5 · stairs)", "#47 (Floor 7 ·
    bulkhead)"), is never overwritten by a batch text (#1, #2 went to
    Floor 3 interior).
V4. #8, #19, #23 had floors 2, 4, 5 + "Interior" and lost the floor.
V5. One heading per place (two "Roof").
V6. The assistant's capture confirmations are the ground truth.

Thu Oct 15, the dry run at ae14f5f with real vision (descriptions work):
W1. "Correction. 3rd floor interior" -> bot "Which photo is that for?" ->
    "Last 3 photos": the next text ANSWERS the question -- the photos for the
    previous text, however long it took. #11-#13 only.
W2. A confirmation "(where? floor and unit)" (#13, #44) is the assistant's
    placeholder, not a place: never a "Where? floor and unit" group.
W3. A capture confirmation never removes detail: #36 confirmed "Floor 6",
    then a batch "Floor 6 · interior" -> Floor 6 · interior.

THE MESSAGES. TIMELINE below is rebuilt from what the two dry-run reports
said (texts, times, the question, the confirmations quoted); the photos'
exact order is not known here. The exact walk:

    railway run python scripts/repair_punch_walk.py --walk 6a868363 \\
        --dump-events backend/tests/fixtures/punch_walk_6a868363.json

writes its messages AND its items as stored (never phone numbers). Saved
there, every test below replays it instead of TIMELINE; the checks that name
a photo by number run on it too.
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


def _burst(start, n, every=2, extra=None):
    return [(start + timedelta(seconds=every * i), "photo", "", (extra or {}).get(i))
            for i in range(n)]


#: (time, kind, caption / text / transcript / the assistant's words, stored
#: place {"floor", "area", "loc_src"} or None). A photo's caption is its own.
TIMELINE = [
    (_t(11, 40, 0), "photo", "Front", None),                               # 1
    (_t(11, 40, 5), "bot", "Got it. #1 'Front' (Facade)", None),
    (_t(11, 40, 20), "photo", "", None),                                   # 2
    (_t(11, 40, 25), "bot", "#2 (Facade)", None),
    (_t(11, 41, 0), "photo", "Back of building", None),                    # 3
    (_t(11, 41, 5), "bot", "#3 'Back of building' (?)", None),
    (_t(11, 41, 30), "photo", "", None),                                   # 4
    (_t(11, 42, 0), "photo", "", None),                                    # 5
    (_t(11, 42, 30), "photo", "", None),                                   # 6
    (_t(11, 43, 0), "photo", "", None),                                    # 7
    (_t(11, 43, 30), "photo", "Interior", {"floor": "2", "loc_src": "group"}),   # 8
    (_t(11, 46, 10), "voice", "Sheetrock not finished in the hallway", None),
    (_t(11, 47, 5), "voice", "Missing outlet covers", None),
    (_t(11, 48, 0), "photo", "", None),                                    # 9
    (_t(11, 49, 0), "photo", "", None),                                    # 10
    (_t(11, 50, 0), "photo", "", None),                                    # 11
    (_t(11, 50, 30), "photo", "", None),                                   # 12
    (_t(11, 51, 0), "photo", "", None),                                    # 13
    (_t(11, 51, 5), "bot", "#13 (where? floor and unit)", None),
    (_t(11, 52, 5), "text", "Correction. 3rd floor interior", None),
    (_t(11, 52, 15), "bot", "Which photo is that for?", None),
    (_t(11, 53, 35), "text", "Last 3 photos", None),                       # 90 s later
    (_t(11, 54, 0), "photo", "Backyard", None),                            # 14
    (_t(11, 54, 30), "photo", "", None),                                   # 15
    (_t(11, 54, 35), "bot", "#15 (Floor 5 · stairs)", None),
    (_t(11, 55, 0), "photo", "5th floor staircase", None),                 # 16
    (_t(11, 55, 30), "photo", "", None),                                   # 17
    (_t(11, 56, 0), "photo", "Front", None),                               # 18
    (_t(11, 56, 30), "photo", "Interior", {"floor": "4", "loc_src": "group"}),   # 19
    (_t(11, 57, 0), "photo", "Roof missing coping", None),                 # 20
] + _burst(_t(11, 57, 4), 20, extra={2: {"floor": "5", "loc_src": "group"},     # 21-40: 23
                                     9: {"floor": "Roof", "loc_src": "group"}}) + [  # 30: a floor "Roof"
    (_t(11, 58, 0), "text", "7th floor. Compound and sheetrock not done", None),
    (_t(11, 59, 0), "text", "Same for the last batch of pics", None),
] + _burst(_t(12, 0, 0), 4) + [                                            # 41-44: the NEXT 4
    (_t(12, 1, 10), "photo", "", None),                                    # 45 (64 s later)
    (_t(12, 1, 12), "photo", "", None),                                    # 46
    (_t(12, 1, 14), "photo", "", None),                                    # 47
    (_t(12, 1, 16), "bot", "#47 (Floor 7 · bulkhead)", None),
    (_t(12, 1, 30), "text", "Done", None),
    (_t(12, 1, 40), "bot", "Where is #3 'Back of building'? (floor + unit, or a named area)", None),
    (_t(12, 2, 10), "text", "1st floor", None),
    (_t(12, 3, 30), "text", "Back of building is location", None),
]
#: #23 is the burst's 3rd photo, its caption "Interior".
TIMELINE[[i for i, r in enumerate(TIMELINE) if r[1] == "photo"][22]] = (
    _t(11, 57, 8), "photo", "Interior", {"floor": "5", "loc_src": "group"})


def _after_photo(n, *rows, timeline=TIMELINE):
    i = [k for k, r in enumerate(timeline) if r[1] == "photo"][n - 1]
    timeline[i + 1:i + 1] = list(rows)


#: W3: #36 confirmed "Floor 6"; then "Last 2 photos 6th floor interior" (#35, #36).
_after_photo(36, (_t(11, 57, 34), "bot", "#36 (Floor 6)", None),
             (_t(11, 57, 35), "text", "Last 2 photos 6th floor interior", None))
#: W2: the placeholder on #44.
_after_photo(44, (_t(12, 0, 7), "bot", "#44 (where? floor and unit)", None))


def _late(timeline):
    """The same walk with nothing sent for 6 minutes after "Same for the last
    batch of pics": no next burst -- the model places it, or it is listed."""
    k = next(i for i, r in enumerate(timeline) if r[2] == "Same for the last batch of pics")
    return timeline[:k + 1] + [(at + timedelta(minutes=6), kind, said, stored)
                               for at, kind, said, stored in timeline[k + 1:]]


LATE_TIMELINE = _late(TIMELINE)


def _fixture() -> dict:
    """The exact walk, when it has been dumped: {"events", "items", ...}."""
    if not FIXTURE.exists():
        return {}
    got = json.loads(FIXTURE.read_text())
    return got if isinstance(got, dict) else {"events": got}


def _session(items) -> dict:
    return {"_id": "w6a8", "user_id": "u_roy", "company_id": CO, "chat": CHAT, "project_id": "p588",
            "job_name": "588 Thomas St", "job_code": "588", "status": "sent", "items": items,
            "created_at": _t(11, 39), "sent_at": _t(12, 10), "send_mode": "shadow",
            "detail": "simple", "group_loc_v2": True}


def _from_fixture(fx: dict):
    """The dumped walk, replayed as it is: its items as stored, its events."""
    events = []
    for r in fx["events"]:
        e = dict(r)
        e["at"] = datetime.fromisoformat(r["at"]) if r.get("at") else None
        events.append(e)
    items = [dict(it) for it in fx.get("items") or []]
    for it in items:
        if isinstance(it.get("at"), str):
            it["at"] = datetime.fromisoformat(it["at"])
    return _session(items), events


def _old_walk(timeline=None):
    """The walk as the old rule left it: each text and voice note was the
    last photo's words (its caption_ids say so), the 11:47 voice note an
    item of its own; sent in shadow. The exact walk when it is dumped."""
    fx = _fixture()
    if fx.get("items") and timeline is None:
        return _from_fixture(fx)
    items, events = [], []
    n = 0
    for i, (at, kind, said, stored) in enumerate(timeline or TIMELINE):
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
            it.update(stored or {})
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
            elif [it for it in items if it.get("photo_key")][-1].get("text"):
                # After a captioned photo the old rule made the note an item of its own.
                items.append({"n": 80 + i, "captured": n + 0.4, "photo_key": None, "message_id": mid,
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
    return _session(items), events


class _WalkBase(_Batch):

    #: None: the walk (the dumped one when saved); else this timeline.
    timeline = None

    def _load(self):
        sess, events = _old_walk(self.timeline)
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



class Walk6a868363(_WalkBase):

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
        for n in (41, 42, 43, 44):                          # the next burst's: never #3's
            self.assertEqual(by_n[n]["floor"], "7", n)
            self.assertIn(by_n[n]["area"], (punch.UNKNOWN, None), n)

    # 3 ───────────────────────────────────────────────────────────────────
    def test_same_for_the_last_batch_is_the_next_burst(self):
        # 11:59 "Same for the last batch of pics", nothing sent since the last
        # batch: the NEXT 4 photos (#41-#44, 12:00) are Floor 7, "Compound and
        # sheetrock not done". #45-#47 (64 s later) are another burst.
        out, log = self.dry()
        self.assertIn("-> same as the last batch -> the next photos #41–#44: Floor 7 — "
                      "Compound and sheetrock not done", log)
        self.assertEqual(out["unplaced"], [])
        self.assertNotIn(punch.UNPLACED_HEADING, out["draft"])
        _out, by_n = self.applied()
        for n in (41, 42, 43, 44):
            self.assertEqual((by_n[n]["floor"], by_n[n]["text"]),
                             ("7", "Compound and sheetrock not done"), n)
        for n in (45, 46):
            self.assertEqual(by_n[n]["floor"], punch.UNKNOWN, n)
        # The batch it copies: #37-#40.
        for n in (37, 40):
            self.assertEqual((by_n[n]["floor"], by_n[n]["text"]),
                             ("7", "Compound and sheetrock not done"), n)

    def test_the_rule(self):
        def ev(kind, at, text=""):
            return {"kind": kind, "at": at, "text": text, "message_id": f"m{at.minute}{at.second}"}
        items = [{"n": k, "captured": k, "photo_key": f"k{k}", "message_id": f"m{m}{sec}",
                  "floor": punch.UNKNOWN, "area": punch.UNKNOWN}
                 for k, (m, sec) in enumerate([(1, 0), (1, 5), (3, 0), (3, 5), (9, 0)], 1)]
        reading = {"kind": "annotation", "floor": "7", "area": None, "description": "Paint", "note": None,
                   "last_n": None}
        events = [ev("photo", _t(12, 1)), ev("photo", _t(12, 1, 5)), ev("text", _t(12, 2), "7th floor paint"),
                  ev("text", _t(12, 2, 30), "same for the next ones"),
                  ev("photo", _t(12, 3)), ev("photo", _t(12, 3, 5)),      # within 5 min: these two
                  ev("photo", _t(12, 9))]                                # a new burst: not this one
        got = punch_batch.replay([dict(i) for i in items], events,
                                 {2: reading, 3: {"kind": "reference"}})
        by_n = {it["n"]: it for it in got["items"]}
        self.assertEqual([by_n[k]["floor"] for k in (1, 2, 3, 4, 5)], ["7", "7", "7", "7", punch.UNKNOWN])
        self.assertEqual(got["references"], [])
        # Nothing within 5 minutes: to the model / the couldn't-place list.
        late = events[:4] + [ev("photo", _t(12, 8))]
        got = punch_batch.replay([dict(i) for i in items[:3]], late,
                                 {2: reading, 3: {"kind": "reference"}})
        self.assertEqual([r["text"] for r in got["references"]], ["same for the next ones"])

    # 4 ───────────────────────────────────────────────────────────────────
    def test_a_caption_that_is_a_place_is_the_location(self):
        _out, by_n = self.applied()

        def where(n):
            return punch.place_label(by_n[n].get("floor"), by_n[n].get("area"))
        self.assertEqual({n: where(n) for n in (1, 14, 16, 18, 20)},
                         {1: "Facade", 14: "Backyard", 16: "Floor 5 · staircase", 18: "Front",
                          20: "Roof"})
        self.assertEqual(by_n[20]["text"], "Missing coping")
        # A place is never the words: the batch's text, or vision "(auto)".
        for n in (1, 14, 16, 18):
            self.assertNotIn(by_n[n].get("text"), ("Front", "Backyard", "5th floor staircase"), n)
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


class NoNextBurst(_WalkBase):
    """A "same for ..." with no photos within 5 minutes: placed by the model,
    else listed under "Couldn't place -- tell me which photos"."""

    timeline = LATE_TIMELINE

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
        self.assertIn("same as batch -> #9, #10: Floor 7 — Compound and sheetrock not done", log)



class TheOct15DryRun(_WalkBase):
    """V1-V6: what the d1e9a11 dry run still got wrong."""

    # V2 ──────────────────────────────────────────────────────────────────
    def test_the_bots_reply_does_not_split_the_correction(self):
        out, log = self.dry()
        self.assertIn("'Correction. 3rd floor interior. Last 3 photos'", log)
        self.assertIn("-> #11–#13: Floor 3 · interior", log)
        # "Last 3 photos" is never read on its own, and nothing else moved.
        self.assertNotIn("text 'Last 3 photos'", log)
        _out, by_n = self.applied()
        on3 = sorted(n for n, it in by_n.items() if it.get("floor") == "3")
        self.assertEqual(on3, [11, 12, 13])

    # V3 / V6 ─────────────────────────────────────────────────────────────
    def test_what_the_bot_confirmed_at_capture_stands(self):
        out, log = self.dry()
        self.assertIn("confirmed at capture: #1 Facade", log)
        self.assertIn("confirmed at capture: #15 Floor 5 · stairs", log)
        self.assertIn("confirmed at capture: #47 Floor 7 · bulkhead", log)
        _out, by_n = self.applied()

        def where(n):
            return punch.place_label(by_n[n].get("floor"), by_n[n].get("area"))
        self.assertEqual({n: where(n) for n in (1, 2, 15, 47)},
                         {1: "Facade", 2: "Facade", 15: "Floor 5 · stairs", 47: "Floor 7 · bulkhead"})

    def test_a_photos_own_caption_is_never_overwritten_by_a_batch(self):
        _out, by_n = self.applied()
        self.assertEqual(punch.place_label(by_n[14]["floor"], by_n[14]["area"]), "Backyard")
        self.assertEqual(punch.place_label(by_n[16]["floor"], by_n[16]["area"]), "Floor 5 · staircase")

    # V4 ──────────────────────────────────────────────────────────────────
    def test_interior_keeps_the_floor(self):
        _out, by_n = self.applied()
        self.assertEqual({n: punch.place_label(by_n[n]["floor"], by_n[n]["area"]).lower()
                          for n in (8, 19, 23)},
                         {8: "floor 2 · interior", 19: "floor 4 · interior", 23: "floor 5 · interior"})

    # V5 ──────────────────────────────────────────────────────────────────
    def test_one_heading_per_place(self):
        out, _log = self.dry()
        heads = [l for l in out["draft"].splitlines() if l.startswith("*") and l.endswith("*")]
        self.assertEqual(len(heads), len(set(h.lower() for h in heads)), heads)
        self.assertEqual([h for h in heads if "roof" in h.lower()], ["*Roof*"])
        # One spelling per heading: "Floor 2 · interior" like "Floor 3 · interior".
        self.assertIn("*Floor 2 · interior*", heads)
        self.assertNotIn("*Floor 2 · Interior*", heads)

    # V1 ──────────────────────────────────────────────────────────────────
    def test_vision_errors_are_shown_never_see_photo(self):
        self.vision_error = "no photo: R2 wa-photos/x-full.jpg: ClientError NoSuchKey"
        events = self._load()
        lines = []
        out = self._run(server.punch_walk_rebatch("w6a8", apply=False, events=events,
                                                  say=lines.append))
        log = "\n".join(lines)
        self.assertRegex(log, r"vision #\d+: NO DESCRIPTION -- no photo: R2 wa-photos/x-full\.jpg: "
                              r"ClientError NoSuchKey")
        self.assertRegex(log, r"vision: \d+ of \d+ photo\(s\) without a description")
        self.assertNotIn("See photo", log + out["draft"])
        self.assertIn(punch.NO_WORDS, out["draft"])


class TheOct15ApplyCheck(_WalkBase):
    """W1-W3: the dry run with real vision."""

    def test_the_answer_to_which_photo_names_the_photos(self):
        out, log = self.dry()
        self.assertIn("'Correction. 3rd floor interior. Last 3 photos'", log)
        self.assertIn("-> #11–#13: Floor 3 · interior", log)
        self.assertNotIn("text 'Correction. 3rd floor interior'\n", log)
        _out, by_n = self.applied()
        self.assertEqual(sorted(n for n, it in by_n.items() if it.get("floor") == "3"), [11, 12, 13])
        # #2, #6, #7, #9, #10 stay as they were.
        self.assertEqual(punch.place_label(by_n[2]["floor"], by_n[2]["area"]), "Facade")
        for n in (6, 7):
            self.assertEqual(punch.place_label(by_n[n]["floor"], by_n[n]["area"]), "Hallway", n)
        for n in (9, 10):
            self.assertEqual((by_n[n]["floor"], by_n[n]["area"]), (punch.UNKNOWN, punch.UNKNOWN), n)

    def test_the_where_placeholder_is_not_a_place(self):
        out, log = self.dry()
        heads = [l for l in out["draft"].splitlines() if l.startswith("*") and l.endswith("*")]
        self.assertEqual([h for h in heads if "where" in h.lower() or "unit" in h.lower()], [])
        self.assertNotIn("confirmed at capture: #13", log)
        self.assertNotIn("confirmed at capture: #44", log)
        _out, by_n = self.applied()
        self.assertEqual(punch.place_label(by_n[13]["floor"], by_n[13]["area"]), "Floor 3 · interior")
        self.assertIsNone(re.search(r"(?i)\bwhere\b", str(by_n[44].get("area"))))

    def test_a_confirmation_never_removes_detail(self):
        out, log = self.dry()
        self.assertIn("confirmed at capture: #36 Floor 6", log)
        _out, by_n = self.applied()
        self.assertEqual({n: punch.place_label(by_n[n]["floor"], by_n[n]["area"]) for n in (35, 36)},
                         {35: "Floor 6 · interior", 36: "Floor 6 · interior"})

    def test_merging_a_confirmation_with_what_the_photo_had(self):
        it = {"floor": "6", "area": "interior"}
        punch_batch.pin_confirmed(it, {"floor": "6", "area": None})
        self.assertEqual((it["floor"], it["area"]), ("6", "interior"))         # same floor: kept
        it = {"floor": "5", "area": "interior"}
        punch_batch.pin_confirmed(it, {"floor": "6", "area": None})
        self.assertEqual((it["floor"], it["area"]), ("6", punch.UNKNOWN))      # another floor
        it = {"floor": "6", "area": punch.UNKNOWN, "loc_src": "photo", "confirmed": True, "n": 1,
              "captured": 1}
        punch_batch.apply_batch([it], {"floor": "7", "area": "interior"})
        self.assertEqual((it["floor"], it["area"]), ("6", punch.UNKNOWN))      # never another floor's


class TheDump(_WalkBase):
    """`--dump-events` writes what the fixture loader replays: a walk dumped
    and loaded back reads exactly as the walk itself."""

    def test_dumped_and_replayed_is_the_same_walk(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "repair_punch_walk", Path(__file__).parents[1] / "scripts" / "repair_punch_walk.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sess, events = _old_walk()
        rows, items = mod.dump(sess, events, punch)
        blob = json.dumps({"events": rows, "items": items})
        self.assertNotIn(CHAT.split("@")[0], blob)                 # never the phone in an id
        direct, _ = self.dry()
        with patch(f"{__name__}._fixture", lambda: json.loads(blob)):
            from_dump, _ = self.dry()
        self.assertEqual(from_dump["draft"], direct["draft"])


class ReadingConfirmations(unittest.TestCase):

    def test_labels(self):
        f = punch_batch.place_from_label
        self.assertEqual(f("Floor 5 · stairs"), {"floor": "5", "area": "stairs"})
        self.assertEqual(f("Floor 7 · bulkhead"), {"floor": "7", "area": "bulkhead"})
        self.assertEqual(f("Facade"), {"floor": None, "area": "Facade"})
        self.assertEqual(f("Roof"), {"floor": "roof", "area": None})
        self.assertEqual(f("3rd floor"), {"floor": "3", "area": None})
        for no in ("?", "8 photos", "Location: not given", "", "where? floor and unit",
                   "Where? Floor and unit"):
            self.assertIsNone(f(no), no)

    def test_messages(self):
        c = punch_batch.capture_confirmations
        self.assertEqual([(n, w) for n, w, _ in c("Got it. #1 'Front' (Facade)")], [(1, "Front")])
        self.assertEqual([n for n, _w, _p in c("#15 (Floor 5 · stairs)")], [15])
        # Quotes inside the caption (Codex on #796).
        got = c("#1 'Women's bathroom crack' (Floor 2 · bathroom)")
        self.assertEqual([(n, w, p) for n, w, p in got],
                         [(1, "Women's bathroom crack", {"floor": "2", "area": "bathroom"})])
        self.assertEqual([(n, w) for n, w, _ in c('#4 "6" gap at sill" (Floor 3)')], [(4, '6" gap at sill')])
        # A batch's count, a question: never a photo's place.
        self.assertEqual(c("Got it — #5–#12 (8 photos): Floor 2 · interior."), [])
        self.assertEqual(c("Where is #3 'Back of building'? (floor + unit, or a named area)"), [])


class Vision(unittest.TestCase):
    """The real vision path: every reason there is no description, said."""

    def run_(self, it, **env):
        import asyncio
        with patch.object(server, "QWEN_API_KEY", env.get("key", "k")), \
                patch.object(server, "record_vision_call", _noop), \
                patch.object(server, "_webhook_media_ref", _empty_ref), \
                patch.object(server, "download_image", env.get("wa", _no_media)), \
                patch.object(server, "_r2_fetch", env.get("r2", lambda k: (None, "ClientError NoSuchKey"))):
            return asyncio.run(server._punch_vision(it, "p588"))

    def test_no_key(self):
        got = self.run_({"n": 1, "photo_key": "k.jpg"}, key="")
        self.assertIn("no vision key", got["error"])

    def test_no_photo_says_where_it_looked(self):
        got = self.run_({"n": 1, "photo_key": "wa/1.jpg", "message_id": "false_x_ABC"})
        self.assertIsNone(got["words"])
        self.assertIn("R2 wa/1-full.jpg: ClientError NoSuchKey", got["error"])
        self.assertIn("R2 wa/1.jpg: ClientError NoSuchKey", got["error"])
        self.assertIn("WhatsApp media: nothing came back (no media reference in the log)", got["error"])

    def test_whatsapp_media_when_r2_has_none(self):
        async def wa(parsed):
            return _jpeg()
        with patch.object(server, "ServerHttpClient", _Http(200, {"choices": [{"message": {
                "content": "Missing outlet cover plate."}}]})):
            got = self.run_({"n": 2, "photo_key": "wa/2.jpg", "message_id": "false_x_DEF"}, wa=wa)
        self.assertEqual((got["words"], got["source"], got["error"]),
                         ("Missing outlet cover plate", "whatsapp", None))

    def test_http_error_is_shown(self):
        with patch.object(server, "ServerHttpClient", _Http(400, {}, text="InvalidParameter: image")):
            got = self.run_({"n": 3, "photo_key": "wa/3.jpg"}, r2=lambda k: (_jpeg(), None))
        self.assertEqual(got["error"], "vision HTTP 400: InvalidParameter: image")

    def test_apply_describes_a_photo_with_no_stored_copy(self):
        # Codex on #796: photo_failed items get the WhatsApp fallback on
        # apply too, as in the dry run.
        import asyncio
        seen = []

        async def vision(it, project_id=None, store=None):
            seen.append(it.get("n"))
            return {"words": "Cracked tile", "source": "whatsapp", "error": None}

        async def save(*a, **k):
            return None
        sess = {"project_id": "p588", "items": [
            {"n": 1, "photo_key": None, "photo_failed": True, "message_id": "A", "text": ""},
            {"n": 2, "photo_key": None, "message_id": "B", "text": ""}]}
        with patch.object(server, "_punch_vision", vision), patch.object(server, "_punch_save", save):
            asyncio.run(server._punch_describe_blanks(sess, trades=False))
        self.assertEqual(seen, [1])
        self.assertEqual(sess["items"][0]["text"], "Cracked tile")
        self.assertEqual(sess["items"][1].get("vision_error"), "no photo")

    def test_the_r2_client_is_made_on_first_use(self):
        made = []
        with patch.object(server, "_r2_client", None), \
                patch.object(server, "_get_r2_client", lambda: made.append(1) or "client"):
            self.assertEqual(server._r2(), "client")
        self.assertEqual(made, [1])


async def _noop(*a, **k):
    return None


async def _empty_ref(*a, **k):
    return {}


async def _no_media(parsed):
    return None


def _jpeg() -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


class _Http:
    def __init__(self, status, body, text=""):
        self.status, self.body, self.text = status, body, text

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        outer = self

        class R:
            status_code = outer.status
            text = outer.text

            def json(self):
                return outer.body
        return R()


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

    def test_the_assistants_reply_between_them_does_not_split_them(self):
        # V2 (11:52): the bot answered between the two texts.
        ev = [{"kind": "text", "text": "Correction. 3rd floor interior", "at": _t(11, 52, 5)},
              {"kind": "bot", "text": "Noted.", "at": _t(11, 52, 15)},
              {"kind": "text", "text": "Last 3 photos", "at": _t(11, 52, 40)}]
        got = punch_batch.merge_texts(ev)
        self.assertEqual([(e["kind"], e.get("text")) for e in got],
                         [("text", "Correction. 3rd floor interior. Last 3 photos"), ("bot", "Noted.")])

    def test_the_answer_to_which_photo_however_long(self):
        # W1: the bot asked "Which photo is that for?"; the answer 90 s later.
        ev = [{"kind": "text", "text": "Correction. 3rd floor interior", "at": _t(11, 52, 5)},
              {"kind": "bot", "text": "Which photo is that for?", "at": _t(11, 52, 15)},
              {"kind": "text", "text": "Last 3 photos", "at": _t(11, 53, 35)}]
        self.assertEqual([e.get("text") for e in punch_batch.merge_texts(ev) if e["kind"] == "text"],
                         ["Correction. 3rd floor interior. Last 3 photos"])
        # Timed from the question (Codex on #797): asked 9 min later,
        # answered 2 min after that.
        late = [dict(ev[0]), {"kind": "bot", "text": "Which photo is that for?", "at": _t(12, 1, 5)},
                {"kind": "text", "text": "Last 3 photos", "at": _t(12, 3, 5)}]
        self.assertEqual([e.get("text") for e in punch_batch.merge_texts(late) if e["kind"] == "text"],
                         ["Correction. 3rd floor interior. Last 3 photos"])
        # Not asked: 90 s apart are two texts.
        ev[1]["text"] = "Got it."
        self.assertEqual(len([e for e in punch_batch.merge_texts(ev) if e["kind"] == "text"]), 2)

    def test_a_question_about_an_item_does(self):
        ev = [{"kind": "text", "text": "Done", "at": _t(12, 1)},
              {"kind": "bot", "text": "Where is #3 'Back of building'?", "at": _t(12, 1, 20)},
              {"kind": "text", "text": "1st floor", "at": _t(12, 1, 40)}]
        got = punch_batch.merge_texts(ev)
        self.assertEqual([e.get("text") for e in got if e["kind"] == "text"], ["Done", "1st floor"])


if __name__ == "__main__":
    unittest.main()
