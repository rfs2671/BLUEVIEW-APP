"""Pure-logic tests for the ProjectModel aggregator (no DB, no HTTP).

Covers derivation, plan-seeded proposals, the operator-confirm transform,
merge safety, and determinism. DB round-trips + endpoints are covered in
test_project_model_endpoints.py.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from app.scheduling.project_model import (  # noqa: E402
    ModelConfirmRequest,
    ScalarConfirm,
    SPECIAL_INSPECTION_VOCAB,
)
from app.scheduling.aggregator import (  # noqa: E402
    apply_confirm,
    build_project_model,
    unconfirmed_view,
)

FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _page(pid, **kw):
    base = {
        "_id": pid, "project_id": "proj1", "is_spec_page": False,
        "discipline": None, "floor": None, "sheet_title": None, "summary": None,
        "notes": None, "materials": None, "spaces": None, "code_refs": None,
    }
    base.update(kw)
    return base


# ── Plan-derived scalars ─────────────────────────────────────────────
def test_has_gas_true_with_evidence_low_when_sparse():
    m = build_project_model("proj1", [_page("p1", notes="Natural gas riser to roof")], now=FIXED_NOW)
    assert m.has_gas is True
    prov = m.field_provenance["has_gas"]
    assert prov.source == "plan_derived"
    assert prov.evidence_page_ids == ["p1"]
    assert prov.confidence == "low"  # single page → sparse


def test_has_gas_high_confidence_multiple_pages():
    pages = [
        _page("p1", notes="fuel gas piping"),
        _page("p2", sheet_title="GAS RISER DIAGRAM"),
        _page("p3", discipline="AR", notes="floor plan"),
    ]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    assert m.has_gas is True
    prov = m.field_provenance["has_gas"]
    assert prov.confidence == "high"
    assert prov.evidence_page_ids == ["p1", "p2"]


def test_sprinkler_and_standpipe_from_sp_discipline_code():
    pages = [_page("p1", discipline="SP"), _page("p2", discipline="AR"), _page("p3", discipline="AR")]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    assert m.has_sprinkler is True
    assert m.has_standpipe is True  # SP covers both
    assert m.field_provenance["has_sprinkler"].confidence == "high"  # discipline hit
    assert m.has_elevator is False  # no elevator signal


def test_floors_max_distinct_with_evidence():
    pages = [_page("p1", floor="1"), _page("p2", floor="2ND FLOOR"), _page("p3", floor="LEVEL 5")]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    assert m.floors == 5
    fp = m.field_provenance["floors"]
    assert fp.evidence_page_ids == ["p3"]
    assert fp.confidence == "high"


def test_floors_low_confidence_when_sparse():
    m = build_project_model("proj1", [_page("p1", floor="3")], now=FIXED_NOW)
    assert m.floors == 3
    assert m.field_provenance["floors"].confidence == "low"


def test_spec_pages_ignored():
    pages = [
        _page("p1", is_spec_page=True, notes="gas gas gas sprinkler elevator"),
        _page("p2", floor="2"),
    ]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    # spec page's text must not create evidence
    assert m.has_gas is False
    assert m.field_provenance["has_gas"].evidence_page_ids == []


# ── Plan-seeded special inspections ──────────────────────────────────
def test_special_inspections_proposed_low_from_notes():
    pages = [
        _page("p1", notes="Provide firestopping at all penetrations; special inspection required."),
        _page("p2", code_refs="Structural steel welding and high-strength bolting per BC 1705"),
        _page("p3", notes="Sprinkler system; comply with NYCECC energy code"),
    ]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    types = {si.inspection_type for si in m.special_inspections}
    assert {"firestopping", "structural_welding", "structural_bolting",
            "sprinkler", "energy_nycecc"} <= types
    for si in m.special_inspections:
        assert si.provenance.status == "proposed"   # NEVER confirmed on aggregation
        assert si.provenance.confidence == "low"
        assert si.provenance.source == "plan_seeded"
        assert si.provenance.evidence_page_ids
        assert si.inspection_type in SPECIAL_INSPECTION_VOCAB
        assert si.id == f"si_{si.inspection_type}"
    ids = [si.id for si in m.special_inspections]
    assert ids == sorted(ids)


# ── Zones ────────────────────────────────────────────────────────────
def test_zones_default_single_all_floors():
    pages = [_page("p1", floor="1"), _page("p2", floor="2"), _page("p3", floor="3")]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    assert len(m.zones) == 1
    z = m.zones[0]
    assert z.id == "zone_all"
    assert z.floors == [1, 2, 3]
    assert z.is_tco_phase is False
    assert z.provenance.status == "proposed"


def test_zones_from_phasing_callouts():
    pages = [
        _page("p1", floor="1", notes="Phase 1 work; TCO for floors 1-2"),
        _page("p2", floor="2", notes="Phase 2 work"),
        _page("p3", floor="3", summary="phase 1 general note"),
    ]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    assert [z.id for z in m.zones] == ["zone_phase_1", "zone_phase_2"]
    assert all(z.is_tco_phase for z in m.zones)


# ── Operator confirm ─────────────────────────────────────────────────
def test_apply_confirm_sets_confirmed_and_stamps_without_mutating_input():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    stamp = datetime(2026, 2, 2, tzinfo=timezone.utc)
    req = ModelConfirmRequest(
        scalars=[ScalarConfirm(field="has_gas", value=True), ScalarConfirm(field="floors", value=10)],
        special_inspection_ids=["si_firestopping"],
    )
    out = apply_confirm(m, req, user_id="u1", now=stamp)
    assert out.has_gas is True and out.floors == 10
    for f in ("has_gas", "floors"):
        assert out.field_provenance[f].status == "confirmed"
        assert out.field_provenance[f].last_confirmed_by == "u1"
        assert out.field_provenance[f].last_confirmed_at == stamp
    si = next(s for s in out.special_inspections if s.id == "si_firestopping")
    assert si.provenance.status == "confirmed"
    # input untouched
    assert m.field_provenance["has_gas"].status == "proposed"
    assert m.special_inspections[0].provenance.status == "proposed"


def test_apply_confirm_unknown_type_rejected():
    m = build_project_model("proj1", [_page("p1"), _page("p2"), _page("p3")], now=FIXED_NOW)
    with pytest.raises(ValueError):
        apply_confirm(m, ModelConfirmRequest(special_inspection_types=["not_a_real_type"]),
                      user_id="u1", now=FIXED_NOW)


def test_apply_confirm_operator_declared_type_added():
    m = build_project_model("proj1", [_page("p1"), _page("p2"), _page("p3")], now=FIXED_NOW)
    out = apply_confirm(m, ModelConfirmRequest(special_inspection_types=["mechanical"]),
                        user_id="u2", now=FIXED_NOW)
    si = next(s for s in out.special_inspections if s.id == "si_mechanical")
    assert si.provenance.source == "operator_declared"
    assert si.provenance.status == "confirmed"


def test_apply_confirm_wrong_scalar_type_rejected():
    m = build_project_model("proj1", [_page("p1"), _page("p2"), _page("p3")], now=FIXED_NOW)
    with pytest.raises(ValueError):
        apply_confirm(m, ModelConfirmRequest(scalars=[ScalarConfirm(field="floors", value=True)]),
                      user_id="u1", now=FIXED_NOW)


# ── Merge safety (critical) ──────────────────────────────────────────
def test_merge_never_downgrades_or_overwrites_confirmed():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    v1 = build_project_model("proj1", pages, now=FIXED_NOW)
    # Operator overrides floors=99 and forces has_sprinkler=False (against the SP page).
    confirmed = apply_confirm(
        v1,
        ModelConfirmRequest(
            scalars=[ScalarConfirm(field="floors", value=99),
                     ScalarConfirm(field="has_sprinkler", value=False)],
            special_inspection_ids=["si_firestopping"],
        ),
        user_id="u1", now=FIXED_NOW,
    )
    # Re-aggregate the SAME pages with the confirmed model as the prior state.
    v2 = build_project_model("proj1", pages, existing=confirmed,
                             now=datetime(2026, 3, 3, tzinfo=timezone.utc))
    assert v2.floors == 99                                    # operator value kept
    assert v2.field_provenance["floors"].status == "confirmed"
    assert v2.has_sprinkler is False                          # override survives re-agg
    assert v2.field_provenance["has_sprinkler"].status == "confirmed"
    si = next(s for s in v2.special_inspections if s.id == "si_firestopping")
    assert si.provenance.status == "confirmed"               # SI not downgraded
    # Still-proposed fields keep refreshing.
    assert v2.field_provenance["has_standpipe"].status == "proposed"


def test_merge_adds_new_proposals_on_reaggregate():
    v1 = build_project_model("proj1", [_page("p1", floor="1"), _page("p2"), _page("p3")], now=FIXED_NOW)
    v2 = build_project_model(
        "proj1",
        [_page("p1", floor="1"), _page("p2", notes="masonry special inspection"), _page("p3")],
        existing=v1, now=FIXED_NOW,
    )
    assert any(si.id == "si_masonry" for si in v2.special_inspections)


# ── Determinism ──────────────────────────────────────────────────────
def test_determinism_same_pages_same_model():
    pages = [_page("p2", notes="sprinkler"), _page("p1", floor="3"), _page("p3", notes="firestopping")]
    a = build_project_model("proj1", pages, now=FIXED_NOW)
    b = build_project_model("proj1", list(reversed(pages)), now=FIXED_NOW)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# ── Unconfirmed queue ────────────────────────────────────────────────
def test_unconfirmed_view_lists_only_proposed():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    m = build_project_model("proj1", pages, now=FIXED_NOW)
    m2 = apply_confirm(
        m,
        ModelConfirmRequest(scalars=[ScalarConfirm(field="has_gas", value=False)],
                            special_inspection_ids=["si_firestopping"]),
        user_id="u1", now=FIXED_NOW,
    )
    view = unconfirmed_view(m2)
    scalar_fields = {s["field"] for s in view["scalars"]}
    assert "has_gas" not in scalar_fields          # confirmed → excluded
    assert "floors" in scalar_fields               # still proposed
    assert "si_firestopping" not in {si["id"] for si in view["special_inspections"]}
