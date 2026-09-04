/**
 * THE CACHE STOPS GROWING FOR EVER, WITHOUT TAKING A DRAWING OFF A PHONE.
 *
 * Nothing has ever deleted from this directory. It is documentDirectory, chosen
 * deliberately because the OS will never evict it, and it is in device backups.
 * When a drawing changes in Dropbox its cache_version bumps, {id}.2.pdf lands,
 * and {id}.1.pdf stays until the app is uninstalled. The readiness strip makes
 * this worse on purpose: it encourages saving every drawing on every project.
 *
 * THE DIRECTORY IS FLAT AND SHARED BY EVERY PROJECT. Names are
 * {fileId}.{cache_version}.{ext} with no project prefix, so a sweep keyed on ONE
 * project's list would delete every OTHER project's plans. That is the failure
 * this file exists to make impossible, and it is asserted first.
 *
 * EVERY AMBIGUITY RESOLVES TO KEEPING. Deleting a file the CP is relying on
 * underground is worse than never having saved it, so:
 *   - lists unreadable, or none stored  -> delete NOTHING
 *   - a name that does not parse        -> keep
 *   - a delete that fails               -> keep, and count it kept
 *
 * Run:  node src/utils/docCacheSweep.test.cjs
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

// ── a fake device: AsyncStorage + FileSystem, both controllable ─────────────
function makeDevice(opts) {
  const o = opts || {};
  const lists = o.lists || {};
  const store = {};
  for (const scope of Object.keys(lists)) {
    store[`bv_doclist:${scope}`] = o.badJson ? '{not json' : JSON.stringify(lists[scope]);
  }
  const disk = new Set(o.files || []);
  const failDelete = o.failDelete || [];
  return {
    disk,
    AsyncStorage: {
      getAllKeys: async () => {
        if (o.breakKeys) throw new Error('storage down');
        return Object.keys(store);
      },
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
    },
    FileSystem: {
      documentDirectory: '/doc/',
      readDirectoryAsync: async () => {
        if (o.breakDir) throw new Error('unreadable');
        return [...disk];
      },
      deleteAsync: async (uri) => {
        const name = uri.split('/').pop();
        if (failDelete.includes(name)) throw new Error('locked');
        disk.delete(name);
      },
      getInfoAsync: async () => ({ exists: true, size: 1 }),
      makeDirectoryAsync: async () => {},
      getFreeDiskStorageAsync: async () => 1e10,
      downloadAsync: async () => ({ status: 200, uri: 'x' }),
    },
  };
}

const MODULE = path.join(__dirname, 'docCache.js');
const COMPILED = babel.transformSync(fs.readFileSync(MODULE, 'utf8'), {
  filename: MODULE,
  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false,
  babelrc: false,
}).code;

function load(device) {
  const m = {};
  const shim = (spec) => {
    if (spec === '@react-native-async-storage/async-storage') {
      return { __esModule: true, default: device.AsyncStorage };
    }
    if (spec === 'expo-file-system/legacy') return device.FileSystem;
    if (spec === 'react-native') return { Platform: { OS: 'ios' } };
    if (spec === './api') return { __esModule: true, default: {}, getToken: async () => 't' };
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', COMPILED)(m, { exports: m }, shim);
  return m;
}

const f = (id, v) => ({ id, cache_version: v });

async function main() {
  // NAMED FAILURES, NOT A STACK TRACE. Against a tree without the sweep, a
  // bare call throws "sweepDocCache is not a function" and the run reports one
  // opaque error instead of the guarantee that is absent.
  {
    const M = load(makeDevice({ lists: {} }));
    let missing = 0;
    for (const name of ['sweepDocCache', 'collectKeepNames']) {
      const present = typeof M[name] === 'function';
      ok(present, `docCache exports ${name}`);
      if (!present) missing += 1;
    }
    if (missing > 0) {
      console.log(`
  ${passed} passed, ${failed} failed`);
      console.log('  (stopping: this tree has no cache sweep)');
      process.exit(1);
    }
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 1. ANOTHER PROJECT'S PLANS ARE NEVER TOUCHED. The flat shared directory
  //    makes this the sharpest edge in the change.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      lists: { 'plans:A': [f('a1', 1), f('a2', 1)], 'plans:B': [f('b1', 1)] },
      files: ['a1.1.pdf', 'a2.1.pdf', 'b1.1.pdf', 'orphan.9.pdf'],
    });
    const r = await load(d).sweepDocCache();
    ok(!d.disk.has('orphan.9.pdf'), 'an orphan no list mentions is removed');
    ok(d.disk.has('b1.1.pdf'),
      "PROJECT B'S PLAN SURVIVES a sweep triggered from project A — the keep-set "
      + 'is the union of ALL cached lists, never one screen');
    ok(d.disk.has('a1.1.pdf') && d.disk.has('a2.1.pdf'),
      "and project A's own files survive");
    ok(r.deleted.length === 1 && r.kept === 3, 'the counts report what happened');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 2. THE ACTUAL WIN: superseded versions.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      lists: { 'plans:A': [f('a1', 3)] },
      files: ['a1.1.pdf', 'a1.2.pdf', 'a1.3.pdf'],
    });
    await load(d).sweepDocCache();
    ok(d.disk.has('a1.3.pdf'), 'the CURRENT version is kept');
    ok(!d.disk.has('a1.1.pdf') && !d.disk.has('a1.2.pdf'),
      'and every superseded version is removed — the growth this fixes');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 3. EVERY AMBIGUITY RESOLVES TO KEEPING.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d1 = makeDevice({ lists: {}, files: ['a1.1.pdf', 'b1.1.pdf'] });
    const r1 = await load(d1).sweepDocCache();
    ok(r1.skipped === true && r1.reason === 'no-keep-set',
      'NO STORED LISTS deletes nothing and says why');
    ok(d1.disk.size === 2, 'and the disk is untouched');

    const d2 = makeDevice({
      lists: { 'plans:A': [f('a1', 1)] }, files: ['a1.1.pdf', 'x.1.pdf'], breakKeys: true,
    });
    const r2 = await load(d2).sweepDocCache();
    ok(r2.skipped === true, 'UNREADABLE STORAGE deletes nothing');
    ok(d2.disk.size === 2, 'and the disk is untouched');

    const d3 = makeDevice({
      lists: { 'plans:A': [f('a1', 1)] }, files: ['a1.1.pdf', 'x.1.pdf'], badJson: true,
    });
    const r3 = await load(d3).sweepDocCache();
    ok(r3.skipped === true, 'A CORRUPT LIST deletes nothing');
    ok(d3.disk.size === 2, 'and the disk is untouched');

    const d4 = makeDevice({
      lists: { 'plans:A': [f('a1', 1)] }, files: ['a1.1.pdf'], breakDir: true,
    });
    const r4 = await load(d4).sweepDocCache();
    ok(r4.skipped === true && r4.reason === 'unreadable-dir',
      'AN UNREADABLE DIRECTORY deletes nothing');

    const d5 = makeDevice({
      lists: { 'plans:A': [f('a1', 1)] },
      files: ['a1.1.pdf', 'notes.txt', 'no-dots', '.hidden'],
    });
    await load(d5).sweepDocCache();
    ok(d5.disk.has('notes.txt') && d5.disk.has('no-dots') && d5.disk.has('.hidden'),
      'A NAME THAT DOES NOT PARSE is left alone — we remove only what we can '
      + 'prove this cache created');

    const d6 = makeDevice({
      lists: { 'plans:A': [f('a1', 1)] },
      files: ['a1.1.pdf', 'gone.1.pdf'],
      failDelete: ['gone.1.pdf'],
    });
    const r6 = await load(d6).sweepDocCache();
    ok(d6.disk.has('gone.1.pdf'), 'A FAILED DELETE leaves the file');
    ok(r6.kept === 2 && r6.deleted.length === 0,
      'and is counted as kept, not deleted');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 4. dryRun reports without touching anything.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ lists: { 'plans:A': [f('a1', 2)] }, files: ['a1.1.pdf', 'a1.2.pdf'] });
    const r = await load(d).sweepDocCache({ dryRun: true });
    ok(r.deleted.indexOf('a1.1.pdf') !== -1, 'dryRun names what it would remove');
    ok(d.disk.size === 2, 'and removes nothing');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 5. collectKeepNames, directly.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      lists: { 'plans:A': [f('a1', 1), { _id: 'a2', cache_version: 4 }, { name: 'no id' }] },
    });
    const keep = await load(d).collectKeepNames();
    ok(keep.has('a1.1.pdf'), 'reads id');
    ok(keep.has('a2.4.pdf'), 'and _id');
    ok(keep.has('a1.1.jpg') && keep.has('a2.4.jpg'),
      'and every extension the cache can write, for each');

    // ─────────────────────────────────────────────────────────────────────
    // THE SUBJECT, ASSERTED DIRECTLY, BECAUSE A TOTAL IS NOT THIS SUBJECT.
    //
    // This read `keep.size === 2`. The claim is "a row with no identifier
    // contributes nothing", and a size only shows that while EVERY row happens
    // to contribute exactly one name. It stopped showing it the day
    // CACHE_EXTS made each row contribute a .pdf AND a .jpg — a change to a
    // different dimension entirely, which moved the number without touching
    // the property. Bumping the 2 to a 4 would have restored the green and
    // kept the defect: the assertion would still be pinning an arithmetic
    // coincidence rather than the absence it is named for.
    //
    // So assert the absence. The keep-set must name exactly the two rows that
    // HAVE identifiers, whatever number of names that turns out to be.
    // ─────────────────────────────────────────────────────────────────────
    const idsKept = new Set([...keep].map((n) => n.split('.')[0]));
    ok(idsKept.size === 2 && idsKept.has('a1') && idsKept.has('a2'),
      'and skips a row with no identifier rather than inventing one');
    ok(![...keep].some((n) => /undefined|null|NaN/.test(n)),
      'and invents no name from a missing id');

    const empty = await load(makeDevice({ lists: {} })).collectKeepNames();
    ok(empty === null, 'NULL, not an empty Set, when there is no basis to delete');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 6. THE OFFLINE LOGBOOKS SURVIVE A SWEEP FIRED FROM THE PLANS SCREEN.
  //
  //    Every case above builds a PLANS-shaped list — [{id, cache_version}] —
  //    and that is the whole reason this defect shipped. cacheDocList stores
  //    whatever array a screen hands it, and site/logbooks.jsx hands it
  //    [{date, logs:[...]}]: the records are one level down and NOTHING at the
  //    top level carries an id. A keep-set that reads `f.id` off each element
  //    came back EMPTY for that key, while the logbook PDFs warmDocCache had
  //    written ({logId}.{updated_at}.pdf) matched SWEEPABLE exactly. The sweep
  //    fires from files.jsx on every successful plans load, so a CP opening
  //    Plans on the street deleted the super's offline compliance record.
  //
  //    Versions do not agree either: plans key on `cache_version`, logbooks on
  //    `updated_at || submitted_at || created_at`.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const log = {
      id: 'lg1',
      status: 'submitted',
      created_at: '2026-05-02T07:00:00Z',
      submitted_at: '2026-05-03T18:30:00Z',
      updated_at: '2026-05-04T14:15:00Z',   // an amendment; what pdfVersion uses
    };
    // Ask the module for the on-disk name rather than hand-sanitising it here,
    // so the test cannot drift from safeName().
    const naming = load(makeDevice({ lists: {} }));
    const liveLogPdf = naming.cachedDocName('lg1', log.updated_at);
    const supersededLogPdf = naming.cachedDocName('lg1', '2026-04-28T09:00:00Z');
    // The full-day combined report. Its id is INVENTED by the logbooks screen
    // (`day_{projectId}_{date}`) and appears in no log record, so it survives
    // only because that screen writes the identity onto the cached entry.
    const dayPdf = naming.cachedDocName('day_P_2026-05-04', log.updated_at);

    const d = makeDevice({
      lists: {
        // The CP's plans list — the screen that TRIGGERS the sweep.
        'plans:A': [f('a1', 2)],
        // The super's logbooks list, nested, on the same device — exactly the
        // shape app/site/logbooks.jsx writes, day-report identity and all.
        'site_logbooks:P': [
          {
            date: '2026-05-04',
            id: 'day_P_2026-05-04',
            cache_version: log.updated_at,
            logs: [log],
          },
          { date: '2026-05-01', id: 'day_P_2026-05-01', cache_version: '2026-05-01', logs: [] },
        ],
      },
      files: ['a1.2.pdf', liveLogPdf, supersededLogPdf, dayPdf, 'orphan.9.pdf'],
    });

    const r = await load(d).sweepDocCache();
    ok(d.disk.has(liveLogPdf),
      'THE SUBMITTED LOGBOOK PDF SURVIVES a sweep fired from the plans screen — '
      + 'the keep-set reads records nested inside {date, logs:[...]}, not just '
      + 'flat file rows');
    ok(d.disk.has('a1.2.pdf'), "and the plans screen's own current plan survives");
    ok(!d.disk.has('orphan.9.pdf'), 'while a genuine orphan is still removed');
    ok(d.disk.has(dayPdf),
      'THE FULL-DAY REPORT SURVIVES TOO — the sweep reads the id off the '
      + '{date, ...} container itself, which is where the logbooks screen '
      + 'declares the name it invented for a file no record mentions');
    ok(!d.disk.has(supersededLogPdf),
      'and a SUPERSEDED logbook PDF is still removed — keeping every version '
      + 'field is not the same as keeping everything');
    ok(r.deleted.length === 2, 'the counts report exactly those two removals');

    // The keep-set directly, so a failure here names the cause rather than the
    // symptom.
    const keep = await load(d).collectKeepNames();
    ok(keep !== null && keep.has(liveLogPdf),
      'collectKeepNames descends into the nested logs array');
    ok(keep.has('a1.2.pdf'), 'and still reads a flat plans row');

    // The fixture above is hand-built, so on its own it proves only what
    // docCache does with that shape. SOMETHING HAS TO ACTUALLY WRITE IT: the
    // day report's id is INVENTED by the site logbooks surface and appears
    // nowhere else on the device, so if the stored row stops carrying it, the
    // keep-set goes back to not naming that file and the sweep deletes it.
    //
    // THE ROW BUILDER MOVED, AND THE GUARANTEE DID NOT. It used to be
    // `datesToList` inside app/site/logbooks.jsx, which cached WHOLE documents
    // and sliced them to 60 dates; it is now `identityRow` in
    // src/utils/siteLogbookHistory.js, which stores identity for every filed
    // date and keeps the detail on the filesystem. What is asserted is the
    // same thing either way: the stored entry carries `id` + `cache_version`.
    const strip = (p) => fs.readFileSync(p, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
      .replace(/^\s*\/\/.*$/gm, '');
    const lb = strip(path.join(__dirname, '..', '..', 'app', 'site', 'logbooks.jsx'));
    const histPath = path.join(__dirname, 'siteLogbookHistory.js');
    const histSrc = fs.existsSync(histPath) ? strip(histPath) : '';
    ok(histSrc !== '', 'src/utils/siteLogbookHistory.js exists');

    const histTree = parser.parse(histSrc, { sourceType: 'module', plugins: ['jsx'] });
    let rowBuilder = null;
    (function walkHist(n, seen) {
      if (!n || typeof n !== 'object' || seen.has(n)) return;
      seen.add(n);
      if (n.type === 'FunctionDeclaration' && n.id && n.id.name === 'identityRow') {
        rowBuilder = generate(n).code;
      }
      if (n.type === 'VariableDeclarator' && n.id.name === 'identityRow' && n.init) {
        rowBuilder = generate(n.init).code;
      }
      for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach((c) => walkHist(c, seen));
        else if (v && typeof v === 'object' && typeof v.type === 'string') walkHist(v, seen);
      }
    }(histTree, new Set()));

    ok(rowBuilder !== null,
      'the site logbooks list is still built by one named row builder (identityRow)');
    ok(rowBuilder !== null
      && /\bid\b/.test(rowBuilder) && rowBuilder.indexOf('cache_version') !== -1,
      'AND STAMPS A CACHE IDENTITY ON EACH STORED ENTRY — without an id on the '
      + 'entry, nothing on the device names the full-day report PDF and the '
      + 'sweep is right to delete it');
    // AND THE LOGS UNDER IT KEEP THEIRS. The keep-set descends into the nested
    // `logs` array and rebuilds `{id}.{version}` from `updated_at`; a row that
    // dropped either would take every individual logbook PDF with it.
    ok(rowBuilder !== null
      && /\blogs\b/.test(rowBuilder) && rowBuilder.indexOf('updated_at') !== -1,
      'and each log under it keeps its own id and version, which is what names '
      + 'the individual logbook PDFs the sweep must not delete');

    // ONE SPELLING OF THE NAME, ACROSS BOTH FILES: where the file is declared
    // to the sweep (the row builder) and where it is opened (the screen). Two
    // spellings of that id would be this same defect one level up.
    ok(/dayReportId\s*\(/.test(histSrc),
      'the day-report id is built by a named helper where the row declares it');
    ok(/dayReportId\s*\(/.test(lb),
      'and the screen that OPENS that file resolves its name through the same '
      + 'helper rather than spelling it a second time');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 7. THE SWEEP RUNS ONLY BEHIND A LIST THE SCREEN TRUSTED ENOUGH TO STORE.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const screen = fs.readFileSync(
      path.join(__dirname, '..', '..', 'app', 'projects', '[id]', 'files.jsx'),
      'utf8');
    const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });
    const seen = new Set();
    let guarded = false;
    (function walk(n) {
      if (!n || typeof n !== 'object' || seen.has(n)) return;
      seen.add(n);
      if (n.type === 'IfStatement' && n.test && n.test.name === 'mayCache') {
        const body = n.consequent.type === 'BlockStatement'
          ? n.consequent.body : [n.consequent];
        const src = body.map((st) => generate(st).code).join('\n');
        if (src.indexOf('sweepDocCache(') !== -1 && src.indexOf('cacheDocList(') !== -1) {
          guarded = true;
        }
      }
      for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v);
      }
    }(tree));
    ok(guarded,
      'the sweep sits behind the same mayCache guard as the list write — it '
      + 'never runs off a mid-sync read');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
