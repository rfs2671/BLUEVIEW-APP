// Project → Schedule: pure helpers for app/projects/[id]/schedule.jsx.
// Nothing here computes a schedule number: it only formats what the server
// returns from the schedule file, and returns null for anything missing so the
// screen shows nothing rather than an invented value.

const isNum = (n) => typeof n === 'number' && Number.isFinite(n);

/** 'YYYY-MM-DD' (or an ISO timestamp) -> 'Mar 4, 2026'; null when absent or unreadable. */
export function dateLabel(value) {
  if (!value || typeof value !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return null;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/** A timestamp -> 'Mar 4, 2026'; null when absent. */
export function whenLabel(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

/** "5 days later than the original finish" -- null unless the file gave a number. */
export function varianceLine(t, days) {
  if (!isNum(days)) return null;
  if (days === 0) return t('varianceNone');
  const n = Math.abs(Math.round(days));
  return `${n} ${t(days > 0 ? 'varianceLate' : 'varianceEarly')}`;
}

/** Percent as the file states it; null when the file has none. */
export function percentLabel(value) {
  if (!isNum(value)) return null;
  return `${Math.round(value * 10) / 10}%`;
}

/** Counts that are real numbers, as [label key, value] rows. */
export function countRows(counts) {
  if (!counts) return [];
  return [['complete', counts.complete], ['inProgress', counts.in_progress], ['notStarted', counts.not_started]]
    .filter(([, v]) => isNum(v));
}

/** The server's reason (detail) when it sent one, else the fallback. */
export function errorDetail(e, fallback) {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

/** Only admins (can_edit) get import / confirm / discard controls. */
export function canManage(data) {
  return !!(data && data.can_edit);
}

/**
 * What the confirm button does for a draft: it must never replace a confirmed
 * schedule without the explicit dialog.
 */
export function confirmMode(data) {
  return data && data.confirmed ? 'replace' : 'confirm';
}
