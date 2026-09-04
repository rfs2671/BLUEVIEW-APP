"""The collision is load-bearing, and now something enforces the note.

`server.py`'s `GET /checkin/{project_id}/{tag_id}` and `card_audit`'s
`GET /checkin/{project_id}/{gate_id}` are the same method and the same shape.
server.py registers first, so its handler wins and card_audit's gate page never
serves.

WHAT THAT HOLDS UP. nfcHelper.buildCheckinUrl writes
`{baseUrl}/checkin/{projectId}/{tagId}` onto every physical NFC tag. Those tags
are on fences and cannot be rewritten remotely. Which side of the collision
wins decides what a worker sees when he taps one — and until 2026-09-04 neither
file mentioned the other.

This is the inverse of "a comment citing code as precedent goes stale
silently": there, a comment nothing enforces. Here, ENFORCEMENT NOTHING
COMMENTS. Both are a dependency with no check on it; this one was invisible.

Run:  python -m pytest backend/tests/test_gate_route_collision_is_documented.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SERVER_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
CA_SRC = (_BACKEND / "card_audit.py").read_text(encoding="utf-8")
NFC_SRC = (_BACKEND.parent / "frontend" / "src" / "utils" / "nfcHelper.js").read_text(
    encoding="utf-8")


def _routes():
    out = []
    for r in server.app.routes:
        p = getattr(r, "path", "")
        if p.startswith("/checkin") or p.startswith("/enrollment"):
            out.append((p, sorted(getattr(r, "methods", []) or [])))
    return out


# ── THE COLLISION IS REAL, MEASURED OFF THE LIVE ROUTE TABLE ──────────────

def test_server_registers_the_two_segment_checkin_route_first():
    """Not asserted from source order — read off the router FastAPI will
    actually match against."""
    paths = [p for p, _ in _routes()]
    a = paths.index("/checkin/{project_id}/{tag_id}")
    b = paths.index("/checkin/{project_id}/{gate_id}")
    assert a < b, (
        "card_audit's gate page now wins the collision. Every deployed NFC tag "
        f"resolves to it instead of checkin.html. order={paths}"
    )


def test_the_posts_on_the_gate_router_are_not_shadowed():
    """Recorded as a fact rather than a wish: four of six gate_router routes
    are reachable, and parse_card spends money on a paid vision API."""
    reachable = {p for p, m in _routes() if "POST" in m}
    for p in ("/checkin/submit", "/checkin/sign",
              "/enrollment/parse_card", "/enrollment/complete"):
        assert p in reachable, p


def test_the_tag_url_shape_is_the_colliding_one():
    """If buildCheckinUrl ever stops writing this shape, the collision stops
    being load-bearing and both comments should be revisited."""
    assert "/checkin/${projectId}/${tagId}" in NFC_SRC, (
        "the NFC tag URL shape changed — re-read both collision comments"
    )


# ── AND BOTH FILES SAY SO ─────────────────────────────────────────────────

def test_both_routes_carry_the_collision_note():
    """The point of the comments is that someone EDITING EITHER ROUTE sees it.
    A followups entry would not have been read by that person."""
    for name, src, marker in (
        ("server.py", SERVER_SRC, "THIS ROUTE SHADOWS card_audit.gate_router"),
        ("card_audit.py", CA_SRC, "THIS ROUTE IS SHADOWED BY server.py"),
    ):
        assert marker in src, f"{name} lost its collision note"
        assert "If you change one, change both." in src, name


def test_each_note_names_the_physical_dependency():
    for name, src in (("server.py", SERVER_SRC), ("card_audit.py", CA_SRC)):
        assert "buildCheckinUrl" in src, f"{name}: the note stopped naming the tags"
        assert "cannot be rewritten remotely" in src, name


def test_the_card_audit_note_warns_against_the_obvious_wrong_fix():
    """Unmounting the router to close the parse_card exposure deletes the only
    writer of worker_enrollments while a merge in server.py reads it. That was
    a live proposal on 2026-09-04, reversed on this evidence."""
    assert "DO NOT UNMOUNT THIS ROUTER" in CA_SRC
    assert "worker_enrollments" in CA_SRC
