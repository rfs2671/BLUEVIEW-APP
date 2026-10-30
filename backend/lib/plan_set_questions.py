"""DRAWING-SET QUESTIONS: the system never decides which drawings belong to a
set (ruling 21, operator, 2026-10-27).

    "The system never decides which drawings belong to a set or which
    governs. When it's ambiguous: (1) if the project has a PM or SM on
    record, ask them through the app/WhatsApp: one question per ambiguity,
    naming the sheets and what each would change. Their answer is stored per
    project, audit-logged, and applied on the next pass. (2) Until answered,
    or if no PM/SM exists: never pick one. Answers state the difference
    instead ... Claims bind only where both readings agree."

WHAT IS AMBIGUOUS HERE (measured on 588 Boyland, bv-worktrees/
L6_ambiguity_measure.md). A plan-titled architectural page in a drawing track
whose number is not in the track's plan series (A-1xx.yy) - the second
architect's A.1.1 ... A.1.7 in "588 THOMAS BOYLAND ST SET_UPDATED .pdf", the
unnumbered "Roof Plan" of "AR - 6.9.26 (Gas change).pdf". Neither file has a
track label, so each is in the filed set only by default; both print door and
window tags the filed set's A-1xx plans also print (A.1.1-A.1.5 tag for tag).
Counted in, the filed set has 72 type F doors; counted out, 36. ONE QUESTION
PER FILE: the pages of one file are one decision ("are these plans part of
the set?"), and its id is stable across passes - the project, the track, the
file's content hash and the pages - so a question is asked once.

THE TWO READINGS. The pass reads the pages of an open question like any plan
(at sheet scope: no plan-series number, no floor) and marks every row it
writes with the question (ROW_KEY). The gate (plan_search) counts each
reading - without the question's rows, and with them - and binds a figure
only where the readings agree; the render states the difference. A page the
pass could not read leaves the "with" reading unknown: nothing that depends
on it binds.

THE ANSWER APPLIES ON THE NEXT PASS: "exclude" - the pages are left out of the
track, no row; "include" - they are read as ordinary rows of the track. The
gate never reads the answer, only the rows the last pass wrote.

Pure: no database, no network. The sends, the stored questions and the audit
are server.py's (`_store_set_questions`, `_ask_set_questions`,
`_record_set_answer`).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

COLLECTION = "plan_set_questions"
KIND_MEMBERSHIP = "set_membership"

OPEN, ANSWERED, WITHDRAWN = "open", "answered", "withdrawn"
INCLUDE, EXCLUDE = "include", "exclude"
ANSWERS = (INCLUDE, EXCLUDE)

#: payload keys an opening row of an open question carries
ROW_KEY = "set_question"
ROW_LABEL = "set_question_label"

#: the WhatsApp kind (send_whatsapp_dm's ledger and preferences)
WA_KIND = "plan_set_question"

#: an A-1xx.yy plan - in the plan series (plan_derive.PLAN_SHEET)
_PLAN_SERIES = re.compile(r"^([A-Z])-(1\d\d)\.(\d\d)$")


def is_membership_ambiguous(page: Dict[str, Any]) -> bool:
    """A plan the pairing refused because its number is not in the plan
    series - or it has none. (Two current A-1xx sheets of one number, or an
    A-1xx with no mechanical partner, are plans of the set: not this.)"""
    num = str(page.get("sheet_number") or "").strip().upper()
    return not _PLAN_SERIES.match(num)


def _file_key(page: Dict[str, Any]) -> str:
    return str(page.get("file_hash") or page.get("file_id") or page.get("file_name") or "")


def question_id(project_id: Any, track: str, page_group: Sequence[Dict[str, Any]]) -> str:
    """Stable across passes: the project, the track, the file's content and
    its pages. A re-upload of the same file is the same question; a changed
    file is a new one (and the old one is withdrawn)."""
    pages = sorted({int(p.get("page_number") or 0) for p in page_group})
    key = "|".join([str(project_id), KIND_MEMBERSHIP, str(track),
                    _file_key(page_group[0]), ",".join(map(str, pages))])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _common_prefix(nums: Sequence[str]) -> str:
    p = nums[0]
    for n in nums[1:]:
        while not n.startswith(p):
            p = p[:-1]
    return p


def labels(page_group: Sequence[Dict[str, Any]]) -> Tuple[str, str]:
    """(short, long): how the render and the question name the pages.
    ("the A.1.x plans", "the A.1.x plans (A.1.1 to A.1.7, 588 THOMAS ...pdf)")
    ("the unnumbered Roof Plan", "the unnumbered Roof Plan (AR - 6.9.26 (Gas
    change).pdf, page 2)")."""
    pages = sorted(page_group, key=lambda p: int(p.get("page_number") or 0))
    fname = str(pages[0].get("file_name") or "a drawing file").strip()
    nums = [str(p.get("sheet_number") or "").strip() for p in pages]
    if all(nums):
        if len(nums) == 1:
            short = f"plan {nums[0]}"
            where = fname
        else:
            pre = _common_prefix(nums)
            short = (f"the {pre}x plans" if pre and pre[-1] in ".-" else
                     "plans " + ", ".join(nums))
            where = f"{nums[0]} to {nums[-1]}, {fname}"
        return short, f"{short} ({where})"
    titles = sorted({str(p.get("sheet_title") or "").strip() or "plan" for p in pages})
    short = ("the unnumbered " + " and ".join(titles)) if len(pages) == 1 else \
        f"the {len(pages)} unnumbered plans"
    pn = ", ".join(str(p.get("page_number")) for p in pages)
    return short, f"{short} ({fname}, page{'s' if len(pages) > 1 else ''} {pn})"


def detect(project_id: Any, track: str,
           refused: Iterable[Tuple[Dict[str, Any], str]]) -> List[Dict[str, Any]]:
    """One question per file of the track's refused plan pages that are
    membership-ambiguous: [{"id", "track", "file_id", "file_name",
    "file_hash", "pages", "short", "label", "pages_detail"}], in file order."""
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for page, _why in refused:
        if is_membership_ambiguous(page):
            by_file.setdefault(_file_key(page), []).append(page)
    out = []
    for _k, group in by_file.items():
        group = sorted(group, key=lambda p: int(p.get("page_number") or 0))
        short, long_ = labels(group)
        out.append({"id": question_id(project_id, track, group), "kind": KIND_MEMBERSHIP,
                    "track": track, "file_id": group[0].get("file_id"),
                    "file_name": group[0].get("file_name"),
                    "file_hash": group[0].get("file_hash"), "short": short, "label": long_,
                    "pages": [{"page_id": p.get("page_id"), "page_number": p.get("page_number"),
                               "sheet_number": p.get("sheet_number"),
                               "sheet_title": p.get("sheet_title")} for p in group]})
    return out


# ── what each reading changes, from the rows the pass wrote ───────────────

def figures(rows: Sequence[Dict[str, Any]], qid: str, track: str
            ) -> List[Dict[str, Any]]:
    """[{"family", "tag", "without", "with"}] for every tag whose count on the
    track differs between the two readings of `qid` - the tags read, with
    every OTHER open question's rows left out. "with" is None when a page of
    the question could not be read."""
    mine = [r for r in rows if (r.get("payload") or {}).get("track") == track]
    unknown = any((r.get("payload") or {}).get(ROW_KEY) == qid and _is_refusal(r) for r in mine)
    base: Dict[Tuple[str, str], int] = {}
    add: Dict[Tuple[str, str], int] = {}
    for r in mine:
        p = r.get("payload") or {}
        if r.get("glyph_status") != "resolved" or not r.get("label") or _is_refusal(r):
            continue
        k = (str(p.get("family") or ""), str(r.get("label")))
        q = p.get(ROW_KEY)
        if q is None:
            base[k] = base.get(k, 0) + 1
        elif q == qid:
            add[k] = add.get(k, 0) + 1
    out = []
    for k in sorted(set(base) | set(add)):
        if add.get(k, 0) == 0 and not unknown:
            continue
        out.append({"family": k[0], "tag": k[1], "without": base.get(k, 0),
                    "with": None if unknown else base.get(k, 0) + add.get(k, 0)})
    return [f for f in out if f["with"] != f["without"]]


def _is_refusal(r: Dict[str, Any]) -> bool:
    unit = r.get("unit")
    return isinstance(unit, str) and unit.startswith("sheet:") and not r.get("label")


def type_name(tag: str) -> str:
    return f"type {tag}" if len(tag) == 1 else tag


def _noun(family: str, n: Optional[int]) -> str:
    word = "window" if "WINDOW" in family.upper() else "door"
    return word if n == 1 else word + "s"


def _them(q: Dict[str, Any]) -> str:
    return "them" if len(q.get("pages") or []) != 1 else "it"


def change_lines(q: Dict[str, Any], limit: int = 0) -> List[str]:
    """Plain-words lines, the largest counts first: "type F doors: 36
    without them, 72 with them"."""
    them = _them(q)
    out = []
    figs = sorted(q.get("figures") or [], key=lambda f: (-(f["without"] or 0), f["tag"]))
    for f in figs:
        w = "not known (the page could not be read)" if f["with"] is None else str(f["with"])
        out.append(f"{type_name(f['tag'])} {_noun(f['family'], 2)}: {f['without']} without {them}, "
                   f"{w} with {them}")
    return out[:limit] if limit else out


def message(q: Dict[str, Any], project_name: str) -> str:
    """The WhatsApp text: plain words, the sheets, what changes, how to
    answer. A site person reads it on a phone."""
    pages = q.get("pages") or []
    nums = [p.get("sheet_number") for p in pages if p.get("sheet_number")]
    what = (f"{len(pages)} floor plans numbered {nums[0]} to {nums[-1]}" if len(nums) > 1 else
            f"plan {nums[0]}" if nums else
            f"an unnumbered {pages[0].get('sheet_title') or 'plan'} (page {pages[0].get('page_number')})"
            if pages else "some plans")
    track = "the filed set" if q.get("track") in (None, "filed") else f"the {q.get('track')} set"
    are = "Are they" if _them(q) == "them" else "Is it"
    lines = [f"Levelog question about the drawings for {project_name}.",
             f"The file \"{q.get('file_name')}\" has {what}. {are} part of {track}?"]
    ch = change_lines(q, limit=4)
    if ch:
        lines.append("It changes the building's counts:")
        lines += [f"- {c}" for c in ch]
        more = len(q.get("figures") or []) - len(ch)
        if more > 0:
            lines.append(f"- and {more} more")
    lines.append("Until you answer, Levelog gives both numbers and states neither as the count.")
    they, are_ = ("they", "are") if _them(q) == "them" else ("it", "is")
    lines.append(f"Reply {q.get('code')} YES if {they} {are_} part of {track}, "
                 f"or {q.get('code')} NO if {they} {are_} not.")
    return "\n".join(lines)


_REPLY = re.compile(r"^\s*(Q\d{1,3})\s*[:.\-]?\s*(YES|Y|NO|N|IN|OUT)\s*[.!]?\s*$", re.I)


def parse_reply(body: Optional[str]) -> Optional[Tuple[str, str]]:
    """(code, INCLUDE | EXCLUDE) for a whole message "Q1 YES" / "q1 no",
    else None. The code is required: a bare "yes" is the assistant's
    (it confirms a pending change) and never an answer here."""
    m = _REPLY.match(str(body or ""))
    if not m:
        return None
    return m.group(1).upper(), (INCLUDE if m.group(2).upper() in ("YES", "Y", "IN") else EXCLUDE)


#: "Q2 it's the final roof plan": a question's code, then words that are not
#: a YES / NO answer - an answer that needs confirming, never a chat message.
_FREE = re.compile(r"^\s*(Q\d{1,3})\b\s*[:.\-]?\s*(\S.*?)\s*$", re.I)


def split_reply(body: Optional[str]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], str]:
    """A WhatsApp message read line by line (10-29: "Gas change govern since
    it was latest.\\nQ1 no" went to the assistant because parse_reply wanted
    the whole message): ([(code, INCLUDE | EXCLUDE)] for every line that is
    an answer, [(code, text)] for every line that starts with a code and is
    not one, the rest of the text)."""
    answers: List[Tuple[str, str]] = []
    free: List[Tuple[str, str]] = []
    rest: List[str] = []
    for line in str(body or "").splitlines():
        a = parse_reply(line)
        m = None if a else _FREE.match(line)
        if a:
            answers.append(a)
        elif m:
            free.append((m.group(1).upper(), m.group(2)))
        elif line.strip():
            rest.append(line.strip())
    return answers, free, "\n".join(rest)


def _track_name(q: Dict[str, Any]) -> str:
    return "the filed set" if q.get("track") in (None, "filed") else f"the {q.get('track')} set"


def confirm_text(q: Dict[str, Any]) -> str:
    """What a PM is told when their words about a question are not a YES or
    NO: nothing is recorded, and how to record it."""
    code, short = q.get("code"), q.get("short") or q.get("label") or "those plans"
    return (f"Nothing is recorded for {code} yet - I keep your words as a note for the "
            f"office. To record it, reply \"{code} YES\" if {short} are part of "
            f"{_track_name(q)}, or \"{code} NO\" if they are not.")


def status_text(q: Dict[str, Any]) -> str:
    """A question's state AS STORED - the only thing the assistant may say
    about whether an answer was recorded (10-29: "Q1 logged as no" was said
    without reading the store, and two minutes later "not decided" while it
    was stored)."""
    code = q.get("code") or "That question"
    if q.get("status") == ANSWERED:
        said = "part of" if q.get("answer") == INCLUDE else "not part of"
        who = q.get("answered_by_name") or "the PM"
        when = str(q.get("answered_at") or "")[:10]
        return (f"{code} is recorded: {q.get('short') or q.get('label')} are {said} "
                f"{_track_name(q)} ({who}, {q.get('answered_via') or 'WhatsApp'}, {when}). "
                f"Levelog uses it from the next drawing check.")
    if q.get("status") == OPEN:
        return (f"{code} is not recorded yet: reply \"{code} YES\" or \"{code} NO\" "
                f"to record it.")
    return f"{code} is no longer open ({q.get('status')})."


#: An outgoing sentence that says a question's answer was recorded.
_RECORDED_CLAIM = re.compile(
    r"\b(Q\d{1,3})\b[^.!?\n]{0,80}?\b(?:logged|recorded|saved|stored|registered|captured|"
    r"noted\s+as|marked\s+as|set\s+(?:to|as))\b"
    r"|\b(?:logged|recorded|saved|stored|registered|captured)\b[^.!?\n]{0,40}?\b(Q\d{1,3})\b",
    re.I)
#: A sentence ends at . ! ? followed by a space or the end ("A.1.1" is not two).
_SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?!\s|$))*(?:[.!?]+(?=\s|$)|\n|$)")


def recorded_claims(text: Optional[str]) -> List[Tuple[str, str]]:
    """[(sentence, code)] for every sentence of `text` that says a
    question's answer was recorded."""
    out = []
    for m in _SENTENCE.finditer(str(text or "")):
        s = m.group(0)
        c = _RECORDED_CLAIM.search(s) if s.strip() else None
        if c:
            out.append((s, (c.group(1) or c.group(2)).upper()))
    return out


def rewrite_recorded_claims(text: str, stored: Dict[str, Dict[str, Any]]) -> Tuple[str, int]:
    """Each sentence saying an answer was recorded becomes the store's own
    words for that question (`stored`: code -> its stored question, as read
    for this sender); a code the store has no question for becomes "can't
    confirm". Returns (text, n rewritten)."""
    n = 0
    for sentence, code in recorded_claims(text):
        q = stored.get(code)
        line = status_text(q) if q else (f"I can't confirm {code} was recorded: reply "
                                          f"\"{code} YES\" or \"{code} NO\" to record it.")
        tail = "\n" if sentence.endswith("\n") else ""
        text = text.replace(sentence, line + tail, 1)
        n += 1
    return text.strip(), n


def answer_text(q: Dict[str, Any], answer: str) -> str:
    track = "the filed set" if q.get("track") in (None, "filed") else f"the {q.get('track')} set"
    said = "part of" if answer == INCLUDE else "not part of"
    return (f"Thanks - saved: {q.get('short')} are {said} {track}. "
            f"Levelog uses it from the next drawing check.")


# ── who is asked ───────────────────────────────────────────────────────────

def pm_on_record(user: Dict[str, Any], project_id: Any, company_id: Any) -> bool:
    """A PM / Site Manager ("pm": one role, two names) of the project's
    company who can see it: assigned to it, or with full PM access."""
    if not user or user.get("is_deleted") or str(user.get("role") or "").lower() != "pm":
        return False
    if str(user.get("company_id") or "") != str(company_id or ""):
        return False
    if user.get("pm_access") == "full":
        return True
    return str(project_id) in {str(p) for p in user.get("assigned_projects") or []}


# ── storing one pass's questions ───────────────────────────────────────────

def reconcile(existing: Sequence[Dict[str, Any]], detected: Sequence[Dict[str, Any]],
              taken: Iterable[Any] = ()) -> Dict[str, List[Dict[str, Any]]]:
    """What one pass changes in the project's stored questions: {"insert",
    "refresh", "withdraw"}. A question detected again keeps its status,
    answer and who was asked (it is never re-opened or re-asked); only its
    pages and figures are refreshed. An OPEN question no longer detected is
    withdrawn; an answered one keeps its answer. A new question's code
    ("Q3") is new in the company (`taken`): a PM's "Q3 YES" names one
    question whichever of their jobs it is on."""
    have = {str(q.get("_id")): q for q in existing}
    seen = {d["id"] for d in detected}
    codes = [int(m.group(1)) for c in list(taken) + [q.get("code") for q in existing]
             for m in [re.match(r"^Q(\d+)$", str(c or ""))] if m]
    nxt = max(codes or [0]) + 1
    out: Dict[str, List[Dict[str, Any]]] = {"insert": [], "refresh": [], "withdraw": []}
    for d in detected:
        if d["id"] in have:
            out["refresh"].append(d)
        else:
            out["insert"].append(dict(d, code=f"Q{nxt}"))
            nxt += 1
    for qid, q in have.items():
        if qid not in seen and q.get("status") == OPEN:
            out["withdraw"].append(q)
    return out
