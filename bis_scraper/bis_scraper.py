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
import random
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

# playwright-stealth patches Chromium to hide the handful of telltales
# that Akamai Bot Manager fingerprints for "headless browser" — missing
# `navigator.plugins`, `navigator.webdriver=true`, Chrome runtime gaps,
# iframe.contentWindow shape, etc. Without this BIS serves a 335-byte
# Access Denied page even through residential proxies. Import is kept
# optional so a locally-run scraper without the dep still boots.
try:
    from playwright_stealth import stealth_async  # type: ignore
    _STEALTH_OK = True
except Exception:
    _STEALTH_OK = False
    async def stealth_async(page):  # type: ignore
        return None

try:
    import resend as _resend
except ImportError:  # pragma: no cover — resend is optional
    _resend = None


# ---------------------------------------------------------------------------
# Logging — structured enough to grep in Railway logs.
# ---------------------------------------------------------------------------

_log_fmt = logging.Formatter(
    "%(asctime)s [bis_scraper] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Route INFO and below to stdout, WARNING+ to stderr. Railway labels stderr
# red regardless of the Python level — without this split, every INFO line
# shows up as "error" in their log UI.
_out_handler = logging.StreamHandler(sys.stdout)
_out_handler.setLevel(logging.DEBUG)
_out_handler.addFilter(lambda r: r.levelno < logging.WARNING)
_out_handler.setFormatter(_log_fmt)
_err_handler = logging.StreamHandler(sys.stderr)
_err_handler.setLevel(logging.WARNING)
_err_handler.setFormatter(_log_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_out_handler, _err_handler])
logger = logging.getLogger("bis_scraper")
# Tone down APScheduler's own INFO messages (they also land on stderr
# otherwise, adding red noise to every tick).
logging.getLogger("apscheduler").setLevel(logging.WARNING)


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


def _build_playwright_proxy() -> Optional[Dict[str, str]]:
    """Convert WEBSHARE_PROXY_URL (http://user:pass@host:port) into the
    dict shape Playwright Chromium expects. Chromium IGNORES inline
    credentials in `server` — it needs `username`/`password` as
    separate keys, otherwise CONNECT goes out with no Proxy-Auth and
    Webshare returns 407, which Playwright surfaces as a 30s
    `Page.goto` timeout. This was the exact symptom in every BIN
    attempt before.
    """
    if not PROXY_URL:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(PROXY_URL)
    if not parsed.hostname or not parsed.port:
        # Malformed; let Playwright surface whatever error it wants.
        return {"server": PROXY_URL}
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port}"
    cfg: Dict[str, str] = {"server": server}
    if parsed.username:
        cfg["username"] = parsed.username
    if parsed.password:
        cfg["password"] = parsed.password
    return cfg


PW_PROXY = _build_playwright_proxy()

BIS_URL = "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet?bin={bin}"

# NYC BIN rules: 7 digits, first digit encodes borough (1=MN, 2=BX, 3=BK,
# 4=QN, 5=SI). A BIN like 2000000 (zeros after the borough digit) is a
# placeholder the DOB issues when a building has no real BIN yet — it will
# never resolve to an actual property profile and will always warmup-
# timeout, wasting scan time. Filter these out before we launch Chromium.
_PLACEHOLDER_BIN_PATTERN = re.compile(r"^[1-5]0{6}$")


def _is_real_bin(bin_number: str) -> bool:
    b = (bin_number or "").strip()
    if not b.isdigit():
        return False
    if len(b) != 7:
        return False
    if _PLACEHOLDER_BIN_PATTERN.match(b):
        return False
    return True

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
# Alert gating — mirrors the two-layer logic in server.py so this scraper
# and the main API share the same dedup schema + the same "initial scan
# is silent" behavior. Both write to `system_config`.
# ---------------------------------------------------------------------------

ALERT_WINDOW_HOURS = 24


async def _initial_scan_done(project_id: str) -> bool:
    """True once the first full BIS scan of this project has completed.
    Before that marker, no emails fire from this source — the backfill
    would otherwise blast the owner with old historical violations."""
    if not project_id:
        return False
    try:
        db = _get_db()
        doc = await db.system_config.find_one(
            {"key": f"initial_scan_done:bis:{project_id}"}
        )
        return bool(doc)
    except Exception as e:
        logger.warning(f"initial_scan_done read failed: {e}")
        # On DB hiccups, err toward "done" so we don't silently suppress
        # real alerts forever.
        return True


async def _mark_initial_scan_done(project_id: str) -> None:
    if not project_id:
        return
    try:
        db = _get_db()
        await db.system_config.update_one(
            {"key": f"initial_scan_done:bis:{project_id}"},
            {"$set": {
                "key":          f"initial_scan_done:bis:{project_id}",
                "source":       "bis",
                "project_id":   project_id,
                "completed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"initial_scan mark failed: {e}")


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
    """Mirrors the main server's `_send_critical_dob_alert`, same email
    shape (so owners don't see a different template from the standalone
    scraper). Two gates:
      1. Initial BIS scan of this project must already be complete —
         otherwise historical backfill would spam the owner.
      2. 24h per-record throttle, shared via system_config with the
         backend so both processes never double-send.
    """
    project_id = str(project.get("_id") or project.get("id") or "")
    raw_dob_id = str(record.get("raw_dob_id") or "")

    # Gate 1 — initial-scan suppression
    if not await _initial_scan_done(project_id):
        logger.info(
            f"alert suppressed (initial BIS scan in progress) "
            f"project={project.get('name')} raw_dob_id={raw_dob_id}"
        )
        return

    # Gate 2 — 24h per-record throttle
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

    project_name = project.get("name", "your project")
    summary      = record.get("ai_summary")  or "A new DOB record was found."
    next_action  = record.get("next_action") or "Open Levelog to review the details."
    rt_raw       = record.get("record_type", "")
    rt           = _humanize_record_type(rt_raw)
    dob_link     = record.get("dob_link") or ""
    detected_at  = record.get("detected_at") or datetime.now(timezone.utc)
    if isinstance(detected_at, datetime):
        detected_str = detected_at.strftime("%b %d, %Y at %I:%M %p UTC")
    else:
        detected_str = str(detected_at)

    link_line = f"\n\nDetails: {dob_link}" if dob_link else ""
    text_body = (
        f"Hi,\n\n"
        f"Levelog picked up a new {rt} on {project_name}.\n\n"
        f"Summary: {summary}\n\n"
        f"Recommended next step: {next_action}\n\n"
        f"Detected {detected_str}."
        f"{link_line}\n\n"
        f"You're receiving this because you're listed as an admin or owner "
        f"on this Levelog project. Reply to this email if you have questions.\n\n"
        f"— Levelog"
    )

    link_html = (
        f'<p style="margin:16px 0 0;"><a href="{dob_link}" '
        f'style="color:#1d4ed8;text-decoration:none;">View on NYC DOB</a></p>'
        if dob_link else ""
    )
    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2937;line-height:1.55;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" width="560" style="max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;">
    <tr><td style="padding:24px 28px;">
      <p style="margin:0 0 12px;font-size:14px;color:#6b7280;">Levelog</p>
      <h1 style="margin:0 0 18px;font-size:18px;font-weight:600;color:#111827;">
        New {rt} on {project_name}
      </h1>
      <p style="margin:0 0 14px;font-size:15px;">Hi,</p>
      <p style="margin:0 0 14px;font-size:15px;">
        Levelog picked up a new {rt} on <strong>{project_name}</strong>. Here are the details:
      </p>
      <p style="margin:0 0 14px;font-size:15px;"><strong>Summary:</strong> {summary}</p>
      <p style="margin:0 0 14px;font-size:15px;"><strong>Recommended next step:</strong> {next_action}</p>
      <p style="margin:0 0 14px;font-size:13px;color:#6b7280;">Detected {detected_str}.</p>
      {link_html}
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
      <p style="margin:0;font-size:12px;color:#6b7280;">
        You're receiving this because you're listed as an admin or owner on this Levelog project.
        Reply to this email if you have questions.
      </p>
    </td></tr>
  </table>
</body>
</html>"""

    subject = f"New {rt} on {project_name}"

    try:
        _resend.api_key = RESEND_KEY
        _resend.Emails.send({
            "from":     "Levelog <notifications@levelog.com>",
            "to":       recipients,
            "subject":  subject,
            "html":     html_body,
            "text":     text_body,
            "reply_to": "support@levelog.com",
        })
        await _mark_alert_sent(project_id, raw_dob_id)
        logger.info(
            f"DOB notification sent project={project_name} "
            f"({rt}) raw_dob_id={raw_dob_id} recipients={len(recipients)}"
        )
    except Exception as e:
        logger.error(f"resend send failed: {e}")


def _humanize_record_type(rt: str) -> str:
    rt = (rt or "alert").lower().replace("_", " ")
    pretty = {
        "violation":  "violation",
        "complaint":  "complaint",
        "permit":     "permit update",
        "inspection": "inspection result",
        "swo":        "stop work order",
    }
    return pretty.get(rt, rt)


# ---------------------------------------------------------------------------
# HTML parsing — BIS layout.
#
# The BIS "Property Profile Overview" page has several tables. The two we
# care about are typically labeled via preceding header rows / sectional
# headings like "COMPLAINTS" and "VIOLATIONS". Layout has shifted over the
# years; the parser is deliberately tolerant.
# ---------------------------------------------------------------------------

def _table_looks_like(table_text: str, *, kind: str) -> bool:
    """Heuristic: does this table's text content look like a violations,
    complaints, or active-permits list? Uses header keywords + row count."""
    low = table_text.lower()
    if kind == "violations":
        keys = ("violation", "vio", "ecb", "oath")
    elif kind == "complaints":
        keys = ("complaint", "comp #", "comp no")
    elif kind == "permits":
        # Active permit rows on BIS have either "permit" or job-filing
        # language + a status column with ISSUED / ACTIVE / RENEWED.
        # Some builds also title it "Jobs / Filings".
        keys = ("permit", "job filing", "filing#", "issued")
    else:
        return False
    # Need at least one keyword AND at least one number-like token
    has_keyword = any(k in low for k in keys)
    has_numbers = bool(re.search(r"\d{5,}", low))
    return has_keyword and has_numbers


# --- License-number row parsing ----------------------------------------------
#
# Active permit rows on the BIS Property Profile page carry the filer/GC
# license number in one of a few columns depending on the table variant.
# The value is typically 6-7 digits, sometimes prefixed (e.g. "GC123456").
# We detect by header ("License", "Lic #", "Licensee License Nbr") OR by
# fallback regex on the row cells.

_LICENSE_HEADER_HINTS = re.compile(
    r"licensee?.*(?:license|lic).*(?:no|nbr|#|number)|^lic\.?\s*(?:#|no|nbr)\s*$|^license\s*(?:#|no|nbr)",
    re.I,
)
# 6–7 digit numeric license number, optionally preceded by 1–3 letter prefix
# (GC, HIC, PL, EL etc). Matches "GC123456", "123456", "1234567".
_LICENSE_VALUE_RE = re.compile(r"^\s*([A-Z]{0,3})\s*-?\s*(\d{6,7})\s*$")


def _extract_license_from_row(headers: List[str], values: List[str]) -> Optional[str]:
    """Given one permit-row's headers and cell values, return the license
    number if present. Prefers the column whose header matches the hint;
    falls back to first cell that looks license-shaped."""
    # Header-targeted lookup
    if headers and len(headers) == len(values):
        for h, v in zip(headers, values):
            if _LICENSE_HEADER_HINTS.search(h or ""):
                m = _LICENSE_VALUE_RE.match(v or "")
                if m:
                    num = m.group(2)
                    return num
    # Fallback: any cell that matches the license-shape pattern AND is
    # clearly not a job-filing number (8+ digits) or ECB (7+ digits with
    # trailing borough letter).
    for v in values:
        m = _LICENSE_VALUE_RE.match(v or "")
        if m:
            num = m.group(2)
            # 6-7 digits is the license range; skip 10+ digit job filings.
            if 6 <= len(num) <= 7:
                return num
    return None


def _is_active_permit_row(row_text: str) -> bool:
    """Only harvest licenses from rows that look like ACTIVE permits —
    don't pick up licenses attached to 2014 closed jobs."""
    low = row_text.lower()
    if any(k in low for k in ("issued", "active", "re-issued", "reissued")):
        return True
    # Some BIS variants use "X" / checkmark under an "Is Open" column;
    # be permissive if no close-out language is present and the row has
    # a recent-looking date (we don't parse dates here — conservative: if
    # the row says 'expired' or 'dismissed', reject).
    if any(k in low for k in ("expired", "dismissed", "withdrawn", "superseded", "closed")):
        return False
    return True


def _extract_tables(html: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Return (violations, complaints, active_license_numbers).
    License numbers come from the active permit rows on the same page."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    violations:       List[Dict[str, Any]] = []
    complaints:       List[Dict[str, Any]] = []
    active_licenses:  List[str]            = []

    for table in tables:
        text = table.get_text(" ", strip=True)
        kind: Optional[str] = None
        if _table_looks_like(text, kind="violations"):
            kind = "violations"
        elif _table_looks_like(text, kind="complaints"):
            kind = "complaints"
        elif _table_looks_like(text, kind="permits"):
            kind = "permits"
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

            if kind == "permits":
                # Don't store permit rows (we don't alert on permits from
                # this scraper — DOB sync handles those). But DO pull the
                # license number if this looks like an active permit.
                if _is_active_permit_row(row_text):
                    lic = _extract_license_from_row(headers, values)
                    if lic and lic not in active_licenses:
                        active_licenses.append(lic)
                continue

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

    return violations, complaints, active_licenses


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
# License capture — Step 1 continuation.
# ---------------------------------------------------------------------------

async def _save_discovered_license(company_id: str, license_number: str,
                                     bin_number: str) -> None:
    """Store the GC license number on the company doc if nothing is set yet.

    We explicitly don't overwrite a value that was placed by manual entry
    or by the NYC Open Data refresh — those are authoritative. Empty
    string / missing → fill it in. That way the scraper helps bootstrap
    new companies but never stomps a human decision.
    """
    if not company_id or not license_number:
        return
    try:
        db = _get_db()
        # Try to match the Mongo _id shape the backend uses.
        from bson import ObjectId
        try:
            oid = ObjectId(company_id)
            match = {"_id": oid}
        except Exception:
            match = {"_id": company_id}

        existing = await db.companies.find_one(match, {"gc_license_number": 1})
        if not existing:
            logger.warning(
                f"license save: company {company_id} not found "
                f"(bin={bin_number})"
            )
            return
        if existing.get("gc_license_number"):
            # Already populated — don't overwrite.
            return
        await db.companies.update_one(
            match,
            {"$set": {
                "gc_license_number":       license_number,
                "gc_license_source":       "bis_scraper",
                "gc_license_discovered_at": datetime.now(timezone.utc),
                "updated_at":              datetime.now(timezone.utc),
            }},
        )
        logger.info(
            f"license saved on company={company_id} "
            f"license_number={license_number} source_bin={bin_number}"
        )
    except Exception as e:
        logger.warning(f"license save failed company={company_id}: {e}")


# ---------------------------------------------------------------------------
# Insurance fetch — Steps 2 + 3.
#
# We run insurance enrichment ONCE per unique license number per 24h, not
# once per project, because multiple projects often share the same GC.
# Dedup is in system_config, same shape as other per-key cooldowns in the
# backend.
#
# Source of truth: BIS Licensing portal. Query by license number → the
# response page contains an Insurance table with the three records that
# matter for permit eligibility:
#    - General Liability
#    - Workers Compensation
#    - Disability Benefits
# Expiration dates there are the authoritative numbers for renewal.
# ---------------------------------------------------------------------------

LICENSE_QUERY_URL = (
    "https://a810-bisweb.nyc.gov/bisweb/LicenseQueryByLicenseNumberServlet"
    "?allkey={lic}&requestid=0"
)
# Insurance is event-driven, not time-driven. We fetch when any of:
#   (a) we have zero insurance records for this license yet (first time
#       we've ever seen the company — covers new-project on-boarding so
#       automated permit renewal has data to work with),
#   (b) the earliest current insurance expiration is ≤ 30 days away
#       (catches the GC's actual renewal, so we surface the new dates),
#   (c) safety ceiling: we haven't checked in > 14 days regardless
#       (handles case where stored dates got corrupted and both checks
#       above pass incorrectly — cheap backstop).
# This is MUCH less traffic than the old every-24h model while still
# never missing a real policy turnover.
INSURANCE_REFRESH_WITHIN_DAYS = 30
INSURANCE_HARD_REFRESH_DAYS   = 14

# Map the various BIS row labels to the canonical insurance_type values
# the backend and frontend already use (same as manual entry).
_INS_TYPE_MAP = [
    ("general liability",    "general_liability"),
    ("general_liability",    "general_liability"),
    ("gen liab",             "general_liability"),
    ("glc",                  "general_liability"),
    ("workers comp",         "workers_comp"),
    ("workers' comp",        "workers_comp"),
    ("workmen",              "workers_comp"),
    ("work comp",            "workers_comp"),
    ("wc",                   "workers_comp"),
    ("disability",           "disability"),
    ("dbl",                  "disability"),
]
_DATE_IN_CELL_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")


def _classify_insurance_row(row_text: str) -> Optional[str]:
    """Return one of {'general_liability','workers_comp','disability'} if the
    row looks like that kind of insurance, else None."""
    low = row_text.lower()
    for hint, canonical in _INS_TYPE_MAP:
        if hint in low:
            return canonical
    return None


def _parse_insurance_table(html: str) -> List[Dict[str, Any]]:
    """Parse the Licensing-portal HTML for insurance records.

    Returns list of dicts shaped like manual entry writes to
    companies.gc_insurance_records:
        {insurance_type, carrier_name, policy_number,
         effective_date, expiration_date, is_current, source}
    """
    out: List[Dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True).lower()
        # Only insurance tables contain all three keywords on the SAME table.
        if "general liability" not in text and "workers" not in text \
                and "disability" not in text:
            continue

        headers: List[str] = []
        header_row = table.find("tr")
        if header_row:
            header_cells = header_row.find_all(["th", "td"])
            headers = [c.get_text(" ", strip=True) for c in header_cells]

        # Best-effort: if we see a clear "Expiration" header, remember its
        # index — the date in that column wins over any other date in the row.
        header_low = [h.lower() for h in headers]
        exp_idx: Optional[int] = None
        eff_idx: Optional[int] = None
        carrier_idx: Optional[int] = None
        policy_idx: Optional[int] = None
        for i, h in enumerate(header_low):
            if "expir" in h:
                exp_idx = i
            elif "effect" in h or "issued" in h:
                eff_idx = i
            elif "carrier" in h or "insurer" in h or "company" in h:
                carrier_idx = i
            elif "policy" in h:
                policy_idx = i

        rows = table.find_all("tr")
        for row in rows[1:] if headers else rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            values = [c.get_text(" ", strip=True) for c in cells]
            row_text = " ".join(values)
            kind = _classify_insurance_row(row_text)
            if not kind:
                continue

            # Pull effective / expiration dates. Prefer header-indexed cells;
            # fall back to "first date in row is effective, last is expiration".
            exp_val = _cell_or_none(values, exp_idx)
            eff_val = _cell_or_none(values, eff_idx)
            carrier = _cell_or_none(values, carrier_idx)
            policy  = _cell_or_none(values, policy_idx)
            if not exp_val or not eff_val:
                all_dates = _DATE_IN_CELL_RE.findall(row_text)
                if not exp_val and all_dates:
                    exp_val = all_dates[-1]
                if not eff_val and len(all_dates) >= 2:
                    eff_val = all_dates[0]

            # Decide is_current based on expiration date vs today.
            is_current = _insurance_is_current(exp_val)

            out.append({
                "insurance_type":  kind,
                "carrier_name":    carrier,
                "policy_number":   policy,
                "effective_date":  eff_val,
                "expiration_date": exp_val,
                "is_current":      is_current,
                "source":          "bis_scraper",
            })
    return out


def _cell_or_none(values: List[str], idx: Optional[int]) -> Optional[str]:
    if idx is None or idx < 0 or idx >= len(values):
        return None
    v = (values[idx] or "").strip()
    return v or None


def _insurance_is_current(expiration_date: Optional[str]) -> bool:
    if not expiration_date:
        return False
    # Accept MM/DD/YYYY or M/D/YY forms.
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(expiration_date, fmt).replace(tzinfo=timezone.utc)
            return dt > datetime.now(timezone.utc)
        except Exception:
            continue
    return False


def _parse_ins_date(v: Optional[str]) -> Optional[datetime]:
    """Parse MM/DD/YYYY or MM/DD/YY into UTC datetime, or None."""
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


async def _insurance_fetch_due(license_number: str) -> bool:
    """Event-driven fetch gate.

    Returns True iff any of:
      (a) no company currently has scraper-written insurance records
          for this license number (brand-new project / first touch),
      (b) earliest still-current insurance record expires in ≤ 30 days
          (so the GC is likely mid-renewal; pick up the new policy),
      (c) cache says we haven't run in > 14 days anyway (cheap
          backstop for corrupted state).

    Unlike the old 24h TTL, this doesn't re-hit BIS hourly for
    licenses whose insurance is far from expiring.
    """
    if not license_number:
        return False

    try:
        db = _get_db()
    except Exception as e:
        logger.warning(f"insurance gate: db unavailable: {e}")
        return True  # on hiccup, err toward running

    now = datetime.now(timezone.utc)

    # (a) Any company actually storing bis_scraper-written records for this
    # license? If not — either no company has this license yet, or we've
    # never fetched for this license. Either way, fetch now.
    try:
        companies_with_records = await db.companies.count_documents({
            "gc_license_number": license_number,
            "gc_insurance_records": {
                "$elemMatch": {"source": "bis_scraper"},
            },
            "is_deleted": {"$ne": True},
        })
    except Exception as e:
        logger.warning(f"insurance gate: company read failed {license_number}: {e}")
        return True
    if companies_with_records == 0:
        logger.info(
            f"insurance gate license={license_number}: no scraper records on "
            f"any company → fetching (initial / on-boarding)"
        )
        return True

    # (b) Earliest current expiration across all companies on this license.
    # If ≤ 30 days, fetch.
    try:
        cursor = db.companies.find(
            {
                "gc_license_number": license_number,
                "gc_insurance_records.source": "bis_scraper",
                "is_deleted": {"$ne": True},
            },
            {"gc_insurance_records": 1},
        )
        earliest_exp: Optional[datetime] = None
        async for company in cursor:
            for rec in company.get("gc_insurance_records") or []:
                if rec.get("source") != "bis_scraper":
                    continue
                if not rec.get("is_current"):
                    continue
                dt = _parse_ins_date(rec.get("expiration_date"))
                if not dt:
                    continue
                if earliest_exp is None or dt < earliest_exp:
                    earliest_exp = dt
    except Exception as e:
        logger.warning(f"insurance gate: expiry read failed {license_number}: {e}")
        return True

    if earliest_exp is not None:
        days_left = (earliest_exp - now).days
        if days_left <= INSURANCE_REFRESH_WITHIN_DAYS:
            logger.info(
                f"insurance gate license={license_number}: earliest exp in "
                f"{days_left}d ≤ {INSURANCE_REFRESH_WITHIN_DAYS}d → fetching"
            )
            return True

    # (c) Hard-refresh backstop. If we happen to have records but the cache
    # says we haven't looked in > 14 days, fetch once just to be safe.
    try:
        doc = await db.system_config.find_one(
            {"key": f"insurance_fetch:{license_number}"}
        )
    except Exception:
        doc = None
    if doc:
        last = doc.get("last_fetched_at")
        if isinstance(last, datetime):
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days = (now - last).total_seconds() / 86400.0
            if days >= INSURANCE_HARD_REFRESH_DAYS:
                logger.info(
                    f"insurance gate license={license_number}: hard-refresh "
                    f"({days:.1f}d since last fetch)"
                )
                return True

    # Otherwise skip — insurance is fresh, not near expiration, and we've
    # checked within the backstop window.
    return False


async def _mark_insurance_fetched(license_number: str, records_found: int) -> None:
    if not license_number:
        return
    try:
        db = _get_db()
        await db.system_config.update_one(
            {"key": f"insurance_fetch:{license_number}"},
            {"$set": {
                "key":             f"insurance_fetch:{license_number}",
                "license_number":  license_number,
                "last_fetched_at": datetime.now(timezone.utc),
                "last_record_count": records_found,
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"insurance cache write failed {license_number}: {e}")


async def _scrape_insurance(playwright, license_number: str) -> Optional[str]:
    """Load the licensing portal page via Playwright and return the HTML."""
    # Same human-pacing jitter as the BIN scraper — unique licenses are
    # processed after the BIN step so this spreads the second burst too.
    await asyncio.sleep(random.uniform(2.0, 9.0))
    browser = None
    try:
        # Non-headless under Xvfb (see Dockerfile). Akamai fingerprints
        # chromium-headless-shell reliably; a real Chromium window
        # rendering into a virtual display passes.
        launch_kwargs: Dict[str, Any] = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if PW_PROXY:
            launch_kwargs["proxy"] = PW_PROXY
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
            },
        )
        page = await context.new_page()
        await stealth_async(page)
        page.set_default_timeout(30_000)
        # Warmup: wait for Akamai's sensor_data POST to land before
        # navigating to the servlet.
        try:
            await page.goto(
                "https://a810-bisweb.nyc.gov/bisweb/",
                wait_until="networkidle",
                timeout=20_000,
            )
        except PlaywrightTimeout:
            logger.warning(
                f"license {license_number}: warmup networkidle timeout; continuing"
            )
        await page.wait_for_timeout(int(random.uniform(3_000, 8_000)))
        url = LICENSE_QUERY_URL.format(lic=license_number)
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1_200)
        try:
            await page.wait_for_selector("table", timeout=10_000)
        except PlaywrightTimeout:
            try:
                fallback_html = await page.content()
            except Exception:
                fallback_html = ""
            logger.warning(
                f"license {license_number}: no <table> after 10s; "
                f"html_len={len(fallback_html)} "
                f"preview={fallback_html[:600]!r}"
            )
            return None
        return await page.content()
    except Exception as e:
        logger.error(
            f"license {license_number}: playwright error: "
            f"{e.__class__.__name__}: {e}"
        )
        return None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


async def _upsert_company_insurance(
    company_ids: List[str], records: List[Dict[str, Any]],
    license_number: str,
) -> None:
    """Write the scraped insurance records into db.companies[*]
    .gc_insurance_records — matching the shape manual entry uses so the
    existing settings/UI read them with no frontend changes.

    We merge by insurance_type: any existing entry with source='manual_entry'
    is preserved (manual wins). Existing bis_scraper entries are replaced by
    the latest scrape. Existing entries without a source are treated as stale
    bis-scraper rows and also replaced.
    """
    if not company_ids or not records:
        return
    db = _get_db()
    now = datetime.now(timezone.utc)
    from bson import ObjectId

    scraped_by_type = {r["insurance_type"]: r for r in records if r.get("insurance_type")}

    for cid in company_ids:
        try:
            try:
                oid = ObjectId(cid)
                match = {"_id": oid}
            except Exception:
                match = {"_id": cid}

            existing = await db.companies.find_one(match, {"gc_insurance_records": 1})
            if not existing:
                continue
            prior: List[Dict[str, Any]] = existing.get("gc_insurance_records") or []

            # Keep manual entries; replace everything else from scraped_by_type.
            merged: List[Dict[str, Any]] = []
            seen_types = set()
            for p in prior:
                itype = p.get("insurance_type")
                src   = p.get("source") or ""
                if src == "manual_entry":
                    merged.append(p)
                    seen_types.add(itype)
                    continue
                # Non-manual: replace with fresh scraped version if we have one,
                # otherwise keep the old (so we don't lose data if scrape
                # regresses — e.g. row disappears temporarily).
                if itype in scraped_by_type:
                    merged.append(scraped_by_type[itype])
                    seen_types.add(itype)
                else:
                    merged.append(p)
                    seen_types.add(itype)
            # Add any scraped types that weren't already represented.
            for itype, rec in scraped_by_type.items():
                if itype not in seen_types:
                    merged.append(rec)

            set_ops: Dict[str, Any] = {
                "gc_insurance_records": merged,
                "gc_last_verified":     now,
                "updated_at":           now,
            }
            # Opportunistically fill license_number on companies that
            # somehow got insurance before a license was written.
            if license_number and not existing.get("gc_license_number"):
                set_ops["gc_license_number"] = license_number
                set_ops["gc_license_source"] = "bis_scraper"

            await db.companies.update_one(match, {"$set": set_ops})
            logger.info(
                f"insurance upserted on company={cid} "
                f"license={license_number} types="
                + ",".join(sorted(scraped_by_type.keys()))
            )
        except Exception as e:
            logger.warning(
                f"insurance upsert failed company={cid} "
                f"license={license_number}: {e}"
            )


async def _companies_for_license(license_number: str) -> List[str]:
    """Return every company_id that currently has this license number set,
    plus every company_id whose tracked project BIN produced this license
    in the same scan run. In practice it's the intersection we need when
    deciding who to update."""
    db = _get_db()
    ids: List[str] = []
    try:
        async for c in db.companies.find(
            {"gc_license_number": license_number},
            {"_id": 1},
        ):
            ids.append(str(c["_id"]))
    except Exception as e:
        logger.warning(f"companies lookup by license failed: {e}")
    return ids


async def _run_insurance_step(playwright, license_to_companies: Dict[str, List[str]]) -> None:
    """Steps 2 + 3: for each unique license seen in this scan run, fetch
    insurance (once per 24h) and upsert onto the associated companies."""
    if not license_to_companies:
        return
    for lic, seed_companies in license_to_companies.items():
        if not lic:
            continue
        try:
            if not await _insurance_fetch_due(lic):
                logger.info(f"insurance cache hit (<24h) license={lic}; skip")
                continue

            html = await _scrape_insurance(playwright, lic)
            if not html:
                logger.warning(f"insurance scrape returned nothing license={lic}")
                await _mark_insurance_fetched(lic, 0)
                continue
            if DEBUG_HTML:
                logger.info(
                    f"license {lic}: html_len={len(html)} preview={html[:400]!r}"
                )
            records = _parse_insurance_table(html)
            logger.info(
                f"license {lic}: parsed {len(records)} insurance records"
            )

            # Which companies to update? Any company whose current
            # gc_license_number matches this license, unioned with the
            # companies seeded from this scan's Step-1 discovery.
            db_companies = await _companies_for_license(lic)
            targets = sorted(set(db_companies) | set(seed_companies))
            if not targets:
                logger.info(f"license {lic}: no companies match — nothing to upsert")
                await _mark_insurance_fetched(lic, len(records))
                continue

            if records:
                await _upsert_company_insurance(targets, records, lic)
            await _mark_insurance_fetched(lic, len(records))
        except Exception as e:
            logger.error(
                f"insurance pipeline failed license={lic}: "
                f"{e.__class__.__name__}: {e}"
            )


# ---------------------------------------------------------------------------
# Playwright scrape.
# ---------------------------------------------------------------------------

async def _scrape_bin(playwright, bin_number: str) -> Optional[str]:
    """Load the BIS Property Profile page and return the full HTML, or
    None on any failure. Swallows Playwright-level errors and logs them
    so one bad BIN doesn't take down the batch."""
    # Pre-scan jitter so the two concurrent workers don't fire at the
    # exact same wall-clock second every cycle. 2-9s random offset
    # breaks the "7 BINs in a tight burst" shape that trips rate
    # heuristics, without adding meaningful latency to the overall
    # hourly scan.
    await asyncio.sleep(random.uniform(2.0, 9.0))
    browser = None
    try:
        # Non-headless under Xvfb (see Dockerfile). Akamai fingerprints
        # chromium-headless-shell reliably; a real Chromium window
        # rendering into a virtual display passes.
        launch_kwargs: Dict[str, Any] = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if PW_PROXY:
            launch_kwargs["proxy"] = PW_PROXY

        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
            },
        )
        page = await context.new_page()
        # Hide headless telltales BEFORE first navigation; otherwise
        # Akamai's sensor_data captures the patched-vs-raw diff.
        await stealth_async(page)
        page.set_default_timeout(30_000)

        # Warm-up — navigate to the BIS root and wait for Akamai's
        # sensor_data POST to complete so `_abck` is set to a valid
        # value. networkidle usually resolves after the sensor fires.
        try:
            await page.goto(
                "https://a810-bisweb.nyc.gov/bisweb/",
                wait_until="networkidle",
                timeout=20_000,
            )
        except PlaywrightTimeout:
            logger.warning(f"BIN {bin_number}: warmup networkidle timeout; continuing")
        # Human-like dwell on the root page before navigating to the
        # servlet: real users read the homepage for 3-8s. 2.5s was
        # the floor for Akamai's sensor_data validation; extending
        # the window with jitter makes the request pattern look less
        # like "automation warming up a cookie jar."
        await page.wait_for_timeout(int(random.uniform(3_000, 8_000)))

        url = BIS_URL.format(bin=bin_number)
        await page.goto(url, wait_until="domcontentloaded")
        # BIS is a classic ASP.NET page; tables render in the initial HTML
        # but sometimes a secondary XHR fills in row data.
        await page.wait_for_timeout(1_200)
        try:
            await page.wait_for_selector("table", timeout=10_000)
        except PlaywrightTimeout:
            # Grab whatever the page contains so we can see if Akamai
            # served a block page, a JS challenge, or something else.
            try:
                fallback_html = await page.content()
            except Exception:
                fallback_html = ""
            logger.warning(
                f"BIN {bin_number}: no <table> after 10s; "
                f"html_len={len(fallback_html)} "
                f"preview={fallback_html[:600]!r}"
            )
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

async def _process_project(playwright, project: dict) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "v_new": 0, "v_crit": 0, "c_new": 0, "c_crit": 0,
        "licenses": [],      # list of license#s discovered on this BIN
        "company_id": "",    # passed up so scan_all can aggregate license→companies
    }
    bin_number = (project.get("nyc_bin") or "").strip()
    if not bin_number:
        return stats
    project_id = str(project.get("_id"))
    company_id = project.get("company_id", "")
    stats["company_id"] = company_id
    pname      = project.get("name") or "(unnamed)"

    html = await _scrape_bin(playwright, bin_number)
    if not html:
        return stats
    if DEBUG_HTML:
        logger.info(f"BIN {bin_number}: html_len={len(html)} preview={html[:400]!r}")

    violations, complaints, active_licenses = _extract_tables(html)
    logger.info(
        f"BIN {bin_number} project={pname}: "
        f"found {len(violations)} violation rows, "
        f"{len(complaints)} complaint rows, "
        f"{len(active_licenses)} active-permit license#s"
    )
    stats["licenses"] = active_licenses

    # Step 1 — stash the license number on the company doc. We only write
    # if the company doesn't already have one (manual entry wins; so does
    # NYC Open Data). Pick the first license encountered — in practice all
    # active permits at a property are filed by the same GC.
    if active_licenses and company_id:
        await _save_discovered_license(company_id, active_licenses[0], bin_number)

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

    # Mark the initial BIS scan done for this project so the next scan
    # can start firing email alerts on newly-discovered records.
    await _mark_initial_scan_done(project_id)
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
        raw = await db.projects.find({
            "track_dob_status": True,
            "nyc_bin":          {"$exists": True, "$ne": ""},
            "is_deleted":       {"$ne": True},
        }).to_list(500)
    except Exception as e:
        logger.error(f"project lookup failed: {e}")
        return []
    # Drop projects with placeholder BINs — they always warmup-timeout.
    kept, skipped = [], []
    for p in raw:
        if _is_real_bin(p.get("nyc_bin", "")):
            kept.append(p)
        else:
            skipped.append((p.get("name") or "?", p.get("nyc_bin") or "-"))
    if skipped:
        logger.info(
            f"skipped {len(skipped)} projects with placeholder/invalid BINs: "
            + ", ".join(f"{n}({b})" for n, b in skipped[:5])
            + (" …" if len(skipped) > 5 else "")
        )
    return kept


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

    # license → list of company_ids that surfaced this license during the
    # current scan run. A single license may appear on multiple projects
    # (shared GC), so we dedupe before running the insurance step.
    license_to_companies: Dict[str, List[str]] = {}

    async with async_playwright() as playwright:
        async def _one(p):
            async with sem:
                try:
                    st = await _process_project(playwright, p)
                    totals["processed"] += 1
                    for k in ("v_new", "v_crit", "c_new", "c_crit"):
                        totals[k] += st.get(k, 0)
                    cid = st.get("company_id") or ""
                    for lic in (st.get("licenses") or []):
                        license_to_companies.setdefault(lic, [])
                        if cid and cid not in license_to_companies[lic]:
                            license_to_companies[lic].append(cid)
                except Exception as e:
                    totals["failed"] += 1
                    logger.error(
                        f"project failed name={p.get('name')} "
                        f"bin={p.get('nyc_bin')}: {e.__class__.__name__}: {e}"
                    )

        await asyncio.gather(*[_one(p) for p in projects])

        # Seed license_to_companies with licenses that were set manually
        # on a company (via admin onboarding / GC autocomplete) but never
        # surfaced on a BIS permit scrape — e.g. the GC has an active
        # license in NYC Open Data but no current permits, or their
        # current projects haven't been added to LeveLog yet. Without
        # this, a freshly-created company's insurance would never get
        # auto-fetched. The `_insurance_fetch_due` gate prevents this
        # from being expensive (it short-circuits once records exist and
        # aren't near expiry).
        try:
            db = _get_db()
            cursor = db.companies.find(
                {
                    "gc_license_number": {"$exists": True, "$ne": ""},
                    "is_deleted": {"$ne": True},
                },
                {"_id": 1, "gc_license_number": 1},
            )
            async for company in cursor:
                lic = str(company.get("gc_license_number") or "").strip()
                if not lic:
                    continue
                cid = str(company.get("_id"))
                license_to_companies.setdefault(lic, [])
                if cid and cid not in license_to_companies[lic]:
                    license_to_companies[lic].append(cid)
        except Exception as e:
            logger.warning(f"company-license seed failed: {e}")

        # Step 2 + 3 — once all BINs are processed, fan out to the
        # Licensing portal per unique license number. This stays under
        # the outer async_playwright context so the Chromium runtime is
        # reused across both phases.
        if license_to_companies:
            logger.info(
                f"insurance step: {len(license_to_companies)} unique licenses "
                f"from this scan"
            )
            await _run_insurance_step(playwright, license_to_companies)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"BIS scan complete: processed={totals['processed']} failed={totals['failed']} "
        f"v_new={totals['v_new']} v_crit={totals['v_crit']} "
        f"c_new={totals['c_new']} c_crit={totals['c_crit']} "
        f"licenses_seen={len(license_to_companies)} elapsed={elapsed:.1f}s"
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
        f"proxy={'on' if PROXY_URL else 'off'}, "
        f"stealth={'on' if _STEALTH_OK else 'off'}"
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
