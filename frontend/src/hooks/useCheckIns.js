import { useState, useEffect } from 'react';
import database from '../database';
import { checkinsAPI } from '../utils/api';
import { Platform } from 'react-native';

const Q = Platform.OS !== 'web' ? require('@nozbe/watermelondb').Q : null;

export function useCheckIns() {
  const [checkIns, setCheckIns] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create check-in - API FIRST, then sync to WatermelonDB
  const createCheckIn = async (checkInData) => {
    try {
      // 1. Call backend API
      const result = await checkinsAPI.checkIn(checkInData);
      
      // 2. Save to WatermelonDB for offline access
      await database.write(async () => {
        await database.get('check_ins').create(checkIn => {
          checkIn.workerId = result.worker_id || checkInData.worker_id;
          checkIn.projectId = result.project_id || checkInData.project_id;
          checkIn.workerName = result.worker_name || '';
          checkIn.workerTrade = checkInData.worker_trade || '';
          checkIn.workerCompany = checkInData.worker_company || '';
          checkIn.projectName = result.project_name || '';
          checkIn.checkInTime = result.timestamp ? new Date(result.timestamp).getTime() : Date.now();
          checkIn.checkOutTime = null;
          checkIn.nfcTagId = checkInData.tag_id || '';
          checkIn.backendId = result.id || '';
          checkIn.isDeleted = false;
          checkIn.syncStatus = 'synced';
        });
      });

      return result;
    } catch (error) {
      console.error('Check-in failed:', error);
      
      // If API fails (offline), save to WatermelonDB and queue for sync
      await database.write(async () => {
        await database.get('check_ins').create(checkIn => {
          checkIn.workerId = checkInData.worker_id || '';
          checkIn.projectId = checkInData.project_id || '';
          checkIn.workerName = checkInData.worker_name || '';
          checkIn.workerTrade = checkInData.worker_trade || '';
          checkIn.workerCompany = checkInData.worker_company || '';
          checkIn.projectName = checkInData.project_name || '';
          checkIn.checkInTime = Date.now();
          checkIn.checkOutTime = null;
          checkIn.nfcTagId = checkInData.tag_id || '';
          checkIn.backendId = '';
          checkIn.isDeleted = false;
          checkIn.syncStatus = 'pending';
        });
      });

      throw error;
    }
  };

  // Check out - API FIRST
  const checkOut = async (checkInId) => {
    try {
      // 1. Call backend API
      await checkinsAPI.checkOut(checkInId);
      
      // 2. Update WatermelonDB
      await database.write(async () => {
        const checkIn = await database.get('check_ins').find(checkInId);
        await checkIn.update(c => {
          c.checkOutTime = Date.now();
          c.syncStatus = 'synced';
        });
      });
    } catch (error) {
      console.error('Check-out failed:', error);
      
      // If API fails, update locally and queue for sync
      await database.write(async () => {
        const checkIn = await database.get('check_ins').find(checkInId);
        await checkIn.update(c => {
          c.checkOutTime = Date.now();
          c.syncStatus = 'pending';
        });
      });

      throw error;
    }
  };

  // Get active check-ins - FROM API, sync to WatermelonDB
  const getActiveCheckIns = async (projectId = null) => {
    try {
      const apiCheckIns = await checkinsAPI.getActiveByProject(projectId);
      
      // Sync to WatermelonDB
      if (Platform.OS !== 'web') {
        await syncCheckInsToLocal(apiCheckIns);
      }
      
      return apiCheckIns;
    } catch (error) {
      console.error('Failed to fetch active check-ins from API, using local:', error);
      
      // Fallback to local
      const queryConditions = [
        Q.where('is_deleted', false),
        Q.where('check_out_time', null)
      ];
      
      if (projectId) {
        queryConditions.push(Q.where('project_id', projectId));
      }
      
      return await database.get('check_ins')
        .query(...queryConditions)
        .fetch();
    }
  };

  // Get today's check-ins - FROM API, sync to WatermelonDB
  const getTodayCheckIns = async (projectId = null, date = new Date()) => {
    try {
      let apiCheckIns;
      if (projectId) {
        apiCheckIns = await checkinsAPI.getTodayByProject(projectId);
      } else {
        apiCheckIns = await checkinsAPI.getByDate(date);
      }
      
      // Sync to WatermelonDB
     if (Platform.OS !== 'web') {
       await syncCheckInsToLocal(apiCheckIns);
     }
      
      return apiCheckIns;
    } catch (error) {
      console.error('Failed to fetch today check-ins from API, using local:', error);
      
      // Fallback to local
      const dayStart = new Date(date);
      dayStart.setHours(0, 0, 0, 0);
      const dayEnd = new Date(date);
      dayEnd.setHours(23, 59, 59, 999);

      const queryConditions = [
        Q.where('is_deleted', false),
        Q.where('check_in_time', Q.gte(dayStart.getTime())),
        Q.where('check_in_time', Q.lte(dayEnd.getTime()))
      ];
      
      if (projectId) {
        queryConditions.push(Q.where('project_id', projectId));
      }
      
      queryConditions.push(Q.sortBy('check_in_time', Q.desc));
      
      return await database.get('check_ins')
        .query(...queryConditions)
        .fetch();
    }
  };

  // Get check-ins by worker
  const getCheckInsByWorker = async (workerId) => {
    return await database.get('check_ins')
      .query(
        Q.where('is_deleted', false),
        Q.where('worker_id', workerId),
        Q.sortBy('check_in_time', Q.desc)
      )
      .fetch();
  };

  // Delete check-in (soft delete)
  const deleteCheckIn = async (checkInId) => {
    await database.write(async () => {
      const checkIn = await database.get('check_ins').find(checkInId);
      await checkIn.update(c => {
        c.isDeleted = true;
      });
    });
  };

  // Helper: Sync API check-ins to WatermelonDB
  const syncCheckInsToLocal = async (apiCheckIns) => {
    if (!Array.isArray(apiCheckIns) || apiCheckIns.length === 0) return;

    await database.write(async () => {
      for (const apiCheckIn of apiCheckIns) {
        const backendId = apiCheckIn._id || apiCheckIn.id;
        
        // Check if already exists locally
        const existing = await database.get('check_ins')
          .query(Q.where('backend_id', backendId))
          .fetch();

        if (existing.length === 0) {
          // Create new
          await database.get('check_ins').create(checkIn => {
            checkIn.workerId = apiCheckIn.worker_id || '';
            checkIn.projectId = apiCheckIn.project_id || '';
            checkIn.workerName = apiCheckIn.worker_name || '';
            checkIn.workerTrade = apiCheckIn.worker_trade || '';
            checkIn.workerCompany = apiCheckIn.worker_company || '';
            checkIn.projectName = apiCheckIn.project_name || '';
            checkIn.checkInTime = apiCheckIn.check_in_time 
              ? new Date(apiCheckIn.check_in_time).getTime() 
              : Date.now();
            checkIn.checkOutTime = apiCheckIn.check_out_time 
              ? new Date(apiCheckIn.check_out_time).getTime() 
              : null;
            checkIn.nfcTagId = apiCheckIn.nfc_tag_id || '';
            checkIn.backendId = backendId;
            checkIn.isDeleted = false;
            checkIn.syncStatus = 'synced';
          });
        } else {
          // Update existing
          await existing[0].update(checkIn => {
            checkIn.workerName = apiCheckIn.worker_name || checkIn.workerName;
            checkIn.workerTrade = apiCheckIn.worker_trade || checkIn.workerTrade;
            checkIn.workerCompany = apiCheckIn.worker_company || checkIn.workerCompany;
            checkIn.projectName = apiCheckIn.project_name || checkIn.projectName;
            if (apiCheckIn.check_out_time) {
              checkIn.checkOutTime = new Date(apiCheckIn.check_out_time).getTime();
            }
            checkIn.syncStatus = 'synced';
          });
        }
      }
    });
  };

  return {
    checkIns,
    loading,
    createCheckIn,
    checkOut,
    getActiveCheckIns,
    getTodayCheckIns,
    getCheckInsByWorker,
    deleteCheckIn,
  };
}
