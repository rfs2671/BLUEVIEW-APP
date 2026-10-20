"""Levelog Assistant's one brain for a DM (behind the per-company flag
`dm_brain_v2`).

Every free-text DM from an opted-in admin or PM goes to one model with:
  * the last HISTORY_TURNS messages of this DM (both sides),
  * who they are (name, role, company) and their jobs,
  * the job this chat is on (the one used in the last 30 minutes),
  * any open flow (a walk in progress, a change or reminder waiting for "yes").
The model decides which tools to call -- several per turn -- and writes the
answer. Style lives in SYSTEM_PROMPT, not in code: nothing here trims an
answer, matches an intent, or writes a reply template.

What stays in code (server.py glue + this module) is only the guardrails:
  * writes and sends to anyone else need an explicit "yes" to a pending
    confirm (the model can only PROPOSE a change);
  * every number and record id in an answer must be in this turn's tool
    results, the conversation or the context -- if not, the model is asked
    again (never truncated);
  * no phone numbers go out;
  * every tool is scoped to the asking user's company and jobs.

This module is pure (no server import): prompt, context, history, checks.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

FLAG = "dm_brain_v2"
#: Claude Sonnet-class. Overridable for an eval or a rollback without a deploy.
MODEL = os.environ.get("DM_BRAIN_MODEL") or "claude-sonnet-5-5"
#: Effort for a chat turn with tool use (Sonnet 5.5 levels).
EFFORT = os.environ.get("DM_BRAIN_EFFORT") or "medium"
MAX_TOKENS = 4000
HISTORY_TURNS = 20
HISTORY_DAYS = 7
#: Model rounds in one turn (each may call several tools at once).
MAX_ROUNDS = 8
#: Times the model is asked again when its answer has a number or id that no
#: tool result, message or context holds.
VERIFY_RETRIES = 2
UNVERIFIED_TEXT = ("I couldn't check that against the records just now. "
                   "Ask me again and I'll pull it fresh.")
FAILED_TEXT = "Levelog Assistant couldn't answer that right now. Try again in a minute."

SYSTEM_PROMPT = """\
You are Levelog Assistant, texting with a general contractor's admin or project manager on WhatsApp \
about their NYC construction jobs. You know their jobs, subs, crews, DOB/DOT records, punch lists, \
follow-ups, drawings, voice notes and group-chat history through your tools.

How you write
- Like a sharp site super texting back: the answer first, then at most a line of what matters next. \
Plain construction language. No greeting, no preamble, no "Great question", no sign-off.
- Short by default: one to four lines. A list only when they ask for one or the answer is a list \
(subs on site, open items); keep each line tight. If there is clearly more, end with one short offer \
("Want the names?", "Want the full list?") -- and when they say yes, send it.
- WhatsApp formatting only: *bold* sparingly, "- " bullets, no headings, no tables, no markdown links.
- Never send an empty heading or a label with nothing under it. You decide the length; nothing will \
cut your answer, so make it complete and short.
- Reply in the language they write in (English, Spanish, Yiddish).

Facts
- Every number, name, date, time, permit/violation/record id you state must come from a tool result \
in this conversation. Call tools for anything factual -- several at once when the question needs it \
(e.g. an update on a job = who is on site + open items + DOB/DOT + what's coming up).
- If no tool has it, say so in one line and say what you can check instead. Never invent, round or \
estimate. Never say you can't access something a tool covers: voice notes, the subs list, \
attendance history, photos or messages they replied to, drawings, the brief.
- Don't repeat an earlier answer word for word to a different question: answer what they asked now, \
or ask one short question if you can't tell what they want.

Jobs, subs, people
- Their jobs are listed in the context. Read job references loosely: "588", "boyland", "walworth", \
typos. If the question is about a job and the context's current job fits, use it. Ask "which job" \
only when it truly could be more than one -- one short question naming the options.
- Sub and company names are often misspelled or misheard ("Akron" for Arkon, "J and G" for J&G): match \
them to the subs list. "DOT" is the NYC Department of Transportation (permits, violations), not a sub.
- When they tell you a fact about a sub ("Arkon is framer", "J&G does scaffold") that the subs list \
doesn't have, say you'll save it and call set_sub_trade -- it only proposes; they confirm with yes.

Changes and sends
- You can't change anything directly. propose_change / set_sub_trade / remind_me / undo_last_change \
only PROPOSE: the tool tells you what the system will ask or confirm; you then ask them, in your own \
words, to reply yes. Never say something is saved, added, sent or changed unless a tool result says it \
was done.
- If a change is waiting for an answer (see Open flows), their message is probably that answer: pass it \
with answer_pending_change, or cancel_pending_change if they drop it.
- send_sheet and send_report send to this chat only (to them). After one, say a short line about it.

Context, history
- Messages starting "[voice note]" were transcribed and may be misheard; read them generously.
- Earlier messages in this chat are context: follow-ups like "and Walworth?", "those 3", "send it" refer \
back to them.
- Never give out phone numbers. Never discuss another company's data.
"""


# ── CONTEXT ──────────────────────────────────────────────────────────────────

def context_block(*, user: Dict[str, Any], jobs: Sequence[Dict[str, Any]],
                  active_job: Optional[Dict[str, Any]], open_flows: Sequence[str],
                  now_label: str) -> str:
    """The turn's context, as text for the model (after the cached prompt).

    `user`: {name, role, company}; `jobs`: [{id, label, aliases}];
    `active_job`: one of jobs or None; `open_flows`: plain descriptions."""
    lines = [f"Now: {now_label} (New York)."]
    who = ", ".join(x for x in (str(user.get("name") or "").strip(),
                                str(user.get("role") or "").strip(),
                                str(user.get("company") or "").strip()) if x)
    if who:
        lines.append(f"You are talking to: {who}.")
    if jobs:
        lines.append("Their jobs (id: name; also called):")
        for j in jobs:
            aka = [a for a in (j.get("aliases") or []) if a and a != j.get("label")]
            lines.append(f"- {j['id']}: {j['label']}" + (f" (also: {', '.join(aka[:4])})" if aka else ""))
    else:
        lines.append("They have no jobs in Levelog yet.")
    if active_job:
        lines.append(f"Current job in this chat: {active_job['label']} ({active_job['id']}).")
    else:
        lines.append("No current job in this chat.")
    if open_flows:
        lines.append("Open flows:")
        lines += [f"- {f}" for f in open_flows]
    else:
        lines.append("Open flows: none.")
    return "\n".join(lines)


def history_messages(rows: Iterable[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    """This DM's last HISTORY_TURNS messages (HISTORY_DAYS), oldest first, as
    alternating user / assistant turns for the Messages API. Consecutive
    messages from one side are joined; the list starts with a user turn."""
    cutoff = now - timedelta(days=HISTORY_DAYS)
    kept = []
    for r in rows:
        at = r.get("created_at")
        if isinstance(at, datetime) and at.tzinfo is not None and at < cutoff:
            continue
        body = str(r.get("body") or "").strip()
        if not body:
            continue
        role = "assistant" if str(r.get("sender") or "") == "bot" else "user"
        if role == "user" and r.get("voice"):
            body = "[voice note] " + body
        kept.append((role, body[:2000]))
    kept = kept[-HISTORY_TURNS:]
    out: List[Dict[str, Any]] = []
    for role, body in kept:
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + body
        else:
            out.append({"role": role, "content": body})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def turn_messages(history: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """The conversation plus this message, roles alternating. The message is
    its own user turn; if the history ends on a user turn (an unanswered
    message), they are joined."""
    msgs = [dict(m) for m in history]
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] = f"{msgs[-1]['content']}\n{text}"
    else:
        msgs.append({"role": "user", "content": text})
    return msgs


# ── GUARDRAILS ───────────────────────────────────────────────────────────────

# A record id: letters then digits ("P-588-1", "SSP-011.00", "B00123456",
# "ECB 39012345X"), or a long digit run (a DOB job / BIN / permit number).
_ID_RE = re.compile(r"\b[A-Z]{1,6}-?\d[\w.-]*\d\b|\b[A-Z]{1,6}-?\d\b|\b\d{5,}(?:-\d+)*\b")
# A number as said: 31, 8:01, 2.5, 1,200.
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:[:.,]\d+)*(?![\w])")
# Phone-shaped: 10-11 digits as a phone is written, never a permit's
# "321234567-01" (a dash and more digits after it).
_PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w-])"
    r"|(?<![\w-])\+?1?\d{10}(?![\d-])")


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if re.fullmatch(r"\d+", s):
        return str(int(s))
    return s


def _numbers(text: str) -> set:
    out = set()
    for m in _NUM_RE.finditer(text or ""):
        # A time or a decimal counts whole: "8:45" does not vouch for "45".
        out.add(_norm_num(m.group(0)))
    return out


def unverified(reply: str, sources: Iterable[str]) -> List[str]:
    """The numbers and record ids in `reply` that no source holds (tool
    results, the conversation, the context). Empty when it checks out."""
    src = "\n".join(s for s in sources if s)
    src_nums = _numbers(src)
    src_low = src.lower()
    missing: List[str] = []
    for m in _ID_RE.finditer(reply or ""):
        tok = m.group(0)
        if tok.lower() not in src_low and tok not in missing:
            missing.append(tok)
    ids = " ".join(missing)
    for m in _NUM_RE.finditer(reply or ""):
        tok = m.group(0)
        if tok in ids:
            continue
        if _norm_num(tok) in src_nums:
            continue
        if tok not in missing:
            missing.append(tok)
    return missing


def verify_note(missing: Sequence[str]) -> str:
    """What the model is told when its answer had figures nothing holds."""
    return ("Before this goes out: these figures in your answer are not in any tool result, message or "
            f"the context: {', '.join(missing[:12])}. Check them with a tool, or answer without them. "
            "Don't compute new figures; use the ones the tools return.")


def redact_phones(text: str) -> str:
    """No phone number goes out in an answer."""
    return _PHONE_RE.sub("[number]", text or "")


def final_text(blocks: Iterable[Any]) -> str:
    """The text of a model response (its text blocks, joined)."""
    parts = []
    for b in blocks:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if t == "text":
            parts.append((b.get("text") if isinstance(b, dict) else getattr(b, "text", "")) or "")
    return "\n".join(p for p in parts if p.strip()).strip()


# ── FAST PATHS: exact commands only ──────────────────────────────────────────

_YES = re.compile(r"^\s*(?:y|yes|yeah|yep|yup|ok|okay|sure|confirm|confirmed|do it|go ahead|"
                  r"s[ií]|claro|dale|correct|👍|✅)\s*[.!]*\s*$", re.IGNORECASE)
_NO = re.compile(r"^\s*(?:n|no|nope|nah|cancel|stop|never ?mind|forget it|don'?t)\s*[.!]*\s*$",
                 re.IGNORECASE)


def is_yes(text: Any) -> bool:
    """An explicit yes to a pending confirm -- only the word itself."""
    return bool(_YES.match(str(text or "")))


def is_no(text: Any) -> bool:
    """An explicit no / cancel to a pending confirm -- only the word itself."""
    return bool(_NO.match(str(text or "")))
