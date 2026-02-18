import { useState, useEffect } from 'react';
import database from '../database';
import { Platform } from 'react-native'

const Q = Platform.OS !== 'web' ? require('@nozbe/watermelondb').Q : null;

export function useDailyLogs(projectId = null) {
  const [dailyLogs, setDailyLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create daily log
  const createDailyLog = async (logData) => {
    await database.write(async () => {
      await database.get('daily_logs').create(log => {
        log.projectId = logData.project_id || '';
        log.projectName = logData.project_name || '';
        log.date = logData.date ? new Date(logData.date).getTime() : Date.now();
        log.weather = logData.weather || '';
        log.notes = logData.notes || '';
        log.workPerformed = logData.work_performed || '';
        log.materialsUsed = logData.materials_used || '';
        log.issues = logData.issues || '';
        log.backendId = logData._id || '';
        log.isDeleted = false;
        log.syncStatus = 'pending';
      });
    });
  };

  // Update daily log
  const updateDailyLog = async (logId, updates) => {
    await database.write(async () => {
      const log = await database.get('daily_logs').find(logId);
      await log.update(l => {
        if (updates.date !== undefined) {
          l.date = new Date(updates.date).getTime();
        }
        if (updates.weather !== undefined) l.weather = updates.weather;
        if (updates.notes !== undefined) l.notes = updates.notes;
        if (updates.work_performed !== undefined) l.workPerformed = updates.work_performed;
        if (updates.materials_used !== undefined) l.materialsUsed = updates.materials_used;
        if (updates.issues !== undefined) l.issues = updates.issues;
        l.syncStatus = 'pending';
      });
    });
  };

  // Delete daily log (soft delete)
  const deleteDailyLog = async (logId) => {
    await database.write(async () => {
      const log = await database.get('daily_logs').find(logId);
      await log.update(l => {
        l.isDeleted = true;
      });
    });
  };

  // Get daily log by ID
  const getDailyLogById = async (logId) => {
    try {
      return await database.get('daily_logs').find(logId);
    } catch (error) {
      console.error('Daily log not found:', error);
      return null;
    }
  };

  // Get logs for a specific date range
  const getLogsByDateRange = async (startDate, endDate, projectId = null) => {
    const queryConditions = [
      Q.where('is_deleted', false),
      Q.where('date', Q.gte(new Date(startDate).getTime())),
      Q.where('date', Q.lte(new Date(endDate).getTime()))
    ];
    
    if (projectId) {
      queryConditions.push(Q.where('project_id', projectId));
    }
    
    queryConditions.push(Q.sortBy('date', Q.desc));
    
    return await database.get('daily_logs')
      .query(...queryConditions)
      .fetch();
  };

  // Get today's log for a project
  const getTodayLog = async (projectId) => {
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    
    const todayEnd = new Date();
    todayEnd.setHours(23, 59, 59, 999);
    
    const logs = await database.get('daily_logs')
      .query(
        Q.where('is_deleted', false),
        Q.where('project_id', projectId),
        Q.where('date', Q.gte(todayStart.getTime())),
        Q.where('date', Q.lte(todayEnd.getTime()))
      )
      .fetch();
    
    return logs.length > 0 ? logs[0] : null;
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
