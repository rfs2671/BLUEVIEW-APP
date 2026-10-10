"""English, Spanish and Yiddish, in pure code.

Crews write and speak English, Spanish and Yiddish -- Yiddish in Hebrew
script AND transliterated ("Yinglish"), often switching inside one message
("the pour is morgn 7am", "el inspector viene Tuesday"). Every reader in the
WhatsApp engines (attention, state changes, Upcoming, memory, chase) is code
written for English words. This module is the one place that knows the other
two:

  normalize_when(text)   Spanish / Yiddish day and time words -> the English
                         words the date resolvers already read ("el próximo
                         martes" -> "next tuesday", "en 3 semanas" -> "in 3
                         weeks", "מארגן" -> "tomorrow"). The resolvers then
                         apply their own never-guess rules unchanged, so a
                         Spanish "next Tuesday" is skipped exactly when an
                         English one is.
  detect(text)           "en" | "es" | "yi" | "mixed" -- a cheap guess from
                         the words and the script, for logs and routing.
  non_english(text)      True when the message is not plain English: the
                         English-only cheap filters must not drop it.
  DONE / SENT / ACTUALLY / NEVER_MIND / CANCEL / ACK / SARCASM
                         word lists for the state-change and short-ack
                         readers, per language.

Replies and reactions stay English. Nothing here translates a quote: a quote
is always kept verbatim, in the language it was said.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

# ── SCRIPT AND LANGUAGE ──────────────────────────────────────────────────────

_HEBREW = re.compile(r"[֐-׿יִ-ﭏ]")

# Common function words. Not a dictionary: enough to tell a Spanish or a
# transliterated Yiddish line from English. Accents are stripped first.
_ES_WORDS = {
    "el", "la", "los", "las", "de", "del", "que", "en", "y", "por", "para", "con",
    "es", "esta", "estan", "esto", "eso", "hoy", "manana", "lunes", "martes",
    "miercoles", "jueves", "viernes", "sabado", "domingo", "semana", "semanas",
    "dia", "dias", "viene", "vienen", "listo", "lista", "ya", "hecho", "terminado",
    "terminamos", "mande", "mandamos", "enviado", "cancelado", "cancelada", "no",
    "si", "pero", "tambien", "ahora", "luego", "despues", "proximo", "proxima",
    "tarde", "noche", "inspeccion", "entrega", "colado", "vaciado", "concreto",
    "hormigon", "grua", "piso", "dale", "vale", "bueno", "gracias", "mañana",
}
_YI_WORDS = {
    "haynt", "haint", "morgn", "ibermorgn", "ibermorgen", "zuntik", "zontik",
    "montik", "dinstik", "mitvokh", "mitvoch", "mitwoch", "donershtik", "donerstik",
    "fraytik", "freitik", "shabes", "shabbos", "iz", "nisht", "nit", "gut", "zicher",
    "zikher", "yo", "avade", "shoyn", "kumt", "kumen", "vokh", "vokhn", "vochn",
    "teg", "nekhstn", "nechstn", "nekhste", "kumendikn", "gemakht", "geshikt",
    "fartik", "oysgemakht", "bashtelt", "abgeshtelt", "der", "di", "dos", "un",
    "mit", "far", "oyf", "af", "zayn", "veln", "vet", "ikh", "ich", "mir", "er",
}
# Words both lists share with English, or too short to count alone.
_AMBIGUOUS = {"no", "yo", "di", "der", "er", "mir", "far", "un", "mit", "en", "y",
              "el", "la", "de", "es", "si", "dia", "gut"}


def fold(text: str) -> str:
    """Lowercase, accents stripped ("mañana" -> "manana"), curly quotes
    straightened. Hebrew letters are kept (their points dropped)."""
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.replace("’", "'").replace("‘", "'")


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z']+", fold(text))


def detect(text: str) -> str:
    """"en" | "es" | "yi" | "mixed". Hebrew script is Yiddish (crews do not
    write Hebrew). Otherwise counted from distinctive words; one distinctive
    word among English is "mixed"."""
    t = str(text or "")
    words = _words(t)
    es = sum(1 for w in words if w in _ES_WORDS and w not in _AMBIGUOUS)
    yi = sum(1 for w in words if w in _YI_WORDS and w not in _AMBIGUOUS)
    if "ñ" in t.lower() or "¿" in t or "¡" in t:
        es += 1
    if _HEBREW.search(t):
        yi += 2
    if not es and not yi:
        return "en"
    other = max(es, yi)
    lang = "es" if es >= yi else "yi"
    english = len(words) - es - yi
    if english >= 3 and english > 2 * other:
        return "mixed"
    return lang


def non_english(text: str) -> bool:
    return detect(text) != "en"


# ── DAYS AND TIMES ───────────────────────────────────────────────────────────
#
# Each rule rewrites the other language's words into the English the
# resolvers read. Order matters: longer phrases first ("pasado mañana" before
# "mañana", "ibermorgn" before "morgn"), and a "mañana" that means MORNING
# ("por la mañana", "10 de la mañana") is read as a time of day, never as
# tomorrow.

_ES_WD = {"lunes": "monday", "martes": "tuesday", "miercoles": "wednesday",
          "jueves": "thursday", "viernes": "friday", "sabado": "saturday",
          "domingo": "sunday"}
_ES_MON = {"enero": "jan", "febrero": "feb", "marzo": "mar", "abril": "apr",
           "mayo": "may", "junio": "jun", "julio": "jul", "agosto": "aug",
           "septiembre": "sep", "setiembre": "sep", "octubre": "oct",
           "noviembre": "nov", "diciembre": "dec"}
_ES_NUM = {"un": "1", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
           "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
           "diez": "10", "quince": "15"}
_YI_WD = {"zuntik": "sunday", "zontik": "sunday", "montik": "monday",
          "dinstik": "tuesday", "mitvokh": "wednesday", "mitvoch": "wednesday",
          "mitwoch": "wednesday", "donershtik": "thursday", "donerstik": "thursday",
          "fraytik": "friday", "freitik": "friday", "fraitik": "friday",
          "shabes": "saturday", "shabbos": "saturday", "shabbes": "saturday",
          "shabbat": "saturday"}
_YI_NUM = {"eyn": "1", "ein": "1", "tsvey": "2", "tzvei": "2", "dray": "3", "drei": "3",
           "fir": "4", "finf": "5", "zeks": "6", "zibn": "7"}
# Hebrew-script Yiddish, as written (no vowel points: fold() drops them).
_HE = [
    ("איבערמארגן", "day after tomorrow"),
    ("היינט", "today"),
    ("מארגן", "tomorrow"),
    ("זונטיק", "sunday"), ("מאנטיק", "monday"), ("דינסטיק", "tuesday"),
    ("מיטוואך", "wednesday"), ("דאנערשטיק", "thursday"), ("פרייטיק", "friday"),
    ("שבת", "saturday"), ("שבּת", "saturday"),
    ("נעקסטן", "next"), ("קומענדיקן", "next"), ("וואכן", "weeks"), ("וואך", "week"),
    ("טעג", "days"), ("אין", "in"),
]

_ES_RULES = [
    # Times of day first: "mañana" here is MORNING, not tomorrow.
    (r"\b(\d{1,2})(?::(\d{2}))?\s+de\s+la\s+manana\b",
     lambda m: f"{m.group(1)}{':' + m.group(2) if m.group(2) else ''}am"),
    (r"\b(\d{1,2})(?::(\d{2}))?\s+de\s+la\s+(?:tarde|noche)\b",
     lambda m: f"{m.group(1)}{':' + m.group(2) if m.group(2) else ''}pm"),
    (r"\b(?:por|en|de)\s+la\s+manana\b", " morning "),
    (r"\b(?:por|en|de)\s+la\s+(?:tarde|noche)\b", " afternoon "),
    (r"\ba\s+las?\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))", r"at \1"),
    (r"\bmediodia\b", "noon"),
    # Days.
    (r"\bpasado\s+manana\b", "day after tomorrow"),
    (r"\bmanana\b", "tomorrow"),
    (r"\bhoy\b", "today"),
    (r"\besta\s+(?:noche|tarde)\b", "tonight"),
    (r"\b(?:la\s+)?(?:proxima\s+semana|semana\s+que\s+viene)\b", "next week"),
    (r"\b(?:el\s+)?(?:proximo|proxima)\s+(" + "|".join(_ES_WD) + r")\b",
     lambda m: "next " + _ES_WD[m.group(1)]),
    (r"\b(?:el\s+)?(" + "|".join(_ES_WD) + r")\s+(?:proximo|que\s+viene)\b",
     lambda m: "next " + _ES_WD[m.group(1)]),
    (r"\beste\s+(" + "|".join(_ES_WD) + r")\b", lambda m: "this " + _ES_WD[m.group(1)]),
    (r"\b(?:el\s+)?(" + "|".join(_ES_WD) + r")\b", lambda m: _ES_WD[m.group(1)]),
    (r"\ben\s+(\d{1,2}|" + "|".join(_ES_NUM) + r")\s+(dia|semana)s?\b",
     lambda m: f"in {_ES_NUM.get(m.group(1), m.group(1))} "
               f"{'day' if m.group(2) == 'dia' else 'week'}s"),
    (r"\ben\s+(?:unos|unas)\s+(?:dias|semanas)\b", "in a few days"),
    (r"\b(\d{1,2})\s+de\s+(" + "|".join(_ES_MON) + r")\b",
     lambda m: f"{_ES_MON[m.group(2)]} {m.group(1)}"),
    (r"\bpronto\b", "soon"),
    (r"\balgun\s+dia\b", "sometime"),
]

_YI_RULES = [
    (r"\bgut\s+morg[e]?n\b", " "),                       # "good morning"
    (r"\bmorg[e]?n\s+in\s+der\s+fri\b", "tomorrow morning"),
    (r"\biber\s*morg[e]?n\b", "day after tomorrow"),
    (r"\bmorg[e]?n\b", "tomorrow"),
    (r"\bha[iy]nt\b", "today"),
    (r"\b(?:nekhst[e]?n?|nechst[e]?n?|kumendik[e]?n?)\s+(" + "|".join(_YI_WD) + r")\b",
     lambda m: "next " + _YI_WD[m.group(1)]),
    (r"\b(" + "|".join(_YI_WD) + r")\b", lambda m: _YI_WD[m.group(1)]),
    (r"\bin\s+(\d{1,2}|" + "|".join(_YI_NUM) + r")\s+(vokh[e]?n?|voch[e]?n?|woch[e]?n?|teg)\b",
     lambda m: f"in {_YI_NUM.get(m.group(1), m.group(1))} "
               f"{'days' if m.group(2) == 'teg' else 'weeks'}"),
    (r"\b(?:nekhst|nechst|kumendik)\w*\s+vokh\b", "next week"),
]
# A whole Hebrew-script word only: "אין" (in) is not the inside of another word.
_HE_COMPILED = [(re.compile(r"(?<![\u0590-\u05FF])" + re.escape(he) + r"(?![\u0590-\u05FF])"), en)
                for he, en in _HE]
_ES_COMPILED = [(re.compile(p), r) for p, r in _ES_RULES]
_YI_COMPILED = [(re.compile(p), r) for p, r in _YI_RULES]


def normalize_when(text: str) -> str:
    """Spanish / Yiddish day and time words -> English ones; English words
    and everything else left as they are. Lowercased and accent-free."""
    t = fold(text)
    for rx, en in _HE_COMPILED:
        t = rx.sub(f" {en} ", t)
    for rx, rep in _ES_COMPILED + _YI_COMPILED:
        t = rx.sub(rep, t)
    return " ".join(t.split())


# ── STATE-CHANGE AND ACK WORDS ───────────────────────────────────────────────
#
# Regex alternations, accent-free and lowercase (match against fold(text)).
# English stays in the readers that already had it; these are the Spanish and
# Yiddish additions they OR in.

DONE = {
    "es": r"listo|lista|ya (?:esta|quedo|termine|terminamos|lo hice)|hecho|terminad[oa]s?"
          r"|termine|terminamos|completad[oa]|ya se (?:hizo|instalo|puso)|quedo listo",
    "yi": r"fartik|oysgemakht|gemakht|shoyn (?:fartik|gemakht|ongeshikt)"
          r"|פארטיק|געמאכט|אויסגעמאכט",
}
SENT = {
    "es": r"(?:ya )?(?:lo |la |los |las )?(?:mande|mandamos|envie|enviamos|enviado|enviada|mandado)",
    "yi": r"geshikt|ongeshikt|avekgeshikt|געשיקט",
}
ACTUALLY = {
    "es": r"en realidad|mejor (?:el|la)|cambio de planes|ahora es",
    "yi": r"eygntlekh|faktish|bashtelt iber",
}
NEVER_MIND = {
    "es": r"olvidalo|olvida(?:lo)? eso|no importa|ya no (?:hace falta|se necesita)|dejalo",
    "yi": r"farges es|nisht neytik|shoyn nisht|lozt es",
}
CANCEL = {
    "es": r"cancelad[oa]s?|se cancelo|suspendid[oa]|no va|ya no va|no hay (?:colado|vaciado|entrega|inspeccion)",
    "yi": r"abgeshtelt|opgeshtelt|batlt|keyn (?:pour|delivery|inspection)",
}
# Short acks: a plain yes, nothing else in the message.
ACK = {
    "es": r"si|sí|ok|okey|dale|vale|ya|claro|listo|de una|perfecto|bueno|va",
    "yi": r"yo|gut|zicher|zikher|avade|shoyn|takeh|יא|גוט|זיכער|אוודאי",
}
# The yes is not a yes ("ya ya", "jaja ok"; emoji are in the readers).
SARCASM = {
    # Only the clear ones: "sí claro" and "cómo no" are a sincere "of course".
    "es": r"\bja(?:ja)+\b|\bje(?:je)+\b|\bya ya\b",
    "yi": r"\bnu nu\b|\bzicher zicher\b|\bvi den\b",
}


def alternation(table: dict) -> str:
    """All languages' alternatives in one group, for a reader to OR in."""
    return "|".join(f"(?:{v})" for v in table.values())
