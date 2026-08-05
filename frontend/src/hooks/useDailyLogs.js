import { useState } from 'react';
import { dailyLogsAPI } from '../utils/api';

export function useDailyLogs(projectId = null) {
  const [dailyLogs, setDailyLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create daily log via API
  const createDailyLog = async (logData) => {
    return await dailyLogsAPI.create(logData);
  };

  // Update daily log via API
  const updateDailyLog = async (logId, updates) => {
    return await dailyLogsAPI.update(logId, updates);
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
    getLogsByDateRange,
    getTodayLog,
  };
}
