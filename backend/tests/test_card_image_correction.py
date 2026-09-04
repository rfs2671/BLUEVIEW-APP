"""A worker photographed his face instead of his SST card, and the record kept it.

TWO DEFECTS, AND THE SECOND IS THE ONE THAT MATTERED.

The gate accepted the image. That is a data-quality problem and it queues
behind the OCR chain. What made it a RETENTION problem is that nothing could
undo it:

  * the write was ONCE-ONLY -- `if osha_card_image and not worker.get(
    "osha_card_image")` -- so scanning the correct card afterwards did nothing.
    The worker's record could never hold his actual credential.
  * `workers` is on SOFT_DELETE_NEVER_PURGE, so the row is never hard-deleted.
  * removing the `certifications[]` row does not touch the image, which is a
    sibling field.
  * and the image is served inline by GET /checkins/project/{id}/flagged to
    every CP review screen on the project, as the credential being judged.

So a photograph of a man's face was retained indefinitely under a certification
key with no path to remove it. This tests the two halves of the remedy.

Run:  python -m pytest backend/tests/test_card_image_correction.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

FACE = "data:image/jpeg;base64,/9j/FACE"
CARD = "data:image/jpeg;base64,/9j/REALCARD"
# FROM THE VOCABULARY, NEVER A LITERAL. The first draft of this file used
# "SST_WORKER", which is not a type this codebase has ever produced. It is not
# in RECOGNIZED_SST_TYPES, so every fixture built with it fell down the "no SST
# cert on file" branch -- and three tests about PROTECTING a verified card were
# quietly exercising the case where there is nothing to protect. The assertion
# below is the cheap tell: a fixture whose subject is a classification must
# prove it lands in the class.
SST = sorted(server.SST_CLASS_TYPES)[0]
assert SST in server.RECOGNIZED_SST_TYPES, (
    "the fixture type must be one the gate actually recognises, or these "
    f"tests measure the wrong branch: {SST!r}"
)


def _w(image=None, certs=None):
    w = {"_id": "x", "name": "A Worker"}
    if image is not None:
        w["osha_card_image"] = image
    w["certifications"] = list(certs or [])
    return w


def _sst(**over):
    c = {"type": SST, "expiration_date": "2027-01-01",
         "needs_review": False, "verified": False}
    c.update(over)
    return c


may = server.card_image_may_be_replaced


# ── THE CASE THAT BROUGHT THIS ────────────────────────────────────────────

def test_a_face_is_replaceable_because_it_produced_no_sst_cert():
    """A photograph of a face yields no SST certification. There is nothing on
    that record worth protecting from a correction."""
    assert may(_w(image=FACE, certs=[]), CARD) is True


def test_a_flagged_card_is_replaceable():
    assert may(_w(image=FACE, certs=[_sst(needs_review=True)]), CARD) is True


def test_a_card_with_no_expiry_is_replaceable():
    assert may(_w(image=FACE, certs=[_sst(expiration_date=None)]), CARD) is True


# ── WHAT MUST STILL BE PROTECTED ──────────────────────────────────────────

def test_a_verified_card_is_never_replaced():
    """`build_worker_certifications` refuses to let a re-scan modify a verified
    row -- "admin-confirmed". The image it was read from gets the same
    treatment, or the record shows one card's data beside another's photo."""
    assert may(_w(image=CARD, certs=[_sst(verified=True)]), FACE) is False


def test_a_verified_card_wins_even_beside_a_flagged_one():
    w = _w(image=CARD, certs=[_sst(needs_review=True), _sst(verified=True)])
    assert may(w, FACE) is False


def test_a_clean_unflagged_card_is_left_alone():
    assert may(_w(image=CARD, certs=[_sst()]), FACE) is False


# ── THE ORIGINAL BEHAVIOUR, UNCHANGED ─────────────────────────────────────

def test_nothing_stored_still_writes():
    assert may(_w(image=None, certs=[]), CARD) is True


def test_no_new_image_never_blanks_what_is_on_file():
    """The returning-worker quick check-in sends no card evidence at all."""
    for empty in (None, "", 0):
        assert may(_w(image=CARD, certs=[_sst()]), empty) is False
        assert may(_w(image=None, certs=[]), empty) is False


# ── THE ERASER ────────────────────────────────────────────────────────────

def test_the_removal_endpoint_exists_and_is_admin_and_tenant_gated():
    routes = {r.path: r for r in server.app.routes if hasattr(r, "path")}
    path = "/api/workers/{worker_id}/osha-card-image"
    assert path in routes, sorted(p for p in routes if "osha-card" in p)
    assert "DELETE" in routes[path].methods
    # BY NAME, OFF THE DEPENDANT TREE, NOT OUT OF A repr().
    #
    # This read `str(route.dependant.dependencies)` and substring-matched it.
    # That repr is 3,242 characters of nested Dependant/ModelField objects
    # whose text is a FastAPI + Pydantic version artifact: it passed locally
    # and failed in CI on the same code, reporting "an admin" about an
    # endpoint that has always had one. A representation is not a structure --
    # the same bet as a character window or a line number, and it lost the
    # same way. Walk the tree and read `__name__`.
    def _dep_names(dep, out=None):
        out = set() if out is None else out
        for d in dep.dependencies:
            call = getattr(d, "call", None)
            if call is not None:
                out.add(getattr(call, "__name__", ""))
            _dep_names(d, out)
        return out

    names = _dep_names(routes[path].dependant)
    assert names, "read no dependencies at all off the route"
    assert "get_admin_user" in names, f"an admin: {sorted(names)}"
    assert "require_worker_write_access" in names,         f"and THIS worker's admin: {sorted(names)}"


def test_the_removal_unsets_one_field_and_never_deletes_the_row():
    """The worker row carries check-in history that is statutory evidence.
    Removing a photograph is not a reason to touch it."""
    import inspect
    src = inspect.getsource(server.remove_worker_osha_card_image)
    assert '"$unset": {"osha_card_image": ""}' in src
    assert "delete_one" not in src and "delete_many" not in src
    assert '"is_deleted"' not in src
    assert "certifications" not in src.split('"""')[2], \
        "the eraser must not touch certifications[]"


# ── IS IT CALLED? ─────────────────────────────────────────────────────────
#
# THE FIRST DRAFT OF THIS FILE DID NOT ASK. Every test above drives
# card_image_may_be_replaced directly, so reverting the CALL SITE back to
# `if osha_card_image and not worker.get("osha_card_image")` left all ten
# green -- a correct function nobody invokes, which is a shape this codebase
# has already recorded three times in one week. A predicate is only a fix at
# the point something asks it.

def test_the_gate_actually_asks_the_predicate():
    import ast
    import inspect
    import textwrap
    src = inspect.getsource(server.register_and_checkin)
    # `register_and_checkin` is module-level, so its source is already at
    # column 0. An earlier version of this line dedented every indented line
    # by four spaces "to be safe" and produced a SyntaxError, which the
    # assertion below then reported as "the predicate is not called". A check
    # that cannot read its subject says the same thing as a check whose
    # subject is genuinely wrong, and only one of those is a defect.
    tree = ast.parse(textwrap.dedent(src))
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "card_image_may_be_replaced" in called, (
        "register_and_checkin decides the card image itself again. The "
        "predicate can be perfect and the write-once bug is still shipping."
    )


def test_the_old_write_once_guard_is_gone_from_the_gate():
    """Named separately from the call check because they fail for different
    reasons: one says the new rule is not consulted, this says the old one is
    still there. Both could be true at once."""
    import inspect
    src = inspect.getsource(server.register_and_checkin)
    assert 'not worker.get("osha_card_image")' not in src, (
        "the write-once guard is back in the check-in path"
    )
