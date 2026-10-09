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


def due_phrase(body: str) -> Optional[str]:
    """The last date the message names, as written, when the code can read
    it (otherwise None)."""
    found = [m.group(0) for m in _DUE_RE.finditer(body or "")]
    for text in reversed(found):
        if wa.parse_due(text, datetime(2026, 1, 5)) is not None:  # readable at all
            return text
    return None


def classify(body: str, has_file: bool = False) -> Optional[Dict[str, Any]]:
    """{kind: done|cancel|reschedule, due_text?} from the words alone, or
    None. A question is never an update ("is it done?")."""
    text = (body or "").strip()
    if not text:
        return {"kind": "done", "file": True} if has_file else None
    if "?" in text:
        return None
    if _CANCEL.search(text) or _FORGET.search(text):
        return {"kind": "cancel"}
    if _RESCHEDULE.search(text):
        due = due_phrase(text)
        if due:
            return {"kind": "reschedule", "due_text": due}
    if _DONE.search(text) and not _FUTURE.search(text):
        return {"kind": "done", "file": bool(has_file)}
    if has_file and len(text) <= 60 and not _FUTURE.search(text):
        return {"kind": "done", "file": True}
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
    if pk:
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
        if len(got["items"]) == 1 and got["link"] != "only_open":
            target = got["items"][0]
            out.append({"item_id": target["id"], "action": "state", "to": "cancelled",
                        "link": got["link"], "by": "requester"})
            for c in live:   # what answered the ask goes with it
                if c.get("parent_id") == target["id"]:
                    out.append({"item_id": c["id"], "action": "state", "to": "cancelled",
                                "link": "via_parent", "by": "requester"})
        elif got["items"]:
            for c in got["items"]:
                out.append({"item_id": c["id"], "action": "flag", "to": None,
                            "link": got["link"], "by": "requester",
                            "note": "possibly_cancelled"})
        return out

    owned = [c for c in live if c.get("owner") == sender and not c.get("multi")
             and (c.get("type") == "commitment"
                  or (kind == "done" and c.get("type") == "request"))]
    got = _pick(owned, upd)

    if kind == "reschedule":
        if len(got["items"]) == 1 and got["link"] != "ambiguous":
            return [{"item_id": got["items"][0]["id"], "action": "state",
                     "to": "rescheduled", "link": got["link"], "by": "owner"}]
        if got["items"]:
            return [{"item_id": c["id"], "action": "flag", "to": None,
                     "link": got["link"], "by": "owner", "note": "which_item"}
                    for c in got["items"]]
        # Someone else moving another person's date: flagged, never applied.
        others = [c for c in live if c.get("type") == "commitment"
                  and c.get("owner") and c.get("owner") != sender]
        # Only by a reply to it or its own topic words: the message just
        # before is not enough to pin someone else's date change on it.
        theirs = _pick(others, {**upd, "terms": upd.get("own_terms") or set(),
                                "previous_key": None, "own_terms": True})
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
    # A reply saying it is done to an ask put to nobody in particular: the
    # replier may well be who did it, but that is a guess, so an admin decides.
    rk = upd.get("reply_key")
    if rk and not got["items"]:
        unowned = [c for c in live if not c.get("owner") and not c.get("multi")
                   and c.get("type") in ("request", "commitment") and c.get("key") == rk
                   and c.get("requester") != sender]
        if unowned:
            return [{"item_id": c["id"], "action": "possibly_done", "to": "possibly_done",
                     "link": "reply", "by": "unknown_owner"} for c in unowned]
    if len(got["items"]) == 1 and got["link"] == "only_open":
        return _done(got["items"][0], "only_open", live)
    if got["items"]:
        return [{"item_id": c["id"], "action": "possibly_done", "to": "possibly_done",
                 "link": "ambiguous", "by": "owner"} for c in got["items"]]
    return []


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


def bursts(rows: List[dict], gap_seconds: int = BURST_SECONDS) -> List[List[dict]]:
    """Consecutive TEXT rows from one sender, each within `gap_seconds` of
    the one before, are one message ("Np" + "Tomorrow"). A file or a reply
    starts its own."""
    out: List[List[dict]] = []
    for r in rows:
        if out:
            last = out[-1][-1]
            a, b = _when(last), _when(r)
            if (str(r.get("sender") or "") == str(last.get("sender") or "")
                    and not media_of(r) and not media_of(last)
                    and not str(r.get("quoted_message_id") or "").strip()
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
