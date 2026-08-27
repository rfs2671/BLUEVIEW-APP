"""registration_source: stamped once, never derived, never rewritten.

WHY A STAMPED FIELD. Apple 5.1.1(v) reaches accounts a person created for
themselves. On this product almost nobody does — owners are seeded, admins are
created by an owner, CPs by an admin, workers have no account at all — so the
deletion control belongs on self-registered accounts and nowhere else.

Every DERIVABLE signal for "self-registered" decays, and the assertions below
exist because one of them looked convincing:

  account_status == "pending"  the only writer is /auth/register, so it does
                               identify self-registration — until approval
                               flips it. The demo account MUST be approved to
                               be reviewable, so the signal disappears from the
                               single account it exists for.
  role == "owner"              POST /admin/users takes `role` from the request
                               body unconstrained, and the seeds create owners.
  company_id is None           /onboarding/company sets it on first use.
  onboarding_step present      exclusive today, but a side effect of an
                               unrelated feature.

THE DECIDING CASE: an approved admin is one field edit away from looking
self-registered, and the field that would do it is the one approval writes.

Run:  python -m pytest backend/tests/test_registration_source.py -q
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
SETTINGS = (_BACKEND.parent / "frontend" / "app" / "settings.jsx").read_text(
    encoding="utf-8")


# ── the values ──────────────────────────────────────────────────────────────

def test_the_three_sources_are_distinct():
    assert server.REG_SELF == "self_registered"
    assert server.REG_ADMIN == "created_by_admin"
    assert server.REG_SEED == "system_seed"
    assert len({server.REG_SELF, server.REG_ADMIN, server.REG_SEED}) == 3


def test_only_self_registered_passes_the_gate():
    assert server.is_self_registered({"registration_source": server.REG_SELF})
    for other in (server.REG_ADMIN, server.REG_SEED, "", "SELF_REGISTERED", None):
        assert not server.is_self_registered({"registration_source": other}), other


def test_absent_means_no():
    """Correct for every pre-marker account. The backfill then makes it
    explicit rather than leaving it to this default."""
    assert not server.is_self_registered({})
    assert not server.is_self_registered(None)


def test_it_is_not_derived_from_anything_mutable():
    """The whole point. A doc that looks self-registered by every decaying
    signal — pending, owner, no company — is still not self-registered."""
    looks_like_it = {
        "account_status": "pending",
        "role": "owner",
        "company_id": None,
        "onboarding_step": "1",
    }
    assert not server.is_self_registered(looks_like_it)


# ── who stamps what ─────────────────────────────────────────────────────────

def test_register_is_the_only_writer_of_self_registered():
    """If a second path starts writing REG_SELF, an account nobody registered
    gains a deletion control and the scoping silently stops holding."""
    writers = re.findall(
        r'registration_source"?\]?\s*[:=]\s*REG_SELF', SRC)
    assert len(writers) == 1, writers
    assert "REG_SELF" in inspect.getsource(server.register)


def test_the_client_cannot_claim_it():
    """Same discipline as role and company_id: forced server-side, never read
    back off the request body."""
    src = inspect.getsource(server.register)
    # The ASSIGNMENT line, not the first mention: the explanatory comment
    # above it also contains the field name, and matching that would be
    # testing the prose rather than the code.
    lines = [l for l in src.splitlines()
             if 'registration_source' in l and '=' in l
             and not l.strip().startswith('#')]
    assert len(lines) == 1, lines
    line = lines[0]
    assert 'REG_SELF' in line
    # Not read back off the request body, same discipline as role/company_id.
    assert 'user_data' not in line and '.get(' not in line


def test_every_other_creation_path_stamps_a_non_self_value():
    for fn in (server.create_admin_user, server.create_admin_with_company):
        assert "REG_ADMIN" in inspect.getsource(fn), fn.__name__
    # The startup seeds.
    assert SRC.count('"registration_source": REG_SEED') >= 4


def test_no_user_insert_is_left_unstamped():
    """A new creation path that forgets the field produces an account whose
    source is unknown — and `absent means no` would quietly deny it the
    control rather than failing loudly."""
    inserts = len(re.findall(r"db\.users\.insert_one", SRC))
    stamped = len(re.findall(r'"registration_source":\s*REG_|registration_source"\]\s*=\s*REG_', SRC))
    assert stamped >= inserts, (stamped, inserts)


# ── immutable afterwards ────────────────────────────────────────────────────

def test_nothing_updates_it():
    """IMMUTABLE. The value records a historical fact — how this account came
    to exist — and no later event can change it.

    COUNTED, not pattern-matched against $set. The first version of this looked
    for the field inside a literal `$set: {...}` and MISSED a rewrite added to
    `_mark_user_deleted`, whose dict is built in a helper and passed in by
    reference. Counting every assignment site catches a write wherever it is
    constructed:

        1  register            REG_SELF
        2  create_admin_user + create_admin_with_company   REG_ADMIN
        4  startup seeds       REG_SEED
    """
    sites = re.findall(
        r'"registration_source":\s*REG_[A-Z]+|\["registration_source"\]\s*=\s*REG_[A-Z]+',
        SRC)
    assert len(sites) == 7, (len(sites), sites)

    # And no update-shaped path mentions it at all.
    for fn in (server.update_admin_account, server.update_profile,
               server._mark_user_deleted, server.delete_admin_user):
        assert "registration_source" not in inspect.getsource(fn), fn.__name__


# ── the gate is on the server, not only the screen ──────────────────────────

def test_the_deletion_request_refuses_a_created_account():
    src = inspect.getsource(server.request_own_account_deletion)
    assert "is_self_registered" in src
    assert "created by your administrator" in src


def test_the_refusal_says_what_to_do_instead():
    """A dead end is worse than no control. It names who can remove it."""
    src = inspect.getsource(server.request_own_account_deletion)
    assert "Ask them to remove it" in src


def test_the_screen_reads_the_same_stamped_field():
    assert "user?.registration_source === 'self_registered'" in SETTINGS
    # And it is ANDed with the site-device check, not replacing it.
    assert "!siteMode && user?.registration_source === 'self_registered'" in SETTINGS


def test_auth_me_returns_the_field_so_the_client_can_read_it():
    """No new endpoint: /auth/me returns the user doc minus the password, so
    the stamped field reaches the client for free."""
    # BEHAVIOURAL. This asserted the SOURCE contained "password" and
    # "return user", which broke when get_me moved from `del user["password"]`
    # to a denylist comprehension -- a syntax pin failing on a correct change.
    # The claim is about what the endpoint RETURNS, so it is asserted on the
    # return value.
    import asyncio
    principal = {
        "id": "u1", "email": "a@b.c", "name": "A", "role": "cp",
        "registration_source": "self_serve",
        "password": "$2b$12$hash",
    }
    out = asyncio.run(server.get_me(current_user=principal))
    assert out["registration_source"] == "self_serve", (
        "the stamped field no longer reaches the client")
    assert "password" not in out, "the hash is being returned"
