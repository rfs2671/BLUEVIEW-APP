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
    """Comments out, CODE AND STRINGS LEFT INTACT — by scanning, not by regex.

    ── WHY THIS IS NOT THREE re.sub CALLS ANY MORE ─────────────────────────

    It was, and the block pattern was `/\\*[\\s\\S]*?\\*/` applied FIRST. So a
    LINE comment that happened to contain the two characters `/*` opened a
    block comment that ran to the next `*/` anywhere in the file. A real
    occurrence, in CpNav.js:

        // Its active rule is "any /logbooks/*", which now includes ...

    swallowed thirty lines of live JSX — the whole nav item map — and handed
    the caller source with the code silently missing.

    THAT IS THIS MODULE'S OWN TRAP, INVERTED AND WORSE. The docstring above
    describes an assertion matching DOCUMENTATION instead of code. This
    deleted the code and left the documentation, so:

        assertIn(...)     fails loudly, and is how it was found
        assertNotIn(...)  PASSES, VACUOUSLY, and says nothing

    There are 617 assertNotIn assertions across 20 files reading through this
    helper. Any one of them covering a region a stray `/*` had blanked was
    asserting nothing at all, and would keep passing while the banned code sat
    right there.

    A REGEX CANNOT DO THIS JOB. Whether `/*` opens a comment depends on
    whether you are already inside a string, a template literal, a line
    comment or a regex literal — that is state, and state is what a scanner
    has. So this walks the source once, tracking exactly that, and replaces
    each comment with a newline-preserving blank so line numbers still line up
    for anyone reading a failure message.
    """
    out = []
    i, n = 0, len(src)
    # The last significant character, used to tell a REGEX LITERAL from a
    # division. `/` after a value divides; `/` after an operator or an opening
    # bracket starts a regex. Getting this wrong matters: a regex containing
    # `//` inside a character class would otherwise blank the rest of the line.
    prev = ""
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            block = src[i:(n if j < 0 else j + 2)]
            # Keep the newlines so line numbers survive.
            out.append("\n" * block.count("\n"))
            i = n if j < 0 else j + 2
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == "\\":
                    if i + 1 < n:
                        out.append(src[i + 1])
                        i += 2
                        continue
                if ch == quote:
                    i += 1
                    break
                i += 1
            prev = quote
            continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%~^<>"):
            # A regex literal. Copied verbatim; its contents are not comments.
            out.append(c)
            i += 1
            in_class = False
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == "\\":
                    if i + 1 < n:
                        out.append(src[i + 1])
                        i += 2
                        continue
                elif ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    i += 1
                    break
                elif ch == "\n":
                    # Not a regex after all (they cannot span lines). Bail out
                    # rather than consuming the rest of the file.
                    i += 1
                    break
                i += 1
            prev = "/"
            continue

        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


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
