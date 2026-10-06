"""THE 2026-09-22 OCR-STRUCTURE MIGRATION'S ENTRY POINTS.

The engine is #649's, tested in test_plan_discipline_migration_20260921 (the
snapshot hash check, refuse-if-moved, resume, idempotence, the DB_NAME guard
and a byte-identical rollback). What is new here is that THESE TWO SCRIPTS
drive it and that their audit rows name THEM: an audit row saying
`script:migrate_plan_discipline_20260921` for a run of the OCR-structure
migration would send anyone asking what happened to this page to the wrong
plan.

The synthetic snapshot is the #649 test's fixture, reused: one discipline
page, one replace page, one page outside the plan.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bson  # noqa: E402

from scripts import migrate_plan_ocr_structure_20260922 as M2  # noqa: E402
from scripts import rollback_plan_ocr_structure_20260922 as R2  # noqa: E402
from unittest import mock  # noqa: E402

from scripts import migrate_plan_discipline_20260921 as M1  # noqa: E402
from scripts import rollback_plan_discipline_20260921 as R1  # noqa: E402
from test_plan_discipline_migration_20260921 import (  # noqa: E402
    GUARD, Base, Fixture,
)


class ItDrivesTheSameEngine(Base):

    def test_apply_then_verify(self):
        code, out = self.f.run(M2, *GUARD)
        self.assertEqual(code, 0, out)
        self.assertIn("'target': 2", out)
        self.assertEqual(self.f.run(M2, "--verify")[0], 0)

    def test_a_dry_run_writes_nothing(self):
        before = self.f.image()
        code, out = self.f.run(M2)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.f.image(), before)

    def test_a_second_run_writes_nothing(self):
        self.f.run(M2, *GUARD)
        image = self.f.image()
        code, out = self.f.run(M2, *GUARD)
        self.assertEqual(code, 0)
        self.assertIn("Nothing to do", out)
        self.assertEqual(self.f.image(), image)

    def test_rollback_restores_every_byte(self):
        original = {c: list(self.f.db[c].raw_sorted())
                    for c in ("document_page_index", "plan_records")}
        self.assertEqual(self.f.run(M2, *GUARD)[0], 0)
        self.assertEqual(self.f.run(R2, *GUARD)[0], 0)
        for c, raws in original.items():
            self.assertEqual(self.f.db[c].raw_sorted(), raws, c)

    def test_it_refuses_a_changed_page(self):
        coll = self.f.db["plan_records"]
        for i, d in enumerate(coll.docs):
            doc = bson.decode(d)
            if doc["page_id"] == str(self.f.p1):
                coll.docs[i] = bson.encode(dict(doc, quote="re-indexed"))
                break
        before = self.f.image()
        self.assertEqual(self.f.run(M2, *GUARD)[0], 2)
        self.assertEqual(self.f.image(), before)

    def test_it_never_defaults_to_a_database(self):
        for module in (M2, R2):
            before = self.f.image()
            with self.assertRaises(SystemExit) as cm:
                self.f.run(module, *GUARD, env_db=None)
            self.assertIn("DB_NAME is not set", str(cm.exception.code))
            self.assertEqual(self.f.image(), before)


class EachScriptOnlyRunsItsOwnPlan(unittest.TestCase):
    """TWO migrations, two plans, and a matched snapshot/plan pair says nothing
    about WHICH of them was asked for. Given the other migration's plan, a
    script must refuse rather than apply it under its own name."""

    def setUp(self):
        self.a = Fixture()          # stands in for the OCR plan
        self.b = Fixture()          # stands in for the discipline plan
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.assertNotEqual(self.a.identity, self.b.identity)

    def test_the_ocr_script_refuses_the_other_plan(self):
        before = self.b.image()
        with mock.patch.object(M2, "EXPECT_PLAN", self.a.identity):
            code, out = self.b.run(M2, *GUARD, bind=False)
        self.assertEqual(code, 2)
        self.assertIn("this is not the plan this script runs", out)
        self.assertEqual(self.b.image(), before)

    def test_the_discipline_script_refuses_the_other_plan(self):
        before = self.a.image()
        with mock.patch.object(M1, "EXPECT_PLAN", self.b.identity):
            code, out = self.a.run(M1, *GUARD, bind=False)
        self.assertEqual(code, 2)
        self.assertIn("this is not the plan this script runs", out)
        self.assertEqual(self.a.image(), before)

    def test_the_rollbacks_refuse_it_too(self):
        for module, other, fixture in ((R2, self.a.identity, self.b),
                                       (R1, self.b.identity, self.a)):
            before = fixture.image()
            with mock.patch.object(module, "EXPECT_PLAN", other):
                code, out = fixture.run(module, *GUARD, bind=False)
            self.assertEqual(code, 2, module.NAME)
            self.assertEqual(fixture.image(), before, module.NAME)

    def test_the_right_pairing_still_applies(self):
        for module, fixture in ((M2, self.a), (M1, self.b)):
            code, out = fixture.run(module, *GUARD)
            self.assertEqual(code, 0, out)
            self.assertIn("'target': 2", out)

    def test_the_shipped_scripts_are_bound_to_different_plans(self):
        self.assertNotEqual(M2.EXPECT_PLAN, M1.EXPECT_PLAN)
        self.assertEqual(M2.EXPECT_PLAN, R2.EXPECT_PLAN)   # one migration, one plan
        self.assertEqual(M1.EXPECT_PLAN, R1.EXPECT_PLAN)
        for h in (M1.EXPECT_PLAN, M2.EXPECT_PLAN):
            self.assertRegex(h, r"^[0-9a-f]{64}$")


class TheAuditRowsNameTheseScripts(Base):

    def _actors(self):
        return {bson.decode(d)["user_id"] for d in self.f.db["audit_logs"].docs}

    def test_migrate(self):
        self.f.run(M2, *GUARD)
        self.assertEqual(self._actors(),
                         {"script:migrate_plan_ocr_structure_20260922"})

    def test_rollback(self):
        self.f.run(M2, *GUARD)
        self.f.db["audit_logs"].docs.clear()
        self.f.run(R2, *GUARD)
        self.assertEqual(self._actors(),
                         {"script:rollback_plan_ocr_structure_20260922"})

    def test_the_engine_still_names_itself(self):
        from scripts import migrate_plan_discipline_20260921 as M1
        self.f.run(M1, *GUARD)
        self.assertEqual(self._actors(),
                         {"script:migrate_plan_discipline_20260921"})


class WhatThisMigrationSays(unittest.TestCase):
    """The two grids it moves and the one it leaves, in the file an operator
    reads before running it."""

    SRC = (_BACKEND / "scripts" / "migrate_plan_ocr_structure_20260922.py").read_text(
        encoding="utf-8")

    def test_it_names_both_grids_and_their_sheets(self):
        for bit in ("SP-002.00", "(grid 3x14", "RFC49 16/7", "F1RES44 9/16",
                    "P-400.00", "(grid 13x6", "FIXTURES | ABBR"):
            self.assertIn(bit, self.SRC)

    def test_it_says_what_it_excludes_and_why(self):
        self.assertIn("EXCLUDED, DELIBERATELY: P-400.00's storage tank", self.SRC)
        self.assertIn("the stored version is better", self.SRC)

    def test_it_says_m200_is_untouched(self):
        self.assertIn("M-200.00 IS NOT IN THIS MIGRATION", self.SRC)


if __name__ == "__main__":
    unittest.main()
