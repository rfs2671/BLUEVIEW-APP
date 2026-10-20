"""Levelog Assistant in a direct message — the pure parts.

Who may use it, which job a message is about, the "Which job?" menu, and
whether a question is about one job, all of them, or neither. No database and
no network here; server.py (`_dm_assistant_*`) does the reading.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Everyone who is not an opted-in Admin or PM gets this, and only this. The
# same words for an unknown number, a CP, a superintendent or an admin who
# has not turned the assistant on: nothing here tells a stranger who has an
# account or what role they hold.
NOT_FOR_YOU_TEXT = (
    "This assistant is for project admins. Ask your admin to add you."
)
NO_JOBS_TEXT = "Levelog Assistant here. You don't have any jobs in Levelog yet."
MENU_EXPIRED_TEXT = "Which job did you mean? Name the address and I'll answer."

JOB_MEMORY_SECONDS = 30 * 60      # the last job used in this DM
MENU_SECONDS = 30 * 60            # a "Which job?" menu: 30 min from FIRST asked
MENU_MAX = 9
# Up to this many jobs, an all-jobs answer gets message excerpts too; above
# it, counts only — but always every job.
CROSS_DETAIL_MAX_JOBS = 15

SCOPE_PROJECT = "project"
SCOPE_ALL = "all"
SCOPE_GENERAL = "general"


def _norm(text: Any) -> str:
    t = str(text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " " + re.sub(r"\s+", " ", t).strip() + " "


def street_label(project: Dict[str, Any]) -> str:
    """'588 Thomas S Boyland St, Brooklyn, NY' -> '588 Thomas S Boyland St'.
    The job's address, short; its name only when no address is on file."""
    for k in ("address", "location"):
        v = str(project.get(k) or "").strip()
        if v:
            return v.split(",")[0].strip()
    return str(project.get("name") or "the project").strip()


_SUFFIXES = {"st", "street", "ave", "avenue", "rd", "road", "blvd", "pl",
             "place", "ct", "court", "dr", "drive", "ln", "lane", "pkwy",
             "parkway", "ter", "terrace", "way", "s", "n", "e", "w"}


def job_aliases(project: Dict[str, Any], group_names: Iterable[str] = ()) -> List[str]:
    """What a person may call this job in a message, normalised.

    The street address ('588 thomas s boyland st'), its house number and first
    street word ('588 thomas'), the street name without the number when it is
    distinctive ('thomas s boyland', 'walworth'), the project name, and the
    names of its WhatsApp groups."""
    out = set()
    street = _norm(street_label(project)).strip()
    if street:
        out.add(street)
        words = street.split()
        if len(words) >= 2 and words[0].isdigit():
            out.add(f"{words[0]} {words[1]}")
            name = words[1:]
            trimmed = list(name)
            while len(trimmed) > 1 and trimmed[-1] in _SUFFIXES:
                trimmed.pop()          # "boyland st" -> "boyland"; a middle "s" stays
            out.add(" ".join([words[0]] + trimmed))
            for cand in (" ".join(name), " ".join(trimmed)):
                if cand and (len(cand.split()) >= 2 or len(cand) >= 6):
                    out.add(cand)
    for v in [project.get("name")] + list(group_names):
        n = _norm(v).strip()
        if len(n) >= 4:
            out.add(n)
    return sorted(out, key=len, reverse=True)


def match_jobs(text: str, jobs: List[Dict[str, Any]]) -> List[str]:
    """Ids of the jobs a message names (each job: {id, aliases}). Whole
    words only, so '8 walworth' does not match '58 walworth'."""
    t = _norm(text)
    scored = []
    for j in jobs:
        found = [a for a in j.get("aliases") or [] if f" {a} " in t]
        if found:
            # A name WITH its house number ("8 walworth") beats the bare
            # street ("walworth") that two jobs on one street share.
            strength = 2 if any(a.split()[0].isdigit() for a in found) else 1
            scored.append((strength, j["id"]))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [jid for s, jid in scored if s == best]


# ── A JOB BY ITS STREET NAME ALONE ───────────────────────────────────────────
#
# "at walworth", "the menahan job", "boyland", "walwroth st": the street's key
# word (the last word of its name: "thomas s boyland st" -> "boyland"), with
# no house number, typos allowed. ONE matcher for the questions assistant and
# every DM action (find_jobs). A key word that is also an everyday word
# ("water", "main", "park") counts only when it is plainly a place ("at
# water", "water st", "the water job") -- "is the water leak fixed" is not
# 77 Water St.
_COMMON_STREET_WORDS = {
    "water", "main", "park", "church", "broad", "front", "high", "bay", "union", "grand",
    "market", "state", "court", "spring", "river", "lake", "hill", "ocean", "beach", "center",
    "central", "bridge", "mill", "pearl", "wall", "gold", "pine", "oak", "elm", "maple",
    "cedar", "walnut", "cherry", "willow", "west", "east", "north", "south", "first", "second",
    "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "college",
    "school", "station", "garden", "green", "lincoln", "washington", "franklin", "madison",
    "jackson", "jefferson", "king", "queen", "prince", "york", "liberty", "plaza", "rock",
}
_PLACE_BEFORE = {"at", "on", "for", "in", "to", "from", "en", "de", "over"}
_PLACE_AFTER = {"st", "street", "ave", "avenue", "rd", "road", "blvd", "pl", "place", "job",
                "site", "project", "building", "jobsite", "ct", "court", "dr", "ln", "way"}


def street_key(label: Any) -> str:
    """The word a person calls a job's street by: '588 Thomas S Boyland St'
    -> 'boyland'; '8 Walworth St' -> 'walworth'; '' when the street has none
    (a numbered street: '852 E 176 St')."""
    words = _norm(label).split()
    if words and re.fullmatch(r"\d+[a-z]?(?:-\d+)?", words[0]):
        words = words[1:]
    while words and words[-1] in _SUFFIXES:
        words.pop()
    key = words[-1] if words else ""
    return key if len(key) >= 4 and not key.isdigit() else ""


def _close(a: str, b: str) -> bool:
    """`a` is `b` with a typo or two: one edit for a word of up to 7
    letters, two above (a transposition is two)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 2:
        return False
    limit = 1 if len(b) <= 7 else 2
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


#: Words around a bare job name that say nothing ("boyland please", "what
#: about walworth"): a message of only these and the street is the job.
_FILLER = {"what", "about", "and", "the", "please", "pls", "ok", "okay", "how", "hows", "is",
           "for", "at", "on", "in", "now", "then", "too", "also", "one", "job", "site"}


def _street_named(words: List[str], key: str) -> bool:
    """The street is named as a PLACE: after "at/on/for/in/...", before
    "st/street/job/site/...", or alone ("boyland", "what about walworth").
    A street word anywhere else may be a person ("did Dean check in" is not
    10 Dean St -- Codex review on #771); an everyday word ("water") never
    counts alone."""
    alone = len([w for w in words if w not in _FILLER]) == 1
    for i, w in enumerate(words):
        if not (w == key or (key not in _COMMON_STREET_WORDS and _close(w, key))):
            continue
        before = words[i - 1] if i else ""
        after = words[i + 1] if i + 1 < len(words) else ""
        if before in _PLACE_BEFORE or after in _PLACE_AFTER or before.isdigit():
            return True                 # a house number before it is a place too
        if alone and key not in _COMMON_STREET_WORDS:
            return True
    return False


def find_jobs(text: Any, jobs: List[Dict[str, Any]]) -> List[str]:
    """Ids of the jobs a message names (each job: {id, label, aliases}).

    Its exact names first (house number + street, the project's name, its
    groups -- match_jobs); else its street's key word alone, fuzzy ("at
    walworth", "the menahan job", "boyland", "walwroth"). Several ids when
    several jobs share the street: the caller asks "Which one?"."""
    order = {j["id"]: menu_order(j) for j in jobs}
    exact = match_jobs(str(text or ""), jobs)
    if exact:
        return sorted(exact, key=lambda i: order.get(i, ("", 0)))
    words = _norm(text).split()
    if not words:
        return []
    # A house number of 2+ digits alone ("588"): one digit is too common
    # ("since 8:07" is not 8 Walworth).
    by_number = [j["id"] for j in jobs if len(house_number(j.get("label"))) >= 2
                 and house_number(j.get("label")) in words]
    if by_number:
        return sorted(by_number, key=lambda i: order.get(i, ("", 0)))
    out = []
    for j in jobs:
        key = street_key(j.get("label") or "")
        if key and _street_named(words, key):
            out.append(j["id"])
    if len(out) > 1:
        # "8 walwroth": a house number -- one digit too -- decides between
        # jobs the street already matched (Codex review on #771).
        # Only right before the street ("8 workers ... at walworth" is not 8).
        labels = {j["id"]: j.get("label") or "" for j in jobs}
        before_street = {words[k - 1] for k in range(1, len(words))
                         for i in out if words[k] == street_key(labels.get(i))
                         or _close(words[k], street_key(labels.get(i)))}
        pick = [i for i in out if house_number(labels.get(i))
                and house_number(labels.get(i)) in before_street]
        if len(pick) == 1:
            return pick
    return sorted(out, key=lambda i: order.get(i, ("", 0)))


def menu_order(job: Dict[str, Any]) -> tuple:
    """By street, then house number: 8 Walworth St before 120 Walworth St."""
    label = str(job.get("label") or "")
    num = house_number(label)
    return (re.sub(r"^\d+\s*", "", label).lower(), int(num) if num else 0)


def menu_text(jobs: List[Dict[str, Any]], header: str = "Which job?") -> str:
    """'Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St' -- or, when a
    street matched several, 'Which one? 1) 8 Walworth St 2) 120 Walworth St'."""
    parts = [f"{i}) {j['label']}" for i, j in enumerate(jobs[:MENU_MAX], 1)]
    return header + " " + " ".join(parts)


def parse_menu_choice(body: Any, count: int) -> Optional[int]:
    """0-based index for a reply that is only a menu number, else None."""
    s = str(body or "").strip().rstrip(".)")
    if not s.isdigit():
        return None
    n = int(s)
    return n - 1 if 1 <= n <= min(count, MENU_MAX) else None


#: A message that asks nothing and names no job (not "Which job?").
NOT_A_QUESTION_TEXT = "Not sure what you need. Ask me about a job, e.g. \"what's open at 588?\""
MENU_AGAIN_TEXT = "Reply with the number or the address — or \"never mind\"."
NUDGE_TEXT = "I'm here. Ask about a job and I'll check it."

# Answers that are not what was asked for: the model failed or its wording
# failed the check, so a fixed text went out instead.
RECORDS_PREFIX = "From the records:\n"
NO_RECORDS_TEXT = "I don't have that in the records."
ALL_JOBS_FAILED_TEXT = "Levelog Assistant couldn't put that together right now. Try again in a minute."
GENERAL_FAILED_TEXT = "Levelog Assistant couldn't answer that right now. Try again in a minute."

# path -> reason for an answer that is not a fallback.
_OK_REASON = {"headcount": "phrased", "job_agent": "agent", "general": "model",
              "all_jobs": "model", "menu": "menu_again", "clarify": "clarify",
              "other_job": "not_on_job"}


def answer_outcome(path: str, answer, wording=None):
    """(fallback, reason) for one DM answer, for the [dm-answer] log line.

    A fallback is an answer that is not the one meant: no answer at all,
    the fixed headcount text because the model's wording failed the check
    or the model gave none, the records as they are because the agent's
    answer had a number not in the data, "I don't have that", a "try again"
    text, or a menu reply that had expired."""
    a = str(answer or "")
    if not a.strip():
        return True, "no_answer"
    if path == "headcount":
        if wording == "fixed_after_check_failed":
            return True, "check_failed"
        if wording == "fixed":
            return True, "no_model_wording"
        if wording == "fixed_by_design":
            # The subs answer: built, never reworded (a count of companies
            # the check can't verify).
            return False, "fixed_by_design"
        return False, "phrased"
    if path == "job_agent":
        if a.startswith(RECORDS_PREFIX):
            return True, "numbers_not_in_data"
        if a == NO_RECORDS_TEXT:
            return True, "no_records"
    if a in (ALL_JOBS_FAILED_TEXT, GENERAL_FAILED_TEXT):
        return True, "model_failed"
    if path == "menu_expired":
        return True, "menu_expired"
    return False, _OK_REASON.get(path, path or "answer")


def fallback_alarm(answers: int, fallbacks: int, threshold: float = 0.10) -> bool:
    """More than 10% of the day's answers were fallbacks."""
    return answers > 0 and fallbacks / answers > threshold


def house_number(label: str) -> str:
    first = str(label or "").strip().split(" ")[0]
    return first if first.isdigit() else ""


def pick_from_menu(text: Any, options: List[Dict[str, Any]]) -> Optional[str]:
    """The id of the job a reply to an open "Which job?" menu picks, else
    None. Accepts the menu number ("2"), the house number ("588", also inside
    a sentence: "I said 588"), or a partial address / group name
    ("walworth"). Only the menu's own jobs; two matches is no pick."""
    i = parse_menu_choice(text, len(options))
    if i is not None:
        return str(options[i]["id"])
    t = _norm(text)
    by_number = [o for o in options if house_number(o.get("label"))
                 and f" {house_number(o.get('label'))} " in t]
    if len(by_number) == 1:
        return str(by_number[0]["id"])
    hit = match_jobs(str(text or ""), options)
    return str(hit[0]) if len(hit) == 1 else None


def is_menu_message(body: Any) -> bool:
    """"Which job? 1) ..." and "Which job — 588 Thomas S Boyland St? Or another: 1) ..."."""
    return bool(re.match(r"Which job\b", str(body or "").strip()))


# ── WHICH JOB, BEFORE EVER ASKING ───────────────────────────────────────────
#
# Thu 9:03 AM, right after the 588 walk was sent: "Was it sent to the GC
# team group chat?" got "Which job?"; a reply to the 588 list ("The list")
# got "Which job?" again. The job is read from, in order:
#   (a) the message replied to;
#   (b) the walk (or flow) going on or just finished -- 2 hours;
#   (c) the job named in this DM in the last 30 minutes;
#   (d) the only job the question could be about (a punch question: the job
#       with the latest punch activity).
# Asked only when still unknown -- and then with the likely one first.

CONTEXT_WALK_SECONDS = 2 * 3600
CONTEXT_NAMED_SECONDS = 30 * 60


def job_in_text(text: Any, jobs: List[Dict[str, Any]]) -> Optional[str]:
    """The ONE job a text names (an address, a house number of 2+ digits, a
    job code like "P-588-6"), else None."""
    t = str(text or "")
    if is_menu_message(t):
        return None                          # a "Which job?" menu names them all
    hit = find_jobs(t, jobs)
    if len(hit) > 1:
        return None
    # A full address names its job whatever its house number ("8 Walworth
    # St" too): two jobs named is no job.
    norm = _norm(t)
    full = {str(j["id"]) for j in jobs if _norm(j.get("label")).strip()
            and f" {_norm(j.get('label')).strip()} " in norm}
    one = {str(h) for h in hit} | full
    if len(one) > 1:
        return None
    if one:
        return one.pop()
    return job_named(t, jobs, in_sentence=True)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def named_recently(rows: Iterable[Dict[str, Any]], jobs: List[Dict[str, Any]], now: datetime,
                   seconds: int = CONTEXT_NAMED_SECONDS) -> Optional[str]:
    """The job named last in this chat (either side) within `seconds`: the
    newest message that names exactly one job."""
    since = now - timedelta(seconds=seconds)
    for r in reversed(list(rows)):
        at = _aware(r.get("created_at"))
        if at is None or at < since:
            continue
        jid = job_in_text(r.get("body"), jobs)
        if jid:
            return jid
    return None


_PUNCH_Q = re.compile(r"\b(?:punch|walk\s*-?\s*throughs?|walks?|lists?|items?|p-?\d+(?:-\d+)?|"
                      r"sent|send|post(?:ed)?)\b", re.IGNORECASE)


def about_punch(text: Any) -> bool:
    """A question about a punch list / walk ("was it sent to the group?",
    "the list", "what's open on P-588-6")."""
    return bool(_PUNCH_Q.search(str(text or "")))


def likely_first(jobs: List[Dict[str, Any]], likely_id: Optional[str]) -> Tuple[List[Dict[str, Any]], str]:
    """The menu with the likely job first, and its header: "Which job —
    588 Thomas S Boyland St? Or another:"; plain "Which job?" when none."""
    likely = next((j for j in jobs if str(j["id"]) == str(likely_id)), None) if likely_id else None
    if not likely:
        return list(jobs), "Which job?"
    rest = [j for j in jobs if j is not likely]
    return [likely] + rest, f"Which job — {likely['label']}? Or another:"


_EMPTY_RE = re.compile(r"^[\s.?!…,;:-]*$")
_NUDGE = {"hello", "hi", "hey", "ping", "bump", "anyone", "and", "so", "well", "hello?"}


def is_nudge(text: Any) -> bool:
    """'.', '?', '??', 'hello?', 'bump': no question of its own -- with a
    reply-to, the quoted message is the question."""
    t = str(text or "").strip().lower()
    if _EMPTY_RE.match(t):
        return True
    words = re.findall(r"[a-z]+", t)
    return 0 < len(words) <= 2 and all(w in _NUDGE for w in words)


# ── A BARE "DONE" / "CANCEL <THING>" THAT NO FLOW TOOK (dm_eval, Oct 20) ──
#
# "Cancel checklist" and "Done" both reached the job agent, which answered
# both with "Checklist creation or cancellation is done in the app." -- a
# claim about a feature, made twice, to two different messages. Nothing was
# open: every flow that owns a "done" or a "cancel" (a walk, a pending
# action, a reminder, an open question) runs before this and took nothing.
# So the answer is about THAT, in fixed words: what is done, or that there
# is nothing of that name to cancel. Never the model.
_DONE_RE = re.compile(
    r"^(?:ok(?:ay)?\W*)?(?:i'?m |we'?re |all |it'?s |im )?(?:done|finished|all done|done here|"
    r"done with (?:it|that|this|everything)|that'?s it|thats all|that'?s all|listo|terminé|"
    r"termine|fartik)\W*$")
# Things another flow cancels for real (a chase setting, the brief, a
# report schedule, a reminder, alerts): never claimed here.
_CANCEL_OWNED = re.compile(
    r"\b(chas\w*|brief\w*|report\w*|remind\w*|alert\w*|notification\w*|schedul\w*|"
    r"setting\w*|sub|subs|job|jobs|person|contact)\b")
_CANCEL_RE = re.compile(
    r"^(?:please |pls |can you |could you )?cancel "
    r"(?:the |my |this |that |our )?([a-z][a-z'&/ -]{1,40}?)\W*$")


def closer(text: Any) -> Optional[Tuple[str, str]]:
    """("done", "") for a bare "Done" / "all done" / "finished";
    ("cancel", "checklist") for "Cancel checklist" / "cancel the walk".
    None for anything else -- a question, or "cancel it" / "never mind",
    which are dm_actions.is_drop's."""
    t = " ".join(str(text or "").strip().lower().split())
    if not t or "?" in t:
        return None
    if _DONE_RE.match(t):
        return ("done", "")
    m = _CANCEL_RE.match(t)
    thing = m.group(1).strip() if m else ""
    if m and thing not in ("it", "that", "this", "them") and not _CANCEL_OWNED.search(thing):
        return ("cancel", thing)
    return None


def done_reply(walk_job: str = "", last_bot: str = "") -> str:
    """"Done with what?" -- with the open walk named, else Levelog's last
    message quoted, so they can say which."""
    if walk_job:
        return f"Done with what? Your walk at {walk_job} is still open."
    last = " ".join(str(last_bot or "").split())
    # Its own last reply is no context ("There's no checklist open here…").
    if last and not (last.startswith("Done with what?") or last.endswith("open here to cancel.")):
        last = last if len(last) <= 60 else last[:57].rstrip() + "…"
        return f"Done with what? My last message was: “{last}”"
    return "Done with what?"


def cancel_reply(thing: str, walk_job: str = "") -> str:
    """Nothing of that name is open here."""
    if walk_job and re.search(r"\b(walk|walkthrough|punch|list)\b", thing):
        return f"Your walk at {walk_job} is still open — nothing else to cancel."
    return f"There's no {thing} open here to cancel."


_MEDIA = {"image": "photo", "video": "video", "document": "document", "sticker": "sticker",
          "ptt": "voice note", "audio": "voice note", "voice": "voice note",
          "location": "location", "vcard": "contact card"}
#: What a reply-to says of a photo sent with no caption.
NO_CAPTION = "(no caption)"


def media_word(quoted_type: Any) -> str:
    """"photo" for WaAPI's "image" ... "" for text."""
    return _MEDIA.get(str(quoted_type or "").strip().lower(), "")


def quoted_words(node: Dict[str, Any]) -> str:
    """The words of a quoted message: its text, or a photo's CAPTION. A
    media message's body is its base64 thumbnail, never words (588, Oct 11:
    a reply to a photo reached the assistant as "I can't access…")."""
    if not isinstance(node, dict):
        return ""
    cap = str(node.get("caption") or "").strip()
    body = str(node.get("body") or node.get("conversation") or "").strip()
    if media_word(node.get("type")) or cap:
        if cap:
            return cap
        return "" if (len(body) > 200 and " " not in body) or media_word(node.get("type")) == "voice note" \
            else body
    return "" if len(body) > 200 and " " not in body else body


def with_quoted(text: str, quoted_body: str, quoted_from_bot: bool,
                quoted_type: str = "") -> str:
    """The question to answer for a reply-to in a DM (as in groups): the
    quoted message is the context -- its words and what it is (a photo with
    its caption). A nudge under your own question is that question again."""
    q = str(quoted_body or "").strip()
    t = str(text or "").strip()
    kind = media_word(quoted_type)
    if not q and not kind:
        return t
    if not quoted_from_bot and is_nudge(t) and not kind:
        return q
    who = "your (Levelog Assistant's) earlier" if quoted_from_bot else "their earlier"
    if kind:
        said = "with no caption" if q in ("", NO_CAPTION) else f"captioned \"{q[:400]}\""
        return f"{t}\n\n(This is a reply to {who} {kind}, {said}.)"
    return f"{t}\n\n(This is a reply to {who} message: \"{q[:400]}\")"


# "I can't see the message you replied to", "I can't access the content of
# the message you're replying to", "unable to view images".
_DENIES_QUOTED = re.compile(
    r"\b(?:can'?t|cannot|can ?not|unable to|not able to|don'?t have(?: any)? access|"
    r"do not have(?: any)? access|no access|not have access)\b[^.?!\n]{0,60}"
    r"\b(?:replied|replying|reply|quoted|previous message|earlier message|"
    r"photos?|images?|pictures?|attachments?)", re.I)


def denies_quoted_access(reply: str) -> bool:
    """The reply claims it cannot see the replied-to message (it is given)."""
    return bool(_DENIES_QUOTED.search(str(reply or "")))


def quoted_fallback(question: str) -> str:
    """Instead of a denial: what was replied to, and the question back."""
    ctx = quoted_context(question)
    m = re.match(r"\(This is a reply to (?:their|your \(Levelog Assistant's\)) earlier (.+?)[.)]*\s*$", ctx)
    what = (m.group(1) if m else "message").replace("message: ", "message ")
    return f"You replied to your {what}. What do you need about it?"


def quoted_context(question: str) -> str:
    """The "(This is a reply to …)" line of a question, or ""."""
    m = re.search(r"\(This is a reply to [^\n]+\)\s*$", str(question or ""))
    return m.group(0) if m else ""


HISTORY_HOURS = 4
HISTORY_MAX = 20


def history_messages(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """This chat's recent messages, oldest first, as chat turns for the
    model: theirs as 'user', Levelog's (answers, menus, the brief) as
    'assistant'."""
    out = []
    for r in rows:
        b = str(r.get("body") or "").strip()
        if not b:
            continue
        out.append({"role": "assistant" if str(r.get("sender") or "") == "bot" else "user",
                    "content": b[:1500]})
    return out[-HISTORY_MAX:]


def last_question(rows: Iterable[Dict[str, Any]], jobs: List[Dict[str, Any]]) -> str:
    """Their latest message in the history that asks something (not a
    bare job name, not a nudge)."""
    for r in reversed(list(rows)):
        if str(r.get("sender") or "") == "bot":
            continue
        b = str(r.get("body") or "").strip()
        if b and not is_nudge(b) and not is_job_only(b, jobs):
            return b
    return ""


def job_named(text: Any, jobs: List[Dict[str, Any]], *, in_sentence: bool = False
              ) -> Optional[str]:
    """The one job a message names by house number ("588", "I said 588")
    or address -- not by menu number (no menu is open). In a sentence only
    a house number of 2+ digits counts ("since 8:07" is not 8 Walworth)."""
    t = _norm(text)
    by_number = [o for o in jobs if house_number(o.get("label"))
                 and (not in_sentence or len(house_number(o.get("label"))) >= 2)
                 and f" {house_number(o.get('label'))} " in t]
    if len(by_number) == 1:
        return str(by_number[0]["id"])
    hit = find_jobs(text, jobs)
    return str(hit[0]) if len(hit) == 1 else None


def is_job_only(text: Any, jobs: List[Dict[str, Any]]) -> bool:
    """'588', '8 walworth', 'the 588 one': names a job and asks nothing."""
    t = str(text or "").strip()
    if not t or "?" in t or len(t.split()) > 4:
        return False
    return job_named(t, jobs) is not None


# ── Which kind of question ─────────────────────────────────────────────────

_ALL_RE = re.compile(
    r"\b(?:my|all(?: of)?(?: my)?|every|each|across(?: all)?(?: my)?|any of my)\s+"
    r"(?:jobs?|projects?|sites?|buildings?)\b"
    r"|\bacross\b|\bany new\b|\bwhich (?:jobs?|projects?|sites?)\b"
    r"|\b(?:this|next) (?:week|month)\b",
    re.IGNORECASE)
_PROJECT_RE = re.compile(
    r"\b(on site|onsite|who'?s (?:there|here|working)|crew|workers?|roster|"
    r"check[- ]?ins?|open items?|punch|daily log|violations?|permits?|"
    r"inspections?|dob|complaints?|swo|stop work|deliver(?:y|ies)|materials?|"
    r"drawings?|sheets?|plans?|happened|activity|going on|status|today|"
    r"yesterday|expir\w*|renew\w*)\b",
    re.IGNORECASE)
_GENERAL_RE = re.compile(
    r"^\s*(?:how do i|how to|how does|what is a|what's a|what is an|what does|"
    r"explain|can you explain|what are the rules|is it required|do i need|"
    r"help\b|what can you do)",
    re.IGNORECASE)


def question_scope(text: str) -> Optional[str]:
    """SCOPE_ALL / SCOPE_PROJECT / SCOPE_GENERAL by rule, or None when the
    rules cannot tell (the server then asks the model)."""
    t = str(text or "")
    if _GENERAL_RE.search(t) and not _ALL_RE.search(t):
        return SCOPE_GENERAL
    if _ALL_RE.search(t):
        return SCOPE_ALL
    if _PROJECT_RE.search(t):
        return SCOPE_PROJECT
    return None


DM_AGENT_CLAUSE = (
    "\n\nYOU ARE IN A PRIVATE WHATSAPP CHAT with one project admin or PM, not "
    "the group. Talk like a sharp assistant super texting a PM: lead with the "
    "answer, short, direct, no filler, no greeting, never 'Yes, that's current "
    "information'. The earlier messages of this chat (both sides, including the "
    "morning brief you sent) are above: use them to understand what 'that', "
    "'those', 'the 2 added' or 'since the morning' mean, and never pivot to an "
    "unrelated topic. Numbers and names come ONLY from this turn's tool results, "
    "never from the earlier messages or memory. If a reference is truly "
    "ambiguous, ask ONE short question naming the options. Name a job "
    "by its short name (\"588\", \"8 Walworth\"), never the full address in capitals. "
    "STYLE, every answer: the FIRST LINE is the direct answer, short and plain, no "
    "preamble; at most 2 more short lines, only if they add something needed; names "
    "and lists only when asked (\"who\", \"list\", \"names\") -- otherwise end with "
    "\"Want the names?\"; under 300 characters unless a list or the detail was asked "
    "for. A question about one sub (\"how many Arkon workers\") is answered for that "
    "sub only. Answer only about the job named in the facts above. Use "
    "the tools for data; never invent a DOB number, date, fine, permit or "
    "violation. You cannot file or renew anything here: if asked, say that is "
    "done in the Levelog app. Changes -- add a job, a sub, a person, a punch "
    "contact, a job's settings -- are made by asking in this chat in plain "
    "words (\"add Arkon to 588 as the plumber\"), never \"use the app\". You "
    "cannot send drawing images here: say what the drawings say "
    "(search_plans) and that sheets are in the app; who is on this job is "
    "who_on_site. THE SUBS LIST (every sub on their jobs, its trade, the jobs "
    "it is on, its punch contact) is find_sub and list_subs: never say you "
    "cannot check the subs or subcontractors, or that they should use the "
    "app for them. VOICE NOTES in the job's groups are transcribed and "
    "stored: read them with recent_voice_notes (the latest ones, or one "
    "person's) or search_project_history (records marked 🎤). Never say you "
    "cannot access, hear or listen to voice notes, recordings or audio. "
    "A REPLY-TO: when the message replies to an earlier one, what it replied "
    "to is given in the question (\"This is a reply to their earlier photo, "
    "captioned …\"): its words and what it is. Use it; never say you cannot "
    "see, open or access the message, photo or image being replied to. "
    "NEVER SAY THE DATA DOESN'T SPECIFY when a tool reads it: days on site, "
    "first day, man-days, crew size over time are sub_attendance; workers per "
    "day, who was on site on a date, the busiest day are site_headcount (both "
    "from the check-ins; pass the period as the user said it); "
    "the punch list is punch_status; who owes what and what is late is "
    "follow_ups; inspections, hearings and dated events ahead are "
    "upcoming_events; a day's log is daily_log; DOB is dob_status. THE "
    "MORNING BRIEF: never say it was sent, delivered or skipped unless "
    "brief_status said so; it is about this person, never a job."
)


# "the last voice note", "what did Meilich say in his voicenote", "nota de voz".
_VOICE_Q = re.compile(
    r"\b(?:voice\s*-?\s*notes?|voicenotes?|voice\s+(?:messages?|memos?|msgs?)|"
    r"audio\s+(?:notes?|messages?|msgs?|clips?)|audios|notas?\s+de\s+voz|"
    r"grabaci[oó]n(?:es)?)\b", re.I)

# "I can't access voice notes", "I don't have access to audio", "unable to
# listen to recordings".
_DENIES_VOICE = re.compile(
    r"\b(?:can'?t|cannot|can ?not|unable to|not able to|don'?t have(?: any)? access|"
    r"do not have(?: any)? access|no access|not have access)\b[^.?!\n]{0,40}"
    r"\b(?:voice\s*-?\s*notes?|voicenotes?|voice\s+(?:messages?|recordings?)|"
    r"audio\s+(?:notes?|messages?|recordings?)|recordings|listen)", re.I)


def asks_about_voice_notes(text: str) -> bool:
    """A DM question about voice notes: answered from recent_voice_notes."""
    return bool(_VOICE_Q.search(str(text or "")))


def denies_voice_access(reply: str) -> bool:
    """The reply claims it cannot read voice notes (it can)."""
    return bool(_DENIES_VOICE.search(str(reply or "")))

CROSS_SYSTEM_PROMPT = (
    "You are Levelog Assistant, answering one project admin or PM in a private "
    "WhatsApp chat about ALL of their jobs. Use ONLY the facts below — one "
    "block per job, named by address. Never invent a job, number, date, fine, "
    "permit or violation; if the facts do not say, say you don't have it. "
    "Short: one line per job that matters, skip jobs with nothing to report, "
    "and say so in one line if nothing matches."
)

GENERAL_SYSTEM_PROMPT = (
    "You are Levelog Assistant, helping a NYC construction project admin or PM "
    "in a private WhatsApp chat. Answer general questions about using Levelog "
    "and general NYC DOB / site-safety practice in a few short sentences. You "
    "have NO project data here: never state a job's permits, violations, "
    "fines, dates or inspections, and never invent DOB figures. For "
    "rules and penalties, say it is general information, not legal advice, "
    "and point to the DOB or their expediter for their case. If the question "
    "is about one of their jobs, ask them to name the job's address."
)

SCOPE_CLASSIFIER_PROMPT = (
    "Classify a construction admin's WhatsApp question. Reply with exactly one "
    "word: project (about one job's data: crew, permits, violations, open "
    "items, deliveries, drawings, activity), all (about all of their jobs at "
    "once), or general (how to use the app, or general NYC DOB / safety "
    "knowledge with no specific job)."
)
