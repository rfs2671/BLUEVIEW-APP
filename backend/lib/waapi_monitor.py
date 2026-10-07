"""Is the WaAPI instance connected? The pure state machine.

The bot is one WhatsApp-Web session. When it disconnects — phone offline,
session logged out, QR re-scan needed — every group and every direct message
goes silent, and nothing in the product says so. This turns a status reading
every 15 minutes into at most two emails per incident: one when it goes down,
one when it comes back.

── FLAPPING ────────────────────────────────────────────────────────────────

One bad reading does not open an incident. DOWN_AFTER consecutive non-ready
readings do, so a single slow poll or WaAPI hiccup does not email anybody.
A single ready reading closes an open incident.

── WHAT COUNTS AS DOWN ──────────────────────────────────────────────────────

`ready` (case-insensitive) is up. Any other instance status — qr, loading,
disconnected, booting — is down. A reading that could not be taken at all
(WaAPI unreachable, 5xx) is `unknown`, and unknown counts toward DOWN_AFTER
too: from the crew's side, an unreachable gateway is a silent bot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

UP, DOWN, UNKNOWN = "up", "down", "unknown"
DOWN_AFTER = 2

ACTION_NONE = "none"
ACTION_ALERT_DOWN = "alert_down"
ACTION_ALERT_RECOVERED = "alert_recovered"

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
         detail: str = "") -> Tuple[Dict[str, Any], str]:
    """Advance the monitor. Returns (new_state, action)."""
    s = dict(state or {})
    s.setdefault("status", UP)
    s.setdefault("consecutive_bad", 0)
    s["last_reading"] = reading
    s["last_detail"] = detail
    s["last_checked_at"] = now

    if reading == UP:
        s["consecutive_bad"] = 0
        if s["status"] == DOWN:
            s["status"] = UP
            s["recovered_at"] = now
            return s, ACTION_ALERT_RECOVERED
        return s, ACTION_NONE

    s["consecutive_bad"] = int(s.get("consecutive_bad") or 0) + 1
    if s["status"] == UP and s["consecutive_bad"] >= DOWN_AFTER:
        s["status"] = DOWN
        s["incident_id"] = uuid.uuid4().hex
        s["down_since"] = now
        s["recovered_at"] = None
        return s, ACTION_ALERT_DOWN
    return s, ACTION_NONE
