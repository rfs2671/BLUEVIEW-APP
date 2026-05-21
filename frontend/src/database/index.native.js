import { Platform } from 'react-native';

let database;

if (Platform.OS !== 'web') {
  const { Database } = require('@nozbe/watermelondb');
  const LokiJSAdapter = require('@nozbe/watermelondb/adapters/lokijs').default;
  const schema = require('./schema').default;
  const migrations = require('./migrations').default;
  const Worker = require('./models/Worker').default;
  const Project = require('./models/Project').default;
  const CheckIn = require('./models/CheckIn').default;
  const DailyLog = require('./models/DailyLog').default;
  const NfcTag = require('./models/NfcTag').default;

  const adapter = new LokiJSAdapter({
    schema,
    // Phase 1 Week 3 PR-B — apply v1 → v2 migration on app reload
    // (adds daily_logs.phase column). WatermelonDB compares on-device
    // schema version to schema.version and runs missing steps.
    migrations,
    useWebWorker: false,
    useIncrementalIndexedDB: true,
    dbName: 'blueview',
    onSetUpError: (error) => {
      console.error('Database setup error:', error);
    }
  });

  database = new Database({
    adapter,
    modelClasses: [Worker, Project, CheckIn, DailyLog, NfcTag],
  });
} else {
  // Web - dummy object, app uses API directly
  database = {
    get: () => ({ query: () => ({ fetch: async () => [] }) }),
    write: async (fn) => fn(),
  };
}

export default database;
