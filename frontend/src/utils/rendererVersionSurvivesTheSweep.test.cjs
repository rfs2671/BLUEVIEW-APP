/**
 * A RENDERER VERSION IN THE FILENAME MUST NOT DELETE THE TABLET'S RECORDS.
 *
 * The legal PDF is cached in two places keyed on the RECORD alone, so a
 * restyle would be invisible on both: a filed log never changes, so its
 * timestamp never moves. Folding the renderer's version into the name fixes
 * that, and introduces a far worse failure if it is done carelessly.
 *
 * THE FAILURE THIS FILE EXISTS FOR. docCache's sweep deletes any file in the
 * flat shared directory whose name is not in a keep-set built from the stored
 * lists. The site manifest's stored row is COMPACT -- `{id, cache_version}`,
 * built from the wire's `v` -- and carries none of the timestamp fields. So a
 * server that changed `v` in place would hand an OLD client, which still names
 * its files from the timestamp because OTA and Railway cannot land together, a
 * keep-set naming a file that does not exist while every file that does exist
 * is missing from it. The next sweep from ANY screen deletes the lot.
 *
 * That is not hypothetical. siteManifestStore records it happening: the
 * keep-set came back empty for logbooks, the files on disk matched the
 * sweepable pattern exactly, and opening the Plans screen deleted the
 * superintendent's offline logbooks -- the one file a DOB inspector asks for.
 *
 * SO THE SERVER SENDS BOTH, and the keep-set only ever GROWS. Three
 * combinations are possible across a deploy gap and all three are asserted
 * below, each holding the file the client of that era actually writes.
 *
 * THE SWEEP IS REALLY RUN -- the module's own `sweepDocCache` against a fake
 * device, with the names built by the module's own `cachedDocName` rather than
 * spelled out here, because the sanitising is part of what has to agree.
 *
 * Run:  node src/utils/rendererVersionSurvivesTheSweep.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const parser = require('@babel/parser');
const generate = require('@babel/generator').default;

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const HERE = __dirname;
const compiled = {};
function compile(file) {
  if (!(file in compiled)) {
    const full = path.join(HERE, file);
    // A MISSING MODULE MUST NOT BE A STACK TRACE. Compile to an empty module
    // and let the export check below name what is absent.
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

function makeDevice(files, wireRows) {
  const store = {};
  const disk = new Set(files || []);
  wireRows = wireRows || [];
  return {
    disk,
    store,
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
        const n = uri.split('/').pop();
        if (n === 'documents') return { exists: true, isDirectory: true };
        return disk.has(n) ? { exists: true, size: 10 } : { exists: false, size: 0 };
      },
      makeDirectoryAsync: async () => {},
      getFreeDiskStorageAsync: async () => 1e10,
      downloadAsync: async () => ({ status: 200, uri: 'x' }),
      moveAsync: async () => {},
    },
    NetInfo: { addEventListener: () => () => {}, fetch: async () => ({ isConnected: true }) },
    AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) },
    // Serves ONE manifest page holding `rows`, which is the wire shape the
    // server actually sends.
    apiClient: {
      defaults: { baseURL: 'https://api.test' },
      get: async () => ({ data: {
        files: { rows: [], has_more: false },
        logbooks: { rows: wireRows, has_more: false },
      } }),
    },
  };
}

function load(device, file) {
  const cache = device.__mod || (device.__mod = {});
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
    throw new Error('unstubbed import: ' + spec);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compile(file))(m, { exports: m }, shim);
  return m;
}

// The two eras' versions for ONE filed logbook.
const ID = '6aa2a530822fb03bcd752e20';
const STAMP = '2026-09-10T12:40:15.999000';   // what an old client names from
const RV = '20260910124015999000r1';          // what a new client names from

async function main() {
  // ── export check, so a tree without the change names what is absent ──────
  {
    const d = makeDevice([]);
    const dc = load(d, 'docCache.js');
    const st = load(d, 'siteManifestStore.js');
    let missing = 0;
    const wanted = [
      ['docCache', 'sweepDocCache', dc],
      ['docCache', 'cachedDocName', dc],
      ['siteManifestStore', 'writeManifestList', st],
      ['siteManifestStore', 'readManifestList', st],
      ['siteManifestStore', 'manifestScopes', st],
      ['siteManifestStore', 'fetchManifest', st],
    ];
    for (const [mod, name, obj] of wanted) {
      const present = typeof obj[name] === 'function';
      ok(present, mod + ' exports ' + name);
      if (!present) missing += 1;
    }
    if (missing) {
      console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
      console.log('  (stopping: this tree cannot be tested)');
      process.exit(1);
    }
  }

  const namer = load(makeDevice([]), 'docCache.js');
  const OLD_NAME = namer.cachedDocName(ID, STAMP);
  const NEW_NAME = namer.cachedDocName(ID, RV);
  ok(OLD_NAME !== NEW_NAME,
    'the two eras produce DIFFERENT filenames — otherwise nothing below is a test');

  // ═════════════════════════════════════════════════════════════════════════
  // 1. NEW SERVER + NEW CLIENT. `rv` is stored, and the versioned file lives.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice([NEW_NAME, 'orphan.9.pdf'], [{ id: ID, v: STAMP, rv: RV }]);
    const st = load(d, 'siteManifestStore.js');
    const scope = st.manifestScopes('p1').logbooks;
    const got = await st.fetchManifest('p1');
    await st.writeManifestList(scope, got.logbooks);

    const back = await st.readManifestList(scope);
    const row = (back.rows || [])[0] || {};
    ok(row.renderer_version === RV,
      'the manifest stores `rv` under the name the keep-set reads (got '
      + JSON.stringify(row.renderer_version) + ')');
    ok(String(row.cache_version) === STAMP,
      '`v` is still stored as cache_version, UNCHANGED — replacing it is the bug');

    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has(NEW_NAME),
      'NEW SERVER + NEW CLIENT: the renderer-versioned PDF survives the sweep');
    ok(!d.disk.has('orphan.9.pdf'),
      'CONTROL: an orphan no list mentions is still deleted — the sweep really ran');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 2. NEW SERVER + OLD CLIENT. THE HAZARD. The old client still writes the
  //    timestamp name, so `v` must still be on the wire to cover it.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice([OLD_NAME], [{ id: ID, v: STAMP, rv: RV }]);
    const st = load(d, 'siteManifestStore.js');
    const scope = st.manifestScopes('p1').logbooks;
    await st.writeManifestList(scope, (await st.fetchManifest('p1')).logbooks);
    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has(OLD_NAME),
      'NEW SERVER + OLD CLIENT: the timestamp-named PDF SURVIVES — this is the '
      + 'combination that deleted the offline records last time');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 3. OLD SERVER + NEW CLIENT. No `rv` on the wire; the fallback name lives.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice([OLD_NAME], [{ id: ID, v: STAMP }]);   // no `rv`
    const st = load(d, 'siteManifestStore.js');
    const scope = st.manifestScopes('p1').logbooks;
    await st.writeManifestList(scope, (await st.fetchManifest('p1')).logbooks);

    const row = ((await st.readManifestList(scope)).rows || [])[0] || {};
    ok(!('renderer_version' in row),
      'an older server costs the row nothing — renderer_version is OMITTED, not '
      + 'stored as a falsy default');

    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has(OLD_NAME),
      'OLD SERVER + NEW CLIENT: the fallback-named PDF survives the sweep');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 4. THE SUBMITTED-LOG ROW covers BOTH names at once, which is why it
  //    needed no second field the way the compact manifest row did.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice([OLD_NAME, NEW_NAME]);
    await d.AsyncStorage.setItem('bv_doclist:site_logs:p1', JSON.stringify([
      {
        date: '2026-09-10',
        id: 'day_p1_2026-09-10',
        logs: [{ id: ID, cache_version: RV, updated_at: STAMP }],
      },
    ]));
    await load(d, 'docCache.js').sweepDocCache();
    ok(d.disk.has(OLD_NAME) && d.disk.has(NEW_NAME),
      'a submitted-log row keeps BOTH names — it carries cache_version AND '
      + 'updated_at, which the compact manifest row does not');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 5. THE SCREEN PREFERS THE SERVER'S VERSION. Read off the AST, so a
  //    reordering of the chain is caught and a comment about it is not.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const src = fs.readFileSync(
      path.join(HERE, '..', '..', 'app', 'site', 'logbooks.jsx'), 'utf8');
    const ast = parser.parse(src, { sourceType: 'module', plugins: ['jsx'] });
    let code = null;
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'VariableDeclarator' && n.id && n.id.name === 'pdfVersion'
          && n.init) {
        code = generate(n.init).code;
      }
      for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v === 'object' && v.type) walk(v);
      }
    })(ast);

    ok(code !== null, 'pdfVersion is still declared on the site logbooks screen');
    if (code) {
      const order = code.match(/cache_version|updated_at|submitted_at|created_at/g) || [];
      ok(order[0] === 'cache_version',
        "the server's version is consulted FIRST (chain: " + order.join(' || ') + ')');
      for (const f of ['updated_at', 'submitted_at', 'created_at']) {
        ok(order.includes(f),
          'the ' + f + ' fallback is still there — an old server must still name a file');
      }
    }
  }

  console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
