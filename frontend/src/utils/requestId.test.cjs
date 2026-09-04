/**
 * ONE ID PER LOGICAL REQUEST — and the word that carries the weight is LOGICAL.
 *
 * WHAT IT IS FOR. One tap on Amend, two arrivals of POST /amend 3.2s apart, on
 * two containers behind two edge IPs. Nothing in this client re-issues (axios
 * 0.27.2, no axios-retry, three interceptors none of which resends) and 3.2s
 * fits no timeout we own — DEFAULT_TIMEOUT_MS is 25000 and every call-site
 * override is LARGER. So the replay is below the application. Eight hours of
 * production logs could not prove that, because no request carried an identity
 * two log lines could be joined on.
 *
 * THE DISCRIMINATION THE HEADER BUYS, and the ONLY property that delivers it:
 *
 *     same id, two arrivals   ->  the transport replayed ONE request
 *     two ids, two arrivals   ->  the client issued TWO
 *
 * A retry below the app replays the serialized bytes, header included, so it
 * cannot help but reuse the id. What the CLIENT must not do is mint a new id
 * for a retry of its own — that would make every attempt look like a new write
 * and the header would say nothing at all. Hence the two assertions that
 * matter here: minted when absent, and NEVER overwritten when present.
 *
 *   node frontend/src/utils/requestId.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const UTILS = __dirname;
const REPO = path.join(UTILS, '..', '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS  ', label); }
  else { failed += 1; console.log('  FAIL  ', label); }
}
function section(t) {
  console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 60 - t.length))}`);
}

const QUIET = { log: () => {}, warn: () => {}, error: () => {}, info: () => {} };

/* ══════════════════════════════════════════════════════════════════════════
 * api.js — the REAL request interceptor, executed
 * ═══════════════════════════════════════════════════════════════════════ */

// A fake axios that captures the interceptor functions api.js registers, so
// the shipped interceptor body runs rather than a hand-copy of it.
function loadApi() {
  const requestInterceptors = [];
  const fakeClient = {
    interceptors: {
      request: { use: (fn) => { requestInterceptors.push(fn); } },
      response: { use: () => {} },
    },
    get: async () => ({ data: {} }),
    post: async () => ({ data: {} }),
    put: async () => ({ data: {} }),
    delete: async () => ({ data: {} }),
    patch: async () => ({ data: {} }),
  };
  const mod = loadEsm('src/utils/api.js', {
    stubs: {
      axios: { create: () => fakeClient },
      '@react-native-async-storage/async-storage': {
        getItem: async () => null, setItem: async () => {}, removeItem: async () => {},
      },
      'expo-constants': { expoConfig: { version: '1.2.3' }, manifest: null },
    },
    globals: { console: QUIET },
  });
  return { mod, requestInterceptors };
}

section('api.js — the shipped request interceptor');
const { mod: api, requestInterceptors } = loadApi();

ok(requestInterceptors.length >= 1, 'the request interceptor was registered and captured');
ok(api.REQUEST_ID_HEADER === 'X-Request-Id',
  `the header name is X-Request-Id (got ${api.REQUEST_ID_HEADER})`);
ok(typeof api.newRequestId === 'function', 'newRequestId is exported');

const applyRequest = requestInterceptors[0];

(async () => {
  // ── Minted when the config carries none ────────────────────────────────
  const a = await applyRequest({ headers: {}, url: '/api/logbooks/x/amend', method: 'post' });
  const idA = a.headers[api.REQUEST_ID_HEADER];
  ok(typeof idA === 'string' && idA.length > 0,
    `a request with no id is given one (got ${JSON.stringify(idA)})`);

  // ── Two separate logical requests get two DIFFERENT ids ────────────────
  const b = await applyRequest({ headers: {}, url: '/api/logbooks/x/amend', method: 'post' });
  ok(b.headers[api.REQUEST_ID_HEADER] !== idA,
    'two separate requests are given DIFFERENT ids — two taps are distinguishable');

  // ── SAME MILLISECOND. The offline-queue duplicate arrives this way, and a
  //    timestamp alone would hand both arrivals one id and hide the very case
  //    the header exists to name.
  const burst = [];
  for (let i = 0; i < 200; i += 1) burst.push(api.newRequestId());
  ok(new Set(burst).size === burst.length,
    `200 ids minted in one tight loop are all distinct (got ${new Set(burst).size} unique)`);

  // ── NEVER OVERWRITTEN — the property the whole design rests on ──────────
  const kept = await applyRequest({
    headers: { 'X-Request-Id': 'the-original-id' },
    url: '/api/logbooks/x/amend', method: 'post',
  });
  ok(kept.headers[api.REQUEST_ID_HEADER] === 'the-original-id',
    'an id already on the headers is NOT replaced — a retry keeps its identity');

  const viaConfig = await applyRequest({
    headers: {}, requestId: 'carried-on-the-config',
    url: '/api/logbooks/x/amend', method: 'post',
  });
  ok(viaConfig.headers[api.REQUEST_ID_HEADER] === 'carried-on-the-config',
    'config.requestId lets a caller re-issue the SAME logical request under its id');

  // ── The charset the server will accept ─────────────────────────────────
  const SERVER_RE = /^[A-Za-z0-9._-]{1,128}$/;
  ok(burst.every((v) => SERVER_RE.test(v)),
    'every minted id satisfies the charset/length the server middleware accepts');

  queueCase();
})().catch((e) => {
  failed += 1; console.log('  FAIL   api.js interceptor case threw:', e.message);
  queueCase();
});

/* ══════════════════════════════════════════════════════════════════════════
 * offlineQueue — the id is minted at ENQUEUE and survives the queue's retry
 * ═══════════════════════════════════════════════════════════════════════ */

function queueCase() {
  section('offlineQueue — the id is minted at the tap, not at the dispatch');
  const store = new Map();
  const posts = [];
  let minted = 0;

  const load = ({ failFirst = false } = {}) => loadEsm('src/utils/offlineQueue.js', {
    stubs: {
      '@react-native-async-storage/async-storage': {
        getItem: async (k) => (store.has(k) ? store.get(k) : null),
        setItem: async (k, v) => { store.set(k, v); },
        removeItem: async (k) => { store.delete(k); },
      },
      '@react-native-community/netinfo': {
        fetch: async () => ({ isConnected: true, isInternetReachable: true }),
        addEventListener: () => () => {},
      },
      './api': {
        getToken: async () => 'tok',
        REQUEST_ID_HEADER: 'X-Request-Id',
        newRequestId: () => { minted += 1; return `minted-${minted}`; },
      },
    },
    globals: {
      console: QUIET,
      fetch: async (url, opts) => {
        posts.push({ url, headers: opts.headers });
        await new Promise((r) => setTimeout(r, 0));
        if (failFirst && posts.length === 1) throw new Error('Network request failed');
        return { ok: true, status: 200, json: async () => ({}) };
      },
    },
  });

  const run = async () => {
    const first = load({ failFirst: true });
    await first.addToQueue({ type: 'create', table: 'daily_logs', data: { n: 1 } });

    ok(minted === 1,
      `the id is minted ONCE, when the item is queued (newRequestId called ${minted}x)`);
    const stored = JSON.parse(store.get('blueview_offline_queue'))[0];
    ok(stored.requestId === 'minted-1',
      `the id is PERSISTED on the queued item (got ${JSON.stringify(stored.requestId)})`);

    // Attempt 1 fails; the item stays queued with its retry count bumped.
    await first.processQueue();
    ok(posts.length === 1 && posts[0].headers['X-Request-Id'] === 'minted-1',
      'attempt 1 goes out carrying the id minted at enqueue');

    const afterFail = JSON.parse(store.get('blueview_offline_queue'))[0];
    ok(afterFail && afterFail.requestId === 'minted-1',
      'the id is unchanged on the still-queued item after a failed attempt');
    ok(afterFail && afterFail.retries === 1,
      `the retry count moved instead (got ${afterFail && afterFail.retries})`);

    // Attempt 2 — a NEW module instance, i.e. after a restart. Same id.
    const second = load();
    await second.processQueue();
    ok(posts.length === 2 && posts[1].headers['X-Request-Id'] === 'minted-1',
      'the RETRY carries the SAME id — one logical write attempted twice, not two writes');
    ok(minted === 1,
      `no second id was ever minted for this item (newRequestId called ${minted}x total)`);
  };

  run().then(serverCase).catch((e) => {
    failed += 1; console.log('  FAIL   offlineQueue request-id case threw:', e.message);
    serverCase();
  });
}

/* ══════════════════════════════════════════════════════════════════════════
 * The server half — a header nobody consumes is decoration
 * ═══════════════════════════════════════════════════════════════════════ */

function serverCase() {
  section('backend — the header is actually consumed');
  const SERVER = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');

  ok(/CLIENT_REQUEST_ID_HEADER\s*=\s*"X-Request-Id"/.test(SERVER),
    'the server names the same header the client sends');

  const mwAt = SERVER.indexOf('async def client_request_id_middleware');
  ok(mwAt > 0, 'the middleware exists');
  const mw = SERVER.slice(mwAt, mwAt + 2600);

  ok(/request\.headers\.get\(CLIENT_REQUEST_ID_HEADER\)/.test(mw),
    'it READS the header off the request — not decoration');
  ok(/sanitized_client_request_id/.test(mw),
    'the value is validated before it is used');
  ok(/request\.state\.client_request_id\s*=/.test(mw),
    'the id is put on request.state, so a handler can reach it');
  ok(/response\.headers\[CLIENT_REQUEST_ID_HEADER\]/.test(mw),
    'the id is echoed back, so a device can quote the id it was served under');
  ok(/_request_id_logger\.info/.test(mw),
    'a log line is emitted — this is the join key the investigation needs');
  ok(/"POST", "PUT", "PATCH", "DELETE"/.test(mw),
    'logged for MUTATING methods; a replayed GET is not the problem');

  // Minted server-side when absent, or a request from an older build is the
  // one request that cannot be correlated later.
  ok(/uuid\.uuid4\(\)\.hex/.test(mw) && /origin/.test(mw),
    'an absent id is minted server-side and the origin is recorded');

  // ── THE TWO CORS LINES, which are the difference between a header that
  //    works on the web build and one that silently does not ──────────────
  // The list is now named once as CORS_ALLOW_HEADERS and read by three
  // things — the registration, the refusal recorder and /api/health — so
  // both halves are asserted: the name is on the list, and the list is what
  // is actually registered.
  ok(/CORS_ALLOW_HEADERS = \[[^\]]*CLIENT_REQUEST_ID_HEADER/s.test(SERVER),
    'the header is in CORS_ALLOW_HEADERS — or the browser refuses to SEND it');
  ok(/allow_headers=CORS_ALLOW_HEADERS/.test(SERVER),
    '...and that list is the one handed to the middleware');
  ok(/expose_headers=\[[^\]]*CLIENT_REQUEST_ID_HEADER/s.test(SERVER),
    'the header is in expose_headers — or the browser hides the echo');

  // ── AND CORS IS STILL THE OUTERMOST LAYER ──────────────────────────────
  // The new middleware is registered BEFORE the CORS block, so Starlette's
  // prepend leaves CORS outside it. Registering it after would put CORS inside
  // and reopen the bug test_cors_survives_rate_limit exists for.
  const midAt = SERVER.indexOf('@app.middleware("http")');
  // \w* because the registered class is CountingCORSMiddleware — a subclass
  // that records refused preflights and decides nothing.
  const corsAt = SERVER.search(/app\.add_middleware\(\s*\w*CORSMiddleware/);
  ok(midAt > 0 && corsAt > 0 && midAt < corsAt,
    'the request-id middleware is registered BEFORE CORS, so CORS stays outermost');

  finish();
}

function finish() {
  console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILURES'} — ${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
}
