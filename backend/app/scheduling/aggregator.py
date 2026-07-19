"""Aggregate ALREADY-EXTRACTED plan data into a typed ProjectModel.

Single responsibility: produce/persist the per-project structured object the
scheduler will later consume. This module does NOT parse PDFs, call any LLM,
schedule anything, or touch WhatsApp. It only reads document_page_index rows
(already produced by the plan-index pipeline) plus the prior ProjectModel, and
upserts the merged result into `project_models`.

DB access follows the repo convention: functions take `db` as the first arg
(mirrors lib/logbook/deficiency.run_deficiency_check_post_save). Pure builders
take a fixed `now` so the same page set yields a byte-identical proposed model
(everything is sorted by id).

Sourcing:
  - Plan-derived scalars (floors, has_*) are computed from indexed page fields.
  - special_inspections + zones are LOW-CONFIDENCE plan-seeded proposals — plan
    general notes list *typical* inspections, not what was filed on a TR1, so
    they are `status="proposed"` until an operator confirms them and MUST NOT be
    treated as required before that.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.scheduling.project_model import (
    PLAN_DERIVED_SCALARS,
    ProjectModel,
    FieldProvenance,
    ModelConfirmRequest,
    SpecialInspection,
    Zone,
    is_known_special_inspection,
    SPECIAL_INSPECTION_VOCAB,
)

# A project with fewer indexed (non-spec) pages than this is treated as sparse:
# every plan-derived field is forced to confidence="low" because the signal is
# too thin to trust.
_MIN_PAGES_FOR_HIGH = 3

# Free-text fields on a document_page_index row that carry system/keyword signal.
_TEXT_FIELDS = ("sheet_title", "summary", "notes", "materials", "spaces", "code_refs")
# Fields scanned for special-inspection callouts (general notes + code refs +
# material callouts).
_SI_TEXT_FIELDS = ("notes", "code_refs", "materials", "summary")

# ── System-presence signals ──────────────────────────────────────────
# discipline codes come from server.detect_discipline / Qwen: AR ME EL PL SP ST GN.
# SP == sprinkler + standpipe + fire protection. There is NO gas or elevator
# discipline code, so those rely on text keywords only (lower confidence).
_SPRINKLER_RE = re.compile(r"\bsprinkler")
_STANDPIPE_RE = re.compile(r"\bstand[\s-]*pipe")
_ELEVATOR_RE = re.compile(r"\belevator|\bhoist[\s-]*way|\belev\.")
_GAS_RE = re.compile(
    r"fuel[\s-]*gas|natural[\s-]*gas|\bgas[\s-]*(?:pip|riser|service|meter|main|line)|\bgas\b"
)

# ── Special-inspection keyword → controlled-vocab mapping ─────────────
# Matched against lower-cased page text. Ambiguous bare words (gas, concrete,
# mechanical, steel) are intentionally permissive — these are proposals only.
_SI_PATTERNS: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("firestopping", re.compile(r"fire[\s-]*stop")),
    ("fire_resistant_penetrations", re.compile(
        r"(?:through|membrane)[\s-]*penetration|penetration[\s-]*firestop|"
        r"fire[\s-]*resist\w*[\s-]*penetration")),
    ("mechanical", re.compile(r"\bmechanical\b|\bhvac\b")),
    ("sprinkler", re.compile(r"\bsprinkler")),
    ("standpipe", re.compile(r"\bstand[\s-]*pipe")),
    ("energy_nycecc", re.compile(r"\bnycecc\b|energy[\s-]*code|energy[\s-]*conservation")),
    ("structural_steel", re.compile(r"structural[\s-]*steel|structural[\s-]*stability")),
    ("structural_welding", re.compile(r"\bweld")),
    ("structural_bolting", re.compile(r"\bbolt")),
    ("structural_concrete", re.compile(r"\bconcrete\b|cast[\s-]*in[\s-]*place")),
    ("masonry", re.compile(r"\bmasonry\b")),
    ("soil_investigation", re.compile(r"\bsoil\b|\bsubgrade\b|\bgeotech")),
    ("deep_foundations", re.compile(r"\bpile\b|\bcaisson|deep[\s-]*foundation")),
    ("fuel_gas_piping", re.compile(r"fuel[\s-]*gas|\bgas[\s-]*pip")),
    ("sprayed_fire_resistant_material", re.compile(r"\bsfrm\b|sprayed[\s-]*fire|fireproofing")),
    ("post_installed_anchors", re.compile(
        r"post[\s-]*installed[\s-]*anchor|expansion[\s-]*anchor|adhesive[\s-]*anchor")),
)

_PHASE_RE = re.compile(r"\bphase[\s-]*(\d+)\b")
_TCO_RE = re.compile(r"\btco\b|temporary[\s-]*certificate[\s-]*of[\s-]*occupancy")


# ── Small helpers ────────────────────────────────────────────────────
def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _page_id(page: Dict[str, Any]) -> str:
    return str(page.get("_id"))


def _text_of(page: Dict[str, Any], fields: Tuple[str, ...]) -> str:
    parts = []
    for f in fields:
        v = page.get(f)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


def _non_spec(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [p for p in pages if not p.get("is_spec_page")]


def _all_floor_list(floors: int) -> List[int]:
    return list(range(1, floors + 1)) if floors >= 1 else []


# ── Plan-derived scalars ─────────────────────────────────────────────
def _derive_floors(pages: List[Dict[str, Any]], sparse: bool) -> Tuple[int, FieldProvenance]:
    """floors = max distinct integer floor observed across pages. Non-numeric
    labels (ROOF/CELLAR/GROUND/PENTHOUSE/MEZZANINE) do not parse and are
    dropped — this can undercount; hence low confidence when the signal is thin.
    """
    parsed: List[Tuple[int, str]] = []
    for p in pages:
        raw = p.get("floor")
        if not raw:
            continue
        m = re.search(r"\d+", str(raw))
        if m:
            parsed.append((int(m.group()), _page_id(p)))
    distinct = sorted({n for n, _ in parsed})
    value = max(distinct) if distinct else 0
    evidence = sorted({pid for n, pid in parsed if n == value})
    confidence = "high" if (not sparse and len(distinct) >= 2 and value > 0) else "low"
    prov = FieldProvenance(
        source="plan_derived",
        confidence=confidence,
        status="proposed",
        evidence_page_ids=evidence,
    )
    return value, prov


def _derive_system(
    pages: List[Dict[str, Any]],
    sparse: bool,
    *,
    keyword_re: "re.Pattern",
    discipline_codes: Tuple[str, ...],
) -> Tuple[bool, FieldProvenance]:
    evidence: List[str] = []
    discipline_hit = False
    for p in pages:
        disc = (p.get("discipline") or "").upper()
        by_disc = disc in discipline_codes
        by_text = bool(keyword_re.search(_text_of(p, _TEXT_FIELDS)))
        if by_disc or by_text:
            evidence.append(_page_id(p))
            if by_disc:
                discipline_hit = True
    evidence = sorted(set(evidence))
    value = bool(evidence)
    if not value or sparse:
        confidence = "low"
    elif discipline_hit or len(evidence) >= 2:
        confidence = "high"
    else:
        confidence = "low"
    prov = FieldProvenance(
        source="plan_derived",
        confidence=confidence,
        status="proposed",
        evidence_page_ids=evidence,
    )
    return value, prov


# ── Plan-seeded proposals ────────────────────────────────────────────
def _propose_special_inspections(pages: List[Dict[str, Any]]) -> List[SpecialInspection]:
    hits: Dict[str, List[str]] = {}
    for p in pages:
        text = _text_of(p, _SI_TEXT_FIELDS)
        if not text:
            continue
        pid = _page_id(p)
        for canonical, pat in _SI_PATTERNS:
            if pat.search(text):
                hits.setdefault(canonical, []).append(pid)
    out: List[SpecialInspection] = []
    for canonical, page_ids in hits.items():
        out.append(SpecialInspection(
            id=f"si_{canonical}",
            inspection_type=canonical,
            provenance=FieldProvenance(
                source="plan_seeded",
                confidence="low",
                status="proposed",
                evidence_page_ids=sorted(set(page_ids)),
            ),
        ))
    return sorted(out, key=lambda s: s.id)


def _propose_zones(pages: List[Dict[str, Any]], floors: int) -> List[Zone]:
    """Zones from phasing callouts; default to a single all-floors zone when no
    reliable callout is found. Multi-zone floor split is NOT derivable from the
    free text, so each detected phase gets all floors (flagged low/proposed)."""
    phase_pages: Dict[int, List[str]] = {}
    tco = False
    for p in pages:
        text = _text_of(p, ("notes", "summary", "sheet_title"))
        if not text:
            continue
        if _TCO_RE.search(text):
            tco = True
        for m in _PHASE_RE.finditer(text):
            phase_pages.setdefault(int(m.group(1)), []).append(_page_id(p))

    all_floors = _all_floor_list(floors)
    if len(phase_pages) >= 2:
        zones: List[Zone] = []
        for n in sorted(phase_pages):
            zones.append(Zone(
                id=f"zone_phase_{n}",
                floors=all_floors,
                is_tco_phase=tco,
                provenance=FieldProvenance(
                    source="plan_seeded",
                    confidence="low",
                    status="proposed",
                    evidence_page_ids=sorted(set(phase_pages[n])),
                ),
            ))
        return sorted(zones, key=lambda z: z.id)

    return [Zone(
        id="zone_all",
        floors=all_floors,
        is_tco_phase=False,
        provenance=FieldProvenance(
            source="plan_seeded",
            confidence="low",
            status="proposed",
            evidence_page_ids=[],
        ),
    )]


# ── Build + merge ────────────────────────────────────────────────────
def build_project_model(
    project_id: str,
    pages: List[Dict[str, Any]],
    *,
    existing: Optional[ProjectModel] = None,
    now: Optional[datetime] = None,
) -> ProjectModel:
    """Pure aggregation: derive scalars, propose SIs/zones, then MERGE with any
    prior model so confirmed fields are never downgraded or overwritten."""
    ts = _now(now)
    non_spec = _non_spec(pages)
    sparse = len(non_spec) < _MIN_PAGES_FOR_HIGH

    floors, floors_prov = _derive_floors(non_spec, sparse)
    gas, gas_prov = _derive_system(
        non_spec, sparse, keyword_re=_GAS_RE, discipline_codes=())
    spr, spr_prov = _derive_system(
        non_spec, sparse, keyword_re=_SPRINKLER_RE, discipline_codes=("SP",))
    stp, stp_prov = _derive_system(
        non_spec, sparse, keyword_re=_STANDPIPE_RE, discipline_codes=("SP",))
    elv, elv_prov = _derive_system(
        non_spec, sparse, keyword_re=_ELEVATOR_RE, discipline_codes=())

    model = ProjectModel(
        project_id=project_id,
        floors=floors,
        has_gas=gas,
        has_sprinkler=spr,
        has_standpipe=stp,
        has_elevator=elv,
        field_provenance={
            "floors": floors_prov,
            "has_gas": gas_prov,
            "has_sprinkler": spr_prov,
            "has_standpipe": stp_prov,
            "has_elevator": elv_prov,
        },
        special_inspections=_propose_special_inspections(non_spec),
        zones=_propose_zones(non_spec, floors),
        aggregated_at=ts,
    )

    if existing is not None:
        model = _merge_preserving_confirmed(new=model, existing=existing)
        model.aggregated_at = ts
    return model


def _merge_preserving_confirmed(*, new: ProjectModel, existing: ProjectModel) -> ProjectModel:
    """Re-aggregation must NEVER downgrade confirmed→proposed or overwrite an
    operator value. Confirmed fields keep their existing value + provenance;
    still-proposed fields are refreshed; new proposals are added."""
    merged = new.model_copy(deep=True)

    # Scalars: keep confirmed values + provenance from existing.
    for field in PLAN_DERIVED_SCALARS:
        ex_prov = existing.field_provenance.get(field)
        if ex_prov is not None and ex_prov.status == "confirmed":
            setattr(merged, field, getattr(existing, field))
            merged.field_provenance[field] = ex_prov.model_copy(deep=True)

    # Special inspections: keep every confirmed existing entry; add fresh
    # proposals whose id isn't already confirmed.
    merged.special_inspections = _merge_list(
        new.special_inspections, existing.special_inspections)
    merged.zones = _merge_list(new.zones, existing.zones)
    return merged


def _merge_list(new_items: List[Any], existing_items: List[Any]) -> List[Any]:
    confirmed = [i for i in existing_items if i.provenance.status == "confirmed"]
    confirmed_ids = {i.id for i in confirmed}
    fresh = [i for i in new_items if i.id not in confirmed_ids]
    out = [i.model_copy(deep=True) for i in confirmed] + fresh
    return sorted(out, key=lambda i: i.id)


# ── Operator confirm ─────────────────────────────────────────────────
def apply_confirm(
    model: ProjectModel,
    req: ModelConfirmRequest,
    *,
    user_id: str,
    now: Optional[datetime] = None,
) -> ProjectModel:
    """Apply an operator confirm. Raises ValueError (→ 422 at the endpoint) on
    an unknown special-inspection type, an unknown id, or a wrong-typed scalar.
    Does not mutate the input model."""
    ts = _now(now)
    m = model.model_copy(deep=True)

    # Validate vocab up-front so nothing is half-applied.
    for t in req.special_inspection_types:
        if not is_known_special_inspection(t):
            raise ValueError(
                f"Unknown special inspection type '{t}'. "
                f"Allowed: {', '.join(SPECIAL_INSPECTION_VOCAB)}"
            )

    def _stamp(prov: FieldProvenance) -> None:
        prov.status = "confirmed"
        prov.last_confirmed_by = user_id
        prov.last_confirmed_at = ts

    # Scalars.
    for sc in req.scalars:
        if sc.field == "floors":
            if isinstance(sc.value, bool) or not isinstance(sc.value, int):
                raise ValueError("floors must be an integer")
        else:
            if not isinstance(sc.value, bool):
                raise ValueError(f"{sc.field} must be a boolean")
        setattr(m, sc.field, sc.value)
        prov = m.field_provenance.get(sc.field) or FieldProvenance(
            source="plan_derived", confidence="low", status="proposed")
        _stamp(prov)
        m.field_provenance[sc.field] = prov

    # Existing special inspections by id → confirm.
    si_by_id = {si.id: si for si in m.special_inspections}
    for si_id in req.special_inspection_ids:
        si = si_by_id.get(si_id)
        if si is None:
            raise ValueError(f"Unknown special_inspection id '{si_id}'")
        _stamp(si.provenance)

    # Operator-declared new special-inspection types (validated above).
    for t in req.special_inspection_types:
        sid = f"si_{t}"
        existing_si = si_by_id.get(sid)
        if existing_si is not None:
            existing_si.provenance.source = "operator_declared"
            _stamp(existing_si.provenance)
        else:
            new_si = SpecialInspection(
                id=sid,
                inspection_type=t,
                provenance=FieldProvenance(
                    source="operator_declared", confidence="high", status="confirmed",
                    last_confirmed_by=user_id, last_confirmed_at=ts,
                ),
            )
            m.special_inspections.append(new_si)
            si_by_id[sid] = new_si

    # Zones by id → confirm.
    zone_by_id = {z.id: z for z in m.zones}
    for zid in req.zone_ids:
        z = zone_by_id.get(zid)
        if z is None:
            raise ValueError(f"Unknown zone id '{zid}'")
        _stamp(z.provenance)

    m.special_inspections = sorted(m.special_inspections, key=lambda s: s.id)
    m.zones = sorted(m.zones, key=lambda z: z.id)
    return m


def unconfirmed_view(model: ProjectModel) -> Dict[str, Any]:
    """The 'needs review' queue: every field still status='proposed'."""
    scalars = []
    for f in PLAN_DERIVED_SCALARS:
        prov = model.field_provenance.get(f)
        if prov is not None and prov.status == "proposed":
            scalars.append({
                "field": f,
                "value": getattr(model, f),
                "provenance": prov.model_dump(mode="json"),
            })
    return {
        "project_id": model.project_id,
        "scalars": scalars,
        "special_inspections": [
            si.model_dump(mode="json")
            for si in model.special_inspections
            if si.provenance.status == "proposed"
        ],
        "zones": [
            z.model_dump(mode="json")
            for z in model.zones
            if z.provenance.status == "proposed"
        ],
    }


# ── Persistence (db is passed in, per repo convention) ───────────────
def _model_to_doc(model: ProjectModel) -> Dict[str, Any]:
    return model.model_dump(mode="python")


def _doc_to_model(doc: Dict[str, Any]) -> ProjectModel:
    data = {k: v for k, v in doc.items() if k != "_id"}
    return ProjectModel(**data)


async def _load_pages(db, project_id: str) -> List[Dict[str, Any]]:
    rows = await db.document_page_index.find(
        {"project_id": project_id}
    ).to_list(length=10000)
    for r in rows:
        r["_id"] = str(r.get("_id"))
    return rows


async def load_project_model(db, project_id: str) -> Optional[ProjectModel]:
    doc = await db.project_models.find_one({"project_id": project_id})
    return _doc_to_model(doc) if doc else None


async def _persist(db, model: ProjectModel) -> None:
    # Upsert only — one current model per project. Never drop.
    await db.project_models.update_one(
        {"project_id": model.project_id},
        {"$set": _model_to_doc(model)},
        upsert=True,
    )


async def aggregate_project_model(
    db, project_id: str, *, now: Optional[datetime] = None,
) -> ProjectModel:
    pages = await _load_pages(db, project_id)
    existing = await load_project_model(db, project_id)
    model = build_project_model(project_id, pages, existing=existing, now=now)
    await _persist(db, model)
    return model


async def confirm_project_model(
    db, project_id: str, req: ModelConfirmRequest, *,
    user_id: str, now: Optional[datetime] = None,
) -> Optional[ProjectModel]:
    existing = await load_project_model(db, project_id)
    if existing is None:
        return None
    updated = apply_confirm(existing, req, user_id=user_id, now=now)
    await _persist(db, updated)
    return updated
