// Project → Reports: the PDF project report (lib/project_report.py on the
// server). Pure copy and choices; the screen is app/projects/[id]/reports.jsx.
// Every number in a report comes from Levelog's records -- this file only
// labels what the server returns.

import { canSearch } from './projectMemory';

/** Same people as Search: an admin, or a PM on their assigned jobs. */
export function canSeeReports(user) {
  return canSearch(user);
}

/** Generate now: the presets (lib/project_report.PRESETS), and a custom range. */
export const PRESETS = [
  { key: 'last_7_days', label: 'Last 7 days' },
  { key: 'last_2_weeks', label: 'Last 2 weeks' },
  { key: 'this_month', label: 'This month' },
  { key: 'last_month', label: 'Last month' },
  { key: 'this_quarter', label: 'This quarter' },
  { key: 'whole_project', label: 'Whole project' },
  { key: 'custom', label: 'Custom range' },
];
/** Kept for anything that still names the old three. */
export const RANGE_CHOICES = [
  { key: 'last 2 weeks', label: 'Last 2 weeks' },
  { key: 'this month', label: 'This month' },
  { key: 'last month', label: 'Last month' },
];

/** The reports a job can be sent on a schedule -- any combination. */
export const KINDS = [
  { key: 'daily', label: 'Daily', hint: 'The daily report, at its send time' },
  { key: 'weekly', label: 'Weekly', hint: 'Mondays 8am · the week before' },
  { key: 'biweekly', label: 'Bi-weekly', hint: 'Every other Monday 8am · 2 weeks' },
  { key: 'monthly', label: 'Monthly', hint: '1st of the month 8am · the month before' },
  { key: 'quarterly', label: 'Quarterly', hint: 'Jan, Apr, Jul, Oct 1st 8am · the quarter before' },
];

/** The list with `key` in or out. */
export function toggled(list, key) {
  const cur = new Set((list || []).map(String));
  if (cur.has(String(key))) cur.delete(String(key)); else cur.add(String(key));
  return Array.from(cur);
}

/** What the screen sends to save the schedule. */
export function settingsBody(schedules, recipientIds, delivery) {
  const keys = KINDS.map((k) => k.key);
  return {
    schedules: keys.filter((k) => (schedules || []).includes(k)),
    recipient_ids: Array.from(new Set((recipientIds || []).map(String))),
    delivery: { whatsapp: !!(delivery && delivery.whatsapp), email: !!(delivery && delivery.email) },
  };
}

/** A custom range: YYYY-MM-DD to YYYY-MM-DD, at most 400 days. '' when good, else why not. */
export function rangeProblem(start, end) {
  const re = /^\d{4}-\d{2}-\d{2}$/;
  if (!re.test(String(start || '')) || !re.test(String(end || ''))) return 'Enter both dates (MM/DD/YYYY).';
  const a = Date.parse(`${start}T00:00:00Z`);
  const b = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return 'Enter both dates (MM/DD/YYYY).';
  if (b < a) return 'The end is before the start.';
  if ((b - a) / 86400000 > 400) return 'Pick at most 400 days.';
  return '';
}

/** "Weekly · Scheduled" / "Asked in WhatsApp by Pat PM" / "Made in the app by Ada Admin". */
export function whoLine(r) {
  const x = r || {};
  const src = x.source_label || sourceLabel(x.source);
  const by = x.requested_by && x.requested_by !== 'Schedule' ? ` by ${x.requested_by}` : '';
  return [x.kind_label, `${src}${by}`].filter(Boolean).join(' · ');
}

/** "Oct 15, 2026" (New York) -- when the report was made. */
export function madeLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric',
    year: 'numeric' });
}

/** What Share sends when there is no file to share: the title and the no-login link. */
export function shareText(r) {
  const x = r || {};
  return x.link ? `${x.title || 'Progress report'}\n${x.link}` : '';
}

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

// ── THE DAILY REPORT'S OWN SETTINGS (folded in from Report Settings) ────────
// Its send time (New York) and the extra addresses it is emailed to, as the
// old Report Settings screen had them; saved with PUT /report-settings.

/** The send times offered, "HH:MM" 24-hour. */
export const SEND_TIMES = ['06:00', '12:00', '15:00', '17:00', '18:00', '19:00', '20:00', '21:00'];

/** "18:00" -> "6:00 PM". */
export function timeLabel(hhmm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || ''));
  if (!m) return '';
  const h = Number(m[1]);
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** One address added to the list: { list } or { error } (the list unchanged). */
export function addEmail(list, raw) {
  const current = Array.isArray(list) ? list : [];
  const email = String(raw || '').trim().toLowerCase();
  if (!email) return { list: current, error: 'Enter an email address.' };
  if (!EMAIL_RE.test(email)) return { list: current, error: "That isn't an email address." };
  if (current.includes(email)) return { list: current, error: 'Already on the list.' };
  return { list: [...current, email] };
}

/** The PUT /report-settings body for one change: only the field that changed
 *  (Codex on #809 — a time change carrying this screen's copy of the list
 *  would put back an address another admin removed meanwhile). */
export function dailySaveBody(patch) {
  const body = {};
  if (patch && 'send_time' in patch) body.report_send_time = patch.send_time;
  if (patch && 'emails' in patch) body.report_email_list = patch.emails;
  return body;
}
