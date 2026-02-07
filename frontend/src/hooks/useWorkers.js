import { useState, useEffect } from 'react';
import { Q } from '@nozbe/watermelondb';
import database from '../database';

export function useWorkers() {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const workersCollection = database.get('workers');
    
    // Subscribe to workers (auto-updates on changes)
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

  // Create worker
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

  // Update worker
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

  // Delete worker (soft delete)
  const deleteWorker = async (workerId) => {
    await database.write(async () => {
      const worker = await database.get('workers').find(workerId);
      await worker.update(w => {
        w.isDeleted = true;
      });
    });
  };

  // Get worker by ID
  const getWorkerById = async (workerId) => {
    try {
      return await database.get('workers').find(workerId);
    } catch (error) {
      console.error('Worker not found:', error);
      return null;
    }
  };

  // Search workers
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
