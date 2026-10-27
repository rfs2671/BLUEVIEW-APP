"""THE ANSWER LOG: one immutable row per answer the bot gives. Pure: no
database handle. server._answer_log_write is its ONLY writer and it only ever
inserts; tests/test_answer_log.py fails on any update / delete / replace of
the collection anywhere in the backend.

WHY. whatsapp_dm_answers (the DM log) is written by the DM paths only; a group
answer and an app answer were stored nowhere but in the chat itself, and no
row anywhere kept the record text the model was actually shown. An answer
cannot be audited against what it was built from unless that is kept, as it
was, next to the words that went out.

A ROW (surface dm | group | app):
  question, final_text      as asked / as sent (phone runs cut to the last 4)
  user_id, company_id, project_ids
  asker_last4               a group asker's phone: the last 4 digits only
  records                   [{id, sheet, file_id, page_id, page, kind, text}]:
                            the plan records the model was shown, `text` the
                            quote as the model saw it (_render_records_for_model:
                            whitespace folded, 400 chars). A message source
                            (project history) keeps its id and a hash, never
                            somebody else's words.
  tools                     [{tool, args, result}] what each tool returned to the
                            model; a tool that returns chat messages keeps
                            only result_sha256 / result_chars
  gates                     what the checks decided, as the check exposes it
                            (the plan gate exposes one outcome per answer, not
                            a decision per claim: see `gates` in the report)
  model, code_sha, path, timing, created_at
  content_hash              sha256 over the row's content (everything above)

NO PHONE IN FULL: every string in the row goes through `redact`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

COLLECTION = "answer_log"
SURFACES = ("dm", "group", "app")

#: Tools whose results are other people's chat messages: their words are not
#: kept, only a hash and the length (the answer's own text is kept as sent).
MESSAGE_TOOLS = frozenset({"search_project_history", "recent_voice_notes"})

MAX_TEXT = 4000
MAX_RECORDS = 60
MAX_TOOLS = 20
RECORD_TEXT = 400               # what _render_records_for_model shows the model
TOOL_RESULT = 3000

_PHONE_RUN = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_PHONE_KEYS = ("worker_phone", "phone", "chat_id", "sender")


def last4(v: Any) -> Optional[str]:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-4:] if len(d) >= 4 else None


def _cut(m: "re.Match") -> str:
    d = re.sub(r"\D", "", m.group(0))
    return f"[…{d[-4:]}]" if len(d) >= 7 else m.group(0)


def redact(v: Any) -> Any:
    """Every phone-like run of 7+ digits becomes its last 4; a key that holds
    a phone or a chat id is dropped."""
    if isinstance(v, str):
        return _PHONE_RUN.sub(_cut, v)
    if isinstance(v, (list, tuple)):
        return [redact(x) for x in v]
    if isinstance(v, dict):
        return {str(k): redact(x) for k, x in v.items() if k not in _PHONE_KEYS}
    return v


def _text(v: Any, n: int = MAX_TEXT) -> str:
    return redact(str(v or "")[:n])


def _sha(v: Any) -> str:
    return hashlib.sha256(str(v or "").encode("utf-8")).hexdigest()


def record_snapshot(r: Dict[str, Any]) -> Dict[str, Any]:
    """One plan record as the model was shown it."""
    quote = re.sub(r"\s+", " ", str(r.get("quote") or r.get("text") or "")).strip()[:RECORD_TEXT]
    row = {"id": str(r.get("_id") or r.get("id") or r.get("record_id") or "") or None,
           "sheet": r.get("sheet_number") or None,
           "file_id": str(r.get("file_id") or "") or None,
           "page_id": str(r.get("page_id") or "") or None,
           "page": r.get("page_number"),
           "kind": r.get("record_type") or r.get("kind") or None,
           "text": redact(quote)}
    return {k: v for k, v in row.items() if v not in (None, "")}


def records_snapshot(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The records, deduplicated by id (else by sheet+text), at most MAX_RECORDS."""
    out, seen = [], set()
    for r in records or []:
        if not isinstance(r, dict):
            continue
        snap = record_snapshot(r)
        key = snap.get("id") or (snap.get("sheet"), snap.get("page"), snap.get("text"))
        if key in seen:
            continue
        seen.add(key)
        out.append(snap)
        if len(out) >= MAX_RECORDS:
            break
    return out


def source_snapshot(s: Dict[str, Any]) -> Dict[str, Any]:
    """A project-history source (somebody's message, a daily report): where it
    is and a hash of its words -- never the words themselves."""
    row = {"id": str(s.get("source_id") or s.get("id") or s.get("sid") or "") or None,
           "sid": s.get("sid"), "kind": s.get("source") or None,
           "day": s.get("day_label") or s.get("when") or None,
           "text_sha256": _sha(s.get("text")), "text_chars": len(str(s.get("text") or ""))}
    return {k: v for k, v in row.items() if v not in (None, "")}


def tools_snapshot(trace: Any) -> List[Dict[str, Any]]:
    """What each tool returned to the model. A non-list (a headcount's own
    tool data, a dict) is kept as one entry."""
    if trace is None:
        return []
    if not isinstance(trace, list):
        return [{"tool": None, "data": redact(trace)}]
    out = []
    for t in trace[:MAX_TOOLS]:
        if not isinstance(t, dict):
            continue
        name = t.get("tool")
        row: Dict[str, Any] = {"tool": name, "args": redact(t.get("args") or {})}
        result = str(t.get("result") or "")
        if name in MESSAGE_TOOLS:
            row.update(result_sha256=_sha(result), result_chars=len(result))
        else:
            row["result"] = _text(result, TOOL_RESULT)
        for k in ("round", "ms", "error", "duplicate"):
            if t.get(k) is not None:
                row[k] = t[k]
        out.append(row)
    return out


def _canon(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


#: The fields the hash covers: the row's content, never _id or the hash.
HASHED = ("surface", "question", "final_text", "user_id", "company_id", "project_ids",
          "asker_last4", "group_id", "records", "tools", "gates", "model", "code_sha",
          "path", "timing", "features", "params", "created_at")


def content_hash(row: Dict[str, Any]) -> str:
    body = {k: _canon(row.get(k)) for k in HASHED}
    return _sha(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str))


def project_ids(*ids: Any) -> List[str]:
    out: List[str] = []
    for v in ids:
        for x in (v if isinstance(v, (list, tuple, set)) else [v]):
            if x and str(x) not in out:
                out.append(str(x))
    return out


def diff(logged: Dict[str, Any], now: Dict[str, Any]) -> Dict[str, Any]:
    """A logged answer against the same question answered again now: the
    final text (a unified diff), the records (by id, else sheet+text) and
    the gate decisions."""
    import difflib

    def keys(rows: Sequence[Dict[str, Any]]) -> List[str]:
        return [str(r.get("id") or f"{r.get('sheet') or ''}|{r.get('text') or ''}") for r in rows or []]
    a, b = str(logged.get("final_text") or ""), str(now.get("final_text") or "")
    was, is_ = keys(logged.get("records") or []), keys(now.get("records") or [])
    gates_was = _canon(logged.get("gates") or [])
    gates_now = _canon(now.get("gates") or [])
    return {
        "text_same": a == b,
        "text_diff": "\n".join(difflib.unified_diff(
            a.splitlines(), b.splitlines(), "logged", "now", lineterm="")),
        "records_same": was == is_,
        "records_only_logged": [k for k in was if k not in is_],
        "records_only_now": [k for k in is_ if k not in was],
        "gates_same": gates_was == gates_now,
        "gates_logged": gates_was,
        "gates_now": gates_now,
    }
