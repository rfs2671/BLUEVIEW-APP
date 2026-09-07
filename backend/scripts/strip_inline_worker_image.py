#!/usr/bin/env python3
"""Take a base64 image off the worker document, once R2 is proven to hold it.

DRY RUN BY DEFAULT. Writes nothing without --apply, and even then deletes
nothing until every object it is about to orphan has been read back out of R2
AND matched against the size of the base64 it is replacing.

ONE SCRIPT, TWO FIELDS, BECAUSE TWO COPIES OF A MIGRATION IS THE DRIFT PATTERN.
This began as `strip_inline_selfies.py`. The card needed the same run with four
strings changed, and a second copy would be two verifiers that could come to
disagree about what "verified" means -- on a job whose entire safety is the
verifier. The field-specific facts are a table; the rules are written once.

    python backend/scripts/strip_inline_worker_image.py selfie
    python backend/scripts/strip_inline_worker_image.py osha_card --apply

── WHY ─────────────────────────────────────────────────────────────────────

Worker documents averaged 848KB because two base64 images lived on the row. On
2026-09-03 the collection crossed 32MB and `GET /workers` began returning 500
for the platform operator, whose query has no company_id and so had no index to
serve its sort. #464's index stopped the crash; this stops it recurring.

    selfie_image      12.9MB / 30 rows   read by NOTHING            (done)
    osha_card_image   37.8MB / 46 rows   read by two screens

── THE SAFETY RULES ────────────────────────────────────────────────────────

1. A STORED URL IS NOT EVIDENCE. `_store_worker_selfie`'s own docstring says
   it: the URL proves the PUT returned, not that the object is readable. Every
   object is HEADed.

2. AND A HEAD IS NOT ENOUGH EITHER. It proves an object exists at that key --
   not that it is THE RIGHT OBJECT. So the size is checked against the base64
   being removed: base64 encodes 3 bytes as 4, so a faithful object is about
   three quarters of the inline payload. This was noticed by accident on the
   selfie run (268,431 inline -> 201,287 stored, a 0.02% miss) and it is a
   verification step here rather than a happy observation. It is what
   distinguishes "an object is there" from "the photograph I am about to
   delete is there".

3. A READABLE ZERO-BYTE OBJECT IS NOT A PHOTOGRAPH. It would pass an existence
   check and authorise deleting the only real copy.

4. ANY FAILURE ABORTS THE WHOLE RUN, including rows that verified. A partial
   strip leaves no way to tell which half ran. This rule earned itself on the
   selfie dry run: `server._r2_client` is assigned in `startup_event`, which a
   script never runs, so 26 of 26 HEADs reported "R2 is not configured" in an
   environment where all five R2_* variables were set. Had the rule been "skip
   the rows that fail", it would have skipped every row, stripped nothing and
   printed a clean finish -- a silent success over a check that never ran.

5. THE STORED KEY IS USED, NEVER A RECOMPUTED ONE. A HEAD that succeeds
   against the WRONG object is worse than one that fails, because it
   authorises the delete.

Rows whose base64 is the only copy are UPLOADED FIRST and verified like every
other row.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("JWT_SECRET", "migration")
os.environ.setdefault("QWEN_API_KEY", "")

import bson  # noqa: E402
import server  # noqa: E402
from pymongo import MongoClient  # noqa: E402

#: Everything that differs between the two fields. The RULES are not in here.
FIELDS = {
    "selfie": {
        "inline": "selfie_image",
        "key": "selfie_r2_key",
        "url": "selfie_r2_url",
        "keyfn": lambda wid: server._worker_selfie_r2_key(wid),
    },
    "osha_card": {
        "inline": "osha_card_image",
        "key": "osha_card_r2_key",
        "url": "osha_card_r2_url",
        "keyfn": lambda wid: server._worker_osha_card_r2_key(wid),
    },
}

#: base64 encodes 3 bytes as 4. An object materially off that ratio is not the
#: image the row is carrying. Loose enough for BSON framing and the data-URL
#: prefix, tight enough that a different photograph fails.
RATIO_LO, RATIO_HI = 0.60, 0.85


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _wire_r2() -> bool:
    """`server._r2_client` is None in any script -- it is assigned in
    `startup_event`, which only runs under the ASGI server. Built here from the
    app's own constructor so the R2 endpoint quirk is inherited, not
    re-derived."""
    client = server._get_r2_client()
    if client is None:
        return False
    server._r2_client = client
    return bool(server.R2_BUCKET_NAME)


def _verify(key: str, inline_len: int):
    """(ok, detail). Never raises: the caller decides what a failure means."""
    if not key:
        return False, "no r2 key on the row"
    try:
        meta = server._r2_client.head_object(
            Bucket=server.R2_BUCKET_NAME, Key=key)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:110]}"
    size = meta.get("ContentLength", 0)
    if not size:
        return False, "object is 0 bytes"
    ratio = size / inline_len if inline_len else 0
    if not (RATIO_LO <= ratio <= RATIO_HI):
        # RULE 2. The object exists and is the wrong size for the payload this
        # row carries, so it is not this row's photograph.
        return False, (f"size {size:,} is {ratio:.2f}x the inline "
                       f"{inline_len:,} — outside {RATIO_LO}-{RATIO_HI}")
    return True, (size, ratio)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("field", choices=sorted(FIELDS))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    F = FIELDS[args.field]
    INLINE, KEY, URL = F["inline"], F["key"], F["url"]

    db = MongoClient(os.environ["MONGO_URL"])[
        os.environ.get("DB_NAME", "test_database")]

    if not _wire_r2():
        print("ABORT: R2 is not configured in this environment. Nothing read "
              "or written. Run under `railway run`.")
        return 1

    rows = list(db.workers.find({INLINE: {"$exists": True, "$ne": None}}))
    if not rows:
        print(f"no worker carries an inline {INLINE}; nothing to do")
        return 0

    def inline_bytes(w):
        return len(bson.BSON.encode({INLINE: w.get(INLINE)}))

    need_up = [w for w in rows if not w.get(URL)]
    total = sum(inline_bytes(w) for w in rows)
    st = db.command("collstats", "workers")

    print("=" * 74)
    print(f"FIELD: {INLINE}    MODE: "
          f"{'APPLY' if args.apply else 'DRY RUN — writes nothing'}")
    print("=" * 74)
    print(f"rows with an inline copy : {len(rows)}")
    print(f"  already in R2          : {len(rows) - len(need_up)}")
    print(f"  NO R2 copy — inline is ALL : {len(need_up)}")
    print(f"inline bytes             : {_fmt(total)}")
    print(f"collection now           : {_fmt(st['size'])}  avg {_fmt(st['avgObjSize'])}")
    print(f"collection after         : ~{_fmt(st['size'] - total)}  "
          f"avg ~{_fmt((st['size'] - total) // max(1, st['count']))}")
    print()

    print(f"--- PHASE 1: upload {len(need_up)} row(s) whose only copy is inline ---")
    uploaded = 0
    for w in need_up:
        name, size = str(w.get("name"))[:26], inline_bytes(w)
        key = F["keyfn"](str(w["_id"]))
        if not args.apply:
            print(f"  WOULD UPLOAD  {name:28s} {_fmt(size):>12s} b  {key}")
            continue
        raw = server._decode_image_data_url(w.get(INLINE))
        if not raw:
            print(f"  ABORT: {name} — not decodable base64. Nothing unset.")
            return 1
        try:
            url = server._upload_to_r2(raw, key, "image/jpeg")
        except Exception as e:  # noqa: BLE001
            print(f"  ABORT: {name} — upload raised {type(e).__name__}: {e}. "
                  "Nothing unset.")
            return 1
        if not url:
            print(f"  ABORT: {name} — upload returned no URL. Nothing unset.")
            return 1
        db.workers.update_one({"_id": w["_id"]},
                              {"$set": {KEY: key, URL: url}})
        w[KEY] = key
        uploaded += 1
        print(f"  uploaded      {name:28s} {_fmt(size):>12s} b  {key}")
    print()

    print(f"--- PHASE 2: HEAD + size-check all {len(rows)} object(s) ---")
    failures, verified = [], 0
    for w in rows:
        name = str(w.get("name"))[:26]
        if not w.get(KEY) and not args.apply:
            print(f"  would-upload  {name:28s} (no key yet — checked after upload)")
            continue
        ok, detail = _verify(w.get(KEY), inline_bytes(w))
        if ok:
            size, ratio = detail
            verified += 1
            print(f"  ok            {name:28s} {_fmt(size):>12s} b  {ratio:.2f}x")
        else:
            failures.append((name, w.get(KEY), detail))
            print(f"  FAIL          {name:28s} {detail}")
    print()

    if failures:
        print("=" * 74)
        print(f"ABORTED: {len(failures)} object(s) did not verify. NOTHING HAS "
              "BEEN UNSET, including the rows that passed.")
        for name, key, why in failures:
            print(f"   {name:28s} key={key!r}  {why}")
        print("=" * 74)
        return 1

    print(f"--- PHASE 3: unset {INLINE} on {len(rows)} row(s) ---")
    if not args.apply:
        print(f"  WOULD UNSET {INLINE} on {len(rows)}, freeing {_fmt(total)} bytes")
        print("\nDRY RUN COMPLETE. Nothing written. Re-run with --apply.")
        return 0

    res = db.workers.update_many({"_id": {"$in": [w["_id"] for w in rows]}},
                                 {"$unset": {INLINE: ""}})
    st2 = db.command("collstats", "workers")
    print(f"  unset on {res.modified_count} worker(s)")
    print()
    print("=" * 74)
    print(f"DONE. uploaded={uploaded} verified={verified} "
          f"stripped={res.modified_count}")
    print(f"collection: {_fmt(st['size'])} -> {_fmt(st2['size'])}")
    print(f"avg doc   : {_fmt(st['avgObjSize'])} -> {_fmt(st2['avgObjSize'])}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
