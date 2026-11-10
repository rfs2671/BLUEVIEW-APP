"""WHAT THE PROGRESS ENGINE CAN STAND ON, FOR ONE JOB: numbers, not opinions.

Pure: no database, no network. scripts/progress_validation.py loads one job's
records READ-ONLY and hands them in as one dict (see `JobData` below); this
module turns them into SECTIONS of metrics, each weak metric with one line of
what to do, and a READINESS table.

THE SECTIONS ARE A REGISTRY. Each is a function `(data) -> section` registered
with `@section("name")`, run in registration order. A lane that adds a source
or a capability adds ONE function (and, if it needs more records, one key in
the loader) and touches no other section:

    @section("forecast")
    def _forecast(data): ...

A section is {"name", "rows": [(label, value)], "todo": [what to do],
"lists": [(title, [(text, count)])], "raw": {numbers readiness reads}}.

WHAT MAY BE PRINTED: counts, ids, dates, shares and level tokens. Work phrases
and location strings are site words and are printed (owner, 2026-11-10), after
`redact`. Never a person's name, a phone number, an email or a quote: the
work-state sample is passed through `redact_answer` (reporters become roles,
inspectors and quotes are withheld) and every free-text line through `redact`.

A COUNT OVER A FIELD NO ROW CARRIES IS NOT A ZERO. `absent()` is checked before
counting on a stored field, and the line says "field not stored" instead
(scripts/probe_helpers.py: four probes reported a missing field as a finding).

THRESHOLDS are review triggers chosen here, not measured: each says so.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import inspection_reports as IR
from lib import photo_place as PL
from lib import progress_plan as PP
from lib import project_report as PR
from lib import work_state as W
from lib.plans import level_suggestion as LS

READY, NEEDS_DATA, BLOCKED = "ready", "needs data", "blocked"

#: Review triggers, NOT measured: below these a metric is called weak.
THRESHOLDS = {
    "one_level_share": 0.25,       # phrases naming exactly one level
    "sequence_share": 0.50,        # phrases matching a step of the sequence
    "photo_exact_share": 0.25,     # photos with a sufficient place
    "validated_share": 0.80,       # inspection rows whose result was read back
    "gate_share": 0.50,            # inspection rows on a tracked gate
    "pred_coverage": 0.50,         # schedule activities carrying the file's logic
    "mapped_share": 0.50,          # schedule activities mapped to work + level
}
TOP = 10
SIGNED_OFF = re.compile(r"\bsign(?:ed)?[\s-]?off\b|\bloc\s+issued\b|\bletter\s+of\s+completion\b", re.I)

#: data = {
#:   "job": {"project_id", "company_id", "building_stories"},
#:   "window": {"start": date, "today": date, "days": int},
#:   "logs": [filed head docs], "acts": [progress_report._log_activities rows],
#:   "index": [photo_index rows, kind photo, this job], "log_ids": {effective head ids},
#:   "spaces": {plan tags}, "confirmations": {photo_key: [answers]},
#:   "relations": int, "relations_enabled": bool,
#:   "inspections": [inspection_reports rows], "dob_rows": [dob_logs rows],
#:   "schedule": confirmed doc | None, "schedule_drafts": int,
#:   "proposed": proposed_sequences doc | None,
#:   "samples": [{"work", "level", "text"}],   # already redacted
#:   "prompt_v": photo_search.PROMPT_V, "reread_tries": PHOTO_INDEX_TRIES,
#: }
JobData = Dict[str, Any]
Section = Dict[str, Any]

_SECTIONS: List[Tuple[str, Callable[[JobData], Section]]] = []


def section(name: str):
    def deco(fn: Callable[[JobData], Section]) -> Callable[[JobData], Section]:
        _SECTIONS.append((name, fn))
        return fn
    return deco


def section_names() -> List[str]:
    return [n for n, _ in _SECTIONS]


# ── SMALL HELPERS ──────────────────────────────────────────────────────────

def share(n: int, d: int) -> str:
    return f"{n}/{d} ({100.0 * n / d:.0f}%)" if d else f"{n}/0 (no rows)"


def ratio(n: int, d: int) -> Optional[float]:
    return n / d if d else None


def weak(n: int, d: int, key: str) -> bool:
    """Below its review trigger. No rows is not weak here: readiness says it."""
    return bool(d) and n / d < THRESHOLDS[key]


def absent(rows: Sequence[Dict[str, Any]], field: str) -> bool:
    """True when there are rows and none of them carries `field` at all."""
    return bool(rows) and not any(isinstance(r, dict) and field in r for r in rows)


def mix(values: Iterable[Any]) -> str:
    c = Counter(str(v) for v in values)
    return ", ".join(f"{k} {n}" for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CONFIRMED_BY = re.compile(r"confirmed by [^;)\n|]+")
_THEIR_WORDS = re.compile(r'their words: "[^"\n]*"')


def redact(text: Any, names: Iterable[str] = ()) -> str:
    """No email, phone number, person's name or quote. `names`: every person
    name the loader knows for this job (users of the company, reporters,
    people who confirmed a photo), replaced whole-word, case-insensitive."""
    t = _EMAIL.sub("[email]", str(text or ""))
    t = PR._PHONE.sub("[number]", t)           # project_report's one phone pattern; layout kept
    t = _THEIR_WORDS.sub("their words: [withheld]", t)
    t = _CONFIRMED_BY.sub("confirmed by a person", t)
    for name in sorted({" ".join(str(n).split()) for n in names if n and len(str(n).strip()) >= 2},
                       key=len, reverse=True):
        t = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", "[person]", t, flags=re.I)
    return t


def role_words(role: Any) -> str:
    r = str(role or "").strip().lower()
    return {"admin": "an admin", "owner": "an admin", "pm": "a PM", "cp": "a CP",
            "superintendent": "a superintendent"}.get(r, "a person")


def redact_answer(answer: Dict[str, Any], roles_by_name: Dict[str, str]) -> Dict[str, Any]:
    """A work_state.what_holds answer with every inspection reporter replaced
    by their role, the inspector and their words withheld. Photos keep what
    they show (the index prompt forbids names). EVERY person field of a gate
    read is cleaned, the later statements (`later`) as well: who someone
    heard it from (`hearsay_from`), who relayed it (`relayed_from`), each
    later statement's reporter and words."""
    out = dict(answer)

    def person(g: Dict[str, Any]) -> Dict[str, Any]:
        g = dict(g)
        if "who" in g:
            g["who"] = roles_by_name.get(str(g.get("who") or ""), "a person")
        for k in ("inspector", "hearsay_from", "relayed_from"):
            if g.get(k):
                g[k] = "[withheld]"
        if g.get("quote"):
            g["quote"] = None
        return g

    def clean(g: Dict[str, Any]) -> Dict[str, Any]:
        g = person(g)
        if g.get("later"):
            g["later"] = [person(r) for r in g["later"]]
        return g
    out["gates"] = [clean(g) for g in answer.get("gates") or []]
    out["other_inspections"] = [clean(g) for g in answer.get("other_inspections") or []]
    return out


def _floor_n(token: str) -> Optional[int]:
    return int(token[len(LS.FLOOR_PREFIX):]) if token.startswith(LS.FLOOR_PREFIX) else None


def sample_levels(acts: Sequence[Dict[str, Any]]) -> List[str]:
    """FLOOR_3 (the owner's question) and the two other levels the logs name
    alone most often, else FLOOR_2 / FLOOR_4."""
    seen = Counter(r["levels"][0] for r in W.evidence_rows(acts) if len(r["levels"]) == 1)
    others = [lv for lv, _n in seen.most_common() if lv != "FLOOR_3"]
    others += [lv for lv in ("FLOOR_2", "FLOOR_4", "FLOOR_5") if lv not in others]
    return ["FLOOR_3"] + others[:2]


# ── LOGS ───────────────────────────────────────────────────────────────────

@section("logs")
def _logs(d: JobData) -> Section:
    rows = W.evidence_rows(d.get("acts") or [])
    c = W.coverage(rows, [])
    n = c["phrases"]
    stories = d["job"].get("building_stories")
    try:
        stories = int(stories) if stories not in (None, "") else None
    except (TypeError, ValueError):
        stories = None
    outside = None
    if stories:
        outside = sum(1 for r in rows if any((_floor_n(lv) or 0) > stories for lv in r["levels"]))
    shared = sum(1 for r in rows if len(r["levels"]) > 1)
    logs = d.get("logs") or []
    amended = sum(1 for lg in logs if int(lg.get("_chain_length") or 1) > 1)
    out: Section = {"name": "logs", "rows": [
        ("window", f"{d['window']['start']} to {d['window']['today']} ({d['window']['days']} days)"),
        ("filed daily logs (effective heads)", len(logs)),
        ("of them amended (an amendment is the record)", amended),
        ("crew rows", len(d.get("acts") or [])),
        ("work phrases", n),
        ("phrases naming any level", share(c["name_a_level"], n)),
        ("phrases naming exactly one level", share(c["name_one_level"], n)),
        ("phrases naming several levels (shared)", share(shared, n)),
        ("phrases naming a level not in the project",
         share(outside, n) if outside is not None else "unknown: the project has no building_stories"),
        ("phrases matching the work sequence", share(c["match_sequence"], n)),
        ("of those, generic only (trade, not part)", share(c["generic_only"], c["match_sequence"])),
        ("levels named (phrases)", ", ".join(f"{k} {v}" for k, v in c["levels"].items()) or "none"),
    ], "todo": [], "lists": [
        ("top unmatched phrases", c["not_matched"][:TOP]),
        ("top unplaced location strings", [(w or "(blank)", k) for w, k in c["not_placed"][:TOP]]),
    ], "raw": {"logs": len(logs), "phrases": n, "one_level": c["name_one_level"], "matched": c["match_sequence"],
               "any_level": c["name_a_level"], "outside": outside, "generic": c["generic_only"]}}
    todo = out["todo"]
    if not logs:
        todo.append("No filed daily log in the window: nothing to answer from. File daily logs (or widen --days).")
    if weak(c["name_one_level"], n, "one_level_share"):
        todo.append("Few phrases name ONE level: ask CPs to fill the location as one floor per crew row "
                    "('3rd floor', not 'floors 1-4'); see the unplaced strings below.")
    if weak(c["match_sequence"], n, "sequence_share"):
        todo.append("Many phrases match no step of the sequence: review the unmatched list; a recurring site word "
                    "is a candidate for lib/work_state._SPECIFIC.")
    if c["match_sequence"] and c["generic_only"] / c["match_sequence"] >= 0.5:
        todo.append("Half or more of the matched phrases name only a trade ('Plumbing', 'MEP'): ask for the part "
                    "('domestic water rough', 'DWV').")
    if not stories:
        todo.append("Set building_stories on the project so a floor above the building can be flagged.")
    elif outside:
        todo.append(f"{outside} phrase(s) name a floor above the building's {stories} stories: a typo or a wrong "
                    "building_stories; check the log rows.")
    return out


# ── PHOTOS ─────────────────────────────────────────────────────────────────

_SOURCES = ("log_row", "plan_tag", "floor_marking", "confirmation", "lent")


@section("photos")
def _photos(d: JobData) -> Section:
    index = d.get("index") or []
    log_ids = d.get("log_ids")
    photos = W.photo_rows(index, log_ids, spaces=d.get("spaces") or {}, confirmations=d.get("confirmations") or {})
    n = len(photos)
    certainty = Counter(p["place"]["certainty"] for p in photos)
    exact = sum(certainty[k] for k in PL.SUFFICIENT)
    constrained = certainty[PL.CONSTRAINED]
    one = [p for p in photos if len(p["levels"]) == 1 and PL.is_sufficient(p["place"])]
    by_source = {s: sum(1 for p in one if any(e.get("used") and e.get("source") == s for e in p["place"]["evidence"]))
                 for s in _SOURCES}
    want_v = d.get("prompt_v")
    tries = int(d.get("reread_tries") or 3)
    if absent(index, "prompt_v"):
        prompt_mix = "field not stored on any row (every row predates the place prompt)"
    else:
        prompt_mix = mix(r.get("prompt_v", "absent") for r in index)
    old = [r for r in index if r.get("prompt_v") != want_v and len(W.places_in(r.get("where"))["levels"]) != 1]
    pending = [r for r in old if int(r.get("reread_tries") or 0) < tries]
    out: Section = {"name": "photos", "rows": [
        ("indexed photos (this job)", len(index)),
        ("of them on the window's filed logs (what work_status reads)", n),
        ("index prompt version mix", prompt_mix),
        ("re-read backlog (older prompt, row names several levels or none)",
         f"{len(old)} ({len(pending)} still to be tried, {len(old) - len(pending)} given up after {tries} tries)"),
        ("place certainty: exact (confirmed/inferred/lent)", share(exact, n)),
        ("place certainty: constrained (several levels, none chosen)", share(constrained, n)),
        ("place certainty: none (suggested/conflict/unknown)", share(n - exact - constrained, n)),
        ("place certainty, every value", mix(p["place"]["certainty"] for p in photos)),
    ] + [(f"placed to one level using {s.replace('_', ' ')}", share(by_source[s], n)) for s in _SOURCES] + [
        ("views", mix(p.get("view") for p in photos)),
        ("inside photos with no level (could be asked)", sum(1 for p in photos if PL.wants_floor(p, p["place"]))),
        ("photo relation rows", d.get("relations", 0)),
        ("photo relations switched on", f"{bool(d.get('relations_enabled'))}; thresholds set: "
                                        f"{bool(d.get('relations_ready'))}"),
    ], "todo": [], "lists": [], "raw": {"photos": n, "indexed": len(index), "exact": exact,
                                        "backlog": len(old), "pending": len(pending), "relations": d.get("relations", 0),
                                        "relations_ready": bool(d.get("relations_ready"))}}
    todo = out["todo"]
    if not index:
        todo.append("No photo of this job is indexed: check PHOTO_INDEX_DISABLED and the photo-index tick log.")
    elif not n:
        todo.append("Indexed photos exist but none is on a filed log of the window (superseded, withdrawn or older).")
    if weak(exact, n, "photo_exact_share"):
        todo.append("Few photos have a place: one floor per crew row on the log places every photo filed under it; "
                    "a reply to 'Floor not on record' confirms one.")
    if pending:
        todo.append(f"{len(pending)} photo(s) wait for the place re-read: it drains from the tick's leftover budget.")
    if d.get("relations") and not d.get("relations_ready"):
        todo.append("Photo relation rows exist while the thresholds are unset: they were not made by the tick; "
                    "find who wrote them.")
    return out


# ── INSPECTIONS ────────────────────────────────────────────────────────────

@section("inspections")
def _inspections(d: JobData) -> Section:
    rows = d.get("inspections") or []
    n = len(rows)
    audited = [r for r in rows if isinstance(r.get("validation"), dict)]
    agree = sum(1 for r in audited if r["validation"].get("agree"))
    gated = sum(1 for r in rows if r.get("gate"))
    state = IR.current_state(rows)
    reasons = Counter(str(r["validation"].get("reason")) for r in audited if not r["validation"].get("agree"))
    filings = [r for r in d.get("dob_rows") or [] if r.get("record_type") == "job_status"]
    signed = [r for r in filings if SIGNED_OFF.search(str(r.get("filing_status") or r.get("current_status") or ""))]
    if absent(filings, "signoff_date"):
        dated = "field not stored on any filing row of this job"
        with_date = None
    else:
        with_date = sum(1 for r in signed if r.get("signoff_date"))
        dated = f"{with_date} with signoff_date, {len(signed) - with_date} without"
    out: Section = {"name": "inspections", "rows": [
        ("inspection_reports rows", n),
        ("by status", mix(r.get("status") for r in rows)),
        ("by source", mix(r.get("source") for r in rows)),
        ("rows carrying the read-back check", share(len(audited), n)),
        ("validated (words agree with the model)", share(agree, n)),
        ("on a tracked gate", share(gated, n)),
        ("current (gate, level) reads", f"{len(state)}: {mix(IR._status(r) for r in state.values())}"),
        ("DOB job filings (job_status rows)", len(filings)),
        ("of them signed off", len(signed)),
        ("sign-off dates", dated),
    ], "todo": [], "lists": [("why a row was left unresolved", reasons.most_common(TOP))],
        "raw": {"rows": n, "agree": agree, "gated": gated, "gate_reads": len(state), "signed": len(signed),
                "signed_dated": with_date, "audited": len(audited)}}
    todo = out["todo"]
    if not n:
        todo.append("No inspection was reported for this job: every gate reads UNKNOWN. Tell field staff to text "
                    "'plumbing rough passed on 3' (or send the sign-off) to the assistant.")
    if n and len(audited) < n:
        todo.append(f"{n - len(audited)} row(s) predate the read-back check: their result is the model's claim.")
    if weak(agree, n, "validated_share"):
        todo.append("Many reports were left unresolved: read the reasons below; ask the reporters the one question.")
    if weak(gated, n, "gate_share"):
        todo.append("Many reports name no tracked gate ('plumbing inspection' without rough/final): they are kept "
                    "as said and move no gate.")
    if filings and not signed:
        todo.append("DOB filings exist and none is signed off: nothing verified to show yet.")
    if with_date is None and filings:
        todo.append("No filing row stores a signoff_date: the verified rung has no source until it is ingested.")
    return out


# ── SCHEDULE ───────────────────────────────────────────────────────────────

@section("schedule")
def _schedule(d: JobData) -> Section:
    sched = d.get("schedule")
    acts = [a for a in (sched or {}).get("activities") or [] if a.get("kind") != "summary"]
    n = len(acts)
    linked = [a for a in acts if isinstance(a.get("predecessors"), list)]
    unknown = n - len(linked)
    lost = sum(int(a.get("predecessors_unresolved") or 0) for a in acts)
    places = [PP.activity_place(a) for a in acts]
    mapped = sum(1 for p in places if p["nodes"] and p["levels"])
    work_only = sum(1 for p in places if p["nodes"] and not p["levels"])
    today = d["window"]["today"]
    la = PP.lookahead(sched, [], today=today, days=14) if sched else None
    prop = d.get("proposed") or {}
    rows = [
        ("confirmed schedule on file", bool(sched)),
        ("drafts waiting for confirmation", d.get("schedule_drafts", 0)),
    ]
    if sched:
        rows += [
            ("format / data date", f"{sched.get('format')} / {sched.get('data_date') or 'not stated'}"),
            ("activities (non-summary)", n),
            ("milestones", sum(1 for a in acts if a.get("kind") == "milestone")),
            ("carrying the file's predecessor logic", share(len(linked), n)),
            ("listing no predecessor (file has logic)", sum(1 for a in linked if not a["predecessors"])),
            ("logic unknown (file carries none)", unknown),
            ("predecessor links", sum(len(a["predecessors"]) for a in linked)),
            ("unresolved links (left out)", lost),
            ("mapped to a work package AND a level", share(mapped, n)),
            ("mapped to a work package, no level", work_only),
            ("planned in the next 14 days (lookahead items)", len(la["items"]) if la else 0),
            ("with no planned date", la["undated"] if la else 0),
        ]
    rows += [("proposed sequence", prop.get("status") or "none stored"),
             ("proposed sequence levels", len(prop.get("levels") or []))]
    out: Section = {"name": "schedule", "rows": rows, "todo": [], "lists": [],
                    "raw": {"confirmed": bool(sched), "activities": n, "linked": len(linked), "unresolved": lost,
                            "mapped": mapped, "lookahead": len(la["items"]) if la else 0,
                            "proposed": prop.get("status")}}
    todo = out["todo"]
    if not sched:
        todo.append("No confirmed schedule: plan-vs-actual and the lookahead cannot run. Upload the P6/MS Project "
                    "export on the project's Schedule screen and confirm it (an admin).")
        if d.get("schedule_drafts"):
            todo.append("A draft is waiting: an admin reviews and confirms it.")
    else:
        if weak(len(linked), n, "pred_coverage"):
            todo.append("Most activities carry no logic: export from P6 as XER (TASKPRED) or MS Project XML, not a "
                        "flat table.")
        if lost:
            todo.append(f"{lost} link(s) could not be matched (another project or a missing id): re-export the "
                        "whole project.")
        if weak(mapped, n, "mapped_share"):
            todo.append("Many activity names map to no work package and level: activity names like 'Drywall "
                        "Floor 3' map; 'Phase 2 interiors' does not.")
    return out


# ── THE WORK-STATE SAMPLE ──────────────────────────────────────────────────

@section("work state sample")
def _samples(d: JobData) -> Section:
    lists = []
    for s in d.get("samples") or []:
        lists.append((f"{s['work']} on {s['level']}", [(line, None) for line in str(s["text"]).split("\n")]))
    return {"name": "work state sample", "rows": [("answers", len(lists))], "todo": [] if lists else [
        "No sample was produced (no project, or the question could not be read)."], "lists": lists, "raw": {}}


# ── READINESS ──────────────────────────────────────────────────────────────

def readiness(raw: Dict[str, Dict[str, Any]], *, lend_ready: bool, signoff_field_seen: bool) -> List[Tuple[str, str, str]]:
    """(capability, ready | needs data | blocked, reason) from the sections' numbers."""
    lg, ph, ins, sc = raw.get("logs", {}), raw.get("photos", {}), raw.get("inspections", {}), raw.get("schedule", {})
    out: List[Tuple[str, str, str]] = []

    def gate(name: str, status: str, why: str) -> None:
        out.append((name, status, why))
    p, one, matched = lg.get("phrases", 0), lg.get("one_level", 0), lg.get("matched", 0)
    if not lg.get("logs"):
        gate("work_status by level", BLOCKED, "no filed daily log in the window")
    elif weak(one, p, "one_level_share"):
        gate("work_status by level", NEEDS_DATA, f"{share(one, p)} phrases name one level")
    else:
        gate("work_status by level", READY, f"{share(one, p)} phrases name one level")
    if not p:
        gate("work matched to the sequence", NEEDS_DATA, "no phrases")
    else:
        gate("work matched to the sequence", NEEDS_DATA if weak(matched, p, "sequence_share") else READY,
             f"{share(matched, p)} phrases match a step")
    n, exact = ph.get("photos", 0), ph.get("exact", 0)
    if not n:
        gate("photo place", NEEDS_DATA, "no indexed photo on the window's filed logs")
    else:
        gate("photo place", NEEDS_DATA if weak(exact, n, "photo_exact_share") else READY,
             f"{share(exact, n)} photos placed exactly")
    gate("photo place re-read", NEEDS_DATA if ph.get("pending") else READY,
         f"{ph.get('pending', 0)} photo(s) waiting" if ph.get("pending") else "no backlog")
    gate("photo comparison (relations)", READY if ph.get("relations_ready") else BLOCKED,
         "thresholds set from a benchmark" if ph.get("relations_ready")
         else "off until scripts/photo_relation_benchmark.py sets both thresholds")
    gate("photo place lending", READY if lend_ready else BLOCKED,
         "LEND_MIN_INLIERS set" if lend_ready else "LEND_MIN_INLIERS unset until a benchmark")
    if not ins.get("rows"):
        gate("inspection gates (reported)", NEEDS_DATA, "no inspection reported")
    else:
        gate("inspection gates (reported)", READY if ins.get("gate_reads") else NEEDS_DATA,
             f"{ins.get('gate_reads', 0)} gate/level read(s) from {ins['rows']} row(s), never verified")
    if not signoff_field_seen:
        gate("verified sign-off (DOB)", BLOCKED, "no DOB filing row carries a signoff_date")
    elif ins.get("signed_dated"):
        gate("verified sign-off (DOB)", READY, f"{ins['signed_dated']} signed-off filing(s) with a date")
    else:
        gate("verified sign-off (DOB)", NEEDS_DATA, "no signed-off filing with a date for this job")
    acts, linked = sc.get("activities", 0), sc.get("linked", 0)
    if not sc.get("confirmed"):
        gate("job's own logic", NEEDS_DATA, "no confirmed schedule")
        gate("lookahead / plan vs actual", NEEDS_DATA, "no confirmed schedule")
    else:
        gate("job's own logic", NEEDS_DATA if weak(linked, acts, "pred_coverage") else READY,
             f"{share(linked, acts)} activities carry the file's links")
        gate("lookahead / plan vs actual", NEEDS_DATA if weak(sc.get("mapped", 0), acts, "mapped_share") else READY,
             f"{share(sc.get('mapped', 0), acts)} activities mapped to work and level")
    if sc.get("confirmed"):
        gate("proposed sequence", READY, "not needed: a confirmed schedule is the plan")
    elif not lg.get("any_level"):
        gate("proposed sequence", NEEDS_DATA, "the logs name no level")
    else:
        gate("proposed sequence", READY, f"status: {sc.get('proposed') or 'not stored yet'}")
    gate("forecast / estimated dates", BLOCKED, "owner ruling 2026-11-09: no rate or estimate is computed")
    return out


# ── RUN AND PRINT ──────────────────────────────────────────────────────────

def run(d: JobData) -> List[Section]:
    return [fn(d) for _name, fn in _SECTIONS]


def readiness_for(sections: List[Section], d: JobData) -> List[Tuple[str, str, str]]:
    raw = {s["name"]: s.get("raw") or {} for s in sections}
    filings = [r for r in d.get("dob_rows") or [] if r.get("record_type") == "job_status"]
    seen = bool(d.get("signoff_field_seen")) or any("signoff_date" in r for r in filings)
    return readiness(raw, lend_ready=PL.LEND_MIN_INLIERS is not None, signoff_field_seen=seen)


def render(sections: List[Section], ready: List[Tuple[str, str, str]], names: Iterable[str] = ()) -> str:
    """The report, every free-text line through `redact`."""
    names = list(names)
    out: List[str] = []
    for s in sections:
        out.append(f"== {s['name'].upper()} ==")
        for label, value in s["rows"]:
            out.append(f"  {label}: {value}")
        for title, items in s["lists"]:
            out.append(f"  {title}:")
            if not items:
                out.append("    (none)")
            for text, count in items:
                out.append(f"    {text}" + (f"  x{count}" if count is not None else ""))
        for t in s["todo"]:
            out.append(f"  WHAT TO DO: {t}")
    out.append("== READINESS ==")
    width = max((len(c) for c, _s, _w in ready), default=10)
    for cap, status, why in ready:
        out.append(f"  {cap:<{width}}  {status:<10}  {why}")
    return redact("\n".join(out), names)


def coverage_line(d: JobData) -> Dict[str, Any]:
    """--all-jobs: counts only, one dict per job."""
    secs = {s["name"]: s["raw"] for s in run({**d, "samples": []}) if s.get("raw") is not None}
    lg, ph, ins, sc = secs["logs"], secs["photos"], secs["inspections"], secs["schedule"]
    return {"project_id": d["job"]["project_id"], "company_id": d["job"]["company_id"],
            "logs": lg["logs"], "phrases": lg["phrases"], "one_level": ratio(lg["one_level"], lg["phrases"]),
            "matched": ratio(lg["matched"], lg["phrases"]), "photos": ph["photos"], "photos_indexed": ph["indexed"],
            "photo_exact": ratio(ph["exact"], ph["photos"]), "reread_backlog": ph["backlog"],
            "inspections": ins["rows"], "validated": ratio(ins["agree"], ins["rows"]), "signed_off": ins["signed"],
            "schedule": sc["confirmed"], "activities": sc["activities"], "pred_coverage": ratio(sc["linked"], sc["activities"]),
            "proposed": sc["proposed"]}


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def render_coverage(lines: List[Dict[str, Any]], fixture_companies: Iterable[str] = ()) -> str:
    fx = {str(c) for c in fixture_companies}
    head = ("project_id               company_id               logs phrases 1lvl  seq   photos exact backlog "
            "insp  valid signed sched acts preds proposed")
    out = [head]
    for c in sorted(lines, key=lambda r: (str(r["company_id"]), str(r["project_id"]))):
        out.append(f"{str(c['project_id'])[:24]:24} {str(c['company_id'])[:24]:24}"
                   f"{' *' if str(c['company_id']) in fx else '  '}"
                   f"{c['logs']:>3} {c['phrases']:>7} {_pct(c['one_level']):>5} {_pct(c['matched']):>5} "
                   f"{c['photos']:>6} {_pct(c['photo_exact']):>5} {c['reread_backlog']:>7} {c['inspections']:>4} "
                   f"{_pct(c['validated']):>5} {c['signed_off']:>6} {('yes' if c['schedule'] else 'no'):>5} "
                   f"{c['activities']:>4} {_pct(c['pred_coverage']):>5} {c['proposed'] or '-'}")
    by_co = Counter(str(c["company_id"]) for c in lines)
    out.append("jobs per company: " + ", ".join(f"{k}{' (fixture tenant)' if k in fx else ''} {v}"
                                                for k, v in sorted(by_co.items())))
    return "\n".join(out)

