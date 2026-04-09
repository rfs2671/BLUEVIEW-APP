import { getToken } from '../utils/api';
import { synchronize } from '@nozbe/watermelondb/sync';
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import database from './index';

const API_URL = process.env.NEXT_PUBLIC_API_URL || process.env.EXPO_PUBLIC_API_URL || 'https://blueview2-production.up.railway.app';
const LAST_SYNC_KEY = 'blueview_last_sync';
const SYNC_LOCK_KEY = 'blueview_sync_lock';

/**
 * Acquire a sync lock to prevent concurrent syncs (offline queue + db sync).
 * Returns true if lock acquired, false if another sync is in progress.
 * Lock auto-expires after 30 seconds to prevent deadlocks.
 */
export async function acquireSyncLock() {
  try {
    const existing = await AsyncStorage.getItem(SYNC_LOCK_KEY);
    if (existing) {
      const lockTime = parseInt(existing, 10);
      if (Date.now() - lockTime < 30000) {
        return false;
      }
    }
    await AsyncStorage.setItem(SYNC_LOCK_KEY, Date.now().toString());
    return true;
  } catch {
    return true;
  }
}

export async function releaseSyncLock() {
  try {
    await AsyncStorage.removeItem(SYNC_LOCK_KEY);
  } catch {
    // Best effort
  }
}

/**
 * Check if device is online
 */
export async function isOnline() {
  const state = await NetInfo.fetch();
  return state.isConnected && state.isInternetReachable !== false;
}

/**
 * Get last sync timestamp
 */
async function getLastSyncTimestamp() {
  const timestamp = await AsyncStorage.getItem(LAST_SYNC_KEY);
  return timestamp ? parseInt(timestamp, 10) : 0;
}

/**
 * Set last sync timestamp
 */
async function setLastSyncTimestamp(timestamp) {
  await AsyncStorage.setItem(LAST_SYNC_KEY, timestamp.toString());
}

/**
 * Main sync function - syncs local database with backend
 */
export async function syncDatabase() {
  const online = await isOnline();

  if (!online) {
    console.log('Cannot sync - device is offline');
    return { success: false, error: 'offline' };
  }

  const locked = await acquireSyncLock();
  if (!locked) {
    console.log('Sync already in progress, skipping');
    return { success: false, error: 'locked' };
  }

  try {
    let serverTimestamp = null;

    await synchronize({
      database,

      pullChanges: async ({ lastPulledAt, schemaVersion, migration }) => {
        const timestamp = lastPulledAt || (await getLastSyncTimestamp());
        const token = await getToken();

        if (!token) {
          throw new Error('No auth token available for sync');
        }

        const response = await fetch(`${API_URL}/api/sync/pull`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            lastPulledAt: timestamp,
            schemaVersion,
            migration
          }),
        });

        if (!response.ok) {
          const status = response.status;
          throw new Error(`Pull failed with status ${status}`);
        }

        const { changes, timestamp: newTimestamp } = await response.json();
        serverTimestamp = newTimestamp;
        return { changes, timestamp: newTimestamp };
      },

      pushChanges: async ({ changes, lastPulledAt }) => {
        const token = await getToken();

        if (!token) {
          throw new Error('No auth token available for sync');
        }

        const response = await fetch(`${API_URL}/api/sync/push`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            changes,
            lastPulledAt
          }),
        });

        if (!response.ok) {
          const status = response.status;
          throw new Error(`Push failed with status ${status}`);
        }
      },
    });

    // Use server timestamp instead of client time to prevent drift
    if (serverTimestamp) {
      await setLastSyncTimestamp(serverTimestamp);
    }

    console.log('✅ Sync successful');
    return { success: true };

  } catch (error) {
    console.error('❌ Sync failed:', error.message);
    return { success: false, error: error.message };
  } finally {
    await releaseSyncLock();
  }
}

/**
 * Auto-sync when app comes online
 */
export function setupAutoSync() {
  let wasOffline = false;

  const unsubscribe = NetInfo.addEventListener(state => {
    const isCurrentlyOnline = state.isConnected && state.isInternetReachable !== false;

    // If we just came back online, sync
    if (wasOffline && isCurrentlyOnline) {
      console.log('📶 Back online - syncing...');
      syncDatabase();
    }

    wasOffline = !isCurrentlyOnline;
  });

  return unsubscribe;
}

/**
 * Clear all local data (use with caution)
 */
export async function clearLocalDatabase() {
  try {
    await database.write(async () => {
      await database.unsafeResetDatabase();
    });
    await AsyncStorage.removeItem(LAST_SYNC_KEY);
  } catch (error) {
    console.error('Failed to clear local database:', error);
    throw error;
  }
}
