"""THE INVESTOR COVER: FOUR TILES, TWO TABLES, TWO COLUMNS.

Page 1 of the redesign. Every field comes off a filed record and NOTHING is
invented to fill a space the mockup happens to have.

── WHAT IS NOT BUILT, AND WHY EACH ONE IS ABSENT ───────────────────────────

ACTIVE FLOORS -- the mockup's fifth tile, reading "2, 5, 6 + ROOF". There is no
source. `location_ids` across ALL 110 activity rows in production is 71
free-text `other:` strings and 40 empty, with ZERO floor chips: three spellings
of the same two floors in three consecutive days. The operator ruled the tile
OUT rather than permanently em-dashed, because a cover tile that always reads
as missing advertises a number the product does not have.

THE EXECUTIVE SUMMARY -- a paragraph beside the weather. Ruled out, along with
inventing anything to fill the space. The AI line stays where it is, feeding
the per-subcontractor sentences in Today's Work: a sentence per sub, each one
through the verifier, rather than one paragraph about the day.

LOOK AHEAD -- the mockup's third footer column, five bullets about tomorrow.
NOTHING IN THIS APP RECORDS WHAT IS PLANNED. It would be the only invented
content on a document whose entire claim is that every field is off a record.

── AND THE ONE THING THE TESTS BELOW EXECUTE RATHER THAN READ ──────────────

The safety tile has THREE states and the third is the one that matters: the
superintendent's log is active on ONE of 37 projects. On the other 36 no
document answers the question, and a tile reading CLEAR there would be an
attestation nobody made. So all three are rendered, from real report HTML,
against fabricated logbooks.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

DATE = "2026-09-09"
PROJECT = {"_id": "p1", "name": "588 Thomas", "address": "588 Thomas",
           "required_logbooks": ["daily_jobsite"], "project_class": "regular"}


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self.docs)


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one

    def find(self, query=None, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, query=None, *a, **k):
        if callable(self._find_one):
            return self._find_one(query)
        return self._find_one

    async def count_documents(self, *a, **k):
        return len(self.docs)

    async def find_one_and_update(self, *a, **k):
        return None


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())


def _daily(activities=None, observations=None):
    return {
        "_id": "lb1", "project_id": "p1", "date": DATE,
        "log_type": "daily_jobsite", "status": "submitted", "is_locked": True,
        "cp_signature": {"ink": "AAA", "affirmed": True,
                         "affirmed_at": "2026-09-09T21:00:00Z"},
        "data": {
            "weather": "Cloudy", "weather_temp": "71F",
            "activities": activities if activities is not None else [],
            "observations": observations or [],
        },
    }


def _cs(blocks):
    return {
        "_id": "lb2", "project_id": "p1", "date": DATE,
        "log_type": "site_superintendent_log", "status": "submitted",
        "is_locked": True, "data": blocks,
    }


NONE4 = {k: {"none_to_report": True} for k in
         ("unsafe_conditions", "orders_given", "dob_actions", "incidents")}


def _render(logbooks, checkins=()):
    db = _Db(
        projects=_Coll(find_one=lambda q: PROJECT),
        logbooks=_Coll(list(logbooks)),
        daily_logs=_Coll(find_one=lambda q: None),
        checkins=_Coll(list(checkins)),
        report_emails=_Coll(find_one=lambda q: None),
    )
    with patch.object(server, "db", db), \
            patch.object(server, "to_query_id", lambda v: v):
        return asyncio.run(server.generate_combined_report("p1", DATE))


def _text(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&mdash;", "—"), ("&#10003;", "TICK"), ("&#10007;", "CROSS"),
                 ("&amp;", "&"), ("&nbsp;", " ")):
        t = t.replace(a, b)
    return " ".join(t.split())


def _tiles(html: str):
    """(value, label) for every cover tile, as rendered.

    ANCHORED ON THE CELL, NOT ON A FONT SIZE. The first draft matched
    `font-size:26px`, and the tiles then moved onto the report's declared type
    scale -- so it found nothing and every assertion below raised IndexError
    rather than failing. A type size is a shape; `<td width="25%">` inside the
    strip is the structure, and the strip is what a tile IS.
    """
    strip = re.search(r"<table[^>]*>\s*<tr>((?:\s*<td width=\"25%\".*?</td>)+)"
                      r"\s*</tr>\s*</table>", html, re.S)
    if not strip:
        return []
    return [(_text(m.group(1)), _text(m.group(2))) for m in re.finditer(
        r'<td width="25%".*?<div[^>]*>(.*?)</div>\s*<div[^>]*>(.*?)</div>',
        strip.group(1), re.S)]


class TheStripIsFourTiles(unittest.TestCase):

    def setUp(self):
        self.html = _render(
            [_daily([{"activity_id": "a1", "company": "Arkon Builders",
                      "trade": "Framers", "photos": []}]), _cs(NONE4)],
            checkins=[{"company": "Arkon Builders", "trade": "Framers"}] * 13
                     + [{"company": "MQ Steel", "trade": "Steel / Ironwork"}] * 3,
        )

    def test_there_are_exactly_four(self):
        self.assertEqual(len(_tiles(self.html)), 4,
                         f"got {[l for _, l in _tiles(self.html)]}")

    def test_the_labels_are_the_four_that_have_a_source(self):
        self.assertEqual([l for _, l in _tiles(self.html)],
                         ["Workers onsite", "Trades", "Safety status",
                          "Daily logs filed"])

    def test_ACTIVE_FLOORS_IS_NOT_ONE_OF_THEM(self):
        """Not em-dashed, not empty — ABSENT. A tile that always reads as
        missing advertises a number the product does not have. Zero floor
        chips exist across all 110 activity rows in production."""
        self.assertNotIn("Active floors", self.html)
        self.assertNotIn("ACTIVE FLOORS", self.html.upper()
                         .replace("ACTIVE FLOORS TILE", ""))

    def test_workers_onsite_is_the_gate_count(self):
        self.assertEqual(_tiles(self.html)[0][0], "16")

    def test_trades_comes_from_the_GATE_not_the_log(self):
        """`trade` is blank on 50 of 110 activity rows; every one of the 217
        check-ins carries one. Two at the gate here, ONE on the log — so a
        count reading 1 means it read the wrong source."""
        self.assertEqual(_tiles(self.html)[1][0], "2")

    def test_a_worker_turned_away_is_not_a_trade_on_site(self):
        html = _render(
            [_daily([{"activity_id": "a1", "company": "A", "photos": []}])],
            checkins=[{"company": "A", "trade": "Framers"},
                      {"company": "B", "trade": "Roofing", "blocked": True}],
        )
        self.assertEqual(_tiles(html)[1][0], "1",
                         "a blocked check-in was counted as a trade on site")


class SafetyStatusHasThreeStatesAndTheThirdIsNotFine(unittest.TestCase):
    """RENDERED, all three. The superintendent's log is active on ONE of 37
    projects; on the rest nothing answers this question."""

    ACT = [{"activity_id": "a1", "company": "Arkon", "photos": []}]

    def _status(self, html):
        return _tiles(html)[2][0]

    def test_all_four_attested_none_reads_CLEAR(self):
        self.assertEqual(self._status(_render([_daily(self.ACT), _cs(NONE4)])),
                         "Clear")

    def test_an_item_with_content_reads_ATTENTION(self):
        blocks = dict(NONE4)
        blocks["incidents"] = {"entries": [{"text": "Struck by falling brick"}]}
        self.assertEqual(self._status(_render([_daily(self.ACT), _cs(blocks)])),
                         "Attention")

    def test_NO_SUPERINTENDENT_LOG_reads_NEITHER(self):
        """THE STATE THAT MATTERS. 36 of 37 projects have no such log. A tile
        reading CLEAR there is an attestation nobody made."""
        self.assertEqual(self._status(_render([_daily(self.ACT)])), "—")

    def test_a_log_whose_items_were_never_reached_reads_NEITHER(self):
        """Filed, but the four items are empty. Not attested, so not clear."""
        self.assertEqual(self._status(_render([_daily(self.ACT), _cs({})])),
                         "—")

    def test_a_flagged_observation_reads_ATTENTION_even_with_all_four_attested(self):
        """The CP flagged something the superintendent's four items do not
        cover. The tile must not say Clear over it."""
        html = _render([
            _daily(self.ACT, observations=[{"description": "No hard hats",
                                            "corrected_immediately": False}]),
            _cs(NONE4),
        ])
        self.assertEqual(self._status(html), "Attention")


class TheFooterIsTwoColumns(unittest.TestCase):

    def setUp(self):
        self.html = _render([_daily([{"activity_id": "a1", "company": "Arkon",
                                      "photos": []}]), _cs(NONE4)])

    def test_look_ahead_is_not_built(self):
        """Nothing in this app records what is planned. It would be the only
        invented content on the document."""
        self.assertNotIn("Look ahead", self.html)
        self.assertNotIn("Look Ahead", self.html)

    def test_both_columns_are_there(self):
        self.assertIn("Safety &amp; compliance", self.html)
        self.assertIn("Attention / open items", self.html)

    def test_an_attested_item_gets_a_tick(self):
        i = self.html.index("Safety &amp; compliance")
        self.assertIn("TICK No unsafe conditions observed",
                      _text(self.html[i:i + 4000]))

    def test_an_unfiled_log_gets_a_DASH_not_a_tick_and_not_a_cross(self):
        """"No incidents reported" and "nobody said" are different claims and
        only one of them is an attestation."""
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}])])
        i = html.index("Safety &amp; compliance")
        body = _text(html[i:i + 4000])
        self.assertIn("— No unsafe conditions observed — not stated", body)
        self.assertNotIn("TICK No unsafe conditions observed", body)

    def test_open_items_says_None_rather_than_rendering_empty(self):
        i = self.html.index("Attention / open items")
        self.assertIn("None", _text(self.html[i:i + 400]))


class TheComplianceSENTENCELeftTheBodyButItsDetailSurvived(unittest.TestCase):

    def test_the_paragraph_is_gone(self):
        """It read "5 of 5 required daily logs filed and signed" directly
        beneath a tile reading "5 of 5" and a tick saying the same words."""
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}]), _cs(NONE4)])
        self.assertNotIn("Compliance:</strong>", html)

    def test_but_a_DEFICIENCY_still_names_which_log(self):
        """The tick becomes the sentence when it cannot be a tick. Losing that
        would make the move a deletion."""
        html = _render([_cs(NONE4)])          # no daily jobsite log at all
        i = html.index("Safety &amp; compliance")
        body = _text(html[i:i + 4000])
        self.assertIn("not filed", body.lower())
        self.assertIn("Daily Jobsite", body)


class WeatherIsPromotedAndTheOldRulingIsRetracted(unittest.TestCase):

    def test_the_panel_renders_from_the_daily_log(self):
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}])])
        self.assertIn(">Weather</div>", html)
        i = html.index(">Weather</div>")
        self.assertIn("Cloudy", _text(html[i:i + 400]))

    def test_it_is_a_PROMOTION__the_daily_log_keeps_its_own(self):
        """Not a move. `_display_weather` gains a call site rather than
        changing one."""
        self.assertGreaterEqual(_SRC.count("_display_weather("), 4)

    def test_the_reversed_ruling_is_QUOTED_not_deleted(self):
        """A correction that erases the words it corrects leaves the next
        grep empty, and empty reads as "no such problem"."""
        i = _SRC.index("WEATHER IS ON THE COVER")
        block = _SRC[i:i + 1800]
        self.assertTrue("NO WEATHER ON THE COVER" in block,
                        "the old ruling was deleted rather than retracted")
        self.assertTrue("REVERSES A RULING" in block,
                        "the quotation is not marked as reversed")


class NoExecutiveSummaryWasInvented(unittest.TestCase):

    def test_no_summary_heading_exists(self):
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}])])
        self.assertNotIn("Executive summary", html)
        self.assertNotIn("Executive Summary", html)

    def test_the_AI_line_still_feeds_the_per_sub_sentences(self):
        """It stays where it is. The ruling removed a paragraph, not the
        sentences."""
        self.assertIn("_pg1_lines", _SRC)
        self.assertIn("_pg1_ai_note", _SRC)


class TheTablesAreRelabelled(unittest.TestCase):

    def test_the_sub_heads_read_as_the_mockup_names_them(self):
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}])])
        heads = re.findall(r"<h3[^>]*>(.*?)</h3>", html)
        self.assertIn("Workforce breakdown", heads)
        self.assertIn("Today's work", heads)

    def test_the_old_names_are_gone(self):
        html = _render([_daily([{"activity_id": "a1", "company": "A",
                                 "photos": []}])])
        heads = re.findall(r"<h3[^>]*>(.*?)</h3>", html)
        self.assertNotIn("Headcount by subcontractor", heads)
        self.assertNotIn("Work today", heads)


class TheTileBuilderIsNotCalled_tile(unittest.TestCase):
    """FOUND BY RENDERING, NOT BY READING. The photo loop binds a LOCAL named
    `_tile` for each photograph's HTML and runs BEFORE the cover is assembled,
    so a function called `_tile` is a string by the time it is called --
    `'str' object is not callable`, on a live render, pointing at a photo loop
    four hundred lines away."""

    def test_the_cover_builder_has_its_own_name(self):
        self.assertIn("def _stat_tile(", _SRC)

    def test_and_the_photo_loop_still_owns__tile(self):
        i = _SRC.index("def _stat_tile(")
        j = _SRC.index("_pg1_photos = \"\"")
        self.assertGreater(j, i, "the photo loop moved above the builder")
        self.assertIn("_tile = (", _SRC[j:j + 4000])


if __name__ == "__main__":
    unittest.main(verbosity=2)
