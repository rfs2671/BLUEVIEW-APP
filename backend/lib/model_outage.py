"""The agent's model is down for a reason a person has to fix.

── WHAT WAS SILENT ─────────────────────────────────────────────────────────
#
# On 2026-10-26 the OpenAI account behind the WhatsApp agent ran out of
# credits: every call answered 429 insufficient_quota / credit_balance_
# exhausted. `_run_group_agent` logged "group agent error" and returned None,
# which its callers read as NOREPLY - so a superintendent who asked a
# question got nothing at all, and nobody was told.
#
# A rate limit or a 5xx passes; an empty balance or a revoked key does not,
# until someone acts. Those are the failures named here: the operators are
# told once an hour through the existing alert path, the log says so, and
# the person who asked is told plainly that the assistant is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

BILLING = "billing"
AUTH = "auth"

#: OpenAI's codes for "the account cannot pay" (error.type / error.code).
_BILLING_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted",
                            "billing_hard_limit_reached", "billing_not_active"})
#: ... and for "this key is not accepted".
_AUTH_CODES = frozenset({"invalid_api_key", "account_deactivated", "invalid_organization"})

UNAVAILABLE_REPLY = ("The Levelog assistant is temporarily unavailable, so I can't "
                     "answer that right now. The team has been told.")


def classify(status_code: int, body: Any) -> Optional[str]:
    """BILLING, AUTH, or None for any failure that is not one of them (a rate
    limit, a server error, a bad request) - those keep their old path."""
    err = (body or {}).get("error") if isinstance(body, dict) else None
    codes = set()
    if isinstance(err, dict):
        codes = {str(err.get(k) or "").strip().lower() for k in ("type", "code")} - {""}
    if codes & _BILLING_CODES:
        return BILLING
    if status_code == 401 or codes & _AUTH_CODES:
        return AUTH
    return None


def alert_key(kind: str, now: Optional[datetime] = None) -> str:
    """One alert per kind per clock hour (UTC): the notification id the
    existing alert path dedupes on."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"agent_model_down:{kind}:{now:%Y-%m-%dT%H}"


def alert_text(kind: str, status_code: int, body: Any, model: str) -> str:
    err = (body or {}).get("error") if isinstance(body, dict) else None
    code = (err or {}).get("code") or (err or {}).get("type") or "?"
    what = ("The OpenAI account has no credits or has hit its billing limit"
            if kind == BILLING else "OpenAI did not accept the API key")
    return (f"{what} (HTTP {status_code}, {code}). The WhatsApp assistant ({model}) "
            f"cannot answer: people who ask are told it is temporarily unavailable.\n\n"
            f"Fix: {'add credits at platform.openai.com > Billing' if kind == BILLING else 'check OPENAI_API_KEY on Railway'}. "
            f"This alert repeats at most once an hour while it lasts.")


__all__ = ["BILLING", "AUTH", "UNAVAILABLE_REPLY", "classify", "alert_key", "alert_text"]
