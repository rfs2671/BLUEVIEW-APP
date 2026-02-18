/**
 * Offline-aware API wrapper
 * Automatically uses local database when offline
 * Queues changes for sync when back online
 */
import NetInfo from '@react-native-community/netinfo';
import database from '../database';
import { addToQueue } from './offlineQueue';

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
 * Offline-aware Workers API
 */
export const offlineWorkersAPI = {
  getAll: new OfflineAwareAPI(
    // API function (will be replaced with actual API call)
    async () => {
      // This will be the original API call
      return [];
    },
    // Local fallback
    async () => {
      const workers = await database.get('workers')
        .query(Q.where('is_deleted', false))
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
    }
  ),

  create: async (workerData) => {
    const online = await isOnline();
    
    // Always save to local database first
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
      // Queue for sync
      await addToQueue({
        type: 'create',
        table: 'workers',
        data: workerData,
        localId: localWorker.id,
      });
    }

    return localWorker;
  },
};

/**
 * Offline-aware Projects API
 */
export const offlineProjectsAPI = {
  getAll: new OfflineAwareAPI(
    async () => [],
    async () => {
      const projects = await database.get('projects')
        .query(Q.where('is_deleted', false))
        .fetch();
      return projects.map(p => ({
        _id: p.backendId || p.id,
        name: p.name,
        address: p.address,
        status: p.status,
        start_date: p.startDate ? new Date(p.startDate).toISOString() : null,
        end_date: p.endDate ? new Date(p.endDate).toISOString() : null,
      }));
    }
  ),
};

/**
 * Offline-aware Check-ins API
 */
export const offlineCheckInsAPI = {
  getTodayByProject: new OfflineAwareAPI(
    async () => [],
    async (projectId) => {
      const todayStart = new Date();
      todayStart.setHours(0, 0, 0, 0);
      
      const checkIns = await database.get('check_ins')
        .query(
          Q.where('is_deleted', false),
          Q.where('project_id', projectId),
          Q.where('check_in_time', Q.gte(todayStart.getTime()))
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
    }
  ),

  getActiveByProject: new OfflineAwareAPI(
    async () => [],
    async (projectId) => {
      const checkIns = await database.get('check_ins')
        .query(
          Q.where('is_deleted', false),
          Q.where('project_id', projectId),
          Q.where('check_out_time', null)
        )
        .fetch();
      
      return checkIns.map(c => ({
        _id: c.backendId || c.id,
        worker_name: c.workerName,
        check_in_time: new Date(c.checkInTime).toISOString(),
      }));
    }
  ),

  checkIn: async (checkInData) => {
    const online = await isOnline();
    
    // Save to local database
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
        checkIn.syncStatus = online ? 'synced' : 'pending';
      });
    });

    if (!online) {
      await addToQueue({
        type: 'create',
        table: 'check_ins',
        data: checkInData,
        localId: localCheckIn.id,
      });
    }

    return localCheckIn;
  },

  checkOut: async (checkInId) => {
    const online = await isOnline();
    
    // Update local database
    await database.write(async () => {
      const checkIn = await database.get('check_ins').find(checkInId);
      await checkIn.update(c => {
        c.checkOutTime = Date.now();
        c.syncStatus = online ? 'synced' : 'pending';
      });
    });

    if (!online) {
      await addToQueue({
        type: 'update',
        table: 'check_ins',
        data: { check_out_time: new Date().toISOString() },
        localId: checkInId,
      });
    }

    return { success: true };
  },
};

/**
 * Offline-aware Daily Logs API
 */
export const offlineDailyLogsAPI = {
  getAll: new OfflineAwareAPI(
    async () => [],
    async () => {
      const logs = await database.get('daily_logs')
        .query(Q.where('is_deleted', false))
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
    }
  ),
};
