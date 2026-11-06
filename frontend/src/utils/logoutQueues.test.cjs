/**
 * NOTHING ONE ACCOUNT QUEUED IS EVER SENT UNDER ANOTHER.
 *
 * The bug: logout cleared the token and the user, and left the three device
 * queues that replay on their own — the offline mutation queue, the pending
 * logbook pushes, the filed-photo queue. The next login's startup / reconnect
 * drains then sent them under WHOEVER signed in, possibly another company.
 *
 * Roy's ruling: logout (and account switch) must drain or clear them, so
 * nothing replays under another account.
 *
 * This drives the REAL modules — api.js (its real interceptors, real clearAuth,
 * real 401 handling), offlineQueue, logbookDrafts, draftSync, filedPhotoQueue,
 * accountQueues, logoutQueues — over one fake device (AsyncStorage), one fake
 * network (axios + fetch) and real JWTs. Every request the device makes is
 * recorded WITH the Authorization header it carried, so "sent under B" is read
 * off the wire, not inferred.
 *
 * CONTROL. Against origin/main the two new modules do not exist; the test then
 * performs the logout main performs (authAPI.logout, i.e. clearAuth) and the
 * assertions fail on BEHAVIOUR — A's writes go out with B's token.
 *
 * Run:  node src/utils/logoutQueues.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const exists = (rel) => fs.existsSync(path.join(FRONTEND, rel));
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function section(t) { console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 66 - t.length))}`); }

const QUIET = { log: () => {}, warn: () => {}, error: () => {}, info: () => {} };
const tick = () => new Promise((r) => setTimeout(r, 0));

// ── real JWTs, the shape create_token signs ──────────────────────────────────
const b64url = (o) => Buffer.from(JSON.stringify(o)).toString('base64')
  .replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const jwt = (sub, companyId) => [
  b64url({ alg: 'HS256', typ: 'JWT' }),
  b64url({ sub, company_id: companyId, exp: Math.floor(Date.now() / 1000) + 86400 }),
  'sig',
].join('.');
const TOKEN_A = jwt('user_A', 'company_1');
const TOKEN_B = jwt('user_B', 'company_2');
const TOKENS = { 'a@x.com': TOKEN_A, 'b@x.com': TOKEN_B };
const whoIs = (auth) => {
  if (auth === `Bearer ${TOKEN_A}`) return 'A';
  if (auth === `Bearer ${TOKEN_B}`) return 'B';
  return auth ? 'other' : 'none';
};

const DRAFT_KEY = 'logbook_draft:proj1:toolbox_talk:2026-11-06';

/**
 * ONE DEVICE: storage, network state, and the wire.
 *
 * `hang` makes every write request wait forever (a dead link that NetInfo still
 * reports as up); `gate` holds the bare-fetch queue mid-request until released.
 */
function makeDevice() {
  const store = new Map();
  const wire = [];
  const net = { online: true, hang: false, gate: null, revoke: false };

  const AsyncStorage = {
    getItem: async (k) => (store.has(k) ? store.get(k) : null),
    setItem: async (k, v) => { store.set(k, String(v)); },
    removeItem: async (k) => { store.delete(k); },
    getAllKeys: async () => [...store.keys()],
    multiRemove: async (keys) => { for (const k of keys) store.delete(k); },
  };

  const httpError = (status, data = {}) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data, headers: {} } });
  const never = () => new Promise(() => {});

  // The server. Answers by route; records every request with its identity.
  const server = async (c) => {
    const url = c.url;
    const auth = (c.headers && c.headers.Authorization) || null;
    if (url === '/api/auth/login') {
      const token = TOKENS[c.data && c.data.email];
      if (!token) throw httpError(401);
      return { data: { token }, headers: {}, status: 200 };
    }
    wire.push({ via: 'axios', method: c.method, url, who: whoIs(auth) });
    if (!net.online) throw Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' });
    if (url === '/api/auth/me') {
      if (net.revoke) throw httpError(401);
      return { data: { id: 'me' }, headers: {}, status: 200 };
    }
    if (net.hang) return never();
    if (url === '/api/logbooks' && c.method === 'post') return { data: { id: `log_${wire.length}` }, headers: {}, status: 200 };
    if (/^\/api\/logbooks\/[^/]+\/activity-photo$/.test(url)) {
      return { data: { photo: { photo_id: 'p1' }, activity_index: 0, photo_index: 0 }, headers: {}, status: 200 };
    }
    return { data: { id: 'x' }, headers: {}, status: 200 };
  };

  // axios.create() — a client that RUNS the interceptors api.js registers, so
  // the Authorization header on the wire is the one the real interceptor set.
  const axios = {
    create: () => {
      const reqI = []; const resI = [];
      const client = {
        interceptors: {
          request: { use: (f, r) => { reqI.push([f, r]); } },
          response: { use: (f, r) => { resI.push([f, r]); } },
        },
        async request(cfg) {
          let c = { ...cfg, headers: { ...(cfg.headers || {}) } };
          for (const [f] of reqI) if (f) c = await f(c);
          let res; let err = null;
          try { res = await server(c); } catch (e) { err = e; err.config = c; }
          if (!err) {
            for (const [f] of resI) if (f) res = await f(res);
            return res;
          }
          for (const [, r] of resI) {
            if (!r) continue;
            try { await r(err); } catch (e2) { err = e2; }
          }
          throw err;
        },
        get: (url, cfg = {}) => client.request({ ...cfg, method: 'get', url }),
        delete: (url, cfg = {}) => client.request({ ...cfg, method: 'delete', url }),
        post: (url, data, cfg = {}) => client.request({ ...cfg, method: 'post', url, data }),
        put: (url, data, cfg = {}) => client.request({ ...cfg, method: 'put', url, data }),
        patch: (url, data, cfg = {}) => client.request({ ...cfg, method: 'patch', url, data }),
      };
      return client;
    },
  };

  // offlineQueue's bare fetch.
  const fetch = async (url, opts = {}) => {
    const auth = (opts.headers && opts.headers.Authorization) || null;
    wire.push({ via: 'fetch', method: opts.method, url: String(url).replace(/^https?:\/\/[^/]+/, ''), who: whoIs(auth) });
    if (net.gate) await net.gate;
    if (!net.online) throw new Error('Network request failed');
    if (net.hang) return never();
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const NetInfo = {
    fetch: async () => ({ isConnected: net.online, isInternetReachable: net.online }),
    addEventListener: () => () => {},
  };

  const stubs = {
    '@react-native-async-storage/async-storage': AsyncStorage,
    '@react-native-community/netinfo': NetInfo,
    'react-native': {
      Platform: { OS: 'ios' },
      AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) },
    },
    'expo-file-system/legacy': {
      documentDirectory: 'file:///docs/',
      getInfoAsync: async () => ({ exists: true }),
      makeDirectoryAsync: async () => {},
      copyAsync: async () => {},
    },
    axios,
    'expo-constants': { expoConfig: { version: '1.0.0' }, manifest: null },
  };
  const globals = {
    console: QUIET,
    fetch,
    FormData: class { constructor() { this.parts = {}; } append(k, v) { this.parts[k] = v; } },
  };

  // ONE INSTANCE OF EACH MODULE, wired to each other — the app's graph. Each
  // later module gets the earlier ones as its relative imports, so there is
  // one api.js (one token), one accountQueues (one epoch) for the device.
  const load = (rel, extra = {}) => loadEsm(rel, { stubs: { ...stubs, ...extra }, globals });
  const aq = exists('src/utils/accountQueues.js') ? load('src/utils/accountQueues.js') : null;
  const withAq = aq ? { './accountQueues': aq } : {};
  const api = load('src/utils/api.js', { ...withAq });
  const drafts = load('src/utils/logbookDrafts.js', { './api': api, ...withAq });
  const offlineQueue = load('src/utils/offlineQueue.js', { './api': api, ...withAq });
  const draftSync = load('src/utils/draftSync.js', { './api': api, './logbookDrafts': drafts, ...withAq });
  const photoQueue = load('src/utils/filedPhotoQueue.js', { './logbookDrafts': drafts, ...withAq });
  const logoutQueues = exists('src/utils/logoutQueues.js')
    ? load('src/utils/logoutQueues.js', {
      './offlineQueue': offlineQueue, './draftSync': draftSync, './filedPhotoQueue': photoQueue, ...withAq,
    })
    : null;

  /** AuthContext.login's storage effects: authAPI.login stores the token, then the user. */
  const login = async (email, id) => {
    await api.authAPI.login(email, 'pw');
    await api.setStoredUser({ id, email });
  };

  /**
   * AuthContext.logout, explicit. Main's is authAPI.logout() alone; this
   * branch's drains and clears first (asserted against AuthContext's source
   * below). `drain: false` is "Log out anyway" after the confirm.
   */
  const logout = async ({ drain = true } = {}) => {
    if (logoutQueues) await logoutQueues.drainAndClearAccountQueues({ drain, timeoutMs: 300 });
    await api.authAPI.logout();
  };

  /** Queue one of each kind of write, as whoever is signed in. */
  const queueOneOfEach = async () => {
    await offlineQueue.addToQueue({ type: 'create', table: 'workers', data: { name: 'Worker' } });
    await drafts.writeDraft(DRAFT_KEY, { data: { topic: 'Ladders' }, status: 'draft' });
    await drafts.markPending(DRAFT_KEY);
    await photoQueue.queueFiledPhoto({
      logbookId: 'log9', activityId: 'act1', photoId: 'ph1', uri: 'file:///docs/logbook_photos/ph1.jpg',
    });
  };

  /** Every drain the app runs at startup and on reconnect. */
  const runStartupDrains = async () => {
    await offlineQueue.processQueue();
    await draftSync.syncPendingDrafts();
    await photoQueue.drainFiledPhotoQueue();
  };

  const queued = () => ({
    offline: JSON.parse(store.get('blueview_offline_queue') || '[]').length,
    drafts: JSON.parse(store.get('logbook_pending_push') || '[]').length,
    photos: JSON.parse(store.get('logbook_filed_photo_queue') || '[]').length,
  });
  const writes = () => wire.filter((w) => w.url !== '/api/auth/me');

  return {
    store, wire, net, api, aq, drafts, offlineQueue, draftSync, photoQueue, logoutQueues,
    login, logout, queueOneOfEach, runStartupDrains, queued, writes,
  };
}

(async () => {
  // ══════════════════════════════════════════════════════════════════════════
  section('1. A queues offline, logs out, B logs in: nothing is sent under B');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    const q0 = d.queued();
    ok(q0.offline === 1 && q0.drafts === 1 && q0.photos === 1,
      `A queued one write in each queue (offline ${q0.offline}, drafts ${q0.drafts}, photos ${q0.photos})`);

    await d.logout(); // offline: nothing can go, so it is deleted
    const q1 = d.queued();
    ok(q1.offline === 0 && q1.drafts === 0 && q1.photos === 0,
      `logout left nothing queued on the device (offline ${q1.offline}, drafts ${q1.drafts}, photos ${q1.photos})`);
    ok(!d.store.has(DRAFT_KEY), 'the unsent draft record itself is gone (the next editor cannot open it)');

    await d.login('b@x.com', 'user_B');
    d.net.online = true;
    await d.runStartupDrains();
    const underB = d.writes().filter((w) => w.who === 'B');
    ok(underB.length === 0,
      `B's startup drains sent NONE of A's writes (sent under B: ${JSON.stringify(underB.map((w) => `${w.method} ${w.url}`))})`);
    ok(d.writes().length === 0, `no write request left the device at all (got ${d.writes().length})`);
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('2. Online logout drains FIRST, with A\'s token, then clears');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    d.net.online = true;
    await d.logout();
    const sent = d.writes();
    ok(sent.length === 3, `all three of A's writes were sent at logout (got ${sent.length}: ${JSON.stringify(sent.map((w) => `${w.method} ${w.url}`))})`);
    ok(sent.length > 0 && sent.every((w) => w.who === 'A'), `every one carried A's token (${JSON.stringify(sent.map((w) => w.who))})`);
    ok(sent.some((w) => w.url === '/api/workers') && sent.some((w) => w.url === '/api/logbooks')
      && sent.some((w) => /activity-photo$/.test(w.url)),
    'one from each queue: the worker create, the logbook create, the filed photo');
    const q = d.queued();
    ok(q.offline + q.drafts + q.photos === 0, 'nothing left queued after the logout');
    ok(!d.store.has('blueview_token'), 'and the token is gone, AFTER the drain used it');

    await d.login('b@x.com', 'user_B');
    await d.runStartupDrains();
    ok(d.writes().length === 3, `B's drains sent nothing more (total writes still ${d.writes().length})`);
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('3. Forced logout (the server refuses the session) clears');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    d.net.online = true;
    d.net.revoke = true;
    // A genuine 401 on the identity endpoint: api.js ends the session itself.
    await d.api.handleUnauthorized({ config: { url: '/api/auth/me' } });
    ok(!d.store.has('blueview_token'), 'the 401 ended the session (token removed by api.js)');
    const q = d.queued();
    ok(q.offline + q.drafts + q.photos === 0,
      `and the queues went with it (offline ${q.offline}, drafts ${q.drafts}, photos ${q.photos})`);
    ok(d.writes().length === 0, `nobody was asked and nothing was sent with the refused token (got ${d.writes().length})`);

    d.net.revoke = false;
    await d.login('b@x.com', 'user_B');
    await d.runStartupDrains();
    ok(d.writes().filter((w) => w.who === 'B').length === 0, 'B\'s drains sent nothing of A\'s');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('4. No logout at all: B signs in over A\'s session; replay drops A\'s items');
  {
    // The path a logout cannot cover: A's token ran out (read-only cached
    // mode keeps the queues), and B signs in on the same device.
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    await d.login('b@x.com', 'user_B');
    d.net.online = true;
    await d.runStartupDrains();
    ok(d.writes().length === 0,
      `none of A's writes were sent under B (sent: ${JSON.stringify(d.writes().map((w) => `${w.who} ${w.method} ${w.url}`))})`);
    const q = d.queued();
    ok(q.offline + q.drafts + q.photos === 0, `A's items were DROPPED, not left to retry (offline ${q.offline}, drafts ${q.drafts}, photos ${q.photos})`);

    // B's own writes still go, under B.
    d.net.online = false;
    await d.queueOneOfEach();
    d.net.online = true;
    await d.runStartupDrains();
    const sent = d.writes();
    ok(sent.length === 3 && sent.every((w) => w.who === 'B'), `B's own three writes were sent, under B (${JSON.stringify(sent.map((w) => w.who))})`);
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('5. The mid-login window: B\'s token on disk, A still in the user cache');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    // authAPI.login has stored B's token; /auth/me has not answered yet, so
    // blueview_user still names A. A drain fired by a reconnect right now:
    await d.api.authAPI.login('b@x.com', 'pw');
    d.net.online = true;
    await d.runStartupDrains();
    ok(d.writes().length === 0, `judged by the TOKEN, not the cached user: nothing sent under B (got ${d.writes().length})`);
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('6. Items queued before stamps existed (legacy)');
  {
    const legacy = (d) => {
      d.store.set('blueview_offline_queue', JSON.stringify([{
        id: 'old1', type: 'create', table: 'workers', data: { name: 'Old' }, timestamp: 1, retries: 0,
      }]));
      d.store.set('logbook_filed_photo_queue', JSON.stringify([{
        logbookId: 'log9', activityId: 'act1', photoId: 'old_ph', uri: 'file:///docs/logbook_photos/o.jpg', queuedAt: 1,
      }]));
    };
    // Same user: the session that was already running when the update landed.
    const d1 = makeDevice();
    await d1.login('a@x.com', 'user_A');
    legacy(d1);
    await d1.runStartupDrains();
    ok(d1.writes().length === 2 && d1.writes().every((w) => w.who === 'A'),
      `same account: the legacy items were kept and sent, under A (${JSON.stringify(d1.writes().map((w) => w.who))})`);

    // A different account: the queues were claimed for A at the first drain.
    const d2 = makeDevice();
    await d2.login('a@x.com', 'user_A');
    legacy(d2);
    d2.net.online = false;
    await d2.runStartupDrains(); // A's session sees them first (offline: nothing goes)
    await d2.login('b@x.com', 'user_B');
    d2.net.online = true;
    await d2.runStartupDrains();
    ok(d2.writes().filter((w) => w.who === 'B').length === 0,
      `different account: B's first drains dropped A's legacy items (sent under B: ${d2.writes().filter((w) => w.who === 'B').length})`);
    const q = d2.queued();
    ok(q.offline + q.photos === 0, 'and they are off the device');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('7. Bounded: a dead link cannot hold the logout');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    d.net.online = true;
    d.net.hang = true; // NetInfo says up; nothing ever answers
    const t0 = Date.now();
    await d.logout();
    const ms = Date.now() - t0;
    ok(d.logoutQueues !== null && ms < 2000, `the logout finished in ${ms}ms against a link that never answers (budget 300ms in this test)`);
    const q = d.queued();
    ok(q.offline + q.drafts + q.photos === 0, 'what could not go was cleared');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('8. A drain still in flight when the clear runs writes nothing back');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.offlineQueue.addToQueue({ type: 'create', table: 'workers', data: { name: 'One' } });
    await d.offlineQueue.addToQueue({ type: 'create', table: 'workers', data: { name: 'Two' } });
    d.net.online = true;
    let release;
    d.net.gate = new Promise((r) => { release = r; });
    const inFlight = d.offlineQueue.processQueue(); // suspended inside the first fetch
    await tick();
    await d.logout({ drain: false }); // "Log out anyway"
    d.net.gate = null;
    release();
    await inFlight;
    ok(d.queued().offline === 0, `the queue stayed empty after the in-flight drain finished (got ${d.queued().offline})`);
    ok(d.wire.filter((w) => w.via === 'fetch').length === 1, `and it stopped at the item it was already sending (sent ${d.wire.filter((w) => w.via === 'fetch').length})`);
    await d.login('b@x.com', 'user_B');
    await d.runStartupDrains();
    ok(d.writes().filter((w) => w.who === 'B').length === 0, 'B\'s drains sent nothing of A\'s');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('9. The count the confirm shows, and the per-account caches');
  {
    const d = makeDevice();
    await d.login('a@x.com', 'user_A');
    d.net.online = false;
    await d.queueOneOfEach();
    d.store.set('bv_projects_cache', '[{"id":"proj1"}]');
    d.store.set('bv_project:proj1', '{}');
    d.store.set('bv_checkins_today:proj1', '{}');
    d.store.set('bv_checkins:2026-11-06', '[]');
    d.store.set('blueview_theme', 'dark');
    let left = null;
    if (d.logoutQueues) left = await d.logoutQueues.drainAccountQueues({ timeoutMs: 300 });
    ok(left && left.outcome === 'offline' && left.remaining.total === 3,
      `offline, the drain is skipped and 3 writes are counted for the confirm (got ${left && JSON.stringify(left.remaining)})`);
    await d.logout({ drain: false });
    ok(['bv_projects_cache', 'bv_project:proj1', 'bv_checkins_today:proj1', 'bv_checkins:2026-11-06'].every((k) => !d.store.has(k)),
      'the project and check-in caches went with the account');
    ok(d.store.get('blueview_theme') === 'dark', 'a device preference (theme) did not');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('10. Every logout path is wired');
  {
    const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
    const auth = strip(read('src/context/AuthContext.js'));
    const body = (auth.match(/const logout = async[\s\S]*?\n {2}};/) || [''])[0];
    const iDrain = body.indexOf('drainAndClearAccountQueues(');
    const iClear = body.indexOf('authAPI.logout(');
    ok(iDrain > -1 && iClear > -1 && iDrain < iClear,
      'AuthContext.logout drains-and-clears BEFORE authAPI.logout clears the token');
    ok(/prepareLogout/.test(auth), 'AuthContext exposes prepareLogout (drain, then count)');

    const api = strip(read('src/utils/api.js'));
    const clearAuth = (api.match(/export const clearAuth = async[\s\S]*?\n};/) || [''])[0];
    ok(clearAuth.indexOf('clearAccountQueues(') > -1
      && clearAuth.indexOf('clearAccountQueues(') < clearAuth.indexOf('removeToken('),
    'clearAuth (every forced path: 401, failed restore) empties the queues before removing the token');

    const screens = ['app/settings.jsx', 'app/site/index.jsx', 'app/site/checkins.jsx',
      'app/site/documents.jsx', 'app/demo.jsx', 'app/onboarding.jsx'];
    for (const s of screens) {
      const src = strip(read(s));
      ok(/useLogoutConfirm\(/.test(src) && /\{logoutDialog\}/.test(src) && !/\bawait logout\(\)|onPress=\{logout\}/.test(src),
        `${s}: logs out through useLogoutConfirm and renders its dialog`);
    }
    // No screen anywhere may bypass the confirm by calling logout() itself.
    const walk = (dir, out = []) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
        const p = path.join(dir, e.name);
        if (e.isDirectory()) walk(p, out);
        else if (/\.(js|jsx)$/.test(e.name) && !/\.test\./.test(e.name)) out.push(p);
      }
      return out;
    };
    const bypass = walk(path.join(FRONTEND, 'app')).filter((p) => /onPress=\{logout\}|await logout\(\)/.test(strip(fs.readFileSync(p, 'utf8'))));
    ok(bypass.length === 0, `no screen calls logout() directly (found: ${JSON.stringify(bypass.map((p) => path.relative(FRONTEND, p)))})`);

    const en = loadEsm('src/i18n/en.js').default;
    const es = loadEsm('src/i18n/es.js').default;
    const keys = ['unsentTitle', 'unsentBody', 'unsentBodyOne', 'logOutAnyway', 'cancel'];
    ok(keys.every((k) => en.logout && en.logout[k] && es.logout && es.logout[k] && en.logout[k] !== es.logout[k]),
      'the confirm copy exists in EN and ES');
    ok(en.logout && /\{n\} changes haven't been sent and will be deleted if you log out/.test(en.logout.unsentBody),
      `EN copy is the ruled wording (${en.logout && en.logout.unsentBody})`);
    ok(en.logout && en.logout.logOutAnyway === 'Log out anyway' && en.logout.cancel === 'Cancel', 'buttons: Log out anyway / Cancel');
    const hook = exists('src/hooks/useLogoutConfirm.jsx') ? strip(read('src/hooks/useLogoutConfirm.jsx')) : '';
    ok(/useT\('logout'\)/.test(hook) && /logout\(\{ drain: false \}\)/.test(hook),
      'the confirm reads the logout namespace, and "Log out anyway" clears without a second drain');

    // The storage keys accountQueues clears are the keys the queues write.
    const aqSrc = exists('src/utils/accountQueues.js') ? read('src/utils/accountQueues.js') : '';
    for (const [mod, key] of [['src/utils/offlineQueue.js', 'blueview_offline_queue'],
      ['src/utils/logbookDrafts.js', 'logbook_pending_push'],
      ['src/utils/filedPhotoQueue.js', 'logbook_filed_photo_queue'],
      ['src/utils/api.js', 'blueview_token']]) {
      ok(read(mod).includes(`'${key}'`) && aqSrc.includes(`'${key}'`), `${key}: the key ${path.basename(mod)} writes is the key accountQueues reads`);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('11. The verdict, by itself');
  {
    const aq = makeDevice().aq;
    const v = aq ? aq.replayVerdict : () => 'n/a';
    ok(v('A|1', 'A|1', null) === 'send', 'stamped, same account: send');
    ok(v('A|1', 'B|2', null) === 'drop', 'stamped, other account: drop');
    ok(v('A|1', 'A|2', null) === 'drop', 'stamped, same person in ANOTHER company: drop');
    ok(v('A|1', null, null) === 'hold', 'stamped, nobody signed in: hold (not sent, not dropped)');
    ok(v(null, 'B|2', 'A|1') === 'drop', 'legacy, queue recorded for another account: drop');
    ok(v(null, 'A|1', 'A|1') === 'send', 'legacy, queue recorded for this account: send');
    ok(v(null, 'A|1', null) === 'send', 'legacy, nothing recorded: send (and the caller claims the record)');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})().catch((e) => {
  console.log(`  FAIL  the test itself threw: ${e && e.stack}`);
  console.log(`\n${passed} passed, ${failed + 1} failed`);
  process.exitCode = 1;
});
