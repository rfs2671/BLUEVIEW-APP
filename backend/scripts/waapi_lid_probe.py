"""READ-ONLY probe: what WaAPI's "get contact LID and phone" returns for one
WhatsApp id. Sends nothing to anyone; writes nothing anywhere.

macOS / Linux (from backend/):
    railway run python scripts/waapi_lid_probe.py 84894491394148@lid

Windows (PowerShell, from backend\\):
    railway run python scripts\\waapi_lid_probe.py 84894491394148@lid

Options:
    --action NAME   the WaAPI client action (default: $WAAPI_LID_ACTION or
                    get-contact-lid-and-phone)
    --key NAME      the body field holding the id (default: contactId)

Prints the HTTP status, the raw JSON, and the phone the server's parser
(lib/wa_mention.phone_from_lookup) reads from it -- the number shown in full
here because you asked for it on your own terminal; the app never shows it.
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

DEFAULT_ACTION = os.environ.get("WAAPI_LID_ACTION", "get-contact-lid-and-phone")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("contact", help="e.g. 84894491394148@lid")
    ap.add_argument("--action", default=DEFAULT_ACTION)
    ap.add_argument("--key", default="contactId")
    a = ap.parse_args(argv)
    base = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
    inst, tok = os.environ.get("WAAPI_INSTANCE_ID"), os.environ.get("WAAPI_TOKEN")
    if not (inst and tok):
        print("No WAAPI_INSTANCE_ID / WAAPI_TOKEN: run under `railway run`.")
        return 2
    from lib.server_http import ServerHttpClient
    url = f"{base}/instances/{inst}/client/action/{a.action}"

    async def call():
        async with ServerHttpClient(timeout=30) as c:
            return await c.post(url, headers={"Authorization": f"Bearer {tok}",
                                              "Content-Type": "application/json"},
                                json={a.key: a.contact})
    r = asyncio.run(call())
    print(f"POST …/client/action/{a.action}  {{{a.key}: {a.contact}}}  -> HTTP {r.status_code}")
    try:
        body = r.json()
        print(json.dumps(body, indent=2, ensure_ascii=False))
    except Exception:
        body = None
        print(r.text[:2000])
    print(f"\nphone read by the server's parser: {wa_mention.phone_from_lookup(body) or '(none)'}")
    return 0 if r.status_code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
