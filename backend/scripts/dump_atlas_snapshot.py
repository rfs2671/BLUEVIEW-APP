"""PR #15B.1 — production helper for dumping Atlas project docs
to test-fixture snapshot files.

Usage (via railway run from operator machine):
  railway run python backend/scripts/dump_atlas_snapshot.py \
      menahan=69e7c10013506cc459fcd046 \
      boyland=69f90c3209947c4967c8074f \
      [...]

Each arg has format ``name=<object_id_hex>``. Output JSON is written
to /tmp/atlas_snapshots/{name}_{id_short}.json using bson.json_util
(preserves ObjectId + datetime as extended JSON).

Operator then runs scripts/download_atlas_snapshots.sh to copy the
files from /tmp on the Railway container to the local
backend/tests/fixtures/atlas_snapshots/ directory.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from bson import ObjectId, json_util
from motor.motor_asyncio import AsyncIOMotorClient


OUTDIR = Path("/tmp/atlas_snapshots")


async def main(targets: list[tuple[str, str]]) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    OUTDIR.mkdir(parents=True, exist_ok=True)

    for name, oid_hex in targets:
        doc = await db.projects.find_one({"_id": ObjectId(oid_hex)})
        if doc is None:
            print(f"  {name}: NOT FOUND (oid={oid_hex})")
            continue
        out_path = OUTDIR / f"{name}_{oid_hex[:8]}.json"
        out_path.write_text(json_util.dumps(doc, indent=2),
                            encoding="utf-8")
        print(f"  {name}: wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: dump_atlas_snapshot.py name1=<oid1> [name2=<oid2> ...]")
        sys.exit(1)
    parsed: list[tuple[str, str]] = []
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"  malformed arg: {arg!r} (expected name=oid)")
            sys.exit(2)
        n, _, oid = arg.partition("=")
        parsed.append((n, oid))
    asyncio.run(main(parsed))
