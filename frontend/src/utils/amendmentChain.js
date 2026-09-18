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
/**
 * THE SENTENCE PRINTED ABOVE THE WITHDRAWAL PAD.
 *
 * MIRRORS server.py's WITHDRAWAL_ATTESTATION_STATEMENT, word for word, and
 * amendmentWithdrawn.test.cjs asserts the two are identical. The server stores
 * this string on the document beside the ink, because a signature with no
 * recorded sentence above it attests to nothing nameable — you can prove a man
 * drew a mark and not what he was told it meant. If the client showed a
 * DIFFERENT sentence, the record would say a man was told something he was
 * never told, which is worse than storing no sentence at all.
 *
 * It lives here rather than in the banner because the server owns the copy of
 * record and this file is already where the client's half of the amendment
 * vocabulary lives (isFiled, isWithdrawn, amendmentSentence).
 */
export const WITHDRAWAL_ATTESTATION_STATEMENT =
  'I am withdrawing this proposed correction. It was never filed, it is not '
  + 'part of the record, and the log it proposed to correct is unchanged.';

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

/**
 * THE KEY THAT WORKS FOR EVERY TYPE, AND WHY `chainKey` WAS NOT IT.
 *
 * `chainKey` reads `data.worker_id` / `data.worker_name`, which resolves for
 * `subcontractor_orientation` and NO OTHER TYPE. Measured on production:
 * orientation 96 documents keyed; daily_jobsite 64, toolbox_talk 69,
 * preshift_signin 55, osha_log 44, scaffold_maintenance 14,
 * site_superintendent_log 11 all returned null and were passed through
 * UNCOLLAPSED -- 32 of the 47 live amendment children are those types. So the
 * one helper written to stop a chain rendering flat only ever stopped it for
 * one of thirteen log types.
 *
 * `parent_logbook_id` IS WHAT AMEND_LOGBOOK WRITES, for every type, and until
 * now nothing in this codebase read it back to group by. It is the chain
 * itself rather than a proxy for it.
 *
 * ── THE WALK GOES ALL THE WAY UP ─────────────────────────────────────
 *
 * Chains reach depth 4 in production and 11 live children have a parent that
 * is ITSELF an amendment, so a rule that read one link and stopped would put a
 * grandchild in its own group and draw the inspector two records again.
 *
 * A PARENT THAT IS NOT IN THE LIST ENDS THE WALK, and the row becomes its own
 * root. That is fail-open: an amendment whose parent is not on screen is
 * SHOWN, rather than filtered into a group that does not contain it. A filed
 * compliance record must never vanish off a list to make one tidy.
 *
 * CYCLE-SAFE, because a self-parent or a pair naming each other is a write
 * nobody has ruled out and an infinite loop here is a frozen screen.
 */
export const parentId = (o) => {
  const pid = String((o && o.parent_logbook_id) || '').trim();
  return pid || null;
};

export function chainRoot(row, byId) {
  let node = row;
  const seen = new Set([String(rowId(row) || '')]);
  for (;;) {
    const pid = parentId(node);
    if (!pid || seen.has(pid) || !byId.has(pid)) return node;
    seen.add(pid);
    node = byId.get(pid);
  }
}

const isFiled = (o) => !!(o && (o.is_locked || o.status === 'submitted'));

/**
 * A CORRECTION ITS AUTHOR TOOK BACK.
 *
 * `POST /logbooks/{id}/withdraw` sets `status: 'withdrawn'` on an unsigned
 * amendment child. The document survives — data, reason, author, parent link
 * all intact — but it is no longer a correction anybody is proposing.
 *
 * WHY THE CLIENT CHECKS AT ALL when the list endpoint already excludes them.
 * Two reasons, and both are live on this project:
 *
 *   THE CACHE. subcontractor_orientation.jsx runs `collapseChains` over a
 *   CACHED roster when it is offline. That cache can be older than the
 *   withdrawal, and a CP with no signal would be told he has a competing
 *   correction open on a record nobody is correcting.
 *
 *   THE BUNDLE. A phone in the field cannot take an OTA for weeks, and this
 *   module is what its screens read. The rule has to be in both halves.
 */
const isWithdrawn = (o) => !!(o && o.status === 'withdrawn');

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
 *   _competing_records   the same refusal, for FILED links. `_open_corrections`
 *                        cannot see this case -- a filed child is not open --
 *                        and production carries six parents with two live
 *                        children. Where both are filed, the newest-first
 *                        tie-break below picks one and the other correction
 *                        leaves the record with nothing saying it was filed.
 *                        A fork must surface as a fork, never as a silent
 *                        choice.
 *
 *                        IT IS THE FILED LINKS OFF THE HEAD'S OWN ANCESTRY,
 *                        which is what makes it depth-independent: on a linear
 *                        chain of any length every filed link IS an ancestor of
 *                        the head, so the list is empty; only a branch produces
 *                        an entry.
 *
 *                        AND IT REQUIRES A PARENT LINK. Without that clause two
 *                        separate ORIGINALS of one worker's orientation -- rows
 *                        this module groups by worker, which amend nothing --
 *                        would each report the other as a competing correction.
 *                        A competing record is a CORRECTION somebody filed
 *                        against this record.
 */
export function chainHead(rows) {
  const all = (rows || []).filter(Boolean);
  if (all.length === 0) return null;

  // WITHDRAWN LINKS LEAVE THE CHAIN ENTIRELY, not just `_open_corrections`.
  // `_chain_length` is what tells a reader "this record was corrected N
  // times", and a correction that was taken back corrected nothing — counting
  // it would say the record changed shape when it never did.
  //
  // THE FALLBACK IS NOT DECORATIVE. If every row were withdrawn this would
  // return null and `collapseChains` would DROP the worker from the list — an
  // orientation vanishing off a compliance screen. The endpoint only ever
  // withdraws amendment children, so a parent is always present in practice;
  // this is what makes that a fact about the data rather than a dependency.
  const list = all.filter((o) => !isWithdrawn(o));
  if (list.length === 0) {
    return {
      ...all[0], _chain_length: all.length,
      _open_corrections: [], _competing_records: [],
    };
  }

  const filed = list.filter(isFiled).sort(newestFirst);
  const open = list.filter((r) => !isFiled(r)).sort(newestFirst);
  const record = filed[0] || null;

  // No filed link at all: the original is still a draft. That is the ordinary
  // pre-signature state, NOT an open correction — calling it one would tell a
  // CP he has a correction outstanding on a record he has not filed yet.
  if (!record) {
    return {
      ...open[0], _chain_length: list.length,
      _open_corrections: [], _competing_records: [],
    };
  }

  // The head's own ancestry: the documents this record was built from. Every
  // filed link on it is superseded BY the head and is not competing with it.
  const byId = new Map();
  list.forEach((o) => { const id = rowId(o); if (id) byId.set(String(id), o); });
  const path = [];
  let node = record;
  while (node) {
    const nid = String(rowId(node) || '');
    if (path.indexOf(nid) !== -1) break;
    path.push(nid);
    const pid = parentId(node);
    node = pid ? byId.get(pid) : null;
  }

  return {
    ...record,
    _chain_length: list.length,
    _open_corrections: open.map((o) => ({
      id: rowId(o),
      created_at: o.created_at || null,
    })),
    _competing_records: filed
      .filter((o) => parentId(o) && path.indexOf(String(rowId(o) || '')) === -1)
      .map((o) => ({ id: rowId(o), created_at: o.created_at || null })),
  };
}

/**
 * One row per RECORD. Rows that cannot be keyed at all are passed through
 * rather than dropped — an unkeyable orientation is still a record, and losing
 * it from the list would be worse than showing it unchained.
 *
 * ── THE KEY IS THE ROOT'S, AND THE ORDER OF THE TWO MATTERS ──────────
 *
 * Each row is walked to the top of its chain, and the GROUP is keyed on that
 * root's `chainKey` when it has one, and on the root's id when it does not.
 *
 * WORKER FIRST, NOT CHAIN FIRST, and that is deliberate. For orientation both
 * keys exist, and keying on the chain alone would split a worker whose
 * orientation was filed TWICE as two unlinked originals into two rows — a
 * live behaviour change on the orientation editor, in a change that is meant
 * to fix the twelve types the worker key never reached. Keying on the root's
 * worker leaves those orientations grouped exactly as they already are and
 * unions any chain hanging off them; every other type has no worker key,
 * falls to the root id, and is collapsed for the first time.
 *
 * So this is strictly additive: no grouping that already happens stops
 * happening, and the types that were passed through uncollapsed no longer
 * are.
 *
 * ── AND THE WORDING ABOVE IS CONSTRAINED, WHICH IS WORTH KNOWING ─────
 *
 * amendmentVisible.test.cjs bans three clock-relative words by regex against
 * the RAW text of this file, comments included, to prove no rule here reads
 * the clock. That is the right claim about the code and the wrong instrument
 * for it: the scan cannot tell a rule from a sentence describing one, so PROSE
 * can fail a gate about behaviour — which is what the paragraph above had to
 * be rewritten around. Left alone rather than weakened here; recorded in the
 * PR's "found, not changed" list instead.
 */
export function collapseChains(list) {
  const rows = (list || []).filter(Boolean);
  const byId = new Map();
  rows.forEach((r) => { const id = rowId(r); if (id) byId.set(String(id), r); });

  const groups = new Map();
  const unkeyed = [];
  rows.forEach((row) => {
    const root = chainRoot(row, byId);
    const rootId = rowId(root);
    const key = chainKey(root)
      || (rootId ? `chain:${String(rootId)}` : chainKey(row));
    if (!key) { unkeyed.push(row); return; }
    groups.set(key, (groups.get(key) || []).concat(row));
  });
  const out = [];
  groups.forEach((group) => {
    const head = chainHead(group);
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
