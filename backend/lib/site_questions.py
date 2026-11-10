"""SITE QUESTIONS: the few questions worth asking TODAY, chosen by what each
answer would change in the schedule.

Pure: no database, no network, no clock. It EXTENDS lib/confirmation_queue
(which reads a job's evidence for six fixed triggers) with the questions a
building model and a remaining-work schedule ESTIMATE (lib/schedule_generator)
make visible, and re-uses its parts rather than copying them:

  * the daily cap (confirmation_queue.MAX_PER_PERSON) and the repeat window
    (REPEAT_DAYS) and the morning-message shape;
  * the closed answers and their reading: every question that a fixed rule can
    read names the confirmation_queue trigger whose answers it takes
    (`reads_as`), so confirmation_queue.parse_reply reads the reply, English or
    Spanish, unchanged; whatever it cannot read is left for the DM brain;
  * the answer item: confirmation_queue.answer_item turns an answer into an
    ATTESTED evidence item (the person, their words, the question). "Don't
    know" stays dont_know, never a no;
  * who may be asked what: lib/dm_roles.tool_refusal, per topic (below);
  * shadow: confirmation_queue.unmessageable_roles() says which roles cannot be
    messaged first; their questions are generated in SHADOW and marked so.

WHERE QUESTIONS COME FROM (`TRIGGERS`), each from a real gap, never a hunch:
  unknown_state        a work activity on a critical path (any scenario) or in
                       the next three weeks whose state is unknown or "in
                       progress, amount unmeasured".
  inspection_not_public  an inspection gate in the next three weeks whose result
                       no public source carries (DOB electrical: Inspections
                       Plus; FDNY; DEP; licensed sprinkler test; TR1/TR8).
  regulatory_deadline  a permit whose expiry falls inside REGULATORY_HORIZON_DAYS.
  utility_status       a utility lead (Con Ed, National Grid) in the window whose
                       application status is unknown.
  acceleration_lever   a schedule_generator lever that saves time alone: the
                       commitment it needs is a question for the PM.
  inference_disproof   an inference (a "not started" or "done" the schedule or
                       the model INFERRED) whose disproof a person can check by
                       looking.
  contradiction        a contradiction in the model, or between public records.
  statement_gap        an attested statement that left out what the schedule
                       needs (a date, which agency), or that only a document
                       can verify.
  stale_sub            a roster sub with no ORIGINAL record for STALE_DAYS whose
                       open work is in the window. Attached to that work's
                       question as a trigger; never a question of its own.
  multi_floor_statement  a state that only multi-floor statements support
                       (shared_only): asked per floor ONLY where the floor
                       changes the finish date (`floor_matters`).

WHAT EACH ANSWER DOES. Every branch says the evidence it would create
(`model_update`: attested at most; an inspection result a person states stays
attested until a document or agency record verifies it; "don't know" changes
nothing and the question stays open) and the schedule state it would set. The
schedule is RE-RUN per branch (Rescheduler: schedule_generator.schedule_scenario
for every scenario) and the branch reports its TCO delta per scenario and the
move of the first open successor. A person's word maps to the generator's
`operator_statement` evidence, which leaves `remaining_operator_done` of the
scope (never zero): a statement is not a verification.

SUPPRESSED, with the reason, never silently:
  answered_by_records  a record at verified (or an attested statement, for a
                       "did it happen" question) already answers it.
  redundant            same subject, aspect and place as a better question.
  no_decision          every branch re-runs to the same TCO in every scenario
                       and moves nothing in the next three weeks, and no
                       regulatory or record decision rides on it.
  floor_does_not_matter  a multi-floor statement whose floor changes no finish.
  not_permitted        no role that could answer may be asked it (dm_roles).
  outside_horizon      a deadline beyond REGULATORY_HORIZON_DAYS.
  daily_cap            every permitted person already has MAX_PER_PERSON today.
  asked_recently       asked within REPEAT_DAYS (history).
  premise_not_established  it presumes work no record shows (a test of pipe
                       nobody has recorded installing).

VALUE (`VALUE_FORMULA`, stated on every question with its terms):
  value = (T + N + D) x U x G x C
  T  schedule swing, working days: max over branches |dTCO normal|
     + 0.5 x max over branches max(|dTCO fast|, |dTCO conservative|)
  N  0.25 x min(20, max over branches |move of the first open successor|),
     counted only when that successor starts inside the three-week window
  D  decision weight for what the generator does not model (a permit deadline:
     3 within 14 days, 2 within 30, 1 within the horizon; a contradiction or a
     record decision: its stated weight; else 0)
  U  urgency 1 + max(0, 21 - days until needed) / 21  (needed = the deadline or
     the first successor's start, whichever is sooner)
  G  evidence gap: unknown 1.0, inferred 0.9, in progress unmeasured 0.8,
     attested (a document request) 0.5
  C  cost to answer: a look on site 1.0, an office lookup 0.9, a third party 0.7
Branch probabilities are NOT known and NOT used: T is the swing the answer can
produce, not an expected value.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import confirmation_queue as CQ
from lib import dm_roles
from lib import schedule_generator as G

ENGINE = "site_questions v1"
SCENARIOS = G.SCENARIOS
#: The next three weeks, in working days from the data date.
WINDOW_WD = 15
WINDOW_DAYS = 21
#: A permit expiring later than this is not today's question.
REGULATORY_HORIZON_DAYS = 45
#: No original record for this long makes a roster sub stale.
STALE_DAYS = 14
MAX_PER_PERSON = CQ.MAX_PER_PERSON
REPEAT_DAYS = CQ.REPEAT_DAYS

TRIGGERS = ("unknown_state", "inspection_not_public", "regulatory_deadline", "utility_status", "acceleration_lever",
            "inference_disproof", "contradiction", "statement_gap", "stale_sub", "multi_floor_statement")
SUPPRESSION_REASONS = ("answered_by_records", "redundant", "no_decision", "floor_does_not_matter", "not_permitted",
                       "outside_horizon", "daily_cap", "asked_recently", "premise_not_established")

VALUE_FORMULA = ("value = (T + N + D) x U x G x C; T = max|dTCO normal| + 0.5 x max(|dTCO fast|, |dTCO conservative|) "
                 "over branches (working days); N = 0.25 x min(20, max |first open successor move|) when it starts in "
                 "the 3-week window; D = decision weight the generator does not model (permit deadline 3/2/1 by "
                 "<=14/<=30/<=45 days; contradiction or record decision: stated); U = 1 + max(0, 21 - days until "
                 "needed)/21; G = evidence gap (unknown 1.0, inferred 0.9, in progress unmeasured 0.8, attested 0.5); "
                 "C = cost to answer (look on site 1.0, office lookup 0.9, third party 0.7). Branch probabilities are "
                 "not known and not used.")
GAP = {"unknown": 1.0, "inferred": 0.9, "in_progress": 0.8, "attested": 0.5}
COST = {"look": 1.0, "office": 0.9, "third_party": 0.7}

#: Topic -> the dm_roles tool that stands for it (lib/dm_roles.tool_refusal
#: decides). Progress and inspections are field tools; permits, agency records
#: (DOB / DEP / utility applications) and the subs list (a sub's commitments)
#: are reserved to a PM or an admin.
TOPIC_TOOLS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "progress": ("work_status", {}),
    "inspection": ("report_inspection", {}),
    "evidence": ("confirm_photo_place", {}),
    "permit": ("active_permits", {}),
    "agency_record": ("dob_status", {}),
    "subcontract": ("find_sub", {}),
    "schedule_approval": ("proposed_sequence", {"approve": True}),
}
#: Role slots a question can be addressed to. A subcontractor is not a LeveLog
#: user and has no role in dm_roles: a "company:<name>" answerer is asked
#: THROUGH the PM, and counts against the PM's daily cap.
ROLE_SLOTS = ("superintendent", "cp", "pm", "admin")
SUB_RELAY = "pm"

#: Assumed consequences, each labelled; used only by the branch that needs one.
HOLDS = {
    "blocked": G.assumption("q_hold_blocked", "Working days a blocked activity waits before it resumes",
                            "working days", "industry-assumption", 2, 5, 10, faster="lower",
                            basis="a blocker reported by a person, no duration stated"),
    "permit_lapse": G.assumption("q_hold_permit_lapse", "Working days to reinstate a permit renewed after it lapsed",
                                 "working days", "industry-assumption", 5, 10, 20, faster="lower",
                                 basis="DOB renewal after expiry: re-filing and review; no measured sample"),
}

#: The kind of work (key_of) -> (English, Spanish) words for it.
LABELS: Dict[str, Tuple[str, str]] = {
    "framing_close": ("interior framing close-out (partitions, blocking, ceiling drops)",
                      "el cierre del framing interior (particiones, blocking, bajadas de techo)"),
    "elec_rough": ("electrical rough-in", "la instalación eléctrica en bruto (rough-in)"),
    "lv_rough": ("fire alarm / smoke-CO / low-voltage rough-in",
                 "el cableado en bruto de alarma contra incendios, detectores de humo/CO y bajo voltaje"),
    "sprinkler_rough": ("sprinkler rough-in", "la tubería de rociadores (sprinklers) en bruto"),
    "sprinkler_riser": ("the sprinkler riser and double-check detector",
                        "el montante (riser) de rociadores y la válvula de doble retención"),
    "duct_rough": ("exhaust and corridor duct rough-in", "los ductos de extracción y del pasillo"),
    "ptac_sleeves": ("the PTAC wall sleeves", "las camisas (sleeves) de los PTAC en las paredes"),
    "insulation": ("exterior and demising wall insulation", "el aislamiento de las paredes exteriores y divisorias"),
    "firestopping": ("firestopping of penetrations and joints", "el sellado cortafuego de penetraciones y juntas"),
    "elec_service_equipment": ("the electrical service equipment (meter bank and main)",
                               "el equipo de servicio eléctrico (banco de medidores y principal)"),
    "eifs": ("EIFS", "el EIFS"),
    "roofing": ("roofing", "el techado"),
    "roof_coping": ("the roof coping", "el coping del techo"),
    "windows": ("window installation", "la instalación de ventanas"),
    "exterior_doors": ("the exterior doors", "las puertas exteriores"),
    "stairs_complete": ("the steel stairs (treads, rails)", "las escaleras de acero (peldaños, barandas)"),
    "roof_drains_detention": ("the roof drains and roof detention", "los drenajes y la detención del techo"),
    "hwh_room": ("the water-heater room", "el cuarto de calentadores de agua"),
    "gas_final_test": ("the gas piping final test", "la prueba final de la tubería de gas"),
    "roof_mech": ("the rooftop fans and units", "los extractores y equipos del techo"),
    "board_hang": ("gypsum board", "el sheetrock (tablaroca)"),
    "gate_elec_rough": ("DOB electrical rough inspection", "la inspección eléctrica en bruto del DOB"),
    "gate_sprinkler_hydro": ("sprinkler hydrostatic test", "la prueba hidrostática de rociadores"),
    "gate_tr8_insulation": ("TR8 insulation inspection", "la inspección de aislamiento TR8"),
    "gate_firestop": ("firestopping special inspection", "la inspección especial de cortafuego"),
    "gate_air_barrier_sides": ("air-barrier inspection on the side walls",
                               "la inspección de la barrera de aire en las paredes laterales"),
    "gate_tr8_fenestration": ("TR8 window (fenestration) inspection", "la inspección TR8 de ventanas"),
    "gate_detention_cert": ("roof detention certification", "la certificación de detención del techo"),
    "gate_dob_gas_final": ("DOB gas final inspection", "la inspección final de gas del DOB"),
    "gate_dob_elec_service": ("DOB electrical service inspection", "la inspección del servicio eléctrico del DOB"),
}
#: Gate families whose result no public source carries.
NOT_PUBLIC_AUTHORITIES = ("DOB Electrical", "FDNY", "DEP", "Licensed sprinkler contractor test (NFPA 13R)",
                          "Special inspector (TR1)", "Special inspector (BC 1704.27)", "Progress inspector (TR8)",
                          "Progress inspector (BC 110.3.4)", "Progress inspector")
#: The kind of work (key_of) -> the model's work node (lib/schedule_generator.MODEL_WORK, inverted, plus gates).
MODEL_NODE = {v: k for k, v in G.MODEL_WORK.items() if not k.startswith("gate_")}
MODEL_NODE.update({"gate_elec_rough": "gate_electrical_rough", "gate_sprinkler_hydro": "gate_sprinkler_hydro",
                   "lv_rough": "rough_lowvolt", "sprinkler_rough": "rough_sprinkler", "eifs": "facade_envelope"})
MODEL_LEVEL = {v: k for k, v in G.MODEL_LEVELS.items()}

ZONE_WORDS = {"MEZ": ("the mezzanine", "el mezzanine"), "ROOF": ("the roof", "el techo"),
              "SITE": ("the site", "la obra"), "ENVELOPE": ("the facade", "la fachada")}


def zone_words(zone: Optional[str]) -> Tuple[str, str]:
    z = str(zone or "")
    if z.startswith("L") and z[1:].isdigit():
        return f"Floor {z[1:]}", f"el piso {z[1:]}"
    return ZONE_WORDS.get(z, (z.lower() or "the building", z.lower() or "el edificio"))


def key_of(aid: str) -> str:
    """An activity's kind of work without its floor: elec_rough_L3 ->
    elec_rough. (The generator's `family` is coarser: roof coping and stairs
    share one, and so do three different TR8 inspections.)"""
    return re.sub(r"_(L\d+|MEZ|ROOF)$", "", aid)


def _is_place(zone: Optional[str]) -> bool:
    z = str(zone or "")
    return (z.startswith("L") and z[1:].isdigit()) or z in ("MEZ", "ROOF")


def label(family: str, name: str = "") -> Tuple[str, str, bool]:
    """(English, Spanish, fallback?) for a family. A family with no Spanish
    words of its own is quoted in English inside the Spanish text and flagged."""
    if family in LABELS:
        en, es = LABELS[family]
        return en, es, False
    en = (name or family).strip()
    return en[:1].lower() + en[1:], f"«{en}»", True


# ═══ RE-RUNNING THE SCHEDULE PER BRANCH ═══════════════════════════════════════

class Rescheduler:
    """The schedule, re-run for a change. A change is
    {"state": {activity_id: state_entry}, "assumptions": {id: {scenario: value}},
    "holds": {activity_id: {scenario: working days}}}. A hold delays an
    activity's earliest start (its own delivery constraint, if any, plus the
    hold). Every scenario is run; runs are cached by change."""

    def __init__(self, net: Dict[str, Any], state: Dict[str, Dict[str, Any]], assumptions: Sequence[Dict[str, Any]],
                 data_date: date, scenarios: Sequence[str] = SCENARIOS):
        self.net = net
        self.state = {a["id"]: state.get(a["id"], dict(G.DEFAULT_STATE)) for a in net["activities"]}
        self.assumptions = list(assumptions)
        self.data_date = data_date
        self.scenarios = tuple(scenarios)
        self.by_id = {a["id"]: a for a in net["activities"]}
        self._table = {a["id"]: a for a in self.assumptions}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.runs = 0
        self.base = self.run({})

    def _value(self, aid: str, scn: str) -> float:
        return float(self._table[aid]["values"][scn])

    def run(self, change: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        key = repr(sorted((k, repr(v)) for k, v in (change or {}).items()))
        if key in self._cache:
            return self._cache[key]
        state = dict(self.state)
        for aid, st in ((change or {}).get("state") or {}).items():
            state[aid] = st
        base_net = self.net
        # An answer "done" means the work is at least UNDER WAY. The generator
        # turns an open FS prerequisite into FF only for an in-progress activity
        # (its retained logic), so an attested "done" (which keeps
        # remaining_operator_done of the scope) would wait to START behind
        # predecessors it already finished alongside. Here the same retained
        # logic is applied to what an answer marks done; the base is untouched.
        done_now = {aid for aid, v in ((change or {}).get("state") or {}).items()
                    if v.get("status") == "done" and v.get("evidence") != "verified_public_record"}
        if done_now:
            base_net = {**self.net, "links": [dict(l, type="FF") if l["to"] in done_now and l["type"] == "FS"
                                              and l["kind"] == "prerequisite" else l for l in self.net["links"]]}
        net = base_net
        holds = (change or {}).get("holds") or {}
        out = {}
        for scn in self.scenarios:
            ov = {k: dict(v) for k, v in ((change or {}).get("assumptions") or {}).items()}
            if holds:
                net = {**base_net, "activities": [dict(a) for a in base_net["activities"]]}
                for a in net["activities"]:
                    if a["id"] in holds:
                        hid = f"q_hold_{a['id']}"
                        own = self._value(a["delivery"], scn) if a.get("delivery") else 0.0
                        ov[hid] = {scn: own + float(holds[a["id"]][scn])}
                        a["delivery"] = hid
            r = G.schedule_scenario(net, state, self.assumptions, scn, self.data_date, ov or None)
            self.runs += 1
            out[scn] = {"tco": r["tco"], "tco_wd": r["tco_working_days"], "critical_path": r["critical_path"],
                        "acts": {k: {"es": v["es"], "start": v["start"], "finish": v["finish"],
                                     "float": v["total_float_days"], "critical": v["critical"]}
                                 for k, v in r["activities"].items()}}
        self._cache[key] = out
        return out

    # -- reading the base --

    def window(self, scn: str = "normal") -> List[str]:
        acts = self.base[scn]["acts"]
        return [k for k, v in acts.items() if v["start"] and v["es"] < WINDOW_WD]

    def critical_anywhere(self) -> set:
        return {k for s in self.scenarios for k in self.base[s]["critical_path"]}

    def successors(self, ids: Iterable[str]) -> List[str]:
        ids = set(ids)
        out = []
        for l in self.net["links"]:
            if l["from"] in ids and l["to"] not in ids and l["kind"] in ("prerequisite", "resource"):
                if l["to"] not in out:
                    out.append(l["to"])
        return out

    def first_open_successor(self, ids: Iterable[str]) -> Optional[str]:
        acts = self.base["normal"]["acts"]
        succ = [s for s in self.successors(ids) if acts[s]["start"]]
        return min(succ, key=lambda s: (acts[s]["es"], s)) if succ else None

    def effect(self, change: Dict[str, Any], subject: Sequence[str]) -> Dict[str, Any]:
        """TCO per scenario and its delta; the first open successor's move
        (normal); the activities of the three-week window that moved."""
        run = self.run(change)
        nxt = self.first_open_successor(subject)
        out: Dict[str, Any] = {"tco": {}, "tco_delta_wd": {}}
        for s in self.scenarios:
            out["tco"][s] = run[s]["tco"]
            out["tco_delta_wd"][s] = run[s]["tco_wd"] - self.base[s]["tco_wd"]
        if nxt:
            b, n = self.base["normal"]["acts"][nxt], run["normal"]["acts"][nxt]
            out["next_activity"] = {"id": nxt, "name": self.by_id[nxt]["name"], "base_start": b["start"],
                                    "branch_start": n["start"], "move_wd": (n["es"] - b["es"]) if n["start"] else None,
                                    "in_window": b["es"] < WINDOW_WD or (n["start"] is not None and n["es"] < WINDOW_WD)}
        else:
            out["next_activity"] = None
        moved = []
        for aid in self.window():
            if aid in subject:
                continue             # the asked work itself: its own answer moves it by definition
            b, n = self.base["normal"]["acts"][aid], run["normal"]["acts"][aid]
            d = (n["es"] - b["es"]) if n["start"] else None
            if d:
                moved.append({"id": aid, "base_start": b["start"], "branch_start": n["start"], "move_wd": d})
        out["window_moves"] = sorted(moved, key=lambda m: (-abs(m["move_wd"]), m["id"]))[:5]
        out["critical_path_head_normal"] = run["normal"]["critical_path"][:3]
        return out


# ═══ BUILDING A QUESTION ══════════════════════════════════════════════════════

def evid(source: str, ref: Any, on: Any, what: str, cls: str) -> Dict[str, Any]:
    """One triggering source: where, which, when, what it says, and its class
    (original record / derived summary context / public record / operator
    statement / schedule estimate / model)."""
    return {"source": source, "ref": str(ref), "date": str(on)[:10] if on else None, "what": what, "class": cls}


def branch(key: str, en: str, es: str, *, change: Optional[Dict[str, Any]] = None, claim: Optional[str] = None,
           category: str = "attested", model: str = "", verified_when: Optional[str] = None) -> Dict[str, Any]:
    """An answer and what it does. `category` is what the answer creates in
    the model: "attested" (a person's word) or "dont_know" (nothing; the
    question stays open). Never "verified": only a document or an agency
    record verifies."""
    if category not in ("attested", "dont_know"):
        raise ValueError(f"an answer creates attested or dont_know, never {category!r}")
    return {"key": key, "label_en": en, "label_es": es, "change": change or {}, "claim": claim,
            "category": category, "model_update": model, "verified_when": verified_when}


def dont_know(next_who: str = "") -> Dict[str, Any]:
    return branch("dont_know", "don't know", "no sé", category="dont_know",
                  model="nothing changes: kept as dont_know, never read as a no; the question stays open"
                        + (f" and goes to {next_who} next" if next_who else ""))


def stated(status: str, why: str, man_days: Optional[float] = None) -> Dict[str, Any]:
    """A person's word, as the generator's state: operator_statement."""
    return G.state_entry(status, "operator_statement", f"ATTESTED (a person's answer): {why}", man_days=man_days)


def question(qid: str, *, triggers: Sequence[str], subject: str, aspect: str, place: str, text_en: str, text_es: str,
             answerers: Sequence[str], topic: str, why: str, evidence: Sequence[Dict[str, Any]],
             branches: Sequence[Dict[str, Any]], activities: Sequence[str], gap: str, cost: str,
             reads_as: Optional[str] = None, deadline: Optional[str] = None, decision_weight: float = 0.0,
             decision_why: str = "", model_node: Optional[str] = None, model_level: Optional[str] = None,
             multi_floor: Sequence[str] = (), es_fallback: bool = False) -> Dict[str, Any]:
    if reads_as is not None and reads_as not in CQ.TRIGGERS:
        raise ValueError(f"reads_as must be a confirmation_queue trigger, not {reads_as!r}")
    if not any(b["category"] == "dont_know" for b in branches):
        raise ValueError(f"{qid}: every question carries don't know")
    return {"id": qid, "triggers": list(dict.fromkeys(triggers)), "subject": subject, "aspect": aspect, "place": place,
            "text_en": text_en, "text_es": text_es, "es_fallback": es_fallback, "answerers": list(answerers),
            "topic": topic, "why_it_matters": why, "evidence": list(evidence), "branches": list(branches),
            "activities": list(activities), "gap": gap, "cost": cost, "reads_as": reads_as, "deadline": deadline,
            "decision_weight": decision_weight, "decision_why": decision_why, "model_node": model_node,
            "model_level": model_level, "multi_floor_refs": list(multi_floor)}


# ═══ THE GENERATORS ═══════════════════════════════════════════════════════════

def _state_of(ctx, aid):
    return ctx["sched"].state.get(aid) or G.DEFAULT_STATE


def _measured(st: Dict[str, Any]) -> bool:
    return bool(st.get("man_days"))


def _act_evidence(ctx, aid: str) -> List[Dict[str, Any]]:
    st = _state_of(ctx, aid)
    a = ctx["sched"].by_id[aid]
    b = ctx["sched"].base["normal"]["acts"][aid]
    out = [evid("588_schedule estimate", aid, ctx["today"], f"{a['name']}: state {st['status']} "
                f"({st['evidence']}); {st['basis']}; normal start {b['start']}, float {b['float']} wd"
                + (", CRITICAL" if b["critical"] else ""), "schedule estimate")]
    for ref in (st.get("sources") or [])[:3]:
        out.append(evid("records", ref, None, "source named by the schedule state", "record (see audit class)"))
    return out


def _model_refs(ctx, model_level: Optional[str], node: Optional[str]) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """The model cell's own refs (with each ref's date and class), whether only
    multi-floor statements support it, and those refs."""
    cell = (((ctx["model"].get("levels") or {}).get(model_level) or {}).get("work") or {}).get(node) or {}
    refs = cell.get("refs") or []
    out = []
    for r in refs[-4:]:
        rid = str(r).split(":")[0]
        meta = ctx["records"].get(rid) or {}
        out.append(evid("records", r, meta.get("date"), f"{meta.get('company') or ''} | {meta.get('location') or ''} | "
                        f"{meta.get('text') or ''}".strip(" |"), meta.get("class") or "record"))
    return out, bool(cell.get("shared_only")), [str(r) for r in refs] if cell.get("shared_only") else []


def _work_questions(ctx) -> List[Dict[str, Any]]:
    S = ctx["sched"]
    crit = S.critical_anywhere()
    window = set(S.window())
    out = []
    for a in S.net["activities"]:
        aid = a["id"]
        # Only work that can be under way now: a critical activity that starts
        # months out has an unknown state because it has not started, which is
        # not a gap a person can close today.
        if a["kind"] != "work" or aid not in window:
            continue
        st = _state_of(ctx, aid)
        if (st["status"] == "done" and st["evidence"] != "inferred") or st["evidence"] == "verified_public_record":
            continue
        if st["status"] == "not_started" and st["evidence"] == "inferred":
            continue                     # an inference: _inference_questions asks it, if anyone can check
        unknown = st["status"] == "unknown"
        if st["status"] == "in_progress" and _measured(st) and aid not in crit:
            continue                     # measured man-days off every critical path: nothing to narrow
        fam, zone = key_of(aid), a.get("zone")
        en, es, fb = label(fam, a["name"])
        zen, zes = zone_words(zone)
        node, lvl = MODEL_NODE.get(fam), MODEL_LEVEL.get(zone)
        ev, shared, mf = _model_refs(ctx, lvl, node) if node and lvl else ([], False, [])
        ev = _act_evidence(ctx, aid) + ev
        company = a.get("company")
        trig = ["unknown_state"] + (["multi_floor_statement"] if shared else [])
        on_en = f" on {zen}" if _is_place(zone) else ""
        on_es = f" en {zes}" if _is_place(zone) else ""
        if unknown:
            t_en = f"Has work on {en} started{on_en}? Not started, started, or done?"
            t_es = f"¿Ya empezó el trabajo de {es}{on_es}? ¿No ha empezado, empezó o ya está terminado?".replace(
                " de el ", " del ")
            brs = [branch("not_yet", "not started", "no ha empezado", claim="not_yet",
                          change={"state": {aid: stated("not_started", f"{a['name']}: not started")}},
                          model=f"attested not_yet on {node or aid} at {lvl or zone}: unknown becomes not started "
                                "(the full scope stays, plus mobilization for a trade not yet on site)"),
                   branch("started", "started", "empezó", claim="started",
                          change={"state": {aid: stated("in_progress", f"{a['name']}: started")}},
                          model=f"attested started on {node or aid} at {lvl or zone}"),
                   branch("done", "done", "terminado", claim="done",
                          change={"state": {aid: stated("done", f"{a['name']}: done")}},
                          model=f"attested done on {node or aid} at {lvl or zone} (not verified; the generator leaves "
                                "remaining_operator_done of the scope)"),
                   dont_know(f"{company} (through the PM)" if company else "the PM")]
            reads, gap = CQ.START_PASSED, "unknown"
        else:
            t_en = f"Did {en} finish{on_en}, or is part of it still pending?"
            t_es = f"¿Se terminó {es}{on_es}, o todavía falta una parte?"
            brs = [branch("done", "finished", "terminado", claim="done",
                          change={"state": {aid: stated("done", f"{a['name']}: finished")}},
                          model=f"attested done on {node or aid} at {lvl or zone} (not verified)"),
                   branch("not_yet", "part still pending", "todavía falta", claim="not_yet",
                          model=f"attested not_yet on {node or aid} at {lvl or zone}: confirms in progress; no "
                                "schedule change"),
                   branch("blocked", "blocked: why", "bloqueado: por qué", claim="blocked",
                          change={"holds": {aid: HOLDS["blocked"]["values"]}},
                          model="attested blocked with the reason; the hold is an ASSUMPTION (q_hold_blocked)"),
                   dont_know(f"{company} (through the PM)" if company else "the PM")]
            reads, gap = CQ.DONE_UNBACKED, "in_progress"
        who = ["superintendent", "cp"] + ([f"company:{company}"] if company else [])
        why = (f"{a['name']} is {'on the critical path' if aid in crit else 'in the next three weeks'}"
               f" ({', '.join(s for s in SCENARIOS if aid in S.base[s]['critical_path']) or 'no scenario critical'}); "
               f"its state is {st['status']} ({st['evidence']}).")
        out.append(question(f"work:{aid}", triggers=trig, subject=fam, aspect="state", place=str(zone), text_en=t_en,
                            text_es=t_es, es_fallback=fb, answerers=who, topic="progress", why=why, evidence=ev,
                            branches=brs, activities=[aid], gap=gap, cost="look", reads_as=reads,
                            model_node=node, model_level=lvl, multi_floor=mf))
    return out


def _gate_questions(ctx) -> List[Dict[str, Any]]:
    """One question per gate FAMILY across its floors in the window (one
    request usually covers several floors), asked only when the work it tests
    is on record somewhere."""
    S = ctx["sched"]
    window = set(S.window())
    fams: Dict[str, List[Dict[str, Any]]] = {}
    for a in S.net["activities"]:
        if a["kind"] != "inspection_gate" or a["id"] not in window:
            continue
        if a.get("authority") not in NOT_PUBLIC_AUTHORITIES or _state_of(ctx, a["id"])["status"] == "done":
            continue
        fams.setdefault(key_of(a["id"]), []).append(a)
    out = []
    for fam, gates in sorted(fams.items()):
        ids = [g["id"] for g in gates]
        tested = sorted({w for g in gates for w in (g.get("gate_of") or [])})
        on_record = [w for w in tested if _state_of(ctx, w)["status"] in ("in_progress", "done")]
        en, es, fb = label(fam, gates[0]["name"])
        zones = [g["zone"] for g in gates]
        zen = ", ".join(zone_words(z)[0] for z in zones)
        zes = ", ".join(zone_words(z)[1] for z in zones)
        auth = gates[0].get("authority")
        ev = [evid("588_schedule estimate", g["id"], ctx["today"], f"{g['name']}: normal "
                   f"{S.base['normal']['acts'][g['id']]['start']}, float {S.base['normal']['acts'][g['id']]['float']} wd; "
                   f"{_state_of(ctx, g['id'])['basis']}", "schedule estimate") for g in gates]
        ev.append(evid("public", "DOB NOW / Open Data", ctx["today"], f"no public result for {auth}: "
                       + ctx["not_public"].get(auth, "no public source read"), "public record (absence, read)"))
        if not on_record:
            out.append({"_suppressed": True, "id": f"gate:{fam}", "subject": fam, "place": ",".join(zones),
                        "reason": "premise_not_established",
                        "detail": f"nothing on record installs what the {en} tests ({', '.join(tested)}): asking "
                                  "whether a test passed presumes work no record shows; the work itself is asked "
                                  "instead", "evidence": ev})
            continue
        passed = {gid: stated("done", f"{en} passed (a person's word, not the agency's record)") for gid in ids}
        t_en = f"Has the {en} been requested, booked or passed for {zen}?"
        t_es = f"¿Ya se pidió, se programó o se pasó {es} para {zes}?"
        brs = [branch("passed", "passed", "pasó", claim="done", change={"state": passed},
                      model=f"attested pass on {MODEL_NODE.get(fam, fam)}; STAYS ATTESTED until the {auth} record or "
                            "the inspector's sign-off sheet is on file",
                      verified_when=f"the {auth} result is read from its own record, or the signed sheet is sent"),
               branch("scheduled", "booked: date", "programada: fecha", claim="scheduled",
                      model="attested scheduled item with its date; no state change until a result"),
               branch("not_yet", "not requested yet", "todavía no se pidió", claim="not_yet",
                      change={"state": {gid: stated("not_started", "not requested") for gid in ids}},
                      model="attested not_yet: the inspection lead starts from the request, not from today"),
               dont_know("the PM")]
        out.append(question(f"gate:{fam}", triggers=["inspection_not_public"], subject=fam, aspect="inspection",
                            place=",".join(zones), text_en=t_en, text_es=t_es, es_fallback=fb,
                            answerers=["superintendent", "cp", "pm"], topic="inspection",
                            why=f"No public source carries the {en} ({auth}); boarding waits on it "
                                f"(the work it tests is on record: {', '.join(on_record)}).",
                            evidence=ev, branches=brs, activities=ids, gap="unknown", cost="look",
                            reads_as=CQ.INSP_PASSED, model_node=MODEL_NODE.get(fam),
                            model_level=MODEL_LEVEL.get(zones[0])))
    return out


def _wd_until(ctx, d: date) -> int:
    cal = G.Calendar(ctx["today"])
    return cal.index(d)


def _regulatory_questions(ctx) -> List[Dict[str, Any]]:
    """Permits by expiry. A renewal filed is attested until the DOB record
    shows the new expiry. Permits expiring the same day are one question."""
    S = ctx["sched"]
    today = ctx["today"]
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    out = []
    for a in S.net["activities"]:
        if a["kind"] != "regulatory" or not a.get("deadline"):
            continue
        if _state_of(ctx, a["id"])["status"] == "done":
            continue
        by_day.setdefault(a["deadline"], []).append(a)
    for day, acts in sorted(by_day.items()):
        d = date.fromisoformat(day)
        days = (d - today).days
        ids = [a["id"] for a in acts]
        names = [a["name"] for a in acts]
        ev = [evid("public", p.get("permit"), p.get("as_of"), p.get("says"), "public record")
              for a in acts for p in ctx["permits"].get(a["id"], [])]
        ev += [evid("588_schedule estimate", a["id"], today, f"{a['name']}: deadline {day}", "schedule estimate")
               for a in acts]
        if days > REGULATORY_HORIZON_DAYS:
            out.append({"_suppressed": True, "id": f"permit:{day}", "subject": "permit_renewal", "place": day,
                        "reason": "outside_horizon",
                        "detail": f"{'; '.join(names)}: expires in {days} days, beyond the "
                                  f"{REGULATORY_HORIZON_DAYS}-day horizon; it is asked when inside it",
                        "evidence": ev})
            continue
        lapse_hold = {aid: {s: _wd_until(ctx, d) + HOLDS["permit_lapse"]["values"][s] for s in SCENARIOS}
                      for aid in ids}
        what_en = " and ".join(ctx["permit_words"].get(aid, (aid, aid))[0] for aid in sorted(ids))
        what_es = " y ".join(ctx["permit_words"].get(aid, (aid, aid))[1] for aid in sorted(ids))
        what_en, what_es = what_en[:1].upper() + what_en[1:], what_es[:1].upper() + what_es[1:]
        t_en = f"{what_en}: {'expires' if len(ids) == 1 else 'expire'} {d:%b} {d.day}. Has the renewal been filed?"
        t_es = f"{what_es}: {'vence' if len(ids) == 1 else 'vencen'} el {d.day} de {_MES[d.month]}. ¿Ya se presentó la renovación?"
        weight = 3.0 if days <= 14 else 2.0 if days <= 30 else 1.0
        brs = [branch("done", "filed", "presentada", claim="done",
                      change={"state": {aid: stated("done", "renewal filed") for aid in ids}},
                      model="attested renewal; VERIFIED only when the DOB permit record shows the new expiry",
                      verified_when="the DOB NOW permit record (rbx6-tga4 / the portal) shows a later expiry"),
               branch("not_yet", "not filed yet", "todavía no", claim="not_yet",
                      change={"holds": lapse_hold},
                      model="attested not_yet; the lapse branch ASSUMES renewal only after expiry "
                            "(q_hold_permit_lapse) and re-runs what waits on the permit"),
               dont_know("the admin")]
        dependents = S.successors(ids)
        out.append(question(f"permit:{day}", triggers=["regulatory_deadline"], subject="permit_renewal",
                            aspect="permit", place=day, text_en=t_en, text_es=t_es,
                            answerers=["superintendent", "pm", "admin"], topic="permit",
                            why=f"Expires in {days} days. Work that waits on it in the network: "
                                f"{', '.join(dependents) or 'none modelled'}." + ctx["permit_why"].get(day, ""),
                            evidence=ev, branches=brs, activities=ids, gap="unknown", cost="office",
                            reads_as=CQ.DONE_UNBACKED, deadline=day, decision_weight=weight,
                            decision_why=f"permit deadline in {days} days"))
    return out


_MES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}


def _utility_questions(ctx) -> List[Dict[str, Any]]:
    S = ctx["sched"]
    out = []
    tab = {a["id"]: a for a in S.assumptions}
    for u in ctx.get("utilities") or ():
        aid, key = u["activity"], u["lead"]
        if aid not in S.by_id or key not in tab or _state_of(ctx, aid)["status"] == "done":
            continue
        v = tab[key]["values"]
        brs = [branch("done", f"filed, moving ({v['fast']} wd lead)", f"presentada y avanzando ({v['fast']} días hábiles)",
                      claim="done", change={"assumptions": {key: {s: v["fast"] for s in SCENARIOS}}},
                      model=f"attested: application filed; lead taken at the fast value {v['fast']} wd (assumption)"),
               branch("not_yet", f"not filed ({v['conservative']} wd lead)",
                      f"no se ha presentado ({v['conservative']} días hábiles)", claim="not_yet",
                      change={"assumptions": {key: {s: v["conservative"] for s in SCENARIOS}}},
                      model=f"attested not filed; lead taken at the conservative value {v['conservative']} wd"),
               dont_know("the admin")]
        out.append(question(f"utility:{aid}", triggers=["utility_status"], subject=aid, aspect="application",
                            place="SITE", text_en=u["text_en"], text_es=u["text_es"], answerers=["pm", "admin"],
                            topic="agency_record", why=u["why"], evidence=u["evidence"], branches=brs,
                            activities=[aid], gap="unknown", cost="office", reads_as=CQ.DONE_UNBACKED))
    return out


def _lever_questions(ctx) -> List[Dict[str, Any]]:
    """A lever that saves time ALONE is a commitment only the PM can get."""
    S = ctx["sched"]
    out = []
    table = {a["id"] for a in S.assumptions}
    for lv in ctx.get("levers") or ():
        ov = {k: v for k, v in lv["overrides"].items() if k in table}
        if not ov:
            continue
        tab = {a["id"]: a for a in S.assumptions}
        full = {}
        for k, v in ov.items():
            if isinstance(v["normal"], dict):
                continue             # a weather profile: not a commitment a person answers
            own = tab[k]["values"]
            pick = min if tab[k].get("faster") == "lower" else max
            # the lever's value in every scenario, never slower than the scenario's own
            full[k] = {s: pick(own[s], v["normal"]) for s in SCENARIOS}
        if not full:
            continue
        brs = [branch("done", lv["yes_en"], lv["yes_es"], claim="done", change={"assumptions": full},
                      model="attested commitment (the PM's word); the crew is MEASURED again from check-ins once on site"),
               branch("not_yet", lv["no_en"], lv["no_es"], claim="not_yet",
                      model="attested: no change to the crew; the schedule stays as measured"),
               dont_know("the admin")]
        out.append(question(f"lever:{lv['id']}", triggers=["acceleration_lever"], subject=lv["subject"],
                            aspect="crew", place=lv.get("place", "ENVELOPE"), text_en=lv["text_en"],
                            text_es=lv["text_es"], answerers=["pm", "admin"], topic="subcontract", why=lv["why"],
                            evidence=lv["evidence"], branches=brs, activities=lv["activities"], gap="unknown",
                            cost="third_party", reads_as=None))
    return out


def _given_questions(ctx) -> List[Dict[str, Any]]:
    """Questions whose words the caller writes (a contradiction, a public
    conflict, an inference to check, a statement gap) but whose branches,
    schedule effects, value and permission this module computes. Each is
    given as a `question()` dict (or a suppressed entry) by the caller."""
    return [dict(q) for q in ctx.get("given") or ()]


# ═══ TRIGGERS THAT ATTACH TO A QUESTION ═══════════════════════════════════════

def stale_subs(ctx) -> Dict[str, Dict[str, Any]]:
    """{company: {"last_original", "days", "open_activities"}} for every roster
    sub with no original record within STALE_DAYS."""
    out = {}
    for comp, last in (ctx.get("sub_last_original") or {}).items():
        days = (ctx["today"] - last).days if last else None
        if days is not None and days <= STALE_DAYS:
            continue
        acts = [a["id"] for a in ctx["sched"].net["activities"] if a.get("company") == comp
                and _state_of(ctx, a["id"])["status"] != "done"]
        out[comp] = {"last_original": last.isoformat() if last else None, "days": days, "open_activities": acts}
    return out


def _attach_stale(ctx, qs: List[Dict[str, Any]], suppressed: List[Dict[str, Any]]) -> None:
    stale = stale_subs(ctx)
    used = set()
    for q in qs:
        for aid in q["activities"]:
            comp = ctx["sched"].by_id.get(aid, {}).get("company")
            if comp in stale:
                s = stale[comp]
                q["triggers"].append("stale_sub")
                q["evidence"].append(evid("model coverage", comp, s["last_original"],
                                          f"{comp}: no original record "
                                          + (f"for {s['days']} days" if s["days"] is not None else "at all"),
                                          "model"))
                used.add(comp)
        q["triggers"] = list(dict.fromkeys(q["triggers"]))
    for comp, s in sorted(stale.items()):
        if comp in used:
            continue
        window = set(ctx["sched"].window()) | ctx["sched"].critical_anywhere()
        open_near = [a for a in s["open_activities"] if a in window]
        why = ("no open activity of this sub is in the network" if not s["open_activities"] else
               f"its open work ({', '.join(s['open_activities'][:4])}) is outside the three-week window and off "
               "every critical path" if not open_near else "its open work is asked under another subject")
        age = ("no original record at all" if s["days"] is None
               else f"{s['days']} days since its last original record")
        suppressed.append({"id": f"stale:{comp}", "subject": comp, "place": "SITE", "reason": "no_decision",
                           "detail": f"stale sub ({age}), but {why}",
                           "evidence": [evid("model coverage", comp, s["last_original"], "sub coverage", "model")]})


# ═══ EVALUATION ═══════════════════════════════════════════════════════════════

def _urgency(ctx, q: Dict[str, Any]) -> Tuple[float, Optional[str], Optional[int]]:
    S = ctx["sched"]
    cands = []
    if q.get("deadline"):
        cands.append(date.fromisoformat(q["deadline"]))
    nxt = S.first_open_successor(q["activities"])
    if nxt and S.base["normal"]["acts"][nxt]["start"]:
        cands.append(date.fromisoformat(S.base["normal"]["acts"][nxt]["start"]))
    crit = S.critical_anywhere()
    for aid in q["activities"]:
        st = S.base["normal"]["acts"].get(aid, {}).get("start")
        # needed when it starts: work of unknown state, and any critical work (under way now, or not)
        if st and (_state_of(ctx, aid)["status"] == "unknown" or aid in crit):
            cands.append(date.fromisoformat(st))
    if not cands:
        return 1.0, None, None
    need = min(cands)
    days = max(0, (need - ctx["today"]).days)
    return round(1 + max(0, WINDOW_DAYS - days) / WINDOW_DAYS, 3), need.isoformat(), days


def evaluate(ctx, q: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run the schedule for every branch; the value with its terms."""
    S = ctx["sched"]
    for b in q["branches"]:
        b["schedule_effect"] = S.effect(b["change"], q["activities"]) if b["category"] != "dont_know" else {
            "tco": {s: S.base[s]["tco"] for s in SCENARIOS}, "tco_delta_wd": {s: 0 for s in SCENARIOS},
            "next_activity": None, "window_moves": [], "note": "no change: don't know is not an answer"}
    effs = [b["schedule_effect"] for b in q["branches"]]
    t_norm = max(abs(e["tco_delta_wd"]["normal"]) for e in effs)
    t_side = max(max(abs(e["tco_delta_wd"]["fast"]), abs(e["tco_delta_wd"]["conservative"])) for e in effs)
    T = t_norm + 0.5 * t_side
    nmove = max([abs(e["next_activity"]["move_wd"] or 0) for e in effs
                 if e.get("next_activity") and e["next_activity"]["in_window"]] or [0])
    N = 0.25 * min(20, nmove)
    D = float(q.get("decision_weight") or 0.0)
    U, need, days = _urgency(ctx, q)
    Gp, C = GAP[q["gap"]], COST[q["cost"]]
    q["urgency"] = {"needed_by": need, "days": days, "factor": U}
    q["downstream"] = [{"id": s, "name": S.by_id[s]["name"], "start": S.base["normal"]["acts"][s]["start"]}
                       for s in S.successors(q["activities"])[:6]]
    q["window_moves_any_branch"] = any(e.get("window_moves") for e in effs)
    q["value"] = {"score": round((T + N + D) * U * Gp * C, 2), "formula": VALUE_FORMULA,
                  "terms": {"T": round(T, 2), "T_normal": t_norm, "T_other": t_side, "N": round(N, 2), "D": D,
                            "U": U, "G": Gp, "C": C}}
    return q


def changes_a_decision(q: Dict[str, Any]) -> bool:
    t = q["value"]["terms"]
    return bool(t["T"] or t["N"] or t["D"] or q.get("window_moves_any_branch"))


def floor_matters(q: Dict[str, Any]) -> bool:
    """A floor matters when some branch for THAT floor moves the finish in some
    scenario."""
    return bool(q["value"]["terms"]["T"])


# ═══ SUPPRESSION, PERMISSION, CAP ═════════════════════════════════════════════

def answered_predecessors(ctx) -> List[Dict[str, Any]]:
    """What a question about the three-week window would otherwise re-ask:
    every predecessor of a window activity that a VERIFIED public record
    already settles, with that record. An inference never settles one."""
    S = ctx["sched"]
    window = set(S.window())
    seen, out = set(), []
    for l in S.net["links"]:
        if l["to"] not in window or l["from"] in seen:
            continue
        st = _state_of(ctx, l["from"])
        # Only a verified public record answers a question. An inference that
        # work is done is a reason to ASK, never to suppress the question.
        if st["status"] != "done" or st["evidence"] != "verified_public_record":
            continue
        seen.add(l["from"])
        a = S.by_id[l["from"]]
        out.append({"id": f"work:{a['id']}", "subject": key_of(a["id"]), "place": str(a.get("zone")),
                    "reason": "answered_by_records",
                    "detail": f"{a['name']}: done ({st['evidence']}): {st['basis']}",
                    "evidence": [evid("588_schedule estimate", a["id"], ctx["today"], st["basis"],
                                      "public record" if st["evidence"] == "verified_public_record" else "inference")]})
    return out


def permitted(role_or_company: str, topic: str) -> Tuple[Optional[str], Optional[str]]:
    """(recipient role, refusal). A company answerer is relayed by the PM."""
    tool, args = TOPIC_TOOLS[topic]
    if role_or_company.startswith("company:"):
        ref = dm_roles.tool_refusal(SUB_RELAY, tool, args)
        return (SUB_RELAY, None) if ref is None else (None, ref)
    ref = dm_roles.tool_refusal(role_or_company, tool, args)
    return (role_or_company, None) if ref is None else (None, ref)


def _answered(ctx, q: Dict[str, Any]) -> Optional[str]:
    """An earlier answer on the same subject and place, inside the repeat
    window (confirmation_queue facts: a fresh "not yet" counts, don't know
    never does)."""
    fs = CQ.facts([a for a in ctx.get("answers") or () if a.get("node") == q.get("model_node")
                   and (not q.get("model_level") or q["model_level"] in (a.get("levels") or []))], ctx["today"])
    if fs:
        return f"answered {fs[0].get('on')} by {fs[0].get('by') or 'a person'}: {fs[0].get('claim')}"
    return None


def plan(ctx, qs: List[Dict[str, Any]], suppressed: List[Dict[str, Any]], people: Sequence[Dict[str, Any]]):
    """Rank by value; place each on the first permitted person with room."""
    roles = [str(p.get("role")) for p in people]
    asked = {(h.get("thing")) for h in ctx.get("history") or ()
             if h.get("day") and (ctx["today"] - date.fromisoformat(str(h["day"])[:10])).days < REPEAT_DAYS}
    load: Dict[str, List[Dict[str, Any]]] = {r: [] for r in roles}
    shadow_roles = set(CQ.unmessageable_roles())
    for q in sorted(qs, key=lambda q: (-q["value"]["score"], q["id"])):
        if q["id"] in asked:
            suppressed.append(_sup(q, "asked_recently", f"asked within {REPEAT_DAYS} days"))
            continue
        refused, room_full, placed = [], [], False
        for who in q["answerers"]:
            rcpt, ref = permitted(who, q["topic"])
            if rcpt is None:
                refused.append({"answerer": who, "refusal": ref})
                continue
            if rcpt not in load:
                continue
            if len(load[rcpt]) >= MAX_PER_PERSON:
                room_full.append(rcpt)
                continue
            q["answerer"] = who.replace("company:", "") + (" (subcontractor, asked through the PM)"
                                                           if who.startswith("company:") else "")
            q["recipient"] = rcpt
            q["refused_roles"] = refused
            q["delivery"] = ("SHADOW: dm_roles says a field role is never messaged first, so live delivery is "
                             "refused (confirmation_queue.live_refused); generated for evaluation only"
                             if rcpt in shadow_roles else "SHADOW: evaluation only; nothing is sent")
            load[rcpt].append(q)
            placed = True
            break
        if not placed:
            if room_full:
                suppressed.append(_sup(q, "daily_cap", f"{', '.join(dict.fromkeys(room_full))} already "
                                                       f"{MAX_PER_PERSON} today; queued for the next day", refused))
            else:
                suppressed.append(_sup(q, "not_permitted", "no permitted recipient: "
                                       + "; ".join(f"{r['answerer']}: {r['refusal']}" for r in refused), refused))
    return load


def _sup(q: Dict[str, Any], reason: str, detail: str, refused: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    if reason not in SUPPRESSION_REASONS:
        raise ValueError(reason)
    out = {"id": q["id"], "subject": q.get("subject"), "place": q.get("place"), "reason": reason, "detail": detail,
           "text_en": q.get("text_en"), "evidence": q.get("evidence", [])[:3]}
    if "value" in q:
        out["value"] = q["value"]["score"]
    if refused:
        out["refused_roles"] = list(refused)
    return out


def generate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Today's questions per person, the suppressed list with reasons, and
    every branch's schedule effect.

    ctx: {"today": date, "sched": Rescheduler, "model": current_state dict,
    "records": {id: {date, company, location, text, class}}, "people": [{role}],
    "permits": {activity_id: [{permit, says, as_of}]}, "permit_words":
    {activity_id: (en, es)}, "permit_why": {deadline: str}, "not_public":
    {authority: why}, "utilities": [...], "levers": [...], "given": [...],
    "sub_last_original": {company: date|None}, "answered_by_records": [...],
    "answers": [evidence items], "history": [{thing, day}]}."""
    generated = (_work_questions(ctx) + _gate_questions(ctx) + _regulatory_questions(ctx) + _utility_questions(ctx)
                 + _lever_questions(ctx))
    given = _given_questions(ctx)
    # A question the caller words replaces the generated one with the same id
    # (same subject, aspect and place), keeping the generated triggers.
    by_id = {q["id"]: q for q in generated}
    for g in given:
        old = by_id.get(g["id"])
        if old and not old.get("_suppressed") and not g.get("_suppressed"):
            g["triggers"] = list(dict.fromkeys(list(old["triggers"]) + list(g["triggers"])))
            g["evidence"] = list(old["evidence"]) + [e for e in g["evidence"] if e not in old["evidence"]]
        by_id[g["id"]] = g
    raw = list(by_id.values())
    suppressed = [dict(s) for s in ctx.get("answered_by_records") or ()] + answered_predecessors(ctx)
    qs = []
    for q in raw:
        if q.get("_suppressed"):
            suppressed.append({k: v for k, v in q.items() if k != "_suppressed"})
        else:
            qs.append(q)
    # never what a person already answered
    keep = []
    for q in qs:
        a = _answered(ctx, q)
        if a:
            suppressed.append(_sup(q, "answered_by_records", a))
        else:
            keep.append(q)
    qs = keep
    _attach_stale(ctx, qs, suppressed)
    qs = [evaluate(ctx, q) for q in qs]
    # redundancy: same subject, aspect and place
    best: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for q in sorted(qs, key=lambda q: (-q["value"]["score"], q["id"])):
        k = (q["subject"], q["aspect"], q["place"])
        if k in best:
            suppressed.append(_sup(q, "redundant", f"same subject, aspect and place as {best[k]['id']}"))
        else:
            best[k] = q
    qs = list(best.values())
    keep = []
    for q in qs:
        if q["multi_floor_refs"] and not floor_matters(q):
            suppressed.append(_sup(q, "floor_does_not_matter",
                                   f"only multi-floor statements place this work here "
                                   f"({', '.join(q['multi_floor_refs'][:3])}); no branch for this floor moves the "
                                   "finish in any scenario, so narrowing the floor changes nothing"))
        elif not changes_a_decision(q):
            suppressed.append(_sup(q, "no_decision", "every branch re-runs to the same TCO in every scenario, moves "
                                                     "nothing in the next three weeks, and no deadline or record "
                                                     "decision rides on it"))
        else:
            keep.append(q)
    people = ctx.get("people") or [{"role": r} for r in ROLE_SLOTS]
    load = plan(ctx, keep, suppressed, people)
    S = ctx["sched"]
    by_person = {r: [_public(q) for q in items] for r, items in load.items()}
    return {
        "engine": ENGINE, "today": ctx["today"].isoformat(), "mode": "SHADOW: evaluation only, nothing is sent",
        "value_formula": VALUE_FORMULA, "cap_per_person": MAX_PER_PERSON,
        "base_schedule": {s: {"tco": S.base[s]["tco"], "tco_working_days": S.base[s]["tco_wd"],
                              "critical_path_head": S.base[s]["critical_path"][:4]} for s in SCENARIOS},
        "assumed_holds": [HOLDS[k] for k in HOLDS],
        "by_person": by_person,
        "suppressed": sorted(suppressed, key=lambda s: (SUPPRESSION_REASONS.index(s["reason"]), str(s["id"]))),
        "counts": {"candidates": len(raw) + len(ctx.get("answered_by_records") or ()),
                   "asked": sum(len(v) for v in by_person.values()), "suppressed": len(suppressed),
                   "by_reason": _count(s["reason"] for s in suppressed), "schedule_runs": S.runs},
        #: the asked questions WITH their branch changes, for a caller that re-runs an answer; not for output.
        "_asked": [q for items in load.values() for q in items],
    }


def _count(xs: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def _public(q: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in q.items() if k not in ("window_moves_any_branch",)}
    out["branches"] = [{k: v for k, v in b.items() if k != "change"} | {"schedule_change": _change_words(b["change"])}
                       for b in q["branches"]]
    return out


def _change_words(change: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if change.get("state"):
        out["state"] = {k: f"{v['status']} ({v['evidence']})" for k, v in change["state"].items()}
    if change.get("assumptions"):
        out["assumptions"] = change["assumptions"]
    if change.get("holds"):
        out["holds_wd"] = change["holds"]
    return out


# ═══ ANSWERING (the chain) ════════════════════════════════════════════════════

def read_reply(q: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    """A reply to ONE question, read by confirmation_queue's fixed rules
    (English and Spanish). None: not one closed answer, left for the DM brain."""
    if not q.get("reads_as"):
        return None
    got = CQ.parse_reply(text, [{"trigger": q["reads_as"]}])
    return got["answers"][0] if got["answers"] else None


def branch_for(q: Dict[str, Any], answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The branch an answer takes. A stated percent takes the nearest
    percent_<n> branch when the question has them, else "not yet"."""
    if answer["answer"] == "percent":
        pct = [b for b in q["branches"] if b["key"].startswith("percent_")]
        if pct:
            return min(pct, key=lambda b: abs(int(b["key"].split("_")[1]) - float(answer.get("percent") or 0)))
    key = {"partial": "not_yet", "percent": "not_yet"}.get(answer["answer"], answer["answer"])
    return next((b for b in q["branches"] if b["key"] == key), None)


def answer_evidence(q: Dict[str, Any], answer: Dict[str, Any], *, answer_id: str, person: str, on: date,
                    project_id: Any) -> Optional[Dict[str, Any]]:
    """The answer as evidence: confirmation_queue.answer_item, so it is
    ATTESTED (or dont_know), never verified. An inspection answer goes through
    confirmation_queue.inspection_check first."""
    cand = {"question": q["text_en"], "project_id": str(project_id), "node": q.get("model_node"),
            "level": q.get("model_level")}
    check = CQ.inspection_check(answer) if q.get("reads_as") in CQ.INSPECTION_TRIGGERS else None
    return CQ.answer_item(cand, answer, answer_id=answer_id, person=person, on=on, check=check)
