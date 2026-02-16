import { useState, useEffect } from 'react';
import { workersAPI } from '../utils/api';

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
      console.error('Failed to fetch workers:', error);
      setWorkers([]);
    } finally {
      setLoading(false);
    }
  };

  const createWorker = async (workerData) => {
    const newWorker = await workersAPI.create(workerData);
    await fetchWorkers(); // Refresh list
    return newWorker;
  };

  const updateWorker = async (workerId, updates) => {
    await workersAPI.update(workerId, updates);
    await fetchWorkers(); // Refresh list
  };

  const deleteWorker = async (workerId) => {
    await workersAPI.delete(workerId);
    await fetchWorkers(); // Refresh list
  };

  const getWorkerById = async (workerId) => {
    try {
      return await workersAPI.getById(workerId);
    } catch (error) {
      console.error('Worker not found:', error);
      return null;
    }
  };

  const searchWorkers = async (query) => {
    // Client-side search since we have all workers
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
