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


def backtest(logs: Iterable[Dict[str, Any]], *, project_id: str = "p", top: int = TOP,
             structural_system: Optional[str] = None) -> Dict[str, Any]:
    """{"overall": {...}, "by_trade": {trade: {...}}, "rows": [...]}. Each stat is
    {"crew_days", "actual", "baseline_hits", "personalized_hits"}."""
    logs = [lg for lg in logs if isinstance(lg, dict) and str(lg.get("date") or "")[:10]]
    logs.sort(key=lambda lg: str(lg["date"])[:10])
    graph = build_sequence_rules_v1()
    succ = successors_by_id(graph)
    labels = {n.id: getattr(n, "scope", n.id) for n in list(graph.nodes) + list(NEW_NODES)}
    known = {n.id for n in graph.nodes} | {n.id for n in NEW_NODES}
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"crew_days": 0, "actual": 0,
                                                            "baseline_hits": 0, "personalized_hits": 0})
    rows: List[Dict[str, Any]] = []
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
            b, p = set(_first(base.chips, top)), set(_first(pers.chips, top))
            hits_b = sum(1 for a in slot["actual"] if a in b)
            hits_p = sum(1 for a in slot["actual"] if a in p)
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
    return {"overall": overall, "by_trade": dict(stats), "rows": rows, "top": top}


def rate(hits: int, actual: int) -> str:
    return f"{100.0 * hits / actual:.0f}%" if actual else "n/a"
