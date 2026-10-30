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
track, no row; "include" - they are read as ordinary rows of the track;
"replaces" - the pages stand IN PLACE OF other sheets of the track (below). The
gate never reads the answer, only the rows the last pass wrote.

REPLACES (Roy, 10-30: "answers can be IN / NOT IN / REPLACES <sheet>. The
yes/no form can't express supersession."). The gas-change file's Roof Plan is
neither "in" nor "out": it is the roof plan, and A-105.01 is not. Its page 1
(A-100.00) is the first floor plan, and A-100.01 is not - and that page is in
no track today (A-100.01 wins by date), so the question, which covers page 2
only, cannot name it. An answer of replaces therefore carries an explicit list,
[{page_id (the replacing page), replaces: {file_id, page_number,
sheet_number}}], and it may name pages of the question's file the question did
not cover. Nothing is inferred: every page is checked against the project's
pages (validate_replacements), anything ambiguous is refused, and the same
checks run again at the pass (apply_decisions). The office records it (the
admin route); a WhatsApp reply is a YES or a NO.

Applied to a track's pages, BEFORE the pass reads them, so rows, areas, walls,
stacks, set health and the questions all follow: a replaced page leaves the
track, the replacing page takes its place, and the pairing rules are the
ones they were (by number). The replacing page keeps its own number when it is
in the plan series (it must name the same floor sequence as the page it
replaces) and has the replaced sheet's number when it is not - an unnumbered
Roof Plan is paired as A-105.01 because the office said so. Its title stays its
own, and it must be a plan titled for the same level. "Exclude" leaves the
pages out of the track the same way.

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
INCLUDE, EXCLUDE, REPLACES = "include", "exclude", "replaces"
ANSWERS = (INCLUDE, EXCLUDE, REPLACES)
#: what a WhatsApp reply can be: a replacement is the office's to record
YES_NO = (INCLUDE, EXCLUDE)

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
            f"{_track_name(q)}, or \"{code} NO\" if they are not. If {short} stand in "
            f"place of other sheets, the office records that replacement - it is not a YES "
            f"or a NO.")


def status_text(q: Dict[str, Any]) -> str:
    """A question's state AS STORED - the only thing the assistant may say
    about whether an answer was recorded (10-29: "Q1 logged as no" was said
    without reading the store, and two minutes later "not decided" while it
    was stored)."""
    code = q.get("code") or "That question"
    if q.get("status") == ANSWERED:
        who = q.get("answered_by_name") or "the PM"
        when = str(q.get("answered_at") or "")[:10]
        by = f"({who}, {q.get('answered_via') or 'WhatsApp'}, {when})"
        if q.get("answer") == REPLACES:
            return (f"{code} is recorded: {replaces_phrase(q)} in {_track_name(q)} {by}. "
                    f"Levelog uses it from the next drawing check.")
        said = "part of" if q.get("answer") == INCLUDE else "not part of"
        return (f"{code} is recorded: {q.get('short') or q.get('label')} are {said} "
                f"{_track_name(q)} {by}. Levelog uses it from the next drawing check.")
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


def sheet_name(page: Dict[str, Any]) -> str:
    """A page as the office names it: "A-100.00 (AR - 6.9.26 (Gas change).pdf,
    page 1)", or "the unnumbered Roof Plan (..., page 2)"."""
    num = str(page.get("sheet_number") or "").strip()
    title = str(page.get("sheet_title") or "").strip() or "plan"
    where = ", ".join(x for x in (str(page.get("file_name") or "").strip(),
                                  f"page {page.get('page_number')}") if x)
    return f"{num or 'the unnumbered ' + title} ({where})"


def replaces_phrase(q: Dict[str, Any]) -> str:
    """"A-100.00 (gas.pdf, page 1) replaces A-100.01; the unnumbered Roof Plan
    (gas.pdf, page 2) replaces A-105.01" - from the stored replacements."""
    parts = []
    for r in q.get("replacements") or []:
        old = r.get("replaces") or {}
        parts.append(f"{sheet_name(r)} replaces {old.get('sheet_number') or 'a sheet'}")
    return "; ".join(parts) or f"{q.get('short') or q.get('label')} replace other sheets"


def answered_phrase(q: Dict[str, Any], track_name: str) -> str:
    """What a recorded answer says, for the render: "part of the filed set",
    "not part of the filed set", or the replacements."""
    if q.get("answer") == REPLACES:
        return f"{replaces_phrase(q)} in {track_name}"
    return ("part of " if q.get("answer") == INCLUDE else "not part of ") + track_name


def answer_text(q: Dict[str, Any], answer: str) -> str:
    track = "the filed set" if q.get("track") in (None, "filed") else f"the {q.get('track')} set"
    said = "part of" if answer == INCLUDE else "not part of"
    return (f"Thanks - saved: {q.get('short')} are {said} {track}. "
            f"Levelog uses it from the next drawing check.")


# ── an answer applied to a track's pages (the pass, before it reads them) ──

def _num(page: Dict[str, Any]) -> str:
    return str(page.get("sheet_number") or "").strip().upper()


def _pid(page: Dict[str, Any]) -> str:
    return str(page.get("_id") if page.get("_id") is not None else page.get("page_id"))


def _series(page: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(discipline letter, sequence) of a page in the plan series, else None."""
    m = _PLAN_SERIES.match(_num(page))
    return (m.group(1), m.group(2)) if m else None


def _same_page(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (str(a.get("file_id")) == str(b.get("file_id"))
            and int(a.get("page_number") or 0) == int(b.get("page_number") or 0))


def _find(pages: Sequence[Dict[str, Any]], file_id: Any, page_number: Any,
          sheet_number: Any) -> List[Dict[str, Any]]:
    try:
        n = int(page_number)
    except (TypeError, ValueError):
        return []
    want = str(sheet_number or "").strip().upper()
    return [p for p in pages if str(p.get("file_id")) == str(file_id)
            and int(p.get("page_number") or 0) == n and _num(p) == want]


def validate_replacements(question: Dict[str, Any], items: Any,
                          track_pages: Sequence[Dict[str, Any]],
                          pool: Sequence[Dict[str, Any]]
                          ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(the replacements, resolved - or the reasons they are refused).

    `items` is what the office sends: [{page_id, replaces: {file_id,
    page_number, sheet_number}}]. `track_pages` are the question's track's
    CURRENT pages (the pages the pass would read); `pool` every page of the
    project's live files (the replacing page may be in no track - A-100.00 of
    the gas-change file loses to A-100.01 by date).

    Nothing is inferred and anything ambiguous is refused:
      - the replacing page is a page of the QUESTION'S FILE (it may be one the
        question did not cover), found by its page id;
      - the replaced page is a current page of the track, found by file, page
        number AND sheet number - all three must match one page - and is an
        architectural plan of the plan series;
      - a replacing page in the plan series names the same architectural
        sequence as the page it replaces (A-100.00 for A-100.01), and one that
        is not takes the replaced sheet's number;
      - both are plans, and where both titles name a floor it is the same one;
      - no page is replaced twice, replaces twice, or is both;
      - every page the question covers is named as a replacing page, so the
        answer decides the whole question;
      - afterwards no two architectural plans of the track share a sequence.
    The same checks run again at every pass (apply_decisions)."""
    from lib import plan_derive as derive
    errs: List[str] = []
    if not isinstance(items, (list, tuple)) or not items:
        return [], ["a replacement answer needs the list of pages and what each replaces"]
    qfile = str(question.get("file_id"))
    by_id = {_pid(p): p for p in pool}
    out: List[Dict[str, Any]] = []
    seen_new: set = set()
    seen_old: set = set()
    for i, it in enumerate(items, 1):
        at = f"replacement {i}"
        if not isinstance(it, dict) or not isinstance(it.get("replaces"), dict) \
                or not str(it.get("page_id") or "").strip():
            errs.append(f"{at}: needs page_id and replaces {{file_id, page_number, sheet_number}}")
            continue
        rep = it["replaces"]
        new = by_id.get(str(it["page_id"]).strip())
        if new is None:
            errs.append(f"{at}: page {it['page_id']} is not a page of this project's current files")
            continue
        if str(new.get("file_id")) != qfile:
            errs.append(f"{at}: page {it['page_id']} is in {new.get('file_name')}, not in the "
                        f"question's file {question.get('file_name')}")
            continue
        if not str(rep.get("sheet_number") or "").strip():
            errs.append(f"{at}: replaces.sheet_number is required")
            continue
        hits = _find(track_pages, rep.get("file_id"), rep.get("page_number"),
                     rep.get("sheet_number"))
        if len(hits) != 1:
            errs.append(f"{at}: {rep.get('sheet_number')} (file {rep.get('file_id')}, page "
                        f"{rep.get('page_number')}) is not one current page of "
                        f"{_track_name(question)}")
            continue
        old = hits[0]
        old_series = _series(old)
        if not old_series or old_series[0] != "A":
            errs.append(f"{at}: {_num(old)} is not an architectural plan of the plan series "
                        f"(A-1xx.yy): only a plan stands in for a plan")
            continue
        if _same_page(new, old):
            errs.append(f"{at}: a page cannot replace itself")
            continue
        new_series = _series(new)
        if new_series and new_series != old_series:
            errs.append(f"{at}: {_num(new)} and {_num(old)} are not the same floor sequence "
                        f"({new_series[0]}-{new_series[1]} against {old_series[0]}-{old_series[1]})")
            continue
        if new_series is None and _num(new) and not re.match(r"^A[.\-]", _num(new)):
            errs.append(f"{at}: {_num(new)} is not an architectural sheet")
            continue
        if not derive.PLAN_TITLE.search(str(new.get("sheet_title") or "")):
            errs.append(f"{at}: page {new.get('page_number')} ({new.get('sheet_title')!r}) is "
                        f"not titled as a plan")
            continue
        a = derive.title_ordinal(new.get("sheet_title"))
        b = derive.title_ordinal(old.get("sheet_title"))
        if a is not None and b is not None and a != b:
            errs.append(f"{at}: the titles name different floors ({new.get('sheet_title')!r} "
                        f"against {old.get('sheet_title')!r}): neither is picked")
            continue
        np_ = (str(new.get("file_id")), int(new.get("page_number") or 0))
        op_ = (str(old.get("file_id")), int(old.get("page_number") or 0))
        if np_ in seen_new or op_ in seen_old:
            errs.append(f"{at}: a page is named twice (replacing or replaced)")
            continue
        seen_new.add(np_)
        seen_old.add(op_)
        out.append({
            "page_id": _pid(new), "file_id": new.get("file_id"), "file_name": new.get("file_name"),
            "page_number": new.get("page_number"), "sheet_number": new.get("sheet_number"),
            "sheet_title": new.get("sheet_title"),
            "takes_sheet_number": new.get("sheet_number") if new_series else old.get("sheet_number"),
            "replaces": {"page_id": _pid(old), "file_id": old.get("file_id"),
                         "file_name": old.get("file_name"), "page_number": old.get("page_number"),
                         "sheet_number": old.get("sheet_number"),
                         "sheet_title": old.get("sheet_title")}})
    if errs:
        return [], errs
    if seen_new & seen_old:
        return [], ["a page is both replacing and replaced"]
    for qp in question.get("pages") or []:
        covered = any(str(r["file_id"]) == qfile and int(r["page_number"] or 0)
                      == int(qp.get("page_number") or 0) for r in out)
        if not covered:
            return [], [f"the question covers page {qp.get('page_number')} "
                        f"({qp.get('sheet_number') or qp.get('sheet_title')}), and no replacement "
                        f"names it: the answer must decide every page of the question"]
    after = _replaced(track_pages, out, {_pid(p): p for p in pool})
    seqs: Dict[str, List[str]] = {}
    for p in after:
        sr = _series(p)
        if sr and sr[0] == "A":
            seqs.setdefault(sr[1], []).append(f"{_num(p)} ({p.get('file_name')} p{p.get('page_number')})")
    clash = [f"A-{k}: " + " and ".join(v) for k, v in sorted(seqs.items()) if len(v) > 1]
    if clash:
        return [], ["after the replacement two architectural plans would share a sequence - "
                    + "; ".join(clash)]
    return out, []


def _replaced(pages: Sequence[Dict[str, Any]], replacements: Sequence[Dict[str, Any]],
              by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`pages` with each replaced page taken out and its replacing page in its
    place - numbered as it is printed when that is in the plan series, else as
    the page it replaces. A replacing page the track already held leaves its
    old place."""
    moving = [(str(r["file_id"]), int(r["page_number"] or 0)) for r in replacements]
    out = [p for p in pages
           if (str(p.get("file_id")), int(p.get("page_number") or 0)) not in moving
           or any(_same_page(p, r["replaces"]) for r in replacements)]
    for r in replacements:
        new = dict(by_id[r["page_id"]], sheet_number=r["takes_sheet_number"])
        i = next(k for k, p in enumerate(out) if _same_page(p, r["replaces"]))
        out[i] = new
    return out


def apply_decisions(current: Dict[str, List[Dict[str, Any]]], pool: Sequence[Dict[str, Any]],
                    decisions: Iterable[Dict[str, Any]]
                    ) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """(the tracks' pages with the stored answers applied, a note per answer).

    `current` is track -> its current pages (server._glyph_track_pages, before
    the answers); `pool` every page of the project's live files; `decisions`
    the ANSWERED questions (exclude, replaces; an include changes nothing
    here). Pure; the input is not changed. Each note is {"id", "code",
    "answer", "applied": bool, "detail": [...]} - an answer that cannot be
    applied is said and applies NOWHERE (a replacement is all or nothing),
    and its pages are read as the question's open reading."""
    out = {t: list(ps) for t, ps in current.items()}
    notes: List[Dict[str, Any]] = []
    ds = sorted((d for d in decisions if d.get("answer") in (EXCLUDE, REPLACES)),
                key=lambda d: (d.get("answer") != EXCLUDE, str(d.get("_id") or d.get("id"))))
    by_id = {_pid(p): p for p in pool}
    for d in ds:
        note = {"id": str(d.get("_id") or d.get("id")), "code": d.get("code"),
                "answer": d.get("answer"), "applied": False, "detail": []}
        notes.append(note)
        track = d.get("track") or "filed"
        pages = out.get(track)
        if pages is None:
            note["detail"].append(f"no {track} track")
            continue
        if d["answer"] == EXCLUDE:
            key = str(d.get("file_hash") or d.get("file_id") or d.get("file_name") or "")
            gone: List[Dict[str, Any]] = []
            for qp in d.get("pages") or []:
                gone += [p for p in pages if _file_key(p) == key
                         and int(p.get("page_number") or 0) == int(qp.get("page_number") or 0)
                         and _num(p) == str(qp.get("sheet_number") or "").strip().upper()]
            ids = {id(p) for p in gone}
            out[track] = [p for p in pages if id(p) not in ids]
            note["applied"] = bool(gone)
            note["detail"] = [f"{_num(p) or 'unnumbered'} {p.get('file_name')} p{p.get('page_number')}"
                              for p in gone] or ["no such page in the track"]
            continue
        got, errs = validate_replacements(d, d.get("replacements"), pages, pool)
        if errs:
            note["detail"] = errs
            continue
        out[track] = _replaced(pages, got, by_id)
        note["applied"] = True
        note["detail"] = [f"{sheet_name(r)} replaces {r['replaces']['sheet_number']}"
                          + (f" (paired as {r['takes_sheet_number']})"
                             if str(r["takes_sheet_number"]) != str(r["sheet_number"]) else "")
                          for r in got]
    return out, notes


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
