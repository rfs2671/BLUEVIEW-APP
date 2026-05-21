import { schemaMigrations, addColumns } from '@nozbe/watermelondb/Schema/migrations';

/**
 * Phase 1 Week 3 PR-B — WatermelonDB schema migrations.
 *
 * Each migration step targets a specific schema version transition.
 * WatermelonDB applies them in order when the on-device schema version
 * is older than the app's current schema version (see schema.js).
 *
 * v1 → v2 — daily_logs gains `phase` column.
 *   Mirrors the backend Pydantic field added in PR #36 (Phase 1 Week 3
 *   PR-A). The schedule_position_ratio resolver in
 *   backend/lib/statistical_engine/live_mutation.py reads this field
 *   via the sync allowlist at server.py:2261.
 */
export default schemaMigrations({
  migrations: [
    {
      toVersion: 2,
      steps: [
        addColumns({
          table: 'daily_logs',
          columns: [
            { name: 'phase', type: 'string', isOptional: true },
          ],
        }),
      ],
    },
  ],
});
