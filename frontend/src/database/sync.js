import { synchronize } from '@nozbe/watermelondb/sync';
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import database from './index';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'https://blueview2-production.up.railway.app';
const LAST_SYNC_KEY = 'blueview_last_sync';

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

  try {
    await synchronize({
      database,
      
      // Pull changes from server
      pullChanges: async ({ lastPulledAt, schemaVersion, migration }) => {
        const timestamp = lastPulledAt || (await getLastSyncTimestamp());
        
        const response = await fetch(`${API_URL}/api/sync/pull`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            lastPulledAt: timestamp,
            schemaVersion,
            migration 
          }),
        });

        if (!response.ok) {
          throw new Error('Pull failed');
        }

        const { changes, timestamp: newTimestamp } = await response.json();
        
        return { changes, timestamp: newTimestamp };
      },

      // Push local changes to server
      pushChanges: async ({ changes, lastPulledAt }) => {
        const response = await fetch(`${API_URL}/api/sync/push`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            changes,
            lastPulledAt 
          }),
        });

        if (!response.ok) {
          throw new Error('Push failed');
        }
      },

      // Handle migration conflicts
    });

    await setLastSyncTimestamp(Date.now());
    
    console.log('✅ Sync successful');
    return { success: true };
    
  } catch (error) {
    console.error('❌ Sync failed:', error);
    return { success: false, error: error.message };
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
 * Format changes for backend
 */
export function formatChangesForBackend(changes) {
  const formatted = {};
  
  Object.keys(changes).forEach(table => {
    formatted[table] = {
      created: changes[table].created.map(record => ({
        id: record.id,
        ...record._raw,
      })),
      updated: changes[table].updated.map(record => ({
        id: record.id,
        ...record._raw,
      })),
      deleted: changes[table].deleted,
    };
  });
  
  return formatted;
}

/**
 * Clear all local data (use with caution)
 */
export async function clearLocalDatabase() {
  await database.write(async () => {
    await database.unsafeResetDatabase();
  });
  await AsyncStorage.removeItem(LAST_SYNC_KEY);
}
