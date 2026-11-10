"""Reconstruct 588 Thomas S. Boyland St from its real records, offline, and
measure the reconstruction against DOB NOW: Inspections.

    PYTHONUTF8=1 python scripts/intel_588_reconstruct.py [--data C:/Users/asddd/bv-worktrees/intel588-data]

READS (local files, never committed, outside this repo):
  <data>/records/588_records.jsonl                  the records lane's rows
  <data>/drawings/building.json                     the drawings lane's building model
  <data>/public/588_public_timeline.json            public DOB / DOT rows (sign-offs read)
  <data>/public/dob_now_inspections_588.json        hand-verified DOB NOW: Inspections
WRITES:
  <data>/model/588_model.json, <data>/model/README.md

No network, no database, no paid API. Pure lib code does the work
(lib/intel_records, lib/construction_inference, lib/project_timeline).

THE BLIND TEST. The reconstruction is run as of BLIND_DAY WITHOUT the DOB NOW:
Inspections file (and without any timeline row from that portal), and WITHOUT
any record that could carry an inspection result (lib/intel_records
.leak_reasons: anything dated or captured after the cutoff, bot / DM answers,
operator inspection statements, any text stating an inspection result, and --
in the "strictest" variant -- every generated report row). What it believed
about each DOB floor-table cell (level x water/sanitary rough, storm rough,
gas rough, underground) is then scored against that file:

  correct_fact       a fact at attested or stronger said the work was done
  correct_inference  an INFERENCE said it was in place (kept apart from a
                     fact: a correct inference is not a verified completion)
  partial            work under way (inferred in progress, in progress, reported)
  miss               unknown: nothing on record the engine could use
  incorrect          it claimed something DOB contradicts: a failure, a "not
                     yet", or an inspection passed BEFORE DOB resulted it
Each row also says whether any record named that PART (a "storm" or "gas"
record) or only plumbing in general, and, for an in-place inference, its
by-date against DOB's result date. The scoring rule is fixed here, before the
run, and is not tuned on the result.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import construction_inference as CI  # noqa: E402
from lib import evidence as E  # noqa: E402
from lib import intel_records as R  # noqa: E402
from lib import location_binder as LB  # noqa: E402
from lib import project_timeline as T  # noqa: E402

DATA = Path("C:/Users/asddd/bv-worktrees/intel588-data")
PID = "6a5f63bc147407d3261df2c7"
BLIND_DAY = date(2026, 11, 4)
TODAY = date(2026, 11, 10)
DOB_PASS_DAY = date(2026, 11, 5)


def load(data: Path) -> Dict[str, Any]:
    with open(data / "records" / "588_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    building = json.loads((data / "drawings" / "building.json").read_text(encoding="utf-8"))
    timeline = json.loads((data / "public" / "588_public_timeline.json").read_text(encoding="utf-8"))
    dob_now = json.loads((data / "public" / "dob_now_inspections_588.json").read_text(encoding="utf-8"))
    return {"records": records, "building": building, "timeline": timeline, "dob_now": dob_now}


# ── GROUND TRUTH, READ ONLY FOR SCORING ───────────────────────────────────

#: DOB floor-table cell -> (engine part nodes, label). Storm piping has no
#: node of its own in the engine: only a generic plumbing record can speak to it.
CELL_PARTS = {"WS ROUGH": (("rough_water", "rough_dwv"), "water / sanitary rough"),
              "ST DRN ROUGH": ((), "storm drainage rough"),
              "GAS ROUGH": (("rough_gas",), "gas rough"),
              "WS UND GRND": ((CI.UNDERGROUND["plumbing"],), "water / sanitary underground"),
              "ST DRN UND GRND": ((CI.UNDERGROUND["plumbing"],), "storm underground")}


def truth(dob_now: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per DOB floor-table cell, with the date the cell was resulted."""
    pl = dob_now.get("plumbing_permit_B01141294-S5-PL") or {}
    when = {c.get("id"): (c.get("resulted") or "")[:10] for c in pl.get("completed_inspections") or ()}
    out = []
    for code, cells in (pl.get("floor_results_table_UNDATED") or {}).items():
        for cell, res in cells.items():
            if cell not in CELL_PARTS:
                continue
            underground = "UND GRND" in cell
            day = when.get("7681636") if underground and code != "OSP" else when.get("7755632")
            out.append({"level_code": code, "level": R.dob_level(code) or "SITE_OPEN_SPACE", "cell": cell,
                        "what": CELL_PARTS[cell][1], "dob": f"{res} {day}", "dob_day": day,
                        "underground": underground})
    return out


def score(state: str, before: List[str]) -> str:
    """Fixed before the run (module docstring)."""
    if before or state.startswith(("failed_", "not_yet_", "blocked_")):
        return "incorrect"
    if state.startswith("done_"):
        return "correct_fact"
    if state.startswith("inferred_done_"):
        return "correct_inference"
    if state.startswith(("inferred_in_progress_", "in_progress_")) or state == "reported":
        return "partial"
    return "miss"


def cell_state(snap: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, Any]:
    lv = t["level"]
    parts = set(CELL_PARTS[t["cell"]][0])
    generic = set() if t["underground"] else {CI.PLUMBING_GENERIC}
    facts = [i for i in snap["_facts"] if lv in (i.get("levels") or ()) and i.get("node") in parts | generic]
    node = CI.UNDERGROUND["plumbing"] if t["underground"] else "rough_plumbing"
    infs = [i for i in snap["inferences"] if i.get("node") == node and i["levels"] == [lv]]
    st = T.subject_state(facts, infs)
    gate = CI.UNDERGROUND_GATE if t["underground"] else "gate_plumbing_rough"
    before = [i["ref"] for i in snap["_facts"] if i.get("node") == gate and i.get("claim") == "done"
              and (not i.get("levels") or lv in i["levels"]) and isinstance(i.get("on"), date)
              and t["dob_day"] and i["on"].isoformat() < t["dob_day"] and E.rank(i["kind"]) <= E.rank("attested")]
    named = any(i.get("node") in parts for i in facts)
    inf = infs[0] if infs else None
    by = inf["on"].isoformat() if inf and inf["claim"] == "done" else None
    return {"state": st, "score": score(st, before), "pass_claimed_before_dob": before,
            "evidence_names_this_part": named,
            "basis_level": "part named by a record" if named else ("system-level only (part never named)"
                                                                    if (facts or infs) else "nothing"),
            "inferred_in_place_by": by,
            "days_before_dob_result": ((date.fromisoformat(t["dob_day"]) - inf["on"]).days
                                       if by and t["dob_day"] else None),
            "inference": _inf_summary(inf) if inf else None, "fact_refs": [i["ref"] for i in facts][:12]}


def blind_test(items: List[Dict[str, Any]], model: Dict[str, Any], tr: List[Dict[str, Any]],
               hc: List[Dict[str, Any]], weekly_days: List[date]) -> Dict[str, Any]:
    snap = T.as_of(items, model, BLIND_DAY, project_id=PID, headcounts=hc)
    rows = [dict(t, **cell_state(snap, t)) for t in tr]
    ever, first = [], {}
    for d in [x for x in weekly_days if x <= BLIND_DAY] + [BLIND_DAY]:
        s = T.as_of(items, model, d, project_id=PID, headcounts=hc)
        for t in tr:
            c = cell_state(s, t)
            key = f"{t['level_code']}:{t['cell']}"
            if c["score"] == "incorrect":
                ever.append({"as_of": d.isoformat(), "cell": key, "state": c["state"], "refs": c["pass_claimed_before_dob"]})
            if key not in first and c["score"] in ("correct_fact", "correct_inference"):
                first[key] = {"as_of": d.isoformat(), "state": c["state"]}
    # Values are read out of OUR result rows before counting (these are not
    # database documents; scripts/audit_probe_field_discipline.py).
    scored = [(r["level"], r["score"]) for r in rows]
    return {"as_of": BLIND_DAY.isoformat(), "dob_now_read": False, "rows": rows,
            "totals": dict(Counter(sc for _lv, sc in scored)),
            "totals_by_level": {lv: dict(Counter(sc for x, sc in scored if x == lv))
                                for lv in sorted({x for x, _sc in scored})},
            "ever_claimed_what_dob_contradicts": ever, "first_weekly_as_of_with_an_in_place_claim": first,
            "inferences_as_of_blind_day": [_inf_summary(i) for i in snap["inferences"]],
            "contradictions_as_of_blind_day": snap["contradictions"],
            "scoring_rule": (__doc__ or "").split("THE BLIND TEST.")[1].strip()}


def _inf_summary(i: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": i["ref"], "claim": i["claim"], "confidence": i["confidence"], "confidence_rule": i["confidence_rule"],
            "basis": i["basis"], "disproof": i["disproof"], "unlocks": i["unlocks"], "blocks": i["blocks"],
            "signals": [{k: s[k] for k in ("source", "ref", "on", "kind", "sub", "levels", "role")} for s in i["signals"]],
            "contradictions": [c["kind"] for c in i["contradictions"]]}


# ── COVERAGE ──────────────────────────────────────────────────────────────

def location_coverage(records: List[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Any]:
    rows = [r for r in records if r.get("type") == "daily_log_activity" and not r.get("duplicate_of")
            and r.get("origin") != "assistant_claim" and r.get("company") and r.get("description")
            and (r.get("fields") or {}).get("kind") in (None, "period_work_item")]
    one_raw = one_model = 0
    by_count: Counter = Counter()
    for r in rows:
        raw = LB.read(r.get("location_text") or "")["levels"]
        lv, _c, _s = R.place(r.get("location_text"), model, R.classify(r["description"].split(",")[0],
                                                                         R.trade_family(r["company"])),
                             r["description"])
        one_raw += len(raw) == 1
        one_model += len(lv) == 1
        by_count[len(lv)] += 1
    n = len(rows)
    return {"rows": n, "one_floor_binder_only": one_raw, "one_floor_with_building_model": one_model,
            "share_one_floor_binder_only": round(one_raw / n, 3) if n else None,
            "share_one_floor_with_building_model": round(one_model / n, 3) if n else None,
            "rows_by_number_of_levels": dict(sorted(by_count.items())),
            "definition": "unique real daily-log crew rows (filed sheets, probes, report period rows) with a company and "
                          "a work description; one floor = the location binds to exactly one level"}


def sub_coverage(snap: Dict[str, Any], roster: Dict[str, str]) -> Dict[str, Any]:
    names = sorted(set(roster) | set(snap["subs"]))
    det = [s for s in names if snap["subs"].get(s, {}).get("current_activity_determinable")]
    return {"as_of": snap["as_of"], "roster_and_record_subs": len(names), "roster_subs": len(roster),
            "determinable": len(det), "share": round(len(det) / len(names), 3) if names else None,
            "share_of_roster": round(len([s for s in roster if s in det]) / len(roster), 3) if roster else None,
            "per_sub": {s: (snap["subs"].get(s, {}).get("current_activity") or
                            {"why_not": snap["subs"].get(s, {}).get("why_not") or "no record of this sub at all"})
                        for s in names}}


# ── MAIN ──────────────────────────────────────────────────────────────────

def load_audit(data: Path) -> Dict[str, Dict[str, Any]]:
    """The independent audit lane's per-record flags, when the file exists."""
    path = data / "records" / "audit_flags.jsonl"
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                out[str(row.get("rec_id") or row.get("id") or row.get("record_id"))] = row
    return out


def _weeks(start: date, end: date) -> List[date]:
    days, d = [], start
    while d < end:
        days.append(d)
        d = date.fromordinal(d.toordinal() + 7)
    return days


def _originals(src: Dict[str, Any], audit: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in src["records"] if R.audit_class(audit.get(str(r.get("id")))) == "original"]


def blind_run(src: Dict[str, Any], model: Dict[str, Any], strictness: str, audit: Dict[str, Dict[str, Any]],
              pub_items: List[Dict[str, Any]], days: List[date], *, apply_audit: bool) -> Dict[str, Any]:
    """apply_audit False = the run before the audit (README duplicates, every
    non-duplicate row as evidence). True = originals only as evidence, the
    audit's leak flags (direct, DOB sign-off state AND borderline) excluded,
    and the public DOB sign-off rows withheld too (the audit flags their
    record-copies as sign-off-state leaks)."""
    kept, excluded = R.blind_records(src["records"], BLIND_DAY, strictness=strictness,
                                     audit=audit if apply_audit else None)
    if apply_audit:
        items, meta = R.items_from_records(kept, model, project_id=PID, audit=audit)
        hc = R.headcounts(_originals({"records": kept}, audit), readme_dups=False)
        pub = []
    else:
        items, meta = R.items_from_records(kept, model, project_id=PID)
        hc = R.headcounts(kept)
        pub = pub_items
    bt = blind_test(items + pub, model, truth(src["dob_now"]), hc, days)
    reasons = [why for e in excluded for why in e["reasons"]]
    summary_rows = meta.get("summary_context") or []
    bt.update({"strictness": strictness, "audit_applied": apply_audit, "records_kept": len(kept),
               "records_excluded": len(excluded), "excluded_by_reason": dict(Counter(reasons)),
               "excluded": excluded, "items": len(items), "audit_classes_of_kept": meta.get("audit_classes"),
               "summary_context_rows": len(summary_rows)})
    return bt


def lost_support(before: List[Dict[str, Any]], after: List[Dict[str, Any]],
                 audit: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each inference of the pre-audit run, what became of it after the
    audit, and the audit class of every signal it stood on."""
    after_by = {i["ref"].rsplit(":", 1)[0]: i for i in after}
    out = []
    for i in before:
        key = i["ref"].rsplit(":", 1)[0]
        sig = [{"ref": s["ref"], "kind": s["kind"], "sub": s.get("sub"), "source": s["source"],
                "audit": R.audit_class(audit.get(str(s["ref"]).split(":")[0]))} for s in i["signals"]]
        a = after_by.get(key)
        classes = [x["audit"] for x in sig]
        out.append({"inference": key, "before": f"{i['claim']} / {i['confidence']}",
                    "after": f"{a['claim']} / {a['confidence']}" if a else "no inference (support lost)",
                    "signals_by_audit_class": dict(Counter(classes)),
                    "original_signal_sources_after_audit": sorted({f"{x['source']}|{x['sub']}" for x in sig
                                                                   if x["audit"] == "original"}),
                    "signals": sig})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--label", default="run", help="name of this blind run (kept under model/blind_runs/)")
    args = ap.parse_args()
    data = Path(args.data)
    src = load(data)
    audit = load_audit(data)
    model = CI.model_from_building(src["building"], name="588 Thomas S. Boyland St")
    pre_items, _pre_meta = R.items_from_records(src["records"], model, project_id=PID)
    rec_items, meta = R.items_from_records(src["records"], model, project_id=PID, audit=audit or None)
    pub_items = R.items_from_public(src["timeline"], project_id=PID)
    dob_items = R.items_from_dob_now(src["dob_now"], project_id=PID)
    hc = R.headcounts(_originals(src, audit), readme_dups=False) if audit else R.headcounts(src["records"])
    full_items = rec_items + pub_items + dob_items
    pre_now = T.as_of(pre_items + pub_items + dob_items, model, TODAY, project_id=PID,
                      headcounts=R.headcounts(src["records"]))
    # From the day this LeveLog project was created (its first record; the
    # records file also holds a probe line dated 2026-01-01 that says nothing
    # was filed, and another project's document of 2026-05-04) to today.
    created = [R._d(r.get("date")) for r in src["records"] if "project_create" in str(r.get("quote") or "")]
    first = min(d for d in created if d) if any(created) else min(
        i["on"] for i in rec_items if isinstance(i.get("on"), date))
    days = _weeks(first, TODAY)
    blinds = {f"pre_audit_{k}": T._jsonable(blind_run(src, model, k, audit, pub_items, days, apply_audit=False))
              for k in R.STRICTNESS + (R.DATES_ONLY,)}
    if audit:
        blinds["post_audit"] = T._jsonable(blind_run(src, model, "conservative", audit, pub_items, days,
                                                     apply_audit=True))
    now = T.as_of(full_items, model, TODAY, project_id=PID, headcounts=hc)
    weekly = [T.public(T.as_of(full_items, model, day, project_id=PID, headcounts=hc)) for day in days + [TODAY]]
    for w in weekly:
        w.pop("subs", None)                               # per-sub histories are given once, below
    out = {
        "_about": "LeveLog offline reconstruction of 588 Thomas S. Boyland St (project " + PID + "), built "
                  + TODAY.isoformat() + " by backend/scripts/intel_588_reconstruct.py from local files only. "
                  "Categories: verified / confirmed / attested (a named person's statement; between confirmed and "
                  "observed) / observed / reported / inferred / unknown. An inference is never a fact, never a "
                  "passed inspection, never a percent. Unknown is never 'not done'.",
        "category_map": {"Verified": "verified", "Confirmed": "confirmed", "Observed": "observed",
                         "Reported": "reported", "Inferred": "inferred", "Unknown": "no items",
                         "attested (engine rung, no owner category)": "a named person's statement; shown as attested"},
        "building_model": model,
        "inputs": {"records": meta, "public_items": len(pub_items), "dob_now_items": len(dob_items),
                   "headcount_pairs": len(hc), "audit_file_used": bool(audit)},
        "current_state": T.public(now),
        "summary_context": T._jsonable(meta.get("summary_context") or []),
        "inferences_before_vs_after_audit": T._jsonable(lost_support(pre_now["inferences"], now["inferences"], audit)),
        "blind_inferences_before_vs_after_audit": (T._jsonable(lost_support(
            [x for x in blinds["pre_audit_conservative"]["inferences_as_of_blind_day"]],
            [x for x in blinds["post_audit"]["inferences_as_of_blind_day"]], audit)) if audit else None),
        "weekly_snapshots": weekly,
        "subs": T.public(now)["subs"],
        "blind_test": blinds,
        "coverage": {"location": location_coverage(src["records"], model), "subs": sub_coverage(now, meta["roster"])},
        "confidence_rules": CI.CONFIDENCE_RULES,
    }
    (data / "model" / "blind_runs").mkdir(parents=True, exist_ok=True)
    (data / "model" / "588_model.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                                   encoding="utf-8")
    (data / "model" / "blind_runs" / f"{args.label}.json").write_text(
        json.dumps(blinds, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    summary = {k: {"totals": b["totals"], "by_level": b["totals_by_level"],
                   "cells": {f"{r['level_code']}:{r['cell']}": [r["state"], r["score"], r["basis_level"],
                                                                 r["inferred_in_place_by"]] for r in b["rows"]},
                   "ever_incorrect": b["ever_claimed_what_dob_contradicts"], "excluded": b["records_excluded"],
                   "excluded_by_reason": b["excluded_by_reason"]} for k, b in blinds.items()}
    infs_now = now["inferences"]
    n_inf = len(infs_now)
    con_kinds = [c["kind"] for c in now["contradictions"]]
    print(json.dumps({"blind": summary,
                      "coverage_location": {k: v for k, v in out["coverage"]["location"].items() if k != "definition"},
                      "coverage_subs": {k: v for k, v in out["coverage"]["subs"].items() if k != "per_sub"},
                      "inferences_now": n_inf, "contradictions_now": len(con_kinds),
                      "contradiction_kinds": dict(Counter(con_kinds)),
                      "items": {"records": len(rec_items), "public": len(pub_items), "dob_now": len(dob_items)}},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
