"""ONE CANONICAL TRADE LIST EVERYWHERE -- REPORT, GATE, CHIPS. Ruled 2026-10-10.

The investor report for 588 Thomas on 2026-10-05 listed "Plumber" among the
trades at the gate beside "Framers" and "HVAC / Mechanical". The operator:
"Plumbing", not "Plumber", and one canonical list everywhere.

THE LIST ALREADY EXISTED (TRADE_VOCABULARY, with its immutability rule), and it
already said "Framing" where 588's roster says "Framers". What was missing is
that no screen printed through it: the gate, the crew chips and the report all
echoed the roster's stored string. So:

  - "Plumbing" replaces "Plumber" in the vocabulary, and "Plumber" is
    DEPRECATED, never re-spelled on a stored row (the published rule);
  - `_trade_label` is the one display rule, and the gate, the report and the
    app's crew chip (frontend dailyJobsiteModel.canonicalTrade) print through
    it;
  - every MATCH still compares the raw stored string.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
CHECKIN = (BACKEND / "checkin.html").read_text(encoding="utf-8")


class TheLabelRule(unittest.TestCase):

    def test_plumber_reads_as_plumbing(self):
        self.assertEqual(server._trade_label("Plumber"), "Plumbing")
        self.assertEqual(server._trade_label(" plumber "), "Plumbing")

    def test_every_deprecated_label_reads_as_its_successor(self):
        for old, new in server.DEPRECATED_TRADES.items():
            self.assertEqual(server._trade_label(old), new, old)

    def test_588s_roster_strings(self):
        self.assertEqual(server._trade_label("Framers"), "Framing")
        self.assertEqual(server._trade_label("HVAC / Mechanical"),
                         "HVAC / Mechanical")

    def test_a_case_variant_reads_as_the_vocabulary_spells_it(self):
        self.assertEqual(server._trade_label("hvac / mechanical"),
                         "HVAC / Mechanical")

    def test_a_custom_trade_and_the_placeholder_read_as_stored(self):
        self.assertEqual(server._trade_label("Laborer"), "Laborer")
        self.assertEqual(server._trade_label("UNASSIGNED"), "UNASSIGNED")
        self.assertEqual(server._trade_label(None), "")

    def test_every_label_it_returns_is_an_active_vocabulary_entry(self):
        """A label that is itself deprecated would be a second hop nobody
        takes -- the screen would print a name the picker no longer offers."""
        for t in list(server.TRADE_VOCABULARY) + list(server.DEPRECATED_TRADES):
            self.assertIn(server._trade_label(t), server.TRADE_VOCABULARY, t)


class TheGatePrintsTheLabelAndSubmitsTheRawTrade(unittest.TestCase):

    def test_the_roster_carries_the_label_beside_the_raw_trade(self):
        src = inspect.getsource(server.get_checkin_info)
        self.assertIn('"trade": t, "company": c,', src)
        self.assertIn('"trade_label": _trade_label(t)', src)

    def test_the_returning_worker_carries_the_label(self):
        src = inspect.getsource(server.lookup_worker)
        self.assertIn('"trade_label": _trade_label(pair["trade"])', src)
        self.assertIn('"trade": pair["trade"] if pair else None', src)

    def test_the_option_reads_the_label(self):
        self.assertIn("opt.textContent = (a.trade_label || a.trade) + ' — ' "
                      "+ a.company;", CHECKIN)
        self.assertIsNone(re.search(r"opt\.textContent = a\.trade \+", CHECKIN))

    def test_the_returning_screen_reads_the_label(self):
        self.assertIn("worker.trade_label || worker.trade", CHECKIN)

    def test_the_roster_match_still_compares_the_raw_trade(self):
        """The label is never sent back as a pick: a returning plumber stored
        as "Plumber" must still match a roster row stored as "Plumber"."""
        self.assertNotIn("rosterKey(a.trade_label", CHECKIN)
        self.assertIn("rosterKey(a.trade) === rosterKey(returningWorker.trade)",
                      CHECKIN)


class TheReportPrintsTheLabel(unittest.TestCase):

    SRC = inspect.getsource(server.generate_combined_report)

    def test_gate_trades_and_activity_trades_go_through_it(self):
        self.assertIn('dict(c, trade=_trade_label(c.get("trade"))) for c in '
                      'checkins', self.SRC)
        self.assertIn('dict(r, trade=_trade_label(r.get("trade")))', self.SRC)

    def test_1005_reads_framing_plumbing_hvac(self):
        from lib.report import model as m
        from lib.report import summary as s
        rows = [{"worker_id": "1", "worker_company": "Arkon Builders",
                 "trade": "Framers"},
                {"worker_id": "2", "worker_company": "Quality Plumbing",
                 "trade": "Plumber"},
                {"worker_id": "3", "worker_company": "BreezCo",
                 "trade": "HVAC / Mechanical"}]
        gate = m.GateDayState(
            [dict(c, trade=server._trade_label(c["trade"])) for c in rows])
        self.assertEqual(gate.trades, ["Framing", "HVAC / Mechanical",
                                       "Plumbing"])
        acts = m.resolve_activities(
            [dict(company=r["worker_company"], num_workers="1",
                  work_locations="1st Floor",
                  trade=server._trade_label(r["trade"])) for r in rows], gate)
        model = m.ReportDisplayModel(
            project={}, date="2026-10-05", gate=gate, activities=acts,
            safety=m.SafetyState(None),
            required_logs=m.RequiredLogsState([], [], []), weather=[])
        self.assertEqual(s.headline(model),
                         "Framing on the 1st floor, Plumbing on the 1st, "
                         "HVAC / Mechanical on the 1st.")

    def test_the_orientation_count_reads_the_stored_rows(self):
        """The labelled rows are COPIES; the coverage count is handed the
        rows as queried."""
        self.assertIn("_oriented_on_site_count(project_id, checkins)", self.SRC)


if __name__ == "__main__":
    unittest.main()
