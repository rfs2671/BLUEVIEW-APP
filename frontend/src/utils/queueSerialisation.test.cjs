/**
 * TWO DRAINS THAT GENUINELY OVERLAP MUST PRODUCE ONE POST PER ITEM.
 *
 * THE SYMPTOM THIS IS WRITTEN AGAINST. Duplicate rows on a NON-IDEMPOTENT
 * create, arriving in the SAME MILLISECOND. A retry needs a round trip and a
 * round trip does not fit in a millisecond, so these are not retries: they are
 * N concurrent drains each holding its own copy of one queued item.
 *
 * WHY THE OBVIOUS TEST IS WORTHLESS. Calling the lock twice in sequence —
 * `await acquire(); await acquire()` — passes with every defect below still
 * present, because the second call runs after the first has finished writing.
 * The defect is an INTERLEAVING, so the test has to interleave. Every case
 * here starts both drains and awaits them together (Promise.all over two
 * un-awaited calls), which is the only shape that puts a second caller inside
 * the first caller's await window.
 *
 * THE FOUR DEFECTS, all in offlineQueue.js as it stood:
 *
 *   1. processQueue read the whole queue, dispatched every item, and wrote the
 *      survivors back ONLY AT THE END — so the entire drain was a window in
 *      which the queue on disk still lists items already posted.
 *   2. acquireSyncLock AWAITED between its check and its set (getItem, then
 *      setItem), so two callers both read "no lock" and both took it. An
 *      AsyncStorage read-modify-write is not a lock; there is no CAS.
 *   3. DatabaseContext.performSync guards on `isSyncing`, a per-render state
 *      value, so the guard reads the value captured at render and never the
 *      one just set. (Not fixed there — fixed HERE, by making the queue itself
 *      unable to run twice. A caller-side guard cannot serialise callers it
 *      does not know about, and there are three.)
 *   4. Three triggers fire unsynchronised — startup, the NetInfo transition,
 *      and the manual Sync button — two of them on ONE reconnect, 2s apart.
 *
 * filedPhotoQueue.js already solved exactly this with a SYNCHRONOUS in-process
 * flag (`let _draining = false`, checked and set with no await between). That
 * is the mechanism both offlineQueue and draftSync now use, so there is one
 * idiom in the codebase rather than three.
 *
 *   node frontend/src/utils/queueSerialisation.test.cjs
 */
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS  ', label); }
  else { failed += 1; console.log('  FAIL  ', label); }
}
function section(t) {
  console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 60 - t.length))}`);
}

const QUIET = {
  log: () => {}, warn: () => {}, error: () => {}, info: () => {},
};

/** A fake AsyncStorage over a caller-supplied Map, so a "restart" reuses disk. */
function fakeStorage(store) {
  return {
    getItem: async (k) => (store.has(k) ? store.get(k) : null),
    setItem: async (k, v) => { store.set(k, v); },
    removeItem: async (k) => { store.delete(k); },
  };
}

/** Yield to the macrotask queue — a real await window, not a microtask hop. */
const tick = () => new Promise((r) => setTimeout(r, 0));

/* ══════════════════════════════════════════════════════════════════════════
 * offlineQueue — the module that posts the non-idempotent creates
 * ═══════════════════════════════════════════════════════════════════════ */

function loadQueue({ store = new Map(), onFetch } = {}) {
  const posts = [];
  const mod = loadEsm('src/utils/offlineQueue.js', {
    stubs: {
      '@react-native-async-storage/async-storage': fakeStorage(store),
      '@react-native-community/netinfo': {
        fetch: async () => ({ isConnected: true, isInternetReachable: true }),
        addEventListener: () => () => {},
      },
      './api': {
        getToken: async () => 'tok',
        newRequestId: () => `rid-${posts.length}-${Math.random().toString(36).slice(2, 8)}`,
        REQUEST_ID_HEADER: 'X-Request-Id',
      },
    },
    globals: {
      console: QUIET,
      // THE DISPATCH IS WHERE THE OVERLAP LIVES. It awaits a real timer, so
      // the first drain is genuinely suspended here while the second runs.
      fetch: async (url, opts) => {
        posts.push({ url, method: opts.method, headers: opts.headers, body: opts.body });
        await tick();
        if (onFetch) return onFetch(posts.length);
        return { ok: true, status: 200, json: async () => ({}) };
      },
    },
  });
  return { mod, posts, store };
}

section('offlineQueue — two overlapping drains, one queued create');
{
  const { mod, posts, store } = loadQueue();
  const run = async () => {
    await mod.addToQueue({ type: 'create', table: 'daily_logs', data: { note: 'one tap' } });
    ok(JSON.parse(store.get('blueview_offline_queue')).length === 1,
      'exactly one item is queued to begin with');

    // NOT awaited in sequence. Both calls are started, then awaited together —
    // the second enters while the first is suspended in its dispatch.
    const [a, b] = await Promise.all([mod.processQueue(), mod.processQueue()]);

    ok(posts.length === 1,
      `one queued item produced exactly ONE POST (got ${posts.length})`);
    ok(a.processed + b.processed === 1,
      `the two drains together report ONE processed item (got ${a.processed + b.processed})`);
    ok(JSON.parse(store.get('blueview_offline_queue')).length === 0,
      'the queue is empty afterwards — the item is not left for a third drain');
  };
  run().then(() => phase2()).catch((e) => {
    failed += 1; console.log('  FAIL   offlineQueue concurrency threw:', e.message);
    phase2();
  });
}

/* ── Three drains, three items — the N-concurrent case ──────────────────── */
function phase2() {
  section('offlineQueue — three overlapping drains, three queued creates');
  const { mod, posts, store } = loadQueue();
  const run = async () => {
    for (const n of [1, 2, 3]) {
      await mod.addToQueue({ type: 'create', table: 'daily_logs', data: { n } });
    }
    const results = await Promise.all([
      mod.processQueue(), mod.processQueue(), mod.processQueue(),
    ]);

    ok(posts.length === 3,
      `three items across three concurrent drains produced THREE posts (got ${posts.length})`);
    const bodies = posts.map((p) => p.body);
    ok(new Set(bodies).size === bodies.length,
      'no queued item was posted twice — every body is distinct');
    const total = results.reduce((s, r) => s + (r.processed || 0), 0);
    ok(total === 3, `the drains together report THREE processed (got ${total})`);
    ok(JSON.parse(store.get('blueview_offline_queue')).length === 0,
      'nothing is left queued');
  };
  run().then(() => phase3()).catch((e) => {
    failed += 1; console.log('  FAIL   offlineQueue N-concurrency threw:', e.message);
    phase3();
  });
}

/* ── Defect 1 on its own: a drain that NEVER FINISHES ───────────────────── */
function phase3() {
  section('offlineQueue — a drain killed mid-flight does not replay what it posted');
  // THIS ONE HAS NO CONCURRENCY IN IT AT ALL, and it is the case a lock can
  // never fix. Three items. Item 1 posts and lands. Item 2's request is still
  // in flight when the OS kills the app — a backgrounded phone in a cellar is
  // the ordinary way this happens, not an exotic one.
  //
  // processQueue wrote the survivors back ONLY on the way out, so a drain that
  // never reaches its end never writes anything: item 1 is still on disk,
  // already posted, and the next cold launch posts it a second time. One tap,
  // two rows, no race.
  const store = new Map();
  const HANG = new Promise(() => {}); // never settles — the process is gone
  const first = loadQueue({
    store,
    onFetch: (n) => (n === 2
      ? HANG
      : { ok: true, status: 200, json: async () => ({}) }),
  });
  const run = async () => {
    for (const n of [1, 2, 3]) {
      await first.mod.addToQueue({ type: 'create', table: 'daily_logs', data: { n } });
    }
    // Started and then ABANDONED. Never awaited, because it never returns.
    first.mod.processQueue().catch(() => {});
    for (let i = 0; i < 8; i += 1) await tick();

    const posted = first.posts.map((p) => JSON.parse(p.body).n);
    ok(posted.includes(1) && posted.includes(2) && !posted.includes(3),
      `the abandoned drain posted item 1 and stalled inside item 2 (posted ${JSON.stringify(posted)})`);

    // Cold launch over the SAME disk — a fresh module instance, so nothing is
    // carried over but the storage, exactly as a real restart.
    const second = loadQueue({ store });
    await second.mod.processQueue();
    const repostedOne = second.posts.filter((p) => JSON.parse(p.body).n === 1).length;
    ok(repostedOne === 0,
      `item 1 already landed and is NOT posted again after the restart (got ${repostedOne} repost(s))`);
    const repostedThree = second.posts.filter((p) => JSON.parse(p.body).n === 3).length;
    ok(repostedThree === 1,
      `item 3 never went out and IS posted after the restart (got ${repostedThree})`);
  };
  run().then(() => phase4()).catch((e) => {
    failed += 1; console.log('  FAIL   interrupted-drain case threw:', e.message);
    phase4();
  });
}

/* ══════════════════════════════════════════════════════════════════════════
 * draftSync — the other unsynchronised drain, which had no lock at all
 * ═══════════════════════════════════════════════════════════════════════ */

function loadDraftSync({ keys }) {
  const creates = [];
  const cleared = [];
  const mod = loadEsm('src/utils/draftSync.js', {
    stubs: {
      '@react-native-async-storage/async-storage': fakeStorage(new Map()),
      '@react-native-community/netinfo': {
        fetch: async () => ({ isConnected: true, isInternetReachable: true }),
        addEventListener: () => () => {},
      },
      './api': {
        logbooksAPI: {
          create: async (body) => {
            creates.push(body);
            await tick();
            return { id: `srv-${creates.length}` };
          },
          update: async () => { await tick(); return {}; },
          finalize: async () => ({}),
        },
      },
      './logbookDrafts': {
        getPendingKeys: async () => keys.slice(),
        readDraft: async () => ({
          data: { note: 'content' }, cp_signature: null, cp_name: null,
          status: 'draft', backend_id: null, finalized: false,
        }),
        setDraftBackendId: async () => {},
        clearPending: async (k) => { cleared.push(k); },
        writeDraft: async () => {},
        uploadPendingActivityPhotos: async (_p, acts) => ({
          uploaded: 0, remaining: 0, activities: acts,
        }),
      },
    },
    globals: { console: QUIET },
  });
  return { mod, creates, cleared };
}

function phase4() {
  section('draftSync — two overlapping drains, one pending draft');
  const KEY = 'logbook_draft:proj1:toolbox_talk:2026-09-03';
  const { mod, creates } = loadDraftSync({ keys: [KEY] });
  const run = async () => {
    const [a, b] = await Promise.all([mod.syncPendingDrafts(), mod.syncPendingDrafts()]);
    ok(creates.length === 1,
      `one pending draft produced exactly ONE create (got ${creates.length})`);
    ok(a.synced + b.synced === 1,
      `the two drains together report ONE synced draft (got ${a.synced + b.synced})`);
  };
  run().then(() => phase5()).catch((e) => {
    failed += 1; console.log('  FAIL   draftSync concurrency threw:', e.message);
    phase5();
  });
}

/* ── The two triggers setupDraftAutoSync itself installs ────────────────── */
function phase5() {
  section('draftSync — startup and reconnect are the two real triggers');
  const KEY = 'logbook_draft:proj1:toolbox_talk:2026-09-03';
  const listeners = [];
  const creates = [];
  const mod = loadEsm('src/utils/draftSync.js', {
    stubs: {
      '@react-native-async-storage/async-storage': fakeStorage(new Map()),
      '@react-native-community/netinfo': {
        fetch: async () => ({ isConnected: true, isInternetReachable: true }),
        addEventListener: (fn) => { listeners.push(fn); return () => {}; },
      },
      './api': {
        logbooksAPI: {
          create: async (body) => { creates.push(body); await tick(); return { id: 'srv-1' }; },
          update: async () => { await tick(); return {}; },
          finalize: async () => ({}),
        },
      },
      './logbookDrafts': {
        getPendingKeys: async () => [KEY],
        readDraft: async () => ({
          data: { note: 'content' }, cp_signature: null, cp_name: null,
          status: 'draft', backend_id: null, finalized: false,
        }),
        setDraftBackendId: async () => {},
        clearPending: async () => {},
        writeDraft: async () => {},
        uploadPendingActivityPhotos: async (_p, acts) => ({
          uploaded: 0, remaining: 0, activities: acts,
        }),
      },
    },
    globals: { console: QUIET },
  });
  const run = async () => {
    // setup fires the STARTUP drain synchronously; the reconnect transition
    // then fires a second one while the first is still in its create.
    mod.setupDraftAutoSync();
    listeners[0]({ isConnected: false, isInternetReachable: false });
    listeners[0]({ isConnected: true, isInternetReachable: true });
    await tick(); await tick(); await tick(); await tick();
    ok(creates.length <= 1,
      `startup + reconnect on ONE pending draft produced at most one create (got ${creates.length})`);
  };
  run().then(finish).catch((e) => {
    failed += 1; console.log('  FAIL   draftSync trigger case threw:', e.message);
    finish();
  });
}

/* ══════════════════════════════════════════════════════════════════════════
 * The controls: these assertions MUST be able to fail
 * ═══════════════════════════════════════════════════════════════════════ */
function finish() {
  section('the weak test this file exists to replace');
  // Documented, not asserted as a pass: two SEQUENTIAL drains obviously post
  // once each, and that is true with every defect present. It is recorded here
  // so nobody replaces the concurrent cases above with this one.
  console.log('  NOTE   a sequential `await drain(); await drain();` passes with all');
  console.log('         four defects present — it never interleaves. Every case');
  console.log('         above starts both drains before awaiting either.');

  console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILURES'} — ${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
}
