from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import resend
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File, Form
import base64
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
from bson import ObjectId
import httpx
import asyncio
import io
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# IMPORTANT: every import below this line that targets a sibling
# module (e.g. `from lib.foo import X` or `from dob_complaint_codes
# import Y`) RELIES on the sys.path.insert above. Putting them
# above this line crashes deployment because Railway's WORKDIR isn't
# backend/ — the script's directory must be added to sys.path before
# any sibling/subpackage import can resolve. (Step 4 regression,
# fixed: f5cb4eb. CI smoke test enforces this going forward.)
from lib.server_http import ServerHttpClient
import re
import hashlib
from urllib.parse import quote_plus
import json
from dob_complaint_codes import classify_complaint, get_disposition_label, get_category_label
import mimetypes

try:
    import boto3
    from botocore.config import Config as BotoConfig
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# ==================== DROPBOX URL CACHE ====================
_dropbox_url_cache: dict = {}

def _cache_key(file_path: str) -> str:
    return hashlib.md5(file_path.encode()).hexdigest()

def _get_cached_url(company_id: str, file_path: str):
    now = datetime.now(timezone.utc)
    entry = _dropbox_url_cache.get(company_id, {}).get(_cache_key(file_path))
    if entry and entry["expires_at"] > now:
        return entry["url"]
    return None

def _set_cached_url(company_id: str, file_path: str, url: str):
    if company_id not in _dropbox_url_cache:
        _dropbox_url_cache[company_id] = {}
    _dropbox_url_cache[company_id][_cache_key(file_path)] = {
        "url": url,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=3),
    }

# ==================== CLOUDFLARE R2 STORAGE ====================

def _get_r2_client():
    """Get boto3 S3 client configured for Cloudflare R2. Returns None if not configured."""
    if not _BOTO3_AVAILABLE:
        return None
    if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY or not R2_ENDPOINT_URL:
        return None
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )

_r2_client = None  # initialized in startup_event


def _upload_to_r2(file_bytes: bytes, r2_key: str, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to R2, returns the public URL. Returns empty string if R2 not configured."""
    if not _r2_client or not R2_BUCKET_NAME:
        return ""
    _r2_client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=r2_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL.rstrip('/')}/{r2_key}"
    return f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}/{r2_key}"


def _presign_r2_get(r2_key: str, expires_in: int = 3600) -> str:
    """Return a short-lived signed GET URL for a private R2 object.

    Works even when the bucket has no public R2.dev subdomain enabled.
    Returns '' if R2 is not configured or signing fails.
    """
    if not _r2_client or not R2_BUCKET_NAME or not r2_key:
        return ""
    try:
        return _r2_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": r2_key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.error(f"R2 presign failed for {r2_key}: {e}")
        return ""

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET')
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required. The server will not start without it.")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 720

DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY', '37ueec2e4se8gbg')
DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET', '9uvjvxkh9gvelys')
DROPBOX_REDIRECT_URI = os.environ.get('DROPBOX_REDIRECT_URI', 'https://api.levelog.com/api/dropbox/callback')

GOOGLE_PLACES_API_KEY = os.environ.get('GOOGLE_PLACES_API_KEY', '')

# Cloudflare R2 storage
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')

# WhatsApp (WaAPI) integration
WAAPI_BASE_URL = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
WAAPI_INSTANCE_ID = os.environ.get("WAAPI_INSTANCE_ID", "")
WAAPI_TOKEN = os.environ.get("WAAPI_TOKEN", "")
WHATSAPP_VENDOR = os.environ.get("WHATSAPP_VENDOR", "waapi")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Qwen2.5-VL via Together AI (OpenAI-compatible) — used for plan indexing
# and query-time sheet matching. 7B model chosen over 72B: title-block
# extraction is a structured task where accuracy is effectively the same
# but 7B is ~10x cheaper and ~3x lower latency.
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
QWEN_API_BASE = os.environ.get("QWEN_API_BASE", "https://api.together.xyz/v1")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")

SCREENSHOT_ENABLED = False

scheduler = AsyncIOScheduler()

app = FastAPI(title="Levelog API", version="2.0.0")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",") if os.environ.get("ALLOWED_ORIGINS") else [
    "https://levelog.com",
    "https://www.levelog.com",
    "https://api.levelog.com",
    # Mozilla's hosted pdf.js viewer is embedded in the native WebView to render
    # PDFs — its JS fetches the file via cross-origin GET, so the backend must
    # allow its origin on the streaming endpoint.
    "https://mozilla.github.io",
    "http://localhost:8081",
    "http://localhost:19006",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Content-Disposition"],
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer(auto_error=False)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== RATE LIMITING (auth endpoints) ====================

from collections import defaultdict
import time as _time

class RateLimiter:
    """Simple in-memory rate limiter for auth endpoints."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = _time.time()
        # Prune expired entries
        self._hits[key] = [t for t in self._hits[key] if now - t < self.window]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True

auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 10 req/min per IP
checkin_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)  # 30 req/min per IP — shift start bursts

async def check_auth_rate_limit(request: Request):
    """Dependency: rate limit login/register by client IP."""
    client_ip = request.client.host if request.client else "unknown"
    if not auth_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

# ==================== AUDIT LOGGING ====================

async def _verify_resend_domain_at_startup() -> None:
    """Probe Resend's /domains endpoint and assert levelog.com is verified.

    Catches DNS expiration, accidental DKIM record deletion, Resend
    account state changes, and copy-paste env errors BEFORE the next
    7am ET digest cron tick goes silent. Logs at ERROR if not verified
    so we see it in Railway log filters; never crashes startup
    (an email-config issue should not 503 the API).

    Runs once at startup. The domain status doesn't change minute-to-
    minute and we don't want to hammer Resend's API.
    """
    if not RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY unset; renewal digest emails will be no-op."
        )
        return
    try:
        from lib.server_http import ServerHttpClient
        async with ServerHttpClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            )
        if resp.status_code != 200:
            logger.warning(
                f"Resend health check: GET /domains returned "
                f"{resp.status_code} (expected 200). "
                f"Email send may fail."
            )
            return
        body = resp.json() or {}
        domains = body.get("data") or body  # tolerate v1/v2 shapes
        if not isinstance(domains, list):
            domains = []
        levelog = next(
            (d for d in domains
             if isinstance(d, dict) and d.get("name") == "levelog.com"),
            None,
        )
        if not levelog:
            logger.error(
                "Resend health check: levelog.com NOT in domain list. "
                "Renewal digest emails will fail. Add the domain at "
                "resend.com/domains."
            )
            return
        status = levelog.get("status")
        if status != "verified":
            logger.error(
                f"Resend health check: levelog.com status={status!r}, "
                f"expected 'verified'. Likely DNS / DKIM / SPF issue. "
                f"Renewal digest emails will fail."
            )
            return
        logger.info(
            f"📧 Resend health check OK: levelog.com verified "
            f"(region={levelog.get('region')!r})"
        )
    except Exception as e:
        # Never crash startup over an email config issue.
        logger.warning(
            f"Resend health check failed (non-fatal): "
            f"{type(e).__name__}: {e}"
        )


async def audit_log(action: str, user_id: str, resource_type: str, resource_id: str, details: dict = None):
    """Record an immutable audit entry for compliance-relevant mutations."""
    try:
        await db.audit_logs.insert_one({
            "action": action,
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")


# Mongo error codes for index conflicts:
#   85 — IndexOptionsConflict     (same key, different options like TTL duration)
#   86 — IndexKeySpecsConflict    (same name, different key spec)
# These two raise OperationFailure on subsequent create_index calls
# whenever a spec change ships. Without explicit handling, ANY future
# tweak to a TTL duration or compound-key shape bricks the deploy.
_INDEX_CONFLICT_CODES = {85, 86}


async def _ensure_index_resilient(collection, *, keys, name: str, **opts):
    """create_index that survives a spec change.

    On normal deploy: creates the index if it doesn't exist; no-op if
    an identical one already does (Mongo dedupes on (collection, keys,
    name, options)).
    On spec change: drops-and-recreates if the existing index has the
    same name/keys but different options (e.g. TTL duration changed).
    Any other failure is logged and swallowed — index creation should
    never block app startup (DOB syncs and UI work fine without TTLs).
    """
    from pymongo.errors import OperationFailure

    try:
        await collection.create_index(keys, name=name, **opts)
        return
    except OperationFailure as e:
        if getattr(e, "code", None) not in _INDEX_CONFLICT_CODES:
            logger.warning(
                f"create_index({collection.name}, {name}) failed (non-conflict): {e!r}"
            )
            return

    # Spec change: same name, different shape. Drop and recreate.
    logger.info(
        f"Recreating index {collection.name}.{name} due to spec change "
        f"(IndexOptions/KeySpecs conflict)."
    )
    try:
        await collection.drop_index(name)
    except OperationFailure as e:
        # If the existing index has a DIFFERENT name but same keys,
        # drop_index by name fails. List indexes, find the colliding
        # one by key match, drop that.
        logger.debug(f"drop_index({name}) failed; scanning by key match: {e!r}")
        async for idx in collection.list_indexes():
            if list(idx.get("key", {}).items()) == list(keys):
                old_name = idx.get("name")
                if old_name and old_name != "_id_":
                    try:
                        await collection.drop_index(old_name)
                        break
                    except Exception as _drop_err:
                        logger.warning(f"drop_index({old_name}) failed: {_drop_err!r}")

    try:
        await collection.create_index(keys, name=name, **opts)
    except Exception as e:
        logger.warning(
            f"create_index({collection.name}, {name}) post-recreate failed: {e!r}"
        )

# ==================== ID HELPER ====================

def to_query_id(id_str: str):
    if not id_str:
        return id_str
    try:
        return ObjectId(id_str)
    except Exception:
        return id_str

# ==================== COMPANY MODEL ====================

# MR.2: filing_reps data model. Each entry is a licensed individual
# at the GC who can sign DOB filings under their own license. The
# array supports the per-GC routing model in §14 of the permit-renewal
# v3 plan — the legal filer at MR.4+ is the licensed individual, NOT
# LeveLog. Distinct from the company's own gc_license_* top-level
# fields, which capture the company's GC license attribute (one per
# company); filing_reps captures the roster of authorized filers,
# potentially many, distinct trade scopes.
#
# Credential ciphertext storage (DOB NOW password) lands HERE in MR.6.
# The cloud only ever sees opaque base64 ciphertext + metadata; the
# encrypt path runs client-side in MR.10's onboarding UI using the
# operator's RSA-4096 public key, and only the worker's private key
# (~/.levelog/agent-keys/agent.key, 0400) can decrypt. Versioning is
# append-only: every new credential gets the next integer; the prior
# active credential gets `superseded_at` stamped at push time. The
# active credential is the entry with `superseded_at is None` and the
# highest version. Revoke == set superseded_at without a replacement.
class FilingRepCredential(BaseModel):
    """MR.6 — encrypted DOB NOW credential for a filing_rep.

    Cloud is intentionally blind to the cleartext: ciphertext is the
    output of MR.5's hybrid scheme (AES-256-GCM data key wrapped by
    RSA-OAEP-4096 against the operator's public key, base64-encoded).
    `public_key_fingerprint` lets the worker assert it's about to
    decrypt with a key whose public-half matches the one used to
    encrypt — a hard error otherwise (prevents silently passing
    ciphertext to the wrong worker laptop)."""
    version: int                                 # auto-incremented per filing_rep, 1-indexed
    encrypted_ciphertext: str                    # base64(RSA-OAEP-wrapped AES-GCM blob), opaque
    public_key_fingerprint: str                  # SHA-256 hex of the encrypting public key
    created_at: datetime
    superseded_at: Optional[datetime] = None     # set when newer version pushes OR explicit revoke


class FilingRep(BaseModel):
    id: str                                   # uuid4 hex, generated server-side on POST
    name: str                                 # licensed individual's full legal name
    license_class: str                        # see FILING_REP_LICENSE_CLASSES below
    license_number: str                       # DOB-issued license number
    license_type: Optional[str] = None        # free-text refinement when license_class == "Other Licensed Trade"
    email: EmailStr                           # routing address for MR.9 filing notifications
    is_primary: bool = False                  # exactly one per company; default routing for filings
    created_at: datetime
    updated_at: datetime
    # MR.6 — encrypted credential history (append-only). Default empty
    # so existing reads of pre-MR.6 documents don't ValidationError.
    credentials: List[FilingRepCredential] = []


FILING_REP_LICENSE_CLASSES = {
    "Class 1 Filing Rep",
    "Class 2 Filing Rep",
    "GC",
    "Plumber",
    "Electrician",
    "Master Fire Suppression Contractor",
    "Other Licensed Trade",
}


class FilingRepCreate(BaseModel):
    name: str
    license_class: str
    license_number: str
    license_type: Optional[str] = None
    email: EmailStr
    is_primary: bool = False


class FilingRepUpdate(BaseModel):
    """All fields optional — PATCH semantics."""
    name: Optional[str] = None
    license_class: Optional[str] = None
    license_number: Optional[str] = None
    license_type: Optional[str] = None
    email: Optional[EmailStr] = None
    is_primary: Optional[bool] = None


class FilingRepCredentialCreate(BaseModel):
    """MR.6 — payload for POST /filing-reps/{rep_id}/credentials.

    `version`, `created_at`, `superseded_at` are managed server-side.
    The client only ships the ciphertext + fingerprint of the public
    key it used to encrypt."""
    encrypted_ciphertext: str
    public_key_fingerprint: str


# ── MR.6: filing_jobs collection ─────────────────────────────────────
# Cloud-side state machine for queued/in-flight DOB NOW filings.
# Lives in its own collection (not embedded on permit_renewals)
# because audit_log grows unboundedly per job and per-renewal there
# can be multiple jobs over time (retries, manual re-runs, future MR
# scope where multiple sub-jobs land per renewal). Indexes keyed off
# permit_renewal_id give fast tenant scoping.

class FilingJobStatus(str, Enum):
    """State machine — append-only audit_log records every transition.

        queued ──► claimed ──► in_progress ──► filed ──► completed
                                          ──► failed
                  (any non-terminal) ──► cancelled

    Terminal: filed (DOB accepted but new expiry not yet stamped),
    completed (DOB stamped new expiry), failed (handler reported
    failure or retry cap hit), cancelled (operator killed it).
    Stale-claim watchdog reverts claimed/in_progress→queued and
    increments retry_count; >3 retries → failed."""
    QUEUED = "queued"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    FILED = "filed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Statuses from which the job CANNOT return to the queue and CANNOT
# be cancelled. The DELETE cancellation endpoint refuses with 409 if
# the job is in any of these.
FILING_JOB_TERMINAL_STATUSES = {
    FilingJobStatus.FILED.value,
    FilingJobStatus.COMPLETED.value,
    FilingJobStatus.FAILED.value,
    FilingJobStatus.CANCELLED.value,
}

# Statuses where the worker may still be operating on the job —
# stale-claim recovery looks at these, and cancellation must use the
# soft `cancellation_requested` flag instead of an immediate status
# flip (worker checks the flag before posting results).
FILING_JOB_INFLIGHT_STATUSES = {
    FilingJobStatus.CLAIMED.value,
    FilingJobStatus.IN_PROGRESS.value,
}

# Retry cap for stale-claim recovery before the watchdog gives up
# and marks the job failed. 3 matches the user-visible retry count.
FILING_JOB_RETRY_LIMIT = 3


class FilingJobEvent(BaseModel):
    """Single audit-log entry. Append-only — never modified after
    insert. The list on FilingJob.audit_log is the source of truth
    for the job's history; status / claimed_at / etc. are derived."""
    event_type: str                              # "queued" | "claimed" | "started" | "filed" | "completed" | "failed" | "cancelled" | "stale_claim_recovered" | "cancellation_requested" | "retry_limit_exceeded"
    timestamp: datetime
    actor: str                                   # worker_id, "system" (watchdog), or admin user_id
    detail: str                                  # human-readable
    metadata: Dict[str, Any] = {}                # structured extras (retry_count, dob_confirmation_number, ...)


class FilingJob(BaseModel):
    id: str
    permit_renewal_id: str
    company_id: str
    filing_rep_id: str                           # FilingRep.id from companies.filing_reps[]
    credential_version: int                      # snapshot of which credential was attached at enqueue
    pw2_field_map: Dict[str, Any]                # snapshot of MR.4 mapper output at enqueue
    status: str                                  # FilingJobStatus value (str-stored for query simplicity)
    claimed_by_worker_id: Optional[str] = None
    claimed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    dob_confirmation_number: Optional[str] = None
    retry_count: int = 0
    cancellation_requested: bool = False         # set by DELETE when job is in-flight
    audit_log: List[FilingJobEvent] = []
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False


# ── MR.6 helpers — pure functions, used by the endpoints below ──────

def filing_rep_active_credential(rep: dict) -> Optional[dict]:
    """Return the active credential entry on a filing_rep dict, or
    None if no credential is currently active. Active = highest
    `version` among entries where `superseded_at is None`."""
    if not isinstance(rep, dict):
        return None
    creds = rep.get("credentials") or []
    active = [c for c in creds if c.get("superseded_at") is None]
    if not active:
        return None
    return max(active, key=lambda c: c.get("version") or 0)


def _filing_job_audit_event(
    *,
    event_type: str,
    actor: str,
    detail: str,
    metadata: Optional[dict] = None,
) -> dict:
    """Construct an append-only audit-log entry. Never mutated after
    being $push-ed onto FilingJob.audit_log."""
    return {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc),
        "actor": actor,
        "detail": detail,
        "metadata": dict(metadata or {}),
    }


# Redis enqueue — soft import. `redis.asyncio` is optional at module-
# load (tests don't need it; the production deploy installs it via
# requirements.txt). Cloud-side LPUSH paired with the worker's BRPOP
# (dob_worker/lib/queue_client.py).
#
# Note on env-var freshness: REDIS_URL is read INSIDE _lpush_filing_queue
# on every call rather than cached at module load. This protects against
# a class of stale-config bugs where the backend process started before
# the operator set REDIS_URL on the Railway service — module-level
# os.environ.get(...) caching would persist the empty value forever
# until a redeploy. Reading per-call costs ~1us and lets a fresh REDIS_URL
# (e.g. after rotating Redis credentials during incident response) flow
# in without restarting the process. FILING_QUEUE_KEY is read the same
# way for the same reason; the value is unlikely to change at runtime
# but the pattern is consistent and trivial.
DEFAULT_FILING_QUEUE_KEY = "levelog:filing-queue"


async def _lpush_filing_queue(payload: dict):
    """LPUSH the job payload onto Redis. Fails-loud (raises) if
    REDIS_URL is unset OR redis package isn't installed — the enqueue
    endpoint catches and surfaces 503 to the caller. Tests patch this
    function directly so they don't need a live Redis.

    REDIS_URL is read fresh on every call (see module-level note)."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        raise RuntimeError("REDIS_URL not configured — cannot enqueue filing job")
    try:
        import redis.asyncio as redis_asyncio
    except ImportError as e:
        raise RuntimeError(f"redis package not installed: {e}") from e
    queue_key = os.environ.get("FILING_QUEUE_KEY", DEFAULT_FILING_QUEUE_KEY)
    client = redis_asyncio.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.lpush(queue_key, json.dumps(payload))
    finally:
        await client.close()


class Company(BaseModel):
    id: str
    name: str
    created_at: datetime
    created_by: Optional[str] = None  # Owner who created it
    # GC License fields
    gc_license_number: Optional[str] = None
    gc_business_name: Optional[str] = None
    gc_licensee_name: Optional[str] = None
    gc_license_status: Optional[str] = None
    gc_license_expiration: Optional[str] = None
    gc_insurance_records: Optional[list] = []
    gc_resolved: bool = False
    gc_last_verified: Optional[datetime] = None
    # MR.2: filing_reps roster (see FilingRep model above).
    filing_reps: List[FilingRep] = []

    # Permit-renewal license-class taxonomy (added 2026-04-26, step 2).
    # NONE: company doesn't hold any tracked license. HIC: NYC DCWP
    # Home Improvement Contractor (informational only — DCWP handles
    # their renewals, this app does not). GC_LICENSED: NYC DOB General
    # Contractor — the only class we run renewal logic for.
    license_class: Optional[str] = None              # "NONE" | "HIC" | "GC_LICENSED"
    license_class_source: Optional[str] = None       # "auto" | "manual_override"
    license_authority: Optional[str] = None          # "DOB" | "DCWP"
    gc_license_last_synced: Optional[datetime] = None
    hic_license_number: Optional[str] = None         # placeholder for future HIC track
    # Parallel field written by the local Docker worker (deferred to
    # step 14+) — DOB NOW Public Portal's authoritative view of this
    # GC's insurance, used for cross-check vs gc_insurance_records.
    dob_now_portal_insurance_snapshot: Optional[list] = None

class CompanyCreate(BaseModel):
    name: str
    gc_license_number: Optional[str] = None
    gc_business_name: Optional[str] = None
    gc_licensee_name: Optional[str] = None
    gc_license_status: Optional[str] = None
    gc_license_expiration: Optional[str] = None
    gc_resolved: bool = False
    
# ==================== MODELS ====================

def serialize_id(obj):
    """Convert MongoDB _id to string id and ensure datetime fields are UTC-marked"""
    if obj and '_id' in obj:
        obj['id'] = str(obj['_id'])
        del obj['_id']
    # Ensure all datetime fields are serialized with UTC indicator
    if obj:
        for key, value in obj.items():
            if isinstance(value, datetime):
                # MongoDB returns naive datetimes that are actually UTC.
                # Mark them explicitly so JS `new Date()` parses correctly.
                if value.tzinfo is None:
                    obj[key] = value.replace(tzinfo=timezone.utc)
    return obj

def serialize_list(items):
    """Convert list of MongoDB docs to serialized format"""
    return [serialize_id(item) for item in items]

async def paginated_query(
    collection,
    query: dict,
    sort_field: str = "created_at",
    sort_dir: int = -1,
    limit: int = 50,
    skip: int = 0,
    projection: dict = None,
):
    """
    Standard paginated query. Returns {items, total, limit, skip, has_more}.
    Use instead of .to_list(1000) on every list endpoint.
    """
    cursor = collection.find(query, projection).sort(sort_field, sort_dir).skip(skip).limit(limit)
    items = []
    async for doc in cursor:
        items.append(serialize_id(dict(doc)))
    total = await collection.count_documents(query)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }

def serialize_sync_record(record):
    """Convert MongoDB record to sync format with timestamps in milliseconds"""
    if '_id' in record:
        record['id'] = str(record['_id'])
        del record['_id']
    
    # Convert datetime fields to milliseconds
    if 'created_at' in record and isinstance(record['created_at'], datetime):
        record['created_at'] = int(record['created_at'].timestamp() * 1000)
    if 'updated_at' in record and isinstance(record['updated_at'], datetime):
        record['updated_at'] = int(record['updated_at'].timestamp() * 1000)
    if 'check_in_time' in record and isinstance(record['check_in_time'], datetime):
        record['check_in_time'] = int(record['check_in_time'].timestamp() * 1000)
    if 'check_out_time' in record and isinstance(record['check_out_time'], datetime):
        record['check_out_time'] = int(record['check_out_time'].timestamp() * 1000)
    if 'timestamp' in record and isinstance(record['timestamp'], datetime):
        record['timestamp'] = int(record['timestamp'].timestamp() * 1000)
    
    return record

def get_today_range_est():
    """Get today's start/end in UTC, aligned to Eastern Time midnight.
    Uses zoneinfo to automatically handle EST (-5) vs EDT (-4)."""
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    now_eastern = datetime.now(eastern)
    today_midnight_eastern = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_midnight_eastern.astimezone(timezone.utc)
    today_end_utc = today_start_utc + timedelta(hours=24)
    return today_start_utc, today_end_utc

VALID_PROJECT_CLASSES = {"regular", "major_a", "major_b"}


# ── MR.5+ — third instance of "Pydantic default protects reads but
# not writes" defensive lift ──────────────────────────────────────
#
# Pattern history:
#   1. backend/requirements.txt missing redis package — production
#      500 because the lazy import path fired only in production,
#      tests mocked the helper.
#   2. companies.filing_reps[].credentials field default {} did not
#      survive Mongo writes on legacy filing-rep docs that predated
#      the field. MR.10 fixed via _lift_credentials_field +
#      backend/scripts/migrate_filing_reps_credentials_init.py.
#   3. THIS — projects.gates (and 5 sibling list fields) default
#      protected reads via Pydantic's `[]` default, but
#      ProjectCreate.gates: Optional[List[...]] = None was carried
#      through model_dump() into the Mongo insert as null, then
#      ProjectResponse(**project_dict) rejected the null on response
#      construction (its type is non-Optional List, default = []).
#
# Same shape, same fix shape:
#   • forward-init in the write path
#   • defensive lift on the read path
#   • backfill migration for already-stranded legacy docs
#
# Future MR-N+ — CI check that scans Pydantic models for fields with
# defaults and verifies each appears explicitly in the corresponding
# insert dict. ~50 lines of AST walk; would have caught all three.

_PROJECT_LIST_DEFAULT_FIELDS = (
    "gates",
    "report_email_list",
    "site_device_subfolders",
    "trade_assignments",
    "required_logbooks",
    "nfc_tags",
)


def _lift_project_list_defaults(project: dict) -> dict:
    """Coerce list-typed fields from None → []. Idempotent.

    Mutates the input dict in place AND returns it (for fluent
    use at call sites). Two transformations, both safe:
      1. If a list field is present with value None → coerce to [].
         (This is the case Pydantic rejects on ProjectResponse
         construction, the production-500 trigger.)
      2. If a list field is missing entirely → set to [].
         (Defensive — keeps inserts shape-stable, makes it cheaper
         to reason about Mongo documents downstream.)

    Real-list values (including non-empty lists) pass through
    untouched. Idempotent: running twice on the same doc has no
    effect after the first call.
    """
    if not project:
        return project
    for fld in _PROJECT_LIST_DEFAULT_FIELDS:
        if project.get(fld) is None:  # matches both None-valued AND missing
            project[fld] = []
    return project


def classify_project(stories, footprint_sqft, full_demo, demo_stories, building_height=None):
    """NYC Building Code §3310 classification.
    Major Building = 10+ stories OR 125+ ft OR 100,000+ sqft footprint.
    SSM required = 15+ stories OR 200+ ft OR footprint > 100,000 sqft.
    SSC can substitute for SSM if < 15 stories AND < 200 ft AND <= 100,000 sqft."""
    is_major = False
    needs_ssm = False

    # Check stories
    if stories and stories >= 15:
        is_major = True
        needs_ssm = True
    elif stories and stories >= 10:
        is_major = True

    # Check height
    if building_height and building_height >= 200:
        is_major = True
        needs_ssm = True
    elif building_height and building_height >= 125:
        is_major = True

    # Check footprint
    if footprint_sqft and footprint_sqft >= 100000:
        is_major = True
        needs_ssm = True

    # Full demolition of major building
    if full_demo and demo_stories and demo_stories >= 15:
        is_major = True
        needs_ssm = True
    elif full_demo and demo_stories and demo_stories >= 10:
        is_major = True

    if needs_ssm:
        return "major_b"
    if is_major:
        return "major_a"
    return "regular"

def get_required_logbooks(project_class, project=None):
    base = ["daily_jobsite", "preshift_signin", "toolbox_talk", "subcontractor_orientation", "osha_log"]
    if project_class in ("major_a", "major_b"):
        base.append("ssc_daily_safety_log")
        base.append("hot_work")
        if project:
            if project.get("building_stories") and project["building_stories"] >= 5:
                base.append("concrete_operations")
            if project.get("has_full_demolition") or project.get("adjacent_to_occupied"):
                base.append("excavation_monitoring")
    if project and project.get("scaffold_erected"):
        base.append("scaffold_maintenance")
    return base

def normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format."""
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    return f"+{digits}"

def format_phone(phone: str) -> str:
    """Format a 10-digit phone number as XXX-XXX-XXXX"""
    digits = ''.join(c for c in (phone or '') if c.isdigit())
    if len(digits) == 11 and digits[0] == '1':
        digits = digits[1:]  # strip leading 1
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phone or ""
 
# ==================== NYC BIN RESOLUTION ====================
 
def _is_placeholder_bin(bin_str: str) -> bool:
    """NYC DOB uses BINs of the form X000000 (e.g. 2000000 for the Bronx)
    as placeholders when a building has no real BIN yet. Every DOB API
    returns zero records against these. Treat them as "no BIN" rather
    than a real lookup hit."""
    if not bin_str or not str(bin_str).isdigit() or len(str(bin_str)) != 7:
        return True
    # First digit is borough code (1–5); remaining six must not all be 0
    return str(bin_str)[1:] == "000000"


async def fetch_nyc_bin_from_address(address: str) -> dict:
    """
    Query NYC GeoSearch to resolve an address into a BIN + BBL and a
    canonical normalized address string. Returns:
        {
          "nyc_bin": str|None,          # 7-digit BIN; None if placeholder or missing
          "bbl": str|None,              # 10-digit BBL; renamed from nyc_bbl in step 9.1
          "track_dob_status": bool,     # True only if we got a REAL BIN
          "normalized_address": str|None,
        }

    Field-name note: the BBL key was renamed from `nyc_bbl` to `bbl`
    on 2026-04-27 (step 9.1). The `nyc_` prefix was redundant — BBL is
    by definition NYC. The function name itself is misleading (it
    fetches BOTH BIN and BBL); a follow-up cleanup will rename to
    `fetch_nyc_dob_ids_from_address`. Tracked but not blocking step 9.1.

    Placeholder BINs (X000000) are REJECTED — stored as None — so the
    caller falls back to address-based DOB queries and the diagnostic
    UI correctly reports "No BIN on file" instead of "BIN 2000000 with
    zero records".

    The normalized_address (GeoSearch's canonical `label`, e.g.
    "852 EAST 176 STREET, Bronx, NY, USA") gives the caller a clean
    address string to store, so downstream Socrata LIKE queries match
    DOB's canonical street forms like "EAST 176 STREET" instead of
    failing on user shorthand like "E 176".
    """
    result = {
        "nyc_bin": None,
        "bbl": None,
        "track_dob_status": False,
        "normalized_address": None,
    }
    if not address or len(address.strip()) < 5:
        return result

    endpoints = [
        "https://geosearch.planninglabs.nyc/v2/search",
        "https://geosearch.planning.nyc.gov/v2/search",
    ]

    for endpoint in endpoints:
        try:
            async with ServerHttpClient(timeout=10.0) as http_client:
                resp = await http_client.get(
                    endpoint,
                    params={"text": address.strip(), "size": "1"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"GeoSearch {endpoint} returned {resp.status_code} for '{address}'"
                    )
                    continue

                data = resp.json()
                features = data.get("features", [])
                if not features:
                    logger.info(f"GeoSearch: no features for '{address}' via {endpoint}")
                    continue

                props = features[0].get("properties", {})
                pad_bin = (
                    props.get("pad_bin", "")
                    or props.get("addendum", {}).get("pad", {}).get("bin", "")
                )
                pad_bbl = (
                    props.get("pad_bbl", "")
                    or props.get("addendum", {}).get("pad", {}).get("bbl", "")
                )
                label = (props.get("label") or "").strip() or None

                # Canonical address — always capture it. A clean street
                # name unlocks the address-based DOB query fallback even
                # when the BIN is a placeholder or missing.
                if label:
                    result["normalized_address"] = label

                # Validate BIN: 7 digits, numeric, AND not a placeholder.
                if pad_bin and not _is_placeholder_bin(str(pad_bin)):
                    result["nyc_bin"] = str(pad_bin)
                    result["track_dob_status"] = True
                elif pad_bin:
                    logger.info(
                        f"GeoSearch returned placeholder BIN {pad_bin} for "
                        f"'{address}' — treating as no BIN so address-based "
                        f"DOB lookups are used instead."
                    )

                if pad_bbl:
                    result["bbl"] = str(pad_bbl)

                logger.info(
                    f"GeoSearch resolved '{address}' -> BIN={result['nyc_bin']} "
                    f"BBL={result['bbl']} label={label!r} via {endpoint}"
                )
                return result

        except Exception as e:
            logger.warning(f"GeoSearch error for '{address}' via {endpoint}: {e}")
            continue

    logger.error(f"All GeoSearch endpoints failed for '{address}'")
    return result
 
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "worker"
    company_name: Optional[str] = None
    company_id: Optional[str] = None
    phone: Optional[str] = None
    trade: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_name: Optional[str] = None
    company_id: Optional[str] = None
    phone: Optional[str] = None
    trade: Optional[str] = None
    assigned_projects: List[str] = []
    created_at: Optional[datetime] = None

class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None

class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# Project Models
# Default construction trade list used by the NFC check-in dropdown
# as a template when an admin opens the trade-assignments editor on a
# brand-new project (the frontend 'Load suggested trades' shortcut
# seeds pairs with this list + empty company field). Not used as a
# runtime fallback — the check-in page shows only the admin-configured
# {trade, company} pairs. Admins assign each trade to the specific
# subcontractor working on that trade for that project, so workers
# check in by picking their combined trade+company entry.
DEFAULT_TRADES: List[str] = [
    "General Labor",
    "Carpenter",
    "Electrician",
    "Plumber",
    "HVAC / Mechanical",
    "Ironworker",
    "Mason",
    "Concrete / Cement",
    "Roofer",
    "Painter",
    "Sheet Metal",
    "Operating Engineer",
    "Demolition",
    "Fire Protection / Sprinkler",
    "Drywall / Plasterer",
    "Glazier",
    "Insulator",
    "Foreman / Supervisor",
    "Surveyor",
    "Safety",
]


class TradeAssignment(BaseModel):
    """One subcontractor assignment on a project.
    trade: the construction trade (e.g. 'HVAC / Mechanical')
    company: the sub doing that trade on this project (e.g. 'Air Star')
    """
    trade: str
    company: str


class ProjectGate(BaseModel):
    """Per-project NFC gate. One row per mounted tag; workers tap the
    tag to open /checkin/{project_id}/{gate_id}. See card_audit module.
    """
    gate_id: str
    label: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class ProjectCreate(BaseModel):
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"
    # NYC DOB Classification (§3310)
    building_stories: Optional[int] = None
    building_height: Optional[int] = None  # feet
    footprint_sqft: Optional[int] = None  # square feet
    has_full_demolition: bool = False
    demolition_stories: Optional[int] = None
    project_class: Optional[str] = None  # admin override
    ssp_number: Optional[str] = None
    ssp_filing_date: Optional[str] = None
    ssp_expiration_date: Optional[str] = None
    # Card audit / NFC gate check-in config. See backend/card_audit.py.
    lat: Optional[float] = None
    lng: Optional[float] = None
    geofence_radius_m: Optional[int] = 150
    gates: Optional[List[ProjectGate]] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None
    report_email_list: Optional[List[str]] = None
    report_send_time: Optional[str] = None
    building_stories: Optional[int] = None
    building_height: Optional[int] = None
    footprint_sqft: Optional[int] = None
    has_full_demolition: Optional[bool] = None
    demolition_stories: Optional[int] = None
    project_class: Optional[str] = None
    ssp_number: Optional[str] = None
    ssp_filing_date: Optional[str] = None
    ssp_expiration_date: Optional[str] = None
    # Per-project subcontractor roster. Each entry pairs a trade with
    # the specific company doing that trade on this project. Workers
    # pick one combined entry from the dropdown at check-in time and
    # both their `trade` and `company` fields get populated from it.
    # Strict: the check-in endpoint rejects submissions whose
    # (trade, company) pair isn't in this list.
    trade_assignments: Optional[List[TradeAssignment]] = None
    # Card audit / NFC gate check-in config. See backend/card_audit.py.
    lat: Optional[float] = None
    lng: Optional[float] = None
    geofence_radius_m: Optional[int] = None
    gates: Optional[List[ProjectGate]] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    nfc_tags: List[Dict] = []
    dropbox_folder: Optional[str] = None
    dropbox_enabled: bool = False
    created_at: Optional[datetime] = None
    nyc_bin: Optional[str] = None
    # BBL field — 10-digit Borough-Block-Lot. Renamed from nyc_bbl
    # 2026-04-27 (step 9.1) per the §12 BIN-matcher spec. The
    # `nyc_` prefix was redundant (BBL is by definition NYC) and
    # produced naming inconsistency with §12 architecture refs.
    # During the transition window the legacy `nyc_bbl` field may
    # still be present on older Mongo docs; reads go through
    # _project_bbl() helper which prefers `bbl` and falls back to
    # `nyc_bbl`. Cleanup commit drops the legacy field after deploy.
    bbl: Optional[str] = None
    # BBL provenance metadata. Drives the §12 BIN-matcher tier-1
    # lookup. The legacy field was populated only at project creation
    # via fetch_nyc_bin_from_address; the step 9.1 migration stamps
    # that legacy path as 'address_lookup_at_creation' and lets future
    # admin / PLUTO-lookup edits track their source.
    bbl_source: Optional[str] = None  # "address_lookup_at_creation" | "pluto_lookup" | "manual_entry" | "geosupport" | "user_corrected"
    bbl_last_synced: Optional[datetime] = None
    track_dob_status: bool = False
    report_email_list: List[str] = []
    report_send_time: str = "18:00"
    project_class: Optional[str] = "regular"
    suggested_class: Optional[str] = None
    building_stories: Optional[int] = None
    building_height: Optional[int] = None
    footprint_sqft: Optional[int] = None
    has_full_demolition: bool = False
    demolition_stories: Optional[int] = None
    required_logbooks: List[str] = []
    ssp_number: Optional[str] = None
    ssp_filing_date: Optional[str] = None
    ssp_expiration_date: Optional[str] = None
    # Site-device visibility allowlist: top-level subfolder names
    # (relative to dropbox_folder_path) that users with role=site_device
    # are allowed to see. Empty list = site devices see nothing.
    # Admins/CPs always see the full folder regardless.
    site_device_subfolders: List[str] = []
    # Per-project subcontractor roster for the NFC check-in dropdown.
    # Each item is {trade, company}. Workers pick one combined entry.
    trade_assignments: List[Dict[str, str]] = []
    # Card audit / NFC gate check-in config. See backend/card_audit.py.
    lat: Optional[float] = None
    lng: Optional[float] = None
    geofence_radius_m: int = 150
    gates: List[Dict[str, Any]] = []

# ==================== CERTIFICATION MODELS ====================

class CertificationType(str, Enum):
    OSHA_10 = "OSHA_10"
    OSHA_30 = "OSHA_30"
    SST_FULL = "SST_FULL"
    SST_LIMITED = "SST_LIMITED"
    SST_SUPERVISOR = "SST_SUPERVISOR"
    FDNY_COF = "FDNY_COF"
    SCAFFOLD = "SCAFFOLD"
    RIGGING = "RIGGING"
    WELDING = "WELDING"
    ASBESTOS = "ASBESTOS"
    LEAD = "LEAD"
    CONFINED_SPACE = "CONFINED_SPACE"
    OTHER = "OTHER"

class WorkerCertification(BaseModel):
    type: str
    card_number: Optional[str] = None
    issue_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    verified: bool = False
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    card_image_url: Optional[str] = None
    ocr_confidence: Optional[float] = None
    notes: Optional[str] = None

# ==================== CERTIFICATION GATE LOGIC ====================

def validate_worker_certifications(worker: dict, project: dict = None) -> dict:
    """
    Validate worker certs against NYC LL196.
    Returns {"cleared": bool, "blocks": [...], "warnings": [...]}
    """
    certs = worker.get("certifications", [])
    blocks = []
    warnings = []
    now = datetime.now(timezone.utc)

    cert_types = {}
    for c in certs:
        ctype = c.get("type", "")
        if ctype not in cert_types:
            cert_types[ctype] = []
        cert_types[ctype].append(c)

    # Check 1: OSHA baseline. NYC SST training requires OSHA-10 as a
    # prerequisite, so any SST cert on file satisfies the OSHA baseline
    # too — we don't force workers to upload two separate photos at
    # NFC check-in just to prove both.
    sst_type_names = {"SST_FULL", "SST_LIMITED", "SST_SUPERVISOR"}
    has_osha = bool(
        cert_types.get("OSHA_10")
        or cert_types.get("OSHA_30")
        or any(cert_types.get(t) for t in sst_type_names)
    )
    if not has_osha:
        blocks.append({
            "type": "MISSING_OSHA",
            "detail": "No OSHA-10 or OSHA-30 card on file. Required for all NYC job sites.",
            "remediation": "Worker must present valid OSHA card to site manager."
        })

    # Check 2: SST card (LL196)
    sst_types = {"SST_FULL", "SST_LIMITED", "SST_SUPERVISOR"}
    sst_certs = []
    for st in sst_types:
        sst_certs.extend(cert_types.get(st, []))

    has_valid_sst = False
    expired_sst = None
    for c in sst_certs:
        exp = c.get("expiration_date")
        if exp is None:
            has_valid_sst = True
            warnings.append({
                "type": "SST_NO_EXPIRY",
                "detail": f"SST card ({c.get('type')}) has no expiration date recorded."
            })
        elif isinstance(exp, str):
            try:
                exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                if exp_dt > now:
                    has_valid_sst = True
                else:
                    expired_sst = exp_dt
            except (ValueError, TypeError):
                has_valid_sst = True
        elif isinstance(exp, datetime):
            # Mongo can return naive datetimes; coerce to UTC for safe compare.
            exp_aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=timezone.utc)
            if exp_aware > now:
                has_valid_sst = True
            else:
                expired_sst = exp_aware

    if not has_valid_sst:
        if expired_sst:
            # Expired is still a hard block — it's a documented event, not
            # an OCR gap. Keep LL196 enforcement strict here.
            blocks.append({
                "type": "EXPIRED_SST",
                "detail": f"SST card expired {expired_sst.strftime('%Y-%m-%d')}. Cannot enter site per NYC LL196.",
                "remediation": "Worker must complete SST renewal training and present updated card."
            })
        elif not sst_certs:
            # Downgrade to warning: first-time NFC workers upload a single
            # card photo. If OCR read it as OSHA (no expiration) we don't
            # have SST evidence yet, but we also don't want to reject the
            # worker at the gate. CP/admin will follow up in cert review.
            warnings.append({
                "type": "MISSING_SST",
                "detail": "No NYC SST card on file yet. Worker can check in, but CP should verify SST card in next review.",
                "cert_type": "SST"
            })

    # Check 3: 30-day expiration warnings
    thirty_days = now + timedelta(days=30)
    for c in certs:
        exp = c.get("expiration_date")
        if exp:
            exp_dt = exp if isinstance(exp, datetime) else None
            if exp_dt is None and isinstance(exp, str):
                try:
                    exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    continue
            # Coerce naive datetimes to UTC so the comparison below works.
            if exp_dt and exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt and now < exp_dt <= thirty_days:
                warnings.append({
                    "type": "CERT_EXPIRING_SOON",
                    "detail": f"{c.get('type')} expires {exp_dt.strftime('%Y-%m-%d')} (within 30 days).",
                    "cert_type": c.get("type")
                })

    return {"cleared": len(blocks) == 0, "blocks": blocks, "warnings": warnings}


async def create_cert_block_alert(worker: dict, project: dict, blocks: list):
    """Create compliance alert when worker is blocked at gate."""
    now = datetime.now(timezone.utc)
    alert = {
        "alert_type": "CERT_BLOCK",
        "project_id": str(project.get("_id", project.get("id", ""))),
        "project_name": project.get("name", ""),
        "company_id": project.get("company_id"),
        "worker_id": str(worker.get("_id", worker.get("id", ""))),
        "worker_name": worker.get("name", ""),
        "worker_company": worker.get("company", ""),
        "blocks": blocks,
        "resolved": False,
        "created_at": now,
        "updated_at": now,
    }
    await db.compliance_alerts.insert_one(alert)
    logger.warning(
        f"🚫 CERT BLOCK: {worker.get('name')} blocked from {project.get('name')} — "
        f"{', '.join(b['type'] for b in blocks)}"
    )


class WorkerCreate(BaseModel):
    name: str
    phone: str
    trade: str
    company: str
    device_id: Optional[str] = None

class WorkerResponse(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    trade: Optional[str] = None
    company: str
    company_id: Optional[str] = None
    status: str = "active"
    osha_number: Optional[str] = None
    osha_data: Optional[Dict] = None
    osha_card_image: Optional[str] = None
    safety_orientations: List[Dict] = []
    certifications: List[Dict] = []
    signature: Optional[Dict | str] = None
    created_at: Optional[datetime] = None

# Check-In Models
class CheckInCreate(BaseModel):
    worker_id: str
    project_id: Optional[str] = None
    tag_id: Optional[str] = None
    phone: Optional[str] = None

class CheckInResponse(BaseModel):
    id: str
    worker_id: str
    worker_name: str
    project_id: str
    project_name: str
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    status: str = "checked_in"
    timestamp: datetime

# NFC Tag Models
class NfcTagCreate(BaseModel):
    tag_id: str
    location_description: str

class NfcTagResponse(BaseModel):
    tag_id: str
    project_id: str
    project_name: str
    location_description: str
    status: str = "active"
    created_at: Optional[datetime] = None

class NfcTagInfo(BaseModel):
    tag_id: str
    project_id: str
    project_name: str
    location_description: str
    company_name: Optional[str] = None

# Public Check-In Models
class PublicCheckInSubmit(BaseModel):
    project_id: str
    tag_id: str
    name: str
    phone: str
    company: str
    trade: str
    
class PublicWorkerRegister(BaseModel):
    project_id: str
    tag_id: str
    company: str  # selected from dropdown
    osha_card_image: str  # base64 image data
    safety_orientation: Dict  # {items checked, timestamp}

class OSHAUploadResponse(BaseModel):
    name: Optional[str] = None
    sst_number: Optional[str] = None
    issued: Optional[str] = None
    expiration: Optional[str] = None
    raw_text: Optional[str] = None
    
# Subcontractor Models
class SubcontractorCreate(BaseModel):
    company_name: str
    contact_name: str
    email: EmailStr
    phone: Optional[str] = None
    trade: Optional[str] = None
    password: str

class SubcontractorResponse(BaseModel):
    id: str
    company_name: str
    contact_name: str
    email: str
    phone: Optional[str] = None
    trade: Optional[str] = None
    workers_count: int = 0
    assigned_projects: List[str] = []
    created_at: Optional[datetime] = None

# Daily Log Models
class SafetyCheckItem(BaseModel):
    item: str
    status: str
    checked_by: Optional[str] = None
    checked_at: Optional[str] = None

class SignatureData(BaseModel):
    signer_name: str
    signed_at: str
    paths: Optional[List[List[Dict]]] = None

class DailyLogCreate(BaseModel):
    project_id: str
    date: str
    weather: Optional[str] = None
    notes: Optional[str] = None
    worker_count: int = 0
    subcontractor_cards: Optional[List[Dict]] = None
    safety_checklist: Optional[Dict[str, Dict]] = None
    corrective_actions: Optional[str] = None
    corrective_actions_na: bool = False
    corrective_actions_audit: Optional[Dict] = None
    incident_log: Optional[str] = None
    incident_log_na: bool = False
    incident_log_audit: Optional[Dict] = None
    superintendent_signature: Optional[Dict] = None
    competent_person_signature: Optional[Dict] = None
    work_performed: Optional[str] = None
    weather_temp: Optional[str] = None
    weather_wind: Optional[str] = None
    weather_condition: Optional[str] = None
    is_locked: bool = False
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None

class DailyLogResponse(BaseModel):
    id: str
    project_id: str
    date: str
    weather: Optional[str] = None
    notes: Optional[str] = None
    worker_count: int = 0
    subcontractor_cards: Optional[List[Dict]] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    safety_checklist: Optional[Dict[str, Dict]] = None
    corrective_actions: Optional[str] = None
    corrective_actions_na: bool = False
    corrective_actions_audit: Optional[Dict] = None
    incident_log: Optional[str] = None
    incident_log_na: bool = False
    incident_log_audit: Optional[Dict] = None
    superintendent_signature: Optional[Dict] = None
    competent_person_signature: Optional[Dict] = None
    work_performed: Optional[str] = None
    weather_temp: Optional[str] = None
    weather_wind: Optional[str] = None
    weather_condition: Optional[str] = None
    is_locked: bool = False
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None

# ==================== DOB COMPLIANCE MODELS ====================
 
class DOBLogResponse(BaseModel):
    id: str
    project_id: str
    company_id: Optional[str] = ""
    nyc_bin: Optional[str] = ""
    record_type: str
    raw_dob_id: str
    ai_summary: Optional[str] = ""
    severity: Optional[str] = "Medium"
    next_action: Optional[str] = ""
    detected_at: datetime
    # Phase 2: Raw structured fields
    permit_type: Optional[str] = None
    permit_subtype: Optional[str] = None
    permit_status: Optional[str] = None
    expiration_date: Optional[str] = None
    issuance_date: Optional[str] = None
    filing_date: Optional[str] = None
    job_number: Optional[str] = None
    job_type: Optional[str] = None
    work_type: Optional[str] = None
    # Permit-renewal classification (populated for record_type=="permit"):
    # filing_system in {"DOB_NOW","BIS"} — drives auto-extension rules.
    # permit_class in {"standard","sidewalk_shed","fence","bldrs_pavement"} —
    # drives strategy (e.g. LL48 sheds use a parallel 90-day manual track).
    filing_system: Optional[str] = None
    permit_class: Optional[str] = None
    violation_type: Optional[str] = None
    violation_number: Optional[str] = None
    violation_category: Optional[str] = None
    violation_date: Optional[str] = None
    penalty_amount: Optional[str] = None
    respondent: Optional[str] = None
    disposition_date: Optional[str] = None
    disposition_comments: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    dob_link: Optional[str] = None
    # Complaint fields
    complaint_number: Optional[str] = None
    complaint_type: Optional[str] = None
    complaint_status: Optional[str] = None
    complaint_date: Optional[str] = None
    closed_date: Optional[str] = None
    incident_address: Optional[str] = None
    disposition_code: Optional[str] = None
    risk_level: Optional[str] = None
    disposition_label: Optional[str] = None
    category_label: Optional[str] = None
    complaint_source: Optional[str] = None
    inspector_unit: Optional[str] = None
    what_to_expect: Optional[str] = None
    linked_violation_id: Optional[str] = None
    linked_complaint_ids: Optional[list] = None
    # Sprint 2 fields
    violation_subtype: Optional[str] = None
    resolution_state: Optional[str] = None
    # Sprint 5 fields
    inspection_date: Optional[str] = None
    inspection_type: Optional[str] = None
    inspection_result: Optional[str] = None
    inspection_result_description: Optional[str] = None
    linked_job_number: Optional[str] = None
    # Sprint 6 fields
    notice_type: Optional[str] = None
    compliance_deadline: Optional[str] = None


class DOBConfigUpdate(BaseModel):
    nyc_bin: Optional[str] = None
    # bbl renamed from nyc_bbl 2026-04-27 (step 9.1). The Pydantic
    # field accepts either name during the transition window via
    # populate_by_name + alias. Forward callers should use `bbl`.
    bbl: Optional[str] = Field(default=None, alias="nyc_bbl")
    track_dob_status: Optional[bool] = None
    gc_legal_name: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")
 
# Site Device Models
class SiteDeviceCreate(BaseModel):
    project_id: str
    device_name: Optional[str] = "Site Device"
    username: str
    password: str

class SiteDeviceResponse(BaseModel):
    id: str
    project_id: str
    project_name: str
    device_name: str
    username: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

class SiteDeviceLogin(BaseModel):
    username: str
    password: str

# ==================== CHECKLIST MODELS ====================

class ChecklistItemCreate(BaseModel):
    text: str
    order: int = 0

class ChecklistItemResponse(BaseModel):
    id: str
    text: str
    order: int = 0

class ChecklistCreate(BaseModel):
    title: str
    description: Optional[str] = None
    items: List[Dict[str, Any]]

class ChecklistResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    items: List[Dict[str, Any]]
    company_id: str
    created_by: str
    created_by_name: Optional[str] = None
    created_at: datetime

class ChecklistAssignmentCreate(BaseModel):
    checklist_id: str
    project_ids: List[str]
    user_ids: List[str]

class ChecklistAssignmentResponse(BaseModel):
    id: str
    checklist_id: str
    checklist_title: str
    project_id: str
    project_name: str
    assigned_users: List[Dict[str, str]]
    created_at: datetime
    completion_stats: Optional[Dict[str, int]] = None

class ChecklistCompletionUpdate(BaseModel):
    item_completions: Dict[str, Dict[str, Any]]

class ChecklistCompletionResponse(BaseModel):
    id: str
    assignment_id: str
    user_id: str
    user_name: str
    item_completions: Dict[str, Dict[str, Any]]
    progress: Dict[str, int]
    last_updated: datetime

# ==================== LOGBOOK MODELS ====================

class LogbookCreate(BaseModel):
    project_id: str
    log_type: str  # scaffold_maintenance, toolbox_talk, preshift_signin, osha_log, daily_jobsite
    date: str  # YYYY-MM-DD
    data: Dict[str, Any]  # flexible per log type
    cp_signature: Optional[Dict] = None
    cp_name: Optional[str] = None
    status: str = "draft"  # draft, submitted

class LogbookUpdate(BaseModel):
    data: Optional[Dict[str, Any]] = None
    cp_signature: Optional[Dict] = None
    cp_name: Optional[str] = None
    status: Optional[str] = None

class CPProfileUpdate(BaseModel):
    cp_name: Optional[str] = None
    cp_signature: Optional[Dict] = None  # {paths, signed_at}
    cp_title: Optional[str] = None

# ==================== SAFETY STAFF MODELS ====================

class SafetyStaffCreate(BaseModel):
    project_id: str
    role: str  # "ssc" (Site Safety Coordinator) or "ssm" (Site Safety Manager)
    name: str
    license_number: str  # S-56 for SSC, S-57 for SSM
    license_expiration: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class SafetyStaffResponse(BaseModel):
    id: str
    project_id: str
    role: str
    name: str
    license_number: str
    license_expiration: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    company_id: Optional[str] = None
    created_at: Optional[datetime] = None
    is_deleted: bool = False

# ==================== LOGBOOK TYPE REGISTRY ====================

LOGBOOK_TYPE_REGISTRY = [
    {
        "key": "daily_jobsite",
        "label": "Daily Jobsite Log",
        "subtitle": "NYC DOB 3301-02",
        "frequency": "daily",
        "icon": "Building2",
        "color": "#ef4444",
        "dob_reference": "§3301.2",
        "applicable_classes": ["regular", "major_a", "major_b"],
    },
    {
        "key": "preshift_signin",
        "label": "Pre-Shift Safety Meeting",
        "subtitle": "Daily sign-in with all workers",
        "frequency": "daily",
        "icon": "Users",
        "color": "#4ade80",
        "dob_reference": "OSHA 1926.21",
        "applicable_classes": ["regular", "major_a", "major_b"],
    },
    {
        "key": "toolbox_talk",
        "label": "Tool Box Talk",
        "subtitle": "OSHA — Weekly per company",
        "frequency": "weekly",
        "icon": "BookOpen",
        "color": "#3b82f6",
        "dob_reference": "OSHA 1926.21",
        "applicable_classes": ["regular", "major_a", "major_b"],
    },
    {
        "key": "subcontractor_orientation",
        "label": "Subcontractor Safety Orientation",
        "subtitle": "First-time workers only",
        "frequency": "as_needed",
        "icon": "ShieldCheck",
        "color": "#8b5cf6",
        "dob_reference": "LL196",
        "applicable_classes": ["regular", "major_a", "major_b"],
    },
    {
        "key": "osha_log",
        "label": "OSHA Log Book",
        "subtitle": "Worker certifications register",
        "frequency": "daily",
        "icon": "ClipboardList",
        "color": "#06b6d4",
        "dob_reference": "OSHA 1926",
        "applicable_classes": ["regular", "major_a", "major_b"],
    },
    {
        "key": "scaffold_maintenance",
        "label": "Scaffold Maintenance Log",
        "subtitle": "NYC DOB — Daily while scaffold is up",
        "frequency": "daily",
        "icon": "HardHat",
        "color": "#f59e0b",
        "dob_reference": "§3314",
        "applicable_classes": ["regular", "major_a", "major_b"],
        "conditional": "scaffold_erected",
    },
    {
        "key": "ssc_daily_safety_log",
        "label": "SSC/SSM Daily Safety Log",
        "subtitle": "Site Safety Coordinator/Manager daily report",
        "frequency": "daily",
        "icon": "ShieldCheck",
        "color": "#ec4899",
        "dob_reference": "§3310.4/§3310.5",
        "applicable_classes": ["major_a", "major_b"],
    },
    {
        "key": "hot_work",
        "label": "Hot Work Permit Log",
        "subtitle": "Welding, cutting, brazing operations",
        "frequency": "as_needed",
        "icon": "Flame",
        "color": "#f97316",
        "dob_reference": "FC §3504",
        "applicable_classes": ["major_a", "major_b"],
    },
    {
        "key": "concrete_operations",
        "label": "Concrete Operations Log",
        "subtitle": "Slump tests, formwork inspection",
        "frequency": "daily",
        "icon": "Layers",
        "color": "#64748b",
        "dob_reference": "§3310.4",
        "applicable_classes": ["major_a", "major_b"],
        "conditional": "building_stories_gte_5",
    },
    {
        "key": "crane_operations",
        "label": "Crane Operations Log",
        "subtitle": "Pre-operation inspection & load log",
        "frequency": "daily",
        "icon": "Crane",
        "color": "#eab308",
        "dob_reference": "§3319",
        "applicable_classes": ["major_a", "major_b"],
        "conditional": "has_crane_permit",
    },
    {
        "key": "excavation_monitoring",
        "label": "Excavation Monitoring Log",
        "subtitle": "Adjacent building monitoring & vibration",
        "frequency": "daily",
        "icon": "Mountain",
        "color": "#a855f7",
        "dob_reference": "§3304",
        "applicable_classes": ["major_a", "major_b"],
        "conditional": "has_excavation",
    },
]

# ==================== SIGNATURE AUDIT TRAIL MODELS ====================
 
class SignatureEventCreate(BaseModel):
    """Payload sent from frontend when a signature is captured."""
    document_type: str  # "logbook", "daily_log", "worker_registration"
    document_id: str    # MongoDB _id of the parent document
    event_type: str     # "cp_sign", "superintendent_sign", "worker_sign"
    signer_name: str
    signer_role: str    # "cp", "site_device", "worker", "admin"
    signature_data: Dict[str, Any]  # The actual {paths, signerName, timestamp} or base64
    content_snapshot: Dict[str, Any]  # Full JSON of document at sign-time
    device_info: Optional[Dict[str, Any]] = None  # {site_device_id, hardware_fingerprint, user_agent}
 
class SignatureEventResponse(BaseModel):
    id: str
    document_type: str
    document_id: str
    event_type: str
    version: int
    signer: Dict[str, Any]
    device: Dict[str, Any]
    content_hash: str
    timestamp: datetime
    # signature_data and content_snapshot omitted from list responses for size
    # — fetch individually via GET /signature-events/{id}
 
# ==================== CONSTRUCTION SUPERINTENDENT MODELS ====================
 
class CSRegistrationCreate(BaseModel):
    """Register a Construction Superintendent to a project."""
    project_id: str
    full_name: str
    license_number: str          # NYC DOB License/Registration Number
    nyc_id_email: Optional[str] = None  # NYC.ID email used for DOB filings
    sst_number: Optional[str] = None    # SST card number if different
    phone: Optional[str] = None
 
class CSRegistrationUpdate(BaseModel):
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    nyc_id_email: Optional[str] = None
    sst_number: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
 
class CSRegistrationResponse(BaseModel):
    id: str
    project_id: str
    project_name: str
    full_name: str
    license_number: str
    nyc_id_email: Optional[str] = None
    sst_number: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    conflict_warning: Optional[str] = None  # Set if license found on another active project
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
	
# ==================== SYNC MODELS ====================

class SyncPullRequest(BaseModel):
    lastPulledAt: Optional[int] = None  # Unix timestamp in milliseconds
    schemaVersion: int = 1
    migration: Optional[dict] = None

class SyncPushRequest(BaseModel):
    changes: dict
    lastPulledAt: Optional[int] = None
    
    # ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str, email: str, role: str, site_mode: bool = False, project_id: str = None, company_id: str = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "site_mode": site_mode,
        "project_id": project_id,
        "company_id": company_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    token: Optional[str] = None,
):
    raw_token = None
    if credentials:
        raw_token = credentials.credentials
    elif token:
        raw_token = token

    if not raw_token:
        logger.error("❌ AUTH FAIL: No token provided")
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(raw_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        site_mode = payload.get("site_mode", False)

        if not user_id:
            logger.error("❌ AUTH FAIL: No user_id in token")
            raise HTTPException(status_code=401, detail="Invalid token")

        if site_mode:
            device = await db.site_devices.find_one({"_id": to_query_id(user_id)})
            if not device:
                logger.error(f"❌ AUTH FAIL: Site device not found - {user_id}")
                raise HTTPException(status_code=401, detail="Device not found")

            device_data = serialize_id(device)
            device_data["site_mode"] = True
            device_data["role"] = "site_device"

            if device.get("project_id"):
                project = await db.projects.find_one({"_id": to_query_id(device["project_id"])})
                if project:
                    device_data["company_id"] = project.get("company_id")

            logger.info(f"✅ AUTH SUCCESS: Site device {user_id}")
            return device_data

        user = await db.users.find_one({"_id": to_query_id(user_id)})
        if not user:
            logger.error(f"❌ AUTH FAIL: User not found - {user_id}")
            raise HTTPException(status_code=401, detail="User not found")

        user_data = serialize_id(user)
        user_data["site_mode"] = False
        logger.info(f"✅ AUTH SUCCESS: User {user_id}, role={user_data.get('role')}")
        return user_data

    except jwt.ExpiredSignatureError:
        logger.error("❌ AUTH FAIL: Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"❌ AUTH FAIL: Invalid token - {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")
		
async def get_admin_user(current_user = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
	
def get_user_company_id(current_user):
    """Get the company_id from current user"""
    if current_user.get("site_mode"):
        return current_user.get("company_id")
    return current_user.get("company_id")

async def require_company_access(current_user = Depends(get_current_user)):
    """Ensure user has a company_id (for company-scoped operations)"""
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(
            status_code=403, 
            detail="Company access required. Please contact your administrator."
        )
    return current_user

# ==================== SYNC HELPERS ====================

# WatermelonDB schema columns per table - only these fields should be sent to client
WATERMELON_COLUMNS = {
    "workers": {"id", "name", "phone", "trade", "company", "osha_number", "certifications", "backend_id", "created_at", "updated_at", "is_deleted"},
    "projects": {"id", "name", "address", "status", "start_date", "end_date", "backend_id", "created_at", "updated_at", "is_deleted"},
    "check_ins": {"id", "worker_id", "project_id", "worker_name", "worker_trade", "worker_company", "project_name", "check_in_time", "check_out_time", "nfc_tag_id", "backend_id", "created_at", "updated_at", "is_deleted", "sync_status"},
    "daily_logs": {"id", "project_id", "project_name", "date", "weather", "notes", "work_performed", "materials_used", "issues", "backend_id", "created_at", "updated_at", "is_deleted", "sync_status"},
    "nfc_tags": {"id", "tag_id", "project_id", "project_name", "location", "backend_id", "created_at", "updated_at", "is_deleted"},
}

def sanitize_for_watermelon(record, table_name):
    """Remove fields that don't exist in WatermelonDB schema to prevent decorator errors"""
    allowed = WATERMELON_COLUMNS.get(table_name)
    if not allowed:
        return record
    
    # Map backend field names to WatermelonDB field names
    if table_name == "nfc_tags":
        if "location_description" in record and "location" not in record:
            record["location"] = record.pop("location_description")
    
    return {k: v for k, v in record.items() if k in allowed}

async def get_table_changes(table_name: str, last_pulled: Optional[datetime], company_id: Optional[str]):
    """Get created, updated, and deleted records for a table since last_pulled"""
    # Map WatermelonDB table names to MongoDB collection names
    collection_name_map = {
        "check_ins": "checkins",
    }
    collection = db[collection_name_map.get(table_name, table_name)]
    
    base_query = {}
    if company_id:
        base_query["company_id"] = company_id
    
    if last_pulled:
        # Records created since last pull
        created_query = {**base_query, "created_at": {"$gt": last_pulled}, "is_deleted": {"$ne": True}}
        created = await collection.find(created_query).to_list(10000)
        
        # Records updated since last pull (but created before)
        updated_query = {
            **base_query,
            "updated_at": {"$gt": last_pulled},
            "created_at": {"$lte": last_pulled},
            "is_deleted": {"$ne": True}
        }
        updated = await collection.find(updated_query).to_list(10000)
        
        # Records deleted since last pull
        deleted_query = {**base_query, "is_deleted": True, "updated_at": {"$gt": last_pulled}}
        deleted_records = await collection.find(deleted_query, {"_id": 1}).to_list(10000)
        deleted = [str(r["_id"]) for r in deleted_records]
    else:
        # First sync - get all non-deleted records
        active_query = {**base_query, "is_deleted": {"$ne": True}}
        created = await collection.find(active_query).to_list(10000)
        updated = []
        deleted = []
    
    return {
        "created": [sanitize_for_watermelon(serialize_sync_record(dict(r)), table_name) for r in created],
        "updated": [sanitize_for_watermelon(serialize_sync_record(dict(r)), table_name) for r in updated],
        "deleted": deleted
    }

# ==================== SYNC ENDPOINTS ====================

@api_router.post("/sync/pull")
async def sync_pull(request: SyncPullRequest, current_user = Depends(get_current_user)):
    """Pull all changes from server since lastPulledAt"""
    try:
        if current_user.get("role") == "owner":
            company_id = None  # Owner sees all data
        else:
            company_id = get_user_company_id(current_user)
            if not company_id:
                raise HTTPException(status_code=403, detail="Company access required for sync")
        
        # Convert milliseconds to datetime
        last_pulled = None
        if request.lastPulledAt:
            last_pulled = datetime.fromtimestamp(request.lastPulledAt / 1000, timezone.utc)
        
        logger.info(f"Sync pull request from user {current_user.get('id')}, company {company_id}, lastPulledAt: {last_pulled}")
        
        # Get changes for each table (use WatermelonDB table names)
        changes = {
            "workers": await get_table_changes("workers", last_pulled, company_id),
            "projects": await get_table_changes("projects", last_pulled, company_id),
            "check_ins": await get_table_changes("check_ins", last_pulled, company_id),
            "daily_logs": await get_table_changes("daily_logs", last_pulled, company_id),
            "nfc_tags": await get_table_changes("nfc_tags", last_pulled, company_id),
        }
        
        current_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        logger.info(f"Sync pull response: {sum(len(t['created']) + len(t['updated']) for t in changes.values())} records")
        
        return {
            "changes": changes,
            "timestamp": current_timestamp
        }
    except Exception as e:
        logger.error(f"Sync pull error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sync pull failed: {str(e)}")

@api_router.post("/sync/push")
async def sync_push(request: SyncPushRequest, current_user = Depends(get_current_user)):
    """Push local changes to server"""
    try:
        if current_user.get("role") == "owner":
            company_id = None
        else:
            company_id = get_user_company_id(current_user)
            if not company_id:
                raise HTTPException(status_code=403, detail="Company access required for sync")
        
        logger.info(f"Sync push request from user {current_user.get('id')}, company {company_id}")
        
        # Map table names to collection names
        table_map = {
            "workers": "workers",
            "projects": "projects",
            "check_ins": "checkins",
            "daily_logs": "daily_logs",
            "nfc_tags": "nfc_tags"
        }
        
        for table_name, table_changes in request.changes.items():
            if table_name not in table_map:
                continue
                
            collection_name = table_map[table_name]
            collection = db[collection_name]
            
            # Handle creates — with duplicate detection for check-ins
            for record in table_changes.get("created", []):
                try:
                    record["company_id"] = company_id
                    record["is_deleted"] = False

                    if "id" in record:
                        record["_id"] = record["id"]
                        del record["id"]

                    if "created_at" in record:
                        record["created_at"] = datetime.fromtimestamp(record["created_at"] / 1000, timezone.utc)
                    else:
                        record["created_at"] = datetime.now(timezone.utc)

                    if "updated_at" in record:
                        record["updated_at"] = datetime.fromtimestamp(record["updated_at"] / 1000, timezone.utc)
                    else:
                        record["updated_at"] = datetime.now(timezone.utc)

                    if "check_in_time" in record and isinstance(record["check_in_time"], (int, float)):
                        record["check_in_time"] = datetime.fromtimestamp(record["check_in_time"] / 1000, timezone.utc)
                    if "check_out_time" in record and isinstance(record["check_out_time"], (int, float)):
                        record["check_out_time"] = datetime.fromtimestamp(record["check_out_time"] / 1000, timezone.utc)
                    if "timestamp" in record and isinstance(record["timestamp"], (int, float)):
                        record["timestamp"] = datetime.fromtimestamp(record["timestamp"] / 1000, timezone.utc)

                    # Duplicate detection for check-ins: same worker + project + day = skip
                    if collection_name == "checkins" and record.get("worker_id") and record.get("project_id"):
                        today_start, today_end = get_today_range_est()
                        existing = await collection.find_one({
                            "worker_id": record["worker_id"],
                            "project_id": record["project_id"],
                            "check_in_time": {"$gte": today_start, "$lt": today_end},
                            "status": "checked_in",
                            "is_deleted": {"$ne": True},
                        })
                        if existing:
                            logger.info(f"Duplicate check-in skipped: worker {record['worker_id']} already checked in")
                            continue

                    await collection.insert_one(record)
                    logger.info(f"Created record in {collection_name} with ID {record['_id']}")
                except Exception as e:
                    if "E11000" in str(e):
                        logger.warning(f"Duplicate ID {record.get('_id')} in create, skipping.")
                    else:
                        logger.error(f"Error creating record in {collection_name}: {str(e)}")
            
            # Handle updates — last-write-wins: only apply if incoming updated_at > server's
            for record in table_changes.get("updated", []):
                try:
                    record_id = record.pop("id", None)
                    if not record_id:
                        continue

                    # Convert timestamps
                    if "updated_at" in record:
                        record["updated_at"] = datetime.fromtimestamp(record["updated_at"] / 1000, timezone.utc)
                    else:
                        record["updated_at"] = datetime.now(timezone.utc)

                    if "check_in_time" in record and isinstance(record["check_in_time"], (int, float)):
                        record["check_in_time"] = datetime.fromtimestamp(record["check_in_time"] / 1000, timezone.utc)
                    if "check_out_time" in record and isinstance(record["check_out_time"], (int, float)):
                        record["check_out_time"] = datetime.fromtimestamp(record["check_out_time"] / 1000, timezone.utc)
                    if "timestamp" in record and isinstance(record["timestamp"], (int, float)):
                        record["timestamp"] = datetime.fromtimestamp(record["timestamp"] / 1000, timezone.utc)

                    # Last-write-wins: only update if our timestamp is newer than server's
                    incoming_ts = record.get("updated_at", datetime.now(timezone.utc))
                    result = await collection.update_one(
                        {
                            "_id": to_query_id(record_id),
                            "company_id": company_id,
                            "$or": [
                                {"updated_at": {"$lt": incoming_ts}},
                                {"updated_at": {"$exists": False}},
                            ],
                        },
                        {"$set": record}
                    )
                    if result.matched_count > 0:
                        logger.info(f"Updated record in {collection_name} (last-write-wins)")
                    else:
                        logger.info(f"Skipped stale update in {collection_name} for {record_id}")
                except Exception as e:
                    logger.error(f"Error updating record in {collection_name}: {str(e)}")
            
            # Handle deletes (soft delete)
            for record_id in table_changes.get("deleted", []):
                try:
                    await collection.update_one(
                        {"_id": to_query_id(record_id), "company_id": company_id},
                        {"$set": {
                            "is_deleted": True,
                            "updated_at": datetime.now(timezone.utc)
                        }}
                    )
                    logger.info(f"Soft deleted record in {collection_name}")
                except Exception as e:
                    logger.error(f"Error deleting record in {collection_name}: {str(e)}")
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Sync push error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sync push failed: {str(e)}")

@api_router.get("/sync/timestamp")
async def sync_timestamp():
    """Get current server timestamp in milliseconds"""
    return {"timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)}

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin, request: Request = None, _rate=Depends(check_auth_rate_limit)):
    # First try regular user login
    user = await db.users.find_one({"email": credentials.email})
    if user and verify_password(credentials.password, user.get("password", "")):
        token = create_token(
            str(user["_id"]), 
            user["email"], 
            user.get("role", "worker"),
            company_id=user.get("company_id")
        )
        return TokenResponse(token=token)
    
    # Try site device login (username matches email field in login)
    device = await db.site_devices.find_one({"username": credentials.email, "is_active": True})
    if device and verify_password(credentials.password, device.get("password", "")):
        # Update last login
        await db.site_devices.update_one(
            {"_id": device["_id"]},
            {"$set": {"last_login": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
        )
        
        # Get company_id from project
        company_id = None
        if device.get("project_id"):
            project = await db.projects.find_one({"_id": to_query_id(device["project_id"])})
            if project:
                company_id = project.get("company_id")
        
        token = create_token(
            str(device["_id"]), 
            device["username"], 
            "site_device",
            site_mode=True,
            project_id=device.get("project_id"),
            company_id=company_id
        )
        return TokenResponse(token=token)
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@api_router.post("/auth/register", response_model=UserResponse)
async def register(user_data: UserCreate, request: Request = None, _rate=Depends(check_auth_rate_limit)):
    # SECURITY REGRESSION (intentional, temporary): password complexity
    # (8-char min + letter+digit mix) was removed for demo-day testing.
    # Only a bare non-empty check remains. Restore the strict checks
    # before production customer rollout.
    pwd = user_data.password
    if not pwd:
        raise HTTPException(status_code=422, detail="Password is required")

    # Check if email exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_dict = user_data.model_dump()
    user_dict["password"] = hash_password(user_dict["password"])
    now = datetime.now(timezone.utc)
    user_dict["created_at"] = now
    user_dict["updated_at"] = now
    user_dict["assigned_projects"] = []
    user_dict["is_deleted"] = False
    
    # If no company_id provided, this is invalid (except for testing)
    if not user_dict.get("company_id") and user_dict.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=400, detail="Company ID required")

    # CP role hard-requires a company — without one every company-gated
    # endpoint will 403 and their session looks broken. Explicit error
    # text for this case on top of the generic Company ID required rule.
    _role = user_dict.get("role") or getattr(user_data, "role", None)
    _cid = user_dict.get("company_id") or getattr(user_data, "company_id", None)
    if (_role == "cp") and not _cid:
        raise HTTPException(
            status_code=422,
            detail="company_id is required when creating a CP user. "
                   "Assign them to a company first.",
        )

    result = await db.users.insert_one(user_dict)
    user_dict["id"] = str(result.inserted_id)
    del user_dict["password"]

    return UserResponse(**user_dict)

@api_router.get("/auth/me")
async def get_me(current_user = Depends(get_current_user)):
    user = dict(current_user)
    if "password" in user:
        del user["password"]
    return user

@api_router.put("/auth/profile")
async def update_profile(body: UpdateProfileRequest, current_user=Depends(get_current_user)):
    """
    Update the authenticated user's display name and/or phone number.
    Available to all roles (admin, owner, cp, worker).

    Phone is normalized to E.164. An empty-string phone is treated as explicit
    removal. Uniqueness is enforced within the user's company.
    """
    name_provided  = body.name  is not None
    phone_provided = body.phone is not None

    if not name_provided and not phone_provided:
        raise HTTPException(status_code=422, detail="No fields to update")

    set_ops: Dict[str, Any] = {}
    now = datetime.now(timezone.utc)

    # ---- Name ----
    if name_provided:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name cannot be empty")
        set_ops["name"] = name
        set_ops["full_name"] = name

    # ---- Phone (may be normalized, may be explicit removal) ----
    new_phone_normalized: Optional[str] = None
    phone_is_removal = False
    if phone_provided:
        raw = (body.phone or "").strip()
        if raw == "":
            phone_is_removal = True
            new_phone_normalized = ""
        else:
            new_phone_normalized = normalize_phone(raw)
            set_ops["phone"] = new_phone_normalized
        if phone_is_removal:
            set_ops["phone"] = ""

    # ---- Fetch current user from DB (authoritative) ----
    user_doc = await db.users.find_one({"_id": to_query_id(current_user["id"])})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    old_phone = (user_doc.get("phone") or "")
    company_id = user_doc.get("company_id")

    # ---- Uniqueness check (only when setting a non-empty phone) ----
    if phone_provided and not phone_is_removal and new_phone_normalized:
        if company_id:
            collision = await db.users.find_one({
                "company_id": company_id,
                "phone": new_phone_normalized,
                "_id": {"$ne": to_query_id(current_user["id"])},
                "is_deleted": {"$ne": True},
            })
            if collision:
                raise HTTPException(
                    status_code=409,
                    detail="This phone number is already in use by another user in your company.",
                )

    set_ops["updated_at"] = now

    result = await db.users.update_one(
        {"_id": to_query_id(current_user["id"])},
        {"$set": set_ops}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # ---- Sync whatsapp_contacts when phone changed and company WhatsApp is active ----
    if phone_provided and company_id and new_phone_normalized != old_phone:
        try:
            wa_config = await db.whatsapp_config.find_one({"company_id": company_id})
            if wa_config and wa_config.get("is_active"):
                # Null out user_id on the old row (preserve message history)
                if old_phone:
                    await db.whatsapp_contacts.update_one(
                        {"company_id": company_id, "phone": old_phone},
                        {"$set": {"user_id": None}},
                    )
                # Upsert new row
                if new_phone_normalized:
                    display_name = set_ops.get("name") or user_doc.get("name", "")
                    await db.whatsapp_contacts.update_one(
                        {"company_id": company_id, "phone": new_phone_normalized},
                        {"$set": {
                            "company_id": company_id,
                            "phone": new_phone_normalized,
                            "user_id": str(current_user["id"]),
                            "display_name": display_name,
                        }},
                        upsert=True,
                    )
        except Exception as e:
            logger.warning(f"whatsapp_contacts sync failed for user {current_user['id']}: {e}")

    # ---- Audit log phone changes specifically ----
    if phone_provided and new_phone_normalized != old_phone:
        try:
            await audit_log(
                "profile_phone_change",
                str(current_user["id"]),
                "user",
                str(current_user["id"]),
                {"old_phone": old_phone, "new_phone": new_phone_normalized},
            )
        except Exception as e:
            logger.warning(f"audit_log (profile_phone_change) failed: {e}")

    logger.info(
        f"User {current_user['id']} updated profile: "
        f"name_changed={name_provided}, phone_changed={phone_provided and new_phone_normalized != old_phone}"
    )
    return {
        "message": "Profile updated",
        "name": set_ops.get("name", user_doc.get("name", "")),
        "phone": set_ops.get("phone", old_phone),
    }


@api_router.put("/auth/password")
async def update_password(body: UpdatePasswordRequest, current_user=Depends(get_current_user)):
    """
    Change the authenticated user's own password.
    Restricted to admin and owner roles only.
    Verifies current password before accepting the new one.
    """
    # Role guard — only admin / owner can use this endpoint
    role = current_user.get("role")
    if role not in ("admin", "owner"):
        raise HTTPException(
            status_code=403,
            detail="Only admins and owners can change passwords through this endpoint"
        )

    # Fetch the stored hash — get_current_user already stripped the password
    # field, so we must re-query the DB for it here.
    user_doc = await db.users.find_one({"_id": to_query_id(current_user["id"])})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify the current password using your existing helper
    stored_hash = user_doc.get("password", "")
    if not verify_password(body.current_password, stored_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # SECURITY REGRESSION (intentional, temporary): minimum-length check
    # removed for demo-day testing. Restore before production rollout.
    if not body.new_password:
        raise HTTPException(status_code=422, detail="New password is required")

    new_hash = hash_password(body.new_password)
    await db.users.update_one(
        {"_id": to_query_id(current_user["id"])},
        {"$set": {
            "password": new_hash,
            "updated_at": datetime.now(timezone.utc),
        }}
    )

    logger.info(f"User {current_user['id']} (role={role}) changed their password")
    return {"message": "Password updated successfully"}

# ==================== ADMIN USER MANAGEMENT ====================

@api_router.get("/admin/users")
async def get_admin_users(
    current_user = Depends(get_admin_user),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if current_user.get("role") != "owner" and company_id:
        query["company_id"] = company_id
    
    result = await paginated_query(db.users, query, sort_field="name", sort_dir=1, limit=limit, skip=skip, projection={"password": 0})
    return result
@api_router.post("/admin/users", response_model=UserResponse)
async def create_admin_user(user_data: UserCreate, admin = Depends(get_admin_user)):
    # SECURITY REGRESSION (intentional, temporary): password complexity
    # removed for demo-day testing. Restore before production rollout.
    pwd = user_data.password
    if not pwd:
        raise HTTPException(status_code=422, detail="Password is required")

    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_dict = user_data.model_dump()
    user_dict["password"] = hash_password(user_dict["password"])
    now = datetime.now(timezone.utc)
    user_dict["created_at"] = now
    user_dict["updated_at"] = now
    user_dict["assigned_projects"] = []
    user_dict["is_deleted"] = False

    # Normalize phone to E.164 if provided
    if user_dict.get("phone"):
        user_dict["phone"] = normalize_phone(user_dict["phone"])

    # IMPORTANT: Inherit company_id from admin creating the user
    user_dict["company_id"] = admin.get("company_id")
    if admin.get("company_name"):
        user_dict["company_name"] = admin.get("company_name")

    # CP role hard-requires a company — without one every company-gated
    # endpoint will 403 and their session looks broken. Block creation
    # up front so the admin sees a clear, actionable error.
    _role = user_dict.get("role") or getattr(user_data, "role", None)
    _cid = user_dict.get("company_id") or getattr(user_data, "company_id", None)
    if (_role == "cp") and not _cid:
        raise HTTPException(
            status_code=422,
            detail="company_id is required when creating a CP user. "
                   "Assign them to a company first.",
        )

    result = await db.users.insert_one(user_dict)
    user_dict["id"] = str(result.inserted_id)

    # Sync to whatsapp_contacts if phone provided
    if user_dict.get("phone") and user_dict.get("company_id"):
        try:
            await db.whatsapp_contacts.update_one(
                {"company_id": user_dict["company_id"], "phone": user_dict["phone"]},
                {"$set": {
                    "company_id": user_dict["company_id"],
                    "phone": user_dict["phone"],
                    "user_id": str(result.inserted_id),
                    "display_name": user_dict.get("name", ""),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"whatsapp_contacts upsert failed for user {result.inserted_id}: {e}")

    del user_dict["password"]

    return UserResponse(**user_dict)

@api_router.get("/admin/users/{user_id}", response_model=UserResponse)
async def get_admin_user_by_id(user_id: str, current_user = Depends(get_admin_user)):
    user = await db.users.find_one({"_id": to_query_id(user_id), "is_deleted": {"$ne": True}}, {"password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**serialize_id(user))

@api_router.put("/admin/users/{user_id}", response_model=UserResponse)
async def update_admin_user(user_id: str, user_data: dict, admin = Depends(get_admin_user)):
    # Field whitelist — prevent privilege escalation via arbitrary field injection
    ALLOWED_USER_FIELDS = {"name", "full_name", "email", "role", "phone", "assigned_projects", "password"}
    update_data = {k: v for k, v in user_data.items() if v is not None and k in ALLOWED_USER_FIELDS and k != "password"}
    if "password" in user_data and user_data["password"]:
        update_data["password"] = hash_password(user_data["password"])

    # Normalize phone to E.164 if provided
    if "phone" in update_data and update_data["phone"]:
        update_data["phone"] = normalize_phone(update_data["phone"])

    update_data["updated_at"] = datetime.now(timezone.utc)

    # Fetch existing user to detect phone changes
    existing_user = await db.users.find_one({"_id": to_query_id(user_id)})
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")
    old_phone = existing_user.get("phone", "")
    company_id = existing_user.get("company_id")

    result = await db.users.update_one(
        {"_id": to_query_id(user_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Sync whatsapp_contacts on phone change
    new_phone = update_data.get("phone", old_phone)
    if company_id and "phone" in update_data:
        try:
            if new_phone != old_phone:
                # Deactivate old contact (preserve message history)
                if old_phone:
                    await db.whatsapp_contacts.update_one(
                        {"company_id": company_id, "phone": old_phone},
                        {"$set": {"user_id": None}},
                    )
                # Upsert new contact
                if new_phone:
                    await db.whatsapp_contacts.update_one(
                        {"company_id": company_id, "phone": new_phone},
                        {"$set": {
                            "company_id": company_id,
                            "phone": new_phone,
                            "user_id": user_id,
                            "display_name": update_data.get("name") or existing_user.get("name", ""),
                        }},
                        upsert=True,
                    )
            else:
                # Phone unchanged — update display_name if name changed
                if "name" in update_data and new_phone:
                    await db.whatsapp_contacts.update_one(
                        {"company_id": company_id, "phone": new_phone},
                        {"$set": {"display_name": update_data["name"]}},
                    )
        except Exception as e:
            logger.warning(f"whatsapp_contacts sync failed for user {user_id}: {e}")

    # Audit — especially important for role changes
    audit_details = {k: v for k, v in update_data.items() if k != "password" and k != "updated_at"}
    if audit_details:
        await audit_log("user_update", str(admin.get("_id", "")), "user", user_id, audit_details)

    user = await db.users.find_one({"_id": to_query_id(user_id)}, {"password": 0})
    return UserResponse(**serialize_id(user))

@api_router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: str, admin = Depends(get_admin_user)):
    # Fetch user before delete to get phone for whatsapp_contacts cleanup
    user_doc = await db.users.find_one({"_id": to_query_id(user_id)})

    # Soft delete
    result = await db.users.update_one(
        {"_id": to_query_id(user_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Revoke WhatsApp bot access — nullify user_id on their contact record
    if user_doc and user_doc.get("phone") and user_doc.get("company_id"):
        try:
            await db.whatsapp_contacts.update_one(
                {"company_id": user_doc["company_id"], "phone": user_doc["phone"]},
                {"$set": {"user_id": None}},
            )
        except Exception as e:
            logger.warning(f"whatsapp_contacts cleanup failed for deleted user {user_id}: {e}")

    await audit_log("user_delete", str(admin.get("_id", "")), "user", user_id)
    return {"message": "User deleted successfully"}

@api_router.post("/admin/users/{user_id}/assign-projects")
async def assign_projects_to_user(user_id: str, project_ids: dict, admin = Depends(get_admin_user)):
    result = await db.users.update_one(
        {"_id": to_query_id(user_id)},
        {"$set": {
            "assigned_projects": project_ids.get("project_ids", []),
            "updated_at": datetime.now(timezone.utc)
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Projects assigned successfully"}

# ==================== ADMIN SUBCONTRACTORS ====================

@api_router.get("/admin/subcontractors")
async def get_subcontractors(
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    result = await paginated_query(db.subcontractors, query, sort_field="company_name", sort_dir=1, limit=limit, skip=skip, projection={"password": 0})
    return result
@api_router.post("/admin/subcontractors", response_model=SubcontractorResponse)
async def create_subcontractor(sub_data: SubcontractorCreate, admin = Depends(get_admin_user)):
    existing = await db.subcontractors.find_one({"email": sub_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    sub_dict = sub_data.model_dump()
    sub_dict["password"] = hash_password(sub_dict["password"])
    now = datetime.now(timezone.utc)
    sub_dict["created_at"] = now
    sub_dict["updated_at"] = now
    sub_dict["workers_count"] = 0
    sub_dict["assigned_projects"] = []
    sub_dict["company_id"] = admin.get("company_id")
    sub_dict["is_deleted"] = False
    
    result = await db.subcontractors.insert_one(sub_dict)
    sub_dict["id"] = str(result.inserted_id)
    del sub_dict["password"]
    
    return SubcontractorResponse(**sub_dict)

@api_router.get("/admin/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def get_subcontractor(sub_id: str, current_user = Depends(get_current_user)):
    sub = await db.subcontractors.find_one({"_id": to_query_id(sub_id), "is_deleted": {"$ne": True}}, {"password": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    return SubcontractorResponse(**serialize_id(sub))

@api_router.put("/admin/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def update_subcontractor(sub_id: str, sub_data: dict, admin = Depends(get_admin_user)):
    ALLOWED_SUB_FIELDS = {"name", "company_name", "email", "phone", "trade", "license_number", "insurance_info", "password"}
    update_data = {k: v for k, v in sub_data.items() if v is not None and k in ALLOWED_SUB_FIELDS and k != "password"}
    if "password" in sub_data and sub_data["password"]:
        update_data["password"] = hash_password(sub_data["password"])
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.subcontractors.update_one(
        {"_id": to_query_id(sub_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    
    sub = await db.subcontractors.find_one({"_id": to_query_id(sub_id)}, {"password": 0})
    return SubcontractorResponse(**serialize_id(sub))

@api_router.delete("/admin/subcontractors/{sub_id}")
async def delete_subcontractor(sub_id: str, admin = Depends(get_admin_user)):
    # Soft delete
    result = await db.subcontractors.update_one(
        {"_id": to_query_id(sub_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    return {"message": "Subcontractor deleted successfully"}

# ==================== OWNER - COMPANY MANAGEMENT ====================

@api_router.get("/owner/companies")
async def get_companies(current_user = Depends(get_current_user)):
    """Get all companies (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    companies = await db.companies.find({"is_deleted": {"$ne": True}}).to_list(200)
    return serialize_list(companies)

@api_router.post("/owner/companies")
async def create_company(company_data: CompanyCreate, current_user = Depends(get_current_user)):
    """Create a new company (owner only). Optionally links to a GC license and fetches insurance from BIS."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    # Check if company name already exists
    existing = await db.companies.find_one({"name": company_data.name, "is_deleted": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="Company name already exists")

    now = datetime.now(timezone.utc)
    company_dict = {
        "name": company_data.name,
        "created_at": now,
        "updated_at": now,
        "created_by": current_user.get("id"),
        "is_deleted": False,
        "gc_license_number": company_data.gc_license_number,
        "gc_business_name": company_data.gc_business_name,
        "gc_licensee_name": company_data.gc_licensee_name,
        "gc_license_status": company_data.gc_license_status,
        "gc_license_expiration": company_data.gc_license_expiration,
        "gc_resolved": company_data.gc_resolved,
        "gc_insurance_records": [],
        "gc_last_verified": None,
    }

    # If GC license provided, fetch insurance from BIS (non-blocking — never fail company creation)
    if company_data.gc_license_number and company_data.gc_resolved:
        try:
            from permit_renewal import _fetch_insurance_details
            import httpx
            async with ServerHttpClient(timeout=20.0) as client:
                insurance = await _fetch_insurance_details(client, company_data.gc_license_number)
                company_dict["gc_insurance_records"] = [rec.dict() for rec in insurance]
                company_dict["gc_last_verified"] = now
        except Exception as e:
            logger.warning(f"BIS insurance fetch failed for {company_data.gc_license_number}: {e}")
            # Company still gets created — insurance will be empty

    result = await db.companies.insert_one(company_dict)
    company_dict["id"] = str(result.inserted_id)
    company_dict.pop("_id", None)

    return company_dict

class LinkGcLicenseRequest(BaseModel):
    gc_license_number: str


@api_router.get("/owner/debug/bis-license/{license_number}", tags=["Owner"])
async def debug_bis_license(license_number: str, current_user=Depends(get_current_user)):
    """Diagnostic: fetch the raw BIS license page and return a sanitized snippet
    plus what the current regex extracts. Owner only."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    import httpx
    from permit_renewal import DOB_BIS_LICENSE_URL, _fetch_insurance_details

    raw_html = ""
    status_code = 0
    err = None
    try:
        async with ServerHttpClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(
                DOB_BIS_LICENSE_URL,
                params={"requestid": "2", "licno": license_number},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            status_code = r.status_code
            raw_html = r.text
    except Exception as e:
        err = str(e)

    # Strip HTML tags to see readable text
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()

    # Try the current regex extraction
    extracted = []
    try:
        async with ServerHttpClient(timeout=20.0) as client:
            extracted = [rec.dict() for rec in await _fetch_insurance_details(client, license_number)]
    except Exception as e:
        extracted = [{"error": str(e)}]

    # Look for date patterns and keywords
    keywords = {
        "General Liability": bool(re.search(r"General\s+Liability", raw_html, re.I)),
        "Workers Comp":      bool(re.search(r"Worker[s']?\s*Comp", raw_html, re.I)),
        "Disability":        bool(re.search(r"Disability", raw_html, re.I)),
        "Insurance":         bool(re.search(r"Insurance", raw_html, re.I)),
        "licensee name":     bool(re.search(r"KATZ|LAZAR", raw_html, re.I)),
    }
    dates = re.findall(r"\d{1,2}/\d{1,2}/\d{2,4}", raw_html)[:20]

    return {
        "license_number": license_number,
        "status_code": status_code,
        "html_length": len(raw_html),
        "error": err,
        "keywords_found": keywords,
        "dates_found": dates,
        "extracted_by_current_regex": extracted,
        "text_snippet_first_2000": text[:2000],
    }



@api_router.post("/owner/companies/{company_id}/link-gc-license", tags=["Owner"])
async def link_gc_license_to_company(
    company_id: str,
    body: LinkGcLicenseRequest,
    current_user=Depends(get_current_user),
):
    """
    Link an existing company to an NYC DOB GC license number, then fetch
    insurance records from BIS. Owner only.
    """
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    company = await db.companies.find_one({"_id": to_query_id(company_id), "is_deleted": {"$ne": True}})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    lic_num = body.gc_license_number.strip()
    if not lic_num:
        raise HTTPException(status_code=422, detail="License number required")

    # Try local cache first; if not present, hit NYC Open Data directly
    gc_doc = await db.gc_licenses.find_one({"license_number": lic_num})
    now = datetime.now(timezone.utc)

    if not gc_doc:
        try:
            import httpx
            DATASET_URL = "https://data.cityofnewyork.us/resource/w5r2-853r.json"
            async with ServerHttpClient(timeout=20.0) as client:
                resp = await client.get(DATASET_URL, params={
                    "license_number": lic_num,
                    "license_type": "GENERAL CONTRACTOR",
                })
                if resp.status_code == 200:
                    records = resp.json()
                    if records:
                        rec = records[0]
                        gc_doc = {
                            "license_number": lic_num,
                            "business_name": (rec.get("business_name") or "").strip(),
                            "licensee_name": f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip(),
                            "license_type": "GC",
                            "license_status": (rec.get("license_status") or "").strip(),
                            "license_expiration": None,
                            "source": "nyc_open_data",
                            "last_synced": now,
                            "created_at": now,
                            "insurance_records": [],
                        }
                        await db.gc_licenses.update_one(
                            {"license_number": lic_num},
                            {"$set": gc_doc},
                            upsert=True,
                        )
        except Exception as e:
            logger.warning(f"NYC Open Data lookup failed for license {lic_num}: {e}")

    if not gc_doc:
        raise HTTPException(status_code=404, detail=f"GC license {lic_num} not found in NYC Open Data.")

    # Fetch insurance from BIS
    insurance_dicts = []
    try:
        from permit_renewal import _fetch_insurance_details
        import httpx
        async with ServerHttpClient(timeout=20.0) as client:
            insurance = await _fetch_insurance_details(client, lic_num)
            insurance_dicts = [rec.dict() for rec in insurance]
    except Exception as e:
        logger.warning(f"BIS insurance fetch failed for license {lic_num}: {e}")

    # Write license + insurance onto the company
    update_fields = {
        "gc_license_number": lic_num,
        "gc_business_name": gc_doc.get("business_name"),
        "gc_licensee_name": gc_doc.get("licensee_name"),
        "gc_license_status": gc_doc.get("license_status"),
        "gc_license_expiration": gc_doc.get("license_expiration"),
        "gc_resolved": True,
        "gc_insurance_records": insurance_dicts,
        "gc_last_verified": now,
        "updated_at": now,
    }
    await db.companies.update_one({"_id": to_query_id(company_id)}, {"$set": update_fields})

    return {
        "company_id": company_id,
        "gc_license_number": lic_num,
        "gc_business_name": gc_doc.get("business_name"),
        "gc_license_status": gc_doc.get("license_status"),
        "gc_insurance_records_count": len(insurance_dicts),
    }


@api_router.delete("/owner/companies/{company_id}", tags=["Owner"])
async def hard_delete_company(company_id: str, current_user=Depends(get_current_user)):
    """Hard delete a company and all its users (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    # Safety check: no active admins assigned
    admin_count = await db.users.count_documents({
        "company_id": company_id,
        "role": "admin",
        "is_deleted": {"$ne": True}
    })
    if admin_count > 0:
        raise HTTPException(status_code=400, detail="Remove all admins from this company first")

    # Delete all users belonging to this company
    await db.users.delete_many({"company_id": company_id})

    # Delete the company
    result = await db.companies.delete_one({"_id": to_query_id(company_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    await audit_log("company_hard_delete", str(current_user.get("_id", "")), "company", company_id)

    return {"message": "Company and all users permanently deleted"}


# ==================== MR.2: FILING REPS CRUD (owner-tier) =================
# Owner-tier endpoints for managing the filing_reps roster on a
# company. See FilingRep / FilingRepCreate / FilingRepUpdate Pydantic
# models near line ~400. is_primary uniqueness is enforced atomically:
# whenever a rep is added or updated with is_primary=True, every other
# rep on the same company is demoted to is_primary=False in the same
# Mongo update. No two reps on a company can be is_primary=True
# simultaneously.

async def _demote_other_primaries(company_id: str, except_rep_id: str):
    """Demote every is_primary=True filing_rep on this company OTHER
    than the given rep_id to is_primary=False. Atomic. Used by both
    the create and update endpoints when the incoming/edited rep
    carries is_primary=True."""
    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {
            "filing_reps.$[other].is_primary": False,
            "filing_reps.$[other].updated_at": datetime.now(timezone.utc),
        }},
        array_filters=[{"other.id": {"$ne": except_rep_id}, "other.is_primary": True}],
    )


@api_router.get("/owner/companies/{company_id}/filing-reps", tags=["Owner"])
async def list_filing_reps(company_id: str, current_user=Depends(get_current_user)):
    """List filing_reps for a company (owner only)."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return company.get("filing_reps") or []


@api_router.post("/owner/companies/{company_id}/filing-reps", tags=["Owner"])
async def add_filing_rep(
    company_id: str,
    body: FilingRepCreate,
    current_user=Depends(get_current_user),
):
    """Add a new filing_rep to a company. Generates a stable rep_id
    (uuid4 hex). If is_primary=True is sent, any other primary on
    this company is demoted in the same transaction so exactly one
    primary holds across the array."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    if body.license_class not in FILING_REP_LICENSE_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"license_class must be one of {sorted(FILING_REP_LICENSE_CLASSES)}",
        )

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    now = datetime.now(timezone.utc)
    rep_id = uuid.uuid4().hex
    rep_doc = {
        "id": rep_id,
        "name": body.name,
        "license_class": body.license_class,
        "license_number": body.license_number,
        "license_type": body.license_type,
        "email": body.email,
        "is_primary": bool(body.is_primary),
        "created_at": now,
        "updated_at": now,
        # MR.10 forward fix: initialize the credentials array on
        # insert so MR.10's add_filing_rep_credential endpoint
        # doesn't have to lift a missing field via its defensive
        # guard. The MR.6 Pydantic model declares this field with
        # a default of [], but Pydantic defaults don't write through
        # to MongoDB on dict-shaped inserts — without this line,
        # new reps would still ship without the field on disk.
        "credentials": [],
    }

    # Push the new rep onto the array.
    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$push": {"filing_reps": rep_doc}},
    )

    # If the new rep is primary, demote any prior primaries.
    if rep_doc["is_primary"]:
        await _demote_other_primaries(company_id, rep_id)

    return rep_doc


@api_router.patch("/owner/companies/{company_id}/filing-reps/{rep_id}", tags=["Owner"])
async def update_filing_rep(
    company_id: str,
    rep_id: str,
    body: FilingRepUpdate,
    current_user=Depends(get_current_user),
):
    """Patch fields on an existing filing_rep. Same is_primary
    uniqueness rule as the create endpoint — flipping a rep TO
    primary demotes any other primary on the same company."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    if body.license_class is not None and body.license_class not in FILING_REP_LICENSE_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"license_class must be one of {sorted(FILING_REP_LICENSE_CLASSES)}",
        )

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    existing_rep = next(
        (r for r in (company.get("filing_reps") or []) if r.get("id") == rep_id),
        None,
    )
    if not existing_rep:
        raise HTTPException(status_code=404, detail="Filing representative not found")

    now = datetime.now(timezone.utc)
    set_fields = {"filing_reps.$[rep].updated_at": now}
    for field in ("name", "license_class", "license_number", "license_type", "email"):
        value = getattr(body, field, None)
        if value is not None:
            set_fields[f"filing_reps.$[rep].{field}"] = value
    if body.is_primary is not None:
        set_fields["filing_reps.$[rep].is_primary"] = bool(body.is_primary)

    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": set_fields},
        array_filters=[{"rep.id": rep_id}],
    )

    # Promotion path — demote any other primary if this rep just
    # flipped to primary.
    if body.is_primary is True:
        await _demote_other_primaries(company_id, rep_id)

    # Return the updated rep.
    refreshed = await db.companies.find_one(
        {"_id": to_query_id(company_id)},
        {"filing_reps": 1},
    )
    updated_rep = next(
        (r for r in (refreshed.get("filing_reps") or []) if r.get("id") == rep_id),
        None,
    )
    return updated_rep or {}


@api_router.delete("/owner/companies/{company_id}/filing-reps/{rep_id}", tags=["Owner"])
async def delete_filing_rep(
    company_id: str,
    rep_id: str,
    current_user=Depends(get_current_user),
):
    """Remove a filing_rep from a company by rep_id."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    result = await db.companies.update_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}},
        {"$pull": {"filing_reps": {"id": rep_id}}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Filing representative not found")

    return {"message": "Filing representative removed", "id": rep_id}


# ──────────────────────────────────────────────────────────────────────
# MR.6 — Filing-rep credentials (encrypted DOB NOW passwords).
# ──────────────────────────────────────────────────────────────────────
# Three endpoints under /owner/companies/{company_id}/filing-reps/{rep_id}/credentials:
#   POST   — push a new credential, supersede the prior active, $push w/ next version
#   DELETE — revoke the current active credential without replacement
#   GET    — list metadata (version, created_at, superseded_at, fingerprint).
#            CIPHERTEXT IS NEVER RETURNED to the UI; the worker reads it
#            from the queue payload, not from this endpoint.
#
# Concurrency note: two simultaneous POST writers can race between the
# supersede step and the push step, producing same-version duplicates.
# This is documented in MR.6's architectural surprises; in practice
# operators rotate credentials rarely and the race window is on the
# order of milliseconds. A future hardening pass can use a Mongo
# aggregation-pipeline update to make the supersede + push truly atomic.

def _find_filing_rep(company: dict, rep_id: str) -> Optional[dict]:
    """Locate a filing_rep entry inside a company doc by rep_id.
    Returns the dict (mutable reference into the company doc) or
    None if not found."""
    for rep in (company.get("filing_reps") or []):
        if rep.get("id") == rep_id:
            return rep
    return None


def _strip_credential_ciphertext(cred: dict) -> dict:
    """Project a credential entry to its metadata-only form for GET
    responses. Ciphertext is opaque-but-still-secret material; never
    surface it through the read API."""
    return {
        "version": cred.get("version"),
        "public_key_fingerprint": cred.get("public_key_fingerprint"),
        "created_at": cred.get("created_at"),
        "superseded_at": cred.get("superseded_at"),
    }


@api_router.get(
    "/owner/companies/{company_id}/filing-reps/{rep_id}/credentials",
    tags=["Owner"],
)
async def list_filing_rep_credentials(
    company_id: str,
    rep_id: str,
    current_user=Depends(get_current_user),
):
    """List credential metadata for a filing_rep. Ordered version desc.
    Ciphertext is intentionally NOT included — the UI never has any
    reason to see it, only the worker decrypts."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    rep = _find_filing_rep(company, rep_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="Filing representative not found")

    creds = rep.get("credentials") or []
    return sorted(
        [_strip_credential_ciphertext(c) for c in creds],
        key=lambda c: (c.get("version") or 0),
        reverse=True,
    )


@api_router.post(
    "/owner/companies/{company_id}/filing-reps/{rep_id}/credentials",
    tags=["Owner"],
)
async def add_filing_rep_credential(
    company_id: str,
    rep_id: str,
    body: FilingRepCredentialCreate,
    current_user=Depends(get_current_user),
):
    """Push a new credential. Side effects:
      1. Stamp `superseded_at` on the prior active credential (if any).
      2. Compute next version = max(existing.version) + 1 (1-indexed).
      3. $push the new credential entry on filing_reps[rep].credentials.

    Two MongoDB ops because $set + $push on the same array element
    in one update is awkward with array_filters; we eat the
    millisecond-scale race window between them. The new credential
    entry is the only one with superseded_at=None when this returns,
    barring a concurrent writer."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    if not body.encrypted_ciphertext or not body.public_key_fingerprint:
        raise HTTPException(
            status_code=400,
            detail="encrypted_ciphertext and public_key_fingerprint are required",
        )

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    rep = _find_filing_rep(company, rep_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="Filing representative not found")

    now = datetime.now(timezone.utc)

    # 0. Defensive lift: pre-MR.10 reps were inserted by add_filing_rep
    #    without a `credentials` field. The MR.6 Pydantic model declares
    #    `credentials: List[FilingRepCredential] = []` as a read-side
    #    default, but Pydantic defaults don't write through on insert,
    #    so legacy docs in production lack the field entirely (verified
    #    against BlueView's reps post-MR.10 deploy). The supersede $set
    #    below traverses the path `filing_reps.$[rep].credentials.$[cred]`
    #    which raises Mongo `PathNotViable` when the credentials array
    #    is absent. Lift the field to [] for any rep missing it. The
    #    matching backfill migration in
    #    backend/scripts/migrate_filing_reps_credentials_init.py
    #    sweeps prod once; this guard keeps the endpoint correct even
    #    if the migration hasn't been run yet, OR if a future code
    #    path inserts a rep without the field (regression-evident
    #    via the test pinned in test_filing_rep_credentials.py).
    #    Idempotent: $elemMatch with `$exists: False` matches nothing
    #    on already-initialized reps, so the update is a no-op.
    await db.companies.update_one(
        {
            "_id": to_query_id(company_id),
            "filing_reps": {
                "$elemMatch": {
                    "id": rep_id,
                    "credentials": {"$exists": False},
                },
            },
        },
        {"$set": {"filing_reps.$.credentials": []}},
    )

    # 1. Supersede the prior active credential, if any. array_filters
    #    matches every credential entry on this rep where superseded_at
    #    is None (exactly one in the steady state — an empty match
    #    when no prior credential exists is a no-op).
    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {
            "filing_reps.$[rep].credentials.$[cred].superseded_at": now,
            "filing_reps.$[rep].updated_at": now,
        }},
        array_filters=[
            {"rep.id": rep_id},
            {"cred.superseded_at": None},
        ],
    )

    # 2. Compute next version from the (potentially-now-superseded)
    #    credentials list.
    existing_versions = [
        (c.get("version") or 0) for c in (rep.get("credentials") or [])
    ]
    next_version = (max(existing_versions) if existing_versions else 0) + 1

    new_credential = {
        "version": next_version,
        "encrypted_ciphertext": body.encrypted_ciphertext,
        "public_key_fingerprint": body.public_key_fingerprint,
        "created_at": now,
        "superseded_at": None,
    }

    # 3. $push the new entry.
    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$push": {"filing_reps.$[rep].credentials": new_credential}},
        array_filters=[{"rep.id": rep_id}],
    )

    # Return the new credential — metadata-only. Caller never needs
    # to read back what they wrote.
    return _strip_credential_ciphertext(new_credential)


@api_router.delete(
    "/owner/companies/{company_id}/filing-reps/{rep_id}/credentials/active",
    tags=["Owner"],
)
async def revoke_filing_rep_active_credential(
    company_id: str,
    rep_id: str,
    current_user=Depends(get_current_user),
):
    """Revoke the current active credential WITHOUT replacement. Sets
    superseded_at on the active entry. Subsequent enqueue requests
    will fail the credential-gate check (active_credential() returns
    None). 404 if no active credential exists.

    Distinct from DELETE on the filing_rep itself, which removes the
    rep entirely. This endpoint preserves the rep + its credential
    history; only the active credential is killed."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    rep = _find_filing_rep(company, rep_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="Filing representative not found")

    active = filing_rep_active_credential(rep)
    if active is None:
        raise HTTPException(
            status_code=404,
            detail="No active credential to revoke",
        )

    now = datetime.now(timezone.utc)
    result = await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {
            "filing_reps.$[rep].credentials.$[cred].superseded_at": now,
            "filing_reps.$[rep].updated_at": now,
        }},
        array_filters=[
            {"rep.id": rep_id},
            {"cred.version": active.get("version"), "cred.superseded_at": None},
        ],
    )
    if result.modified_count == 0:
        # Race: another writer just superseded it. Surface as 404 so
        # the caller can re-read state.
        raise HTTPException(
            status_code=404,
            detail="Active credential changed between read and revoke",
        )

    return {
        "revoked": True,
        "version": active.get("version"),
        "superseded_at": now,
    }


# ──────────────────────────────────────────────────────────────────────
# MR.6 — Admin filing-jobs observability surface (owner-tier).
# ──────────────────────────────────────────────────────────────────────
# GET /api/admin/filing-jobs lists every job across every company
# for the audit/observability UI MR.7 ships. Filters and pagination
# match the conventions of the other admin list endpoints.

VALID_FILING_JOB_SORT_FIELDS = {"created_at", "updated_at", "status"}


@api_router.get("/admin/filing-jobs", tags=["Admin"])
async def admin_list_filing_jobs(
    current_user=Depends(get_current_user),
    status: Optional[str] = Query(None, description="Filter by FilingJobStatus value"),
    company_id: Optional[str] = Query(None, description="Filter to a single tenant"),
    created_after: Optional[str] = Query(None, description="ISO-8601 lower bound on created_at"),
    created_before: Optional[str] = Query(None, description="ISO-8601 upper bound on created_at"),
    sort_by: str = Query("created_at"),
    sort_dir: int = Query(-1, ge=-1, le=1),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """List filing_jobs across all tenants for the owner-tier audit
    surface. Owner-only. Filters: status, company_id, date range
    (ISO-8601 strings; parsed via fromisoformat). Pagination uses the
    same skip/limit/total/has_more shape as paginated_query()."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    # Validate sort_by — refuse arbitrary fields so a typo doesn't
    # silently sort by a field that doesn't exist (Mongo returns
    # everything in insertion order in that case, which looks like
    # success).
    if sort_by not in VALID_FILING_JOB_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"sort_by must be one of {sorted(VALID_FILING_JOB_SORT_FIELDS)}; "
                f"got {sort_by!r}"
            ),
        )
    if sort_dir not in (-1, 1):
        raise HTTPException(status_code=400, detail="sort_dir must be -1 or 1")

    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if status:
        # Validate against the enum so a typo (e.g. 'inprogress' vs
        # 'in_progress') 400s instead of returning an empty list.
        valid_statuses = {s.value for s in FilingJobStatus}
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of {sorted(valid_statuses)}; got {status!r}",
            )
        query["status"] = status
    if company_id:
        query["company_id"] = company_id

    # Date range — accept ISO-8601 strings (with or without Z suffix).
    if created_after or created_before:
        date_query: Dict[str, datetime] = {}
        try:
            if created_after:
                date_query["$gte"] = datetime.fromisoformat(
                    created_after.replace("Z", "+00:00")
                )
            if created_before:
                date_query["$lte"] = datetime.fromisoformat(
                    created_before.replace("Z", "+00:00")
                )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"created_after/created_before must be ISO-8601: {e}",
            )
        query["created_at"] = date_query

    cursor = (
        db.filing_jobs.find(query)
        .sort(sort_by, sort_dir)
        .skip(skip)
        .limit(limit)
    )
    items: List[Dict[str, Any]] = []
    async for job in cursor:
        # Belt-and-suspenders strip — schema doesn't carry ciphertext
        # but defense-in-depth for any future drift.
        job_dict = serialize_id(dict(job))
        job_dict.pop("encrypted_ciphertext", None)
        items.append(job_dict)
    total = await db.filing_jobs.count_documents(query)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


# ──────────────────────────────────────────────────────────────────────
# MR.9 — Notification observability + manual resend (owner-tier).
# ──────────────────────────────────────────────────────────────────────

VALID_NOTIFICATION_TRIGGERS_FOR_FILTER = {
    "renewal_t_minus_30",
    "renewal_t_minus_14",
    "renewal_t_minus_7",
    "filing_stuck",
    "renewal_completed",
}


@api_router.get("/admin/notifications", tags=["Admin"])
async def admin_list_notifications(
    current_user=Depends(get_current_user),
    trigger_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    permit_renewal_id: Optional[str] = Query(None),
    sent_after: Optional[str] = Query(None, description="ISO-8601"),
    sent_before: Optional[str] = Query(None, description="ISO-8601"),
    sort_dir: int = Query(-1, ge=-1, le=1),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """List notification_log entries — owner-tier audit surface. Used
    to answer "did the operator actually get the email?" — filters by
    trigger_type, status, permit_renewal_id, and ISO-8601 date range.
    Returns the paginated_query envelope shape."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    if sort_dir not in (-1, 1):
        raise HTTPException(status_code=400, detail="sort_dir must be -1 or 1")

    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if trigger_type:
        if trigger_type not in VALID_NOTIFICATION_TRIGGERS_FOR_FILTER:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"trigger_type must be one of "
                    f"{sorted(VALID_NOTIFICATION_TRIGGERS_FOR_FILTER)}"
                ),
            )
        query["trigger_type"] = trigger_type
    if status:
        from lib.notifications import VALID_NOTIFICATION_STATUSES
        if status not in VALID_NOTIFICATION_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"status must be one of "
                    f"{sorted(VALID_NOTIFICATION_STATUSES)}"
                ),
            )
        query["status"] = status
    if permit_renewal_id:
        query["permit_renewal_id"] = permit_renewal_id

    if sent_after or sent_before:
        date_query: Dict[str, datetime] = {}
        try:
            if sent_after:
                date_query["$gte"] = datetime.fromisoformat(
                    sent_after.replace("Z", "+00:00")
                )
            if sent_before:
                date_query["$lte"] = datetime.fromisoformat(
                    sent_before.replace("Z", "+00:00")
                )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"sent_after/sent_before must be ISO-8601: {e}",
            )
        query["sent_at"] = date_query

    cursor = (
        db.notification_log.find(query)
        .sort("sent_at", sort_dir)
        .skip(skip)
        .limit(limit)
    )
    items: List[Dict[str, Any]] = []
    async for doc in cursor:
        items.append(serialize_id(dict(doc)))
    total = await db.notification_log.count_documents(query)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


@api_router.post(
    "/admin/notifications/{notification_id}/resend",
    tags=["Admin"],
)
async def admin_resend_notification(
    notification_id: str,
    current_user=Depends(get_current_user),
):
    """Re-send a previously-failed notification by re-rendering the
    trigger template against the original renewal + recipient and
    routing through send_notification (which writes a NEW log entry).
    The original notification_log entry is unchanged — failures are
    preserved as audit evidence.

    Idempotency: the resend uses the same (renewal, trigger, recipient)
    keys as the original, so if a successful send happened in the
    last 23h, send_notification will short-circuit with
    `suppressed_idempotent`. To force a real send, the operator can
    call this endpoint again after the dedup window passes."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    from lib.notifications import send_notification
    from lib.email_templates import render_for_trigger

    original = await db.notification_log.find_one(
        {"_id": to_query_id(notification_id)}
    )
    if not original:
        raise HTTPException(status_code=404, detail="Notification not found")

    permit_renewal_id = original.get("permit_renewal_id")
    trigger_type = original.get("trigger_type")
    recipient = original.get("recipient")
    if not (permit_renewal_id and trigger_type and recipient):
        raise HTTPException(
            status_code=422,
            detail="Original notification record incomplete — cannot resend",
        )

    # Re-render with current renewal + project state (NOT the original
    # context, which we don't store). This is intentional — if the
    # data has changed (e.g. expiration was extended), the resend
    # reflects the current truth.
    renewal = await db.permit_renewals.find_one(
        {"_id": to_query_id(permit_renewal_id)}
    )
    if not renewal:
        raise HTTPException(
            status_code=404,
            detail="Underlying renewal not found (may have been deleted)",
        )

    # Reconstruct days_until_expiry from current_expiration. For
    # stuck/completed triggers this is unused by the template but
    # required for context shape consistency.
    days_until = 0
    try:
        from dateutil import parser as dateparser
        exp = renewal.get("current_expiration")
        if exp:
            exp_dt = dateparser.parse(str(exp)).date()
            days_until = (exp_dt - datetime.now(timezone.utc).date()).days
    except Exception:
        pass

    base_context = await _renewal_reminder_context(renewal, days_until)
    base_context["recipient_name"] = recipient.split("@", 1)[0]
    # Best-effort name override from filing_reps roster.
    try:
        company = await db.companies.find_one(
            {"_id": to_query_id(renewal.get("company_id"))}
        )
        if company:
            for rep in (company.get("filing_reps") or []):
                if (rep.get("email") or "").lower() == recipient.lower():
                    base_context["recipient_name"] = rep.get("name") or base_context["recipient_name"]
                    break
    except Exception:
        pass

    # Layer in any trigger-specific context preserved from the
    # original metadata (e.g. days_stuck, new_expiration).
    base_context.update(original.get("metadata") or {})

    try:
        subject, html, text = render_for_trigger(trigger_type, base_context)
    except Exception as render_err:
        raise HTTPException(
            status_code=500,
            detail=f"Template render failed: {render_err}",
        )

    new_log = await send_notification(
        db,
        permit_renewal_id=permit_renewal_id,
        trigger_type=trigger_type,
        recipient=recipient,
        subject=subject,
        html=html,
        text=text,
        metadata={
            **(original.get("metadata") or {}),
            "resent_from_notification_id": str(original.get("_id")),
        },
    )
    return serialize_id(dict(new_log))


# ──────────────────────────────────────────────────────────────────────
# MR.10 — Agent public-key registry + authorization document.
# ──────────────────────────────────────────────────────────────────────
#
# The local Docker agent generates an RSA-4096 keypair on first run
# (dob_worker/scripts/generate_keypair.py, MR.5). The operator pastes
# the public key into the Owner Portal; this server stores it in
# `agent_public_keys`. The frontend's credential-entry form fetches
# the active key (GET /agent-public-key, no auth — public keys are
# public by definition), encrypts the operator-typed credentials in
# the browser using the SubtleCrypto Web Crypto API, and POSTs the
# resulting ciphertext to the existing MR.6 /credentials endpoint.
#
# Byte format MUST match dob_worker/lib/crypto.py:
#   [4-byte big-endian RSA-wrapped-key length]
#   [RSA-OAEP-SHA256-wrapped 32-byte AES key]
#   [12-byte AES-GCM nonce]
#   [AES-GCM ciphertext + 16-byte tag concatenated]
# Final blob is base64-encoded for JSON transport.
#
# Authorization document: one-time-per-company gate. Operator must
# accept text + type the licensee name before any credentials can
# be added. MR.6's enqueue endpoint refuses jobs for companies
# without a non-null `authorization` field.

def _compute_public_key_fingerprint(pem: str) -> str:
    """SHA-256 hex digest of the DER-encoded SubjectPublicKeyInfo.

    Matches the fingerprint convention the frontend SubtleCrypto path
    can reproduce: hash the DER bytes (i.e. the binary content between
    the PEM markers), output as lowercase hex. Frontend can verify
    by re-deriving from the same PEM."""
    from cryptography.hazmat.primitives import serialization
    import hashlib
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


class AgentPublicKeyCreate(BaseModel):
    """POST body for /api/admin/agent-keys."""
    worker_id: str
    public_key_pem: str


@api_router.post("/admin/agent-keys", tags=["Admin"])
async def admin_register_agent_key(
    body: AgentPublicKeyCreate,
    current_user=Depends(get_current_user),
):
    """Register an agent's public key. Owner-tier. The operator runs
    `docker compose run --rm dob_worker python scripts/generate_keypair.py`
    on the local agent (per MR.5's operator pre-deploy checklist),
    copies the printed public-key PEM, and pastes it here."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    pem = (body.public_key_pem or "").strip()
    if not pem.startswith("-----BEGIN PUBLIC KEY-----") or "-----END PUBLIC KEY-----" not in pem:
        raise HTTPException(
            status_code=400,
            detail="public_key_pem must be a valid SubjectPublicKeyInfo PEM",
        )

    try:
        fingerprint = _compute_public_key_fingerprint(pem)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse public key: {e}",
        )

    now = datetime.now(timezone.utc)
    doc = {
        "worker_id": body.worker_id,
        "public_key_pem": pem,
        "fingerprint_sha256": fingerprint,
        "created_at": now,
        "revoked_at": None,
    }
    result = await db.agent_public_keys.insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize_id(dict(doc))


@api_router.get("/admin/agent-keys", tags=["Admin"])
async def admin_list_agent_keys(
    current_user=Depends(get_current_user),
):
    """List all registered agent public keys (active + revoked).
    Used by the operator portal to audit which keypairs are
    authorized to decrypt credentials."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    cursor = db.agent_public_keys.find({}).sort("created_at", -1)
    keys: List[Dict[str, Any]] = []
    async for doc in cursor:
        keys.append(serialize_id(dict(doc)))
    return {"keys": keys, "total": len(keys)}


@api_router.delete("/admin/agent-keys/{key_id}", tags=["Admin"])
async def admin_revoke_agent_key(
    key_id: str,
    current_user=Depends(get_current_user),
):
    """Mark an agent key revoked. Subsequent credential encryptions
    must use a non-revoked active key. Existing credentials encrypted
    against a now-revoked key remain valid until the agent stops
    decrypting them — revocation is forward-only."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    now = datetime.now(timezone.utc)
    result = await db.agent_public_keys.update_one(
        {"_id": to_query_id(key_id)},
        {"$set": {"revoked_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent key not found")
    return {"revoked": True, "key_id": key_id, "revoked_at": now}


@api_router.get("/agent-public-key")
async def public_get_active_agent_key():
    """No-auth read of the active agent public key. Public keys are
    public by definition; the frontend uses this to encrypt operator-
    typed credentials before POST /credentials.

    Returns the most recently created key with revoked_at=null. 503
    when no active key exists — operator must register one via
    POST /api/admin/agent-keys before credentials can be added."""
    active = await db.agent_public_keys.find_one(
        {"revoked_at": None},
        sort=[("created_at", -1)],
    )
    if not active:
        raise HTTPException(
            status_code=503,
            detail=(
                "No active agent key registered. Run "
                "scripts/generate_keypair.py on the local agent and "
                "POST the public key to /api/admin/agent-keys."
            ),
        )
    # Return only the public-facing fields. We never expose the
    # full Mongo doc (created_at and worker_id are fine to expose
    # but stripping them keeps the API surface minimal — frontend
    # only needs the PEM + fingerprint to encrypt).
    return {
        "public_key_pem": active.get("public_key_pem"),
        "fingerprint_sha256": active.get("fingerprint_sha256"),
        "worker_id": active.get("worker_id"),
    }


# ── Authorization document ─────────────────────────────────────────
# One-time-per-company gate. Operator accepts the text + types the
# licensee name to confirm. Credentials cannot be added (frontend
# blocks the modal) and renewals cannot be filed (MR.6 gate refuses
# enqueue) until authorization is on file.

class AuthorizationAccept(BaseModel):
    """POST body for /api/owner/companies/{id}/authorization."""
    licensee_name_typed: str

# Bumping AUTHORIZATION_TEXT_VERSION re-arms the gate: companies whose
# stored authorization.version does not match the current version are
# treated as un-authorized. This is the documented mechanism for
# requiring re-acceptance after material changes to the auth text.
# Keep in sync with the Version: line in backend/templates/authorization_text.md.
AUTHORIZATION_TEXT_VERSION = "1.0"


def _load_authorization_text() -> str:
    """Read the canonical authorization text from the bundled
    template file. Cached at module import time would be marginally
    faster but file reads on a cold cache are still microsecond-scale
    and this endpoint is operator-rare."""
    import os.path
    here = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(here, "templates", "authorization_text.md")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Authorization text not found at {template_path}")
        return ""


@api_router.get("/owner/companies/{company_id}/authorization", tags=["Owner"])
async def get_company_authorization(
    company_id: str,
    current_user=Depends(get_current_user),
):
    """Return the current authorization status + the canonical text
    the operator must accept. Always returns 200 — `accepted` field
    indicates whether a non-null record exists matching the current
    version."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    auth = company.get("authorization") or None
    accepted = (
        auth is not None
        and auth.get("version") == AUTHORIZATION_TEXT_VERSION
    )
    return {
        "company_id": company_id,
        "accepted": accepted,
        "authorization": serialize_id(dict(auth)) if auth else None,
        "current_version": AUTHORIZATION_TEXT_VERSION,
        "authorization_text": _load_authorization_text(),
        "expected_licensee_name": (
            company.get("gc_licensee_name")
            or company.get("gc_business_name")
            or company.get("name")
        ),
    }


@api_router.post("/owner/companies/{company_id}/authorization", tags=["Owner"])
async def post_company_authorization(
    company_id: str,
    body: AuthorizationAccept,
    current_user=Depends(get_current_user),
):
    """Persist authorization acceptance for a company. The operator's
    typed licensee_name must match (case-insensitive, whitespace-
    normalized) one of the canonical name forms on the company doc:
    gc_licensee_name, gc_business_name, or name. Mismatch → 400.

    Re-posting overwrites the existing record — operators can re-
    accept after a text version bump or after revoking + re-granting.
    The new record gets a fresh accepted_at and version stamp."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    typed = (body.licensee_name_typed or "").strip()
    if not typed:
        raise HTTPException(
            status_code=400,
            detail="licensee_name_typed is required",
        )

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    expected_names = {
        (company.get("gc_licensee_name") or "").strip().lower(),
        (company.get("gc_business_name") or "").strip().lower(),
        (company.get("name") or "").strip().lower(),
    }
    expected_names.discard("")
    if typed.lower() not in expected_names:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Typed name does not match any registered name "
                    "for this company"
                ),
                "code": "licensee_name_mismatch",
                "expected_one_of": sorted(n for n in expected_names if n),
            },
        )

    now = datetime.now(timezone.utc)
    auth_doc = {
        "version": AUTHORIZATION_TEXT_VERSION,
        "accepted_at": now,
        "accepted_by_user_id": (
            current_user.get("user_id")
            or current_user.get("id")
            or current_user.get("email")
            or "unknown"
        ),
        "licensee_name_typed": typed,
    }
    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {"authorization": auth_doc, "updated_at": now}},
    )
    return {
        "company_id": company_id,
        "authorization": auth_doc,
    }


# ==================== GC LICENSE INDEX & AUTOCOMPLETE ====================

@api_router.post("/owner/seed-gc-licenses")
async def seed_gc_licenses(current_user=Depends(get_current_user)):
    """Bulk-load all GC licenses from NYC Open Data into gc_licenses collection (owner only)."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    import httpx
    DATASET_URL = "https://data.cityofnewyork.us/resource/w5r2-853r.json"
    PAGE_SIZE = 1000
    offset = 0
    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc)

    try:
        async with ServerHttpClient(timeout=30.0) as client:
            while True:
                resp = await client.get(DATASET_URL, params={
                    "$where": "license_type='GENERAL CONTRACTOR'",
                    "$limit": str(PAGE_SIZE),
                    "$offset": str(offset),
                })
                if resp.status_code != 200:
                    logger.error(f"NYC Open Data returned {resp.status_code}")
                    break
                records = resp.json()
                if not records:
                    break

                for rec in records:
                    lic_num = rec.get("license_number", "").strip()
                    if not lic_num:
                        continue
                    doc = {
                        "license_number": lic_num,
                        "business_name": (rec.get("business_name") or "").strip(),
                        "licensee_name": f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip(),
                        "license_type": "GC",
                        "license_status": (rec.get("license_status") or "").strip(),
                        "license_expiration": None,  # Not available in Open Data — BIS only
                        "insurance_records": [],
                        "source": "nyc_open_data",
                        "last_synced": now,
                    }
                    result = await db.gc_licenses.update_one(
                        {"license_number": lic_num},
                        {"$set": doc, "$setOnInsert": {"created_at": now}},
                        upsert=True,
                    )
                    if result.upserted_id:
                        inserted += 1
                    elif result.modified_count > 0:
                        updated += 1

                offset += PAGE_SIZE
                if len(records) < PAGE_SIZE:
                    break
    except Exception as e:
        logger.exception(f"GC license seed error: {e}")
        raise HTTPException(status_code=500, detail=f"Seed failed: {str(e)}")

    # Ensure text index for autocomplete
    try:
        await db.gc_licenses.create_index("license_number", unique=True)
        await db.gc_licenses.create_index([("business_name", 1)])
    except Exception:
        pass

    return {"inserted": inserted, "updated": updated, "total_processed": offset}


@api_router.post("/owner/run-gc-sync")
async def run_gc_sync(current_user=Depends(get_current_user)):
    """Re-sync GC licenses from NYC Open Data. Flags status changes for companies in our DB (owner only)."""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    import httpx
    DATASET_URL = "https://data.cityofnewyork.us/resource/w5r2-853r.json"
    PAGE_SIZE = 1000
    offset = 0
    updated = 0
    status_changes = []
    now = datetime.now(timezone.utc)

    try:
        async with ServerHttpClient(timeout=30.0) as client:
            while True:
                resp = await client.get(DATASET_URL, params={
                    "$where": "license_type='GENERAL CONTRACTOR'",
                    "$limit": str(PAGE_SIZE),
                    "$offset": str(offset),
                })
                if resp.status_code != 200:
                    break
                records = resp.json()
                if not records:
                    break

                for rec in records:
                    lic_num = rec.get("license_number", "").strip()
                    if not lic_num:
                        continue
                    new_status = (rec.get("license_status") or "").strip()

                    # Check for status change
                    existing = await db.gc_licenses.find_one({"license_number": lic_num})
                    old_status = existing.get("license_status") if existing else None

                    await db.gc_licenses.update_one(
                        {"license_number": lic_num},
                        {"$set": {
                            "business_name": (rec.get("business_name") or "").strip(),
                            "licensee_name": f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip(),
                            "license_status": new_status,
                            "source": "nyc_open_data",
                            "last_synced": now,
                        }, "$setOnInsert": {"created_at": now, "license_type": "GC", "insurance_records": [], "license_expiration": None}},
                        upsert=True,
                    )

                    if old_status and old_status != new_status:
                        updated += 1
                        status_changes.append({"license_number": lic_num, "old": old_status, "new": new_status})
                        # Flag companies using this license
                        await db.companies.update_many(
                            {"gc_license_number": lic_num, "is_deleted": {"$ne": True}},
                            {"$set": {"gc_license_status": new_status, "updated_at": now}},
                        )

                offset += PAGE_SIZE
                if len(records) < PAGE_SIZE:
                    break
    except Exception as e:
        logger.exception(f"GC sync error: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

    return {"processed": offset, "status_changes": len(status_changes), "changes": status_changes[:50]}


@api_router.get("/gc/autocomplete")
async def gc_autocomplete(
    q: str = Query(..., min_length=2, description="Search query"),
    current_user=Depends(get_current_user),
):
    """Autocomplete GC license by business name. Searches local index first, falls back to BIS scrape."""
    import re as _re

    # Build regex prefix match (case-insensitive)
    escaped = _re.escape(q.strip())
    regex = {"$regex": escaped, "$options": "i"}

    results = await db.gc_licenses.find(
        {"business_name": regex, "license_status": {"$in": ["ACTIVE", "Active", "active"]}},
    ).sort("business_name", 1).limit(10).to_list(10)

    # If too few local results, try BIS scrape as fallback
    if len(results) < 2:
        try:
            from permit_renewal import scrape_gc_license_info
            bis_result = await scrape_gc_license_info(q.strip())
            if bis_result and bis_result.license_number:
                # Cache into gc_licenses collection
                now = datetime.now(timezone.utc)
                await db.gc_licenses.update_one(
                    {"license_number": bis_result.license_number},
                    {"$set": {
                        "business_name": bis_result.business_name or q.strip(),
                        "licensee_name": bis_result.licensee_name or "",
                        "license_type": "GC",
                        "license_status": bis_result.license_status or "ACTIVE",
                        "license_expiration": bis_result.license_expiration,
                        "source": "bis_scrape",
                        "last_synced": now,
                    }, "$setOnInsert": {"created_at": now, "insurance_records": []}},
                    upsert=True,
                )
                # Check if already in results
                existing_nums = {r.get("license_number") for r in results}
                if bis_result.license_number not in existing_nums:
                    bis_doc = await db.gc_licenses.find_one({"license_number": bis_result.license_number})
                    if bis_doc:
                        results.append(bis_doc)
        except Exception as e:
            logger.warning(f"BIS fallback failed for autocomplete '{q}': {e}")

    return [
        {
            "license_number": r.get("license_number"),
            "business_name": r.get("business_name"),
            "licensee_name": r.get("licensee_name"),
            "license_expiration": r.get("license_expiration"),
            "license_status": r.get("license_status"),
        }
        for r in results
    ]


# ==================== ADMIN - INSURANCE & LICENSE (READ-ONLY) ====================

@api_router.get("/admin/company/insurance")
async def get_admin_company_insurance(current_user=Depends(get_admin_user)):
    """Get GC license + insurance info for the admin's own company."""
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company associated with your account")

    company = await db.companies.find_one({"_id": to_query_id(company_id), "is_deleted": {"$ne": True}})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return {
        "company_id": str(company["_id"]),
        "company_name": company.get("name"),
        "gc_license_number": company.get("gc_license_number"),
        "gc_business_name": company.get("gc_business_name"),
        "gc_licensee_name": company.get("gc_licensee_name"),
        "gc_license_status": company.get("gc_license_status"),
        "gc_license_expiration": company.get("gc_license_expiration"),
        "gc_insurance_records": company.get("gc_insurance_records", []),
        "gc_resolved": company.get("gc_resolved", False),
        "gc_last_verified": company.get("gc_last_verified"),
    }


@api_router.post("/admin/company/insurance/refresh")
async def refresh_admin_company_insurance(current_user=Depends(get_admin_user)):
    """Refresh the company's GC license status/name from NYC Open Data.

    Insurance records are NOT touched by this endpoint — they are now managed
    manually via PUT /admin/company/insurance/manual. DOB BIS was the only
    source for insurance and is blocked by Akamai bot protection.
    """
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company associated with your account")

    company = await db.companies.find_one({"_id": to_query_id(company_id), "is_deleted": {"$ne": True}})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    lic_num = company.get("gc_license_number")
    if not lic_num:
        raise HTTPException(status_code=400, detail="No GC license linked to this company. Contact your administrator.")

    now = datetime.now(timezone.utc)
    warning = "Insurance records are manually managed. Use 'Update Insurance' to change expiry dates."

    # Pull current status via NYC Open Data using the existing scrape_gc_license_info
    # implementation (which was rewritten in Commit 1 to hit Open Data).
    try:
        from permit_renewal import scrape_gc_license_info
        lookup_name = company.get("gc_business_name") or company.get("name", "")
        logger.info(
            f"Insurance refresh — company_id={company_id} license={lic_num} "
            f"lookup_name={lookup_name!r}"
        )
        gc_info = await scrape_gc_license_info(lookup_name)
        update_fields = {
            "gc_last_verified": now,
            "updated_at": now,
        }
        if gc_info:
            if gc_info.license_status:
                update_fields["gc_license_status"] = gc_info.license_status
            if gc_info.license_expiration:
                update_fields["gc_license_expiration"] = gc_info.license_expiration
            if gc_info.business_name:
                update_fields["gc_business_name"] = gc_info.business_name
            if gc_info.licensee_name:
                update_fields["gc_licensee_name"] = gc_info.licensee_name

        await db.companies.update_one({"_id": to_query_id(company_id)}, {"$set": update_fields})
        # Re-read so we return fresh values
        company = await db.companies.find_one({"_id": to_query_id(company_id)})

    except Exception as e:
        logger.error(f"License refresh failed for company {company_id} license {lic_num}: {e}")
        warning = "Could not reach NYC Open Data. Showing cached license data."

    return {
        "gc_license_number": lic_num,
        "gc_license_status": company.get("gc_license_status"),
        "gc_license_expiration": company.get("gc_license_expiration"),
        # Preserve manually-entered records — never overwrite.
        "gc_insurance_records": company.get("gc_insurance_records", []),
        "gc_last_verified": str(now),
        "warning": warning,
    }


class ManualInsuranceRequest(BaseModel):
    general_liability_expiry: str
    workers_comp_expiry: str
    disability_expiry: str


@api_router.put("/admin/company/insurance/manual")
async def set_admin_company_insurance_manual(
    body: ManualInsuranceRequest,
    current_user=Depends(get_admin_user),
):
    """
    Admin manually sets the 3 required insurance expiry dates for their company.
    Replaces the BIS-scraped records, since BIS is blocked by Akamai.

    Dates must be parseable (MM/DD/YYYY preferred), must be in the future,
    and must be within 5 years from today.
    """
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company associated with your account")

    company = await db.companies.find_one({"_id": to_query_id(company_id), "is_deleted": {"$ne": True}})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    from dateutil import parser as dateparser

    field_specs = [
        ("general_liability", "General Liability", body.general_liability_expiry),
        ("workers_comp",      "Workers' Comp",     body.workers_comp_expiry),
        ("disability",        "Disability",        body.disability_expiry),
    ]

    now = datetime.now(timezone.utc)
    max_future = now + timedelta(days=365 * 5)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    parsed = []
    for ins_type, label, raw in field_specs:
        raw = (raw or "").strip()
        if not raw:
            raise HTTPException(
                status_code=422,
                detail=f"{label} expiration date is required.",
            )
        try:
            dt = dateparser.parse(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(
                status_code=422,
                detail=f"{label} date '{raw}' could not be parsed. Use MM/DD/YYYY.",
            )

        if dt < today_midnight:
            raise HTTPException(
                status_code=422,
                detail=f"{label} expiration is in the past ({raw}). Enter a current or future date.",
            )
        if dt > max_future:
            raise HTTPException(
                status_code=422,
                detail=f"{label} expiration is more than 5 years out ({raw}). Double-check the year.",
            )

        parsed.append((ins_type, label, dt))

    today_str = now.strftime("%m/%d/%Y")
    records = []
    for ins_type, label, dt in parsed:
        records.append({
            "insurance_type": ins_type,
            "carrier_name":   None,
            "policy_number":  None,
            "effective_date": today_str,
            "expiration_date": dt.strftime("%m/%d/%Y"),
            "is_current":     True,
            "source":         "manual_entry",
        })

    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {
            "gc_insurance_records": records,
            "gc_last_verified": now,
            "updated_at": now,
        }},
    )

    # Audit
    try:
        await audit_log(
            "insurance_manual_update",
            str(current_user.get("id", "")),
            "company",
            str(company_id),
            {"records": records},
        )
    except Exception as e:
        logger.warning(f"audit_log(insurance_manual_update) failed: {e}")

    company = await db.companies.find_one({"_id": to_query_id(company_id)})
    return {
        "company_id":            str(company["_id"]),
        "company_name":          company.get("name"),
        "gc_license_number":     company.get("gc_license_number"),
        "gc_business_name":      company.get("gc_business_name"),
        "gc_licensee_name":      company.get("gc_licensee_name"),
        "gc_license_status":     company.get("gc_license_status"),
        "gc_license_expiration": company.get("gc_license_expiration"),
        "gc_insurance_records":  company.get("gc_insurance_records", []),
        "gc_resolved":           company.get("gc_resolved", False),
        "gc_last_verified":      company.get("gc_last_verified"),
    }


# ==================== COI UPLOAD + OCR (Step 7) ====================
# Admin uploads a Certificate of Insurance PDF; backend OCRs via Qwen,
# stores the original in R2 with 7-year retention, returns the parsed
# fields for admin to review before commit.
#
# Two-phase: upload returns a draft, confirm commits to gc_insurance_records.
# Drafts auto-expire after 24h (TTL index in startup).
#
# GC-licensed companies only; HIC and unlicensed companies don't see
# the upload UI (per plan §5.1) and are rejected here as defense in depth.

class CoiConfirmRequest(BaseModel):
    draft_id: str
    insurance_type: str           # general_liability | workers_comp | disability
    carrier_name: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[str] = None    # MM/DD/YYYY
    expiration_date: Optional[str] = None   # MM/DD/YYYY


@api_router.post("/admin/company/insurance/upload-coi")
async def admin_upload_coi(
    insurance_type: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_admin_user),
):
    """Phase 1 of COI upload — validate, store, OCR, return draft.

    Idempotent on file bytes via SHA-256: re-uploading the same PDF
    yields the same R2 key (R2 dedupes naturally) and re-uses the
    cached OCR result if one exists for this (company, sha) pair —
    no duplicate Qwen API charge.
    """
    from lib.coi_storage import (
        validate_pdf_bytes,
        coi_pdf_key,
        coi_preview_key,
        render_first_page_jpeg,
        upload_coi_objects,
        ALLOWED_INSURANCE_TYPES,
        CoiValidationError,
    )
    from lib.coi_ocr import extract_coi_fields, OcrConfigError

    if insurance_type not in ALLOWED_INSURANCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"insurance_type must be one of {sorted(ALLOWED_INSURANCE_TYPES)}",
        )

    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company associated with your account")

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Defense in depth: HIC / unlicensed companies don't get COI UI in
    # the frontend, but reject here too in case the endpoint is hit
    # directly. GC license is the only one DOB tracks insurance for.
    if (company.get("license_class") or "GC_LICENSED") != "GC_LICENSED":
        raise HTTPException(
            status_code=409,
            detail=(
                "COI upload is for GC-licensed companies only. "
                "HIC license insurance is managed through DCWP, not LeveLog."
            ),
        )

    # Read + validate. Synchronous bytes work runs in executor so the
    # event loop doesn't block on a 300KB upload.
    pdf_bytes = await file.read()
    try:
        validated = await asyncio.to_thread(
            validate_pdf_bytes,
            pdf_bytes,
            expected_content_type=file.content_type or "",
        )
    except CoiValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Idempotency: if we already have a draft / confirmed record for
    # this exact file, return the existing OCR result. Same sha →
    # same parsed fields, no Qwen charge.
    sha = validated.sha256_hex
    pdf_key = coi_pdf_key(str(company_id), insurance_type, sha)
    preview_key = coi_preview_key(str(company_id), insurance_type, sha)

    existing_draft = await db.coi_ocr_drafts.find_one({
        "company_id": str(company_id),
        "sha256": sha,
        "insurance_type": insurance_type,
    })
    if existing_draft:
        return {
            "draft_id": str(existing_draft["_id"]),
            "pdf_url": existing_draft.get("pdf_url"),
            "preview_url": existing_draft.get("preview_url"),
            "parsed": existing_draft.get("ocr_result", {}),
            "cached": True,
        }

    # Render first page → JPEG. Run in executor (poppler is blocking).
    try:
        preview_bytes = await asyncio.to_thread(render_first_page_jpeg, pdf_bytes)
    except CoiValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Upload PDF + preview to R2. Same path runs in executor.
    try:
        urls = await asyncio.to_thread(
            upload_coi_objects,
            pdf_bytes, preview_bytes,
            pdf_key, preview_key,
            sha256_hex=sha,
            insurance_type=insurance_type,
            company_id=str(company_id),
        )
    except RuntimeError as e:
        # R2 not configured — surface as 503, not a 500.
        raise HTTPException(status_code=503, detail=str(e))

    # OCR — async-native, no executor needed.
    try:
        ocr_result = await extract_coi_fields(
            preview_bytes,
            insurance_type=insurance_type,
        )
    except OcrConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # OCR failed but we have the PDF stored. Return a draft with
        # empty parsed values so admin can manually fill in.
        logger.error(f"COI OCR failed for company={company_id} sha={sha[:16]}: {type(e).__name__}")
        from lib.coi_ocr import CoiOcrResult
        ocr_result = CoiOcrResult(min_confidence=0.0)

    parsed_payload = ocr_result.as_admin_payload()

    # Persist as draft. Confirmed-in-place via the confirm endpoint.
    now = datetime.now(timezone.utc)
    draft_doc = {
        "company_id": str(company_id),
        "user_id": str(current_user.get("id", "")),
        "sha256": sha,
        "insurance_type": insurance_type,
        "size_bytes": validated.size_bytes,
        "page_count": validated.page_count,
        "pdf_key": pdf_key,
        "preview_key": preview_key,
        "pdf_url": urls["pdf_url"],
        "preview_url": urls["preview_url"],
        "ocr_result": parsed_payload,
        "created_at": now,
    }
    insert_result = await db.coi_ocr_drafts.insert_one(draft_doc)

    # Audit log: never echoes parsed values, only metadata. PII stays
    # in coi_ocr_drafts and only flows to the confirm response.
    try:
        await audit_log(
            "coi_uploaded",
            str(current_user.get("id", "")),
            "company",
            str(company_id),
            {
                "insurance_type": insurance_type,
                "sha256": sha,
                "size_bytes": validated.size_bytes,
                "page_count": validated.page_count,
                "min_confidence": parsed_payload.get("min_confidence"),
                "auto_accept": parsed_payload.get("auto_accept"),
                "draft_id": str(insert_result.inserted_id),
            },
        )
    except Exception as e:
        logger.warning(f"audit_log(coi_uploaded) failed: {e}")

    return {
        "draft_id": str(insert_result.inserted_id),
        "pdf_url": urls["pdf_url"],
        "preview_url": urls["preview_url"],
        "parsed": parsed_payload,
        "cached": False,
    }


@api_router.put("/admin/company/insurance/upload-coi/confirm")
async def admin_confirm_coi(
    body: CoiConfirmRequest,
    current_user=Depends(get_admin_user),
):
    """Phase 2 — admin commits the (possibly edited) parsed fields to
    gc_insurance_records. Replaces any existing record of the same
    insurance_type on this company; the prior record's PDF stays in
    R2 (7-year retention metadata) and is referenced from the audit
    log entry so we don't lose the audit trail."""
    from lib.coi_storage import ALLOWED_INSURANCE_TYPES

    if body.insurance_type not in ALLOWED_INSURANCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"insurance_type must be one of {sorted(ALLOWED_INSURANCE_TYPES)}",
        )

    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company associated with your account")

    draft = await db.coi_ocr_drafts.find_one({"_id": to_query_id(body.draft_id)})
    if not draft:
        raise HTTPException(status_code=404, detail="COI draft not found or expired")
    if draft.get("company_id") != str(company_id):
        # Don't reveal cross-tenant existence — generic 404.
        raise HTTPException(status_code=404, detail="COI draft not found or expired")
    if draft.get("insurance_type") != body.insurance_type:
        raise HTTPException(
            status_code=400,
            detail="Draft insurance_type does not match confirm body. Re-upload.",
        )

    # Build the new InsuranceRecord. Pulled values from the confirm
    # request (admin may have edited the OCR output); R2 URL + OCR
    # confidence carry over from the draft so audit trail is preserved.
    now = datetime.now(timezone.utc)
    parsed = draft.get("ocr_result") or {}
    new_record = {
        "insurance_type":      body.insurance_type,
        "carrier_name":        body.carrier_name,
        "policy_number":       body.policy_number,
        "effective_date":      body.effective_date,
        "expiration_date":     body.expiration_date,
        "is_current":          True,
        "source":              "coi_ocr",
        "coi_pdf_url":         draft.get("pdf_url"),
        "ocr_confidence":      parsed.get("min_confidence"),
        "dob_now_verified_at": None,
        "dob_now_discrepancy": False,
    }

    company = await db.companies.find_one(
        {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Replace any existing record of this type. Keep all other types untouched.
    existing_records = company.get("gc_insurance_records") or []
    prior_of_type = next(
        (r for r in existing_records
         if isinstance(r, dict) and r.get("insurance_type") == body.insurance_type),
        None,
    )
    new_records = [
        r for r in existing_records
        if not (isinstance(r, dict) and r.get("insurance_type") == body.insurance_type)
    ]
    new_records.append(new_record)

    await db.companies.update_one(
        {"_id": to_query_id(company_id)},
        {"$set": {"gc_insurance_records": new_records, "updated_at": now}},
    )

    # Cleanup: drop the draft now that it's been committed.
    await db.coi_ocr_drafts.delete_one({"_id": to_query_id(body.draft_id)})

    try:
        await audit_log(
            "coi_confirmed",
            str(current_user.get("id", "")),
            "company",
            str(company_id),
            {
                "insurance_type":   body.insurance_type,
                "draft_id":         body.draft_id,
                "ocr_confidence":   parsed.get("min_confidence"),
                "auto_accept":      parsed.get("auto_accept"),
                "edited_by_admin":  _coi_diff(parsed, body),
                "prior_record_url": (prior_of_type or {}).get("coi_pdf_url"),
                "new_record_url":   draft.get("pdf_url"),
            },
        )
    except Exception as e:
        logger.warning(f"audit_log(coi_confirmed) failed: {e}")

    return {
        "ok": True,
        "insurance_type": body.insurance_type,
        "carrier_name":   new_record["carrier_name"],
        "expiration_date": new_record["expiration_date"],
        "source":         new_record["source"],
        "ocr_confidence": new_record["ocr_confidence"],
        "coi_pdf_url":    new_record["coi_pdf_url"],
    }


def _coi_diff(parsed: dict, body: CoiConfirmRequest) -> list:
    """Identify which fields the admin edited away from the OCR result.
    Returned in the audit log so we can post-hoc audit OCR accuracy:
    if admins are routinely overriding `policy_number`, the prompt
    needs work. Field VALUES are intentionally NOT logged — only the
    list of which fields were changed."""
    edited = []
    for f in ("carrier_name", "policy_number", "effective_date", "expiration_date"):
        if (parsed.get(f) or "") != (getattr(body, f) or ""):
            edited.append(f)
    return edited


# ==================== END COI UPLOAD + OCR ====================


class CreateAdminRequest(BaseModel):
    name: str
    email: str
    password: str
    company_name: str
    phone: Optional[str] = None

@api_router.post("/owner/admins")
async def create_admin_with_company(admin_data: CreateAdminRequest, current_user = Depends(get_current_user)):
    """Create admin account with company (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    # Check if email exists
    existing_user = await db.users.find_one({"email": admin_data.email, "is_deleted": {"$ne": True}})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create company first
    company_name = admin_data.company_name
    existing_company = await db.companies.find_one({"name": company_name, "is_deleted": {"$ne": True}})
    
    now = datetime.now(timezone.utc)
    
    if existing_company:
        company_id = str(existing_company["_id"])
    else:
        company_doc = {
            "name": company_name,
            "created_at": now,
            "updated_at": now,
            "created_by": current_user.get("id"),
            "is_deleted": False
        }
        company_result = await db.companies.insert_one(company_doc)
        company_id = str(company_result.inserted_id)
    
    # Normalize and collision-check phone (if provided)
    new_phone = ""
    if admin_data.phone and admin_data.phone.strip():
        new_phone = normalize_phone(admin_data.phone.strip())
        collision = await db.users.find_one({
            "company_id": company_id,
            "phone": new_phone,
            "is_deleted": {"$ne": True},
        })
        if collision:
            raise HTTPException(
                status_code=409,
                detail="This phone number is already in use by another user in this company.",
            )

    # Create admin user
    user_doc = {
        "email": admin_data.email,
        "password": hash_password(admin_data.password),
        "name": admin_data.name,
        "role": "admin",
        "company_id": company_id,
        "company_name": company_name,
        "created_at": now,
        "updated_at": now,
        "assigned_projects": [],
        "is_deleted": False
    }
    if new_phone:
        user_doc["phone"] = new_phone

    user_result = await db.users.insert_one(user_doc)
    new_user_id = str(user_result.inserted_id)

    # If company WhatsApp is active, upsert the new admin into whatsapp_contacts.
    # If not active, whatsapp_activate's auto-population sweep will pick them up later.
    if new_phone:
        try:
            wa_config = await db.whatsapp_config.find_one({"company_id": company_id})
            if wa_config and wa_config.get("is_active"):
                await db.whatsapp_contacts.update_one(
                    {"company_id": company_id, "phone": new_phone},
                    {"$set": {
                        "company_id": company_id,
                        "phone": new_phone,
                        "user_id": new_user_id,
                        "display_name": admin_data.name,
                    }},
                    upsert=True,
                )
        except Exception as e:
            logger.warning(f"whatsapp_contacts upsert failed for new admin {new_user_id}: {e}")

    return {
        "id": new_user_id,
        "email": admin_data.email,
        "name": admin_data.name,
        "phone": new_phone or None,
        "company_id": company_id,
        "company_name": company_name,
        "role": "admin",
        "message": "Admin account created successfully"
    }

@api_router.get("/owner/admins")
async def get_admin_accounts(current_user = Depends(get_current_user)):
    """Get all admin accounts (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    admins = await db.users.find({"role": "admin", "is_deleted": {"$ne": True}}, {"password": 0}).to_list(200)
    return serialize_list(admins)

@api_router.delete("/owner/admins/{admin_id}")
async def delete_admin_account(admin_id: str, current_user = Depends(get_current_user)):
    """Delete admin account (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    # Soft delete
    result = await db.users.update_one(
        {"_id": to_query_id(admin_id), "role": "admin"},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    return {"message": "Admin account deleted successfully"}

@api_router.put("/owner/admins/{admin_id}")
async def update_admin_account(admin_id: str, admin_data: dict, current_user = Depends(get_current_user)):
    """Update admin account (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    update_fields = {}
    if "name" in admin_data:
        update_fields["name"] = admin_data["name"]
    if "email" in admin_data:
        update_fields["email"] = admin_data["email"]
    if "company_id" in admin_data:
        update_fields["company_id"] = admin_data["company_id"]
    if "password" in admin_data and admin_data["password"]:
        update_fields["password"] = hash_password(admin_data["password"])
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_fields["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.users.update_one(
        {"_id": to_query_id(admin_id), "role": "admin", "is_deleted": {"$ne": True}},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    admin = await db.users.find_one({"_id": to_query_id(admin_id)})
    return serialize_id(admin)

@api_router.post("/admin/migrate-company-data")
async def migrate_company_data(data: dict, current_user = Depends(get_current_user)):
    """Migrate admin data to companies (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    assignments = data.get("assignments", [])
    results = []
    
    for assignment in assignments:
        admin_email = assignment.get("admin_email")
        company_id = assignment.get("company_id")
        
        if not admin_email or not company_id:
            continue
        
        # Update admin's company_id
        await db.users.update_one(
            {"email": admin_email, "is_deleted": {"$ne": True}},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        
        # Find admin
        admin = await db.users.find_one({"email": admin_email})
        if not admin:
            continue
        
        admin_id = str(admin["_id"])
        
        # Migrate projects created by this admin
        await db.projects.update_many(
            {"created_by": admin_id, "company_id": {"$exists": False}},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        await db.projects.update_many(
            {"created_by": admin_id, "company_id": None},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        
        # Migrate workers
        await db.workers.update_many(
            {"created_by": admin_id, "company_id": {"$exists": False}},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        await db.workers.update_many(
            {"created_by": admin_id, "company_id": None},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        
        # Migrate checkins
        await db.checkins.update_many(
            {"created_by": admin_id, "company_id": {"$exists": False}},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        
        # Migrate daily logs
        await db.daily_logs.update_many(
            {"created_by": admin_id, "company_id": {"$exists": False}},
            {"$set": {"company_id": company_id, "updated_at": datetime.now(timezone.utc)}}
        )
        
        results.append({"admin_email": admin_email, "company_id": company_id, "status": "migrated"})
    
    return {"message": "Migration completed", "results": results}

# ==================== PROJECTS ====================

@api_router.get("/projects")
async def get_projects(
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    result = await paginated_query(db.projects, query, sort_field="name", sort_dir=1, limit=limit, skip=skip)
    return result

@api_router.post("/projects", response_model=ProjectResponse)
async def create_project(project_data: ProjectCreate, admin = Depends(get_admin_user)):
    project_dict = project_data.model_dump()

    # MR.5+ — third instance of Pydantic-default-not-protecting-writes.
    # ProjectCreate.gates: Optional[List[ProjectGate]] = None carries
    # through model_dump() as {"gates": None}. ProjectResponse below
    # rejects None for its non-Optional List type. Forward-init now
    # so the Mongo insert is shape-stable AND the response succeeds.
    # Same fix shape as MR.10's _lift_credentials_field +
    # migrate_filing_reps_credentials_init.py.
    _lift_project_list_defaults(project_dict)

    if project_dict.get("address") and (not project_dict.get("name") or project_dict["name"] == project_dict["address"]):
        project_dict["name"] = project_dict["address"]
    if project_dict.get("name") and not project_dict.get("address"):
        project_dict["address"] = project_dict.get("location") or project_dict["name"]
    
    now = datetime.now(timezone.utc)
    project_dict["created_at"] = now
    project_dict["updated_at"] = now
    project_dict["nfc_tags"] = []
    project_dict["dropbox_enabled"] = False
    project_dict["dropbox_folder"] = None
    project_dict["is_deleted"] = False
    
    # IMPORTANT: Auto-inject company_id from admin
    project_dict["company_id"] = admin.get("company_id")
    project_dict["company_name"] = admin.get("company_name")
    project_dict["admin_id"] = admin.get("id")
    
    # ── DOB: Auto-resolve NYC BIN + canonical address from address ──
    # Field rename note (2026-04-27 step 9.1): nyc_bbl → bbl. The
    # legacy nyc_bbl key is no longer written by new project creation.
    # Existing prod docs still carry nyc_bbl; the step 9.1 migration
    # copies their values into the new `bbl` field. Cleanup commit
    # drops the legacy nyc_bbl reads after deploy verification.
    project_dict["nyc_bin"] = None
    project_dict["bbl"] = None
    project_dict["bbl_source"] = None
    project_dict["bbl_last_synced"] = None
    project_dict["track_dob_status"] = False

    address_for_bin = project_dict.get("address") or project_dict.get("location") or ""
    if address_for_bin:
        bin_result = await fetch_nyc_bin_from_address(address_for_bin)
        project_dict["nyc_bin"] = bin_result["nyc_bin"]
        if bin_result.get("bbl"):
            project_dict["bbl"] = bin_result["bbl"]
            project_dict["bbl_source"] = "address_lookup_at_creation"
            project_dict["bbl_last_synced"] = now
        project_dict["track_dob_status"] = bin_result["track_dob_status"]

        # Upgrade the project's address to GeoSearch's canonical form
        # (e.g. "852 E 176" → "852 EAST 176 STREET, Bronx, NY, USA").
        # This is critical: downstream address-based DOB Socrata
        # queries LIKE-match DOB's canonical street names, which use
        # "EAST" not "E" and include "STREET". Without this upgrade,
        # "852 E 176" finds nothing even though the building has
        # permits filed under "852 EAST 176 STREET".
        normalized = bin_result.get("normalized_address")
        if normalized and normalized != project_dict.get("address"):
            logger.info(
                f"Normalized address '{project_dict.get('address')}' → "
                f"'{normalized}'"
            )
            project_dict["address"] = normalized

        if bin_result["nyc_bin"]:
            logger.info(
                f"Auto-resolved BIN {bin_result['nyc_bin']} for project "
                f"'{project_dict.get('name')}'"
            )
        else:
            logger.info(
                f"No real BIN resolved for project "
                f"'{project_dict.get('name')}' — address-based DOB "
                f"lookups will be used."
            )
    # ── END DOB ──

    # ── Project classification ──
    suggested = classify_project(
        project_dict.get("building_stories"),
        project_dict.get("footprint_sqft"),
        project_dict.get("has_full_demolition", False),
        project_dict.get("demolition_stories"),
        project_dict.get("building_height"),
    )
    project_dict["suggested_class"] = suggested
    override = project_dict.get("project_class")
    if override and override in VALID_PROJECT_CLASSES:
        project_dict["project_class"] = override
        if override != suggested:
            await db.compliance_alerts.insert_one({
                "type": "classification_override",
                "project_name": project_dict.get("name"),
                "suggested_class": suggested,
                "override_class": override,
                "admin_id": str(admin.get("_id", admin.get("id", ""))),
                "timestamp": now,
                "resolved": False,
            })
    else:
        project_dict["project_class"] = suggested

    project_dict["required_logbooks"] = get_required_logbooks(project_dict["project_class"], project_dict)
    # ── END classification ──

    result = await db.projects.insert_one(project_dict)
    project_dict["id"] = str(result.inserted_id)

    await audit_log("project_create", str(admin.get("_id", admin.get("id", ""))), "project", str(result.inserted_id), {
        "name": project_dict.get("name"), "address": project_dict.get("address"),
        "project_class": project_dict.get("project_class"), "suggested_class": suggested,
    })

    # Defense in depth — the lift above already covered model_dump's
    # None values, but if any code path between then and now wrote
    # None back into project_dict (e.g. a future migration helper),
    # we'd still want the response to construct cleanly.
    _lift_project_list_defaults(project_dict)

    return ProjectResponse(**project_dict)

@api_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check company access
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    # MR.5+ — defensive lift for legacy docs that have list fields
    # set to None. Three production docs in this state today (the
    # operator's failed create attempts before this commit landed);
    # without this lift, GET on any of them 500s.
    _lift_project_list_defaults(project)

    return ProjectResponse(**serialize_id(project))

@api_router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, project_data: ProjectUpdate, admin = Depends(get_admin_user)):
    update_data = {k: v for k, v in project_data.model_dump().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    # Normalize email list to lowercase if present
    if "report_email_list" in update_data and update_data["report_email_list"] is not None:
        update_data["report_email_list"] = [e.lower() for e in update_data["report_email_list"]]

    # Re-classify when classification-relevant fields change
    classification_fields = {"building_stories", "building_height", "footprint_sqft", "has_full_demolition", "demolition_stories", "project_class"}
    if classification_fields & update_data.keys():
        existing = await db.projects.find_one({"_id": to_query_id(project_id)})
        if existing:
            merged = {**existing, **update_data}
            suggested = classify_project(
                merged.get("building_stories"),
                merged.get("footprint_sqft"),
                merged.get("has_full_demolition", False),
                merged.get("demolition_stories"),
                merged.get("building_height"),
            )
            update_data["suggested_class"] = suggested
            override = update_data.get("project_class")
            if override and override in VALID_PROJECT_CLASSES:
                update_data["project_class"] = override
            else:
                update_data["project_class"] = suggested
            update_data["required_logbooks"] = get_required_logbooks(update_data["project_class"], merged)

    result = await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")

    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    # MR.5+ — same defensive lift as get_project. Update endpoints
    # don't currently set list fields to None (the existing code
    # filters None values out via dict-comprehension before $set),
    # but the read-back can still pull a legacy doc whose pre-update
    # state had None lists.
    _lift_project_list_defaults(project)
    return ProjectResponse(**serialize_id(project))

@api_router.get("/projects/{project_id}/required-logbooks")
async def get_project_required_logbooks(project_id: str, current_user = Depends(get_current_user)):
    """Return the required logbook types for this project based on its classification."""
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    project_class = project.get("project_class", "regular")
    required = get_required_logbooks(project_class, project)
    return {"project_id": project_id, "project_class": project_class, "required_logbooks": required}

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, admin = Depends(get_admin_user)):
    # Verify project exists and user has access
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    # Hard delete all DOB logs for this project
    dob_result = await db.dob_logs.delete_many({"project_id": project_id})
    logger.info(f"Deleted {dob_result.deleted_count} dob_logs for project {project_id}")

    # Soft delete the project
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )

    await audit_log("project_delete", str(admin.get("_id", admin.get("id", ""))), "project", project_id, {
        "name": project.get("name"), "dob_logs_deleted": dob_result.deleted_count,
    })

    return {"message": "Project deleted successfully", "dob_logs_deleted": dob_result.deleted_count}

# ==================== PROJECT NFC TAGS ====================

@api_router.get("/projects/{project_id}/nfc-tags")
async def get_project_nfc_tags(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.get("nfc_tags", [])

@api_router.post("/projects/{project_id}/nfc-tags")
async def add_nfc_tag_to_project(project_id: str, tag_data: NfcTagCreate, admin = Depends(get_admin_user)):
    # Get project and verify company access
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    now = datetime.now(timezone.utc)
    
    # Check if this tag_id exists ANYWHERE (including soft-deleted) due to unique index on tag_id
    existing_tag = await db.nfc_tags.find_one({"tag_id": tag_data.tag_id})
    
    if existing_tag:
        old_project_id = existing_tag.get("project_id")
        if old_project_id and old_project_id != project_id and not existing_tag.get("is_deleted"):
            logger.info(f"NFC tag {tag_data.tag_id} was registered to project {old_project_id}, reassigning to {project_id}")
            await db.projects.update_one(
                {"_id": to_query_id(old_project_id)},
                {
                    "$pull": {"nfc_tags": {"tag_id": tag_data.tag_id}},
                    "$set": {"updated_at": now}
                }
            )
        
        # Update the existing document in-place (avoids unique index conflict)
        await db.nfc_tags.update_one(
            {"_id": existing_tag["_id"]},
            {"$set": {
                "project_id": project_id,
                "location_description": tag_data.location_description,
                "updated_at": now,
                "admin_id": admin["id"],
                "company_id": project.get("company_id"),
                "status": "active",
                "is_deleted": False
            }}
        )
    else:
        # Brand new tag - safe to insert
        nfc_tag = {
            "tag_id": tag_data.tag_id,
            "project_id": project_id,
            "location_description": tag_data.location_description,
            "created_at": now,
            "updated_at": now,
            "admin_id": admin["id"],
            "company_id": project.get("company_id"),
            "status": "active",
            "is_deleted": False
        }
        await db.nfc_tags.insert_one(nfc_tag)
    
    # Also update project's nfc_tags array
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {
            "$push": {"nfc_tags": {"tag_id": tag_data.tag_id, "location": tag_data.location_description}},
            "$set": {"updated_at": now}
        }
    )
    
    # Return success - frontend will refetch project data via fetchData()
    logger.info(f"NFC tag {tag_data.tag_id} registered to project {project_id}")
    return {
        "message": "NFC tag registered successfully",
        "tag_id": tag_data.tag_id,
    }

@api_router.delete("/projects/{project_id}/nfc-tags/{tag_id}")
async def remove_nfc_tag_from_project(project_id: str, tag_id: str, admin = Depends(get_admin_user)):
    now = datetime.now(timezone.utc)
    
    # Soft delete from nfc_tags collection
    await db.nfc_tags.update_one(
        {"tag_id": tag_id, "project_id": project_id},
        {"$set": {"is_deleted": True, "updated_at": now}}
    )
    
    # Remove from project's nfc_tags array
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {
            "$pull": {"nfc_tags": {"tag_id": tag_id}},
            "$set": {"updated_at": now}
        }
    )
    return {"message": "NFC tag removed successfully"}

# ==================== NFC TAG INFO (PUBLIC) ====================

@api_router.get("/nfc-tags/{tag_id}/info", response_model=NfcTagInfo)
async def get_nfc_tag_info(tag_id: str):
    """Public endpoint - no auth required. Used by workers scanning NFC tags."""
    tag = await db.nfc_tags.find_one({"tag_id": tag_id, "status": "active", "is_deleted": {"$ne": True}})
    if not tag:
        raise HTTPException(status_code=404, detail="NFC tag not found or inactive")
    
    # Get project info
    project = await db.projects.find_one({"_id": to_query_id(tag["project_id"]), "is_deleted": {"$ne": True}})
    
    return NfcTagInfo(
        tag_id=tag["tag_id"],
        project_id=tag["project_id"],
        project_name=project.get("name", "Unknown Project") if project else "Unknown Project",
        location_description=tag.get("location_description", "Check-In Point"),
        company_name=project.get("company_name") if project else None
    )

@api_router.get("/checkin/{project_id}/{tag_id}/info")
async def get_checkin_info(project_id: str, tag_id: str):
    """Public endpoint - no auth required"""
    try:
        tag = await db.nfc_tags.find_one({
            "tag_id": tag_id,
            "project_id": project_id,
            "status": "active",
            "is_deleted": {"$ne": True}
        })

        if not tag:
            raise HTTPException(status_code=404, detail="Invalid check-in link")

        project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Per-project trade/company assignments. Admins set these via
        # PUT /api/projects/{id} with trade_assignments: [{trade, company}].
        # Sanitize + drop any rows missing either field.
        raw_assignments = project.get("trade_assignments") or []
        assignments: List[Dict[str, str]] = []
        for row in raw_assignments:
            if not isinstance(row, dict):
                continue
            t = str(row.get("trade") or "").strip()
            c = str(row.get("company") or "").strip()
            if t and c:
                assignments.append({"trade": t, "company": c})

        return {
            "project_id": project_id,
            "project_name": project.get("name", "Unknown Project"),
            "location": tag.get("location_description", "Check-In Point"),
            "tag_id": tag_id,
            "company_name": project.get("company_name"),
            "trade_assignments": assignments,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@api_router.post("/checkin/upload-osha")
async def upload_osha_card(file_data: dict, request: Request):
    """OCR an OSHA/SST card photo using the Qwen2.5-VL vision model.

    PUBLIC endpoint — the NFC check-in flow is unauthenticated (workers
    tap a sticker, land on a public HTML page, no login). Previously
    this was gated behind `Depends(get_current_user)`, which made every
    photo upload 401 and surface as "Could not read card" in the UI.

    Rate-limited via the shared check-in limiter to prevent abuse of
    the paid vision API.

    Mirrors the httpx+Together shape used by _qwen_visual_qa(). Input is
    a base64 image + content_type; output is the same {name, sst_number,
    issued, expiration, box_2d} JSON the frontend already consumes.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not checkin_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    import httpx
    import json as json_mod

    if not QWEN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Vision API not configured. Set QWEN_API_KEY.",
        )

    image_b64 = file_data.get("image")
    content_type = file_data.get("content_type", "image/jpeg")

    if not image_b64:
        raise HTTPException(status_code=400, detail="No image provided")

    # Strip data URL prefix if present
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    image_url = f"data:{content_type};base64,{image_b64}"

    extraction_prompt = (
        "Extract the following from this SST/OSHA safety training card image. "
        "Return ONLY valid JSON, no markdown:\n"
        "{\"name\": \"full name on card\", "
        "\"sst_number\": \"the ID number or card number shown on the card\", "
        "\"issued\": \"issued date if visible\", "
        "\"expiration\": \"expiration date if visible\", "
        "\"box_2d\": [ymin, xmin, ymax, xmax]}\n"
        "If a field is not visible, set it to null. 'box_2d' should be the "
        "normalized coordinates (0-1000) tightly framing the card. Return "
        "the JSON object only."
    )

    text = ""
    try:
        async with ServerHttpClient(timeout=60.0) as client_http:
            resp = await client_http.post(
                f"{QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": QWEN_MODEL,
                    "max_tokens": 500,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": image_url}},
                            {"type": "text", "text": extraction_prompt},
                        ],
                    }],
                },
            )
            if resp.status_code != 200:
                logger.error(
                    f"Qwen vision error {resp.status_code}: {resp.text[:300]}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Vision API error: {resp.status_code}",
                )

            result = resp.json()
            raw_text = result["choices"][0]["message"]["content"]

        # Parse JSON from response
        text = (raw_text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        extracted = json_mod.loads(text)
        return extracted

    except json_mod.JSONDecodeError:
        return {
            "name":       None,
            "sst_number": None,
            "issued":     None,
            "expiration": None,
            "raw_text":   text,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OSHA OCR error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR processing failed: {str(e)}",
        )

@api_router.get("/checkin/{project_id}/companies")
async def get_project_companies(project_id: str):
    """Public endpoint - get list of companies/subcontractors for a project's company"""
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = project.get("company_id")
    
    # Get subcontractors for this company
    subs = await db.subcontractors.find(
        {"company_id": company_id, "is_deleted": {"$ne": True}},
        {"company_name": 1, "trade": 1}
    ).to_list(500)
    
    companies = [{"name": s.get("company_name"), "trade": s.get("trade")} for s in subs]
    
    # Also add the main company name
    if company_id:
        main_company = await db.companies.find_one({"_id": to_query_id(company_id)})
        if main_company:
            companies.insert(0, {"name": main_company.get("name"), "trade": "General Contractor"})
    
    return companies
    
@api_router.post("/checkin/register-and-checkin")
async def register_and_checkin(data: dict):
    """Public endpoint - full registration with OSHA + orientation + check-in in one call"""
    project_id = data.get("project_id")
    tag_id = data.get("tag_id")
    name = data.get("name")
    phone = data.get("phone")
    trade = data.get("trade")
    company = data.get("company")
    osha_card_image = data.get("osha_card_image")  # base64
    osha_data = data.get("osha_data")  # OCR results dict
    osha_number = data.get("osha_number")
    safety_orientation = data.get("safety_orientation")  # dict of checked items
    signature = data.get("signature")  # base64 PNG
    language_provided = data.get("language_provided", "en")  # "en" or "es" auto-captured from NFC
    device_info = data.get("device_info")  # FingerprintJS data from checkin.html
	
    if not all([project_id, tag_id, name, company]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    # Format phone number
    if phone:
        phone = format_phone(phone)

    # Verify tag + project
    tag = await db.nfc_tags.find_one({
        "tag_id": tag_id,
        "project_id": project_id,
        "status": "active",
        "is_deleted": {"$ne": True}
    })
    if not tag:
        raise HTTPException(status_code=404, detail="Invalid check-in point")

    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Strict-roster enforcement: the submitted {trade, company} MUST match
    # one of the admin-configured trade_assignments for this project. The
    # frontend already forces a dropdown pick, but a modified client could
    # still POST arbitrary values — reject them here so the workforce list
    # matches who's actually been assigned to the project.
    raw_assignments = project.get("trade_assignments") or []
    allowed_pairs = set()
    for row in raw_assignments:
        if not isinstance(row, dict):
            continue
        t = str(row.get("trade") or "").strip()
        c = str(row.get("company") or "").strip()
        if t and c:
            allowed_pairs.add((t, c))
    submitted_pair = ((trade or "").strip(), (company or "").strip())
    if not allowed_pairs:
        raise HTTPException(
            status_code=409,
            detail="This project has no trades configured. Ask your site admin to add trades before workers can check in.",
        )
    if submitted_pair not in allowed_pairs:
        raise HTTPException(
            status_code=400,
            detail="Selected trade and company are not assigned to this project.",
        )
    
    now = datetime.now(timezone.utc)
    admin_id = project.get("admin_id")
    company_id = project.get("company_id")
    
    # Find or create worker by phone (or by OSHA number if no phone)
    worker = None
    if phone:
        raw_digits = ''.join(c for c in phone if c.isdigit())
        formatted = format_phone(raw_digits)
        worker = await db.workers.find_one({"phone": {"$in": [phone, raw_digits, formatted]}, "is_deleted": {"$ne": True}})
    if not worker and osha_number:
        worker = await db.workers.find_one({"osha_number": osha_number, "is_deleted": {"$ne": True}})
    
    if not worker:
        # Create new worker with full data
        worker = {
            "name": name,
            "phone": phone or "",
            "trade": trade or "",
            "company": company,
            "osha_number": osha_number or "",
            "osha_data": osha_data,
            "osha_card_image": osha_card_image,
            "signature": signature,
            "safety_orientations": [{
                "project_id": project_id,
                "project_name": project.get("name"),
                "checklist": safety_orientation,
                "completed_at": now.isoformat(),
            }] if safety_orientation else [],
            "certifications": [],
            "admin_id": admin_id,
            "company_id": company_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        }
        result = await db.workers.insert_one(worker)
        worker["_id"] = result.inserted_id
    else:
        # Update existing worker with new OSHA data if provided
        update_fields = {"updated_at": now}
        if osha_card_image and not worker.get("osha_card_image"):
            update_fields["osha_card_image"] = osha_card_image
        if osha_data:
            update_fields["osha_data"] = osha_data
        if osha_number:
            update_fields["osha_number"] = osha_number
        if name:
            update_fields["name"] = name
        if company:
            update_fields["company"] = company
        if trade:
            update_fields["trade"] = trade
        
        # Append safety orientation for this project if not already done
        if safety_orientation:
            existing_orientations = worker.get("safety_orientations", [])
            already_oriented = any(o.get("project_id") == project_id for o in existing_orientations)
            if not already_oriented:
                existing_orientations.append({
                    "project_id": project_id,
                    "project_name": project.get("name"),
                    "checklist": safety_orientation,
                    "completed_at": now.isoformat(),
                })
                update_fields["safety_orientations"] = existing_orientations
        
        await db.workers.update_one({"_id": worker["_id"]}, {"$set": update_fields})
    
    # Save orientation as a proper logbook document so CP can view/sign it
    if safety_orientation:
        worker_id_str = str(worker["_id"])
        existing_orient_log = await db.logbooks.find_one({
            "log_type": "subcontractor_orientation",
            "project_id": project_id,
            "data.worker_id": worker_id_str,
            "is_deleted": {"$ne": True},
        })
        if not existing_orient_log:
            await db.logbooks.insert_one({
                "log_type": "subcontractor_orientation",
                "project_id": project_id,
                "project_name": project.get("name", ""),
                "company_id": company_id,
                "date": now.strftime("%Y-%m-%d"),
                "status": "draft",  # CP must add signature to submit
                "cp_signature": None,
                "cp_name": None,
                "data": {
                    "worker_id": worker_id_str,
                    "worker_name": name,
                    "worker_company": company,
                    "worker_trade": trade or "",
                    "osha_number": osha_number or "",
                    "worker_signature": signature,
                    "checklist": safety_orientation,
                    "completed_at": now.isoformat(),
                    "orientation_number": None,
					"language_provided": language_provided,
                },
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
            })
    
    # Create check-in — use EST-aligned day boundaries for NYC compliance
    today_start, today_end = get_today_range_est()
    existing_checkin = await db.checkins.find_one({
        "worker_id": str(worker["_id"]),
        "project_id": project_id,
        "check_in_time": {"$gte": today_start, "$lt": today_end},
        "status": "checked_in",
        "is_deleted": {"$ne": True}
    })
    
    if existing_checkin:
        return {
            "success": True,
            "message": "Already checked in",
            "worker_id": str(worker["_id"]),
            "worker_name": worker.get("name"),
            "project_name": project.get("name"),
            "check_in_time": existing_checkin["check_in_time"].isoformat(),
            "is_new_worker": False,
        }
    
    # ── CERTIFICATION GATE ──
    # Create an OSHA cert from the uploaded card. Previously this code
    # would OVERWRITE type to "SST_LIMITED" when an expiration date was
    # detected — which is wrong: an OSHA card with expiration is still
    # an OSHA card, and flipping the type made validate_worker_certifications
    # fail "MISSING_OSHA" immediately for any worker who uploaded one.
    #
    # Strategy now: if the photo carries an expiration, create BOTH an
    # OSHA_10 entry (lifetime, no expiration carried over) AND an
    # SST_LIMITED entry (the expiration lives there). If no expiration
    # found, just create the OSHA_10. Also: accept any uploaded card
    # image as a best-effort OSHA signal even if OCR couldn't pull the
    # number — better than silently blocking the worker for an OCR fail.
    worker_certs = worker.get("certifications", [])
    has_existing_osha = any(c.get("type", "").startswith("OSHA") for c in worker_certs)
    has_existing_sst = any(c.get("type", "").startswith("SST") for c in worker_certs)

    if not has_existing_osha and (osha_number or osha_card_image):
        course_str = str(osha_data.get("course", "") if osha_data else "")
        osha_cert = {
            "type": "OSHA_30" if "30" in course_str else "OSHA_10",
            "card_number": osha_number or None,
            "issue_date": None,
            "expiration_date": None,  # OSHA cards are lifetime post-2020
            "verified": False,
            "needs_review": not bool(osha_number),  # flag for admin if OCR missed number
            "ocr_confidence": osha_data.get("confidence") if osha_data else None,
        }
        worker_certs.append(osha_cert)

    # If the card appears to be SST (has expiration), also add an SST entry.
    if not has_existing_sst and osha_data and osha_data.get("expiration"):
        try:
            exp_dt = datetime.strptime(osha_data["expiration"], "%m/%d/%Y").replace(tzinfo=timezone.utc)
            worker_certs.append({
                "type": "SST_LIMITED",
                "card_number": osha_number or None,
                "issue_date": None,
                "expiration_date": exp_dt,
                "verified": False,
                "needs_review": not bool(osha_number),
                "ocr_confidence": osha_data.get("confidence") if osha_data else None,
            })
        except (ValueError, TypeError):
            pass

    if len(worker_certs) != len(worker.get("certifications", [])):
        await db.workers.update_one(
            {"_id": worker["_id"]},
            {"$set": {"certifications": worker_certs, "updated_at": now}}
        )
        worker["certifications"] = worker_certs

    cert_result = validate_worker_certifications(worker, project)
    if not cert_result["cleared"]:
        await create_cert_block_alert(worker, project, cert_result["blocks"])
        return {
            "success": False,
            "blocked": True,
            "worker_name": worker.get("name"),
            "worker_id": str(worker["_id"]),
            "blocks": cert_result["blocks"],
            "message": "Registration saved but check-in denied — missing certifications.",
        }
    cert_warnings = cert_result.get("warnings", [])

    checkin_record = {
        "worker_id": str(worker["_id"]),
        "worker_name": worker.get("name"),
        "worker_phone": worker.get("phone"),
        "worker_company": worker.get("company"),
        "worker_trade": worker.get("trade"),
        "company": worker.get("company"),
        "trade": worker.get("trade"),
        "project_id": project_id,
        "project_name": project.get("name"),
        "admin_id": admin_id,
        "company_id": company_id,
        "tag_id": tag_id,
        "check_in_time": now,
        "check_out_time": None,
        "status": "checked_in",
        "timestamp": now,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
        "cert_warnings": cert_warnings,
    }
    
    result = await db.checkins.insert_one(checkin_record)
    
    return {
        "success": True,
        "message": "Registration and check-in successful",
        "worker_id": str(worker["_id"]),
        "checkin_id": str(result.inserted_id),
        "worker_name": worker.get("name"),
        "project_name": project.get("name"),
        "check_in_time": now.isoformat(),
        "is_new_worker": True,
    }
@api_router.post("/checkin/lookup-worker")
async def lookup_worker(data: dict):
    """Public endpoint - check if worker exists by phone.
    Used by returning workers to skip registration."""
    phone = data.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone required")
    
    # Search by both raw digits and formatted version
    raw_digits = ''.join(c for c in phone if c.isdigit())
    formatted = format_phone(raw_digits)
    
    worker = await db.workers.find_one(
        {"phone": {"$in": [phone, raw_digits, formatted]}, "is_deleted": {"$ne": True}},
        {"osha_card_image": 0}
    )
    
    if not worker:
        return {"found": False}
    
    return {
        "found": True,
        "worker_id": str(worker["_id"]),
        "name": worker.get("name"),
        "trade": worker.get("trade"),
        "company": worker.get("company"),
        "osha_number": worker.get("osha_number"),
        "has_osha_card": bool(worker.get("osha_card_image")),
        "safety_orientations": worker.get("safety_orientations", []),
    }   
   
@api_router.post("/checkin/submit")
async def submit_checkin(checkin_data: PublicCheckInSubmit):
    """Public endpoint - workers check in via this"""
    try:
        # Format phone number
        checkin_data.phone = format_phone(checkin_data.phone)
        
        # Verify tag
        tag = await db.nfc_tags.find_one({
            "tag_id": checkin_data.tag_id,
            "project_id": checkin_data.project_id,
            "status": "active",
            "is_deleted": {"$ne": True}
        })
        
        if not tag:
            raise HTTPException(status_code=404, detail="Invalid check-in")
        
        project = await db.projects.find_one({"_id": to_query_id(checkin_data.project_id), "is_deleted": {"$ne": True}})
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Strict (trade, company) validation — the check-in page presents
        # a dropdown of combined Trade — Company entries from the admin's
        # per-project subcontractor roster. Workers can only submit a
        # pair that the admin pre-configured. Matching is case/whitespace
        # tolerant so the DB values get canonicalized to the admin's
        # exact casing for consistent reporting.
        raw_assignments = project.get("trade_assignments") or []
        assignments = []
        for row in raw_assignments:
            if not isinstance(row, dict):
                continue
            t = str(row.get("trade") or "").strip()
            c = str(row.get("company") or "").strip()
            if t and c:
                assignments.append({"trade": t, "company": c})

        if not assignments:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This project has no subcontractors configured yet. "
                    "Ask the project admin to set up the check-in trade list."
                ),
            )

        submitted_trade = str(checkin_data.trade or "").strip()
        submitted_company = str(checkin_data.company or "").strip()
        match = next(
            (
                a for a in assignments
                if a["trade"].lower() == submitted_trade.lower()
                and a["company"].lower() == submitted_company.lower()
            ),
            None,
        )
        if not match:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Please pick your trade and company from the dropdown. "
                    "Custom entries are not allowed."
                ),
            )
        # Canonicalize to the admin's exact casing.
        checkin_data.trade = match["trade"]
        checkin_data.company = match["company"]

        admin_id = project.get("admin_id")
        company_id = project.get("company_id")
        now = datetime.now(timezone.utc)

        # Find or create worker
        raw_digits = ''.join(c for c in checkin_data.phone if c.isdigit())
        formatted_phone = format_phone(raw_digits)
        worker = await db.workers.find_one({"phone": {"$in": [checkin_data.phone, raw_digits, formatted_phone]}, "is_deleted": {"$ne": True}})
        
        if not worker:
            new_worker = {
                "name": checkin_data.name,
                "phone": checkin_data.phone,
                "company": checkin_data.company,
                "trade": checkin_data.trade,
                "admin_id": admin_id,
                "company_id": company_id,
                "created_at": now,
                "updated_at": now,
                "status": "active",
                "is_deleted": False
            }
            result = await db.workers.insert_one(new_worker)
            worker = new_worker
            worker["_id"] = result.inserted_id
        else:
            # Update worker info
            update_fields = {}
            if worker.get("name") != checkin_data.name:
                update_fields["name"] = checkin_data.name
            if worker.get("company") != checkin_data.company:
                update_fields["company"] = checkin_data.company
            if worker.get("trade") != checkin_data.trade:
                update_fields["trade"] = checkin_data.trade
            if not worker.get("admin_id"):
                update_fields["admin_id"] = admin_id
            if not worker.get("company_id"):
                update_fields["company_id"] = company_id
            
            if update_fields:
                update_fields["updated_at"] = now
                await db.workers.update_one(
                    {"_id": worker["_id"]},
                    {"$set": update_fields}
                )
        
        # Check if already checked in today (EST-aligned)
        today_start, today_end = get_today_range_est()
        existing_checkin = await db.checkins.find_one({
            "worker_id": str(worker["_id"]),
            "project_id": checkin_data.project_id,
            "check_in_time": {"$gte": today_start, "$lt": today_end},
            "status": "checked_in",
            "is_deleted": {"$ne": True}
        })
        
        if existing_checkin:
            return {
                "success": True,
                "message": "Already checked in",
                "checkin_id": str(existing_checkin["_id"]),
                "worker_name": worker.get("name"),
                "project_name": project.get("name"),
                "check_in_time": existing_checkin["check_in_time"].isoformat()
            }
        
        # ── CERTIFICATION GATE ──
        cert_result = validate_worker_certifications(worker, project)
        if not cert_result["cleared"]:
            await create_cert_block_alert(worker, project, cert_result["blocks"])
            raise HTTPException(
                status_code=403,
                detail={
                    "blocked": True,
                    "worker_name": worker.get("name"),
                    "blocks": cert_result["blocks"],
                    "message": "Check-in denied — certification requirements not met."
                }
            )
        cert_warnings = cert_result.get("warnings", [])

        # Create check-in
        checkin_record = {
            "worker_id": str(worker["_id"]),
            "worker_name": worker.get("name"),
            "worker_phone": worker.get("phone"),
            "worker_company": worker.get("company"),
            "worker_trade": worker.get("trade"),
            "company": worker.get("company"),
            "trade": worker.get("trade"),
            "project_id": checkin_data.project_id,
            "project_name": project.get("name"),
            "admin_id": admin_id,
            "company_id": company_id,
            "tag_id": checkin_data.tag_id,
            "check_in_time": now,
            "check_out_time": None,
            "status": "checked_in",
            "timestamp": now,
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
            "cert_warnings": cert_warnings,
        }
        
        result = await db.checkins.insert_one(checkin_record)
        
        return {
            "success": True,
            "message": "Check-in successful",
            "checkin_id": str(result.inserted_id),
            "worker_name": worker.get("name"),
            "project_name": project.get("name"),
            "check_in_time": now.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check-in failed: {str(e)}")
        
# ==================== WORKERS ====================

@api_router.get("/workers")
async def get_workers(
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    result = await paginated_query(db.workers, query, sort_field="name", sort_dir=1, limit=limit, skip=skip)
    return result

@api_router.post("/workers/register")
async def register_worker(worker_data: WorkerCreate):
    """Public endpoint - allows workers to self-register via NFC check-in."""
    # Check if worker with phone exists
    existing = await db.workers.find_one({"phone": worker_data.phone, "is_deleted": {"$ne": True}})
    if existing:
        return {"worker_id": str(existing["_id"]), "message": "Worker already registered"}
    
    worker_dict = worker_data.model_dump()
    worker_dict["status"] = "active"
    now = datetime.now(timezone.utc)
    worker_dict["created_at"] = now
    worker_dict["updated_at"] = now
    worker_dict["certifications"] = []
    worker_dict["signature"] = None
    worker_dict["is_deleted"] = False
    
    result = await db.workers.insert_one(worker_dict)
    
    return {"worker_id": str(result.inserted_id), "message": "Worker registered successfully"}

# ==================== WORKER CERTIFICATION MANAGEMENT ====================

@api_router.get("/workers/{worker_id}/certifications")
async def get_worker_certifications(worker_id: str, current_user=Depends(get_current_user)):
    """Get structured certifications with validation status."""
    worker = await db.workers.find_one({"_id": to_query_id(worker_id), "is_deleted": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    certs = worker.get("certifications", [])
    validation = validate_worker_certifications(worker)
    return {"worker_id": worker_id, "worker_name": worker.get("name"), "certifications": certs, "validation": validation}

@api_router.post("/workers/{worker_id}/certifications")
async def add_worker_certification(worker_id: str, cert: WorkerCertification, admin=Depends(get_admin_user)):
    """Add a certification to a worker's record."""
    try:
        worker = await db.workers.find_one({"_id": to_query_id(worker_id), "is_deleted": {"$ne": True}})
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        now = datetime.now(timezone.utc)
        cert_dict = cert.model_dump()
        cert_dict["added_by"] = str(admin.get("id") or admin.get("_id") or "")
        cert_dict["added_at"] = now
        await db.workers.update_one(
            {"_id": to_query_id(worker_id)},
            {"$push": {"certifications": cert_dict}, "$set": {"updated_at": now}}
        )
        updated = await db.workers.find_one({"_id": to_query_id(worker_id)})
        try:
            validation = validate_worker_certifications(updated)
        except Exception as e:
            logger.warning(f"validate_worker_certifications failed: {e}")
            validation = {"cleared": False, "blocks": [], "warnings": []}

        # Make the response JSON-safe — datetime objects from Pydantic v2 .model_dump()
        # are real datetime.datetime instances and FastAPI will only serialize them
        # if returned via JSONResponse or the Pydantic response_model path.
        from fastapi.encoders import jsonable_encoder
        return jsonable_encoder({
            "message": "Certification added",
            "certification": cert_dict,
            "validation": validation,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"add_worker_certification crashed for worker {worker_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)[:200]}")

@api_router.delete("/workers/{worker_id}/certifications/{cert_index}")
async def remove_worker_certification(worker_id: str, cert_index: int, admin=Depends(get_admin_user)):
    """Remove a certification by index."""
    worker = await db.workers.find_one({"_id": to_query_id(worker_id), "is_deleted": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    certs = worker.get("certifications", [])
    if cert_index < 0 or cert_index >= len(certs):
        raise HTTPException(status_code=400, detail="Invalid certification index")
    removed = certs.pop(cert_index)
    now = datetime.now(timezone.utc)
    await db.workers.update_one(
        {"_id": to_query_id(worker_id)},
        {"$set": {"certifications": certs, "updated_at": now}}
    )
    return {"message": "Certification removed", "removed": removed}

@api_router.post("/admin/certifications/scan-expiring")
async def scan_expiring_certifications(admin=Depends(get_admin_user)):
    """Scan all workers for expiring or missing certifications."""
    company_id = get_user_company_id(admin)
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    workers = await db.workers.find(query).to_list(5000)
    blocked_workers = []
    warning_workers = []
    for w in workers:
        result = validate_worker_certifications(w)
        ws = {"worker_id": str(w.get("_id", "")), "name": w.get("name", ""), "company": w.get("company", ""), "trade": w.get("trade", "")}
        if result["blocks"]:
            ws["blocks"] = result["blocks"]
            blocked_workers.append(ws)
        elif result["warnings"]:
            ws["warnings"] = result["warnings"]
            warning_workers.append(ws)
    return {"total_scanned": len(workers), "blocked_count": len(blocked_workers), "warning_count": len(warning_workers), "blocked_workers": blocked_workers, "warning_workers": warning_workers}
	
@api_router.get("/workers/{worker_id}/osha-card")
async def get_worker_osha_card(worker_id: str, current_user = Depends(get_current_user)):
    """Get worker's OSHA card image and data - for admin and site device"""
    worker = await db.workers.find_one(
        {"_id": to_query_id(worker_id), "is_deleted": {"$ne": True}},
		{"osha_card_image": 1, "osha_data": 1, "osha_number": 1, "safety_orientations": 1, "name": 1, "company_id": 1, "signature": 1}
	)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Check access: admin must have worker in their company OR worker checked into their projects
    user_role = current_user.get("role")
    if user_role not in ["admin", "site_device"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    company_id = get_user_company_id(current_user)
    worker_company = worker.get("company_id")
    
    # Check if worker's company matches OR worker has checked into this company's projects
    if worker_company != company_id:
        # Check if worker checked into any of this admin's projects
        has_checkin = await db.checkins.find_one({
            "worker_id": worker_id,
            "company_id": company_id
        })
        if not has_checkin:
            raise HTTPException(status_code=403, detail="Access denied to this worker's data")
    
    return {
        "name": worker.get("name"),
        "osha_card_image": worker.get("osha_card_image"),
        "osha_data": worker.get("osha_data"),
        "osha_number": worker.get("osha_number"),
        "safety_orientations": worker.get("safety_orientations", []),
		"signature": worker.get("signature"),
    }
@api_router.get("/workers/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, current_user = Depends(get_current_user)):
    worker = await db.workers.find_one({"_id": to_query_id(worker_id), "is_deleted": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Check company access
    company_id = get_user_company_id(current_user)
    if company_id and worker.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return WorkerResponse(**serialize_id(worker))

@api_router.put("/workers/{worker_id}", response_model=WorkerResponse)
async def update_worker(worker_id: str, worker_data: dict, current_user = Depends(get_current_user)):
    ALLOWED_WORKER_FIELDS = {"name", "phone", "trade", "company", "osha_number", "certifications", "emergency_contact", "emergency_phone", "notes"}
    update_data = {k: v for k, v in worker_data.items() if v is not None and k in ALLOWED_WORKER_FIELDS}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.workers.update_one(
        {"_id": to_query_id(worker_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    worker = await db.workers.find_one({"_id": to_query_id(worker_id)})
    return WorkerResponse(**serialize_id(worker))

@api_router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str, admin = Depends(get_admin_user)):
    # Soft delete
    result = await db.workers.update_one(
        {"_id": to_query_id(worker_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"message": "Worker deleted successfully"}

# ==================== CHECK-INS ====================

@api_router.post("/workers")
async def create_worker(worker_data: WorkerCreate, current_user = Depends(get_current_user)):
    """Create a new worker (admin)"""
    # Check if worker with phone exists
    existing = await db.workers.find_one({"phone": worker_data.phone, "is_deleted": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="Worker with this phone already exists")
    
    company_id = get_user_company_id(current_user)
    worker_dict = worker_data.model_dump()
    worker_dict["status"] = "active"
    now = datetime.now(timezone.utc)
    worker_dict["created_at"] = now
    worker_dict["updated_at"] = now
    worker_dict["certifications"] = []
    worker_dict["signature"] = None
    worker_dict["is_deleted"] = False
    if company_id:
        worker_dict["company_id"] = company_id
    
    result = await db.workers.insert_one(worker_dict)
    worker_dict["id"] = str(result.inserted_id)
    worker_dict.pop("_id", None)
    
    return WorkerResponse(**worker_dict)

@api_router.get("/checkins")
async def get_all_checkins(
    date: str = None,
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """Get all check-ins for the user's company"""
    company_id = get_user_company_id(current_user)
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    if date:
        # Parse date as Eastern Time day, convert to UTC range
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo("America/New_York")
        day_start_eastern = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=eastern)
        day_start_utc = day_start_eastern.astimezone(timezone.utc)
        day_end_utc = day_start_utc + timedelta(hours=24)
        query["check_in_time"] = {"$gte": day_start_utc, "$lt": day_end_utc}
    total = await db.checkins.count_documents(query)
    checkins = await db.checkins.find(query).sort("check_in_time", -1).skip(skip).limit(limit).to_list(limit)
    
    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = await db.workers.find_one({"_id": to_query_id(s["worker_id"]), "is_deleted": {"$ne": True}})
            if worker:
                s["worker_name"] = worker.get("name", "Unknown Worker")
                s["worker_company"] = s.get("worker_company") or worker.get("company")
                s["worker_trade"] = s.get("worker_trade") or worker.get("trade")
                s["name"] = s["worker_name"]
                s["company"] = s["worker_company"]
                s["trade"] = s["worker_trade"]
        results.append(s)
    return {"items": results, "total": total, "limit": limit, "skip": skip, "has_more": (skip + limit) < total}

@api_router.post("/checkins")
async def create_checkin(checkin_data: CheckInCreate, current_user = Depends(get_current_user)):
    """Create a check-in from admin panel — with duplicate prevention"""
    worker = None
    if checkin_data.worker_id:
        worker = await db.workers.find_one({"_id": to_query_id(checkin_data.worker_id), "is_deleted": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    project = None
    if checkin_data.project_id:
        project = await db.projects.find_one({"_id": to_query_id(checkin_data.project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    now = datetime.now(timezone.utc)
    
    # ── Prevent duplicate check-in for same worker+project today (EST-aligned) ──
    today_start, today_end = get_today_range_est()
    existing_checkin = await db.checkins.find_one({
        "worker_id": str(worker["_id"]),
        "project_id": str(project["_id"]),
        "check_in_time": {"$gte": today_start, "$lt": today_end},
        "status": "checked_in",
        "is_deleted": {"$ne": True}
    })
    
    if existing_checkin:
        existing_data = serialize_id(existing_checkin)
        return existing_data

    # ── CERTIFICATION GATE ──
    cert_result = validate_worker_certifications(worker, project)
    if not cert_result["cleared"]:
        await create_cert_block_alert(worker, project, cert_result["blocks"])
        raise HTTPException(
            status_code=403,
            detail={
                "blocked": True,
                "worker_name": worker.get("name"),
                "blocks": cert_result["blocks"],
                "message": "Check-in denied — certification requirements not met."
            }
        )
    cert_warnings = cert_result.get("warnings", [])

    checkin_record = {
        "worker_id": str(worker["_id"]),
        "worker_name": worker.get("name"),
        "worker_company": worker.get("company"),
        "worker_trade": worker.get("trade"),
        "project_id": str(project["_id"]),
        "project_name": project.get("name"),
        "company_id": project.get("company_id"),
        "check_in_time": now,
        "check_out_time": None,
        "status": "checked_in",
        "timestamp": now,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
        "cert_warnings": cert_warnings,
    }
    
    result = await db.checkins.insert_one(checkin_record)
    checkin_record["id"] = str(result.inserted_id)
    checkin_record.pop("_id", None)
    # JSON-safe — checkin_record carries raw datetime fields that FastAPI's
    # default serializer will choke on without a response_model.
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(checkin_record)


@api_router.post("/checkin")
async def check_in_worker(checkin_data: CheckInCreate, request: Request = None):
    """Public endpoint - allows workers to check in via NFC or manual.
    Rate-limited and duplicate-protected since it doesn't require JWT."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not checkin_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many check-in requests. Try again shortly.")
    # Find worker
    worker = None
    if checkin_data.worker_id:
        worker = await db.workers.find_one({"_id": to_query_id(checkin_data.worker_id), "is_deleted": {"$ne": True}})
    elif checkin_data.phone:
        worker = await db.workers.find_one({"phone": checkin_data.phone, "is_deleted": {"$ne": True}})
    
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Find project from tag or direct project_id
    project = None
    if checkin_data.tag_id:
        tag = await db.nfc_tags.find_one({"tag_id": checkin_data.tag_id, "status": "active", "is_deleted": {"$ne": True}})
        if tag:
            project = await db.projects.find_one({"_id": to_query_id(tag["project_id"]), "is_deleted": {"$ne": True}})
    elif checkin_data.project_id:
        project = await db.projects.find_one({"_id": to_query_id(checkin_data.project_id), "is_deleted": {"$ne": True}})
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # ── DUPLICATE CHECK (EST-aligned) ──
    today_start, today_end = get_today_range_est()
    existing_checkin = await db.checkins.find_one({
        "worker_id": str(worker["_id"]),
        "project_id": str(project["_id"]),
        "check_in_time": {"$gte": today_start, "$lt": today_end},
        "status": "checked_in",
        "is_deleted": {"$ne": True}
    })
    if existing_checkin:
        return {
            "id": str(existing_checkin["_id"]),
            "worker_id": str(worker["_id"]),
            "worker_name": worker.get("name"),
            "project_id": str(project["_id"]),
            "project_name": project.get("name"),
            "timestamp": existing_checkin["check_in_time"].isoformat(),
            "message": "Already checked in today"
        }

    # ── CERTIFICATION GATE ──
    cert_result = validate_worker_certifications(worker, project)
    if not cert_result["cleared"]:
        await create_cert_block_alert(worker, project, cert_result["blocks"])
        raise HTTPException(
            status_code=403,
            detail={
                "blocked": True,
                "worker_name": worker.get("name"),
                "blocks": cert_result["blocks"],
                "message": "Check-in denied — certification requirements not met."
            }
        )
    cert_warnings = cert_result.get("warnings", [])

    # Create check-in record
    now = datetime.now(timezone.utc)
    checkin_record = {
        "worker_id": str(worker["_id"]),
        "worker_name": worker.get("name"),
        "worker_company": worker.get("company"),
        "worker_trade": worker.get("trade"),
        "project_id": str(project["_id"]),
        "project_name": project.get("name"),
        "company_id": project.get("company_id"),
        "check_in_time": now,
        "check_out_time": None,
        "status": "checked_in",
        "timestamp": now,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
	    "cert_warnings": cert_warnings,
    }
    
    result = await db.checkins.insert_one(checkin_record)
    checkin_record["id"] = str(result.inserted_id)

    await audit_log("checkin_create", str(worker["_id"]), "checkin", str(result.inserted_id), {
        "worker_name": worker.get("name"), "project_name": project.get("name"), "project_id": str(project["_id"]),
    })

    return {
        "id": str(result.inserted_id),
        "worker_id": str(worker["_id"]),
        "worker_name": worker.get("name"),
        "project_id": str(project["_id"]),
        "project_name": project.get("name"),
        "timestamp": now.isoformat(),
        "message": "Check-in successful"
    }

@api_router.post("/checkins/{checkin_id}/checkout")
async def check_out_worker(checkin_id: str, current_user = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    result = await db.checkins.update_one(
        {"_id": to_query_id(checkin_id)},
        {"$set": {"check_out_time": now, "status": "checked_out", "updated_at": now}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Check-in record not found")

    await audit_log("checkout", str(current_user.get("_id", "")), "checkin", checkin_id)

    return {"message": "Check-out successful"}

@api_router.get("/checkins/project/{project_id}")
async def get_project_checkins(
    project_id: str,
    current_user = Depends(get_current_user),
    limit: int = Query(200, ge=1, le=1000),
    skip: int = Query(0, ge=0),
):
    checkins = await db.checkins.find({"project_id": project_id, "is_deleted": {"$ne": True}}).sort("check_in_time", -1).skip(skip).limit(limit).to_list(limit)

    # Batch-fetch workers for check-ins missing worker_name (avoid N+1)
    missing_worker_ids = set()
    for c in checkins:
        if not c.get("worker_name") and c.get("worker_id"):
            missing_worker_ids.add(c["worker_id"])

    workers_map = {}
    if missing_worker_ids:
        query_ids = [to_query_id(wid) for wid in missing_worker_ids]
        workers_list = await db.workers.find({"_id": {"$in": query_ids}, "is_deleted": {"$ne": True}}).to_list(len(query_ids))
        for w in workers_list:
            workers_map[str(w["_id"])] = w

    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = workers_map.get(s["worker_id"])
            if worker:
                s["worker_name"] = worker.get("name", "Unknown Worker")
                s["worker_company"] = s.get("worker_company") or worker.get("company")
                s["worker_trade"] = s.get("worker_trade") or worker.get("trade")
        results.append(s)
    return results

@api_router.get("/checkins/project/{project_id}/active")
async def get_active_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    today_start, today_end = get_today_range_est()
    checkins = await db.checkins.find({
        "project_id": project_id,
        "status": "checked_in",
        "check_in_time": {"$gte": today_start, "$lt": today_end},
        "is_deleted": {"$ne": True}
    }).to_list(500)

    # Batch-fetch workers for check-ins missing worker_name (avoid N+1)
    missing_ids = set()
    for c in checkins:
        if not c.get("worker_name") and c.get("worker_id"):
            missing_ids.add(c["worker_id"])
    workers_map = {}
    if missing_ids:
        wlist = await db.workers.find({"_id": {"$in": [to_query_id(wid) for wid in missing_ids]}, "is_deleted": {"$ne": True}}).to_list(len(missing_ids))
        for w in wlist:
            workers_map[str(w["_id"])] = w

    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = workers_map.get(s["worker_id"])
            if worker:
                s["worker_name"] = worker.get("name", "Unknown Worker")
                s["worker_company"] = s.get("worker_company") or worker.get("company")
                s["worker_trade"] = s.get("worker_trade") or worker.get("trade")
        results.append(s)
    return results

@api_router.get("/checkins/project/{project_id}/today")
async def get_today_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    today_start, today_end = get_today_range_est()
    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": today_start, "$lt": today_end},
        "is_deleted": {"$ne": True}
    }).to_list(500)

    # Batch-fetch workers for check-ins missing worker_name (avoid N+1)
    missing_ids = set()
    for c in checkins:
        if not c.get("worker_name") and c.get("worker_id"):
            missing_ids.add(c["worker_id"])
    workers_map = {}
    if missing_ids:
        wlist = await db.workers.find({"_id": {"$in": [to_query_id(wid) for wid in missing_ids]}, "is_deleted": {"$ne": True}}).to_list(len(missing_ids))
        for w in wlist:
            workers_map[str(w["_id"])] = w

    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = workers_map.get(s["worker_id"])
            if worker:
                s["worker_name"] = worker.get("name", "Unknown Worker")
                s["worker_company"] = s.get("worker_company") or worker.get("company")
                s["worker_trade"] = s.get("worker_trade") or worker.get("trade")
        results.append(s)
    return results

# ==================== DAILY LOGS ====================

@api_router.get("/daily-logs")
async def get_daily_logs(
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    result = await paginated_query(db.daily_logs, query, sort_field="date", limit=limit, skip=skip)
    return result

@api_router.post("/daily-logs", response_model=DailyLogResponse)
async def create_daily_log(log_data: DailyLogCreate, current_user = Depends(get_current_user)):
    log_dict = log_data.model_dump()
    now = datetime.now(timezone.utc)
    log_dict["created_at"] = now
    log_dict["updated_at"] = now
    log_dict["created_by"] = current_user.get("id")
    log_dict["created_by_name"] = current_user.get("full_name") or current_user.get("name") or current_user.get("device_name")
    log_dict["is_deleted"] = False
	
    # Prevent duplicate log for same project + date
    existing = await db.daily_logs.find_one({
        "project_id": log_data.project_id,
        "date": log_data.date,
        "is_deleted": {"$ne": True}
    })
    if existing:
        raise HTTPException(status_code=409, detail="A daily log already exists for this project and date.")
    
    # Get project to inject company_id
    project = await db.projects.find_one({"_id": to_query_id(log_data.project_id), "is_deleted": {"$ne": True}})
    if project:
        log_dict["company_id"] = project.get("company_id")
    
    result = await db.daily_logs.insert_one(log_dict)
    log_dict["id"] = str(result.inserted_id)
    
    return DailyLogResponse(**log_dict)

@api_router.put("/daily-logs/{log_id}")
async def update_daily_log(log_id: str, update_data: dict, current_user = Depends(get_current_user)):
    """Update an existing daily log"""
    existing = await db.daily_logs.find_one({"_id": to_query_id(log_id)})
    
    if not existing:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    if existing.get("is_locked"):
        raise HTTPException(status_code=423, detail="This log is locked and cannot be edited.")
    
    update_data.pop("id", None)
    update_data.pop("_id", None)
    update_data.pop("created_at", None)
    update_data.pop("created_by", None)
    
    now = datetime.now(timezone.utc)
    update_data["updated_at"] = now
    update_data["updated_by"] = current_user.get("id")
    update_data["updated_by_name"] = current_user.get("full_name") or current_user.get("name") or current_user.get("device_name")
    
    await db.daily_logs.update_one(
        {"_id": to_query_id(log_id)},
        {"$set": update_data}
    )
    
    log = await db.daily_logs.find_one({"_id": to_query_id(log_id)})
    return serialize_id(log)

@api_router.get("/daily-logs/{log_id}", response_model=DailyLogResponse)
async def get_daily_log(log_id: str, current_user = Depends(get_current_user)):
    log = await db.daily_logs.find_one({"_id": to_query_id(log_id), "is_deleted": {"$ne": True}})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    return DailyLogResponse(**serialize_id(log))

@api_router.get("/daily-logs/project/{project_id}")
async def get_project_daily_logs(project_id: str, current_user = Depends(get_current_user)):
    result = await paginated_query(
        db.daily_logs,
        {"project_id": project_id, "is_deleted": {"$ne": True}},
        sort_field="date", limit=50, skip=0,
    )
    return result

@api_router.get("/daily-logs/project/{project_id}/date/{date}")
async def get_daily_log_by_date(project_id: str, date: str, current_user = Depends(get_current_user)):
    """Get daily log for a specific project and date"""
    log = await db.daily_logs.find_one({
        "project_id": project_id,
        "date": date,
        "is_deleted": {"$ne": True}
    })
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found for this date")
    return serialize_id(log)

# ==================== SITE DEVICE MANAGEMENT ====================

@api_router.get("/admin/site-devices")
async def get_site_devices(admin = Depends(get_admin_user)):
    """Get all site devices"""
    company_id = get_user_company_id(admin)
    
    devices = await db.site_devices.find({"is_deleted": {"$ne": True}}, {"password": 0}).to_list(200)
    result = []
    for device in devices:
        device_data = serialize_id(device)
        # Get project name
        if device.get("project_id"):
            project = await db.projects.find_one({"_id": to_query_id(device["project_id"]), "is_deleted": {"$ne": True}})
            if project:
                device_data["project_name"] = project.get("name")
                # Filter by company
                if company_id and project.get("company_id") != company_id:
                    continue
        result.append(device_data)
    return result

@api_router.post("/admin/site-devices")
async def create_site_device(device_data: SiteDeviceCreate, admin = Depends(get_admin_user)):
    """Create a new site device credential"""
    # Check if username exists
    existing = await db.site_devices.find_one({"username": device_data.username, "is_deleted": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Verify project exists and belongs to admin's company
    project = await db.projects.find_one({"_id": to_query_id(device_data.project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check company access
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    device_dict = device_data.model_dump()
    device_dict["password"] = hash_password(device_dict["password"])
    device_dict["is_active"] = True
    now = datetime.now(timezone.utc)
    device_dict["created_at"] = now
    device_dict["updated_at"] = now
    device_dict["created_by"] = admin.get("id")
    device_dict["company_id"] = project.get("company_id")
    device_dict["is_deleted"] = False
    
    result = await db.site_devices.insert_one(device_dict)
    
    return {
        "id": str(result.inserted_id),
        "project_id": device_data.project_id,
        "project_name": project.get("name"),
        "device_name": device_data.device_name,
        "username": device_data.username,
        "is_active": True,
        "message": "Site device created successfully"
    }

@api_router.get("/admin/site-devices/{device_id}")
async def get_site_device(device_id: str, admin = Depends(get_admin_user)):
    """Get a specific site device"""
    device = await db.site_devices.find_one({"_id": to_query_id(device_id), "is_deleted": {"$ne": True}}, {"password": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Site device not found")
    
    device_data = serialize_id(device)
    if device.get("project_id"):
        project = await db.projects.find_one({"_id": to_query_id(device["project_id"]), "is_deleted": {"$ne": True}})
        device_data["project_name"] = project.get("name") if project else "Unknown"
    
    return device_data

@api_router.put("/admin/site-devices/{device_id}")
async def update_site_device(device_id: str, update_data: dict, admin = Depends(get_admin_user)):
    """Update a site device"""
    update_fields = {}
    
    if "device_name" in update_data:
        update_fields["device_name"] = update_data["device_name"]
    if "is_active" in update_data:
        update_fields["is_active"] = update_data["is_active"]
    if "password" in update_data and update_data["password"]:
        update_fields["password"] = hash_password(update_data["password"])
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    
    update_fields["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.site_devices.update_one(
        {"_id": to_query_id(device_id)},
        {"$set": update_fields}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Site device not found")
    
    return {"message": "Site device updated successfully"}

@api_router.delete("/admin/site-devices/{device_id}")
async def delete_site_device(device_id: str, admin = Depends(get_admin_user)):
    """Delete a site device"""
    # Soft delete
    result = await db.site_devices.update_one(
        {"_id": to_query_id(device_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Site device not found")
    return {"message": "Site device deleted successfully"}

@api_router.get("/projects/{project_id}/site-devices")
async def get_project_site_devices(project_id: str, admin = Depends(get_admin_user)):
    """Get all site devices for a specific project"""
    devices = await db.site_devices.find(
        {"project_id": project_id, "is_deleted": {"$ne": True}},
        {"password": 0}
    ).to_list(100)
    return serialize_list(devices)

@api_router.post("/projects/{project_id}/site-devices")
async def create_project_site_device(project_id: str, device_data: SiteDeviceCreate, admin = Depends(get_admin_user)):
    """Create a site device from project detail page"""
    existing = await db.site_devices.find_one({"username": device_data.username, "is_deleted": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    now = datetime.now(timezone.utc)
    device_dict = {
        "project_id": project_id,
        "device_name": device_data.device_name or "Site Device",
        "username": device_data.username,
        "password": hash_password(device_data.password),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": admin.get("id"),
        "company_id": project.get("company_id"),
        "is_deleted": False,
    }
    
    result = await db.site_devices.insert_one(device_dict)
    
    return {
        "id": str(result.inserted_id),
        "project_id": project_id,
        "project_name": project.get("name"),
        "device_name": device_dict["device_name"],
        "username": device_data.username,
        "is_active": True,
        "message": "Site device created successfully"
    }

# ==================== SIGNATURE EVENT HELPERS ====================
 
def compute_content_hash(content: dict) -> str:
    """SHA-256 hash of the JSON-serialized content snapshot.
    Ensures deterministic serialization with sort_keys."""
    import json
    canonical = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
 
 
async def create_signature_event(
    document_type: str,
    document_id: str,
    event_type: str,
    signer_name: str,
    signer_role: str,
    signer_user_id: str,
    signature_data: dict,
    content_snapshot: dict,
    device_info: dict = None,
    ip_address: str = None,
) -> str:
    """Create a signature event in the audit ledger.
    Returns the inserted event_id as a string."""
    
    now = datetime.now(timezone.utc)
    
    # Determine version: count existing events for this document
    existing_count = await db.signature_events.count_documents({
        "document_type": document_type,
        "document_id": document_id,
    })
    version = existing_count + 1
    
    content_hash = compute_content_hash(content_snapshot)
    
    event_doc = {
        "document_type": document_type,
        "document_id": document_id,
        "event_type": event_type,
        "version": version,
        "signer": {
            "user_id": signer_user_id,
            "name": signer_name,
            "role": signer_role,
        },
        "device": device_info or {},
        "content_snapshot": content_snapshot,
        "content_hash": content_hash,
        "signature_data": signature_data,
        "timestamp": now,
        "ip_address": ip_address,
        "is_deleted": False,
    }
    
    result = await db.signature_events.insert_one(event_doc)
    return str(result.inserted_id)
 
 
# ==================== SIGNATURE EVENT ENDPOINTS ====================
 
@api_router.post("/signature-events")
async def record_signature_event(
    data: SignatureEventCreate,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Record a signature event from any frontend signature capture.
    Returns the event_id to be stored as a reference on the parent document."""
    
    user_id = current_user.get("id")
    ip_address = request.client.host if request.client else None
    
    event_id = await create_signature_event(
        document_type=data.document_type,
        document_id=data.document_id,
        event_type=data.event_type,
        signer_name=data.signer_name,
        signer_role=data.signer_role,
        signer_user_id=user_id,
        signature_data=data.signature_data,
        content_snapshot=data.content_snapshot,
        device_info=data.device_info,
        ip_address=ip_address,
    )
    
    return {"event_id": event_id, "message": "Signature event recorded"}
 
 
@api_router.post("/signature-events/public")
async def record_public_signature_event(data: dict, request: Request):
    """Record a signature event from public endpoints (NFC check-in).
    No auth required — used by checkin.html worker registration."""
    
    ip_address = request.client.host if request.client else None
    
    required = ["document_type", "document_id", "event_type", "signer_name", "signature_data", "content_snapshot"]
    for field in required:
        if field not in data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    event_id = await create_signature_event(
        document_type=data["document_type"],
        document_id=data["document_id"],
        event_type=data["event_type"],
        signer_name=data["signer_name"],
        signer_role=data.get("signer_role", "worker"),
        signer_user_id=data.get("worker_id", "anonymous"),
        signature_data=data["signature_data"],
        content_snapshot=data["content_snapshot"],
        device_info=data.get("device_info"),
        ip_address=ip_address,
    )
    
    return {"event_id": event_id}
 
 
@api_router.get("/signature-events/document/{document_type}/{document_id}")
async def get_signature_events_for_document(
    document_type: str,
    document_id: str,
    current_user=Depends(get_current_user),
):
    """Get all signature events for a specific document (audit trail view).
    Returns events in chronological order with hashes for verification."""
    
    events = await db.signature_events.find({
        "document_type": document_type,
        "document_id": document_id,
        "is_deleted": {"$ne": True},
    }).sort("version", 1).to_list(100)
    
    result = []
    for evt in events:
        result.append({
            "id": str(evt["_id"]),
            "version": evt.get("version"),
            "event_type": evt.get("event_type"),
            "signer": evt.get("signer"),
            "device": evt.get("device"),
            "content_hash": evt.get("content_hash"),
            "timestamp": evt.get("timestamp"),
            "ip_address": evt.get("ip_address"),
            # Omit content_snapshot and signature_data from list — fetch individually
        })
    
    return {"events": result, "total": len(result)}
 
 
@api_router.get("/signature-events/{event_id}")
async def get_signature_event_detail(event_id: str, current_user=Depends(get_current_user)):
    """Get full detail of a single signature event including snapshot and signature data."""
    
    event = await db.signature_events.find_one({"_id": to_query_id(event_id)})
    if not event:
        raise HTTPException(status_code=404, detail="Signature event not found")
    
    return serialize_id(event)
 
 
@api_router.get("/signature-events/verify/{document_type}/{document_id}")
async def verify_signature_integrity(
    document_type: str,
    document_id: str,
    current_user=Depends(get_current_user),
):
    """Verify that no signature events have been tampered with.
    Re-computes content_hash from stored snapshot and compares."""
    
    events = await db.signature_events.find({
        "document_type": document_type,
        "document_id": document_id,
        "is_deleted": {"$ne": True},
    }).sort("version", 1).to_list(100)
    
    results = []
    for evt in events:
        stored_hash = evt.get("content_hash", "")
        recomputed_hash = compute_content_hash(evt.get("content_snapshot", {}))
        is_valid = stored_hash == recomputed_hash
        
        results.append({
            "event_id": str(evt["_id"]),
            "version": evt.get("version"),
            "event_type": evt.get("event_type"),
            "signer_name": evt.get("signer", {}).get("name"),
            "timestamp": evt.get("timestamp"),
            "stored_hash": stored_hash,
            "recomputed_hash": recomputed_hash,
            "integrity_valid": is_valid,
        })
    
    all_valid = all(r["integrity_valid"] for r in results)
    
    # Check for version gaps (deletion detection)
    versions = [r["version"] for r in results if r.get("version")]
    has_gaps = versions != list(range(1, len(versions) + 1)) if versions else False
    
    return {
        "document_type": document_type,
        "document_id": document_id,
        "total_events": len(results),
        "all_valid": all_valid,
        "has_version_gaps": has_gaps,
        "events": results,
    }
 
 
# ==================== CONSTRUCTION SUPERINTENDENT ENDPOINTS ====================
 
@api_router.post("/admin/cs-registrations")
async def register_construction_superintendent(
    data: CSRegistrationCreate,
    admin=Depends(get_admin_user),
):
    """Register a Construction Superintendent to a project.
    Checks for license conflicts across active projects (one-job rule)."""
    
    company_id = get_user_company_id(admin)
    now = datetime.now(timezone.utc)
    
    # Verify project
    project = await db.projects.find_one({"_id": to_query_id(data.project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    # Check if this project already has an active CS
    existing_for_project = await db.cs_registrations.find_one({
        "project_id": data.project_id,
        "is_active": True,
        "is_deleted": {"$ne": True},
    })
    if existing_for_project:
        # Deactivate previous CS for this project
        await db.cs_registrations.update_one(
            {"_id": existing_for_project["_id"]},
            {"$set": {"is_active": False, "deactivated_at": now, "updated_at": now}}
        )
    
    # ONE-JOB RULE CHECK: Look for same license on other active projects
    conflict_warning = None
    license_clean = data.license_number.strip().upper()
    
    conflicting = await db.cs_registrations.find({
        "license_number_normalized": license_clean,
        "is_active": True,
        "is_deleted": {"$ne": True},
        "project_id": {"$ne": data.project_id},
    }).to_list(50)
    
    if conflicting:
        conflict_projects = []
        for c in conflicting:
            cp = await db.projects.find_one({"_id": to_query_id(c["project_id"])})
            conflict_projects.append(cp.get("name", "Unknown") if cp else "Unknown")
        
        conflict_warning = (
            f"WARNING: License {license_clean} is already registered as active CS on: "
            + ", ".join(conflict_projects)
            + ". NYC DOB one-job rule (eff. Jan 2026) limits CS to one active job."
        )
        
        # Log compliance alert
        await db.compliance_alerts.insert_one({
            "alert_type": "cs_one_job_conflict",
            "severity": "high",
            "license_number": license_clean,
            "cs_name": data.full_name,
            "conflicting_projects": [c["project_id"] for c in conflicting],
            "new_project_id": data.project_id,
            "company_id": company_id,
            "message": conflict_warning,
            "resolved": False,
            "created_at": now,
            "created_by": admin.get("id"),
        })
    
    # Create registration
    reg_doc = {
        "project_id": data.project_id,
        "full_name": data.full_name.strip(),
        "license_number": data.license_number.strip(),
        "license_number_normalized": license_clean,
        "nyc_id_email": (data.nyc_id_email or "").strip().lower() or None,
        "sst_number": (data.sst_number or "").strip() or None,
        "phone": (data.phone or "").strip() or None,
        "is_active": True,
        "company_id": company_id,
        "created_by": admin.get("id"),
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    
    result = await db.cs_registrations.insert_one(reg_doc)
    
    return {
        "id": str(result.inserted_id),
        "project_id": data.project_id,
        "project_name": project.get("name"),
        "full_name": data.full_name,
        "license_number": data.license_number,
        "nyc_id_email": data.nyc_id_email,
        "is_active": True,
        "conflict_warning": conflict_warning,
        "message": "CS registered successfully" + (" — with conflict warning" if conflict_warning else ""),
    }
 
 
@api_router.get("/admin/cs-registrations")
async def list_cs_registrations(
    project_id: Optional[str] = None,
    admin=Depends(get_admin_user),
):
    """List all CS registrations, optionally filtered by project."""
    
    company_id = get_user_company_id(admin)
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    if project_id:
        query["project_id"] = project_id
    
    regs = await db.cs_registrations.find(query).sort("created_at", -1).to_list(200)
    
    result = []
    for reg in regs:
        reg_data = serialize_id(reg)
        # Add project name
        project = await db.projects.find_one({"_id": to_query_id(reg["project_id"])})
        reg_data["project_name"] = project.get("name") if project else "Unknown"
        
        # Check for active conflicts
        if reg.get("is_active"):
            conflicts = await db.cs_registrations.count_documents({
                "license_number_normalized": reg.get("license_number_normalized"),
                "is_active": True,
                "is_deleted": {"$ne": True},
                "_id": {"$ne": reg["_id"]},
            })
            reg_data["has_conflict"] = conflicts > 0
        else:
            reg_data["has_conflict"] = False
        
        result.append(reg_data)
    
    return result
 
 
@api_router.get("/admin/cs-registrations/{registration_id}")
async def get_cs_registration(registration_id: str, admin=Depends(get_admin_user)):
    """Get a specific CS registration."""
    reg = await db.cs_registrations.find_one({"_id": to_query_id(registration_id), "is_deleted": {"$ne": True}})
    if not reg:
        raise HTTPException(status_code=404, detail="CS registration not found")
    return serialize_id(reg)
 
 
@api_router.put("/admin/cs-registrations/{registration_id}")
async def update_cs_registration(
    registration_id: str,
    data: CSRegistrationUpdate,
    admin=Depends(get_admin_user),
):
    """Update a CS registration."""
    now = datetime.now(timezone.utc)
    update = {"updated_at": now}
    
    if data.full_name is not None:
        update["full_name"] = data.full_name.strip()
    if data.license_number is not None:
        update["license_number"] = data.license_number.strip()
        update["license_number_normalized"] = data.license_number.strip().upper()
    if data.nyc_id_email is not None:
        update["nyc_id_email"] = data.nyc_id_email.strip().lower() or None
    if data.sst_number is not None:
        update["sst_number"] = data.sst_number.strip() or None
    if data.phone is not None:
        update["phone"] = data.phone.strip() or None
    if data.is_active is not None:
        update["is_active"] = data.is_active
        if not data.is_active:
            update["deactivated_at"] = now
    
    result = await db.cs_registrations.update_one(
        {"_id": to_query_id(registration_id)},
        {"$set": update}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="CS registration not found")
    
    updated = await db.cs_registrations.find_one({"_id": to_query_id(registration_id)})
    return serialize_id(updated)
 
 
@api_router.delete("/admin/cs-registrations/{registration_id}")
async def delete_cs_registration(registration_id: str, admin=Depends(get_admin_user)):
    """Soft-delete a CS registration."""
    await db.cs_registrations.update_one(
        {"_id": to_query_id(registration_id)},
        {"$set": {"is_deleted": True, "is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "CS registration deleted"}
 
 
@api_router.get("/cs/project/{project_id}")
async def get_project_cs(project_id: str, current_user=Depends(get_current_user)):
    """Get the active CS for a project. Used by site device to auto-fill superintendent info."""
    
    cs = await db.cs_registrations.find_one({
        "project_id": project_id,
        "is_active": True,
        "is_deleted": {"$ne": True},
    })
    
    if not cs:
        return {"registered": False}
    
    return {
        "registered": True,
        "id": str(cs["_id"]),
        "full_name": cs.get("full_name"),
        "license_number": cs.get("license_number"),
        "nyc_id_email": cs.get("nyc_id_email"),
        "sst_number": cs.get("sst_number"),
    }
 
 
# ==================== COMPLIANCE ALERTS ENDPOINTS ====================
 
@api_router.get("/admin/compliance-alerts")
async def get_compliance_alerts(
    resolved: Optional[bool] = None,
    admin=Depends(get_admin_user),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get compliance alerts for the admin dashboard."""
    
    company_id = get_user_company_id(admin)
    query = {}
    if company_id:
        query["company_id"] = company_id
    if resolved is not None:
        query["resolved"] = resolved
    
    result = await paginated_query(db.compliance_alerts, query, limit=limit, skip=skip)
    return result
	
 
@api_router.put("/admin/compliance-alerts/{alert_id}/resolve")
async def resolve_compliance_alert(alert_id: str, admin=Depends(get_admin_user)):
    """Mark a compliance alert as resolved."""
    now = datetime.now(timezone.utc)
    await db.compliance_alerts.update_one(
        {"_id": to_query_id(alert_id)},
        {"$set": {"resolved": True, "resolved_at": now, "resolved_by": admin.get("id")}}
    )
    return {"message": "Alert resolved"}
 
 
# ==================== PER-LOG-TYPE PDF ENDPOINT ====================
 
@api_router.get("/reports/logbook/{logbook_id}/pdf")
async def get_single_logbook_pdf(logbook_id: str, token: Optional[str] = None, current_user=Depends(get_current_user)):
    """Generate PDF for a single logbook entry (per-type PDF).
    Reuses the combined report HTML generator but filters to one log type."""
    from fastapi.responses import Response
    
    logbook = await db.logbooks.find_one({"_id": to_query_id(logbook_id), "is_deleted": {"$ne": True}})
    if not logbook:
        raise HTTPException(status_code=404, detail="Logbook not found")
    
    project_id = logbook.get("project_id")
    date = logbook.get("date")
    log_type = logbook.get("log_type")
    
    # Generate full report HTML but we'll use it as-is since it filters by date
    # For a single-type PDF, generate targeted HTML
    html = await generate_single_logbook_html(logbook)
    
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")
    
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = (project.get("name", "report") if project else "report").replace(" ", "_")
    type_label = log_type.replace("_", "-") if log_type else "log"
    filename = f"Levelog_{type_label}_{project_name}_{date}.pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
 
 
async def generate_single_logbook_html(logbook: dict) -> str:
    """Generate standalone HTML for a single logbook entry.
    Reuses the same styling as the combined report."""
    
    BASE_URL = "https://api.levelog.com"
    
    project_id = logbook.get("project_id")
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = project.get("name", "Unknown") if project else "Unknown"
    project_address = project.get("address", "") if project else ""
    date = logbook.get("date", "N/A")
    log_type = logbook.get("log_type", "unknown")
    data = logbook.get("data", {})
    
    gen_time = datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p')
    
    # Reuse existing style constants
    TH = (
        'style="background-color:#1e293b;color:#ffffff;padding:10px 12px;'
        'text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;'
        'letter-spacing:0.5px;" bgcolor="#1e293b"'
    )
    TD = 'style="padding:10px 12px;border-bottom:1px solid #e2e8f0;color:#334155;"'
    
    def section_title(text):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="margin:28px 0 12px 0;">'
            '<tr><td style="font-size:16px;font-weight:600;color:#0A1929;'
            f'padding-bottom:8px;border-bottom:2px solid #e2e8f0;">{text}</td></tr></table>'
        )
    
    def bold_para(label, value):
        return f'<p style="color:#475569;margin:6px 0;"><strong style="color:#0A1929;">{label}:</strong> {value}</p>'
    
    def info_box(content):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
            'style="margin:12px 0;"><tr><td style="background-color:#f1f5f9;'
            f'padding:16px;border-radius:8px;color:#334155;" bgcolor="#f1f5f9">{content}</td></tr></table>'
        )
    
    # Build type-specific content
    body_html = ""
    type_title = ""
    
    if log_type == "daily_jobsite":
        type_title = "Daily Jobsite Log (NYC DOB 3301-02)"
        weather_str = f'{data.get("weather", "N/A")} {data.get("weather_temp", "")}'
        if data.get("weather_wind"):
            weather_str += f' — Wind: {data["weather_wind"]}'
        
        # Activities table
        act_rows = ""
        for i, act in enumerate(data.get("activities", [])):
            act_rows += (
                f'<tr><td {TD}>{act.get("crew_name", "")}</td>'
                f'<td {TD}>{act.get("company", "N/A")}</td>'
                f'<td {TD}>{act.get("num_workers", 0)}</td>'
                f'<td {TD}>{act.get("work_description", "N/A")}</td>'
                f'<td {TD}>{act.get("work_locations", "")}</td></tr>'
            )
        
        equip = data.get("equipment_on_site", {})
        equip_list = ", ".join(k.replace("_", " ").title() for k, v in equip.items() if v)
        chk = data.get("checklist_items", {})
        check_list = ", ".join(k.replace("_", " ").title() for k, v in chk.items() if v)
        
        # Observations
        obs_html = ""
        obs_rows = ""
        for obs in data.get("observations", []):
            if obs.get("description", "").strip():
                obs_rows += (
                    f'<tr><td {TD}>{obs.get("description", "")}</td>'
                    f'<td {TD}>{obs.get("responsible_party", "")}</td>'
                    f'<td {TD}>{obs.get("remedy", "")}</td></tr>'
                )
        if obs_rows:
            obs_html = (
                '<h3 style="color:#0A1929;margin:16px 0 8px;">Safety Observations</h3>'
                '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
                'style="border-collapse:collapse;font-size:13px;">'
                f'<tr><th {TH}>Description</th><th {TH}>Responsible</th><th {TH}>Remedy</th></tr>'
                + obs_rows + '</table>'
            )
        
        cp_sig = render_signature_html(logbook.get("cp_signature"), "CP Signature")
        sup_sig = render_signature_html(data.get("superintendent_signature"), "Superintendent")
        visitors = data.get("visitors_deliveries", "")
        
        body_html = (
            info_box(
                f'<strong style="color:#0A1929;">Weather:</strong> {weather_str}<br />'
                f'<strong style="color:#0A1929;">Description:</strong> {data.get("general_description", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Time In:</strong> {data.get("time_in") or "N/A"}'
                f' &nbsp;&nbsp; <strong style="color:#0A1929;">Time Out:</strong> {data.get("time_out") or "N/A"}<br />'
                f'<strong style="color:#0A1929;">Areas Visited:</strong> {data.get("areas_visited") or "N/A"}'
            )
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Crew</th><th {TH}>Company</th><th {TH}>Workers</th>'
              f'<th {TH}>Description</th><th {TH}>Location</th></tr>'
            + (act_rows or f'<tr><td colspan="5" {TD}>—</td></tr>')
            + '</table>'
            + bold_para("Equipment", equip_list or "None")
            + bold_para("Inspected", check_list or "None")
            + obs_html
            + (bold_para("Visitors / Deliveries", visitors) if visitors else "")
            + bold_para("CP", logbook.get("cp_name", "N/A"))
            + cp_sig + sup_sig
        )
    
    elif log_type == "toolbox_talk":
        type_title = "Tool Box Talk"
        topics = data.get("checked_topics", {})
        topic_list = ", ".join(k.replace("_", " ").title() for k, v in topics.items() if v)
        
        att_rows = ""
        for a in data.get("attendees", []):
            signed = "&#10003;" if a.get("signed") else "&mdash;"
            att_rows += (
                f'<tr><td {TD}>{a.get("name", "")}</td>'
                f'<td {TD}>{a.get("company", "")}</td>'
                f'<td {TD}>{signed}</td></tr>'
            )
        
        tb_sig = render_signature_html(logbook.get("cp_signature"), "CP Signature")
        
        body_html = (
            info_box(
                f'<strong style="color:#0A1929;">Location:</strong> {data.get("location", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Company:</strong> {data.get("company_name", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Performed By:</strong> {data.get("performed_by", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Time:</strong> {data.get("meeting_time", "N/A")}'
            )
            + bold_para("Topics", topic_list or "None")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Name</th><th {TH}>Company</th><th {TH}>Signed</th></tr>'
            + (att_rows or f'<tr><td colspan="3" {TD}>—</td></tr>')
            + '</table>'
            + bold_para("CP", logbook.get("cp_name", "N/A"))
            + tb_sig
        )
    
    elif log_type == "preshift_signin":
        type_title = "Pre-Shift Sign-In"
        workers = data.get("workers", [])
        
        w_rows = ""
        for w in workers:
            if w.get("name", "").strip():
                w_rows += (
                    f'<tr><td {TD}>{w.get("name", "")}</td>'
                    f'<td {TD}>{w.get("company", "")}</td>'
                    f'<td {TD}>{w.get("osha_number", "")}</td>'
                    f'<td {TD}>{w.get("had_injury") or "&mdash;"}</td>'
                    f'<td {TD}>{w.get("inspected_ppe") or "&mdash;"}</td></tr>'
                )
        
        ps_sig = render_signature_html(logbook.get("cp_signature"), "CP Signature")
        
        body_html = (
            info_box(
                f'<strong style="color:#0A1929;">Company:</strong> {data.get("company", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Location:</strong> {data.get("project_location", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Total Workers:</strong> {data.get("total_count", len(workers))}'
            )
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Name</th><th {TH}>Company</th><th {TH}>OSHA #</th>'
              f'<th {TH}>Injury</th><th {TH}>PPE</th></tr>'
            + (w_rows or f'<tr><td colspan="5" {TD}>—</td></tr>')
            + '</table>'
            + bold_para("CP", logbook.get("cp_name", "N/A"))
            + ps_sig
        )
    
    else:
        type_title = log_type.replace("_", " ").title()
        body_html = bold_para("Status", logbook.get("status", "N/A"))
    
    # Wrap in full HTML document
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{type_title} — {project_name} — {date}</title>
<style>body{{font-family:Arial,sans-serif;margin:0;padding:0;color:#334155;background:#fff;}}
table{{border-collapse:collapse;}}
</style></head>
<body style="margin:0;padding:0;background-color:#ffffff;">
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:700px;margin:0 auto;">
<tr><td style="background-color:#0A1929;padding:24px 40px;color:#fff;" bgcolor="#0A1929">
<span style="font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#60a5fa;">LEVELOG</span><br/>
<span style="font-size:20px;font-weight:600;">{type_title}</span><br/>
<span style="font-size:13px;color:#94a3b8;">{project_name} — {project_address}</span>
<table cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;"><tr>
<td style="padding-right:24px;vertical-align:top;"><span style="font-size:10px;text-transform:uppercase;color:#64748b;">DATE</span><br/><span style="font-size:15px;color:#fff;">{date}</span></td>
<td style="vertical-align:top;"><span style="font-size:10px;text-transform:uppercase;color:#64748b;">STATUS</span><br/><span style="font-size:15px;color:#fff;">{logbook.get("status", "N/A").upper()}</span></td>
</tr></table>
</td></tr>
<tr><td style="padding:24px 40px;background-color:#ffffff;" bgcolor="#ffffff">
{section_title(type_title)}
{body_html}
</td></tr>
<tr><td style="background-color:#f8fafc;padding:24px 40px;text-align:center;border-top:1px solid #e2e8f0;" bgcolor="#f8fafc">
<span style="font-size:11px;color:#94a3b8;">Generated on {gen_time} UTC</span><br/>
<span style="font-size:10px;color:#cbd5e1;letter-spacing:3px;">LEVELOG CONSTRUCTION MANAGEMENT</span>
</td></tr></table></body></html>"""
    
    return html
	
# ==================== STATS / DASHBOARD ====================
@api_router.get("/stats/dashboard")
async def get_dashboard_stats(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    today_start, today_end = get_today_range_est()
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    total_workers = await db.workers.count_documents(query)

    on_site_query = {**query, "status": "checked_in"}
    unique_on_site = await db.checkins.distinct("worker_id", on_site_query)
    on_site_now = len(unique_on_site)
    
    project_query = {**query, "status": "active"}
    total_projects = await db.projects.count_documents(project_query)
    
    today_query = {**query, "check_in_time": {"$gte": today_start, "$lt": today_end}}
    today_checkins = await db.checkins.count_documents(today_query)
    
    return {
        "total_workers": total_workers,
        "total_projects": total_projects,
        "on_site_now": on_site_now,
        "today_checkins": today_checkins
    }
    


# ==================== PROJECT CHECKLISTS ====================

@api_router.get("/projects/{project_id}/checklists")
async def get_project_checklists(project_id: str, current_user = Depends(get_current_user)):
    """Get all checklist assignments for a project"""
    assignments = await db.checklist_assignments.find({
        "project_id": project_id,
        "is_deleted": {"$ne": True}
    }).to_list(200)
    
    result = []
    for assignment in assignments:
        checklist = await db.checklists.find_one({"_id": to_query_id(assignment["checklist_id"])})
        if checklist:
            item = serialize_id(dict(assignment))
            item["checklist_title"] = checklist.get("title", "")
            item["checklist_items"] = checklist.get("items", [])
            result.append(item)
    
    return result

# ==================== ADMIN CHECKLISTS ====================

@api_router.get("/admin/checklists")
async def get_checklists(admin = Depends(get_admin_user)):
    """Get all checklists for the admin's company"""
    company_id = get_user_company_id(admin)
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    checklists = await db.checklists.find(query).sort("created_at", -1).to_list(200)
    result = []
    for cl in checklists:
        serialized = serialize_id(cl)
        # Get creator name
        if cl.get("created_by"):
            creator = await db.users.find_one({"_id": to_query_id(cl["created_by"])})
            serialized["created_by_name"] = creator.get("name") if creator else "Unknown"
        result.append(serialized)
    return result

@api_router.post("/admin/checklists")
async def create_checklist(checklist_data: ChecklistCreate, admin = Depends(get_admin_user)):
    """Create a new checklist"""
    company_id = get_user_company_id(admin)
    now = datetime.now(timezone.utc)
    
    # Add IDs to items if not present
    items = []
    for i, item in enumerate(checklist_data.items):
        if "id" not in item:
            item["id"] = str(uuid.uuid4())
        if "order" not in item:
            item["order"] = i
        items.append(item)
    
    checklist_dict = {
        "title": checklist_data.title,
        "description": checklist_data.description,
        "items": items,
        "company_id": company_id,
        "created_by": admin.get("id"),
        "created_at": now,
        "updated_at": now,
        "is_deleted": False
    }
    
    result = await db.checklists.insert_one(checklist_dict)
    checklist_dict["id"] = str(result.inserted_id)
    checklist_dict.pop("_id", None)
    
    # Add creator name
    checklist_dict["created_by_name"] = admin.get("name")
    
    return checklist_dict

@api_router.get("/admin/checklists/{checklist_id}")
async def get_checklist(checklist_id: str, admin = Depends(get_admin_user)):
    """Get a single checklist by ID"""
    checklist = await db.checklists.find_one({"_id": to_query_id(checklist_id), "is_deleted": {"$ne": True}})
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    serialized = serialize_id(checklist)
    if checklist.get("created_by"):
        creator = await db.users.find_one({"_id": to_query_id(checklist["created_by"])})
        serialized["created_by_name"] = creator.get("name") if creator else "Unknown"
    
    return serialized

@api_router.put("/admin/checklists/{checklist_id}")
async def update_checklist(checklist_id: str, checklist_data: dict, admin = Depends(get_admin_user)):
    """Update a checklist"""
    update_fields = {}
    if "title" in checklist_data:
        update_fields["title"] = checklist_data["title"]
    if "description" in checklist_data:
        update_fields["description"] = checklist_data["description"]
    if "items" in checklist_data:
        items = []
        for i, item in enumerate(checklist_data["items"]):
            if "id" not in item:
                item["id"] = str(uuid.uuid4())
            if "order" not in item:
                item["order"] = i
            items.append(item)
        update_fields["items"] = items
    
    update_fields["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.checklists.update_one(
        {"_id": to_query_id(checklist_id), "is_deleted": {"$ne": True}},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    checklist = await db.checklists.find_one({"_id": to_query_id(checklist_id)})
    return serialize_id(checklist)

@api_router.delete("/admin/checklists/{checklist_id}")
async def delete_checklist(checklist_id: str, admin = Depends(get_admin_user)):
    """Soft delete a checklist"""
    result = await db.checklists.update_one(
        {"_id": to_query_id(checklist_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    # Also soft-delete related assignments
    await db.checklist_assignments.update_many(
        {"checklist_id": checklist_id},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"message": "Checklist deleted successfully"}

@api_router.post("/admin/checklists/{checklist_id}/assign")
async def assign_checklist(checklist_id: str, assignment_data: ChecklistAssignmentCreate, admin = Depends(get_admin_user)):
    """Assign a checklist to projects and users"""
    checklist = await db.checklists.find_one({"_id": to_query_id(checklist_id), "is_deleted": {"$ne": True}})
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    now = datetime.now(timezone.utc)
    company_id = get_user_company_id(admin)
    created_assignments = []
    
    for project_id in assignment_data.project_ids:
        # Check if assignment already exists
        existing = await db.checklist_assignments.find_one({
            "checklist_id": checklist_id,
            "project_id": project_id,
            "is_deleted": {"$ne": True}
        })
        if existing:
            # Update existing assignment's users
            await db.checklist_assignments.update_one(
                {"_id": existing["_id"]},
                {"$set": {"assigned_user_ids": assignment_data.user_ids, "updated_at": now}}
            )
            continue
        
        # Get project name
        project = await db.projects.find_one({"_id": to_query_id(project_id)})
        project_name = project.get("name", "") if project else ""
        
        # Get user details
        assigned_users = []
        for user_id in assignment_data.user_ids:
            user = await db.users.find_one({"_id": to_query_id(user_id)})
            if user:
                assigned_users.append({"id": user_id, "name": user.get("name", "")})
        
        assignment_dict = {
            "checklist_id": checklist_id,
            "checklist_title": checklist.get("title", ""),
            "project_id": project_id,
            "project_name": project_name,
            "assigned_user_ids": assignment_data.user_ids,
            "assigned_users": assigned_users,
            "company_id": company_id,
            "created_by": admin.get("id"),
            "created_at": now,
            "updated_at": now,
            "is_deleted": False
        }
        
        result = await db.checklist_assignments.insert_one(assignment_dict)
        assignment_dict["id"] = str(result.inserted_id)
        assignment_dict.pop("_id", None)
        created_assignments.append(assignment_dict)
    
    return created_assignments

@api_router.get("/admin/checklists/{checklist_id}/assignments")
async def get_checklist_assignments(checklist_id: str, admin = Depends(get_admin_user)):
    """Get all assignments for a checklist"""
    assignments = await db.checklist_assignments.find({
        "checklist_id": checklist_id,
        "is_deleted": {"$ne": True}
    }).to_list(200)
    
    result = []
    for assignment in assignments:
        serialized = serialize_id(dict(assignment))
        
        # Get completion stats — use count instead of fetching all docs
        completion_count = await db.checklist_completions.count_documents({
            "assignment_id": str(assignment["_id"]) if "_id" in assignment else assignment.get("id")
        })
        
        serialized["completion_stats"] = {
            "total_assigned": len(assignment.get("assigned_user_ids", [])),
            "completed": completion_count
        }
        result.append(serialized)
    
    return result

# ==================== USER CHECKLISTS ====================

@api_router.get("/checklists/assigned")
async def get_assigned_checklists(current_user = Depends(get_current_user)):
    """Get checklists assigned to the current user"""
    user_id = current_user.get("id")
    
    assignments = await db.checklist_assignments.find({
        "assigned_user_ids": user_id,
        "is_deleted": {"$ne": True}
    }).to_list(200)
    
    result = []
    for assignment in assignments:
        checklist = await db.checklists.find_one({"_id": to_query_id(assignment["checklist_id"])})
        if not checklist:
            continue
        
        serialized = serialize_id(dict(assignment))
        serialized["checklist_title"] = checklist.get("title", "")
        serialized["checklist_items"] = checklist.get("items", [])
        
        # Check if user has completed this
        completion = await db.checklist_completions.find_one({
            "assignment_id": str(assignment["_id"]),
            "user_id": user_id
        })
        serialized["is_completed"] = completion is not None
        serialized["completion"] = serialize_id(dict(completion)) if completion else None
        
        result.append(serialized)
    
    return result

@api_router.get("/checklists/assignments/{assignment_id}")
async def get_assignment_details(assignment_id: str, current_user = Depends(get_current_user)):
    """Get details of a specific checklist assignment"""
    assignment = await db.checklist_assignments.find_one({
        "_id": to_query_id(assignment_id),
        "is_deleted": {"$ne": True}
    })
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    checklist = await db.checklists.find_one({"_id": to_query_id(assignment["checklist_id"])})
    
    serialized = serialize_id(dict(assignment))
    if checklist:
        serialized["checklist_title"] = checklist.get("title", "")
        serialized["checklist_items"] = checklist.get("items", [])
    
    # Get user's completion
    user_id = current_user.get("id")
    completion = await db.checklist_completions.find_one({
        "assignment_id": assignment_id,
        "user_id": user_id
    })
    serialized["completion"] = serialize_id(dict(completion)) if completion else None
    
    return serialized

@api_router.put("/checklists/assignments/{assignment_id}/complete")
async def complete_checklist(assignment_id: str, completion_data: ChecklistCompletionUpdate, current_user = Depends(get_current_user)):
    """Submit or update checklist completion"""
    assignment = await db.checklist_assignments.find_one({
        "_id": to_query_id(assignment_id),
        "is_deleted": {"$ne": True}
    })
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    user_id = current_user.get("id")
    now = datetime.now(timezone.utc)
    
    # Check if completion already exists
    existing = await db.checklist_completions.find_one({
        "assignment_id": assignment_id,
        "user_id": user_id
    })
    
    completion_dict = {
        "assignment_id": assignment_id,
        "checklist_id": assignment.get("checklist_id"),
        "project_id": assignment.get("project_id"),
        "user_id": user_id,
        "user_name": current_user.get("name", ""),
        "item_completions": completion_data.item_completions,
        "updated_at": now,
    }
    
    if existing:
        await db.checklist_completions.update_one(
            {"_id": existing["_id"]},
            {"$set": completion_dict}
        )
        completion_dict["id"] = str(existing["_id"])
    else:
        completion_dict["created_at"] = now
        result = await db.checklist_completions.insert_one(completion_dict)
        completion_dict["id"] = str(result.inserted_id)
    
    completion_dict.pop("_id", None)
    return completion_dict

# ==================== REPORTS ====================

@api_router.get("/reports")
async def get_reports(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    reports = await db.reports.find(query).sort("created_at", -1).to_list(200)
    return serialize_list(reports)

@api_router.get("/reports/project/{project_id}")
async def get_project_reports(project_id: str, current_user = Depends(get_current_user)):
    reports = await db.reports.find({"project_id": project_id, "is_deleted": {"$ne": True}}).sort("created_at", -1).to_list(200)
    return serialize_list(reports)

# ==================== DROPBOX INTEGRATION ====================

@api_router.get("/dropbox/status")
async def get_dropbox_status(current_user = Depends(get_current_user)):
    """Check if Dropbox is connected for current user's company"""
    company_id = get_user_company_id(current_user)
    if not company_id:
        return {"connected": False}
    
    connection = await db.dropbox_connections.find_one({
        "company_id": company_id,
        "is_deleted": {"$ne": True}
    })
    
    if connection and connection.get("access_token"):
        return {
            "connected": True,
            "account_name": connection.get("account_name", ""),
            "connected_at": connection.get("connected_at"),
        }
    return {"connected": False}

@api_router.get("/dropbox/auth-url")
async def get_dropbox_auth_url(current_user = Depends(get_current_user)):
    """Get Dropbox OAuth authorization URL"""
    state = jwt.encode(
        {"user_id": current_user.get("id"), "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        JWT_SECRET, algorithm=JWT_ALGORITHM
    )
    auth_url = (
        f"https://www.dropbox.com/oauth2/authorize"
        f"?client_id={DROPBOX_APP_KEY}"
        f"&redirect_uri={DROPBOX_REDIRECT_URI}"
        f"&response_type=code"
        f"&token_access_type=offline"
        f"&state={state}"
    )
    return {"auth_url": auth_url}

@api_router.get("/dropbox/callback")
async def dropbox_callback(code: str = None, state: str = None, error: str = None):
    """Handle Dropbox OAuth callback"""
    from fastapi.responses import HTMLResponse
    
    if error:
        return HTMLResponse(f"<html><body><h2>Dropbox connection failed</h2><p>{error}</p><script>window.close();</script></body></html>")
    
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    
    # Verify state
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["user_id"]
    except (jwt.InvalidTokenError, KeyError, Exception) as e:
        logger.warning(f"Dropbox callback state validation failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid state")
    
    # Exchange code for token
    async with ServerHttpClient() as client_http:
        token_response = await client_http.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": DROPBOX_APP_KEY,
                "client_secret": DROPBOX_APP_SECRET,
                "redirect_uri": DROPBOX_REDIRECT_URI,
            }
        )
    
    if token_response.status_code != 200:
        try:
            err = token_response.json()
            msg = (
                err.get("error_description")
                or err.get("error_summary")
                or err.get("error")
                or "Connection failed"
            )
        except Exception:
            msg = token_response.text[:300] if token_response.text else "Unknown error"
        return HTMLResponse(
            f"""<html><body style="font-family:sans-serif;padding:40px;background:#0a0e1a;color:#f1f5f9;text-align:center">
            <h2 style="color:#ef4444;margin-bottom:16px">Dropbox Connection Failed</h2>
            <p style="color:#94a3b8;margin-bottom:12px">{msg}</p>
            <p style="color:#64748b;font-size:13px">If this says 'too_many_users': go to dropbox.com/developers/apps
            and either submit the app for Production or add this user email as a Tester.</p>
            <script>setTimeout(()=>window.close(),8000);</script>
            </body></html>""",
            status_code=200,
        )
    
    token_data = token_response.json()
    
    # Get account info
    async with ServerHttpClient() as client_http:
        account_response = await client_http.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
    
    account_name = ""
    if account_response.status_code == 200:
        account_info = account_response.json()
        account_name = account_info.get("name", {}).get("display_name", "")
    
    # Get user's company
    user = await db.users.find_one({"_id": to_query_id(user_id)})
    company_id = user.get("company_id") if user else None
    
    now = datetime.now(timezone.utc)
    
    # Store connection
    expires_at = now + timedelta(seconds=token_data.get("expires_in", 14400))
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {
            "company_id": company_id,
            "user_id": user_id,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "account_id": token_data.get("account_id"),
            "account_name": account_name,
            "access_token_expires_at": expires_at,
            "connected_at": now,
            "updated_at": now,
            "is_deleted": False,
        }},
        upsert=True
    )
    
    # Use specific origin instead of '*' to prevent cross-origin message interception
    allowed_origin = ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "https://levelog.com"
    return HTMLResponse(f"<html><body><h2>Dropbox connected successfully!</h2><p>You can close this window.</p><script>window.opener && window.opener.postMessage('dropbox-connected','{allowed_origin}'); setTimeout(()=>window.close(), 2000);</script></body></html>")

@api_router.post("/dropbox/complete-auth")
async def complete_dropbox_auth(data: dict, current_user = Depends(get_current_user)):
    """Complete Dropbox OAuth with authorization code (alternative to callback)"""
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code required")
    
    async with ServerHttpClient() as client_http:
        token_response = await client_http.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": DROPBOX_APP_KEY,
                "client_secret": DROPBOX_APP_SECRET,
                "redirect_uri": DROPBOX_REDIRECT_URI,
            }
        )
    
    if token_response.status_code != 200:
        try:
            err = token_response.json()
            msg = (err.get("error_description") or err.get("error") or "Token exchange failed")
        except Exception:
            msg = token_response.text[:200] or "Token exchange failed"
        raise HTTPException(status_code=422, detail=f"Dropbox error: {msg}")

    token_data = token_response.json()
    company_id = get_user_company_id(current_user)
    now = datetime.now(timezone.utc)
    
    # Get account info
    async with ServerHttpClient() as client_http:
        account_response = await client_http.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
    
    account_name = ""
    if account_response.status_code == 200:
        account_info = account_response.json()
        account_name = account_info.get("name", {}).get("display_name", "")
    
    expires_at = now + timedelta(seconds=token_data.get("expires_in", 14400))
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {
            "company_id": company_id,
            "user_id": current_user.get("id"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "account_id": token_data.get("account_id"),
            "account_name": account_name,
            "access_token_expires_at": expires_at,
            "connected_at": now,
            "updated_at": now,
            "is_deleted": False,
        }},
        upsert=True
    )

    return {"message": "Dropbox connected successfully", "account_name": account_name}

@api_router.delete("/dropbox/disconnect")
async def disconnect_dropbox(current_user = Depends(get_current_user)):
    """Disconnect Dropbox"""
    company_id = get_user_company_id(current_user)
    
    # Revoke token
    connection = await db.dropbox_connections.find_one({"company_id": company_id})
    if connection and connection.get("access_token"):
        try:
            async with ServerHttpClient() as client_http:
                await client_http.post(
                    "https://api.dropboxapi.com/2/auth/token/revoke",
                    headers={"Authorization": f"Bearer {connection['access_token']}"}
                )
        except Exception as e:
            logger.warning(f"Dropbox token revocation failed (non-blocking): {e}")
    
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {"is_deleted": True, "access_token": None, "refresh_token": None, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"message": "Dropbox disconnected"}

async def get_valid_dropbox_token(company_id: str) -> str:
    """Get a valid Dropbox access token, proactively refreshing if expired or expiring within 30 min."""
    connection = await db.dropbox_connections.find_one({
        "company_id": company_id, "is_deleted": {"$ne": True}
    })
    if not connection:
        raise HTTPException(status_code=400, detail="Dropbox not connected")

    # Check if token is still valid (with 30-min buffer).
    # PyMongo returns datetimes as offset-naive by default, even though we
    # store them as aware UTC — coerce before comparing, otherwise Python
    # raises "can't compare offset-naive and offset-aware datetimes".
    expires_at = connection.get("access_token_expires_at")
    if expires_at and isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc) + timedelta(minutes=30):
            return connection["access_token"]

    # Token expired or no expiry stored — refresh
    refresh_token = connection.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token. Please reconnect Dropbox.")

    try:
        async with ServerHttpClient(timeout=15.0) as c:
            resp = await c.post("https://api.dropboxapi.com/oauth2/token", data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": DROPBOX_APP_KEY,
                "client_secret": DROPBOX_APP_SECRET,
            })
        if resp.status_code != 200:
            logger.error(f"Dropbox token refresh failed: {resp.status_code} {resp.text}")
            raise HTTPException(status_code=401, detail="Dropbox token refresh failed. Please reconnect.")

        token_data = resp.json()
        new_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 14400)  # default 4 hours
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        await db.dropbox_connections.update_one(
            {"company_id": company_id},
            {"$set": {
                "access_token": new_token,
                "access_token_expires_at": new_expires_at,
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        logger.info(f"Dropbox token refreshed for company {company_id}, expires at {new_expires_at}")
        return new_token
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dropbox token refresh error: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh Dropbox token")

async def dropbox_api_call(company_id: str, method: str, url: str, **kwargs):
    """Make Dropbox API call with automatic token refresh"""
    token = await get_valid_dropbox_token(company_id)

    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    async with ServerHttpClient() as client_http:
        response = await getattr(client_http, method)(url, headers=headers, **kwargs)

    # Safety net: if 401 despite proactive refresh, force-refresh once more
    if response.status_code == 401:
        token = await get_valid_dropbox_token(company_id)
        headers["Authorization"] = f"Bearer {token}"
        async with ServerHttpClient() as client_http:
            response = await getattr(client_http, method)(url, headers=headers, **kwargs)

    return response

@api_router.get("/dropbox/folders")
async def get_dropbox_folders(path: str = "", current_user = Depends(get_current_user)):
    """Get Dropbox folders for selection.

    Dropbox quirk: the root path MUST be the empty string, NOT '/'. If the
    client passes '/', Dropbox returns 400 malformed_path. We also include
    shared and mounted folders so users of Dropbox Business accounts see
    team-shared folders in the picker.
    """
    company_id = get_user_company_id(current_user)

    # Normalize the path — Dropbox is strict here.
    norm_path = (path or "").strip()
    if norm_path in ("/", ""):
        norm_path = ""  # root
    elif not norm_path.startswith("/"):
        norm_path = "/" + norm_path
    # Strip trailing slash for non-root paths
    if norm_path != "" and norm_path.endswith("/"):
        norm_path = norm_path.rstrip("/")

    try:
        response = await dropbox_api_call(
            company_id, "post",
            "https://api.dropboxapi.com/2/files/list_folder",
            json={
                "path": norm_path,
                "recursive": False,
                "include_mounted_folders": True,
                "include_non_downloadable_files": False,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Dropbox folders request blew up — company={company_id} path={norm_path!r} err={e}"
        )
        raise HTTPException(status_code=500, detail=f"Dropbox request failed: {e}")

    if response.status_code != 200:
        # Surface the actual Dropbox error so the UI / logs tell us what broke
        # (bad_path, expired_token, insufficient_scope, etc.) instead of a
        # generic 400 that forces us to guess.
        body_text = ""
        try:
            body_text = response.text[:500]
        except Exception:
            pass
        logger.error(
            f"Dropbox list_folder failed — company={company_id} path={norm_path!r} "
            f"status={response.status_code} body={body_text!r}"
        )
        # Parse Dropbox's JSON error to produce a user-facing message.
        detail = "Failed to list folders"
        try:
            err = response.json()
            summary = err.get("error_summary") or ""
            tag = (err.get("error", {}) or {}).get(".tag") or ""
            if "insufficient_scope" in summary or "missing_scope" in summary:
                detail = (
                    "Dropbox app is missing the files.metadata.read permission. "
                    "Disconnect and reconnect, or check the Dropbox app permissions."
                )
            elif "expired_access_token" in summary or "invalid_access_token" in summary:
                detail = "Dropbox token expired — please reconnect Dropbox."
            elif tag == "path" or "path/" in summary:
                detail = f"Dropbox rejected path {norm_path!r}: {summary or 'not_found'}"
            elif summary:
                detail = f"Dropbox error: {summary}"
        except Exception:
            if body_text:
                detail = f"Dropbox error: {body_text[:200]}"
        raise HTTPException(status_code=400, detail=detail)

    data = response.json()
    folders = [
        {
            "name": entry["name"],
            "path": entry.get("path_lower") or entry.get("path_display") or "",
            "id": entry.get("id", ""),
        }
        for entry in data.get("entries", [])
        if entry.get(".tag") == "folder"
    ]

    return folders

def _normalize_subfolder_names(names: List[str]) -> List[str]:
    """Strip leading slashes + trailing slashes, drop empties, dedupe
    (case-insensitive by comparison but preserve caller casing).
    Used so both 'Approved Plans' and '/Approved Plans/' end up as
    the single canonical 'Approved Plans' entry."""
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
    """True iff file_path lives under any allowed subfolder of
    folder_path. Path comparison is case-insensitive because Dropbox
    preserves case in `name` but stores a lowercased `path_lower`; we
    call this with either, so normalize both sides."""
    if not file_path or not allowed_subfolders:
        return False
    fp = file_path.lower()
    base = (folder_path or "").lower().rstrip("/")
    # Strip the base project folder prefix so comparisons are relative.
    rel = fp[len(base):] if base and fp.startswith(base) else fp
    rel = rel.lstrip("/")
    for sub in allowed_subfolders:
        sub_low = sub.lower().strip("/").strip()
        if not sub_low:
            continue
        if rel == sub_low or rel.startswith(sub_low + "/"):
            return True
    return False


@api_router.get("/projects/{project_id}/dropbox-subfolders")
async def list_dropbox_subfolders(
    project_id: str, current_user = Depends(get_admin_user)
):
    """Admin-only: list the top-level subfolders under the project's
    linked Dropbox folder. Used by the 'Site Device Visibility' UI to
    render checkboxes for which subfolders the kiosk can see."""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    company_id = company_id or project.get("company_id")
    folder_path = project.get("dropbox_folder_path") or ""
    if not folder_path:
        return {"subfolders": [], "selected": [], "folder_path": ""}

    try:
        # Dropbox wants "" for root, not "/" — translate our stored sentinel.
        api_path = _dropbox_api_path(folder_path)
        resp = await dropbox_api_call(
            company_id, "post",
            "https://api.dropboxapi.com/2/files/list_folder",
            json={"path": api_path, "recursive": False},
        )
        subfolders: List[str] = []
        if resp.status_code == 200:
            for entry in resp.json().get("entries", []):
                if entry.get(".tag") == "folder":
                    subfolders.append(entry.get("name", ""))
            subfolders = [s for s in subfolders if s]
            subfolders.sort(key=lambda x: x.lower())
    except Exception as e:
        logger.warning(
            f"list subfolders failed for project {project_id}: {e}"
        )
        subfolders = []

    return {
        "folder_path": folder_path,
        "subfolders": subfolders,
        "selected": _normalize_subfolder_names(
            project.get("site_device_subfolders") or []
        ),
    }


@api_router.put("/projects/{project_id}/site-device-subfolders")
async def set_site_device_subfolders(
    project_id: str,
    data: dict,
    current_user = Depends(get_admin_user),
):
    """Admin-only: set the list of subfolder names (relative to the
    project's Dropbox folder) that site-device users are allowed to
    see. Passing [] locks site devices out completely (safe default).
    Names are stripped + deduped server-side; do not include slashes.
    """
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    subfolders_raw = data.get("subfolders")
    if not isinstance(subfolders_raw, list):
        raise HTTPException(
            status_code=400,
            detail="subfolders must be an array of folder names",
        )
    cleaned = _normalize_subfolder_names(subfolders_raw)
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": {
            "site_device_subfolders": cleaned,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return {
        "message": "Site device visibility updated",
        "site_device_subfolders": cleaned,
    }


def _dropbox_api_path(stored: str) -> str:
    """Translate an internally-stored folder path to the exact shape
    Dropbox's API expects. We store '/' as a sentinel for 'the root of
    this app's scope' (so `if not folder_path` can still distinguish
    linked-to-root from not-linked). Dropbox requires root as '' not '/'.
    """
    s = (stored or "").strip()
    if s in ("", "/"):
        return ""
    if not s.startswith("/"):
        s = "/" + s
    return s.rstrip("/")


@api_router.post("/projects/{project_id}/link-dropbox")
async def link_dropbox_to_project(project_id: str, data: dict, current_user = Depends(get_current_user)):
    """Link or unlink a Dropbox folder for a project.

    - folder_path: None  → unlink (clear dropbox_folder_path)
    - folder_path: "" or "/" → link to root of the app's Dropbox scope
    - folder_path: "/Foo/Bar" → link to that folder (normalized)
    """
    now = datetime.now(timezone.utc)
    folder_path = data.get("folder_path")

    # Explicit null means unlink. Clear the field and return.
    if folder_path is None:
        await db.projects.update_one(
            {"_id": to_query_id(project_id)},
            {
                "$unset": {
                    "dropbox_folder_path": "",
                    "dropbox_linked_at": "",
                    "dropbox_linked_by": "",
                },
                "$set": {"updated_at": now},
            },
        )
        return {"message": "Dropbox folder unlinked", "folder_path": None}

    if not isinstance(folder_path, str):
        raise HTTPException(status_code=400, detail="folder_path must be a string or null")

    raw = folder_path.strip()
    # "" and "/" both mean "link to root". Store as "/" so downstream
    # truthiness checks ('if not folder_path') treat root-linked
    # projects as linked.
    if raw in ("", "/"):
        norm = "/"
    else:
        norm = raw if raw.startswith("/") else "/" + raw
        if norm != "/" and norm.endswith("/"):
            norm = norm.rstrip("/")

    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": {
            "dropbox_folder_path": norm,
            "dropbox_linked_at": now,
            "dropbox_linked_by": current_user.get("id"),
            "updated_at": now,
        }}
    )

    return {"message": "Dropbox folder linked", "folder_path": norm}

@api_router.get("/projects/{project_id}/dropbox-files")
async def get_project_dropbox_files(project_id: str, current_user = Depends(get_current_user)):
    """Get files from project's linked Dropbox folder (R2-backed with Dropbox fallback).

    Role-based visibility: users with role=site_device only see files
    whose path sits under one of the project's site_device_subfolders.
    Empty list → site devices see nothing (safe default). Admins/CPs
    see the full folder regardless.
    """
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    company_id = company_id or project.get("company_id")
    folder_path = project.get("dropbox_folder_path")

    is_site_device = (
        current_user.get("site_mode")
        or current_user.get("role") == "site_device"
    )
    allowed_subfolders = _normalize_subfolder_names(
        project.get("site_device_subfolders") or []
    )

    def _visible_to_site(path: str) -> bool:
        return _path_is_under_allowed_subfolder(
            path, folder_path or "", allowed_subfolders
        )

    # Short-circuit: site device with no subfolders configured sees nothing.
    if is_site_device and not allowed_subfolders:
        return []

    # Check project_files collection first (R2 cache + direct uploads)
    cached_files = await db.project_files.find({
        "project_id": project_id,
        "company_id": company_id,
        "is_deleted": {"$ne": True},
    }).to_list(5000)

    if cached_files:
        files = []
        for rec in cached_files:
            dropbox_path = rec.get("dropbox_path", "")
            if is_site_device and not _visible_to_site(dropbox_path):
                continue
            r2_key = rec.get("r2_key", "")
            stored_url = rec.get("r2_url", "")
            rec_id = str(rec.get("_id", ""))
            # Prefer backend proxy URL (no CORS headaches, enforces auth).
            proxy_url = f"/api/projects/{project_id}/files/{rec_id}/content" if r2_key and rec_id else ""
            files.append({
                "name": rec.get("name", ""),
                "path": dropbox_path,
                "id": rec_id,
                "type": "file",
                "size": rec.get("size", 0),
                "modified": rec.get("modified", ""),
                "r2_url": proxy_url or stored_url,
                "cache_version": rec.get("cache_version", 0),
                "source": rec.get("source", "dropbox_sync"),
            })
        return files

    # No cached records — fall back to live Dropbox listing (only if folder linked)
    if not folder_path:
        return []

    # Dropbox wants "" for root, not "/" — translate our stored sentinel.
    norm_folder = _dropbox_api_path(folder_path)

    # Site devices need a RECURSIVE listing so we can see files inside
    # the allowed subfolders, not just top-level entries.
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": norm_folder, "recursive": bool(is_site_device)}
    )

    if response.status_code != 200:
        body_text = ""
        try:
            body_text = response.text[:500]
        except Exception:
            pass
        logger.error(
            f"Dropbox dropbox-files list_folder failed — company={company_id} "
            f"project={project_id} path={norm_folder!r} status={response.status_code} "
            f"body={body_text!r}"
        )
        detail = "Failed to list files"
        try:
            err = response.json()
            summary = err.get("error_summary") or ""
            if "not_found" in summary:
                detail = f"Dropbox folder {norm_folder!r} not found. Re-link the project to a valid folder."
            elif summary:
                detail = f"Dropbox error: {summary}"
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail)

    data = response.json()
    files = []
    for entry in data.get("entries", []):
        path_lower = entry.get("path_lower", "")
        if is_site_device:
            # Only files; drop any folder entries from the recursive scan.
            if entry.get(".tag") != "file":
                continue
            if not _visible_to_site(path_lower):
                continue
        file_info = {
            "name": entry["name"],
            "path": path_lower,
            "id": entry.get("id", ""),
            "type": entry[".tag"],
            "r2_url": "",
            "cache_version": 0,
        }
        if entry[".tag"] == "file":
            file_info["size"] = entry.get("size", 0)
            file_info["modified"] = entry.get("server_modified", "")
        files.append(file_info)

    # Trigger background sync so next request will use cached records
    asyncio.create_task(_sync_project_to_r2(project_id, company_id, folder_path))

    # Background-warm URL cache for PDFs
    async def _warm_pdf_cache(files_list, cid):
        for f in files_list:
            if f.get("name", "").lower().endswith(".pdf"):
                path = f.get("path", "")
                if path and not _get_cached_url(cid, path):
                    try:
                        resp = await dropbox_api_call(
                            cid, "post",
                            "https://api.dropboxapi.com/2/files/get_temporary_link",
                            json={"path": path}
                        )
                        if resp.status_code == 200:
                            _set_cached_url(cid, path, resp.json().get("link", ""))
                    except Exception:
                        pass
    asyncio.create_task(_warm_pdf_cache(files, company_id))

    return files

async def _sync_project_to_r2(project_id: str, company_id: str, folder_path: str):
    """Background task: sync Dropbox files to R2 and update project_files collection."""
    try:
        # Dropbox wants "" for root, not "/" — translate our stored sentinel.
        api_path = _dropbox_api_path(folder_path)
        response = await dropbox_api_call(
            company_id, "post",
            "https://api.dropboxapi.com/2/files/list_folder",
            json={"path": api_path, "recursive": True}
        )
        if response.status_code != 200:
            logger.error(f"Sync failed for project {project_id}: Dropbox list_folder returned {response.status_code}")
            return

        data = response.json()
        entries = [e for e in data.get("entries", []) if e[".tag"] == "file"]

        # Handle pagination
        while data.get("has_more"):
            cursor_resp = await dropbox_api_call(
                company_id, "post",
                "https://api.dropboxapi.com/2/files/list_folder/continue",
                json={"cursor": data["cursor"]}
            )
            if cursor_resp.status_code != 200:
                break
            data = cursor_resp.json()
            entries.extend([e for e in data.get("entries", []) if e[".tag"] == "file"])

        now = datetime.now(timezone.utc)
        synced = 0

        for entry in entries:
            dropbox_path = entry["path_lower"]
            content_hash = entry.get("content_hash", "")
            filename = entry["name"]

            try:
                existing = await db.project_files.find_one({
                    "project_id": project_id, "dropbox_path": dropbox_path
                })

                if existing and existing.get("dropbox_content_hash") == content_hash and content_hash:
                    # Unchanged — just update last_synced_at
                    await db.project_files.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {"last_synced_at": now}}
                    )
                    synced += 1
                    continue

                # New or changed — download from Dropbox
                dl_resp = await dropbox_api_call(
                    company_id, "post",
                    "https://content.dropboxapi.com/2/files/download",
                    headers={"Dropbox-API-Arg": f'{{"path": "{dropbox_path}"}}'}
                )
                if dl_resp.status_code != 200:
                    logger.warning(f"Sync skip {dropbox_path}: download failed {dl_resp.status_code}")
                    continue

                file_bytes = dl_resp.content
                r2_key = f"{company_id}/{project_id}/{filename}"
                ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                r2_url = ""

                # Upload to R2 (non-blocking)
                if _r2_client:
                    try:
                        r2_url = await asyncio.to_thread(_upload_to_r2, file_bytes, r2_key, ct)
                    except Exception as r2_err:
                        logger.error(f"R2 upload failed for {r2_key}: {r2_err}")

                file_record = {
                    "project_id": project_id,
                    "company_id": company_id,
                    "name": filename,
                    "dropbox_path": dropbox_path,
                    "dropbox_content_hash": content_hash,
                    "r2_key": r2_key if r2_url else "",
                    "r2_url": r2_url,
                    "size": entry.get("size", 0),
                    "modified": entry.get("server_modified", ""),
                    "source": "dropbox_sync",
                    "last_synced_at": now,
                    "updated_at": now,
                }

                if existing:
                    file_record["cache_version"] = existing.get("cache_version", 0) + 1
                    await db.project_files.update_one(
                        {"_id": existing["_id"]},
                        {"$set": file_record}
                    )
                    file_record["_id"] = existing["_id"]
                else:
                    file_record["cache_version"] = 1
                    file_record["created_at"] = now
                    insert_res = await db.project_files.insert_one(file_record)
                    file_record["_id"] = insert_res.inserted_id

                # Sprint 3: spawn plan indexing for PDFs when a file is new/changed.
                # Hash cache inside _index_pdf_file also catches unchanged bytes.
                if (
                    QWEN_API_KEY
                    and filename.lower().endswith(".pdf")
                    and r2_url
                ):
                    asyncio.create_task(
                        _index_pdf_file(project_id, company_id, dict(file_record))
                    )

                synced += 1
            except Exception as entry_err:
                logger.error(f"Sync error for {dropbox_path}: {entry_err}")

        # Update sync timestamp
        await db.projects.update_one(
            {"_id": to_query_id(project_id)},
            {"$set": {"dropbox_last_synced": now}}
        )
        logger.info(f"Sync complete for project {project_id}: {synced}/{len(entries)} files")

    except Exception as e:
        logger.error(f"Background sync failed for project {project_id}: {e}")


@api_router.post("/projects/{project_id}/sync-dropbox")
async def sync_project_dropbox(project_id: str, current_user = Depends(get_current_user)):
    """Sync/refresh project files from Dropbox — returns immediately, runs sync in background"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    folder_path = project.get("dropbox_folder_path")
    if not folder_path:
        raise HTTPException(status_code=400, detail="No Dropbox folder linked")

    company_id = company_id or project.get("company_id")

    # Dropbox wants "" for root, not "/" — translate our stored sentinel.
    api_path = _dropbox_api_path(folder_path)

    # Quick count from Dropbox for immediate response
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": api_path, "recursive": True}
    )

    file_count = 0
    if response.status_code == 200:
        data = response.json()
        file_count = len([e for e in data.get("entries", []) if e[".tag"] == "file"])

    # Launch background sync
    asyncio.create_task(_sync_project_to_r2(project_id, company_id, folder_path))

    return {"message": "Sync started", "file_count": file_count}

@api_router.get("/projects/{project_id}/dropbox-file-url")
async def get_dropbox_file_url(project_id: str, file_path: str, current_user = Depends(get_current_user)):
    """Get a download/preview URL for a project file (R2 preferred, Dropbox fallback)"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    company_id = company_id or project.get("company_id")

    # Check project_files for R2 URL first (company-scoped)
    file_rec = await db.project_files.find_one({
        "project_id": project_id, "company_id": company_id, "dropbox_path": file_path
    })
    if file_rec and file_rec.get("r2_key"):
        proxy = f"/api/projects/{project_id}/files/{str(file_rec['_id'])}/content"
        return {"url": proxy, "cached": False, "source": "r2_proxy"}
    if file_rec and file_rec.get("r2_url"):
        return {"url": file_rec["r2_url"], "cached": True, "source": "r2"}

    # Check in-memory Dropbox URL cache
    cached_url = _get_cached_url(company_id, file_path)
    if cached_url:
        return {"url": cached_url, "cached": True, "source": "dropbox_cache"}

    # Fall back to Dropbox temporary link
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/get_temporary_link",
        json={"path": file_path}
    )

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to get file URL")

    data = response.json()
    url = data.get("link", "")
    _set_cached_url(company_id, file_path, url)
    return {"url": url, "cached": False, "source": "dropbox"}


# ==================== DIRECT FILE UPLOAD (R2) ====================

def _sanitize_upload_filename(raw: str) -> str:
    """Normalize an uploaded filename for safe R2 storage.

    - URL-decodes any %XX escapes (React Native / some browsers send them encoded).
    - Strips directory path components (basename only).
    - Collapses multiple spaces.
    - Replaces characters that make R2 public URLs awkward (#, ?) with '_'.
    - Keeps spaces, parentheses, dashes — those are fine in keys, R2/browsers
      handle them with single URL-encoding in flight.
    """
    import urllib.parse as _urlparse
    from pathlib import PurePosixPath
    name = raw or "upload.pdf"
    # Strip any path, take basename
    name = PurePosixPath(name.replace("\\", "/")).name or "upload.pdf"
    # Decode %XX until stable (handle double-encoding seen in some clients)
    for _ in range(3):
        decoded = _urlparse.unquote(name)
        if decoded == name:
            break
        name = decoded
    # Replace characters that break R2 URLs
    for ch in ["#", "?", "\n", "\r", "\t"]:
        name = name.replace(ch, "_")
    name = " ".join(name.split())  # collapse whitespace
    if not name.lower().endswith(".pdf"):
        name = name + ".pdf"
    return name[:180]  # cap length


async def _log_upload_attempt(record: dict):
    """Fire-and-forget log of upload attempts to help diagnose failures."""
    try:
        record["received_at"] = datetime.now(timezone.utc)
        await db.upload_attempts_log.insert_one(record)
    except Exception:
        pass  # never let logging break the request


@api_router.post("/projects/{project_id}/upload-file")
async def upload_project_file(project_id: str, request: Request, file: UploadFile = File(...), current_user = Depends(get_current_user)):
    """Upload a file directly to R2 storage for a project (PDF only, max 100 MB)."""
    _log_base = {
        "project_id":      project_id,
        "raw_filename":    file.filename or "",
        "content_type":    file.content_type or "",
        "actor_email":     current_user.get("email", ""),
        "remote_addr":     request.client.host if request and request.client else "",
        "user_agent":      request.headers.get("user-agent", "") if request else "",
    }

    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        await _log_upload_attempt({**_log_base, "outcome": "404_project_not_found"})
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        await _log_upload_attempt({**_log_base, "outcome": "403_wrong_company"})
        raise HTTPException(status_code=403, detail="Access denied to this project")
    company_id = company_id or project.get("company_id")

    # Validate file type (accept .pdf regardless of case; decode if URL-encoded)
    filename = _sanitize_upload_filename(file.filename or "upload.pdf")
    if not filename.lower().endswith(".pdf"):
        await _log_upload_attempt({**_log_base, "outcome": "400_not_pdf", "sanitized_filename": filename})
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Read and validate size (100 MB max)
    try:
        file_bytes = await file.read()
    except Exception as e:
        logger.error(f"upload read failed for {filename}: {e}", exc_info=True)
        await _log_upload_attempt({**_log_base, "outcome": "400_read_failed", "error": str(e)[:500]})
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {e}")
    if not file_bytes:
        await _log_upload_attempt({**_log_base, "outcome": "400_empty_file", "sanitized_filename": filename})
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    max_size = 100 * 1024 * 1024
    if len(file_bytes) > max_size:
        await _log_upload_attempt({**_log_base, "outcome": "400_too_large", "size": len(file_bytes)})
        raise HTTPException(status_code=400, detail="File too large. Maximum 100 MB.")

    if not _r2_client:
        await _log_upload_attempt({**_log_base, "outcome": "503_r2_not_configured", "size": len(file_bytes)})
        raise HTTPException(status_code=503, detail="File storage (R2) is not configured")

    # De-dup: if a record with the same name already exists on this project,
    # suffix with a timestamp so we don't overwrite the original in R2.
    existing_same = await db.project_files.find_one({
        "project_id": project_id,
        "name": filename,
        "is_deleted": {"$ne": True},
    })
    if existing_same:
        stem, _, ext = filename.rpartition(".")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"{stem or filename}-{ts}.{ext or 'pdf'}"

    r2_key = f"{company_id}/{project_id}/{filename}"
    try:
        r2_url = await asyncio.to_thread(_upload_to_r2, file_bytes, r2_key, "application/pdf")
    except Exception as e:
        logger.error(f"Direct upload R2 error (key={r2_key}): {e}", exc_info=True)
        await _log_upload_attempt({**_log_base, "outcome": "500_r2_error", "r2_key": r2_key, "error": str(e)[:500]})
        raise HTTPException(status_code=500, detail=f"Storage error: {str(e)[:200]}")

    now = datetime.now(timezone.utc)
    file_record = {
        "project_id": project_id,
        "company_id": company_id,
        "name": filename,
        "dropbox_path": "",
        "dropbox_content_hash": "",
        "r2_key": r2_key,
        "r2_url": r2_url,
        "size": len(file_bytes),
        "modified": now.isoformat(),
        "source": "direct_upload",
        "cache_version": 1,
        "created_at": now,
        "updated_at": now,
        "uploaded_by": current_user.get("id"),
    }
    try:
        result = await db.project_files.insert_one(file_record)
    except Exception as e:
        logger.error(f"project_files insert failed: {e}", exc_info=True)
        await _log_upload_attempt({**_log_base, "outcome": "500_mongo_error", "error": str(e)[:500]})
        raise HTTPException(status_code=500, detail=f"Metadata write error: {str(e)[:200]}")
    file_record["_id"] = str(result.inserted_id)
    file_record.pop("created_at", None)
    file_record.pop("updated_at", None)

    # Sprint 3: spawn plan indexing for PDFs (no-op if QWEN_API_KEY unset)
    if filename.lower().endswith(".pdf") and QWEN_API_KEY:
        asyncio.create_task(_index_pdf_file(project_id, company_id, file_record))

    proxy_url = f"/api/projects/{project_id}/files/{file_record['_id']}/content"
    await _log_upload_attempt({
        **_log_base,
        "outcome": "200_ok",
        "sanitized_filename": filename,
        "r2_key": r2_key,
        "size": len(file_bytes),
        "file_id": file_record["_id"],
    })
    return {
        "id": file_record["_id"],
        "name": filename,
        "r2_url": proxy_url,
        "size": len(file_bytes),
        "source": "direct_upload",
    }


@api_router.get("/debug/bis-scraper-state")
async def debug_bis_scraper_state(current_user=Depends(get_current_user)):
    """Dump the state the BIS scraper has written to Mongo, so we can
    verify it's actually getting through DOB's Akamai gate without
    tailing Railway logs.

    Reports (owner/admin only):
      - Per-project initial-scan markers (source='bis')
      - Per-license insurance fetch cache entries + record counts
      - Companies whose gc_license_number/gc_insurance_records came
        from the scraper
      - Recent dob_logs written with source='bis_scraper'
      - Tracked projects the scraper should be hitting (for reference)
    """
    role = (current_user.get("role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    company_id = get_user_company_id(current_user)
    now = datetime.now(timezone.utc)

    # 1. Tracked projects the scraper should be scanning.
    proj_filter: Dict[str, Any] = {
        "track_dob_status": True,
        "nyc_bin":          {"$exists": True, "$ne": ""},
        "is_deleted":       {"$ne": True},
    }
    if company_id:
        proj_filter["company_id"] = company_id
    tracked = await db.projects.find(
        proj_filter,
        {"name": 1, "nyc_bin": 1, "company_id": 1},
    ).to_list(200)

    # 2. initial_scan_done:bis markers per project.
    bis_markers = await db.system_config.find(
        {"key": {"$regex": "^initial_scan_done:bis:"}}
    ).to_list(500)
    markers_by_pid: Dict[str, Any] = {}
    for m in bis_markers:
        pid = str(m.get("project_id") or m.get("key", "").split(":")[-1] or "")
        if pid:
            markers_by_pid[pid] = m.get("completed_at")

    # 3. Insurance fetch cache — per unique license.
    fetches = await db.system_config.find(
        {"key": {"$regex": "^insurance_fetch:"}}
    ).sort("last_fetched_at", -1).to_list(200)
    fetch_rows = []
    for f in fetches:
        last = f.get("last_fetched_at")
        if isinstance(last, datetime):
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours_ago = round((now - last).total_seconds() / 3600.0, 1)
        else:
            hours_ago = None
        fetch_rows.append({
            "license_number":      f.get("license_number"),
            "last_fetched_at":     str(last) if last else None,
            "hours_since_fetch":   hours_ago,
            "last_record_count":   f.get("last_record_count"),
        })

    # 4. Companies with scraper-sourced license or insurance.
    comp_filter: Dict[str, Any] = {
        "$or": [
            {"gc_license_source": "bis_scraper"},
            {"gc_insurance_records.source": "bis_scraper"},
        ],
    }
    if company_id:
        comp_filter["_id"] = to_query_id(company_id)
    companies = await db.companies.find(comp_filter).to_list(200)
    company_rows = []
    for c in companies:
        ins = c.get("gc_insurance_records") or []
        scraper_ins = [
            {
                "type":       i.get("insurance_type"),
                "expiration": i.get("expiration_date"),
                "is_current": i.get("is_current"),
                "carrier":    i.get("carrier_name"),
                "source":     i.get("source"),
            }
            for i in ins
        ]
        company_rows.append({
            "company_id":          str(c.get("_id")),
            "name":                c.get("name") or c.get("gc_business_name"),
            "gc_license_number":   c.get("gc_license_number"),
            "gc_license_source":   c.get("gc_license_source"),
            "gc_last_verified":    str(c.get("gc_last_verified") or ""),
            "insurance_records":   scraper_ins,
        })

    # 5. Recent dob_logs with source='bis_scraper' (cap 20).
    log_filter: Dict[str, Any] = {"source": "bis_scraper"}
    if company_id:
        log_filter["company_id"] = company_id
    recent_logs = await db.dob_logs.find(log_filter).sort("detected_at", -1).limit(20).to_list(20)
    log_rows = [{
        "detected_at":  str(r.get("detected_at")),
        "project_id":   r.get("project_id"),
        "record_type":  r.get("record_type"),
        "severity":     r.get("severity"),
        "raw_dob_id":   r.get("raw_dob_id"),
        "summary":      (r.get("ai_summary") or "")[:200],
    } for r in recent_logs]

    bis_log_total = await db.dob_logs.count_documents(log_filter)

    # 6. Per-project summary — join tracked list with markers + company license.
    project_rows = []
    for p in tracked:
        pid = str(p.get("_id"))
        cid = p.get("company_id") or ""
        comp = None
        try:
            comp = await db.companies.find_one(
                {"_id": to_query_id(cid)} if cid else {"_id": None},
                {"gc_license_number": 1, "gc_license_source": 1},
            )
        except Exception:
            comp = None
        project_rows.append({
            "project_id":           pid,
            "name":                 p.get("name"),
            "nyc_bin":              p.get("nyc_bin"),
            "initial_scan_done_at": str(markers_by_pid.get(pid) or ""),
            "company_id":           cid,
            "company_license":      (comp or {}).get("gc_license_number"),
            "license_source":       (comp or {}).get("gc_license_source"),
        })

    return {
        "now":                      now.isoformat(),
        "tracked_project_count":    len(tracked),
        "projects":                 project_rows,
        "insurance_fetch_cache":    fetch_rows,
        "companies_with_scraper_data": company_rows,
        "recent_bis_dob_logs":      log_rows,
        "total_bis_dob_logs":       bis_log_total,
        "interpretation": {
            "scraper_is_hitting_bis": (
                bool(recent_logs) or bool(markers_by_pid) or bool(fetches)
            ),
            "scraper_is_capturing_licenses": bool(company_rows),
            "scraper_is_fetching_insurance": any(
                (r.get("last_record_count") or 0) > 0 for r in fetch_rows
            ),
        },
    }


@api_router.get("/debug/upload-log")
async def debug_upload_log(current_user=Depends(get_current_user)):
    """Last 30 upload attempts with outcome — owner/admin only."""
    role = (current_user.get("role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    rows = await db.upload_attempts_log.find().sort("received_at", -1).limit(30).to_list(30)
    return {
        "count": len(rows),
        "recent": [
            {
                "received_at":   str(r.get("received_at")),
                "outcome":       r.get("outcome"),
                "raw_filename":  r.get("raw_filename"),
                "sanitized":     r.get("sanitized_filename"),
                "size":          r.get("size"),
                "actor":         r.get("actor_email"),
                "remote_addr":   r.get("remote_addr"),
                "user_agent":    (r.get("user_agent") or "")[:200],
                "error":         r.get("error"),
                "content_type":  r.get("content_type"),
                "r2_key":        r.get("r2_key"),
            }
            for r in rows
        ],
    }


@api_router.get("/projects/{project_id}/files/{file_id}/content")
async def stream_project_file(project_id: str, file_id: str, current_user = Depends(get_current_user)):
    """Stream a project file from R2 through the backend.

    Auth: bearer header or `?token=` query param (handled by get_current_user —
    query-token works for <iframe src> / <object> viewers that can't set headers).
    """
    try:
        rec_oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file id")
    rec = await db.project_files.find_one({"_id": rec_oid, "project_id": project_id})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")

    user_company_id = str(current_user.get("company_id") or "")
    if user_company_id and rec.get("company_id") and rec["company_id"] != user_company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    r2_key = rec.get("r2_key", "")
    if not r2_key or not _r2_client or not R2_BUCKET_NAME:
        raise HTTPException(status_code=404, detail="File not stored in R2")

    try:
        obj = await asyncio.to_thread(_r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=r2_key)
    except Exception as e:
        logger.error(f"R2 get_object failed key={r2_key}: {e}")
        raise HTTPException(status_code=502, detail="Storage fetch failed")

    body = obj["Body"]
    content_type = obj.get("ContentType") or mimetypes.guess_type(rec.get("name", "") or r2_key)[0] or "application/octet-stream"
    filename = rec.get("name", "file")

    def _iter():
        try:
            for chunk in iter(lambda: body.read(65536), b""):
                yield chunk
        finally:
            try: body.close()
            except Exception: pass

    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    if obj.get("ContentLength"):
        headers["Content-Length"] = str(obj["ContentLength"])
    return StreamingResponse(_iter(), media_type=content_type, headers=headers)


@api_router.delete("/projects/{project_id}/files/{file_id}")
async def delete_project_file(project_id: str, file_id: str, current_user = Depends(get_current_user)):
    """Hard-delete a project file: removes from R2 and Mongo. Admin/owner only.

    For Dropbox-synced files we only remove the Mongo row — Dropbox is the
    source of truth there and we don't want to reach into the user's Dropbox.
    """
    # Permission check: only company owner / admin may hard-delete files.
    role = str(current_user.get("role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only company owners or admins can delete files")

    try:
        rec_oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file id")

    rec = await db.project_files.find_one({"_id": rec_oid, "project_id": project_id})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")

    user_company_id = str(current_user.get("company_id") or "")
    if user_company_id and rec.get("company_id") and rec["company_id"] != user_company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    r2_key = rec.get("r2_key", "")
    r2_deleted = False
    if r2_key and _r2_client and R2_BUCKET_NAME:
        try:
            await asyncio.to_thread(
                _r2_client.delete_object,
                Bucket=R2_BUCKET_NAME,
                Key=r2_key,
            )
            r2_deleted = True
        except Exception as e:
            logger.error(f"R2 delete_object failed key={r2_key}: {e}")
            # Continue: still remove DB row so the file stops appearing.

    delete_result = await db.project_files.delete_one({"_id": rec_oid})

    logger.info(
        f"File hard-deleted by {current_user.get('email')}: "
        f"name={rec.get('name')} r2_key={r2_key or '-'} r2_deleted={r2_deleted} "
        f"mongo_deleted={delete_result.deleted_count}"
    )
    return {
        "deleted": True,
        "file_id": file_id,
        "name": rec.get("name", ""),
        "r2_deleted": r2_deleted,
        "mongo_deleted": delete_result.deleted_count == 1,
    }


# ==================== DROPBOX WEBHOOK ====================

@api_router.get("/dropbox/webhook")
async def dropbox_webhook_challenge(challenge: str = ""):
    """Dropbox webhook verification -- return challenge as plain text."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(challenge)


@api_router.post("/dropbox/webhook")
async def dropbox_webhook_notify(request: Request):
    """Dropbox webhook notification -- trigger background sync for affected projects."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    accounts = []
    for entry in body.get("list_folder", {}).get("accounts", []):
        accounts.append(entry)
    if not body.get("list_folder"):
        # Delta/legacy format
        delta = body.get("delta", {})
        if delta.get("users"):
            accounts = delta["users"]

    if not accounts:
        return {"status": "ok"}

    # Find companies whose Dropbox account_id matches
    for acct_id in accounts:
        connections = await db.dropbox_connections.find({
            "account_id": acct_id, "is_deleted": {"$ne": True}
        }).to_list(100)

        for conn in connections:
            cid = conn.get("company_id")
            if not cid:
                continue
            # Find projects with linked Dropbox folders for this company
            projects = await db.projects.find({
                "company_id": cid,
                "dropbox_folder_path": {"$exists": True, "$ne": ""},
                "is_deleted": {"$ne": True},
            }).to_list(500)

            for proj in projects:
                pid = str(proj["_id"])
                folder = proj.get("dropbox_folder_path", "")
                if folder:
                    asyncio.create_task(_sync_project_to_r2(pid, cid, folder))
                    logger.info(f"Dropbox webhook: triggered sync for project {pid}")

    return {"status": "ok"}


@api_router.post("/dropbox/register-webhook")
async def register_dropbox_webhook(data: dict = {}, current_user = Depends(get_admin_user)):
    """Register Dropbox webhook URL (admin one-time setup)."""
    webhook_url = data.get("url", "")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="url required in body")

    company_id = get_user_company_id(current_user)
    token = await get_valid_dropbox_token(company_id)

    async with ServerHttpClient(timeout=15.0) as c:
        resp = await c.post(
            "https://api.dropboxapi.com/2/files/list_folder/longpoll",
            headers={"Authorization": f"Bearer {token}"},
            json={"cursor": ""},
        )

    # Dropbox doesn't have a direct "register webhook" API — webhooks are
    # configured in the Dropbox App Console. This endpoint verifies the token works.
    return {
        "message": "Dropbox connection verified. Register the webhook URL in your Dropbox App Console.",
        "webhook_url": webhook_url,
        "token_valid": True,
    }


# ==================== DAILY LOG PDF EXPORT ====================

@api_router.get("/daily-logs/{log_id}/pdf")
async def get_daily_log_pdf(log_id: str, current_user = Depends(get_current_user)):
    """Generate PDF for a daily log"""
    from fastapi.responses import Response
    import io
    
    log = await db.daily_logs.find_one({"_id": to_query_id(log_id), "is_deleted": {"$ne": True}})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    # Get project info
    project = None
    if log.get("project_id"):
        project = await db.projects.find_one({"_id": to_query_id(log["project_id"])})
    
    project_name = project.get("name", "Unknown") if project else "Unknown"
    project_address = project.get("address") or project.get("location") or project.get("name", "") if project else ""
    
    # Build simple HTML-based PDF
    log_date = log.get("date", "N/A")
    weather = log.get("weather", "N/A")
    notes = log.get("notes", "")
    worker_count = log.get("worker_count", 0)
    created_by = log.get("created_by_name", "Unknown")
    
    # Subcontractor cards
    sub_cards = log.get("subcontractor_cards", []) or []
    sub_html = ""
    for card in sub_cards:
        sub_html += f"""
        <tr>
            <td>{card.get('company_name', 'N/A')}</td>
            <td>{card.get('trade', 'N/A')}</td>
            <td>{card.get('worker_count', 0)}</td>
            <td>{card.get('hours', 'N/A')}</td>
            <td>{card.get('description', '')}</td>
        </tr>"""
    
    # Safety checklist
    safety = log.get("safety_checklist", {}) or {}
    safety_html = ""
    for item_key, item_val in safety.items():
        status = item_val.get("status", "N/A") if isinstance(item_val, dict) else str(item_val)
        note = item_val.get("note", "") if isinstance(item_val, dict) else ""
        safety_html += f"<tr><td>{item_key}</td><td>{status}</td><td>{note}</td></tr>"
    
    corrective = log.get("corrective_actions", "N/A") if not log.get("corrective_actions_na") else "N/A"
    incident = log.get("incident_log", "N/A") if not log.get("incident_log_na") else "N/A"
    
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
            h1 {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 10px; }}
            h2 {{ color: #2c3e50; margin-top: 25px; }}
            .header-info {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
            .info-box {{ background: #f8f9fa; padding: 12px; border-radius: 6px; margin: 8px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background: #1a5276; color: white; }}
            tr:nth-child(even) {{ background: #f2f2f2; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #ccc; font-size: 12px; color: #888; }}
            .signature-box {{ border: 1px solid #ddd; padding: 20px; margin: 10px 0; min-height: 60px; }}
        </style>
    </head>
    <body>
        <h1>Daily Construction Log</h1>
        <div class="info-box">
            <strong>Project:</strong> {project_name}<br>
            <strong>Address:</strong> {project_address}<br>
            <strong>Date:</strong> {log_date}<br>
            <strong>Weather:</strong> {weather}<br>
            <strong>Workers on Site:</strong> {worker_count}<br>
            <strong>Prepared By:</strong> {created_by}
        </div>
        
        <h2>Notes</h2>
        <p>{notes or 'No notes recorded.'}</p>
        
        <h2>Subcontractor Activity</h2>
        <table>
            <tr><th>Company</th><th>Trade</th><th>Workers</th><th>Hours</th><th>Description</th></tr>
            {sub_html if sub_html else '<tr><td colspan="5">No subcontractor activity recorded.</td></tr>'}
        </table>
        
        <h2>Safety Checklist</h2>
        <table>
            <tr><th>Item</th><th>Status</th><th>Notes</th></tr>
            {safety_html if safety_html else '<tr><td colspan="3">No safety items recorded.</td></tr>'}
        </table>
        
        <h2>Corrective Actions</h2>
        <p>{corrective}</p>
        
        <h2>Incident Log</h2>
        <p>{incident}</p>
        
        <div class="footer">
            Generated by Levelog Construction Management • {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}
        </div>
    </body>
    </html>
    """
    
    # Return HTML as downloadable file (can be printed to PDF by browser)
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="daily-log-{log_date}.html"'
        }
    )
    
# ==================== PHOTO UPLOADS ====================

@api_router.post("/daily-logs/{log_id}/photos")
async def upload_daily_log_photo(
    log_id: str,
    current_user = Depends(get_current_user),
    file: UploadFile = File(...),
    subcontractor_index: int = Form(default=-1),
    caption: str = Form(default=""),
):
    """Upload a photo to a daily log, optionally linked to a subcontractor card"""
    log = await db.daily_logs.find_one({"_id": to_query_id(log_id), "is_deleted": {"$ne": True}})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    # CRITICAL FIX: CP role CAN upload photos. Only site_device (read-only) cannot.
    role = current_user.get("role")
    if role == "site_device":
        raise HTTPException(status_code=403, detail="Site devices (read-only) cannot upload photos")
    
    if role not in ["admin", "owner"]:
        company_id = get_user_company_id(current_user)
        log_company = log.get("company_id")
        user_projects = current_user.get("assigned_projects", [])
        if company_id != log_company and log.get("project_id") not in user_projects:
            raise HTTPException(status_code=403, detail="Access denied")
    
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    
    b64_data = base64.b64encode(content).decode('utf-8')
    now = datetime.now(timezone.utc)
    
    photo_doc = {
        "daily_log_id": log_id,
        "project_id": log.get("project_id"),
        "company_id": log.get("company_id"),
        "subcontractor_index": subcontractor_index,
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "data": b64_data,
        "caption": caption,
        "uploaded_by": current_user.get("id"),
        "uploaded_by_name": current_user.get("name") or current_user.get("device_name", "Unknown"),
        "created_at": now,
        "is_deleted": False,
    }
    
    result = await db.daily_log_photos.insert_one(photo_doc)
    
    return {
        "id": str(result.inserted_id),
        "filename": file.filename,
        "size": len(content),
        "subcontractor_index": subcontractor_index,
        "caption": caption,
        "uploaded_by_name": photo_doc["uploaded_by_name"],
        "created_at": now.isoformat(),
    }

@api_router.get("/daily-logs/{log_id}/photos")
async def get_daily_log_photos(log_id: str, current_user = Depends(get_current_user)):
    """Get all photos for a daily log (metadata only, no base64)"""
    photos = await db.daily_log_photos.find(
        {"daily_log_id": log_id, "is_deleted": {"$ne": True}},
        {"data": 0}
    ).to_list(200)
    return serialize_list(photos)

@api_router.get("/daily-logs/{log_id}/photos/{photo_id}")
async def get_daily_log_photo(log_id: str, photo_id: str, current_user = Depends(get_current_user)):
    """Get a single photo with base64 data"""
    photo = await db.daily_log_photos.find_one({
        "_id": to_query_id(photo_id),
        "daily_log_id": log_id,
        "is_deleted": {"$ne": True}
    })
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    return serialize_id(photo)

@api_router.get("/daily-logs/{log_id}/photos/{photo_id}/image")
async def get_daily_log_photo_image(log_id: str, photo_id: str, current_user = Depends(get_current_user)):
    """Serve photo as raw image binary"""
    from fastapi.responses import Response
    photo = await db.daily_log_photos.find_one({
        "_id": to_query_id(photo_id),
        "daily_log_id": log_id,
        "is_deleted": {"$ne": True}
    })
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    image_data = base64.b64decode(photo["data"])
    return Response(content=image_data, media_type=photo.get("content_type", "image/jpeg"))

@api_router.get("/reports/logbook-photo/{logbook_id}/{activity_index}/{photo_index}")
async def get_logbook_activity_photo(logbook_id: str, activity_index: int, photo_index: int):
    """Public endpoint - serve activity photo from logbook as raw image for email reports."""
    from fastapi.responses import Response
    logbook = await db.logbooks.find_one({"_id": to_query_id(logbook_id), "is_deleted": {"$ne": True}})
    if not logbook:
        raise HTTPException(status_code=404, detail="Logbook not found")
    data = logbook.get("data", {})
    activities = data.get("activities", [])
    if activity_index < 0 or activity_index >= len(activities):
        raise HTTPException(status_code=404, detail="Activity not found")
    photos = activities[activity_index].get("photos") or []
    if photo_index < 0 or photo_index >= len(photos):
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = photos[photo_index]
    b64 = photo.get("base64", "")
    if not b64:
        raise HTTPException(status_code=404, detail="Photo data not available")
    image_data = base64.b64decode(b64)
    return Response(content=image_data, media_type="image/jpeg")

@api_router.delete("/daily-logs/{log_id}/photos/{photo_id}")
async def delete_daily_log_photo(log_id: str, photo_id: str, current_user = Depends(get_current_user)):
    """Delete a photo (soft delete)"""
    result = await db.daily_log_photos.update_one(
        {"_id": to_query_id(photo_id), "daily_log_id": log_id},
        {"$set": {"is_deleted": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"message": "Photo deleted"}
    
# ==================== CP PROFILE ENDPOINTS ====================

@api_router.get("/cp/profile")
async def get_cp_profile(current_user = Depends(get_current_user)):
    """Return the CP profile (name + saved signature) for the logged-in user.

    Defensive by design: returns a safe skeleton on any error rather than
    a 500 / 404. The frontend useCpProfile hook silently swallows errors
    so a failure here would mask the problem AND leave the UI half-broken.
    Returning the skeleton keeps the pad empty, signup-ready, and lets
    the user continue.
    """
    try:
        user_id = current_user.get("id")
        user = await db.users.find_one({"_id": to_query_id(user_id)})
        if not user:
            return {
                "cp_name": None,
                "cp_title": "Competent Person",
                "cp_signature": None,
                "has_signature": False,
            }
        return {
            "cp_name": user.get("cp_name") or user.get("name"),
            "cp_title": user.get("cp_title", "Competent Person"),
            "cp_signature": user.get("cp_signature"),
            "has_signature": bool(user.get("cp_signature")),
        }
    except Exception as e:
        logger.error(f"get_cp_profile error: {e}")
        return {
            "cp_name": None,
            "cp_title": "Competent Person",
            "cp_signature": None,
            "has_signature": False,
        }

@api_router.put("/cp/profile")
async def update_cp_profile(data: CPProfileUpdate, current_user = Depends(get_current_user)):
    """Save CP name and signature - called on first login"""
    user_id = current_user.get("id")
    now = datetime.now(timezone.utc)
    update = {"updated_at": now}
    if data.cp_name is not None:
        update["cp_name"] = data.cp_name
    if data.cp_signature is not None:
        update["cp_signature"] = data.cp_signature
    if data.cp_title is not None:
        update["cp_title"] = data.cp_title
    await db.users.update_one({"_id": to_query_id(user_id)}, {"$set": update})
    return {"message": "CP profile updated"}

# ==================== LOGBOOK ENDPOINTS ====================

@api_router.get("/logbooks/project/{project_id}")
async def get_project_logbooks(
    project_id: str,
    log_type: Optional[str] = None,
    date: Optional[str] = None,
    current_user = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """Get all logbooks for a project, optionally filtered by type and date"""
    company_id = get_user_company_id(current_user)
    query = {
        "project_id": project_id,
        "is_deleted": {"$ne": True}
    }
    if company_id:
        query["company_id"] = company_id
    if log_type:
        query["log_type"] = log_type
    if date:
        query["date"] = date
    result = await paginated_query(db.logbooks, query, sort_field="date", limit=limit, skip=skip)
    return result

@api_router.get("/logbooks/{logbook_id}")
async def get_logbook(logbook_id: str, current_user = Depends(get_current_user)):
    """Get a single logbook entry"""
    logbook = await db.logbooks.find_one({"_id": to_query_id(logbook_id)})
    if not logbook:
        raise HTTPException(status_code=404, detail="Logbook not found")
    return serialize_id(logbook)

@api_router.post("/logbooks")
async def create_logbook(data: LogbookCreate, current_user = Depends(get_current_user)):
    """Create a new logbook entry"""
    company_id = get_user_company_id(current_user)
    now = datetime.now(timezone.utc)

    # Verify project exists
    project = await db.projects.find_one({"_id": to_query_id(data.project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check for existing entry same type+date (upsert logic)
    existing = await db.logbooks.find_one({
        "project_id": data.project_id,
        "log_type": data.log_type,
        "date": data.date,
        "is_deleted": {"$ne": True}
    })
    if existing:
        # Update existing
        await db.logbooks.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "data": data.data,
                "cp_signature": data.cp_signature,
                "cp_name": data.cp_name,
                "status": data.status,
                "updated_at": now,
            }}
        )
        updated = await db.logbooks.find_one({"_id": existing["_id"]})
        return serialize_id(updated)

    doc = {
        "project_id": data.project_id,
        "project_name": project.get("name", ""),
        "company_id": company_id,
        "log_type": data.log_type,
        "date": data.date,
        "data": data.data,
        "cp_signature": data.cp_signature,
        "cp_name": data.cp_name,
        "status": data.status,
        "created_by": current_user.get("id"),
        "created_by_name": current_user.get("name"),
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    result = await db.logbooks.insert_one(doc)
    created = await db.logbooks.find_one({"_id": result.inserted_id})

    await audit_log("logbook_create", str(current_user.get("_id", current_user.get("id", ""))), "logbook", str(result.inserted_id), {
        "log_type": data.log_type, "project_id": data.project_id, "date": data.date,
    })

    return serialize_id(created)

@api_router.put("/logbooks/{logbook_id}")
async def update_logbook(logbook_id: str, data: LogbookUpdate, current_user = Depends(get_current_user)):
    """Update an existing logbook entry"""
    now = datetime.now(timezone.utc)
    update = {"updated_at": now}
    if data.data is not None:
        update["data"] = data.data
    if data.cp_signature is not None:
        update["cp_signature"] = data.cp_signature
    if data.cp_name is not None:
        update["cp_name"] = data.cp_name
    if data.status is not None:
        update["status"] = data.status
    result = await db.logbooks.update_one({"_id": to_query_id(logbook_id)}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Logbook not found")
    updated = await db.logbooks.find_one({"_id": to_query_id(logbook_id)})
    return serialize_id(updated)

@api_router.delete("/logbooks/{logbook_id}")
async def delete_logbook(logbook_id: str, current_user = Depends(get_current_user)):
    """Soft delete a logbook entry — only by admins or the user who created it"""
    logbook = await db.logbooks.find_one({"_id": to_query_id(logbook_id), "is_deleted": {"$ne": True}})
    if not logbook:
        raise HTTPException(status_code=404, detail="Logbook not found")

    # Authorization: admin/owner can delete any, others only their own
    user_role = current_user.get("role", "")
    user_id = str(current_user.get("_id", ""))
    if user_role not in ("admin", "owner") and logbook.get("created_by") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this logbook")

    await db.logbooks.update_one(
        {"_id": to_query_id(logbook_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )

    await audit_log("logbook_delete", user_id, "logbook", logbook_id, {
        "log_type": logbook.get("log_type"), "project_id": logbook.get("project_id"),
    })

    return {"message": "Logbook deleted"}

@api_router.get("/logbooks/project/{project_id}/notifications")
async def get_logbook_notifications(project_id: str, current_user = Depends(get_current_user)):
    """
    Returns alerts for CP:
    - Workers who haven't had toolbox talk this week
    - New workers since last week without orientation
    """
    now = datetime.now(timezone.utc)
    # Start of current week (Monday)
    days_since_monday = now.weekday()
    week_start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_str = week_start.strftime("%Y-%m-%d")

    # Get all workers checked into this project this week
    checkins_this_week = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": week_start},
        "is_deleted": {"$ne": True}
    }).to_list(2000)

    worker_ids_this_week = list(set(c.get("worker_id") for c in checkins_this_week if c.get("worker_id")))

    # Get toolbox talk entries this week for this project
    toolbox_this_week = await db.logbooks.find({
        "project_id": project_id,
        "log_type": "toolbox_talk",
        "date": {"$gte": week_start_str},
        "is_deleted": {"$ne": True}
    }).to_list(100)

    # Collect worker IDs already covered in toolbox this week
    covered_worker_ids = set()
    for tb in toolbox_this_week:
        attendees = tb.get("data", {}).get("attendees", [])
        for a in attendees:
            if a.get("worker_id"):
                covered_worker_ids.add(a["worker_id"])

    # Missing workers = on site this week but not in toolbox
    missing_toolbox = []
    for wid in worker_ids_this_week:
        if wid not in covered_worker_ids:
            worker = await db.workers.find_one({"_id": to_query_id(wid)})
            if worker:
                missing_toolbox.append({
                    "worker_id": wid,
                    "worker_name": worker.get("name"),
                    "company": worker.get("company"),
                })

    # Count orientation docs that haven't been CP-signed yet
    unsigned_orientations = await db.logbooks.count_documents({
        "project_id": project_id,
        "log_type": "subcontractor_orientation",
        "status": {"$ne": "submitted"},
        "is_deleted": {"$ne": True},
    })

    return {
        "missing_toolbox_talk": missing_toolbox,
        "unsigned_orientations": unsigned_orientations,
        "week_start": week_start_str,
    }

@api_router.get("/logbooks/project/{project_id}/scaffold-info")
async def get_scaffold_info(project_id: str, current_user = Depends(get_current_user)):
    """Get saved scaffold info for a project (remembered after first entry)"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "scaffold_erector": project.get("scaffold_erector", ""),
        "permit_number": project.get("permit_number", ""),
        "installation_date": project.get("installation_date", ""),
        "expiration_date": project.get("expiration_date", ""),
        "shed_type": project.get("shed_type", ""),
        "scaffold_height": project.get("scaffold_height", ""),
        "num_platforms": project.get("num_platforms", ""),
        "drawings_on_site": project.get("drawings_on_site", True),
        "renters_name": project.get("renters_name", ""),
        "phone": project.get("scaffold_phone", ""),
        "scaffold_erected": project.get("scaffold_erected", False),
    }

@api_router.put("/logbooks/project/{project_id}/scaffold-info")
async def update_scaffold_info(project_id: str, data: Dict[str, Any], current_user = Depends(get_current_user)):
    """Save scaffold info to project so it's remembered"""
    update = {
        "scaffold_erector": data.get("scaffold_erector"),
        "permit_number": data.get("permit_number"),
        "installation_date": data.get("installation_date"),
        "expiration_date": data.get("expiration_date"),
        "shed_type": data.get("shed_type"),
        "scaffold_height": data.get("scaffold_height"),
        "num_platforms": data.get("num_platforms"),
        "drawings_on_site": data.get("drawings_on_site"),
        "renters_name": data.get("renters_name"),
        "scaffold_phone": data.get("phone"),
        "scaffold_erected": data.get("scaffold_erected"),
        "updated_at": datetime.now(timezone.utc),
    }
    # Remove None values
    update = {k: v for k, v in update.items() if v is not None}
    await db.projects.update_one({"_id": to_query_id(project_id)}, {"$set": update})
    return {"message": "Scaffold info saved"}
# ==================== LOGBOOK TYPE REGISTRY ENDPOINT ====================

@api_router.get("/logbook-types")
async def get_logbook_types(current_user = Depends(get_current_user)):
    """Return the full logbook type registry for UI rendering."""
    return LOGBOOK_TYPE_REGISTRY

# ==================== SAFETY STAFF ENDPOINTS ====================

@api_router.get("/projects/{project_id}/safety-staff")
async def get_project_safety_staff(project_id: str, current_user = Depends(get_current_user)):
    """Get safety staff registrations for a project (SSC/SSM)."""
    staff = await db.safety_staff_registrations.find({
        "project_id": project_id, "is_deleted": {"$ne": True}
    }).to_list(20)
    return serialize_list(staff)

@api_router.post("/projects/{project_id}/safety-staff")
async def create_safety_staff(project_id: str, data: SafetyStaffCreate, admin = Depends(get_admin_user)):
    """Register a Site Safety Coordinator (SSC) or Site Safety Manager (SSM) for a project."""
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if data.role not in ("ssc", "ssm"):
        raise HTTPException(status_code=422, detail="Role must be 'ssc' or 'ssm'")

    now = datetime.now(timezone.utc)
    staff_dict = data.model_dump()
    staff_dict["company_id"] = project.get("company_id")
    staff_dict["created_at"] = now
    staff_dict["updated_at"] = now
    staff_dict["is_deleted"] = False

    result = await db.safety_staff_registrations.insert_one(staff_dict)

    await audit_log("safety_staff_create", str(admin.get("_id", admin.get("id", ""))), "safety_staff", str(result.inserted_id), {
        "role": data.role, "name": data.name, "license_number": data.license_number, "project_id": project_id,
    })

    staff_dict["id"] = str(result.inserted_id)
    return staff_dict

@api_router.put("/safety-staff/{staff_id}")
async def update_safety_staff(staff_id: str, data: dict, admin = Depends(get_admin_user)):
    """Update a safety staff registration."""
    ALLOWED_FIELDS = {"name", "license_number", "license_expiration", "phone", "email", "role"}
    update_data = {k: v for k, v in data.items() if v is not None and k in ALLOWED_FIELDS}
    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db.safety_staff_registrations.update_one(
        {"_id": to_query_id(staff_id)},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Safety staff not found")

    updated = await db.safety_staff_registrations.find_one({"_id": to_query_id(staff_id)})
    return serialize_id(updated)

@api_router.delete("/safety-staff/{staff_id}")
async def delete_safety_staff(staff_id: str, admin = Depends(get_admin_user)):
    """Soft delete a safety staff registration."""
    result = await db.safety_staff_registrations.update_one(
        {"_id": to_query_id(staff_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Safety staff not found")

    await audit_log("safety_staff_delete", str(admin.get("_id", admin.get("id", ""))), "safety_staff", staff_id)
    return {"message": "Safety staff removed"}

# ==================== GOOGLE PLACES AUTOCOMPLETE ====================

@api_router.get("/places/autocomplete")
async def places_autocomplete(input: str, types: str = "address", current_user = Depends(get_current_user)):
    """Proxy Google Places Autocomplete to avoid exposing API key on client."""
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=501, detail="Google Places API key not configured")
    
    if not input or len(input) < 2:
        return {"predictions": []}
    
    try:
        async with ServerHttpClient() as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/place/autocomplete/json",
                params={
                    "input": input,
                    "types": types,
                    "components": "country:us",
                    "key": GOOGLE_PLACES_API_KEY,
                },
                timeout=5.0,
            )
            data = response.json()
            if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
                logger.warning(f"Places API error: {data.get('status')} - {data.get('error_message', '')}")
            
            return {"predictions": data.get("predictions", [])}
    except httpx.RequestError as e:
        logger.error(f"Places API request failed: {e}")
        raise HTTPException(status_code=502, detail="Could not reach Google Places API")
		
@api_router.get("/weather")
async def get_weather(lat: Optional[float] = None, lng: Optional[float] = None, address: Optional[str] = None, current_user = Depends(get_current_user)):
    """
    Get current weather using OpenWeather API.
    Pass lat/lng directly, or address for geocoding.
    Falls back to NYC (40.7128, -74.0060) if no location provided.
    """
    api_key = os.environ.get('OPENWEATHER_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="Weather API key not configured")

    latitude = lat or 40.7128
    longitude = lng or -74.0060

    try:
        async with ServerHttpClient(timeout=10.0) as client:
            # If address provided but no lat/lng, geocode via OpenWeather
            if address and not lat:
                geo_url = (
                    f"https://api.openweathermap.org/geo/1.0/direct"
                    f"?q={address}&limit=1&appid={api_key}"
                )
                geo_res = await client.get(geo_url)
                if geo_res.status_code == 200:
                    geo_data = geo_res.json()
                    if geo_data and len(geo_data) > 0:
                        latitude = geo_data[0].get("lat", latitude)
                        longitude = geo_data[0].get("lon", longitude)

            # Fetch current weather from OpenWeather
            weather_url = (
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?lat={latitude}&lon={longitude}"
                f"&units=imperial&appid={api_key}"
            )
            res = await client.get(weather_url)
            if res.status_code != 200:
                logger.error(f"OpenWeather API error: {res.status_code} {res.text}")
                raise HTTPException(status_code=502, detail="Weather API unavailable")

            data = res.json()
            main = data.get("main", {})
            wind = data.get("wind", {})
            weather_list = data.get("weather", [{}])
            weather_main = weather_list[0].get("main", "") if weather_list else ""
            weather_desc = weather_list[0].get("description", "") if weather_list else ""

            # Map OpenWeather main condition to our app's weather options
            condition_map = {
                "Clear": "Sunny",
                "Clouds": "Cloudy",
                "Rain": "Rainy",
                "Drizzle": "Rainy",
                "Thunderstorm": "Stormy",
                "Snow": "Snow",
                "Mist": "Fog",
                "Fog": "Fog",
                "Haze": "Fog",
                "Smoke": "Fog",
                "Dust": "Windy",
                "Sand": "Windy",
                "Squall": "Windy",
                "Tornado": "Stormy",
            }
            condition = condition_map.get(weather_main, "Cloudy")

            # Check if it's very windy (> 20 mph) regardless of condition
            wind_speed = wind.get("speed", 0)
            if wind_speed > 20 and condition not in ("Stormy", "Snow", "Rainy"):
                condition = "Windy"

            return {
                "temperature": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "wind_speed": wind_speed,
                "condition": condition,
                "description": weather_desc,
            }
    except httpx.RequestError as e:
        logger.error(f"Weather fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Could not fetch weather data")

@api_router.get("/logbooks/project/{project_id}/checkins-today")
async def get_project_checkins_today(project_id: str, date: Optional[str] = None, current_user = Depends(get_current_user)):
    """Get all workers checked in to a project on a given date (for
    auto-populating log books).

    Merges two sources so the rollout from the legacy `checkins`
    collection to the new gate-based `sign_ins` + `worker_enrollments`
    can happen without breaking existing logbooks:

      1. NEW: sign_ins + worker_enrollments + daily_signatures for the
         given calendar date. Workers who signed at the gate today
         appear here with their daily signature auto-filled — no
         physical sign-on-admin's-tablet needed.
      2. LEGACY: the pre-existing `checkins` collection for workers
         who haven't migrated. Their signature comes from the per-
         worker `workers.signature` field as before.

    Dedup key: lower(name)+lower(company). New-system rows win on
    collision because their signature is the day's attestation, not
    a static profile image.
    """
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    now_eastern = datetime.now(eastern)
    target_date = date or now_eastern.strftime("%Y-%m-%d")

    # Parse date using Eastern Time boundaries for NYC compliance
    try:
        day_eastern = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=eastern)
        day_start = day_eastern.astimezone(timezone.utc)
        day_end = (day_eastern + timedelta(hours=24)).astimezone(timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    result: List[Dict[str, Any]] = []
    seen_name_keys: set = set()

    # ── PASS 1: New-system gate sign_ins ────────────────────────────────
    try:
        import card_audit as _ca
        sign_ins = await db.sign_ins.find({
            "project_id": project_id,
            "timestamp": {"$gte": day_start, "$lt": day_end},
        }).to_list(1000)

        # Unique worker_enrollment_ids from today's sign_ins
        enrollment_ids = []
        seen_eids: set = set()
        first_checkin_at: Dict[str, datetime] = {}
        for si in sign_ins:
            eid = si.get("worker_enrollment_id")
            if not eid:
                continue
            ts = si.get("timestamp")
            if eid not in seen_eids:
                seen_eids.add(eid)
                enrollment_ids.append(eid)
            if isinstance(ts, datetime):
                cur = first_checkin_at.get(eid)
                if cur is None or ts < cur:
                    first_checkin_at[eid] = ts

        # Pull enrollments and today's daily signatures in bulk
        enrollment_map: Dict[str, Dict[str, Any]] = {}
        if enrollment_ids:
            enrollment_object_ids = []
            for eid in enrollment_ids:
                try:
                    enrollment_object_ids.append(ObjectId(eid))
                except Exception:
                    pass
            async for e in db.worker_enrollments.find({"_id": {"$in": enrollment_object_ids}}):
                enrollment_map[str(e["_id"])] = e

        sig_map: Dict[str, str] = {}
        async for sig in db.daily_signatures.find({
            "project_id": project_id,
            "calendar_date": target_date,
            "worker_enrollment_id": {"$in": enrollment_ids},
        }):
            key = sig.get("signature_r2_key")
            if key:
                sig_map[sig["worker_enrollment_id"]] = key

        for eid in enrollment_ids:
            e = enrollment_map.get(eid)
            if not e:
                continue
            name = (e.get("worker_name") or "").strip()
            company = (e.get("sub_name") or "").strip()
            name_key = (name.lower(), company.lower())
            seen_name_keys.add(name_key)
            first_ts = first_checkin_at.get(eid)
            # Use the first sign_in of the day as the stable reference —
            # the frontend builds /api/signatures/{signin_id} from this.
            # No presigned URL is returned; access goes through the
            # authenticated proxy so the image is fetchable for the full
            # session, not just an hour.
            first_signin_id = None
            for si in sign_ins:
                if si.get("worker_enrollment_id") == eid:
                    first_signin_id = str(si["_id"])
                    break
            result.append({
                "worker_id": eid,   # enrollment id serves the same role
                "worker_name": name or "Unknown",
                "company": company,
                "trade": e.get("trade") or "",
                "check_in_time": first_ts.isoformat() if isinstance(first_ts, datetime) else "",
                "osha_number": e.get("card_id") or "",   # SST card id doubles as the worker's ID number
                "certifications": [],
                "worker_signature": None,               # new system: frontend uses signin_id
                "signin_id": first_signin_id,           # → /api/signatures/{signin_id}
                "source": "gate_checkin",
            })
    except Exception as _e:
        logger.warning(f"checkins-today new-system merge failed: {_e!r}")

    # ── PASS 2: Legacy checkins for workers not on the new system ──────
    try:
        legacy = await db.checkins.find({
            "project_id": project_id,
            "check_in_time": {"$gte": day_start, "$lt": day_end},
            "is_deleted": {"$ne": True},
        }).to_list(500)
    except Exception:
        legacy = []

    seen_legacy_wids: set = set()
    for c in legacy:
        wid = c.get("worker_id")
        if wid in seen_legacy_wids:
            continue
        seen_legacy_wids.add(wid)
        worker = await db.workers.find_one({"_id": to_query_id(wid)}) if wid else None
        name = (c.get("worker_name") or (worker.get("name") if worker else "") or "").strip()
        company = (c.get("worker_company") or (worker.get("company") if worker else "") or "").strip()
        name_key = (name.lower(), company.lower())
        if name_key in seen_name_keys:
            continue   # already represented by a gate sign-in
        seen_name_keys.add(name_key)
        result.append({
            "worker_id": wid,
            "worker_name": name or "Unknown",
            "company": company,
            "trade": c.get("worker_trade") or (worker.get("trade") if worker else ""),
            "check_in_time": c.get("check_in_time").isoformat() if isinstance(c.get("check_in_time"), datetime) else str(c.get("check_in_time", "")),
            "osha_number": worker.get("osha_number") if worker else "",
            "certifications": worker.get("certifications", []) if worker else [],
            # Legacy rows carry the inline base64 signature from the old
            # per-worker profile field. These aren't in R2 so the proxy
            # endpoint doesn't apply — frontend renders directly from
            # this string (data URL or base64).
            "worker_signature": worker.get("signature") if worker else None,
            "signin_id": None,
            "source": "legacy_checkin",
        })

    return result


@api_router.get("/projects/{project_id}/daily-headcount")
async def get_project_daily_headcount(
    project_id: str,
    date: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Per-sub headcount for a project on a given calendar date.

    Used by Daily Jobsite Log — a per-company headcount report, NOT a
    per-worker signature roster. The response is flat:

        [{"sub_name": "...", "trade": "...", "worker_count_today": N}, ...]

    Workers are counted, not listed. No signatures. The three logbooks
    that DO need per-worker signature autofill (preshift_signin,
    osha_log, toolbox_talk) continue to hit /checkins-today, which
    returns the roster + signin_id for signature proxy.
    """
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    now_eastern = datetime.now(eastern)
    target_date = date or now_eastern.strftime("%Y-%m-%d")
    try:
        day_eastern = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=eastern)
        day_start = day_eastern.astimezone(timezone.utc)
        day_end = (day_eastern + timedelta(hours=24)).astimezone(timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    # Project access check — same pattern as other project-scoped reads.
    project = await db.projects.find_one({"_id": to_query_id(project_id), "is_deleted": {"$ne": True}})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    # Aggregate in two passes — new gate sign_ins + legacy checkins —
    # keyed by (sub, trade). Dedup workers across passes by normalized
    # (name, company) so a worker who appears in both systems during
    # transition isn't counted twice.
    buckets: Dict[tuple, Dict[str, Any]] = {}   # (sub_lower, trade_lower) -> row
    seen_workers: set = set()                   # (name_lower, company_lower)

    # ── Pass 1: new gate sign_ins ──────────────────────────────────────
    sign_ins = await db.sign_ins.find({
        "project_id": project_id,
        "timestamp": {"$gte": day_start, "$lt": day_end},
    }).to_list(2000)
    eids: List[str] = []
    seen_eids: set = set()
    for si in sign_ins:
        eid = si.get("worker_enrollment_id")
        if eid and eid not in seen_eids:
            seen_eids.add(eid)
            eids.append(eid)

    if eids:
        oids = []
        for eid in eids:
            try:
                oids.append(ObjectId(eid))
            except Exception:
                pass
        async for e in db.worker_enrollments.find({"_id": {"$in": oids}}):
            sub = (e.get("sub_name") or "").strip()
            trade = (e.get("trade") or "").strip()
            name = (e.get("worker_name") or "").strip()
            worker_key = (name.lower(), sub.lower())
            if worker_key in seen_workers:
                continue
            seen_workers.add(worker_key)
            key = (sub.lower(), trade.lower())
            row = buckets.get(key)
            if row is None:
                row = {"sub_name": sub, "trade": trade, "worker_count_today": 0}
                buckets[key] = row
            row["worker_count_today"] += 1

    # ── Pass 2: legacy checkins (pre-gate-migration workers) ───────────
    try:
        legacy = await db.checkins.find({
            "project_id": project_id,
            "check_in_time": {"$gte": day_start, "$lt": day_end},
            "is_deleted": {"$ne": True},
        }).to_list(2000)
    except Exception:
        legacy = []

    for c in legacy:
        wid = c.get("worker_id")
        worker = await db.workers.find_one({"_id": to_query_id(wid)}) if wid else None
        name = (c.get("worker_name") or (worker.get("name") if worker else "") or "").strip()
        company = (c.get("worker_company") or (worker.get("company") if worker else "") or "").strip()
        trade = (c.get("worker_trade") or (worker.get("trade") if worker else "") or "").strip()
        worker_key = (name.lower(), company.lower())
        if worker_key in seen_workers or not name:
            continue
        seen_workers.add(worker_key)
        key = (company.lower(), trade.lower())
        row = buckets.get(key)
        if row is None:
            row = {"sub_name": company, "trade": trade, "worker_count_today": 0}
            buckets[key] = row
        row["worker_count_today"] += 1

    # Stable order: by sub_name, then trade
    rows = sorted(buckets.values(), key=lambda r: ((r["sub_name"] or "").lower(), (r["trade"] or "").lower()))
    return rows


@api_router.get("/signatures/{signin_id}")
async def get_signature_image(signin_id: str, current_user=Depends(get_current_user)):
    """Authenticated proxy for a worker's daily signature image.

    Permanent mechanism (replaces presigned R2 URLs, which were
    unreliable for logbook forms left open through a full shift).

    Auth: session-authenticated user must have project-level read
          access to the project containing the sign-in.
    Source: the R2 key stored on the sign_in's matching daily_signature
            row. No app-layer cache — R2 reads are cheap and browser
            caching via Cache-Control: private, max-age=3600 covers
            repeat loads within a session.

    Error shapes — frontend distinguishes these to render four
    distinct states (missing signature, forbidden, storage down,
    unknown id):
      404 {"error":"signature_not_found"}   — sign-in has no stored signature
      403 {"error":"forbidden"}             — cross-project access attempt
      500 {"error":"storage_unavailable"}   — R2 read failure
      404 {"error":"signature_not_found"}   — sign-in id does not exist
    """
    try:
        oid = ObjectId(signin_id)
    except Exception:
        return JSONResponse(status_code=404, content={"error": "signature_not_found"})

    sign_in = await db.sign_ins.find_one({"_id": oid})
    if not sign_in:
        return JSONResponse(status_code=404, content={"error": "signature_not_found"})

    # Access check — resolve the project, compare company to the user's.
    project = await db.projects.find_one({
        "_id": to_query_id(sign_in.get("project_id")),
        "is_deleted": {"$ne": True},
    })
    if not project:
        return JSONResponse(status_code=404, content={"error": "signature_not_found"})
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    # Resolve the R2 key via daily_signatures (spec: "No schema changes"
    # — the key lives on daily_signatures, keyed by
    # project_id + worker_enrollment_id + calendar_date, derivable from
    # the sign_in's own fields).
    from zoneinfo import ZoneInfo
    ts = sign_in.get("timestamp") or datetime.now(timezone.utc)
    if isinstance(ts, datetime) and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    date_ymd = (
        ts.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if isinstance(ts, datetime) else ""
    )
    sig_row = await db.daily_signatures.find_one({
        "project_id": sign_in.get("project_id"),
        "worker_enrollment_id": sign_in.get("worker_enrollment_id"),
        "calendar_date": date_ymd,
    })
    r2_key = (sig_row or {}).get("signature_r2_key")
    if not r2_key:
        return JSONResponse(status_code=404, content={"error": "signature_not_found"})

    # Separate card-audit bucket (object-locked, 7-year retention).
    # Not the general R2_BUCKET_NAME — don't fall through to that.
    import card_audit as _ca
    if not _r2_client or not _ca.CARD_AUDIT_BUCKET_NAME:
        return JSONResponse(status_code=500, content={"error": "storage_unavailable"})
    try:
        obj = await asyncio.to_thread(
            _r2_client.get_object,
            Bucket=_ca.CARD_AUDIT_BUCKET_NAME,
            Key=r2_key,
        )
        content_type = obj.get("ContentType") or "image/png"
        body = obj["Body"].read()
    except Exception as e:
        logger.error(f"signature proxy R2 read failed key={r2_key}: {e!r}")
        return JSONResponse(status_code=500, content={"error": "storage_unavailable"})

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ==================== ROOT ENDPOINT ====================

@api_router.get("/")
async def root():
    return {"message": "Levelog API v2.0.0 - Sync Enabled", "status": "running"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/checkin/{tag_id}")
async def serve_checkin_page(tag_id: str):
    from fastapi.responses import HTMLResponse
    html_path = Path(__file__).parent / "checkin.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Check-in page not found")
    return HTMLResponse(content=html_path.read_text(), status_code=200)

@app.get("/checkin/{project_id}/{tag_id}")
async def serve_checkin_page_full(project_id: str, tag_id: str):
    from fastapi.responses import HTMLResponse
    html_path = Path(__file__).parent / "checkin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

# ==================== COMBINED REPORT GENERATOR ====================
def render_signature_html(sig, label="CP Signature"):
    """Render a signature as email-safe HTML. Signatures stay as base64
    since they are small PNGs critical for legal compliance."""
    if not sig:
        return ""
    if isinstance(sig, str):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;">'
            '<tr><td style="font-weight:bold;color:#0A1929;font-size:14px;padding-bottom:4px;">'
            + label + ':</td></tr>'
            '<tr><td><img src="data:image/png;base64,' + sig
            + '" style="max-width:280px;height:auto;border:1px solid #e2e8f0;border-radius:4px;" /></td></tr>'
            '</table>'
        )
    if isinstance(sig, dict):
        sig_data = sig.get("data") or sig.get("paths") or ""
        signer = sig.get("signer_name", "")
        if isinstance(sig_data, str) and sig_data:
            full_label = f"{label} ({signer})" if signer else label
            return (
                '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;">'
                '<tr><td style="font-weight:bold;color:#0A1929;font-size:14px;padding-bottom:4px;">'
                + full_label + ':</td></tr>'
                '<tr><td><img src="data:image/png;base64,' + sig_data
                + '" style="max-width:280px;height:auto;border:1px solid #e2e8f0;border-radius:4px;" /></td></tr>'
                '</table>'
            )
        if signer:
            return (
                '<p style="color:#475569;margin:8px 0;">'
                '<strong style="color:#0A1929;">' + label + ':</strong> '
                + signer + ' (signed)</p>'
            )
    return ""


async def generate_combined_report(project_id: str, date: str) -> str:
    """Generate email-safe HTML report. Uses table-based layout, bgcolor attrs,
    and URL-based images for Gmail/Outlook/Apple Mail compatibility.

    Fixes:
      1) White background forced (Gmail dark mode defeated via bgcolor + color-scheme)
      2) Fits in email box (table layout, zero flexbox)
      3) Photos render (base64 -> absolute URLs to public image endpoints)
      4) Full report content (daily_log_photos fetched + all sections)
    """

    BASE_URL = "https://api.levelog.com"

    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = project.get("name", "Unknown") if project else "Unknown"
    project_address = project.get("address", "") if project else ""

    logbooks = await db.logbooks.find({
        "project_id": project_id,
        "date": date,
        "is_deleted": {"$ne": True},
    }).to_list(100)

    daily_log = await db.daily_logs.find_one({
        "project_id": project_id,
        "date": date,
        "is_deleted": {"$ne": True},
    })

    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": day_start, "$lt": day_end},
        "is_deleted": {"$ne": True},
    }).to_list(500)

    checkin_count = len(checkins)

    # --- Fetch daily_log_photos if daily_log exists ---
    daily_log_photos = []
    if daily_log:
        dl_id = str(daily_log["_id"])
        daily_log_photos = await db.daily_log_photos.find(
            {"daily_log_id": dl_id, "is_deleted": {"$ne": True}},
            {"data": 0},
        ).to_list(500)

    # Reusable inline style constants
    TH = (
        'style="background-color:#1e293b;color:#ffffff;padding:10px 12px;'
        'text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;'
        'letter-spacing:0.5px;" bgcolor="#1e293b"'
    )
    TD = 'style="padding:10px 12px;border-bottom:1px solid #e2e8f0;color:#334155;"'
    EMPTY_5 = f'<tr><td colspan="5" {TD}>&mdash;</td></tr>'
    EMPTY_3 = f'<tr><td colspan="3" {TD}>&mdash;</td></tr>'

    def section_title(text):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="margin:28px 0 12px 0;">'
            '<tr><td style="font-size:16px;font-weight:600;color:#0A1929;'
            f'padding-bottom:8px;border-bottom:2px solid #e2e8f0;">{text}</td></tr></table>'
        )

    def sub_title(text):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="margin:16px 0 8px 0;">'
            f'<tr><td style="font-size:14px;font-weight:600;color:#475569;">{text}</td></tr></table>'
        )

    def info_box(content):
        return (
            '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
            'style="margin:12px 0;" bgcolor="#f1f5f9">'
            '<tr><td style="background-color:#f1f5f9;padding:14px 18px;'
            'border-left:4px solid #1565C0;font-size:14px;line-height:1.7;color:#475569;">'
            + content + '</td></tr></table>'
        )

    def para(text):
        return f'<p style="color:#475569;line-height:1.6;margin:8px 0;">{text}</p>'

    def bold_para(label, value):
        return (
            '<p style="color:#475569;line-height:1.6;margin:8px 0;">'
            f'<strong style="color:#0A1929;">{label}:</strong> {value}</p>'
        )

    # ==========================================================
    #  DAILY JOBSITE (CP Logbook)
    # ==========================================================
    daily_jobsite = next((l for l in logbooks if l.get("log_type") == "daily_jobsite"), None)
    jobsite_html = ""
    if daily_jobsite:
        logbook_id = str(daily_jobsite["_id"])
        d = daily_jobsite.get("data", {})
        activities = d.get("activities", [])

        act_rows = ""
        for ai, act in enumerate(activities):
            # Photos as URL-based <img> tags
            photos = ""
            for pi, photo in enumerate(act.get("photos") or []):
                if photo.get("base64"):
                    url = f"{BASE_URL}/api/reports/logbook-photo/{logbook_id}/{ai}/{pi}"
                    photos += (
                        f'<img src="{url}" width="140" height="105" '
                        'style="width:140px;height:105px;object-fit:cover;'
                        'border-radius:4px;border:1px solid #e2e8f0;'
                        'display:inline-block;margin:3px;" />'
                    )

            act_rows += (
                f'<tr>'
                f'<td {TD}>{act.get("crew_id", "")}</td>'
                f'<td {TD}>{act.get("company", "")}</td>'
                f'<td {TD}>{act.get("num_workers", "")}</td>'
                f'<td {TD}>{act.get("work_description", "")}</td>'
                f'<td {TD}>{act.get("work_locations", "")}</td>'
                f'</tr>'
            )
            if photos:
                act_rows += (
                    '<tr><td colspan="5" style="padding:8px 12px;border-bottom:1px solid #e2e8f0;'
                    f'background-color:#f8fafc;" bgcolor="#f8fafc">{photos}</td></tr>'
                )

        equip = d.get("equipment_on_site", {})
        equip_list = ", ".join(k.replace("_", " ").title() for k, v in equip.items() if v)
        chk = d.get("checklist_items", {})
        check_list = ", ".join(k.replace("_", " ").title() for k, v in chk.items() if v)

        obs_html = ""
        obs_rows = ""
        for obs in d.get("observations", []):
            obs_rows += (
                f'<tr><td {TD}>{obs.get("description", "")}</td>'
                f'<td {TD}>{obs.get("responsible_party", "")}</td>'
                f'<td {TD}>{obs.get("remedy", "")}</td></tr>'
            )
        if obs_rows:
            obs_html = (
                sub_title("Safety Observations")
                + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
                  'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
                + f'<tr><th {TH}>Description</th><th {TH}>Responsible</th><th {TH}>Remedy</th></tr>'
                + obs_rows + '</table>'
            )

        cp_sig = render_signature_html(daily_jobsite.get("cp_signature"), "CP Signature")
        sup_sig = render_signature_html(d.get("superintendent_signature"), "Superintendent")
        visitors = d.get("visitors_deliveries", "")
        wind = d.get("weather_wind", "")

        weather_str = f'{d.get("weather", "N/A")} {d.get("weather_temp", "")}'
        if wind:
            weather_str += f' &mdash; Wind: {wind}'

        jobsite_html = (
            section_title("Daily Jobsite Log (NYC DOB 3301-02)")
            + info_box(
                f'<strong style="color:#0A1929;">Weather:</strong> {weather_str}<br />'
                f'<strong style="color:#0A1929;">Description:</strong> {d.get("general_description", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Time In:</strong> {d.get("time_in") or "N/A"}'
                f' &nbsp;&nbsp; <strong style="color:#0A1929;">Time Out:</strong> {d.get("time_out") or "N/A"}<br />'
                f'<strong style="color:#0A1929;">Areas Visited:</strong> {d.get("areas_visited") or "N/A"}'
            )
            + sub_title("Activity Details")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Crew</th><th {TH}>Company</th><th {TH}>Workers</th>'
              f'<th {TH}>Description</th><th {TH}>Location</th></tr>'
            + (act_rows or EMPTY_5)
            + '</table>'
            + bold_para("Equipment", equip_list or "None")
            + bold_para("Inspected", check_list or "None")
            + obs_html
            + (bold_para("Visitors / Deliveries", visitors) if visitors else "")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="margin-top:16px;border-top:1px solid #e2e8f0;"><tr><td style="padding-top:12px;">'
            + bold_para("CP", daily_jobsite.get("cp_name", "N/A"))
            + cp_sig + sup_sig
            + '</td></tr></table>'
        )

    # ==========================================================
    #  TOOLBOX TALK
    # ==========================================================
    toolbox = next((l for l in logbooks if l.get("log_type") == "toolbox_talk"), None)
    toolbox_html = ""
    if toolbox:
        td_data = toolbox.get("data", {})
        topics = td_data.get("checked_topics", {})
        topic_list = ", ".join(k.replace("_", " ").title() for k, v in topics.items() if v)
        att_rows = ""
        for a in td_data.get("attendees", []):
            signed = "&#10003;" if a.get("signed") else "&mdash;"
            att_rows += (
                f'<tr><td {TD}>{a.get("name", "")}</td>'
                f'<td {TD}>{a.get("company", "")}</td>'
                f'<td {TD}>{signed}</td></tr>'
            )

        tb_sig = render_signature_html(toolbox.get("cp_signature"), "CP Signature")

        toolbox_html = (
            section_title("Tool Box Talk")
            + info_box(
                f'<strong style="color:#0A1929;">Location:</strong> {td_data.get("location", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Company:</strong> {td_data.get("company_name", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Performed By:</strong> {td_data.get("performed_by", "N/A")}<br />'
                f'<strong style="color:#0A1929;">Time:</strong> {td_data.get("meeting_time", "N/A")}'
            )
            + bold_para("Topics", topic_list or "None")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Name</th><th {TH}>Company</th><th {TH}>Signed</th></tr>'
            + (att_rows or EMPTY_3)
            + '</table>'
            + bold_para("CP", toolbox.get("cp_name", "N/A"))
            + tb_sig
        )

    # ==========================================================
    #  PRE-SHIFT SIGN-IN
    # ==========================================================
    preshift = next((l for l in logbooks if l.get("log_type") == "preshift_signin"), None)
    preshift_html = ""
    if preshift:
        pd = preshift.get("data", {})
        w_rows = ""
        for w in pd.get("workers", []):
            if w.get("name", "").strip():
                w_rows += (
                    f'<tr><td {TD}>{w.get("name", "")}</td>'
                    f'<td {TD}>{w.get("company", "")}</td>'
                    f'<td {TD}>{w.get("osha_number", "")}</td>'
                    f'<td {TD}>{w.get("had_injury") or "&mdash;"}</td>'
                    f'<td {TD}>{w.get("inspected_ppe") or "&mdash;"}</td></tr>'
                )

        ps_sig = render_signature_html(preshift.get("cp_signature"), "CP Signature")

        preshift_html = (
            section_title("Pre-Shift Sign-In")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Name</th><th {TH}>Company</th><th {TH}>OSHA #</th>'
              f'<th {TH}>Injury</th><th {TH}>PPE</th></tr>'
            + (w_rows or EMPTY_5)
            + '</table>'
            + bold_para("CP", preshift.get("cp_name", "N/A"))
            + ps_sig
        )

    # ==========================================================
    #  SITE SUPERINTENDENT LOG  (daily_log)
    # ==========================================================
    site_html = ""
    if daily_log:
        dl_id = str(daily_log["_id"])

        # Subcontractor cards
        sub_rows = ""
        for card in (daily_log.get("subcontractor_cards") or []):
            sub_rows += (
                f'<tr><td {TD}>{card.get("company_name", "N/A")}</td>'
                f'<td {TD}>{card.get("trade", "N/A")}</td>'
                f'<td {TD}>{card.get("num_workers", 0)}</td>'
                f'<td {TD}>{card.get("hours", "N/A")}</td>'
                f'<td {TD}>{card.get("description", "N/A")}</td></tr>'
            )

        # Safety checklist
        safety_rows = ""
        for item_key, item_val in (daily_log.get("safety_checklist") or {}).items():
            st = item_val.get("status", "N/A") if isinstance(item_val, dict) else str(item_val)
            cb = item_val.get("checked_by", "") if isinstance(item_val, dict) else ""
            safety_rows += (
                f'<tr><td {TD}>{item_key.replace("_", " ").title()}</td>'
                f'<td {TD}>{st}</td><td {TD}>{cb}</td></tr>'
            )

        corrective_na = daily_log.get("corrective_actions_na", False)
        corrective_text = "N/A" if corrective_na else (daily_log.get("corrective_actions", "") or "None recorded")

        incident_na = daily_log.get("incident_log_na", False)
        incident_text = "N/A" if incident_na else (daily_log.get("incident_log", "") or "None recorded")

        work_performed = daily_log.get("work_performed", "")
        work_html = (sub_title("Work Performed") + para(work_performed)) if work_performed else ""

        # Superintendent signature
        sup_sig_html = ""
        sup_sig_raw = daily_log.get("superintendent_signature")
        if sup_sig_raw and isinstance(sup_sig_raw, dict):
            sn = sup_sig_raw.get("signer_name", "Superintendent")
            sd = sup_sig_raw.get("paths") or sup_sig_raw.get("data") or ""
            if isinstance(sd, str) and sd:
                sup_sig_html = (
                    '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;">'
                    '<tr><td style="font-weight:bold;color:#0A1929;font-size:14px;padding-bottom:4px;">'
                    f'Superintendent ({sn}):</td></tr>'
                    f'<tr><td><img src="data:image/png;base64,{sd}" '
                    'style="max-width:300px;height:auto;border:1px solid #e2e8f0;border-radius:4px;" /></td></tr>'
                    '</table>'
                )
            elif sn:
                sup_sig_html = bold_para("Superintendent", sn + " (signed)")

        # CP signature
        cp_sig_html = ""
        cp_sig_raw = daily_log.get("competent_person_signature")
        if cp_sig_raw and isinstance(cp_sig_raw, dict):
            cn = cp_sig_raw.get("signer_name", "Competent Person")
            cd = cp_sig_raw.get("paths") or cp_sig_raw.get("data") or ""
            if isinstance(cd, str) and cd:
                cp_sig_html = (
                    '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;">'
                    '<tr><td style="font-weight:bold;color:#0A1929;font-size:14px;padding-bottom:4px;">'
                    f'Competent Person ({cn}):</td></tr>'
                    f'<tr><td><img src="data:image/png;base64,{cd}" '
                    'style="max-width:300px;height:auto;border:1px solid #e2e8f0;border-radius:4px;" /></td></tr>'
                    '</table>'
                )
            elif cn:
                cp_sig_html = bold_para("Competent Person", cn + " (signed)")

        # Photos from daily_log_photos collection
        photos_section = ""
        if daily_log_photos:
            cells = []
            for ph in daily_log_photos:
                pid = str(ph["_id"])
                url = f"{BASE_URL}/api/daily-logs/{dl_id}/photos/{pid}/image"
                cap = ph.get("caption", "")
                cells.append(
                    f'<td style="padding:3px;vertical-align:top;" valign="top">'
                    f'<img src="{url}" width="180" height="135" alt="{cap}" '
                    f'style="width:180px;height:135px;object-fit:cover;border-radius:4px;'
                    f'border:1px solid #e2e8f0;display:block;" /></td>'
                )
            rows = ""
            for i in range(0, len(cells), 3):
                rows += "<tr>" + "".join(cells[i:i + 3]) + "</tr>"
            photos_section = (
                sub_title("Site Photos")
                + f'<table cellpadding="0" cellspacing="0" border="0">{rows}</table>'
            )

        not_signed_super = bold_para("Superintendent", "Not signed")
        not_signed_cp = bold_para("Competent Person", "Not signed")

        site_html = (
            section_title("Site Superintendent Log")
            + info_box(
                f'<strong style="color:#0A1929;">Weather:</strong> '
                f'{daily_log.get("weather", "N/A")} '
                f'{daily_log.get("weather_temp", "") or ""} '
                f'{daily_log.get("weather_wind", "") or ""}<br />'
                f'<strong style="color:#0A1929;">Workers on Site:</strong> {daily_log.get("worker_count", 0)}<br />'
                f'<strong style="color:#0A1929;">Notes:</strong> {daily_log.get("notes", "N/A")}'
            )
            + work_html
            + sub_title("Subcontractor Activity")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Company</th><th {TH}>Trade</th><th {TH}>Workers</th>'
              f'<th {TH}>Hours</th><th {TH}>Description</th></tr>'
            + (sub_rows or EMPTY_5) + '</table>'
            + sub_title("Safety Checklist")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + f'<tr><th {TH}>Item</th><th {TH}>Status</th><th {TH}>Checked By</th></tr>'
            + (safety_rows or EMPTY_3) + '</table>'
            + sub_title("Corrective Actions") + para(corrective_text)
            + sub_title("Incident Log") + para(incident_text)
            + photos_section
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="margin-top:20px;border-top:2px solid #e2e8f0;"><tr><td style="padding-top:16px;">'
            + sub_title("Signatures")
            + (sup_sig_html or not_signed_super)
            + (cp_sig_html or not_signed_cp)
            + '</td></tr></table>'
        )

    # ==========================================================
    #  ADDITIONAL LOGBOOKS (new types: SSC, concrete, crane, hot work, excavation)
    # ==========================================================
    handled_types = {"daily_jobsite", "toolbox_talk", "preshift_signin", "scaffold_maintenance",
                     "subcontractor_orientation", "osha_log"}
    additional_logbooks_html = ""
    for logbook in logbooks:
        lt = logbook.get("log_type", "")
        if lt in handled_types:
            continue
        d = logbook.get("data", {})
        label = lt.replace("_", " ").title()
        # Build key-value rows from the data dict
        data_rows = ""
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                if isinstance(v, list):
                    v_str = ", ".join(str(item) if not isinstance(item, dict) else str(item) for item in v[:10])
                else:
                    v_str = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv)
            elif isinstance(v, bool):
                v_str = "Yes" if v else "No"
            else:
                v_str = str(v) if v else ""
            if v_str:
                field_label = k.replace("_", " ").title()
                data_rows += f'<tr><td {TD} style="font-weight:600;width:35%;padding:10px 12px;border-bottom:1px solid #e2e8f0;color:#334155;">{field_label}</td><td {TD}>{v_str}</td></tr>'

        sig_html = render_signature_html(logbook.get("cp_signature"), "Signature")
        additional_logbooks_html += (
            section_title(f"{label}")
            + '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
              'style="border-collapse:collapse;margin:12px 0;font-size:13px;">'
            + (data_rows or f'<tr><td {TD}>No data recorded</td></tr>')
            + '</table>'
            + sig_html
        )

    # ==========================================================
    #  FINAL HTML ASSEMBLY  (email-safe, table-based)
    # ==========================================================
    gen_time = datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p')
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

    html = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="light only" />
<meta name="supported-color-schemes" content="light only" />
<title>Daily Construction Report - {project_name}</title>
<!--[if mso]><style>table, td {{font-family: Arial, sans-serif !important;}}</style><![endif]-->
<style>
  :root {{ color-scheme: light only; }}
  body, .body {{ background-color: #f0f4f8 !important; }}
  u + .body {{ background-color: #f0f4f8 !important; }}
  [data-ogsc] .wrapper {{ background-color: #ffffff !important; }}
  [data-ogsc] body {{ background-color: #f0f4f8 !important; }}
  @media (prefers-color-scheme: dark) {{
    body, .body {{ background-color: #f0f4f8 !important; }}
    .wrapper {{ background-color: #ffffff !important; }}
    .content-cell {{ background-color: #ffffff !important; color: #1a2332 !important; }}
  }}
</style>
</head>
<body class="body" style="margin:0;padding:0;background-color:#f0f4f8;font-family:{font};-webkit-font-smoothing:antialiased;" bgcolor="#f0f4f8">

<table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f0f4f8" style="background-color:#f0f4f8;">
<tr><td align="center" style="padding:20px 0;">

<table cellpadding="0" cellspacing="0" border="0" width="680" class="wrapper" bgcolor="#ffffff"
  style="background-color:#ffffff;max-width:680px;width:100%;">

  <!-- HEADER -->
  <tr>
    <td style="background-color:#0A1929;padding:32px 40px;" bgcolor="#0A1929">
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr><td style="color:rgba(255,255,255,0.5);font-size:10px;letter-spacing:3px;text-transform:uppercase;padding-bottom:16px;font-family:{font};">LEVELOG</td></tr>
        <tr><td style="color:#ffffff;font-size:22px;font-weight:600;letter-spacing:0.5px;padding-bottom:4px;font-family:{font};">Daily Construction Report</td></tr>
        <tr><td style="color:rgba(255,255,255,0.7);font-size:13px;font-weight:400;font-family:{font};">{project_name}</td></tr>
      </table>
    </td>
  </tr>

  <!-- SUMMARY ROW -->
  <tr>
    <td style="background-color:#f8fafc;padding:20px 40px;border-bottom:1px solid #e2e8f0;" bgcolor="#f8fafc">
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
          <td width="33%" valign="top" style="vertical-align:top;">
            <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;font-weight:600;">DATE</span><br />
            <span style="font-size:15px;color:#0A1929;font-weight:500;">{date}</span>
          </td>
          <td width="34%" valign="top" style="vertical-align:top;">
            <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;font-weight:600;">ADDRESS</span><br />
            <span style="font-size:15px;color:#0A1929;font-weight:500;">{project_address or 'N/A'}</span>
          </td>
          <td width="33%" valign="top" style="vertical-align:top;">
            <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;font-weight:600;">WORKERS</span><br />
            <span style="font-size:15px;color:#0A1929;font-weight:500;">{checkin_count}</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- CONTENT -->
  <tr>
    <td class="content-cell" style="padding:24px 40px 40px;background-color:#ffffff;color:#1a2332;" bgcolor="#ffffff">
      {jobsite_html}
      {toolbox_html}
      {preshift_html}
      {site_html}
      {additional_logbooks_html}
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background-color:#f8fafc;padding:24px 40px;text-align:center;border-top:1px solid #e2e8f0;" bgcolor="#f8fafc">
      <span style="font-size:11px;color:#94a3b8;">This report was automatically generated on {gen_time} UTC</span><br />
      <span style="font-size:10px;color:#cbd5e1;letter-spacing:3px;text-transform:uppercase;">LEVELOG CONSTRUCTION MANAGEMENT</span>
    </td>
  </tr>

</table>
</td></tr></table>

</body>
</html>"""
    return html

@api_router.get("/reports/project/{project_id}/date/{date}")
async def get_combined_report(project_id: str, date: str, token: Optional[str] = None, current_user = Depends(get_current_user)):
    """Generate combined daily report for a project+date."""
    from fastapi.responses import HTMLResponse
    html = await generate_combined_report(project_id, date)
    return HTMLResponse(content=html)
@api_router.get("/reports/project/{project_id}/date/{date}/pdf")
async def get_combined_report_pdf(project_id: str, date: str, token: Optional[str] = None, current_user = Depends(get_current_user)):
    """Generate combined daily report as downloadable PDF."""
    from fastapi.responses import Response
    html = await generate_combined_report(project_id, date)
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")
    
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = (project.get("name", "report") if project else "report").replace(" ", "_")
    filename = f"Levelog_Report_{project_name}_{date}.pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@api_router.get("/reports/project/{project_id}/preview/{date}")
async def get_report_preview(project_id: str, date: str, current_user = Depends(get_current_user)):
    """Get report preview metadata for a date — shows what has been filled so far (midday check).
    Returns summary of logbooks, checkins, daily log status without full HTML."""
    role = current_user.get("role")
    if role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Only admins can preview reports")

    project_id_obj = to_query_id(project_id)
    project = await db.projects.find_one({"_id": project_id_obj})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if role == "admin" and project.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Access denied")

    # Gather all data for the date
    logbooks = await db.logbooks.find({
        "project_id": project_id,
        "date": date,
        "is_deleted": {"$ne": True},
    }).to_list(100)

    daily_log = await db.daily_logs.find_one({
        "project_id": project_id,
        "date": date,
        "is_deleted": {"$ne": True},
    })

    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    checkin_count = await db.checkins.count_documents({
        "project_id": project_id,
        "check_in_time": {"$gte": day_start, "$lt": day_end},
        "is_deleted": {"$ne": True},
    })

    # Build summary of what sections are filled
    logbook_summary = []
    for lb in logbooks:
        logbook_summary.append({
            "log_type": lb.get("log_type"),
            "status": lb.get("status", "draft"),
            "has_signature": bool(lb.get("cp_signature")),
            "cp_name": lb.get("cp_name"),
            "updated_at": lb.get("updated_at").isoformat() if isinstance(lb.get("updated_at"), datetime) else str(lb.get("updated_at", "")),
        })

    # Check if report was already sent today
    already_sent = await db.report_emails.find_one({
        "project_id": project_id,
        "date": date,
    })

    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "date": date,
        "checkin_count": checkin_count,
        "logbooks": logbook_summary,
        "has_daily_log": bool(daily_log),
        "daily_log_status": daily_log.get("status") if daily_log else None,
        "daily_log_weather": daily_log.get("weather") if daily_log else None,
        "daily_log_worker_count": daily_log.get("worker_count", 0) if daily_log else 0,
        "subcontractor_count": len(daily_log.get("subcontractor_cards", []) or []) if daily_log else 0,
        "report_already_sent": bool(already_sent),
        "report_sent_at": already_sent.get("sent_at").isoformat() if already_sent and isinstance(already_sent.get("sent_at"), datetime) else None,
        "report_send_time": project.get("report_send_time", "18:00"),
        "report_email_list": project.get("report_email_list", []),
    }


@api_router.get("/logbooks/project/{project_id}/submitted")
async def get_submitted_logbooks(project_id: str, current_user = Depends(get_current_user)):
    """Get all submitted logbook entries grouped by date. For site device inspector view."""
    logbooks = await db.logbooks.find({
        "project_id": project_id,
        "status": "submitted",
        "is_deleted": {"$ne": True},
    }).sort("date", -1).to_list(500)
    by_date = {}
    for log in logbooks:
        d = log.get("date", "unknown")
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(serialize_id(dict(log)))
    return {"dates": by_date}

@api_router.put("/projects/{project_id}/report-settings")
async def update_report_settings(project_id: str, data: dict, current_user = Depends(get_current_user)):
    """Update report email list + send time with validation."""
    # Verify user is admin
    user_role = current_user.get("role")
    if user_role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Only admins can modify report settings")
    
    # Validate project exists
    project_id_obj = to_query_id(project_id)
    project = await db.projects.find_one({"_id": project_id_obj})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check multi-tenancy: admin must be in same company as project
    if user_role == "admin":
        company_id = current_user.get("company_id")
        if project.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Cannot modify projects outside your company")
    
    # Build update dict only with provided fields
    now = datetime.now(timezone.utc)
    update = {"updated_at": now}
    
    if "report_email_list" in data and data["report_email_list"] is not None:
        update["report_email_list"] = [email.lower() for email in data["report_email_list"]]
    
    if "report_send_time" in data and data["report_send_time"] is not None:
        update["report_send_time"] = data["report_send_time"]
    
    # Perform update
    result = await db.projects.update_one(
        {"_id": project_id_obj},
        {"$set": update}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    
    updated_project = await db.projects.find_one({"_id": project_id_obj})
    return {
        "message": "Report settings saved successfully",
        "report_email_list": updated_project.get("report_email_list", []),
        "report_send_time": updated_project.get("report_send_time", "18:00"),
    }

@api_router.get("/reports/project/{project_id}/history")
async def get_report_history(
    project_id: str,
    current_user = Depends(get_current_user),
    limit: int = Query(30, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Get report send history for a project (admin view)."""
    # Verify admin/owner
    role = current_user.get("role")
    if role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Only admins can view report history")
    
    # Verify project exists and user has access
    project_id_obj = to_query_id(project_id)
    project = await db.projects.find_one({"_id": project_id_obj})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if role == "admin" and project.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get report emails (automatic scheduler sends)
    history = await db.report_emails.find({
        "project_id": project_id
    }).sort("date", -1).skip(skip).limit(limit).to_list(limit)
    
    total = await db.report_emails.count_documents({"project_id": project_id})
    
    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "history": [serialize_id(h) for h in history],
        "total": total,
        "limit": limit,
        "skip": skip,
    }


@api_router.get("/reports/project/{project_id}/logs")
async def get_submitted_logs(
    project_id: str,
    current_user = Depends(get_current_user),
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    log_type: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
):
    """Get submitted logbook entries for a project (admin view)."""
    # Verify admin
    role = current_user.get("role")
    if role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Only admins can view logs")
    
    # Verify project
    project_id_obj = to_query_id(project_id)
    project = await db.projects.find_one({"_id": project_id_obj})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if role == "admin" and project.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Build query
    query = {
        "project_id": project_id,
        "status": "submitted",
        "is_deleted": {"$ne": True}
    }
    
    if date:
        query["date"] = date
    
    if log_type:
        query["log_type"] = log_type
    
    logs = await db.logbooks.find(query).sort("date", -1).limit(limit).to_list(limit)
    
    return {
        "project_id": project_id,
        "logs": [serialize_id(log) for log in logs],
        "filters": {
            "date": date,
            "log_type": log_type,
        }
    }

# ==================== DOB COMPLIANCE ENGINE ====================

def _parse_address_components(project_address: str) -> tuple:
    """Split "123 Main St, Brooklyn, NY" into (house_num, street_name).

    Sanitizes for Socrata $where — only uppercase alphanumerics + space
    survive, so attacker-supplied project names can't break out of the
    LIKE clause.
    """
    clean_address = ""
    if project_address:
        clean_address = project_address.split(",")[0].strip()[:40]
    house_num = ""
    street_name = ""
    if clean_address:
        parts = clean_address.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            house_num = parts[0]
            street_name = parts[1].upper()
        else:
            street_name = clean_address.upper()
    street_name = re.sub(r"[^A-Z0-9 ]", "", street_name)
    house_num = re.sub(r"[^0-9]", "", house_num)
    return house_num, street_name


async def _query_dob_apis(nyc_bin: str, project_address: str = "") -> list:
    """Query NYC Open Data Socrata endpoints by BIN and/or address."""
    all_records = []
    seen_ids = set()
    
    # Extract clean street address for address-based queries
    clean_address = ""
    if project_address:
        clean_address = project_address.split(",")[0].strip()[:40]
    
    # Determine if BIN is usable (not a placeholder like X000000)
    bin_usable = nyc_bin and not nyc_bin.endswith("000000")
    
    # Parse house number and street name separately
    house_num, street_name = _parse_address_components(project_address)
    
    endpoints = []
    
    # ── JOB FILINGS (DOB NOW - w9ak-ipjd) ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/w9ak-ipjd.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "job_status",
            "id_field": "job_filing_number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/w9ak-ipjd.json",
            "params": {"house_no": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "50"},
            "record_type": "job_status",
            "id_field": "job_filing_number",
        })
    
    # ── VIOLATIONS: DOB NOW Safety (855j-jady) - NEWEST, check first ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/855j-jady.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "violation",
            "id_field": "violation_number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/855j-jady.json",
            "params": {"house_number": house_num, "$where": f"upper(street) like '%{street_name}%'", "$limit": "50"},
            "record_type": "violation",
            "id_field": "violation_number",
        })
    
    # ── VIOLATIONS: BIS legacy (3h2n-5cm9) - older violations ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/3h2n-5cm9.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "violation",
            "id_field": "isn_dob_bis_viol",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/3h2n-5cm9.json",
            "params": {"house_number": house_num, "$where": f"upper(street) like '%{street_name}%'", "$limit": "50"},
            "record_type": "violation",
            "id_field": "isn_dob_bis_viol",
        })
    
    # ── VIOLATIONS: ECB/OATH (6bgk-3dad) - adjudicated summonses ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/6bgk-3dad.json",
            "params": {"bin": nyc_bin, "$limit": "100", "$order": "issue_date DESC"},
            "record_type": "violation",
            "id_field": "ecb_violation_number",
        })
    # ECB/OATH (6bgk-3dad) has no `violation_address` — the only address
    # fields are `respondent_*` (mailing address of the respondent, not
    # the violation site). BIN is the only reliable key for this dataset,
    # so no address-shape fallback is added here.
    
    # ── PERMITS: DOB NOW Build (rbx6-tga4) - NEWEST, check first.
    #    This dataset has NO `filing_date` column — available date fields
    #    are `approved_date`, `issued_date`, `expired_date`. Ordering by
    #    a non-existent column made Socrata 400 every query, which is
    #    why DOB NOW Build permits were silently missing from projects.
    #    Order by `issued_date DESC` so renewal collapse keeps the
    #    most-recently-issued filing.
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
            "params": {"bin": nyc_bin, "$limit": "250", "$order": "issued_date DESC"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
            "params": {"house_no": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "250", "$order": "issued_date DESC"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })

    # ── PERMITS: DOB NOW Electrical (dm9a-ab7w) - separate dataset for
    #    electrical permits (not returned by rbx6-tga4 or ipu4-2q9a).
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/dm9a-ab7w.json",
            "params": {"bin": nyc_bin, "$limit": "250", "$order": "filing_date DESC"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })
    if house_num and street_name:
        # DOB NOW Electrical address column is `house_number` (not `house_no`
        # like the Build dataset — different teams, different schemas).
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/dm9a-ab7w.json",
            "params": {"house_number": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "250", "$order": "filing_date DESC"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })

    # ── PERMITS: BIS legacy (ipu4-2q9a) - pre-2018 permits across
    #    all trades (PL, EL, EQ, etc.). Order by filing_date DESC.
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/ipu4-2q9a.json",
            "params": {"bin__": nyc_bin, "$limit": "250", "$order": "filing_date DESC"},
            "record_type": "permit",
            "id_field": "job__",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/ipu4-2q9a.json",
            "params": {"house__": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "250", "$order": "filing_date DESC"},
            "record_type": "permit",
            "id_field": "job__",
        })
    
    # ── DOB INSPECTIONS (p937-wjvj) ──
    # Active projects easily have 100+ inspections over a year — the
    # old $limit=50 was truncating older records off the end of the
    # DESC sort, which is how April inspections disappear when there
    # have been 50 more-recent inspections since. Bump to 500 and
    # add an address-based fallback so BIN churn doesn't hide data.
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/p937-wjvj.json",
            "params": {"bin": nyc_bin, "$limit": "500", "$order": "inspection_date DESC"},
            "record_type": "inspection",
            "id_field": "job_ticket_or_work_order_id",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/p937-wjvj.json",
            "params": {
                "house_number": house_num,
                "$where": f"upper(street_name) like '%{street_name}%'",
                "$limit": "500",
                "$order": "inspection_date DESC",
            },
            "record_type": "inspection",
            "id_field": "job_ticket_or_work_order_id",
        })

    # ── DOB COMPLAINTS RECEIVED (eabe-havv) - Primary DOB complaint source ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/eabe-havv.json",
            "params": {"bin": nyc_bin, "$limit": "50", "$order": "date_entered DESC"},
            "record_type": "complaint",
            "id_field": "complaint_number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/eabe-havv.json",
            "params": {"house_number": house_num, "$where": f"upper(house_street) like '%{street_name}%'", "$limit": "50", "$order": "date_entered DESC"},
            "record_type": "complaint",
            "id_field": "complaint_number",
        })

    
    # Per-endpoint counters so permit-count regressions ("previously 7,
    # now 2") can be diagnosed from a single sync log line without
    # live-tailing. Reported after the loop completes.
    per_endpoint_stats: List[Dict[str, Any]] = []

    async with ServerHttpClient(timeout=20.0) as http_client:
        for ep in endpoints:
            raw_returned = 0
            kept_after_dedup = 0
            try:
                resp = await http_client.get(ep["url"], params=ep["params"])
                if resp.status_code == 200:
                    records = resp.json()
                    if not isinstance(records, list):
                        records = []
                    raw_returned = len(records)
                    for rec in records:
                        # Build a dedup key from the record's unique ID
                        id_field = ep["id_field"]
                        raw_id = str(rec.get(id_field, "")).strip()

                        # Inspections with empty job_ticket_or_work_order_id
                        # are dropped by a pure raw_id gate — and there are
                        # real ones with blank tickets in p937-wjvj,
                        # especially older quick-close records. Build a
                        # composite fallback (job + date + result) so we
                        # don't silently lose attestations that actually
                        # happened.
                        if not raw_id and ep["record_type"] == "inspection":
                            composite = "|".join([
                                str(rec.get("job_id") or rec.get("job_filing_number") or rec.get("job__") or ""),
                                str(rec.get("inspection_date") or rec.get("approved_date") or ""),
                                str(rec.get("inspection_type") or rec.get("job_progress") or ""),
                                str(rec.get("result") or ""),
                                str(rec.get("bin") or rec.get("bin__") or ""),
                            ])
                            if composite.strip("|"):
                                raw_id = f"composite:{composite}"
                                rec["_id_field"] = "_composite_inspection_key"

                        if not raw_id:
                            continue

                        # Permits need special handling: DOB issues a new
                        # filing per renewal (B00834550-I1, -I2, -I3...)
                        # with distinct job_filing_numbers. The old filings
                        # stay in the dataset forever. If we dedup on the
                        # raw filing number, users see every historical
                        # filing including long-expired ones that have
                        # already been renewed. Collapse by BASE job
                        # number + work_type and, because endpoints are
                        # ordered by filing_date DESC, the first record
                        # we see is the newest — keep it, drop older
                        # renewals for the same (base_job, work_type).
                        if ep["record_type"] == "permit":
                            base_job = _base_job_number(raw_id)
                            work_suffix = rec.get("work_type") or rec.get("permit_type") or rec.get("permit_sequence__") or ""
                            dedup_key = f"permit:{base_job}:{work_suffix}"
                            # Also stamp the record with the collapsed id
                            # so downstream storage uses the stable
                            # (base_job, work_type) key instead of the
                            # per-filing id that churns on every renewal.
                            rec["_collapsed_permit_id"] = f"{base_job}:{work_suffix}" if work_suffix else base_job
                        else:
                            dedup_key = f"{ep['record_type']}:{raw_id}"

                        # Skip if we already have this record from another endpoint
                        if dedup_key in seen_ids:
                            continue
                        seen_ids.add(dedup_key)
                        kept_after_dedup += 1

                        rec["_record_type"] = ep["record_type"]
                        rec["_id_field"] = id_field
                        if ep["record_type"] == "violation":
                            # Check ALL text fields for stop work indicators across all 3 violation datasets
                            swo_fields = [
                                rec.get("violation_type", ""),
                                rec.get("violation_type_code", ""),
                                rec.get("description", ""),
                                rec.get("violation_description", ""),
                                rec.get("infraction_codes", ""),
                                rec.get("penalty_description", ""),
                                rec.get("section_of_law", ""),
                                rec.get("severity", ""),
                                rec.get("violation_category", ""),
                                rec.get("certification_status", ""),
                                rec.get("status", ""),
                            ]
                            combined = " ".join(str(f or "").lower() for f in swo_fields)
                            if "stop work" in combined or "swo" in combined or "partial stop" in combined:
                                rec["_record_type"] = "swo"
                        all_records.append(rec)
                else:
                    logger.warning(f"DOB API {ep['url']} returned {resp.status_code}")
            except Exception as e:
                logger.error(f"DOB API error {ep['url']}: {e}")
            per_endpoint_stats.append({
                "url": ep["url"].rsplit("/", 1)[-1].replace(".json", ""),
                "record_type": ep["record_type"],
                "query_shape": "bin" if "bin" in ep["params"] or "bin__" in ep["params"] else "addr",
                "raw_returned": raw_returned,
                "kept_after_dedup": kept_after_dedup,
            })

    # Per-record-type breakdown. Permits get special treatment: log
    # raw vs collapsed counts AND the unique base_jobs observed so we
    # can diagnose "shows N permits, should be M" without guessing.
    def _pt_summary(record_type: str) -> str:
        rows = [s for s in per_endpoint_stats if s["record_type"] == record_type]
        raw = sum(r["raw_returned"] for r in rows)
        kept = sum(r["kept_after_dedup"] for r in rows)
        shapes = ",".join(f"{r['url']}({r['query_shape']})={r['raw_returned']}→{r['kept_after_dedup']}" for r in rows)
        return f"{record_type}: raw={raw} kept={kept} [{shapes}]"

    permit_base_jobs = sorted({
        r.get("_collapsed_permit_id", "").split(":")[0]
        for r in all_records if r.get("_record_type") == "permit" and r.get("_collapsed_permit_id")
    })
    logger.info(
        f"DOB query complete: {len(all_records)} unique records from "
        f"{len(endpoints)} endpoints — "
        + "; ".join(_pt_summary(rt) for rt in ("permit", "inspection", "complaint", "violation"))
        + (f" — permit_base_jobs={permit_base_jobs}" if permit_base_jobs else "")
    )
    return all_records
 
def _humanize_record_type(rt: str) -> str:
    """User-facing label. No screaming caps — those hurt spam scores."""
    rt = (rt or "alert").lower().replace("_", " ")
    pretty = {
        "violation":  "violation",
        "complaint":  "complaint",
        "permit":     "permit update",
        "inspection": "inspection result",
        "swo":        "stop work order",
    }
    return pretty.get(rt, rt)


async def _send_critical_dob_alert(project: dict, dob_log: dict):
    """Send a notification email about a DOB record that needs attention.

    Deliberately plain and conversational. All-caps subjects, red
    banners, bracketed "[CRITICAL]" tags, and heavy emoji push spam
    filters toward Promotions / Junk even when SPF/DKIM/DMARC are
    clean on Resend. Ship a plain-text alternative alongside the HTML
    — html-only messages are themselves a spam signal.
    """
    if not RESEND_API_KEY:
        return

    company_id = project.get("company_id")
    if not company_id:
        return

    recipients = []
    admin_users = await db.users.find({
        "company_id": company_id,
        "role":       {"$in": ["admin", "owner"]},
        "is_deleted": {"$ne": True},
    }).to_list(50)
    for u in admin_users:
        email = u.get("email")
        if email:
            recipients.append(email)
    if not recipients:
        return

    project_name = project.get("name", "your project")
    summary      = dob_log.get("ai_summary")  or "A new DOB record was found."
    next_action  = dob_log.get("next_action") or "Open Levelog to review the details."
    rt_raw       = dob_log.get("record_type", "")
    rt           = _humanize_record_type(rt_raw)
    dob_link     = dob_log.get("dob_link") or ""
    detected_at  = dob_log.get("detected_at") or datetime.now(timezone.utc)
    if isinstance(detected_at, datetime):
        detected_str = detected_at.strftime("%b %d, %Y at %I:%M %p UTC")
    else:
        detected_str = str(detected_at)

    # Plaintext alternative: present-tense, human, no urgency language.
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

    # HTML — neutral transactional layout. No red banner, no uppercase
    # pill labels, no emoji. Looks like any other account notification.
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
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from":     "Levelog <notifications@levelog.com>",
            "to":       recipients,
            "subject":  subject,
            "html":     html_body,
            "text":     text_body,
            "reply_to": "support@levelog.com",
        })
        logger.info(
            f"DOB notification sent for {project_name} "
            f"({rt}) to {len(recipients)} recipients"
        )
    except Exception as e:
        logger.error(f"Failed to send DOB notification: {e}")


# ==================== DOB ALERT GATING ====================
#
# Two layers, both keyed in system_config:
#
#  1. Initial-scan suppression. The first time a source (`dob`, `311`, `bis`)
#     scans a project, it pulls in the entire historical backlog. Emailing
#     every single one of those to the owner is worthless noise — the records
#     show in the app regardless. After the initial scan completes, we mark
#     the project/source pair done; from then on, newly-discovered records
#     can alert.
#
#  2. 24h per-record throttle. Mirrors the /dob-sync rate limiter shape.
#     Without this, every 30-min scheduler tick that rediscovers the same
#     Critical record resends the email.

_DOB_ALERT_THROTTLE_HOURS = 24


async def _initial_scan_done(project_id: str, source: str) -> bool:
    """True if `source` has already completed at least one full scan for
    this project. `source` is one of 'dob' (nightly DOB sync / NYC Open
    Data), '311' (311 Service Requests poll), 'bis' (BIS scraper)."""
    if not project_id or not source:
        return False
    try:
        doc = await db.system_config.find_one(
            {"key": f"initial_scan_done:{source}:{project_id}"}
        )
        return bool(doc)
    except Exception as e:
        logger.warning(f"initial_scan_done read failed: {e}")
        # On DB hiccups, err toward "done" so we don't silently suppress
        # real alerts forever.
        return True


async def _mark_initial_scan_done(project_id: str, source: str) -> None:
    if not project_id or not source:
        return
    try:
        await db.system_config.update_one(
            {"key": f"initial_scan_done:{source}:{project_id}"},
            {"$set": {
                "key":          f"initial_scan_done:{source}:{project_id}",
                "source":       source,
                "project_id":   project_id,
                "completed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"initial_scan mark failed: {e}")


async def _dob_alert_recently_sent(project_id: str, raw_dob_id: str,
                                     window_hours: int = _DOB_ALERT_THROTTLE_HOURS) -> bool:
    """Returns True if we've already emailed this (project, record) combo
    inside the window. Keyed on `dob_alert_sent:{project}:{raw_dob_id}`."""
    if not project_id or not raw_dob_id:
        return False
    try:
        doc = await db.system_config.find_one(
            {"key": f"dob_alert_sent:{project_id}:{raw_dob_id}"}
        )
        if not doc:
            return False
        last = doc.get("last_alert_at")
        if not isinstance(last, datetime):
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        return elapsed_hours < window_hours
    except Exception as e:
        logger.warning(f"alert throttle read failed: {e}")
        return False  # on error, err toward sending rather than silent-drop


async def _mark_dob_alert_sent(project_id: str, raw_dob_id: str) -> None:
    if not project_id or not raw_dob_id:
        return
    try:
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


async def _send_critical_dob_alert_throttled(
    project: dict, dob_log: dict, source: str = "dob",
) -> bool:
    """Wrapper that enforces:

      1. Initial-scan suppression: first scan of the (project, source) pair
         never emails. Records still get inserted and shown in the app —
         this just mutes the notification firehose during backfill.
      2. 24h per-record throttle.

    `source` is one of 'dob', '311', 'bis'. Returns True if an alert was
    actually sent, False if suppressed. Existing callers that don't pass
    `source` get the default 'dob' which matches the nightly scan.
    """
    project_id = str(project.get("_id") or project.get("id") or "")
    raw_dob_id = str(dob_log.get("raw_dob_id") or "")

    # Gate 1 — initial-scan suppression
    if not await _initial_scan_done(project_id, source):
        logger.info(
            f"DOB alert suppressed (initial scan in progress) "
            f"source={source} project={project.get('name')} "
            f"raw_dob_id={raw_dob_id}"
        )
        return False

    # Gate 2 — 24h per-record throttle
    if await _dob_alert_recently_sent(project_id, raw_dob_id):
        logger.info(
            f"DOB alert throttled (within 24h) source={source} "
            f"project={project.get('name')} raw_dob_id={raw_dob_id}"
        )
        return False

    await _send_critical_dob_alert(project, dob_log)
    await _mark_dob_alert_sent(project_id, raw_dob_id)
    return True


# ==================== 311 FAST POLL (Feature 1) ====================
# NYC 311 Service Requests dataset (`erm2-nwe9`) — distinct from the
# DOB-specific complaints dataset `eabe-havv` already polled by the nightly
# scan. 311 catches the faster-moving stuff: neighbor calls about noise /
# construction / illegal conversions / elevator outages / boiler issues.
#
# Runs every 30 minutes via APScheduler. Dedup key is the 311 `unique_key`,
# stored in `dob_logs.raw_dob_id` with a `311:` prefix to avoid collision
# with DOB complaint numbers.

_NYC_311_ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

# 311 complaint_type values that map to DOB-relevant inspector action.
# Curated per operator feedback: neighbor calls that actually produce
# inspector visits / violations against the building.
_311_ACTION_COMPLAINT_TYPES = {
    "Construction",
    "General Construction/Plumbing",
    "Construction Equipment",
    "Scaffold Safety",
    "Illegal Construction",
    "After Hours Work Illegal",
    "Non-Residential Building Condition",
    "Structural - Private",
    "Boiler",
    "Elevator",
    "Facade",
    "Unsafe Building",
    "Derrick/Suspension/Adjustable Scaffold",
    "Illegal Conversion",
}
_311_ACTION_SET_LOWER = {t.lower() for t in _311_ACTION_COMPLAINT_TYPES}


def _severity_for_311(complaint_type: str) -> str:
    """Return 'Action' for construction/structural categories, else 'Monitor'."""
    if not complaint_type:
        return "Monitor"
    return "Action" if complaint_type.strip().lower() in _311_ACTION_SET_LOWER else "Monitor"


def _fmt_311_summary(rec: dict) -> str:
    """One-line human summary for dob_logs.ai_summary."""
    ct = (rec.get("complaint_type") or "").strip() or "311 Complaint"
    desc = (rec.get("descriptor") or "").strip()
    agency = (rec.get("agency") or "").strip()
    parts = [ct]
    if desc and desc != ct:
        parts.append(desc)
    if agency:
        parts.append(f"({agency})")
    return " — ".join(parts)[:220]


def _next_action_for_311(rec: dict) -> str:
    status = (rec.get("status") or "").strip().lower()
    if status in ("closed", "resolved"):
        return "311 complaint is closed. Review disposition and file with the project record."
    return (
        "Inspector may visit within 48 hours. Pull the cited area, brief the super, "
        "and make sure relevant permits are posted + current."
    )


async def _fetch_311_for_project(
    client: "httpx.AsyncClient",
    bbl: str,
    house_num: str,
    street_name: str,
) -> List[dict]:
    """Fetch recent 311 service requests for a project.

    The 311 dataset (erm2-nwe9) has NO `bin` column — only `bbl`. Prior
    BIN queries were 400-ing every run. Prefer BBL when the project has
    one, otherwise fall back to an address match. Sorted newest-first,
    limit 100.

    Parameter renamed `nyc_bbl` → `bbl` 2026-04-27 (step 9.1) for
    consistency with the renamed Mongo field.
    """
    params: Optional[dict] = None
    if bbl:
        params = {
            "bbl":     bbl,
            "$limit":  "100",
            "$order":  "created_date DESC",
        }
    elif house_num and street_name:
        # incident_address is the raw street string ("123 Main St"); match
        # on house number + street name. Uppercased to tolerate casing.
        safe_house = house_num.replace("'", "").strip()
        safe_street = street_name.replace("'", "").strip().upper()
        params = {
            "$where": f"upper(incident_address) like '%{safe_house}%{safe_street}%'",
            "$limit":  "100",
            "$order":  "created_date DESC",
        }
    else:
        return []

    try:
        resp = await client.get(_NYC_311_ENDPOINT, params=params, timeout=20.0)
        if resp.status_code != 200:
            key = bbl or f"{house_num} {street_name}"
            logger.warning(f"311 fetch {key} returned {resp.status_code}")
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        key = bbl or f"{house_num} {street_name}"
        logger.warning(f"311 fetch {key} failed: {e}")
        return []


async def _ingest_311_for_project(project: dict, client: "httpx.AsyncClient") -> dict:
    """Fetch + upsert new 311 records for one project. Returns a small stats dict."""
    project_id = str(project.get("_id"))
    company_id = project.get("company_id", "")
    nyc_bin = (project.get("nyc_bin") or "").strip()
    # bbl-first read with nyc_bbl fallback during the step-9.1 transition window.
    bbl = (project.get("bbl") or project.get("nyc_bbl") or "").strip()
    # 311 needs BBL (dataset has no `bin` column) OR an address match.
    # Use the same address parsing the main DOB fetcher uses.
    house_num, street_name = _parse_address_components(project.get("address") or "")
    if not bbl and not (house_num and street_name):
        return {"new": 0, "actions": 0, "skipped": True}

    records = await _fetch_311_for_project(client, bbl, house_num, street_name)
    new_count = 0
    action_count = 0
    now = datetime.now(timezone.utc)

    for rec in records:
        unique_key = str(rec.get("unique_key") or "").strip()
        if not unique_key:
            continue
        raw_dob_id = f"311:{unique_key}"

        # Dedupe against prior inserts — the `raw_dob_id` unique index handles
        # collisions, but we still want to know if it existed so we don't
        # fire an alert on known records.
        existing = await db.dob_logs.find_one({"raw_dob_id": raw_dob_id})
        if existing:
            continue

        ctype = (rec.get("complaint_type") or "").strip()
        severity = _severity_for_311(ctype)

        address_parts = [
            (rec.get("incident_address") or "").strip(),
            (rec.get("city") or "").strip(),
        ]
        incident_address = ", ".join(p for p in address_parts if p)

        doc = {
            "project_id":        project_id,
            "company_id":        company_id,
            "nyc_bin":           nyc_bin,
            "record_type":       "complaint",
            "raw_dob_id":        raw_dob_id,
            "ai_summary":        _fmt_311_summary(rec),
            "severity":          severity,
            "next_action":       _next_action_for_311(rec),
            "dob_link":          (
                f"https://portal.311.nyc.gov/sr-details/?id={unique_key}"
            ),
            "detected_at":       now,
            "created_at":        now,
            "updated_at":        now,
            "is_deleted":        False,
            # 311-shaped extras — keep them on the same document so the
            # frontend timeline shows the same fields as DOB complaints.
            "complaint_number":  unique_key,
            "complaint_type":    ctype or None,
            "complaint_status":  rec.get("status") or None,
            "complaint_date":    rec.get("created_date"),
            "closed_date":       rec.get("closed_date"),
            "description":       (rec.get("descriptor") or "").strip() or None,
            "incident_address":  incident_address or None,
            "complaint_source":  "311",
            "source":            "311",   # extra tag so analytics can split 311 vs DOB
            "agency":            (rec.get("agency") or "").strip() or None,
            "agency_name":       (rec.get("agency_name") or "").strip() or None,
            "resolution_description": (rec.get("resolution_description") or "").strip() or None,
        }

        try:
            await db.dob_logs.insert_one(doc)
            new_count += 1
            if severity == "Action":
                action_count += 1
                # Fire critical alert through the throttled wrapper.
                # Initial-scan suppression here means the very first 311
                # poll for a project quietly backfills the historical
                # complaints without spamming the owner.
                await _send_critical_dob_alert_throttled(project, doc, source="311")
        except Exception as e:
            # The unique index on raw_dob_id will reject duplicates; swallow.
            msg = str(e).lower()
            if "duplicate key" in msg:
                continue
            logger.warning(
                f"311 insert failed project={project.get('name')} "
                f"unique_key={unique_key}: {e}"
            )

    # Mark the 311 initial scan done for this project so subsequent polls
    # can email when genuinely new complaints show up.
    await _mark_initial_scan_done(project_id, "311")
    return {"new": new_count, "actions": action_count, "skipped": False}


async def _poll_311_fast_complaints() -> None:
    """APScheduler job: poll 311 for every tracked BIN.

    Runs every 30 minutes. Safe to run alongside `dob_nightly_scan` — the two
    hit different datasets (erm2-nwe9 vs eabe-havv) and dedupe by a
    namespaced `raw_dob_id` (`311:<unique_key>` here, bare ID there).
    """
    started = datetime.now(timezone.utc)
    try:
        projects = await db.projects.find({
            "track_dob_status": True,
            "nyc_bin":          {"$exists": True, "$ne": ""},
            "is_deleted":       {"$ne": True},
        }).to_list(500)
    except Exception as e:
        logger.error(f"311 poll: project lookup failed: {e}")
        return

    if not projects:
        logger.info("311 poll: no tracked projects — skip")
        return

    total_new = 0
    total_action = 0
    total_processed = 0
    async with ServerHttpClient(
        headers={"User-Agent": "Levelog/1.0 (311 poller)"},
    ) as client:
        # Cap concurrency so we don't hammer the NYC Open Data endpoint.
        sem = asyncio.Semaphore(5)

        async def _one(p):
            nonlocal total_new, total_action, total_processed
            async with sem:
                try:
                    stats = await _ingest_311_for_project(p, client)
                    if not stats.get("skipped"):
                        total_processed += 1
                        total_new += stats.get("new", 0)
                        total_action += stats.get("actions", 0)
                except Exception as e:
                    logger.warning(
                        f"311 poll project={p.get('name')} failed: {e}"
                    )

        await asyncio.gather(*[_one(p) for p in projects])

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"311 poll complete: projects={total_processed} new_records={total_new} "
        f"action_alerts={total_action} elapsed={elapsed:.1f}s"
    )

 
def _classify_filing_system(job_number: Optional[str]) -> str:
    """Classify a permit as DOB_NOW vs BIS based on job number shape.

    Per NYC DOB: DOB NOW Build job filings use a letter prefix
    (B/M/Q/X/R + digits, optional -I<n> suffix), while legacy BIS
    jobs are purely numeric. Drives different auto-extension rules
    in the renewal eligibility engine (BIS = 31-day look-ahead,
    DOB NOW = end-of-day after carrier files COI update).
    """
    if not job_number:
        return "DOB_NOW"  # safe default — most new filings are DOB NOW
    s = str(job_number).strip().upper()
    if s and s[0] in ("B", "M", "Q", "X", "R"):
        return "DOB_NOW"
    if s.replace("-", "").isdigit():
        return "BIS"
    return "DOB_NOW"


# Permit classification → drives renewal strategy (LL48 sheds get a
# parallel 90-day manual track per the Jan 26 2026 service notice).
_SHED_WORK_TYPES = {"SH"}
_FENCE_WORK_TYPES = {"FN"}
_BLDRS_PAVEMENT_WORK_TYPES = {"BL"}


def _classify_permit_class(work_type: Optional[str]) -> str:
    """Map a DOB work_type code to the renewal-strategy permit_class.

    'SH' → sidewalk_shed (90-day cap, PE/RA progress report required)
    'FN' → fence
    'BL' → bldrs_pavement (a BL without an SH on the same job is its
           own permit class — different rules from sheds)
    everything else → standard
    """
    if not work_type:
        return "standard"
    wt = str(work_type).strip().upper()
    if wt in _SHED_WORK_TYPES:
        return "sidewalk_shed"
    if wt in _FENCE_WORK_TYPES:
        return "fence"
    if wt in _BLDRS_PAVEMENT_WORK_TYPES:
        return "bldrs_pavement"
    return "standard"


def _extract_permit_fields(rec: dict) -> dict:
    """Extract structured permit fields from raw DOB record.

    Also derives `filing_system` and `permit_class` so the renewal
    engine can branch without re-parsing the job number on every
    eligibility check. Both are deterministic functions of job# and
    work_type; storing them lets us index on them later.
    """
    fields = {}
    # DOB NOW permits (rbx6-tga4)
    fields["permit_type"] = rec.get("permit_type") or rec.get("permittee_s_license_type") or None
    fields["permit_subtype"] = rec.get("permit_subtype") or rec.get("work_type") or None
    fields["permit_status"] = rec.get("permit_status") or rec.get("current_status") or rec.get("status") or None
    fields["expiration_date"] = rec.get("expiration_date") or rec.get("permit_expiration_date") or rec.get("expired_date") or None
    fields["issuance_date"] = rec.get("issuance_date") or rec.get("issued_date") or rec.get("permit_si_issuance_date") or None
    fields["filing_date"] = rec.get("filing_date") or rec.get("pre_filing_date") or rec.get("latest_action_date") or None
    fields["job_number"] = rec.get("job__") or rec.get("job_filing_number") or rec.get("job_number") or None
    fields["job_type"] = rec.get("job_type") or rec.get("filing_reason") or None
    fields["work_type"] = rec.get("work_type") or rec.get("permit_type") or None
    cleaned = {k: str(v).strip() if v else None for k, v in fields.items()}
    # Derived classification — must come AFTER cleanup so we read
    # the same trimmed values the rest of the pipeline persists.
    cleaned["filing_system"] = _classify_filing_system(cleaned.get("job_number"))
    cleaned["permit_class"] = _classify_permit_class(cleaned.get("work_type"))
    return cleaned
 
 
def _classify_violation_subtype(rec: dict) -> str:
    """Classify violation into sub-type: SWO_FULL, SWO_PARTIAL, VACATE_FULL, VACATE_PARTIAL, COMM_ORDER, ECB, NOV."""
    vtype = str(rec.get("violation_type") or rec.get("violation_type_code") or "").upper()
    desc = str(rec.get("description") or rec.get("violation_description") or "").upper()
    record_type = str(rec.get("_record_type") or "").lower()
    ecb_num = rec.get("ecb_violation_number") or ""

    combined = f"{vtype} {desc}"

    if "FULL STOP WORK" in combined or (record_type == "swo" and "PARTIAL" not in combined):
        return "SWO_FULL"
    if "PARTIAL STOP" in combined or "PARTIAL SWO" in combined:
        return "SWO_PARTIAL"
    if "FULL VACATE" in combined:
        return "VACATE_FULL"
    if "PARTIAL VACATE" in combined or "VACATE" in combined:
        return "VACATE_PARTIAL"
    if "COMMISSIONER" in combined or "COMM ORDER" in combined:
        return "COMM_ORDER"
    if ecb_num or "ECB" in combined:
        return "ECB"
    return "NOV"


def _classify_resolution_state(rec: dict) -> str:
    """Derive resolution state from violation record fields."""
    cert_status = str(rec.get("certification_status") or "").upper()
    current_status = str(rec.get("current_status") or "").upper()
    category = str(rec.get("violation_category") or "").upper()
    hearing = rec.get("hearing_date_time") or rec.get("hearing_date") or ""
    disp_date = rec.get("disposition_date") or ""

    if any(w in cert_status for w in ["CERTIFIED", "CERTIFICATE", "RESOLVED"]):
        return "certified"
    if any(w in current_status for w in ["DISMISSED"]):
        return "dismissed"
    if any(w in category for w in ["DISMISSED"]):
        return "dismissed"
    if any(w in current_status for w in ["PAID", "SATISFIED"]):
        return "paid"
    if any(w in current_status for w in ["RESOLVED", "CLOSED"]):
        return "resolved"
    if "CURE" in cert_status or "CURE" in current_status:
        return "cure_pending"
    if hearing:
        try:
            from dateutil import parser as dateparser
            h_date = dateparser.parse(str(hearing))
            if h_date.tzinfo is None:
                h_date = h_date.replace(tzinfo=timezone.utc)
            if h_date > datetime.now(timezone.utc):
                return "hearing_scheduled"
            return "hearing_past"
        except Exception:
            return "hearing_scheduled"
    return "open"


def _classify_notice_type(rec: dict) -> Optional[str]:
    """Classify violation notice type from description and violation_type fields."""
    desc = str(rec.get("description") or rec.get("violation_description") or "").upper()
    vtype = str(rec.get("violation_type") or rec.get("violation_type_code") or "").upper()
    combined = f"{vtype} {desc}"

    if "COMMISSIONER" in combined and "ORDER" in combined:
        return "commissioners_order"
    if "PADLOCK" in combined:
        return "padlock_order"
    if "EMERGENCY" in combined and ("DECLARATION" in combined or "ORDER" in combined):
        return "emergency_declaration"
    if "NOTICE OF DEFICIENCY" in combined or "NOD" in combined:
        return "notice_of_deficiency"
    if "LETTER OF DEFICIENCY" in combined or "LOD" in combined:
        return "letter_of_deficiency"
    return None


def _extract_compliance_deadline(rec: dict) -> Optional[str]:
    """Attempt to extract a compliance deadline from disposition comments or description."""
    from dateutil import parser as dateparser
    import re

    text = f"{rec.get('disposition_comments', '') or ''} {rec.get('description', '') or ''}"
    # Look for patterns like "comply by MM/DD/YYYY", "deadline: MM/DD/YYYY", "within 30 days"
    date_patterns = [
        r'comply by\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        r'deadline[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})',
        r'before\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        r'by\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        r'cure by\s+(\d{1,2}/\d{1,2}/\d{2,4})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                deadline = dateparser.parse(match.group(1))
                return deadline.strftime("%Y-%m-%d")
            except Exception:
                continue
    return None


def _extract_violation_fields(rec: dict) -> dict:
    """Extract structured violation fields from raw DOB record."""
    fields = {}
    fields["violation_type"] = rec.get("violation_type") or rec.get("violation_type_code") or rec.get("severity") or None
    # Build a display-friendly violation number from whichever source
    fields["violation_number"] = rec.get("ecb_violation_number") or rec.get("violation_number") or rec.get("number") or rec.get("isn_dob_bis_viol") or None
    fields["violation_category"] = rec.get("violation_category") or rec.get("category") or None
    fields["violation_date"] = rec.get("issue_date") or rec.get("violation_date") or rec.get("issued_date") or rec.get("infraction_date") or None
    fields["description"] = rec.get("description") or rec.get("violation_description") or rec.get("infraction_codes") or None
    fields["penalty_amount"] = rec.get("penalty_applied") or rec.get("penalty_balance_due") or rec.get("amount_paid") or None
    fields["respondent"] = rec.get("respondent_name") or rec.get("respondent") or None
    fields["disposition_date"] = rec.get("disposition_date") or rec.get("hearing_date_time") or None
    fields["disposition_comments"] = rec.get("disposition_comments") or rec.get("hearing_status") or None
    fields["status"] = rec.get("violation_category") or rec.get("certification_status") or rec.get("current_status") or None
    fields["violation_subtype"] = _classify_violation_subtype(rec)
    fields["resolution_state"] = _classify_resolution_state(rec)
    fields["notice_type"] = _classify_notice_type(rec)
    fields["compliance_deadline"] = _extract_compliance_deadline(rec)
    return {k: str(v).strip() if v else None for k, v in fields.items()}


def _extract_complaint_fields(rec: dict) -> dict:
    """Extract structured complaint fields from DOB Complaints Received (eabe-havv)."""
    fields = {}
    fields["complaint_number"] = rec.get("complaint_number") or None
    fields["complaint_type"] = rec.get("complaint_category") or None
    fields["complaint_status"] = rec.get("status") or None
    fields["complaint_date"] = rec.get("date_entered") or None
    fields["closed_date"] = rec.get("disposition_date") or None
    # Build rich description from code lookups
    category = rec.get("complaint_category") or ""
    disposition_code = rec.get("disposition_code") or ""
    fields["description"] = get_category_label(category) if category else None
    fields["disposition_code"] = disposition_code or None
    # Address
    house = rec.get("house_number") or ""
    street = rec.get("house_street") or ""
    fields["incident_address"] = f"{house} {street}".strip() if (house or street) else None

    # Sprint 1: Classify complaint and persist rich data
    result = classify_complaint(rec)
    fields["risk_level"] = result.get("risk_level")
    fields["disposition_label"] = result.get("disposition_label")
    fields["category_label"] = result.get("category_label")

    # Derived: complaint_source
    cat_code = rec.get("complaint_category", "")
    if rec.get("community_board"):
        fields["complaint_source"] = "Neighbor/Community Complaint"
    elif (cat_code >= "4A" and cat_code <= "4W") or (cat_code >= "6B" and cat_code <= "7N"):
        fields["complaint_source"] = "DOB Internal Inspection"
    else:
        fields["complaint_source"] = "311 Complaint"

    # Derived: inspector_unit
    disp_code = (disposition_code or "").strip()
    import re as _re
    if _re.match(r'^(D[1-9]|E[A-D])$', disp_code):
        fields["inspector_unit"] = result.get("disposition_label")
    else:
        fields["inspector_unit"] = None

    # Derived: what_to_expect
    if _re.match(r'^A[1-9]$', disp_code):
        fields["what_to_expect"] = "Inspector will visit within 1-5 business days"
    elif _re.match(r'^D[1-9]$', disp_code):
        unit_name = result.get("disposition_label", "specialized unit")
        fields["what_to_expect"] = f"Inspector from {unit_name} will visit within 1-5 business days"
    elif _re.match(r'^I[1-5]$', disp_code):
        fields["what_to_expect"] = "Respond before hearing date — cure or pay penalty"
    elif _re.match(r'^I[6-9]$', disp_code):
        fields["what_to_expect"] = "All covered work must cease immediately"
    elif _re.match(r'^C[1-9]$', disp_code):
        fields["what_to_expect"] = "Inspector will return — ensure site is accessible"
    elif _re.match(r'^[ZR][1-9]$', disp_code):
        fields["what_to_expect"] = "No further action needed"
    elif _re.match(r'^E[A-D]$', disp_code):
        fields["what_to_expect"] = "Inspector will visit within 1-5 business days"
    else:
        fields["what_to_expect"] = "Review complaint status on DOB BIS"

    return {k: str(v).strip() if v else None for k, v in fields.items()}


# DOB inspection job_id prefix → human-readable work category.
# The p937-wjvj dataset's `inspection_type` is phase-only (Initial / Re-inspection),
# the actual work category is encoded in the job_id letter prefix.
DOB_JOB_PREFIX_CATEGORY = {
    "PC": "Plumbing",
    "PL": "Plumbing",
    "EL": "Electrical",
    "ME": "Mechanical",
    "SP": "Sprinkler",
    "SD": "Standpipe",
    "EA": "Elevator",
    "EW": "Earthwork",
    "FS": "Fuel Storage",
    "FB": "Fuel Burning",
    "BL": "Boiler",
    "OT": "Other / General Construction",
    "CC": "Curb Cut",
    "SG": "Sign",
    "FA": "Fire Alarm",
    "FP": "Fire Suppression",
    "AN": "Antenna",
    "SF": "Scaffold",
    "SH": "Sidewalk Shed",
    "FN": "Fence",
    "DM": "Demolition",
    "EQ": "Construction Equipment",
    "CH": "Chute",
    "NB": "New Building",
    "A1": "Alteration Type 1",
    "A2": "Alteration Type 2",
    "A3": "Alteration Type 3",
}


def _base_job_number(job_id: str) -> str:
    """Strip DOB filing sequence suffix so renewals collapse to one
    permit. 'B00834550-I1' → 'B00834550'. 'B00834550-I2' → 'B00834550'.
    Legacy numeric BIS jobs (e.g. '101220923') pass through unchanged.

    DOB NOW issues a fresh `job_filing_number` for every renewal of the
    same underlying permit. Without this collapse, the UI shows every
    historical filing — including long-expired ones that have already
    been renewed — as if they were separate live permits.
    """
    if not job_id:
        return ""
    import re as _re
    s = str(job_id).strip().upper()
    # DOB NOW: letter + digits, optional -I<digits> suffix
    m = _re.match(r'^([A-Z]\d+)(?:-[A-Z]\d+)?$', s)
    if m:
        return m.group(1)
    # BIS legacy: leading run of digits (strip any trailing letters)
    m = _re.match(r'^(\d+)', s)
    if m:
        return m.group(1)
    return s


def _decode_job_prefix(job_id: str) -> str:
    """Return a human-readable work category for a DOB job_id prefix, or ''."""
    if not job_id:
        return ""
    s = str(job_id).strip().upper()
    # DOB-NOW jobs often look like B00714447-I1 or M01234567-PC1 — category may
    # follow the dash. Try both positions.
    import re as _re
    m = _re.search(r'-([A-Z]{2})\d*$', s)
    if m and m.group(1) in DOB_JOB_PREFIX_CATEGORY:
        return DOB_JOB_PREFIX_CATEGORY[m.group(1)]
    # Leading two letters (legacy BIS jobs like PC6530234)
    if len(s) >= 2 and s[:2] in DOB_JOB_PREFIX_CATEGORY:
        return DOB_JOB_PREFIX_CATEGORY[s[:2]]
    return ""


def _extract_inspection_fields(rec: dict) -> dict:
    """Extract structured inspection fields from DOB Inspections dataset (p937-wjvj).

    The dataset's `inspection_type` is phase-only ("Initial" / "Re-inspection").
    We enrich it with the work category decoded from the job_id prefix so the
    UI shows "Plumbing — Initial" instead of just "Initial".
    """
    fields = {}
    fields["inspection_date"] = rec.get("inspection_date") or rec.get("approved_date") or None

    raw_phase = rec.get("inspection_type") or rec.get("inspection_category") or rec.get("job_progress") or None
    job_id = rec.get("job_id") or rec.get("job_filing_number") or rec.get("job_number") or rec.get("job__") or None
    category = _decode_job_prefix(str(job_id or ""))

    # Compose a richer inspection_type string when we can.
    if raw_phase and category:
        composed = f"{category} — {str(raw_phase).strip()}"
    elif category:
        composed = f"{category} Inspection"
    else:
        composed = raw_phase
    fields["inspection_type"] = composed
    fields["inspection_category"] = category or None
    fields["inspection_phase"] = str(raw_phase).strip() if raw_phase else None

    fields["inspection_result"] = rec.get("result") or rec.get("inspection_result") or None
    fields["inspection_result_description"] = rec.get("result_description") or rec.get("comments") or None
    fields["linked_job_number"] = job_id
    return {k: str(v).strip() if v else None for k, v in fields.items()}


def _determine_severity(rec: dict, record_type: str) -> str:
    """Determine severity: 'Action' (needs attention) or 'Good' (no action needed)."""
    if record_type == "permit":
        exp = rec.get("expiration_date") or rec.get("permit_expiration_date") or rec.get("expired_date") or ""
        if exp:
            try:
                from dateutil import parser as dateparser
                exp_date = dateparser.parse(str(exp))
                if exp_date.tzinfo is None:
                    exp_date = exp_date.replace(tzinfo=timezone.utc)
                days_left = (exp_date - datetime.now(timezone.utc)).days
                if days_left <= 30:
                    return "Action"
            except Exception:
                pass
        status = str(rec.get("permit_status") or rec.get("current_status") or "").lower()
        if "expired" in status or "revoked" in status:
            return "Action"
        return "Good"

    if record_type in ("violation", "swo"):
        # Check if dismissed/resolved — should be filtered out, but just in case
        cat = str(rec.get("violation_category", "") or "").upper()
        status = str(rec.get("certification_status", "") or rec.get("current_status", "") or "").upper()
        if any(word in cat for word in ["DISMISSED", "RESOLVED"]):
            return "Good"
        if any(word in status for word in ["RESOLVED", "DISMISSED", "CLOSED", "CERTIFIED"]):
            return "Good"
        return "Action"

    if record_type == "inspection":
        result = str(rec.get("result") or rec.get("inspection_result") or "").upper()
        if "FAIL" in result:
            return "Action"
        return "Good"

    if record_type == "complaint":
        result = classify_complaint(rec)
        return result["severity"]
    return "Good"
 
 
def _generate_summary(rec: dict, record_type: str) -> str:
    """Generate a human-readable summary from raw fields without AI."""
    if record_type == "permit":
        job = rec.get("job__") or rec.get("job_filing_number") or "Unknown"
        ptype = rec.get("work_type") or rec.get("permit_type") or rec.get("filing_reason") or "General"
        status = rec.get("permit_status") or rec.get("current_status") or "Unknown"
        exp = rec.get("expiration_date") or rec.get("permit_expiration_date") or rec.get("expired_date") or ""
        summary = f"Permit {job} ({ptype}) — Status: {status}"
        if exp:
            summary += f" — Expires: {str(exp)[:10]}"
        return summary
 
    if record_type in ("violation", "swo"):
        vnum = rec.get("violation_number") or rec.get("number") or rec.get("ecb_violation_number") or "Unknown"
        vtype = rec.get("violation_type") or rec.get("violation_type_code") or rec.get("severity") or ""
        desc = rec.get("description") or rec.get("violation_description") or rec.get("infraction_codes") or ""
        if desc and len(str(desc)) > 120:
            desc = str(desc)[:117] + "..."
        return f"Violation {vnum}: {vtype}. {desc}".strip()
 
    if record_type == "complaint":
        comp_num = rec.get("complaint_number") or ""
        result = classify_complaint(rec)
        CATEGORY_DESCRIPTIONS = {
            "01": "illegal work or work without a permit",
            "03": "failure to maintain building facade",
            "05": "work contrary to approved plans",
            "06": "unsafe construction condition",
            "09": "illegal conversion or occupancy",
            "12": "failure to maintain elevator",
            "14": "demolition without permit",
            "23": "working without a safety net",
            "28": "illegal curb cut or sidewalk damage",
            "30": "debris falling from building",
            "45": "unsafe scaffolding or sidewalk shed",
            "49": "construction noise outside allowed hours",
            "59": "work without required DOB inspection",
            "63": "illegal fence or retaining wall",
            "71": "crane or derrick safety violation",
            "83": "failure to safeguard persons or property",
            "91": "building under construction in unsafe condition",
        }
        cat_code = rec.get("complaint_category", "")
        desc = CATEGORY_DESCRIPTIONS.get(cat_code, result['category_label'])
        summary = f"Complaint about {desc.lower()}. {result['disposition_label']}."
        if comp_num:
            summary = f"#{comp_num}: {summary}"
        return summary
 
    if record_type == "inspection":
        phase = rec.get("inspection_type") or rec.get("job_progress") or ""
        job = rec.get("job_id") or rec.get("job_filing_number") or rec.get("job_number") or ""
        category = _decode_job_prefix(str(job))
        result = rec.get("result") or rec.get("inspection_result") or "Pending"
        if category and phase:
            label = f"{category} — {phase} Inspection"
        elif category:
            label = f"{category} Inspection"
        elif phase:
            label = f"{phase} Inspection"
        else:
            label = "Inspection"
        job_str = f" (Job {job})" if job else ""
        return f"{label}{job_str} — Result: {result}"

    if record_type == "job_status":
        job = rec.get("job__") or "Unknown"
        jtype = rec.get("job_type") or ""
        desc = rec.get("job_description") or rec.get("job_s1_special_place_name") or ""
        if desc and len(str(desc)) > 100:
            desc = str(desc)[:97] + "..."
        return f"Job {job} ({jtype}): {desc}".strip()
 
    return f"DOB record detected"
 
 
def _generate_next_action(rec: dict, record_type: str, severity: str) -> str:
    """Generate next action from raw fields."""
    if record_type == "permit":
        status = str(rec.get("permit_status") or rec.get("current_status") or "").lower()
        if "expired" in status:
            return "URGENT: Permit has expired. File renewal application on DOB NOW immediately."
        if severity == "Action":
            exp = rec.get("expiration_date") or rec.get("permit_expiration_date") or rec.get("expired_date") or ""
            return f"Permit expiring {str(exp)[:10]}. Contact expediter to file renewal on DOB NOW before expiration."
        return "Permit is active and current. No action needed."

    if record_type in ("violation", "swo"):
        vtype = str(rec.get("violation_type", "") or rec.get("violation_type_code", "")).lower()
        if "stop work" in vtype or "swo" in vtype:
            return "STOP ALL WORK. Contact DOB and your attorney immediately to resolve SWO."
        if severity == "Action":
            return "Active violation. Contact your expediter and schedule correction with DOB."
        return "Violation resolved. No action needed."

    if record_type == "inspection":
        result = str(rec.get("result") or rec.get("inspection_result") or "").upper()
        if "FAIL" in result:
            return "Failed inspection. Review deficiencies and schedule re-inspection on DOB NOW."
        if "PARTIAL" in result:
            return "Partial pass. Address noted deficiencies and request follow-up inspection."
        return "Inspection passed. No action needed."

    if record_type == "complaint":
        result = classify_complaint(rec)
        return result["action"]

    return "Review record details on DOB BIS/NOW portal."
 
 
def _is_dob_now_job(job_num: str) -> bool:
    """True iff the job number's leading non-digit is a letter — DOB NOW
    job numbers start with a borough letter (B, M, Q, X, R, etc.).
    Purely numeric ids are BIS legacy. Empty → False.
    """
    s = str(job_num or "").strip()
    if not s:
        return False
    return s[0].isalpha()


def _bis_bin_overview_url(bin_val: str) -> str:
    """BIS Overview By BIN — the safe BIN-scoped fallback."""
    if not bin_val:
        return ""
    return (
        "https://a810-bisweb.nyc.gov/bisweb/OverviewByBinServlet"
        f"?requestid=2&allbin={quote_plus(str(bin_val))}"
        "&allinquirytype=BXS3OCV4"
    )


def _open_data_filtered_url(dataset_id: str, column: str, value: str) -> str:
    """Build an Open Data filtered-view URL. This is the only public
    URL-param-respecting surface for DOB NOW specific records — the
    DOB NOW Public Portal is a client-side SPA whose deep-links the
    server doesn't honor, and the BIS `JobsQueryByNumberServlet`
    returns 'not found' for B-prefix jobs because DOB NOW jobs don't
    exist in BIS.
    """
    if not (dataset_id and column and value):
        return ""
    return (
        f"https://data.cityofnewyork.us/resource/{dataset_id}.html"
        f"?{quote_plus(column)}={quote_plus(str(value))}"
    )


def _build_dob_link(rec: dict, record_type: str) -> str:
    """Build a public URL that actually resolves to the record.

    Routing, by record type:
      - permit / job_status
          DOB NOW job (borough-letter prefix) → Open Data w9ak-ipjd
            filtered by job_filing_number
          BIS legacy (numeric) → JobsQueryByNumberServlet with the
            record's real doc number, zero-padded to 2 digits
          No job → BIS OverviewByBin
      - inspection
          DOB NOW job → Open Data p937-wjvj filtered by job_id
          Legacy numeric → JobsQueryByNumberServlet, doc 01
          No job → BIS OverviewByBin
      - violation / swo
          ecb_violation_number → ECBQueryByNumberServlet
          isn + bin + number → ActionViolationDisplayServlet
          Else → BIS OverviewByBin
      - complaint
          BIS has no complaint-number deep-link — fall back to the
          complaints-by-BIN list view (unchanged).
      - Fallback → PropertyProfileOverviewServlet by BIN

    DOB NOW jobs must NOT be routed to BIS `JobsQueryByNumberServlet` —
    per nyc.gov, "Jobs filed in DOB NOW: Build will not appear in BIS,"
    which is the regression we're fixing.
    """
    bin_val = str(rec.get("bin") or rec.get("bin__") or "").strip()
    job_num = str(
        rec.get("job__")
        or rec.get("job_filing_number")
        or rec.get("job_number")
        or ""
    ).strip()
    isn_val = str(rec.get("isn_dob_bis_viol") or rec.get("isn") or "").strip()
    ecb_num = str(rec.get("ecb_violation_number") or "").strip()

    dob_now = _is_dob_now_job(job_num)

    # ── SWO: straight to the complaints-by-BIN list view ──────────────
    if record_type == "swo":
        if bin_val:
            return (
                "https://a810-bisweb.nyc.gov/bisweb/ComplaintsByAddressServlet"
                f"?requestid=2&allbin={quote_plus(bin_val)}&fillerdata=A"
            )
        return ""

    # ── Violations ───────────────────────────────────────────────────
    if record_type == "violation":
        if ecb_num:
            # ECB/OATH — this one has always worked.
            return (
                "https://a810-bisweb.nyc.gov/bisweb/ECBQueryByNumberServlet"
                f"?requestid=2&ecbin={quote_plus(ecb_num)}"
            )
        # 3h2n-5cm9 rows carry both `isn_dob_bis_viol` and `number`.
        # Together with the BIN those are the keys BIS's
        # ActionViolationDisplayServlet actually wants. Old code fed
        # the ISN into `vlcompdetlkey` (a different identifier from a
        # different servlet) and got "ALL KEYS CANNOT BE BLANK".
        viol_num = str(rec.get("number") or rec.get("violation_number") or "").strip()
        if isn_val and bin_val and viol_num:
            return (
                "https://a810-bisweb.nyc.gov/bisweb/ActionViolationDisplayServlet"
                f"?requestid=2&allbin={quote_plus(bin_val)}"
                "&allinquirytype=BXS3OCV4"
                f"&allisn={quote_plus(isn_val)}"
                f"&ppremise60={quote_plus(viol_num)}"
            )
        # Fallback: BIN-scoped overview.
        return _bis_bin_overview_url(bin_val)

    # ── Complaints: no public deep-link exists; BIN list view. ────────
    if record_type == "complaint":
        if bin_val:
            return (
                "https://a810-bisweb.nyc.gov/bisweb/ComplaintsByAddressServlet"
                f"?requestid=1&allbin={quote_plus(bin_val)}"
            )
        return ""

    # ── Permits / job status ─────────────────────────────────────────
    if record_type in ("permit", "job_status"):
        if dob_now and job_num:
            # DOB NOW jobs are not in BIS. Route to Open Data's
            # filtered view on the Approved Permits dataset so the
            # user lands on the exact row. Strip the filing suffix:
            # w9ak-ipjd holds one row per filing, but the filter
            # param is job_filing_number (full id including -I<n>),
            # so we pass the full id through after trimming.
            return _open_data_filtered_url(
                "w9ak-ipjd", "job_filing_number", job_num
            )
        if job_num:
            # BIS legacy numeric — JobsQueryByNumberServlet with the
            # record's doc number. BIS returns "{JOB} 01 NOT FOUND"
            # when doc 02/03/... was filed but we asked for 01, so
            # pull the real doc from the record and only default to
            # 01 when absent.
            doc_num = str(
                rec.get("doc__")
                or rec.get("doc_number")
                or rec.get("docnum")
                or "01"
            ).strip().zfill(2)
            base_job = _base_job_number(job_num)
            return (
                "https://a810-bisweb.nyc.gov/bisweb/JobsQueryByNumberServlet"
                f"?passjobnumber={quote_plus(base_job)}"
                f"&passdocnumber={quote_plus(doc_num)}&requestid=1"
            )
        return _bis_bin_overview_url(bin_val)

    # ── Inspections ──────────────────────────────────────────────────
    if record_type == "inspection":
        insp_job = str(
            rec.get("job_id")
            or rec.get("job_filing_number")
            or rec.get("job_number")
            or rec.get("job__")
            or ""
        ).strip()
        if _is_dob_now_job(insp_job):
            return _open_data_filtered_url(
                "p937-wjvj", "job_id", insp_job
            )
        if insp_job:
            base_job = _base_job_number(insp_job)
            return (
                "https://a810-bisweb.nyc.gov/bisweb/JobsQueryByNumberServlet"
                f"?passjobnumber={quote_plus(base_job)}"
                "&passdocnumber=01&requestid=1"
            )
        return _bis_bin_overview_url(bin_val)

    # ── Final fallback: property profile by BIN. ─────────────────────
    if bin_val:
        return (
            "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"
            f"?bin={quote_plus(bin_val)}"
        )
    return ""


async def run_dob_sync_for_project(project: dict) -> list:
    """Core sync logic: fetch, dedupe, extract fields, save, alert. Used by cron + manual.

    BIN auto-heal: if the project has no stored BIN (or a placeholder
    like 2000000) and the first address-based pass returns ANY record
    with a real BIN in its `bin` field, we backfill that BIN to the
    project AND re-run the queries with the real BIN. This is the
    auto-reverse-lookup path — lets us find complete records across
    all four DOB datasets (some of which are BIN-only, no address
    variant) when GeoSearch alone couldn't resolve the BIN.
    """
    project_id = str(project["_id"])
    company_id = project.get("company_id", "")
    nyc_bin = (project.get("nyc_bin") or "").strip()
    project_address = project.get("address", "")

    if not nyc_bin and not project_address:
        return []

    raw_records = await _query_dob_apis(nyc_bin, project_address)

    # --- BIN auto-heal ---
    # Scan returned records for a real BIN. DOB's datasets expose the
    # BIN on every record. If the project has no real BIN stored, pull
    # the most-common real BIN from returned records and re-query with
    # that so BIN-only endpoints (inspections, BIS legacy permits) also
    # surface records.
    should_heal = (not nyc_bin) or _is_placeholder_bin(nyc_bin)
    if should_heal and raw_records:
        bin_votes: Dict[str, int] = {}
        for rec in raw_records:
            # DOB datasets use various field names for BIN: bin, bin__
            candidate = str(
                rec.get("bin") or rec.get("bin__") or ""
            ).strip()
            if candidate and not _is_placeholder_bin(candidate):
                bin_votes[candidate] = bin_votes.get(candidate, 0) + 1

        if bin_votes:
            healed_bin = max(bin_votes, key=bin_votes.get)
            logger.info(
                f"DOB BIN auto-heal for project {project_id}: "
                f"stored={nyc_bin!r} → healed={healed_bin} "
                f"(votes={bin_votes})"
            )
            # Backfill on the project document so future syncs skip
            # the address fallback entirely and hit BIN-only endpoints.
            try:
                await db.projects.update_one(
                    {"_id": to_query_id(project_id)},
                    {"$set": {
                        "nyc_bin": healed_bin,
                        "track_dob_status": True,
                        "updated_at": datetime.now(timezone.utc),
                    }},
                )
            except Exception as e:
                logger.warning(f"BIN backfill write failed: {e}")
            # Re-query with the real BIN and merge (dedup by record id).
            nyc_bin = healed_bin
            heal_records = await _query_dob_apis(healed_bin, project_address)
            if heal_records:
                seen_keys = set()
                merged = []
                for rec in raw_records + heal_records:
                    key = (
                        rec.get("_record_type", ""),
                        rec.get("_id_field", ""),
                        str(rec.get(rec.get("_id_field", "unique_key"), "")),
                    )
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    merged.append(rec)
                raw_records = merged
                logger.info(
                    f"DOB BIN auto-heal merged {len(heal_records)} "
                    f"BIN-query records (total after dedup: {len(raw_records)})"
                )

    if not raw_records:
        return []
 
    # One-time cleanup of legacy-format permit rows. Before the
    # renewal-collapse fix, permits were keyed by per-filing
    # job_filing_number (e.g. "B00834550-I1:FE"), so a renewed permit
    # left behind its expired predecessor as a phantom row. New code
    # keys permits as "permit:BASE_JOB:WORK_TYPE" — any permit row in
    # this project that doesn't match that prefix is a stale legacy
    # entry. Only run the purge when we successfully fetched fresh
    # permit data, so an upstream DOB API outage doesn't wipe good
    # cached state.
    if any(r.get("_record_type") == "permit" for r in raw_records):
        try:
            purged = await db.dob_logs.delete_many({
                "project_id": project_id,
                "record_type": "permit",
                "raw_dob_id": {"$not": {"$regex": "^permit:"}},
            })
            if purged.deleted_count:
                logger.info(
                    f"DOB sync for project {project_id}: purged "
                    f"{purged.deleted_count} legacy-format permit rows"
                )
        except Exception as e:
            logger.warning(f"Legacy permit purge failed for project {project_id}: {e}")

    existing_ids = set()
    existing_cursor = db.dob_logs.find({"project_id": project_id}, {"raw_dob_id": 1})
    async for doc in existing_cursor:
        existing_ids.add(doc.get("raw_dob_id"))
 
    new_records = []
    for rec in raw_records:
        id_field = rec.get("_id_field", "unique_key")
        raw_id = str(rec.get(id_field, ""))
        if not raw_id:
            continue
        # Permits: use the collapsed (base_job, work_type) key stamped
        # during the fetch phase so renewals update the existing row
        # rather than creating a new one. Without this, every renewal
        # gets a fresh job_filing_number and leaks an expired
        # "ghost" permit into the logs.
        if rec.get("_record_type") == "permit":
            collapsed = rec.get("_collapsed_permit_id")
            if collapsed:
                raw_id = f"permit:{collapsed}"
            else:
                work_suffix = rec.get("work_type") or rec.get("permit_type") or rec.get("permit_sequence__") or ""
                raw_id = f"{raw_id}:{work_suffix}" if work_suffix else raw_id
        # NOTE: we don't skip on existing_ids for permits here — the
        # update path below refreshes status/expiration from the newest
        # filing. Only skip for non-permit types where the record is
        # immutable.
        if rec.get("_record_type") != "permit" and raw_id in existing_ids:
            continue
        new_records.append((raw_id, rec))
 
    if not new_records:
        logger.info(f"DOB sync for project {project_id}: no new records")
        return []
 
    inserted_logs = []
    now = datetime.now(timezone.utc)
 
    for raw_id, rec in new_records:
        try:
            record_type = rec.get("_record_type", "unknown")
            # raw_id already has work-type suffix applied during dedup phase above
            severity = _determine_severity(rec, record_type)
            summary = _generate_summary(rec, record_type)
            next_action = _generate_next_action(rec, record_type, severity)
            dob_link = _build_dob_link(rec, record_type)

            # Extract structured fields based on record type
            extra_fields = {}
            if record_type == "permit":
                extra_fields = _extract_permit_fields(rec)
            elif record_type in ("violation", "swo"):
                extra_fields = _extract_violation_fields(rec)
            elif record_type == "complaint":
                extra_fields = _extract_complaint_fields(rec)
            elif record_type == "inspection":
                extra_fields = _extract_inspection_fields(rec)

            dob_log = {
                "project_id": project_id,
                "company_id": company_id,
                "nyc_bin": nyc_bin,
                "record_type": record_type,
                "raw_dob_id": raw_id,
                "ai_summary": summary,
                "severity": severity,
                "next_action": next_action,
                "dob_link": dob_link,
                "detected_at": now,
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
                **extra_fields,
            }

            existing = await db.dob_logs.find_one({"raw_dob_id": raw_id})
            if existing:
                # Update mutable fields — status, severity, expiration, summary
                update_fields = {
                    "severity": dob_log["severity"],
                    "next_action": dob_log["next_action"],
                    "ai_summary": dob_log["ai_summary"],
                    "dob_link": dob_log["dob_link"],
                    "updated_at": now,
                    **extra_fields,
                }
                await db.dob_logs.update_one(
                    {"raw_dob_id": raw_id},
                    {"$set": update_fields},
                )
                dob_log["id"] = str(existing["_id"])
                # Only alert if severity escalated to Action — and route
                # through the throttled wrapper so initial-scan
                # suppression + 24h dedupe apply.
                old_severity = existing.get("severity", "")
                if severity == "Action" and old_severity != "Action":
                    await _send_critical_dob_alert_throttled(project, dob_log, source="dob")
            else:
                result = await db.dob_logs.insert_one(dob_log)
                dob_log["id"] = str(result.inserted_id)
                inserted_logs.append(dob_log)
                if severity == "Action":
                    await _send_critical_dob_alert_throttled(project, dob_log, source="dob")
        except Exception as e:
            logger.error(f"Failed to process dob_log for raw_id={raw_id} type={rec.get('_record_type')}: {e}", exc_info=True)
 
    # Sprint 1: Cross-reference complaints to violations
    try:
        from dateutil import parser as dateparser
        from datetime import timedelta
        complaints = await db.dob_logs.find({
            "project_id": project_id,
            "record_type": "complaint",
            "complaint_date": {"$ne": None},
        }).to_list(length=5000)
        violations = await db.dob_logs.find({
            "project_id": project_id,
            "record_type": "violation",
            "violation_date": {"$ne": None},
        }).to_list(length=5000)
        for comp in complaints:
            try:
                comp_date = dateparser.parse(comp["complaint_date"])
                comp_bin = comp.get("nyc_bin") or ""
                for viol in violations:
                    try:
                        viol_date = dateparser.parse(viol["violation_date"])
                        viol_bin = viol.get("nyc_bin") or ""
                        if comp_bin and comp_bin == viol_bin and timedelta(0) <= (viol_date - comp_date) <= timedelta(days=30):
                            await db.dob_logs.update_one(
                                {"_id": comp["_id"]},
                                {"$set": {"linked_violation_id": str(viol["_id"])}}
                            )
                            await db.dob_logs.update_one(
                                {"_id": viol["_id"]},
                                {"$addToSet": {"linked_complaint_ids": str(comp["_id"])}}
                            )
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Complaint-to-violation cross-referencing failed for project {project_id}: {e}")

    logger.info(
        f"DOB sync for project {project_id}: {len(inserted_logs)} new records "
        f"({sum(1 for l in inserted_logs if l.get('severity') == 'Critical')} critical)"
    )
    # Mark the initial DOB scan done for this project so subsequent scans
    # can send email alerts. The first scan of a newly-tracked project
    # pulls in the entire historical backlog — silent during that run.
    await _mark_initial_scan_done(project_id, "dob")
    return inserted_logs
 
 
async def nightly_compliance_check():
    """Nightly check: missing logbooks, missing SSP for major projects, expiring safety staff licenses."""
    try:
        logger.info("🔍 Nightly compliance check starting...")
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        projects = await db.projects.find({
            "status": "active", "is_deleted": {"$ne": True}
        }).to_list(500)

        for project in projects:
            pid = str(project["_id"])
            pname = project.get("name", "Unknown")
            pclass = project.get("project_class", "regular")
            company_id = project.get("company_id")

            # 1. Check for missing required daily logbooks (only if workers were on site today)
            today_start, today_end = get_today_range_est()
            checkin_count = await db.checkins.count_documents({
                "project_id": pid,
                "check_in_time": {"$gte": today_start, "$lt": today_end},
                "is_deleted": {"$ne": True},
            })

            if checkin_count > 0:
                required = project.get("required_logbooks") or get_required_logbooks(pclass, project)
                daily_required = [r for r in required if r not in ("subcontractor_orientation", "toolbox_talk")]

                for log_type in daily_required:
                    existing = await db.logbooks.find_one({
                        "project_id": pid, "log_type": log_type, "date": today,
                        "status": "submitted", "is_deleted": {"$ne": True},
                    })
                    if not existing:
                        # Check if alert already exists for today
                        existing_alert = await db.compliance_alerts.find_one({
                            "alert_type": "missing_logbook", "project_id": pid,
                            "details.log_type": log_type, "details.date": today,
                        })
                        if not existing_alert:
                            severity = "high" if log_type == "ssc_daily_safety_log" else "medium"
                            await db.compliance_alerts.insert_one({
                                "alert_type": "missing_logbook",
                                "severity": severity,
                                "project_id": pid,
                                "project_name": pname,
                                "message": f"Required {log_type.replace('_', ' ').title()} not submitted for {pname} on {today}",
                                "resolved": False,
                                "created_at": now,
                                "company_id": company_id,
                                "details": {"log_type": log_type, "date": today},
                            })

            # 2. Missing SSP for major projects
            if pclass in ("major_a", "major_b") and not project.get("ssp_number"):
                existing_alert = await db.compliance_alerts.find_one({
                    "alert_type": "missing_ssp", "project_id": pid, "resolved": False,
                })
                if not existing_alert:
                    await db.compliance_alerts.insert_one({
                        "alert_type": "missing_ssp",
                        "severity": "critical",
                        "project_id": pid,
                        "project_name": pname,
                        "message": f"Major project {pname} has no Site Safety Plan (SSP) filed with DOB",
                        "resolved": False,
                        "created_at": now,
                        "company_id": company_id,
                    })

            # 3. SSP expiration warning (within 30 days)
            ssp_exp = project.get("ssp_expiration_date")
            if ssp_exp:
                try:
                    exp_date = datetime.strptime(ssp_exp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    days_until = (exp_date - now).days
                    if 0 < days_until <= 30:
                        existing_alert = await db.compliance_alerts.find_one({
                            "alert_type": "ssp_expiring", "project_id": pid, "resolved": False,
                        })
                        if not existing_alert:
                            await db.compliance_alerts.insert_one({
                                "alert_type": "ssp_expiring",
                                "severity": "high",
                                "project_id": pid,
                                "project_name": pname,
                                "message": f"SSP for {pname} expires in {days_until} days ({ssp_exp})",
                                "resolved": False,
                                "created_at": now,
                                "company_id": company_id,
                            })
                except Exception:
                    pass

        # 4. Expiring safety staff licenses (within 30 days)
        all_staff = await db.safety_staff_registrations.find({
            "is_deleted": {"$ne": True}
        }).to_list(500)

        for staff in all_staff:
            exp = staff.get("license_expiration")
            if exp:
                try:
                    exp_date = datetime.strptime(exp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    days_until = (exp_date - now).days
                    if 0 < days_until <= 30:
                        sid = str(staff["_id"])
                        existing_alert = await db.compliance_alerts.find_one({
                            "alert_type": "staff_license_expiring",
                            "details.staff_id": sid, "resolved": False,
                        })
                        if not existing_alert:
                            await db.compliance_alerts.insert_one({
                                "alert_type": "staff_license_expiring",
                                "severity": "high",
                                "project_id": staff.get("project_id"),
                                "message": f"{staff.get('role', '').upper()} {staff.get('name')}'s license ({staff.get('license_number')}) expires in {days_until} days",
                                "resolved": False,
                                "created_at": now,
                                "company_id": staff.get("company_id"),
                                "details": {"staff_id": sid, "license_expiration": exp},
                            })
                except Exception:
                    pass

        logger.info("🔍 Nightly compliance check completed")
    except Exception as e:
        logger.error(f"Nightly compliance check error: {e}")

async def nightly_dob_scan():
    """Cron job: runs daily at 04:00 AM EST."""
    logger.info("🏗️ DOB nightly scan starting...")
 
    projects = await db.projects.find({
        "track_dob_status": True,
        "$or": [
            {"nyc_bin": {"$ne": None, "$exists": True}},
            {"address": {"$ne": None, "$ne": "", "$exists": True}},
        ],
        "is_deleted": {"$ne": True},
    }).to_list(500)
 
    if not projects:
        logger.info("DOB nightly scan: no tracked projects")
        return
 
    total_new = 0
    for project in projects:
        try:
            new_logs = await run_dob_sync_for_project(project)
            total_new += len(new_logs)
        except Exception as e:
            logger.error(f"DOB scan error for project {project.get('name')}: {e}")
 
    logger.info(f"🏗️ DOB nightly scan complete: {len(projects)} projects scanned, {total_new} new records")
    # Check for expiring permits across all projects
    await check_permit_expirations()
    await nightly_renewal_scan(db)

async def renewal_digest_daily_cron():
    """Daily 7am-ET digest run.

    For each non-deleted company:
      1. Pull permits + project denorm.
      2. compute_company_alerts() → list of alerts that crossed today.
      3. Idempotency check — alerts already sent today are skipped.
      4. If any new alerts: build HTML, resolve recipients, send via
         Resend, log success per-alert into renewal_alert_sent.

    Recipients per spec §4.1:
      - Company admins with notifications_enabled != False (default ON)
      - Non-admin PMs with renewal_digest_opt_in == True (default OFF)
      - Optional shared mailbox alias on companies.renewal_digest_alias_email
    """
    from lib.renewal_digest import (
        compute_company_alerts,
        digest_html,
        digest_subject,
        AlertKind,
    )

    started = datetime.now(timezone.utc)
    today = started

    companies = await db.companies.find({"is_deleted": {"$ne": True}}).to_list(500)
    sent_count = 0
    skipped_company_count = 0

    for company in companies:
        company_id = str(company["_id"])

        # Pull permits across all this company's tracked projects.
        # Denormalize project name so the email can render the right
        # project per permit.
        projects = await db.projects.find(
            {"company_id": company_id, "is_deleted": {"$ne": True}},
            {"_id": 1, "name": 1, "track_dob_status": 1},
        ).to_list(500)
        project_id_to_name = {str(p["_id"]): p.get("name", "") for p in projects}
        if not projects:
            permits = []
        else:
            permits = await db.dob_logs.find({
                "project_id": {"$in": list(project_id_to_name.keys())},
                "record_type": "permit",
                "is_deleted": {"$ne": True},
            }, {
                "_id": 1, "project_id": 1, "job_number": 1,
                "issuance_date": 1, "permit_class": 1, "filing_system": 1,
            }).to_list(2000)
            for p in permits:
                p["project_name"] = project_id_to_name.get(p.get("project_id"), "")

        alerts = compute_company_alerts(
            company=company, permits=permits, today=today,
        )
        if not alerts:
            skipped_company_count += 1
            continue

        # Idempotency: filter alerts already sent today.
        new_alerts = []
        for a in alerts:
            key = a.idempotency_key()
            key["sent_date"] = today.date().isoformat()
            existing = await db.renewal_alert_sent.find_one(key)
            if existing:
                continue
            new_alerts.append((a, key))

        if not new_alerts:
            skipped_company_count += 1
            continue

        # Resolve recipients.
        recipients = await _resolve_renewal_digest_recipients(company)
        if not recipients:
            logger.info(
                f"[renewal_digest] company={company_id} has "
                f"{len(new_alerts)} new alerts but zero opted-in recipients; "
                f"skipping send (alerts will retry tomorrow)."
            )
            continue

        subject = digest_subject([a for a, _ in new_alerts], company.get("name") or "")
        html = digest_html([a for a, _ in new_alerts], company.get("name") or "")

        # Send via Resend (or no-op if env unset).
        try:
            await _send_renewal_digest_email(recipients, subject, html)
        except Exception as e:
            logger.error(
                f"[renewal_digest] send failed for company={company_id}: {e!r}"
            )
            continue  # don't mark idempotency on send failure

        # Mark idempotency: insert a row per alert.
        for _, key in new_alerts:
            try:
                await db.renewal_alert_sent.insert_one({
                    **key,
                    "sent_at": started,
                    "recipients": recipients,
                })
                sent_count += 1
            except Exception as e:
                # Unique-index collision (concurrent cron) is benign.
                logger.debug(f"[renewal_digest] idempotency insert: {e!r}")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"📧 renewal digest cron complete: "
        f"alerts_sent={sent_count} companies_skipped={skipped_company_count} "
        f"elapsed={elapsed:.1f}s"
    )


async def _resolve_renewal_digest_recipients(company: dict) -> list:
    """Per spec §4.1:
      - admins of this company: opt-OUT (default ON, suppressed if
        user.renewal_digest_opt_out == True)
      - non-admin PMs: opt-IN (default OFF, included only if
        user.renewal_digest_opt_in == True)
      - optional shared alias on companies.renewal_digest_alias_email
    Returns deduplicated list of email addresses.
    """
    company_id = str(company["_id"])
    emails: list = []

    # Admins: default ON, opt-out via user flag.
    admin_cursor = db.users.find({
        "company_id": company_id,
        "role": "admin",
        "is_deleted": {"$ne": True},
        "renewal_digest_opt_out": {"$ne": True},
    }, {"email": 1})
    async for u in admin_cursor:
        e = (u.get("email") or "").strip().lower()
        if e:
            emails.append(e)

    # Non-admin PMs / CPs: default OFF, opt-in.
    pm_cursor = db.users.find({
        "company_id": company_id,
        "role": {"$in": ["pm", "cp"]},
        "is_deleted": {"$ne": True},
        "renewal_digest_opt_in": True,
    }, {"email": 1})
    async for u in pm_cursor:
        e = (u.get("email") or "").strip().lower()
        if e:
            emails.append(e)

    # Optional shared mailbox alias.
    alias = (company.get("renewal_digest_alias_email") or "").strip().lower()
    if alias:
        emails.append(alias)

    # Dedupe, preserve order.
    seen = set()
    out = []
    for e in emails:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


async def _send_renewal_digest_email(recipients: list, subject: str, html: str) -> None:
    """Resend send. No-op if RESEND_API_KEY env is unset (dev environments)."""
    if not RESEND_API_KEY:
        logger.debug(
            f"[renewal_digest] RESEND_API_KEY unset; would have sent to "
            f"{len(recipients)} recipient(s) with subject={subject!r}"
        )
        return
    try:
        resend.api_key = RESEND_API_KEY
        # Resend Python SDK is sync — but the call is fast (<1s typical),
        # acceptable to run in the cron event loop.
        resend.Emails.send({
            "from": "Levelog <notifications@levelog.com>",
            "to": recipients,
            "subject": subject,
            "html": html,
        })
    except Exception as e:
        # Re-raise so the caller skips marking idempotency.
        raise


async def _eligibility_shadow_sweep():
    """30-min sweep that runs both legacy and v2 eligibility against
    every active permit, writes diff to `eligibility_shadow`. Only
    registered when ELIGIBILITY_REWRITE_MODE == 'shadow' (see startup).

    Cron lock: APScheduler `max_instances=1` ensures overlapping runs
    skip rather than double up. Mongo `processing_until` field on a
    sentinel doc would be more explicit but the in-process lock is
    sufficient for single-instance deploys.
    """
    from lib import eligibility_dispatcher, eligibility_shadow, eligibility_v2
    from permit_renewal import _check_renewal_eligibility_legacy_inner

    started = datetime.now(timezone.utc)
    permits_evaluated = 0
    permits_failed = 0

    # All permit rows on tracked projects with track_dob_status=True.
    # Fetch project + company once per permit; the dispatcher pattern
    # demands the snapshot-of-input determinism across legacy and v2.
    tracked_projects = await db.projects.find(
        {"track_dob_status": True, "is_deleted": {"$ne": True}},
        {"_id": 1, "name": 1, "company_id": 1},
    ).to_list(500)

    project_by_id = {str(p["_id"]): p for p in tracked_projects}
    company_cache: Dict[str, Optional[dict]] = {}

    for project in tracked_projects:
        project_id = str(project["_id"])
        company_id = project.get("company_id")
        if company_id and company_id not in company_cache:
            company_cache[company_id] = await db.companies.find_one(
                {"_id": to_query_id(company_id), "is_deleted": {"$ne": True}}
            )
        company = company_cache.get(company_id) or {}

        permits = await db.dob_logs.find({
            "project_id": project_id,
            "record_type": "permit",
            "is_deleted": {"$ne": True},
        }).to_list(500)

        for permit in permits:
            try:
                async def _legacy(p, pj, c, t, _name=None):
                    name = (
                        _name
                        or (c.get("gc_business_name") if c else None)
                        or (c.get("name") if c else "")
                        or ""
                    )
                    return await _check_renewal_eligibility_legacy_inner(
                        db, p, pj, name, c, today=t,
                    )

                async def _v2(d, p, pj, c, t):
                    return await eligibility_v2.evaluate(d, p, pj, c or {}, today=t)

                shadow_doc = await eligibility_shadow.run_one(
                    db,
                    legacy_callable=_legacy,
                    v2_callable=_v2,
                    permit=permit,
                    project=project,
                    company=company,
                )
                shadow_doc["sweep_started_at"] = started
                shadow_doc["project_id"] = project_id
                await db.eligibility_shadow.insert_one(shadow_doc)
                permits_evaluated += 1
            except Exception as e:
                permits_failed += 1
                logger.warning(
                    f"[eligibility_shadow_sweep] permit "
                    f"{permit.get('_id')} failed: {e!r}"
                )

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"🪞 eligibility shadow sweep complete: "
        f"evaluated={permits_evaluated} failed={permits_failed} "
        f"elapsed={elapsed:.1f}s"
    )


async def check_permit_expirations():
    """Check all tracked projects for permits expiring within 14 days. Called by nightly scan."""
    try:
        expiring_permits = []
        cutoff = datetime.now(timezone.utc) + timedelta(days=14)
 
        permits = await db.dob_logs.find({
            "record_type": "permit",
            "expiration_date": {"$ne": None},
            "is_deleted": {"$ne": True},
        }).to_list(1000)
 
        for permit in permits:
            exp_str = permit.get("expiration_date", "")
            if not exp_str:
                continue
            try:
                from dateutil import parser as dateparser
                exp_date = dateparser.parse(str(exp_str))
                if exp_date.tzinfo is None:
                    exp_date = exp_date.replace(tzinfo=timezone.utc)
                days_left = (exp_date - datetime.now(timezone.utc)).days
                if 0 < days_left <= 30:
                    await db.dob_logs.update_one(
                        {"_id": permit["_id"]},
                        {"$set": {"severity": "Action", "next_action": f"Permit expires in {days_left} days ({str(exp_str)[:10]}). File renewal on DOB NOW."}}
                    )
                    expiring_permits.append(permit)
                elif days_left <= 0:
                    await db.dob_logs.update_one(
                        {"_id": permit["_id"]},
                        {"$set": {"severity": "Action", "next_action": "EXPIRED: Permit has expired. Stop permitted work and file renewal immediately."}}
                    )
            except Exception:
                continue
 
        if expiring_permits:
            logger.info(f"Permit expiration check: {len(expiring_permits)} permits expiring within 14 days")
    except Exception as e:
        logger.error(f"Permit expiration check error: {e}")

 
# ==================== DOB COMPLIANCE ENDPOINTS ====================
 
@api_router.put("/projects/{project_id}/dob-config")
async def update_dob_config(project_id: str, config: DOBConfigUpdate, admin=Depends(get_admin_user)):
    """Manual override: update BIN/BBL and toggle DOB tracking."""
    project = await db.projects.find_one({
        "_id": to_query_id(project_id),
        "is_deleted": {"$ne": True},
    })
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
 
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
 
    update_fields = {"updated_at": datetime.now(timezone.utc)}
 
    if config.nyc_bin is not None:
        clean_bin = config.nyc_bin.strip()
        if clean_bin and (len(clean_bin) != 7 or not clean_bin.isdigit()):
            raise HTTPException(status_code=422, detail="BIN must be exactly 7 digits")
        update_fields["nyc_bin"] = clean_bin if clean_bin else None
 
    if config.bbl is not None:
        # Accept either `bbl` (canonical) or `nyc_bbl` (legacy alias)
        # via DOBConfigUpdate's populate_by_name. Always write to the
        # canonical `bbl` field. The step 9.1 migration $rename'd
        # legacy nyc_bbl values into bbl, so existing docs are clean.
        update_fields["bbl"] = config.bbl.strip() or None
        update_fields["bbl_source"] = "manual_entry"
        update_fields["bbl_last_synced"] = datetime.now(timezone.utc)
 
    if config.track_dob_status is not None:
        update_fields["track_dob_status"] = config.track_dob_status

    if config.gc_legal_name is not None:
        update_fields["gc_legal_name"] = config.gc_legal_name.strip() or None

    await db.projects.update_one({"_id": to_query_id(project_id)}, {"$set": update_fields})

    await audit_log("dob_config_update", str(admin.get("_id", admin.get("id", ""))), "project", project_id, {
        k: v for k, v in update_fields.items() if k != "updated_at"
    })

    updated = await db.projects.find_one({"_id": to_query_id(project_id)})

    # If BIN was just set or tracking just enabled, kick off an immediate background sync
    bin_changed = config.nyc_bin is not None and config.nyc_bin.strip() != (project.get("nyc_bin") or "")
    tracking_enabled = config.track_dob_status is True and not project.get("track_dob_status")
    if (bin_changed or tracking_enabled) and updated.get("nyc_bin"):
        import asyncio
        asyncio.create_task(run_dob_sync_for_project(updated))
        logger.info(f"Auto-triggered DOB sync for project {project_id} after config save")

    return {
        "message": "DOB config updated",
        "nyc_bin": updated.get("nyc_bin"),
        # bbl-first read with nyc_bbl fallback during step 9.1 transition.
        "bbl": updated.get("bbl") or updated.get("nyc_bbl"),
        "track_dob_status": updated.get("track_dob_status", False),
        "gc_legal_name": updated.get("gc_legal_name"),
    }


@api_router.get("/projects/{project_id}/dob-config")
async def get_dob_config(project_id: str, current_user=Depends(get_current_user)):
    """Get DOB config for a project (BIN, tracking, GC name)."""
    project = await db.projects.find_one({
        "_id": to_query_id(project_id),
        "is_deleted": {"$ne": True},
    })
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    return {
        "nyc_bin": project.get("nyc_bin"),
        # bbl-first read with nyc_bbl fallback during step 9.1 transition.
        "bbl": project.get("bbl") or project.get("nyc_bbl"),
        "track_dob_status": project.get("track_dob_status", False),
        "gc_legal_name": project.get("gc_legal_name"),
    }


@api_router.get("/projects/{project_id}/dob-logs")
async def get_dob_logs(
    project_id: str,
    current_user=Depends(get_current_user),
    severity: Optional[str] = Query(None, description="Filter: Low, Medium, Critical"),
    record_type: Optional[str] = Query(None, description="Filter: complaint, violation, job_status, swo"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get translated DOB logs for a project, sorted by detected_at descending."""
    project = await db.projects.find_one({
        "_id": to_query_id(project_id),
        "is_deleted": {"$ne": True},
    })
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
 
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
 
    query = {"project_id": project_id, "is_deleted": {"$ne": True}}
    if severity:
        query["severity"] = severity
    if record_type:
        query["record_type"] = record_type
 
    total = await db.dob_logs.count_documents(query)
    logs = await db.dob_logs.find(query).sort("detected_at", -1).skip(skip).limit(limit).to_list(limit)
 
    serialized_logs = []
    for log in logs:
        try:
            raw = log.get("raw_record") or {}
            rtype = log.get("record_type")

            # Broken DOB links written before the routing fix get
            # rebuilt on read from the raw record so existing rows pick
            # up working URLs without a migration. Previous regressions:
            # complaint URL used a bogus `vlession` param; permit URL
            # hardcoded passdocnumber=01; violation URL fed the ISN
            # into vlcompdetlkey; DOB NOW jobs (B-prefix) were routed
            # to BIS which doesn't have them. Now covers every type
            # whose builder was wrong.
            if raw and rtype in ("complaint", "permit", "job_status", "violation", "swo", "inspection"):
                try:
                    fresh_link = _build_dob_link(raw, rtype)
                    if fresh_link:
                        log["dob_link"] = fresh_link
                except Exception:
                    pass

            # Inspection records written before the job-prefix decoder landed
            # stored inspection_type as phase-only ("Initial"). Re-enrich on
            # read from the raw DOB record so existing rows show the work
            # category ("Plumbing — Initial") without a migration.
            if rtype == "inspection":
                phase = log.get("inspection_type") or ""
                if raw and ("—" not in phase):
                    job_id = (
                        log.get("linked_job_number")
                        or raw.get("job_id")
                        or raw.get("job_filing_number")
                        or raw.get("job_number")
                        or ""
                    )
                    category = _decode_job_prefix(str(job_id))
                    raw_phase = (
                        raw.get("inspection_type")
                        or raw.get("job_progress")
                        or phase
                    )
                    if category and raw_phase:
                        log["inspection_type"] = f"{category} — {raw_phase}"
                    elif category:
                        log["inspection_type"] = f"{category} Inspection"
                    # Regenerate summary so the card text reflects the category
                    result = raw.get("result") or log.get("inspection_result") or "Pending"
                    label_phase = raw_phase or "General"
                    if category and raw_phase:
                        label = f"{category} — {raw_phase} Inspection"
                    elif category:
                        label = f"{category} Inspection"
                    else:
                        label = f"{label_phase} Inspection"
                    job_str = f" (Job {job_id})" if job_id else ""
                    log["ai_summary"] = f"{label}{job_str} — Result: {result}"
            serialized_logs.append(DOBLogResponse(**serialize_id(dict(log))))
        except Exception as e:
            logger.error(f"Failed to serialize dob_log {log.get('_id')}: {e}")

    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "nyc_bin": project.get("nyc_bin"),
        "track_dob_status": project.get("track_dob_status", False),
        "total": total,
        "logs": serialized_logs,
    }
 
 
@api_router.post("/projects/{project_id}/dob-sync")
async def manual_dob_sync(project_id: str, current_user=Depends(get_current_user)):
    """Manual trigger: bypass cron and force immediate DOB fetch. Rate limited 15 min."""
    import traceback as _tb
    try:
        project = await db.projects.find_one({
            "_id": to_query_id(project_id),
            "is_deleted": {"$ne": True},
        })
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        company_id = get_user_company_id(current_user)
        if company_id and project.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Access denied to this project")

        if not project.get("nyc_bin") and not project.get("address"):
            raise HTTPException(status_code=400, detail="No BIN or address configured. Update DOB config first.")

        rate_key = f"dob_sync_last:{project_id}"
        rate_doc = await db.system_config.find_one({"key": rate_key})
        if rate_doc:
            last_time = rate_doc.get("last_sync_at")
            if last_time and isinstance(last_time, datetime):
                # Ensure both datetimes are tz-aware for subtraction
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                if elapsed < 900:
                    remaining = int(900 - elapsed)
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limited. Try again in {remaining // 60}m {remaining % 60}s.",
                    )
        await db.system_config.update_one(
            {"key": rate_key},
            {"$set": {"key": rate_key, "last_sync_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

        new_logs = await run_dob_sync_for_project(project)

        safe_logs = []
        for log in new_logs:
            try:
                safe_logs.append(DOBLogResponse(**serialize_id(dict(log))))
            except Exception as e:
                logger.warning(f"Failed to serialize dob_log {log.get('raw_dob_id')}: {e}")

        action_count = sum(1 for l in new_logs if l.get("severity") == "Action")
        return {
            "message": f"DOB sync complete. {len(new_logs)} new record(s) found.",
            "new_records": len(new_logs),
            "critical_count": action_count,
            "logs": safe_logs,
        }
    except HTTPException:
        raise
    except Exception as e:
        tb_str = _tb.format_exc()
        logger.exception(f"DOB sync UNHANDLED error for project {project_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"DOB sync error: {str(e)}"},
        )


# ==================== REPORT EMAIL SCHEDULER ====================

async def check_and_send_reports():
    """Called every minute. Sends report emails for projects whose send time matches now."""
    if not RESEND_API_KEY:
        return
    now = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    est_now = now.astimezone(eastern)
    current_time = est_now.strftime("%H:%M")
    today = est_now.strftime("%Y-%m-%d")

    projects_due = await db.projects.find({
        "report_send_time": current_time,
        "report_email_list": {"$exists": True, "$ne": []},
        "is_deleted": {"$ne": True},
    }).to_list(100)

    if not projects_due:
        return

    resend.api_key = RESEND_API_KEY
    for project in projects_due:
        project_id = str(project["_id"])
        project_name = project.get("name", "Project")
        email_list = project.get("report_email_list", [])
        if not email_list:
            continue
        already_sent = await db.report_emails.find_one({"project_id": project_id, "date": today})
        if already_sent:
            continue

        # Skip if no data exists for today (avoid blank reports)
        try:
            has_logbooks = await db.logbooks.count_documents({
                "project_id": project_id,
                "date": today,
                "status": "submitted",
                "is_deleted": {"$ne": True},
            })
            has_daily_log = await db.daily_logs.find_one({
                "project_id": project_id,
                "date": today,
                "is_deleted": {"$ne": True},
            })
            day_start = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            has_checkins = await db.checkins.count_documents({
                "project_id": project_id,
                "check_in_time": {"$gte": day_start, "$lt": day_end},
                "is_deleted": {"$ne": True},
            })
            if not has_logbooks and not has_daily_log and not has_checkins:
                logger.info(
                    f"Report skipped for {project_name} — no data for {today}"
                )
                continue
        except Exception as e:
            logger.warning(f"Data check failed for {project_name}, sending anyway: {e}")

        try:
            html = await generate_combined_report(project_id, today)
            resend.Emails.send({
                "from": "Levelog Reports <reports@levelog.com>",
                "to": email_list,
                "subject": f"Daily Report - {project_name} - {today}",
                "html": html,
            })
            await db.report_emails.insert_one({
                "project_id": project_id,
                "date": today,
                "sent_at": now,
                "recipients": email_list,
            })
            logger.info(f"Report sent for {project_name} to {len(email_list)} recipients")
        except Exception as e:
            logger.error(f"Failed to send report for {project_name}: {e}")

# ==================== DOCUMENT ANNOTATIONS (PLAN NOTES) ====================

async def _generate_annotation_screenshot(
    annotation_id: str,
    document_path: str,
    page_number: int,
    position: dict,
    project_id: str,
    company_id: str,
):
    """Render page thumbnail, draw red circle at pin, crop 400x400, store as base64 data URL."""
    if not SCREENSHOT_ENABLED:
        return
    try:
        from pdf2image import convert_from_bytes
        from PIL import Image, ImageDraw

        # Fetch PDF bytes from Dropbox
        project = await db.projects.find_one({"_id": to_query_id(project_id)})
        if not project:
            return
        try:
            access_token = await get_valid_dropbox_token(company_id)
        except Exception:
            return

        async with ServerHttpClient(timeout=30) as hc:
            resp = await hc.post(
                "https://content.dropboxapi.com/2/files/download",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Dropbox-API-Arg": f'{{"path": "{document_path}"}}',
                },
            )
            if resp.status_code != 200:
                logger.error(f"Dropbox download failed for annotation screenshot: {resp.status_code}")
                return
            pdf_bytes = resp.content

        images = convert_from_bytes(pdf_bytes, first_page=page_number, last_page=page_number, dpi=150)
        if not images:
            return
        img = images[0]

        # Draw red circle at position
        draw = ImageDraw.Draw(img)
        px = int(position.get("x", 0.5) * img.width)
        py = int(position.get("y", 0.5) * img.height)
        r = 18
        draw.ellipse([px - r, py - r, px + r, py + r], outline="red", width=4)

        # Crop 400x400 centred on pin
        half = 200
        left = max(px - half, 0)
        top = max(py - half, 0)
        right = min(px + half, img.width)
        bottom = min(py + half, img.height)
        cropped = img.crop((left, top, right, bottom))

        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        data_url = f"data:image/jpeg;base64,{b64}"

        await db.document_annotations.update_one(
            {"_id": to_query_id(annotation_id)},
            {"$set": {"screenshot": data_url}},
        )
        logger.info(f"Annotation screenshot generated for {annotation_id}")
    except Exception as e:
        logger.error(f"Annotation screenshot failed: {e}")


async def _send_annotation_emails(annotation: dict, project_name: str, recipient_ids: list, creator_id: str):
    """Wait up to 30s for screenshot, then email all recipients."""
    try:
        # Wait for screenshot to be generated (up to 30s)
        ann_id = annotation.get("id") or str(annotation.get("_id"))
        screenshot_url = None
        for _ in range(15):
            await asyncio.sleep(2)
            doc = await db.document_annotations.find_one({"_id": to_query_id(ann_id)})
            if doc and doc.get("screenshot"):
                screenshot_url = doc["screenshot"]
                break

        # Gather recipient emails
        recipient_emails = []
        for uid in recipient_ids:
            if uid == creator_id:
                continue
            user = await db.users.find_one({"_id": to_query_id(uid)})
            if user and user.get("email"):
                recipient_emails.append(user["email"])

        if not recipient_emails:
            return

        creator = await db.users.find_one({"_id": to_query_id(creator_id)})
        creator_name = creator.get("name", "A team member") if creator else "A team member"

        short_link = f"https://levelog.com/a/{ann_id}"
        comment_text = annotation.get("comment", "")

        screenshot_block = ""
        if screenshot_url:
            screenshot_block = f'<img src="{screenshot_url}" alt="Plan screenshot" style="max-width:400px;border-radius:8px;border:1px solid #e2e8f0;margin:12px 0;" /><br/>'

        html = f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px;background:#ffffff;">
            <div style="text-align:center;margin-bottom:16px;">
                <span style="font-size:20px;font-weight:700;color:#1e3a5f;">LEVELOG</span>
            </div>
            <div style="background:#f8fafc;border-radius:12px;padding:20px;border:1px solid #e2e8f0;">
                <p style="margin:0 0 8px;font-size:14px;color:#64748b;">New Plan Note on <strong>{project_name}</strong></p>
                <p style="margin:0 0 16px;font-size:16px;color:#1e293b;"><strong>{creator_name}</strong> left a note:</p>
                {screenshot_block}
                <div style="background:#ffffff;border-radius:8px;padding:16px;border-left:4px solid #3b82f6;margin:12px 0;">
                    <p style="margin:0;font-size:14px;color:#334155;">{comment_text}</p>
                </div>
                <a href="{short_link}" style="display:inline-block;margin-top:16px;padding:10px 24px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600;">View Note</a>
            </div>
            <p style="text-align:center;font-size:10px;color:#cbd5e1;margin-top:16px;letter-spacing:2px;">LEVELOG</p>
        </div>
        """

        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": "Levelog Plans <plans@levelog.com>",
            "to": recipient_emails,
            "subject": f"Plan Note — {project_name}",
            "html": html,
        })
        logger.info(f"Annotation email sent to {len(recipient_emails)} recipients for {ann_id}")
    except Exception as e:
        logger.error(f"Failed to send annotation email: {e}")


async def _send_reply_notification(annotation: dict, thread_entry: dict):
    """Notify annotation creator when someone replies."""
    try:
        ann_id = annotation.get("id") or str(annotation.get("_id"))
        creator_id = annotation.get("created_by")
        replier_id = thread_entry.get("user_id")

        if creator_id == replier_id:
            return  # Don't notify self

        creator = await db.users.find_one({"_id": to_query_id(creator_id)})
        if not creator or not creator.get("email"):
            return

        replier = await db.users.find_one({"_id": to_query_id(replier_id)})
        replier_name = replier.get("name", "A team member") if replier else "A team member"

        project = await db.projects.find_one({"_id": to_query_id(annotation.get("project_id"))})
        project_name = project.get("name", "Unknown Project") if project else "Unknown Project"

        short_link = f"https://levelog.com/a/{ann_id}"
        reply_text = thread_entry.get("message", "")

        html = f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px;background:#ffffff;">
            <div style="text-align:center;margin-bottom:16px;">
                <span style="font-size:20px;font-weight:700;color:#1e3a5f;">LEVELOG</span>
            </div>
            <div style="background:#f8fafc;border-radius:12px;padding:20px;border:1px solid #e2e8f0;">
                <p style="margin:0 0 8px;font-size:14px;color:#64748b;">Reply on <strong>{project_name}</strong></p>
                <p style="margin:0 0 16px;font-size:16px;color:#1e293b;"><strong>{replier_name}</strong> replied to your note:</p>
                <div style="background:#ffffff;border-radius:8px;padding:16px;border-left:4px solid #10b981;margin:12px 0;">
                    <p style="margin:0;font-size:14px;color:#334155;">{reply_text}</p>
                </div>
                <a href="{short_link}" style="display:inline-block;margin-top:16px;padding:10px 24px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600;">View Thread</a>
            </div>
            <p style="text-align:center;font-size:10px;color:#cbd5e1;margin-top:16px;letter-spacing:2px;">LEVELOG</p>
        </div>
        """

        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": "Levelog Plans <plans@levelog.com>",
            "to": [creator["email"]],
            "subject": f"Reply on Plan Note — {project_name}",
            "html": html,
        })
        logger.info(f"Reply notification sent for annotation {ann_id}")
    except Exception as e:
        logger.error(f"Failed to send reply notification: {e}")


@api_router.get("/users/company-roster")
async def get_company_roster(current_user=Depends(get_current_user)):
    """Minimal user roster for the current user's company. Any authenticated
    user can call this — used by the annotation recipient picker. Returns
    only safe fields (id, name, email, role) and excludes deleted users.
    """
    company_id = get_user_company_id(current_user)
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    users = await db.users.find(
        query,
        {"password": 0, "_id": 1, "name": 1, "full_name": 1, "email": 1, "role": 1},
    ).sort("name", 1).to_list(500)
    out = []
    for u in users:
        out.append({
            "id":    str(u.get("_id")),
            "name":  u.get("name") or u.get("full_name") or u.get("email") or "Unknown",
            "email": u.get("email") or "",
            "role":  u.get("role") or "",
        })
    return out


@api_router.post("/annotations")
async def create_annotation(data: dict, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    """Create a document annotation (plan note).

    Accepts EITHER `document_path` (legacy, Dropbox-synced files) or `file_id`
    (direct-uploaded files which have no dropbox path). file_id is
    canonicalized as `file:{id}` and used as the document_path key.
    """
    project_id = data.get("project_id")
    document_path = (data.get("document_path") or "").strip()
    file_id = (data.get("file_id") or "").strip()
    page_number = data.get("page_number", 1)
    position = data.get("position", {"x": 0.5, "y": 0.5})
    comment = data.get("comment", "")
    recipients_input = data.get("recipients", "all")

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    # Prefer file_id when present — it's stable across renames / R2 keys
    # (direct-upload files have empty dropbox_path).
    if file_id:
        document_path = f"file:{file_id}"
    if not document_path:
        raise HTTPException(
            status_code=400,
            detail="Either document_path or file_id is required",
        )

    user_id = current_user.get("id") or str(current_user.get("_id"))
    company_id = get_user_company_id(current_user)

    # Expand "all" to actual user IDs in the company
    if recipients_input == "all":
        all_users = await db.users.find(
            {"company_id": company_id, "is_deleted": {"$ne": True}},
            {"_id": 1},
        ).to_list(500)
        recipient_ids = [str(u["_id"]) for u in all_users]
    else:
        recipient_ids = recipients_input if isinstance(recipients_input, list) else [recipients_input]
        # Coerce any IDs to strings
        recipient_ids = [str(r) for r in recipient_ids if r]

    now = datetime.now(timezone.utc)
    doc = {
        "project_id": project_id,
        "document_path": document_path,
        "file_id": file_id or None,
        "page_number": page_number,
        "position": position,
        "comment": comment,
        "recipients": recipient_ids,
        "created_by": user_id,
        "company_id": company_id,
        "thread": [],
        "resolved": False,
        "is_deleted": False,
        "screenshot": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.document_annotations.insert_one(doc)
    ann_id = str(result.inserted_id)
    doc["id"] = ann_id

    # Fetch project name for email
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = project.get("name", "Unknown Project") if project else "Unknown Project"

    # Background: generate screenshot + send emails
    background_tasks.add_task(
        _generate_annotation_screenshot, ann_id, document_path, page_number, position, project_id, company_id
    )
    background_tasks.add_task(
        _send_annotation_emails, doc, project_name, recipient_ids, user_id
    )

    return serialize_id(doc)


@api_router.get("/annotations/{project_id}/{document_path:path}")
async def get_annotations_for_document(project_id: str, document_path: str, current_user=Depends(get_current_user)):
    """Get annotations for a document with server-side visibility filtering.

    `document_path` may be either a real Dropbox path ("/Projects/…/A-101.pdf")
    or the sentinel form `file:{id}` used by direct-uploaded files.
    """
    user_id = current_user.get("id") or str(current_user.get("_id"))
    user_role = current_user.get("role")

    query = {
        "project_id": project_id,
        "document_path": document_path,
        "is_deleted": {"$ne": True},
    }

    # Non-admins only see their own annotations or where they are recipients
    if user_role not in ["admin", "owner"]:
        query["$or"] = [
            {"created_by": user_id},
            {"recipients": user_id},
        ]

    annotations = await db.document_annotations.find(query).sort("created_at", -1).to_list(500)
    return serialize_list([dict(a) for a in annotations])


@api_router.put("/annotations/{annotation_id}/reply")
async def add_annotation_reply(annotation_id: str, data: dict, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    """Add a reply to an annotation thread."""
    message = data.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    user_id = current_user.get("id") or str(current_user.get("_id"))
    now = datetime.now(timezone.utc)

    thread_entry = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "user_name": current_user.get("name", "Unknown"),
        "message": message,
        "created_at": now,
    }

    result = await db.document_annotations.update_one(
        {"_id": to_query_id(annotation_id), "is_deleted": {"$ne": True}},
        {"$push": {"thread": thread_entry}, "$set": {"updated_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Annotation not found")

    annotation = await db.document_annotations.find_one({"_id": to_query_id(annotation_id)})
    background_tasks.add_task(_send_reply_notification, serialize_id(dict(annotation)), thread_entry)

    return serialize_id(dict(annotation))


@api_router.put("/annotations/{annotation_id}/resolve")
async def resolve_annotation(annotation_id: str, current_user=Depends(get_current_user)):
    """Mark annotation as resolved. Only creator, recipient, or admin can resolve."""
    user_id = current_user.get("id") or str(current_user.get("_id"))
    user_role = current_user.get("role")

    annotation = await db.document_annotations.find_one(
        {"_id": to_query_id(annotation_id), "is_deleted": {"$ne": True}}
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    is_creator = annotation.get("created_by") == user_id
    is_recipient = user_id in (annotation.get("recipients") or [])
    is_admin = user_role in ["admin", "owner"]

    if not (is_creator or is_recipient or is_admin):
        raise HTTPException(status_code=403, detail="Not authorized to resolve this annotation")

    await db.document_annotations.update_one(
        {"_id": to_query_id(annotation_id)},
        {"$set": {"resolved": True, "resolved_by": user_id, "resolved_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.document_annotations.find_one({"_id": to_query_id(annotation_id)})
    return serialize_id(dict(updated))


@api_router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, current_user=Depends(get_current_user)):
    """Soft delete an annotation. Only creator or admin."""
    user_id = current_user.get("id") or str(current_user.get("_id"))
    user_role = current_user.get("role")

    annotation = await db.document_annotations.find_one(
        {"_id": to_query_id(annotation_id), "is_deleted": {"$ne": True}}
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    is_creator = annotation.get("created_by") == user_id
    is_admin = user_role in ["admin", "owner"]

    if not (is_creator or is_admin):
        raise HTTPException(status_code=403, detail="Not authorized to delete this annotation")

    await db.document_annotations.update_one(
        {"_id": to_query_id(annotation_id)},
        {"$set": {"is_deleted": True, "deleted_by": user_id, "deleted_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
    )
    return {"status": "deleted"}


# ==================== PERMIT RENEWAL MODULE ====================
# Tolerate both Railway deploy modes:
#   - Dockerfile: WORKDIR=/app, package = `backend`, import path
#                 `backend.permit_renewal`
#   - Procfile:   `cd backend && uvicorn server:app`, cwd has
#                 backend/ on sys.path, import path `permit_renewal`
# Either succeeds; the other ModuleNotFoundError is swallowed.
try:
    from backend.permit_renewal import create_permit_renewal_routes, nightly_renewal_scan
except ModuleNotFoundError:
    from permit_renewal import create_permit_renewal_routes, nightly_renewal_scan

create_permit_renewal_routes(
    api_router=api_router,
    db=db,
    get_current_user=get_current_user,
    get_admin_user=get_admin_user,
    to_query_id=to_query_id,
    get_user_company_id=get_user_company_id,
    serialize_id=serialize_id,
)

# ==================== WHATSAPP INTEGRATION ====================

import random
import string as _string
import io

# ---------- helpers ----------

async def send_whatsapp_message(chat_id: str, message: str):
    """Send a WhatsApp message via WaAPI HTTP API."""
    if not WAAPI_INSTANCE_ID or not WAAPI_TOKEN:
        logger.warning("WhatsApp send skipped — WAAPI credentials not configured")
        return None
    url = f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/client/action/send-message"
    headers = {"Authorization": f"Bearer {WAAPI_TOKEN}", "Content-Type": "application/json"}
    payload = {"chatId": chat_id, "message": message}
    try:
        async with ServerHttpClient(timeout=15) as client_http:
            resp = await client_http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            # Log outbound bot turn into whatsapp_messages so the agent's
            # history loader can recall it on the next user message (makes
            # multi-turn clarifications work). Best-effort — never fail send.
            try:
                now = datetime.now(timezone.utc)
                await db.whatsapp_messages.insert_one({
                    "group_id":   chat_id,
                    "sender":     "bot",
                    "body":       message,
                    "has_audio":  False,
                    "message_id": "",
                    "timestamp":  now,
                    "created_at": now,
                })
            except Exception as _log_err:
                logger.debug(f"whatsapp_messages bot-log skipped: {_log_err}")
            return resp.json()
    except Exception as e:
        logger.error(f"WhatsApp send failed to {chat_id}: {e}")
        return None


def parse_inbound_message(payload: dict, vendor: str = "waapi") -> dict:
    """Normalize a WaAPI inbound webhook payload to a standard format.

    WaAPI puts most fields inside msg._data (the raw WhatsApp-Web payload).
    Some fields are duplicated at msg level, others are only inside _data.
    We read with a `_data`-first fallback so either shape works.
    """
    if vendor == "waapi":
        data = payload.get("data", {})
        msg = data.get("message", data)
        inner = (msg.get("_data") or {}) if isinstance(msg.get("_data"), dict) else {}

        # Auto-learn bot LID: if this webhook is for a message FROM us
        # (fromMe=true) whose author JID is a @lid, that IS our bot's
        # LID. Learn it once; subsequent inbound @mentions will match
        # even without WAAPI_BOT_LID configured.
        try:
            msg_id_blob = msg.get("id") or inner.get("id") or {}
            from_me = False
            if isinstance(msg_id_blob, dict):
                from_me = bool(msg_id_blob.get("fromMe"))
            if from_me:
                for cand in (
                    msg.get("author"),
                    inner.get("author"),
                    msg.get("from"),
                    inner.get("from"),
                    msg_id_blob.get("participant") if isinstance(msg_id_blob, dict) else None,
                ):
                    if isinstance(cand, str) and "@lid" in cand:
                        _learn_bot_lid(_jid_digits(cand))
                        break
        except Exception:
            pass

        def _pick(field, default=""):
            # Prefer top-level, fall back to _data
            v = msg.get(field)
            if v is None or v == "":
                v = inner.get(field, default)
            return v if v is not None else default

        from_field = _pick("from", "")
        to_field = _pick("to", "")
        body = _pick("body", "")
        mtype = _pick("type", "")
        author = _pick("author", "") or from_field  # in groups, author = sender

        is_group = "@g.us" in from_field

        # Audio / voice notes
        has_audio = mtype in ("audio", "ptt")
        audio_url = None
        if has_audio:
            media = msg.get("media") or inner or {}
            audio_url = media.get("url") or media.get("directPath")

        # Images
        has_image = (mtype == "image")
        image_url = None
        if has_image:
            media = msg.get("media") or {}
            image_url = media.get("url") or media.get("directPath") or None

        # Message id can live at msg.id.id (nested), msg.id (string), or inner.id.id
        raw_id = msg.get("id")
        if isinstance(raw_id, dict):
            msg_id = raw_id.get("id", "")
        elif raw_id:
            msg_id = str(raw_id)
        else:
            inner_id = inner.get("id")
            if isinstance(inner_id, dict):
                msg_id = inner_id.get("id", "")
            else:
                msg_id = str(inner_id or "")

        # Serialized id — WaAPI's download-media action rejects the short
        # hash and requires the full 'false_<chatId>_<hash>_<sender>@lid'
        # form. Live in id._serialized on both outer msg and inner._data.
        msg_id_serialized = ""
        for src in (msg.get("id"), inner.get("id")):
            if isinstance(src, dict):
                v = src.get("_serialized")
                if isinstance(v, str) and v:
                    msg_id_serialized = v
                    break

        # Timestamp — WaAPI uses 't' (epoch seconds) inside _data, 'timestamp' elsewhere
        ts = msg.get("timestamp") or inner.get("t") or inner.get("timestamp") or 0
        try:
            ts = int(ts)
        except Exception:
            ts = 0

        # Quoted message (reply context). WhatsApp puts the quoted message
        # under quotedMsg / quotedMessage / contextInfo.quotedMessage
        # depending on payload version. We need:
        #   - body text (for @levelog threading on text replies),
        #   - type + messageId (for voicenote-replied-to-with-@levelog, so
        #     we can pull the voicenote audio out and transcribe it).
        quoted_body = ""
        quoted_type = ""
        quoted_message_id = ""
        quoted_node = None
        for path in (
            ("quotedMsg",),
            ("quotedMessage",),
            ("contextInfo", "quotedMessage"),
        ):
            node = msg
            for k in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if isinstance(node, dict):
                quoted_node = node
                quoted_body = (node.get("body") or node.get("conversation") or "").strip()
                quoted_type = (node.get("type") or "").strip()
                if quoted_body or quoted_type:
                    break
        if quoted_node is None:
            inner_ctx = inner.get("quotedMsg") or inner.get("contextInfo") or {}
            if isinstance(inner_ctx, dict):
                q = inner_ctx.get("quotedMessage") or inner_ctx
                if isinstance(q, dict):
                    quoted_node = q
                    quoted_body = (q.get("body") or q.get("conversation") or "").strip()
                    quoted_type = (q.get("type") or "").strip()
        # quotedStanzaID / quotedParticipant / stanzaId — WaAPI surfaces one of
        # these as the id of the quoted message. Check both the outer msg
        # context and the inner _data context.
        for src in (msg, inner):
            if not isinstance(src, dict):
                continue
            ctx = src.get("contextInfo") or src.get("context_info") or {}
            if isinstance(ctx, dict):
                for key in ("stanzaId", "stanzaID", "quotedStanzaID", "quotedStanzaId", "quotedMessageId"):
                    v = ctx.get(key)
                    if isinstance(v, str) and v:
                        quoted_message_id = v
                        break
            if quoted_message_id:
                break
        # Fallback: if the quoted node itself carries an id, use it.
        if not quoted_message_id and isinstance(quoted_node, dict):
            qid = quoted_node.get("id")
            if isinstance(qid, dict):
                qid = qid.get("id")
            if isinstance(qid, str) and qid:
                quoted_message_id = qid

        # Mentions — WhatsApp's native @-mention (tap @ then pick a contact)
        # doesn't put "@Levelog" in the body as text; it stores the mentioned
        # contact's JID(s) in mentionedJidList / mentionedIds / contextInfo.
        # The body contains the bare phone number like "@15165494475 show me…"
        # (with the human-readable contact name rendered only client-side).
        mentioned_jids: list = []
        for path in (
            ("mentionedJidList",),
            ("mentionedIds",),
            ("contextInfo", "mentionedJid"),
            ("contextInfo", "mentionedJidList"),
        ):
            node = msg
            for k in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if isinstance(node, list):
                mentioned_jids.extend(str(j) for j in node if j)
        # Also look inside _data
        for path in (
            ("mentionedJidList",),
            ("mentionedIds",),
            ("contextInfo", "mentionedJid"),
        ):
            node = inner
            for k in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if isinstance(node, list):
                mentioned_jids.extend(str(j) for j in node if j)
        # De-duplicate while preserving order
        seen = set()
        mentioned_jids = [j for j in mentioned_jids if not (j in seen or seen.add(j))]

        # Flag: the quoted message is a voicenote (ptt/audio). Used by the
        # processor to fetch + transcribe the quoted audio when a text
        # reply with @levelog quotes a voicenote.
        quoted_is_audio = quoted_type.lower() in ("audio", "ptt", "voice") or (
            isinstance(quoted_node, dict) and (
                "ptt" in (quoted_node.get("type") or "").lower()
                or bool(quoted_node.get("audioMessage"))
                or bool(quoted_node.get("pttMessage"))
            )
        )

        return {
            "message_id": msg_id,
            "message_id_serialized": msg_id_serialized,
            "from": from_field,
            "sender": author,
            "to": to_field,
            "body": body,
            "quoted_body": quoted_body,
            "quoted_type": quoted_type,
            "quoted_is_audio": quoted_is_audio,
            "quoted_message_id": quoted_message_id,
            "mentioned_jids": mentioned_jids,
            "is_group": is_group,
            "group_id": from_field if is_group else None,
            "timestamp": ts,
            "has_audio": has_audio,
            "audio_url": audio_url,
            "has_image": has_image,
            "image_url": image_url,
            "raw": msg,
        }
    # Fallback — return as-is with safe defaults
    return {
        "message_id": str(payload.get("id", "")),
        "from": payload.get("from", ""),
        "sender": payload.get("from", ""),
        "to": payload.get("to", ""),
        "body": payload.get("body", ""),
        "is_group": False,
        "group_id": None,
        "timestamp": 0,
        "has_audio": False,
        "audio_url": None,
        "has_image": False,
        "image_url": None,
        "raw": payload,
    }


def _decrypt_whatsapp_media(
    encrypted: bytes,
    media_key_b64: str,
    media_type: str = "audio",
) -> Optional[bytes]:
    """Decrypt a WhatsApp .enc media blob using its mediaKey.

    WhatsApp media is AES-256-CBC encrypted with HKDF-SHA256 derived
    keys. Reference: WhatsApp / Signal protocol media spec, implemented
    the same way Baileys / whatsmeow / wa-automate do.

    Pipeline:
      1. HKDF-SHA256(mediaKey, salt=zero32, info=<type-specific>) → 112 bytes
      2. iv = keys[0:16], cipherKey = keys[16:48]
      3. ciphertext = encrypted[:-10]  (strip 10-byte MAC tag)
      4. AES-256-CBC decrypt, PKCS7 unpad → decoded media bytes
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
    except Exception as e:
        logger.error(f"cryptography import failed: {e}")
        return None

    info_map = {
        "image":    b"WhatsApp Image Keys",
        "video":    b"WhatsApp Video Keys",
        "audio":    b"WhatsApp Audio Keys",
        "document": b"WhatsApp Document Keys",
    }
    info = info_map.get(media_type, b"WhatsApp Audio Keys")

    try:
        key = base64.b64decode(media_key_b64)
    except Exception as e:
        logger.warning(f"mediaKey b64 decode failed: {e}")
        return None
    if len(key) != 32:
        logger.warning(
            f"mediaKey unexpected length {len(key)} (expected 32 bytes)"
        )
        return None

    try:
        keys = HKDF(
            algorithm=hashes.SHA256(),
            length=112,
            salt=b"\x00" * 32,
            info=info,
        ).derive(key)
    except Exception as e:
        logger.warning(f"HKDF derive failed: {e}")
        return None

    iv = keys[0:16]
    cipher_key = keys[16:48]

    if len(encrypted) < 11:
        return None
    ciphertext = encrypted[:-10]  # last 10 bytes are MAC; we don't verify here

    try:
        decryptor = Cipher(algorithms.AES(cipher_key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as e:
        logger.warning(f"AES decrypt failed: {e}")
        return None

    # PKCS7 unpad
    if not padded:
        return None
    pad_len = padded[-1]
    if 1 <= pad_len <= 16 and padded[-pad_len:] == bytes([pad_len]) * pad_len:
        return padded[:-pad_len]
    return padded


# Shared dict caller can set on parsed_msg — download_audio fills it with
# decrypt-attempt diagnostics so the processor can persist it into the
# audio_diag row. Keys: mediakey_found(bool), mediakey_len(int),
# decrypt_attempted(bool), decrypt_produced_ogg(bool), decrypt_error(str).
_AUDIO_DIAG_KEY = "__audio_diag__"


async def download_audio(parsed_msg: dict) -> Optional[bytes]:
    """Download audio bytes for a voicenote.

    WhatsApp delivers voicenote media as an encrypted `directPath` in
    the webhook — raw GETs against that path return 404. We have to
    go through WaAPI's download-media endpoint (or mediaUrl if WaAPI
    already re-hosted it).

    Order of attempts:
      1. If audio_url is an https URL pointing at WaAPI's CDN
         (contains 'waapi'), try the GET with the WaAPI Bearer token.
      2. Otherwise, POST to the WaAPI download-media endpoint with
         the messageId — this returns base64 bytes we decode.
      3. Last resort, try the raw URL with no auth in case WaAPI
         already re-hosted it on an open CDN.
    """
    # WaAPI's download-media action wants the SERIALIZED messageId
    # (bool_chatId_hash_sender@lid), not the short hash. The serialized
    # form is what the webhook delivers under id._serialized. Caller
    # may pass either — prefer serialized, fall back to short.
    message_id_ser = parsed_msg.get("message_id_serialized") or ""
    message_id = message_id_ser or parsed_msg.get("message_id") or ""
    audio_url = parsed_msg.get("audio_url")
    probe_trace: List[Dict[str, Any]] = []

    if WAAPI_INSTANCE_ID and WAAPI_TOKEN and message_id:
        # WaAPI v1 exposes multiple equivalent endpoints for media download;
        # try the most common names in order. We stop on the first 2xx.
        # Each failure writes a trace entry so the debug endpoint can show
        # which names actually exist on this account.
        # Only client/action/download-media exists on WaAPI v1 — the
        # others are 404s. Kept in the list but first in priority so
        # the common path is fast; we fall through on error for
        # diagnostic coverage only.
        paths = [
            "client/action/download-media",
        ]
        for path in paths:
            try:
                async with ServerHttpClient(timeout=45) as client_http:
                    resp = await client_http.post(
                        f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/{path}",
                        headers={
                            "Authorization": f"Bearer {WAAPI_TOKEN}",
                            "Content-Type":  "application/json",
                        },
                        json={"messageId": message_id},
                    )
                    if 200 <= resp.status_code < 300:
                        probe_trace.append({
                            "path":   path,
                            "status": resp.status_code,
                            "body":   (resp.text or "")[:4000],
                        })
                        j = resp.json() if resp.content else {}

                        # Recursively walk the response looking for a
                        # base64 audio payload or a media URL. WaAPI
                        # nests under data.data.media / data.data.message,
                        # different plans may vary.
                        def _find_audio(node: Any, depth: int = 0) -> Optional[bytes]:
                            if depth > 8 or node is None:
                                return None
                            if isinstance(node, str):
                                # Heuristic: base64 audio blobs are >500 chars
                                # and start with common OGG/OPUS magic-encoded
                                # prefixes. data: URI has the mime prefix.
                                s = node
                                if s.startswith("data:") and ";base64," in s:
                                    try:
                                        return base64.b64decode(s.split(",", 1)[1])
                                    except Exception:
                                        return None
                                # Heuristic: pure base64 of audio (>500 chars,
                                # only base64 alphabet) — try decode.
                                if len(s) > 500 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", s):
                                    try:
                                        b = base64.b64decode(s, validate=False)
                                        # Very rough sanity: ogg starts b"OggS".
                                        if len(b) > 200:
                                            return b
                                    except Exception:
                                        return None
                                return None
                            if isinstance(node, dict):
                                # Check common explicit keys first.
                                for key in (
                                    "base64", "mediaBase64", "audioBase64",
                                    "dataUrl", "dataURL",
                                ):
                                    v = node.get(key)
                                    if isinstance(v, str) and len(v) > 100:
                                        r = _find_audio(v, depth + 1)
                                        if r:
                                            return r
                                # Then any string child long enough.
                                for k, v in node.items():
                                    r = _find_audio(v, depth + 1)
                                    if r:
                                        return r
                            elif isinstance(node, list):
                                for item in node:
                                    r = _find_audio(item, depth + 1)
                                    if r:
                                        return r
                            return None

                        audio_bytes_found = _find_audio(j)
                        # Populate caller-visible diag.
                        diag_slot = parsed_msg.setdefault(_AUDIO_DIAG_KEY, {})
                        diag_slot["raw_bytes_size"] = (
                            len(audio_bytes_found) if audio_bytes_found else 0
                        )
                        if audio_bytes_found:
                            diag_slot["raw_first16"] = audio_bytes_found[:16].hex()
                            magic = audio_bytes_found[:16].hex()
                            known_magics = (
                                b"OggS", b"ID3", b"\xff\xfb", b"\xff\xf3",
                                b"\xff\xf2", b"RIFF",
                            )
                            is_decoded = any(
                                audio_bytes_found.startswith(m) for m in known_magics
                            )
                            diag_slot["already_decoded"] = is_decoded
                            if not is_decoded:
                                def _find_mediakey(node: Any, depth: int = 0) -> Optional[str]:
                                    if depth > 10 or node is None:
                                        return None
                                    if isinstance(node, dict):
                                        # Explicit key first.
                                        v = node.get("mediaKey")
                                        if isinstance(v, str) and len(v) >= 40:
                                            return v
                                        for key, val in node.items():
                                            if key == "mediaKey" and isinstance(val, str):
                                                return val
                                            r = _find_mediakey(val, depth + 1)
                                            if r:
                                                return r
                                    elif isinstance(node, list):
                                        for item in node:
                                            r = _find_mediakey(item, depth + 1)
                                            if r:
                                                return r
                                    return None

                                media_key_b64 = _find_mediakey(j)
                                diag_slot["mediakey_found"] = bool(media_key_b64)
                                diag_slot["mediakey_len"] = (
                                    len(media_key_b64) if media_key_b64 else 0
                                )
                                if media_key_b64:
                                    diag_slot["decrypt_attempted"] = True
                                    try:
                                        decrypted = _decrypt_whatsapp_media(
                                            audio_bytes_found, media_key_b64, "audio"
                                        )
                                    except Exception as _de:
                                        decrypted = None
                                        diag_slot["decrypt_error"] = (
                                            f"{type(_de).__name__}: {str(_de)[:160]}"
                                        )
                                    diag_slot["decrypt_returned_bytes"] = bool(decrypted)
                                    if decrypted:
                                        diag_slot["decrypt_first16"] = (
                                            decrypted[:16].hex()
                                        )
                                        diag_slot["decrypt_produced_ogg"] = (
                                            decrypted.startswith(b"OggS")
                                        )
                                        audio_bytes_found = decrypted
                                        magic = audio_bytes_found[:16].hex()
                            probe_trace.append({
                                "path":          path + " [SUCCESS]",
                                "size":          len(audio_bytes_found),
                                "first16":       magic,
                                "ascii8":        audio_bytes_found[:8].decode(
                                    "ascii", errors="replace"
                                ),
                                "was_encrypted": not is_decoded,
                                "decrypt_done":  not is_decoded and magic.startswith("4f6767"),
                            })
                            logger.info(
                                f"audio success probe: size={len(audio_bytes_found)} "
                                f"magic={magic} was_enc={not is_decoded}"
                            )
                            try:
                                await db.whatsapp_audio_probe.insert_one({
                                    "message_id":  message_id,
                                    "trace":       probe_trace,
                                    "received_at": datetime.now(timezone.utc),
                                    "outcome":     "success",
                                })
                            except Exception as _ins_err:
                                logger.error(
                                    f"audio probe insert failed: {_ins_err}"
                                )
                            return audio_bytes_found

                        # Fall back to URL discovery.
                        def _find_url(node: Any, depth: int = 0) -> Optional[str]:
                            if depth > 8 or node is None:
                                return None
                            if isinstance(node, str):
                                if node.startswith("http") and ("." in node):
                                    return node
                                return None
                            if isinstance(node, dict):
                                for key in ("mediaUrl", "url", "downloadUrl", "directUrl"):
                                    v = node.get(key)
                                    if isinstance(v, str) and v.startswith("http"):
                                        return v
                                for v in node.values():
                                    r = _find_url(v, depth + 1)
                                    if r:
                                        return r
                            elif isinstance(node, list):
                                for item in node:
                                    r = _find_url(item, depth + 1)
                                    if r:
                                        return r
                            return None

                        media_url = _find_url(j)
                        if isinstance(media_url, str) and media_url.startswith("http"):
                            # WaAPI handed us a CDN URL instead of inline bytes.
                            try:
                                resp2 = await client_http.get(media_url)
                                if 200 <= resp2.status_code < 300 and resp2.content:
                                    return resp2.content
                            except Exception as e:
                                logger.warning(
                                    f"audio download: CDN GET failed: {e}"
                                )
                    else:
                        probe_trace.append({
                            "path": path,
                            "status": resp.status_code,
                            "body": (resp.text or "")[:250],
                        })
                        logger.info(
                            f"audio download: {path} returned "
                            f"{resp.status_code} body={(resp.text or '')[:200]!r}"
                        )
            except Exception as e:
                probe_trace.append({"path": path, "error": str(e)[:200]})
                logger.warning(f"audio download: {path} exception: {e}")
                continue

    # Attempt 1/3: fall back to the raw URL GET if we have one.
    if audio_url:
        try:
            headers = {}
            if WAAPI_TOKEN and "waapi" in audio_url:
                headers["Authorization"] = f"Bearer {WAAPI_TOKEN}"
            async with ServerHttpClient(timeout=30) as client_http:
                resp = await client_http.get(audio_url, headers=headers)
                if 200 <= resp.status_code < 300 and resp.content:
                    return resp.content
                probe_trace.append({
                    "path": "direct_get",
                    "status": resp.status_code,
                    "size":   len(resp.content),
                })
                logger.warning(
                    f"audio download: direct GET returned "
                    f"{resp.status_code} size={len(resp.content)}"
                )
        except Exception as e:
            probe_trace.append({"path": "direct_get", "error": str(e)[:200]})
            logger.warning(f"audio download: direct GET exception: {e}")

    # Persist full probe trace so the debug endpoint surfaces what each
    # WaAPI endpoint responded with. Best-effort — we don't block on this.
    try:
        await db.whatsapp_audio_probe.insert_one({
            "message_id":  message_id,
            "trace":       probe_trace,
            "received_at": datetime.now(timezone.utc),
        })
    except Exception:
        pass

    logger.error(f"audio download: all strategies failed msg_id={message_id}")
    return None


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe a voicenote via OpenAI Whisper.

    No `language` hint is sent — Whisper auto-detects, which handles
    English, Yiddish, Spanish, Hebrew, etc. without forcing the wrong
    decoder. Previously we hard-coded 'yi' (Yiddish) which made
    English voicenotes return empty and the agent hallucinate a
    'text only' reply.

    A 'prompt' hint is still useful: it biases Whisper toward
    construction vocabulary + the handful of languages our crews
    actually speak.
    """
    if not OPENAI_API_KEY:
        logger.warning("Transcription skipped — OPENAI_API_KEY not set")
        return ""
    if not audio_bytes or len(audio_bytes) < 200:
        logger.warning(f"Transcription skipped — audio too small ({len(audio_bytes) if audio_bytes else 0} bytes)")
        return ""
    try:
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        files_payload = {
            "file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
            "model": (None, "whisper-1"),
            # Biasing vocabulary, NOT a language lock.
            "prompt": (
                None,
                "NYC construction site radio: permits, violations, "
                "DOB, inspection, plumbing, electrical, mechanical, "
                "sheet A-101, ME-401, P-1, hoist, scaffold, riser.",
            ),
        }
        async with ServerHttpClient(timeout=60) as client_http:
            resp = await client_http.post(url, headers=headers, files=files_payload)
            if resp.status_code != 200:
                logger.error(
                    f"Whisper transcription failed status={resp.status_code} "
                    f"body={resp.text[:300]}"
                )
                return ""
            text = (resp.json().get("text") or "").strip()
            if not text:
                logger.warning(
                    f"Whisper returned empty text for {len(audio_bytes)}B audio"
                )
            return text
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return ""


async def classify_intent(message: str) -> Optional[str]:
    """Classify a WhatsApp message intent. String match first, GPT-4o-mini fallback."""
    text = message.lower().strip()
    # Quick string-match rules
    if any(kw in text for kw in ["who on site", "who is on site", "who's on site", "whose on site", "workers on site"]):
        return "who_on_site"
    if any(kw in text for kw in ["dob status", "dob update", "violations", "dob check"]):
        return "dob_status"
    if any(kw in text for kw in ["open items", "open observations", "punch list", "uncorrected"]):
        return "open_items"
    # Material delivery receipt
    material_delivery_keywords = ["delivery", "arrived", "received", "delivered", "dropped off",
                                   "on site now", "material here", "truck came", "receipt",
                                   "shortage", "missing", "short", "only got"]
    if any(kw in text for kw in material_delivery_keywords):
        return "material_receipt"
    # Material status query
    material_status_keywords = ["material status", "what's missing", "delivery status",
                                 "outstanding materials", "what do we need", "materials needed"]
    if any(kw in text for kw in material_status_keywords):
        return "material_status"
    # GPT-4o-mini fallback
    if not OPENAI_API_KEY:
        return None
    try:
        import json as _json
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "temperature": 0,
            "max_tokens": 30,
            "messages": [
                {"role": "system", "content": (
                    "Classify the user message into one of these intents: "
                    "who_on_site, dob_status, open_items, material_receipt, material_status, or none. "
                    "Reply with ONLY the intent label."
                )},
                {"role": "user", "content": message},
            ],
        }
        async with ServerHttpClient(timeout=10) as client_http:
            resp = await client_http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            label = resp.json()["choices"][0]["message"]["content"].strip().lower()
            if label in ("who_on_site", "dob_status", "open_items", "material_receipt", "material_status"):
                return label
            return None
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        return None


# ---------- intent handlers ----------

async def _handle_who_on_site(
    project_id: str,
    trade: Optional[str] = None,
    company: Optional[str] = None,
) -> str:
    """Return formatted worker list on site. Optionally filter by trade or company."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": today_start},
        "status": "checked_in",
        "is_deleted": {"$ne": True},
    }).to_list(500)

    def _match(ci: dict) -> bool:
        if trade:
            t = (ci.get("worker_trade") or ci.get("trade") or "").lower()
            if trade.lower() not in t:
                return False
        if company:
            c = (ci.get("worker_company") or ci.get("company") or ci.get("company_name") or "").lower()
            if company.lower() not in c:
                return False
        return True

    filtered = [ci for ci in checkins if _match(ci)]
    n = len(filtered)

    filter_desc = ""
    if trade and company:
        filter_desc = f" ({trade} at {company})"
    elif trade:
        filter_desc = f" ({trade})"
    elif company:
        filter_desc = f" ({company})"

    if not filtered:
        if trade or company:
            return f"No {trade or company} workers checked in on site today{filter_desc}."
        return "No workers currently checked in on site."

    # Group by company (or trade if filtering by company)
    if company:
        by_key: Dict[str, list] = {}
        for ci in filtered:
            key = (ci.get("worker_trade") or ci.get("trade") or "General").title()
            by_key.setdefault(key, []).append(ci.get("worker_name", "Unknown"))
        lines = [f"*{n} on site today{filter_desc}:*"]
        for k, names in sorted(by_key.items()):
            lines.append(f"\n_{k}_ ({len(names)}):")
            for nm in sorted(names):
                lines.append(f"  - {nm}")
    else:
        by_company: Dict[str, list] = {}
        for ci in filtered:
            co = ci.get("worker_company") or ci.get("company") or ci.get("company_name") or "Unknown"
            by_company.setdefault(co, []).append(ci.get("worker_name", "Unknown"))
        lines = [f"*{n} on site today{filter_desc}:*"]
        for co, names in sorted(by_company.items()):
            lines.append(f"\n_{co}_ ({len(names)}):")
            for nm in sorted(names):
                lines.append(f"  - {nm}")
    return "\n".join(lines)


async def _handle_list_workers(
    company_id: Optional[str],
    trade: Optional[str] = None,
    company: Optional[str] = None,
) -> str:
    """Return the full worker roster, optionally filtered by trade/company.
    Not limited to who's on site today — the full roster."""
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    workers = await db.workers.find(query).to_list(1000)

    def _match(w: dict) -> bool:
        if trade:
            t = (w.get("trade") or "").lower()
            if trade.lower() not in t:
                return False
        if company:
            c = (w.get("company") or "").lower()
            if company.lower() not in c:
                return False
        return True

    filtered = [w for w in workers if _match(w)]
    n = len(filtered)
    if not filtered:
        if trade or company:
            return f"No workers match filter ({trade or company})."
        return "No workers in the roster yet."

    filter_desc = ""
    if trade and company:
        filter_desc = f" — {trade} at {company}"
    elif trade:
        filter_desc = f" — {trade}"
    elif company:
        filter_desc = f" — {company}"

    by_trade: Dict[str, list] = {}
    for w in filtered:
        t = (w.get("trade") or "General").title()
        by_trade.setdefault(t, []).append(w.get("name", "Unknown"))
    lines = [f"*{n} workers{filter_desc}:*"]
    for t, names in sorted(by_trade.items()):
        lines.append(f"\n_{t}_ ({len(names)}):")
        for nm in sorted(names):
            lines.append(f"  - {nm}")
    return "\n".join(lines)


async def _handle_dob_status(project_id: str) -> str:
    """Return project DOB info summary."""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        return "Project not found."

    # BIN lives at the top level as nyc_bin in current schema; fall back to
    # the legacy dob_config.bin_number for older records.
    bin_number = (
        project.get("nyc_bin")
        or (project.get("dob_config") or {}).get("bin_number")
        or "N/A"
    )
    bbl = project.get("bbl") or project.get("nyc_bbl") or (project.get("dob_config") or {}).get("bbl") or ""

    lines = [f"*DOB Status for {project.get('name') or 'this project'}*"]
    lines.append(f"BIN: {bin_number}")
    if bbl:
        lines.append(f"BBL: {bbl}")

    # Recent violations — be defensive about None-valued fields (Mongo stores
    # explicit None, and None[:80] raises TypeError).
    recent = await db.dob_logs.find({
        "project_id": project_id,
        "record_type": "violation",
    }).sort("detected_at", -1).to_list(5)
    if recent:
        lines.append(f"\nRecent violations ({len(recent)}):")
        for v in recent:
            desc = v.get("description") or v.get("raw_dob_id") or v.get("violation_number") or "(no details)"
            desc = str(desc)[:80]
            lines.append(f"  - {desc}")
    else:
        lines.append("\nNo recent violations on file.")
    return "\n".join(lines)


async def _handle_open_items(project_id: str) -> str:
    """Return uncorrected observations from today's daily log."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = await db.daily_logs.find_one({"project_id": project_id, "date": today_str})
    if not log:
        return "No daily log found for today."
    observations = log.get("observations", [])
    open_obs = [o for o in observations if not o.get("corrected")]
    if not open_obs:
        return "All observations corrected for today."
    lines = [f"*Open items today ({len(open_obs)}):*"]
    for i, o in enumerate(open_obs, 1):
        desc = o.get("description", o.get("note", "No description"))[:100]
        lines.append(f"  {i}. {desc}")
    return "\n".join(lines)


# ---------- material tracking ----------

async def _detect_material_request(message_body: str, project_id: str, company_id: str) -> Optional[dict]:
    """Use GPT-4o-mini to detect if a message contains a material request."""
    if not message_body or len(message_body.strip()) < 15:
        return None
    if not OPENAI_API_KEY:
        return None

    try:
        async with ServerHttpClient(timeout=15) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": """You analyze construction site WhatsApp messages to detect material requests.
A material request is when someone asks for construction materials to be ordered or delivered.
Examples: "need 200 sheets of drywall", "order 50 bags of concrete", "we're out of 2x4s", "bring 10 boxes of screws tomorrow"
NOT material requests: status updates, questions, greetings, photos, scheduling.

If this is a material request, return JSON:
{"is_request": true, "items": [{"name": "material name", "quantity": number_or_null, "unit": "unit_or_null", "specs": "any specifications"}], "trade": "framing|plumbing|electrical|concrete|drywall|general", "needed_by": "date_mentioned_or_null"}

If NOT a material request, return: {"is_request": false}"""},
                        {"role": "user", "content": message_body}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                result = json.loads(content)
                if result.get("is_request"):
                    return result
    except Exception as e:
        logger.error(f"Material detection error: {e}")
    return None


async def _create_material_request(project_id: str, company_id: str, group_id: str,
                                     message_id: str, sender_phone: str, detection: dict) -> dict:
    """Create a material request document from detected request."""
    now = datetime.now(timezone.utc)

    # Duplicate detection: check for similar request from same group in last 24h
    recent = await db.material_requests.find_one({
        "project_id": project_id,
        "group_id": group_id,
        "status": {"$in": ["open", "partial"]},
        "created_at": {"$gte": now - timedelta(hours=24)}
    })
    if recent:
        # Check item overlap
        existing_names = {i["name"].lower() for i in recent.get("items", [])}
        new_names = {i["name"].lower() for i in detection.get("items", [])}
        overlap = len(existing_names & new_names)
        if overlap > 0 and overlap >= len(new_names) * 0.5:
            logger.info(f"Duplicate material request detected for project {project_id}, skipping")
            return recent

    items = []
    for item in detection.get("items", []):
        items.append({
            "name": item.get("name", "Unknown"),
            "quantity_requested": item.get("quantity"),
            "quantity_received": 0,
            "unit": item.get("unit"),
            "specs": item.get("specs"),
            "status": "pending",
        })

    doc = {
        "project_id": project_id,
        "company_id": company_id,
        "group_id": group_id,
        "message_id": message_id,
        "requested_by": sender_phone,
        "requested_by_trade": detection.get("trade", "general"),
        "needed_by_date": detection.get("needed_by"),
        "items": items,
        "status": "open",
        "delivery_receipts": [],
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }

    result = await db.material_requests.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def _send_material_confirmation(group_id: str, request_doc: dict):
    """Send formatted confirmation to WhatsApp group."""
    items = request_doc.get("items", [])
    trade = request_doc.get("requested_by_trade", "general").title()
    needed_by = request_doc.get("needed_by_date")

    lines = [f"\U0001f4cb *Material Request Logged* ({trade})"]
    if needed_by:
        lines.append(f"\U0001f4c5 Needed by: {needed_by}")
    lines.append("")
    for i, item in enumerate(items, 1):
        qty = f"{item['quantity_requested']} {item.get('unit') or 'units'}" if item.get('quantity_requested') else "TBD"
        specs = f" \u2014 {item['specs']}" if item.get('specs') else ""
        lines.append(f"{i}. {item['name']}: {qty}{specs}")
    lines.append("")
    lines.append("_Reply with delivery info when materials arrive._")

    message = "\n".join(lines)
    await send_whatsapp_message(group_id, message)


async def _handle_material_receipt(project_id: str, message_body: str, sender_phone: str) -> str:
    """Reconcile a delivery receipt against open material requests."""
    if not project_id or not OPENAI_API_KEY:
        return "I couldn't process this delivery receipt. Please log it manually."

    # Get open/partial requests
    requests = await db.material_requests.find({
        "project_id": project_id,
        "status": {"$in": ["open", "partial"]},
        "is_deleted": {"$ne": True}
    }).to_list(20)

    if not requests:
        return "No open material requests found for this project."

    # Build outstanding items summary
    outstanding = []
    for req in requests:
        for item in req.get("items", []):
            if item["status"] in ("pending", "partial"):
                remaining = (item.get("quantity_requested") or 0) - (item.get("quantity_received") or 0)
                outstanding.append({
                    "request_id": str(req["_id"]),
                    "item_name": item["name"],
                    "quantity_remaining": remaining,
                    "unit": item.get("unit"),
                })

    if not outstanding:
        return "All material requests are fulfilled. No outstanding items."

    try:
        async with ServerHttpClient(timeout=15) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o",
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": f"""Match the delivery receipt against outstanding material requests.
Outstanding items: {json.dumps(outstanding)}
Return JSON: {{"matches": [{{"request_id": "id", "item_name": "name", "quantity_received": number}}], "unmatched": ["items not on any request"]}}"""},
                        {"role": "user", "content": message_body}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if resp.status_code != 200:
                return "Could not process delivery receipt. Please log manually."

            result = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logger.error(f"Delivery reconciliation error: {e}")
        return "Error processing delivery receipt. Please log manually."

    # Update MongoDB
    report_lines = ["\U0001f4e6 *Delivery Reconciliation*", ""]
    for match in result.get("matches", []):
        req_id = match.get("request_id")
        item_name = match.get("item_name")
        qty_received = match.get("quantity_received", 0)

        # Find and update the request
        for req in requests:
            if str(req["_id"]) == req_id:
                for item in req.get("items", []):
                    if item["name"].lower() == item_name.lower():
                        item["quantity_received"] = (item.get("quantity_received") or 0) + qty_received
                        if item.get("quantity_requested") and item["quantity_received"] >= item["quantity_requested"]:
                            item["status"] = "received"
                            report_lines.append(f"\u2705 {item_name}: {qty_received} received \u2014 *Complete*")
                        else:
                            remaining = (item.get("quantity_requested") or 0) - item["quantity_received"]
                            item["status"] = "partial"
                            report_lines.append(f"\u26a0\ufe0f {item_name}: {qty_received} received \u2014 {remaining} still needed")
                        break

                # Update overall request status
                statuses = [i["status"] for i in req.get("items", [])]
                if all(s == "received" for s in statuses):
                    req_status = "fulfilled"
                elif any(s in ("received", "partial") for s in statuses):
                    req_status = "partial"
                else:
                    req_status = "open"

                await db.material_requests.update_one(
                    {"_id": req["_id"]},
                    {"$set": {"items": req["items"], "status": req_status, "updated_at": datetime.now(timezone.utc)},
                     "$push": {"delivery_receipts": {"received_by": sender_phone, "message": message_body, "timestamp": datetime.now(timezone.utc), "matches": result.get("matches", [])}}}
                )
                break

    for unmatched in result.get("unmatched", []):
        report_lines.append(f"\u2753 {unmatched} \u2014 not on any open request")

    return "\n".join(report_lines)


async def _handle_project_info(project_id: str) -> str:
    """Return a short, human-readable summary of the project bound to this group."""
    if not project_id:
        return "Could not determine which project this group is linked to."
    try:
        project = await db.projects.find_one({"_id": to_query_id(project_id)})
    except Exception:
        project = None
    if not project:
        return "Project not found."

    name = project.get("name") or "(unnamed project)"
    address = project.get("address") or project.get("formatted_address") or "—"
    bin_ = project.get("nyc_bin") or project.get("bin") or ""
    bbl = project.get("bbl") or project.get("nyc_bbl") or ""
    # GC name: same canonical fallback chain as api_check_eligibility,
    # via _resolve_gc_legal_name in permit_renewal.py. Adds one
    # companies.find_one round-trip but matches semantics across
    # display (here) and eligibility-check input. Falls back to the
    # legacy project.gc_name field if the chain produces nothing,
    # preserving the prior display behavior on old project docs that
    # only carry that field.
    gc = ""
    try:
        from permit_renewal import _resolve_gc_legal_name
        company_for_gc = None
        company_id = project.get("company_id")
        if company_id:
            try:
                company_for_gc = await db.companies.find_one(
                    {"_id": to_query_id(company_id)}
                )
            except Exception:
                company_for_gc = None
        gc = _resolve_gc_legal_name(project, company_for_gc)
    except Exception:
        # Defensive — chat handler should never crash on a name lookup.
        gc = ""
    if not gc:
        gc = project.get("gc_name") or ""  # legacy field
    status = project.get("status") or "active"

    lines = [f"📍 *{name}*", address]
    if bin_:
        lines.append(f"BIN: {bin_}")
    if bbl:
        lines.append(f"BBL: {bbl}")
    if gc:
        lines.append(f"GC: {gc}")
    lines.append(f"Status: {status}")
    return "\n".join(lines)


APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://app.levelog.com")


def _permit_renewal_deep_link(project_id: str, permit_id: str) -> str:
    """Deep link to the mobile/web renewal screen with the permit preselected.

    The frontend reads ?permit=<id> and auto-selects. If the user isn't
    signed in, the login screen preserves the return URL so they land
    back on renewal after auth.
    """
    return (
        f"{APP_BASE_URL.rstrip('/')}/project/{project_id}/permit-renewal"
        f"?permit={permit_id}"
    )


def _permit_matches_hint(permit: dict, hint: str) -> int:
    """Score a permit 0-N against a free-text hint. Higher = better match."""
    if not hint:
        return 0
    h = hint.lower()
    score = 0
    for field, weight in (
        ("permit_type",    4),
        ("permit_subtype", 3),
        ("job_number",     5),
        ("raw_dob_id",     2),
        ("work_type",      1),
    ):
        v = str(permit.get(field) or "").lower()
        if not v:
            continue
        if h == v:
            score += weight * 3
        elif h in v or v in h:
            score += weight
        else:
            # Token overlap
            htoks = set(re.findall(r"[a-z0-9]+", h))
            vtoks = set(re.findall(r"[a-z0-9]+", v))
            if htoks & vtoks:
                score += max(1, weight // 2)
    # Well-known abbreviation expansions
    aliases = [
        ("pl", "plumbing"), ("me", "mechanical"), ("el", "electrical"),
        ("sp", "sprinkler"), ("mh", "mechanical"), ("gc", "general construction"),
        ("dm", "demolition"), ("eq", "equipment"), ("sh", "sheeting"),
        ("fn", "foundation"), ("nb", "new building"), ("fo", "footing"),
        ("ea", "earthwork"),
    ]
    ptype = str(permit.get("permit_type") or "").lower()
    psub = str(permit.get("permit_subtype") or "").lower()
    for short, long in aliases:
        if (short in h and (long in ptype or long in psub)) or \
           (long in h and (short == ptype or short == psub)):
            score += 5
    # "Soonest" / "expiring" preference handled by caller
    return score


async def _handle_start_permit_renewal(
    project_id: str, group_id: str, sender: str, permit_hint: str
) -> str:
    """Resolve permit → check eligibility → send deep link or blocker list."""
    if not project_id:
        return "Could not determine which project this is."

    # Load the same active-permit set the user sees.
    try:
        permits = await db.dob_logs.find({
            "project_id":  project_id,
            "record_type": "permit",
            "is_deleted":  {"$ne": True},
        }).to_list(200)
    except Exception as e:
        logger.error(f"start_permit_renewal load failed: {e}", exc_info=True)
        return "Couldn't load permits right now — please try again in a minute."

    now = datetime.now(timezone.utc)
    active_status = {"permit issued", "issued", "active", "pre-filed"}

    def _parse_iso(v):
        if not v:
            return None
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        try:
            s = str(v).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    active = []
    for p in permits:
        stat = str(p.get("permit_status") or "").strip().lower()
        exp = _parse_iso(p.get("expiration_date"))
        if stat in active_status and (exp is None or exp > now):
            active.append((p, exp))

    if not active:
        return "No active permits on file for this project — nothing to renew."

    # "Soonest" / "expiring" shortcut
    hint_low = (permit_hint or "").lower()
    prefer_soonest = any(
        w in hint_low for w in ("soonest", "expiring", "most urgent", "first")
    )

    if prefer_soonest:
        active.sort(key=lambda x: (x[1] or datetime.max.replace(tzinfo=timezone.utc)))
        top = active[0]
        scored = [(100, top[0], top[1])]
    else:
        scored = [
            (_permit_matches_hint(p, permit_hint), p, exp) for p, exp in active
        ]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda x: -x[0])

    if not scored:
        # Nothing matched the hint — list the options.
        lines = [f"I don't see a permit matching '{permit_hint}'. Active permits:"]
        active.sort(key=lambda x: (x[1] or datetime.max.replace(tzinfo=timezone.utc)))
        for p, exp in active[:10]:
            label = f"{p.get('permit_type') or 'Permit'}"
            if p.get("permit_subtype"):
                label += f"/{p['permit_subtype']}"
            if p.get("job_number"):
                label += f" — {p['job_number']}"
            if exp:
                label += f" (exp {exp.strftime('%Y-%m-%d')})"
            lines.append(f"  • {label}")
        lines.append("Which one should I renew?")
        return "\n".join(lines)

    # If top two scores are tied or very close, ask for clarification.
    if len(scored) >= 2 and scored[1][0] >= max(scored[0][0] - 1, 1):
        lines = [f"Multiple permits match '{permit_hint}':"]
        for score, p, exp in scored[:5]:
            label = f"{p.get('permit_type') or 'Permit'}"
            if p.get("permit_subtype"):
                label += f"/{p['permit_subtype']}"
            if p.get("job_number"):
                label += f" — {p['job_number']}"
            if exp:
                label += f" (exp {exp.strftime('%Y-%m-%d')})"
            lines.append(f"  • {label}")
        lines.append("Which one? Reply with the job number or full type.")
        return "\n".join(lines)

    target, target_exp = scored[0][1], scored[0][2]
    permit_id = str(target["_id"])

    # Eligibility — call the existing engine. Needs company name.
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    company_doc = None
    if project and project.get("company_id"):
        company_doc = await db.companies.find_one(
            {"_id": to_query_id(project["company_id"])}
        )
    company_name = (company_doc or {}).get("name") or ""

    try:
        from backend.permit_renewal import check_renewal_eligibility
        elig = await check_renewal_eligibility(
            db, permit_id, project_id, company_name,
            company_id=str(project["company_id"]) if project else None,
        )
    except Exception as e:
        logger.error(f"eligibility check failed: {e}", exc_info=True)
        deep = _permit_renewal_deep_link(project_id, permit_id)
        return (
            f"Couldn't run the automatic eligibility check, but I can take you "
            f"straight to the renewal screen:\n{deep}"
        )

    ptype = target.get("permit_type") or "Permit"
    sub = target.get("permit_subtype")
    label = f"{ptype}" + (f"/{sub}" if sub else "")
    job = target.get("job_number") or ""
    exp_str = target_exp.strftime("%Y-%m-%d") if target_exp else "unknown"
    days_left = elig.days_until_expiry if elig and elig.days_until_expiry is not None else None

    deep = _permit_renewal_deep_link(project_id, permit_id)

    header = f"*Renewal — {label}*"
    if job:
        header += f" (Job {job})"
    header += f"\nExpires {exp_str}" + (f" ({days_left}d left)" if days_left is not None else "")

    if not elig.eligible and elig.blocking_reasons:
        bullets = "\n".join(f"  • {r}" for r in elig.blocking_reasons[:6])
        extra = ""
        if elig.insurance_flags:
            extra = "\n\nInsurance to update first:\n" + "\n".join(
                f"  • {f}" for f in elig.insurance_flags[:5]
            )
        return (
            f"{header}\n\n"
            f"Not ready to auto-renew yet:\n{bullets}{extra}\n\n"
            f"Open the renewal screen anyway to review and file manually:\n{deep}"
        )

    if elig.insurance_not_entered:
        return (
            f"{header}\n\n"
            f"Ready to renew, but I don't have insurance on file for this company yet.\n"
            f"Add General Liability, Workers Comp, and Disability in Settings, "
            f"then tap here:\n{deep}"
        )

    return (
        f"{header}\n\n"
        f"Eligible to renew — all checks pass. Open the renewal form:\n{deep}"
    )


async def _handle_active_permits(project_id: str) -> str:
    """Return currently-active DOB permits for this project.

    Reads from db.dob_logs where record_type='permit' and the permit is
    issued/active and not expired. Groups by permit type/subtype.
    """
    if not project_id:
        return "Could not determine project."
    try:
        permits = await db.dob_logs.find({
            "project_id":  project_id,
            "record_type": "permit",
            "is_deleted":  {"$ne": True},
        }).sort("expiration_date", -1).to_list(100)
    except Exception as e:
        logger.error(f"active_permits query failed: {e}", exc_info=True)
        return "Couldn't load permit data right now — please try again in a minute."

    if not permits:
        return (
            "No permits on file for this project in our DB. "
            "If you expect permits, run a DOB sync from the project page."
        )

    # Classify: active if status is issued-like and not past expiration.
    now = datetime.now(timezone.utc)
    active_status = {"permit issued", "issued", "active", "pre-filed"}

    def _parse_iso(v):
        if not v:
            return None
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        try:
            s = str(v).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    active = []
    for p in permits:
        stat = str(p.get("permit_status") or "").strip().lower()
        exp = _parse_iso(p.get("expiration_date"))
        if stat in active_status and (exp is None or exp > now):
            active.append((p, exp))

    if not active:
        total = len(permits)
        return f"No active permits right now (found {total} on file, all expired or closed)."

    # Sort active by expiration (soonest first)
    active.sort(key=lambda x: (x[1] or datetime.max.replace(tzinfo=timezone.utc)))

    # Pre-compute days-to-expiry so the LLM composing the final reply
    # can't hallucinate "no permits expiring soon" when one clearly is.
    # Bucket: <=30 days = URGENT, <=90 = soon, >90 = ok.
    expiring_30 = [a for a in active if a[1] and (a[1] - now).days <= 30]
    expiring_90 = [a for a in active if a[1] and 30 < (a[1] - now).days <= 90]

    header_bits = [f"*Active permits ({len(active)}):*"]
    if expiring_30:
        header_bits.append(
            f"⚠️ {len(expiring_30)} permit(s) expiring within 30 days — renewal needed now."
        )
    if expiring_90:
        header_bits.append(
            f"🟡 {len(expiring_90)} permit(s) expiring within 31–90 days."
        )
    lines = header_bits
    for p, exp in active[:15]:
        ptype = p.get("permit_type") or "Permit"
        sub = p.get("permit_subtype") or ""
        job = p.get("job_number") or p.get("raw_dob_id") or ""
        label = f"{ptype}" + (f"/{sub}" if sub else "")
        if job:
            label += f" — Job {job}"
        if exp:
            days = (exp - now).days
            if days <= 30:
                flag = f" ⚠️ *{days}d left*"
            elif days <= 90:
                flag = f" 🟡 {days}d left"
            else:
                flag = ""
            label += f" (exp {exp.strftime('%Y-%m-%d')}{flag})"
        lines.append(f"  • {label}")
    if len(active) > 15:
        lines.append(f"…and {len(active) - 15} more.")
    return "\n".join(lines)


async def _handle_material_status(project_id: str) -> str:
    """Return formatted status of open/partial material requests."""
    if not project_id:
        return "Could not determine project."

    requests = await db.material_requests.find({
        "project_id": project_id,
        "status": {"$in": ["open", "partial"]},
        "is_deleted": {"$ne": True}
    }).to_list(20)

    if not requests:
        return "\u2705 No outstanding material requests."

    lines = ["\U0001f4ca *Outstanding Materials*", ""]
    for req in requests:
        trade = req.get("requested_by_trade", "general").title()
        lines.append(f"*{trade}* (requested {req.get('created_at', '').strftime('%m/%d') if isinstance(req.get('created_at'), datetime) else 'N/A'}):")
        for item in req.get("items", []):
            if item["status"] in ("pending", "partial"):
                remaining = (item.get("quantity_requested") or 0) - (item.get("quantity_received") or 0)
                unit = item.get("unit") or "units"
                if item["status"] == "pending":
                    lines.append(f"  \u23f3 {item['name']}: {remaining} {unit} needed")
                else:
                    lines.append(f"  \u26a0\ufe0f {item['name']}: {remaining} {unit} still needed")
        lines.append("")

    return "\n".join(lines)


async def _find_project_for_contact(contact: dict) -> Optional[str]:
    """Return first assigned project ID for a contact, or None."""
    user_id = contact.get("user_id")
    if not user_id:
        return None
    user = await db.users.find_one({"_id": to_query_id(user_id)})
    if not user:
        return None
    assigned = user.get("assigned_projects", [])
    if assigned:
        return str(assigned[0])
    # Fallback: first active project in company
    company_id = user.get("company_id")
    if company_id:
        proj = await db.projects.find_one({"company_id": company_id, "is_deleted": {"$ne": True}})
        if proj:
            return str(proj["_id"])
    return None


# ---------- inbound processing ----------

# ==================== WHATSAPP BOT CONFIG ====================

def _default_bot_config() -> dict:
    """Default bot_config assigned to newly linked or migrated groups.

    IMPORTANT: daily_summary_enabled defaults to False everywhere. Old groups
    without a config pick up these defaults via the startup migration so they
    do NOT start receiving unsolicited summaries on first deploy of this code.
    Admins must explicitly opt in per group.
    """
    return {
        "bot_enabled": True,  # master kill switch — False short-circuits everything
        "daily_summary_enabled": False,
        "daily_summary_time": "17:00",       # 24h EST HH:MM
        "daily_summary_days": [1, 2, 3, 4, 5],  # ISO weekday Mon=1 Sun=7
        "checklist_extraction_enabled": False,
        "checklist_frequency": "daily",       # "daily" | "on_demand"
        "checklist_time": "16:00",
        "features": {
            "who_on_site": True,
            "dob_status": True,
            "open_items": True,
            "material_detection": True,
            # Default ON — the tool is the bot's whole reason to know the
            # plans, and it's gated behind the indexing pipeline anyway.
            "plan_queries": True,
            # "strict" (default): bot only replies when explicitly addressed
            #   via @levelog / @<botphone> / "levelog ..." prefix, OR to a
            #   voice note / follow-up text sent within 3 min of the sender's
            #   own explicit @levelog message (the session window).
            # "loose": also triggers on intent-starter words like "who",
            #   "show", "what", "where", "find" anywhere in the message.
            "address_mode": "strict",
        },
        "cross_project_summary": False,
    }


_WHATSAPP_CONFIG_KEYS = {
    "bot_enabled", "daily_summary_enabled", "daily_summary_time",
    "daily_summary_days", "checklist_extraction_enabled",
    "checklist_frequency", "checklist_time", "features",
    "cross_project_summary",
}
_WHATSAPP_FEATURE_KEYS = {
    "who_on_site", "dob_status", "open_items", "material_detection", "plan_queries",
    "address_mode",
}
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


async def _whatsapp_send_log_try_mark(
    group_id: str, job_type: str, sent_date_est: str
) -> bool:
    """Attempt to record that a scheduled send happened for this group/job/date.

    Returns True if the caller should proceed with the send (first attempt today).
    Returns False if a duplicate key error fires (already sent) -- caller must skip.

    Backed by a MongoDB unique compound index. Survives server restarts. No
    in-memory state anywhere.
    """
    from pymongo.errors import DuplicateKeyError
    try:
        await db.whatsapp_send_log.insert_one({
            "group_id": group_id,
            "job_type": job_type,
            "sent_date_est": sent_date_est,
            "created_at": datetime.now(timezone.utc),
        })
        return True
    except DuplicateKeyError:
        return False


async def run_whatsapp_startup_migrations():
    """Idempotent startup migrations for the WhatsApp feature set.

    Safe to call on every server boot. Runs:
    - Set default bot_config on any existing whatsapp_groups without one.
    - Create whatsapp_send_log collection + unique compound + TTL index.
    - Create whatsapp_checklists compound index (used in Sprint 2).
    - Create document_page_index unique compound (used in Sprint 3).
    """
    try:
        # Migration 1 — backfill bot_config on legacy group docs
        result = await db.whatsapp_groups.update_many(
            {"bot_config": {"$exists": False}},
            {"$set": {"bot_config": _default_bot_config()}},
        )
        if result.modified_count:
            logger.info(
                f"WhatsApp migration: backfilled bot_config on "
                f"{result.modified_count} existing group doc(s)"
            )

        # Migration 2 — send_log dedup collection
        await db.whatsapp_send_log.create_index(
            [("group_id", 1), ("job_type", 1), ("sent_date_est", 1)],
            unique=True,
            name="whatsapp_send_log_unique",
        )
        # 45-day TTL so the collection doesn't grow forever
        await db.whatsapp_send_log.create_index(
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 45,
            name="whatsapp_send_log_ttl",
        )

        # Migration 3 — whatsapp_checklists indexes (Sprint 2 consumer)
        await db.whatsapp_checklists.create_index(
            [("project_id", 1), ("generated_at", -1)],
            name="checklists_by_project_recent",
        )
        await db.whatsapp_checklists.create_index(
            [("group_id", 1), ("generated_at", -1)],
            name="checklists_by_group_recent",
        )

        # Migration 4 — document_page_index unique compound (Sprint 3 consumer)
        await db.document_page_index.create_index(
            [("file_id", 1), ("page_number", 1)],
            unique=True,
            name="document_page_unique",
        )
        await db.document_page_index.create_index(
            [("project_id", 1), ("discipline", 1)],
            name="document_page_by_project_discipline",
        )
        # Migration 4b (plan-query v2): fast exact-match lookup on sheet
        # number per project. Alphanumeric sheet IDs ('A-301', 'ME-401')
        # are poorly served by vector search; regex / exact match on this
        # field always takes priority over semantic retrieval.
        await db.document_page_index.create_index(
            [("project_id", 1), ("sheet_number", 1)],
            name="document_page_by_sheet_number",
        )
        await db.document_page_index.create_index(
            [("project_id", 1), ("floor", 1)],
            name="document_page_by_floor",
        )

        # Migration 5 — whatsapp_conversation_state (Sprint 6 consumer).
        # One active draft per group; auto-expire via TTL on expires_at.
        await db.whatsapp_conversation_state.create_index(
            "group_id", unique=True, name="convo_state_by_group"
        )
        await db.whatsapp_conversation_state.create_index(
            "expires_at", expireAfterSeconds=0, name="convo_state_ttl"
        )
    except Exception as e:
        logger.warning(f"run_whatsapp_startup_migrations: {e}")


# ==================== SPRINT 3 — PLAN QUERY PIPELINE ====================

# Module-level concurrency guard so a first-sync of a project with 500 PDFs
# doesn't spawn 500 simultaneous indexers. Combined with the per-file page
# semaphore (size 5) the worst case is 3 files * 5 pages = 15 in-flight Qwen
# requests.
_PDF_INDEX_FILE_SEMAPHORE = asyncio.Semaphore(3)


_DISCIPLINE_PATTERNS = [
    ("AR", re.compile(r"\b(?:ar|arch|architectural)\b", re.I)),
    ("ME", re.compile(r"\b(?:me|mech|mechanical|hvac|mh)\b", re.I)),
    ("EL", re.compile(r"\b(?:el|elec|electrical)\b", re.I)),
    ("PL", re.compile(r"\b(?:pl|plmb|plumbing)\b", re.I)),
    ("SP", re.compile(r"\b(?:sp|sprk|sprinkler|fp|fire\s*protection)\b", re.I)),
    ("ST", re.compile(r"\b(?:st|str|strl|structural)\b", re.I)),
    ("GN", re.compile(r"\b(?:gn|gen|general|site|civil|cv)\b", re.I)),
]


def detect_discipline(filename: str) -> str:
    """Classify a drawing file name into an AEC discipline code.

    Checks the full filename + any path components. Case-insensitive.
    Returns 'other' when no pattern matches.
    """
    if not filename:
        return "other"
    # Split path components and filename into words to match
    raw = filename.replace("\\", "/")
    parts = [p for p in raw.split("/") if p]
    joined = " ".join(parts)
    for code, pat in _DISCIPLINE_PATTERNS:
        if pat.search(joined):
            return code
    return "other"


# ------------- Plan-query index prompts -------------
#
# The indexing prompt is intentionally verbose. Its output is the ONLY basis
# for the downstream embedding + semantic search, so anything missing here is
# permanently invisible to the query pipeline. Qwen-VL handles multi-section
# structured extraction well; keep the section headers stable so the parser
# fallback and human reviewers can grep it.
_PLAN_INDEX_PROMPT = (
    "You are indexing a NYC construction drawing for a searchable database "
    "used by field workers and general contractors. Your output will be the "
    "sole basis for answering technical questions about this sheet.\n\n"
    "Extract and return every piece of the following information exactly as "
    "it appears in the drawing. Do not paraphrase. Do not summarize. Quote "
    "all text verbatim. If a field is not present on this sheet, write NONE "
    "for that field. Be exhaustive — a field worker's safety depends on this "
    "data being complete.\n\n"
    "Return the answer with these exact labeled sections, one per line or "
    "bulleted beneath the label:\n"
    "SHEET_ID: the sheet number exactly as printed (examples: A-301, ME-401, S-102, PL-201)\n"
    "SHEET_TITLE: the full title as printed on the title block\n"
    "DISCIPLINE: Architectural | Structural | Mechanical | Electrical | Plumbing | Sprinkler | Civil | General\n"
    "FLOOR: every floor, level, or zone this sheet covers\n"
    "SPACES_AND_ROOMS: all room names, unit types, corridor labels, space identifiers\n"
    "DIMENSIONS: every explicit dimension callout, ceiling height, clear width, slab thickness, structural depth shown\n"
    "MATERIALS_AND_SPECS: every material, product name, gauge, thickness, fire rating, R-value, performance spec, keynote text verbatim "
    "(examples: 5/8\" Type X GWB, 3-5/8\" 20GA metal stud at 16\" OC, DensGlass Gold sheathing, R-19 batt insulation, 2-hour fire-rated assembly)\n"
    "CODE_REFS: Local Law citations, NYC Building Code sections, IBC refs, special inspection flags, fire-rating assembly numbers\n"
    "DETAIL_AND_SECTION_REFS: all detail bubbles, section cut markers, enlarged plan callouts with their reference numbers\n"
    "NOTES: all general notes, keynotes, and sheet-specific notes in full\n"
)


def _parse_plan_summary(text: str) -> dict:
    """Extract structured fields from a Qwen indexing summary.

    Section labels come from _PLAN_INDEX_PROMPT. Tolerant to minor label
    drift ('SHEET ID', 'Sheet_Id', 'Sheet ID:'). Unmatched sections get None.
    """
    out = {
        "sheet_number":  None,
        "sheet_title":   None,
        "discipline":    None,
        "floor":         None,
        "spaces":        None,
        "dimensions":    None,
        "materials":     None,
        "code_refs":     None,
        "detail_refs":   None,
        "notes":         None,
    }
    if not text:
        return out
    label_map = {
        "SHEET_ID":                  "sheet_number",
        "SHEETID":                   "sheet_number",
        "SHEET_TITLE":               "sheet_title",
        "SHEETTITLE":                "sheet_title",
        "DISCIPLINE":                "discipline",
        "FLOOR":                     "floor",
        "FLOOR_OR_LEVEL":            "floor",
        "SPACES_AND_ROOMS":          "spaces",
        "SPACES":                    "spaces",
        "DIMENSIONS":                "dimensions",
        "MATERIALS_AND_SPECS":       "materials",
        "MATERIALS":                 "materials",
        "CODE_REFS":                 "code_refs",
        "CODE_REFERENCES":           "code_refs",
        "DETAIL_AND_SECTION_REFS":   "detail_refs",
        "DETAIL_REFS":               "detail_refs",
        "DETAILS":                   "detail_refs",
        "NOTES":                     "notes",
    }
    # Split on label: at start of line. Use a tolerant regex that accepts
    # "Sheet ID:", "SHEET_ID:", "Sheet_Id -", etc.
    # Strategy: find all (label_norm, value) pairs by scanning for labeled
    # sections anchored at line starts.
    lines = text.splitlines()
    current_key = None
    current_buf: list = []
    def _flush():
        nonlocal current_key, current_buf
        if current_key and current_buf:
            val = "\n".join(current_buf).strip(" \t:-\n")
            if val and val.upper() != "NONE":
                out[current_key] = val
        current_key = None
        current_buf = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if current_key:
                current_buf.append("")
            continue
        m = re.match(r"^[*_\-\s]*([A-Za-z][A-Za-z _\-]+?)\s*[:\-–]\s*(.*)$", line)
        if m:
            label_raw = re.sub(r"[^A-Za-z]", "_", m.group(1).strip().upper()).strip("_")
            label_norm = re.sub(r"__+", "_", label_raw)
            if label_norm in label_map:
                _flush()
                current_key = label_map[label_norm]
                rest = m.group(2).strip(" -:\t")
                current_buf = [rest] if rest else []
                continue
        if current_key:
            current_buf.append(line)
    _flush()
    return out


async def _generate_embedding(text: str) -> Optional[list]:
    """Generate an OpenAI embedding (text-embedding-3-small, 1536 dim).

    Returns None on any failure — callers must tolerate missing embeddings.
    """
    if not OPENAI_API_KEY or not text:
        return None
    # OpenAI caps at 8192 tokens per input; truncate aggressively at char level.
    text = text.strip()[:20000]
    try:
        async with ServerHttpClient(timeout=30.0) as client_http:
            resp = await client_http.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": "text-embedding-3-small", "input": text},
            )
            if resp.status_code != 200:
                logger.warning(f"embedding API {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        logger.warning(f"embedding failed: {e}")
        return None


async def _upload_page_jpeg_to_r2(project_id: str, file_id: str,
                                    page_number: int, jpeg_bytes: bytes) -> str:
    """Store a per-page rendered JPEG to R2 at
    `plans/{project_id}/{file_id}/page_{N}.jpg` and return the key."""
    r2_key = f"plans/{project_id}/{file_id}/page_{page_number}.jpg"
    try:
        await asyncio.to_thread(
            _upload_to_r2, jpeg_bytes, r2_key, "image/jpeg"
        )
        return r2_key
    except Exception as e:
        logger.warning(f"page jpeg upload failed {r2_key}: {e}")
        return ""


def _is_sheet_number_query(s: str) -> bool:
    """Heuristic: does this token look like a sheet id (A-301, ME-401)?"""
    if not s:
        return False
    s = s.strip().upper()
    return bool(re.match(r"^[A-Z]{1,3}-?\d{1,4}[A-Z]?$", s))


async def _index_single_page(
    *,
    project_id: str,
    company_id: str,
    file_id: str,
    file_name: str,
    file_hash: str,
    page_number: int,
    discipline: str,
    page_text: str,
    page_image_bytes: Optional[bytes],
):
    """Index one page: Qwen summary + embedding + R2 JPEG storage.

    Extractable-text length is used as a rough gate for SPEC-only pages
    (walls-of-text with no drawing). Architectural drawings have long
    title blocks + keynote lists that can push text past 1000 chars
    while still being primarily VISUAL, so the threshold has to be set
    high enough to let those through. We also require the text to look
    paragraph-style (long lines) rather than labels-and-dimensions-style
    (short fragments).
    """
    now = datetime.now(timezone.utc)
    base_doc = {
        "project_id":    project_id,
        "company_id":    company_id,
        "file_id":       file_id,
        "file_name":     file_name,
        "file_hash":     file_hash,
        "discipline":    discipline,
        "page_number":   page_number,
        "indexed_at":    now,
        "index_version": 2,
    }

    # Spec-sheet detection: must be BOTH long (>5000 chars — a drawing with
    # annotations rarely gets that high) AND paragraph-style (avg non-empty
    # line length ≥40 chars). Architectural drawings have many short labels
    # and fail the second check even when they have lots of keynote text.
    stripped = (page_text or "").strip()
    is_spec = False
    if len(stripped) > 5000:
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if lines:
            avg_len = sum(len(ln) for ln in lines) / len(lines)
            is_spec = avg_len >= 40
    if is_spec:
        doc = dict(base_doc)
        doc.update({
            "sheet_number":       None,
            "sheet_title":        "[SPECIFICATION PAGE]",
            "floor":              None,
            "keywords":           [],
            "summary":            "",
            "spaces":             None,
            "dimensions":         None,
            "materials":          None,
            "code_refs":          None,
            "detail_refs":        None,
            "notes":              None,
            "embedding":          None,
            "page_jpeg_r2_key":   "",
            "is_spec_page":       True,
        })
        await db.document_page_index.update_one(
            {"file_id": file_id, "page_number": page_number},
            {"$set": doc},
            upsert=True,
        )
        return

    if not page_image_bytes:
        doc = dict(base_doc)
        doc.update({
            "sheet_number":       None,
            "sheet_title":        None,
            "floor":              None,
            "keywords":           [],
            "summary":            "",
            "embedding":          None,
            "page_jpeg_r2_key":   "",
            "is_spec_page":       False,
        })
        await db.document_page_index.update_one(
            {"file_id": file_id, "page_number": page_number},
            {"$set": doc},
            upsert=True,
        )
        return

    # 1. Upload per-page JPEG to R2 (used at query time so we don't re-render).
    page_jpeg_r2_key = await _upload_page_jpeg_to_r2(
        project_id, file_id, page_number, page_image_bytes
    )

    # 2. Qwen summary.
    summary_text = ""
    b64 = base64.b64encode(page_image_bytes).decode("ascii")
    try:
        async with ServerHttpClient(timeout=90.0) as client_http:
            resp = await client_http.post(
                f"{QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":       QWEN_MODEL,
                    "max_tokens":  1500,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": _PLAN_INDEX_PROMPT},
                        ],
                    }],
                },
            )
            if resp.status_code == 200:
                summary_text = resp.json()["choices"][0]["message"].get("content", "") or ""
            else:
                logger.warning(
                    f"Qwen index returned {resp.status_code} for "
                    f"{file_name} page {page_number}"
                )
    except Exception as e:
        logger.warning(
            f"Qwen index call failed for {file_name} page {page_number}: {e}"
        )

    parsed = _parse_plan_summary(summary_text)
    sheet_number = (parsed.get("sheet_number") or "").strip() or None
    sheet_title  = (parsed.get("sheet_title") or "").strip() or None
    floor        = (parsed.get("floor") or "").strip() or None

    # Build keywords from title + materials + spaces for fast keyword search.
    kw_source = " ".join(filter(None, [
        sheet_title, parsed.get("spaces"), parsed.get("materials"),
    ]))
    words = re.findall(r"[A-Za-z0-9\-]{3,}", kw_source.upper())
    # Drop short stopwords even after length filter
    _STOP = {"THE", "AND", "FOR", "PER", "WITH", "FROM", "THIS", "THAT", "ARE"}
    keywords = list({w for w in words if w not in _STOP})[:40]

    # 3. Embedding of the full summary text.
    embedding = await _generate_embedding(summary_text) if summary_text else None

    doc = dict(base_doc)
    doc.update({
        "sheet_number":       sheet_number,
        "sheet_title":        sheet_title,
        "floor":              floor,
        "keywords":           keywords,
        "summary":            summary_text,
        "spaces":             parsed.get("spaces"),
        "dimensions":         parsed.get("dimensions"),
        "materials":          parsed.get("materials"),
        "code_refs":          parsed.get("code_refs"),
        "detail_refs":        parsed.get("detail_refs"),
        "notes":              parsed.get("notes"),
        "embedding":          embedding,
        "page_jpeg_r2_key":   page_jpeg_r2_key,
        "is_spec_page":       False,
    })
    await db.document_page_index.update_one(
        {"file_id": file_id, "page_number": page_number},
        {"$set": doc},
        upsert=True,
    )


# Minimum rendering DPI for the plan-query pipeline. Construction drawings
# carry dimension callouts and material specs in tiny type; anything lower
# than 250 becomes unreadable by Qwen-VL. 300 for enlarged-detail sheets.
_PLAN_RENDER_DPI = 250
_PLAN_RENDER_DPI_DETAIL = 300


def _render_dpi_for(file_name: str, page_number: int) -> int:
    """Pick the DPI for rendering this page. Detail sheets get a bump."""
    low = (file_name or "").lower()
    if any(tok in low for tok in ("detail", "enlarged", "schedule", "d-")):
        return _PLAN_RENDER_DPI_DETAIL
    return _PLAN_RENDER_DPI


def _pdf_total_pages(pdf_bytes: bytes) -> int:
    try:
        from pypdf import PdfReader
        import io as _io
        return len(PdfReader(_io.BytesIO(pdf_bytes)).pages)
    except Exception:
        try:
            from PyPDF2 import PdfReader as LegacyReader  # type: ignore
            import io as _io
            return len(LegacyReader(_io.BytesIO(pdf_bytes)).pages)
        except Exception:
            # Last resort — render page 1 only to probe; returns 0 if render fails
            from pdf2image.pdf2image import pdfinfo_from_bytes
            try:
                info = pdfinfo_from_bytes(pdf_bytes)
                return int(info.get("Pages") or 0)
            except Exception:
                return 0


def _pdf_page_texts(pdf_bytes: bytes) -> List[str]:
    """Extract text per page. Returns [] if extraction unavailable."""
    try:
        from pypdf import PdfReader
        import io as _io
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        return [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        try:
            from PyPDF2 import PdfReader as LegacyReader  # type: ignore
            import io as _io
            reader = LegacyReader(_io.BytesIO(pdf_bytes))
            return [(p.extract_text() or "") for p in reader.pages]
        except Exception:
            return []


def _render_pdf_page(pdf_bytes: bytes, page_number: int, dpi: int) -> Optional[bytes]:
    """Render a single PDF page to JPEG bytes.

    We render one page at a time (first_page/last_page = page_number) so
    peak memory stays bounded — all-at-once renders OOM on large multi-page
    architectural sets on small Railway instances.
    """
    from pdf2image import convert_from_bytes
    import io as _io
    try:
        imgs = convert_from_bytes(
            pdf_bytes, dpi=dpi,
            first_page=page_number, last_page=page_number,
        )
        if not imgs:
            return None
        buf = _io.BytesIO()
        imgs[0].save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"render page {page_number} at {dpi} dpi failed: {e}")
        return None


def _pdf_pages_render_and_text(pdf_bytes: bytes, dpi: int = _PLAN_RENDER_DPI,
                                 file_name: str = ""):
    """Generator yielding (page_number, page_text, jpeg_bytes_or_None).

    Renders each page separately to bound memory. DPI may be overridden
    per-page by _render_dpi_for() based on filename heuristics.
    """
    total = _pdf_total_pages(pdf_bytes)
    if total <= 0:
        return
    texts = _pdf_page_texts(pdf_bytes)
    for page_num in range(1, total + 1):
        page_dpi = _render_dpi_for(file_name, page_num)
        jpeg_bytes = _render_pdf_page(pdf_bytes, page_num, page_dpi)
        text = texts[page_num - 1] if page_num - 1 < len(texts) else ""
        yield page_num, text, jpeg_bytes


async def _index_pdf_file(project_id: str, company_id: str, file_record: dict):
    """Download a PDF from R2 and index each page into document_page_index.

    Quiet no-op when QWEN_API_KEY isn't set (we still can't run text-only
    pre-filtering without risking blank entries, so the whole index skip
    is the safest behavior — the feature is off when key is absent).

    File-hash cache: if every page for this file_id is already indexed with
    a matching file_hash, skip entirely. This makes repeated Dropbox syncs
    essentially free.
    """
    if not QWEN_API_KEY:
        logger.info("Plan index skipped — QWEN_API_KEY not configured")
        return
    if not _r2_client or not file_record.get("r2_key"):
        logger.info(
            f"Plan index skipped (no R2 object) for "
            f"{file_record.get('name')}"
        )
        return

    async with _PDF_INDEX_FILE_SEMAPHORE:
        file_id = str(file_record.get("_id") or file_record.get("id") or "")
        file_name = file_record.get("name") or "unknown.pdf"
        r2_key = file_record["r2_key"]
        discipline = detect_discipline(file_name)

        # Download bytes
        try:
            obj = await asyncio.to_thread(
                _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=r2_key
            )
            pdf_bytes = obj["Body"].read()
        except Exception as e:
            logger.error(f"Plan index: R2 download failed for {r2_key}: {e}")
            return

        # Compute MD5 for hash-cache
        import hashlib
        file_hash = hashlib.md5(pdf_bytes).hexdigest()

        # Skip only if an existing entry has the same hash AND was produced
        # by the current index_version (2). Earlier versions used a minimal
        # prompt + no embedding and must be reprocessed.
        existing = await db.document_page_index.find_one({
            "file_id":      file_id,
            "file_hash":    file_hash,
            "index_version": {"$gte": 2},
        })
        if existing:
            logger.info(
                f"Plan index: {file_name} already indexed at current hash + "
                f"version — skipping"
            )
            return

        # Total page count up front so we can log progress.
        total = _pdf_total_pages(pdf_bytes)
        if total <= 0:
            logger.error(f"Plan index: page count = 0 for {file_name}")
            return
        texts = _pdf_page_texts(pdf_bytes) or ["" for _ in range(total)]

        # Render page-by-page (bounded memory) and fire Qwen in parallel with
        # a small semaphore so peak concurrency is 3 per file.
        sem = asyncio.Semaphore(3)

        async def _process_page(page_num: int):
            async with sem:
                dpi = _render_dpi_for(file_name, page_num)
                jpeg = await asyncio.to_thread(
                    _render_pdf_page, pdf_bytes, page_num, dpi
                )
                text = texts[page_num - 1] if page_num - 1 < len(texts) else ""
                await _index_single_page(
                    project_id=project_id,
                    company_id=company_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_hash=file_hash,
                    page_number=page_num,
                    discipline=discipline,
                    page_text=text,
                    page_image_bytes=jpeg,
                )

        # Chunked progress logging.
        CHUNK = 5
        for start in range(1, total + 1, CHUNK):
            end = min(start + CHUNK - 1, total)
            await asyncio.gather(*[_process_page(n) for n in range(start, end + 1)])
            logger.info(f"Plan index: {file_name}: {end}/{total}")

        logger.info(f"Plan index complete: {file_name} ({total} pages)")


async def _project_has_full_index(project_id: str) -> bool:
    """Return True when every PDF in the project's files has at least one
    document_page_index entry with a matching file_hash — used to skip
    re-sync indexing entirely when nothing has changed.
    """
    pdf_files = await db.project_files.find({
        "project_id": project_id,
        "name": {"$regex": r"\.pdf$", "$options": "i"},
    }).to_list(200)
    if not pdf_files:
        return True
    for fr in pdf_files:
        file_id = str(fr.get("_id"))
        if not fr.get("r2_key"):
            return False
        hit = await db.document_page_index.find_one({"file_id": file_id})
        if not hit:
            return False
    return True


# ==================== PLAN QUERY HANDLER ====================

PLAN_TRIGGER_VERBS = [
    "show me", "find the", "pull up", "send me",
    "where is", "what does", "which sheet", "get me", "open",
]
PLAN_DRAWING_NOUNS = [
    "plan", "elevation", "section", "detail", "schedule",
    "sheet", "drawing", "blueprint",
]


def _has_plan_query_trigger(text: str) -> bool:
    """Two-condition match: trigger verb AND drawing noun both present."""
    if not text:
        return False
    low = text.lower()
    has_verb = any(v in low for v in PLAN_TRIGGER_VERBS)
    if not has_verb:
        return False
    has_noun = any(n in low for n in PLAN_DRAWING_NOUNS)
    return has_noun


_PLAN_QUERY_PARSER_PROMPT = (
    "You are parsing a construction worker's WhatsApp message into a structured "
    "drawing search query for a NYC residential project.\n\n"
    "Return a JSON object with exactly these fields:\n"
    "  sheet_number: exact sheet ID if mentioned (A-301, ME-401, S-102), else null\n"
    "  discipline: one of AR, ST, ME, EL, PL, SP, GN — inferred from context, else null\n"
    "  floor: floor number or name if mentioned (3, roof, cellar, penthouse), else null\n"
    "  sheet_type: one of plan, elevation, section, detail, schedule, riser, diagram, else null\n"
    "  keywords: array of 2-4 key construction terms that would appear on a drawing\n"
    "  question: the verbatim question to answer from the drawing, or null if the user "
    "wants the image ('show me', 'pull up', 'send me', 'find the')\n"
    "  dob_route: true if the message is about permits, violations, or DOB status and "
    "should NOT be treated as a plan query; else false\n\n"
    "Spatial → floor/discipline inference (always apply before returning):\n"
    "- 'backyard', 'yard', 'rear yard', 'courtyard', 'garden' → floor='1', "
    "  likely discipline='PL' if drainage/sewer/water, else 'GN' for site/landscape.\n"
    "- 'front yard', 'front walk', 'sidewalk', 'street', 'curb' → floor='1', "
    "  discipline='GN'.\n"
    "- 'basement', 'cellar', 'sub-basement' → floor='cellar' or 'basement'.\n"
    "- 'rooftop', 'roof' → floor='roof'.\n"
    "- 'penthouse', 'PH' → floor='penthouse'.\n"
    "- 'ground floor', 'first floor', '1st floor', 'lobby' → floor='1'.\n"
    "- 'mezzanine' → floor='mezzanine'.\n\n"
    "Topic → discipline inference:\n"
    "- drain / drainage / sewer / trap / cleanout / waste line / water line / "
    "  hose bib / floor drain / roof drain → discipline='PL'.\n"
    "- HVAC / ductwork / AHU / VAV / boiler / chiller / supply grille / "
    "  return grille / diffuser → discipline='ME'.\n"
    "- outlet / receptacle / panel / feeder / circuit / switch / lighting / "
    "  riser (electrical) → discipline='EL'.\n"
    "- standpipe / fire pump / sprinkler head / zone valve → discipline='SP'.\n"
    "- beam / column / footing / slab / rebar / girder / shear wall → 'ST'.\n"
    "- partition / door / ceiling / finish / stair / elevator → 'AR'.\n"
    "- site work / landscape / retaining wall / fence / pavers → 'GN'.\n\n"
    "Keywords should always include the spatial noun (e.g. BACKYARD, ROOF, "
    "BASEMENT) AND the topic noun (DRAIN, DUCT, OUTLET) so keyword retrieval "
    "can match even if discipline inference is wrong.\n\n"
    "Routing rules:\n"
    "- 'show me / pull up / send me / find the' → question=null (image send).\n"
    "- 'what is / how thick / how many / where / any / is there / required / "
    "  what size / how far' or any '?' → extract as question.\n"
    "- Permit / violation / DOB keyword → set dob_route=true and leave other fields null.\n"
    "- Return ONLY valid JSON, no explanation."
)


async def _parse_plan_query(query: str) -> dict:
    """Parse a natural-language plan request into a structured search spec.

    Returns dict with keys: sheet_number, discipline, floor, sheet_type,
    keywords (list), question (str|None), dob_route (bool).
    """
    if not OPENAI_API_KEY or not query:
        return {}
    try:
        async with ServerHttpClient(timeout=20.0) as client_http:
            resp = await client_http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 250,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _PLAN_QUERY_PARSER_PROMPT},
                        {"role": "user",   "content": query},
                    ],
                },
            )
            if resp.status_code != 200:
                return {}
            import json as _json
            parsed = _json.loads(resp.json()["choices"][0]["message"]["content"])
            if not isinstance(parsed, dict):
                return {}
            # Normalize types
            if "keywords" in parsed and not isinstance(parsed["keywords"], list):
                parsed["keywords"] = []
            parsed["dob_route"] = bool(parsed.get("dob_route"))
            return parsed
    except Exception as e:
        logger.warning(f"plan query parse failed: {e}")
        return {}


def _cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity over two equal-length embedding vectors. 0 if malformed."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    import math
    return dot / (math.sqrt(na) * math.sqrt(nb))


async def _retrieve_plan_candidates(
    project_id: str,
    parsed: dict,
    original_query: str,
    limit: int = 3,
) -> list:
    """Retrieve top plan-page candidates for a query.

    Priority order:
      1. If parser returned a sheet_number, do an exact (case-insensitive)
         match on the sheet_number field and return it directly.
      2. Otherwise, run two parallel searches:
           a. Vector similarity against the summary embedding.
           b. Keyword match on sheet_title + keywords + materials.
         Merge via Reciprocal Rank Fusion and return top `limit`.

    Hard filters: discipline + floor (if extracted), and always exclude
    spec pages (is_spec_page=True or sheet_title='[SPECIFICATION PAGE]').
    """
    base_filter: Dict[str, Any] = {
        "project_id":   project_id,
        "is_spec_page": {"$ne": True},
        "sheet_title":  {"$ne": "[SPECIFICATION PAGE]"},
    }

    # Hard filters — normalize discipline to the 2-letter code stored in the
    # index ('ME', 'AR', 'ST', etc). The agent sometimes passes the full
    # word ('Mechanical') or alternate casing; match tolerantly.
    _DISC_ALIASES = {
        "AR": "AR", "A": "AR", "ARCH": "AR", "ARCHITECTURAL": "AR",
        "ST": "ST", "S": "ST", "STR": "ST", "STRUCTURAL": "ST",
        "ME": "ME", "M": "ME", "MECH": "ME", "MECHANICAL": "ME", "HVAC": "ME", "MH": "ME",
        "EL": "EL", "E": "EL", "ELEC": "EL", "ELECTRICAL": "EL",
        "PL": "PL", "P": "PL", "PLMB": "PL", "PLUMBING": "PL",
        "SP": "SP", "SPRK": "SP", "SPRINKLER": "SP", "FP": "SP",
        "GN": "GN", "GEN": "GN", "GENERAL": "GN", "CIVIL": "GN", "SITE": "GN",
    }
    raw_disc = (parsed.get("discipline") or "").strip().upper()
    disc = _DISC_ALIASES.get(raw_disc) or (raw_disc if len(raw_disc) == 2 else None)
    if disc:
        base_filter["discipline"] = disc
    floor = parsed.get("floor")
    if isinstance(floor, (int, float)):
        floor = str(int(floor))

    # ── 1. Sheet-number exact match ───────────────────────────────────────
    # Sheet numbers are often stamped with decimal subsheet suffixes
    # (M-200, M-200.00, A-301.1). If the user types the base id we want
    # all variants to hit. Pattern: start ^, optional trailing .digits, end.
    sheet_q = (parsed.get("sheet_number") or "").strip()
    if not sheet_q:
        for tok in re.findall(r"[A-Za-z]{1,3}-?\d{1,4}[A-Za-z]?", original_query or ""):
            if _is_sheet_number_query(tok):
                sheet_q = tok
                break
    if sheet_q:
        q_upper = sheet_q.upper()
        # Build up the set of prefixes to accept
        prefixes = {q_upper}
        m = re.match(r"^([A-Z]{1,3})-?(\d{1,4}[A-Z]?)(\.\d+)?$", q_upper)
        if m:
            prefixes.add(f"{m.group(1)}-{m.group(2)}")
            prefixes.add(f"{m.group(1)}{m.group(2)}")
            # Also accept the exact decimal form the user gave us
            if m.group(3):
                prefixes.add(f"{m.group(1)}-{m.group(2)}{m.group(3)}")
        # Regex: ^(PFX1|PFX2)(\.\d+)?$  — tolerate decimal subsheet
        pattern = (
            f"^({'|'.join(re.escape(p) for p in prefixes)})"
            r"(\.\d+)?$"
        )
        fq = dict(base_filter)
        fq["sheet_number"] = {"$regex": pattern, "$options": "i"}
        # Multiple hits possible when a family shares a base (M-200, M-200.1…);
        # prefer the shortest — it's the "most canonical" base sheet.
        hits = await db.document_page_index.find(fq).to_list(10)
        if hits:
            hits.sort(key=lambda p: len(p.get("sheet_number") or ""))
            return [hits[0]]
        # Fall through to full search if no exact match

    # ── 2. Load candidate pool + parallel search ──────────────────────────
    pool = await db.document_page_index.find(base_filter).limit(400).to_list(400)
    if not pool and base_filter.get("discipline"):
        # Discipline filter was too strict (e.g. user asked about "drains in
        # backyard" — parser tagged it PL, but the drainage is actually on
        # a site/GN sheet). Retry without discipline; floor/spec filters
        # stay in place.
        logger.info(
            f"plan retrieval: discipline={base_filter['discipline']} filter "
            f"returned empty pool, retrying without discipline filter"
        )
        relaxed = {k: v for k, v in base_filter.items() if k != "discipline"}
        pool = await db.document_page_index.find(relaxed).limit(400).to_list(400)
    if not pool:
        return []

    # Optional floor filter (soft — use regex on floor field + sheet_title)
    if floor:
        fr = _floor_regex(str(floor))
        if fr:
            pat = re.compile(fr, re.I)
            filtered = [
                p for p in pool
                if pat.search(str(p.get("floor") or ""))
                or pat.search(str(p.get("sheet_title") or ""))
            ]
            if filtered:
                pool = filtered

    # 2a. Vector similarity
    query_embedding = await _generate_embedding(original_query)
    vector_ranked = []
    if query_embedding:
        scored = []
        for p in pool:
            emb = p.get("embedding") or []
            sim = _cosine_similarity(query_embedding, emb)
            scored.append((sim, p))
        scored.sort(key=lambda x: -x[0])
        vector_ranked = [p for _s, p in scored if _s > 0.05]

    # 2b. Keyword match
    keywords = [str(k).upper() for k in (parsed.get("keywords") or []) if k]
    # Also split the raw query into keywords as a safety net
    extra_kws = re.findall(r"[A-Z][A-Z0-9\-]{2,}", (original_query or "").upper())
    keywords = list({*keywords, *extra_kws})
    keyword_ranked = []
    if keywords:
        scored_kw = []
        for p in pool:
            bag = " ".join(filter(None, [
                (p.get("sheet_number") or "").upper(),
                (p.get("sheet_title") or "").upper(),
                " ".join(p.get("keywords") or []).upper(),
                (p.get("materials") or "").upper(),
                (p.get("spaces") or "").upper(),
            ]))
            score = sum(1 for k in keywords if k in bag)
            if score > 0:
                scored_kw.append((score, p))
        scored_kw.sort(key=lambda x: -x[0])
        keyword_ranked = [p for _s, p in scored_kw]

    # ── 3. Reciprocal Rank Fusion ─────────────────────────────────────────
    # RRF constant k=60 (standard choice). Score = sum(1 / (k + rank)).
    K = 60
    rrf: Dict[str, dict] = {}
    scores: Dict[str, float] = {}
    for rank, p in enumerate(vector_ranked[:50], start=1):
        pid = str(p["_id"])
        rrf[pid] = p
        scores[pid] = scores.get(pid, 0) + 1.0 / (K + rank)
    for rank, p in enumerate(keyword_ranked[:50], start=1):
        pid = str(p["_id"])
        rrf[pid] = p
        scores[pid] = scores.get(pid, 0) + 1.0 / (K + rank)
    ordered = sorted(rrf.values(), key=lambda p: -scores[str(p["_id"])])
    return ordered[:limit]


def _floor_regex(val: str) -> str:
    """Build a safe regex for floor matching. Numeric floors require a word
    boundary + FLOOR context so '4' doesn't match '14TH FLOOR' or 'BASEMENT 4'.
    """
    v = (val or "").strip()
    if not v:
        return ""
    if v.isdigit():
        return rf"\b{v}(?:ST|ND|RD|TH)?\s+FLOOR\b"
    return rf"\b{re.escape(v)}\b"


SHOW_VERBS = ("show me", "pull up", "send me", "find the", "open", "get me", "display")


def _classify_plan_question(query: str) -> bool:
    """Return True if the user is asking a visual question about a drawing
    (VQA), False if they just want the image sent.

    Heuristic: VQA if the query starts with or prominently features a
    question word (what/how/where/why/which/when/is/are/does/do/can) AND
    does NOT start with a show-verb. Also any '?' with no show-verb.
    """
    if not query:
        return False
    low = query.strip().lower()
    # Explicit show-me requests → image send
    for v in SHOW_VERBS:
        if low.startswith(v):
            return False
    # Question words at start or after "@levelog"
    stripped = re.sub(r"^@?levelog\s*[:,-]?\s*", "", low)
    question_starters = (
        "what", "how", "where", "why", "which", "when",
        "is ", "are ", "does ", "do ", "can ", "could ", "would ",
    )
    for q in question_starters:
        if stripped.startswith(q):
            return True
    if "?" in low:
        return True
    return False


async def _fetch_page_jpeg(page_rec: dict) -> Optional[bytes]:
    """Fetch the pre-rendered JPEG for a page from R2.

    Indexed pages (v2+) store the R2 key at `page_jpeg_r2_key`. If missing
    (legacy index), fall back to on-the-fly render of the source PDF —
    slower, but keeps the query path working during the migration.
    """
    key = page_rec.get("page_jpeg_r2_key")
    if key and _r2_client and R2_BUCKET_NAME:
        try:
            obj = await asyncio.to_thread(
                _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=key
            )
            return obj["Body"].read()
        except Exception as e:
            logger.warning(f"R2 get page jpeg {key} failed: {e}")

    # Fallback: render live from the source PDF.
    file_id = page_rec.get("file_id")
    page_num = page_rec.get("page_number") or 1
    file_rec = None
    try:
        file_rec = await db.project_files.find_one({"_id": ObjectId(file_id)}) if file_id else None
    except Exception:
        file_rec = None
    if not file_rec or not file_rec.get("r2_key"):
        return None
    try:
        obj = await asyncio.to_thread(
            _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=file_rec["r2_key"]
        )
        pdf_bytes = obj["Body"].read()
    except Exception as e:
        logger.warning(f"source pdf fetch failed: {e}")
        return None
    dpi = _render_dpi_for(file_rec.get("name", ""), page_num)
    return await asyncio.to_thread(_render_pdf_page, pdf_bytes, page_num, dpi)


_VQA_PROMPT = (
    "You are answering a field question about a NYC construction drawing for "
    "a crew member on site with a phone in hand. They need a fast, specific answer.\n\n"
    "Sheet: {sheet_number} — {sheet_title}\n\n"
    "Question: {user_question}\n\n"
    "Answer format — follow exactly:\n"
    "- If the question is yes/no, START with 'Yes.' or 'No.' then the specifics.\n"
    "- If the question is 'how many / where / what size / how far', START with "
    "the count or value, THEN the dimension/location quoted from the drawing.\n"
    "- Quote dimensions, pipe sizes, materials, note numbers EXACTLY as shown "
    "(e.g. '2 floor drains, 4\\\" trap, 2'-10\\\" from building line', "
    "'3/4\\\" CW line per Note 4').\n"
    "- Maximum 40 words. No preamble. No 'based on the drawing' or 'according "
    "to this sheet'. Just the answer.\n"
    "- If multiple instances exist in different rooms/zones, list each with a "
    "1-word location tag (e.g. 'Kitchen: FD-1 at 3'-2\\\". Bath: FD-2 at wall.').\n"
    "- NEVER invent dimensions. Only quote what is literally printed on the sheet.\n"
    "- If this specific information is not shown on this sheet, reply with "
    "exactly this single word and nothing else: NOT_SHOWN_ON_SHEET"
)


async def _qwen_visual_qa(jpeg_bytes: bytes, question: str,
                           sheet_number: str, sheet_title: str) -> Optional[str]:
    """Ask Qwen2.5-VL a question about a single rendered plan page.
    Returns plain-text answer (possibly 'NOT_SHOWN_ON_SHEET'), or None on failure."""
    if not QWEN_API_KEY or not jpeg_bytes:
        return None
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    prompt = _VQA_PROMPT.format(
        sheet_number=sheet_number or "(unknown)",
        sheet_title=sheet_title or "(unknown)",
        user_question=question.strip(),
    )
    try:
        async with ServerHttpClient(timeout=90.0) as client_http:
            resp = await client_http.post(
                f"{QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": QWEN_MODEL,
                    "max_tokens": 300,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Qwen VQA returned {resp.status_code}")
                return None
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        logger.warning(f"Qwen VQA failed: {e}")
        return None


def _compress_jpeg_for_whatsapp(src_bytes: bytes, max_dim: int = 4800,
                                  max_size_bytes: int = 15 * 1024 * 1024,
                                  min_quality: int = 55) -> bytes:
    """Resize + re-encode a JPEG so it fits WaAPI's media delivery limits.

    Resolution doubled vs. the previous pass — max_dim 2400 → 4800,
    ceiling 4 MB → 15 MB (WaAPI's stated limit is ~16 MB; we leave
    a ~1 MB safety margin for multipart overhead). Quality ladder
    starts at 90 so the first-try encoding is noticeably sharper on
    construction drawings where dimension text was borderline
    legible at q=85.

    The iterative step-down preserves the original "best-effort,
    never block the send" behavior: we try q=90 → 85 → 80 → 75 → 70
    → 65 → min_quality and return the first encoding under the
    ceiling. If even the lowest quality is oversized, we still ship
    it (WaAPI may downscale further but at least the crew gets
    SOMETHING).
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(src_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Downscale if the larger side exceeds max_dim
        w, h = img.size
        longest = max(w, h)
        if longest > max_dim:
            scale = max_dim / longest
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        # Iteratively lower quality until we fit.
        for q in (90, 85, 80, 75, 70, 65, min_quality):
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_size_bytes:
                return data
        return data  # best-effort — even if over, ship it
    except Exception as e:
        logger.warning(f"jpeg compress failed: {e}")
        return src_bytes


async def _send_plan_image(
    group_id: str, page_rec: dict, caption: str,
) -> bool:
    """Fetch a page's pre-rendered JPEG from R2, downscale to WhatsApp-safe
    size, upload to R2 via presigned URL, and send-image to the group.
    Returns True on success."""
    sheet_ref = page_rec.get("sheet_number") or page_rec.get("_id")
    jpeg_src = await _fetch_page_jpeg(page_rec)
    if not jpeg_src:
        logger.warning(
            f"plan send: jpeg fetch returned empty for sheet={sheet_ref} "
            f"key={page_rec.get('page_jpeg_r2_key')}"
        )
        return False
    jpeg = await asyncio.to_thread(_compress_jpeg_for_whatsapp, jpeg_src)
    logger.info(
        f"plan send: jpeg ok for sheet={sheet_ref} "
        f"src_size={len(jpeg_src)} compressed_size={len(jpeg)}"
    )
    import uuid as _uuid
    temp_key = f"temp/whatsapp/{group_id}/{_uuid.uuid4()}.jpg"
    try:
        await asyncio.to_thread(_upload_to_r2, jpeg, temp_key, "image/jpeg")
        # WaAPI does a HEAD preflight. R2 presigned URLs are method-scoped
        # (signed GET returns 403 on HEAD), so we hand WaAPI a URL that
        # points to our own backend proxy — it handles HEAD+GET cleanly.
        tok = await _mint_temp_media_token(temp_key, "image/jpeg", ttl_seconds=3600)
        media_url = _public_temp_media_url(tok)
    except Exception as e:
        logger.warning(f"plan send: temp upload failed sheet={sheet_ref}: {e}")
        return False
    # WaAPI endpoint is `send-media` with a `mediaUrl` field (NOT send-image
    # with `image`, which returns 404). Discovered via probe-waapi-endpoints.
    try:
        async with ServerHttpClient(timeout=40.0) as client_http:
            resp = await client_http.post(
                f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/client/action/send-media",
                headers={
                    "Authorization": f"Bearer {WAAPI_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "chatId":   group_id,
                    "mediaUrl": media_url,
                    "caption":  caption,
                },
            )
            ok = 200 <= resp.status_code < 300
            body_preview = ""
            try:
                body_preview = resp.text[:400]
            except Exception:
                pass
            logger.info(
                f"plan send: WaAPI send-media status={resp.status_code} ok={ok} "
                f"sheet={sheet_ref} body={body_preview!r}"
            )
            if ok:
                # WaAPI sometimes returns 200 with {data: {status: 'error'}}.
                try:
                    j = resp.json()
                    if isinstance(j, dict):
                        inner = j.get("data") or {}
                        if isinstance(inner, dict) and inner.get("status") == "error":
                            logger.warning(
                                f"plan send: WaAPI data.status=error: {inner}"
                            )
                            return False
                except Exception:
                    pass
            return ok
    except Exception as e:
        logger.warning(f"WaAPI send-media exception sheet={sheet_ref}: {e}")
        return False


async def _handle_plan_query(project_id: str, group_id: str, query: str,
                              question: Optional[str] = None,
                              parsed_override: Optional[dict] = None) -> None:
    """End-to-end plan-query pipeline (spec-compliant v2).

    Flow:
      1. Immediate ack.
      2. Parse → structured spec (sheet_number, discipline, floor, keywords,
         question, dob_route). Bail to DOB handler if dob_route.
      3. Retrieve: sheet-number exact match first; else vector + keyword
         with Reciprocal Rank Fusion. Top 3 candidates.
      4. If parser says no question (show-me verb) → send top 1 or 2 images.
      5. If parser extracted a question → VQA loop through candidates.
    """
    if not QWEN_API_KEY:
        await send_whatsapp_message(group_id, "Plan queries are not configured.")
        return

    # 1. Immediate ack (needs to be fast — construction sites have poor signal)
    try:
        await send_whatsapp_message(group_id, "🔎 Checking the drawings…")
    except Exception:
        pass

    # 2. Parse — prefer the structured spec from the agent router if it's
    # available (avoids a second gpt-4o-mini call and a lossy re-parse of
    # the synth string).
    if isinstance(parsed_override, dict) and parsed_override:
        parsed = dict(parsed_override)
    else:
        parsed = await _parse_plan_query(query)
    if parsed.get("dob_route"):
        # Parser flagged this as a DOB/permits question — route to dob_status.
        txt = await _handle_dob_status(project_id)
        await send_whatsapp_message(group_id, txt)
        return

    # `question` param from the agent-router overrides parser's question —
    # except the agent often hallucinates a question for "show me" phrases
    # where the user clearly wants the image, not an answer. Check for
    # show-verb prefix in BOTH the synth query AND the agent's question
    # (agent frequently echoes the user's full "show me..." utterance into
    # the question slot). If either looks like a show-verb request, force
    # image-send mode.
    def _looks_like_show_verb(s: str) -> bool:
        s = (s or "").strip().lower()
        return any(s.startswith(v) for v in SHOW_VERBS)

    if _looks_like_show_verb(query) or _looks_like_show_verb(question or ""):
        effective_question = None
    else:
        effective_question = (question or "").strip() or parsed.get("question")
        if effective_question and effective_question.strip().lower() in ("null", "none", ""):
            effective_question = None
        if not effective_question and _classify_plan_question(query):
            effective_question = query.strip()

    # 3. Retrieve
    candidates = await _retrieve_plan_candidates(
        project_id, parsed, query, limit=3
    )
    if not candidates:
        await send_whatsapp_message(
            group_id,
            "Couldn't find a matching sheet in the indexed drawings. "
            "Try a sheet number (A-301, ME-401) or a description like "
            "'4th floor mechanical plan'. If your plans are new, make sure "
            "they've finished indexing in the app.",
        )
        return

    # 4a. Image-send path (parser said user wants the image, no question)
    if not effective_question:
        # Send top 1-2 candidates.
        sent_any = False
        for i, rec in enumerate(candidates[:2]):
            sheet_number = rec.get("sheet_number") or "Sheet"
            sheet_title  = rec.get("sheet_title")  or "Construction Drawing"
            caption = f"{sheet_number} — {sheet_title}"
            ok = await _send_plan_image(group_id, rec, caption)
            if ok:
                sent_any = True
            else:
                # Text fallback if image send fails
                await send_whatsapp_message(
                    group_id,
                    f"Found: {caption}. Open it in the Levelog app under Plans & Files.",
                )
            if i + 1 < min(2, len(candidates)):
                await asyncio.sleep(1.2)
        if not sent_any:
            logger.info(
                f"plan query image send: all {len(candidates[:2])} candidates failed"
            )
        return

    # 4b. VQA path — iterate candidates, stop on first real answer.
    # On success we send BOTH the short text answer AND the sheet image so
    # the crew can verify the answer against the drawing in one message.
    for rec in candidates:
        try:
            sheet_number = rec.get("sheet_number") or "Sheet"
            sheet_title  = rec.get("sheet_title")  or "Construction Drawing"
            jpeg = await _fetch_page_jpeg(rec)
            if not jpeg:
                continue
            answer = await _qwen_visual_qa(
                jpeg, effective_question, sheet_number, sheet_title,
            )
            if not answer or "NOT_SHOWN_ON_SHEET" in answer.upper():
                continue
            # Got an answer — format with sheet citation per spec.
            reply_text = f"*{sheet_number}* — {sheet_title}\n\n{answer}"
            await send_whatsapp_message(group_id, reply_text)
            # Follow up with the drawing image so the crew has visual
            # reference. Silent failure is fine — they already have the
            # answer text.
            try:
                await asyncio.sleep(0.6)
                await _send_plan_image(
                    group_id, rec, f"{sheet_number} — {sheet_title}",
                )
            except Exception as e:
                logger.warning(
                    f"plan image send after VQA failed sheet={sheet_number}: {e}"
                )
            return
        except Exception as e:
            logger.warning(f"VQA attempt failed for {rec.get('sheet_number')}: {e}")
            continue

    # All candidates exhausted — per spec, send the top image and note that
    # the answer couldn't be confirmed directly.
    top = candidates[0]
    top_sheet = top.get("sheet_number") or "Sheet"
    top_title = top.get("sheet_title")  or "Construction Drawing"
    await send_whatsapp_message(
        group_id,
        f"Couldn't confirm an answer from the indexed drawings. Sending the "
        f"closest match: *{top_sheet}* — {top_title}",
    )
    await _send_plan_image(group_id, top, f"{top_sheet} — {top_title}")


# ==================== SPRINT 4 — AGENTIC INTENT ROUTER ====================

_BOT_ADDRESS_SOFT_TRIGGERS = [
    "who", "show", "how many", "how much", "what", "where", "find", "pull", "open",
    "dob", "violation", "punch", "open items", "material", "delivery",
    "create checklist", "make checklist", "new checklist", "add checklist",
    "assign", "done ",
]


def _jid_digits(jid: str) -> str:
    """Return just the digits from a WhatsApp JID like '15165494475@c.us' or
    '153906327875707@lid'. Empty string for unknown/empty input."""
    if not jid:
        return ""
    # Drop the @domain suffix, then strip anything non-digit.
    head = jid.split("@", 1)[0]
    return re.sub(r"\D", "", head)


_LEARNED_BOT_LIDS: set = set()


def _learn_bot_lid(lid_digits: str) -> None:
    """Remember a LID we've seen WhatsApp route to/from our bot.

    Call this when we observe a webhook with fromMe=true whose author
    is a @lid JID — that author IS the bot's LID. Cached in-process so
    subsequent webhooks get matched even if WAAPI_BOT_LID isn't set.
    Survives restarts only if WAAPI_BOT_LID is configured.
    """
    if lid_digits and len(lid_digits) >= 10:
        _LEARNED_BOT_LIDS.add(lid_digits)


def _bot_identifier_digits() -> list:
    """All digit-strings we recognize as the bot.

    WhatsApp gives the bot two separate IDs:
      - its E.164 phone number (what you'd dial) — WAAPI_DISPLAY_NUMBER
      - its LID (a random ~15-digit identifier used in mentions and some
        group events) — WAAPI_BOT_LID

    Native @mentions in modern WhatsApp Web reference the LID, NOT the
    phone number, so matching by phone alone misses real @mentions.
    Also accepts LIDs we've auto-learned from outbound (fromMe=true)
    webhooks at runtime — saves having to reconfigure if WhatsApp ever
    rotates the LID.
    """
    out = []
    phone = re.sub(r"\D", "", os.environ.get("WAAPI_DISPLAY_NUMBER", "") or "")
    if phone:
        out.append(phone)
    lid = re.sub(r"\D", "", os.environ.get("WAAPI_BOT_LID", "") or "")
    if lid:
        out.append(lid)
    out.extend(_LEARNED_BOT_LIDS)
    return out


def _digits_match_bot(digits: str, bot_ids: Optional[list] = None) -> bool:
    """Case-insensitive digit-suffix match against any configured bot id."""
    if not digits:
        return False
    ids = bot_ids if bot_ids is not None else _bot_identifier_digits()
    for bot_id in ids:
        if not bot_id:
            continue
        # Exact equality first (ideal for LID which is opaque),
        # then last-10 suffix to tolerate country-code variants on phone numbers.
        if digits == bot_id:
            return True
        if len(bot_id) >= 10 and len(digits) >= 10 and digits[-10:] == bot_id[-10:]:
            return True
    return False


def _has_explicit_bot_mention(
    body: str,
    bot_phone_digits: str,  # kept for backwards compat; prefer _bot_identifier_digits()
    mentioned_jids: Optional[list] = None,
) -> bool:
    """Returns True iff the bot was explicitly addressed.

    Matches (any of):
      - WhatsApp native @mention: the bot's JID (phone or LID) appears in
        mentioned_jids. Modern clients use @lid here.
      - Bare '@<digits>' token in the body that matches bot phone or LID.
        (some vendors don't populate mentionedJidList.)
      - Literal text '@levelog' or 'levelog ' prefix (typed fallback).
    """
    # Build the set of bot identifiers — union of phone + LID + the legacy
    # `bot_phone_digits` arg the call site passed in.
    bot_ids = _bot_identifier_digits()
    if bot_phone_digits and bot_phone_digits not in bot_ids:
        bot_ids.append(bot_phone_digits)

    # 1. Native @-mention via JID list (the primary, correct path)
    if mentioned_jids:
        for jid in mentioned_jids:
            if _digits_match_bot(_jid_digits(str(jid)), bot_ids):
                return True

    if not body:
        return False
    low = body.strip().lower()

    # 2. Bare @<digits> token in the body text (WhatsApp renders the
    #    mention as a styled pill, but the raw body carries '@<digits>').
    for token in re.findall(r"@[\w\d]+", low):
        digits = re.sub(r"\D", "", token)
        if _digits_match_bot(digits, bot_ids):
            return True

    # 3. Literal text fallback — people will still type '@Levelog' in
    # contexts where the native @mention is lost (web paste, some 3rd-party
    # clients, or just habit).
    if low.startswith("@levelog") or low.startswith("levelog ") or low == "levelog":
        return True
    if "@levelog" in low:
        return True

    return False


# Key for the short-lived "sender just addressed the bot" session. When the
# sender tags @levelog with text, we mark them active for BOT_SESSION_TTL
# seconds — follow-up voice notes / short text replies from the same sender
# within that window are also routed to the agent without requiring another
# explicit mention. This matches how people naturally interact with the bot:
# "@levelog who's on site" → (bot replies) → voice note "also show me the roof"
BOT_SESSION_TTL_SECONDS = 180  # 3 minutes


async def _mark_bot_session(group_id: str, sender: str) -> None:
    """Record that `sender` just explicitly addressed the bot in this group.

    Subsequent messages from the same sender within BOT_SESSION_TTL_SECONDS
    are treated as bot-addressed. Uses whatsapp_conversation_state with a
    TTL index so rows auto-expire.
    """
    try:
        exp = datetime.now(timezone.utc) + timedelta(seconds=BOT_SESSION_TTL_SECONDS)
        await db.whatsapp_conversation_state.update_one(
            {"kind": "bot_session", "group_id": group_id, "sender": sender},
            {"$set": {
                "kind":       "bot_session",
                "group_id":   group_id,
                "sender":     sender,
                "expires_at": exp,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.debug(f"mark_bot_session failed: {e}")


async def _is_in_bot_session(group_id: str, sender: str) -> bool:
    """True if the sender has an active session with the bot in this group."""
    try:
        row = await db.whatsapp_conversation_state.find_one({
            "kind":     "bot_session",
            "group_id": group_id,
            "sender":   sender,
        })
        if not row:
            return False
        exp = row.get("expires_at")
        if not exp:
            return False
        exp_aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=timezone.utc)
        return exp_aware > datetime.now(timezone.utc)
    except Exception:
        return False


async def _is_bot_addressed(
    body: str,
    bot_phone_digits: str,
    is_voice: bool,
    *,
    group_id: str = "",
    sender: str = "",
    mode: str = "strict",
    quoted_body: str = "",
    mentioned_jids: Optional[list] = None,
    quoted_mentioned_jids: Optional[list] = None,
) -> bool:
    """Decide whether this message should route through the agent.

    Modes:
      strict (default, recommended):
        - Text: requires an explicit @levelog / levelog / @<botphone> mention,
          OR is a reply to a bot message, OR is from a sender in an active
          bot session (they just @mentioned within 3 min).
        - Voice: only when quoting a bot message, or when the sender has an
          active bot session, or when the quoted text itself mentions
          @levelog.

      loose (legacy):
        - Voice always routes; text routes on any intent-starter word.
    """
    # Explicit mention — always True in either mode
    if _has_explicit_bot_mention(body, bot_phone_digits, mentioned_jids):
        if group_id and sender:
            await _mark_bot_session(group_id, sender)
        return True

    # Quoted/reply context: the bot was mentioned in the message this one
    # is replying to (either via native @mention JID or literal text).
    if _has_explicit_bot_mention(quoted_body, bot_phone_digits, quoted_mentioned_jids):
        if group_id and sender:
            await _mark_bot_session(group_id, sender)
        return True

    if mode == "loose":
        # Legacy behavior — any voice, or any soft-trigger word
        if is_voice:
            return True
        if body:
            low = body.strip().lower()
            for t in _BOT_ADDRESS_SOFT_TRIGGERS:
                if t in low:
                    return True
        return False

    # Strict mode from here down
    if group_id and sender and await _is_in_bot_session(group_id, sender):
        # Sender recently addressed the bot — route follow-ups (text or voice)
        # through the agent so "@levelog who's on site" → "voice: also show me
        # the roof" works naturally.
        return True

    return False


# Tool schema for the GPT-4o-mini agent
_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "who_on_site",
            "description": (
                "Return the workers currently checked in on site today. "
                "Optionally filter by trade (e.g. 'carpenter', 'electrician', 'framer') "
                "or by subcontractor company name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trade":   {"type": "string", "description": "Trade filter, e.g. 'carpenter'"},
                    "company": {"type": "string", "description": "Subcontractor company filter"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workers",
            "description": (
                "Return the full roster of workers for the project's company, optionally "
                "filtered. Use this when the user asks about workers in general ('how many "
                "carpenters do we have'), not who is currently on site."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trade":   {"type": "string"},
                    "company": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dob_status",
            "description": "Return DOB status, permits, and recent violations for the project.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_items",
            "description": (
                "Return open / uncorrected / outstanding items from today's daily jobsite "
                "log (punch list, to-do items, unresolved issues, safety findings that still "
                "need correction). Use for phrases like 'open items', 'outstanding items', "
                "'what's still open', 'punch list', 'to-do list', 'unresolved issues', "
                "'anything open', 'what's pending'. Do NOT use for construction drawings "
                "— that's query_plan. Do NOT use for DOB permits — that's active_permits."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "active_permits",
            "description": (
                "List currently-active DOB permits on the project — GC, DM (demolition), "
                "EW (equipment/work), PL (plumbing), EL (electrical), MH (mechanical), "
                "SP (sprinkler), etc. Use for 'active permits', 'what permits are open', "
                "'show me permits', 'permit status', 'is the GC permit active', 'permits "
                "expiring', or any question about issued / non-expired DOB job filings. Do "
                "NOT use for violations — violations are in dob_status."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "material_status",
            "description": "Return outstanding material requests for the project.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_plan",
            "description": (
                "Look up a construction drawing. Use for requests about PLANS, DRAWINGS, "
                "ELEVATIONS, SECTIONS, DETAILS, SCHEDULES, or SHEETS — typically phrased "
                "'show me...', 'pull up...', 'find the...', 'what does the X sheet say', "
                "or naming a sheet number like 'A-101' / 'ME-401' / 'S-2'. Do NOT use this "
                "for checklist/punch items (that's open_items), for people (that's "
                "who_on_site), or for materials (that's material_status). Pass the user's "
                "original question so the plan pages can be visually analyzed (e.g. "
                "'what's the thickness of the exterior wall?'). If the user just wants the "
                "sheet shown, pass question=null."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "discipline":   {"type": "string", "description": "AR|ME|EL|PL|SP|ST|GN"},
                    "floor":        {"type": "string"},
                    "sheet_type":   {"type": "string", "description": "plan|elevation|section|detail|schedule"},
                    "sheet_number": {"type": "string", "description": "e.g. ME-401"},
                    "keywords":     {"type": "array", "items": {"type": "string"}},
                    "question":     {"type": "string", "description": "The user's question to answer from the drawing"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_info",
            "description": (
                "Return basic information about the project linked to this group — "
                "name, address, NYC BIN/BBL, GC name, and active permit status. "
                "Use for questions like 'what's the address', 'what project is this', "
                "'what's the BIN', or 'how many projects do I have' (answers with this "
                "project; the bot is scoped to one project per group)."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_permit_renewal",
            "description": (
                "Start a DOB permit renewal for a specific permit. Call this when the "
                "user says 'renew the plumbing permit', 'start renewal for PL', "
                "'yes renew that one', 'renew B00995273-S1'. Resolves a free-text "
                "permit hint (permit type, subtype, job number, or ordinal like "
                "'first one') to a single permit record, runs eligibility checks "
                "(insurance coverage, license status, expiration window), then "
                "either surfaces blockers or sends the user a direct deep link "
                "to the Levelog renewal screen pre-loaded with that permit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "permit_hint": {
                        "type": "string",
                        "description": (
                            "User's free-text identifier for the permit: permit type "
                            "(e.g. 'plumbing', 'PL', 'mechanical'), subtype, job "
                            "number like 'B00995273-S1', ordinal like 'first' / "
                            "'the plumbing one', or 'the one expiring soonest'."
                        ),
                    },
                },
                "required": ["permit_hint"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_checklist",
            "description": (
                "Begin a multi-turn flow to create an action-item checklist. Use this when "
                "the user says 'create checklist', 'make checklist', or lists items they "
                "want assigned. Parse out the items from the message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text":     {"type": "string"},
                                "category": {"type": "string", "description": "safety|materials|coordination|inspection|other"},
                            },
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        },
    },
]


_AGENT_SYSTEM_PROMPT_BASE = (
    "You are Levelog Assistant — a WhatsApp bot for a NYC GC/expediter who needs "
    "a smart, proactive teammate in their project group chat. Act like the "
    "project manager's right hand: brief, specific, and always one step ahead.\n\n"
    "CAPABILITIES (via tools):\n"
    "  • Active permits + who's expiring + renewal (active_permits, start_permit_renewal)\n"
    "  • DOB violations + complaints + 311 + BIN (dob_status)\n"
    "  • Open items / punch list / materials (open_items, material_status)\n"
    "  • Crew roster + who's on site (list_workers, who_on_site)\n"
    "  • Project metadata — address/BIN/BBL (project_info)\n"
    "  • Construction drawings visual Q&A + image send (query_plan)\n"
    "  • Checklist assignment flow (start_checklist)\n\n"
    "ROUTING (pick based on the current message, not history):\n"
    "  • 'permit', 'active permits', 'PL/ME/EL/SP permit', 'which permits expire' → "
    "    active_permits. Never query_plan for these.\n"
    "  • 'renew <permit>', 'start renewal', 'yes renew', 'renew the plumbing one' → "
    "    start_permit_renewal with permit_hint.\n"
    "  • 'violation', 'DOB status', 'complaints', '311', 'BIN' → dob_status.\n"
    "  • 'open items', 'punch list', 'to-do', 'outstanding' → open_items.\n"
    "  • 'who's on site', 'how many workers', 'trade count' → who_on_site.\n"
    "  • 'list workers', 'all carpenters', 'roster' → list_workers.\n"
    "  • 'materials', 'deliveries', 'on order' → material_status.\n"
    "  • 'address', 'BIN', 'BBL', 'project info' → project_info.\n"
    "  • 'plan', 'drawing', 'sheet', elevation/section/detail/schedule, "
    "    'show me A-101/ME-401', any question about what's shown on a drawing → "
    "    query_plan. ONLY for visual drawings.\n"
    "  • 'create checklist' → start_checklist.\n\n"
    "PROACTIVE NEXT-STEP DOCTRINE — this is what makes you feel human:\n"
    "After every tool call, look at the result and offer the obvious next action "
    "as a 1-line question. The user should rarely have to ask for the follow-up.\n"
    "  • active_permits returned ⚠️ flags → end with: 'Want me to start renewal "
    "    for <permit>?'\n"
    "  • dob_status returned open violations → end with: 'Want the filing details "
    "    or a checklist for fixing these?'\n"
    "  • query_plan sent a sheet → end with: 'Need a specific measurement or "
    "    detail from it?'\n"
    "  • material_status shows missing items → end with: 'Want me to create a "
    "    follow-up checklist for the sub?'\n"
    "  • start_permit_renewal returned insurance blockers → end with: 'Want "
    "    the direct Settings link to upload insurance?'\n"
    "Never append a next-step question when the user's message was ALREADY "
    "answering your previous one. Don't pester.\n\n"
    "MULTI-STEP REASONING:\n"
    "If a single user message needs two tools (e.g. 'any permits expiring and do "
    "we have insurance coverage for the renewal?'), call both and combine results "
    "in one reply. The tool system runs them in parallel when possible.\n\n"
    "PERMIT RENEWAL FLOW:\n"
    "When the user says yes/confirm/renew after you suggested a renewal, call "
    "start_permit_renewal with the permit they implied (latest ⚠️ from your prior "
    "turn). The tool returns either a deep-link URL the user can tap to open the "
    "Levelog renewal screen, a blocker list with the link anyway, or a missing-info "
    "prompt. Pass through whatever the tool says verbatim — the link MUST appear "
    "in your reply so the user can tap it.\n\n"
    "CLARIFICATION DISCIPLINE:\n"
    "Only ask a clarifying question when: (a) a permit/sheet/worker identifier is "
    "truly ambiguous after a tool result, or (b) renewal needs data not in the DB. "
    "Never ask 'which permit?' when there's only one active permit matching.\n\n"
    "DATA TRUST:\n"
    "Tool output for permits includes '⚠️ Nd left' flags. When the user asks "
    "'expiring in next N days' or 'need renewal', count permits whose days-left ≤ N "
    "from the tool output. Never say 'no permits expiring' if the output has any "
    "⚠️ or 🟡 flag. Trust tool numbers over your own date arithmetic.\n\n"
    "DRAWING DISCIPLINE:\n"
    "NYC sheet prefixes: AR/A=Architectural, ST/S=Structural, ME/M=Mechanical, "
    "EL/E=Electrical, PL/P=Plumbing, SP=Sprinkler, GN=General. "
    "Spatial terms map to discipline + floor: 'backyard/rear yard' → floor=1, "
    "discipline=PL if drainage else GN; 'rooftop' → floor=roof; 'basement/cellar' "
    "→ floor=cellar. For 'show me <sheet>' call query_plan with best-guess args — "
    "never ask the user to rephrase a drawing request.\n\n"
    "STYLE:\n"
    "Keep replies under 80 words unless listing many items. Use the tool's exact "
    "numbers, dates, job numbers — don't round or summarize them away. Never "
    "invent data that wasn't returned. When a link is in the tool output, keep "
    "it intact — that URL is how the user takes the next action."
)

_AGENT_NOREPLY_CLAUSE = (
    " If the user's message is off-topic (casual chatter between workers not directed at you), "
    "respond with the single word NOREPLY and no other text."
)

_AGENT_EXPLICIT_CLAUSE = (
    " The user just addressed you explicitly with '@levelog' or the bot's phone mention. "
    "This message is definitely for you. You MUST call a tool OR give a direct text reply — "
    "never respond NOREPLY for an explicitly-addressed message. If you don't know which tool "
    "fits, make your best guess and try."
)


# ==================== SPRINT 6 — INTERACTIVE CHECKLIST CREATION ====================

async def _get_checklist_candidates(
    company_id: Optional[str], project_id: str, limit: int = 40
) -> list:
    """Return the list of people who can be assigned a checklist item.

    Mix of:
      - Company admins / owners / CPs (users with a role)
      - Workers in the roster (db.workers) for this company
    Each entry: {id, kind: 'user'|'worker', name, trade, company}.
    """
    out = []

    # Users
    try:
        uq: Dict[str, Any] = {"is_deleted": {"$ne": True}}
        if company_id:
            uq["company_id"] = company_id
        users = await db.users.find(uq, {"password": 0}).to_list(200)
        for u in users:
            role = (u.get("role") or "").lower()
            if role not in ("admin", "owner", "cp", "superintendent"):
                continue
            out.append({
                "id":      str(u.get("_id")),
                "kind":    "user",
                "name":    u.get("name") or u.get("full_name") or u.get("email") or "Unknown",
                "trade":   (role or "").title(),
                "company": u.get("company_name") or "",
            })
    except Exception:
        pass

    # Workers
    try:
        wq: Dict[str, Any] = {"is_deleted": {"$ne": True}}
        if company_id:
            wq["company_id"] = company_id
        workers = await db.workers.find(wq).to_list(200)
        for w in workers:
            out.append({
                "id":      str(w.get("_id")),
                "kind":    "worker",
                "name":    w.get("name") or "Unknown",
                "trade":   (w.get("trade") or "").title(),
                "company": w.get("company") or "",
            })
    except Exception:
        pass

    # De-dup by (kind, id)
    seen = set()
    deduped = []
    for c in out:
        key = (c["kind"], c["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    return deduped[:limit]


def _format_candidates_message(
    items: list, candidates: list, max_candidates: int = 8
) -> str:
    """Compose the bot's 'who should handle each item' prompt."""
    lines = [f"📝 Got {len(items)} item{'s' if len(items) != 1 else ''} for a checklist:"]
    for idx, it in enumerate(items[:10], 1):
        lines.append(f"  {idx}. {it.get('text', '')}")
    lines.append("")
    lines.append("Who should I assign each to? Reply like:")
    lines.append('  "1: Anthony, 2: Carlos, 3: skip"')
    lines.append("")
    lines.append("*Candidates:*")
    for c in candidates[:max_candidates]:
        trade = c.get("trade") or ""
        co = c.get("company") or ""
        tail = []
        if trade: tail.append(trade)
        if co:    tail.append(co)
        suffix = f" ({', '.join(tail)})" if tail else ""
        lines.append(f"  • {c['name']}{suffix}")
    if len(candidates) > max_candidates:
        lines.append(f"  … and {len(candidates) - max_candidates} more (use full names)")
    lines.append("")
    lines.append('Or reply "cancel" to discard.')
    return "\n".join(lines)


async def _handle_start_checklist(
    project_id: str, group_id: str, items: list, sender: str,
    company_id: Optional[str] = None,
) -> str:
    """Sprint 6: start the interactive checklist creation flow.

    Saves a conversation state with draft items + candidate list, then returns
    a prompt asking the user to assign each item."""
    items = [i for i in (items or []) if (i.get("text") or "").strip()]
    if not items:
        return "Tell me what items you want on the checklist."

    candidates = await _get_checklist_candidates(company_id, project_id, limit=40)

    now = datetime.now(timezone.utc)
    normalized_items = [
        {"text": i.get("text", "").strip(), "category": (i.get("category") or "other").lower()}
        for i in items
    ]
    try:
        await db.whatsapp_conversation_state.update_one(
            {"group_id": group_id},
            {"$set": {
                "group_id":    group_id,
                "project_id":  project_id,
                "company_id":  company_id,
                "awaiting":    "checklist_assignment",
                "draft_items": normalized_items,
                "candidates":  candidates,
                "created_by":  sender,
                "created_at":  now,
                "expires_at":  now + timedelta(minutes=10),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"checklist draft save failed: {e}")
        return "Could not start checklist — please try again."

    return _format_candidates_message(normalized_items, candidates)


def _fuzzy_match_candidate(query: str, candidates: list):
    """Return the best candidate match for a free-text name, or None if
    ambiguous / no match. Uses case-insensitive substring + token match."""
    if not query or not candidates:
        return None
    q = query.strip().lower()
    if q in ("skip", "-", "none", "unassigned", ""):
        return "SKIP"

    # Exact full-name match
    for c in candidates:
        if c["name"].lower() == q:
            return c
    # First-name match (unique)
    first_matches = [c for c in candidates if c["name"].split()[0].lower() == q]
    if len(first_matches) == 1:
        return first_matches[0]
    # Substring match (unique)
    subs = [c for c in candidates if q in c["name"].lower()]
    if len(subs) == 1:
        return subs[0]
    # Token start match (unique)
    starts = [c for c in candidates if c["name"].lower().startswith(q)]
    if len(starts) == 1:
        return starts[0]
    # Ambiguous
    if len(subs) > 1:
        return {"AMBIGUOUS": [c["name"] for c in subs[:4]]}
    return None


def _parse_assignment_reply(body: str, num_items: int) -> list:
    """Parse a reply like '1: Anthony, 2: Carlos, 3: skip' into a list of
    (item_index, name_or_skip) pairs. Returns [] if parse fails entirely.

    Accepts various separators: ',' ';' newline. Accepts '1 - Anthony', '1) Anthony'."""
    if not body:
        return []
    text = body.strip()
    if text.lower() in ("cancel", "abort", "stop"):
        return [("CANCEL", None)]

    # Split on newlines or commas or semicolons
    parts = re.split(r"[,\n;]+", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r"^(\d+)\s*[:\-\)\.]?\s*(.+)$", p)
        if not m:
            continue
        try:
            idx = int(m.group(1))
        except Exception:
            continue
        if idx < 1 or idx > num_items:
            continue
        name = m.group(2).strip()
        out.append((idx, name))
    return out


async def _handle_checklist_assignment_reply(
    state: dict, body: str, group_id: str, sender: str,
) -> Optional[str]:
    """Process a user reply to the 'who should I assign' prompt. Returns the
    text reply to send, or None if the reply doesn't look like an assignment
    (caller should fall through to the agent)."""
    items = state.get("draft_items") or []
    candidates = state.get("candidates") or []
    if not items:
        return None

    parsed = _parse_assignment_reply(body, len(items))
    if not parsed:
        return None

    if parsed and parsed[0][0] == "CANCEL":
        await db.whatsapp_conversation_state.delete_one({"group_id": group_id})
        return "✓ Checklist discarded."

    # Apply assignments — last one wins per index
    assigned = {}  # idx -> candidate | 'SKIP'
    ambiguous = []
    unknown = []
    for idx, name in parsed:
        m = _fuzzy_match_candidate(name or "", candidates)
        if m == "SKIP":
            assigned[idx] = "SKIP"
        elif isinstance(m, dict) and "AMBIGUOUS" in m:
            ambiguous.append((idx, name, m["AMBIGUOUS"]))
        elif m is None:
            unknown.append((idx, name))
        else:
            assigned[idx] = m

    if ambiguous:
        lines = ["Need a more specific name for:"]
        for idx, name, opts in ambiguous:
            lines.append(f"  {idx}. '{name}' → {', '.join(opts)}")
        lines.append("Reply with full name. State kept; you can also say 'cancel'.")
        return "\n".join(lines)

    if unknown:
        lines = ["Didn't recognize:"]
        for idx, name in unknown:
            lines.append(f"  {idx}. '{name}'")
        lines.append("Check the candidates list and reply again. State kept.")
        return "\n".join(lines)

    # Build the final checklist doc
    project_id = state.get("project_id")
    company_id = state.get("company_id")
    now = datetime.now(timezone.utc)
    today_start, today_end = get_today_range_est()

    final_items = []
    for i, it in enumerate(items, start=1):
        ass = assigned.get(i)
        if ass == "SKIP" or ass is None:
            assigned_to = None
        else:
            assigned_to = ass.get("name")
        final_items.append({
            "text":          it.get("text", ""),
            "assigned_to":   assigned_to,
            "due_date":      None,
            "category":      it.get("category", "other"),
            "priority":      "medium",
            "completed":     False,
            "completed_at":  None,
            "completed_by":  None,
        })

    project = await db.projects.find_one({"_id": to_query_id(project_id)}) if project_id else None
    project_name = project.get("name", "Project") if project else "Project"

    doc = {
        "project_id":           project_id or "",
        "company_id":           company_id or "",
        "group_id":             group_id,
        "generated_at":         now,
        "date_range_start":     today_start,
        "date_range_end":       today_end,
        "items":                final_items,
        "source_message_count": 0,  # manual creation
        "source":               "interactive",
        "created_by_phone":     state.get("created_by") or sender,
        "is_deleted":           False,
    }
    await db.whatsapp_checklists.insert_one(doc)
    await db.whatsapp_conversation_state.delete_one({"group_id": group_id})

    # Compose confirmation message
    lines = [f"✅ Checklist created for {project_name}:"]
    for i, it in enumerate(final_items, start=1):
        who = it.get("assigned_to") or "Unassigned"
        lines.append(f"  {i}. {it['text']} → {who}")
    lines.append("")
    lines.append('View in Levelog app · Reply "done N" to mark complete.')
    return "\n".join(lines)


async def _run_group_agent(
    *,
    project_id: str,
    group_id: str,
    company_id: Optional[str],
    sender: str,
    body: str,
    features: Dict[str, Any],
    explicit_mention: bool = False,
) -> Optional[str]:
    """Run the tool-use agent over a bot-addressed message. Returns the reply
    text to send (or None for NOREPLY / silence)."""
    if not OPENAI_API_KEY:
        return None

    # Strip known prefixes
    trimmed = body.strip()
    low = trimmed.lower()
    for pfx in ("@levelog", "levelog "):
        if low.startswith(pfx):
            trimmed = trimmed[len(pfx):].strip(" :,-")
            break
    # Also strip @<digits> mentions (phone OR LID — LIDs are ~13–15 digits,
    # phone numbers 10–15). Accept 7+ so we catch short country-codeless too.
    trimmed = re.sub(r"@\d{7,}", "", trimmed).strip()

    # Pull recent conversation so the LLM remembers its own prior turns.
    # Without this, when the bot asks for clarification and the user replies,
    # the follow-up is read as a brand-new question with no context.
    history_msgs: List[Dict[str, str]] = []
    try:
        recent = await db.whatsapp_messages.find(
            {"group_id": group_id}
        ).sort("created_at", -1).limit(10).to_list(10)
        recent.reverse()  # oldest → newest
        # Drop the in-flight current message if it's already logged (it is:
        # see _process_whatsapp_message line ~12325, which inserts before
        # running the agent). We match on message_id when available, else
        # by body equality within the most recent row.
        if recent and recent[-1].get("sender") != "bot":
            last = recent[-1]
            if (last.get("body") or "").strip() == (body or "").strip():
                recent = recent[:-1]
        # Drop error/ack replies from the history so the model doesn't read
        # "too many tool calls" or "searching drawings…" as precedent and
        # decide to give up or re-route the same way.
        NOISE_PREFIXES = (
            "too many tool calls",
            "🔍 searching drawings",
            "🔎 checking the drawings",
            "plan queries are not configured",
            "couldn't find that sheet",
        )
        for m in recent[-6:]:  # keep context small (was 8) to reduce pattern-lock
            role = "assistant" if m.get("sender") == "bot" else "user"
            msg_body = (m.get("body") or "").strip()
            if not msg_body:
                continue
            if role == "assistant":
                low = msg_body.lower()
                if any(low.startswith(p) for p in NOISE_PREFIXES):
                    continue
                history_msgs.append({"role": "assistant", "content": msg_body})
            else:
                # Annotate user messages with sender phone so the model can
                # tell different people apart in the group.
                who = str(m.get("sender") or "")[-4:] or "user"
                history_msgs.append({
                    "role":    "user",
                    "content": f"[{who}] {msg_body}",
                })
    except Exception as e:
        logger.warning(f"agent: loading history failed: {e}")

    # Build the system prompt. If the user addressed us explicitly, drop the
    # permissive "feel free to NOREPLY" clause and insert a much stronger
    # "this message is definitely for you, MUST reply" instruction instead.
    if explicit_mention:
        system_prompt = _AGENT_SYSTEM_PROMPT_BASE + _AGENT_EXPLICIT_CLAUSE
    else:
        system_prompt = _AGENT_SYSTEM_PROMPT_BASE + _AGENT_NOREPLY_CLAUSE

    messages = [
        {"role": "system", "content": system_prompt},
        *history_msgs,
        {"role": "user",   "content": trimmed or body},
    ]

    # Filter the tool list by per-group feature flags
    enabled_tools = []
    for t in _AGENT_TOOLS:
        name = t["function"]["name"]
        if name == "who_on_site" and not features.get("who_on_site", True):
            continue
        if name == "list_workers" and not features.get("who_on_site", True):
            continue
        if name == "dob_status" and not features.get("dob_status", True):
            continue
        if name == "open_items" and not features.get("open_items", True):
            continue
        if name == "material_status" and not features.get("material_detection", True):
            continue
        if name == "query_plan" and not features.get("plan_queries", False):
            continue
        enabled_tools.append(t)

    try:
        async with ServerHttpClient(timeout=40.0) as client_http:
            last_content = ""  # track so we can fall back gracefully on overrun
            for _turn in range(4):  # max 4 tool rounds
                resp = await client_http.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "temperature": 0.2,
                        "max_tokens": 500,
                        "tools": enabled_tools,
                        "tool_choice": "auto",
                        "messages": messages,
                    },
                )
                resp.raise_for_status()
                choice = resp.json()["choices"][0]["message"]
                tool_calls = choice.get("tool_calls") or []
                content = choice.get("content") or ""
                if content:
                    last_content = content

                # Diagnostic — always log the model's choice so "agent ran but
                # said nothing" failures show up in Railway logs.
                tc_names = [tc.get("function", {}).get("name", "") for tc in tool_calls]
                logger.info(
                    f"agent turn={_turn} group={group_id[-10:] if group_id else '?'} "
                    f"sender={sender[-4:]} explicit={explicit_mention} "
                    f"tools={tc_names} content={(content or '')[:120]!r}"
                )

                # No tool calls — we have the final reply
                if not tool_calls:
                    stripped = content.strip()
                    if stripped.upper() == "NOREPLY":
                        # If the user explicitly addressed us, NOREPLY is a
                        # policy violation — force a polite fallback so we
                        # don't ghost them.
                        if explicit_mention:
                            logger.warning(
                                f"agent: NOREPLY despite explicit mention; "
                                f"fallback for body={body[:80]!r}"
                            )
                            return (
                                "I'm not sure how to help with that yet. "
                                "Try: who's on site, open items, DOB status, "
                                "show me <sheet>, or what's the project address."
                            )
                        return None
                    return stripped or None

                # Short-circuit: query_plan and start_checklist both dispatch
                # asynchronously — the async worker will send its own user-facing
                # messages (acknowledgement + image or checklist prompt). Running
                # more LLM rounds after calling them just wastes tokens and risks
                # double-replies. Stop here and let the async work speak.
                async_dispatch_tools = {"query_plan", "start_checklist"}
                if any(tc["function"]["name"] in async_dispatch_tools for tc in tool_calls):
                    # Execute them (fire-and-forget semantics inside the handlers)
                    import json as _json
                    for tc in tool_calls:
                        tc_name = tc["function"]["name"]
                        try:
                            tc_args = _json.loads(tc["function"].get("arguments") or "{}")
                        except Exception:
                            tc_args = {}
                        await _dispatch_agent_tool(
                            tc_name, tc_args,
                            project_id=project_id, group_id=group_id,
                            company_id=company_id, sender=sender,
                        )
                    return None  # the async handler sends the reply

                # Append assistant turn and execute each tool (synchronous tools)
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })
                import json as _json
                for tc in tool_calls:
                    tc_name = tc["function"]["name"]
                    try:
                        tc_args = _json.loads(tc["function"].get("arguments") or "{}")
                    except Exception:
                        tc_args = {}
                    tool_result = await _dispatch_agent_tool(
                        tc_name,
                        tc_args,
                        project_id=project_id,
                        group_id=group_id,
                        company_id=company_id,
                        sender=sender,
                    )
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "name":         tc_name,
                        "content":      tool_result,
                    })
            # Max turns reached — return whatever assistant text we've seen if
            # any (often the model has already said something useful mid-loop);
            # otherwise fall back silently rather than dumping a "too many
            # tool calls" message into the group chat.
            if last_content and last_content.strip().upper() != "NOREPLY":
                return last_content.strip()
            logger.warning(
                f"agent: max turns hit for group={group_id} sender={sender} body={body[:80]!r}"
            )
            return None
    except Exception as e:
        logger.error(f"group agent error: {e}", exc_info=True)
        return None


async def _dispatch_agent_tool(
    name: str, args: dict, *, project_id: str, group_id: str,
    company_id: Optional[str], sender: str,
) -> str:
    """Invoke one of the agent tools and return its text result."""
    try:
        if name == "who_on_site":
            return await _handle_who_on_site(
                project_id,
                trade=args.get("trade"),
                company=args.get("company"),
            )
        if name == "list_workers":
            return await _handle_list_workers(
                company_id=company_id,
                trade=args.get("trade"),
                company=args.get("company"),
            )
        if name == "project_info":
            return await _handle_project_info(project_id)
        if name == "dob_status":
            return await _handle_dob_status(project_id)
        if name == "active_permits":
            return await _handle_active_permits(project_id)
        if name == "open_items":
            return await _handle_open_items(project_id)
        if name == "material_status":
            return await _handle_material_status(project_id)
        if name == "query_plan":
            # Sprint 5: visual question answering. If `question` is given we
            # dispatch in VQA mode (Qwen answers from the drawing). Else we
            # just send the matching sheet image(s).
            question = args.get("question") or ""
            sheet_number = args.get("sheet_number") or ""
            bits = []
            if args.get("discipline"): bits.append(args["discipline"])
            if args.get("floor"):      bits.append(f"{args['floor']} floor")
            if args.get("sheet_type"): bits.append(args["sheet_type"])
            if sheet_number:           bits.append(sheet_number)
            if args.get("keywords"):   bits.extend(args["keywords"])
            synth = " ".join(bits) or question or "plan"
            # Pass the structured spec straight through so _handle_plan_query
            # doesn't have to re-parse the synth via another LLM call. The
            # parser also loses floor/discipline on messy synth strings.
            parsed_override = {
                "sheet_number": sheet_number or None,
                "discipline":   args.get("discipline") or None,
                "floor":        args.get("floor") or None,
                "sheet_type":   args.get("sheet_type") or None,
                "keywords":     args.get("keywords") or [],
                "question":     question or None,
            }
            asyncio.create_task(
                _handle_plan_query(
                    project_id, group_id, synth,
                    question=question or None,
                    parsed_override=parsed_override,
                )
            )
            if question:
                return f"(Plan VQA initiated for '{synth[:60]}' — question: '{question[:80]}'. Qwen will answer from the drawing.)"
            return f"(Plan search initiated for '{synth[:60]}'. Sending the matching sheet image.)"
        if name == "start_permit_renewal":
            return await _handle_start_permit_renewal(
                project_id, group_id, sender,
                permit_hint=args.get("permit_hint") or "",
            )
        if name == "start_checklist":
            items = args.get("items") or []
            return await _handle_start_checklist(
                project_id, group_id, items, sender, company_id=company_id
            )
        return f"(Unknown tool '{name}'.)"
    except Exception as e:
        logger.error(f"tool {name} failed: {e}", exc_info=True)
        return f"(Tool error: {str(e)[:120]})"


# ==================== WHATSAPP MESSAGE PROCESSOR ====================

async def _process_whatsapp_message(payload: dict):
    """Background task to process an inbound WhatsApp message."""
    try:
        parsed = parse_inbound_message(payload, vendor=WHATSAPP_VENDOR)
        sender = parsed["sender"].split("@")[0]  # phone number
        now = datetime.now(timezone.utc)

        # --- GROUP message ---
        if parsed["is_group"]:
            group_id = parsed["group_id"]

            # ── Link-code detection runs FIRST, before any group-linked check.
            # This is how an unlinked group becomes linked: user pastes the
            # 6-digit code we generated, webhook fires, we record group_id on
            # the pending link code, user clicks Verify in the app.
            body_for_code = parsed.get("body") or ""
            code_match = re.match(r"^\s*(\d{6})\s*$", body_for_code)
            if code_match:
                code_val = code_match.group(1)
                code_doc = await db.whatsapp_link_codes.find_one({"code": code_val})
                if code_doc and not code_doc.get("verified"):
                    await db.whatsapp_link_codes.update_one(
                        {"_id": code_doc["_id"]},
                        {"$set": {"group_id": group_id, "group_verified": True}},
                    )
                    logger.info(
                        f"whatsapp link: group {group_id} registered code {code_val}"
                    )

            # Look up linked group
            group_doc = await db.whatsapp_groups.find_one({"wa_group_id": group_id, "active": True})
            if not group_doc:
                return  # Not a linked group — ignore further processing
            project_id = group_doc["project_id"]
            msg_company_id = group_doc.get("company_id")

            # Per-group bot config (legacy docs without a config get all-default
            # behavior via .get() defaults — the startup migration backfills.)
            bot_config = group_doc.get("bot_config", {}) or {}
            features = bot_config.get("features", {}) or {}
            bot_enabled = bot_config.get("bot_enabled", True)

            # Voicenotes are not processed by the bot for now. WaAPI's
            # download-media returns encrypted .enc bytes and the
            # mediaKey resolution was unreliable. Text-only is the
            # product decision. Silently ignore — message still stored
            # in history below. Quoted voicenotes (text reply to a
            # voicenote with @Levelog) are also silently ignored.
            body = parsed["body"]
            if parsed.get("has_audio") or parsed.get("quoted_is_audio"):
                try:
                    await db.whatsapp_messages.insert_one({
                        "group_id":   group_id,
                        "project_id": project_id,
                        "company_id": msg_company_id,
                        "sender":     sender,
                        "body":       body or "(voicenote — ignored)",
                        "has_audio":  True,
                        "message_id": parsed.get("message_id"),
                        "timestamp":  datetime.fromtimestamp(
                            parsed["timestamp"], tz=timezone.utc
                        ) if parsed.get("timestamp") else now,
                        "created_at": now,
                        "skipped":    "voice_disabled",
                    })
                except Exception:
                    pass
                return

            # Store message (always — history is not subject to bot_enabled)
            await db.whatsapp_messages.insert_one({
                "group_id": group_id,
                "project_id": project_id,
                "company_id": msg_company_id,
                "sender": sender,
                "body": body,
                "has_audio": parsed["has_audio"],
                "message_id": parsed["message_id"],
                "timestamp": datetime.fromtimestamp(parsed["timestamp"], tz=timezone.utc) if parsed["timestamp"] else now,
                "created_at": now,
            })

            # Master kill switch — stop all bot-initiated behavior below this point
            if not bot_enabled:
                return

            # ── Sprint 6: interactive checklist assignment flow ──
            # If this group has an active draft checklist awaiting assignment,
            # try to parse the reply BEFORE running any other handlers.
            try:
                convo_state = await db.whatsapp_conversation_state.find_one(
                    {"group_id": group_id}
                )
            except Exception:
                convo_state = None
            if convo_state:
                # Expired? drop it
                exp = convo_state.get("expires_at")
                if isinstance(exp, datetime):
                    exp_aware = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
                    if exp_aware < datetime.now(timezone.utc):
                        await db.whatsapp_conversation_state.delete_one({"group_id": group_id})
                        convo_state = None
            if convo_state and convo_state.get("awaiting") == "checklist_assignment":
                reply = await _handle_checklist_assignment_reply(
                    convo_state, body or "", group_id, sender
                )
                if reply:
                    await send_whatsapp_message(group_id, reply)
                    return
                # Not an assignment reply — fall through to agent

            # ── "done N" — mark checklist item complete ──
            # Must come before on-demand @levelog detection so short msgs match.
            if body:
                done_match = re.match(r"^\s*done\s+(\d+)\s*$", body.strip(), re.IGNORECASE)
                if done_match:
                    try:
                        n = int(done_match.group(1))
                    except Exception:
                        n = 0
                    # Find most recent non-deleted checklist for this group
                    latest = await db.whatsapp_checklists.find_one(
                        {"group_id": group_id, "is_deleted": {"$ne": True}},
                        sort=[("generated_at", -1)],
                    )
                    if not latest:
                        await send_whatsapp_message(
                            group_id,
                            "No active checklist found for this group.",
                        )
                        return
                    items_list = latest.get("items") or []
                    if n < 1 or n > len(items_list):
                        await send_whatsapp_message(
                            group_id,
                            f"Item {n} not found. This checklist has {len(items_list)} items.",
                        )
                        return
                    idx = n - 1
                    items_list[idx]["completed"] = True
                    items_list[idx]["completed_at"] = now
                    items_list[idx]["completed_by"] = sender
                    await db.whatsapp_checklists.update_one(
                        {"_id": latest["_id"]},
                        {"$set": {"items": items_list}},
                    )
                    # Which checklist? Show time so multiple checklists per day
                    # are distinguishable.
                    try:
                        from zoneinfo import ZoneInfo
                        gen_est = latest.get("generated_at")
                        if isinstance(gen_est, datetime):
                            if gen_est.tzinfo is None:
                                gen_est = gen_est.replace(tzinfo=timezone.utc)
                            gen_local = gen_est.astimezone(ZoneInfo("America/New_York"))
                            label = gen_local.strftime("%-I:%M %p") if hasattr(gen_local, 'strftime') else str(gen_local)
                            # Windows fallback — strftime %-I is POSIX only
                            label = gen_local.strftime("%I:%M %p").lstrip("0")
                        else:
                            label = "today's"
                    except Exception:
                        label = "today's"
                    await send_whatsapp_message(
                        group_id,
                        f"✓ Item {n} of {label} checklist marked complete.",
                    )
                    return

            # ── On-demand @levelog checklist / !checklist trigger ──
            if body:
                ondemand = False
                lower = body.strip().lower()
                for kw in ("@levelog checklist", "@levelog  checklist", "!checklist"):
                    if kw in lower:
                        ondemand = True
                        break
                if ondemand:
                    # Condition 1: feature must be enabled for this group
                    if not bot_config.get("checklist_extraction_enabled", False):
                        # Silent — do not respond per spec
                        return
                    # Condition 2: sender must be a registered admin/owner/cp
                    contact = await db.whatsapp_contacts.find_one(
                        {"phone": sender, "user_id": {"$ne": None}}
                    )
                    sender_role = None
                    if contact and contact.get("user_id"):
                        user_doc = await db.users.find_one(
                            {"_id": to_query_id(contact["user_id"])}
                        )
                        if user_doc:
                            sender_role = (user_doc.get("role") or "").lower()
                    if sender_role not in ("admin", "owner", "cp"):
                        await send_whatsapp_message(
                            group_id,
                            "You need admin or manager access to request a checklist. "
                            "If you are an admin, add your phone in Settings → Personal "
                            "Details so the bot can recognize you.",
                        )
                        return
                    # Build conversation text for the last 24 hours (EST-today window)
                    today_start_od, today_end_od = get_today_range_est()
                    msgs_od = await db.whatsapp_messages.find({
                        "group_id": group_id,
                        "created_at": {"$gte": today_start_od, "$lt": today_end_od},
                    }).sort("created_at", 1).to_list(500)
                    convo_lines_od = []
                    for m in msgs_od:
                        if m.get("type") == "bot_plan_response":
                            continue
                        s_sender = m.get("sender", "unknown")
                        s_body = m.get("body", "")
                        if s_body:
                            convo_lines_od.append(f"{s_sender}: {s_body}")
                    convo_text_od = "\n".join(convo_lines_od[:400])
                    # On-demand does NOT go through send_log dedup — user requested it
                    try:
                        await _extract_whatsapp_checklist(
                            str(project_id), group_id, convo_text_od
                        )
                    except Exception as e:
                        logger.error(f"on-demand checklist failed: {e}", exc_info=True)
                    return

            # ── Sprint 4: Agentic intent router ──
            # Run the tool-use agent only if the bot was addressed. This covers
            # voice notes, @mentions of the bot number, '@levelog' prefix, and
            # soft intent trigger phrases. The agent can call tools for
            # who_on_site, dob_status, open_items, material_status, query_plan,
            # list_workers, and start_checklist.
            bot_phone_digits = re.sub(
                r"\D", "", os.environ.get("WAAPI_DISPLAY_NUMBER", "")
            )
            address_mode = (features.get("address_mode") or "strict").lower()
            quoted_body = parsed.get("quoted_body") or ""
            mentioned_jids = parsed.get("mentioned_jids") or []
            # Did the user explicitly @-mention the bot (native WhatsApp
            # @mention, literal @levelog text, or a quoted reply to either)?
            # If yes we lift the NOREPLY escape hatch for the agent — an
            # explicitly addressed message MUST get some reply.
            explicit_mention = (
                _has_explicit_bot_mention(body, bot_phone_digits, mentioned_jids)
                or _has_explicit_bot_mention(quoted_body, bot_phone_digits, None)
            )
            is_addressed = await _is_bot_addressed(
                body,
                bot_phone_digits,
                parsed.get("has_audio", False),
                group_id=group_id,
                sender=sender,
                mode=address_mode,
                quoted_body=quoted_body,
                mentioned_jids=mentioned_jids,
            )
            if is_addressed:
                reply = await _run_group_agent(
                    project_id=str(project_id),
                    group_id=group_id,
                    company_id=msg_company_id,
                    sender=sender,
                    body=body,
                    features=features,
                    explicit_mention=explicit_mention,
                )
                if reply:
                    await send_whatsapp_message(group_id, reply)
                return

            # Material request detection gated on the features flag
            if features.get("material_detection", True) and body and len(body) >= 15:
                detection = await _detect_material_request(body, str(project_id), msg_company_id)
                if detection:
                    req_doc = await _create_material_request(
                        str(project_id), msg_company_id, group_id,
                        parsed["message_id"], sender, detection
                    )
                    if req_doc and req_doc.get("_id"):
                        await _send_material_confirmation(group_id, req_doc)
            return

        # --- DIRECT message ---
        # Look up contact
        contact = await db.whatsapp_contacts.find_one({"phone": sender, "user_id": {"$ne": None}})
        if not contact:
            # Unknown or unregistered number — stay silent
            return

        # Transcribe audio if present
        body = parsed["body"]
        if parsed["has_audio"]:
            audio_bytes = await download_audio(parsed)
            if audio_bytes:
                body = await transcribe_audio(audio_bytes)

        if not body:
            return

        # Classify intent
        intent = await classify_intent(body)
        if not intent:
            return

        project_id = await _find_project_for_contact(contact)
        if not project_id:
            await send_whatsapp_message(parsed["from"], "No project found linked to your account.")
            return

        # Execute intent
        if intent == "who_on_site":
            reply = await _handle_who_on_site(project_id)
        elif intent == "dob_status":
            reply = await _handle_dob_status(project_id)
        elif intent == "open_items":
            reply = await _handle_open_items(project_id)
        elif intent == "material_receipt":
            reply = await _handle_material_receipt(project_id, body, sender)
        elif intent == "material_status":
            reply = await _handle_material_status(project_id)
        else:
            return

        await send_whatsapp_message(parsed["from"], reply)

    except Exception as e:
        logger.error(f"WhatsApp message processing error: {e}", exc_info=True)


# ---------- group link handler ----------

async def _handle_bot_added_to_group(group_id: str):
    """When bot is added to a group, send the pending link code into the group."""
    # Find any pending link code that hasn't been group-verified
    code_doc = await db.whatsapp_link_codes.find_one({
        "verified": False,
        "group_verified": {"$ne": True},
    })
    if code_doc:
        code = code_doc["code"]
        await send_whatsapp_message(
            group_id,
            f"Levelog bot has been added. To link this group, someone with access should paste this code in the Levelog app:\n\n*{code}*\n\nOr type the code in this group to auto-verify."
        )


# ---------- webhook (PUBLIC — no JWT) ----------

@api_router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Public webhook for WaAPI — returns 200 immediately, processes in background.
    Also logs every raw payload into whatsapp_webhook_log for debugging."""
    raw_body = b""
    try:
        raw_body = await request.body()
    except Exception:
        pass

    # Dump raw payload into a debug collection so we can inspect what WaAPI sends
    try:
        await db.whatsapp_webhook_log.insert_one({
            "received_at": datetime.now(timezone.utc),
            "headers": {k: v for k, v in request.headers.items()
                        if k.lower() not in ("cookie", "authorization")},
            "remote_addr": request.client.host if request.client else None,
            "raw_body_preview": raw_body[:4000].decode("utf-8", errors="replace"),
            "raw_body_length": len(raw_body),
        })
    except Exception as e:
        logger.warning(f"webhook log insert failed: {e}")

    payload = None
    try:
        import json as _json
        payload = _json.loads(raw_body.decode("utf-8")) if raw_body else None
    except Exception:
        return {"status": "ok"}

    if payload:
        asyncio.create_task(_process_whatsapp_message(payload))
    return {"status": "ok"}


@api_router.get("/whatsapp/debug/audio-probe")
async def whatsapp_debug_audio_probe(
    current_user=Depends(get_current_user), limit: int = 10
):
    """Recent download-audio probe traces — which WaAPI endpoints were
    tried and what each returned."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        rows = await db.whatsapp_audio_probe.find().sort(
            "received_at", -1
        ).limit(min(limit, 50)).to_list(min(limit, 50))
        for r in rows:
            r.pop("_id", None)
            if isinstance(r.get("received_at"), datetime):
                r["received_at"] = r["received_at"].isoformat()
        return {"count": len(rows), "recent": rows}
    except Exception as e:
        return {"error": str(e)}


@api_router.get("/whatsapp/debug/audio-diag")
async def whatsapp_debug_audio_diag(
    current_user=Depends(get_current_user), limit: int = 10
):
    """Recent voicenote download/transcription outcomes."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        rows = await db.whatsapp_audio_diag.find().sort(
            "received_at", -1
        ).limit(min(limit, 50)).to_list(min(limit, 50))
        for r in rows:
            r.pop("_id", None)
            if isinstance(r.get("received_at"), datetime):
                r["received_at"] = r["received_at"].isoformat()
        return {"count": len(rows), "recent": rows}
    except Exception as e:
        return {"error": str(e)}


@api_router.get("/whatsapp/debug/bot-identifiers")
async def whatsapp_debug_bot_ids(current_user=Depends(get_current_user)):
    """Dump the digit-strings the addressing matcher recognizes as 'the bot'.

    If your native @mention isn't being detected, compare the LID the
    webhook payloads carry (see /whatsapp/debug/webhook-log) against the
    list this returns. A missing LID here = env var isn't loaded, or has
    whitespace/quote corruption.
    """
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    env_phone_raw = os.environ.get("WAAPI_DISPLAY_NUMBER", "")
    env_lid_raw = os.environ.get("WAAPI_BOT_LID", "")
    return {
        "env_waapi_display_number": {
            "raw_repr": repr(env_phone_raw),
            "digits_only": re.sub(r"\D", "", env_phone_raw),
        },
        "env_waapi_bot_lid": {
            "raw_repr": repr(env_lid_raw),
            "digits_only": re.sub(r"\D", "", env_lid_raw),
        },
        "learned_lids_since_restart": sorted(_LEARNED_BOT_LIDS),
        "full_matcher_set": _bot_identifier_digits(),
        "note": (
            "If native @mentions still fail, look at "
            "/whatsapp/debug/webhook-log and find the @<digits> token in a "
            "recent inbound body. It must be exactly equal to one of "
            "full_matcher_set entries, or share the last 10 digits with a "
            "phone entry."
        ),
    }


@api_router.get("/whatsapp/debug/webhook-log")
async def whatsapp_debug_webhook_log(current_user=Depends(get_current_user)):
    """Return the last 20 raw webhook hits so we can see what WaAPI is sending."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    rows = await db.whatsapp_webhook_log.find().sort("received_at", -1).limit(20).to_list(20)
    total = await db.whatsapp_webhook_log.estimated_document_count()
    return {
        "total": total,
        "recent": [
            {
                "received_at":     str(r.get("received_at")),
                "remote_addr":     r.get("remote_addr"),
                "body_length":     r.get("raw_body_length"),
                "body_preview":    (r.get("raw_body_preview") or "")[:1500],
                "user_agent":      (r.get("headers") or {}).get("user-agent"),
            }
            for r in rows
        ],
    }


# ---------- group linking flow (auth required) ----------

@api_router.post("/whatsapp/group-link/initiate")
async def whatsapp_group_link_initiate(
    body: dict,
    current_user=Depends(get_current_user),
):
    """Generate a 6-digit code valid for 5 minutes to link a WhatsApp group to a project."""
    project_id = body.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    company_id = get_user_company_id(current_user)
    # Generate unique 6-digit code
    code = "".join(random.choices(_string.digits, k=6))
    now = datetime.now(timezone.utc)
    # get_current_user returns the user dict via serialize_id, which strips
    # _id and replaces it with id. Use .get('id') with a fallback so this
    # also tolerates older payload shapes.
    creator_id = str(current_user.get("id") or current_user.get("_id") or "")
    await db.whatsapp_link_codes.insert_one({
        "code": code,
        "project_id": project_id,
        "company_id": company_id,
        "created_by": creator_id,
        "verified": False,
        "group_verified": False,
        "group_id": None,
        "created_at": now,
        "expires_at": now + timedelta(minutes=5),
    })
    return {"code": code, "expires_in_seconds": 300}


@api_router.get("/whatsapp/debug/waapi-config")
async def whatsapp_debug_waapi_config(current_user=Depends(get_current_user)):
    """Return which WaAPI instance the backend is actually pointing at.
    Helps diagnose mismatches between the dashboard and the env vars."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Probe WaAPI for instance status
    status_data = None
    status_err = None
    try:
        async with ServerHttpClient(timeout=10.0) as client_http:
            resp = await client_http.get(
                f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}",
                headers={"Authorization": f"Bearer {WAAPI_TOKEN}"},
            )
            status_data = {
                "http_status": resp.status_code,
                "body_preview": resp.text[:500],
            }
    except Exception as e:
        status_err = str(e)

    return {
        "configured_instance_id": WAAPI_INSTANCE_ID or "(empty)",
        "configured_base_url": WAAPI_BASE_URL,
        "configured_display_number": os.environ.get("WAAPI_DISPLAY_NUMBER", "(empty)"),
        "token_present": bool(WAAPI_TOKEN),
        "token_length": len(WAAPI_TOKEN) if WAAPI_TOKEN else 0,
        "waapi_instance_probe": status_data,
        "waapi_instance_probe_error": status_err,
    }


@api_router.get("/whatsapp/debug/recent-messages")
async def whatsapp_debug_recent_messages(current_user=Depends(get_current_user)):
    """Owner/admin: show the last 20 whatsapp_messages stored. Confirms whether
    the webhook is actually delivering events into the DB."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    msgs = await db.whatsapp_messages.find().sort("created_at", -1).limit(20).to_list(20)
    return {
        "count": await db.whatsapp_messages.estimated_document_count(),
        "recent": [
            {
                "from": m.get("sender"),
                "group_id": m.get("group_id"),
                "body": (m.get("body") or "")[:140],
                "created_at": str(m.get("created_at")),
            }
            for m in msgs
        ],
    }


@api_router.get("/whatsapp/debug/pending-codes")
async def whatsapp_debug_pending_codes(current_user=Depends(get_current_user)):
    """Owner/admin only: list un-verified codes for this company so we can
    see what the webhook actually stored vs what the user is typing."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    company_id = get_user_company_id(current_user)
    codes = await db.whatsapp_link_codes.find({
        "company_id": company_id,
        "verified": False,
    }).sort("created_at", -1).to_list(20)
    out = []
    for c in codes:
        out.append({
            "code":            c.get("code"),
            "project_id":      c.get("project_id"),
            "group_id":        c.get("group_id"),
            "group_verified":  c.get("group_verified"),
            "created_at":      str(c.get("created_at")),
            "expires_at":      str(c.get("expires_at")),
            "verified":        c.get("verified"),
        })
    return {"codes": out}


@api_router.post("/whatsapp/group-link/verify")
async def whatsapp_group_link_verify(
    body: dict,
    current_user=Depends(get_current_user),
):
    """Verify a link code and create the group-project association."""
    code = body.get("code", "").strip()
    project_id = body.get("project_id")
    if not code or not project_id:
        raise HTTPException(status_code=400, detail="code and project_id required")
    company_id = get_user_company_id(current_user)
    code_doc = await db.whatsapp_link_codes.find_one({
        "code": code,
        "project_id": project_id,
        "company_id": company_id,
        "verified": False,
    })
    if not code_doc:
        raise HTTPException(status_code=404, detail="Invalid or expired code")
    group_id = code_doc.get("group_id")
    if not group_id and not code_doc.get("group_verified"):
        raise HTTPException(status_code=400, detail="Code not yet verified by group. Send the code in the WhatsApp group first.")
    # Create group link. Seed bot_config on first insert only ($setOnInsert)
    # so re-linking an existing group doesn't clobber the admin's config.
    now = datetime.now(timezone.utc)
    linker_id = str(current_user.get("id") or current_user.get("_id") or "")
    await db.whatsapp_groups.update_one(
        {"company_id": company_id, "wa_group_id": group_id},
        {
            "$set": {
                "project_id": project_id,
                "company_id": company_id,
                "wa_group_id": group_id,
                "linked_by": linker_id,
                "linked_at": now,
                "active": True,
            },
            "$setOnInsert": {
                "bot_config": _default_bot_config(),
            },
        },
        upsert=True,
    )
    # Mark code as used
    await db.whatsapp_link_codes.update_one(
        {"_id": code_doc["_id"]},
        {"$set": {"verified": True}},
    )
    return {"status": "linked", "group_id": group_id, "project_id": project_id}


# ---------- WhatsApp management endpoints (auth required) ----------

@api_router.get("/whatsapp/groups/{project_id}")
async def whatsapp_get_groups(project_id: str, current_user=Depends(get_current_user)):
    """List linked WhatsApp groups for a project, with message counts + bot_config."""
    company_id = get_user_company_id(current_user)
    groups = await db.whatsapp_groups.find({
        "project_id": project_id,
        "company_id": company_id,
        "active": True,
    }).to_list(50)
    results = []
    for g in groups:
        msg_count = await db.whatsapp_messages.count_documents({"group_id": g["wa_group_id"]})
        # Merge stored config over defaults so legacy docs without one still
        # return a complete object — frontend never has to handle missing fields.
        cfg = _default_bot_config()
        stored = g.get("bot_config") or {}
        cfg.update({k: v for k, v in stored.items() if k in _WHATSAPP_CONFIG_KEYS})
        # Merge features subdoc specifically so partial feature dicts work too.
        if "features" in stored and isinstance(stored["features"], dict):
            merged_features = dict(cfg["features"])
            merged_features.update({
                k: v for k, v in stored["features"].items() if k in _WHATSAPP_FEATURE_KEYS
            })
            cfg["features"] = merged_features
        results.append({
            "id": str(g["_id"]),
            "wa_group_id": g["wa_group_id"],
            "project_id": g["project_id"],
            "linked_at": g.get("linked_at"),
            "message_count": msg_count,
            "group_name": g.get("group_name"),
            "bot_config": cfg,
        })
    return results


@api_router.put("/whatsapp/groups/{group_doc_id}/config")
async def whatsapp_update_group_config(
    group_doc_id: str,
    body: dict,
    current_user=Depends(get_current_user),
):
    """Update bot_config for a linked WhatsApp group.

    Admin/owner only, must belong to the group's company. Accepts a partial
    or full config object. Unknown keys rejected. Time fields validated HH:MM.
    Days list validated 1-7.
    """
    # Role gate — only admins/owners can modify bot config
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin or owner access required")

    group = await db.whatsapp_groups.find_one({"_id": to_query_id(group_doc_id)})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    user_company_id = get_user_company_id(current_user)
    if user_company_id and group.get("company_id") != user_company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # ---- Validate payload ----
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=422, detail="Request body must be a non-empty object")

    unknown = set(body.keys()) - _WHATSAPP_CONFIG_KEYS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown config keys: {sorted(unknown)}",
        )

    set_ops: Dict[str, Any] = {}

    if "bot_enabled" in body:
        if not isinstance(body["bot_enabled"], bool):
            raise HTTPException(status_code=422, detail="bot_enabled must be a boolean")
        set_ops["bot_config.bot_enabled"] = body["bot_enabled"]

    if "daily_summary_enabled" in body:
        if not isinstance(body["daily_summary_enabled"], bool):
            raise HTTPException(status_code=422, detail="daily_summary_enabled must be a boolean")
        set_ops["bot_config.daily_summary_enabled"] = body["daily_summary_enabled"]

    if "daily_summary_time" in body:
        t = body["daily_summary_time"]
        if not isinstance(t, str) or not _HHMM_RE.match(t):
            raise HTTPException(status_code=422, detail="daily_summary_time must be HH:MM (24h)")
        set_ops["bot_config.daily_summary_time"] = t

    if "daily_summary_days" in body:
        d = body["daily_summary_days"]
        if not isinstance(d, list) or not all(isinstance(x, int) and 1 <= x <= 7 for x in d):
            raise HTTPException(
                status_code=422,
                detail="daily_summary_days must be a list of ints 1-7 (Mon=1 Sun=7)",
            )
        set_ops["bot_config.daily_summary_days"] = d

    if "checklist_extraction_enabled" in body:
        if not isinstance(body["checklist_extraction_enabled"], bool):
            raise HTTPException(
                status_code=422, detail="checklist_extraction_enabled must be a boolean"
            )
        set_ops["bot_config.checklist_extraction_enabled"] = body["checklist_extraction_enabled"]

    if "checklist_frequency" in body:
        f = body["checklist_frequency"]
        if f not in ("daily", "on_demand"):
            raise HTTPException(
                status_code=422, detail="checklist_frequency must be 'daily' or 'on_demand'"
            )
        set_ops["bot_config.checklist_frequency"] = f

    if "checklist_time" in body:
        t = body["checklist_time"]
        if not isinstance(t, str) or not _HHMM_RE.match(t):
            raise HTTPException(status_code=422, detail="checklist_time must be HH:MM (24h)")
        set_ops["bot_config.checklist_time"] = t

    if "cross_project_summary" in body:
        if not isinstance(body["cross_project_summary"], bool):
            raise HTTPException(status_code=422, detail="cross_project_summary must be a boolean")
        set_ops["bot_config.cross_project_summary"] = body["cross_project_summary"]

    if "features" in body:
        f = body["features"]
        if not isinstance(f, dict):
            raise HTTPException(status_code=422, detail="features must be an object")
        unknown_features = set(f.keys()) - _WHATSAPP_FEATURE_KEYS
        if unknown_features:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown feature keys: {sorted(unknown_features)}",
            )
        for k, v in f.items():
            # address_mode is the one non-boolean feature — it's a string enum.
            if k == "address_mode":
                if v not in ("strict", "loose"):
                    raise HTTPException(
                        status_code=422,
                        detail="features.address_mode must be 'strict' or 'loose'",
                    )
                continue
            if not isinstance(v, bool):
                raise HTTPException(
                    status_code=422,
                    detail=f"features.{k} must be a boolean",
                )
            set_ops[f"bot_config.features.{k}"] = v

    # Cross-field validation — days list required non-empty if daily summary enabled
    # Handles either the effective new state OR combo of request + stored state.
    merged_enabled = set_ops.get("bot_config.daily_summary_enabled")
    if merged_enabled is None:
        merged_enabled = (group.get("bot_config") or {}).get("daily_summary_enabled", False)
    merged_days = set_ops.get("bot_config.daily_summary_days")
    if merged_days is None:
        merged_days = (group.get("bot_config") or {}).get("daily_summary_days", [1, 2, 3, 4, 5])
    if merged_enabled and not merged_days:
        raise HTTPException(
            status_code=422,
            detail="daily_summary_days cannot be empty when daily_summary_enabled is true",
        )

    set_ops["updated_at"] = datetime.now(timezone.utc)

    await db.whatsapp_groups.update_one(
        {"_id": to_query_id(group_doc_id)},
        {"$set": set_ops},
    )

    updated = await db.whatsapp_groups.find_one({"_id": to_query_id(group_doc_id)})

    # Return the same shape as the list endpoint entry for this group
    cfg = _default_bot_config()
    stored = updated.get("bot_config") or {}
    cfg.update({k: v for k, v in stored.items() if k in _WHATSAPP_CONFIG_KEYS})
    if "features" in stored and isinstance(stored["features"], dict):
        merged_features = dict(cfg["features"])
        merged_features.update({
            k: v for k, v in stored["features"].items() if k in _WHATSAPP_FEATURE_KEYS
        })
        cfg["features"] = merged_features

    return {
        "id": str(updated["_id"]),
        "wa_group_id": updated.get("wa_group_id"),
        "project_id": updated.get("project_id"),
        "group_name": updated.get("group_name"),
        "linked_at": updated.get("linked_at"),
        "bot_config": cfg,
    }


@api_router.delete("/whatsapp/groups/{group_doc_id}")
async def whatsapp_unlink_group(group_doc_id: str, current_user=Depends(get_current_user)):
    """Unlink (deactivate) a WhatsApp group."""
    company_id = get_user_company_id(current_user)
    result = await db.whatsapp_groups.update_one(
        {"_id": to_query_id(group_doc_id), "company_id": company_id},
        {"$set": {"active": False, "unlinked_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "unlinked"}


@api_router.post("/whatsapp/activate")
async def whatsapp_activate(current_user=Depends(get_current_user)):
    """Activate WhatsApp for the company. Auto-populate contacts from users."""
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=400, detail="No company associated")

    # Check if already active
    existing = await db.whatsapp_config.find_one({"company_id": company_id})
    if existing:
        return {"status": "already_active", "whatsapp_number": os.environ.get("WAAPI_DISPLAY_NUMBER", "")}

    # Create config
    await db.whatsapp_config.insert_one({
        "company_id": company_id,
        "is_active": True,
        "activated_at": datetime.now(timezone.utc),
        "activated_by": str(current_user.get("_id", current_user.get("id", "")))
    })
    # Auto-populate contacts from existing users with phone numbers
    users = await db.users.find({
        "company_id": company_id,
        "is_deleted": {"$ne": True},
        "phone": {"$exists": True, "$ne": ""},
    }).to_list(500)
    created = 0
    for user in users:
        phone = re.sub(r"[^\d]", "", user.get("phone", ""))
        if not phone:
            continue
        try:
            await db.whatsapp_contacts.update_one(
                {"company_id": company_id, "phone": phone},
                {"$setOnInsert": {
                    "company_id": company_id,
                    "phone": phone,
                    "user_id": str(user["_id"]),
                    "name": user.get("name", ""),
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            created += 1
        except Exception:
            pass  # duplicate
    return {"status": "activated", "contacts_synced": created, "whatsapp_number": os.environ.get("WAAPI_DISPLAY_NUMBER", "")}


@api_router.get("/whatsapp/status")
async def whatsapp_status(current_user=Depends(get_current_user)):
    """Check if WhatsApp is configured at platform level and active for company."""
    company_id = get_user_company_id(current_user)
    platform_configured = bool(WAAPI_INSTANCE_ID and WAAPI_TOKEN)
    company_active = False
    whatsapp_number = ""
    if company_id:
        config = await db.whatsapp_config.find_one({"company_id": company_id})
        company_active = bool(config and config.get("is_active"))
    if company_active:
        whatsapp_number = os.environ.get("WAAPI_DISPLAY_NUMBER", "")
    return {
        "platform_configured": platform_configured,
        "company_active": company_active,
        "whatsapp_number": whatsapp_number,
        "vendor": WHATSAPP_VENDOR,
    }


@api_router.post("/projects/{project_id}/repair-file-names")
async def repair_file_names(project_id: str, current_user=Depends(get_admin_user)):
    """Fix existing project_files rows whose `name` / `r2_key` contain URL-encoded
    sequences (%20, %2F, etc.). Renames the R2 object and updates the DB record.
    Safe to run repeatedly."""
    import urllib.parse as _urlparse
    company_id = get_user_company_id(current_user)
    # Do NOT filter by company_id — some legacy rows may have been written
    # without a company_id field, and the caller already matched project_id
    # which is scope enough.
    query: Dict[str, Any] = {"project_id": project_id, "is_deleted": {"$ne": True}}
    files = await db.project_files.find(query).to_list(500)
    debug_info = []
    repaired = []
    for f in files:
        raw = f.get("name") or ""
        decoded = _sanitize_upload_filename(raw)
        debug_info.append({
            "raw": raw, "decoded": decoded, "changed": decoded != raw,
            "has_r2_key": bool(f.get("r2_key")),
            "company_id": f.get("company_id"),
        })
        if decoded == raw:
            continue
        if not _r2_client:
            continue
        old_key = f.get("r2_key") or f"{f.get('company_id', '')}/{project_id}/{raw}"
        new_key = f"{f.get('company_id', '')}/{project_id}/{decoded}"
        try:
            # Copy to new key (R2 is S3-compatible)
            await asyncio.to_thread(
                _r2_client.copy_object,
                Bucket=R2_BUCKET_NAME,
                CopySource={"Bucket": R2_BUCKET_NAME, "Key": old_key},
                Key=new_key,
                ContentType="application/pdf",
            )
            # Delete old
            await asyncio.to_thread(
                _r2_client.delete_object, Bucket=R2_BUCKET_NAME, Key=old_key
            )
        except Exception as e:
            err_msg = f"copy/delete failed: old_key={old_key!r} new_key={new_key!r} error={str(e)[:300]}"
            logger.warning(f"repair_file_names: {err_msg}")
            debug_info[-1]["r2_error"] = err_msg
            continue

        new_url = f"{R2_PUBLIC_URL.rstrip('/')}/{new_key}" if R2_PUBLIC_URL else f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}/{new_key}"
        await db.project_files.update_one(
            {"_id": f["_id"]},
            {"$set": {
                "name":    decoded,
                "r2_key":  new_key,
                "r2_url":  new_url,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        repaired.append({"old_name": raw, "new_name": decoded})

    return {"repaired_count": len(repaired), "repaired": repaired, "debug": debug_info}


@api_router.post("/projects/{project_id}/reindex-document")
async def reindex_project_document(
    project_id: str,
    body: dict,
    current_user=Depends(get_admin_user),
):
    """Admin-only: re-index a single PDF. Clears existing page entries first
    so the file_hash cache can't block the re-run."""
    file_id = (body or {}).get("file_id")
    if not file_id:
        raise HTTPException(status_code=422, detail="file_id is required")

    # Verify company match
    file_rec = await db.project_files.find_one({"_id": to_query_id(file_id)})
    if not file_rec:
        raise HTTPException(status_code=404, detail="File not found")
    if file_rec.get("project_id") != project_id:
        raise HTTPException(status_code=400, detail="File is not part of this project")
    company_id = get_user_company_id(current_user)
    if company_id and file_rec.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not QWEN_API_KEY:
        raise HTTPException(status_code=503, detail="Plan indexing is not configured")
    if not file_rec.get("r2_key"):
        raise HTTPException(status_code=400, detail="File has no R2 storage key")

    # Wipe existing entries for this file
    await db.document_page_index.delete_many({"file_id": str(file_rec["_id"])})

    # Count pages for the response (best-effort)
    total_pages = 0
    try:
        obj = await asyncio.to_thread(
            _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=file_rec["r2_key"]
        )
        pdf_bytes = obj["Body"].read()
        try:
            from pypdf import PdfReader
            import io as _io
            total_pages = len(PdfReader(_io.BytesIO(pdf_bytes)).pages)
        except Exception:
            total_pages = 0
    except Exception:
        pass

    # Spawn background re-index
    asyncio.create_task(
        _index_pdf_file(project_id, file_rec.get("company_id") or company_id or "", dict(file_rec))
    )
    return {
        "status": "indexing",
        "file_name": file_rec.get("name"),
        "total_pages": total_pages,
    }


@api_router.post("/projects/{project_id}/reindex-all")
async def reindex_all_project_files(
    project_id: str,
    current_user=Depends(get_admin_user),
):
    """Admin-only: queue a full re-index of every PDF on this project.

    Useful after a prompt/DPI upgrade — the per-file hash cache is scoped
    by index_version, so v1-indexed pages will get reprocessed automatically
    by _index_pdf_file once spawned.
    """
    if not QWEN_API_KEY:
        raise HTTPException(status_code=503, detail="Plan indexing is not configured")
    company_id = get_user_company_id(current_user)

    q: Dict[str, Any] = {
        "project_id": project_id,
        "name":       {"$regex": r"\.pdf$", "$options": "i"},
        "r2_key":     {"$exists": True, "$ne": ""},
    }
    if company_id:
        q["company_id"] = company_id
    files = await db.project_files.find(q).to_list(500)
    if not files:
        return {"queued": 0, "files": []}

    queued = []
    for fr in files:
        # Wipe existing index entries so stale v1 pages don't linger.
        await db.document_page_index.delete_many({"file_id": str(fr["_id"])})
        asyncio.create_task(
            _index_pdf_file(
                project_id,
                fr.get("company_id") or company_id or "",
                dict(fr),
            )
        )
        queued.append(fr.get("name"))
    return {"queued": len(queued), "files": queued}


# ==================== TEMP-MEDIA PROXY (for WaAPI preflight) ====================
#
# WaAPI's send-media does a HEAD preflight on the supplied URL before fetching
# the body. R2 presigned URLs are method-scoped (a signed GET returns 403 on
# HEAD), so WaAPI rejects them. We side-step by handing WaAPI a URL that
# points to OUR backend — it accepts both HEAD and GET and proxies the bytes
# from R2. Token is opaque and rows TTL-auto-expire via whatsapp_conversation_state.


async def _mint_temp_media_token(r2_key: str, content_type: str = "image/jpeg",
                                   ttl_seconds: int = 3600) -> str:
    """Store an R2 key under an opaque token; return the token string."""
    import secrets as _secrets
    token = _secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    try:
        await db.temp_media_tokens.insert_one({
            "token":        token,
            "r2_key":       r2_key,
            "content_type": content_type,
            "created_at":   now,
            "expires_at":   exp,
        })
        # Ensure TTL index exists (idempotent).
        try:
            await db.temp_media_tokens.create_index(
                "expires_at", expireAfterSeconds=0, name="temp_media_ttl"
            )
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"temp_media_tokens insert failed: {e}")
    return token


async def _resolve_temp_media_token(token: str) -> Optional[dict]:
    try:
        row = await db.temp_media_tokens.find_one({"token": token})
    except Exception:
        return None
    if not row:
        return None
    exp = row.get("expires_at")
    if isinstance(exp, datetime):
        exp_aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=timezone.utc)
        if exp_aware < datetime.now(timezone.utc):
            return None
    return row


# Both routes are mounted on the unauth'd app (not api_router with its
# Depends(get_current_user) on other endpoints) because WaAPI doesn't
# forward auth headers. Token IS the auth.
@app.head("/api/public/temp-media/{token}")
async def public_temp_media_head(token: str):
    row = await _resolve_temp_media_token(token)
    if not row:
        return Response(status_code=404)
    # HEAD must mirror GET headers but have no body.
    return Response(
        status_code=200,
        headers={
            "Content-Type":  row.get("content_type") or "image/jpeg",
            "Cache-Control": "public, max-age=300",
        },
    )


@app.get("/api/public/temp-media/{token}")
async def public_temp_media_get(token: str):
    row = await _resolve_temp_media_token(token)
    if not row:
        raise HTTPException(status_code=404, detail="Not found or expired")
    r2_key = row.get("r2_key") or ""
    if not r2_key or not _r2_client or not R2_BUCKET_NAME:
        raise HTTPException(status_code=404, detail="Storage miss")
    try:
        obj = await asyncio.to_thread(
            _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=r2_key
        )
        data = obj["Body"].read()
    except Exception as e:
        logger.error(f"temp-media R2 get failed {r2_key}: {e}")
        raise HTTPException(status_code=502, detail="Storage fetch failed")
    return Response(
        content=data,
        media_type=row.get("content_type") or "image/jpeg",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _public_temp_media_url(token: str) -> str:
    """Build the fully-qualified URL WaAPI will HEAD+GET."""
    base = os.environ.get("PUBLIC_BASE_URL", "https://api.levelog.com").rstrip("/")
    return f"{base}/api/public/temp-media/{token}"


@api_router.post("/debug/probe-waapi-endpoints")
async def debug_probe_waapi_endpoints(
    body: dict,
    current_user=Depends(get_admin_user),
):
    """Probe multiple WaAPI action paths with the same test payload to see
    which endpoint actually accepts our image sends. Returns {path: status}.

    Body: {"image_url": "<presigned_r2_url>", "group_id": "<wa_group_id>"}
    """
    image_url = (body or {}).get("image_url", "").strip()
    group_id = (body or {}).get("group_id", "").strip()
    if not image_url or not group_id:
        raise HTTPException(status_code=422, detail="image_url and group_id required")
    if not WAAPI_INSTANCE_ID or not WAAPI_TOKEN:
        raise HTTPException(status_code=503, detail="WaAPI not configured")

    paths_to_try = [
        ("client/action/send-image",       {"chatId": group_id, "image":    image_url, "caption": "probe"}),
        ("client/action/send-media",       {"chatId": group_id, "mediaUrl": image_url, "caption": "probe"}),
        ("client/action/send-media",       {"chatId": group_id, "media":    image_url, "caption": "probe"}),
        ("client/action/send-media-url",   {"chatId": group_id, "mediaUrl": image_url, "caption": "probe"}),
        ("client/action/send-file-picture",{"chatId": group_id, "image":    image_url, "caption": "probe"}),
        ("client/action/send-message",     {"chatId": group_id, "mediaUrl": image_url, "message": "probe"}),
    ]
    results = {}
    async with ServerHttpClient(timeout=25.0) as client_http:
        for path, payload in paths_to_try:
            try:
                resp = await client_http.post(
                    f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/{path}",
                    headers={
                        "Authorization": f"Bearer {WAAPI_TOKEN}",
                        "Content-Type":  "application/json",
                    },
                    json=payload,
                )
                try:
                    j = resp.json()
                except Exception:
                    j = None
                results[f"{path} fields={list(payload.keys())}"] = {
                    "status": resp.status_code,
                    "body_preview": resp.text[:300],
                    "json": j,
                }
            except Exception as e:
                results[path] = {"error": str(e)[:200]}
    return {"base_url": WAAPI_BASE_URL, "instance": WAAPI_INSTANCE_ID, "results": results}


@api_router.post("/projects/{project_id}/debug/test-plan-image-send")
async def debug_test_plan_image_send(
    project_id: str,
    body: dict,
    current_user=Depends(get_admin_user),
):
    """Admin diagnostic — try to send a specific sheet's pre-rendered JPEG
    to a WhatsApp group and return the exact WaAPI response + our internal
    step results. Use this to figure out why image sends fall back to text
    without needing to tail Railway logs.

    Body: {"sheet_number": "Z-101.00", "group_id": "<wa_group_id>"}
    """
    sheet = (body or {}).get("sheet_number", "").strip()
    group_id = (body or {}).get("group_id", "").strip()
    if not sheet or not group_id:
        raise HTTPException(status_code=422, detail="sheet_number and group_id required")

    page = await db.document_page_index.find_one({
        "project_id": project_id,
        "sheet_number": {"$regex": f"^{re.escape(sheet)}(\\.\\d+)?$", "$options": "i"},
    })
    if not page:
        raise HTTPException(status_code=404, detail=f"No indexed page for sheet {sheet}")

    result = {
        "sheet_number":     page.get("sheet_number"),
        "sheet_title":      page.get("sheet_title"),
        "page_jpeg_r2_key": page.get("page_jpeg_r2_key"),
        "steps": {},
    }

    # Step 1 — fetch the jpeg (and compress for WhatsApp delivery)
    jpeg_src = await _fetch_page_jpeg(page)
    if jpeg_src:
        jpeg = await asyncio.to_thread(_compress_jpeg_for_whatsapp, jpeg_src)
    else:
        jpeg = None
    result["steps"]["fetch_jpeg"] = {
        "ok": bool(jpeg),
        "src_size": len(jpeg_src) if jpeg_src else 0,
        "compressed_size": len(jpeg) if jpeg else 0,
    }
    if not jpeg:
        return result

    # Step 2 — upload temp + mint token-based URL
    import uuid as _uuid
    temp_key = f"temp/whatsapp/{group_id}/{_uuid.uuid4()}.jpg"
    try:
        await asyncio.to_thread(_upload_to_r2, jpeg, temp_key, "image/jpeg")
        tok = await _mint_temp_media_token(temp_key, "image/jpeg", ttl_seconds=3600)
        media_url = _public_temp_media_url(tok)
        result["steps"]["upload_temp"] = {"ok": True, "temp_key": temp_key}
        result["steps"]["token_url"] = {"ok": True, "url": media_url}
    except Exception as e:
        result["steps"]["upload_temp"] = {"ok": False, "error": str(e)[:300]}
        return result

    # Step 3 — WaAPI send-media
    try:
        async with ServerHttpClient(timeout=40.0) as client_http:
            resp = await client_http.post(
                f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/client/action/send-media",
                headers={
                    "Authorization": f"Bearer {WAAPI_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "chatId":   group_id,
                    "mediaUrl": media_url,
                    "caption":  f"[diagnostic] {page.get('sheet_number')}",
                },
            )
            try:
                body_json = resp.json()
            except Exception:
                body_json = None
            result["steps"]["waapi_send_media"] = {
                "status":     resp.status_code,
                "ok":         200 <= resp.status_code < 300,
                "body_text":  resp.text[:800],
                "body_json":  body_json,
            }
    except Exception as e:
        result["steps"]["waapi_send_media"] = {"error": str(e)[:300]}
    return result


@api_router.get("/projects/{project_id}/debug/indexed-pages")
async def debug_indexed_pages(
    project_id: str,
    current_user=Depends(get_current_user),
    limit: int = 50,
):
    """Admin diagnostic — show what v2 indexing actually stored for this
    project's pages. Returns the interesting fields only (no raw summaries
    over 400 chars, no full embedding array)."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    company_id = get_user_company_id(current_user)
    q: Dict[str, Any] = {"project_id": project_id}
    if company_id:
        q["company_id"] = company_id
    rows = await db.document_page_index.find(q).sort([
        ("file_name", 1), ("page_number", 1),
    ]).limit(limit).to_list(limit)
    out = []
    for r in rows:
        summary = r.get("summary") or ""
        emb = r.get("embedding")
        out.append({
            "file_name":        r.get("file_name"),
            "page":             r.get("page_number"),
            "index_version":    r.get("index_version"),
            "discipline":       r.get("discipline"),
            "sheet_number":     r.get("sheet_number"),
            "sheet_title":      r.get("sheet_title"),
            "floor":            r.get("floor"),
            "is_spec_page":     r.get("is_spec_page"),
            "keywords_count":   len(r.get("keywords") or []),
            "summary_length":   len(summary),
            "summary_preview":  summary[:400],
            "has_embedding":    bool(emb) and isinstance(emb, list) and len(emb) > 0,
            "embedding_dim":    (len(emb) if isinstance(emb, list) else 0),
            "page_jpeg_r2_key": r.get("page_jpeg_r2_key") or "",
            "materials_preview": (r.get("materials") or "")[:200],
        })
    return {"count": len(out), "pages": out}


@api_router.get("/projects/{project_id}/document-index-status")
async def get_document_index_status(
    project_id: str,
    current_user=Depends(get_current_user),
):
    """Per-file indexing status for a project. Includes a top-level flag
    that tells the frontend whether the server has a Qwen key at all."""
    company_id = get_user_company_id(current_user)
    query: Dict[str, Any] = {"project_id": project_id}
    if company_id:
        query["company_id"] = company_id
    # PDFs only
    query["name"] = {"$regex": r"\.pdf$", "$options": "i"}

    files_out = []
    try:
        from pypdf import PdfReader
        import io as _io
    except Exception:
        PdfReader = None  # type: ignore
        _io = None        # type: ignore

    files = await db.project_files.find(query).to_list(500)
    for fr in files:
        file_id = str(fr.get("_id"))
        total_pages = 0
        # Try to read page count from the PDF (cheap if file is small)
        if PdfReader is not None and _io is not None and fr.get("r2_key") and _r2_client:
            try:
                obj = await asyncio.to_thread(
                    _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=fr["r2_key"]
                )
                total_pages = len(PdfReader(_io.BytesIO(obj["Body"].read())).pages)
            except Exception:
                total_pages = 0
        indexed = await db.document_page_index.count_documents({
            "file_id": file_id,
            "sheet_title": {"$ne": "[SPECIFICATION PAGE]"},
        })
        most_recent = await db.document_page_index.find_one(
            {"file_id": file_id},
            sort=[("indexed_at", -1)],
        )
        files_out.append({
            "file_id": file_id,
            "file_name": fr.get("name"),
            "total_pages": total_pages,
            "indexed_pages": indexed,
            "last_indexed_at": (most_recent or {}).get("indexed_at"),
        })

    return {
        "qwen_configured": bool(QWEN_API_KEY),
        "files": files_out,
    }


@api_router.get("/projects/{project_id}/whatsapp-checklists")
async def list_project_whatsapp_checklists(
    project_id: str,
    group_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (EST) filter"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
):
    """List WhatsApp-extracted checklists for a project."""
    company_id = get_user_company_id(current_user)
    query: Dict[str, Any] = {
        "project_id": project_id,
        "is_deleted": {"$ne": True},
    }
    if company_id:
        query["company_id"] = company_id
    if group_id:
        query["group_id"] = group_id
    if date:
        try:
            from zoneinfo import ZoneInfo
            eastern = ZoneInfo("America/New_York")
            day_start_est = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=eastern)
            day_start_utc = day_start_est.astimezone(timezone.utc)
            day_end_utc = day_start_utc + timedelta(hours=24)
            query["generated_at"] = {"$gte": day_start_utc, "$lt": day_end_utc}
        except Exception:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    total = await db.whatsapp_checklists.count_documents(query)
    cursor = (
        db.whatsapp_checklists
        .find(query)
        .sort("generated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = []
    async for doc in cursor:
        items.append(serialize_id(doc))
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


@api_router.put("/whatsapp-checklists/{checklist_id}/items/{item_index}")
async def update_whatsapp_checklist_item(
    checklist_id: str,
    item_index: int,
    body: dict,
    current_user=Depends(get_current_user),
):
    """Mark a single item complete/incomplete from the app."""
    if "completed" not in body or not isinstance(body["completed"], bool):
        raise HTTPException(status_code=422, detail="completed (bool) is required")

    doc = await db.whatsapp_checklists.find_one({"_id": to_query_id(checklist_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Checklist not found")

    company_id = get_user_company_id(current_user)
    if company_id and doc.get("company_id") and doc["company_id"] != company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    items = list(doc.get("items") or [])
    if item_index < 0 or item_index >= len(items):
        raise HTTPException(status_code=404, detail="item_index out of range")

    now = datetime.now(timezone.utc)
    items[item_index] = {
        **items[item_index],
        "completed": body["completed"],
        "completed_at": now if body["completed"] else None,
        "completed_by": current_user.get("name") or current_user.get("email") if body["completed"] else None,
    }

    await db.whatsapp_checklists.update_one(
        {"_id": to_query_id(checklist_id)},
        {"$set": {"items": items, "updated_at": now}},
    )
    updated = await db.whatsapp_checklists.find_one({"_id": to_query_id(checklist_id)})
    return serialize_id(updated)


@api_router.get("/whatsapp/contact.vcf")
async def whatsapp_contact_vcard(current_user=Depends(get_current_user)):
    """
    Return a vCard 3.0 for the Levelog Assistant WhatsApp number so the user
    can save it to their native contacts app and add it to WhatsApp groups.
    Requires the caller's company to have an active whatsapp_config.
    """
    company_id = get_user_company_id(current_user)
    if not company_id:
        raise HTTPException(status_code=400, detail="No company associated with this user.")

    wa_config = await db.whatsapp_config.find_one({"company_id": company_id})
    if not wa_config or not wa_config.get("is_active"):
        raise HTTPException(
            status_code=400,
            detail="WhatsApp integration is not active for this company. Activate it first on the integrations page.",
        )

    # Per-company number first, then fall back to env (forward-compatible)
    raw_number = (wa_config.get("whatsapp_number") or "").strip()
    if not raw_number:
        raw_number = os.environ.get("WAAPI_DISPLAY_NUMBER", "").strip()
    if not raw_number:
        raise HTTPException(status_code=500, detail="WhatsApp number is not configured on the server.")

    # Normalize to E.164 (ensure leading +)
    digits = re.sub(r"\D", "", raw_number)
    if not digits:
        raise HTTPException(status_code=500, detail="Invalid WhatsApp number format.")
    e164 = f"+{digits}"

    # vCard 3.0 — CRLF line endings (iOS strict), escape commas/semicolons in NOTE
    note = (
        "Site intelligence assistant. Ask: who is on site, DOB permit status, "
        "open compliance items, material deliveries, and daily summaries."
    ).replace(";", r"\;").replace(",", r"\,")

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "N:Assistant;Levelog;;;",
        "FN:Levelog Assistant",
        "ORG:Levelog",
        "TITLE:Site Intelligence Bot",
        f"TEL;TYPE=CELL,VOICE:{e164}",
        f"X-WHATSAPP:{e164}",
        f"NOTE:{note}",
        "END:VCARD",
    ]
    vcard = "\r\n".join(lines) + "\r\n"

    return Response(
        content=vcard,
        media_type="text/vcard",
        headers={
            "Content-Disposition": 'attachment; filename="levelog-assistant.vcf"',
            "Cache-Control": "no-store",
        },
    )


# ---------- material request endpoints (auth required) ----------

@api_router.get("/projects/{project_id}/material-requests")
async def get_material_requests(project_id: str, status: str = None, current_user=Depends(get_current_user)):
    """Get material requests for a project."""
    query = {"project_id": project_id, "company_id": current_user.get("company_id"), "is_deleted": {"$ne": True}}
    if status:
        query["status"] = status
    requests = await db.material_requests.find(query).sort("created_at", -1).to_list(100)
    for r in requests:
        r["id"] = str(r.pop("_id"))
    return {"requests": requests, "total": len(requests)}


@api_router.put("/material-requests/{request_id}/cancel")
async def cancel_material_request(request_id: str, current_user=Depends(get_current_user)):
    """Cancel a material request (admin only)."""
    if current_user.get("role") not in ("admin", "owner"):
        raise HTTPException(403, "Only admins can cancel material requests")
    result = await db.material_requests.update_one(
        {"_id": to_query_id(request_id), "company_id": current_user.get("company_id")},
        {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc)}}
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Material request not found")
    return {"message": "Material request cancelled"}


# ---------- daily summary scheduler ----------

def _current_est_time_and_date():
    """Return (HH:MM string, ISO weekday 1-7, YYYY-MM-DD date string) in EST/EDT."""
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    now_est = datetime.now(timezone.utc).astimezone(eastern)
    return (
        now_est.strftime("%H:%M"),
        now_est.isoweekday(),  # Mon=1 Sun=7
        now_est.strftime("%Y-%m-%d"),
    )


def _within_30min_window(now_hhmm: str, target_hhmm: str) -> bool:
    """True if now_hhmm is within [target_hhmm, target_hhmm + 30 minutes).

    Computed on whole minutes. A 17:00 target window covers 17:00 through
    17:29 inclusive. A 23:50 target covers 23:50 through 00:19 (wraps).
    """
    try:
        nh, nm = [int(x) for x in now_hhmm.split(":")]
        th, tm = [int(x) for x in target_hhmm.split(":")]
    except Exception:
        return False
    now_minutes = (nh * 60 + nm) % (24 * 60)
    target_minutes = (th * 60 + tm) % (24 * 60)
    diff = (now_minutes - target_minutes) % (24 * 60)
    return 0 <= diff < 30


async def _summarize_and_send_for_group(group_doc: dict) -> None:
    """Build and send a daily summary for one group. Caller handles dedup."""
    project_id = group_doc.get("project_id")
    group_id = group_doc.get("wa_group_id")
    if not project_id or not group_id:
        return

    today_start, today_end = get_today_range_est()
    messages = await db.whatsapp_messages.find({
        "group_id": group_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
    }).sort("created_at", 1).to_list(500)
    if not messages:
        return

    # Build convo text. Skip bot_plan_response messages so the summary
    # doesn't describe the bot's own image sends as if a person said them.
    convo_lines = []
    for m in messages:
        msg_type = m.get("type")
        sender = m.get("sender", "unknown")
        body_text = m.get("body", "")
        if msg_type == "bot_plan_response":
            # Render as a system note, not a human line
            if body_text:
                convo_lines.append(f"[bot sent plan sheet: {body_text}]")
            continue
        if body_text:
            convo_lines.append(f"{sender}: {body_text}")
    if not convo_lines:
        return
    conversation_text = "\n".join(convo_lines[:200])

    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = project.get("name", "Project") if project else "Project"

    if not OPENAI_API_KEY:
        logger.info(f"Daily summary skipped for {project_name}: no OPENAI_API_KEY")
        return

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        gpt_payload = {
            "model": "gpt-4o",
            "temperature": 0.3,
            "max_tokens": 500,
            "messages": [
                {"role": "system", "content": (
                    "You are a construction project assistant. Summarize the day's WhatsApp "
                    "group messages into a concise daily digest. Focus on: key decisions, "
                    "issues raised, action items, and safety concerns. Format with bullet points. "
                    "Keep it under 300 words. Lines wrapped in [brackets] are automated system "
                    "notes, not human messages — treat them as context only."
                )},
                {"role": "user", "content": f"Project: {project_name}\n\nMessages:\n{conversation_text}"},
            ],
        }
        async with ServerHttpClient(timeout=30) as client_http:
            resp = await client_http.post(url, json=gpt_payload, headers=headers)
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"].strip()
        header = f"*Daily Summary - {project_name}*\n_{datetime.now(timezone.utc).strftime('%B %d, %Y')}_\n"
        await send_whatsapp_message(group_id, header + "\n" + summary)
    except Exception as e:
        logger.error(f"Daily summary GPT failed for {project_name}: {e}")


async def _send_whatsapp_daily_summaries():
    """Runs every 30 min. For each active group:
    - skip if bot_enabled == False
    - skip if daily_summary_enabled == False
    - skip if today's ISO weekday not in daily_summary_days
    - skip if current EST time not within [configured_time, +30min)
    - dedup via whatsapp_send_log (MongoDB unique key) so re-fires within
      the window send at most once per day per group.
    """
    try:
        now_hhmm, iso_weekday, today_est = _current_est_time_and_date()
        groups = await db.whatsapp_groups.find({"active": True}).to_list(500)
        for group_doc in groups:
            cfg = group_doc.get("bot_config") or {}
            if not cfg.get("bot_enabled", True):
                continue
            if not cfg.get("daily_summary_enabled", False):
                continue
            days = cfg.get("daily_summary_days", [1, 2, 3, 4, 5])
            if iso_weekday not in (days or []):
                continue
            configured = cfg.get("daily_summary_time", "17:00")
            if not _within_30min_window(now_hhmm, configured):
                continue

            group_id = group_doc.get("wa_group_id")
            if not group_id:
                continue

            # MongoDB-backed dedup — survives restarts.
            first_send = await _whatsapp_send_log_try_mark(
                group_id, "daily_summary", today_est
            )
            if not first_send:
                continue

            try:
                await _summarize_and_send_for_group(group_doc)
            except Exception as e:
                logger.error(f"daily summary send failed for {group_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"WhatsApp daily summary job error: {e}", exc_info=True)


CHECKLIST_SYSTEM_PROMPT = """You are a construction project assistant analyzing WhatsApp group conversations from a NYC construction site.
Extract all action items, commitments, and open issues from the conversation.

For each item found return:
- text: imperative form ("Order 200 sheets of drywall", "Call inspector re: floor 3")
- assigned_to: person name or phone if mentioned, null if unclear
- due_date: specific date or relative term if mentioned, null if none
- category: safety | materials | coordination | inspection | other
- priority: high (safety issues, DOB/inspection, blockers), medium (deliveries, coordination), low (general)

Focus on: explicit requests, commitments made, unresolved issues, safety concerns, inspection prep, material shortages.
Ignore: greetings, already-resolved confirmations, jokes, reactions.

Return ONLY valid JSON: {"items": [...]}
If no action items found return: {"items": []}"""


_CATEGORY_EMOJI = {
    "safety": "⚠️",
    "materials": "📦",
    "coordination": "🤝",
    "inspection": "🔍",
    "other": "•",
}


def _format_checklist_message(project_name: str, items: list) -> str:
    """Produce the WhatsApp-formatted checklist message body."""
    now_est = _current_est_time_and_date()[2]
    high = [i for i in items if (i.get("priority") or "").lower() == "high"]
    med  = [i for i in items if (i.get("priority") or "").lower() == "medium"]
    rest = [i for i in items if (i.get("priority") or "").lower() not in ("high", "medium")]

    lines = [
        f"✅ *Action Items — {project_name}*",
        f"_{now_est}_",
        "",
    ]
    def _render(bucket, header):
        if not bucket:
            return
        lines.append(header)
        for idx_global, it in bucket:
            txt = (it.get("text") or "").strip()
            if not txt:
                continue
            who = (it.get("assigned_to") or "").strip() or "Unassigned"
            lines.append(f"• {idx_global}. {txt} → {who}")
        lines.append("")

    # Assign global 1-based indices matching storage order so "done N"
    # maps to the same slot the user sees.
    indexed = list(enumerate(items, start=1))
    idx_high = [(i, it) for (i, it) in indexed if (it.get("priority") or "").lower() == "high"]
    idx_med  = [(i, it) for (i, it) in indexed if (it.get("priority") or "").lower() == "medium"]
    idx_rest = [(i, it) for (i, it) in indexed if (it.get("priority") or "").lower() not in ("high", "medium")]

    _render(idx_high, "🔴 HIGH PRIORITY")
    _render(idx_med,  "🟡 MEDIUM")
    _render(idx_rest, "⚪ OTHER")

    lines.append(f"_{len(items)} items · Reply \"done 1\" to mark complete_")
    return "\n".join(lines).rstrip()


async def _extract_whatsapp_checklist(project_id: str, group_id: str, conversation_text: str):
    """Call GPT-4o-mini to extract action items from a group conversation,
    persist to whatsapp_checklists, and send a formatted message back to
    the group. No-ops silently if no actionable items are found.
    """
    if not conversation_text or not conversation_text.strip():
        return None
    if not OPENAI_API_KEY:
        logger.info(
            f"checklist extraction skipped (no OPENAI_API_KEY) "
            f"project={project_id} group={group_id}"
        )
        return None

    # Call GPT-4o-mini — structured extraction, forced JSON
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": CHECKLIST_SYSTEM_PROMPT},
                {"role": "user",   "content": conversation_text[:12000]},
            ],
        }
        async with ServerHttpClient(timeout=40.0) as client_http:
            resp = await client_http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(
            f"checklist GPT call failed (project={project_id}, group={group_id}): {e}"
        )
        return None

    # Parse JSON
    try:
        import json as _json
        data = _json.loads(content)
        raw_items = data.get("items") or []
        if not isinstance(raw_items, list):
            raw_items = []
    except Exception:
        logger.warning(
            f"checklist JSON parse failed for project={project_id} group={group_id}"
        )
        return None

    # Normalize + filter
    VALID_CATEGORY = {"safety", "materials", "coordination", "inspection", "other"}
    VALID_PRIORITY = {"high", "medium", "low"}
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        text_val = (raw.get("text") or "").strip()
        if not text_val:
            continue
        category = (raw.get("category") or "other").strip().lower()
        if category not in VALID_CATEGORY:
            category = "other"
        priority = (raw.get("priority") or "low").strip().lower()
        if priority not in VALID_PRIORITY:
            priority = "low"
        items.append({
            "text": text_val[:500],
            "assigned_to": (raw.get("assigned_to") or None),
            "due_date": (raw.get("due_date") or None),
            "category": category,
            "priority": priority,
            "completed": False,
            "completed_at": None,
            "completed_by": None,
        })

    # Empty extraction => no DB write, no message
    if not items:
        logger.info(
            f"checklist extraction yielded 0 items (project={project_id}, group={group_id})"
        )
        return None

    # Lookup project + company info
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    project_name = project.get("name", "Project") if project else "Project"
    company_id = (project.get("company_id") if project else None) or ""

    now_utc = datetime.now(timezone.utc)
    today_start, today_end = get_today_range_est()

    # Count messages in scope for metadata
    source_count = await db.whatsapp_messages.count_documents({
        "group_id": group_id,
        "created_at": {"$gte": today_start, "$lt": today_end},
    })

    doc = {
        "project_id": project_id,
        "company_id": company_id,
        "group_id": group_id,
        "generated_at": now_utc,
        "date_range_start": today_start,
        "date_range_end": today_end,
        "items": items,
        "source_message_count": source_count,
        "is_deleted": False,
    }
    result = await db.whatsapp_checklists.insert_one(doc)

    # Format + send to group
    try:
        message = _format_checklist_message(project_name, items)
        await send_whatsapp_message(group_id, message)
    except Exception as e:
        logger.error(
            f"checklist send failed (project={project_id}, group={group_id}): {e}"
        )

    return str(result.inserted_id)


async def _run_whatsapp_checklist_extractions():
    """Runs every 30 min. Finds groups configured for daily checklist extraction
    whose configured time matches the current EST window, dedups via send_log,
    and calls _extract_whatsapp_checklist."""
    try:
        now_hhmm, _iso_weekday, today_est = _current_est_time_and_date()
        groups = await db.whatsapp_groups.find({"active": True}).to_list(500)
        for group_doc in groups:
            cfg = group_doc.get("bot_config") or {}
            if not cfg.get("bot_enabled", True):
                continue
            if not cfg.get("checklist_extraction_enabled", False):
                continue
            if cfg.get("checklist_frequency", "daily") != "daily":
                continue
            configured = cfg.get("checklist_time", "16:00")
            if not _within_30min_window(now_hhmm, configured):
                continue

            group_id = group_doc.get("wa_group_id")
            project_id = group_doc.get("project_id")
            if not group_id or not project_id:
                continue

            first_send = await _whatsapp_send_log_try_mark(
                group_id, "checklist", today_est
            )
            if not first_send:
                continue

            # Build conversation text for the last 24 hours
            today_start, today_end = get_today_range_est()
            messages = await db.whatsapp_messages.find({
                "group_id": group_id,
                "created_at": {"$gte": today_start, "$lt": today_end},
            }).sort("created_at", 1).to_list(500)
            convo_lines = []
            for m in messages:
                if m.get("type") == "bot_plan_response":
                    continue
                sender = m.get("sender", "unknown")
                body_text = m.get("body", "")
                if body_text:
                    convo_lines.append(f"{sender}: {body_text}")
            if not convo_lines:
                continue
            convo_text = "\n".join(convo_lines[:400])

            try:
                await _extract_whatsapp_checklist(project_id, group_id, convo_text)
            except Exception as e:
                logger.error(f"checklist extraction failed for {group_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"WhatsApp checklist scheduler error: {e}", exc_info=True)


# Card audit VLM adapter. Feeds a raw (jpeg_bytes, prompt) pair into
# the Qwen2.5-VL chat/completions API and returns the assistant's text.
# Kept here rather than in card_audit.py so the module stays free of
# direct httpx + QWEN_API_KEY coupling.
async def _card_audit_vlm_adapter(jpeg_bytes: bytes, prompt: str) -> str:
    """Used by card_audit.enrollment_parse_card to extract card fields."""
    if not QWEN_API_KEY or not jpeg_bytes:
        return ""
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    try:
        async with ServerHttpClient(timeout=60.0) as client_http:
            resp = await client_http.post(
                f"{QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": QWEN_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }],
                    "temperature": 0.0,
                    "max_tokens": 400,
                },
            )
        if resp.status_code != 200:
            logger.warning(
                f"card_audit VLM {resp.status_code}: {resp.text[:300]!r}"
            )
            return ""
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:
        logger.error(f"card_audit VLM adapter failed: {e!r}")
        return ""


# ════════════════════════════════════════════════════════════════════
# MR.5 — INTERNAL endpoints for the local dob_worker.
# ════════════════════════════════════════════════════════════════════
# Three endpoints, all gated by X-Worker-Secret header. Optional
# cf-access-jwt validation is accepted but not yet enforced (v2 makes
# it mandatory). All under /api/internal/* — never reachable by user
# tokens; only the worker hits these.

WORKER_SECRET = os.environ.get("WORKER_SECRET", "")


def _validate_worker_secret(request: Request):
    """Reject if X-Worker-Secret header doesn't match. Constant-time
    comparison via secrets.compare_digest to defeat timing attacks
    on the secret length / prefix."""
    import secrets as _secrets
    if not WORKER_SECRET:
        # Backend env not configured — refuse all worker traffic
        # rather than silently accept (the worker would then succeed
        # with an empty header).
        raise HTTPException(
            status_code=503,
            detail="Worker integration not configured (WORKER_SECRET unset)",
        )
    presented = request.headers.get("X-Worker-Secret", "")
    if not _secrets.compare_digest(presented, WORKER_SECRET):
        raise HTTPException(status_code=401, detail="Invalid worker secret")


@api_router.post("/internal/permit-renewal-claim")
async def internal_permit_renewal_claim(
    request: Request,
    body: dict,
):
    """Worker calls this BEFORE running a dob_now_filing handler.
    Records a claim on the renewal so the stale-claim watchdog can
    return it to the queue if the worker crashes. Returns 200 if
    claimed, 409 if the renewal is already in a non-claimable state
    ({IN_PROGRESS, AWAITING_DOB_APPROVAL, COMPLETED, FAILED})."""
    _validate_worker_secret(request)
    permit_renewal_id = body.get("permit_renewal_id")
    worker_id = body.get("worker_id") or "unknown"
    if not permit_renewal_id:
        raise HTTPException(status_code=400, detail="permit_renewal_id required")
    from permit_renewal import RenewalStatus
    NON_CLAIMABLE = {
        RenewalStatus.IN_PROGRESS,
        RenewalStatus.AWAITING_DOB_APPROVAL,
        RenewalStatus.COMPLETED,
        RenewalStatus.FAILED,
    }
    renewal = await db.permit_renewals.find_one({"_id": to_query_id(permit_renewal_id)})
    if not renewal:
        raise HTTPException(status_code=404, detail="Renewal not found")
    if renewal.get("status") in NON_CLAIMABLE:
        raise HTTPException(
            status_code=409,
            detail=f"Renewal in non-claimable status {renewal.get('status')!r}",
        )
    now = datetime.now(timezone.utc)
    await db.permit_renewals.update_one(
        {"_id": to_query_id(permit_renewal_id)},
        {"$set": {
            "status": RenewalStatus.IN_PROGRESS,
            "claim_at": now,
            "claimed_by_worker_id": worker_id,
            "updated_at": now,
        }},
    )
    return {"claimed": True, "permit_renewal_id": permit_renewal_id}


@api_router.post("/internal/job-result")
async def internal_job_result(request: Request, body: dict):
    """Worker calls this after every handler completes. Cloud
    transitions BOTH the filing_jobs doc (when filing_job_id is on
    the result, MR.6+) AND the permit_renewals doc (existing MR.5
    behavior) based on result.status.

    Worker contract for filing_job_id propagation: handlers carry the
    filing_job_id from the queue payload through to the result. If
    the field is absent on the result body (legacy bis_scrape jobs,
    or in-flight MR.5-vintage runs that pre-date MR.6), the
    filing_jobs branch is skipped.

    Cancellation handling: if cancellation_requested=True on the
    filing_job, we record the result as 'cancelled' regardless of
    what the worker reported — operator intent wins. The worker
    contract is to short-circuit before posting result when it sees
    cancellation_requested, but we double-check here so a
    well-behaved worker that reports 'completed' on a cancelled job
    doesn't undo the operator's cancel.
    """
    _validate_worker_secret(request)
    from permit_renewal import RenewalStatus

    job_id = body.get("job_id") or "unknown"
    job_type = body.get("job_type") or "unknown"
    permit_renewal_id = body.get("permit_renewal_id")
    filing_job_id = body.get("filing_job_id")  # MR.6 — set by dob_now_filing handler
    result = body.get("result") or {}
    status_value = (result.get("status") or "").lower()
    worker_id = body.get("worker_id") or "unknown_worker"
    now = datetime.now(timezone.utc)

    # Audit log every result regardless of state-transition.
    await db.agent_job_results.insert_one({
        "job_id": job_id,
        "job_type": job_type,
        "permit_renewal_id": permit_renewal_id,
        "filing_job_id": filing_job_id,
        "worker_id": body.get("worker_id"),
        "result": result,
        "received_at": now,
    })

    # ── MR.6: filing_jobs state machine ──────────────────────────────
    # When filing_job_id is set, transition the FilingJob doc and
    # append an audit-log entry. Do this BEFORE the permit_renewals
    # transition so the FilingJob is the canonical source for the job
    # result; if the renewal update fails we still have the audit.
    filing_job_transitioned = False
    if filing_job_id:
        existing_job = await db.filing_jobs.find_one({"_id": filing_job_id})
        if existing_job:
            current_status = existing_job.get("status")
            cancellation_requested = bool(
                existing_job.get("cancellation_requested")
            )

            # Cancellation override: if the operator requested cancel
            # while this job was in-flight, force the resolution to
            # CANCELLED regardless of what the worker reports. The
            # well-behaved worker should already have detected the
            # flag and reported status=cancelled itself; this branch
            # handles the misbehaving / racing worker.
            if cancellation_requested and current_status not in FILING_JOB_TERMINAL_STATUSES:
                effective_status = FilingJobStatus.CANCELLED.value
                effective_event_type = "cancelled"
                effective_detail = (
                    f"Worker reported {status_value!r} but cancellation was "
                    f"requested by operator; resolving as cancelled."
                )
            else:
                # Map worker-reported status → FilingJobStatus value.
                worker_to_filing_status = {
                    "filed":     FilingJobStatus.FILED.value,
                    "completed": FilingJobStatus.COMPLETED.value,
                    "failed":    FilingJobStatus.FAILED.value,
                    "cancelled": FilingJobStatus.CANCELLED.value,
                }
                effective_status = worker_to_filing_status.get(status_value)
                effective_event_type = status_value or "unknown"
                effective_detail = (
                    result.get("detail") or f"Worker reported {status_value!r}"
                )

            if effective_status is not None:
                set_fields: Dict[str, Any] = {
                    "status": effective_status,
                    "updated_at": now,
                }
                # Status-specific bookkeeping.
                if effective_status in FILING_JOB_TERMINAL_STATUSES:
                    set_fields["completed_at"] = now
                if effective_status == FilingJobStatus.FAILED.value:
                    set_fields["failure_reason"] = result.get("detail")
                # DOB confirmation number, if present, is preserved
                # regardless of status — useful even on FAILED jobs
                # where DOB returned a confirmation before rejecting.
                confirmation = result.get("dob_confirmation_number")
                if confirmation:
                    set_fields["dob_confirmation_number"] = confirmation

                audit_event = _filing_job_audit_event(
                    event_type=effective_event_type,
                    actor=worker_id,
                    detail=effective_detail,
                    metadata={
                        k: v for k, v in {
                            "dob_confirmation_number": confirmation,
                            "worker_reported_status": status_value,
                        }.items() if v is not None
                    },
                )
                await db.filing_jobs.update_one(
                    {"_id": filing_job_id},
                    {
                        "$set": set_fields,
                        "$push": {"audit_log": audit_event},
                    },
                )
                filing_job_transitioned = True

    # bis_scrape jobs don't touch renewals — log and return.
    if not permit_renewal_id:
        return {"recorded": True, "filing_job_transitioned": filing_job_transitioned}

    transitions = {
        "filed":     RenewalStatus.AWAITING_DOB_APPROVAL,
        "completed": RenewalStatus.COMPLETED,
        "failed":    RenewalStatus.FAILED,
    }
    new_status = transitions.get(status_value)
    if new_status is None:
        # not_implemented / cancelled / unknown — no permit_renewals state change.
        return {
            "recorded": True,
            "transitioned": False,
            "filing_job_transitioned": filing_job_transitioned,
        }

    update_set = {
        "status": new_status,
        "updated_at": now,
    }
    if status_value == "filed":
        update_set["filed_at"] = now
    elif status_value == "completed":
        update_set["completed_at"] = now
    elif status_value == "failed":
        update_set["failure_reason"] = result.get("detail")
    # MR.6 — propagate confirmation number to the renewal doc too,
    # so the existing UI surfaces it without joining filing_jobs.
    confirmation = result.get("dob_confirmation_number")
    if confirmation:
        update_set["dob_confirmation_number"] = confirmation

    await db.permit_renewals.update_one(
        {"_id": to_query_id(permit_renewal_id)},
        {"$set": update_set},
    )
    return {
        "recorded": True,
        "transitioned": True,
        "new_status": new_status.value,
        "filing_job_transitioned": filing_job_transitioned,
    }


@api_router.post("/internal/agent-heartbeat")
async def internal_agent_heartbeat(request: Request, body: dict):
    """Worker posts state every 60s. Upsert one doc per worker_id
    so heartbeat-watchdog can read the latest value cheaply."""
    _validate_worker_secret(request)
    worker_id = body.get("worker_id")
    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id required")
    await db.agent_heartbeats.update_one(
        {"_id": worker_id},
        {"$set": {
            **body,
            "received_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return {"received": True}


@api_router.get("/internal/filing-jobs/{filing_job_id}")
async def internal_get_filing_job(filing_job_id: str, request: Request):
    """MR.11 Bug 2 fix — worker-tier read of a single FilingJob doc.

    Why this exists: the dob_now_filing handler's _check_cancellation
    path needs to read the latest FilingJob (specifically the
    `cancellation_requested` flag and the `audit_log` for
    operator_response polling). The matching READ surface that
    already exists for operators is
    `GET /api/permit-renewals/{id}/filing-jobs`, but that endpoint
    is gated by Depends(get_current_user) — bearer/cookie auth that
    the worker doesn't carry. The worker has only X-Worker-Secret.

    Worker calls were 401-ing silently; _check_cancellation soft-
    failed to "not cancelled" and the handler proceeded with already-
    cancelled jobs. This internal-tier endpoint pairs the same data
    the operator-tier returns with worker-tier auth, closing the gap.

    Defensive ciphertext strip on output (mirrors the operator-tier
    serializer in permit_renewal.py:_serialize_filing_job) — schema
    doesn't carry ciphertext on filing_jobs but the strip is belt-
    and-suspenders against future drift."""
    _validate_worker_secret(request)
    job = await db.filing_jobs.find_one(
        {"_id": filing_job_id, "is_deleted": {"$ne": True}}
    )
    if not job:
        raise HTTPException(status_code=404, detail="FilingJob not found")
    out = serialize_id(dict(job))
    out.pop("encrypted_ciphertext", None)
    return out


@api_router.post("/internal/filing-job-event")
async def internal_filing_job_event(request: Request, body: dict):
    """MR.11 — worker-side audit-log append for mid-flight events.

    Lets the worker raise events the UI needs to show (claimed,
    started, captcha_required, 2fa_required, etc.) WITHOUT going
    through the terminal /job-result path. The matching operator
    response flows back through MR.7's /operator-input endpoint;
    the worker polls audit_log via the existing
    GET /api/permit-renewals/{id}/filing-jobs to consume it.

    Body: {filing_job_id, event_type, actor?, detail?, metadata?}.
    Auth: X-Worker-Secret (same as the other /internal/* endpoints).

    Why this endpoint: MR.7 documented the worker-side challenge
    contract but no append mechanism shipped. The /job-result
    endpoint only $push-es audit events for terminal status
    transitions (filed/completed/failed/cancelled); intermediate
    events were unreachable by the worker. MR.11 needs them for
    the 2FA/CAPTCHA prompt round-trip.
    """
    _validate_worker_secret(request)
    filing_job_id = body.get("filing_job_id")
    event_type = body.get("event_type")
    if not filing_job_id or not event_type:
        raise HTTPException(
            status_code=400,
            detail="filing_job_id and event_type are required",
        )
    actor = body.get("actor") or "worker"
    detail = body.get("detail") or ""
    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=400,
            detail="metadata must be an object if provided",
        )

    event = _filing_job_audit_event(
        event_type=event_type,
        actor=actor,
        detail=detail,
        metadata=metadata,
    )
    result = await db.filing_jobs.update_one(
        {"_id": filing_job_id, "is_deleted": {"$ne": True}},
        {
            "$set": {"updated_at": event["timestamp"]},
            "$push": {"audit_log": event},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="filing_job not found")
    return {
        "appended": True,
        "filing_job_id": filing_job_id,
        "event_type": event_type,
    }


# ── Watchdog jobs (scheduled at startup, see startup_event) ───────

async def _stale_claim_watchdog():
    """Every 5 min: clean up stuck claims in two collections.

    permit_renewals (MR.5): IN_PROGRESS rows with claim_at >30 min
    ago revert to ELIGIBLE; the bookkeeping fields are unset.

    filing_jobs (MR.6): jobs in {claimed, in_progress} with
    claimed_at OR started_at >30 min ago either:
      - retry_count < FILING_JOB_RETRY_LIMIT: revert to QUEUED,
        retry_count++, audit-log "stale_claim_recovered" — operator's
        next enqueue or the cron re-fires the job;
      - retry_count >= FILING_JOB_RETRY_LIMIT: mark FAILED with
        failure_reason="exceeded_retry_limit", audit-log
        "retry_limit_exceeded".
    Recovery is per-doc, not bulk update_many, because the audit_log
    $push needs the per-doc retry_count to compute the next state.
    """
    try:
        from permit_renewal import RenewalStatus
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        now = datetime.now(timezone.utc)

        # ── permit_renewals (MR.5 behavior, unchanged) ──────────────
        result = await db.permit_renewals.update_many(
            {
                "status": RenewalStatus.IN_PROGRESS,
                "claim_at": {"$lt": cutoff},
                "is_deleted": {"$ne": True},
            },
            {"$set": {
                # Revert to ELIGIBLE so the next eligibility scan or
                # operator trigger can re-prepare. Drop the claim
                # bookkeeping fields.
                "status": RenewalStatus.ELIGIBLE,
                "stale_claim_cleared_at": now,
                "updated_at": now,
            }, "$unset": {"claim_at": "", "claimed_by_worker_id": ""}},
        )
        if result.modified_count > 0:
            logger.warning(
                "[stale_claim_watchdog] cleared %d stale renewal claims",
                result.modified_count,
            )

        # ── filing_jobs (MR.6 behavior) ──────────────────────────────
        # Find candidates: in-flight statuses with stale claim/start.
        stale_jobs_cursor = db.filing_jobs.find({
            "status": {"$in": list(FILING_JOB_INFLIGHT_STATUSES)},
            "is_deleted": {"$ne": True},
            "$or": [
                {"claimed_at": {"$lt": cutoff}},
                {"started_at": {"$lt": cutoff}},
            ],
        })
        recovered = 0
        gave_up = 0
        async for job in stale_jobs_cursor:
            job_id = job.get("_id")
            current_retry = int(job.get("retry_count") or 0)

            if current_retry < FILING_JOB_RETRY_LIMIT:
                # Revert to queued for re-enqueue. Retry counter ticks
                # up; bookkeeping fields are cleared so the next claim
                # starts clean.
                event = _filing_job_audit_event(
                    event_type="stale_claim_recovered",
                    actor="system",
                    detail=(
                        f"Watchdog reverted stale {job.get('status')!r} claim "
                        f"to queued (retry {current_retry + 1}/{FILING_JOB_RETRY_LIMIT})"
                    ),
                    metadata={
                        "previous_status": job.get("status"),
                        "previous_worker_id": job.get("claimed_by_worker_id"),
                        "previous_retry_count": current_retry,
                    },
                )
                await db.filing_jobs.update_one(
                    {"_id": job_id},
                    {
                        "$set": {
                            "status": FilingJobStatus.QUEUED.value,
                            "retry_count": current_retry + 1,
                            "claimed_by_worker_id": None,
                            "claimed_at": None,
                            "started_at": None,
                            "updated_at": now,
                        },
                        "$push": {"audit_log": event},
                    },
                )
                recovered += 1
                # Note: re-LPUSH onto Redis is the responsibility of
                # the next operator enqueue OR a future periodic
                # re-enqueue cron. The watchdog only owns the cloud-
                # side state revert. This is intentional — we don't
                # want the watchdog to silently re-LPUSH a job whose
                # snapshot might have been invalidated by intervening
                # data changes (credential rotated, readiness gate
                # would now fail, etc.). MR.7's UI surfaces these
                # back-to-queued jobs so the operator can decide.
            else:
                # Retry cap hit → terminal failure.
                event = _filing_job_audit_event(
                    event_type="retry_limit_exceeded",
                    actor="system",
                    detail=(
                        f"Watchdog gave up after {current_retry} retries; "
                        f"marking job failed."
                    ),
                    metadata={
                        "retry_count": current_retry,
                        "limit": FILING_JOB_RETRY_LIMIT,
                    },
                )
                await db.filing_jobs.update_one(
                    {"_id": job_id},
                    {
                        "$set": {
                            "status": FilingJobStatus.FAILED.value,
                            "failure_reason": "exceeded_retry_limit",
                            "completed_at": now,
                            "updated_at": now,
                        },
                        "$push": {"audit_log": event},
                    },
                )
                gave_up += 1

        if recovered or gave_up:
            logger.warning(
                "[stale_claim_watchdog] filing_jobs: recovered=%d gave_up=%d",
                recovered, gave_up,
            )
    except Exception as e:
        logger.error(f"[stale_claim_watchdog] error: {e!r}")


async def _heartbeat_watchdog():
    """Every 5 min: flag workers as degraded when no heartbeat in
    >30 min. Stores per-worker degraded flags in system_status.
    Email escalation lands in MR.9; MR.5 surfaces the flag only."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        recent = db.agent_heartbeats.find(
            {}, {"_id": 1, "received_at": 1},
        )
        async for hb in recent:
            received_at = hb.get("received_at")
            worker_id = hb.get("_id")
            if not isinstance(received_at, datetime):
                continue
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            degraded = received_at < cutoff
            await db.system_status.update_one(
                {"_id": f"agent_heartbeat:{worker_id}"},
                {"$set": {
                    "worker_id": worker_id,
                    "degraded": degraded,
                    "last_heartbeat_at": received_at,
                    "checked_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
    except Exception as e:
        logger.error(f"[heartbeat_watchdog] error: {e!r}")


# ── MR.8: DOB approval watcher ─────────────────────────────────────
# Closes the post-filing tracking loop. Once MR.6's worker reports
# status=filed, the renewal sits in AWAITING_DOB_APPROVAL until DOB
# stamps the new expiration on the underlying permit. This watcher
# polls dob_logs (refreshed independently by nightly_dob_scan) and
# transitions the renewal to COMPLETED when dob_log.expiration_date
# advances past renewal.current_expiration.
#
# Cadence: every 30 min. Same interval as nightly_dob_scan but a
# different concern: nightly_dob_scan REFRESHES dob_logs from NYC
# Open Data; this watcher CONSUMES the refreshed data to drive
# renewal state. They're complementary — running both at 30 min
# means worst-case latency from DOB stamping to operator-visible
# completion is ~60 min (one cycle to refresh dob_logs + one cycle
# for the watcher to read it). Acceptable for a renewal that's
# already 5–10 business days into DOB processing.
#
# Idempotency:
#   • Completion transition: only fires when status is currently
#     AWAITING_DOB_APPROVAL. Once flipped to COMPLETED, the renewal
#     is filtered out of subsequent watcher runs by the status query.
#   • Stuck-at-DOB event: the audit_log is scanned for an existing
#     `stuck_at_dob` event before append — re-running the watcher
#     does not duplicate. The event is appended exactly once per
#     stuck renewal.

DOB_APPROVAL_STUCK_THRESHOLD_DAYS = 14


def _safe_parse_date(value) -> Optional[datetime]:
    """Robust date parser used by the watcher. Accepts strings (ISO,
    M/D/YYYY, M-D-YYYY, etc.) and datetime objects. Returns None on
    parse failure rather than raising — the watcher logs and skips."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(str(value))
    except Exception:
        return None


async def _append_filing_job_audit_event(
    permit_renewal_id: str,
    event: dict,
    *,
    update_status: Optional[str] = None,
    extra_set_fields: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Find the most recent FilingJob for a renewal and $push the event.
    Optionally also set FilingJob.status and other fields atomically.
    Returns the filing_job_id touched, or None if no FilingJob exists
    (e.g. renewal was filed via the legacy MR.1 path before MR.6)."""
    job = await db.filing_jobs.find_one(
        {
            "permit_renewal_id": permit_renewal_id,
            "is_deleted": {"$ne": True},
        },
        sort=[("created_at", -1)],
    )
    if not job:
        return None
    set_fields: Dict[str, Any] = {"updated_at": event["timestamp"]}
    if update_status:
        set_fields["status"] = update_status
    if extra_set_fields:
        set_fields.update(extra_set_fields)
    await db.filing_jobs.update_one(
        {"_id": job["_id"]},
        {
            "$set": set_fields,
            "$push": {"audit_log": event},
        },
    )
    return str(job["_id"])


async def dob_approval_watcher():
    """Every 30 min: detect renewal completion in DOB data and
    transition AWAITING_DOB_APPROVAL → COMPLETED. Also surfaces a
    stuck-at-DOB signal for renewals waiting >14 days.

    Per-renewal exceptions are caught and logged so one bad row
    doesn't kill the cycle. The cycle itself is wrapped in a
    blanket try/except for the same reason — apscheduler should
    never see a raise from this job."""
    try:
        from permit_renewal import RenewalStatus
    except ModuleNotFoundError:
        from backend.permit_renewal import RenewalStatus

    try:
        now = datetime.now(timezone.utc)
        stuck_threshold = now - timedelta(days=DOB_APPROVAL_STUCK_THRESHOLD_DAYS)

        cursor = db.permit_renewals.find({
            "status": RenewalStatus.AWAITING_DOB_APPROVAL.value,
            "is_deleted": {"$ne": True},
        })

        confirmed = 0
        stuck_appended = 0
        skipped = 0

        async for renewal in cursor:
            try:
                renewal_id = renewal.get("_id")
                permit_dob_log_id = renewal.get("permit_dob_log_id")
                if not permit_dob_log_id:
                    logger.warning(
                        "[dob_approval_watcher] renewal %s has no "
                        "permit_dob_log_id; skipping",
                        renewal_id,
                    )
                    skipped += 1
                    continue

                dob_log = await db.dob_logs.find_one(
                    {"_id": to_query_id(permit_dob_log_id)}
                )
                if not dob_log:
                    logger.warning(
                        "[dob_approval_watcher] dob_log %s not found for "
                        "renewal %s; skipping",
                        permit_dob_log_id, renewal_id,
                    )
                    skipped += 1
                    continue

                old_exp_str = renewal.get("current_expiration")
                new_exp_str = dob_log.get("expiration_date")
                old_exp = _safe_parse_date(old_exp_str)
                new_exp = _safe_parse_date(new_exp_str)

                if old_exp is None or new_exp is None:
                    # Can't compare. Don't promote, don't add stuck
                    # (we don't have data for that judgment either).
                    skipped += 1
                    continue

                # Compare as dates only — permit expirations are
                # calendar dates; ignoring time-of-day sidesteps
                # tz-aware-vs-naive comparison errors.
                if new_exp.date() > old_exp.date():
                    # Renewal complete.
                    transition_event = {
                        "event_type": "renewal_confirmed_in_dob",
                        "timestamp": now,
                        "actor": "dob_approval_watcher",
                        "detail": (
                            f"DOB stamped new expiration {new_exp_str} "
                            f"(was {old_exp_str})"
                        ),
                        "metadata": {
                            "old_expiration": old_exp_str,
                            "new_expiration": new_exp_str,
                        },
                    }
                    # Update the renewal first; FilingJob update
                    # follows. If the FilingJob update fails, the
                    # renewal is still correctly transitioned —
                    # operator-visible state is the priority.
                    await db.permit_renewals.update_one(
                        {"_id": renewal_id},
                        {"$set": {
                            "status": RenewalStatus.COMPLETED.value,
                            "completed_at": now,
                            "new_expiration_date": new_exp_str,
                            "updated_at": now,
                        }},
                    )
                    try:
                        from permit_renewal import RenewalStatus as _RS  # local re-bind for closure clarity
                        await _append_filing_job_audit_event(
                            permit_renewal_id=str(renewal_id),
                            event=transition_event,
                            update_status="completed",
                            extra_set_fields={"completed_at": now},
                        )
                    except Exception as fj_err:
                        logger.warning(
                            "[dob_approval_watcher] renewal %s transitioned "
                            "to completed but FilingJob audit append failed: %r",
                            renewal_id, fj_err,
                        )
                    confirmed += 1
                    logger.info(
                        "[dob_approval_watcher] renewal %s completed: "
                        "%s -> %s",
                        renewal_id, old_exp_str, new_exp_str,
                    )
                    # MR.9: fire the completion notification. The hook
                    # is best-effort — a Resend failure or feature-flag
                    # suppression must not crash the watcher cycle.
                    try:
                        await _send_renewal_notification_hook(
                            renewal,
                            trigger_type="renewal_completed",
                            extra_context={
                                "new_expiration": new_exp_str,
                                "old_expiration": old_exp_str,
                            },
                        )
                    except Exception as hook_err:
                        logger.warning(
                            "[dob_approval_watcher] completion hook failed "
                            "for renewal %s: %r",
                            renewal_id, hook_err,
                        )
                    continue

                # Still waiting. Check stuck-at-DOB threshold.
                created_at = renewal.get("created_at")
                if isinstance(created_at, str):
                    created_at = _safe_parse_date(created_at)
                if isinstance(created_at, datetime) and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                if created_at and created_at < stuck_threshold:
                    # Idempotency: only append the stuck event if
                    # the most recent FilingJob's audit_log doesn't
                    # already carry one. Walk back-to-front; first
                    # match short-circuits.
                    fj = await db.filing_jobs.find_one(
                        {
                            "permit_renewal_id": str(renewal_id),
                            "is_deleted": {"$ne": True},
                        },
                        sort=[("created_at", -1)],
                    )
                    if fj is None:
                        # No FilingJob to attach to (legacy renewal).
                        # Skip silently — the renewal-level state on
                        # the `created_at` age is enough for the
                        # operator to see it's stuck.
                        continue
                    already = any(
                        ev.get("event_type") == "stuck_at_dob"
                        for ev in (fj.get("audit_log") or [])
                    )
                    if already:
                        continue
                    days_stuck = int(
                        (now - created_at).total_seconds() // 86400
                    )
                    stuck_event = {
                        "event_type": "stuck_at_dob",
                        "timestamp": now,
                        "actor": "dob_approval_watcher",
                        "detail": (
                            f"Renewal still awaiting DOB approval after "
                            f"{days_stuck} days. Operator should check "
                            f"DOB NOW manually."
                        ),
                        "metadata": {
                            "days_stuck": days_stuck,
                            "old_expiration": old_exp_str,
                            "current_dob_expiration": new_exp_str,
                        },
                    }
                    await db.filing_jobs.update_one(
                        {"_id": fj["_id"]},
                        {
                            "$set": {"updated_at": now},
                            "$push": {"audit_log": stuck_event},
                        },
                    )
                    stuck_appended += 1
                    logger.info(
                        "[dob_approval_watcher] stuck_at_dob appended for "
                        "renewal %s (days_stuck=%d)",
                        renewal_id, days_stuck,
                    )
                    # MR.9: fire the stuck notification. Idempotency
                    # in send_notification + the audit-log dedup above
                    # together ensure exactly-one-email per stuck
                    # renewal per recipient (per 23h window).
                    try:
                        await _send_renewal_notification_hook(
                            renewal,
                            trigger_type="filing_stuck",
                            extra_context={
                                "days_stuck": days_stuck,
                            },
                        )
                    except Exception as hook_err:
                        logger.warning(
                            "[dob_approval_watcher] stuck hook failed "
                            "for renewal %s: %r",
                            renewal_id, hook_err,
                        )
            except Exception as per_err:
                logger.error(
                    "[dob_approval_watcher] error on renewal %s: %r",
                    renewal.get("_id"), per_err,
                )
                continue

        if confirmed or stuck_appended or skipped:
            logger.info(
                "[dob_approval_watcher] cycle: confirmed=%d "
                "stuck_appended=%d skipped=%d",
                confirmed, stuck_appended, skipped,
            )
    except Exception as e:
        logger.error(f"[dob_approval_watcher] cycle error: {e!r}")


# ── MR.9: Notification cron + watcher hooks ────────────────────────
# Daily 7am ET reminder cron walks active renewals and sends T-30,
# T-14, and T-7 reminder emails. The MR.8 watcher hooks (stuck +
# completed) live in the watcher itself; see _maybe_send_notification
# below for the shared adapter.

# Reminder-eligible renewal statuses: those where the OPERATOR still
# needs to act. We exclude statuses where the system has already
# taken over (awaiting_dob_filing, awaiting_dob_approval, in_progress)
# because the stuck-at-DOB notification covers escalation in those
# cases. Also excludes terminal (completed/failed). Sending T-30 to a
# renewal that's already filed just confuses the operator.
REMINDER_ELIGIBLE_STATUSES = {
    "eligible",
    "needs_insurance",
    "ineligible_insurance",
    "ineligible_license",
    "draft_ready",
    "awaiting_gc",
}


# Time windows for the three reminders. Each is (lower_days_inclusive,
# upper_days_exclusive) such that a renewal expiring exactly N days
# from today falls into the window centered on N. The 2-day windows
# are deliberately wider than the 1-day cron cadence so a missed run
# (e.g. backend redeploy) doesn't drop a reminder; idempotency
# (notification_log) prevents duplicate sends across consecutive runs.
REMINDER_WINDOWS = [
    ("renewal_t_minus_30", 29, 31, 30),  # name, low, high, label_days
    ("renewal_t_minus_14", 13, 15, 14),
    ("renewal_t_minus_7",   6,  8,  7),
]


async def _renewal_reminder_context(renewal: dict, days_until: int) -> dict:
    """Build the email context dict for a renewal. Loads the project
    + dob_log so the email shows job_number, work_type, address.
    Best-effort — missing references render as "—" rather than raise."""
    project = None
    dob_log = None
    try:
        if renewal.get("project_id"):
            project = await db.projects.find_one(
                {"_id": to_query_id(renewal.get("project_id"))}
            )
    except Exception:
        project = None
    try:
        if renewal.get("permit_dob_log_id"):
            dob_log = await db.dob_logs.find_one(
                {"_id": to_query_id(renewal.get("permit_dob_log_id"))}
            )
    except Exception:
        dob_log = None

    from lib.notifications import build_action_link

    return {
        "project_name": (project or {}).get("name") or (project or {}).get("address") or "—",
        "project_address": (project or {}).get("address") or "—",
        "permit_job_number": (
            (dob_log or {}).get("job_number")
            or renewal.get("job_number")
            or "—"
        ),
        "permit_work_type": (dob_log or {}).get("work_type") or renewal.get("permit_type") or "—",
        "current_expiration": renewal.get("current_expiration") or "—",
        "days_until_expiry": days_until,
        "action_link": build_action_link(
            project_id=str(renewal.get("project_id") or ""),
            permit_dob_log_id=str(renewal.get("permit_dob_log_id") or "") or None,
        ),
    }


async def _send_reminder_for_renewal(
    renewal: dict,
    *,
    trigger_type: str,
    days_until: int,
):
    """Fire one notification per recipient for a single renewal at a
    single trigger type. Recipients come from filing_reps + admin
    user; see lib.notifications.collect_notification_recipients.

    All sends go through send_notification — feature flag, idempotency,
    and notification_log writes are handled there."""
    from lib.notifications import (
        send_notification,
        collect_notification_recipients,
    )
    from lib.email_templates import render_for_trigger

    company_id = renewal.get("company_id")
    if not company_id:
        logger.warning(
            "[renewal_reminder_cron] renewal %s has no company_id; skipping",
            renewal.get("_id"),
        )
        return

    recipients = await collect_notification_recipients(db, str(company_id))
    if not recipients:
        logger.info(
            "[renewal_reminder_cron] no recipients for renewal %s "
            "(company %s); skipping",
            renewal.get("_id"), company_id,
        )
        return

    permit_renewal_id = str(renewal.get("_id"))

    base_context = await _renewal_reminder_context(renewal, days_until)
    for recipient in recipients:
        ctx = dict(base_context)
        # Recipient-specific name lookup: try to find the matching
        # filing_rep by email. Falls back to the email handle
        # (text before @) so the email feels addressed even when
        # we can't match a name.
        ctx["recipient_name"] = recipient.split("@", 1)[0]
        try:
            company_doc = await db.companies.find_one(
                {"_id": to_query_id(company_id)}
            )
            if company_doc:
                for rep in (company_doc.get("filing_reps") or []):
                    if (rep.get("email") or "").lower() == recipient:
                        ctx["recipient_name"] = rep.get("name") or ctx["recipient_name"]
                        break
        except Exception:
            pass

        try:
            subject, html, text = render_for_trigger(trigger_type, ctx)
        except Exception as render_err:
            logger.error(
                "[renewal_reminder_cron] template render failed "
                "trigger=%s renewal=%s: %r",
                trigger_type, permit_renewal_id, render_err,
            )
            continue

        try:
            await send_notification(
                db,
                permit_renewal_id=permit_renewal_id,
                trigger_type=trigger_type,
                recipient=recipient,
                subject=subject,
                html=html,
                text=text,
                metadata={"days_until_expiry": days_until},
            )
        except Exception as send_err:
            # send_notification handles its own logging + status;
            # this is defensive against unexpected raises.
            logger.error(
                "[renewal_reminder_cron] send_notification raised "
                "trigger=%s renewal=%s recipient=%s: %r",
                trigger_type, permit_renewal_id, recipient, send_err,
            )


async def renewal_reminder_cron():
    """Daily 7am ET. For each non-terminal, operator-actionable
    renewal whose current_expiration falls into one of the three
    reminder windows (T-30, T-14, T-7), fire the matching
    notification to filing_reps + the company admin.

    Date strategy: current_expiration is stored as an Optional[str]
    on permit_renewals (mixed format: ISO and M/D/YYYY both seen in
    production). We can't do a Mongo range query because string
    comparison breaks on mixed formats, so we scan all eligible
    renewals and partition in Python via dateparser. Volume is low
    (single tenant: <100 active renewals) so the scan is cheap.

    Idempotency: send_notification skips when a successful send for
    the same (renewal, trigger, recipient) lands in the last 23h.
    The 23h window leaves slack for cron drift (a 7am run today vs
    7:05am tomorrow still dedups)."""
    try:
        from dateutil import parser as dateparser
        today_utc = datetime.now(timezone.utc).date()

        # Single Mongo scan — eligible-status renewals. We don't filter
        # on current_expiration in Mongo because of the mixed-string
        # format problem documented above.
        cursor = db.permit_renewals.find({
            "status": {"$in": list(REMINDER_ELIGIBLE_STATUSES)},
            "is_deleted": {"$ne": True},
        })

        candidates = []
        async for renewal in cursor:
            exp_str = renewal.get("current_expiration")
            if not exp_str:
                continue
            try:
                exp_date = dateparser.parse(str(exp_str)).date()
            except Exception:
                continue
            days_until = (exp_date - today_utc).days
            candidates.append((renewal, days_until))

        # For each window, dispatch matching candidates.
        sent = 0
        for trigger_type, low, high, label_days in REMINDER_WINDOWS:
            for renewal, days_until in candidates:
                if low <= days_until < high:
                    await _send_reminder_for_renewal(
                        renewal,
                        trigger_type=trigger_type,
                        days_until=days_until,
                    )
                    sent += 1

        if sent:
            logger.info(
                "[renewal_reminder_cron] processed %d renewal/recipient "
                "pairs (idempotency may have suppressed some sends)",
                sent,
            )
    except Exception as e:
        logger.error(f"[renewal_reminder_cron] cycle error: {e!r}")


async def _send_renewal_notification_hook(
    renewal: dict,
    *,
    trigger_type: str,
    extra_context: Optional[dict] = None,
):
    """Watcher-hook adapter. Builds the context, resolves recipients,
    and fires send_notification per recipient. Used by the MR.8
    dob_approval_watcher when it appends a stuck_at_dob or
    renewal_confirmed_in_dob audit event."""
    from lib.notifications import (
        send_notification,
        collect_notification_recipients,
    )
    from lib.email_templates import render_for_trigger

    company_id = renewal.get("company_id")
    if not company_id:
        return
    recipients = await collect_notification_recipients(db, str(company_id))
    if not recipients:
        return

    permit_renewal_id = str(renewal.get("_id"))
    days_until = 0  # unused for stuck/completed; required by template ctx
    base_context = await _renewal_reminder_context(renewal, days_until)
    base_context.update(extra_context or {})

    for recipient in recipients:
        ctx = dict(base_context)
        ctx["recipient_name"] = recipient.split("@", 1)[0]
        try:
            company_doc = await db.companies.find_one(
                {"_id": to_query_id(company_id)}
            )
            if company_doc:
                for rep in (company_doc.get("filing_reps") or []):
                    if (rep.get("email") or "").lower() == recipient:
                        ctx["recipient_name"] = rep.get("name") or ctx["recipient_name"]
                        break
        except Exception:
            pass

        try:
            subject, html, text = render_for_trigger(trigger_type, ctx)
        except Exception as render_err:
            logger.error(
                "[notification_hook] template render failed "
                "trigger=%s renewal=%s: %r",
                trigger_type, permit_renewal_id, render_err,
            )
            continue

        try:
            await send_notification(
                db,
                permit_renewal_id=permit_renewal_id,
                trigger_type=trigger_type,
                recipient=recipient,
                subject=subject,
                html=html,
                text=text,
                metadata=extra_context or {},
            )
        except Exception as send_err:
            logger.error(
                "[notification_hook] send_notification raised "
                "trigger=%s renewal=%s recipient=%s: %r",
                trigger_type, permit_renewal_id, recipient, send_err,
            )


# Card audit routers — gate_router serves public HTML at /checkin/...
# and /enrollment/... (no auth, workers are anonymous), admin_router
# serves JSON at /api/admin/... (admin-gated). The admin gate is a
# small dep wrapper that resolves the admin user AND stashes it on
# request.state so card_audit endpoints can read it without taking
# it as a parameter (mount-time include_router deps don't expose
# their resolved values to downstream endpoint signatures).
async def _card_audit_admin_gate(request: Request, admin_user = Depends(get_admin_user)):
    request.state.current_user = admin_user
    return admin_user

try:
    import card_audit as _card_audit_module  # noqa: E402
    app.include_router(_card_audit_module.gate_router)
    app.include_router(
        _card_audit_module.admin_router,
        dependencies=[Depends(_card_audit_admin_gate)],
    )
except Exception as _card_router_err:
    logger.error(f"card_audit router mount failed: {_card_router_err!r}")


# Include the router in the main app
app.include_router(api_router)


@app.get("/a/{annotation_id}")
async def annotation_short_link(annotation_id: str, request: Request):
    """Short link redirect for annotation deep links."""
    from fastapi.responses import HTMLResponse

    web_url = f"https://levelog.com/plans?annotation={annotation_id}"
    deep_link = f"levelog://annotation/{annotation_id}"

    # Return HTML that tries the deep link first, falls back to web
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Redirecting…</title>
<script>
  var deep = "{deep_link}";
  var web  = "{web_url}";
  var ua = navigator.userAgent || "";
  if (/iPhone|iPad|Android/i.test(ua)) {{
    window.location = deep;
    setTimeout(function() {{ window.location = web; }}, 1500);
  }} else {{
    window.location = web;
  }}
</script>
</head>
<body style="font-family:sans-serif;text-align:center;padding:60px;">
<p>Redirecting&hellip;</p>
<p><a href="{web_url}">Click here if not redirected</a></p>
</body></html>"""
    return HTMLResponse(content=html)


@app.on_event("shutdown")
async def shutdown_db_client():
    if scheduler.running:
        scheduler.shutdown()
    client.close()

# Startup event to create indexes and seed data
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Levelog API with Sync Support...")

    # Initialize R2 storage client
    global _r2_client
    _r2_client = _get_r2_client()
    if _r2_client:
        logger.info(f"R2 storage configured: bucket={R2_BUCKET_NAME}")
        # Ensure CORS lets the web app fetch presigned URLs directly from R2.
        try:
            await asyncio.to_thread(
                _r2_client.put_bucket_cors,
                Bucket=R2_BUCKET_NAME,
                CORSConfiguration={
                    "CORSRules": [{
                        "AllowedOrigins": [
                            "https://www.levelog.com",
                            "https://levelog.com",
                            "https://app.levelog.com",
                            "http://localhost:19006",
                            "http://localhost:8081",
                        ],
                        "AllowedMethods": ["GET", "HEAD"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["Content-Length", "Content-Type", "ETag"],
                        "MaxAgeSeconds": 3600,
                    }]
                },
            )
            logger.info("R2 bucket CORS policy applied")
        except Exception as _cors_err:
            logger.error(f"Failed to apply R2 CORS policy: {_cors_err}")
    else:
        logger.warning("R2 storage not configured — file delivery will use Dropbox only")

    global SCREENSHOT_ENABLED
    SCREENSHOT_ENABLED = False
    try:
        from pdf2image import convert_from_bytes
        _test_pdf = (
            b"%PDF-1.4 1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj "
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
            b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
        )
        convert_from_bytes(_test_pdf, first_page=1, last_page=1)
        SCREENSHOT_ENABLED = True
        logger.info("pdf2image/poppler: OK — annotation screenshots enabled")
    except Exception as _e:
        logger.error(f"pdf2image/poppler not available: {_e}. Annotation screenshots disabled.")

    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.workers.create_index("phone", unique=True, sparse=True)
    await db.nfc_tags.create_index("tag_id", unique=True)
    await db.subcontractors.create_index("email", unique=True)
    await db.companies.create_index("name", unique=True)
    await db.checklists.create_index("company_id")
    await db.checklist_assignments.create_index("checklist_id")
    await db.checklist_assignments.create_index("project_id")
    await db.checklist_assignments.create_index("assigned_user_ids")
    await db.checklist_completions.create_index([("assignment_id", 1), ("user_id", 1)])

    # Safety staff indexes
    await db.safety_staff_registrations.create_index([("project_id", 1), ("role", 1)])
    await db.safety_staff_registrations.create_index("company_id")

    # Audit log indexes
    await db.audit_logs.create_index([("resource_type", 1), ("resource_id", 1)])
    await db.audit_logs.create_index("timestamp")

    # Document annotation indexes
    await db.document_annotations.create_index("project_id")
    await db.document_annotations.create_index("created_by")
    await db.document_annotations.create_index("recipients")
    await db.document_annotations.create_index([("project_id", 1), ("document_path", 1)])

    # Project files (R2 cache) indexes
    await db.project_files.create_index("project_id")
    # Uniqueness on (project_id, dropbox_path) must only apply to real Dropbox paths.
    # Direct uploads store dropbox_path="" and would otherwise collide on a sparse index,
    # because sparse skips missing fields but not empty strings.
    try:
        _pf_indexes = await db.project_files.index_information()
        _old_name = "project_id_1_dropbox_path_1"
        if _old_name in _pf_indexes and not _pf_indexes[_old_name].get("partialFilterExpression"):
            await db.project_files.drop_index(_old_name)
    except Exception as _e:
        logger.warning(f"project_files unique index migration skipped: {_e}")
    await db.project_files.create_index(
        [("project_id", 1), ("dropbox_path", 1)],
        unique=True,
        partialFilterExpression={"dropbox_path": {"$gt": ""}},
    )
    await db.project_files.create_index("dropbox_content_hash")

    # Create compound indexes for sync queries
    await db.workers.create_index([("company_id", 1), ("updated_at", -1)])
    await db.projects.create_index([("company_id", 1), ("updated_at", -1)])
    await db.checkins.create_index([("company_id", 1), ("updated_at", -1)])
    await db.daily_logs.create_index([("company_id", 1), ("updated_at", -1)])
    await db.daily_logs.create_index([("project_id", 1), ("date", 1)], unique=True, sparse=True)
    await db.nfc_tags.create_index([("company_id", 1), ("updated_at", -1)])
    await db.logbooks.create_index([("project_id", 1), ("log_type", 1), ("date", -1)])
    await db.logbooks.create_index([("company_id", 1), ("date", -1)])

	# Compound index for check-in duplicate prevention (critical at scale)
    await db.checkins.create_index(
        [("worker_id", 1), ("project_id", 1), ("check_in_time", 1), ("status", 1)],
        name="checkin_dedup_compound"
    )
    # Partial index for active (non-deleted) records — optimizes the is_deleted != True filter
    await db.workers.create_index(
        [("company_id", 1), ("status", 1)],
        partialFilterExpression={"is_deleted": {"$eq": False}},
        name="workers_active_by_company"
    )
    await db.checkins.create_index(
        [("project_id", 1), ("status", 1)],
        partialFilterExpression={"is_deleted": {"$eq": False}},
        name="checkins_active_by_project"
    )
	
    # COI expiration tracking (Phase 3 prep)
    await db.certificates_of_insurance.create_index(
        [("company_id", 1), ("expiration_date", 1)],
        name="coi_expiry_by_company"
    )
    # Worker certification expiration scanning
    await db.workers.create_index(
        [("certifications.expiration_date", 1)],
        partialFilterExpression={"is_deleted": {"$eq": False}},
        name="worker_cert_expiry",
    )

    # WhatsApp indexes
    await db.whatsapp_groups.create_index([("company_id", 1), ("wa_group_id", 1)])
    await db.whatsapp_groups.create_index("project_id")
    await db.whatsapp_messages.create_index([("project_id", 1), ("timestamp", -1)])
    await db.whatsapp_messages.create_index([("group_id", 1), ("created_at", -1)])
    await db.whatsapp_contacts.create_index([("company_id", 1), ("phone", 1)], unique=True)
    await db.whatsapp_link_codes.create_index("expires_at", expireAfterSeconds=0)

    # Create owner account if doesn't exist
    owner = await db.users.find_one({"email": "rfs2671@gmail.com"})
    owner_default_pw = os.environ.get("OWNER_DEFAULT_PASSWORD")
    if not owner and owner_default_pw:
        now = datetime.now(timezone.utc)
        await db.users.insert_one({
            "email": "rfs2671@gmail.com",
            "password": hash_password(owner_default_pw),
            "name": "Roy Fishman",
            "role": "owner",
            "created_at": now,
            "updated_at": now,
            "assigned_projects": [],
            "is_deleted": False
        })
        logger.info("Created default owner user")
    elif owner and owner.get("role") == "admin":
        # Upgrade existing admin to owner
        await db.users.update_one(
            {"email": "rfs2671@gmail.com"},
            {"$set": {"role": "owner", "updated_at": datetime.now(timezone.utc)}}
        )
        logger.info("Upgraded existing admin to owner role")

    # ── TEST DATA SEED (creates test accounts + project if missing) ──
    test_user = await db.users.find_one({"email": "test@test.com"})
    if not test_user:
        now = datetime.now(timezone.utc)
        # 1. Create test company
        test_company = await db.companies.find_one({"name": "Test Construction Co"})
        if not test_company:
            result = await db.companies.insert_one({
                "name": "Test Construction Co",
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
            })
            test_company_id = str(result.inserted_id)
            logger.info(f"Created test company: {test_company_id}")
        else:
            test_company_id = str(test_company["_id"])

        # 2. Create test@test.com as owner
        result = await db.users.insert_one({
            "email": "test@test.com",
            "password": hash_password("test"),
            "name": "Test Owner",
            "full_name": "Test Owner",
            "role": "owner",
            "company_id": test_company_id,
            "phone": "+15163018154",
            "created_at": now,
            "updated_at": now,
            "assigned_projects": [],
            "is_deleted": False,
        })
        test_owner_id = str(result.inserted_id)
        logger.info(f"Created test owner: test@test.com")

        # 3. Create admin account (rfs2671@gmail.com) for this company
        existing_admin = await db.users.find_one({"email": "rfs2671@gmail.com", "company_id": test_company_id})
        if not existing_admin:
            result = await db.users.insert_one({
                "email": "rfs2671@gmail.com",
                "password": hash_password("test"),
                "name": "Roy Fishman",
                "full_name": "Roy Fishman",
                "role": "admin",
                "company_id": test_company_id,
                "phone": "+15163018154",
                "created_at": now,
                "updated_at": now,
                "assigned_projects": [],
                "is_deleted": False,
            })
            admin_id = str(result.inserted_id)
            logger.info(f"Created test admin: rfs2671@gmail.com")

        # 4. Create test CP (Construction Professional)
        result = await db.users.insert_one({
            "email": "cp@test.com",
            "password": hash_password("test"),
            "name": "Test CP",
            "full_name": "Test Construction Professional",
            "role": "cp",
            "company_id": test_company_id,
            "phone": "+15551234567",
            "created_at": now,
            "updated_at": now,
            "assigned_projects": [],
            "is_deleted": False,
        })
        cp_id = str(result.inserted_id)
        logger.info(f"Created test CP: cp@test.com")

        # 5. Create test worker
        test_worker = await db.workers.insert_one({
            "name": "Test Worker",
            "full_name": "Test Worker",
            "company_id": test_company_id,
            "phone": "+15559876543",
            "email": "worker@test.com",
            "trade": "General Laborer",
            "sst_card_number": "SST-TEST-001",
            "osha_card_number": "OSHA-TEST-001",
            "certifications": [
                {
                    "type": "SST",
                    "number": "SST-TEST-001",
                    "expiration_date": (now + timedelta(days=365)).isoformat(),
                },
                {
                    "type": "OSHA-30",
                    "number": "OSHA-TEST-001",
                    "expiration_date": (now + timedelta(days=180)).isoformat(),
                },
            ],
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        })
        worker_id = str(test_worker.inserted_id)
        logger.info(f"Created test worker: {worker_id}")

        # 6. Create test subcontractor
        await db.subcontractors.insert_one({
            "name": "Test Electrical Sub",
            "company_name": "Spark Electric LLC",
            "company_id": test_company_id,
            "email": "sub@test.com",
            "phone": "+15557654321",
            "trade": "Electrician",
            "license_number": "LIC-ELEC-TEST",
            "insurance_info": "Policy #INS-TEST-001, Exp 2027-01-01",
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        })
        logger.info("Created test subcontractor: Spark Electric LLC")

        # 7. Create test project with real NYC BIN (Empire State Building)
        test_project = await db.projects.find_one({"name": "Test Project - ESB", "company_id": test_company_id})
        if not test_project:
            result = await db.projects.insert_one({
                "name": "Test Project - ESB",
                "company_id": test_company_id,
                "address": "350 5th Avenue, New York, NY 10118",
                "nyc_bin": "1015862",
                # bbl renamed from nyc_bbl 2026-04-27 (step 9.1).
                "bbl": "1008370032",
                "bbl_source": "manual_entry",
                "bbl_last_synced": now,
                "track_dob_status": True,
                "gc_legal_name": "Test Construction Co",
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
            })
            test_project_id = str(result.inserted_id)
            # Assign project to all test users
            await db.users.update_many(
                {"company_id": test_company_id},
                {"$addToSet": {"assigned_projects": test_project_id}},
            )
            logger.info(f"Created test project (ESB): {test_project_id}")

        logger.info("✅ Test data seeding complete")

     # Start report email scheduler
    scheduler.add_job(
        check_and_send_reports,
        CronTrigger(minute='*'),
        id='report_email_scheduler',
        replace_existing=True,
    )
    
    # DOB compliance scanner — runs every 30 minutes
    scheduler.add_job(
        nightly_dob_scan,
        'interval',
        minutes=30,
        id='dob_nightly_scan',
        replace_existing=True,
    )

    # MR.5: stale-claim watchdog — clears IN_PROGRESS claims older
    # than 30 min so the renewal re-enters the queue. Every 5 min.
    scheduler.add_job(
        _stale_claim_watchdog,
        IntervalTrigger(minutes=5),
        id='stale_claim_watchdog',
        replace_existing=True,
    )
    # MR.5: heartbeat watchdog — flags workers as degraded after
    # 30 min absence. Email escalation in MR.9.
    scheduler.add_job(
        _heartbeat_watchdog,
        IntervalTrigger(minutes=5),
        id='heartbeat_watchdog',
        replace_existing=True,
    )

    # MR.8: DOB approval watcher — every 30 min, checks dob_logs for
    # renewed permit expirations and transitions matching renewals
    # from AWAITING_DOB_APPROVAL → COMPLETED. Staggered 10 min off the
    # nightly_dob_scan tick so dob_logs is freshly refreshed before
    # the watcher reads it (worst case is one missed read window;
    # the next 30-min cycle catches it).
    scheduler.add_job(
        dob_approval_watcher,
        IntervalTrigger(minutes=30),
        id='dob_approval_watcher',
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    # MR.9: daily 7am ET reminder cron — sends T-30 / T-14 / T-7
    # notifications to filing_reps + the company admin for each
    # operator-actionable renewal whose current_expiration falls in
    # one of the three windows. Gated by NOTIFICATIONS_ENABLED
    # (default off) so a misconfigured Resend key doesn't blast emails
    # on first deploy. CronTrigger handles DST automatically — when
    # ET shifts between EST and EDT the absolute UTC time of "7am ET"
    # changes, but the trigger fires correctly because the timezone
    # is named, not numeric.
    scheduler.add_job(
        renewal_reminder_cron,
        CronTrigger(hour=7, minute=0, timezone="America/New_York"),
        id='renewal_reminder_cron',
        replace_existing=True,
    )

    # 311 fast poll — every 30 minutes, staggered 15 min off the DOB scan so
    # the two don't spike the outbound HTTP client at the same time.
    scheduler.add_job(
        _poll_311_fast_complaints,
        IntervalTrigger(minutes=30),
        id='dob_311_fast_poll',
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    # Nightly compliance check — missing logbooks, missing SSP, expiring licenses
    scheduler.add_job(
        nightly_compliance_check,
        CronTrigger(hour=22, minute=0),  # 10 PM EST
        id='nightly_compliance_check',
        replace_existing=True,
    )

    # WhatsApp daily summary — runs every 30 minutes, sends when each group's
    # configured time/day matches the current EST window. Dedup is MongoDB-backed
    # via whatsapp_send_log so it survives restarts.
    scheduler.add_job(
        _send_whatsapp_daily_summaries,
        IntervalTrigger(minutes=30),
        id='whatsapp_daily_summary',
        replace_existing=True,
    )
    # WhatsApp checklist extraction — same cadence, different job_type in dedup log.
    scheduler.add_job(
        _run_whatsapp_checklist_extractions,
        IntervalTrigger(minutes=30),
        id='whatsapp_checklist_extraction',
        replace_existing=True,
    )

    # Card audit nightly jobs. See backend/card_audit.py.
    try:
        import card_audit as _card_audit  # noqa: E402
        scheduler.add_job(
            _card_audit.check_card_expirations,
            CronTrigger(hour=2, minute=15, timezone="America/New_York"),
            id='card_audit_expiration_check',
            replace_existing=True,
        )
        scheduler.add_job(
            _card_audit.run_fraud_detection,
            CronTrigger(hour=2, minute=30, timezone="America/New_York"),
            id='card_audit_fraud_detection',
            replace_existing=True,
        )
    except Exception as _card_job_err:
        logger.error(f"card_audit scheduler wire failed: {_card_job_err!r}")

    # ── Eligibility rewrite: shadow-mode cron + startup mode validation ──
    # Validate ELIGIBILITY_REWRITE_MODE early. A typo (e.g. 'shadwo')
    # crashes the process now — the alternative (silent default to
    # 'off') is the worst case: you think shadow is running, it isn't,
    # you cut over after 48h of zero data.
    try:
        from lib.eligibility_dispatcher import (
            assert_valid_mode_at_startup as _validate_eligibility_mode,
            get_mode as _get_eligibility_mode,
        )
        _eligibility_mode = _validate_eligibility_mode()
    except Exception as _e:
        logger.error(f"Eligibility mode validation FAILED at startup: {_e!r}")
        raise

    if _eligibility_mode == "shadow":
        try:
            scheduler.add_job(
                _eligibility_shadow_sweep,
                IntervalTrigger(minutes=30),
                id='eligibility_shadow_sweep',
                replace_existing=True,
                max_instances=1,  # cron lock — skip if previous run still going
                coalesce=True,
            )
            logger.info("🪞 Eligibility shadow sweep scheduled (every 30 min)")
        except Exception as _e:
            logger.error(f"eligibility_shadow_sweep scheduler wire failed: {_e!r}")

    # ── Resend domain health check ──
    # Probe before the digest cron is registered so a verification
    # failure surfaces at deploy time, not at the next 7am ET tick.
    await _verify_resend_domain_at_startup()

    # ── Renewal digest daily cron ──
    # 7am America/New_York every day. One email per company per day,
    # only on days that actually crossed a threshold (per spec §4).
    # Suppression + idempotency live in renewal_alert_sent collection.
    try:
        scheduler.add_job(
            renewal_digest_daily_cron,
            CronTrigger(hour=7, minute=0, timezone="America/New_York"),
            id='renewal_digest_daily',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("📧 Renewal digest scheduled (daily 7am ET)")
    except Exception as _e:
        logger.error(f"renewal_digest_daily scheduler wire failed: {_e!r}")

    # Mongo TTL on eligibility_shadow records — 30 days. Idempotent.
    await _ensure_index_resilient(
        db.eligibility_shadow,
        keys=[("ran_at", 1)],
        name="eligibility_shadow_ttl",
        expireAfterSeconds=30 * 24 * 60 * 60,
    )

    # COI OCR drafts: 24h TTL. If admin uploads then walks away without
    # confirming, the draft drops automatically — no orphan accumulation.
    # The PDF + preview in R2 stay (7-year retention) but the in-flight
    # draft state is per-session.
    await _ensure_index_resilient(
        db.coi_ocr_drafts,
        keys=[("created_at", 1)],
        name="coi_ocr_drafts_ttl",
        expireAfterSeconds=24 * 60 * 60,
    )
    # Idempotency lookup index — same (company, sha, type) returns
    # the cached draft instead of creating a duplicate.
    await _ensure_index_resilient(
        db.coi_ocr_drafts,
        keys=[("company_id", 1), ("sha256", 1), ("insurance_type", 1)],
        name="coi_ocr_drafts_idem",
    )

    # Renewal-digest idempotency: one row per (company, kind, expiry,
    # threshold, sent_date). Prevents the cron firing twice on the same
    # day from sending two emails. 90-day TTL — long enough for late
    # debugging, short enough to not accumulate forever.
    await _ensure_index_resilient(
        db.renewal_alert_sent,
        keys=[
            ("company_id", 1),
            ("kind", 1),
            ("expiry_date", 1),
            ("threshold_days", 1),
            ("permit_id", 1),
            ("sent_date", 1),
        ],
        name="renewal_alert_sent_idem",
    )
    await _ensure_index_resilient(
        db.renewal_alert_sent,
        keys=[("sent_at", 1)],
        name="renewal_alert_sent_ttl",
        expireAfterSeconds=90 * 24 * 60 * 60,
    )

    scheduler.start()
    logger.info("📧 Report email scheduler started")
    logger.info("🏗️ DOB compliance scanner scheduled (every 30 minutes)")
    logger.info("🔍 Nightly compliance check scheduled (10 PM)")
    logger.info("💬 WhatsApp daily summary scheduled (every 30 min, per-group config)")
    logger.info("✅ WhatsApp checklist extraction scheduled (every 30 min, per-group config)")

    # WhatsApp startup migrations — bot_config backfill, indexes, TTL
    await run_whatsapp_startup_migrations()
    
    # DOB collection indexes
    await db.dob_logs.create_index([("project_id", 1), ("detected_at", -1)])
    await db.dob_logs.create_index([("company_id", 1)])
    await db.dob_logs.create_index("raw_dob_id", unique=True, sparse=True)

    # Card audit module init — injects db + R2 + VLM adapter. Must run
    # AFTER _r2_client is initialized (which happens at module import
    # time via the _get_r2_client() call wired into startup below, if
    # present) but BEFORE the first request. Doing it here at end of
    # startup means both are guaranteed ready.
    try:
        import card_audit as _card_audit  # noqa: E402
        _card_audit.init(
            db_ref=db,
            r2_client=_r2_client,
            qwen_vlm=_card_audit_vlm_adapter,
        )
        await _card_audit.ensure_indexes()
        logger.info(
            f"🪪 card_audit wired. bucket={_card_audit.CARD_AUDIT_BUCKET_NAME!r} "
            f"key_prefix={_card_audit.CARD_AUDIT_KEY_PREFIX!r}"
        )
        if not _card_audit.CARD_AUDIT_BUCKET_NAME:
            logger.warning(
                "⚠️  No R2 bucket configured for card audit — card photos "
                "will not persist. Set R2_BUCKET_NAME."
            )
    except Exception as _init_err:
        logger.error(f"card_audit init failed: {_init_err!r}")

    logger.info("Levelog API started successfully with Sync v2.0")
