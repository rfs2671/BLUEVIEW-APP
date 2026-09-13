"""RE-CAPTURE THE BASELINE WITH AN INSTRUMENT THAT CAN SEE IMAGES.

The first corpus was gathered with a `visible()` that tokenised the image
source and then stripped the tag it lived in, so the token never survived. Any
comparison built on it was blind to every signature on the page.

FIVE OF THE SIX TYPES ARE STILL BRANCH-RENDERED, so their old output is still
recoverable. `daily_jobsite` is not: it converted, and its branch is deleted.
This also measures exactly what that costs.
"""
import asyncio
import base64
import collections
import gzip
import hashlib
import html as _h
import json
import re
import sys

sys.path.insert(0, "/app/backend")
import server
from lib import legal_render

if server._r2_client is None:
    server._r2_client = server._get_r2_client()


def visible(html):
    """The repaired one. Tokens first, as text, before any tag is stripped."""
    s = re.sub(r"<img\b[^>]*>", " [IMAGE] ", html, flags=re.I)
    s = re.sub(r"<svg\b.*?</svg>", " [INK] ", s, flags=re.S | re.I)
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _h.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


async def main():
    types = [t["key"] for t in server.LOGBOOK_TYPE_REGISTRY]
    todo = [t for t in types if t not in legal_render.CONVERTED_TYPES]
    out = {}
    print("== RE-CAPTURE (branch still the renderer) ==", file=sys.stderr)
    for t in todo:
        recs = await server.db.logbooks.find({
            "log_type": t, "is_deleted": {"$ne": True}}).to_list(2000)
        if not recs:
            continue
        rows = {}
        img = ink = withany = 0
        for r in recs:
            text = visible(await server.generate_single_logbook_html(r))
            ni, nk = text.count("[IMAGE]"), text.count("[INK]")
            img += ni
            ink += nk
            withany += 1 if (ni or nk) else 0
            rows[str(r.get("_id"))] = {
                "date": str(r.get("date") or ""),
                "status": str(r.get("status") or ""),
                "images": ni, "ink": nk, "text": text,
                "sha": hashlib.sha256(text.encode()).hexdigest()[:16]}
        out[t] = rows
        print(f"  {t:28} {len(rows):>4} records  {img:>5} images  {ink:>4} ink"
              f"  {withany:>4} records carrying either", file=sys.stderr)

    # ── WHAT THE SPENT BASELINE COSTS, MEASURED ────────────────────────
    print("\n== daily_jobsite: its branch output is unrecoverable ==",
          file=sys.stderr)
    dj = await server.db.logbooks.find({
        "log_type": "daily_jobsite", "is_deleted": {"$ne": True}}).to_list(2000)
    now_img = now_ink = now_any = 0
    sig_shape = collections.Counter()
    for r in dj:
        text = visible(await server.generate_single_logbook_html(r))
        ni, nk = text.count("[IMAGE]"), text.count("[INK]")
        now_img += ni
        now_ink += nk
        now_any += 1 if (ni or nk) else 0
        s = r.get("cp_signature")
        if not s:
            sig_shape["no mark"] += 1
        elif isinstance(s, dict) and s.get("paths"):
            sig_shape["vector strokes"] += 1
        elif isinstance(s, dict) and s.get("data"):
            sig_shape["raster"] += 1
        elif isinstance(s, str):
            sig_shape["bare string"] += 1
        else:
            sig_shape["object, nothing drawable"] += 1
    print(f"  records:                     {len(dj)}", file=sys.stderr)
    print(f"  carrying an image or ink NOW: {now_any}"
          f"  ({now_img} images, {now_ink} ink)", file=sys.stderr)
    print(f"  cp_signature shapes: {dict(sig_shape)}", file=sys.stderr)

    blob = json.dumps(out, sort_keys=True)
    print(f"\n{len(blob)} bytes", file=sys.stderr)
    print(base64.b64encode(gzip.compress(blob.encode())).decode())


asyncio.new_event_loop().run_until_complete(main())
