"""The benchmark's arithmetic, its candidate pairs and its promise not to write.

What it can't show here is the answer: there are no real labeled photos in this
repository, so no precision on a real pair is asserted anywhere below.
"""

from __future__ import annotations

import ast
import copy
import csv
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import photo_relation_benchmark as B  # noqa: E402
from tests.test_dm_brain import _Brain  # noqa: E402
from tests.test_whatsapp_dm_assistant import _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402

import server  # noqa: E402

SCRIPT = (_BACKEND / "scripts" / "photo_relation_benchmark.py").read_text(encoding="utf-8")
WRITES = {"insert_one", "insert_many", "update_one", "update_many", "delete_one", "delete_many", "replace_one",
          "bulk_write", "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "record_vision_call"}


def _r(key, where="floor 3", day="2026-10-01", view="interior", log="L1", sub="A", work="Drywall", quality=8.0):
    return {"photo_key": key, "short": key, "where": where, "date": day, "view": view, "log_id": log, "sub": sub, "work": work,
            "quality": quality, "description": f"d {key}", "kind": "photo"}


def _lab(label, inliers=0, epipolar=0, ok=True, cls=B.PROBABLE_SAME, same="", conf=""):
    return {"label": label, "inliers": inliers, "epipolar_inliers": epipolar, "geometry_ok": ok, "candidate_class": cls,
            "vision_same": same, "vision_confidence": conf}


class TheCandidates(unittest.TestCase):

    def _pairs(self, rows):
        return B.build_candidates(rows, per_class=50)

    def _of(self, pairs, cls):
        return [p for p in pairs if p["candidate_class"] == cls]

    def test_known_different_is_two_different_single_levels(self):
        rows = [_r("a", where="floor 3"), _r("b", where="floor 4"), _r("c", where="floor 3", day="2026-10-02")]
        pairs = self._of(self._pairs(rows), B.KNOWN_DIFFERENT)
        self.assertTrue(pairs)
        for p in pairs:
            self.assertNotEqual(p["level_a"], p["level_b"])
            self.assertEqual(p["label"], "different")

    def test_a_shared_row_is_never_known_different(self):
        rows = [_r("a", where="floors 1-4"), _r("b", where="floor 3"), _r("c", where="floor 5")]
        ids = {i for p in self._of(self._pairs(rows), B.KNOWN_DIFFERENT) for i in (p["key_a"], p["key_b"])}
        self.assertNotIn("a", ids)

    def test_two_kinds_of_view_are_not_a_different_pair(self):
        rows = [_r("a", where="floor 3", view="basement"), _r("b", where="floor 4", view="interior")]
        self.assertEqual(self._of(self._pairs(rows), B.KNOWN_DIFFERENT), [])

    def test_outside_photos_are_left_out(self):
        rows = [_r("a", where="floor 3", view="building_front"), _r("b", where="floor 4", view="building_front")]
        self.assertEqual(self._pairs(rows), [])

    def test_probable_same_is_one_crew_row_on_one_day_and_unlabeled(self):
        rows = [_r("a"), _r("b"), _r("c", sub="Other"), _r("d", log="L2")]
        pairs = self._of(self._pairs(rows), B.PROBABLE_SAME)
        self.assertEqual([{p["key_a"], p["key_b"]} for p in pairs], [{"a", "b"}])
        self.assertEqual(pairs[0]["label"], "")

    def test_same_level_later_needs_the_days_between(self):
        rows = [_r("a", log="L1"), _r("b", day="2026-10-02", log="L2"), _r("c", day="2026-10-15", log="L3")]
        pairs = self._of(self._pairs(rows), B.SAME_LEVEL_LATER)
        self.assertTrue(pairs)
        self.assertTrue(all({p["key_a"], p["key_b"]} != {"a", "b"} for p in pairs))
        self.assertEqual({p["label"] for p in pairs}, {""})

    def test_a_poor_photo_is_left_out(self):
        self.assertEqual(self._pairs([_r("a", quality=1), _r("b", quality=1)]), [])

    def test_the_same_photos_give_the_same_pairs(self):
        rows = [_r(f"k{i}", where=f"floor {i % 3 + 1}", day=f"2026-10-{i + 1:02d}", log=f"L{i}") for i in range(12)]
        self.assertEqual(self._pairs(rows), self._pairs(rows))

    def test_each_class_is_bounded_and_a_pair_appears_once(self):
        rows = [_r(f"k{i}", where=f"floor {i % 3 + 1}", day=f"2026-10-{i % 20 + 1:02d}", log=f"L{i}") for i in range(60)]
        pairs = B.build_candidates(rows, per_class=7)
        for cls in (B.KNOWN_DIFFERENT, B.SAME_LEVEL_LATER):
            self.assertLessEqual(len(self._of(pairs, cls)), 7)
        self.assertEqual(len({p["pair_id"] for p in pairs}), len(pairs))

    def test_the_earlier_photo_comes_first(self):
        p = B._pair(_r("b", day="2026-11-01"), _r("a", day="2026-10-01"), B.SAME_LEVEL_LATER)
        self.assertEqual((p["key_a"], p["key_b"]), ("a", "b"))

    def test_a_link_points_at_the_photo_in_its_log(self):
        log = {"_id": "L1", "data": {"activities": [{"photos": [{"enhanced_r2_key": "other"}]}, {"photos": [{}, {"enhanced_r2_key": "wanted"}]}]}}
        self.assertEqual(B.photo_address(log, "wanted"), (1, 1))
        self.assertIsNone(B.photo_address(log, "missing"))


class TheArithmetic(unittest.TestCase):

    def test_a_confusion_table(self):
        rows = [_lab("same", 50), _lab("same", 5), _lab("different", 40), _lab("different", 2), _lab("different", 1)]
        self.assertEqual(B.confusion(rows, lambda r: r["inliers"] >= 10),
                         {"tp": 1, "fp": 1, "fn": 1, "tn": 2, "precision": 0.5, "recall": 0.5})

    def test_a_rate_with_no_denominator_is_none(self):
        c = B.confusion([_lab("different", 0)], lambda r: False)
        self.assertEqual((c["precision"], c["recall"]), (None, None))

    def test_the_report_warns_when_labels_are_few(self):
        out = "\n".join(B.report([_lab("same", 50), _lab("different", 0)], 3, 0))
        self.assertIn("TOO FEW to set a threshold", out)
        self.assertIn("Left out, no usable label: 3", out)

    def test_enough_labels_do_not_warn(self):
        rows = [_lab("same", 50)] * B.FEW_LABELS + [_lab("different", 0)] * B.FEW_LABELS
        self.assertNotIn("TOO FEW", "\n".join(B.report(rows, 0, 0)))

    def test_unmeasured_pairs_are_named(self):
        self.assertIn("1 pair(s) could not be measured", "\n".join(B.report([_lab("same", 0, ok=False)], 0, 0)))

    def test_vision_appears_only_when_it_was_asked(self):
        self.assertNotIn("Vision on", "\n".join(B.report([_lab("same", 1)], 0, 0)))
        out = "\n".join(B.report([_lab("same", 1, same="yes", conf=0.9), _lab("different", 1, same="unsure", conf=0.9)], 0, 2))
        self.assertIn("Vision on 2 pair(s)", out)
        self.assertIn("Vision calls made: 2.", out)

    def test_the_csv_round_trip_keeps_only_real_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "p.csv")
            B.write_pairs([{**{f: "" for f in B.FIELDS}, "key_a": "a", "key_b": "b", "label": x} for x in ("Same", "different", "", "maybe")], path)
            with open(path, newline="", encoding="utf-8") as fh:
                self.assertEqual(csv.DictReader(fh).fieldnames, B.FIELDS)
            keep, left = B.read_labels(path)
        self.assertEqual(([r["label"] for r in keep], left), (["same", "different"], 2))


class VisionNeedsBothFlags(unittest.TestCase):

    def test_vision_without_a_cap_is_refused(self):
        for argv in (["evaluate", "p.csv", "--vision"], ["evaluate", "p.csv", "--vision", "--max-calls", "0"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                B.parse_args(argv)

    def test_no_vision_by_default(self):
        self.assertFalse(B.parse_args(["evaluate", "p.csv"]).vision)
        self.assertEqual(B.parse_args(["evaluate", "p.csv", "--vision", "--max-calls", "5"]).max_calls, 5)


class ItWritesNothing(_Brain):

    def test_no_write_call_appears_in_the_script(self):
        calls = {n.func.attr for n in ast.walk(ast.parse(SCRIPT)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(calls & WRITES, set())

    def test_measuring_changes_no_collection_and_the_cap_holds(self):
        self.db[server.PHOTO_INDEX].rows += [{"_id": f"v1:{k}", "kind": "photo", "photo_key": k, "log_id": "L", "project_id": "p"} for k in "abcd"]
        pairs = [{"key_a": "a", "key_b": "b", "label": "same"}, {"key_a": "c", "key_b": "d", "label": "different"}]
        before = copy.deepcopy({n: c.rows for n, c in self.db._c.items()})
        calls = []

        async def bytes_of(row):
            return b"x"

        async def compare(a, b, pid, *, meter=True):
            calls.append(meter)
            return {"same_area": "yes", "confidence": 0.9}
        with _Ctx(db=self.db), patch.object(server, "_photo_log_bytes", bytes_of), patch.object(server, "_photo_compare_call", compare):
            rows, used = _run(B.measure(pairs, vision=True, max_calls=1))
        self.assertEqual((calls, used), ([False], 1), "unmetered, because a meter is a write")
        self.assertEqual([r["vision_same"] for r in rows], ["yes", ""])
        self.assertEqual({n: c.rows for n, c in self.db._c.items()}, before)

    def test_a_photo_it_cannot_find_is_counted_unmeasured(self):
        with _Ctx(db=self.db):
            rows, _ = _run(B.measure([{"key_a": "x", "key_b": "y", "label": "same"}], vision=False, max_calls=0))
        self.assertEqual((rows[0]["geometry_ok"], rows[0]["inliers"]), (False, 0))

    def test_the_unmetered_path_exists_only_on_the_compare_call(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        body = src[src.index("async def _photo_compare_call("):src.index("async def _photo_log_bytes(")]
        self.assertIn("if meter:\n        await record_vision_call(", body)
        self.assertEqual(src.count("meter=False"), 0, "only the benchmark, in its own file")


if __name__ == "__main__":
    unittest.main()
