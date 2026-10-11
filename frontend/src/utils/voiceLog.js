// Project → WhatsApp → Voice log (admins): the words for each row. Pure; the
// screen is app/projects/[id]/voice-log.jsx.

export const VOICE_LOG_TITLE = 'Voice log';
export const VOICE_LOG_NOTE =
  "Every voice note of this job: its groups' notes, and DM voice notes answered about it.";

const LANGS = { en: 'English', es: 'Spanish', yi: 'Yiddish' };
export const STATUS_LABELS = {
  transcribed: 'Transcribed',
  flagged: 'Flagged',
  not_processed: 'Not processed',
};
export const STATUS_FILTERS = ['', 'transcribed', 'flagged', 'not_processed'];

export function langLabel(code) {
  if (!code) return '';
  return LANGS[code] || String(code).toUpperCase();
}

/** "Sun Oct 11, 2:57 PM" in New York. */
export function whenLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const opt = { timeZone: 'America/New_York' };
  const day = d.toLocaleDateString('en-US', { ...opt, weekday: 'short', month: 'short', day: 'numeric' });
  const time = d.toLocaleTimeString('en-US', { ...opt, hour: 'numeric', minute: '2-digit' });
  return `${day.replace(/,/g, '')}, ${time}`;
}

/** "Meilich · 588 – Site · Spanish · 91% · 4s" (DM: "· DM"). */
export function headLine(n) {
  const x = n || {};
  const parts = [
    x.forwarded ? `forwarded by ${x.who || 'someone'}` : (x.who || 'Someone'),
    x.where === 'dm' ? 'DM' : x.place,
    langLabel(x.lang),
    typeof x.confidence === 'number' ? `${Math.round(x.confidence * 100)}%` : '',
    x.duration_sec ? `${Math.round(x.duration_sec)}s` : '',
  ];
  return parts.filter(Boolean).join(' · ');
}

/** "Flagged — yiddish" / "Not processed — shorter than 2 seconds". */
export function statusLine(n) {
  const x = n || {};
  const label = STATUS_LABELS[x.status] || '';
  if (!label) return '';
  const why = x.reason ? String(x.reason).replace(/_/g, ' ') : '';
  return why ? `${label} — ${why}` : label;
}

/** The Produced column: one line per item / event, or "Nothing". */
export function producedLines(n) {
  const list = (n && n.produced) || [];
  if (!list.length) return [{ key: 'none', kind: 'none', text: 'Produced: nothing' }];
  return list.map((p) => ({
    key: `${p.kind}:${p.id}`,
    kind: p.kind,
    id: p.id,
    text: p.kind === 'event'
      ? `Produced: event “${p.label}”${p.date ? ` (${p.date})` : ''}`
      : `Produced: ${p.type || 'item'} “${p.label}”${p.status ? ` · ${p.status}` : ''}`,
  }));
}

/** Where tapping a Produced line goes. */
export function producedRoute(projectId, p) {
  if (!p || p.kind === 'none') return null;
  return p.kind === 'event'
    ? `/projects/${projectId}/upcoming`
    : `/projects/${projectId}/whatsapp-groups`;
}

export function emptyText(filtered) {
  return filtered ? 'No voice note matches these filters.' : 'No voice notes yet.';
}

export const LOAD_MORE = 'Load more';

/** A page appended to what is shown (a note is never listed twice). */
export function appendPage(notes, page) {
  const seen = new Set((notes || []).map((n) => `${n.where}-${n.id}`));
  return (notes || []).concat(((page && page.notes) || [])
    .filter((n) => !seen.has(`${n.where}-${n.id}`)));
}
