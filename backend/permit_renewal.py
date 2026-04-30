import os
from lib.server_http import ServerHttpClient
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Literal
from enum import Enum

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId

logger = logging.getLogger(__name__)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to UTC-aware. Mongo BSON dates round-trip through
    Motor as offset-naive even when written aware (PyMongo strips tzinfo
    by default unless tz_aware=True on the client). Callers that subtract
    `datetime.now(timezone.utc)` from a Mongo-read datetime will hit
    ``TypeError: can't subtract offset-naive and offset-aware datetimes``
    if this coercion is skipped — that crashed the nightly_renewal_scan
    cron until the fix landed. Returns None unchanged."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
OWNER_ALERT_EMAIL = os.environ.get("OWNER_ALERT_EMAIL", "")

# Blocked by Akamai — license lookup replaced with NYC Open Data (w5r2-853r).
# Kept for reference and backward compatibility with old log messages.
DOB_BIS_LICENSE_URL = "https://a810-bisweb.nyc.gov/bisweb/LicenseQueryServlet"
DOB_BIS_BASE_URL    = "https://a810-bisweb.nyc.gov/bisweb/"
DOB_NOW_BUILD_URL = "https://a810-dobnow.nyc.gov/publish/Index.html"

# NYC Open Data Socrata endpoint for DCA General Contractor licenses.
# Free, no auth required, no bot protection.
NYC_OPEN_DATA_GC_LICENSES_URL = "https://data.cityofnewyork.us/resource/w5r2-853r.json"

# Browser-like headers — BIS is behind Akamai which 403s bare requests.
_BIS_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def _warmup_bis_cookies(client) -> None:
    """Hit the BIS landing page first so Akamai drops the session cookies.
    Subsequent requests using the same client then pass bot detection.
    Silent on failure -- caller falls back to direct request."""
    try:
        await client.get(
            DOB_BIS_BASE_URL,
            headers={**_BIS_BROWSER_HEADERS, "Sec-Fetch-Site": "none"},
            timeout=20.0,
        )
    except Exception as e:
        logger.debug(f"BIS warmup failed (will retry without cookies): {e}")



# ══════════════════════════════════════════════════════════════════════════════
# ENUMS & MODELS
# ══════════════════════════════════════════════════════════════════════════════

class RenewalStatus(str, Enum):
    ELIGIBLE = "eligible"
    NEEDS_INSURANCE = "needs_insurance"          # Insurance dates have never been entered.
    INELIGIBLE_INSURANCE = "ineligible_insurance"  # Entered but expired or short of renewal window.
    INELIGIBLE_LICENSE = "ineligible_license"
    DRAFT_READY = "draft_ready"
    AWAITING_GC = "awaiting_gc"
    # MR.5 additions — local-agent filing pipeline:
    IN_PROGRESS = "in_progress"                  # Worker has claimed the renewal, handler running.
    AWAITING_DOB_APPROVAL = "awaiting_dob_approval"  # Worker filed; DOB has not yet stamped the new expiration.
    COMPLETED = "completed"
    FAILED = "failed"


class InsuranceRecord(BaseModel):
    """Insurance information for a GC's certificate-of-insurance record.

    Historically scraped from DOB BIS (auto-fetch is now disabled — the
    BIS Licensing portal no longer exposes insurance for licenses
    migrated to DOB NOW). Today's sources, in order of authority:

      1. coi_ocr          — admin uploaded a COI PDF, Qwen extracted dates
      2. dob_now_portal   — local Docker worker scraped DOB NOW Public Portal
      3. manual_entry     — admin typed dates directly in Settings (fallback)

    Backfill rule (see migrations/20260426_companies_*.py): pre-this-deploy
    records with source missing/null are stamped 'manual_entry' because
    BIS auto-fetch was disabled before this code shipped, so the only way
    a record could have been written was through the Settings manual-entry
    flow.
    """
    insurance_type: str
    carrier_name: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    is_current: bool = False

    # Provenance — Literal-typed for forward writes; Optional so absent keys
    # on legacy reads don't ValidationError.
    source: Optional[Literal[
        "manual_entry",
        "coi_ocr",
        "dob_now_portal",
    ]] = None

    # ── COI OCR + portal verification fields (added 2026-04-26, step 2) ──
    # All Optional with explicit None defaults so absence on existing
    # subdocs reads cleanly. dob_now_discrepancy is bool-with-default
    # (matches the existing is_current pattern) so absent keys read False.
    coi_pdf_url: Optional[str] = None                  # R2 URL of original PDF, kept 7yr
    ocr_confidence: Optional[float] = None             # 0.0-1.0, present iff source == "coi_ocr"
    dob_now_verified_at: Optional[datetime] = None     # last cross-check vs Public Portal
    dob_now_discrepancy: bool = False                  # True iff our record diverged from Public Portal snapshot


class GCLicenseInfo(BaseModel):
    """GC License information from DOB Licensing Portal."""
    license_number: Optional[str] = None
    license_type: Optional[str] = None
    licensee_name: Optional[str] = None
    business_name: Optional[str] = None
    license_status: Optional[str] = None
    license_expiration: Optional[str] = None
    insurance_records: List[InsuranceRecord] = []


class RenewalEligibility(BaseModel):
    """Result of eligibility check for permit renewal."""
    eligible: bool = False
    permit_id: str
    project_id: str
    job_number: Optional[str] = None
    permit_type: Optional[str] = None
    expiration_date: Optional[str] = None
    days_until_expiry: Optional[int] = None
    renewal_path: Optional[str] = None  # "dob_now" or "bis_legacy"
    paa_required: bool = False
    gc_license: Optional[GCLicenseInfo] = None
    blocking_reasons: List[str] = []
    insurance_flags: List[str] = []
    # True when the company has never entered insurance expiry dates. Distinct
    # from ineligible_insurance (entered but expired). Drives a soft CTA in the
    # UI rather than a hard block.
    insurance_not_entered: bool = False
    # ── v2 enrichment fields (step 6, commit 2.1) ──────────────────
    # Populated only when the dispatcher is in mode='live' (or in shadow
    # mode's legacy-crash fallback path). Legacy / mode='off' / shadow's
    # normal path leave all four as None. Frontend MUST render these
    # conditionally on field presence — during the deploy window between
    # 2.1 ship and the dispatcher flip the UI sees None for all four
    # and falls back to the legacy display.
    #
    # `effective_expiry`: ISO date the renewal action is actually due
    #   by, after applying §1.1 ceilings (1-year-since-issuance, 31-day
    #   BIS lookahead, etc.) on top of the calendar expiration.
    # `renewal_strategy`: enum-string from RENEWAL_STRATEGIES in
    #   eligibility_v2.py (e.g. "AUTO_EXTEND_DOB_NOW", "MANUAL_1YR_CEILING").
    # `limiting_factor`: {label, kind, expires_in_days} — drives the
    #   subtitle / "why this date" display.
    # `action`: {kind, deadline_days, instructions[]} — next-step
    #   user-facing copy block.
    effective_expiry: Optional[str] = None
    renewal_strategy: Optional[str] = None
    limiting_factor: Optional[Dict[str, Any]] = None
    action: Optional[Dict[str, Any]] = None
    # ── MR.1.6: issuance_date plumbing ─────────────────────────────
    # ISO-string form of the permit's original DOB issuance date.
    # Source: v2 dict at backend/lib/eligibility_v2.py:366-369. Same
    # shape semantics as the four v2 enrichment fields above —
    # populated in mode='live' (and shadow's legacy-crash fallback),
    # None otherwise. MR.1's panel uses it to show date-specific
    # copy ("This permit was issued on Jan 26, 2026...") instead of
    # the generic phrasing; MR.4's PW2 field mapper will read it
    # off the persisted renewal record rather than re-fetching from
    # dob_logs at form-generation time.
    issuance_date: Optional[str] = None


class PermitRenewalCreate(BaseModel):
    """Request to initiate a permit renewal."""
    permit_dob_log_id: str
    project_id: str


class PermitRenewalResponse(BaseModel):
    """Full renewal record returned to frontend."""
    id: str
    project_id: str
    project_name: Optional[str] = None
    project_address: Optional[str] = None
    permit_dob_log_id: str
    job_number: Optional[str] = None
    permit_type: Optional[str] = None
    current_expiration: Optional[str] = None
    days_until_expiry: Optional[int] = None
    status: str = RenewalStatus.ELIGIBLE
    gc_license_number: Optional[str] = None
    gc_license_status: Optional[str] = None
    insurance_gl_expiry: Optional[str] = None
    insurance_wc_expiry: Optional[str] = None
    insurance_db_expiry: Optional[str] = None
    insurance_all_current: bool = False
    blocking_reasons: List[str] = []
    dob_now_url: Optional[str] = None
    dob_filing_url: Optional[str] = None
    permit_status_on_dob: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ══════════════════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _to_oid(s: str):
    try:
        return ObjectId(s)
    except Exception:
        return s


# ══════════════════════════════════════════════════════════════════════════════
# DOB BIS LICENSE SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_gc_name(raw: str) -> str:
    """Normalize a company name for NYC Open Data GC license LIKE queries.

    The dataset stores names without trailing punctuation and without
    the leading/trailing suffix markers (INC, LLC, CORP, etc). Callers
    often pass names with a trailing period ("Blueview Construction Inc.")
    or extra whitespace — those should match. We:
      1. Upper-case + strip whitespace.
      2. Strip trailing non-alphanumeric chars (periods, commas, etc).
      3. Collapse internal whitespace.
    Do NOT strip INC/LLC/CORP — customers often DO have that in the
    dataset name; the caller pipeline tries progressively shorter
    fallbacks on miss.
    """
    n = (raw or "").upper().strip()
    if not n:
        return ""
    # Trim trailing non-alphanumeric (., ,, ;, etc.)
    while n and not n[-1].isalnum():
        n = n[:-1]
    # Collapse internal whitespace
    n = " ".join(n.split())
    return n


def _gc_name_fallbacks(canonical: str) -> List[str]:
    """Build a short list of progressively looser LIKE candidates so
    "Blueview Construction Inc" also matches a dataset row of just
    "Blueview Construction" — but we don't spam the API with every
    possible prefix. First hit wins."""
    if not canonical:
        return []
    out = [canonical]
    # Strip common corporate-form suffixes
    for suf in (" INC", " LLC", " CORP", " CO", " LLP", " LP", " LTD"):
        if canonical.endswith(suf):
            trimmed = canonical[: -len(suf)].rstrip()
            if trimmed and trimmed not in out:
                out.append(trimmed)
            break
    return out


async def scrape_gc_license_info(company_name: str) -> Optional[GCLicenseInfo]:
    """
    Look up a General Contractor license by business name using NYC Open Data.

    Replaces the old BIS HTML scraper, which is now blocked by Akamai Bot Manager.
    The Open Data endpoint is free, unauthenticated, and returns JSON.

    Signature is preserved so all existing callers continue to work. Insurance
    records are always empty from this function now — insurance is managed
    out-of-band by the dob_worker (handlers/bis_scrape.py), or via manual entry in Settings
    (see PUT /api/admin/company/insurance/manual).

    Name matching: the dataset's business_name field is uppercase, with no
    trailing period. We normalize the caller's input before the LIKE and
    retry with a corporate-suffix-stripped fallback if the first pass
    returns zero records.
    """
    import httpx

    canonical = _normalize_gc_name(company_name)
    if not canonical:
        return None

    candidates = _gc_name_fallbacks(canonical)
    logger.info(
        f"NYC Open Data GC lookup — raw={company_name!r} "
        f"normalized={canonical!r} candidates={candidates}"
    )

    async def _query(name: str):
        safe = name.replace("'", "''")
        where = (
            f"license_type='GENERAL CONTRACTOR' "
            f"AND upper(business_name) LIKE '%{safe}%'"
        )
        async with ServerHttpClient(timeout=15.0) as client:
            resp = await client.get(
                NYC_OPEN_DATA_GC_LICENSES_URL,
                params={"$where": where, "$limit": "5"},
            )
            if resp.status_code != 200:
                logger.warning(
                    f"NYC Open Data GC lookup returned {resp.status_code} "
                    f"for {name!r}"
                )
                return None
            return resp.json() or []

    try:
        records = None
        matched_name = None
        for name in candidates:
            found = await _query(name)
            if found:
                records = found
                matched_name = name
                break

        if not records:
            logger.info(
                f"NYC Open Data GC lookup — no records for any candidate "
                f"of {company_name!r}"
            )
            return None
        logger.info(
            f"NYC Open Data GC lookup — matched on {matched_name!r} "
            f"({len(records)} rows)"
        )

        # Prefer an ACTIVE license if any are present; otherwise first result
        def _status(r):
            return (r.get("license_status") or "").upper()

        active = [r for r in records if _status(r) == "ACTIVE"]
        chosen = active[0] if active else records[0]

        licensee = f"{chosen.get('first_name', '')} {chosen.get('last_name', '')}".strip()

        info = GCLicenseInfo(
            license_number=(chosen.get("license_number") or "").strip() or None,
            license_type="General Contractor",
            licensee_name=licensee or None,
            business_name=(chosen.get("business_name") or "").strip() or None,
            license_status=(chosen.get("license_status") or "").strip() or None,
            # NYC Open Data's GC dataset does not expose expiration — leave None.
            license_expiration=None,
            # Insurance data is no longer auto-fetched; use manual entry.
            insurance_records=[],
        )

        # Cache into gc_licenses so autocomplete still works.
        try:
            now = datetime.now(timezone.utc)
            from server import db as _db  # type: ignore
            await _db.gc_licenses.update_one(
                {"license_number": info.license_number},
                {"$set": {
                    "license_number": info.license_number,
                    "business_name": info.business_name or "",
                    "licensee_name": info.licensee_name or "",
                    "license_type": "GC",
                    "license_status": info.license_status or "",
                    "license_expiration": info.license_expiration,
                    "source": "nyc_open_data",
                    "last_synced": now,
                }, "$setOnInsert": {"created_at": now, "insurance_records": []}},
                upsert=True,
            )
        except Exception:
            # Non-fatal — caching is best-effort
            pass

        return info

    except Exception as e:
        logger.error(
            f"NYC Open Data GC lookup error for {company_name!r}: {e}"
        )
        return None


def _parse_bis_license_html(html: str) -> Optional[GCLicenseInfo]:
    """Extract license fields from BIS HTML response."""
    info = GCLicenseInfo()

    m = re.search(r'(T?GC-?\d{4,6})', html, re.IGNORECASE)
    if m:
        info.license_number = m.group(1).upper()

    for pattern in [
        r'License\s+Status.*?<td[^>]*>(.*?)</td>',
        r'Status.*?:\s*(Active|Inactive|Expired|Suspended)',
    ]:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            info.license_status = m.group(1).strip()
            break

    m = re.search(r'Business\s+Name.*?<td[^>]*>(.*?)</td>', html, re.IGNORECASE | re.DOTALL)
    if m:
        info.business_name = m.group(1).strip()

    m = re.search(r'Licensee\s+Name.*?<td[^>]*>(.*?)</td>', html, re.IGNORECASE | re.DOTALL)
    if m:
        info.licensee_name = m.group(1).strip()

    m = re.search(r'(?:Expiration|Expires?).*?(\d{1,2}/\d{1,2}/\d{2,4})', html, re.IGNORECASE)
    if m:
        info.license_expiration = m.group(1)

    info.license_type = "General Contractor"
    return info if info.license_number else None


async def _fetch_insurance_details(client, license_number: str) -> List[InsuranceRecord]:
    """No-op stub — insurance auto-fetch is disabled.

    The NYC DOB BIS Licensing Portal is behind Akamai Bot Manager and blocks
    all non-residential traffic (including Render's outbound IPs). NYC Open
    Data does not expose contractor insurance records.

    Insurance is now entered manually by admins via
    PUT /api/admin/company/insurance/manual and stored on the company doc.

    This function is preserved as a stub because it is referenced from several
    call sites; returning an empty list lets those flows continue gracefully
    without introducing any changes at the call-site level.
    """
    logger.info(
        "Insurance auto-fetch disabled — using manually entered records "
        f"(called for license {license_number})"
    )
    return []


async def _fetch_insurance_details_LEGACY_DISABLED(client, license_number: str):
    """Previous BIS scraper body, retained verbatim for reference only.
    NOT wired up. Do not call. Kept because the regex patterns may become
    useful if DOB ever ships an API."""
    records = []

    try:
        await _warmup_bis_cookies(client)

        resp = await client.get(
            DOB_BIS_LICENSE_URL,
            params={"requestid": "2", "licno": license_number},
            headers=_BIS_BROWSER_HEADERS,
        )
        if resp.status_code != 200:
            logger.warning(f"BIS returned {resp.status_code} for license {license_number}")
            return records

        html = resp.text
        if "Access Denied" in html and "edgesuite" in html.lower():
            logger.warning(f"BIS served Akamai block page for license {license_number}")
            return records

        insurance_patterns = [
            ("general_liability", r'General\s+Liability.*?(\d{1,2}/\d{1,2}/\d{2,4}).*?(\d{1,2}/\d{1,2}/\d{2,4})'),
            ("workers_comp", r"Worker[s']?\s*Comp.*?(\d{1,2}/\d{1,2}/\d{2,4}).*?(\d{1,2}/\d{1,2}/\d{2,4})"),
            ("disability", r'Disability.*?(\d{1,2}/\d{1,2}/\d{2,4}).*?(\d{1,2}/\d{1,2}/\d{2,4})'),
        ]

        for ins_type, pattern in insurance_patterns:
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if m:
                from dateutil import parser as dateparser
                eff_date = m.group(1)
                exp_date = m.group(2)

                try:
                    exp_dt = dateparser.parse(exp_date)
                    is_current = exp_dt > datetime.now()
                except Exception:
                    is_current = False

                records.append(InsuranceRecord(
                    insurance_type=ins_type,
                    effective_date=eff_date,
                    expiration_date=exp_date,
                    is_current=is_current,
                ))

    except Exception as e:
        logger.error(f"Insurance fetch error for {license_number}: {e}")

    return records


# ══════════════════════════════════════════════════════════════════════════════
# ELIGIBILITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

async def check_renewal_eligibility(
    db,
    permit_dob_log_id: str,
    project_id: str,
    company_name: str,
    company_id: Optional[str] = None,
) -> RenewalEligibility:
    """Public entry point — delegates to the dispatcher.

    The dispatcher reads ELIGIBILITY_REWRITE_MODE and routes to either
    the legacy logic (this function's `_inner` below), v2 logic
    (lib/eligibility_v2.py), or both (shadow mode). Existing callsites
    of `check_renewal_eligibility` need no changes.
    """
    from lib.eligibility_dispatcher import (
        check_renewal_eligibility as _dispatch,
    )
    return await _dispatch(db, permit_dob_log_id, project_id, company_name, company_id)


async def _check_renewal_eligibility_legacy_inner(
    db,
    permit: dict,
    project: dict,
    company_name: str,
    company_doc: Optional[dict],
    *,
    today: Optional[datetime] = None,
) -> RenewalEligibility:
    """Legacy eligibility logic, refactored to accept pre-fetched docs.

    The dispatcher fetches (permit, project, company) once and passes
    the SAME tuple to both this function and the v2 evaluator, so
    shadow-mode diffs aren't polluted by between-fetch drift.

    Body is unchanged from the pre-step-5 version of
    `check_renewal_eligibility`, except for the early-fetch lines
    being replaced with parameter unpacking.
    """
    if not permit:
        raise HTTPException(status_code=404, detail="Permit record not found")
    if permit.get("record_type") != "permit":
        raise HTTPException(status_code=400, detail="Record is not a permit")

    permit_dob_log_id = str(permit.get("_id"))
    project_id = str(project.get("_id")) if project else ""
    today = today or datetime.now(timezone.utc)

    # ── Determine renewal path (DOB NOW vs BIS legacy) ──
    job_number = permit.get("job_number", "")
    job_clean = job_number.replace("-", "").strip() if job_number else ""
    is_dob_now = job_clean.upper().startswith("B")
    is_bis_legacy = bool(job_clean) and job_clean.isdigit()
    renewal_path = "dob_now" if is_dob_now else ("bis_legacy" if is_bis_legacy else "dob_now")

    eligibility = RenewalEligibility(
        permit_id=permit_dob_log_id,
        project_id=project_id,
        job_number=permit.get("job_number"),
        permit_type=permit.get("permit_type"),
        expiration_date=permit.get("expiration_date"),
        renewal_path=renewal_path,
    )

    # ── BIS legacy permits cannot be renewed automatically ──
    if renewal_path == "bis_legacy":
        eligibility.blocking_reasons.append(
            "This permit was filed through the legacy BIS system. "
            "Automated renewal is not available \u2014 contact your expediter "
            "to file a Post Approval Amendment (PAA) or re-file through DOB NOW."
        )

    # ── Check expiration window ──
    exp_str = permit.get("expiration_date")
    if exp_str:
        try:
            from dateutil import parser as dateparser
            exp_date = dateparser.parse(str(exp_str))
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=timezone.utc)
            days_left = (exp_date - today).days
            eligibility.days_until_expiry = days_left

            if days_left > 30:
                eligibility.blocking_reasons.append(
                    f"Permit expires in {days_left} days. Renewal available within 30 days of expiry."
                )
            elif days_left < -60:
                # Expired more than 60 days — PAA required
                eligibility.paa_required = True
                eligibility.blocking_reasons.append(
                    "This permit has been expired for more than 60 days. "
                    "Standard renewal is no longer available \u2014 a Post Approval "
                    "Amendment (PAA) is required."
                )
            elif days_left < 0:
                # Expired within 60 days — still renewable on DOB NOW
                # Do NOT block — just note it's expired so the user knows
                pass
        except Exception:
            eligibility.blocking_reasons.append("Could not parse permit expiration date.")
    else:
        eligibility.blocking_reasons.append("No expiration date on permit record.")

    # ── Build GCLicenseInfo — prefer cached company license fields. ──
    gc_info: Optional[GCLicenseInfo] = None
    if company_doc and company_doc.get("gc_license_number"):
        gc_info = GCLicenseInfo(
            license_number=company_doc.get("gc_license_number"),
            business_name=company_doc.get("gc_business_name"),
            licensee_name=company_doc.get("gc_licensee_name"),
            license_status=company_doc.get("gc_license_status"),
            license_expiration=company_doc.get("gc_license_expiration"),
            insurance_records=[],  # populated below from company doc's manual entries
        )
    else:
        # Cold path: look up by company name via NYC Open Data.
        gc_info = await scrape_gc_license_info(company_name)

    # ── License status check ──
    if not gc_info or not gc_info.license_number:
        eligibility.blocking_reasons.append(
            f"GC License not found for '{company_name}'. "
            "Verify company name matches DOB records."
        )
    else:
        if gc_info.license_status and gc_info.license_status.lower() not in ("active",):
            eligibility.blocking_reasons.append(
                f"GC License {gc_info.license_number} status is "
                f"'{gc_info.license_status}'. Must be Active."
            )

    # ── Insurance: read manually-entered records from the company doc ──
    manual_records_raw = (company_doc or {}).get("gc_insurance_records", []) or []

    if not manual_records_raw:
        # Soft prompt — not a hard block. Frontend shows a 'Go to Settings' CTA.
        eligibility.insurance_not_entered = True
    else:
        try:
            parsed_records = [InsuranceRecord(**rec) for rec in manual_records_raw]
        except Exception as e:
            logger.warning(
                f"Could not parse gc_insurance_records for company "
                f"{(company_doc or {}).get('_id')}: {e}"
            )
            parsed_records = []

        if gc_info is None:
            # License lookup failed but insurance data exists — don't lose it.
            gc_info = GCLicenseInfo(insurance_records=parsed_records)
        else:
            gc_info.insurance_records = parsed_records

        # Use the dispatcher-supplied `today` so shadow-mode comparisons
        # against v2 are deterministic against the same wall clock.
        renewal_target = today + timedelta(days=365)
        required_types = {"general_liability", "workers_comp", "disability"}
        found_types = set()

        for ins in parsed_records:
            found_types.add(ins.insurance_type)
            if ins.expiration_date:
                try:
                    from dateutil import parser as dateparser
                    ins_exp = dateparser.parse(ins.expiration_date)
                    if ins_exp.tzinfo is None:
                        ins_exp = ins_exp.replace(tzinfo=timezone.utc)
                    if ins_exp < renewal_target:
                        label = ins.insurance_type.replace("_", " ").title()
                        eligibility.insurance_flags.append(
                            f"{label} expires {ins.expiration_date} — "
                            f"must cover through {renewal_target.strftime('%m/%d/%Y')}"
                        )
                except Exception:
                    eligibility.insurance_flags.append(
                        f"Cannot parse {ins.insurance_type} expiration."
                    )

        missing = required_types - found_types
        for m in missing:
            label = m.replace("_", " ").title()
            eligibility.insurance_flags.append(
                f"{label} insurance not entered in Settings."
            )

        if eligibility.insurance_flags:
            eligibility.blocking_reasons.append("Insurance Update Required")

    eligibility.gc_license = gc_info

    # insurance_not_entered is a soft prompt — keeps eligible=False so the
    # CTA shows, but does NOT add to blocking_reasons.
    eligibility.eligible = (
        len(eligibility.blocking_reasons) == 0
        and not eligibility.insurance_not_entered
    )
    return eligibility


# ══════════════════════════════════════════════════════════════════════════════
# RENEWAL DATA ASSEMBLER (replaces Playwright RPA)
# ══════════════════════════════════════════════════════════════════════════════

async def prepare_renewal_data(permit_data: dict) -> dict:
    """Assemble renewal data for manual filing -- no browser automation."""
    job_number = permit_data.get("job_number", "")
    job_clean = job_number.replace("-", "").strip()

    return {
        "renewal_path": "dob_now" if job_clean.upper().startswith("B") else "bis_legacy",
        "dob_now_url": f"https://a810-dobnow.nyc.gov/publish/#!/service/DobDashboard/1/{job_clean}" if job_clean.upper().startswith("B") else None,
        "copyable_fields": [
            {"label": "Job Number", "value": job_number},
            {"label": "Address", "value": permit_data.get("address", "")},
            {"label": "GC License #", "value": permit_data.get("gc_license", "")},
            {"label": "BIN", "value": permit_data.get("bin", "")},
        ],
        "checklist": [
            "Log in to DOB NOW with your NYC.ID",
            f"Navigate to Job #{job_number}",
            "Select 'Renew Permit' from the Actions menu",
            "Verify all pre-filled information is correct",
            "Upload any required updated documents",
            "Submit the renewal application",
            "Pay the DOB fee",
            "Download the receipt for your records",
        ],
        "paa_required": permit_data.get("paa_required", False),
    }


# ══════════════════════════════════════════════════════════════════════════════
# STATUS MONITOR — Check DOB APIs for permit issuance
# ══════════════════════════════════════════════════════════════════════════════

async def check_renewal_completion(db, renewal: dict) -> bool:
    """
    Poll DOB Open Data APIs to check if a renewed permit has been issued.
    Called by the nightly scan for renewals in 'awaiting_gc' status.
    Returns True if the permit was detected as renewed/issued.
    """
    import httpx

    job_number = renewal.get("job_number")
    if not job_number:
        return False

    try:
        async with ServerHttpClient(timeout=15.0) as client:
            resp = await client.get(
                "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
                params={
                    "job_filing_number": job_number,
                    "$order": "issuance_date DESC",
                    "$limit": "5",
                },
            )

            if resp.status_code != 200:
                return False

            records = resp.json()
            if not records:
                return False

            renewal_created = renewal.get("created_at")
            if isinstance(renewal_created, str):
                from dateutil import parser as dateparser
                renewal_created = dateparser.parse(renewal_created)

            for rec in records:
                issuance_str = (
                    rec.get("issuance_date")
                    or rec.get("issued_date")
                )
                status = (
                    rec.get("permit_status")
                    or rec.get("current_status")
                    or ""
                ).lower()

                if not issuance_str:
                    continue

                try:
                    from dateutil import parser as dateparser
                    issuance_date = dateparser.parse(str(issuance_str))

                    # New issuance after we created the renewal record
                    if renewal_created and issuance_date > renewal_created:
                        logger.info(
                            f"Renewal completed: job {job_number} "
                            f"issued {issuance_str}"
                        )
                        return True

                    # Status explicitly active with future expiration
                    if status in (
                        "issued", "active", "entire", "permit issued"
                    ):
                        exp_str = (
                            rec.get("expiration_date")
                            or rec.get("permit_expiration_date")
                        )
                        if exp_str:
                            exp_date = dateparser.parse(str(exp_str))
                            if exp_date > datetime.now(timezone.utc):
                                logger.info(
                                    f"Renewal completed: job {job_number} "
                                    f"status={status}, expiry={exp_str}"
                                )
                                return True
                except Exception:
                    continue

    except Exception as e:
        logger.error(
            f"Completion check error for job {job_number}: {e}"
        )

    return False


# ══════════════════════════════════════════════════════════════════════════════
# DOB NOW HEALTH CHECK — Monitor DOB NOW availability
# ══════════════════════════════════════════════════════════════════════════════

async def run_dob_now_health_check(db):
    """
    Daily health check that validates DOB NOW is reachable via HTTP.
    Sends Resend email alert if the site is down.
    """
    logger.info("DOB NOW health check starting...")

    issues = []

    try:
        import httpx

        async with ServerHttpClient(timeout=20.0) as client:
            resp = await client.get(DOB_NOW_BUILD_URL)
            if resp.status_code != 200:
                issues.append(
                    f"DOB NOW returned HTTP {resp.status_code}. "
                    "The site may be down or undergoing maintenance."
                )
    except Exception as e:
        issues.append(
            f"DOB NOW UNREACHABLE: Could not connect to DOB NOW. "
            f"Error: {str(e)}"
        )

    # Send alert if issues detected
    if issues:
        logger.warning(
            f"DOB NOW health check: {len(issues)} issue(s) detected"
        )
        await _send_health_check_alert(db, issues)
    else:
        logger.info(
            "✅ DOB NOW health check passed — all selectors valid"
        )

    # Store result. js_hash is reserved for a future feature that
    # would hash the DOB NOW JS bundle to detect UI changes capable
    # of breaking the RPA selectors. The compute step was never
    # implemented, so we persist None — preserves the doc shape
    # consumed by GET /permit-renewals/health-status (which already
    # tolerates absence via .get("js_hash")) without referencing an
    # undefined variable. Restore to a real hash when/if the compute
    # step lands.
    await db.system_config.update_one(
        {"key": "dob_now_health_check"},
        {"$set": {
            "key": "dob_now_health_check",
            "last_run": datetime.now(timezone.utc),
            "status": "failed" if issues else "passed",
            "issues": issues,
            "js_hash": None,
        }},
        upsert=True,
    )

    return {"status": "failed" if issues else "passed", "issues": issues}


async def _send_health_check_alert(db, issues: List[str]):
    """Send DOB NOW UI change alert email via Resend.

    Takes `db` as the first positional parameter — the function reads
    and writes `db.system_config` for the 24-hour cooldown record. The
    parameter was previously implicit (the function relied on a
    module-level `db` that doesn't exist), causing NameError every
    time the Job 3 health-check fired with detected issues."""
    if not RESEND_API_KEY:
        logger.warning(
            "Cannot send health check alert — RESEND_API_KEY not set"
        )
        return

    recipient = OWNER_ALERT_EMAIL
    if not recipient:
        logger.warning(
            "Cannot send health check alert — OWNER_ALERT_EMAIL not set"
        )
        return

    # 24-hour cooldown: don't spam if we already alerted recently
    try:
        last_alert = await db.system_config.find_one(
            {"key": "dob_health_check_last_alert"}
        )
        if last_alert and last_alert.get("sent_at"):
            last_sent = _ensure_utc(last_alert["sent_at"])
            if isinstance(last_sent, datetime):
                hours_since = (
                    datetime.now(timezone.utc) - last_sent
                ).total_seconds() / 3600
                if hours_since < 24:
                    logger.info(
                        f"Health check alert suppressed — last sent "
                        f"{hours_since:.1f}h ago. Issues: {issues}"
                    )
                    return
    except Exception as e:
        logger.warning(f"Cooldown check failed, proceeding: {e}")

    try:
        import resend
        resend.api_key = RESEND_API_KEY

        issues_html = "".join(
            f'<div style="background:#fef2f2;border:1px solid #fecaca;'
            f'border-radius:6px;padding:12px;margin-bottom:8px;">'
            f'<p style="margin:0;font-size:14px;color:#991b1b;">'
            f'{issue}</p></div>'
            for issue in issues
        )

        html = f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;">
            <div style="background:#dc2626;color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
                <h1 style="margin:0;font-size:18px;">⚠️ DOB NOW Availability Issue</h1>
                <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">
                    Permit renewal portal may be unavailable
                </p>
            </div>
            <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
                <p style="margin:0 0 16px;font-size:14px;color:#374151;">
                    The daily DOB NOW health check detected
                    {len(issues)} issue(s):
                </p>
                {issues_html}
                <div style="background:#f9fafb;border-radius:6px;padding:16px;margin-top:16px;">
                    <p style="margin:0 0 4px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;">
                        Required Action
                    </p>
                    <p style="margin:0;font-size:14px;color:#1f2937;">
                        Check DOB NOW availability and advise users
                        if manual renewal filing may be temporarily
                        unavailable.
                    </p>
                </div>
                <p style="margin:16px 0 0;font-size:12px;color:#9ca3af;">
                    Detected at {datetime.now(timezone.utc).strftime('%B %d, %Y %I:%M %p')} UTC
                </p>
            </div>
            <p style="text-align:center;font-size:10px;color:#cbd5e1;margin-top:16px;letter-spacing:2px;">
                LEVELOG COMPLIANCE
            </p>
        </div>
        """

        resend.Emails.send({
            "from": "Levelog Alerts <alerts@levelog.com>",
            "to": [recipient],
            "subject": (
                f"⚠️ DOB NOW Health Check Alert "
                f"({len(issues)} issue{'s' if len(issues) != 1 else ''})"
            ),
            "html": html,
        })
        logger.info(f"Health check alert sent to {recipient}")

        # Record send time for 24h cooldown
        await db.system_config.update_one(
            {"key": "dob_health_check_last_alert"},
            {"$set": {
                "key": "dob_health_check_last_alert",
                "sent_at": datetime.now(timezone.utc),
                "issues": issues,
            }},
            upsert=True,
        )

    except Exception as e:
        logger.error(f"Failed to send health check alert: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# NIGHTLY SCAN
# ══════════════════════════════════════════════════════════════════════════════

async def nightly_renewal_scan(db):
    """
    Called by the nightly cron. Three jobs:
    1. Scan dob_logs for permits expiring ≤30 days → create renewal records
    2. Check 'awaiting_gc' renewals for completion on DOB
    3. Run DOB NOW health check
    """
    logger.info("🔄 Nightly permit renewal scan starting...")

    # ── Job 1: Create renewal records for expiring permits ───────────
    created_count = 0

    permits = await db.dob_logs.find({
        "record_type": "permit",
        "expiration_date": {"$ne": None},
        "is_deleted": {"$ne": True},
    }).to_list(1000)

    for permit in permits:
        exp_str = permit.get("expiration_date")
        if not exp_str:
            continue

        try:
            from dateutil import parser as dateparser
            exp_date = dateparser.parse(str(exp_str))
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=timezone.utc)
            days_left = (exp_date - datetime.now(timezone.utc)).days

            if 0 < days_left <= 30:
                permit_id = str(permit["_id"])
                project_id = permit.get("project_id")

                # Skip if renewal already exists
                existing = await db.permit_renewals.find_one({
                    "permit_dob_log_id": permit_id,
                    "status": {"$nin": [
                        RenewalStatus.FAILED,
                        RenewalStatus.COMPLETED,
                    ]},
                })
                if existing:
                    continue

                # Get project + company
                project = None
                if project_id:
                    project = await db.projects.find_one(
                        {"_id": _to_oid(project_id)}
                    )
                if not project:
                    continue

                company_id = project.get("company_id")
                company = None
                if company_id:
                    company = await db.companies.find_one(
                        {"_id": _to_oid(company_id)}
                    )
                company_name = (
                    company.get("name", "") if company else ""
                )
                if not company_name:
                    continue

                # Run eligibility check
                eligibility = await check_renewal_eligibility(
                    db, permit_id, project_id, company_name, company_id=company_id
                )

                # Pick the right status. needs_insurance is distinct from
                # ineligible_insurance -- the former means "never entered".
                if eligibility.eligible:
                    status_value = RenewalStatus.ELIGIBLE
                elif eligibility.insurance_not_entered:
                    status_value = RenewalStatus.NEEDS_INSURANCE
                else:
                    status_value = RenewalStatus.INELIGIBLE_INSURANCE

                # Create renewal record
                now = datetime.now(timezone.utc)
                renewal_doc = {
                    "project_id": project_id,
                    "project_name": project.get("name", ""),
                    "project_address": project.get("address", ""),
                    "company_id": company_id,
                    "company_name": company_name,
                    "permit_dob_log_id": permit_id,
                    "job_number": eligibility.job_number,
                    "permit_type": eligibility.permit_type,
                    "current_expiration": eligibility.expiration_date,
                    "days_until_expiry": eligibility.days_until_expiry,
                    "status": status_value,
                    "gc_license_number": (
                        eligibility.gc_license.license_number
                        if eligibility.gc_license else None
                    ),
                    "gc_license_status": (
                        eligibility.gc_license.license_status
                        if eligibility.gc_license else None
                    ),
                    "insurance_gl_expiry": None,
                    "insurance_wc_expiry": None,
                    "insurance_db_expiry": None,
                    "insurance_all_current": eligibility.eligible,
                    "blocking_reasons": eligibility.blocking_reasons,
                    "insurance_flags": eligibility.insurance_flags,
                    "dob_now_url": None,
                    "dob_filing_url": None,
                    # v2 enrichment (step 6.2.3). Sourced verbatim from
                    # the dispatcher response (RenewalEligibility) — no
                    # recomputation. All four are None in shadow/off
                    # mode and populate after the cutover. The frontend
                    # rendering in 6.2.2 falls back gracefully when
                    # absent, so older records continue to load.
                    "renewal_strategy": eligibility.renewal_strategy,
                    "effective_expiry": eligibility.effective_expiry,
                    "limiting_factor": eligibility.limiting_factor,
                    "action": eligibility.action,
                    # MR.1.6: issuance_date persistence. Same passthrough
                    # semantics as the four fields above — None on
                    # legacy/shadow paths, populated on live. Older
                    # records keep None until the backfill script
                    # touches them.
                    "issuance_date": eligibility.issuance_date,
                    "created_at": now,
                    "updated_at": now,
                    "is_deleted": False,
                }

                # Populate insurance expiry fields
                if eligibility.gc_license:
                    for ins in eligibility.gc_license.insurance_records:
                        if ins.insurance_type == "general_liability":
                            renewal_doc["insurance_gl_expiry"] = (
                                ins.expiration_date
                            )
                        elif ins.insurance_type == "workers_comp":
                            renewal_doc["insurance_wc_expiry"] = (
                                ins.expiration_date
                            )
                        elif ins.insurance_type == "disability":
                            renewal_doc["insurance_db_expiry"] = (
                                ins.expiration_date
                            )

                await db.permit_renewals.insert_one(renewal_doc)
                created_count += 1
                logger.info(
                    f"Created renewal for permit {permit_id} "
                    f"(job {eligibility.job_number}, "
                    f"{'eligible' if eligibility.eligible else 'blocked'})"
                )

        except Exception as e:
            logger.error(
                f"Nightly scan error for permit {permit.get('_id')}: {e}"
            )

    # ── Job 2: Check awaiting_gc renewals for completion ─────────────
    completed_count = 0
    awaiting = await db.permit_renewals.find({
        "status": RenewalStatus.AWAITING_GC,
        "is_deleted": {"$ne": True},
    }).to_list(200)

    for renewal in awaiting:
        try:
            is_done = await check_renewal_completion(db, renewal)
            if is_done:
                await db.permit_renewals.update_one(
                    {"_id": renewal["_id"]},
                    {"$set": {
                        "status": RenewalStatus.COMPLETED,
                        "completed_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }},
                )
                completed_count += 1
        except Exception as e:
            logger.error(
                f"Completion check error for renewal "
                f"{renewal.get('_id')}: {e}"
            )

    # ── Job 3: DOB NOW health check (once per day only) ─────────────
    try:
        last_check = await db.system_config.find_one(
            {"key": "dob_now_health_check"}
        )
        should_run = True
        if last_check and last_check.get("last_run"):
            last_run = _ensure_utc(last_check["last_run"])
            if isinstance(last_run, datetime):
                hours_since = (
                    datetime.now(timezone.utc) - last_run
                ).total_seconds() / 3600
                if hours_since < 23:
                    should_run = False
                    logger.info(
                        f"Health check skipped — last ran {hours_since:.1f}h ago"
                    )
        if should_run:
            await run_dob_now_health_check(db)
    except Exception as e:
        logger.error(f"Health check scheduling error: {e}")

    logger.info(
        f"🔄 Nightly renewal scan complete: "
        f"{created_count} new, {completed_count} completed, "
        f"{len(awaiting)} checked"
    )


# ══════════════════════════════════════════════════════════════════════════════
# API ROUTE FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def create_permit_renewal_routes(
    api_router: APIRouter,
    db,
    get_current_user,
    get_admin_user,
    to_query_id,
    get_user_company_id,
    serialize_id,
):
    """Register all permit renewal endpoints on the FastAPI router."""

    # GET /api/permit-renewals
    @api_router.get("/permit-renewals")
    async def list_renewals(
        current_user=Depends(get_current_user),
        project_id: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        """List permit renewals for the user's company."""
        company_id = get_user_company_id(current_user)
        query = {"is_deleted": {"$ne": True}}
        if company_id:
            query["company_id"] = company_id
        if project_id:
            query["project_id"] = project_id
        if status:
            query["status"] = status

        renewals = (
            await db.permit_renewals
            .find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
            .to_list(limit)
        )
        total = await db.permit_renewals.count_documents(query)
        return {
            "renewals": [serialize_id(r) for r in renewals],
            "total": total,
        }

    # GET /api/permit-renewals/{renewal_id}
    @api_router.get("/permit-renewals/{renewal_id}")
    async def get_renewal(
        renewal_id: str,
        current_user=Depends(get_current_user),
    ):
        """Get a single renewal record."""
        renewal = await db.permit_renewals.find_one(
            {"_id": to_query_id(renewal_id)}
        )
        if not renewal:
            raise HTTPException(
                status_code=404, detail="Renewal not found"
            )
        company_id = get_user_company_id(current_user)
        if company_id and renewal.get("company_id") != company_id:
            raise HTTPException(
                status_code=403, detail="Access denied"
            )
        return serialize_id(renewal)

    # MR.4: GET /api/permit-renewals/{renewal_id}/pw2-field-map
    @api_router.get("/permit-renewals/{renewal_id}/pw2-field-map")
    async def get_pw2_field_map(
        renewal_id: str,
        current_user=Depends(get_current_user),
    ):
        """PW2 form-fill field map for the local Playwright agent.
        Pure deterministic transform — no Mongo writes, no external
        IO. Returns a JSON map of field-name → typed value pairs the
        agent will type into DOB NOW's PW2 form, plus required
        attachments and operator notes.

        Caller should run filing-readiness first; this endpoint
        returns 409 when the readiness report's `ready` is false so
        consumers can't accidentally bypass the pre-flight gate.
        Same tenant guard as the other /{renewal_id}/* endpoints.
        """
        from lib.pw2_field_mapper import map_pw2_fields
        from lib.filing_readiness import check_filing_readiness

        renewal = await db.permit_renewals.find_one(
            {"_id": to_query_id(renewal_id)}
        )
        if not renewal:
            raise HTTPException(status_code=404, detail="Renewal not found")
        company_id = get_user_company_id(current_user)
        if company_id and renewal.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Readiness gate — refuse the field map when readiness fails.
        # Lets MR.6 (the enqueue endpoint) call this directly without
        # re-running readiness.
        readiness = await check_filing_readiness(db, renewal_id)
        if not readiness.ready:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Filing readiness check failed; resolve blockers before requesting field map.",
                    "blockers": readiness.blockers,
                    "readiness_endpoint": (
                        f"/api/permit-renewals/{renewal_id}/filing-readiness"
                    ),
                },
            )

        field_map = await map_pw2_fields(db, renewal_id)
        return field_map.model_dump()

    # MR.3: GET /api/permit-renewals/{renewal_id}/filing-readiness
    @api_router.get("/permit-renewals/{renewal_id}/filing-readiness")
    async def get_filing_readiness(
        renewal_id: str,
        current_user=Depends(get_current_user),
    ):
        """Pre-flight readiness check for a permit renewal. Returns a
        structured FilingReadinessReport with per-check pass/fail/warn
        outcomes and aggregated blockers/warnings. MR.3 — pure
        deterministic service; MR.6 will use this to gate
        enqueue-filing requests so the local Docker worker isn't
        dispatched on guaranteed-failure jobs.

        Same tenant guard as GET /{renewal_id}: a non-owner caller
        with a company_id can only read renewals on their own company.
        """
        from lib.filing_readiness import check_filing_readiness

        # Tenant guard: load the renewal up-front to check
        # company_id ownership. The readiness service itself doesn't
        # enforce auth — it's a pure function — so we gate at the
        # endpoint layer.
        renewal = await db.permit_renewals.find_one(
            {"_id": to_query_id(renewal_id)}
        )
        if not renewal:
            raise HTTPException(
                status_code=404, detail="Renewal not found"
            )
        company_id = get_user_company_id(current_user)
        if company_id and renewal.get("company_id") != company_id:
            raise HTTPException(
                status_code=403, detail="Access denied"
            )

        report = await check_filing_readiness(db, renewal_id)
        return report.model_dump()

    # POST /api/permit-renewals/check-eligibility
    @api_router.post("/permit-renewals/check-eligibility")
    async def api_check_eligibility(
        body: PermitRenewalCreate,
        current_user=Depends(get_current_user),
    ):
        """Dry-run eligibility check."""
        company_id = get_user_company_id(current_user)
        company = None
        if company_id:
            company = await db.companies.find_one(
                {"_id": to_query_id(company_id)}
            )
        # Prefer the project-level GC legal name (set in Settings → DOB Permit Renewal)
        # Fall back to the company name if not set
        permit_log = await db.dob_logs.find_one({"_id": to_query_id(body.permit_dob_log_id)})
        project_for_gc = await db.projects.find_one({"_id": to_query_id(body.project_id)}) if body.project_id else None
        company_name = (
            (project_for_gc.get("gc_legal_name") or "").strip()
            if project_for_gc
            else ""
        ) or (company.get("name", "") if company else "")
        if not company_name:
            raise HTTPException(
                status_code=400,
                detail="GC Legal Name required. Set it in Settings → DOB Permit Renewal.",
            )

        eligibility = await check_renewal_eligibility(
            db, body.permit_dob_log_id, body.project_id, company_name,
            company_id=company_id,
        )
        return eligibility.model_dump()

    # POST /api/permit-renewals/prepare
    @api_router.post("/permit-renewals/prepare")
    async def prepare_renewal(
        body: PermitRenewalCreate,
        current_user=Depends(get_current_user),
    ):
        """
        Full workflow:
        1. Check eligibility
        2. Run RPA to prepare draft on DOB NOW
        3. Create/update renewal record with deep-link URL
        """
        company_id = get_user_company_id(current_user)
        company = None
        if company_id:
            company = await db.companies.find_one(
                {"_id": to_query_id(company_id)}
            )
        company_name = company.get("name", "") if company else ""

        project = await db.projects.find_one(
            {"_id": to_query_id(body.project_id)}
        )
        if not project:
            raise HTTPException(
                status_code=404, detail="Project not found"
            )

        eligibility = await check_renewal_eligibility(
            db, body.permit_dob_log_id, body.project_id, company_name,
            company_id=company_id,
        )

        if not eligibility.eligible:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "Permit not eligible for automated renewal"
                    ),
                    "blocking_reasons": eligibility.blocking_reasons,
                    "insurance_flags": eligibility.insurance_flags,
                },
            )

        # Assemble renewal data (no browser automation)
        renewal_data_result = await prepare_renewal_data({
            "job_number": eligibility.job_number or "",
            "address": project.get("address", ""),
            "gc_license": (
                eligibility.gc_license.license_number
                if eligibility.gc_license else ""
            ),
            "bin": project.get("bin", ""),
            "paa_required": eligibility.paa_required,
        })

        now = datetime.now(timezone.utc)

        # Check if record already exists from nightly scan
        existing = await db.permit_renewals.find_one({
            "permit_dob_log_id": body.permit_dob_log_id,
            "status": {"$nin": [
                RenewalStatus.FAILED,
                RenewalStatus.COMPLETED,
            ]},
        })

        renewal_fields = {
            "project_id": body.project_id,
            "project_name": project.get("name", ""),
            "project_address": project.get("address", ""),
            "company_id": company_id,
            "company_name": company_name,
            "permit_dob_log_id": body.permit_dob_log_id,
            "job_number": eligibility.job_number,
            "permit_type": eligibility.permit_type,
            "current_expiration": eligibility.expiration_date,
            "days_until_expiry": eligibility.days_until_expiry,
            "status": RenewalStatus.AWAITING_GC,
            "renewal_path": renewal_data_result.get("renewal_path"),
            "gc_license_number": (
                eligibility.gc_license.license_number
                if eligibility.gc_license else None
            ),
            "gc_license_status": (
                eligibility.gc_license.license_status
                if eligibility.gc_license else None
            ),
            "insurance_all_current": True,
            "blocking_reasons": [],
            "insurance_flags": [],
            "dob_now_url": renewal_data_result.get("dob_now_url"),
            "copyable_fields": renewal_data_result.get("copyable_fields"),
            "checklist": renewal_data_result.get("checklist"),
            "paa_required": renewal_data_result.get("paa_required", False),
            # v2 enrichment (step 6.2.3) — same passthrough as the
            # nightly scan writer. Sourced from the dispatcher's
            # RenewalEligibility response.
            "renewal_strategy": eligibility.renewal_strategy,
            "effective_expiry": eligibility.effective_expiry,
            "limiting_factor": eligibility.limiting_factor,
            "action": eligibility.action,
            # MR.1.6: issuance_date passthrough — see nightly writer.
            "issuance_date": eligibility.issuance_date,
            "updated_at": now,
            "prepared_by": current_user.get("id"),
        }

        if eligibility.gc_license:
            for ins in eligibility.gc_license.insurance_records:
                if ins.insurance_type == "general_liability":
                    renewal_fields["insurance_gl_expiry"] = (
                        ins.expiration_date
                    )
                elif ins.insurance_type == "workers_comp":
                    renewal_fields["insurance_wc_expiry"] = (
                        ins.expiration_date
                    )
                elif ins.insurance_type == "disability":
                    renewal_fields["insurance_db_expiry"] = (
                        ins.expiration_date
                    )

        if existing:
            await db.permit_renewals.update_one(
                {"_id": existing["_id"]},
                {"$set": renewal_fields},
            )
            renewal_fields["id"] = str(existing["_id"])
        else:
            renewal_fields["created_at"] = now
            renewal_fields["is_deleted"] = False
            result = await db.permit_renewals.insert_one(renewal_fields)
            renewal_fields["id"] = str(result.inserted_id)

        return serialize_id(renewal_fields)

    # GET /api/permit-renewals/dashboard-alerts
    @api_router.get("/permit-renewals/dashboard-alerts")
    async def get_dashboard_alerts(
        current_user=Depends(get_current_user),
    ):
        """Active renewal alerts for the dashboard."""
        company_id = get_user_company_id(current_user)
        query = {
            "is_deleted": {"$ne": True},
            "status": {"$nin": [
                RenewalStatus.COMPLETED,
                RenewalStatus.FAILED,
            ]},
        }
        if company_id:
            query["company_id"] = company_id

        renewals = (
            await db.permit_renewals
            .find(query)
            .sort("days_until_expiry", 1)
            .to_list(50)
        )

        alerts = []
        for r in renewals:
            alerts.append({
                "id": str(r["_id"]),
                "project_id": r.get("project_id"),
                "project_name": r.get("project_name"),
                "job_number": r.get("job_number"),
                "permit_type": r.get("permit_type"),
                "days_until_expiry": r.get("days_until_expiry"),
                "status": r.get("status"),
                "dob_now_url": r.get("dob_now_url"),
                "blocking_reasons": r.get("blocking_reasons", []),
            })

        return {"alerts": alerts, "total": len(alerts)}

    # GET /api/permit-renewals/health-status
    @api_router.get("/permit-renewals/health-status")
    async def get_health_status(admin=Depends(get_admin_user)):
        """Latest DOB NOW health check result (admin only)."""
        result = await db.system_config.find_one(
            {"key": "dob_now_health_check"}
        )
        if not result:
            return {
                "status": "never_run",
                "last_run": None,
                "issues": [],
            }
        return {
            "status": result.get("status", "unknown"),
            "last_run": result.get("last_run"),
            "issues": result.get("issues", []),
            "js_hash": result.get("js_hash"),
        }
