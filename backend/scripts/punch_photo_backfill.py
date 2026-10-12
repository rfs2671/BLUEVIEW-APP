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
project). A photo WaAPI no longer has is reported, never guessed.
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


def _r2_bytes(server, key):
    try:
        return server._r2_client.get_object(Bucket=server.R2_BUCKET_NAME, Key=key)["Body"].read()
    except Exception:
        return None


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
    fixed = missing = ok = 0
    for r in rows:
        walk = await db[punch.SESSIONS].find_one({"_id": r.get("walk_id")}) or {}
        by_key = {p.get("key"): p.get("message_id") for p in walk.get("photos") or [] if p.get("key")}
        for it in walk.get("items") or []:
            if it.get("photo_key") and it.get("message_id"):
                by_key.setdefault(it["photo_key"], it["message_id"])
        # A run stopped after the walk was updated: the item's old key is
        # found through the walk's new (-full) one.
        by_key.update({k[:-len("-full.jpg")] + ".jpg": m for k, m in list(by_key.items())
                       if k.endswith("-full.jpg") and k[:-len("-full.jpg")] + ".jpg" not in by_key})
        comp = r.get("completion") or {}
        slots = [("photo_key", r.get("photo_key"))] + \
            [(f"extra_photos.{i}", k) for i, k in enumerate(r.get("extra_photos") or [])] + \
            [("completion.photo_key", comp.get("photo_key"))]
        for field, key in slots:
            if not key:
                continue
            got = await asyncio.to_thread(_r2_bytes, server, key)
            px = server._image_px(got) if got else (0, 0)
            if got and max(px) >= server.FULL_PHOTO_MIN_PX:
                ok += 1
                continue
            mid = comp.get("message_id") if field.startswith("completion") else by_key.get(key)
            label = f"{r.get('pid')} {field} ({px[0]}x{px[1]})"
            if not mid:
                missing += 1
                print(f"  {label}: no source message on record -- left")
                continue
            img = await server.download_image({"message_id_serialized": mid, "message_id": mid})
            if not img:
                missing += 1
                print(f"  {label}: WaAPI has no original for {mid} -- left")
                continue
            w, h = server._image_px(img)
            new = full_key(key)
            fixed += 1
            print(f"  {label} -> {w}x{h}, {len(img) // 1024} KB at {new}")
            if not a.apply:
                continue
            if not await asyncio.to_thread(server._upload_to_r2, img, new, "image/jpeg"):
                print(f"    upload failed -- left")
                continue
            # The walk first, the item last (Codex review on #762): the item
            # pointing at the original is what marks this photo done, so a
            # failure in between leaves it to be redone by the next run.
            if walk:
                sets = {f"items.{i}.photo_key": new for i, it in enumerate(walk.get("items") or [])
                        if it.get("photo_key") == key}
                sets.update({f"photos.{i}.key": new for i, p in enumerate(walk.get("photos") or [])
                             if p.get("key") == key})
                if sets:
                    await db[punch.SESSIONS].update_one({"_id": walk["_id"]}, {"$set": sets})
            await db[punch.COLLECTION].update_one({"_id": r["_id"]}, {"$set": {field: new}})
    print(f"{len(rows)} item(s): {ok} photo(s) already full size, {fixed} "
          f"{'replaced' if a.apply else 'to replace'}, {missing} without an original"
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
