/**
 * Project → WhatsApp → Would chase (beta): what the screen says for the
 * server's answers. Pure, so it is tested under plain node
 * (whatsappChase.test.cjs).
 *
 * SHADOW MODE. Sub chasing sends nothing yet: each entry is a nudge it WOULD
 * have sent (in the item's group, @mentioning the owner, quoting the original
 * message; or, after the end of day nudge, a private DM to the company
 * admin). An admin marks each one Correct / Wrong so precision is known
 * before anything is ever sent.
 * (GET /api/projects/{id}/whatsapp/chase, POST …/whatsapp/chase/{entry}/review)
 */

export const CHASE_TITLE = 'Would chase (beta)';
export const CHASE_NOTE =
  'Nudges the assistant would send about items due today. Nothing here was sent. '
  + 'Mark each one so we can measure how often it is right.';
export const CHASE_OFF_NOTE = 'Sub chasing is switched off on the server.';

export const CHASE_VERDICTS = [
  { verdict: 'correct', label: 'Correct' },
  { verdict: 'wrong', label: 'Wrong' },
];

export const SLOT_LABELS = {
  morning: 'Morning',
  midday: 'Midday',
  eod: 'End of day',
  admin_dm: 'DM to admin',
};

function clock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, '0');
  const ap = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}

/** "Morning · 8:35 AM · Main St Project" / "DM to admin · 5:35 PM · to Ana". */
export function headLine(e) {
  if (!e) return '';
  const parts = [SLOT_LABELS[e.slot] || 'Nudge'];
  const t = clock(e.at);
  if (e.day) parts.push(t ? `${e.day} ${t}` : e.day);
  else if (t) parts.push(t);
  if (e.kind === 'admin_dm') {
    if ((e.to || []).length) parts.push(`to ${e.to.join(', ')}`);
  } else if (e.group_name) {
    parts.push(e.group_name);
  }
  return parts.join(' · ');
}

/** "Owner: Mike Rivera · 2 items". */
export function ownerLine(e) {
  if (!e || !e.owner) return null;
  const n = (e.items || []).length;
  return n > 1 ? `Owner: ${e.owner} · ${n} items` : `Owner: ${e.owner}`;
}

export function reasonLine(e) {
  return e && e.reason ? `Why: ${e.reason}` : null;
}

/** "3 of 4 correct (75%)" overall, then per slot. */
export function precisionLines(p) {
  if (!p) return [];
  const one = (label, r) => {
    const judged = (r.correct || 0) + (r.wrong || 0);
    if (!judged) return `${label}: not reviewed yet`;
    return `${label}: ${r.correct} of ${judged} correct (${Math.round((100 * r.correct) / judged)}%)`;
  };
  const total = (p.correct || 0) + (p.wrong || 0) + (p.unreviewed || 0);
  if (!total) return [];
  const out = [one('All', p)];
  const by = p.by_slot || {};
  Object.keys(SLOT_LABELS).filter((k) => by[k]).forEach((k) => out.push(one(SLOT_LABELS[k], by[k])));
  return out;
}

export function emptyText(total) {
  return total
    ? 'Nothing more to show.'
    : 'Nothing yet. Entries appear on the day an item with a confirmed owner is due.';
}
