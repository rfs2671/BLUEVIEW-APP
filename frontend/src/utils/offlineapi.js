import { Platform } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import database from '../database';
import { addToQueue } from './offlineQueue';
import { checkinsAPI } from './api';

const Q = Platform.OS !== 'web' ? require('@nozbe/watermelondb').Q : null;

/**
 * Check if device is online
 */
export async function isOnline() {
  const state = await NetInfo.fetch();
  return state.isConnected && state.isInternetReachable !== false;
}

/**
 * Offline-aware wrapper for API calls
 * If offline: uses local database
 * If online: uses API, updates local database
 */
export class OfflineAwareAPI {
  constructor(apiFunction, localFallback) {
    this.apiFunction = apiFunction;
    this.localFallback = localFallback;
  }

  async execute(...args) {
    const online = await isOnline();

    if (!online && this.localFallback) {
      // Use local database
      console.log('📵 Offline - using local database');
      return await this.localFallback(...args);
    }

    try {
      // Try API call
      const result = await this.apiFunction(...args);
      return result;
    } catch (error) {
      // If API fails and we have local fallback, use it
      if (this.localFallback) {
        console.log('⚠️ API failed - falling back to local database');
        return await this.localFallback(...args);
      }
      throw error;
    }
  }
}

/**
 * Helper: only use WatermelonDB queries on native where Q is available
 */
function requireNativeQ() {
  if (!Q) {
    throw new Error('WatermelonDB queries are not available on web');
  }
  return Q;
}

/**
 * Offline-aware Workers API
 */
export const offlineWorkersAPI = {
  getAll: new OfflineAwareAPI(
    // API function (will be replaced with actual API call)
    async () => {
      return [];
    },
    // Local fallback — only works on native
    Platform.OS !== 'web' ? async () => {
      const q = requireNativeQ();
      const workers = await database.get('workers')
        .query(q.where('is_deleted', false))
        .fetch();
      return workers.map(w => ({
        _id: w.backendId || w.id,
        name: w.name,
        phone: w.phone,
        trade: w.trade,
        company: w.company,
        osha_number: w.oshaNumber,
        certifications: w.certifications,
      }));
    } : null
  ),

  create: async (workerData) => {
    const online = await isOnline();

    if (Platform.OS !== 'web') {
      // Always save to local database first on native
      let localWorker;
      await database.write(async () => {
        localWorker = await database.get('workers').create(worker => {
          worker.name = workerData.name;
          worker.phone = workerData.phone || '';
          worker.trade = workerData.trade || '';
          worker.company = workerData.company || '';
          worker.oshaNumber = workerData.osha_number || '';
          worker.certificationsJSON = JSON.stringify(workerData.certifications || []);
          worker.backendId = '';
          worker.isDeleted = false;
        });
      });

      if (!online) {
        await addToQueue({
          type: 'create',
          table: 'workers',
          data: workerData,
          localId: localWorker.id,
        });
      }

      return localWorker;
    }

    // On web when offline, queue it
    if (!online) {
      await addToQueue({
        type: 'create',
        table: 'workers',
        data: workerData,
      });
      return { ...workerData, _id: `pending_${Date.now()}`, _pending: true };
    }

    return null; // Caller should use the regular API when online on web
  },
};

/**
 * Offline-aware Projects API
 */
export const offlineProjectsAPI = {
  getAll: new OfflineAwareAPI(
    async () => [],
    Platform.OS !== 'web' ? async () => {
      const q = requireNativeQ();
      const projects = await database.get('projects')
        .query(q.where('is_deleted', false))
        .fetch();
      return projects.map(p => ({
        _id: p.backendId || p.id,
        name: p.name,
        address: p.address,
        status: p.status,
        start_date: p.startDate ? new Date(p.startDate).toISOString() : null,
        end_date: p.endDate ? new Date(p.endDate).toISOString() : null,
      }));
    } : null
  ),
};

/**
 * Offline-aware Check-ins API
 */
export const offlineCheckInsAPI = {
  getTodayByProject: new OfflineAwareAPI(
    async () => [],
    Platform.OS !== 'web' ? async (projectId) => {
      const q = requireNativeQ();
      const todayStart = new Date();
      todayStart.setHours(0, 0, 0, 0);

      const checkIns = await database.get('check_ins')
        .query(
          q.where('is_deleted', false),
          q.where('project_id', projectId),
          q.where('check_in_time', q.gte(todayStart.getTime()))
        )
        .fetch();

      return checkIns.map(c => ({
        _id: c.backendId || c.id,
        worker_id: c.workerId,
        project_id: c.projectId,
        worker_name: c.workerName,
        worker_trade: c.workerTrade,
        worker_company: c.workerCompany,
        project_name: c.projectName,
        check_in_time: new Date(c.checkInTime).toISOString(),
        check_out_time: c.checkOutTime ? new Date(c.checkOutTime).toISOString() : null,
      }));
    } : null
  ),

  getActiveByProject: new OfflineAwareAPI(
    async () => [],
    Platform.OS !== 'web' ? async (projectId) => {
      const q = requireNativeQ();
      const checkIns = await database.get('check_ins')
        .query(
          q.where('is_deleted', false),
          q.where('project_id', projectId),
          q.where('check_out_time', null)
        )
        .fetch();

      return checkIns.map(c => ({
        _id: c.backendId || c.id,
        worker_name: c.workerName,
        check_in_time: new Date(c.checkInTime).toISOString(),
      }));
    } : null
  ),

  checkIn: async (checkInData) => {
    const online = await isOnline();

    if (Platform.OS !== 'web') {
      // Save to local database on native
      let localCheckIn;
      await database.write(async () => {
        localCheckIn = await database.get('check_ins').create(checkIn => {
          checkIn.workerId = checkInData.worker_id || '';
          checkIn.projectId = checkInData.project_id || '';
          checkIn.workerName = checkInData.worker_name || '';
          checkIn.workerTrade = checkInData.worker_trade || '';
          checkIn.workerCompany = checkInData.worker_company || '';
          checkIn.projectName = checkInData.project_name || '';
          checkIn.checkInTime = Date.now();
          checkIn.checkOutTime = null;
          checkIn.nfcTagId = checkInData.nfc_tag_id || '';
          checkIn.backendId = '';
          checkIn.isDeleted = false;
          checkIn.syncStatus = 'pending'; // Always pending until confirmed by server
        });
      });

      if (online) {
        // Try to sync immediately via API
        try {
          const result = await checkinsAPI.checkIn(checkInData);
          // Update local record with backend ID and mark synced
          await database.write(async () => {
            await localCheckIn.update(c => {
              c.backendId = result._id || result.id || '';
              c.syncStatus = 'synced';
            });
          });
        } catch (error) {
          console.log('API check-in failed, queued for sync:', error.message);
          await addToQueue({
            type: 'create',
            table: 'check_ins',
            data: checkInData,
            localId: localCheckIn.id,
          });
        }
      } else {
        await addToQueue({
          type: 'create',
          table: 'check_ins',
          data: checkInData,
          localId: localCheckIn.id,
        });
      }

      return localCheckIn;
    }

    // Web path: use API directly when online, queue when offline
    if (online) {
      return await checkinsAPI.checkIn(checkInData);
    }

    await addToQueue({
      type: 'create',
      table: 'check_ins',
      data: checkInData,
    });
    return { ...checkInData, _id: `pending_${Date.now()}`, _pending: true };
  },

  checkOut: async (checkInId) => {
    const online = await isOnline();

    if (Platform.OS !== 'web') {
      // Update local database
      await database.write(async () => {
        const checkIn = await database.get('check_ins').find(checkInId);
        await checkIn.update(c => {
          c.checkOutTime = Date.now();
          c.syncStatus = 'pending'; // Always pending until confirmed
        });
      });

      if (online) {
        try {
          await checkinsAPI.checkOut(checkInId);
          await database.write(async () => {
            const checkIn = await database.get('check_ins').find(checkInId);
            await checkIn.update(c => {
              c.syncStatus = 'synced';
            });
          });
        } catch (error) {
          console.log('API check-out failed, queued for sync:', error.message);
          await addToQueue({
            type: 'update',
            table: 'check_ins',
            data: { _id: checkInId, check_out_time: new Date().toISOString() },
            localId: checkInId,
          });
        }
      } else {
        await addToQueue({
          type: 'update',
          table: 'check_ins',
          data: { _id: checkInId, check_out_time: new Date().toISOString() },
          localId: checkInId,
        });
      }

      return { success: true };
    }

    // Web path
    if (online) {
      return await checkinsAPI.checkOut(checkInId);
    }

    await addToQueue({
      type: 'update',
      table: 'check_ins',
      data: { _id: checkInId, check_out_time: new Date().toISOString() },
    });
    return { success: true, _pending: true };
  },
};

/**
 * Offline-aware Daily Logs API
 */
export const offlineDailyLogsAPI = {
  getAll: new OfflineAwareAPI(
    async () => [],
    Platform.OS !== 'web' ? async () => {
      const q = requireNativeQ();
      const logs = await database.get('daily_logs')
        .query(q.where('is_deleted', false))
        .fetch();
      return logs.map(l => ({
        _id: l.backendId || l.id,
        project_id: l.projectId,
        project_name: l.projectName,
        date: new Date(l.date).toISOString(),
        weather: l.weather,
        notes: l.notes,
        work_performed: l.workPerformed,
        materials_used: l.materialsUsed,
        issues: l.issues,
      }));
    } : null
  ),
};
