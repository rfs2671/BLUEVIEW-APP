"""Read source for a text assertion — with the prose already gone.

THE TRAP THIS CLOSES. A test asserts that some pattern is absent from a file:

    self.assertNotIn("db.logbooks", SRC)

and passes — because the module's own docstring says "nothing here writes to
db.logbooks". The assertion matched the DOCUMENTATION of the rule instead of
the code, and the rule itself was never checked.

It has happened four times on this project, and twice AFTER it was written up
and circulated. Vigilance demonstrably does not work on it, so the fix is
mechanical: this helper is the way tests read source, and it strips comments
and docstrings by default. A test cannot opt into the broken shape by
forgetting — it has to ask for `raw=True` and say why.

    from tests.source_text import code_of

    SRC = code_of("server.py")                 # comments and docstrings gone
    RAW = code_of("server.py", raw=True)       # everything, when that is the point

WHEN raw=True IS CORRECT. Asserting that a comment EXISTS — the provenance
notes this codebase leans on ("a dead duplicate of the answers question"), or
that a removal procedure is still documented. Those are assertions about the
prose, so the prose must be there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

_BACKEND = Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"

# Triple-quoted strings, single or double. Non-greedy, DOTALL. This removes
# every triple-quoted literal, not only docstrings — a module-level SQL blob
# or prompt template goes too, which is the conservative direction: a test
# asserting on a prompt's contents should pass raw=True and say so.
_TRIPLE = re.compile(r'("""|\'\'\')[\s\S]*?\1')
_PY_COMMENT = re.compile(r"(?m)^\s*#.*$")
_PY_TRAILING = re.compile(r"(?m)\s#[^\n'\"]*$")
_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"(?m)^\s*//.*$")
_TRAILING = re.compile(r"(?m)\s//[^\n'\"`]*$")


def strip_python(src: str) -> str:
    """Docstrings and # comments out; code and ordinary strings left alone."""
    src = _TRIPLE.sub("", src)
    src = _PY_COMMENT.sub("", src)
    return _PY_TRAILING.sub("", src)


def strip_js(src: str) -> str:
    """/* */ and // comments out."""
    src = _BLOCK.sub("", src)
    src = _LINE.sub("", src)
    return _TRAILING.sub("", src)


def strip_css(src: str) -> str:
    """/* */ only — CSS has no line comment."""
    return _BLOCK.sub("", src)


def code_of(relative_path: Union[str, Path], *, raw: bool = False) -> str:
    """The source of a repo file, comments and docstrings removed.

    `relative_path` is resolved against backend/ first, then the repo root, so
    both "server.py" and "frontend/app/logbooks/daily_jobsite.jsx" work.

    Pass raw=True ONLY when the assertion is genuinely about the prose — that
    a provenance note still exists, say. Everywhere else the default is what
    keeps an absence test honest.
    """
    p = Path(relative_path)
    for base in (_BACKEND, _BACKEND.parent):
        candidate = base / p
        if candidate.exists():
            src = candidate.read_text(encoding="utf-8")
            break
    else:
        raise FileNotFoundError(f"{relative_path} not found under backend/ or repo root")

    if raw:
        return src
    suffix = candidate.suffix.lower()
    if suffix == ".py":
        return strip_python(src)
    if suffix in (".js", ".jsx", ".cjs", ".ts", ".tsx"):
        return strip_js(src)
    if suffix == ".css":
        return strip_css(src)
    return src
