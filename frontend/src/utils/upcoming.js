// Project → Upcoming: what is coming up on the job. Pure copy and grouping;
// the screen is app/projects/[id]/upcoming.jsx. Events come from three places
// (the server's lib/upcoming.py): a city record (ECB/OATH hearings, permit
// expirations), the job's WhatsApp group ("from chat", with the words it came
// from), and a person's own "remind me" in a DM (never listed on a job).

import { canSearch } from './projectMemory';
import { dateEntryError, toStoredDate } from './dateEntry';

/** Same people as Search: an admin, or a PM on their assigned jobs. */
export function canSeeUpcoming(user) {
  return canSearch(user);
}

export const CHIP_TONES = { city: 'city', chat: 'chat', dm: 'mine' };

/** "Thu Dec 4" headings, each with its events in time order (no time last). */
export function byDay(events) {
  const days = [];
  const at = {};
  const list = (Array.isArray(events) ? events : [])
    .filter((e) => e && e.status === 'open' && e.date)
    .slice()
    .sort((a, b) => (a.date + (a.time || '99:99')).localeCompare(b.date + (b.time || '99:99')));
  for (const e of list) {
    if (!(e.date in at)) {
      at[e.date] = days.length;
      days.push({ date: e.date, label: e.day_label || e.date, events: [] });
    }
    days[at[e.date]].events.push(e);
  }
  return days;
}

/** "9am — Con Ed meter set" / "Con Ed meter set". */
export function eventLine(e) {
  const x = e || {};
  return x.time_label ? `${x.time_label} — ${x.title || ''}` : (x.title || '');
}

/** The words a chat event came from, and who said them. */
export function evidenceLine(e) {
  const x = e || {};
  if (x.source !== 'chat' || !x.quote) return '';
  return x.who ? `“${x.quote}” — ${x.who}` : `“${x.quote}”`;
}

/** The last move, if it moved: "Moved from Dec 2". */
export function movedLine(e) {
  const h = (e && Array.isArray(e.history)) ? e.history : [];
  const last = [...h].reverse().find((x) => x && x.action === 'rescheduled');
  return last && last.frm ? `Moved from ${last.frm}` : '';
}

/** The edit form's checks, before anything is sent. The day is typed in the
 *  shared DateInput (MM/DD/YYYY, src/utils/dateEntry.js) and sent as ISO. */
export function cleanEdit({ date, time }) {
  const out = {};
  const err = dateEntryError(date);
  if (err) return { error: err };
  const iso = toStoredDate(date);
  if (iso) out.date = iso;
  const t = String(time || '').trim();
  if (t && !/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) return { error: 'Time as HH:MM (24h), or leave it empty.' };
  out.time = t;
  return { patch: out };
}
