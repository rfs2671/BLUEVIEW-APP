import { Model } from '@nozbe/watermelondb';
import { field, date, readonly, relation } from '@nozbe/watermelondb/decorators';

export default class NfcTag extends Model {
  static table = 'nfc_tags';
  static associations = {
    projects: { type: 'belongs_to', key: 'project_id' },
  };

  @field('tag_id') tagId;
  @field('project_id') projectId;
  @field('project_name') projectName;
  @field('location') location;
  @field('backend_id') backendId;
  @field('is_deleted') isDeleted;

  @readonly @date('created_at') createdAt;
  @date('updated_at') updatedAt;

  @relation('projects', 'project_id') project;
}
