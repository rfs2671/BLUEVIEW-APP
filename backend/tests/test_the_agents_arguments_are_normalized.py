"""The agent's search arguments are normalized in code, not only asked for in
the prompt (ruling 2026-10-26).

Measured on Qwen/Qwen3.8-Flash with the 32 eval questions (agent-filled
arguments 23/32 against 29/32 case-filled): a property word left in the
subject, a floor filter that emptied a count, and a definition answered from
general knowledge without searching. The fixes are deterministic argument
normalization and the tool's own words - no ranking or gate change.

Each test asks first whether plan_search normalizes, so the control run on
the base branch fails by assertion.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402


def _ps():
    from lib import plan_search as ps
    assert hasattr(ps, "normalize_arguments"), "the arguments are not normalized (base)"
    return ps


class ThePropertyLeavesTheSubject(unittest.TestCase):

    def test_the_attributes_own_word_stays_in_either_number(self):
        # Ruling 2026-10-28 (option B): the value is often printed WITH the
        # attribute's word - A-500.00's '3 1/2" METAL STUD 16" O.C. 20 GAUGE
        # MIN.' - so moving the word itself out of the subject dropped it.
        ps = _ps()
        self.assertEqual(ps.normalize_arguments("metal stud gauge", "gauge")[:2], ("metal stud gauge", "gauge"))
        self.assertEqual(ps.normalize_arguments("sidewalk shed height", "height")[0], "sidewalk shed height")
        self.assertEqual(ps.normalize_arguments("ceiling heights", "height")[0], "ceiling heights")
        # 'gauges' is one edit from 'gauge', but it is the word, not a misspelling.
        self.assertEqual(ps.normalize_arguments("metal stud gauges", "gauge")[0], "metal stud gauges")
        self.assertEqual(ps.normalize_arguments("pipe inches", "inch")[0], "pipe inches")

    def test_the_typo_the_agent_corrected_moves(self):
        ps = _ps()
        # The GC typed 'hight'; the agent spelled the attribute right and left
        # the typo in the subject - where the floor reads it as a word the
        # drawings never print, and the search returns nothing.
        self.assertEqual(ps.normalize_arguments("sidewalk shed hight", "height")[:2], ("sidewalk shed", "height"))
        self.assertEqual(ps.normalize_arguments("door hight", "height")[:2], ("door", "height"))

    def test_only_the_attributes_own_word_moves(self):
        ps = _ps()
        # 'area' is a property word, but not this attribute's: nothing is
        # inferred from a list.
        self.assertEqual(ps.normalize_arguments("passive recreation area", "size")[0], "passive recreation area")
        # HIGH is printed on the shed drawing and is not one edit from height.
        self.assertEqual(ps.normalize_arguments("high shed", "height")[0], "high shed")
        self.assertEqual(ps.normalize_arguments("metal studs", "")[0], "metal studs")

    def test_a_subject_that_is_only_the_attribute_is_left_alone(self):
        ps = _ps()
        self.assertEqual(ps.normalize_arguments("height", "height")[0], "height")


class ACountIsNotNarrowedByFloor(unittest.TestCase):

    def test_a_count_drops_the_floor_and_nothing_else_does(self):
        ps = _ps()
        self.assertEqual(ps.normalize_arguments("exhaust fan", "", "count", "4")[2], "")
        self.assertEqual(ps.normalize_arguments("exhaust fan", "", "attribute", "4")[2], "4")
        self.assertEqual(ps.normalize_arguments("exhaust fan", "", "", "4")[2], "4")


def _search(rows, subject, **kw):
    _ps()
    db = AsyncFakeDB()
    for i, r in enumerate(rows):
        db[server.PLAN_RECORDS].docs.append(dict(r, project_id="p", page_id=f"pg{i}", ordinal=i,
                                                 label="", subject_terms=[], tier="text_layer"))
    seen_floors = []

    async def _ids(project_id, floor="", **_kw):
        seen_floors.append(floor)
        return [] if floor else [f"pg{i}" for i in range(len(rows))]

    with patch.object(server, "db", db), patch.object(server, "_current_record_page_ids", _ids):
        return asyncio.run(server.search_plans("p", subject, **kw)), seen_floors


SHED = [{"sheet_number": "SSP-009.00", "record_type": "text", "quote": "SIDEWALK SHED"},
        {"sheet_number": "SSP-003.00", "record_type": "legend_entry", "quote": "8' HIGH SHED"}]


# Ten plain METAL STUD dimensions and the one line that prints the gauge,
# as A-500.00 prints them.
STUDS = ([{"sheet_number": "A-500.00", "record_type": "dimension", "quote": f'{w} METAL STUD'}
          for w in ('1 5/8"', '2 1/2"', '3 1/2"', '3 5/8"', '4"', '6"', '2 1/2" 16"', '3 1/2" 16"', '3 5/8" 16"', '6" 16"')]
         + [{"sheet_number": "A-500.00", "record_type": "text", "quote": '3 1/2" METAL STUD 16" O.C. 20 GAUGE MIN.'}])


class TheSearchUsesThem(unittest.TestCase):

    def test_the_line_that_prints_the_gauge_comes_back(self):
        # Production 2026-10-26: 'metal stud gauge' searched as 'metal stud'
        # returned 8 plain METAL STUD records and not the 20 GAUGE line.
        got, _ = _search(STUDS, "metal stud gauge", intent="attribute", attribute="gauge")
        self.assertIn('3 1/2" METAL STUD 16" O.C. 20 GAUGE MIN.', [r["quote"] for r in got],
                      "the attribute's own word left the subject, and the line printing the value with it was outranked")

    def test_a_misspelled_property_no_longer_empties_the_search(self):
        got, _ = _search(SHED, "sidewalk shed hight", intent="attribute", attribute="height")
        self.assertTrue(got, "the floor read 'hight' as a word the drawings never use")
        self.assertIn("8' HIGH SHED", [r["quote"] for r in got])

    def test_a_count_reads_the_whole_set_whatever_floor_it_names(self):
        got, floors = _search(SHED, "sidewalk shed", intent="count", floor="4")
        self.assertTrue(floors)
        self.assertEqual(set(floors), {""}, "a page lookup was narrowed by floor")
        self.assertTrue(got)


class TheAgentIsToldSo(unittest.TestCase):

    def test_a_definition_is_searched_first(self):
        _ps()
        p = server._AGENT_SYSTEM_PROMPT_BASE
        self.assertIn("NEVER answer a definition from general knowledge before", p)

    def test_the_tool_says_where_floor_and_attribute_belong(self):
        _ps()
        (tool,) = [t for t in server._AGENT_TOOLS if t["function"]["name"] == "search_plans"]
        props = tool["function"]["parameters"]["properties"]
        self.assertIn("Not for a count", props["floor"].get("description", ""))
        self.assertIn("never a place", props["attribute"]["description"])


if __name__ == "__main__":
    unittest.main()
