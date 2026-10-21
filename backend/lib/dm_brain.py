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

The model is Qwen 3.8 Flash on DeepInfra (OpenAI-compatible chat completions,
tool calling); a stronger DeepInfra model (ESCALATE_MODEL) gets the one
retry when the evidence check fails, and writes report summaries.

This module is pure (no server import): prompt, context, history, checks.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

FLAG = "dm_brain_v2"
#: DeepInfra, OpenAI-compatible; the key is the one the vision calls use
#: (QWEN_API_KEY). Overridable for an eval or a rollback without a deploy.
API_BASE = (os.environ.get("DM_BRAIN_API_BASE") or "https://api.deepinfra.com/v1/openai").rstrip("/")
#: Every turn: Qwen 3.8 Flash (fast, cheap, tool calling).
MODEL = os.environ.get("DM_BRAIN_MODEL") or "Qwen/Qwen3.8-Flash"
#: A stronger DeepInfra model: report summaries, and the one retry when the
#: evidence check fails.
ESCALATE_MODEL = os.environ.get("DM_BRAIN_ESCALATE_MODEL") or "Qwen/Qwen3.8-Max"
#: The output budget per model call -- Qwen 3.8 Flash's reasoning tokens
#: count against it (Tue: a reply of "*Ark" after 26 s was a budget spent on
#: reasoning), so it is generous; a cut answer is retried once at
#: RETRY_MAX_TOKENS and never sent.
MAX_TOKENS = int(os.environ.get("DM_BRAIN_MAX_TOKENS") or 6000)
RETRY_MAX_TOKENS = int(os.environ.get("DM_BRAIN_RETRY_MAX_TOKENS") or 12000)
#: DeepInfra's reasoning_effort ("low" / "medium" / "high"), sent only when set.
REASONING_EFFORT = (os.environ.get("DM_BRAIN_REASONING_EFFORT") or "").strip()
TEMPERATURE = 0.2
HISTORY_TURNS = 20
HISTORY_DAYS = 7
#: Tool calls in one turn, run one after another; then it must answer.
MAX_TOOL_CALLS = 6
#: Model calls in one turn (tool rounds + the answer + the retries).
MAX_ROUNDS = MAX_TOOL_CALLS + 7
#: Times the model is asked again (the same model) when its answer has a
#: number or id that no tool result, message or context holds.
VERIFY_RETRIES = 1
UNVERIFIED_TEXT = ("I couldn't check that against the records just now. "
                   "Ask me again and I'll pull it fresh.")
#: Sent instead of an answer that came back cut off twice.
TRUNCATED_TEXT = "My answer came out cut off. Ask me again and I'll send it whole."
#: Sent instead of an answer that twice said something was done that wasn't.
ACTION_UNVERIFIED_TEXT = "I haven't done that yet. Tell me again and I'll do it."
#: How a record whose sender is the person asking is marked in tool results.
SELF_MARK = "(you)"
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
- Reply in the language they write in: English, Spanish, or Yiddish (Yiddish is written in Hebrew letters --
answer in Yiddish, never Hebrew). Names, job numbers and record ids stay as they are.

Facts
- Every number, name, date, time, permit/violation/record id you state must come from a tool result \
in this conversation. Call tools for anything factual -- several at once when the question needs it \
(e.g. an update on a job = who is on site + open items + DOB/DOT + what's coming up).
- If no tool has it, say so in one line and say what you can check instead. Never invent, round or \
estimate. Never say you can't access something a tool covers: voice notes, the subs list, \
attendance history, photos or messages they replied to, drawings, the brief.
- They ARE the site manager / PM / admin: never tell them to check with, ask or reach out to anyone \
else (the site manager, the super, the office, the sub) for something a tool could hold.
- Never answer "I'm not sure", "I don't have that" or "check with X" before you have called EVERY tool \
that could hold it (a trade, e.g. "how many days hvac worked in 588": sub_attendance with trade; a sub \
you can't place: find_sub / list_subs, then its tool). If after that nothing has it, say in one line \
what you checked.
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
- Answer their LATEST message only. Earlier messages in this chat are context, not questions to answer \
again: follow-ups like "and Walworth?", "those 3", "send it" refer \
back to them.
- A message or voice note is "from you" / "you said" ONLY when the tool result marks its sender "(you)"; \
otherwise name the sender as the record does.
- Say something was sent, saved, cancelled or done ONLY when a tool result this turn says it was.
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


#: Before their latest message when earlier ones share its turn.
LATEST_MARK = ("[Their latest message -- answer this one. The lines above are earlier messages, "
               "context only; don't answer them again:]")


def turn_messages(history: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """The conversation plus this message, roles alternating. The message is
    its own user turn; if the history ends on a user turn (an earlier message
    with no reply recorded after it), they share the turn -- marked, so the
    model answers THIS message, not the earlier one too (Oct 20 #37: "How
    many arkon guys on 588" got a 546 checklist asked before it)."""
    msgs = [dict(m) for m in history]
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] = (f"{msgs[-1]['content']}\n\n{LATEST_MARK}\n{text}")
    else:
        msgs.append({"role": "user", "content": text})
    return msgs


# ── GUARDRAILS ───────────────────────────────────────────────────────────────

# A record id: letters then digits ("P-588-1", "SSP-011.00", "B00123456",
# "ECB 39012345X"), or a long digit run (a DOB job / BIN / permit number).
_ID_RE = re.compile(r"\b[A-Z]{1,6}-?\d[\w.-]*\d\b|\b[A-Z]{1,6}-?\d\b|\b\d{5,}(?:-\d+)*\b")
# An ISO date (and time), as tools and Mongo write them.
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
# A number as said: 31, 8:01, 2.5, 1,200.
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:[:.,]\d+)*(?![\w])")
# Phone-shaped: 10-11 digits as a phone is written, never a permit's
# "321234567-01" (a dash and more digits after it).
_PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w-])"
    r"|(?<![\w-])\+?1?\d{10}(?![\d-])"
    # International, written with its "+": "+44 20 7946 0958", "+972-54-123-4567",
    # "+972541234567" (8-15 digits). A permit number has no "+".
    r"|(?<![\w+])\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?![\w-])")


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
    # An ISO date in a source vouches for its parts: "2026-09-18T00:00:00"
    # from a tool covers "Sep 18" / "2026-09-18" (Oct 20 eval: "18" blocked a
    # right answer). Only ISO dates -- "8:45" still does not vouch for "45".
    src_nums = _numbers(src)
    for m in _ISO_RE.finditer(src):
        src_nums |= {_norm_num(g) for g in m.groups() if g}
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


# "check with the site manager", "ask the super", "I'm not sure", "I don't
# have that", "not in the records" (Tue 12:28 PM: an HVAC days question got
# "check with the site manager" -- the asker IS the site manager).
_REFER_RE = re.compile(
    r"\b(?:check|confirm|verify)\s+with\b|\b(?:ask|contact|call|reach\s+out\s+to|talk\s+to|text)\s+"
    r"(?:your|the|their|a|an)\s+(?:site\s+manager|super(?:intendent)?|foreman|office|pm|project\s+manager|"
    r"gc|sub(?:contractor)?|team|admin)\b", re.IGNORECASE)
_UNSURE_RE = re.compile(
    r"\bi'?m\s+not\s+sure\b|\bi\s+am\s+not\s+sure\b|\bi\s+(?:don'?t|do\s+not)\s+(?:know|have)\b|"
    r"\bi\s+(?:can'?t|cannot|couldn'?t)\s+(?:tell|find|see|answer|say)\b|\bno\s+(?:data|records?|info(?:rmation)?)\b|"
    r"\bnot\s+in\s+(?:the|my)\s+records\b|\bdon'?t\s+have\s+(?:that|this|any)\b", re.IGNORECASE)

#: Times the model is asked again when it deflects ("check with X") or says
#: it can't answer.
DEFLECT_RETRIES = 1


def refers_elsewhere(reply: Any) -> bool:
    """Sends them to someone else for the answer."""
    return bool(_REFER_RE.search(str(reply or "")))


def cant_answer(reply: Any) -> bool:
    """A "can't answer": sends them elsewhere, or says it doesn't know /
    doesn't have it."""
    t = str(reply or "")
    return refers_elsewhere(t) or bool(_UNSURE_RE.search(t))


def deflect_note(tools_tried: Sequence[str]) -> str:
    """What the model is told when its answer deflects."""
    tried = ", ".join(tools_tried) if tools_tried else "none"
    return ("Before this goes out: your answer sends them to someone else or says you can't answer. "
            "They are the site manager / PM -- never send them elsewhere. Tools called so far: "
            f"{tried}. Call every tool that could hold this first (sub_attendance takes a trade; "
            "find_sub / list_subs place a sub). If nothing has it after that, say in one line what "
            "you checked.")


# ── CUT, CLAIMED, "YOU" ──────────────────────────────────────────────────────

def _bold_unbalanced(text: str) -> bool:
    """An odd number of WhatsApp bold stars ("*Ark"), bullets aside."""
    stars = 0
    for line in str(text or "").splitlines():
        body = re.sub(r"^\s*\*\s+", "", line)          # "* item" is a bullet
        stars += body.count("*")
    return stars % 2 == 1


def truncated(text: Any, finish_reason: Any = None, after_tools: bool = False) -> bool:
    """A reply that must not go out as it is: the budget ran out
    (finish_reason "length"), nothing came back, the bold is left open, or
    under 20 characters after tools were called."""
    t = str(text or "").strip()
    if finish_reason == "length" or not t or _bold_unbalanced(t):
        return True
    return bool(after_tools and len(t) < 20)


def cut_note() -> str:
    return ("Before this goes out: your answer came back cut off. Answer again, complete, in a few "
            "short lines -- no long thinking, the tool results above have what you need.")


_CLAIMS = (
    ("sent", re.compile(r"\b(?:i(?:'ve| have)?\s+(?:just\s+)?sent|i'?m\s+sending|sending\s+(?:it|you|the|now)|"
                        r"(?:just\s+)?sent\s+(?:it|you|the|that|this|over)|^sent\b)", re.I | re.M)),
    ("saved", re.compile(r"\b(?:i(?:'ve| have)?\s+saved|(?:it'?s|that'?s|is|are|been)\s+saved|^saved\b)",
                         re.I | re.M)),
    ("cancelled", re.compile(r"\b(?:i(?:'ve| have)?\s+cancell?ed|(?:it'?s|that'?s|is|been)\s+cancell?ed|"
                             r"^cancell?ed\b)", re.I | re.M)),
    ("done", re.compile(r"\b(?:i(?:'ve| have)?\s+done\s+(?:it|that)|all\s+done|^done\b(?!\s+P-))",
                        re.I | re.M)),
)


def action_claims(reply: Any) -> List[str]:
    """What the reply says was done: "sent", "saved", "cancelled", "done"."""
    t = str(reply or "")
    return [k for k, rx in _CLAIMS if rx.search(t)]


def claim_note(claims: Sequence[str], tools: Sequence[str]) -> str:
    return (f"Before this goes out: your answer says it was {', '.join(claims)}, but no tool this turn "
            f"did that (tools called: {', '.join(tools) or 'none'}). Rewrite it: say what you found, or "
            "what will happen when they say yes. Nothing is sent or saved unless a tool result says so.")


_FROM_YOU = re.compile(r"\bfrom\s+you\b|\byou\s+(?:said|sent|posted|mentioned|recorded|asked)\b|"
                       r"\byour\s+(?:own\s+)?(?:voice\s+note|message|note|recording)\b", re.I)


def says_from_you(reply: Any) -> bool:
    """Says a record is the asker's own ("from you", "you said")."""
    return bool(_FROM_YOU.search(str(reply or "")))


def you_note() -> str:
    return ("Before this goes out: your answer says a message or voice note is from them, but no record "
            f"this turn is marked {SELF_MARK}. Name the sender as the record does, and answer again.")


def redact_phones(text: str) -> str:
    """No phone number goes out in an answer."""
    return _PHONE_RE.sub("[number]", text or "")


_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


def final_text(content: Any) -> str:
    """The text of a model message: its content, without any <think> block."""
    if isinstance(content, list):
        content = "\n".join(str((c.get("text") if isinstance(c, dict) else getattr(c, "text", "")) or "")
                            for c in content)
    return _THINK_RE.sub("", str(content or "")).strip()


def json_object(content: Any) -> Optional[Dict[str, Any]]:
    """One JSON object from a model message (fences and <think> removed;
    the first {...} if there is text around it), else None."""
    import json
    t = final_text(content)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    for cand in (t, t[t.find("{"):t.rfind("}") + 1] if "{" in t else ""):
        try:
            got = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(got, dict):
            return got
    return None


# What a reply's language should be: Hebrew script (Yiddish), Spanish, or English.
_HEB = re.compile(r"[\u0590-\u05FF]")
_ES = re.compile(r"[¿¡ñáéíóú]|\b(?:cu[aá]nt[oa]s?|hoy|trabajadores|qu[eé]|d[oó]nde|est[aá]n?|hay|"
                 r"semana|d[ií]as?|obra)\b", re.IGNORECASE)


def language(text: Any) -> str:
    """"yi", "es" or "en" -- the script and words, for the eval's check."""
    t = str(text or "")
    if _HEB.search(t):
        return "yi"
    if len(_ES.findall(t)) >= 1 and not re.search(r"\b(?:the|how|many|what|is|are)\b", t, re.I):
        return "es"
    return "en"


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
