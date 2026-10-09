/**
 * Project → WhatsApp → Attention (beta): what the review screen says for the
 * server's answers. Pure, so it is tested under plain node
 * (whatsappAttention.test.cjs).
 *
 * SHADOW MODE. Nothing on this screen was posted to any group or person. An
 * admin marks each item Correct / Wrong / Dismiss so precision per type is
 * known before anything is ever shown in WhatsApp.
 * (GET /api/projects/{id}/attention, POST …/attention/{item}/review)
 *
 * Each item has a timeline: made, then any change a later message made to it
 * (rescheduled, done, cancelled, possibly done, one part done, a flag), each
 * with the exact words that made it, marked Correct / Wrong on its own.
 * (POST …/attention/{item}/history/{change}/review)
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
  // One entry for an update that could be about several items ("Sent" with
  // two open): its summary names them; none of them was changed.
  update_review: 'Unclear update',
};

export const VERDICTS = [
  { verdict: 'correct', label: 'Correct' },
  { verdict: 'wrong', label: 'Wrong' },
  { verdict: 'dismissed', label: 'Dismiss' },
];

export function typeLabel(type) {
  return TYPE_LABELS[type] || 'Item';
}

/** "Owner: Mike" / "Owner: Mike (not matched to a person)" /
 *  "Owner: possibly Mike (check)" / null. */
export function ownerLine(item) {
  if (!item || !item.owner) return null;
  const tail = item.owner_status === 'resolved' ? '' : ' (not matched to a person)';
  if (item.owner_possibly) return `Owner: possibly ${item.owner}${tail} (check)`;
  return `Owner: ${item.owner}${tail}`;
}

export function dueLine(item) {
  if (!item || !item.due_text) return null;
  return item.due_at ? `Due: ${item.due_text} (${item.due_at})` : `Due: ${item.due_text}`;
}

export function statusLine(item) {
  if (!item) return null;
  const parts = {
    possibly_resolved: 'Possibly answered (someone replied)',
    possibly_done: 'Possibly done: check which item it was',
    rescheduled: 'Rescheduled',
    done: 'Done',
    cancelled: 'Cancelled',
  };
  const line = parts[item.status] || null;
  if (item.parts_done) {
    const n = `${item.parts_done} ${item.parts_done === 1 ? 'person has' : 'people have'} done their part`;
    return line ? `${line} · ${n}` : n;
  }
  return line;
}

// ── TIMELINE ──────────────────────────────────────────────────────────────

export const LISTS = [
  { status: 'open', label: 'Open' },
  { status: 'closed', label: 'Done / cancelled' },
];

export const STATE_VERDICTS = [
  { verdict: 'correct', label: 'Correct' },
  { verdict: 'wrong', label: 'Wrong' },
];

const LINKS = {
  reply: 'a reply to it',
  previous: 'right after it',
  owner_topic: 'same person, same topic',
  only_open: 'their only open item',
  ambiguous: 'not clear which item',
  via_parent: 'with the ask it answered',
  via_child: 'with the answer to it',
  answers: 'answers an earlier ask',
};

const FLAGS = {
  not_owner: 'Someone else gave a new date. Not applied.',
  possibly_cancelled: 'Possibly cancelled. Not applied.',
  which_item: 'New date, but not clear for which item. Not applied.',
  possible_owner: 'Said yes right after this ask, which named nobody. Possibly theirs.',
  possible_subject: 'Said right after an ask that named nobody, in words that do not say what it is about. Possibly theirs, possibly that ask.',
  possible_handover: 'Someone said its owner is out and took work on, but not clearly this. Not applied; not chased.',
};

const CLOSED_BY = { requester: 'by who asked', gc_staff: 'by GC staff' };

/** What one timeline entry says happened. */
export function eventLine(e) {
  if (!e) return '';
  if (e.kind === 'created') return e.due_to ? `Recorded · due ${e.due_to}` : 'Recorded';
  if (e.kind === 'follow_up') return 'Followed up (no change)';
  if (e.kind === 'part_done') return `One part done (…${e.sender_last4 || '????'})`;
  if (e.kind === 'flag') return FLAGS[e.note] || 'Flagged for review. Not applied.';
  if (e.kind === 'handover') {
    const who = `Handed over: ${e.owner_from || 'owner'} → ${e.owner_to || 'someone else'}`;
    return e.due_to ? `${who} · due ${e.due_to}` : who;
  }
  switch (e.to) {
    case 'rescheduled':
      return `Rescheduled: ${e.due_from || 'no date'} → ${e.due_to || 'no date'}`;
    case 'done':
      if (e.evidence_kind === 'file') return 'Done (file sent)';
      return CLOSED_BY[e.by] ? `Done (closed ${CLOSED_BY[e.by]})` : 'Done';
    case 'cancelled':
      return e.by === 'gc_staff' ? 'Cancelled by GC staff' : 'Cancelled by who asked';
    case 'possibly_done':
      return 'Possibly done';
    default:
      return 'Changed';
  }
}

/** "How it was linked: a reply to it" or null. */
export function linkLine(e) {
  const l = e && LINKS[e.link];
  return l ? `Linked: ${l}` : null;
}

/** Changes get Correct / Wrong; recording the item and a follow-up do not. */
export function reviewable(e) {
  return !!e && e.kind !== 'created' && e.kind !== 'follow_up' && !!e.id;
}

const CHANGE_LABELS = {
  rescheduled: 'Rescheduled', done: 'Done', cancelled: 'Cancelled',
  possibly_done: 'Possibly done', part_done: 'Part done', flag: 'Flagged',
  handover: 'Handed over',
};

/** "Done: 3 of 4 correct (75%)" per kind of change. */
export function statePrecisionLines(sp) {
  const p = sp || {};
  return Object.keys(CHANGE_LABELS)
    .filter((k) => p[k])
    .map((k) => {
      const r = p[k];
      const judged = (r.correct || 0) + (r.wrong || 0);
      if (!judged) return `${CHANGE_LABELS[k]}: not reviewed yet`;
      return `${CHANGE_LABELS[k]}: ${r.correct} of ${judged} correct (${Math.round((100 * r.correct) / judged)}%)`;
    });
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
