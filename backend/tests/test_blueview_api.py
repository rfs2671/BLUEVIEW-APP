"""
Blueview API Backend Tests
Tests for authentication, projects, daily logs, workers, and dropbox integration
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "rfs2671@gmail.com"
ADMIN_PASSWORD = "Asdddfgh1$"
SITE_DEVICE_USERNAME = "site-downtown-1"
SITE_DEVICE_PASSWORD = "password"


class TestHealthCheck:
    """Health check endpoint tests"""
    
    def test_health_endpoint(self):
        """Test health endpoint returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        print(f"✓ Health check passed: {data}")

    def test_root_endpoint(self):
        """Test root API endpoint"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "status" in data
        print(f"✓ Root endpoint passed: {data}")


class TestAuthentication:
    """Authentication endpoint tests"""
    
    def test_admin_login_success(self):
        """Test admin login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token_type"] == "bearer"
        print(f"✓ Admin login successful")
        return data["token"]
    
    def test_admin_login_invalid_credentials(self):
        """Test admin login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        print(f"✓ Invalid credentials rejected correctly")
    
    def test_site_device_login_success(self):
        """Test site device login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": SITE_DEVICE_USERNAME,
            "password": SITE_DEVICE_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token_type"] == "bearer"
        print(f"✓ Site device login successful")
        return data["token"]
    
    def test_get_current_user_admin(self):
        """Test getting current user info for admin"""
        # First login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        token = login_response.json()["token"]
        
        # Get user info
        response = requests.get(f"{BASE_URL}/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == ADMIN_EMAIL
        assert data["role"] == "admin"
        print(f"✓ Admin user info retrieved: {data['email']}")
    
    def test_get_current_user_site_device(self):
        """Test getting current user info for site device"""
        # First login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": SITE_DEVICE_USERNAME,
            "password": SITE_DEVICE_PASSWORD
        })
        token = login_response.json()["token"]
        
        # Get user info
        response = requests.get(f"{BASE_URL}/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["site_mode"] == True
        assert data["role"] == "site_device"
        print(f"✓ Site device user info retrieved: {data}")


class TestProjects:
    """Project management endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_projects(self, admin_token):
        """Test getting all projects"""
        response = requests.get(f"{BASE_URL}/api/projects", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} projects")
        return data
    
    def test_get_project_by_id(self, admin_token):
        """Test getting a specific project"""
        # First get all projects
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        projects = projects_response.json()
        
        if len(projects) > 0:
            project_id = projects[0]["id"]
            response = requests.get(f"{BASE_URL}/api/projects/{project_id}", headers={
                "Authorization": f"Bearer {admin_token}"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == project_id
            print(f"✓ Retrieved project: {data['name']}")
        else:
            pytest.skip("No projects available to test")


class TestDailyLogs:
    """Daily log endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    @pytest.fixture
    def project_id(self, admin_token):
        """Get a project ID for testing"""
        response = requests.get(f"{BASE_URL}/api/projects", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        projects = response.json()
        if len(projects) > 0:
            return projects[0]["id"]
        pytest.skip("No projects available")
    
    def test_get_daily_logs(self, admin_token):
        """Test getting all daily logs"""
        response = requests.get(f"{BASE_URL}/api/daily-logs", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} daily logs")
    
    def test_get_project_daily_logs(self, admin_token, project_id):
        """Test getting daily logs for a specific project"""
        response = requests.get(f"{BASE_URL}/api/daily-logs/project/{project_id}", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} daily logs for project")
    
    def test_create_daily_log(self, admin_token, project_id):
        """Test creating a new daily log"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_data = {
            "project_id": project_id,
            "date": today,
            "weather": "sunny",
            "notes": "TEST_Daily log test notes",
            "worker_count": 10,
            "subcontractor_cards": [],
            "safety_checklist": {
                "fall_protection": {"status": "checked", "checked_by": "Test User", "checked_at": datetime.now().isoformat()},
                "scaffolding": {"status": "checked", "checked_by": "Test User", "checked_at": datetime.now().isoformat()},
                "ppe": {"status": "na", "checked_by": "Test User", "checked_at": datetime.now().isoformat()}
            },
            "corrective_actions": "",
            "corrective_actions_na": True,
            "incident_log": "",
            "incident_log_na": True
        }
        
        response = requests.post(f"{BASE_URL}/api/daily-logs", 
            headers={"Authorization": f"Bearer {admin_token}"},
            json=log_data
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == project_id
        assert data["weather"] == "sunny"
        assert data["worker_count"] == 10
        print(f"✓ Created daily log: {data['id']}")
        return data["id"]
    
    def test_update_daily_log(self, admin_token, project_id):
        """Test updating an existing daily log"""
        # First create a log
        today = datetime.now().strftime("%Y-%m-%d")
        create_data = {
            "project_id": project_id,
            "date": today,
            "weather": "cloudy",
            "notes": "TEST_Initial notes",
            "worker_count": 5
        }
        
        create_response = requests.post(f"{BASE_URL}/api/daily-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=create_data
        )
        
        if create_response.status_code == 200:
            log_id = create_response.json()["id"]
            
            # Update the log
            update_data = {
                "weather": "rainy",
                "notes": "TEST_Updated notes",
                "worker_count": 15
            }
            
            update_response = requests.put(f"{BASE_URL}/api/daily-logs/{log_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=update_data
            )
            assert update_response.status_code == 200
            updated_data = update_response.json()
            assert updated_data["weather"] == "rainy"
            assert updated_data["worker_count"] == 15
            print(f"✓ Updated daily log: {log_id}")
        else:
            # Log might already exist for today, try to get and update it
            logs_response = requests.get(f"{BASE_URL}/api/daily-logs/project/{project_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            logs = logs_response.json()
            if len(logs) > 0:
                log_id = logs[0]["id"]
                update_data = {"notes": "TEST_Updated via existing log"}
                update_response = requests.put(f"{BASE_URL}/api/daily-logs/{log_id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json=update_data
                )
                assert update_response.status_code == 200
                print(f"✓ Updated existing daily log: {log_id}")


class TestWorkers:
    """Worker management endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_workers(self, admin_token):
        """Test getting all workers"""
        response = requests.get(f"{BASE_URL}/api/workers", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} workers")
    
    def test_register_worker(self):
        """Test worker self-registration (public endpoint)"""
        worker_data = {
            "name": "TEST_Worker",
            "phone": f"555-{datetime.now().strftime('%H%M%S')}",
            "company": "Test Company",
            "trade": "Electrician"
        }
        
        response = requests.post(f"{BASE_URL}/api/workers/register", json=worker_data)
        assert response.status_code == 200
        data = response.json()
        assert "worker_id" in data
        print(f"✓ Registered worker: {data['worker_id']}")


class TestDropboxIntegration:
    """Dropbox integration endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_dropbox_status(self, admin_token):
        """Test getting Dropbox connection status"""
        response = requests.get(f"{BASE_URL}/api/dropbox/status", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert "connected" in data
        print(f"✓ Dropbox status: connected={data['connected']}")
    
    def test_get_dropbox_auth_url(self, admin_token):
        """Test getting Dropbox authorization URL"""
        response = requests.get(f"{BASE_URL}/api/dropbox/auth-url", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert "authorize_url" in data
        assert "dropbox.com" in data["authorize_url"]
        print(f"✓ Dropbox auth URL generated")


class TestDashboardStats:
    """Dashboard statistics endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_dashboard_stats(self, admin_token):
        """Test getting dashboard statistics"""
        response = requests.get(f"{BASE_URL}/api/stats/dashboard", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert "total_workers" in data
        assert "total_projects" in data
        assert "on_site_now" in data
        assert "today_checkins" in data
        print(f"✓ Dashboard stats: {data}")


class TestSiteDevices:
    """Site device management endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_site_devices(self, admin_token):
        """Test getting all site devices"""
        response = requests.get(f"{BASE_URL}/api/admin/site-devices", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} site devices")


class TestNFCTags:
    """NFC tag management endpoint tests"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    @pytest.fixture
    def project_id(self, admin_token):
        """Get a project ID for testing"""
        response = requests.get(f"{BASE_URL}/api/projects", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        projects = response.json()
        if len(projects) > 0:
            return projects[0]["id"]
        pytest.skip("No projects available")
    
    def test_get_project_nfc_tags(self, admin_token, project_id):
        """Test getting NFC tags for a project"""
        response = requests.get(f"{BASE_URL}/api/projects/{project_id}/nfc-tags", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Retrieved {len(data)} NFC tags for project")
    
    def test_get_nfc_tag_info_public(self):
        """Test getting NFC tag info (public endpoint)"""
        # Try with a known tag ID
        response = requests.get(f"{BASE_URL}/api/nfc-tags/BLUEVIEW-TAG-001/info")
        # Could be 200 or 404 depending on if tag exists
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "tag_id" in data
            assert "project_name" in data
            print(f"✓ NFC tag info retrieved: {data['project_name']}")
        else:
            print(f"✓ NFC tag not found (expected for non-existent tag)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
