/**
 * The OSHA / SST certification register — everything that decides what ends up
 * inside the signed record, out of the screen and into a module.
 *
 * WHY A MODULE. The frontend suite here has no renderer: logic inside a
 * component can only be asserted by grepping its source, logic in a module can
 * be EXECUTED. Every function below decides something a DOB inspector reads, so
 * every function below is tested for real — the same reason
 * dailyJobsiteModel.js exists.
 *
 * THE PAYLOAD SHAPE IS FROZEN. `data.entries[]`, with exactly the keys
 * backend/server.py:13458-13490 renders and app/site/logbooks.jsx displays:
 *
 *   worker_id  worker_name  company  certification_type  card_number
 *   expiration  signed  date        (+ blocked / blocks on a gate refusal)
 *
 * A key renamed here silently empties a column on a filed PDF, so
 * oshaLogModel.test.cjs asserts the set rather than trusting the port.
 */

import { easternToday } from './dates';

export const CERT_TYPES = [
  'OSHA 10', 'OSHA 30', 'OSHA 40hr', 'OSHA 62hr', 'SST',
  'Flagman', 'Forklift', 'Scaffold', 'Other',
];

/**
 * The keys every row carries. Exported so a test can assert the payload the
 * screen builds still matches what the renderers read, rather than a copy of
 * this list that drifted.
 */
export const ENTRY_KEYS = Object.freeze([
  'worker_id', 'worker_name', 'company', 'certification_type',
  'card_number', 'expiration', 'signed', 'date',
]);

/**
 * A blank row.
 *
 * TIER 1 — this date is FILED onto the OSHA/SST row, not used for a lookup.
 * toISOString() is UTC, so an entry added after 20:00 EDT (19:00 EST) was
 * stamped with TOMORROW's date. That persists and an inspector reads it.
 */
export const EMPTY_ENTRY = () => ({
  worker_id: null,
  worker_name: '',
  company: '',
  certification_type: '',
  card_number: '',
  expiration: '',
  signed: false,
  date: easternToday(),
});

/**
 * ONE ROW PER CERTIFICATION, which is the shape the operator approved.
 *
 * A worker holding OSHA 30 and an SST card is TWO rows, not one row listing
 * two cards: the register is a list of certifications and each has its own
 * number and its own expiry. A worker with no certification on file still gets
 * a row — he was on site, and an absent row reads as an absent worker.
 *
 * THE DATE IS THE LOG'S DATE, not today's. These rows are built for the day
 * being filed, which on a back-filled log is not the day the CP is standing in.
 * EMPTY_ENTRY's easternToday() is right for a row added BY HAND right now;
 * it would be wrong here.
 */
export function buildEntriesFromCheckins(checkins, date) {
  const out = [];
  for (const c of (Array.isArray(checkins) ? checkins : [])) {
    if (!c || typeof c !== 'object') continue;

    // A worker turned away at the gate for missing OSHA. He is recorded as
    // DENIED and never as a certification: the register would otherwise show
    // him as though he carried a card, and the one fact the gate established
    // is that he did not.
    if (c.blocked) {
      out.push({
        worker_id: c.worker_id ?? null,
        worker_name: c.worker_name || '',
        company: c.company || '',
        certification_type: 'MISSING OSHA',
        card_number: '',
        expiration: '',
        signed: false,
        blocked: true,
        blocks: c.blocks || [],
        date,
      });
      continue;
    }

    const certs = Array.isArray(c.certifications) ? c.certifications : [];
    if (certs.length > 0) {
      for (const cert of certs) {
        out.push({
          worker_id: c.worker_id ?? null,
          worker_name: c.worker_name || '',
          company: c.company || '',
          certification_type: (cert && cert.name) || '',
          card_number: (cert && cert.card_number) || c.osha_number || '',
          expiration: (cert && cert.expiry) || '',
          signed: false,
          date,
        });
      }
    } else {
      out.push({
        worker_id: c.worker_id ?? null,
        worker_name: c.worker_name || '',
        company: c.company || '',
        certification_type: c.osha_number ? 'OSHA 40hr' : '',
        card_number: c.osha_number || '',
        expiration: '',
        signed: false,
        date,
      });
    }
  }
  return out;
}

/**
 * Has this row been touched at all?
 *
 * MIRRORS THE RENDERER, deliberately. backend/server.py:13472 drops a row with
 * none of these five fields as "an untouched EMPTY_ENTRY seed". The screen uses
 * the same rule for its pip, so what the CP sees as incomplete is exactly what
 * the PDF will decline to print.
 */
export function entryHasContent(entry) {
  if (!entry || typeof entry !== 'object') return false;
  return ['worker_name', 'company', 'certification_type', 'card_number', 'expiration']
    .some((k) => String(entry[k] ?? '').trim() !== '');
}

/**
 * Which steps the CP has LEFT incomplete. Never gates — the stepper marks, and
 * a CP who cannot complete a step because the data is not there must still be
 * able to finish and sign his day.
 *
 * Step 1 is the register: incomplete when not one row carries anything.
 * Step 2 is the signature.
 */
export function incompleteSteps({ entries, cpSignature }) {
  const out = [];
  const rows = Array.isArray(entries) ? entries : [];
  if (!rows.some(entryHasContent)) out.push(1);
  if (!String(cpSignature || '').trim()) out.push(2);
  return out;
}

/** The payload body. The ONE place the shape is decided. */
export function draftBody(entries) {
  return { entries: Array.isArray(entries) ? entries : [] };
}

export default {
  CERT_TYPES,
  ENTRY_KEYS,
  EMPTY_ENTRY,
  buildEntriesFromCheckins,
  entryHasContent,
  incompleteSteps,
  draftBody,
};
