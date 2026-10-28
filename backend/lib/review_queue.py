"""THE REVIEW QUEUE (L6 step 3: the feed only). Pure: no database handle.

Uncertain findings, queued for the platform operator's review queue (L6.4:
operator-gated routes and the web screen, approve / deny with an
explanation -- not built here). This step only INSERTS items:
server._review_queue_add is the one writer, nothing changes a row, and no
person is ever shown one.

ONE COLLECTION, `review_queue`, for the auto-queued kinds below. A dispute
(a person saying an answer is wrong) stays where L6.2 put it, in
`answer_disputes`, with its own one-row-per-(answer, person) key; L6.4 lists
both collections side by side, and KIND_DISPUTE is reserved here so the
screen has one vocabulary.

KINDS (the producers, each in server.py):
  conflicting_sources   an answer whose checks refused or doubted it: the
                        plan answer gate replaced it (ungrounded, label_leak,
                        no_records_refused) or overturned its refusal from the
                        sheet (refusal_overturned); a plan record it was shown
                        is contested ("(readings disagree)"); the DM brain
                        stopped on a claim it could not verify. Queued from
                        _answer_log_write, so every surface is covered and the
                        item names its answer_log row.
  set_health            one item per set-health finding of a glyph pass
                        (lib/plan_set_health), queued from _write_set_health.
                        A clean set and "not assessed" are no finding.
  registration_refusal  a START refused for a person the system knows (and so
                        knows the company of): wrong phone for the code, no
                        phone on the profile, a phone shared by two accounts,
                        a role that may not use the assistant.
  plan_set_question     a set-membership question for the PM (L7, PR #889).
                        #889 is not on main: from_plan_set_question and
                        server._review_queue_plan_set_question are the hook it
                        calls when it lands; nothing on main produces one yet.

A ROW:
  _id               sha256 of kind|company|subject key: the same finding
                    queued twice is a duplicate key, one row
  kind, company_id, project_id, answer_log_id (when the item is an answer)
  summary           one line, phone runs cut to the last 4 (answer_log.redact)
  evidence          record ids, sheets, outcomes, short quotes of the plan
                    records -- never anybody's chat words
  created_at
  status            "pending". Written once, at insert; nothing in this step
                    changes it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from lib import answer_log

COLLECTION = "review_queue"
STATUS_PENDING = "pending"

KIND_DISPUTE = "dispute"                    # lives in answer_disputes (L6.2)
KIND_CONFLICTING_SOURCES = "conflicting_sources"
KIND_SET_HEALTH = "set_health"
KIND_REGISTRATION_REFUSAL = "registration_refusal"
KIND_PLAN_SET_QUESTION = "plan_set_question"
KINDS = (KIND_DISPUTE, KIND_CONFLICTING_SOURCES, KIND_SET_HEALTH,
         KIND_REGISTRATION_REFUSAL, KIND_PLAN_SET_QUESTION)
#: The kinds this collection holds (a dispute is answer_disputes' row).
QUEUED_KINDS = KINDS[1:]

#: Plan answer gate outcomes that are a refusal or a doubted answer.
#: "grounded" and "no_records" (nothing asserted) are not.
GATE_OUTCOMES = frozenset({"ungrounded", "label_leak", "no_records_refused",
                           "refusal_overturned"})
#: DM brain stops on a claim it could not check against what it was given.
DM_STOPS = frozenset({"unverified", "unsupported_claim"})
#: The cell text plan_ocr writes where two readings of one cell disagree.
CONTESTED_TEXT = "(readings disagree)"

#: Set-health kinds that are no finding.
HEALTHY = frozenset({"set_health_clean", "set_health_not_assessed"})

#: START refusals queued, by the reason _handle_dm_start gives.
REGISTRATION_REASONS = frozenset({"code_phone_mismatch", "phone_missing",
                                  "phone_shared", "ambiguous", "role_not_eligible"})

MAX_SUMMARY = 300
MAX_QUOTE = 160
MAX_EVIDENCE = 12


def _norm(v: Any) -> str:
    return " ".join(re.sub(r"[^\w\s'-]", " ", str(v or "").lower()).split())[:200]


def item_id(kind: str, company_id: Any, subject_key: Any) -> str:
    return hashlib.sha256(f"{kind}|{company_id}|{subject_key}".encode("utf-8")).hexdigest()


def item(kind: str, company_id: Any, subject_key: Any, *, summary: Any,
         evidence: Optional[Dict[str, Any]] = None, project_id: Any = None,
         answer_log_id: Any = None, now: datetime) -> Optional[Dict[str, Any]]:
    """The row. None without a company or with a kind this does not hold:
    an item belongs to one company's queue."""
    if kind not in QUEUED_KINDS or not company_id:
        return None
    return {
        "_id": item_id(kind, company_id, subject_key),
        "kind": kind,
        "company_id": str(company_id),
        "project_id": str(project_id) if project_id else None,
        "answer_log_id": str(answer_log_id) if answer_log_id else None,
        "summary": answer_log.redact(str(summary or "")[:MAX_SUMMARY]),
        "evidence": answer_log.redact(evidence or {}),
        "created_at": now,
        "status": STATUS_PENDING,
    }


# ── conflicting_sources ────────────────────────────────────────────────────

def contested(record: Dict[str, Any]) -> bool:
    """A plan record whose own reading is in doubt."""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if payload.get("count_contested") or record.get("glyph_status") == "contested":
        return True
    text = str(record.get("quote") or record.get("text") or "")
    return CONTESTED_TEXT in text


def from_answer(row: Dict[str, Any], raw_records: Iterable[Dict[str, Any]] = (), *,
                now: datetime) -> Optional[Dict[str, Any]]:
    """An answer_log row (as written) whose checks refused or doubted it, or
    whose shown records are contested. None: nothing uncertain."""
    if not row or not row.get("company_id"):
        return None
    reasons: List[str] = []
    subject = ""
    for g in row.get("gates") or []:
        if not isinstance(g, dict):
            continue
        if g.get("gate") == "plan_answer_gate" and g.get("outcome") in GATE_OUTCOMES:
            reasons.append(f"plan_gate:{g['outcome']}")
            subject = subject or str(g.get("subject") or "")
        elif str(g.get("gate") or "").startswith("dm_") and g.get("stop") in DM_STOPS:
            reasons.append(f"{g['gate']}:{g['stop']}")
    shown = [r for r in raw_records or [] if isinstance(r, dict)]
    disputed = [answer_log.record_snapshot(r) for r in shown if contested(r)]
    if disputed:
        reasons.append("records_contested")
    if not reasons:
        return None
    projects = sorted(str(p) for p in row.get("project_ids") or [])
    key = "|".join(projects) + "|" + _norm(subject or row.get("question"))
    sheets = sorted({str(r["sheet"]) for r in disputed if r.get("sheet")}) or sorted(
        {str(r["sheet"]) for r in row.get("records") or [] if r.get("sheet")})
    evidence = {
        "reasons": reasons,
        "surface": row.get("surface"),
        "path": row.get("path"),
        "subject": subject[:200] or None,
        "sheets": sheets[:MAX_EVIDENCE],
        "record_ids": [r["id"] for r in (disputed or row.get("records") or [])
                       if r.get("id")][:MAX_EVIDENCE],
        "quotes": [{"id": r.get("id"), "sheet": r.get("sheet"),
                    "text": str(r.get("text") or "")[:MAX_QUOTE]} for r in disputed][:MAX_EVIDENCE],
    }
    what = subject or "an answer"
    summary = (f"{', '.join(reasons)} on {what[:120]}"
               + (f" (sheets {', '.join(sheets[:4])})" if sheets else ""))
    return item(KIND_CONFLICTING_SOURCES, row["company_id"], key, summary=summary,
                evidence=evidence, project_id=projects[0] if len(projects) == 1 else None,
                answer_log_id=row.get("_id"), now=now)


# ── set_health ─────────────────────────────────────────────────────────────

def from_set_health(company_id: Any, project_id: Any, finding: Dict[str, Any], *,
                    now: datetime) -> Optional[Dict[str, Any]]:
    """One set-health finding of one project. None: a clean set, or not
    assessed (no finding)."""
    kind = str(finding.get("kind") or "")
    if not kind or kind in HEALTHY or not project_id:
        return None
    sheet, subject, track = finding.get("sheet"), finding.get("subject"), finding.get("track")
    key = f"{project_id}|{kind}|{track or ''}|{sheet or ''}|{subject or ''}"
    evidence = {"finding": kind, "sheet": sheet, "subject": subject, "track": track,
                "detail": str(finding.get("detail") or "")[:MAX_QUOTE] or None}
    summary = f"{kind}" + (f" on {sheet}" if sheet else "") + (
        f": {subject}" if subject and subject != sheet else "")
    return item(KIND_SET_HEALTH, company_id, key, summary=summary,
                evidence={k: v for k, v in evidence.items() if v not in (None, "")},
                project_id=project_id, now=now)


# ── registration_refusal ───────────────────────────────────────────────────

def from_registration(company_id: Any, user_id: Any, reason: str, *, chat: Any = None,
                      role: Any = None, now: datetime) -> Optional[Dict[str, Any]]:
    """A START refused for a known person of a known company. The chat is
    kept as its last 4 digits only."""
    if reason not in REGISTRATION_REASONS or not user_id:
        return None
    tail = answer_log.last4(chat)
    evidence = {"reason": reason, "user_id": str(user_id), "chat_last4": tail,
                "role": str(role) if role else None}
    summary = (f"START refused ({reason})"
               + (f" for a {role}" if role else "")
               + (f" from chat …{tail}" if tail else ""))
    return item(KIND_REGISTRATION_REFUSAL, company_id, f"{user_id}|{reason}",
                summary=summary,
                evidence={k: v for k, v in evidence.items() if v not in (None, "")},
                now=now)


# ── plan_set_question (L7, PR #889: the hook) ──────────────────────────────

def from_plan_set_question(company_id: Any, project_id: Any, question: Dict[str, Any], *,
                           now: datetime) -> Optional[Dict[str, Any]]:
    """One set-membership question for the PM (lib/plan_set_questions on
    #889: a question names its sheets and what each reading would change).
    Keyed by the question's own id (else its code)."""
    qid = question.get("_id") or question.get("id") or question.get("code")
    if not qid or not project_id:
        return None
    sheets = [str(s) for s in (question.get("sheets") or [])][:MAX_EVIDENCE]
    evidence = {"question_id": str(qid), "code": question.get("code"),
                "sheets": sheets or None,
                "readings": [str(r)[:MAX_QUOTE] for r in (question.get("readings") or [])][:4]
                or None}
    text = str(question.get("question") or question.get("text") or "set membership question")
    return item(KIND_PLAN_SET_QUESTION, company_id, f"{project_id}|{qid}",
                summary=text[:MAX_SUMMARY],
                evidence={k: v for k, v in evidence.items() if v not in (None, "")},
                project_id=project_id, now=now)
