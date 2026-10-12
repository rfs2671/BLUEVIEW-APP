"""What happened to a punch item's photos. READ-ONLY.

    railway run python scripts/punch_photo_diag.py --pid P-588-4
    railway run python scripts/punch_photo_diag.py --project <id>

For each item: the R2 key it holds and whether that object is there (its
size in pixels and KB), whether it is the original or WhatsApp's preview, and
how it was had when it came in (server._punch_store_photo's record): from
WhatsApp's CDN, from WaAPI, or only the webhook's preview -- with what the
CDN and each WaAPI try answered. Then the same for its completion photo.
Whether the walk kept the message's media reference (to fetch it again) is
said yes / no; its values (keys, paths) are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def photo_lines(server, label: str, key, quality, record) -> list:
    out = [f"  {label}: " + (f"R2 key {key}" if key else "NO photo key")]
    if key:
        got = server._r2_bytes(key)
        if got:
            w, h = server._image_px(got)
            out.append(f"    in R2: {w}x{h}, {len(got) // 1024} KB "
                       f"({'full size' if max(w, h) >= server.FULL_PHOTO_MIN_PX else 'PREVIEW size'})")
        else:
            out.append("    in R2: NOT FOUND")
        out.append(f"    quality on record: {quality or 'none (not yet checked)'}")
    rec = record or {}
    if rec:
        out.append(f"    captured from: {rec.get('source') or 'nothing'}"
                   + (f", {rec['px'][0]}x{rec['px'][1]}" if rec.get("px") else "")
                   + (f", {rec['kb']} KB" if rec.get("kb") else ""))
        out.append(f"    WhatsApp CDN: {rec.get('cdn') or 'not tried'}")
        for i, w in enumerate(rec.get("waapi") or [], 1):
            out.append(f"    WaAPI try {i}: {w}")
        if rec.get("r2"):
            out.append(f"    R2: {rec['r2']}")
    else:
        out.append("    capture record: none (stored before the record was kept)")
    return out


async def main_async(a, db=None, server=None) -> int:
    from lib import punch
    if server is None:
        import server
    if db is None:
        db = server.db
    q = {"pid": {"$in": a.pid}} if a.pid else {}
    if a.project:
        q["project_id"] = a.project
    rows = await db[punch.COLLECTION].find(q).to_list(500)
    for r in sorted(rows, key=lambda r: (str(r.get("project_id")), r.get("seq") or 0)):
        print(f"{r.get('pid')} ({r.get('status')}) “{str(r.get('text') or '')[:60]}”")
        for line in photo_lines(server, "photo", r.get("photo_key"), r.get("photo_quality"),
                                r.get("photo_capture")):
            print(line)
        print(f"    media reference kept: {'yes' if r.get('media_ref') else 'no'}")
        for i, (k, q) in enumerate(zip(r.get("extra_photos") or [], punch.extra_qualities(r)), 2):
            for line in photo_lines(server, f"photo {i} (merged in)", k, q, None):
                print(line)
        comp = r.get("completion") or {}
        if comp:
            for line in photo_lines(server, "done photo", comp.get("photo_key"),
                                    comp.get("photo_quality"), comp.get("photo_capture")):
                print(line)
            if comp.get("photo_key"):
                print(f"    media reference kept: {'yes' if comp.get('media_ref') else 'no'}")
    return 0


def main(argv=None, db=None, server=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", action="append", default=[], help="P-588-4 (repeat)")
    ap.add_argument("--project", default="")
    return asyncio.run(main_async(ap.parse_args(argv), db, server))


if __name__ == "__main__":
    sys.exit(main())
