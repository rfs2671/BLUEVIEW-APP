"""Two U1 corrections, both of which reach a signed document.

1. WEATHER IS NEVER A BLANK ON A FILED RECORD.

   Weather on the Daily Jobsite Log is fetched, not typed, so when the fetch
   fails the CP has no way to fill it in. A blank cell in the PDF cannot be
   told apart from a question nobody asked, so the document has to say what
   actually happened.

   The three renderers that print it disagreed. All used
   `data.get("weather", "N/A")` — but a dict default only fires when the key is
   ABSENT, and the editor always writes the key. So an empty value rendered as
   an empty string on two of them and as "N/A" on the third.

2. ActivityChip CARRIES ITS NODE'S TRADE.

   The chip list exposed id/label/rank/band and no grouping signal at all,
   which left the daily log unable to summarise a day as anything but a list of
   individual activities. `trade` is real data already on every WorkPackage.

   Deliberately NOT a semantic phase: deciding which of 86 nodes is
   "foundation" versus "superstructure" is domain judgment, and
   sequence_rules_v1's own header says RULE CONTENTS PENDING NYC DOB
   DOMAIN-EXPERT SIGN-OFF.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from app.scheduling.sequence_ranking import rank_activities  # noqa: E402
from app.scheduling.sequence_rules_v1 import OTHER_ACTIVITY_ID  # noqa: E402


class TestWeatherIsNeverBlank(unittest.TestCase):
    """`_display_weather` — the one renderer all three call sites share."""

    def test_retrieved_weather_reads_normally(self):
        self.assertEqual(
            server._display_weather({"weather": "Sunny", "weather_temp": "72°F"}),
            "Sunny 72°F",
        )

    def test_wind_is_appended_when_present(self):
        out = server._display_weather(
            {"weather": "Windy", "weather_temp": "50°F", "weather_wind": "20 mph"},
        )
        self.assertEqual(out, "Windy 50°F — Wind: 20 mph")

    def test_no_wind_appends_nothing(self):
        out = server._display_weather({"weather": "Cloudy", "weather_temp": "60°F"})
        self.assertNotIn("Wind", out)

    # ── the whole point ──────────────────────────────────────────────────
    def test_empty_string_is_NOT_a_blank(self):
        """The regression. The editor always writes the key, so the old
        `.get(k, "N/A")` default never fired and this rendered as ' '."""
        out = server._display_weather({"weather": "", "weather_temp": ""})
        self.assertEqual(out, server.NOT_RECORDED)
        self.assertTrue(out.strip(), "a filed record must never show a blank cell")

    def test_absent_key_is_not_a_blank_either(self):
        out = server._display_weather({})
        self.assertEqual(out, server.NOT_RECORDED)

    def test_none_data_does_not_crash_a_report(self):
        self.assertEqual(server._display_weather(None), server.NOT_RECORDED)

    def test_a_failed_fetch_says_so_rather_than_looking_unanswered(self):
        for state in ("offline", "error"):
            out = server._display_weather({"weather": "", "weather_fetch_state": state})
            self.assertIn("could not be retrieved", out.lower(), state)
            self.assertNotEqual(
                out, server.NOT_RECORDED,
                "a failed fetch is NOT the same as a field nobody filled",
            )

    def test_failure_state_wins_even_over_a_stale_value(self):
        """If the fetch failed, whatever is in `weather` is not today's weather."""
        out = server._display_weather(
            {"weather": "Sunny", "weather_fetch_state": "offline"},
        )
        self.assertIn("could not be retrieved", out.lower())

    def test_ok_state_renders_the_value(self):
        out = server._display_weather({"weather": "Rainy", "weather_fetch_state": "ok"})
        self.assertEqual(out, "Rainy")

    def test_documents_filed_before_the_field_existed_read_honestly(self):
        """No fetch state at all — an older log. It falls through to the value,
        or to not-recorded. It must never claim a retrieval failure."""
        self.assertEqual(server._display_weather({"weather": "Snow"}), "Snow")
        self.assertEqual(server._display_weather({"notes": "x"}), server.NOT_RECORDED)

    def test_copy_matches_the_inspector_screen(self):
        """logbookView.fNotRecorded is '— Not recorded'. One record must read
        the same on the device and in the PDF."""
        en = (_BACKEND.parent / "frontend" / "src" / "i18n" / "en.js").read_text(
            encoding="utf-8",
        )
        self.assertIn("fNotRecorded: '— Not recorded'", en)
        self.assertEqual(server.NOT_RECORDED, "— Not recorded")

    def test_every_daily_jobsite_renderer_goes_through_the_helper(self):
        """The three call sites must not drift back to their own defaults."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        # THE LEDGER, BOTH WAYS ROUND, because it has now moved twice and the
        # second move reverses the first:
        #
        #   5 -> 4  "the investor cover's call site is gone -- weather is a
        #            field of the daily jobsite log and is printed in that
        #            log's section, not twice on one document"
        #   4 -> 5  the operator reversed it. The cover carries a weather panel
        #           again, as a PROMOTION: the daily jobsite section KEEPS its
        #           own, so the helper gained a caller rather than moving one.
        #
        # What this assertion is for is unchanged -- that no renderer drifts
        # back to its own defaults -- and the earlier reasoning is kept rather
        # than deleted, so a reader who greps it finds the reversal.
        #   5 -> 3  the report stopped EMBEDDING the filed documents, so its
        #            copies of the daily jobsite and SSC sections went with
        #            them. Both facts are still printed -- on the filed PDFs
        #            those sections index -- and the cover's panel stays.
        #
        # ── AND THE HELPER NOW HAS TWO SHAPES, NOT TWO RESOLUTIONS ────────
        #
        # `_weather_parts` holds every rule and `_display_weather` composes one
        # line from it, so a surface that sets the condition, temperature and
        # wind out separately does not have to take the line apart. Counting
        # one name alone would therefore report a renderer as having drifted
        # away when it had only asked for the other shape.
        #
        # WHAT THIS COUNTS IS THE RESOLUTION'S CALL SITES: two definitions,
        # the composition between them, the filed log's section, and the
        # investor page's panel.
        self.assertEqual(
            src.count('_display_weather(') + src.count('_weather_parts('), 5,
            "expected 2 definitions + 1 composition + 2 call sites: the filed "
            "daily jobsite log's own section, and the investor page's panel",
        )
        # THE COMPOSITION IS THE ONE THAT MAKES THEM ONE RESOLUTION rather
        # than two that happen to agree today.
        i = src.index("def _display_weather(")
        j = src.index(chr(10) + "def ", i + 10)
        self.assertIn("return _weather_parts(data).line", src[i:j],
                      "the line is built somewhere other than from the parts, "
                      "so there are two resolutions to drift apart")
        # The exact bug shape, gone.
        self.assertNotIn('f\'{data.get("weather", "N/A")} ', src)
        self.assertNotIn('f\'{d.get("weather", "N/A")} ', src)


class TheSameResolutionInTwoShapes(unittest.TestCase):
    """`_weather_parts` offers the pieces; `_display_weather` composes them.

    The panel on Page 1 sets the condition, the temperature and the wind out
    separately. The alternative was for the renderer to split the composed
    sentence, which is the layout layer deciding what a piece of a resolved
    string means -- so the helper that already decided offers both shapes.
    """

    def test_the_parts_and_the_line_are_the_same_reading(self):
        d = {"weather": "Cloudy", "weather_temp": "73°F",
             "weather_wind": "14 mph"}
        parts = server._weather_parts(d)
        self.assertEqual(parts.condition, "Cloudy")
        self.assertEqual(parts.temperature, "73°F")
        self.assertEqual(parts.wind, "14 mph")
        self.assertEqual(parts.line, server._display_weather(d))

    def test_a_failed_FETCH_offers_no_parts_at_all(self):
        """THE CASE THAT MATTERS MOST. The fetch state wins over whatever the
        other fields hold, so a stale temperature cannot be laid out beside a
        sentence saying the reading could not be retrieved."""
        for state in ("offline", "error"):
            d = {"weather_fetch_state": state, "weather": "Cloudy",
                 "weather_temp": "73°F", "weather_wind": "14 mph"}
            parts = server._weather_parts(d)
            self.assertEqual((parts.condition, parts.temperature, parts.wind),
                             ("", "", ""), state)
            self.assertIn("could not be retrieved", parts.line)

    def test_an_unrecorded_day_offers_no_parts_either(self):
        parts = server._weather_parts({"weather": "", "weather_temp": ""})
        self.assertEqual((parts.condition, parts.temperature), ("", ""))
        self.assertEqual(parts.line, server.NOT_RECORDED)

    def test_a_missing_value_is_absent_rather_than_invented(self):
        """Temperature with no condition, and a reading with no wind: each
        prints what the record holds and nothing in place of what it does
        not."""
        parts = server._weather_parts({"weather_temp": "73°F"})
        self.assertEqual(parts.condition, "")
        self.assertEqual(parts.temperature, "73°F")
        self.assertEqual(parts.wind, "")
        self.assertEqual(parts.line, "73°F")

    def test_the_composed_line_is_byte_identical_across_every_shape(self):
        """THE COMPATIBILITY CLAIM, ASSERTED RATHER THAN PROMISED. Everything
        that printed one line before this change prints the same one."""
        shapes = [
            {}, None, {"weather": "Rainy"}, {"weather_temp": "73°F"},
            {"weather": "Cloudy", "weather_temp": "73°F"},
            {"weather": "Cloudy", "weather_temp": "73°F",
             "weather_wind": "14 mph"},
            {"weather": "  Snow  ", "weather_temp": " 31°F "},
            {"weather_fetch_state": "offline"},
            {"weather_fetch_state": "error", "weather": "Cloudy"},
            {"weather_fetch_state": "ok", "weather": "Windy",
             "weather_temp": "50°F", "weather_wind": "20 mph"},
        ]
        for d in shapes:
            with self.subTest(shape=d):
                self.assertEqual(server._display_weather(d),
                                 server._weather_parts(d).line)


class TestActivityChipCarriesTrade(unittest.TestCase):
    def setUp(self):
        self.ranking = rank_activities(
            project_id="p1",
            prior_activity_ids=["building_envelope_closed"],
            structural_system="cast_in_place",
            remembered_other_labels=["night pour"],
        )
        self.chips = self.ranking.model_dump()["chips"]

    def test_chips_are_emitted_at_all(self):
        self.assertGreater(len(self.chips), 20)

    def test_every_catalogue_chip_carries_its_nodes_trade(self):
        real = [c for c in self.chips if c["band"] != "remembered_other"]
        missing = [c["id"] for c in real if not c["trade"]]
        self.assertEqual(missing, [], "every rule-backed chip has a trade")

    def test_the_trade_is_the_nodes_own_value_not_a_guess(self):
        by_id = {c["id"]: c["trade"] for c in self.chips}
        # Read straight off sequence_rules_v1's WorkPackage declarations.
        self.assertEqual(by_id.get("drywall"), "drywall")
        self.assertEqual(by_id.get("insulation"), "insulation")
        self.assertEqual(by_id.get("site_cleanup"), "gc")

    def test_a_remembered_free_text_entry_has_NO_trade(self):
        """There is no rule row behind it, so None — not an empty string, which
        would imply one was looked up and found blank."""
        remembered = [c for c in self.chips if c["band"] == "remembered_other"]
        self.assertEqual(len(remembered), 1)
        self.assertIsNone(remembered[0]["trade"])

    def test_the_other_escape_hatch_reports_its_real_node_trade(self):
        """`other` IS a node (declared with trade 'gc'), so it reports 'gc'.
        That is accurate about the graph and meaningless as a summary of the
        day — the CLIENT excludes it. Pinned here so the exclusion in
        dailyJobsiteModel.deriveGeneralDescription keeps its reason."""
        other = [c for c in self.chips if c["id"] == OTHER_ACTIVITY_ID]
        self.assertEqual(len(other), 1)
        self.assertEqual(other[0]["trade"], "gc")

    def test_adding_trade_did_not_pre_select_anything(self):
        self.assertEqual([c for c in self.chips if c["selected"]], [])

    def test_other_is_still_last(self):
        self.assertEqual(self.chips[-1]["id"], OTHER_ACTIVITY_ID)

    def test_ranking_still_degrades_without_raising(self):
        for bad in (None, "nonsense", 12345, [], ["no_such_node"]):
            r = rank_activities(project_id="p", prior_activity_ids=bad)
            self.assertGreater(len(r.chips), 0, repr(bad))


if __name__ == "__main__":
    unittest.main()
