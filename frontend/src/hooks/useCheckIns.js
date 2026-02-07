import { useState, useEffect } from 'react';
import { Q } from '@nozbe/watermelondb';
import database from '../database';

export function useCheckIns(projectId = null) {
  const [checkIns, setCheckIns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkInsCollection = database.get('check_ins');
    
    // Build query
    const queryConditions = [Q.where('is_deleted', false)];
    
    if (projectId) {
      queryConditions.push(Q.where('project_id', projectId));
    }
    
    queryConditions.push(Q.sortBy('check_in_time', Q.desc));

    // Subscribe to check-ins (auto-updates on changes)
    const subscription = checkInsCollection
      .query(...queryConditions)
      .observe()
      .subscribe(checkIns => {
        setCheckIns(checkIns);
        setLoading(false);
      });

    return () => subscription.unsubscribe();
  }, [projectId]);

  // Create check-in
  const createCheckIn = async (checkInData) => {
    await database.write(async () => {
      await database.get('check_ins').create(checkIn => {
        checkIn.workerId = checkInData.worker_id || '';
        checkIn.projectId = checkInData.project_id || '';
        checkIn.workerName = checkInData.worker_name || '';
        checkIn.workerTrade = checkInData.worker_trade || '';
        checkIn.workerCompany = checkInData.worker_company || '';
        checkIn.projectName = checkInData.project_name || '';
        checkIn.checkInTime = checkInData.check_in_time 
          ? new Date(checkInData.check_in_time).getTime() 
          : Date.now();
        checkIn.checkOutTime = checkInData.check_out_time 
          ? new Date(checkInData.check_out_time).getTime() 
          : null;
        checkIn.nfcTagId = checkInData.nfc_tag_id || '';
        checkIn.backendId = checkInData._id || '';
        checkIn.isDeleted = false;
        checkIn.syncStatus = 'pending';
      });
    });
  };

  // Check out
  const checkOut = async (checkInId) => {
    await database.write(async () => {
      const checkIn = await database.get('check_ins').find(checkInId);
      await checkIn.update(c => {
        c.checkOutTime = Date.now();
        c.syncStatus = 'pending';
      });
    });
  };

  // Get active check-ins (not checked out)
  const getActiveCheckIns = async (projectId = null) => {
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
  };

  // Get today's check-ins
  const getTodayCheckIns = async (projectId = null) => {
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    
    const queryConditions = [
      Q.where('is_deleted', false),
      Q.where('check_in_time', Q.gte(todayStart.getTime()))
    ];
    
    if (projectId) {
      queryConditions.push(Q.where('project_id', projectId));
    }
    
    queryConditions.push(Q.sortBy('check_in_time', Q.desc));
    
    return await database.get('check_ins')
      .query(...queryConditions)
      .fetch();
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
