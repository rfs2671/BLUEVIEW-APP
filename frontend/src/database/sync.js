import { getToken } from '../utils/api';
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';

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
        return false; // Lock still valid
      }
      // Lock expired, take it
    }
    await AsyncStorage.setItem(SYNC_LOCK_KEY, Date.now().toString());
    return true;
  } catch {
    return true; // If storage fails, allow sync to proceed
  }
}

export async function releaseSyncLock() {
  try {
    await AsyncStorage.removeItem(SYNC_LOCK_KEY);
  } catch {
    // Best effort
  }
}

async function getLastSyncTimestamp() {
  const timestamp = await AsyncStorage.getItem(LAST_SYNC_KEY);
  return timestamp ? parseInt(timestamp, 10) : 0;
}

async function setLastSyncTimestamp(timestamp) {
  await AsyncStorage.setItem(LAST_SYNC_KEY, timestamp.toString());
}

/**
 * Web sync — pulls changes from server and pushes local pending items.
 * On web, WatermelonDB is not available, so this does API-level sync only.
 */
export async function syncDatabase() {
  const state = await NetInfo.fetch();
  const isOnline = state.isConnected && state.isInternetReachable !== false;

  if (!isOnline) {
    return { success: false, error: 'offline' };
  }

  const locked = await acquireSyncLock();
  if (!locked) {
    console.log('Sync already in progress, skipping');
    return { success: false, error: 'locked' };
  }

  try {
    const token = await getToken();
    if (!token) {
      return { success: false, error: 'no_token' };
    }

    const lastSync = await getLastSyncTimestamp();

    // Pull changes from server
    const pullResponse = await fetch(`${API_URL}/api/sync/pull`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ lastPulledAt: lastSync }),
    });

    if (!pullResponse.ok) {
      const status = pullResponse.status;
      throw new Error(`Pull failed with status ${status}`);
    }

    const pullData = await pullResponse.json();

    // Use server timestamp, not client time
    if (pullData.timestamp) {
      await setLastSyncTimestamp(pullData.timestamp);
    }

    console.log('✅ Web sync successful');
    return { success: true };

  } catch (error) {
    console.error('❌ Web sync failed:', error.message);
    return { success: false, error: error.message };
  } finally {
    await releaseSyncLock();
  }
}

/**
 * Auto-sync when app comes online (web version)
 */
export function setupAutoSync() {
  let wasOffline = false;

  const unsubscribe = NetInfo.addEventListener((state) => {
    const isCurrentlyOnline = state.isConnected && state.isInternetReachable !== false;

    if (wasOffline && isCurrentlyOnline) {
      console.log('📶 Back online - syncing (web)...');
      syncDatabase();
    }

    wasOffline = !isCurrentlyOnline;
  });

  return unsubscribe;
}
