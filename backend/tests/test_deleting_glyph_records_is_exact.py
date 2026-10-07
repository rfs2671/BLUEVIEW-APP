"""DELETING GLYPH ROWS DELETES THOSE ROWS AND NOTHING ELSE.

scripts/delete_glyph_records.py removes the rows the placement pass wrote
(operator ruling 2026-10-06: the count gate bound a partial glyph count as a
total, so the rows come out until the reader is fixed). A production delete
is the one operation here that cannot be undone by re-reading anything, so
each property it claims is checked against a database that holds the rows
it must NOT touch: other records on the project, glyph rows on another
project, and glyph-typed rows another writer might produce.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

try:                                     # absent on main: tests FAIL, not error
    from scripts import delete_glyph_records as G
except ImportError:                      # pragma: no cover
    G = None

PID, OTHER_PID = "6a5f63bc147407d3261df2c7", "ffffffffffffffffffffffff"


def _present():
    assert G is not None, "scripts.delete_glyph_records is not in this tree"


def _matches(doc, flt):
    for k, v in flt.items():
        if isinstance(v, dict) and "$ne" in v:
            if doc.get(k) == v["$ne"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


class _Result:
    def __init__(self, n):
        self.deleted_count = n


class _Coll:
    def __init__(self, docs, leak=0):
        self.docs, self.leak = list(docs), leak

    def count_documents(self, flt):
        return sum(1 for d in self.docs if _matches(d, flt))

    def find(self, flt, proj=None):
        return [dict(d) for d in self.docs if _matches(d, flt)]

    def delete_many(self, flt):
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        if self.leak:                    # a delete that took something else
            keep = keep[self.leak:]
        self.docs = keep
        return _Result(n)


class _Db:
    def __init__(self, coll):
        self.plan_records = coll


def _glyph(i, pid=PID, **kw):
    return dict({"project_id": pid, "record_type": "glyph",
                 "tier": "registered_glyph", "source": "plan_takeoff",
                 "sheet_number": f"M-10{i % 4}.00", "i": i}, **kw)


def _world(n_glyph=84, leak=0):
    docs = [_glyph(i) for i in range(n_glyph)]
    docs += [{"project_id": PID, "record_type": t, "i": i}
             for i, t in enumerate(["schedule", "element", "note"] * 10)]
    docs += [_glyph(i, pid=OTHER_PID) for i in range(5)]
    docs += [_glyph(900, source="some_other_writer"),
             _glyph(901, tier="vision_read")]
    return _Db(_Coll(docs, leak))


def _run(db, expect, write):
    out = io.StringIO()
    with redirect_stdout(out):
        code = G.run(db, PID, expect, write)
    return code, out.getvalue()


class TheFilterIsTheRowsThePassWrote(unittest.TestCase):

    def test_every_clause(self):
        _present()
        self.assertEqual(G.glyph_filter(PID),
                         {"project_id": PID, "record_type": "glyph",
                          "tier": "registered_glyph", "source": "plan_takeoff"})


class ADryRunChangesNothing(unittest.TestCase):

    def test_it_reports_and_deletes_nothing(self):
        _present()
        db = _world()
        before = len(db.plan_records.docs)
        code, out = _run(db, 84, write=False)
        self.assertEqual(code, G.OK)
        self.assertEqual(len(db.plan_records.docs), before)
        self.assertIn("glyph rows matching the filter: 84", out)
        self.assertIn("other records on the project:   30", out)
        self.assertIn("DRY RUN", out)


class ASurpriseCountRefuses(unittest.TestCase):

    def test_more_than_expected_refuses_even_with_the_flag(self):
        _present()
        db = _world(n_glyph=85)
        before = len(db.plan_records.docs)
        code, out = _run(db, 84, write=True)
        self.assertEqual(code, G.REFUSED)
        self.assertEqual(len(db.plan_records.docs), before)
        self.assertIn("REFUSED", out)

    def test_fewer_than_expected_refuses(self):
        _present()
        code, _out = _run(_world(n_glyph=80), 84, write=True)
        self.assertEqual(code, G.REFUSED)


class TheDeleteTakesExactlyThoseRows(unittest.TestCase):

    def test_only_the_projects_pass_rows_go(self):
        _present()
        db = _world()
        code, out = _run(db, 84, write=True)
        self.assertEqual(code, G.OK, out)
        left = db.plan_records.docs
        self.assertEqual(sum(1 for d in left if d.get("project_id") == PID
                             and d.get("record_type") == "glyph"
                             and d.get("source") == "plan_takeoff"
                             and d.get("tier") == "registered_glyph"), 0)
        self.assertEqual(sum(1 for d in left if d.get("project_id") == PID
                             and d.get("record_type") != "glyph"), 30)
        self.assertEqual(sum(1 for d in left if d.get("project_id") == OTHER_PID), 5)
        self.assertEqual(sum(1 for d in left if d.get("i") in (900, 901)), 2)
        self.assertIn("DELETED 84", out)
        self.assertIn("other records before / after: 30 / 30", out)

    def test_a_delete_that_moved_anything_else_fails_loudly(self):
        _present()
        code, out = _run(_world(leak=1), 84, write=True)
        self.assertEqual(code, G.FAILED)
        self.assertIn("FAILED", out)


class TheGuardStandsInFront(unittest.TestCase):

    def test_the_flag_without_a_reason_is_an_error(self):
        _present()
        argv = ["delete_glyph_records", "--project", PID, "--expect", "84",
                "--i-know", "--session", "s1"]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()), \
                patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                G.main()
        self.assertEqual(e.exception.code, 2)

    def test_expect_is_required(self):
        _present()
        argv = ["delete_glyph_records", "--project", PID]
        with patch.object(sys, "argv", argv), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                G.main()
        self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
