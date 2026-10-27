"""The DM brain's plan answer reads a level as the SET names it.

"spray foam 5th floor ceiling" on a set of four floors, a mezzanine and a
roof (2026-10-27): the search_plans tool result carries
`level_mapping: 5th floor = Mezzanine (A-104.00) on this set` for the answer
to state, the mezzanine's sheets and the roof assembly's sections/details
are searched (that ceiling is the underside of the roof), and no search asks
the drawings for the word 5TH. A two-meaning word comes back with its
`term_senses`. Invented sheet titles; no customer drawings.
"""

from __future__ import annotations

from unittest.mock import patch

import server  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_dm_plan_answer_crop import _page_jpeg  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402
from lib import plan_search  # noqa: E402

TITLES = {"pg1": ("A-100.00", "FIRST FLOOR PLAN"), "pg2": ("A-101.00", "SECOND FLOOR PLAN"),
          "pg3": ("A-102.00", "THIRD FLOOR PLAN"), "pg4": ("A-103.00", "FOURTH FLOOR PLAN"),
          "pgM": ("A-104.00", "MEZZANINE PLAN"), "pgT": ("A-105.00", "ROOF PLAN"),
          "pgR": ("A-301.00", "ROOF SECTIONS AND DETAILS"),
          "pgK": ("A-501.00", "INTERIOR DETAILS")}
PAGES = [{"_id": pid, "project_id": THOMAS, "file_id": "f1", "file_name": "A-set.pdf",
          "page_number": i + 1, "sheet_number": sn, "sheet_title": t,
          "page_jpeg_r2_key": f"plans/k/page_{i + 1}.jpg"}
         for i, (pid, (sn, t)) in enumerate(TITLES.items())]


def _rec(page_id, quote, ordinal=0):
    return {"page_id": page_id, "project_id": THOMAS, "sheet_number": TITLES[page_id][0],
            "file_name": "A-set.pdf", "page_number": 1, "record_type": "note",
            "ordinal": ordinal, "quote": quote, "bbox": None, "tier": "text_layer",
            "source": "text_layer", "verified": True}


RECORDS = [
    _rec("pgR", "ROOF ASSEMBLY: CLOSED CELL SPRAY FOAM INSULATION AT UNDERSIDE OF DECK"),
    _rec("pgM", "MEZZANINE CEILING: GYP. BD. ON FURRING"),
    _rec("pgK", "KITCHEN SOFFIT: GYP. BD. BOX OVER UPPER CABINETS"),
]


class _Levels(_Brain):
    def setUp(self):
        super().setUp()
        self.db.document_page_index.rows.extend(dict(p) for p in PAGES)
        self.db.project_files.rows.append({"_id": "f1", "project_id": THOMAS,
                                           "name": "A-set.pdf"})
        self.searches = []

    def run_brain(self, body, llm):
        async def ranked(project_id, page_ids, subject, intent):
            self.searches.append((sorted(page_ids), subject))
            terms = plan_search.search_terms(subject)
            hits = [dict(r) for r in RECORDS if r["page_id"] in page_ids
                    and all(any(f in r["quote"].lower() for f in plan_search.term_forms(t))
                            for t in terms)]
            return (hits, terms) if hits else None

        async def fetch(page):
            return _page_jpeg()

        def upload(data, key, content_type="application/octet-stream"):
            return f"https://r2.test/{key}"
        ps = [patch.object(server, "_ranked_for_subject", ranked),
              patch.object(server, "_fetch_page_jpeg", fetch),
              patch.object(server, "_upload_to_r2", upload)]
        for p in ps:
            p.start()
        try:
            with _Ctx(db=self.db) as c:
                return self.say(c, body, llm)
        finally:
            for p in reversed(ps):
                p.stop()


class FifthFloorCeilingIsTheMezzanineAndTheRoofAssembly(_Levels):
    def test_the_tool_result_carries_the_mapping_and_the_roof_sheets_are_searched(self):
        seen = {}
        answer = ("5th floor = Mezzanine (A-104.00) on this set.\n"
                  "Closed cell spray foam at the underside of the roof deck [A-301.00].")

        def check(kw):
            seen["result"] = last_tool_results(kw)[0]
            return resp(text(answer))
        llm = FakeLLM(resp(use("search_plans", {"job": "588",
                                                "subject": "spray foam 5th floor ceiling"})),
                      check)
        out = self.run_brain("spray foam on the 5th floor ceiling at 588?", llm)
        res = seen["result"]
        self.assertIn("level_mapping: 5th floor = Mezzanine (A-104.00) on this set", res)
        self.assertIn("searched_sheets:", res)
        self.assertIn("(A-301.00)", res)
        self.assertIn("SPRAY FOAM INSULATION AT UNDERSIDE OF DECK [A-301.00", res)
        # The roof assembly was searched on its own, for the material.
        self.assertIn((["pgR"], "spray foam"), self.searches)
        # The mezzanine's own sheet was searched too.
        self.assertTrue(any(ids == ["pgM"] for ids, _s in self.searches), self.searches)
        # Nothing asked the drawings for the word 5TH.
        self.assertEqual([s for _ids, s in self.searches if "5th" in s.lower()], [])
        self.assertEqual(out[0], answer)

    def test_a_floor_argument_is_mapped_the_same_way(self):
        seen = {}

        def check(kw):
            seen["result"] = last_tool_results(kw)[0]
            return resp(text("ok"))
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "ceiling",
                                                "floor": "5th"})), check)
        self.run_brain("5th floor ceiling at 588?", llm)
        self.assertIn("level_mapping: 5th floor = Mezzanine (A-104.00) on this set",
                      seen["result"])
        self.assertIn((["pgR"], "ceiling"), self.searches)


class AWordWithTwoMeaningsSaysWhichItIs(_Levels):
    def test_kitchen_soffits_come_back_as_the_interior_meaning(self):
        seen = {}

        def check(kw):
            seen["result"] = last_tool_results(kw)[0]
            return resp(text("Gyp. bd. box over the upper cabinets [A-501.00]."))
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "kitchen soffit"})),
                      check)
        self.run_brain("kitchen soffits on 588?", llm)
        self.assertIn("term_senses: 'soffit' means two different things on drawings", seen["result"])
        self.assertIn("Here it means the interior soffit", seen["result"])
        # No level was named, so no mapping is there to state.
        self.assertEqual([ln for ln in seen["result"].splitlines()
                          if ln.startswith("level_mapping:")], [])
