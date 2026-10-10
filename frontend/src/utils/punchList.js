/**
 * Project → Punch list: copy and shaping for the screen
 * (app/projects/[id]/punch.jsx) and the "Punch sends" setting in
 * Levelog Assistant. Items come from a walkthrough in the super's WhatsApp
 * DM; the app reads them, and admins fix a trade / floor / status.
 */

import { canSearch } from './projectMemory';

/** Admins and PMs (the endpoint's rule). */
export function canSeePunch(user) {
  return canSearch(user);
}

export const STATUS_LABELS = {
  open: 'Open',
  ready_to_check: 'Ready to check',
  closed: 'Closed',
};

export function statusLabel(s) {
  return STATUS_LABELS[s] || String(s || '').replace(/_/g, ' ');
}

export function floorLabel(f) {
  if (!f || f === '?') return 'Floor ?';
  return /^\d+$/.test(String(f)) ? `Floor ${f}` : String(f).charAt(0).toUpperCase() + String(f).slice(1);
}

/** The filter chips: "All" plus each value the job has. */
export function filterChips(values, label = (v) => v) {
  return [{ value: '', label: 'All' }].concat((values || []).map((v) => ({ value: v, label: label(v) })));
}

/** "Floor 6 · Apt 6B · electrical" */
export function whereLine(it) {
  const parts = [];
  if (it.floor && it.floor !== '?') parts.push(floorLabel(it.floor));
  if (it.area && it.area !== '?' && it.area !== it.floor) parts.push(it.area);
  parts.push(it.trade && it.trade !== '?' ? it.trade : 'trade ?');
  return parts.join(' · ');
}

/** "Mike Rivera (Bright Electric) · due Mon" */
export function whoLine(it) {
  const a = it.assignee || {};
  const who = a.name ? `${a.name}${a.company ? ` (${a.company})` : ''}` : 'Not assigned';
  return it.due ? `${who} · due ${it.due}` : who;
}

/** The words as written or said: 🎤 marks a voice note. */
export function itemWords(it) {
  const w = it.text || '(no words)';
  return it.voice ? `🎤 “${w}”` : `“${w}”`;
}

const ACTIONS = {
  sent: 'Sent', open: 'Reopened', ready_to_check: 'Marked done (ready to check)',
  closed: 'Closed', edited: 'Edited',
};

/** One history line: "Oct 13, 9:05 AM — Closed: “P-588-4 ok”". */
export function historyLine(h, fmt = (iso) => iso) {
  const what = ACTIONS[h.action] || String(h.action || '');
  const when = h.at ? `${fmt(h.at)} — ` : '';
  const quote = h.quote && h.action !== 'sent' ? `: “${h.quote}”` : '';
  return `${when}${what}${quote}`;
}

export function emptyText(filtered) {
  return filtered
    ? 'Nothing matches these filters.'
    : 'No punch items yet. Start one from WhatsApp: DM the assistant "starting walkthrough at <job>", then a photo per item.';
}

/** What an admin may set in the app. */
export const ADMIN_STATUSES = ['open', 'ready_to_check', 'closed'];

// ── "Punch sends" (Levelog Assistant) ────────────────────────────────────
export const PUNCH_SENDS_OPTIONS = [
  { mode: 'shadow', label: 'Shadow',
    line: 'The walker sees what would be posted. Nothing is posted in the group.' },
  { mode: 'live', label: 'Live',
    line: 'On "send", one message per assignee goes to the GC group, with the photos.' },
];

export function punchSendsMode(data) {
  return data && data.punch_sends === 'live' ? 'live' : 'shadow';
}
