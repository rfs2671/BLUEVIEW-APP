import React, { createContext, useContext, useEffect, useState } from 'react';
import { setupAutoQueueProcessing, getQueueStatus, processQueue } from '../utils/offlineQueue';
import { useNetworkStatus } from '../hooks/useNetworkStatus';

// AsyncStorage-only offline context. WatermelonDB was removed (it was
// dormant on native); offline now runs entirely on AsyncStorage via
// offlineQueue. This provider exposes the same shape its consumers
// (OfflineIndicator, SyncButton) already read — queueStatus, performSync,
// isSyncing, lastSyncTime — so nothing downstream changes.
const DatabaseContext = createContext({});

export function DatabaseProvider({ children }) {
  // ✅ ALL HOOKS MUST BE CALLED AT TOP LEVEL, BEFORE ANY CONDITIONAL LOGIC
  const [isInitialized, setIsInitialized] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState(null);
  const [queueStatus, setQueueStatus] = useState({ size: 0, isOnline: false });
  const { isOnline } = useNetworkStatus(); // ✅ Hook called at top level

  // Initialize offline queue processing on mount
  useEffect(() => {
    let autoQueueUnsubscribe;

    const initialize = async () => {
      try {
        console.log('🗄️ Initializing offline store...');
        autoQueueUnsubscribe = setupAutoQueueProcessing();

        if (isOnline) {
          console.log('📶 Online - draining offline queue...');
          await performSync();
        }

        const status = await getQueueStatus();
        setQueueStatus(status);
        console.log('✅ Offline store initialized');
      } catch (error) {
        console.error('❌ Offline store initialization failed:', error);
      } finally {
        // ✅ Set initialized AFTER all async operations complete
        setIsInitialized(true);
      }
    };

    initialize();

    return () => {
      if (autoQueueUnsubscribe) autoQueueUnsubscribe();
    };
  }, [isOnline]); // Re-run when online status changes

  // Update queue status when network status changes
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
      const result = await processQueue();
      if (result.success) {
        setLastSyncTime(new Date());
      }
      const status = await getQueueStatus();
      setQueueStatus(status);
      return result.success
        ? { success: true }
        : { success: false, error: result.error || 'sync_failed' };
    } catch (error) {
      console.error('Sync error:', error);
      return { success: false, error: error.message };
    } finally {
      setIsSyncing(false);
    }
  };

  const value = { isInitialized, isSyncing, lastSyncTime, queueStatus, performSync };

  return (
    <DatabaseContext.Provider value={value}>
      {children}
    </DatabaseContext.Provider>
  );
}

/**
 * Hook to access database context
 * Safe to use in any component within DatabaseProvider
 */
export function useDatabaseContext() {
  const context = useContext(DatabaseContext);
  if (!context) {
    throw new Error('useDatabaseContext must be used within DatabaseProvider');
  }
  return context;
}
