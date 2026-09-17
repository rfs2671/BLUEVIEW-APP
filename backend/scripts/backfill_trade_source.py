"""Annotate existing roster rows with trade_source. Rewrites no trade string.

WHAT IT DOES, precisely: adds `trade_source: "vocabulary" | "custom"` to every
row of every project's `trade_assignments`. It does not touch `trade`,
`company`, `id`, or `status`, and it touches no other collection.

WHY A SCRIPT AND NOT AN AUTOMATIC BACKFILL. The convention is already set in
this repo -- test_roster_ids_on_create.py pins that create_project contains no
`update_many`, with the note "The backfill is the operator's call, and this
pins that the code does not quietly make it for him." Same rule here.

WHY NOTHING IS REWRITTEN. A published label is immutable. A filed
subcontractor_orientation holds `data.worker_trade` as a plain English string
forever, and nothing joins on it -- so re-spelling a roster value would orphan
that record silently. A string matching no vocabulary entry keeps its exact
bytes and is flagged `custom`; it renders, files and prints identically.

Rows are also stamped on every save by _merge_trade_assignments, so this is a
one-time catch-up for rosters nobody has edited since.

    DRY RUN (default -- prints what would change, writes nothing):
        python backend/scripts/backfill_trade_source.py

    APPLY:
        python backend/scripts/backfill_trade_source.py --apply
"""

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:backfill_trade_source", the session and the reason.
# Without --i-know the handle is unwrapped and nothing is written. See
# prod_guard.
import os as _g_os                                              # noqa: E402
import sys as _g_sys                                            # noqa: E402
_g_sys.path.insert(0, _g_os.path.dirname(_g_os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag,
)

NAME = "backfill_trade_source"


def _roster_key(value) -> str:
    """Mirrors server._roster_key. Duplicated here ON PURPOSE: importing server
    boots the whole FastAPI app, its indexes and its background tasks, which a
    one-shot migration must not do. A test asserts the two agree."""
    return str(value or "").strip().casefold()


async def main(args) -> int:
    # THE BOOL BECAME THE NAMESPACE, because `audited` needs the reason and the
    # session that go on the row, and a bare `apply` carries neither. The gate
    # itself is unchanged: `apply` is still the one local every branch below
    # tests, it is just bound from the guard now.
    apply = args.apply
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set.")
        return 2

    # Imported lazily and by module surgery rather than by importing `server`:
    # the lists are the only thing needed and booting the app is not.
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    ns: dict = {"List": list, "Dict": dict}
    for name in ("TRADE_VOCABULARY", "DEPRECATED_TRADES"):
        start = src.index(f"{name}: ")
        end = src.index("\n]\n", start) + 3 if name == "TRADE_VOCABULARY" else src.index("\n}\n", start) + 3
        exec(src[start:end], ns)  # noqa: S102 - reading our own source, not input
    vocabulary = ns["TRADE_VOCABULARY"]
    deprecated = ns["DEPRECATED_TRADES"]
    known = {_roster_key(t) for t in vocabulary} | {_roster_key(t) for t in deprecated}
    print(f"vocabulary: {len(vocabulary)} active + {len(deprecated)} deprecated")

    client = AsyncIOMotorClient(mongo_url)
    db = audited(client[db_name], args, NAME)

    seen = Counter()
    custom_values = Counter()
    projects_touched = 0
    rows_touched = 0

    async for project in db.projects.find({"trade_assignments": {"$exists": True}}):
        rows = project.get("trade_assignments") or []
        if not isinstance(rows, list):
            continue
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            trade = row.get("trade")
            source = "vocabulary" if _roster_key(trade) in known else "custom"
            seen[source] += 1
            if source == "custom":
                custom_values[str(trade)] += 1
            if row.get("trade_source") != source:
                row["trade_source"] = source
                changed = True
                rows_touched += 1
        if changed:
            projects_touched += 1
            if apply:
                await db.projects.update_one(
                    {"_id": project["_id"]},
                    {"$set": {"trade_assignments": rows}},
                )

    print(f"\nrows: {seen['vocabulary']} vocabulary, {seen['custom']} custom")
    print(f"projects needing the stamp: {projects_touched}  (rows: {rows_touched})")
    if custom_values:
        print("\nOFF-VOCABULARY VALUES -- kept exactly as stored, never rewritten:")
        for value, n in custom_values.most_common():
            print(f"  {n:5d}  {value!r}")
        print("\nEach is a candidate for the vocabulary. Adding a label there and")
        print("re-running flips the flag without editing a single stored string.")
    if not apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
    client.close()
    return 0


if __name__ == "__main__":
    # BEFORE THE PARSER, so `--apply` is refused by name rather than being
    # parsed into a flag that no longer means what the runbook says it means.
    refuse_legacy_flag()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the annotations")
    add_guard_args(ap)
    args = ap.parse_args()
    # --i-know IS THE GATE NOW. The old flag is still parsed so an operator's
    # runbook reaches a message rather than an argparse error -- refuse_legacy_flag
    # has already stopped him if he typed one -- and this line is what makes the
    # rest of the script obey the guard without rewriting any of its branches.
    args.apply = check_guard(args)
    sys.exit(asyncio.run(main(args)))
