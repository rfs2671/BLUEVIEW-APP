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
  if (it.room && it.area && it.area !== '?') parts.push(it.room);   // "Apt 3D · bedroom"
  parts.push(it.trade && it.trade !== '?' ? it.trade : 'trade ?');
  return parts.join(' · ');
}

/** "Mike Rivera (Bright Electric) · due Mon" */
export function whoLine(it) {
  const a = it.assignee || {};
  const who = a.name ? `${a.name}${a.company ? ` (${a.company})` : ''}` : 'Not assigned';
  return it.due ? `${who} · due ${it.due}` : who;
}

/** "Mike Rivera: mention won't notify (no number)" when the send could not
 *  @mention the assignee for real. */
export function mentionLine(it) {
  if (!it || !it.mention_note) return null;
  const a = it.assignee || {};
  return `${a.name || 'Assignee'}: ${it.mention_note}`;
}

/** The words as written or said: 🎤 marks a voice note. */
export function itemWords(it) {
  const w = it.text || '(no words)';
  return it.voice ? `🎤 “${w}”` : `“${w}”`;
}

const ACTIONS = {
  sent: 'Sent', open: 'Reopened', ready_to_check: 'Marked done (ready to check)',
  closed: 'Closed', edited: 'Edited', reassigned: 'Reassigned to', due: 'Due changed',
};

/** One line under the status chips: what each status means. */
export const STATUS_EXPLAINER =
  'Open = assigned · Ready to check = assignee says fixed · Closed = admin/PM verified';

/** The status chips with their counts: "All 4", "Open 3", "Ready to check 0". */
export function statusChips(statuses, counts) {
  const c = counts || {};
  const total = (statuses || []).reduce((n, s) => n + (c[s] || 0), 0);
  return [{ value: '', label: `All ${total}` }].concat((statuses || []).map((s) => ({
    value: s, label: `${statusLabel(s)} ${c[s] || 0}` })));
}

/** The assignee filter row shows whenever the list has anyone on it. */
export function showAssigneeRow(assignees) {
  return (assignees || []).length >= 1;
}

/** The assignee filter: "All" then each person on the list. */
export function assigneeChips(assignees) {
  return [{ value: '', label: 'Everyone' }].concat((assignees || []).map((a) => ({
    value: a.key, label: a.name || 'Not assigned' })));
}

/** What an admin / PM can do to an item, by its status. Close and reopen
 *  as in WhatsApp ("P23 ok" / "P23 not done"). */
export function itemActions(it, canAct) {
  if (!canAct || !it) return [];
  const out = [];
  if (it.status !== 'closed') out.push({ key: 'close', label: 'Close', patch: { status: 'closed' } });
  if (it.status !== 'open') out.push({ key: 'reopen', label: 'Reopen', patch: { status: 'open' } });
  out.push({ key: 'reassign', label: 'Reassign' });
  out.push({ key: 'due', label: 'Change due' });
  return out;
}

/** The due choices (the words the server reads). */
export const DUE_CHOICES = [
  { words: 'ASAP', label: 'ASAP' },
  { words: 'tomorrow', label: 'Tomorrow' },
  { words: 'Mon', label: 'Mon' },
  { words: 'Wed', label: 'Wed' },
  { words: 'Fri', label: 'Fri' },
  { words: 'no due date', label: 'No due date' },
];

/** The photos an item has, in order: [{ which, label }] -- 'item', 'item:2', …
 *  then the completion photo ('done'). */
export function photoList(it) {
  const n = (it && (it.photos != null ? it.photos : (it.has_photo ? 1 : 0))) || 0;
  const out = [];
  for (let i = 1; i <= n; i += 1) {
    out.push({ which: i === 1 ? 'item' : `item:${i}`, label: n > 1 ? `Photo ${i} of ${n}` : 'Photo' });
  }
  if (it && it.completion && it.completion.has_photo) out.push({ which: 'done', label: 'Done photo' });
  return out;
}

/** One history line: "Oct 13, 9:05 AM — Closed: “P-588-4 ok”". */
export function historyLine(h, fmt = (iso) => iso) {
  // A send says whether it went, and where (live 588, Oct 12: a shadow send
  // read "Sent"): "Would send (shadow) · DM to Chris (GC team)".
  const sent = h.action === 'sent'
    ? `${h.mode === 'live' ? 'Sent' : 'Would send (shadow)'}${h.dest ? ` · ${h.dest}` : ''}` : null;
  const what = sent || ACTIONS[h.action] || String(h.action || '');
  const when = h.at ? `${fmt(h.at)} — ` : '';
  const quote = !h.quote || h.action === 'sent' ? ''
    : (h.action === 'reassigned' || h.action === 'due') ? ` ${h.quote}` : `: “${h.quote}”`;
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

// ── "Punch list goes to" (Levelog Assistant) ─────────────────────────────
export const PUNCH_TO_OPTIONS = [
  { mode: 'per_trade', label: 'Per trade',
    line: 'Posted in the job group, mentioning the person picked for each trade on "Who gets what?".' },
  { mode: 'one_person', label: 'One person',
    line: 'The whole list by DM to one person. "Who gets what?" is skipped; the recap still asks for ok.' },
];

// ── "Punch items due" (Levelog Assistant): the due a walk's items get
// unless the walker says. ASAP is chased every day from tomorrow; no due
// date is never chased.
export const PUNCH_DUE_OPTIONS = [
  { mode: 'asap', label: 'ASAP', line: 'Chased every day from tomorrow until done.' },
  { mode: 'tomorrow', label: 'Tomorrow', line: 'Chased tomorrow.' },
  { mode: 'fri', label: 'Friday', line: 'Chased on Friday.' },
  { mode: 'none', label: 'No due date', line: 'Never chased; shown open on the punch list.' },
];

export function punchDueMode(data) {
  const v = data && data.punch_due_default;
  return PUNCH_DUE_OPTIONS.some((o) => o.mode === v) ? v : 'asap';
}

export function punchToMode(data) {
  return data && data.punch_to === 'one_person' ? 'one_person' : 'per_trade';
}

/** "Electrical · Power Direct" and who its punch contact is. */
export function punchContactLine(row) {
  const r = row || {};
  return {
    title: [r.trade, r.company].filter(Boolean).join(' · '),
    line: r.contact_name
      ? `Punch contact: ${r.contact_name}`
      : (r.options || []).length
        ? 'No punch contact: "Who gets what?" asks.'
        : 'No one from this sub in People yet.',
  };
}

export const PUNCH_CONTACTS_NOTE = 'Only these people are suggested for a sub\'s punch items. '
  + 'Workers who check in are never messaged.';


/** Under a photo that is only WhatsApp's preview (the original could not be had). */
export const PREVIEW_ONLY = 'Original unavailable — preview only';

export function photoNote(it, which) {
  const q = which === 'done' ? it && it.completion && it.completion.photo_quality
    : it && it.photo_quality;
  return q === 'preview' ? PREVIEW_ONLY : null;
}
