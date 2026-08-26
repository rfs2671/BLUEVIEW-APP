/**
 * THE HARNESS ITSELF, TESTED.
 *
 * esmHarness exists so a test can execute shipped ESM under plain node without
 * deleting its imports. It replaces a regex import-strip that cost three
 * things, and the two that matter are asserted here:
 *
 *   A RELATIVE IMPORT LOADS FOR REAL. `./signatureAffirmed` imports nothing and
 *   always could have loaded, but a line-based strip deleted it with NetInfo.
 *   That is the entire reason draftSync carried a hand-copy of
 *   isAffirmedSignature, kept in step by a string-equality assertion -- the
 *   same shape as stripAffirmation, which named three literals inline and
 *   silently missed a fourth when the attestation grew one.
 *
 *   A MISSING KEY IS LOUD. draftSync imports writeDraft and
 *   uploadPendingActivityPhotos; two harnesses declared neither and passed
 *   because no exercised path reached them. Under the old strip that was a
 *   latent ReferenceError from inside generated source; a half-filled stub was
 *   worse still, since a named import compiles to a property read and an absent
 *   key is just `undefined`.
 *
 *   node frontend/src/utils/esmHarness.test.cjs
 */
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}
function throws(fn, match, label) {
  try {
    fn();
    ok(false, `${label} (did not throw)`);
  } catch (e) {
    ok(match.test(e.message), `${label}${match.test(e.message) ? '' : ` (wrong message: ${e.message})`}`);
  }
}

const RN_STUBS = {
  '@react-native-async-storage/async-storage': { getItem: async () => null, setItem: async () => {} },
  '@react-native-community/netinfo': { addEventListener: () => () => {} },
  './api': { logbooksAPI: {} },
  './logbookDrafts': {
    getPendingKeys: async () => [],
    readDraft: async () => null,
    setDraftBackendId: async () => {},
    clearPending: async () => {},
    writeDraft: async () => {},
    uploadPendingActivityPhotos: async () => {},
  },
};

let liveImportCheck = async () => {};

console.log('\n-- a module with no imports loads on its own --');
{
  const m = loadEsm('src/utils/signatureAffirmed.js');
  ok(typeof m.isAffirmedSignature === 'function', 'named exports come through');
  ok(typeof m.hasSignatureInk === 'function', 'all of them');
  ok(m.isAffirmedSignature({ affirmed: true }) === true, 'and they are the real functions');
}

console.log('\n-- a relative import resolves FOR REAL --');
{
  // PROVED THROUGH BEHAVIOUR, because draftSync does not re-export the
  // predicate. The drain refuses to push an unaffirmed submit. Run the same
  // draft twice: once with `./signatureAffirmed` loaded for real, once with it
  // stubbed to say yes to everything. If the import were dead, both runs would
  // agree — and a copy of the predicate compiled into draftSync would ignore
  // the stub entirely, which is exactly the state this replaced.
  const KEY = 'logbook_draft:proj1:hot_work:2026-08-26';
  const UNAFFIRMED = { paths: [[{ x: 1, y: 1 }]], signerName: 'CP' };

  function run(extraStubs) {
    const created = [];
    const mod = loadEsm('src/utils/draftSync.js', {
      globals: { console: { log: () => {}, warn: () => {} } },
      stubs: {
        ...RN_STUBS,
        './api': {
          logbooksAPI: {
            create: async (b) => { created.push(b); return { id: 'new1' }; },
            update: async (id) => ({ id }),
            finalize: async (id) => ({ id }),
          },
        },
        './logbookDrafts': {
          ...RN_STUBS['./logbookDrafts'],
          getPendingKeys: async () => [KEY],
          readDraft: async () => ({
            data: { note: 'x' }, cp_signature: UNAFFIRMED, cp_name: 'CP',
            status: 'submitted', backend_id: null, finalized: false,
          }),
        },
        ...extraStubs,
      },
    });
    return { mod, created };
  }

  // The awaits run in the single async tail at the bottom, so this file has one
  // exit point. Inlining an async IIFE here printed the summary twice: the
  // synchronous sections below it ran during its first await.
  liveImportCheck = async () => {
    const real = run({});
    await real.mod.syncPendingDrafts();
    ok(real.created.length === 0,
      'with the REAL predicate the drain refuses an unaffirmed submit');

    const faked = run({ './signatureAffirmed': { isAffirmedSignature: () => true } });
    await faked.mod.syncPendingDrafts();
    ok(faked.created.length === 1,
      'and stubbing ./signatureAffirmed CHANGES that — so the import is live, '
      + 'not a copy compiled into draftSync and not a dropped line');
  };
}

console.log('\n-- an unstubbed BARE import throws, and names itself --');
{
  throws(
    () => loadEsm('src/utils/draftSync.js', { stubs: {} }),
    /no stub for '@react-native-async-storage\/async-storage'/,
    'the specifier is named, not silently deleted');
  throws(
    () => loadEsm('src/utils/draftSync.js', { stubs: {} }),
    /draftSync\.js/,
    'and so is the file that imported it');
}

console.log('\n-- an unstubbed RELATIVE import is loaded, and fails on ITS deps --');
{
  // ./logbookDrafts left unstubbed: the harness loads it for real, and it
  // imports react-native and expo-file-system, which have no stubs. The error
  // must name THOSE, not the relative module -- that is what tells you which
  // stub to add.
  const stubs = { ...RN_STUBS };
  delete stubs['./logbookDrafts'];
  throws(
    () => loadEsm('src/utils/draftSync.js', { stubs }),
    /no stub for '(react-native|expo-file-system\/legacy|axios)'/,
    'the transitive dependency is what gets named');
}

console.log('\n-- a stub refuses a key it does not define --');
{
  const stubs = {
    ...RN_STUBS,
    './logbookDrafts': { getPendingKeys: async () => [] },   // the rest omitted
  };
  throws(
    () => loadEsm('src/utils/draftSync.js', {
      globals: { console: { log: () => {}, warn: () => {} } },
      stubs,
    }),
    /has no 'readDraft'|has no 'setDraftBackendId'|has no 'clearPending'|has no 'writeDraft'|has no 'uploadPendingActivityPhotos'/,
    'THE HOLE THIS CLOSES: a half-filled stub used to yield undefined and fail '
    + 'somewhere else, or not at all');
  throws(
    () => loadEsm('src/utils/draftSync.js', {
      globals: { console: { log: () => {}, warn: () => {} } },
      stubs,
    }),
    /draftSync\.js imports it/,
    'and the message names the importer, so the fix is obvious');
}

console.log('\n-- interop: default and named from one stub --');
{
  // `import AsyncStorage from '...'` compiles to _interopRequireDefault, which
  // reads __esModule on the stub. A proxy that threw on unknown keys would
  // break every default import if it did not allow the interop protocol
  // through -- so this is not a detail, it is load-bearing.
  const m = loadEsm('src/utils/draftSync.js', {
    globals: { console: { log: () => {}, warn: () => {} } },
    stubs: RN_STUBS,
  });
  ok(typeof m.syncPendingDrafts === 'function',
    'a plain object serves as a default export without declaring __esModule');
}

console.log('\n-- globals are shadowed, not mutated --');
{
  const lines = [];
  loadEsm('src/utils/draftSync.js', {
    globals: { console: { log: (...a) => lines.push(a), warn: () => {} } },
    stubs: RN_STUBS,
  });
  ok(typeof console.log === 'function' && console.log !== lines.push,
    'the real console is untouched — the injected one is a parameter, so it '
    + 'shadows inside the module only');
}

console.log('\n-- it is not collected as a test --');
{
  // tests.yml globs `*.test.cjs` / `*.test.js` under src and app. The loader
  // must not match, or the runner executes a module with no assertions and
  // counts it as a passing file.
  ok(!/\.test\.cjs$/.test('esmHarness.cjs'), 'esmHarness.cjs is not a test filename');
  ok(path.basename(require.resolve('./esmHarness.cjs')) === 'esmHarness.cjs',
    'and it is required by path, so it is unambiguous');
}

(async () => {
  console.log('\n-- the relative import is live, proved through behaviour --');
  await liveImportCheck();

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
