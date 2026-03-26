import os
import re
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

NYC_ID_USERNAME = os.environ.get("NYC_ID_USERNAME", "")
NYC_ID_PASSWORD = os.environ.get("NYC_ID_PASSWORD", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
OWNER_ALERT_EMAIL = os.environ.get("OWNER_ALERT_EMAIL", "")

DOB_BIS_LICENSE_URL = "https://a810-bisweb.nyc.gov/bisweb/LicenseQueryServlet"
DOB_NOW_BUILD_URL = "https://a810-dobnow.nyc.gov/publish/Index.html"

# RPA selectors the bot depends on — monitored by the health check
RPA_CRITICAL_SELECTORS = {
    "login_button": "text=Log In",
    "nycid_username": "#username",
    "nycid_password": "#password",
    "nycid_submit": "button[type='submit']",
    "job_search_input": "input[placeholder*='Job']",
    "renew_permit_btn": "text=Renew Permit",
    "save_btn": "text=Save",
    "actions_dropdown": "button:has-text('Actions')",
}


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS & MODELS
# ══════════════════════════════════════════════════════════════════════════════

class RenewalStatus(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE_INSURANCE = "ineligible_insurance"
    INELIGIBLE_LICENSE = "ineligible_license"
    DRAFT_READY = "draft_ready"
    AWAITING_GC = "awaiting_gc"
    COMPLETED = "completed"
    FAILED = "failed"


class InsuranceRecord(BaseModel):
    """Insurance information scraped from DOB Licensing Portal."""
    insurance_type: str
    carrier_name: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    is_current: bool = False


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
    gc_license: Optional[GCLicenseInfo] = None
    blocking_reasons: List[str] = []
    insurance_flags: List[str] = []


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

async def scrape_gc_license_info(company_name: str) -> Optional[GCLicenseInfo]:
    """
    Query NYC DOB BIS Licensing Portal by company name.
    Extracts GC license number, status, and insurance records.
    """
    import httpx

    logger.info(f"BIS scrape: looking up GC license for '{company_name}'")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(DOB_BIS_LICENSE_URL, params={
                "requestid": "1",
                "licnm": company_name.upper().strip(),
                "licno": "",
                "lictp": "G",
                "go2": "Submit",
            })

            if resp.status_code != 200:
                logger.warning(f"BIS license query returned {resp.status_code}")
                return None

            html = resp.text
            info = _parse_bis_license_html(html)

            if info and info.license_number:
                info.insurance_records = await _fetch_insurance_details(
                    client, info.license_number
                )

            return info

    except Exception as e:
        logger.error(f"BIS scrape error for '{company_name}': {e}")
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
    """Fetch insurance records for a given GC license from BIS."""
    records = []

    try:
        resp = await client.get(DOB_BIS_LICENSE_URL, params={
            "requestid": "2",
            "licno": license_number,
        })
        if resp.status_code != 200:
            return records

        html = resp.text

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
) -> RenewalEligibility:
    """
    Full eligibility check:
    1. Verify permit exists and is expiring within 30 days
    2. Scrape BIS for GC license + insurance
    3. Validate all insurance covers 1 year from renewal date
    """
    permit = await db.dob_logs.find_one({"_id": _to_oid(permit_dob_log_id)})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit record not found")
    if permit.get("record_type") != "permit":
        raise HTTPException(status_code=400, detail="Record is not a permit")

    eligibility = RenewalEligibility(
        permit_id=permit_dob_log_id,
        project_id=project_id,
        job_number=permit.get("job_number"),
        permit_type=permit.get("permit_type"),
        expiration_date=permit.get("expiration_date"),
    )

    # ── Check expiration window ──
    exp_str = permit.get("expiration_date")
    if exp_str:
        try:
            from dateutil import parser as dateparser
            exp_date = dateparser.parse(str(exp_str))
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=timezone.utc)
            days_left = (exp_date - datetime.now(timezone.utc)).days
            eligibility.days_until_expiry = days_left

            if days_left > 30:
                eligibility.blocking_reasons.append(
                    f"Permit expires in {days_left} days. Renewal available within 30 days of expiry."
                )
            elif days_left < 0:
                eligibility.blocking_reasons.append(
                    "Permit has already expired. Manual renewal required on DOB NOW."
                )
        except Exception:
            eligibility.blocking_reasons.append("Could not parse permit expiration date.")
    else:
        eligibility.blocking_reasons.append("No expiration date on permit record.")

    # ── Scrape GC license + insurance ──
    gc_info = await scrape_gc_license_info(company_name)
    eligibility.gc_license = gc_info

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

        renewal_target = datetime.now(timezone.utc) + timedelta(days=365)
        required_types = {"general_liability", "workers_comp", "disability"}
        found_types = set()

        for ins in gc_info.insurance_records:
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
                f"{label} insurance not found on DOB Licensing Portal."
            )

        if eligibility.insurance_flags:
            eligibility.blocking_reasons.append("Insurance Update Required")

    eligibility.eligible = len(eligibility.blocking_reasons) == 0
    return eligibility


# ══════════════════════════════════════════════════════════════════════════════
# DOB NOW RPA — PREPARER DRAFT
# ══════════════════════════════════════════════════════════════════════════════

async def prepare_renewal_on_dob_now(
    job_number: str,
    license_number: str,
    project_address: str,
) -> Dict[str, Any]:
    """
    Playwright headless browser:
      1. Log into DOB NOW: Build as Preparer (NYC.ID)
      2. Search for the Job Number
      3. Click "Renew Permit"
      4. Save as Draft
      5. Return deep-link URLs for the GC

    Returns dict with success, dob_filing_url, signature_url, error.
    """
    result = {
        "success": False,
        "dob_filing_url": None,
        "signature_url": None,
        "error": None,
    }

    if not NYC_ID_USERNAME or not NYC_ID_PASSWORD:
        result["error"] = (
            "NYC.ID credentials not configured. "
            "Set NYC_ID_USERNAME and NYC_ID_PASSWORD env vars."
        )
        logger.error(result["error"])
        return result

    if not job_number:
        result["error"] = "Job number is required for renewal preparation."
        return result

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # Step 1: Navigate to DOB NOW Build
            logger.info(f"RPA: Navigating to DOB NOW for job {job_number}")
            await page.goto(
                DOB_NOW_BUILD_URL,
                wait_until="networkidle",
                timeout=30000,
            )

            # Step 2: Authenticate via NYC.ID
            login_btn = page.locator(
                RPA_CRITICAL_SELECTORS["login_button"]
            ).first
            if await login_btn.is_visible(timeout=5000):
                await login_btn.click()
                await page.wait_for_url(
                    "**/account.nyc.gov/**", timeout=15000
                )

                await page.fill(
                    RPA_CRITICAL_SELECTORS["nycid_username"],
                    NYC_ID_USERNAME,
                )
                await page.fill(
                    RPA_CRITICAL_SELECTORS["nycid_password"],
                    NYC_ID_PASSWORD,
                )
                await page.click(RPA_CRITICAL_SELECTORS["nycid_submit"])
                await page.wait_for_url(
                    "**/a810-dobnow.nyc.gov/**", timeout=30000
                )
                logger.info("RPA: Authenticated with NYC.ID")

            # Step 3: Search for Job Number
            await page.wait_for_selector(
                RPA_CRITICAL_SELECTORS["job_search_input"],
                timeout=10000,
            )
            await page.fill(
                RPA_CRITICAL_SELECTORS["job_search_input"],
                job_number,
            )
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)

            # Step 4: Click on the job row
            job_row = page.locator(f"text={job_number}").first
            if not await job_row.is_visible(timeout=5000):
                result["error"] = f"Job {job_number} not found in DOB NOW"
                await browser.close()
                return result

            await job_row.click()
            await page.wait_for_timeout(2000)

            # Step 5: Click "Renew Permit"
            renew_btn = page.locator(
                RPA_CRITICAL_SELECTORS["renew_permit_btn"]
            ).first

            if await renew_btn.is_visible(timeout=3000):
                await renew_btn.click()
                await page.wait_for_timeout(3000)
                logger.info(
                    f"RPA: Clicked 'Renew Permit' for job {job_number}"
                )
            else:
                # Fallback: Actions dropdown → Renew
                actions_btn = page.locator(
                    RPA_CRITICAL_SELECTORS["actions_dropdown"]
                ).first
                if await actions_btn.is_visible(timeout=3000):
                    await actions_btn.click()
                    await page.wait_for_timeout(1000)
                    renew_option = page.locator("text=Renew").first
                    if await renew_option.is_visible(timeout=2000):
                        await renew_option.click()
                        await page.wait_for_timeout(3000)
                    else:
                        result["error"] = (
                            "'Renew' option not available in Actions dropdown. "
                            "The permit may not be eligible for renewal on DOB NOW."
                        )
                        await browser.close()
                        return result
                else:
                    result["error"] = (
                        "Cannot find 'Renew Permit' button or Actions dropdown. "
                        "DOB NOW UI may have changed."
                    )
                    await browser.close()
                    return result

            # Step 6: Save as Draft
            save_btn = page.locator(
                RPA_CRITICAL_SELECTORS["save_btn"]
            ).first
            if await save_btn.is_visible(timeout=5000):
                await save_btn.click()
                await page.wait_for_timeout(2000)
                logger.info(
                    f"RPA: Saved renewal draft for job {job_number}"
                )

            # Step 7: Capture URLs
            result["dob_filing_url"] = page.url

            job_clean = job_number.replace("-", "")
            result["signature_url"] = (
                f"https://a810-dobnow.nyc.gov/publish/#!/"
                f"job/{job_clean}/action/renewal/"
                f"tab/statementsAndSignatures"
            )

            result["success"] = True
            logger.info(
                f"RPA: Renewal draft ready for job {job_number}. "
                f"GC deep-link: {result['signature_url']}"
            )
            await browser.close()

    except Exception as e:
        result["error"] = f"RPA error: {str(e)}"
        logger.error(f"RPA error for job {job_number}: {e}")

    return result


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
        async with httpx.AsyncClient(timeout=15.0) as client:
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
# DOB NOW HEALTH CHECK — Monitor for UI changes
# ══════════════════════════════════════════════════════════════════════════════

async def run_dob_now_health_check(db):
    """
    Daily health check that validates DOB NOW's UI hasn't changed.
    Three checks:
      1. DOM Selectors — verifies login page elements exist
      2. JS Bundle Hash — detects redeployments
      3. NYC.ID login page — verifies form fields
    Sends Resend email alert if anything fails.
    """
    logger.info("🔍 DOB NOW health check starting...")

    issues = []
    js_hash_current = None

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Check 1: Load DOB NOW and verify login button
            try:
                await page.goto(
                    DOB_NOW_BUILD_URL,
                    wait_until="networkidle",
                    timeout=30000,
                )

                login_visible = await page.locator(
                    RPA_CRITICAL_SELECTORS["login_button"]
                ).first.is_visible(timeout=5000)

                if not login_visible:
                    issues.append(
                        "LOGIN BUTTON MISSING: The 'Log In' button was not "
                        "found on the DOB NOW landing page. "
                        "Selector may need updating."
                    )
            except Exception as e:
                issues.append(
                    f"PAGE LOAD FAILED: DOB NOW Build failed to load. "
                    f"Error: {str(e)}"
                )

            # Check 2: Hash JS bundle URLs for change detection
            try:
                scripts = await page.evaluate("""
                    () => Array.from(
                        document.querySelectorAll('script[src]')
                    )
                    .map(s => s.src)
                    .filter(src =>
                        src.includes('dobnow') || src.includes('bundle')
                    )
                    .sort()
                """)

                if scripts:
                    js_hash_current = hashlib.sha256(
                        "|".join(scripts).encode()
                    ).hexdigest()[:16]

                    stored = await db.system_config.find_one(
                        {"key": "dob_now_js_hash"}
                    )
                    if stored and stored.get("value") != js_hash_current:
                        issues.append(
                            f"JS BUNDLE CHANGED: DOB NOW deployed new "
                            f"JavaScript. Old hash: {stored.get('value')}, "
                            f"New hash: {js_hash_current}. "
                            f"RPA selectors may need updating."
                        )

                    await db.system_config.update_one(
                        {"key": "dob_now_js_hash"},
                        {"$set": {
                            "key": "dob_now_js_hash",
                            "value": js_hash_current,
                            "updated_at": datetime.now(timezone.utc),
                        }},
                        upsert=True,
                    )
            except Exception as e:
                issues.append(f"JS HASH CHECK FAILED: {str(e)}")

            # Check 3: Verify NYC.ID login page loads
            try:
                login_btn = page.locator(
                    RPA_CRITICAL_SELECTORS["login_button"]
                ).first
                if await login_btn.is_visible(timeout=3000):
                    await login_btn.click()
                    await page.wait_for_url(
                        "**/account.nyc.gov/**", timeout=10000
                    )

                    username_ok = await page.locator(
                        RPA_CRITICAL_SELECTORS["nycid_username"]
                    ).first.is_visible(timeout=5000)
                    if not username_ok:
                        issues.append(
                            "NYC.ID LOGIN CHANGED: Username field "
                            "(#username) not found."
                        )

                    password_ok = await page.locator(
                        RPA_CRITICAL_SELECTORS["nycid_password"]
                    ).first.is_visible(timeout=3000)
                    if not password_ok:
                        issues.append(
                            "NYC.ID LOGIN CHANGED: Password field "
                            "(#password) not found."
                        )
            except Exception as e:
                issues.append(f"NYC.ID PAGE CHECK FAILED: {str(e)}")

            await browser.close()

    except Exception as e:
        issues.append(
            f"HEALTH CHECK CRASHED: Playwright failed to start. "
            f"Error: {str(e)}"
        )

    # Send alert if issues detected
    if issues:
        logger.warning(
            f"DOB NOW health check: {len(issues)} issue(s) detected"
        )
        await _send_health_check_alert(issues)
    else:
        logger.info(
            "✅ DOB NOW health check passed — all selectors valid"
        )

    # Store result
    await db.system_config.update_one(
        {"key": "dob_now_health_check"},
        {"$set": {
            "key": "dob_now_health_check",
            "last_run": datetime.now(timezone.utc),
            "status": "failed" if issues else "passed",
            "issues": issues,
            "js_hash": js_hash_current,
        }},
        upsert=True,
    )

    return {"status": "failed" if issues else "passed", "issues": issues}


async def _send_health_check_alert(issues: List[str]):
    """Send DOB NOW UI change alert email via Resend."""
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
            last_sent = last_alert["sent_at"]
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
                <h1 style="margin:0;font-size:18px;">⚠️ DOB NOW UI Change Detected</h1>
                <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">
                    Permit Renewal RPA may need updating
                </p>
            </div>
            <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
                <p style="margin:0 0 16px;font-size:14px;color:#374151;">
                    The daily DOB NOW health check detected
                    {len(issues)} issue(s) that may break the permit
                    renewal automation:
                </p>
                {issues_html}
                <div style="background:#f9fafb;border-radius:6px;padding:16px;margin-top:16px;">
                    <p style="margin:0 0 4px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;">
                        Required Action
                    </p>
                    <p style="margin:0;font-size:14px;color:#1f2937;">
                        Review the RPA selectors in
                        <code>permit_renewal.py</code>
                        (RPA_CRITICAL_SELECTORS dict) and update any
                        that no longer match DOB NOW's interface.
                    </p>
                </div>
                <p style="margin:16px 0 0;font-size:12px;color:#9ca3af;">
                    Detected at {datetime.now(timezone.utc).strftime('%B %d, %Y %I:%M %p')} UTC
                </p>
            </div>
            <p style="text-align:center;font-size:10px;color:#cbd5e1;margin-top:16px;letter-spacing:2px;">
                BLUEVIEW COMPLIANCE
            </p>
        </div>
        """

        resend.Emails.send({
            "from": "Blueview Alerts <alerts@blue-view.app>",
            "to": [recipient],
            "subject": (
                f"⚠️ DOB NOW UI Change — Permit Renewal RPA Alert "
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
                    db, permit_id, project_id, company_name
                )

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
                    "status": (
                        RenewalStatus.ELIGIBLE
                        if eligibility.eligible
                        else RenewalStatus.INELIGIBLE_INSURANCE
                    ),
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
            last_run = last_check["last_run"]
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
            db, body.permit_dob_log_id, body.project_id, company_name
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
            db, body.permit_dob_log_id, body.project_id, company_name
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

        # Run RPA
        rpa_result = await prepare_renewal_on_dob_now(
            job_number=eligibility.job_number or "",
            license_number=(
                eligibility.gc_license.license_number
                if eligibility.gc_license else ""
            ),
            project_address=project.get("address", ""),
        )

        if not rpa_result["success"]:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"DOB NOW automation failed: "
                    f"{rpa_result.get('error', 'Unknown error')}"
                ),
            )

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
            "dob_filing_url": rpa_result.get("dob_filing_url"),
            "dob_now_url": rpa_result.get("signature_url"),
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
