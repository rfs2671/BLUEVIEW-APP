import { appSchema, tableSchema } from '@nozbe/watermelondb';

export default appSchema({
  version: 1,
  tables: [
    // Workers table
    tableSchema({
      name: 'workers',
      columns: [
        { name: 'name', type: 'string' },
        { name: 'phone', type: 'string', isOptional: true },
        { name: 'trade', type: 'string', isOptional: true },
        { name: 'company', type: 'string', isOptional: true },
        { name: 'osha_number', type: 'string', isOptional: true },
        { name: 'certifications', type: 'string', isOptional: true }, // JSON array
        { name: 'backend_id', type: 'string', isIndexed: true }, // MongoDB _id
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
        { name: 'is_deleted', type: 'boolean' },
      ],
    }),

    // Projects table
    tableSchema({
      name: 'projects',
      columns: [
        { name: 'name', type: 'string' },
        { name: 'address', type: 'string', isOptional: true },
        { name: 'status', type: 'string' }, // active, completed, on_hold
        { name: 'start_date', type: 'number', isOptional: true },
        { name: 'end_date', type: 'number', isOptional: true },
        { name: 'backend_id', type: 'string', isIndexed: true },
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
        { name: 'is_deleted', type: 'boolean' },
      ],
    }),

    // Check-ins table
    tableSchema({
      name: 'check_ins',
      columns: [
        { name: 'worker_id', type: 'string', isIndexed: true }, // Foreign key
        { name: 'project_id', type: 'string', isIndexed: true }, // Foreign key
        { name: 'worker_name', type: 'string' }, // Denormalized for quick access
        { name: 'worker_trade', type: 'string', isOptional: true },
        { name: 'worker_company', type: 'string', isOptional: true },
        { name: 'project_name', type: 'string' },
        { name: 'check_in_time', type: 'number' },
        { name: 'check_out_time', type: 'number', isOptional: true },
        { name: 'nfc_tag_id', type: 'string', isOptional: true },
        { name: 'backend_id', type: 'string', isIndexed: true },
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
        { name: 'is_deleted', type: 'boolean' },
        { name: 'sync_status', type: 'string' }, // synced, pending, failed
      ],
    }),

    // Daily logs table
    tableSchema({
      name: 'daily_logs',
      columns: [
        { name: 'project_id', type: 'string', isIndexed: true },
        { name: 'project_name', type: 'string' },
        { name: 'date', type: 'number' },
        { name: 'weather', type: 'string', isOptional: true },
        { name: 'notes', type: 'string', isOptional: true },
        { name: 'work_performed', type: 'string', isOptional: true },
        { name: 'materials_used', type: 'string', isOptional: true },
        { name: 'issues', type: 'string', isOptional: true },
        { name: 'backend_id', type: 'string', isIndexed: true },
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
        { name: 'is_deleted', type: 'boolean' },
        { name: 'sync_status', type: 'string' }, // synced, pending, failed
      ],
    }),

    // NFC tags table
    tableSchema({
      name: 'nfc_tags',
      columns: [
        { name: 'tag_id', type: 'string', isIndexed: true },
        { name: 'project_id', type: 'string', isIndexed: true },
        { name: 'project_name', type: 'string' },
        { name: 'location', type: 'string', isOptional: true },
        { name: 'backend_id', type: 'string', isIndexed: true },
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
        { name: 'is_deleted', type: 'boolean' },
      ],
    }),
  ],
});
