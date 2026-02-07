import { Model } from '@nozbe/watermelondb';
import { field, date, readonly, relation } from '@nozbe/watermelondb/decorators';

export default class CheckIn extends Model {
  static table = 'check_ins';
  static associations = {
    workers: { type: 'belongs_to', key: 'worker_id' },
    projects: { type: 'belongs_to', key: 'project_id' },
  };

  @field('worker_id') workerId;
  @field('project_id') projectId;
  @field('worker_name') workerName;
  @field('worker_trade') workerTrade;
  @field('worker_company') workerCompany;
  @field('project_name') projectName;
  @date('check_in_time') checkInTime;
  @date('check_out_time') checkOutTime;
  @field('nfc_tag_id') nfcTagId;
  @field('backend_id') backendId;
  @field('is_deleted') isDeleted;
  @field('sync_status') syncStatus; // 'synced', 'pending', 'failed'

  @readonly @date('created_at') createdAt;
  @date('updated_at') updatedAt;

  @relation('workers', 'worker_id') worker;
  @relation('projects', 'project_id') project;

  // Helper to check if checked out
  get isCheckedOut() {
    return !!this.checkOutTime;
  }

  // Helper to get duration in minutes
  get durationMinutes() {
    if (!this.checkOutTime) return null;
    return Math.floor((this.checkOutTime - this.checkInTime) / (1000 * 60));
  }
}
