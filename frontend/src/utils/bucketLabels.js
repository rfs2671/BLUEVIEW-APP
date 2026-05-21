// Phase 1 Week 13-19 PR-B — 10-bucket DOB taxonomy labels.
//
// Frontend mirror of the 10 bucket names emitted by
// backend.lib.statistical_engine.violation_taxonomy.BUCKETS. The
// backend persists snake_case bucket strings throughout the
// causal_lift_matrix + recent-complaint-buckets responses; this helper
// renders them as GC-readable titles for the Tactical Recommendations
// surface ("safety_hazards" → "Safety Hazards").
//
// Same pattern as displayHelpers.PROJECT_TYPE_LABELS — a single
// lookup table for the production enum, with a graceful fallback for
// any future bucket additions on the backend.

export const BUCKET_LABELS = {
  structural_concerns:     'Structural Concerns',
  construction_violations: 'Construction Violations',
  occupancy_violations:    'Occupancy Violations',
  safety_hazards:          'Safety Hazards',
  environmental:           'Environmental',
  mep_systems:             'MEP Systems',
  accessibility:           'Accessibility',
  zoning:                  'Zoning',
  quality_of_life:         'Quality of Life',
  other:                   'Other',
};

/**
 * Render a violation_taxonomy bucket name as a GC-readable title.
 * Returns 'Unknown' for null/undefined/empty inputs so prose
 * interpolation stays safe. Falls through to a generic title-case
 * for any bucket not present in BUCKET_LABELS (defensive against
 * future backend additions).
 */
export function bucketLabel(bucket) {
  if (!bucket) return 'Unknown';
  if (Object.prototype.hasOwnProperty.call(BUCKET_LABELS, bucket)) {
    return BUCKET_LABELS[bucket];
  }
  return String(bucket)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default {
  BUCKET_LABELS,
  bucketLabel,
};
