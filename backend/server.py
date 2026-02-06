from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'blueview-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Create the main app
app = FastAPI(title="Blueview API", version="2.0.0")

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
    """Convert ObjectId to string"""
    if obj and '_id' in obj:
        obj['id'] = str(obj['_id'])
        del obj['_id']
    return obj

def serialize_list(items):
    """Convert list of MongoDB docs to serialized format"""
    return [serialize_id(item) for item in items]

# Auth Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "worker"
    company_name: Optional[str] = None  # For display, but we'll use company_id
    company_id: Optional[str] = None  # Link to companies collection
    phone: Optional[str] = None
    trade: Optional[str] = None

class UserLogin(BaseModel):
    email: str  # Can be email or username for site devices
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_name: Optional[str] = None
    company_id: Optional[str] = None  # Add company_id
    phone: Optional[str] = None
    trade: Optional[str] = None
    assigned_projects: List[str] = []
    created_at: Optional[datetime] = None

class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"

# Project Models
class ProjectCreate(BaseModel):
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"
    # company_id will be auto-injected from current_user

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"
    company_id: Optional[str] = None  # Add company_id
    company_name: Optional[str] = None  # For display
    nfc_tags: List[Dict] = []
    dropbox_folder: Optional[str] = None
    dropbox_enabled: bool = False
    created_at: Optional[datetime] = None

# Worker Models
class WorkerCreate(BaseModel):
    name: str
    phone: str
    trade: str
    company: str
    device_id: Optional[str] = None
    # company_id (admin's company) will be auto-injected

class WorkerResponse(BaseModel):
    id: str
    name: str
    phone: str
    trade: str
    company: str
    company_id: Optional[str] = None  # Admin's company who manages this worker
    status: str = "active"
    certifications: List[Dict] = []
    signature: Optional[Dict] = None
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
    status: str  # 'checked', 'unchecked', 'na'
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
    # Safety checklist
    safety_checklist: Optional[Dict[str, Dict]] = None
    # Corrective actions
    corrective_actions: Optional[str] = None
    corrective_actions_na: bool = False
    corrective_actions_audit: Optional[Dict] = None
    # Incident log
    incident_log: Optional[str] = None
    incident_log_na: bool = False
    incident_log_audit: Optional[Dict] = None
    # Signatures
    superintendent_signature: Optional[Dict] = None
    competent_person_signature: Optional[Dict] = None

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
    # Safety checklist
    safety_checklist: Optional[Dict[str, Dict]] = None
    # Corrective actions
    corrective_actions: Optional[str] = None
    corrective_actions_na: bool = False
    corrective_actions_audit: Optional[Dict] = None
    # Incident log
    incident_log: Optional[str] = None
    incident_log_na: bool = False
    incident_log_audit: Optional[Dict] = None
    # Signatures
    superintendent_signature: Optional[Dict] = None
    competent_person_signature: Optional[Dict] = None

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
    items: List[Dict[str, Any]]  # [{text: str, order: int}]

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
    assigned_users: List[Dict[str, str]]  # [{id, name, email}]
    created_at: datetime
    completion_stats: Optional[Dict[str, int]] = None  # {completed: X, total: Y}

class ChecklistCompletionUpdate(BaseModel):
    item_completions: Dict[str, Dict[str, Any]]  # {item_id: {checked: bool, note: str, timestamp: str}}

class ChecklistCompletionResponse(BaseModel):
    id: str
    assignment_id: str
    user_id: str
    user_name: str
    item_completions: Dict[str, Dict[str, Any]]
    progress: Dict[str, int]  # {completed: X, total: Y}
    last_updated: datetime

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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        site_mode = payload.get("site_mode", False)
        project_id = payload.get("project_id")
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # For site devices, fetch from site_devices collection
        if site_mode:
            device = await db.site_devices.find_one({"_id": ObjectId(user_id)})
            if not device:
                raise HTTPException(status_code=401, detail="Device not found")
            
            device_data = serialize_id(device)
            device_data["site_mode"] = True
            device_data["role"] = "site_device"
            
            # Get company_id from project
            if device.get("project_id"):
                project = await db.projects.find_one({"_id": ObjectId(device["project_id"])})
                if project:
                    device_data["company_id"] = project.get("company_id")
            
            return device_data
        
        # Regular user
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        user_data = serialize_id(user)
        user_data["site_mode"] = False
        return user_data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_admin_user(current_user = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def get_user_company_id(current_user):
    """Get the company_id from current user"""
    # Site devices inherit company from their project
    if current_user.get("site_mode"):
        return current_user.get("company_id")
    
    # Regular users have company_id directly
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
            {"$set": {"last_login": datetime.now(timezone.utc)}}
        )
        
        # Get company_id from project
        company_id = None
        if device.get("project_id"):
            project = await db.projects.find_one({"_id": ObjectId(device["project_id"])})
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
    user_dict["created_at"] = datetime.now(timezone.utc)
    user_dict["assigned_projects"] = []
    
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
    
    # For site devices, include project info
    if user.get("site_mode"):
        project_id = user.get("project_id")
        if project_id:
            project = await db.projects.find_one({"_id": ObjectId(project_id)})
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
    query = {}
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
    user_dict["created_at"] = datetime.now(timezone.utc)
    user_dict["assigned_projects"] = []
    
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
    user = await db.users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**serialize_id(user))

@api_router.put("/admin/users/{user_id}", response_model=UserResponse)
async def update_admin_user(user_id: str, user_data: dict, admin = Depends(get_admin_user)):
    # Remove password from update if not provided
    update_data = {k: v for k, v in user_data.items() if v is not None and k != "password"}
    if "password" in user_data and user_data["password"]:
        update_data["password"] = hash_password(user_data["password"])
    
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = await db.users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
    return UserResponse(**serialize_id(user))

@api_router.delete("/admin/users/{user_id}")
async def delete_admin_user(user_id: str, admin = Depends(get_admin_user)):
    result = await db.users.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted successfully"}

@api_router.post("/admin/users/{user_id}/assign-projects")
async def assign_projects_to_user(user_id: str, project_ids: dict, admin = Depends(get_admin_user)):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"assigned_projects": project_ids.get("project_ids", [])}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Projects assigned successfully"}

# ==================== ADMIN SUBCONTRACTORS ====================

@api_router.get("/admin/subcontractors", response_model=List[SubcontractorResponse])
async def get_subcontractors(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {}
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
    sub_dict["created_at"] = datetime.now(timezone.utc)
    sub_dict["workers_count"] = 0
    sub_dict["assigned_projects"] = []
    sub_dict["company_id"] = admin.get("company_id")
    
    result = await db.subcontractors.insert_one(sub_dict)
    sub_dict["id"] = str(result.inserted_id)
    del sub_dict["password"]
    
    return SubcontractorResponse(**sub_dict)

@api_router.get("/admin/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def get_subcontractor(sub_id: str, current_user = Depends(get_current_user)):
    sub = await db.subcontractors.find_one({"_id": ObjectId(sub_id)}, {"password": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    return SubcontractorResponse(**serialize_id(sub))

@api_router.put("/admin/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def update_subcontractor(sub_id: str, sub_data: dict, admin = Depends(get_admin_user)):
    update_data = {k: v for k, v in sub_data.items() if v is not None and k != "password"}
    if "password" in sub_data and sub_data["password"]:
        update_data["password"] = hash_password(sub_data["password"])
    
    result = await db.subcontractors.update_one(
        {"_id": ObjectId(sub_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    
    sub = await db.subcontractors.find_one({"_id": ObjectId(sub_id)}, {"password": 0})
    return SubcontractorResponse(**serialize_id(sub))

@api_router.delete("/admin/subcontractors/{sub_id}")
async def delete_subcontractor(sub_id: str, admin = Depends(get_admin_user)):
    result = await db.subcontractors.delete_one({"_id": ObjectId(sub_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    return {"message": "Subcontractor deleted successfully"}

# ==================== OWNER - COMPANY MANAGEMENT ====================

@api_router.get("/owner/companies")
async def get_companies(current_user = Depends(get_current_user)):
    """Get all companies (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    companies = await db.companies.find({}).to_list(1000)
    return serialize_list(companies)

@api_router.post("/owner/companies")
async def create_company(company_data: CompanyCreate, current_user = Depends(get_current_user)):
    """Create a new company (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    # Check if company name already exists
    existing = await db.companies.find_one({"name": company_data.name})
    if existing:
        raise HTTPException(status_code=400, detail="Company name already exists")
    
    company_dict = {
        "name": company_data.name,
        "created_at": datetime.now(timezone.utc),
        "created_by": current_user.get("id")
    }
    
    result = await db.companies.insert_one(company_dict)
    company_dict["id"] = str(result.inserted_id)
    
    return company_dict

@api_router.post("/owner/admins")
async def create_admin_with_company(admin_data: dict, current_user = Depends(get_current_user)):
    """Create admin account with company (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    # Required fields
    required = ["email", "password", "name", "company_name"]
    for field in required:
        if field not in admin_data or not admin_data[field]:
            raise HTTPException(status_code=400, detail=f"{field} is required")
    
    # Check if email exists
    existing_user = await db.users.find_one({"email": admin_data["email"]})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create company first
    company_name = admin_data["company_name"]
    existing_company = await db.companies.find_one({"name": company_name})
    
    if existing_company:
        company_id = str(existing_company["_id"])
    else:
        company_doc = {
            "name": company_name,
            "created_at": datetime.now(timezone.utc),
            "created_by": current_user.get("id")
        }
        company_result = await db.companies.insert_one(company_doc)
        company_id = str(company_result.inserted_id)
    
    # Create admin user
    user_doc = {
        "email": admin_data["email"],
        "password": hash_password(admin_data["password"]),
        "name": admin_data["name"],
        "role": "admin",
        "company_id": company_id,
        "company_name": company_name,
        "created_at": datetime.now(timezone.utc),
        "assigned_projects": []
    }
    
    user_result = await db.users.insert_one(user_doc)
    
    return {
        "id": str(user_result.inserted_id),
        "email": admin_data["email"],
        "name": admin_data["name"],
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
    
    admins = await db.users.find({"role": "admin"}, {"password": 0}).to_list(1000)
    return serialize_list(admins)

@api_router.delete("/owner/admins/{admin_id}")
async def delete_admin_account(admin_id: str, current_user = Depends(get_current_user)):
    """Delete admin account (owner only)"""
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    result = await db.users.delete_one({"_id": ObjectId(admin_id), "role": "admin"})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    return {"message": "Admin account deleted successfully"}

# ==================== DATA MIGRATION ====================

@api_router.post("/admin/migrate-company-data")
async def migrate_company_data(migration_data: dict, current_user = Depends(get_current_user)):
    """
    Assign existing data to companies.
    migration_data format: {
        "assignments": [
            {"admin_email": "admin@company.com", "company_id": "company_id_here"}
        ]
    }
    """
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    
    assignments = migration_data.get("assignments", [])
    results = []
    
    for assignment in assignments:
        admin_email = assignment.get("admin_email")
        company_id = assignment.get("company_id")
        
        if not admin_email or not company_id:
            continue
        
        # Find admin user
        admin = await db.users.find_one({"email": admin_email, "role": "admin"})
        if not admin:
            results.append({"email": admin_email, "status": "not_found"})
            continue
        
        admin_id = str(admin["_id"])
        
        # Get company info
        company = await db.companies.find_one({"_id": ObjectId(company_id)})
        if not company:
            results.append({"email": admin_email, "status": "company_not_found"})
            continue
        
        company_name = company.get("name")
        
        # Update admin user
        await db.users.update_one(
            {"_id": admin["_id"]},
            {"$set": {"company_id": company_id, "company_name": company_name}}
        )
        
        # Update all projects created by this admin
        await db.projects.update_many(
            {"admin_id": admin_id},
            {"$set": {"company_id": company_id, "company_name": company_name}}
        )
        
        # Update all workers created by this admin
        await db.workers.update_many(
            {"admin_id": admin_id},
            {"$set": {"company_id": company_id}}
        )
        
        # Update all checkins
        await db.checkins.update_many(
            {"admin_id": admin_id},
            {"$set": {"company_id": company_id}}
        )
        
        # Update all daily logs
        await db.daily_logs.update_many(
            {"created_by": admin_id},
            {"$set": {"company_id": company_id}}
        )
        
        # Update site devices
        projects = await db.projects.find({"company_id": company_id}).to_list(1000)
        project_ids = [str(p["_id"]) for p in projects]
        
        await db.site_devices.update_many(
            {"project_id": {"$in": project_ids}},
            {"$set": {"company_id": company_id}}
        )
        
        results.append({
            "email": admin_email,
            "company_name": company_name,
            "status": "success"
        })
    
    return {"results": results}

# ==================== SITE DEVICE MANAGEMENT ====================

@api_router.get("/admin/site-devices")
async def get_site_devices(admin = Depends(get_admin_user)):
    """Get all site devices"""
    company_id = get_user_company_id(admin)
    
    devices = await db.site_devices.find({}, {"password": 0}).to_list(1000)
    result = []
    for device in devices:
        device_data = serialize_id(device)
        # Get project name
        if device.get("project_id"):
            project = await db.projects.find_one({"_id": ObjectId(device["project_id"])})
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
    existing = await db.site_devices.find_one({"username": device_data.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Verify project exists and belongs to admin's company
    project = await db.projects.find_one({"_id": ObjectId(device_data.project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check company access
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    device_dict = device_data.model_dump()
    device_dict["password"] = hash_password(device_dict["password"])
    device_dict["is_active"] = True
    device_dict["created_at"] = datetime.now(timezone.utc)
    device_dict["created_by"] = admin.get("id")
    device_dict["company_id"] = project.get("company_id")
    
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
    device = await db.site_devices.find_one({"_id": ObjectId(device_id)}, {"password": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Site device not found")
    
    device_data = serialize_id(device)
    if device.get("project_id"):
        project = await db.projects.find_one({"_id": ObjectId(device["project_id"])})
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
    
    result = await db.site_devices.update_one(
        {"_id": ObjectId(device_id)},
        {"$set": update_fields}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Site device not found")
    
    return {"message": "Site device updated successfully"}

@api_router.delete("/admin/site-devices/{device_id}")
async def delete_site_device(device_id: str, admin = Depends(get_admin_user)):
    """Delete a site device"""
    result = await db.site_devices.delete_one({"_id": ObjectId(device_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Site device not found")
    return {"message": "Site device deleted successfully"}

@api_router.get("/projects/{project_id}/site-devices")
async def get_project_site_devices(project_id: str, admin = Depends(get_admin_user)):
    """Get all site devices for a specific project"""
    devices = await db.site_devices.find(
        {"project_id": project_id},
        {"password": 0}
    ).to_list(100)
    return serialize_list(devices)

# ==================== PROJECTS ====================

@api_router.get("/projects", response_model=List[ProjectResponse])
async def get_projects(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    # Filter by company_id if user has one
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    projects = await db.projects.find(query).to_list(1000)
    return [ProjectResponse(**serialize_id(p)) for p in projects]

@api_router.post("/projects", response_model=ProjectResponse)
async def create_project(project_data: ProjectCreate, admin = Depends(get_admin_user)):
    project_dict = project_data.model_dump()
    project_dict["created_at"] = datetime.now(timezone.utc)
    project_dict["nfc_tags"] = []
    project_dict["dropbox_enabled"] = False
    project_dict["dropbox_folder"] = None
    
    # IMPORTANT: Auto-inject company_id from admin
    project_dict["company_id"] = admin.get("company_id")
    project_dict["company_name"] = admin.get("company_name")
    project_dict["admin_id"] = admin.get("id")
    
    result = await db.projects.insert_one(project_dict)
    project_dict["id"] = str(result.inserted_id)
    
    return ProjectResponse(**project_dict)

@api_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
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
    
    result = await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    return ProjectResponse(**serialize_id(project))

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, admin = Depends(get_admin_user)):
    result = await db.projects.delete_one({"_id": ObjectId(project_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Project deleted successfully"}

# ==================== PROJECT NFC TAGS ====================

@api_router.get("/projects/{project_id}/nfc-tags")
async def get_project_nfc_tags(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.get("nfc_tags", [])

@api_router.post("/projects/{project_id}/nfc-tags")
async def add_nfc_tag_to_project(project_id: str, tag_data: NfcTagCreate, admin = Depends(get_admin_user)):
    # Get project and verify company access
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    company_id = get_user_company_id(admin)
    if company_id and project.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this project")
    
    # Create NFC tag document
    nfc_tag = {
        "tag_id": tag_data.tag_id,
        "project_id": project_id,
        "location_description": tag_data.location_description,
        "created_at": datetime.now(timezone.utc),
        "admin_id": admin["id"],
        "company_id": project.get("company_id"),
        "status": "active"
    }
    
    # Store in nfc_tags collection
    await db.nfc_tags.insert_one(nfc_tag)
    
    # Also update project's nfc_tags array
    await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$push": {"nfc_tags": {"tag_id": tag_data.tag_id, "location": tag_data.location_description}}}
    )
    
    # Fetch updated project
    updated_project = await db.projects.find_one({"_id": ObjectId(project_id)})
    return {
        "message": "NFC tag registered successfully",
        "tag_id": tag_data.tag_id,
        "project": serialize_id(updated_project)
    }

@api_router.delete("/projects/{project_id}/nfc-tags/{tag_id}")
async def remove_nfc_tag_from_project(project_id: str, tag_id: str, admin = Depends(get_admin_user)):
    await db.nfc_tags.delete_one({"tag_id": tag_id, "project_id": project_id})
    await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$pull": {"nfc_tags": {"tag_id": tag_id}}}
    )
    return {"message": "NFC tag removed successfully"}

# ==================== NFC TAG INFO (PUBLIC) ====================

@api_router.get("/nfc-tags/{tag_id}/info", response_model=NfcTagInfo)
async def get_nfc_tag_info(tag_id: str):
    """Public endpoint - no auth required. Used by workers scanning NFC tags."""
    tag = await db.nfc_tags.find_one({"tag_id": tag_id, "status": "active"})
    if not tag:
        raise HTTPException(status_code=404, detail="NFC tag not found or inactive")
    
    # Get project info
    project = await db.projects.find_one({"_id": ObjectId(tag["project_id"])})
    
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
            "status": "active"
        })
        
        if not tag:
            raise HTTPException(status_code=404, detail="Invalid check-in link")
        
        project = await db.projects.find_one({"_id": ObjectId(project_id)})
        
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


@api_router.post("/checkin/submit")
async def submit_checkin(checkin_data: PublicCheckInSubmit):
    """Public endpoint - workers check in via this"""
    try:
        # Verify tag
        tag = await db.nfc_tags.find_one({
            "tag_id": checkin_data.tag_id,
            "project_id": checkin_data.project_id,
            "status": "active"
        })
        
        if not tag:
            raise HTTPException(status_code=404, detail="Invalid check-in")
        
        project = await db.projects.find_one({"_id": ObjectId(checkin_data.project_id)})
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        admin_id = project.get("admin_id")
        company_id = project.get("company_id")
        
        # Find or create worker
        worker = await db.workers.find_one({"phone": checkin_data.phone})
        
        if not worker:
            new_worker = {
                "name": checkin_data.name,
                "phone": checkin_data.phone,
                "company": checkin_data.company,
                "trade": checkin_data.trade,
                "admin_id": admin_id,
                "company_id": company_id,
                "created_at": datetime.now(timezone.utc),
                "status": "active"
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
                await db.workers.update_one(
                    {"_id": worker["_id"]},
                    {"$set": update_fields}
                )
        
        # Check if already checked in today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        existing_checkin = await db.checkins.find_one({
            "worker_id": str(worker["_id"]),
            "project_id": checkin_data.project_id,
            "check_in_time": {"$gte": today_start},
            "status": "checked_in"
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
        now = datetime.now(timezone.utc)
        checkin_record = {
            "worker_id": str(worker["_id"]),
            "worker_name": worker.get("name"),
            "worker_phone": worker.get("phone"),
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
            "timestamp": now
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
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    workers = await db.workers.find(query).to_list(1000)
    return [WorkerResponse(**serialize_id(w)) for w in workers]

@api_router.post("/workers/register")
async def register_worker(worker_data: WorkerCreate):
    """Public endpoint - allows workers to self-register via NFC check-in."""
    # Check if worker with phone exists
    existing = await db.workers.find_one({"phone": worker_data.phone})
    if existing:
        return {"worker_id": str(existing["_id"]), "message": "Worker already registered"}
    
    worker_dict = worker_data.model_dump()
    worker_dict["status"] = "active"
    worker_dict["created_at"] = datetime.now(timezone.utc)
    worker_dict["certifications"] = []
    worker_dict["signature"] = None
    
    result = await db.workers.insert_one(worker_dict)
    
    return {"worker_id": str(result.inserted_id), "message": "Worker registered successfully"}

@api_router.get("/workers/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, current_user = Depends(get_current_user)):
    worker = await db.workers.find_one({"_id": ObjectId(worker_id)})
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
    
    result = await db.workers.update_one(
        {"_id": ObjectId(worker_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    worker = await db.workers.find_one({"_id": ObjectId(worker_id)})
    return WorkerResponse(**serialize_id(worker))

@api_router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str, admin = Depends(get_admin_user)):
    result = await db.workers.delete_one({"_id": ObjectId(worker_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"message": "Worker deleted successfully"}

# ==================== CHECK-INS ====================

@api_router.post("/checkin")
async def check_in_worker(checkin_data: CheckInCreate):
    """Public endpoint - allows workers to check in via NFC or manual."""
    # Find worker
    worker = None
    if checkin_data.worker_id:
        worker = await db.workers.find_one({"_id": ObjectId(checkin_data.worker_id)})
    elif checkin_data.phone:
        worker = await db.workers.find_one({"phone": checkin_data.phone})
    
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Find project from tag or direct project_id
    project = None
    if checkin_data.tag_id:
        tag = await db.nfc_tags.find_one({"tag_id": checkin_data.tag_id, "status": "active"})
        if tag:
            project = await db.projects.find_one({"_id": ObjectId(tag["project_id"])})
    elif checkin_data.project_id:
        project = await db.projects.find_one({"_id": ObjectId(checkin_data.project_id)})
    
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
        "timestamp": now
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
    result = await db.checkins.update_one(
        {"_id": ObjectId(checkin_id)},
        {"$set": {"check_out_time": datetime.now(timezone.utc), "status": "checked_out"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Check-in record not found")
    return {"message": "Check-out successful"}

@api_router.get("/checkins/project/{project_id}")
async def get_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    checkins = await db.checkins.find({"project_id": project_id}).to_list(1000)
    return serialize_list(checkins)

@api_router.get("/checkins/project/{project_id}/active")
async def get_active_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    checkins = await db.checkins.find({
        "project_id": project_id,
        "status": "checked_in"
    }).to_list(1000)
    return serialize_list(checkins)

@api_router.get("/checkins/project/{project_id}/today")
async def get_today_project_checkins(project_id: str, current_user = Depends(get_current_user)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    checkins = await db.checkins.find({
        "project_id": project_id,
        "check_in_time": {"$gte": today_start}
    }).to_list(1000)
    return serialize_list(checkins)

# ==================== DAILY LOGS ====================

@api_router.get("/daily-logs")
async def get_daily_logs(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {}
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
    
    # Get project to inject company_id
    project = await db.projects.find_one({"_id": ObjectId(log_data.project_id)})
    if project:
        log_dict["company_id"] = project.get("company_id")
    
    result = await db.daily_logs.insert_one(log_dict)
    log_dict["id"] = str(result.inserted_id)
    
    return DailyLogResponse(**log_dict)

@api_router.put("/daily-logs/{log_id}")
async def update_daily_log(log_id: str, update_data: dict, current_user = Depends(get_current_user)):
    """Update an existing daily log"""
    # Remove fields that shouldn't be updated directly
    update_data.pop("id", None)
    update_data.pop("_id", None)
    update_data.pop("created_at", None)
    update_data.pop("created_by", None)
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    update_data["updated_by"] = current_user.get("id")
    update_data["updated_by_name"] = current_user.get("full_name") or current_user.get("name") or current_user.get("device_name")
    
    result = await db.daily_logs.update_one(
        {"_id": ObjectId(log_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    # Return updated log
    log = await db.daily_logs.find_one({"_id": ObjectId(log_id)})
    return serialize_id(log)

@api_router.get("/daily-logs/{log_id}", response_model=DailyLogResponse)
async def get_daily_log(log_id: str, current_user = Depends(get_current_user)):
    log = await db.daily_logs.find_one({"_id": ObjectId(log_id)})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    return DailyLogResponse(**serialize_id(log))

@api_router.get("/daily-logs/project/{project_id}")
async def get_project_daily_logs(project_id: str, current_user = Depends(get_current_user)):
    logs = await db.daily_logs.find({"project_id": project_id}).sort("date", -1).to_list(1000)
    return serialize_list(logs)

# ==================== REPORTS ====================

@api_router.get("/reports")
async def get_reports(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    reports = await db.reports.find(query).to_list(1000)
    return serialize_list(reports)

@api_router.get("/reports/project/{project_id}")
async def get_project_reports(project_id: str, current_user = Depends(get_current_user)):
    reports = await db.reports.find({"project_id": project_id}).to_list(1000)
    return serialize_list(reports)

# ==================== DROPBOX INTEGRATION ====================

@api_router.get("/dropbox/status")
async def get_dropbox_status(current_user = Depends(get_current_user)):
    # Check if user has Dropbox connected
    dropbox_config = await db.integrations.find_one({"type": "dropbox", "user_id": current_user.get("id")})
    if dropbox_config:
        return {
            "connected": True,
            "account_email": dropbox_config.get("account_email"),
            "connected_at": dropbox_config.get("connected_at")
        }
    return {"connected": False, "account_email": None, "connected_at": None}

@api_router.get("/dropbox/auth-url")
async def get_dropbox_auth_url(current_user = Depends(get_current_user)):
    app_key = os.environ.get("DROPBOX_APP_KEY", "37ueec2e4se8gbg")
    # Use the preview URL for callback
    base_url = os.environ.get("BASE_URL", "https://blueview2-production.up.railway.app")
    redirect_uri = f"{base_url}/api/dropbox/callback"
    
    authorize_url = f"https://www.dropbox.com/oauth2/authorize?response_type=code&client_id={app_key}&redirect_uri={redirect_uri}&token_access_type=offline"
    
    return {"authorize_url": authorize_url}

@api_router.post("/dropbox/disconnect")
async def disconnect_dropbox(current_user = Depends(get_current_user)):
    await db.integrations.delete_one({"type": "dropbox", "user_id": current_user.get("id")})
    return {"message": "Dropbox disconnected successfully"}

@api_router.get("/projects/{project_id}/dropbox-files")
async def get_project_dropbox_files(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not project.get("dropbox_enabled") or not project.get("dropbox_folder"):
        return {"files": [], "message": "Dropbox not enabled for this project"}
    
    # Get Dropbox access token
    dropbox_config = await db.integrations.find_one({"type": "dropbox"})
    if not dropbox_config or not dropbox_config.get("access_token"):
        return {"files": [], "message": "Dropbox not connected"}
    
    access_token = dropbox_config.get("access_token")
    folder_path = project.get("dropbox_folder", "")
    
    # Fetch files from Dropbox
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.dropboxapi.com/2/files/list_folder",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={"path": folder_path if folder_path else "", "recursive": False}
            )
            
            if response.status_code != 200:
                logger.error(f"Dropbox list_folder failed: {response.text}")
                return {"files": [], "message": "Failed to fetch files from Dropbox"}
            
            data = response.json()
            files = []
            for entry in data.get("entries", []):
                if entry.get(".tag") == "file":
                    files.append({
                        "name": entry.get("name"),
                        "path": entry.get("path_display"),
                        "size": entry.get("size", 0),
                        "modified": entry.get("client_modified") or entry.get("server_modified"),
                        "id": entry.get("id")
                    })
            
            return {"files": files}
            
        except Exception as e:
            logger.error(f"Error fetching Dropbox files: {e}")
            return {"files": [], "message": str(e)}

@api_router.get("/projects/{project_id}/dropbox-file-url")
async def get_dropbox_file_url(project_id: str, file_path: str, current_user = Depends(get_current_user)):
    """Get a temporary download/view URL for a Dropbox file"""
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get Dropbox access token
    dropbox_config = await db.integrations.find_one({"type": "dropbox"})
    if not dropbox_config or not dropbox_config.get("access_token"):
        raise HTTPException(status_code=400, detail="Dropbox not connected")
    
    access_token = dropbox_config.get("access_token")
    
    async with httpx.AsyncClient() as client:
        try:
            # Get temporary link for the file
            response = await client.post(
                "https://api.dropboxapi.com/2/files/get_temporary_link",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={"path": file_path}
            )
            
            if response.status_code != 200:
                logger.error(f"Dropbox get_temporary_link failed: {response.text}")
                raise HTTPException(status_code=400, detail="Failed to get file URL")
            
            data = response.json()
            return {
                "url": data.get("link"),
                "name": data.get("metadata", {}).get("name"),
                "size": data.get("metadata", {}).get("size")
            }
            
        except httpx.RequestError as e:
            logger.error(f"Dropbox API request failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to connect to Dropbox API")

@api_router.post("/projects/{project_id}/link-dropbox")
async def link_dropbox_folder(project_id: str, folder_data: dict, admin = Depends(get_admin_user)):
    folder_path = folder_data.get("folder_path")
    
    result = await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"dropbox_enabled": True, "dropbox_folder": folder_path}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {"message": "Dropbox folder linked successfully", "folder_path": folder_path}

@api_router.post("/dropbox/complete-auth")
async def complete_dropbox_auth(auth_data: dict, current_user = Depends(get_current_user)):
    """Exchange authorization code for access tokens and store them"""
    code = auth_data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code required")
    
    app_key = os.environ.get("DROPBOX_APP_KEY", "37ueec2e4se8gbg")
    app_secret = os.environ.get("DROPBOX_APP_SECRET", "9uvjvxkh9gvelys")
    
    # Exchange code for tokens
    token_url = "https://api.dropboxapi.com/oauth2/token"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                token_url,
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": app_key,
                    "client_secret": app_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                logger.error(f"Dropbox token exchange failed: {response.text}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            
            if not access_token:
                raise HTTPException(status_code=400, detail="No access token received")
            
            # Get account info to verify connection
            account_response = await client.post(
                "https://api.dropboxapi.com/2/users/get_current_account",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            account_email = None
            if account_response.status_code == 200:
                account_data = account_response.json()
                account_email = account_data.get("email")
            
            # Store tokens in database
            user_id = current_user.get("id")
            now = datetime.now(timezone.utc)
            
            await db.integrations.update_one(
                {"type": "dropbox", "user_id": user_id},
                {
                    "$set": {
                        "type": "dropbox",
                        "user_id": user_id,
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "account_email": account_email,
                        "connected_at": now,
                        "updated_at": now
                    }
                },
                upsert=True
            )
            
            logger.info(f"Dropbox connected for user {user_id} ({account_email})")
            
            return {
                "success": True,
                "message": "Dropbox connected successfully",
                "email": account_email
            }
            
        except httpx.RequestError as e:
            logger.error(f"Dropbox API request failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to connect to Dropbox API")

@api_router.get("/dropbox/callback")
async def dropbox_oauth_callback(code: str = None, error: str = None):
    """
    OAuth callback handler - returns HTML page that extracts the code
    and sends it to the frontend for completion
    """
    if error:
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Dropbox Authorization Failed</title></head>
        <body style="font-family: system-ui; display: flex; align-items: center; justify-content: center; height: 100vh; background: #1a1a2e; color: white;">
            <div style="text-align: center;">
                <h1>Authorization Failed</h1>
                <p>Error: {error}</p>
                <p>Please close this window and try again.</p>
            </div>
        </body>
        </html>
        """
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)
    
    if not code:
        html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Dropbox Authorization</title></head>
        <body style="font-family: system-ui; display: flex; align-items: center; justify-content: center; height: 100vh; background: #1a1a2e; color: white;">
            <div style="text-align: center;">
                <h1>Missing Authorization Code</h1>
                <p>No authorization code received from Dropbox.</p>
                <p>Please close this window and try again.</p>
            </div>
        </body>
        </html>
        """
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)
    
    # Return HTML page with the code that user can copy or auto-redirect
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dropbox Authorization</title>
        <style>
            body {{
                font-family: system-ui, -apple-system, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #0a0a1a 0%, #1a1a3e 50%, #0a0a1a 100%);
                color: white;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: rgba(255,255,255,0.1);
                border-radius: 20px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
                max-width: 500px;
            }}
            h1 {{ color: #4ade80; margin-bottom: 20px; }}
            .code-box {{
                background: rgba(0,0,0,0.3);
                padding: 15px;
                border-radius: 10px;
                font-family: monospace;
                word-break: break-all;
                margin: 20px 0;
                font-size: 14px;
            }}
            .btn {{
                background: #0061FF;
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 10px;
                cursor: pointer;
                font-size: 16px;
                margin: 10px;
            }}
            .btn:hover {{ opacity: 0.9; }}
            .success {{ color: #4ade80; }}
            .info {{ color: #94a3b8; font-size: 14px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✓ Authorization Successful</h1>
            <p>Copy this authorization code back to the Blueview app:</p>
            <div class="code-box" id="code">{code}</div>
            <button class="btn" onclick="copyCode()">Copy Code</button>
            <p class="info">After copying, return to the Blueview app and paste this code to complete the connection.</p>
            <p id="status"></p>
        </div>
        <script>
            function copyCode() {{
                navigator.clipboard.writeText("{code}");
                document.getElementById('status').innerHTML = '<span class="success">Code copied to clipboard!</span>';
            }}
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

# ==================== ADMIN CHECKLISTS ====================

@api_router.get("/admin/checklists")
async def get_admin_checklists(admin = Depends(get_admin_user)):
    """Get all checklists for admin's company"""
    company_id = get_user_company_id(admin)
    
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    checklists = await db.checklists.find(query).to_list(1000)
    
    result = []
    for checklist in checklists:
        checklist_data = serialize_id(checklist)
        
        # Get assignment count
        assignment_count = await db.checklist_assignments.count_documents({
            "checklist_id": checklist_data["id"]
        })
        checklist_data["assignment_count"] = assignment_count
        
        result.append(checklist_data)
    
    return result

@api_router.post("/admin/checklists")
async def create_checklist(checklist_data: ChecklistCreate, admin = Depends(get_admin_user)):
    """Create a new checklist"""
    company_id = get_user_company_id(admin)
    
    # Add unique IDs to items
    items_with_ids = []
    for idx, item in enumerate(checklist_data.items):
        items_with_ids.append({
            "id": str(uuid.uuid4()),
            "text": item.get("text", ""),
            "order": item.get("order", idx)
        })
    
    checklist_dict = {
        "title": checklist_data.title,
        "description": checklist_data.description,
        "items": items_with_ids,
        "company_id": company_id,
        "created_by": admin.get("id"),
        "created_by_name": admin.get("name"),
        "created_at": datetime.now(timezone.utc)
    }
    
    result = await db.checklists.insert_one(checklist_dict)
    checklist_dict["id"] = str(result.inserted_id)
    
    return checklist_dict

@api_router.get("/admin/checklists/{checklist_id}")
async def get_checklist(checklist_id: str, admin = Depends(get_admin_user)):
    """Get a specific checklist"""
    checklist = await db.checklists.find_one({"_id": ObjectId(checklist_id)})
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    return serialize_id(checklist)

@api_router.put("/admin/checklists/{checklist_id}")
async def update_checklist(
    checklist_id: str,
    checklist_data: ChecklistCreate,
    admin = Depends(get_admin_user)
):
    """Update a checklist"""
    # Add/preserve IDs for items
    items_with_ids = []
    for idx, item in enumerate(checklist_data.items):
        items_with_ids.append({
            "id": item.get("id", str(uuid.uuid4())),
            "text": item.get("text", ""),
            "order": item.get("order", idx)
        })
    
    update_data = {
        "title": checklist_data.title,
        "description": checklist_data.description,
        "items": items_with_ids,
        "updated_at": datetime.now(timezone.utc)
    }
    
    result = await db.checklists.update_one(
        {"_id": ObjectId(checklist_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    checklist = await db.checklists.find_one({"_id": ObjectId(checklist_id)})
    return serialize_id(checklist)

@api_router.delete("/admin/checklists/{checklist_id}")
async def delete_checklist(checklist_id: str, admin = Depends(get_admin_user)):
    """Delete a checklist and all its assignments"""
    # Delete all assignments first
    await db.checklist_assignments.delete_many({"checklist_id": checklist_id})
    
    # Delete all completions
    assignments = await db.checklist_assignments.find({"checklist_id": checklist_id}).to_list(1000)
    assignment_ids = [str(a["_id"]) for a in assignments]
    await db.checklist_completions.delete_many({"assignment_id": {"$in": assignment_ids}})
    
    # Delete checklist
    result = await db.checklists.delete_one({"_id": ObjectId(checklist_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    return {"message": "Checklist deleted successfully"}

@api_router.post("/admin/checklists/{checklist_id}/assign")
async def assign_checklist(
    checklist_id: str,
    assignment_data: ChecklistAssignmentCreate,
    admin = Depends(get_admin_user)
):
    """Assign checklist to projects and users"""
    # Verify checklist exists
    checklist = await db.checklists.find_one({"_id": ObjectId(checklist_id)})
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist not found")
    
    assignments_created = []
    
    # Create assignment for each project
    for project_id in assignment_data.project_ids:
        # Verify project exists
        project = await db.projects.find_one({"_id": ObjectId(project_id)})
        if not project:
            continue
        
        # Get user details
        assigned_users = []
        for user_id in assignment_data.user_ids:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if user:
                assigned_users.append({
                    "id": str(user["_id"]),
                    "name": user.get("name"),
                    "email": user.get("email")
                })
        
        assignment_dict = {
            "checklist_id": checklist_id,
            "checklist_title": checklist.get("title"),
            "project_id": project_id,
            "project_name": project.get("name"),
            "assigned_user_ids": assignment_data.user_ids,
            "assigned_users": assigned_users,
            "created_by": admin.get("id"),
            "created_at": datetime.now(timezone.utc),
            "company_id": get_user_company_id(admin)
        }
        
        result = await db.checklist_assignments.insert_one(assignment_dict)
        assignment_dict["id"] = str(result.inserted_id)
        assignments_created.append(assignment_dict)
    
    return {
        "message": f"Checklist assigned to {len(assignments_created)} project(s)",
        "assignments": assignments_created
    }

@api_router.get("/admin/checklists/{checklist_id}/assignments")
async def get_checklist_assignments(checklist_id: str, admin = Depends(get_admin_user)):
    """Get all assignments for a checklist"""
    assignments = await db.checklist_assignments.find(
        {"checklist_id": checklist_id}
    ).to_list(1000)
    
    result = []
    for assignment in assignments:
        assignment_data = serialize_id(assignment)
        
        # Get completion stats
        assignment_id = assignment_data["id"]
        completions = await db.checklist_completions.find(
            {"assignment_id": assignment_id}
        ).to_list(1000)
        
        assignment_data["completions"] = [serialize_id(c) for c in completions]
        result.append(assignment_data)
    
    return result

# ==================== PROJECT CHECKLISTS ====================

@api_router.get("/projects/{project_id}/checklists")
async def get_project_checklists(project_id: str, current_user = Depends(get_current_user)):
    """Get all checklists assigned to a project"""
    assignments = await db.checklist_assignments.find(
        {"project_id": project_id}
    ).to_list(1000)
    
    result = []
    for assignment in assignments:
        assignment_data = serialize_id(assignment)
        
        # Get checklist details
        checklist = await db.checklists.find_one({"_id": ObjectId(assignment["checklist_id"])})
        if checklist:
            assignment_data["checklist"] = serialize_id(checklist)
        
        # Get completion stats for this assignment
        completions = await db.checklist_completions.find(
            {"assignment_id": assignment_data["id"]}
        ).to_list(1000)
        
        completed_count = sum(1 for c in completions if c.get("progress", {}).get("completed") == c.get("progress", {}).get("total"))
        total_assigned = len(assignment.get("assigned_user_ids", []))
        
        assignment_data["completion_stats"] = {
            "completed": completed_count,
            "total": total_assigned
        }
        
        assignment_data["completions"] = [serialize_id(c) for c in completions]
        
        result.append(assignment_data)
    
    return result

# ==================== USER CHECKLISTS ====================

@api_router.get("/checklists/assigned")
async def get_assigned_checklists(current_user = Depends(get_current_user)):
    """Get checklists assigned to current user"""
    user_id = current_user.get("id")
    
    # Find assignments where user is in assigned_user_ids
    assignments = await db.checklist_assignments.find(
        {"assigned_user_ids": user_id}
    ).to_list(1000)
    
    result = []
    for assignment in assignments:
        assignment_data = serialize_id(assignment)
        
        # Get checklist details
        checklist = await db.checklists.find_one({"_id": ObjectId(assignment["checklist_id"])})
        if checklist:
            assignment_data["checklist"] = serialize_id(checklist)
        
        # Get user's completion for this assignment
        completion = await db.checklist_completions.find_one({
            "assignment_id": assignment_data["id"],
            "user_id": user_id
        })
        
        if completion:
            assignment_data["completion"] = serialize_id(completion)
        else:
            assignment_data["completion"] = None
        
        result.append(assignment_data)
    
    return result

@api_router.get("/checklists/assignments/{assignment_id}")
async def get_assignment_details(assignment_id: str, current_user = Depends(get_current_user)):
    """Get assignment details with checklist and user's completion"""
    assignment = await db.checklist_assignments.find_one({"_id": ObjectId(assignment_id)})
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    assignment_data = serialize_id(assignment)
    
    # Get checklist
    checklist = await db.checklists.find_one({"_id": ObjectId(assignment["checklist_id"])})
    if checklist:
        assignment_data["checklist"] = serialize_id(checklist)
    
    # Get user's completion
    user_id = current_user.get("id")
    completion = await db.checklist_completions.find_one({
        "assignment_id": assignment_id,
        "user_id": user_id
    })
    
    if completion:
        assignment_data["completion"] = serialize_id(completion)
    
    return assignment_data

@api_router.put("/checklists/assignments/{assignment_id}/complete")
async def update_checklist_completion(
    assignment_id: str,
    completion_data: ChecklistCompletionUpdate,
    current_user = Depends(get_current_user)
):
    """Update user's completion of a checklist"""
    user_id = current_user.get("id")
    
    # Calculate progress
    total_items = len(completion_data.item_completions)
    completed_items = sum(1 for item in completion_data.item_completions.values() if item.get("checked"))
    
    progress = {
        "completed": completed_items,
        "total": total_items
    }
    
    # Update or create completion record
    now = datetime.now(timezone.utc)
    completion_dict = {
        "assignment_id": assignment_id,
        "user_id": user_id,
        "user_name": current_user.get("name"),
        "item_completions": completion_data.item_completions,
        "progress": progress,
        "last_updated": now
    }
    
    existing = await db.checklist_completions.find_one({
        "assignment_id": assignment_id,
        "user_id": user_id
    })
    
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
    
    return completion_dict

# ==================== STATS / DASHBOARD ====================

@api_router.get("/stats/dashboard")
async def get_dashboard_stats(current_user = Depends(get_current_user)):
    company_id = get_user_company_id(current_user)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    total_workers = await db.workers.count_documents(query)
    
    project_query = {**query, "status": "active"}
    total_projects = await db.projects.count_documents(project_query)
    
    checkin_query = {**query, "status": "checked_in"}
    on_site_now = await db.checkins.count_documents(checkin_query)
    
    today_query = {**query, "check_in_time": {"$gte": today_start}}
    today_checkins = await db.checkins.count_documents(today_query)
    
    return {
        "total_workers": total_workers,
        "total_projects": total_projects,
        "on_site_now": on_site_now,
        "today_checkins": today_checkins
    }

# ==================== ROOT ENDPOINT ====================

@api_router.get("/")
async def root():
    return {"message": "Blueview API v2.0.0", "status": "running"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        "https://blue-view.app",
        "https://www.blue-view.app", 
        "https://blueview.vercel.app",
        "http://localhost:3000",
        "http://localhost:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# Startup event to create indexes and seed data
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Blueview API...")
    
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
    
    # Create owner account if doesn't exist
    owner = await db.users.find_one({"email": "rfs2671@gmail.com"})
    if not owner:
        await db.users.insert_one({
            "email": "rfs2671@gmail.com",
            "password": hash_password("Asdddfgh1$"),
            "name": "Roy Fishman",
            "role": "owner",  # Changed to owner
            "created_at": datetime.now(timezone.utc),
            "assigned_projects": []
        })
        logger.info("Created default owner user")
    elif owner.get("role") == "admin":
        # Upgrade existing admin to owner
        await db.users.update_one(
            {"email": "rfs2671@gmail.com"},
            {"$set": {"role": "owner"}}
        )
        logger.info("Upgraded existing admin to owner role")
    
    logger.info("Blueview API started successfully")
