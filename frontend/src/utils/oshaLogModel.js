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
 * THE KEYS THE BACKEND ACTUALLY SENDS.
 *
 * This read `cert.name` and `cert.expiry`. A stored certification carries
 * neither: it is `{type, card_number, issue_date, expiration_date, verified,
 * needs_review, ...}` (backend/server.py:2006-2016, 2061-2071), and
 * /checkins-today passes the stored dicts through UNTOUCHED (server.py:17559).
 * So every auto-built row on every OSHA register carried a blank certification
 * type and a blank expiry — only card_number ever matched — and that is what
 * printed on the filed document.
 *
 * `expiry` and `name` are still read as fallbacks. Nothing in the current
 * backend writes them, but a hand-entered or legacy row may, and dropping a
 * value that IS there would trade one blank column for another.
 */

// The stored enum -> what a DOB inspector should read. Translation only: every
// value here is one of the seven the backend can store (server.py:1894-1901).
// An UNKNOWN code passes through VERBATIM rather than being guessed at — this
// deliberately infers no card class, which is Part 3A's job.
const CERT_TYPE_LABELS = Object.freeze({
  OSHA_10: 'OSHA 10',
  OSHA_30: 'OSHA 30',
  OSHA_UNSPECIFIED: 'OSHA',
  SST_FULL: 'SST',
  SST_LIMITED: 'SST Limited',
  SST_SUPERVISOR: 'SST Supervisor',
  SST_TEMPORARY: 'SST Temporary',
  // SST_UNSPECIFIED is deliberately absent: "an SST card is present but its
  // class could not be read" must not print as a class. It falls through to
  // the verbatim branch below and reads SST_UNSPECIFIED, which is ugly and
  // true. Part 3A decides what it should say.
});

export function certLabel(cert) {
  if (!cert || typeof cert !== 'object') return '';
  const raw = String(cert.type ?? cert.name ?? '').trim();
  if (!raw) return '';
  return CERT_TYPE_LABELS[raw] || raw;
}

/**
 * `expiration_date` is a datetime the API serialises to an ISO string, and the
 * register prints a date. Anything unparseable is echoed as stored — a value
 * this function does not understand is still a value the CP may need to see.
 */
export function certExpiration(cert) {
  if (!cert || typeof cert !== 'object') return '';
  const raw = cert.expiration_date ?? cert.expiry ?? '';
  const s = String(raw ?? '').trim();
  if (!s) return '';
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(s);
  return m ? m[1] : s;
}

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
          certification_type: certLabel(cert),
          card_number: (cert && cert.card_number) || c.osha_number || '',
          expiration: certExpiration(cert),
          signed: false,
          date,
        });
      }
    } else {
      out.push({
        worker_id: c.worker_id ?? null,
        worker_name: c.worker_name || '',
        company: c.company || '',
        // NO FABRICATED CLASS. This branch used to write the literal
        // 'OSHA 40hr' whenever a worker had an OSHA number — asserting a
        // 40-hour credential onto a DOB record on the strength of a number
        // being present, which establishes that a card exists and nothing
        // whatever about its class. Device round 4 read it back off a filed
        // register. Blank is honest; a credential nobody verified is not.
        //
        // The column stays blank until real card data exists to fill it.
        // /checkins-today hardcodes `certifications: []` on the gate pass
        // (server.py:17499) and worker_enrollments is empty on the tested
        // project, so there is currently no source for either the class or
        // the expiry. certLabel/certExpiration are still reached on any row
        // that DOES carry certifications.
        certification_type: '',
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
 * NO LONGER THE FILING RULE, and the split is the point. This still answers
 * "did the CP put anything in this row" — it is what the row pip and the
 * "N rows" count read, so a half-typed row still shows as work in progress.
 * Whether the row may be FILED is `entryNamesWorker` below, and the rows where
 * the two answers DISAGREE are exactly what the submit gate names.
 *
 * It used to be both, mirroring the renderer's five-field seed-skip. That rule
 * let a row with a card number and no name onto a signed register.
 */
export function entryHasContent(entry) {
  if (!entry || typeof entry !== 'object') return false;
  return ['worker_name', 'company', 'certification_type', 'card_number', 'expiration']
    .some((k) => String(entry[k] ?? '').trim() !== '');
}

/**
 * AN OSHA ENTRY MUST CARRY A WORKER.
 *
 * A certification register is a list of statements about NAMED MEN: this man
 * holds this card, which expires on this date. A row with a company, a card
 * number and a signature mark but no name is not an incomplete record of
 * someone — it is an assertion about a man the document does not identify, and
 * that is worse than the abandoned blank row this file already refused. Nobody
 * can be checked against it, and nobody can be cleared by it.
 *
 * So the name is the one field that decides whether the row is filed, and
 * every other field is detail ON a row that already names somebody.
 *
 * MIRRORS THE RENDERERS, which is where this rule now lives on the server too:
 * _SUBMIT_ROW_CONTENT_RULES["osha_log"] (backend/server.py) is `worker_name`
 * alone, and both PDF renderers drop the same rows. What is filed and what is
 * printed are the same register.
 */
export function entryNamesWorker(entry) {
  if (!entry || typeof entry !== 'object') return false;
  return String(entry.worker_name ?? '').trim() !== '';
}

/**
 * The rows the CP typed into that WILL NOT BE FILED, and why they will not.
 *
 * Content but no name — the gap between the two predicates above. Returns the
 * 1-based row NUMBER as it reads on screen plus whatever the row does carry,
 * because a refusal that does not point at a row is a dead end on a register
 * that may run to thirty of them.
 *
 * An untouched seed row is NOT here: it says nothing, it is dropped silently,
 * and it has been dropped silently since the row-content rule shipped. Only a
 * row the CP put something into is worth stopping him for.
 */
export function unnamedEntries(entries) {
  const out = [];
  (Array.isArray(entries) ? entries : []).forEach((e, i) => {
    if (entryNamesWorker(e)) return;
    if (!entryHasContent(e)) return;
    out.push({
      row: i + 1,
      company: String((e && e.company) ?? '').trim(),
      card_number: String((e && e.card_number) ?? '').trim(),
      certification_type: String((e && e.certification_type) ?? '').trim(),
    });
  });
  return out;
}

/**
 * EDITING THE NAME ON A ROW DETACHES ITS worker_id.
 *
 * THE DEFECT THIS EXISTS TO STOP, from production (project
 * 6a5f63bc147407d3261df2c7, 2026-08-11): one worker_id appeared TWICE in a
 * signed register — once as the man the gate recorded, once as a different man
 * entirely. A subcontractor's certification was filed against another
 * subcontractor's worker record. On a compliance document that is a false
 * statement about who holds that card.
 *
 * HOW IT HAPPENED. The register auto-builds ONE ROW PER CERTIFICATION, so a
 * worker holding two cards gets two rows carrying the same worker_id and the
 * same name. That reads as a duplicate. The CP typed a second man's name over
 * what looked like a spare row — and the row kept the first man's id, because
 * the edit only ever touched `worker_name`.
 *
 * It was NOT the "add a worker" button: that mints EMPTY_ENTRY, whose
 * worker_id is null, and never could have inherited one.
 *
 * THE RULE. A worker_id is a claim about WHO this row is, and it is only good
 * for the name the gate attached it to. The moment that name is edited the app
 * can no longer stand behind the claim, so it stops making it. null is honest:
 * the app cannot identify him. Another man's id is not.
 *
 * THE COST, accepted deliberately: correcting a typo in a gate-recorded name
 * also detaches the id, because nothing here can tell a typo from a different
 * person. Losing a link is recoverable; filing a certification against the
 * wrong worker record is not.
 */
export function applyEntryEdit(entry, field, value) {
  const next = { ...entry, [field]: value };
  if (
    field === 'worker_name'
    && entry
    && entry.worker_id !== null
    && entry.worker_id !== undefined
    && String(value ?? '').trim() !== String(entry.worker_name ?? '').trim()
  ) {
    next.worker_id = null;
  }
  return next;
}

/**
 * The rows that may be FILED: the ones that name a worker.
 *
 * WIDENED FROM "the row says something" TO "the row names somebody" — device
 * round 6. The old rule kept an abandoned blank row off the register, which
 * was the production defect it was written for, and let through the worse
 * shape: a row carrying a card number and a signature mark against no name at
 * all. Both are now dropped, for the same reason and by the same call.
 *
 * Uses the SAME rule both PDF renderers drop rows by, so the register that is
 * filed and the register that is printed contain exactly the same rows. The
 * CP is told which rows these are BEFORE this runs — see unnamedEntries and
 * the submit gate in app/logbooks/osha_log.jsx — so nothing is ever deleted
 * out from under him without a sentence naming it.
 */
export function entriesForFiling(entries) {
  return (Array.isArray(entries) ? entries : []).filter(entryNamesWorker);
}

/**
 * worker_ids carried by more than one row.
 *
 * NOT AN ERROR — it is the approved shape. One row per certification means a
 * man with two cards is two rows, and both are his. The screen labels them so
 * they read as two CARDS rather than as one worker listed twice, which is the
 * misreading that produced the defect above.
 */
export function sharedWorkerIds(entries) {
  const counts = new Map();
  for (const e of (Array.isArray(entries) ? entries : [])) {
    const id = e && e.worker_id;
    if (id === null || id === undefined || id === '') continue;
    counts.set(String(id), (counts.get(String(id)) || 0) + 1);
  }
  return new Set([...counts.entries()].filter(([, n]) => n > 1).map(([id]) => id));
}

/**
 * Which steps the CP has LEFT incomplete. Never gates — the stepper marks, and
 * a CP who cannot complete a step because the data is not there must still be
 * able to finish and sign his day.
 *
 * Step 1 is the register: incomplete when not one row WILL BE FILED. A screen
 * full of rows that all get dropped at filing is an incomplete step, not a
 * complete one, so the pip asks the filing question rather than the touched
 * question.
 * Step 2 is the signature.
 */
export function incompleteSteps({ entries, cpSignature }) {
  const out = [];
  const rows = Array.isArray(entries) ? entries : [];
  if (!rows.some(entryNamesWorker)) out.push(1);
  if (!String(cpSignature || '').trim()) out.push(2);
  return out;
}

/** The payload body. The ONE place the shape is decided. */
export function draftBody(entries) {
  return { entries: Array.isArray(entries) ? entries : [] };
}

export default {
  CERT_TYPES,
  CERT_TYPE_LABELS,
  certLabel,
  certExpiration,
  ENTRY_KEYS,
  EMPTY_ENTRY,
  buildEntriesFromCheckins,
  entryHasContent,
  entryNamesWorker,
  unnamedEntries,
  applyEntryEdit,
  entriesForFiling,
  sharedWorkerIds,
  incompleteSteps,
  draftBody,
};
