"""Attention pass 1 (Oct 2026) as a regression fixture.

The 17 lines of the solo test pass, in order, each with the label it should
get (tests/fixtures/attention/pass1_2026_10.json). What pass 1 got wrong, and
what this pins:

  * "Inspection moved to Tuesday 10am" came out as an Issue rated High. An
    issue is a problem (defect, delay, safety, blocked work): a schedule or
    info update is not one and is dropped, whatever the model says. And
    severity is only ever what the message states: "high" needs the message
    to say so, never the topic.
  * The last three lines, and two commitments before them, never reached the
    model: the cheap filter had no word for them. Not lag (the worker runs
    every 5 minutes, 200 rows per group, 400 model calls a run).

The model is scripted here (the expected labels, plus pass 1's wrong answer
on line 7) so the code around it is what is tested. scripts/
attention_fixture_eval.py runs the same lines through the real model.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import wa_attention as wa  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    T0, _Model, _first_sight, _items, _msg, _tick, _world,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "attention"
                      / "pass1_2026_10.json").read_text())
LINES = FIXTURE["lines"]
SENDER = {"A": "17185551001", "B": "17185551002",
          "C": "17185551003", "D": "17185551004"}


def _expect(kind):
    return [ln for ln in LINES if ln["expect"]["kind"] == kind]


def _scripted_model():
    """The labels the fixture expects, and pass 1's wrong answer on line 7
    (an Issue, High). Lines that are not items get nothing."""
    answers = {}
    for ln in LINES:
        e = ln["expect"]
        if e["kind"] == "item":
            answers[ln["body"]] = [{
                "type": e["type"], "quote": ln["body"], "summary": ln["body"][:60],
                "owner_text": e.get("owner_text"), "due_text": e.get("due_text"),
                # The model says high on everything: none of it may stick.
                "importance": "high", "tags": []}]
        elif ln.get("pass1"):
            answers[ln["body"]] = [{
                "type": ln["pass1"]["type"], "quote": ln["body"],
                "summary": "Inspection moved", "owner_text": None,
                "due_text": "Tuesday 10am", "importance": ln["pass1"]["importance"],
                "tags": ["inspection"]}]
    return _Model(answers)


class TheFixture(unittest.TestCase):

    def test_seventeen_lines_in_order(self):
        self.assertEqual([ln["n"] for ln in LINES], list(range(1, 18)))
        self.assertEqual(len(_expect("item")), 10)

    def test_every_line_with_something_to_record_reaches_the_model(self):
        # Pass 1 lost lines 12, 14 and 17 (and the 15/16 updates) here.
        for ln in LINES:
            if ln["expect"]["kind"] == "none" or ln.get("file"):
                continue
            self.assertIsNotNone(wa.filter_reason({"body": ln["body"]}),
                                 f"line {ln['n']}: {ln['body']}")

    def test_noise_still_costs_nothing(self):
        for body in ("Great, another rain day, love this job",
                     "Why does this always happen to us"):
            self.assertIsNone(wa.filter_reason({"body": body}), body)

    def test_nothing_here_states_a_severity(self):
        for ln in LINES:
            got = wa.importance("high", ln["body"])
            self.assertEqual(got["importance"], "normal", f"line {ln['n']}")
            self.assertEqual(got["importance_source"], "capped")

    def test_nothing_here_is_a_problem(self):
        for ln in LINES:
            self.assertFalse(wa.names_a_problem(ln["body"]), f"line {ln['n']}")

    def test_due_dates_the_code_reads(self):
        sent = T0                                   # Thursday Oct 8, 10 AM ET
        self.assertEqual(wa.parse_due("by tomorrow", sent), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("by Friday EOD", sent), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("7am Thursday", sent), date(2026, 10, 15))
        self.assertEqual(wa.parse_due("by the 15th", sent), date(2026, 10, 15))
        self.assertIsNone(wa.parse_due("later", sent))


class ThePassReplayed(unittest.TestCase):
    """All 17 lines through the worker, one run, as they were sent."""

    @classmethod
    def setUpClass(cls):
        db = _world()
        _first_sight(db)
        ids = {}
        for ln in LINES:
            kw = {}
            if ln.get("reply_to"):
                kw["quoted_message_id"] = ids[ln["reply_to"]]
                kw["quoted_author"] = SENDER[LINES[ln["reply_to"] - 1]["from"]] + "@c.us"
            if ln.get("file"):
                kw["media_type"] = "document"
                kw["file_name"] = ln["file"]
            row = _msg(db, ln["body"], sender=SENDER[ln["from"]],
                       at=T0 + timedelta(minutes=ln["n"]), **kw)
            ids[ln["n"]] = row["message_id"]
        cls.model = _scripted_model()
        cls.report, cls.sends = _tick(db, cls.model, T0 + timedelta(minutes=30))
        cls.items = _items(db)
        cls.by_quote = {it["evidence"]["quote"]: it for it in cls.items}

    def test_nothing_is_sent(self):
        self.assertEqual(self.sends, [])

    def test_the_inspection_line_is_not_an_issue(self):
        self.assertNotIn("Inspection moved to Tuesday 10am", self.by_quote)
        self.assertEqual(self.report["dropped_not_issue"], 1)
        self.assertFalse([it for it in self.items if it["type"] == "issue"])

    def test_exactly_the_expected_items(self):
        want = {ln["body"]: ln["expect"] for ln in _expect("item")}
        self.assertEqual(set(self.by_quote), set(want))
        for body, e in want.items():
            it = self.by_quote[body]
            self.assertEqual(it["type"], e["type"], body)
            self.assertEqual(it["due"]["due_text"], e.get("due_text"), body)
            # The script's one-letter names ("B, can you...") are below the
            # 3 characters a quoted piece needs, so only "Everyone" is kept.
            if len(e.get("owner_text") or "") >= 3:
                self.assertEqual(it["owner"]["owner_text"], e["owner_text"], body)
            if e.get("owner"):        # a commitment is its sender's
                self.assertEqual(it["evidence"]["sender"], SENDER[e["owner"]], body)

    def test_no_item_is_high(self):
        self.assertEqual({it["importance"] for it in self.items}, {"normal"})

    def test_updates_are_not_new_items(self):
        for ln in _expect("state"):
            if ln["body"]:
                self.assertNotIn(ln["body"], self.by_quote, f"line {ln['n']}")

    def test_the_model_saw_the_lines_pass_1_missed(self):
        seen = "\n".join(c.split(">>> ", 1)[1] for c in self.model.calls)
        for n in (12, 14, 15, 16, 17):
            self.assertIn(LINES[n - 1]["body"], seen, f"line {n}")
        self.assertEqual(self.report["filtered_out"], 3)   # 4, 5 and the file



class ARealIssueStillCounts(unittest.TestCase):

    def test_a_problem_is_kept_and_rated_as_stated(self):
        db = _world()
        _first_sight(db)
        _msg(db, "Leak on 4 again, ceiling is wet")
        _msg(db, "URGENT stop work, scaffold on 6 is unsafe")
        model = _Model({
            "Leak on 4": [{"type": "issue", "quote": "Leak on 4 again",
                           "summary": "Leak on 4", "importance": "high"}],
            "scaffold": [{"type": "issue", "quote": "scaffold on 6 is unsafe",
                          "summary": "Unsafe scaffold", "importance": "normal"}],
        })
        report, _ = _tick(db, model, T0 + timedelta(hours=1))
        got = {it["summary"]: it["importance"] for it in _items(db)}
        self.assertEqual(got, {"Leak on 4": "normal", "Unsafe scaffold": "high"})
        self.assertEqual(report["dropped_not_issue"], 0)


if __name__ == "__main__":
    unittest.main()
