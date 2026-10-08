"""WhatsApp group names, as people see them.

A group's name is its WhatsApp subject, read from WaAPI get-group-info and
stored on the row (`group_name`). The id (`1203…@g.us`) is an address, not a
name: nothing a person reads ever shows it. A group with no known subject is
shown as UNNAMED.
"""

from __future__ import annotations

import re
from typing import Any, Optional

UNNAMED = "Unnamed group"

# Retry a failed subject lookup no more often than this, per group.
NAME_RETRY_SECONDS = 60 * 60
# At most this many WaAPI lookups for one read of a list.
NAME_FETCH_LIMIT = 10

_RAW_ID_RE = re.compile(r"^\s*[\d-]+(@(g\.us|c\.us|lid|s\.whatsapp\.net))?\s*$",
                        re.IGNORECASE)


def is_real_name(name: Any) -> bool:
    """A subject a person typed — not empty, not a WhatsApp id."""
    s = str(name or "").strip()
    return bool(s) and "@g.us" not in s.lower() and not _RAW_ID_RE.match(s)


def display_name(name: Any) -> str:
    return str(name).strip() if is_real_name(name) else UNNAMED


def project_label(project: Optional[dict]) -> str:
    """How the bot names a job: its address. The project name only when no
    address is on file. Never the nickname."""
    p = project or {}
    for k in ("address", "location", "name"):
        v = str(p.get(k) or "").strip()
        if v:
            return v
    return "the project"
