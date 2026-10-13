"""A location for a group of photos, during the walk (Tue Oct 13, 588).

A location typed between photos is for every photo since the previous
location message, not the last photo alone: "all 2nd floor interior",
"these are all roof", "everything above is cellar", "rest are lobby", or a
bare "roof". A reply to one photo is that photo; "#12-20 roof" those
numbers. The model reads loose words (EN / ES / YI); the code applies them,
never over a place the walker gave one photo. One line confirms; 'undo'.
A walk taken before this is re-read once under the rule.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from tests import _punch_detailed  # noqa: E402
from lib import punch  # noqa: E402
from tests.test_punch_walkthrough_1821 import P588, _Walk  # noqa: E402


setUpModule, tearDownModule = _punch_detailed.module_hooks()


class GroupLocations(_Walk):

    projects = (P588,)

    def photos(self, *captions):
        for c in captions:
            self._turn(c, photo=True)

    def test_a_burst_then_all_then_five_more_then_roof(self):
        self._turn("starting walkthrough at 588")
        self.photos(*[f"defect {i}" for i in range(1, 13)])
        (said,) = self._turn("all 2nd floor interior")
        self.assertEqual(said, "Set 2nd floor (interior) for #1–#12 (12 photos).")
        for n in range(1, 13):
            self.assertEqual((self.item(n)["floor"], self.item(n)["area"]), ("2", "interior"))
        self.photos(*[f"flashing loose {i}" for i in range(13, 18)])
        (said,) = self._turn("roof")
        self.assertEqual(said, "Set roof for #13–#17 (5 photos).")
        self.assertEqual([self.item(n)["area"] for n in range(13, 18)], ["roof"] * 5)
        self.assertEqual(self.item(12)["area"], "interior")              # untouched

    def test_phrasings(self):
        for said, where in (("these are all roof", (None, "roof")),
                            ("everything above is cellar", (None, "cellar")),
                            ("rest are lobby", (None, "lobby")),
                            ("todos en el sótano", (None, "sótano"))):
            with self.subTest(said):
                self.setUp()
                self.photos("a", "b")
                (out,) = self._turn(said)
                self.assertTrue(out.endswith("for #1–#2 (2 photos).") or out.endswith(
                    "for #1, #2 (2 photos)."), out)
                got = (self.item(1).get("floor"), self.item(1)["area"])
                self.assertEqual(got[1], where[1])

    def test_never_over_a_place_given_for_one_photo(self):
        self.photos("tile cracked 4F", "outlet missing", "paint chip")
        self._turn("lobby", reply_to=2)                                  # that photo only
        self.assertEqual(self.item(2)["area"], "lobby")
        self.assertNotIn("area", {k for k, v in self.item(3).items() if v not in (None, "?")})
        (out,) = self._turn("all roof")
        self.assertEqual(out, "Set roof for #3 (1 photo).")
        self.assertEqual((self.item(1)["area"], self.item(2)["area"], self.item(3)["area"]),
                         ("Apt 4F", "lobby", "roof"))

    def test_a_numbered_place_is_that_photos(self):
        # Codex on #783: "#2 lobby", then "all roof": #2 stays the lobby.
        self.photos("a", "b", "c")
        self._turn("#2 lobby")
        (out,) = self._turn("all roof")
        self.assertEqual(out, "Set roof for #1, #3 (2 photos).")
        self.assertEqual(self.item(2)["area"], "lobby")

    def test_numbers(self):
        self.photos(*[f"x{i}" for i in range(1, 6)])
        (out,) = self._turn("#2-4 roof")
        self.assertEqual(out, "Set roof for #2–#4 (3 photos).")
        self.assertEqual([self.item(n).get("area") for n in (1, 5)], [punch.UNKNOWN] * 2)

    def test_undo(self):
        self.photos("a", "b", "c")
        self._turn("all cellar")
        (out,) = self._turn("undo")
        self.assertEqual(out, "Undone — #1–#3 back as they were.")
        self.assertEqual([self.item(n).get("area") for n in (1, 2, 3)], [punch.UNKNOWN] * 3)
        # The next group is the same photos again.
        (out,) = self._turn("roof")
        self.assertEqual(out, "Set roof for #1–#3 (3 photos).")

    def test_loose_words_through_the_model(self):
        async def model(text):
            return {"kind": "location", "scope": "group", "numbers": [],
                    "location": "back of building"} if "back" in text else {"kind": "other"}
        with patch.object(server, "_punch_loc_model", model):
            self.photos("a", "b")
            (out,) = self._turn("ok so all of that was back of the building")
            self.assertEqual(out, "Set back of building for #1, #2 (2 photos).")
            # Not a place: a note on the photo just sent, as before.
            self._turn("c", photo=True)
            (out,) = self._turn("hinge loose too")
            self.assertIn("got it", out)
        self.assertEqual(self.item(3).get("area"), punch.UNKNOWN)

    def test_the_model_is_checked(self):
        self.assertIsNone(punch.clean_loc_model({"kind": "other", "location": "roof"}))
        self.assertIsNone(punch.clean_loc_model({"kind": "location", "location": ""}))
        self.assertEqual(punch.clean_loc_model({"kind": "location", "scope": "numbers",
                                                "numbers": [], "location": "roof"})["scope"],
                         "group")
        self.assertIsNone(punch.read_group_location("tile cracked 4F"))
        self.assertIsNone(punch.read_group_location("also the fixture is loose"))


class AWalkFromBefore(_Walk):
    """Fix the 588 walk: its location messages re-read under the rule
    before anything still missing is asked."""

    projects = (P588,)

    def test_a_bare_word_on_one_photo_stays_that_photos(self):
        # Codex on #783: "roof" on #3 may have been a reply to #3 -- never
        # spread to #1 and #2 by the repair.
        self.photos = GroupLocations.photos.__get__(self)
        self.photos("a", "b", "c", "d", "e")
        s = self.sess()
        s.pop("group_loc_v2", None)
        s["items"][2].update(floor="roof", area="roof")
        s["status"], s["asking"] = "locating", 1
        out = self._turn("skip")
        self.assertEqual(len(out), 1)                                   # no repair message
        self.assertIn("(draft)", out[0])
        self.assertEqual([self.item(n).get("area") for n in (1, 2, 3)],
                         [punch.UNKNOWN, punch.UNKNOWN, "roof"])
        self.assertTrue(self.sess()["group_loc_v2"])

    def test_the_group_ends_at_a_place_from_a_message(self):
        # "roof" on #2 (a message, maybe a reply), then "all cellar" kept on #4:
        # cellar is for #3 and #4 only.
        self.photos = GroupLocations.photos.__get__(self)
        self.photos("a", "b", "c", "d")
        s = self.sess()
        s.pop("group_loc_v2", None)
        s["items"][1].update(floor="roof", area="roof")
        s["items"][3]["notes"] = [{"text": "all cellar", "at": None}]
        out = self._turn("e", photo=True)
        self.assertIn("Set cellar for #3, #4 (2 photos).", out[0])
        self.assertEqual(self.item(1).get("area"), punch.UNKNOWN)
        # The next group starts after #4 (Codex on #783): "roof" now is #5 only.
        (said,) = self._turn("all roof")
        self.assertEqual(said, "Set roof for #5 (1 photo).")
        self.assertEqual(self.item(4)["area"], "cellar")

    def test_the_old_rules_note_is_read_whole(self):
        # The old rule, "all 2nd floor interior" after photo 4: floor 2 on #4,
        # and the words kept as a note on it.
        self.photos = GroupLocations.photos.__get__(self)
        self.photos("a", "b", "c", "d", "e")
        s = self.sess()
        s.pop("group_loc_v2", None)
        s["items"][3].update(floor="2", notes=[{"text": "all 2nd floor interior", "at": None}])
        out = self._turn("f", photo=True)
        self.assertEqual(out[0], "\n".join([
            "Your location messages, applied to the photos before them:",
            "Set 2nd floor (interior) for #1–#4 (4 photos).", "Reply 'undo' to take it back."]))
        self.assertEqual([(self.item(n)["floor"], self.item(n)["area"]) for n in range(1, 5)],
                         [("2", "interior")] * 4)
        self.assertNotIn("notes", self.item(4))
        self.assertEqual(self.item(5).get("area"), punch.UNKNOWN)       # after it: not touched

    def test_the_old_rules_caption_is_read_whole(self):
        # A wordless photo, then "all 2nd floor interior": the old rule made
        # it that photo's caption.
        self.photos = GroupLocations.photos.__get__(self)
        self.photos("a", "b", "")
        s = self.sess()
        s.pop("group_loc_v2", None)
        s["items"][2].update(text="All interior", said="all 2nd floor interior", floor="2")
        out = self._turn("d", photo=True)
        self.assertIn("Set 2nd floor (interior) for #1–#3 (3 photos).", out[0])

    def test_a_new_walk_is_never_re_read(self):
        self._turn("a", photo=True)
        self.assertTrue(self.sess()["group_loc_v2"])


if __name__ == "__main__":
    unittest.main()
