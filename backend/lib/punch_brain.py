"""The walk's brain: what a walker MEANT by a message during a walkthrough.

Live 588, Tue Oct 13, 1:43 PM: the walk read like a form. "Ignore all trades
and location. The floor and description enough for this list" got the
"Reply to fix (...)" hint again; "Send" got "43 still need a trade (5, 2, 3,
8, 19 ...)"; "Send to me" got "I don't know me on this job."

So every free-text message during a walk goes to the model WITH the walk's
state (stage, how many items, what is missing, who it goes to), and the model
answers with the action(s) it means. The code checks each one against the
walk (real numbers, real trades, a place that reads as one) and applies only
those. Fixed commands ("send", "ok", "undo", "3 rear yard", "2 → electrical")
stay a fast path and never reach the model.

Pure: no I/O. The server builds the state (state_for), sends PROMPT + the
state + the message, and applies what clean_plan returns.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from lib import punch

#: Each action the model may answer with, and what it means.
ACTIONS = ("simple", "detailed", "send", "assign", "due", "trade", "location", "drop",
           "words", "note", "add", "undo", "show", "cancel", "answer")

PROMPT = (
    "You help a construction superintendent run a punch-list walkthrough over WhatsApp. "
    "They send photos with short captions; then a draft list; then who gets it; then a "
    "recap, where 'ok' sends. You get the walk's STATE (JSON) and ONE message from them. "
    "Work out what they want and answer with a JSON object only:\n"
    "{\"actions\": [ ... ], \"reply\": \"...\"}\n"
    "Actions (use only these, in the order to do them):\n"
    "- {\"do\": \"simple\"}: drop trades and locations for this walk; the list is just floor + "
    "description (\"ignore trades and locations\", \"just floor and description\", \"keep it "
    "simple\", \"don't need trades\").\n"
    "- {\"do\": \"detailed\"}: they want trades and locations after all.\n"
    "- {\"do\": \"send\", \"to\": null | \"me\" | \"group\" | \"<a person's name>\", \"due\": null | "
    "\"<when>\"}: finish / go on / send it. \"me\", \"myself\", \"to me\" is \"me\" (the walker). "
    "\"to the group\" is \"group\". Missing trades or locations never stop a send.\n"
    "- {\"do\": \"assign\", \"to\": \"me\" | \"group\" | \"<name>\", \"trade\": null | \"<trade>\"}: "
    "who gets the list (trade null: the whole list) or one trade's items.\n"
    "- {\"do\": \"due\", \"when\": \"<asap | no date | a day>\", \"trade\": null | \"<trade>\"}.\n"
    "- {\"do\": \"trade\", \"items\": [numbers], \"trade\": \"<trade>\"}.\n"
    "- {\"do\": \"location\", \"items\": [numbers] | \"since_last\" | \"missing\", \"place\": "
    "\"<their words for the place>\"}: since_last = the photos sent since their last "
    "location message (\"these are all roof\"); missing = every item with no location.\n"
    "- {\"do\": \"drop\", \"items\": [numbers]}.\n"
    "- {\"do\": \"words\", \"item\": n, \"text\": \"...\"}: replace what item n says.\n"
    "- {\"do\": \"note\", \"item\": n, \"text\": \"...\"}: more words about item n (during "
    "capture, a note with no number is about the last photo).\n"
    "- {\"do\": \"add\", \"text\": \"...\"}: a new item with no photo.\n"
    "- {\"do\": \"undo\"}: undo the last group location.\n"
    "- {\"do\": \"show\"}: show the list / where things stand.\n"
    "- {\"do\": \"cancel\"}: ONLY when they clearly say to cancel or throw away the walkthrough.\n"
    "- {\"do\": \"answer\"}: a question or small talk; the reply answers it.\n"
    "Rules: use only item numbers in STATE.numbers. Never invent a name: copy the name they "
    "said. Never send unless they ask to send, finish or go on. If you are not sure what "
    "they mean, use no action and ask ONE short question in the reply.\n"
    "reply: what you say back -- short, warm, plain, like a helpful person on site; at most "
    "2 lines; no command syntax (never \"2 → electrical\"), no lists of item numbers. Do not "
    "repeat what the code will show (the list, the recap); \"Got it.\" is fine. Answer in "
    "their language (English, Spanish, Yiddish)."
)

#: The stages, as the model reads them.
STAGES = {
    "capturing": "taking photos (each photo is an item; they say 'done' when finished)",
    "locating": "asked once where the items with no location are (they may skip)",
    "draft": "the draft list is shown; they fix it or say send",
    "assign": "asking who gets the list",
    "recap": "the recap is shown; 'ok' sends it now",
    "due": "the recap is shown; 'ok' sends it now",
}

_MAX_ITEMS = 80


def state_for(sess: Dict[str, Any], *, detail: str, walker: str = "",
              recipients: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the model is shown about the walk: never photo keys, ids or
    phone numbers -- the stage, the counts, the items (numbered, short) and
    who it goes to."""
    live = [it for it in sess.get("items") or [] if it.get("status", "draft") != "dropped"]
    items = []
    for it in punch.ordered(live)[:_MAX_ITEMS]:
        row = {"n": it.get("n"), "says": str(it.get("text") or "")[:60]}
        if (it.get("floor") or punch.UNKNOWN) != punch.UNKNOWN:
            row["floor"] = it["floor"]
        if (it.get("area") or punch.UNKNOWN) != punch.UNKNOWN:
            row["area"] = str(it["area"])[:40]
        if (it.get("trade") or punch.UNKNOWN) != punch.UNKNOWN:
            row["trade"] = it["trade"]
        items.append(row)
    status = sess.get("status") or "capturing"
    last = max(live, key=lambda it: it.get("captured") or 0) if live else None
    return {
        "stage": status, "stage_means": STAGES.get(status, status),
        "job": sess.get("job_name") or "",
        "detail": detail,
        "walker": walker,
        "item_count": len(live),
        "no_trade": sum(1 for it in live if (it.get("trade") or punch.UNKNOWN) == punch.UNKNOWN),
        "no_location": len(punch.missing_location(live)),
        "last_photo": last.get("n") if last else None,
        **({"asked_where_is": int(sess["asking"])}
           if status == "locating" and sess.get("asking") and not sess.get("where_asked") else {}),
        "numbers": [it.get("n") for it in live],
        "recipients": recipients or {},
        "trades": list(punch.TRADES),
        "items": items,
        **({"more_items": len(live) - _MAX_ITEMS} if len(live) > _MAX_ITEMS else {}),
    }


def user_message(state: Dict[str, Any], said: str) -> str:
    return "STATE:\n" + json.dumps(state, ensure_ascii=False, default=str) \
        + "\n\nMESSAGE:\n" + str(said or "")[:1000]


#: Words that say cancel: a "cancel" from the model needs them in the message.
_CANCEL = re.compile(r"\b(?:cancel\w*|throw\s+(?:it|this)\s+(?:away|out)|scrap|discard|delete\s+(?:it|the\s+"
                     r"(?:walk|list|walkthrough))|forget\s+(?:it|the\s+(?:walk|list|whole\s+thing))|abort"
                     r"|start\s+over|cancelar|borra(?:r)?\s+todo)\b", re.IGNORECASE)
#: Words that say send / finish / go on: a "send" at the recap (which sends
#: NOW) needs one of them, or a plain yes.
_GO = re.compile(r"\b(?:send|sent|go|go\s+ahead|ok(?:ay)?|yes|yeah|yep|sure|finish\w*|done|fine|good|great"
                 r"|perfect|correct|right|post|deliver|ship|manda\w*|env[ií]a\w*|dale|s[ií]|listo)\b",
                 re.IGNORECASE)

_ARROWS = re.compile(r"\s*(?:→|->|=>)\s*")


def _nums(v: Any, known: List[int]) -> List[int]:
    out: List[int] = []
    for x in v if isinstance(v, list) else [v]:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n in known and n not in out:
            out.append(n)
    return out


def _name(v: Any) -> Optional[str]:
    """"me", "group", or a name as said (short; no phone numbers)."""
    t = " ".join(str(v or "").split()).strip(" .!,")
    if not t or len(t) > 60 or re.search(r"\d{5,}", t):
        return None
    if punch.is_me(t):
        return "me"
    if re.fullmatch(r"(?i)(?:the\s+|our\s+|this\s+)?(?:job\s+|gc\s+|whatsapp\s+)?group(?:\s+chat)?", t):
        return "group"
    return t


def clean_reply(text: Any) -> str:
    """At most 2 lines, no arrows, nothing long."""
    t = str(text or "").strip()
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()][:2]
    t = _ARROWS.sub(" to ", "\n".join(lines))
    return t[:300].rstrip()


def clean_plan(got: Any, state: Dict[str, Any], said: str) -> Optional[Dict[str, Any]]:
    """The model's answer, checked against the walk. Returns {"actions":
    [...], "reply": str} with only actions that are safe to apply, or None
    when the answer is not one JSON object. Never a number not in the walk,
    a trade not known, a place that reads as none, a cancel the message did
    not say, or a send at the recap the message did not ask for."""
    if not isinstance(got, dict):
        return None
    known = [n for n in state.get("numbers") or [] if isinstance(n, int)]
    stage = state.get("stage")
    out: List[Dict[str, Any]] = []
    for a in got.get("actions") or []:
        if not isinstance(a, dict) or a.get("do") not in ACTIONS:
            continue
        do = a["do"]
        if do in ("simple", "detailed", "undo", "show", "answer"):
            out.append({"do": do})
        elif do == "cancel":
            if _CANCEL.search(said or ""):
                out.append({"do": "cancel"})
        elif do == "send":
            if stage in ("recap", "due") and not _GO.search(said or "") and not a.get("to"):
                continue                                    # a send at the recap is now: asked for
            act = {"do": "send", "to": _name(a.get("to")) if a.get("to") else None}
            due = punch.due_words(a.get("due")) if a.get("due") else None
            if due:
                act["due"] = due
            out.append(act)
        elif do == "assign":
            to = _name(a.get("to"))
            if not to:
                continue
            trade = punch.trade_word(str(a.get("trade") or "")) if a.get("trade") else None
            if a.get("trade") and not trade:
                continue                            # a trade it named but we don't know: never "all"
            out.append({"do": "assign", "to": to, "trade": trade})
        elif do == "due":
            when = punch.due_words(a.get("when"))
            if not when:
                continue
            trade = punch.trade_word(str(a.get("trade") or "")) if a.get("trade") else None
            if a.get("trade") and not trade:
                continue
            out.append({"do": "due", "when": when, "trade": trade})
        elif do == "trade":
            ns, trade = _nums(a.get("items"), known), punch.trade_word(str(a.get("trade") or ""))
            if ns and trade:
                out.append({"do": "trade", "items": ns, "trade": trade})
        elif do == "location":
            loc = punch.free_location(a.get("place"))
            if not (loc.get("floor") or loc.get("area")):
                continue
            scope = a.get("items")
            if scope in ("since_last", "missing"):
                out.append({"do": "location", "scope": scope, "items": [], "place": loc})
            else:
                ns = _nums(scope, known)
                if ns:
                    out.append({"do": "location", "scope": "numbers", "items": ns, "place": loc})
        elif do == "drop":
            ns = _nums(a.get("items"), known)
            if ns:
                out.append({"do": "drop", "items": ns})
        elif do in ("words", "note"):
            ns = _nums(a.get("item"), known)
            text = " ".join(str(a.get("text") or "").split())[:300]
            if ns and text:
                out.append({"do": do, "item": ns[0], "text": text})
        elif do == "add":
            text = " ".join(str(a.get("text") or "").split())[:300]
            if text:
                out.append({"do": "add", "text": text})
    return {"actions": out[:20], "reply": clean_reply(got.get("reply"))}


# ── WHEN THE MODEL IS DOWN ───────────────────────────────────────────────────
#
# Only then: the walk still understands the plain asks it was stuck on.

_SIMPLE = re.compile(
    r"(?:\b(?:ignore|skip|forget|drop|no\s+need\s+(?:for|of)|don'?t\s+(?:need|want|care\s+about)|without|no)\s+"
    r"(?:the\s+|all\s+(?:the\s+)?)?(?:trades?|locations?)\b"
    r"|\bjust\s+(?:the\s+)?floors?\s+(?:and|&|\+)\s+(?:the\s+)?descriptions?\b"
    r"|\bfloors?\s+(?:and|&|\+)\s+(?:the\s+)?descriptions?\s+(?:is\s+|are\s+)?(?:enough|fine|ok|good)\b"
    r"|\bkeep\s+it\s+simple\b|\bsimple\s+(?:list|mode|version)\b)", re.IGNORECASE)
_DETAILED = re.compile(r"\b(?:detailed\s+(?:list|mode|version)|add\s+(?:the\s+)?trades|with\s+trades"
                       r"|i\s+want\s+(?:the\s+)?trades)\b", re.IGNORECASE)


def wants_simple(text: Any) -> bool:
    return bool(_SIMPLE.search(str(text or "")))


def wants_detailed(text: Any) -> bool:
    return bool(_DETAILED.search(str(text or ""))) and not wants_simple(text)


SIMPLE_OK = "Got it — just floor and description for this list."
DETAILED_OK = "Got it — trades and locations back on for this list."
