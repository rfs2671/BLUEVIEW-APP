#!/usr/bin/env python3
"""DOES 1024 px STILL READ THE CARD NUMBER AND THE EXPIRY.

WHY THIS IS A SCRIPT AND NOT A TEST. The question can only be answered against
REAL STORED CARDS and a REAL PROVIDER — a synthetic image proves nothing about
glare, a sleeve, a worn card or a hand-stamped date, and a mock proves nothing
at all. It needs R2 credentials and QWEN_API_KEY, which CI does not have and
must not have, so it is a command an operator runs and pastes the output of.

WHAT IT COMPARES. For each of N stored cards under `worker-osha-cards/`, it
sends the SAME image twice through the SAME prompt the gate uses:

    full size   exactly the bytes in R2
    downscaled  server._downscale_card_for_vision, i.e. what the gate now sends

and diffs the two extractions field by field, CALLING OUT `sst_number` and
`expiration` — the two fields the compliance gates read, and the two a resize
would lose first. Everything else is reported but is not a verdict.

IT NEVER WRITES. No worker row, no check-in, no certification, no vision-meter
count. It reads R2 and calls the model; that is all.

    cd backend
    python scripts/verify_card_downscale.py --limit 10

    # a specific bound, to answer "does 1280 fix a card 1024 lost"
    OSHA_VISION_MAX_EDGE=1280 python scripts/verify_card_downscale.py --limit 10

EXIT CODE IS THE ANSWER: 0 when every card agreed on card number and expiry,
1 when any card lost either. Read the status, not the prose.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRITICAL = ("sst_number", "expiration")
ALSO_REPORTED = ("name", "card_type", "card_class", "issued", "card_dominant_color")


def _norm(v):
    """Compare like a person would: case and spacing are not a difference."""
    if v is None:
        return None
    return "".join(str(v).split()).upper()


async def _read(server, image_b64: str, label: str):
    """One extraction. Returns (payload_or_None, seconds, error)."""
    from lib.server_http import ServerHttpClient
    t0 = time.perf_counter()
    try:
        async with ServerHttpClient(timeout=120.0) as http:
            resp = await http.post(
                f"{server.QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {server.QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": server.QWEN_MODEL,
                    "max_tokens": 500,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                            {"type": "text", "text": server._OSHA_EXTRACTION_PROMPT},
                        ],
                    }],
                },
            )
        dt = time.perf_counter() - t0
        if resp.status_code != 200:
            return None, dt, f"HTTP {resp.status_code}: {(resp.text or '')[:160]}"
        text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return None, dt, f"{label}: model did not return an object"
        return server._osha_ocr_payload(obj), dt, None
    except Exception as exc:                                    # noqa: BLE001
        # %r. str() on an httpx timeout is the empty string; see server.py.
        return None, time.perf_counter() - t0, repr(exc)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--prefix", default="worker-osha-cards/")
    args = ap.parse_args()

    import server

    if not server.QWEN_API_KEY:
        print("QWEN_API_KEY is not set — cannot ask the provider anything.")
        return 2
    if not (server._r2_client and server.R2_BUCKET_NAME):
        print("R2 is not configured — cannot read stored cards.")
        return 2

    bound = server._osha_vision_max_edge()
    print(f"model={server.QWEN_MODEL} base={server.QWEN_API_BASE} "
          f"max_edge={bound}")
    print(f"listing up to {args.limit} cards under {args.prefix}\n")

    paginator = server._r2_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=server.R2_BUCKET_NAME, Prefix=args.prefix):
        for item in page.get("Contents", []):
            if item["Key"].lower().endswith((".jpg", ".jpeg", ".png")):
                keys.append(item["Key"])
            if len(keys) >= args.limit:
                break
        if len(keys) >= args.limit:
            break

    if not keys:
        print("no stored cards found — nothing to verify.")
        return 2

    losses = 0
    for n, key in enumerate(keys, 1):
        obj = server._r2_client.get_object(Bucket=server.R2_BUCKET_NAME, Key=key)
        raw = obj["Body"].read()
        full_b64 = base64.b64encode(raw).decode("ascii")
        small_b64, _ct, meta = server._downscale_card_for_vision(full_b64)

        full, t_full, e_full = await _read(server, full_b64, "full")
        small, t_small, e_small = await _read(server, small_b64, "downscaled")

        print(f"[{n}/{len(keys)}] {key}")
        print(f"    {meta.get('size_in')} {meta.get('bytes_in')} B  ->  "
              f"{meta.get('size_out')} {meta.get('bytes_out')} B")
        print(f"    full {t_full:.2f}s   downscaled {t_small:.2f}s")
        if e_full or e_small:
            print(f"    INCONCLUSIVE full={e_full!r} small={e_small!r}")
            losses += 1
            continue

        card_lost = False
        for field in CRITICAL:
            a, b = getattr(full, field), getattr(small, field)
            same = _norm(a) == _norm(b)
            print(f"    {'OK ' if same else 'LOST'} {field}: {a!r} -> {b!r}")
            if not same:
                card_lost = True
        for field in ALSO_REPORTED:
            a, b = getattr(full, field), getattr(small, field)
            if _norm(a) != _norm(b):
                print(f"    (differs, not a verdict) {field}: {a!r} -> {b!r}")
        if card_lost:
            losses += 1
        print()

    print(f"{len(keys)} cards compared at max_edge={bound}: "
          f"{len(keys) - losses} agreed on card number and expiry, {losses} did not.")
    if losses:
        print("RAISE OSHA_VISION_MAX_EDGE and run this again before shipping "
              "the current bound.")
    return 1 if losses else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
