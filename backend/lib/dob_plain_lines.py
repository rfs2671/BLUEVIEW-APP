"""The model's plain one-liner for a DOB record that has free text and no
usable code: the prompt, the checker, and the sweep that stores it.

ORDER (lib/dob_plain_labels has the tables):
  1. The record's code is in a table and the row is specific -> that line,
     source "code". No model.
  2. The record has DOB's own free text (a violation description, a 311
     descriptor) -> the model writes {en, es} ONCE, the checker below reads
     it, and the result is STORED on the row. Source "llm".
  3. The checker refused the line, or there is no free text -> the record's
     broad code row if it has one (source "code"), else the neutral generic
     line (source "fallback").

ONCE, IN THE BACKGROUND. `sweep` runs from a scheduled job (server.py
`_dob_plain_lines_job`), never from a request. A row it has decided carries
`plain_line_version`; a row the model was asked about carries
`plain_line_check`, and neither is ever sent to the model again. Another row of
the same record (a 311 status change inserts a new row) copies the stored
answer instead of asking. A model call that fails outright (timeout, HTTP
error) is not an answer: it is counted in `plain_line_llm_tries` and tried on a
later tick, at most MAX_TRIES times, then the row takes step 3.

THE READ PATH NEVER ASKS. `line_for_read` returns the stored line, or for a
row the sweep has not reached yet the deterministic line (step 1 / 3) -- it has
no model argument to call.

THE CHECKER. Deterministic, and it only refuses: a line that names a number,
date, money amount, address or party that is not in the DOB text is rejected.
"In the DOB text" is read on the text the model was given (`dob_text`), case-
insensitively. A party is detected as (a) any capitalised word after the first
word of the line (and after sentence punctuation) that does not occur in the
DOB text and is not one of the agency acronyms in ACRONYMS, or (b) a company
or honorific token (Inc, LLC, Corp, Mr ...) that does not occur in it. A
proper name used as the FIRST word of the line is the gap in (a); the prompt
asks for sentence case and no names, and (b) still catches a company suffix
there.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from lib.dob_plain_labels import (
    MAX_WORDS, code_label, dob_text, free_text, generic_label, word_count,
    ECB_DATASET,
)

__all__ = [
    "PLAIN_LINE_VERSION", "MAX_TRIES", "SOURCES", "build_prompt", "parse_reply",
    "check_line", "check_pair", "needs_model", "plan_line", "sweep",
    "line_for_read",
]

PLAIN_LINE_VERSION = 1
MAX_TRIES = 3                 # failed model CALLS per record before step 3
SWEEP_BATCH = 500             # rows read per tick
SWEEP_LLM_BUDGET = 40         # model calls per tick (a backlog drains over ticks)
RECORD_TYPES = ("complaint", "violation", "swo")
SOURCES = ("code", "llm", "fallback")

PROMPT = """You rewrite one New York City Department of Buildings record as a plain one-line summary for a construction superintendent.

Rules:
- At most 12 words in each language.
- Say what the problem is, in everyday words. No legal or code language.
- Do NOT write any number, date, dollar amount, address, street name, or name of a person or company. Leave them out.
- No code section numbers and no record numbers.
- Sentence case: capitalise only the first word and agency acronyms such as DOB or DOT.
- Spanish line: the same meaning, in plain Spanish.

Reply with JSON only, nothing else: {{"en": "...", "es": "..."}}

Record type: {kind}
Record text:
{text}
"""

ACRONYMS = frozenset({"DOB", "ECB", "OATH", "DOT", "FDNY", "NYC", "DEP"})

_NUMBER_WORDS = {
    "en": {
        "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
        "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16",
        "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
        "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
        "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
        "million": "1000000", "dozen": "12", "first": "1", "second": "2",
        "third": "3", "fourth": "4", "fifth": "5", "sixth": "6", "seventh": "7",
        "eighth": "8", "ninth": "9", "tenth": "10",
    },
    "es": {
        "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
        "ocho": "8", "nueve": "9", "diez": "10", "once": "11", "doce": "12",
        "trece": "13", "catorce": "14", "quince": "15", "dieciséis": "16",
        "diecisiete": "17", "dieciocho": "18", "diecinueve": "19", "veinte": "20",
        "treinta": "30", "cuarenta": "40", "cincuenta": "50", "sesenta": "60",
        "setenta": "70", "ochenta": "80", "noventa": "90", "cien": "100",
        "ciento": "100", "mil": "1000", "millón": "1000000", "millones": "1000000",
        "docena": "12", "primer": "1", "primero": "1", "primera": "1",
        "segundo": "2", "segunda": "2", "tercer": "3", "tercero": "3",
        "tercera": "3", "cuarto": "4", "cuarta": "4", "quinto": "5", "quinta": "5",
    },
}

# "may" (a verb) and "mar" (Spanish for sea) are left out on purpose; a date
# that uses them carries a day number, which the number rule reads.
_DATE_WORDS = frozenset("""
january february march april june july august september sept october november
december jan feb apr jun jul aug sep oct nov dec
enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre
noviembre diciembre
monday tuesday wednesday thursday friday saturday sunday
lunes martes miércoles miercoles jueves viernes sábado sabado domingo
today tomorrow yesterday tonight hoy ayer anoche
""".split())

_MONEY_WORDS = frozenset("dollar dollars usd cents dólar dólares dolar dolares centavos".split())
_PARTY_TOKENS = frozenset("inc llc corp corporation ltd pllc llp lp mr mrs ms sr sra srta".split())
_PLACES = ("brooklyn", "manhattan", "queens", "bronx", "staten island", "new york", "nueva york")
_STREET_SUFFIX = r"(?:street|st|avenue|ave|boulevard|blvd|road|rd|parkway|pkwy|terrace|highway|hwy|place|pl)"
_ADDR_STOP = frozenset("""the a an this that on in at of to from for no without along into
same its their each every any one""".split())
_ES_STREET = r"(?:calle|avenida|bulevar|carretera)"
_ES_STOP = frozenset("de del la el las los sin con para por y o a en al su una un".split())

_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*")


def _squash(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _digits(text: str) -> set:
    # 10,000 -> 10000; every digit run, without leading zeros.
    joined = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text or "")
    return {str(int(d)) for d in re.findall(r"\d+", joined)}


def _words(text: str) -> set:
    return {w.lower().strip("'’-") for w in _WORD.findall(text or "")}


def build_prompt(row: Dict[str, Any], text: str) -> str:
    rtype = str(row.get("record_type") or "")
    if rtype == "complaint":
        kind = "311 complaint"
    elif str(row.get("dataset") or "") == ECB_DATASET:
        kind = "ECB violation (summons)"
    elif rtype == "swo":
        kind = "DOB stop work order"
    else:
        kind = "DOB violation"
    return PROMPT.format(kind=kind, text=text)


def parse_reply(reply: Any) -> Optional[Dict[str, str]]:
    """{en, es} from the model's reply, or None. Tolerates a ```json fence."""
    s = str(reply or "")
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    en, es = obj.get("en"), obj.get("es")
    if not isinstance(en, str) or not isinstance(es, str):
        return None
    return {"en": _squash(en), "es": _squash(es)}


def check_line(line: str, source: str, lang: str = "en") -> Tuple[bool, str]:
    """(ok, reason). Refuses a line that is empty, over MAX_WORDS, or names a
    number, date, money amount, address or party not in `source`."""
    raw = str(line or "")
    s = _squash(raw)
    if not s:
        return False, "empty line"
    if "\n" in raw.strip():
        return False, "more than one line"
    n = word_count(s)
    if n > MAX_WORDS:
        return False, f"{n} words (max {MAX_WORDS})"
    src = _squash(source)
    src_low = src.lower()
    src_digits = _digits(src)
    src_words = _words(src)
    low = s.lower()

    extra = sorted(_digits(s) - src_digits, key=lambda d: (len(d), d))
    if extra:
        return False, f"number {extra[0]} is not in the DOB text"

    words_in_order = _WORD.findall(s)
    lw = [w.lower().strip("'’-") for w in words_in_order]
    for w in lw:
        digit = _NUMBER_WORDS.get(lang, {}).get(w)
        if digit and w not in src_words and digit not in src_digits:
            return False, f"number '{w}' is not in the DOB text"
    for w in lw:
        if w in _DATE_WORDS and w not in src_words:
            return False, f"date '{w}' is not in the DOB text"

    if "$" in s or any(w in _MONEY_WORDS for w in lw):
        if "$" not in src and not (_MONEY_WORDS & src_words):
            return False, "money amount is not in the DOB text"

    for place in _PLACES:
        if re.search(rf"\b{place}\b", low) and place not in src_low:
            return False, f"place '{place}' is not in the DOB text"
    for m in re.finditer(rf"\b([a-z0-9'’\-]+)\s+{_STREET_SUFFIX}\b\.?", low):
        before = m.group(1)
        if before in _ADDR_STOP:
            continue
        if _squash(m.group(0)).rstrip(".") not in src_low and before not in src_words:
            return False, f"address '{_squash(m.group(0))}' is not in the DOB text"
    for m in re.finditer(rf"\b{_ES_STREET}\s+([a-záéíóúñü0-9'’\-]+)", low):
        if m.group(1) not in _ES_STOP and m.group(1) not in src_words:
            return False, f"address '{_squash(m.group(0))}' is not in the DOB text"

    for w in lw:
        if w.rstrip(".") in _PARTY_TOKENS and w.rstrip(".") not in src_words:
            return False, f"party '{w}' is not in the DOB text"
    # A capitalised word that is neither the line's first word nor right after
    # sentence punctuation reads as a name. It must come from the DOB text.
    for m in _WORD.finditer(s):
        tok = m.group(0)
        if not tok[0].isupper():
            continue
        before = s[:m.start()].rstrip()
        if not before or before[-1] in ".:;!?—–-(\"'“":
            continue
        if tok in ACRONYMS or tok.lower().strip("'’-") in src_words:
            continue
        return False, f"'{tok}' looks like a name and is not in the DOB text"
    return True, "ok"


def check_pair(pair: Optional[Dict[str, str]], source: str) -> Tuple[bool, str]:
    if not pair:
        return False, "reply was not {en, es} JSON"
    for lang in ("en", "es"):
        ok, why = check_line(pair.get(lang, ""), source, lang)
        if not ok:
            return False, f"{lang}: {why}"
    return True, "ok"


def _pair(label: Dict[str, Any]) -> Dict[str, str]:
    return {"en": label["en"], "es": label["es"]}


def _deterministic(row: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
    """Step 3: the broad code row, else the generic line."""
    code = code_label(row)
    if code:
        return _pair(code), "code"
    return generic_label(row), "fallback"


def needs_model(row: Dict[str, Any]) -> bool:
    """Would deciding this row ask the model (if it has not been asked)?"""
    code = code_label(row)
    if code and not code.get("broad"):
        return False
    return bool(free_text(row))


def ready(row: Dict[str, Any]) -> bool:
    """Has the DOB sync stamped this row with what the decision reads? A
    violation row stored before the sync recorded its `dataset`, or an ECB row
    stored before it recorded the summons' infraction code, would be judged on
    half its fields; the next sync refreshes it in place."""
    if str(row.get("record_type") or "") in ("violation", "swo"):
        if "dataset" not in row:
            return False
        if str(row.get("dataset") or "") == ECB_DATASET and "ecb_status" not in row:
            return False
    return True


LLM = Callable[[str, Dict[str, Any]], Awaitable[Any]]


async def plan_line(row: Dict[str, Any], *, llm: Optional[LLM], model: str = "",
                    now: Optional[datetime] = None,
                    prior: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(fields to $set, called_model). Fields None = undecided (the model is
    needed and not available this tick)."""
    now = now or datetime.now(timezone.utc)
    base = {"plain_line_version": PLAIN_LINE_VERSION, "plain_line_generated_at": now}
    code = code_label(row)
    if code and not code.get("broad"):
        return {**base, "plain_line": _pair(code), "plain_line_source": "code",
                "plain_line_model": None}, False
    text = free_text(row)
    if not text:
        line, src = _deterministic(row)
        return {**base, "plain_line": line, "plain_line_source": src,
                "plain_line_model": None}, False

    # Asked before -- this row, or another row of the same record: reuse.
    asked = row if isinstance(row.get("plain_line_check"), dict) else prior
    if asked and isinstance(asked.get("plain_line_check"), dict):
        keep = {k: asked.get(k) for k in ("plain_line_check", "plain_line_model", "plain_line_llm_raw")}
        if asked.get("plain_line_source") == "llm" and isinstance(asked.get("plain_line"), dict):
            return {**base, **keep, "plain_line": asked["plain_line"],
                    "plain_line_source": "llm",
                    "plain_line_generated_at": asked.get("plain_line_generated_at") or now}, False
        line, src = _deterministic(row)
        return {**base, **keep, "plain_line": line, "plain_line_source": src}, False

    if llm is None:
        return None, False
    tries = int(row.get("plain_line_llm_tries") or 0)
    try:
        reply = await llm(build_prompt(row, text), row)
        if reply is None:
            raise RuntimeError("no reply")
    except Exception as e:
        tries += 1
        if tries < MAX_TRIES:
            return {"plain_line_llm_tries": tries}, True
        line, src = _deterministic(row)
        return {**base, "plain_line": line, "plain_line_source": src,
                "plain_line_model": model or None, "plain_line_llm_tries": tries,
                "plain_line_check": {"ok": False,
                                     "reason": f"model call failed {tries} times ({type(e).__name__})"}}, True
    pair = parse_reply(reply)
    ok, why = check_pair(pair, text)
    attempt = {"plain_line_model": model or None,
               "plain_line_check": {"ok": ok, "reason": why},
               "plain_line_llm_raw": pair if pair else str(reply)[:300]}
    if ok:
        return {**base, **attempt, "plain_line": pair, "plain_line_source": "llm"}, True
    line, src = _deterministic(row)
    return {**base, **attempt, "plain_line": line, "plain_line_source": src}, True


async def _prior(db, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Another row of the same record whose answer is already stored."""
    try:
        return await db.dob_logs.find_one({
            "project_id": row.get("project_id"), "raw_dob_id": row.get("raw_dob_id"),
            "_id": {"$ne": row.get("_id")}, "plain_line_check": {"$exists": True},
        })
    except Exception:
        return None


async def sweep(db, *, project_ids: Iterable[str], llm: Optional[LLM], model: str = "",
                budget: int = SWEEP_LLM_BUDGET, batch: int = SWEEP_BATCH,
                now: Optional[datetime] = None) -> Dict[str, int]:
    """Decide and store the line of every undecided complaint / violation / SWO
    row of `project_ids`. At most `budget` model calls. Never raises."""
    report = {"rows": 0, "code": 0, "llm": 0, "fallback": 0, "refused": 0,
              "waiting": 0, "calls": 0, "failed": 0}
    ids = [str(p) for p in project_ids or [] if p]
    if not ids:
        return report
    try:
        rows = await db.dob_logs.find({
            "project_id": {"$in": ids},
            "record_type": {"$in": list(RECORD_TYPES)},
            "is_deleted": {"$ne": True},
            "plain_line_version": {"$ne": PLAIN_LINE_VERSION},
        }).limit(batch).to_list(batch)
    except Exception:
        return report
    for row in rows:
        report["rows"] += 1
        if not ready(row):
            report["waiting"] += 1
            continue
        try:
            prior = await _prior(db, row) if needs_model(row) else None
            fields, called = await plan_line(
                row, llm=llm if report["calls"] < budget else None,
                model=model, now=now, prior=prior)
            if called:
                report["calls"] += 1
            if not fields:
                report["waiting"] += 1
                continue
            await db.dob_logs.update_one({"_id": row["_id"]}, {"$set": fields})
            src = fields.get("plain_line_source")
            if src in SOURCES:
                report[src] += 1
                chk = fields.get("plain_line_check")
                if called and isinstance(chk, dict) and not chk.get("ok"):
                    report["refused"] += 1
            else:
                report["failed"] += 1
        except Exception:
            report["failed"] += 1
    return report


def line_for_read(row: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
    """(line, source) to serve. The stored line; for a row the sweep has not
    reached, the deterministic one. Never asks the model."""
    stored = row.get("plain_line")
    src = row.get("plain_line_source")
    if (isinstance(stored, dict) and isinstance(stored.get("en"), str)
            and isinstance(stored.get("es"), str) and src in SOURCES):
        return {"en": stored["en"], "es": stored["es"]}, src
    code = code_label(row)
    if code and not code.get("broad"):
        return _pair(code), "code"
    return _deterministic(row)


def card_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """What a Compliance card reads, for a complaint / violation / SWO row."""
    if str(row.get("record_type") or "") not in RECORD_TYPES:
        return {}
    line, src = line_for_read(row)
    return {"plain_line": line, "plain_line_source": src, "dob_text": dob_text(row)}
