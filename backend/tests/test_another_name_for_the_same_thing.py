"""The agent may name what it is looking for by another name (ruling 2026-10-25).

Asked what type of AC units 588 Boyland has, search_plans led with three
vision-read notes - "EACH AC UNIT SHALL HAVE A MINI-CONDENSATE PUMP" - which
the project team says are split-system boilerplate, because they print both
AC and UNITS. The PTAC schedule prints PTAC and never AC, matched one word of
two, and ranked eleventh. The drawings never say a PTAC is an AC.

So `search_plans(..., also=["PTAC"])`: each name is matched, floor-checked and
ranked on its own printed words, and a record takes the best place it earns
under any name. Nothing is matched that the sheet does not print, and the
gate is not touched.

Each test asks first whether search_plans takes `also`, so the control run on
main fails by assertion rather than by TypeError.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402

PID = "proj-boyland"

#: The boilerplate, as production stores it: vision-read, on M-101 to M-103.
BOILERPLATE = [
    {"sheet_number": f"M-10{i}.00", "page_id": f"pg-m10{i}", "record_type": "note",
     "tier": "vision_read", "ordinal": 1,
     "quote": "2. CONTRACTOR SHALL RUN REFRIGERANT PIPES UP TO ROOF FROM EACH INDOOR "
              "UNIT. EACH AC UNIT SHALL HAVE A MINI-CONDENSATE PUMP."}
    for i in (1, 2, 3)]
#: What production returns for PTAC (2026-10-25): the M-200.00 schedule and
#: its element counts, and M-104.00's legend and OCR rows - eight records
#: that print PTAC, each read from the drawing's own text or a grid of it.
PTAC = (
    [{"sheet_number": "M-200.00", "page_id": "pg-m200", "record_type": "schedule",
      "tier": "ocr_grid_cell", "ordinal": 1,
      "quote": "ROOMS PTAC UNITS SCHEDULE UNIT NO. | QTY | MAKE | MODEL"}]
    + [{"sheet_number": "M-200.00", "page_id": "pg-m200", "record_type": "element",
        "tier": "ocr_grid_cell", "ordinal": 1 + n,
        "quote": f"PTAC-{n} — count {c} — ROOMS PTAC UNITS SCHEDULE"}
       for n, c in ((1, 21), (2, 9), (3, 11))]
    + [{"sheet_number": "M-104.00", "page_id": "pg-m104", "record_type": "legend_entry",
        "tier": "text_layer", "ordinal": n, "quote": f"PTAC-{n} — legend"}
       for n in (1, 2, 3, 4)])
#: Tables that match UNITS alone and outranked the schedule on tier.
UNITS_ONLY = [
    {"sheet_number": f"Z-00{i}.00", "page_id": f"pg-z{i}", "record_type": "schedule",
     "tier": "schedule_cell", "ordinal": 1,
     "quote": f"OCCUPANCY LOAD {i} DWELLING UNITS"} for i in range(1, 9)]


def _search(rows, subject, intent="identify", **kw):
    params = inspect.signature(server.search_plans).parameters
    assert "also" in params, "search_plans takes no other names (also=)"
    db = AsyncFakeDB()
    for r in rows:
        db[server.PLAN_RECORDS].docs.append(dict(r, project_id=PID, label="", subject_terms=[]))
    pages = sorted({r["page_id"] for r in rows})

    async def _ids(project_id, **_kw):
        return pages

    with patch.object(server, "db", db), patch.object(server, "_current_record_page_ids", _ids):
        return asyncio.run(server.search_plans(PID, subject, intent=intent, **kw))


class AnotherName(unittest.TestCase):

    def test_without_it_the_boilerplate_leads(self):
        # The measured failure, kept as the baseline the next test departs from.
        got = _search(BOILERPLATE + PTAC + UNITS_ONLY, "AC units")
        self.assertIn("MINI-CONDENSATE", got[0]["quote"])
        self.assertFalse(any("PTAC" in r["quote"] for r in got))

    def test_with_it_the_schedule_leads_and_the_boilerplate_is_gone(self):
        got = _search(BOILERPLATE + PTAC + UNITS_ONLY, "AC units", also=["PTAC"])
        self.assertIn("PTAC", got[0]["quote"])
        self.assertEqual({r["sheet_number"] for r in got[:4]}, {"M-200.00"})
        self.assertFalse(any("MINI-CONDENSATE" in r["quote"] for r in got))

    def test_a_name_counts_only_for_words_the_sheet_prints(self):
        # PTAC lends nothing to a record that does not print it: the UNITS
        # tables keep the place UNITS alone earns them, below the schedule.
        rows = BOILERPLATE + PTAC[:2] + UNITS_ONLY
        alone = [r["quote"] for r in _search(rows, "AC units", limit=20)]
        both = [r["quote"] for r in _search(rows, "AC units", also=["PTAC"], limit=20)]
        # The tables matching UNITS alone keep their order among themselves...
        self.assertEqual([q for q in both if "OCCUPANCY" in q],
                         [q for q in alone if "OCCUPANCY" in q])
        # ...and every one sits below every record that prints all of a name.
        self.assertLess(max(i for i, q in enumerate(both) if "PTAC" in q or "AC UNIT" in q),
                        min(i for i, q in enumerate(both) if "OCCUPANCY" in q))

    def test_a_name_the_drawings_never_use_finds_nothing_by_itself(self):
        # The floor holds per name: 'mini-split' is printed nowhere, so it
        # adds nothing - and alone it would return nothing.
        self.assertEqual(_search(PTAC, "mini-split heads"), [])
        got = _search(PTAC, "mini-split heads", also=["PTAC"])
        self.assertTrue(got and all("PTAC" in r["quote"] for r in got))

    def test_a_record_under_both_names_takes_its_better_place(self):
        # The schedule prints UNITS (half of 'AC units') and PTAC (all of
        # 'PTAC'): it ranks as a full match, above the boilerplate.
        got = _search(BOILERPLATE + PTAC[:1], "AC units", also=["PTAC"])
        self.assertTrue(got[0]["quote"].startswith("ROOMS PTAC UNITS SCHEDULE"), got[0]["quote"])

    def test_one_record_is_one_place(self):
        got = _search(BOILERPLATE + PTAC, "AC units", also=["PTAC", "AC unit"])
        keys = [(r["page_id"], r["quote"]) for r in got]
        self.assertEqual(len(keys), len(set(keys)))
        notes = [r for r in got if r["record_type"] == "note"]
        self.assertLessEqual(len(notes), 1)
        if notes:
            self.assertEqual(sorted((notes[0].get("also_on") or []) + [notes[0]["sheet_number"]]),
                             ["M-101.00", "M-102.00", "M-103.00"])


class TheCaseHoldsIt(unittest.TestCase):
    """The ac-type case requires PTAC and fails if ANY returned record is the
    split-system boilerplate - an answer may cite anything returned, not only
    the three lines the render prints."""

    CASE = {"id": "ac-type", "kind": "answer", "subject": "AC units", "also": ["PTAC"],
            "intent": "identify",
            "expect": {"sheets": ["M-200.00"], "text": ["PTAC"],
                       "forbid_returned": ["MINI-CONDENSATE PUMP"]},
            "truth": {"how": "text_layer", "evidence": "x"}}

    def _score(self, returned):
        from lib import plan_eval as pe
        return pe.score_case(self.CASE, [dict(r, project_id=PID, label="") for r in returned], {})

    def test_boilerplate_anywhere_in_what_came_back_fails_the_case(self):
        r = self._score(PTAC[:7] + BOILERPLATE[:1])
        self.assertEqual(r["outcome"], "fail")
        self.assertFalse(r["checks"]["forbid_returned:MINI-CONDENSATE PUMP"])

    def test_the_schedule_alone_passes_it(self):
        r = self._score(PTAC)
        self.assertEqual(r["outcome"], "pass", r["reasons"])
        self.assertEqual(r["checks"]["lead_matched_only_through_labels"], 0)

    def test_a_record_found_by_its_other_name_is_not_a_label_match(self):
        # M-104.00's legend prints PTAC and not one word of 'AC units'.
        r = self._score(PTAC[4:])
        self.assertEqual(r["checks"]["lead_matched_only_through_labels"], 0)

    def test_the_suite_refuses_an_also_that_is_not_another_name(self):
        from lib import plan_eval as pe
        suite = pe.load_suite(str(Path(__file__).resolve().parents[1] / "eval" / "boyland.json"))
        self.assertEqual(next(c for c in suite["cases"] if c["id"] == "ac-type").get("also"), ["PTAC"])
        for bad in ("PTAC", [], ["AC units"], [""]):
            broken = dict(suite, cases=[dict(c, also=bad) if c["id"] == "ac-type" else c
                                        for c in suite["cases"]])
            with self.assertRaises(pe.SuiteError, msg=repr(bad)):
                pe.validate_suite(broken)


class TheAgentCanSayIt(unittest.TestCase):

    def test_the_tool_offers_also_and_passes_it(self):
        tools = [t for t in server._AGENT_TOOLS if t["function"]["name"] == "search_plans"] \
            if hasattr(server, "AGENT_TOOLS") else []
        src = inspect.getsource(server._dispatch_agent_tool)
        block = src[src.index('if name == "search_plans"'):][:1200]
        self.assertIn('args.get("also")', block)
        self.assertIn("also=also", block)
        if tools:
            self.assertIn("also", tools[0]["function"]["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
