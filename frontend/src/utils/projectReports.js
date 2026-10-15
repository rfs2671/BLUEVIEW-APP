// Project → Reports: the PDF project report (lib/project_report.py on the
// server). Pure copy and choices; the screen is app/projects/[id]/reports.jsx.
// Every number in a report comes from Levelog's records -- this file only
// labels what the server returns.

import { canSearch } from './projectMemory';

/** Same people as Search: an admin, or a PM on their assigned jobs. */
export function canSeeReports(user) {
  return canSearch(user);
}

/** The periods offered by Generate; the words are what the server reads. */
export const RANGE_CHOICES = [
  { key: 'last 2 weeks', label: 'Last 2 weeks' },
  { key: 'this month', label: 'This month' },
  { key: 'last month', label: 'Last month' },
];

export const SCHEDULE_OPTIONS = [
  { key: 'off', label: 'Off' },
  { key: 'biweekly', label: 'Every 2 weeks', hint: 'Monday 8am' },
  { key: 'monthly', label: 'Monthly', hint: '1st of the month, 8am' },
];

export function scheduleLabel(key) {
  const o = SCHEDULE_OPTIONS.find((x) => x.key === key) || SCHEDULE_OPTIONS[0];
  return o.hint ? `${o.label} (${o.hint})` : o.label;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function md(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return null;
  return { y: Number(m[1]), label: `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}` };
}

/** "Oct 1 – Oct 14, 2026" (the year once when both ends share it). */
export function periodLabel(start, end) {
  const a = md(start);
  const b = md(end);
  if (!a || !b) return '';
  if (a.y === b.y) return `${a.label} – ${b.label}, ${b.y}`;
  return `${a.label}, ${a.y} – ${b.label}, ${b.y}`;
}

/** Where a report came from, for its list row. */
export function sourceLabel(source) {
  if (source === 'schedule') return 'Scheduled';
  if (source === 'dm') return 'Asked in WhatsApp';
  return 'Made in the app';
}

/** The file name a download is saved under. */
export function pdfName(report) {
  const t = String((report && report.title) || 'Levelog report').replace(/[^\w\- ]+/g, '').trim();
  return `${t.replace(/\s+/g, '-') || 'report'}.pdf`;
}

/** Only admins set the schedule (the server refuses anyone else). */
export function scheduleBody(schedule, pmIds) {
  const keys = SCHEDULE_OPTIONS.map((o) => o.key);
  return {
    schedule: keys.includes(schedule) ? schedule : 'off',
    pm_ids: Array.from(new Set((pmIds || []).map(String))),
  };
}
