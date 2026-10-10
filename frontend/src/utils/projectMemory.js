// Project → Search: the project's WhatsApp messages and daily reports,
// searched, every result with its source. Pure copy and formatting; the
// screen is app/projects/[id]/search.jsx.

export const NO_SOURCE = "I can't find that in the project history.";

/** Who may search a project: an admin, or a PM on their assigned projects
 *  (the server checks the project; this only decides the tile). */
export function canSearch(user) {
  if (user && user.is_platform_operator === true) return true;
  const role = String((user && user.role) || '').trim().toLowerCase();
  return role === 'admin' || role === 'pm';
}

/** The query as sent, or an error to show. */
export function cleanQuery(q) {
  const s = String(q || '').replace(/\s+/g, ' ').trim();
  if (s.length < 2) return { error: 'Type what to search for.' };
  return { query: s.slice(0, 300) };
}

/** The chip under a result: "Mike Rivera · Main St Electric · Oct 3, 7:42 AM",
 *  or "Daily report · Activity: … · Oct 3". */
export function chipText(r) {
  const x = r || {};
  const parts = x.source === 'daily_report'
    ? ['Daily report', x.label, x.when]
    : x.source === 'attention'
      ? ['Tracked item', x.label, x.when]
      : [x.who || 'Someone', x.group, x.voice && x.when ? `🎤 ${x.when}` : x.when];
  return parts.filter(Boolean).join(' · ');
}

/** A result's words, cut for the list. */
export function preview(text, max = 220) {
  const s = String(text || '').replace(/\s+/g, ' ').trim();
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`;
}

/** Only WhatsApp messages and daily-report entries open in context. */
export function opensContext(r) {
  return !!r && (r.source === 'whatsapp' || r.source === 'daily_report') && !!r.id;
}

/** The answer box: "found" (cited claims) or the no-source line. */
export function answerState(answer) {
  if (!answer) return null;
  const claims = Array.isArray(answer.claims) ? answer.claims : [];
  if (!claims.length) return { found: false, text: NO_SOURCE, claims: [] };
  // lead: "No record that the dumpster was swapped." when the records only
  // hold a plan for something the question asks was done.
  return { found: true, timeline: answer.mode === 'timeline', claims,
           lead: typeof answer.lead === 'string' ? answer.lead : '' };
}

/** A claim's head line: the timeline date, the words, and who relayed a
 *  decision someone else made ("(relayed by Wendy Cho)"). */
export function claimLine(c, timeline) {
  const x = c || {};
  const head = timeline && x.date ? `${x.date} — ${x.text || ''}` : (x.text || '');
  // A plan line already says whose plan it is: "(Roy Fishman, Oct 2)".
  return x.relayed_by && !x.planned ? `${head} (relayed by ${x.relayed_by})` : head;
}

/** Every source that shows a claim, each with its own words: one fact,
 *  several chips. */
export function claimSources(c) {
  const x = c || {};
  const first = x.source ? [{ ...x.source, quote: x.quote }] : [];
  return first.concat(Array.isArray(x.also) ? x.also : []);
}
