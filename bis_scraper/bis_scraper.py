"""
Blueview BIS Scraper — standalone worker.

Loads the NYC DOB BIS Property Profile page for each tracked project BIN
using Playwright (real Chromium, bypasses the Akamai anti-bot gate that
blocks httpx requests). Parses the violations and complaints tables, diffs
against existing `dob_logs` records by violation/complaint number, inserts
anything new, and fires an email alert through the same throttled helper
the main server uses for any Critical record.

Runs as a separate Railway deployment — NOT inside the FastAPI server.
Own process, own long-running APScheduler, shares the production MongoDB
via MONGO_URL / DB_NAME (same credentials as the backend).

Environment variables (see README.md for required values):

    MONGO_URL               Mongo connection string (required, same as backend)
    DB_NAME                 Mongo database name (required, same as backend)
    RESEND_API_KEY          For critical-alert emails. If missing, alerts log
                            only (no email).
    WEBSHARE_PROXY_URL      Optional. Proxy URL in the form
                            http://user:pass@host:port. Falls back to direct
                            connection if unset.
    BIS_SCAN_INTERVAL_MIN   Scan cadence. Default 60.
    BIS_SCAN_CONCURRENCY    Parallel BINs per scan. Default 2. BIS is slow
                            and rate-limited; keep this low.
    BIS_DEBUG_HTML          If '1', logs a ~400-char HTML preview when a
                            table isn't found. Useful during initial
                            bring-up. Default '0'.

Deploy notes: see README.md in this directory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from bs4 import BeautifulSoup
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

try:
    import resend as _resend
except ImportError:  # pragma: no cover — resend is optional
    _resend = None


# ---------------------------------------------------------------------------
# Logging — structured enough to grep in Railway logs.
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bis_scraper] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bis_scraper")


# ---------------------------------------------------------------------------
# Config (env-driven, see module docstring).
# ---------------------------------------------------------------------------

MONGO_URL   = os.environ.get("MONGO_URL", "")
DB_NAME     = os.environ.get("DB_NAME", "")
RESEND_KEY  = os.environ.get("RESEND_API_KEY", "")
PROXY_URL   = os.environ.get("WEBSHARE_PROXY_URL", "").strip()
SCAN_MIN    = int(os.environ.get("BIS_SCAN_INTERVAL_MIN", "60"))
CONCURRENCY = int(os.environ.get("BIS_SCAN_CONCURRENCY", "2"))
DEBUG_HTML  = os.environ.get("BIS_DEBUG_HTML", "0") == "1"

BIS_URL = "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet?bin={bin}"

# Per the spec: Critical severity for any of:
#   - "STOP WORK" anywhere in the violations table
#   - ECB with outstanding penalty and no hearing-date-satisfied
#   - violation status ACTIVE + description contains HAZARDOUS
# Everything else is Action (real violation/complaint) or Monitor (closed).
_CRITICAL_MARKERS = ("stop work", "hazardous")


# ---------------------------------------------------------------------------
# Mongo — singleton, async driver so we can run alongside Playwright.
# ---------------------------------------------------------------------------

_db_client: Optional[AsyncIOMotorClient] = None


def _get_db():
    global _db_client
    if _db_client is None:
        if not MONGO_URL or not DB_NAME:
            raise RuntimeError("MONGO_URL and DB_NAME are required")
        _db_client = AsyncIOMotorClient(MONGO_URL)
    return _db_client[DB_NAME]


# ---------------------------------------------------------------------------
# Alert dedupe — mirrors the 24-hour throttle in server.py so this scraper
# and the main server share the same dedup window. Both write to
# `system_config` with the same key schema.
# ---------------------------------------------------------------------------

ALERT_WINDOW_HOURS = 24


async def _alert_recently_sent(project_id: str, raw_dob_id: str) -> bool:
    if not project_id or not raw_dob_id:
        return False
    try:
        db = _get_db()
        doc = await db.system_config.find_one(
            {"key": f"dob_alert_sent:{project_id}:{raw_dob_id}"}
        )
    except Exception as e:
        logger.warning(f"alert throttle read failed: {e}")
        return False
    if not doc:
        return False
    last = doc.get("last_alert_at")
    if not isinstance(last, datetime):
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
    return hours < ALERT_WINDOW_HOURS


async def _mark_alert_sent(project_id: str, raw_dob_id: str) -> None:
    if not project_id or not raw_dob_id:
        return
    try:
        db = _get_db()
        await db.system_config.update_one(
            {"key": f"dob_alert_sent:{project_id}:{raw_dob_id}"},
            {"$set": {
                "key":           f"dob_alert_sent:{project_id}:{raw_dob_id}",
                "last_alert_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"alert throttle write failed: {e}")


async def _send_critical_alert(project: dict, record: dict) -> None:
    """Mirrors the main server's `_send_critical_dob_alert`, same email shape
    (so owners don't see a different template from the standalone scraper).
    Throttled to 24h per (project, raw_dob_id)."""
    project_id = str(project.get("_id") or project.get("id") or "")
    raw_dob_id = str(record.get("raw_dob_id") or "")
    if await _alert_recently_sent(project_id, raw_dob_id):
        logger.info(
            f"alert throttled (24h) project={project.get('name')} "
            f"raw_dob_id={raw_dob_id}"
        )
        return

    if not _resend or not RESEND_KEY:
        logger.warning(
            f"critical alert — RESEND_API_KEY missing, logging only. "
            f"project={project.get('name')} raw_dob_id={raw_dob_id} "
            f"summary={record.get('ai_summary')}"
        )
        await _mark_alert_sent(project_id, raw_dob_id)
        return

    company_id = project.get("company_id")
    if not company_id:
        return
    try:
        db = _get_db()
        admin_users = await db.users.find({
            "company_id": company_id,
            "role":       {"$in": ["admin", "owner"]},
            "is_deleted": {"$ne": True},
        }).to_list(50)
        recipients = [u.get("email") for u in admin_users if u.get("email")]
    except Exception as e:
        logger.error(f"alert recipients lookup failed: {e}")
        return
    if not recipients:
        return

    project_name = project.get("name", "Unknown Project")
    summary      = record.get("ai_summary", "No summary available")
    next_action  = record.get("next_action", "Review immediately")
    rtype        = record.get("record_type", "alert").upper().replace("_", " ")

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #dc2626; color: white; padding: 20px 24px; border-radius: 8px 8px 0 0;">
            <h1 style="margin: 0; font-size: 18px;">⚠️ CRITICAL DOB Alert</h1>
            <p style="margin: 4px 0 0; opacity: 0.9; font-size: 14px;">{project_name}</p>
        </div>
        <div style="background: #fff; border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
            <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
                <p style="margin: 0 0 4px; font-size: 11px; color: #991b1b; text-transform: uppercase; letter-spacing: 0.5px;">{rtype}</p>
                <p style="margin: 0; font-size: 15px; color: #1f2937; font-weight: 500;">{summary}</p>
            </div>
            <div style="background: #f9fafb; border-radius: 6px; padding: 16px;">
                <p style="margin: 0 0 4px; font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Required Action</p>
                <p style="margin: 0; font-size: 14px; color: #1f2937;">{next_action}</p>
            </div>
            <p style="margin: 16px 0 0; font-size: 12px; color: #9ca3af;">
                Source: BIS scraper
            </p>
        </div>
        <p style="text-align: center; font-size: 10px; color: #cbd5e1; margin-top: 16px; letter-spacing: 2px;">LEVELOG COMPLIANCE</p>
    </div>
    """
    try:
        _resend.api_key = RESEND_KEY
        _resend.Emails.send({
            "from":    "Levelog Alerts <alerts@levelog.com>",
            "to":      recipients,
            "subject": f"[CRITICAL] DOB Alert: {project_name} — {rtype}",
            "html":    html,
        })
        await _mark_alert_sent(project_id, raw_dob_id)
        logger.info(
            f"critical alert sent project={project_name} "
            f"raw_dob_id={raw_dob_id} recipients={len(recipients)}"
        )
    except Exception as e:
        logger.error(f"resend send failed: {e}")


# ---------------------------------------------------------------------------
# HTML parsing — BIS layout.
#
# The BIS "Property Profile Overview" page has several tables. The two we
# care about are typically labeled via preceding header rows / sectional
# headings like "COMPLAINTS" and "VIOLATIONS". Layout has shifted over the
# years; the parser is deliberately tolerant.
# ---------------------------------------------------------------------------

def _table_looks_like(table_text: str, *, kind: str) -> bool:
    """Heuristic: does this table's text content look like a violations or
    complaints list? Uses header keywords + row count."""
    low = table_text.lower()
    if kind == "violations":
        keys = ("violation", "vio", "ecb", "oath")
    elif kind == "complaints":
        keys = ("complaint", "comp #", "comp no")
    else:
        return False
    # Need at least one keyword AND at least one number-like token
    has_keyword = any(k in low for k in keys)
    has_numbers = bool(re.search(r"\d{5,}", low))
    return has_keyword and has_numbers


def _extract_tables(html: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (violations, complaints) — each as a list of dicts with the
    row text columns extracted. Raw enough that downstream severity rules
    can scan the whole row text; structured enough that we can grab an id.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    violations: List[Dict[str, Any]] = []
    complaints: List[Dict[str, Any]] = []

    for table in tables:
        text = table.get_text(" ", strip=True)
        kind: Optional[str] = None
        if _table_looks_like(text, kind="violations"):
            kind = "violations"
        elif _table_looks_like(text, kind="complaints"):
            kind = "complaints"
        else:
            continue

        # Extract rows + headers
        headers: List[str] = []
        header_row = table.find("tr")
        if header_row:
            header_cells = header_row.find_all(["th", "td"])
            headers = [c.get_text(" ", strip=True) for c in header_cells]

        rows = table.find_all("tr")[1:] if table.find_all("tr") else []
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            values = [c.get_text(" ", strip=True) for c in cells]
            row_text = " ".join(values)
            rec: Dict[str, Any] = {
                "_row_text": row_text,
                "_cells":    values,
                "_headers":  headers,
            }
            # Best-effort id extraction: first cell with a long numeric run,
            # or any cell matching an ECB-style number.
            rec["_id_candidate"] = _pick_id_from_cells(values)
            if kind == "violations":
                violations.append(rec)
            else:
                complaints.append(rec)

    return violations, complaints


def _pick_id_from_cells(cells: List[str]) -> str:
    """Pull a violation/complaint number out of a row. Looks for:
       - ECB-style: 10-digit numeric (e.g. 34867321K, 00012345)
       - or any 5+ digit token from the first few cells
    """
    for cell in cells[:5]:
        # ECB with trailing borough letter
        m = re.match(r"^\s*(\d{7,12}[A-Z]?)\s*$", cell)
        if m:
            return m.group(1)
    # Fallback: grab the longest numeric run in the row
    joined = " ".join(cells)
    longest = ""
    for tok in re.findall(r"\d{5,}", joined):
        if len(tok) > len(longest):
            longest = tok
    return longest


def _classify_violation_severity(row_text: str, headers: List[str], values: List[str]) -> str:
    """Critical / Action / Monitor for a violation row, per spec Q4."""
    low = row_text.lower()

    # --- Critical markers ---
    if "stop work" in low:
        return "Critical"
    if "hazardous" in low and "active" in low:
        return "Critical"
    # ECB with outstanding penalty + no hearing-satisfied.
    if "ecb" in low or "environmental control board" in low:
        if re.search(r"\$\s*\d", row_text):  # any dollar amount
            if "satisfied" not in low and "paid" not in low:
                return "Critical"

    # --- Action markers ---
    if "active" in low or "open" in low or "unresolved" in low:
        return "Action"
    if "not complied" in low:
        return "Action"

    # --- Default ---
    if "dismissed" in low or "certified" in low or "closed" in low or "resolved" in low:
        return "Monitor"
    return "Action"  # unknown → treat as Action (safer than Monitor)


def _classify_complaint_severity(row_text: str) -> str:
    """Critical/Action/Monitor for a BIS complaint row."""
    low = row_text.lower()
    if "stop work" in low:
        return "Critical"
    if "hazardous" in low and "active" in low:
        return "Critical"
    if "active" in low or "open" in low:
        return "Action"
    if "closed" in low or "disposed" in low or "resolved" in low:
        return "Monitor"
    return "Action"


def _next_action(severity: str, record_type: str) -> str:
    if severity == "Critical":
        return (
            "Critical finding — review immediately. Pull the site, stop "
            "affected work if it matches the violation scope, and confirm "
            "hearing / certification deadlines."
        )
    if severity == "Action":
        if record_type == "violation":
            return "Review the violation, certify correction if eligible, watch for ECB hearing date."
        return "Active complaint — inspector may visit. Verify cited area and prep the super."
    return "Monitor for status changes at the next scan."


# ---------------------------------------------------------------------------
# Playwright scrape.
# ---------------------------------------------------------------------------

async def _scrape_bin(playwright, bin_number: str) -> Optional[str]:
    """Load the BIS Property Profile page and return the full HTML, or
    None on any failure. Swallows Playwright-level errors and logs them
    so one bad BIN doesn't take down the batch."""
    browser = None
    try:
        launch_kwargs: Dict[str, Any] = {"headless": True}
        if PROXY_URL:
            launch_kwargs["proxy"] = {"server": PROXY_URL}

        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        # BIS loads cookies on the root page, then uses them for the query.
        page = await context.new_page()
        page.set_default_timeout(30_000)

        # Warm-up — sets Akamai cookies.
        try:
            await page.goto("https://a810-bisweb.nyc.gov/bisweb/", wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
        except PlaywrightTimeout:
            logger.warning(f"BIN {bin_number}: warmup timeout; continuing")

        url = BIS_URL.format(bin=bin_number)
        await page.goto(url, wait_until="domcontentloaded")
        # BIS is a classic ASP.NET page; tables render in the initial HTML
        # but sometimes a secondary XHR fills in row data.
        await page.wait_for_timeout(1_200)
        try:
            await page.wait_for_selector("table", timeout=10_000)
        except PlaywrightTimeout:
            logger.warning(f"BIN {bin_number}: no <table> after 10s")
            return None
        html = await page.content()
        return html
    except Exception as e:
        logger.error(f"BIN {bin_number}: playwright error: {e.__class__.__name__}: {e}")
        return None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Per-BIN workflow: scrape → parse → diff → insert → alert.
# ---------------------------------------------------------------------------

async def _process_project(playwright, project: dict) -> Dict[str, int]:
    stats = {"v_new": 0, "v_crit": 0, "c_new": 0, "c_crit": 0}
    bin_number = (project.get("nyc_bin") or "").strip()
    if not bin_number:
        return stats
    project_id = str(project.get("_id"))
    company_id = project.get("company_id", "")
    pname      = project.get("name") or "(unnamed)"

    html = await _scrape_bin(playwright, bin_number)
    if not html:
        return stats
    if DEBUG_HTML:
        logger.info(f"BIN {bin_number}: html_len={len(html)} preview={html[:400]!r}")

    violations, complaints = _extract_tables(html)
    logger.info(
        f"BIN {bin_number} project={pname}: "
        f"found {len(violations)} violation rows, {len(complaints)} complaint rows"
    )

    # --- Ingest violations ---
    for v in violations:
        vid = v.get("_id_candidate") or ""
        if not vid:
            continue
        raw_dob_id = f"bis-v:{vid}"
        # Dedupe against dob_logs (both this raw_dob_id AND the bare id that
        # the httpx BIS sync might have inserted earlier — they should be the
        # same source of truth).
        db = _get_db()
        existing = await db.dob_logs.find_one({
            "project_id":   project_id,
            "$or": [
                {"raw_dob_id":       raw_dob_id},
                {"violation_number": vid},
            ],
        })
        if existing:
            continue

        sev = _classify_violation_severity(v["_row_text"], v.get("_headers") or [], v.get("_cells") or [])
        doc = _build_dob_log_doc(
            project=project,
            project_id=project_id,
            company_id=company_id,
            bin_number=bin_number,
            record_type="violation",
            raw_dob_id=raw_dob_id,
            vid=vid,
            row=v,
            severity=sev,
        )
        try:
            await db.dob_logs.insert_one(doc)
            stats["v_new"] += 1
            if sev == "Critical":
                stats["v_crit"] += 1
                await _send_critical_alert(project, doc)
        except Exception as e:
            msg = str(e).lower()
            if "duplicate key" not in msg:
                logger.warning(f"violation insert failed BIN={bin_number} id={vid}: {e}")

    # --- Ingest complaints ---
    for c in complaints:
        cid = c.get("_id_candidate") or ""
        if not cid:
            continue
        raw_dob_id = f"bis-c:{cid}"
        db = _get_db()
        existing = await db.dob_logs.find_one({
            "project_id":   project_id,
            "$or": [
                {"raw_dob_id":       raw_dob_id},
                {"complaint_number": cid},
            ],
        })
        if existing:
            continue

        sev = _classify_complaint_severity(c["_row_text"])
        doc = _build_dob_log_doc(
            project=project,
            project_id=project_id,
            company_id=company_id,
            bin_number=bin_number,
            record_type="complaint",
            raw_dob_id=raw_dob_id,
            vid=cid,
            row=c,
            severity=sev,
        )
        try:
            await db.dob_logs.insert_one(doc)
            stats["c_new"] += 1
            if sev == "Critical":
                stats["c_crit"] += 1
                await _send_critical_alert(project, doc)
        except Exception as e:
            msg = str(e).lower()
            if "duplicate key" not in msg:
                logger.warning(f"complaint insert failed BIN={bin_number} id={cid}: {e}")

    return stats


def _build_dob_log_doc(*, project: dict, project_id: str, company_id: str,
                        bin_number: str, record_type: str, raw_dob_id: str,
                        vid: str, row: Dict[str, Any], severity: str) -> Dict[str, Any]:
    """Shape matches what server.py writes to `dob_logs` so the frontend
    and reporting pipeline see a consistent row regardless of source."""
    now = datetime.now(timezone.utc)
    cells = row.get("_cells") or []
    row_text = row.get("_row_text") or ""

    # Best-effort title / status from the row text (BIS tables don't
    # have consistent column ordering).
    summary = (row_text[:220] + "…") if len(row_text) > 220 else row_text

    doc = {
        "project_id":   project_id,
        "company_id":   company_id,
        "nyc_bin":      bin_number,
        "record_type":  record_type,
        "raw_dob_id":   raw_dob_id,
        "ai_summary":   f"[BIS] {summary}" if summary else f"[BIS] {record_type} {vid}",
        "severity":     severity,
        "next_action":  _next_action(severity, record_type),
        "dob_link":     BIS_URL.format(bin=bin_number),
        "detected_at":  now,
        "created_at":   now,
        "updated_at":   now,
        "is_deleted":   False,
        "source":       "bis_scraper",
    }
    if record_type == "violation":
        doc["violation_number"] = vid
        # Cheap extractions from the row — downstream UI already tolerates
        # missing fields, so these are best-effort.
        for cell in cells:
            low = cell.lower()
            if "active" in low or "open" in low or "dismissed" in low or "certified" in low:
                doc["resolution_state"] = cell
                break
    else:
        doc["complaint_number"] = vid
        for cell in cells:
            low = cell.lower()
            if "active" in low or "closed" in low or "disposed" in low:
                doc["complaint_status"] = cell
                break

    return doc


# ---------------------------------------------------------------------------
# Scan loop.
# ---------------------------------------------------------------------------

async def _load_tracked_projects() -> List[dict]:
    db = _get_db()
    try:
        return await db.projects.find({
            "track_dob_status": True,
            "nyc_bin":          {"$exists": True, "$ne": ""},
            "is_deleted":       {"$ne": True},
        }).to_list(500)
    except Exception as e:
        logger.error(f"project lookup failed: {e}")
        return []


async def scan_all() -> None:
    started = datetime.now(timezone.utc)
    projects = await _load_tracked_projects()
    if not projects:
        logger.info("BIS scan: no tracked projects")
        return
    logger.info(
        f"BIS scan starting: {len(projects)} projects "
        f"proxy={'on' if PROXY_URL else 'off'} concurrency={CONCURRENCY}"
    )

    totals = {"v_new": 0, "v_crit": 0, "c_new": 0, "c_crit": 0, "processed": 0, "failed": 0}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with async_playwright() as playwright:
        async def _one(p):
            async with sem:
                try:
                    st = await _process_project(playwright, p)
                    totals["processed"] += 1
                    for k in ("v_new", "v_crit", "c_new", "c_crit"):
                        totals[k] += st.get(k, 0)
                except Exception as e:
                    totals["failed"] += 1
                    logger.error(
                        f"project failed name={p.get('name')} "
                        f"bin={p.get('nyc_bin')}: {e.__class__.__name__}: {e}"
                    )

        await asyncio.gather(*[_one(p) for p in projects])

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"BIS scan complete: processed={totals['processed']} failed={totals['failed']} "
        f"v_new={totals['v_new']} v_crit={totals['v_crit']} "
        f"c_new={totals['c_new']} c_crit={totals['c_crit']} elapsed={elapsed:.1f}s"
    )


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

async def _run_forever() -> None:
    # Sanity checks.
    if not MONGO_URL or not DB_NAME:
        logger.error("MONGO_URL and DB_NAME must be set. Exiting.")
        sys.exit(1)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        scan_all,
        IntervalTrigger(minutes=SCAN_MIN),
        id="bis_scan_all",
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"bis_scraper started, interval={SCAN_MIN}m, concurrency={CONCURRENCY}, "
        f"proxy={'on' if PROXY_URL else 'off'}"
    )

    # Block forever; scheduler runs in the background asyncio loop.
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("shutting down")
        scheduler.shutdown(wait=False)


def main():
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
