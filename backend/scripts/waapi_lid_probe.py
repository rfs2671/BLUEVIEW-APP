"""READ-ONLY probe: what WaAPI's get-lid returns for one or more WhatsApp
ids. Sends nothing to anyone; writes nothing anywhere.

macOS / Linux (from backend/):
    railway run python scripts/waapi_lid_probe.py 84894491394148@lid [more ids …]

Windows (PowerShell, from backend\\):
    railway run python scripts\\waapi_lid_probe.py 84894491394148@lid

POST …/client/action/get-lid  {"contactIds": [ids…]}   (works both ways:
a @lid gives its phone, a @c.us its lid). Prints the HTTP status, the raw
JSON, and what the server's parser (lib/wa_mention.phones_from_lookup)
reads from it -- numbers shown in full here because you asked on your own
terminal; the app never shows them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import wa_mention  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+", help="e.g. 84894491394148@lid")
    a = ap.parse_args(argv)
    base = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
    inst, tok = os.environ.get("WAAPI_INSTANCE_ID"), os.environ.get("WAAPI_TOKEN")
    if not (inst and tok):
        print("No WAAPI_INSTANCE_ID / WAAPI_TOKEN: run under `railway run`.")
        return 2
    from lib.server_http import ServerHttpClient
    url = f"{base}/instances/{inst}/client/action/{wa_mention.LID_ACTION}"
    body = wa_mention.lookup_body(a.ids[:wa_mention.LOOKUP_CHUNK])

    async def call():
        async with ServerHttpClient(timeout=30) as c:
            return await c.post(url, headers={"Authorization": f"Bearer {tok}",
                                              "Content-Type": "application/json"},
                                json=body)
    r = asyncio.run(call())
    print(f"POST …/client/action/{wa_mention.LID_ACTION}  {json.dumps(body)}  -> HTTP {r.status_code}")
    try:
        answer = r.json()
        print(json.dumps(answer, indent=2, ensure_ascii=False))
    except Exception:
        answer = None
        print(r.text[:2000])
    parsed = wa_mention.phones_from_lookup(answer, body["contactIds"])
    print("\nwhat the server reads:")
    if parsed is None:
        print("  (not a success: nothing learned, nothing cached)")
    else:
        for lid, number in parsed.items():
            print(f"  {lid} -> {number or 'no number (cached as such for a week)'}")
    return 0 if r.status_code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
