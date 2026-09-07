#!/usr/bin/env python3
"""Take the base64 selfie off the worker document, once R2 is proven to hold it.

DRY RUN BY DEFAULT. Writes nothing without --apply, and even then it deletes
nothing until every object it is about to orphan has been read back out of R2.

── WHY ─────────────────────────────────────────────────────────────────────

`selfie_image` is 12.9MB of base64 across 30 worker documents and NOTHING READS
IT -- not a screen, not an endpoint, not checkin.html. Every reference in the
codebase is the write path, the unserved-sort sweeper, or a test. 26 of the 30
rows also carry `selfie_r2_url`: the object is already in object storage and the
inline copy is a second one.

It is not free. Worker documents average 848KB, and on 2026-09-03 the collection
crossed 32MB and took out `GET /workers` for the platform operator -- whose
query has no company_id and therefore had no index to serve its sort. The index
(`workers_by_name`, #464) stopped the crash. This stops it recurring at the next
threshold, and there will be one.

THE PATTERN THIS CLOSES. The R2 write path landed 2026-08-26 and the inline
write was never retired, so both stores have been running side by side ever
since. A migration that adds the new store without retiring the old leaves BOTH,
and the old one keeps costing -- the ported-fix pattern in a data shape rather
than a code shape.

── THE SAFETY RULE, WHICH IS THE WHOLE POINT OF THIS SCRIPT ────────────────

`_store_worker_selfie`'s own docstring says it:

    THE URL PROVES THE WRITE RETURNED, NOT THAT THE OBJECT IS READABLE.

So a stored `selfie_r2_url` is NOT evidence the bytes survive. Every object is
HEADed and confirmed non-empty before anything is unset, and

    ANY FAILED HEAD ABORTS THE WHOLE RUN. Nothing is unset, including the rows
    that verified. Skipping a bad row and stripping the rest would leave the
    operator with a partial migration and no way to tell which half ran.

This is a delete of the ONLY copy of a photograph attached to a compliance
record. It gets the pessimistic version of every choice.

── THE STORED KEY IS USED, NEVER A RECOMPUTED ONE ──────────────────────────

`selfie_r2_key` is read verbatim off the row. Recomputing it from
`_worker_selfie_r2_key(worker_id)` would silently target a different object for
any row written under an older key scheme -- and a HEAD that succeeds against
the WRONG object is worse than one that fails, because it authorises the delete.
Same rule the logbook photo merge follows.

── THE FOUR WITHOUT R2 ─────────────────────────────────────────────────────

Four rows have an inline selfie and no R2 URL at all, and for them the base64 is
THE ONLY COPY. All four were created before 2026-08-26, when the R2 path went
live; no worker created since lacks one. None carries `selfie_upload_failed`,
which is consistent with predating the path rather than with an upload having
failed.

They are UPLOADED FIRST and verified like every other row. If any upload fails,
the run aborts before the strip phase -- their photograph is not traded for a
smaller collection.

USAGE
  MONGO_URL=... DB_NAME=... python backend/scripts/strip_inline_selfies.py
  MONGO_URL=... DB_NAME=... python backend/scripts/strip_inline_selfies.py --apply

  Run under `railway run` so R2_* and MONGO_URL come from the deployed
  environment. The dry run performs every READ the real run does, including the
  HEADs, so what it reports about readability is the same answer --apply would
  get.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("JWT_SECRET", "migration")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402  (brings the R2 client, key scheme and decoder)
from pymongo import MongoClient  # noqa: E402

FIELD = "selfie_image"


def _wire_r2() -> bool:
    """Build the R2 client this process will use, and say whether it exists.

    `server._r2_client` IS `None` IN ANY SCRIPT. It is assigned in
    `startup_event`, which only runs under the ASGI server -- so a migration
    that imports `server` and reads that global sees no client and concludes
    R2 is unconfigured, in an environment where all five R2_* variables are
    set. That happened on this script's first dry run: 26 of 26 HEADs reported
    "R2 is not configured".

    IT ABORTED, WHICH IS THE ARGUMENT FOR THE ABORT RULE. Had the rule been
    "skip the rows that fail", the run would have skipped every row, stripped
    nothing, and reported a clean finish over a check that never ran -- a
    silent success on zero work, which is the shape this codebase keeps
    finding. Because any failure aborts, a misconfigured verifier looks
    exactly like unreadable objects: loud, and refusing to delete.

    `_get_r2_client()` is the app's own constructor, so the endpoint quirk
    (R2_ENDPOINT_URL carries the bucket, and keys carry the doubled segment)
    is inherited rather than re-derived.
    """
    client = server._get_r2_client()
    if client is None:
        return False
    server._r2_client = client   # so server._upload_to_r2 works in-process
    return bool(server.R2_BUCKET_NAME)


def _fmt(n: int) -> str:
    return f"{n:,}"


def _head(key: str):
    """(ok, size_or_error). NEVER raises -- the caller decides what a failure
    means, and a traceback here would abort mid-loop with rows half-checked."""
    if not key:
        return False, "no selfie_r2_key on the row"
    if not (server._r2_client and server.R2_BUCKET_NAME):
        return False, "R2 is not configured in this environment"
    try:
        meta = server._r2_client.head_object(
            Bucket=server.R2_BUCKET_NAME, Key=key)
    except Exception as e:  # noqa: BLE001 - any failure is a failure
        return False, f"{type(e).__name__}: {str(e)[:120]}"
    size = meta.get("ContentLength", 0)
    if not size:
        # A READABLE ZERO-BYTE OBJECT IS NOT A PHOTOGRAPH. It would pass a
        # "does it exist" check and authorise deleting the only real copy.
        return False, "object is 0 bytes"
    return True, size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually upload the missing four and unset the field")
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGO_URL"])[
        os.environ.get("DB_NAME", "test_database")]

    # BEFORE ANY ROW IS READ. A verifier that cannot verify must say so once,
    # at the top, rather than reporting a failure per row and burying the one
    # fact that matters.
    if not _wire_r2():
        print("ABORT: R2 is not configured in this environment "
              "(R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ENDPOINT_URL / "
              "R2_BUCKET_NAME). Nothing was read or written. Run this under "
              "`railway run` so the deployed environment supplies them.")
        return 1

    rows = list(db.workers.find({FIELD: {"$exists": True, "$ne": None}}))
    if not rows:
        print("no worker carries an inline selfie; nothing to do")
        return 0

    import bson
    def inline_bytes(w):
        return len(bson.BSON.encode({FIELD: w.get(FIELD)}))

    have_url = [w for w in rows if w.get("selfie_r2_url")]
    need_up = [w for w in rows if not w.get("selfie_r2_url")]
    total_bytes = sum(inline_bytes(w) for w in rows)

    print("=" * 72)
    print(f"MODE: {'APPLY' if args.apply else 'DRY RUN — writes nothing'}")
    print("=" * 72)
    print(f"workers with an inline {FIELD} : {len(rows)}")
    print(f"  already in R2 (has url)      : {len(have_url)}")
    print(f"  NO R2 copy — inline is ALL   : {len(need_up)}")
    print(f"inline bytes on the documents  : {_fmt(total_bytes)}")
    st = db.command("collstats", "workers")
    print(f"collection now                 : {_fmt(st['size'])} bytes, "
          f"avg {_fmt(st['avgObjSize'])}")
    print(f"collection after this strip    : ~{_fmt(st['size'] - total_bytes)} "
          f"bytes, avg ~{_fmt((st['size'] - total_bytes) // max(1, st['count']))}")
    print()

    # ── PHASE 1: the rows whose only copy is inline ────────────────────────
    print(f"--- PHASE 1: upload the {len(need_up)} row(s) with no R2 copy ---")
    uploaded = []
    for w in need_up:
        name = str(w.get("name"))[:26]
        size = inline_bytes(w)
        if not args.apply:
            print(f"  WOULD UPLOAD  {name:28s} {_fmt(size):>12s} b  "
                  f"key={server._worker_selfie_r2_key(str(w['_id']))}")
            continue
        raw = server._decode_image_data_url(w.get(FIELD))
        if not raw:
            print(f"  ABORT: {name} — inline selfie is not decodable base64. "
                  "Nothing has been written or unset.")
            return 1
        key = server._worker_selfie_r2_key(str(w["_id"]))
        try:
            url = server._upload_to_r2(raw, key, "image/jpeg")
        except Exception as e:  # noqa: BLE001
            print(f"  ABORT: {name} — upload raised {type(e).__name__}: {e}. "
                  "Nothing has been unset.")
            return 1
        if not url:
            print(f"  ABORT: {name} — upload returned no URL (R2 unconfigured?). "
                  "Nothing has been unset.")
            return 1
        db.workers.update_one({"_id": w["_id"]},
                              {"$set": {"selfie_r2_key": key,
                                        "selfie_r2_url": url}})
        w["selfie_r2_key"] = key
        uploaded.append(name)
        print(f"  uploaded      {name:28s} {_fmt(size):>12s} b  key={key}")
    print()

    # ── PHASE 2: prove every object reads back ─────────────────────────────
    print(f"--- PHASE 2: HEAD all {len(rows)} object(s) ---")
    failures = []
    verified = 0
    for w in rows:
        name = str(w.get("name"))[:26]
        # THE STORED KEY, NOT A RECOMPUTED ONE. A HEAD that succeeds against
        # the wrong object is worse than one that fails: it authorises the
        # delete.
        key = w.get("selfie_r2_key")
        if not key and not args.apply and not w.get("selfie_r2_url"):
            print(f"  would-upload  {name:28s} (no key yet — checked after upload)")
            continue
        ok, info = _head(key)
        if ok:
            verified += 1
            print(f"  ok            {name:28s} {_fmt(info):>12s} b")
        else:
            failures.append((name, key, info))
            print(f"  FAIL          {name:28s} {info}")
    print()

    if failures:
        print("=" * 72)
        print(f"ABORTED: {len(failures)} object(s) did not read back from R2.")
        print("NOTHING HAS BEEN UNSET, including the rows that verified — a")
        print("partial strip leaves no way to tell which half ran.")
        for name, key, info in failures:
            print(f"   {name:28s} key={key!r}  {info}")
        print("=" * 72)
        return 1

    # ── PHASE 3: only now, remove the inline copy ──────────────────────────
    print(f"--- PHASE 3: unset {FIELD} on {len(rows)} row(s) ---")
    if not args.apply:
        print(f"  WOULD UNSET {FIELD} on {len(rows)} worker(s), "
              f"freeing {_fmt(total_bytes)} bytes")
        print()
        print("DRY RUN COMPLETE. Nothing was written. Re-run with --apply.")
        return 0

    res = db.workers.update_many(
        {"_id": {"$in": [w["_id"] for w in rows]}},
        {"$unset": {FIELD: ""}})
    print(f"  unset on {res.modified_count} worker(s)")
    st2 = db.command("collstats", "workers")
    print()
    print("=" * 72)
    print(f"DONE. uploaded={len(uploaded)} verified={verified} "
          f"stripped={res.modified_count}")
    print(f"collection: {_fmt(st['size'])} -> {_fmt(st2['size'])} bytes")
    print(f"avg doc   : {_fmt(st['avgObjSize'])} -> {_fmt(st2['avgObjSize'])} bytes")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
