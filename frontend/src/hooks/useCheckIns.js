import { useState } from 'react';
import { checkinsAPI } from '../utils/api';

export function useCheckIns() {
  const [checkIns, setCheckIns] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create check-in via API
  const createCheckIn = async (checkInData) => {
    return await checkinsAPI.checkIn(checkInData);
  };

  // Check out via API
  const checkOut = async (checkInId) => {
    await checkinsAPI.checkOut(checkInId);
  };

  // Get active check-ins from API
  const getActiveCheckIns = async (projectId = null) => {
    try {
      return await checkinsAPI.getActiveByProject(projectId);
    } catch (error) {
      console.error('Failed to fetch active check-ins:', error);
      return [];
    }
  };

  // Get today's check-ins from API
  const getTodayCheckIns = async (projectId = null, date = new Date()) => {
    try {
      if (projectId) {
        return await checkinsAPI.getTodayByProject(projectId);
      }
      return await checkinsAPI.getByDate(date);
    } catch (error) {
      console.error('Failed to fetch today check-ins:', error);
      return [];
    }
  };

  // Get check-ins by worker (filtered client-side from the check-ins list)
  const getCheckInsByWorker = async (workerId) => {
    try {
      const all = await checkinsAPI.getAll();
      return (all || []).filter(c => c.worker_id === workerId || c.workerId === workerId);
    } catch (error) {
      console.error('Failed to fetch check-ins by worker:', error);
      return [];
    }
  };

  // Delete check-in — no backend endpoint exists; kept for API compatibility.
  const deleteCheckIn = async (checkInId) => {
    console.warn('deleteCheckIn is not supported by the API');
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
