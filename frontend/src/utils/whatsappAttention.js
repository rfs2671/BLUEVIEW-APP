/**
 * Project → WhatsApp → Attention (beta): what the review screen says for the
 * server's answers. Pure, so it is tested under plain node
 * (whatsappAttention.test.cjs).
 *
 * SHADOW MODE. Nothing on this screen was posted to any group or person. An
 * admin marks each item Correct / Wrong / Dismiss so precision per type is
 * known before anything is ever shown in WhatsApp.
 * (GET /api/projects/{id}/attention, POST …/attention/{item}/review)
 */

export const ATTENTION_TITLE = 'Attention (beta)';
export const ATTENTION_NOTE =
  'What the assistant would flag from your group chats. Nothing here was posted. '
  + 'Mark each one so we can measure how often it is right.';

export const TYPE_LABELS = {
  question: 'Question',
  request: 'Request',
  commitment: 'Commitment',
  issue: 'Issue',
  decision: 'Decision',
};

export const VERDICTS = [
  { verdict: 'correct', label: 'Correct' },
  { verdict: 'wrong', label: 'Wrong' },
  { verdict: 'dismissed', label: 'Dismiss' },
];

export function typeLabel(type) {
  return TYPE_LABELS[type] || 'Item';
}

/** "Owner: Mike" / "Owner: Mike (not matched to a person)" / null. */
export function ownerLine(item) {
  if (!item || !item.owner) return null;
  const tail = item.owner_status === 'resolved' ? '' : ' (not matched to a person)';
  return `Owner: ${item.owner}${tail}`;
}

export function dueLine(item) {
  if (!item || !item.due_text) return null;
  return item.due_at ? `Due: ${item.due_text} (${item.due_at})` : `Due: ${item.due_text}`;
}

export function statusLine(item) {
  if (!item) return null;
  if (item.status === 'possibly_resolved') return 'Possibly answered (someone replied)';
  return null;
}

/** "Question: 3 of 4 correct (75%)" per type, in a fixed order. */
export function precisionLines(precision) {
  const p = precision || {};
  return Object.keys(TYPE_LABELS)
    .filter((t) => p[t])
    .map((t) => {
      const r = p[t];
      const judged = (r.correct || 0) + (r.wrong || 0);
      if (!judged) return `${typeLabel(t)}: not reviewed yet`;
      const pct = Math.round((100 * r.correct) / judged);
      return `${typeLabel(t)}: ${r.correct} of ${judged} correct (${pct}%)`;
    });
}

export function emptyText(total) {
  return total
    ? 'Nothing left to review.'
    : 'Nothing flagged yet. Items appear as your linked groups talk.';
}
