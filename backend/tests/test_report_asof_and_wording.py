"""Defects two fresh readers found in sample reports (2026-11-22), each pinned here.

  * COMING UP listed a hearing for a violation issued after the report's period: a report for a past period is
    prepared from today's event rows, and an event first recorded after the anchor day was not upcoming then.
  * The report's flag read "Watch" above a risk printed HIGH.
  * The estimate was counted over the floors a log had named so far, so on a 22-floor schedule a trade on 17 floors
    was "of 17", and nothing said so. With a confirmed schedule the floors it names are counted; either way the
    report says what it counted over, and prints the count behind each estimate.
  * A federal holiday that was worked was counted as a working day while the note said it was excluded.
  * Wording: a sentence run into the next, "their photographs", "Current / actual", "violation or orders",
    "OPEN ACTIVE", the same activity listed twice, a WhatsApp line naming three subs of five and saying nothing more.
"""
import re
import unittest
from datetime import date, datetime, timezone

from lib import progress_report as P
from lib import progress_report_render as RR
from lib import progress_stages as ST
from lib import report_calendar

D = date


def row(day, work, where, company="Northline Mechanical", trade="HVAC"):
    return {"date": day, "work": work, "where": where, "company": company, "trade": trade, "work_trades": [trade]}


class ComingUpKnowsOnlyWhatWasKnown(unittest.TestCase):
    EV = {"source": "city", "date": "2026-12-08", "kind": "hearing", "title": "OATH hearing, violation ECB-0412",
          "status": "open"}

    def test_an_event_first_recorded_after_the_period_is_left_out(self):
        late = dict(self.EV, created_at=datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(P.coming_up([late], D(2026, 11, 8), None, {"expiring": []}), [])

    def test_the_same_event_is_listed_once_it_was_known(self):
        late = dict(self.EV, created_at=datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc))
        got = P.coming_up([late], D(2026, 11, 18), None, {"expiring": []})
        self.assertEqual([u["what"] for u in got], ["OATH hearing, violation ECB-0412"])

    def test_an_event_with_no_recorded_day_is_listed_as_before(self):
        got = P.coming_up([dict(self.EV)], D(2026, 11, 8), None, {"expiring": []})
        self.assertEqual(len(got), 1)

    def test_a_day_given_as_text_is_read_too(self):
        late = dict(self.EV, created_at="2026-11-16")
        self.assertEqual(P.coming_up([late], D(2026, 11, 15), None, {"expiring": []}), [])


class TheFlagTakesTheWordOfItsHighestRisk(unittest.TestCase):
    def status(self, *levels):
        rep = {"risks": [{"level": lv} for lv in levels], "regulatory": {"coverage": {"state": "verified"}}}
        return P.status(rep)["label"]

    def test_each_level(self):
        self.assertEqual(self.status("high", "watch"), "High risk")
        self.assertEqual(self.status("watch"), "Watch")
        self.assertEqual(self.status("critical", "high"), "Needs attention")
        self.assertEqual(self.status(), "No flagged issues")


class TheEstimateSaysWhatItIsCountedOver(unittest.TestCase):
    def rows(self):
        out = []
        for f in range(1, 9):                       # ductwork reported complete on floors 1-8
            out.append(row(D(2026, 9, f), "Supply and return ductwork complete", f"Floor {f}"))
        out.append(row(D(2026, 11, 17), "Supply and return ductwork", "Floor 9"))
        return out

    def test_without_a_schedule_only_logged_floors_count_and_it_says_so(self):
        b = ST.build(self.rows(), end=D(2026, 11, 18))
        self.assertEqual(b["floors"], list(range(1, 10)))
        self.assertEqual(b["floors_from_schedule"], [])
        self.assertIn("is not told how many floors the job has", ST.floors_basis(b))

    def test_floors_the_schedule_names_are_counted(self):
        b = ST.build(self.rows(), end=D(2026, 11, 18), plan_floors=range(1, 23))
        self.assertEqual(len(b["floors"]), 22)
        self.assertEqual(b["floors_from_schedule"], list(range(10, 23)))
        t = b["trades"]["hvac"] if "hvac" in b["trades"] else next(iter(b["trades"].values()))
        self.assertEqual(t["counts"], {"done": 8, "under_way": 1, "of": 22})
        self.assertEqual(t["estimate"], 40)         # (8 + 0.5) / 22 = 38.6 -> 40; over 9 floors it read 95
        self.assertEqual(ST.counts_words(t), "8 of 22 floors appear complete, 1 under way")
        self.assertIn("Counted over 22 floors", ST.floors_basis(b))
        self.assertIn("floors 10–22", ST.floors_basis(b))

    def test_the_weeks_before_are_counted_over_the_same_floors(self):
        b = ST.build(self.rows(), end=D(2026, 11, 18), plan_floors=range(1, 23))
        first = next(h for h in b["history"] if h["estimates"])
        self.assertLessEqual(max(first["estimates"].values()), 40)


class AHolidayThatWasWorkedIsNotNamedAsExcluded(unittest.TestCase):
    def test_the_note_names_only_the_holidays_left_out(self):
        vets = D(2026, 11, 11)
        self.assertTrue(any("Veterans" in n for n in report_calendar.holiday_names(D(2026, 11, 5), D(2026, 11, 18))))
        named = report_calendar.holiday_names(D(2026, 11, 5), D(2026, 11, 18), worked=[vets])
        self.assertEqual([n for n in named if "Veterans" in n], [])


class RainIsAWord(unittest.TestCase):
    def test_rain_is_not_mended_to_drain(self):
        fixes = P.spelling_fixes(["Rain. Deck work stopped at 10 a.m.", "Water main tie-in", "Drain lines floors 1-2"])
        self.assertEqual({k: v for k, v in fixes.items() if k in ("rain", "main")}, {})


class TheWording(unittest.TestCase):
    def test_one_activity_reported_complete_later_is_one_line(self):
        self.assertEqual(P._phrase_key("Electrical rough-in"), P._phrase_key("Electrical rough-in complete"))

    def test_a_line_over_floors_not_all_complete_does_not_say_complete(self):
        def act(day, work, floor):
            return {"key": "brightway", "date": day, "work": work, "floors": [floor], "where": f"Floor {floor}",
                    "amended": False}
        cur = [act(D(2026, 11, 9), "Electrical rough-in complete", 12), act(D(2026, 11, 10), "Electrical rough-in", 13)]
        subs = [{"key": "brightway", "name": "Brightway Electric", "trade": "Electrical"}]
        items = P._work(cur, [], {}, subs)[0]["items"]
        self.assertEqual([(i["work"], i["floors"]) for i in items], [("Electrical rough-in", [12, 13])])
        both = [act(D(2026, 11, 9), "Electrical rough-in complete", 12)]
        self.assertEqual(P._work(both, [], {}, subs)[0]["items"][0]["work"], "Electrical rough-in complete")

    def test_the_whatsapp_line_counts_the_subs_it_does_not_name(self):
        work = [{"name": f"Sub {i}", "items": [{"work": f"Work {i}", "place": ""}]} for i in range(5)]
        rep = {"job": "Job", "period_short": "Nov 5–18", "work": work, "subs": work, "schedule": None,
               "site": {"worked": 0}, "prev": {"days": 0}, "regulatory": {"coverage": {"state": "unknown"}}}
        line = next(x for x in P.whatsapp_message(rep).splitlines() if x.startswith("- Work:"))
        self.assertTrue(line.endswith(", +2 more in the report"), line)

    def test_a_record_prints_one_status_word(self):
        r = {"kind": "DOB violation", "number": "1", "issued": D(2026, 11, 1), "status": "ACTIVE", "closed": False,
             "type": "violation", "ref_id": "R1"}
        cell = RR._reg_row(r)
        self.assertEqual(len(re.findall(r"\bACTIVE\b", cell)), 0, cell)
        self.assertEqual(len(re.findall(r">OPEN<", cell)), 1, cell)
        r2 = dict(r, status="HEARING SCHEDULED")
        self.assertIn("city status:</span> HEARING SCHEDULED", RR._reg_row(r2))
        r3 = dict(r, status="CLOSED", closed=True)
        self.assertEqual(len(re.findall(r"CLOSED", RR._reg_row(r3))), 1)


if __name__ == "__main__":
    unittest.main()
