import React, { createContext, useContext, useEffect, useState } from 'react';
import { Platform } from 'react-native';
import { DatabaseProvider as WatermelonProvider } from '@nozbe/watermelondb/DatabaseProvider';
import database from '../database';
import { syncDatabase, setupAutoSync } from '../database/sync';
import { setupAutoQueueProcessing, getQueueStatus } from '../utils/offlineQueue';
import { useNetworkStatus } from '../hooks/useNetworkStatus';

const DatabaseContext = createContext({});

export function DatabaseProvider({ children }) {
  const [isInitialized, setIsInitialized] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState(null);
  const [queueStatus, setQueueStatus] = useState({ size: 0, isOnline: false });
  const { isOnline } = useNetworkStatus();

  // Initialize database and sync
  useEffect(() => {
    let autoSyncUnsubscribe;
    let autoQueueUnsubscribe;

    const initialize = async () => {
      try {
        console.log('🗄️ Initializing database...');
        setIsInitialized(true);

        autoSyncUnsubscribe = Platform.OS !== 'web' ? setupAutoSync() : null;
        autoQueueUnsubscribe = Platform.OS !== 'web' ? setupAutoQueueProcessing() : null;
        
        if (Platform.OS !== 'web' && isOnline) {
          console.log('📶 Online - performing initial sync...');
          await performSync();
      }
        
        // Update queue status
        const status = await getQueueStatus();
        setQueueStatus(status);
        
        console.log('✅ Database initialized');
      } catch (error) {
        console.error('❌ Database initialization failed:', error);
        // Continue anyway - app can still work offline
        setIsInitialized(true);
      }
    };

    initialize();

    // Cleanup
    return () => {
      if (autoSyncUnsubscribe) autoSyncUnsubscribe();
      if (autoQueueUnsubscribe) autoQueueUnsubscribe();
    };
  }, []);

  // Update queue status when network status changes
  useEffect(() => {
    const updateQueue = async () => {
      const status = await getQueueStatus();
      setQueueStatus(status);
    };
    updateQueue();
  }, [isOnline]);

  // Manual sync function
  const performSync = async () => {
    if (!isOnline) {
      console.log('Cannot sync - offline');
      return { success: false, error: 'offline' };
    }

    if (isSyncing) {
      console.log('Sync already in progress');
      return { success: false, error: 'already_syncing' };
    }

    setIsSyncing(true);
    
    try {
      const result = await syncDatabase();
      
      if (result.success) {
        setLastSyncTime(new Date());
        
        // Update queue status after sync
        const status = await getQueueStatus();
        setQueueStatus(status);
      }
      
      return result;
    } catch (error) {
      console.error('Sync error:', error);
      return { success: false, error: error.message };
    } finally {
      setIsSyncing(false);
    }
  };

  const value = {
    database,
    isInitialized,
    isSyncing,
    lastSyncTime,
    queueStatus,
    performSync,
  };

  if (!isInitialized) {
    // Show loading state while initializing
    return null; // Or a loading spinner component
  }
  
  return (
  <DatabaseContext.Provider value={value}>
    {Platform.OS === 'web' ? (
      children
    ) : (
      <WatermelonProvider database={database}>
        {children}
      </WatermelonProvider>
    )}
  </DatabaseContext.Provider>
);

// Custom hook to use database context
export function useDatabase() {
  const context = useContext(DatabaseContext);
  if (!context) {
    throw new Error('useDatabase must be used within DatabaseProvider');
  }
  return context;
}
