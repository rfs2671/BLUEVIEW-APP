/**
 * OWNER PORTAL → REVIEW QUEUE (platform operator only; L6.4). What the
 * screen SAYS and SENDS, from what /api/owner/review-queue returned. Pure and
 * tested (reviewQueue.test.cjs); the screen only fetches and draws.
 *
 * The server is the boundary: every /api/owner route answers 404 to anyone
 * who is not the operator. Nothing here decides access.
 *
 * DEFAULT VIEW "Needs decision": pending items of normal priority. Low
 * priority (set_health_info) is behind "Show low priority".
 */

export const MIN_EXPLANATION = 10;

export const REASON_LABEL = {
  dispute: 'Dispute',
  conflict: 'Conflicting sources',
  replaced: 'Answer replaced',
  unverified: 'Unverified claim',
  set_health_failed: 'Set health: failed',
  set_health_info: 'Set health: info',
  registration: 'Registration refused',
};

export const KIND_LABEL = {
  dispute: 'Dispute',
  conflicting_sources: 'Conflicting sources',
  set_health: 'Set health',
  registration_refusal: 'Registration refusal',
  plan_set_question: 'Plan set question',
};

export const STATUS_FILTERS = [
  { key: 'pending', label: 'Needs decision' },
  { key: 'approved', label: 'Approved' },
  { key: 'denied', label: 'Denied' },
];

export const REASON_FILTERS = [{ key: '', label: 'All reasons' }].concat(
  Object.keys(REASON_LABEL).map((k) => ({ key: k, label: REASON_LABEL[k] })),
);

export function reasonLabel(reason, kind) {
  if (reason && REASON_LABEL[reason]) return REASON_LABEL[reason];
  if (reason) return String(reason);
  return KIND_LABEL[kind] || String(kind || 'Item');
}

/** The list request's query: the default view sends status=pending,
 *  priority=normal. "Show low priority" widens to every priority. */
export function listParams({ status, reason, company, showLow, offset, limit } = {}) {
  // set_health_info is the low-priority reason: picking it shows it.
  const low = showLow || reason === 'set_health_info';
  const p = { status: status || 'pending', priority: low ? 'all' : 'normal' };
  if (reason) p.reason = reason;
  if (company) p.company_id = company;
  if (offset) p.offset = offset;
  if (limit) p.limit = limit;
  return p;
}

/** The decide request, or why not yet. The explanation is required. */
export function decideRequest(decision, explanation, notify) {
  if (decision !== 'approve' && decision !== 'deny') {
    return { error: 'Choose approve or deny.' };
  }
  const text = String(explanation || '').trim();
  if (text.replace(/\s+/g, ' ').length < MIN_EXPLANATION) {
    return { error: `Write an explanation (at least ${MIN_EXPLANATION} characters).` };
  }
  return { body: { decision, explanation: text, notify: notify === true } };
}

function fmtWhen(at) {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return String(at);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

function gateLine(g) {
  if (!g || typeof g !== 'object') return String(g || '');
  const name = g.gate || 'check';
  const said = g.outcome || g.stop || g.decision || '';
  return said ? `${name}: ${said}` : name;
}

/** One item, as text. Works on whatever shape came back (never throws). */
export function itemView(item) {
  const it = item && typeof item === 'object' ? item : {};
  const ans = it.answer && typeof it.answer === 'object' ? it.answer : null;
  const dec = it.decision && typeof it.decision === 'object' ? it.decision : null;
  const company = it.company && typeof it.company === 'object' ? it.company : {};
  const project = it.project && typeof it.project === 'object' ? it.project : null;
  const records = ans && Array.isArray(ans.records) ? ans.records : [];
  return {
    key: `${it.source || 'item'}:${it.id || ''}`,
    source: it.source || '',
    id: it.id || '',
    label: reasonLabel(it.reason, it.kind),
    low: it.priority === 'low',
    pending: it.status === 'pending',
    company: company.name || company.id || 'No company',
    project: project ? (project.name || project.id) : null,
    when: fmtWhen(it.created_at),
    summary: it.summary || '',
    asker: it.asker ? (it.asker.name || 'Unknown person') : null,
    canNotify: it.source === 'dispute' && !!(it.asker && it.asker.user_id),
    question: ans ? ans.question || '' : null,
    answer: ans ? ans.final_text || '' : null,
    records: records.map((r) => ({
      key: r.id || `${r.sheet || ''}|${r.text || ''}`,
      sheet: r.sheet || '',
      text: r.text || (r.text_sha256 ? '(message source: words not kept)' : ''),
    })),
    recordsMore: ans && ans.records_total > records.length
      ? ans.records_total - records.length : 0,
    gates: ans && Array.isArray(ans.gates) ? ans.gates.map(gateLine) : [],
    build: ans ? [ans.model, ans.code_sha].filter(Boolean).join(' · ') : '',
    evidence: it.evidence && typeof it.evidence === 'object' ? it.evidence : null,
    decision: dec ? {
      text: dec.decision === 'approve' ? 'Approved' : 'Denied',
      explanation: dec.explanation || '',
      when: fmtWhen(dec.decided_at),
      notified: dec.notify === true,
    } : null,
  };
}

/** What to say after a decision. */
export function decideResult(res) {
  const n = (res && res.notify) || {};
  if (n.sent) return 'Decided. The person was sent the note.';
  if (n.reason === 'no_asker') return 'Decided. Not notified: a group asker has no direct chat.';
  if (n.reason === 'not_reachable') return 'Decided. Not notified: they cannot be reached by DM.';
  if (n.reason === 'not_a_dispute') return 'Decided. Nobody to notify for this kind.';
  return 'Decided.';
}
