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
import inspect
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


#: Flags that USED to mean "really do it" on the scripts in this directory.
#: They no longer gate anything. Listed so the refusal below can name the one
#: the caller actually typed.
LEGACY_WRITE_FLAGS = ("--execute", "--apply", "--commit", "--yes")


def refuse_legacy_flag(argv=None) -> None:
    """A runbook that says `--execute` must FAIL LOUDLY, not silently no-op.

    Sixteen of the twenty scripts here already had a write flag -- `--execute`,
    `--apply`, `--dry-run/--execute` -- and every one of them is written down in
    a docstring, a runbook or somebody's shell history. Two outcomes were
    available when `--i-know` took over as the gate, and both of the obvious
    ones are wrong:

      SILENTLY WRITE on the old flag  -- then the guard is decoration.
      SILENTLY NO-OP on the old flag  -- then an operator runs the documented
                                         command, sees a clean report, and
                                         believes a migration ran that did not.

    So the old flag without the new one is an ERROR that names both. The third
    outcome is the only honest one: the command stops and says what changed.
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--i-know" in argv:
        return
    used = [f for f in LEGACY_WRITE_FLAGS if f in argv]
    if not used:
        return
    sys.stderr.write(
        f"\n{' and '.join(used)} no longer authorises a production write.\n"
        "  The gate is now --i-know, and it requires --reason and --session\n"
        "  so the audit row can say who ran this and why. Nothing was\n"
        "  changed.\n\n"
        "  Add:  --i-know --reason '<why>' --session <id>\n\n")
    raise SystemExit(2)


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
    """Write the row.

    ── HOW MANY ROWS, AND IT IS A JUDGEMENT PER SCRIPT ─────────────────────

    ONE PER DOCUMENT for a targeted change -- reparenting a project, setting a
    building's levels. "The script updated 4 rows" is not an audit trail when
    the question afterwards is about one project, and `details` carries the
    before/after for that document.

    ONE PER RUN for a bulk migration. A backfill touching ten thousand rows
    would otherwise write ten thousand audit rows and bury every other entry in
    the collection; there the row records the selector, the counts and the
    reason, which is what anybody asks of a migration.

    The rule is: could a person afterwards ask about ONE of these documents? If
    yes, a row each. If the only question is "did the migration run", one row.

    NOT FAILURE-ISOLATED, and this is the one place in the codebase where that
    is right. The app's `audit_log` swallows a write failure because refusing
    would break a CP's filing; here there is nothing to protect — if the row
    cannot be written, the operator would rather the script stopped than have
    it continue leaving untraceable changes.
    """
    await db[AUDIT_COLLECTION].insert_one(
        _audit_row(action, resource_type, resource_id, details, args, name))


def script_audit_sync(db, action: str, resource_type: str, resource_id: str,
                      details: dict, args, name: Optional[str] = None) -> None:
    """`script_audit` for a PyMongo handle.

    Three of the twenty scripts here -- backfill_deleted_at, backfill_iso_expiry
    and strip_inline_worker_image -- connect with `pymongo.MongoClient`, not
    motor, because they were written as one-shot synchronous reports. Their
    writes are production writes like any other, so they need the same row; the
    only thing that differs is that `insert_one` returns a result rather than a
    coroutine. SAME COLLECTION, SAME SHAPE, SAME actor -- a reader asking what
    happened to a document must not have to know which driver touched it.
    """
    db[AUDIT_COLLECTION].insert_one(
        _audit_row(action, resource_type, resource_id, details, args, name))


def _audit_row(action, resource_type, resource_id, details, args, name) -> dict:
    """The row itself, built in ONE place so the sync and async paths cannot
    drift into writing two different shapes into the same collection."""
    return {
        "action": action,
        "user_id": SCRIPT_ACTOR_PREFIX + (name or script_name()),
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "details": details or {},
        "timestamp": datetime.now(timezone.utc),
        "session_id": str(getattr(args, "session", "") or ""),
        "reason": str(getattr(args, "reason", "") or ""),
    }


def report_dry_run(what: str) -> None:
    sys.stdout.write(
        f"\nDRY RUN — nothing was written.\n  Would: {what}\n"
        "  Re-run with --i-know --reason '<why>' --session <id> to apply.\n\n")


# ── THE AUDITED HANDLE ──────────────────────────────────────────────────────
#
# WHY A WRAPPER AND NOT A CALL AT EVERY WRITE SITE.
#
# Twenty scripts, twenty-six write calls, every one in a differently-shaped
# main(). Hand-placing an audit call at each is twenty-six chances to put it
# after an early return, inside the wrong branch, or on the dry-run path -- and
# a source test can only prove the call EXISTS, not that it runs when the write
# runs. The failure it is guarding against is precisely "the write happened and
# nothing recorded it", so a guard that can be bypassed by control flow is the
# wrong shape.
#
# Wrapping the handle makes the row a property of the WRITE rather than of the
# script: `db.dob_logs.delete_many(...)` audits because it executed, not
# because somebody remembered. One line changes per script.
#
# IT RECORDS THE SELECTOR AND THE RESULT, which is what anybody asks
# afterwards: what did it match, what did it change, what was the filter. The
# arguments are stringified and truncated -- an audit row is evidence that
# something happened, not a copy of the payload.

#: The methods that change stored data. Anything not here passes straight
#: through untouched, so a wrapped handle reads exactly like a bare one.
_WRITE_METHODS = frozenset({
    "update_one", "update_many", "insert_one", "insert_many",
    "delete_one", "delete_many", "bulk_write", "replace_one",
    "find_one_and_update", "find_one_and_delete", "drop",
})

#: NEVER AUDIT THE AUDIT LOG. `script_audit` is itself an `insert_one`, so
#: without this a single write recurses until the stack ends.
_NEVER_AUDITED = frozenset({AUDIT_COLLECTION})


def _short(value, limit: int = 300) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "…"


class _AuditedCollection:
    def __init__(self, coll, parent, cname):
        self._coll, self._parent, self._cname = coll, parent, cname

    def _details(self, attr, a, result) -> dict:
        # Built AFTER the write, and deliberately: a row claiming a change that
        # then failed is worse than no row. The counts below only exist once the
        # driver has answered.
        details = {
            "method": attr,
            "collection": self._cname,
            "args": [_short(x) for x in a][:3],
        }
        for field in ("matched_count", "modified_count", "deleted_count",
                      "upserted_id", "inserted_id"):
            got = getattr(result, field, None)
            if got is not None:
                details[field] = str(got)
        return details

    def __getattr__(self, attr):
        target = getattr(self._coll, attr)
        if attr not in _WRITE_METHODS or self._cname in _NEVER_AUDITED:
            return target

        # NOT an `async def`, and that is the whole point. Three of these
        # scripts drive PyMongo and the rest drive Motor. An `async def` wrapper
        # over PyMongo is the worst available failure: the sync caller gets back
        # a coroutine it never awaits, so the WRITE SILENTLY DOES NOT HAPPEN and
        # the run reports success -- a script that looks guarded and is in fact
        # inert. So the driver decides, by what it actually returned.
        def _wrapped(*a, **kw):
            result = target(*a, **kw)
            if inspect.isawaitable(result):
                return _finish_async(self, attr, a, result)
            script_audit_sync(
                self._parent._db, f"script_{attr}", "collection", self._cname,
                self._details(attr, a, result), self._parent._args,
                name=self._parent._name,
            )
            return result

        return _wrapped


async def _finish_async(coll, attr, a, pending):
    """Await the driver's write, then write the row. Separate from `_wrapped`
    so the sync path never constructs a coroutine at all."""
    result = await pending
    await script_audit(
        coll._parent._db, f"script_{attr}", "collection", coll._cname,
        coll._details(attr, a, result), coll._parent._args,
        name=coll._parent._name,
    )
    return result


class _AuditedDb:
    """A database handle -- Motor or PyMongo -- whose writes record themselves.

    READS ARE UNTOUCHED and cost nothing: `__getattr__` only wraps a collection,
    and the collection only wraps the eleven write methods.
    """

    def __init__(self, db, args, name):
        self._db, self._args, self._name = db, args, name

    def __getattr__(self, attr):
        target = getattr(self._db, attr)
        # A DATABASE METHOD IS NOT A COLLECTION. `db.list_collection_names()`,
        # `db.command(...)` and friends resolve to bound methods; wrapping one
        # in _AuditedCollection returns an object that is not callable, so the
        # script dies on a READ it was never meant to touch. Both drivers hand
        # back a real Collection for an unknown name, so `find_one` is what
        # distinguishes the two.
        if not hasattr(target, "find_one"):
            return target
        return _AuditedCollection(target, self, attr)

    def __getitem__(self, key):
        return _AuditedCollection(self._db[key], self, str(key))


def audited(db, args, name: Optional[str] = None):
    """Wrap a database handle so every write leaves an audit row.

    Used as the ONE line a production-writing script changes:

        db = audited(client[dbname], args, NAME)

    Returns the handle unchanged when the guard has not authorised a write --
    there is nothing to audit on a dry run, and wrapping would only add a layer
    to step through while debugging one.
    """
    if not getattr(args, "i_know", False):
        return db
    return _AuditedDb(db, args, name or script_name())
