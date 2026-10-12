"""Punch photos stored as WhatsApp's tiny preview: fetch the original again.
DRY RUN unless --i-know (with --reason and --session: every write leaves an
audit row, scripts/prod_guard.py).

    railway run python scripts/punch_photo_backfill.py --pid P-588-1 --pid P-588-2 --pid P-588-3
    railway run python scripts/punch_photo_backfill.py --pid P-588-1 --pid P-588-2 --pid P-588-3 \
        --i-know --reason "replace the 588 punch previews with the originals" --session <id>

Live 588, Oct 12: the photos in the app were the webhook's ~100 px
jpegThumbnail, blown up. For each item photo (and extra photo, and its
completion photo) whose stored image is under server.FULL_PHOTO_MIN_PX on its
longer side: the WhatsApp message it came from (the walk's photo log), its
original through WaAPI download-media (server.download_image, which never
returns a preview), uploaded next to the old one (<key>-full.jpg) and the
item and its walk pointed at it. The old object is left (swept with the
project). A photo whose original is no longer to be had is labelled
"Original unavailable — preview only", never guessed. The same repair runs
once at startup for every photo with no quality on record
(server.punch_photo_repair); this runs it on demand.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from prod_guard import add_guard_args, audited, check_guard, refuse_legacy_flag  # noqa: E402

NAME = "punch_photo_backfill"


def full_key(key: str) -> str:
    return (key[:-4] if key.endswith(".jpg") else key) + "-full.jpg"


async def main_async(a, db=None, server=None) -> int:
    from lib import punch
    if server is None:
        import server
    if db is None:
        db = server.db
    a.apply = check_guard(a)
    db = audited(db, a, NAME)
    q = {"pid": {"$in": a.pid}} if a.pid else {}
    if a.project:
        q["project_id"] = a.project
    rows = await db[punch.COLLECTION].find(q).to_list(5000)
    got = await server.punch_photo_repair(rows, apply=a.apply, store=db, say=print)
    print(f"{len(rows)} item(s): {got['original']} photo(s) already full size, "
          f"{got['replaced']} {'replaced' if a.apply else 'to replace'}, "
          f"{got['preview_only']} without an original ({'labelled' if a.apply else 'to label'} "
          f"\"Original unavailable — preview only\"), {got['left']} left"
          + ("" if a.apply else " (dry run: nothing written; --i-know to write)"))
    return 0


def main(argv=None, db=None, server=None) -> int:
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", action="append", default=[], help="P-588-1 (repeat); default all")
    ap.add_argument("--project", default="", help="only this project id")
    add_guard_args(ap)
    return asyncio.run(main_async(ap.parse_args(argv), db, server))


if __name__ == "__main__":
    sys.exit(main())
