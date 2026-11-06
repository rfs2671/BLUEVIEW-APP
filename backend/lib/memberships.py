"""Company memberships: one person, many companies.

A membership is {user_id, company_id, role, pm_access, assigned_projects,
status}. `pm_access` and `assigned_projects` together are the membership's
project scope, under the names the users document already gives them, so the
code that reads a principal today reads a membership the same way.

-- WHAT THIS STAGE IS -------------------------------------------------------

A MIRROR, AND NOTHING READS IT. The users document is still the source of
truth: every user with a company_id has exactly one membership, copied from
that document by `plan_mirror`, and the server re-runs the copy at startup and
on a timer. No request, job or screen reads this collection yet, so nothing a
person can do or see changes. The next stage moves the reads over, and the
mirror is what makes that move checkable: the collection it starts reading is
already, provably, what the users documents say.

THE COPY MUST GO WHEN THE READS ARRIVE. Once memberships are the source of
truth, re-copying from the users documents would undo them: a person who left
a company still has that company_id on their users document, so the next run
would set the membership back to "active". Stage 2 removes the startup and
hourly runs of the mirror in the same change that moves the reads, with a test
that a left membership stays left.

-- WHY NOTHING IS DELETED --------------------------------------------------

A membership whose user is soft-deleted, moved to another company, or gone
from the users collection is set to status "removed", never deleted. A
soft-deleted user can be restored (the owner portal does it), and the mirror
then sets the same row back to "active". A row nobody needs any more costs
nothing; a deleted row a restore needed is a person who lost a company.
"""

from __future__ import annotations

from typing import Iterable, Optional

COLLECTION = "memberships"

STATUS_ACTIVE = "active"
STATUS_REMOVED = "removed"

#: Marks the rows this stage writes. The next stage writes rows of its own
#: (an admin adding an existing person); a row with this origin is one the
#: users document still owns.
ORIGIN_USERS_MIRROR = "users_mirror"

#: The users fields a membership copies. Projection for the mirror's read.
USER_FIELDS = ("company_id", "role", "pm_access", "assigned_projects", "is_deleted")

#: What a mirror row holds besides its key. Compared to decide whether a write
#: is needed, so a re-run over unchanged users writes nothing.
_COMPARED = ("role", "pm_access", "assigned_projects", "status")


def _id(value) -> str:
    return str(value) if value is not None else ""


def expected_from_user(user: dict) -> Optional[dict]:
    """The one membership a users document implies, or None (no company)."""
    company_id = _id((user or {}).get("company_id")).strip()
    user_id = _id((user or {}).get("_id") or (user or {}).get("id"))
    if not company_id or not user_id:
        return None
    projects = (user or {}).get("assigned_projects")
    return {
        "user_id": user_id,
        "company_id": company_id,
        "role": (user or {}).get("role"),
        "pm_access": (user or {}).get("pm_access"),
        "assigned_projects": [str(p) for p in projects] if isinstance(projects, list) else [],
        "status": STATUS_REMOVED if (user or {}).get("is_deleted") else STATUS_ACTIVE,
    }


def _differs(have: dict, want: dict) -> bool:
    return any(have.get(k) != want.get(k) for k in _COMPARED)


def plan_mirror(users: Iterable[dict], memberships: Iterable[dict]) -> list[dict]:
    """The writes that make `memberships` mirror `users`.

    Each write is {"key": {"user_id", "company_id"}, "set": {...},
    "insert": bool}; the caller applies it as an upsert on the key. Only rows
    of ORIGIN_USERS_MIRROR are ended here: a membership the next stage creates
    is not this mirror's to end.
    """
    have = {}
    for m in memberships:
        have[(_id(m.get("user_id")), _id(m.get("company_id")))] = m

    want = {}
    for u in users:
        row = expected_from_user(u)
        if row:
            want[(row["user_id"], row["company_id"])] = row

    writes = []
    for key, row in want.items():
        current = have.get(key)
        if current is None or _differs(current, row):
            writes.append({
                "key": {"user_id": key[0], "company_id": key[1]},
                "set": {k: row[k] for k in _COMPARED} | {"origin": ORIGIN_USERS_MIRROR},
                "insert": current is None,
            })

    # A mirror row the users no longer imply: the user changed company, lost
    # it, or is gone. Ended, not deleted (module docstring).
    for key, current in have.items():
        if key in want or current.get("origin") != ORIGIN_USERS_MIRROR:
            continue
        if current.get("status") != STATUS_REMOVED:
            writes.append({
                "key": {"user_id": key[0], "company_id": key[1]},
                "set": {"status": STATUS_REMOVED},
                "insert": False,
            })
    return writes


def parity(users: Iterable[dict], memberships: Iterable[dict]) -> dict:
    """How far the collection is from the users documents: 0 when mirrored.

    Counted over the same inputs `plan_mirror` reads, so after a run that
    applied every write it must be zero; anything else is a write that did not
    land.
    """
    pending = plan_mirror(users, memberships)
    return {
        "missing": sum(1 for w in pending if w["insert"]),
        "stale": sum(1 for w in pending if not w["insert"]),
    }
