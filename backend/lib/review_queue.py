"""THE REVIEW QUEUE (L6 step 3: the feed only). Pure: no database handle.

Uncertain findings, queued for the platform operator's review queue (L6.4:
operator-gated routes and the web screen, approve / deny with an
explanation -- the section at the end of this file). The feed only
INSERTS items: server._review_queue_add is the one inserter. The one
change ever made to a row is the operator's decision (L6.4,
server._review_decide: status pending -> approved | denied, and again with
a new explanation; each decision appended to `decisions`). No
person but the operator is ever shown one.

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
  status            "pending" at insert. Changed by the operator's
                    decision only (server._review_decide), to "approved" or
                    "denied", with `decision` {decision, explanation, notify,
                    include_explanation, operator_id, decided_at} beside it
                    (the current one) and `decisions` (every one, appended;
                    a decided item may be decided again with a NEW
                    explanation).
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
    disputed = [answer_log.record_snapshot(r) for r in shown if contested(r)]
    if disputed:
        reasons.append("records_contested")
        found.append(REASON_CONFLICT)
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


# ── L6.4: THE OPERATOR'S REVIEW (routes and screen) ─────────────────────────
#
# The platform operator lists both collections side by side (a dispute from
# answer_disputes, every other kind from review_queue), reads an item with
# its answer_log row, and decides it: approve or deny, with an explanation
# and an optional note to the person who disputed. server._review_decide is
# the ONE writer of a decision: a conditional update of the item's own
# status and decision, appending the decision to `decisions`. A decided item
# may be decided again (owner ruling) with a NEW explanation: the same
# explanation as the current decision is a 409. answer_log is never touched.
# Nothing here is shown to anyone but the operator; a disputing person only
# ever sees "Flagged for review" (and, when the operator ticks Notify, the
# NOTIFY_TEXT line, English then Spanish, plus the explanation when the
# operator ticks "Include my explanation").
#
# NOT HERE (L6.5): an approved dispute becoming a verified eval example and a
# fix ticket, a denied one a disputed-but-confirmed example, and "under
# review" refusals while an item is pending.

SOURCE_DISPUTE = "dispute"          # a row of answer_disputes
SOURCE_QUEUE = "queue"              # a row of review_queue
SOURCES = (SOURCE_DISPUTE, SOURCE_QUEUE)

STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_DENIED)
DECISIONS = {"approve": STATUS_APPROVED, "deny": STATUS_DENIED}

MIN_EXPLANATION = 10
MAX_EXPLANATION = 2000
MAX_LIST = 100
MAX_OFFSET = 1000
LIST_RECORDS = 6                    # records per answer on the list; all on the item

#: The line a disputing person gets when the operator ticks Notify, English
#: then Spanish in one message (as the proactive bilingual DMs are sent: the
#: DOT embargo DM, EN block then ES block; a proactive DM has no per-person
#: language). Plain on purpose: no status word, no reviewer; the operator's
#: explanation only when they tick "Include my explanation".
NOTIFY_TEXT = {
    "approve": {"en": "Thanks — you were right. We've logged it for a fix.",
                "es": "Gracias — tenía razón. Lo registramos para corregirlo."},
    "deny": {"en": "Thanks — we checked; the answer stands.",
             "es": "Gracias — lo revisamos; la respuesta es correcta."},
}


def notify_text(decision: str, explanation: Any = None) -> str:
    """EN line, ES line, then (when given) the explanation on a new line."""
    t = NOTIFY_TEXT[decision]
    out = f"{t['en']}\n{t['es']}"
    extra = clean_explanation(explanation) if explanation else ""
    return f"{out}\n{extra}" if extra else out


def check_decision(decision: Any, explanation: Any) -> Optional[str]:
    """None when the decision can be written; else what is wrong with it."""
    if decision not in DECISIONS:
        return "decision must be approve or deny"
    text = " ".join(str(explanation or "").split())
    if len(text) < MIN_EXPLANATION:
        return f"an explanation of at least {MIN_EXPLANATION} characters is required"
    return None


def clean_explanation(explanation: Any) -> str:
    return answer_log.redact(str(explanation or "").strip()[:MAX_EXPLANATION])


def _norm_text(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def same_explanation(current: Any, explanation: Any) -> bool:
    """A re-decision must say something new: True when `explanation` is the
    current decision's (whitespace and case aside)."""
    if not isinstance(current, dict):
        return False
    return _norm_text(current.get("explanation")) == _norm_text(clean_explanation(explanation))


def history(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every decision of an item, oldest first. A row decided before the
    history existed has only `decision`: that is its history of one."""
    hist = doc.get("decisions")
    if isinstance(hist, list):
        return [d for d in hist if isinstance(d, dict)]
    return [doc["decision"]] if isinstance(doc.get("decision"), dict) else []


def decision_entry(decision: str, explanation: Any, notify: bool, include_explanation: bool,
                   operator_id: Any, now: datetime) -> Dict[str, Any]:
    """One decision: what was decided, why, and whether the person was told."""
    return {"decision": decision,
            "explanation": clean_explanation(explanation),
            "notify": bool(notify),
            "include_explanation": bool(notify and include_explanation),
            "operator_id": str(operator_id or ""),
            "decided_at": now}


def decision_set(decision: str, explanation: Any, notify: bool, operator_id: Any,
                 now: datetime, include_explanation: bool = False) -> Dict[str, Any]:
    """The $set of a decision: the item's status and what decided it."""
    return {"status": DECISIONS[decision],
            "decision": decision_entry(decision, explanation, notify, include_explanation,
                                       operator_id, now)}


#: Owner ruling (L6.4): every item has a REASON and a PRIORITY. A queue row
#: carries both (set at insert by the feed); a dispute is reason "dispute",
#: priority normal. Low priority is set_health_info only.
REASON_DISPUTE = "dispute"
REVIEW_REASONS = (REASON_DISPUTE,) + REASONS
PRIORITIES = (PRIORITY_NORMAL, PRIORITY_LOW)
#: The list's priority filter: "normal" (the default "Needs decision" view,
#: low hidden), "low" only, or "all".
PRIORITY_FILTERS = (PRIORITY_NORMAL, PRIORITY_LOW, "all")


def sources_for(kind: Optional[str], reason: Optional[str] = None,
                priority: Optional[str] = None) -> List[str]:
    """Which collections a filter reads: a dispute is answer_disputes' row,
    every other kind and reason is review_queue's, and no dispute is low."""
    out = list(SOURCES)
    if kind:
        out = [s for s in out if (s == SOURCE_DISPUTE) == (kind == KIND_DISPUTE)]
    if reason:
        out = [s for s in out if (s == SOURCE_DISPUTE) == (reason == REASON_DISPUTE)]
    if priority == PRIORITY_LOW:
        out = [s for s in out if s == SOURCE_QUEUE]
    return out


def reason_of(source: str, doc: Dict[str, Any]) -> Optional[str]:
    if source == SOURCE_DISPUTE:
        return REASON_DISPUTE
    return doc.get("reason")


def priority_of(source: str, doc: Dict[str, Any]) -> str:
    if source == SOURCE_DISPUTE:
        return PRIORITY_NORMAL
    return PRIORITY_LOW if doc.get("priority") == PRIORITY_LOW else PRIORITY_NORMAL


def _when(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def answer_view(row: Optional[Dict[str, Any]], *, full: bool = False) -> Optional[Dict[str, Any]]:
    """The answer_log row an item names, as the operator reads it (the row
    was redacted at insert; it is redacted again on the way out)."""
    if not row:
        return None
    records = list(row.get("records") or [])
    out = {
        "id": str(row.get("_id")),
        "surface": row.get("surface"),
        "path": row.get("path"),
        "question": row.get("question"),
        "final_text": row.get("final_text"),
        "records": records if full else records[:LIST_RECORDS],
        "records_total": len(records),
        "gates": list(row.get("gates") or []),
        "model": row.get("model"),
        "code_sha": row.get("code_sha"),
        "asker_last4": row.get("asker_last4"),
        "created_at": _when(row.get("created_at")),
    }
    if full:
        out["tools"] = list(row.get("tools") or [])
        out["timing"] = row.get("timing")
        out["content_hash"] = row.get("content_hash")
    return answer_log.redact(out)


def item_view(source: str, doc: Dict[str, Any], *, company_name: Any = None,
              project: Optional[Dict[str, Any]] = None,
              answer: Optional[Dict[str, Any]] = None,
              asker_name: Any = None, full: bool = False) -> Dict[str, Any]:
    """One item of either collection, in one shape, for the operator only."""
    dispute = source == SOURCE_DISPUTE
    decision = doc.get("decision") if isinstance(doc.get("decision"), dict) else None
    out = {
        "source": source,
        "id": str(doc.get("_id")),
        "kind": KIND_DISPUTE if dispute else doc.get("kind"),
        "reason": reason_of(source, doc),
        "priority": priority_of(source, doc),
        "company": {"id": str(doc.get("company_id") or ""), "name": company_name},
        "project": project,
        "created_at": _when(doc.get("created_at")),
        "status": doc.get("status"),
        "summary": doc.get("text") if dispute else doc.get("summary"),
        "answer_log_id": doc.get("answer_log_id"),
        "answer": answer_view(answer, full=full),
        "decision": ({**decision, "decided_at": _when(decision.get("decided_at"))}
                     if decision else None),
        "decisions": [{**d, "decided_at": _when(d.get("decided_at"))} for d in history(doc)],
    }
    if dispute:
        out["asker"] = {"user_id": doc.get("user_id"), "name": asker_name,
                        "surface": doc.get("surface")}
    if full and not dispute:
        out["evidence"] = doc.get("evidence") or {}
    return answer_log.redact(out)


def merge_newest(lists: Iterable[List[Dict[str, Any]]], offset: int,
                 limit: int) -> List[Dict[str, Any]]:
    """Items of several newest-first lists, newest first, one page."""
    rows = [r for rows in lists for r in rows]
    rows.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")),
              reverse=True)
    return rows[offset:offset + limit]
