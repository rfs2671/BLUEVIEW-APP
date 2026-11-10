"""The benchmark's candidate pairs, its arithmetic, and its promises: no label a
person did not write, no pair scored on one person's label or on a disagreement,
no "different" from a signal that merely did not match, no verdict from a small
sample, no name on the contact sheet, and no write to Mongo.

What it can't show here is the answer: there are no real labeled photos in this
repository, so no rate on a real pair is asserted anywhere below.
"""

from __future__ import annotations

import ast
import copy
import csv
import io
import math
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
from lib import benchmark_stats as S  # noqa: E402
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


def _lab(label, inliers=0, epipolar=0, ok=True, kind=B.SAME_CREW_DAY, same="", conf="", gap=0, project="p1"):
    return {"label": label, "inliers": inliers, "epipolar_inliers": epipolar, "geometry_ok": ok, "candidate_kind": kind,
            "vision_same": same, "vision_confidence": conf, "stage_gap": gap, "project_id": project}


def _enough(fp_at_10=0, negatives=160, projects=("p1", "p2"), gaps=(0, 1, 2), hard_every=2):
    """Enough labeled pairs for a 2% ceiling at 0 false positives (149): every
    other negative hard, two projects, three stage gaps among 30 same pairs."""
    same = [_lab("same", 60, gap=gaps[i % len(gaps)], project=projects[i % len(projects)]) for i in range(30)]
    other = [_lab("different", 12 if i < fp_at_10 else 2, project=projects[i % len(projects)],
                  kind=B.SAME_LINE_OTHER_FLOOR if i % hard_every == 0 else B.DIFFERENT_LEVEL) for i in range(negatives)]
    return same + other


class TheCandidates(unittest.TestCase):

    def _pairs(self, rows, n=50):
        return B.build_candidates(rows, per_kind=n)

    def _of(self, pairs, kind):
        return [p for p in pairs if p["candidate_kind"] == kind]

    def test_no_pair_carries_a_label(self):
        rows = [_r("a", where="floor 3"), _r("b", where="floor 4"), _r("c"), _r("d", day="2026-10-20", log="L2")]
        pairs = self._pairs(rows)
        self.assertTrue(pairs)
        self.assertEqual({p[c] for p in pairs for c in B.LABEL_COLUMNS}, {""})
        for col in ("candidate_kind", "label_a", "label_b", "label_resolved", "sheet_id", "project_id"):
            self.assertIn(col, B.FIELDS)
        self.assertNotIn("label", B.FIELDS, "one column for one person is not an independent label")

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
        self.assertEqual({p[c] for p in pairs for c in B.LABEL_COLUMNS}, {""})

    def test_two_lines_are_not_one(self):
        rows = [_r("a", where="floor 3 apt 3B"), _r("b", where="floor 4 apt 4C", log="L2")]
        self.assertEqual(self._of(self._pairs(rows), B.SAME_LINE_OTHER_FLOOR), [])

    def test_a_rare_stage_gap_is_not_crowded_out(self):
        """Forty framing photos and four finish photos on one level: most pairs
        are framing against framing, and the quota still reaches the rare gap."""
        rows = [_r(f"f{i}", day=f"2026-{i % 9 + 1:02d}-{i % 27 + 1:02d}", log=f"F{i}", work="Framing") for i in range(40)]
        rows += [_r(f"p{i}", day=f"2026-1{i % 3}-{i + 1:02d}", log=f"P{i}", work="Prime and paint") for i in range(4)]
        pairs = self._of(B.build_candidates(rows, per_kind=6), B.ACROSS_STAGES)
        gaps = [p["stage_gap"] for p in pairs]
        self.assertEqual((gaps.count(0), gaps.count(3)), (3, 3), gaps)

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


class OnlyTwoPeoplesLabelsCount(unittest.TestCase):

    def _csv(self, labels, fields=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "p.csv")
        rows = [{**{f: "" for f in B.FIELDS}, "key_a": f"a{i}", "key_b": f"b{i}", "label_a": a, "label_b": b, "label_resolved": r}
                for i, (a, b, r) in enumerate(labels)]
        if fields is None:
            B.write_pairs(rows, path)
        else:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows([{**r, "label": r["label_a"]} for r in rows])
        return path

    def test_only_agreed_or_resolved_pairs_are_scored(self):
        keep, tally = B.read_labels(self._csv([("Same", "same", ""), ("different", "different", ""), ("", "", ""),
                                               ("unsure", "unsure", ""), ("same", "", ""), ("same", "different", ""),
                                               ("same", "different", "different")]))
        self.assertEqual([(r["key_a"], r["label"]) for r in keep], [("a0", "same"), ("a1", "different"), ("a6", "different")])
        self.assertEqual({k: tally.get(k) for k in ("scored", "blank", "unsure", "one_label", "disputed")},
                         {"scored": 3, "blank": 1, "unsure": 1, "one_label": 1, "disputed": 1})
        self.assertEqual((tally["kappa"]["n"], tally["kappa"]["agreed"]), (5, 3))

    def test_a_disagreement_is_excluded_until_resolved(self):
        keep, tally = B.read_labels(self._csv([("same", "different", "")] * 3))
        self.assertEqual((keep, tally["disputed"]), ([], 3))

    def test_a_typo_refuses_the_file(self):
        for labels in ([("same", "differnt", "")], [("same", "different", "smae")]):
            with self.subTest(labels=labels), self.assertRaises(B.BadLabel):
                B.read_labels(self._csv(labels))

    def test_a_one_person_file_is_refused(self):
        """The old single `label` column: one person's labels are never scored."""
        with self.assertRaises(B.BadLabel):
            B.read_labels(self._csv([("same", "same", "")], fields=["pair_id", "key_a", "key_b", "label"]))

    def test_an_unscored_file_is_refused_before_anything_is_measured(self):
        path = self._csv([("", "", ""), ("same", "", ""), ("same", "different", "")])
        with patch.object(B, "measure", side_effect=AssertionError("measured")), redirect_stdout(io.StringIO()) as out:
            rc = _run(B.run_evaluate(path, vision=False, max_calls=0, out_path=None, ceiling=0.05))
        self.assertEqual(rc, 2)
        self.assertIn("Refused: no pair has two agreeing labels", out.getvalue())

    def test_the_csv_columns(self):
        with open(self._csv([("same", "same", "")]), newline="", encoding="utf-8") as fh:
            self.assertEqual(csv.DictReader(fh).fieldnames, B.FIELDS)


class TheTwoErrors(unittest.TestCase):

    def test_a_miss_is_unconfirmed_and_never_a_false_positive(self):
        e = S.errors([_lab("different", 0), _lab("different", 0, ok=False)], lambda r: r["inliers"] >= 10)
        self.assertEqual(e["fp"]["k"], 0)

    def test_combined_mirrors_the_live_rule(self):
        rows = [_lab("same", 99, same="no", conf=0.9), _lab("same", 0, same="yes", conf=0.9), _lab("same", 99, same="unsure", conf=0.1)]
        combined = {s: says for f, s, _r, says in B.signals(rows) if f == "combined"}
        said = combined["inliers>=15 or yes>=0.7"]
        self.assertEqual([said(r) for r in rows], [False, True, True], "a model's no is not overruled by geometry")

    def test_the_report_names_both_errors_each_signal_each_stratum_and_the_intervals(self):
        rows = [_lab("same", 50, same="yes", conf=0.9, gap=2), _lab("different", 0, same="no", conf=0.9, gap=0, project="p2",
                                                                   kind=B.SIMILAR_ROOM_SAME_FLOOR)]
        tally = {"blank": 3, "one_label": 1, "unsure": 0, "disputed": 2, "kappa": S.cohen_kappa([("same", "same"), ("same", "different")])}
        out = "\n".join(B.report(rows, tally, 2, ceiling=0.02))
        for piece in ("Same-place FALSE POSITIVES", "MISSED same-place matches", "geometry ", "vision ", "combined ",
                      "construction-stage gap 2:", "construction-stage gap 0:", "project p1:", "project p2:",
                      "negative kind hard:", "negative kind easy:", "blank 3, one label only 1", "disputed 2",
                      "Cohen's kappa 0.000", "Vision calls made: 2.", "says UNCONFIRMED",
                      "0/1 = 0.000, 95% exact 0.0000-0.9750, Wilson 0.0000-0.7935, one-sided upper 0.9500",
                      "a ceiling of 0.02 needs: 149 at 0 false positive(s), 236 at 1 false positive(s), 313 at 2"):
            self.assertIn(piece, out)

    def test_an_unmeasured_pair_is_unconfirmed_not_different(self):
        out = "\n".join(B.report([_lab("same", 0, ok=False)], {}, 0))
        self.assertIn("counted as unconfirmed by geometry, never as different", out)
        self.assertIn("no pair was labeled by both people", out)


class TheVerdict(unittest.TestCase):

    def _verdict(self, rows, ceiling):
        return "\n".join(B.report(rows, {}, 0, ceiling=ceiling))

    def test_no_ceiling_no_verdict(self):
        self.assertIn("Verdict: none. Pass --fp-ceiling", self._verdict(_enough(), None))

    def test_enough_labels_enable_the_setting_with_the_fewest_misses_under_the_bound(self):
        out = self._verdict(_enough(fp_at_10=3), 0.02)
        self.assertIn("geometry: WOULD ENABLE at inliers>=15: false positives 0/160 = 0.000", out)
        self.assertIn("confirm on a fresh sample", out)

    def test_a_signal_that_never_says_same_is_not_enabled(self):
        out = self._verdict(_enough(), 0.02)
        self.assertIn("geometry_epipolar: WOULD NOT ENABLE", out)
        self.assertIn("confirms none of the 30 same-place pairs", out)

    def test_thirty_negatives_never_enable_two_percent(self):
        """The ruling's case: 0 false positives in 30 is an upper bound of 9.5%."""
        out = self._verdict(_enough(negatives=30), 0.02)
        self.assertIn("geometry: WOULD NOT ENABLE", out)
        self.assertIn("one-sided 95% upper bound of the false-positive rate is 0.0950, not under the ceiling 0.02", out)
        self.assertIn("independently labeled negatives: have 30, need 149 (at 0 false positive(s) observed); 119 more", out)

    def test_each_missing_requirement_is_named(self):
        for kw, piece in (({"projects": ("p1",)}, "projects among the negatives: have 1, need 2"),
                          ({"gaps": (0, 1)}, "construction-stage-gap strata among the same-place pairs: have 2"),
                          ({"hard_every": 4}, "hard negatives: have 40 of 160, need at least 1/3 (54)")):
            with self.subTest(kw=kw):
                out = self._verdict(_enough(**kw), 0.02)
                self.assertIn("geometry: WOULD NOT ENABLE", out)
                self.assertIn(piece, out)

    def test_a_ceiling_nothing_meets_is_said(self):
        rows = [dict(r, inliers=200) for r in _enough()]
        out = self._verdict(rows, 0.01)
        self.assertIn("geometry: WOULD NOT ENABLE", out)
        self.assertIn("not under the ceiling 0.01", out)

    def test_vision_on_a_few_calls_never_enables(self):
        rows = _enough()
        for r in rows[:40]:
            r.update(vision_same="yes" if S.is_same(r) else "no", vision_confidence=0.95)
        out = self._verdict(rows, 0.02)
        self.assertIn("vision: WOULD NOT ENABLE", out)
        self.assertIn("geometry: WOULD ENABLE", out)

    def test_the_ceiling_is_a_rate(self):
        for v in ("5", "0", "1"):
            with self.subTest(v=v), self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                B.parse_args(["evaluate", "p.csv", "--fp-ceiling", v])
        self.assertEqual(B.parse_args(["evaluate", "p.csv", "--fp-ceiling", "0.02"]).fp_ceiling, 0.02)


def _project_rows(pid, n=60, floors=4):
    """Photos of one project over `floors` levels and four stages, with unit
    lines and room types, so every candidate kind has a pool."""
    works = ["Framing", "Domestic water rough", "Drywall", "Prime and paint"]
    rooms = ["bathroom", "kitchen"]
    out = []
    for i in range(n):
        floor = i % floors + 2
        out.append(_r(f"{pid}-k{i}", where=f"floor {floor} apt {floor}{'BC'[i % 2]}", day=f"2026-{i % 9 + 1:02d}-{i % 27 + 1:02d}",
                      log=f"{pid}-L{i % 20}", sub="AB"[i % 2], work=works[(i // 3) % 4], room_type=rooms[(i // 2) % 2],
                      project_id=pid))
    return out


class ThePlan(unittest.TestCase):

    def test_quotas_are_sized_for_the_ceiling_and_half_hard(self):
        q = B.kind_quotas(0.02, expect_errors=1, overdraw=1.25)
        negatives = q[B.DIFFERENT_LEVEL] + q[B.SAME_LINE_OTHER_FLOOR] + q[B.SIMILAR_ROOM_SAME_FLOOR]
        self.assertEqual(negatives, math.ceil(236 * 1.25))
        self.assertGreaterEqual(3 * (q[B.SAME_LINE_OTHER_FLOOR] + q[B.SIMILAR_ROOM_SAME_FLOOR]), negatives)
        self.assertEqual(q[B.ACROSS_STAGES] + q[B.SAME_CREW_DAY], math.ceil(negatives * 0.5))
        self.assertEqual(sum(B.kind_quotas(0.02, expect_errors=0, overdraw=1).values()) - 75, 149)

    def test_every_project_is_drawn_from_and_no_label_is_filled(self):
        rows = {"p1": _project_rows("p1"), "p2": _project_rows("p2"), "p3": _project_rows("p3", n=12)}
        quotas = {k: 12 for k in B.KINDS}
        pairs = B.plan_pairs(rows, quotas, seed=7)
        self.assertEqual({p["project_id"] for p in pairs}, {"p1", "p2", "p3"})
        self.assertEqual({p[c] for p in pairs for c in B.LABEL_COLUMNS}, {""})
        for p in pairs:
            self.assertTrue(p["key_a"].startswith(p["project_id"] + "-") and p["key_b"].startswith(p["project_id"] + "-"),
                            "a pair never crosses projects")
            self.assertEqual(p["sheet_id"], S.sheet_id(p["pair_id"]))
        kinds = S.tally(pairs, S.kind)
        for kind in B.KINDS:
            self.assertLessEqual(kinds.get(kind, 0), 12)
        self.assertGreater(kinds.get(B.SAME_LINE_OTHER_FLOOR, 0), 0)
        self.assertGreater(kinds.get(B.SIMILAR_ROOM_SAME_FLOOR, 0), 0)
        self.assertEqual(len({p["pair_id"] for p in pairs}), len(pairs))
        self.assertEqual(pairs, B.plan_pairs(rows, quotas, seed=7), "seeded")
        self.assertNotEqual(pairs, B.plan_pairs(rows, quotas, seed=8))

    def test_one_project_is_reported_as_a_plan_that_cannot_meet_the_rule(self):
        pairs = B.plan_pairs({"p1": _project_rows("p1")}, {k: 10 for k in B.KINDS})
        out = "\n".join(B.plan_report(pairs, {k: 10 for k in B.KINDS}, 0.02))
        self.assertIn("PLAN CANNOT MEET: negative candidates come from 1 project(s), need 2", out)
        self.assertIn("fewer than the 149 the ceiling needs", out)

    def test_plan_needs_a_ceiling(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            B.parse_args(["plan"])
        self.assertEqual(B.parse_args(["plan", "--fp-ceiling", "0.01"]).seed, 1109)


def _jpeg(color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), color).save(buf, "JPEG")
    return buf.getvalue()


class _NoDb:
    def __getattr__(self, name):
        raise AssertionError(f"the contact sheet touched the database: db.{name}")

    def __getitem__(self, name):
        raise AssertionError(f"the contact sheet touched the database: db[{name!r}]")


class TheContactSheet(unittest.TestCase):

    ROW = {**{f: "" for f in B.FIELDS}, "pair_id": "r2/x.jpg|r2/y.jpg", "key_a": "r2/x.jpg", "key_b": "r2/y.jpg",
           "where_a": "Apt 3B Mr Rosenberg", "sub_a": "Quality Plumbing", "shows_a": "call 917-555-0142",
           "project_id": "proj-secret-name"}

    def test_ids_only_and_the_photos_inline(self):
        fetched = []

        def fetch(key):
            fetched.append(key)
            return _jpeg()
        page = B.build_sheet([self.ROW, {**self.ROW, "pair_id": "inline:L:0:1|r2/z.jpg", "key_a": "inline:L:0:1", "key_b": "r2/z.jpg"}],
                             fetch, side=120)
        self.assertEqual(fetched, ["r2/x.jpg", "r2/y.jpg", "r2/z.jpg"], "an inline photo is not in R2 and is not read")
        self.assertEqual(page.count("data:image/jpeg;base64,"), 3)
        self.assertIn(S.sheet_id(self.ROW["pair_id"]), page)
        self.assertIn("not in R2", page)
        for secret in ("Rosenberg", "Quality Plumbing", "917-555-0142", "proj-secret-name", "r2/x.jpg"):
            self.assertNotIn(secret, page)

    def test_a_thumbnail_is_small(self):
        import base64 as b64
        from PIL import Image
        uri = B.thumbnail(_jpeg(), side=100)
        with Image.open(io.BytesIO(b64.b64decode(uri.split(",", 1)[1]))) as im:
            self.assertLessEqual(max(im.size), 100)
        self.assertIsNone(B.thumbnail(b"not an image"))
        self.assertIsNone(B.thumbnail(None))

    def test_it_reads_r2_and_never_the_database(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, out = str(Path(tmp.name) / "p.csv"), str(Path(tmp.name) / "s.html")
        B.write_pairs([dict(self.ROW, label_a="same", label_b="different"), dict(self.ROW, pair_id="q", label_a="same", label_b="same")], src)
        keys = []

        def r2_fetch(key):
            keys.append(key)
            return _jpeg(), None
        with patch.object(server, "db", _NoDb()), patch.object(server, "_r2_fetch", r2_fetch), redirect_stdout(io.StringIO()):
            rc = B.run_sheet(src, out, side=80, disputed=True)
        self.assertEqual((rc, keys), (0, ["r2/x.jpg", "r2/y.jpg"]), "--disputed: only the pair the two disagree on")
        self.assertIn(S.sheet_id(self.ROW["pair_id"]), Path(out).read_text(encoding="utf-8"))


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

    def test_the_plan_reads_every_live_project_and_writes_nothing(self):
        live = [str(p["_id"]) for p in self.db.projects.rows if not p.get("is_deleted")][:2]
        self.assertEqual(len(live), 2, "the fixture has two live projects")
        for pid in live:
            self.db[server.PHOTO_INDEX].rows += [{**r, "_id": f"v1:{r['photo_key']}"} for r in _project_rows(pid, n=40)]
        self.db[server.PHOTO_INDEX].rows += [{**r, "_id": f"v1:{r['photo_key']}"} for r in _project_rows("gone", n=40)]
        before = copy.deepcopy({n: c.rows for n, c in self.db._c.items()})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = str(Path(tmp.name) / "plan.csv")
        with _Ctx(db=self.db), redirect_stdout(io.StringIO()) as printed:
            rc = _run(B.run_plan(out, ceiling=0.05, expect_errors=0, overdraw=1.0, same_share=0.5, seed=3))
        self.assertEqual(rc, 0, printed.getvalue())
        # A read of a collection the fixture never filled makes it, empty.
        self.assertEqual({n: c.rows for n, c in self.db._c.items() if n in before or c.rows}, before)
        with open(out, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(rows)
        self.assertEqual({r["project_id"] for r in rows}, set(live), "every live project, and no deleted one")
        self.assertEqual({r[c] for r in rows for c in B.LABEL_COLUMNS}, {""})
        self.assertIn("over 2 live project(s)", printed.getvalue())

    def test_the_unmetered_path_exists_only_on_the_compare_call(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        body = src[src.index("async def _photo_compare_call("):src.index("async def _photo_log_bytes(")]
        self.assertIn("if meter:\n        await record_vision_call(", body)
        self.assertEqual(src.count("meter=False"), 0, "only the benchmark, in its own file")


if __name__ == "__main__":
    unittest.main()
