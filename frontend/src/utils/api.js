import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// API Base URL - uses the preview URL which proxies /api to backend
const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || 'https://api.levelog.com';

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
    const response = await apiClient.post('/api/auth/login', {
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

  updateProfile: async (data) => {
    const response = await apiClient.put('/api/auth/profile', data);
    return response.data;
  },

  updatePassword: async (data) => {
    const response = await apiClient.put('/api/auth/password', data);
    return response.data;
  },
};

/**
 * Projects APIs
 */
export const projectsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/projects');
    const data = response.data;
    return Array.isArray(data) ? data : (data.items || []);
  },

  getById: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}`);
    return response.data;
  },

  addNfcTag: async (projectId, tagData) => {
    const response = await apiClient.post(`/api/projects/${projectId}/nfc-tags`, tagData);
    return response.data;
  },

  getNfcTags: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/nfc-tags`);
    return response.data;
  },

  deleteNfcTag: async (projectId, tagId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}/nfc-tags/${tagId}`);
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

  updateReportSettings: async (projectId, settingsData) => {
    const response = await apiClient.put(`/api/projects/${projectId}/report-settings`, settingsData);
    return response.data;
  },

  delete: async (projectId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}`);
    return response.data;
  },

  getRequiredLogbooks: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/required-logbooks`);
    return response.data;
  },
};

/**
 * Workers APIs
 */
export const workersAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/workers');
    const data = response.data;
    return Array.isArray(data) ? data : (data.items || []);
},

  getById: async (workerId) => {
    const response = await apiClient.get(`/api/workers/${workerId}`);
    return response.data;
  },

  create: async (workerData) => {
    const response = await apiClient.post('/api/workers', workerData);
    return response.data;
  },

  getOshaCard: async (workerId) => {
    const response = await apiClient.get(`/api/workers/${workerId}/osha-card`);
    return response.data;
  },

  update: async (workerId, workerData) => {
    const response = await apiClient.put(`/api/workers/${workerId}`, workerData);
    return response.data;
  },

  delete: async (workerId) => {
    const response = await apiClient.delete(`/api/workers/${workerId}`);
    return response.data;
  },
};

/**
 * Check-ins APIs
 */
export const checkinsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/checkins');
    const data = response.data;
    return Array.isArray(data) ? data : (data.items || []);
  },

  getByDate: async (date) => {
    const dateStr = date.toISOString().split('T')[0];
    const response = await apiClient.get(`/api/checkins?date=${dateStr}`);
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

  getById: async (logId) => {
    const response = await apiClient.get(`/api/daily-logs/${logId}`);
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

  update: async (logId, updateData) => {
    const response = await apiClient.put(`/api/daily-logs/${logId}`, updateData);
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
 * Paginated fetch helper — handles both old (array) and new ({items, total}) response shapes.
 */
export const fetchPaginated = async (url, params = {}) => {
  const response = await apiClient.get(url, {
    params: { limit: 50, skip: 0, ...params },
  });
  if (Array.isArray(response.data)) {
    return { items: response.data, total: response.data.length, has_more: false };
  }
  return response.data;
};

/**
 * Load ALL records across pages (for exports/reports only — not UI lists).
 */
export const fetchAll = async (url, params = {}, maxPages = 20) => {
  const all = [];
  let skip = 0;
  const limit = 200;
  for (let page = 0; page < maxPages; page++) {
    const result = await fetchPaginated(url, { ...params, limit, skip });
    all.push(...result.items);
    if (!result.has_more) break;
    skip += limit;
  }
  return all;
};
/**
 * Dropbox APIs
 */
export const dropboxAPI = {
  getStatus: async () => {
    const response = await apiClient.get('/api/dropbox/status');
    return response.data;
  },

  getAuthUrl: async () => {
    const response = await apiClient.get('/api/dropbox/auth-url');
    return response.data;
  },

  completeAuth: async (code) => {
    const response = await apiClient.post('/api/dropbox/complete-auth', { code });
    return response.data;
  },

  disconnect: async () => {
    const response = await apiClient.delete('/api/dropbox/disconnect');
    return response.data;
  },

  linkToProject: async (projectId, folderPath) => {
    const response = await apiClient.post(`/api/projects/${projectId}/link-dropbox`, {
      folder_path: folderPath,
    });
    return response.data;
  },

  getProjectFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
    return response.data;
  },

  getFolders: async (path = '') => {
    const response = await apiClient.get('/api/dropbox/folders', {
      params: { path },
    });
    return response.data;
  },

  syncProject: async (projectId) => {
    const response = await apiClient.post(`/api/projects/${projectId}/sync-dropbox`);
    return response.data;
  },

  getFileUrl: async (projectId, filePath) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-file-url`, {
      params: { file_path: filePath },
    });
    return response.data;
  },

  uploadFile: async (projectId, formData) => {
    // Web:   axios auto-sets `multipart/form-data; boundary=...` when the body
    //        is a browser FormData, BUT only if the header is absent. Our default
    //        `Content-Type: application/json` would otherwise stick, so we pass
    //        `undefined` to force axios to drop it and let the browser fill it in.
    // Native: React Native's XHR will auto-set the multipart header if we pass
    //         `multipart/form-data` with no boundary. We also need to disable
    //         axios's transformRequest (which would otherwise JSON-stringify our
    //         FormData) by passing the body through as-is.
    const isWeb = typeof window !== 'undefined' && !!window.document;
    const headers = isWeb
      ? { 'Content-Type': undefined }
      : { 'Content-Type': 'multipart/form-data' };
    const response = await apiClient.post(`/api/projects/${projectId}/upload-file`, formData, {
      timeout: 120000,
      headers,
      transformRequest: (data) => data,
    });
    return response.data;
  },

  deleteFile: async (projectId, fileId) => {
    // Hard-delete: removes R2 object + Mongo row. Owner/admin only.
    const response = await apiClient.delete(`/api/projects/${projectId}/files/${fileId}`);
    return response.data;
  },
};

/**
 * Admin User Management APIs
 */
export const adminUsersAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/admin/users');
    const data = response.data;
    return Array.isArray(data) ? data : (data.items || []);
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
 * Owner Portal APIs
 */
export const ownerAPI = {
  getAdmins: async () => {
    const response = await apiClient.get('/api/owner/admins');
    const data = response.data;
    return Array.isArray(data) ? data : (data.items || []);
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

/**
 * Checklists APIs
 */
export const checklistsAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/admin/checklists');
    return response.data;
  },

  create: async (data) => {
    const response = await apiClient.post('/api/admin/checklists', data);
    return response.data;
  },

  getById: async (id) => {
    const response = await apiClient.get(`/api/admin/checklists/${id}`);
    return response.data;
  },

  update: async (id, data) => {
    const response = await apiClient.put(`/api/admin/checklists/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await apiClient.delete(`/api/admin/checklists/${id}`);
    return response.data;
  },

  assign: async (checklistId, data) => {
    const response = await apiClient.post(`/api/admin/checklists/${checklistId}/assign`, data);
    return response.data;
  },

  getAssignments: async (checklistId) => {
    const response = await apiClient.get(`/api/admin/checklists/${checklistId}/assignments`);
    return response.data;
  },

  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/checklists`);
    return response.data;
  },

  getAssigned: async () => {
    const response = await apiClient.get('/api/checklists/assigned');
    return response.data;
  },

  getAssignmentDetails: async (assignmentId) => {
    const response = await apiClient.get(`/api/checklists/assignments/${assignmentId}`);
    return response.data;
  },

  updateCompletion: async (assignmentId, data) => {
    const response = await apiClient.put(`/api/checklists/assignments/${assignmentId}/complete`, data);
    return response.data;
  },
};

/**
 * Logbook Type Registry
 */
export const logbookTypesAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/logbook-types');
    return response.data;
  },
};

/**
 * Safety Staff APIs
 */
export const safetyStaffAPI = {
  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/safety-staff`);
    return response.data;
  },

  create: async (projectId, data) => {
    const response = await apiClient.post(`/api/projects/${projectId}/safety-staff`, data);
    return response.data;
  },

  update: async (staffId, data) => {
    const response = await apiClient.put(`/api/safety-staff/${staffId}`, data);
    return response.data;
  },

  delete: async (staffId) => {
    const response = await apiClient.delete(`/api/safety-staff/${staffId}`);
    return response.data;
  },
};

export const logbooksAPI = {
  getByProject: async (projectId, logType = null, date = null) => {
    const params = {};
    if (logType) params.log_type = logType;
    if (date) params.date = date;
    const response = await apiClient.get(`/api/logbooks/project/${projectId}`, { params });
    return response.data;
  },

  getById: async (logbookId) => {
    const response = await apiClient.get(`/api/logbooks/${logbookId}`);
    return response.data;
  },

  create: async (data) => {
    const response = await apiClient.post('/api/logbooks', data);
    return response.data;
  },

  update: async (logbookId, data) => {
    const response = await apiClient.put(`/api/logbooks/${logbookId}`, data);
    return response.data;
  },

  delete: async (logbookId) => {
    const response = await apiClient.delete(`/api/logbooks/${logbookId}`);
    return response.data;
  },

  getNotifications: async (projectId) => {
    const response = await apiClient.get(`/api/logbooks/project/${projectId}/notifications`);
    return response.data;
  },

  getScaffoldInfo: async (projectId) => {
    const response = await apiClient.get(`/api/logbooks/project/${projectId}/scaffold-info`);
    return response.data;
  },

  saveScaffoldInfo: async (projectId, data) => {
    const response = await apiClient.put(`/api/logbooks/project/${projectId}/scaffold-info`, data);
    return response.data;
  },

  getSubmitted: async (projectId) => {
    const response = await apiClient.get(`/api/logbooks/project/${projectId}/submitted`);
    return response.data;
  },

  getPdf: async (logbookId) => {
    const response = await apiClient.get(`/api/reports/logbook/${logbookId}/pdf`, {
      responseType: 'blob',
    });
    return response.data;
  },

  getCheckinsForDate: async (projectId, date = null) => {
    const params = date ? { date } : {};
    const response = await apiClient.get(`/api/logbooks/project/${projectId}/checkins-today`, { params });
    return response.data;
  },
};

export const cpProfileAPI = {
  getProfile: async () => {
    const response = await apiClient.get('/api/cp/profile');
    return response.data;
  },

  updateProfile: async (data) => {
    const response = await apiClient.put('/api/cp/profile', data);
    return response.data;
  },
};

export const weatherAPI = {
  getCurrent: async (lat = null, lng = null, address = null) => {
    const params = {};
    if (lat) params.lat = lat;
    if (lng) params.lng = lng;
    if (address) params.address = address;
    const response = await apiClient.get('/api/weather', { params });
    return response.data;
  },
};

/**
 * Reports APIs (admin)
 */
export const reportsAPI = {
  getPreview: async (projectId, date) => {
    const response = await apiClient.get(`/api/reports/project/${projectId}/preview/${date}`);
    return response.data;
  },

  getFullReport: async (projectId, date) => {
    const response = await apiClient.get(`/api/reports/project/${projectId}/date/${date}`);
    return response.data;
  },

  getHistory: async (projectId, limit = 30, skip = 0) => {
    const response = await apiClient.get(`/api/reports/project/${projectId}/history`, {
      params: { limit, skip },
    });
    return response.data;
  },

  getLogs: async (projectId, date = null, logType = null) => {
    const params = {};
    if (date) params.date = date;
    if (logType) params.log_type = logType;
    const response = await apiClient.get(`/api/reports/project/${projectId}/logs`, { params });
    return response.data;
  },
};

export const dobAPI = {
  getLogs: async (projectId, params = {}) => {
    const queryParts = [];
    if (params.severity) queryParts.push(`severity=${params.severity}`);
    if (params.record_type) queryParts.push(`record_type=${params.record_type}`);
    if (params.limit) queryParts.push(`limit=${params.limit}`);
    if (params.skip) queryParts.push(`skip=${params.skip}`);
    const queryString = queryParts.length > 0 ? `?${queryParts.join('&')}` : '';
    const response = await apiClient.get(`/api/projects/${projectId}/dob-logs${queryString}`);
    return response.data;
  },

  updateConfig: async (projectId, config) => {
    const response = await apiClient.put(`/api/projects/${projectId}/dob-config`, config);
    return response.data;
  },

  syncNow: async (projectId) => {
    const response = await apiClient.post(`/api/projects/${projectId}/dob-sync`);
    return response.data;
  },

  getConfig: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dob-config`);
    return response.data;
  },
};

export const permitRenewalAPI = {
  list: async (params = {}) => {
    const query = new URLSearchParams();
    if (params.project_id) query.set('project_id', params.project_id);
    if (params.status) query.set('status', params.status);
    if (params.limit) query.set('limit', String(params.limit));
    if (params.skip) query.set('skip', String(params.skip));
    const qs = query.toString();
    const response = await apiClient.get(`/api/permit-renewals${qs ? `?${qs}` : ''}`);
    return response.data;
  },
  getById: async (renewalId) => {
    const response = await apiClient.get(`/api/permit-renewals/${renewalId}`);
    return response.data;
  },
  checkEligibility: async (permitDobLogId, projectId) => {
    const response = await apiClient.post('/api/permit-renewals/check-eligibility', {
      permit_dob_log_id: permitDobLogId,
      project_id: projectId,
    });
    return response.data;
  },
  prepare: async (permitDobLogId, projectId) => {
    const response = await apiClient.post('/api/permit-renewals/prepare', {
      permit_dob_log_id: permitDobLogId,
      project_id: projectId,
    });
    return response.data;
  },
  getDashboardAlerts: async () => {
    const response = await apiClient.get('/api/permit-renewals/dashboard-alerts');
    return response.data;
  },
  getHealthStatus: async () => {
    const response = await apiClient.get('/api/permit-renewals/health-status');
    return response.data;
  },
};

export const csRegistrationAPI = {
  getAll: async (projectId = null) => {
    const params = projectId ? { project_id: projectId } : {};
    const response = await apiClient.get('/api/admin/cs-registrations', { params });
    return response.data;
  },

  create: async (data) => {
    const response = await apiClient.post('/api/admin/cs-registrations', data);
    return response.data;
  },

  getById: async (registrationId) => {
    const response = await apiClient.get(`/api/admin/cs-registrations/${registrationId}`);
    return response.data;
  },

  update: async (registrationId, data) => {
    const response = await apiClient.put(`/api/admin/cs-registrations/${registrationId}`, data);
    return response.data;
  },

  delete: async (registrationId) => {
    const response = await apiClient.delete(`/api/admin/cs-registrations/${registrationId}`);
    return response.data;
  },

  getForProject: async (projectId) => {
    const response = await apiClient.get(`/api/cs/project/${projectId}`);
    return response.data;
  },
};

/**
 * Compliance Alerts APIs (admin)
 */
export const complianceAlertsAPI = {
  getAll: async (resolved = null) => {
    const params = resolved !== null ? { resolved } : {};
    const response = await apiClient.get('/api/admin/compliance-alerts', { params });
    return response.data;
  },

  resolve: async (alertId) => {
    const response = await apiClient.put(`/api/admin/compliance-alerts/${alertId}/resolve`);
    return response.data;
  },
};

/**
 * Signature Events APIs
 */
export const signatureEventsAPI = {
  getForDocument: async (documentType, documentId) => {
    const response = await apiClient.get(
      `/api/signature-events/document/${documentType}/${documentId}`
    );
    return response.data;
  },

  getDetail: async (eventId) => {
    const response = await apiClient.get(`/api/signature-events/${eventId}`);
    return response.data;
  },

  verify: async (documentType, documentId) => {
    const response = await apiClient.get(
      `/api/signature-events/verify/${documentType}/${documentId}`
    );
    return response.data;
  },
};

/**
 * Document Annotations (Plan Notes) APIs
 */
export const annotationsAPI = {
  create: async (data) => {
    const response = await apiClient.post('/api/annotations', data);
    return response.data;
  },
  getForDocument: async (projectId, documentPath) => {
    const encoded = encodeURIComponent(documentPath);
    const response = await apiClient.get(`/api/annotations/${projectId}/${encoded}`);
    return response.data;
  },
  reply: async (annotationId, message) => {
    const response = await apiClient.put(`/api/annotations/${annotationId}/reply`, { message });
    return response.data;
  },
  resolve: async (annotationId) => {
    const response = await apiClient.put(`/api/annotations/${annotationId}/resolve`);
    return response.data;
  },
  delete: async (annotationId) => {
    const response = await apiClient.delete(`/api/annotations/${annotationId}`);
    return response.data;
  },
};

/**
 * WhatsApp Integration APIs
 */
export const whatsappAPI = {
  getStatus: async () => {
    const response = await apiClient.get('/api/whatsapp/status');
    return response.data;
  },

  activate: async () => {
    const response = await apiClient.post('/api/whatsapp/activate');
    return response.data;
  },

  getGroups: async (projectId) => {
    const response = await apiClient.get(`/api/whatsapp/groups/${projectId}`);
    return response.data;
  },

  initiateLink: async (projectId) => {
    const response = await apiClient.post('/api/whatsapp/group-link/initiate', {
      project_id: projectId,
    });
    return response.data;
  },

  verifyLink: async (code, projectId) => {
    const response = await apiClient.post('/api/whatsapp/group-link/verify', {
      code,
      project_id: projectId,
    });
    return response.data;
  },

  unlinkGroup: async (groupDocId) => {
    const response = await apiClient.delete(`/api/whatsapp/groups/${groupDocId}`);
    return response.data;
  },

  /**
   * Update per-group bot configuration. Frontend sends the full bot_config
   * object on every save (simpler than diffing). Backend uses $set with dot
   * notation so partial updates from other clients still work.
   */
  updateGroupConfig: async (groupDocId, config) => {
    const response = await apiClient.put(
      `/api/whatsapp/groups/${groupDocId}/config`,
      config,
    );
    return response.data;
  },

  /**
   * Download the Levelog Assistant vCard and save to contacts.
   *
   * Web:    fetches as blob and triggers a browser download.
   * Native: uses React Native's Linking to open the authed .vcf URL in the
   *         system handler -- iOS/Android auto-present the "Add Contact" flow.
   *
   * OTA-safe: uses only the existing core libraries (axios + Platform + Linking).
   * No expo-sharing dependency -- that would require a native rebuild.
   */
  downloadVCard: async () => {
    const { Platform, Linking } = require('react-native');

    if (Platform.OS === 'web') {
      // Auth + blob download so the browser saves the .vcf file
      const response = await apiClient.get('/api/whatsapp/contact.vcf', {
        responseType: 'blob',
      });
      const blob = new Blob([response.data], { type: 'text/vcard' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'levelog-assistant.vcf';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      return { ok: true };
    }

    // Native: we need the auth token on the URL (Linking can't set headers).
    // Fetch the file content, write it to cache via expo-file-system (already
    // installed), and open it -- the OS shows the "Add Contact" sheet.
    const FileSystem = require('expo-file-system');
    const response = await apiClient.get('/api/whatsapp/contact.vcf', {
      responseType: 'text',
      transformResponse: [(data) => data], // keep as raw text
    });

    const fileUri = `${FileSystem.cacheDirectory}levelog-assistant.vcf`;
    await FileSystem.writeAsStringAsync(fileUri, response.data, {
      encoding: FileSystem.EncodingType.UTF8,
    });

    // On Android, a file:// URI may need a content:// for Linking to work.
    // Fall back gracefully; if Linking fails, surface the file path so the
    // UI can toast it.
    try {
      const supported = await Linking.canOpenURL(fileUri);
      if (supported) {
        await Linking.openURL(fileUri);
        return { ok: true, fileUri };
      }
    } catch (_) { /* fall through */ }

    return { ok: true, fileUri };
  },
};

/**
 * Document indexing (Sprint 3 — plan queries).
 */
export const documentsAPI = {
  getIndexStatus: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/document-index-status`,
    );
    return response.data;
  },
  reindexFile: async (projectId, fileId) => {
    const response = await apiClient.post(
      `/api/projects/${projectId}/reindex-document`,
      { file_id: fileId },
    );
    return response.data;
  },
};

/**
 * WhatsApp checklists — server-extracted action items from group conversations.
 */
export const checklistAPI = {
  getForProject: async (projectId, params = {}) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/whatsapp-checklists`,
      { params },
    );
    return response.data;
  },

  updateItem: async (checklistId, itemIndex, data) => {
    const response = await apiClient.put(
      `/api/whatsapp-checklists/${checklistId}/items/${itemIndex}`,
      data,
    );
    return response.data;
  },
};

export default apiClient;
