"""Things an admin or PM can get done by DM with the assistant, in their own
words: add a job, put a sub on a job, add a person, set a sub's punch
contact, change a job's settings. Pure parts (no database, no network): the
action a message asks for, its fields checked, and every reply.

RULE ONE: people talk normally and the bot answers like a helpful person. No
commands to learn, no jargon, short replies (two short sentences at most), in
the language they wrote (English or Spanish; Yiddish gets English). A
70-year-old super understands every message. No ids, no field names, never a
whole phone number (the last 4 only).

READING. The model reads the intent out of loose text (typos, no
punctuation, EN/ES/YI mixed, voice transcripts) into an action and fields
(MODEL_PROMPT); `clean()` checks every field -- the model's answer is never
trusted as it comes. Without the model (no key, an error, a bad answer)
`rules()` reads the same messages by pattern. Missing information is asked
one short question at a time; between people or jobs it never guesses.

SAFETY. A low-risk change (add a job, a sub, a person, a punch contact, a
setting) needs a plain "yes". Sending punch lists for real needs the job's
address typed back, by an admin. "undo" / "never mind" within 10 minutes
reverses the last change; every change is audited (server.py).
"""

from __future__ import annotations

import re

from lib import trades as lib_trades
from typing import Any, Dict, List, Optional

from lib import multilang

ACTIONS = ("add_job", "add_sub", "add_person", "set_punch_contact", "set_setting",
           "undo", "unsupported", "none")
#: Settings a DM can change: what it is, and the values it takes.
SETTINGS = {"chase_weekends": (True, False), "punch_sends": ("shadow", "live")}
BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
GC_TEAM = "GC team"
UNDO_MINUTES = 10
#: How long a question stays open.
PENDING_SECONDS = 15 * 60

_MAX = {"address": 120, "job": 80, "company": 80, "trade": 40, "name": 60, "role": 40,
        "what": 80, "borough": 20, "zip": 5, "phone": 20}


# ── READING ──────────────────────────────────────────────────────────────────

MODEL_PROMPT = """You read one WhatsApp message that a construction company's admin or project
manager sent to their assistant, and say what they want done. They write loosely: typos, no
punctuation, English, Spanish or Yiddish mixed, voice-note transcripts.

Reply with ONE JSON object, nothing else:
{"action": one of "add_job" | "add_sub" | "add_person" | "set_punch_contact" | "set_setting"
            | "undo" | "unsupported" | "none",
 "address": street address of a NEW job, as written ("9 menahan st"),
 "borough": "Manhattan" | "Brooklyn" | "Queens" | "Bronx" | "Staten Island" if they said one,
 "zip": 5-digit ZIP if they said one,
 "job": the EXISTING job they mean, as they said it ("588", "thomas boyland"),
 "company": a subcontractor company's name ("Power Direct"); "GC team" when they say "our"/"we",
 "trade": the sub's trade in one or two words ("electrical", "plumbing"),
 "name": a person's name,
 "role": the person's role if said ("super", "foreman", "pm"),
 "phone": the phone number exactly as written,
 "setting": "chase_weekends" (reminding subs on Saturday/Sunday) or "punch_sends" (punch lists
            really sent, or only shown to them as practice),
 "value": for chase_weekends true/false; for punch_sends "live" (for real) or "shadow" (practice),
 "what": for "unsupported", the thing they asked in 2-4 words}
Leave out keys you do not know. Never invent a value they did not say.

- add_job: a new job / address to start tracking. "add 9 menahan", "we got a new job on 9 menahan
  st", "start tracking 588 thomas boyland", "nuevo trabajo en 9 menahan".
- add_sub: a company working on a job. "put power direct on 588 they're the electrician".
- add_person: someone's name and number. "chris is our super his number is 718 555 1234".
- set_punch_contact: who gets a sub's punch lists. "dov handles punch for power direct".
- set_setting: "stop bugging people on weekends at 588" -> chase_weekends false at job 588;
  "start sending punch lists for real at 588" -> punch_sends live.
- undo: "undo that", "never mind", "wait no", "cancel", "olvídalo".
- unsupported: anything else they want CHANGED (delete a job, remove a user, rename...).
- none: a question or anything that is not a request to change something."""


def _fold(text: Any) -> str:
    t = multilang.fold(str(text or ""))
    t = re.sub(r"(\w)'s\b", r"\1", t).replace("'", "")       # "dov's number" -> "dov number"
    t = re.sub(r"[^\w#@+&/\-\s]", " ", t)
    return " ".join(t.split())


def _one_line(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n].strip(" ,.;:-")


def phone_digits(raw: Any) -> str:
    """10 digits ("718 555 1234" -> "7185551234"), or 11 with a leading 1;
    "" when it is not a phone number."""
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


_PHONE_LIKE = re.compile(r"\+?\(?\d[\d\s().\-]{5,}\d")


def redact(text: Any) -> str:
    """What they said, for the audit: every phone-like run of digits as its
    last 4 only ("718 555 1234" -> "…1234")."""
    def short(m):
        d = re.sub(r"\D", "", m.group(0))
        return f"…{d[-4:]}" if len(d) >= 7 else m.group(0)
    return _PHONE_LIKE.sub(short, str(text or ""))


def last4(phone: Any) -> str:
    d = re.sub(r"\D", "", str(phone or ""))
    return d[-4:] if len(d) >= 4 else ""


_BOROUGH_WORDS = {
    "manhattan": "Manhattan", "new york": "Manhattan", "nyc": "Manhattan", "mn": "Manhattan",
    "brooklyn": "Brooklyn", "bklyn": "Brooklyn", "bk": "Brooklyn", "bkln": "Brooklyn",
    "queens": "Queens", "qns": "Queens", "qn": "Queens",
    "bronx": "Bronx", "the bronx": "Bronx", "bx": "Bronx", "el bronx": "Bronx",
    "staten island": "Staten Island", "si": "Staten Island", "staten": "Staten Island",
}


def borough(raw: Any) -> str:
    t = _fold(raw)
    t = re.sub(r"^(?:in|en|its|it s|it's|the borough is)\s+", "", t)
    return _BOROUGH_WORDS.get(t, "")


def find_borough(text: Any) -> str:
    """A borough named anywhere in the text ("9 menahan brooklyn")."""
    t = f" {_fold(text)} "
    for word in sorted(_BOROUGH_WORDS, key=len, reverse=True):
        if len(word) > 3 and f" {word} " in t:
            return _BOROUGH_WORDS[word]
    return ""


def find_zip(text: Any) -> str:
    m = re.search(r"\b(1[01]\d{3})\b", str(text or ""))
    return m.group(1) if m else ""


# The trade words: lib/trades.SYNONYMS (one list, mapped to the published
# labels -- "electrician" -> "Electrical", "sheetrock" -> "Drywall").


def trade(raw: Any) -> str:
    """"they're the electrician" -> "Electrical"; an unknown trade as said."""
    t = _fold(raw)
    t = re.sub(r"^(?:they re|they are|theyre|hes|shes|as|is|are|son|es|como|the|our|el|la|los|las)\s+",
               "", t)
    t = re.sub(r"^(?:the|our|el|la|los|las)\s+", "", t)
    t = re.sub(r"\s+(?:guys?|company|sub|contractor|trade)$", "", t).strip()
    if not t:
        return ""
    syn = lib_trades.SYNONYMS
    for cand in (t, t.rstrip("s")):
        if cand in syn:
            return syn[cand]
    for w in t.split():
        for cand in (w, w.rstrip("s")):
            if cand in syn:
                return syn[cand]
    return " ".join(w.capitalize() for w in t.split())[:_MAX["trade"]]


def _title(s: str) -> str:
    return " ".join(w if re.search(r"\d", w) else w[:1].upper() + w[1:] for w in s.split())


def clean(raw: Any) -> Dict[str, Any]:
    """The model's (or the patterns') answer, every field checked; anything
    not understood is dropped. {"action": "none"} when nothing usable."""
    if not isinstance(raw, dict):
        return {"action": "none"}
    action = str(raw.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return {"action": "none"}
    out: Dict[str, Any] = {"action": action}
    for k in ("address", "job", "company", "name", "role", "what"):
        v = _one_line(raw.get(k), _MAX[k])
        if v and not re.fullmatch(r"(?:none|null|n/?a|unknown|-)", v, re.I):
            out[k] = v
    if raw.get("trade"):
        tr = trade(raw.get("trade"))
        if tr:
            out["trade"] = tr
    b = borough(raw.get("borough")) if raw.get("borough") else ""
    if b:
        out["borough"] = b
    z = re.sub(r"\D", "", str(raw.get("zip") or ""))
    if len(z) == 5:
        out["zip"] = z
    if raw.get("phone"):
        p = phone_digits(raw.get("phone"))
        if p:
            out["phone"] = p
        else:
            out["bad_phone"] = True
    if action == "set_setting":
        s = str(raw.get("setting") or "").strip()
        if s in SETTINGS:
            v = raw.get("value")
            if s == "chase_weekends":
                v = {"true": True, "false": False, "on": True, "off": False}.get(
                    str(v).strip().lower(), v)
            if v in SETTINGS[s]:
                out["setting"], out["value"] = s, v
    if action == "add_job" and out.get("address"):
        a = out["address"]
        out.setdefault("borough", find_borough(a))
        out.setdefault("zip", find_zip(a))
        out = {k: v for k, v in out.items() if v != ""}
    if action == "add_person" and out.get("company") and _fold(out["company"]) in (
            "our", "us", "we", "gc", "gc team", "the gc", "the office", "office", "nuestro",
            "nosotros"):
        out["company"] = GC_TEAM
    if out.get("name"):
        out["name"] = _title(out["name"])
    if out.get("company") and out["company"] != GC_TEAM:
        out["company"] = _title(out["company"])
    return out


# The patterns: the same messages, read without the model.

_UNDO = re.compile(
    r"^(?:undo(?: that| it| the last(?: one)?)?|never ?mind|nevermind|nvm|wait(?:,)? no|no wait"
    r"|cancel(?: that| it)?|scratch that|forget (?:it|that)|take (?:it|that) back|oops"
    r"|deshacer|deshazlo|olvidalo|olvida eso|cancela(?:lo)?|no importa|mejor no|espera no"
    r"|lozt es|farges es|vart nein|nisht)\W*$")
_HOUSE = r"\d+[a-z]?(?:-\d+)?"
_ADD_JOB = re.compile(
    r"^(?:(?:hey|hi|ok|so|yo|please|pls|can you|could you|i need you to|lets|let s)\s+)*"
    r"(?:(?:we\s+)?(?:got|have|just got|signed|picked up)\s+(?:a\s+)?(?:new\s+)?(?:job|project|site|building)"
    r"|(?:add|create|set up|setup|open|start)(?:\s+(?:a|the))?(?:\s+new)?(?:\s+(?:job|project|site))?"
    r"|new\s+(?:job|project|site)|start\s+(?:tracking|watching|monitoring)|track|watch"
    r"|nuevo\s+(?:trabajo|proyecto)|(?:un\s+)?trabajo\s+nuevo|agrega(?:r)?(?:\s+(?:el|un))?(?:\s+(?:trabajo|proyecto))?"
    r"|empieza a (?:seguir|vigilar)|a(?:ñ|n)ade)"
    r"(?:\s+(?:on|at|in|for|en|de|del|called))?\s+(?P<addr>" + _HOUSE + r"\s+[a-z].*)$")
_ADD_SUB = re.compile(
    r"^(?:(?:hey|ok|so|please|pls)\s+)*(?:put|add|assign|pon(?:er)?|agrega(?:r)?|mete(?:r)?)\s+(?:a\s+)?"
    r"(?P<company>[a-z][\w&'.\- ]{1,60}?)\s+(?:on|onto|to|at|for|en|al|a)\s+"
    r"(?:the\s+)?(?:job\s+(?:at\s+)?|el\s+trabajo\s+(?:de\s+)?|trabajo\s+(?:de\s+)?)?"
    r"(?P<job>" + _HOUSE + r"(?:\s+[a-z]+){0,3}?|[a-z]+(?:\s+[a-z]+){0,2}?)"
    r"(?:\s*(?:,|-)?\s*(?:they re|they are|theyre|hes|shes|as|as the|is|for|son|es|como|for the)\s+"
    r"(?P<trade>[a-z][a-z ]{1,30}?))?\s*$")
_SUB_IS = re.compile(
    r"^(?P<company>[a-z][\w&'.\- ]{1,60}?)\s+(?:is|are|son|es)\s+(?:the|our|el|la|los|nuestros?)\s+"
    r"(?P<trade>[a-z]+(?: [a-z]+)?)\s+(?:on|at|for|en|para)\s+(?P<job>" + _HOUSE + r"(?:\s+[a-z]+){0,3})\s*$")
_PHONE = r"(?P<phone>\+?1?[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})"
_PERSON = re.compile(
    r"^(?:(?:add|save|agrega|guarda)\s+)?(?P<name>[a-z][a-z.'\-]+(?: [a-z][a-z.'\-]+){0,2}?)"
    r"(?:\s*,)?\s+(?:(?:is|es)\s+(?P<who>(?:our|the|a|el|la|nuestro|nuestra)?\s*[a-z ]{0,40}?)"
    r"|(?:from|with|at|de|con)\s+(?P<from>[a-z][\w&'. ]{1,40}?))?"
    r"(?:\s*,)?\s*(?:(?:and\s+)?(?:his|her|their|the|su|el)?\s*(?:number|phone|cell|numero|telefono|celular|#)"
    r"(?:\s+(?:is|es))?\s*:?\s*)?" + _PHONE + r"\s*$")
_PERSON_PHONE_FIRST = re.compile(
    r"^(?:(?:add|save|agrega|guarda)\s+)?(?P<name>[a-z][a-z.\-]+(?: [a-z][a-z.\-]+){0,2}?)\s*,?\s*"
    + _PHONE + r"\s*,?\s*(?:(?:from|with|at|de|con)\s+(?P<from>[a-z][\w&. ]{1,40}?)"
    r"|(?:is\s+)?(?:our|the|el|la|nuestro|nuestra)\s+(?P<who>[a-z ]{1,30}?))?\s*$")
_ROLES = {"super": "super", "superintendent": "super", "foreman": "foreman", "pm": "PM",
          "project manager": "PM", "manager": "PM", "capataz": "foreman", "supervisor": "super",
          "encargado": "foreman", "owner": "owner", "dueno": "owner", "safety": "safety",
          "laborer": "laborer", "electrician": "electrician", "plumber": "plumber"}
_PUNCH_CONTACT = [
    re.compile(r"^(?P<name>[a-z][a-z.'\- ]{1,40}?)\s+(?:handles|does|runs|takes care of|is in charge of|"
               r"is the punch contact for|gets|maneja|se encarga de|recibe)\s+(?:the\s+|el\s+|la\s+|las\s+)?"
               r"(?:punch(?: list)?s?|lista(?:s)? de punch|punch list)\s+(?:for|from|de|para)\s+"
               r"(?P<company>[a-z][\w&'. ]{1,60}?)\s*$"),
    re.compile(r"^(?:the\s+)?punch(?: list)?\s+(?:contact|person|guy)\s+(?:for|at)\s+"
               r"(?P<company>[a-z][\w&'. ]{1,60}?)\s+is\s+(?P<name>[a-z][a-z.'\- ]{1,40}?)\s*$"),
    re.compile(r"^(?:send|give)\s+(?P<company>[a-z][\w&'. ]{1,60}?)\s+punch(?: lists?)?\s+to\s+"
               r"(?P<name>[a-z][a-z.'\- ]{1,40}?)\s*$"),
]
_JOB_TAIL = re.compile(r"\b(?:at|on|for|en|in|de|para)\s+(?P<job>" + _HOUSE +
                       r"(?:\s+[a-z]+){0,3}|[a-z]+(?:\s+[a-z]+){0,2})\s*$")
_WEEKEND = re.compile(r"weekend|saturday|sunday|sat and sun|fin(?:es)? de semana|sabado|domingo"
                      r"|shabbos|shabbat|shabes")
_STOP = re.compile(r"\b(?:stop|no|no more|dont|do not|turn off|off|quit|quiet|leave .* alone"
                   r"|deja de|para de|sin|nada|never)\b")
_START = re.compile(r"\b(?:start|turn on|on|ok to|okay to|go ahead and|resume|empieza|activa|si)\b")
_PUNCH_LIVE = re.compile(r"punch.*(?:for real|for reals|live|really|de verdad|en serio|actually send)"
                         r"|(?:go|turn on|switch to|set to)\s+live.*punch|punch.*\bon\b.*real")
_PUNCH_PRACTICE = re.compile(r"punch.*(?:practice|test(?:ing)?|shadow|prueba|stop sending|dont send|don't send)"
                             r"|(?:stop|quit) sending punch")
_UNSUPPORTED = re.compile(r"^(?:please\s+)?(?P<what>(?:delete|remove|erase|get rid of|kill|rename|archive"
                          r"|close out|borra(?:r)?|elimina(?:r)?|quita(?:r)?|cierra)\b.{0,60})$")


# ── WHAT THEY WANT, BEFORE THE DETAILS ───────────────────────────────────────
#
# "Starting a new job I wanna set up" (Mon 7:17 PM, live): no address yet, so
# none of the patterns above matched, the model missed it too, and the DM went
# to the questions assistant -- which asked "Which job? 1) 588 2) 8 Walworth".
# A request with no details is still that request: these catch it, and the
# step asks the one thing missing ("Sure — what's the address?").
_QUESTION = re.compile(r"^(?:what|whats|who|whos|how|hows|when|where|why|which|is|are|do|does|did"
                       r"|any|cuantos|cuantas|que|quien|cuando|donde)\b|\?\s*$")
_BARE = [
    ("set_punch_contact", re.compile(
        r"\b(?:set(?:\s*up)?|add|change|update|pick|choose|new|assign|who gets)\b.{0,30}"
        r"\bpunch(?: list)?\s+(?:contact|person|guy)s?\b"
        r"|\bpunch(?: list)?\s+(?:contact|person)s?\b.{0,20}\b(?:set|add|change|update)\b"
        r"|\bcontacto de punch\b")),
    ("add_job", re.compile(
        r"\b(?:new|another|nuevo|nueva|otro)\s+(?:job|project|site|building|jobsite|trabajo|proyecto|obra)\b"
        r"|\b(?:trabajo|proyecto|obra)\s+(?:nuevo|nueva)\b"
        r"|\b(?:add|adding|create|creating|set\s*up|setting up|start|open|track|agrega(?:r)?|crea(?:r)?)"
        r"\s+(?:a|an|un|una|the)?\s*"
        r"(?:new\s+)?(?:job|project|site|jobsite|trabajo|proyecto|obra)\b"
        r"|\b(?:got|have|signed|picked up|landed|won)\s+(?:a|another)\s+(?:new\s+)?(?:job|project|site)\b")),
    ("add_sub", re.compile(
        r"\b(?:add|adding|put|putting|assign|new|set\s*up|setting up|agrega(?:r)?|pon(?:er)?)\s+"
        r"(?:a|an|another|un|otro)?\s*(?:new\s+)?(?:sub|subs|subcontractor|subcontractors|"
        r"subcontratista|trade)\b")),
    ("add_person", re.compile(
        r"\b(?:add|adding|save|saving|new|put in|agrega(?:r)?|guarda(?:r)?)\s+(?:a|an|another|un|una|otro)?\s*"
        r"(?:new\s+)?(?:someone|somebody|person|contact|number|phone number|guy|worker|people|"
        r"alguien|persona|contacto|numero)\b")),
]


#: A request asked politely is still a request ("Do you mind adding a new
#: job?", "can you add a sub?" -- Codex review on #771).
_POLITE = re.compile(r"^(?:hey\s+|hi\s+|so\s+|ok\s+)*(?:do you mind|would you mind|can you|could you|"
                     r"would you|will you|can we|could we|can i|could i|is it possible to|"
                     r"please|pls|puedes|podrias|me puedes)\b")


def bare_request(text: Any) -> Dict[str, Any]:
    """The request a message makes before any detail is given ("Starting a
    new job I wanna set up", "need to add someone"), else {"action": "none"}.
    Never a question ("any new jobs this week?") -- but a request asked
    politely is one ("do you mind adding a new job?")."""
    t = _fold(text)
    if not t or (_QUESTION.search(t) and not _POLITE.match(t)):
        return {"action": "none"}
    for action, rx in _BARE:
        if rx.search(t):
            return {"action": action}
    return {"action": "none"}


_NOT_JOB = {"for", "real", "reals", "live", "please", "pls", "on", "weekends", "weekend", "too",
            "now", "again", "de", "verdad", "también", "tambien", "also", "the", "lists", "list",
            "punch", "really", "en", "serio", "thanks", "asap", "anymore"}


def _job_words(job: str) -> str:
    """"588 for real" -> "588": the job's words only."""
    out = []
    for w in job.split():
        if w in _NOT_JOB:
            break
        out.append(w)
    return " ".join(out)


def _job_hint(t: str) -> str:
    for m in reversed(list(re.finditer(r"\b(?:at|on|for|en|in|de|para)\s+(?P<job>" + _HOUSE +
                                       r"(?:\s+[a-z]+){0,3})", t))):
        return _job_words(m.group("job"))
    m = _JOB_TAIL.search(t)
    if m:
        return _job_words(m.group("job").strip())
    m = re.search(r"\b(" + _HOUSE + r")\b", t)
    return m.group(1) if m else ""


def _strip_tail(s: str) -> str:
    s = re.sub(r"\s+(?:please|pls|thanks|thank you|for me|por favor|gracias|asap)$", "", s)
    s = re.sub(r"^(?:on|at|en|the)\s+", "", s)
    return s.strip(" ,.")


def rules(text: Any) -> Dict[str, Any]:
    """What the message asks, read by pattern (the model's fallback); the
    result goes through clean() like the model's."""
    t = _fold(text)
    if not t:
        return {"action": "none"}
    if _UNDO.match(t):
        return {"action": "undo"}
    m = _UNSUPPORTED.match(t)
    if m:
        return {"action": "unsupported", "what": m.group("what")}
    for rx in _PUNCH_CONTACT:
        m = rx.match(t)
        if m:
            company, job = _strip_tail(m.group("company")), ""
            # "for arkon at walworth": the sub, then the job.
            at = re.match(r"^(?P<company>.+?)\s+(?:at|on|en)\s+(?:the\s+)?(?P<job>.+?)(?:\s+job)?$", company)
            if at:
                company, job = at.group("company").strip(), at.group("job").strip()
            return clean({"action": "set_punch_contact", "name": m.group("name"),
                          "company": company, "job": job})
    if _WEEKEND.search(t):
        value = False if _STOP.search(t) else (True if _START.search(t) else None)
        if value is not None:
            return clean({"action": "set_setting", "setting": "chase_weekends", "value": value,
                          "job": _job_hint(t)})
    if "punch" in t and _PUNCH_PRACTICE.search(t):
        return clean({"action": "set_setting", "setting": "punch_sends", "value": "shadow",
                      "job": _job_hint(t)})
    if "punch" in t and _PUNCH_LIVE.search(t):
        return clean({"action": "set_setting", "setting": "punch_sends", "value": "live",
                      "job": _job_hint(t)})
    m = _PERSON.match(t) or _PERSON_PHONE_FIRST.match(t)
    if m:
        who = _fold(m.group("who") or "")
        role = next((v for k, v in sorted(_ROLES.items(), key=lambda kv: -len(kv[0]))
                     if re.search(rf"\b{k}\b", who)), "")
        company = ""
        if re.match(r"(?:our|nuestro|nuestra)\b", who) or (
                m.re is _PERSON_PHONE_FIRST and m.group("who")):
            company = GC_TEAM
        elif m.group("from"):
            company = _strip_tail(m.group("from"))
        return clean({"action": "add_person", "name": m.group("name"), "role": role,
                      "company": company, "phone": m.group("phone")})
    m = _ADD_JOB.match(t)
    if m:
        addr = _strip_tail(m.group("addr"))
        return clean({"action": "add_job", "address": addr})
    for rx in (_ADD_SUB, _SUB_IS):
        m = rx.match(t)
        if m:
            company = _strip_tail(m.group("company"))
            if re.fullmatch(_HOUSE + r"(?:\s+\w+)*", company):
                continue                       # "add 9 menahan": a job, not a sub
            return clean({"action": "add_sub", "company": company,
                          "job": _strip_tail(m.group("job")),
                          "trade": (m.groupdict().get("trade") or "").strip()})
    return bare_request(text)


#: Words that make a message worth reading as a request at all (before the
#: model is asked): the rest goes to the questions assistant as before.
_HINT = re.compile(
    r"\b(?:add|new job|new project|got a (?:new )?job|start tracking|track|put|assign|number is|"
    r"phone is|cell is|\d{3}\D{0,2}\d{3}\D{0,2}\d{4}|handles punch|punch (?:contact|list|lists)|"
    r"picked up|bldg|building|new site|foreman|cell|"
    r"weekends?|saturday|sunday|for real|live|undo|never ?mind|nvm|wait no|scratch that|cancel|"
    r"delete|remove|rename|is our|is the|nuevo|agrega|pon |numero|fin(?:es)? de semana|olvidalo|"
    r"deshacer|borra|elimina|maneja|se encarga)\b")


def looks_like_request(text: Any) -> bool:
    t = _fold(text)
    return bool(t) and (bool(_HINT.search(t)) or rules(text).get("action") not in ("none", None))


# ── ANSWERS: yes / no / a pick ───────────────────────────────────────────────

_YES = re.compile(
    r"^(?:y|ya|yes|yeah|yea|yep|yup|yess+|sure|ok|okay|okey|k|kk|go ahead|go for it|do it|"
    r"please do|correct|right|thats right|that s right|yes please|yes do it|perfect|great|"
    r"si|sí|si si|dale|claro|va|listo|hazlo|correcto|de una|por favor|perfecto|bueno|"
    r"yo|avade|zicher|zikher|takeh|gut)\W*$")
_NO = re.compile(
    r"^(?:n|no|nope|nah|no thanks|don t|dont|do not|not now|stop|cancel|no no|wrong|"
    r"no gracias|mejor no|nel|nein|neyn|nisht)\W*$")
_YES_EMOJI = ("👍", "✅", "👌", "🙏", "💯", "✔")
_NO_EMOJI = ("👎", "❌", "✋", "🚫")


def yes_no(text: Any) -> Optional[bool]:
    raw = str(text or "").strip()
    if raw and all(ch in "".join(_YES_EMOJI) + "️\U0001f3fb\U0001f3fc\U0001f3fd\U0001f3fe\U0001f3ff "
                   for ch in raw):
        return True
    if raw and any(e in raw for e in _NO_EMOJI) and not re.search(r"\w", raw):
        return False
    t = _fold(raw)
    if _YES.match(t):
        return True
    if _NO.match(t):
        return False
    return None


def is_undo(text: Any) -> bool:
    return bool(_UNDO.match(_fold(text)))


def pick(text: Any, options: List[str]) -> Optional[int]:
    """Which of `options` the answer picks: "2", "the second", "number 2",
    or words of one option only. None when unclear."""
    t = _fold(text)
    words = {"first": 1, "1st": 1, "one": 1, "primero": 1, "primera": 1, "uno": 1,
             "second": 2, "2nd": 2, "two": 2, "segundo": 2, "segunda": 2, "dos": 2,
             "third": 3, "3rd": 3, "three": 3, "tercero": 3, "tercera": 3, "tres": 3}
    m = re.fullmatch(r"(?:#|no |number |numero |el |la |the )?(\d)(?: please| por favor)?", t)
    n = int(m.group(1)) if m else next((v for k, v in words.items()
                                        if re.fullmatch(rf"(?:the |el |la |number )?{k}(?: one)?", t)), None)
    if n and 1 <= n <= len(options):
        return n - 1
    hits = [i for i, o in enumerate(options)
            if t and len(t) >= 3 and (t in _fold(o) or _fold(o).startswith(t))]
    return hits[0] if len(hits) == 1 else None


_ES_HINT = {"nuevo", "nueva", "trabajo", "proyecto", "agrega", "agregar", "pon", "poner", "numero",
            "telefono", "celular", "fines", "semana", "olvidalo", "deshacer", "maneja", "encarga",
            "plomeros", "electricistas", "pintores", "molestar", "nuestro", "nuestra", "capataz",
            "dale", "gracias", "cual", "donde", "quien", "recordatorios", "listas", "verdad", "si",
            "son", "su", "los", "las", "el", "de", "en", "es", "un", "una", "para", "con"}
_EN_HINT = {"the", "on", "at", "is", "our", "add", "put", "new", "job", "his", "her", "number",
            "they", "we", "got", "start", "stop", "for", "and", "to", "with", "from", "please"}


def reply_lang(text: Any) -> str:
    """The language to answer in: Spanish when they wrote Spanish; English
    otherwise (Yiddish gets English)."""
    if multilang.detect(text) == "es":
        return "es"
    words = _fold(text).split()
    es = sum(1 for w in words if w in _ES_HINT)
    en = sum(1 for w in words if w in _EN_HINT)
    return "es" if es >= 2 and es > en else "en"


# ── PLAIN WORDS OUT ──────────────────────────────────────────────────────────

_ABBR = {"STREET": "St", "AVENUE": "Ave", "ROAD": "Rd", "BOULEVARD": "Blvd", "PLACE": "Pl",
         "COURT": "Ct", "DRIVE": "Dr", "LANE": "Ln", "PARKWAY": "Pkwy", "TERRACE": "Ter",
         "EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S", "HIGHWAY": "Hwy",
         "EXPRESSWAY": "Expy", "SQUARE": "Sq", "PLAZA": "Plz"}


def pretty_address(label: Any, with_borough: bool = True) -> str:
    """GeoSearch's "9 MENAHAN STREET, Brooklyn, NY, USA" -> "9 Menahan St,
    Brooklyn" (or "9 Menahan St")."""
    parts = [p.strip() for p in str(label or "").split(",") if p.strip()]
    if not parts:
        return ""
    words = []
    for w in parts[0].split():
        up = w.upper()
        words.append(_ABBR.get(up) or (w if re.search(r"\d", w) else w[:1].upper() + w[1:].lower()))
    street = " ".join(words)
    if with_borough and len(parts) > 1 and parts[1] not in ("NY", "USA"):
        return f"{street}, {parts[1]}"
    return street


TEXT = {
    "en": {
        "found": "Found it: {place}. Add it as a new job?",
        "which_place": "I found a few. Which one?",
        "no_match": "I couldn't find that address. Which borough is it in?",
        "no_match_again": "I still can't find it. What's the ZIP code?",
        "no_match_last": "I can't find that address. You can add it in the app.",
        "ask_address": "Sure — what's the address?",
        "already_job": "{job} is already one of your jobs.",
        "job_done": "Done — {job} is set up. I'll start watching DOB and DOT for it.",
        "which_job": "Which job?",
        "which_one": "Which one?",
        "no_job": "I don't see that job. Which one did you mean?",
        "ask_company": "Which company?",
        "ask_trade": "What trade is {company}?",
        "trade_unknown": "{trade} isn't on your trade list — did you mean: {options}? "
                         "Or add '{trade}' as a new trade?",
        "sub_confirm": "Add {company} ({trade}) to {job}?",
        "sub_already": "{company} is already on {job} for {trade}.",
        "sub_done": "Done — {company} is on {job} for {trade}.",
        "ask_name": "What's their name?",
        "ask_phone": "What's {name}'s number?",
        "bad_phone": "That doesn't look like a phone number. Can you send it again?",
        "ask_works_for": "Who does {name} work for?",
        "unknown_company": "I don't see {company} on your jobs. Who does {name} work for?",
        "person_confirm": "Save {name} ({company}), number ending {last4}?",
        "person_update": "{name} is saved already. Update to {company}, number ending {last4}?",
        "person_done": "Done — {name} is saved.",
        "which_person": "Which {first} — {options}?",
        "no_person": "I don't have {name} saved yet. What's their number?",
        "no_person_at": "I don't have {name} from {company} saved yet. What's their number?",
        "contact_confirm": "Send {company}'s punch lists at {job} to {name}?",
        "contact_wrong_company": "{name} isn't with {company}. Who handles punch for {company}?",
        "contact_done": "Done — {name} gets {company}'s punch lists at {job}.",
        "sub_not_on_job": "{company} isn't on {job}. Add them first, then I can set their punch contact.",
        "ask_setting": "What should I change at {job}?",
        "weekends_off_confirm": "Stop reminding people on weekends at {job}?",
        "weekends_on_confirm": "Remind people on weekends too at {job}?",
        "weekends_off_done": "Done — no weekend reminders at {job}.",
        "weekends_on_done": "Done — weekend reminders are on at {job}.",
        "weekends_same_off": "Weekend reminders are already off at {job}.",
        "weekends_same_on": "Weekend reminders are already on at {job}.",
        "live_confirm": "This makes punch lists really go out to the subs at {job}. To confirm, type the job's address.",
        "live_done": "Done — punch lists at {job} now really go out.",
        "live_mismatch": "That didn't match the address, so nothing changed.",
        "practice_confirm": "Put punch lists at {job} back to practice (nothing sent)?",
        "practice_done": "Done — punch lists at {job} are back to practice. Nothing gets sent.",
        "live_same": "Punch lists at {job} already go out for real.",
        "practice_same": "Punch lists at {job} are already in practice mode.",
        "admin_only": "Only a company admin can do that. I can add people, subs and punch contacts for you.",
        "admin_only_live": "Only a company admin can turn that on.",
        "not_approved": "Your account isn't approved yet, so I can't make changes. Ask your admin.",
        "which_sub": "Which one?",
        "cancelled": "OK, I won't do it.",
        "nothing_to_undo": "There's nothing to undo.",
        "undo_too_late": "That was too long ago to undo here. You can change it in the app.",
        "undone": "Undone — {what}.",
        "undo_job": "{job} is removed",
        "undo_sub": "{company} is off {job}",
        "undo_person_new": "{name} is removed",
        "undo_person_old": "{name} is back the way it was",
        "undo_contact": "{job}'s punch contact is back the way it was",
        "undo_setting": "{job} is back the way it was",
        "yes_or_no": "Should I go ahead? Yes or no.",
        "pick_again": "Which one? Send the number.",
        "unsupported": "I can't do that here yet — please use the app. I can add jobs, subs and people, and change job settings.",
        "failed": "Sorry, that didn't work. Nothing changed — please try again in a minute.",
    },
    "es": {
        "found": "Lo encontré: {place}. ¿Lo agrego como trabajo nuevo?",
        "which_place": "Encontré varios. ¿Cuál es?",
        "no_match": "No encontré esa dirección. ¿En qué condado está?",
        "no_match_again": "Todavía no la encuentro. ¿Cuál es el código postal?",
        "no_match_last": "No encuentro esa dirección. Puede agregarla en la app.",
        "ask_address": "Claro, ¿cuál es la dirección?",
        "already_job": "{job} ya es uno de sus trabajos.",
        "job_done": "Listo — {job} está creado. Voy a vigilar DOB y DOT para ese trabajo.",
        "which_job": "¿Cuál trabajo?",
        "which_one": "¿Cuál?",
        "no_job": "No veo ese trabajo. ¿Cuál quiso decir?",
        "ask_company": "¿Qué compañía?",
        "ask_trade": "¿Qué oficio tiene {company}?",
        "trade_unknown": "{trade} no está en su lista de oficios — ¿quiso decir: {options}? "
                         "¿O agrego '{trade}' como oficio nuevo?",
        "sub_confirm": "¿Agrego a {company} ({trade}) en {job}?",
        "sub_already": "{company} ya está en {job} para {trade}.",
        "sub_done": "Listo — {company} está en {job} para {trade}.",
        "ask_name": "¿Cómo se llama?",
        "ask_phone": "¿Cuál es el número de {name}?",
        "bad_phone": "Eso no parece un número de teléfono. ¿Me lo manda otra vez?",
        "ask_works_for": "¿Para quién trabaja {name}?",
        "unknown_company": "No veo a {company} en sus trabajos. ¿Para quién trabaja {name}?",
        "person_confirm": "¿Guardo a {name} ({company}), número que termina en {last4}?",
        "person_update": "{name} ya está guardado. ¿Lo cambio a {company}, número que termina en {last4}?",
        "person_done": "Listo — {name} está guardado.",
        "which_person": "¿Cuál {first} — {options}?",
        "no_person": "Todavía no tengo a {name}. ¿Cuál es su número?",
        "no_person_at": "Todavía no tengo a {name} de {company}. ¿Cuál es su número?",
        "contact_confirm": "¿Mando las listas de punch de {company} en {job} a {name}?",
        "contact_wrong_company": "{name} no es de {company}. ¿Quién recibe el punch de {company}?",
        "contact_done": "Listo — {name} recibe las listas de punch de {company} en {job}.",
        "sub_not_on_job": "{company} no está en {job}. Agréguelo primero y luego pongo su contacto.",
        "ask_setting": "¿Qué cambio en {job}?",
        "weekends_off_confirm": "¿Dejo de mandar recordatorios los fines de semana en {job}?",
        "weekends_on_confirm": "¿Mando recordatorios también los fines de semana en {job}?",
        "weekends_off_done": "Listo — no hay recordatorios los fines de semana en {job}.",
        "weekends_on_done": "Listo — hay recordatorios los fines de semana en {job}.",
        "weekends_same_off": "Los recordatorios de fin de semana ya están apagados en {job}.",
        "weekends_same_on": "Los recordatorios de fin de semana ya están prendidos en {job}.",
        "live_confirm": "Así las listas de punch de {job} se mandan de verdad a los subs. Para confirmar, escriba la dirección.",
        "live_done": "Listo — las listas de punch de {job} ahora se mandan de verdad.",
        "live_mismatch": "No coincide con la dirección, así que no cambié nada.",
        "practice_confirm": "¿Pongo las listas de punch de {job} en práctica (no se manda nada)?",
        "practice_done": "Listo — las listas de punch de {job} están en práctica. No se manda nada.",
        "live_same": "Las listas de punch de {job} ya se mandan de verdad.",
        "practice_same": "Las listas de punch de {job} ya están en práctica.",
        "admin_only": "Solo un administrador puede hacer eso. Yo puedo agregar personas, subs y contactos de punch.",
        "admin_only_live": "Solo un administrador puede prender eso.",
        "not_approved": "Su cuenta todavía no está aprobada, así que no puedo hacer cambios. Pregúntele a su administrador.",
        "which_sub": "¿Cuál?",
        "cancelled": "Está bien, no lo hago.",
        "nothing_to_undo": "No hay nada que deshacer.",
        "undo_too_late": "Ya pasó mucho tiempo para deshacerlo aquí. Puede cambiarlo en la app.",
        "undone": "Deshecho — {what}.",
        "undo_job": "{job} se quitó",
        "undo_sub": "{company} ya no está en {job}",
        "undo_person_new": "{name} se quitó",
        "undo_person_old": "{name} quedó como estaba",
        "undo_contact": "el contacto de punch de {job} quedó como estaba",
        "undo_setting": "{job} quedó como estaba",
        "yes_or_no": "¿Lo hago? Sí o no.",
        "pick_again": "¿Cuál? Mande el número.",
        "unsupported": "Eso todavía no lo puedo hacer aquí — use la app. Puedo agregar trabajos, subs y personas, y cambiar ajustes.",
        "failed": "Perdón, no funcionó. No cambió nada — intente de nuevo en un minuto.",
    },
}


def say(lang: str, key: str, **kw: Any) -> str:
    table = TEXT.get(lang) or TEXT["en"]
    return (table.get(key) or TEXT["en"][key]).format(**kw)


def numbered(question: str, options: List[str]) -> str:
    """"Which one?" and a short numbered list, one per line."""
    return question + "\n" + "\n".join(f"{i}) {o}" for i, o in enumerate(options, 1))


def or_list(options: List[str], lang: str = "en") -> str:
    word = " o " if lang == "es" else " or "
    return options[0] if len(options) == 1 else ", ".join(options[:-1]) + word + options[-1]


def company_label(company: str) -> str:
    """"GC team" reads as "GC" in a name list."""
    return "GC" if company == GC_TEAM else company


_JARGON = re.compile(r"\b(?:BIN|BBL|id|ids|project_id|trade_assignments?|sender_map|shadow|"
                     r"punch_sends|chase_weekends|null|None|JSON|API|webhook|GeoSearch)\b|[_{}<>]")


def plain(text: str) -> List[str]:
    """What breaks rule one in a reply (empty when it is fine): more than
    two sentences (a numbered list's lines aside), jargon or an id, a whole
    phone number."""
    problems = []
    lines = [ln for ln in str(text).split("\n") if not re.match(r"\s*\d+\)\s", ln)]
    body = " ".join(lines)
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", body.strip()) if s.strip()]
    if len(sentences) > 2:
        problems.append(f"{len(sentences)} sentences")
    if _JARGON.search(text):
        problems.append(f"jargon: {_JARGON.search(text).group(0)}")
    if re.search(r"\d{3}\D{0,2}\d{3}\D{0,2}\d{4}", text) or re.search(r"\d{7,}", text):
        problems.append("a whole number")
    if len(body) > 220:
        problems.append(f"{len(body)} characters")
    return problems
