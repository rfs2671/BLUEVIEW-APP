"""ProjectResponse defaults project_class to "regular" — by ruling.

THIS FILE REPLACES test_project_response_class_null.py, which pinned the
opposite. That file was not wrong when it was written, and the reasoning is
kept here because the boundary between the two positions is the whole point:

    THEN: an absent project_class meant "nobody assessed this §3310
    classification". Defaulting it to "regular" made the API assert an
    assessment nobody had made, and shipped it beside
    classification_source="unassessed" — one response, two contradictory
    answers, nothing to say which a consumer should believe.

    NOW: the operator has ruled that a project STARTS regular and an admin
    changes it when the project changes — foundation complete, now Major A.
    Regular is a real starting value, not a guess, so an absent key is not an
    unanswered question; it is a project nobody has needed to reclassify.

WHAT THE DEFAULT REACHES, verified rather than assumed. It fires only on an
ABSENT key. Both write paths always SET the key (create at server.py:9646-9670,
update at :9822-9829) and the create form now always sends a class, so exactly
one population is left: legacy documents written before the classification
model landed.

WHAT IT DOES NOT REACH — asserted below, because this was the one live concern
raised against the change. Every get_required_logbooks caller reads
`project.get("project_class")` off the RAW MONGO DOCUMENT, never off this model.
So the fail-closed logbook rule still sees a legacy project as unassessed and
still gives it the FULL logbook set. This default changes what the API says, not
what the compliance rule decides.

Run:  python -m pytest backend/tests/test_project_response_class_default.py -q
"""
import inspect

import server


BASE = {"id": "p1", "name": "N", "address": "A", "company_id": "c1"}


def test_absent_key_serialises_as_regular():
    """The ruling, in one assertion."""
    r = server.ProjectResponse(**BASE)
    assert r.project_class == "regular"


def test_an_assessed_class_is_still_carried():
    """The default must not overwrite a real classification."""
    for cls in sorted(server.VALID_PROJECT_CLASSES):
        r = server.ProjectResponse(**BASE, project_class=cls)
        assert r.project_class == cls, f"{cls} was lost in serialisation"


def test_an_explicit_null_still_survives_as_null():
    """A DEFAULT IS NOT A COERCION. The field stays Optional and an explicit
    None passes through untouched — the default only fills an ABSENT key.

    This matters because the update path can still write None (`suggested` is
    None when there was nothing to measure), and a model that silently rewrote
    that to "regular" would be inventing an answer at serialisation time rather
    than defaulting one. If that null should become regular, it is a write-path
    decision and a backfill, not a serialisation side effect.
    """
    assert server.ProjectResponse(**BASE, project_class=None).project_class is None


def test_the_payload_and_the_assessed_flag_agree_for_the_default():
    """The old file's coherence test, re-pointed.

    Its complaint was that the payload could say "regular" while
    classification_assessed said no. Under the ruling the two now AGREE for the
    defaulted case: regular is a real class, so a payload carrying it reads as
    assessed, which is what the operator says it is.
    """
    payload = server.ProjectResponse(**BASE).model_dump()
    assert payload["project_class"] == "regular"
    assert server.classification_assessed(payload), (
        "the default must read as a real class, or it reintroduces the "
        "contradiction from the other direction"
    )


def test_the_fail_closed_logbook_rule_is_untouched_by_this_default():
    """THE ONE CONCERN RAISED AGAINST THIS CHANGE, tested rather than argued.

    If get_required_logbooks ever read the SERIALISED class, a legacy project
    would flip onto the `assessed` branch and get a NARROWED logbook set — a
    compliance behaviour change arrived at through a serialisation default.

    It does not. The callers read the raw document, where the key is still
    absent. Asserted two ways: the rule's own behaviour on an absent class, and
    the call sites' source.
    """
    # Behaviour: an absent/None class still takes the unassessed branch, which
    # skips the class filter and yields the FULL set.
    full = server.get_required_logbooks(None, {})
    narrowed = server.get_required_logbooks("regular", {})
    assert len(full) >= len(narrowed), (
        "an unassessed project must be over-covered, never under-covered"
    )
    assert set(narrowed) <= set(full)

    # Source: no caller passes a ProjectResponse-derived class.
    src = inspect.getsource(server)
    for marker in (
        'get_required_logbooks(project_class, project)',
        'get_required_logbooks(project.get("project_class"), project)',
    ):
        assert marker in src, f"expected raw-document read {marker!r} is gone"
