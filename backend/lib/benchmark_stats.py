"""How sure a same-place benchmark can be, from how many labeled pairs.

THE OWNER'S RULING. Thirty labeled "different" pairs cannot show a 2%
false-positive ceiling: with 0 false positives in 30, the exact one-sided 95%
upper bound is 9.5%. So every rate here comes with its interval, the number of
labeled negatives a ceiling needs is computed, not guessed, and the verdict
"would enable" needs ALL of:

    the one-sided 95% upper bound of the false-positive rate UNDER the ceiling
    at least `required_negatives(ceiling, observed false positives)` labeled negatives
    negatives from at least MIN_PROJECTS projects
    same-place pairs in at least MIN_STAGE_GAPS construction-stage-gap strata
    hard negatives (one unit line on two floors, similar rooms on one floor)
        at least HARD_SHARE of the negatives
    at least MIN_SAME same-place pairs, so the miss rate is measured at all

Anything short of that prints what is missing. A pair counts only when TWO
people labeled it independently and agreed (or a person resolved the
disagreement in `label_resolved`); a disagreement is excluded until resolved.

A signal that does not say "same" leaves a pair UNCONFIRMED, never "different":
a miss is not an error of the dangerous kind, only a photo left without extra
support.

Exact (Clopper-Pearson) intervals come from the beta quantile, found by
bisection on the regularized incomplete beta (a continued fraction, Numerical
Recipes 6.4). scipy is not a dependency. Wilson intervals use the stdlib normal
quantile.

Pure: no database, no network.
"""

from __future__ import annotations

import hashlib
import math
from statistics import NormalDist
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

CONFIDENCE = 0.95
MIN_PROJECTS = 2
MIN_STAGE_GAPS = 3
#: Hard negatives must be at least this share of the negatives: hard * 3 >= all.
HARD_SHARE_NUM, HARD_SHARE_DEN = 1, 3
MIN_SAME = 30
HARD_KINDS = ("same_line_other_floor", "similar_room_same_floor")
SAME, DIFFERENT, UNSURE = "same", "different", "unsure"
LABELS = (SAME, DIFFERENT)
ANSWERS = (SAME, DIFFERENT, UNSURE)

_TINY = 1e-300
_EPS = 1e-15


class BadLabel(ValueError):
    """A label that is neither a person's answer nor blank: a typo must not be
    silently left out of the count."""


# ── THE BETA DISTRIBUTION ──────────────────────────────────────────────────

def _betacf(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta, by modified Lentz."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta I_x(a, b), a > 0, b > 0, 0 <= x <= 1."""
    if a <= 0 or b <= 0:
        raise ValueError("a and b must be positive")
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(p: float, a: float, b: float) -> float:
    """The p-quantile of Beta(a, b): bisection, since I_x is increasing in x."""
    if not 0 <= p <= 1:
        raise ValueError("p must be in [0, 1]")
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return (lo + hi) / 2


# ── INTERVALS FOR A RATE ───────────────────────────────────────────────────

def _check(k: int, n: int, confidence: float) -> None:
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k}, n={n}")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")


def clopper_pearson(k: int, n: int, confidence: float = CONFIDENCE) -> Tuple[float, float]:
    """The exact two-sided interval for k events in n trials."""
    _check(k, n, confidence)
    alpha = 1 - confidence
    lo = 0.0 if k == 0 else beta_ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta_ppf(1 - alpha / 2, k + 1, n - k)
    return lo, hi


def upper_bound(k: int, n: int, confidence: float = CONFIDENCE) -> float:
    """The exact ONE-sided upper bound: the rate is under this with `confidence`."""
    _check(k, n, confidence)
    return 1.0 if k == n else beta_ppf(confidence, k + 1, n - k)


def wilson(k: int, n: int, confidence: float = CONFIDENCE) -> Tuple[float, float]:
    """The Wilson score two-sided interval."""
    _check(k, n, confidence)
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    z2 = z * z
    centre = (k + z2 / 2) / (n + z2)
    half = z / (n + z2) * math.sqrt(k * (n - k) / n + z2 / 4)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int, confidence: float = CONFIDENCE) -> Dict[str, Any]:
    """k events in n, the observed rate and its intervals. n == 0: no rate."""
    if n == 0:
        return {"k": k, "n": 0, "rate": None, "exact": None, "wilson": None, "upper": None}
    return {"k": k, "n": n, "rate": k / n, "exact": clopper_pearson(k, n, confidence),
            "wilson": wilson(k, n, confidence), "upper": upper_bound(k, n, confidence)}


def fmt(r: Dict[str, Any]) -> str:
    if not r["n"]:
        return f"{r['k']}/0 (no labeled pairs: no rate)"
    (el, eh), (wl, wh) = r["exact"], r["wilson"]
    return (f"{r['k']}/{r['n']} = {r['rate']:.3f}, 95% exact {el:.4f}-{eh:.4f}, Wilson {wl:.4f}-{wh:.4f}, "
            f"one-sided upper {r['upper']:.4f}")


def required_negatives(ceiling: float, errors: int = 0, confidence: float = CONFIDENCE) -> int:
    """The fewest labeled negatives n such that `errors` false positives in n
    give a one-sided upper bound UNDER `ceiling`. The bound falls as n grows, so
    an exponential search then bisection finds the first n."""
    if not 0 < ceiling < 1:
        raise ValueError("the ceiling is a rate in (0, 1)")
    if errors < 0:
        raise ValueError("errors must be >= 0")
    lo = errors + 1                       # the bound at lo may or may not pass
    if upper_bound(errors, lo, confidence) < ceiling:
        return lo
    hi = lo * 2
    while upper_bound(errors, hi, confidence) >= ceiling:
        lo, hi = hi, hi * 2
    while hi - lo > 1:                    # bound(lo) >= ceiling > bound(hi)
        mid = (lo + hi) // 2
        if upper_bound(errors, mid, confidence) < ceiling:
            hi = mid
        else:
            lo = mid
    return hi


# ── TWO LABELERS ───────────────────────────────────────────────────────────

def _norm(v: Any, column: str, line: int) -> str:
    s = str(v or "").strip().lower()
    if s and s not in ANSWERS:
        raise BadLabel(f"line {line}: {column} {v!r} is not same, different, unsure or blank")
    return s


def resolve(label_a: Any, label_b: Any, resolved: Any = "", line: int = 0) -> Tuple[str, str]:
    """(status, label). status is one of:

        scored      two people agreed on same/different, or a person resolved a
                    disagreement to one of them: `label` is it
        blank       nobody labeled it
        one_label   only one person did: not independent, not scored
        unsure      the answer, agreed or resolved, is unsure: not scored
        disputed    the two disagree and nobody has resolved it: not scored
    """
    a, b = _norm(label_a, "label_a", line), _norm(label_b, "label_b", line)
    r = _norm(resolved, "label_resolved", line)
    if not a and not b:
        if r:
            raise BadLabel(f"line {line}: label_resolved {resolved!r} on a pair nobody labeled")
        return "blank", ""
    if not a or not b:
        if r:
            raise BadLabel(f"line {line}: label_resolved {resolved!r} with only one label: it needs two to resolve")
        return "one_label", ""
    if a == b:
        if r and r != a:
            raise BadLabel(f"line {line}: label_resolved {resolved!r} contradicts two labels that agree ({a!r})")
        return ("scored", a) if a in LABELS else ("unsure", "")
    if not r:
        return "disputed", ""
    return ("scored", r) if r in LABELS else ("unsure", "")


def cohen_kappa(pairs: Iterable[Tuple[str, str]]) -> Dict[str, Any]:
    """Agreement of two labelers over the pairs BOTH labeled. kappa is None
    when chance agreement is total (both used one answer only)."""
    pairs = [(a, b) for a, b in pairs if a and b]
    n = len(pairs)
    if not n:
        return {"n": 0, "agreed": 0, "observed": None, "chance": None, "kappa": None}
    agreed = sum(1 for a, b in pairs if a == b)
    cats = sorted({x for p in pairs for x in p})
    chance = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in cats)
    observed = agreed / n
    kappa = None if chance >= 1 else (observed - chance) / (1 - chance)
    return {"n": n, "agreed": agreed, "observed": observed, "chance": chance, "kappa": kappa}


# ── ERRORS, BY STRATUM ─────────────────────────────────────────────────────

def is_same(row: Dict[str, Any]) -> bool:
    return row["label"] == SAME


def errors(rows: Sequence[Dict[str, Any]], says_same: Callable[[Dict[str, Any]], bool],
           confidence: float = CONFIDENCE) -> Dict[str, Any]:
    """The two errors, apart, each with its intervals. A row the signal does
    not call same is UNCONFIRMED by it, not called different."""
    same = [r for r in rows if is_same(r)]
    other = [r for r in rows if not is_same(r)]
    fp = sum(1 for r in other if says_same(r))
    missed = sum(1 for r in same if not says_same(r))
    return {"fp": rate(fp, len(other), confidence), "miss": rate(missed, len(same), confidence)}


def stage_gap(row: Dict[str, Any]) -> str:
    """0 is a gap (the same stage), not a missing one."""
    v = row.get("stage_gap")
    return "unknown" if v is None or v == "" else str(v)


def project(row: Dict[str, Any]) -> str:
    return str(row.get("project_id") or "") or "unknown"


def negative_kind(row: Dict[str, Any]) -> str:
    """hard: one unit line on two floors, or similar rooms on one floor."""
    return "hard" if row.get("candidate_kind") in HARD_KINDS else "easy"


STRATA: Tuple[Tuple[str, Callable[[Dict[str, Any]], str]], ...] = (
    ("construction-stage gap", stage_gap), ("project", project), ("negative kind", negative_kind))


def by_stratum(rows: Sequence[Dict[str, Any]], says_same: Callable[[Dict[str, Any]], bool],
               key: Callable[[Dict[str, Any]], str]) -> List[Tuple[str, Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return [(g, errors(groups[g], says_same)) for g in sorted(groups)]


# ── WHAT A VERDICT NEEDS ───────────────────────────────────────────────────

def coverage(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """What the labeled sample spans, independent of any signal."""
    neg = [r for r in rows if not is_same(r)]
    pos = [r for r in rows if is_same(r)]
    return {"negatives": len(neg), "same": len(pos),
            "projects": sorted({project(r) for r in neg} - {"unknown"}),
            "stage_gaps": sorted({stage_gap(r) for r in pos} - {"unknown"}),
            "hard": sum(1 for r in neg if negative_kind(r) == "hard")}


def missing(rows: Sequence[Dict[str, Any]], fp: Dict[str, Any], ceiling: float,
            confidence: float = CONFIDENCE, miss: Optional[Dict[str, Any]] = None) -> List[str]:
    """Everything that stands between this sample and "would enable" at a
    setting whose false positives are `fp` and misses `miss` (`rate` dicts).
    Empty: nothing. A setting that confirms no same-place pair at all keeps its
    false positives at 0 by saying nothing, and is refused for it."""
    c = coverage(rows)
    out = []
    if miss is not None and miss["n"] and miss["k"] == miss["n"]:
        out.append(f"the setting confirms none of the {miss['n']} same-place pairs: nothing to enable")
    need = required_negatives(ceiling, fp["k"], confidence)
    if fp["upper"] is None or fp["upper"] >= ceiling:
        bound = "none (no labeled negatives)" if fp["upper"] is None else f"{fp['upper']:.4f}"
        out.append(f"one-sided {confidence:.0%} upper bound of the false-positive rate is {bound}, "
                   f"not under the ceiling {ceiling}")
    if c["negatives"] < need:
        out.append(f"independently labeled negatives: have {c['negatives']}, need {need} "
                   f"(at {fp['k']} false positive(s) observed); {need - c['negatives']} more")
    if len(c["projects"]) < MIN_PROJECTS:
        out.append(f"projects among the negatives: have {len(c['projects'])}, need {MIN_PROJECTS}")
    if len(c["stage_gaps"]) < MIN_STAGE_GAPS:
        have = ", ".join(c["stage_gaps"]) or "none"
        out.append(f"construction-stage-gap strata among the same-place pairs: have {len(c['stage_gaps'])} ({have}), "
                   f"need {MIN_STAGE_GAPS}")
    if c["hard"] * HARD_SHARE_DEN < c["negatives"] * HARD_SHARE_NUM or not c["negatives"]:
        want = -(-c["negatives"] * HARD_SHARE_NUM // HARD_SHARE_DEN) if c["negatives"] else 1
        out.append(f"hard negatives: have {c['hard']} of {c['negatives']}, need at least "
                   f"{HARD_SHARE_NUM}/{HARD_SHARE_DEN} ({want})")
    if c["same"] < MIN_SAME:
        out.append(f"same-place pairs: have {c['same']}, need {MIN_SAME} so the miss rate is measured at all")
    return out


# ── A PLAN: HOW MANY TO DRAW, FROM WHERE ───────────────────────────────────

def allocate(capacity: Dict[Any, int], total: int) -> Dict[Any, int]:
    """`total` spread as evenly as possible over the strata, none past its
    capacity; what a small stratum cannot take goes to the others. Deterministic:
    strata are visited in the order of their names."""
    alloc = {k: 0 for k in capacity}
    left = max(0, int(total))
    while left > 0:
        open_ = [k for k in sorted(capacity, key=str) if alloc[k] < capacity[k]]
        if not open_:
            break
        share = max(1, left // len(open_))
        for k in open_:
            give = min(share, capacity[k] - alloc[k], left)
            alloc[k] += give
            left -= give
            if not left:
                break
    return alloc


NEGATIVE_KINDS = ("different_level",) + HARD_KINDS
SAME_KINDS = ("same_crew_day", "same_level_across_stages")


def plan_shortfalls(pairs: Sequence[Dict[str, Any]], ceiling: float, confidence: float = CONFIDENCE) -> List[str]:
    """What a drawn plan cannot supply even if every candidate is labeled as
    its kind suggests. (A suggestion is not a label: the real sample is
    measured again by `missing` once two people have labeled it.)"""
    neg = [p for p in pairs if kind(p) in NEGATIVE_KINDS]
    pos = [p for p in pairs if kind(p) in SAME_KINDS]
    out = []
    need = required_negatives(ceiling, 0, confidence)
    if len(neg) < need:
        out.append(f"negative candidates {len(neg)}, fewer than the {need} the ceiling needs at 0 false positives")
    projects = {project(p) for p in neg} - {"unknown"}
    if len(projects) < MIN_PROJECTS:
        out.append(f"negative candidates come from {len(projects)} project(s), need {MIN_PROJECTS}")
    gaps = {stage_gap(p) for p in pos} - {"unknown"}
    if len(gaps) < MIN_STAGE_GAPS:
        out.append(f"same-place candidates span {len(gaps)} stage gap(s) ({', '.join(sorted(gaps)) or 'none'}), "
                   f"need {MIN_STAGE_GAPS}")
    hard = sum(1 for p in neg if negative_kind(p) == "hard")
    if not neg or hard * HARD_SHARE_DEN < len(neg) * HARD_SHARE_NUM:
        out.append(f"hard negative candidates {hard} of {len(neg)}, need at least {HARD_SHARE_NUM}/{HARD_SHARE_DEN}")
    return out


def kind(row: Dict[str, Any]) -> str:
    return str(row.get("candidate_kind") or "")


def tally(rows: Iterable[Any], key: Callable[[Any], Any]) -> Dict[Any, int]:
    """How many rows per value of `key`."""
    out: Dict[Any, int] = {}
    for r in rows:
        k = key(r)
        out[k] = out.get(k, 0) + 1
    return out


def sheet_id(pair_id: str) -> str:
    """A short, stable id for a pair: what a labeler sees, instead of a name."""
    return hashlib.sha1(str(pair_id).encode("utf-8")).hexdigest()[:10]
