"""Account deletion, and the attribution that has to survive it.

THE GUARANTEE THIS FILE EXISTS FOR. A filed 3301-02 signed by a man whose
account is gone still has to say who signed it. Two ways to get that wrong:

  blank it      -> the attestation is ORPHANED. A document asserting an
                   inspection was fine, signed by nobody. That is worse than
                   the problem deletion solves.
  bare name     -> implies a live account somebody could still ask about it.

So the record says both things: this man signed, and his account is gone. The
`deleted_user:` prefix is that second half, and the assertions below fail if a
deletion path ever writes a bare id or an empty string instead. The guarantee
must not rest on the deletion path remembering.

Run:  python -m pytest backend/tests/test_account_deletion.py -q
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


# ── the prefix itself ───────────────────────────────────────────────────────

def test_the_prefix_is_what_it_says():
    assert server.DELETED_USER_PREFIX == "deleted_user:"


def test_a_real_id_keeps_its_id_behind_the_prefix():
    """Prefixed, NOT replaced. The id is the link back to the account that
    signed; dropping it would anonymise the attestation, which is the other
    way of orphaning it."""
    ref = server.deleted_user_ref("6a5f63bc147407d3261df2c7")
    assert ref == "deleted_user:6a5f63bc147407d3261df2c7"


def test_it_is_never_bare():
    """THE POINT. A bare id or name reads as a live account."""
    for value in ("6a5f63bc147407d3261df2c7", "Michael Reyes", 12345):
        assert server.deleted_user_ref(value).startswith("deleted_user:")


def test_it_is_never_blank_even_when_the_id_is():
    """An id we cannot name still must not become an empty string: blank reads
    as NO SIGNER, which is exactly the orphaning this prevents."""
    for empty in (None, "", "   "):
        ref = server.deleted_user_ref(empty)
        assert ref == "deleted_user:unknown"
        assert ref.strip() != "deleted_user:"


def test_it_never_returns_something_falsy():
    for value in (None, "", 0, False, "x"):
        assert server.deleted_user_ref(value)


# ── one writer, so it cannot be forgotten ───────────────────────────────────

def test_the_soft_delete_payload_carries_the_ref():
    out = server._mark_user_deleted("abc123")
    assert out["deleted_user_ref"] == "deleted_user:abc123"
    assert out["is_deleted"] is True
    assert out["deleted_at"] is not None


def test_the_payload_does_not_touch_the_name():
    """`users` is in SOFT_DELETE_NEVER_PURGE, so the row survives and the name
    with it. That is what keeps signature_events.signer.user_id resolvable to
    a PERSON rather than to nothing."""
    out = server._mark_user_deleted("abc123")
    for forbidden in ("name", "full_name", "email"):
        assert forbidden not in out, forbidden


def test_EVERY_user_soft_delete_goes_through_that_one_writer():
    """THE ASSERTION THAT STOPS THIS ROTTING. If a future path soft-deletes a
    user with its own inline $set, it will not carry the prefix and the
    guarantee silently stops holding for the accounts it deletes."""
    # Bounded [\s\S], NOT [^)]: the update_one filter contains
    # to_query_id(...), so a )-terminated scan never reaches the $set and the
    # assertion passes on everything.
    inline = re.findall(
        r'db\.users\.update_one\([\s\S]{0,300}?"is_deleted":\s*True',
        SRC, re.S,
    )
    assert inline == [], (
        "a users soft-delete bypasses _mark_user_deleted: %r" % (inline,))
    # And the two known executing paths do use it.
    # The CALL, not the name: the explanatory comment above each call also
    # contains "_mark_user_deleted", so a bare-name check passes even after the
    # call itself is replaced by an inline $set.
    for fn in (server.delete_admin_user, server.delete_admin_account):
        assert '{"$set": _mark_user_deleted(' in inspect.getsource(fn), fn.__name__


def test_deletion_never_rewrites_a_signed_record():
    """It stamps the RETAINED user row. It must never edit
    signature_events.signer, which sits under a content_hash — editing evidence
    to record that its author left is a worse act than the one it documents."""
    for fn in (server.delete_admin_user, server.delete_admin_account,
               server.request_own_account_deletion):
        src = inspect.getsource(fn)
        for collection in ("db.signature_events", "db.logbooks",
                           "db.daily_logs", "db.checkins"):
            assert collection not in src, (fn.__name__, collection)


def test_the_compliance_collections_are_still_never_purged():
    """The retention half of the promise the copy makes to the user."""
    for name in ("logbooks", "signature_events", "checkins", "audit_logs",
                 "daily_signatures", "sign_ins", "users"):
        assert '"%s"' % name in SRC


# ── the request path ────────────────────────────────────────────────────────

def test_a_request_is_recorded_not_executed():
    """Apple 5.1.1(v) wants an in-app path, not an immediate one. A CP with
    unsynced signed logbooks must DRAIN before his access ends, and only a
    person can confirm that happened."""
    src = inspect.getsource(server.request_own_account_deletion)
    assert "deletion_requested_at" in src
    assert "is_deleted" not in src, "a request must not delete anything"


def test_the_request_is_auditable():
    assert 'audit_log("account_deletion_requested"' in SRC
    assert 'audit_log("account_deletion_withdrawn"' in SRC


def test_it_can_be_withdrawn():
    """A request he cannot take back is a trap, not a choice."""
    src = inspect.getsource(server.withdraw_own_account_deletion)
    assert "$unset" in src and "deletion_requested_at" in src


def test_a_shared_site_device_is_not_somebodys_account():
    src = inspect.getsource(server.request_own_account_deletion)
    assert 'role") == "site_device"' in src
    assert "site_mode" in src


def test_workers_have_no_deletion_path_because_they_have_no_account():
    """A worker has no password, no email, no username, and no login path
    reads db.workers — only db.users and db.site_devices authenticate. He never
    created an account, so 5.1.1(v) does not reach him, and a worker record is
    a compliance record about a man who checked in."""
    fields = set(server.WorkerCreate.model_fields)
    assert not fields & {"password", "email", "username"}
    assert "db.workers.find_one" not in inspect.getsource(server.login)
