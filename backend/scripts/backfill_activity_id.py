#!/usr/bin/env python3
"""Give a FILED log's id-less crew rows an identity.  DRY-RUN BY DEFAULT.

  python backend/scripts/backfill_activity_id.py            # DRY RUN, writes nothing
  python backend/scripts/backfill_activity_id.py --apply    # writes
  python backend/scripts/backfill_activity_id.py --logbook-id <id>   # one record

Requires MONGO_URL + DB_NAME, the same contract as the other scripts here.

═══════════════════════════════════════════════════════════════════════════
THE DEAD END THIS ENDS
═══════════════════════════════════════════════════════════════════════════

POST /api/logbooks/{id}/activity-photo appends a photograph to a filed log by
pushing through `arrayFilters: [{act.activity_id: X}]` — IDENTITY, NEVER
POSITION, because an index stops naming the same row the moment one is added,
removed or reordered, and that endpoint is reached hours after the CP stopped
looking at the screen.

A crew row that carries no `activity_id` therefore cannot be reached by any id
a client could send. The endpoint refuses it by name (409
ACTIVITY_HAS_NO_IDENTITY) rather than pushing at a plausible index — which is
correct, and is a dead end on real historical records.

═══════════════════════════════════════════════════════════════════════════
WHAT THE INVESTIGATION FOUND
═══════════════════════════════════════════════════════════════════════════

  WHERE THE FIELD COMES FROM. `EMPTY_ACTIVITY` in
  frontend/src/utils/dailyJobsiteModel.js is the ONLY writer of `activity_id`,
  added 2026-08-10 (f49ddb5). The backend has never written one: server.py
  reads the field in exactly two places, the capture-photo R2 key and the
  append route, and NEITHER PDF RENDERER NOR THE COMBINED REPORT PRINTS IT.

  THE WINDOW IS WIDER THAN THAT DATE. `withActivityIds` — the client-side mint
  for a stored row that has none — landed 2026-08-31 (2fa1293), three weeks
  later. Between those dates a log could be hydrated and re-saved and keep its
  id-less rows. So the affected shape is: any daily_jobsite (or
  fall_protection) log whose crew rows were last written by a build from before
  2026-08-31, plus every amendment child that copied one — amend_logbook starts
  the child from `original.get("data")` verbatim.

  AND THE CLIENT-SIDE MINT CANNOT REACH A FILED LOG. `withActivityIds` runs on
  hydrate and only reaches the server through a save; a filed log refuses every
  save (423 when locked, 409 FILED_LOG_DATA_IMMUTABLE otherwise). The rows that
  need an identity most are exactly the ones it can never touch. That is the
  gap, and it is why this runs server-side.

  THE COUNT CANNOT BE READ FROM THE CODE. Production is not queryable from
  here. Run the mongosh in the README section at the bottom of this docstring
  first — the dry run below reports the same numbers.

═══════════════════════════════════════════════════════════════════════════
WHY POSITION IS SAFE HERE AND NOWHERE ELSE
═══════════════════════════════════════════════════════════════════════════

Adding an `activity_index` parameter to the append route was the other option
and it is refused. It would work for the panel that renders
`filedLog.data.activities` in stored order — and it would then be available to
every caller, on every log, forever. daily_jobsite.jsx:216-228 records exactly
what that costs: the screen's list is NOT the server's list
(reconcileCrewsWithRoster lifts every unassigned-worker row out of its stored
position and re-appends it at the tail; commitAddCrew appends a hand-added crew
after those), so an index from a client is a photograph on another crew's row
of a signed compliance record. Widening the API permanently to serve a bounded
historical set is the wrong trade.

INSIDE THIS SCRIPT the position never crosses a wire. It is read off the stored
array, server-side, on a FILED log — a document whose `data` no writer may
rewrite, which is the very guard the append feature exists to route around — and
every write is PINNED to the array that was read:

    _id                          the document
    data.activities  $size N     the array is the same length
    data.activities.i
        .activity_id  $in
        [null, ""]               that row is still id-less
    <one or more content fields> that row is still the row that was read

If any of those has moved, the update matches nothing, the script reports a
MISS, and NOTHING is written. It never falls back to a looser filter.

═══════════════════════════════════════════════════════════════════════════
WHAT IT WRITES, AND WHAT IT REFUSES TO
═══════════════════════════════════════════════════════════════════════════

  ONE FIELD, ADDITIVE ONLY. `data.activities.{i}.activity_id`, and nothing
  else. It never overwrites an existing id, never reorders, never removes, and
  never touches crews, headcounts, work performed or weather. `activity_id` is
  a row identity, not statutory content — BC 3301.2 does not ask for it and no
  renderer prints it — which is the whole reason stamping a signed record with
  one is not an amendment to what the CP attested to.

  `updated_at` IS NOT MOVED. The append route moves it deliberately, because a
  photograph appearing on the record is something a reader should know about.
  Nothing a reader can see changes here. Moving it would tell every reader, and
  every sweep that sorts on it, that hundreds of filed records changed on the
  night this was run.

  THE ACT IS RECORDED ON THE DOCUMENT instead: `activity_id_backfilled_at`,
  following base64_purged_at's precedent — a stamp the server writes recording
  what it did.

  A COLLISION REFUSES THE WHOLE DOCUMENT. `arrayFilters` matches EVERY row
  carrying the id, so two rows sharing one means a single photograph landing on
  both — a photograph on the wrong activity of a signed record, which is the
  one outcome this must never produce. If a minted id is already present
  anywhere in the document, that document is skipped entirely and named in the
  report. A partially stamped document with a collision in it is still a
  document with a collision in it.

  DRAFTS ARE OUT OF SCOPE. A draft's rows get an id from the ordinary editor
  the next time it is opened and saved, and its array is live — stamping it
  would be a write fighting the client for no gain. The dead end only exists on
  a record the CP can no longer save.

  IDEMPOTENT. Run it twice and the second run reports 0 candidates.

═══════════════════════════════════════════════════════════════════════════
THE ID
═══════════════════════════════════════════════════════════════════════════

    legacy_{logbook_id}_{index}

DETERMINISTIC, so a re-run after a partial apply plans the same identity for
the same row rather than minting a second one. UNIQUE WITHIN THE DOCUMENT by
construction, which is the only scope arrayFilters cares about. It cannot
collide with a client-minted id (`act_{ms}_{seq}` / `fp_{base36}_{seq}`). And
it survives server.py's `_logbook_photo_key_segment` unchanged, so the R2 key
`logbook-photos/{project}/{activity_id}/{photo_id}.jpg` names what the row
carries.

The logbook id is embedded so the id is traceable to the record it was minted
for. An amendment child that later copies this `data` carries its PARENT's id
inside the string; that is cosmetic, and harmless — the value is only ever
matched within the document that holds it.

═══════════════════════════════════════════════════════════════════════════
COUNT IT FIRST (mongosh, plain lines — run each one on its own)
═══════════════════════════════════════════════════════════════════════════

use levelog
db.logbooks.countDocuments({ is_deleted: { $ne: true }, $or: [ { status: "submitted" }, { is_locked: true } ], "data.activities": { $elemMatch: { activity_id: { $in: [null, ""] } } } })
db.logbooks.aggregate([ { $match: { is_deleted: { $ne: true }, $or: [ { status: "submitted" }, { is_locked: true } ], "data.activities": { $elemMatch: { activity_id: { $in: [null, ""] } } } } }, { $group: { _id: "$log_type", logs: { $sum: 1 } } } ])
db.logbooks.countDocuments({ activity_id_backfilled_at: { $exists: true } })
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# The prefix is part of the contract, not decoration: `test_the_prefix_cannot
# _collide_with_a_client_minted_id` holds it against both client mints.
LEGACY_ID_PREFIX = "legacy_"

# base64_purged_at's precedent — a stamp the server writes recording what it
# did, on the document it did it to.
STAMP_FIELD = "activity_id_backfilled_at"

# THE ROW FIELDS USED AS A FINGERPRINT, and why these five. They are the ones
# both PDF renderers print positionally (server.py:12857-12861 and :17713-17719)
# and the ones EMPTY_ACTIVITY seeds, so a legacy crew row that carries any
# content at all carries one of them. They are pinned in the update filter so a
# row that changed between the read and the write is MISSED rather than stamped.
#
# Only fields that are PRESENT AND SCALAR are used. A dict or list would make
# the filter an exact-document match on a subtree, which is a different and
# much more brittle question than "is this still the row I read".
FINGERPRINT_FIELDS = ("crew_id", "company", "num_workers",
                      "work_description", "work_locations", "worker_name")

# How many fingerprint fields to pin. More is not better: every extra clause is
# another way for a legitimate row to MISS on a value that was always equal.
# Three present fields is already a very specific row.
FINGERPRINT_MAX = 3

# The candidate set. `$or` on status/is_locked is the same pair
# isOpenForEditing asks — an END_OF_DAY log is submitted and not locked until
# the overnight sweep, an IMMEDIATE type is locked the moment it is signed, and
# reading only one of them would miss half the filed records.
#
# `$in: [null, ""]` matches a MISSING field as well as a null one, and the
# empty string besides. Absence, null and "" are one state, exactly as the
# endpoint treats them.
CANDIDATE_QUERY = {
    "is_deleted": {"$ne": True},
    "$or": [{"status": "submitted"}, {"is_locked": True}],
    "data.activities": {"$elemMatch": {"activity_id": {"$in": [None, ""]}}},
}


def minted_id(logbook_id, index: int) -> str:
    return f"{LEGACY_ID_PREFIX}{logbook_id}_{index}"


def _identity(row) -> str:
    """The row's identity as the ENDPOINT reads it: str(...).strip()."""
    return str((row or {}).get("activity_id") or "").strip()


def _fingerprint(row, index: int) -> dict:
    out = {}
    for field in FINGERPRINT_FIELDS:
        if len(out) >= FINGERPRINT_MAX:
            break
        val = row.get(field)
        if isinstance(val, (str, int, float, bool)) and str(val).strip():
            out[f"data.activities.{index}.{field}"] = val
    return out


def plan_for_document(doc: dict) -> dict:
    """What this script WOULD do to one document. Pure — no I/O, no writes.

    Returns {logbook_id, project_id, log_type, date, total, already_identified,
    unstampable, stamps: [{index, activity_id, filter}], refusal}.

    `refusal` is a machine name and `stamps` is empty whenever it is set. Every
    refusal is a fact about the DOCUMENT, not about this run — re-running will
    reach the same conclusion.
    """
    logbook_id = str(doc.get("_id") or "")
    out = {
        "logbook_id": logbook_id,
        "project_id": str(doc.get("project_id") or ""),
        "log_type": str(doc.get("log_type") or ""),
        "date": str(doc.get("date") or ""),
        "total": 0,
        "already_identified": 0,
        "unstampable": 0,
        "stamps": [],
        "refusal": None,
    }

    if doc.get("is_deleted") is True:
        out["refusal"] = "DELETED"
        return out
    if not (doc.get("status") == "submitted" or doc.get("is_locked")):
        out["refusal"] = "NOT_FILED"
        return out

    rows = ((doc.get("data") or {}).get("activities"))
    if not isinstance(rows, list) or not rows:
        out["refusal"] = "NO_ACTIVITIES"
        return out
    out["total"] = len(rows)

    existing = {_identity(r) for r in rows if isinstance(r, dict) and _identity(r)}
    out["already_identified"] = len(
        [r for r in rows if isinstance(r, dict) and _identity(r)])

    stamps = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            # A non-dict in activities[] is not a crew row and there is nothing
            # to stamp on it. Counted, never guessed at.
            out["unstampable"] += 1
            continue
        if _identity(row):
            continue
        new_id = minted_id(logbook_id, index)
        if new_id in existing:
            # THE WHOLE DOCUMENT, not this row. See the docstring: a partial
            # stamp of a document with a collision in it is still one.
            out["refusal"] = "ID_COLLISION"
            out["stamps"] = []
            return out
        stamps.append({
            "index": index,
            "activity_id": new_id,
            "filter": {
                "_id": doc.get("_id"),
                "data.activities": {"$size": len(rows)},
                f"data.activities.{index}.activity_id": {"$in": [None, ""]},
                **_fingerprint(row, index),
            },
        })
    out["stamps"] = stamps
    return out


async def apply_plan(db, plan: dict, dry_run: bool = False) -> dict:
    """Execute one document's plan. Returns {stamped, missed}.

    Every write is its own update_one with its own pinned filter, rather than
    one update carrying every path. A single combined write would be all-or-
    nothing on a filter naming every row at once — and the interesting failure
    is one row having moved, which should cost that row and no other.
    """
    result = {"stamped": 0, "missed": 0}
    if plan.get("refusal") or not plan.get("stamps"):
        return result
    if dry_run:
        return result
    for stamp in plan["stamps"]:
        res = await db.logbooks.update_one(
            stamp["filter"],
            {"$set": {
                f"data.activities.{stamp['index']}.activity_id":
                    stamp["activity_id"],
            }},
        )
        if getattr(res, "matched_count", 0):
            result["stamped"] += 1
        else:
            # The row is not the row that was read. Nothing was written and
            # nothing is retried with a looser filter.
            result["missed"] += 1
    if result["stamped"]:
        await db.logbooks.update_one(
            {"_id": plan["logbook_id"]},
            {"$set": {STAMP_FIELD: datetime.now(timezone.utc)}},
        )
    return result


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--logbook-id", default=None,
                    help="restrict to one logbook _id")
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N documents (0 = all)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME env vars required", file=sys.stderr)
        return 2

    from motor.motor_asyncio import AsyncIOMotorClient
    from server import to_query_id

    db = AsyncIOMotorClient(mongo_url)[db_name]

    query = dict(CANDIDATE_QUERY)
    if args.logbook_id:
        # Deliberately ANDed with the candidate query rather than replacing it:
        # naming a document does not exempt it from the scope rules.
        query["_id"] = to_query_id(args.logbook_id)

    docs = await db.logbooks.find(query).to_list(length=args.limit or None)

    print("MODE:                     %s" % ("APPLY" if args.apply else "DRY RUN"))
    print("Candidate filed logs:     %d" % len(docs))
    print()

    plans = [plan_for_document(d) for d in docs]
    refused = [p for p in plans if p["refusal"]]
    workable = [p for p in plans if not p["refusal"] and p["stamps"]]
    nothing = [p for p in plans if not p["refusal"] and not p["stamps"]]

    rows_to_stamp = sum(len(p["stamps"]) for p in workable)
    print("  would stamp:            %d rows across %d logs"
          % (rows_to_stamp, len(workable)))
    print("  nothing to do:          %d logs" % len(nothing))
    print("  REFUSED:                %d logs" % len(refused))
    print()

    by_type = {}
    for p in workable:
        by_type[p["log_type"]] = by_type.get(p["log_type"], 0) + len(p["stamps"])
    if by_type:
        print("Rows by log type:")
        for k in sorted(by_type):
            print("  %-28s %d" % (k or "(none)", by_type[k]))
        print()

    if refused:
        print("REFUSED — these are NOT touched, and a re-run will refuse them again:")
        for p in refused:
            print("  %-26s %-20s %-12s  %s"
                  % (p["logbook_id"], p["log_type"], p["date"], p["refusal"]))
        print()

    if workable:
        print("Would set:")
        for p in workable:
            print("  %s  %s %s  (%d rows, %d already identified)"
                  % (p["logbook_id"], p["log_type"], p["date"],
                     p["total"], p["already_identified"]))
            for s in p["stamps"]:
                print("      data.activities.%-3d activity_id = %s"
                      % (s["index"], s["activity_id"]))
        print()

    if not args.apply:
        print("DRY RUN — nothing was written. Re-run with --apply.")
        return 0

    stamped = missed = 0
    for p in workable:
        res = await apply_plan(db, p)
        stamped += res["stamped"]
        missed += res["missed"]

    print("Stamped:                  %d rows" % stamped)
    print("MISSED:                   %d rows" % missed)
    if missed:
        print()
        print("A MISS IS NOT A FAILURE TO RETRY BLINDLY. It means the row was")
        print("not the row this run read — the document changed underneath it.")
        print("Re-run the DRY RUN and look at what those documents hold now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
