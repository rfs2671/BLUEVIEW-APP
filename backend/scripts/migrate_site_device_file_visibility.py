"""One-shot migration — turn FOLDER selections into explicit FILE selections.

Why this exists
───────────────
Site-device visibility used to be a list of top-level folder NAMES on the
project document (`project.site_device_subfolders`), and a file was published
to a gate tablet iff its Dropbox path sat under one of them
(`_path_is_under_allowed_subfolder`). That meant a Dropbox sync could publish a
drawing to a tablet an inspector reads without anyone having looked at it.

The operator's ruling: per-file selection REPLACES the folder model. Nothing
reaches that tablet without someone choosing it. Visibility now lives on the
`project_files` row as `site_visible: bool`, and the request path no longer
reads `site_device_subfolders` at all.

THIS SCRIPT IS THE HANDOVER. It must set `site_visible` so that every tablet
sees EXACTLY the files it saw the day before — no more, no fewer. So it does
not re-derive intent; it replays the OLD predicate, byte for byte, and writes
down the answer. The predicate is copied in below rather than imported,
because it no longer exists in server.py — that is the point of the change,
and a copy here is an artifact of the migration rather than a second live
model that could drift.

NOTHING IS SILENTLY DROPPED OR SILENTLY ADDED
─────────────────────────────────────────────
Every row lands in exactly one bucket, every bucket is counted, and the
buckets sum to the number of rows examined (asserted, not assumed).

  publish        the old predicate said the tablet could see it  → site_visible True
  withhold       the old predicate said it could not             → site_visible False
  direct-upload  dropbox_path == "" — see below                  → site_visible False
  already-set    the row already carries a boolean site_visible  → untouched
  REFUSE         the row cannot be classified                    → the run ABORTS

DIRECT UPLOADS ARE THE INTERESTING CASE, and they are named individually in
the output, not just counted. `POST /projects/{id}/upload-file` stores
`dropbox_path: ""`, and the old predicate returns False on an empty path in
its first line — so a directly-uploaded drawing was invisible to every tablet,
permanently, with no folder that could ever have included it. Per-file
selection is the first model that CAN publish one. Publishing them here would
be a silent ADD: nobody has ever chosen them, and the first anyone would know
is an inspector holding a drawing that was never meant to be on the tablet. So
they stay not-visible and are printed by name, for an admin to tick
deliberately on the Plans & Files screen.

A PROJECT WITH NO FOLDERS SELECTED published nothing (the endpoint's documented
"empty list locks site devices out"). Its rows are all withheld, which is the
same behaviour it has today.

REFUSAL, NOT GUESSING
─────────────────────
A row is refused — and the whole run aborts before any write — when it cannot
be classified with certainty:

  * `dropbox_path` is present but is not a string (a shape nobody planned);
  * the row's project document is missing or soft-deleted, so there is no
    folder list and no folder path to replay the predicate against;
  * the row already carries a `site_visible` that is not a bool.

Aborting is deliberate. Half a migration over a visibility control leaves some
tablets on the new model and some on nothing, and the difference is invisible
until an inspector is holding one.

Idempotent: re-runs skip rows that already carry a boolean `site_visible`, so a
second `--execute` is a no-op and an admin's own choices made between runs are
never overwritten.

Run modes
─────────
    # Dry-run — print and count what WOULD be set. No writes. The default.
    python backend/scripts/migrate_site_device_file_visibility.py

    # Live — perform the $set updates.
    python backend/scripts/migrate_site_device_file_visibility.py --execute

    # Narrow to one project while checking the output.
    python backend/scripts/migrate_site_device_file_visibility.py --project <id>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import List

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# -----------------------------------------------------------------------------
# THE OLD PREDICATE, COPIED VERBATIM from server.py as it stood at the commit
# before per-file visibility. Do not "improve" it: its job is to reproduce the
# exact set of files each tablet could see, including any quirk. The one that
# matters is the first line -- an empty file_path is False, which is why every
# direct upload was invisible.
# -----------------------------------------------------------------------------

def _normalize_subfolder_names(names: List[str]) -> List[str]:
    seen_lower = set()
    out = []
    for raw in names or []:
        if not isinstance(raw, str):
            continue
        n = raw.strip().strip("/").strip()
        if not n:
            continue
        low = n.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        out.append(n)
    return out


def _path_is_under_allowed_subfolder(
    file_path: str, folder_path: str, allowed_subfolders: List[str]
) -> bool:
    if not file_path or not allowed_subfolders:
        return False
    fp = file_path.lower()
    base = (folder_path or "").lower().rstrip("/")
    rel = fp[len(base):] if base and fp.startswith(base) else fp
    rel = rel.lstrip("/")
    for sub in allowed_subfolders:
        sub_low = sub.lower().strip("/").strip()
        if not sub_low:
            continue
        if rel == sub_low or rel.startswith(sub_low + "/"):
            return True
    return False


# --------------------------------------------------------------------------- #

PUBLISH = "publish"
WITHHOLD = "withhold"
DIRECT = "direct-upload"
ALREADY = "already-set"


class Refusal(Exception):
    """One unclassifiable row aborts the run before anything is written."""


def classify(rec: dict, project: dict | None) -> str:
    """Return the bucket for one project_files row, or raise Refusal.

    Kept pure and free of I/O so the decision is testable without a database.
    """
    existing = rec.get("site_visible")
    if existing is not None:
        if not isinstance(existing, bool):
            raise Refusal(
                f"site_visible is {type(existing).__name__} "
                f"{existing!r}, not a bool"
            )
        return ALREADY

    if not project:
        raise Refusal(
            "no project document -- cannot replay the folder rule for this row"
        )

    path = rec.get("dropbox_path", "")
    if not isinstance(path, str):
        raise Refusal(f"dropbox_path is {type(path).__name__}, not a string")

    if path == "":
        # Never publishable under the old model, so publishing it now would be
        # an ADD nobody made. Withheld and NAMED in the report.
        return DIRECT

    allowed = _normalize_subfolder_names(project.get("site_device_subfolders") or [])
    folder = project.get("dropbox_folder_path") or ""
    return PUBLISH if _path_is_under_allowed_subfolder(path, folder, allowed) else WITHHOLD


async def run(execute: bool, only_project: str | None) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set.")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    file_query: dict = {"is_deleted": {"$ne": True}}
    if only_project:
        file_query["project_id"] = only_project

    rows = await db.project_files.find(file_query).to_list(None)

    # Projects are fetched once each and cached; project_id on a file row is a
    # string, and projects are keyed by either a string _id or an ObjectId
    # depending on when they were created -- both shapes are tried before a row
    # is refused for a missing project.
    from bson import ObjectId
    project_cache: dict = {}

    async def project_for(pid):
        if pid in project_cache:
            return project_cache[pid]
        doc = await db.projects.find_one({"_id": pid, "is_deleted": {"$ne": True}})
        if not doc:
            try:
                doc = await db.projects.find_one(
                    {"_id": ObjectId(str(pid)), "is_deleted": {"$ne": True}}
                )
            except Exception:
                doc = None
        project_cache[pid] = doc
        return doc

    buckets: dict = defaultdict(list)
    refusals: list = []

    for rec in rows:
        pid = rec.get("project_id")
        project = await project_for(pid)
        try:
            buckets[classify(rec, project)].append((rec, project))
        except Refusal as exc:
            refusals.append((rec, str(exc)))

    print("=" * 72)
    print("SITE-DEVICE VISIBILITY -- folder selections -> explicit file selections")
    print(f"mode: {'EXECUTE (writes)' if execute else 'DRY RUN (no writes)'}")
    if only_project:
        print(f"scope: project {only_project}")
    print("=" * 72)
    print(f"project_files rows examined : {len(rows)}")
    print("")
    print(f"  publish        -> site_visible=True   : {len(buckets[PUBLISH])}")
    print(f"  withhold       -> site_visible=False  : {len(buckets[WITHHOLD])}")
    print(f"  direct-upload  -> site_visible=False  : {len(buckets[DIRECT])}")
    print(f"  already-set    -> untouched           : {len(buckets[ALREADY])}")
    print(f"  REFUSED        -> run aborts          : {len(refusals)}")

    total = sum(len(v) for v in buckets.values()) + len(refusals)
    print("")
    print(f"  buckets sum to {total} of {len(rows)} rows examined")
    if total != len(rows):
        print("  MISMATCH -- a row went uncounted. Refusing to write.")
        client.close()
        return 2

    # Per-project breakdown, so an operator can see the shape of what each
    # tablet is about to be handed rather than one global number.
    per_project: dict = defaultdict(lambda: defaultdict(int))
    for bucket, items in buckets.items():
        for rec, _ in items:
            per_project[rec.get("project_id")][bucket] += 1
    if per_project:
        print("")
        print("per project (publish / withhold / direct / already-set):")
        for pid in sorted(per_project, key=lambda x: str(x)):
            b = per_project[pid]
            proj = project_cache.get(pid) or {}
            folders = _normalize_subfolder_names(
                proj.get("site_device_subfolders") or [])
            print(
                f"  {str(pid):<26} "
                f"{b[PUBLISH]:>4} / {b[WITHHOLD]:>4} / {b[DIRECT]:>4} / {b[ALREADY]:>4}"
                f"   folders was: {folders or '(none -- saw nothing)'}"
            )

    # THE FILES THE OLD MODEL COULD NEVER PUBLISH. Named, not just counted:
    # each one is a drawing an admin may want on the tablet and has never been
    # able to put there, and a bare count would not tell them which.
    if buckets[DIRECT]:
        print("")
        print(f"direct uploads left NOT visible ({len(buckets[DIRECT])}) --")
        print("  no folder could ever have published these, so publishing them")
        print("  here would be a choice nobody made. Tick them on Plans & Files.")
        for rec, _ in sorted(buckets[DIRECT], key=lambda r: str(r[0].get("name"))):
            print(f"    {rec.get('project_id')}  {rec.get('name')!r}  id={rec.get('_id')}")

    if refusals:
        print("")
        print(f"REFUSED -- {len(refusals)} row(s) could not be classified.")
        print("NOTHING WAS WRITTEN. Resolve these, then re-run.")
        for rec, why in refusals:
            print(f"    id={rec.get('_id')} project={rec.get('project_id')} "
                  f"name={rec.get('name')!r}: {why}")
        client.close()
        return 1

    to_true = [rec["_id"] for rec, _ in buckets[PUBLISH]]
    to_false = [rec["_id"] for rec, _ in buckets[WITHHOLD] + buckets[DIRECT]]

    if not execute:
        print("")
        print(f"DRY RUN -- would set site_visible=True on {len(to_true)} row(s) "
              f"and False on {len(to_false)} row(s).")
        print("Re-run with --execute to apply.")
        client.close()
        return 0

    wrote_true = wrote_false = 0
    if to_true:
        res = await db.project_files.update_many(
            {"_id": {"$in": to_true}}, {"$set": {"site_visible": True}})
        wrote_true = res.modified_count
    if to_false:
        res = await db.project_files.update_many(
            {"_id": {"$in": to_false}}, {"$set": {"site_visible": False}})
        wrote_false = res.modified_count

    print("")
    print(f"EXECUTED -- site_visible=True on {wrote_true} row(s), "
          f"False on {wrote_false} row(s).")
    if wrote_true != len(to_true) or wrote_false != len(to_false):
        print("  NOTE: modified_count differs from the planned count. A row "
              "already holding the target value reports 0 modified; that is "
              "expected on a re-run and nothing else changed.")
    client.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true",
                    help="perform the writes (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op flag; the default is already a dry run")
    ap.add_argument("--project", default=None,
                    help="limit to a single project_id")
    args = ap.parse_args()
    if args.execute and args.dry_run:
        print("--execute and --dry-run are mutually exclusive.")
        return 2
    return asyncio.run(run(execute=args.execute, only_project=args.project))


if __name__ == "__main__":
    raise SystemExit(main())
