/**
 * AN INCOMPLETE MANIFEST CANNOT TAKE A FILE OFF THE TABLET.
 *
 * THE MACHINE. A fixed Android tablet is bolted to the gate. It polls
 * GET /api/projects/{id}/manifest, which names every record the project has
 * approved it to hold, downloads what is missing or version-changed, and drops
 * what the manifest no longer names. That last clause is the dangerous one:
 * "drop what is not named" is only safe if the manifest is the WHOLE set.
 *
 * IT IS NOT ALWAYS THE WHOLE SET. The read this replaces for logbooks ended in
 * `.to_list(500)` — a silent ceiling with nothing in the response to say it had
 * been hit. Pointed at a diff-and-delete client, a truncated manifest is a
 * cache shredder: every logbook past the cap reads as withdrawn and the tablet
 * deletes the compliance record a DOB inspector asks for, offline, where it
 * cannot be fetched back. The server now pages and declares `complete`; this
 * file is the client half of that contract.
 *
 * THE GUARANTEE IS WRITTEN TWICE, ON PURPOSE, AND THE SECOND HALF IS THE ONE
 * THAT IS EASY TO MISS.
 *
 *   1. an incomplete assembly never calls sweepDocCache; and
 *   2. an incomplete assembly never SHRINKS the stored list either.
 *
 * (2) is not belt-and-braces. sweepDocCache's keep-set is the union of EVERY
 * cached list, and other screens call it — the plans screen sweeps on every
 * successful list load. So a shrunken list is a loaded gun: this module would
 * not fire it, and the next time somebody opened Plans, that screen would.
 * Declining to sweep while quietly dropping ids from the list would look
 * correct in review and delete the records anyway.
 *
 * DELETION GOES THROUGH THE UNION KEEP-SET, NEVER BY ID. The documents
 * directory is FLAT and shared by every project and every surface: names are
 * {fileId}.{cache_version}.{ext} with no project prefix. Deleting by id from
 * this module would destroy another project's plans. There is a prior incident
 * of exactly this shape — a keep-set built by reading `f.id` off each element
 * came back empty for the site logbooks list, and opening Plans deleted the
 * super's offline logbooks. So the real docCache is loaded here, not a mock of
 * it, and the cross-surface survival is asserted directly.
 *
 * Run:  node src/utils/siteManifestStore.test.cjs
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

// ── a fake device: AsyncStorage + FileSystem + network, all controllable ────
function makeDevice(opts) {
  const o = opts || {};
  const store = {};
  for (const scope of Object.keys(o.lists || {})) {
    store[`bv_doclist:${scope}`] = JSON.stringify(o.lists[scope]);
  }
  const disk = new Set(o.files || []);
  const downloaded = [];
  const listeners = { net: [], app: [] };

  // ── FAULT INJECTION, because the interesting states of a chunked write are
  //    the ones a happy path never reaches.
  //
  //   `failSetItemAfter: n`  — the (n+1)th setItem onwards throws, the way
  //     AsyncStorage rejects once the 6 MB database ceiling is hit. It THROWS
  //     rather than truncating because that is what the library actually does:
  //     multiSet catches the SQLiteException and hands the JS layer an error,
  //     which AsyncStorage.setItem turns into a rejected promise. There is no
  //     silent-truncation mode to simulate.
  //
  //   `failRemoveItem: true` — every removeItem throws, which is how a rollback
  //     or a cleanup gets INTERRUPTED. The half-done state it leaves behind is
  //     the state these tests care about most.
  const io = { sets: 0, removes: 0 };
  const setFails = () =>
    o.failSetItemAfter !== undefined && io.sets > o.failSetItemAfter;

  return {
    disk,
    store,
    downloaded,
    listeners,
    io,
    readList: (scope) => {
      const raw = store[`bv_doclist:${scope}`];
      return raw ? JSON.parse(raw) : null;
    },
    // Every stored list key, so a test can assert that superseded chunks were
    // actually reclaimed rather than merely ignored.
    listKeys: () => Object.keys(store).filter((k) => k.startsWith('bv_doclist:')),
    // Flip a fault on partway through a test, so a device can be healthy for
    // the setup write and broken for the one under test.
    setFailRemove: (v) => { o.failRemoveItem = v; },
    setFailSetAfter: (n) => { o.failSetItemAfter = n; io.sets = 0; },
    AsyncStorage: {
      getAllKeys: async () => Object.keys(store),
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => {
        io.sets += 1;
        if (setFails()) throw new Error('database or disk is full (code 13)');
        store[k] = v;
      },
      removeItem: async (k) => {
        io.removes += 1;
        if (o.failRemoveItem) throw new Error('database or disk is full (code 13)');
        delete store[k];
      },
    },
    FileSystem: {
      documentDirectory: '/doc/',
      readDirectoryAsync: async () => [...disk],
      deleteAsync: async (uri) => { disk.delete(uri.split('/').pop()); },
      getInfoAsync: async (uri) => {
        const name = uri.split('/').pop();
        if (name === 'documents') return { exists: true, isDirectory: true };
        return disk.has(name) ? { exists: true, size: 10 } : { exists: false, size: 0 };
      },
      makeDirectoryAsync: async () => {},
      getFreeDiskStorageAsync: async () => (o.freeBytes === undefined ? 1e10 : o.freeBytes),
      downloadAsync: async (url, dest) => {
        const name = dest.split('/').pop();
        // The downloader writes to a .part path and renames on success, so the
        // name recorded here is the file the run is PULLING, not the temp path
        // it lands in first. Nothing is hidden by stripping it: the promotion
        // itself is asserted through `disk`, which only ever holds the final
        // name if moveAsync actually ran.
        downloaded.push({ url, name: name.replace(/\.part$/, '') });
        if (o.failDownload) return { status: 500, uri: null };
        disk.add(name);
        return { status: 200, uri: dest };
      },
      // REAL expo-file-system/legacy HAS moveAsync. A double that omits it does
      // not test a downloader that renames — it makes one look broken.
      moveAsync: async ({ from, to }) => {
        const src = from.split('/').pop();
        const dst = to.split('/').pop();
        if (!disk.has(src)) throw new Error('ENOENT: ' + src);
        disk.delete(src);
        disk.add(dst);
      },
    },
    // Unsubscribing REALLY removes the listener — a fake whose remover is a
    // no-op would let a teardown test pass against a module that never tore
    // anything down.
    NetInfo: {
      addEventListener: (fn) => {
        listeners.net.push(fn);
        return () => { listeners.net = listeners.net.filter((x) => x !== fn); };
      },
      fetch: async () => ({ isConnected: true, isInternetReachable: true }),
    },
    AppState: {
      currentState: 'active',
      addEventListener: (_type, fn) => {
        listeners.app.push(fn);
        return { remove: () => { listeners.app = listeners.app.filter((x) => x !== fn); } };
      },
    },
    // `pages` is an array of responses served in order; a `null` entry is a
    // network failure mid-walk.
    apiClient: {
      defaults: { baseURL: 'https://api.test' },
      get: async (url) => {
        const page = (o.pages || []).shift();
        if (page === null || page === undefined) {
          const e = new Error('Network Error');
          e.request = {};
          throw e;
        }
        return { data: page, __url: url };
      },
    },
  };
}

// ── module loader: the REAL docCache, so the union sweep is genuinely run ───
const HERE = __dirname;
const compiled = {};
function compile(file) {
  if (!compiled[file]) {
    const full = path.join(HERE, file);
    // A MISSING MODULE MUST NOT BE A STACK TRACE. Against a tree without the
    // store, an ENOENT here would replace every named guarantee below with one
    // opaque error — which is the reporting failure this harness exists to
    // avoid. Compile to an empty module and let the export check name them.
    if (!fs.existsSync(full)) { compiled[file] = ''; return compiled[file]; }
    compiled[file] = babel.transformSync(fs.readFileSync(full, 'utf8'), {
      filename: full,
      plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
      configFile: false,
      babelrc: false,
    }).code;
  }
  return compiled[file];
}

function load(device, file) {
  const cache = device.__modcache || (device.__modcache = {});
  if (cache[file]) return cache[file];
  const m = {};
  cache[file] = m;
  const shim = (spec) => {
    if (spec === '@react-native-async-storage/async-storage') {
      return { __esModule: true, default: device.AsyncStorage };
    }
    if (spec === 'expo-file-system/legacy') return device.FileSystem;
    if (spec === 'react-native') {
      return { Platform: { OS: 'android' }, AppState: device.AppState };
    }
    if (spec === '@react-native-community/netinfo') {
      return { __esModule: true, default: device.NetInfo };
    }
    if (spec === './api') {
      return { __esModule: true, default: device.apiClient, getToken: async () => 'jwt' };
    }
    if (spec === './docCache') return load(device, 'docCache.js');
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compile(file))(m, { exports: m }, shim);
  return m;
}
const store = (device) => load(device, 'siteManifestStore.js');

/**
 * What the STORE would hand a caller for a scope — through the module's own
 * reader, never by poking the raw key.
 *
 * Once the list is chunked the scope key holds a COMMIT RECORD, not the rows,
 * so a test that reads the raw key is asserting the storage format instead of
 * the guarantee. Everything below asks the module the same question a screen
 * would. Falls back to the raw key on a tree that has no reader yet, so the
 * pre-existing guarantees keep reporting themselves by name.
 */
async function storedRows(device, scope) {
  const M = store(device);
  if (typeof M.readManifestList === 'function') {
    const r = await M.readManifestList(scope);
    return (r && r.rows) || [];
  }
  return device.readList(scope) || [];
}
async function storedState(device, scope) {
  const M = store(device);
  if (typeof M.readManifestList !== 'function') return 'no-reader';
  const r = await M.readManifestList(scope);
  return (r && r.state) || 'no-state';
}

// ── row builders ───────────────────────────────────────────────────────────
//
// TWO SHAPES, DELIBERATELY NOT ONE. The WIRE row is compact — `{id, v, s, e}`.
// The STORED row must be docCache's — `{id, cache_version}` — because the
// keep-set builder reconstructs the on-disk name from `cache_version` and
// treats a row without one as version 0. A store that wrote the wire shape
// straight through would have the sweep keep `{id}.0.pdf`, a name nothing
// bears, and delete every file it had just downloaded. Keeping the two shapes
// visibly distinct here is what makes that assertable.
const fRow = (id, v, e = 'pdf', s = 100) => ({ id, v, s, e });   // wire
const lRow = (id, v) => ({ id, v });                              // wire
const sRow = (id, cache_version) => ({ id, cache_version });      // stored

function page({ files = [], logbooks = [], filesMore = false, logsMore = false,
                filesSkip = 0, logsSkip = 0, complete } = {}) {
  return {
    project_id: 'P1',
    limit: 1000,
    files: { rows: files, skip: filesSkip, total: files.length, has_more: filesMore },
    logbooks: { rows: logbooks, skip: logsSkip, total: logbooks.length, has_more: logsMore },
    complete: complete === undefined
      ? (!filesMore && !logsMore && filesSkip === 0 && logsSkip === 0)
      : complete,
  };
}

async function main() {
  // NAMED FAILURES, NOT A STACK TRACE. Against a tree without the store, a
  // bare call throws "not a function" and the run reports one opaque error
  // instead of the guarantees that are absent.
  {
    const M = store(makeDevice({}));
    let missing = 0;
    for (const name of ['mergeRows', 'fetchManifest', 'syncSiteManifest',
                        'setupSiteManifestSync', 'manifestScopes']) {
      const present = typeof M[name] === 'function';
      ok(present, `siteManifestStore exports ${name}`);
      if (!present) missing += 1;
    }
    if (missing > 0) {
      console.log(`\n  ${passed} passed, ${failed} failed`);
      console.log('  (stopping: this tree has no site manifest store)');
      process.exit(1);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 1. THE CORE RULE, AS A PURE FUNCTION. mergeRows is the only place the
  //    stored list is allowed to shrink, so it is the only place the
  //    completeness flag has to be honoured.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const M = store(makeDevice({}));
    const prev = [sRow('a', 1), sRow('b', 1), sRow('c', 1)];
    const next = [sRow('a', 1), sRow('b', 2)];

    const whole = M.mergeRows(prev, next, true);
    ok(whole.length === 2 && whole.every((r) => r.id !== 'c'),
      'a COMPLETE manifest replaces the list, so a withdrawn id leaves it');
    ok(whole.find((r) => r.id === 'b').cache_version === 2,
      'and a version change is taken');

    const partial = M.mergeRows(prev, next, false);
    const ids = new Set(partial.map((r) => r.id));
    ok(ids.has('a') && ids.has('b') && ids.has('c'),
      'an INCOMPLETE manifest keeps every id it did not name — the list never '
      + 'shrinks, because another screen may sweep against it at any moment');
    ok(partial.some((r) => r.id === 'b' && r.cache_version === 2)
      && partial.some((r) => r.id === 'b' && r.cache_version === 1),
      'and it keeps BOTH versions of a changed record: the old bytes are still '
      + 'on disk and still the only copy this tablet can open');
  }
  {
    const M = store(makeDevice({}));
    ok(M.mergeRows([sRow('a', 1)], [], false).length === 1,
      'an incomplete manifest with NO rows at all deletes nothing');
    ok(M.mergeRows([sRow('a', 1)], [], true).length === 0,
      'a complete manifest with no rows means the project approved nothing');
  }
  {
    // THE SHAPE THAT WOULD DELETE EVERYTHING IT JUST DOWNLOADED. docCache
    // rebuilds the on-disk name from `cache_version`; a row stored as {id, v}
    // makes it keep `{id}.0.pdf` — a name no file bears — so the next sweep
    // removes the real bytes. Nothing else in this repo would catch it.
    const d = makeDevice({ pages: [page({ files: [fRow('F1', 7)] })] });
    await store(d).syncSiteManifest('P1');
    const row = (await storedRows(d, 'site_manifest_files:P1'))[0];
    ok(row && row.cache_version === 7,
      'the STORED row carries cache_version, the field docCache keys names on');
    ok(d.disk.has('F1.7.pdf'), 'the file was downloaded');
    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has('F1.7.pdf'),
      'and it SURVIVES the next sweep — a wire-shaped row would have had the '
      + 'keep-set name it F1.0.pdf and delete the bytes just downloaded');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 2. THE SAME RULE THROUGH THE REAL SYNC, ON A REAL FAKE DISK.
  //    This is the assertion the stream exists for.
  // ═══════════════════════════════════════════════════════════════════════
  {
    // A truncated first page: has_more true, so `complete` is false. The
    // logbooks named on page 2 are NOT in the assembly, and the walk fails
    // before it can get them.
    const d = makeDevice({
      lists: { 'site_manifest_logs:P1': [sRow('L1', 'v1'), sRow('L2', 'v1')] },
      files: ['L1.v1.pdf', 'L2.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')], logsMore: true }), null],
    });
    const r = await store(d).syncSiteManifest('P1');

    ok(r.complete === false, 'a truncated walk reports incomplete');
    ok(d.disk.has('L2.v1.pdf'),
      'THE LOGBOOK PAST THE CAP IS STILL ON THE TABLET — a truncated manifest '
      + 'cannot delete the compliance record');
    const stored = await storedRows(d, 'site_manifest_logs:P1');
    ok(stored.some((x) => x.id === 'L2'),
      'and the stored list still NAMES it, so a sweep run later from any other '
      + 'screen keeps it too');
    ok(r.swept === false, 'and no sweep was run from here');
  }
  {
    // The same shape, but the sweep is then run by somebody else — the plans
    // screen does exactly this on every successful list load. This is the
    // failure mode that "we simply do not call sweep" would not survive.
    const d = makeDevice({
      lists: { 'site_manifest_logs:P1': [sRow('L1', 'v1'), sRow('L2', 'v1')] },
      files: ['L1.v1.pdf', 'L2.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')], logsMore: true }), null],
    });
    await store(d).syncSiteManifest('P1');
    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has('L2.v1.pdf'),
      'AND IT SURVIVES A FOREIGN SWEEP — the guarantee lives in the stored '
      + 'list, not merely in this module declining to call sweepDocCache');
  }
  {
    // A mid-walk network failure is the same class of incompleteness.
    const d = makeDevice({
      lists: { 'site_manifest_logs:P1': [sRow('L1', 'v1'), sRow('L9', 'v1')] },
      files: ['L1.v1.pdf', 'L9.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')], logsMore: true }), null],
    });
    const r = await store(d).syncSiteManifest('P1');
    ok(r.complete === false && d.disk.has('L9.v1.pdf'),
      'a dropped page mid-walk deletes nothing');
  }
  {
    // And the whole request failing is not an empty approved set.
    const d = makeDevice({
      lists: { 'site_manifest_logs:P1': [sRow('L1', 'v1')] },
      files: ['L1.v1.pdf'],
      pages: [null],
    });
    const r = await store(d).syncSiteManifest('P1');
    ok(r.ok === false && d.disk.has('L1.v1.pdf'),
      'an offline poll is not "the project approved nothing"');
    ok((await storedRows(d, 'site_manifest_logs:P1')).length === 1,
      'and the stored list is untouched');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 3. A COMPLETE MANIFEST DOES REMOVE — through the union keep-set, and
  //    without touching any other project or surface.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      lists: {
        'site_manifest_logs:P1': [sRow('L1', 'v1'), sRow('L2', 'v1')],
        // another project's plans, and another SURFACE's day-report on this
        // one — both live in the same flat directory with no prefix.
        'plans:OTHER': [{ id: 'X1', cache_version: 1 }],
        'site_logbooks:P1': [{ date: '2026-08-01', id: 'day_P1_2026-08-01', cache_version: 'v1', logs: [] }],
      },
      files: ['L1.v1.pdf', 'L2.v1.pdf', 'X1.1.pdf', 'day_P1_2026-08-01.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')] })],
    });
    const r = await store(d).syncSiteManifest('P1');

    ok(r.complete === true && r.swept === true, 'a complete assembly sweeps');
    ok(!d.disk.has('L2.v1.pdf'),
      'the logbook the manifest no longer names is removed');
    ok(d.disk.has('X1.1.pdf'),
      "ANOTHER PROJECT'S PLAN SURVIVES — the keep-set is the union of every "
      + 'cached list, never this one project');
    ok(d.disk.has('day_P1_2026-08-01.v1.pdf'),
      "AND THE SITE LOGBOOKS SCREEN'S FULL-DAY REPORT SURVIVES — that file's "
      + 'name is invented by another surface and named only in its list');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 4. IT ACTUALLY FILLS THE TABLET: missing and version-changed bytes.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      files: ['F2.1.pdf'],
      pages: [page({
        files: [fRow('F1', 1), fRow('F2', 2)],
        logbooks: [lRow('L1', 'v1')],
      })],
    });
    const r = await store(d).syncSiteManifest('P1');
    const names = d.downloaded.map((x) => x.name);
    ok(names.includes('F1.1.pdf'), 'a file that is missing is downloaded');
    ok(names.includes('F2.2.pdf'),
      'a file whose cache_version moved is re-downloaded under the new name');
    ok(!names.includes('F2.1.pdf'), 'and the unchanged copy is not re-fetched');
    ok(names.includes('L1.v1.pdf'), 'a submitted logbook PDF is downloaded');
    ok(r.downloaded === 3, 'the run reports what it pulled');
  }
  {
    const d = makeDevice({
      pages: [page({ files: [fRow('F1', 1, 'pdf'), fRow('F2', 1, 'docx')] })],
    });
    await store(d).syncSiteManifest('P1');
    ok(d.downloaded.length === 1 && d.downloaded[0].name === 'F1.1.pdf',
      'only what the tablet can open offline is pulled — it renders PDFs and '
      + 'nothing else, so a .docx would be bytes nobody can read');
    const stored = await storedRows(d, 'site_manifest_files:P1');
    ok(stored.some((x) => x.id === 'F2'),
      'but the manifest still LISTS it, so the screen can show it exists');
  }
  {
    const d = makeDevice({
      pages: [page({ files: [fRow('F1', 1)] })],
    });
    await store(d).syncSiteManifest('P1');
    const url = d.downloaded[0].url;
    ok(url.includes('/api/projects/P1/files/F1/content'),
      'the file url is composed from the id the manifest gave');
    ok(!/token=/.test(url),
      'and carries no token — the JWT rides in the Authorization header');
  }
  {
    const d = makeDevice({ pages: [page({ logbooks: [lRow('L1', 'v1')] })] });
    await store(d).syncSiteManifest('P1');
    ok(d.downloaded[0].url.includes('/api/reports/logbook/L1/pdf'),
      'the logbook url is the report route');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 5. THE PAGE WALK
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      pages: [
        page({ logbooks: [lRow('L1', 'v1')], logsMore: true }),
        page({ logbooks: [lRow('L2', 'v1')], logsSkip: 1, complete: false }),
      ],
    });
    const m = await store(d).fetchManifest('P1', { limit: 1 });
    ok(m.logbooks.length === 2, 'every page is assembled');
    ok(m.complete === true,
      'a walk that reached the end IS complete, even though no single page '
      + 'said so — page 2 of 2 is a fragment on its own');
  }
  {
    const d = makeDevice({
      pages: Array.from({ length: 40 }, () =>
        page({ logbooks: [lRow('x', 'v1')], logsMore: true })),
    });
    const m = await store(d).fetchManifest('P1', { limit: 1, maxPages: 5 });
    ok(m.complete === false,
      'a server that never says has_more:false is a bug, and the walk stops '
      + 'and reports incomplete rather than looping for ever');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 6. DISK. `s` is on the row so the run can refuse BEFORE it starts,
  //    rather than dying on file 9 with a half-filled tablet.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      freeBytes: 500,
      pages: [page({ files: [fRow('F1', 1, 'pdf', 1e9)] })],
    });
    const r = await store(d).syncSiteManifest('P1');
    ok(d.downloaded.length === 0 && r.reason === 'no-space',
      'a run that cannot fit refuses up front and says why — rather than dying '
      + 'on file 9 with a half-filled tablet and no way to know which half');
    ok(r.swept === true,
      'but the sweep still ran, and ran BEFORE the budget was measured: '
      + 'reclaiming orphans is the only way a full tablet ever gets space '
      + 'back, and the sweep can only ever remove what no list names');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 7. TRIGGERS. Foreground and reconnect, and nothing that needs a
  //    background-execution dependency: the tablet is mains-powered and
  //    permanently foregrounded.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ pages: [page({}), page({}), page({}), page({})] });
    const M = store(d);
    let runs = 0;
    const stop = M.setupSiteManifestSync(() => 'P1', {
      intervalMs: 0,
      run: async () => { runs += 1; },
    });
    ok(runs === 1, 'it syncs once at startup — a tablet cold-booted with the '
      + 'network already up must fill itself with nobody touching it');

    d.listeners.net.forEach((fn) => fn({ isConnected: false, isInternetReachable: false }));
    d.listeners.net.forEach((fn) => fn({ isConnected: true, isInternetReachable: true }));
    ok(runs === 2, 'and again on a NetInfo reconnect');

    d.listeners.app.forEach((fn) => fn('background'));
    d.listeners.app.forEach((fn) => fn('active'));
    ok(runs === 3, 'and again on foreground');

    ok(typeof stop === 'function', 'setup returns a teardown');
    stop();
    d.listeners.net.forEach((fn) => fn({ isConnected: false }));
    d.listeners.net.forEach((fn) => fn({ isConnected: true, isInternetReachable: true }));
    ok(runs === 3, 'and teardown actually stops it');
  }
  {
    const d = makeDevice({ pages: [page({})] });
    const M = store(d);
    let runs = 0;
    const stop = M.setupSiteManifestSync(() => null, {
      intervalMs: 0,
      run: async () => { runs += 1; },
    });
    ok(runs === 0, 'no project, no sync — this is a site-device surface only');
    stop();
  }
  {
    // Two triggers can land together (reconnect on foreground). A second run
    // on top of the first would double every download.
    const d = makeDevice({ pages: [page({}), page({})] });
    const M = store(d);
    const first = M.syncSiteManifest('P1');
    const second = await M.syncSiteManifest('P1');
    await first;
    ok(second.reason === 'busy', 'overlapping runs collapse to one');
  }
  {
    const src = fs.readFileSync(path.join(HERE, 'siteManifestStore.js'), 'utf8');
    // An IMPORT, not a mention — the header explains at length why this module
    // does not reach for one, and a bare substring match would fail on the
    // explanation itself.
    ok(!/(from|require\()\s*['"](expo-task-manager|expo-background[\w-]*)['"]/.test(src),
      'NO BACKGROUND-EXECUTION DEPENDENCY. The tablet is mains-powered and '
      + 'permanently foregrounded; a background task would be a new native '
      + 'dependency, a new rebuild and a new failure mode for nothing');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 8. AND SOMETHING ACTUALLY MOUNTS IT.
  //
  //    Every guarantee above is worth nothing if no screen ever starts the
  //    poll. A util with no caller is the failure this repo has shipped
  //    before — a keep-set that returned empty, a limiter nobody reset — so
  //    the wiring is asserted rather than assumed.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const layout = fs.readFileSync(
      path.join(HERE, '..', '..', 'app', '_layout.jsx'), 'utf8');
    ok(/setupSiteManifestSync/.test(layout)
      && /from '\.\.\/src\/utils\/siteManifestStore'/.test(layout),
      'the root layout imports the store');
    ok(/<SiteManifestSync\s*\/>/.test(layout),
      'and renders it, inside AuthProvider where siteProject is readable');
    ok(/siteMode\s*&&\s*siteProject\?\.id/.test(layout),
      'gated on the site device — the manifest is not a CP phone’s business');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 9. A HALF-WRITTEN MANIFEST MUST NOT READ AS A COMPLETE SHORT ONE.
  //
  //    The list is written as indexed CHUNKS plus a single final COMMIT that
  //    names the chunk count and a generation id. That makes three states, not
  //    two, and the reader has to tell them apart:
  //
  //      COMPLETE — a commit exists and every chunk it names is present.
  //      ABSENT   — nothing is stored for this scope at all.
  //      PARTIAL  — chunk keys exist that no commit names, or a commit names
  //                 chunks that are not all there.
  //
  //    PARTIAL is the one that matters. Returning the chunks that happen to be
  //    present would hand the caller a SHORT list that looks complete, and a
  //    short list is not a display bug here: sweepDocCache's keep-set is the
  //    union of every cached list and OTHER SCREENS CALL IT. The plans screen
  //    sweeps on every successful list load. A short list is a loaded gun this
  //    module would not fire and the next person to open Plans would — which
  //    is the same failure the incomplete-FETCH rule above exists to prevent,
  //    reached through a half-finished WRITE instead of a truncated read.
  //
  //    So PARTIAL is reported as its own state and is treated exactly like
  //    ABSENT everywhere a decision is made: it can never authorise a shrink.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const M = store(makeDevice({}));
    for (const name of ['readManifestList', 'writeManifestList', 'manifestChunkKey']) {
      ok(typeof M[name] === 'function', `siteManifestStore exports ${name}`);
    }
  }

  const CHUNKED = typeof store(makeDevice({})).writeManifestList === 'function';
  // Every guarantee below is emitted BY NAME whether or not the code exists,
  // so a tree without the chunked store reports what is MISSING rather than
  // one opaque stack trace — and `okc` makes each of them require that code,
  // so none can pass vacuously on a tree where the setup never ran.
  const okc = (cond, label) => ok(CHUNKED && !!cond, label);

  {
    // ── round trip across many chunks ──────────────────────────────────
    const d = makeDevice({});
    const M = store(d);
    const rows = Array.from({ length: 1300 }, (_, i) => sRow(`R${i}`, 'v1'));
    const w = CHUNKED ? await M.writeManifestList('site_manifest_logs:P1', rows) : {};
    okc(w.ok === true, 'a list larger than one chunk writes');
    okc(w.chunks > 1, 'and is actually split — a single key would be the thing '
      + 'this change exists to stop');
    const back = CHUNKED ? await M.readManifestList('site_manifest_logs:P1') : {};
    okc(back.state === 'complete', 'and reads back COMPLETE');
    okc((back.rows || []).length === 1300,
      'with every row, in order, across the chunk boundaries');
    okc((back.rows || []).map((r) => r.id).join() === rows.map((r) => r.id).join(),
      'and identical row-for-row');
  }
  {
    // ── the commit is the LAST write, and it names the generation ──────
    const d = makeDevice({ failSetItemAfter: 2 });
    const M = store(d);
    const rows = Array.from({ length: 1300 }, (_, i) => sRow(`R${i}`, 'v1'));
    const w = CHUNKED ? await M.writeManifestList('site_manifest_logs:P1', rows) : { ok: true };
    okc(w.ok === false,
      'a write that cannot finish its chunks REPORTS failure rather than '
      + 'committing what it managed');
    const raw = d.readList('site_manifest_logs:P1');
    okc(raw === null,
      'AND NO COMMIT RECORD WAS WRITTEN. The commit is the last write, so a '
      + 'run that dies among the chunks leaves nothing claiming to be a list');
  }
  {
    // ══ THE REQUIRED TEST ═══════════════════════════════════════════════
    // A chunk write is interrupted partway — the process dies before the
    // commit, and the rollback does not get to run either (removeItem throws,
    // which is what a full database or a power cut looks like). The chunks of
    // a generation nothing names are on the device. The next read must call
    // that ABSENT, and nothing may shrink.
    const d = makeDevice({
      files: ['L1.v1.pdf', 'L2.v1.pdf', 'L3.v1.pdf'],
      failSetItemAfter: 2,
      failRemoveItem: true,
    });
    const M = store(d);
    const rows = [sRow('L1', 'v1'), sRow('L2', 'v1'), sRow('L3', 'v1')];
    if (CHUNKED) await M.writeManifestList('site_manifest_logs:P1', rows, { chunkRows: 1 });

    const chunkKeys = d.listKeys().filter((k) => k.includes('#g'));
    okc(chunkKeys.length > 0 && chunkKeys.length < 3,
      'the interrupted write really did leave SOME chunks and not all of them '
      + '— otherwise the state under test was never reached');

    const r = CHUNKED ? await M.readManifestList('site_manifest_logs:P1') : {};
    okc(r.state === 'absent' || r.state === 'partial',
      'THE NEXT READ REPORTS ABSENT. Chunks that no commit names are not a '
      + 'list; a reader that returned them would be handing back a complete-'
      + 'looking SHORT list');
    okc(r.state !== 'complete',
      'and above all it is NOT reported complete — that is the whole point');
    okc((r.rows || []).length === 0,
      'and it yields no rows, so nothing downstream can mistake a fragment '
      + 'for the approved set');
    okc(d.disk.size === 3,
      'AND IT SHRANK NOTHING — every file that was on the tablet is still on '
      + 'the tablet');
  }
  {
    // ══ THE SECOND REQUIRED TEST ════════════════════════════════════════
    // The same interrupted write, and then a FOREIGN sweep — the plans screen
    // does exactly this on every successful list load. This is the assertion
    // that "the reader declines to return the fragment" would NOT survive:
    // the sweep does not consult the reader at all, it walks the raw
    // bv_doclist keys. So the chunks have to be stored as PLAIN ROW ARRAYS
    // under that prefix, which puts every id they hold into the union keep-set
    // whether or not any commit names them.
    //
    // The tablet holds what a first fill would actually have got as far as
    // downloading — the records the chunks that landed name — plus another
    // surface's file, so the sweep has a real keep-set to work from and is not
    // declining merely because it could not look.
    const d = makeDevice({
      lists: { 'plans:OTHER': [{ id: 'X1', cache_version: 1 }] },
      files: ['L1.v1.pdf', 'L2.v1.pdf', 'X1.1.pdf'],
      failSetItemAfter: 2,
      failRemoveItem: true,
    });
    const M = store(d);
    const rows = [sRow('L1', 'v1'), sRow('L2', 'v1'), sRow('L3', 'v1')];
    if (CHUNKED) await M.writeManifestList('site_manifest_logs:P1', rows, { chunkRows: 1 });

    const before = d.disk.size;
    const res = await load(d, 'docCache.js').sweepDocCache();
    okc(res && res.skipped !== true,
      'the sweep really ran — a sweep that declined to look would prove '
      + 'nothing about the keep-set');
    okc(d.disk.size === before,
      'A FOREIGN SWEEP AFTER AN INTERRUPTED WRITE DELETES NO BYTES — the '
      + 'orphaned chunks still name their ids in the union keep-set, so the '
      + 'plans screen cannot shred what a half-finished write left behind');
    okc(res.deleted && res.deleted.length === 0,
      'and it reports having deleted nothing, rather than deleting quietly');
    okc(d.disk.has('L1.v1.pdf') && d.disk.has('L2.v1.pdf'),
      'specifically the records the ORPHANED chunks name are kept, though no '
      + 'commit names those chunks and the reader calls the scope absent');
  }
  {
    // The same interruption, but on a tablet that already had a COMMITTED
    // generation. Here the guarantee is stronger than "absent": the commit
    // never moved, so the whole previous list is still what a reader gets and
    // what the sweep unions — a half-written manifest cannot displace a whole
    // one, let alone shrink it.
    const d = makeDevice({ files: ['L1.v1.pdf', 'L2.v1.pdf', 'L3.v1.pdf'] });
    const M = store(d);
    const rows = [sRow('L1', 'v1'), sRow('L2', 'v1'), sRow('L3', 'v1')];
    if (CHUNKED) await M.writeManifestList('site_manifest_logs:P1', rows, { chunkRows: 1 });
    okc((await storedRows(d, 'site_manifest_logs:P1')).length === 3, 'setup: three rows committed');

    // Now a SHORTER write that dies among its chunks and cannot roll back —
    // the shape that would be most damaging if the commit were not the last
    // write, because the list it is trying to install is smaller.
    const before = d.disk.size;
    d.setFailRemove(true);
    d.setFailSetAfter(1);
    if (CHUNKED) {
      await M.writeManifestList('site_manifest_logs:P1',
        [sRow('L1', 'v1'), sRow('L2', 'v1')], { chunkRows: 1 });
    }
    d.setFailSetAfter(undefined);
    okc((await storedRows(d, 'site_manifest_logs:P1')).length === 3,
      'THE PREVIOUS GENERATION IS STILL WHAT THE READER RETURNS, whole — the '
      + 'commit is one write and it never happened, so nothing switched over');
    await load(d, 'docCache.js').sweepDocCache();
    okc(d.disk.size === before,
      'and a foreign sweep on top of that still deletes nothing');
  }
  {
    // A commit that names more chunks than are present. This is the shape a
    // reader gets wrong by counting rows instead of checking the generation:
    // two chunks of a four-chunk manifest parse perfectly and look like a
    // complete short list.
    const d = makeDevice({});
    const M = store(d);
    const rows = Array.from({ length: 8 }, (_, i) => sRow(`R${i}`, 'v1'));
    if (CHUNKED) await M.writeManifestList('site_manifest_logs:P1', rows, { chunkRows: 2 });
    // amputate the last chunk, exactly as a partial write or an eviction would
    const keys = d.listKeys().filter((k) => k.includes('#g'));
    delete d.store[keys[keys.length - 1]];

    const r = CHUNKED ? await M.readManifestList('site_manifest_logs:P1') : {};
    okc(r.state !== 'complete',
      'a manifest whose chunks do not ALL match the committed generation is '
      + 'not complete — it is absent');
    okc((r.rows || []).length === 0,
      'and specifically it is not "complete and short", which is the state '
      + 'that would let a foreign sweep delete the missing chunk’s records');
  }
  {
    // Generations must not be able to blend. If chunk keys were reused across
    // writes, a half-finished SHORT write over a long one would leave chunk 0
    // and 1 new and chunk 2 old — and the reader would assemble a list that
    // never existed.
    const d = makeDevice({});
    const M = store(d);
    if (CHUNKED) {
      await M.writeManifestList('site_manifest_logs:P1',
        Array.from({ length: 6 }, (_, i) => sRow(`OLD${i}`, 'v1')), { chunkRows: 2 });
    }
    const genOne = d.listKeys().filter((k) => k.includes('#g'));
    if (CHUNKED) {
      await M.writeManifestList('site_manifest_logs:P1',
        Array.from({ length: 4 }, (_, i) => sRow(`NEW${i}`, 'v1')), { chunkRows: 2 });
    }
    const genTwo = d.listKeys().filter((k) => k.includes('#g'));
    okc(genOne.length > 0 && genTwo.length > 0
      && genOne.every((k) => !genTwo.includes(k)),
      'a second write uses ENTIRELY NEW chunk keys — a generation is stamped '
      + 'into the key, so no chunk of one write can ever be read as part of '
      + 'another');
    const r = CHUNKED ? await M.readManifestList('site_manifest_logs:P1') : {};
    okc((r.rows || []).every((x) => x.id.startsWith('NEW')),
      'and the read returns the new generation only, never a blend');
  }
  {
    // Superseded chunks are reclaimed. They are not merely ignored: the
    // AsyncStorage ceiling is DATABASE-WIDE, so every generation left behind
    // is spent against the same 6 MB every other key is drawing on.
    const d = makeDevice({});
    const M = store(d);
    for (let i = 0; i < 4; i += 1) {
      if (CHUNKED) {
        await M.writeManifestList('site_manifest_logs:P1',
          Array.from({ length: 6 }, (_, k) => sRow(`R${i}_${k}`, 'v1')), { chunkRows: 2 });
      }
    }
    const chunks = d.listKeys().filter((k) => k.includes('#g'));
    okc(chunks.length === 3,
      'after four writes only the LAST generation’s chunks remain — a '
      + 'superseded generation is reclaimed, not left to accumulate against a '
      + 'database-wide ceiling');
    okc((await storedRows(d, 'site_manifest_logs:P1')).length === 6,
      'and the surviving generation still reads complete');
  }
  {
    // Cleanup must be safe to interrupt. removeItem throws throughout, so the
    // purge of the superseded generation gets nowhere — and the new list must
    // still read complete, with the stale chunks harmless.
    const d = makeDevice({});
    const M = store(d);
    if (CHUNKED) {
      await M.writeManifestList('site_manifest_logs:P1',
        Array.from({ length: 6 }, (_, k) => sRow(`OLD${k}`, 'v1')), { chunkRows: 2 });
    }
    d.setFailRemove(true);   // the device goes bad AFTER the setup write
    const w = CHUNKED ? await M.writeManifestList('site_manifest_logs:P1',
      Array.from({ length: 4 }, (_, k) => sRow(`NEW${k}`, 'v1')), { chunkRows: 2 }) : {};
    okc(w.ok === true,
      'A CLEANUP THAT CANNOT DELETE DOES NOT FAIL THE WRITE — reclaiming a '
      + 'superseded generation is housekeeping, and housekeeping must never '
      + 'be able to lose a manifest that was written correctly');
    const r = CHUNKED ? await M.readManifestList('site_manifest_logs:P1') : {};
    okc(r.state === 'complete' && (r.rows || []).length === 4,
      'and the committed generation reads complete with the stale chunks '
      + 'still on the device — they are ignored by generation, not by luck');
  }
  {
    // A tablet upgraded into this build has a flat, unchunked list already
    // stored. It must keep reading as what it is: a complete list.
    const d = makeDevice({
      lists: { 'site_manifest_logs:P1': [sRow('L1', 'v1'), sRow('L2', 'v1')] },
      files: ['L1.v1.pdf', 'L2.v1.pdf'],
    });
    const r = CHUNKED ? await store(d).readManifestList('site_manifest_logs:P1') : {};
    okc(r.state === 'complete' && (r.rows || []).length === 2,
      'A LIST WRITTEN BY THE PREVIOUS BUILD STILL READS COMPLETE — an upgrade '
      + 'that read it as absent would refuse to union against it, and the '
      + 'first incomplete poll after the upgrade would report a shrink');
  }
  {
    // ── the discipline extended to partial WRITES, through the real sync ──
    //
    // The store already refuses to shrink on an incomplete FETCH. The same
    // refusal has to hold when the PREVIOUS STORED LIST is the thing that is
    // untrustworthy: unioning against a list that reads absent because it was
    // half-written silently drops every id in the chunks that are missing.
    const d = makeDevice({
      files: ['L1.v1.pdf', 'L2.v1.pdf', 'L3.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')], logsMore: true }), null],
    });
    const M = store(d);
    // leave a half-written generation behind: chunks, no commit
    if (CHUNKED) {
      const g = 'orphan';
      await d.AsyncStorage.setItem(
        `bv_doclist:${M.manifestChunkKey('site_manifest_logs:P1', g, 0)}`,
        JSON.stringify([sRow('L2', 'v1'), sRow('L3', 'v1')]));
    }
    const before = d.disk.size;
    const r = await M.syncSiteManifest('P1');
    okc(r.complete === false, 'the poll is incomplete, as set up');
    okc(d.disk.size === before,
      'AN INCOMPLETE POLL ON TOP OF A HALF-WRITTEN LIST REMOVES NOTHING');
    okc(r.swept === false, 'and does not sweep');
    await load(d, 'docCache.js').sweepDocCache();
    okc(d.disk.has('L2.v1.pdf') && d.disk.has('L3.v1.pdf'),
      'AND A FOREIGN SWEEP AFTERWARDS STILL FINDS THEM NAMED — the union it '
      + 'walks includes the orphaned chunks, and the sync did not overwrite '
      + 'the scope with a union computed against an empty prev');
  }
  {
    // The complementary case: a COMPLETE poll is the whole truth, so it is
    // allowed to replace even a half-written prior generation. Nothing about
    // partial-write safety may block the tablet from ever converging.
    const d = makeDevice({
      files: ['L1.v1.pdf', 'L2.v1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')] })],
    });
    const M = store(d);
    if (CHUNKED) {
      await d.AsyncStorage.setItem(
        `bv_doclist:${M.manifestChunkKey('site_manifest_logs:P1', 'orphan', 0)}`,
        JSON.stringify([sRow('L2', 'v1')]));
    }
    const r = await M.syncSiteManifest('P1');
    okc(r.complete === true && r.swept === true,
      'a COMPLETE poll still sweeps, even over a half-written generation — '
      + 'the refusal to shrink must not become a refusal to ever converge');
    okc((await storedRows(d, 'site_manifest_logs:P1')).map((x) => x.id).join() === 'L1',
      'and the stored list is the manifest, with the orphan generation gone');
    okc(!d.disk.has('L2.v1.pdf'),
      'so the withdrawn record is finally removed');
  }
  {
    // A commit that fails must not be followed by a sweep. The old generation
    // is still the committed one, so its keep-set is the OLD list — sweeping
    // against it would delete files the new complete manifest still names.
    const d = makeDevice({
      lists: { 'plans:OTHER': [{ id: 'X1', cache_version: 1 }] },
      files: ['X1.1.pdf'],
      pages: [page({ logbooks: [lRow('L1', 'v1')] })],
      failSetItemAfter: 0,
    });
    const r = await store(d).syncSiteManifest('P1');
    okc(r.swept === false,
      'A RUN WHOSE COMMIT FAILED DOES NOT SWEEP — the keep-set on the device '
      + 'is no longer the one this run computed, and deleting against a list '
      + 'you did not manage to write is deleting against a guess');
    okc(d.disk.has('X1.1.pdf'), 'and another surface’s file is untouched');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
