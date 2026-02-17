import { useState, useEffect } from 'react';
import { workersAPI } from '../utils/api';
import database from '../database';
import { Q } from '@nozbe/watermelondb';
import { addToQueue } from '../utils/offlineQueue';

export function useWorkers() {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchWorkers();
  }, []);

  const fetchWorkers = async () => {
    try {
      setLoading(true);
      
      // 1. Try API first
      const data = await workersAPI.getAll();
      setWorkers(data || []);
      
      // 2. Sync to WatermelonDB for offline access
      await syncWorkersToLocal(data);
    } catch (error) {
      console.error('Failed to fetch from API, using local cache:', error);
      
      // 3. Fallback to WatermelonDB if offline
      const localWorkers = await database.get('workers')
        .query(Q.where('is_deleted', false))
        .fetch();
      
      setWorkers(localWorkers.map(w => ({
        _id: w.backendId || w.id,
        id: w.backendId || w.id,
        name: w.name,
        phone: w.phone,
        trade: w.trade,
        company: w.company,
        osha_number: w.oshaNumber,
        certifications: w.certifications,
      })));
    } finally {
      setLoading(false);
    }
  };

  const createWorker = async (workerData) => {
    try {
      // 1. Try API first
      const newWorker = await workersAPI.create(workerData);
      
      // 2. Save to WatermelonDB
      await database.write(async () => {
        await database.get('workers').create(worker => {
          worker.name = workerData.name;
          worker.phone = workerData.phone || '';
          worker.trade = workerData.trade || '';
          worker.company = workerData.company || '';
          worker.oshaNumber = workerData.osha_number || '';
          worker.certificationsJSON = JSON.stringify(workerData.certifications || []);
          worker.backendId = newWorker._id || newWorker.id;
          worker.isDeleted = false;
          worker.syncStatus = 'synced';
        });
      });
      
      await fetchWorkers();
      return newWorker;
    } catch (error) {
      console.error('Failed to create worker online, saving offline:', error);
      
      // 3. If offline, save to WatermelonDB and queue
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
          worker.syncStatus = 'pending';
        });
      });
      
      // 4. Add to sync queue
      await addToQueue({
        type: 'create',
        table: 'workers',
        data: workerData,
        localId: localWorker.id,
      });
      
      await fetchWorkers();
      throw error; // Let caller know it's pending
    }
  };

  const updateWorker = async (workerId, updates) => {
    try {
      // 1. Try API first
      await workersAPI.update(workerId, updates);
      
      // 2. Update WatermelonDB
      const localWorkers = await database.get('workers')
        .query(Q.where('backend_id', workerId))
        .fetch();
      
      if (localWorkers.length > 0) {
        await database.write(async () => {
          await localWorkers[0].update(w => {
            if (updates.name !== undefined) w.name = updates.name;
            if (updates.phone !== undefined) w.phone = updates.phone;
            if (updates.trade !== undefined) w.trade = updates.trade;
            if (updates.company !== undefined) w.company = updates.company;
            if (updates.osha_number !== undefined) w.oshaNumber = updates.osha_number;
            if (updates.certifications !== undefined) {
              w.certificationsJSON = JSON.stringify(updates.certifications);
            }
            w.syncStatus = 'synced';
          });
        });
      }
      
      await fetchWorkers();
    } catch (error) {
      console.error('Failed to update worker online, queueing for sync:', error);
      
      // 3. If offline, update WatermelonDB and queue
      const localWorkers = await database.get('workers')
        .query(Q.where('backend_id', workerId))
        .fetch();
      
      if (localWorkers.length > 0) {
        await database.write(async () => {
          await localWorkers[0].update(w => {
            if (updates.name !== undefined) w.name = updates.name;
            if (updates.phone !== undefined) w.phone = updates.phone;
            if (updates.trade !== undefined) w.trade = updates.trade;
            if (updates.company !== undefined) w.company = updates.company;
            if (updates.osha_number !== undefined) w.oshaNumber = updates.osha_number;
            if (updates.certifications !== undefined) {
              w.certificationsJSON = JSON.stringify(updates.certifications);
            }
            w.syncStatus = 'pending';
          });
        });
      }
      
      // 4. Add to sync queue
      await addToQueue({
        type: 'update',
        table: 'workers',
        data: updates,
        id: workerId,
      });
      
      await fetchWorkers();
      throw error; // Let caller know it's pending
    }
  };

  const deleteWorker = async (workerId) => {
    try {
      // 1. Try API first
      await workersAPI.delete(workerId);
      
      // 2. Soft delete in WatermelonDB
      const localWorkers = await database.get('workers')
        .query(Q.where('backend_id', workerId))
        .fetch();
      
      if (localWorkers.length > 0) {
        await database.write(async () => {
          await localWorkers[0].update(w => {
            w.isDeleted = true;
            w.syncStatus = 'synced';
          });
        });
      }
      
      await fetchWorkers();
    } catch (error) {
      console.error('Failed to delete worker online, queueing for sync:', error);
      
      // 3. If offline, soft delete locally and queue
      const localWorkers = await database.get('workers')
        .query(Q.where('backend_id', workerId))
        .fetch();
      
      if (localWorkers.length > 0) {
        await database.write(async () => {
          await localWorkers[0].update(w => {
            w.isDeleted = true;
            w.syncStatus = 'pending';
          });
        });
      }
      
      // 4. Add to sync queue
      await addToQueue({
        type: 'delete',
        table: 'workers',
        id: workerId,
      });
      
      await fetchWorkers();
      throw error;
    }
  };

  const getWorkerById = async (workerId) => {
    try {
      // 1. Try API first
      return await workersAPI.getById(workerId);
    } catch (error) {
      console.error('Failed to fetch worker from API, checking local:', error);
      
      // 2. Fallback to WatermelonDB
      const localWorkers = await database.get('workers')
        .query(Q.where('backend_id', workerId))
        .fetch();
      
      if (localWorkers.length > 0) {
        const w = localWorkers[0];
        return {
          _id: w.backendId,
          id: w.backendId,
          name: w.name,
          phone: w.phone,
          trade: w.trade,
          company: w.company,
          osha_number: w.oshaNumber,
          certifications: w.certifications,
        };
      }
      
      return null;
    }
  };

  const searchWorkers = async (query) => {
    if (!query) return workers;
    
    const lowerQuery = query.toLowerCase();
    return workers.filter(w => 
      w.name?.toLowerCase().includes(lowerQuery) ||
      w.company?.toLowerCase().includes(lowerQuery) ||
      w.trade?.toLowerCase().includes(lowerQuery)
    );
  };

  // Helper: Sync API workers to WatermelonDB
  const syncWorkersToLocal = async (apiWorkers) => {
    if (!Array.isArray(apiWorkers) || apiWorkers.length === 0) return;

    await database.write(async () => {
      for (const apiWorker of apiWorkers) {
        const backendId = apiWorker._id || apiWorker.id;
        
        // Check if already exists locally
        const existing = await database.get('workers')
          .query(Q.where('backend_id', backendId))
          .fetch();

        if (existing.length === 0) {
          // Create new
          await database.get('workers').create(worker => {
            worker.name = apiWorker.name || '';
            worker.phone = apiWorker.phone || '';
            worker.trade = apiWorker.trade || '';
            worker.company = apiWorker.company || '';
            worker.oshaNumber = apiWorker.osha_number || '';
            worker.certificationsJSON = JSON.stringify(apiWorker.certifications || []);
            worker.backendId = backendId;
            worker.isDeleted = false;
            worker.syncStatus = 'synced';
          });
        } else {
          // Update existing
          await existing[0].update(worker => {
            worker.name = apiWorker.name || worker.name;
            worker.phone = apiWorker.phone || worker.phone;
            worker.trade = apiWorker.trade || worker.trade;
            worker.company = apiWorker.company || worker.company;
            worker.oshaNumber = apiWorker.osha_number || worker.oshaNumber;
            if (apiWorker.certifications) {
              worker.certificationsJSON = JSON.stringify(apiWorker.certifications);
            }
            worker.syncStatus = 'synced';
          });
        }
      }
    });
  };

  return {
    workers,
    loading,
    createWorker,
    updateWorker,
    deleteWorker,
    getWorkerById,
    searchWorkers,
    refreshWorkers: fetchWorkers,
  };
}
