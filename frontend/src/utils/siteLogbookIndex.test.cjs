/**
 * THE LIST LOADS FIRST, THE DOCUMENTS LOAD WHEN THEY ARE WANTED.
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. A DOB
 * inspector arrives without warning, taps Log Books, and waits.
 *
 * ── THE DEFECT, MEASURED ON PRODUCTION 2026-10-07 (588 Thomas) ────────────
 *
 * He waited ~TEN MINUTES, online, with no refresh control and no progress.
 * Through the real handler, the walk this screen performs to draw a list of
 * dates:
 *
 *     page  dates  recs        bytes     ms
 *        1     10     63     6452999   1546
 *        2     10     83     4043877    788
 *        3     10     71     2028208    536
 *        4     10     57     1598155    463
 *        5      3     15      240401    121
 *      TOT     43    289    14363640   3454
 *
 * 14,363,640 bytes. 14,122,753 of them — 98.3% — were `data`: the kiosk
 * worker-signature images on pre-shift sheets. THE SERVER WAS NOT SLOW. 3.4 s
 * of handler time for all five pages. The ten minutes was TRANSFER.
 *
 * And the list draws none of it. `identityRow` keeps `{id, log_type, status,
 * updated_at}` per log, and those same 43 dates and 289 records are 44,016
 * bytes — 0.306%. The tablet moved 326x the bytes its list needs.
 *
 * ── FOUR FAULTS, AND THIS FILE GUARDS THE FIX TO EACH ─────────────────────
 *
 *   A. THE LIST COST THE WHOLE CORPUS. The walk now asks `view=index` and
 *      refuses to commit anything if the server did not say it honoured it —
 *      an old server ignores an unknown query param and serves documents, and
 *      an index assembled out of those is an index nobody agreed to serve.
 *
 *   B. NOTHING RENDERED UNTIL EVERY PAGE LANDED. The walk reports each page as
 *      it arrives, with COUNTED numbers, before issuing the next request.
 *
 *   C. EVERYTHING WAS RE-FETCHED EVERY OPEN. The old walk rewrote every day's
 *      detail to disk on every open, unchanged or not. A day already held at
 *      its filed version is now not requested AT ALL — the headline assertion
 *      here is ZERO requests for a second open of an unchanged project.
 *
 *   D. IT COMPETED WITH A 105 MB EAGER DOWNLOAD. The manifest filler yields
 *      the link to a foreground read, BETWEEN files, and is deferred rather
 *      than cancelled: every file is still fetched.
 *
 * ── AND WHAT MAY NOT BE WEAKENED ──────────────────────────────────────────
 *
 * `siteLogbookHistory`'s completeness rule: nothing is committed unless the
 * walk completed, because `datesToList` names each day's full-day-report PDF
 * and `sweepDocCache` deletes every cached document that no stored list names.
 * A shrunken list is not a short screen, it is DELETED RECORDS. The index walk
 * is a second walk and it is held to the same rule here, clause for clause.
 *
 * Run:  node src/utils/siteLogbookIndex.test.cjs
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
function section(title) {
  console.log(`\n${title}`);
}

// ── a fake device: AsyncStorage + FileSystem + a routed server ─────────────
function makeDevice(opts) {
  const o = opts || {};
  const store = {};
  for (const scope of Object.keys(o.lists || {})) {
    store[`bv_doclist:${scope}`] = JSON.stringify(o.lists[scope]);
  }
  const docs = new Set(o.docs || []);
  const days = new Set(o.days || []);
  const dayBytes = Object.assign({}, o.dayBytes || {});
  const requests = [];
  const io = { sets: 0, dirsMade: [], dirReads: 0, writes: 0 };

  const dirOf = (uri) => {
    const parts = String(uri).split('/').filter(Boolean);
    return parts.length > 1 ? parts[parts.length - 2] : '';
  };
  const nameOf = (uri) => String(uri).split('/').pop();

  const netError = () => {
    const e = new Error('Network Error');
    e.request = {};
    return e;
  };

  const fetchedFiles = [];
  const rawDownload = async (url, dest) => {
    fetchedFiles.push({ url, name: nameOf(dest).replace(/\.part$/, '') });
    if (o.failDownload) return { status: 500, uri: null };
    docs.add(nameOf(dest));
    return { status: 200, uri: dest };
  };

  return {
    fetchedFiles,
    docs,
    days,
    dayBytes,
    store,
    requests,
    io,
    netError,
    listKeys: () => Object.keys(store).filter((k) => k.startsWith('bv_doclist:')),
    AsyncStorage: {
      getAllKeys: async () => Object.keys(store),
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => {
        io.sets += 1;
        if (o.failSetItemAfter !== undefined && io.sets > o.failSetItemAfter) {
          throw new Error('database or disk is full (code 13)');
        }
        store[k] = v;
      },
      removeItem: async (k) => { delete store[k]; },
    },
    FileSystem: {
      documentDirectory: o.noFs ? null : '/doc/',
      readDirectoryAsync: async (uri) => {
        io.dirReads += 1;
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
        io.writes += 1;
        const n = nameOf(uri);
        days.add(n);
        dayBytes[n] = contents;
      },
      getFreeDiskStorageAsync: async () => (o.freeBytes === undefined ? 1e10 : o.freeBytes),
      // ONE TRANSPORT, TWO ENTRY POINTS, and `moveAsync` is not optional.
      // cacheDocFile races a stall guard around a RESUMABLE task and writes to
      // a `.part` path it then renames; a double that offers only
      // downloadAsync leaves it calling undefined, and section E would then be
      // measuring a broken double rather than a deferred fill.
      createDownloadResumable: (url, dest, _options, onProgress) => ({
        cancelAsync: async () => {},
        downloadAsync: async () => {
          if (onProgress) onProgress({ totalBytesWritten: 1024 });
          return rawDownload(url, dest);
        },
      }),
      downloadAsync: rawDownload,
      moveAsync: async ({ from, to }) => {
        const src = nameOf(from);
        const dst = nameOf(to);
        if (!docs.has(src)) throw new Error(`ENOENT: ${src}`);
        docs.delete(src);
        docs.add(dst);
      },
    },
    // `route(url, nth)` answers each request. `null` is a network failure.
    apiClient: {
      defaults: { baseURL: 'https://api.test' },
      get: async (url) => {
        requests.push(url);
        const answer = o.route ? o.route(url, requests.length) : undefined;
        if (answer === null || answer === undefined) throw netError();
        return { data: answer };
      },
    },
  };
}

// ── module loader: the REAL docCache and the REAL chunked store ────────────
const HERE = __dirname;
const compiled = {};
function compile(file) {
  if (!compiled[file]) {
    const full = path.join(HERE, file);
    // A MISSING MODULE MUST NOT BE A STACK TRACE — against a tree without the
    // new module, an ENOENT would replace every named guarantee below with one
    // opaque error. Compile to empty and let the export check name them.
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
      return {
        Platform: { OS: device.__web ? 'web' : 'android' },
        AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) },
      };
    }
    if (spec === '@react-native-community/netinfo') {
      return {
        __esModule: true,
        default: { addEventListener: () => () => {}, fetch: async () => ({ isConnected: true }) },
      };
    }
    if (spec === './api') {
      return { __esModule: true, default: device.apiClient, getToken: async () => 'jwt' };
    }
    if (spec === './docCache') return load(device, 'docCache.js');
    if (spec === './siteManifestStore') return load(device, 'siteManifestStore.js');
    if (spec === './syncPriority') return load(device, 'syncPriority.js');
    // The deferral protocol. LOADED FOR REAL, not stubbed: it imports
    // nothing, so there is nothing to stub it for -- see
    // src/utils/signatureDeferral.js.
    if (spec === './signatureDeferral') return load(device, 'signatureDeferral.js');
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compile(file))(m, { exports: m }, shim);
  return m;
}
const hist = (d) => load(d, 'siteLogbookHistory.js');
const manifest = (d) => load(d, 'siteManifestStore.js');
const priority = (d) => load(d, 'syncPriority.js');

const PID = 'P1';

// ── fixtures ──────────────────────────────────────────────────────────────
//
// A log carries a FAT `data`, so an assertion about what the index costs is an
// assertion about real weight rather than about a field count. 3.5 KB is the
// shape of eight kiosk signatures, which is what a pre-shift sheet really is.
const FAT = 'x'.repeat(3584);

function log(i, type, date) {
  return {
    id: `lb_${type}_${i}`,
    _id: `lb_${type}_${i}`,
    log_type: type,
    date,
    status: 'submitted',
    cp_name: 'Casey CP',
    cache_version: `${date}T07_05_00r1`,
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

const datesOf = (o) => Object.keys(o).sort().reverse();

/** One page of the INDEX response: identity fields only, plus the echo. */
function indexPage(dates, nextBefore) {
  const out = {};
  for (const k of Object.keys(dates)) {
    out[k] = dates[k].map((l) => ({
      id: l.id, log_type: l.log_type, status: l.status, updated_at: l.updated_at,
    }));
  }
  const keys = Object.keys(out);
  return {
    dates: out,
    complete: nextBefore === null || nextBefore === undefined,
    next_before: nextBefore === undefined ? null : nextBefore,
    view: 'index',
    date_count: keys.length,
    log_count: keys.reduce((n, k) => n + out[k].length, 0),
  };
}

/** One page of the FULL response, which is what an old server serves. */
function fullPage(dates, nextBefore) {
  const keys = Object.keys(dates);
  return {
    dates,
    complete: nextBefore === null || nextBefore === undefined,
    next_before: nextBefore === undefined ? null : nextBefore,
    date_count: keys.length,
    log_count: keys.reduce((n, k) => n + dates[k].length, 0),
  };
}

/** One day's whole documents — the `?date=` read.
 *
 *  NO `view` KEY. The server echoes it only for a caller that asked for a mode;
 *  the default body's key set is PINNED by
 *  test_one_record_with_its_history.py because an installed tablet reads it. */
function dayPage(date, logs) {
  return {
    dates: { [date]: logs },
    complete: false,
    next_before: null,
    date_count: 1,
    log_count: logs.length,
  };
}

// The site MANIFEST response, for section E. Same shapes
// siteManifestStore.test.cjs uses: the WIRE row is compact `{id, v, s, e}`.
const wireRow = (id, v = 1, e = 'pdf', s = 100) => ({ id, v, s, e });
function manifestPage(files = [], logbooks = []) {
  return {
    project_id: 'P1',
    limit: 1000,
    files: { rows: files, skip: 0, total: files.length, has_more: false },
    logbooks: { rows: logbooks, skip: 0, total: logbooks.length, has_more: false },
    complete: true,
  };
}

const isIndexReq = (u) => u.includes('view=index');
const dateOfReq = (u) => (u.match(/[?&]date=([^&]+)/) || [])[1];

/**
 * A server that serves the index in pages and one day at a time. The ONE
 * fixture most cases below run against, so a request count is a request count
 * against a single consistent corpus.
 */
function serverFor(corpus, opts = {}) {
  const keys = datesOf(corpus);
  return (url) => {
    const d = dateOfReq(url);
    if (d) {
      if (opts.dayFails) return null;
      const logs = corpus[decodeURIComponent(d)];
      return dayPage(decodeURIComponent(d), opts.emptyDays ? [] : (logs || []));
    }
    const limit = Number((url.match(/[?&]limit=(\d+)/) || [])[1] || 0);
    const before = (url.match(/[?&]before=([^&]+)/) || [])[1];
    const remaining = before
      ? keys.filter((k) => k < decodeURIComponent(before))
      : keys;
    const page = remaining.slice(0, limit || remaining.length);
    const slice = {};
    for (const k of page) slice[k] = corpus[k];
    const next = page.length < remaining.length ? page[page.length - 1] : null;
    if (!isIndexReq(url) || opts.oldServer) return fullPage(slice, next);
    return indexPage(slice, next);
  };
}

const bytes = (o) => Buffer.byteLength(JSON.stringify(o));

// ── source pins ───────────────────────────────────────────────────────────
//
// STRIP COMMENTS FIRST. Assertions in this repo have been found passing on the
// comment that MENTIONED the thing they were looking for, so prose goes before
// anything is read out of the text.
function stripJs(src) {
  const out = [];
  let i = 0;
  const n = src.length;
  while (i < n) {
    const two = src.slice(i, i + 2);
    if (two === '/*') { const j = src.indexOf('*/', i + 2); i = j < 0 ? n : j + 2; continue; }
    if (two === '//') { const j = src.indexOf('\n', i); i = j < 0 ? n : j; continue; }
    const ch = src[i];
    if (ch === '"' || ch === "'" || ch === '`') {
      let j = i + 1;
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue; }
        if (src[j] === ch) break;
        j += 1;
      }
      out.push(src.slice(i, j + 1));
      i = j + 1;
      continue;
    }
    out.push(ch);
    i += 1;
  }
  return out.join('');
}
const readStripped = (rel) => {
  const full = path.join(HERE, rel);
  return fs.existsSync(full) ? stripJs(fs.readFileSync(full, 'utf8')) : '';
};

// ═══════════════════════════════════════════════════════════════════════════
async function main() {
  // ── 0. the parts exist and are named ─────────────────────────────────────
  section('0. THE MODULES NAME THEIR PARTS');
  {
    const d = makeDevice({});
    const M = hist(d);
    let missing = 0;
    for (const fn of ['fetchSubmittedIndex', 'syncLogbookIndex', 'ensureDayDetail',
      'heldDayDetails', 'backfillDayDetails', 'dayDetailPath',
      // The OLD walk stays, and it is reachable: it is the fallback for a
      // server that predates `view=index`. See section A.
      'fetchSubmittedHistory', 'syncLogbookHistory']) {
      const present = typeof M[fn] === 'function';
      ok(present, `siteLogbookHistory exports ${fn}()`);
      if (!present) missing += 1;
    }
    const P = priority(d);
    for (const fn of ['claimForeground', 'awaitQuiet', 'foregroundClaims',
      '__resetSyncPriority']) {
      const present = typeof P[fn] === 'function';
      ok(present, `syncPriority exports ${fn}()`);
      if (!present) missing += 1;
    }
    ok(M.INDEX_PAGE_DATES > M.HISTORY_PAGE_DATES,
      'the index page is wider than the document page — an index row is ~1 KB, '
      + 'a document ~334 KB, so the bound is memory rather than transfer');
    ok(M.INDEX_PROBE_DATES === M.HISTORY_PAGE_DATES,
      'but the FIRST index page is the document page size: an old server '
      + 'ignores `view` and serves documents, and page one is the only page '
      + 'asked before the server has said which it is');
    if (missing > 0) {
      console.log(`\n  ${passed} passed, ${failed} failed`);
      console.log('  (stopping: this tree has no logbook index read)');
      process.exit(1);
    }
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('A. THE LIST ASKS FOR THE INDEX, AND ONLY TAKES AN INDEX');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const corpus = history(43);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    ok(r.complete === true && r.ok === true && r.dates === 43,
      'the whole 43-date history arrives and the walk declares itself complete');
    ok(d.requests.length === 2,
      `the list costs TWO requests, not five pages of documents (got ${d.requests.length})`);
    ok(d.requests.every(isIndexReq),
      'and every one of them asked for view=index');
    ok(/limit=10(&|$)/.test(d.requests[0]) && /limit=500(&|$)/.test(d.requests[1]),
      'page one is the probe width and page two is the index width');
    ok(d.io.writes === 0,
      'AND THE WALK WROTE NO DAY DETAIL. The old walk rewrote all 43 days to '
      + 'disk on every open; this one has no documents to write');
    const rows = (await M.readHistoryIndex(PID)).rows;
    ok(rows.length === 43 && rows[0].logs.length === 2,
      'the committed index is the identity rows the list renders from');
    ok(rows.every((row) => row.logs.every((l) => !('data' in l))),
      'and no `data` reached AsyncStorage');
  }
  {
    // THE WEIGHT, AS A RATIO, ON THE SAME CORPUS.
    const corpus = history(43);
    const full = datesOf(corpus).reduce((n, k) => n + bytes(fullPage({ [k]: corpus[k] }, null)), 0);
    const idx = datesOf(corpus).reduce((n, k) => n + bytes(indexPage({ [k]: corpus[k] }, null)), 0);
    ok(idx * 20 < full,
      `the index is ${(100 * idx / full).toFixed(2)}% of the documents on this `
      + 'fixture — production measured 0.306%');
  }
  {
    // AN OLD SERVER. It ignores `view=index` and serves whole documents.
    const corpus = history(43);
    const d = makeDevice({ route: serverFor(corpus, { oldServer: true }) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    ok(r.complete === false && r.reason === 'index-unsupported',
      'a server that does not echo `view: index` is named as such rather than '
      + 'mistaken for one that honoured it');
    ok(d.requests.length === 1,
      'and the walk stops after ONE page — it does not go on asking a server '
      + 'that predates the parameter for 500 dates of documents at a time');
    ok(d.listKeys().length === 0,
      'NOTHING IS COMMITTED. An index assembled out of bodies the server did '
      + 'not agree to serve is not an index this walk may vouch for');
  }
  {
    // A SERVER THAT DECLARES NEITHER. The pre-#639 body was `{dates}` alone.
    const d = makeDevice({ route: () => ({ dates: history(3), view: 'index' }) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    ok(r.complete === false && r.reason === 'no-completeness-contract',
      'a body with neither `complete` nor `next_before` is not a whole history '
      + '— the silent-ceiling defect must not be rebuilt on the client');
    ok(d.listKeys().length === 0, 'and it commits nothing');
  }
  {
    // A DROPPED PAGE NEVER SHRINKS WHAT IS STORED.
    const corpus = history(43);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    await M.syncLogbookIndex(PID);
    const before = (await M.readHistoryIndex(PID)).rows.length;
    // Same AsyncStorage, new network: a device that already holds the history
    // and then loses the link mid-walk. The store is REPLAYED rather than
    // reassigned — makeDevice closes over its own object, so an assignment
    // would leave the module reading an empty one and the assertion would pass
    // for the wrong reason.
    const d2 = makeDevice({
      route: (url, n) => (n === 1 ? indexPage(history(5), '2026-12-24') : null),
    });
    for (const k of Object.keys(d.store)) d2.store[k] = d.store[k];
    const M2 = hist(d2);
    const r = await M2.syncLogbookIndex(PID);
    ok(r.complete === false && r.reason === 'unreachable',
      'a page that never reached a server is incompleteness, not an empty history');
    const after = (await M2.readHistoryIndex(PID)).rows.length;
    ok(after === before,
      `the stored list did not shrink (${before} -> ${after}) — a shrunken list `
      + 'is what makes sweepDocCache delete the offline PDFs');
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('B. EVERY PAGE IS REPORTED AS IT LANDS, IN COUNTED NUMBERS');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const corpus = history(43);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const seen = [];
    const r = await M.syncLogbookIndex(PID, {
      onPage: (p) => { seen.push({ pages: p.pages, dates: p.dates, rows: p.rows.length }); },
    });
    ok(seen.length === 2, 'the walk reported once per page');
    ok(seen[0].pages === 1 && seen[0].dates === 10 && seen[0].rows === 10,
      'the first report is the 10 dates that actually arrived, not an estimate');
    ok(seen[1].pages === 2 && seen[1].dates === 43,
      'and the second is the running total, counted off the rows assembled');
    ok(seen[seen.length - 1].dates === r.dates,
      'the last report agrees with what was committed — nothing is rounded up');
    const rising = seen.every((p, i) => i === 0 || p.dates >= seen[i - 1].dates);
    ok(rising, 'and it only ever goes up');
  }
  {
    // A PROGRESS CALLBACK MAY NOT FAIL A WALK.
    const corpus = history(12);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID, {
      onPage: () => { throw new Error('a render threw'); },
    });
    ok(r.complete === true && r.dates === 12,
      'a throwing progress callback does not cost the history');
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('C. A DAY IS FETCHED WHEN IT IS WANTED, AND ONLY ONCE');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const corpus = history(43);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows[0];
    const before = d.requests.length;

    const first = await M.ensureDayDetail(PID, row.date, row.cache_version, {
      expectLogs: row.logs.length,
    });
    ok(Array.isArray(first.logs) && first.logs.length === 2 && first.fetched === true,
      'a day not on the device is fetched');
    ok(d.requests.length === before + 1,
      'in exactly ONE request');
    const req = d.requests[d.requests.length - 1];
    ok(dateOfReq(req) === encodeURIComponent(row.date) && !isIndexReq(req),
      `and it asks for that one date (${req})`);
    ok(first.stored === true, 'and it lands on the filesystem');
    ok(bytes(dayPage(row.date, corpus[row.date])) * 10
       < datesOf(corpus).reduce((n, k) => n + bytes(fullPage({ [k]: corpus[k] }, null)), 0),
      'one day is an order of magnitude less than the corpus it used to cost');

    const n2 = d.requests.length;
    const second = await M.ensureDayDetail(PID, row.date, row.cache_version, {
      expectLogs: row.logs.length,
    });
    ok(d.requests.length === n2 && second.fetched === false,
      'THE SECOND OPEN OF THE SAME DAY TRANSFERS NOTHING — the version is part '
      + 'of the file name, so a hit means "this device holds this day as filed"');
    ok(JSON.stringify(second.logs) === JSON.stringify(first.logs),
      'and it is the same record');
  }
  {
    // AN AMENDMENT BETWEEN THE INDEX AND THE READ.
    //
    // The index says this day is at version V and the device holds nothing for
    // it. By the time the inspector taps it, somebody has filed a correction,
    // so the server answers with V2. The file must be named on WHAT ARRIVED:
    // storing the new documents under V is how a tablet comes to serve a
    // superseded record out of a file that claims to be the current one.
    const corpus = history(2);
    const date = datesOf(corpus)[0];
    const amended = corpus[date].map((l) => ({
      ...l, updated_at: `${date}T23:59:00+00:00`,
    }));
    const d = makeDevice({
      route: (url) => (dateOfReq(url)
        ? dayPage(date, amended)
        : serverFor(corpus)(url)),
    });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows.find((x) => x.date === date);
    ok(row.cache_version === `${date}T07:05:00+00:00`,
      'the index committed the version the server listed');
    const res = await M.ensureDayDetail(PID, date, row.cache_version, { expectLogs: 2 });
    ok(res.amended === true,
      'a day whose filed version moved since the index says so, rather than '
      + 'quietly serving one version under the other one\'s name');
    ok(res.version === `${date}T23:59:00+00:00`,
      'and the file is named on WHAT ARRIVED — storing new documents under the '
      + 'old name is how a tablet serves a superseded record as the current one');
    ok(d.days.has(M.dayDetailName(PID, date, `${date}T23:59:00+00:00`)),
      'so the file on disk carries the corrected version');
    ok(!d.days.has(M.dayDetailName(PID, date, row.cache_version)),
      'and nothing was written under the superseded one');
  }
  {
    // AN EMPTY ANSWER FOR A FILED DAY IS REFUSED.
    const corpus = history(3);
    const date = datesOf(corpus)[0];
    const d = makeDevice({ route: serverFor(corpus, { emptyDays: true }) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows.find((x) => x.date === date);
    const res = await M.ensureDayDetail(PID, date, row.cache_version, { expectLogs: 2 });
    ok(res.logs === null && res.reason === 'empty-for-a-filed-day',
      'NULL IS NOT AN EMPTY DAY. The index says two records were filed; an '
      + 'empty body means the index is stale, not that the day is blank');
    ok(res.stored === false && d.io.writes === 0,
      'and nothing is written, so "this filed day is empty" is never cached '
      + 'and served to an inspector');
  }
  {
    // OFFLINE: the caller already knows, and does not spend 60 s finding out.
    const corpus = history(3);
    const date = datesOf(corpus)[0];
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows.find((x) => x.date === date);
    const n = d.requests.length;
    const res = await M.ensureDayDetail(PID, date, row.cache_version, { offline: true });
    ok(res.logs === null && res.reason === 'not-held' && d.requests.length === n,
      'a caller that knows it is offline asks for nothing');
  }
  {
    // A DROPPED DAY IS NOT AN EMPTY DAY EITHER.
    const corpus = history(3);
    const date = datesOf(corpus)[0];
    const d = makeDevice({ route: serverFor(corpus, { dayFails: true }) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows.find((x) => x.date === date);
    const res = await M.ensureDayDetail(PID, date, row.cache_version, { expectLogs: 2 });
    ok(res.logs === null && res.reason === 'unreachable' && !!res.error,
      'an unreachable day reports unreachable, and the caller renders the '
      + '"not saved on this tablet" card rather than a blank day');
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('D. THE OFFLINE FILL: WHAT CHANGED, AND NOTHING ELSE');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const corpus = history(8);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const n0 = d.requests.length;
    const progress = [];
    const fill = await M.backfillDayDetails(PID, r.rows, {
      onProgress: (p) => progress.push({ ...p }),
    });
    ok(fill.complete === true && fill.held === 8 && fill.total === 8 && fill.fetched === 8,
      'a first fill holds every date in the committed index');
    ok(d.requests.length === n0 + 8, 'one request a date, no more');
    ok(progress[0].held === 0 && progress[0].total === 8,
      'the first progress report is a COUNT of what is on disk, which is none');
    ok(progress[progress.length - 1].held === 8,
      'and the last is a count of what landed');
    ok(progress.every((p) => p.total === 8),
      'the denominator is the committed index on every report — never a guess');
    ok(progress.every((p, i) => i === 0 || p.held >= progress[i - 1].held),
      'and the numerator only rises');

    // ── THE HEADLINE. A SECOND OPEN, NOTHING CHANGED. ────────────────────
    const n1 = d.requests.length;
    const again = await M.backfillDayDetails(PID, r.rows, {});
    ok(d.requests.length === n1 && again.fetched === 0,
      'A SECOND OPEN WITH NOTHING CHANGED FETCHES 0 OF 8 DAYS. This is fault 3: '
      + 'the old walk re-downloaded the whole corpus and rewrote every day');
    ok(again.held === 8 && again.complete === true,
      'and it still reports the device as whole');
    ok(d.io.dirReads <= 4,
      `the held count is ONE directory read, not one stat a date (${d.io.dirReads} `
      + 'reads across two fills)');
  }
  {
    // RESUMABLE AND BOUNDED.
    const corpus = history(8);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const first = await M.backfillDayDetails(PID, r.rows, { perRun: 3 });
    ok(first.fetched === 3 && first.reason === 'per-run-cap' && first.complete === false,
      'one run cannot occupy the device for ever');
    const second = await M.backfillDayDetails(PID, r.rows, { perRun: 3 });
    ok(second.fetched === 3 && second.held === 6,
      'and the next run resumes where it stopped, off the directory read');
    const third = await M.backfillDayDetails(PID, r.rows, { perRun: 3 });
    ok(third.held === 8 && third.complete === true, 'until the device is whole');
  }
  {
    // NEWEST FIRST, because that is what an inspector asks for.
    const corpus = history(5);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const n0 = d.requests.length;
    await M.backfillDayDetails(PID, r.rows, { perRun: 2 });
    const asked = d.requests.slice(n0).map((u) => decodeURIComponent(dateOfReq(u)));
    ok(JSON.stringify(asked) === JSON.stringify(datesOf(corpus).slice(0, 2)),
      `the newest dates are filled first (${asked.join(', ')})`);
  }
  {
    // IT STOPS ON THE FIRST UNREACHABLE DAY.
    const corpus = history(20);
    const d = makeDevice({ route: serverFor(corpus, { dayFails: true }) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const n0 = d.requests.length;
    const fill = await M.backfillDayDetails(PID, r.rows, {});
    ok(fill.reason === 'unreachable' && d.requests.length === n0 + 1,
      'a tablet that has gone into the dead zone does not spend twenty '
      + '60-second timeouts discovering it one date at a time');
    ok(fill.held === 0 && fill.complete === false,
      'and it reports the number it reached rather than rounding up');
  }
  {
    // THE YIELD IS AWAITED BEFORE EACH DOWNLOAD.
    const corpus = history(4);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const order = [];
    await M.backfillDayDetails(PID, r.rows, {
      beforeEach: async () => { order.push('yield'); },
    });
    ok(order.length === 4,
      'the fill offers the link back before every single day it fetches');
  }
  {
    // STOPPED ON A PROJECT CHANGE.
    const corpus = history(6);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const fill = await M.backfillDayDetails(PID, r.rows, { shouldStop: () => true });
    ok(fill.reason === 'stopped' && fill.fetched === 0,
      'a tablet re-provisioned to another job stops filling the old one');
  }
  {
    // WEB HAS NO FILESYSTEM, AND SAYS SO RATHER THAN REPORTING 0 OF 43.
    const d = makeDevice({ noFs: true, route: serverFor(history(4)) });
    d.__web = true;
    const M = hist(d);
    const rows = Object.keys(history(4)).map((date) => M.identityRow(PID, date, history(4)[date]));
    const held = await M.heldDayDetails(PID, rows);
    ok(held.readable === false && held.total === 4,
      '`readable` is not `held > 0`: a browser keeps no offline copies, and a '
      + 'progress bar that can never move is a device accused of failing');
    const fill = await M.backfillDayDetails(PID, rows, {});
    ok(fill.reason === 'no-filesystem' && fill.readable === false,
      'and the fill says the same rather than attempting it');
  }
  {
    // PRUNE STILL WORKS WHEN MOST DAYS HAVE NO FILE AT ALL.
    const corpus = history(6);
    const d = makeDevice({ route: serverFor(corpus) });
    const M = hist(d);
    const r = await M.syncLogbookIndex(PID);
    const row = r.rows[0];
    await M.ensureDayDetail(PID, row.date, row.cache_version, { expectLogs: 2 });
    const kept = M.dayDetailName(PID, row.date, row.cache_version);
    d.days.add(M.dayDetailName(PID, '2019-01-01', 'gone'));
    const removed = await M.pruneDayDetails(PID, r.rows);
    ok(removed === 1 && d.days.has(kept),
      'the prune reclaims a date the index no longer names and leaves the five '
      + 'dates with no file yet alone — an absent file has no name to delete');
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('E. THE PRIORITY GATE: THE FILL GOES SECOND, AND NEVER NEVER');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({});
    const P = priority(d);
    P.__resetSyncPriority();
    ok(P.foregroundClaims() === 0, 'nothing is claimed to begin with');
    ok((await P.awaitQuiet(5000)) === 'idle',
      'an idle tablet never waits — the fill starts immediately');

    const release = P.claimForeground('the-list');
    ok(P.foregroundClaims() === 1, 'a read claims the link');
    let settled = null;
    const waiting = P.awaitQuiet(5000).then((why) => { settled = why; });
    await new Promise((r2) => setImmediate(r2));
    ok(settled === null, 'and a fill waiting on it has NOT proceeded');
    release();
    await waiting;
    ok(settled === 'quiet',
      'releasing the claim releases the fill — the real event, not a timer');
    ok(release() === false, 'and releasing twice does not drop somebody else\'s claim');
  }
  {
    const d = makeDevice({});
    const P = priority(d);
    P.__resetSyncPriority();
    P.claimForeground('leaked');
    const why = await P.awaitQuiet(20);
    ok(why === 'timeout',
      'A LEAKED CLAIM COSTS ONE DEFERRAL, NOT A TABLET THAT STOPPED FILLING. '
      + 'A gate that can deadlock would leave a device holding nothing, and '
      + 'nothing on it would say so until an inspector asked in a cellar');
    ok(P.foregroundClaims() === 1,
      'and the cap does not forge a release it did not get');
    P.__resetSyncPriority();
  }
  {
    // THE MANIFEST FILLER ACTUALLY CALLS THE HOOK, BETWEEN FILES.
    const d = makeDevice({ route: () => manifestPage([wireRow('F1'), wireRow('F2')]) });
    const S = manifest(d);
    const order = [];
    const r = await S.syncSiteManifest(PID, {
      beforeEachDownload: async () => { order.push('yield'); },
    });
    ok(r.ok === true, 'the manifest run still completes');
    ok(order.length >= 2,
      `the fill offers the link back before each file (${order.length} yields) `
      + '— a run that checked only on entry would start before the screen did '
      + 'and then hold the radio for 105 MB regardless');
    ok(r.downloaded === 2,
      'AND EVERY FILE IS STILL FETCHED. The hook defers; it never cancels. '
      + 'The offline guarantee is the product');
  }
  {
    // AND WITHOUT THE HOOK IT BEHAVES EXACTLY AS IT DID.
    const d = makeDevice({ route: () => manifestPage([wireRow('F1')]) });
    const S = manifest(d);
    const r = await S.syncSiteManifest(PID);
    ok(r.ok === true && r.downloaded === 1,
      'a caller that passes no priority hook is unaffected — adminPlanPrefetch '
      + 'is a phone, not a gate tablet with an inspector in front of it');
  }

  // ═════════════════════════════════════════════════════════════════════════
  section('F. THE SCREEN AND THE LAYOUT ARE WIRED TO ALL OF IT');
  // ═════════════════════════════════════════════════════════════════════════
  {
    const screen = readStripped('../../app/site/logbooks.jsx');
    ok(screen.length > 0, 'the site logbooks screen is readable');
    ok(screen.includes('syncLogbookIndex('),
      'the screen loads its list through the INDEX walk');
    ok(screen.includes('ensureDayDetail('),
      'and reads a day through ensureDayDetail, which is what skips a day the '
      + 'device already holds');
    ok(screen.includes('backfillDayDetails('),
      'and still fills the device for the dead zone — WHEN, not WHETHER');
    ok(/reason === 'index-unsupported'/.test(screen)
      && screen.includes('syncLogbookHistory('),
      'and the old full-document walk is kept as the fallback for a server '
      + 'that predates `view=index`, so a deploy gap is slow rather than blank');
    ok(screen.includes('RefreshControl') && /onRefresh=/.test(screen),
      'pull-to-refresh exists');
    ok(/accessibilityLabel="Check for new filed records"/.test(screen),
      'and so does an explicit control, because this is a tablet operated with '
      + 'work gloves by somebody who has never seen the app');
    ok(screen.includes('claimForeground('),
      'the read claims the link, which is what defers the 105 MB filler');
    ok(/setListProgress\(\{\s*pages,\s*dates\s*\}\)/.test(screen),
      'THE PROGRESS NUMBERS COME OFF THE WALK, not off a timer: `pages` is '
      + 'responses returned and `dates` is rows assembled from them');
    ok(screen.includes('onProgress:') && /held\} of \$\{(offlineFill\.)?total\}/.test(screen),
      'and the offline fraction is the counted held/total, with no assumed '
      + 'denominator');
    ok(!/setInterval\(/.test(screen) && !/Animated\./.test(screen),
      'there is no animated or ticking progress anywhere on this screen');
  }
  {
    const layout = readStripped('../../app/_layout.jsx');
    ok(layout.length > 0, 'the root layout is readable');
    ok(layout.includes('beforeEachDownload') && layout.includes('awaitQuiet('),
      'SiteManifestSync passes the priority hook — the gate tablet is the '
      + 'machine with the problem and this is the only thing that starts the '
      + 'fill there');
    ok(/SITE_FILL_DEFERRAL_MS\s*=\s*\d+/.test(layout),
      'and the cap is a named number, not a literal buried in a call');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
