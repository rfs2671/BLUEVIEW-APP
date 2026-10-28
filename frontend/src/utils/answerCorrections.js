/**
 * OWNER PORTAL → "MARK WRONG" (platform operator only). What the Answers
 * screen and the review queue's Mark wrong form SAY and SEND. Pure and
 * tested (answerCorrections.test.cjs); the screens only fetch and draw.
 *
 * A correction is append-only on the server: marking an answer wrong again
 * adds a new correction, and the newest is the current one.
 */

import { answerView, fmtWhen } from './reviewQueue';

export const MIN_CORRECT = 2;
export const MAX_NOTE = 2000;

export const SURFACE_LABEL = { dm: 'DM', group: 'Group', app: 'App' };

/** The POST body, or why not yet. The correct answer is required; the note
 *  is optional (an empty note is not sent). */
export function correctionRequest(correctAnswer, note) {
  const text = String(correctAnswer || '').trim();
  if (text.replace(/\s+/g, ' ').length < MIN_CORRECT) {
    return { error: 'Write the correct answer.' };
  }
  const n = String(note || '').trim();
  if (n.length > MAX_NOTE) return { error: `The note is over ${MAX_NOTE} characters.` };
  return { body: n ? { correct_answer: text, note: n } : { correct_answer: text } };
}

/** One correction, as text. */
export function correctionView(c) {
  const it = c && typeof c === 'object' ? c : {};
  return {
    key: it.id || `${it.ts || ''}|${it.correct_answer || ''}`,
    correct: it.correct_answer || '',
    note: it.note || '',
    when: fmtWhen(it.ts),
  };
}

/** One row of GET /api/owner/answers, as text (never throws). */
export function answerRowView(row) {
  const r = row && typeof row === 'object' ? row : {};
  const ans = answerView(r.answer) || {
    id: '', question: '', answer: '', records: [], recordsMore: 0, gates: [], build: '',
    when: '', surface: '',
  };
  const company = r.company && typeof r.company === 'object' ? r.company : {};
  const n = Number(r.corrections_count) || 0;
  return {
    ...ans,
    key: `answer:${ans.id}`,
    company: company.name || company.id || 'No company',
    surfaceLabel: SURFACE_LABEL[ans.surface] || ans.surface || '',
    corrections: n,
    correctionsLabel: n === 0 ? '' : (n === 1 ? 'Marked wrong' : `Marked wrong ×${n}`),
  };
}

/** The search request's query. */
export function searchParams({ q, company, surface, offset, limit } = {}) {
  const p = {};
  const text = String(q || '').trim();
  if (text) p.q = text;
  if (company) p.company_id = company;
  if (surface) p.surface = surface;
  if (offset) p.offset = offset;
  if (limit) p.limit = limit;
  return p;
}
