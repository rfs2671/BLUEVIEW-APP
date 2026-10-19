"""Does the DM assistant sound like a person or like a template? Scored on the
real answer log (whatsapp_dm_answers), offline and deterministic.

Every function here is pure: rows in, numbers out. The live read and the
file handling are in scripts/dm_eval.py.

A row is one answer as _dm_log_answer stored it:
    {user_id, company_id, project_id, path, fallback, reason,
     question, answer, created_at}

WHAT COUNTS AS "TEMPLATE"
  canned      the same answer SHAPE (numbers, times and names folded to #)
              sent for several different questions. "4 on site at 588 now"
              and "7 on site at 9 Menahan now" are one shape.
  repeat      the same user got the identical answer to a different
              question within REPEAT_WINDOW. That is the 10:21 "Show me" /
              "Show me details" failure.
  re-ask      the same user asked again within REASK_WINDOW, in words close
              to the last question: the answer did not land.
  fallback    the log's own verdict (wa_assistant.answer_outcome): no
              answer, the fixed text after the model's wording failed, etc.
  long        a long answer to a short question.

WHAT IT DOES NOT DO: judge whether an answer is TRUE. That needs the data
behind it; review_sample() picks rows for a person (or a later model pass)
to label.

NOTHING PERSONAL LEAVES. scrub() removes phone-like digit runs, links (the
no-login punch/report/calendar links included) and email addresses from
every string this module returns.
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

REPEAT_WINDOW = timedelta(minutes=30)
REASK_WINDOW = timedelta(minutes=3)
REASK_SIMILARITY = 0.5
CANNED_MIN = 3
LONG_ANSWER_WORDS = 60
SHORT_QUESTION_WORDS = 8

# The log's paths whose answer is fixed text by design (see server.py
# _dm_assistant_reply). They are reported, not counted against the model.
TEMPLATE_PATHS = frozenset({
    "more", "menu", "menu_expired", "other_job", "not_a_question", "clarify",
})

_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|app|io|net|org)/\S*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")
_WORD = re.compile(r"[a-z0-9']+")
_SENT_START = re.compile(r"(^|[.!?\n]\s*)(\S+)")
_CAP = re.compile(r"\b[A-Z][\w'&-]*")

_STOP = frozenset(
    "a an the is are was were be to of in on at for and or how many much what who "
    "whats what's which do does did i me my we our you your it its this that there "
    "here now today please pls can could would will".split()
)


def scrub(text: Any) -> str:
    """Phone numbers, links and emails out; whitespace collapsed."""
    s = str(text or "")
    s = _URL.sub("[link]", s)
    s = _EMAIL.sub("[email]", s)
    s = _PHONE.sub("[number]", s)
    return " ".join(s.split())


def skeleton(answer: Any) -> str:
    """The answer's shape: lower case, with every number and every
    capitalised word that is not a sentence's first word (names of people,
    companies, jobs) turned into #, and a run of them into one # — so
    "588" and "9 Menahan" are the same slot."""
    s = scrub(answer)
    starts = {m.start(2) for m in _SENT_START.finditer(s)}
    s = _CAP.sub(lambda m: m.group(0) if m.start() in starts else "#", s)
    s = _NUM.sub("#", s).lower()
    s = re.sub(r"#(?:[\s'&-]+#)+", "#", s)
    return " ".join(s.split())


def _words(text: Any) -> list:
    return _WORD.findall(str(text or "").lower())


def similarity(a: Any, b: Any) -> float:
    """Jaccard over content words; 0 when either side has none."""
    wa = {w for w in _words(a) if w not in _STOP}
    wb = {w for w in _words(b) if w not in _STOP}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _ts(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if isinstance(v, dict) and "$date" in v:
        return _ts(v["$date"])
    return None


def _example(r: dict) -> dict:
    return {"path": r.get("path") or "", "question": scrub(r.get("question"))[:200],
            "answer": scrub(r.get("answer"))[:300]}


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def score(rows: Iterable[dict], *, canned_min: int = CANNED_MIN, top: int = 15) -> dict:
    """The report. Every quoted string in it is scrubbed."""
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: (str(r.get("user_id") or ""),
                             _ts(r.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)))
    total = len(rows)
    by_path = Counter(r.get("path") or "?" for r in rows)
    by_reason = Counter(r.get("reason") or "?" for r in rows if r.get("fallback"))
    fallbacks = sum(1 for r in rows if r.get("fallback"))

    # ── canned: one shape, several different questions ──
    model_rows = [r for r in rows if (r.get("path") or "") not in TEMPLATE_PATHS]
    shapes = defaultdict(list)
    for r in model_rows:
        if str(r.get("answer") or "").strip():
            shapes[skeleton(r.get("answer"))].append(r)
    canned = []
    canned_rows = 0
    for shape, rs in shapes.items():
        qs = {" ".join(_words(r.get("question"))) for r in rs}
        if len(rs) >= canned_min and len(qs) >= canned_min:
            canned_rows += len(rs)
            canned.append({"shape": shape[:200], "count": len(rs), "questions": len(qs),
                           "paths": dict(Counter(r.get("path") or "?" for r in rs)),
                           "example": _example(rs[0])})
    canned.sort(key=lambda c: -c["count"])

    # ── per user, in time order: repeats and re-asks ──
    repeats, reasks = [], []
    for i in range(1, total):
        prev, cur = rows[i - 1], rows[i]
        if (prev.get("user_id") or None) != (cur.get("user_id") or None) or not cur.get("user_id"):
            continue
        t0, t1 = _ts(prev.get("created_at")), _ts(cur.get("created_at"))
        if not t0 or not t1:
            continue
        gap = t1 - t0
        a0, a1 = str(prev.get("answer") or "").strip(), str(cur.get("answer") or "").strip()
        q0, q1 = str(prev.get("question") or ""), str(cur.get("question") or "")
        if (a0 and a0 == a1 and gap <= REPEAT_WINDOW
                and " ".join(_words(q0)) != " ".join(_words(q1))):
            repeats.append({"first": _example(prev), "then": _example(cur),
                            "minutes": round(gap.total_seconds() / 60, 1)})
        if gap <= REASK_WINDOW and similarity(q0, q1) >= REASK_SIMILARITY:
            reasks.append({"first": _example(prev), "then": _example(cur),
                           "seconds": int(gap.total_seconds())})

    long_rows = [r for r in model_rows
                 if len(_words(r.get("question"))) <= SHORT_QUESTION_WORDS
                 and len(_words(r.get("answer"))) > LONG_ANSWER_WORDS]

    openers = Counter(" ".join(_words(skeleton(r.get("answer")))[:3])
                      for r in model_rows if str(r.get("answer") or "").strip())

    return {
        "answers": total,
        "users": len({r.get("user_id") for r in rows if r.get("user_id")}),
        "by_path": dict(by_path.most_common()),
        "fallbacks": fallbacks, "fallback_pct": _pct(fallbacks, total),
        "fallback_reasons": dict(by_reason.most_common()),
        "template_path_answers": sum(by_path[p] for p in TEMPLATE_PATHS),
        "canned_answers": canned_rows,
        "canned_pct_of_model": _pct(canned_rows, len(model_rows)),
        "canned_shapes": canned[:top],
        "repeats": len(repeats), "repeat_examples": repeats[:top],
        "reasks": len(reasks), "reask_pct": _pct(len(reasks), total),
        "reask_examples": reasks[:top],
        "long_answers": len(long_rows),
        "long_examples": [_example(r) for r in long_rows[:top]],
        "top_openers": [{"opener": o, "count": n} for o, n in openers.most_common(10) if o],
    }


def review_sample(rows: Iterable[dict], n: int = 200, seed: int = 7) -> list:
    """Up to n rows for a person to label, spread across paths (round robin),
    scrubbed, with empty label columns."""
    by = defaultdict(list)
    for r in rows:
        if isinstance(r, dict) and str(r.get("answer") or "").strip():
            by[r.get("path") or "?"].append(r)
    rnd = random.Random(seed)
    for v in by.values():
        rnd.shuffle(v)
    out, keys = [], sorted(by)
    while len(out) < n and any(by[k] for k in keys):
        for k in keys:
            if by[k] and len(out) < n:
                r = by[k].pop()
                t = _ts(r.get("created_at"))
                out.append({"when": t.isoformat() if t else "", "path": k,
                            "fallback": bool(r.get("fallback")),
                            "question": scrub(r.get("question")),
                            "answer": scrub(r.get("answer")),
                            "sounds_human_1_5": "", "answered_the_question_y_n": "",
                            "note": ""})
    return out


def render(report: dict) -> str:
    """The report as plain text for a terminal."""
    r = report
    lines = [
        f"DM answers: {r['answers']} from {r['users']} people",
        f"  fallbacks: {r['fallbacks']} ({r['fallback_pct']}%)  "
        + ", ".join(f"{k} {v}" for k, v in r["fallback_reasons"].items()),
        f"  fixed-text paths: {r['template_path_answers']}",
        f"  canned (same shape, {CANNED_MIN}+ different questions): "
        f"{r['canned_answers']} ({r['canned_pct_of_model']}% of model answers)",
        f"  same answer repeated to a different question: {r['repeats']}",
        f"  asked again within {int(REASK_WINDOW.total_seconds() // 60)} min: "
        f"{r['reasks']} ({r['reask_pct']}%)",
        f"  long answer to a short question: {r['long_answers']}",
        "", "BY PATH: " + ", ".join(f"{k} {v}" for k, v in r["by_path"].items()),
        "", "TOP CANNED SHAPES",
    ]
    for c in r["canned_shapes"]:
        lines.append(f"  {c['count']}x / {c['questions']} questions  {c['shape']}")
        lines.append(f"      e.g. Q: {c['example']['question']}")
    lines += ["", "REPEATS"]
    for x in r["repeat_examples"]:
        lines.append(f"  Q1: {x['first']['question']}  |  Q2: {x['then']['question']}")
        lines.append(f"      A (both): {x['then']['answer'][:160]}")
    lines += ["", "ASKED AGAIN"]
    for x in r["reask_examples"]:
        lines.append(f"  Q1: {x['first']['question']}  ->  A: {x['first']['answer'][:120]}")
        lines.append(f"      Q2 ({x['seconds']}s later): {x['then']['question']}")
    lines += ["", "OPENERS: " + ", ".join(f"\"{o['opener']}\" {o['count']}" for o in r["top_openers"])]
    return "\n".join(lines)
