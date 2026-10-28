"""THE REVIEW QUEUE (L6 step 3: the feed only). Pure: no database handle.

Uncertain findings, queued for the platform operator's review queue (L6.4:
operator-gated routes and the web screen, approve / deny with an
explanation -- not built here). This step only INSERTS items:
server._review_queue_add is the one writer, nothing changes a row, and no
person is ever shown one.

ONE COLLECTION, `review_queue`, for the auto-queued kinds below. Customers
do not flag answers: every item here comes from the system's own checks.

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
  plan_set_question     a set-membership question for the PM (PR #889,
                        lib/plan_set_questions): server._store_set_questions
                        queues each question it opens through
                        server._review_queue_plan_set_question.

A ROW:
  _id               sha256 of kind|company|subject key: the same finding
                    queued twice is a duplicate key, one row
  kind, company_id, project_id, answer_log_id (when the item is an answer)
  summary           one line, phone runs cut to the last 4 (answer_log.redact)
  evidence          record ids, sheets, outcomes, short quotes of the plan
                    records -- never anybody's chat words
  created_at
  reason            why it is queued (owner's ruling, L6.3): conflict |
                    replaced | unverified | set_health_failed |
                    set_health_info | registration | set_ambiguity (REASONS
                    below). A plan-set question is set_ambiguity (owner's
                    ruling: it replaces the earlier "conflict").
  priority          "low" for set_health_info, "normal" for everything else
                    (L6.4 lists pending items by status, priority, newest)
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

KIND_CONFLICTING_SOURCES = "conflicting_sources"
KIND_SET_HEALTH = "set_health"
KIND_REGISTRATION_REFUSAL = "registration_refusal"
KIND_PLAN_SET_QUESTION = "plan_set_question"
KINDS = (KIND_CONFLICTING_SOURCES, KIND_SET_HEALTH,
         KIND_REGISTRATION_REFUSAL, KIND_PLAN_SET_QUESTION)
#: The kinds this collection holds: all of them.
QUEUED_KINDS = KINDS

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
#: Set-health findings that are purely informational: recorded, refusing no
#: claim of their own (lib/plan_set_health: a prose mention is "recorded ...
#: never counted"; a schedule tag not located "refuses nothing else").
#: Every other kind -- set_health_unavailable, and any kind not named here --
#: is a failed check.
SET_HEALTH_INFO = frozenset({"mentioned_unlocated", "schedule_tag_not_located"})

# ── WHY AN ITEM IS QUEUED (reason), and its priority ───────────────────────
REASON_CONFLICT = "conflict"                # contested records, "readings disagree"
REASON_REPLACED = "replaced"                # the plan gate replaced / overturned it
REASON_UNVERIFIED = "unverified"            # the DM brain stopped on a claim
REASON_SET_HEALTH_FAILED = "set_health_failed"
REASON_SET_HEALTH_INFO = "set_health_info"
REASON_REGISTRATION = "registration"
REASON_SET_AMBIGUITY = "set_ambiguity"      # #889: which drawings belong to the set
REASONS = (REASON_CONFLICT, REASON_REPLACED, REASON_UNVERIFIED, REASON_SET_HEALTH_FAILED,
           REASON_SET_HEALTH_INFO, REASON_REGISTRATION, REASON_SET_AMBIGUITY)
#: An answer that hits several: the first of these wins.
ANSWER_PRECEDENCE = (REASON_CONFLICT, REASON_REPLACED, REASON_UNVERIFIED)
PRIORITY_LOW = "low"
PRIORITY_NORMAL = "normal"


def priority(reason: str) -> str:
    return PRIORITY_LOW if reason == REASON_SET_HEALTH_INFO else PRIORITY_NORMAL


def answer_reason(found: Iterable[str]) -> Optional[str]:
    """conflict > replaced > unverified."""
    found = set(found or ())
    return next((r for r in ANSWER_PRECEDENCE if r in found), None)

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


def item(kind: str, company_id: Any, subject_key: Any, *, reason: str, summary: Any,
         evidence: Optional[Dict[str, Any]] = None, project_id: Any = None,
         answer_log_id: Any = None, now: datetime) -> Optional[Dict[str, Any]]:
    """The row. None without a company, or with a kind or reason this does
    not hold: an item belongs to one company's queue."""
    if kind not in QUEUED_KINDS or reason not in REASONS or not company_id:
        return None
    return {
        "_id": item_id(kind, company_id, subject_key),
        "kind": kind,
        "company_id": str(company_id),
        "project_id": str(project_id) if project_id else None,
        "answer_log_id": str(answer_log_id) if answer_log_id else None,
        "summary": answer_log.redact(str(summary or "")[:MAX_SUMMARY]),
        "evidence": answer_log.redact(evidence or {}),
        "reason": reason,
        "priority": priority(reason),
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
    found: List[str] = []
    subject = ""
    for g in row.get("gates") or []:
        if not isinstance(g, dict):
            continue
        if g.get("gate") == "plan_answer_gate" and g.get("outcome") in GATE_OUTCOMES:
            reasons.append(f"plan_gate:{g['outcome']}")
            found.append(REASON_REPLACED)
            subject = subject or str(g.get("subject") or "")
        elif str(g.get("gate") or "").startswith("dm_") and g.get("stop") in DM_STOPS:
            reasons.append(f"{g['gate']}:{g['stop']}")
            found.append(REASON_UNVERIFIED)
    shown = [r for r in raw_records or [] if isinstance(r, dict)]
    contested_recs = [answer_log.record_snapshot(r) for r in shown if contested(r)]
    if contested_recs:
        reasons.append("records_contested")
        found.append(REASON_CONFLICT)
    if not reasons:
        return None
    projects = sorted(str(p) for p in row.get("project_ids") or [])
    key = "|".join(projects) + "|" + _norm(subject or row.get("question"))
    sheets = sorted({str(r["sheet"]) for r in contested_recs if r.get("sheet")}) or sorted(
        {str(r["sheet"]) for r in row.get("records") or [] if r.get("sheet")})
    evidence = {
        "reasons": reasons,
        "surface": row.get("surface"),
        "path": row.get("path"),
        "subject": subject[:200] or None,
        "sheets": sheets[:MAX_EVIDENCE],
        "record_ids": [r["id"] for r in (contested_recs or row.get("records") or [])
                       if r.get("id")][:MAX_EVIDENCE],
        "quotes": [{"id": r.get("id"), "sheet": r.get("sheet"),
                    "text": str(r.get("text") or "")[:MAX_QUOTE]} for r in contested_recs][:MAX_EVIDENCE],
    }
    what = subject or "an answer"
    summary = (f"{', '.join(reasons)} on {what[:120]}"
               + (f" (sheets {', '.join(sheets[:4])})" if sheets else ""))
    return item(KIND_CONFLICTING_SOURCES, row["company_id"], key,
                reason=answer_reason(found) or REASON_CONFLICT, summary=summary,
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
    reason = REASON_SET_HEALTH_INFO if kind in SET_HEALTH_INFO else REASON_SET_HEALTH_FAILED
    return item(KIND_SET_HEALTH, company_id, key, reason=reason, summary=summary,
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
                reason=REASON_REGISTRATION, summary=summary,
                evidence={k: v for k, v in evidence.items() if v not in (None, "")},
                now=now)


# ── plan_set_question (PR #889) ──────────────────────────────

def from_plan_set_question(company_id: Any, project_id: Any, question: Dict[str, Any], *,
                           now: datetime) -> Optional[Dict[str, Any]]:
    """One set-membership question for the PM (lib/plan_set_questions on
    #889: a question names its sheets and what each reading would change).
    Keyed by the question's own id (else its code). Reads #889's stored
    shape (label, pages[].sheet_number, figures) or plain sheets/readings."""
    qid = question.get("_id") or question.get("id") or question.get("code")
    if not qid or not project_id:
        return None
    sheets = question.get("sheets") or [
        p.get("sheet_number") for p in (question.get("pages") or [])
        if isinstance(p, dict) and p.get("sheet_number")]
    sheets = [str(s) for s in sheets][:MAX_EVIDENCE]
    readings = question.get("readings")
    if not readings and question.get("figures"):
        try:
            from lib import plan_set_questions as psq
            readings = psq.change_lines(question)
        except Exception:
            readings = None
    evidence = {"question_id": str(qid), "code": question.get("code"),
                "sheets": sheets or None,
                "readings": [str(r)[:MAX_QUOTE] for r in (readings or [])][:4] or None}
    text = str(question.get("question") or question.get("text") or question.get("label")
               or "set membership question")
    return item(KIND_PLAN_SET_QUESTION, company_id, f"{project_id}|{qid}",
                reason=REASON_SET_AMBIGUITY, summary=text[:MAX_SUMMARY],
                evidence={k: v for k, v in evidence.items() if v not in (None, "")},
                project_id=project_id, now=now)
