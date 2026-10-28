"""ANSWER CORRECTIONS: the operator's "Mark wrong" on a logged answer. Pure:
no database handle. server._answer_correction_write is the ONLY writer and it
only ever inserts; tests/test_answer_corrections.py fails on any update /
delete / replace of the collection anywhere in the backend.

WHY. This collection is the input feed for the self-learning work (built in
another session): each row is one answer the operator says was wrong, what
it should have said, and exactly which build and model gave the wrong one.
It is the operator's alone: customers do not flag answers, and nothing here
is ever shown to or sent to a customer.

APPEND-ONLY. A correction is never edited or removed. Correcting the same
answer again is a new row; the newest row for an answer is the current
correction, and every earlier one stays (readers order by `ts`). Every write
is also its own audit_logs row ("answer_correction").

SCHEMA (collection `answer_corrections`, schema_version 1):
  _id                 str     a new ObjectId, as a string
  schema_version      int     1
  answer_log_id       str     the answer_log row corrected (its _id)
  question            str     the question, as answer_log kept it
  wrong_answer        str     the answer as sent (answer_log.final_text)
  correct_answer      str     what it should have said (required, operator)
  note                str|None  the operator's note (optional)
  project_ids         [str]   answer_log.project_ids (may be empty)
  project_id          str|None  the one project when there is exactly one
  company_id          str     answer_log.company_id
  surface             str     dm | group | app
  code_sha            str|None  the build that gave the wrong answer
  model               str|None  the model that gave it
  answer_created_at   datetime  when the wrong answer was given
  answer_content_hash str|None  answer_log.content_hash of the row corrected,
                                so a reader can check it corrects THAT row
  operator_id         str     who marked it wrong
  ts                  datetime  when it was marked wrong (UTC)
  content_hash        str     sha256 over every field above but _id

NO PHONE IN FULL: every string goes through answer_log.redact (a phone-like
run of 7+ digits becomes its last 4), as the answer log itself does.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from lib import answer_log

COLLECTION = "answer_corrections"
SCHEMA_VERSION = 1

MIN_CORRECT = 2
MAX_CORRECT = answer_log.MAX_TEXT
MAX_NOTE = 2000

#: The fields content_hash covers, in this order.
HASHED = ("schema_version", "answer_log_id", "question", "wrong_answer", "correct_answer",
          "note", "project_ids", "project_id", "company_id", "surface", "code_sha",
          "model", "answer_created_at", "answer_content_hash", "operator_id", "ts")


def _clean(v: Any, n: int) -> str:
    return answer_log.redact(str(v or "").strip()[:n])


def check(correct_answer: Any, note: Any = None) -> Optional[str]:
    """None when the correction can be written; else what is wrong with it."""
    text = " ".join(str(correct_answer or "").split())
    if len(text) < MIN_CORRECT:
        return "a correct answer is required"
    if len(str(correct_answer or "")) > MAX_CORRECT:
        return f"the correct answer is over {MAX_CORRECT} characters"
    if note is not None and len(str(note)) > MAX_NOTE:
        return f"the note is over {MAX_NOTE} characters"
    return None


def _canon(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def content_hash(doc: Dict[str, Any]) -> str:
    body = {k: _canon(doc.get(k)) for k in HASHED}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def build(row: Dict[str, Any], correct_answer: Any, note: Any, *, operator_id: Any,
          now: datetime, _id: str) -> Dict[str, Any]:
    """The correction row for one answer_log row (the caller checked it)."""
    pids = [str(p) for p in row.get("project_ids") or [] if p]
    note_text = _clean(note, MAX_NOTE) if note is not None else ""
    doc = {
        "_id": str(_id),
        "schema_version": SCHEMA_VERSION,
        "answer_log_id": str(row.get("_id")),
        "question": answer_log.redact(str(row.get("question") or "")),
        "wrong_answer": answer_log.redact(str(row.get("final_text") or "")),
        "correct_answer": _clean(correct_answer, MAX_CORRECT),
        "note": note_text or None,
        "project_ids": pids,
        "project_id": pids[0] if len(pids) == 1 else None,
        "company_id": str(row.get("company_id") or ""),
        "surface": row.get("surface"),
        "code_sha": row.get("code_sha"),
        "model": row.get("model"),
        "answer_created_at": row.get("created_at"),
        "answer_content_hash": row.get("content_hash"),
        "operator_id": str(operator_id or ""),
        "ts": now,
    }
    doc["content_hash"] = content_hash(doc)
    return doc


#: The text fields of a row (redacted on the way out, as at insert). Ids,
#: hashes and dates are never passed through redact: a sha256 or an
#: ObjectId can hold 7 digits in a row, and so does an ISO date.
TEXT_FIELDS = ("question", "wrong_answer", "correct_answer", "note")


def view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """A correction as the operator reads it (dates as ISO strings)."""
    out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in doc.items()
           if k != "_id"}
    for k in TEXT_FIELDS:
        if out.get(k) is not None:
            out[k] = answer_log.redact(out[k])
    out["id"] = str(doc.get("_id"))
    return out
