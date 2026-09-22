"""THE 2026-09-21 DISCIPLINE MIGRATION AND ITS ROLLBACK, OFFLINE.

Against a small synthetic snapshot in `fake_raw_mongo`, which keeps every
document as BSON bytes. Three pages:

    P1  a discipline page       ST -> AR, two records updated in place
    P2  a replace page          two records replaced by three, page extraction set
    P3  NOT in the plan         must come through every run byte-identical

The full-scale version of the same checks — the real 20,408-record snapshot,
apply compared with the dry run and rollback compared byte for byte — runs
from the snapshot folder, which is not in the repository; its result is in the
PR that added these scripts.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bson  # noqa: E402
from bson import ObjectId, json_util  # noqa: E402

from fake_raw_mongo import FakeClient  # noqa: E402
from scripts import migrate_plan_discipline_20260921 as M  # noqa: E402
from scripts import plan_discipline_20260921 as P  # noqa: E402
from scripts import rollback_plan_discipline_20260921 as R  # noqa: E402

DB = P.EXPECTED_DB
PID = "proj-1"
T0 = datetime(2026, 9, 20, 22, 22, 34, 585000, tzinfo=timezone.utc)
GUARD = ["--i-know", "--reason", "test", "--session", "s-test"]


def _page(pid, file_id, n, disc, sheet):
    return {"_id": pid, "project_id": PID, "file_id": file_id, "page_number": n,
            "file_name": "f.pdf", "sheet_number": sheet, "discipline": disc,
            "extraction": {"schedules": [{"name": "old"}], "elements": [],
                           "sheet_number": sheet},
            "embedding": [0.25, 0.5], "indexed_at": T0}


def _rec(page_id, file_id, n, disc, ordinal):
    return {"_id": ObjectId(), "project_id": PID, "file_id": file_id,
            "page_id": str(page_id), "page_number": n, "discipline": disc,
            "record_type": "text", "ordinal": ordinal, "quote": f"q{ordinal}",
            "payload": {"a": 1, "b": 2.5}, "created_at": T0}


class Fixture:
    """A snapshot folder, its plan, and a fake database loaded from it."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        os.makedirs(os.path.join(self.dir, "snapshot"))
        self.p1, self.p2, self.p3 = ObjectId(), ObjectId(), ObjectId()
        pages = [_page(self.p1, "F1", 1, "ST", "A.4.1"),
                 _page(self.p2, "F2", 3, "SP", "SP-003.00"),
                 _page(self.p3, "F1", 2, "ST", "A.5.1")]
        recs = ([_rec(self.p1, "F1", 1, "ST", i) for i in range(2)]
                + [_rec(self.p2, "F2", 3, "SP", i) for i in range(2)]
                + [_rec(self.p3, "F1", 2, "ST", i) for i in range(2)])
        self.page_raw = [bson.encode(d) for d in pages]
        self.rec_raw = [bson.encode(d) for d in recs]
        for name, raws in (("pages.bson", self.page_raw),
                           ("records.bson", self.rec_raw)):
            with open(os.path.join(self.dir, "snapshot", name), "wb") as f:
                f.write(b"".join(raws))
        new_recs = [dict(_rec(self.p2, "F2", 3, "SP", i), record_type="schedule")
                    for i in range(3)]
        plan = {
            "project_id": PID, "code": "test", "built_at": T0,
            "inputs": {f"snapshot/{n}": P.sha256(os.path.join(self.dir, "snapshot", n))
                       for n in ("records.bson", "pages.bson")},
            "pages": [
                {"page_id": self.p1, "file_id": "F1", "page_number": 1,
                 "file_name": "f.pdf", "sheet_number": "A.4.1",
                 "discipline_from": "ST", "discipline_to": "AR",
                 "records_before": 2, "records_after": 2, "kind": "discipline"},
                {"page_id": self.p2, "file_id": "F2", "page_number": 3,
                 "file_name": "f.pdf", "sheet_number": "SP-003.00",
                 "discipline_from": "SP", "discipline_to": "SP",
                 "records_before": 2, "records_after": 3, "kind": "replace",
                 "records": new_recs,
                 "page_set": {"discipline": "SP",
                              "extraction.schedules": [{"name": "new"}],
                              "extraction.elements": [{"tag": "RFC49"}]}},
            ],
        }
        with open(os.path.join(self.dir, "plan.json"), "w", encoding="utf-8") as f:
            f.write(json_util.dumps(plan, json_options=json_util.CANONICAL_JSON_OPTIONS))
        self.new_recs = new_recs
        self.client = FakeClient()
        db = self.client[DB]
        db["document_page_index"].docs = list(self.page_raw)
        db["plan_records"].docs = list(self.rec_raw)

    @property
    def db(self):
        return self.client[DB]

    def image(self):
        """Every stored byte, for 'nothing was written' assertions."""
        return {c: list(self.db[c].raw_sorted())
                for c in ("document_page_index", "plan_records", "audit_logs")}

    def run(self, module, *extra, env_db=DB):
        out = io.StringIO()
        env = {"DB_NAME": env_db} if env_db is not None else {}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            if env_db is None:
                os.environ.pop("DB_NAME", None)
            code = module.main(["--snapshot-dir", self.dir, *extra],
                               client=self.client)
        return code, out.getvalue()

    def close(self):
        self.tmp.cleanup()


class Base(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.close()

    def recs_of(self, page_id):
        return [bson.decode(d) for d in self.f.db["plan_records"].docs
                if bson.decode(d)["page_id"] == str(page_id)]


class ADryRunWritesNothing(Base):

    def test_default_is_a_dry_run(self):
        before = self.f.image()
        code, out = self.f.run(M)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.f.image(), before)

    def test_it_prints_counts_per_collection_and_per_page(self):
        _, out = self.f.run(M)
        self.assertIn("plan_records (project)=6", out)
        self.assertIn("document_page_index (project)=3", out)
        self.assertIn("A.4.1", out)
        self.assertIn("SP-003.00", out)
        self.assertIn("'snapshot': 2", out)


class ApplyReachesTheTarget(Base):

    def test_apply(self):
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 0, out)
        self.assertIn("'target': 2", out)
        self.assertIn("AFTER", out)

    def test_discipline_is_updated_in_place(self):
        before = {r["_id"]: r for r in self.recs_of(self.f.p1)}
        self.f.run(M, *GUARD)
        after = {r["_id"]: r for r in self.recs_of(self.f.p1)}
        self.assertEqual(set(after), set(before), "record _ids must be kept")
        for _id, r in after.items():
            self.assertEqual(r["discipline"], "AR")
            self.assertEqual({**r, "discipline": "ST"}, before[_id])
        page = bson.decode(self.f.db["document_page_index"].find_one(
            {"_id": self.f.p1}).raw)
        self.assertEqual(page["discipline"], "AR")

    def test_a_replace_page_holds_exactly_the_planned_records(self):
        self.f.run(M, *GUARD)
        got = sorted(P.key(r) for r in self.recs_of(self.f.p2))
        want = sorted(P.key(r) for r in json_util.loads(json_util.dumps(
            self.f.new_recs)))
        self.assertEqual(got, want)
        page = bson.decode(self.f.db["document_page_index"].find_one(
            {"_id": self.f.p2}).raw)
        self.assertEqual(page["extraction"]["schedules"], [{"name": "new"}])
        self.assertEqual(page["extraction"]["sheet_number"], "SP-003.00")
        self.assertEqual(page["embedding"], [0.25, 0.5])

    def test_a_page_outside_the_plan_is_byte_identical(self):
        p3_before = [d for d in self.f.db["plan_records"].docs
                     if bson.decode(d)["page_id"] == str(self.f.p3)]
        row_before = self.f.db["document_page_index"].find_one({"_id": self.f.p3}).raw
        self.f.run(M, *GUARD)
        self.assertEqual([d for d in self.f.db["plan_records"].docs
                          if bson.decode(d)["page_id"] == str(self.f.p3)], p3_before)
        self.assertEqual(self.f.db["document_page_index"].find_one(
            {"_id": self.f.p3}).raw, row_before)

    def test_every_write_leaves_an_audit_row(self):
        self.f.run(M, *GUARD)
        rows = [bson.decode(d) for d in self.f.db["audit_logs"].docs]
        self.assertEqual(len(rows), 5)       # P1: 2 updates; P2: delete, insert, update
        for r in rows:
            self.assertEqual(r["user_id"], "script:migrate_plan_discipline_20260921")
            self.assertEqual((r["reason"], r["session_id"]), ("test", "s-test"))

    def test_verify(self):
        self.assertEqual(self.f.run(M, "--verify")[0], 1)
        self.f.run(M, *GUARD)
        code, out = self.f.run(M, "--verify")
        self.assertEqual(code, 0, out)


class ItIsIdempotent(Base):

    def test_a_second_run_writes_nothing(self):
        self.f.run(M, *GUARD)
        image = self.f.image()
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 0)
        self.assertIn("Nothing to do", out)
        self.assertEqual(self.f.image(), image)

    def test_an_interrupted_run_resumes(self):
        rows = P.survey(self.f.db, P.with_project(P.load(self.f.dir)[0]),
                        *P.load(self.f.dir)[1:])
        M._write_page(self.f.db, rows[0])        # only P1, as if killed after it
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 0, out)
        self.assertIn("'target': 2", out)


class ACutOffRunIsFinishedNotRefused(Base):
    """A page is several writes. Whatever a dropped connection leaves between
    them must be finished by the next run of either script."""

    def _survey(self):
        plan, pages, recs = P.load(self.f.dir)
        return P.survey(self.f.db, P.with_project(plan), pages, recs)

    def test_a_replace_page_cut_off_after_its_delete(self):
        self.f.db["plan_records"].delete_many(
            {"project_id": PID, "file_id": "F2", "page_number": 3})
        states = {str(r.entry["page_id"]): r.state for r in self._survey()}
        self.assertEqual(states[str(self.f.p2)], P.PARTIAL)
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 0, out)
        self.assertIn("'target': 2", out)

    def test_a_discipline_page_with_half_its_rows_updated(self):
        coll = self.f.db["plan_records"]
        for i, d in enumerate(coll.docs):
            doc = bson.decode(d)
            if doc["page_id"] == str(self.f.p1):
                doc["discipline"] = "AR"
                coll.docs[i] = bson.encode(doc)
                break
        self.assertEqual(self._survey()[0].state, P.PARTIAL)
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 0, out)
        self.assertIn("'target': 2", out)

    def test_a_rollback_cut_off_mid_page_is_finished_byte_identical(self):
        original = {c: list(self.f.db[c].raw_sorted())
                    for c in ("document_page_index", "plan_records")}
        self.f.run(M, *GUARD)
        # as if killed after the delete of P1's rows, before their re-insert
        self.f.db["plan_records"].delete_many(
            {"project_id": PID, "file_id": "F1", "page_number": 1})
        self.assertEqual(self._survey()[0].state, P.PARTIAL)
        code, out = self.f.run(R, *GUARD)
        self.assertEqual(code, 0, out)
        for c, raws in original.items():
            self.assertEqual(self.f.db[c].raw_sorted(), raws, c)

    def test_a_row_this_plan_never_saw_is_not_partial(self):
        self.f.db["plan_records"].delete_many(
            {"project_id": PID, "file_id": "F2", "page_number": 3})
        self.f.db["plan_records"].insert_one(
            {"project_id": PID, "file_id": "F2", "page_number": 3,
             "page_id": str(self.f.p2), "quote": "from a re-index"})
        before = self.f.image()
        code, _ = self.f.run(M, *GUARD)
        self.assertEqual(code, 2)
        self.assertEqual(self.f.image(), before)


class ItRefusesAChangedPage(Base):

    def _reindex_p1(self):
        coll = self.f.db["plan_records"]
        for i, d in enumerate(coll.docs):
            doc = bson.decode(d)
            if doc["page_id"] == str(self.f.p1):
                doc["quote"] = "re-indexed"
                coll.docs[i] = bson.encode(doc)
                return

    def test_migrate_refuses_and_writes_nothing(self):
        self._reindex_p1()
        before = self.f.image()
        code, out = self.f.run(M, *GUARD)
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.f.image(), before)

    def test_rollback_refuses_and_writes_nothing(self):
        self.f.run(M, *GUARD)
        self._reindex_p1()
        before = self.f.image()
        code, out = self.f.run(R, *GUARD)
        self.assertEqual(code, 2)
        self.assertEqual(self.f.image(), before)

    def test_a_different_snapshot_is_refused(self):
        with open(os.path.join(self.f.dir, "snapshot", "pages.bson"), "ab") as f:
            f.write(b"")
        path = os.path.join(self.f.dir, "snapshot", "records.bson")
        with open(path, "rb") as f:
            blob = f.read()
        with open(path, "wb") as f:
            f.write(blob[:-1] + bytes([blob[-1] ^ 1]))
        before = self.f.image()
        with self.assertRaises(SystemExit):
            self.f.run(M, *GUARD)
        self.assertEqual(self.f.image(), before)


class RollbackIsByteIdentical(Base):

    def test_apply_then_rollback_restores_every_byte(self):
        original = {c: list(self.f.db[c].raw_sorted())
                    for c in ("document_page_index", "plan_records")}
        self.assertEqual(self.f.run(M, *GUARD)[0], 0)
        self.assertNotEqual(self.f.db["plan_records"].raw_sorted(),
                            original["plan_records"])
        code, out = self.f.run(R, *GUARD)
        self.assertEqual(code, 0, out)
        for c, raws in original.items():
            self.assertEqual(self.f.db[c].raw_sorted(), raws, c)

    def test_rollback_dry_run_writes_nothing(self):
        self.f.run(M, *GUARD)
        before = self.f.image()
        code, out = self.f.run(R)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.f.image(), before)

    def test_rollback_of_an_unmigrated_database_does_nothing(self):
        before = self.f.image()
        code, out = self.f.run(R, *GUARD)
        self.assertEqual(code, 0)
        self.assertIn("Nothing to roll back", out)
        self.assertEqual(self.f.image(), before)


class ItNeverDefaultsToADatabase(Base):
    """DB_NAME must be exactly 'blueview'. Unset or anything else stops the run
    before a connection, with nothing written, for BOTH scripts."""

    def _refused(self, module, env_db, *extra):
        before = self.f.image()
        with self.assertRaises(SystemExit) as cm:
            self.f.run(module, *extra, env_db=env_db)
        self.assertEqual(self.f.image(), before)
        return str(cm.exception.code)

    def test_unset_is_refused(self):
        for module in (M, R):
            msg = self._refused(module, None, *GUARD)
            self.assertIn("DB_NAME is not set", msg)
            self.assertIn("Nothing was written", msg)

    def test_the_old_default_is_refused(self):
        for module in (M, R):
            msg = self._refused(module, "test_database", *GUARD)
            self.assertIn("runs only against 'blueview'", msg)

    def test_a_dry_run_is_refused_too(self):
        self._refused(M, None)
        self._refused(M, "blueview_staging", "--verify")

    def test_no_default_database_is_left_in_either_script(self):
        from pathlib import Path
        for name in ("migrate_plan_discipline_20260921.py",
                     "rollback_plan_discipline_20260921.py"):
            src = (_BACKEND / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn('"test_database"', src, name)
            self.assertIn("P.target_db()", src, name)


class TheGate(Base):

    def test_apply_is_not_a_write_flag(self):
        before = self.f.image()
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                self.f.run(M, "--apply")
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.f.image(), before)

    def test_i_know_needs_a_reason_and_a_session(self):
        before = self.f.image()
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                self.f.run(M, "--i-know", "--session", "")
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.f.image(), before)


if __name__ == "__main__":
    unittest.main()
