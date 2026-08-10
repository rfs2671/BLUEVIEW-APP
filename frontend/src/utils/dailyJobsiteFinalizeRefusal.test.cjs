/**
 * A SERVER REFUSAL IS NOT BEING OFFLINE.
 *
 * daily_jobsite's end-of-day Submit & Sign handled every /finalize failure the
 * same way:
 *
 *     } catch (finalizeErr) { console.warn('Finalize deferred...'); }
 *     await markFinalized(_key); setLocked(true);
 *     toast.success('Submitted & Signed', '...will sync when you are back online.');
 *
 * The server's completeness gate REFUSES an empty or unsigned log with a machine
 * code (FINALIZE_EMPTY_LOG / FINALIZE_MISSING_CP_SIGNATURE). Through that catch,
 * a refusal produced three compounding failures at once:
 *
 *   1. the CP was told the log was signed, locked, and would sync. It never
 *      would — the server had said no and would keep saying no.
 *   2. markFinalized makes the local draft IMMUTABLE (logbookDrafts.js
 *      writeDraft), so he could not fix the very condition being refused.
 *   3. the content push had SUCCEEDED, so there was no pending key, so the
 *      reconnect drain never retried it either. The divergence was silent,
 *      permanent, and the device read FINALIZED.
 *
 * What is asserted here, against the REAL shipped source: on a refusal nothing
 * claims success, markFinalized is never reached, the draft is still writable
 * afterwards (proved by running the real writeDraft over it, not by inferring
 * it), the screen is not navigated away from, and the reason is shown in the
 * CP's language through the SAME mechanism LogbookLockBar uses — as a toast AND
 * as a recorded refusal, since the toast is gone in four seconds and an unlocked
 * compliance record has to still say so afterwards. That record is written by
 * draftSync's real recordFinalizeError into a real store, and LogbookLockBar's
 * real mount effect is then run over it to prove the banner actually appears.
 *
 * THERE ARE THREE OUTCOMES, NOT TWO, and only one may promise a sync:
 *
 *   offline (no response at all) — the draft IS queued and the drain WILL
 *     re-apply /finalize, so the freeze and the promise are both true. Unchanged.
 *   4xx — the server judged this log and said no. A refusal.
 *   5xx — the server FAILED. Nothing locked, nothing queued (the content push
 *     succeeded, so there is no pending key to retry), so "signed and locked, it
 *     will sync when you are back online" is the same lie on a rarer path. It is
 *     a retryable failure and says so, reusing the existing generic copy.
 *
 * Offline is decided by the app-wide isOfflineError, not by a second predicate.
 *
 * Run:  node src/utils/dailyJobsiteFinalizeRefusal.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const SRC = path.join(UTILS, '..');
const FRONTEND = path.join(SRC, '..');
const I18N = path.join(SRC, 'i18n');
const screenSrc = fs.readFileSync(path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
const barSrc = fs.readFileSync(path.join(SRC, 'components', 'LogbookLockBar.jsx'), 'utf8');
const draftSyncSrc = fs.readFileSync(path.join(UTILS, 'draftSync.js'), 'utf8');
const draftsSrc = fs.readFileSync(path.join(UTILS, 'logbookDrafts.js'), 'utf8');
const offlineSrc = fs.readFileSync(path.join(UTILS, 'offlineState.js'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── extraction ───────────────────────────────────────────────────────────────
function matchBalanced(text, openIdx, open, close) {
  let depth = 0;
  for (let i = openIdx; i < text.length; i += 1) {
    if (text[i] === open) depth += 1;
    else if (text[i] === close) {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new Error('unbalanced region');
}
function decl(text, anchor) {
  const at = text.indexOf(anchor);
  if (at < 0) throw new Error(`anchor not found: ${anchor}`);
  const open = text.indexOf('{', at);
  return text.slice(at, matchBalanced(text, open, '{', '}') + 1);
}

const submitSrc = decl(screenSrc, 'const handleSubmitAndSign = async () => {');
const gateCopySrc = decl(screenSrc, 'const gateCopy = (code) => {');
const barGateCopySrc = decl(barSrc, 'const gateCopy = (code) =>');
// LogbookLockBar's mount effect — the READER of what the editor now writes.
const barEffectSrc = decl(barSrc, 'useEffect(() => {').replace(/^useEffect\(\(\) =>\s*/, '');

// ── the i18n layer (same technique as src/i18n/i18n.test.cjs) ────────────────
function loadI18n() {
  const strip = (f) => fs.readFileSync(path.join(I18N, f), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  const idx = fs.readFileSync(path.join(I18N, 'index.js'), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export (const|function) /gm, '$1 ')
    .replace(/^export default \{[\s\S]*?\};$/m, '');
  const preamble = `
    const useState = (init) => [typeof init === 'function' ? init() : init, () => {}];
    const useEffect = () => {};
    const useCallback = (fn) => fn;
  `;
  // eslint-disable-next-line no-new-func
  return new Function(`
    ${preamble}
    const en = (() => { ${strip('en.js')} return __default; })();
    const es = (() => { ${strip('es.js')} return __default; })();
    ${idx}
    return { CATALOGUES, LOCALES, translate };
  `)();
}
const I = loadI18n();
const tFor = (locale) => (key) => I.translate('finalize', key, locale);

// The screen's gateCopy, bound to a locale exactly as useT would bind it.
const gateCopyFor = (locale) =>
  // eslint-disable-next-line no-new-func
  new Function('tFinalize', `${gateCopySrc};\nreturn gateCopy;`)(tFor(locale));

// draftSync — the REAL module over an in-memory AsyncStorage, so the refusal the
// editor records and the refusal LogbookLockBar reads are the same bytes in the
// same store rather than two independent beliefs about a key name.
function loadDraftSync() {
  const store = {};
  const body = draftSyncSrc
    .replace(/^import[\s\S]*?;\s*$/gm, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const NetInfo = __env.NetInfo;
    const logbooksAPI = {};
    const getPendingKeys = async () => [];
    const readDraft = async () => null;
    const setDraftBackendId = async () => {};
    const clearPending = async () => {};
    const console = { log: () => {}, warn: () => {} };
    ${body}
    return { finalizeErrorCode, recordFinalizeError, readFinalizeError, clearFinalizeError };
  `)({
    AsyncStorage: {
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
    },
    NetInfo: { addEventListener: () => () => {} },
  });
  return { ...mod, store };
}
// finalizeErrorCode is pure, so one instance serves every caller below.
const { finalizeErrorCode } = loadDraftSync();

// The app-wide OFFLINE predicate — the real one, so "offline" in this test is
// the same thing it is in every other screen.
const { isOfflineError } = (() => {
  const body = offlineSrc.replace(/^export (async function|function|const) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  return new Function(`${body}\nreturn { isOfflineError };`)();
})();

// logbookDrafts — the REAL store, over an in-memory AsyncStorage, so "the draft
// is still editable" is demonstrated rather than asserted from the absence of a
// call.
function loadDrafts() {
  const store = {};
  const body = draftsSrc
    .replace(/^import[\s\S]*?;\s*$/gm, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const Platform = __env.Platform;
    const FileSystem = __env.FileSystem;
    ${body}
    return { draftKey, readDraft, writeDraft, markFinalized, persistActivityPhotos };
  `)({
    AsyncStorage: {
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
    },
    Platform: { OS: 'web' },
    FileSystem: { documentDirectory: null },
  });
  return { ...mod, store };
}

// ── the harness ──────────────────────────────────────────────────────────────
const KEY = 'logbook_draft:proj1:daily_jobsite:2026-08-07';
const rejection = (status, code) => ({
  message: 'Request failed with status code ' + status,
  response: { status, data: { detail: code ? { code } : 'Something went wrong' } },
});
const offline = () => ({ message: 'Network Error' });

async function run({ finalizeError, savedId = 'log123', saveFailed = false, locale = 'en' } = {}) {
  const D = loadDrafts();
  await D.writeDraft(KEY, {
    data: { general_description: 'Shoring.' }, cp_signature: 'sig', cp_name: 'Casey', status: 'submitted',
  });
  // The real recorder/reader/clearer, sharing one store — see loadDraftSync.
  const S = loadDraftSync();

  const calls = {
    toasts: [], finalized: [], cleared: [], recorded: [], locked: [], back: 0, warns: [],
  };
  const env = {
    saving: false,
    signing: false,
    cpSignature: 'sig',
    setSigning: () => {},
    projectId: 'proj1',
    date: '2026-08-07',
    draftKey: D.draftKey,
    markFinalized: async (k) => { calls.finalized.push(k); return D.markFinalized(k); },
    // Spied but NOT stubbed: the real draftSync functions run, against the real
    // store, so what the screen writes is what LogbookLockBar will later read.
    clearFinalizeError: async (id) => { calls.cleared.push(id); return S.clearFinalizeError(id); },
    recordFinalizeError: async (id, code, k) => {
      calls.recorded.push({ id, code, key: k });
      return S.recordFinalizeError(id, code, k);
    },
    finalizeErrorCode,
    isOfflineError,
    setLocked: (v) => { calls.locked.push(v); },
    router: { back: () => { calls.back += 1; } },
    console: { warn: (...a) => calls.warns.push(a.join(' ')) },
    toast: {
      success: (title, body) => calls.toasts.push({ kind: 'success', title, body }),
      error: (title, body) => calls.toasts.push({ kind: 'error', title, body }),
      warning: (title, body) => calls.toasts.push({ kind: 'warning', title, body }),
    },
    // persistAndPush returns `undefined` when the save itself failed (and has
    // already reported it), `null` when it only landed locally.
    // Named handleSave before the U1 stepper split saving from signing; the
    // contract it stands in for is identical.
    persistAndPush: async () => (saveFailed ? undefined : savedId),
    // The stepper's own additions. `_key` moved out of this function and became
    // a memoized value on the component; the observation gate is new, and runs
    // BEFORE any of the finalize logic below, so it has to be satisfiable here.
    _key: KEY,
    observations: [],
    incompleteObservations: () => [],
    setStep: () => {},
    // Real English copy, so the success-toast assertions ("back online",
    // "amendment") test the shipped sentence rather than a stub.
    t: (k) => I.translate('dailyJobsite', k, 'en'),
    logbooksAPI: {
      finalize: async () => { if (finalizeError) throw finalizeError; return { is_locked: true }; },
    },
    tFinalize: tFor(locale),
    gateCopy: gateCopyFor(locale),
  };
  const names = Object.keys(env);
  // eslint-disable-next-line no-new-func
  const fn = new Function(...names, `${submitSrc}\nreturn handleSubmitAndSign;`)(
    ...names.map((n) => env[n]),
  );
  await fn();
  return { calls, D, S };
}

/**
 * Run LogbookLockBar's REAL mount effect over a store, and answer the only
 * question that matters: does the banner appear on this log, and saying what?
 *
 * `undefined` = no refusal on record (no banner). The effect is the component's
 * own source, and readFinalizeError is draftSync's own, so this proves the two
 * sides agree about the key and the record shape — not that they each match a
 * literal copied into this file.
 */
async function bannerFor(S, logId) {
  let refusedCode = 'UNSET';
  // eslint-disable-next-line no-new-func
  await new Function('logId', 'readFinalizeError', 'setRefusedCode',
    `return (async () => ${barEffectSrc})();`)(logId, S.readFinalizeError, (v) => { refusedCode = v; });
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  return { refusedCode, shown: refusedCode !== undefined };
}

const GENERIC = { en: I.translate('finalize', 'genericError', 'en'), es: I.translate('finalize', 'genericError', 'es') };
const CODES = ['FINALIZE_EMPTY_LOG', 'FINALIZE_MISSING_CP_SIGNATURE'];

(async () => {
  // ── 1. A FINALIZE_* REFUSAL ────────────────────────────────────────────────
  for (const code of CODES) {
    const { calls, D, S } = await run({ finalizeError: rejection(400, code) });

    ok(!calls.toasts.some((t) => t.kind === 'success'),
      `${code}: NO success toast — nothing claims the log was signed and locked`);
    ok(!JSON.stringify(calls.toasts).includes('back online'),
      `${code}: the CP is never told it "will sync when you are back online"`);
    ok(calls.finalized.length === 0,
      `${code}: markFinalized is NOT called — the local draft is not frozen`);
    ok(calls.locked.length === 0,
      `${code}: the form is not flipped read-only`);
    ok(calls.back === 0,
      `${code}: the screen is not navigated away from — the CP can fix it here`);

    // THE DRAFT IS ACTUALLY STILL EDITABLE. Proved by writing to it.
    const wrote = await D.writeDraft(KEY, { data: { general_description: 'Shoring and slab prep.' } });
    const after = await D.readDraft(KEY);
    ok(wrote === true && after.data.general_description === 'Shoring and slab prep.',
      `${code}: the draft accepts a content edit afterwards — the CP CAN fix what was refused`);
    ok(after.finalized === false,
      `${code}: and it is not marked finalized`);

    const err = calls.toasts.find((t) => t.kind === 'error');
    ok(!!err, `${code}: an error toast IS shown`);
    ok(err.title === I.translate('finalize', 'errorTitle', 'en'),
      `${code}: titled from the shared finalize namespace`);
    ok(err.body === I.translate('finalize', `code_${code}`, 'en'),
      `${code}: the body is the mapped reason for THIS code, not the generic fallback`);
    ok(err.body !== GENERIC.en, `${code}: ...and it really is its own message`);
    ok(!err.body.includes(code) && !err.body.includes('status code'),
      `${code}: the machine code and the axios message never reach the screen`);
    ok(!JSON.stringify(calls.toasts).includes('Something went wrong'),
      `${code}: the server's raw English detail is never rendered`);

    const es = await run({ finalizeError: rejection(400, code), locale: 'es' });
    const esErr = es.calls.toasts.find((t) => t.kind === 'error');
    // FLIPPED, not dropped. `finalize` is EN-only by ruling — a logbook is a
    // legal record filed with the DOB and these are the CP's lock/refusal
    // prompts. The guard that matters is unchanged: the CP is shown the MAPPED
    // copy for the code, never the server's raw detail. Under es that copy
    // resolves to English via translate()'s fallback, which is the difference
    // between "deliberately English" and "missing".
    ok(esErr.body === I.translate('finalize', `code_${code}`, 'es'),
      `${code}: an es-locale CP gets the mapped reason`);
    ok(esErr.body === err.body, `${code}: which is the English copy — EN-only namespace`);

    // ── AND IT OUTLIVES THE TOAST ──────────────────────────────────────────
    // The toast above is gone in four seconds. If the CP walks off the screen
    // while it fades, the refusal has to still be somewhere.
    ok(calls.recorded.length === 1 && calls.recorded[0].id === 'log123'
      && calls.recorded[0].code === code,
      `${code}: the refusal is RECORDED against this logbook id, not just toasted`);

    const raw = S.store.logbook_finalize_errors;
    ok(typeof raw === 'string', `${code}: written to the shared logbook_finalize_errors key`);
    const rec = JSON.parse(raw).log123;
    ok(rec && rec.code === code && rec.key === KEY && typeof rec.at === 'number',
      `${code}: in the drain's own { code, key, at } shape — the reader is not given a second format`);

    // THE BANNER ACTUALLY APPEARS. LogbookLockBar's real effect, over the real
    // reader, over the bytes the screen just wrote.
    const banner = await bannerFor(S, 'log123');
    ok(banner.shown, `${code}: LogbookLockBar's mount effect finds it — the persistent banner appears`);
    ok(banner.refusedCode === code, `${code}: carrying THIS code, so the banner names the real reason`);
    ok(gateCopyFor('en')(banner.refusedCode) === err.body,
      `${code}: and the banner reads exactly what the toast said`);

    // Nothing was recorded against a DIFFERENT log — the banner cannot leak.
    const other = await bannerFor(S, 'someOtherLog');
    ok(!other.shown, `${code}: no banner on any other log`);
  }

  // ── 2. A 4xx with NO recognised code is still a refusal ────────────────────
  {
    const { calls, S } = await run({ finalizeError: rejection(403, null) });
    ok(calls.finalized.length === 0 && !calls.toasts.some((t) => t.kind === 'success'),
      '403: the server answered and said no — not frozen, not announced as success');
    const err = calls.toasts.find((t) => t.kind === 'error');
    ok(err && err.body === GENERIC.en,
      '403: falls back to the bilingual generic message, never to the server prose');
    const banner = await bannerFor(S, 'log123');
    ok(banner.shown && banner.refusedCode === null,
      '403: recorded with no code — the banner still appears, carrying the generic reason');
  }

  // ── 3. A GENUINE OFFLINE FINALIZE IS UNCHANGED ────────────────────────────
  {
    const { calls, D, S } = await run({ finalizeError: offline() });
    ok(calls.finalized.length === 1,
      'offline: the log IS frozen on this device — an EOD sign with no signal must still hold');
    ok(calls.locked.length === 1 && calls.locked[0] === true,
      'offline: the form goes read-only, as before');
    const s = calls.toasts.find((t) => t.kind === 'success');
    ok(!!s && /back online/.test(s.body),
      'offline: the CP is still told it will sync when he is back online');
    ok(calls.back === 1, 'offline: and he is still returned to the list');
    ok(!calls.toasts.some((t) => t.kind === 'error'), 'offline: no error is shown');

    const after = await D.readDraft(KEY);
    ok(after.finalized === true, 'offline: the draft really is frozen locally');

    ok(calls.recorded.length === 0, 'offline: nothing is recorded — the server never refused anything');
    const banner = await bannerFor(S, 'log123');
    ok(!banner.shown, 'offline: and no "NOT LOCKED ON THE SERVER" banner is raised');
  }

  // ── 4. A 5xx IS NOT BEING OFFLINE EITHER ──────────────────────────────────
  // The server FAILED rather than judged. Nothing is locked and nothing is
  // queued — the content push succeeded, so there is no pending key for the
  // drain to retry — so "signed and locked, it will sync when you are back
  // online" is the same lie as the refusal case on a rarer path.
  for (const status of [500, 502, 503]) {
    const { calls, D, S } = await run({ finalizeError: rejection(status, null) });

    ok(!calls.toasts.some((t) => t.kind === 'success'),
      `${status}: NO success toast — the log is not locked anywhere`);
    ok(!JSON.stringify(calls.toasts).includes('back online'),
      `${status}: the CP is NOT told it will sync when he is back online — nothing is queued`);
    ok(!JSON.stringify(calls.toasts).includes('locked'),
      `${status}: and nothing claims it is locked`);
    ok(calls.finalized.length === 0,
      `${status}: markFinalized is NOT called — the draft must stay retryable`);
    ok(calls.locked.length === 0, `${status}: the form is not flipped read-only`);
    ok(calls.back === 0, `${status}: the CP is left on the screen, where the retry button is`);

    const wrote = await D.writeDraft(KEY, { data: { general_description: 'Shoring, slab prep.' } });
    const after = await D.readDraft(KEY);
    ok(wrote === true && after.finalized === false
      && after.data.general_description === 'Shoring, slab prep.',
      `${status}: the draft is still editable — press Submit & Sign again when the server is well`);

    const err = calls.toasts.find((t) => t.kind === 'error');
    ok(!!err && err.title === I.translate('finalize', 'errorTitle', 'en'),
      `${status}: an error IS shown, from the shared finalize namespace`);
    const body = err ? err.body : '';
    ok(body === GENERIC.en,
      `${status}: reusing the existing generic "could not be finalized, please try again" copy`);
    ok(!/back online|offline/i.test(body),
      `${status}: which does not describe it as an offline condition`);
    ok(!body.includes(String(status)) && !body.includes('status code'),
      `${status}: no HTTP status or axios prose reaches the CP`);

    const es = await run({ finalizeError: rejection(status, null), locale: 'es' });
    const esErr = es.calls.toasts.find((t) => t.kind === 'error');
    ok(esErr && esErr.body === GENERIC.es && esErr.body === GENERIC.en,
      `${status}: and an es-locale CP gets the same English generic (EN-only)`);

    // NOT recorded: the banner's own copy says the log is frozen on this device
    // and queued. On a 5xx it is neither, so raising it would be a third lie.
    ok(calls.recorded.length === 0,
      `${status}: no refusal is recorded — the server named no condition to fix`);
    ok(!(await bannerFor(S, 'log123')).shown,
      `${status}: so no "NOT LOCKED ON THE SERVER" banner, whose copy would not be true here`);
  }

  // ── 4b. THE THREE BRANCHES ARE GENUINELY DISTINCT ─────────────────────────
  {
    const off = (await run({ finalizeError: offline() })).calls;
    const five = (await run({ finalizeError: rejection(500, null) })).calls;
    const four = (await run({ finalizeError: rejection(400, 'FINALIZE_EMPTY_LOG') })).calls;

    ok(off.finalized.length === 1 && five.finalized.length === 0 && four.finalized.length === 0,
      '3-way: ONLY a genuine offline freezes the log locally');
    ok(off.toasts.some((t) => t.kind === 'success')
      && !five.toasts.some((t) => t.kind === 'success')
      && !four.toasts.some((t) => t.kind === 'success'),
      '3-way: ONLY a genuine offline claims success');
    ok(off.recorded.length === 0 && five.recorded.length === 0 && four.recorded.length === 1,
      '3-way: ONLY a refusal — a condition the server named — is recorded for the banner');
    const b5 = (five.toasts.find((t) => t.kind === 'error') || {}).body;
    const b4 = (four.toasts.find((t) => t.kind === 'error') || {}).body;
    ok(!!b5 && !!b4 && b5 !== b4,
      '3-way: a server failure and a refusal do not read the same to the CP');

    // The predicate is the app's, not a second one invented here.
    ok(/import \{ isOfflineError \} from '\.\.\/\.\.\/src\/utils\/offlineState'/.test(screenSrc),
      '3-way: offline is decided by the app-wide isOfflineError, the same predicate settleFetch uses');
    ok(/const offline = isOfflineError\(finalizeErr\);/.test(submitSrc),
      '3-way: ...and it is applied to the finalize error itself');
    ok(!/error\.response|!finalizeErr\?\.response/.test(submitSrc),
      '3-way: handleSubmitAndSign does not re-derive "offline" from the response object');

    // isOfflineError's own contract, so the branch above cannot be read wrong.
    ok(/if \(error\.response\) return false;/.test(offlineSrc),
      '3-way: isOfflineError is false whenever a server answered — a 5xx can never take the offline branch');
  }

  // ── 5. A SUCCESSFUL finalize ──────────────────────────────────────────────
  {
    const { calls, S } = await run({});
    ok(calls.finalized.length === 1 && calls.locked[0] === true && calls.back === 1,
      'success: frozen, locked and dismissed, as before');
    const s = calls.toasts.find((t) => t.kind === 'success');
    ok(!!s && /amendment/.test(s.body),
      'success: the CP is told corrections now require an amendment');
    ok(calls.cleared.includes('log123'),
      'success: a refusal previously recorded by the drain is CLEARED, so the LockBar banner goes');
    ok(calls.recorded.length === 0, 'success: nothing recorded');

    // And the clear really removes what a refusal wrote: record, then finalize.
    await S.recordFinalizeError('log123', 'FINALIZE_EMPTY_LOG', KEY);
    ok((await bannerFor(S, 'log123')).shown, 'success: (a recorded refusal does raise the banner)');
    await S.clearFinalizeError('log123');
    ok(!(await bannerFor(S, 'log123')).shown,
      'success: ...and the clear on a real finalize takes the banner away again');
  }

  // ── 6. An OFFLINE save (no server id at all) still freezes locally ────────
  {
    const { calls } = await run({ savedId: null });
    ok(calls.finalized.length === 1 && calls.back === 1,
      'no server id: never reached the server, so it freezes locally and reports the sync promise');
    ok(calls.cleared.length === 0 && calls.recorded.length === 0,
      'no server id: nothing to clear and nothing to record');
  }

  // ── 7. A save that FAILED still aborts before anything is frozen ──────────
  {
    const { calls } = await run({ saveFailed: true });
    ok(calls.finalized.length === 0 && calls.toasts.length === 0 && calls.back === 0
      && calls.recorded.length === 0,
      'failed save: returns early — handleSave already reported it, and nothing is frozen or recorded');
  }

  // ── 8. THE MECHANISM IS REUSED, NOT REBUILT ──────────────────────────────
  ok(/from '\.\.\/\.\.\/src\/utils\/draftSync'/.test(screenSrc)
    && /finalizeErrorCode/.test(screenSrc) && /clearFinalizeError/.test(screenSrc),
    'reuse: the screen imports draftSync`s finalize-error helpers rather than parsing the error itself');
  ok(!/response\?\.data\?\.detail/.test(submitSrc) && !/\.data\.detail/.test(submitSrc),
    'reuse: handleSubmitAndSign never touches response.data.detail — that stays inside finalizeErrorCode');
  ok(/useT\('finalize'\)/.test(screenSrc),
    'reuse: the copy comes from LogbookLockBar`s own `finalize` namespace, not a second catalogue');

  // ── ONE RECORDER, ONE KEY ────────────────────────────────────────────────
  // The banner only appears if both sides use the same store. They do because
  // there is only one implementation — asserted here so it stays that way.
  ok(/^export async function recordFinalizeError\(/m.test(draftSyncSrc),
    'reuse: recordFinalizeError is EXPORTED from draftSync — the drain is no longer its only writer');
  ok(/import \{[^}]*recordFinalizeError[^}]*\} from '\.\.\/\.\.\/src\/utils\/draftSync'/.test(screenSrc),
    'reuse: the screen imports that same recorder rather than writing storage itself');
  ok(/readFinalizeError/.test(barSrc) && /from '\.\.\/utils\/draftSync'/.test(barSrc),
    'reuse: LogbookLockBar reads through draftSync too — writer and reader share one module');
  ok((draftSyncSrc.match(/'logbook_finalize_errors'/g) || []).length === 1,
    'reuse: the storage key is a single literal in draftSync');
  ok(!/logbook_finalize_errors/.test(screenSrc) && !/logbook_finalize_errors/.test(barSrc),
    'reuse: and neither the screen nor the LockBar restates it — there is nothing to drift');
  ok(!/AsyncStorage/.test(submitSrc),
    'reuse: handleSubmitAndSign never touches AsyncStorage directly');

  // The two gateCopy implementations must follow the SAME rule.
  const norm = (s) => s.replace(/\s+/g, ' ').replace(/^const gateCopy = \(code\) =>\s*\{?/, '').trim();
  ok(norm(gateCopySrc).replace(/tFinalize/g, 't') === norm(barGateCopySrc).replace(/;$/, ''),
    'reuse: the screen`s gateCopy is LogbookLockBar`s rule verbatim (only the translator name differs)');
  for (const loc of I.LOCALES) {
    for (const code of [...CODES, 'FINALIZE_SOMETHING_NEW', null]) {
      // eslint-disable-next-line no-new-func
      const barCopy = new Function('t', `${barGateCopySrc};\nreturn gateCopy;`)(tFor(loc))(code);
      ok(gateCopyFor(loc)(code) === barCopy,
        `reuse: ${code || 'no code'}/${loc} reads identically on the screen and on the LockBar banner`);
    }
  }

  ok(/const refused = typeof status === 'number' && status >= 400 && status < 500;/.test(submitSrc),
    'source: the refusal test is the HTTP status the server answered with');
  const refusalAt = submitSrc.indexOf('if (refused) {');
  const freezeAt = submitSrc.indexOf('await markFinalized(_key);');
  ok(refusalAt > 0 && freezeAt > refusalAt,
    'source: the refusal returns BEFORE markFinalized — the ordering is what makes the draft stay editable');
  ok(!/catch \(finalizeErr\) \{\s*\/\/ Offline \/ server refused\./.test(screenSrc),
    'source: the old "offline / server refused" catch-all is gone');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
