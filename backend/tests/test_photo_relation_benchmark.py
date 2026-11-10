"""The benchmark's candidate pairs, its arithmetic, and its promises: no label a
person did not write, no "different" from a signal that merely did not match,
and no write to Mongo.

What it can't show here is the answer: there are no real labeled photos in this
repository, so no rate on a real pair is asserted anywhere below.
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


def _r(key, where="floor 3", day="2026-10-01", view="interior", log="L1", sub="A", work="Drywall", quality=8.0, **kw):
    return {"photo_key": key, "short": key, "where": where, "date": day, "view": view, "log_id": log, "sub": sub, "work": work,
            "quality": quality, "description": f"d {key}", "kind": "photo", **kw}


def _lab(label, inliers=0, epipolar=0, ok=True, kind=B.SAME_CREW_DAY, same="", conf="", gap=0):
    return {"label": label, "inliers": inliers, "epipolar_inliers": epipolar, "geometry_ok": ok, "candidate_kind": kind,
            "vision_same": same, "vision_confidence": conf, "stage_gap": gap}


class TheCandidates(unittest.TestCase):

    def _pairs(self, rows, n=50):
        return B.build_candidates(rows, per_kind=n)

    def _of(self, pairs, kind):
        return [p for p in pairs if p["candidate_kind"] == kind]

    def test_no_pair_carries_a_label(self):
        rows = [_r("a", where="floor 3"), _r("b", where="floor 4"), _r("c"), _r("d", day="2026-10-20", log="L2")]
        pairs = self._pairs(rows)
        self.assertTrue(pairs)
        self.assertEqual({p["label"] for p in pairs}, {""})
        self.assertIn("candidate_kind", B.FIELDS)

    def test_different_level_is_two_different_single_levels(self):
        pairs = self._of(self._pairs([_r("a", where="floor 3"), _r("b", where="floor 4"), _r("c", where="floor 3", day="2026-10-02")]),
                         B.DIFFERENT_LEVEL)
        self.assertTrue(pairs)
        self.assertTrue(all(p["level_a"] != p["level_b"] for p in pairs))

    def test_a_shared_row_is_never_a_different_level(self):
        rows = [_r("a", where="floors 1-4"), _r("b", where="floor 3"), _r("c", where="floor 5")]
        ids = {i for p in self._of(self._pairs(rows), B.DIFFERENT_LEVEL) for i in (p["key_a"], p["key_b"])}
        self.assertNotIn("a", ids)

    def test_outside_and_poor_photos_are_left_out(self):
        self.assertEqual(self._pairs([_r("a", view="building_front"), _r("b", where="floor 4", view="building_front")]), [])
        self.assertEqual(self._pairs([_r("a", quality=1), _r("b", quality=1)]), [])

    def test_same_crew_day(self):
        pairs = self._of(self._pairs([_r("a"), _r("b"), _r("c", sub="Other"), _r("d", log="L2")]), B.SAME_CREW_DAY)
        self.assertEqual([{p["key_a"], p["key_b"]} for p in pairs], [{"a", "b"}])

    def test_the_stage_of_a_row(self):
        for work, stage in (("Framing", 0), ("Domestic water rough", 1), ("Drywall", 2), ("Prime and paint", 3),
                            ("Framing, drywall", None), ("Cleanup", None)):
            with self.subTest(work=work):
                self.assertEqual(B.stage_of({"work": work}), stage)

    def test_across_stages_spreads_over_the_stage_gaps(self):
        works = ["Framing", "Domestic water rough", "Drywall", "Prime and paint"]
        rows = [_r(f"k{i}", day=f"2026-{(i % 9) + 1:02d}-{(i % 27) + 1:02d}", log=f"L{i}", work=works[i % 4]) for i in range(80)]
        pairs = self._of(B.build_candidates(rows, per_kind=8), B.ACROSS_STAGES)
        gaps = {p["stage_gap"] for p in pairs}
        self.assertLessEqual({0, 1, 2, 3}, gaps, "every gap represented, not just near-identical shots")
        self.assertTrue(all(B._gap_ok({"date": p["date_a"]}, {"date": p["date_b"]}) for p in pairs))

    def test_a_hard_negative_on_one_apartment_line(self):
        rows = [_r("a", where="floor 3 apt 3B"), _r("b", where="floor 4 apt 4B", log="L2"), _r("c", where="floor 4 apt 4C", log="L3")]
        pairs = self._of(self._pairs(rows), B.SAME_LINE_OTHER_FLOOR)
        self.assertEqual({frozenset((p["space_a"], p["space_b"])) for p in pairs}, {frozenset(("3B", "4B"))})
        self.assertEqual({p["label"] for p in pairs}, {""})

    def test_a_unit_read_in_the_photo_counts_for_the_line(self):
        self.assertEqual(B.unit_of({"where": "floors 1-4", "visible_text": ["APT 4B"]}), "4B")
        self.assertIsNone(B.unit_of({"where": "Apt 3B", "visible_text": ["4B"]}), "two units is none")

    def test_a_hard_negative_of_similar_rooms_on_one_floor(self):
        rows = [_r("a", where="floor 3 apt 3B", room_type="bathroom"), _r("b", where="floor 3 apt 3C", room_type="bathroom", log="L2"),
                _r("c", where="floor 3 apt 3D", room_type="kitchen", log="L3")]
        pairs = self._of(self._pairs(rows), B.SIMILAR_ROOM_SAME_FLOOR)
        self.assertEqual({frozenset((p["key_a"], p["key_b"])) for p in pairs}, {frozenset(("a", "b"))})

    def test_the_same_photos_give_the_same_pairs_and_each_kind_is_bounded(self):
        rows = [_r(f"k{i}", where=f"floor {i % 3 + 1}", day=f"2026-10-{i % 20 + 1:02d}", log=f"L{i}") for i in range(60)]
        self.assertEqual(B.build_candidates(rows, per_kind=7), B.build_candidates(rows, per_kind=7))
        pairs = B.build_candidates(rows, per_kind=7)
        for kind in B.KINDS:
            self.assertLessEqual(len(self._of(pairs, kind)), 7)
        self.assertEqual(len({p["pair_id"] for p in pairs}), len(pairs))

    def test_the_earlier_photo_comes_first(self):
        p = B._pair(_r("b", day="2026-11-01"), _r("a", day="2026-10-01"), B.ACROSS_STAGES)
        self.assertEqual((p["key_a"], p["key_b"]), ("a", "b"))

    def test_a_link_points_at_the_photo_in_its_log(self):
        log = {"_id": "L1", "data": {"activities": [{"photos": [{"enhanced_r2_key": "other"}]}, {"photos": [{}, {"enhanced_r2_key": "wanted"}]}]}}
        self.assertEqual(B.photo_address(log, "wanted"), (1, 1))
        self.assertIsNone(B.photo_address(log, "missing"))


class OnlyAPersonsLabelCounts(unittest.TestCase):

    def _csv(self, labels):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "p.csv")
        B.write_pairs([{**{f: "" for f in B.FIELDS}, "key_a": "a", "key_b": "b", "label": x} for x in labels], path)
        return path

    def test_blank_and_unsure_are_not_scored(self):
        keep, not_scored = B.read_labels(self._csv(["Same", "different", "", "unsure"]))
        self.assertEqual(([r["label"] for r in keep], not_scored), (["same", "different"], 2))

    def test_a_typo_refuses_the_file(self):
        with self.assertRaises(B.BadLabel):
            B.read_labels(self._csv(["same", "differnt"]))

    def test_an_unlabeled_file_is_refused_before_anything_is_measured(self):
        path = self._csv(["", "", "unsure"])
        with patch.object(B, "measure", side_effect=AssertionError("measured")), redirect_stdout(io.StringIO()) as out:
            rc = _run(B.run_evaluate(path, vision=False, max_calls=0, out_path=None, ceiling=0.05))
        self.assertEqual(rc, 2)
        self.assertIn("Refused: no row has a label a person filled in", out.getvalue())

    def test_the_csv_columns(self):
        with open(self._csv(["same"]), newline="", encoding="utf-8") as fh:
            self.assertEqual(csv.DictReader(fh).fieldnames, B.FIELDS)


class TheTwoErrors(unittest.TestCase):

    def test_false_positives_and_misses_are_apart_with_their_rates(self):
        rows = [_lab("same", 50), _lab("same", 5), _lab("different", 40), _lab("different", 2), _lab("different", 1)]
        self.assertEqual(B.errors(rows, lambda r: r["inliers"] >= 10),
                         {"false_positives": 1, "different": 3, "fp_rate": 0.3333, "missed": 1, "same": 2, "miss_rate": 0.5})

    def test_a_miss_is_unconfirmed_and_never_a_false_positive(self):
        e = B.errors([_lab("different", 0), _lab("different", 0, ok=False)], lambda r: r["inliers"] >= 10)
        self.assertEqual(e["false_positives"], 0)

    def test_a_rate_with_no_denominator_is_none(self):
        e = B.errors([_lab("different", 0)], lambda r: False)
        self.assertEqual((e["fp_rate"], e["miss_rate"]), (0.0, None))

    def test_combined_mirrors_the_live_rule(self):
        rows = [_lab("same", 99, same="no", conf=0.9), _lab("same", 0, same="yes", conf=0.9), _lab("same", 99, same="unsure", conf=0.1)]
        combined = {s: says for f, s, _r, says in B.signals(rows) if f == "combined"}
        said = combined["inliers>=15 or yes>=0.7"]
        self.assertEqual([said(r) for r in rows], [False, True, True], "a model's no is not overruled by geometry")

    def test_the_report_names_both_errors_and_each_signal(self):
        rows = [_lab("same", 50, same="yes", conf=0.9, gap=2), _lab("different", 0, same="no", conf=0.9, gap=0)]
        out = "\n".join(B.report(rows, 3, 2))
        for piece in ("Same-place FALSE POSITIVES", "MISSED same-place matches", "geometry ", "vision ", "combined ",
                      "stage gap 2:", "stage gap 0:", "Not scored (blank or unsure): 3", "Vision calls made: 2.",
                      "TOO FEW to set a threshold", "says UNCONFIRMED"):
            self.assertIn(piece, out)

    def test_an_unmeasured_pair_is_unconfirmed_not_different(self):
        self.assertIn("counted as unconfirmed by geometry, never as different", "\n".join(B.report([_lab("same", 0, ok=False)], 0, 0)))


class TheVerdict(unittest.TestCase):

    def _many(self, fp_at_10):
        same = [_lab("same", 60)] * B.FEW_LABELS
        other = [_lab("different", 12)] * fp_at_10 + [_lab("different", 2)] * (B.FEW_LABELS - fp_at_10)
        return same + other

    def _verdict(self, rows, ceiling):
        return "\n".join(B.report(rows, 0, 0, ceiling=ceiling))

    def test_no_ceiling_no_verdict(self):
        self.assertIn("Verdict: none. Pass --fp-ceiling", self._verdict(self._many(0), None))

    def test_it_picks_the_setting_under_the_ceiling_with_the_fewest_misses(self):
        out = self._verdict(self._many(3), 0.0)
        self.assertIn("geometry: WOULD ENABLE at inliers>=15: false positives 0/30", out)

    def test_a_ceiling_nothing_meets_is_said(self):
        rows = [_lab("same", 60)] * B.FEW_LABELS + [_lab("different", 200)] * B.FEW_LABELS
        self.assertIn("geometry: WOULD NOT ENABLE: no setting keeps false positives", self._verdict(rows, 0.01))

    def test_too_few_labels_never_enables(self):
        self.assertIn("geometry: WOULD NOT ENABLE: fewer than", self._verdict([_lab("same", 60), _lab("different", 0)], 0.5))

    def test_the_ceiling_is_a_rate(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            B.parse_args(["evaluate", "p.csv", "--fp-ceiling", "5"])
        self.assertEqual(B.parse_args(["evaluate", "p.csv", "--fp-ceiling", "0.02"]).fp_ceiling, 0.02)


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
