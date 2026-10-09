#!/usr/bin/env python3
"""READ-ONLY: was the platform gate ever hit by a non-operator?

Counts the lines the retired `require_platform_operator` wrote, by role and
(where it can be told) by route. Prints counts only -- never an email, a user
id, an IP or a token.

The gate wrote one of two WARNING lines per refused (or, in shadow mode,
waved-through) request:

  [platform-gate SHADOW] would have blocked non-operator '<email>' (role='<role>'). ...
  [platform-gate] blocked non-operator '<email>'

Neither names the route. Uvicorn's access line for the same request follows
it, so the route is taken from the next access line for an operator path
within ROUTE_WINDOW_S seconds, and is reported as "(route unknown)" when there
is none. With concurrent traffic that pairing is approximate; the role counts
are exact.

USAGE (Railway CLI, logged in, linked to the backend service):

  railway logs --json --since 30d > /tmp/backend-30d.jsonl   # or plain text
  python backend/scripts/platform_gate_log_report.py /tmp/backend-30d.jsonl

Reads a file (or stdin with "-"). Accepts Railway's JSON lines
({"timestamp": ..., "message": ...}) or plain text lines.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Iterable, Iterator, Optional, Tuple

ROUTE_WINDOW_S = 5.0

SHADOW = re.compile(
    r"\[platform-gate SHADOW\] would have blocked non-operator .*?"
    r"\(role=(?P<role>'[^']*'|\"[^\"]*\"|None)\)")
ENFORCED = re.compile(r"\[platform-gate\] blocked non-operator ")
ACCESS = re.compile(
    r'"(?P<method>GET|POST|PUT|PATCH|DELETE) (?P<path>/api/[^ ?"]*)[^"]*" (?P<status>\d{3})')

# Paths the old gate stood in front of. Anything else is not paired.
OPERATOR_PATH = re.compile(
    r"^/api/(owner/|debug/|whatsapp/debug/|admin/(filing-jobs|notifications|"
    r"migrate-company-data)|projects/(pending-deletion|[^/]+/(dependencies|"
    r"hard-delete|debug/)))")

ID_SEGMENT = re.compile(r"/[0-9a-f]{24}(?=/|$)|/[0-9a-f]{32}(?=/|$)")


def _parse_line(raw: str) -> Tuple[Optional[datetime], str]:
    raw = raw.rstrip("\n")
    ts = None
    msg = raw
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            msg = str(obj.get("message") or "")
            ts = _ts(obj.get("timestamp"))
        except ValueError:
            pass
    if ts is None:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)", msg)
        if m:
            ts = _ts(m.group(1))
    return ts, msg


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


def _route(method: str, path: str) -> str:
    """The route with ids replaced, so no record id is printed."""
    return f"{method} {ID_SEGMENT.sub('/{id}', path)}"


def _role(token: str) -> str:
    t = token.strip("'\"")
    return t if t and t != "None" else "(none)"


def tally(lines: Iterable[str]) -> Counter:
    """Counter keyed by (mode, role, route). Pure; reads nothing else."""
    events = []   # (ts, mode, role)
    access = []   # (ts, route)
    for raw in lines:
        ts, msg = _parse_line(raw)
        m = SHADOW.search(msg)
        if m:
            events.append((ts, "shadow (would have denied)", _role(m.group("role"))))
            continue
        if ENFORCED.search(msg):
            events.append((ts, "enforced (denied)", "(not logged)"))
            continue
        a = ACCESS.search(msg)
        if a and OPERATOR_PATH.match(a.group("path")):
            access.append((ts, _route(a.group("method"), a.group("path"))))

    used = set()
    out: Counter = Counter()
    for ts, mode, role in events:
        route = "(route unknown)"
        if ts is not None:
            for i, (ats, r) in enumerate(access):
                if i in used or ats is None:
                    continue
                d = (ats - ts).total_seconds()
                if 0 <= d <= ROUTE_WINDOW_S:
                    route = r
                    used.add(i)
                    break
        out[(mode, role, route)] += 1
    return out


def _lines(path: str) -> Iterator[str]:
    if path == "-":
        yield from sys.stdin
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            yield from f


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    counts = tally(_lines(argv[1]))
    if not counts:
        print("No platform-gate lines found: the gate was not hit in this log.")
        return 0
    print(f"{'mode':28} {'role':16} {'count':>6}  route")
    for (mode, role, route), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{mode:28} {role:16} {n:>6}  {route}")
    print(f"\ntotal: {sum(counts.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
