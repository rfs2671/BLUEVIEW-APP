"""Build ONE real progress report from a real database -- no writes, no send.

    railway run python scripts\\real_report_dry_run.py 2026-10-01 2026-10-19 --project 588 [out_dir]

Reads the project's check-ins, filed daily logs (as amended), DOB/DOT records,
confirmed schedule and photos exactly as the product does
(server.build_project_report with dry_run=True), renders the PDF, and writes
it, a PNG per page (when pdftoppm is installed), the snapshot JSON and a
printed summary to out_dir (default docs/samples/real).

Connection: REAL_REPORT_MONGO_URL / REAL_REPORT_DB when set, else the
MONGO_URL / DB_NAME the environment already has (what `railway run` injects).
Photos: R2_* and QWEN_API_KEY from the environment.
Project: --project is a name / address match ("588"); the company is read from
the project's own record. --company narrows the match when two companies have
a job by that name. REAL_REPORT_PROJECT / REAL_REPORT_COMPANY_ID also work.

What it will NOT do: store a report, upload to R2, mint a link, send a message,
or write to any collection. It enforces that itself, BEFORE the application is
imported: every write method of motor and pymongo raises, and the vision meter
and verdict cache are no-ops. That is a guard in this script, not a database
permission -- a read-only database user remains the safer login. The vision
model IS called for the photo screen (the product's own spend).

Nothing is fabricated: no data, no photos, no figures. If a source cannot be
read the script stops and says which.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# Windows consoles default to a legacy code page; the report's text has
# dashes, arrows and quotes.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
           "delete_many", "bulk_write", "find_one_and_update", "find_one_and_replace",
           "find_one_and_delete", "create_index", "create_indexes", "drop_index", "drop_indexes",
           "drop", "rename", "aggregate_write")
_DB_WRITES = ("create_collection", "drop_collection")


def _refuse(name):
    def blocked(*a, **k):
        raise RuntimeError(f"dry run: {name} is not allowed")
    return blocked


def lock_database():
    """Make every write method of the drivers raise. Done BEFORE `import
    server`, so nothing the application does at import or later can write."""
    targets = []
    try:
        from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
        targets.append((AsyncIOMotorCollection, _WRITES))
        targets.append((AsyncIOMotorDatabase, _DB_WRITES))
    except Exception:
        pass
    try:
        from pymongo.collection import Collection
        from pymongo.database import Database
        targets.append((Collection, _WRITES))
        targets.append((Database, _DB_WRITES))
    except Exception:
        pass
    for cls, names in targets:
        for n in names:
            if hasattr(cls, n):
                setattr(cls, n, _refuse(n))


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Read-only dry run of the unified progress report.")
    ap.add_argument("start", help="first day, YYYY-MM-DD")
    ap.add_argument("end", help="last day, YYYY-MM-DD")
    ap.add_argument("out_dir", nargs="?", default=os.path.join(HERE, "..", "..", "docs", "samples", "real"))
    ap.add_argument("--project", default=os.environ.get("REAL_REPORT_PROJECT", ""),
                    help='job name or address to match, e.g. "588"')
    ap.add_argument("--company", default=os.environ.get("REAL_REPORT_COMPANY_ID", ""),
                    help="company id, only to narrow the match")
    a = ap.parse_intermixed_args(argv)
    if not a.project:
        ap.error("--project is required (a job name or address, e.g. 588)")
    try:
        a.start, a.end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    except ValueError:
        ap.error("dates are YYYY-MM-DD")
    if a.end < a.start:
        ap.error("end is before start")
    return a


def configure_environment():
    url = os.environ.get("REAL_REPORT_MONGO_URL") or os.environ.get("MONGO_URL")
    name = os.environ.get("REAL_REPORT_DB") or os.environ.get("DB_NAME")
    if not url or not name:
        sys.exit("No database: set MONGO_URL and DB_NAME (railway run does) or REAL_REPORT_MONGO_URL and "
                 "REAL_REPORT_DB. Nothing was read or written.")
    os.environ["MONGO_URL"], os.environ["DB_NAME"] = url, name
    os.environ.setdefault("JWT_SECRET", "dry-run-only")
    os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
    return name


async def find_project(server, needle, company):
    """The one project whose name or address contains `needle` (or whose id
    is it). Its own company_id is the company."""
    q = {"is_deleted": {"$ne": True}}
    if company:
        q["company_id"] = server._company_id_filter(company)
    rows = await server.db.projects.find(q).to_list(5000)
    pat = re.compile(re.escape(needle.strip()), re.IGNORECASE)
    hits = [p for p in rows if str(p.get("_id")) == needle.strip()
            or pat.search(str(p.get("name") or "")) or pat.search(str(p.get("address") or ""))]
    if not hits:
        sys.exit(f"No project matches '{needle}'. Nothing was built.")
    if len(hits) > 1:
        lines = [f"  {p.get('_id')}  {p.get('name') or ''} | {p.get('address') or ''} | company {p.get('company_id')}"
                 for p in hits[:10]]
        sys.exit(f"'{needle}' matches {len(hits)} projects; pass the exact id as --project "
                 f"(or narrow with --company):\n" + "\n".join(lines))
    return hits[0]


async def main(args):
    import server

    async def no_meter(*a, **k):
        return None
    server.record_vision_call = no_meter
    server._photo_verdict_cache = no_meter

    project = await find_project(server, args.project, args.company)
    company = str(project.get("company_id") or "")
    if not company:
        sys.exit("That project has no company id; nothing was built.")
    print(f"project: {project.get('name')} | {project.get('address')} | id {project.get('_id')} | company {company}")
    print(f"DOB/DOT tracking on: {bool(project.get('track_dob_status'))}")
    now = datetime.now(timezone.utc)
    got = await server.build_project_report(company, [project], args.start, args.end, now=now, by="dry-run",
                                            source="dry_run", dry_run=True)
    out = os.path.abspath(args.out_dir)
    os.makedirs(out, exist_ok=True)
    pdf = os.path.join(out, "progress_report_real.pdf")
    with open(pdf, "wb") as f:
        f.write(got["pdf"])
    with open(os.path.join(out, "progress_report_real.snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(got["snapshot"], f, indent=2, default=str, ensure_ascii=False)
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "70", "-png", pdf, os.path.join(out, "progress_report_real")], check=True)
    else:
        print("pdftoppm is not installed: no page images (the PDF is enough).")
    rep = got["reports"][0]
    print(f"wrote {pdf}")
    print(f"  period {args.start}..{args.end}; days with site activity: {rep['site']['worked']}")
    print(f"  subs: {', '.join(x['name'] for x in rep['subs']) or 'none'}")
    print(f"  photos: {'; '.join(str(x.get('sub')) + ' ' + str(x.get('date')) + ' [' + str(x.get('work')) + '] ' + str(x.get('caption')) for x in got['photos']) or 'none'}")
    print(f"  schedule: {'confirmed' if rep['schedule'] else 'none'}; financials: {'provided' if rep['financials'] else 'none'}")
    print("  limitations:")
    for line in rep["limitations"]:
        print("   -", line)


if __name__ == "__main__":
    ARGS = parse_args(sys.argv[1:])
    DB = configure_environment()
    lock_database()                      # before the application is imported
    print(f"database: {DB} (every write is blocked in this script)")
    asyncio.run(main(ARGS))
