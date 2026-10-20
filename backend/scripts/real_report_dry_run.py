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
import pathlib
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


def _browser():
    """A Chromium-family browser that can print a page to PDF headlessly: Edge
    (every Windows machine has it), Chrome, or Chromium."""
    cands = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def print_with_browser(html_path, pdf_path):
    """Best effort: headless Edge / Chrome prints the HTML to a PDF. Its layout
    is the browser's, not the production engine's (no page footers)."""
    exe = _browser()
    if not exe:
        return False
    try:
        subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path}", pathlib.Path(html_path).resolve().as_uri()],
                       check=True, timeout=90, capture_output=True)
    except Exception as e:
        print(f"browser print failed ({type(e).__name__}); open the HTML and use Print -> Save as PDF.")
        return False
    return os.path.exists(pdf_path)


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


async def bin_analysis(server, project):
    """Which buildings the project's DOB records belong to: the project's own
    BIN(s), then each record group by the BIN the RECORD carries (read from its
    link / fields), with sample numbers -- to decide which records are this
    site's. Read-only."""
    from lib import report_regulatory as RG
    pid = str(project.get("_id"))
    rows = await server.db.dob_logs.find({"project_id": pid, "is_deleted": {"$ne": True}}).to_list(20000)
    have = [project.get("nyc_bin"), *(project.get("additional_bins") or [])]
    lines = [f"project address: {project.get('address')}",
             f"project nyc_bin: {project.get('nyc_bin')} | additional_bins: {project.get('additional_bins') or []} | "
             f"bbl: {project.get('bbl') or project.get('nyc_bbl')}",
             f"dob_logs rows for the project: {sum(1 for _ in rows)}", ""]
    groups = {}
    for r in rows:
        key = (RG.row_bin(r) or "(no BIN readable)", str(r.get("nyc_bin") or ""), str(r.get("record_type") or ""))
        groups.setdefault(key, []).append(r)
    lines.append("record BIN | row.nyc_bin (project BIN when synced) | type | rows | sample numbers / status")
    for (rb, rn, rt), rs in sorted(groups.items()):
        from lib import wa_alerts
        sample = ", ".join(f"{wa_alerts.record_number(x) or '?'} [{wa_alerts.record_status(x) or '?'}]" for x in rs[:4])
        lines.append(f"{rb} | {rn} | {rt} | {sum(1 for _ in rs)} | {sample}")
    kept, left, unverified, inferred = RG.split_by_bin(rows, [b for b in have if b])
    lines += ["", f"with the project's BIN(s) {[b for b in have if b]}: kept {sum(1 for _ in kept)}, "
              f"excluded {sum(1 for _ in left)}, BIN unreadable {unverified}; BINs inferred as part of the site "
              f"(their jobs also appear under the project's BIN): {inferred}"]
    return "\n".join(lines) + "\n"


def _soda_get(dataset, params):
    import urllib.parse
    import urllib.request
    url = f"https://data.cityofnewyork.us/resource/{dataset}.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=40) as r:       # a read of public open data; nothing is sent
        return json.loads(r.read().decode("utf-8"))


async def dot_probe(server, project):
    """DOT violations and permits for the project, asked of NYC Open Data NOW
    with the same requests and the same matching the DOT sync uses, next to what
    is stored in dot_logs. Shows whether the sync would find a summons the
    report does not list (e.g. one written under a street's old name). A read."""
    from lib import dot_sync
    pk = dot_sync.project_keys(project)
    stored = await server.db.dot_logs.find({"project_id": str(project.get("_id")), "is_deleted": {"$ne": True}}).to_list(2000)
    lines = [f"project keys: {pk}",
             "stored in dot_logs: " + (", ".join(f"{x.get('record_type')} {x.get('number')} [{x.get('status')}]" for x in stored[:40]) or "none"), ""]
    for q in dot_sync.queries(pk):
        try:
            recs = await asyncio.to_thread(_soda_get, q["dataset"], q["params"])
        except Exception as e:
            lines.append(f"{q['dataset']} {q['kind']}: request failed ({type(e).__name__}: {e})")
            continue
        hits = []
        for rec in recs:
            if isinstance(rec, dict):
                how = dot_sync.match(q["kind"], pk, rec)
                if how:
                    log = dot_sync.to_log(q["kind"], rec)
                    if log:
                        hits.append(f"{log['number']} via {how} | issued {log.get('issue_date')} | status {log.get('status')} | "
                                    f"hearing {log.get('hearing_date')} | {str(log.get('description') or '')[:70]}")
        lines.append(f"{q['dataset']} {q['kind']}: {', '.join(['returned', str(len(recs))])} rows, matched {len(hits)}")
        lines += ["   " + h for h in hits]
    return "\n".join(lines) + "\n"


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
    html_path = os.path.join(out, "progress_report_real.html")
    with open(os.path.join(out, "progress_report_real.snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(got["snapshot"], f, indent=2, default=str, ensure_ascii=False)
    with open(os.path.join(out, "progress_report_real.bin_analysis.txt"), "w", encoding="utf-8") as f:
        f.write(await bin_analysis(server, project))
    print("wrote progress_report_real.bin_analysis.txt")
    with open(os.path.join(out, "progress_report_real.dot_probe.txt"), "w", encoding="utf-8") as f:
        f.write(await dot_probe(server, project))
    print("wrote progress_report_real.dot_probe.txt")
    photos = got["photos"]
    photo_lines = [f"{x.get('sub')} | {x.get('date')} | {x.get('where') or ''} | sees: {x.get('work')} | "
                   f"{x.get('caption')}" for x in photos]
    review = [f"{x['why']:<60} | {x['sub']} ({x['trade']}) | {x['date']} | {x['where']} | kind {x['kind']} | "
              f"sees {x['work']} | score {x['score']:g}" for x in got.get("photo_review") or []]
    with open(os.path.join(out, "progress_report_real.photos.txt"), "w", encoding="utf-8") as f:
        f.write("USED IN THE REPORT\n" + ("\n".join(photo_lines) if photo_lines else "no photos selected") +
                "\n\nEVERY PHOTO JUDGED (used first)\n" + ("\n".join(review) if review else "none") + "\n")
    if got["pdf"]:
        with open(pdf, "wb") as f:
            f.write(got["pdf"])
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "70", "-png", pdf, os.path.join(out, "progress_report_real")], check=True)
        else:
            print("pdftoppm is not installed: no page images (the PDF is enough).")
        print(f"wrote {pdf}")
    else:
        # No WeasyPrint (its native libraries are missing on Windows): the same
        # report as one self-contained page -- the CSS is inline and every
        # photo is embedded -- to print from a browser.
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(got["html"])
        print(f"wrote {html_path}")
        if print_with_browser(html_path, pdf):
            print(f"wrote {pdf} (printed by Edge/Chrome: browser layout, no page footers)")
        else:
            print("Open the HTML in Chrome -> Print -> Save as PDF (Margins: Default, Background graphics: ON).")
    rep = got["reports"][0]
    print(f"  period {args.start}..{args.end}; days with site activity: {rep['site']['worked']}")
    print(f"  subs: {', '.join(x['name'] for x in rep['subs']) or 'none'}")
    print("  photos:" + ("" if photo_lines else " none"))
    for line in photo_lines:
        print("   -", line)
    print(f"  schedule: {'confirmed' if rep['schedule'] else 'none'}; financials: {'provided' if rep['financials'] else 'none'}")
    reg = rep["regulatory"]
    print(f"  regulatory (project BIN(s): {reg.get('bins') or 'unknown'}):")
    for lst in ("issued", "changed", "open", "expiring"):
        for e in reg[lst]:
            print(f"   {lst:<8} {e['kind']} {e['number']} | status: {e['status']} | closed: {e['closed']} | issued {e['issued']}")
    for e in reg.get("excluded") or []:
        print(f"   EXCLUDED  {e['kind']} {e['number']} | BIN {e['bin']} | status: {e['status']} | {e['reason']}")
    print("  data notes:")
    for line in rep["data_notes"]:
        print("   -", line)
    print("  limitations:")
    for line in rep["limitations"]:
        print("   -", line)


if __name__ == "__main__":
    ARGS = parse_args(sys.argv[1:])
    DB = configure_environment()
    lock_database()                      # before the application is imported
    print(f"database: {DB} (every write is blocked in this script)")
    asyncio.run(main(ARGS))
