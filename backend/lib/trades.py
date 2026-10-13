"""A company's trades: the canonical labels, their synonyms, the closest ones.

The trade list is server.TRADE_VOCABULARY (the published labels, never
re-spelled) plus the trades a company added (`company_trades`). A trade said
in a DM ("they're the electricians", "sheetrock", "plomero") resolves to ONE
label on that list; an unknown one is offered the 3 closest -- or added as a
new trade. The synonyms here are why a known trade is never added twice.

Pure: no database, no server import.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Dict, Iterable, List, Optional

#: COLLECTION: the trades a company added beyond the vocabulary. One row per
#: (company_id, key); `label` is the trade as it was added, title-cased.
COLLECTION = "company_trades"

#: Said -> the canonical vocabulary label (server.TRADE_VOCABULARY). Words and
#: phrases, folded (lowercase, no accents). Plurals are tried without the "s".
SYNONYMS: Dict[str, str] = {
    # Electrical
    "electric": "Electrical", "electrical": "Electrical", "electrician": "Electrical",
    "electricista": "Electrical", "electricidad": "Electrical", "sparky": "Electrical",
    # Plumbing
    "plumber": "Plumbing", "plumbing": "Plumbing", "plomero": "Plumbing",
    "plomeria": "Plumbing", "pipes": "Plumbing",
    # Drywall
    "drywall": "Drywall", "sheetrock": "Drywall", "taper": "Drywall", "taping": "Drywall",
    "drywaller": "Drywall", "sheet rock": "Drywall", "gypsum": "Drywall", "board": "Drywall",
    # Painting
    "paint": "Painting", "painter": "Painting", "painting": "Painting", "pintor": "Painting",
    "pintura": "Painting",
    # HVAC / Mechanical
    "hvac": "HVAC / Mechanical", "mechanical": "HVAC / Mechanical", "mech": "HVAC / Mechanical",
    "ac": "HVAC / Mechanical", "a c": "HVAC / Mechanical", "heating": "HVAC / Mechanical",
    "ductwork": "HVAC / Mechanical", "sheet metal": "HVAC / Mechanical",
    # Sprinkler / Fire Protection
    "sprinkler": "Sprinkler", "sprinklers": "Sprinkler", "fire sprinkler": "Sprinkler",
    "fire protection": "Fire Protection", "fire alarm": "Fire Protection",
    # Framing (carpentry is ruled under Framing)
    "framing": "Framing", "framer": "Framing", "carpenter": "Framing", "carpentry": "Framing",
    "carpintero": "Framing", "carpinteria": "Framing", "wood framing": "Framing",
    # Concrete / Formwork
    "concrete": "Concrete", "cement": "Concrete", "concreto": "Concrete",
    "formwork": "Formwork", "forms": "Formwork", "foundation": "Formwork",
    # Masonry
    "masonry": "Masonry", "mason": "Masonry", "bricklayer": "Masonry", "brick": "Masonry",
    "block": "Masonry", "albanil": "Masonry",
    # Steel
    "steel": "Steel / Ironwork", "iron": "Steel / Ironwork", "ironwork": "Steel / Ironwork",
    "ironworker": "Steel / Ironwork", "welder": "Steel / Ironwork", "welding": "Steel / Ironwork",
    # Roofing / Waterproofing
    "roofing": "Roofing", "roofer": "Roofing", "roof": "Roofing", "techo": "Roofing",
    "waterproofing": "Waterproofing", "waterproof": "Waterproofing",
    # Glazing
    "glazing": "Glazing", "glazier": "Glazing", "glass": "Glazing", "windows": "Glazing",
    "window": "Glazing", "curtain wall": "Glazing",
    # Flooring
    "flooring": "Flooring", "floors": "Flooring", "floor": "Flooring", "pisos": "Flooring",
    # Others in the vocabulary
    "excavation": "Excavation", "excavator": "Excavation", "digging": "Excavation",
    "demolition": "Demolition", "demo": "Demolition",
    "abatement": "Abatement", "asbestos": "Abatement",
    "scaffolding": "Scaffolding", "scaffold": "Scaffolding", "scaffolder": "Scaffolding",
    "surveying": "Surveying", "surveyor": "Surveying", "survey": "Surveying",
    "elevator": "Elevator", "elevators": "Elevator", "elevador": "Elevator",
    "water main": "Water Main", "watermain": "Water Main",
    "safety": "Safety", "cleaning": "Cleaning", "cleaner": "Cleaning", "cleanup": "Cleaning",
    "limpieza": "Cleaning",
}

#: Trades that are not on the list but sit next to ones that are: offered
#: first among the closest ("tile" -> Flooring, Masonry).
RELATED: Dict[str, List[str]] = {
    "tile": ["Flooring", "Masonry", "Drywall"], "tiles": ["Flooring", "Masonry", "Drywall"],
    "carpet": ["Flooring", "Cleaning", "Painting"], "millwork": ["Framing", "Flooring", "Glazing"],
    "doors": ["Framing", "Glazing", "Steel / Ironwork"], "insulation": ["Drywall", "Waterproofing", "Roofing"],
    "stucco": ["Masonry", "Waterproofing", "Painting"], "low voltage": ["Electrical", "Fire Protection", "Safety"],
    "landscaping": ["Excavation", "Cleaning", "Surveying"], "fencing": ["Steel / Ironwork", "Safety", "Excavation"],
}

_FILLER = re.compile(
    r"^(?:they re|they are|theyre|hes|shes|he s|she s|as|is|are|son|es|como|"
    r"the|our|el|la|los|las|a|an)\s+")
_TAIL = re.compile(r"\s+(?:guys?|company|companies|sub|subs|contractor|contractors|trade|crew|work)$")


def fold(text: object) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9/ ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def said(raw: object) -> str:
    """The trade words of what was said: "they're the electricians" ->
    "electricians"."""
    t = fold(raw)
    for _ in range(3):
        t = _FILLER.sub("", t)
    return _TAIL.sub("", t).strip()


def _key(label: object) -> str:
    return str(label or "").strip().casefold()


def resolve(raw: object, known: Iterable[str]) -> Optional[str]:
    """The label on `known` (the company's trade list) that `raw` names --
    by the label itself, either half of a "HVAC / Mechanical" label, or a
    synonym -- else None (unknown: ask)."""
    t = said(raw)
    if not t:
        return None
    labels = list(known)
    by_key = {_key(lab): lab for lab in labels}
    for lab in labels:
        for part in [lab] + [p.strip() for p in lab.split("/")]:
            if fold(part) and fold(part) in (t, t.rstrip("s")):
                return lab
    for cand in (t, t.rstrip("s"), re.sub(r"(?:ers|er|s)$", "", t)):
        canon = SYNONYMS.get(cand)
        if canon and _key(canon) in by_key:
            return by_key[_key(canon)]
    for w in t.split():
        for cand in (w, w.rstrip("s")):
            canon = SYNONYMS.get(cand)
            if canon and _key(canon) in by_key:
                return by_key[_key(canon)]
    return None


def closest(raw: object, known: Iterable[str], n: int = 3) -> List[str]:
    """The `n` labels on `known` closest to what was said (by the labels and
    their synonyms), best first, each once."""
    t = said(raw)
    labels = list(known)
    by_key = {_key(lab): lab for lab in labels}
    related = [by_key[_key(r)] for r in RELATED.get(t, RELATED.get(t.rstrip("s"), []))
               if _key(r) in by_key]
    if related:
        rest = [lab for lab in closest_by_text(t, labels, by_key) if lab not in related]
        return (related + rest)[:n]
    return closest_by_text(t, labels, by_key)[:n]


def closest_by_text(t: str, labels: List[str], by_key: Dict[str, str]) -> List[str]:
    scored: Dict[str, float] = {}
    for lab in labels:
        for part in [lab] + [p.strip() for p in lab.split("/")]:
            r = difflib.SequenceMatcher(None, t, fold(part)).ratio()
            scored[lab] = max(scored.get(lab, 0.0), r)
    for word, canon in SYNONYMS.items():
        lab = by_key.get(_key(canon))
        if lab:
            r = difflib.SequenceMatcher(None, t, word).ratio()
            scored[lab] = max(scored.get(lab, 0.0), r)
    return [lab for lab, _ in sorted(scored.items(), key=lambda kv: (-kv[1], labels.index(kv[0])))]


def new_label(raw: object) -> str:
    """How a new trade is stored: its words, title-cased, at most 40 chars."""
    t = said(raw)
    return " ".join(w[:1].upper() + w[1:] for w in t.split())[:40]


_ADD = re.compile(r"^(?:yes\W*|yeah\W*|ok\W*|si\W*)?(?:please\s+)?(?:add(?:\s+(?:it|that|them|one))?"
                  r"(?:\s+as\s+(?:a\s+)?new(?:\s+trade)?)?|add\s+.+\s+as\s+(?:a\s+)?new(?:\s+trade)?|"
                  r"new trade|new one|create it|make it|agregalo|agregala|agregar|nuevo)\W*$")


def is_add(text: object) -> bool:
    """'add it', 'yes add', 'add Dance as a new trade', 'new trade'."""
    return bool(_ADD.match(fold(text)))
