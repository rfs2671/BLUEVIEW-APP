"""Give every captured photo the thumbnail the enhance pass never made for it.

WHY THEY HAVE NONE. `_enhance_logbook_photos` was scheduled from POST
/logbooks alone. The CP's real path -- Save Draft, then Submit -- arrives as a
PUT, the offline drain pushes with a PUT, and a photo added to a filed log goes
through the append route; none of those three ran it. A photo that reached a
log through any of them kept its R2 original (`original_r2_key`) and nothing
else: no thumbnail, no enhanced render. On 2026-10-08 that was 134 photos on
filed daily jobsite logs on 588 Thomas, and the site kiosk loaded each one's
FULL-SIZE ORIGINAL into an 80x60 tile. The forward fix schedules the pass from
all three paths; this is the one-shot for the photos it missed.

WHAT IT DOES, per photo that has `original_r2_key`, no `thumb_r2_key`, and no
`enhance_status` of "done":

  1. ENHANCE, WITH THE PASS'S OWN FUNCTION. `server._enhance_r2_original_sync`
     -- exactly what `_enhance_logbook_photos` calls for a captured photo --
     reads the original from R2, uploads `<original>-enhanced.jpg` and
     `<original>-thumb.jpg` beside it, and returns the patch: the two keys,
     `enhance_status: "done"`, timings and dimensions, and the ~400px
     `thumb_base64` the capture path keeps inline as the last-resort copy. Not
     reimplemented here: a second copy of the enhance step is a second thing
     that can be wrong.
  2. WRITE THE PATCH, CONDITIONALLY. One `$set` on the photo's own path, with
     a filter that the photo AT THAT POSITION still has this original and
     still has no thumbnail. A log edited since the scan, or a run that
     overlaps another, writes nothing rather than writing onto the wrong photo.
  3. NOTHING ELSE. The original object is never touched. `updated_at` is not
     moved: the record's content -- what was filed -- is unchanged; it gains a
     rendition of a photo it already had. A photo whose enhance FAILS is
     stamped `enhance_status: "failed"` with the error, as the pass does, and
     counted.

ORDER WITH #699. Each photo gains an inline ~400px thumbnail. Until the device
build that defers those (#699) is the one phones run, a day download carries
them inline -- so this runs after #699 ships.

DRY-RUN IS THE DEFAULT. Without --i-know nothing is uploaded and nothing is
written; the run lists every photo it would enhance and the size of its
original. --i-know requires --reason and --session, and every database write
is recorded in audit_logs with actor "script:backfill_photo_thumbnails" (see
scripts/prod_guard.py). The R2 uploads are not Mongo writes; the audited `$set`
names both keys they produced.

Usage:
  python -m scripts.backfill_photo_thumbnails                         # dry-run
  python -m scripts.backfill_photo_thumbnails --project-id <id>       # scoped
  python -m scripts.backfill_photo_thumbnails --i-know --reason "..." --session <id>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

import os as _g_os                                              # noqa: E402
import sys as _g_sys                                            # noqa: E402
_g_sys.path.insert(0, _g_os.path.dirname(_g_os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag,
)

NAME = "backfill_photo_thumbnails"
logger = logging.getLogger(__name__)


def photos_needing_a_thumbnail(doc: dict) -> List[Dict[str, Any]]:
    """[{ai, pi, original_r2_key}] for this log's photos the pass never reached.

    PURE. A photo qualifies when it was captured into R2 (`original_r2_key`),
    has no thumbnail object (`thumb_r2_key`), and is not already enhanced. An
    inline-base64 photo is NOT this script's: it has its own path through the
    pass, and backing those up is scripts/backfill_photo_to_r2.py's job.
    """
    out = []
    data = (doc or {}).get("data")
    acts = data.get("activities") if isinstance(data, dict) else None
    if not isinstance(acts, list):
        return out
    for ai, act in enumerate(acts):
        photos = act.get("photos") if isinstance(act, dict) else None
        if not isinstance(photos, list):
            continue
        for pi, p in enumerate(photos):
            if not isinstance(p, dict):
                continue
            key = p.get("original_r2_key")
            if (key and not p.get("thumb_r2_key")
                    and p.get("enhance_status") != "done"):
                out.append({"ai": ai, "pi": pi, "original_r2_key": key})
    return out


def _object_size(key: str) -> Optional[int]:
    """Size of the original in R2, or None when it cannot be read. READ-ONLY."""
    try:
        head = server._r2_client.head_object(Bucket=server.R2_BUCKET_NAME, Key=key)
        return int(head.get("ContentLength") or 0)
    except Exception:  # pragma: no cover - reported, not raised
        return None


async def run(db, execute: bool = False, project_id: Optional[str] = None,
              logbook_id: Optional[str] = None, limit: int = 0) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "logbooks_scanned": 0, "logbooks_with_work": 0, "photos": 0,
        "originals_missing_in_r2": 0, "original_bytes": 0,
        "enhanced": 0, "failed": 0, "skipped_changed_since_scan": 0,
    }
    if not (server._r2_client and server.R2_BUCKET_NAME):
        raise SystemExit(
            "R2 is not configured. Refusing to run: there is nothing to read "
            "the originals from.")
    query: Dict[str, Any] = {
        "is_deleted": {"$ne": True},
        "data.activities.photos.original_r2_key": {"$exists": True},
    }
    if project_id:
        query["project_id"] = project_id
    if logbook_id:
        query["_id"] = server.to_query_id(logbook_id)
    docs = await db.logbooks.find(query).to_list(limit or 100000)
    loop = asyncio.get_running_loop()
    for doc in docs:
        stats["logbooks_scanned"] += 1
        todo = photos_needing_a_thumbnail(doc)
        if not todo:
            continue
        stats["logbooks_with_work"] += 1
        for t in todo:
            stats["photos"] += 1
            size = _object_size(t["original_r2_key"])
            if size is None:
                stats["originals_missing_in_r2"] += 1
            else:
                stats["original_bytes"] += size
            print(f"{'ENHANCE' if execute else 'would enhance'} "
                  f"log={doc['_id']} date={str(doc.get('date'))[:10]} "
                  f"status={doc.get('status')} a{t['ai']} p{t['pi']} "
                  f"original={t['original_r2_key']} bytes={size}")
            if not execute:
                continue
            field = f"data.activities.{t['ai']}.photos.{t['pi']}"
            try:
                patch = await loop.run_in_executor(
                    None, server._enhance_r2_original_sync, t["original_r2_key"])
                stats["enhanced"] += 1
            except Exception as e:
                logger.warning("enhance failed log=%s %s: %r", doc["_id"], field, e)
                patch = {"enhance_status": "failed", "enhance_error": str(e)[:200]}
                stats["failed"] += 1
            res = await db.logbooks.update_one(
                {"_id": doc["_id"],
                 f"{field}.original_r2_key": t["original_r2_key"],
                 f"{field}.thumb_r2_key": {"$exists": False}},
                {"$set": {f"{field}.{k}": v for k, v in patch.items()}},
            )
            if not getattr(res, "matched_count", 0):
                stats["skipped_changed_since_scan"] += 1
    logger.info("%s %s complete: %s", NAME, "EXECUTE" if execute else "DRY-RUN", stats)
    return stats


def main():
    refuse_legacy_flag()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=None, help="Scope to one project")
    parser.add_argument("--logbook-id", default=None, help="Scope to one logbook")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N logbooks (0 = all)")
    add_guard_args(parser)
    args = parser.parse_args()
    execute = check_guard(args)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if server._r2_client is None:
        server._r2_client = server._get_r2_client()
    server.db = audited(server.db, args, NAME)
    print(asyncio.run(run(server.db, execute=execute, project_id=args.project_id,
                          logbook_id=args.logbook_id, limit=args.limit)))


if __name__ == "__main__":
    main()
