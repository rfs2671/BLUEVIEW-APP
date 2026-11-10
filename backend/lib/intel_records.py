"""RECORDS-ARCHAEOLOGY ROWS -> EVIDENCE ITEMS, FOR AN OFFLINE RECONSTRUCTION.

The intel-588 records lane wrote one JSON object per real record (type,
date, company, location_text, crew_count, description, quote, fields,
provenance). This module turns those rows, the public-records timeline and
the hand-verified DOB NOW: Inspections summary into lib/evidence.py items,
so lib/construction_inference and lib/project_timeline can read them.

THE RUNG OF EACH ROW is the rung of what it IS, never of what it says:
  a filed daily-log crew row ............ reported (in_progress), source logbooks
  a report period row ("Oct 27-Nov 5") .. reported on its FIRST and LAST printed
                                          dates only; the days between are unknown
  a daily-log photo's caption ........... observed (in_progress); the caption is a
                                          vision model's, unverified, kept in note
  a gate check-in count ................. reported present, source checkins (who
                                          was on site, never where)
  an operator / named person's statement  attested
  a DOB LOC / sign-off .................. verified (its date is a paperwork date)
  DOB NOW: Inspections pass / spot check  verified; a licensed plumber's
                                          self-certification is confirmed

PLACES come from lib/location_binder.read on the filed location text, mapped
through the BUILDING MODEL: "Ground" is the model's ground level; "Underground"
under-slab work is the ground level, space "below the ground slab" (a building
with no cellar has nothing else below grade). A phrase that names its own level
("Roof MEP") is placed there, and the filed location is kept in the note
("filed location: ...") so a disagreement is visible, never resolved silently.

WORK comes from lib/work_state.classify with the crew's trade, then narrowed
by trade where the words are generic: a plumber's "MEP rough-in" is plumbing
rough-in, an electrician's is electrical, a concrete crew's "vapour barrier"
is the slab on grade, a framer's "ceiling drops" are framing.

Pure: the caller reads the files. No database, no network.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import construction_inference as CI
from lib import evidence as E
from lib import location_binder as LB
from lib import work_nodes as WN
from lib import work_state as W

YEAR = 2026
_MON = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
#: Rows that are not 588 day records or that another row already carries.
SKIP_ORIGINS = ("assistant_claim",)


def _d(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def period_dates(text: str, year: int = YEAR) -> Tuple[Optional[date], Optional[date]]:
    """"Oct 27–Nov 5" -> (Oct 27, Nov 5); "Oct 29–30" -> (Oct 29, Oct 30);
    "Nov 4" -> (Nov 4, Nov 4). Anything else -> (None, None)."""
    parts = re.findall(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})|(?<=[–\-])\s*(\d{1,2})\b", str(text or ""))
    out: List[date] = []
    month = None
    for mon, day, bare in parts:
        if mon:
            month = _MON.get(mon.lower())
            d = int(day)
        elif bare and month:
            d = int(bare)
        else:
            continue
        if month:
            try:
                out.append(date(year, month, d))
            except ValueError:
                return None, None
    if not out:
        return None, None
    return out[0], out[-1]


# ── TRADES ────────────────────────────────────────────────────────────────

def roster(records: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """company -> trade, from the project's trade-assignment rows."""
    out: Dict[str, str] = {}
    for r in records:
        f = r.get("fields") or {}
        if f.get("kind") == "roster_row_trade_assignment" and r.get("company"):
            m = re.search(r'"trade":\s*"([^"]+)"', r.get("quote") or "")
            if m:
                out[_canon(r["company"])] = m.group(1)
    return out


def _canon(company: Any) -> str:
    c = re.sub(r"\s+", " ", str(company or "")).strip()
    return {"Arkon": "Arkon Builders", "J&P": "J&P Construction"}.get(c, c)


def trade_family(company: str, trade: str = "") -> str:
    t = f"{company} {trade}".lower()
    for fam, rx in (("plumbing", r"plumb|water main"), ("electrical", r"electric|power direct|low volt"),
                    ("hvac", r"hvac|mechanical|breez"), ("concrete", r"concrete|cement|\baaz\b"),
                    ("framing", r"fram|arkon"), ("insulation", r"insulat|\ba1\b"), ("windows", r"window|slate"),
                    ("roofing", r"roof|pinnacle"), ("stucco", r"stucco|j&p"), ("scaffold", r"scaffold|j&g"),
                    ("steel", r"steel|iron"), ("cleaning", r"clean|echo")):
        if re.search(rx, t):
            return fam
    return ""


# ── WORK AND PLACE ────────────────────────────────────────────────────────

#: Slab-on-grade work by the concrete crew. "Under-slab MEP" is another
#: trade's work under the slab, not slab work.
_SLAB_WORDS = re.compile(r"(?<!under-)(?<!under )\bslab\b|vapou?r\s+barrier|\bmesh\b|\bgravel\b", re.I)
_UNDER = re.compile(r"under[\s-]?ground|under[\s-]?slab|\bexcavat\w*", re.I)
_INSPECT = re.compile(r"\binspection\b", re.I)
_OWN_LEVEL = re.compile(r"\broof\b(?!\s+protection)", re.I)


def classify(phrase: str, family: str) -> Optional[str]:
    """One node for one phrase of one crew, or None when it names no work."""
    p = phrase.strip()
    if not p:
        return None
    if family == "concrete" and _SLAB_WORDS.search(p):
        return CI.SLAB_ON_GRADE
    if family in ("plumbing", "electrical") and _UNDER.search(p):
        if _INSPECT.search(p):
            return CI.UNDERGROUND_GATE if family == "plumbing" else None
        return CI.UNDERGROUND[family]
    if family == "plumbing" and _INSPECT.search(p) and re.search(r"rough", p, re.I):
        return "gate_plumbing_rough"
    if family == "framing" and re.search(r"ceiling\s+drops?", p, re.I):
        return "framing"
    if family == "windows" and re.search(r"vapou?r\s+barrier", p, re.I):
        return "facade_envelope"
    crew = {"plumbing": "plumber", "electrical": "electrician", "hvac": "hvac"}.get(family, "")
    nodes, generic = W.classify(p, crew)
    if not nodes:
        return None
    if nodes == ["mep_trim"]:
        return "mep_trim"
    if generic or len(nodes) > 1:
        return {"plumbing": CI.PLUMBING_GENERIC, "electrical": "rough_electric", "hvac": "rough_duct"}.get(
            family, CI.PLUMBING_GENERIC if set(nodes) == {"rough_dwv", "rough_water"} else None)
    return nodes[0]


def place(location_text: Any, model: Dict[str, Any], node: Optional[str] = None,
          phrase: str = "") -> Tuple[List[str], List[str], Optional[str]]:
    """(levels, candidates, space). Candidates: levels NAMED but not in the
    model -- kept, never placed."""
    known = set(model.get("levels") or ())
    g = model.get("ground_level")
    if phrase and _OWN_LEVEL.search(phrase):
        return ["ROOF"], [], None
    r = LB.read(location_text or "")
    lv = [g if x == "GROUND" and g else x for x in r["levels"]]
    space = None
    if "FOUNDATION" in lv and "FOUNDATION" not in known:
        # The foundation is below the ground floor and under the whole
        # building, not a storey: building-wide, never an impossible level.
        lv, space = [x for x in lv if x != "FOUNDATION"], "foundation"
    if node in (CI.UNDERGROUND["plumbing"], CI.UNDERGROUND["electrical"], CI.UNDERGROUND_GATE) and g:
        lv, space = [g], "below the ground slab"
    elif not lv and r.get("unsettled") and node == CI.SLAB_ON_GRADE and g:
        lv = [g]
    levels = sorted({x for x in lv if not known or x in known})
    candidates = sorted({x for x in lv if known and x not in known})
    return levels, candidates, space


def _phrases(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"[,/;]|\band\b", str(text or "")) if p.strip()]


# ── WHO SAID IT, AND WHEN IT EXISTED ──────────────────────────────────────

#: The author of every crew row of the GC's Daily Jobsite Log, and of the
#: photos filed with those rows (the place on a photo is the row's place, typed
#: by the same person). One author is ONE source, whichever sub a row names.
CP_LOG = "GC daily jobsite log (typed and signed by the CP)"
GATE = "gate (NFC check-in)"
WALK = "punch walk (a person on site, WhatsApp)"
_FILED_DOC = re.compile(r"^(daily_jobsite|toolbox_talk|preshift_signin|osha_log|scaffold_maintenance|"
                        r"site_superintendent_log|subcontractor_orientation)/(\w+)")
_SIGNED = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def _when(text: Any) -> Optional[datetime]:
    t = str(text or "")
    try:
        return datetime.fromisoformat(t[:19].replace(" ", "T")) if re.match(r"\d{4}-\d{2}-\d{2}", t) else None
    except ValueError:
        return None


def _signed(text: Any) -> Optional[datetime]:
    m = _SIGNED.search(str(text or ""))
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").replace(hour=23, minute=59) if m else None
    except ValueError:
        return None


def doc_index(records: Iterable[Dict[str, Any]]) -> Dict[str, datetime]:
    """filed document id -> when it was signed / last amended (the later)."""
    out: Dict[str, datetime] = {}
    for r in records:
        f = r.get("fields") or {}
        m = _FILED_DOC.match(str((r.get("provenance") or {}).get("line_or_offset") or ""))
        if not m:
            continue
        when = [w for w in (_signed(f.get("cp_signature_claimed")), _when(f.get("amended_on"))) if w]
        if when:
            out[m.group(2)] = max(when + ([out[m.group(2)]] if m.group(2) in out else []))
    return out


def existed_on(r: Dict[str, Any], docs: Dict[str, datetime]) -> Optional[datetime]:
    """When this record EXISTED (never the date of the work it describes):
    a filed document's row -> its document's signature / amendment time; a
    row that carries its own creation time -> that; anything else -> the time
    it was captured (a report's tiles exist from the report's generation)."""
    m = _FILED_DOC.match(str((r.get("provenance") or {}).get("line_or_offset") or ""))
    if m and m.group(2) in docs:
        return docs[m.group(2)]
    f = r.get("fields") or {}
    for k in ("created_at_utc", "created_at", "at_utc", "when_utc", "time_utc"):
        w = _when(f.get(k))
        if w:
            return w
    return _when((r.get("provenance") or {}).get("transcript_timestamp"))


# ── ROWS -> ITEMS ─────────────────────────────────────────────────────────

def _work_items(r: Dict[str, Any], model: Dict[str, Any], pid: str, trades: Dict[str, str], *,
                kind: str, on: date, ref: str, text: str, location: Any, note: str,
                claim: str = "in_progress", said: Optional[datetime] = None,
                by: Optional[str] = CP_LOG) -> List[Dict[str, Any]]:
    company = _canon(r.get("company"))
    fam = trade_family(company, trades.get(company, ""))
    out, seen = [], set()
    for ph in _phrases(text) or [text]:
        node = classify(ph, fam)
        if not node or node in seen:
            continue
        seen.add(node)
        levels, cands, space = place(location, model, node, ph)
        if node == "site_protection":
            continue
        c = "present" if node in (CI.UNDERGROUND_GATE, "gate_plumbing_rough") else claim
        out.append(E.item(kind, c, source="photo_index" if kind == "observed" else "logbooks",
                          ref=f"{ref}:{node}", project_id=pid, node=node, levels=levels, candidates=cands,
                          space=space, sub=company or None, on=on, by=by,
                          said_at=said or datetime(on.year, on.month, on.day, 23, 59),
                          quote=text[:200], shared=len(levels) > 1,
                          note=f"{CI.FILED_LOCATION}{location or '(none)'}; trade: {trades.get(company, fam) or '?'}; {note}"))
    return out


def audit_class(a: Optional[Dict[str, Any]]) -> str:
    """original | duplicate | synthetic | derived, from one audit_flags row."""
    if not a:
        return "unaudited"
    if a.get("derived_class") == "synthetic":
        return "synthetic"
    if a.get("dup_of"):
        return "duplicate"
    return "original" if a.get("is_original") else "derived"


def items_from_records(records: Sequence[Dict[str, Any]], model: Dict[str, Any], *, project_id: str = "588",
                       audit: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(items, meta). meta: what was read, skipped and why.

    With the independent AUDIT (records/audit_flags.jsonl, by rec_id): only
    ORIGINAL rows become evidence. A duplicate is dropped (the audit's dup_of
    names the original, which is kept -- the records README's own
    duplicate_of kept the derived copy in 23 of 25 pairs, so it is ignored);
    a synthetic row is dropped; a DERIVED row (generated report, classifier
    output, bot / DM text, relayed report, LLM replay, probe aggregate) is
    kept only as SUMMARY CONTEXT in meta["summary_context"]: it never becomes
    an evidence item, so it can never support a fact or be an independent
    signal. Without the audit: every row the records README did not mark a
    duplicate (the pre-audit behaviour)."""
    trades = roster(records)
    if audit is None:
        return _items(records, model, project_id, trades, readme_dups=True)
    cls = {str(r.get("id")): audit_class(audit.get(str(r.get("id")))) for r in records}
    originals = [r for r in records if cls[str(r.get("id"))] == "original"]
    derived = [r for r in records if cls[str(r.get("id"))] == "derived"]
    docs = doc_index(records)
    items, meta = _items(originals, model, project_id, trades, readme_dups=False, docs=docs)
    summ, _ = _items(derived, model, project_id, trades, readme_dups=False, docs=docs)
    meta["summary_context"] = [{"ref": i["ref"], "on": i.get("on"), "sub": i.get("sub"), "node": i.get("node"),
                                "levels": i.get("levels"), "quote": (i.get("quote") or "")[:120],
                                "derived_class": (audit.get(i["ref"].split(":")[0]) or {}).get("derived_class"),
                                "use": "summary context only: never evidence, never a signal"} for i in summ]
    from collections import Counter as _C
    meta["audit_classes"] = dict(_C(cls.values()))
    return items, meta


def _items(records: Sequence[Dict[str, Any]], model: Dict[str, Any], project_id: str, trades: Dict[str, str], *,
           readme_dups: bool, docs: Optional[Dict[str, datetime]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    docs = doc_index(records) if docs is None else docs
    items: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = defaultdict(int)
    for r in records:
        if (readme_dups and r.get("duplicate_of")) or r.get("origin") in SKIP_ORIGINS:
            skipped["duplicate_or_assistant_claim"] += 1
            continue
        t, f = r.get("type"), r.get("fields") or {}
        d = _d(r.get("date"))
        rid = str(r.get("id"))
        said = existed_on(r, docs)
        if t == "daily_log_activity" and f.get("kind") == "period_work_item":
            if f.get("first"):
                a, b = _d(f.get("first")), _d(f.get("last"))
            else:
                a, b = period_dates(f.get("dates") or "")
            for tag, day in (("first", a), ("last", b)):
                if day and not (tag == "last" and day == a):
                    items += _work_items(r, model, project_id, trades, kind="reported", on=day, ref=f"{rid}:{tag}",
                                         text=r.get("description") or "", location=r.get("location_text"),
                                         note=f"report period row, {tag} printed date; days between unknown", said=said)
            continue
        if t == "daily_log_activity" and f.get("kind") == "crew_day_activity_ids" and d:
            continue                                        # the same crew rows, re-read as ids: not a second record
        if t == "daily_log_activity" and d and r.get("company"):
            text = r.get("description") or ""
            if not text:
                skipped["crew_row_without_description"] += 1
                continue
            items += _work_items(r, model, project_id, trades, kind="reported", on=d, ref=rid, text=text,
                                 location=r.get("location_text"),
                                 note="amended document" if f.get("amended_doc") else "filed daily log crew row",
                                 said=said)
            continue
        if t == "photo" and d and r.get("company") and (f.get("kind") in ("report_visual_progress_tile", "progress")):
            text = r.get("description") or ""
            if f.get("kind") == "progress":
                text = str(f.get("sees") or "")
            items += _work_items(r, model, project_id, trades, kind="observed", on=d, ref=rid, text=text,
                                 location=r.get("location_text"),
                                 note="photo filed with this crew's log row; caption by a vision model, unverified",
                                 said=said)
            continue
        if t == "photo" and "walk_item" in f and d:
            tag = str(f.get("floor_tag") or "")
            # The walk's floor / area / trade TAGS are set by the bot that bound
            # each photo (independent audit 2026-11-10: "floor/area/trade tags
            # are bot-inferred"), so a tag is never a person's word: the place
            # is only what the person's own caption names. A row may say the
            # tag was set by a person (`floor_tag_by: "person"`); then it counts.
            guessed = f.get("floor_tag_by") != "person"
            caption = str(f.get("caption_text") or "")
            src_text = caption if guessed else (f"floor {tag}" if tag and tag.isdigit() else tag)
            levels, cands, _ = place(src_text, model)
            items.append(E.item("observed", "present", source="photo_index", ref=rid, project_id=project_id,
                                levels=levels, candidates=cands, on=d, quote=caption[:160], by=WALK, said_at=said,
                                note=(f"punch-walk photo; floor tag '{tag}' was GUESSED by the bot, so the place is "
                                      f"only what the caption says" if guessed else
                                      f"punch-walk photo; floor tag '{tag}' set by the person")))
            continue
        if t == "checkin_aggregate" and d and isinstance(f.get("by_company"), dict) and "doc" not in f \
                and f.get("kind") not in ("preshift_signin_doc",):
            for co, n in f["by_company"].items():
                if n and _canon(co) not in ("Not yet assigned", "(no company)"):
                    items.append(E.item("reported", "present", source="checkins", ref=f"{rid}:{_canon(co)}",
                                        project_id=project_id, sub=_canon(co), on=d, by=GATE, said_at=said,
                                        note=f"gate check-ins: {n}"))
            continue
        if t == "inspection_statement" and d:
            q = r.get("quote") or ""
            if re.search(r"DOB\s+underground\s+plumbing", q, re.I):
                g = model.get("ground_level")
                items.append(E.item("reported", "present", source="logbooks", ref=rid, project_id=project_id,
                                    node=CI.UNDERGROUND_GATE, levels=[g] if g else [], on=d, quote=q[:200],
                                    by=CP_LOG, said_at=said,
                                    note="a log field names a DOB underground plumbing inspection visit; no result stated"))
            elif r.get("origin") == "operator_statement" and isinstance(f.get("results"), dict):
                for what, res in f["results"].items():
                    node = {"plumbing rough-in": "gate_plumbing_rough", "demolition sign-off inspection": "demolition",
                            "water main": "site_utilities", "fire alarm": "gate_ls_fire_alarm"}.get(what)
                    claim = {"passed": "done", "scheduled": "scheduled"}.get(str(res))
                    if node and claim:
                        items.append(E.item("attested", claim, source="whatsapp", ref=f"{rid}:{node}",
                                            project_id=project_id, node=node, on=d, by="operator", quote=q[:200],
                                            note="operator statement; names no floor"))
            continue
        skipped[f"type:{t}"] += 1
    return items, {"read": len(records), "items": len(items), "skipped": dict(skipped), "roster": trades}


#: Text that states an inspection RESULT ("rough ins dob passed", "water main
#: inspection passed", "signed off"). A record carrying one is left out of a
#: blind run whatever its date.
_RESULT = re.compile(
    r"\b(?:rough|under\s?ground|water\s+main|fire\s+alarm|sign[\s-]?off|inspection|inspections)\b[^.\n]{0,60}?"
    r"\b(?:pass(?:ed|es)?|fail(?:ed|s)?|certified|signed\s+off|approved)\b"
    r"|\b(?:pass(?:ed)?|fail(?:ed)?)\b[^.\n]{0,40}?\b(?:rough|inspection)\b", re.I)
#: Files that are GENERATED report output (an engine's rendering of rows),
#: as opposed to a capture of filed documents.
GENERATED_SOURCES = ("progress_report_real", "activity_backtest")
STRICTNESS = ("conservative", "strictest")
#: Not a blind run: only the record's own date is checked. Kept to MEASURE how
#: much the leakage filter changes the answer, never to report a score.
DATES_ONLY = "dates_only_leaky"


def _ts(r: Dict[str, Any]) -> Optional[date]:
    return _d(((r.get("provenance") or {}).get("transcript_timestamp") or "")[:10])


def leak_reasons(r: Dict[str, Any], cutoff: date, *, strictness: str = "conservative",
                 audit: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    """Why a record may NOT be seen by a blind run as of `cutoff` ([] = it may).

    conservative: dated after the cutoff; captured / said after the cutoff
      (we cannot show the text existed in that form on the cutoff day: the
      Oct 27-Nov 9 report was generated 2026-11-09); a bot / DM answer; an
      operator statement about inspections; any text stating an inspection
      result; an audit flag leaks_inspection_result.
    strictest: also every row of a generated report, even one generated
      before the cutoff (the Oct 1-19 report of 2026-10-21)."""
    out = []
    f = r.get("fields") or {}
    d, ts = _d(r.get("date")), _ts(r)
    if d and d > cutoff:
        out.append(f"dated {d} (after the cutoff)")
    if strictness == DATES_ONLY:
        return out
    if ts and ts > cutoff:
        out.append(f"captured/said {ts} (after the cutoff)")
    if r.get("origin") == "assistant_claim":
        out.append("assistant claim, not a record")
    if r.get("type") == "whatsapp" or f.get("bot_answer_logged_in_production") or f.get("path") \
            or f.get("sender_role") == "bot" or "replay_answers" in f:
        out.append("bot / DM answer or replay")
    if r.get("origin") == "operator_statement" and r.get("type") == "inspection_statement":
        out.append("operator statement about inspections")
    text = " ".join(str(x) for x in (r.get("quote"), r.get("description"), json.dumps(f, default=str)) if x)
    if _RESULT.search(text):
        out.append("states an inspection result")
    a = (audit or {}).get(str(r.get("id"))) or {}
    if a.get("leaks_inspection_result"):          # "direct", "dob_signoff_state: ...", "borderline: ..."
        out.append(f"audit leak flag: {str(a['leaks_inspection_result'])[:60]}")
    if strictness == "strictest":
        src = str((r.get("provenance") or {}).get("source_file") or "")
        if any(g in src for g in GENERATED_SOURCES) or f.get("kind") in ("period_work_item", "sub_period_summary",
                                                                         "report_visual_progress_tile"):
            out.append("generated report row")
    return out


def blind_records(records: Sequence[Dict[str, Any]], cutoff: date, *, strictness: str = "conservative",
                  audit: Optional[Dict[str, Dict[str, Any]]] = None
                  ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(kept, excluded with reasons)."""
    kept, excluded = [], []
    for r in records:
        why = leak_reasons(r, cutoff, strictness=strictness, audit=audit)
        if why:
            excluded.append({"id": r.get("id"), "type": r.get("type"), "date": r.get("date"), "reasons": why})
        else:
            kept.append(r)
    return kept, excluded


def headcounts(records: Sequence[Dict[str, Any]], *, readme_dups: bool = True) -> List[Dict[str, Any]]:
    """Per day and company: the daily log's crew count vs the gate count, when
    both are on record. Amended documents replace the original's rows."""
    logs: Dict[Tuple[date, str], Dict[str, Any]] = {}
    amended_days = {(_d(r.get("date"))) for r in records if (r.get("fields") or {}).get("amended_doc")}
    for r in records:
        f = r.get("fields") or {}
        d = _d(r.get("date"))
        if r.get("type") != "daily_log_activity" or not d or not r.get("company") \
                or (readme_dups and r.get("duplicate_of")) \
                or not isinstance(r.get("crew_count"), int) or f.get("kind"):
            continue
        if d in amended_days and not f.get("amended_doc") and "amended_doc" in f:
            continue
        k = (d, _canon(r["company"]))
        e = logs.setdefault(k, {"n": 0, "refs": []})
        e["n"] += r["crew_count"]
        e["refs"].append(r["id"])
    gates: Dict[Tuple[date, str], Tuple[int, str]] = {}
    for r in records:
        f = r.get("fields") or {}
        d = _d(r.get("date"))
        if r.get("type") == "checkin_aggregate" and d and isinstance(f.get("by_company"), dict) and "doc" not in f \
                and not (readme_dups and r.get("duplicate_of")) and r.get("origin") != "assistant_claim":
            for co, n in f["by_company"].items():
                gates.setdefault((d, _canon(co)), (n, r["id"]))
    out = []
    for (d, co), e in sorted(logs.items()):
        if (d, co) in gates:
            g, gref = gates[(d, co)]
            out.append({"date": d, "sub": co, "log_count": e["n"], "gate_count": g, "refs": e["refs"] + [gref]})
    return out


# ── PUBLIC RECORDS ────────────────────────────────────────────────────────

DOB_NOW_INSPECTIONS = "DOB NOW: Inspections"
_SIGNOFF_NODE = (("demolition", "demolition"), ("fence", "site_protection"), ("foundation", "foundation"),
                 ("earth_work", "foundation"))
#: Filings whose work type is not flagged in the public row, named by the
#: public-records lane's README (B01141294-S8 = support of excavation).
_FILING_NODE = {"B01141294-S8": "excavation_soe"}


def items_from_public(rows: Sequence[Dict[str, Any]], *, project_id: str = "588") -> List[Dict[str, Any]]:
    """Sign-offs (LOC) from the public timeline as verified. DOB NOW:
    Inspections rows are NOT read here (items_from_dob_now reads them), so a
    blind run can leave them out by not calling it."""
    out = []
    for r in rows:
        if r.get("kind") != "signoff" or DOB_NOW_INSPECTIONS in str(r.get("source_dataset") or ""):
            continue
        d = _d(r.get("date"))
        wt = str(r.get("work_type") or "").lower()
        node = _FILING_NODE.get(str(r.get("job_or_permit_no"))) or next((n for k, n in _SIGNOFF_NODE if k in wt), None)
        if not d or not node:
            continue
        out.append(E.item("verified", "done", source="dob_logs", ref=str(r.get("job_or_permit_no")),
                          project_id=project_id, node=node, on=d, said_at=datetime(d.year, d.month, d.day, 23, 59),
                          quote=f"{r.get('work_type')}: {r.get('status_text_verbatim')}",
                          note="LOC date is a paperwork date, not the date of the work"))
    return out


_DOB_LEVEL = {"MEZ": "MEZZANINE", "ROF": "ROOF"}


def dob_level(code: str) -> Optional[str]:
    if code in _DOB_LEVEL:
        return _DOB_LEVEL[code]
    return f"FLOOR_{int(code)}" if code.isdigit() else None


def items_from_dob_now(doc: Dict[str, Any], *, project_id: str = "588") -> List[Dict[str, Any]]:
    """The hand-verified DOB NOW: Inspections summary. The floor results table
    is undated; a PASSED rough cell takes the date of the one inspection whose
    comment covers it (the PL 'requested floors' inspection). Underground
    CERTIFIED = a licensed plumber's self-certification (confirmed); the DOB
    spot check of it = verified."""
    out = []
    pl = doc.get("plumbing_permit_B01141294-S5-PL") or {}
    done = {c.get("id"): c for c in pl.get("completed_inspections") or ()}
    rough = done.get("7755632") or {}
    rough_on = _d(rough.get("resulted"))
    under_on = _d((done.get("7681636") or {}).get("resulted"))
    for code, cells in (pl.get("floor_results_table_UNDATED") or {}).items():
        lv = dob_level(code)
        for cell, res in cells.items():
            if "ROUGH" in cell and res == "PASSED" and rough_on and lv:
                out.append(E.item("verified", "done", source="dob_now_inspections", ref=f"7755632:{code}:{cell}",
                                  project_id=project_id, node="gate_plumbing_rough", levels=[lv], on=rough_on,
                                  quote=f"{cell} PASSED (floor {code})", note="DOB inspection 7755632; not a sign-off"))
            elif "UND GRND" in cell and res == "CERTIFIED" and under_on and lv:
                out.append(E.item("confirmed", "done", source="dob_now_inspections", ref=f"selfcert:{code}:{cell}",
                                  project_id=project_id, node=CI.UNDERGROUND_GATE, levels=[lv], on=under_on,
                                  quote=f"{cell} CERTIFIED (floor {code})", by="licensed master plumber",
                                  note="licensed plumber self-certification"))
            elif "UND GRND" in cell and res == "PASSED" and code == "OSP" and rough_on:
                out.append(E.item("verified", "done", source="dob_now_inspections", ref=f"7755632:OSP:{cell}",
                                  project_id=project_id, node="site_utilities", on=rough_on,
                                  quote=f"{cell} PASSED (open space)", note="DOB inspection 7755632 (OSP rough)"))
    for adv in doc.get("advance_notices") or ():
        sc = adv.get("dob_spot_check") or {}
        d = _d(sc.get("resulted"))
        if d and "Pass" in str(sc.get("result")):
            floors = {re.sub(r".*floor\s+", "", s) for s in adv.get("inspections") or ()}
            levels = [lv for lv in (dob_level(f) for f in floors) if lv]
            node = CI.UNDERGROUND_GATE if levels else "site_utilities"
            out.append(E.item("verified", "done", source="dob_now_inspections", ref=str(sc.get("id")),
                              project_id=project_id, node=node, levels=levels, on=d,
                              quote=f"{sc.get('result')}: {'; '.join(adv.get('inspections') or [])}",
                              note=f"DOB spot check of advance notice {adv.get('record')}"))
    return out
