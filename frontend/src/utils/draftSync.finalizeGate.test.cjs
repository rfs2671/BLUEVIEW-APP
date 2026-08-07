/**
 * The FINALIZE COMPLETENESS GATE, client side.
 *
 * The server refuses to finalize an empty or unsigned log and says so with a
 * machine CODE only — detail: {"code": "FINALIZE_EMPTY_LOG"} — because the
 * convention here is that the server names the condition and the client owns
 * the wording (backend/server.py:14638-14645). Two things had to be true for a
 * CP to ever learn that, and neither was:
 *
 *   1. draftSync's reconnect drain swallowed the finalize outright
 *      (`catch (_e) {}`) and then cleared the pending key anyway, so a refusal
 *      was invisible AND unretried — locked on the device, unlocked on the
 *      server, forever.
 *   2. LogbookLockBar rendered the server's raw English `detail` — which for
 *      the gate is now an object, so it would render nothing useful at all, and
 *      for a Spanish-speaking CP renders English regardless.
 *
 * Everything below runs the REAL shipped source: the modules are read,
 * stripped of their imports and evaluated against stubs (the harness
 * src/i18n/i18n.test.cjs uses), and LogbookLockBar's gateCopy is extracted
 * VERBATIM by brace matching (the harness src/utils/checkinCardGate.test.cjs
 * uses). Nothing here is a hand-copy of the logic under test.
 *
 * Run:  node src/utils/draftSync.finalizeGate.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const SRC = path.join(UTILS, '..');
const I18N = path.join(SRC, 'i18n');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The two codes the SERVER actually returns ────────────────────────────────
// Read out of server.py so a renamed code fails here instead of silently
// falling back to the generic message in the app.
const serverSrc = fs.readFileSync(
  path.join(SRC, '..', '..', 'backend', 'server.py'), 'utf8');
const SERVER_CODES = [...new Set(
  [...serverSrc.matchAll(/"code":\s*"(FINALIZE_[A-Z_]+)"/g)].map((m) => m[1]),
)].sort();
ok(SERVER_CODES.length === 2
  && SERVER_CODES.includes('FINALIZE_EMPTY_LOG')
  && SERVER_CODES.includes('FINALIZE_MISSING_CP_SIGNATURE'),
  `server.py returns exactly the 2 gate codes (${SERVER_CODES.join(', ')})`);
ok(/detail=\{"code":\s*"FINALIZE_EMPTY_LOG"\}/.test(serverSrc.replace(/\s+/g, ' ')),
  'server.py returns the code inside detail as an object, not as prose');

// ── Load the i18n layer (same technique as src/i18n/i18n.test.cjs) ───────────
function loadI18n() {
  const strip = (f) => fs.readFileSync(path.join(I18N, f), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  const en = strip('en.js');
  const es = strip('es.js');
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
    const en = (() => { ${en} return __default; })();
    const es = (() => { ${es} return __default; })();
    ${idx}
    return { CATALOGUES, LOCALES, translate, setLocale };
  `)();
}
const I = loadI18n();

// ── LogbookLockBar's gateCopy, extracted VERBATIM ────────────────────────────
const barSrc = fs.readFileSync(path.join(SRC, 'components', 'LogbookLockBar.jsx'), 'utf8');

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
function extractBlock(src, anchor, label) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`${label} not found in LogbookLockBar.jsx`);
  const open = src.indexOf('{', at);
  return src.slice(at, matchBalanced(src, open, '{', '}') + 1);
}
const gateCopySrc = extractBlock(barSrc, 'const gateCopy = (code) =>', 'gateCopy');
const doFinalizeSrc = extractBlock(barSrc, 'const doFinalize = async () =>', 'doFinalize');

// Bind the extracted arrow to a translator for one locale, exactly as useT does.
function gateCopyFor(locale) {
  // eslint-disable-next-line no-new-func
  return new Function('t', `${gateCopySrc};\nreturn gateCopy;`)(
    (key) => I.translate('finalize', key, locale));
}

// ── 1. Both codes map to real, non-empty, DIFFERENT copy in EN and ES ────────
const GENERIC = { en: I.translate('finalize', 'genericError', 'en'), es: I.translate('finalize', 'genericError', 'es') };
for (const code of SERVER_CODES) {
  for (const loc of I.LOCALES) {
    const copy = gateCopyFor(loc)(code);
    ok(typeof copy === 'string' && copy.trim().length > 0,
      `${code}/${loc}: maps to non-empty copy`);
    ok(copy !== GENERIC[loc],
      `${code}/${loc}: maps to its OWN message, not the generic fallback`);
    ok(!copy.includes(code) && copy !== `code_${code}`,
      `${code}/${loc}: renders prose, never the machine code or the catalogue key`);
  }
  ok(gateCopyFor('en')(code) !== gateCopyFor('es')(code),
    `${code}: the Spanish copy is actually translated, not the English string`);
}

// ── 2. An unrecognised code falls back to the bilingual generic ──────────────
// This is the BLOCK_LABELS rule from backend/checkin.html:1508-1518: a code the
// client has never heard of must still produce a sentence in the CP's language.
for (const loc of I.LOCALES) {
  ok(gateCopyFor(loc)('FINALIZE_SOMETHING_NEW') === GENERIC[loc],
    `unknown code/${loc}: falls back to the generic message`);
  ok(gateCopyFor(loc)(null) === GENERIC[loc],
    `no code at all/${loc}: falls back to the generic message`);
  ok(GENERIC[loc].trim().length > 0, `generic/${loc}: is non-empty`);
}
ok(GENERIC.en !== GENERIC.es, 'the generic fallback itself is bilingual');

// ── 3. The server's raw English detail is never surfaced ─────────────────────
ok(!/detail/.test(doFinalizeSrc),
  'doFinalize never touches response.data.detail — it maps the code instead');
ok(/finalizeErrorCode\(e\)/.test(doFinalizeSrc) && /gateCopy\(/.test(doFinalizeSrc),
  'doFinalize routes the error through finalizeErrorCode -> gateCopy');
ok(!/e\?\.message/.test(doFinalizeSrc),
  'doFinalize does not fall back to the English axios message either');
ok(/useT\('finalize'\)/.test(barSrc), 'LogbookLockBar pulls its copy from the i18n layer');
ok(/readFinalizeError/.test(barSrc) && /clearFinalizeError/.test(barSrc),
  'LogbookLockBar reads the recorded drain refusal and clears it on success');
ok((barSrc.match(/\{notLockedBanner\}/g) || []).length === 3,
  'the not-locked banner renders on all 3 of LogbookLockBar`s return paths');

// ── Load draftSync against stubs ─────────────────────────────────────────────
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
    return { parseDraftKey, syncPendingDrafts, finalizeErrorCode,
             readFinalizeError, clearFinalizeError };
  `)(env);
}

const KEY = 'logbook_draft:proj1:hot_work:2026-08-04';
function makeEnv({ finalizeError, hasBackendId = true } = {}) {
  const store = {};              // AsyncStorage
  const calls = { cleared: [], finalized: [], updated: [], created: [], boundIds: [] };
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
      readDraft: async () => ({
        data: { note: 'below-grade pre-work' },
        cp_signature: 'sig',
        cp_name: 'CP',
        status: 'submitted',
        backend_id: hasBackendId ? 'log123' : null,
        finalized: true,
      }),
      setDraftBackendId: async (k, id) => { calls.boundIds.push(id); },
      clearPending: async (k) => { calls.cleared.push(k); },
      logbooksAPI: {
        update: async (id, body) => { calls.updated.push(id); return { id }; },
        create: async (body) => { calls.created.push(body); return { id: 'newlog9' }; },
        finalize: async (id) => {
          calls.finalized.push(id);
          if (finalizeError) throw finalizeError;
          return { id, is_locked: true };
        },
      },
    },
  };
}
const gateRejection = (code) => ({
  message: 'Request failed with status code 400',
  response: { status: 400, data: { detail: { code } } },
});

(async () => {
  // ── 4. finalizeErrorCode: the code, and NOTHING else, escapes the module ───
  const { finalizeErrorCode } = loadDraftSync(makeEnv().env);
  ok(finalizeErrorCode(gateRejection('FINALIZE_EMPTY_LOG')) === 'FINALIZE_EMPTY_LOG',
    'finalizeErrorCode: pulls the machine code out of detail.code');
  ok(finalizeErrorCode(gateRejection('FINALIZE_MISSING_CP_SIGNATURE')) === 'FINALIZE_MISSING_CP_SIGNATURE',
    'finalizeErrorCode: reads both gate codes');
  ok(finalizeErrorCode({ response: { data: { detail: 'Logbook not found' } } }) === null,
    'finalizeErrorCode: a PROSE detail returns null — English server text can never leak to the UI');
  ok(finalizeErrorCode({ response: { data: { detail: { code: 'SOMETHING_ELSE' } } } }) === null,
    'finalizeErrorCode: a non-FINALIZE code is not treated as a gate code');
  ok(finalizeErrorCode({ message: 'Network Error' }) === null,
    'finalizeErrorCode: an offline error carries no code');
  ok(finalizeErrorCode(undefined) === null, 'finalizeErrorCode: tolerates a missing error');

  // ── 5. A refused finalize is NOT swallowed, and the draft stays pending ────
  for (const code of [...SERVER_CODES, null]) {
    const label = code || 'an unrecognised failure';
    const h = makeEnv({ finalizeError: code ? gateRejection(code) : new Error('Network Error') });
    const mod = loadDraftSync(h.env);
    const res = await mod.syncPendingDrafts();

    ok(res.synced === 0 && res.finalizeRefused === 1,
      `${label}: the drain reports the push as NOT synced`);
    ok(h.calls.cleared.length === 0,
      `${label}: clearPending was NOT called — the draft stays PENDING and retries`);
    ok(h.calls.updated.length === 1 && h.calls.finalized.length === 1,
      `${label}: the content still landed; only the freeze failed`);
    ok(h.store[KEY] === undefined,
      `${label}: the draft itself is untouched — nothing is lost`);

    const rec = await mod.readFinalizeError('log123');
    ok(rec !== null && rec.code === code,
      `${label}: the refusal is recorded against the logbook id for the UI to surface`);
    ok(rec.key === KEY, `${label}: the record carries the draft key it came from`);
    ok(JSON.stringify(h.store).indexOf('Request failed') === -1,
      `${label}: no raw English server/axios text is persisted`);
    ok(await mod.readFinalizeError('some-other-log') === null,
      `${label}: the record is scoped to ITS log — no banner on an unrelated one`);
  }

  // ── 6. The create path is guarded the same way ─────────────────────────────
  {
    const h = makeEnv({ finalizeError: gateRejection('FINALIZE_EMPTY_LOG'), hasBackendId: false });
    const mod = loadDraftSync(h.env);
    const res = await mod.syncPendingDrafts();
    ok(h.calls.created.length === 1 && h.calls.cleared.length === 0 && res.finalizeRefused === 1,
      'create path: a refused freeze also leaves the key pending');
    ok(h.calls.boundIds[0] === 'newlog9',
      'create path: the new server id is still bound to the draft (the push did land)');
    const rec = await mod.readFinalizeError('newlog9');
    ok(rec && rec.code === 'FINALIZE_EMPTY_LOG',
      'create path: the refusal is recorded against the NEW server id');
  }

  // ── 7. A finalize that SUCCEEDS clears everything, as before ──────────────
  {
    const h = makeEnv();
    const mod = loadDraftSync(h.env);
    await mod.clearFinalizeError('log123');           // no-op on an empty store
    h.store.logbook_finalize_errors = JSON.stringify({
      log123: { code: 'FINALIZE_EMPTY_LOG', key: KEY, at: 1 },
    });
    const res = await mod.syncPendingDrafts();
    ok(res.synced === 1 && res.finalizeRefused === 0, 'success: the push is reported as synced');
    ok(h.calls.cleared.length === 1 && h.calls.cleared[0] === KEY,
      'success: the pending key is cleared exactly as before');
    ok(await mod.readFinalizeError('log123') === null,
      'success: a stale refusal record is cleared, so the banner goes away');
  }

  // ── 8. The swallow is gone from the source itself ─────────────────────────
  ok(!/finalize\(id\);\s*\}\s*catch\s*\(_e\)\s*\{/.test(draftSyncSrc),
    'draftSync: the `catch (_e) {}` around finalize is gone');
  ok(/recordFinalizeError\(/.test(draftSyncSrc) && /'finalize-refused'/.test(draftSyncSrc),
    'draftSync: a refusal is recorded and named');
  const pushOneSrc = draftSyncSrc.slice(draftSyncSrc.indexOf('async function pushOne'));
  const guardAt = pushOneSrc.search(/if \(!frozen\.ok\) \{/);
  const clearAt = pushOneSrc.search(/await clearPending\(key\);\s*return \{ key, ok: true, mode: 'update'/);
  ok(guardAt > 0 && clearAt > guardAt,
    'draftSync: the refusal returns BEFORE clearPending on the update path');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
