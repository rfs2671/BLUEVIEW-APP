"""
LeveLog Card Audit — NFC Gate Check-In + VLM Enrollment

────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE IS
────────────────────────────────────────────────────────────────────────
A zero-install check-in system for NYC construction workers. Workers
tap their phone to a passive NFC sticker mounted at the project gate.
The sticker's NDEF URL opens a server-rendered HTML page served from
this module. The page handles:

  - First-time enrollment via VLM card parsing (Qwen2.5-VL)
  - Daily check-in via SST card chip tap (Android Web NFC) or manual
    last-6 entry (iPhone)
  - Nightly expiration flagging and four fraud-pattern queries

There is NO worker app, NO worker login, NO worker account, NO kiosk,
NO mounted reader. The worker's phone is a dumb browser. Everything
lives server-side.

────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE VERIFIES
────────────────────────────────────────────────────────────────────────
  - Card possession daily — chip tap binds to enrollment record
  - Card authenticity at enrollment — VLM + photo archive + NDEF URL
    captured once
  - Card expiration ongoing — stored date + nightly check

No runtime fetch of any external card-issuer URL. No parsing of any
external card-issuer page. Those are deliberate omissions — don't
add them back.

────────────────────────────────────────────────────────────────────────
COPY STRINGS + ATTESTATION ENUM
────────────────────────────────────────────────────────────────────────
The strings in the COPY_STRINGS dict below are committed to historical
audit records. The `attestation_type` enum values are likewise written
verbatim into every Mongo row and never renamed. Adding new values is
fine; changing existing ones is a migration.
"""

import os
import re
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
import httpx


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

# R2 bucket for card-audit evidence (signatures, card photos).
# Resolution order:
#   1. CARD_AUDIT_BUCKET_NAME  — dedicated bucket, preferred for
#      production (7-year object lock + lifecycle rules applied
#      out-of-band as an ops runbook).
#   2. R2_BUCKET_NAME          — fallback to the general app bucket
#      with all card-audit keys nested under the "card-audit/" prefix
#      so they're isolated at the path level even when the bucket is
#      shared. This keeps pilot deployments one env-var away from
#      working without a dedicated bucket provisioning step.
#
# The shared-bucket path is production-viable; migrating to a dedicated
# bucket later is a clean prefix-preserving S3 copy, no rewrite of
# historical references.
_DEDICATED_BUCKET = os.environ.get("CARD_AUDIT_BUCKET_NAME", "").strip()
_FALLBACK_BUCKET = os.environ.get("R2_BUCKET_NAME", "").strip()
CARD_AUDIT_BUCKET_NAME = _DEDICATED_BUCKET or _FALLBACK_BUCKET
# Key prefix: empty when we have a dedicated bucket, "card-audit/" when
# we're sharing the general bucket.
CARD_AUDIT_KEY_PREFIX = "" if _DEDICATED_BUCKET else ("card-audit/" if _FALLBACK_BUCKET else "")

# Cookie JWT signing key. Reuses the main app's JWT_SECRET by default —
# card_audit doesn't own its own secret, and these cookies authenticate
# the same "this worker on this phone on this project" identity the
# rest of the stack uses. 90-day lifetime: a full construction season
# covers ~6 months; splitting at 90 days means a returning worker does
# the card-tap fallback at the midpoint of a long project, which is the
# only cheap anti-phone-sharing check we get without re-requiring the
# chip read daily.
CHECKIN_COOKIE_NAME = "lvg_checkin"
CHECKIN_COOKIE_TTL_DAYS = 90
CHECKIN_JWT_SECRET = os.environ.get("JWT_SECRET", "dev-insecure-card-audit-secret")
CHECKIN_JWT_ALG = "HS256"

# Geofence defaults. Per-project override on the project doc.
DEFAULT_GEOFENCE_RADIUS_M = 150
GEOFENCE_MIN_M = 50
GEOFENCE_MAX_M = 1000

# VLM enrollment retry budget
VLM_RETRY_MAX = 2

# Card expiration warning window
EXPIRATION_WARN_DAYS = 30

# Fraud detection windows
DUAL_SITE_WINDOW_DAYS = 1           # same calendar day
CARD_SHARED_WINDOW_DAYS = 90
REPEATED_MISMATCH_WINDOW_DAYS = 30
REPEATED_MISMATCH_THRESHOLD = 3


# ═══════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════

class AttestationType(str, Enum):
    """Written verbatim into sign_ins.attestation_type and
    card_audit_log.attestation_type. Historical rows reference these
    literal strings — do NOT rename existing values.
    """
    AUTOMATED_CARD_CHIP_READ_MATCHED_ENROLLMENT = "automated_card_chip_read_matched_enrollment"
    MANUAL_CARD_ID_ENTRY_MATCHED_ENROLLMENT = "manual_card_id_entry_matched_enrollment"
    ADMIN_ACKNOWLEDGED_FLAG = "admin_acknowledged_flag"
    ADMIN_INVESTIGATED_FLAG = "admin_investigated_flag"
    ADMIN_REVOKED_ENROLLMENT = "admin_revoked_enrollment"
    VLM_CARD_ENROLLMENT_PARSED = "vlm_card_enrollment_parsed"
    VLM_CARD_ENROLLMENT_MANUAL_CORRECTION = "vlm_card_enrollment_manual_correction"
    COOKIE_RECOGNIZED_RETURNING_WORKER = "cookie_recognized_returning_worker"
    DAILY_SIGNATURE_CAPTURED = "daily_signature_captured"


class FraudFlagType(str, Enum):
    DUAL_SITE_SAME_DAY = "dual_site_same_day"
    CARD_SHARED_ACROSS_WORKERS = "card_shared_across_workers"
    REPEATED_MISMATCH = "repeated_mismatch"
    OUT_OF_GEOFENCE = "out_of_geofence"
    EXPIRED_CARD_SIGNIN = "expired_card_signin"


class FraudActionType(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATED = "investigated"
    REVOKED = "revoked"
    FALSE_POSITIVE = "false_positive"


class EnrollmentMethod(str, Enum):
    SELF_SERVE_AT_GATE = "self_serve_at_gate"
    ADMIN_PORTAL = "admin_portal"


class EnrollmentStatus(str, Enum):
    ACTIVE = "active"
    PENDING_APPROVAL = "pending_approval"
    REVOKED = "revoked"


class CardType(str, Enum):
    SST = "SST"
    WORKER_WALLET = "Worker Wallet"
    UNKNOWN = "unknown"


class TapMethod(str, Enum):
    WEB_NFC = "web_nfc"
    MANUAL_ENTRY = "manual_entry"


# ═══════════════════════════════════════════════════════════════════════
# COPY STRINGS — LANGUAGE LOCK
# ═══════════════════════════════════════════════════════════════════════
#
# Any change to CARD_CONFIRMATION_HEADER or the user-facing
# success/failure strings requires a new migration — historical rows
# reference the current wording.

# Dashboard column header.
CARD_CONFIRMATION_HEADER = "Card Confirmation"


# Worker-facing strings — English + Spanish, locked verbatim.
COPY_STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "success": "Checked in. Have a good shift.",
        "failure": "Card not recognized. See your foreman.",
        "tap_instruction": "Tap your SST card to this phone",
        "start_card_scan": "Start Card Scan",
        "manual_header": "Enter the last 6 digits of your card number",
        "submit": "Submit",
        "enrollment_header": "First time here. Let's get you enrolled.",
        "take_photo": "Take a photo of your SST card",
        "retry_photo": "We couldn't read your card clearly. Please take another photo.",
        "correction_header": "Please check the information below and fix anything wrong.",
        "confirm": "Confirm",
        "fix": "Fix",
        "sub_label": "Your company (subcontractor)",
        "trade_label": "Your trade",
        "auto_redirect": "Tap again when ready",
        "loading": "Reading card…",
        "nfc_timeout": "Didn't read. Try again.",
        "nfc_unsupported": "This phone can't read the chip. Enter the last 6 digits of your card.",
        "expired_but_checked_in": "Your card is expired. You are checked in. See your foreman.",
        "sign_here": "Sign for today",
        "clear": "Clear",
        "new_phone_prompt": "New phone? Tap your card once to link it.",
    },
    "es": {
        "success": "Registrado. Buen turno.",
        "failure": "Tarjeta no reconocida. Vea a su supervisor.",
        "tap_instruction": "Acerque su tarjeta SST al teléfono",
        "start_card_scan": "Escanear tarjeta",
        "manual_header": "Escriba los últimos 6 dígitos de su tarjeta",
        "submit": "Enviar",
        "enrollment_header": "Primera vez aquí. Vamos a registrarlo.",
        "take_photo": "Tome una foto de su tarjeta SST",
        "retry_photo": "No pudimos leer su tarjeta. Tome otra foto.",
        "correction_header": "Revise la información y corrija lo que esté mal.",
        "confirm": "Confirmar",
        "fix": "Corregir",
        "sub_label": "Su compañía (subcontratista)",
        "trade_label": "Su oficio",
        "auto_redirect": "Toque de nuevo cuando esté listo",
        "loading": "Leyendo tarjeta…",
        "nfc_timeout": "No se leyó. Intente de nuevo.",
        "nfc_unsupported": "Este teléfono no puede leer el chip. Escriba los últimos 6 dígitos.",
        "expired_but_checked_in": "Su tarjeta está vencida. Está registrado. Vea a su supervisor.",
        "sign_here": "Firme para hoy",
        "clear": "Borrar",
        "new_phone_prompt": "¿Teléfono nuevo? Acerque su tarjeta una vez para vincularlo.",
    },
}


def pick_lang(accept_language: Optional[str]) -> str:
    """Pick UI language from Accept-Language header. English default,
    Spanish if 'es' appears before any other supported language."""
    if not accept_language:
        return "en"
    s = accept_language.lower()
    # Very permissive: if 'es' is first-mentioned, use Spanish
    parts = [p.split(";")[0].strip() for p in s.split(",")]
    for p in parts:
        if p.startswith("es"):
            return "es"
        if p.startswith("en"):
            return "en"
    return "en"


# ═══════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════

class Gate(BaseModel):
    """One NFC-tag-mounted entry gate on a project. Stored inline on
    the project doc. gate_id is a 6-8 char base32 stable UUID chosen at
    creation — short enough to print on a sticker, stable enough to
    never change.
    """
    gate_id: str
    label: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class WorkerEnrollment(BaseModel):
    id: Optional[str] = None
    project_id: str
    card_id: str
    card_id_printed: Optional[str] = None
    worker_name: str
    sub_name: str          # denormalized from project trade_assignments
    trade: str
    card_type: str = CardType.UNKNOWN.value
    card_expiration_date: Optional[datetime] = None
    card_photo_s3_key: Optional[str] = None
    card_photo_sha256: Optional[str] = None
    ndef_url_raw: Optional[str] = None
    enrollment_method: str = EnrollmentMethod.SELF_SERVE_AT_GATE.value
    enrollment_approved: bool = True
    enrolled_at: datetime
    enrolled_by_user_id: Optional[str] = None
    status: str = EnrollmentStatus.ACTIVE.value
    is_deleted: bool = False


class SignIn(BaseModel):
    id: Optional[str] = None
    worker_enrollment_id: str
    project_id: str
    gate_id: str
    card_id_read: str
    card_id_match: bool
    tap_method: str
    user_agent: Optional[str] = None
    geolocation_lat: Optional[float] = None
    geolocation_lng: Optional[float] = None
    within_geofence: Optional[bool] = None   # None = unknown (no project coords)
    attestation_type: str
    timestamp: datetime


class DailySignature(BaseModel):
    """One signature per (worker, project, calendar_date). Captured at
    the first sign-in of the day; reused as the signature block on
    every logbook generated for that worker-day so a worker signs once
    and the system autofills the daily jobsite log, OSHA log,
    subcontractor orientation, etc. Idempotent: multiple sign-ins on
    the same day all reference the one stored signature.
    """
    id: Optional[str] = None
    project_id: str
    worker_enrollment_id: str
    calendar_date: str            # YYYY-MM-DD in America/New_York
    signature_r2_key: Optional[str] = None   # PNG in card-audit bucket
    signature_sha256: Optional[str] = None
    signed_at: datetime
    user_agent: Optional[str] = None


class CardFraudFlag(BaseModel):
    id: Optional[str] = None
    project_id: str
    flag_type: str
    worker_enrollment_id: Optional[str] = None
    card_id: Optional[str] = None
    related_sign_in_ids: List[str] = []
    notes: Optional[str] = None
    raised_at: datetime
    acknowledged_by_user_id: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    action_taken: Optional[str] = None
    is_deleted: bool = False


class UnexpectedNdefHost(BaseModel):
    """Append-only log of NDEF URLs whose host didn't match the
    expected-host allowlist. This is how format drift gets caught BEFORE
    it becomes a silent fraud vector: legitimate URL-structure changes
    show up as a batch of the same new host; a fraud attempt looks
    different from both drift and the status quo.
    """
    id: Optional[str] = None
    project_id: Optional[str] = None
    gate_id: Optional[str] = None
    ndef_url_raw: str
    host: str
    observed_at: datetime


# ═══════════════════════════════════════════════════════════════════════
# CARD ID EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

# Hosts we expect to see in SST/Worker Wallet chip URLs. URL drift is
# expected and not a rejection reason — unexpected hosts are logged to
# `unexpected_ndef_hosts` and proceed. See UnexpectedNdefHost.
_EXPECTED_HOST_SUBSTRINGS = ("trainingconnect", "mycomply", "dobnow", "nyc.gov")

# Permissive card ID validator — 8-32 alphanumeric (possibly hyphenated).
# Tightened in a follow-up PR once a real pilot card URL is captured.
_CARD_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{6,30}[A-Za-z0-9]")


def extract_card_id_from_ndef(ndef_url: str) -> Optional[str]:
    """Extract a card ID from an NDEF URL.

    Strategy: walk the URL path segments and query values, return the
    first token that matches the permissive card-ID shape. Intentionally
    loose — stored ndef_url_raw lets us retroactively re-extract IDs
    from historical rows when the regex tightens after a real pilot URL
    is captured.

    Returns None if no token in the URL matches.
    """
    if not ndef_url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(ndef_url)
        # Candidates in order of preference: last path segment, query
        # values, any remaining path segment.
        candidates: List[str] = []
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            candidates.append(path_parts[-1])
        if parsed.query:
            for kv in parsed.query.split("&"):
                if "=" in kv:
                    _, v = kv.split("=", 1)
                    candidates.append(v)
                else:
                    candidates.append(kv)
        candidates.extend(path_parts[:-1])
        for cand in candidates:
            if _CARD_ID_PATTERN.fullmatch(cand or ""):
                return cand
        # Fallback: scan the full URL for a substring match
        m = _CARD_ID_PATTERN.search(ndef_url)
        if m:
            return m.group(0)
    except Exception as e:
        logger.warning(f"NDEF URL parse failed: {e!r} url={ndef_url[:200]!r}")
    return None


def is_expected_ndef_host(ndef_url: str) -> bool:
    """True iff the URL host contains any of the expected substrings.
    Unexpected hosts are logged and proceed (not rejected) — format drift
    is expected; fraud attempts are not. That's how you tell them apart
    in the audit log later.
    """
    if not ndef_url:
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(ndef_url).hostname or "").lower()
        return any(s in host for s in _EXPECTED_HOST_SUBSTRINGS)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# GEO + HASH HELPERS
# ═══════════════════════════════════════════════════════════════════════

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters between two lat/lng points."""
    import math
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def compute_geofence(
    project_lat: Optional[float],
    project_lng: Optional[float],
    worker_lat: Optional[float],
    worker_lng: Optional[float],
    radius_m: int,
) -> Optional[bool]:
    """Return True/False if both coord pairs are present, else None."""
    if project_lat is None or project_lng is None:
        return None
    if worker_lat is None or worker_lng is None:
        return None
    try:
        d = haversine_m(project_lat, project_lng, worker_lat, worker_lng)
        return d <= radius_m
    except Exception:
        return None


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256 of bytes, stored alongside every uploaded card asset
    so tampering is detectable later."""
    return hashlib.sha256(data).hexdigest()


# ─── Cookie-based worker recognition ────────────────────────────────────
#
# The NFC sticker at the gate only identifies the project+gate, not the
# worker. To avoid making every worker re-tap their card every day, we
# set a long-lived signed cookie on their phone at enrollment / card
# match. Future taps resolve the worker from the cookie and skip the
# card step entirely.
#
# Trade-off: a worker who lets a friend use their phone gets checked
# in as the friend. We accept that — the chip-tap-every-day approach
# the user explicitly rejected as "waste of time" was the only
# stronger check, and the daily signature provides a second layer of
# worker-attested attendance that a stolen phone can't silently fake.

def issue_checkin_cookie_value(worker_enrollment_id: str, project_id: str) -> str:
    """Create a signed JWT the gate page can use to recognize a
    returning worker without a card tap."""
    import jwt as _jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": worker_enrollment_id,
        "pid": project_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=CHECKIN_COOKIE_TTL_DAYS)).timestamp()),
    }
    return _jwt.encode(payload, CHECKIN_JWT_SECRET, algorithm=CHECKIN_JWT_ALG)


def verify_checkin_cookie(cookie_value: Optional[str], project_id: str) -> Optional[str]:
    """Returns worker_enrollment_id if the cookie is valid for this
    project, else None. Invalid, expired, or cross-project cookies
    fall through to the card-tap path."""
    if not cookie_value:
        return None
    try:
        import jwt as _jwt
        payload = _jwt.decode(cookie_value, CHECKIN_JWT_SECRET, algorithms=[CHECKIN_JWT_ALG])
        if payload.get("pid") != project_id:
            return None
        return payload.get("sub") or None
    except Exception:
        return None


def today_ymd_et() -> str:
    """YYYY-MM-DD in America/New_York. A 'workday' for a NYC jobsite
    starts and ends in ET regardless of server timezone — don't key
    daily signatures by UTC or the midnight-shift crew gets split
    across two attendance rows."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def build_card_audit_key(
    project_id: str,
    worker_enrollment_id: str,
    event_type: str,
) -> str:
    """Partitioned key pattern from the spec:
    {project_id}/{worker_enrollment_id}/{YYYY}/{MM}/{event_type}-{uuid}.png

    Partitioning by year/month makes cheap lifecycle rules and compliance
    exports possible at scale. Don't flatten this — at 40M objects the
    flat-namespace bucket becomes unshippable.
    """
    now = datetime.now(timezone.utc)
    return (
        f"{CARD_AUDIT_KEY_PREFIX}"
        f"{project_id}/{worker_enrollment_id}/"
        f"{now.year:04d}/{now.month:02d}/"
        f"{event_type}-{uuid.uuid4()}.png"
    )


# ═══════════════════════════════════════════════════════════════════════
# HTML RENDERING
# ═══════════════════════════════════════════════════════════════════════
#
# Plain f-strings, no Jinja, no templates directory. Three pages. Each
# is mobile-first, Tailwind via CDN, minimum 18pt text, minimum 60pt
# buttons, illustration-first, text-second. Single instruction per
# screen.

_TAILWIND_CDN = '<script src="https://cdn.tailwindcss.com"></script>'

_BASE_STYLES = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  .action-btn { min-height: 60pt; font-size: 20pt; }
  .big-text { font-size: 22pt; line-height: 1.3; }
  .med-text { font-size: 18pt; line-height: 1.4; }
  .illustration { font-size: 96pt; line-height: 1; }
</style>
"""


def _html_shell(title: str, body: str, lang: str = "en") -> str:
    """Wrap page body in minimal HTML shell with Tailwind + base styles."""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>{title}</title>
{_TAILWIND_CDN}
{_BASE_STYLES}
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen flex flex-col items-center justify-start p-4">
{body}
</body>
</html>
"""


def render_gate_landing_page(
    project_id: str,
    project_name: str,
    gate_id: str,
    lang: str,
    is_android_chrome: bool,
) -> str:
    """The page the gate NFC tag opens. Branches on user-agent: Android
    Chrome gets the Web NFC reader, everyone else gets a manual entry
    form."""
    t = COPY_STRINGS[lang]
    header_html = f"""
<div class="w-full max-w-md mx-auto pt-4 pb-2 text-center">
  <div class="text-sm text-slate-500 uppercase tracking-wider">{_esc(project_name)}</div>
</div>
"""

    if is_android_chrome:
        body = f"""
{header_html}
<div class="w-full max-w-md mx-auto flex-1 flex flex-col items-center justify-center">
  <div class="illustration mb-6">📱 ↔ 🪪</div>
  <div class="big-text font-semibold text-center mb-8">{_esc(t['tap_instruction'])}</div>
  <button id="scanBtn" class="action-btn bg-blue-600 text-white rounded-2xl px-10 font-bold shadow-lg">
    {_esc(t['start_card_scan'])}
  </button>
  <div id="statusMsg" class="med-text text-slate-600 mt-6 text-center min-h-[48pt]"></div>
</div>
<form id="submitForm" method="POST" action="/checkin/submit" style="display:none;">
  <input type="hidden" name="project_id" value="{_esc(project_id)}"/>
  <input type="hidden" name="gate_id" value="{_esc(gate_id)}"/>
  <input type="hidden" name="tap_method" value="web_nfc"/>
  <input type="hidden" name="ndef_url_raw" id="ndefField"/>
  <input type="hidden" name="card_id_read" id="cardIdField"/>
  <input type="hidden" name="lat" id="latField"/>
  <input type="hidden" name="lng" id="lngField"/>
</form>
<script>
  // Capture geolocation early; proceed without it if denied.
  let geoLat = null, geoLng = null;
  if (navigator.geolocation) {{
    navigator.geolocation.getCurrentPosition(
      (pos) => {{ geoLat = pos.coords.latitude; geoLng = pos.coords.longitude; }},
      () => {{}},
      {{ enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 }}
    );
  }}
  const btn = document.getElementById('scanBtn');
  const status = document.getElementById('statusMsg');
  btn.addEventListener('click', async () => {{
    if (!('NDEFReader' in window)) {{
      status.textContent = {_jsstr(t['nfc_unsupported'])};
      // Redirect to manual fallback after 2s
      setTimeout(() => {{ location.href = '/checkin/{_esc(project_id)}/{_esc(gate_id)}?mode=manual'; }}, 2000);
      return;
    }}
    try {{
      status.textContent = {_jsstr(t['loading'])};
      btn.disabled = true;
      const reader = new NDEFReader();
      await reader.scan();
      let timedOut = false;
      const timeout = setTimeout(() => {{ timedOut = true; }}, 10000);
      reader.onreading = (event) => {{
        if (timedOut) return;
        clearTimeout(timeout);
        let url = '';
        for (const rec of event.message.records) {{
          if (rec.recordType === 'url' || rec.recordType === 'absolute-url') {{
            url = new TextDecoder().decode(rec.data);
            break;
          }}
          if (!url && rec.recordType === 'text') {{
            url = new TextDecoder().decode(rec.data);
          }}
        }}
        if (!url) {{
          status.textContent = {_jsstr(t['nfc_timeout'])};
          btn.disabled = false;
          return;
        }}
        document.getElementById('ndefField').value = url;
        // Client-side card ID extraction — server re-extracts verbatim.
        const match = url.match(/[A-Za-z0-9][A-Za-z0-9-]{{6,30}}[A-Za-z0-9]/);
        document.getElementById('cardIdField').value = match ? match[0] : '';
        document.getElementById('latField').value = geoLat || '';
        document.getElementById('lngField').value = geoLng || '';
        if (navigator.vibrate) navigator.vibrate(50);
        document.getElementById('submitForm').submit();
      }};
      reader.onreadingerror = () => {{
        status.textContent = {_jsstr(t['nfc_timeout'])};
        btn.disabled = false;
      }};
    }} catch (e) {{
      status.textContent = {_jsstr(t['nfc_timeout'])};
      btn.disabled = false;
    }}
  }});
</script>
"""
    else:
        # iOS Safari / other — manual entry only
        body = f"""
{header_html}
<div class="w-full max-w-md mx-auto flex-1 flex flex-col items-center justify-center">
  <div class="illustration mb-6">🪪</div>
  <div class="big-text font-semibold text-center mb-6">{_esc(t['manual_header'])}</div>
  <form method="POST" action="/checkin/submit" class="w-full flex flex-col items-center gap-4">
    <input type="hidden" name="project_id" value="{_esc(project_id)}"/>
    <input type="hidden" name="gate_id" value="{_esc(gate_id)}"/>
    <input type="hidden" name="tap_method" value="manual_entry"/>
    <input type="hidden" name="lat" id="latField"/>
    <input type="hidden" name="lng" id="lngField"/>
    <input type="text"
           name="card_id_read"
           inputmode="numeric"
           autocomplete="off"
           maxlength="10"
           minlength="6"
           pattern="[A-Za-z0-9]{{6,10}}"
           required
           class="w-full text-center text-4xl tracking-widest font-mono border-2 border-slate-300 rounded-2xl py-5"
           placeholder="______"/>
    <button type="submit" class="action-btn bg-blue-600 text-white rounded-2xl px-10 font-bold shadow-lg">
      {_esc(t['submit'])}
    </button>
  </form>
</div>
<script>
  if (navigator.geolocation) {{
    navigator.geolocation.getCurrentPosition(
      (pos) => {{
        document.getElementById('latField').value = pos.coords.latitude;
        document.getElementById('lngField').value = pos.coords.longitude;
      }},
      () => {{}},
      {{ enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 }}
    );
  }}
</script>
"""
    return _html_shell("Check in", body, lang)


def render_enrollment_page(
    project_id: str,
    gate_id: str,
    card_id_read: str,
    lang: str,
    error_msg: Optional[str] = None,
) -> str:
    """Shown when card_id_read has no matching enrollment — worker is
    new and must enroll before today's sign-in completes."""
    t = COPY_STRINGS[lang]
    err_html = ""
    if error_msg:
        err_html = f'<div class="med-text text-red-700 bg-red-50 rounded-xl p-3 mb-4">{_esc(error_msg)}</div>'
    body = f"""
<div class="w-full max-w-md mx-auto pt-4">
  <div class="big-text font-semibold text-center mb-6">{_esc(t['enrollment_header'])}</div>
  <div class="illustration text-center mb-6">🪪 📸</div>
  {err_html}
  <form method="POST" action="/enrollment/parse_card" enctype="multipart/form-data" class="flex flex-col gap-4">
    <input type="hidden" name="project_id" value="{_esc(project_id)}"/>
    <input type="hidden" name="gate_id" value="{_esc(gate_id)}"/>
    <input type="hidden" name="card_id_read" value="{_esc(card_id_read)}"/>
    <label class="action-btn bg-blue-600 text-white rounded-2xl px-6 font-bold shadow-lg flex items-center justify-center cursor-pointer">
      <input type="file" name="card_photo" accept="image/*" capture="environment" required class="hidden" onchange="this.form.submit()"/>
      📷 {_esc(t['take_photo'])}
    </label>
  </form>
</div>
"""
    return _html_shell("Enroll", body, lang)


def render_enrollment_confirm_page(
    project_id: str,
    gate_id: str,
    card_id_read: str,
    parsed: Dict[str, Any],
    subcontractors: List[Dict[str, Any]],
    lang: str,
    correction_mode: bool = False,
) -> str:
    """Read-only tiles of VLM-extracted fields with Confirm button +
    Fix link. If correction_mode=True, tiles become editable inputs."""
    t = COPY_STRINGS[lang]
    header = t['correction_header'] if correction_mode else t['enrollment_header']

    def field(name: str, label: str, value: str, editable: bool) -> str:
        value = value or ""
        if editable:
            return f"""
<div class="border-2 border-slate-200 rounded-xl p-3">
  <div class="text-xs uppercase tracking-wider text-slate-500 mb-1">{_esc(label)}</div>
  <input type="text" name="{name}" value="{_esc(value)}" class="w-full text-lg font-semibold bg-transparent focus:outline-none"/>
</div>"""
        return f"""
<div class="bg-slate-100 rounded-xl p-3">
  <div class="text-xs uppercase tracking-wider text-slate-500 mb-1">{_esc(label)}</div>
  <div class="text-lg font-semibold">{_esc(value)}</div>
  <input type="hidden" name="{name}" value="{_esc(value)}"/>
</div>"""

    tiles = "".join([
        field("worker_name", "Name", parsed.get("full_legal_name") or "", correction_mode),
        field("card_id", "Card ID", parsed.get("card_id") or "", correction_mode),
        field("card_expiration_date", "Expiration", parsed.get("expiration_date") or "", correction_mode),
        field("card_type", "Card type", parsed.get("card_type") or "unknown", correction_mode),
    ])

    # Sub dropdown reuses project's trade_assignments — unique companies
    sub_options = sorted({s.get("company", "") for s in subcontractors if s.get("company")})
    sub_html = '<select name="sub_name" required class="border-2 border-slate-200 rounded-xl p-3 text-lg">'
    sub_html += f'<option value="">— {_esc(t["sub_label"])} —</option>'
    for name in sub_options:
        sub_html += f'<option value="{_esc(name)}">{_esc(name)}</option>'
    sub_html += "</select>"

    # Trade dropdown — populated client-side based on sub pick (since
    # trades are per-sub on this project).
    import json as _json
    sub_to_trades_map = {}
    for s in subcontractors:
        co = s.get("company", "")
        tr = s.get("trade", "")
        if co and tr:
            sub_to_trades_map.setdefault(co, []).append(tr)
    trade_html = f'''
<select name="trade" required id="tradeSelect" class="border-2 border-slate-200 rounded-xl p-3 text-lg">
  <option value="">— {_esc(t["trade_label"])} —</option>
</select>
<script>
const subToTrades = {_json.dumps(sub_to_trades_map)};
document.querySelector('select[name="sub_name"]').addEventListener('change', (e) => {{
  const trades = subToTrades[e.target.value] || [];
  const ts = document.getElementById('tradeSelect');
  ts.innerHTML = '<option value="">— {_esc(t["trade_label"])} —</option>' +
    trades.map(t => `<option value="${{t}}">${{t}}</option>`).join('');
  // Auto-select + hide if only one trade for this sub
  if (trades.length === 1) {{
    ts.value = trades[0];
    ts.parentElement.style.display = 'none';
  }}
}});
</script>'''

    body = f"""
<div class="w-full max-w-md mx-auto pt-4">
  <div class="big-text font-semibold text-center mb-6">{_esc(header)}</div>
  <form method="POST" action="/enrollment/complete" class="flex flex-col gap-3">
    <input type="hidden" name="project_id" value="{_esc(project_id)}"/>
    <input type="hidden" name="gate_id" value="{_esc(gate_id)}"/>
    <input type="hidden" name="card_id_read" value="{_esc(card_id_read)}"/>
    <input type="hidden" name="correction_mode" value="{'1' if correction_mode else '0'}"/>
    {tiles}
    {sub_html}
    {trade_html}
    <button type="submit" class="action-btn bg-green-600 text-white rounded-2xl px-10 font-bold shadow-lg mt-4">
      {_esc(t['confirm'])}
    </button>
    {"" if correction_mode else f'<a href="?fix=1&project_id={_esc(project_id)}&gate_id={_esc(gate_id)}" class="text-center text-slate-500 underline med-text mt-2">{_esc(t["fix"])}</a>'}
  </form>
</div>
"""
    return _html_shell("Confirm enrollment", body, lang)


def render_signature_pad_page(
    project_id: str,
    gate_id: str,
    worker_first_name: str,
    project_name: str,
    lang: str,
) -> str:
    """One-time-per-day signature capture. Touch canvas + Submit. The
    captured PNG is reused as the signature block on every logbook the
    worker appears in for the day — they sign once, the rest autofills.
    """
    t = COPY_STRINGS[lang]
    body = f"""
<div class="w-full max-w-md mx-auto pt-4">
  <div class="text-center med-text text-slate-500 mb-1">{_esc(project_name)}</div>
  <div class="big-text font-semibold text-center mb-2">{_esc(worker_first_name)}</div>
  <div class="med-text text-center text-slate-600 mb-4">{_esc(t['sign_here'])}</div>
  <div class="bg-white rounded-2xl border-2 border-slate-300 p-2 mb-3">
    <canvas id="pad" width="600" height="280" class="w-full touch-none bg-white rounded-xl" style="height:220px"></canvas>
  </div>
  <div class="flex gap-3">
    <button id="clearBtn" class="flex-1 action-btn bg-slate-200 text-slate-900 rounded-2xl font-bold">
      {_esc(t['clear'])}
    </button>
    <button id="submitBtn" class="flex-[2] action-btn bg-green-600 text-white rounded-2xl font-bold">
      {_esc(t['submit'])}
    </button>
  </div>
  <form id="signForm" method="POST" action="/checkin/sign" style="display:none;">
    <input type="hidden" name="project_id" value="{_esc(project_id)}"/>
    <input type="hidden" name="gate_id" value="{_esc(gate_id)}"/>
    <input type="hidden" name="signature_png" id="sigField"/>
    <input type="hidden" name="lat" id="latField"/>
    <input type="hidden" name="lng" id="lngField"/>
  </form>
</div>
<script>
(function(){{
  const cv = document.getElementById('pad');
  const ctx = cv.getContext('2d');
  // Scale canvas to device pixel ratio for a crisp line
  const dpr = window.devicePixelRatio || 1;
  const rect = cv.getBoundingClientRect();
  cv.width = rect.width * dpr;
  cv.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#1e293b';
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, rect.width, rect.height);

  let drawing = false, last = null, hasInk = false;
  function pt(e) {{
    const r = cv.getBoundingClientRect();
    const t = (e.touches && e.touches[0]) || e;
    return {{ x: t.clientX - r.left, y: t.clientY - r.top }};
  }}
  function start(e) {{ e.preventDefault(); drawing = true; last = pt(e); }}
  function move(e) {{
    if (!drawing) return;
    e.preventDefault();
    const p = pt(e);
    ctx.beginPath();
    ctx.moveTo(last.x, last.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    last = p;
    hasInk = true;
  }}
  function end() {{ drawing = false; last = null; }}
  cv.addEventListener('mousedown', start);
  cv.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);
  cv.addEventListener('touchstart', start, {{passive:false}});
  cv.addEventListener('touchmove', move, {{passive:false}});
  cv.addEventListener('touchend', end);

  document.getElementById('clearBtn').onclick = () => {{
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, rect.width, rect.height);
    hasInk = false;
  }};

  if (navigator.geolocation) {{
    navigator.geolocation.getCurrentPosition(
      (p) => {{
        document.getElementById('latField').value = p.coords.latitude;
        document.getElementById('lngField').value = p.coords.longitude;
      }}, () => {{}},
      {{ enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 }}
    );
  }}

  document.getElementById('submitBtn').onclick = () => {{
    if (!hasInk) return;
    document.getElementById('sigField').value = cv.toDataURL('image/png');
    document.getElementById('signForm').submit();
  }};
}})();
</script>
"""
    return _html_shell("Sign for today", body, lang)


def render_success_page(
    worker_first_name: str,
    project_name: str,
    timestamp: datetime,
    lang: str,
    expired_warning: bool = False,
) -> str:
    """Full-screen green check, worker's first name, project, timestamp.
    Loud, fast, auto-dismiss after 5s. Haptic if supported."""
    t = COPY_STRINGS[lang]
    ts_str = timestamp.strftime("%H:%M")
    success_msg = t['success']
    extra_banner = ""
    if expired_warning:
        extra_banner = f"""
<div class="absolute top-6 left-4 right-4 bg-orange-100 text-orange-900 rounded-xl p-3 med-text font-semibold text-center">
  {_esc(t['expired_but_checked_in'])}
</div>
"""
    body = f"""
<div class="fixed inset-0 bg-green-500 flex flex-col items-center justify-center text-white relative">
  {extra_banner}
  <div style="font-size:160pt;line-height:1">✓</div>
  <div class="big-text font-bold mt-2">{_esc(success_msg)}</div>
  <div class="med-text mt-4">{_esc(worker_first_name)}</div>
  <div class="med-text opacity-80">{_esc(project_name)}</div>
  <div class="med-text opacity-60 mt-2">{ts_str}</div>
</div>
<script>
  if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
  setTimeout(() => {{ document.body.innerHTML =
    '<div class="fixed inset-0 bg-slate-100 flex items-center justify-center text-slate-500 big-text p-6 text-center">' +
    {_jsstr(t['auto_redirect'])} + '</div>';
  }}, 5000);
</script>
"""
    return _html_shell("Checked in", body, lang)


def render_failure_page(lang: str, detail: Optional[str] = None) -> str:
    t = COPY_STRINGS[lang]
    detail_html = f'<div class="med-text opacity-80 mt-3">{_esc(detail)}</div>' if detail else ""
    body = f"""
<div class="fixed inset-0 bg-red-600 flex flex-col items-center justify-center text-white p-6 text-center">
  <div style="font-size:160pt;line-height:1">✕</div>
  <div class="big-text font-bold mt-4">{_esc(t['failure'])}</div>
  {detail_html}
</div>
"""
    return _html_shell("Failed", body, lang)


# Small escapers local to the module
def _esc(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _jsstr(s: Any) -> str:
    """Safely embed a string in a JS literal."""
    import json as _json
    return _json.dumps(str(s or ""))


# ═══════════════════════════════════════════════════════════════════════
# MODULE STATE — INJECTED AT STARTUP
# ═══════════════════════════════════════════════════════════════════════
#
# The card_audit module doesn't own the Mongo client; server.py injects
# the `db` reference + the R2 client + the Qwen VLM helper via init().
# This keeps the module testable and avoids import cycles.

_db = None
_r2_client = None
_qwen_vlm = None  # async fn: (jpeg_bytes, prompt) -> str
_get_current_user_dep = None  # FastAPI dependency to resolve the acting admin user


def init(
    *,
    db_ref,
    r2_client=None,
    qwen_vlm=None,
    get_current_user_dep=None,
):
    """Called from server.py startup to hand this module its deps.
    Keeps the module free of circular imports into server.py."""
    global _db, _r2_client, _qwen_vlm, _get_current_user_dep
    _db = db_ref
    _r2_client = r2_client
    _qwen_vlm = qwen_vlm
    _get_current_user_dep = get_current_user_dep


def _require_db():
    if _db is None:
        raise RuntimeError("card_audit.init() was never called; _db is None")
    return _db


# ═══════════════════════════════════════════════════════════════════════
# AUDIT LOG WRITER
# ═══════════════════════════════════════════════════════════════════════

async def write_audit_log(
    *,
    attestation_type: str,
    project_id: Optional[str] = None,
    worker_enrollment_id: Optional[str] = None,
    sign_in_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    device_ua: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
):
    """Append-only. Never update, never delete. Local Law 196 evidence."""
    db = _require_db()
    row = {
        "attestation_type": attestation_type,
        "project_id": project_id,
        "worker_enrollment_id": worker_enrollment_id,
        "sign_in_id": sign_in_id,
        "actor_user_id": actor_user_id,
        "device_ua": device_ua,
        "lat": lat,
        "lng": lng,
        "details": details or {},
        "observed_at": datetime.now(timezone.utc),
    }
    try:
        await db.card_audit_log.insert_one(row)
    except Exception as e:
        # Audit log write failures must never break the caller — they
        # should surface as ops alerts, not user-facing 500s.
        logger.error(f"card_audit_log write failed: {e!r} row={row}")


# ═══════════════════════════════════════════════════════════════════════
# R2 UPLOAD
# ═══════════════════════════════════════════════════════════════════════

def upload_card_photo_to_r2(
    image_bytes: bytes,
    project_id: str,
    worker_enrollment_id: str,
    event_type: str,
    content_type: str = "image/jpeg",
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (s3_key, sha256) or (None, None) if bucket not configured.
    Bucket is the SEPARATE card-audit bucket with 7-year object lock —
    not the general R2 bucket — so don't fall through to R2_BUCKET_NAME
    as a default.
    """
    if not _r2_client or not CARD_AUDIT_BUCKET_NAME:
        logger.warning(
            "CARD_AUDIT_BUCKET_NAME not configured — card photo not persisted"
        )
        return None, None
    key = build_card_audit_key(project_id, worker_enrollment_id, event_type)
    digest = sha256_hex(image_bytes)
    try:
        _r2_client.put_object(
            Bucket=CARD_AUDIT_BUCKET_NAME,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
            # Object lock metadata is enforced at the bucket level (ops
            # runbook); we include a SHA-256 as custom metadata for
            # chain-of-custody at key level too.
            Metadata={"sha256": digest},
        )
        return key, digest
    except Exception as e:
        logger.error(f"R2 card-audit upload failed key={key}: {e!r}")
        return None, None


# ═══════════════════════════════════════════════════════════════════════
# ROUTERS
# ═══════════════════════════════════════════════════════════════════════
#
# Two routers:
#   `gate_router` — unprefixed, serves HTML at /checkin/... and
#       /enrollment/... — these are the URLs printed on NFC stickers
#       and posted to by the server-rendered forms. No /api prefix,
#       because workers see these URLs.
#   `admin_router` — /api-prefixed, JSON, admin-authenticated.
#       Consumed by the LeveLog admin dashboard.

gate_router = APIRouter(tags=["card_audit_gate"])
admin_router = APIRouter(prefix="/api", tags=["card_audit_admin"])


def _pick_lang(request: Request) -> str:
    return pick_lang(request.headers.get("accept-language"))


def _is_android_chrome(ua: str) -> bool:
    if not ua:
        return False
    lua = ua.lower()
    return "android" in lua and "chrome" in lua and "wv" not in lua


# ─── GET /checkin/{project_id}/{gate_id} ────────────────────────────────

@gate_router.get("/checkin/{project_id}/{gate_id}", response_class=HTMLResponse)
async def gate_landing(project_id: str, gate_id: str, request: Request, mode: Optional[str] = None):
    """The page the gate NFC tag opens. No auth — public.

    Three paths, branched server-side:
      1. Valid cookie + signature already captured today → write sign_in,
         full-screen success immediately. Worker taps and keeps walking.
      2. Valid cookie, no signature today → signature pad.
      3. No cookie (new phone / cleared cookies / enrollment day) →
         card picker (Android chip tap or iOS manual last-6).
    """
    db = _require_db()
    lang = _pick_lang(request)
    ua = request.headers.get("user-agent", "")

    project = await db.projects.find_one({"_id": _to_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        return HTMLResponse(render_failure_page(lang, "Unknown project"), status_code=404)

    gates = project.get("gates") or []
    if not any(g.get("gate_id") == gate_id for g in gates):
        return HTMLResponse(render_failure_page(lang, "Unknown gate"), status_code=404)

    # Path 1 + 2: cookie recognition. `mode=manual` forces the card path
    # for a user whose cookie is stale / phone is shared.
    if mode != "manual":
        cookie_val = request.cookies.get(CHECKIN_COOKIE_NAME)
        worker_id = verify_checkin_cookie(cookie_val, project_id)
        if worker_id:
            enrollment = await db.worker_enrollments.find_one({
                "_id": _to_id(worker_id),
                "status": EnrollmentStatus.ACTIVE.value,
                "is_deleted": {"$ne": True},
            })
            if enrollment:
                today = today_ymd_et()
                sig = await db.daily_signatures.find_one({
                    "project_id": project_id,
                    "worker_enrollment_id": worker_id,
                    "calendar_date": today,
                })
                if sig:
                    # Fast path — signed already today, just write the
                    # sign_in row and show the green check.
                    sign_in_id = await _write_cookie_signin(
                        enrollment=enrollment,
                        project=project,
                        gate_id=gate_id,
                        request=request,
                    )
                    return RedirectResponse(
                        url=f"/checkin/success/{sign_in_id}?expired=0",
                        status_code=303,
                    )
                # Recognized but unsigned today — show the signature pad
                first_name = (enrollment.get("worker_name") or "").split(" ")[0]
                html = render_signature_pad_page(
                    project_id=project_id,
                    gate_id=gate_id,
                    worker_first_name=first_name,
                    project_name=project.get("name") or "",
                    lang=lang,
                )
                return HTMLResponse(html)

    # Path 3: no cookie — show card picker
    show_android = (mode != "manual") and _is_android_chrome(ua)
    html = render_gate_landing_page(
        project_id=project_id,
        project_name=project.get("name") or "",
        gate_id=gate_id,
        lang=lang,
        is_android_chrome=show_android,
    )
    return HTMLResponse(html)


async def _write_cookie_signin(
    *,
    enrollment: Dict[str, Any],
    project: Dict[str, Any],
    gate_id: str,
    request: Request,
) -> str:
    """Write a sign_in row for a cookie-recognized returning worker.
    No card_id_read because no tap happened — the field is set to the
    enrollment's stored card_id for audit/query continuity."""
    db = _require_db()
    ua = request.headers.get("user-agent", "")
    lat = _parse_float(request.query_params.get("lat"))
    lng = _parse_float(request.query_params.get("lng"))
    radius = int(project.get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M)
    within = compute_geofence(project.get("lat"), project.get("lng"), lat, lng, radius)
    now = datetime.now(timezone.utc)
    project_id = str(project["_id"])
    row = {
        "worker_enrollment_id": str(enrollment["_id"]),
        "project_id": project_id,
        "gate_id": gate_id,
        "card_id_read": enrollment.get("card_id"),
        "ndef_url_raw": None,
        "card_id_match": True,
        "tap_method": "cookie_recognized",
        "user_agent": ua,
        "geolocation_lat": lat,
        "geolocation_lng": lng,
        "within_geofence": within,
        "attestation_type": AttestationType.COOKIE_RECOGNIZED_RETURNING_WORKER.value,
        "timestamp": now,
    }
    res = await db.sign_ins.insert_one(row)
    sign_in_id = str(res.inserted_id)
    await write_audit_log(
        attestation_type=AttestationType.COOKIE_RECOGNIZED_RETURNING_WORKER.value,
        project_id=project_id,
        worker_enrollment_id=str(enrollment["_id"]),
        sign_in_id=sign_in_id,
        device_ua=ua,
        lat=lat,
        lng=lng,
        details={"gate_id": gate_id},
    )
    return sign_in_id


# ─── POST /checkin/submit ───────────────────────────────────────────────

@gate_router.post("/checkin/submit", response_class=HTMLResponse)
async def checkin_submit(request: Request):
    """Handles both chip-tap and manual-entry form submits."""
    db = _require_db()
    form = await request.form()
    project_id = str(form.get("project_id") or "").strip()
    gate_id = str(form.get("gate_id") or "").strip()
    card_id_read = str(form.get("card_id_read") or "").strip()
    tap_method = str(form.get("tap_method") or "manual_entry").strip()
    ndef_url_raw = str(form.get("ndef_url_raw") or "").strip() or None
    ua = request.headers.get("user-agent", "")
    lang = _pick_lang(request)
    lat = _parse_float(form.get("lat"))
    lng = _parse_float(form.get("lng"))

    if not project_id or not gate_id:
        return HTMLResponse(render_failure_page(lang, "Missing identifiers"), status_code=400)

    project = await db.projects.find_one({"_id": _to_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        return HTMLResponse(render_failure_page(lang, "Unknown project"), status_code=404)

    # Log unexpected NDEF hosts (don't reject — spec rule: log and proceed)
    if ndef_url_raw and not is_expected_ndef_host(ndef_url_raw):
        try:
            from urllib.parse import urlparse
            host = urlparse(ndef_url_raw).hostname or ""
            await db.unexpected_ndef_hosts.insert_one({
                "project_id": project_id,
                "gate_id": gate_id,
                "ndef_url_raw": ndef_url_raw,
                "host": host,
                "observed_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning(f"unexpected_ndef_hosts log failed: {e!r}")

    # Card ID extraction: prefer client-extracted value, fall back to
    # server-side re-extract from ndef_url_raw.
    if not card_id_read and ndef_url_raw:
        card_id_read = extract_card_id_from_ndef(ndef_url_raw) or ""

    # Validate card ID shape (8-32 alphanumeric). Manual-entry fallback
    # accepts 6-10 (last 6 of printed).
    if tap_method == TapMethod.MANUAL_ENTRY.value:
        valid = bool(card_id_read) and 6 <= len(card_id_read) <= 10 and card_id_read.isalnum()
    else:
        valid = bool(card_id_read) and 8 <= len(card_id_read) <= 32 and _CARD_ID_PATTERN.fullmatch(card_id_read)
    if not valid:
        return HTMLResponse(render_failure_page(lang, None), status_code=400)

    # Look up enrollment on this project. Chip-tap matches `card_id`.
    # Manual entry matches by last-6 of `card_id_printed` (the number
    # visible on the card face, which often differs from the embedded
    # chip ID).
    enrollment = None
    if tap_method == TapMethod.MANUAL_ENTRY.value:
        # Last-6 suffix match on card_id_printed
        enrollment = await db.worker_enrollments.find_one({
            "project_id": project_id,
            "card_id_printed": {"$regex": re.escape(card_id_read) + "$", "$options": "i"},
            "status": EnrollmentStatus.ACTIVE.value,
            "is_deleted": {"$ne": True},
        })
    else:
        enrollment = await db.worker_enrollments.find_one({
            "project_id": project_id,
            "card_id": card_id_read,
            "status": EnrollmentStatus.ACTIVE.value,
            "is_deleted": {"$ne": True},
        })

    if not enrollment:
        # New worker — return the enrollment form with the card ID
        # pre-filled so we can bind it to the new enrollment row.
        return HTMLResponse(render_enrollment_page(project_id, gate_id, card_id_read, lang))

    # Geofence
    p_lat = project.get("lat")
    p_lng = project.get("lng")
    radius = int(project.get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M)
    within = compute_geofence(p_lat, p_lng, lat, lng, radius)

    # Expiration check (don't block — log + flag)
    expired = False
    exp = enrollment.get("card_expiration_date")
    if exp and isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            expired = True

    # Write sign_in row
    attestation = (
        AttestationType.MANUAL_CARD_ID_ENTRY_MATCHED_ENROLLMENT.value
        if tap_method == TapMethod.MANUAL_ENTRY.value
        else AttestationType.AUTOMATED_CARD_CHIP_READ_MATCHED_ENROLLMENT.value
    )
    sign_in_row = {
        "worker_enrollment_id": str(enrollment["_id"]),
        "project_id": project_id,
        "gate_id": gate_id,
        "card_id_read": card_id_read,
        "ndef_url_raw": ndef_url_raw,
        "card_id_match": True,
        "tap_method": tap_method,
        "user_agent": ua,
        "geolocation_lat": lat,
        "geolocation_lng": lng,
        "within_geofence": within,
        "attestation_type": attestation,
        "timestamp": datetime.now(timezone.utc),
    }
    result = await db.sign_ins.insert_one(sign_in_row)
    sign_in_id = str(result.inserted_id)

    # Expired-card flag — not a block
    if expired:
        await db.card_fraud_flags.insert_one({
            "project_id": project_id,
            "flag_type": FraudFlagType.EXPIRED_CARD_SIGNIN.value,
            "worker_enrollment_id": str(enrollment["_id"]),
            "card_id": enrollment.get("card_id"),
            "related_sign_in_ids": [sign_in_id],
            "raised_at": datetime.now(timezone.utc),
            "is_deleted": False,
        })

    await write_audit_log(
        attestation_type=attestation,
        project_id=project_id,
        worker_enrollment_id=str(enrollment["_id"]),
        sign_in_id=sign_in_id,
        device_ua=ua,
        lat=lat,
        lng=lng,
        details={"gate_id": gate_id, "tap_method": tap_method, "card_id": card_id_read},
    )

    # Set the 90-day recognition cookie so this phone skips the card
    # step on subsequent taps.
    cookie_val = issue_checkin_cookie_value(str(enrollment["_id"]), project_id)

    # Branch: already signed today → success. Else signature pad.
    today = today_ymd_et()
    sig = await db.daily_signatures.find_one({
        "project_id": project_id,
        "worker_enrollment_id": str(enrollment["_id"]),
        "calendar_date": today,
    })
    if sig:
        resp = RedirectResponse(
            url=f"/checkin/success/{sign_in_id}?expired={'1' if expired else '0'}",
            status_code=303,
        )
    else:
        resp = RedirectResponse(
            url=f"/checkin/{project_id}/{gate_id}",
            status_code=303,
        )
    resp.set_cookie(
        key=CHECKIN_COOKIE_NAME,
        value=cookie_val,
        max_age=CHECKIN_COOKIE_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp


# ─── POST /checkin/sign ─────────────────────────────────────────────────

@gate_router.post("/checkin/sign", response_class=HTMLResponse)
async def checkin_sign(request: Request):
    """Accept the day's signature PNG (data URL), upload to R2, write
    the daily_signatures row, write the sign_in row, redirect to the
    success page. Idempotent — a second submit on the same
    (project, worker, date) replaces the prior row."""
    db = _require_db()
    form = await request.form()
    project_id = str(form.get("project_id") or "").strip()
    gate_id = str(form.get("gate_id") or "").strip()
    sig_data_url = str(form.get("signature_png") or "").strip()
    lang = _pick_lang(request)
    ua = request.headers.get("user-agent", "")

    cookie_val = request.cookies.get(CHECKIN_COOKIE_NAME)
    worker_id = verify_checkin_cookie(cookie_val, project_id)
    if not worker_id:
        return HTMLResponse(render_failure_page(lang, "Please tap your card"), status_code=401)

    enrollment = await db.worker_enrollments.find_one({
        "_id": _to_id(worker_id),
        "status": EnrollmentStatus.ACTIVE.value,
        "is_deleted": {"$ne": True},
    })
    if not enrollment:
        return HTMLResponse(render_failure_page(lang, "Enrollment not found"), status_code=404)

    project = await db.projects.find_one({"_id": _to_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        return HTMLResponse(render_failure_page(lang, "Unknown project"), status_code=404)

    if not sig_data_url.startswith("data:image/"):
        return HTMLResponse(render_failure_page(lang, "Signature missing"), status_code=400)

    try:
        import base64 as _b64
        header, b64 = sig_data_url.split(",", 1)
        sig_bytes = _b64.b64decode(b64)
    except Exception:
        return HTMLResponse(render_failure_page(lang, "Signature invalid"), status_code=400)

    # Upload signature to the card-audit bucket under a per-date key so
    # it's idempotent and auditable.
    today = today_ymd_et()
    sig_key = None
    sig_hash = None
    if _r2_client and CARD_AUDIT_BUCKET_NAME:
        sig_key = (
            f"{CARD_AUDIT_KEY_PREFIX}"
            f"{project_id}/{worker_id}/signatures/"
            f"{today[:4]}/{today[5:7]}/{today}.png"
        )
        sig_hash = sha256_hex(sig_bytes)
        try:
            _r2_client.put_object(
                Bucket=CARD_AUDIT_BUCKET_NAME,
                Key=sig_key,
                Body=sig_bytes,
                ContentType="image/png",
                Metadata={"sha256": sig_hash},
            )
        except Exception as e:
            logger.error(f"daily signature R2 upload failed for {worker_id} on {today}: {e!r}")

    now = datetime.now(timezone.utc)
    await db.daily_signatures.update_one(
        {"project_id": project_id, "worker_enrollment_id": worker_id, "calendar_date": today},
        {"$set": {
            "project_id": project_id,
            "worker_enrollment_id": worker_id,
            "calendar_date": today,
            "signature_r2_key": sig_key,
            "signature_sha256": sig_hash,
            "signed_at": now,
            "user_agent": ua,
        }},
        upsert=True,
    )

    # Write the sign_in row for this gate tap (the one that triggered
    # the signature prompt).
    lat = _parse_float(form.get("lat"))
    lng = _parse_float(form.get("lng"))
    radius = int(project.get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M)
    within = compute_geofence(project.get("lat"), project.get("lng"), lat, lng, radius)

    sign_in_doc = {
        "worker_enrollment_id": worker_id,
        "project_id": project_id,
        "gate_id": gate_id,
        "card_id_read": enrollment.get("card_id"),
        "ndef_url_raw": None,
        "card_id_match": True,
        "tap_method": "cookie_recognized",
        "user_agent": ua,
        "geolocation_lat": lat,
        "geolocation_lng": lng,
        "within_geofence": within,
        "attestation_type": AttestationType.COOKIE_RECOGNIZED_RETURNING_WORKER.value,
        "timestamp": now,
    }
    si_res = await db.sign_ins.insert_one(sign_in_doc)
    sign_in_id = str(si_res.inserted_id)

    await write_audit_log(
        attestation_type=AttestationType.DAILY_SIGNATURE_CAPTURED.value,
        project_id=project_id,
        worker_enrollment_id=worker_id,
        sign_in_id=sign_in_id,
        device_ua=ua,
        lat=lat,
        lng=lng,
        details={"calendar_date": today, "signature_r2_key": sig_key},
    )

    # Check expiration so the success banner reflects it
    expired = False
    exp = enrollment.get("card_expiration_date")
    if exp and isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            expired = True

    return RedirectResponse(
        url=f"/checkin/success/{sign_in_id}?expired={'1' if expired else '0'}",
        status_code=303,
    )


async def get_daily_signature(
    *,
    worker_enrollment_id: str,
    project_id: str,
    calendar_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Public helper for logbook autofill. Returns the day's signature
    row or None. `calendar_date` defaults to today (America/New_York).

    Other modules (OSHA log generator, daily jobsite log, etc.) import
    this to stamp the worker's signature block on rendered forms
    without asking the worker to re-sign.

    Returned dict shape:
      { 'signature_r2_key': str | None,
        'signature_sha256': str | None,
        'signed_at': datetime,
        'calendar_date': 'YYYY-MM-DD' }
    """
    db = _require_db()
    date_key = calendar_date or today_ymd_et()
    doc = await db.daily_signatures.find_one({
        "worker_enrollment_id": worker_enrollment_id,
        "project_id": project_id,
        "calendar_date": date_key,
    })
    if not doc:
        return None
    return {
        "signature_r2_key": doc.get("signature_r2_key"),
        "signature_sha256": doc.get("signature_sha256"),
        "signed_at": doc.get("signed_at"),
        "calendar_date": doc.get("calendar_date"),
    }


# Signature access is via the authenticated backend proxy endpoint
# `GET /api/signatures/{signin_id}` in server.py. No presigned URL
# generation for signature objects anywhere in the codebase — logbook
# forms stay open for a full shift and a 1-hour presigned URL is
# unreliable for that. Presigned URLs remain valid for other asset
# types (card photos, enrollment artifacts) but not for signatures.


# ─── GET /checkin/success/{sign_in_id} ──────────────────────────────────

@gate_router.get("/checkin/success/{sign_in_id}", response_class=HTMLResponse)
async def checkin_success(sign_in_id: str, request: Request, expired: str = "0"):
    db = _require_db()
    try:
        from bson import ObjectId
        sign_in = await db.sign_ins.find_one({"_id": ObjectId(sign_in_id)})
    except Exception:
        sign_in = None
    if not sign_in:
        return HTMLResponse(render_failure_page(_pick_lang(request)), status_code=404)

    lang = _pick_lang(request)
    enrollment = await db.worker_enrollments.find_one({"_id": _to_id(sign_in["worker_enrollment_id"])})
    project = await db.projects.find_one({"_id": _to_id(sign_in["project_id"])})
    first_name = ((enrollment or {}).get("worker_name") or "").split(" ")[0]
    project_name = (project or {}).get("name") or ""
    html = render_success_page(
        worker_first_name=first_name,
        project_name=project_name,
        timestamp=sign_in.get("timestamp") or datetime.now(timezone.utc),
        lang=lang,
        expired_warning=(expired == "1"),
    )
    return HTMLResponse(html)


# ─── POST /enrollment/parse_card ────────────────────────────────────────

@gate_router.post("/enrollment/parse_card", response_class=HTMLResponse)
async def enrollment_parse_card(request: Request):
    """VLM extracts card_id, full_legal_name, expiration_date, card_type
    from the uploaded card photo. Returns the read-only confirm page."""
    db = _require_db()
    form = await request.form()
    project_id = str(form.get("project_id") or "").strip()
    gate_id = str(form.get("gate_id") or "").strip()
    card_id_read = str(form.get("card_id_read") or "").strip()
    lang = _pick_lang(request)

    file: Optional[UploadFile] = form.get("card_photo")  # type: ignore
    if not file or not isinstance(file, UploadFile):
        return HTMLResponse(render_enrollment_page(project_id, gate_id, card_id_read, lang, COPY_STRINGS[lang]["retry_photo"]), status_code=400)

    img_bytes = await file.read()
    if not img_bytes:
        return HTMLResponse(render_enrollment_page(project_id, gate_id, card_id_read, lang, COPY_STRINGS[lang]["retry_photo"]), status_code=400)

    parsed = {}
    raw_vlm_response = ""
    if _qwen_vlm is None:
        # Without VLM configured we jump straight to manual-correction
        # mode so enrollment isn't dead in the water.
        parsed = {
            "card_id": card_id_read,
            "full_legal_name": "",
            "expiration_date": "",
            "card_type": CardType.UNKNOWN.value,
            "issuing_course_provider": "",
        }
        raw_vlm_response = "vlm_not_configured"
    else:
        try:
            prompt = (
                "Extract the following from this construction SST / Worker Wallet card "
                "image. Return ONLY valid JSON, no markdown:\n"
                '{"card_id": "the ID number on the card (alphanumeric, 8-32 chars, the number used to verify training)", '
                '"full_legal_name": "the full name printed on the card", '
                '"expiration_date": "the expiration date in YYYY-MM-DD format, or null if not visible", '
                '"card_type": "one of: SST, Worker Wallet, unknown", '
                '"issuing_course_provider": "the organization that issued the card, or null"}\n'
                "If a field is not visible, set it to null. Return JSON object only."
            )
            raw_vlm_response = await _qwen_vlm(img_bytes, prompt)
            import json as _json
            # Strip any markdown fencing before json.loads
            txt = raw_vlm_response.strip()
            if txt.startswith("```"):
                txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt).rstrip("`").rstrip()
                if txt.endswith("```"):
                    txt = txt[:-3]
            parsed = _json.loads(txt)
        except Exception as e:
            logger.warning(f"VLM card parse failed: {e!r} response={raw_vlm_response[:500]!r}")
            parsed = {
                "card_id": "",
                "full_legal_name": "",
                "expiration_date": "",
                "card_type": CardType.UNKNOWN.value,
                "issuing_course_provider": "",
            }

    # Validate the parsed fields with permissive rules
    valid_id = bool(parsed.get("card_id")) and _CARD_ID_PATTERN.fullmatch(str(parsed.get("card_id")) or "")
    exp_ok = True
    try:
        if parsed.get("expiration_date"):
            dt = datetime.fromisoformat(str(parsed["expiration_date"]))
            today = datetime.now(timezone.utc).date()
            exp_date = dt.date() if dt.tzinfo is None else dt.astimezone(timezone.utc).date()
            if exp_date < today or exp_date > today.replace(year=today.year + 5):
                exp_ok = False
    except Exception:
        exp_ok = False

    subs = (await db.projects.find_one({"_id": _to_id(project_id)}) or {}).get("trade_assignments") or []

    # Stash the upload in a pending-enrollment doc so /enrollment/complete
    # can pick it up without requiring the form to re-send the file.
    pending_id = str(uuid.uuid4())
    await db.pending_enrollments.insert_one({
        "_id": pending_id,
        "project_id": project_id,
        "gate_id": gate_id,
        "card_id_read": card_id_read,
        "parsed": parsed,
        "raw_vlm_response": raw_vlm_response,
        "image_bytes_sha256": sha256_hex(img_bytes),
        "image_content_type": file.content_type or "image/jpeg",
        "image_bytes": img_bytes,   # temp — discarded after /complete
        "created_at": datetime.now(timezone.utc),
    })

    # If extraction clearly failed, drop into correction mode (editable)
    correction = not (valid_id and exp_ok)
    html = render_enrollment_confirm_page(
        project_id=project_id,
        gate_id=gate_id,
        card_id_read=card_id_read,
        parsed=parsed,
        subcontractors=subs,
        lang=lang,
        correction_mode=correction,
    )
    # Embed the pending_id as a hidden field via script patching
    html = html.replace(
        '</form>',
        f'<input type="hidden" name="pending_id" value="{_esc(pending_id)}"/></form>',
        1,
    )
    await write_audit_log(
        attestation_type=(
            AttestationType.VLM_CARD_ENROLLMENT_MANUAL_CORRECTION.value
            if correction else AttestationType.VLM_CARD_ENROLLMENT_PARSED.value
        ),
        project_id=project_id,
        details={
            "pending_id": pending_id,
            "parsed_card_id": parsed.get("card_id"),
            "vlm_response_preview": (raw_vlm_response or "")[:500],
        },
    )
    return HTMLResponse(html)


# ─── POST /enrollment/complete ──────────────────────────────────────────

@gate_router.post("/enrollment/complete", response_class=HTMLResponse)
async def enrollment_complete(request: Request):
    db = _require_db()
    form = await request.form()
    project_id = str(form.get("project_id") or "").strip()
    gate_id = str(form.get("gate_id") or "").strip()
    card_id_read = str(form.get("card_id_read") or "").strip()
    pending_id = str(form.get("pending_id") or "").strip()
    lang = _pick_lang(request)
    ua = request.headers.get("user-agent", "")

    pending = await db.pending_enrollments.find_one({"_id": pending_id}) if pending_id else None
    if not pending:
        return HTMLResponse(render_failure_page(lang, "Enrollment session expired"), status_code=400)

    project = await db.projects.find_one({"_id": _to_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        return HTMLResponse(render_failure_page(lang, "Unknown project"), status_code=404)

    worker_name = str(form.get("worker_name") or pending["parsed"].get("full_legal_name") or "").strip()
    card_id = str(form.get("card_id") or pending["parsed"].get("card_id") or "").strip()
    exp_raw = str(form.get("card_expiration_date") or pending["parsed"].get("expiration_date") or "").strip()
    card_type = str(form.get("card_type") or pending["parsed"].get("card_type") or CardType.UNKNOWN.value).strip()
    sub_name = str(form.get("sub_name") or "").strip()
    trade = str(form.get("trade") or "").strip()

    if not worker_name or not card_id or not sub_name or not trade:
        return HTMLResponse(render_failure_page(lang, "Missing required fields"), status_code=400)

    if not _CARD_ID_PATTERN.fullmatch(card_id):
        return HTMLResponse(render_failure_page(lang, "Card ID invalid"), status_code=400)

    exp_dt: Optional[datetime] = None
    if exp_raw:
        try:
            exp_dt = datetime.fromisoformat(exp_raw)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        except Exception:
            exp_dt = None

    # Reject dup card on this project
    dup = await db.worker_enrollments.find_one({
        "project_id": project_id,
        "card_id": card_id,
        "is_deleted": {"$ne": True},
    })
    if dup:
        return HTMLResponse(render_failure_page(lang, "Card already enrolled on this project"), status_code=409)

    now = datetime.now(timezone.utc)
    enrollment_doc = {
        "project_id": project_id,
        "card_id": card_id,
        "card_id_printed": card_id,  # placeholder until printed-vs-embedded is split
        "worker_name": worker_name,
        "sub_name": sub_name,
        "trade": trade,
        "card_type": card_type,
        "card_expiration_date": exp_dt,
        "card_photo_s3_key": None,
        "card_photo_sha256": None,
        "ndef_url_raw": pending.get("ndef_url_raw"),
        "enrollment_method": EnrollmentMethod.SELF_SERVE_AT_GATE.value,
        "enrollment_approved": True,
        "enrolled_at": now,
        "enrolled_by_user_id": None,
        "status": EnrollmentStatus.ACTIVE.value,
        "is_deleted": False,
    }
    insert_result = await db.worker_enrollments.insert_one(enrollment_doc)
    enrollment_id = str(insert_result.inserted_id)

    # Upload card photo to the card-audit bucket
    try:
        key, digest = upload_card_photo_to_r2(
            pending["image_bytes"],
            project_id,
            enrollment_id,
            "enrollment",
            content_type=pending.get("image_content_type", "image/jpeg"),
        )
        if key:
            await db.worker_enrollments.update_one(
                {"_id": insert_result.inserted_id},
                {"$set": {"card_photo_s3_key": key, "card_photo_sha256": digest}},
            )
    except Exception as e:
        logger.error(f"card photo upload failed for enrollment {enrollment_id}: {e!r}")

    # Clean up the pending row (contains image bytes — don't leave around)
    try:
        await db.pending_enrollments.delete_one({"_id": pending_id})
    except Exception:
        pass

    # Auto-complete today's sign-in for this freshly enrolled worker
    lat = _parse_float(form.get("lat"))
    lng = _parse_float(form.get("lng"))
    within = compute_geofence(
        project.get("lat"),
        project.get("lng"),
        lat, lng,
        int(project.get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M),
    )
    sign_in_doc = {
        "worker_enrollment_id": enrollment_id,
        "project_id": project_id,
        "gate_id": gate_id,
        "card_id_read": card_id,
        "ndef_url_raw": pending.get("ndef_url_raw"),
        "card_id_match": True,
        "tap_method": TapMethod.MANUAL_ENTRY.value,  # enrollment path is always manual-like
        "user_agent": ua,
        "geolocation_lat": lat,
        "geolocation_lng": lng,
        "within_geofence": within,
        "attestation_type": AttestationType.MANUAL_CARD_ID_ENTRY_MATCHED_ENROLLMENT.value,
        "timestamp": now,
    }
    si_res = await db.sign_ins.insert_one(sign_in_doc)
    sign_in_id = str(si_res.inserted_id)

    await write_audit_log(
        attestation_type=AttestationType.VLM_CARD_ENROLLMENT_PARSED.value,
        project_id=project_id,
        worker_enrollment_id=enrollment_id,
        sign_in_id=sign_in_id,
        device_ua=ua,
        lat=lat,
        lng=lng,
        details={
            "gate_id": gate_id,
            "card_id": card_id,
            "sub_name": sub_name,
            "trade": trade,
            "card_type": card_type,
        },
    )

    # Issue the recognition cookie + redirect into the signature pad.
    # Enrollment day = first signature day.
    cookie_val = issue_checkin_cookie_value(enrollment_id, project_id)
    resp = RedirectResponse(url=f"/checkin/{project_id}/{gate_id}", status_code=303)
    resp.set_cookie(
        key=CHECKIN_COOKIE_NAME,
        value=cookie_val,
        max_age=CHECKIN_COOKIE_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp


# ═══════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@admin_router.get("/admin/projects/{project_id}/card-queue")
async def card_queue(project_id: str, request: Request):
    """Unified queue for the admin dashboard: pending enrollments,
    unacknowledged fraud flags, expired/expiring cards.

    Auth is enforced by an include_router dependency at mount time in
    server.py — this endpoint assumes the request has already been
    admin-gated by the time it runs.
    """
    db = _require_db()
    now = datetime.now(timezone.utc)
    warn_cutoff = now + timedelta(days=EXPIRATION_WARN_DAYS)

    pending = await db.worker_enrollments.find({
        "project_id": project_id,
        "status": EnrollmentStatus.PENDING_APPROVAL.value,
        "is_deleted": {"$ne": True},
    }).to_list(200)

    flags = await db.card_fraud_flags.find({
        "project_id": project_id,
        "acknowledged_at": None,
        "is_deleted": {"$ne": True},
    }).sort("raised_at", -1).to_list(500)

    expiring = await db.worker_enrollments.find({
        "project_id": project_id,
        "status": EnrollmentStatus.ACTIVE.value,
        "card_expiration_date": {"$lte": warn_cutoff},
        "is_deleted": {"$ne": True},
    }).to_list(500)

    return {
        "project_id": project_id,
        "column_header": CARD_CONFIRMATION_HEADER,
        "pending_enrollments": [_serialize_enrollment(e) for e in pending],
        "fraud_flags": [_serialize_flag(f) for f in flags],
        "expiring_cards": [_serialize_enrollment(e) for e in expiring],
    }


@admin_router.post("/admin/card-flags/{flag_id}/action")
async def card_flag_action(flag_id: str, body: Dict[str, Any], request: Request):
    """Acknowledge / investigate / revoke a flag. All three paths write
    to the audit log. Auth via include_router dep at mount time."""
    db = _require_db()
    action = str(body.get("action") or "").strip().lower()
    if action not in {a.value for a in FraudActionType}:
        raise HTTPException(status_code=400, detail="Invalid action")

    from bson import ObjectId
    try:
        oid = ObjectId(flag_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid flag id")

    flag = await db.card_fraud_flags.find_one({"_id": oid})
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")

    # server.py's admin dep stores the resolved user on request.state;
    # we read it here rather than declaring it as a param, because the
    # dep is injected at mount time (include_router dependencies=),
    # not per-endpoint.
    actor_user = getattr(request.state, "current_user", None) or {}
    actor_id = actor_user.get("id") if isinstance(actor_user, dict) else None
    now = datetime.now(timezone.utc)
    await db.card_fraud_flags.update_one(
        {"_id": oid},
        {"$set": {
            "action_taken": action,
            "acknowledged_by_user_id": actor_id,
            "acknowledged_at": now,
        }},
    )

    attestation_map = {
        FraudActionType.ACKNOWLEDGED.value: AttestationType.ADMIN_ACKNOWLEDGED_FLAG.value,
        FraudActionType.INVESTIGATED.value: AttestationType.ADMIN_INVESTIGATED_FLAG.value,
        FraudActionType.REVOKED.value: AttestationType.ADMIN_REVOKED_ENROLLMENT.value,
        FraudActionType.FALSE_POSITIVE.value: AttestationType.ADMIN_ACKNOWLEDGED_FLAG.value,
    }
    if action == FraudActionType.REVOKED.value and flag.get("worker_enrollment_id"):
        await db.worker_enrollments.update_one(
            {"_id": _to_id(flag["worker_enrollment_id"])},
            {"$set": {"status": EnrollmentStatus.REVOKED.value}},
        )

    await write_audit_log(
        attestation_type=attestation_map[action],
        project_id=flag.get("project_id"),
        worker_enrollment_id=flag.get("worker_enrollment_id"),
        actor_user_id=actor_id,
        details={"flag_id": flag_id, "flag_type": flag.get("flag_type"), "action": action},
    )
    return {"ok": True, "action": action}


# ═══════════════════════════════════════════════════════════════════════
# NIGHTLY JOBS
# ═══════════════════════════════════════════════════════════════════════

async def check_card_expirations():
    """Runs nightly. No external URL fetch — just compares stored
    card_expiration_date against today. Raises expired_card_signin flag
    for expiration transitions that don't already have an active flag.
    """
    db = _require_db()
    now = datetime.now(timezone.utc)
    warn_cutoff = now + timedelta(days=EXPIRATION_WARN_DAYS)

    cursor = db.worker_enrollments.find({
        "status": EnrollmentStatus.ACTIVE.value,
        "card_expiration_date": {"$lte": warn_cutoff},
        "is_deleted": {"$ne": True},
    })
    processed = 0
    async for e in cursor:
        processed += 1
        # Does an unacknowledged expired flag already exist for this
        # enrollment? If yes, don't double-raise.
        existing = await db.card_fraud_flags.find_one({
            "worker_enrollment_id": str(e["_id"]),
            "flag_type": FraudFlagType.EXPIRED_CARD_SIGNIN.value,
            "acknowledged_at": None,
            "is_deleted": {"$ne": True},
        })
        if existing:
            continue
        await db.card_fraud_flags.insert_one({
            "project_id": e.get("project_id"),
            "flag_type": FraudFlagType.EXPIRED_CARD_SIGNIN.value,
            "worker_enrollment_id": str(e["_id"]),
            "card_id": e.get("card_id"),
            "related_sign_in_ids": [],
            "notes": f"card_expiration_date={e.get('card_expiration_date')}",
            "raised_at": now,
            "is_deleted": False,
        })
    logger.info(f"check_card_expirations: {processed} active enrollments within {EXPIRATION_WARN_DAYS}d expiry window")


async def run_fraud_detection():
    """Four nightly queries:
      1. dual_site_same_day
      2. card_shared_across_workers (90-day window, ≥3 workers)
      3. repeated_mismatch (30-day window, ≥3 mismatches, same worker)
      4. out_of_geofence (weekly summary aggregation into one flag)
    """
    db = _require_db()
    now = datetime.now(timezone.utc)

    # ── 1. dual_site_same_day ──────────────────────────────────────────
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    pipeline = [
        {"$match": {"timestamp": {"$gte": day_start - timedelta(days=1)}}},
        {"$group": {
            "_id": {"card_id": "$card_id_read", "project_id": "$project_id"},
            "sign_ins": {"$push": "$_id"},
        }},
        {"$group": {
            "_id": "$_id.card_id",
            "projects": {"$addToSet": "$_id.project_id"},
            "all_sign_ins": {"$push": "$sign_ins"},
        }},
        {"$match": {"projects.1": {"$exists": True}}},  # 2+ projects
    ]
    try:
        async for group in db.sign_ins.aggregate(pipeline):
            card_id = group["_id"]
            projects = group["projects"]
            all_si = [str(x) for sub in group["all_sign_ins"] for x in sub]
            # Raise one flag per project-card pair; flag semantics per
            # answer 1 in the spec: flag, not block.
            for p in projects:
                existing = await db.card_fraud_flags.find_one({
                    "project_id": p,
                    "card_id": card_id,
                    "flag_type": FraudFlagType.DUAL_SITE_SAME_DAY.value,
                    "raised_at": {"$gte": day_start},
                    "is_deleted": {"$ne": True},
                })
                if existing:
                    continue
                counterparties = [x for x in projects if x != p]
                await db.card_fraud_flags.insert_one({
                    "project_id": p,
                    "flag_type": FraudFlagType.DUAL_SITE_SAME_DAY.value,
                    "card_id": card_id,
                    "related_sign_in_ids": all_si,
                    "notes": f"Same card signed in at {len(counterparties)} other project(s): {counterparties}",
                    "raised_at": now,
                    "is_deleted": False,
                })
    except Exception as e:
        logger.error(f"fraud.dual_site_same_day failed: {e!r}")

    # ── 2. card_shared_across_workers ──────────────────────────────────
    ninety_days_ago = now - timedelta(days=CARD_SHARED_WINDOW_DAYS)
    pipe2 = [
        {"$match": {"timestamp": {"$gte": ninety_days_ago}}},
        {"$group": {
            "_id": "$card_id_read",
            "workers": {"$addToSet": "$worker_enrollment_id"},
            "sign_ins": {"$push": "$_id"},
            "projects": {"$addToSet": "$project_id"},
        }},
        {"$match": {"workers.2": {"$exists": True}}},  # 3+ workers
    ]
    try:
        async for g in db.sign_ins.aggregate(pipe2):
            card_id = g["_id"]
            for p in g.get("projects") or []:
                existing = await db.card_fraud_flags.find_one({
                    "project_id": p,
                    "card_id": card_id,
                    "flag_type": FraudFlagType.CARD_SHARED_ACROSS_WORKERS.value,
                    "acknowledged_at": None,
                    "is_deleted": {"$ne": True},
                })
                if existing:
                    continue
                await db.card_fraud_flags.insert_one({
                    "project_id": p,
                    "flag_type": FraudFlagType.CARD_SHARED_ACROSS_WORKERS.value,
                    "card_id": card_id,
                    "related_sign_in_ids": [str(x) for x in (g.get("sign_ins") or [])],
                    "notes": f"Card tied to {len(g['workers'])} distinct workers in last 90 days",
                    "raised_at": now,
                    "is_deleted": False,
                })
    except Exception as e:
        logger.error(f"fraud.card_shared_across_workers failed: {e!r}")

    # ── 3. repeated_mismatch ───────────────────────────────────────────
    thirty_days_ago = now - timedelta(days=REPEATED_MISMATCH_WINDOW_DAYS)
    pipe3 = [
        {"$match": {
            "timestamp": {"$gte": thirty_days_ago},
            "card_id_match": False,
        }},
        {"$group": {
            "_id": "$worker_enrollment_id",
            "count": {"$sum": 1},
            "sign_ins": {"$push": "$_id"},
            "projects": {"$addToSet": "$project_id"},
        }},
        {"$match": {"count": {"$gte": REPEATED_MISMATCH_THRESHOLD}}},
    ]
    try:
        async for g in db.sign_ins.aggregate(pipe3):
            worker_id = g["_id"]
            for p in g.get("projects") or []:
                existing = await db.card_fraud_flags.find_one({
                    "project_id": p,
                    "worker_enrollment_id": worker_id,
                    "flag_type": FraudFlagType.REPEATED_MISMATCH.value,
                    "acknowledged_at": None,
                    "is_deleted": {"$ne": True},
                })
                if existing:
                    continue
                await db.card_fraud_flags.insert_one({
                    "project_id": p,
                    "flag_type": FraudFlagType.REPEATED_MISMATCH.value,
                    "worker_enrollment_id": worker_id,
                    "related_sign_in_ids": [str(x) for x in (g.get("sign_ins") or [])],
                    "notes": f"{g['count']} mismatches in last 30 days",
                    "raised_at": now,
                    "is_deleted": False,
                })
    except Exception as e:
        logger.error(f"fraud.repeated_mismatch failed: {e!r}")

    # ── 4. out_of_geofence (weekly summary) ────────────────────────────
    week_ago = now - timedelta(days=7)
    pipe4 = [
        {"$match": {
            "timestamp": {"$gte": week_ago},
            "within_geofence": False,
        }},
        {"$group": {
            "_id": "$project_id",
            "count": {"$sum": 1},
            "sign_ins": {"$push": "$_id"},
        }},
    ]
    try:
        async for g in db.sign_ins.aggregate(pipe4):
            p = g["_id"]
            # Replace the previous week's summary flag if unacknowledged
            await db.card_fraud_flags.delete_many({
                "project_id": p,
                "flag_type": FraudFlagType.OUT_OF_GEOFENCE.value,
                "acknowledged_at": None,
            })
            await db.card_fraud_flags.insert_one({
                "project_id": p,
                "flag_type": FraudFlagType.OUT_OF_GEOFENCE.value,
                "related_sign_in_ids": [str(x) for x in (g.get("sign_ins") or [])][:200],
                "notes": f"{g['count']} sign-ins outside geofence in last 7 days",
                "raised_at": now,
                "is_deleted": False,
            })
    except Exception as e:
        logger.error(f"fraud.out_of_geofence failed: {e!r}")

    logger.info("run_fraud_detection: complete")


async def ensure_indexes():
    """Create the indexes needed for the queries above. Idempotent —
    Mongo silently skips if they already exist."""
    db = _require_db()
    try:
        await db.worker_enrollments.create_index([("project_id", 1), ("card_id", 1)], unique=True, sparse=True)
        await db.worker_enrollments.create_index([("project_id", 1), ("card_id_printed", 1)])
        await db.worker_enrollments.create_index([("status", 1), ("card_expiration_date", 1)])

        await db.sign_ins.create_index([("project_id", 1), ("timestamp", -1)])
        await db.sign_ins.create_index([("card_id_read", 1), ("timestamp", -1)])
        await db.sign_ins.create_index([("worker_enrollment_id", 1), ("timestamp", -1)])

        await db.card_fraud_flags.create_index([("project_id", 1), ("acknowledged_at", 1), ("raised_at", -1)])
        await db.card_fraud_flags.create_index([("card_id", 1)])

        await db.card_audit_log.create_index([("project_id", 1), ("observed_at", -1)])
        await db.card_audit_log.create_index([("attestation_type", 1), ("observed_at", -1)])

        await db.unexpected_ndef_hosts.create_index([("observed_at", -1)])

        # One daily signature per (worker, project, date). The unique
        # index prevents two signatures colliding if the worker taps
        # twice before the first upload settles.
        await db.daily_signatures.create_index(
            [("project_id", 1), ("worker_enrollment_id", 1), ("calendar_date", 1)],
            unique=True,
        )
        await db.daily_signatures.create_index(
            [("project_id", 1), ("calendar_date", 1)]
        )

        # Pending enrollment rows carry the raw image bytes between
        # /enrollment/parse_card and /enrollment/complete. If a worker
        # abandons the flow, Mongo gets cluttered with orphan images —
        # TTL expires the row 30 minutes after creation.
        await db.pending_enrollments.create_index(
            [("created_at", 1)],
            expireAfterSeconds=1800,
        )
        logger.info("card_audit indexes ensured")
    except Exception as e:
        logger.warning(f"card_audit index creation failed: {e!r}")


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _to_id(s: Any):
    """Convert a string ID (or ObjectId, or any) to ObjectId when
    possible, else return as-is. Matches server.py's `to_query_id`
    pattern."""
    from bson import ObjectId
    if isinstance(s, ObjectId):
        return s
    try:
        return ObjectId(str(s))
    except Exception:
        return s


def _parse_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _serialize_enrollment(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(e.get("_id")),
        "project_id": e.get("project_id"),
        "worker_name": e.get("worker_name"),
        "card_id": e.get("card_id"),
        "sub_name": e.get("sub_name"),
        "trade": e.get("trade"),
        "card_type": e.get("card_type"),
        "card_expiration_date": _iso(e.get("card_expiration_date")),
        "enrolled_at": _iso(e.get("enrolled_at")),
        "status": e.get("status"),
    }


def _serialize_flag(f: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(f.get("_id")),
        "project_id": f.get("project_id"),
        "flag_type": f.get("flag_type"),
        "worker_enrollment_id": f.get("worker_enrollment_id"),
        "card_id": f.get("card_id"),
        "related_sign_in_ids": f.get("related_sign_in_ids") or [],
        "notes": f.get("notes"),
        "raised_at": _iso(f.get("raised_at")),
        "acknowledged_at": _iso(f.get("acknowledged_at")),
        "action_taken": f.get("action_taken"),
    }


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.isoformat()
    return None
