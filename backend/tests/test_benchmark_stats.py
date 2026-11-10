"""THE STATISTICS A SAME-PLACE VERDICT RESTS ON.

The owner's ruling: 30 negatives cannot validate a 2% false-positive ceiling.
So the intervals must be right (checked against closed forms, the binomial
identity they are defined by, and Newcombe's published table), the required
sample size must be the exact first n (checked against a brute-force scan), and
the verdict must refuse on EACH missing requirement alone.
"""

from __future__ import annotations

import math
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import benchmark_stats as S  # noqa: E402


def _binom_cdf(k, n, p):
    """P(X <= k), X ~ Binomial(n, p), summed exactly."""
    p = Fraction(p)
    return float(sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k + 1)))


class TheIncompleteBeta(unittest.TestCase):

    def test_closed_forms(self):
        # Beta(2, 3) at 0.4 is P(Binomial(4, 0.4) >= 2) = 0.5248.
        self.assertAlmostEqual(S.betainc(2, 3, 0.4), 0.5248, places=12)
        # Beta(1/2, 1/2) is the arcsine law.
        for x in (0.01, 0.3, 0.5, 0.77, 0.999):
            self.assertAlmostEqual(S.betainc(0.5, 0.5, x), 2 / math.pi * math.asin(math.sqrt(x)), places=10)
        # Beta(a, 1) is x ** a; Beta(1, b) is 1 - (1 - x) ** b.
        for a in (1, 2.5, 40, 300):
            self.assertAlmostEqual(S.betainc(a, 1, 0.97), 0.97 ** a, places=12)
            self.assertAlmostEqual(S.betainc(1, a, 0.03), 1 - 0.97 ** a, places=12)

    def test_the_binomial_identity_on_both_branches(self):
        """I_x(k, n - k + 1) = P(Binomial(n, x) >= k): each x below and above
        the continued fraction's switch point (a + 1) / (a + b + 2)."""
        for n in (1, 7, 30, 150, 400):
            for k in sorted({1, n // 3 or 1, n}):
                for x in (0.001, 0.02, 0.2, 0.5, 0.8, 0.999):
                    with self.subTest(n=n, k=k, x=x):
                        self.assertAlmostEqual(S.betainc(k, n - k + 1, x), 1 - _binom_cdf(k - 1, n, x), places=10)

    def test_the_ends_and_bad_arguments(self):
        self.assertEqual((S.betainc(3, 4, 0), S.betainc(3, 4, 1)), (0.0, 1.0))
        for a, b in ((0, 1), (1, -1)):
            with self.assertRaises(ValueError):
                S.betainc(a, b, 0.5)

    def test_the_quantile_inverts_it(self):
        for a, b in ((1, 150), (3, 148), (0.5, 0.5), (81, 183), (200, 2)):
            for p in (0.025, 0.05, 0.5, 0.95, 0.975):
                with self.subTest(a=a, b=b, p=p):
                    self.assertAlmostEqual(S.betainc(a, b, S.beta_ppf(p, a, b)), p, places=10)
        with self.assertRaises(ValueError):
            S.beta_ppf(1.5, 1, 1)


class ExactIntervals(unittest.TestCase):

    def test_zero_in_150(self):
        """The owner's numbers: 0/150, two-sided 95% upper ~0.0242, one-sided ~0.0198."""
        lo, hi = S.clopper_pearson(0, 150)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.0242, delta=1e-4)
        self.assertAlmostEqual(S.upper_bound(0, 150), 0.0198, delta=1e-4)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 150), places=12)
        self.assertAlmostEqual(S.upper_bound(0, 150), 1 - 0.05 ** (1 / 150), places=12)

    def test_newcombe_1998_table(self):
        """Newcombe, Statistics in Medicine 17:857 (1998), Table I: exact
        (Clopper-Pearson) and Wilson score 95% intervals, to 4 places."""
        table = {(81, 263): ((0.2527, 0.3676), (0.2553, 0.3662)),
                 (15, 148): ((0.0578, 0.1617), (0.0624, 0.1605)),
                 (0, 20): ((0.0, 0.1684), (0.0, 0.1611)),
                 (1, 29): ((0.0009, 0.1776), (0.0061, 0.1718))}
        for (k, n), (exact, score) in table.items():
            with self.subTest(k=k, n=n):
                for got, want in zip(S.clopper_pearson(k, n) + S.wilson(k, n), exact + score):
                    self.assertAlmostEqual(got, want, delta=1e-4)

    def test_each_bound_is_the_tail_it_is_defined_by(self):
        """The upper bound u: P(X <= k | u) = alpha / 2. The lower l:
        P(X >= k | l) = alpha / 2. One-sided upper: P(X <= k) = alpha."""
        for k, n in ((1, 10), (3, 60), (2, 236), (12, 300), (149, 150)):
            with self.subTest(k=k, n=n):
                lo, hi = S.clopper_pearson(k, n)
                self.assertAlmostEqual(_binom_cdf(k, n, hi), 0.025, places=9)
                self.assertAlmostEqual(1 - _binom_cdf(k - 1, n, lo), 0.025, places=9)
                self.assertAlmostEqual(_binom_cdf(k, n, S.upper_bound(k, n)), 0.05, places=9)

    def test_all_events(self):
        lo, hi = S.clopper_pearson(20, 20)
        self.assertEqual(hi, 1.0)
        self.assertAlmostEqual(lo, 0.025 ** (1 / 20), places=12)
        self.assertEqual(S.upper_bound(5, 5), 1.0)

    def test_another_confidence(self):
        self.assertAlmostEqual(S.upper_bound(0, 100, 0.99), 1 - 0.01 ** (1 / 100), places=12)

    def test_bad_counts(self):
        for k, n in ((0, 0), (5, 4), (-1, 3)):
            with self.subTest(k=k, n=n), self.assertRaises(ValueError):
                S.clopper_pearson(k, n)
        with self.assertRaises(ValueError):
            S.wilson(1, 10, 1.0)


class WilsonIntervals(unittest.TestCase):

    def test_the_score_formula(self):
        z = 1.959963984540054
        for k, n in ((1, 10), (7, 40), (0, 150)):
            p = k / n
            centre = (p + z * z / (2 * n)) / (1 + z * z / n)
            half = z / (1 + z * z / n) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
            lo, hi = S.wilson(k, n)
            self.assertAlmostEqual(lo, max(0, centre - half), places=12)
            self.assertAlmostEqual(hi, centre + half, places=12)

    def test_at_zero_events_the_upper_bound_is_z2_over_n_plus_z2(self):
        z2 = 1.959963984540054 ** 2
        self.assertEqual(S.wilson(0, 150)[0], 0.0)
        self.assertAlmostEqual(S.wilson(0, 150)[1], z2 / (150 + z2), places=12)


class RequiredSampleSize(unittest.TestCase):

    def _scan(self, ceiling, k):
        n = k + 1
        while S.upper_bound(k, n) >= ceiling:
            n += 1
        return n

    def test_the_owners_table(self):
        """Pinned, and below re-derived by a scan that shares nothing with the search."""
        want = {0.01: (299, 473, 628), 0.02: (149, 236, 313), 0.05: (59, 93, 124)}
        for ceiling, row in want.items():
            self.assertEqual(tuple(S.required_negatives(ceiling, k) for k in (0, 1, 2)), row)

    def test_it_is_the_first_n(self):
        for ceiling in (0.01, 0.02, 0.05, 0.1, 0.3):
            for k in (0, 1, 2, 5):
                with self.subTest(ceiling=ceiling, k=k):
                    n = S.required_negatives(ceiling, k)
                    self.assertEqual(n, self._scan(ceiling, k))
                    self.assertLess(S.upper_bound(k, n), ceiling)
                    if n - 1 > k:
                        self.assertGreaterEqual(S.upper_bound(k, n - 1), ceiling)

    def test_zero_errors_has_a_closed_form(self):
        """1 - 0.05 ** (1/n) < c  <=>  n > ln 0.05 / ln(1 - c): the rule of three, exactly."""
        for c in (0.01, 0.02, 0.05):
            self.assertEqual(S.required_negatives(c, 0), math.floor(math.log(0.05) / math.log(1 - c)) + 1)
        self.assertLess(abs(S.required_negatives(0.02, 0) - 3 / 0.02), 2)

    def test_thirty_is_not_enough_for_two_percent(self):
        self.assertGreater(S.upper_bound(0, 30), 0.09)
        self.assertGreater(S.required_negatives(0.02), 30)

    def test_bad_ceilings(self):
        for c in (0, 1, -0.1, 2):
            with self.subTest(c=c), self.assertRaises(ValueError):
                S.required_negatives(c)
        with self.assertRaises(ValueError):
            S.required_negatives(0.02, -1)


class TwoLabelers(unittest.TestCase):

    def test_the_statuses(self):
        cases = {("same", "same", ""): ("scored", "same"), ("Different", " different ", ""): ("scored", "different"),
                 ("", "", ""): ("blank", ""), ("same", "", ""): ("one_label", ""), ("", "different", ""): ("one_label", ""),
                 ("unsure", "unsure", ""): ("unsure", ""), ("same", "different", ""): ("disputed", ""),
                 ("same", "unsure", ""): ("disputed", ""), ("same", "different", "different"): ("scored", "different"),
                 ("same", "different", "unsure"): ("unsure", ""), ("same", "same", "same"): ("scored", "same")}
        for (a, b, r), want in cases.items():
            with self.subTest(a=a, b=b, r=r):
                self.assertEqual(S.resolve(a, b, r), want)

    def test_what_is_refused(self):
        for a, b, r in (("smae", "same", ""), ("same", "same", "differnt"), ("same", "same", "different"),
                        ("same", "", "same"), ("", "", "same")):
            with self.subTest(a=a, b=b, r=r), self.assertRaises(S.BadLabel):
                S.resolve(a, b, r, line=7)

    def test_kappa_on_a_textbook_table(self):
        """20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no: po 0.7, pe 0.5, kappa 0.4."""
        pairs = [("same", "same")] * 20 + [("same", "different")] * 5 + [("different", "same")] * 10 + [("different", "different")] * 15
        k = S.cohen_kappa(pairs)
        self.assertEqual((k["n"], k["agreed"]), (50, 35))
        self.assertAlmostEqual(k["observed"], 0.7)
        self.assertAlmostEqual(k["chance"], 0.5)
        self.assertAlmostEqual(k["kappa"], 0.4)

    def test_kappa_counts_only_pairs_both_labeled_and_can_be_undefined(self):
        self.assertEqual(S.cohen_kappa([("same", ""), ("", "")])["n"], 0)
        self.assertIsNone(S.cohen_kappa([("same", "same")] * 4)["kappa"])
        self.assertAlmostEqual(S.cohen_kappa([("same", "same"), ("different", "different")])["kappa"], 1.0)


def _row(label, said=False, project="p1", gap=1, kind="different_level"):
    return {"label": label, "said": said, "project_id": project, "stage_gap": gap, "candidate_kind": kind}


def _says(r):
    return r["said"]


def _sample(neg=60, hard=20, projects=("p1", "p2"), gaps=(0, 1, 2), same=30, fp=0):
    rows = []
    for i in range(neg):
        kind = "same_line_other_floor" if i < hard else "different_level"
        rows.append(_row("different", said=i < fp, project=projects[i % len(projects)], kind=kind))
    for i in range(same):
        rows.append(_row("same", said=True, project=projects[i % len(projects)], gap=gaps[i % len(gaps)], kind="same_crew_day"))
    return rows


class TheErrors(unittest.TestCase):

    def test_false_positives_and_misses_apart(self):
        rows = [_row("same", True), _row("same", False), _row("different", True), _row("different", False), _row("different", False)]
        e = S.errors(rows, _says)
        self.assertEqual((e["fp"]["k"], e["fp"]["n"], e["miss"]["k"], e["miss"]["n"]), (1, 3, 1, 2))
        self.assertAlmostEqual(e["fp"]["rate"], 1 / 3)
        self.assertEqual(e["fp"]["exact"], S.clopper_pearson(1, 3))

    def test_no_denominator_no_rate(self):
        e = S.errors([_row("different")], _says)
        self.assertIsNone(e["miss"]["rate"])
        self.assertIn("no labeled pairs", S.fmt(e["miss"]))

    def test_strata(self):
        rows = [_row("different", True, project="p1", gap=0), _row("different", False, project="p2", gap="",
                                                                    kind="similar_room_same_floor")]
        by_gap = dict(S.by_stratum(rows, _says, S.stage_gap))
        self.assertEqual(sorted(by_gap), ["0", "unknown"])
        self.assertEqual(by_gap["0"]["fp"]["k"], 1)
        by_kind = dict(S.by_stratum(rows, _says, S.negative_kind))
        self.assertEqual((by_kind["easy"]["fp"]["k"], by_kind["hard"]["fp"]["k"]), (1, 0))
        self.assertEqual(sorted(dict(S.by_stratum(rows, _says, S.project))), ["p1", "p2"])


class EachRequirementAloneRefuses(unittest.TestCase):
    """At a 5% ceiling, 0 in 60 has an upper bound of 0.0487: just enough. The
    sample below meets every requirement; each test takes away ONE."""

    CEILING = 0.05

    def _missing(self, **kw):
        rows = _sample(**kw)
        return S.missing(rows, S.errors(rows, _says)["fp"], self.CEILING)

    def test_a_sample_that_meets_everything(self):
        self.assertEqual(self._missing(), [])

    def test_too_few_negatives(self):
        out = self._missing(neg=58, hard=20)
        self.assertEqual(len(out), 2, out)
        self.assertIn("not under the ceiling 0.05", out[0])
        self.assertIn("negatives: have 58, need 59 (at 0 false positive(s) observed); 1 more", out[1])

    def test_one_false_positive_raises_the_count(self):
        out = self._missing(fp=1)
        self.assertTrue(any("need 93 (at 1 false positive(s)" in m for m in out), out)

    def test_one_project(self):
        self.assertEqual(self._missing(projects=("p1",)), ["projects among the negatives: have 1, need 2"])

    def test_two_stage_gaps(self):
        self.assertEqual(self._missing(gaps=(0, 1)),
                         ["construction-stage-gap strata among the same-place pairs: have 2 (0, 1), need 3"])

    def test_stage_gaps_count_only_among_same_place_pairs(self):
        """Negatives spread over every gap do not make same-place pairs span
        construction stages."""
        rows = _sample(gaps=(0,))
        for i, r in enumerate(x for x in rows if x["label"] == "different"):
            r["stage_gap"] = i % 4
        out = S.missing(rows, S.errors(rows, _says)["fp"], self.CEILING)
        self.assertEqual(out, ["construction-stage-gap strata among the same-place pairs: have 1 (0), need 3"])

    def test_an_unknown_gap_is_not_a_stratum(self):
        self.assertEqual(len(self._missing(gaps=(0, 1, "unknown"))), 1)

    def test_too_few_hard_negatives(self):
        self.assertEqual(self._missing(hard=19), ["hard negatives: have 19 of 60, need at least 1/3 (20)"])

    def test_too_few_same_pairs(self):
        self.assertEqual(self._missing(same=29), ["same-place pairs: have 29, need 30 so the miss rate is measured at all"])

    def test_no_negatives_at_all(self):
        rows = _sample(neg=0, hard=0)
        out = S.missing(rows, S.errors(rows, _says)["fp"], self.CEILING)
        self.assertIn("none (no labeled negatives)", out[0])


class ThePlan(unittest.TestCase):

    def test_allocate_spreads_and_refills(self):
        self.assertEqual(S.allocate({"a": 100, "b": 100}, 10), {"a": 5, "b": 5})
        self.assertEqual(S.allocate({"a": 2, "b": 100, "c": 100}, 30), {"a": 2, "b": 14, "c": 14})
        self.assertEqual(S.allocate({"a": 3, "b": 4}, 100), {"a": 3, "b": 4})
        self.assertEqual(S.allocate({"a": 9, "b": 9, "c": 9}, 2), {"a": 1, "b": 1, "c": 0})
        self.assertEqual(S.allocate({}, 5), {})

    def test_shortfalls(self):
        pairs = [{"candidate_kind": "different_level", "project_id": "p1", "stage_gap": 1}] * 10
        out = S.plan_shortfalls(pairs, 0.05)
        self.assertEqual(len(out), 4, out)
        good = ([{"candidate_kind": "same_line_other_floor", "project_id": p, "stage_gap": 0} for p in ("p1", "p2")] * 10
                + [{"candidate_kind": "different_level", "project_id": "p1", "stage_gap": 0}] * 40
                + [{"candidate_kind": "same_level_across_stages", "project_id": "p1", "stage_gap": g} for g in (0, 1, 2)])
        self.assertEqual(S.plan_shortfalls(good, 0.05), [])

    def test_sheet_id_is_stable_and_short(self):
        self.assertEqual(S.sheet_id("a|b"), S.sheet_id("a|b"))
        self.assertNotEqual(S.sheet_id("a|b"), S.sheet_id("a|c"))
        self.assertEqual(len(S.sheet_id("a|b")), 10)


if __name__ == "__main__":
    unittest.main()
