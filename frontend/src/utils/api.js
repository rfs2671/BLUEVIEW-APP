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

// ── Phase C2: 429 rate-limit handling ─────────────────────────────
//
// The backend's lib/rate_limits.py middleware returns 429 with a
// JSON body { error, retry_after_seconds, limit } and a Retry-After
// header on every blocked request. We surface a user-friendly
// message via the supplied toast hook (set once at app boot via
// registerRateLimitToast); we do NOT auto-retry — retrying would
// just amplify the abuse signal and burn the user's window faster.
//
// Auth-form-specific lockout (login form locks for retry_after_seconds)
// is handled at the call site (see login.jsx in a future commit if
// needed); this interceptor only owns the toast and the rejected
// promise.
let _onRateLimitedToast = null;
export const registerRateLimitToast = (toastFn) => {
  _onRateLimitedToast = typeof toastFn === 'function' ? toastFn : null;
};

export const parseRateLimitError = (err) => {
  if (!err || !err.response || err.response.status !== 429) return null;
  const body = err.response.data || {};
  const retryAfterFromHeader = parseInt(
    err.response.headers?.['retry-after'] || '0', 10,
  );
  const retry =
    Number.isFinite(body.retry_after_seconds) && body.retry_after_seconds > 0
      ? body.retry_after_seconds
      : Number.isFinite(retryAfterFromHeader) && retryAfterFromHeader > 0
        ? retryAfterFromHeader
        : 60;
  return {
    retryAfterSeconds: retry,
    limit: body.limit || null,
    error: body.error || 'rate_limit_exceeded',
  };
};

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      await clearAuth();
      // Navigation will be handled by AuthContext
    } else if (error.response?.status === 429) {
      const info = parseRateLimitError(error);
      if (info && _onRateLimitedToast) {
        try {
          _onRateLimitedToast({
            retryAfterSeconds: info.retryAfterSeconds,
            limit: info.limit,
            // User-facing message — "Please try again in N seconds"
            // is friendlier than the raw 429 stack.
            message:
              `Too many requests. Please try again in ${info.retryAfterSeconds} seconds.`,
          });
        } catch (_e) { /* never let the error path itself throw */ }
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Phase B3 — customer onboarding flow.
 *
 * The frontend RouteGuard reads onboardingAPI.getStatus() on every
 * authed page; when show_onboarding=true it forces a redirect to
 * /onboarding. Each step calls patchStep() to advance / skip / mark
 * complete. Pre-B3 users (no `onboarding_step` field on doc) get
 * show_onboarding=false from the backend and never see the flow.
 */
export const onboardingAPI = {
  getStatus: async () => {
    const response = await apiClient.get('/api/users/me/onboarding-status');
    return response.data;
  },

  patchStep: async (step) => {
    const response = await apiClient.patch('/api/users/me/onboarding-step', { step });
    return response.data;
  },
};

/**
 * Read-only seeded demo for pending (unapproved) accounts. Static server data,
 * no external cost. Open to pending users.
 */
export const demoAPI = {
  getProject: async () => {
    const response = await apiClient.get('/api/demo/project');
    return response.data;
  },
};

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

  // Self-serve signup. The backend forces new accounts to a pending state and
  // does not return a token, so callers register then call login() to sign in.
  register: async (payload) => {
    const response = await apiClient.post('/api/auth/register', payload);
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

  // Apple 5.1.1(v). A REQUEST, not a deletion — see the server note. A CP
  // carries unsynced signed logbooks; revoke his token and the drain takes a
  // 401, which the client correctly reads as a server refusal and banners as
  // "your log was refused". The records survive but are stranded and
  // mislabelled. Drain first, delete second, and only a person can confirm the
  // drain finished.
  requestAccountDeletion: async () => {
    const response = await apiClient.post('/api/auth/me/deletion-request');
    return response.data;
  },

  withdrawAccountDeletion: async () => {
    const response = await apiClient.delete('/api/auth/me/deletion-request');
    return response.data;
  },
};

/**
 * Projects APIs
 */
/**
 * The commit the BACKEND is running. Pairs with the JS bundle identity in
 * settings so a stale-bundle device test cannot be mistaken for a missing
 * feature — which it was, once, for the Step 1 equipment/weather move.
 */
export const versionAPI = {
  get: async () => {
    const response = await apiClient.get('/api/version');
    return response.data;
  },
};

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

  // PR #15D — Compliance Risk forecast. Returns the
  // PredictionResponse shape from server.serialize_prediction_cache
  // _to_response: { prediction_available, horizons, anchored_baseline,
  // confidence, metadata }. Consumed by CompliancePanel.
  getPrediction: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/prediction`
    );
    return response.data;
  },

  // Phase 1 Week 11-12 PR-A — Defcon 3-tier urgency status. Returns
  // DefconStatusResponse: { tier, tier_color, primary_reason,
  // contributing_factors, last_evaluated_at, cohort_context }.
  // Consumed by CompliancePanel (DefconHeader) and the
  // /project/{id}/defcon detail screen.
  getDefconStatus: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/defcon-status`
    );
    return response.data;
  },

  // Phase 1 Week 13-19 PR-B — recent complaint buckets rollup.
  // Returns { buckets: [{bucket, n_complaints}, ...] } sorted by
  // count DESC for the project's last-90-day complaint distribution.
  // Feeds the Tactical Recommendations component which fans out into
  // per-bucket /api/causal-lift queries.
  getRecentComplaintBuckets: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/recent-complaint-buckets`
    );
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

  // TIER 1 — mark for deletion (admin or owner). Nothing is removed: the
  // project is flagged, hidden from admin surfaces, and its NFC tags are
  // deactivated. Only the owner can purge it afterwards.
  delete: async (projectId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}`);
    return response.data;
  },

  // Owner-ONLY: projects an admin has marked for deletion, awaiting purge.
  pendingDeletion: async () => {
    const response = await apiClient.get('/api/projects/pending-deletion');
    return response.data;
  },

  // TIER 2 — owner-ONLY irreversible purge. Removes the project and every
  // document, storage object and config key it owns.
  hardDelete: async (projectId) => {
    const response = await apiClient.delete(
      `/api/projects/${projectId}/hard-delete`,
    );
    return response.data;
  },

  getRequiredLogbooks: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/required-logbooks`);
    return response.data;
  },
};

/**
 * Phase 1 Week 13-19 PR-A + PR-B — causal lift readout.
 * Returns the top recommendations from the causal_lift_matrix
 * collection, filtered by complaint_bucket + window_days. By default
 * the backend filters to lift_ratio >= 1.5 AND confidence ∈
 * {HIGH, MEDIUM}; pass { includeAll: true } to bypass.
 */
export const causalLiftAPI = {
  getByBucket: async (bucket, { windowDays = 90, includeAll = false, limit = 50 } = {}) => {
    const params = {
      complaint_bucket: bucket,
      window_days: windowDays,
      limit,
    };
    if (includeAll) params.include_all = true;
    const response = await apiClient.get('/api/causal-lift', { params });
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
    // Use the New York calendar date, not the UTC one — toISOString() rolls to
    // the next day for any evening EDT time (e.g. 8:30pm EDT = 00:30 UTC), which
    // asked the backend for the wrong day's check-ins. en-CA formats as YYYY-MM-DD.
    const dateStr = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(date);
    const response = await apiClient.get(`/api/checkins?date=${dateStr}`);
    // /api/checkins is paginated: {items,total,limit,skip,has_more}. Unwrap so
    // callers get the array they Array.isArray-guard on (projectsAPI.getAll
    // pattern). Tolerates a bare array if the endpoint is ever de-paginated.
    const data = response.data;
    return Array.isArray(data) ? data : (data?.items ?? []);
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

  // GET /api/checkins/project/{id}/flagged — check-ins needing a decision:
  // unreviewed expired-SST, or arrived with no trade assigned. Company-scoped
  // server-side (unlike the other project-checkins endpoints).
  getFlagged: async (projectId) => {
    const response = await apiClient.get(
      `/api/checkins/project/${projectId}/flagged`,
    );
    return response.data;
  },

  // POST /api/checkins/{id}/assign-trade — assign a trade/company to a
  // check-in that arrived without one and clear needs_trade_assignment.
  // The pair must exist on the project's roster; attribution is server-derived.
  assignTrade: async (checkinId, trade, company) => {
    const response = await apiClient.post(
      `/api/checkins/${checkinId}/assign-trade`,
      { trade, company },
    );
    return response.data;
  },

  // POST /api/checkins/{id}/review — record an admin/CP decision on a flagged
  // (e.g. expired-SST) check-in. decision: "approved" | "sent_home".
  // Attribution (reviewed_by) is derived server-side from the auth token —
  // it is never sent by the client.
  review: async (checkinId, decision) => {
    const response = await apiClient.post(
      `/api/checkins/${checkinId}/review`,
      { decision },
    );
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
    // Paginated wrapper {items,...} → array (projectsAPI.getAll pattern), so
    // the site daily-log "Previous" list and Today-log lookup stop collapsing
    // to [] under Array.isArray. Bare array tolerated for future de-pagination.
    const data = response.data;
    return Array.isArray(data) ? data : (data?.items ?? []);
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

  // Site-device visibility config: which subfolders of the linked
  // project folder the kiosk role is allowed to see. Empty list = kiosk
  // sees nothing. Admins/CPs always see everything.
  getSiteDeviceSubfolders: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/${projectId}/dropbox-subfolders`
    );
    return response.data;
  },

  setSiteDeviceSubfolders: async (projectId, subfolders) => {
    const response = await apiClient.put(
      `/api/projects/${projectId}/site-device-subfolders`,
      { subfolders }
    );
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
export const logbookActivationAPI = {
  /**
   * Switch a conditional logbook on or off for a project.
   *
   * The SERVER decides who may: the registry declares `activated_by` per type
   * and the endpoint enforces it, so hiding a control on the client is a
   * courtesy and never the guard. A CP who reaches the hot-work switch some
   * other way still gets a 403.
   */
  set: async (projectId, logType, active) => {
    const response = await apiClient.put(
      `/api/logbooks/project/${projectId}/activation`,
      { log_type: logType, active },
    );
    return response.data;
  },
};

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
    // Paginated wrapper {items,...} → array (projectsAPI.getAll pattern). This
    // is the load-bearing one: the logbook editors Array.isArray-guard this to
    // compute `existing`; the raw wrapper made existing=null, so they reopened
    // blank and re-entered the create path, upsert-$set overwriting the day's
    // record (a real toolbox_talk was overwritten 2026-07-29, no audit trail).
    const data = response.data;
    return Array.isArray(data) ? data : (data?.items ?? []);
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

  // Tier 1 (1): end-of-day FINALIZATION — locks the log immutable (423 on edit after).
  finalize: async (logbookId) => {
    const response = await apiClient.post(`/api/logbooks/${logbookId}/finalize`);
    return response.data;
  },

  // Tier 1 (1): create a linked AMENDMENT of a finalized log. reason is required;
  // optional data seeds the editable child (else it copies the original's data).
  amend: async (logbookId, reason, data = undefined) => {
    const response = await apiClient.post(`/api/logbooks/${logbookId}/amend`, { reason, data });
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

  /**
   * The same roster as getCheckinsForDate, but WITH the integrity report the
   * bare list cannot carry:
   *
   *   {workers, partial, degraded_passes, truncated_passes, collapsed}
   *
   * The endpoint runs three passes and each swallows its own failure, so a
   * bare list cannot distinguish "nobody else was on site" from "a query
   * failed and those men are missing". The daily jobsite stepper builds a
   * SIGNED record off this, so it asks for the envelope and says so on screen
   * when `partial` is true rather than rendering a short roster as complete.
   *
   * `collapsed` counts men dropped by the (name, company) dedupe guard —
   * normally a duplicate of the same worker, but indistinguishable from a
   * second man who shares a name at one sub, because the gate and legacy id
   * spaces have no join key.
   *
   * Returns a normalized envelope even on a malformed response, so a caller
   * never has to guess whether it got the list or the wrapper.
   */
  getCheckinsRoster: async (projectId, date = null) => {
    const params = { envelope: 1 };
    if (date) params.date = date;
    const response = await apiClient.get(
      `/api/logbooks/project/${projectId}/checkins-today`, { params },
    );
    const d = response.data;
    if (Array.isArray(d)) {
      // An older server that does not know the flag. Unknown is NOT clean:
      // report it as partial so the CP is never told a roster is complete on
      // the word of something that cannot make that claim.
      return {
        workers: d, partial: true, degraded_passes: [], truncated_passes: [],
        collapsed: 0, envelope_unsupported: true,
      };
    }
    return {
      workers: Array.isArray(d?.workers) ? d.workers : [],
      partial: d?.partial !== false,
      degraded_passes: d?.degraded_passes || [],
      truncated_passes: d?.truncated_passes || [],
      collapsed: Number(d?.collapsed) || 0,
      envelope_unsupported: false,
    };
  },

  /**
   * Ranked activity chips for one project-day.
   * GET /api/projects/{id}/activity-chips — RANKING ONLY. The server never
   * pre-selects (ActivityChip.selected is Literal[False], so a selected chip is
   * unconstructible) and "Other" is always the last chip. `date` is the day
   * being logged; priors are read from the most recent daily_jobsite log
   * STRICTLY BEFORE it.
   */
  getActivityChips: async (projectId, date = null, trade = null) => {
    const params = {};
    if (date) params.date = date;
    // The CREW's roster trade. Without it the whole catalogue comes back, as
    // before. With it the suggested and catalog bands narrow to that trade —
    // an electrical crew was being offered drywall because the ranking keyed
    // off the PROJECT's prior day and nothing else.
    if (trade) params.trade = trade;
    const response = await apiClient.get(
      `/api/projects/${projectId}/activity-chips`, { params },
    );
    return response.data;
  },

  /**
   * Per-company headcount for a project on a given date. Used by
   * Daily Jobsite Log — a headcount log, not a signature roster.
   * Returns [{sub_name, trade, worker_count_today}, ...].
   */
  getDailyHeadcount: async (projectId, date = null) => {
    const params = date ? { date } : {};
    const response = await apiClient.get(`/api/projects/${projectId}/daily-headcount`, { params });
    return response.data;
  },

  /**
   * URL an <Image> can point at for a SAVED logbook activity photo. `variant`
   * selects the derivative: 'enhanced' (long edge 1800) or 'thumb' (400); any
   * other value serves the untouched original. The endpoint falls back to the
   * original on ANY failure (enhancement pending/failed, R2 miss), so this URL
   * never yields a broken image. `bust` cache-busts when the enhance status
   * flips. Only valid once the logbook has an id.
   */
  getLogbookPhotoUrl: (logbookId, activityIndex, photoIndex, variant = 'enhanced', bust = '') => {
    if (!logbookId && logbookId !== 0) return null;
    const q = `?v=${encodeURIComponent(variant)}${bust ? `&t=${encodeURIComponent(bust)}` : ''}`;
    return `${API_BASE_URL}/api/reports/logbook-photo/${encodeURIComponent(logbookId)}/${activityIndex}/${photoIndex}${q}`;
  },
};

/**
 * Signature image helpers. Images come from an authenticated backend
 * proxy — /api/signatures/{signin_id} — which reads from R2 with
 * server-side credentials. The session token travels on the request
 * via apiClient's Authorization header. Never use presigned URLs for
 * signatures anywhere in the app.
 */
export const signaturesAPI = {
  /** Return the URL an <Image> / <img> component can point src/uri at. */
  getImageUrl: (signInId) => {
    if (!signInId) return null;
    return `${API_BASE_URL}/api/signatures/${encodeURIComponent(signInId)}`;
  },

  /**
   * Fetch the signature bytes directly (useful for PDF export pipelines
   * that embed the image rather than referencing it by URL). Returns
   * a Blob on web, a base64 string on native.
   */
  fetchImage: async (signInId) => {
    if (!signInId) return null;
    const response = await apiClient.get(`/api/signatures/${encodeURIComponent(signInId)}`, {
      responseType: 'blob',
    });
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
  // MR.14 commit 3 — activity feed query supports the full filter set:
  //   severity, record_type, signal_kinds (array), severity_kind,
  //   date_range, unread_only, search, limit, skip, include_seed.
  getLogs: async (projectId, params = {}) => {
    const queryParts = [];
    if (params.severity) queryParts.push(`severity=${encodeURIComponent(params.severity)}`);
    if (params.record_type) queryParts.push(`record_type=${encodeURIComponent(params.record_type)}`);
    if (params.signal_kinds && params.signal_kinds.length) {
      queryParts.push(`signal_kinds=${encodeURIComponent(params.signal_kinds.join(','))}`);
    }
    if (params.severity_kind) queryParts.push(`severity_kind=${encodeURIComponent(params.severity_kind)}`);
    if (params.date_range) queryParts.push(`date_range=${encodeURIComponent(params.date_range)}`);
    if (params.unread_only) queryParts.push(`unread_only=true`);
    if (params.search) queryParts.push(`search=${encodeURIComponent(params.search)}`);
    if (typeof params.limit === 'number') queryParts.push(`limit=${params.limit}`);
    if (typeof params.skip === 'number') queryParts.push(`skip=${params.skip}`);
    if (params.include_seed) queryParts.push(`include_seed=true`);
    const queryString = queryParts.length > 0 ? `?${queryParts.join('&')}` : '';
    const response = await apiClient.get(`/api/projects/${projectId}/dob-logs${queryString}`);
    return response.data;
  },

  // Standing OPEN DOB exposure for one project, computed server-side by
  // STATUS deduped by raw_dob_id — NO detected_at window (so tile numbers
  // don't decay as the sync stamp ages). Returns
  // { by_project: { <pid>: { open_violations, open_complaints,
  //   permits_expiring, has_risk_score } }, totals: {...} }.
  getSummary: async (projectId) => {
    const response = await apiClient.get(
      `/api/projects/dob-summary?project_id=${encodeURIComponent(projectId)}`
    );
    return response.data;
  },

  // MR.14 commit 3 — mark a single dob_log as read for the calling user.
  markRead: async (projectId, logId) => {
    const response = await apiClient.post(
      `/api/projects/${projectId}/dob-logs/${logId}/mark-read`
    );
    return response.data;
  },

  // MR.14 commit 3 — bulk-mark all unread dob_logs in the activity-feed
  // window (last 30 days, excluding seed transitions). Server applies the
  // same scope filter as the default GET to keep the write bounded.
  markAllRead: async (projectId) => {
    const response = await apiClient.post(
      `/api/projects/${projectId}/dob-logs/mark-all-read`
    );
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
 * Lightweight company user roster for recipient pickers.
 * Available to ANY authenticated user (not admin-only).
 */
export const usersAPI = {
  companyRoster: async () => {
    const response = await apiClient.get('/api/users/company-roster');
    return Array.isArray(response.data) ? response.data : [];
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

// V2.3 Commit 7 — In-app notifications inbox.
// Backs the project-page notifications surface. Each endpoint
// is server-scoped to current_user (no cross-user leakage).
export const notificationsAPI = {
  // GET /api/notifications — paginated list. Default
  // status="active" filter (hides dismissed). Optional
  // unread_only and project_id filters.
  list: async ({ projectId, unreadOnly = false, limit = 50, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (unreadOnly) params.unread_only = true;
    if (projectId) params.project_id = projectId;
    const response = await apiClient.get('/api/notifications', { params });
    return response.data;
  },

  // GET /api/notifications/unread-count — single integer count.
  // FE polls this on a 60-second interval for the per-project
  // badge. Optional project_id scope.
  unreadCount: async ({ projectId } = {}) => {
    const params = {};
    if (projectId) params.project_id = projectId;
    const response = await apiClient.get(
      '/api/notifications/unread-count', { params },
    );
    return response.data;
  },

  // POST /api/notifications/{id}/mark-read — sets read_at=now
  // for one notification. Ownership enforced server-side; 404
  // on cross-user access.
  markRead: async (notificationId) => {
    const response = await apiClient.post(
      `/api/notifications/${notificationId}/mark-read`,
    );
    return response.data;
  },

  // POST /api/notifications/mark-all-read — bulk update for
  // the current user's unread-active notifications. Optional
  // project_id scopes to one project's inbox.
  markAllRead: async ({ projectId } = {}) => {
    const params = {};
    if (projectId) params.project_id = projectId;
    const response = await apiClient.post(
      '/api/notifications/mark-all-read', null, { params },
    );
    return response.data;
  },
};

export default apiClient;
