"""Move the INLINE full-size photo bytes of EXISTING logbooks into R2.

From this track on, a photo is uploaded to R2 the moment it is TAKEN and the
document carries only the key. Every logbook written BEFORE that still holds
its photos as base64 under data.activities[].photos[] — this is the one-shot
that gives those photos an R2 object too.

WHAT IT DOES, per photo, in order:

  1. UPLOAD. The inline bytes go to R2 under the capture-scheme key
     `logbook-photos/{project_id}/{activity_id}/{photo_id}.jpg`, the same key
     shape a live capture uses, so both eras end up addressed identically.

     The photo id is CONTENT-ADDRESSED — sha256 of the inline base64 — and not
     minted at random. A re-run therefore computes the SAME key and overwrites
     the same object instead of orphaning a second copy, even if a previous run
     died between the upload and the document write. Old rows may predate
     `activity_id`; those fall back to the logbook id for the middle segment.
     Neither segment is ever recomputed from a POSITION, so a later row
     reorder cannot make the key point at a different photo.

  2. WRITE THE KEY. `original_r2_key` on the photo — the rung the serving
     ladder (_logbook_photo_sources) has always read and nothing used to write.

  3. RECLAIM, BY DELEGATION. The inline copy is removed by calling Track P's
     own _purge_finalized_photo_base64, unchanged — the three conditions
     (enhance_status == "done", both derivative keys present, a live
     head_object on BOTH) are not reimplemented here, because a second
     implementation of a safety gate is a second thing that can be wrong.
     THIS SCRIPT NEVER TOUCHES thumb_base64: the purge materialises the
     retained thumbnail itself, from the bytes R2 really returns, in the same
     update that removes the full-size copy. That is the only writer of it on
     this path and it stays that way.

     Only FINALIZED (is_locked) logs are offered for reclaim, because that is
     Track P's contract — an editable log keeps its inline copy, exactly as it
     does in production today. A photo the purge refuses keeps its base64
     permanently and is COUNTED, not retried into a hole.

  4. NOTHING ELSE. No photo is deleted, no key is rewritten, no positional key
     from the old scheme is migrated or removed. A photo that already has an
     `original_r2_key` is skipped at step 1 and still considered at step 3.

DRY-RUN IS THE DEFAULT. Without --execute nothing is uploaded and nothing is
written; the run reports exactly what it would have done.

Usage:
  python -m scripts.backfill_photo_to_r2                      # dry-run, all
  python -m scripts.backfill_photo_to_r2 --project-id proj1   # dry-run, scoped
  python -m scripts.backfill_photo_to_r2 --execute            # write
  python -m scripts.backfill_photo_to_r2 --execute --limit 50 # write, capped
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

logger = logging.getLogger(__name__)


def photo_backfill_id(b64_data: str) -> str:
    """The photo id segment for a pre-existing inline photo.

    Content-addressed on purpose: the same bytes always produce the same key,
    so a re-run (or a run resumed after a crash) converges on the one object
    instead of leaving an orphan behind for every attempt.
    """
    digest = hashlib.sha256((b64_data or "").encode("ascii", "ignore")).hexdigest()
    return f"bf_{digest[:32]}"


def planned_key(doc: Dict[str, Any], activity: Dict[str, Any], b64_data: str) -> str:
    """The R2 key this photo would be uploaded under.

    `activity_id` when the row has one (rows created before it existed do not),
    the logbook id otherwise. Never a position — a reordered row must not
    rename an object.
    """
    activity_id = str((activity or {}).get("activity_id") or "").strip()
    return server._logbook_capture_photo_r2_key(
        str(doc.get("project_id") or ""),
        activity_id or str(doc.get("_id") or ""),
        photo_backfill_id(b64_data),
    )


async def backfill_one(db, doc: Dict[str, Any], execute: bool,
                       stats: Dict[str, int]) -> None:
    """Upload every inline photo of one logbook, then offer it for reclaim."""
    logbook_id = str(doc.get("_id"))
    activities = ((doc.get("data") or {}).get("activities") or [])
    uploaded_here = 0

    for ai, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue
        for pi, photo in enumerate(activity.get("photos") or []):
            if not isinstance(photo, dict):
                continue
            b64_data = photo.get("base64")
            if not b64_data:
                stats["skipped_no_inline_copy"] += 1
                continue
            if photo.get("original_r2_key"):
                stats["skipped_already_keyed"] += 1
                continue

            key = planned_key(doc, activity, b64_data)
            stats["photos_to_upload"] += 1
            if not execute:
                logger.info(
                    "[DRY-RUN] %s a=%d p=%d -> %s", logbook_id, ai, pi, key,
                )
                continue

            try:
                raw = base64.b64decode(b64_data)
            except Exception as e:
                logger.warning(
                    "[backfill] %s a=%d p=%d: inline copy will not decode: %r "
                    "- LEFT ALONE", logbook_id, ai, pi, e,
                )
                stats["undecodable"] += 1
                continue
            if not raw:
                stats["undecodable"] += 1
                continue

            try:
                await asyncio.to_thread(server._upload_to_r2, raw, key, "image/jpeg")
            except Exception as e:
                logger.warning(
                    "[backfill] %s a=%d p=%d: upload failed: %r - LEFT ALONE",
                    logbook_id, ai, pi, e,
                )
                stats["upload_failed"] += 1
                continue

            field = f"data.activities.{ai}.photos.{pi}"
            await db.logbooks.update_one(
                {"_id": server.to_query_id(logbook_id)},
                {"$set": {
                    f"{field}.original_r2_key": key,
                    f"{field}.backfilled_to_r2_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
            # Keep the in-memory copy in step with the document, so the reclaim
            # below sees what was just written.
            photo["original_r2_key"] = key
            uploaded_here += 1
            stats["uploaded"] += 1

    if uploaded_here:
        stats["logbooks_touched"] += 1

    # ── the reclaim, delegated ───────────────────────────────────────────
    if not doc.get("is_locked"):
        stats["reclaim_skipped_not_finalized"] += 1
        return
    if not execute:
        stats["reclaim_candidates"] += 1
        return
    try:
        purged = await server._purge_finalized_photo_base64(logbook_id, doc)
    except Exception as e:
        logger.warning("[backfill] purge skipped for %s: %r", logbook_id, e)
        return
    stats["inline_copies_reclaimed"] += purged


async def run_backfill(db, execute: bool = False, project_id: Optional[str] = None,
                       logbook_id: Optional[str] = None,
                       limit: int = 0) -> Dict[str, int]:
    stats: Dict[str, int] = {
        "logbooks_scanned": 0,
        "logbooks_touched": 0,
        "photos_to_upload": 0,
        "uploaded": 0,
        "skipped_no_inline_copy": 0,
        "skipped_already_keyed": 0,
        "undecodable": 0,
        "upload_failed": 0,
        "reclaim_candidates": 0,
        "reclaim_skipped_not_finalized": 0,
        "inline_copies_reclaimed": 0,
    }

    if execute and not (server._r2_client and server.R2_BUCKET_NAME):
        raise SystemExit(
            "R2 is not configured (R2_BUCKET_NAME / credentials). Refusing to "
            "run with --execute: there would be nothing to upload into, and a "
            "key written for an object that does not exist is worse than no "
            "key at all."
        )

    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if project_id:
        query["project_id"] = project_id
    if logbook_id:
        query["_id"] = server.to_query_id(logbook_id)

    docs = await db.logbooks.find(query).to_list(limit or 100000)
    for doc in docs:
        stats["logbooks_scanned"] += 1
        await backfill_one(db, doc, execute, stats)

    logger.info(
        "backfill_photo_to_r2 %s complete: %s",
        "EXECUTE" if execute else "DRY-RUN", stats,
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="Upload and write changes (default: dry-run, writes nothing)",
    )
    parser.add_argument("--project-id", default=None, help="Scope to one project")
    parser.add_argument("--logbook-id", default=None, help="Scope to one logbook")
    parser.add_argument(
        "--limit", type=int, default=0, help="Stop after N logbooks (0 = all)",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # server.db, NOT a second client. The reclaim delegates to Track P's
    # _purge_finalized_photo_base64, which writes through the module-level `db`
    # — so reading through a different handle would let the two halves of this
    # script address two different databases if the environment ever drifted.
    # One handle, one database, by construction.
    if server._r2_client is None:
        # The module-level R2 client is created in server's startup event,
        # which does not run for a script. Built the same way, same config.
        server._r2_client = server._get_r2_client()

    print(asyncio.run(run_backfill(
        server.db, execute=args.execute, project_id=args.project_id,
        logbook_id=args.logbook_id, limit=args.limit,
    )))


if __name__ == "__main__":
    main()
