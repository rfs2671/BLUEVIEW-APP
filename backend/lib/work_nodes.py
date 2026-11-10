"""Site, structure and envelope work: the kinds of work graph_v1 does not cover.

app/scheduling/graph_v1.py is the operator-approved INTERIOR sequence (framing
through trim). A job is also demolished, dug, founded, framed in concrete or
steel, roofed and closed in, and the records name that work: "Excavation",
"Stucco", a DOB Letter of Completion for the foundation filing. These nodes give
that work a name so evidence about it is not thrown away as unmatched.

THIS IS DATA, NOT AN APPROVED SEQUENCE. graph_v1's approved content is not
touched and none of these nodes enters it. `SEQUENCE` below holds only the
order nobody disputes (a building is demolished before it is dug, dug before
it is founded, founded before its frame goes up), and every edge says
"template, unapproved". Nothing here may be reported as this job's logic or
used to name a cause.

WHOLE WORDS ONLY. "Blocking" is framing (graph_v1's), not masonry; "Roof MEP"
is MEP on the roof, not roofing; "Vapour barrier" is insulation. "Outer bldg"
names a PLACE, not a kind of work, so it classifies as nothing. A phrase that
names no work here is nothing, never a guess.

Pure: no database, no network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

TEMPLATE_UNAPPROVED = "template, unapproved"

#: id -> {label, per_level, progress}. `per_level`: the work happens level by
#: level (a slab, a facade, a window line); otherwise it is about the whole
#: site or building. `progress`: False for work that protects the site and is
#: not construction progress (a construction fence, a sidewalk shed).
NODES: Dict[str, Dict[str, Any]] = {
    "demolition": {"label": "demolition", "per_level": False, "progress": True},
    "excavation_soe": {"label": "excavation and support of excavation", "per_level": False, "progress": True},
    "foundation": {"label": "foundation", "per_level": False, "progress": True},
    "superstructure": {"label": "superstructure (structural frame and slabs)", "per_level": True, "progress": True},
    "roofing": {"label": "roofing", "per_level": False, "progress": True},
    "facade_envelope": {"label": "facade / envelope", "per_level": True, "progress": True},
    "windows": {"label": "windows", "per_level": True, "progress": True},
    "elevator": {"label": "elevator", "per_level": False, "progress": True},
    "site_utilities": {"label": "site utilities", "per_level": False, "progress": True},
    # A DOB work type of its own (the standpipe filing); graph_v1 has only its
    # life-safety GATE (gate_ls_standpipe), not the installation.
    "standpipe": {"label": "standpipe", "per_level": True, "progress": True},
    "site_protection": {"label": "site protection (construction fence, sidewalk shed)", "per_level": False,
                        "progress": False},
}

#: First match wins, per phrase. Ordered so the most specific words are read
#: first and site protection last (a photo of a frame "with a sidewalk shed
#: along the street" is a photo of the frame).
_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("demolition", re.compile(r"\bdemo(?:lition|lish\w*)?\b|\babatement\b", re.I)),
    ("excavation_soe", re.compile(
        r"\bexcavat\w*\b|\bsoe\b|\bsupport\s+of\s+excavation\b|\bearth\s?work\b|\bbackfill\w*\b"
        r"|\bunderpinning\b|\blagging\b|\bsoldier\s+piles?\b|\btie[\s-]?backs?\b|\bsheet\s+piles?\b", re.I)),
    ("foundation", re.compile(
        r"\bfoundations?\b|\bfootings?\b|\bpile\s+caps?\b|\bgrade\s+beams?\b|\bmat\s+slab\b"
        r"|\bslab\s+on\s+grade\b|\bsog\b|\bcaissons?\b", re.I)),
    ("roofing", re.compile(
        r"\broofing\b|\broof\s+membrane\b|\bepdm\b|\btpo\b|\bbuilt[\s-]?up\s+roof\b|\bmodified\s+bitumen\b", re.I)),
    ("windows", re.compile(r"\bwindows?\b|\bstorefronts?\b|\bcurtain\s?walls?\b|\bglazing\b", re.I)),
    ("facade_envelope", re.compile(
        r"\bstucco\b|\bfa[cç]ades?\b|\beifs\b|\bsiding\b|\bcladding\b|\bbrick\s?(?:work|veneer|face)?\b"
        r"|\bair\s+barrier\b|\bexterior\s+(?:walls?|sheathing|finish\w*)\b|\bparapets?\b|\bcoping\b", re.I)),
    ("superstructure", re.compile(
        r"\bsuperstructure\b|\bstructural\s+(?:steel|frame|concrete)\b|\bsteel\s+erect\w*\b|\bformwork\b"
        r"|\brebar\b|\b(?:metal|concrete)\s+decks?\b|\bslabs?\b|\bdeck\s+pour\b|\bconcrete\s+(?:frame|columns?|walls?)\b"
        r"|\bplanks?\b|\bshear\s+walls?\b|\bcolumns?\b", re.I)),
    ("elevator", re.compile(r"\belevators?\b|\bhoistway\b", re.I)),
    ("standpipe", re.compile(r"\bstand[\s-]?pipes?\b", re.I)),
    ("site_utilities", re.compile(
        r"\bsite\s+utilit\w*\b|\bwater\s+main\b|\bwater\s+service\b|\bsewer\s+(?:connection|line|tap|main)s?\b"
        r"|\bstorm\s+(?:drain|sewer|line)s?\b|\butility\s+(?:connection|trench\w*)\b|\bdrywells?\b"
        r"|\bcatch\s+basins?\b", re.I)),
    ("site_protection", re.compile(
        r"\bconstruction\s+fence\b|\bfenc(?:e|es|ing)\b|\bsidewalk\s+sheds?\b|\bscaffold\w*\b", re.I)),
)

#: The only order these nodes are given. Each edge is (before, after, status).
SEQUENCE: Tuple[Tuple[str, str, str], ...] = (
    ("demolition", "excavation_soe", TEMPLATE_UNAPPROVED),
    ("excavation_soe", "foundation", TEMPLATE_UNAPPROVED),
    ("foundation", "superstructure", TEMPLATE_UNAPPROVED),
)


def classify(phrase: Any) -> Tuple[List[str], bool]:
    """(node ids, generic) in work_state.classify's shape. Never generic: a
    phrase here names the work or names nothing."""
    t = str(phrase or "")
    for node, rx in _RULES:
        if rx.search(t):
            return [node], False
    return [], False


def label(node: str) -> str:
    return NODES[node]["label"] if node in NODES else node.replace("_", " ")


def is_progress(node: str) -> bool:
    """False only for a node known here to be site protection."""
    return bool(NODES.get(node, {"progress": True})["progress"])
