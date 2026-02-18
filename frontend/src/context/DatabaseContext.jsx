import React, { createContext, useContext, useEffect, useState } from 'react';
import { Platform } from 'react-native';
import database from '../database';
import { syncDatabase, setupAutoSync } from '../database/sync';
import { setupAutoQueueProcessing, getQueueStatus } from '../utils/offlineQueue';
import { useNetworkStatus } from '../hooks/useNetworkStatus';

const WatermelonProvider = Platform.OS !== 'web' 
  ? require('@nozbe/watermelondb/DatabaseProvider').DatabaseProvider 
  : ({ children }) => children;

const DatabaseContext = createContext({});

export function DatabaseProvider({ children }) {
  const [isInitialized, setIsInitialized] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState(null);
  const [queueStatus, setQueueStatus] = useState({ size: 0, isOnline: false });
  const { isOnline } = useNetworkStatus();

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
        const status = await getQueueStatus();
        setQueueStatus(status);
        console.log('✅ Database initialized');
      } catch (error) {
        console.error('❌ Database initialization failed:', error);
        setIsInitialized(true);
      }
    };
    initialize();
    return () => {
      if (autoSyncUnsubscribe) autoSyncUnsubscribe();
      if (autoQueueUnsubscribe) autoQueueUnsubscribe();
    };
  }, []);

  useEffect(() => {
    const updateQueue = async () => {
      const status = await getQueueStatus();
      setQueueStatus(status);
    };
    updateQueue();
  }, [isOnline]);

  const performSync = async () => {
    if (!isOnline) return { success: false, error: 'offline' };
    if (isSyncing) return { success: false, error: 'already_syncing' };
    setIsSyncing(true);
    try {
      const result = await syncDatabase();
      if (result.success) {
        setLastSyncTime(new Date());
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

  const value = { database, isInitialized, isSyncing, lastSyncTime, queueStatus, performSync };

  if (!isInitialized) return null;

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
} // ← this closing brace was missing

export function useDatabase() {
  const context = useContext(DatabaseContext);
  if (!context) {
    throw new Error('useDatabase must be used within DatabaseProvider');
  }
  return context;
}
