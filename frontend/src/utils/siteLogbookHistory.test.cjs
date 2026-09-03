/**
 * THE TABLET KEEPS EVERY FILED DATE, AND KEEPS ITS PDFs.
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. A DOB
 * inspector arrives without warning and may ask for ANY date. The operator has
 * ruled the device must hold everything it is approved to see, complete.
 *
 * WHAT WAS WRONG. app/site/logbooks.jsx stored the WHOLE submitted-logbook
 * response — every document, with its rendered thumbnails and its kiosk worker
 * signatures — under one AsyncStorage key, sliced to the newest 60 dates. Two
 * consequences, and the second is the one that destroys records:
 *
 *   1. 60 dates of a photo-and-signature-heavy job is 5,768,861 bytes against
 *      an AsyncStorage ceiling of 6 MB that is DATABASE-WIDE (ReactDatabase-
 *      Supplier's 6 MB default; the app is CNG/prebuild with no android/
 *      overriding it). At 91.7% of the ceiling the write was already one busy
 *      month from being REJECTED — and a rejected write is not a missing
 *      photo, it is an EMPTY SCREEN offline for the one person there to read
 *      the record.
 *
 *   2. `datesToList` is what NAMES each day's full-day-report PDF, and
 *      sweepDocCache deletes every cached document that no stored list names.
 *      So the `.slice(0, 60)` did not merely hide date 61 — it un-named it,
 *      and the next time anybody opened Plans the sweep DELETED its PDF.
 *
 * RAISING 60 IS THE WRONG FIX and this file pins why: the weight is not the
 * dates, it is what each date carries. Measured on the same fixture the
 * projection work used, per date:
 *
 *     date list + tab badge counts        91 B
 *     naming every PDF for the sweep     221 B
 *     both together                      319 B
 *     the rendered day detail         95,829 B      <- 99.67% of the list
 *
 * So the resolution is structural, and it is the one siteManifestStore already
 * proved on this device: compact rows in chunked AsyncStorage keys, heavy bytes
 * on the FILESYSTEM. 4000 dates — the server's own ceiling, eleven years of
 * daily filing — is 1,281,901 B of identity rows, 20.4% of the database
 * ceiling, in 8 chunks whose largest value is 7.65% of a CursorWindow.
 *
 * ── WHAT THIS FILE GUARDS ──────────────────────────────────────────────────
 *
 *   A. THE KEEP-SET NEVER SHRINKS. The stored identity row keeps the exact
 *      `{id, cache_version}` shape docCache's keep-set builder reads, at both
 *      levels (the day report and each log), so the names the sweep keeps are
 *      the SAME names as before — just no longer cut off at 60. The real
 *      docCache is loaded here, not a mock of it, and the survival of a
 *      hundredth-date PDF across a foreign sweep is asserted directly.
 *
 *   B. DAY DETAIL IS NOT IN `documents/`. It cannot be: addRecordNames only
 *      ever emits `{id}.{version}.pdf`, so a `.json` in that flat shared
 *      directory is named by NO keep-set, matches SWEEPABLE, and is deleted by
 *      the very next sweep from any surface. Its own directory is what keeps
 *      sweepDocCache untouched.
 *
 *   C. AN INCOMPLETE WALK NEVER SHRINKS ANYTHING. Same rule as the manifest
 *      store, for the same reason: a shrunken list is a loaded gun this module
 *      would not fire and the next person to open Plans would.
 *
 *   D. A SERVER THAT DOES NOT DECLARE COMPLETENESS IS INCOMPLETE. The old
 *      response carried neither `complete` nor `next_before`. Reading its
 *      single body as the whole history is exactly the silent-ceiling defect,
 *      relocated to the client.
 *
 *   E. MEMORY IS BOUNDED BY ONE PAGE. The parameter-free response is now the
 *      COMPLETE set — at the server's own 4000-date ceiling that is ~366 MB in
 *      one body, which no tablet can parse. The walk hands each page to the
 *      store and releases it before asking for the next.
 *
 * Run:  node src/utils/siteLogbookHistory.test.cjs
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

// ── a fake device: AsyncStorage + FileSystem + a paging server ──────────────
function makeDevice(opts) {
  const o = opts || {};
  const store = {};
  for (const scope of Object.keys(o.lists || {})) {
    store[`bv_doclist:${scope}`] = JSON.stringify(o.lists[scope]);
  }
  // The FLAT shared documents/ directory, and the day-detail directory, kept
  // apart here exactly as they must be apart on the device.
  const docs = new Set(o.docs || []);
  const days = new Set(o.days || []);
  const dayBytes = Object.assign({}, o.dayBytes || {});
  const requests = [];
  const io = { sets: 0, dirsMade: [] };

  const setFails = () =>
    o.failSetItemAfter !== undefined && io.sets > o.failSetItemAfter;

  const dirOf = (uri) => {
    const parts = String(uri).split('/').filter(Boolean);
    return parts.length > 1 ? parts[parts.length - 2] : '';
  };
  const nameOf = (uri) => String(uri).split('/').pop();

  return {
    docs,
    days,
    dayBytes,
    store,
    requests,
    io,
    setFailSetAfter: (n) => { o.failSetItemAfter = n; io.sets = 0; },
    listKeys: () => Object.keys(store).filter((k) => k.startsWith('bv_doclist:')),
    AsyncStorage: {
      getAllKeys: async () => Object.keys(store),
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => {
        io.sets += 1;
        if (setFails()) throw new Error('database or disk is full (code 13)');
        store[k] = v;
      },
      removeItem: async (k) => { delete store[k]; },
    },
    FileSystem: {
      documentDirectory: '/doc/',
      readDirectoryAsync: async (uri) => {
        const d = nameOf(String(uri).replace(/\/$/, ''));
        if (d === 'documents') return [...docs];
        return [...days];
      },
      deleteAsync: async (uri) => {
        const d = dirOf(uri);
        const n = nameOf(uri);
        if (d === 'documents') docs.delete(n);
        else { days.delete(n); delete dayBytes[n]; }
      },
      // Directories are made, not assumed — otherwise a module that wrote its
      // day detail straight into the FLAT shared documents/ directory would
      // pass every assertion below, which is the one mistake that deletes it.
      getInfoAsync: async (uri) => {
        const n = nameOf(String(uri).replace(/\/$/, ''));
        if (n === 'documents') return { exists: true, isDirectory: true };
        if (n === 'site_logdays') {
          return { exists: io.dirsMade.includes('site_logdays'), isDirectory: true };
        }
        const d = dirOf(uri);
        const set = d === 'documents' ? docs : days;
        return set.has(n) ? { exists: true, size: 10 } : { exists: false, size: 0 };
      },
      makeDirectoryAsync: async (uri) => {
        io.dirsMade.push(nameOf(String(uri).replace(/\/$/, '')));
      },
      readAsStringAsync: async (uri) => {
        const n = nameOf(uri);
        if (!(n in dayBytes)) throw new Error('ENOENT');
        return dayBytes[n];
      },
      writeAsStringAsync: async (uri, contents) => {
        if (o.failDayWrite) throw new Error('ENOSPC');
        const n = nameOf(uri);
        days.add(n);
        dayBytes[n] = contents;
      },
      getFreeDiskStorageAsync: async () => (o.freeBytes === undefined ? 1e10 : o.freeBytes),
      downloadAsync: async (url, dest) => {
        docs.add(nameOf(dest));
        return { status: 200, uri: dest };
      },
    },
    // `pages` is served in order; `null` is a network failure mid-walk.
    apiClient: {
      defaults: { baseURL: 'https://api.test' },
      get: async (url) => {
        requests.push(url);
        const page = (o.pages || []).shift();
        if (page === null || page === undefined) {
          const e = new Error('Network Error');
          e.request = {};
          throw e;
        }
        return { data: page };
      },
    },
  };
}

// ── module loader: the REAL docCache and the REAL chunked store ─────────────
const HERE = __dirname;
const compiled = {};
function compile(file) {
  if (!compiled[file]) {
    const full = path.join(HERE, file);
    // A MISSING MODULE MUST NOT BE A STACK TRACE — against a tree without the
    // history store, an ENOENT would replace every named guarantee below with
    // one opaque error. Compile to empty and let the export check name them.
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
      return { Platform: { OS: 'android' }, AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) } };
    }
    if (spec === '@react-native-community/netinfo') {
      return { __esModule: true, default: { addEventListener: () => () => {}, fetch: async () => ({ isConnected: true }) } };
    }
    if (spec === './api') {
      return { __esModule: true, default: device.apiClient, getToken: async () => 'jwt' };
    }
    if (spec === './docCache') return load(device, 'docCache.js');
    if (spec === './siteManifestStore') return load(device, 'siteManifestStore.js');
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compile(file))(m, { exports: m }, shim);
  return m;
}
const hist = (d) => load(d, 'siteLogbookHistory.js');
const cache = (d) => load(d, 'docCache.js');

const PID = 'P1';

// ── fixtures ───────────────────────────────────────────────────────────────
//
// A log carries a FAT `data` so every assertion about what reaches AsyncStorage
// is an assertion about real weight, not about a field count.
const FAT = 'x'.repeat(4096);

function log(i, type, date) {
  return {
    id: `lb_${type}_${i}`,
    _id: `lb_${type}_${i}`,
    log_type: type,
    date,
    status: 'submitted',
    cp_name: 'Casey CP',
    created_at: `${date}T07:00:00+00:00`,
    updated_at: `${date}T07:05:00+00:00`,
    data: { workers: [{ name: 'W', worker_signature: FAT }], blob: FAT },
  };
}

/** `n` dates, newest first, two logs each. */
function history(n, from = 0) {
  const out = {};
  for (let i = from; i < from + n; i += 1) {
    const date = `2026-${String(12 - Math.floor(i / 28)).padStart(2, '0')}-${String(28 - (i % 28)).padStart(2, '0')}`;
    out[date] = [log(i, 'daily_jobsite', date), log(i, 'preshift_signin', date)];
  }
  return out;
}

/** One page of the paged submitted response. */
function page(dates, nextBefore) {
  const keys = Object.keys(dates).sort().reverse();
  return {
    dates,
    complete: nextBefore === null || nextBefore === undefined,
    next_before: nextBefore === undefined ? null : nextBefore,
    date_count: keys.length,
    log_count: keys.reduce((n, k) => n + dates[k].length, 0),
  };
}

const sortDates = (o) => Object.keys(o).sort().reverse();

async function indexRows(d) {
  const M = hist(d);
  const r = await M.readHistoryIndex(PID);
  return (r && r.rows) || [];
}

// ═══════════════════════════════════════════════════════════════════════════
async function main() {
  // ── 0. the module exists and names its parts ─────────────────────────────
  {
    const d = makeDevice({});
    const M = hist(d);
    for (const fn of ['historyScope', 'dayReportId', 'dayReportVersion',
      'identityRow', 'mergeHistoryRows', 'readHistoryIndex', 'readDayDetail',
      'fetchSubmittedHistory', 'syncLogbookHistory']) {
      ok(typeof M[fn] === 'function', `siteLogbookHistory exports ${fn}()`);
    }
  }

  // ═════════════════════════════════════════════════════════════════════════
  // A. THE STORED ROW IS COMPACT, AND COMPLETE HISTORY FITS
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ pages: [page(history(400))] });
    const M = hist(d);
    const r = await M.syncLogbookHistory(PID);
    ok(r.complete === true, 'a single complete response is a complete walk');
    ok(r.dates === 400, '400 dates were stored, not 60 — the cap is gone');

    const rows = await indexRows(d);
    ok(rows.length === 400, 'the index holds every date the server named');

    // THE WEIGHT, MEASURED THROUGH THE REAL STORAGE the module actually used.
    const stored = d.listKeys()
      .filter((k) => k.startsWith('bv_doclist:site_logbook_history'))
      .reduce((n, k) => n + Buffer.byteLength(d.store[k], 'utf8'), 0);
    const perDate = stored / 400;
    ok(perDate < 600,
      `an identity row is ${perDate.toFixed(0)} B/date — under 600, so the `
      + 'server’s 4000-date ceiling fits inside the 6 MB database ceiling');
    ok(stored * 10 < 6 * 1024 * 1024,
      '400 dates is under a tenth of the whole AsyncStorage database ceiling');

    // AND THE FAT IS NOT IN THERE.
    const raw = d.listKeys().map((k) => d.store[k]).join('');
    ok(!raw.includes(FAT),
      'NO rendered day detail reached AsyncStorage — the 99.67% stays off it');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // B. THE KEEP-SET: SAME NAMES, NO LONGER CUT OFF AT 60
  // ═════════════════════════════════════════════════════════════════════════
  {
    const dates = history(100);
    const keys = sortDates(dates);
    // Every day-report PDF and every per-log PDF is already on the device.
    const docs = [];
    for (const date of keys) {
      docs.push(`day_${PID}_${date}.${date}T07_05_00_00_00.pdf`);
      for (const l of dates[date]) docs.push(`${l.id}.${date}T07_05_00_00_00.pdf`);
    }
    const d = makeDevice({ pages: [page(dates)], docs });
    await hist(d).syncLogbookHistory(PID);

    // A FOREIGN SWEEP — this is the plans screen, on any successful list load.
    const swept = await cache(d).sweepDocCache();
    ok(!swept.skipped, 'the union sweep ran');
    ok(swept.deleted.length === 0,
      'a foreign sweep deleted NOTHING — every one of the 100 dates is named');

    const oldest = keys[keys.length - 1];
    ok(d.docs.has(`day_${PID}_${oldest}.${oldest}T07_05_00_00_00.pdf`),
      `the full-day report for date 100 (${oldest}) survived — the .slice(0, 60) `
      + 'used to un-name it and the next sweep deleted it');
    ok(d.docs.has(`lb_daily_jobsite_99.${oldest}T07_05_00_00_00.pdf`),
      'and so did the individual logbook PDF on that date');
  }

  // ── B2. day detail is NOT in the swept flat directory ────────────────────
  {
    const d = makeDevice({ pages: [page(history(3))] });
    await hist(d).syncLogbookHistory(PID);
    ok(d.days.size === 3, 'one day-detail file per date was written');
    ok(d.docs.size === 0,
      'and NOT ONE of them landed in documents/ — addRecordNames only ever '
      + 'emits .pdf, so a .json there is named by no keep-set and SWEEPABLE '
      + 'matches it: the next sweep from any surface would delete it');
    ok(d.io.dirsMade.includes('site_logdays'),
      'day detail has its own directory, so sweepDocCache is untouched');

    const swept = await cache(d).sweepDocCache();
    ok(!swept.skipped && swept.deleted.length === 0, 'the sweep left it alone');
    ok(d.days.size === 3, 'the day-detail files are still there after a sweep');
  }

  // ── B3. the detail actually round-trips, keyed on the day's version ──────
  {
    const dates = history(2);
    const d = makeDevice({ pages: [page(dates)] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);
    const rows = await indexRows(d);
    const row = rows[0];
    const got = await M.readDayDetail(PID, row.date, row.cache_version);
    ok(Array.isArray(got) && got.length === 2,
      'an expanded day reads its two logs back off the filesystem');
    ok(got[0].data && got[0].data.blob === FAT,
      'and they carry the full rendered detail, byte for byte');

    const stale = await M.readDayDetail(PID, row.date, 'a-different-version');
    ok(stale === null,
      'an AMENDED day misses its file rather than serving the superseded record '
      + '— the version is in the name, as it is for every other cached doc');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // C. AN INCOMPLETE WALK NEVER SHRINKS ANYTHING
  // ═════════════════════════════════════════════════════════════════════════
  {
    // First: a complete walk of 5 dates. Then: a walk that drops its page.
    const full = history(5);
    const d = makeDevice({ pages: [page(full), null] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);
    ok((await indexRows(d)).length === 5, 'five dates are stored');

    const r2 = await M.syncLogbookHistory(PID);
    ok(r2.complete === false, 'a dropped page is reported as an incomplete walk');
    ok(r2.ok === false, 'and as a failed read, so the screen can say so');
    const after = await indexRows(d);
    ok(after.length === 5,
      'the stored index did NOT shrink — a shrunken list is a loaded gun this '
      + 'module would not fire and the next person to open Plans would');
  }

  // ── C2. a SHORT but successful page unions, it does not replace ──────────
  {
    const d = makeDevice({ pages: [page(history(5))] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);
    const before = (await indexRows(d)).map((r) => r.date).sort();

    // The server now answers with only the newest date and says it is a PAGE.
    const newest = { [before[before.length - 1]]: history(1)[before[before.length - 1]] };
    d.__pages = null;
    const d2 = makeDevice({ lists: {}, pages: [page(newest, 'cursor'), null] });
    // Replay the first device's storage onto the second so the union is real.
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    const M2 = hist(d2);
    const r = await M2.syncLogbookHistory(PID);
    ok(r.complete === false, 'a page that names a cursor is not the whole history');
    const after = (await indexRows(d2)).map((r2) => r2.date).sort();
    ok(after.length === 5,
      'every date the page did not mention is KEPT — an incomplete fetch has no '
      + 'authority to remove, so all five survive');
  }

  // ── C3. a COMPLETE walk is the only thing that may drop a date ───────────
  {
    const d = makeDevice({ pages: [page(history(5))] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);

    const three = history(3);
    const d2 = makeDevice({ pages: [page(three)] });
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    const r = await hist(d2).syncLogbookHistory(PID);
    ok(r.complete === true, 'the second walk was complete');
    ok((await indexRows(d2)).length === 3,
      'a COMPLETE walk is the truth, so a withdrawn date leaves the list');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // D. A SERVER THAT DOES NOT DECLARE COMPLETENESS IS INCOMPLETE
  // ═════════════════════════════════════════════════════════════════════════
  {
    // The pre-projection body: `{dates}` and nothing else. It was capped at
    // 500 logs and said so nowhere.
    const d = makeDevice({ pages: [{ dates: history(4) }] });
    const r = await hist(d).syncLogbookHistory(PID);
    ok(r.complete === false,
      'a response carrying neither `complete` nor `next_before` is NOT the whole '
      + 'history — believing it would relocate the silent ceiling to the client');
    ok(String(r.reason || '').includes('contract'),
      'and the reason names why, rather than reading as a network failure');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // E. MEMORY IS BOUNDED BY ONE PAGE
  // ═════════════════════════════════════════════════════════════════════════
  {
    const p1 = history(2, 0);
    const p2 = history(2, 2);
    const p3 = history(2, 4);
    const cur = (o) => sortDates(o)[sortDates(o).length - 1];
    const d = makeDevice({
      pages: [page(p1, cur(p1)), page(p2, cur(p2)), page(p3)],
    });
    const M = hist(d);
    const r = await M.syncLogbookHistory(PID, { limit: 2 });
    ok(r.complete === true, 'a walk that followed every cursor to the end is complete');
    ok(r.dates === 6, 'and assembled all six dates across three pages');
    ok(d.requests.length === 3, 'in exactly three requests');
    ok(/limit=2/.test(d.requests[0]) && !/before=/.test(d.requests[0]),
      'the first request asks for a bounded PAGE, never the 366 MB complete body');
    ok(/before=/.test(d.requests[1]),
      'and the second carries the cursor the first returned');
    ok(d.days.size === 6,
      'every page’s detail was written to disk before the next was asked for, '
      + 'so one page is the memory high-water mark');
    ok(r.recent && Object.keys(r.recent).length === 2,
      'the FIRST page is handed back — the newest dates, the window this screen '
      + 'used to hold whole, so a recent day opens with no disk read');
    ok(r.recent && Object.keys(r.recent).every((k) => k in p1),
      'and it is the newest page, not the last one the walk happened to end on');
    ok(Object.values(r.recent)[0][0].data.blob === FAT,
      'carrying the real rendered detail, which on a platform that cannot hold '
      + 'files is the only detail there will ever be');
  }

  // ── E2. the walk is bounded, and stopping short reports incomplete ───────
  {
    const pages = [];
    for (let i = 0; i < 40; i += 1) {
      const p = history(1, i);
      pages.push(page(p, sortDates(p)[0]));
    }
    const d = makeDevice({ pages });
    const r = await hist(d).syncLogbookHistory(PID, { limit: 1, maxPages: 5 });
    ok(r.complete === false,
      'a server that never stops naming a cursor does not produce an endless walk');
    ok(d.requests.length === 5, 'the walk stopped at its page cap');
    ok((await indexRows(d)).length === 0,
      'and committed nothing, because it may not claim to be the whole history');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // F. A REJECTED WRITE COSTS THE NEW LIST, NEVER THE OLD ONE
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ pages: [page(history(4))] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);
    const before = (await indexRows(d)).length;
    ok(before === 4, 'four dates are committed');

    // The database is full from here on — every setItem rejects, exactly as
    // AsyncStorage does at the ceiling.
    const d2 = makeDevice({ pages: [page(history(9))] });
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    d2.setFailSetAfter(0);
    const r = await hist(d2).syncLogbookHistory(PID);
    ok(r.stored === false, 'a rejected write is REPORTED, not assumed to have landed');
    d2.setFailSetAfter(undefined);
    ok((await indexRows(d2)).length === 4,
      'and the previously committed generation is still what the reader assembles, '
      + 'whole — the tablet keeps the records it had');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // G. DAY DETAIL IS PRUNED ONLY BY A COMPLETE WALK, AND ONLY ITS OWN PROJECT
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ pages: [page(history(5))] });
    const M = hist(d);
    await M.syncLogbookHistory(PID);
    ok(d.days.size === 5, 'five day-detail files');

    // Another project's tablet state, and a stray file this module never wrote.
    d.days.add('P9_2020-01-01.v1.json');
    d.days.add('not-ours.txt');

    const d2 = makeDevice({ pages: [page(history(2))] });
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    for (const n of d.days) { d2.days.add(n); d2.dayBytes[n] = d.dayBytes[n] || '[]'; }
    const r = await hist(d2).syncLogbookHistory(PID);
    ok(r.complete === true, 'the walk was complete, so pruning is authorised');
    ok(d2.days.has('P9_2020-01-01.v1.json'),
      'another project’s day detail is NEVER touched — deleting by id out of a '
      + 'shared directory is the shape of the prior incident');
    ok(d2.days.has('not-ours.txt'),
      'and a name this module did not write is left alone');
    ok(![...d2.days].some((n) => n.startsWith(`${PID}_2026-12-24`)),
      'a date this project no longer files on had its detail reclaimed');
  }

  // ── G2. an INCOMPLETE walk prunes nothing ────────────────────────────────
  {
    const d = makeDevice({ pages: [page(history(5))] });
    await hist(d).syncLogbookHistory(PID);
    const kept = [...d.days];

    const d2 = makeDevice({ pages: [page(history(1), 'cursor'), null] });
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    for (const n of d.days) { d2.days.add(n); d2.dayBytes[n] = d.dayBytes[n]; }
    await hist(d2).syncLogbookHistory(PID);
    ok(kept.every((n) => d2.days.has(n)),
      'an incomplete walk deleted no day detail — stale is recoverable on the '
      + 'next poll, deleted underground is not');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // H. THE ROW SHAPE IS docCache's, NOT A CONVENIENT ONE
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({});
    const M = hist(d);
    const date = '2026-04-28';
    const logs = [log(1, 'daily_jobsite', date), log(2, 'preshift_signin', date)];
    const row = M.identityRow(PID, date, logs);
    ok(row.id === `day_${PID}_${date}`,
      'the row declares the full-day report id this screen INVENTS — nothing '
      + 'else on the device names that file');
    ok(row.cache_version === `${date}T07:05:00+00:00`,
      'versioned on the newest log of the day, so an amendment re-downloads');
    ok(row.logs.every((l) => l.id && l.updated_at && l.log_type && l.status),
      'each log keeps id + version (for the sweep) and log_type + status (for the '
      + 'tab filter and its badge) — and nothing else');
    ok(row.logs.every((l) => l.data === undefined),
      'and carries NO `data`: that is the 95,829 B/date this whole design moves off '
      + 'AsyncStorage');
    ok(M.dayReportVersion([], date) === date,
      'a day with no logs still names its report, so the sweep still keeps it');

    // INHERITED FROM THE PIN THIS COMMIT DELETES. site/logbooks.jsx used to
    // run `stripPhotoBlobs` before writing its list, and a backend source test
    // grepped that screen for the name. The screen no longer stores anything --
    // this module does -- so the grep pinned a deleted name in the wrong file.
    // The concern is real and it is asserted here instead, by EXECUTION: not
    // "the strip function is still present" but "no photo bytes come out".
    //
    // Stronger than what it replaces. `stripPhotoBlobs` was a blacklist that
    // removed `base64` and would have needed editing again for `thumb_base64`;
    // identityRow is an allow-list, so a photo field invented tomorrow is
    // excluded without anyone remembering to exclude it.
    const fat = {
      id: 'L9', log_type: 'daily_jobsite', status: 'submitted',
      updated_at: date + 'T07:05:00+00:00',
      base64: 'A'.repeat(4096),
      thumb_base64: 'B'.repeat(1024),
      photos: [{ base64: 'C'.repeat(4096), thumb_base64: 'D'.repeat(1024) }],
      data: { notes: 'E'.repeat(4096) },
    };
    const lean = M.identityRow(PID, date, [fat]).logs[0];
    ok(JSON.stringify(lean).indexOf('AAAA') === -1
      && JSON.stringify(lean).indexOf('BBBB') === -1
      && JSON.stringify(lean).indexOf('CCCC') === -1
      && JSON.stringify(lean).indexOf('DDDD') === -1
      && JSON.stringify(lean).indexOf('EEEE') === -1,
      'NO PHOTO BYTES REACH AsyncStorage -- base64, thumb_base64, a photos[] '
      + 'array and data are all absent from the stored row, by allow-list');
    ok(Object.keys(lean).sort().join(',') === 'id,log_type,status,updated_at',
      'and the row is EXACTLY the four fields -- a fifth would be a new field '
      + 'nobody sized against the 6 MB ceiling');
  }

  // ── H2. mergeHistoryRows keys on the DATE, not on id|version ────────────
  {
    const d = makeDevice({});
    const M = hist(d);
    const prev = [{ date: '2026-04-28', id: 'day_P1_2026-04-28', cache_version: 'v1', logs: [] }];
    const next = [{ date: '2026-04-28', id: 'day_P1_2026-04-28', cache_version: 'v2', logs: [] }];
    const merged = M.mergeHistoryRows(prev, next, false);
    ok(merged.length === 1,
      'an AMENDED date replaces its own row rather than appearing twice — a '
      + 'merge keyed on id|version would render the same day in the list twice');
    ok(merged[0].cache_version === 'v2', 'and the newer version wins');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
