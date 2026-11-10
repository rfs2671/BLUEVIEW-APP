"""Reconstruct 588 Thomas S. Boyland St from its real records, offline, and
measure the reconstruction against DOB NOW: Inspections.

    PYTHONUTF8=1 python scripts/intel_588_reconstruct.py [--data C:/Users/asddd/bv-worktrees/intel588-data]

READS (local files, never committed, outside this repo):
  <data>/records/588_records.jsonl                  the records lane's rows
  <data>/records/audit_flags.jsonl                  the independent audit (originals, duplicates, leaks)
  <data>/drawings/building.json                     the drawings lane's building model
  <data>/public/588_public_timeline.json            public DOB / DOT rows (sign-offs read)
  <data>/public/dob_now_inspections_588.json        hand-verified DOB NOW: Inspections
WRITES:
  <data>/model/588_model.json, <data>/model/blind_runs/<label>.json

No network, no database, no paid API. Pure lib code does the work
(lib/intel_records, lib/construction_inference, lib/project_timeline).

EVIDENCE = the audit's ORIGINAL rows only (derived rows are summary context,
never a signal). A record is visible on day D only if it EXISTED on D
(lib/intel_records.existed_on: a filed log from its signature, a report's
tile from the report's generation, a capture from its capture time).

THE BLIND TEST. Run as of BLIND_DAY WITHOUT the DOB NOW: Inspections file and
without any record that could carry an inspection result (lib/intel_records
.leak_reasons + every audit leak flag, borderline included). Each DOB floor-
table cell (level x water/sanitary rough, storm rough, gas rough,
underground) is scored:

  correct_fact        a fact at attested or stronger said the work was done
  correct_inference   an INFERENCE said it was in place (not a verified completion)
  weak_reported_only  reported only (a log row, a photo, an inference of work
                      under way): true, but weak
  miss                unknown: nothing on record the engine could use
  incorrect           it claimed something DOB contradicts: a failure, a "not
                      yet", or an inspection passed BEFORE DOB resulted it

UNDER THREE RULE SETS (adversarial review 2, M1):
  as_stated           independence = source and the crew named (the rule as
                      first written: two subs on one CP log were "two sources")
  one_person          independence = the AUTHOR / OBSERVER: one person's log is
                      one source whatever subs it names (the rule now)
  part_named          one_person, and a cell counts only if a record NAMES its
                      part (water/sanitary, storm, gas); otherwise it is a miss

OFFICIAL vs POST-HOC. The OFFICIAL blind score is the rules as they stood
BEFORE DOB was seen (the first blind run's rule set, FROZEN below and
re-applied with mock.patch to the same audited, as-of-visible data). Every rule
changed after that run gives the POST-HOC result, labelled "post-hoc, not
blind". The scoring rule itself was fixed before the first run.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest import mock

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
RULE_SETS = ("as_stated", "one_person", "part_named")


def load(data: Path) -> Dict[str, Any]:
    with open(data / "records" / "588_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    building = json.loads((data / "drawings" / "building.json").read_text(encoding="utf-8"))
    timeline = json.loads((data / "public" / "588_public_timeline.json").read_text(encoding="utf-8"))
    dob_now = json.loads((data / "public" / "dob_now_inspections_588.json").read_text(encoding="utf-8"))
    return {"records": records, "building": building, "timeline": timeline, "dob_now": dob_now}


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


# ── THE RULES AS THEY STOOD AT THE FIRST BLIND RUN (FROZEN) ───────────────

def frozen_slab_pour(facts, model):
    """The first run's slab pour: the earliest ground-level foundation / slab
    row naming a pour and a slab (it took an 08-26 chip list as the pour)."""
    g = model.get("ground_level")
    pours = sorted((i for i in facts if g in (i.get("levels") or ()) and i.get("node") in ("foundation", CI.SLAB_ON_GRADE)
                    and re.search(r"\bpour(?:ing|ed|s)?\b", i.get("quote") or "", re.I)
                    and re.search(r"\bslab\b", i.get("quote") or "", re.I) and CI._on(i)), key=CI._on)
    return pours[0] if pours else None


def frozen_independence_key(signal):
    """The first run's independence: source and the crew named."""
    if signal.get("independence"):
        return str(signal["independence"])
    actor = str(signal.get("sub") or signal.get("by") or "").strip().lower()
    return f"{signal.get('source')}|{actor}"


@contextlib.contextmanager
def rules(version: str, rule_set: str) -> Iterator[None]:
    """version: "frozen" (official) | "post_hoc". rule_set: RULE_SETS."""
    with contextlib.ExitStack() as st:
        if rule_set == "as_stated":
            st.enter_context(mock.patch.object(E, "independence_key", frozen_independence_key))
        if version == "frozen":
            st.enter_context(mock.patch.object(CI, "slab_pour", frozen_slab_pour))
            st.enter_context(mock.patch.object(CI, "one_per_record", lambda s: list(s)))
            st.enter_context(mock.patch.object(CI, "framing_before_slab_pour", lambda f, m: []))
            st.enter_context(mock.patch.object(CI, "group_issues", lambda c, i: c))
        yield


# ── GROUND TRUTH, READ ONLY FOR SCORING ───────────────────────────────────

#: DOB floor-table cell -> (engine part nodes, words that NAME the part, label).
CELL_PARTS = {
    "WS ROUGH": (("rough_water", "rough_dwv"), r"\bwater\b|sanitary|\bsewer|\bwaste\b|\bdwv\b", "water / sanitary rough"),
    "ST DRN ROUGH": ((), r"\bstorm|\bdrain|\bleader", "storm drainage rough"),
    "GAS ROUGH": (("rough_gas",), r"\bgas\b", "gas rough"),
    "WS UND GRND": ((CI.UNDERGROUND["plumbing"],), r"underground plumbing|\bwater\b|sanitary|\bsewer|\bwaste\b",
                    "water / sanitary underground"),
    "ST DRN UND GRND": ((CI.UNDERGROUND["plumbing"],), r"\bstorm|\bdrain|\bleader", "storm underground"),
}


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
                        "what": CELL_PARTS[cell][2], "dob": f"{res} {day}", "dob_day": day,
                        "underground": underground})
    return out


def score(state: str, before: List[str]) -> str:
    """Fixed before the first run (only the word 'partial' was renamed)."""
    if before or state.startswith(("failed_", "not_yet_", "blocked_")):
        return "incorrect"
    if state.startswith("done_"):
        return "correct_fact"
    if state.startswith("inferred_done_"):
        return "correct_inference"
    if state.startswith(("inferred_in_progress_", "in_progress_")) or state == "reported":
        return "weak_reported_only"
    return "miss"


def cell_state(snap: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, Any]:
    lv = t["level"]
    parts, words, _label = CELL_PARTS[t["cell"]]
    generic = set() if t["underground"] else {CI.PLUMBING_GENERIC}
    facts = [i for i in snap["_facts"] if lv in (i.get("levels") or ()) and i.get("node") in set(parts) | generic]
    node = CI.UNDERGROUND["plumbing"] if t["underground"] else "rough_plumbing"
    infs = [i for i in snap["inferences"] if i.get("node") == node and i["levels"] == [lv]]
    st = T.subject_state(facts, infs)
    gate = CI.UNDERGROUND_GATE if t["underground"] else "gate_plumbing_rough"
    before = [i["ref"] for i in snap["_facts"] if i.get("node") == gate and i.get("claim") == "done"
              and (not i.get("levels") or lv in i["levels"]) and isinstance(i.get("on"), date)
              and t["dob_day"] and i["on"].isoformat() < t["dob_day"] and E.rank(i["kind"]) <= E.rank("attested")]
    named = [i["ref"] for i in facts if re.search(words, i.get("quote") or "", re.I)]
    inf = infs[0] if infs else None
    by = inf["on"].isoformat() if inf and inf["claim"] == "done" else None
    newest = max((i["on"] for i in facts if isinstance(i.get("on"), date)), default=None)
    level_lists = [i.get("levels") or () for i in facts]          # read out before counting (probe discipline)
    level_counts = [len(x) for x in level_lists]
    return {"state": st, "score": score(st, before), "pass_claimed_before_dob": before,
            "part_named_by": named[:6],
            "basis_level": ("part named by a record" if named else "system-level only (part never named)"
                            if (facts or infs) else "nothing"),
            "multi_floor_only": bool(level_counts) and all(n > 1 for n in level_counts),
            "newest_support": newest.isoformat() if newest else None,
            "newest_support_days_before_blind_day": (BLIND_DAY - newest).days if newest else None,
            "inferred_in_place_by": by,
            "days_before_dob_result": ((date.fromisoformat(t["dob_day"]) - inf["on"]).days
                                       if by and t["dob_day"] else None),
            "inference": _inf_summary(inf) if inf else None, "fact_refs": [i["ref"] for i in facts][:12]}


def blind_test(items: List[Dict[str, Any]], model: Dict[str, Any], tr: List[Dict[str, Any]],
               hc: List[Dict[str, Any]], weekly_days: List[date], rule_set: str) -> Dict[str, Any]:
    snap = T.as_of(items, model, BLIND_DAY, project_id=PID, headcounts=hc)
    rows = [dict(t, **cell_state(snap, t)) for t in tr]
    if rule_set == "part_named":
        for r in rows:
            if r["basis_level"] != "part named by a record" and r["score"] != "incorrect":
                r["score"] = "miss"
    ever = []
    for d in [x for x in weekly_days if x <= BLIND_DAY]:
        s = T.as_of(items, model, d, project_id=PID, headcounts=hc)
        for t in tr:
            c = cell_state(s, t)
            if c["score"] == "incorrect":
                ever.append({"as_of": d.isoformat(), "cell": f"{t['level_code']}:{t['cell']}", "state": c["state"],
                             "refs": c["pass_claimed_before_dob"]})
    scored = [(r["level"], r["score"]) for r in rows]
    return {"as_of": BLIND_DAY.isoformat(), "rule_set": rule_set, "dob_now_read": False, "rows": rows,
            "totals": dict(Counter(sc for _lv, sc in scored)),
            "totals_by_level": {lv: dict(Counter(sc for x, sc in scored if x == lv))
                                for lv in sorted({x for x, _sc in scored})},
            "ever_claimed_what_dob_contradicts": ever,
            "inferences_as_of_blind_day": [_inf_summary(i) for i in snap["inferences"]],
            "contradictions_as_of_blind_day": snap["contradictions"]}


def _inf_summary(i: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": i["ref"], "claim": i["claim"], "confidence": i["confidence"], "confidence_rule": i["confidence_rule"],
            "basis": i["basis"], "disproof": i["disproof"], "unlocks": i["unlocks"], "blocks": i["blocks"],
            "signals": [{k: s.get(k) for k in ("source", "ref", "on", "kind", "sub", "by", "levels", "role")}
                        for s in i["signals"]],
            "contradictions": [c["kind"] for c in i["contradictions"]]}


# ── COVERAGE ──────────────────────────────────────────────────────────────

def location_coverage(records: List[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Any]:
    rows = [r for r in records if r.get("type") == "daily_log_activity" and r.get("company") and r.get("description")
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
            "definition": "the audit's ORIGINAL daily-log crew rows with a company and a work description; one "
                          "floor = the location binds to exactly one level"}


def sub_coverage(snap: Dict[str, Any], roster: Dict[str, str], tile_refs: set) -> Dict[str, Any]:
    """Whose current activity is determinable on the day, and FROM WHAT: a
    sub whose latest work record is a photo tile embedded in a generated
    report is counted apart, never as the measurement."""
    names = sorted(set(roster) | set(snap["subs"]))
    det, from_tiles, from_filed = [], [], []
    for s in names:
        cur = snap["subs"].get(s, {}).get("current_activity")
        if not cur:
            continue
        det.append(s)
        bases = {r.split(":", 1)[0] for r in cur.get("refs") or ()}
        (from_tiles if bases <= tile_refs else from_filed).append(s)
    n_roster = len(roster)
    return {"as_of": snap["as_of"], "roster_subs": n_roster,
            "determinable_from_filed_or_original_records": len([s for s in from_filed if s in roster]),
            "determinable_only_from_photo_tiles_inside_the_11_09_generated_report": len([s for s in from_tiles
                                                                                          if s in roster]),
            "measurement": f"{len([s for s in from_filed if s in roster])}/{n_roster} from filed / original records; "
                           f"{len([s for s in from_tiles if s in roster])}/{n_roster} only from photo tiles inside "
                           "the 11-09 generated report (not a measurement)",
            "per_sub": {s: (dict(snap["subs"][s]["current_activity"],
                                 source="photo tile inside the 11-09 generated report" if s in from_tiles else "record")
                            if s in det else {"why_not": snap["subs"].get(s, {}).get("why_not")
                                              or "no work record on file"})
                        for s in names}}


# ── RUNS ──────────────────────────────────────────────────────────────────

def _weeks(start: date, end: date) -> List[date]:
    days, d = [], start
    while d < end:
        days.append(d)
        d = date.fromordinal(d.toordinal() + 7)
    return days


def _originals(records: List[Dict[str, Any]], audit: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if R.audit_class(audit.get(str(r.get("id")))) == "original"]


def blind_runs(src: Dict[str, Any], model: Dict[str, Any], audit: Dict[str, Dict[str, Any]],
               days: List[date]) -> Dict[str, Any]:
    kept, excluded = R.blind_records(src["records"], BLIND_DAY, audit=audit)
    hc = R.headcounts(_originals(kept, audit), readme_dups=False)
    tr = truth(src["dob_now"])
    reasons = [why for e in excluded for why in e["reasons"]]
    out: Dict[str, Any] = {"records_kept": len(kept), "records_excluded": len(excluded),
                           "excluded_by_reason": dict(Counter(reasons)),
                           "excluded": excluded}
    for version, label in (("frozen", "official_blind_frozen_rules"), ("post_hoc", "post_hoc_not_blind")):
        out[label] = {}
        for rs in RULE_SETS:
            with rules(version, rs):
                items, _meta = R.items_from_records(kept, model, project_id=PID, audit=audit)
                out[label][rs] = T._jsonable(blind_test(items, model, tr, hc, days, rs))
    return out


def lost_support(before: List[Dict[str, Any]], after: List[Dict[str, Any]],
                 audit: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each inference of the as-stated run, what became of it under one
    person = one source, and the author of every signal it stood on."""
    after_by = {i["ref"].rsplit(":", 1)[0]: i for i in after}
    out = []
    for i in before:
        key = i["ref"].rsplit(":", 1)[0]
        a = after_by.get(key)
        authors = sorted({str(s.get("by") or s.get("sub")) for s in i["signals"]})
        classes = [R.audit_class(audit.get(str(s["ref"]).split(":")[0])) for s in i["signals"]]
        out.append({"inference": key, "as_stated": f"{i['claim']} / {i['confidence']}",
                    "one_person_one_source": f"{a['claim']} / {a['confidence']}" if a else "no inference (support lost)",
                    "authors_of_its_signals": authors,
                    "signal_audit_classes": dict(Counter(classes))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--label", default="run", help="name of this blind run (kept under model/blind_runs/)")
    args = ap.parse_args()
    data = Path(args.data)
    src = load(data)
    audit = load_audit(data)
    if not audit:
        raise SystemExit("records/audit_flags.jsonl is required: only audited originals are evidence")
    model = CI.model_from_building(src["building"], name="588 Thomas S. Boyland St")
    originals = _originals(src["records"], audit)
    rec_items, meta = R.items_from_records(src["records"], model, project_id=PID, audit=audit)
    pub_items = R.items_from_public(src["timeline"], project_id=PID)
    dob_items = R.items_from_dob_now(src["dob_now"], project_id=PID)
    hc = R.headcounts(originals, readme_dups=False)
    full_items = rec_items + pub_items + dob_items
    created = [R._d(r.get("date")) for r in src["records"] if "project_create" in str(r.get("quote") or "")]
    days = _weeks(min(d for d in created if d), TODAY)
    blinds = blind_runs(src, model, audit, days)
    now = T.as_of(full_items, model, TODAY, project_id=PID, headcounts=hc)
    with rules("post_hoc", "as_stated"):
        stated_now = T.as_of(full_items, model, TODAY, project_id=PID, headcounts=hc)
    weekly = [T.public(T.as_of(full_items, model, day, project_id=PID, headcounts=hc)) for day in days + [TODAY]]
    for w in weekly:
        w.pop("subs", None)                               # per-sub histories are given once, below
    tiles = {str(r.get("id")) for r in src["records"]
             if (r.get("fields") or {}).get("kind") == "report_visual_progress_tile"}
    out = {
        "_about": "LeveLog offline reconstruction of 588 Thomas S. Boyland St (project " + PID + "), built "
                  + TODAY.isoformat() + " by backend/scripts/intel_588_reconstruct.py from local files only. "
                  "Evidence = the audit's original rows; a record is visible on a day only if it existed then. "
                  "Categories: verified / confirmed / attested (a named person's statement; between confirmed and "
                  "observed) / observed / reported / inferred / unknown. An inference is never a fact, never a "
                  "passed inspection, never a percent. Unknown is never 'not done'.",
        "category_map": {"Verified": "verified", "Confirmed": "confirmed", "Observed": "observed",
                         "Reported": "reported", "Inferred": "inferred", "Unknown": "no items",
                         "attested (engine rung, no owner category)": "a named person's statement; shown as attested"},
        "building_model": model,
        "inputs": {"records": {k: v for k, v in meta.items() if k != "summary_context"},
                   "public_items": len(pub_items), "dob_now_items": len(dob_items), "headcount_pairs": len(hc)},
        "current_state": T.public(now),
        "summary_context": T._jsonable(meta.get("summary_context") or []),
        "inferences_as_stated_vs_one_person": T._jsonable(lost_support(stated_now["inferences"], now["inferences"],
                                                                        audit)),
        "weekly_snapshots": weekly,
        "subs": T.public(now)["subs"],
        "blind_test": blinds,
        "coverage": {"location": location_coverage(originals, model), "subs": sub_coverage(now, meta["roster"], tiles)},
        "confidence_rules": CI.CONFIDENCE_RULES,
    }
    (data / "model" / "blind_runs").mkdir(parents=True, exist_ok=True)
    (data / "model" / "588_model.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                                   encoding="utf-8")
    (data / "model" / "blind_runs" / f"{args.label}.json").write_text(
        json.dumps(blinds, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    totals = {f"{v}:{rs}": blinds[v][rs]["totals"] for v in ("official_blind_frozen_rules", "post_hoc_not_blind")
              for rs in RULE_SETS}
    con_kinds = [c["kind"] for c in now["contradictions"]]
    print(json.dumps({"blind_totals": totals, "excluded": blinds["records_excluded"],
                      "coverage_subs": out["coverage"]["subs"]["measurement"],
                      "coverage_location": {k: v for k, v in out["coverage"]["location"].items() if k != "definition"},
                      "contradiction_kinds": dict(Counter(con_kinds)),
                      "items": {"records": len(rec_items), "public": len(pub_items), "dob_now": len(dob_items)}},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
