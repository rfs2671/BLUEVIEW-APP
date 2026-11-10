"""DOB sign-offs: which job filings DOB has signed off, and how to say so.

THE LIVE DEFECT (Nov 9, 11:37 PM). Asked "What inspections happened in 588
since the beginning of the project", the WhatsApp assistant answered that no
inspection history was filed and that DOB passes and sign-offs "aren't in
anything I can read". NYC Open Data said otherwise: four filings on BIN 3430621
carry a Letter of Completion -- the full demolition (B01075600-I1, 2026-07-08),
the construction fence (B01074863-I1, 2026-07-22), support of excavation
(B01141294-S8, 2026-10-29) and foundation + earthwork (B01141294-S4,
2026-11-05). Those rows were in dob_logs; no tool the assistant has read them,
and the job-filing extractor threw the sign-off date away.

DOB writes "done" in several vocabularies, one per dataset:
  w9ak-ipjd (DOB NOW job filings)  'LOC Issued', 'Full Demolition Signed-off',
                                   'TA Certificate of Operation Issued',
                                   'PA Certificate of Operation Issued',
                                   'CO Issued'
  rbx6-tga4 (DOB NOW permits)      'Signed-off'
  dm9a-ab7w (DOB NOW electrical)   job_status 'Job is complete',
                                   filing_status 'Complete'
Every place that asks "is this permit still live" reads them through
is_signed_off(), so a signed-off filing is never an active permit, never a
permit "expiring", and never a "permit issued" notice because its status
happens to contain the word ISSUED.

Phrases are matched as whole words, and a negator directly before one keeps
it open ('NOT SIGNED OFF'). 'QA Review for LOC' and 'Inspection not complete
due to withdrawal' are NOT sign-offs and do not match.

Pure: no I/O.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── Is this status a sign-off? ──────────────────────────────────────────────

_SPLIT = re.compile(r"[^A-Z0-9]+")
_NEGATORS = frozenset({"NOT", "NO", "NON", "UN", "NEVER", "WITHOUT"})

#: (phrase tokens, kind). Kind picks the words the answer uses.
_PHRASES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("LOC", "ISSUED"), "loc"),
    (("SIGNED", "OFF"), "signed_off"),
    (("CERTIFICATE", "OF", "OPERATION", "ISSUED"), "cert_operation"),
    (("CO", "ISSUED"), "co"),
    (("JOB", "IS", "COMPLETE"), "electrical_complete"),
)
#: A whole status that is exactly this word (dm9a-ab7w filing_status).
_EXACT = {("COMPLETE",): "electrical_complete"}

#: The fields a dob_logs row keeps a DOB status in, permit and filing alike.
STATUS_FIELDS = ("permit_status", "filing_status", "current_status", "status",
                 "job_filing_status", "electrical_job_status")


def _tokens(status: Any) -> List[str]:
    return [t for t in _SPLIT.split(str(status or "").upper()) if t]


def signoff_kind(status: Any) -> Optional[str]:
    """'loc' / 'signed_off' / 'cert_operation' / 'co' / 'electrical_complete'
    when `status` says DOB signed the filing off, else None."""
    toks = _tokens(status)
    if not toks:
        return None
    if tuple(toks) in _EXACT:
        return _EXACT[tuple(toks)]
    for phrase, kind in _PHRASES:
        n = len(phrase)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i:i + n]) == phrase and (i == 0 or toks[i - 1] not in _NEGATORS):
                return kind
    return None


def is_signed_off(status: Any) -> bool:
    return signoff_kind(status) is not None


def row_signed_off(row: Dict[str, Any]) -> bool:
    """A dob_logs row (permit or job filing) that DOB has signed off, by any
    status field it carries."""
    return any(is_signed_off((row or {}).get(k)) for k in STATUS_FIELDS)


def _row_kind(row: Dict[str, Any]) -> Optional[str]:
    """The strongest sign-off the row states: a Letter of Completion beats a
    bare 'Signed-off' on the permit twin."""
    kinds = [signoff_kind(row.get(k)) for k in STATUS_FIELDS]
    kinds = [k for k in kinds if k]
    for k in ("loc", "cert_operation", "co", "electrical_complete", "signed_off"):
        if k in kinds:
            return k
    return None


# ── What work a filing covers ───────────────────────────────────────────────
#
# w9ak-ipjd marks each work type with a YES/NO flag. Order is the order a
# superintendent would say them.
WORK_TYPE_FLAGS: Tuple[Tuple[str, str], ...] = (
    ("full_demolition_work_type_", "full demolition"),
    ("foundation_work_type_", "foundation"),
    ("earth_work_work_type_", "earthwork"),
    ("support_of_excavation_work_type_", "support of excavation"),
    ("structural_work_type_", "structural"),
    ("general_construction_work_type_", "general construction"),
    ("mechanical_systems_work_type_", "mechanical systems"),
    ("boiler_equipment_work_type_", "boiler equipment"),
    ("plumbing_work_type", "plumbing"),
    ("sprinkler_work_type", "sprinkler"),
    ("standpipe", "standpipe"),
    ("protection_mechanical_methods_work_type_", "protection / mechanical methods"),
    ("place_of_assembly_work_type_", "place of assembly"),
    ("temporary_place_of_assembly_work_type_", "temporary place of assembly"),
    ("green_roof_work_type_", "green roof"),
    ("solar_work_type_", "solar"),
    ("antenna", "antenna"),
    ("sign", "sign"),
    ("curb_cut", "curb cut"),
    ("fence", "construction fence"),
    ("sidewalk_shed_work_type_", "sidewalk shed"),
    ("shed", "sidewalk shed"),
    ("scaffold", "scaffold"),
    ("suspended_scaffold_work_type_", "suspended scaffold"),
)


def work_types(rec: Dict[str, Any]) -> Optional[str]:
    """'foundation, earthwork' from the raw w9ak-ipjd flags, or None."""
    out: List[str] = []
    for key, label in WORK_TYPE_FLAGS:
        if str((rec or {}).get(key) or "").strip().upper() == "YES" and label not in out:
            out.append(label)
    return ", ".join(out) or None


# ── The answer ──────────────────────────────────────────────────────────────

_VERB = {
    "loc": "signed off by DOB (Letter of Completion)",
    "signed_off": "signed off by DOB",
    "cert_operation": "DOB issued the Certificate of Operation",
    "co": "DOB issued the Certificate of Occupancy",
    "electrical_complete": "electrical job marked complete by DOB",
}

#: What public data does not hold, said every time sign-offs are listed, so
#: an empty list is never read as "no inspections happened".
INSPECTIONS_NOT_PUBLIC = (
    "Not in NYC public data, so not in these records: DOB NOW inspection results "
    "(plumbing rough, fire alarm and other trade inspections) and DEP water-main "
    "inspections. Missing here does not mean they did not happen. An inspection "
    "posted in the job's WhatsApp group (what passed and the date, or the sign-off "
    "sheet with a caption) is kept in the project history as reported by the team, "
    "not DOB-verified.")


def _day(v: Any) -> Optional[date]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _filing_number(row: Dict[str, Any]) -> str:
    for k in ("job_filing_number", "job_number"):
        v = str(row.get(k) or "").strip()
        if v:
            return v.upper()
    return str(row.get("raw_dob_id") or "").strip()


def _signoff_day(row: Dict[str, Any], kind: str) -> Optional[date]:
    """DOB's own date for the sign-off: `signoff_date` (w9ak-ipjd) or the
    electrical `completion_date` of a completed job. Never the date LeveLog
    saw the row, and never a job filing's `filing_date`: that is when the job
    was FILED (B0002-I1 filed 2025-01-03 is not signed off on 2025-01-03).
    It is carried apart as `filing_date` and said as such."""
    d = _day(row.get("signoff_date"))
    if d:
        return d
    if kind == "electrical_complete":
        d = _day(row.get("electrical_completion_date"))
        if d:
            return d
    return None


def _covers(row: Dict[str, Any]) -> List[str]:
    wt = str(row.get("work_types") or "").strip()
    if wt:
        return [w.strip() for w in wt.split(",") if w.strip()]
    for k in ("work_type", "permit_subtype"):
        v = str(row.get(k) or "").strip()
        if v:
            return [v.lower()]
    desc = re.sub(r"\s+", " ", str(row.get("job_description") or "")).strip()[:90].lower()
    if row.get("electrical_job_status"):
        return [f"electrical: {desc}" if desc else "electrical"]
    return [desc] if desc else []


def _stamp(r: Dict[str, Any]) -> datetime:
    v = r.get("status_changed_at") or r.get("detected_at")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _latest(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The newest row of each record (permits keep one row per change)."""
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = str(r.get("raw_dob_id") or r.get("_id") or "")
        if rid and (rid not in best or _stamp(r) > _stamp(best[rid])):
            best[rid] = r
    return list(best.values())


def signoffs(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per signed-off filing among dob_logs rows:
    {number, kind, covers: [..], date: date|None}, oldest first (undated last).

    A filing can be stored as several rows -- one permit row per work type
    (B01141294-S4 is an Earth Work permit AND a Foundation permit) and a
    job-filing row -- so entries are joined on the filing number."""
    by_num: Dict[str, Dict[str, Any]] = {}
    for r in _latest(x for x in rows if not (x or {}).get("is_deleted")):
        if str(r.get("record_type") or "").lower() not in ("permit", "job_status"):
            continue
        kind = _row_kind(r)
        if not kind:
            continue
        num = _filing_number(r)
        if not num:
            continue
        e = by_num.setdefault(num, {"number": num, "kind": kind, "covers": [], "date": None, "filing_date": None})
        fd = _day(r.get("filing_date")) if str(r.get("record_type") or "").lower() == "job_status" else None
        if fd and (e["filing_date"] is None or fd < e["filing_date"]):
            e["filing_date"] = fd
        rank = ("loc", "cert_operation", "co", "electrical_complete", "signed_off")
        if rank.index(kind) < rank.index(e["kind"]):
            e["kind"] = kind
        for c in _covers(r):
            if c not in e["covers"]:
                e["covers"].append(c)
        d = _signoff_day(r, kind)
        if d and (e["date"] is None or d > e["date"]):
            e["date"] = d
    return sorted(by_num.values(),
                  key=lambda e: (e["date"] is None, e["date"] or date.max, e["number"]))


def signoff_line(e: Dict[str, Any]) -> str:
    covers = ", ".join(e["covers"]) or "work on this filing"
    if e["date"]:
        when = f"on {e['date'].isoformat()}"
    elif e.get("filing_date"):
        when = f"(status date unknown; filing date {e['filing_date'].isoformat()})"
    else:
        when = "(DOB's sign-off date is not on the stored record yet)"
    return f"  - {e['number']} — {covers}: {_VERB[e['kind']]} {when}"


def signoff_section(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The lines dob_status adds: every sign-off, then what is not public."""
    entries = signoffs(rows)
    if entries:
        out = [f"\nDOB sign-offs ({len(entries)}) — DOB-verified, NYC Open Data:"]
        out += [signoff_line(e) for e in entries]
    else:
        out = ["\nDOB sign-offs: none on the DOB job filings and permits LeveLog holds "
               "for this job."]
    out.append(INSPECTIONS_NOT_PUBLIC)
    return out
