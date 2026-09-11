"""PAGE 4: ONE CARD PER REQUIRED LOG, AND THE CARD SURVIVES ITS PICTURE.

The project record is an INDEX. The investor report may index rather than
contain -- it has no statutory weight and no inspector reads it -- so each
required logbook gets a card and the card links to the filed record.

── SEVEN CARDS, NOT EIGHT ──────────────────────────────────────────────────

The mockup's eighth reads "Additional Records -- permits, deliveries, visitors,
etc." and there is nothing behind it: visitors and deliveries are FIELDS ON THE
DAILY JOBSITE LOG, already inside card 01. A card promising records that live
in another card is worse than seven cards.

THE COUNT IS PER PROJECT. Across the five live projects the required set is 0,
5, 5, 7 and 7; a Major A/B job carries more. So the grid FLOWS 4-up rather than
pretending to be 4x2.

── THREE STATES, BECAUSE A REQUIRED LOG CAN BE MISSING ─────────────────────

It was put to me that one cannot be -- "there's no way to submit without it
anyway". MEASURED ACROSS EVERY PROJECT AND DATE IN PRODUCTION: 38 days where
fewer were filed than were due, against 6 complete. On 588 Thomas the
superintendent and scaffold logs are absent from nearly every day before
2026-09-04, which is when they were switched on. The belief came from three
weeks of complete days.

There is no gate and there could not be: each logbook is an independent
document with its own Submit, and "the day ended" is not an event this app
owns.

── AND THE PICTURE IS AN ILLUSTRATION, NOT THE RECORD ──────────────────────

This is the FIRST LIVE USE OF POPPLER in this codebase -- `SCREENSHOT_ENABLED`
is False, so the one existing caller never runs. Every failure path returns
None and the card renders without its picture: A MISSING THUMBNAIL COSTS AN
IMAGE, NEVER THE CARD. The tests below prove that by rendering with no R2
client at all, which is also what happens locally.
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
REQUIRED = ["daily_jobsite", "preshift_signin", "site_superintendent_log",
            "toolbox_talk", "subcontractor_orientation", "osha_log",
            "scaffold_maintenance"]


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

    def __aiter__(self):
        """Some readers iterate the cursor directly. Without this they raise
        and the renderer logs a warning it then swallows -- noise that reads
        like a defect in the code under test."""
        async def _gen():
            for d in self.docs:
                yield d
        return _gen()


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one
        self.inserted = []

    def find(self, q=None, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, q=None, *a, **k):
        return self._find_one(q) if callable(self._find_one) else self._find_one

    async def count_documents(self, *a, **k):
        return len(self.docs)

    async def insert_one(self, doc):
        self.inserted.append(doc)

    async def update_one(self, *a, **k):
        return None

    async def create_index(self, *a, **k):
        return None

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


def _filed(log_type, lid):
    return {"_id": lid, "project_id": "p1", "date": DATE, "log_type": log_type,
            "status": "submitted", "is_locked": True,
            "updated_at": "2026-09-09T21:00:00Z",
            "cp_signature": {"ink": "A", "affirmed": True,
                             "affirmed_at": "2026-09-09T21:00:00Z"},
            "data": {"activities": []}}


def _render(types_filed, required=None):
    project = {"_id": "p1", "name": "588 Thomas", "address": "588 Thomas",
               "required_logbooks": list(required or REQUIRED),
               "project_class": "regular"}
    db = _Db(
        projects=_Coll(find_one=lambda q: project),
        logbooks=_Coll([_filed(t, f"lb{i}") for i, t in enumerate(types_filed)]),
        daily_logs=_Coll(find_one=lambda q: None),
        checkins=_Coll([]),
        report_emails=_Coll(find_one=lambda q: None),
    )
    with patch.object(server, "db", db), \
            patch.object(server, "to_query_id", lambda v: v):
        return asyncio.run(server.generate_combined_report("p1", DATE))


def _page4(html):
    i = html.find("Project record")
    return html[i:] if i >= 0 else ""


def _cards(html):
    """(number, title, citation, has_image, footer) per card, as rendered."""
    out = []
    for m in re.finditer(
        r'<td width="25%" valign="top".*?<div[^>]*>(\d\d)</div>\s*'
        r'<div[^>]*>(.*?)</div>(.*?)</td></tr></table></td>',
            _page4(html), re.S):
        rest = m.group(3)
        cite = re.search(r'font-size:11px[^>]*>(.*?)</div>', rest)
        foot = ("View document" if "View document" in rest else
                (re.search(r'color:#64748b;">\s*(.*?)\s*</div>', rest, re.S)
                 .group(1) if 'color:#64748b;">' in rest else "?"))
        out.append((m.group(1), _t(m.group(2)),
                    _t(cite.group(1)) if cite else "",
                    '<img src="' in rest, _t(foot)))
    return out


def _t(x):
    return " ".join(re.sub(r"<[^>]+>", " ", x).replace("&amp;", "&").split())


class OneCardPerRequiredLog(unittest.TestCase):

    def setUp(self):
        self.html = _render(REQUIRED)

    def test_there_are_seven_not_eight(self):
        self.assertEqual(len(_cards(self.html)), 7)

    def test_there_is_no_ADDITIONAL_RECORDS_card(self):
        """Visitors and deliveries are fields on the daily jobsite log,
        already inside card 01."""
        p4 = _page4(self.html)
        self.assertNotIn("Additional Records", p4)
        self.assertNotIn("Additional records", p4)
        self.assertNotIn("deliveries, visitors", p4)

    def test_the_count_follows_the_PROJECT_not_a_constant(self):
        """0, 5, 5, 7 and 7 across the five live projects."""
        five = REQUIRED[:5]
        self.assertEqual(len(_cards(_render(five, required=five))), 5)

    def test_an_empty_STORED_set_falls_back_to_the_computed_one(self):
        """AND PAGE 4 STILL RENDERS, which is right and was not my first
        guess. `required_logbooks` is a CACHE -- the renderer already recomputes
        from `project_class` when it is empty, because a requirement exists
        whether or not the cached list does. One live project has an empty
        stored set; it is not a project with no obligations."""
        html = _render([], required=[])
        self.assertNotEqual(_page4(html), "")
        self.assertGreater(len(_cards(html)), 0)
        i = _SRC.index("_required = list(project.get(")
        self.assertIn("get_required_logbooks", _SRC[i:i + 260])

    def test_the_citations_are_OURS(self):
        cites = {t: c for _, t, c, _, _ in _cards(self.html)}
        self.assertEqual(cites["Daily Jobsite Log"], "§3301.2")
        self.assertEqual(cites["Construction Superintendent Log"],
                         "§3301.13.13")
        self.assertEqual(cites["Subcontractor Safety Orientation"], "LL196")
        self.assertEqual(cites["Scaffold Maintenance Log"], "§3314")

    def test_the_citation_is_read_from_the_registry_not_retyped(self):
        """The mockup prints "§3301-02" for what the registry calls §3301.2.
        A second copy of a citation on a compliance-adjacent document is a
        second citation the moment one is edited."""
        i = _SRC.index("_CITE = {")
        self.assertIn("LOGBOOK_TYPE_REGISTRY", _SRC[i:i + 200])
        self.assertIn('t.get("dob_reference")', _SRC[i:i + 200])

    def test_the_cards_are_numbered_from_one(self):
        self.assertEqual([n for n, *_ in _cards(self.html)],
                         ["01", "02", "03", "04", "05", "06", "07"])


class ThreeStatesBecauseARequiredLogCanBeMissing(unittest.TestCase):

    def test_a_filed_log_gets_a_button(self):
        cards = _cards(_render(REQUIRED))
        self.assertTrue(all(f == "View document" for *_, f in cards))

    def test_a_DAILY_log_that_was_not_filed_says_Not_filed(self):
        """38 days in production where fewer were filed than were due."""
        html = _render([t for t in REQUIRED if t != "scaffold_maintenance"])
        by_title = {t: f for _, t, _, _, f in _cards(html)}
        self.assertEqual(by_title["Scaffold Maintenance Log"], "Not filed")

    def test_a_WEEKLY_log_not_filed_today_is_NOT_a_deficiency(self):
        """`toolbox_talk` is weekly and `subcontractor_orientation` is
        as-needed. The cover's ratio excludes them deliberately; the card must
        not contradict it by calling them missing."""
        html = _render([t for t in REQUIRED
                        if t not in ("toolbox_talk",
                                     "subcontractor_orientation")])
        by_title = {t: f for _, t, _, _, f in _cards(html)}
        self.assertEqual(by_title["Tool Box Talk"], "Not due today")
        self.assertEqual(by_title["Subcontractor Safety Orientation"],
                         "Not due today")

    def test_the_card_is_STILL_THERE_when_the_log_is_not(self):
        """Omitting it would show five cards on a project requiring seven, and
        a reader counting cards would get a different answer from the cover's
        ratio."""
        html = _render([t for t in REQUIRED if t != "scaffold_maintenance"])
        self.assertEqual(len(_cards(html)), 7)

    def test_and_a_missing_log_gets_NO_link(self):
        html = _render([t for t in REQUIRED if t != "scaffold_maintenance"])
        self.assertEqual(len(re.findall(r"/api/public/logbook/",
                                        _page4(html))), 6)


class TheLinksGoThroughTheShareToken(unittest.TestCase):

    def test_every_filed_card_carries_one(self):
        html = _render(REQUIRED)
        self.assertEqual(len(re.findall(r"/api/public/logbook/",
                                        _page4(html))), 7)

    def test_it_is_the_public_route_and_not_the_authenticated_one(self):
        """`get_single_logbook_pdf` is Depends(get_current_user); a recipient
        clicking it gets a 401."""
        p4 = _page4(_render(REQUIRED))
        self.assertNotIn("/api/reports/logbook/", p4)

    def test_a_token_that_cannot_be_minted_costs_the_button_not_the_card(self):
        async def _no_token(*a, **k):
            return None
        with patch.object(server, "_mint_logbook_share_token", _no_token):
            html = _render(REQUIRED)
        self.assertEqual(len(_cards(html)), 7, "the cards went with the links")
        self.assertEqual(len(re.findall(r"/api/public/logbook/",
                                        _page4(html))), 0)


class TheCardSurvivesAFailedRaster(unittest.TestCase):
    """FIRST LIVE USE OF POPPLER. `SCREENSHOT_ENABLED` is False, so the one
    existing caller never runs and nothing exercises it in production."""

    def test_no_r2_client_means_no_picture_and_seven_intact_cards(self):
        """Which is also what happens locally, so this path is the one every
        run takes here."""
        self.assertIsNone(server._r2_client,
                          "the fixture assumes R2 is unconfigured in tests")
        cards = _cards(_render(REQUIRED))
        self.assertEqual(len(cards), 7)
        self.assertTrue(all(not img for *_, img, _ in cards))
        self.assertTrue(all(f == "View document" for *_, f in cards),
                        "the button went with the picture")

    def test_a_raster_that_throws_returns_None_rather_than_raising(self):
        def _boom(_b):
            raise RuntimeError("poppler is not installed")
        with patch.object(server, "_render_logbook_thumbnail", _boom):
            self.assertEqual(len(_cards(_render(REQUIRED))), 7)

    def test_the_rasteriser_swallows_a_missing_poppler(self):
        """Executed. An ImportError and a poppler-not-found both come back as
        None, because both are "no picture"."""
        self.assertIsNone(server._render_logbook_thumbnail(b"not a pdf"))
        self.assertIsNone(server._render_logbook_thumbnail(b""))

    def test_every_exit_in_the_url_helper_returns_None(self):
        body = _thumb_url_body()
        self.assertNotIn("raise", body)
        self.assertGreaterEqual(body.count("return None"), 3)


def _thumb_url_body():
    """The WHOLE of `_logbook_thumbnail_url`, to its next top-level def.

    Every assertion below sliced `_SRC[i:i + 2600]`, and the function grew past
    2600 characters the moment it gained the comment explaining why poppler is
    unexercised -- so two checks started reading a truncated body and failed on
    code that had not changed. A character count is not an anchor: it measures
    how much was written, not where the subject ends.
    """
    i = _SRC.index("async def _logbook_thumbnail_url(")
    j = _SRC.index("\ndef ", i)
    return _SRC[i:j]


class TheThumbnailIsRenderedOnceEver(unittest.TestCase):

    def test_the_cache_key_is_the_logbook_AND_its_updated_at(self):
        """A filed log is frozen, so the picture is a pure function of it.
        `updated_at` moves when a photograph is appended -- the only write
        `append_activity_photo` makes outside photos[] -- so an appended
        photograph produces a new key and nothing else does."""
        self.assertEqual(server._logbook_thumb_r2_key("lb1", "2026"),
                         "report-thumbs/lb1/2026.png")
        self.assertNotEqual(server._logbook_thumb_r2_key("lb1", "a"),
                            server._logbook_thumb_r2_key("lb1", "b"))

    def test_the_cache_is_consulted_BEFORE_anything_is_rendered(self):
        body = _thumb_url_body()
        self.assertLess(body.index("db.logbook_thumbnails.find_one"),
                        body.index("generate_single_logbook_html"),
                        "every report would re-render the PDF")

    def test_the_row_is_written_AFTER_the_object(self):
        """A cache entry naming an object R2 does not have would serve a broken
        image every day after, and nothing would retry it."""
        body = _thumb_url_body()
        self.assertLess(body.index("_upload_to_r2"),
                        body.index("db.logbook_thumbnails.update_one"))

    def test_it_is_delivered_through_the_temp_media_token(self):
        """A public URL to an R2 object, fetched over HTTP by WeasyPrint --
        which is what that mechanism was built for."""
        body = _thumb_url_body()
        self.assertIn("_mint_temp_media_token(key", body)
        self.assertIn("_public_temp_media_url", body)

    def test_the_TTL_is_the_media_default_not_the_document_one(self):
        """The fetch happens DURING the render, seconds after the mint -- not
        weeks later by a reader, which is what the 90-day document token is
        for."""
        i = _SRC.index("_mint_temp_media_token(key")
        self.assertIn("ttl_seconds=3600", _SRC[i:i + 120])

    def test_the_raster_runs_off_the_event_loop(self):
        # THE THREE CALLS BY NAME, not a count of the words. Counting
        # occurrences of "asyncio.to_thread" got 4: the comment above the
        # renderer MENTIONS it, and prose in the haystack is not a call.
        body = _thumb_url_body()
        # THE OPEN PAREN IS WHAT MAKES IT A CALL. `asyncio.to_thread` counted
        # 4, because the comment above the renderer names the function in
        # prose. Prose in the haystack is not a call, and the paren is the
        # cheapest thing that tells them apart.
        self.assertEqual(body.count("asyncio.to_thread("), 3,
                         "the PDF render, the raster and the R2 put are all "
                         "blocking and all three must be offloaded")
        for blocking in ("_render_pdf", "_render_logbook_thumbnail",
                         "_upload_to_r2"):
            self.assertIn(blocking, body,
                          f"{blocking} is no longer called here")


class TheGridFlowsFourUp(unittest.TestCase):

    def test_seven_cards_render_as_four_then_three(self):
        """COUNTED, NOT PARSED. The first draft matched `<tr>(.*?)</tr>` and
        found zero rows: every card contains its own nested table, so a
        non-greedy outer match terminates at the first INNER `</tr>`. Counting
        the two kinds of cell needs no nesting-aware parser and says the same
        thing -- seven cards in rows of four is 4 + 3, which is one pad."""
        p4 = _page4(_render(REQUIRED))
        cards = len(re.findall(r'<td width="25%" valign="top"', p4))
        pads = len(re.findall(r'<td width="25%"></td>', p4))
        self.assertEqual(cards, 7)
        self.assertEqual(pads, 1, "7 cards is 4 + 3, so one padding cell")
        self.assertEqual((cards + pads) % 4, 0, "the rows are not four wide")

    def test_five_cards_render_as_four_then_one(self):
        five = REQUIRED[:5]
        p4 = _page4(_render(five, required=five))
        self.assertEqual(len(re.findall(r'<td width="25%" valign="top"', p4)), 5)
        self.assertEqual(len(re.findall(r'<td width="25%"></td>', p4)), 3)

    def test_the_last_row_is_PADDED_so_its_cards_keep_their_width(self):
        """Three cards stretched across a page do not match the four above
        them."""
        p4 = _page4(_render(REQUIRED))
        self.assertIn('<td width="25%"></td>', p4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
