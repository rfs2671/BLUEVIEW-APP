"""Score the DM assistant on its REAL answers. READ-ONLY.

    railway run python scripts/dm_eval.py --days 30
    railway run python scripts/dm_eval.py --days 30 --json /tmp/dm_eval.json --sample /tmp/dm_review.csv
    python scripts/dm_eval.py --from-file answers.jsonl         # offline, no database

Reads whatsapp_dm_answers (every DM answer since the log began, 2026-10-09,
with the path that produced it) and prints how often the assistant sounds
like a template: canned shapes, the same answer to different questions,
people asking again, fallbacks, long answers. See lib/dm_eval.py.

--sample writes up to --sample-size rows, spread across paths, for a person
to label (sounds human 1-5, answered the question y/n). --export writes the
scrubbed rows as JSONL so the scoring can be re-run with no database.

Nothing is written to the database. Every string printed or written is
scrubbed of phone numbers, links and email addresses; user, company and
project ids are not exported.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from lib import dm_eval  # noqa: E402

_FIELDS = ("path", "fallback", "reason", "question", "answer", "created_at")


def _row_out(r: dict, key: str) -> dict:
    """The exportable row: scrubbed text, an opaque per-run user key, no ids."""
    t = dm_eval._ts(r.get("created_at"))
    return {
        "user": key,
        "path": r.get("path") or "",
        "fallback": bool(r.get("fallback")),
        "reason": r.get("reason") or "",
        "question": dm_eval.scrub(r.get("question")),
        "answer": dm_eval.scrub(r.get("answer")),
        "created_at": t.isoformat() if t else "",
    }


def anonymise(rows) -> list:
    """Scrubbed rows with user ids replaced by u1, u2 … (stable within a run)."""
    keys, out = {}, []
    for r in rows:
        uid = str(r.get("user_id") or r.get("user") or "")
        k = keys.setdefault(uid, f"u{len(keys) + 1}") if uid else ""
        row = _row_out(r, k)
        row["user_id"] = k
        out.append(row)
    return out


async def _live_rows(days: int, limit: int) -> list:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`, or use --from-file.")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    proj = {f: 1 for f in _FIELDS} | {"user_id": 1, "_id": 0}
    cur = db.whatsapp_dm_answers.find({"created_at": {"$gte": since}}, proj) \
        .sort("created_at", 1).limit(limit)
    return [r async for r in cur]


def _file_rows(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--from-file", help="score a JSONL export instead of the database")
    ap.add_argument("--json", help="write the report as JSON")
    ap.add_argument("--sample", help="write a CSV of rows to label")
    ap.add_argument("--sample-size", type=int, default=200)
    ap.add_argument("--export", help="write the scrubbed rows as JSONL")
    a = ap.parse_args(argv)

    raw = _file_rows(a.from_file) if a.from_file else asyncio.run(_live_rows(a.days, a.limit))
    rows = anonymise(raw)
    report = dm_eval.score(rows)
    print(dm_eval.render(report))

    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if a.export:
        with open(a.export, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if a.sample:
        sample = dm_eval.review_sample(rows, a.sample_size)
        with open(a.sample, "w", encoding="utf-8", newline="") as f:
            if sample:
                w = csv.DictWriter(f, fieldnames=list(sample[0]))
                w.writeheader()
                w.writerows(sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
