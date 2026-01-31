"""
Backend API Integration Tests for Blueview
Tests: Auth, Admin Users, Admin Subcontractors, NFC Tags
"""
import pytest
import requests
import os

BASE_URL = "https://blueview2-production.up.railway.app"

# Test credentials
TEST_EMAIL = "rfs2671@gmail.com"
TEST_PASSWORD = "Asdddfgh1$"


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
        assert "user" in data
        assert data["user"]["email"] == TEST_EMAIL
        assert data["user"]["role"] == "admin"
        print(f"Login successful: {data['user']['name']}")
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })
        assert response.status_code in [401, 400]
        print("Invalid credentials correctly rejected")
    
    def test_get_me_with_token(self):
        """Test /api/auth/me endpoint with valid token"""
        # First login to get token
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        token = login_response.json()["token"]
        
        # Get user info
        response = requests.get(f"{BASE_URL}/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_EMAIL
        print(f"Auth/me successful: {data['name']}")


class TestAdminUsers:
    """Admin User Management API tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_all_users(self, auth_token):
        """Test GET /api/admin/users - returns list of users"""
        response = requests.get(f"{BASE_URL}/api/admin/users", headers={
            "Authorization": f"Bearer {auth_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} users")
        
        # Verify data structure
        if len(data) > 0:
            user = data[0]
            assert "id" in user or "_id" in user
            assert "email" in user
            assert "name" in user
            assert "role" in user
            print(f"User structure verified: {user['name']} ({user['role']})")
    
    def test_get_all_users_unauthorized(self):
        """Test GET /api/admin/users without token"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code in [401, 403]
        print("Unauthorized access correctly rejected")


class TestAdminSubcontractors:
    """Admin Subcontractors API tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_all_subcontractors(self, auth_token):
        """Test GET /api/admin/subcontractors - returns list of subcontractors"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors", headers={
            "Authorization": f"Bearer {auth_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} subcontractors")
        
        # Verify data structure
        if len(data) > 0:
            sub = data[0]
            assert "id" in sub or "_id" in sub
            assert "email" in sub
            assert "company_name" in sub
            assert "contact_name" in sub
            print(f"Subcontractor structure verified: {sub['company_name']}")
    
    def test_get_all_subcontractors_unauthorized(self):
        """Test GET /api/admin/subcontractors without token"""
        response = requests.get(f"{BASE_URL}/api/admin/subcontractors")
        assert response.status_code in [401, 403]
        print("Unauthorized access correctly rejected")


class TestNFCTags:
    """NFC Tag API tests"""
    
    def test_get_tag_info_not_found(self):
        """Test GET /api/nfc-tags/{tag_id}/info - tag not found"""
        response = requests.get(f"{BASE_URL}/api/nfc-tags/TEST123/info")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower() or "inactive" in data["detail"].lower()
        print(f"Tag not found error: {data['detail']}")
    
    def test_get_tag_info_invalid_tag(self):
        """Test GET /api/nfc-tags/{tag_id}/info - invalid tag format"""
        response = requests.get(f"{BASE_URL}/api/nfc-tags/INVALID_TAG_12345/info")
        assert response.status_code in [404, 400]
        print("Invalid tag correctly handled")


class TestProjects:
    """Projects API tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_all_projects(self, auth_token):
        """Test GET /api/projects - returns list of projects"""
        response = requests.get(f"{BASE_URL}/api/projects", headers={
            "Authorization": f"Bearer {auth_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} projects")


class TestWorkers:
    """Workers API tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        return response.json()["token"]
    
    def test_get_all_workers(self, auth_token):
        """Test GET /api/workers - returns list of workers"""
        response = requests.get(f"{BASE_URL}/api/workers", headers={
            "Authorization": f"Bearer {auth_token}"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} workers")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
