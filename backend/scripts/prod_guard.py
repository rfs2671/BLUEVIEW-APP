"""THE GUARD EVERY SCRIPT THAT WRITES PRODUCTION GOES THROUGH.

── WHY IT EXISTS, WITH THE DATE ────────────────────────────────────────────

On 2026-09-16 at 19:07:45Z a session ran `railway run -- python
/c/tmp/writes.py` and did two things to the production database:

    db.projects.update_one({"_id": E852}, {"$set": {"is_deleted": False}})
    db.projects.delete_one({"_id": STUB})

Both were defensible on their own terms — the second counted references across
thirteen collections and found none. Both were INVISIBLE.

`railway run` injects the production environment LOCALLY, so the connection
comes from the laptop. Nothing reaches the container: no HTTP log line, no
application audit row. And the cluster is Atlas SHARED TIER — `hostInfo`
returns CMD_NOT_ALLOWED — where database auditing does not exist. There is no
second source. A project document left the database and the only trace was a
cron error four hours earlier that happened to name the id.

OPERATOR RULE, FOR EVERY SESSION: a production write goes through the app,
which is audited, or through a file in this directory carrying this guard. A
session that needs a prod write reports the exact write and waits for a ruling.
Read-only probes need none of this. Deletes need a ruling, always.

── WHAT THE GUARD ACTUALLY BUYS ────────────────────────────────────────────

THE FLAG IS NOT THE POINT — a flag only stops an accident, and this was not an
accident. THE AUDIT ROW IS THE POINT. `--i-know` exists so that writing one is
unavoidable: you cannot get past the argument parser without also supplying the
reason and the session that the row records.

    actor       "script:<name>"   -- not a user id, because no user did this
    session_id  which session ran it
    reason      why, in the operator's terms, not the script's

── IT IS DELIBERATELY NOT A PERMISSION SYSTEM ──────────────────────────────

Anyone who can run the script can pass the flag. It is not trying to stop a
determined operator; it is trying to make sure that what happened leaves a row
behind, and that a person typing a one-off command has to state out loud what
they are about to do to a database holding filed statutory records.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

#: Actor prefix on every row this writes. Never a user id: no user did it, and
#: attributing it to one would put a person's name on a machine's act.
SCRIPT_ACTOR_PREFIX = "script:"

#: The collection the app's own audit_log writes to. SAME COLLECTION, on
#: purpose -- one place to read when the question is "what happened to this
#: project", rather than a second log nobody remembers to check.
AUDIT_COLLECTION = "audit_logs"


def script_name(argv0: Optional[str] = None) -> str:
    return os.path.basename(argv0 or sys.argv[0] or "unknown").removesuffix(".py")


def add_guard_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The three arguments every production writer takes."""
    parser.add_argument(
        "--i-know", action="store_true", dest="i_know",
        help="Required for any write. Without it the script reports what it "
             "WOULD do and changes nothing.")
    parser.add_argument(
        "--reason", default="",
        help="Why this is being run, in the operator's terms. Recorded on "
             "every audit row. Required with --i-know.")
    parser.add_argument(
        "--session", default=os.environ.get("CLAUDE_SESSION_ID", ""),
        help="The session id running this. Defaults to $CLAUDE_SESSION_ID. "
             "Required with --i-know.")
    return parser


def check_guard(args) -> bool:
    """True when the script may write. Exits 2 when the flag is there and the
    provenance is not.

    ── A DRY RUN IS NOT A FAILURE ──────────────────────────────────────────

    No `--i-know` returns False and the caller reports what it would do. That
    is the DEFAULT, and it is what makes the guard cheap to comply with: the
    first run of any of these scripts is always a report.

    `--i-know` WITHOUT a reason or a session is an ERROR, not a dry run. The
    flag says "I mean it"; the other two are what make that sentence
    attributable, and accepting the flag alone would leave exactly the row this
    whole file exists to prevent -- a write nobody can trace.
    """
    if not getattr(args, "i_know", False):
        return False
    missing = [n for n, v in (("--reason", getattr(args, "reason", "")),
                              ("--session", getattr(args, "session", "")))
               if not str(v or "").strip()]
    if missing:
        sys.stderr.write(
            "\n--i-know requires " + " and ".join(missing) + ".\n"
            "  An unattributed production write is the thing this guard "
            "exists to stop;\n  the flag on its own would just make it "
            "deliberate.\n\n")
        raise SystemExit(2)
    return True


async def script_audit(db, action: str, resource_type: str, resource_id: str,
                       details: dict, args, name: Optional[str] = None) -> None:
    """Write the row. Called ONCE PER DOCUMENT TOUCHED, not once per run.

    PER DOCUMENT, because "the script updated 4 rows" is not an audit trail —
    the question afterwards is always about one project, and a summary row
    cannot answer it. `details` carries the before/after for that document.

    NOT FAILURE-ISOLATED, and this is the one place in the codebase where that
    is right. The app's `audit_log` swallows a write failure because refusing
    would break a CP's filing; here there is nothing to protect — if the row
    cannot be written, the operator would rather the script stopped than have
    it continue leaving untraceable changes.
    """
    await db[AUDIT_COLLECTION].insert_one({
        "action": action,
        "user_id": SCRIPT_ACTOR_PREFIX + (name or script_name()),
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "details": details or {},
        "timestamp": datetime.now(timezone.utc),
        "session_id": str(getattr(args, "session", "") or ""),
        "reason": str(getattr(args, "reason", "") or ""),
    })


def report_dry_run(what: str) -> None:
    sys.stdout.write(
        f"\nDRY RUN — nothing was written.\n  Would: {what}\n"
        "  Re-run with --i-know --reason '<why>' --session <id> to apply.\n\n")
