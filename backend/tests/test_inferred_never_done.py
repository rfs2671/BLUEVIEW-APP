"""An INFERENCE never reaches done, a passed inspection or a percent, in any
consumer (adversarial review 2, finding A4 / M4).

One test per consumer of evidence or of the reconstruction's states:
  lib/evidence.status / strongest      (the ladder)
  lib/project_progress.build           (cells, counts)
  lib/confirmation_queue.facts         (what a question may cite)
  lib/forecast._strong                 (start / done markers)
  lib/schedule_generator               (remaining work in every scenario, both rules)
  lib/site_questions                   (an inferred predecessor is ASKED, never suppressed)
  lib/dm_* answers                     read no evidence items: asserted by import scan below.
Synthetic fixtures only.
"""

from __future__ import annotations

import ast
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from lib import confirmation_queue as CQ  # noqa: E402
from lib import evidence as E  # noqa: E402
from lib import forecast as F  # noqa: E402
from lib import project_progress as PP  # noqa: E402
from lib import schedule_generator as G  # noqa: E402
from lib import site_questions as Q  # noqa: E402

D = date(2026, 3, 2)
SIGNALS = [{"source": "logbooks", "ref": "L1", "kind": "reported", "by": "CP"},
           {"source": "photo_index", "ref": "P1", "kind": "observed", "by": "camera"}]


def inferred(node="framing", levels=("FLOOR_1",)):
    return E.item("inferred", "done", source="lib/construction_inference", ref="inf", project_id="p", node=node,
                  levels=list(levels), on=D, basis="synthetic", disproof="synthetic", confidence="high",
                  confidence_rule="synthetic", signals=SIGNALS)


class TheLadder(unittest.TestCase):
    def test_status_and_strongest(self):
        self.assertEqual(E.status([inferred()]), "unknown")
        self.assertIsNone(E.strongest([inferred()]))


class ProjectProgress(unittest.TestCase):
    def test_no_cell_is_done_and_nothing_is_counted(self):
        m = PP.build([inferred()], today=D, project={"building_stories": 1})
        self.assertEqual(m["cells"][("FLOOR_1", "framing")]["bucket"], "unknown")
        self.assertNotIn("done", m["counts"])


class ConfirmationQueue(unittest.TestCase):
    def test_an_inference_is_not_a_fact_a_question_may_cite(self):
        self.assertEqual(CQ.facts([inferred()], today=D), [])


class Forecast(unittest.TestCase):
    def test_an_inference_never_marks_a_start_or_a_done(self):
        self.assertFalse(F._strong(inferred()))


class ScheduleGenerator(unittest.TestCase):
    def resolver(self):
        assumptions = G.coherent_conservative(G.default_assumptions())
        A, _t = G._resolver(assumptions)
        return A

    def test_an_inferred_done_leaves_scope_open_in_every_scenario(self):
        A = self.resolver()
        st = G.state_entry("done", "inferred", "synthetic: later work closes over it")
        for scn in G.SCENARIOS + (G.STRESS,):
            rem, how = G.remaining_fraction(st, scn, A)
            with self.subTest(scenario=scn):
                self.assertGreater(rem, 0.0, how)
        self.assertLessEqual(G.remaining_fraction(st, "fast", A)[0], G.remaining_fraction(st, "conservative", A)[0])

    def test_a_model_state_of_inferred_done_is_tagged_inferred_never_verified(self):
        self.assertEqual(G.MODEL_STATUS["inferred_done_high"][1], "inferred")
        self.assertEqual(G.MODEL_STATUS["inferred_done_medium"][1], "inferred")

    def test_an_inferred_gate_is_pending(self):
        A = self.resolver()
        rem, _how = G.remaining_fraction(G.state_entry("done", "inferred", "x"), "fast", A, gate=True)
        self.assertEqual(rem, 1.0)


class SiteQuestions(unittest.TestCase):
    def ctx(self, evidence):
        sched = SimpleNamespace(
            window=lambda: ["board_L1"],
            net={"links": [{"from": "frame_L1", "to": "board_L1", "kind": "prerequisite", "type": "FS"}]},
            by_id={"frame_L1": {"id": "frame_L1", "name": "frame L1", "zone": "L1"}},
            state={"frame_L1": G.state_entry("done", evidence, "synthetic")})
        return {"sched": sched, "today": D}

    def test_an_inferred_predecessor_is_not_answered_by_records(self):
        self.assertEqual(Q.answered_predecessors(self.ctx("inferred")), [])
        self.assertEqual([x["id"] for x in Q.answered_predecessors(self.ctx("verified_public_record"))],
                         ["work:frame_L1"])


class DmAnswers(unittest.TestCase):
    def test_no_dm_module_reads_evidence_kinds(self):
        # The DM answer modules never import the evidence ladder or the
        # reconstruction, so an inference cannot reach a DM answer as done.
        banned = {"lib.evidence", "lib.construction_inference", "lib.project_timeline"}
        for path in sorted((BACKEND / "lib").glob("dm_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            names = {f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
                     for a in n.names}
            with self.subTest(module=path.name):
                self.assertEqual((mods | names) & banned, set())


if __name__ == "__main__":
    unittest.main()
