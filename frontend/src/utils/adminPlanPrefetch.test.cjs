/**
 * AN ADMIN'S PHONE FILLS ITSELF, AND THE FOUR WAYS A PHONE IS NOT A TABLET.
 *
 * THE RULING. Every device that can view plans holds every plan for its
 * projects, offline and complete, with no user action — because the sheet an
 * inspector asks about is the one nobody opened. The gate tablet has done this
 * since siteManifestStore shipped; an admin's phone did nothing at all, caching
 * a plan only at the moment it was tapped.
 *
 * WHAT THIS FILE HOLDS — the four differences, each of which is a way the
 * tablet's design would be wrong on a phone:
 *
 *   1. ALL ASSIGNED PROJECTS, not "the ones he is on". Measured at ~100 MB
 *      today. "The ones he is on" invites the exact failure the ruling
 *      removes.
 *   2. MOST-RECENTLY-OPENED FIRST, so an interrupted phone holds the useful
 *      half rather than whichever half the server listed first.
 *   3. UNMETERED BY DEFAULT. A hundred megabytes of plans over cellular is a
 *      bill nobody agreed to — but an UNKNOWN answer is treated as unmetered,
 *      because refusing to fill a phone the platform declined to describe
 *      reproduces the empty-device failure against a device probably on Wi-Fi.
 *   4. NO INTERVAL. A timer fires only while the app is already foregrounded,
 *      which the foreground trigger already covers.
 *
 * AND THE PROPERTY THAT MATTERS MOST: one project failing does not end the
 * walk. The next project may be the one he needs.
 *
 * Run:  node src/utils/adminPlanPrefetch.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const HERE = __dirname;

function makeDevice(opts) {
  const o = opts || {};
  const store = {};
  const listeners = { net: [], app: [] };
  return {
    store,
    listeners,
    AsyncStorage: {
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => {
        if (o.failSetItem) throw new Error('database or disk is full (code 13)');
        store[k] = v;
      },
      removeItem: async (k) => { delete store[k]; },
      getAllKeys: async () => Object.keys(store),
    },
    NetInfo: {
      addEventListener: (fn) => {
        listeners.net.push(fn);
        return () => { listeners.net = listeners.net.filter((x) => x !== fn); };
      },
      fetch: async () => o.net || { isConnected: true, isInternetReachable: true, details: {} },
    },
    AppState: {
      currentState: 'active',
      addEventListener: (_t, fn) => {
        listeners.app.push(fn);
        return { remove: () => { listeners.app = listeners.app.filter((x) => x !== fn); } };
      },
    },
  };
}

const compiled = {};
function load(device, rel) {
  const full = path.join(HERE, rel);
  const key = `${rel}`;
  if (!(key in compiled)) {
    compiled[key] = babel.transformSync(fs.readFileSync(full, 'utf8'), {
      filename: full,
      plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
      configFile: false,
      babelrc: false,
    }).code;
  }
  const m = {};
  const shim = (spec) => {
    if (spec === '@react-native-async-storage/async-storage') {
      return { __esModule: true, default: device.AsyncStorage };
    }
    if (spec === '@react-native-community/netinfo') {
      return { __esModule: true, default: device.NetInfo };
    }
    if (spec === 'react-native') return { AppState: device.AppState };
    if (spec === './api') return { projectsAPI: { getAll: async () => [] } };
    if (spec === './siteManifestStore') {
      return {
        syncSiteManifest: async () => ({ ok: true }),
        DISK_RESERVE_PHONE_BYTES: 1024 * 1024 * 1024,
      };
    }
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compiled[key])(m, { exports: m }, shim);
  return m;
}

(async () => {
  console.log('\nAdmin plan prefetch\n');

  // ══ 1. ORDER: most-recently-opened first, never-opened kept ════════════
  {
    const M = load(makeDevice({}), 'adminPlanPrefetch.js');
    const order = M.orderProjects(['a', 'b', 'c'], { b: 300, a: 100 });
    ok(JSON.stringify(order) === JSON.stringify(['b', 'a', 'c']),
      'most-recently-opened first, and a project never opened sorts last');
    ok(M.orderProjects(['a', 'b', 'c'], {}).length === 3,
      'a project never opened is NOT dropped — it is the sheet he never looked at');
    ok(JSON.stringify(M.orderProjects(['c', 'a', 'b'], {}))
       === JSON.stringify(M.orderProjects(['b', 'c', 'a'], {})),
      'the never-opened tail is stable, so two phones fill in the same direction');
    ok(JSON.stringify(M.orderProjects(['a', 'a', 'b'], {})) === JSON.stringify(['a', 'b']),
      'a duplicated assignment is walked once');
  }

  // ══ 2. THE OPEN RECORD ═════════════════════════════════════════════════
  {
    const d = makeDevice({});
    const M = load(d, 'adminPlanPrefetch.js');
    await M.noteProjectOpened('P1', 1000);
    await M.noteProjectOpened('P2', 2000);
    const map = await M.readLastOpened();
    ok(map.P1 === 1000 && map.P2 === 2000, 'opening a project is recorded');

    const bad = makeDevice({ failSetItem: true });
    const MB = load(bad, 'adminPlanPrefetch.js');
    let threw = null;
    try { await MB.noteProjectOpened('P1'); } catch (e) { threw = e; }
    ok(threw === null,
      'a device that cannot write the hint still opens the screen — an ordering '
      + 'hint must never be able to fail a plan list');
    ok(JSON.stringify(await MB.readLastOpened()) === '{}',
      'and an unreadable record reads as no history rather than throwing');
  }

  // ══ 3. METERED ═════════════════════════════════════════════════════════
  {
    const M = load(makeDevice({}), 'adminPlanPrefetch.js');
    const wifi = { isConnected: true, isInternetReachable: true, details: { isConnectionExpensive: false } };
    const cell = { isConnected: true, isInternetReachable: true, details: { isConnectionExpensive: true } };
    const unknown = { isConnected: true, isInternetReachable: true, details: {} };
    const off = { isConnected: false, isInternetReachable: false, details: {} };

    ok(M.mayDownloadOn(wifi) === true, 'wi-fi downloads');
    ok(M.mayDownloadOn(cell) === false, 'a metered connection defers by default');
    ok(M.mayDownloadOn(cell, true) === true, 'and the override is explicit');
    ok(M.mayDownloadOn(unknown) === true,
      'an UNKNOWN answer is treated as unmetered — refusing to fill a phone the '
      + 'platform declined to describe is the empty-device failure again, '
      + 'against a device probably on wi-fi');
    ok(M.mayDownloadOn(off) === false, 'offline downloads nothing');
    ok(M.mayDownloadOn(off, true) === false,
      'and the metered override does not conjure a connection');
  }

  // ══ 4. THE WALK ════════════════════════════════════════════════════════
  {
    const d = makeDevice({});
    const M = load(d, 'adminPlanPrefetch.js');
    await M.noteProjectOpened('P3', 5000);

    const seen = [];
    const opts = {
      listProjects: async () => [{ id: 'P1' }, { id: 'P2' }, { _id: 'P3' }],
      run: async (pid, o) => { seen.push({ pid, reserve: o && o.reserveBytes }); return { ok: true }; },
      netState: async () => ({ isConnected: true, isInternetReachable: true, details: {} }),
    };
    const r = await M.prefetchAssignedProjects(opts);
    ok(r.ok === true && r.projects.length === 3, 'every assigned project is walked');
    ok(seen[0].pid === 'P3',
      'and the one he opened most recently goes first, so an interrupted phone '
      + 'holds the useful half');
    ok(seen.every((x) => x.reserve === 1024 * 1024 * 1024),
      'each project is filled against the PHONE reserve — a phone that fills its '
      + 'last 200 MB with plans is a broken phone');

    // One failure must not end the walk.
    const seen2 = [];
    const r2 = await M.prefetchAssignedProjects({
      ...opts,
      run: async (pid) => {
        seen2.push(pid);
        if (pid === 'P3') throw new Error('boom');
        return { ok: true };
      },
    });
    ok(seen2.length === 3 && r2.ok === true,
      'one project failing does not end the walk — the next may be the one he needs');
    ok(r2.projects.find((p) => p.projectId === 'P3').ok === false,
      'and the failure is reported rather than swallowed into a success');

    // Metered and offline refuse before listing anything.
    const cellOpts = {
      ...opts,
      netState: async () => ({ isConnected: true, isInternetReachable: true, details: { isConnectionExpensive: true } }),
      listProjects: async () => { throw new Error('should not be called'); },
    };
    const r3 = await M.prefetchAssignedProjects(cellOpts);
    ok(r3.ok === false && r3.reason === 'metered',
      'a metered connection refuses BEFORE fetching a project list');

    const r4 = await M.prefetchAssignedProjects({
      ...opts,
      listProjects: async () => { throw new Error('offline'); },
    });
    ok(r4.ok === false && r4.reason === 'no-project-list',
      'no project list is not a fault — the next foreground tries again');
  }

  // ══ 5. TRIGGERS: foreground, reconnect, login. NO INTERVAL. ════════════
  {
    const src = fs.readFileSync(path.join(HERE, 'adminPlanPrefetch.js'), 'utf8');
    const code = src.split('\n').filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('//')).join('\n');
    ok(!/setInterval/.test(code),
      'NO INTERVAL — a timer fires only while the app is already foregrounded, '
      + 'which the foreground trigger covers, and otherwise spends battery');

    const d = makeDevice({});
    const M = load(d, 'adminPlanPrefetch.js');
    let runs = 0;
    let on = true;
    const stop = M.setupAdminPlanPrefetch(() => on, { run: async () => { runs += 1; } });
    await new Promise((r) => setTimeout(r, 0));
    ok(runs === 1, 'it fires once on setup — that is login');

    d.listeners.net.forEach((fn) => fn({ isConnected: false, isInternetReachable: false }));
    d.listeners.net.forEach((fn) => fn({ isConnected: true, isInternetReachable: true }));
    await new Promise((r) => setTimeout(r, 0));
    ok(runs === 2, 'and on regaining connectivity');

    d.listeners.app.forEach((fn) => fn('background'));
    d.listeners.app.forEach((fn) => fn('active'));
    await new Promise((r) => setTimeout(r, 0));
    ok(runs === 3, 'and on foreground');

    on = false;
    d.listeners.app.forEach((fn) => fn('background'));
    d.listeners.app.forEach((fn) => fn('active'));
    await new Promise((r) => setTimeout(r, 0));
    ok(runs === 3,
      'a signed-out user stops the walk — `enabled` is read at FIRE time, not '
      + 'captured, so a sign-out stops one already scheduled');

    stop();
    ok(d.listeners.net.length === 0 && d.listeners.app.length === 0,
      'and teardown really removes both listeners');
  }

  // ══ 6. THE AGGREGATE, so the day this stops being small is seen coming ══
  {
    const M = load(makeDevice({}), 'adminPlanPrefetch.js');
    const agg = await M.aggregateBytes(['P1', 'P2'], {
      fetchManifest: async (pid) => ({
        complete: true,
        files: { rows: pid === 'P1' ? [{ s: 100 }, { s: 200 }] : [] },
      }),
    });
    ok(agg.total === 300, 'the aggregate sums what the manifest already carries');
    ok(agg.projects.length === 2 && agg.projects[1].bytes === 0,
      'a project with no files reports zero rather than being omitted');
    const bad = await M.aggregateBytes(['P1'], {
      fetchManifest: async () => { throw new Error('offline'); },
    });
    ok(bad.projects[0].bytes === null,
      'and a project it could not measure reports null, never a fabricated zero');
  }

  console.log(`\n  ${passed} passed, ${failed} failed\n`);
  process.exit(failed ? 1 : 0);
})();
