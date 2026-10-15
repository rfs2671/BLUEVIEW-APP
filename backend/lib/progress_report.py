"""The project progress report: what a GC sends an owner or a lender.

Plain construction language, evidence only. Every statement in it is built
from a record the server read for the job and the period: check-ins (who was
on site, which days), filed daily logs (each crew's work description,
locations and photos, the day's observations), the job's group chat (text),
walkthrough photos, DOB/DOT records, commitments, punch items and upcoming
events. Nothing is estimated; a section with nothing in it says "None".

Never "man-days", never a percentage against the period before: an owner
reads days on site and workers on site.

  1 Cover          job, GC, period, prepared date
  2 Summary        5-8 sentences (the model writes them from the facts here;
                   check_summary keeps only a text whose every number and
                   name is in the facts, else summary_fallback)
  3 Schedule       "Actual work (from daily logs)": one row per sub, bars on
                   the days it was on site, each bar labelled with its work
  4 Work by sub    dates on site, average / most workers, the work (from the
                   logs), its issues
  5 Photos         10-15 from the filed DAILY LOGS only (never the group
                   chat's or a walkthrough's), grouped by sub: each sub's
                   earliest and latest, dated, captioned with its work line;
                   vision only screens out blurry / people / document shots.
                   Fewer usable: what there is, never padded
  6 Site activity  workers on site per day, by sub
  7 DOB / DOT      new records, number and status
  8 Open items     late commitments, punch by assignee
  9 Coming up      the next 2 weeks

Pure: no database, no network, no model. server.py reads the rows, calls the
model, fetches the photos, and renders the PDF with WeasyPrint.
"""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import attendance as att
from lib import wa_photos
from lib import project_report as base
from lib.datefmt import strftime as _fmt

NY = base.NY
UPCOMING_DAYS = 14
#: At most this many photos; as many as the period has that pass (the aim
#: is 10-15, never a photo that does not).
MAX_PHOTOS = 15
ATTACHED_LINE = "Full report (PDF) attached."
SOURCE_LINE = "Source: Levelog records — check-ins, daily logs and their photos, group chat"

#: Never in the report.
FORBIDDEN = re.compile(r"man[- ]?days?|\d+\s?%|percent", re.IGNORECASE)

#: Colors for the subs (charts), in order.
PALETTE = ["#1F3A5F", "#C8102E", "#2E7D32", "#E07B00", "#6A1B9A", "#00838F", "#8D6E63",
           "#5C6BC0", "#AD1457", "#9E9D24"]


# ── SMALL THINGS ─────────────────────────────────────────────────────────────

def _e(v: Any) -> str:
    return html.escape(base.no_phone(v))


def _day(d: Optional[date]) -> str:
    return _fmt(d, "%b %-d") if d else ""


def _wday(d: date) -> str:
    return _fmt(d, "%a %b %-d")


def _span(a: date, b: date) -> str:
    """"Oct 2", "Oct 2–15", "Sep 28–Oct 3"."""
    if a == b:
        return _day(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{_day(a)}–{b.day}"
    return f"{_day(a)}–{_day(b)}"


def short_name(name: Any, work: Any = "") -> str:
    """A sub as people say it: "Arkon Builders" -> "Arkon"; "J&G
    Scaffolding" -> "J&G" when the work already says scaffolding."""
    from lib import wa_style
    words = str(name or "").split()
    while len(words) > 1 and _fold(words[-1]) in wa_style._CO_TAIL:
        words.pop()
    if len(words) > 1 and _fold(words[-1]) in wa_style._TRADE_WORDS \
            and _fold(words[-1]) in _fold(work).split():
        words.pop()
    return " ".join(words) or str(name or "")


def short_period(start: date, end: date, now: datetime) -> str:
    """"Oct 2–15", "Sep 28 – Oct 11" (the year only when it is not this one)."""
    full = base.period_label(start, end)
    year = (att.local_day(now) or end).year
    return re.sub(r",\s*" + str(year) + r"$", "", full) if start.year == end.year == year else full


def job_title(label: str) -> str:
    """"588 Thomas S Boyland St" -> "588 Thomas S Boyland" (the street word
    off, as people say it)."""
    t = " ".join(str(label or "").split())
    return re.sub(r"\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Pl|Place)\.?$", "", t, flags=re.IGNORECASE) or t


def _fold(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def company_key(name: Any) -> str:
    """One key however a company is written: "Arkon" / "Arkon Builders LLC"
    -> "arkon", "Power Direct" -> "power direct". Trade words stay: "ABC
    Plumbing" and "ABC Electrical" are two subs (Codex on #803)."""
    from lib import wa_style
    full = _fold(name)
    return " ".join([w for w in full.split() if w not in wa_style._CO_TAIL] or full.split())


def bare_key(key: str) -> str:
    """The key without its trade words: "j g scaffolding" -> "j g"."""
    from lib import wa_style
    words = key.split()
    return " ".join([w for w in words if w not in wa_style._TRADE_WORDS] or words)


def canonical_keys(keys: Iterable[str]) -> Dict[str, str]:
    """Each key -> the sub it is. "j g" (no trade word) is "j g scaffolding"
    when that is the only sub it can be; never merges two subs whose names
    differ by their trade ("abc plumbing", "abc electrical")."""
    keys = {k for k in keys if k}
    out = {k: k for k in keys}
    for k in keys:
        if bare_key(k) != k:
            continue
        fuller = [k2 for k2 in keys if k2 != k and bare_key(k2) == k]
        if len(fuller) == 1:
            out[k] = fuller[0]
    return out


def sub_aliases(keys: Iterable[str]) -> Dict[str, List[str]]:
    """What in a text names each sub: its key, and its name without the
    trade word when no other sub shares that ("J&G" -> J&G Scaffolding)."""
    keys = list(keys)
    bares = Counter(bare_key(k) for k in keys)
    return {k: [k] + ([bare_key(k)] if bare_key(k) != k and bares[bare_key(k)] == 1 else [])
            for k in keys}


def names_sub(text: Any, names: Iterable[str]) -> bool:
    """`text` names the sub ("J&G" in "J&G short 2 guys")."""
    t = f" {_fold(text)} "
    return any(n and len(n) >= 3 and f" {n} " in t for n in names)


_FLOOR = re.compile(r"\b(?:fl(?:oor)?s?\.?\s*#?(\d{1,2})(?:\s*(?:-|–|to|&|and)\s*(\d{1,2}))?"
                    r"|(\d{1,2})(?:st|nd|rd|th)\s+fl(?:oor)?)\b", re.IGNORECASE)


def floors_in(text: Any) -> List[int]:
    out: List[int] = []
    for m in _FLOOR.finditer(str(text or "")):
        a = m.group(1) or m.group(3)
        b = m.group(2)
        if a:
            lo = int(a)
            hi = int(b) if b else lo
            out.extend(range(min(lo, hi), max(lo, hi) + 1))
    return sorted(set(n for n in out if 0 < n < 100))


def floors_label(floors: Iterable[int]) -> str:
    """[1, 2, 3, 4] -> "fl 1–4"; [2, 5] -> "fl 2, 5"."""
    fs = sorted(set(floors))
    if not fs:
        return ""
    if fs == list(range(fs[0], fs[-1] + 1)) and len(fs) > 1:
        return f"fl {fs[0]}–{fs[-1]}"
    return "fl " + ", ".join(str(f) for f in fs)


def _clean_work(text: Any) -> str:
    """A crew's work description, as one short phrase: "Framing", "Riser
    install" (never the floors -- they go after it)."""
    t = " ".join(str(text or "").split()).strip(" .;,-")
    t = _FLOOR.sub("", t)
    t = re.sub(r"\s+(?:on|at|in)\s*$", "", t.strip(" .;,-"))
    t = re.sub(r"\s{2,}", " ", t).strip(" .;,-")
    return (t[:1].upper() + t[1:]) if t else ""


# ── THE ROWS, READ ───────────────────────────────────────────────────────────

def _log_activities(logs: Iterable[dict], start: date, end: date) -> List[Dict[str, Any]]:
    """Every crew row of the filed daily logs in the period: {date, company,
    key, trade, workers, work, where, floors, photos}."""
    out = []
    for lg in logs:
        d = base._d(lg.get("date"))
        if not base._in(d, start, end):
            continue
        for slot, a in enumerate((lg.get("data") or {}).get("activities") or []):
            if not isinstance(a, dict) or not str(a.get("company") or "").strip():
                continue
            where = " ".join(str(a.get("work_locations") or "").split())
            work = _clean_work(a.get("work_description"))
            try:
                workers = int(a.get("num_workers") or 0)
            except (TypeError, ValueError):
                workers = 0
            out.append({"date": d, "company": str(a["company"]).strip(), "log": f"{lg.get('_id') or d}:{slot}",
                        "key": company_key(a["company"]), "trade": str(a.get("trade") or "").strip(),
                        "workers": workers, "work": work, "where": where,
                        "floors": floors_in(where) or floors_in(a.get("work_description")),
                        "photos": [p for p in (a.get("photos") or []) if isinstance(p, dict)]})
    return out


def _log_observations(logs: Iterable[dict], start: date, end: date) -> List[Dict[str, Any]]:
    out = []
    for lg in logs:
        d = base._d(lg.get("date"))
        if not base._in(d, start, end):
            continue
        for o in ((lg.get("data") or {}).get("observations") or []):
            t = base.no_phone((o or {}).get("description"))
            if t and t.lower().strip(". ") not in ("n/a", "na", "none", "no", "nothing"):
                out.append({"date": d, "text": t[:240]})
    out.sort(key=lambda x: x["date"])
    return out


def _chat(rows: Iterable[dict], start: date, end: date) -> List[Dict[str, Any]]:
    """The group's own words in the period: text people wrote (never the
    bot's, never a skipped / voice placeholder)."""
    out = []
    for r in rows:
        d = att.local_day(r.get("timestamp") or r.get("created_at"))
        voice = r.get("voice") or {}
        if not base._in(d, start, end) or r.get("skipped") or r.get("from_me") \
                or str(r.get("sender") or "") == "bot" or voice.get("review") or voice.get("flagged"):
            continue
        # A photo's body may be its base64 thumbnail: only its caption is words.
        said = (r.get("voice") or {}).get("transcript") or r.get("body")
        text = base.no_phone(wa_photos.caption(said))
        if len(text) < 8 or text.startswith("("):
            continue
        out.append({"date": d, "who": base.no_phone(r.get("sender_name") or ""), "text": text[:300]})
    out.sort(key=lambda x: x["date"])
    return out


# ── THE SUBS ─────────────────────────────────────────────────────────────────

def _runs(days: List[date]) -> List[Tuple[date, date]]:
    """Consecutive working days as one bar (a weekend in between does not
    break it)."""
    runs: List[Tuple[date, date]] = []
    for d in sorted(set(days)):
        if runs:
            a, b = runs[-1]
            gap = [b + timedelta(days=i) for i in range(1, (d - b).days)]
            if all(g.weekday() >= 5 for g in gap):
                runs[-1] = (a, d)
                continue
        runs.append((d, d))
    return runs


def _work_label(acts: List[Dict[str, Any]]) -> str:
    """"Framing fl 1–4", "Riser install fl 2–3 · Fixtures" -- the work the
    logs give for these rows, most frequent first, at most two."""
    if not acts:
        return ""
    by_work: Dict[str, List[int]] = defaultdict(list)
    count: Counter = Counter()
    for a in acts:
        if not a["work"]:
            continue
        count[a["work"]] += 1
        by_work[a["work"]].extend(a["floors"])
    parts = []
    for work, _n in count.most_common(2):
        fl = floors_label(by_work[work])
        parts.append(f"{work} {fl}".strip())
    return " · ".join(parts)


def _subs(checkins: List[dict], acts: List[Dict[str, Any]], start: date, end: date,
          chat: List[Dict[str, Any]], commitments: List[dict], punch_items: List[dict],
          observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per sub: its days on site (check-ins, else the logs), crew
    per day, the work by run, issues."""
    days = att.by_day(checkins, start, end)
    canon = canonical_keys([company_key(co) for by_co in days.values() for co in by_co]
                           + [a["key"] for a in acts])
    for a in acts:
        a["key"] = canon.get(a["key"], a["key"])

    def key_of(name: Any) -> str:
        k = company_key(name)
        return canon.get(k, k)
    aliases = sub_aliases(set(canon.values()))
    crew: Dict[str, Dict[date, int]] = defaultdict(dict)
    names: Dict[str, Counter] = defaultdict(Counter)
    for d, by_co in days.items():
        for co, workers in by_co.items():
            k = key_of(co) or co.lower()
            crew[k][d] = crew[k].get(d, 0) + len(workers)
            names[k][co] += len(workers)
    log_crew: Dict[str, Dict[date, int]] = defaultdict(dict)
    trades: Dict[str, Counter] = defaultdict(Counter)
    for a in acts:
        k = a["key"] or a["company"].lower()
        if not names[k]:
            names[k][a["company"]] = 1
        if a["workers"]:
            log_crew[k][a["date"]] = max(log_crew[k].get(a["date"], 0), a["workers"])
        if a["trade"]:
            trades[k][a["trade"]] += 1
    out = []
    for k in set(crew) | set(log_crew):
        per_day = crew.get(k) or log_crew.get(k) or {}
        if not per_day:
            continue
        name = names[k].most_common(1)[0][0] if names[k] else k.title()
        mine = [a for a in acts if (a["key"] or a["company"].lower()) == k]
        runs = []
        for a, b in _runs(list(per_day)):
            in_run = [x for x in mine if a <= x["date"] <= b]
            runs.append({"start": a, "end": b, "label": _work_label(in_run)})
        # One bullet per stretch of the same work in the same place:
        # "Framing — fl 1–2 (Oct 2–9)", then "Framing — fl 3–4 (Oct 12–15)".
        stretches: List[Dict[str, Any]] = []
        for x in sorted(mine, key=lambda y: y["date"]):
            if not x["work"]:
                continue
            place = floors_label(x["floors"]) or base.no_phone(x["where"])[:60]
            place = place[:1].upper() + place[1:] if place and not x["floors"] else place
            open_one = next((w for w in reversed(stretches) if w["work"] == x["work"]), None)
            if open_one and open_one["place"] == place:
                open_one["last"] = x["date"]
            else:
                stretches.append({"work": x["work"], "place": place, "first": x["date"], "last": x["date"]})
        bullets = [f"{w['work']}{' — ' + w['place'] if w['place'] else ''} ({_span(w['first'], w['last'])})"
                   for w in stretches]
        issues = []
        for c in commitments:
            o = c.get("owner") or {}
            if key_of(o.get("sub_company") or o.get("name")) == k and c.get("_late"):
                issues.append(f"Late: {base.no_phone(c.get('summary'))[:120]} "
                              f"(due {_day(base._d((c.get('due') or {}).get('due_at')))})")
        open_punch = sum(1 for p in punch_items if p.get("status") == "open" and key_of(
            (p.get("assignee") or {}).get("company") or (p.get("assignee") or {}).get("name")) == k)
        if open_punch:
            issues.append(f"{open_punch} open punch item{'s' if open_punch != 1 else ''}")
        for o in observations:
            if names_sub(o["text"], aliases.get(k, [k])):
                issues.append(f"{_day(o['date'])}: {o['text']}")
        counts = list(per_day.values())
        out.append({"key": k, "name": name, "trade": trades[k].most_common(1)[0][0] if trades[k] else "",
                    "days": sorted(per_day), "crew": per_day,
                    "avg": round(sum(counts) / len(counts), 1), "max": max(counts),
                    "first": min(per_day), "last": max(per_day), "runs": runs,
                    "work": bullets, "label": _work_label(mine), "issues": issues[:6],
                    "chat": [c for c in chat if names_sub(c["text"], aliases.get(k, [k]))][:8]})
    out.sort(key=lambda s: (-len(s["days"]), -s["max"], s["name"]))
    return out


# ── SITE ACTIVITY ────────────────────────────────────────────────────────────

def _site(subs: List[Dict[str, Any]], start: date, end: date, today: date) -> Dict[str, Any]:
    days: Dict[date, Dict[str, int]] = defaultdict(dict)
    for s in subs:
        for d, n in s["crew"].items():
            days[d][s["name"]] = n
    worked = sorted(days)
    # The days the site could have been worked: weekdays up to today, and any
    # weekend day it was.
    last = min(end, today)
    possible = sorted({start + timedelta(days=i) for i in range((last - start).days + 1)
                       if (start + timedelta(days=i)).weekday() < 5} | set(worked))
    if not worked:
        return {"worked": 0, "possible": len(possible), "table": []}
    totals = {d: sum(days[d].values()) for d in worked}
    top = max(totals.values())
    return {"worked": len(worked), "possible": len(possible),
            "avg": round(sum(totals.values()) / len(worked)), "max": top,
            "max_day": next(d for d in worked if totals[d] == top),
            "table": [{"day": d, "by_sub": dict(days[d]), "total": totals[d]} for d in worked]}


# ── OPEN ITEMS AND WHAT'S NEXT ──────────────────────────────────────────────

def _late_commitments(items: List[dict], end: date) -> List[Dict[str, Any]]:
    out = []
    for i in items:
        due = base._d((i.get("due") or {}).get("due_at"))
        made = base._d(i.get("created_at"))
        # Not yet made by the end of the period: not late in it (Codex on #803).
        if made and made > end:
            continue
        if i.get("status") in base._OPEN and due and due < end:
            i["_late"] = True
            o = i.get("owner") or {}
            out.append({"who": base.no_phone(o.get("name") or o.get("sub_company") or "No owner yet"),
                        "company": base.no_phone(o.get("sub_company") or ""),
                        "what": base.no_phone(i.get("summary") or "")[:160], "due": due,
                        "since": base._d(i.get("created_at")), "days_late": (end - due).days})
    out.sort(key=lambda x: (x["due"], x["who"]))
    return out


def _punch_summary(items: List[dict]) -> Dict[str, Any]:
    live = [i for i in items if i.get("status") in ("open", "ready_to_check", "closed")]
    if not live:
        return {}
    by: Dict[str, Dict[str, int]] = defaultdict(lambda: {"open": 0, "ready": 0, "closed": 0})
    for i in live:
        a = i.get("assignee") or {}
        who = base.no_phone(a.get("name") or a.get("company") or "Unassigned")
        by[who][{"open": "open", "ready_to_check": "ready", "closed": "closed"}[i["status"]]] += 1
    rows = sorted(({"name": k, **v} for k, v in by.items()), key=lambda r: (-r["open"], -r["ready"], r["name"]))
    return {"open": sum(r["open"] for r in rows), "ready": sum(r["ready"] for r in rows),
            "closed": sum(r["closed"] for r in rows), "by_assignee": rows}


def _coming_up(events: List[dict], items: List[dict], start: date, end: date) -> List[Dict[str, Any]]:
    out = []
    for e in base._events(events, start, end):
        what = e["title"] + (f" ({e['agency']})" if e.get("agency") else "")
        out.append({"date": e["date"], "what": what, "time": e.get("time") or "",
                    "say": f"{what} on {_wday(e['date'])}"})
    for i in items:
        due = base._d((i.get("due") or {}).get("due_at"))
        if i.get("status") in base._OPEN and base._in(due, start, end):
            o = i.get("owner") or {}
            who = base.no_phone(o.get("name") or o.get("sub_company") or "")
            item = base.no_phone(i.get("summary"))[:120]
            out.append({"date": due, "time": "",
                        "what": f"{who + ': ' if who else ''}{item} (due)",
                        "say": f"{item[:1].lower() + item[1:]}{' from ' + who if who else ''} "
                               f"due {_wday(due)}"})
    out.sort(key=lambda x: (x["date"], x["time"]))
    return out[:20]


# ── PHOTOS ───────────────────────────────────────────────────────────────────

def photo_candidates(acts: List[Dict[str, Any]], start: date, end: date,
                     *_ignored: Any, **_ignored_kw: Any) -> List[Dict[str, Any]]:
    """The report's photos come from the filed daily logs ONLY: each one is
    already filed under its sub, its day and its work. Never a photo from the
    group chat or a walkthrough (they are kept for the search and the media
    log, not for the report)."""
    out = []
    for a in acts:
        if not base._in(a["date"], start, end):
            continue
        place = floors_label(a["floors"]) or base.no_phone(a["where"])[:60]
        for n, p in enumerate(a["photos"]):
            key = p.get("enhanced_r2_key") or p.get("original_r2_key") or p.get("thumb_r2_key")
            # A filed photo with only its inline copy is a photo too (Codex on
            # #803): keyed by where it is, read from the log by the server.
            if not key and (p.get("base64") or p.get("thumb_base64")):
                key = f"inline:{a['log']}:{n}"
            if key:
                out.append({"key": key, "date": a["date"], "sub": a["company"], "where": place,
                            "words": work_line(a["work"] or a["trade"], place),
                            "source": "daily log", "photo": p})
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: (c["date"], c["key"])):
        if c["key"] not in seen:
            seen.add(c["key"])
            uniq.append(c)
    return uniq


def work_line(work: Any, place: Any) -> str:
    """The caption of a daily-log photo: the sub's work that day, as the log
    says it -- "Framing — fl 1–2", "Scaffolding — Front facade"."""
    w = str(work or "").strip() or "Work on site"
    p = str(place or "").strip()
    if p and p[:1].isalpha() and not p.startswith("fl "):
        p = p[:1].upper() + p[1:]
    return f"{w} — {p}" if p else w


def to_judge(cands: List[Dict[str, Any]], limit: int = 40) -> List[Dict[str, Any]]:
    """Which photos to send to vision (it costs): each sub's first 3 and last
    3, then the rest spread over the period."""
    by_sub: Dict[str, List[dict]] = defaultdict(list)
    for c in cands:
        by_sub[company_key(c["sub"]) or c["source"]].append(c)
    picked: List[dict] = []
    for group in by_sub.values():
        for c in group[:3] + group[-3:]:
            if c not in picked:
                picked.append(c)
    rest = [c for c in cands if c not in picked]
    step = max(1, len(rest) // max(1, limit - len(picked))) if rest else 1
    picked += rest[::step]
    return picked[:limit]


def pick_photos(cands: List[Dict[str, Any]], verdicts: Dict[str, Dict[str, Any]],
                most: int = MAX_PHOTOS) -> List[Dict[str, Any]]:
    """Up to 15 daily-log photos for the report, grouped by sub: only photos
    vision calls a clear progress shot (never blurry, people-only, a document
    or a duplicate of the same sub, day and place); each sub's earliest and
    latest first, then every sub's best in turn. Fewer than 10 usable: what
    there is -- never padded. The caption is the sub's work line from the
    log (never words the model wrote)."""
    good = []
    for c in cands:
        if c.get("source") != "daily log":
            continue
        v = verdicts.get(c["key"]) or {}
        if v.get("ok") and v.get("kind", "progress") == "progress":
            good.append({**c, "score": float(v.get("score") or 0),
                         "caption": base.no_phone(c["words"] or "Work on site")[:120]})
    chosen: List[dict] = []

    def add(c):
        if len(chosen) >= most or any(x["key"] == c["key"] for x in chosen):
            return False
        if any(company_key(x["sub"]) == company_key(c["sub"]) and x["date"] == c["date"]
               and x["where"] == c["where"] for x in chosen):
            return False
        chosen.append(c)
        return True
    by_sub: Dict[str, List[dict]] = defaultdict(list)
    for c in good:
        by_sub[company_key(c["sub"]) or c["sub"]].append(c)
    for group in by_sub.values():
        group.sort(key=lambda c: (c["date"], -c["score"]))
        if group[0]["date"] != group[-1]["date"]:
            add({**group[0], "pair": "before"})
            add({**group[-1], "pair": "after"})
        else:
            add(max(group, key=lambda c: c["score"]))
    # Then each sub's best in turn, so no one sub fills the page.
    queues = [sorted(g, key=lambda c: -c["score"]) for g in by_sub.values()]
    while len(chosen) < most and any(queues):
        for q in queues:
            while q and not add(q.pop(0)):
                pass
    chosen.sort(key=lambda c: (c["sub"], c["date"]))
    return chosen


def parse_verdict(said: Any) -> Optional[Dict[str, Any]]:
    """The vision model's JSON answer, checked: {ok, kind, score, caption}
    or None."""
    import json
    m = re.search(r"\{.*\}", str(said or ""), re.DOTALL)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    kind = str(v.get("kind") or "other").lower()
    try:
        score = max(0.0, min(10.0, float(v.get("score") or 0)))
    except (TypeError, ValueError):
        score = 0.0
    caption = " ".join(str(v.get("caption") or "").split())[:120]
    return {"ok": bool(v.get("ok")) and kind == "progress", "kind": kind, "score": score,
            "caption": base.no_phone(caption)}


JUDGE_PROMPT = (
    "You pick photos for a construction progress report an owner will read. Look at this "
    "jobsite photo and answer in JSON only: {\"ok\": true|false, \"kind\": \"progress\"|"
    "\"people\"|\"document\"|\"blurry\"|\"other\", \"score\": 0-10, \"caption\": \"...\"}. "
    "ok is true only for a clear, well-lit photo that shows the work or the building "
    "(framing, walls, risers, scaffolding, a floor, the facade). kind is people when people "
    "fill the frame, document for paper, screens or drawings, blurry when out of focus. "
    "score: wide, sharp, shows progress = high. caption: one short line, plain construction "
    "words, ONLY what is visible (e.g. \"Metal stud framing on the 3rd floor\"); never a name, "
    "a number or a date you cannot see.")


# ── THE SUMMARY ──────────────────────────────────────────────────────────────

def facts(rep: Dict[str, Any]) -> List[str]:
    """What the summary may say, one fact a line, each with its source."""
    out = []
    site = rep["site"]
    if site["worked"]:
        out.append(f"[check-ins] The site was worked {site['worked']} of {site['possible']} working days; "
                   f"an average of {site['avg']} workers on site a day; busiest day "
                   f"{_wday(site['max_day'])} with {site['max']} workers.")
    else:
        out.append("[check-ins] No check-ins in this period.")
    for s in rep["subs"]:
        work = "; ".join(s["work"]) or "no work description in the daily logs"
        out.append(f"[daily logs] {s['name']}{' (' + s['trade'] + ')' if s['trade'] else ''}: "
                   f"{len(s['days'])} days on site ({_span(s['first'], s['last'])}), "
                   f"up to {s['max']} workers. Work: {work}.")
        for c in s["chat"][:3]:
            out.append(f"[group chat {_day(c['date'])}, {c['who'] or 'someone'}] {c['text']}")
    for o in rep["observations"][:6]:
        out.append(f"[daily log {_day(o['date'])}] {o['text']}")
    if rep["records"]:
        for r in rep["records"]:
            out.append(f"[DOB/DOT] New {r['kind']} {r['number']} ({_day(r['date'])}), status {r['status']}.")
    else:
        out.append("[DOB/DOT] No new DOB or DOT records.")
    for c in rep["late"]:
        out.append(f"[commitments] Late: {c['who']} — {c['what']} (due {_day(c['due'])}).")
    p = rep["punch"]
    if p:
        out.append(f"[punch] {p['open']} open, {p['ready']} ready to check, {p['closed']} closed.")
    for e in rep["coming_up"][:6]:
        out.append(f"[coming up] {_wday(e['date'])}: {e['what']}.")
    return out


SUMMARY_PROMPT = (
    "You write the summary of a construction progress report that a general contractor sends "
    "to the owner or the lender. Write 5 to 8 sentences of plain construction language: what "
    "work was done on site, the key progress, any problems, and what is next. Use ONLY the "
    "facts given (each line is one fact and its source). Every number, date, name and company "
    "must come from them; do not add, estimate, compute or round anything. Never say "
    "\"man-days\", never a percentage, no headings, no bullet points, no greeting.")

_COMMON_CAPS = set("""
The This That These Those It Its On In At By For From With Work Workers Site Floor Floors
Next Open Late No New Busiest Average Up Upcoming Coming Daily DOB DOT Punch Mon Tue Wed Thu
Fri Sat Sun Monday Tuesday Wednesday Thursday Friday Saturday Sunday Jan Feb Mar Apr May Jun
Jul Aug Sep Oct Nov Dec January February March April June July August September October
November December During Over Across Overall Progress Several Both All Two Three Four Five
Six Seven Eight Nine Ten There We A An And Also Work Crews Crew Meanwhile However Some One
""".split())


_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"


def _numbers(text: str) -> Tuple[set, set]:
    """({(month, day), ...}, {count, ...}) in `text`: "Oct 15" is a date,
    "37 workers" / "fl 1–4" / "14.4" are counts."""
    days = {(m.group(1)[:3].lower(), m.group(2))
            for m in re.finditer(r"\b(" + _MONTH + r")\s+(\d{1,2})\b", text)}
    rest = re.sub(r"\b" + _MONTH + r"\s+\d{1,2}(?:\s*[–-]\s*\d{1,2}\b)?(?:,\s*\d{4})?", " ", text)
    # A record number's digits ("X01-…-A11") are not counts; "3rd" is 3.
    counts = set(re.findall(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)(?:st|nd|rd|th)?(?![A-Za-z0-9])", rest))
    return days, counts


def check_summary(text: Any, rep: Dict[str, Any]) -> bool:
    """The model's summary goes out only when it says nothing the facts do
    not: every number and every name in it is in them, 5-8 sentences,
    never "man-days" or a percentage."""
    t = " ".join(str(text or "").split())
    if not t or FORBIDDEN.search(t):
        return False
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    if not 4 <= len(sentences) <= 9:
        return False
    src = " ".join(facts(rep)) + " " + rep["job"] + " " + rep["period"]
    # A date's day goes with its month ("Oct 15"); any other number must be
    # one of the facts' own counts, not just digits seen somewhere in a date.
    days, counts = _numbers(src)
    t_days, t_counts = _numbers(t)
    if not t_days <= days or not t_counts <= counts:
        return False
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z&'’.-]*", src)}
    for w in re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][A-Za-z&'’-]+", t):
        if w not in _COMMON_CAPS and w.lower() not in words and w.lower().rstrip("s") not in words:
            return False
    return True


def summary_fallback(rep: Dict[str, Any]) -> str:
    """The summary from the records alone, when the model's does not pass."""
    s, site = rep["subs"], rep["site"]
    out = []
    if s:
        parts = [f"{x['label'].lower() if x['label'] else 'work on site'} ({x['name']})" for x in s[:5]]
        out.append(f"Work this period at {rep['job']}: " + _join(parts) + ".")
    if site["worked"]:
        out.append(f"The site was worked {site['worked']} of {site['possible']} working days, "
                   f"with an average of {site['avg']} workers on site a day; the busiest day was "
                   f"{_wday(site['max_day'])} with {site['max']}.")
    else:
        out.append("No one checked in on site in this period.")
    if rep["observations"]:
        o = rep["observations"][0]
        out.append(f"The daily log of {_day(o['date'])} notes: {o['text'].rstrip('.')}.")
    if rep["records"]:
        n = len(rep["records"])
        out.append(f"{n} new DOB/DOT record{'s were' if n != 1 else ' was'} issued for the job "
                   f"({', '.join(r['kind'] + ' ' + r['number'] for r in rep['records'][:3])}).")
    else:
        out.append("No new DOB or DOT records were issued for the job.")
    late, p = rep["late"], rep["punch"]
    if late or p.get("open"):
        bits = []
        if late:
            bits.append(f"{len(late)} commitment{'s are' if len(late) != 1 else ' is'} past due")
        if p.get("open"):
            bits.append(f"{p['open']} punch item{'s remain' if p['open'] != 1 else ' remains'} open")
        out.append(_join(bits).capitalize() + ".")
    if rep["coming_up"]:
        out.append("Coming up: " + _join([e["say"].rstrip(".") for e in rep["coming_up"][:2]]) + ".")
    return " ".join(out)


def _join(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1] if parts else ""


# ── THE REPORT ───────────────────────────────────────────────────────────────

def compute(*, job: str, address: str, gc: str, start: date, end: date, now: datetime,
            checkins: Iterable[dict] = (), logbooks: Iterable[dict] = (), chat: Iterable[dict] = (),
            records: Iterable[dict] = (), events: Iterable[dict] = (),
            commitments: Iterable[dict] = (), punch_items: Iterable[dict] = (),
            **_ignored: Any) -> Dict[str, Any]:
    """Everything of one job's report for [start, end], from its rows."""
    today = att.local_day(now) or end
    checkins, logbooks = list(checkins), list(logbooks)
    commitments = [dict(c) for c in commitments]
    punch_items = list(punch_items)
    acts = _log_activities(logbooks, start, end)
    observations = _log_observations(logbooks, start, end)
    talk = _chat(chat, start, end)
    late = _late_commitments(commitments, end)
    subs = _subs(checkins, acts, start, end, talk, commitments, punch_items, observations)
    for i, s in enumerate(subs):
        s["color"] = PALETTE[i % len(PALETTE)]
    nxt = max(end, today) + timedelta(days=1)
    return {
        "job": job_title(job), "job_full": job, "address": address, "gc": gc,
        "start": start, "end": end, "today": today, "generated": now,
        "period": base.period_label(start, end), "period_short": short_period(start, end, now),
        "subs": subs, "site": _site(subs, start, end, today), "observations": observations,
        "chat": talk, "records": base._records(list(records), start, end),
        "late": late, "punch": _punch_summary(punch_items),
        "coming_up": _coming_up(list(events), commitments, nxt, nxt + timedelta(days=UPCOMING_DAYS - 1)),
        # Daily-log photos only (never the group chat's or a walkthrough's).
        "photo_candidates": _named(photo_candidates(acts, start, end), subs),
        "photos": [], "summary": "",
    }


def _named(cands: List[Dict[str, Any]], subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each photo under its sub's name as the report says it ("Arkon" sent
    in the group is "Arkon Builders" of the check-ins and logs)."""
    keys = [s["key"] for s in subs]
    canon = canonical_keys(keys + [company_key(c["sub"]) for c in cands if c["sub"]])
    name = {s["key"]: s["name"] for s in subs}
    for c in cands:
        k = company_key(c["sub"])
        k = canon.get(k, k)
        if k in name:
            c["sub"] = name[k]
    return cands


# ── THE WHATSAPP MESSAGE ─────────────────────────────────────────────────────

def _is_issue(kind: str) -> bool:
    """A record that is something to fix (a violation, complaint, stop work
    order) -- not a permit or a status."""
    k = kind.lower()
    return not ("permit" in k or "status" in k)


def whatsapp_message(rep: Dict[str, Any], *, attached: bool = True, link: Optional[str] = None) -> str:
    """The short message the PDF goes with:

        588 Thomas S Boyland · Oct 2–15
        - Work this period: framing fl 1–4 (Arkon), risers (Quality Plumbing)
        - Site: worked 9 of 9 days · avg 26 workers/day · busiest Thu Oct 15 (37)
        - Open: 4 late commitments · 51 punch items
        Full report (PDF) attached.
    """
    lines = [f"{rep['job']} · {rep['period_short']}"]
    work = []
    for s in rep["subs"][:5]:
        w = (s["label"] or s["trade"] or "on site").split(" · ")[0]
        work.append(f"{w[:1].lower()}{w[1:]} ({short_name(s['name'], w)})")
    lines.append("- Work this period: " + (", ".join(work) if work else "no crews on site"))
    site = rep["site"]
    if site["worked"]:
        lines.append(f"- Site: worked {site['worked']} of {site['possible']} days · avg {site['avg']} "
                     f"workers/day · busiest {_wday(site['max_day'])} ({site['max']})")
    else:
        lines.append("- Site: no check-ins this period")
    bits = []
    if rep["late"]:
        bits.append(f"{len(rep['late'])} late commitment{'s' if len(rep['late']) != 1 else ''}")
    if rep["punch"].get("open"):
        bits.append(f"{rep['punch']['open']} punch item{'s' if rep['punch']['open'] != 1 else ''}")
    issues = [r for r in rep["records"] if r["open"] and _is_issue(r["kind"])]
    if issues:
        bits.append(f"{len(issues)} new DOB/DOT violation{'s' if len(issues) != 1 else ''}")
    lines.append("- Open: " + (" · ".join(bits) if bits else "nothing open"))
    if attached:
        lines.append(ATTACHED_LINE)
    elif link:
        lines.append(f"Full report (PDF): {link}")
    return "\n".join(lines)


# ── THE PDF (HTML for WeasyPrint) ────────────────────────────────────────────

CSS = """
@page { size: Letter; margin: 0.65in 0.6in 0.8in;
  @top-left { content: "HEADER"; font: 8pt Helvetica, Arial, sans-serif; color: #7a8599; }
  @bottom-left { content: "SOURCE"; font: 7.5pt Helvetica, Arial, sans-serif; color: #7a8599; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages);
                  font: 8pt Helvetica, Arial, sans-serif; color: #7a8599; } }
@page cover { margin: 0; @top-left { content: none; } @bottom-left { content: none; }
              @bottom-right { content: none; } }
body { font: 10pt/1.45 Helvetica, Arial, sans-serif; color: #1c2430; }
.cover { page: cover; height: 11in; position: relative; background: #1F3A5F; color: #fff; }
.cover .band { padding: 1.2in 0.8in 0; }
.cover .brand { font-weight: 800; letter-spacing: 3px; font-size: 13pt; opacity: .85; }
.cover .gc { margin-top: 1.6in; font-size: 13pt; font-weight: 600; opacity: .9; }
.cover h1 { font-size: 30pt; line-height: 1.15; margin: 10px 0 6px; }
.cover .addr { font-size: 12pt; opacity: .85; }
.cover .kind { margin-top: 28px; font-size: 11pt; letter-spacing: 2px; text-transform: uppercase; opacity: .8; }
.cover .period { font-size: 18pt; font-weight: 600; margin-top: 4px; }
.cover .prep { position: absolute; bottom: 0.8in; left: 0.8in; font-size: 9.5pt; opacity: .8; }
h2 { font-size: 14pt; color: #1F3A5F; margin: 0 0 8px; padding-bottom: 4px;
     border-bottom: 2px solid #1F3A5F; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 14px 0 4px; color: #1c2430; page-break-after: avoid; }
section { page-break-before: always; }
section.flow { page-break-before: auto; margin-top: 22px; }
p.lead { font-size: 11pt; line-height: 1.6; }
.kpis { display: flex; gap: 10px; margin: 14px 0 4px; }
.kpis div { flex: 1; border: 1px solid #d8dee8; border-radius: 6px; padding: 8px 10px; }
.kpis b { display: block; font-size: 16pt; color: #1F3A5F; }
.kpis span { font-size: 8.5pt; color: #5b6676; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; }
th, td { border-bottom: 1px solid #e3e7ee; padding: 4px 6px; text-align: left; font-size: 9pt;
         vertical-align: top; }
th { background: #f1f4f8; color: #3c4858; font-weight: 600; }
td.n, th.n { text-align: right; }
.sub { break-inside: avoid; page-break-inside: avoid; border: 1px solid #e3e7ee; border-radius: 6px;
       padding: 8px 12px; margin: 0 0 10px; }
.sub .head { display: flex; justify-content: space-between; align-items: baseline; }
.sub .name { font-weight: 700; font-size: 11pt; }
.sub .dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; }
.sub .meta { color: #5b6676; font-size: 9pt; }
ul { margin: 4px 0 4px 16px; padding: 0; } li { margin: 2px 0; }
.issues li { color: #8a1c1c; }
table.photos { table-layout: fixed; margin: 0 0 4px; }
table.photos tr { break-inside: avoid; page-break-inside: avoid; }
td.photo { width: 50%; border: none; padding: 0 6px 10px 0; }
.photo img { width: 100%; height: 1.9in; object-fit: cover; border-radius: 4px; }
.photo .cap { font-size: 8.5pt; color: #3c4858; margin-top: 3px; }
.photo .cap b { color: #1c2430; }
.tag { display: inline-block; font-size: 7.5pt; padding: 1px 5px; border-radius: 3px;
       background: #eef2f7; color: #3c4858; margin-left: 4px; }
.none { color: #5b6676; font-style: italic; }
.muted { color: #5b6676; font-size: 8.5pt; }
.chart { width: 100%; }
.keep { break-inside: avoid; page-break-inside: avoid; }
"""


def gantt_svg(rep: Dict[str, Any], width: int = 700) -> str:
    """"Actual work (from daily logs)": a row per sub, a bar for each run of
    days it was on site, labelled with the work; a line at today."""
    subs, start, end = rep["subs"], rep["start"], rep["end"]
    if not subs:
        return ""
    ndays = (end - start).days + 1
    left, top, row_h = 150, 26, 34
    plot = width - left - 10
    dw = plot / ndays
    height = top + row_h * len(subs) + 24
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="chart" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif">']
    for i in range(ndays):
        d = start + timedelta(days=i)
        x = left + i * dw
        if d.weekday() >= 5:
            out.append(f'<rect x="{x:.1f}" y="{top}" width="{dw:.1f}" height="{row_h * len(subs)}" fill="#f4f6f9"/>')
        if ndays <= 31 or d.weekday() == 0:
            out.append(f'<text x="{x + dw / 2:.1f}" y="{top - 8}" font-size="8" text-anchor="middle" '
                       f'fill="#5b6676">{_fmt(d, "%-m/%-d")}</text>')
    for r, s in enumerate(subs):
        y = top + r * row_h
        out.append(f'<line x1="0" y1="{y + row_h}" x2="{width}" y2="{y + row_h}" stroke="#e3e7ee"/>')
        out.append(f'<text x="4" y="{y + row_h / 2 + 4}" font-size="9.5" font-weight="bold" '
                   f'fill="#1c2430">{_e(s["name"][:22])}</text>')
        for run in s["runs"]:
            x = left + (run["start"] - start).days * dw
            w = ((run["end"] - run["start"]).days + 1) * dw
            out.append(f'<rect x="{x + 1:.1f}" y="{y + 6}" width="{max(w - 2, 3):.1f}" height="{row_h - 12}" '
                       f'rx="3" fill="{s["color"]}"/>')
            label = run["label"] or s["trade"] or ""
            if label:
                fits = int(w / 5.2)
                txt = label if len(label) <= fits else (label[:max(fits - 1, 0)] + "…" if fits > 6 else "")
                if txt:
                    out.append(f'<text x="{x + 5:.1f}" y="{y + row_h / 2 + 3.5}" font-size="8.5" '
                               f'fill="#fff">{_e(txt)}</text>')
    today = rep["today"]
    if start <= today <= end:
        x = left + ((today - start).days + 0.5) * dw
        out.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{top + row_h * len(subs)}" '
                   f'stroke="#C8102E" stroke-width="1.5" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{x:.1f}" y="{height - 6}" font-size="8.5" text-anchor="middle" '
                   f'fill="#C8102E">Today</text>')
    out.append("</svg>")
    return "".join(out)


def activity_svg(rep: Dict[str, Any], width: int = 700, height: int = 200) -> str:
    """Workers on site per day, stacked by sub, the total on top."""
    table, subs = rep["site"]["table"], rep["subs"]
    if not table:
        return ""
    top_v = max(r["total"] for r in table) or 1
    n = len(table)
    left, base_y = 30, height - 26
    bw = max(6, (width - left - 10) / n - 6)
    color = {s["name"]: s["color"] for s in subs}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="chart" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif">']
    for i, r in enumerate(table):
        x = left + i * (bw + 6)
        y = base_y
        for s in subs:
            v = r["by_sub"].get(s["name"], 0)
            if not v:
                continue
            h = (base_y - 18) * v / top_v
            y -= h
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{color[s["name"]]}"/>')
        out.append(f'<text x="{x + bw / 2:.1f}" y="{y - 3:.1f}" font-size="8.5" text-anchor="middle" '
                   f'fill="#1c2430">{r["total"]}</text>')
        out.append(f'<text x="{x + bw / 2:.1f}" y="{base_y + 12}" font-size="8" text-anchor="middle" '
                   f'fill="#5b6676">{_fmt(r["day"], "%-m/%-d")}</text>')
    out.append(f'<line x1="{left - 4}" y1="{base_y}" x2="{width}" y2="{base_y}" stroke="#9aa5b4"/>')
    out.append("</svg>")
    legend = "".join(f'<span style="margin-right:12px"><span class="dot" style="display:inline-block;'
                     f'width:9px;height:9px;border-radius:2px;background:{s["color"]}"></span> '
                     f'{_e(s["name"])}</span>' for s in subs)
    return "".join(out) + f'<div class="muted">{legend}</div>'


def _cover(rep: Dict[str, Any], prepared: str) -> str:
    return (f"<div class='cover'><div class='band'><div class='brand'>LEVELOG</div>"
            f"<div class='gc'>{_e(rep['gc'])}</div>"
            f"<h1>{_e(rep['job_full'])}</h1><div class='addr'>{_e(rep['address'])}</div>"
            f"<div class='kind'>Construction progress report</div>"
            f"<div class='period'>{_e(rep['period'])}</div></div>"
            f"<div class='prep'>Prepared {_e(prepared)} · {_e(SOURCE_LINE)}</div></div>")


def _summary_section(rep: Dict[str, Any]) -> str:
    site = rep["site"]
    k = []
    if site["worked"]:
        k = [("Days on site", f"{site['worked']} of {site['possible']}"),
             ("Workers on site / day", f"{site['avg']} avg"),
             ("Busiest day", f"{site['max']} · {_day(site['max_day'])}")]
    k.append(("Subs on site", str(len(rep["subs"]))))
    kp = "".join(f"<div><b>{_e(v)}</b><span>{_e(lbl)}</span></div>" for lbl, v in k)
    return (f"<section class='first'><h2>Summary</h2><p class='lead'>{_e(rep['summary'])}</p>"
            f"<div class='kpis'>{kp}</div></section>")


def _schedule_section(rep: Dict[str, Any]) -> str:
    g = gantt_svg(rep)
    body = g or "<p class='none'>No crews on site in this period.</p>"
    return (f"<section class='flow keep'><h2>Actual work (from daily logs)</h2>{body}"
            f"<div class='muted'>Bars are the days each sub was on site (check-ins); labels are the work "
            f"written in the daily logs. No planned dates — no schedule is on file.</div></section>")


def _subs_section(rep: Dict[str, Any]) -> str:
    if not rep["subs"]:
        return "<section><h2>Work by sub</h2><p class='none'>None.</p></section>"
    cards = []
    for s in rep["subs"]:
        work = ("<ul>" + "".join(f"<li>{_e(w)}</li>" for w in s["work"]) + "</ul>") if s["work"] \
            else "<div class='none'>No work description in the daily logs.</div>"
        issues = ("<b>Issues</b><ul class='issues'>" + "".join(f"<li>{_e(i)}</li>" for i in s["issues"])
                  + "</ul>") if s["issues"] else ""
        cards.append(
            f"<div class='sub'><div class='head'><span class='name'><span class='dot' "
            f"style='background:{s['color']}'></span>{_e(s['name'])}"
            f"{('<span class=tag>' + _e(s['trade']) + '</span>') if s['trade'] else ''}</span>"
            f"<span class='meta'>{len(s['days'])} days on site · {_e(_span(s['first'], s['last']))}"
            f" · avg {s['avg']:g}, most {s['max']} workers</span></div>"
            f"{work}{issues}</div>")
    return "<section><h2>Work by sub</h2>" + "".join(cards) + "</section>"


def _photos_section(rep: Dict[str, Any], images: Dict[str, str]) -> str:
    shown = [p for p in rep["photos"] if images.get(p["key"])]
    if not shown:
        return ("<section><h2>Progress photos</h2><p class='none'>No progress photos in the daily "
                "logs for this period.</p></section>")
    groups: Dict[str, List[dict]] = defaultdict(list)
    for p in shown:
        groups[p.get("sub") or "Daily log"].append(p)
    out = ["<section><h2>Progress photos</h2><div class='muted'>From the daily logs: each photo "
           "dated, with the sub's work that day.</div>"]
    for sub, photos in groups.items():
        cells = []
        for p in sorted(photos, key=lambda x: x["date"]):
            pair = (f"<span class='tag'>{'Earliest' if p['pair'] == 'before' else 'Latest'}</span>"
                    if p.get("pair") else "")
            cells.append(f"<td class='photo'><img src='{images[p['key']]}'/>"
                         f"<div class='cap'><b>{_e(_wday(p['date']))}</b>{pair}<br>"
                         f"{_e(p['caption'])}</div></td>")
        rows = "".join("<tr>" + "".join(cells[i:i + 2]) + ("<td class='photo'></td>" if len(cells[i:i + 2]) < 2
                                                            else "") + "</tr>"
                       for i in range(0, len(cells), 2))
        out.append(f"<h3>{_e(sub)}</h3><table class='photos'>{rows}</table>")
    return "".join(out) + "</section>"


def _activity_section(rep: Dict[str, Any]) -> str:
    site = rep["site"]
    if not site["worked"]:
        return "<section class='flow'><h2>Site activity</h2><p class='none'>No check-ins.</p></section>"
    rows = "".join(f"<tr><td>{_e(s['name'])}</td><td class='n'>{len(s['days'])}</td>"
                   f"<td class='n'>{s['avg']:g}</td><td class='n'>{s['max']}</td></tr>" for s in rep["subs"])
    return (f"<section><h2>Site activity</h2>"
            f"<h3>Workers on site per day</h3>{activity_svg(rep)}"
            f"<p>Worked {site['worked']} of {site['possible']} working days · average {site['avg']} "
            f"workers on site a day · busiest {_e(_wday(site['max_day']))} ({site['max']}).</p>"
            f"<table><tr><th>Sub</th><th class='n'>Days on site</th><th class='n'>Avg workers</th>"
            f"<th class='n'>Most workers</th></tr>{rows}</table>"
            f"<div class='muted'>Each worker counted once a day, from site check-ins.</div></section>")


def _dob_section(rep: Dict[str, Any]) -> str:
    recs = rep["records"]
    body = ("<table><tr><th>Type</th><th>Number</th><th>Date</th><th>Status</th></tr>"
            + "".join(f"<tr><td>{_e(r['kind'])}</td><td>{_e(r['number'])}</td><td>{_e(_day(r['date']))}</td>"
                      f"<td>{_e(r['status'])}</td></tr>" for r in recs) + "</table>") if recs \
        else "<p class='none'>None — no new DOB or DOT records this period.</p>"
    return f"<section class='flow keep'><h2>DOB / DOT</h2>{body}</section>"


def _open_section(rep: Dict[str, Any]) -> str:
    late = rep["late"]
    lt = ("<table><tr><th>Who</th><th>What</th><th>Due</th><th>Since</th></tr>"
          + "".join(f"<tr><td>{_e(c['who'])}</td><td>{_e(c['what'])}</td><td>{_e(_day(c['due']))}"
                    f" <span class='muted'>({c['days_late']} days late)</span></td>"
                    f"<td>{_e(_day(c['since']))}</td></tr>" for c in late) + "</table>") if late \
        else "<p class='none'>None.</p>"
    p = rep["punch"]
    pt = ("<p>{} open · {} ready to check · {} closed.</p>".format(p["open"], p["ready"], p["closed"])
          + "<table><tr><th>Assigned to</th><th class='n'>Open</th><th class='n'>Ready to check</th>"
          "<th class='n'>Closed</th></tr>"
          + "".join(f"<tr><td>{_e(a['name'])}</td><td class='n'>{a['open']}</td><td class='n'>{a['ready']}</td>"
                    f"<td class='n'>{a['closed']}</td></tr>" for a in p["by_assignee"]) + "</table>") if p \
        else "<p class='none'>None.</p>"
    return (f"<section><h2>Open items</h2><h3>Late commitments</h3>{lt}"
            f"<h3>Punch list</h3>{pt}</section>")


def _next_section(rep: Dict[str, Any]) -> str:
    up = rep["coming_up"]
    body = ("<ul>" + "".join(f"<li><b>{_e(_wday(e['date']))}</b>{(' ' + _e(e['time'])) if e['time'] else ''}"
                             f" — {_e(e['what'])}</li>" for e in up) + "</ul>") if up \
        else "<p class='none'>Nothing scheduled in the records for the next 2 weeks.</p>"
    return f"<section class='flow keep'><h2>Coming up (next 2 weeks)</h2>{body}</section>"


def render_html(reps: List[Dict[str, Any]], *, gc: str, title: str, now: datetime,
                images: Optional[Dict[str, str]] = None) -> str:
    """The PDF's HTML: per job a cover and the eight sections; page numbers,
    the job in the page header, the source line in the footer. `images`:
    photo key -> data URI (the server fetches them)."""
    images = images or {}
    prepared = _fmt(now.astimezone(NY), "%B %-d, %Y")
    head = f"{reps[0]['job']} · {reps[0]['period']}" if len(reps) == 1 else title
    css = (CSS.replace('"HEADER"', '"' + head.replace('"', "'") + '"')
           .replace('"SOURCE"', '"' + SOURCE_LINE + '"'))
    body = []
    for rep in reps:
        body.append(_cover(rep, prepared) + _summary_section(rep) + _schedule_section(rep)
                    + _subs_section(rep) + _photos_section(rep, images) + _activity_section(rep)
                    + _dob_section(rep) + _open_section(rep) + _next_section(rep))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(body)}</body></html>")


def title_for(reps: List[Dict[str, Any]]) -> str:
    if len(reps) == 1:
        return f"Progress report — {reps[0]['job']} — {reps[0]['period']}"
    return f"Progress report — {len(reps)} jobs — {reps[0]['period']}"


def text_outline(rep: Dict[str, Any]) -> str:
    """The report as plain text (the snapshot, and what the app previews)."""
    out = [f"{rep['job_full']} — {rep['period']}", "", "SUMMARY", rep["summary"], "",
           "ACTUAL WORK (FROM DAILY LOGS)"]
    for s in rep["subs"]:
        bars = "; ".join(f"{_span(r['start'], r['end'])}: {r['label'] or s['trade'] or 'on site'}"
                         for r in s["runs"])
        out.append(f"  {s['name']}: {bars}")
    out += ["", "WORK BY SUB"]
    for s in rep["subs"]:
        out.append(f"  {s['name']} — {len(s['days'])} days on site ({_span(s['first'], s['last'])}), "
                   f"avg {s['avg']:g}, most {s['max']} workers")
        out += [f"    - {w}" for w in s["work"]] or ["    - No work description in the daily logs."]
        out += [f"    ! {i}" for i in s["issues"]]
    out += ["", "PROGRESS PHOTOS"]
    out += [f"  {p['sub']} · {_wday(p['date'])} — {p['caption']}"
            f"{' [' + p['pair'] + ']' if p.get('pair') else ''}" for p in rep["photos"]] or ["  None."]
    site = rep["site"]
    out += ["", "SITE ACTIVITY"]
    out += ([f"  Worked {site['worked']} of {site['possible']} working days · avg {site['avg']} workers/day"
             f" · busiest {_wday(site['max_day'])} ({site['max']})"]
            + [f"  {_wday(r['day'])}: {r['total']} ("
               + ", ".join(f"{k} {v}" for k, v in sorted(r["by_sub"].items(), key=lambda kv: -kv[1])) + ")"
               for r in site["table"]]) if site["worked"] else ["  No check-ins."]
    out += ["", "DOB / DOT"]
    out += [f"  {r['kind']} {r['number']} — {_day(r['date'])} — {r['status']}" for r in rep["records"]] or ["  None."]
    out += ["", "OPEN ITEMS", "  Late commitments:"]
    out += [f"    {c['who']}: {c['what']} — due {_day(c['due'])} ({c['days_late']} days late), since "
            f"{_day(c['since'])}" for c in rep["late"]] or ["    None."]
    p = rep["punch"]
    out.append(f"  Punch: {p['open']} open, {p['ready']} ready to check, {p['closed']} closed" if p else "  Punch: none")
    out += [f"    {a['name']}: {a['open']} open, {a['ready']} ready, {a['closed']} closed" for a in p.get("by_assignee", [])]
    out += ["", "COMING UP (NEXT 2 WEEKS)"]
    out += [f"  {_wday(e['date'])}{' ' + e['time'] if e['time'] else ''} — {e['what']}"
            for e in rep["coming_up"]] or ["  Nothing scheduled."]
    return "\n".join(out)
