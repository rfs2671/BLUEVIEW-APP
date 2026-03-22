from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
from bson import ObjectId
import httpx
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re
from dob_complaint_codes import classify_complaint, get_disposition_label, get_category_label

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'blueview-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 720

# Dropbox Configuration
DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY', '37ueec2e4se8gbg')
DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET', '9uvjvxkh9gvelys')
DROPBOX_REDIRECT_URI = os.environ.get('DROPBOX_REDIRECT_URI', 'https://blueview2-production.up.railway.app/api/dropbox/callback')

# Google Places
GOOGLE_PLACES_API_KEY = os.environ.get('GOOGLE_PLACES_API_KEY', '')

# Resend (email)
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')

# Report scheduler
scheduler = AsyncIOScheduler()

# Create the main app
app = FastAPI(title="Blueview API", version="2.0.0")

# CORS - must be added immediately after app creation
# Use both: the standard middleware for preflight (OPTIONS) requests,
# plus a raw middleware that guarantees headers on ALL responses
# including 500s and validation errors that bypass CORSMiddleware.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request, call_next):
    """Fallback: ensure CORS headers are present even on error responses."""
    try:
        response = await call_next(request)
    except Exception:
        # If something truly blows up, still send CORS headers
        from fastapi.responses import JSONResponse
        response = JSONResponse({"detail": "Internal server error"}, status_code=500)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    return response

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

class CompanyCreate(BaseModel):
    name: str
    
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
    """Get today's start/end in UTC, aligned to Eastern Time midnight."""
    now_utc = datetime.now(timezone.utc)
    est_offset = timedelta(hours=-5)
    now_est = now_utc + est_offset
    today_est_midnight = now_est.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_est_midnight - est_offset
    today_end_utc = today_start_utc + timedelta(hours=24)
    return today_start_utc, today_end_utc

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
    name: str

class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# Project Models
class ProjectCreate(BaseModel):
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None
    report_email_list: Optional[List[str]] = None
    report_send_time: Optional[str] = None

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

# Worker Models
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
    status: Optional[str] = None
    dob_link: Optional[str] = None
 
 
class DOBConfigUpdate(BaseModel):
    nyc_bin: Optional[str] = None
    nyc_bbl: Optional[str] = None
    track_dob_status: Optional[bool] = None
    gc_legal_name: Optional[str] = None
 
# Site Device Models
class SiteDeviceCreate(BaseModel):
    project_id: str
    device_name: str
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
            
            # Handle creates
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

                    await collection.insert_one(record)
                    logger.info(f"Created record in {collection_name} with ID {record['_id']}")
                except Exception as e:
                    if "E11000" in str(e):
                        logger.warning(f"Duplicate ID {record.get('_id')} in create, skipping.")
                    else:
                        logger.error(f"Error creating record in {collection_name}: {str(e)}")
            
            # Handle updates
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
                    
                    await collection.update_one(
                        {"_id": to_query_id(record_id), "company_id": company_id},
                        {"$set": record}
                    )
                    logger.info(f"Updated record in {collection_name}")
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
async def login(credentials: UserLogin):
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
async def register(user_data: UserCreate):
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
    Update the authenticated user's display name.
    Available to all roles (admin, owner, cp, worker).
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be empty")

    now = datetime.now(timezone.utc)
    result = await db.users.update_one(
        {"_id": to_query_id(current_user["id"])},
        {"$set": {
            "name": name,
            "full_name": name,      # kept in sync so /auth/me returns both consistently
            "updated_at": now,
        }}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"User {current_user['id']} updated their display name to '{name}'")
    return {"message": "Profile updated", "name": name}


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
    
    # For site devices, include project info
    if user.get("site_mode"):
        project_id = user.get("project_id")
        if project_id:
            project = await db.projects.find_one({"_id": to_query_id(project_id)})
            if project:
                user["project_name"] = project.get("name")
                user["project"] = serialize_id(project)
        
        return {
            "id": user.get("id"),
            "name": user.get("device_name", "Site Device"),
            "username": user.get("username"),
            "role": "site_device",
            "site_mode": True,
            "project_id": user.get("project_id"),
            "project_name": user.get("project_name"),
            "project": user.get("project"),
            "company_id": user.get("company_id")
        }
    
    return user

# ==================== ADMIN USER MANAGEMENT ====================

@api_router.get("/admin/users", response_model=List[UserResponse])
async def get_admin_users(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    # Filter by company if not owner
    query = {"is_deleted": {"$ne": True}}
    if current_user.get("role") != "owner" and company_id:
        query["company_id"] = company_id
    
    users = await db.users.find(query, {"password": 0}).to_list(1000)
    return [UserResponse(**serialize_id(u)) for u in users]

@api_router.post("/admin/users", response_model=UserResponse)
async def create_admin_user(user_data: UserCreate, admin = Depends(get_admin_user)):
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
    
    # IMPORTANT: Inherit company_id from admin creating the user
    user_dict["company_id"] = admin.get("company_id")
    if admin.get("company_name"):
        user_dict["company_name"] = admin.get("company_name")
    
    result = await db.users.insert_one(user_dict)
    user_dict["id"] = str(result.inserted_id)
    del user_dict["password"]
    
    return UserResponse(**user_dict)

@api_router.get("/admin/users/{user_id}", response_model=UserResponse)
async def get_admin_user_by_id(user_id: str, current_user = Depends(get_current_user)):
    user = await db.users.find_one({"_id": to_query_id(user_id), "is_deleted": {"$ne": True}}, {"password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**serialize_id(user))

@api_router.put("/admin/users/{user_id}", response_model=UserResponse)
async def update_admin_user(user_id: str, user_data: dict, admin = Depends(get_admin_user)):
    # Remove password from update if not provided
    update_data = {k: v for k, v in user_data.items() if v is not None and k != "password"}
    if "password" in user_data and user_data["password"]:
        update_data["password"] = hash_password(user_data["password"])
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.users.update_one(
        {"_id": to_query_id(user_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = await db.users.find_one({"_id": to_query_id(user_id)}, {"password": 0})
    return UserResponse(**serialize_id(user))

@api_router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: str, admin = Depends(get_admin_user)):
    # Soft delete
    result = await db.users.update_one(
        {"_id": to_query_id(user_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
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

@api_router.get("/admin/subcontractors", response_model=List[SubcontractorResponse])
async def get_subcontractors(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    subs = await db.subcontractors.find(query, {"password": 0}).to_list(1000)
    return [SubcontractorResponse(**serialize_id(s)) for s in subs]

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
    update_data = {k: v for k, v in sub_data.items() if v is not None and k != "password"}
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
    
    companies = await db.companies.find({"is_deleted": {"$ne": True}}).to_list(1000)
    return serialize_list(companies)

@api_router.post("/owner/companies")
async def create_company(company_data: CompanyCreate, current_user = Depends(get_current_user)):
    """Create a new company (owner only)"""
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
        "is_deleted": False
    }
    
    result = await db.companies.insert_one(company_dict)
    company_dict["id"] = str(result.inserted_id)
    company_dict.pop("_id", None)
    
    return company_dict

@api_router.delete("/owner/companies/{company_id}", tags=["Owner"])
async def hard_delete_company(company_id: str, current_user=Depends(get_current_user)):
    """Hard delete a company and all its users (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    # Delete all users belonging to this company
    await db.users.delete_many({"company_id": company_id})
    
    # Delete the company
    await db.companies.delete_one({"_id": to_query_id(company_id)})
    
    return {"message": "Company and all users permanently deleted"}

    # Check no admins assigned
    admin_count = await db.users.count_documents({
        "company_id": company_id, 
        "role": "admin", 
        "is_deleted": {"$ne": True}
    })
    if admin_count > 0:
        raise HTTPException(status_code=400, detail="Remove all admins from this company first")
    
    result = await db.companies.delete_one({"_id": to_query_id(company_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {"message": "Company deleted successfully"}

class CreateAdminRequest(BaseModel):
    name: str
    email: str
    password: str
    company_name: str

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
    
    user_result = await db.users.insert_one(user_doc)
    
    return {
        "id": str(user_result.inserted_id),
        "email": admin_data.email,
        "name": admin_data.name,
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
    
    admins = await db.users.find({"role": "admin", "is_deleted": {"$ne": True}}, {"password": 0}).to_list(1000)
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

@api_router.get("/projects", response_model=List[ProjectResponse])
async def get_projects(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    # Filter by company_id if user has one
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    projects = await db.projects.find(query).to_list(1000)
    return [ProjectResponse(**serialize_id(p)) for p in projects]

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
    
    result = await db.projects.insert_one(project_dict)
    project_dict["id"] = str(result.inserted_id)
    
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
    
    result = await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    return ProjectResponse(**serialize_id(project))

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
async def upload_osha_card(file_data: dict):
    """Public endpoint - OCR an OSHA/SST card photo using Gemini AI."""
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
                },
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
            })
    
    # Create check-in
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    existing_checkin = await db.checkins.find_one({
        "worker_id": str(worker["_id"]),
        "project_id": project_id,
        "check_in_time": {"$gte": today_start},
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
            "project_id": project_id,
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
            "is_deleted": False
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

@api_router.get("/workers", response_model=List[WorkerResponse])
async def get_workers(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    # Filter by company_id if user has one
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    workers = await db.workers.find(query).to_list(1000)
    return [WorkerResponse(**serialize_id(w)) for w in workers]

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
    update_data = {k: v for k, v in worker_data.items() if v is not None}
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
async def get_all_checkins(date: str = None, current_user = Depends(get_current_user)):
    """Get all check-ins for the user's company"""
    company_id = get_user_company_id(current_user)
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    if date:
        # Parse date as Eastern Time day, convert to UTC range
        est_offset = timedelta(hours=-5)
        day_start_est = datetime.strptime(date, "%Y-%m-%d")
        day_start_utc = day_start_est - est_offset
        day_end_utc = day_start_utc + timedelta(hours=24)
        query["check_in_time"] = {"$gte": day_start_utc, "$lt": day_end_utc}
    checkins = await db.checkins.find(query).sort("check_in_time", -1).to_list(1000)
    
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
    return results

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
        "is_deleted": False
    }
    
    result = await db.checkins.insert_one(checkin_record)
    checkin_record["id"] = str(result.inserted_id)
    checkin_record.pop("_id", None)
    return checkin_record

@api_router.post("/checkin")
async def check_in_worker(checkin_data: CheckInCreate):
    """Public endpoint - allows workers to check in via NFC or manual."""
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
        "is_deleted": False
    }
    
    result = await db.checkins.insert_one(checkin_record)
    checkin_record["id"] = str(result.inserted_id)
    
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
    return {"message": "Check-out successful"}

@api_router.get("/checkins/project/{project_id}")
async def get_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    checkins = await db.checkins.find({"project_id": project_id, "is_deleted": {"$ne": True}}).to_list(1000)
    
    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = await db.workers.find_one({"_id": to_query_id(s["worker_id"]), "is_deleted": {"$ne": True}})
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
    }).to_list(1000)
	
    # Populate missing worker_name from workers collection
    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = await db.workers.find_one({"_id": to_query_id(s["worker_id"]), "is_deleted": {"$ne": True}})
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
    }).to_list(1000)
    
    # Populate missing worker_name from workers collection
    results = []
    for c in checkins:
        s = serialize_id(c)
        if not s.get("worker_name") and s.get("worker_id"):
            worker = await db.workers.find_one({"_id": to_query_id(s["worker_id"]), "is_deleted": {"$ne": True}})
            if worker:
                s["worker_name"] = worker.get("name", "Unknown Worker")
                s["worker_company"] = s.get("worker_company") or worker.get("company")
                s["worker_trade"] = s.get("worker_trade") or worker.get("trade")
        results.append(s)
    return results

# ==================== DAILY LOGS ====================

@api_router.get("/daily-logs")
async def get_daily_logs(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {"is_deleted": {"$ne": True}}
    if company_id:
        query["company_id"] = company_id
    
    logs = await db.daily_logs.find(query).sort("date", -1).to_list(1000)
    return serialize_list(logs)

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
    logs = await db.daily_logs.find({"project_id": project_id, "is_deleted": {"$ne": True}}).sort("date", -1).to_list(1000)
    return serialize_list(logs)

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
    
    devices = await db.site_devices.find({"is_deleted": {"$ne": True}}, {"password": 0}).to_list(1000)
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
    }).to_list(1000)
    
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
    
    checklists = await db.checklists.find(query).sort("created_at", -1).to_list(1000)
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
    }).to_list(1000)
    
    result = []
    for assignment in assignments:
        serialized = serialize_id(dict(assignment))
        
        # Get completion stats
        completions = await db.checklist_completions.find({
            "assignment_id": str(assignment["_id"]) if "_id" in assignment else assignment.get("id")
        }).to_list(1000)
        
        serialized["completion_stats"] = {
            "total_assigned": len(assignment.get("assigned_user_ids", [])),
            "completed": len(completions)
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
    }).to_list(1000)
    
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
    
    reports = await db.reports.find(query).to_list(1000)
    return serialize_list(reports)

@api_router.get("/reports/project/{project_id}")
async def get_project_reports(project_id: str, current_user = Depends(get_current_user)):
    reports = await db.reports.find({"project_id": project_id, "is_deleted": {"$ne": True}}).to_list(1000)
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
    except:
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
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {
            "company_id": company_id,
            "user_id": user_id,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "account_id": token_data.get("account_id"),
            "account_name": account_name,
            "connected_at": now,
            "updated_at": now,
            "is_deleted": False,
        }},
        upsert=True
    )
    
    return HTMLResponse("<html><body><h2>Dropbox connected successfully!</h2><p>You can close this window.</p><script>window.opener && window.opener.postMessage('dropbox-connected','*'); setTimeout(()=>window.close(), 2000);</script></body></html>")

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
    
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {
            "company_id": company_id,
            "user_id": current_user.get("id"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "account_id": token_data.get("account_id"),
            "account_name": account_name,
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
        except:
            pass
    
    await db.dropbox_connections.update_one(
        {"company_id": company_id},
        {"$set": {"is_deleted": True, "access_token": None, "refresh_token": None, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"message": "Dropbox disconnected"}

async def get_dropbox_token(company_id: str) -> Optional[str]:
    """Get valid Dropbox access token, refreshing if needed"""
    connection = await db.dropbox_connections.find_one({
        "company_id": company_id,
        "is_deleted": {"$ne": True}
    })
    
    if not connection or not connection.get("access_token"):
        return None
    
    # Try to use current token, refresh if it fails
    return connection["access_token"]

async def refresh_dropbox_token(company_id: str) -> Optional[str]:
    """Refresh Dropbox token"""
    connection = await db.dropbox_connections.find_one({"company_id": company_id})
    if not connection or not connection.get("refresh_token"):
        return None
    
    async with httpx.AsyncClient() as client_http:
        response = await client_http.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": connection["refresh_token"],
                "client_id": DROPBOX_APP_KEY,
                "client_secret": DROPBOX_APP_SECRET,
            }
        )
    
    if response.status_code == 200:
        token_data = response.json()
        await db.dropbox_connections.update_one(
            {"company_id": company_id},
            {"$set": {"access_token": token_data["access_token"], "updated_at": datetime.now(timezone.utc)}}
        )
        return token_data["access_token"]
    return None

async def dropbox_api_call(company_id: str, method: str, url: str, **kwargs):
    """Make Dropbox API call with automatic token refresh"""
    token = await get_dropbox_token(company_id)
    if not token:
        raise HTTPException(status_code=400, detail="Dropbox not connected")
    
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    
    async with httpx.AsyncClient() as client_http:
        response = await getattr(client_http, method)(url, headers=headers, **kwargs)
    
    # If unauthorized, try refresh
    if response.status_code == 401:
        token = await refresh_dropbox_token(company_id)
        if not token:
            raise HTTPException(status_code=401, detail="Dropbox token expired. Please reconnect.")
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
    """Get files from project's linked Dropbox folder"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    folder_path = project.get("dropbox_folder_path")
    if not folder_path:
        return []
    
    company_id = company_id or project.get("company_id")
    
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
        }
        if entry[".tag"] == "file":
            file_info["size"] = entry.get("size", 0)
            file_info["modified"] = entry.get("server_modified", "")
        files.append(file_info)
    
    return files

@api_router.post("/projects/{project_id}/sync-dropbox")
async def sync_project_dropbox(project_id: str, current_user = Depends(get_current_user)):
    """Sync/refresh project files from Dropbox"""
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
    
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/list_folder",
        json={"path": folder_path, "recursive": True}
    )
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to sync files")
    
    data = response.json()
    file_count = len([e for e in data.get("entries", []) if e[".tag"] == "file"])
    
    # Update sync timestamp
    await db.projects.update_one(
        {"_id": to_query_id(project_id)},
        {"$set": {"dropbox_last_synced": datetime.now(timezone.utc)}}
    )
    
    return {"message": f"Synced {file_count} files", "file_count": file_count}

@api_router.get("/projects/{project_id}/dropbox-file-url")
async def get_dropbox_file_url(project_id: str, file_path: str, current_user = Depends(get_current_user)):
    """Get a temporary download/preview URL for a Dropbox file"""
    project = await db.projects.find_one({"_id": to_query_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = get_user_company_id(current_user)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    company_id = company_id or project.get("company_id")
    
    response = await dropbox_api_call(
        company_id, "post",
        "https://api.dropboxapi.com/2/files/get_temporary_link",
        json={"path": file_path}
    )
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to get file URL")
    
    data = response.json()
    return {"url": data.get("link", ""), "metadata": data.get("metadata", {})}

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
            Generated by Blueview Construction Management • {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}
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
    ).to_list(1000)
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
async def get_daily_log_photo_image(log_id: str, photo_id: str):
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
    current_user = Depends(get_current_user)
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
    logbooks = await db.logbooks.find(query).sort("date", -1).to_list(500)
    return [serialize_id(lb) for lb in logbooks]

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
    """Soft delete a logbook entry"""
    await db.logbooks.update_one(
        {"_id": to_query_id(logbook_id)},
        {"$set": {"is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
    )
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
    }).to_list(1000)

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
async def get_weather(lat: Optional[float] = None, lng: Optional[float] = None, address: Optional[str] = None):
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
    now = datetime.now(timezone.utc)
    target_date = date or now.strftime("%Y-%m-%d")

    # Parse date
    try:
        day_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        day_end = day_start.replace(hour=23, minute=59, second=59)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": day_start, "$lte": day_end},
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
    return {"message": "Blueview API v2.0.0 - Sync Enabled", "status": "running"}

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

@app.get("/checkin/{tag_id}")
async def serve_checkin_page_short(tag_id: str):
    from fastapi.responses import HTMLResponse
    html_path = Path(__file__).parent / "checkin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

@app.get("/checkin/{project_id}/{tag_id}")
async def serve_checkin_page_full(project_id: str, tag_id: str):
    from fastapi.responses import HTMLResponse
    html_path = Path(__file__).parent / "checkin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

# ==================== COMBINED REPORT GENERATOR ====================
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

    BASE_URL = "https://blueview2-production.up.railway.app"

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
        <tr><td style="color:rgba(255,255,255,0.5);font-size:10px;letter-spacing:3px;text-transform:uppercase;padding-bottom:16px;font-family:{font};">BLUEVIEW</td></tr>
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
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background-color:#f8fafc;padding:24px 40px;text-align:center;border-top:1px solid #e2e8f0;" bgcolor="#f8fafc">
      <span style="font-size:11px;color:#94a3b8;">This report was automatically generated on {gen_time} UTC</span><br />
      <span style="font-size:10px;color:#cbd5e1;letter-spacing:3px;text-transform:uppercase;">BLUEVIEW CONSTRUCTION MANAGEMENT</span>
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
    filename = f"Blueview_Report_{project_name}_{date}.pdf"
    
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
    }).sort("date", -1).to_list(1000)
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
    
    endpoints = []
    
    # ── JOB FILINGS (DOB NOW - w9ak-ipjd) ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/w9ak-ipjd.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "job_status",
            "id_field": "job__",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/w9ak-ipjd.json",
            "params": {"house__": house_num, "$where": f"upper(street_name) like '%{street_name}%'", "$limit": "50"},
            "record_type": "job_status",
            "id_field": "job__",
        })
    
    # ── VIOLATIONS: DOB NOW Safety (855j-jady) - NEWEST, check first ──
    if bin_usable:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/855j-jady.json",
            "params": {"bin": nyc_bin, "$limit": "50"},
            "record_type": "violation",
            "id_field": "number",
        })
    if house_num and street_name:
        endpoints.append({
            "url": "https://data.cityofnewyork.us/resource/855j-jady.json",
            "params": {"house_number": house_num, "$where": f"upper(street) like '%{street_name}%'", "$limit": "50"},
            "record_type": "violation",
            "id_field": "number",
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
            "params": {"bin__": nyc_bin, "$limit": "50"},
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
        <p style="text-align: center; font-size: 10px; color: #cbd5e1; margin-top: 16px; letter-spacing: 2px;">BLUEVIEW COMPLIANCE</p>
    </div>
    """
 
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": "Blueview Alerts <alerts@blue-view.app>",
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
        prefix = f"#{comp_num}" if comp_num else ""
        return f"311 Complaint {prefix}: {result['category_label']} — {result['disposition_label']} [{result['risk_level']}]".strip()
 
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
 
        try:
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
            logger.error(f"Failed to upsert dob_log for raw_id={raw_id}: {e}")
 
    logger.info(
        f"DOB sync for project {project_id}: {len(inserted_logs)} new records "
        f"({sum(1 for l in inserted_logs if l.get('severity') == 'Critical')} critical)"
    )
    return inserted_logs
 
 
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
 
    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "nyc_bin": project.get("nyc_bin"),
        "track_dob_status": project.get("track_dob_status", False),
        "total": total,
        "logs": [DOBLogResponse(**serialize_id(dict(log))) for log in logs],
    }
 
 
@api_router.post("/projects/{project_id}/dob-sync")
async def manual_dob_sync(project_id: str, current_user=Depends(get_current_user)):
    """Manual trigger: bypass cron and force immediate DOB fetch. Rate limited 15 min."""
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
 
    try:
        new_logs = await run_dob_sync_for_project(project)
    except Exception as e:
        logger.exception(f"DOB sync failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"DOB sync error: {str(e)}")

    safe_logs = []
    for log in new_logs:
        try:
            safe_logs.append(DOBLogResponse(**serialize_id(dict(log))))
        except Exception as e:
            logger.warning(f"Failed to serialize dob_log {log.get('raw_dob_id')}: {e}")

    return {
        "message": f"DOB sync complete. {len(new_logs)} new record(s) found.",
        "new_records": len(new_logs),
        "critical_count": sum(1 for l in new_logs if l.get("severity") == "Critical"),
        "logs": safe_logs,
    }
 
 
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
        try:
            html = await generate_combined_report(project_id, today)
            resend.Emails.send({
                "from": "Blueview Reports <reports@blue-view.app>",
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

# Include the router in the main app
app.include_router(api_router)

@app.on_event("shutdown")
async def shutdown_db_client():
    if scheduler.running:
        scheduler.shutdown()
    client.close()

# Startup event to create indexes and seed data
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Blueview API with Sync Support...")
    
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
    
    # Create compound indexes for sync queries
    await db.workers.create_index([("company_id", 1), ("updated_at", -1)])
    await db.projects.create_index([("company_id", 1), ("updated_at", -1)])
    await db.checkins.create_index([("company_id", 1), ("updated_at", -1)])
    await db.daily_logs.create_index([("company_id", 1), ("updated_at", -1)])
    await db.daily_logs.create_index([("project_id", 1), ("date", 1)], unique=True, sparse=True)
    await db.nfc_tags.create_index([("company_id", 1), ("updated_at", -1)])
    await db.logbooks.create_index([("project_id", 1), ("log_type", 1), ("date", -1)])
    await db.logbooks.create_index([("company_id", 1), ("date", -1)])
    
    # Create owner account if doesn't exist
    owner = await db.users.find_one({"email": "rfs2671@gmail.com"})
    if not owner:
        now = datetime.now(timezone.utc)
        await db.users.insert_one({
            "email": "rfs2671@gmail.com",
            "password": hash_password("Asdddfgh1$"),
            "name": "Roy Fishman",
            "role": "owner",
            "created_at": now,
            "updated_at": now,
            "assigned_projects": [],
            "is_deleted": False
        })
        logger.info("Created default owner user")
    elif owner.get("role") == "admin":
        # Upgrade existing admin to owner
        await db.users.update_one(
            {"email": "rfs2671@gmail.com"},
            {"$set": {"role": "owner", "updated_at": datetime.now(timezone.utc)}}
        )
        logger.info("Upgraded existing admin to owner role")
    
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
    
    scheduler.start()
    logger.info("📧 Report email scheduler started")
    logger.info("🏗️ DOB compliance scanner scheduled (every 30 minutes)")
    
    # DOB collection indexes
    await db.dob_logs.create_index([("project_id", 1), ("detected_at", -1)])
    await db.dob_logs.create_index([("company_id", 1)])
    await db.dob_logs.create_index("raw_dob_id", unique=True, sparse=True)
    
    logger.info("Blueview API started successfully with Sync v2.0")
