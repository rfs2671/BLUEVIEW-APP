"""WHAT EVERY FILED DOCUMENT SAYS TODAY, BEFORE ANY MORE BRANCHES ARE DELETED.

── THE ANSWER TO "CAN THE BRANCH BE RENDERED ALONGSIDE THE ENGINE" ───────

For the daily jobsite log and the ten other unconverted types: YES, and it is
easier now than it will ever be again, because THE BRANCH IS STILL THE
RENDERER. Nothing has to be reconstructed, checked out or patched. Running
`generate_single_logbook_html` on the deployed build today IS the old output.

That stops being true the moment a type is converted. The orientation sheet had
to be recovered from a9c48678 -- the last commit where its branch ran -- and
that only worked because the commit existed and the helpers had not moved. It
is not a repeatable plan.

So this captures the baseline for EVERY unconverted type at once, rather than
per conversion. One run, and each of the eleven conversions that follow has
something to diff against that was written before anyone had an interest in the
answer.

── VISIBLE TEXT, NOT BYTES ───────────────────────────────────────────────

The sheets are being deliberately redesigned, so a byte diff is all noise. What
may not change is what the document SAYS. Tags out, entities decoded,
whitespace collapsed, and image payloads replaced by a token -- 248 base64
photographs would otherwise be the entire artifact.

CASE IS FOLDED IN THE COMPARISON, NOT HERE. The first diff run reported the job
address missing when the engine had merely uppercased it. The stored text keeps
its case; the comparer lowercases.
"""
import asyncio
import base64
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


def visible(html: str) -> str:
    s = re.sub(r'src="[^"]*"', 'src="INK"', html)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _h.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


async def main():
    types = [t["key"] for t in server.LOGBOOK_TYPE_REGISTRY]
    todo = [t for t in types if t not in legal_render.CONVERTED_TYPES]
    print(f"types defined:     {len(types)}", file=sys.stderr)
    print(f"already converted: {sorted(legal_render.CONVERTED_TYPES)}",
          file=sys.stderr)
    print(f"to baseline:       {len(todo)}", file=sys.stderr)

    out = {}
    for t in todo:
        recs = await server.db.logbooks.find({
            "log_type": t, "is_deleted": {"$ne": True}}).to_list(2000)
        rows = {}
        for r in recs:
            try:
                text = visible(await server.generate_single_logbook_html(r))
            except Exception as e:
                text = f"!! {type(e).__name__}: {e}"
            rows[str(r.get("_id"))] = {
                "date": str(r.get("date") or ""),
                "status": str(r.get("status") or ""),
                "text": text,
                "sha": hashlib.sha256(text.encode()).hexdigest()[:16],
            }
        out[t] = rows
        bad = sum(1 for v in rows.values() if v["text"].startswith("!!"))
        print(f"  {t:28} {len(rows):>4} records"
              + (f"   {bad} FAILED TO RENDER" if bad else ""), file=sys.stderr)

    blob = json.dumps(out, sort_keys=True)
    print(f"\n{len(blob)} bytes of visible text", file=sys.stderr)
    enc = base64.b64encode(gzip.compress(blob.encode())).decode()
    print(f"{len(enc)} bytes base64", file=sys.stderr)
    print(enc)


asyncio.new_event_loop().run_until_complete(main())
