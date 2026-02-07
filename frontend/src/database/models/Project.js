import { Model } from '@nozbe/watermelondb';
import { field, date, readonly, children } from '@nozbe/watermelondb/decorators';

export default class Project extends Model {
  static table = 'projects';
  static associations = {
    check_ins: { type: 'has_many', foreignKey: 'project_id' },
    daily_logs: { type: 'has_many', foreignKey: 'project_id' },
    nfc_tags: { type: 'has_many', foreignKey: 'project_id' },
  };

  @field('name') name;
  @field('address') address;
  @field('status') status;
  @date('start_date') startDate;
  @date('end_date') endDate;
  @field('backend_id') backendId;
  @field('is_deleted') isDeleted;

  @readonly @date('created_at') createdAt;
  @date('updated_at') updatedAt;

  @children('check_ins') checkIns;
  @children('daily_logs') dailyLogs;
  @children('nfc_tags') nfcTags;
}
