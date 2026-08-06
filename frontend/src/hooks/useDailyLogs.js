import { useState } from 'react';
import { dailyLogsAPI } from '../utils/api';
import { isOfflineError, settleFetch } from '../utils/offlineState';

/**
 * Daily-log API access.
 *
 * OFFLINE CONTRACT (Phase A). `createDailyLog`/`updateDailyLog` used to be bare
 * passthroughs — `return await dailyLogsAPI.create(logData)` — so a dead zone
 * sent the raw axios rejection straight to the screen's catch, which rendered
 * "Could not save daily log" and dropped a SIGNED compliance record on the
 * floor. They still reject on failure (identical public shape: same names, same
 * success returns, so no caller breaks), but the rejection now carries
 *
 *   error.offline     -> true when the request never reached a server
 *   error.userMessage -> copy the caller can surface verbatim
 *
 * so the screen can say "saved on this device, it will sync" instead of
 * implying loss. The DURABLE copy is the screen's AsyncStorage draft
 * (src/utils/logbookDrafts.js) — no second queue is invented here; this hook
 * stays a thin, honest API wrapper.
 */

function annotatePushError(error, verb) {
  const offline = isOfflineError(error);
  try {
    error.offline = offline;
    error.userMessage = offline
      ? 'No connection right now — this is saved on your device and will sync when you reconnect.'
      : (error?.response?.data?.detail || `The server could not ${verb} this daily log.`);
  } catch (_e) { /* non-writable error object — annotation is best-effort */ }
  return error;
}

export function useDailyLogs(projectId = null) {
  const [dailyLogs, setDailyLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create daily log via API. Rejects (annotated) on failure — callers must
  // have already persisted the local draft before calling.
  const createDailyLog = async (logData) => {
    try {
      return await dailyLogsAPI.create(logData);
    } catch (error) {
      console.warn('Daily log create push failed:', error?.message);
      throw annotatePushError(error, 'create');
    }
  };

  // Update daily log via API. Same annotated-rejection contract as create.
  const updateDailyLog = async (logId, updates) => {
    try {
      return await dailyLogsAPI.update(logId, updates);
    } catch (error) {
      console.warn('Daily log update push failed:', error?.message);
      throw annotatePushError(error, 'update');
    }
  };

  // Delete daily log — no backend endpoint exists; kept for API compatibility.
  const deleteDailyLog = async (logId) => {
    console.warn('deleteDailyLog is not supported by the API');
  };

  // Get daily log by ID
  const getDailyLogById = async (logId) => {
    try {
      return await dailyLogsAPI.getById(logId);
    } catch (error) {
      console.error('Daily log not found:', error);
      return null;
    }
  };

  /**
   * OFFLINE vs EMPTY read of a project's daily logs.
   *
   * Returns { status: 'ok' | 'offline' | 'error', data, error } rather than a
   * bare array, because `[]` on failure is exactly the lie this app is trying
   * to kill: a dead zone must never render "No Logs Found". Callers may only
   * show an empty state when `status === 'ok'`.
   */
  const getProjectLogs = async (projectIdArg = null) => {
    const pid = projectIdArg || projectId;
    // No project selected is a genuine "nothing to show", not a failed read.
    if (!pid) return { status: 'ok', data: [], error: null };
    const r = await settleFetch(() => dailyLogsAPI.getByProject(pid));
    return {
      status: r.status,
      data: Array.isArray(r.data) ? r.data : [],
      error: r.error,
    };
  };

  // Get logs for a specific date range (filtered client-side from project logs)
  const getLogsByDateRange = async (startDate, endDate, projectIdArg = null) => {
    const pid = projectIdArg || projectId;
    if (!pid) return [];
    try {
      const logs = await dailyLogsAPI.getByProject(pid);
      const start = new Date(startDate).getTime();
      const end = new Date(endDate).getTime();
      return (logs || []).filter(l => {
        const t = new Date(l.date).getTime();
        return t >= start && t <= end;
      });
    } catch (error) {
      console.error('Failed to fetch logs by date range:', error);
      return [];
    }
  };

  // Get today's log for a project
  const getTodayLog = async (pid) => {
    try {
      const dateStr = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
      const log = await dailyLogsAPI.getByProjectAndDate(pid, dateStr);
      return log || null;
    } catch (error) {
      console.error('Failed to fetch today log:', error);
      return null;
    }
  };

  return {
    dailyLogs,
    loading,
    createDailyLog,
    updateDailyLog,
    deleteDailyLog,
    getDailyLogById,
    getProjectLogs,
    getLogsByDateRange,
    getTodayLog,
  };
}
