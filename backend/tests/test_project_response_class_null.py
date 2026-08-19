"""ProjectResponse must not invent a §3310 classification.

The model defaulted project_class to "regular", so a project document with NO
project_class key — the correct representation of "nobody assessed this" —
serialised to the client as a real class, alongside
classification_source="unassessed". One response, two contradictory answers.
"""
import server


BASE = {"id": "p1", "name": "N", "address": "A", "company_id": "c1"}


def test_absent_key_does_not_become_a_class():
    """The unassessed case. This is the whole bug: no key, real class out."""
    r = server.ProjectResponse(**BASE)
    assert r.project_class is None, (
        "an absent project_class serialised as a real class — the API asserted "
        "an assessment nobody made"
    )


def test_explicit_null_survives():
    """classify_project returns None when nothing was measured, and the write
    path always SETS the key. That null must reach the client as null."""
    assert server.ProjectResponse(**BASE, project_class=None).project_class is None


def test_an_assessed_class_is_still_carried():
    """The other direction — the fix must not erase a real classification."""
    for cls in sorted(server.VALID_PROJECT_CLASSES):
        r = server.ProjectResponse(**BASE, project_class=cls)
        assert r.project_class == cls, f"{cls} was lost in serialisation"


def test_the_serialised_payload_agrees_with_classification_assessed():
    """The two fields must never contradict each other.

    A response carrying project_class="regular" beside
    classification_source="unassessed" has no defined answer for which a
    consumer should believe. Asserted on the DUMPED payload, because that is
    what the client actually receives.
    """
    unassessed = server.ProjectResponse(**BASE).model_dump()
    assert unassessed["project_class"] is None
    assert not server.classification_assessed(unassessed), (
        "the payload reads as ASSESSED while nothing was assessed"
    )

    assessed = server.ProjectResponse(**BASE, project_class="major_a").model_dump()
    assert server.classification_assessed(assessed)


def test_the_default_is_not_reintroduced():
    """Behavioural, not a string check: construct with the key absent and
    assert nothing fills it in."""
    assert server.ProjectResponse.model_fields["project_class"].default is None
    assert server.ProjectResponse(**BASE).model_dump()["project_class"] is None
