import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { syncDatabase, acquireSyncLock, releaseSyncLock } from '../database/sync';
import { getToken } from './api';

const QUEUE_KEY = 'blueview_offline_queue';
const MAX_RETRIES = 3;

const API_URL = process.env.NEXT_PUBLIC_API_URL || process.env.EXPO_PUBLIC_API_URL || 'https://blueview2-production.up.railway.app';

/**
 * Offline queue item structure:
 * {
 *   id: string,
 *   type: 'create' | 'update' | 'delete',
 *   table: 'workers' | 'projects' | 'check_ins' | 'daily_logs',
 *   data: object,
 *   timestamp: number,
 *   retries: number,
 * }
 */

/**
 * Get current queue
 */
async function getQueue() {
  try {
    const queue = await AsyncStorage.getItem(QUEUE_KEY);
    return queue ? JSON.parse(queue) : [];
  } catch (error) {
    console.error('Failed to get queue:', error);
    return [];
  }
}

/**
 * Save queue
 */
async function saveQueue(queue) {
  try {
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch (error) {
    console.error('Failed to save queue:', error);
  }
}

/**
 * Add item to queue
 */
export async function addToQueue(item) {
  const queue = await getQueue();
  queue.push({
    ...item,
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    timestamp: Date.now(),
    retries: 0,
  });
  await saveQueue(queue);
  console.log(`📋 Added to offline queue: ${item.type} ${item.table}`);
}

/**
 * Map queue item to an API call
 */
async function processQueueItem(item, token) {
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };

  const tableEndpoints = {
    workers: '/api/workers',
    projects: '/api/projects',
    check_ins: '/api/checkins',
    daily_logs: '/api/daily-logs',
  };

  const endpoint = tableEndpoints[item.table];
  if (!endpoint) {
    throw new Error(`Unknown table: ${item.table}`);
  }

  let url = `${API_URL}${endpoint}`;
  let method = 'POST';

  if (item.type === 'update' && item.data._id) {
    url = `${url}/${item.data._id}`;
    method = 'PUT';
  } else if (item.type === 'delete' && item.data._id) {
    url = `${url}/${item.data._id}`;
    method = 'DELETE';
  }

  const response = await fetch(url, {
    method,
    headers,
    body: method !== 'DELETE' ? JSON.stringify(item.data) : undefined,
  });

  if (!response.ok) {
    const status = response.status;
    throw new Error(`API call failed with status ${status}`);
  }

  return await response.json();
}

/**
 * Process the queue - try to sync all pending items.
 * Coordinates with WatermelonDB sync via shared lock.
 */
export async function processQueue() {
  const state = await NetInfo.fetch();
  const isOnline = state.isConnected && state.isInternetReachable !== false;

  if (!isOnline) {
    console.log('❌ Cannot process queue - offline');
    return { success: false, processed: 0 };
  }

  const queue = await getQueue();

  if (queue.length === 0) {
    return { success: true, processed: 0 };
  }

  console.log(`📤 Processing ${queue.length} queued items...`);

  // Try database sync first (acquires its own lock)
  const syncResult = await syncDatabase();

  if (syncResult.success) {
    // Database sync handled the changes — clear the queue
    await saveQueue([]);
    console.log(`✅ Processed ${queue.length} items via sync`);
    return { success: true, processed: queue.length };
  }

  // Sync failed or was locked — process items individually via direct API calls
  const locked = await acquireSyncLock();
  if (!locked) {
    console.log('Sync lock held, deferring queue processing');
    return { success: false, processed: 0 };
  }

  try {
    const token = await getToken();
    if (!token) {
      return { success: false, processed: 0, error: 'no_token' };
    }

    const failedItems = [];
    let processedCount = 0;

    for (const item of queue) {
      if (item.retries >= MAX_RETRIES) {
        console.log(`⚠️ Max retries reached for item ${item.id}`);
        failedItems.push({ ...item, error: 'max_retries' });
        continue;
      }

      try {
        await processQueueItem(item, token);
        processedCount++;
      } catch (error) {
        console.error(`Failed to process item ${item.id}:`, error.message);
        failedItems.push({
          ...item,
          retries: item.retries + 1,
          lastError: error.message,
        });
      }
    }

    // Save only failed items back to queue
    await saveQueue(failedItems);

    return {
      success: failedItems.length === 0,
      processed: processedCount,
      failed: failedItems.length,
    };
  } finally {
    await releaseSyncLock();
  }
}

/**
 * Get queue size
 */
export async function getQueueSize() {
  const queue = await getQueue();
  return queue.length;
}

/**
 * Clear the queue
 */
export async function clearQueue() {
  await AsyncStorage.removeItem(QUEUE_KEY);
  console.log('🗑️ Queue cleared');
}

/**
 * Setup auto-processing when coming online.
 * Waits for connection to stabilize, then processes.
 */
export function setupAutoQueueProcessing() {
  let wasOffline = false;
  let reconnectTimer = null;

  const unsubscribe = NetInfo.addEventListener(async (state) => {
    const isCurrentlyOnline = state.isConnected && state.isInternetReachable !== false;

    if (wasOffline && isCurrentlyOnline) {
      console.log('📶 Back online - scheduling queue processing...');

      // Clear any pending timer
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }

      // Wait for connection to stabilize
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        const result = await processQueue();
        if (result.success) {
          console.log(`✅ Successfully processed ${result.processed} queued items`);
        } else if (result.failed) {
          console.log(`⚠️ Processed ${result.processed}, ${result.failed} failed`);
        }
      }, 2000);
    }

    wasOffline = !isCurrentlyOnline;
  });

  // Return cleanup function that also clears pending timer
  return () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    unsubscribe();
  };
}

/**
 * Get queue status for UI
 */
export async function getQueueStatus() {
  const queue = await getQueue();
  const state = await NetInfo.fetch();

  return {
    size: queue.length,
    isOnline: state.isConnected && state.isInternetReachable !== false,
    oldestItem: queue.length > 0 ? queue[0].timestamp : null,
    newestItem: queue.length > 0 ? queue[queue.length - 1].timestamp : null,
  };
}
