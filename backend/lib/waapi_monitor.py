"""Is the WaAPI instance connected? The pure state machine.

The bot is one WhatsApp-Web session. When it disconnects — phone offline,
session logged out, QR re-scan needed — every group and every direct message
goes silent, and nothing in the product says so. This turns a status reading
every 15 minutes into at most two emails per incident: one when it starts,
one when it ends.

── TWO TRACKS, NEVER MIXED ──────────────────────────────────────────────────

CONNECTION. Only a status actually read from WaAPI moves it. `ready`
(case-insensitive) is up; any other instance status — qr, loading,
disconnected, booting — is down. DOWN_AFTER consecutive down readings open a
"disconnected" incident; one up reading closes it.

READABILITY. A reading that could not be taken or understood — WaAPI
unreachable, an HTTP error, a status path that does not exist, a body with no
status field — is `unknown`. Unknown NEVER counts as disconnected: the status
path is not verified against WaAPI's docs, and a monitor that cries
"disconnected" because it is reading the wrong URL is worse than none.
Instead, UNREADABLE_AFTER consecutive unknowns open a separate "can't read
status" incident; the first readable reading (up or down) closes it.

An unknown reading leaves the connection track exactly as it was: it neither
adds to nor resets the down count, and it does not close a disconnected
incident.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

UP, DOWN, UNKNOWN = "up", "down", "unknown"
DOWN_AFTER = 2
UNREADABLE_AFTER = 2

ACTION_NONE = "none"
ACTION_ALERT_DOWN = "alert_down"
ACTION_ALERT_RECOVERED = "alert_recovered"
ACTION_ALERT_UNREADABLE = "alert_unreadable"
ACTION_ALERT_READABLE = "alert_readable"

CONNECTION_ACTIONS = frozenset({ACTION_ALERT_DOWN, ACTION_ALERT_RECOVERED})
READABILITY_ACTIONS = frozenset({ACTION_ALERT_UNREADABLE, ACTION_ALERT_READABLE})

READY_STATES = frozenset({"ready"})


def find_status(payload: Any, depth: int = 0) -> Optional[str]:
    """The instance status anywhere in a WaAPI response, or None.

    WaAPI has returned it as clientStatus.instanceStatus and as a top-level
    `instanceStatus`/`status` in different versions, so it is searched for
    rather than read from one path. A bare "success" is the envelope, not
    the instance, and is skipped."""
    if depth > 6 or payload is None:
        return None
    if isinstance(payload, dict):
        for key in ("instanceStatus", "instance_status", "clientStatus"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
        for v in payload.values():
            got = find_status(v, depth + 1)
            if got:
                return got
        v = payload.get("status")
        if isinstance(v, str) and v.strip() and v.strip().lower() not in (
                "success", "error", "ok"):
            return v.strip().lower()
    elif isinstance(payload, list):
        for v in payload[:10]:
            got = find_status(v, depth + 1)
            if got:
                return got
    return None


def classify(status: Optional[str]) -> str:
    if status is None:
        return UNKNOWN
    return UP if status.lower() in READY_STATES else DOWN


def step(state: Optional[Dict[str, Any]], reading: str, now: datetime,
         detail: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """Advance the monitor. Returns (new_state, actions); actions is empty
    when nothing changed and can hold one action per track."""
    s = dict(state or {})
    s.setdefault("status", UP)
    s.setdefault("consecutive_bad", 0)
    s.setdefault("readable", True)
    s.setdefault("consecutive_unknown", 0)
    s["last_reading"] = reading
    s["last_detail"] = detail
    s["last_checked_at"] = now
    actions: List[str] = []

    # Readability track.
    if reading == UNKNOWN:
        s["consecutive_unknown"] = int(s.get("consecutive_unknown") or 0) + 1
        if s["readable"] and s["consecutive_unknown"] >= UNREADABLE_AFTER:
            s["readable"] = False
            s["read_incident_id"] = uuid.uuid4().hex
            s["unreadable_since"] = now
            s["readable_again_at"] = None
            actions.append(ACTION_ALERT_UNREADABLE)
        return s, actions  # the connection track does not move on unknown
    s["consecutive_unknown"] = 0
    if not s["readable"]:
        s["readable"] = True
        s["readable_again_at"] = now
        actions.append(ACTION_ALERT_READABLE)

    # Connection track: only readings actually taken.
    if reading == UP:
        s["consecutive_bad"] = 0
        if s["status"] == DOWN:
            s["status"] = UP
            s["recovered_at"] = now
            actions.append(ACTION_ALERT_RECOVERED)
        return s, actions

    s["consecutive_bad"] = int(s.get("consecutive_bad") or 0) + 1
    if s["status"] == UP and s["consecutive_bad"] >= DOWN_AFTER:
        s["status"] = DOWN
        s["incident_id"] = uuid.uuid4().hex
        s["down_since"] = now
        s["recovered_at"] = None
        actions.append(ACTION_ALERT_DOWN)
    return s, actions
