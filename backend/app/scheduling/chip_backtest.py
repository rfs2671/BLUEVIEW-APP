"""Replay filed daily logs to measure the activity-chip ranking. Pure.

For every day a crew logged activities, ask what each ranking would have put in
the first `top` chips knowing ONLY the days before it, and whether the activities
the crew really logged were among them. Two rankings are compared:

  baseline      rank_activities as the endpoint called it before: the project's
                single latest previous day, narrowed to the crew's trade
  personalized  the same, then re-ranked by the crew's own earlier days
                (crew_history.personalize)

HIT RATE = actual activities found in the first `top` chips / actual activities.
Only activities the rule table knows count (a free-text "Other" cannot be ranked).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from app.scheduling.crew_history import crew_days, personalize
from app.scheduling.sequence_ranking import rank_activities
from app.scheduling.sequence_rules_v1 import build_sequence_rules_v1, successors_by_id
from app.scheduling.trade_taxonomy_v1 import NEW_NODES, trades_for_roster

TOP = 4


def _ids(row: Dict[str, Any]) -> List[str]:
    out = [i for i in (row.get("activity_ids") or []) if isinstance(i, str)]
    legacy = row.get("activity_chip_id")
    if isinstance(legacy, str) and legacy and legacy not in out:
        out.append(legacy)
    return out


def _first(chips, top: int) -> List[str]:
    return [c.id for c in chips if c.band != "other"][:top]


def _ranks(chips) -> Dict[str, int]:
    return {c.id: n for n, c in enumerate(c for c in chips if c.band != "other")}


def backtest(logs: Iterable[Dict[str, Any]], *, project_id: str = "p", top: int = TOP,
             structural_system: Optional[str] = None, other_projects: Iterable[Iterable[Dict[str, Any]]] = ()) -> Dict[str, Any]:
    """{"overall", "by_trade", "rows", "events", "top"}. `overall` / `by_trade`
    stats are {"crew_days", "actual", "baseline_hits", "personalized_hits"} at
    `top`; `events` has one entry per ACTIVITY the crew really logged: its
    trade, whether the crew had logged it on its previous day ("continuing") or
    not ("new"), and its position (0-based, None if absent) in the baseline, the
    personalized and the personalized-without-usual-order rankings."""
    logs = [lg for lg in logs if isinstance(lg, dict) and str(lg.get("date") or "")[:10]]
    logs.sort(key=lambda lg: str(lg["date"])[:10])
    graph = build_sequence_rules_v1()
    succ = successors_by_id(graph)
    labels = {n.id: getattr(n, "scope", n.id) for n in list(graph.nodes) + list(NEW_NODES)}
    known = {n.id for n in graph.nodes} | {n.id for n in NEW_NODES}
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"crew_days": 0, "actual": 0,
                                                            "baseline_hits": 0, "personalized_hits": 0})
    rows: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    # what other projects' filed logs say comes next (never this project's own
    # future), then this project's own earlier days as they accumulate
    others = Transitions()
    for other in other_projects:
        others.learn(other, known)
    for lg in logs:
        day = str(lg["date"])[:10]
        data = lg.get("data") if isinstance(lg.get("data"), dict) else {}
        by_trade: Dict[str, Dict[str, Any]] = {}
        for row in data.get("activities") or []:
            if not isinstance(row, dict):
                continue
            trades = trades_for_roster(row.get("trade"))
            actual = [i for i in _ids(row) if i in known]
            if not trades or not actual:
                continue
            slot = by_trade.setdefault(row.get("trade"), {"actual": [], "trades": trades})
            slot["actual"] += [i for i in actual if i not in slot["actual"]]
        before = [x for x in logs if str(x["date"])[:10] < day]
        model = Transitions()
        model.merge(others)
        model.learn(before, known)         # this project's own EARLIER days only
        prior_ids: List[str] = []
        if before:
            for row in (before[-1].get("data") or {}).get("activities") or []:
                if isinstance(row, dict):
                    prior_ids += [i for i in _ids(row) if i not in prior_ids]
        for trade, slot in by_trade.items():
            wanted = set(slot["trades"])
            days = crew_days(before, lambda r, w=wanted: bool(w & set(trades_for_roster(r.get("trade")))), day)
            base = rank_activities(project_id=project_id, prior_activity_ids=prior_ids,
                                   structural_system=structural_system, trade=trade)
            pers = personalize(base, days, succ, labels) if days else base
            noord = personalize(base, days, succ, labels, use_order=False) if days else base
            b, p = set(_first(base.chips, top)), set(_first(pers.chips, top))
            hits_b = sum(1 for a in slot["actual"] if a in b)
            hits_p = sum(1 for a in slot["actual"] if a in p)
            rb, rp, rn = _ranks(base.chips), _ranks(pers.chips), _ranks(noord.chips)
            prev_crew = set(days[0][1]) if days else set()
            tk = _trade_key(trade)
            learned_all = with_learned(base, prev_crew, tk, model, labels, keep_first=0)
            learned_keep = with_learned(base, prev_crew, tk, model, labels, keep_first=2)
            rl, rk = _ranks(learned_all.chips), _ranks(learned_keep.chips)
            for a in slot["actual"]:
                events.append({"date": day, "trade": str(trade), "activity": a, "label": labels.get(a, a),
                               "kind": "continuing" if a in prev_crew else "new", "had_history": bool(days),
                               "baseline_pos": rb.get(a), "personalized_pos": rp.get(a),
                               "no_order_pos": rn.get(a), "learned_pos": rl.get(a), "learned_keep2_pos": rk.get(a),
                               "previous": [labels.get(x, x) for x in sorted(prev_crew)]})
            key = str(trade)
            for bucket in (stats[key], stats["ALL"]):
                bucket["crew_days"] += 1
                bucket["actual"] += len(slot["actual"])
                bucket["baseline_hits"] += hits_b
                bucket["personalized_hits"] += hits_p
            rows.append({"date": day, "trade": key, "had_history": bool(days), "actual": slot["actual"],
                         "baseline_top": _first(base.chips, top), "personalized_top": _first(pers.chips, top),
                         "baseline_hits": hits_b, "personalized_hits": hits_p})
    overall = stats.pop("ALL", {"crew_days": 0, "actual": 0, "baseline_hits": 0, "personalized_hits": 0})
    return {"overall": overall, "by_trade": dict(stats), "rows": rows, "events": events, "top": top}



def hit_rates(events: List[Dict[str, Any]], kind: Optional[str] = None, cuts=(4, 6, 8)) -> Dict[str, Any]:
    """Of the activities really logged (optionally only "continuing" or "new"),
    the share found within the first N chips, for each ranking."""
    ev = [e for e in events if kind in (None, e["kind"])]
    out: Dict[str, Any] = {"n": len(ev)}
    for name in ("baseline_pos", "personalized_pos", "no_order_pos", "learned_pos", "learned_keep2_pos"):
        for n in cuts:
            out[f"{name}@{n}"] = sum(1 for e in ev if e[name] is not None and e[name] < n)
    return out


def rate(hits: int, actual: int) -> str:
    return f"{100.0 * hits / actual:.0f}%" if actual else "n/a"


# ── LEARNING WHAT COMES NEXT FROM FILED LOGS ─────────────────────────────────
#
# A crew's own days cannot predict an activity it has never logged on this job
# (the first backtest on a real project: 48% of NEW activities in the first four
# chips, with or without the crew's history). Other projects' filed logs can:
# "after a crew's day of A, which activities did crews start the next day?".

def _trade_key(trade: Any) -> str:
    return "|".join(sorted(trades_for_roster(trade)))


def _crew_day_ids(logs: Iterable[Dict[str, Any]], known: set) -> Dict[str, List[tuple]]:
    """{trade key: [(date, [known activity ids])]} oldest first, one entry per
    worked day of a trade on one project's logs."""
    out: Dict[str, Dict[str, List[str]]] = defaultdict(dict)
    for lg in logs:
        day = str(lg.get("date") or "")[:10]
        data = lg.get("data") if isinstance(lg.get("data"), dict) else {}
        for row in data.get("activities") or []:
            if not isinstance(row, dict):
                continue
            tk = _trade_key(row.get("trade"))
            ids = [i for i in _ids(row) if i in known]
            if tk and day and ids:
                bucket = out[tk].setdefault(day, [])
                bucket += [i for i in ids if i not in bucket]
    return {tk: sorted(days.items()) for tk, days in out.items()}


class Transitions:
    """Counts of "after a day with A, the crew's next worked day added B" per
    trade, learned from filed daily logs. Counts only: no company, project,
    person or date is kept, so what it holds cannot identify anyone."""

    def __init__(self) -> None:
        self.after: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.total: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add_days(self, tk: str, days: List[tuple]) -> None:
        for (_, prev), (_, cur) in zip(days, days[1:]):
            added = [b for b in cur if b not in prev]
            for a in prev:
                self.total[tk][a] += 1
                for b in added:
                    self.after[tk][a][b] += 1

    def merge(self, other: "Transitions") -> None:
        for tk, by_a in other.after.items():
            for a, by_b in by_a.items():
                for b, n in by_b.items():
                    self.after[tk][a][b] += n
        for tk, by_a in other.total.items():
            for a, n in by_a.items():
                self.total[tk][a] += n

    def learn(self, logs: Iterable[Dict[str, Any]], known: set) -> None:
        for tk, days in _crew_day_ids(list(logs), known).items():
            self.add_days(tk, days)

    def scores(self, tk: str, previous: Iterable[str]) -> Dict[str, float]:
        """P(b is added | previous day had a), averaged over the previous day's
        activities, for every activity b NOT already in the previous day."""
        prev = [a for a in previous]
        out: Dict[str, float] = defaultdict(float)
        for a in prev:
            tot = self.total[tk].get(a, 0)
            if not tot:
                continue
            for b, n in self.after[tk][a].items():
                if b not in prev:
                    out[b] += n / tot
        return {b: v / max(len(prev), 1) for b, v in out.items()}


def with_learned(ranking, previous: Iterable[str], tk: str, model: "Transitions", labels: Dict[str, str],
                 keep_first: int = 0, lift: int = 4):
    """`ranking` with the most likely NEW activities (by `model`) moved to the
    front of the suggested band, after the first `keep_first` chips. Same chips,
    Other last, nothing selected; unchanged when the model knows nothing."""
    scores = model.scores(tk, previous)
    by_id = {c.id: c for c in ranking.chips}
    cands = sorted((b for b in scores if b in by_id and by_id[b].band != "other"), key=lambda b: (-scores[b], by_id[b].rank))[:lift]
    if not cands:
        return ranking
    chips = list(ranking.chips)
    head = [c for c in chips if c.id not in cands][:keep_first]
    rest = [c for c in chips if c.id not in cands and c not in head]
    top = [by_id[b].model_copy(update={"band": "suggested"}) for b in cands]
    order = head + top + rest
    return ranking.model_copy(update={"chips": [c.model_copy(update={"rank": n}) for n, c in enumerate(order)]})
