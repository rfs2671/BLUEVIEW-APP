/**
 * Centralized API Utility for Blueview
 * Handles all API requests with JWT authentication
 */
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// API Base URL - uses the preview URL which proxies /api to backend
const API_BASE_URL = 'https://docshare-31.preview.emergentagent.com';

// Create axios instance
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Token management
export const getToken = async () => {
  try {
    return await AsyncStorage.getItem('blueview_token');
  } catch (e) {
    return null;
  }
};

export const setToken = async (token) => {
  try {
    await AsyncStorage.setItem('blueview_token', token);
  } catch (e) {
    console.error('Error saving token:', e);
  }
};

export const removeToken = async () => {
  try {
    await AsyncStorage.removeItem('blueview_token');
  } catch (e) {
    console.error('Error removing token:', e);
  }
};

// User data management
export const getStoredUser = async () => {
  try {
    const user = await AsyncStorage.getItem('blueview_user');
    return user ? JSON.parse(user) : null;
  } catch (e) {
    return null;
  }
};

export const setStoredUser = async (user) => {
  try {
    await AsyncStorage.setItem('blueview_user', JSON.stringify(user));
  } catch (e) {
    console.error('Error saving user:', e);
  }
};

export const removeStoredUser = async () => {
  try {
    await AsyncStorage.removeItem('blueview_user');
  } catch (e) {
    console.error('Error removing user:', e);
  }
};

// Clear all auth data
export const clearAuth = async () => {
  await removeToken();
  await removeStoredUser();
};

// Request interceptor to attach JWT
apiClient.interceptors.request.use(
  async (config) => {
    const token = await getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      await clearAuth();
      // Navigation will be handled by AuthContext
    }
    return Promise.reject(error);
  }
);

/**
 * Authentication APIs
 */
export const authAPI = {
  login: async (email, password) => {
    const response = await axios.post(`${API_BASE_URL}/api/auth/login`, {
      email,
      password,
    });
    
    // Store token (API returns 'token' not 'access_token')
    if (response.data.token) {
      await setToken(response.data.token);
    }
    
    return response.data;
  },

  getMe: async () => {
    const response = await apiClient.get('/api/auth/me');
    return response.data;
  },

  logout: async () => {
    await clearAuth();
  },
};

/**
 * Projects APIs
 */
export const projectsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/projects');
    return response.data;
  },

  getById: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}`);
    return response.data;
  },

  create: async (projectData) => {
    const response = await apiClient.post('/api/projects', projectData);
    return response.data;
  },

  update: async (projectId, projectData) => {
    const response = await apiClient.put(`/api/projects/${projectId}`, projectData);
    return response.data;
  },

  delete: async (projectId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}`);
    return response.data;
  },
};

/**
 * Workers APIs
 */
export const workersAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/workers');
    return response.data;
  },

  getById: async (workerId) => {
    const response = await apiClient.get(`/api/workers/${workerId}`);
    return response.data;
  },

  create: async (workerData) => {
    const response = await apiClient.post('/api/workers', workerData);
    return response.data;
  },
};

/**
 * Check-ins APIs
 */
export const checkinsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/checkins');
    return response.data;
  },

  getTodayByProject: async (projectId) => {
    const response = await apiClient.get(`/api/checkins/project/${projectId}/today`);
    return response.data;
  },

  getActiveByProject: async (projectId) => {
    const response = await apiClient.get(`/api/checkins/project/${projectId}/active`);
    return response.data;
  },

  checkIn: async (checkinData) => {
    const response = await apiClient.post('/api/checkins', checkinData);
    return response.data;
  },

  checkOut: async (checkinId) => {
    const response = await apiClient.post(`/api/checkins/${checkinId}/checkout`);
    return response.data;
  },
};

/**
 * Daily Logs APIs
 */
export const dailyLogsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/daily-logs');
    return response.data;
  },

  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/daily-logs/project/${projectId}`);
    return response.data;
  },

  getByProjectAndDate: async (projectId, date) => {
    const response = await apiClient.get(`/api/daily-logs/project/${projectId}/date/${date}`);
    return response.data;
  },

  create: async (logData) => {
    const response = await apiClient.post('/api/daily-logs', logData);
    return response.data;
  },

  getPdf: async (logId) => {
    const response = await apiClient.get(`/api/daily-logs/${logId}/pdf`, {
      responseType: 'blob',
    });
    return response.data;
  },
};

/**
 * Dropbox APIs
 */
export const dropboxAPI = {
  // Get Dropbox connection status
  getStatus: async () => {
    const response = await apiClient.get('/api/dropbox/status');
    return response.data;
  },

  // Get OAuth authorization URL
  getAuthUrl: async () => {
    const response = await apiClient.get('/api/dropbox/auth-url');
    return response.data;
  },

  // Complete OAuth flow with authorization code
  completeAuth: async (code) => {
    const response = await apiClient.post('/api/dropbox/complete-auth', { code });
    return response.data;
  },

  // Disconnect Dropbox
  disconnect: async () => {
    const response = await apiClient.delete('/api/dropbox/disconnect');
    return response.data;
  },

  // Link Dropbox folder to project
  linkToProject: async (projectId, folderPath) => {
    const response = await apiClient.post(`/api/projects/${projectId}/link-dropbox`, {
      folder_path: folderPath,
    });
    return response.data;
  },

  // Get Dropbox files for a project
  getProjectFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
    return response.data;
  },

  // Get user's Dropbox folders for selection
  getFolders: async (path = '') => {
    const response = await apiClient.get('/api/dropbox/folders', {
      params: { path },
    });
    return response.data;
  },

  // Sync project files from Dropbox
  syncProject: async (projectId) => {
    const response = await apiClient.post(`/api/projects/${projectId}/sync-dropbox`);
    return response.data;
  },

  // Get file download/preview URL
  getFileUrl: async (projectId, filePath) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-file-url`, {
      params: { file_path: filePath },
    });
    return response.data;
  },
};

/**
 * Admin User Management APIs
 */
export const adminUsersAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/admin/users');
    return response.data;
  },

  getById: async (userId) => {
    const response = await apiClient.get(`/api/admin/users/${userId}`);
    return response.data;
  },

  create: async (userData) => {
    const response = await apiClient.post('/api/admin/users', userData);
    return response.data;
  },

  update: async (userId, userData) => {
    const response = await apiClient.put(`/api/admin/users/${userId}`, userData);
    return response.data;
  },

  delete: async (userId) => {
    const response = await apiClient.delete(`/api/admin/users/${userId}`);
    return response.data;
  },

  assignProjects: async (userId, projectIds) => {
    const response = await apiClient.post(`/api/admin/users/${userId}/assign-projects`, {
      project_ids: projectIds,
    });
    return response.data;
  },
};

/**
 * Admin Subcontractors APIs
 */
export const adminSubcontractorsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/admin/subcontractors');
    return response.data;
  },

  getById: async (subId) => {
    const response = await apiClient.get(`/api/admin/subcontractors/${subId}`);
    return response.data;
  },

  create: async (subData) => {
    const response = await apiClient.post('/api/admin/subcontractors', subData);
    return response.data;
  },

  update: async (subId, subData) => {
    const response = await apiClient.put(`/api/admin/subcontractors/${subId}`, subData);
    return response.data;
  },

  delete: async (subId) => {
    const response = await apiClient.delete(`/api/admin/subcontractors/${subId}`);
    return response.data;
  },
};

/**
 * NFC Check-In APIs
 */
export const nfcAPI = {
  // Get NFC tag info (no auth required - used on worker check-in)
  getTagInfo: async (tagId) => {
    const response = await axios.get(`${API_BASE_URL}/api/nfc-tags/${tagId}/info`);
    return response.data;
  },

  // Link NFC tag to project (admin only)
  linkToProject: async (projectId, tagId, locationDescription) => {
    const response = await apiClient.post(`/api/projects/${projectId}/nfc-tags`, {
      tag_id: tagId,
      location_description: locationDescription,
    });
    return response.data;
  },

  // Unlink NFC tag from project (admin only)
  unlinkFromProject: async (projectId, tagId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}/nfc-tags/${tagId}`);
    return response.data;
  },

  // Get project NFC tags
  getProjectTags: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/nfc-tags`);
    return response.data;
  },

  // Process check-in (no auth - used by workers)
  checkIn: async (checkinData) => {
    const response = await axios.post(`${API_BASE_URL}/api/checkin`, checkinData);
    return response.data;
  },

  // Register new worker (no auth)
  registerWorker: async (workerData) => {
    const response = await axios.post(`${API_BASE_URL}/api/workers/register`, workerData);
    return response.data;
  },
};

/**
 * Owner Portal APIs
 */
export const ownerAPI = {
  // Get all admin accounts
  getAdmins: async () => {
    const response = await apiClient.get('/api/owner/admins');
    return response.data;
  },

  createAdmin: async (adminData) => {
    const response = await apiClient.post('/api/owner/admins', adminData);
    return response.data;
  },

  updateAdmin: async (adminId, adminData) => {
    const response = await apiClient.put(`/api/owner/admins/${adminId}`, adminData);
    return response.data;
  },

  deleteAdmin: async (adminId) => {
    const response = await apiClient.delete(`/api/owner/admins/${adminId}`);
    return response.data;
  },
};

export default apiClient;
