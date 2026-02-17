// ============================================
// CRITICAL: Polyfill for crypto.subtle
// ============================================
// WatermelonDB requires crypto.subtle which is not available in all browsers
// This polyfill prevents the "Cannot read properties of undefined (reading 'subtle')" error

if (typeof window !== 'undefined') {
  // Check if we're missing crypto or crypto.subtle
  const needsPolyfill = !window.crypto || !window.crypto.subtle;
  
  if (needsPolyfill) {
    console.warn('⚠️ crypto.subtle not available, using polyfill');
    
    // Ensure window.crypto exists
    if (!window.crypto) {
      window.crypto = {};
    }
    
    // Simple hash function as fallback
    const simpleHash = async (str) => {
      const encoder = new TextEncoder();
      const data = encoder.encode(str);
      let hash = 0;
      for (let i = 0; i < data.length; i++) {
        hash = ((hash << 5) - hash) + data[i];
        hash = hash & hash; // Convert to 32bit integer
      }
      // Return as ArrayBuffer-like object
      const buffer = new ArrayBuffer(32);
      const view = new DataView(buffer);
      view.setInt32(0, hash);
      return buffer;
    };
    
    // Minimal polyfill for crypto.subtle
    window.crypto.subtle = {
      digest: async (algorithm, data) => {
        try {
          // Convert data to string for hashing
          let str;
          if (typeof data === 'string') {
            str = data;
          } else if (data instanceof ArrayBuffer) {
            str = new TextDecoder().decode(data);
          } else if (data instanceof Uint8Array) {
            str = new TextDecoder().decode(data);
          } else {
            str = JSON.stringify(data);
          }
          
          return await simpleHash(str);
        } catch (error) {
          console.error('Polyfill digest error:', error);
          // Return empty buffer on error
          return new ArrayBuffer(32);
        }
      }
    };
    
    // Also add getRandomValues if missing (often used with subtle)
    if (!window.crypto.getRandomValues) {
      window.crypto.getRandomValues = (array) => {
        for (let i = 0; i < array.length; i++) {
          array[i] = Math.floor(Math.random() * 256);
        }
        return array;
      };
    }
  }
}

import { Database } from '@nozbe/watermelondb'
import LokiJSAdapter from '@nozbe/watermelondb/adapters/lokijs'
import schema from './schema'
import Worker from './models/Worker'
import Project from './models/Project'
import CheckIn from './models/CheckIn'
import DailyLog from './models/DailyLog'
import NfcTag from './models/NfcTag'

const adapter = new LokiJSAdapter({
  schema,
  useWebWorker: false,
  useIncrementalIndexedDB: true,
  dbName: 'blueview',
  onSetUpError: (error) => {
    console.error('Database setup error:', error)
  }
})

const database = new Database({
  adapter,
  modelClasses: [Worker, Project, CheckIn, DailyLog, NfcTag],
})

export default database
