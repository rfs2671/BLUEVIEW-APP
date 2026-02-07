import { Model } from '@nozbe/watermelondb';
import { field, date, readonly, children } from '@nozbe/watermelondb/decorators';

export default class Worker extends Model {
  static table = 'workers';
  static associations = {
    check_ins: { type: 'has_many', foreignKey: 'worker_id' },
  };

  @field('name') name;
  @field('phone') phone;
  @field('trade') trade;
  @field('company') company;
  @field('osha_number') oshaNumber;
  @field('certifications') certificationsJSON; // JSON string
  @field('backend_id') backendId;
  @field('is_deleted') isDeleted;

  @readonly @date('created_at') createdAt;
  @date('updated_at') updatedAt;

  @children('check_ins') checkIns;

  // Helper to get certifications as array
  get certifications() {
    try {
      return this.certificationsJSON ? JSON.parse(this.certificationsJSON) : [];
    } catch (e) {
      return [];
    }
  }

  // Helper to set certifications from array
  setCertifications(certs) {
    this.certificationsJSON = JSON.stringify(certs);
  }
}
