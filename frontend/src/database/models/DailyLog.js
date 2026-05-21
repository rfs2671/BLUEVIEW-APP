import { Model } from '@nozbe/watermelondb';
import { field, date, readonly, relation } from '@nozbe/watermelondb/decorators';

export default class DailyLog extends Model {
  static table = 'daily_logs';
  static associations = {
    projects: { type: 'belongs_to', key: 'project_id' },
  };

  @field('project_id') projectId;
  @field('project_name') projectName;
  @date('date') date;
  @field('weather') weather;
  @field('notes') notes;
  @field('work_performed') workPerformed;
  @field('materials_used') materialsUsed;
  @field('issues') issues;
  // Phase 1 Week 3 PR-B — manual project phase. Enum values mirror
  // backend Pydantic Literal[...] in server.py:DailyLogCreate.
  // Schema-on-read default is null (older logs migrated v1→v2 receive
  // null for this column).
  @field('phase') phase;
  @field('backend_id') backendId;
  @field('is_deleted') isDeleted;
  @field('sync_status') syncStatus; // 'synced', 'pending', 'failed'

  @readonly @date('created_at') createdAt;
  @date('updated_at') updatedAt;

  @relation('projects', 'project_id') project;
}
