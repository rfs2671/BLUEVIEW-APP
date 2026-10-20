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
every string this module returns. mask_names() takes out the worker and
company names the log itself recorded for that answer (tool_data), and any
run of two or more capitalised words ("Moshe Klein", "Power Direct").
"""

from __future__ import annotations

import hashlib
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
# _dm_assistant_reply), or, for "sheet", an internal "[Sheet] <label>"
# marker standing in for the image that was sent. They are reported, not
# counted against the model.
TEMPLATE_PATHS = frozenset({
    "more", "menu", "menu_expired", "other_job", "not_a_question", "clarify",
    "sheet", "closer", "no_repeat", "walk_help",
})

_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|app|io|net|org)/\S*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")
# Any script's letters and digits, so a Yiddish question in Hebrew letters
# has words too.
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_NAME_RUN = re.compile(r"\b[A-Z][\w'&.-]*(?:\s+[A-Z][\w'&.-]*)+")
_NAME_KEYS = frozenset({"name", "company", "worker_name", "assignee", "contact_name", "sub"})
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


def known_names(tool_data: Any) -> set:
    """The people and companies a logged answer's tool_data names: name /
    company fields, by_company pairs, the "added" list."""
    out = set()

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, (list, tuple)):
            if key == "by_company":
                for pair in v:
                    if isinstance(pair, (list, tuple)) and pair and isinstance(pair[0], str):
                        out.add(pair[0])
            elif key == "added":
                out.update(x for x in v if isinstance(x, str))
            else:
                for x in v:
                    walk(x, key)
        elif isinstance(v, str) and key in _NAME_KEYS:
            out.add(v)

    walk(tool_data)
    return {n.strip() for n in out if len(n.strip()) >= 2}


def mask_names(text: Any, names: Iterable[str] = ()) -> str:
    """Known names, then any run of 2+ capitalised words, -> [name]."""
    s = str(text or "")
    for n in sorted(set(names), key=len, reverse=True):
        s = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", "[name]", s, flags=re.IGNORECASE)
    return _NAME_RUN.sub("[name]", s)


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


def _kind(r: dict) -> str:
    """A headcount answer's kind (count / subs / list …): the row's own
    `kind`, else its tool_data's. Empty for every other path."""
    td = r.get("tool_data")
    return str(r.get("kind") or (td.get("kind") if isinstance(td, dict) else "") or "")


def scope_key(r: dict) -> str:
    """What data a headcount answer read -- its job, the sub it named and
    the "since" -- as an opaque key (a row's own `scope`, else derived from
    its project_id and tool_data). Kind alone does not say it: a whole-site
    count and an Arkon-only count are both "count" (Codex on #816)."""
    if r.get("scope"):
        return str(r["scope"])
    td = r.get("tool_data") if isinstance(r.get("tool_data"), dict) else {}
    raw = "|".join(str(x or "") for x in (r.get("project_id"), td.get("company"), td.get("since")))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _same_data_question(a: dict, b: dict) -> bool:
    """Two headcount answers of the same kind over the same data (job, sub,
    since): the same question in other words ("How many subs on site?" /
    "How many companies on site"), so the same answer is right, not a
    repeat. A different kind -- a subs question answered with the worker
    count -- or a different scope still is one."""
    return ((a.get("path") or "") == (b.get("path") or "") == "headcount"
            and _kind(a) and _kind(a) == _kind(b) and scope_key(a) == scope_key(b))


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
    # Each answer is compared with EVERY earlier answer to the same user in
    # the window, not only the one before it, so a question in between does
    # not hide a repeat or a re-ask. Each answer counts at most once.
    repeats, reasks = [], []
    for i in range(1, total):
        cur = rows[i]
        uid, t1 = cur.get("user_id"), _ts(cur.get("created_at"))
        if not uid or not t1:
            continue
        a1 = str(cur.get("answer") or "").strip()
        q1 = str(cur.get("question") or "")
        got_repeat = got_reask = False
        j = i - 1
        while j >= 0 and rows[j].get("user_id") == uid and not (got_repeat and got_reask):
            prev = rows[j]
            t0 = _ts(prev.get("created_at"))
            j -= 1
            if not t0:
                continue
            gap = t1 - t0
            if gap > max(REPEAT_WINDOW, REASK_WINDOW):
                break
            a0 = str(prev.get("answer") or "").strip()
            q0 = str(prev.get("question") or "")
            # A sheet SENT again is the image asked for again, not words
            # repeated: its logged answer is a "[Sheet]" marker. A failure
            # text ("Found … but couldn't send the image") is words.
            if (not got_repeat and a0 and a0 == a1 and gap <= REPEAT_WINDOW
                    and not a1.startswith("[Sheet]")
                    and not _same_data_question(prev, cur)
                    and " ".join(_words(q0)) != " ".join(_words(q1))):
                got_repeat = True
                repeats.append({"first": _example(prev), "then": _example(cur),
                                "minutes": round(gap.total_seconds() / 60, 1)})
            if (not got_reask and gap <= REASK_WINDOW
                    and similarity(q0, q1) >= REASK_SIMILARITY):
                got_reask = True
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
        "check_failed_examples": [
            {**_example(r), "rejected": scrub(r.get("rejected"))[:300],
             "check": str(r.get("check") or "")}
            for r in rows if r.get("reason") == "check_failed"][:top],
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
    lines += ["", "CHECK FAILED (the model's wording, thrown away)"]
    for x in r.get("check_failed_examples", []):
        lines.append(f"  Q: {x['question']}  [{x['check'] or 'not logged'}]")
        lines.append(f"      rejected: {x['rejected'] or '(not logged before this change)'}")
        lines.append(f"      sent: {x['answer'][:160]}")
    lines += ["", "OPENERS: " + ", ".join(f"\"{o['opener']}\" {o['count']}" for o in r["top_openers"])]
    return "\n".join(lines)
