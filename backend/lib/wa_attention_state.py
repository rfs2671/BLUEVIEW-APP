"""Attention: commitment state updates — the pure parts.

An item moves  open → rescheduled → done | cancelled  on a later message, in
SHADOW MODE (nothing is posted, nobody is messaged). The rules:

  * WHAT the update says is read by code from its words, never by the model:
      done        "sent", "done", "finished", "delivered"... (no future
                  words, no question), or a file the owner attaches
      cancelled   "never mind", "cancel", "scratch that", "scope changed"...
      rescheduled a change word ("actually", "instead", "moved", "not
                  happening"...) and a new date the code can read
  * WHO may make it:
      done / rescheduled  the item's OWNER only. Anyone else saying "sent"
                          changes nothing; anyone else saying "actually
                          Monday" changes nothing and is flagged for review.
      cancelled           the REQUESTER (and the items answering their ask).
  * WHICH item it is about (the link), strongest first:
      reply       the update quotes the item's message (or its parent's)
      previous    the message just before the update is the item's own
      owner_topic the owner's open items that share a topic word with the
                  update (or with the message just before it), exactly one
      only_open   an update with no topic words and the owner has exactly
                  one open item
    Two or more candidates and nothing to choose between them: every one is
    marked "possibly done" for an admin. NEVER CLOSED ON A GUESS.
  * EVIDENCE OR SILENCE: every state change carries the exact words of the
    message that made it (or the file it attached), and keeps a timeline
    entry an admin marks Correct / Wrong.

No database, no network: server.py reads candidates and writes the result.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from lib import multilang as ml
from lib import wa_attention as wa

# Where an item can be. "open" and "rescheduled" are live; "possibly_done"
# and "possibly_resolved" wait for an admin; the rest are closed.
LIVE = ("open", "rescheduled", "possibly_done")
OPEN_LIST = ("open", "rescheduled", "possibly_done", "possibly_resolved")
STATE_VERDICTS = ("correct", "wrong")

# Two messages from one sender less than this apart are one message ("Np" /
# "Tomorrow"); the worker waits this long before reading the last one.
BURST_SECONDS = 60
# The message before an update says what it is about only if this recent.
PREVIOUS_SECONDS = 2 * 60 * 60

_FUTURE = re.compile(
    r"\b(will|i'll|we'll|he'll|she'll|they'll|gonna|going to|tomorrow|tmrw"
    r"|later|tonight)\b", re.IGNORECASE)
_DONE = re.compile(
    r"\b(sent|done|finished|completed|delivered|dropped (it |them )?off|uploaded"
    r"|attached|ordered|submitted|installed|it'?s in|they'?re in|took care of it)\b",
    re.IGNORECASE)
_CANCEL = re.compile(
    r"\b(never ?mind|nvm|cancel(l?ed)?|scratch that|no longer need\w*"
    r"|don'?t need|not needed|hold off|scope (has )?changed|changed (the )?scope)\b",
    re.IGNORECASE)
# "Forget the meter, DEP already approved it": "forget" as the instruction
# that opens a sentence -- not "I always forget the meter", not "don't
# (ever) forget the meter".
_FORGET = re.compile(
    r"(?:^|[.!?;,]\s*)(?:(?:ok(?:ay)?|actually|nah|so|oh)[,.]?\s+)?"
    r"forget (it|that|this|about|the)\b", re.IGNORECASE)
_RESCHEDULE = re.compile(
    r"\b(actually|instead|moved?|moving|pushed|push(ing)? it|not happening"
    r"|change[sd]? to|rather)\b", re.IGNORECASE)

# The same in Spanish and Yiddish (lib/multilang.py), read on the folded text
# (lowercase, accents stripped: "ya lo mandé" -> "ya lo mande").
_ML_DONE = re.compile(r"\b(?:" + ml.alternation(ml.DONE) + "|" + ml.alternation(ml.SENT) + r")\b")
_ML_CANCEL = re.compile(r"\b(?:" + ml.alternation(ml.CANCEL) + "|" + ml.alternation(ml.NEVER_MIND) + r")\b")
_ML_RESCHEDULE = re.compile(r"\b(?:" + ml.alternation(ml.ACTUALLY)
                            + r"|movid[oa]|cambiad[oa]|pasa(?:do)? (?:al|para)|lo pasamos"
                            + r"|iberleygt|ibergeleygt|opgeleygt)\b")
_ML_FUTURE = re.compile(r"\b(?:voy a|vamos a|va a|van a|manana|luego|despues|mas tarde|ahorita"
                        r"|vel|veln|vet|morgn|morgen|shpeter)\b")

# Date words the due parser reads; the LAST one in a message is the new date
# ("Wednesday is not happening. Gonna take care of it Friday" → Friday).
_DAY = (r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|mon|tues?|wed|thur?s?|fri|sat|sun")
_DUE_RE = re.compile(
    r"\b(?:(?:by|on|until|till) )?(?:"
    r"(?:\d{1,2}(?::\d{2})?\s?(?:am|pm) )?(?:" + _DAY + r")(?: \d{1,2}(?::\d{2})?\s?(?:am|pm))?"
    r"|tomorrow(?: morning| afternoon)?|tmrw|today|tonight|eod|end of (?:the )?day"
    r"|the \d{1,2}(?:st|nd|rd|th)|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?"
    # Spanish and Yiddish (read by wa.parse_due through multilang). "por la
    # mañana" is the morning, not tomorrow.
    r"|(?:el )?(?:pr[oó]xim[oa] )?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
    r"(?: (?:pr[oó]ximo|que viene))?"
    r"|pasado ma[ñn]ana|(?<!la )ma[ñn]ana|hoy|en \d{1,2} (?:d[ií]as|semanas)"
    r"|\d{1,2} de (?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    r"|(?:nekhstn |nechstn |kumendikn )?(?:zuntik|montik|dinstik|mitvokh|mitvoch|donershtik|fraytik|shabes|shabbos)"
    r"|iber ?morg[e]?n|morg[e]?n|ha[iy]nt|in \d{1,2} (?:vokhn|teg)"
    r"|איבערמארגן|מארגן|היינט|זונטיק|מאנטיק|דינסטיק|מיטוואך|דאנערשטיק|פרייטיק|שבת"
    r")\b", re.IGNORECASE)

MULTI_OWNER_RE = re.compile(
    r"\b(everyone|everybody|all of you|you all|y'?all|you guys|all subs|every sub)\b",
    re.IGNORECASE)

# Words that say nothing about WHAT an item is about.
_GENERIC = set("""
send sent sending get got take care need needed needs bring bringing will can
someone anyone everyone everybody guys now later today tomorrow morning
afternoon tonight week next actually done came come coming have mine yours
thanks thank yeah yep yes sure lol eod time asap please pls happening
monday tuesday wednesday thursday friday saturday sunday mon tue tues wed
thu thur thurs fri sat sun am pm still out back here there one ones things
thing stuff confirm know let try new updated update order ordering ordered
take taking make making give giving finish finished sending fine good great deadline hard
""".split())


def new_event_id() -> str:
    return uuid.uuid4().hex[:12]


def short_id(message_id: Any) -> str:
    """WhatsApp ids come short ("3EB0...") or serialized
    ({fromMe}_{chatId}_{id}[_{participant}]). Replies quote the short one."""
    raw = str(message_id or "").strip()
    parts = raw.split("_")
    if len(parts) >= 3 and parts[0] in ("true", "false") and "@" in parts[1]:
        return parts[2]
    return raw


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def topic_terms(*texts: Optional[str]) -> Set[str]:
    """The words that say what something is about: risers, load calcs,
    sleeve layout. Not dates, not "send", not names one letter long."""
    out: Set[str] = set()
    for t in texts:
        for w in re.findall(r"[a-z][a-z0-9']+", str(t or "").lower().translate(wa._TYPO)):
            w = w.strip("'")
            if w.endswith("'s"):
                w = w[:-2]
            if len(w) < 3 or "'" in w or w in wa._STOP or w in _GENERIC:
                continue
            w = _stem(w)
            if w not in _GENERIC:
                out.add(w)
    return out


# Words a commitment can carry without naming what it is about: "Sunday.
# I'll keep u posted", "Sure I'll get it before 8am".
_NOT_A_SUBJECT = {"keep", "posted", "post", "before", "after", "update", "updates",
                  "back", "sure", "asap", "soon", "later", "morning", "afternoon",
                  "tonight", "week", "today", "tmrw", "tomorrow", "handle", "check",
                  "look", "try", "first", "thing", "eod"}


def own_subject(quote: str) -> Set[str]:
    """What a commitment names as its own subject ("the updated logistics
    plan" -> {logistic, plan}); empty for "Np", "I'll take care of it",
    "Sunday. I'll keep u posted"."""
    return {t for t in topic_terms(quote) if t not in _NOT_A_SUBJECT}


def due_phrase(body: str) -> Optional[str]:
    """The last date the message names, as written, when the code can read
    it (otherwise None)."""
    found = [m.group(0) for m in _DUE_RE.finditer(body or "")]
    for text in reversed(found):
        if wa.parse_due(text, datetime(2026, 1, 5)) is not None:  # readable at all
            return text
    return None


# A new time on the same day: "till 11-12", "by 3pm", "before 8am". A bare
# "11-12" counts only after till/until/by/before/at/around.
_TIME_RE = re.compile(
    r"\b(?:(?:by|before|at|till|until|til|around)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    r"(?:\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|\d{1,2}(?::\d{2})?\s*(?:am|pm)(?:\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)"
    r"(?![\w:])", re.IGNORECASE)


def time_phrase(body: str) -> Optional[str]:
    """The last time of day the message names, as written, else None."""
    found = [m.group(0) for m in _TIME_RE.finditer(body or "")]
    return found[-1] if found else None


# "Mike already did", "Jose sent them", "already done": it is done, and the
# words say someone else did it -- what the asking side says to close an
# item ("Never mind the panel confirm, Mike already did" is done, not
# cancelled). A name is capitalised; "I" is never "someone else".
_NOT_DOERS = {"Yes", "No", "Never", "Who", "What", "Already", "Just", "Also", "Ok",
              "Okay", "It", "That", "This", "Nvm", "Mind", "And", "But", "So", "We"}
_DONE_BY = re.compile(
    r"\b(?:([A-Z][a-z]+)|(?i:he|she|they))\s+(?:(?i:already|just)\s+)?"
    r"(?i:did(?: it)?|sent (?:it|them)|handled it|took care of it|got it done|finished it)\b"
    r"|(?i:\balready (?:done|sent|did|delivered|submitted|handled|taken care of)\b)")


def done_by_other(text: str) -> bool:
    return doer(text) is not None


def doer(text: str) -> Optional[str]:
    """Who the words say did it: a first name (lowercase), "" for he / she /
    they / "already done", None when they say nobody else did."""
    for m in _DONE_BY.finditer(text or ""):
        if m.group(1) and m.group(1) in _NOT_DOERS:
            continue
        before = re.findall(r"[a-z']+", (text or "")[:m.start()].lower())
        if not m.group(1) and before and before[-1] in _FIRST_PERSON:
            continue    # "I already sent the panel": the sender did it
        return (m.group(1) or "").lower()
    return None


_FIRST_PERSON = {"i", "we", "i've", "we've", "ive", "weve", "me", "us"}


def classify(body: str, has_file: bool = False) -> Optional[Dict[str, Any]]:
    """{kind: done|cancel|reschedule, due_text?, by_other?} from the words
    alone, or None. A question is never an update ("is it done?")."""
    text = (body or "").strip()
    if not text:
        return {"kind": "done", "file": True} if has_file else None
    if "?" in text or "¿" in text:
        return None
    ft = ml.fold(text)
    future = bool(_FUTURE.search(text) or _ML_FUTURE.search(ft))
    if _CANCEL.search(text) or _FORGET.search(text) or _ML_CANCEL.search(ft):
        if done_by_other(text):
            # "Never mind the panel confirm, Mike already did": done.
            return {"kind": "done", "by_other": True}
        return {"kind": "cancel"}
    if _RESCHEDULE.search(text) or _ML_RESCHEDULE.search(ft):
        due = due_phrase(text)
        if due:
            return {"kind": "reschedule", "due_text": due}
        at = time_phrase(text)
        if at:
            # "Actually give me till 11-12": same day, a new time.
            return {"kind": "reschedule", "due_text": at, "time_only": True}
    if done_by_other(text) and not future:
        return {"kind": "done", "by_other": True}
    if (_DONE.search(text) or _ML_DONE.search(ft)) and not future:
        return {"kind": "done", "file": bool(has_file)}
    if has_file and len(text) <= 60 and not future:
        return {"kind": "done", "file": True}
    return None


# ── SHORT ACKS ───────────────────────────────────────────────────────────────
#
# "Np", "ok", "will do", "Np / Tomorrow", "👍 tmrw": a yes to an ask, with a
# date or not ("lol ok", "sure 😂" are not). Too short for the model to read on its own (pass 1 and 2 lost
# them), so the code reads them: a yes from the person the ask was put to is
# a commitment to THAT ask; a yes with no ask put to them is nothing.

ACK_WINDOW_SECONDS = 30 * 60
_ACK_STRONG = {"np", "ok", "okay", "k", "kk", "sure", "yep", "yup", "yes", "yeah",
               "copy", "roger", "will", "got", "on", "👍", "👌", "🫡", "✅", "💪"}
# Spanish and Yiddish yeses ("sí", "dale", "ya" / "yo", "gut", "zicher"),
# compared accent-free.
_ACK_STRONG |= {"si", "dale", "vale", "claro", "listo", "ya", "perfecto", "va", "okey",
                "yo", "gut", "zicher", "zikher", "avade", "takeh", "יא", "גוט", "זיכער", "אוודאי"}
_ACK_WORDS = _ACK_STRONG | {"no", "problem", "prob", "do", "thing", "you", "it", "that",
                            "de", "una", "jefe", "bueno", "gracias", "shoyn", "a", "sheynem",
                            "dank", "boss",
                            "thanks", "thx", "ty", "boss", "bro", "man", "🙏", "will",
                            # "I" / "Kk" sent as two messages, merged.
                            "i"}


def ack(body: str) -> Optional[Dict[str, Any]]:
    """{due_text} when the whole message is a short yes (with or without a
    date the code can read), else None."""
    text = (body or "").strip()
    if not text or "?" in text or len(text) > 40:
        return None
    due = due_phrase(text)
    rest = text
    if due:
        i = rest.lower().rfind(due.lower())
        rest = rest[:i] + rest[i + len(due):]
    if ml.alternation(ml.SARCASM) and re.search(ml.alternation(ml.SARCASM), ml.fold(text)):
        return None     # "ya ya, seguro", "sí claro"
    rest = re.sub(r"[,.!;:\-¡¿]+", " ", ml.fold(rest).translate(wa._TYPO))
    # Emoji glued to words ("👍tmrw") stand on their own.
    rest = re.sub(r"([^\w\s'])", r" \1 ", rest)
    words = [w for w in rest.split() if w not in ("\ufe0f",)]
    if not words or len(words) > 5:
        return None
    if any(w in _SARCASM for w in words):
        return None     # "lol ok", "sure 😂": not a yes
    if not all(w in _ACK_WORDS for w in words):
        return None
    if not any(w in _ACK_STRONG for w in words):
        return None
    if words == ["will"]:
        return None
    return {"due_text": due}


ACK_PREVIOUS_SECONDS = 10 * 60
_SARCASM = {"lol", "lmao", "lmfao", "rofl", "haha", "hahaha", "hehe", "😂", "🤣", "🙄", "😅",
            "jaja", "jajaja", "jajajaja", "jeje", "jejeje"}


def is_mine(c: Dict[str, Any], upd: Dict[str, Any]) -> bool:
    """Is item `c` the sender's? By sender digits, or by who they resolve to
    (a user or a person in People) -- one person can post from a phone id
    and an @lid privacy id."""
    if c.get("owner") and c.get("owner") == upd.get("sender"):
        return True
    ref = c.get("owner_ref")
    return bool(ref and ref == upd.get("sender_ref"))


def ack_target(upd: Dict[str, Any], items: List[dict]) -> Optional[Dict[str, Any]]:
    """{ask, how, confident} for the open ask a short yes answers, or None.
    `upd`: sender, sender_name, reply_key, sent_at, and `recent` -- the
    messages before the yes, oldest first, each {key, sender, sent_at}.

      1. reply    it replies to the ask                         confident
      2. previous an ask put to nobody, under 10 minutes old,    POSSIBLY
                  with no one else (but who asked and who says
                  yes) writing in between
      3. named    the one ask put to this sender by @mention or  confident
                  by name in the last 30 minutes

    A reply to something else, two named asks, or a third person in
    between: None -- never a guess."""
    sender = upd.get("sender") or ""
    sent_at = upd.get("sent_at")
    asks = [c for c in items if c.get("type") in ("request", "question")
            and c.get("status") in LIVE and c.get("requester") != sender
            and not c.get("multi")]

    def age(at):
        if not (isinstance(at, datetime) and isinstance(sent_at, datetime)):
            return None
        a = at.replace(tzinfo=None) if at.tzinfo else at
        b = sent_at.replace(tzinfo=None) if sent_at.tzinfo else sent_at
        return (b - a).total_seconds()

    rk = upd.get("reply_key")
    if rk:
        hit = [c for c in asks if c.get("key") == rk]
        return {"ask": hit[0], "how": "reply", "confident": True} if hit else None

    by_key = {c.get("key"): c for c in asks if c.get("key")}
    seen = set()
    for m in reversed(upd.get("recent") or []):
        g = age(m.get("sent_at"))
        if g is None or g < 0 or g > ACK_PREVIOUS_SECONDS:
            break
        c = by_key.get(m.get("key"))
        if c and (not c.get("owner") or is_mine(c, upd)) \
                and not c.get("owner_possibly"):
            if seen <= {sender, c.get("requester")}:
                return {"ask": c, "how": "previous",
                        "confident": is_mine(c, upd)}
            break
        seen.add(str(m.get("sender") or ""))

    first = (upd.get("sender_name") or "").strip().split(" ")[0].lower()
    mine = [c for c in asks if 0 <= (age(c.get("sent_at")) or -1) <= ACK_WINDOW_SECONDS and (
        (is_mine(c, upd) and not c.get("owner_possibly"))
        or (len(first) >= 2 and first in re.findall(r"[a-z]+", (c.get("owner_text") or "").lower())))]
    if len(mine) == 1:
        return {"ask": mine[0], "how": "named", "confident": True}
    return None


def is_multi_owner(owner_text: Optional[str], mentions: Iterable[str] = ()) -> bool:
    return bool(MULTI_OWNER_RE.search(owner_text or "")) or len(list(mentions)) > 1


# ── WHICH ITEM ───────────────────────────────────────────────────────────────
#
# Candidates are plain dicts the server builds from attention_items:
#   id, type, status, owner (sender digits of the person who owes it, or ""),
#   requester (sender digits), key (short id of its message), parent_key,
#   parent_id, topic (set), multi (bool)

def _one_thread(hit: List[dict]) -> List[dict]:
    """An ask and the commitment answering it are one thing to finish:
    "Just sent sleeves layout" matches both, and is about the commitment
    (done on it closes the ask too). Keep the answer, drop its ask."""
    ids = {c["id"] for c in hit}
    return [c for c in hit if not any(o.get("parent_id") == c["id"] and o["id"] in ids
                                      for o in hit)]


def _pick(cands: List[dict], upd: dict) -> Dict[str, Any]:
    """{items, link} by reply, previous message, topic, only-open."""
    got = _pick_raw(cands, upd)
    items = _one_thread(got["items"])
    if got["link"] == "ambiguous" and len(items) == 1:
        # An ask and its own answer were all there was: one thing open.
        return {"items": items, "link": "only_open"}
    return {**got, "items": items}


def _pick_raw(cands: List[dict], upd: dict) -> Dict[str, Any]:
    rk, pk = upd.get("reply_key"), upd.get("previous_key")
    if rk:
        hit = [c for c in cands if rk in (c.get("key"), c.get("parent_key"))]
        if hit:
            return {"items": hit, "link": "reply"}
    # A reply is the strongest link: a reply to something else is never
    # pinned on the message that happened to come before it.
    if pk and not rk:
        hit = [c for c in cands if c.get("key") == pk]
        if hit:
            return {"items": hit, "link": "previous"}
    terms = set(upd.get("terms") or ())
    if terms:
        hit = [c for c in cands if terms & set(c.get("topic") or ())]
        if hit:
            return {"items": hit, "link": "owner_topic"}
    if not upd.get("own_terms") and len(cands) == 1:
        return {"items": cands, "link": "only_open"}
    if not upd.get("own_terms") and len(cands) > 1:
        return {"items": cands, "link": "ambiguous"}
    return {"items": [], "link": None}


def decide(upd: Dict[str, Any], items: List[dict]) -> List[Dict[str, Any]]:
    """What a classified update does. `upd`: kind, sender, reply_key,
    previous_key, terms (the update's and the previous message's topic
    words), own_terms (the update's own), due_text.

    Returns actions: {item_id, action: state|part_done|possibly_done|flag,
    to, link, by}."""
    kind, sender = upd["kind"], upd.get("sender") or ""
    live = [c for c in items if c.get("status") in LIVE]
    out: List[Dict[str, Any]] = []

    if kind == "cancel":
        mine = [c for c in live if c.get("requester") == sender
                and c.get("type") in ("request", "question")]
        got = _pick(mine, upd)
        if not got["items"] and upd.get("sender_gc"):
            # GC staff call off anyone's ask by what it is about (a reply to
            # it, or its own subject words): never by "the one open".
            got = _by_subject([c for c in live if c.get("type") in ("request", "question")],
                              upd)
            if len(got["items"]) == 1:
                got = {**got, "by": "gc_staff"}
        if len(got["items"]) == 1 and got["link"] != "only_open":
            target = got["items"][0]
            by = got.get("by") or "requester"
            out.append({"item_id": target["id"], "action": "state", "to": "cancelled",
                        "link": got["link"], "by": by})
            for c in live:   # what answered the ask goes with it
                if c.get("parent_id") == target["id"]:
                    out.append({"item_id": c["id"], "action": "state", "to": "cancelled",
                                "link": "via_parent", "by": by})
        elif got["items"]:
            out.append(_review("cancel", got["items"], got["link"], "requester",
                               "possibly_cancelled"))
        return out

    owned = [c for c in live if is_mine(c, upd) and not c.get("multi")
             and (c.get("type") == "commitment"
                  or (kind == "done" and c.get("type") == "request"))]
    got = _pick(owned, upd)

    if kind == "reschedule":
        if len(got["items"]) == 1 and got["link"] != "ambiguous":
            return [{"item_id": got["items"][0]["id"], "action": "state",
                     "to": "rescheduled", "link": got["link"], "by": "owner"}]
        if got["items"]:
            return [_review("reschedule", got["items"], got["link"], "owner", "which_item")]
        # Someone else moving another person's date: flagged, never applied.
        others = [c for c in live if c.get("type") == "commitment"
                  and c.get("owner") and not is_mine(c, upd)]
        # Only by a reply to it or its own topic words: the message just
        # before is not enough to pin someone else's date change on it.
        theirs = _pick(others, {**upd, "terms": upd.get("own_terms") or set(),
                                "previous_key": None, "own_terms": True})
        if len(theirs["items"]) > 1:
            return [_review("reschedule", theirs["items"], theirs["link"], "other",
                            "not_owner")]
        return [{"item_id": c["id"], "action": "flag", "to": None,
                 "link": theirs["link"], "by": "other", "note": "not_owner"}
                for c in theirs["items"]]

    # done. A clear link to one of the owner's items first; then an ask made
    # of everyone that the update answers ("Sent mine" under "Everyone send
    # insurance certs"); only then the owner's items with nothing to tell
    # them apart.
    if len(got["items"]) == 1 and got["link"] in ("reply", "previous", "owner_topic"):
        return _done(got["items"][0], got["link"], live)
    # This person's part of an ask made of everyone: the ask stays open for
    # the rest.
    multi = [c for c in live if c.get("multi") and c.get("type") == "request"]
    m = _pick(multi, {**upd, "own_terms": True})
    if len(m["items"]) == 1 and m["link"] in ("reply", "previous", "owner_topic"):
        return [{"item_id": m["items"][0]["id"], "action": "part_done", "to": None,
                 "link": m["link"], "by": "owner"}]
    # FROM THE ASKING SIDE: whoever asked, or GC staff, close an item by what
    # it is about (its subject words, or a reply to it) -- "Never mind the
    # panel confirm, Mike already did". Only when the words say someone else
    # did it ("sent it" is the sender's own doing); never by "the one open".
    rk = upd.get("reply_key")
    if not got["items"] and upd.get("by_other"):
        closed = _close_from_asking_side(upd, live)
        if closed is not None:
            return closed
    # A reply saying it is done to an ask put to nobody in particular: the
    # replier may well be who did it, but that is a guess, so an admin decides.
    if rk and not got["items"]:
        unowned = [c for c in live if not c.get("owner") and not c.get("multi")
                   and c.get("type") in ("request", "commitment") and c.get("key") == rk
                   and c.get("requester") != sender]
        if unowned:
            return [{"item_id": c["id"], "action": "possibly_done", "to": "possibly_done",
                     "link": "reply", "by": "unknown_owner"} for c in unowned]
    if len(got["items"]) == 1 and got["link"] == "only_open":
        return _done(got["items"][0], "only_open", live)
    if len(got["items"]) > 1:
        return [_review("done", got["items"], "ambiguous", "owner", "possibly_done")]
    if got["items"]:
        return [{"item_id": c["id"], "action": "possibly_done", "to": "possibly_done",
                 "link": "ambiguous", "by": "owner"} for c in got["items"]]
    return []


def _by_subject(cands: List[dict], upd: dict) -> Dict[str, Any]:
    """{items, link} by a reply to it or its own subject words only."""
    got = _pick(cands, {**upd, "previous_key": None,
                        "terms": upd.get("own_terms") or set(), "own_terms": True})
    return got if got["link"] in ("reply", "owner_topic") else {"items": [], "link": None}


def _closer(c: dict, upd: dict, live: List[dict]) -> Optional[str]:
    """"requester" when the sender asked for it (or for the ask it answers),
    "gc_staff" when the sender is GC staff, else None."""
    sender = upd.get("sender") or ""
    if c.get("requester") == sender:
        return "requester"
    parent = next((p for p in live if p["id"] == c.get("parent_id")), None)
    if parent and parent.get("requester") == sender:
        return "requester"
    return "gc_staff" if upd.get("sender_gc") else None


def _close_from_asking_side(upd: dict, live: List[dict]) -> Optional[List[Dict[str, Any]]]:
    cands = [c for c in live if not c.get("multi") and not is_mine(c, upd)
             and c.get("type") in ("request", "commitment") and _closer(c, upd, live)]
    name = upd.get("doer") or ""
    # Who did it is not what it is about: "Mike" matches every item Mike has.
    got = _by_subject(cands, {**upd, "own_terms": set(upd.get("own_terms") or ()) - {name}})
    hit = got["items"]
    if not hit:
        return None
    if len(hit) > 1 and name:
        # "Mike already did": the item of the one it names.
        named = [c for c in hit if name in re.findall(r"[a-z]+", (c.get("owner_name") or "").lower())]
        hit = named or hit
    if len(hit) > 1:
        # A confirmed owner's item over one only possibly theirs.
        sure = [c for c in hit if not c.get("owner_possibly")]
        hit = sure or hit
    if len(hit) > 1:
        return [_review("done", hit, got["link"], "requester", "which_item")]
    target = hit[0]
    return [{**a, "by": _closer(target, upd, live)} for a in _done(target, got["link"], live)]


# ── HANDOVER ─────────────────────────────────────────────────────────────────
#
# "Patricia's out sick, I'll send the risers Friday": Patricia's item is the
# sender's now. A named person is out / can't, and the sender takes it on --
# or "covering for Patricia". Confident (reassigned) when the item is the one
# the words are about, or the two work for the same company; otherwise the
# item is flagged for an admin and nobody is chased on it.

_ABSENT = re.compile(
    r"\b([a-z]{2,})(?:'s| is| was| has been)?\s+(?:out|off|sick|away|home sick|on vacation"
    r"|on leave|not (?:in|here|around|coming)|can'?t make it|can'?t do it|cannot"
    r"|can'?t|won'?t be able|isn'?t able)\b", re.IGNORECASE)
_TAKEOVER = re.compile(
    r"\b(?:covering for|cover(?:ing)? for|taking over (?:for|from)|filling in for"
    r"|i'?ll take over (?:for|from)|i'?ll cover for)\s+([a-z]{2,})\b", re.IGNORECASE)
_TAKE_ON = re.compile(
    r"\b(?:i'?ll|i will|i'?m gonna|i got it|i'?ll take it|i'?ll handle|i'?ll cover|on me)\b",
    re.IGNORECASE)
_NOT_NAMES = {"he", "she", "they", "it", "we", "you", "that", "this", "there", "who",
              "pump", "power", "water", "elevator", "lift", "crew", "truck", "everyone"}


def handover_name(body: str) -> Optional[str]:
    """The first name (lowercase) of who is out, when the sender takes their
    work on; else None."""
    text = norm_quote(body)
    m = _TAKEOVER.search(text)
    if m and m.group(1).lower() not in _NOT_NAMES:
        return m.group(1).lower()
    if not _TAKE_ON.search(text):
        return None
    for m in _ABSENT.finditer(text):
        name = m.group(1).lower()
        if name not in _NOT_NAMES and name not in wa._STOP:
            return name
    return None


def decide_handover(upd: Dict[str, Any], items: List[dict]) -> List[Dict[str, Any]]:
    """`upd`: sender, sender_ref, own_terms, reply_key, same_company (the
    sender and the named person work for one company), named_ref.
    Returns [{item_id, action: handover|flag, link, by, note?}] or one
    review entry."""
    ref = upd.get("named_ref")
    if not ref or ref == upd.get("sender_ref"):
        return []
    theirs = [c for c in items if c.get("status") in LIVE and c.get("owner_ref") == ref
              and not c.get("multi") and c.get("type") in ("commitment", "request")]
    theirs = _one_thread(theirs)
    if not theirs:
        return []
    got = _by_subject(theirs, upd)
    hit, subject = got["items"], bool(got["items"])
    link = got["link"]
    if not hit and len(theirs) == 1:
        hit, link = theirs, "only_open"
    if len(hit) != 1:
        return [_review("handover", hit or theirs, link or "ambiguous", "other",
                        "possible_handover")]
    if subject or upd.get("same_company"):
        return [{"item_id": hit[0]["id"], "action": "handover", "to": None,
                 "link": link, "by": "other"}]
    # Flagged with the ask it answers: a flagged answer no longer stands in
    # for its ask, and nobody is to be chased on either.
    flagged = [hit[0]] + [c for c in items if c["id"] == hit[0].get("parent_id")
                          and c.get("status") in LIVE]
    return [{"item_id": c["id"], "action": "flag", "to": None,
             "link": link if c is hit[0] else "via_child", "by": "other",
             "note": "possible_handover"} for c in flagged]


def _review(kind: str, items: List[dict], link: Optional[str], by: str,
            note: str) -> Dict[str, Any]:
    """ONE review entry for an update that could be about several items
    ("Sent" with two things open): the items themselves are left as they
    are; an admin says which one it was."""
    return {"action": "review", "kind": kind, "item_ids": [c["id"] for c in items],
            "link": link, "by": by, "note": note}


def _done(target: dict, link: str, live: List[dict]) -> List[Dict[str, Any]]:
    """Done on one item, and on the ask it answered / what answered it (not
    an ask made of everyone: that is closed one part at a time)."""
    out = [{"item_id": target["id"], "action": "state", "to": "done",
            "link": link, "by": "owner"}]
    for c in live:
        if c.get("multi") or c["id"] == target["id"]:
            continue
        if c["id"] == target.get("parent_id"):
            out.append({"item_id": c["id"], "action": "state", "to": "done",
                        "link": "via_child", "by": "owner"})
        elif c.get("parent_id") == target["id"]:
            out.append({"item_id": c["id"], "action": "state", "to": "done",
                        "link": "via_parent", "by": "owner"})
    return out


def state_precision(items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per change (rescheduled, done, cancelled, possibly_done, part_done,
    flag): correct, wrong, unreviewed, precision = correct / (correct +
    wrong), or None before any verdict."""
    out: Dict[str, Dict[str, Any]] = {}
    for it in items:
        for e in it.get("history") or []:
            if not isinstance(e, dict) or e.get("kind") in ("created", "follow_up"):
                continue
            name = e.get("to") if e.get("kind") == "state" else e.get("kind")
            row = out.setdefault(str(name), {"correct": 0, "wrong": 0, "unreviewed": 0})
            v = (e.get("review") or {}).get("verdict")
            row[v if v in STATE_VERDICTS else "unreviewed"] += 1
    for row in out.values():
        judged = row["correct"] + row["wrong"]
        row["precision"] = round(row["correct"] / judged, 3) if judged else None
    return out


def follow_up_of(question_terms: Set[str], asker: str, items: List[dict]) -> Optional[str]:
    """A question about something already promised ("B the risers came
    in?") is a follow-up on that commitment, not a new item: the id of the
    one open commitment it is about, else None."""
    if not question_terms:
        return None
    hit = [c for c in items if c.get("status") in LIVE and c.get("type") == "commitment"
           and c.get("owner") != asker and question_terms & set(c.get("topic") or ())]
    return hit[0]["id"] if len(hit) == 1 else None


_UPDATE_START = re.compile(
    r"^\W*(?:actually|just sent|sent|never ?mind|nvm|forget|done)\b", re.IGNORECASE)
_ML_UPDATE_START = re.compile(
    r"^\W*(?:en realidad|ya (?:lo |la )?(?:mande|envie)|listo|olvidalo|olvida eso|no importa"
    r"|eygntlekh|shoyn geshikt|geshikt|fartik|farges es)\b")


def starts_with_update(body: Any) -> bool:
    """"Actually give me till 11-12", "Just sent", "Never mind the …"."""
    b = str(body or "").strip()
    return bool(_UPDATE_START.match(b) or _ML_UPDATE_START.match(ml.fold(b)))


def _standalone(r: dict) -> bool:
    """A reply or an update is its own message: nothing merges into it and
    it merges into nothing. A reply is a reply even when only its quoted
    words arrived."""
    return (bool(str(r.get("quoted_message_id") or "").strip())
            or bool(str(r.get("quoted_body") or "").strip())
            or starts_with_update(r.get("body")))


_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201b": "'", "\u2032": "'",
                         "\u201c": '"', "\u201d": '"', "\u201f": '"', "\u2033": '"'})


def norm_quote(text: Any) -> str:
    """A message's words for matching a reply's quoted text: trimmed, curly
    quotes straight."""
    return str(text or "").translate(_QUOTES).strip()


def bursts(rows: List[dict], gap_seconds: int = BURST_SECONDS) -> List[List[dict]]:
    """Consecutive TEXT rows from one sender, each within `gap_seconds` of
    the one before, are one message ("Np" + "Tomorrow"). A file, a reply, or
    an update ("Actually …", "Sent", "Never mind …") starts its own and
    keeps its own id: what it updates is found from IT, not from what came
    just before."""
    out: List[List[dict]] = []
    for r in rows:
        if out:
            last = out[-1][-1]
            a, b = _when(last), _when(r)
            if (str(r.get("sender") or "") == str(last.get("sender") or "")
                    and not media_of(r) and not media_of(last)
                    and not _standalone(r) and not _standalone(last)
                    and a and b and 0 <= (b - a).total_seconds() < gap_seconds):
                out[-1].append(r)
                continue
        out.append([r])
    return out


def merge(burst: List[dict]) -> dict:
    """One message from a burst: the first row's identity, every row's
    words (one per line), mentions joined, the last row's time."""
    if len(burst) == 1:
        return burst[0]
    first, last = burst[0], burst[-1]
    msg = dict(first)
    msg["body"] = "\n".join(str(r.get("body") or "").strip() for r in burst
                            if str(r.get("body") or "").strip())
    msg["mentioned_jids"] = list(dict.fromkeys(
        j for r in burst for j in (r.get("mentioned_jids") or [])))
    msg["merged_ids"] = [str(r.get("message_id") or r.get("_id")) for r in burst]
    msg["created_at"] = last.get("created_at")
    msg["first_created_at"] = first.get("created_at")   # what came before it
    return msg


def _when(r: dict) -> Optional[datetime]:
    t = r.get("timestamp") or r.get("created_at")
    if isinstance(t, datetime):
        return t.replace(tzinfo=None) if t.tzinfo else t
    return None


MEDIA_TYPES = ("document", "image", "video")


def media_of(r: dict) -> str:
    t = str(r.get("media_type") or "").lower()
    if t in MEDIA_TYPES:
        return t
    return "image" if r.get("has_image") else ""


def text_of(r: dict) -> str:
    """The words of a row. A file's stored body can be a thumbnail rather
    than a caption; that is not words."""
    body = str(r.get("body") or "").strip()
    if media_of(r) and body and " " not in body and len(body) > 80:
        return ""
    return body


def file_quote(r: dict) -> str:
    name = str(r.get("file_name") or "").strip()[:80]
    kind = media_of(r) or "file"
    return f"[{kind}: {name}]" if name else f"[{kind}]"
