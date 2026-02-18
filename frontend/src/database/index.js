import { Platform } from 'react-native';

let database;

if (Platform.OS !== 'web') {
  const { Database } = require('@nozbe/watermelondb');
  const LokiJSAdapter = require('@nozbe/watermelondb/adapters/lokijs').default;
  const schema = require('./schema').default;
  const Worker = require('./models/Worker').default;
  const Project = require('./models/Project').default;
  const CheckIn = require('./models/CheckIn').default;
  const DailyLog = require('./models/DailyLog').default;
  const NfcTag = require('./models/NfcTag').default;

  const adapter = new LokiJSAdapter({
    schema,
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
