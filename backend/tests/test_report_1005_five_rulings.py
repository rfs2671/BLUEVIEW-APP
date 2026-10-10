"""THE INVESTOR REPORT FOR 588 THOMAS, 2026-10-05 (REPORT #40), RULED 2026-10-10.

Five defects on one page, and the fixture below is that day's filed content,
reduced to the fields the report reads:

  1. Three "Contractor not recorded" rows. They were BreezCo's three new hires:
     the daily log built its crews from the gate at 13:12, before the CP
     assigned them to BreezCo at 13:18, and the filed log never learned it.
     RULED: fold a company-less gate row into its company via that day's
     check-ins; drop whatever still has no company (no render, no count).
  2. The executive summary was the trade list in lower case. RULED: the
     approved wording, assembled from filed content only.
  3. "Counts aligned" / "Count variance" badges. RULED: removed; the two
     numbers stay.
  4. Trades at gate run together on one clipped line. RULED: count plus a
     bulleted list, proper case, nothing truncated.
  5. The location tile printed "Unmapped source value: 3rd Floor, 4th Floor,
     ...". RULED: distinct floors in order, no duplicates, the debug string
     never printed, unreadable values omitted.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.report import location_vocabulary as lv  # noqa: E402
from lib.report import model as m  # noqa: E402
from lib.report import renderer as r  # noqa: E402
from lib.report import summary as s  # noqa: E402
from lib.report import view as v  # noqa: E402


def _checkin(wid, company, trade, name=None):
    return {"worker_id": wid, "worker_name": name or f"Worker {wid}",
            "worker_company": company, "trade": trade, "status": "checked_in"}


#: The 22 check-ins, as they stand now: the three new hires carry BreezCo /
#: HVAC because the CP assigned it at 13:18.
CHECKINS = (
    [_checkin(f"a{i}", "Arkon Builders", "Framers") for i in range(13)]
    + [_checkin(f"q{i}", "Quality Plumbing", "Plumber") for i in range(5)]
    + [_checkin("b0", "BreezCo", "HVAC / Mechanical")]
    + [_checkin(w, "BreezCo", "HVAC / Mechanical", name=n) for w, n in (
        ("n1", "Jason J Gudiel Ortiz"),
        ("n2", "Luis Rafael Ayala De La Rosa"),
        ("n3", "Hanual L Castillo"))]
)


def _crew(company, trade, n, desc, where, **extra):
    row = {"company": company, "trade": trade, "num_workers": str(n),
           "work_description": desc, "work_locations": where, "photos": []}
    row.update(extra)
    return row


def _blank(wid, name):
    """A crew the log built from the gate for a man with no company yet."""
    return {"company": "", "trade": "", "num_workers": "1",
            "work_description": "", "work_locations": "", "photos": [],
            "gate_sourced": True, "worker_ids": [wid], "worker_names": [name]}


ACTIVITIES = [
    _crew("Arkon Builders", "Framing", 13, "framing (layout, track and studs)",
          "3rd Floor, 4th Floor"),
    _crew("Quality Plumbing", "Plumbing", 5, "MEP rough-in, Plumbing",
          "1st Floor, 2nd Floor, 3rd Floor, 4th Floor"),
    _crew("BreezCo", "HVAC / Mechanical", 1, "ductwork rough, Duct work",
          "1st Floor, 2nd Floor"),
    _blank("n1", "Jason J Gudiel Ortiz"),
    _blank("n2", "Luis Rafael Ayala De La Rosa"),
    _blank("n3", "Hanual L Castillo"),
]

TOOLBOX = {"meeting_time": "08:00 AM",
           "attendees": [{"name": f"p{i}"} for i in range(22)]}
CHECKLIST = {k: {"result": "pass"} for k in (
    "street_frontage", "fire_safety", "perimeter_fence", "fall_protections",
    "neighbors_property", "license_spot_check", "plans", "permits")}
CHECKLIST["other_checklist"] = {"result": None, "note": "1st thru 4th "}
SUPERINTENDENT = {"incidents": {"none_to_report": True},
                  "unsafe_conditions": {"none_to_report": True},
                  "dob_actions": {"none_to_report": True},
                  "orders_given": {"none_to_report": True}}


def _model(activities=ACTIVITIES, checkins=CHECKINS):
    gate = m.GateDayState(list(checkins))
    acts = m.resolve_activities(list(activities), gate)
    return m.ReportDisplayModel(
        project={}, date="2026-10-05", gate=gate, activities=acts,
        safety=m.SafetyState({"x": 1}, "Clear"),
        required_logs=m.RequiredLogsState(["daily_jobsite"], ["daily_jobsite"],
                                          ["daily_jobsite"]),
        weather=["Sunny"])


def _view(model, **kw):
    return v.build(model, address="588 Thomas S Boyland Street",
                   city="Brooklyn, NY", date_long="5 October 2026",
                   generated="g", report_number="Report #40",
                   headline=kw.get("headline", s.headline(model)),
                   summary_body=kw.get("body"), cards=[],
                   photo_url=lambda *a: "/".join(map(str, a[1:3])),
                   logbook_id="L")


# ══════════════════════════════════════════════════════════════════════════
#  1. THE FOLD
# ══════════════════════════════════════════════════════════════════════════

class OneTheBlankGateRowsFoldIntoBreezCo(unittest.TestCase):

    def test_breezco_is_four_on_the_log_and_four_at_the_gate(self):
        model = _model()
        breezco = [a for a in model.activities if a.company == "BreezCo"]
        self.assertEqual(len(breezco), 1)
        self.assertEqual(breezco[0].log_count, 4)
        self.assertEqual(breezco[0].gate_count, 4)
        self.assertEqual(breezco[0].statement,
                         "4 on daily log · 4 gate check-ins")
        self.assertEqual(breezco[0].folded_indices, [3, 4, 5])

    def test_no_row_reads_contractor_not_recorded(self):
        html = r.render(_view(_model()))
        self.assertNotIn(m.UNNAMED_CONTRACTOR, html)
        self.assertEqual([a.company for a in _model().activities],
                         ["Arkon Builders", "Quality Plumbing", "BreezCo"])

    def test_a_row_whose_man_has_no_company_anywhere_is_dropped(self):
        """No render, no count -- and counted as dropped, so the page's three
        rows against the log's seven has an answer."""
        acts = ACTIVITIES + [_blank("ghost", "Nobody Known")]
        model = _model(activities=acts)
        self.assertEqual(len(model.activities), 3)
        self.assertEqual(model.unnamed_rows_dropped, 1)

    def test_a_typed_row_with_no_company_is_dropped_too(self):
        """"Drop whatever still has no company" -- not only gate rows."""
        acts = ACTIVITIES + [_crew("", "", 2, "cleanup", "1st Floor")]
        model = _model(activities=acts)
        self.assertNotIn("", [a.company for a in model.activities])
        self.assertEqual(model.unnamed_rows_dropped, 1)

    def test_with_no_row_for_the_company_the_blank_row_becomes_its_row(self):
        acts = [ACTIVITIES[0], _blank("n1", "Jason J Gudiel Ortiz")]
        model = _model(activities=acts)
        self.assertEqual([a.company for a in model.activities],
                         ["Arkon Builders", "BreezCo"])
        self.assertEqual(model.activities[1].log_count, 1)

    def test_a_row_whose_men_resolve_to_two_companies_is_not_guessed(self):
        row = _blank("n1", "x")
        row["worker_ids"] = ["n1", "a0"]
        model = _model(activities=[ACTIVITIES[0], row])
        self.assertEqual(len(model.activities), 1)
        self.assertEqual(model.activities[0].log_count, 13)
        self.assertEqual(model.unnamed_rows_dropped, 1)

    def test_names_resolve_a_row_that_carries_no_ids(self):
        row = _blank("n1", "Jason J Gudiel Ortiz")
        row["worker_ids"] = []
        model = _model(activities=[ACTIVITIES[2], row])
        self.assertEqual(model.activities[0].log_count, 2)

    def test_the_placeholder_company_resolves_nothing(self):
        cis = [_checkin("n1", "UNASSIGNED", "")]
        model = _model(activities=[_blank("n1", "x")], checkins=cis)
        self.assertEqual(model.activities, [])

    def test_a_folded_rows_photographs_keep_their_own_stored_index(self):
        """The photo endpoint reads data.activities[ai].photos[pi]. A folded
        row's photograph lives under ITS index, not the row it joined."""
        blank = _blank("n1", "x")
        blank["photos"] = [{"p": 1}]
        acts = [ACTIVITIES[2], {"company": "Other Co", "num_workers": "1"}, blank]
        view = _view(_model(activities=acts))
        self.assertEqual([p.url for p in view.bands[0].photos], ["2/0"])

    def test_the_fold_reads_the_filed_log_and_writes_nothing(self):
        acts = [dict(a) for a in ACTIVITIES]
        _model(activities=acts)
        self.assertEqual(acts, ACTIVITIES)


# ══════════════════════════════════════════════════════════════════════════
#  2. THE EXECUTIVE SUMMARY
# ══════════════════════════════════════════════════════════════════════════

class TwoTheSummaryIsTheApprovedWording(unittest.TestCase):

    def test_the_headline(self):
        self.assertEqual(
            s.headline(_model()),
            "Framing on the 3rd–4th floors, Plumbing on the 1st–4th, "
            "HVAC / Mechanical on the 1st–2nd.")

    def test_the_body(self):
        self.assertEqual(
            s.body(_model(), toolbox=TOOLBOX, checklist=CHECKLIST,
                   superintendent=SUPERINTENDENT),
            "Arkon Builders (13) worked on framing (layout, track and studs) "
            "on the 3rd and 4th floors. Quality Plumbing (5) worked on MEP "
            "rough-in, Plumbing on the 1st through 4th floors. BreezCo (4) "
            "worked on ductwork rough, Duct work on the 1st and 2nd floors. "
            "The toolbox talk at 8:00 AM had 22 attendees. The daily site "
            "inspection passed on every item, and the superintendent reported "
            "no incidents, unsafe conditions or DOB actions.")

    def test_every_description_is_the_filed_string(self):
        body = s.body(_model())
        for a in ACTIVITIES[:3]:
            desc = a["work_description"]
            self.assertIn(desc[0].lower() + desc[1:]
                          if desc[1:2].islower() else desc, body)

    def test_no_superintendent_log_no_safety_clause(self):
        """Not reported is not none. Without the filed log the summary says
        nothing about incidents."""
        body = s.body(_model(), toolbox=TOOLBOX, checklist=CHECKLIST,
                      superintendent=None)
        self.assertNotIn("incident", body)
        self.assertTrue(body.endswith("passed on every item."))

    def test_an_unanswered_section_is_not_reported_as_none(self):
        sup = dict(SUPERINTENDENT)
        del sup["dob_actions"]
        body = s.body(_model(), superintendent=sup)
        self.assertIn("reported no incidents or unsafe conditions", body)
        self.assertNotIn("DOB", body)

    def test_a_reported_section_is_said_to_be_recorded(self):
        sup = dict(SUPERINTENDENT, incidents={"description": "cut hand"})
        body = s.body(_model(), superintendent=sup)
        self.assertIn("reported no unsafe conditions or DOB actions and "
                      "recorded incidents", body)

    def test_a_failed_item_is_counted_not_hidden(self):
        chk = dict(CHECKLIST, plans={"result": "fail"})
        self.assertIn("recorded 1 failed item", s.body(_model(), checklist=chk))

    def test_no_toolbox_no_toolbox_sentence(self):
        self.assertNotIn("toolbox", s.body(_model(), toolbox=None))

    def test_a_count_prints_only_where_the_log_recorded_one(self):
        acts = [_crew("Arkon Builders", "Framing", "", "framing", "3rd Floor")]
        self.assertTrue(s.body(_model(activities=acts)).startswith(
            "Arkon Builders worked on framing on the 3rd floor."))

    def test_no_crew_falls_back_to_the_counts_sentence(self):
        model = _model(activities=[])
        self.assertIsNone(s.body(model))
        self.assertEqual(s.headline(model), "No activity documented")
        self.assertIn("checked in through the gate",
                      _view(model, body=None).summary.body)


# ══════════════════════════════════════════════════════════════════════════
#  3. THE BADGES
# ══════════════════════════════════════════════════════════════════════════

class ThreeTheBadgesAreGoneAndTheNumbersStay(unittest.TestCase):

    def test_no_badge_wording_and_no_chip_element(self):
        acts = ACTIVITIES + [_crew("Power Direct", "Electrical", 3, "x", "")]
        html = r.render(_view(_model(activities=acts)))
        for word in ("Counts aligned", "Count variance", "Count not recorded",
                     "Documented activity", 'class="chip"'):
            self.assertNotIn(word, html)
        self.assertIn("13 on daily log · 13 gate check-ins", html)
        self.assertIn("3 on daily log · 0 matched gate check-ins", html)


# ══════════════════════════════════════════════════════════════════════════
#  4. TRADES AT GATE
# ══════════════════════════════════════════════════════════════════════════

class FourTradesAtGateAreAList(unittest.TestCase):

    def test_count_and_one_item_per_trade(self):
        cell = _view(_model()).rail[1]
        self.assertEqual((cell.value, cell.label), ("3", "Trades at gate"))
        self.assertEqual(cell.items, ("Framers", "HVAC / Mechanical", "Plumber"))
        self.assertFalse(any(" · " in n for n in cell.notes))

    def test_proper_case_and_one_entry_per_trade(self):
        cis = [_checkin("1", "A", "plumber"), _checkin("2", "A", "Plumber"),
               _checkin("3", "B", "HVAC / Mechanical")]
        self.assertEqual(m.GateDayState(cis).trades,
                         ["HVAC / Mechanical", "Plumber"])

    def test_rendered_as_bullets_with_nothing_clipped(self):
        html = r.render(_view(_model()))
        self.assertIn('<ul class="ri"><li>Framers</li><li>HVAC / Mechanical'
                      '</li><li>Plumber</li></ul>', html)
        css = html[html.index(".p1 ul.ri"):]
        css = css[:css.index("}")]
        self.assertNotIn("nowrap", css)
        self.assertNotIn("ellipsis", css)


# ══════════════════════════════════════════════════════════════════════════
#  5. THE LOCATION TILE
# ══════════════════════════════════════════════════════════════════════════

class FiveTheLocationTile(unittest.TestCase):

    def test_1005_reads_four_distinct_floors_in_order(self):
        value, label, notes = _model().day_location().rail()
        self.assertEqual((value, label), ("4", "Active areas"))
        self.assertEqual(notes, ["L4 / L3 / L2 / L1"])

    def test_the_debug_string_is_never_printed(self):
        acts = ACTIVITIES + [_crew("Power Direct", "Electrical", 3, "x",
                                   "Somewhere else: stair 2")]
        html = r.render(_view(_model(activities=acts)))
        self.assertNotIn("Unmapped", html)
        self.assertNotIn("stair 2", html)

    def test_every_chip_label_the_app_emits_is_read(self):
        res = lv.resolve(["Sub-cellar, Cellar, 1st Floor, Mezzanine, "
                          "2nd Floor, 12th Floor, Roof"])
        self.assertEqual(res.areas, ["ROOF", "L12", "L2", "MEZZ", "L1",
                                     "CELLAR", "SUBCELLAR"])
        self.assertEqual(res.unmapped, [])

    def test_a_wrong_suffix_is_not_a_chip(self):
        self.assertEqual(lv.resolve(["2th Floor"]).areas, [])
        self.assertEqual(lv.resolve(["11st Floor"]).areas, [])
        self.assertEqual(lv.resolve(["11th Floor"]).areas, ["L11"])

    def test_a_hand_typed_key_with_a_comma_still_reads_whole(self):
        self.assertEqual(lv.resolve(["Foundation, Ex. 2&4"]).areas,
                         ["FDN", "EX"])

    def test_a_readable_part_is_kept_beside_an_unreadable_one(self):
        res = lv.resolve(["3rd Floor, Stair 2"])
        self.assertEqual(res.areas, ["L3"])
        self.assertEqual(res.unmapped, ["Stair 2"])

    def test_the_row_omits_what_it_cannot_read(self):
        acts = [_crew("Power Direct", "Electrical", 3, "x", "J")]
        row = _view(_model(activities=acts)).activities[0]
        self.assertEqual(row.where, "")


if __name__ == "__main__":
    unittest.main()
