from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
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
import re
import hashlib
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

# ==================== ID HELPER ====================

def to_query_id(id_str: str):
    if not id_str:
        return id_str
    try:
        return ObjectId(id_str)
    except Exception:
        return id_str

# ==================== COMPANY MODEL ====================

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
 
async def fetch_nyc_bin_from_address(address: str) -> dict:
    """
    Query NYC GeoSearch to resolve an address into a BIN + BBL.
    Returns {"nyc_bin": str|None, "nyc_bbl": str|None, "track_dob_status": bool}
    Tries multiple endpoints as fallbacks.
    """
    result = {"nyc_bin": None, "nyc_bbl": None, "track_dob_status": False}
    if not address or len(address.strip()) < 5:
        return result

    # Try multiple GeoSearch endpoints (primary + fallback)
    endpoints = [
        "https://geosearch.planninglabs.nyc/v2/search",
        "https://geosearch.planning.nyc.gov/v2/search",
    ]

    for endpoint in endpoints:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.get(
                    endpoint,
                    params={"text": address.strip(), "size": "1"},
                )
                if resp.status_code != 200:
                    logger.warning(f"GeoSearch {endpoint} returned {resp.status_code} for '{address}'")
                    continue

                data = resp.json()
                features = data.get("features", [])
                if not features:
                    logger.info(f"GeoSearch: no features for '{address}' via {endpoint}")
                    continue

                props = features[0].get("properties", {})
                pad_bin = props.get("pad_bin", "") or props.get("addendum", {}).get("pad", {}).get("bin", "")
                pad_bbl = props.get("pad_bbl", "") or props.get("addendum", {}).get("pad", {}).get("bbl", "")

                # Validate BIN is 7 digits
                if pad_bin and len(str(pad_bin)) == 7 and str(pad_bin).isdigit():
                    result["nyc_bin"] = str(pad_bin)
                    result["track_dob_status"] = True

                if pad_bbl:
                    result["nyc_bbl"] = str(pad_bbl)

                logger.info(f"GeoSearch resolved '{address}' -> BIN={result['nyc_bin']}, BBL={result['nyc_bbl']} via {endpoint}")
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
    nyc_bbl: Optional[str] = None
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

    # Check 1: OSHA baseline
    has_osha = bool(cert_types.get("OSHA_10") or cert_types.get("OSHA_30"))
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
            blocks.append({
                "type": "EXPIRED_SST",
                "detail": f"SST card expired {expired_sst.strftime('%Y-%m-%d')}. Cannot enter site per NYC LL196.",
                "remediation": "Worker must complete SST renewal training and present updated card."
            })
        elif not sst_certs:
            blocks.append({
                "type": "MISSING_SST",
                "detail": "No NYC SST card on file. Required per LL196.",
                "remediation": "Worker must complete SST training (10-hr or 62-hr) and present card."
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
    nyc_bbl: Optional[str] = None
    track_dob_status: Optional[bool] = None
    gc_legal_name: Optional[str] = None
 
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
    # Password complexity — minimum 8 chars, at least one letter and one digit
    pwd = user_data.password
    if len(pwd) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if not re.search(r'[A-Za-z]', pwd) or not re.search(r'[0-9]', pwd):
        raise HTTPException(status_code=422, detail="Password must contain at least one letter and one digit")

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

    # Enforce a minimum length
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="New password must be at least 6 characters")

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
    # Password complexity
    pwd = user_data.password
    if len(pwd) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if not re.search(r'[A-Za-z]', pwd) or not re.search(r'[0-9]', pwd):
        raise HTTPException(status_code=422, detail="Password must contain at least one letter and one digit")

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
            async with httpx.AsyncClient(timeout=20.0) as client:
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
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
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
        async with httpx.AsyncClient(timeout=20.0) as client:
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
            async with httpx.AsyncClient(timeout=20.0) as client:
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
        async with httpx.AsyncClient(timeout=20.0) as client:
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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
        gc_info = await scrape_gc_license_info(
            company.get("gc_business_name") or company.get("name", "")
        )
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
    
    # ── DOB: Auto-resolve NYC BIN from address ──
    project_dict["nyc_bin"] = None
    project_dict["nyc_bbl"] = None
    project_dict["track_dob_status"] = False
 
    address_for_bin = project_dict.get("address") or project_dict.get("location") or ""
    if address_for_bin:
        bin_result = await fetch_nyc_bin_from_address(address_for_bin)
        project_dict["nyc_bin"] = bin_result["nyc_bin"]
        project_dict["nyc_bbl"] = bin_result["nyc_bbl"]
        project_dict["track_dob_status"] = bin_result["track_dob_status"]
        if bin_result["nyc_bin"]:
            logger.info(f"Auto-resolved BIN {bin_result['nyc_bin']} for project '{project_dict.get('name')}'")
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
        
        return {
            "project_id": project_id,
            "project_name": project.get("name", "Unknown Project"),
            "location": tag.get("location_description", "Check-In Point"),
            "tag_id": tag_id,
            "company_name": project.get("company_name")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@api_router.post("/checkin/upload-osha")
async def upload_osha_card(file_data: dict, current_user = Depends(get_current_user)):
    """OCR an OSHA/SST card photo using Gemini AI."""
    import httpx
    import json as json_mod

    image_b64 = file_data.get("image")
    content_type = file_data.get("content_type", "image/jpeg")

    if not image_b64:
        raise HTTPException(status_code=400, detail="No image provided")

    # Strip data URL prefix if present
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": content_type,
                                    "data": image_b64,
                                }
                            },
                            {
								"text": "Extract the following from this SST/OSHA safety training card image. Return ONLY valid JSON, no markdown:\n{\"name\": \"full name on card\", \"sst_number\": \"the ID number or card number shown on the card\", \"issued\": \"issued date if visible\", \"expiration\": \"expiration date if visible\", \"box_2d\": [ymin, xmin, ymax, xmax]}\nIf a field is not visible, set it to null. 'box_2d' should be the normalized coordinates (0-1000) tightly framing the card. Return the JSON object only."
                            },
                        ]
                    }]
                },
            )

        if response.status_code != 200:
            logger.error(f"Gemini API error: {response.text}")
            raise HTTPException(status_code=502, detail="AI processing failed")

        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]

        # Parse JSON from response
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        extracted = json_mod.loads(text)
        return extracted

    except json_mod.JSONDecodeError:
        return {"name": None, "sst_number": None, "issued": None, "expiration": None, "raw_text": text}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OSHA OCR error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")

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
    worker_certs = worker.get("certifications", [])
    if osha_number and not any(c.get("type", "").startswith("OSHA") for c in worker_certs):
        new_cert = {
            "type": "OSHA_30" if "30" in str(osha_data.get("course", "") if osha_data else "") else "OSHA_10",
            "card_number": osha_number,
            "issue_date": None,
            "expiration_date": None,
            "verified": False,
            "ocr_confidence": osha_data.get("confidence") if osha_data else None,
        }
        if osha_data and osha_data.get("expiration"):
            try:
                new_cert["expiration_date"] = datetime.strptime(osha_data["expiration"], "%m/%d/%Y").replace(tzinfo=timezone.utc)
                new_cert["type"] = "SST_LIMITED"
            except (ValueError, TypeError):
                pass
        worker_certs.append(new_cert)
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
    async with httpx.AsyncClient() as client_http:
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
        return HTMLResponse(f"<html><body><h2>Failed to connect</h2><p>{token_response.text}</p><script>window.close();</script></body></html>")
    
    token_data = token_response.json()
    
    # Get account info
    async with httpx.AsyncClient() as client_http:
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
    
    async with httpx.AsyncClient() as client_http:
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
        raise HTTPException(status_code=400, detail="Failed to exchange code for token")
    
    token_data = token_response.json()
    company_id = get_user_company_id(current_user)
    now = datetime.now(timezone.utc)
    
    # Get account info
    async with httpx.AsyncClient() as client_http:
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
            async with httpx.AsyncClient() as client_http:
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

    # Check if token is still valid (with 30-min buffer)
    expires_at = connection.get("access_token_expires_at")
    if expires_at and isinstance(expires_at, datetime):
        if expires_at > datetime.now(timezone.utc) + timedelta(minutes=30):
            return connection["access_token"]

    # Token expired or no expiry stored — refresh
    refresh_token = connection.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token. Please reconnect Dropbox.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
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

    async with httpx.AsyncClient() as client_http:
        response = await getattr(client_http, method)(url, headers=headers, **kwargs)

    # Safety net: if 401 despite proactive refresh, force-refresh once more
    if response.status_code == 401:
        token = await get_valid_dropbox_token(company_id)
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient() as client_http:
            response = await getattr(client_http, method)(url, headers=headers, **kwargs)

    return response

@api_router.get("/dropbox/folders")
async def get_dropbox_folders(path: str = "", current_user = Depends(get_current_user)):
    """Get Dropbox folders for selection"""
    company_id = get_user_company_id(current_user)
    
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": path or "", "recursive": False, "include_mounted_folders": True}
    )
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to list folders")
    
    data = response.json()
    folders = [
        {
            "name": entry["name"],
            "path": entry["path_lower"],
            "id": entry.get("id", ""),
        }
        for entry in data.get("entries", [])
        if entry[".tag"] == "folder"
    ]
    
    return folders

@api_router.post("/projects/{project_id}/link-dropbox")
async def link_dropbox_to_project(project_id: str, data: dict, current_user = Depends(get_current_user)):
    """Link a Dropbox folder to a project"""
    folder_path = data.get("folder_path")
    if not folder_path:
        raise HTTPException(status_code=400, detail="folder_path required")
    
    now = datetime.now(timezone.utc)
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": {
            "dropbox_folder_path": folder_path,
            "dropbox_linked_at": now,
            "dropbox_linked_by": current_user.get("id"),
            "updated_at": now,
        }}
    )
    
    return {"message": "Dropbox folder linked", "folder_path": folder_path}

@api_router.get("/projects/{project_id}/dropbox-files")
async def get_project_dropbox_files(project_id: str, current_user = Depends(get_current_user)):
    """Get files from project's linked Dropbox folder (R2-backed with Dropbox fallback)"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    company_id = company_id or project.get("company_id")
    folder_path = project.get("dropbox_folder_path")

    # Check project_files collection first (R2 cache + direct uploads)
    cached_files = await db.project_files.find({
        "project_id": project_id,
        "company_id": company_id,
        "is_deleted": {"$ne": True},
    }).to_list(5000)

    if cached_files:
        files = []
        for rec in cached_files:
            files.append({
                "name": rec.get("name", ""),
                "path": rec.get("dropbox_path", ""),
                "id": str(rec.get("_id", "")),
                "type": "file",
                "size": rec.get("size", 0),
                "modified": rec.get("modified", ""),
                "r2_url": rec.get("r2_url", ""),
                "cache_version": rec.get("cache_version", 0),
                "source": rec.get("source", "dropbox_sync"),
            })
        return files

    # No cached records — fall back to live Dropbox listing (only if folder linked)
    if not folder_path:
        return []

    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": folder_path, "recursive": False}
    )

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to list files")

    data = response.json()
    files = []
    for entry in data.get("entries", []):
        file_info = {
            "name": entry["name"],
            "path": entry["path_lower"],
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
        response = await dropbox_api_call(
            company_id, "post",
            "https://api.dropboxapi.com/2/files/list_folder",
            json={"path": folder_path, "recursive": True}
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

    # Quick count from Dropbox for immediate response
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": folder_path, "recursive": True}
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

@api_router.post("/projects/{project_id}/upload-file")
async def upload_project_file(project_id: str, file: UploadFile = File(...), current_user = Depends(get_current_user)):
    """Upload a file directly to R2 storage for a project (PDF only, max 100 MB)."""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    company_id = company_id or project.get("company_id")

    # Validate file type
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Read and validate size (100 MB max)
    file_bytes = await file.read()
    max_size = 100 * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=400, detail="File too large. Maximum 100 MB.")

    if not _r2_client:
        raise HTTPException(status_code=503, detail="File storage (R2) is not configured")

    r2_key = f"{company_id}/{project_id}/{filename}"
    try:
        r2_url = await asyncio.to_thread(_upload_to_r2, file_bytes, r2_key, "application/pdf")
    except Exception as e:
        logger.error(f"Direct upload R2 error: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")

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
    result = await db.project_files.insert_one(file_record)
    file_record["_id"] = str(result.inserted_id)
    file_record.pop("created_at", None)
    file_record.pop("updated_at", None)

    # Sprint 3: spawn plan indexing for PDFs (no-op if QWEN_API_KEY unset)
    if filename.lower().endswith(".pdf") and QWEN_API_KEY:
        asyncio.create_task(_index_pdf_file(project_id, company_id, file_record))

    return {
        "id": file_record["_id"],
        "name": filename,
        "r2_url": r2_url,
        "size": len(file_bytes),
        "source": "direct_upload",
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

    async with httpx.AsyncClient(timeout=15.0) as c:
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
    """Get CP profile including saved signature"""
    user_id = current_user.get("id")
    user = await db.users.find_one({"_id": to_query_id(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "cp_name": user.get("cp_name") or user.get("name"),
        "cp_title": user.get("cp_title", "Competent Person"),
        "cp_signature": user.get("cp_signature"),
        "has_signature": bool(user.get("cp_signature")),
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
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
    """Get all workers checked in to a project on a given date (for auto-populating log books)"""
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

    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": day_start, "$lt": day_end},
        "is_deleted": {"$ne": True}
    }).to_list(500)

    # Enrich with worker data
    result = []
    seen_workers = set()
    for c in checkins:
        wid = c.get("worker_id")
        if wid in seen_workers:
            continue
        seen_workers.add(wid)
        worker = await db.workers.find_one({"_id": to_query_id(wid)}) if wid else None
        result.append({
            "worker_id": wid,
            "worker_name": c.get("worker_name") or (worker.get("name") if worker else "Unknown"),
            "company": c.get("worker_company") or (worker.get("company") if worker else ""),
            "trade": c.get("worker_trade") or (worker.get("trade") if worker else ""),
            "check_in_time": c.get("check_in_time").isoformat() if isinstance(c.get("check_in_time"), datetime) else str(c.get("check_in_time", "")),
            "osha_number": worker.get("osha_number") if worker else "",
            "certifications": worker.get("certifications", []) if worker else [],
            "worker_signature": worker.get("signature") if worker else None,
        })

    return result

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
    house_num = ""
    street_name = ""
    if clean_address:
        parts = clean_address.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            house_num = parts[0]
            street_name = parts[1].upper()
        else:
            street_name = clean_address.upper()
    # Sanitize for Socrata $where clause — strip characters that could manipulate the query
    street_name = re.sub(r"[^A-Z0-9 ]", "", street_name)
    house_num = re.sub(r"[^0-9]", "", house_num)
    
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
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/6bgk-3dad.json",
            "params": {"$where": f"upper(violation_address) like '%{house_num}%{street_name}%'", "$limit": "100", "$order": "issue_date DESC"},
            "record_type": "violation",
            "id_field": "ecb_violation_number",
        })
    
    # ── PERMITS: DOB NOW Build (rbx6-tga4) - NEWEST, check first ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
            "params": {"house_no": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "50"},
            "record_type": "permit",
            "id_field": "job_filing_number",
        })
    
    # ── PERMITS: BIS legacy (ipu4-2q9a) - older permits ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/ipu4-2q9a.json",
            "params": {"bin__": nyc_bin, "$limit": "50"},
            "record_type": "permit",
            "id_field": "job__",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/ipu4-2q9a.json",
            "params": {"house__": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "50"},
            "record_type": "permit",
            "id_field": "job__",
        })
    
    # ── DOB INSPECTIONS (p937-wjvj) ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/p937-wjvj.json",
            "params": {"bin": nyc_bin, "$limit": "50", "$order": "inspection_date DESC"},
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

    
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        for ep in endpoints:
            try:
                resp = await http_client.get(ep["url"], params=ep["params"])
                if resp.status_code == 200:
                    records = resp.json()
                    for rec in records:
                        # Build a dedup key from the record's unique ID
                        id_field = ep["id_field"]
                        raw_id = str(rec.get(id_field, ""))
                        if not raw_id:
                            continue
                        
                        # For permits, append work_type to dedup key (one job = multiple permits)
                        if ep["record_type"] == "permit":
                            work_suffix = rec.get("work_type") or rec.get("permit_type") or rec.get("permit_sequence__") or ""
                            dedup_key = f"permit:{raw_id}:{work_suffix}"
                        else:
                            dedup_key = f"{ep['record_type']}:{raw_id}"
                        
                        # Skip if we already have this record from another endpoint
                        if dedup_key in seen_ids:
                            continue
                        seen_ids.add(dedup_key)
                        
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
    
    logger.info(f"DOB query complete: {len(all_records)} unique records from {len(endpoints)} endpoints")
    return all_records
 
async def _send_critical_dob_alert(project: dict, dob_log: dict):
    """Send an immediate email for Critical severity DOB alerts."""
    if not RESEND_API_KEY:
        return
 
    company_id = project.get("company_id")
    if not company_id:
        return
 
    recipients = []
    admin_users = await db.users.find({
        "company_id": company_id,
        "role": {"$in": ["admin", "owner"]},
        "is_deleted": {"$ne": True},
    }).to_list(50)
 
    for u in admin_users:
        email = u.get("email")
        if email:
            recipients.append(email)
 
    if not recipients:
        return
 
    project_name = project.get("name", "Unknown Project")
    summary = dob_log.get("ai_summary", "No summary available")
    next_action = dob_log.get("next_action", "Review immediately")
    record_type = dob_log.get("record_type", "alert").upper().replace("_", " ")
 
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #dc2626; color: white; padding: 20px 24px; border-radius: 8px 8px 0 0;">
            <h1 style="margin: 0; font-size: 18px;">⚠️ CRITICAL DOB Alert</h1>
            <p style="margin: 4px 0 0; opacity: 0.9; font-size: 14px;">{project_name}</p>
        </div>
        <div style="background: #fff; border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
            <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
                <p style="margin: 0 0 4px; font-size: 11px; color: #991b1b; text-transform: uppercase; letter-spacing: 0.5px;">{record_type}</p>
                <p style="margin: 0; font-size: 15px; color: #1f2937; font-weight: 500;">{summary}</p>
            </div>
            <div style="background: #f9fafb; border-radius: 6px; padding: 16px;">
                <p style="margin: 0 0 4px; font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Required Action</p>
                <p style="margin: 0; font-size: 14px; color: #1f2937;">{next_action}</p>
            </div>
            <p style="margin: 16px 0 0; font-size: 12px; color: #9ca3af;">
                Detected at {dob_log.get('detected_at', datetime.now(timezone.utc)).strftime('%B %d, %Y %I:%M %p')} UTC
            </p>
        </div>
        <p style="text-align: center; font-size: 10px; color: #cbd5e1; margin-top: 16px; letter-spacing: 2px;">LEVELOG COMPLIANCE</p>
    </div>
    """
 
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": "Levelog Alerts <alerts@levelog.com>",
            "to": recipients,
            "subject": f"[CRITICAL] DOB Alert: {project_name} — {record_type}",
            "html": html,
        })
        logger.info(f"Critical DOB alert sent for {project_name} to {len(recipients)} recipients")
    except Exception as e:
        logger.error(f"Failed to send critical DOB alert: {e}")
 
 
def _extract_permit_fields(rec: dict) -> dict:
    """Extract structured permit fields from raw DOB record."""
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
    return {k: str(v).strip() if v else None for k, v in fields.items()}
 
 
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


def _extract_inspection_fields(rec: dict) -> dict:
    """Extract structured inspection fields from DOB Inspections dataset (p937-wjvj)."""
    fields = {}
    fields["inspection_date"] = rec.get("inspection_date") or rec.get("approved_date") or None
    fields["inspection_type"] = rec.get("inspection_type") or rec.get("inspection_category") or rec.get("job_progress") or None
    fields["inspection_result"] = rec.get("result") or rec.get("inspection_result") or None
    fields["inspection_result_description"] = rec.get("result_description") or rec.get("comments") or None
    fields["linked_job_number"] = rec.get("job_id") or rec.get("job_filing_number") or rec.get("job_number") or rec.get("job__") or None
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
        insp_type = rec.get("inspection_type") or rec.get("inspection_category") or rec.get("job_progress") or "General"
        job = rec.get("job_id") or rec.get("job_filing_number") or rec.get("job_number") or ""
        result = rec.get("result") or rec.get("inspection_result") or "Pending"
        job_str = f" for Job {job}" if job else ""
        return f"Inspection ({insp_type}){job_str} — Result: {result}"

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
 
 
def _build_dob_link(rec: dict, record_type: str) -> str:
    """Build a direct public link to DOB BIS or DOB NOW for this record.

    DOB NOW jobs (B-prefix, 2018+) do not exist in BIS — they must link to
    DOB NOW Public Portal. Legacy numeric job numbers link to BIS.
    All URLs below are publicly accessible without login.
    """
    bin_val  = str(rec.get("bin") or rec.get("bin__") or "").strip()
    job_num  = str(rec.get("job__") or rec.get("job_filing_number") or rec.get("job_number") or "").strip()
    isn_val  = str(rec.get("isn_dob_bis_viol") or rec.get("isn") or "").strip()
    ecb_num  = str(rec.get("ecb_violation_number") or "").strip()

    # Strip dashes for DOB NOW deep-links (B01234567 not B0123-4567)
    job_clean = job_num.replace("-", "").strip()
    is_dob_now_job = job_clean.upper().startswith("B") if job_clean else False

    if record_type == "swo":
        if bin_val:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/ComplaintsByAddressServlet"
                f"?requestid=2&allbin={bin_val}&fillerdata=A"
            )

    if record_type in ("violation", "swo"):
        if ecb_num:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/ECBQueryByNumberServlet"
                f"?requestid=2&ecbin={ecb_num}"
            )
        if isn_val:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/OverviewForComplaintServlet"
                f"?requestid=2&vlcompdetlkey={isn_val}"
            )
        if bin_val:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/OverviewByBinServlet"
                f"?requestid=2&allbin={bin_val}&allinquirytype=BXS3OCV4"
            )
        return ""

    if record_type == "complaint":
        comp_num = str(rec.get("complaint_number") or "").strip()
        if comp_num:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/OverviewForComplaintServlet"
                f"?requestid=2&vlession=L&vlession={comp_num}"
            )
        if bin_val:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/ComplaintsByAddressServlet"
                f"?requestid=1&allbin={bin_val}"
            )
        return ""

    if record_type in ("permit", "job_status"):
        if is_dob_now_job and job_clean:
            # DOB NOW Public Portal now requires NYC.ID login (since June 2024)
            # Fall through to BIS lookup by job number or BIN instead
            base_job_match = re.match(r'(B\d{8})', job_clean.upper())
            base_job_now = base_job_match.group(1) if base_job_match else job_clean
            if bin_val:
                return (
                    f"https://a810-bisweb.nyc.gov/bisweb/JobsQueryByNumberServlet"
                    f"?passjobnumber={base_job_now}&passdocnumber=01&requestid=1"
                )
        # BIS legacy: direct job query, no login required
        base_job = job_num.split("-")[0].strip() if job_num else ""
        if base_job:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/JobsQueryByNumberServlet"
                f"?passjobnumber={base_job}&passdocnumber=01&requestid=1"
            )
        if bin_val:
            return (
                f"https://a810-bisweb.nyc.gov/bisweb/OverviewByBinServlet"
                f"?requestid=2&allbin={bin_val}&allinquirytype=BXS3OCV4"
            )
        return ""

    if record_type == "inspection":
        job = str(rec.get("job_id") or rec.get("job_filing_number") or rec.get("job_number") or "").replace("-","").strip()
        if job and job.upper().startswith("B"):
            return f"https://a810-bisweb.nyc.gov/bisweb/JobsQueryByNumberServlet?passjobnumber={job}&passdocnumber=01&requestid=1"
        if bin_val:
            return f"https://a810-bisweb.nyc.gov/bisweb/OverviewByBinServlet?requestid=2&allbin={bin_val}&allinquirytype=BXS3OCV4"
        return ""

    if bin_val:
        return (
            f"https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"
            f"?bin={bin_val}"
        )
    return ""


async def run_dob_sync_for_project(project: dict) -> list:
    """Core sync logic: fetch, dedupe, extract fields, save, alert. Used by cron + manual."""
    project_id = str(project["_id"])
    company_id = project.get("company_id", "")
    nyc_bin = project.get("nyc_bin", "")
    project_address = project.get("address", "")
 
    if not nyc_bin and not project_address:
        return []
 
    raw_records = await _query_dob_apis(nyc_bin, project_address)
    if not raw_records:
        return []
 
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
        # Apply permit work-type suffix BEFORE dedup check so the key matches
        # what gets stored — prevents re-insertion on every sync run
        if rec.get("_record_type") == "permit":
            work_suffix = rec.get("work_type") or rec.get("permit_type") or rec.get("permit_sequence__") or ""
            raw_id = f"{raw_id}:{work_suffix}" if work_suffix else raw_id
        if raw_id in existing_ids:
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
                # Only alert if severity escalated to Action
                old_severity = existing.get("severity", "")
                if severity == "Action" and old_severity != "Action":
                    await _send_critical_dob_alert(project, dob_log)
            else:
                result = await db.dob_logs.insert_one(dob_log)
                dob_log["id"] = str(result.inserted_id)
                inserted_logs.append(dob_log)
                if severity == "Action":
                    await _send_critical_dob_alert(project, dob_log)
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
 
    if config.nyc_bbl is not None:
        update_fields["nyc_bbl"] = config.nyc_bbl.strip() or None
 
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
        "nyc_bbl": updated.get("nyc_bbl"),
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
        "nyc_bbl": project.get("nyc_bbl"),
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

        async with httpx.AsyncClient(timeout=30) as hc:
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


@api_router.post("/annotations")
async def create_annotation(data: dict, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    """Create a document annotation (plan note)."""
    project_id = data.get("project_id")
    document_path = data.get("document_path")
    page_number = data.get("page_number", 1)
    position = data.get("position", {"x": 0.5, "y": 0.5})
    comment = data.get("comment", "")
    recipients_input = data.get("recipients", "all")

    if not project_id or not document_path:
        raise HTTPException(status_code=400, detail="project_id and document_path are required")

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

    now = datetime.now(timezone.utc)
    doc = {
        "project_id": project_id,
        "document_path": document_path,
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
    """Get annotations for a document with server-side visibility filtering."""
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
from backend.permit_renewal import create_permit_renewal_routes, nightly_renewal_scan

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
        async with httpx.AsyncClient(timeout=15) as client_http:
            resp = await client_http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
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

        # Timestamp — WaAPI uses 't' (epoch seconds) inside _data, 'timestamp' elsewhere
        ts = msg.get("timestamp") or inner.get("t") or inner.get("timestamp") or 0
        try:
            ts = int(ts)
        except Exception:
            ts = 0

        return {
            "message_id": msg_id,
            "from": from_field,
            "sender": author,
            "to": to_field,
            "body": body,
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


async def download_audio(parsed_msg: dict) -> Optional[bytes]:
    """Download audio bytes from parsed message audio URL."""
    audio_url = parsed_msg.get("audio_url")
    if not audio_url:
        return None
    try:
        headers = {}
        if WAAPI_TOKEN and "waapi" in audio_url:
            headers["Authorization"] = f"Bearer {WAAPI_TOKEN}"
        async with httpx.AsyncClient(timeout=30) as client_http:
            resp = await client_http.get(audio_url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"Audio download failed: {e}")
        return None


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio bytes using OpenAI Whisper API. Primary language: Yiddish."""
    if not OPENAI_API_KEY:
        logger.warning("Transcription skipped — OPENAI_API_KEY not set")
        return ""
    try:
        import json as _json
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        # Build multipart form
        files_payload = {
            "file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
            "model": (None, "whisper-1"),
            "language": (None, "yi"),  # Yiddish primary
        }
        async with httpx.AsyncClient(timeout=60) as client_http:
            resp = await client_http.post(url, headers=headers, files=files_payload)
            resp.raise_for_status()
            return resp.json().get("text", "")
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
        async with httpx.AsyncClient(timeout=10) as client_http:
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

async def _handle_who_on_site(project_id: str) -> str:
    """Return formatted worker list by company for a project."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": today_start},
        "status": "checked_in",
        "is_deleted": {"$ne": True},
    }).to_list(500)
    if not checkins:
        return "No workers currently checked in on site."
    # Group by company
    by_company: Dict[str, list] = {}
    for ci in checkins:
        co = ci.get("company_name", "Unknown")
        name = ci.get("worker_name", "Unknown")
        by_company.setdefault(co, []).append(name)
    lines = [f"*Workers on site today ({len(checkins)} total):*"]
    for company, workers in sorted(by_company.items()):
        lines.append(f"\n_{company}_ ({len(workers)}):")
        for w in sorted(workers):
            lines.append(f"  - {w}")
    return "\n".join(lines)


async def _handle_dob_status(project_id: str) -> str:
    """Return project DOB info summary."""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        return "Project not found."
    dob_cfg = project.get("dob_config", {})
    bin_number = dob_cfg.get("bin_number", "N/A")
    lines = [f"*DOB Status for {project.get('name', 'Unknown')}*"]
    lines.append(f"BIN: {bin_number}")
    # Recent violations
    recent = await db.dob_logs.find({
        "project_id": project_id,
        "record_type": "violation",
    }).sort("detected_at", -1).to_list(5)
    if recent:
        lines.append(f"\nRecent violations ({len(recent)}):")
        for v in recent:
            desc = v.get("description", v.get("raw_dob_id", ""))[:80]
            lines.append(f"  - {desc}")
    else:
        lines.append("\nNo recent violations found.")
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
        async with httpx.AsyncClient(timeout=15) as client:
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
        async with httpx.AsyncClient(timeout=15) as client:
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
            "plan_queries": False,
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
    "who_on_site", "dob_status", "open_items", "material_detection", "plan_queries"
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
    """Index one page. Uses PyMuPDF text length as a pre-filter so dense
    text ('specs') never gets sent to Qwen (cost + accuracy)."""
    now = datetime.now(timezone.utc)

    # Dense text = spec pages, skip Qwen, still store so coverage is complete.
    if page_text and len(page_text.strip()) > 800:
        await db.document_page_index.update_one(
            {"file_id": file_id, "page_number": page_number},
            {"$set": {
                "project_id": project_id,
                "company_id": company_id,
                "file_id": file_id,
                "file_name": file_name,
                "file_hash": file_hash,
                "discipline": discipline,
                "page_number": page_number,
                "sheet_number": None,
                "sheet_title": "[SPECIFICATION PAGE]",
                "floor": None,
                "keywords": [],
                "indexed_at": now,
                "index_version": 1,
            }},
            upsert=True,
        )
        return

    if not page_image_bytes:
        # Cannot send without image bytes — record as unknown page
        await db.document_page_index.update_one(
            {"file_id": file_id, "page_number": page_number},
            {"$set": {
                "project_id": project_id,
                "company_id": company_id,
                "file_id": file_id,
                "file_name": file_name,
                "file_hash": file_hash,
                "discipline": discipline,
                "page_number": page_number,
                "sheet_number": None,
                "sheet_title": None,
                "floor": None,
                "keywords": [],
                "indexed_at": now,
                "index_version": 1,
            }},
            upsert=True,
        )
        return

    b64 = base64.b64encode(page_image_bytes).decode("ascii")
    prompt_text = (
        "Look at the title block of this construction drawing (usually bottom "
        "right or bottom center). Extract: sheet_number (e.g. ME-401, A-201), "
        "sheet_title (e.g. FOURTH FLOOR MECHANICAL PLAN), floor_reference "
        "(e.g. 4TH, 4, ROOF, CELLAR, TYPICAL). "
        'Use null for any field NOT indicated. Return ONLY JSON: '
        '{"sheet_number": ..., "sheet_title": ..., "floor": ...}'
    )

    sheet_number = None
    sheet_title = None
    floor = None
    keywords: List[str] = []

    try:
        async with httpx.AsyncClient(timeout=60.0) as client_http:
            resp = await client_http.post(
                f"{QWEN_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": QWEN_MODEL,
                    "max_tokens": 150,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                                },
                                {"type": "text", "text": prompt_text},
                            ],
                        }
                    ],
                },
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Some vendors wrap JSON in backticks / language tags — strip.
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*", "", content).rstrip("`").strip()
                import json as _json
                try:
                    parsed = _json.loads(content)
                except Exception:
                    parsed = {}
                sheet_number = parsed.get("sheet_number") or None
                sheet_title = parsed.get("sheet_title") or None
                floor = parsed.get("floor") or None
                # Build keywords from sheet_title words for fast search
                if isinstance(sheet_title, str):
                    words = re.findall(r"[A-Za-z0-9\-]{2,}", sheet_title.upper())
                    keywords = list({w for w in words if len(w) >= 2})[:20]
            else:
                logger.warning(
                    f"Qwen returned {resp.status_code} for "
                    f"{file_name} page {page_number}"
                )
    except Exception as e:
        logger.warning(
            f"Qwen call failed for {file_name} page {page_number}: {e}"
        )

    # Normalize floor values to simple digits where possible
    if isinstance(floor, str):
        floor = floor.strip() or None

    await db.document_page_index.update_one(
        {"file_id": file_id, "page_number": page_number},
        {"$set": {
            "project_id": project_id,
            "company_id": company_id,
            "file_id": file_id,
            "file_name": file_name,
            "file_hash": file_hash,
            "discipline": discipline,
            "page_number": page_number,
            "sheet_number": sheet_number,
            "sheet_title": sheet_title,
            "floor": floor,
            "keywords": keywords,
            "indexed_at": now,
            "index_version": 1,
        }},
        upsert=True,
    )


def _pdf_pages_render_and_text(pdf_bytes: bytes, dpi: int = 150):
    """Generator yielding (page_number, page_text, jpeg_bytes_or_None).

    Uses pdf2image (already in requirements) + pdfplumber-style text
    extraction via PyPDF2 if available, else skips the text pre-filter
    for that page.
    """
    # Render images
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(pdf_bytes, dpi=dpi)

    # Try text extraction via PyPDF2 (likely already installed as a dep of
    # the rest of the stack). Fall back to empty string per page if missing.
    page_texts: List[str] = []
    try:
        from pypdf import PdfReader
        import io as _io
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        for p in reader.pages:
            try:
                page_texts.append(p.extract_text() or "")
            except Exception:
                page_texts.append("")
    except Exception:
        try:
            from PyPDF2 import PdfReader as LegacyReader  # type: ignore
            import io as _io
            reader = LegacyReader(_io.BytesIO(pdf_bytes))
            for p in reader.pages:
                try:
                    page_texts.append(p.extract_text() or "")
                except Exception:
                    page_texts.append("")
        except Exception:
            page_texts = ["" for _ in images]

    import io as _io
    for idx, img in enumerate(images, start=1):
        buf = _io.BytesIO()
        try:
            img.save(buf, format="JPEG", quality=82)
            jpeg_bytes = buf.getvalue()
        except Exception:
            jpeg_bytes = None
        text = page_texts[idx - 1] if idx - 1 < len(page_texts) else ""
        yield idx, text, jpeg_bytes


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

        # If any existing index entry for this file already has the same
        # hash we assume the file's content is unchanged and bail out.
        existing = await db.document_page_index.find_one({
            "file_id": file_id,
            "file_hash": file_hash,
        })
        if existing:
            logger.info(
                f"Plan index: {file_name} already indexed at current hash — "
                f"skipping"
            )
            return

        # Render + classify each page. Bound concurrency with a per-file
        # semaphore so we don't fire 200 Qwen calls at once.
        try:
            pages = list(_pdf_pages_render_and_text(pdf_bytes, dpi=150))
        except Exception as e:
            logger.error(f"Plan index: PDF render failed for {file_name}: {e}")
            return

        sem = asyncio.Semaphore(5)
        total = len(pages)

        async def _run(p):
            num, text, jpeg = p
            async with sem:
                await _index_single_page(
                    project_id=project_id,
                    company_id=company_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_hash=file_hash,
                    page_number=num,
                    discipline=discipline,
                    page_text=text,
                    page_image_bytes=jpeg,
                )

        # Log progress every 10 pages by chunking
        CHUNK = 10
        for start in range(0, total, CHUNK):
            batch = pages[start:start + CHUNK]
            await asyncio.gather(*[_run(p) for p in batch])
            logger.info(
                f"Plan index: {file_name}: {min(start + CHUNK, total)}/{total}"
            )

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


async def _parse_plan_query(query: str) -> dict:
    """Parse a natural-language plan request into a search spec."""
    if not OPENAI_API_KEY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client_http:
            resp = await client_http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": (
                            "Parse this construction drawing request. Return ONLY JSON: "
                            '{"discipline": "AR|ME|EL|PL|SP|ST|GN|null", '
                            '"floor": "floor number/name as string or null", '
                            '"sheet_type": "plan|elevation|section|detail|schedule|null", '
                            '"sheet_number": "exact sheet number if mentioned e.g. ME-401 or null", '
                            '"keywords": ["other relevant terms"]}'
                        )},
                        {"role": "user", "content": query},
                    ],
                },
            )
            if resp.status_code != 200:
                return {}
            import json as _json
            parsed = _json.loads(resp.json()["choices"][0]["message"]["content"])
            return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        logger.warning(f"plan query parse failed: {e}")
        return {}


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


async def _handle_plan_query(project_id: str, group_id: str, query: str) -> None:
    """End-to-end: acknowledge, parse, search, render, send via WaAPI."""
    if not QWEN_API_KEY:
        await send_whatsapp_message(group_id, "Plan queries are not configured.")
        return

    # Immediate ack so the user knows we're on it (rendering can take 10s+)
    try:
        await send_whatsapp_message(group_id, "🔍 Searching drawings…")
    except Exception:
        pass

    parsed = await _parse_plan_query(query)
    discipline = (parsed.get("discipline") or "").strip() or None
    floor = parsed.get("floor") or None
    sheet_number_query = (parsed.get("sheet_number") or "").strip() or None
    keywords = parsed.get("keywords") or []

    # Build MongoDB query
    base_query: Dict[str, Any] = {
        "project_id": project_id,
        "sheet_title": {"$ne": "[SPECIFICATION PAGE]"},
    }

    if sheet_number_query:
        # Fast path — exact sheet number match, case-insensitive
        base_query["sheet_number"] = {
            "$regex": f"^{re.escape(sheet_number_query)}$",
            "$options": "i",
        }
    else:
        and_clauses: List[Dict[str, Any]] = []
        if discipline:
            and_clauses.append({"discipline": discipline})
        if floor:
            fr = _floor_regex(str(floor))
            if fr:
                and_clauses.append({"$or": [
                    {"floor": {"$regex": fr, "$options": "i"}},
                    {"sheet_title": {"$regex": fr, "$options": "i"}},
                ]})
        if keywords:
            kw_clauses = []
            for kw in keywords[:6]:
                if isinstance(kw, str) and len(kw.strip()) >= 2:
                    pat = {"$regex": re.escape(kw.strip()), "$options": "i"}
                    kw_clauses.append({"sheet_title": pat})
                    kw_clauses.append({"keywords": pat})
            if kw_clauses:
                and_clauses.append({"$or": kw_clauses})
        if and_clauses:
            base_query["$and"] = and_clauses

    results = await db.document_page_index.find(base_query).limit(5).to_list(5)

    # Sort client-side: exact discipline match first, then floor, then keyword.
    def _rank(doc):
        score = 0
        if discipline and doc.get("discipline") == discipline:
            score += 100
        if floor and (
            str(doc.get("floor") or "").lower() == str(floor).lower()
            or re.search(_floor_regex(str(floor)) or "", doc.get("sheet_title") or "", re.I)
        ):
            score += 50
        return -score  # ascending
    results.sort(key=_rank)
    results = results[:3]

    if not results:
        await send_whatsapp_message(
            group_id,
            "Couldn't find that sheet in the indexed drawings. "
            "Try being more specific (e.g., 'ME-401' or '4th floor mechanical plan'). "
            "Make sure plans are synced and indexed in the app.",
        )
        return

    # Render + upload + send each result
    sent_urls: List[str] = []
    sent_captions: List[str] = []
    import uuid as _uuid
    for i, result in enumerate(results):
        try:
            file_id = result.get("file_id")
            page_number = result.get("page_number")
            sheet_number = result.get("sheet_number") or "Sheet"
            sheet_title = result.get("sheet_title") or "Construction Drawing"

            file_rec = await db.project_files.find_one({"_id": to_query_id(file_id)})
            if not file_rec or not file_rec.get("r2_key"):
                continue

            # Download PDF + render the target page
            try:
                obj = await asyncio.to_thread(
                    _r2_client.get_object, Bucket=R2_BUCKET_NAME, Key=file_rec["r2_key"]
                )
                pdf_bytes = obj["Body"].read()
            except Exception as e:
                logger.warning(f"plan query: R2 get failed: {e}")
                continue

            # Render just the target page at 150 DPI (re-render at 100 if huge)
            try:
                from pdf2image import convert_from_bytes
                imgs = convert_from_bytes(
                    pdf_bytes,
                    dpi=150,
                    first_page=page_number,
                    last_page=page_number,
                )
                if not imgs:
                    continue
                import io as _io
                buf = _io.BytesIO()
                imgs[0].save(buf, format="JPEG", quality=82)
                jpeg_bytes = buf.getvalue()
                if len(jpeg_bytes) > 5 * 1024 * 1024:
                    buf = _io.BytesIO()
                    imgs_low = convert_from_bytes(
                        pdf_bytes,
                        dpi=100,
                        first_page=page_number,
                        last_page=page_number,
                    )
                    imgs_low[0].save(buf, format="JPEG", quality=82)
                    jpeg_bytes = buf.getvalue()
            except Exception as e:
                logger.warning(f"plan query: render failed: {e}")
                continue

            # Upload to R2 at temp/whatsapp/{group}/{uuid}.jpg
            # NOTE: R2 lifecycle rule required: temp/whatsapp/ prefix, 7-day expiry
            temp_key = f"temp/whatsapp/{group_id}/{_uuid.uuid4()}.jpg"
            try:
                r2_url = await asyncio.to_thread(
                    _upload_to_r2, jpeg_bytes, temp_key, "image/jpeg"
                )
            except Exception as e:
                logger.warning(f"plan query: R2 upload failed: {e}")
                continue

            caption = f"{sheet_number} — {sheet_title}"

            # Send via WaAPI send-image, fall back to text on error
            sent_ok = False
            try:
                async with httpx.AsyncClient(timeout=40.0) as client_http:
                    resp = await client_http.post(
                        f"{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/client/action/send-image",
                        headers={
                            "Authorization": f"Bearer {WAAPI_TOKEN}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "chatId": group_id,
                            "image": r2_url,
                            "caption": caption,
                        },
                    )
                    sent_ok = 200 <= resp.status_code < 300
                    if not sent_ok:
                        logger.warning(
                            f"WaAPI send-image returned {resp.status_code}"
                        )
            except Exception as e:
                logger.warning(f"WaAPI send-image error: {e}")

            if not sent_ok:
                # Text fallback
                await send_whatsapp_message(
                    group_id,
                    f"Found: {caption}. View it in the Levelog app under Construction Plans.",
                )

            sent_urls.append(r2_url)
            sent_captions.append(caption)

            # Rate-limit subsequent sends
            if i < len(results) - 1:
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"plan query result send failed: {e}")

    # Log a synthetic bot_plan_response entry for conversation history
    try:
        await db.whatsapp_messages.insert_one({
            "group_id": group_id,
            "sender": "bot",
            "body": sent_captions[0] if sent_captions else "(plan response)",
            "media_urls": sent_urls,
            "type": "bot_plan_response",
            "created_at": datetime.now(timezone.utc),
            "project_id": project_id,
            "company_id": None,
        })
    except Exception:
        pass


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

            # Transcribe audio if present
            body = parsed["body"]
            if parsed["has_audio"]:
                audio_bytes = await download_audio(parsed)
                if audio_bytes:
                    body = await transcribe_audio(audio_bytes)

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

            # ── Plan query (construction drawing lookup) ──
            # Gated on features.plan_queries (default False in bot_config).
            if features.get("plan_queries", False) and body and _has_plan_query_trigger(body):
                asyncio.create_task(
                    _handle_plan_query(str(project_id), group_id, body)
                )
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
        async with httpx.AsyncClient(timeout=10.0) as client_http:
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
        async with httpx.AsyncClient(timeout=30) as client_http:
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
        async with httpx.AsyncClient(timeout=40.0) as client_http:
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
    await db.project_files.create_index([("project_id", 1), ("dropbox_path", 1)], unique=True, sparse=True)
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
                "nyc_bbl": "1008370032",
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
    
    logger.info("Levelog API started successfully with Sync v2.0")
