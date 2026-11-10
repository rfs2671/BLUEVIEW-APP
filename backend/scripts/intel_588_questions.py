"""Today's site questions for 588 Thomas S. Boyland St, from local data, and the
chain demonstration. EVALUATION ONLY: nothing is sent.

    PYTHONUTF8=1 python backend/scripts/intel_588_questions.py [DATA_DIR]

DATA_DIR (default: env INTEL588_DATA, else C:/Users/asddd/bv-worktrees/intel588-data)
holds the records, the drawings' building.json, the public records, the audited
model (model/588_model.json) and the schedule inputs. Writes
DATA_DIR/questions/588_questions.json and README.md. Real data never enters
git: this script reads and writes only DATA_DIR. No database, no network, no
paid API. lib/site_questions does the work; this file is the 588 adapter: it
loads the files, words the questions only a person can word (a contradiction,
a public conflict, a statement gap) and runs the chain.

THE CHAIN, per question and per answer branch (`chain`):
  plans (building.json) + logs + photos (original records) -> location
  (intel_records.place) -> activity (intel_records.classify) -> work progress
  (the model cell, project_timeline.as_of) -> dependency state (the schedule
  state and links) -> schedule (schedule_generator) -> question
  (site_questions) -> a SIMULATED answer -> confirmation_queue.parse_reply ->
  the attested evidence item (confirmation_queue.answer_item) -> the model
  re-built WITH it (project_timeline.as_of) -> its state laid over the
  schedule (schedule_generator.state_from_model) plus what the model does not
  carry -> the schedule re-run, and the delta.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import construction_inference as CI  # noqa: E402
from lib import intel_records as R  # noqa: E402
from lib import project_timeline as T  # noqa: E402
from lib import schedule_generator as G  # noqa: E402
from lib import site_questions as SQ  # noqa: E402

TODAY = date(2026, 11, 10)
PID = "6a5f63bc147407d3261df2c7"
DEFAULT_DATA = "C:/Users/asddd/bv-worktrees/intel588-data"


# ── LOADING ───────────────────────────────────────────────────────────────

def load(data: Path) -> Dict[str, Any]:
    rd = lambda p: json.loads((data / p).read_text(encoding="utf-8"))  # noqa: E731
    with open(data / "records" / "588_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    audit = {}
    af = data / "records" / "audit_flags.jsonl"
    if af.exists():
        with open(af, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    a = json.loads(line)
                    audit[str(a["rec_id"])] = a
    return {"records": records, "audit": audit, "building": rd("drawings/building.json"),
            "timeline": rd("public/588_public_timeline.json"), "dob_now": rd("public/dob_now_inspections_588.json"),
            "reconciliation": rd("public/status_reconciliation.json"), "model": rd("model/588_model.json")}


def records_index(src: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for r in src["records"]:
        a = src["audit"].get(str(r["id"]))
        out[str(r["id"])] = {"date": r.get("date"), "company": r.get("company"), "location": r.get("location_text"),
                             "text": (r.get("description") or r.get("quote") or "")[:140].replace("\n", " "),
                             "class": R.audit_class(a)}
    return out


def schedule_base(src: Dict[str, Any]) -> Dict[str, Any]:
    p = G.prepare(src["building"], src["records"], src["dob_now"], src["timeline"],
                  audit=list(src["audit"].values()) or None)
    st, notes = G.state_from_model(src["model"], p["net"], p["provisional"])
    return {"prepared": p, "state": st, "notes": notes}


def _rec(ix, rid: str, source: str = "records") -> Dict[str, Any]:
    m = ix.get(rid.split(":")[0]) or {}
    return SQ.evid(source, rid, m.get("date"), " | ".join(str(x) for x in (m.get("company"), m.get("location"),
                                                                        m.get("text")) if x), m.get("class", "record"))


def _pub(row: Dict[str, Any]) -> Dict[str, Any]:
    return SQ.evid("public", row.get("job_or_permit_no"), row.get("date"),
                   f"{row.get('work_type')}: {row.get('status_text_verbatim')} ({row.get('source_dataset')}, "
                   f"{row.get('raw_file')} row {row.get('raw_row_index')})", "public record")


def _timeline(src, permit_no: str) -> List[Dict[str, Any]]:
    return [_pub(r) for r in src["timeline"] if str(r.get("job_or_permit_no") or "") == permit_no]


# ── THE 588 ADAPTER: what only a person can word ──────────────────────────

def permits(src) -> Dict[str, List[Dict[str, Any]]]:
    rec = {i["id"]: i for i in src["reconciliation"]["items"] if "id" in i}
    shed = rec.get("sidewalk_shed_B01409772_I1", {})
    plum = rec.get("plumbing_B23173802-S5_vs_B01141294-S5", {})
    return {
        "renew_permit_shed": [{"permit": "B01409772-I1-SH", "as_of": "2026-11-10",
                               "says": (shed.get("resolution") or "") + " Open: " + "; ".join(shed.get("unresolved") or [])}],
        "renew_permit_plumbing": [{"permit": "B01141294-S5-PL", "as_of": "2026-11-10",
                                   "says": (plum.get("sources") or [{}])[0].get("says", "")}],
        "renew_permit_sprinkler": [{"permit": "B01141294-S7-EW-SP", "as_of": "2026-07-15",
                                    "says": "Sprinklers: Permit Issued 2026-07-15 (rbx6-tga4); expiry 2026-12-03 per the "
                                            "schedule's public permit record"}],
        "renew_permit_scaffold": [{"permit": "B01467559-I1-SF", "as_of": "2026-09-30",
                                   "says": "Supported Scaffold: Permit Issued 2026-09-30 (rbx6-tga4), expires 2026-12-22"}],
    }


PERMIT_WORDS = {
    "renew_permit_shed": ("Sidewalk shed permit B01409772",
                          "El permiso del sidewalk shed (protección de acera) B01409772"),
    "renew_permit_plumbing": ("Plumbing permit B01141294-S5 (Quality Piping)",
                              "El permiso de plomería B01141294-S5 (Quality Piping)"),
    "renew_permit_sprinkler": ("sprinkler permit B01141294-S7", "el permiso de rociadores B01141294-S7"),
    "renew_permit_scaffold": ("Supported scaffold permit B01467559", "El permiso del andamio B01467559"),
    "renew_permits_gc": ("GC, structural and mechanical permits", "Los permisos de GC, estructura y mecánica"),
}
PERMIT_WHY = {
    "2026-11-22": " The shed stays until the facade is finished (scaffold_shed_removal follows the EIFS, 2027-04); the "
                  "network models no consequence of a lapse (an unpermitted shed is a violation; this shed already drew "
                  "ECB 39558662P on 2026-09-02).",
    "2026-12-03": " S5 carries the Nov 5 DOB rough passes; the gas final, detention certification and plumbing final are "
                  "inspected under it. 24 Seven holds a second plumbing permit (B23173802-S5, expires 2027-05-01).",
}
#: What a lapse COSTS beyond the stoppage the schedule models (the stoppage itself is re-run).
PERMIT_CONSEQUENCE = {
    "2026-11-22": "AC 28-105: no work from an unpermitted sidewalk shed; the shed protects the public sidewalk under "
                  "the facade work (public safety); an unpermitted shed is an ECB violation and this shed already drew "
                  "ECB 39558662P on 2026-09-02",
    "2026-12-03": "no DOB inspection is booked under an expired permit: the gas final, the roof detention "
                  "certification and the plumbing and sprinkler finals wait for reinstatement",
    "2026-12-22": "AC 28-105: no work from an unpermitted supported scaffold; the EIFS is applied from it",
}
NOT_PUBLIC = {
    "DOB Electrical": "electrical inspections are in DOB NOW: Inspections Plus, which was not read (public README section 3)",
    "FDNY": "no public FDNY fire-alarm dataset; no fire-alarm filing exists in DOB",
    "DEP": "DEP tap / sewer-connection inspection results are not public (only CONN permits)",
    "Licensed sprinkler contractor test (NFPA 13R)": "a contractor's test; no public result",
    "Progress inspector (TR8)": "TR8 progress inspections are not public",
    "Special inspector (TR1)": "TR1 special inspections are not public",
    "Special inspector (BC 1704.27)": "special inspections are not public",
    "Progress inspector (BC 110.3.4)": "progress inspections are not public",
}


def utilities(src) -> List[Dict[str, Any]]:
    return [
        {"activity": "coned_lead", "lead": "lead_coned",
         "text_en": "Has the Con Ed service application (load letter) been filed for the electrical service yet?",
         "text_es": "¿Ya se presentó la solicitud de servicio a Con Ed (load letter) para el servicio eléctrico?",
         "why": "No record shows a Con Ed application; Con Ed must energize before the electrical final. The lead is an "
                "assumption of 20-70 working days.",
         "evidence": [SQ.evid("public", "B01445590-I1", "2026-08-13", "general wiring permit issued (Power Direct); no "
                              "Con Ed case is house-keyed in the public pull", "public record")]},
        {"activity": "ng_service_lead", "lead": "lead_ng_service",
         "text_en": "Has the National Grid gas service request been filed? (The Nov 6 street permit is a gas leak repair.)",
         "text_es": "¿Ya se pidió el servicio de gas a National Grid? (El permiso del 6 de nov. es una reparación de fuga.)",
         "why": "The gas meter, water heaters and DHW start-up wait on it; the lead is an assumption of 15-60 wd.",
         "evidence": _timeline(src, "B012026310E18")},
    ]


def _crew_words(sched: SQ.Rescheduler) -> Dict[str, Any]:
    cid = G._eifs_crew(sched.net)
    tab = {x["id"]: x for x in sched.assumptions}
    a = tab.get(cid) or {}
    return {"id": cid, "normal": (a.get("values") or {}).get("normal"), "tag": a.get("tag"), "basis": a.get("basis")}


def levers(src, sched: SQ.Rescheduler) -> List[Dict[str, Any]]:
    by = {lv["id"]: lv for lv in G.LEVERS}
    ix = records_index(src)
    roles = SQ.facade_roles(sched.net)
    cw = _crew_words(sched)
    n = cw["normal"]
    return [
        dict(by["eifs_staff_and_enclose"], subject="eifs", place="ENVELOPE",
             activities=roles["side"] + roles["front_rear"] + roles["bulkhead"],
             text_en=f"The EIFS crew is taken at {n:g} applicators a day ({cw['tag']}), and EIFS now sets the finish "
                     "date. Can J&P put 5 applicators on it from next week?",
             text_es=f"El equipo de EIFS se toma en {n:g} aplicadores por día ({cw['tag']}) y el EIFS ahora define la "
                     "fecha de terminación. ¿Puede J&P poner 5 aplicadores desde la próxima semana?",
             yes_en="yes, about 5", yes_es="sí, unos 5", no_en="no, same crew", no_es="no, el mismo equipo",
             why=f"EIFS by elevation ({', '.join(roles['side'] + roles['front_rear'] + roles['bulkhead'])}) is the "
                 f"normal critical path; crew {cw['id']} = {n:g}/day ({cw['tag']}: {cw['basis']}). A crew commitment is "
                 "the PM's (subcontract).",
             evidence=[_rec(ix, "R0359"), SQ.evid("588_schedule estimate", cw["id"], "2026-11-09",
                                                  f"{cw['tag']}: {cw['basis']}", "schedule estimate")]),
        dict(by["inspections_prebooked"], subject="inspections", place="SITE",
             activities=["gate_dob_elec_final", "gate_fdny_fa", "gate_tco"],
             text_en="Will we book each DOB and FDNY inspection a week ahead, and is the TR1/TR8 agency on standing "
                     "visits?",
             text_es="¿Vamos a pedir cada inspección del DOB y del FDNY con una semana de anticipación, y la agencia "
                     "TR1/TR8 tiene visitas fijas?",
             yes_en="yes", yes_es="sí", no_en="no, as requested", no_es="no, según se pidan",
             why="The DOB electrical final, TR8 final, final progress inspection and TCO sit on the critical path "
                 "behind the EIFS; their leads are assumptions (measured DOB request-to-result: 7 wd, n=1).",
             evidence=[SQ.evid("public", "7755632", "2026-11-05", "DOB plumbing inspection: requested 10-27, resulted "
                               "11-05 (7 working days)", "public record")]),
    ]


def _qty_rate(sched: SQ.Rescheduler, aid: str) -> tuple:
    """(effective SF, normal rate) for a production activity, as the generator computes them."""
    A, _t = G._resolver(sched.assumptions)
    a = sched.by_id[aid]
    eff, _rem, _how = G._effort(a, G.state_entry("not_started", "no_record", "probe"), "normal", A)
    rate = float(A(a["rate"], "normal"))
    crew = G.crew_used(a, "normal", A) or 1.0
    return eff * crew * rate, rate


def side_wall_branches(sched: SQ.Rescheduler, side: List[str]) -> List[Dict[str, Any]]:
    """Branches that touch the SIDE-WALL activities only, found by role. The
    model has one facade node, so the answer is carried as attested on these
    activities and never on the model node (it would mark front/rear too)."""
    out = []
    for pct, en, es in ((25, "under a quarter", "menos de una cuarta parte"), (50, "about half", "más o menos la mitad"),
                        (75, "most of it (3/4)", "la mayor parte (3/4)")):
        st, parts = {}, []
        for aid in side:
            qty, rate = _qty_rate(sched, aid)
            md = round(pct / 100.0 * qty / rate, 1)
            st[aid] = SQ.stated("in_progress", f"side-wall EIFS about {pct}% done", man_days=md)
            parts.append(f"{aid}: {md} man-days of {qty:.0f} SF at {rate:g} SF/worker-day")
        out.append(SQ.branch(f"percent_{pct}", en, es, claim="in_progress", change={"state": st},
                             model=f"attested in_progress, stated {pct}%, carried on {', '.join(side)} ONLY (not the "
                                   "model's single facade node); the schedule takes " + "; ".join(parts)))
    out.append(SQ.branch("done", "finished", "terminado", claim="done",
                         change={"state": {aid: SQ.stated("done", "side-wall EIFS finished") for aid in side}},
                         model=f"attested done on {', '.join(side)} ONLY; front/rear untouched; not verified"))
    out.append(SQ.dont_know("J&P Construction (through the PM)"))
    return out


def given(src, sched: SQ.Rescheduler) -> List[Dict[str, Any]]:
    ix = records_index(src)
    cons = {c["kind"]: c for c in src["model"]["current_state"]["contradictions"]}
    imp = [c for c in src["model"]["current_state"]["contradictions"] if c["kind"] == "impossible_level"]
    imp_refs = [r for c in imp for r in c["refs"]]
    rec = {i["id"]: i for i in src["reconciliation"]["items"] if "id" in i}
    elec = rec.get("electrical_B01331892_I1EL_S1EL", {})
    plum = rec.get("plumbing_B23173802-S5_vs_B01141294-S5", {})
    no_change = lambda k, en, es, m: SQ.branch(k, en, es, model=m)  # noqa: E731
    roles = SQ.facade_roles(sched.net)
    side = roles["side"]
    side_rows = {aid: sched.base["normal"]["acts"][aid] for aid in side}
    side_when = "; ".join(f"{aid} {r['start']}..{r['finish']}, float {r['float']} wd" for aid, r in side_rows.items())
    out = [
        # EIFS: the critical path's own state, worded as an amount.
        SQ.question("work:eifs_side_walls", triggers=["unknown_state"], subject="eifs_side_walls", aspect="state",
                    place="ENVELOPE",
                    text_en="How much of the EIFS on the two side walls is done: under a quarter, about half, or most "
                            "of it?",
                    text_es="¿Cuánto del EIFS de las dos paredes laterales está hecho: menos de una cuarta parte, "
                            "más o menos la mitad, o la mayor parte?",
                    answerers=["superintendent", "cp", "company:J&P Construction"], topic="progress",
                    why=f"The side-wall EIFS leads the normal critical path ({side_when}); how much is in place is "
                        "not measured by any original record.",
                    evidence=[_rec(ix, "R0359")], branches=side_wall_branches(sched, side), activities=side,
                    gap="in_progress", cost="look", reads_as="done_unbacked", model_node=None),
        # The scaffold the EIFS crew works from: J&G has no record.
        SQ.question("work:scaffold_sides", triggers=["unknown_state", "stale_sub"], subject="scaffold", aspect="state",
                    place="ENVELOPE",
                    text_en="Is the J&G pipe scaffold up the full height of both side walls for the EIFS crew?",
                    text_es="¿El andamio de J&G está armado en toda la altura de las dos paredes laterales para el "
                            "equipo de EIFS?",
                    answerers=["cp", "superintendent", "company:J&G"], topic="progress",
                    why=f"The side-wall EIFS ({side_when}) is applied from the supported scaffold (permit "
                        "B01467559). J&G, the scaffold sub, has no original record at all.",
                    evidence=[SQ.evid("model coverage", "J&G", None, "J&G: no record of this sub at all", "model"),
                              SQ.evid("public", "B01467559-I1-SF", "2026-09-30", "Supported Scaffold: Permit Issued "
                                      "(rbx6-tga4), expires 2026-12-22", "public record")],
                    branches=[no_change("done", "yes, full height", "sí, en toda la altura",
                                        "attested: scaffold complete on both side walls; no schedule change"),
                              SQ.branch("not_yet", "only part of it", "solo una parte", claim="not_yet",
                                        change={"holds": {aid: SQ.HOLDS["blocked"]["values"] for aid in side}},
                                        model="attested: scaffold incomplete; EIFS on the rest WAITS for an "
                                              "ASSUMED q_hold_blocked"),
                              SQ.dont_know("J&G (through the PM)")],
                    activities=side, gap="unknown", cost="look", reads_as="done_unbacked"),
        # The plumber's "trim out" / "fixtures" vs the inferred "no board anywhere".
        SQ.question("infer:board_hang", triggers=["inference_disproof", "contradiction"], subject="board_hang",
                    aspect="state", place="L1",
                    text_en="Quality Plumbing's report says 'trim out' and 'fixtures' on floors 1-4. Is that tubs and "
                            "valves set at rough, or is sheetrock up on Floor 1?",
                    text_es="El reporte de Quality Plumbing dice 'trim out' y 'fixtures' en los pisos 1-4. ¿Son "
                            "bañeras y válvulas puestas en la etapa de rough, o ya hay sheetrock en el piso 1?",
                    answerers=["superintendent", "cp", "company:Quality Plumbing"], topic="progress",
                    why="The schedule INFERS no board on any floor (no record of board, no pre-board inspection on "
                        "record). Board on Floor 1 would mean close-in started before the electrical rough "
                        "inspection, which no source shows.",
                    evidence=[_rec(ix, "R0307"), _rec(ix, "R0308"), _rec(ix, "R0309"),
                              SQ.evid("588_schedule estimate", "board_hang_L1", TODAY,
                                      sched.state["board_hang_L1"]["basis"], "inference")],
                    branches=[no_change("absent", "tubs and valves at rough", "bañeras y válvulas en rough",
                                        "attested: the inference holds; no change"),
                              SQ.branch("present", "sheetrock is up on Floor 1", "ya hay sheetrock en el piso 1",
                                        claim="in_progress",
                                        change={"state": {"board_hang_L1": SQ.stated("in_progress", "board up on Floor 1")}},
                                        model="attested in_progress on board_hang at FLOOR_1; and a CONTRADICTION to "
                                              "resolve: board before any recorded electrical rough inspection"),
                              SQ.dont_know("Quality Plumbing (through the PM)")],
                    activities=["board_hang_L1"], gap="inferred", cost="look", reads_as="work_off_logged_level",
                    decision_weight=1.0, decision_why="covered work before its inspection would be a record decision",
                    model_node="board_hang", model_level="FLOOR_1"),
        # The punch walk of Oct 13 tags floors 588 does not have.
        SQ.question("contra:punch_walk_levels", triggers=["contradiction"], subject="punch_walk_2026-10-13",
                    aspect="binding", place="SITE",
                    text_en="The Oct 13 punch walk tags photos on floors 5, 6, 7 and a cellar; 588 has floors 1-4, a "
                            "mezzanine and a roof. Was that walk of this building?",
                    text_es="El recorrido de punch del 13 de oct. marca fotos en los pisos 5, 6, 7 y un sótano; el 588 "
                            "tiene pisos 1-4, mezzanine y techo. ¿Ese recorrido fue de este edificio?",
                    answerers=["superintendent", "cp"], topic="evidence",
                    why=f"{len(imp_refs)} photos of the 47-item walk sit on levels this building does not have, so "
                        "their punch items cannot be placed or closed. One says 'Roof missing coping', and the roof "
                        "coping has no record.",
                    evidence=[_rec(ix, r) for r in imp_refs],
                    branches=[SQ.branch("present", "yes, 588 (floor tags wrong)", "sí, el 588 (pisos mal marcados)",
                                        claim="present",
                                        change={"state": {"roof_coping": SQ.stated("not_started", "roof missing coping "
                                                                                    "(punch walk 10-13)")}},
                                        model="attested: the photos are 588's; their floors stay CANDIDATES until a "
                                              "person names each; 'Roof missing coping' becomes not_started on the "
                                              "coping"),
                              no_change("absent", "no, another building", "no, otro edificio",
                                        "attested: the walk is re-bound away from 588; no 588 state changes"),
                              SQ.dont_know("the PM")],
                    activities=["roof_coping"], gap="unknown", cost="look", reads_as="work_off_logged_level",
                    decision_weight=1.0, decision_why="placing or re-binding the walk's punch items is a record decision"),
        # Contradictions whose answer changes nothing: put through the same evaluation, so the engine says so.
        SQ.question("contra:cellar_piles_concrete", triggers=["contradiction"], subject="foundation_words",
                    aspect="binding", place="SITE",
                    text_en="Logs name a cellar slab, piles and concrete columns; the drawings show a slab on grade, "
                            "footings and a steel-stud frame. Were those words from another job?",
                    text_es="Los logs nombran un sótano, pilotes y columnas de concreto; los planos muestran losa sobre "
                            "terreno, zapatas y estructura de acero liviano. ¿Esas palabras eran de otra obra?",
                    answerers=["superintendent", "cp"], topic="progress",
                    why="Three model contradictions (names_a_cellar, piles_not_on_drawings, concrete_frame_in_a_cfs_"
                        "building) on foundation-era rows; the foundation and SOE are signed off (LOC 2026-11-05, "
                        "2026-10-29).",
                    evidence=[_rec(ix, r) for k in ("names_a_cellar", "piles_not_on_drawings",
                                                    "concrete_frame_in_a_cfs_building")
                              for r in (cons.get(k) or {}).get("refs", [])[:2]],
                    branches=[no_change("present", "yes, other job words", "sí, de otra obra", "attested; no state"),
                              no_change("absent", "no, SOE piles / crew words", "no, pilotes del SOE / palabras del equipo",
                                        "attested; no state"),
                              SQ.dont_know()],
                    activities=["foundation_sog"], gap="unknown", cost="look", reads_as="work_off_logged_level"),
        # The electrical permit two systems label differently.
        SQ.question("conflict:electrical_B01331892", triggers=["contradiction"], subject="electrical_permit",
                    aspect="record", place="SITE",
                    text_en="DOB shows the Hivolts electrical filing B01331892 as Cancelled in Open Data but Permit "
                            "Issued on the portal; Power Direct works under B01445590. Was the Hivolts filing withdrawn?",
                    text_es="El DOB muestra la solicitud eléctrica de Hivolts B01331892 como Cancelada en Open Data pero "
                            "Permiso Emitido en el portal; Power Direct trabaja bajo B01445590. ¿Se retiró la de Hivolts?",
                    answerers=["pm", "admin"], topic="agency_record",
                    why="An electrical filing left open by a replaced electrician must be withdrawn or signed off before "
                        "the electrical final and the TCO; the network has no activity for it.",
                    evidence=[SQ.evid("public", s.get("source"), s.get("as_of", "")[:10], s.get("says"), "public record")
                              for s in elec.get("sources") or []],
                    branches=[no_change("done", "yes, withdrawn", "sí, retirada",
                                        "attested; VERIFIED when the Accela status history or a re-pulled dm9a-ab7w "
                                        "shows it"),
                              no_change("not_yet", "no, still open", "no, sigue abierta",
                                        "attested: a TCO prerequisite the network does not model (withdraw or sign "
                                        "off B01331892)"),
                              SQ.dont_know("the admin")],
                    activities=["gate_dob_elec_final"], gap="unknown", cost="office", reads_as="done_unbacked",
                    decision_weight=1.0, decision_why="an open superseded filing blocks the final; not modelled"),
        # Two plumbing firms.
        SQ.question("conflict:second_plumber", triggers=["contradiction", "stale_sub"], subject="plumber_of_record",
                    aspect="record", place="SITE",
                    text_en="Two plumbing permits are open: Quality Piping (S5, expires Dec 3, holds the Nov 5 rough "
                            "passes) and 24 Seven (B23173802-S5). Is 24 Seven added for the street connection, or "
                            "replacing Quality Piping?",
                    text_es="Hay dos permisos de plomería: Quality Piping (S5, vence el 3 de dic., tiene las "
                            "inspecciones de rough del 5 de nov.) y 24 Seven (B23173802-S5). ¿24 Seven se agregó para la "
                            "conexión a la calle, o reemplaza a Quality Piping?",
                    answerers=["pm", "admin"], topic="agency_record",
                    why="It decides which permit must be renewed by Dec 3 and who books the gas final, the detention "
                        "certification and the DEP connection.",
                    evidence=[SQ.evid("public", s.get("source"), (s.get("as_of") or "")[:10], s.get("says"),
                                      "public record") for s in (plum.get("sources") or [])[:2]],
                    branches=[no_change("present", "added, for the street connection", "agregado, para la conexión",
                                        "attested; both permits stay"),
                              no_change("absent", "replacing Quality Piping", "reemplaza a Quality Piping",
                                        "attested; the finals move to B23173802 (not modelled)"),
                              SQ.dont_know("the admin")],
                    activities=["renew_permit_plumbing"], gap="unknown", cost="office",
                    reads_as="work_off_logged_level", decision_weight=1.0,
                    decision_why="which permit to renew by Dec 3"),
        # The house sewer: 24 Seven's street permit ran; DEP results are not public.
        SQ.question("work:house_sewer_connection", triggers=["inspection_not_public", "stale_sub"],
                    subject="sewer_connection", aspect="state", place="SITE",
                    text_en="Is the house sewer connected at the street? 24 Seven's DOT 'install water and sewer "
                            "service' permit ran Sep 23-Oct 16, renewed to Nov 1.",
                    text_es="¿Ya está conectada la cloaca del edificio en la calle? El permiso del DOT de 24 Seven "
                            "'instalar servicio de agua y cloaca' fue del 23 sep. al 16 oct., renovado al 1 nov.",
                    answerers=["superintendent", "pm", "company:24/7 Plumbing"], topic="progress",
                    why="The DEP connection inspection gates the plumbing final; no DEP result is public; the schedule "
                        "puts the drill-in in January.",
                    evidence=_timeline(src, "B012026266B82") + _timeline(src, "B012026289B88")
                    + _timeline(src, "CONN00056576"),
                    branches=[SQ.branch("done", "connected", "conectada", claim="done",
                                        change={"state": {k: SQ.stated("done", "house sewer connected")
                                                          for k in ("house_sewer_connection", "dep_connection_permit",
                                                                    "dot_opening_permit", "gate_detention_cert")}},
                                        model="attested done on the connection; the DEP inspection STAYS unknown until "
                                              "a DEP record or the inspector's paper",
                                        verified_when="DEP's connection inspection record or sign-off"),
                              SQ.branch("started", "started", "empezó", claim="started",
                                        change={"state": {"house_sewer_connection":
                                                          SQ.stated("in_progress", "connection started")}},
                                        model="attested started"),
                              SQ.branch("not_yet", "not yet", "todavía no", claim="not_yet",
                                        change={"state": {"house_sewer_connection":
                                                          SQ.stated("not_started", "not connected")}},
                                        model="attested not_yet"),
                              SQ.dont_know("24/7 Plumbing (through the PM)")],
                    activities=["house_sewer_connection"], gap="unknown", cost="look", reads_as="planned_start_passed"),
        # R0590: "fire alarm dob scheduled": no date, no fire-alarm filing in DOB.
        SQ.question("statement:fire_alarm_scheduled", triggers=["statement_gap", "inspection_not_public"],
                    subject="fire_alarm_inspection", aspect="date", place="SITE",
                    text_en="On Nov 10 you said the fire alarm inspection is scheduled. For what date, and is it FDNY's "
                            "acceptance test? No fire-alarm filing shows in DOB.",
                    text_es="El 10 de nov. dijo que la inspección de alarma contra incendios está programada. ¿Para qué "
                            "fecha, y es la prueba de aceptación del FDNY? No aparece ninguna solicitud de alarma en el DOB.",
                    answerers=["admin", "pm"], topic="agency_record",
                    why="An FDNY test needs the fire-alarm rough (Voltec: roster only, no record) and a pre-test; the "
                        "schedule puts the FDNY acceptance in March. A near date would mean the alarm is installed.",
                    evidence=[_rec(ix, "R0590"), SQ.evid("public", "DOB filings w9ak-ipjd", "2026-11-10",
                                                         "no fire-alarm filing exists", "public record (absence, read)")],
                    branches=[SQ.branch("present", "FDNY test booked within weeks", "prueba del FDNY en pocas semanas",
                                        claim="scheduled",
                                        change={"state": {k: SQ.stated("done", "fire alarm installed (implied by a "
                                                                       "booked FDNY test)")
                                                          for k in ("lv_rough_L1", "lv_rough_L2", "lv_rough_L3",
                                                                    "lv_rough_L4", "lv_rough_MEZ")}},
                                        model="attested scheduled on gate_fdny_fa with its date; the installed alarm is "
                                              "an IMPLICATION of the answer, attested, never verified"),
                              no_change("absent", "only requested / a later date", "solo pedida / fecha más adelante",
                                        "attested scheduled, no state change"),
                              SQ.dont_know("the PM")],
                    activities=["gate_fdny_fa", "lv_rough_L1"], gap="attested", cost="office",
                    reads_as="work_off_logged_level", decision_weight=1.0,
                    decision_why="the statement and the record disagree (no filing)"),
        # R0590: "water main dob inspection passed": attested; DEP results are not public.
        SQ.question("statement:water_main_paper", triggers=["statement_gap", "inspection_not_public"],
                    subject="water_service", aspect="document", place="SITE",
                    text_en="You said the water main inspection passed. Can you send the inspection paper (DEP or DOB)?",
                    text_es="Dijo que la inspección de la tubería principal de agua pasó. ¿Puede mandar el papel de la "
                            "inspección (DEP o DOB)?",
                    answerers=["admin", "pm"], topic="evidence",
                    why="The operator's word is the only basis for water service done; DEP results are not public. "
                        "A paper turns attested into verified.",
                    evidence=[_rec(ix, "R0590")] + _timeline(src, "CONN00056576"),
                    branches=[SQ.branch("done", "sent", "enviado", claim="done",
                                        change={"state": {"water_service": G.state_entry(
                                            "done", "verified_public_record", "IF the paper reads as a pass: verified "
                                            "by the document, not by the answer")}},
                                        model="the ANSWER stays attested; the DOCUMENT, once read and matching, "
                                              "verifies water_service",
                                        verified_when="the inspection paper is read and names this service"),
                              no_change("not_yet", "no paper", "no hay papel", "stays attested (R0590)"),
                              SQ.dont_know("the PM")],
                    activities=["water_service"], gap="attested", cost="office", reads_as="done_unbacked",
                    decision_weight=0.5, decision_why="an operator statement is the only basis"),
    ]
    # The under-slab electrical inference: its disproof is checkable, and nothing can change.
    inf = next((i for i in src["model"]["current_state"]["inferences"] if i.get("node") == "underground_electric"), None)
    if inf:
        out.append(SQ.question(
            "infer:under_slab_electric", triggers=["inference_disproof"], subject="underground_electric",
            aspect="state", place="L1",
            text_en="Was all the under-slab electrical conduit on Floor 1 in before the Sep 2 pour?",
            text_es="¿Toda la tubería eléctrica bajo la losa del piso 1 estaba puesta antes del vaciado del 2 de sep.?",
            answerers=["superintendent", "cp", "company:Power Direct"], topic="progress",
            why=f"Inference ({inf.get('confidence')}): {inf.get('basis')}. Disproof: {inf.get('disproof')}.",
            evidence=[SQ.evid("model inference", inf["ref"], inf.get("on"), inf.get("quote"), "inference")],
            branches=[no_change("done", "yes", "sí", "attested; the inference stands"),
                      no_change("not_yet", "no, some after", "no, parte después",
                                "attested; a contradiction with the pour: the slab cannot be re-sequenced"),
                      SQ.dont_know()],
            activities=["foundation_sog"], gap="inferred", cost="look", reads_as="done_unbacked",
            model_node="underground_electric", model_level="FLOOR_1"))
    return out


def answered_by_records(src) -> List[Dict[str, Any]]:
    """Questions a person would be asked by a naive generator that the record
    already answers, with the record."""
    ix = records_index(src)
    cs = src["model"]["current_state"]
    out = []
    pl = (src["dob_now"].get("plumbing_permit_B01141294-S5-PL") or {})
    for lv in ("FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF"):
        cell = ((cs["levels"].get(lv) or {}).get("work") or {}).get("gate_plumbing_rough") or {}
        if cell.get("status") == "done_verified":
            out.append({"id": f"gate:gate_plumbing_rough:{lv}", "subject": "gate_plumbing_rough", "place": lv,
                        "reason": "answered_by_records",
                        "detail": f"DOB inspection 7755632 passed plumbing rough (W/S, storm, gas) on {lv} 2026-11-05 "
                                  "(verified); a person's word would rank below it",
                        "evidence": [SQ.evid("public", r, "2026-11-05", "DOB floor table: PASSED", "public record")
                                     for r in (cell.get("refs") or [])[:3]]})
    for inf in cs.get("inferences") or []:
        ver = [s for s in inf.get("signals") or [] if s.get("kind") in ("verified", "confirmed")]
        if ver:
            out.append({"id": f"infer:{inf['node']}", "subject": inf["node"], "place": ",".join(inf.get("levels") or []),
                        "reason": "answered_by_records",
                        "detail": f"inference '{inf['quote']}' is backed by "
                                  + ", ".join(f"{s['ref']} ({s['kind']}, {s['on']})" for s in ver),
                        "evidence": [SQ.evid("public", s["ref"], s["on"], s["kind"], "public record") for s in ver]})
    b = cs.get("building") or {}
    if (b.get("gate_plumbing_rough") or {}).get("status") == "done_attested":
        out.append({"id": "statement:plumbing_rough_passed", "subject": "gate_plumbing_rough", "place": "SITE",
                    "reason": "answered_by_records",
                    "detail": "the operator's 'plumbing rough ins dob passed' (R0590, attested) is verified by DOB "
                              "7755632 (2026-11-05); nothing to ask",
                    "evidence": [_rec(ix, "R0590")]})
    _ = pl
    return out


def build_ctx(src: Dict[str, Any]) -> Dict[str, Any]:
    sb = schedule_base(src)
    p = sb["prepared"]
    sched = SQ.Rescheduler(p["net"], sb["state"], p["assumptions"], TODAY)
    cs = src["model"]["current_state"]
    roster = (src["model"].get("coverage") or {}).get("subs", {}).get("per_sub") or {}
    last = {}
    for comp in roster:
        s = (cs.get("subs") or {}).get(comp) or {}
        last[comp] = date.fromisoformat(s["last"]) if s.get("last") else None
    ctx = {"today": TODAY, "sched": sched, "model": cs, "records": records_index(src),
           "people": [{"role": r} for r in SQ.ROLE_SLOTS], "permits": permits(src), "permit_words": PERMIT_WORDS,
           "permit_why": PERMIT_WHY, "permit_consequence": PERMIT_CONSEQUENCE, "not_public": NOT_PUBLIC,
           "utilities": utilities(src),
           "sub_last_original": last, "answered_by_records": answered_by_records(src), "answers": [], "history": [],
           "schedule_notes": sb["notes"]}
    ctx["given"] = given(src, sched)
    ctx["levers"] = levers(src, sched)
    return ctx


# ── THE CHAIN ─────────────────────────────────────────────────────────────

#: SIMULATED replies, one per branch key, English and Spanish. Never sent,
#: never received: written here to drive the chain.
SIMULATED = {
    "done": "listo, ya terminamos", "not_yet": "not yet", "blocked": "blocked waiting on the scaffold",
    "started": "started", "passed": "passed", "scheduled": "booked for next week",
    "percent_25": "maybe 20%", "percent_50": "50%", "percent_75": "75%", "dont_know": "no sé",
    "present": "yes", "absent": "no",
}


def _items(src) -> Dict[str, Any]:
    model = CI.model_from_building(src["building"], name="588 Thomas S. Boyland St")
    rec, meta = R.items_from_records(src["records"], model, project_id=PID, audit=src["audit"] or None)
    pub = R.items_from_public(src["timeline"], project_id=PID)
    dob = R.items_from_dob_now(src["dob_now"], project_id=PID)
    originals = [r for r in src["records"] if R.audit_class(src["audit"].get(str(r["id"]))) == "original"]
    hc = R.headcounts(originals, readme_dups=False)
    return {"model": model, "items": rec + pub + dob, "hc": hc, "rec": rec}


def _cell(state: Dict[str, Any], node: Optional[str], level: Optional[str]) -> Any:
    if not node:
        return None
    if level:
        return (((state.get("levels") or {}).get(level) or {}).get("work") or {}).get(node, {}).get("status", "unknown")
    return ((state.get("building") or {}).get(node) or {}).get("status", "unknown")


def trace(src, ctx, q: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """plans + logs + photos -> location -> activity -> progress -> dependency -> schedule."""
    S = ctx["sched"]
    model = base["model"]
    aid = q["activities"][0]
    a = S.by_id[aid]
    refs = [e["ref"].split(":")[0] for e in q["evidence"] if e["source"] == "records"]
    recs = {str(r["id"]): r for r in src["records"]}
    steps = []
    for rid in refs[:3]:
        r = recs.get(rid)
        if not r:
            continue
        fam = R.trade_family(R._canon(r.get("company")), R.roster(src["records"]).get(R._canon(r.get("company")), ""))
        text = r.get("description") or r.get("quote") or ""
        node = R.classify(text, fam)
        levels, cands, space = R.place(r.get("location_text"), model, node, text)
        steps.append({"record": rid, "type": r.get("type"), "date": r.get("date"), "company": r.get("company"),
                      "audit_class": R.audit_class(src["audit"].get(rid)), "location_text": r.get("location_text"),
                      "text": text[:100], "location": {"levels": levels, "candidates": cands, "space": space},
                      "activity": node})
    b = S.base["normal"]["acts"][aid]
    return {
        "plans": {"activity": aid, "name": a["name"], "scope": a.get("scope"), "zone": a.get("zone"),
                  "building_levels": model.get("levels"), "superstructure": model.get("superstructure")},
        "logs_and_photos": steps,
        "work_progress": {"model_cell": _cell(src["model"]["current_state"], q.get("model_node"), q.get("model_level")),
                          "node": q.get("model_node"), "level": q.get("model_level")},
        "dependency_state": {"state": S.state[aid], "predecessors": [l["from"] for l in S.net["links"]
                                                                     if l["to"] == aid][:6],
                             "successors": S.successors([aid])[:6]},
        "schedule": {"normal_start": b["start"], "normal_finish": b["finish"], "float_wd": b["float"],
                     "critical": b["critical"], "tco": {s: S.base[s]["tco"] for s in SQ.SCENARIOS}},
    }


def chain(src, ctx, q: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    S = ctx["sched"]
    out = {"question": q["id"], "text_en": q["text_en"], "text_es": q["text_es"], "recipient": q.get("recipient"),
           "answerer": q.get("answerer"), "trace": trace(src, ctx, q, base), "branches": []}
    before = T.public(T.as_of(base["items"], base["model"], TODAY, project_id=PID, headcounts=base["hc"]))
    for k, b in enumerate(q["branches"]):
        reply = SIMULATED.get(b["key"], b["label_en"])
        ans = SQ.read_reply(q, reply)
        how = "read by confirmation_queue.parse_reply (fixed rules)"
        if ans is None or SQ.branch_for(q, ans) is not b:
            ans = {"answer": "dont_know" if b["category"] == "dont_know" else
                   ("done" if b["claim"] in (None, "done", "present") else b["claim"]), "words": reply}
            how = ("NOT read by the fixed rules (left for the DM brain); the branch is chosen as the DM brain would, "
                   "SIMULATED")
        item = SQ.answer_evidence(q, dict(ans), answer_id=f"SIM-{q['id']}-{k}", person=q.get("recipient") or "",
                                  on=TODAY, project_id=PID)
        row = {"branch": b["key"], "SIMULATED_reply": reply, "read": how, "answer": ans.get("answer"),
               "evidence_item": None if item is None else {kk: item.get(kk) for kk in
                                                           ("kind", "claim", "node", "levels", "by", "quote", "source")}}
        if item is not None and item.get("claim") != "dont_know" and q.get("model_node"):
            after = T.public(T.as_of(base["items"] + [item], base["model"], TODAY, project_id=PID,
                                     headcounts=base["hc"]))
        else:
            after = before
        row["model_cell"] = {"before": _cell(before, q.get("model_node"), q.get("model_level")),
                             "after": _cell(after, q.get("model_node"), q.get("model_level"))}
        doc_after = dict(src["model"], current_state=after)
        st, _n = G.state_from_model(doc_after, S.net, ctx["_provisional"])
        carried = {aid: st.get(aid) for aid in (b["change"].get("state") or {})}
        carried_ok = [aid for aid, v in carried.items() if v and v["status"] == b["change"]["state"][aid]["status"]
                      and v["status"] != S.state.get(aid, G.DEFAULT_STATE)["status"]]
        model_moved = sorted(k2 for k2 in st if st[k2]["status"] != ctx["_model_state"].get(k2, G.DEFAULT_STATE)["status"])
        direct = {aid: v for aid, v in (b["change"].get("state") or {}).items() if aid not in carried_ok}
        named_states = set(b["change"].get("state") or {})
        # the answer targets ITS activities: what the rebuilt model moves beyond them is reported, not applied
        change = {"state": {**{k2: st[k2] for k2 in model_moved if k2 in named_states}, **direct}}
        for key in ("assumptions", "holds"):
            if b["change"].get(key):
                change[key] = b["change"][key]
        eff = S.effect(change, q["activities"]) if b["category"] != "dont_know" else None
        named = set(b["change"].get("state") or {})
        row["schedule"] = {
            "from_the_updated_model": model_moved,
            # what the rebuilt model moved that the answer did not name: the model's granularity, not the answer
            "moved_by_the_model_beyond_the_answer_not_applied": [k2 for k2 in model_moved if k2 not in named],
            "applied_directly_because_the_model_does_not_carry_it": sorted(direct) + sorted(
                k2 for k2 in ("assumptions", "holds") if b["change"].get(k2)),
            "tco": eff["tco"] if eff else {s: S.base[s]["tco"] for s in SQ.SCENARIOS},
            "tco_delta_wd": eff["tco_delta_wd"] if eff else {s: 0 for s in SQ.SCENARIOS},
            "next_activity": eff["next_activity"] if eff else None,
            "agrees_with_the_question_branch": (eff["tco_delta_wd"] if eff else {s: 0 for s in SQ.SCENARIOS})
            == b["schedule_effect"]["tco_delta_wd"]}
        out["branches"].append(row)
    return out


# ── README ────────────────────────────────────────────────────────────────

def _d(e: Dict[str, Any]) -> str:
    return " ".join(f"{s[0]}{v:+d}" for s, v in e["tco_delta_wd"].items())


def readme(doc: Dict[str, Any]) -> str:
    L = ["# 588 site questions - SIMULATION (data date 2026-11-10)", "",
         "**Evaluation only. Nothing was sent; every answer below is SIMULATED.** Built by `backend/lib/site_questions.py` "
         "(runner `backend/scripts/intel_588_questions.py`) from the audited model, the schedule estimate and the public "
         "records. Full detail: `588_questions.json`.", ""]
    b = doc["base_schedule"]
    L += [f"Base schedule (estimate, model laid over): TCO fast {b['fast']['tco']}, normal {b['normal']['tco']}, "
          f"conservative {b['conservative']['tco']}. Normal critical path starts "
          f"{' > '.join(b['normal']['critical_path_head'])}.", "",
          f"Value: `{doc['value_formula']}`", "",
          "Delivery: superintendent / CP questions are SHADOW only: lib/dm_roles says a field role is never messaged "
          "first, so confirmation_queue refuses live delivery to them. Role slots only; no personal names. A "
          "subcontractor is not a LeveLog user: its questions go through the PM and count against the PM's cap.", "",
          "Answers create **attested** evidence at most (confirmation_queue.answer_item); an inspection result a person "
          "states stays attested until a document or agency record verifies it; \"don't know\" changes nothing and is "
          "never a no. Schedule delta per branch = TCO change in working days (f = fast, n = normal, c = conservative), "
          "re-run by schedule_generator.", ""]
    for role, qs in doc["by_person"].items():
        L += [f"## {role} ({len(qs)})", ""]
        if not qs:
            L += ["(no question today)", ""]
            continue
        L += ["| # | value | question (EN / ES) | answerer | why | trigger | branches: TCO delta (f n c), first successor move | urgency |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for k, q in enumerate(qs, 1):
            trig = "; ".join(f"{e['source']} {e['ref']} {e['date'] or ''}".strip() for e in q["evidence"][:3])
            brs = "<br>".join(
                f"**{x['label_en']}** ({x['category']}): {_d(x['schedule_effect'])}"
                + (f", next {x['schedule_effect']['next_activity']['id']} {x['schedule_effect']['next_activity']['move_wd']:+d} wd"
                   if x["schedule_effect"].get("next_activity") and x["schedule_effect"]["next_activity"].get("move_wd")
                   else "") for x in q["branches"])
            u = q["urgency"]
            L.append(f"| {k} | {q['value']['score']} | {q['text_en']}<br>_{q['text_es']}_ | {q['answerer']} | "
                     f"{q['why_it_matters']} | {', '.join(q['triggers'])}: {trig} | {brs} | "
                     f"needed by {u['needed_by']} ({u['days']} d) |")
        L.append("")
    sup = doc["suppressed"]
    L += ["## Cap check", "", "Did anything the cap held back outrank what a person was asked? (ranked placement; "
          "listed so it is visible)", "", "| recipient | lowest asked | highest held by the cap | holds |",
          "| --- | --- | --- | --- |"]
    for role, a in doc["cap_audit"].items():
        L.append(f"| {role} | {a['lowest_asked']} | {a['highest_capped']} ({a['highest_capped_id']}) | {a['holds']} |")
    L.append("")
    L += [f"## Suppressed ({doc['counts']['suppressed']})", "", "| id | reason | detail |", "| --- | --- | --- |"]
    for s in sup:
        L.append(f"| {s['id']} | {s['reason']} | {str(s['detail'])[:260]} |")
    L += ["", "## Chain demonstration (top 3 questions and the top field question, every branch; answers SIMULATED)", ""]
    for c in doc["chain_demo"]:
        t = c["trace"]
        L += [f"### {c['question']} -> {c['recipient']} ({c['answerer']})", "",
              f"- Plans: {t['plans']['name']} ({t['plans']['zone']}); scope {t['plans']['scope']}",
              "- Logs and photos -> location -> activity: " + ("; ".join(
                  f"{s['record']} {s['date']} {s['company'] or ''} '{s['location_text']}' / '{s['text'][:50]}' "
                  f"[{s['audit_class']}] -> {s['location']['levels'] or s['location']['space'] or 'building'} -> "
                  f"{s['activity']}" for s in t["logs_and_photos"]) or "no record evidence (public / schedule only)"),
              f"- Work progress (model): {t['work_progress']}",
              f"- Dependency state: {t['dependency_state']['state']['status']} ({t['dependency_state']['state']['evidence']}); "
              f"predecessors {t['dependency_state']['predecessors']}; successors {t['dependency_state']['successors']}",
              f"- Schedule: {t['schedule']}", f"- Question: {c['text_en']} / _{c['text_es']}_", "",
              "| branch | SIMULATED reply | read | evidence created | model cell before -> after | schedule from model / direct | TCO delta (f n c) | first successor | matches branch |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in c["branches"]:
            ev = r["evidence_item"] or {}
            na = r["schedule"]["next_activity"]
            L.append(f"| {r['branch']} | \"{r['SIMULATED_reply']}\" | {r['read'][:60]} | {ev.get('kind')} {ev.get('claim')} | "
                     f"{r['model_cell']['before']} -> {r['model_cell']['after']} | {r['schedule']['from_the_updated_model'][:4]} / "
                     f"{r['schedule']['applied_directly_because_the_model_does_not_carry_it'][:4]} | "
                     f"{_d(r['schedule'])} | {(na or {}).get('id')} {(na or {}).get('move_wd')} | "
                     f"{r['schedule']['agrees_with_the_question_branch']} |")
        L.append("")
    over = sorted({f"{c['question']} / {r['branch']}: {', '.join(r['schedule']['moved_by_the_model_beyond_the_answer_not_applied'])}"
                   for c in doc["chain_demo"] for r in c["branches"]
                   if r["schedule"]["moved_by_the_model_beyond_the_answer_not_applied"]})
    if over:
        L += ["**Model coarser than the answer:** the rebuilt model moved schedule activities the answer did not "
              "name; they were REPORTED and NOT applied (an answer targets its own activities): " + "; ".join(over), ""]
    L += ["## Notes", ""] + [f"- {n}" for n in doc["notes"]]
    return "\n".join(L) + "\n"


def run(data: Path) -> Dict[str, Any]:
    src = load(data)
    ctx = build_ctx(src)
    sb = schedule_base(src)
    ctx["_provisional"] = sb["prepared"]["provisional"]
    ctx["_model_state"] = sb["state"]
    doc = SQ.generate(ctx)
    ctx["_evaluated"] = doc.pop("_asked")
    base = _items(src)
    asked = sorted((q for qs in doc["by_person"].values() for q in qs), key=lambda q: (-q["value"]["score"], q["id"]))
    demo = list(asked[:3])
    field = next((q for q in asked if q["recipient"] in ("superintendent", "cp")), None)
    if field is not None and field not in demo:
        demo.append(field)          # the top FIELD question too: the one that runs from logs and photos
    doc["chain_demo"] = [chain(src, ctx, _rebuild(ctx, q), base) for q in demo]
    doc["notes"] = ctx["schedule_notes"] + [
        "Persons are role slots (superintendent, CP, PM, admin) on 588; opt-in and assignment were not read (no "
        "production access).",
        "Evidence classes: 'original' = audited original record; 'derived' = summary context only (never evidence); "
        "public = an agency record; schedule estimate = schedule_generator output, never a fact.",
        "A hold (q_hold_blocked, q_hold_permit_lapse) is an INDUSTRY ASSUMPTION used only by the branch that needs it.",
        "Spanish text is written per question; a family with no Spanish words of its own is flagged es_fallback.",
        "Reported done is done (schedule_generator, this change): work recorded done on any word short of a verified "
        "record no longer waits for its open prerequisites; each open prerequisite is a contradiction "
        "(state_contradictions) and becomes a question about the open work, never a delay. An unverified inspection "
        "pass stays PENDING, so a person's 'passed' moves no gate.",
        "Facade by role: the EIFS activities are found by elevation (site_questions.facade_roles), never by id. A "
        "side-wall answer is carried as attested on the side-wall activities only; the model's single facade node is "
        "not updated by it (it would mark front/rear too).",
        "Permit lapse: the not-filed branch stops the work under way that needs the permit for q_hold_permit_lapse "
        "from the expiry, and re-runs the schedule; what the stoppage does not capture (violation, public safety) is "
        "stated as the consequence and carried by D.",
        "Formula change (N): moves of crew work and inspection gates starting within the next 10 working days, "
        "summed, weight 0.5 (was: the first successor anywhere in three weeks, weight 0.25), so a question that "
        "changes what crews do next week is not crowded out by one that moves paperwork with months of float.",
        "The PM and admin caps fill with office questions, so the subcontractor relays (through the PM) wait; the "
        "field caps fill with three-week-window state questions. Everything over the cap is listed under daily_cap "
        "with its value, for the next day.",
    ]
    return doc


def _rebuild(ctx, q_public: Dict[str, Any]) -> Dict[str, Any]:
    """The evaluated question with its branch changes (the public copy drops them)."""
    for q in ctx["_evaluated"]:
        if q["id"] == q_public["id"]:
            return dict(q, recipient=q_public.get("recipient"), answerer=q_public.get("answerer"))
    raise KeyError(q_public["id"])


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    data = Path(args[0] if args else os.environ.get("INTEL588_DATA", DEFAULT_DATA))
    doc = run(data)
    out = data / "questions"
    out.mkdir(parents=True, exist_ok=True)
    (out / "588_questions.json").write_text(json.dumps(G.jsonable(doc), indent=1, ensure_ascii=False, default=str),
                                            encoding="utf-8")
    (out / "README.md").write_text(readme(doc), encoding="utf-8")
    for role, qs in doc["by_person"].items():
        for q in qs:
            print(role, q["value"]["score"], q["id"], "|", q["text_en"])
    print("suppressed", doc["counts"]["suppressed"], doc["counts"]["by_reason"], "runs", doc["counts"]["schedule_runs"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
