/**
 * THE DRAIN STOPS RETRYING A CREATE THE SERVER CAN ONLY EVER REFUSE — and the
 * two halves of the machine-code convention are asserted against each other.
 *
 * Two things, because the second is why the first could not have worked:
 *
 * 1. A create refused with FILED_LOG_DATA_IMMUTABLE will never land, however
 *    the draft changes: the server is not judging the payload, it is stating
 *    that a filed record already exists for this (project, type, date). Left
 *    pending it was re-sent on every reconnect for the life of the install,
 *    under a durable banner. It is also the path a log that filed CORRECTLY
 *    takes when the response was lost — so the banner sat on a good filing,
 *    and a banner that cannot come down is how a CP learns to read past all of
 *    them.
 *
 * 2. finalizeErrorCode's GATE_CODE regex matched FINALIZE_ and SUBMIT_ only.
 *    #214's code carries neither prefix — deliberately, its server comment
 *    explains why — so the code came out null, every caller fell back to
 *    "could not be finalized, please try again", and the copy written for it
 *    was unreachable. The server named a condition the client could not hear.
 *
 * The last block asserts every logbook gate code server.py emits is one this
 * extractor recognises, which is the check that was missing when #214 landed.
 *
 * Runs the REAL shipped module through esmHarness, the same way
 * draftSync.finalizeGate.test.cjs does.
 *
 * Run:  node src/utils/drainAlreadyFiled.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const UTILS = __dirname;
const SRC = path.join(UTILS, '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const KEY = 'logbook_draft:proj1:daily_jobsite:2026-08-28';

function makeEnv({ backendId = null, rejection } = {}) {
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
      readDraft: async () => ({
        data: { activities: [{ company: 'Arkon Builders' }] },
        cp_signature: { affirmed: true },
        cp_name: 'CP',
        status: 'submitted',
        backend_id: backendId,
        finalized: false,
      }),
      setDraftBackendId: async () => {},
      clearPending: async (k) => { calls.cleared.push(k); },
      logbooksAPI: {
        create: async (body) => {
          calls.created.push(body);
          if (rejection) throw rejection;
          return { id: 'newlog9' };
        },
        update: async (id, body) => {
          calls.updated.push(id);
          if (rejection) throw rejection;
          return { id };
        },
        finalize: async (id) => ({ id, is_locked: true }),
      },
    },
  };
}

function loadDraftSync(env) {
  return loadEsm('src/utils/draftSync.js', {
    globals: { console: env.console },
    stubs: {
      '@react-native-async-storage/async-storage': env.AsyncStorage,
      '@react-native-community/netinfo': env.NetInfo,
      './api': { logbooksAPI: env.logbooksAPI },
      './logbookDrafts': {
        // draftSync -> logbookTiming (isVisitLog) -> markFinalized.
        markFinalized: async () => {},
        getPendingKeys: env.getPendingKeys,
        readDraft: env.readDraft,
        setDraftBackendId: env.setDraftBackendId,
        clearPending: env.clearPending,
        writeDraft: async () => true,
        uploadPendingActivityPhotos: async (_p, acts) => ({
          uploaded: 0, remaining: 0, activities: acts,
        }),
      },
    },
  });
}

const refusal = (status, code) => ({
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail: code ? { code } : 'prose' } },
});

const FILED = refusal(409, 'FILED_LOG_DATA_IMMUTABLE');

(async () => {
  console.log('\n-- the code is EXTRACTABLE, which it was not --');
  {
    const { finalizeErrorCode } = loadDraftSync(makeEnv().env);
    ok(finalizeErrorCode(FILED) === 'FILED_LOG_DATA_IMMUTABLE',
      'FILED_LOG_DATA_IMMUTABLE survives finalizeErrorCode — it did not, so the '
      + 'copy written for it could never render and the CP was told to retry');
    ok(finalizeErrorCode(refusal(400, 'SUBMIT_EMPTY_LOG')) === 'SUBMIT_EMPTY_LOG',
      'and the prefixes that already worked still do');
    ok(finalizeErrorCode(refusal(409, null)) === null,
      'a PROSE detail is still null — the server English never reaches the UI');
    ok(finalizeErrorCode(refusal(400, 'SOMETHING_ELSE')) === null,
      'and an unknown prefix is still not treated as a gate code');
  }

  console.log('\n-- a create the server can only refuse stops being retried --');
  {
    const { calls, env } = makeEnv({ backendId: null, rejection: FILED });
    const { syncPendingDrafts } = loadDraftSync(env);
    const out = await syncPendingDrafts();
    ok(calls.created.length === 1, 'it was attempted once');
    ok(calls.cleared.includes(KEY),
      'and the key is CLEARED — it can never land, so re-sending it on every '
      + 'reconnect is work that cannot succeed');
    ok(out.synced === 0, 'it is not counted as synced — nothing reached the server');
    ok(out.finalizeRefused === 1, 'it IS counted as refused, not silently dropped');
  }

  console.log('\n-- the refusal is recorded, once --');
  {
    const { calls, store, env } = makeEnv({ backendId: null, rejection: FILED });
    const { syncPendingDrafts } = loadDraftSync(env);
    await syncPendingDrafts();
    const recorded = Object.values(JSON.parse(store['logbook_finalize_errors'] || '{}'));
    ok(recorded.length === 1 && recorded[0].code === 'FILED_LOG_DATA_IMMUTABLE',
      'the refusal is on record against the draft key, with the real code — a '
      + 'discard that said nothing would be the silent shape this file exists '
      + `to prevent (got ${JSON.stringify(recorded)})`);
    ok(calls.cleared.length === 1, 'and recorded ONCE: the key is gone, so no '
      + 'later drain re-asserts it');
  }

  console.log('\n-- every OTHER refusal still stays pending --');
  {
    for (const code of ['SUBMIT_EMPTY_LOG', 'SUBMIT_MISSING_CP_SIGNATURE', 'SUBMIT_NO_CONTENT']) {
      const { calls, env } = makeEnv({ backendId: null, rejection: refusal(400, code) });
      const { syncPendingDrafts } = loadDraftSync(env);
      await syncPendingDrafts();
      ok(!calls.cleared.includes(KEY),
        `${code} stays pending — the CP can FIX it in the draft, and the next `
        + 'drain sends the corrected version');
    }
  }

  console.log('\n-- and an UPDATE refused the same way still stays pending --');
  {
    const { calls, env } = makeEnv({ backendId: 'log123', rejection: FILED });
    const { syncPendingDrafts } = loadDraftSync(env);
    await syncPendingDrafts();
    ok(calls.updated.length === 1, 'the update was attempted');
    ok(!calls.cleared.includes(KEY),
      'and the key is kept: on an update the draft HOLDS a backend_id, so the '
      + "banner's Amend button has the log id it needs and the refusal is "
      + 'actionable. A refused create has no id to amend, which is the whole '
      + 'difference');
  }

  // ── the two halves of the convention, against each other ──────────────────
  console.log('\n-- every logbook gate code the server emits is extractable --');
  {
    const serverSrc = fs.readFileSync(
      path.join(SRC, '..', '..', 'backend', 'server.py'), 'utf8');
    // The logbook write/finalize gates. NOT every code in server.py: the
    // ACTIVATION_* and LOGBOOK_NOT_ACTIVATABLE codes belong to endpoints that
    // do not route through this extractor, and widening it to them would change
    // behaviour on screens this file knows nothing about.
    const LOGBOOK_GATE_CODES = [
      'FINALIZE_EMPTY_LOG',
      'FINALIZE_MISSING_CP_SIGNATURE',
      'SUBMIT_EMPTY_LOG',
      'SUBMIT_MISSING_CP_SIGNATURE',
      'SUBMIT_MISSING_TRADE',
      'SUBMIT_NO_CONTENT',
      'FILED_LOG_DATA_IMMUTABLE',
    ];
    const { finalizeErrorCode } = loadDraftSync(makeEnv().env);
    for (const code of LOGBOOK_GATE_CODES) {
      ok(new RegExp(`"code":\\s*"${code}"`).test(serverSrc),
        `server.py still emits ${code}`);
      ok(finalizeErrorCode(refusal(409, code)) === code,
        `and the client can hear it — ${code}`);
    }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
  console.log('ALL PASSED');
})();
