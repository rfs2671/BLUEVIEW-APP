"""The walkthrough in a DM, Sun Oct 11 6:21-6:22 PM (588), and the rules it
broke.

What happened: two photos with captions ("Bulb burnt", "Missing screw by
table") each got a 👍. A reply to photo 1, "2nd floor Apt 2D", went to the
assistant: "Which job?". "588" set the walk's job. A reply to photo 2, "4th
floor Apt 4F", went to the assistant again: "Which job?" AGAIN, its menu still
open. "588... Same walkthrough" picked the menu's job for the menu's question
(the FIRST reply), and the assistant said it couldn't access the message
replied to, about "2nd floor, Apt 2D" -- the wrong photo, and untrue.

The rules now:
  1. The first photo starts the walk; the job is asked ONCE, then (none when
     the walker has one job, or picked one in this DM in the last 30
     minutes). The walk stays until "done" / "cancel", or 2 hours idle.
  2. A reply to one of the walk's photos is about THAT item: its location
     (floor + unit), trade or words. Never the assistant.
  3. Other typing during a walk is a note on the photo just sent, or "Add to
     which photo?". Never the assistant.
  4. The assistant is given what a reply-to quotes (its words and that it is
     a photo) and never says it can't see it.
  6. Every item needs a location before the draft: "done" asks per photo.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import punch, wa_assistant  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO = "co_588"
CHAT = "17185550100@c.us"
P588 = {"_id": "p588", "name": "588 Thomas St", "address": "588 Thomas St, Brooklyn, NY",
        "company_id": CO}
P12 = {"_id": "p12", "name": "12 Main St", "address": "12 Main St, Brooklyn, NY",
       "company_id": CO}
THUMB = "/9j/4AAQSkZJRgABAQAAAQABAAD" + "A" * 400          # a photo's base64 thumbnail


def _mid(i):
    return f"false_{CHAT}_3EB0{i:04d}"


class _Walk(unittest.TestCase):
    """Each message goes through _punch_dm_turn, and when it is not a walk
    turn to the assistant -- exactly the webhook's order."""

    projects = (P588, P12)

    def setUp(self):
        self.db = FakeDb(projects=list(self.projects))
        self.said, self.reacts, self.assistant = [], [], []
        self.n = 0
        self.ident = {"user_id": "u_roy", "company_id": CO, "role": "admin",
                      "user": {"_id": "u_roy", "name": "Roy"}, "projects": list(self.projects)}

    def _turn(self, text="", photo=False, reply_to=None, quoted_body=None):
        self.n += 1
        parsed = {"has_image": photo, "message_id": f"3EB0{self.n:04d}",
                  "message_id_serialized": _mid(self.n)}
        if reply_to:
            parsed.update(quoted_message_id=f"3EB0{reply_to:04d}", quoted_type="image",
                          quoted_body=THUMB if quoted_body is None else quoted_body)

        async def send(chat, msg, *a, **k):
            self.said.append(msg)
            return True

        async def react(chat, mid, emoji):
            self.reacts.append((self.n, emoji))
            return True

        async def assistant(*a, **k):
            self.assistant.append(a[2] if len(a) > 2 else k)

        async def image(parsed):
            return b"\xff\xd8\xff" + b"\x00" * 64

        before = len(self.said)
        with patch.object(server, "db", self.db), \
                patch.object(server, "send_whatsapp_message", send), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_assistant_reply", assistant), \
                patch.object(server, "download_image", image), \
                patch.object(server, "_upload_to_r2", lambda *a, **k: True):
            self._deliver(parsed, text)
        return self.said[before:]

    def _deliver(self, parsed, text):
        async def go():
            if not await server._punch_dm_turn(self.ident, CHAT, parsed, text):
                await server._dm_assistant_reply(self.ident, CHAT, text, parsed["message_id"])
        asyncio.run(go())

    def sess(self):
        (s,) = [r for r in self.db[punch.SESSIONS].rows if r["status"] not in ("expired",)]
        return s

    def item(self, n):
        return next(it for it in self.sess()["items"] if it["captured"] == n)


class The1821Sequence(_Walk):

    def test_exactly_as_sent(self):
        # 6:21 PM, two photos with captions: 👍 each; the job asked once.
        out1 = self._turn("Bulb burnt", photo=True)
        out2 = self._turn("Missing screw by table", photo=True)
        self.assertEqual(self.reacts, [(1, "👍"), (2, "👍")])
        self.assertEqual(len(out1), 1)
        self.assertIn("Which job is this walkthrough for?", out1[0])
        self.assertEqual(out2, [])
        # Reply to photo 1: its location. Not the assistant, no "Which job?".
        out = self._turn("2nd floor Apt 2D", reply_to=1)
        # Answered in words, never only a 👍 (live 588, Oct 12, 10:46 AM).
        self.assertEqual(out, ["#1 'Bulb burnt' (Floor 2 · Apt 2D) — got it. Next photo, or 'done' "
                               "(or \"done, send to Chris\")."])
        self.assertEqual(len(self.reacts), 2)
        # "588": the walk's job.
        out = self._turn("588")
        self.assertEqual(out, ["Walkthrough at 588 Thomas St. Keep going; 'done' when finished."])
        # Reply to photo 2: ITS location (not photo 1's), no job question.
        out = self._turn("4th floor Apt 4F", reply_to=2)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("#2 'Missing screw by table' (Floor 4 · Apt 4F) — got it."))
        # "588... Same walkthrough": yes, this one -- never the assistant.
        out = self._turn("588... Same walkthrough")
        self.assertEqual(out, ["Still the walkthrough at 588 Thomas St. Keep going; 'done' when finished."])
        self.assertEqual(self.assistant, [])
        self.assertEqual(sum("Which job" in s for s in self.said), 1)

        # The state (item 5): both photos in the 588 walk, each with its area.
        s = self.sess()
        self.assertEqual((s["project_id"], s["status"], len(s["items"])), ("p588", "capturing", 2))
        self.assertEqual((self.item(1)["text"], self.item(1)["floor"], self.item(1)["area"]),
                         ("Bulb burnt", "2", "Apt 2D"))
        self.assertEqual((self.item(2)["text"], self.item(2)["floor"], self.item(2)["area"]),
                         ("Missing screw by table", "4", "Apt 4F"))
        self.assertFalse(self.item(1).get("notes") or self.item(2).get("notes"))

        # "done": every item has a location, so the draft.
        (draft,) = self._turn("done")
        self.assertIn("588 Thomas St · walkthrough · 2 items (draft)", draft)
        self.assertIn("Bulb burnt (Apt 2D)", draft)
        self.assertIn("Missing screw by table (Apt 4F)", draft)
        self.assertLess(draft.index("*Floor 2*"), draft.index("*Floor 4*"))
        self.assertEqual(self.assistant, [])

    def test_a_reply_matched_by_its_caption_when_the_id_is_missing(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw by table", photo=True)
        self._turn("4F", reply_to=999, quoted_body="Missing screw by table")   # an id that matches nothing
        self.assertEqual(self.item(2)["area"], "Apt 4F")
        self.assertEqual(self.item(1)["area"], punch.UNKNOWN)


class TheJobIsAskedOnce(_Walk):

    def test_one_job_is_never_asked(self):
        self.projects = (P588,)
        self.setUp()
        self.assertEqual(self._turn("Bulb burnt 2D", photo=True), [])
        self.assertEqual(self.sess()["project_id"], "p588")

    def test_a_job_picked_here_in_the_last_30_minutes(self):
        with patch.object(server, "db", self.db):
            asyncio.run(server._dm_state_set("dm_job", CHAT, 1800, project_id="p12"))
        self.assertEqual(self._turn("Bulb burnt 2D", photo=True), [])
        self.assertEqual(self.sess()["job_name"], "12 Main St")

    def test_a_number_from_the_question_picks(self):
        self._turn("Bulb burnt 2D", photo=True)
        self.assertEqual(self._turn("2"), ["Walkthrough at 12 Main St. Keep going; 'done' when finished."])

    def test_idle_a_day_ends_the_walk(self):
        # 12:02 PM: 24 hours idle, not 2 (a real walk is not lost at lunch).
        self.projects = (P588,)
        self.setUp()
        self._turn("Bulb burnt 2D", photo=True)
        self.db[punch.SESSIONS].rows[0]["updated_at"] = datetime.now(timezone.utc) - timedelta(hours=3)
        self._turn("Loose outlet 3B", photo=True)
        self.assertEqual([r["status"] for r in self.db[punch.SESSIONS].rows], ["capturing"])
        self.db[punch.SESSIONS].rows[0]["updated_at"] = datetime.now(timezone.utc) - timedelta(hours=25)
        self._turn("Bulb burnt 2D", photo=True)
        statuses = sorted(r["status"] for r in self.db[punch.SESSIONS].rows)
        self.assertEqual(statuses, ["capturing", "expired"])
        self.assertEqual(len([r for r in self.db[punch.SESSIONS].rows
                              if r["status"] == "expired"][0]["items"]), 2)   # kept
        self.assertEqual([it["text"] for it in self.sess()["items"]], ["Bulb burnt"])
        return
        self.db[punch.SESSIONS].rows[0]["updated_at"] = datetime.now(timezone.utc) - timedelta(hours=3)
        self._turn("Loose outlet 3B", photo=True)
        statuses = sorted(r["status"] for r in self.db[punch.SESSIONS].rows)
        self.assertEqual(statuses, ["capturing", "expired"])
        self.assertEqual([it["text"] for it in self.sess()["items"]], ["Loose outlet"])   # 3B: its place, not its words


class TypingDuringAWalk(_Walk):

    projects = (P588,)

    def test_a_note_on_the_photo_just_sent(self):
        self._turn("Bulb burnt 2D", photo=True)
        (said,) = self._turn("also the fixture is loose")
        self.assertTrue(said.startswith("#1 'Bulb burnt' (Floor 2 · Apt 2D) — got it."))
        self.assertEqual(self.item(1)["notes"][0]["text"], "also the fixture is loose")
        self.assertEqual(self.assistant, [])

    def test_which_photo_when_the_last_one_is_not_recent(self):
        self._turn("Bulb burnt 2D", photo=True)
        self._turn("Missing screw 4F", photo=True)
        self.sess()["items"][-1]["at"] = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.assertEqual(self._turn("hinge is loose too"), [punch.WHICH_PHOTO])
        (said,) = self._turn("1")
        self.assertTrue(said.startswith("#1 'Bulb burnt'"))
        self.assertEqual(self.item(1)["notes"][0]["text"], "hinge is loose too")
        self.assertEqual(self.assistant, [])

    def test_hash_number_targets_a_photo(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw", photo=True)
        self._turn("#1 lobby")
        self.assertEqual(self.item(1)["area"], "lobby")


class ALocationIsNeverABlocker(_Walk):
    """Tue Oct 13, 12:02 PM: a real 45-item walk at 588 stuck at "39 items
    need a location", asked one at a time; "1st floor" -> "Where on floor
    1?"; "Back of building is location", "Ignore all that and just finish"
    and "." -> the same long prompt, 5 times. Now: any words are a place, a
    floor alone is one, ONE question for all of them, then the draft."""

    projects = (P588,)

    def test_one_question_for_all_then_the_draft(self):
        self._turn("Bulb burnt 2D", photo=True)
        self._turn("Missing screw by table", photo=True)
        self._turn("Paint touch up corridor", photo=True)            # an area: enough
        self._turn("Crack in slab", photo=True)
        (q,) = self._turn("done")
        self.assertEqual(q, "\n".join([
            "2 have no location. Reply like '3 rear yard, 5-9 roof, 12 2nd floor', or "
            "'all roof', or 'skip' to send without.",
            "#2 Missing screw by table", "#4 Crack in slab"]))
        (draft,) = self._turn("2 back of building, 4 1st floor")
        self.assertTrue(draft.startswith("Set 2 locations."), draft)
        self.assertIn("(draft)", draft)
        self.assertEqual(self.item(2)["area"], "back of building")        # as typed
        self.assertEqual((self.item(4)["floor"], self.item(4)["area"]), ("1", punch.UNKNOWN))
        self.assertEqual(self.sess()["status"], "draft")

    def test_skip_goes_out_without(self):
        for said in ("skip", "Ignore all that and just finish", ".", "just send", "send as is",
                     "move on"):
            with self.subTest(said):
                self.setUp()
                self._turn("Bulb burnt", photo=True)
                self._turn("done")
                (draft,) = self._turn(said)
                self.assertIn("(draft)", draft)
                self.assertIn("*Location: not given*", draft)
                # And never asked again: 'send' goes on to who gets what.
                (who,) = self._turn("send")
                self.assertNotIn("no location. Reply like", who)

    def test_all_and_rest(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw", photo=True)
        self._turn("done")
        self._turn("all rear yard")
        self.assertEqual([self.item(n)["area"] for n in (1, 2)], ["rear yard", "rear yard"])

    def test_never_the_same_prompt_twice_in_a_row(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw", photo=True)
        self._turn("done")
        (a,) = self._turn("hmm")
        self.assertEqual(a, punch.BATCH_SHORT)                        # short, no list again
        (b,) = self._turn("what")
        self.assertEqual(b, punch.BATCH_SHORT + " " + punch.SKIP_HINT)
        (draft,) = self._turn("??")
        self.assertIn("(draft)", draft)                               # on, never a 3rd time

    def test_a_floor_alone_is_a_location(self):
        self._turn("Bulb burnt 1st floor", photo=True)
        (draft,) = self._turn("done")
        self.assertIn("(draft)", draft)
        self.assertIn("*Floor 1*", draft)

    def test_a_walk_asked_the_old_way(self):
        # 12:02 PM: a walk mid-question when this ships ("Where on floor 1
        # is #1?"): the answer is that item's, as typed; then the one question.
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw", photo=True)
        sess = self.sess()
        sess.update(status="locating", asking=1)
        sess.pop("where_asked", None)
        (q,) = self._turn("Back of building is location")
        self.assertEqual(self.item(1)["area"], "Back of building")
        self.assertTrue(q.startswith("Set 1 location.\n1 has no location."), q)
        (draft,) = self._turn("Ignore all that and just finish")
        self.assertIn("(draft)", draft)

    def test_a_photo_after_the_question_is_an_item_and_not_asked(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("done")
        self._turn("skip")
        (out,) = self._turn("Loose outlet", photo=True)
        self.assertIn("Added #2 'Loose outlet'", out)
        self.assertNotIn("no location", out)
        self.assertEqual([it["text"] for it in self.sess()["items"]], ["Bulb burnt", "Loose outlet"])

    def test_an_unknown_number_changes_nothing(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("done")
        (draft,) = self._turn("#99 lobby")
        self.assertIn("No #99 in this walkthrough.", draft)
        self.assertEqual(self.item(1).get("area", punch.UNKNOWN), punch.UNKNOWN)

    def test_drop_one(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("Missing screw 4F", photo=True)
        self._turn("done")
        (draft,) = self._turn("drop 1")
        self.assertIn("1 item (draft)", draft)

    def test_locations_in_the_draft(self):
        self._turn("Bulb burnt", photo=True)
        self._turn("done")
        self._turn("skip")
        (draft,) = self._turn("1 near the gas meter")
        self.assertTrue(draft.startswith("Set 1 location."), draft)
        self.assertEqual(self.item(1)["area"], "near the gas meter")

    def test_add_under_a_photo_is_its_own_item(self):
        # 12:02 PM: "Add missing access ladder" replying to the stucco photo
        # had been kept as a note on it -- in no draft, in no message.
        self._turn("Stucco cracked rear wall 2nd floor", photo=True)
        (out,) = self._turn("Add missing access ladder", reply_to=1)
        self.assertIn("Added #2 'Missing access ladder'", out)
        two = self.item(2)
        self.assertEqual((two["text"], two["floor"], two["photo_key"]),
                         ("Missing access ladder", "2", None))
        self.assertNotIn("notes", self.item(1))

    def test_an_added_item_never_reuses_a_dropped_number(self):
        # Codex on #781: after dropping #2, "Add …" under #1 made a new #2.
        self._turn("Stucco cracked 2nd floor", photo=True)
        self._turn("Tile chipped 2nd floor", photo=True)
        self._turn("done")
        self._turn("drop 2")
        (out,) = self._turn("Add missing access ladder", reply_to=1)
        self.assertIn("Added #3 'Missing access ladder'", out)


class WhereWordsAreRead(unittest.TestCase):

    def test_valid_locations(self):
        cases = {
            "2nd floor Apt 2D": ("2", "Apt 2D"), "4th floor Apt 4F": ("4", "Apt 4F"),
            "4F": ("4", "Apt 4F"), "fl 4 unit F": ("4", "Apt 4F"), "Bulb burnt 2D": ("2", "Apt 2D"),
            "piso 4 apto F": ("4", "Apt 4F"), "lobby": (None, "lobby"), "keler": (None, "cellar"),
            "elevator room": (None, "elevator machine room"), "machine room": (None, "elevator machine room"),
            "water main": (None, "meter room"), "meter room": (None, "meter room"),
            "boiler room": (None, "boiler room"), "roof": (None, "roof"), "bulkhead": (None, "bulkhead"),
            "cellar": (None, "cellar"), "basement": (None, "basement"),
            "compactor room": (None, "compactor room"), "stairwell A": (None, "stairwell A"),
            "stair B": (None, "stairwell B"), "mail room": (None, "mail room"), "gym": (None, "gym"),
            "laundry": (None, "laundry room"), "bike room": (None, "bike room"),
            "trash room": (None, "trash room"), "parking": (None, "parking"),
            "courtyard": (None, "courtyard"), "facade": (None, "facade"), "exterior": (None, "facade"),
            "sidewalk": (None, "sidewalk"), "3rd floor corridor": ("3", "corridor"),
            "sótano": (None, "cellar"), "vestíbulo": (None, "lobby"),
        }
        for words, (floor, area) in cases.items():
            with self.subTest(words):
                loc = punch.read_location(words)
                self.assertEqual((loc["floor"], loc["area"]), (floor, area))
                self.assertEqual(punch.location_state(loc["floor"], loc["area"]), "ok")

    def test_anything_named_is_enough(self):
        for words, state in {"Missing screw by table": "missing", "5th floor": "ok",
                             "Floor 6 kitchen": "ok", "corridor": "ok",
                             "hallway": "ok", "stairs landing": "ok",
                             "Apt F": "ok", "2x4 missing": "missing", "10am": "missing"}.items():
            with self.subTest(words):
                loc = punch.read_location(words)
                self.assertEqual(punch.location_state(loc["floor"], loc["area"]), state)
        self.assertEqual(punch.free_location("Back of building is location"),
                         {"floor": None, "area": "Back of building"})
        self.assertEqual(punch.free_location("near the gas meter"),
                         {"floor": None, "area": "near the gas meter"})
        for filler in ("hmm", "what?", "ok", "idk", "?"):
            self.assertEqual(punch.free_location(filler), {"floor": None, "area": None})


class TheAssistantSeesWhatWasRepliedTo(unittest.TestCase):

    def test_a_photo_reply_carries_its_caption_and_type(self):
        q = wa_assistant.with_quoted("588... Same walkthrough", "Missing screw by table", False, "image")
        self.assertIn('(This is a reply to their earlier photo, captioned "Missing screw by table".)', q)
        q = wa_assistant.with_quoted("what is this", wa_assistant.NO_CAPTION, False, "image")
        self.assertIn("their earlier photo, with no caption", q)

    def test_a_photo_body_is_its_caption_never_its_thumbnail(self):
        self.assertEqual(wa_assistant.quoted_words({"type": "image", "body": THUMB,
                                                    "caption": "Bulb burnt"}), "Bulb burnt")
        self.assertEqual(wa_assistant.quoted_words({"type": "image", "body": THUMB}), "")
        self.assertEqual(wa_assistant.quoted_words({"type": "chat", "body": "ok"}), "ok")

    def test_never_says_it_cannot_see_it(self):
        self.assertIn("never say you cannot see, open or access the message",
                      wa_assistant.DM_AGENT_CLAUSE)
        denial = ("I can't access or interpret the content of the message you replied to. "
                  "Could you tell me about 2nd floor, Apt 2D?")
        self.assertTrue(wa_assistant.denies_quoted_access(denial))
        self.assertFalse(wa_assistant.denies_quoted_access("Two inspections are open at 588."))
        q = wa_assistant.with_quoted("what's this", "Bulb burnt", False, "image")
        self.assertEqual(wa_assistant.quoted_fallback(q),
                         'You replied to your photo, captioned "Bulb burnt". What do you need about it?')
        # And the server swaps a denial for that, wherever it answers a job question.
        src = inspect.getsource(server)
        self.assertIn("wa_assistant.denies_quoted_access(reply)", src)

    def test_the_dm_passes_the_type(self):
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertIn('"type": parsed.get("quoted_type") or ""', src)


if __name__ == "__main__":
    unittest.main()
