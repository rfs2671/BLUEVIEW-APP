"""Adversarial review 2 (section B): two more replies the reader took for
"checked, nothing found", and the general rule that closes the class.

THE RULE. A list is CHECKED only when the reply positively IS the refreshed
list and its own count agrees with the rows read:
  inspection list  the delta re-renders the inspection update panel AND carries
                   the refresh's own markers (panelsToRefreshIDs naming that
                   panel, the onCompletedListLoaded startup script); a list
                   with rows states "Completed Inspections: (N)" and N equals
                   the rows; an EMPTY list is checked only when the record
                   itself shows no results (the real empty reply and an
                   un-refreshed panel carry the same words, so the record is
                   the only corroboration there is).
  search           a results grid's "Showing a-b of N" equals the rows read
                   across all pages; the no-results notice counts only with
                   no stated total, no grid and no pager.
Any missing marker or disagreeing count is unrecognised / partial, never checked.
"""

from __future__ import annotations

import re
import unittest

from lib import dob_now_inspections as D
from lib import dob_now_portal as P
from lib import source_coverage as SC
from tests import dob_now_fake as F

S5 = "B01141294S5PL"


def _segments(text):
    return D.delta_segments(text)


def _static_panel_delta(with_markers: bool) -> str:
    """The record's STATIC inspection panel (placeholder: 'There are no
    completed inspections') sent back as the list postback's delta: what an
    un-refreshed re-render returns. B01141294-S5 has 3 completed inspections."""
    static = F.fixture(f"record_{S5}.html")
    i = static.find('<div id="ctl00_PlaceHolderMain_InspectionList_inspectionUpdatePanel">')
    panel = static[i + len('<div id="ctl00_PlaceHolderMain_InspectionList_inspectionUpdatePanel">'):]
    segs = [("updatePanel", "ctl00_PlaceHolderMain_InspectionList_inspectionUpdatePanel", panel),
            ("hiddenField", "__VIEWSTATE", "vs-unrefreshed")]
    if with_markers:
        real = [s for s in _segments(F.fixture(f"inspections_{S5}.txt"))
                if s[0] in ("panelsToRefreshIDs", "scriptStartupBlock")]
        segs += real
    return F.delta(*segs)


def _drop_last_row(text: str) -> str:
    """The real S5 delta with its last completed row removed (count still says 3)."""
    segs = _segments(text)
    out = []
    for t, i, c in segs:
        if t == "updatePanel":
            rows = [m.start() for m in re.finditer(r'<tr class="InspectionListRow">', c)]
            end = c.find("</table>", rows[-1])
            c = c[:rows[-1]] + c[end:]
        out.append((t, i, c))
    return F.delta(*out)


class TheUnrefreshedList(unittest.TestCase):
    """Review 2, C2: reproduced on B01141294-S5, which has 3 (incl. 7755632)."""

    def test_an_unrefreshed_panel_even_with_the_markers_is_not_checked(self):
        res = P.check_bins([F.NEW_BIN], F.portal(override={S5: _static_panel_delta(with_markers=True)}))
        s5 = next(r for r in res["records"] if r["record_id"] == S5)
        self.assertIs(s5["inspections"]["loaded"], False)
        self.assertRegex(s5["inspections"]["why"], r"floor-results table shows results")
        self.assertEqual(res["state"], "partial")
        self.assertEqual(P.coverage_entry(res)["state"], SC.NOT_LOADED)
        _items, cov = D.to_evidence(res["records"], "p")
        self.assertIn(S5, cov["lists_not_loaded"])

    def test_without_the_refresh_markers_it_is_not_a_list(self):
        lst = D.parse_inspection_list(_static_panel_delta(with_markers=False))
        self.assertIs(lst["loaded"], False)
        self.assertRegex(lst["why"], r"refresh")

    def test_the_real_replies_still_read(self):
        self.assertEqual(len(D.parse_inspection_list(F.fixture(f"inspections_{S5}.txt"))["completed"]), 3)
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], F.portal())
        self.assertEqual(res["state"], "checked")
        by = {r["record_id"]: r["inspections"] for r in res["records"]}
        # B23173802-S5 and the CERT record: empty, and their records show no results.
        self.assertEqual((by["B23173802S5PL"]["loaded"], by["B23173802S5PL"]["completed"]), (True, []))
        self.assertIs(by["CERT-ADV-PL-26-010624"]["loaded"], True)


class CountsMustAgree(unittest.TestCase):
    """The generic rule: the reply's own count equals the rows read."""

    def test_a_list_whose_count_disagrees_with_its_rows(self):
        short = D.parse_inspection_list(_drop_last_row(F.fixture(f"inspections_{S5}.txt")))
        self.assertIs(short["loaded"], False)
        self.assertRegex(short["why"], r"read 2 of the 3")
        more = F.fixture(f"inspections_{S5}.txt").replace("Completed Inspections:</FONT> (3)",
                                                           "Completed Inspections:</FONT> (2)")
        more = re.sub(r"^\d+", lambda m: str(int(m.group(0))), more, count=1)
        self.assertIs(D.parse_inspection_list(more)["loaded"], False)

    def test_a_list_with_rows_and_no_count_is_not_checked(self):
        no_count = F.fixture(f"inspections_{S5}.txt").replace("Completed Inspections:</FONT> (3)",
                                                               "Completed Inspections:</FONT>    ")
        self.assertIs(D.parse_inspection_list(no_count)["loaded"], False)

    def test_a_search_whose_rows_exceed_its_total(self):
        body = F.search_delta(F.NEW_BIN, 1).replace("Showing 1-3 of 4", "Showing 1-3 of 2")
        res = P.check_bins([F.NEW_BIN], F.portal(search_reply=body))
        self.assertNotEqual(res["state"], "checked")


class TheNoResultsNoticeBesideATotal(unittest.TestCase):
    """Review 2, M7: the notice next to 'Showing 1-10 of 23' and a pager."""

    PAGER = ('<table class="aca_pagination"><tr><td><a href="javascript:__doPostBack(&#39;ctl00$PlaceHolderMain$'
             'dgvPermitList$gdvPermitList$ctl13$ctl03&#39;,&#39;&#39;)">2</a></td></tr></table>')

    def reply(self, rows: str) -> str:
        return F.delta(("updatePanel", "ctl00_PlaceHolderMain_updatePanel",
                        '<span>Showing 1-10 of 23</span><table id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList">'
                        + rows + "</table>" + self.PAGER),
                       ("updatePanel", "ctl00_PlaceHolderMain_updatePanel2",
                        "<span style='display:none'>Your search returned no results.</span>"))

    def test_rows_in_changed_markup_and_a_hidden_notice(self):
        body = self.reply('<tr class="ACA_TabRow_Odd"><td><a href="/x?capID1=A&amp;capID2=B">B0114 (markup changed)</a>'
                          "</td></tr>")
        self.assertNotEqual(P.search_reply_kind(body), "no_results")
        res = P.check_bins([F.NEW_BIN], F.portal(search_reply=body))
        self.assertNotEqual(res["state"], "checked")
        self.assertEqual(P.coverage_entry(res)["state"], SC.UNREACHABLE)

    def test_no_rows_a_total_and_the_notice(self):
        self.assertEqual(P.search_reply_kind(self.reply("")), "unrecognised")

    def test_the_plain_notice_is_still_no_results(self):
        self.assertEqual(P.search_reply_kind(F.no_results_delta()), "no_results")


if __name__ == "__main__":
    unittest.main()
