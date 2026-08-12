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
        self.assertEqual(
            src.count('_display_weather('), 5,
            "expected 1 definition + 4 call sites: the two PDF renderers, the "
            "SSC section, and the investor progress page",
        )
        # The exact bug shape, gone.
        self.assertNotIn('f\'{data.get("weather", "N/A")} ', src)
        self.assertNotIn('f\'{d.get("weather", "N/A")} ', src)


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
