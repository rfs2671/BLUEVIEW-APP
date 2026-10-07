"""WhatsApp tenant boundary and webhook authentication — the pure half.

Everything here is synchronous and imports no database driver, so the rules can
be tested without a server and read without a server in your head.

── THE INVARIANT ─────────────────────────────────────────────────────────────

    WhatsApp group -> company -> project

The group record names a company and a project. That pair is trusted only after
the project document itself has been read back WITH that company id in the
filter. A group whose pair cannot be established conclusively — no row, two
rows that disagree, an empty company, an empty project — gets no project answer
and no project post. There is no tie-break: picking "the likely company" out of
two is exactly the guess that puts one customer's site in another's chat.

── SECURITY EVENTS CARRY IDS, NEVER CONTENT ──────────────────────────────────

`security_event_payload` keeps an allow-list of identifier fields. A message
body, a plan excerpt, a token or a header value cannot reach the log through it
even if a caller passes one, because unknown keys are dropped, not escaped.
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

# Statuses `classify_group_rows` can return.
GROUP_OK = "ok"
GROUP_UNLINKED = "unlinked"
GROUP_DUPLICATE = "duplicate"
GROUP_INVALID = "invalid"

# A webhook secret shorter than this is treated as unset. 32 bytes is the
# floor the operator set; `secrets.token_urlsafe(32)` produces 43 characters.
WEBHOOK_SECRET_MIN_BYTES = 32

# The query-string key WaAPI sends the secret under. WaAPI has no signature or
# custom-header option for webhooks (its SDK's updateInstance takes only a URL
# and an event list), so the secret has to ride in the URL it calls.
WEBHOOK_TOKEN_PARAM = "token"

# What the bot says in a group whose ownership cannot be established. It names
# nothing: no project, no company, no reason that would tell a stranger which
# tenant the group was almost bound to.
GROUP_UNAVAILABLE_TEXT = (
    "This group isn't available on Levelog right now. "
    "An administrator needs to review its connection.\n\n"
    "Este grupo no está disponible en Levelog en este momento. "
    "Un administrador debe revisar su conexión."
)

# What a tool returns when its project cannot be proven to belong to the
# group's company. The agent sees this instead of data.
BOT_SCOPE_REFUSAL = (
    "This project isn't available here. / "
    "Este proyecto no está disponible aquí."
)

_SECURITY_EVENT_FIELDS = (
    "company_id", "project_id", "wa_group_id", "user_id",
    "caller_company_id", "project_company_id", "other_company_id",
    "companies", "projects", "row_count", "reason", "remote_addr",
)


def _id(v: Any) -> str:
    return str(v or "").strip()


def classify_group_rows(rows: Iterable[dict]) -> Tuple[str, Optional[dict], str]:
    """Decide what the ACTIVE whatsapp_groups rows for one wa_group_id mean.

    Returns (status, row, reason). `row` is set only for GROUP_OK.

    - No rows: unlinked.
    - Any row missing its company or its project: invalid. "" and None are
      the same absence (see _same_company_or_403 in server.py for why).
    - Rows naming more than one (company, project) pair: duplicate. This
      covers two companies, and one company with two projects for a group
      that may bind to exactly one.
    - Several rows naming the SAME pair are one binding written twice; the
      first is used. That is not ambiguous about whose data it is.
    """
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return GROUP_UNLINKED, None, "no_active_row"
    for r in rows:
        if not _id(r.get("company_id")) or not _id(r.get("project_id")):
            return GROUP_INVALID, None, "row_missing_company_or_project"
    pairs = {(_id(r.get("company_id")), _id(r.get("project_id"))) for r in rows}
    if len(pairs) > 1:
        companies = {c for c, _ in pairs}
        reason = ("multiple_companies" if len(companies) > 1
                  else "multiple_projects")
        return GROUP_DUPLICATE, None, reason
    return GROUP_OK, rows[0], "ok"


def same_company(a: Any, b: Any) -> bool:
    """Both present and equal as strings. An absent side never matches."""
    a, b = _id(a), _id(b)
    return bool(a) and bool(b) and a == b


def webhook_secret_usable(secret: Optional[str]) -> bool:
    return len((secret or "").encode("utf-8")) >= WEBHOOK_SECRET_MIN_BYTES


def webhook_token_ok(provided: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time comparison. An unusable configured secret rejects every
    caller: an integration that cannot authenticate its sender must not fall
    back to trusting it."""
    if not webhook_secret_usable(expected):
        return False
    if not provided:
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"), (expected or "").encode("utf-8"))


def redact_query_param(text: str, param: str = WEBHOOK_TOKEN_PARAM) -> str:
    """Replace the value of `param=` anywhere in a URL-ish string."""
    if not text or f"{param}=" not in text:
        return text
    out = []
    i = 0
    key = f"{param}="
    while True:
        j = text.find(key, i)
        if j < 0:
            out.append(text[i:])
            break
        # Only a real parameter boundary: start, '?', '&' or ';'.
        if j > 0 and text[j - 1] not in "?&;":
            out.append(text[i:j + len(key)])
            i = j + len(key)
            continue
        out.append(text[i:j + len(key)])
        out.append("[redacted]")
        k = j + len(key)
        while k < len(text) and text[k] not in "& \"'":
            k += 1
        i = k
    return "".join(out)


def security_event_payload(kind: str, **fields: Any) -> Dict[str, Any]:
    """The record a security event is logged as. Unknown keys are dropped."""
    out: Dict[str, Any] = {
        "event": str(kind),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for k in _SECURITY_EVENT_FIELDS:
        if k in fields and fields[k] is not None:
            v = fields[k]
            if isinstance(v, (list, tuple, set)):
                v = sorted(_id(x) for x in v)
            elif not isinstance(v, (int, float, bool)):
                v = _id(v)
            out[k] = v
    return out


def format_security_event(kind: str, **fields: Any) -> str:
    return "[security-event] " + json.dumps(
        security_event_payload(kind, **fields), sort_keys=True)


# ── THE INDEX THAT SHOULD EVENTUALLY ENFORCE THIS, NOT BUILT ───────────────
#
# One active binding per WhatsApp group, enforced by the database. It is NOT
# created here or at startup: building a unique index over live rows that
# already violate it fails, and the rows have to be looked at by a person
# before anything decides which binding is real. Data first, then this.
#
#   db.whatsapp_groups.createIndex(
#       { wa_group_id: 1 },
#       { name: "whatsapp_groups_one_active_binding",
#         unique: true,
#         partialFilterExpression: { active: true } }
#   )
PROPOSED_UNIQUE_INDEX = {
    "keys": [("wa_group_id", 1)],
    "name": "whatsapp_groups_one_active_binding",
    "unique": True,
    "partialFilterExpression": {"active": True},
}
