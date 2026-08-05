import { useState, useEffect } from 'react';
import { workersAPI } from '../utils/api';
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
      const data = await workersAPI.getAll();
      setWorkers(data || []);
    } catch (error) {
      console.error('Failed to fetch workers from API:', error);
      // Offline / API error — keep whatever is already in state.
    } finally {
      setLoading(false);
    }
  };

  const createWorker = async (workerData) => {
    try {
      // 1. Try API first
      const newWorker = await workersAPI.create(workerData);
      await fetchWorkers();
      return newWorker;
    } catch (error) {
      console.error('Failed to create worker online, queueing for sync:', error);

      // 2. If offline, queue for later sync
      await addToQueue({
        type: 'create',
        table: 'workers',
        data: workerData,
      });

      await fetchWorkers();
      throw error; // Let caller know it's pending
    }
  };

  const updateWorker = async (workerId, updates) => {
    try {
      // 1. Try API first
      await workersAPI.update(workerId, updates);
      await fetchWorkers();
    } catch (error) {
      console.error('Failed to update worker online, queueing for sync:', error);

      // 2. If offline, queue for later sync
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
      await fetchWorkers();
    } catch (error) {
      console.error('Failed to delete worker online, queueing for sync:', error);

      // 2. If offline, queue for later sync
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
      return await workersAPI.getById(workerId);
    } catch (error) {
      console.error('Failed to fetch worker from API:', error);
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
