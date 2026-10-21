"""The project progress report: one document for a GC, an owner, a developer,
an investor and a lender.

Plain construction language, evidence only. Every statement is built from a
record the server read for the job and the period, and says which kind of
record it came from:

  G  gate check-ins          who was on site, which days (independent of any log)
  L  filed daily logs        what each crew reported doing, where, with photos
  R  DOB / DOT records       the city's own record, with its number and link
  S  project schedule        a schedule a person imported and confirmed
  F  financial figures       figures a person provided and confirmed

Nothing is estimated and nothing is generated: the overview and the changes
since the previous period are composed from the numbers below by fixed
templates, so every sentence can be traced to a line of the evidence index.
A section with nothing in it is left out or reduced to one honest line.

WHAT IS DELIBERATELY NOT IN THIS REPORT (and why)
  * WhatsApp chat, commitments, chasing, reminders. They are internal to the
    GC, model-extracted and (the attention engine) unreviewed; an owner or
    lender reads "late commitment" as a project risk. Chat text is no longer
    sent to a model for this report either.
  * The punch list and walkthrough observations: assignments to named people
    on the GC's own team are internal; their statuses were also read as of
    today, not as of the period.
  * Individual workers: counts by sub only.
  * Free-text site observations: unclassified and potentially personal. The
    structured daily inspections (pass / fail per item) are included.
  * A percent complete derived from manpower, log wording or photographs. A
    percent appears only when the schedule file itself reports it (lib/
    schedule_plan.py), attributed to that file and its data date.
  * Any financial figure that was not provided and confirmed.

PERIOD-AWARE, NOT PERIOD-SPECIFIC. Weekly, bi-weekly, monthly, quarterly and
custom reports are the same report. The period changes only the granularity
of the charts (days, weeks, months) and, through the previous period of the
same length, what "changed" means.

Pure: no database, no network, no model. server.py reads the rows, screens
the photos with the vision model, and renders the PDF with WeasyPrint.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import attendance as att
from lib import project_report as base
from lib import report_calendar, report_regulatory
from lib.datefmt import strftime as _fmt

NY = base.NY
ENGINE_VERSION = "2026.10.2"
UPCOMING_DAYS = 30
#: 4-6 photographs, never more: a few good ones, not a gallery.
MIN_PHOTOS, MAX_PHOTOS = 4, 8
MAX_PER_SUB = 2
#: A photograph must show installed work STRONGLY to appear: fewer than four
#: photographs is better than a weak one used to fill the page.
MIN_SCORE = 6.0
ATTACHED_LINE = "Full report (PDF) attached."
SOURCE_LINE = "Source: Levelog records — site check-ins, filed daily logs, DOB/DOT records"

#: A sub's headcount "changed" when its average moved at least this much AND
#: at least this many workers; a whole-site change uses the same rule.
CHANGE_PCT = 0.30
CHANGE_WORKERS = 3
WORKFORCE_NOTE_PCT = 0.15
#: Gate and log headcount "agree" within this many workers or this share.
AGREE_WORKERS = 1
AGREE_PCT = 0.25

#: Never in the report.
FORBIDDEN = re.compile(r"man[- ]?days?|\d+\s?%|percent", re.IGNORECASE)

#: Colors for the subs (charts), in order.
PALETTE = ["#1F3A5F", "#2A7F8E", "#6B5B95", "#B7791F", "#3F7D58", "#5B7083", "#8D6E63",
           "#4C5FB5", "#8E4585", "#8A8D2F"]

_UNASSIGNED = {"unassigned", "no company", "pending assignment", "unknown", "none", "n a"}


# ── SMALL THINGS ─────────────────────────────────────────────────────────────

def _day(d: Optional[date]) -> str:
    return _fmt(d, "%b %-d") if d else ""


def _dayy(d: Optional[date]) -> str:
    return _fmt(d, "%b %-d, %Y") if d else ""


def _wday(d: date) -> str:
    return _fmt(d, "%a %b %-d")


def _span(a: date, b: date) -> str:
    """"Oct 2", "Oct 2–15", "Sep 28–Oct 3"."""
    if a == b:
        return _day(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{_day(a)}–{b.day}"
    return f"{_day(a)}–{_day(b)}"


def _n(n: int, word: str, plural: Optional[str] = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _join(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _fold(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def _e_phone(v: Any) -> str:
    return base.no_phone(v)


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


def is_unassigned(name: Any) -> bool:
    """A check-in or log row with no real company: "UNASSIGNED", "No
    company", a blank. Counted in the site's headcount, never shown as a sub."""
    return _fold(name) in _UNASSIGNED or not _fold(name)


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
    """[1, 2, 3, 4] -> "floors 1–4"; [2, 5] -> "floors 2, 5"; [3] -> "floor 3"."""
    fs = sorted(set(floors))
    if not fs:
        return ""
    if len(fs) == 1:
        return f"floor {fs[0]}"
    if fs == list(range(fs[0], fs[-1] + 1)):
        return f"floors {fs[0]}–{fs[-1]}"
    return "floors " + ", ".join(str(f) for f in fs)


def _clean_work(text: Any) -> str:
    """A crew's work description, as one short phrase: "Framing", "Riser
    install" (never the floors -- they go after it)."""
    t = " ".join(str(text or "").split()).strip(" .;,-")
    t = _FLOOR.sub("", t)
    t = re.sub(r"\s+(?:on|at|in)\s*$", "", t.strip(" .;,-"))
    t = re.sub(r"\s{2,}", " ", t).strip(" .;,-")
    return (t[:1].upper() + t[1:]) if t else ""


def _one_edit(a: str, b: str) -> bool:
    """Exactly one substitution, insertion, deletion or swap apart."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


#: Words a construction log uses constantly. A misspelling is mended toward
#: these as well as toward the logs' own frequent words (a crew that writes
#: "wite" once and "wire" never would otherwise keep its typo).
_VOCAB = frozenset("""wire wiring electrical electric conduit switchgear panel plumbing plumber pipe pipes piping riser
risers fixtures fixture framing studs track drywall sheetrock insulation sprinkler sprinklers ductwork duct ducts hvac
scaffold scaffolding stairs stair railing concrete slab rebar formwork shoring sheathing masonry brick demolition
cleaning install installed installation rough finish testing pressure domestic water sanitary drain drains fire
alarm lighting fixtures cables cable pulling hangers anchors welding bolting steel beams columns decking roofing
waterproofing windows doors painting taping spackle flooring tile layout inspection mobilization""".split())


#: Real short words that sit one edit from a vocabulary word ("wide" / "wire"):
#: never "corrected".
_REAL_WORDS = frozenset("""wide wipe wise wine wore tile pile pale pole pose post poor door fire hire tire core care
bore base case cast cost last list lift loft soft roof room tube tune cube dust just must rust bust beam beams team
seam seat heat head load road lead leak lean mean meat neat wall well will wind wing wood wool word work worn""".split())


def spelling_fixes(texts: Iterable[str]) -> Dict[str, str]:
    """Misspellings in the logs' own wording ("wite", "eletrical"), mended from
    the logs' own vocabulary: a word seen once, one edit from a word the same
    logs use three or more times. Never from a dictionary the logs do not use,
    and never a plural or other suffix of a word ("risers" stays)."""
    count: Counter = Counter(w for t in texts for w in re.findall(r"[a-z]{4,}", str(t).lower()))
    common = sorted({w for w, c in count.items() if c >= 3} | set(_VOCAB))
    fixes: Dict[str, str] = {}
    for w, c in count.items():
        if c > 2 or w in _VOCAB or w in _REAL_WORDS:
            continue
        hits = [x for x in common if _one_edit(w, x) and not (x.startswith(w) or w.startswith(x))]
        if c == 2:                      # a word used twice is mended only toward the curated vocabulary
            hits = [x for x in hits if x in _VOCAB]
        if len(hits) == 1:
            fixes[w] = hits[0]
    return fixes


def _apply_fixes(text: str, fixes: Dict[str, str]) -> str:
    if not fixes or not text:
        return text

    def swap(m):
        w = m.group(0)
        to = fixes.get(w.lower())
        if not to:
            return w
        return to.capitalize() if w[:1].isupper() else to
    return re.sub(r"[A-Za-z]{4,}", swap, text)


# ── THE LOGS: ONE EFFECTIVE RECORD PER DAY ───────────────────────────────────

def effective_logs(logs: Iterable[dict]) -> Dict[str, Any]:
    """The filed daily logs as the report must read them.

    `logs` are the CHAIN HEADS the server picked (server.collapse_amendment_
    chains: the original until an amendment is signed and filed, then the
    amendment; a withdrawn or unsigned amendment never wins) -- the same rule
    the daily report and the inspector's list use, so the three cannot
    disagree about a corrected day. They carry `_chain_length` (>1: amended),
    `_competing` (filed corrections on a fork) and `_amendment_reason`.

    The OLD reader excluded every amendment, so a correction the Competent
    Person had signed never reached the report: the lender read what the CP
    had formally corrected. Here an amended day is read from its amendment
    and marked, and the appendix says so.

    Two heads for one date that are not a chain (a day filed twice) are one
    day: the one filed last is used and the duplicate counted."""
    by_date: Dict[date, List[dict]] = defaultdict(list)
    for lg in logs:
        d = base._d(lg.get("date"))
        if d:
            by_date[d].append(lg)
    items: List[dict] = []
    duplicates = 0

    def stamp(lg: dict) -> str:
        v = lg.get("updated_at") or lg.get("created_at")
        return v.isoformat() if isinstance(v, datetime) else str(v or "")
    for d in sorted(by_date):
        rows = sorted(by_date[d], key=lambda lg: (stamp(lg), str(lg.get("_id") or "")))
        duplicates += len(rows) - 1
        items.append(rows[-1])
    amended = [base._d(lg.get("date")) for lg in items if int(lg.get("_chain_length") or 1) > 1]
    return {"items": items, "duplicates": duplicates, "amended": amended,
            "competing": sum(int(lg.get("_competing") or 0) for lg in items)}


def _log_activities(logs: Iterable[dict], start: date, end: date) -> List[Dict[str, Any]]:
    """Every crew row of the effective daily logs in [start, end]: {date,
    company, key, trade, workers, work, where, floors, photos, log, amended}.
    A row with no company is kept (its crew and photos are real) and marked
    `key == ""`: counted in the site total, never shown as a sub."""
    out = []
    for lg in logs:
        d = base._d(lg.get("date"))
        if not base._in(d, start, end):
            continue
        amended = int(lg.get("_chain_length") or 1) > 1
        for slot, a in enumerate((lg.get("data") or {}).get("activities") or []):
            if not isinstance(a, dict):
                continue
            company = " ".join(str(a.get("company") or "").split())
            where = " ".join(str(a.get("work_locations") or "").split())
            work = _clean_work(a.get("work_description"))
            try:
                workers = int(a.get("num_workers") or 0)
            except (TypeError, ValueError):
                workers = 0
            key = "" if is_unassigned(company) else company_key(company)
            out.append({"date": d, "company": company, "log": f"{lg.get('_id') or d}:{slot}",
                        "log_id": str(lg.get("_id") or ""), "key": key,
                        "trade": str(a.get("trade") or "").strip(), "workers": workers, "work": work,
                        "where": where, "floors": floors_in(where) or floors_in(a.get("work_description")),
                        "photos": [p for p in (a.get("photos") or []) if isinstance(p, dict)],
                        "amended": amended})
    return out


_INSPECTION_LABEL = {"street_frontage": "Street frontage", "fire_safety": "Fire safety",
                     "perimeter_fence": "Perimeter fence", "fall_protections": "Fall protection",
                     "neighbors_property": "Neighboring property", "license_spot_check": "License spot-check",
                     "plans": "Plans on site", "permits": "Permits posted", "other": "Other"}
_PASS, _FAIL = {"pass", "passed", "ok"}, {"fail", "failed"}


def inspections(logs: Iterable[dict], start: date, end: date) -> Dict[str, Any]:
    """The daily inspection items (pass / fail / not walked) of the effective
    logs in the period: STRUCTURED facts, no free text. -> {"days", "walked",
    "passed", "failed", "failed_items": [{date, item}]}."""
    days = walked = passed = 0
    failed_items: List[Dict[str, Any]] = []
    for lg in logs:
        d = base._d(lg.get("date"))
        if not base._in(d, start, end):
            continue
        items = (lg.get("data") or {}).get("checklist_items") or {}
        results = [(k, str((v or {}).get("result") or "").strip().lower()) for k, v in items.items()
                   if isinstance(v, dict)]
        day_walked = [(k, r) for k, r in results if r in _PASS | _FAIL]
        if not day_walked:
            continue
        days += 1
        walked += len(day_walked)
        for k, r in day_walked:
            if r in _PASS:
                passed += 1
            else:
                failed_items.append({"date": d, "item": _INSPECTION_LABEL.get(k, k.replace("_", " ").capitalize())})
    failed_items.sort(key=lambda x: x["date"], reverse=True)
    return {"days": days, "walked": walked, "passed": passed, "failed": len(failed_items),
            "failed_items": failed_items[:6]}


# ── WHO WAS ON SITE: THE GATE AND THE LOGS, TOGETHER ────────────────────────

def _window(days_map: Dict[date, Dict[str, set]], acts: List[Dict[str, Any]], canon: Dict[str, str],
            start: date, end: date, log_days: set) -> Dict[str, Any]:
    """One window's workforce: per sub per day the count from the GATE, else
    from the daily log (`basis`), the gate-vs-log comparison, and the site
    total per day.

    A sub's day is a day it has gate check-ins OR a crew row in a filed log.
    The headcount is the gate's whenever the gate saw anyone (the gate does
    not depend on anyone remembering to write it down); a day known only from
    the log is counted from the log and marked, and the appendix says how
    many there were. Where both exist and differ by more than AGREE_*, the
    day is a variance and is counted, never averaged away."""
    per: Dict[str, Dict[str, Any]] = {}
    unassigned: Dict[date, int] = defaultdict(int)

    def sub(k: str, name: str) -> Dict[str, Any]:
        s = per.setdefault(k, {"key": k, "names": Counter(), "trades": Counter(), "days": {}})
        s["names"][name] += 1
        return s
    for d, by_co in days_map.items():
        if not base._in(d, start, end):
            continue
        for co, workers in by_co.items():
            if is_unassigned(co):
                unassigned[d] += len(workers)
                continue
            k = company_key(co)
            k = canon.get(k, k)
            s = sub(k, co)
            e = s["days"].setdefault(d, {"gate": 0, "log": 0, "log_rows": 0})
            e["gate"] += len(workers)
    log_rows_no_company: Dict[date, int] = defaultdict(int)
    for a in acts:
        if not base._in(a["date"], start, end):
            continue
        if not a["key"]:
            log_rows_no_company[a["date"]] += 1
            continue
        k = canon.get(a["key"], a["key"])
        s = sub(k, a["company"])
        if a["trade"]:
            s["trades"][a["trade"]] += 1
        e = s["days"].setdefault(a["date"], {"gate": 0, "log": 0, "log_rows": 0})
        e["log"] = max(e["log"], a["workers"]) if e["log_rows"] else a["workers"]
        e["log_rows"] += 1
    totals: Dict[date, int] = defaultdict(int)
    recon = {"aligned": 0, "variance": 0, "gate_only": 0, "log_only": 0, "no_log_day": 0, "log_basis_days": 0}
    variance_days: List[Dict[str, Any]] = []
    for s in per.values():
        for d, e in s["days"].items():
            gate, log = e["gate"], e["log"]
            if gate:
                e["count"], e["basis"] = gate, "gate"
            else:
                e["count"], e["basis"] = log, "log"
                if log:
                    recon["log_basis_days"] += 1
            if not e["count"] and not e["log_rows"] and not gate:
                continue
            totals[d] += e["count"]
            if gate and e["log_rows"]:
                if abs(gate - log) <= max(AGREE_WORKERS, round(AGREE_PCT * max(gate, log))):
                    recon["aligned"] += 1
                else:
                    recon["variance"] += 1
                    variance_days.append({"date": d, "sub": s["names"].most_common(1)[0][0],
                                          "gate": gate, "log": log})
            elif gate and d in log_days:
                recon["gate_only"] += 1
            elif gate:
                recon["no_log_day"] += 1
            elif e["log_rows"]:
                recon["log_only"] += 1
    for d, n in unassigned.items():
        totals[d] += n
    worked = sorted(d for d, n in totals.items() if n > 0)
    return {"per": per, "totals": dict(totals), "worked": worked, "unassigned": dict(unassigned),
            "recon": recon, "variance_days": sorted(variance_days, key=lambda v: v["date"]),
            "log_rows_no_company": sum(log_rows_no_company.values())}


def _stats(totals: Dict[date, int], worked: List[date]) -> Dict[str, Any]:
    if not worked:
        return {"days": 0, "avg": 0.0, "peak": 0, "peak_day": None}
    vals = [totals[d] for d in worked]
    top = max(vals)
    return {"days": len(worked), "avg": round(sum(vals) / len(vals), 1), "peak": top,
            "peak_day": next(d for d in worked if totals[d] == top)}


def _sub_rows(win: Dict[str, Any], prev: Dict[str, Any], canon_names: Dict[str, str]) -> List[Dict[str, Any]]:
    out = []
    for k, s in win["per"].items():
        counted = {d: e["count"] for d, e in s["days"].items() if e["count"] > 0}
        if not counted:
            continue
        ds = sorted(counted)
        vals = list(counted.values())
        p = prev["per"].get(k)
        pcounts = [e["count"] for e in (p["days"].values() if p else []) if e["count"] > 0]
        out.append({"key": k, "name": canon_names.get(k) or s["names"].most_common(1)[0][0],
                    "trade": s["trades"].most_common(1)[0][0] if s["trades"] else "",
                    "days": ds, "counts": counted, "avg": round(sum(vals) / len(vals), 1), "max": max(vals),
                    "first": ds[0], "last": ds[-1],
                    "log_days": sum(1 for d in ds if s["days"][d]["basis"] == "log"),
                    "prev_days": len(pcounts),
                    "prev_avg": round(sum(pcounts) / len(pcounts), 1) if pcounts else 0.0})
    out.sort(key=lambda r: (-len(r["days"]), -r["max"], r["name"]))
    return out


# ── THE WORK: BY TRADE AND FLOOR, AGAINST THE PREVIOUS PERIOD ────────────────

_PHRASE_SPLIT = re.compile(r"\s*(?:,|;|\s\+\s|\s&\s|\band\b)\s*", re.IGNORECASE)
_PHRASE_NOISE = frozenset({"install", "installation", "installing", "installed", "work", "works", "the", "of"})


def work_phrases(text: Any) -> List[str]:
    """The separate activities one log line names: "Electrical wiring, pulling
    wire" -> two. Commas inside parentheses stay ("Framing (layout, track and
    studs)" is one)."""
    t, depth, cur, parts = str(text or ""), 0, [], []
    for ch in t:
        depth += (ch == "(") - (ch == ")")
        if ch in ",;" and depth <= 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    out = []
    for part in parts:
        for piece in ([part] if "(" in part else _PHRASE_SPLIT.split(part)):
            piece = " ".join(piece.split()).strip(" .;,-")
            if piece:
                out.append(piece[:1].upper() + piece[1:])
    return out


def _phrase_key(phrase: str) -> str:
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", phrase.lower()).split() if w not in _PHRASE_NOISE]
    return " ".join(words)


def lc_first(text: str) -> str:
    """Lowercase the first letter of a phrase for use mid-sentence -- unless it
    starts with an acronym (MEP, HVAC, CMU)."""
    first = text.split(" ", 1)[0]
    return text if (len(first) > 1 and first[:2].isupper()) else text[:1].lower() + text[1:]


def _work(cur: List[Dict[str, Any]], prev: List[Dict[str, Any]], canon: Dict[str, str],
          subs: List[Dict[str, Any]], comparable: bool = True) -> List[Dict[str, Any]]:
    """What each sub reported doing, in a few lines: one line per ACTIVITY
    (a log line naming two is two), the same activity on any number of days one
    line with its span and floors, and a line is "advanced" only when the SAME
    activity is now reported on floors it was not before.

    NOTHING IS "NEW". Logs word the same work differently from one day to the
    next, so "this activity did not appear last period" is mostly a change of
    wording; a report that said "NEW" for it claimed a start nobody can
    support. A sub new to the site is shown as new in the workforce table,
    where the check-ins prove it. `comparable` is False when the previous
    period holds no activity at all: nothing is then "advanced"."""
    def keyed(a: Dict[str, Any]) -> str:
        return canon.get(a["key"], a["key"])

    def expand(rows):
        for a in rows:
            for ph in work_phrases(a["work"]):
                k = _phrase_key(ph)
                if k:
                    yield k, ph, a
    out = []
    for s in subs:
        mine = [a for a in cur if keyed(a) == s["key"] and a["work"]]
        before = [a for a in prev if keyed(a) == s["key"] and a["work"]]
        before_floors: Dict[str, set] = defaultdict(set)
        for k, _ph, a in expand(before):
            before_floors[k].update(a["floors"])
        by_work: Dict[str, List[Any]] = defaultdict(list)
        shown: Dict[str, str] = {}
        for k, ph, a in expand(sorted(mine, key=lambda x: x["date"])):
            by_work[k].append(a)
            shown.setdefault(k, ph)
        items = []
        for k, rows in by_work.items():
            floors = sorted({f for a in rows for f in a["floors"]})
            places = Counter(a["where"] for a in rows if a["where"] and not a["floors"])
            seen_before = k in before_floors
            new_floors = sorted(set(floors) - before_floors.get(k, set()))
            installs = not any(w in f"{s.get('trade') or ''} {s.get('name') or ''}".lower() for w in _NON_INSTALL)
            status = ("reported" if not comparable else
                      "advanced" if installs and seen_before and new_floors and floors else
                      "continued" if seen_before else "reported")
            fam_sub, fam_work = trade_family(s.get("trade"), s.get("name")), trade_family(shown[k])
            items.append({"work": shown[k], "floors": floors,
                          "trade_mismatch": bool(fam_sub and fam_work and fam_sub != fam_work),
                          "place": floors_label(floors) or (places.most_common(1)[0][0][:60] if places else ""),
                          "first": rows[0]["date"], "last": rows[-1]["date"], "days": len({a["date"] for a in rows}),
                          "status": status, "new_floors": new_floors if seen_before else [],
                          "amended": any(a["amended"] for a in rows)})
        items.sort(key=lambda i: (-i["days"], i["work"]))
        out.append({"key": s["key"], "name": s["name"], "trade": s["trade"], "items": items[:4]})
    return out


def _floor_matrix(cur: List[Dict[str, Any]], prev: List[Dict[str, Any]], canon: Dict[str, str],
                  subs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Floors where each sub reported work: this period, or only before. A
    record of REPORTED ACTIVITY by floor -- never a completion claim. None
    when the logs name fewer than two floors."""
    def floors_of(rows: List[Dict[str, Any]], k: str) -> set:
        return {f for a in rows if canon.get(a["key"], a["key"]) == k for f in a["floors"]}
    allf = sorted({f for a in cur + prev for f in a["floors"]})
    if len(allf) < 2 or len(allf) > 30:
        return None
    rows = []
    for s in subs:
        now, before = floors_of(cur, s["key"]), floors_of(prev, s["key"])
        if now or before:
            rows.append({"name": s["name"], "color": s.get("color", PALETTE[0]),
                         "cells": {f: ("now" if f in now else "before" if f in before else "") for f in allf}})
    return {"floors": allf, "rows": rows} if rows else None


# ── PHOTOS ───────────────────────────────────────────────────────────────────

def photo_candidates(acts: List[Dict[str, Any]], start: date, end: date,
                     *_ignored: Any, **_ignored_kw: Any) -> List[Dict[str, Any]]:
    """The report's photographs come from the filed daily logs ONLY: each is
    already filed under its sub, its day and its work. Never a photo from the
    group chat or a walkthrough, and never one from a day nobody filed."""
    out = []
    for a in acts:
        if not base._in(a["date"], start, end) or not a["key"]:
            continue
        place = floors_label(a["floors"]) or base.no_phone(a["where"])[:60]
        for n, p in enumerate(a["photos"]):
            key = p.get("enhanced_r2_key") or p.get("original_r2_key") or p.get("thumb_r2_key")
            # A filed photo with only its inline copy is a photo too (Codex on
            # #803): keyed by where it is, read from the log by the server.
            if not key and (p.get("base64") or p.get("thumb_base64")):
                key = f"inline:{a['log']}:{n}"
            if key:
                out.append({"key": key, "date": a["date"], "sub": a["company"], "trade": a["trade"],
                            "where": place, "words": work_line(a["work"] or a["trade"], place),
                            "work": a["work"], "log_id": a["log_id"], "source": "daily log", "photo": p})
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: (c["date"], c["key"])):
        if c["key"] not in seen:
            seen.add(c["key"])
            uniq.append(c)
    return uniq


def work_line(work: Any, place: Any) -> str:
    """The caption of a daily-log photo: the sub's work that day, as the log
    says it -- "Framing — floors 1–2", "Scaffolding — Front facade"."""
    w = str(work or "").strip() or "Work on site"
    p = str(place or "").strip()
    if p and p[:1].isalpha() and not p.startswith(("fl ", "floor")):
        p = p[:1].upper() + p[1:]
    return f"{w} — {p}" if p else w


def to_judge(cands: List[Dict[str, Any]], limit: int = 30) -> List[Dict[str, Any]]:
    """Which photos to send to vision (it costs): each sub's first 2 and last
    2, then the rest spread over the period."""
    by_sub: Dict[str, List[dict]] = defaultdict(list)
    for c in cands:
        by_sub[company_key(c["sub"]) or c["source"]].append(c)
    picked: List[dict] = []
    for group in by_sub.values():
        for c in group[:2] + group[-2:]:
            if c not in picked:
                picked.append(c)
    rest = [c for c in cands if c not in picked]
    step = max(1, len(rest) // max(1, limit - len(picked))) if rest else 1
    picked += rest[::step]
    return picked[:limit]


WORK_FAMILIES = ("framing", "plumbing", "electrical", "hvac", "scaffolding", "stairs", "concrete", "masonry",
                 "demolition", "facade", "other", "none")
_FAMILY_WORDS = (("scaffolding", ("scaffold", "hoist", "sidewalk shed")), ("hvac", ("hvac", "duct", "mechanical")),
                 ("plumbing", ("plumb", "pipe", "riser", "sanitary")),
                 ("electrical", ("electr", "wiring", "low voltage")),
                 ("stairs", ("stair", "railing", "iron", "structural steel")),
                 ("framing", ("fram", "stud", "drywall", "sheetrock", "gypsum", "carpent", "partition")),
                 ("concrete", ("concrete", "slab", "foundation", "rebar", "pour")),
                 ("masonry", ("mason", "brick", "cmu", "block")), ("demolition", ("demo",)),
                 ("facade", ("facade", "curtain wall", "window", "glaz", "roof")))


def trade_family(*texts: Any) -> str:
    """The kind of work a sub's name / trade says ("Quality Plumbing" ->
    plumbing), or "" when it says none. A general contractor says none."""
    t = " ".join(str(x or "").lower() for x in texts)
    for fam, words in _FAMILY_WORDS:
        if any(w in t for w in words):
            return fam
    return ""


def parse_verdict(said: Any) -> Optional[Dict[str, Any]]:
    """The vision model's JSON answer, checked: {ok, kind, score, caption,
    work} or None."""
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
    work = str(v.get("work") or "none").lower()
    caption = " ".join(str(v.get("caption") or "").split())[:100]
    return {"ok": bool(v.get("ok")) and kind == "progress", "kind": kind, "score": score,
            "work": work if work in WORK_FAMILIES else "other", "caption": base.no_phone(caption)}


JUDGE_PROMPT = (
    "You choose photos that PROVE CONSTRUCTION PROGRESS in a report an owner or lender will read. "
    "Look at this jobsite photo and answer in JSON only: {\"ok\": true|false, \"kind\": \"progress\"|"
    "\"materials\"|\"area\"|\"people\"|\"document\"|\"blurry\"|\"other\", \"score\": 0-10, "
    "\"work\": \"framing\"|\"plumbing\"|\"electrical\"|\"hvac\"|\"scaffolding\"|\"stairs\"|\"concrete\"|"
    "\"masonry\"|\"demolition\"|\"facade\"|\"other\"|\"none\", \"caption\": \"...\"}. "
    "kind is progress ONLY when INSTALLED or BUILT work is clearly visible (framing standing, pipes or "
    "conduit in place, scaffolding erected, a stair set, a slab poured, a facade). materials: stacked or "
    "stored materials or equipment. area: an empty room, corridor or general site condition with no "
    "identifiable work. people: people fill the frame. document: paper, screens, drawings. blurry: out "
    "of focus or too dark, OR partly covered by a finger, thumb, hand, strap or smudged lens (kind blurry, "
    "score 3 or less, ok false). ok is true only for a sharp, well-lit, unobstructed progress photo. score: how strongly it "
    "shows completed work (wide view, the work identifiable and complete = 8-10; partial or unclear = "
    "1-4). work: the one trade whose work you can SEE; none when you cannot tell. caption: one short "
    "line of ONLY what is visible, plain construction words (e.g. \"Metal stud framing, one floor\"); "
    "never a name, a number, a date or a location you cannot see.")


#: Crews that do not install work: a photograph of installed work is not
#: THEIR evidence (a cleaning crew was credited with a framing photo on the
#: first real 588 report).
_NON_INSTALL = ("clean", "janitor", "porter", "security", "guard", "trucking", "hauling", "rubbish", "dumpster",
                "waste", "flagging", "traffic", "delivery", "supervis", "inspector", "engineer", "survey")

#: What a photograph says, by the work the vision model SEES -- fixed words, so
#: a caption can never name a material or a detail the model got wrong (the
#: first real report read "wooden stairs" for a steel stair).
WORK_CAPTION = {"framing": "Framing in place", "plumbing": "Plumbing installed", "electrical": "Electrical work installed",
                "hvac": "Ductwork installed", "scaffolding": "Scaffolding erected", "stairs": "Stair installed",
                "concrete": "Concrete work in place", "masonry": "Masonry in place", "demolition": "Demolition work",
                "facade": "Facade work", "other": "Installed work", "none": "Installed work"}


def _consistent(c: Dict[str, Any], v: Dict[str, Any]) -> bool:
    """A photo is the sub's evidence only if what it shows is that sub's kind
    of work: a plumber's log with a photo of a stair is not plumbing progress,
    and a crew that installs nothing has no installed-work photo. Unknown on
    either side is not a contradiction."""
    label = f"{c.get('trade') or ''} {c.get('sub') or ''}".lower()
    if any(w in label for w in _NON_INSTALL):
        return False
    sub_fam = trade_family(c.get("trade"), c.get("sub"))
    seen = str(v.get("work") or "none")
    if not sub_fam or seen in ("none", "other"):
        return True
    return seen == sub_fam


def pick_photos(cands: List[Dict[str, Any]], verdicts: Dict[str, Dict[str, Any]],
                most: int = MAX_PHOTOS) -> List[Dict[str, Any]]:
    """Four to eight photographs that show INSTALLED work: only photos vision
    calls a clear progress shot (never materials, a corridor, people, a
    document or a blur) whose visible work matches the sub's kind of work,
    the strongest of each sub first, then the next strongest, never the same
    sub, day and place twice and never more than two of one sub.

    THE CAPTION IS WHAT THE PHOTO SHOWS, in FIXED WORDS by the kind of work the
    model sees (WORK_CAPTION), not the log's words for the activity row it was
    attached to (an audit found a stair photographed under a plumber's log
    line) and not the model's free text (the first real report read "wooden
    stairs" for a steel stair). The sub, date and place are as the log filed
    them.

    NO BEFORE / AFTER: nothing checks that two photos show the same place."""
    good = []
    for c in cands:
        if c.get("source") != "daily log":
            continue
        v = verdicts.get(c["key"]) or {}
        if (v.get("ok") and v.get("kind", "progress") == "progress" and _consistent(c, v)
                and float(v.get("score") or 0) >= MIN_SCORE):
            good.append({**c, "score": float(v.get("score") or 0),
                         "caption": WORK_CAPTION.get(str(v.get("work") or "none"), WORK_CAPTION["none"]),
                         "work": str(v.get("work") or "none")})
    chosen: List[dict] = []
    per_sub: Counter = Counter()

    def add(c: Dict[str, Any]) -> bool:
        k = company_key(c["sub"]) or c["sub"]
        if len(chosen) >= most or per_sub[k] >= MAX_PER_SUB or any(x["key"] == c["key"] for x in chosen):
            return False
        if any(company_key(x["sub"]) == company_key(c["sub"]) and x["date"] == c["date"]
               and x["where"] == c["where"] for x in chosen):
            return False
        chosen.append(c)
        per_sub[k] += 1
        return True
    by_sub: Dict[str, List[dict]] = defaultdict(list)
    for c in good:
        by_sub[company_key(c["sub"]) or c["sub"]].append(c)
    queues = [sorted(g, key=lambda c: (-c["score"], c["date"])) for _, g in sorted(by_sub.items())]
    while len(chosen) < most and any(queues):
        for q in queues:
            while q and not add(q.pop(0)):
                pass
    chosen.sort(key=lambda c: (c["date"], c["sub"]))
    return chosen


# ── COMING UP ────────────────────────────────────────────────────────────────

def coming_up(events: Iterable[dict], end: date, plan: Optional[Dict[str, Any]],
              regulatory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What is dated and next, from records with their own date: the city's
    hearing and permit dates, permits that expire, and the schedule's
    upcoming milestones. NOT from chat: a date a model read out of a message
    is a guess an owner would take for a commitment.

    The window is anchored on the period's LAST DAY, not on today, so a
    report for last month shows what was upcoming then."""
    horizon = end + timedelta(days=UPCOMING_DAYS)
    out: List[Dict[str, Any]] = []
    for e in events:
        if str(e.get("source") or "city") != "city" or e.get("status") in ("cancelled", "dismissed"):
            continue
        d = base._d(e.get("date"))
        if d and end < d <= horizon:
            out.append({"date": d, "what": base.no_phone(e.get("title")), "src": "R",
                        "kind": str(e.get("kind") or "")})
    seen = {(o["date"], o["what"]) for o in out}
    for p in regulatory.get("expiring") or []:
        what = (f"{len(p['members'])} DOT street permits expire" if p.get("members")
                else f"{p['kind']} {p['number']} expires".strip())
        num = str(p.get("number") or "").upper()
        # The same expiry may already be there as a city event worded differently
        # ("DOB permit expires · #B23173802-S5"): one line, not two (found on
        # the first real 588 report).
        dup = bool(num) and any(o["date"] == p["expires"] and num in str(o["what"]).upper() for o in out)
        if p["expires"] and p["expires"] <= horizon and (p["expires"], what) not in seen and not dup:
            out.append({"date": p["expires"], "what": what, "src": "R", "kind": "permit_expiration"})
    for m in (plan or {}).get("milestones", {}).get("upcoming") or []:
        d = base._d(m.get("date")) or base._d(m.get("current_finish")) or base._d(m.get("baseline_finish"))
        if d:
            out.append({"date": d, "what": f"Milestone: {m.get('name')}", "src": "S", "kind": "milestone"})
    out.sort(key=lambda x: (x["date"], x["what"]))
    return out[:8]


# ── THE REPORT ───────────────────────────────────────────────────────────────

def bucket_for(days: int) -> str:
    """The chart granularity for a period of `days`: daily up to three weeks,
    weekly up to about four months, monthly beyond."""
    return "day" if days <= 21 else "week" if days <= 125 else "month"


def _bucket_key(d: date, grain: str) -> date:
    if grain == "day":
        return d
    if grain == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def series(totals: Dict[date, int], worked: List[date], start: date, end: date, grain: str
           ) -> List[Dict[str, Any]]:
    """The workforce chart's bars: one per bucket of the period (a day, a
    Monday-start week, a month): the average workers on the days worked in
    it, and how many days that was."""
    buckets: Dict[date, List[int]] = defaultdict(list)
    for d in worked:
        if start <= d <= end:
            buckets[_bucket_key(d, grain)].append(totals[d])
    out = []
    cur = _bucket_key(start, grain)
    while cur <= end:
        vals = buckets.get(cur, [])
        out.append({"start": cur, "avg": round(sum(vals) / len(vals), 1) if vals else 0.0,
                    "days": len(vals), "peak": max(vals) if vals else 0})
        cur = (cur + timedelta(days=1 if grain == "day" else 7)) if grain != "month" else \
            (cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1))
    return out


def compute(*, job: str, address: str, gc: str, start: date, end: date, now: datetime, kind: str = "",
            checkins: Iterable[dict] = (), logbooks: Iterable[dict] = (),
            dob_rows: Iterable[dict] = (), dot_rows: Iterable[dict] = (),
            events: Iterable[dict] = (), schedule: Optional[Dict[str, Any]] = None,
            schedule_meta: Optional[Dict[str, Any]] = None, financials: Optional[Dict[str, Any]] = None, sync: Optional[Dict[str, Any]] = None,
            first_activity: Optional[date] = None, project_bins: Iterable[Any] = (), **_ignored: Any) -> Dict[str, Any]:
    """Everything of one job's report for [start, end], from its rows.

    `checkins` and `logbooks` span the period AND the previous period of the
    same length (the server reads both); the comparison is computed here from
    the same rows, so a number printed twice cannot differ."""
    today = att.local_day(now) or end
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    checkins = list(checkins)
    log_set = effective_logs(logbooks)
    logs = log_set["items"]
    acts = _log_activities(logs, prev_start, end)
    fixes = spelling_fixes(a["work"] for a in acts)
    for a in acts:
        a["work"] = _apply_fixes(a["work"], fixes)
    days_map = att.by_day(checkins, prev_start, end)
    all_keys = [company_key(co) for by_co in days_map.values() for co in by_co if not is_unassigned(co)]
    canon = canonical_keys(all_keys + [a["key"] for a in acts if a["key"]])
    log_days = {d for d in (base._d(lg.get("date")) for lg in logs) if d}
    cur = _window(days_map, acts, canon, start, end, log_days)
    prv = _window(days_map, acts, canon, prev_start, prev_end, log_days)
    names: Dict[str, str] = {}
    for w in (cur, prv):
        for k, s in w["per"].items():
            names.setdefault(k, s["names"].most_common(1)[0][0])
    subs = _sub_rows(cur, prv, names)
    for i, s in enumerate(subs):
        s["color"] = PALETTE[i % len(PALETTE)]
    now_stats, prev_stats = _stats(cur["totals"], cur["worked"]), _stats(prv["totals"], prv["worked"])
    last = min(end, today)
    possible = report_calendar.working_days(start, last, first_activity=first_activity, worked=cur["worked"])
    prev_possible = report_calendar.working_days(prev_start, prev_end, first_activity=first_activity,
                                                 worked=prv["worked"])
    grain = bucket_for(length)
    cur_acts = [a for a in acts if start <= a["date"] <= end]
    prev_acts = [a for a in acts if prev_start <= a["date"] <= prev_end]
    work = _work(cur_acts, prev_acts, canon, subs, comparable=bool(prv["worked"] or prev_acts))
    reg = report_regulatory.build(list(dob_rows), list(dot_rows), start, end, today=today, sync=sync, now=now,
                                  project_bins=project_bins)
    plan = None
    if schedule:
        try:
            from lib import schedule_plan
            plan = schedule_plan.assess(schedule, period_start=start, period_end=end, today=today)
            plan.update({k: v for k, v in (schedule_meta or {}).items() if k in ("source_name", "confirmed_by")})
        except Exception:                      # a schedule that cannot be read is no schedule
            plan = None
    insp = inspections(logs, start, end)
    rep: Dict[str, Any] = {
        "engine": ENGINE_VERSION, "kind": kind or "custom",
        "job": job_title(job), "job_full": job, "address": address, "gc": gc,
        "start": start, "end": end, "today": today, "generated": now, "length": length,
        "prev_start": prev_start, "prev_end": prev_end, "grain": grain,
        "period": base.period_label(start, end), "period_short": short_period(start, end, now),
        "subs": subs, "work": work, "floor_matrix": _floor_matrix(cur_acts, prev_acts, canon, subs),
        "site": {**now_stats, "possible": len(possible), "worked": len(cur["worked"]),
                 "table": [{"day": d, "total": cur["totals"][d]} for d in cur["worked"]],
                 "series": series(cur["totals"], cur["worked"], start, end, grain),
                 "prev_series": series(prv["totals"], prv["worked"], prev_start, prev_end, grain),
                 "basis": report_calendar.BASIS_NOTE,
                 "holidays": report_calendar.holiday_names(start, last)},
        "prev": {**prev_stats, "possible": len(prev_possible), "worked": len(prv["worked"])},
        "regulatory": reg, "inspections": insp, "schedule": plan, "financials": _financials(financials),
        "photo_candidates": photo_candidates(cur_acts, start, end), "photos": [],
        "log_set": {"filed": len([lg for lg in logs if start <= (base._d(lg.get("date")) or start) <= end]),
                    "amended": [d for d in log_set["amended"] if d and start <= d <= end],
                    "duplicates": log_set["duplicates"], "competing": log_set["competing"]},
        "recon": {**cur["recon"], "variance_days": cur["variance_days"][:6],
                  "log_rows_no_company": cur["log_rows_no_company"],
                  "unassigned_checkins": sum(cur["unassigned"].values())},
    }
    rep["prev_subs"] = [{"name": names.get(k) or s["names"].most_common(1)[0][0], "key": k,
                         "days": len([1 for e in s["days"].values() if e["count"] > 0]),
                         "last": max((d for d, e in s["days"].items() if e["count"] > 0), default=None)}
                        for k, s in prv["per"].items() if any(e["count"] > 0 for e in s["days"].values())]
    rep["mobilization"] = mobilization(rep)
    rep["upcoming"] = coming_up(list(events), end, plan, reg)
    rep["risks"] = risks(rep)
    rep["status"] = status(rep)
    rep["changes"] = changes(rep)
    rep["overview"] = overview(rep)
    rep["limitations"] = limitations(rep)
    rep["spelling"] = dict(sorted(fixes.items())[:6])
    rep["data_notes"] = data_notes(rep, [lg for lg in logs if start <= (base._d(lg.get("date")) or start) <= end],
                                   checkins, cur["worked"])
    rep["evidence"] = evidence(rep, checkins, [lg for lg in logs if base._in(base._d(lg.get("date")), start, end)])
    return rep


def _financials(f: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Financial figures, ONLY when a person provided and confirmed them: a
    dict with `confirmed` True, an `as_of` date and a `source`, and at least
    one figure. Anything else is no financial data -- the section is left out
    and the limitation says so. No figure is ever computed here."""
    if not isinstance(f, dict) or not f.get("confirmed") or not f.get("source") or not f.get("as_of"):
        return None
    keys = ("contract_value", "approved_changes", "revised_contract", "billed_to_date", "paid_to_date",
            "retainage", "cost_to_complete", "contingency_remaining", "budget")
    figs = {k: f[k] for k in keys if isinstance(f.get(k), (int, float)) and not isinstance(f.get(k), bool)}
    if not figs:
        return None
    return {"as_of": base._d(f.get("as_of")), "source": str(f.get("source"))[:120], "figures": figs,
            "draw_status": str(f.get("draw_status") or "")[:80] or None}


# ── WHAT CHANGED, WHAT IS AT RISK, WHAT IT IS BASED ON ───────────────────────

def mobilization(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Subs that arrived, left, or changed size since the previous period.
    Not asserted when the previous period had no site activity (the job's
    first period: everyone would be "new")."""
    out: Dict[str, Any] = {"new": [], "gone": [], "changed": [], "comparable": rep["prev"]["days"] > 0}
    if not out["comparable"]:
        return out
    here = {s["key"] for s in rep["subs"]}
    for g in rep.get("prev_subs") or []:
        if g["key"] not in here and g["days"] >= 2:
            out["gone"].append({"name": g["name"], "last": g["last"]})
    for s in rep["subs"]:
        if s["prev_days"] == 0:
            out["new"].append({"name": s["name"], "first": s["first"], "avg": s["avg"]})
        else:
            delta = s["avg"] - s["prev_avg"]
            if abs(delta) >= CHANGE_WORKERS and abs(delta) >= CHANGE_PCT * max(s["prev_avg"], 1):
                out["changed"].append({"name": s["name"], "avg": s["avg"], "prev_avg": s["prev_avg"],
                                       "direction": "up" if delta > 0 else "down"})
    return out


def changes(rep: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The meaningful changes since the previous period, at most six, each
    with the kind of record it rests on, most material first: regulatory
    events, schedule milestones, the workforce, mobilization, then the work.
    Deterministic: the rules are the thresholds above and the regulatory /
    schedule facts."""
    out: List[Dict[str, Any]] = []
    site, prev, mob = rep["site"], rep["prev"], rep["mobilization"]
    reg = rep["regulatory"]
    for r in reg["swo_lifted"][:2]:
        out.append({"src": "R", "refs": [r["id"]],
                    "text": f"{r['kind']} {r['number']} was lifted on {_dayy(r['changed_on'])}."})
    new_issues = [r for r in reg["issued"] if r["type"] in report_regulatory.OPEN_TYPES]
    if new_issues:
        out.append({"src": "R", "refs": [r["id"] for r in new_issues[:3]],
                    "text": f"{_n(len(new_issues), 'new DOB/DOT violation or order')} issued: "
                    + _join([f"{r['kind']} {r['number']}".strip() for r in new_issues[:3]]) + "."})
    resolved = [r for r in reg["changed"] if r["closed"] and r["type"] in report_regulatory.OPEN_TYPES
                and r["id"] not in {x["id"] for x in reg["swo_lifted"]}]
    if resolved:
        out.append({"src": "R", "refs": [r["id"] for r in resolved[:3]],
                    "text": f"{_n(len(resolved), 'violation')} resolved: "
                    + _join([f"{r['kind']} {r['number']}".strip() for r in resolved[:3]]) + "."})
    plan = rep["schedule"]
    if plan and plan.get("usable"):
        done = plan["milestones"]["completed_in_period"]
        if done:
            out.append({"src": "S", "text": f"{_n(len(done), 'milestone')} completed per the schedule: "
                        + _join([m["name"] for m in done[:2]]) + "."})
    if prev["days"] and site["worked"]:
        delta = site["avg"] - prev["avg"]
        if abs(delta) >= CHANGE_WORKERS and abs(delta) >= WORKFORCE_NOTE_PCT * max(prev["avg"], 1):
            out.append({"src": "G", "text": f"Average workforce {'rose' if delta > 0 else 'fell'} to "
                        f"{site['avg']:g} workers a day from {prev['avg']:g} in the previous period."})
    if mob["new"]:
        out.append({"src": "G", "text": _join([m["name"] for m in mob["new"][:4]])
                    + " mobilized this period (not on site in the previous one)."})
    if mob["gone"]:
        out.append({"src": "G", "text": _join([g["name"] for g in mob["gone"][:3]])
                    + " no longer on site (none this period)."})
    for m in mob["changed"][:2]:
        out.append({"src": "G", "text": f"{m['name']} crew {'increased' if m['direction'] == 'up' else 'decreased'} "
                    f"to an average of {m['avg']:g} from {m['prev_avg']:g}."})
    adv = [(w["name"], i) for w in rep["work"] for i in w["items"]
           if i["status"] == "advanced" and not i.get("trade_mismatch")]
    for name, i in adv[:3]:
        out.append({"src": "L", "text": f"{name}: {lc_first(i['work'])} advanced to {floors_label(i['new_floors'])}."})
    return out[:6]


def risks(rep: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Material, project-level risks, from facts only: stop work and vacate
    orders, open DOB/DOT violations, permits about to expire, failed daily
    inspections, overdue milestones, a schedule that has slipped, a sharp
    drop in the workforce. Each has a level (critical / high / watch), the
    evidence kind and the entries it rests on. At most six."""
    out: List[Dict[str, Any]] = []
    reg = rep["regulatory"]
    for r in reg["swo_active"]:
        out.append({"level": "critical", "src": "R", "ref": r["id"], "refs": [r["id"]],
                    "text": f"{r['kind']} {r['number']} is active (issued {_dayy(r['issued'])})."})
    opens = [r for r in reg["open"] if r["id"] not in {x["id"] for x in reg["swo_active"]}]
    if opens:
        out.append({"level": "high", "src": "R", "ref": ",".join(r["id"] for r in opens[:5]),
                    "refs": [r["id"] for r in opens[:3]],
                    "text": f"{_n(len(opens), 'DOB/DOT violation or complaint')} open: "
                    + _join([f"{r['kind']} {r['number']}".strip() for r in opens[:3]])
                    + (f" and {len(opens) - 3} more" if len(opens) > 3 else "") + "."})
    soon = [p for p in reg["expiring"] if p["expires"] and (p["expires"] - rep["end"]).days <= 30]
    if soon:
        out.append({"level": "watch", "src": "R", "ref": ",".join(p["id"] for p in soon[:5]),
                    "refs": [p["id"] for p in soon[:3]],
                    "text": ("Permits expiring within 30 days: " if len(soon) > 1 else "Permit expiring within 30 days: ")
                    + _join([(f"{len(p['members'])} DOT street permits ({_dayy(p['expires'])})" if p.get("members")
                              else f"{p['kind']} {p['number']} ({_dayy(p['expires'])})").strip() for p in soon[:3]]) + "."})
    insp = rep["inspections"]
    if insp["failed"]:
        out.append({"level": "high", "src": "L", "ref": "",
                    "text": f"{_n(insp['failed'], 'daily inspection item')} recorded as failed in the daily logs: "
                    + _join(sorted({f"{f['item']} ({_day(f['date'])})" for f in insp["failed_items"]})[:3]) + "."})
    plan = rep["schedule"]
    if plan and plan.get("usable"):
        od = plan["milestones"]["overdue"]
        if od:
            out.append({"level": "high", "src": "S", "ref": "",
                        "text": f"{_n(len(od), 'milestone')} past due per the schedule: "
                        + _join([m["name"] for m in od[:2]]) + "."})
        v = plan["project"].get("variance_days")
        if v is not None and v >= 14:
            out.append({"level": "watch", "src": "S", "ref": "",
                        "text": f"The schedule's forecast finish is {_n(v, 'day')} after its original finish."})
    site, prev = rep["site"], rep["prev"]
    if prev["days"] >= 3 and site["worked"] and prev["avg"] >= 6 and \
            site["avg"] <= prev["avg"] * (1 - 0.35):
        out.append({"level": "watch", "src": "G", "ref": "",
                    "text": f"Average workforce is down to {site['avg']:g} a day from {prev['avg']:g}."})
    rank = {"critical": 0, "high": 1, "watch": 2}
    out.sort(key=lambda r: rank[r["level"]])
    return out[:6]


def status(rep: Dict[str, Any]) -> Dict[str, Any]:
    """The report's flag: what the records show, and what they cannot. It is
    NOT a judgment of schedule, cost or quality -- those need a schedule and
    figures the report does not have unless they were provided."""
    levels = {r["level"] for r in rep["risks"]}
    if "critical" in levels:
        label, level = "Needs attention", "critical"
    elif "high" in levels:
        label, level = "Watch", "high"
    elif levels:
        label, level = "Watch", "watch"
    else:
        label, level = "No flagged issues", "ok"
    cov = rep["regulatory"]["coverage"]["state"]
    basis = "Based on site check-ins, filed daily logs and DOB/DOT records"
    if cov in ("unknown", "not_tracked", "stale"):
        basis += "; regulatory records could not be verified for this period"
    return {"label": label, "level": level, "basis": basis + "."}


def overview(rep: Dict[str, Any]) -> List[str]:
    """The paragraphs of the executive overview, composed from the numbers:
    activity, progress, regulatory, schedule, finance. Each is one or two
    plain sentences and every figure in it is printed elsewhere in the
    report."""
    site, prev, subs = rep["site"], rep["prev"], rep["subs"]
    out: List[str] = []
    if site["worked"]:
        s = (f"{_n(len(subs), 'subcontractor')} worked on site on {site['worked']} of {site['possible']} "
             f"working days, averaging {site['avg']:g} workers a day with a peak of {site['peak']} on "
             f"{_wday(site['peak_day'])}.")
        if prev["days"]:
            delta = site["avg"] - prev["avg"]
            if abs(delta) >= CHANGE_WORKERS and abs(delta) >= WORKFORCE_NOTE_PCT * max(prev["avg"], 1):
                s += f" The average was {'up' if delta > 0 else 'down'} from {prev['avg']:g} in the previous period."
            else:
                s += f" That is in line with the previous period ({prev['avg']:g} a day)."
        out.append(s)
    else:
        out.append("No site check-ins or filed crew reports were recorded in this period.")
    lines = []
    for w in rep["work"][:4]:
        for i in [x for x in w["items"] if not x.get("trade_mismatch")][:1]:
            lines.append(f"{w['name']}: {lc_first(i['work'])}" + (f" on {i['place']}" if i["place"] else ""))
    if lines:
        out.append("Reported work — " + "; ".join(lines) + ".")
    reg = rep["regulatory"]
    cov = reg["coverage"]
    if cov["state"] in ("verified", "partial"):
        bits = []
        if reg["swo_active"]:
            bits.append(f"{_n(len(reg['swo_active']), 'stop work or vacate order')} active")
        others = [r for r in reg["open"] if r["id"] not in {x["id"] for x in reg["swo_active"]}]
        if others:
            bits.append(f"{_n(len(others), 'DOB/DOT violation or complaint')} open")
        if reg["issued"]:
            bits.append(f"{_n(len(reg['issued']), 'record')} issued in the period")
        out.append("Regulatory — " + (_join(bits) if bits else
                   "no DOB/DOT violations, orders or complaints open at the end of the period") + ".")
    else:
        out.append("Regulatory — " + cov["note"])
    plan = rep["schedule"]
    if plan and plan.get("usable"):
        proj = plan["project"]
        s = f"Schedule — per the project schedule dated {_dayy(plan['as_of'])}"
        if plan["as_of"] is None:
            s = "Schedule — per the imported project schedule"
        parts = []
        c = plan["counts"]
        if c["activities"]:
            parts.append(f"{c['complete']} of {c['activities']} scheduled activities complete")
        if plan["milestones"]["overdue"]:
            parts.append(f"{_n(len(plan['milestones']['overdue']), 'milestone')} past due")
        if proj.get("forecast_finish") and proj.get("baseline_finish"):
            parts.append(f"forecast finish {_dayy(proj['forecast_finish'])} against an original "
                         f"{_dayy(proj['baseline_finish'])}")
        out.append(s + (": " + _join(parts) if parts else ".") + ("." if parts else ""))
    else:
        out.append("Schedule — no confirmed project schedule is on file, so schedule status and "
                   "completion are not reported.")
    return out


def limitations(rep: Dict[str, Any]) -> List[str]:
    """Plain-English notes on what this report does not contain and why: kept
    short and printed once, at the end."""
    out = []
    if not (rep["schedule"] and rep["schedule"].get("usable")):
        out.append("No confirmed project schedule is on file: completion percentages, planned-versus-actual "
                   "progress and milestone status are not reported.")
    else:
        out.extend(rep["schedule"].get("limitations") or [])
    if not rep["financials"]:
        out.append("No confirmed financial data is on file: budget, change-order, cost and draw information "
                   "is not reported.")
    out.append("Progress is as reported in the daily logs and site check-ins. It is not independently "
               "verified, and no percent complete is derived from headcount, log wording or photographs.")
    out.append("Photographs are supplied in the filed daily logs; their location and date are as filed and "
               "are not independently verified.")
    out.append("Internal GC coordination (messages, reminders, punch-list assignments, free-text site "
               "observations) and individual worker information are not included in this report.")
    return out


def data_notes(rep: Dict[str, Any], logs: List[dict], checkins: List[dict], worked: List[date]) -> List[str]:
    """What a careful reader should know about the records behind the numbers:
    days with no filed log, amended days, gate/log differences."""
    out = []
    site, ls, rc = rep["site"], rep["log_set"], rep["recon"]
    odd = [(w["name"], i["work"]) for w in rep.get("work") or [] for i in w["items"] if i.get("trade_mismatch")]
    if odd:
        out.append("Listed under a sub whose trade does not match the work: "
                   + "; ".join(f"{n}: {t}" for n, t in odd[:4])
                   + ". Shown as filed, marked CHECK, and not used in the summary; the daily log may have the wrong company on that line.")
    reg = rep.get("regulatory") or {}
    left = reg.get("excluded") or []
    if left:
        by_bin: Dict[str, List[str]] = defaultdict(list)
        for e in left:
            by_bin[e["bin"] or "?"].append(e["number"] or e["kind"])
        parts = "; ".join(f"BIN {b}: {', '.join(n[:6])}{' and more' if len(n) > 6 else ''}" for b, n in sorted(by_bin.items()))
        verb = "was" if len(left) == 1 else "were"
        out.append(f"{len(left)} DOB record{'s' if len(left) != 1 else ''} for another building {verb} left out "
                   f"({parts}); this project's BIN is {', '.join(reg.get('bins') or []) or 'unknown'}. They are listed "
                   "in the report's stored snapshot for review; if they belong to this site, add the BIN to the project.")
    if reg.get("bins_inferred"):
        out.append("Records filed under BIN " + ", ".join(reg["bins_inferred"]) + " are included because their jobs also "
                   "appear under this project's BIN " + ", ".join(reg.get("bins") or []) + " (one DOB job can cover more than "
                   "one building of a lot); add the BIN to the project to confirm it.")
    if reg.get("bin_unverified"):
        out.append(f"{reg['bin_unverified']} DOB record row{'s' if reg['bin_unverified'] != 1 else ''} carry no building "
                   "number (BIN), so whether they belong to this site could not be checked; they are included.")
    if rep.get("spelling"):
        out.append("Obvious misspellings in the daily logs' wording were corrected for reading ("
                   + ", ".join(f"{a} → {b}" for a, b in rep["spelling"].items()) + ").")
    in_period_checkins = [r for r in checkins if base._in(att.local_day(r.get("check_in_time")), rep["start"],
                                                            rep["end"])]
    if site["worked"]:
        missing = [d for d in worked if d not in {base._d(lg.get("date")) for lg in logs}]
        out.append(f"Daily logs were filed for {ls['filed']} of the {site['worked']} days with site activity"
                   + (f" (no filed log on {_join([_day(d) for d in missing[:4]])}"
                      + (f" and {len(missing) - 4} more" if len(missing) > 4 else "") + ")." if missing else "."))
    if ls["amended"]:
        out.append(f"{_n(len(ls['amended']), 'day')} ({_join([_day(d) for d in ls['amended'][:4]])}) "
                   "were amended after filing; the corrected version is used.")
    if ls["competing"]:
        out.append(f"{_n(ls['competing'], 'day')} has competing corrections filed; the most recent is used.")
    if ls["duplicates"]:
        out.append(f"{_n(ls['duplicates'], 'day')} had more than one daily log filed; the latest is used.")
    if rc["variance"]:
        v = rc["variance_days"][0]
        out.append(f"On {_n(rc['variance'], 'sub-day')}, the daily-log headcount differed from the gate "
                   f"check-ins by more than {int(AGREE_PCT * 100)}% (e.g. {v['sub']} on {_day(v['date'])}: "
                   f"{v['gate']} checked in, {v['log']} logged). Gate counts are used.")
    if rc["log_basis_days"]:
        out.append(f"On {_n(rc['log_basis_days'], 'sub-day')} the crew appears in the daily log but has no gate "
                   "check-ins; the logged headcount is used.")
    if rc["gate_only"]:
        out.append(f"On {_n(rc['gate_only'], 'sub-day')} workers checked in but the sub is not named in that "
                   "day's daily log.")
    if rc["unassigned_checkins"]:
        out.append(f"{_n(rc['unassigned_checkins'], 'check-in')} had no company assigned; they are counted in "
                   "site totals but not attributed to a sub.")
    if rc["log_rows_no_company"]:
        out.append(f"{_n(rc['log_rows_no_company'], 'daily-log crew row')} named no company and are not "
                   "attributed to a sub.")
    if site.get("holidays"):
        out.append(f"Working days exclude {_join(site['holidays'][:3])}.")
    return out


# ── EVIDENCE: WHAT EVERY NUMBER CAN BE TRACED TO ─────────────────────────────

def evidence(rep: Dict[str, Any], checkins: List[dict], logs: List[dict]) -> List[Dict[str, Any]]:
    """The index of sources, printed in the report and stored with it: the
    gate check-in window, each daily log used (with its id, and whether it
    was amended), each regulatory record cited (number, date, link), and the
    schedule file. Ids are the system's own, so a reader with access can
    open the record; the appendix prints the short form."""
    out: List[Dict[str, Any]] = []
    n_ck = sum(1 for r in checkins if base._in(att.local_day(r.get("check_in_time")), rep["start"], rep["end"]))
    out.append({"id": "G", "kind": "checkins", "label": "Site check-ins",
                "detail": f"{n_ck} check-in records, {_span(rep['start'], rep['end'])} "
                          "(NFC / QR gate; one worker counts once a day)",
                "count": n_ck})
    out.append({"id": "L", "kind": "daily_logs", "label": "Filed daily logs",
                "detail": f"{len(logs)} daily jobsite logs filed in the period"
                          + (f", {len(rep['log_set']['amended'])} amended" if rep["log_set"]["amended"] else ""),
                "refs": [{"id": str(lg.get("_id") or ""), "date": base._d(lg.get("date")),
                          "amended": int(lg.get("_chain_length") or 1) > 1,
                          "reason": str(lg.get("_amendment_reason") or lg.get("amendment_reason") or "")[:160] or None} for lg in logs]})
    reg = rep["regulatory"]
    seen = set()
    n = 0
    for lst in ("swo_active", "open", "swo_lifted", "issued", "changed", "expiring"):
        for r in reg[lst]:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            n += 1
            r["ref_id"] = f"R{n}"
            out.append({"id": f"R{n}", "kind": "regulatory", "label": f"{r['kind']} {r['number']}".strip(),
                        "detail": f"{r['source'].upper()} record; status {r['status'] or 'not stated'}"
                                  + (f"; permits {', '.join(r['members'][:40])}" if r.get("members") else ""),
                        "record": r["id"], "row_id": r["row_id"], "link": r["link"], "issued": r["issued"]})
    plan = rep["schedule"]
    if plan and plan.get("usable"):
        out.append({"id": "S", "kind": "schedule", "label": "Project schedule",
                    "detail": (plan.get("source_name") or "Imported schedule")
                              + (f", data date {_dayy(plan['as_of'])}" if plan.get("as_of") else "")
                              + (f", confirmed by {plan['confirmed_by']}" if plan.get("confirmed_by") else "")})
    return out


# ── THE WHATSAPP MESSAGE ─────────────────────────────────────────────────────

def whatsapp_message(rep: Dict[str, Any], *, attached: bool = True, link: Optional[str] = None) -> str:
    """The short message the PDF goes with:

        588 Thomas S Boyland · Oct 2–15
        - Site: 4 subs · 9 of 9 days · avg 26 workers/day (previous 22)
        - Work: framing floors 1–4 (Arkon), risers (Quality Plumbing)
        - Regulatory: no open violations or orders
        Full report (PDF) attached.

    Only what the report itself prints: no chat, no punch list."""
    lines = [f"{rep['job']} · {rep['period_short']}"]
    site, prev = rep["site"], rep["prev"]
    if site["worked"]:
        bit = f"- Site: {_n(len(rep['subs']), 'sub')} · {site['worked']} of {site['possible']} days · " \
              f"avg {site['avg']:g} workers/day"
        if prev["days"]:
            bit += f" (previous {prev['avg']:g})"
        lines.append(bit)
    else:
        lines.append("- Site: no check-ins this period")
    work = []
    for w in rep["work"][:3]:
        good = [x for x in w["items"] if not x.get("trade_mismatch")]
        if good:
            i = good[0]
            work.append(f"{lc_first(i['work'])}{' ' + i['place'] if i['place'] else ''} ({short_name(w['name'], i['work'])})")
    if work:
        lines.append("- Work: " + ", ".join(work))
    reg = rep["regulatory"]
    if reg["coverage"]["state"] in ("verified", "partial"):
        if reg["swo_active"]:
            lines.append(f"- Regulatory: {_n(len(reg['swo_active']), 'stop work/vacate order')} ACTIVE")
        elif reg["open"]:
            lines.append(f"- Regulatory: {_n(len(reg['open']), 'open violation/complaint', 'open violations/complaints')}")
        else:
            lines.append("- Regulatory: no open violations or orders")
    plan = rep["schedule"]
    if plan and plan.get("usable") and plan["milestones"]["overdue"]:
        lines.append(f"- Schedule: {_n(len(plan['milestones']['overdue']), 'milestone')} past due")
    if attached:
        lines.append(ATTACHED_LINE)
    elif link:
        lines.append(f"Full report (PDF): {link}")
    return "\n".join(lines)


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


# ── THE SNAPSHOT ─────────────────────────────────────────────────────────────

def snapshot(rep: Dict[str, Any]) -> Dict[str, Any]:
    """The report's facts as stored with it: JSON-safe (dates as ISO strings),
    without the photographs' bytes. What was printed, the evidence it rests
    on, and the engine version -- so a report can be audited, and shown
    again, exactly as it was sent: its inputs change (a violation is
    resolved, a log is amended) and a regenerated report would not match."""
    def clean(v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items() if k != "photo"}
        if isinstance(v, (list, tuple, set)):
            return [clean(x) for x in v]
        return v
    keep = ("engine", "kind", "job", "job_full", "address", "gc", "start", "end", "generated", "length",
            "prev_start", "prev_end", "grain", "subs", "work", "site", "prev", "regulatory", "inspections",
            "schedule", "financials", "photos", "log_set", "recon", "mobilization", "upcoming", "risks",
            "status", "changes", "overview", "limitations", "data_notes", "evidence", "floor_matrix")
    snap = {k: clean(rep.get(k)) for k in keep}
    snap["photos"] = [{k: clean(v) for k, v in p.items() if k in ("key", "date", "sub", "trade", "where", "caption", "log_id")}
                      for p in rep.get("photos") or []]
    return snap


def photo_review(cands: List[Dict[str, Any]], verdicts: Dict[str, Dict[str, Any]],
                 chosen: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every photograph the vision model judged, and why it was or was not
    used -- for the people checking the report (never printed in it)."""
    picked = {c["key"] for c in chosen}
    out = []
    for c in cands:
        v = verdicts.get(c["key"])
        if v is None:
            continue
        if c["key"] in picked:
            why = "used"
        elif not v.get("ok"):
            why = f"not installed work ({v.get('kind')})"
        elif not _consistent(c, v):
            why = f"trade mismatch (sub: {c.get('trade') or c.get('sub')}; photo shows: {v.get('work')})"
        elif float(v.get("score") or 0) < MIN_SCORE:
            why = f"score {float(v.get('score') or 0):g} below {MIN_SCORE:g}"
        else:
            why = "not needed (per-sub / per-day limit or page full)"
        out.append({"sub": c["sub"], "trade": c.get("trade") or "", "date": c["date"], "where": c.get("where") or "",
                    "kind": v.get("kind"), "work": v.get("work"), "score": float(v.get("score") or 0), "why": why})
    seen, unique = set(), []
    for r in out:                       # one photo can be filed twice (original and enhanced): list it once
        k = (r["sub"], str(r["date"]), r["where"], r["kind"], r["work"], r["score"], r["why"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return sorted(unique, key=lambda r: (r["why"] != "used", r["sub"], str(r["date"])))
