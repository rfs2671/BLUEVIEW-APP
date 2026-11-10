"""THE LANES TOGETHER: DOB SIGN-OFFS REACH THE WHOLE-BUILDING STATUS.

Nov 9, 11:37 PM, the owner: "What inspections happened in 588 ... since
beginning of the project". The assistant said no sign-offs were in anything it
could read. NYC Open Data has four for 588 (demolition, foundation + earthwork,
support of excavation, construction fence). The evidence-sources lane turns
them into `verified` items; the progress model dropped every item that named no
level, so the strongest evidence 588 has never reached its status. Asserted:

  * a whole-filing sign-off lands in the WHOLE BUILDING section, verified;
  * it is never spread onto the floors (no floor's cell becomes done);
  * site protection (a fence) is not construction progress and stays out;
  * work_nodes' dict + SEQUENCE shape is read (the model expected a list).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import evidence_sources as ES  # noqa: E402
from lib import project_progress as PG  # noqa: E402
from tests import test_evidence_sources as T  # noqa: E402

PROJECT = {"_id": T.PID, "name": "588", "building_stories": 4, "has_cellar": True}


def _model(rows=None):
    items, _cov = ES.from_dob(rows if rows is not None else T.WITH_1008, T.PID, bins=(T.BIN_588,))
    return PG.build(items, today=T.TODAY, project=PROJECT, job="588")


class TheWholeBuilding(unittest.TestCase):

    def test_work_nodes_shape_is_read(self):
        steps, said = PG._extra_steps()
        self.assertEqual(said, "read")
        ids = {s["id"] for s in steps}
        self.assertTrue({"demolition", "foundation", "excavation_soe"} <= ids)
        self.assertNotIn("site_protection", ids, "a fence is not progress")
        self.assertFalse(next(s for s in steps if s["id"] == "demolition")["per_level"])

    def test_the_sign_offs_are_verified_done_for_the_building(self):
        building = {c["node"]: c for c in _model()["building"]}
        for node in ("demolition", "foundation", "excavation_soe"):
            with self.subTest(node=node):
                self.assertEqual(building[node]["status"], "done_verified")

    def test_a_building_record_is_never_spread_onto_a_floor(self):
        model = _model()
        floor_done = [k for k, c in model["cells"].items() if c["status"] == "done_verified"]
        self.assertEqual(floor_done, [], "no floor's cell is done from a whole-filing sign-off")

    def test_the_text_names_them(self):
        out = PG.as_text(_model())
        self.assertIn("Whole building", out)
        self.assertIn("demolition: done, verified", out)
        self.assertNotIn("site protection", out.split("Whole building, no record:")[0])

    def test_with_no_dob_records_the_building_is_unknown_not_not_done(self):
        out = PG.as_text(_model([]))
        self.assertIn("Whole building, no record", out)
        self.assertNotIn("not done", out.lower())


if __name__ == "__main__":
    unittest.main()
