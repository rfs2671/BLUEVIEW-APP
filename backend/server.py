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
    company_name: Optional[str] = None
    phone: Optional[str] = None
    trade: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_name: Optional[str] = None
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

class WorkerResponse(BaseModel):
    id: str
    name: str
    phone: str
    trade: str
    company: str
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
class DailyLogCreate(BaseModel):
    project_id: str
    date: str
    weather: Optional[str] = None
    notes: Optional[str] = None
    worker_count: int = 0

class DailyLogResponse(BaseModel):
    id: str
    project_id: str
    date: str
    weather: Optional[str] = None
    notes: Optional[str] = None
    worker_count: int = 0
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
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
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return serialize_id(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_admin_user(current_user = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(credentials.password, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(str(user["_id"]), user["email"], user.get("role", "worker"))
    return TokenResponse(token=token)

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
    
    result = await db.users.insert_one(user_dict)
    user_dict["id"] = str(result.inserted_id)
    del user_dict["password"]
    
    return UserResponse(**user_dict)

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user = Depends(get_current_user)):
    user = dict(current_user)
    if "password" in user:
        del user["password"]
    return UserResponse(**user)

# ==================== ADMIN USER MANAGEMENT ====================

@api_router.get("/admin/users", response_model=List[UserResponse])
async def get_admin_users(current_user = Depends(get_current_user)):
    users = await db.users.find({}, {"password": 0}).to_list(1000)
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
    subs = await db.subcontractors.find({}, {"password": 0}).to_list(1000)
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

# ==================== PROJECTS ====================

@api_router.get("/projects", response_model=List[ProjectResponse])
async def get_projects(current_user = Depends(get_current_user)):
    projects = await db.projects.find({}).to_list(1000)
    return [ProjectResponse(**serialize_id(p)) for p in projects]

@api_router.post("/projects", response_model=ProjectResponse)
async def create_project(project_data: ProjectCreate, admin = Depends(get_admin_user)):
    project_dict = project_data.model_dump()
    project_dict["created_at"] = datetime.now(timezone.utc)
    project_dict["nfc_tags"] = []
    project_dict["dropbox_enabled"] = False
    project_dict["dropbox_folder"] = None
    
    result = await db.projects.insert_one(project_dict)
    project_dict["id"] = str(result.inserted_id)
    
    return ProjectResponse(**project_dict)

@api_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, current_user = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
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
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if tag already exists
    existing_tag = await db.nfc_tags.find_one({"tag_id": tag_data.tag_id})
    if existing_tag:
        raise HTTPException(status_code=400, detail="NFC tag already registered to another project")
    
    nfc_tag = {
        "tag_id": tag_data.tag_id,
        "project_id": project_id,
        "project_name": project.get("name"),
        "location_description": tag_data.location_description,
        "status": "active",
        "created_at": datetime.now(timezone.utc)
    }
    
    # Store in nfc_tags collection
    await db.nfc_tags.insert_one(nfc_tag)
    
    # Also update project's nfc_tags array
    await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$push": {"nfc_tags": {"tag_id": tag_data.tag_id, "location": tag_data.location_description}}}
    )
    
    return {"message": "NFC tag registered successfully", "tag_id": tag_data.tag_id}

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
    
    return NfcTagInfo(
        tag_id=tag["tag_id"],
        project_id=tag["project_id"],
        project_name=tag.get("project_name", "Unknown Project"),
        location_description=tag.get("location_description", "Check-In Point"),
        company_name=tag.get("company_name")
    )

# ==================== WORKERS ====================

@api_router.get("/workers", response_model=List[WorkerResponse])
async def get_workers(current_user = Depends(get_current_user)):
    workers = await db.workers.find({}).to_list(1000)
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
    logs = await db.daily_logs.find({}).to_list(1000)
    return serialize_list(logs)

@api_router.post("/daily-logs", response_model=DailyLogResponse)
async def create_daily_log(log_data: DailyLogCreate, current_user = Depends(get_current_user)):
    log_dict = log_data.model_dump()
    log_dict["created_at"] = datetime.now(timezone.utc)
    log_dict["created_by"] = current_user.get("id")
    
    result = await db.daily_logs.insert_one(log_dict)
    log_dict["id"] = str(result.inserted_id)
    
    return DailyLogResponse(**log_dict)

@api_router.get("/daily-logs/{log_id}", response_model=DailyLogResponse)
async def get_daily_log(log_id: str, current_user = Depends(get_current_user)):
    log = await db.daily_logs.find_one({"_id": ObjectId(log_id)})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    return DailyLogResponse(**serialize_id(log))

@api_router.get("/daily-logs/project/{project_id}")
async def get_project_daily_logs(project_id: str, current_user = Depends(get_current_user)):
    logs = await db.daily_logs.find({"project_id": project_id}).to_list(1000)
    return serialize_list(logs)

# ==================== REPORTS ====================

@api_router.get("/reports")
async def get_reports(current_user = Depends(get_current_user)):
    reports = await db.reports.find({}).to_list(1000)
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
            "email": dropbox_config.get("email"),
            "connected_at": dropbox_config.get("connected_at")
        }
    return {"connected": False, "connected_at": None}

@api_router.get("/dropbox/auth-url")
async def get_dropbox_auth_url(current_user = Depends(get_current_user)):
    app_key = os.environ.get("DROPBOX_APP_KEY", "37ueec2e4se8gbg")
    redirect_uri = os.environ.get("DROPBOX_REDIRECT_URI", "https://blueview.app/dropbox/callback")
    
    authorize_url = f"https://www.dropbox.com/oauth2/authorize?response_type=code&client_id={app_key}&token_access_type=offline"
    
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
    
    if not project.get("dropbox_enabled"):
        return {"files": [], "message": "Dropbox not enabled for this project"}
    
    # In real implementation, would fetch from Dropbox API
    # For now, return stored files
    files = await db.dropbox_files.find({"project_id": project_id}).to_list(1000)
    return {"files": serialize_list(files)}

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

# ==================== STATS / DASHBOARD ====================

@api_router.get("/stats/dashboard")
async def get_dashboard_stats(current_user = Depends(get_current_user)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    total_workers = await db.workers.count_documents({})
    total_projects = await db.projects.count_documents({"status": "active"})
    on_site_now = await db.checkins.count_documents({"status": "checked_in"})
    today_checkins = await db.checkins.count_documents({"check_in_time": {"$gte": today_start}})
    
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
    allow_origins=["*"],
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
    await db.workers.create_index("phone", unique=True)
    await db.nfc_tags.create_index("tag_id", unique=True)
    await db.subcontractors.create_index("email", unique=True)
    
    # Check if admin user exists, if not create default
    admin = await db.users.find_one({"email": "rfs2671@gmail.com"})
    if not admin:
        await db.users.insert_one({
            "email": "rfs2671@gmail.com",
            "password": hash_password("Asdddfgh1$"),
            "name": "Roy Fishman",
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
            "assigned_projects": []
        })
        logger.info("Created default admin user")
    
    logger.info("Blueview API started successfully")
