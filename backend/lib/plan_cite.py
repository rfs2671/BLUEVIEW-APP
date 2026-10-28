"""STRUCTURED CITATIONS: the model cites a plan record only as a token,
[src:N], and never types a file name or a set label.

WHY. #892 showed the model each record's file and drawing set, and the
model copied them into its answer. The gate then read their digits ("588",
"7.2", a label's date) as figures (#910 fixed that by removing the names as
text, with the rules it needs so no scope is lost). A token cannot carry a
figure or a scope: it is a pointer. So the evidence line names a record by
its token, the answer cites by token, the gate checks the answer with every
token taken out, and only after the gate is each token turned into what a
reader can act on: "(A-302 · 588 Boyland Arch 7.2.pdf, owner's set)".

THE REGISTRY is one per turn (server._answer_turn_begin): the same record
keeps its number across every search in the turn, so a token the model
read two tool calls ago still points at it. A token that names no record
of the turn is dropped when rendered - never shown as "[src:9]".

Pure: no database, no network. plan_sources does the naming.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from lib import plan_sources

#: A token as the model writes it: "[src:3]", "[ src : 3 ]", "[SRC:3]".
TOKEN_RE = re.compile(r"\[\s*src\s*:\s*(\d{1,4})\s*\]", re.I)
#: One or more tokens in a row ("[src:1][src:2]", "[src:1], [src:2]"), with
#: the spaces before them: the run is replaced whole, nothing around it.
_TOK = r"\[\s*src\s*:\s*\d{1,4}\s*\]"
_RUN_RE = re.compile(r"[ \t]*" + _TOK + r"(?:[ \t]*[,;]?[ \t]*" + _TOK + r")*", re.I)


def token(n: int) -> str:
    return f"[src:{int(n)}]"


def _key(r: Dict[str, Any]) -> tuple:
    rid = r.get("_id") or r.get("id")
    if rid:
        return ("id", str(rid))
    return ("at", str(r.get("page_id") or ""), str(r.get("sheet_number") or ""),
            str(r.get("record_type") or ""), str(r.get("quote") or "")[:200])


class Cites:
    """The turn's tokens: record -> N (from 1), and N -> record."""

    def __init__(self) -> None:
        self._n: Dict[tuple, int] = {}
        self._records: List[Dict[str, Any]] = []

    def token_for(self, r: Dict[str, Any]) -> str:
        k = _key(r)
        if k not in self._n:
            self._records.append(r)
            self._n[k] = len(self._records)
        return token(self._n[k])

    def record(self, n: int) -> Optional[Dict[str, Any]]:
        return self._records[n - 1] if 1 <= n <= len(self._records) else None

    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)


def strip_tokens(text: str) -> str:
    """`text` with every token taken out: what a check reads figures from.
    A token is a pointer, never a figure (its N must not vouch for a "3")."""
    return TOKEN_RE.sub(" ", text or "")


def display(where: str, src: Optional[Dict[str, Any]]) -> str:
    """What a token becomes: "A-302 · 588 Boyland Arch 7.2.pdf, owner's set"
    (the sheet or page, its file, its set); the citation alone without a
    source."""
    if not where:
        return ""
    if not src:
        return where
    out = where
    if src.get("file_name"):
        out += f" · {src['file_name']}"
    if src.get("set_name"):
        out += f", {src['set_name']}"
    return out


def render(text: str, cites: Optional[Cites], sources: Optional[Dict[str, dict]],
           where_of: Callable[[Dict[str, Any]], Optional[str]]) -> str:
    """Every run of tokens in `text` as one "(…; …)" of display names, in
    order and without repeats. A token no record of the turn holds is
    dropped. `where_of` is plan_search.cite; `sources` {file_id: source_of}."""
    if not text or not TOKEN_RE.search(text):
        return text or ""

    def one(n: int) -> str:
        r = cites.record(n) if cites is not None else None
        if not r:
            return ""
        src = (sources or {}).get(str(r.get("file_id") or ""))
        return display(where_of(r) or "", src)

    def run(m: "re.Match") -> str:
        names: List[str] = []
        for t in TOKEN_RE.finditer(m.group(0)):
            d = one(int(t.group(1)))
            if d and d not in names:
                names.append(d)
        return f" ({'; '.join(names)})" if names else ""

    return _RUN_RE.sub(run, text).strip()
