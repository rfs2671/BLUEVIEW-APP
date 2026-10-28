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
 *
 * A decided item may be decided again with a NEW explanation (the server
 * keeps every decision in `decisions`; the same explanation is a 409).
 * Nobody is notified of a decision: customers do not flag answers.
 */

export const MIN_EXPLANATION = 10;

export const REASON_LABEL = {
  conflict: 'Conflicting sources',
  replaced: 'Answer replaced',
  unverified: 'Unverified claim',
  set_health_failed: 'Set health: failed',
  set_health_info: 'Set health: info',
  registration: 'Registration refused',
  set_ambiguity: 'Set ambiguity',
};

export const KIND_LABEL = {
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

const norm = (t) => String(t || '').trim().replace(/\s+/g, ' ').toLowerCase();

/** The decide request, or why not yet. The explanation is required; a
 *  re-decision needs a new one (`previous` is the current decision's). */
export function decideRequest(decision, explanation, previous) {
  if (decision !== 'approve' && decision !== 'deny') {
    return { error: 'Choose approve or deny.' };
  }
  const text = String(explanation || '').trim();
  if (text.replace(/\s+/g, ' ').length < MIN_EXPLANATION) {
    return { error: `Write an explanation (at least ${MIN_EXPLANATION} characters).` };
  }
  if (previous && norm(previous) === norm(text)) {
    return { error: 'To decide this again, write a new explanation.' };
  }
  return { body: { decision, explanation: text } };
}

export function fmtWhen(at) {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return String(at);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

function decisionView(dec) {
  return {
    text: dec.decision === 'approve' ? 'Approved' : 'Denied',
    explanation: dec.explanation || '',
    when: fmtWhen(dec.decided_at),
  };
}

function gateLine(g) {
  if (!g || typeof g !== 'object') return String(g || '');
  const name = g.gate || 'check';
  const said = g.outcome || g.stop || g.decision || '';
  return said ? `${name}: ${said}` : name;
}

/** An answer_log row as the screen shows it (null when there is none). */
export function answerView(ans) {
  if (!ans || typeof ans !== 'object') return null;
  const records = Array.isArray(ans.records) ? ans.records : [];
  return {
    id: ans.id || '',
    question: ans.question || '',
    answer: ans.final_text || '',
    records: records.map((r) => ({
      key: r.id || `${r.sheet || ''}|${r.text || ''}`,
      sheet: r.sheet || '',
      text: r.text || (r.text_sha256 ? '(message source: words not kept)' : ''),
    })),
    recordsMore: ans.records_total > records.length ? ans.records_total - records.length : 0,
    gates: Array.isArray(ans.gates) ? ans.gates.map(gateLine) : [],
    build: [ans.model, ans.code_sha].filter(Boolean).join(' · '),
    when: fmtWhen(ans.created_at),
    surface: ans.surface || '',
  };
}

/** One item, as text. Works on whatever shape came back (never throws). */
export function itemView(item) {
  const it = item && typeof item === 'object' ? item : {};
  const ans = answerView(it.answer);
  const dec = it.decision && typeof it.decision === 'object' ? it.decision : null;
  const company = it.company && typeof it.company === 'object' ? it.company : {};
  const project = it.project && typeof it.project === 'object' ? it.project : null;
  return {
    key: `item:${it.id || ''}`,
    id: it.id || '',
    label: reasonLabel(it.reason, it.kind),
    low: it.priority === 'low',
    pending: it.status === 'pending',
    company: company.name || company.id || 'No company',
    project: project ? (project.name || project.id) : null,
    when: fmtWhen(it.created_at),
    summary: it.summary || '',
    answerLog: ans,
    question: ans ? ans.question : null,
    answer: ans ? ans.answer : null,
    records: ans ? ans.records : [],
    recordsMore: ans ? ans.recordsMore : 0,
    gates: ans ? ans.gates : [],
    build: ans ? ans.build : '',
    evidence: it.evidence && typeof it.evidence === 'object' ? it.evidence : null,
    decision: dec ? decisionView(dec) : null,
    // Every decision, newest first (the server keeps them oldest first).
    history: (Array.isArray(it.decisions) ? it.decisions : [])
      .filter((x) => x && typeof x === 'object').map(decisionView).reverse(),
  };
}

/** The list after a decision: the decided item replaced, or dropped when
 *  its new status no longer matches the status filter being shown. */
export function reconcileAfterDecision(list, id, fresh, statusFilter) {
  const rows = Array.isArray(list) ? list : [];
  if (!fresh || typeof fresh !== 'object') return rows;
  if (statusFilter && fresh.status && fresh.status !== statusFilter) {
    return rows.filter((r) => r.id !== id);
  }
  return rows.map((r) => (r.id === id ? fresh : r));
}

/** The company chips: the companies with items, plus the selected one when
 *  it has none in this status (so it can always be seen and cleared). */
export function companyChoices(companies, selected) {
  const list = Array.isArray(companies) ? companies.filter((c) => c && c.id) : [];
  if (selected && !list.some((c) => c.id === selected)) {
    return list.concat([{ id: selected, name: null }]);
  }
  return list;
}
