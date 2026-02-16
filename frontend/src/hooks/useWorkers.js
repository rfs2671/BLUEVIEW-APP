import { useState, useEffect } from 'react';
import { Q } from '@nozbe/watermelondb';
import database from '../database';
import { workersAPI } from '../utils/api';

export function useWorkers() {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const workersCollection = database.get('workers');
    
    const subscription = workersCollection
      .query(
        Q.where('is_deleted', false),
        Q.sortBy('name', Q.asc)
      )
      .observe()
      .subscribe(workers => {
        setWorkers(workers);
        setLoading(false);
      });

    return () => subscription.unsubscribe();
  }, []);

  const createWorker = async (workerData) => {
    await database.write(async () => {
      await database.get('workers').create(worker => {
        worker.name = workerData.name;
        worker.phone = workerData.phone || '';
        worker.trade = workerData.trade || '';
        worker.company = workerData.company || '';
        worker.oshaNumber = workerData.osha_number || '';
        worker.certificationsJSON = JSON.stringify(workerData.certifications || []);
        worker.backendId = workerData._id || '';
        worker.isDeleted = false;
        worker.syncStatus = 'pending';
      });
    });
  };

  const updateWorker = async (workerId, updates) => {
    await database.write(async () => {
      const worker = await database.get('workers').find(workerId);
      await worker.update(w => {
        if (updates.name !== undefined) w.name = updates.name;
        if (updates.phone !== undefined) w.phone = updates.phone;
        if (updates.trade !== undefined) w.trade = updates.trade;
        if (updates.company !== undefined) w.company = updates.company;
        if (updates.osha_number !== undefined) w.oshaNumber = updates.osha_number;
        if (updates.certifications !== undefined) {
          w.certificationsJSON = JSON.stringify(updates.certifications);
        }
      });
    });
  };

  const deleteWorker = async (workerId) => {
    await database.write(async () => {
      const worker = await database.get('workers').find(workerId);
      await worker.update(w => {
        w.isDeleted = true;
      });
    });
  };

  const getWorkerById = async (workerId) => {
    try {
      // 1. Try local storage first
      return await database.get('workers').find(workerId);
    } catch (error) {
      console.log('Worker not found locally, fetching from API...');
      try {
        // 2. Fallback to live API if local record doesn't exist yet
        const remoteWorker = await workersAPI.getById(workerId);
        return {
          ...remoteWorker,
          // Normalize field names to match what the UI expects
          oshaNumber: remoteWorker.osha_number || remoteWorker.oshaNumber,
          certifications: remoteWorker.certifications || JSON.parse(remoteWorker.certificationsJSON || '[]')
        };
      } catch (apiError) {
        console.error('Worker not found in DB or API:', apiError);
        return null;
      }
    }
  };

  const searchWorkers = async (query) => {
    const results = await database.get('workers')
      .query(
        Q.where('is_deleted', false),
        Q.or(
          Q.where('name', Q.like(`%${Q.sanitizeLikeString(query)}%`)),
          Q.where('company', Q.like(`%${Q.sanitizeLikeString(query)}%`)),
          Q.where('trade', Q.like(`%${Q.sanitizeLikeString(query)}%`))
        )
      )
      .fetch();
    return results;
  };

  return {
    workers,
    loading,
    createWorker,
    updateWorker,
    deleteWorker,
    getWorkerById,
    searchWorkers,
  };
}
