/**
 * THE PER-SCREEN PUSHER — a log type the generic drain cannot rebuild now
 * genuinely syncs on reconnect, and the CP logbook path is untouched.
 *
 * THE DEFECT THIS CLOSES. draftSync's drain refuses 'daily_log' and
 * 'site_daily_log' (SKIP_LOG_TYPES) because they post a flatter shape to
 * dailyLogsAPI than it can reconstruct from a draft. Correct — and nothing ever
 * told the screens, which queued the key and showed a superintendent at a gate
 * tablet a GREEN SUCCESS TOAST saying the log "will sync when you are back
 * online". It never would. The key sat in the pending index for the life of the
 * install and only a human reopening that date and pressing Save could file it.
 *
 * THE SHAPE OF THE FIX, and what has to be proved about it:
 *
 *   NOTHING IS GUESSED. The screen records the EXACT request body it would have
 *   sent (`push_body`) and the drain replays that object. No mapping step, so
 *   no field to invent or drop. A draft with no recorded body is REFUSED, not
 *   reconstructed from `data` — the one thing the skip existed to prevent.
 *
 *   THE CP PATH IS LOAD-BEARING AND MUST NOT MOVE. The pending index is SHARED
 *   with the CP logbook drafts. So the registered path is a sibling of pushOne
 *   rather than a route through it, and this file drains a MIXED index to prove
 *   a daily log and a logbook in the same pass each go to their own API and
 *   each clear only their own key.
 *
 *   NO SECOND TRIGGER. The existing NetInfo transition is reused; registration
 *   adds a payload shape, not a listener.
 *
 * Everything below runs the REAL shipped modules through esmHarness, the same
 * way drainAlreadyFiled.test.cjs and draftSync.finalizeGate.test.cjs do.
 *
 * Run:  node src/utils/draftSyncPusherRegistry.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const SITE_KEY = 'logbook_draft:proj1:site_daily_log:2026-09-01';
const CP_KEY = 'logbook_draft:proj1:daily_jobsite:2026-09-01';

// The body a screen records at submit: the flat daily-log shape, with the audit
// stamps taken at the moment of the user's action. This is what must arrive at
// dailyLogsAPI byte for byte.
const RECORDED_BODY = Object.freeze({
  project_id: 'proj1',
  date: '2026-09-01',
  weather: 'rainy',
  notes: 'Below-grade pour, east bay.',
  worker_count: 14,
  safety_checklist: { fall_protection: { status: 'pass' } },
  corrective_actions: 'Toe board replaced at bay 3.',
  corrective_actions_na: false,
  corrective_actions_audit: { entered_by: 'R. Silva', entered_at: '2026-09-01T18:22:00.000Z' },
  incident_log: '',
  incident_log_na: true,
  superintendent_signature: { signer_name: 'R. Silva', affirmed: true },
  competent_person_signature: { signer_name: 'M. Diaz', affirmed: true },
});

/**
 * An in-memory pending index and draft store, so a drain's EFFECTS on the queue
 * are observable rather than asserted from source.
 */
function makeEnv({ keys, drafts, logbooksRejection } = {}) {
  const pending = [...keys];
  const calls = { logbooksCreated: [], logbooksUpdated: [], boundIds: [] };
  return {
    calls,
    pending,
    env: {
      console: { log: () => {}, warn: () => {} },
      NetInfo: { addEventListener: () => () => {} },
      AsyncStorage: {
        getItem: async () => null,
        setItem: async () => {},
      },
      getPendingKeys: async () => [...pending],
      readDraft: async (k) => (drafts[k] ? { ...drafts[k] } : null),
      setDraftBackendId: async (k, id) => {
        calls.boundIds.push([k, id]);
        if (drafts[k]) drafts[k].backend_id = id;
      },
      clearPending: async (k) => {
        const i = pending.indexOf(k);
        if (i !== -1) pending.splice(i, 1);
      },
      logbooksAPI: {
        create: async (body) => {
          calls.logbooksCreated.push(body);
          if (logbooksRejection) throw logbooksRejection;
          return { id: 'cplog7' };
        },
        update: async (id, body) => {
          calls.logbooksUpdated.push([id, body]);
          if (logbooksRejection) throw logbooksRejection;
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

const siteDraft = (over = {}) => ({
  data: { weather: 'rainy', notes: 'Below-grade pour, east bay.' },
  cp_signature: null,
  cp_name: null,
  status: 'submitted',
  backend_id: null,
  finalized: false,
  push_body: { ...RECORDED_BODY },
  ...over,
});

const cpDraft = (over = {}) => ({
  data: { activities: [{ company: 'Arkon Builders' }] },
  cp_signature: { affirmed: true, signature: 'data:image/png;base64,AAA' },
  cp_name: 'CP',
  status: 'submitted',
  backend_id: null,
  finalized: false,
  push_body: null,
  ...over,
});

const refusal = (status, code) => ({
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail: code ? { code } : 'prose' } },
});

// REACHED THROUGH SHIMS, so a missing export ENUMERATES the gaps instead of
// throwing on the first one. A test that dies at line 1 of a pre-fix run tells
// you one thing; this one tells you everything that is not built yet, which is
// what a failing run is for.
const canDrain = (ds, t) => (
  typeof ds.canDrainLogType === 'function' ? ds.canDrainLogType(t) : 'ABSENT');
const register = (ds, t, fn) => (
  typeof ds.registerDraftPusher === 'function' ? ds.registerDraftPusher(t, fn) : () => {});

(async () => {
  console.log('\n-- the mechanism exists at all --');
  {
    const ds = loadDraftSync(makeEnv({ keys: [], drafts: {} }).env);
    ok(typeof ds.registerDraftPusher === 'function',
      'draftSync exports registerDraftPusher — the per-screen pusher its own '
      + 'header proposed');
    ok(typeof ds.canDrainLogType === 'function',
      'and canDrainLogType, so a screen can ask before it promises anything');
    ok(fs.existsSync(path.join(FRONTEND, 'src', 'utils', 'dailyLogPusher.js')),
      'dailyLogPusher.js exists — the daily log has a pusher of its own');
  }

  console.log('\n-- WITHOUT a pusher, the skip is exactly what it always was --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    const r = await ds.syncPendingDrafts();
    ok(r.synced === 0, 'an unregistered daily-log key is not pushed');
    ok(pending.includes(SITE_KEY),
      'and it stays PENDING — the log is on the device and the queue keeps it');
    ok(canDrain(ds, 'site_daily_log') === false,
      'canDrainLogType says so, which is what the screen copy is allowed to '
      + 'depend on');
    ok(canDrain(ds, 'daily_jobsite') === true,
      'while a standard logbook type was always drainable');
  }

  console.log('\n-- WITH a pusher, it syncs, and the body is the RECORDED one --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    const seen = [];
    register(ds, 'site_daily_log', async (arg) => {
      seen.push(arg);
      return { mode: 'create', backendId: 'dl42' };
    });

    ok(canDrain(ds, 'site_daily_log') === true,
      'the type reports as drainable once a pusher owns it');

    const r = await ds.syncPendingDrafts();
    ok(r.synced === 1, 'the drain reports the daily log as synced');
    ok(seen.length === 1, 'the registered pusher was called exactly once');
    ok(!pending.includes(SITE_KEY),
      'and the pending key is CLEARED — this is the thing that never happened');

    // NOTHING IS RECONSTRUCTED. The pusher is handed the object the screen
    // recorded, not one this module assembled from `data`. Deep-equal rather
    // than a spot check: a dropped audit stamp or an invented field is the
    // failure mode the whole skip existed to prevent.
    ok(seen[0] && JSON.stringify(seen[0].body) === JSON.stringify(RECORDED_BODY),
      'the body handed to the pusher is byte-for-byte the recorded push_body');
    ok(!!seen[0] && seen[0].logType === 'site_daily_log' && seen[0].projectId === 'proj1'
      && seen[0].date === '2026-09-01',
      'along with the identity parsed from the key');
    ok(calls.logbooksCreated.length === 0 && calls.logbooksUpdated.length === 0,
      'and logbooksAPI was never touched — a daily log is not a logbook');
  }

  console.log('\n-- A DRAFT WITH NO RECORDED BODY IS REFUSED, not guessed at --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft({ push_body: null }) },
    });
    const ds = loadDraftSync(env);
    let called = 0;
    register(ds, 'site_daily_log', async () => { called += 1; return {}; });
    const r = await ds.syncPendingDrafts();
    ok(called === 0,
      'a key queued before push_body existed is NOT sent — `data` is not a payload');
    ok(r.synced === 0, 'nothing is reported as synced');
    ok(pending.includes(SITE_KEY),
      'and it stays pending, so the next manual save records a body and files it');
  }

  console.log('\n-- the server id is bound BEFORE the key is dropped --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    register(ds, 'site_daily_log', async () => ({ mode: 'create', backendId: 'dl42' }));
    await ds.syncPendingDrafts();
    ok(calls.boundIds.length === 1 && calls.boundIds[0][1] === 'dl42',
      'a create binds the new id onto the draft — without it the next save '
      + 'POSTs a duplicate log for the same day');
    ok(!pending.includes(SITE_KEY), 'and only then is the key cleared');
  }

  console.log('\n-- a failure of either kind leaves the key PENDING --');
  for (const [label, thrown] of [
    ['a 4xx refusal', refusal(422, 'SUBMIT_EMPTY_LOG')],
    ['an unreachable server (no response)', { message: 'Network Error' }],
    ['a 5xx', refusal(503)],
  ]) {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    register(ds, 'site_daily_log', async () => { throw thrown; });
    const r = await ds.syncPendingDrafts();
    ok(r.synced === 0, `${label}: nothing is reported as synced`);
    ok(pending.includes(SITE_KEY),
      `${label}: the key stays queued and the next reconnect tries again`);
  }

  console.log('\n-- THE CP LOGBOOK PATH, drained from the SAME index --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [CP_KEY, SITE_KEY],
      drafts: { [CP_KEY]: cpDraft(), [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    const seen = [];
    register(ds, 'site_daily_log', async (a) => {
      seen.push(a.key); return { mode: 'create', backendId: 'dl42' };
    });

    const r = await ds.syncPendingDrafts();
    ok(r.attempted === 2 && r.synced === 2, 'both keys drain in one pass');
    // THE TWO SURFACES DO NOT CROSS. This is the regression that would matter:
    // a daily-log pusher must never see a logbook key, and the logbook drain
    // must never see a daily log.
    ok(seen.length === 1 && seen[0] === SITE_KEY,
      'the registered pusher saw ONLY the daily-log key');
    ok(calls.logbooksCreated.length === 1,
      'and the CP logbook went to logbooksAPI exactly as before');
    ok(calls.logbooksCreated[0].data
      && calls.logbooksCreated[0].data.activities,
      'with the standard reconstructed payload, unchanged');
    ok(pending.length === 0, 'each key cleared its own entry, and only its own');
  }
  {
    // AND THE OTHER DIRECTION. A registered daily-log pusher must not change
    // what happens to a logbook key that FAILS: it stays pending, as always.
    const { env, pending, calls } = makeEnv({
      keys: [CP_KEY, SITE_KEY],
      drafts: { [CP_KEY]: cpDraft(), [SITE_KEY]: siteDraft() },
      logbooksRejection: { message: 'Network Error' },
    });
    const ds = loadDraftSync(env);
    register(ds, 'site_daily_log', async () => ({ mode: 'create', backendId: 'dl42' }));
    await ds.syncPendingDrafts();
    ok(pending.includes(CP_KEY),
      'a failed CP logbook push still leaves ITS key pending');
    ok(!pending.includes(SITE_KEY),
      'while the daily log that DID land is cleared — one failure does not '
      + 'strand the other surface');
  }

  console.log('\n-- unregistering restores the old behaviour exactly --');
  {
    const { env, pending, calls } = makeEnv({
      keys: [SITE_KEY], drafts: { [SITE_KEY]: siteDraft() },
    });
    const ds = loadDraftSync(env);
    const off = register(ds, 'site_daily_log', async () => ({ backendId: 'x' }));
    off();
    ok(canDrain(ds, 'site_daily_log') === false, 'the type is skipped again');
    const r = await ds.syncPendingDrafts();
    ok(r.synced === 0 && pending.includes(SITE_KEY),
      'and the key is refused and kept, as it was before any of this');
  }

  console.log('\n-- the REAL daily-log pusher: update vs create, body verbatim --');
  if (!fs.existsSync(path.join(FRONTEND, 'src', 'utils', 'dailyLogPusher.js'))) {
    ok(false, 'dailyLogPusher.js does not exist — nothing to exercise');
  } else {
    const sent = { created: [], updated: [] };
    const registered = [];
    const pusher = loadEsm('src/utils/dailyLogPusher.js', {
      stubs: {
        './api': {
          dailyLogsAPI: {
            create: async (b) => { sent.created.push(b); return { id: 'dl99' }; },
            update: async (id, b) => { sent.updated.push([id, b]); return { id }; },
          },
        },
        './draftSync': {
          registerDraftPusher: (t, fn) => { registered.push([t, fn]); return () => {}; },
        },
      },
    });

    const created = await pusher.pushDailyLogDraft({
      draft: siteDraft(), body: RECORDED_BODY,
    });
    ok(sent.created.length === 1 && sent.updated.length === 0,
      'a draft with no server id CREATES');
    ok(JSON.stringify(sent.created[0]) === JSON.stringify(RECORDED_BODY),
      'and posts the recorded body verbatim — no mapping step, nothing dropped');
    ok(created.backendId === 'dl99' && created.mode === 'create',
      'reporting the new id back so the drain can bind it');

    const updated = await pusher.pushDailyLogDraft({
      draft: siteDraft({ backend_id: 'dl99' }), body: RECORDED_BODY,
    });
    ok(sent.updated.length === 1 && sent.updated[0][0] === 'dl99',
      'a draft that knows its id UPDATES that id — a create here is the '
      + 'duplicate backend_id exists to stop');
    ok(JSON.stringify(sent.updated[0][1]) === JSON.stringify(RECORDED_BODY),
      'with the same verbatim body');
    ok(updated.backendId === 'dl99', 'and keeps the id it already had');

    // A THROW REACHES THE DRAIN. The three-way split between a refusal, an
    // unreachable server and a success is made in ONE place for every log type.
    let threw = false;
    const boom = Object.assign(new Error('nope'), { response: { status: 422 } });
    try {
      await loadEsm('src/utils/dailyLogPusher.js', {
        stubs: {
          './api': { dailyLogsAPI: { create: async () => { throw boom; }, update: async () => {} } },
          './draftSync': { registerDraftPusher: () => () => {} },
        },
      }).pushDailyLogDraft({ draft: siteDraft(), body: RECORDED_BODY });
    } catch (_e) { threw = true; }
    ok(threw, 'a failed push THROWS rather than swallowing — the drain owns the verdict');

    // BOTH SCREENS. The CP's daily log and the superintendent's are different
    // screens over the same endpoint, and both were telling the same lie.
    pusher.registerDailyLogPushers();
    const types = registered.map(([t]) => t).sort();
    ok(types.length === 2 && types[0] === 'daily_log' && types[1] === 'site_daily_log',
      `both daily-log types are registered (${types.join(', ')})`);
    ok(registered.every(([, fn]) => fn === pusher.pushDailyLogDraft),
      'by the same function — a second copy would be a second thing to keep in step');
  }

  console.log('\n-- registered at app start, before the drain, with NO new trigger --');
  {
    const layout = fs.readFileSync(path.join(FRONTEND, 'app', '_layout.jsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    ok(layout.length > 0, '_layout.jsx read and non-empty');
    const regAt = layout.indexOf('registerDailyLogPushers()');
    const syncAt = layout.indexOf('setupDraftAutoSync()');
    ok(regAt !== -1, '_layout registers the pushers');
    ok(syncAt !== -1, 'and still sets up the drain');
    // ORDER IS LOAD-BEARING: setupDraftAutoSync drains ONCE immediately, for the
    // app that was killed with keys pending. Registering after it misses that
    // pass, and a log queued overnight waits for the next reconnect instead.
    ok(regAt !== -1 && syncAt > regAt,
      'the pushers are registered BEFORE the drain, so the startup pass sees them');
    // ONE TRIGGER. The NetInfo listener lives in draftSync and nowhere else.
    ok(!/NetInfo/.test(layout),
      '_layout adds no NetInfo listener of its own — the existing drain trigger is reused');
    const pusherPath = path.join(FRONTEND, 'src', 'utils', 'dailyLogPusher.js');
    // COMMENTS STRIPPED. The module's own prose explains that it reuses the
    // existing NetInfo trigger, and a bare grep would match the explanation.
    const pusherSrc = fs.existsSync(pusherPath)
      ? fs.readFileSync(pusherPath, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      : '';
    ok(pusherSrc.length > 0, 'dailyLogPusher.js read and non-empty');
    ok(!/netinfo|addEventListener/i.test(pusherSrc),
      'and neither does the pusher — it is a payload shape, not a second listener');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
