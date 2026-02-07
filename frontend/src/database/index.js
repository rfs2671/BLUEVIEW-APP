import { Database } from '@nozbe/watermelondb';
import SQLiteAdapter from '@nozbe/watermelondb/adapters/sqlite';

import schema from './schema';
import Worker from './models/Worker';
import Project from './models/Project';
import CheckIn from './models/CheckIn';
import DailyLog from './models/DailyLog';
import NfcTag from './models/NfcTag';

// Create the SQLite adapter
const adapter = new SQLiteAdapter({
  schema,
  // Optional: migrations for future schema changes
  // migrations,
  jsi: true, // Use JSI for better performance
  onSetUpError: (error) => {
    console.error('Database setup error:', error);
  },
});

// Create the database
const database = new Database({
  adapter,
  modelClasses: [Worker, Project, CheckIn, DailyLog, NfcTag],
});

export default database;
