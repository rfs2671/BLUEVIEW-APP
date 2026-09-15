#!/usr/bin/env python3
"""WHERE ELSE AN EXCEPTION IS RECORDED BY str() ALONE.

`str(httpx.ReadTimeout())` is the empty string. On 2026-09-11 that fact turned
a four-day registration outage into the log line

    OSHA OCR error:

and the worker's message `OCR processing failed: `. Neither named the type,
neither named the model, and nobody could see what was wrong.

THE LIST IS DERIVED, NOT PASTED. A census written into a PR body is wrong the
day after it is written, and a hand-maintained list of exemptions is a check
with an expiry date nobody set. This is the script that produced the number in
that PR; run it to get today's.

    cd backend
    python scripts/audit_exception_logging.py server.py
    python scripts/audit_exception_logging.py server.py lib/*.py --routed-only

WHAT COUNTS AS A HIT. A `logger.<level>(...)` call, inside an `except X as e:`
handler, whose only record of `e` is `str(e)` or `{e}` — no `!r`, no `%r`, no
`exc_info=`, and not `logger.exception`. Those four are the ways the TYPE
survives an empty message, which is the whole property that was missing.

WHAT IT CANNOT SEE, and this matters when reading the number: a handler that
logs NOTHING AT ALL and only re-raises `detail=f"...{str(e)}"`. Two of those
sat on the gate path — `GET /checkin/{project_id}/{tag_id}/info` and
`POST /checkin/submit` — and they are strictly worse than a hit here, because
there is no log line to be empty. `--silent` lists those instead.
"""
from __future__ import annotations

import argparse
import ast
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}


def _carries_as_str(node: ast.AST, name: str) -> bool:
    """True when `node` interpolates `e` or `str(e)` — i.e. %s-shaped."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.FormattedValue):
            v = sub.value
            # {e} with no !r conversion (114 is 'r')
            if isinstance(v, ast.Name) and v.id == name and sub.conversion != 114:
                return True
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == "str" and len(sub.args) == 1
                and isinstance(sub.args[0], ast.Name) and sub.args[0].id == name):
            return True
    return False


def _has_repr(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.FormattedValue) and sub.conversion == 114:
            return True
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == "repr"):
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "%r" in sub.value:
            return True
    return False


def _owners(tree: ast.AST):
    """line -> (function name, "METHOD /path" or "")."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = ""
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.args and isinstance(d.args[0], ast.Constant)):
                route = f"{d.func.attr.upper()} {d.args[0].value}"
        for ln in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
            prev = out.get(ln)
            if prev is None or prev[2] <= node.lineno:
                out[ln] = (node.name, route, node.lineno)
    return out


def census(path: str):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()
    owner = _owners(tree)
    hits, silent = [], []

    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name:
            continue
        name = handler.name
        logged = False
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"):
                continue
            logged = True
            if node.func.attr not in LOG_LEVELS:        # .exception carries a traceback
                continue
            if not any(_carries_as_str(a, name) for a in node.args):
                continue
            if any(k.arg == "exc_info" for k in node.keywords) or _has_repr(node):
                continue
            fn, route, _ = owner.get(node.lineno, ("<module>", "", 0))
            hits.append((node.lineno, node.func.attr, fn, route,
                         lines[node.lineno - 1].strip()[:110]))

        if not logged and _carries_as_str(handler, name):
            fn, route, _ = owner.get(handler.lineno, ("<module>", "", 0))
            silent.append((handler.lineno, "NO LOG", fn, route,
                           lines[handler.lineno].strip()[:110]))

    return sorted(hits), sorted(silent)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--routed-only", action="store_true",
                    help="only handlers inside an HTTP route")
    ap.add_argument("--silent", action="store_true",
                    help="list handlers that log NOTHING and re-raise str(e)")
    args = ap.parse_args()

    total = 0
    for path in args.paths:
        hits, silent = census(path)
        rows = silent if args.silent else hits
        if args.routed_only:
            rows = [r for r in rows if r[3]]
        total += len(rows)
        print(f"# {path}: {len(rows)}")
        for ln, level, fn, route, text in rows:
            print(f"{path}:{ln}\t{level}\t{fn}\t{route or '-'}\t{text}")
    print(f"# TOTAL: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
