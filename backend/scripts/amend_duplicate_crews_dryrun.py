#!/usr/bin/env python3
"""DRY RUN: fold gate-appended duplicate crews back into the CP's rows.

POSTS NOTHING. WRITES NOTHING. It reads one logbook, applies the merge rule,
and prints the resulting activities array for a human to read before any
amendment is filed.

WHY THE LOG NEEDS ONE. reconcileCrewsWithRoster short-circuited hand-added rows
before its matcher, so a gate crew for a company the CP had already typed was
appended as a SECOND row instead of merging. 2026-08-31's daily jobsite log was
submitted with eight crews where four worked, and the report's crew table
printed all eight on a compliance document.

WHY THIS IS AN AMENDMENT AND NOT AN EDIT. The log is `submitted`, and both
create_logbook and update_logbook refuse a data write on a filed record with
409 FILED_LOG_DATA_IMMUTABLE. That guard is correct and must not be bypassed
with a direct Mongo write -- the whole point of the record is that it cannot be
quietly rewritten after filing. The correction goes through
POST /api/logbooks/{id}/amend, which records it as its own act.

THE RULE, applied per company:

  * the CP's row is kept -- his work description and his photos are the
    evidence and they stay where he put them;
  * the gate row's PHOTOS are moved onto it. On 2026-08-31 C5 carries two of
    the thirteen, and dropping C5 without moving them would lose them. Their
    R2 keys travel unchanged: a key is stored per photo and read back verbatim
    (server.py _logbook_photo_sources), never recomputed from the row;
  * the gate row's COUNT is carried across as gate_num_workers, so the
    turnstile's evidence survives the merge rather than being deleted with the
    row -- which was #244's objection to merging at all;
  * the CP's own count stands in num_workers with num_workers_source 'cp' when
    he typed one; the gate's is adopted when he did not;
  * the gate row is then dropped.

A gate row whose company has NO hand-typed counterpart is left exactly as it
is. This script merges; it never deletes a crew that stands alone.

USAGE
  MONGO_URL=... DB_NAME=... python backend/scripts/amend_duplicate_crews_dryrun.py \\
      --project-name "588 Thomas" --date 2026-08-31 [--json]

  --project-name matches on the project's name OR address, case- and
  spacing-insensitively, and REFUSES to run on anything but a single match --
  it prints the candidates instead. Guessing which project a compliance
  amendment belongs to is not a thing this should do. --project <id> is still
  accepted when the id is known.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover
    print("motor is required: pip install motor", file=sys.stderr)
    raise

CP_SOURCE = "cp"
GATE_SOURCE = "gate"


def _key(value) -> str:
    """Company/trade comparison key. Mirrors rosterKey on the client."""
    return " ".join(str(value or "").strip().lower().split())


def _count(row) -> str:
    return str(row.get("num_workers") or "").strip()


def pick_project(projects, needle):
    """(project_or_None, candidates). Never guesses between two matches.

    Matches name or address on a normalised substring, so "588 Thomas" finds
    "588 Thomas St" and "588  thomas street" alike without the caller having to
    reproduce the stored punctuation.
    """
    want = _key(needle)
    if not want:
        return None, []
    hits = []
    for p in projects or []:
        hay = f"{_key(p.get('name'))} {_key(p.get('address'))}"
        if want in hay:
            hits.append(p)
    exact = [p for p in hits if _key(p.get("name")) == want]
    if len(exact) == 1:
        return exact[0], hits
    if len(hits) == 1:
        return hits[0], hits
    return None, hits


def merge_rows(activities):
    """Return (merged_activities, report_lines). Pure — no I/O, no mutation."""
    rows = [dict(a) for a in (activities or []) if isinstance(a, dict)]
    notes = []

    hand = [r for r in rows if not r.get("gate_sourced")]
    gate = [r for r in rows if r.get("gate_sourced")]

    by_company = {}
    for h in hand:
        by_company.setdefault(_key(h.get("company")), []).append(h)

    out = []
    consumed = set()

    for h in hand:
        c = _key(h.get("company"))
        # Only an UNAMBIGUOUS pairing is merged: one hand row and one gate row
        # for that company. Anything else is left alone and reported, because
        # guessing which crew a row meant is how work gets filed against the
        # wrong trade.
        mates = [i for i, g in enumerate(gate)
                 if _key(g.get("company")) == c and i not in consumed]
        if len(by_company.get(c, [])) != 1 or len(mates) != 1:
            notes.append(
                f"  LEFT ALONE  {h.get('crew_id')} {h.get('company')!r}: "
                f"{len(by_company.get(c, []))} hand row(s), {len(mates)} gate row(s) "
                f"-- not an unambiguous pair")
            out.append(h)
            continue

        gi = mates[0]
        g = gate[gi]
        consumed.add(gi)

        merged = dict(h)
        merged["gate_sourced"] = True
        merged["trade"] = h.get("trade") or g.get("trade") or ""

        cp_typed = _count(h) != ""
        merged["num_workers"] = _count(h) if cp_typed else _count(g)
        merged["num_workers_source"] = CP_SOURCE if cp_typed else GATE_SOURCE
        merged["gate_num_workers"] = _count(g)

        for field in ("worker_ids", "worker_names", "check_in_time"):
            if g.get(field) is not None:
                merged[field] = g.get(field)
        if not merged.get("subcontractor_id"):
            merged["subcontractor_id"] = g.get("subcontractor_id")

        h_photos = list(h.get("photos") or [])
        g_photos = list(g.get("photos") or [])
        merged["photos"] = h_photos + g_photos

        notes.append(
            f"  MERGED      {h.get('crew_id')} + {g.get('crew_id')} "
            f"{h.get('company')!r}: photos {len(h_photos)}+{len(g_photos)}"
            f"={len(merged['photos'])}, num_workers "
            f"{_count(h) or '(blank)'}->{merged['num_workers']} "
            f"({merged['num_workers_source']}), gate_num_workers "
            f"{merged['gate_num_workers']}")
        out.append(merged)

    for i, g in enumerate(gate):
        if i in consumed:
            continue
        notes.append(
            f"  KEPT        {g.get('crew_id')} {g.get('company')!r}: gate crew "
            f"with no hand-typed counterpart")
        out.append(g)

    return out, notes


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="project id, when it is already known")
    ap.add_argument("--project-name",
                    help='name or address, e.g. "588 Thomas"')
    ap.add_argument("--date", required=True)
    ap.add_argument("--log-type", default="daily_jobsite")
    ap.add_argument("--json", action="store_true",
                    help="print the merged activities array as JSON")
    args = ap.parse_args()

    if not args.project and not args.project_name:
        print("one of --project or --project-name is required", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    project_id = args.project
    if not project_id:
        rows = await db.projects.find(
            {"is_deleted": {"$ne": True}}, {"name": 1, "address": 1}).to_list(None)
        hit, candidates = pick_project(rows, args.project_name)
        if not hit:
            print(f"{len(candidates)} projects match {args.project_name!r}; "
                  f"re-run with --project <id>", file=sys.stderr)
            for c in candidates[:10]:
                print(f"  {c.get('_id')}  {c.get('name')!r}  "
                      f"{c.get('address')!r}", file=sys.stderr)
            return 1
        project_id = str(hit["_id"])
        print(f"project   {hit.get('name')!r}  ({project_id})")

    doc = await db.logbooks.find_one({
        "project_id": project_id,
        "log_type": args.log_type,
        "date": args.date,
        "is_deleted": {"$ne": True},
    })
    if not doc:
        print("no such logbook", file=sys.stderr)
        return 1

    acts = ((doc.get("data") or {}).get("activities")) or []
    merged, notes = merge_rows(acts)

    def photo_total(rows):
        return sum(len(r.get("photos") or []) for r in rows)

    print(f"\nlogbook   {doc.get('_id')}")
    print(f"status    {doc.get('status')}   is_locked={doc.get('is_locked')}")
    print(f"created   {doc.get('created_at')}")
    print(f"updated   {doc.get('updated_at')}")
    print(f"\nBEFORE    {len(acts)} crews, {photo_total(acts)} photos")
    for a in acts:
        print(f"  {a.get('crew_id'):<4} {str(a.get('company'))[:24]:<24} "
              f"gate_sourced={bool(a.get('gate_sourced'))!s:<5} "
              f"activity_id={a.get('activity_id') or '(none)'!s:<24} "
              f"photos={len(a.get('photos') or [])} "
              f"num_workers={a.get('num_workers')!r}")

    print("\nRULE APPLIED")
    for n in notes:
        print(n)

    print(f"\nAFTER     {len(merged)} crews, {photo_total(merged)} photos")
    for a in merged:
        print(f"  {a.get('crew_id'):<4} {str(a.get('company'))[:24]:<24} "
              f"photos={len(a.get('photos') or [])} "
              f"num_workers={a.get('num_workers')!r} "
              f"({a.get('num_workers_source')}) "
              f"gate_num_workers={a.get('gate_num_workers')!r}")

    lost = photo_total(acts) - photo_total(merged)
    print(f"\nPHOTOS {'PRESERVED' if lost == 0 else f'LOST: {lost} !!!'} "
          f"({photo_total(acts)} -> {photo_total(merged)})")
    if lost:
        print("REFUSING TO RECOMMEND THIS PAYLOAD", file=sys.stderr)
        return 2

    if args.json:
        print("\n--- activities payload ---")
        print(json.dumps(merged, indent=2, default=str))

    print("\nDRY RUN — nothing was written. File via "
          "POST /api/logbooks/{id}/amend after review.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
