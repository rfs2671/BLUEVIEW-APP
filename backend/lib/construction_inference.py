"""WHAT THE RECORDS IMPLY, GIVEN HOW THIS BUILDING IS BUILT.

lib/evidence.py holds facts on a ladder (verified > confirmed > attested >
observed > reported). This module connects those facts with construction
knowledge SPECIFIC TO THE BUILDING MODEL PASSED IN -- its levels, its foundation
(footings + slab on grade, or not), its frame (cold-formed steel or not), which
levels carry plumbing, what is on its roof -- and says what follows. Nothing
here is a template applied blindly: a rule that needs a model fact (a slab on
grade, roof drains, a mezzanine bath) runs only when the model states it.

Four kinds of output, never mixed:

  implications   what a VERIFIED record entails by itself. A passed DOB rough
                 inspection on floor 3 on Nov 5 means the inspected rough-in
                 existed on floor 3 on Nov 5: kind "verified", claim "done",
                 with `implied_by`. It implies nothing else (not a sign-off, not
                 the electrical, not the insulation).
  inferences     evidence.item(kind="inferred"): a plausible conclusion that
                 >= 2 INDEPENDENT signals support. Each carries its signals
                 (source, ref, date, category), contradictions, a confidence
                 word WITH the rule that produced it, what would disprove it,
                 and what it unlocks / blocks. An inference never becomes a
                 fact, a passed inspection or a percent; evidence.status()
                 ignores it.
  contradictions records that cannot all be true as written (an impossible
                 floor, a pour where the model has no cast slab, a headcount
                 that disagrees with the gate, work out of physical order).
                 Stated, never resolved by guessing.
  closure        per level, what must be on record before walls and ceilings
                 close, and which of those have NO record yet. No record is
                 UNKNOWN, never "not done".

INDEPENDENCE (evidence.independence_key): a signal's source and actor. Two log
rows of one crew are one source; the plumber's row and the insulator's row are
two; a gate check-in says a crew was on site, never where, so it is context and
never counts toward an inference about a place.

CONFIDENCE, mechanically (CONFIDENCE_RULES):
  high    >= 3 independent sources, >= 1 of them names this level ALONE, >= 1
          is observed-or-stronger, and no contradiction touches the subject.
  medium  >= 2 independent sources and (one names this level alone, or one
          is observed-or-stronger).
  low     >= 2 independent sources, every one a multi-floor statement
          ("floors 1-4") below observed.
  Each contradiction touching the subject lowers it one step (never below low).

MULTI-FLOOR STATEMENTS ("floors 1-4") are about every floor they name and about
no one floor alone. A floor is NARROWED only by an independent signal that names
it alone (a photo filed for that floor, another crew's row for that floor).

Pure: no database, no network. Items are evidence.item dicts.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import evidence as E
from lib import location_binder as LB

SOURCE = "lib/construction_inference"

# ── WORK VOCABULARY (graph_v1 ids where graph_v1 has them) ─────────────────

#: The parts a passed plumbing rough inspection covers (gas only where the model has gas).
PLUMBING = ("rough_dwv", "rough_water", "rough_gas")
#: A record that says "plumbing" / a plumber's "MEP rough-in" without naming the part.
PLUMBING_GENERIC = "rough_plumbing"
SYSTEMS: Dict[str, Tuple[str, ...]] = {
    "plumbing": (PLUMBING_GENERIC,) + PLUMBING,
    "electrical": ("rough_electric", "rough_lowvolt"),
    "hvac": ("rough_duct",),
    "sprinkler": ("rough_sprinkler",),
}
SYSTEM_GATE = {"plumbing": "gate_plumbing_rough", "electrical": "gate_electrical_rough",
               "sprinkler": "gate_sprinkler_hydro"}
#: Below the ground-floor slab (not graph_v1: graph_v1 starts at framing).
UNDERGROUND = {"plumbing": "underground_plumbing", "electrical": "underground_electric"}
UNDERGROUND_GATE = "gate_plumbing_underground"
SLAB_ON_GRADE = "slab_on_grade"

#: Physical order on one level of a framed building. A stage's work closes over
#: the previous stage's work, so a later stage started is a signal (never proof)
#: that the earlier stage is in place where the later one is.
STAGES = ("slab", "framing", "rough", "rough_inspection", "insulation", "board", "finish")
_STAGE_OF = {SLAB_ON_GRADE: "slab", "framing": "framing",
             **{n: "rough" for nodes in SYSTEMS.values() for n in nodes},
             "gate_plumbing_rough": "rough_inspection", "gate_electrical_rough": "rough_inspection",
             "gate_sprinkler_hydro": "rough_inspection", "gate_firestopping": "rough_inspection",
             "insulation": "insulation", "gate_nycecc_insulation": "insulation",
             "drywall": "board", "ceiling_drop": "board", "prime": "finish", "finishes": "finish",
             "mep_trim": "finish"}
#: Closing walls and ceilings needs these on record first (graph_v1's pre-board
#: gate cluster), each only where the model says the system exists.
CLOSURE_GATES = (("gate_plumbing_rough", "plumbing"), ("gate_electrical_rough", "electrical"),
                 ("gate_sprinkler_hydro", "sprinkler"), ("gate_firestopping", None),
                 ("gate_nycecc_insulation", None))

CONFIDENCE_RULES = {
    "high": ">= 3 independent sources, >= 1 names this level alone, >= 1 observed-or-stronger, no contradiction",
    "medium": ">= 2 independent sources and (>= 1 names this level alone or >= 1 observed-or-stronger)",
    "low": ">= 2 independent sources, all multi-floor statements below observed",
    "step_down": "each contradiction touching the subject lowers the confidence one step (never below low)",
}
_STEP = {"high": "medium", "medium": "low", "low": "low"}
OBSERVED_OR_STRONGER = ("verified", "confirmed", "attested", "observed")
#: Sources that say who was on site, never where: context, never a place signal.
PRESENCE_ONLY_SOURCES = ("checkins",)


# ── THE BUILDING MODEL ────────────────────────────────────────────────────

_ORD = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8}


def _val(node: Any) -> Any:
    return node.get("value") if isinstance(node, dict) and "value" in node else node


def model_from_building(b: Dict[str, Any], *, name: str = "") -> Dict[str, Any]:
    """The facts the rules need, read from a drawings-lane building.json
    (sections structure / derived_quantities_per_floor / plumbing /
    fire_protection_electrical_vertical / unit_schedule / inspections). A fact
    the file does not state stays None, and a rule that needs it does not run."""
    st = b.get("structure") or {}
    system = str(_val(st.get("system")) or "")
    found = _val(st.get("foundation"))
    found_text = (found.get("type") if isinstance(found, dict) else str(found or "")) or ""
    q = _val(b.get("derived_quantities_per_floor")) or {}
    levels: List[str] = []
    for key in sorted((k for k in q if k in _ORD), key=lambda k: _ORD[k]):
        levels.append(f"FLOOR_{_ORD[key]}")
    if "MEZZANINE" in q:
        levels.append("MEZZANINE")
    if "ROOF" in q:
        levels.append("ROOF")
    baths = {lv: (q.get(k) or {}).get("baths") for k, lv in
             [(k, f"FLOOR_{_ORD[k]}") for k in q if k in _ORD] + [("MEZZANINE", "MEZZANINE")]}
    plumb = b.get("plumbing") or {}
    roof_text = " ".join(str((q.get("ROOF") or {}).get(k) or "") for k in ("notes",)) + " " + \
        str(_val(plumb.get("gas")) or "") + " " + str(_val(plumb.get("sewer_and_storm")) or "")
    roof_plumbing = [w for w, rx in (("roof drains", r"roof\s+drains?|\(AD\)"), ("hot-water heater room", r"HWH"),
                                     ("vent stacks through the roof", r"V-\d|vent"))
                     if re.search(rx, roof_text, re.I)]
    stacks = str((_val(plumb.get("stacks_risers")) or {}).get("located_per_plan") or "") if isinstance(
        _val(plumb.get("stacks_risers")), dict) else ""
    if re.search(r"P-105", stacks):
        roof_plumbing.append("stacks located on the roof plan (P-105)")
    plumbing_levels = [lv for lv in levels if (baths.get(lv) or 0) > 0]
    if roof_plumbing and "ROOF" in levels:
        plumbing_levels.append("ROOF")
    fp = b.get("fire_protection_electrical_vertical") or {}
    sprinkler = str(_val(fp.get("sprinkler")) or "")
    units: Dict[str, List[str]] = defaultdict(list)
    for u in _val(b.get("unit_schedule")) or []:
        if isinstance(u, dict) and u.get("floor"):
            units[f"FLOOR_{int(u['floor'])}"].append(str(u.get("id")))
            if u.get("upper_mezz_net_sf"):
                units["MEZZANINE"].append(str(u.get("id")))
    slab_on_grade = bool(re.search(r"slab[\s-]on[\s-]grade|\bSOG\b", found_text, re.I))
    piles = None if not found_text else bool(re.search(r"\bpiles?\b(?!\s*/)", found_text, re.I)
                                              and not re.search(r"no\s+piles", found_text, re.I))
    if found_text and "no piles" in str(b.get("structure")).lower():
        piles = False
    elev = str(_val(fp.get("elevator")) or "")
    cfs = bool(re.search(r"cold[\s-]formed|\bCFS\b", system, re.I))
    return {
        "name": name,
        "levels": levels,
        "ground_level": levels[0] if levels and levels[0] == "FLOOR_1" else None,
        "below_grade_levels": [],          # the model names no cellar; a record that does is a contradiction
        "foundation": found_text or None,
        "slab_on_grade": slab_on_grade,
        "piles_drawn": piles,
        # Cast-in-place concrete only where the model has it: the ground slab
        # on grade. A CFS frame's upper floors are joists + panel subfloor.
        "cast_concrete_levels": [levels[0]] if slab_on_grade and levels else [],
        "superstructure": "cfs" if cfs else (system or None),
        "plumbing_levels": plumbing_levels,
        "roof_plumbing": roof_plumbing,
        "systems": {"plumbing": bool(plumbing_levels), "gas": bool(re.search(r"\bgas\b", str(_val(plumb.get("gas")) or ""), re.I)),
                    "sprinkler": bool(re.search(r"sprinkler", sprinkler, re.I)),
                    "elevator": False if re.match(r"\s*NONE", elev, re.I) else (True if elev else None),
                    "electrical": True, "hvac": True},
        "units": dict(units),
        "baths": {k: v for k, v in baths.items() if v is not None},
    }


# ── SMALL HELPERS ─────────────────────────────────────────────────────────

def _on(i: Dict[str, Any]) -> Optional[date]:
    v = i.get("on")
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if isinstance(d, date) else None


def system_of(node: Optional[str]) -> Optional[str]:
    for s, nodes in SYSTEMS.items():
        if node in nodes:
            return s
    for s, n in UNDERGROUND.items():
        if node == n:
            return s
    return None


def stage_of(node: Optional[str]) -> Optional[str]:
    return _STAGE_OF.get(node or "")


def signal(i: Dict[str, Any], role: str, level: Optional[str] = None) -> Dict[str, Any]:
    """One supporting signal, kept with its own category and place."""
    lv = list(i.get("levels") or ())
    return {"source": i.get("source"), "ref": i.get("ref"), "on": _iso(_on(i)), "kind": i.get("kind"),
            "claim": i.get("claim"), "node": i.get("node"), "sub": i.get("sub"), "by": i.get("by"),
            "levels": lv, "names_level_alone": bool(level) and lv == [level], "quote": (i.get("quote") or "")[:160],
            "role": role}


def _place_signals(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in signals if s.get("source") not in PRESENCE_ONLY_SOURCES]


def confidence(signals: Sequence[Dict[str, Any]], n_contradictions: int = 0) -> Tuple[str, str]:
    """(word, rule) by CONFIDENCE_RULES. Only place signals count."""
    sig = _place_signals(signals)
    n = E.independent_sources(sig)
    alone = any(s.get("names_level_alone") for s in sig)
    strong = any(s.get("kind") in OBSERVED_OR_STRONGER for s in sig)
    # The base word ignores contradictions; each one then steps it down once
    # (so "high" also means "no contradiction").
    if n >= 3 and alone and strong:
        word, rule = "high", CONFIDENCE_RULES["high"]
    elif n >= 2 and (alone or strong):
        word, rule = "medium", CONFIDENCE_RULES["medium"]
    else:
        word, rule = "low", CONFIDENCE_RULES["low"]
    for _ in range(n_contradictions):
        word = _STEP[word]
    if n_contradictions:
        rule = f"{rule}; {CONFIDENCE_RULES['step_down']} ({n_contradictions} contradiction(s))"
    return word, rule


def _contradiction(kind: str, what: str, refs: Iterable[Any], *, levels: Sequence[str] = (), node: Optional[str] = None,
                   on: Optional[date] = None, explanations: Sequence[str] = ()) -> Dict[str, Any]:
    return {"kind": kind, "what": what, "refs": sorted({str(r) for r in refs if r}), "levels": list(levels),
            "node": node, "on": _iso(on), "candidate_explanations": list(explanations)}


# ── RULE: VERIFIED IMPLICATIONS ───────────────────────────────────────────

#: What a passed plumbing rough (or underground) inspection never stands for.
#: It unlocks close-in for PLUMBING only, on the levels it names.
NOT_IMPLIED_BY_A_ROUGH_PASS = (
    "final plumbing inspection / plumbing completion", "plumbing sign-off (the permit stays open)",
    "DEP water service / sewer connection", "TR1 special inspections (cold-formed steel, steel details, "
    "adjacent structures)", "electrical rough or final", "sprinkler hydrostatic test", "fire alarm",
    "insulation / energy (TR8) inspection", "fire-stopping special inspection")


def implications(facts: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A passed (verified / confirmed) rough or underground inspection on a
    level means the inspected installation existed there on that day. That is
    a reading of the record, not an inference: it carries the record's own
    rung and `implied_by`. It implies nothing about any other system, level or
    stage, and is never a sign-off."""
    out = []
    for g in facts:
        if g.get("claim") != "done" or g.get("kind") not in ("verified", "confirmed"):
            continue
        if g.get("node") == "gate_plumbing_rough":
            nodes = PLUMBING if model.get("systems", {}).get("gas") else ("rough_dwv", "rough_water")
        elif g.get("node") == UNDERGROUND_GATE and g.get("kind") == "verified":
            nodes = (UNDERGROUND["plumbing"],)
        else:
            continue
        for n in nodes:
            it = E.item(g["kind"], "done", source=g["source"], ref=f"{g['ref']}:implies:{n}", project_id=g["project_id"],
                        node=n, levels=g.get("levels") or (), on=_on(g), said_at=g.get("said_at"), by=g.get("by"),
                        quote=g.get("quote"), shared=g.get("shared", False),
                        note=f"implication of {g['kind']} record {g['ref']}: the inspected installation existed "
                             f"by {_iso(_on(g))}; not a sign-off, says nothing of other systems or stages")
            it["implied_by"] = g["ref"]
            it["does_not_imply"] = list(NOT_IMPLIED_BY_A_ROUGH_PASS)
            out.append(it)
    return out


# ── RULE: CONTRADICTIONS ──────────────────────────────────────────────────

_POUR = re.compile(r"\bpour(?:ing|ed|s)?\b", re.I)
_SLAB = re.compile(r"\bslab\b", re.I)
_CELLAR = re.compile(r"\bcellar\b|\bbasement\b", re.I)
_PILE = re.compile(r"\bpiles?\b|\bpile\s+caps?\b|\bgrade\s+beams?\b", re.I)
_ROOF_WORD = re.compile(r"\broof\b", re.I)
_CONCRETE_FRAME = re.compile(r"\b(?:pour|formwork|rebar)\w*\b[^,;]{0,20}\b(?:columns?|shear\s+walls?)\b"
                             r"|\b(?:columns?|shear\s+walls?)\b[^,;]{0,20}\b(?:pour|formwork|rebar)\w*\b", re.I)


def contradictions(items: Sequence[Dict[str, Any]], model: Dict[str, Any], *,
                   headcounts: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    known = set(model.get("levels") or ())
    # Impossible places: a level the building does not have.
    bad: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for i in items:
        for lv in list(i.get("levels") or ()) + list(i.get("candidates") or ()):
            if known and lv not in known:
                bad[lv].append(i)
    for lv, rows in sorted(bad.items()):
        out.append(_contradiction(
            "impossible_level", f"{len(rows)} record(s) name {lv}, which this building does not have "
            f"(levels: {', '.join(model.get('levels') or [])})", (r["ref"] for r in rows), levels=[lv],
            explanations=["the record was bound to the wrong project", "the floor tag is wrong"]))
    # Concrete where the model has no cast slab.
    cast = set(model.get("cast_concrete_levels") or ())
    if model.get("superstructure") == "cfs":
        for i in items:
            q = i.get("quote") or ""
            if _POUR.search(q) and _SLAB.search(q) and any(lv not in cast for lv in i.get("levels") or ()):
                out.append(_contradiction(
                    "pour_without_a_cast_slab", "a slab pour is recorded on a level where the model has a CFS joist "
                    "floor with a panel subfloor, not a cast slab", [i["ref"]], levels=i.get("levels") or (),
                    on=_on(i)))
    # A cast concrete frame (columns, shear walls) named on a CFS building.
    if model.get("superstructure") == "cfs":
        rows = [i for i in items if _CONCRETE_FRAME.search(i.get("quote") or "")]
        if rows:
            out.append(_contradiction(
                "concrete_frame_in_a_cfs_building", f"{len(rows)} record(s) name concrete columns / shear walls; the "
                "structural model is a cold-formed steel frame with CFS braced shear walls", (r["ref"] for r in rows),
                explanations=["activity chips remembered from another job were re-used",
                              "foundation-wall work was named with frame words"]))
    # A cellar named on a building with none.
    if not model.get("below_grade_levels"):
        rows = [i for i in items if _CELLAR.search(i.get("quote") or "") and i.get("source") != "dob_logs"]
        if rows:
            out.append(_contradiction(
                "names_a_cellar", f"{len(rows)} record(s) name a cellar; the building model has none "
                "(slab on grade)", (r["ref"] for r in rows),
                explanations=["'cellar slab' is the crew's name for the ground slab on grade",
                              "the record belongs to another building"]))
    # Piles where the drawings show footings only.
    if model.get("piles_drawn") is False:
        rows = [i for i in items if _PILE.search(i.get("quote") or "")]
        if rows:
            out.append(_contradiction(
                "piles_not_on_drawings", f"{len(rows)} record(s) name piles / pile caps / grade beams; the structural "
                "model shows spread footings and a slab on grade, no piles", (r["ref"] for r in rows),
                explanations=["support-of-excavation piles at the neighbours (an SOE filing exists)",
                              "foundation drawings (not provided) differ"]))
    # Work whose words name the roof while the row's filed location names
    # other floors ("Roof MEP" filed under "floors 1-4").
    for i in items:
        filed = filed_location(i)
        if filed is None or not _ROOF_WORD.search(i.get("quote") or ""):
            continue
        filed_levels = LB.read(filed)["levels"]
        if filed_levels and "ROOF" not in filed_levels:
            out.append(_contradiction(
                "work_names_another_level", f"'{(i.get('quote') or '')[:60]}' names the roof but the row's filed "
                f"location is '{filed}'", [i["ref"]], levels=i.get("levels") or (), node=i.get("node"), on=_on(i),
                explanations=["the crew worked on the roof and the location column was left at its default",
                              "the work served floors 1-4 from the roof"]))
    # Headcount: log vs gate, same day and company.
    for h in headcounts or ():
        lc, gc = h.get("log_count"), h.get("gate_count")
        if isinstance(lc, int) and isinstance(gc, int) and lc != gc:
            out.append(_contradiction(
                "headcount_log_vs_gate", f"{h.get('sub')} on {h.get('date')}: {lc} on the daily log, {gc} at the gate",
                h.get("refs") or (), on=h.get("date") if isinstance(h.get("date"), date) else None))
    return out


FILED_LOCATION = "filed location: "


def filed_location(i: Dict[str, Any]) -> Optional[str]:
    """The location text exactly as the record filed it, when the adapter kept
    it in `note` ("filed location: floors 1-4; ...")."""
    note = i.get("note") or ""
    if FILED_LOCATION not in note:
        return None
    return note.split(FILED_LOCATION, 1)[1].split(";", 1)[0].strip()


def _touching(cons: Sequence[Dict[str, Any]], level: str, nodes: Sequence[str], refs: Sequence[str]) -> List[Dict[str, Any]]:
    rs = set(refs)
    return [c for c in cons if (set(c.get("refs") or ()) & rs)
            or (level in (c.get("levels") or ()) and c.get("node") in nodes)]


# ── RULE: STAGES IN ORDER ─────────────────────────────────────────────────

def stages(facts: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Per level and stage: first and last date on record, the nodes and refs."""
    out: Dict[str, Dict[str, Any]] = {}
    for lv in model.get("levels") or ():
        per: Dict[str, Dict[str, Any]] = {}
        for i in facts:
            st, d = stage_of(i.get("node")), _on(i)
            if not st or not d or lv not in (i.get("levels") or ()) or i.get("claim") not in E.WORK_CLAIMS:
                continue
            s = per.setdefault(st, {"first": d, "last": d, "nodes": set(), "refs": [], "alone": False})
            s["first"], s["last"] = min(s["first"], d), max(s["last"], d)
            s["nodes"].add(i["node"])
            s["refs"].append(i["ref"])
            s["alone"] = s["alone"] or (i.get("levels") == [lv])
        out[lv] = {k: {"first": _iso(v["first"]), "last": _iso(v["last"]), "nodes": sorted(v["nodes"]),
                       "refs": sorted(set(v["refs"])), "names_level_alone": v["alone"]}
                   for k, v in sorted(per.items(), key=lambda kv: STAGES.index(kv[0]))}
    return out


def order_contradictions(stage_map: Dict[str, Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A stage first recorded before the stage it physically closes over was
    ever recorded on that level. A question for the superintendent, never a
    cause: crews often name the later stage for preparatory work."""
    out = []
    for lv, per in stage_map.items():
        firsts = {k: date.fromisoformat(v["first"]) for k, v in per.items()}
        for later, earlier in (("framing", "slab"), ("insulation", "rough"), ("board", "rough"),
                               ("finish", "insulation"), ("finish", "board")):
            if later not in firsts:
                continue
            if earlier == "slab" and not (model.get("slab_on_grade") and lv == model.get("ground_level")):
                continue
            if earlier in firsts and firsts[later] < firsts[earlier]:
                out.append(_contradiction(
                    "stage_out_of_order", f"{later} on {lv} first recorded {firsts[later]}, before {earlier} "
                    f"({firsts[earlier]}); on this building {earlier} comes first", per[later]["refs"][:5],
                    levels=[lv], on=firsts[later],
                    explanations=[f"the crew named {later} for preparatory work",
                                  f"{earlier} on {lv} began earlier than any record shows"]))
            elif earlier not in firsts and earlier in ("insulation", "board") and later == "finish":
                out.append(_contradiction(
                    "stage_without_predecessor", f"{later} on {lv} recorded from {firsts[later]} with no {earlier} "
                    f"on record on {lv}", per[later]["refs"][:5], levels=[lv], on=firsts[later],
                    explanations=["fixtures set during rough-in (tubs, shower valves) were called trim/fixtures",
                                  f"{earlier} on {lv} is unrecorded"]))
    return out


# ── RULE: ROUGH-IN IN PLACE, PER LEVEL AND SYSTEM ─────────────────────────

def _successors(facts: Sequence[Dict[str, Any]], level: str, system: str) -> List[Dict[str, Any]]:
    """Work recorded on `level` that physically closes over this system's
    rough-in: insulation, board, or this system's own fixture set / trim."""
    out = []
    for i in facts:
        st = stage_of(i.get("node"))
        if level not in (i.get("levels") or ()) or i.get("claim") not in E.WORK_CLAIMS:
            continue
        if st in ("insulation", "board") and i.get("node") not in ("gate_nycecc_insulation",):
            out.append(i)
        elif i.get("node") == "mep_trim" and system_of_trim(i) == system:
            out.append(i)
    return out


def system_of_trim(i: Dict[str, Any]) -> Optional[str]:
    t = f"{i.get('sub') or ''} {i.get('note') or ''}".lower()
    if "plumb" in t or "water main" in t:
        return "plumbing"
    if "electric" in t or "power" in t:
        return "electrical"
    if "hvac" in t or "mechanical" in t:
        return "hvac"
    return None


def _roof_successors(facts: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Roofing over a roof the model gives drains / vents through: the drain
    bodies and vent flashings are set before the membrane."""
    if not model.get("roof_plumbing"):
        return []
    return [i for i in facts if i.get("node") == "roofing" and i.get("claim") in E.WORK_CLAIMS]


def rough_in(facts: Sequence[Dict[str, Any]], model: Dict[str, Any], level: str, system: str, *,
             as_of: date, project_id: Any, cons: Sequence[Dict[str, Any]] = ()) -> Optional[Dict[str, Any]]:
    """An inference that `system` rough-in is in place (claim done) or under
    way (claim in_progress) on `level`, or None when fewer than two independent
    place signals support either. Never when a verified / confirmed record
    already says the gate passed there (that is a fact, see implications)."""
    nodes = SYSTEMS[system]
    gate = SYSTEM_GATE.get(system)
    on_level = [i for i in facts if level in (i.get("levels") or ())]
    if gate and any(i.get("node") == gate and i.get("claim") == "done" and i.get("kind") in ("verified", "confirmed")
                    for i in on_level):
        return None
    direct = [i for i in on_level if i.get("node") in nodes and i.get("claim") in E.WORK_CLAIMS]
    if not direct:
        return None
    sigs = [signal(i, "rough-in recorded on this level", level) for i in direct]
    succ = _successors(facts, level, system)
    if level == "ROOF" and system == "plumbing":
        succ += _roof_successors(facts, model)
    sigs += [signal(i, "later work recorded here closes over the rough-in", level) for i in succ]
    # A statement that the gate passed / was booked, below verified (a named
    # person, a log line): support, never the fact itself.
    stated = [i for i in facts if gate and i.get("node") == gate and i.get("claim") in ("done", "scheduled", "present")
              and (not i.get("levels") or level in i["levels"]) and i.get("kind") not in ("verified", "confirmed")]
    sigs += [signal(i, "a statement about this system's rough inspection", level) for i in stated]
    place = _place_signals(sigs)
    if E.independent_sources(place) < E.MIN_INDEPENDENT_SIGNALS:
        return None
    claim = "done" if (succ or any(i.get("claim") == "done" for i in stated)) else "in_progress"
    refs = [s["ref"] for s in sigs]
    touch = _touching(cons, level, nodes, refs)
    word, rule = confidence(sigs, len(touch))
    last = max(d for d in (_on(i) for i in direct + succ + stated) if d)
    first = min(d for d in (_on(i) for i in direct) if d)
    alone = sorted({s["ref"] for s in sigs if s["names_level_alone"]})
    label = {"plumbing": "plumbing (water, sanitary/storm, gas)", "electrical": "electrical",
             "hvac": "HVAC duct", "sprinkler": "sprinkler"}[system]
    what = "in place" if claim == "done" else "under way"
    basis = (f"{label} rough-in recorded on {level} from {first}; "
             + (f"{len(succ)} later record(s) on {level} close over it; " if succ else "")
             + (f"named on {level} alone by {len(alone)} record(s)" if alone else
                "every record names several floors together (not narrowed to this floor)"))
    return E.item(
        "inferred", claim, source=SOURCE, ref=f"inf:rough:{system}:{level}:{as_of.isoformat()}", project_id=project_id,
        node=f"rough_{system}", levels=[level], on=last, sub=None,
        quote=f"{label} rough-in on {level}: {what} (inferred)", basis=basis,
        note=f"as of {as_of.isoformat()}; rule rough_in_place; narrowed by: {', '.join(alone) or 'nothing'}",
        signals=sigs, confidence=word, confidence_rule=rule, contradictions=touch,
        disproof=(f"a DOB {label} rough inspection on {level} that failed or was never requested; a record that the "
                  f"rough-in on {level} started after {last}; a photo of {level} showing open walls with no "
                  f"{label} piping or wiring"),
        unlocks=[f"{gate} on {level} (the rough inspection can be requested)"] if gate and claim == "done" else [],
        blocks=([f"insulation / board on {level} until {gate} is on record"] if gate else []))


# ── RULE: SLAB ON GRADE CLOSES OVER WHAT IS UNDER IT ──────────────────────

_SUBBASE = re.compile(r"\bgravel\b|vapou?r\s+barrier|\bmesh\b|\bsub[\s-]?base\b", re.I)


def slab_pour(facts: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The ground slab-on-grade pour: the earliest slab-on-grade record that
    names a slab pour AND after which no sub-base preparation (gravel, vapour
    barrier, mesh) is recorded on that level. A slab on grade is poured over
    its prepared sub-base, never before it, so a "pour" recorded before the
    gravel went down is not this slab (a footing, a pile cap, a list of chips)."""
    g = model.get("ground_level")
    rows = [i for i in facts if g in (i.get("levels") or ()) and i.get("node") == SLAB_ON_GRADE and _on(i)]
    prep = [_on(i) for i in rows if _SUBBASE.search(i.get("quote") or "")]
    pours = sorted((i for i in rows if _POUR.search(i.get("quote") or "") and _SLAB.search(i.get("quote") or "")
                    and not any(p > _on(i) for p in prep)), key=_on)
    return pours[0] if pours else None


def under_slab(facts: Sequence[Dict[str, Any]], model: Dict[str, Any], system: str, *, as_of: date,
               project_id: Any, cons: Sequence[Dict[str, Any]] = ()) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Only when the model has a slab on grade: work under the ground slab is
    in place by the day the slab was poured over it. Returns (inference or
    None, contradictions: under-slab work recorded after the pour)."""
    g = model.get("ground_level")
    if not (model.get("slab_on_grade") and g):
        return None, []
    pour = slab_pour(facts, model)
    node = UNDERGROUND[system]
    under = [i for i in facts if i.get("node") == node and g in (i.get("levels") or ()) and _on(i)]
    if not pour or not under:
        return None, []
    p = _on(pour)
    before = [i for i in under if _on(i) <= p]
    after = [i for i in under if _on(i) > p]
    cons_out = []
    if after:
        cons_out.append(_contradiction(
            "under_slab_after_pour", f"{system} work under the {g} slab recorded after the slab pour of {p}",
            [i["ref"] for i in after] + [pour["ref"]], levels=[g], node=node, on=_on(after[0]),
            explanations=["work at the foundation wall or outside the slab (a service entry), not under it",
                          "a patch / trench cut through the new slab"]))
    if not before:
        return None, cons_out
    # An underground PLUMBING inspection speaks only for the plumbing.
    visits = [i for i in facts if system == "plumbing" and i.get("node") == UNDERGROUND_GATE and _on(i) and _on(i) <= p]
    sigs = ([signal(i, f"{system} work under the slab recorded before the pour", g) for i in before]
            + [signal(pour, "the slab on grade poured over it", g)]
            + [signal(i, "an inspection of the under-slab work was recorded", g) for i in visits])
    if E.independent_sources(_place_signals(sigs)) < E.MIN_INDEPENDENT_SIGNALS:
        return None, cons_out
    refs = [s["ref"] for s in sigs]
    touch = _touching(list(cons) + cons_out, g, (node,), refs)
    word, rule = confidence(sigs, len(touch))
    label = "plumbing" if system == "plumbing" else "electrical conduit"
    inf = E.item(
        "inferred", "done", source=SOURCE, ref=f"inf:under_slab:{system}:{as_of.isoformat()}", project_id=project_id,
        node=node, levels=[g], on=p, space="below the ground slab",
        quote=f"under-slab {label} on {g}: in place by the slab pour of {p} (inferred)",
        basis=f"{len(before)} record(s) of under-slab {label} on {g} up to {_on(before[-1])}; the slab on grade was "
              f"recorded poured on {p}; on a slab-on-grade building nothing is laid under a slab after it is poured",
        note=f"as of {as_of.isoformat()}; rule under_slab_before_pour",
        signals=sigs, confidence=word, confidence_rule=rule, contradictions=touch,
        disproof=f"a record of under-slab {label} on {g} laid after {p}; the slab pour recorded on {p} was another "
                 f"slab; a failed underground inspection",
        unlocks=[f"framing on {g} on the finished slab"], blocks=[])
    return inf, cons_out


# ── CLOSURE PREREQUISITES ─────────────────────────────────────────────────

def closure(facts: Sequence[Dict[str, Any]], inferences: Sequence[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Any]:
    """Per level where insulation or board is recorded: each pre-board gate
    the model needs, with what is on record. No record is unknown."""
    out = {}
    systems = model.get("systems") or {}
    for lv in model.get("levels") or ():
        closing = sorted((i for i in facts if lv in (i.get("levels") or ()) and stage_of(i.get("node")) in ("insulation", "board")
                          and i.get("node") != "gate_nycecc_insulation" and _on(i)), key=_on)
        if not closing:
            continue
        rows = []
        for gate, system in CLOSURE_GATES:
            if system == "plumbing" and lv not in (model.get("plumbing_levels") or ()):
                continue
            if system == "sprinkler" and not systems.get("sprinkler"):
                continue
            on_rec = [i for i in facts if i.get("node") == gate and lv in (i.get("levels") or ())]
            st = E.status(on_rec)
            inf = [x for x in inferences if system and x.get("node") == f"rough_{system}" and lv in x["levels"]]
            rows.append({"gate": gate, "status": st, "refs": [i["ref"] for i in on_rec],
                         "rough_in": ({"inferred": inf[0]["claim"], "confidence": inf[0]["confidence"]} if inf else None),
                         "open": st == "unknown"})
        out[lv] = {"closing_first": _iso(_on(closing[0])), "closing_refs": [i["ref"] for i in closing][:6],
                   "prerequisites": rows,
                   "open_on_record": [r["gate"] for r in rows if r["open"]],
                   "words": (f"walls / ceilings on {lv} began closing {_on(closing[0])}; with no record (unknown, not 'not done'): "
                             + ", ".join(r["gate"] for r in rows if r["open"])) if any(r["open"] for r in rows) else
                            f"walls / ceilings on {lv} began closing {_on(closing[0])}; every pre-board gate has a record",
                   "note": "a plumbing rough pass unlocks close-in for PLUMBING only; each other gate stands on its own"}
    return out


# ── ALL RULES ─────────────────────────────────────────────────────────────

def infer(items: Sequence[Dict[str, Any]], model: Dict[str, Any], *, as_of: date, project_id: Any = "",
          headcounts: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Every rule over the facts dated on or before `as_of`."""
    facts = [i for i in items if E.is_fact(i) and (_on(i) is None or _on(i) <= as_of)]
    imp = implications([i for i in facts if _on(i)], model)
    facts_plus = facts + imp
    dated = [i for i in facts_plus if _on(i)]
    stage_map = stages(dated, model)
    cons = contradictions(facts, model, headcounts=[h for h in headcounts or ()
                                                     if not isinstance(h.get("date"), date) or h["date"] <= as_of])
    cons += order_contradictions(stage_map, model)
    infs: List[Dict[str, Any]] = []
    for system in ("plumbing", "electrical"):
        inf, c = under_slab(dated, model, system, as_of=as_of, project_id=project_id, cons=cons)
        cons += c
        if inf:
            infs.append(inf)
    for system, nodes in SYSTEMS.items():
        if system == "sprinkler" and not (model.get("systems") or {}).get("sprinkler"):
            continue
        levels = model.get("plumbing_levels") if system == "plumbing" else model.get("levels")
        for lv in levels or ():
            inf = rough_in(dated, model, lv, system, as_of=as_of, project_id=project_id, cons=cons)
            if inf:
                infs.append(inf)
    return {"as_of": as_of.isoformat(), "implications": imp, "inferences": infs, "contradictions": cons,
            "stages": stage_map, "closure": closure(dated, infs, model), "confidence_rules": CONFIDENCE_RULES}
