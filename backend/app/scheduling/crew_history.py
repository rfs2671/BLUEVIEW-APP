"""A crew's own history on this project, used to rank tomorrow's activity chips.

Pure: no DB, no HTTP, no LLM, no I/O. `personalize` is the only entry point
that changes a ranking and it NEVER raises for bad input.

WHY THIS EXISTS. rank_activities keys off the PROJECT's single most recent day
and a fixed rule table: it does not know that THIS plumbing crew has run "MEP
rough-in" for seven days and is about to move to the next activity, that the
framers are on day eleven of "framing", or that a crew was off yesterday and
last worked on Monday. Even the suggested band is in declaration order, not by
relevance. The crew's own filed logs say all of it.

THE GUARANTEES OF rank_activities STILL HOLD, and are enforced here:

  1. RANK ORDER ONLY. A chip is never selected (ActivityChip.selected is
     Literal[False]); nothing is added or removed from the list, only reordered
     and labelled with a `reason`.
  2. "OTHER" STAYS LAST.
  3. NOTHING BLOCKS. Every chip that was offered is still offered.
  4. NO PREDICTION OF PROGRESS. This ranks what is LIKELY TO BE LOGGED, from
     what the crew logged. It says nothing about how much work is complete.

THE RULES, in the order they weigh:
  * CONTINUING: an activity this crew logged on its most recent day on the
    project stays first (work continues across days), most-run-longest first.
  * NEXT: the rule table's successors of what the crew just did, boosted when
    the crew has done the activity as long as its own completed runs on this
    project usually last (the median length of its earlier runs).
  * HABIT: where this crew went after the same activity earlier on this
    project ("moved from A to B before").
  * STAGE: the trade's own sequence (app/scheduling/trade_sequence.py): the crew's
    furthest stage on its last worked day -- however long ago -- gives the rest of
    that stage and the next stage ("after underground plumbing: MEP rough-in").
    A crew that was away a week is ranked from where it left off, not from the
    project's latest day.
  * SCHEDULED: an activity a confirmed schedule has planned for the date and
    whose name matches (the caller passes these; nothing is guessed here).
  * RECENT: anything the crew logged lately, weighted by how recently (each
    earlier worked day counts 0.6 of the one after it).
A crew with no history on the project is ranked exactly as before.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.scheduling.schedule_models import ActivityRanking

__all__ = ["crew_days", "personalize", "runs_of"]

DECAY = 0.6
MAX_DAYS = 12            # worked days considered, newest first
MAX_PERSONAL = 6         # chips lifted into the suggested band
CONTINUING_BONUS = 2.0
NEXT_BONUS = 1.2
RUN_REACHED_BONUS = 0.8  # added to the successors of an activity run as long as usual
HABIT_BONUS = 1.0        # per earlier observation of "from A to B", at most twice
STAGE_NEXT_BONUS = 1.5   # the stage after the crew's furthest stage
STAGE_SAME_BONUS = 0.9   # the rest of the crew's current stage (concurrent work)
SCHEDULED_BONUS = 1.4    # planned for today in a confirmed schedule
_PROMOTABLE_BANDS = ("suggested", "catalog", "remembered_other", "always_available")


def _ids_of(row: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    ids = row.get("activity_ids")
    if isinstance(ids, (list, tuple)):
        out += [i.strip() for i in ids if isinstance(i, str) and i.strip()]
    legacy = row.get("activity_chip_id")
    if isinstance(legacy, str) and legacy.strip() and legacy.strip() not in out:
        out.append(legacy.strip())
    seen: List[str] = []
    for i in out:
        if i not in seen:
            seen.append(i)
    return seen


def crew_days(logs: Iterable[Dict[str, Any]], row_is_crew: Callable[[Dict[str, Any]], bool], before: str,
              limit: int = MAX_DAYS) -> List[Tuple[str, List[str]]]:
    """[(date, activity ids)] for the days BEFORE `before` on which a row of this
    crew logged activities, newest first. `logs` are the project's daily jobsite
    logs; `row_is_crew` says whether an activity row belongs to the crew.
    Tolerant: anything malformed is skipped."""
    by_day: Dict[str, List[str]] = {}
    for lg in logs or []:
        if not isinstance(lg, dict):
            continue
        day = str(lg.get("date") or "")[:10]
        data = lg.get("data")
        rows = data.get("activities") if isinstance(data, dict) else None
        if not day or day >= before or not isinstance(rows, list):
            continue
        for row in rows:
            try:
                ok = isinstance(row, dict) and row_is_crew(row)
            except Exception:
                ok = False
            if not ok:
                continue
            ids = by_day.setdefault(day, [])
            ids += [i for i in _ids_of(row) if i not in ids]
    days = sorted(((d, ids) for d, ids in by_day.items() if ids), key=lambda x: x[0], reverse=True)
    return days[:limit]


def runs_of(days: Sequence[Tuple[str, List[str]]], activity: str) -> Tuple[int, List[int]]:
    """(the CURRENT run length of `activity`, the lengths of its COMPLETED earlier
    runs), over worked days newest first. The current run is the days it has been
    logged on in a row up to the most recent day (0 if it was not logged then)."""
    flags = [activity in ids for _, ids in days]
    current = 0
    for f in flags:
        if f:
            current += 1
        else:
            break
    completed: List[int] = []
    i = current
    while i < len(flags):
        if flags[i]:
            j = i
            while j < len(flags) and flags[j]:
                j += 1
            # a run that touches the oldest day we hold may have begun earlier:
            # its length is a floor, not a fact, so only runs with a gap before
            # them count as completed
            if j < len(flags):
                completed.append(j - i)
            i = j
        else:
            i += 1
    return current, completed


def _median(xs: Sequence[int]) -> float:
    s = sorted(xs)
    n = len(s)
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0 if n else 0.0


def transitions(days: Sequence[Tuple[str, List[str]]]) -> Dict[Tuple[str, str], int]:
    """How often the crew moved from activity A to activity B: on consecutive
    worked days, A was logged and B was not, then B was logged and A was not.
    `days` is newest first."""
    out: Dict[Tuple[str, str], int] = {}
    for newer, older in zip(days, days[1:]):
        before, after = older[1], newer[1]
        for a in before:
            if a in after:
                continue
            for b in after:
                if b not in before:
                    out[(a, b)] = out.get((a, b), 0) + 1
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def personalize(ranking: ActivityRanking, days: Sequence[Tuple[str, List[str]]],
                successors: Dict[str, List[str]], labels: Optional[Dict[str, str]] = None,
                use_order: bool = True, stages: Sequence[Sequence[str]] = (),
                scheduled: Optional[Dict[str, str]] = None) -> ActivityRanking:
    """`ranking` reordered by the crew's own history; the same chips, the same
    set, "Other" last. With no usable history the ranking is returned as it was."""
    try:
        return _personalize(ranking, list(days or []), successors or {}, labels or {}, use_order,
                            [list(x) for x in stages or []], dict(scheduled or {}))
    except Exception:                      # the rules must never stop a day being logged
        return ranking


def _personalize(ranking: ActivityRanking, days: List[Tuple[str, List[str]]],
                 successors: Dict[str, List[str]], labels: Dict[str, str], use_order: bool = True,
                 stages: Optional[List[List[str]]] = None, scheduled: Optional[Dict[str, str]] = None
                 ) -> ActivityRanking:
    # A confirmed schedule's activities for the date count even for a crew with
    # no history on the project; everything else needs the crew's own days.
    if not days and not scheduled:
        return ranking
    chips = list(ranking.chips)
    by_id = {c.id: c for c in chips}
    label = {**labels, **{c.id: c.label for c in chips}}
    last_day, last_ids = days[0] if days else ("", [])
    score: Dict[str, float] = {}
    why: Dict[str, str] = {}
    best: Dict[str, float] = {}

    def lift(chip_id: str, points: float, reason: str) -> None:
        """Add `points` to a chip; its reason is its STRONGEST single cause."""
        if chip_id not in by_id or by_id[chip_id].band not in _PROMOTABLE_BANDS:
            return
        score[chip_id] = score.get(chip_id, 0.0) + points
        if points > best.get(chip_id, 0.0):
            best[chip_id] = points
            why[chip_id] = reason

    habit = transitions(days)
    # RECENT: every activity the crew logged lately, newer worked days heavier.
    for n, (day, ids) in enumerate(days):
        for i in ids:
            if i in by_id:
                lift(i, DECAY ** n, f"logged {day}")
    # CONTINUING and NEXT, from the most recent worked day.
    for a in last_ids:
        cur, completed = runs_of(days, a)
        usual = _median(completed)
        reached = bool(completed) and cur >= usual >= 2
        if a in by_id:
            lift(a, CONTINUING_BONUS + 0.05 * min(cur, 10),
                 (f"continuing - logged {_plural(cur, 'day')} running" if cur > 1 else f"continuing - logged {last_day}")
                 + (" (usual run reached)" if reached else ""))
        extra = RUN_REACHED_BONUS if reached else 0.0
        tail = f" (run {cur} days, usually {usual:g})" if reached else ""
        for s in successors.get(a, ()):
            if s in by_id and s not in last_ids:
                lift(s, NEXT_BONUS + extra, f"next after {label.get(a, a)}" + tail)
        for (x, y), n in habit.items():
            if x == a and y in by_id and y not in last_ids:
                lift(y, HABIT_BONUS * min(n, 2) + extra,
                     f"this crew moved from {label.get(a, a)} to {label.get(y, y)} before" + tail)
    if use_order and stages and days:
        from app.scheduling.trade_sequence import next_work
        extra_run = {}
        for a in last_ids:
            cur, completed = runs_of(days, a)
            extra_run[a] = RUN_REACHED_BONUS if (completed and cur >= _median(completed) >= 2) else 0.0
        for chip_id, kind, anchor in next_work(stages, last_ids):
            pts = (STAGE_NEXT_BONUS if kind == "next" else STAGE_SAME_BONUS) + extra_run.get(anchor, 0.0)
            what = label.get(anchor, anchor)
            lift(chip_id, pts, (f"next stage after {what}" if kind == "next" else f"same stage as {what}")
                 + f" (last on site {last_day})")
    for chip_id, why_text in (scheduled or {}).items():
        lift(chip_id, SCHEDULED_BONUS, why_text)
    ranked = sorted((i for i in score if score[i] > 0), key=lambda i: (-score[i], by_id[i].rank))[:MAX_PERSONAL]
    if not ranked:
        return ranking
    top = [by_id[i].model_copy(update={"band": "suggested", "reason": why.get(i)}) for i in ranked]
    moved = set(ranked)
    rest = [c for c in chips if c.id not in moved]
    suggested_rest = [c for c in rest if c.band == "suggested"]
    others = [c for c in rest if c.band not in ("suggested", "other")]
    last = [c for c in rest if c.band == "other"]
    order = top + suggested_rest + others + last
    order = [c.model_copy(update={"rank": n}) for n, c in enumerate(order)]
    return ranking.model_copy(update={"chips": order})
