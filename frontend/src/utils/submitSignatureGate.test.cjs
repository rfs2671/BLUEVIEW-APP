/**
 * THE SUBMIT GATE, client side.
 *
 * For the nine IMMEDIATE log types the signature IS the freeze: the server locks
 * the record on `status: "submitted"` alone. Five of the nine forms had NO
 * client guard at all, so a CP whose profile carries no saved signature could
 * tap Submit and mint a locked, unsigned legal record — and one of those five is
 * preshift_signin, the morning sign-in.
 *
 * The server gate alone was not acceptable: a rejection with no on-screen reason
 * stops a man at the start of his shift with nothing to act on. So the guard is
 * client-first (button disabled + a hint naming the fix), the drain refuses to
 * replay an unsigned submit, and the server gate is the backstop.
 *
 * WHERE THE CP SETS HIS SIGNATURE — there is no profile screen. Nothing under
 * app/settings or app/profile writes cp_signature; useCpProfile.autoSave
 * persists it AFTER a log is signed. So the hint points at the SignaturePad on
 * the same screen, which every one of the five renders directly above Submit.
 *
 * Everything below runs the REAL shipped source — modules are read, stripped of
 * imports and evaluated against stubs (the technique in
 * draftSync.finalizeGate.test.cjs), so nothing here is a hand-copy of the logic
 * under test.
 *
 * Run:  node src/utils/submitSignatureGate.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const SRC = path.join(UTILS, '..');
const APP_LOGBOOKS = path.join(SRC, '..', 'app', 'logbooks');
const I18N = path.join(SRC, 'i18n');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The nine types whose signature IS the freeze, read out of server.py so this
// list cannot drift from the backend's.
const serverSrc = fs.readFileSync(
  path.join(SRC, '..', '..', 'backend', 'server.py'), 'utf8');
const timingBlock = serverSrc.slice(
  serverSrc.indexOf('LOGBOOK_TIMING_CLASS = {'),
  serverSrc.indexOf('def logbook_timing_class'),
);
const IMMEDIATE = [...timingBlock.matchAll(/"([a-z_]+)":\s*"immediate"/g)].map((m) => m[1]);
ok(IMMEDIATE.length === 9, `server.py declares 9 IMMEDIATE types (got ${IMMEDIATE.length})`);

// The five that had no guard before this change.
const NEWLY_GUARDED = [
  'preshift_signin', 'hot_work', 'concrete_operations',
  'crane_operations', 'excavation_monitoring',
];

// ── 1. every immediate form blocks an unsigned submit ────────────────────────
for (const t of IMMEDIATE) {
  const f = path.join(APP_LOGBOOKS, `${t}.jsx`);
  if (!fs.existsSync(f)) { ok(false, `${t}.jsx exists`); continue; }
  const src = fs.readFileSync(f, 'utf8');
  // subcontractor_orientation derives status FROM the signature rather than
  // disabling a button — structurally unreachable, which is stronger.
  const derives = /const status = newCpSignature \? 'submitted' : 'draft'/.test(src);
  const disables = /disabled=\{!cpSignature/.test(src);
  // A form ported onto the shared stepper does not own its footer button, so it
  // cannot write `disabled=` itself — it passes the same condition through
  // LogbookStepper's `submitDisabled`, which the chrome applies to the one
  // submit Pressable. THE GUARANTEE IS IDENTICAL and is asserted end to end
  // below: this only recognises where the expression now lives.
  const stepperGated = /submitDisabled=\{!cpSignature\}/.test(src);
  ok(derives || disables || stepperGated,
    `${t}: an unsigned submit is unreachable (${derives ? 'status derived' : (disables ? 'button disabled' : 'stepper submitDisabled')})`);
}

// ── 1b. the shared stepper HONOURS submitDisabled ────────────────────────────
//
// Without this, `submitDisabled={!cpSignature}` above would be a prop nobody
// reads and the recognition in 1 would be a hole in the gate rather than a
// second spelling of it. Asserted on the chrome, once, for every form that
// will ever be ported onto it.
const chromeSrc = fs.readFileSync(
  path.join(SRC, 'components', 'logbookStepper', 'LogbookStepper.jsx'), 'utf8');
ok(/submitDisabled = false,/.test(chromeSrc),
  'stepper: submitDisabled is a declared prop, defaulting to enabled');
ok(/disabled=\{submitting \|\| submitDisabled\}/.test(chromeSrc),
  'stepper: the submit button is disabled when the form says so');
ok(/accessibilityState=\{\{ disabled: submitting \|\| submitDisabled \}\}/.test(chromeSrc),
  'stepper: and it says so to a screen reader, not only in the styling');
// The gate must sit on the SUBMIT branch, never on Next — a CP with no
// signature must still be able to walk the form.
const footerSrc = chromeSrc.slice(chromeSrc.indexOf('<View style={s.footer}>'),
  chromeSrc.lastIndexOf('</SafeAreaView>'));
const nextBranch = footerSrc.slice(0, footerSrc.indexOf(') : ('));
ok(!/submitDisabled/.test(nextBranch),
  'stepper: an unsigned CP can still page through the form — only Submit is gated');

// ── 2. the guard is not a dead end ───────────────────────────────────────────
for (const t of NEWLY_GUARDED) {
  const src = fs.readFileSync(path.join(APP_LOGBOOKS, `${t}.jsx`), 'utf8');
  ok(/\{!cpSignature && \(/.test(src) && /submitNeedsSignature/.test(src),
    `${t}: tells the CP WHY submit is unavailable`);
  ok(/profileLoaded \? 'submitNeedsSignature' : 'submitSignatureLoading'/.test(src),
    `${t}: does not accuse a CP of being unsigned while the profile is still loading`);
  ok(/useT\('finalize'\)/.test(src),
    `${t}: the hint goes through i18n, not a hardcoded English string`);
  // The pad it points at must actually be on this screen, above the button.
  const padAt = src.indexOf('<SignaturePad');
  const submitAt = src.indexOf("handleSave('submitted')");
  ok(padAt !== -1 && padAt < submitAt,
    `${t}: the SignaturePad the hint names is on-screen above Submit`);
}

// ── 3. bilingual, and actually translated ────────────────────────────────────
const en = fs.readFileSync(path.join(I18N, 'en.js'), 'utf8');
const es = fs.readFileSync(path.join(I18N, 'es.js'), 'utf8');
const NEW_KEYS = [
  'code_SUBMIT_EMPTY_LOG', 'code_SUBMIT_MISSING_CP_SIGNATURE',
  'submitNeedsSignature', 'submitSignatureLoading',
  'notPushedTitle', 'notPushedHint',
];
const valueOf = (src, key) => {
  const m = new RegExp(`${key}:\\s*'((?:[^'\\\\]|\\\\.)*)'`).exec(src);
  return m ? m[1] : null;
};
// FLIPPED, not dropped. `finalize` is EN-only by ruling: a logbook is a legal
// record filed with the DOB, and these are the CP's lock, refusal and signature
// prompts. The guard still bites — the EN copy must exist, and the ES catalogue
// must NOT carry it, so a well-meant translation cannot quietly reappear.
// A Spanish-locale CP still reads these: translate() falls back to English.
for (const k of NEW_KEYS) {
  ok(Boolean(valueOf(en, k)), `${k}: present in EN`);
  ok(valueOf(es, k) === null, `${k}: absent from ES — CP-facing legal record copy`);
}
ok(!/^\s*finalize:\s*\{/m.test(es),
  'the whole finalize namespace is absent from the ES catalogue');

// ── 4. the server's codes and the client's copy agree ────────────────────────
const SUBMIT_CODES = [...new Set(
  [...serverSrc.matchAll(/"code":\s*"(SUBMIT_[A-Z_]+)"/g)].map((m) => m[1]),
)].sort();
// Three now. SUBMIT_MISSING_TRADE joined them: a safety orientation may be
// CREATED without a trade (the gate check-in writes one that way, and a worker
// at the turnstile is never blocked for an admin's unfinished roster) but may
// not be SUBMITTED without one. Same machine-code convention, no new mechanism.
ok(SUBMIT_CODES.length === 3
  && SUBMIT_CODES.includes('SUBMIT_EMPTY_LOG')
  && SUBMIT_CODES.includes('SUBMIT_MISSING_CP_SIGNATURE')
  && SUBMIT_CODES.includes('SUBMIT_MISSING_TRADE'),
  `server.py returns exactly the 3 submit codes (${SUBMIT_CODES.join(', ')})`);
for (const c of SUBMIT_CODES) {
  ok(en.includes(`code_${c}:`),
    `${c}: has mapped copy, so it never falls back to the generic message`);
}

// ── 5. both server endpoints are gated, not just create ──────────────────────
// The ordinary flow is Save Draft (POST) then Submit — which, because the log
// exists by then, arrives as a PUT. A gate on create alone never sees it.
// Counts RAISE SITES, not mentions: the helper that backs the trade gate names
// this code in its docstring to explain the convention it follows, and a prose
// mention is not a gate. Matching on the detail literal keeps that honest.
const gateHits = (
  serverSrc.match(/detail=\{"code": "SUBMIT_MISSING_CP_SIGNATURE"\}/g) || []
).length;
ok(gateHits === 2, `the signature gate exists in BOTH endpoints (${gateHits} sites)`);
const updateFn = serverSrc.slice(
  serverSrc.indexOf('async def update_logbook'),
  serverSrc.indexOf('async def update_logbook') + 4000,
);
ok(/SUBMIT_MISSING_CP_SIGNATURE/.test(updateFn),
  'update_logbook — the path the CP actually walks — carries the gate');
ok(updateFn.indexOf('SUBMIT_MISSING_CP_SIGNATURE') < updateFn.indexOf('update = {"updated_at"')
   || updateFn.indexOf('SUBMIT_MISSING_CP_SIGNATURE') < updateFn.indexOf('is_locked'),
  'update_logbook: the gate runs BEFORE the lock is written, so a refusal mutates nothing');

// ── 6. LogbookLockBar can surface a refusal for a log that never existed ─────
const lockBar = fs.readFileSync(path.join(SRC, 'components', 'LogbookLockBar.jsx'), 'utf8');
ok(/const handle = logId \|\| draftKey;/.test(lockBar),
  'LockBar: falls back to the draft key when there is no logbook id');
ok(/const neverSaved = !logId;/.test(lockBar),
  'LockBar: distinguishes NOT SAVED from NOT LOCKED');
ok(/neverSaved \? 'notPushedTitle' : 'notLockedTitle'/.test(lockBar),
  'LockBar: a log that was never created does not claim to be merely unlocked');
ok(/\}, \[logId, draftKey\]\);/.test(lockBar),
  'LockBar: re-reads when either handle changes');

// Every form that can be refused must pass the draft key, or the banner is
// invisible on exactly the logs that were never created.
for (const t of [...NEWLY_GUARDED, 'daily_jobsite']) {
  const src = fs.readFileSync(path.join(APP_LOGBOOKS, `${t}.jsx`), 'utf8');
  ok(/draftKey=\{draftKey\(\{/.test(src), `${t}: passes draftKey to LogbookLockBar`);
}

// ── 7. the drain, running for real ───────────────────────────────────────────
const draftSyncSrc = fs.readFileSync(path.join(UTILS, 'draftSync.js'), 'utf8');

function loadDraftSync(env) {
  const body = draftSyncSrc
    .replace(/^import[\s\S]*?;\s*$/gm, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  return new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const NetInfo = __env.NetInfo;
    const logbooksAPI = __env.logbooksAPI;
    const getPendingKeys = __env.getPendingKeys;
    const readDraft = __env.readDraft;
    const setDraftBackendId = __env.setDraftBackendId;
    const clearPending = __env.clearPending;
    const console = __env.console;
    ${body}
    return { syncPendingDrafts, readFinalizeError };
  `)(env);
}

const KEY = 'logbook_draft:proj1:hot_work:2026-08-09';
function makeEnv({ signature, status = 'submitted', backendId = null, createError } = {}) {
  const store = {};
  const calls = { cleared: [], created: [], updated: [] };
  return {
    calls,
    store,
    env: {
      console: { log: () => {}, warn: () => {} },
      NetInfo: { addEventListener: () => () => {} },
      AsyncStorage: {
        getItem: async (k) => (k in store ? store[k] : null),
        setItem: async (k, v) => { store[k] = v; },
      },
      getPendingKeys: async () => [KEY],
      // No `activities` key, so the photo branch is not entered.
      readDraft: async () => ({
        data: { work_type: '', location: '' },
        cp_signature: signature,
        cp_name: 'CP',
        status,
        backend_id: backendId,
        finalized: false,
      }),
      setDraftBackendId: async () => {},
      clearPending: async (k) => { calls.cleared.push(k); },
      logbooksAPI: {
        update: async (id) => { calls.updated.push(id); return { id }; },
        create: async (b) => {
          calls.created.push(b);
          if (createError) throw createError;
          return { id: 'newlog9' };
        },
        finalize: async (id) => ({ id }),
      },
    },
  };
}
const refusal = (code, status = 400) => ({
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail: { code } } },
});

(async () => {
  // An unsigned SUBMIT is never sent at all.
  {
    const h = makeEnv({ signature: null, status: 'submitted' });
    const mod = loadDraftSync(h.env);
    const res = await mod.syncPendingDrafts();
    ok(h.calls.created.length === 0,
      'drain: an unsigned submitted draft is NOT pushed to the server');
    ok(h.calls.cleared.length === 0,
      'drain: the key stays PENDING, so signing the log still gets it filed');
    ok(res.finalizeRefused === 1, 'drain: the refusal is counted, not swallowed');
    const rec = await mod.readFinalizeError(KEY);
    ok(rec && rec.code === 'SUBMIT_MISSING_CP_SIGNATURE',
      'drain: recorded against the DRAFT KEY, so the banner has something to read');
  }

  // A signed submit still goes out — the guard must not cost a correct CP.
  {
    const h = makeEnv({ signature: 'sig', status: 'submitted' });
    const mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    ok(h.calls.created.length === 1, 'drain: a SIGNED submit is still pushed');
    ok(h.calls.cleared.length === 1, 'drain: a successful push clears the key');
  }

  // An unsigned DRAFT is not a submit and must not be blocked.
  {
    const h = makeEnv({ signature: null, status: 'draft' });
    const mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    ok(h.calls.created.length === 1, 'drain: an unsigned DRAFT is still pushed');
  }

  // A server REFUSAL of a create is surfaced and stays pending.
  {
    const h = makeEnv({
      signature: 'sig', status: 'submitted',
      createError: refusal('SUBMIT_EMPTY_LOG'),
    });
    const mod = loadDraftSync(h.env);
    const res = await mod.syncPendingDrafts();
    ok(h.calls.cleared.length === 0, 'drain: a refused create leaves the key PENDING');
    ok(res.finalizeRefused === 1, 'drain: a refused create is counted as a refusal');
    const rec = await mod.readFinalizeError(KEY);
    ok(rec && rec.code === 'SUBMIT_EMPTY_LOG',
      'drain: a refused create is recorded under the draft key — it has no log id');
  }

  // A 5xx or a dead network is NOT a refusal and must not be reported as one.
  {
    const h = makeEnv({
      signature: 'sig', status: 'submitted',
      createError: { message: 'Network Error' },
    });
    const mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    const rec = await mod.readFinalizeError(KEY);
    ok(!rec, 'drain: offline records NOTHING — the server never judged this log');
    ok(h.calls.cleared.length === 0, 'drain: offline still leaves the key pending');
  }
  {
    const h = makeEnv({
      signature: 'sig', status: 'submitted',
      createError: refusal('SUBMIT_EMPTY_LOG', 503),
    });
    const mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    ok(!(await mod.readFinalizeError(KEY)),
      'drain: a 5xx records NOTHING — the server FAILED, it did not judge');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
  console.log('ALL PASSED');
})();
