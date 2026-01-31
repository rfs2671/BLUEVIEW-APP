"""
Comprehensive Backend API Tests for Blueview
Tests: Auth, Projects, NFC Tags, Admin Users, Admin Subcontractors, Dropbox
"""
import pytest
import requests
import os
import uuid

BASE_URL = "https://projnfc.preview.emergentagent.com"

# Test credentials
TEST_EMAIL = "rfs2671@gmail.com"
TEST_PASSWORD = "Asdddfgh1$"
TEST_PROJECT_ID = "697e6d9195a7b27a02d2bb72"


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
    return {"Authorization": f"Bearer {auth_token}"}


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
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0
        print(f"Login successful, token received")
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })
        assert response.status_code == 401
        print("Invalid credentials correctly rejected")
    
    def test_login_missing_fields(self):
        """Test login with missing fields"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL
        })
        assert response.status_code == 422  # Validation error
        print("Missing fields correctly rejected")
    
    def test_get_me_with_token(self, auth_headers):
        """Test /api/auth/me endpoint with valid token"""
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_EMAIL
        assert data["role"] == "admin"
        assert "name" in data
        print(f"Auth/me successful: {data['name']} ({data['role']})")
    
    def test_get_me_without_token(self):
        """Test /api/auth/me without token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestProjects:
    """Projects API tests"""
    
    def test_get_all_projects(self, auth_headers):
        """Test GET /api/projects"""
        response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} projects")
        
        if len(data) > 0:
            project = data[0]
            assert "id" in project
            assert "name" in project
            print(f"First project: {project['name']}")
    
    def test_get_project_by_id(self, auth_headers):
        """Test GET /api/projects/{id}"""
        response = requests.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_ID}", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            assert "name" in data
            print(f"Project found: {data['name']}")
        else:
            # Project may not exist, which is acceptable
            assert response.status_code == 404
            print("Test project not found (expected if not seeded)")
    
    def test_get_projects_unauthorized(self):
        """Test GET /api/projects without token"""
        response = requests.get(f"{BASE_URL}/api/projects")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestNFCTags:
    """NFC Tags API tests"""
    
    def test_get_nfc_tag_info_not_found(self):
        """Test GET /api/nfc-tags/{tag_id}/info for non-existent tag"""
        response = requests.get(f"{BASE_URL}/api/nfc-tags/NONEXISTENT123/info")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        print(f"Non-existent tag correctly returns 404: {data['detail']}")
    
    def test_get_project_nfc_tags(self, auth_headers):
        """Test GET /api/projects/{id}/nfc-tags"""
        response = requests.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_ID}/nfc-tags", headers=auth_headers)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            print(f"Found {len(data)} NFC tags for project")
        else:
            assert response.status_code == 404
            print("Test project not found")
    
    def test_add_and_delete_nfc_tag(self, auth_headers):
        """Test POST and DELETE /api/projects/{id}/nfc-tags"""
        # First, get or create a project
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers=auth_headers)
        projects = projects_response.json()
        
        if len(projects) == 0:
            print("No projects available, skipping NFC tag test")
            pytest.skip("No projects available")
        
        project_id = projects[0]["id"]
        test_tag_id = f"TEST_TAG_{uuid.uuid4().hex[:8]}"
        
        # Add NFC tag
        add_response = requests.post(
            f"{BASE_URL}/api/projects/{project_id}/nfc-tags",
            headers=auth_headers,
            json={
                "tag_id": test_tag_id,
                "location_description": "Test Location"
            }
        )
        
        if add_response.status_code == 200:
            print(f"NFC tag added: {test_tag_id}")
            
            # Verify tag was added
            tags_response = requests.get(f"{BASE_URL}/api/projects/{project_id}/nfc-tags", headers=auth_headers)
            tags = tags_response.json()
            tag_ids = [t.get("tag_id") for t in tags]
            assert test_tag_id in tag_ids, "Tag should be in project tags"
            
            # Delete the tag
            delete_response = requests.delete(
                f"{BASE_URL}/api/projects/{project_id}/nfc-tags/{test_tag_id}",
                headers=auth_headers
            )
            assert delete_response.status_code == 200
            print(f"NFC tag deleted: {test_tag_id}")
        else:
            print(f"Add NFC tag response: {add_response.status_code} - {add_response.text}")


class TestAdminUsers:
    """Admin User Management API tests"""
    
    def test_get_all_users(self, auth_headers):
        """Test GET /api/admin/users"""
        response = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} users")
        
        if len(data) > 0:
            user = data[0]
            assert "id" in user
            assert "email" in user
            assert "name" in user
            assert "role" in user
            print(f"User structure verified: {user['name']} ({user['role']})")
    
    def test_get_all_users_unauthorized(self):
        """Test GET /api/admin/users without token"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")
    
    def test_create_update_delete_user(self, auth_headers):
        """Test full CRUD for admin users"""
        test_email = f"TEST_user_{uuid.uuid4().hex[:8]}@test.com"
        
        # CREATE
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            headers=auth_headers,
            json={
                "email": test_email,
                "password": "TestPass123!",
                "name": "Test User",
                "role": "worker"
            }
        )
        assert create_response.status_code in [200, 201], f"Create failed: {create_response.text}"
        created_user = create_response.json()
        user_id = created_user["id"]
        print(f"Created user: {created_user['name']} (ID: {user_id})")
        
        # READ
        get_response = requests.get(f"{BASE_URL}/api/admin/users/{user_id}", headers=auth_headers)
        assert get_response.status_code == 200
        fetched_user = get_response.json()
        assert fetched_user["email"] == test_email
        print(f"Fetched user: {fetched_user['name']}")
        
        # UPDATE
        update_response = requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers=auth_headers,
            json={"name": "Updated Test User"}
        )
        assert update_response.status_code == 200
        updated_user = update_response.json()
        assert updated_user["name"] == "Updated Test User"
        print(f"Updated user: {updated_user['name']}")
        
        # DELETE
        delete_response = requests.delete(f"{BASE_URL}/api/admin/users/{user_id}", headers=auth_headers)
        assert delete_response.status_code == 200
        print(f"Deleted user: {user_id}")
        
        # Verify deletion
        verify_response = requests.get(f"{BASE_URL}/api/admin/users/{user_id}", headers=auth_headers)
        assert verify_response.status_code == 404
        print("User deletion verified")


class TestAdminSubcontractors:
    """Admin Subcontractors API tests"""
    
    def test_get_all_subcontractors(self, auth_headers):
        """Test GET /api/admin/subcontractors"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} subcontractors")
        
        if len(data) > 0:
            sub = data[0]
            assert "id" in sub
            assert "company_name" in sub
            assert "contact_name" in sub
            assert "email" in sub
            print(f"Subcontractor: {sub['company_name']}")
    
    def test_get_all_subcontractors_unauthorized(self):
        """Test GET /api/admin/subcontractors without token"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")
    
    def test_create_update_delete_subcontractor(self, auth_headers):
        """Test full CRUD for subcontractors"""
        test_email = f"TEST_sub_{uuid.uuid4().hex[:8]}@test.com"
        
        # CREATE
        create_response = requests.post(
            f"{BASE_URL}/api/admin/subcontractors",
            headers=auth_headers,
            json={
                "company_name": "Test Subcontractor Inc",
                "contact_name": "Test Contact",
                "email": test_email,
                "phone": "555-0123",
                "trade": "Electrical",
                "password": "TestPass123!"
            }
        )
        assert create_response.status_code in [200, 201], f"Create failed: {create_response.text}"
        created_sub = create_response.json()
        sub_id = created_sub["id"]
        print(f"Created subcontractor: {created_sub['company_name']} (ID: {sub_id})")
        
        # READ
        get_response = requests.get(f"{BASE_URL}/api/admin/subcontractors/{sub_id}", headers=auth_headers)
        assert get_response.status_code == 200
        fetched_sub = get_response.json()
        assert fetched_sub["email"] == test_email
        print(f"Fetched subcontractor: {fetched_sub['company_name']}")
        
        # UPDATE
        update_response = requests.put(
            f"{BASE_URL}/api/admin/subcontractors/{sub_id}",
            headers=auth_headers,
            json={"company_name": "Updated Test Subcontractor"}
        )
        assert update_response.status_code == 200
        updated_sub = update_response.json()
        assert updated_sub["company_name"] == "Updated Test Subcontractor"
        print(f"Updated subcontractor: {updated_sub['company_name']}")
        
        # DELETE
        delete_response = requests.delete(f"{BASE_URL}/api/admin/subcontractors/{sub_id}", headers=auth_headers)
        assert delete_response.status_code == 200
        print(f"Deleted subcontractor: {sub_id}")
        
        # Verify deletion
        verify_response = requests.get(f"{BASE_URL}/api/admin/subcontractors/{sub_id}", headers=auth_headers)
        assert verify_response.status_code == 404
        print("Subcontractor deletion verified")


class TestDropboxIntegration:
    """Dropbox Integration API tests"""
    
    def test_get_dropbox_status(self, auth_headers):
        """Test GET /api/dropbox/status"""
        response = requests.get(f"{BASE_URL}/api/dropbox/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "connected" in data
        print(f"Dropbox status: connected={data['connected']}")
    
    def test_get_dropbox_auth_url(self, auth_headers):
        """Test GET /api/dropbox/auth-url"""
        response = requests.get(f"{BASE_URL}/api/dropbox/auth-url", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "authorize_url" in data
        assert "dropbox.com" in data["authorize_url"]
        print(f"Dropbox auth URL received: {data['authorize_url'][:50]}...")
    
    def test_dropbox_status_unauthorized(self):
        """Test GET /api/dropbox/status without token"""
        response = requests.get(f"{BASE_URL}/api/dropbox/status")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestDashboardStats:
    """Dashboard Stats API tests"""
    
    def test_get_dashboard_stats(self, auth_headers):
        """Test GET /api/stats/dashboard"""
        response = requests.get(f"{BASE_URL}/api/stats/dashboard", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_workers" in data
        assert "total_projects" in data
        assert "on_site_now" in data
        assert "today_checkins" in data
        print(f"Dashboard stats: workers={data['total_workers']}, projects={data['total_projects']}")
    
    def test_dashboard_stats_unauthorized(self):
        """Test GET /api/stats/dashboard without token"""
        response = requests.get(f"{BASE_URL}/api/stats/dashboard")
        assert response.status_code == 401
        print("Unauthorized access correctly rejected")


class TestWorkers:
    """Workers API tests"""
    
    def test_get_all_workers(self, auth_headers):
        """Test GET /api/workers"""
        response = requests.get(f"{BASE_URL}/api/workers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} workers")
    
    def test_register_worker_public(self):
        """Test POST /api/workers/register (public endpoint)"""
        test_phone = f"555-{uuid.uuid4().hex[:7]}"
        response = requests.post(f"{BASE_URL}/api/workers/register", json={
            "name": "Test Worker",
            "phone": test_phone,
            "trade": "Electrician",
            "company": "Test Company"
        })
        assert response.status_code == 200
        data = response.json()
        assert "worker_id" in data
        print(f"Worker registered: {data['worker_id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
