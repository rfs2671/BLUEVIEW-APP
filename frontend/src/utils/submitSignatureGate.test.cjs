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

// ── 1. every immediate form blocks an UNAFFIRMED submit ──────────────────────
//
// STRENGTHENED by device round 4. This used to test `!cpSignature` — is
// anything there — and production held `cp_signature: {}`, an empty object,
// which is truthy and passed. Three logs were filed that way and every
// rendered section said "UNAFFIRMED — inherited signature". The predicate is
// now the renderer's own: affirmed FOR THIS DOCUMENT. Full coverage of the
// rule itself is in signatureAffirmed.test.cjs; this keeps the structural
// assertion in the file that has always owned it.
for (const t of IMMEDIATE) {
  const f = path.join(APP_LOGBOOKS, `${t}.jsx`);
  if (!fs.existsSync(f)) { ok(false, `${t}.jsx exists`); continue; }
  const src = fs.readFileSync(f, 'utf8');
  // subcontractor_orientation derives status FROM the signature rather than
  // disabling a button — structurally unreachable, which is stronger.
  const derives = /const status = isAffirmedSignature\(newCpSignature\) \? 'submitted' : 'draft'/.test(src);
  const disables = /disabled=\{!isAffirmedSignature\(cpSignature\)/.test(src);
  // A form ported onto the shared stepper does not own its footer button, so it
  // cannot write `disabled=` itself — it passes the same condition through
  // LogbookStepper's `submitDisabled`, which the chrome applies to the one
  // submit Pressable. THE GUARANTEE IS IDENTICAL and is asserted end to end
  // below: this only recognises where the expression now lives.
  const stepperGated = /submitDisabled=\{!isAffirmedSignature\(cpSignature\)/.test(src);
  ok(derives || disables || stepperGated,
    `${t}: an UNAFFIRMED submit is unreachable (${derives ? 'status derived' : (disables ? 'button disabled' : 'stepper submitDisabled')})`);
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
// THE NEXT BRANCH ONLY. The slice used to start at the top of the footer,
// which now also holds the submit hint — and that hint names submitDisabled,
// so a correct footer failed an assertion about the Next button. Anchored to
// the ternary itself, it tests what it always meant to test.
const nextBranch = footerSrc.slice(
  footerSrc.indexOf('{step < total ? ('), footerSrc.indexOf(') : ('));
ok(!/submitDisabled/.test(nextBranch),
  'stepper: an unaffirmed CP can still page through the form — only Submit is gated');
// And the hint itself must not appear beside Next: a man on step 2 being told
// to sign is being told to fix something he has not reached.
ok(/\{step === total && submitDisabled && !!submitHint && \(/.test(footerSrc),
  'stepper: the hint is scoped to the submit step');

// ── 2. the guard is not a dead end ───────────────────────────────────────────
for (const t of NEWLY_GUARDED) {
  const src = fs.readFileSync(path.join(APP_LOGBOOKS, `${t}.jsx`), 'utf8');
  // The three-way choice moved into affirmationHintKey — one place, executed by
  // signatureAffirmed.test.cjs, rather than the same ternary spelled out in
  // nine screens where eight could stay right while one drifted.
  ok(/\{!!affirmationHintKey\(cpSignature, profileLoaded\) && \(/.test(src),
    `${t}: tells the CP WHY submit is unavailable`);
  ok(/tFinalize\(affirmationHintKey\(cpSignature, profileLoaded\)\)/.test(src),
    `${t}: and the sentence is chosen by the shared helper, so "sign" and "affirm" cannot be confused`);
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
  'submitNeedsSignature', 'submitSignatureLoading', 'submitNeedsAffirmation',
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
// Four now. SUBMIT_MISSING_TRADE joined first: a safety orientation may be
// CREATED without a trade (the gate check-in writes one that way, and a worker
// at the turnstile is never blocked for an admin's unfinished roster) but may
// not be SUBMITTED without one.
//
// SUBMIT_NO_CONTENT is the fourth, and it is NOT a completeness rule — those
// belong to the editors, as finalize_logbook's docstring rules. It fires only
// for the two records that ARE a list of rows (osha_log, preshift_signin) when
// every row is one the PDF renderer would already refuse to print, i.e. the
// document would come out blank. Same machine-code convention, no new
// mechanism.
ok(SUBMIT_CODES.length === 4
  && SUBMIT_CODES.includes('SUBMIT_EMPTY_LOG')
  && SUBMIT_CODES.includes('SUBMIT_MISSING_CP_SIGNATURE')
  && SUBMIT_CODES.includes('SUBMIT_MISSING_TRADE')
  && SUBMIT_CODES.includes('SUBMIT_NO_CONTENT'),
  `server.py returns exactly the 4 submit codes (${SUBMIT_CODES.join(', ')})`);
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
// 6000, not 4000: SUBMIT_NO_CONTENT added a gate between the signature check
// and the write, pushing `update = {"updated_at"` past the old window. A
// too-short slice makes indexOf return -1 and the comparison below passes or
// fails for the wrong reason, so the window is asserted to contain both
// landmarks before they are compared.
const updateFn = serverSrc.slice(
  serverSrc.indexOf('async def update_logbook'),
  serverSrc.indexOf('async def update_logbook') + 6000,
);
ok(updateFn.includes('SUBMIT_MISSING_CP_SIGNATURE') && updateFn.includes('update = {"updated_at"'),
  'the update_logbook window holds both the gate and the write it must precede');
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
// AFFIRMED. The drain asks the renderer's question now, so `'sig'` — a bare
// string, and `{}` — would both be refused before the transport under test is
// ever reached. Anywhere a VALID signature is meant, it is this.
const AFFIRMED = { affirmed: true, signerName: 'CP', timestamp: '2026-08-09T12:00:00Z' };
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
    const h = makeEnv({ signature: AFFIRMED, status: 'submitted' });
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
      signature: AFFIRMED, status: 'submitted',
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
      signature: AFFIRMED, status: 'submitted',
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
      signature: AFFIRMED, status: 'submitted',
      createError: refusal('SUBMIT_EMPTY_LOG', 503),
    });
    const mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    ok(!(await mod.readFinalizeError(KEY)),
      'drain: a 5xx records NOTHING — the server FAILED, it did not judge');
  }

  // ── THE DRAIN REFUSES INCOMPLETE CONTENT TOO (option B) ─────────────────
  //
  // #127's client gate cannot reach the drain: a pre-shift draft written on an
  // older build replays with injury/PPE null and the server accepts it. These
  // run the REAL syncPendingDrafts against a draft carrying that shape.
  {
    const KEY_PS = 'logbook_draft:proj1:preshift_signin:2026-08-13';
    const mkPs = (workers, logType = 'preshift_signin') => {
      const store = {};
      const calls = { created: [], cleared: [] };
      const k = 'logbook_draft:proj1:' + logType + ':2026-08-13';
      return { calls, env: {
        console: { log: () => {}, warn: () => {} },
        NetInfo: { addEventListener: () => () => {} },
        AsyncStorage: {
          getItem: async (kk) => (kk in store ? store[kk] : null),
          setItem: async (kk, v) => { store[kk] = v; },
        },
        getPendingKeys: async () => [k],
        readDraft: async () => ({
          data: { company: 'AAZ', workers },
          cp_signature: AFFIRMED, cp_name: 'CP', status: 'submitted',
          backend_id: null, finalized: false,
        }),
        setDraftBackendId: async () => {},
        clearPending: async (kk) => { calls.cleared.push(kk); },
        logbooksAPI: {
          update: async (id) => ({ id }),
          create: async (b) => { calls.created.push(b); return { id: 'ps1' }; },
          finalize: async (id) => ({ id }),
        },
      } };
    };

    let h = mkPs([{ name: 'Wilmer Carrillo', had_injury: null, inspected_ppe: null }]);
    let mod = loadDraftSync(h.env);
    await mod.syncPendingDrafts();
    ok(h.calls.created.length === 0,
      'drain: a signed pre-shift draft with null injury/PPE is NOT pushed');
    ok(h.calls.cleared.length === 0,
      'drain: the key stays PENDING, so answering it still gets the log filed');
    const recPs = await mod.readFinalizeError(KEY_PS);
    ok(recPs && recPs.code === 'SUBMIT_INCOMPLETE_WORKER_ANSWERS',
      'drain: recorded, so the durable banner has something to read');

    h = mkPs([{ name: 'Wilmer Carrillo', had_injury: 'no', inspected_ppe: 'yes' }]);
    await loadDraftSync(h.env).syncPendingDrafts();
    ok(h.calls.created.length === 1, 'drain: an ANSWERED pre-shift draft is still pushed');

    h = mkPs([{ name: '', had_injury: null, inspected_ppe: null },
      { name: 'Wilmer Carrillo', had_injury: 'no', inspected_ppe: 'no' }]);
    await loadDraftSync(h.env).syncPendingDrafts();
    ok(h.calls.created.length === 1, 'drain: a nameless spare row never blocks the push');

    h = mkPs([{ name: 'X', had_injury: null, inspected_ppe: null }], 'toolbox_talk');
    await loadDraftSync(h.env).syncPendingDrafts();
    ok(h.calls.created.length === 1,
      'drain: the gate is scoped to preshift_signin and touches no other type');
  }

  // ── 8. THE CLIENT GATE AND THE DRAIN AGREE ABOUT `undefined` ────────────
  //
  // Device round 4, finding 1. The filed record turned out NOT to be a defect —
  // it was submitted twelve minutes before the gate reached that device — but
  // the investigation found a real hole: the screen tested `w.had_injury !==
  // null`, and `undefined !== null` is TRUE. A row that never carried the key
  // at all walked through as answered.
  //
  // That row is reachable. `reconcileRoster` returns kept rows VERBATIM by
  // ruling (nothing is re-hydrated), so a stored row missing the key keeps
  // missing it for as long as the log exists. The drain has always checked both
  // (`=== null || === undefined`), so the two gates disagreed about the same
  // draft: the CP could not submit it, and the drain would not send it, but a
  // row that reached the screen already missing the key passed the screen.
  //
  // EXECUTED, not grepped — the predicate is lifted out of the shipped screen
  // and run, so a rewording of the source cannot pass this by accident.
  {
    const ps = fs.readFileSync(path.join(APP_LOGBOOKS, 'preshift_signin.jsx'), 'utf8');
    const m = /const answeredBoth = (\(w\) => [^;]+);/.exec(ps);
    ok(!!m, 'preshift_signin: answeredBoth is still a single extractable expression');
    // eslint-disable-next-line no-new-func
    const answeredBoth = m ? new Function(`return ${m[1]};`)() : () => false;
    ok(answeredBoth({ had_injury: 'no', inspected_ppe: 'yes' }) === true,
      'an answered row is answered');
    ok(answeredBoth({ had_injury: null, inspected_ppe: null }) === false,
      'a null row is not');
    ok(answeredBoth({}) === false,
      'AND NEITHER IS A ROW MISSING THE KEYS — the hole this closes');
    ok(answeredBoth({ had_injury: 'no' }) === false, 'one answer is not both');
    ok(answeredBoth({ had_injury: 'no', inspected_ppe: 'no' }) === true,
      'and "no" to both is still a complete answer, not an absent one');

    // The red outline and "Required field" marker must use the SAME test, or
    // the CP is shown a clean row he cannot submit.
    ok((ps.match(/worker\.had_injury == null/g) || []).length === 2,
      'preshift_signin: the injury marker uses the same loose test in both places');
    ok((ps.match(/worker\.inspected_ppe == null/g) || []).length === 2,
      'preshift_signin: and so does the PPE marker');
    ok(!/worker\.(had_injury|inspected_ppe) === null/.test(ps),
      'preshift_signin: no strict-null test survives to disagree with the gate');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
  console.log('ALL PASSED');
})();
