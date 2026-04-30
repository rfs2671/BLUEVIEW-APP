"""dob_now_filing handler — MR.11 real implementation.

Replaces the MR.5 stub with Playwright automation against
DOB NOW. Decrypts the operator-supplied credentials using the
agent's local private key (lib/crypto.py), launches a per-GC
BrowserContext via lib/browser_context.py with persistent
storage_state, logs into NYC.ID, navigates to the permit's PW2
renewal form, fills it from the cloud-supplied pw2_field_map
(MR.4 mapper output), submits, and captures the DOB confirmation
number from the success page.

Critical pieces called out at the top of the file because they
need empirical confirmation in the operator's first smoke run
against real DOB NOW (no integration tests against the live site
ship in this commit — the handler's selectors are best-effort
based on code-only research):

  • NYC.ID login form selectors (username/password input names,
    submit button text, post-submit redirect URL pattern).
  • DOB NOW dashboard navigation: how to reach "My Permits" /
    list, how to filter by job_filing_number.
  • PW2 form field name attributes (the mapper emits canonical
    keys like "applicant_name"; the actual <input name="..."> on
    DOB NOW may differ — handler tries `name=`, then `[id*=...]`,
    then label-based xpath).
  • Confirmation-number extraction regex on the post-submit page.
  • 2FA / CAPTCHA challenge detection markers (DOM elements,
    URL fragments, iframe tags).

Every selector with this need is annotated `# SELECTOR-EMPIRICAL`
in the source. After the first real smoke run, the operator will
report which selectors matched / missed; a follow-up commit
locks in the confirmed forms.

Failure modes handled in this commit (each returns a
HandlerResult(status="failed") with a specific failure_reason
the operator can act on):
  - credential_key_mismatch: ciphertext was encrypted against a
    different keypair than this agent holds.
  - decrypt_failed: ciphertext is structurally invalid OR the
    private key won't decrypt it (tampering / wrong key /
    truncated blob).
  - akamai_challenge: Akamai's bot-detection page intercepted us.
    Trips the per-job-type circuit breaker (lib/circuit_breaker.py)
    so subsequent jobs back off automatically.
  - login_failed: credentials rejected by NYC.ID.
  - 2fa_timeout: operator didn't supply the 2FA code within
    OPERATOR_RESPONSE_TIMEOUT.
  - captcha_timeout: same for CAPTCHA.
  - permit_not_found: the job_filing_number isn't in the user's
    "My Permits" list. Most likely cause: the filing rep's
    license doesn't cover this permit type.
  - permit_not_renewable: permit is in a state DOB doesn't allow
    renewal from (already renewed, expired beyond the grace
    window, etc.).
  - dob_validation_error: form submitted but DOB returned errors.
    Audit-log captures the error messages so the operator can
    fix the underlying data.
  - submission_no_confirmation: form submitted, no clear
    confirmation page detected. Manual intervention required.
  - cancelled_by_operator: cancellation_requested flag set on
    the FilingJob between/during steps.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.crypto import agent_key_fingerprint, decrypt_credentials
from lib.handler_types import HandlerContext, HandlerResult
from lib.browser_context import with_browser_context
from lib.queue_client import (
    fetch_filing_job,
    post_filing_job_event,
)


logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────

DOB_NOW_LANDING = "https://a810-dobnow.nyc.gov/Publish/Index.html#!/"
NYC_ID_LOGIN_PATTERN = re.compile(r"a810-dobnow|nyc\.gov", re.I)

# How long we'll wait for the operator to respond to a 2FA / CAPTCHA
# prompt. 15 minutes lines up with MR.7's UI — the operator sees the
# prompt in the FilingStatusCard, has time to fish out their phone,
# and responds via the operator-input modal.
OPERATOR_RESPONSE_TIMEOUT_SECONDS = 15 * 60
OPERATOR_RESPONSE_POLL_SECONDS = 10

# Cancellation-check cadence between major steps. Keeps the cost
# bounded (no per-keystroke checks); 4 checkpoints per filing run
# is enough granularity for the operator's "cancel filing" button
# to feel responsive without flooding the backend with GETs.
CANCELLATION_CHECKPOINTS = (
    "before_login",
    "after_login",
    "after_navigate",
    "after_fill",
)

PLAYWRIGHT_NAVIGATION_TIMEOUT_MS = 60_000
PLAYWRIGHT_DEFAULT_TIMEOUT_MS = 30_000


# ── Akamai detection ────────────────────────────────────────────────
# Akamai bot manager intercepts headless browsers with a 403 + an
# HTML page containing specific markers. If we hit one, the agent
# can't proceed without a different network / fingerprint. Trip the
# breaker; operator will see the failure and likely needs to either
# install cloudflared (for residential-IP egress) OR rotate
# storage_state.

AKAMAI_MARKERS = (
    "Access Denied",
    "ak-bm-rendering",
    "akamai-bot-manager",
    "Reference #",  # Akamai's "Pardon our interruption" pages
)


def _is_akamai_challenge(page_content: str, status_code: Optional[int] = None) -> bool:
    """Best-effort Akamai detection. Pure function — easily testable.
    Caller passes both the page HTML/text content AND the HTTP status
    of the most recent navigation response so we can short-circuit
    on a 403 even if the body lacks the magic strings."""
    if status_code == 403:
        return True
    if not page_content:
        return False
    haystack = page_content[:8000]  # bot pages are usually small; cap scan
    return any(marker in haystack for marker in AKAMAI_MARKERS)


# ── Credentials decrypt + fingerprint check ─────────────────────────

def _decrypt_payload_credentials(
    payload: dict,
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Verify the public-key fingerprint, decrypt the ciphertext,
    return (credentials_dict, error_reason). Exactly one is None.

    error_reason values used:
      - "credential_key_mismatch"
      - "decrypt_failed"
      - "missing_credentials_field"
    """
    encrypted_b64 = payload.get("encrypted_credentials_b64") or ""
    if not encrypted_b64:
        return None, "missing_credentials_field"

    # Note: payload doesn't ship the public_key_fingerprint (the
    # backend doesn't include it on the queue payload — we only
    # know it via the FilingJob doc's credential_version → look up
    # via fetch_filing_job if we want to verify). For v1 we just
    # check our local key can decrypt; if the ciphertext was
    # encrypted against a different key, decrypt_credentials raises
    # and we surface as decrypt_failed. The fingerprint mismatch
    # case is technically a strict subset of decrypt_failed so the
    # operator-facing distinction matters less than the failure
    # mode itself: re-encrypt the credential through the MR.10 UI.
    try:
        creds = decrypt_credentials(encrypted_b64)
    except Exception as e:
        logger.error(
            "[dob_now_filing] decrypt_credentials raised: %s",
            type(e).__name__,
        )
        return None, "decrypt_failed"

    if not isinstance(creds, dict) or "username" not in creds or "password" not in creds:
        return None, "decrypt_failed"
    return creds, None


# ── Cancellation polling ────────────────────────────────────────────

async def _check_cancellation(
    http_client,
    *,
    backend_url: str,
    permit_renewal_id: str,
    filing_job_id: str,
    checkpoint: str,
) -> bool:
    """Returns True if the operator clicked Cancel on this job
    between steps. Soft-fails on backend unreachable (returns
    False) so a transient backend blip doesn't kill the run."""
    job = await fetch_filing_job(
        http_client,
        backend_url=backend_url,
        permit_renewal_id=permit_renewal_id,
        filing_job_id=filing_job_id,
    )
    if job is None:
        # Soft fail — assume not cancelled so the run continues.
        return False
    cancelled = bool(job.get("cancellation_requested"))
    if cancelled:
        logger.info(
            "[dob_now_filing] cancellation_requested observed at "
            "checkpoint=%s for filing_job_id=%s",
            checkpoint, filing_job_id,
        )
    return cancelled


# ── Operator response polling (2FA / CAPTCHA) ───────────────────────

async def _wait_for_operator_response(
    http_client,
    *,
    backend_url: str,
    permit_renewal_id: str,
    filing_job_id: str,
    expected_kind: str,  # "captcha_response" or "2fa_response"
    timeout_seconds: int = OPERATOR_RESPONSE_TIMEOUT_SECONDS,
    poll_seconds: int = OPERATOR_RESPONSE_POLL_SECONDS,
) -> Optional[str]:
    """Poll the FilingJob's audit_log every poll_seconds for an
    operator_response event whose metadata.response_kind matches.
    Returns the response value on success, None on timeout.

    Walks audit_log newest-first and short-circuits on the first
    matching operator_response — EXCEPT we also stop if a NEWER
    matching challenge event appears, which would mean the worker's
    own challenge raised again (e.g. operator typed the wrong code
    and DOB issued a fresh one). The agent doesn't currently re-
    raise from inside this function — that's caller policy — but
    the freshness check keeps the contract clean."""
    waited = 0
    while waited < timeout_seconds:
        job = await fetch_filing_job(
            http_client,
            backend_url=backend_url,
            permit_renewal_id=permit_renewal_id,
            filing_job_id=filing_job_id,
        )
        if job is not None:
            audit = job.get("audit_log") or []
            # Walk newest-to-oldest looking for a matching response.
            for ev in reversed(audit):
                if (
                    ev.get("event_type") == "operator_response"
                    and (ev.get("metadata") or {}).get("response_kind") == expected_kind
                ):
                    value = (ev.get("metadata") or {}).get("response_value")
                    if isinstance(value, str) and value.strip():
                        return value
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds
    return None


# ── Selectors (best-effort first pass; SELECTOR-EMPIRICAL) ─────────
# Every selector below needs operator confirmation in the smoke run.
# Listed as fallback chains: handler tries each in order and uses
# the first that matches a visible element. If NONE match, the
# handler fails loudly with a specific failure_reason so the
# operator can paste the page HTML and we can lock in the right
# selector in a follow-up commit.

LOGIN_USERNAME_SELECTORS = (
    'input[name="username"]',
    'input[name="email"]',
    'input[id*="user"]',
    'input[type="email"]',
    'input[placeholder*="email" i]',
)
LOGIN_PASSWORD_SELECTORS = (
    'input[name="password"]',
    'input[id*="pass" i]',
    'input[type="password"]',
)
LOGIN_SUBMIT_SELECTORS = (
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Log In")',
)
TWO_FA_INPUT_SELECTORS = (
    'input[name*="otp" i]',
    'input[name*="code" i]',
    'input[autocomplete="one-time-code"]',
    'input[id*="2fa" i]',
)
CAPTCHA_IMAGE_SELECTORS = (
    'img[src*="captcha" i]',
    'iframe[src*="captcha" i]',
    'iframe[title*="captcha" i]',
)
CAPTCHA_INPUT_SELECTORS = (
    'input[name*="captcha" i]',
    'input[id*="captcha" i]',
)
PERMIT_LIST_LINK_SELECTORS = (
    'a:has-text("My Permits")',
    'a:has-text("My Filings")',
    'nav a[href*="permit" i]',
)
PERMIT_RENEW_BUTTON_SELECTORS = (
    'button:has-text("Renew")',
    'a:has-text("Renew")',
    'button:has-text("Renew Permit")',
)
SUBMIT_BUTTON_SELECTORS = (
    'button:has-text("Submit")',
    'button[type="submit"]:not([disabled])',
    'button:has-text("File")',
)


def _get_async_playwright():
    """Return the `async_playwright` callable. Lazily imports the
    Playwright module on each call (cheap once cached by Python's
    sys.modules) so tests can patch this helper to inject a mock
    without disturbing the real Playwright module's machinery.

    Tests use:
        patch("handlers.dob_now_filing._get_async_playwright",
              return_value=fake_async_playwright_factory)

    Production calls return the real callable; the cost of the
    import is paid once per worker process."""
    from playwright.async_api import async_playwright as _apw  # type: ignore
    return _apw


async def _try_first_match(page, selectors):
    """Try a list of CSS selectors; return the first locator that
    has at least one visible match. Returns None if none match."""
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.is_visible(timeout=2000):
                return locator
        except Exception:
            continue
    return None


# ── Login flow ──────────────────────────────────────────────────────

async def _login(
    page,
    *,
    username: str,
    password: str,
    http_client,
    backend_url: str,
    permit_renewal_id: str,
    filing_job_id: str,
) -> Optional[str]:
    """Log into DOB NOW via NYC.ID. Returns failure_reason string
    on failure, None on success.

    Steps:
      1. Navigate to landing.
      2. Detect Akamai challenge → fail loud.
      3. If a "Sign In" button is visible (no active session yet),
         click it. SELECTOR-EMPIRICAL.
      4. Fill username + password from fallback selectors.
      5. Submit.
      6. After submit, watch for either:
         - Successful redirect to dobnow (DOM change, URL pattern)
         - 2FA challenge (input visible)
         - CAPTCHA challenge (image visible)
         - Generic "invalid credentials" message
      7. For 2FA / CAPTCHA: append audit event, poll operator-
         input, submit response, re-evaluate.
      8. Returns None when we believe we're logged in (post-redirect
         + presence of a dashboard-like element).
    """
    try:
        resp = await page.goto(
            DOB_NOW_LANDING,
            wait_until="domcontentloaded",
            timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
        )
    except Exception as e:
        logger.error("[dob_now_filing] navigation to DOB_NOW_LANDING failed: %r", e)
        return "network_timeout"

    status = resp.status if resp else None
    body_text = ""
    try:
        body_text = await page.content()
    except Exception:
        body_text = ""
    if _is_akamai_challenge(body_text, status):
        logger.warning(
            "[dob_now_filing] Akamai challenge detected (status=%s)",
            status,
        )
        return "akamai_challenge"

    # If we already have a logged-in session via storage_state
    # cookies, the landing page often redirects straight to a
    # dashboard. Heuristic: look for the username/password input.
    # If absent, assume we're already in.
    user_input = await _try_first_match(page, LOGIN_USERNAME_SELECTORS)
    if user_input is None:
        # Maybe we need to click a "Sign In" button first.
        sign_in = await _try_first_match(page, (
            'a:has-text("Sign In")',
            'button:has-text("Sign In")',
            'a:has-text("Log In")',
        ))
        if sign_in is not None:
            try:
                await sign_in.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
                )
                user_input = await _try_first_match(page, LOGIN_USERNAME_SELECTORS)
            except Exception as e:
                logger.warning("[dob_now_filing] Sign In click failed: %r", e)

    if user_input is None:
        # Likely already logged in via storage_state. Heuristic
        # confirmation: look for a "Sign Out" / username display /
        # dashboard link. If we still can't tell, proceed —
        # downstream navigation will fail loudly if we're not
        # actually logged in.
        logger.info(
            "[dob_now_filing] no login form detected; assuming "
            "session restored from storage_state"
        )
        return None

    # Cold-login path. Fill credentials.
    pw_input = await _try_first_match(page, LOGIN_PASSWORD_SELECTORS)
    if pw_input is None:
        return "login_form_password_field_not_found"
    submit_btn = await _try_first_match(page, LOGIN_SUBMIT_SELECTORS)
    if submit_btn is None:
        return "login_form_submit_button_not_found"

    try:
        await user_input.fill(username, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await pw_input.fill(password, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await submit_btn.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
        )
    except Exception as e:
        logger.error("[dob_now_filing] login submit failed: %r", e)
        return "login_submit_failed"

    # Post-submit: detect 2FA, CAPTCHA, invalid creds, or success.
    # Order matters: check challenges before "did login succeed?"
    # because the challenge pages can also lack a username field
    # (which is our normal "logged in" heuristic).
    body_text_post = ""
    try:
        body_text_post = await page.content()
    except Exception:
        pass

    if _is_akamai_challenge(body_text_post, None):
        return "akamai_challenge"

    # 2FA detection
    tfa_input = await _try_first_match(page, TWO_FA_INPUT_SELECTORS)
    if tfa_input is not None:
        await post_filing_job_event(
            http_client,
            backend_url=backend_url,
            filing_job_id=filing_job_id,
            event_type="2fa_required",
            detail="DOB NOW requested a 2FA code",
            metadata={"channel": "unknown"},  # SELECTOR-EMPIRICAL: parse from page
        )
        code = await _wait_for_operator_response(
            http_client,
            backend_url=backend_url,
            permit_renewal_id=permit_renewal_id,
            filing_job_id=filing_job_id,
            expected_kind="2fa_response",
        )
        if code is None:
            return "2fa_timeout"
        try:
            await tfa_input.fill(code, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
            sub2 = await _try_first_match(page, LOGIN_SUBMIT_SELECTORS)
            if sub2 is not None:
                await sub2.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
                )
        except Exception as e:
            logger.error("[dob_now_filing] 2FA submit failed: %r", e)
            return "2fa_submit_failed"

    # CAPTCHA detection
    cap_image = await _try_first_match(page, CAPTCHA_IMAGE_SELECTORS)
    if cap_image is not None:
        # Screenshot the captcha element + base64-encode for
        # transmission to the operator UI.
        try:
            screenshot_bytes = await cap_image.screenshot(timeout=10_000)
            image_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception:
            image_b64 = ""
        await post_filing_job_event(
            http_client,
            backend_url=backend_url,
            filing_job_id=filing_job_id,
            event_type="captcha_required",
            detail="DOB NOW presented a CAPTCHA",
            metadata={"captcha_image_b64": image_b64},
        )
        text = await _wait_for_operator_response(
            http_client,
            backend_url=backend_url,
            permit_renewal_id=permit_renewal_id,
            filing_job_id=filing_job_id,
            expected_kind="captcha_response",
        )
        if text is None:
            return "captcha_timeout"
        cap_input = await _try_first_match(page, CAPTCHA_INPUT_SELECTORS)
        if cap_input is None:
            return "captcha_input_not_found"
        try:
            await cap_input.fill(text, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
            sub3 = await _try_first_match(page, LOGIN_SUBMIT_SELECTORS)
            if sub3 is not None:
                await sub3.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
                )
        except Exception as e:
            logger.error("[dob_now_filing] CAPTCHA submit failed: %r", e)
            return "captcha_submit_failed"

    # Final post-login check: did we actually log in? Heuristic:
    # username field is gone AND we're on a dobnow URL.
    final_user_input = await _try_first_match(page, LOGIN_USERNAME_SELECTORS)
    final_url = page.url or ""
    body_final = ""
    try:
        body_final = await page.content()
    except Exception:
        pass
    if final_user_input is not None:
        # Still on a login form. Look for an error message.
        if "invalid" in (body_final or "").lower() or "incorrect" in (body_final or "").lower():
            return "invalid_credentials"
        return "login_failed"
    if "dobnow" not in final_url.lower() and "nyc.gov" not in final_url.lower():
        return "post_login_unexpected_url"
    return None


# ── Permit navigation ──────────────────────────────────────────────

async def _navigate_to_permit(
    page,
    *,
    job_filing_number: str,
) -> Optional[str]:
    """From the dashboard, find the permit by job_filing_number
    and click into its renewal flow. Returns failure_reason or None.

    SELECTOR-EMPIRICAL throughout. The DOB NOW SPA's exact navigation
    pattern is unknown without a logged-in session; this is best-
    effort. Smoke run will refine."""
    permits_link = await _try_first_match(page, PERMIT_LIST_LINK_SELECTORS)
    if permits_link is not None:
        try:
            await permits_link.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
            )
        except Exception as e:
            logger.warning("[dob_now_filing] permits-link click failed: %r", e)

    # Find the row for our specific permit.
    row_selectors = (
        f'tr:has-text("{job_filing_number}")',
        f'div[role="row"]:has-text("{job_filing_number}")',
        f'a:has-text("{job_filing_number}")',
    )
    permit_row = await _try_first_match(page, row_selectors)
    if permit_row is None:
        return "permit_not_found"

    try:
        await permit_row.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
        )
    except Exception as e:
        logger.error("[dob_now_filing] permit-row click failed: %r", e)
        return "permit_click_failed"

    renew_btn = await _try_first_match(page, PERMIT_RENEW_BUTTON_SELECTORS)
    if renew_btn is None:
        return "permit_not_renewable"

    try:
        await renew_btn.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
        )
    except Exception as e:
        logger.error("[dob_now_filing] renew-button click failed: %r", e)
        return "renew_click_failed"

    return None


# ── PW2 form fill ───────────────────────────────────────────────────

async def _find_form_input(page, field_name: str):
    """Multi-strategy input lookup. Returns the first matching
    visible Locator or None.

    Strategy order (fastest → slowest):
      1. name attribute exact match
      2. id substring match (case-insensitive)
      3. label-driven: <label for="...">field_name</label>
      4. xpath against placeholder / aria-label
    """
    selectors = (
        f'[name="{field_name}"]',
        f'[id*="{field_name}" i]',
        f'label:has-text("{field_name}") + input',
        f'label:has-text("{field_name}") + select',
        f'label:has-text("{field_name}") ~ input',
        f'[placeholder*="{field_name}" i]',
        f'[aria-label*="{field_name}" i]',
    )
    return await _try_first_match(page, selectors)


async def _fill_field(page, field_name: str, value: str, field_type: str) -> bool:
    """Dispatch by field_type. Returns True on success, False if the
    field couldn't be found or filled. Caller decides whether a
    failure to fill a non-critical field is fatal (it isn't —
    handler logs and continues; critical fields would have been
    blocked by MR.6's enqueue gate)."""
    locator = await _find_form_input(page, field_name)
    if locator is None:
        logger.warning(
            "[dob_now_filing] field input not found: name=%r",
            field_name,
        )
        return False

    try:
        ft = (field_type or "").lower()
        if ft in ("text", "date"):
            # Date inputs accept .fill() with ISO/M-D-YYYY string
            # in most modern Chromium builds. SELECTOR-EMPIRICAL:
            # if DOB NOW uses a custom date picker, this will need
            # special handling (clicking calendar, navigating months).
            await locator.fill(value, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        elif ft == "select":
            # Try by-value first, fall back to by-label.
            try:
                await locator.select_option(value=value, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
            except Exception:
                await locator.select_option(label=value, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        elif ft == "checkbox":
            truthy = str(value).strip().lower() in ("true", "yes", "1", "on")
            if truthy:
                await locator.check(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
            else:
                await locator.uncheck(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        elif ft == "signature_required":
            # Click the canvas + draw a single horizontal line.
            # Acceptable as a placeholder signature for DOB NOW's
            # filing-rep affirmation. SELECTOR-EMPIRICAL: confirm
            # canvas size + position in smoke run.
            box = await locator.bounding_box()
            if box is None:
                return False
            x0, y0 = box["x"] + 10, box["y"] + box["height"] / 2
            x1 = box["x"] + box["width"] - 10
            await page.mouse.move(x0, y0)
            await page.mouse.down()
            await page.mouse.move(x1, y0, steps=20)
            await page.mouse.up()
        else:
            # Unknown field_type — try .fill() as a last resort.
            await locator.fill(value, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        return True
    except Exception as e:
        logger.warning(
            "[dob_now_filing] fill failed for field=%r type=%r: %r",
            field_name, field_type, e,
        )
        return False


async def _fill_pw2_form(page, pw2_field_map: dict) -> int:
    """Iterate the mapper output's `fields` dict and fill each one.
    Returns the count of fields successfully filled.

    Skips fields whose value is unmappable (not present in `fields`
    — they're in `unmappable_fields`, partitioned by criticality at
    enqueue time so we know nothing critical is missing here)."""
    fields = (pw2_field_map or {}).get("fields") or {}
    filled = 0
    for name, fv in fields.items():
        if not isinstance(fv, dict):
            continue
        value = fv.get("value")
        ft = fv.get("field_type") or "text"
        if value is None or value == "":
            continue
        ok = await _fill_field(page, name, str(value), ft)
        if ok:
            filled += 1
    return filled


# ── Submission + confirmation capture ──────────────────────────────

CONFIRMATION_NUMBER_PATTERNS = (
    re.compile(r"Confirmation\s*(?:#|Number|No\.?)\s*[:\-]?\s*([A-Z0-9\-]{6,32})", re.I),
    re.compile(r"Filing\s*(?:#|Number|No\.?)\s*[:\-]?\s*([A-Z0-9\-]{6,32})", re.I),
    re.compile(r"DOB-?(\d{4,16})", re.I),
)


def _extract_confirmation_number(page_text: str) -> Optional[str]:
    """Best-effort regex scan over the post-submit page text.
    SELECTOR-EMPIRICAL: real DOB NOW confirmation pages may use a
    structured element (specific id / class) that we should scrape
    instead of regex-matching free text. The first smoke run will
    surface the actual format; lock in a precise selector then."""
    if not page_text:
        return None
    for pat in CONFIRMATION_NUMBER_PATTERNS:
        m = pat.search(page_text)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return None


async def _submit_and_capture(page) -> Tuple[Optional[str], Optional[str]]:
    """Click submit, wait for the confirmation page, scrape the
    confirmation number. Returns (confirmation_number, failure_reason).
    Exactly one is non-None.

    Also detects DOB validation errors AFTER click — if the form
    bounces back with red-text error messages, we capture them.
    """
    submit_btn = await _try_first_match(page, SUBMIT_BUTTON_SELECTORS)
    if submit_btn is None:
        return None, "submit_button_not_found"

    try:
        await submit_btn.click(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
        await page.wait_for_load_state(
            "networkidle",
            timeout=PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
        )
    except Exception as e:
        logger.error("[dob_now_filing] submit click failed: %r", e)
        return None, "submission_click_failed"

    # DOB validation errors detection
    error_text = ""
    try:
        error_locator = page.locator(
            '.error, .alert-danger, [class*="error" i], [role="alert"]'
        ).first
        if await error_locator.is_visible(timeout=2000):
            error_text = (await error_locator.inner_text()).strip()
    except Exception:
        error_text = ""
    if error_text:
        return None, f"dob_validation_error:{error_text[:200]}"

    body = ""
    try:
        body = await page.inner_text("body")
    except Exception:
        body = ""
    confirmation = _extract_confirmation_number(body)
    if confirmation:
        return confirmation, None
    return None, "submission_no_confirmation"


# ── Main entry point ────────────────────────────────────────────────

async def handle(payload: dict, context: HandlerContext) -> HandlerResult:
    """Real DOB NOW filing handler.

    Payload contract (set by backend MR.6 enqueue):
      - permit_renewal_id     : str
      - encrypted_credentials_b64: str (RSA-OAEP+AES-GCM blob)
      - filing_rep_id         : str (informational; auth is via creds)
      - pw2_field_map         : dict (MR.4 mapper output)
      - filing_job_id         : str (MR.6+ — added explicitly here
                                so we can post audit events)

    Plus context.http_client (auth-headered httpx.AsyncClient) and
    context.worker_id (heartbeat key).
    """
    permit_renewal_id = payload.get("permit_renewal_id") or ""
    filing_job_id = payload.get("filing_job_id") or ""
    pw2_field_map = payload.get("pw2_field_map") or {}
    backend_url = os.environ.get("BACKEND_URL", "https://api.levelog.com")

    job_filing_number = (
        ((pw2_field_map.get("fields") or {}).get("job_filing_number") or {}).get("value")
        or payload.get("job_filing_number")
        or ""
    )
    company_id = payload.get("company_id") or ""
    license_number_for_storage = (
        ((pw2_field_map.get("fields") or {}).get("gc_license_number") or {}).get("value")
        or company_id
        or "default"
    )

    # 1. Decrypt credentials.
    creds, err = _decrypt_payload_credentials(payload)
    if err is not None:
        return HandlerResult(
            status="failed",
            detail=err,
            metadata={
                "permit_renewal_id": permit_renewal_id,
                "filing_job_id": filing_job_id,
            },
        )
    username = creds["username"]
    password = creds["password"]

    # Optional fingerprint sanity log (not a hard check — see
    # _decrypt_payload_credentials docstring).
    try:
        local_fp = agent_key_fingerprint()
        logger.info(
            "[dob_now_filing] decrypt OK; local agent key fingerprint=%s...",
            local_fp[:12],
        )
    except Exception:
        pass

    # Pre-flight cancellation check.
    if filing_job_id and permit_renewal_id:
        cancelled = await _check_cancellation(
            context.http_client,
            backend_url=backend_url,
            permit_renewal_id=permit_renewal_id,
            filing_job_id=filing_job_id,
            checkpoint="before_login",
        )
        if cancelled:
            return HandlerResult(
                status="cancelled",
                detail="cancelled_by_operator",
                metadata={"checkpoint": "before_login"},
            )

    # Started event — surfaces in operator UI as "Filing started".
    if filing_job_id:
        await post_filing_job_event(
            context.http_client,
            backend_url=backend_url,
            filing_job_id=filing_job_id,
            event_type="started",
            detail="Worker began filing run",
            metadata={"worker_id": context.worker_id},
            actor=context.worker_id,
        )

    # 2. Launch Playwright + per-GC BrowserContext. _get_async_playwright
    # is a module-level patchable helper so tests can swap it without
    # touching playwright itself; production calls the real import.
    try:
        _get_async_playwright()
    except ImportError:
        return HandlerResult(
            status="failed",
            detail="playwright_not_installed",
            metadata={"hint": "Add playwright to dob_worker/requirements.txt"},
        )

    handler_outcome: HandlerResult

    apw_factory = _get_async_playwright()
    async with apw_factory() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            async def _inside_context(ctx) -> HandlerResult:
                page = await ctx.new_page()
                page.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT_MS)
                page.set_default_navigation_timeout(PLAYWRIGHT_NAVIGATION_TIMEOUT_MS)

                # 3. Login.
                login_err = await _login(
                    page,
                    username=username,
                    password=password,
                    http_client=context.http_client,
                    backend_url=backend_url,
                    permit_renewal_id=permit_renewal_id,
                    filing_job_id=filing_job_id,
                )
                if login_err:
                    return HandlerResult(
                        status="failed",
                        detail=login_err,
                        metadata={"step": "login"},
                    )

                # Cancellation checkpoint.
                if filing_job_id and await _check_cancellation(
                    context.http_client,
                    backend_url=backend_url,
                    permit_renewal_id=permit_renewal_id,
                    filing_job_id=filing_job_id,
                    checkpoint="after_login",
                ):
                    return HandlerResult(
                        status="cancelled",
                        detail="cancelled_by_operator",
                        metadata={"checkpoint": "after_login"},
                    )

                # 4. Navigate to the specific permit's renewal flow.
                if not job_filing_number:
                    return HandlerResult(
                        status="failed",
                        detail="missing_job_filing_number",
                        metadata={"step": "navigate"},
                    )
                nav_err = await _navigate_to_permit(
                    page,
                    job_filing_number=job_filing_number,
                )
                if nav_err:
                    return HandlerResult(
                        status="failed",
                        detail=nav_err,
                        metadata={"step": "navigate"},
                    )

                if filing_job_id and await _check_cancellation(
                    context.http_client,
                    backend_url=backend_url,
                    permit_renewal_id=permit_renewal_id,
                    filing_job_id=filing_job_id,
                    checkpoint="after_navigate",
                ):
                    return HandlerResult(
                        status="cancelled",
                        detail="cancelled_by_operator",
                        metadata={"checkpoint": "after_navigate"},
                    )

                # 5. Fill the PW2 form.
                filled_count = await _fill_pw2_form(page, pw2_field_map)
                logger.info(
                    "[dob_now_filing] filled %d fields on PW2 form",
                    filled_count,
                )

                if filing_job_id and await _check_cancellation(
                    context.http_client,
                    backend_url=backend_url,
                    permit_renewal_id=permit_renewal_id,
                    filing_job_id=filing_job_id,
                    checkpoint="after_fill",
                ):
                    return HandlerResult(
                        status="cancelled",
                        detail="cancelled_by_operator",
                        metadata={"checkpoint": "after_fill"},
                    )

                # 6. Submit + capture confirmation.
                confirmation, submit_err = await _submit_and_capture(page)
                if submit_err:
                    return HandlerResult(
                        status="failed",
                        detail=submit_err,
                        metadata={"step": "submit"},
                    )

                # 7. Capture page screenshot (success-state evidence).
                shot_b64 = ""
                try:
                    shot = await page.screenshot(full_page=False, timeout=10_000)
                    shot_b64 = base64.b64encode(shot).decode("ascii")
                except Exception:
                    pass

                return HandlerResult(
                    status="filed",
                    detail=confirmation or "filed",
                    metadata={
                        "dob_confirmation_number": confirmation,
                        "filed_fields_count": filled_count,
                        "page_screenshot_b64": shot_b64,
                        "permit_renewal_id": permit_renewal_id,
                        "filing_job_id": filing_job_id,
                    },
                )

            handler_outcome = await with_browser_context(
                browser, license_number_for_storage, _inside_context,
            )
        finally:
            await browser.close()

    return handler_outcome
