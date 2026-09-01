/**
 * An amendment chain, collapsed to the record it currently is.
 *
 * THE OPERATOR'S REPORT. Angel Lopez showed SIX rows on 588 Thomas: one
 * orientation and five amendments of it, drawn as siblings with nothing saying
 * which was current. `GET /logbooks/project/...` does not filter
 * `is_amendment`, so every link in the chain comes back and every screen that
 * maps the list draws a card per link. It read as a duplication bug and was
 * not one — it was a chain, rendered flat.
 *
 * ONE IMPLEMENTATION, TWO CONSUMERS. The orientation editor and the reports
 * tab had the same defect, and a rule written twice is two rules the moment
 * one is edited. That is the failure this codebase spent 2026-08-31 on: a
 * field with a governing decision in one place and a second writer that never
 * found it.
 *
 * THE HEAD IS THE DEEPEST SIGNED LINK — the same rule `_filed_log` applies on
 * the server. An unsigned amendment is an INTENTION, not a correction, and it
 * must never present as the record.
 */

/** The stored id for a row, whichever shape the caller has. */
export const rowId = (o) => (o && (o.id || o._id)) || null;

/**
 * WHAT MAKES TWO ROWS THE SAME MAN.
 *
 * `worker_id` when there is one; the NAME only as a fallback for rows that
 * carry no id at all.
 *
 * NEVER BY NAME ALONE WHEN AN ID EXISTS. Two different worker_ids that happen
 * to share a name are two men, and merging them would put one man's
 * orientation on another man's compliance record — worse than the same man
 * appearing twice, which is merely untidy. Two Angel Lopezes on one site is
 * ordinary; a signed record attributing one's orientation to the other is not.
 *
 * So: id-bearing rows group ONLY with the same id. Id-less rows group among
 * themselves by name, which is the best available and is never allowed to
 * absorb a row that has an id.
 */
export const chainKey = (o) => {
  const wid = o && o.data && o.data.worker_id;
  if (wid) return `id:${String(wid)}`;
  const name = String((o && o.data && o.data.worker_name) || '').trim().toLowerCase();
  return name ? `name:${name}` : null;
};

const isFiled = (o) => !!(o && (o.is_locked || o.status === 'submitted'));

const newestFirst = (a, b) => {
  const ta = Date.parse((a && a.created_at) || '') || 0;
  const tb = Date.parse((b && b.created_at) || '') || 0;
  if (ta !== tb) return tb - ta;
  return String(rowId(b) || '').localeCompare(String(rowId(a) || ''));
};

/**
 * The head of one worker's chain, annotated with what is outstanding.
 *
 *   _chain_length        how many documents this record is made of. A reader
 *                        cannot tell an amended record from an original
 *                        without it — the head looks like a first draft.
 *   _open_corrections    every UNSIGNED link, newest first. Plural on purpose:
 *                        588 Thomas has a FORK, two competing unsigned
 *                        children of one parent, and showing one of them would
 *                        be picking a winner silently.
 */
export function chainHead(rows) {
  const list = (rows || []).filter(Boolean);
  if (list.length === 0) return null;

  const filed = list.filter(isFiled).sort(newestFirst);
  const open = list.filter((r) => !isFiled(r)).sort(newestFirst);
  const record = filed[0] || null;

  // No filed link at all: the original is still a draft. That is the ordinary
  // pre-signature state, NOT an open correction — calling it one would tell a
  // CP he has a correction outstanding on a record he has not filed yet.
  if (!record) {
    return { ...open[0], _chain_length: list.length, _open_corrections: [] };
  }

  return {
    ...record,
    _chain_length: list.length,
    _open_corrections: open.map((o) => ({
      id: rowId(o),
      created_at: o.created_at || null,
    })),
  };
}

/**
 * One row per worker. Rows that cannot be keyed at all are passed through
 * rather than dropped — an unkeyable orientation is still a record, and losing
 * it from the list would be worse than showing it unchained.
 */
export function collapseChains(list) {
  const groups = new Map();
  const unkeyed = [];
  (list || []).forEach((row) => {
    const key = chainKey(row);
    if (!key) { unkeyed.push(row); return; }
    groups.set(key, (groups.get(key) || []).concat(row));
  });
  const out = [];
  groups.forEach((rows) => {
    const head = chainHead(rows);
    if (head) out.push(head);
  });
  return [...out, ...unkeyed];
}

/**
 * The sentence the CP reads about an open correction.
 *
 * THE DEFECT THIS REPLACES, from his dashboard on 2026-09-01:
 *
 *   "A correction was filed by Michael Cespedes on 2026-08-14. Photo Review it
 *    and sign."
 *
 * "Photo" is the ENTIRE stored amendment_reason on that child, not a
 * truncation. The card interpolated it raw — `${lead} ${a.reason} Review it
 * and sign.` — so any reason without ending punctuation ran into the next
 * clause. Every amendment filed before the readability rule can be a fragment
 * like that, and the four "1" reasons on 588 Thomas are the extreme case.
 *
 * IT IS QUOTED, NOT PUNCTUATED. Appending a full stop to "Photo" would present
 * a fragment as prose somebody wrote. Quoting reports it as the text that was
 * recorded — which is what it is — and makes it structurally impossible to run
 * into the following clause whatever it contains.
 *
 * Everything comes off the record: no clock, nothing relative.
 */
export function amendmentSentence(a) {
  const tail = 'Review it and sign.';
  if (!a) return `A correction was filed on this log. ${tail}`;
  const who = a.by ? ` by ${a.by}` : '';
  const when = a.at ? ` on ${a.at}` : '';
  const lead = `A correction was filed${who}${when}.`;
  const reason = a.has_reason && a.reason ? String(a.reason).trim() : '';
  if (!reason) return `${lead} No reason was recorded for it. ${tail}`;
  return `${lead} Reason given: "${reason}". ${tail}`;
}

/**
 * The status pill for one log TYPE on one day.
 *
 * THE DEFECT THIS REPLACES: the screen built `logMap[log.log_type] = log`, so
 * 34 orientation documents collapsed to whichever the array happened to end
 * with. When that was an unsigned Angel Lopez amendment the type read "Draft"
 * over 33 signed workers — and since the endpoint sorts by `date`, the winner
 * within one date was unspecified and could differ between loads.
 *
 * IT IS NOT "ANY DRAFT EXISTS", AND MUST NOT BECOME THAT. An unsigned
 * amendment is an open CORRECTION on a filed record, not unfinished work: the
 * record is filed, and the stale-unsigned card is what surfaces the
 * correction. Reading "Draft" would tell a CP his signed day is unfinished.
 *
 * So the question is: is every worker's CURRENT record filed? Chain heads —
 * the same rule the list uses, so the pill and the rows cannot disagree.
 */
export function logTypeStatus(rows) {
  const heads = collapseChains(rows);
  if (heads.length === 0) return 'pending';
  const filed = (h) => !!(h && (h.is_locked || h.status === 'submitted'));
  return heads.every(filed) ? 'submitted' : 'draft';
}

export default collapseChains;
