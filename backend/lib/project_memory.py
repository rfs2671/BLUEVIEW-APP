"""Project memory search v1: EVIDENCE OR SILENCE. Pure rules, no database.

What a project said, found again: the WhatsApp messages of the project's
linked groups and the filed daily reports, searched by words and by meaning,
and answered only with what a source says, cited.

THE CONTRACT
  - Every claim carries a source: who (their name in People, else their
    WhatsApp name), which group, when, and the exact words (<= QUOTE_MAX).
  - Every quote is checked against the sources that were retrieved for this
    question, verbatim (spacing and curly quotes aside). A claim whose quote
    is in none of them is dropped -- not reworded, not kept "probably".
  - Nothing left: NO_SOURCE. Never an answer from the model's own knowledge.
  - Never posts in a group. DM and the app only.

The server half (indexing, retrieval, the model call, the DM tool and the
app endpoints) is in server.py, "PROJECT MEMORY".
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

COLLECTION = "project_memory"
STATE = "project_memory_state"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMS = 1536
ANSWER_MODEL = "gpt-4o"
TEXT_INDEX = "project_memory_text"
VECTOR_INDEX = "project_memory_vector"

QUOTE_MAX = 200
TEXT_MAX = 1500              # stored per source row
TOP_K = 15                   # sources the model sees for an answer
STORY_MIN, STORY_MAX = 5, 12
RRF_K = 60

NO_SOURCE = "I can't find that in the project history."

SOURCE_WHATSAPP = "whatsapp"
SOURCE_DAILY = "daily_report"
SOURCE_ATTENTION = "attention"


# ── WHAT GOES IN ─────────────────────────────────────────────────────────────

def indexable_message(row: Dict[str, Any]) -> bool:
    """A group message of a linked group, from a person, with words."""
    if not row or row.get("is_dm") or str(row.get("sender") or "") == "bot":
        return False
    if row.get("project_id") in (None, ""):
        return False
    return bool(clean(row.get("body")))


def clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def field_text(v: Any) -> str:
    """A report field as words: a checkbox group (`{'boom_crane': True,
    'compressor': False}`) is the names ticked, a list is its items joined
    -- never the Python form of either (server._log_field, the same rule)."""
    if isinstance(v, dict):
        return ", ".join(str(k).replace("_", " ") for k, on in v.items() if on)
    if isinstance(v, list):
        return ", ".join(clean(x) for x in v if clean(x))
    return clean(v)


def daily_report_entries(log: Dict[str, Any]) -> List[Dict[str, str]]:
    """The text fields of a filed daily jobsite report, one entry each:
    [{key, label, text}]. Order as the report reads."""
    data = log.get("data") or {}
    out: List[Dict[str, str]] = []

    def add(key: str, label: str, text: Any) -> None:
        t = clean(text)
        if t:
            out.append({"key": key, "label": label, "text": t[:TEXT_MAX]})

    add("general", "Work summary", data.get("general_description"))
    for i, a in enumerate(data.get("activities") or []):
        if not isinstance(a, dict):
            continue
        who = " · ".join(x for x in (clean(a.get("company")), clean(a.get("trade"))) if x)
        where = clean(a.get("work_locations") or a.get("work_location"))
        what = clean(a.get("work_description"))
        if what:
            label = f"Activity: {who}" if who else "Activity"
            add(f"activity:{i}", label, f"{what} ({where})" if where else what)
    for i, o in enumerate(data.get("observations") or []):
        if not isinstance(o, dict):
            continue
        add(f"observation:{i}", "Observation", o.get("description") or o.get("note"))
    add("visitors", "Visitors / deliveries", field_text(data.get("visitors_deliveries")))
    add("equipment", "Equipment on site", field_text(data.get("equipment_on_site")))
    add("areas", "Areas visited", field_text(data.get("areas_visited")))
    return out


# ── RETRIEVAL ────────────────────────────────────────────────────────────────

_STOP = set("""
a an the and or but if of to in on at by for with from as is are was were be been
it its this that these those there here what who whom when where why how which
did do does done we you they he she i me my our your their us them can could
would should will shall may might about any some all into out up down over
again than then so just also very not no yes ok please pls hey hi happen happened
""".split())


def terms(text: Any) -> List[str]:
    """Search words: lowercase, no stop words, simple plural stem."""
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9']*", str(text or "").lower()):
        w = w.strip("'")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) < 2 or w in _STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def lexical_score(query_terms: Sequence[str], text: str) -> float:
    """BM25-shaped: each query word found counts, rarer-in-text less padded.
    Only for the fallback (no Atlas Search)."""
    if not query_terms:
        return 0.0
    words = terms(text)
    if not words:
        return 0.0
    counts: Dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    score = 0.0
    for q in set(query_terms):
        tf = counts.get(q, 0)
        if tf:
            score += (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * len(words) / 30.0))
    return score


def cosine(a: Optional[Sequence[float]], b: Optional[Sequence[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rrf(*ranked: Iterable[str], k: int = RRF_K) -> List[str]:
    """Reciprocal rank fusion of ranked id lists."""
    score: Dict[str, float] = {}
    for lst in ranked:
        for i, sid in enumerate(lst):
            score[sid] = score.get(sid, 0.0) + 1.0 / (k + i + 1)
    return [sid for sid, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))]


# ── THE MODEL'S ANSWER, CHECKED ──────────────────────────────────────────────

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‛": "'", "′": "'",
                         "“": '"', "”": '"', "‟": '"', "″": '"'})


def norm(text: Any) -> str:
    return " ".join(str(text or "").translate(_QUOTES).split()).lower()


def find_quote(quote: str, sources: Sequence[Dict[str, Any]],
               prefer: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The retrieved source whose text holds `quote` verbatim (spacing,
    case and curly quotes aside), the cited one first. None: it is in none."""
    q = norm(quote)
    if not q or len(clean(quote)) > QUOTE_MAX:
        return None
    ordered = sorted(sources, key=lambda s: s.get("sid") != prefer)
    for s in ordered:
        if q in norm(s.get("text")):
            return s
    return None


def is_full_story(query: str) -> bool:
    return bool(re.search(r"\b(what happened (with|to|on)|full story|the story|history of"
                          r"|timeline|walk me through)\b", query or "", re.IGNORECASE))


def parse_model(content: Any) -> Dict[str, Any]:
    try:
        data = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ── FAITHFULNESS: WHO DECIDED, AND WHETHER IT HAPPENED ───────────────────────
#
# Two ways a quote is right and the claim built on it is still wrong:
#   RELAYED  "Owner wants the 3B window changed", posted by Wendy: Wendy SAID
#            it; the owner WANTED it. The claim names the decider and says who
#            relayed it -- never the poster as the one who decided.
#   PLANNED  "We're getting a pump", "dumpster swap is set for Tuesday": an
#            intention or a plan, not an event. A claim that says it was done
#            is upgraded certainty: rewritten to "<what> planned for <when> (<who>, <date>)".

_ROLES = (r"owner|owners|client|architect|engineer|structural engineer|landlord|inspector"
          r"|dob|city|tenant|developer|consultant|expeditor|super|superintendent|pm|gc")
_DECIDE = (r"wants|wanted|asked(?: for)?|asks(?: for)?|approved|approves|requested|requests"
           r"|decided|decides|insists|insisted|prefers|preferred|needs|needed|said|says"
           r"|signed off(?: on)?|rejected|rejects")
_RELAYED = re.compile(
    r"\b(?:the\s+)?(?:(?i:(" + _ROLES + r"))|([A-Z][a-z]+(?: [A-Z][a-z]+)?))(?:'s?)?\s+"
    r"(?i:(?:has |have |just |already )?(" + _DECIDE + r"))\b")
_NOT_DECIDERS = {"I", "We", "You", "He", "She", "They", "It", "This", "That", "Got",
                 "Ok", "Okay", "Yes", "No", "Please", "Just", "Also"}


def relayed_decider(quote: str, poster: str = "",
                    people: Optional[Iterable[str]] = None) -> Optional[str]:
    """Who the words say wanted / approved / decided -- "the owner", "Mike" --
    when that is someone other than the poster. None when the poster speaks
    for themself ("I want", "we decided") or nobody is named.

    A role ("owner", "architect") always counts. A NAME counts only when it is
    one of `people` (first names of the people in these records): "Drawings
    approved" is not a person approving anything."""
    first = (poster or "").strip().split(" ")[0].lower()
    known = {p.strip().split(" ")[0].lower() for p in (people or []) if p and p.strip()}
    for m in _RELAYED.finditer(quote or ""):
        role, name = m.group(1), m.group(2)
        if role:
            r = role.lower()
            return {"dob": "DOB", "pm": "the PM", "gc": "the GC"}.get(r, f"the {r}")
        if name and name.split(" ")[0] not in _NOT_DECIDERS:
            lead = name.split(" ")[0].lower()
            if (first and lead == first) or lead not in known:
                continue                     # the poster, or not a person
            return name
    return None


_INTENT = re.compile(
    r"\b(will|won'?t|'ll|going to|gonna|getting|get(?:ting)? (?:a|the)|plan(?:s|ned|ning)?"
    r"|scheduled|set for|is set|are set|should|tomorrow|tmrw|next (?:week|mon|tue|wed|thu|fri"
    r"|sat|sun)\w*|later today|this afternoon|pending|waiting (?:on|for)|expect(?:ed|ing)?"
    r"|supposed to|to be (?:done|delivered|installed|poured)|on order|ordering|booked for)\b",
    re.IGNORECASE)
_DONE_WORDS = re.compile(
    r"\b(done|finished|completed|sent|poured|installed|delivered|is here|are here|arrived"
    r"|passed|is in|are in|received|picked up|dropped off|swapped|replaced|took care"
    r"|signed off|already|running|approved|rejected|confirmed|inspected)\b", re.IGNORECASE)
_PAST_CLAIM = re.compile(
    r"\b((?:was|were|has been|have been|had been|got) \w+(?:ed|en|ne|t)"
    r"|acquired|obtained|received|completed|finished|delivered|installed|poured|arrived"
    r"|swapped|replaced|took place|happened|was done|were done|got done|got it"
    r"|got (?:a|an|the|their|our|his|her)|picked up|brought|rented)\b",
    re.IGNORECASE)


def is_intent(quote: str) -> bool:
    """The words state a plan or an intention, and nothing in them says it
    has happened."""
    return bool(_INTENT.search(quote or "")) and not _DONE_WORDS.search(quote or "")


_CLAUSE = re.compile(r"(?<=[.;!?])\s+|\n+|\s+but\s+", re.IGNORECASE)


def planned_for(quote: str, claim_text: str) -> bool:
    """The part of the quote the claim is about states only a plan.
    "Drawings approved. Installation is set for Monday." -- a claim about the
    installation is judged on the installation clause, not on "approved"."""
    parts = [p for p in _CLAUSE.split(quote or "") if p and p.strip()]
    if len(parts) < 2:
        return is_intent(quote)
    want = set(terms(claim_text))
    scored = [(len(want & set(terms(p))), p) for p in parts]
    best = max(n for n, _ in scored)
    if best == 0:
        return is_intent(quote)
    return any(is_intent(p) for n, p in scored if n == best)


def claims_done(text: str) -> bool:
    return bool(_PAST_CLAIM.search(text or ""))


def _words(text: str) -> set:
    return set(terms(text))


_NEGATION = re.compile(r"\b(?:not|no|never|none|nobody|nothing|cannot|without)\b|\w+n['’]t\b",
                       re.IGNORECASE)


def _negated(text: str) -> bool:
    return bool(_NEGATION.search(text or ""))


def same_fact(a: Dict[str, Any], b: Dict[str, Any], timeline: bool = False) -> bool:
    """Two claims that say the same thing (one fact, several sources)."""
    if timeline and (a.get("date") or "") != (b.get("date") or ""):
        return False
    if _negated(a["text"]) != _negated(b["text"]):
        return False                 # "approved" and "not approved" are two facts
    wa, wb = _words(a["text"]), _words(b["text"])
    if not wa or not wb:
        return norm(a["text"]) == norm(b["text"])
    return len(wa & wb) / len(wa | wb) >= (0.75 if timeline else 0.6)


def checked_claims(raw: Any, sources: Sequence[Dict[str, Any]],
                   limit: int = 12, timeline: bool = False,
                   report: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The model's claims that survive the check, made faithful:
    [{text, sid, quote, date?, also: [{sid, quote}], relayed_by?, decider?,
      planned?}].

      - every quote must be in a retrieved source, verbatim (<= QUOTE_MAX),
        else the claim's source is dropped (no source left: the claim goes);
      - RELAYED: the decider the words name replaces the poster as the one
        who decided; the poster is kept as who relayed it;
      - PLANNED: a done-sounding claim on words that only state a plan is
        rewritten to "<what> planned for <when> (<who>, <date>) -- not
        confirmed as done", what was planned kept;
      - one claim per fact: the same fact from several sources is one claim
        with several sources.
    """
    out: List[Dict[str, Any]] = []
    people = {str(x.get("who") or "") for x in sources if x.get("who")}
    tally = report if report is not None else {}
    tally.update(dropped=0, merged=0, made_faithful=0)
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            tally["dropped"] += 1
            continue
        text = clean(c.get("text"))
        cites = c.get("sources") if isinstance(c.get("sources"), list) else [
            {"source": c.get("source"), "quote": c.get("quote")}]
        found = []
        for ci in cites:
            if not isinstance(ci, dict):
                continue
            quote = clean(ci.get("quote")).strip('"“”')
            if not quote:
                continue
            src = find_quote(quote, sources, prefer=str(ci.get("source") or ""))
            if src and all(not (f[0]["sid"] == src["sid"] and norm(f[1]) == norm(quote))
                           for f in found):
                found.append((src, quote))
        if not text or not found:
            tally["dropped"] += 1           # no quote of it in any record retrieved
            continue
        src, quote = found[0]
        claim: Dict[str, Any] = {"text": text, "sid": src["sid"], "quote": quote,
                                 # A timeline entry's date is its record's.
                                 "date": clean(c.get("date")) or (
                                     src.get("day_label") or "" if timeline else ""),
                                 "also": [{"sid": s["sid"], "quote": q} for s, q in found[1:]]}
        before = claim["text"]
        _make_faithful(claim, src, people)
        if claim["text"] != before:
            tally["made_faithful"] += 1
        twin = next((o for o in out if same_fact(o, claim, timeline)), None)
        if twin:
            have = {(twin["sid"], norm(twin["quote"]))} | {
                (a["sid"], norm(a["quote"])) for a in twin["also"]}
            for a in [{"sid": claim["sid"], "quote": claim["quote"]}] + claim["also"]:
                if (a["sid"], norm(a["quote"])) not in have:
                    twin["also"].append(a)
                    have.add((a["sid"], norm(a["quote"])))
            tally["merged"] += 1
            continue
        out.append(claim)
        if len(out) >= limit:
            break
    return out


_RELAY_NOTE = re.compile(r"\s*[(\[]\s*(?:relayed|passed on|forwarded)\s+(?:by|from|via)\b[^)\]]*[)\]]",
                         re.IGNORECASE)


def _make_faithful(claim: Dict[str, Any], src: Dict[str, Any],
                   people: Iterable[str] = ()) -> None:
    quote = claim["quote"]
    # Who relayed a decision is said once, by format_answer, and only when
    # the code found one: a "(relayed by …)" the model wrote itself is never
    # kept ("Patricia sent the drawings (relayed by Patricia Lee)").
    text = _RELAY_NOTE.sub("", claim["text"]).rstrip()
    poster = src.get("who") or ""
    decider = (relayed_decider(quote, poster, people)
               if src.get("source") == SOURCE_WHATSAPP else None)
    if decider and poster:
        cap = decider[0].upper() + decider[1:]
        for name in sorted({poster, poster.split(" ")[0]}, key=len, reverse=True):
            if len(name) >= 2 and re.search(r"\b" + re.escape(name) + r"\b", text):
                # Never the poster as the decider.
                text = re.sub(r"\b" + re.escape(name) + r"\b", cap, text, count=1)
                break
        # "Relayed by" only when the claim is about the decider's decision.
        # A claim about what the poster did themself has no relayer.
        if re.search(r"\b" + re.escape(decider.replace("the ", "", 1)) + r"\b", text,
                     re.IGNORECASE):
            claim["decider"], claim["relayed_by"] = decider, poster
    if planned_for(quote, text):
        day = src.get("day_label") or ""
        if claims_done(text):
            text = plan_line(text, plan_clause(quote, text), poster, day)
            claim["planned"] = True
        elif _SAYS_PLANNED.search(text):
            # Already told as a plan: say whose plan and as of when.
            if "not confirmed" not in text.lower():
                who_day = ", ".join(x for x in (poster, day) if x)
                text = text.rstrip(" .") + (f" ({who_day})" if who_day else "") + (
                    " — not confirmed as done")
            claim["planned"] = True
    claim["text"] = text


_SAYS_PLANNED = re.compile(r"\b(planned|scheduled|set for|expected|plans? to|will|going to)\b",
                           re.IGNORECASE)


_WHEN = re.compile(
    r"(?:\b(?:on|for|by)\s+)?\b((?:next\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)day"
    r"(?:,?\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?)?|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?"
    r"|tomorrow(?: morning| afternoon)?|tmrw|tonight|later today|this (?:morning|afternoon|week)"
    r"|next week|end of (?:the )?(?:day|week))\b(?:\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm))?",
    re.IGNORECASE)
_GOT = re.compile(
    r"^\s*[\w' .-]*?\b(?:got|acquired|obtained|received|picked up|brought|rented)\s+"
    r"(?:(?:a|an|the|their|our|his|her)\s+)?(?P<thing>.+?)\s*\.?$", re.IGNORECASE)
_PASSIVE = re.compile(r"\b(?:was|were|been|is|are|be)\s+(?:got|acquired|obtained|received"
                      r"|picked up|brought|rented)\b", re.IGNORECASE)
_SET_FOR = re.compile(
    r"^\s*(?P<what>[^,;]+?)\s+(?:is|are|was|were)\s+(?:set|scheduled|planned|booked|slated)"
    r"\s+for\b", re.IGNORECASE)


def plan_clause(quote: str, claim_text: str) -> str:
    """The part of the quote that states the plan the claim is about."""
    parts = [p.strip() for p in _CLAUSE.split(quote or "") if p and p.strip()]
    if len(parts) < 2:
        return (quote or "").strip()
    want = set(terms(claim_text))
    ranked = sorted(parts, key=lambda p: (not is_intent(p), -len(want & set(terms(p)))))
    return ranked[0]


def plan_line(claim_text: str, clause: str, who: str = "", day: str = "") -> str:
    """A done-sounding claim on words that only state a plan, told as the
    plan it is, substance kept:
    "Dumpster swap planned for Tuesday 10/6 (Roy Fishman, Oct 2) — not
    confirmed as done"."""
    m = _WHEN.search(clause or "")
    when_ = m.group(1) if m else ""
    sf = _SET_FOR.match(clause or "")
    if sf:
        what = sf.group("what").strip() + " planned"
    elif _GOT.match(claim_text or "") and not _PASSIVE.search(claim_text):
        # "Roy got a pump from the rental yard" -> "Pump planned from the
        # rental yard": the thing is the subject of a plan, not the person.
        thing = _GOT.match(claim_text).group("thing")
        parts = re.split(r"\s+(from|to|at|for|with|by|into|on)\s+", thing, maxsplit=1)
        what = f"{parts[0]} planned" + (f" {parts[1]} {parts[2]}" if len(parts) == 3 else "")
        mw = _WHEN.search(what)
        if mw:
            when_ = when_ or mw.group(1)
            what = what[:mw.start()] + what[mw.end():]
    else:
        what = _PAST_CLAIM.sub("planned", claim_text, count=1)
        mw = _WHEN.search(what)
        if mw:
            when_ = when_ or mw.group(1)
            what = (what[:mw.start()] + what[mw.end():])
    what = re.sub(r"\s+", " ", what).strip(" .,;")
    what = re.sub(r"^(?:the|a|an)\s+", "", what, flags=re.IGNORECASE)
    what = what[:1].upper() + what[1:] if what else "Planned"
    if "planned" not in what.lower():
        what += " planned"
    line = what + (f" for {when_}" if when_ and when_.lower() not in what.lower() else "")
    who_day = ", ".join(x for x in (who, day) if x)
    return line + (f" ({who_day})" if who_day else "") + " — not confirmed as done"


_PAST_OF = {"send": "sent", "get": "got", "come": "came", "go": "went", "begin": "began",
            "pour": "poured", "set": "set", "put": "put", "do": "did", "make": "made",
            "take": "took", "bring": "brought", "pay": "paid", "run": "ran", "hold": "held"}
_DID_VERBS = ("send", "pour", "install", "deliver", "swap", "arrive", "start", "finish",
              "happen", "get", "come", "approve", "inspect", "sign", "submit", "order",
              "replace", "remove", "fix", "repair", "complete", "pass", "fail", "pay",
              "drop", "pick", "test", "move", "change", "close", "open", "begin", "do")
_DONE_Q = re.compile(r"^(?:(?:when|what day|what time)\s+)?(was|were|did|has|have)\s+(.+)$",
                     re.IGNORECASE)


def _past(verb: str) -> str:
    v = verb.lower()
    if v in _PAST_OF:
        return _PAST_OF[v]
    if v.endswith("e"):
        return verb + "d"
    if re.search(r"[^aeiou]y$", v):
        return verb[:-1] + "ied"
    return verb + "ed"


def no_record_line(question: str) -> str:
    """For "when was X done?" when the records only hold a plan: the line
    the answer leads with. "" when the question is not asking whether
    something happened."""
    q = clean(question).strip().rstrip("?.! ")
    m = _DONE_Q.match(q)
    if not m:
        return ""
    aux, words = m.group(1).lower(), m.group(2).split()
    if aux in ("was", "were", "has", "have"):
        # The aux goes back before the participle: "was the dumpster
        # swapped" -> "the dumpster was swapped"; "has the slab been poured"
        # -> "the slab has been poured".
        pasts = set(_PAST_OF.values())
        for i, w in enumerate(words[1:], start=1):
            lw = w.lower()
            if lw == "been" or lw in pasts or re.search(r"(?:ed|en)$", lw):
                return f"No record that {' '.join(words[:i])} {aux} {' '.join(words[i:])}."
    if aux == "did":
        for i, w in enumerate(words[1:], start=1):
            if w.lower() in _DID_VERBS:
                rest = " ".join([*words[:i], _past(w), *words[i + 1:]])
                return f"No record that {rest}."
    return "No record that this happened."


def lead_line(question: str, claims: Sequence[Dict[str, Any]], timeline: bool = False) -> str:
    """"No record that X happened." -- only when the question asks whether
    or when something was done and every claim is a plan."""
    if timeline or not claims or not all(c.get("planned") for c in claims):
        return ""
    return no_record_line(question)


# ── WHAT THE PERSON READS ────────────────────────────────────────────────────

def when(at: Any) -> str:
    """"Oct 3, 7:42 AM" in New York (the caller passes a NY-local datetime)."""
    if not isinstance(at, datetime):
        return ""
    h = at.strftime("%I").lstrip("0") or "12"
    return f"{at.strftime('%b')} {at.day}, {h}:{at.strftime('%M %p')}"


def cite(src: Dict[str, Any]) -> str:
    """"Mike Rivera · Main St Electric · Oct 3, 7:42 AM" / "Daily report · Oct 3"."""
    if src.get("source") == SOURCE_DAILY:
        parts = ["Daily report", src.get("label") or "", src.get("day_label") or ""]
    else:
        parts = [src.get("who") or "Someone", src.get("group") or "", src.get("when") or ""]
    return " · ".join(p for p in parts if p)


def format_answer(claims: Sequence[Dict[str, Any]], by_sid: Dict[str, Dict[str, Any]],
                  timeline: bool = False, lead: str = "") -> str:
    """The reply: `lead` ("No record that …") first when given, then each
    claim, its source and its exact words. NO_SOURCE when nothing survived."""
    if not claims:
        return NO_SOURCE
    lines = [lead] if lead else []
    for c in claims:
        src = by_sid[c["sid"]]
        head = f"{c['date']} — {c['text']}" if timeline and c.get("date") else c["text"]
        if c.get("relayed_by") and not c.get("planned"):
            head += f" (relayed by {c['relayed_by']}" + (
                f", {src.get('day_label')})" if src.get("day_label") else ")")
        rows = [f"• {head}", f"   {cite(src)}: “{c['quote']}”"]
        for a in c.get("also") or []:
            rows.append(f"   {cite(by_sid[a['sid']])}: “{a['quote']}”")
        lines.append("\n".join(rows))
    return "\n".join(lines)


def source_block(sources: Sequence[Dict[str, Any]]) -> str:
    """The sources as the model sees them."""
    rows = []
    for s in sources:
        rows.append(f"[{s['sid']}] {cite(s)}\n{s.get('text') or ''}")
    return "\n\n".join(rows)


ANSWER_PROMPT = """You answer questions about ONE construction project from its records: WhatsApp group messages, filed daily reports and tracked items. The records are below, each with an id like [S3].

RULES
- Use ONLY the records. Never your own knowledge, never a guess.
- Every claim needs the id of the record it comes from and an EXACT quote from that record: copied character for character, at most 200 characters, the shortest part that proves the claim.
- If the records do not answer the question, return no claims.
- WHO SAID IT IS NOT WHO DECIDED IT. The name before the group is who POSTED the words. When the words say someone else wants, asked, approved or decided ("Owner wants X", "the architect approved Y", "per Mike"), the claim says THAT person decided: "The owner wanted X". Never make the poster the decider. Do not write "(relayed by …)" yourself; the reply adds who relayed it.
- NO CERTAINTY UPGRADES. A plan or intention stays a plan: "getting a pump" is not "got a pump"; "set for Tuesday" is not "happened Tuesday". A future date in an older message is "<what> planned for <date>". Keep what was planned in the claim. Only say something was done when a record says it was done.
- ONE CLAIM PER FACT. When several records support the same fact, make ONE claim and list every record in "sources".
- Keep each claim to one short sentence.

Return JSON: {"claims": [{"text": "...", "sources": [{"source": "S3", "quote": "..."}]}]}"""

TIMELINE_PROMPT = """You tell what happened with something on ONE construction project, from its records: WhatsApp group messages, filed daily reports and tracked items (commitments, new dates, done). The records are below, each with an id like [S3] and its date.

RULES
- Use ONLY the records. Never your own knowledge, never a guess.
- A dated timeline, oldest first, 5 to 12 entries when the records have that many (fewer is fine).
- Every entry needs the id of its record and an EXACT quote from that record: copied character for character, at most 200 characters.
- The date of an entry is the date of its record. A plan stays a plan: "set for Oct 12" in a message of Oct 1 is "Oct 1 — install planned for Oct 12", not an Oct 12 event.
- WHO SAID IT IS NOT WHO DECIDED IT: "Owner wants X" posted by Wendy is "The owner wanted X", never "Wendy wanted X". Do not write "(relayed by …)" yourself.
- One entry per event; when several records show the same event, list them all in "sources".
- If the records say nothing about it, return no entries.

Return JSON: {"claims": [{"date": "Oct 3", "text": "...", "sources": [{"source": "S3", "quote": "..."}]}]}"""
