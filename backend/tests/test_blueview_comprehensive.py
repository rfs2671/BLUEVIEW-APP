"""
Comprehensive Backend API Tests for Blueview Construction Management App
Tests: Auth, Dashboard Stats, Admin Users CRUD, Admin Subcontractors CRUD, 
       Projects CRUD, Workers, Check-ins, NFC Tags, Daily Logs
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = "https://docshare-31.preview.emergentagent.com"

# Test credentials
TEST_EMAIL = "rfs2671@gmail.com"
TEST_PASSWORD = "Asdddfgh1$"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for all tests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get auth headers for all tests"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestHealthAndRoot:
    """Health check and root endpoint tests"""
    
    def test_health_check(self):
        """Test /api/health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"Health check passed: {data}")
    
    def test_root_endpoint(self):
        """Test /api/ root endpoint"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "Blueview" in data["message"]
        print(f"Root endpoint: {data}")


class TestAuthentication:
    """Authentication endpoint tests"""
    
    def test_login_success(self):
        """Test login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token_type"] == "bearer"
        print(f"Login successful, token received")
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })
        assert response.status_code == 401
        print("Invalid credentials correctly rejected")
    
    def test_get_me_with_token(self, auth_headers):
        """Test /api/auth/me endpoint with valid token"""
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_EMAIL
        assert data["role"] == "admin"
        assert "id" in data
        print(f"Auth/me successful: {data['name']} ({data['role']})")
    
    def test_get_me_without_token(self):
        """Test /api/auth/me without token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestDashboardStats:
    """Dashboard statistics endpoint tests"""
    
    def test_get_dashboard_stats(self, auth_headers):
        """Test GET /api/stats/dashboard - returns real stats"""
        response = requests.get(f"{BASE_URL}/api/stats/dashboard", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields exist
        assert "total_workers" in data
        assert "total_projects" in data
        assert "on_site_now" in data
        assert "today_checkins" in data
        
        # Verify data types
        assert isinstance(data["total_workers"], int)
        assert isinstance(data["total_projects"], int)
        assert isinstance(data["on_site_now"], int)
        assert isinstance(data["today_checkins"], int)
        
        print(f"Dashboard stats: Workers={data['total_workers']}, Projects={data['total_projects']}, OnSite={data['on_site_now']}, TodayCheckins={data['today_checkins']}")


class TestAdminUsers:
    """Admin User Management API tests"""
    
    def test_get_all_users(self, auth_headers):
        """Test GET /api/admin/users - returns list of users"""
        response = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} users")
        
        # Verify data structure
        if len(data) > 0:
            user = data[0]
            assert "id" in user
            assert "email" in user
            assert "name" in user
            assert "role" in user
            print(f"User structure verified: {user['name']} ({user['role']})")
    
    def test_create_user(self, auth_headers):
        """Test POST /api/admin/users - create new user"""
        test_user = {
            "email": f"TEST_user_{datetime.now().timestamp()}@test.com",
            "password": "TestPass123!",
            "name": "TEST User",
            "role": "worker"
        }
        response = requests.post(f"{BASE_URL}/api/admin/users", json=test_user, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user["email"]
        assert data["name"] == test_user["name"]
        assert data["role"] == test_user["role"]
        assert "id" in data
        print(f"Created user: {data['name']} (ID: {data['id']})")
        
        # Cleanup - delete the test user
        delete_response = requests.delete(f"{BASE_URL}/api/admin/users/{data['id']}", headers=auth_headers)
        assert delete_response.status_code == 200
        print(f"Cleaned up test user")
    
    def test_get_all_users_unauthorized(self):
        """Test GET /api/admin/users without token"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestAdminSubcontractors:
    """Admin Subcontractors API tests"""
    
    def test_get_all_subcontractors(self, auth_headers):
        """Test GET /api/admin/subcontractors - returns list of subcontractors"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} subcontractors")
        
        # Verify data structure
        if len(data) > 0:
            sub = data[0]
            assert "id" in sub
            assert "email" in sub
            assert "company_name" in sub
            assert "contact_name" in sub
            print(f"Subcontractor structure verified: {sub['company_name']}")
    
    def test_create_subcontractor(self, auth_headers):
        """Test POST /api/admin/subcontractors - create new subcontractor"""
        test_sub = {
            "company_name": f"TEST Company {datetime.now().timestamp()}",
            "contact_name": "TEST Contact",
            "email": f"TEST_sub_{datetime.now().timestamp()}@test.com",
            "phone": "555-0123",
            "trade": "Electrical",
            "password": "TestPass123!"
        }
        response = requests.post(f"{BASE_URL}/api/admin/subcontractors", json=test_sub, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["company_name"] == test_sub["company_name"]
        assert data["contact_name"] == test_sub["contact_name"]
        assert "id" in data
        print(f"Created subcontractor: {data['company_name']} (ID: {data['id']})")
        
        # Cleanup - delete the test subcontractor
        delete_response = requests.delete(f"{BASE_URL}/api/admin/subcontractors/{data['id']}", headers=auth_headers)
        assert delete_response.status_code == 200
        print(f"Cleaned up test subcontractor")
    
    def test_get_all_subcontractors_unauthorized(self):
        """Test GET /api/admin/subcontractors without token"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestProjects:
    """Projects API tests"""
    
    def test_get_all_projects(self, auth_headers):
        """Test GET /api/projects - returns list of projects"""
        response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} projects")
        
        # Verify data structure
        if len(data) > 0:
            project = data[0]
            assert "id" in project
            assert "name" in project
            assert "status" in project
            print(f"Project structure verified: {project['name']} ({project['status']})")
    
    def test_create_and_delete_project(self, auth_headers):
        """Test POST /api/projects - create new project and DELETE"""
        test_project = {
            "name": f"TEST Project {datetime.now().timestamp()}",
            "location": "Test Location",
            "address": "123 Test St",
            "status": "active"
        }
        response = requests.post(f"{BASE_URL}/api/projects", json=test_project, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_project["name"]
        assert "id" in data
        project_id = data["id"]
        print(f"Created project: {data['name']} (ID: {project_id})")
        
        # Verify GET by ID
        get_response = requests.get(f"{BASE_URL}/api/projects/{project_id}", headers=auth_headers)
        assert get_response.status_code == 200
        assert get_response.json()["name"] == test_project["name"]
        print(f"Verified project retrieval by ID")
        
        # Cleanup - delete the test project
        delete_response = requests.delete(f"{BASE_URL}/api/projects/{project_id}", headers=auth_headers)
        assert delete_response.status_code == 200
        print(f"Cleaned up test project")


class TestWorkers:
    """Workers API tests"""
    
    def test_get_all_workers(self, auth_headers):
        """Test GET /api/workers - returns list of workers"""
        response = requests.get(f"{BASE_URL}/api/workers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} workers")
        
        # Verify data structure
        if len(data) > 0:
            worker = data[0]
            assert "id" in worker
            assert "name" in worker
            assert "phone" in worker
            assert "trade" in worker
            print(f"Worker structure verified: {worker['name']} ({worker['trade']})")
    
    def test_register_worker(self):
        """Test POST /api/workers/register - public endpoint for worker registration"""
        test_worker = {
            "name": f"TEST Worker {datetime.now().timestamp()}",
            "phone": f"555-{int(datetime.now().timestamp()) % 10000:04d}",
            "trade": "Electrician",
            "company": "TEST Company"
        }
        response = requests.post(f"{BASE_URL}/api/workers/register", json=test_worker)
        assert response.status_code == 200
        data = response.json()
        assert "worker_id" in data
        assert "message" in data
        print(f"Registered worker: {data['worker_id']}")


class TestNFCTags:
    """NFC Tag API tests"""
    
    def test_get_tag_info_existing(self):
        """Test GET /api/nfc-tags/BLUEVIEW-TAG-001/info - existing tag"""
        response = requests.get(f"{BASE_URL}/api/nfc-tags/BLUEVIEW-TAG-001/info")
        assert response.status_code == 200
        data = response.json()
        assert "tag_id" in data
        assert "project_id" in data
        assert "project_name" in data
        assert "location_description" in data
        print(f"NFC Tag info: {data['tag_id']} -> {data['project_name']}")
    
    def test_get_tag_info_not_found(self):
        """Test GET /api/nfc-tags/{tag_id}/info - tag not found"""
        response = requests.get(f"{BASE_URL}/api/nfc-tags/NONEXISTENT-TAG/info")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        print(f"Tag not found error: {data['detail']}")


class TestCheckIns:
    """Check-in API tests"""
    
    def test_checkin_with_project_and_worker(self, auth_headers):
        """Test POST /api/checkin - check in a worker"""
        # First get a worker and project
        workers_response = requests.get(f"{BASE_URL}/api/workers", headers=auth_headers)
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        
        workers = workers_response.json()
        projects = projects_response.json()
        
        if len(workers) > 0 and len(projects) > 0:
            worker_id = workers[0]["id"]
            project_id = projects[0]["id"]
            
            checkin_data = {
                "worker_id": worker_id,
                "project_id": project_id
            }
            response = requests.post(f"{BASE_URL}/api/checkin", json=checkin_data)
            assert response.status_code == 200
            data = response.json()
            assert "id" in data
            assert "worker_name" in data
            assert "project_name" in data
            assert "message" in data
            print(f"Check-in successful: {data['worker_name']} at {data['project_name']}")
        else:
            pytest.skip("No workers or projects available for check-in test")
    
    def test_get_project_checkins(self, auth_headers):
        """Test GET /api/checkins/project/{project_id} - get project check-ins"""
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        projects = projects_response.json()
        
        if len(projects) > 0:
            project_id = projects[0]["id"]
            response = requests.get(f"{BASE_URL}/api/checkins/project/{project_id}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            print(f"Found {len(data)} check-ins for project")
        else:
            pytest.skip("No projects available for check-in test")


class TestDailyLogs:
    """Daily Logs API tests"""
    
    def test_get_all_daily_logs(self, auth_headers):
        """Test GET /api/daily-logs - returns list of daily logs"""
        response = requests.get(f"{BASE_URL}/api/daily-logs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} daily logs")
    
    def test_create_daily_log(self, auth_headers):
        """Test POST /api/daily-logs - create new daily log"""
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        projects = projects_response.json()
        
        if len(projects) > 0:
            project_id = projects[0]["id"]
            test_log = {
                "project_id": project_id,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "weather": "Sunny",
                "notes": "TEST daily log entry",
                "worker_count": 5
            }
            response = requests.post(f"{BASE_URL}/api/daily-logs", json=test_log, headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["project_id"] == project_id
            assert "id" in data
            print(f"Created daily log: {data['id']}")
        else:
            pytest.skip("No projects available for daily log test")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
