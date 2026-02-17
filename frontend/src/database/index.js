if (typeof window !== 'undefined') {
  if (!window.crypto) {
    window.crypto = {};
  }
  if (!window.crypto.subtle) {
    // Create a minimal polyfill that WatermelonDB can use
    window.crypto.subtle = {
      digest: async (algorithm, data) => {
        // Fallback implementation using a simple hash
        const msgBuffer = new TextEncoder().encode(JSON.stringify(data));
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        return hashBuffer;
      }
    };
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
