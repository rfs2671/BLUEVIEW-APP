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
             structural_system: Optional[str] = None) -> Dict[str, Any]:
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
            for a in slot["actual"]:
                events.append({"date": day, "trade": str(trade), "activity": a, "label": labels.get(a, a),
                               "kind": "continuing" if a in prev_crew else "new", "had_history": bool(days),
                               "baseline_pos": rb.get(a), "personalized_pos": rp.get(a),
                               "no_order_pos": rn.get(a),
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
    for name in ("baseline_pos", "personalized_pos", "no_order_pos"):
        for n in cuts:
            out[f"{name}@{n}"] = sum(1 for e in ev if e[name] is not None and e[name] < n)
    return out


def rate(hits: int, actual: int) -> str:
    return f"{100.0 * hits / actual:.0f}%" if actual else "n/a"
