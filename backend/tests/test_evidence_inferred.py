"""lib/evidence.py: the INFERRED kind.

An inference is a plausible conclusion that MULTIPLE INDEPENDENT signals support
("plumbing rough-in on floor 3 is probably installed: the plumber logged rough-in
there, an insulation crew's photo shows pipe there, and insulation started").
It is not a fact, so, like an estimate:

  * it never decides status() (never done_<rung>, never a passed inspection);
  * strongest() never returns it as a fact;
  * it never carries a percent;
  * it needs a basis, a disproof (what would show it wrong), a confidence word
    from a fixed list WITH the rule that produced it, and >= 2 signals from
    independent sources, each signal itself a fact with its own category.

Every fixture below is SYNTHETIC (made-up refs and dates).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import evidence as E  # noqa: E402

PID = "proj_synthetic"


def sig(source, ref, kind="reported", on=date(2026, 10, 1), sub=None, by=None, note="synthetic"):
    return {"source": source, "ref": ref, "kind": kind, "on": on, "sub": sub, "by": by, "note": note}


TWO = [sig("logbooks", "L1", sub="Plumber Co"), sig("photo_index", "P1", kind="observed", sub="Insulation Co")]


def inferred(claim="done", signals=TWO, **kw):
    args = dict(source="lib/construction_inference", ref="inf:1", project_id=PID, node="rough_plumbing",
                levels=["FLOOR_3"], on=date(2026, 10, 2), basis="synthetic rule", disproof="a failed rough inspection",
                confidence="medium", confidence_rule="two independent sources, one observed")
    args.update(kw)
    return E.item("inferred", claim, signals=signals, **args)


class TheInferredKind(unittest.TestCase):

    def test_it_is_a_kind_and_not_a_fact(self):
        self.assertIn("inferred", E.KINDS)
        self.assertIn("inferred", E.NON_FACTS)
        self.assertIn("estimate", E.NON_FACTS)
        self.assertFalse(E.is_fact(inferred()))
        self.assertTrue(E.is_fact(E.item("reported", "in_progress", source="logbooks", ref="L1", project_id=PID)))

    def test_it_carries_signals_disproof_and_a_named_confidence_rule(self):
        i = inferred()
        self.assertEqual(i["kind"], "inferred")
        self.assertEqual(len(i["signals"]), 2)
        self.assertEqual(i["disproof"], "a failed rough inspection")
        self.assertEqual(i["confidence"], "medium")
        self.assertEqual(i["confidence_rule"], "two independent sources, one observed")
        self.assertEqual(i["contradictions"], [])
        self.assertIsNone(i["stated_percent"])

    def test_a_fact_item_keeps_exactly_its_old_keys(self):
        keys = set(E.item("reported", "present", source="x", ref="r", project_id=PID))
        self.assertEqual(keys & {"signals", "disproof", "confidence", "confidence_rule"}, set())

    def test_one_source_is_not_an_inference(self):
        same = [sig("logbooks", "L1", sub="Plumber Co"), sig("logbooks", "L2", sub="Plumber Co")]
        with self.assertRaises(ValueError):
            inferred(signals=same)
        with self.assertRaises(ValueError):
            inferred(signals=TWO[:1])

    def test_it_needs_basis_disproof_and_a_confidence_from_the_list(self):
        with self.assertRaises(ValueError):
            inferred(basis=None)
        with self.assertRaises(ValueError):
            inferred(disproof=None)
        with self.assertRaises(ValueError):
            inferred(confidence="0.83")
        with self.assertRaises(ValueError):
            inferred(confidence_rule=None)

    def test_it_never_carries_a_percent_or_a_failure(self):
        with self.assertRaises(ValueError):
            inferred(stated_percent=80.0)
        with self.assertRaises(ValueError):
            inferred(claim="failed")

    def test_a_signal_must_itself_be_a_fact(self):
        bad = [sig("logbooks", "L1", sub="A"), sig("lib/forecast", "E1", kind="estimate", sub="B")]
        with self.assertRaises(ValueError):
            inferred(signals=bad)
        chained = [sig("logbooks", "L1", sub="A"), sig("lib/construction_inference", "I1", kind="inferred", sub="B")]
        with self.assertRaises(ValueError):
            inferred(signals=chained)

    def test_independence_is_source_and_actor(self):
        self.assertEqual(E.independent_sources(TWO), 2)
        self.assertEqual(E.independent_sources([sig("logbooks", "L1", sub="A"), sig("logbooks", "L9", sub="B")]), 2)
        self.assertEqual(E.independent_sources([sig("logbooks", "L1", sub="A"), sig("logbooks", "L9", sub="a")]), 1)
        explicit = [dict(sig("logbooks", "L1", sub="A"), independence="cp-typed"),
                    dict(sig("logbooks", "L2", sub="B"), independence="cp-typed")]
        self.assertEqual(E.independent_sources(explicit), 1)


class StatusIgnoresIt(unittest.TestCase):

    def test_an_inferred_done_never_says_done(self):
        self.assertEqual(E.status([inferred()]), "unknown")
        rep = E.item("reported", "in_progress", source="logbooks", ref="L1", project_id=PID, node="rough_plumbing",
                     levels=["FLOOR_3"], on=date(2026, 10, 1))
        self.assertEqual(E.status([rep, inferred()]), "reported")

    def test_strongest_never_returns_it_as_a_fact(self):
        rep = E.item("reported", "in_progress", source="logbooks", ref="L1", project_id=PID)
        self.assertIs(E.strongest([inferred(), rep]), rep)
        self.assertIsNone(E.strongest([inferred()]))
        self.assertEqual(E.strongest([inferred()], facts_only=False)["kind"], "inferred")


class TheProgressEngineIgnoresIt(unittest.TestCase):

    def test_a_cell_never_counts_an_inference(self):
        from lib import project_progress as PP
        model = PP.build([inferred(node="framing", levels=["FLOOR_1"])], today=date(2026, 10, 5),
                         project={"building_stories": 2})
        self.assertEqual(model["cells"][("FLOOR_1", "framing")]["status"], "unknown")
        self.assertEqual(model["cells"][("FLOOR_1", "framing")]["item_count"], 0)
        self.assertEqual(model["inferences_set_apart"], 1)


if __name__ == "__main__":
    unittest.main()
