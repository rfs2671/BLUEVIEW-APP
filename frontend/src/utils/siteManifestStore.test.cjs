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

  return {
    disk,
    store,
    downloaded,
    listeners,
    readList: (scope) => {
      const raw = store[`bv_doclist:${scope}`];
      return raw ? JSON.parse(raw) : null;
    },
    AsyncStorage: {
      getAllKeys: async () => Object.keys(store),
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
      removeItem: async (k) => { delete store[k]; },
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
    const row = (d.readList('site_manifest_files:P1') || [])[0];
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
    const stored = d.readList('site_manifest_logs:P1') || [];
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
    ok((d.readList('site_manifest_logs:P1') || []).length === 1,
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
    const stored = d.readList('site_manifest_files:P1') || [];
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

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
