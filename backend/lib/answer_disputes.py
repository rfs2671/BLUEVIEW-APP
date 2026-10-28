"""ANSWER DISPUTES (L6 step 2: capture only). Pure: no database handle.

A person who says a bot answer is wrong gets exactly one thing back:
"Flagged for review". Nothing else is ever shown to them: no status, no
approve / deny, no reviewer. Only the platform operator reviews a dispute
(L6.4: the /owner/review-queue routes, lib/review_queue's last section);
this module only records it.

A ROW in `answer_disputes`, one per (answer, person):
  _id               sha256 of answer_log_id + user_id: the same person
                    disputing the same answer twice is the same row (the
                    second insert is a duplicate key, and the reply is the same)
  answer_log_id     the disputed answer (an answer_log row of the SAME company)
  company_id, user_id, surface (dm | app)
  text              what they said, phone runs cut to the last 4 (answer_log.redact)
  created_at
  status            "pending" at insert. Changed once, by the operator's
                    decision only (server._review_decide, L6.4), to
                    "approved" or "denied" with `decision` beside it.

THE DETECTOR (is_dispute) is deliberately narrow: the whole message must be
a dispute ("that's wrong", "not right", "incorrect", "no it's not", "eso
está mal", "no es correcto"), optionally followed by a correction after a
punctuation mark ("that's wrong, it's 3'-6\""). A question is never a dispute
("is that right?", "what's wrong with the pump?"), nor is a sentence that
merely contains the word ("the wrong door was installed", "not right now").
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from lib import answer_log

COLLECTION = "answer_disputes"
REPLY = "Flagged for review"
STATUS_PENDING = "pending"
SURFACES = ("dm", "app")

#: A message with no reply-to disputes the last answer only this soon after it.
WINDOW_SECONDS = 10 * 60
#: A reply-to whose id is not on any row is matched by its words this far back.
QUOTE_LOOKBACK_SECONDS = 24 * 60 * 60
MAX_TEXT = 1000
MAX_CHARS = 240                 # a longer message is a conversation, not a dispute


def _norm(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("’", "'").replace("‘", "'").replace("'", "")
    return " ".join(t.split())


# Fillers a dispute may open with ("no, that's wrong", "nope incorrect").
_LEAD = r"(?:(?:no|nope|nah|um+|hm+|actually|sorry|eh|pues|oye)\b[\s,.!-]*)*"
_ADV = r"(?:(?:totally|completely|definitely|all|still|just|so|really|absolutely|clearly|simply" \
       r"|totalmente|completamente|todo)\s+)?"
_SUBJ_EN = (r"(?:(?:that|this|it|the answer|your answer|that answer|this answer)\s+(?:is|was)\s+"
            r"|thats\s+|its\s+|youre\s+|you are\s+|thats\s+just\s+)?")
_PHR_EN = (r"(?:wrong|incorrect|inaccurate|not right|not correct|not true|not accurate|false"
           r"|mistaken|a mistake|wrong answer|the wrong answer"
           r"|not what the (?:plans?|drawings?|sheets?) (?:says?|shows?))")
# "no it's not": only with the no in front ("it's not" alone is a sentence start).
_NOT_EN = r"(?:its not|it is not|it isnt|thats not|that is not|that isnt|thats not it|not it)"
_SUBJ_ES = r"(?:(?:eso|esto|esa respuesta|la respuesta)\s+)?(?:(?:esta|es|estas)\s+)?"
_PHR_ES = r"(?:mal|incorrect[oa]|equivocad[oa]|falso|erroneo|errado)"
_NO_ES = r"(?:(?:eso|esto)\s+)?no\s+es\s+(?:correcto|cierto|verdad|asi)|te equivocas"
# After the dispute: nothing, or a correction that starts at a punctuation mark.
_TAIL = r"(?:\s*[!.]*\s*$|\s*[,.;:!—–-].*$)"

_DISPUTE = re.compile(
    rf"^{_LEAD}(?:"
    rf"{_SUBJ_EN}{_ADV}{_PHR_EN}"
    rf"|{_SUBJ_ES}{_ADV}{_PHR_ES}"
    rf"|{_NO_ES}"
    rf")\s*{_TAIL}")
_NO_NOT = re.compile(rf"^(?:no|nope|nah)\b[\s,.!-]*{_NOT_EN}{_TAIL}")


def is_dispute(text: Any) -> bool:
    """The whole message says the answer is wrong (see the module docstring)."""
    raw = str(text or "").strip()
    if not raw or len(raw) > MAX_CHARS or "?" in raw or "¿" in raw:
        return False
    t = _norm(raw)
    return bool(_DISPUTE.match(t) or _NO_NOT.match(t))


#: DM paths whose logged text is the bot's own question or a marker, never
#: an answer ("Which job?", "[confirmed …]"): a "no it's not" answers them.
NOT_ANSWER_PATHS = frozenset({"clarify", "menu", "menu_expired", "brain_confirm",
                              "brain_command", "not_a_question", "walk_help"})


def disputable(row: Optional[Dict[str, Any]]) -> bool:
    """An answer, not the bot's own question ("Which job?") or a marker
    ("[cancelled]"): a "no it's not" to a question is an answer to it."""
    if not row or row.get("path") in NOT_ANSWER_PATHS:
        return False
    text = str(row.get("final_text") or "").strip()
    if not text or text.startswith("["):
        return False
    # One line that asks: the bot's question, not an answer.
    return not ("\n" not in text and text.endswith("?"))


def short_id(message_id: Any) -> str:
    """A WhatsApp id in its short form: replies quote the short one, and the
    serialized form ({fromMe}_{chat}_{id}) carries the chat -- a phone."""
    raw = str(message_id or "").strip()
    parts = raw.split("_")
    if len(parts) >= 3 and parts[0] in ("true", "false") and "@" in parts[1]:
        return parts[2]
    return raw


def sent_ids(resp: Any, _depth: int = 0) -> List[str]:
    """The id(s) of the message WaAPI says it sent (short form only), from
    wherever in its answer an id node sits ({"id": {"_serialized": ...}} or
    {"id": {"id": ..., "fromMe": true}}). [] when it gives none."""
    out: List[str] = []
    if _depth > 6:
        return out
    if isinstance(resp, dict):
        ser = resp.get("_serialized")
        if isinstance(ser, str) and ser.startswith("true_"):
            sid = short_id(ser)
            if sid:
                out.append(sid)
        elif resp.get("fromMe") is True and isinstance(resp.get("id"), str) and resp["id"]:
            out.append(resp["id"])
        for v in resp.values():
            if isinstance(v, (dict, list)):
                out.extend(sent_ids(v, _depth + 1))
    elif isinstance(resp, list):
        for v in resp:
            out.extend(sent_ids(v, _depth + 1))
    return list(dict.fromkeys(out))


def quote_matches(quoted_body: Any, row: Dict[str, Any]) -> bool:
    """A reply-to's words are this answer's (as it was logged)."""
    q = " ".join(answer_log.redact(str(quoted_body or "")).split())
    a = " ".join(str(row.get("final_text") or "").split())
    if len(q) < 8 or not a:
        return False
    return q[:300] in a or a[:300] in q


def dispute_id(answer_log_id: Any, user_id: Any) -> str:
    return hashlib.sha256(f"{answer_log_id}|{user_id}".encode("utf-8")).hexdigest()[:32]


def dispute_row(log_row: Dict[str, Any], *, user_id: Any, surface: str, text: Any,
                now: datetime) -> Dict[str, Any]:
    """The row for one person disputing one answer_log row (its company's)."""
    return {
        "_id": dispute_id(log_row["_id"], user_id),
        "answer_log_id": str(log_row["_id"]),
        "company_id": str(log_row.get("company_id")),
        "user_id": str(user_id),
        "surface": surface if surface in SURFACES else "dm",
        "text": answer_log.redact(str(text or "")[:MAX_TEXT]),
        "created_at": now,
        "status": STATUS_PENDING,
    }


def user_view() -> Dict[str, str]:
    """All a disputing user is ever shown."""
    return {"status": REPLY}


def ids(values: Iterable[Any]) -> List[str]:
    return [s for s in dict.fromkeys(short_id(v) for v in values or []) if s]
