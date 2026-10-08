/**
 * A SHEET'S TEXT LOADS FIRST; ITS SIGNATURE IMAGES ARE A SECOND READ.
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. A DOB
 * inspector arrives without warning, taps Log Books, opens a date, and reads a
 * filed compliance record.
 *
 * ── WHERE THIS PICKS UP ───────────────────────────────────────────────────
 *
 * #681 made the LIST cost the index: 39,308 bytes and 167 ms for 43 dates,
 * against 14,363,640 bytes over five pages, and 0 of 43 days re-fetched on a
 * second open. Opening ONE DAY still cost that day's whole payload.
 *
 * ── THE REMAINING DEFECT, MEASURED ON PRODUCTION 2026-10-08 ───────────────
 *
 *     data.workers[].worker_signature          9,685,074 B   56.7%
 *     data.worker_signature  (orientation)     1,548,916 B    9.1%
 *     data.attendees[].worker_signature                0 B    0.0%
 *     data.attendees[].signature                       0 B    0.0%
 *     cp_signature.data                                0 B    0.0%
 *     ─────────────────────────────────────────────────────────────
 *     signature images                        11,233,990 B   65.8% of 17,080,794
 *
 * Per day, 43 dates and 339 records:
 *
 *                    lightest     median    heaviest
 *     today             4,691    361,525   1,440,691
 *     text only         4,691     99,491     592,243
 *
 * ── THE TRAP THIS FILE EXISTS TO HOLD SHUT ────────────────────────────────
 *
 * The pre-shift renderer keyed TWO blocks off one field:
 *
 *     workers.some(w => w.worker_signature)    -> draw the signature images
 *     workers.some(w => !w.worker_signature)   -> list those names as UNSIGNED
 *
 * So a payload that merely OMITTED the mark would tell a DOB inspector that
 * every one of the 505 men who signed at the kiosk had NOT signed. That is a
 * false statement on a legal record and it is worse than a slow screen. There
 * are THREE states — signed-and-here, signed-and-coming, did-not-sign — and
 * section A asserts that each reader answers all three.
 *
 * ── AND WHAT MAY NOT BE WEAKENED ──────────────────────────────────────────
 *
 *   THE OFFLINE GUARANTEE. The tablet must still END UP holding the ink for
 *   the dead zone. This change alters WHEN a signature arrives, never WHETHER:
 *   section E holds `backfillDayDetails` to fetching it, newest first, bounded,
 *   resumable, yielding — and to a SECOND run that makes zero requests.
 *
 *   THE SWEEP. `pruneDayDetails` deletes every `{projectId}_` name its
 *   keep-set does not hold. A keep-set built from day names alone would delete
 *   every signature file on the tablet on the first complete walk after one
 *   landed, and the fill would never finish. Section D is that assertion and
 *   it is the one that would have shipped broken.
 *
 * Run:  node src/utils/siteSignatureDeferral.test.cjs
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
function eq(got, want, label) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a === b) { passed += 1; console.log(`  PASS  ${label}`); }
  else {
    failed += 1;
    console.log(`  FAIL  ${label}\n          got  ${a}\n          want ${b}`);
  }
}
function section(title) { console.log(`\n${title}`); }

// ── THE SECTIONS RUN IN ORDER, AWAITED ────────────────────────────────────
//
// NOT fire-and-forget async IIFEs, which is what these were. Those resolve
// whenever they resolve, so a section that awaits a real read can report its
// failures AFTER the summary has already printed — the shape of a suite that
// cannot fail. Each section is queued and awaited in turn, and the summary is
// printed by the runner rather than by a process exit hook.
const SECTIONS = [];

// ── a fake device: a filesystem and a routed server ───────────────────────
function makeDevice(opts) {
  const o = opts || {};
  const days = new Set(o.days || []);
  const dayBytes = Object.assign({}, o.dayBytes || {});
  const requests = [];
  const io = { dirReads: 0, writes: 0, dirsMade: [] };
  const nameOf = (uri) => String(uri).split('/').pop();

  const netError = () => {
    const e = new Error('Network Error');
    e.request = {};
    return e;
  };

  return {
    days,
    dayBytes,
    requests,
    io,
    AsyncStorage: {
      getAllKeys: async () => [],
      getItem: async () => null,
      setItem: async () => {},
      removeItem: async () => {},
    },
    FileSystem: {
      documentDirectory: o.noFs ? null : '/doc/',
      readDirectoryAsync: async () => { io.dirReads += 1; return [...days]; },
      deleteAsync: async (uri) => {
        const n = nameOf(uri);
        days.delete(n);
        delete dayBytes[n];
      },
      getInfoAsync: async (uri) => {
        const n = nameOf(String(uri).replace(/\/$/, ''));
        if (n === 'site_logdays') {
          return { exists: io.dirsMade.includes('site_logdays'), isDirectory: true };
        }
        return days.has(n) ? { exists: true, size: 10 } : { exists: false, size: 0 };
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
        if (o.failWrite) throw new Error('ENOSPC');
        io.writes += 1;
        const n = nameOf(uri);
        days.add(n);
        dayBytes[n] = contents;
      },
      getFreeDiskStorageAsync: async () => 1e10,
      createDownloadResumable: () => ({
        cancelAsync: async () => {},
        downloadAsync: async () => ({ status: 200, uri: '/doc/x' }),
      }),
      downloadAsync: async () => ({ status: 200, uri: '/doc/x' }),
      moveAsync: async () => {},
    },
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

// ── module loader: the REAL module, not a description of it ───────────────
const HERE = __dirname;
const compiled = {};
function compile(file) {
  if (!compiled[file]) {
    const full = path.join(HERE, file);
    // A MISSING MODULE MUST NOT BE A STACK TRACE — against a tree without the
    // new exports an ENOENT would replace every named guarantee below with one
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

const PID = 'P1';
const DAY = '2026-09-28';
const STAMP = `${DAY}T07:05:00+00:00`;

// A data URI, which is what all 583 production marks are. A splice or a
// predicate that only handled bare base64 would pass a fixture using one and
// fail on every filed record.
const SIG = `data:image/png;base64,${'W'.repeat(4096)}`;
const ACK = `data:image/png;base64,${'A'.repeat(4096)}`;

/** A pre-shift sheet as `view=text` serves it: two marks DEFERRED, two men
 *  genuinely unsigned in the two shapes production holds. */
function preshiftText() {
  return {
    id: 'lb_preshift', _id: 'lb_preshift', log_type: 'preshift_signin',
    date: DAY, status: 'submitted', updated_at: STAMP,
    cache_version: STAMP,
    data: { workers: [
      { name: 'Signed One', worker_signature_deferred: true },
      { name: 'Unsigned Null', worker_signature: null },
      { name: 'Signed Two', worker_signature_deferred: true },
      { name: 'Unsigned Absent' },
    ] },
  };
}

/** The SAME sheet as a server that predates `view=text` serves it. */
function preshiftWhole() {
  return {
    id: 'lb_preshift', _id: 'lb_preshift', log_type: 'preshift_signin',
    date: DAY, status: 'submitted', updated_at: STAMP,
    cache_version: STAMP,
    data: { workers: [
      { name: 'Signed One', worker_signature: SIG },
      { name: 'Unsigned Null', worker_signature: null },
      { name: 'Signed Two', worker_signature: SIG },
      { name: 'Unsigned Absent' },
    ] },
  };
}

function orientationText() {
  return {
    id: 'lb_or', _id: 'lb_or', log_type: 'subcontractor_orientation',
    date: DAY, status: 'submitted', updated_at: STAMP, cache_version: STAMP,
    data: { worker_name: 'New Hire', worker_signature_deferred: true },
  };
}

function toolboxText() {
  return {
    id: 'lb_tb', _id: 'lb_tb', log_type: 'toolbox_talk',
    date: DAY, status: 'submitted', updated_at: STAMP, cache_version: STAMP,
    data: { attendees: [
      { name: 'A One', worker_signature_deferred: true },
      { name: 'A Two', signature_deferred: true },
      { name: 'A None', worker_signature: null, signature: null },
    ] },
  };
}

/** No mark anywhere — the record that must cost nothing. */
function dailyText() {
  return {
    id: 'lb_dj', _id: 'lb_dj', log_type: 'daily_jobsite',
    date: DAY, status: 'submitted', updated_at: STAMP, cache_version: STAMP,
    data: { weather: 'Sunny' },
  };
}

const INDEX_ROW = {
  date: DAY,
  id: `day_${PID}_${DAY}`,
  cache_version: STAMP,
  logs: [
    { id: 'lb_preshift', log_type: 'preshift_signin', status: 'submitted', updated_at: STAMP },
    { id: 'lb_dj', log_type: 'daily_jobsite', status: 'submitted', updated_at: STAMP },
  ],
};

// ═══════════════════════════════════════════════════════════════════════════
// THE EXPORTS, FIRST, SO EVERY GUARANTEE BELOW IS NAMED EVEN WHEN ABSENT
// ═══════════════════════════════════════════════════════════════════════════
section('0. the deferral protocol exists');
SECTIONS.push(async () => {
  const h = hist(makeDevice({}));
  for (const name of ['SIG_DEFERRED_SUFFIX', 'SIG_FIELDS', 'signatureMark',
                      'deferredSignaturePaths', 'dayHasDeferredSignatures',
                      'applySignatureImages', 'applyDaySignatureImages',
                      'signatureImagesPath', 'recordSignatureName',
                      'readRecordSignatures', 'writeRecordSignatures',
                      'ensureRecordSignatures', 'heldDaySignatures',
                      'fillDaySignatures']) {
    ok(h[name] !== undefined, `siteLogbookHistory exports ${name}`);
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// A. THREE STATES, NOT TWO
// ═══════════════════════════════════════════════════════════════════════════
section('A. three states, not two — the trap');
SECTIONS.push(async () => {
  const h = hist(makeDevice({}));
  if (!h.signatureMark) { console.log('  (protocol absent — A skipped)'); return; }
  const W = h.SIG_FIELDS.worker;
  const rows = preshiftText().data.workers;

  eq(h.signatureMark(rows[0], W).deferred, true, 'a deferred mark reports deferred');
  eq(h.signatureMark(rows[0], W).value, null, 'a deferred mark has no value');
  eq(h.signatureMark(rows[1], W), { value: null, deferred: false, field: null },
     'worker_signature: null is NOT SIGNED, not deferred');
  eq(h.signatureMark(rows[3], W), { value: null, deferred: false, field: null },
     'an absent key is NOT SIGNED, not deferred');
  eq(h.signatureMark(preshiftWhole().data.workers[0], W).value, SIG,
     'a present mark reports its bytes');

  // THE INVARIANT, NOT THE TWO SIDES. The UNSIGNED list the screen draws off a
  // TEXT body must be the SAME LIST it draws off a WHOLE body. Derived from
  // each body the way the screen derives it, and asserted equal.
  const unsignedOld = preshiftWhole().data.workers
    .filter((w) => !w.worker_signature).map((w) => w.name);
  const unsignedNew = preshiftText().data.workers
    .filter((w) => !h.signatureMark(w, W).value && !h.signatureMark(w, W).deferred)
    .map((w) => w.name);
  eq(unsignedNew, unsignedOld,
     'THE UNSIGNED LIST IS THE SAME LIST off a text body as off a whole one');
  eq(unsignedNew, ['Unsigned Null', 'Unsigned Absent'],
     'and it is the two men who really did not sign');

  // The old reader, run against the new body, to NAME what was avoided.
  const wouldHaveSaid = preshiftText().data.workers
    .filter((w) => !w.worker_signature).map((w) => w.name);
  ok(wouldHaveSaid.length === 4 && unsignedNew.length === 2,
     'the OLD reader on a text body would have called all 4 unsigned — which '
     + 'is the false statement this protocol exists to prevent');

  eq(h.signatureMark({ worker_signature: SIG, worker_signature_deferred: true }, W).value,
     SIG, 'a value present beside a flag WINS — never hide ink the device holds');

  const T = h.SIG_FIELDS.attendee;
  const att = toolboxText().data.attendees;
  eq(h.signatureMark(att[0], T).deferred, true, 'attendee worker_signature covered');
  eq(h.signatureMark(att[1], T).deferred, true, 'attendee signature covered');
  eq(h.signatureMark(att[2], T).deferred, false, 'an unsigned attendee stays unsigned');

  eq(h.signatureMark(orientationText().data, h.SIG_FIELDS.acknowledgment).deferred,
     true, 'the orientation acknowledgment is covered');
  eq(h.signatureMark({ worker_signature: null }, h.SIG_FIELDS.acknowledgment).deferred,
     false, 'a PRESENT-AND-NULL acknowledgment still reads UNSIGNED');
});

// ═══════════════════════════════════════════════════════════════════════════
// B. THE ADDRESSES, DERIVED FROM THE BODY
// ═══════════════════════════════════════════════════════════════════════════
section('B. the addresses come out of the body, never out of a promise');
SECTIONS.push(async () => {
  const h = hist(makeDevice({}));
  if (h.deferredSignaturePaths) {
    eq(h.deferredSignaturePaths(preshiftText()),
       ['data.workers.0.worker_signature', 'data.workers.2.worker_signature'],
       'the roster addresses are indexed');
    eq(h.deferredSignaturePaths(toolboxText()),
       ['data.attendees.0.worker_signature', 'data.attendees.1.signature'],
       'both attendee keys address separately');
    eq(h.deferredSignaturePaths(orientationText()), ['data.worker_signature'],
       'the acknowledgment addresses the scalar');
    eq(h.deferredSignaturePaths(dailyText()), [],
       'a record with no mark is owed nothing');
    // THE DEPLOY GAP NEEDS NO BRANCH. A whole-document body carries no flags,
    // so nothing is owed and nothing is fetched — the marks are already here.
    eq(h.deferredSignaturePaths(preshiftWhole()), [],
       'A WHOLE-DOCUMENT BODY IS OWED NOTHING — the deploy-gap fallback');
    eq(h.dayHasDeferredSignatures([dailyText(), preshiftText()]), true,
       'a day with one deferred record says so');
    eq(h.dayHasDeferredSignatures([dailyText()]), false,
       'a day with none says so');
    eq(h.dayHasDeferredSignatures([preshiftWhole()]), false,
       'and a whole-document day says so');
  } else { console.log('  (protocol absent — B skipped)'); }
});

// ═══════════════════════════════════════════════════════════════════════════
// C. THE SPLICE
// ═══════════════════════════════════════════════════════════════════════════
section('C. the splice puts the record back into the shape the screen knows');
SECTIONS.push(async () => {
  const h = hist(makeDevice({}));
  if (h.applySignatureImages) {
    const text = preshiftText();
    const out = h.applySignatureImages(text, {
      'data.workers.0.worker_signature': SIG,
      'data.workers.2.worker_signature': SIG,
    });
    // SPLICED, NOT PASSED ALONGSIDE: once the bytes are in hand the record is
    // byte-for-byte the shape this screen has always rendered, so the drawing
    // code for a loaded mark is the code that was already right.
    eq(out.data.workers, preshiftWhole().data.workers,
       'A SPLICED RECORD IS BYTE-FOR-BYTE THE WHOLE-DOCUMENT RECORD');
    eq(out.data.workers[0].worker_signature_deferred, undefined,
       'the flag is GONE with the splice — never image and notice at once');
    eq(h.deferredSignaturePaths(out), [], 'and nothing is owed afterwards');

    // COPY-ON-WRITE, both directions.
    eq(text.data.workers[0].worker_signature_deferred, true,
       'the input is not mutated');
    ok(out.data.workers[1] === text.data.workers[1],
       'an untouched roster row is the SAME OBJECT, not a copy');

    const d = dailyText();
    ok(h.applySignatureImages(d, {}) === d,
       'a record with nothing to splice is returned unchanged, identity included');
    ok(h.applySignatureImages(d, null) === d,
       'and a null map is an answer, not a crash');

    // A PATH NOTHING DEFERRED IS IGNORED. That is a server and a device
    // disagreeing about the record, and the stored document is the record.
    const sneak = h.applySignatureImages(dailyText(), {
      'data.workers.0.worker_signature': SIG,
    });
    eq(sneak.data.workers, undefined,
       'a path this body did not defer is IGNORED, never written');
    const nulled = h.applySignatureImages(preshiftText(), {
      'data.workers.1.worker_signature': SIG,
    });
    eq(nulled.data.workers[1].worker_signature, null,
       'and a man who did not sign cannot be given ink by a path');

    const or = h.applySignatureImages(orientationText(), {
      'data.worker_signature': ACK,
    });
    eq(or.data.worker_signature, ACK, 'the scalar acknowledgment splices');
    eq(or.data.worker_signature_deferred, undefined, 'and loses its flag');

    const day = h.applyDaySignatureImages([dailyText(), preshiftText()], {
      lb_preshift: { 'data.workers.0.worker_signature': SIG },
    });
    eq(day[1].data.workers[0].worker_signature, SIG, 'a day splices by log id');
    eq(day[0].data.weather, 'Sunny', 'and leaves the rest alone');
  } else { console.log('  (protocol absent — C skipped)'); }
});

// ═══════════════════════════════════════════════════════════════════════════
// D. THE SWEEP KEEPS THE INK  —  the assertion that would have shipped broken
// ═══════════════════════════════════════════════════════════════════════════
section('D. pruneDayDetails keeps the signature files');
SECTIONS.push(async () => {
  const h = hist(makeDevice({}));
  if (!h.recordSignatureName) { console.log('  (protocol absent — D skipped)'); return; }
  const dayName = h.dayDetailName(PID, DAY, STAMP);
  const sigA = h.recordSignatureName(PID, 'lb_preshift', STAMP);
  const sigB = h.recordSignatureName(PID, 'lb_dj', STAMP);
  const stale = h.recordSignatureName(PID, 'lb_withdrawn', STAMP);
  const other = h.recordSignatureName('P2', 'lb_preshift', STAMP);

  const d = makeDevice({ days: [dayName, sigA, sigB, stale, other] });
  const removed = await hist(d).pruneDayDetails(PID, [INDEX_ROW]);

  ok(d.days.has(dayName), 'the day detail survives');
  ok(d.days.has(sigA),
     'THE SIGNATURE FILE SURVIVES — without this the first complete walk after '
     + 'one landed would delete every mark on the tablet, and the fill would '
     + 'download them all again, for ever');
  ok(d.days.has(sigB), 'and so does the second record of the day');
  ok(!d.days.has(stale), 'a record the index no longer names is reclaimed');
  ok(d.days.has(other), "another project's file is left alone");
  eq(removed, 1, 'exactly one file was reclaimed');

  eq(h.recordSignatureName(PID, 'lb/../x', STAMP).includes('/'), false,
     'a record id cannot introduce a path separator');
  ok(h.recordSignatureName(PID, 'lb_preshift', STAMP)
     !== h.dayDetailName(PID, 'lb_preshift', STAMP),
     'a signature file cannot collide with a day detail file');
});

// ═══════════════════════════════════════════════════════════════════════════
// E. THE READS, AND WHAT THEY COST
// ═══════════════════════════════════════════════════════════════════════════
section('E. the day asks for text; the ink is a second read');
SECTIONS.push(async () => {
  const h0 = hist(makeDevice({}));
  if (!h0.signatureImagesPath) { console.log('  (protocol absent — E skipped)'); return; }

  ok(h0.dayDetailPath(PID, DAY).includes('view=text'),
     'the day read asks for view=text');
  ok(!h0.dayDetailPath(PID, DAY).includes('token'),
     'and carries no token in the URL');
  eq(h0.signatureImagesPath('lb_preshift'),
     '/api/logbooks/lb_preshift/signature-images',
     'the ink read is per RECORD');

  // the day read, text mode
  const dayBody = (view) => ({
    dates: { [DAY]: [preshiftText(), dailyText()] },
    complete: false, next_before: null, view,
  });

  {
    const d = makeDevice({ route: (u) => (u.includes('/submitted?') ? dayBody('text') : null) });
    const r = await hist(d).ensureDayDetail(PID, DAY, STAMP);
    eq(r.textView, true, 'ensureDayDetail reports a text body as one');
    eq(h0.deferredSignaturePaths(r.logs[0]).length, 2,
       'and the day it stored is owed two marks');
  }
  {
    // THE DEPLOY GAP, REPORTED NOT ASSUMED. A server without `view=text`
    // ignores it and serves whole documents, which render correctly.
    const d = makeDevice({
      route: (u) => (u.includes('/submitted?')
        ? { dates: { [DAY]: [preshiftWhole()] }, complete: false, next_before: null }
        : null),
    });
    const r = await hist(d).ensureDayDetail(PID, DAY, STAMP);
    eq(r.textView, false, 'a whole-document body is reported as NOT text');
    eq(h0.deferredSignaturePaths(r.logs[0]), [],
       'and nothing is owed, so nothing is fetched');
  }

  const sigBody = (version) => ({
    logbook_id: 'lb_preshift', version,
    signatures: { 'data.workers.0.worker_signature': SIG,
                  'data.workers.2.worker_signature': SIG },
    count: 2,
  });

  {
    const d = makeDevice({ route: (u) => (u.includes('/signature-images') ? sigBody(STAMP) : null) });
    const r = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP);
    eq(r.fetched, true, 'the ink is fetched when it is not held');
    eq(r.stored, true, 'and written to disk');
    eq(Object.keys(r.images).length, 2, 'two marks arrived');
    eq(d.requests.length, 1, 'ONE request for one record');

    // THE SECOND READ IS FREE. The version is in the file name, so a hit means
    // "this device holds this record's ink as filed" and nothing transfers.
    const before = d.requests.length;
    const again = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP);
    eq(d.requests.length - before, 0,
       'A SECOND READ OF HELD INK COSTS ZERO REQUESTS');
    eq(again.fetched, false, 'and says it came off the disk');
    eq(Object.keys(again.images).length, 2, 'with the marks intact');
  }
  {
    // THE AMENDMENT GUARD. Splicing a corrected mark into a superseded sheet,
    // or storing it under that sheet's name, is worse than waiting.
    const d = makeDevice({ route: (u) => (u.includes('/signature-images') ? sigBody('LATER') : null) });
    const r = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP);
    eq(r.stale, true, 'a record amended between the two reads reports stale');
    eq(r.images, null, 'and hands back no ink');
    eq(r.stored, false, 'and writes nothing');
    eq(d.io.writes, 0, 'nothing reached the disk');
  }
  {
    const d = makeDevice({ route: () => null });
    const r = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP);
    eq(r.reason, 'unreachable', 'the dead zone is reported');
    eq(r.images, null, 'and the flags are left standing');
  }
  {
    const d = makeDevice({});
    const r = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP,
                                                  { offline: true });
    eq(r.reason, 'not-held', 'a caller that knows it is offline is told at once');
    eq(d.requests.length, 0, 'and spends no 60-second timeout finding out');
  }
  {
    // A SERVER THAT DOES NOT HAVE THE ENDPOINT. Reported, never invented.
    const d = makeDevice({ route: () => ({ detail: 'Not Found' }) });
    const r = await hist(d).ensureRecordSignatures(PID, 'lb_preshift', STAMP);
    eq(r.reason, 'no-signatures', 'a body with no signatures key is reported');
    eq(r.images, null, 'and nothing is made up');
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// F. THE SHEET FILLS ONE SHEET AT A TIME
// ═══════════════════════════════════════════════════════════════════════════
section('F. the sheet at the top fills first');
SECTIONS.push(async () => {
  const h0 = hist(makeDevice({}));
  if (!h0.fillDaySignatures) { console.log('  (protocol absent — F skipped)'); return; }

  const byId = {
    lb_preshift: { 'data.workers.0.worker_signature': SIG,
                   'data.workers.2.worker_signature': SIG },
    lb_or: { 'data.worker_signature': ACK },
  };
  const route = (u) => {
    const m = /\/api\/logbooks\/([^/]+)\/signature-images/.exec(u);
    if (!m) return null;
    return { logbook_id: m[1], version: STAMP,
             signatures: byId[m[1]] || {}, count: 0 };
  };

  {
    const d = makeDevice({ route });
    const steps = [];
    const r = await hist(d).fillDaySignatures(
      PID, [preshiftText(), dailyText(), orientationText()],
      { onRecord: ({ fetched, owed }) => { steps.push(`${fetched}/${owed}`); } });
    eq(r.owed, 2, 'two of the three records are owed ink');
    eq(r.fetched, 2, 'and both arrived');
    eq(steps, ['1/2', '2/2'],
       'PROGRESSIVE: the caller is told after EACH sheet, not at the end');
    eq(d.requests.length, 2,
       'ONE request per owed record — the record with no mark costs nothing');
    eq(r.logs[0].data.workers, preshiftWhole().data.workers,
       'the first sheet is spliced');
    eq(r.logs[2].data.worker_signature, ACK, 'and so is the third');
    ok(r.logs[1] === undefined || r.logs[1].data.weather === 'Sunny',
       'and the record with no mark is untouched');
  }
  {
    // THE DEAD ZONE IS DISCOVERED ONCE, NOT ONCE A SHEET. Sixteen records at a
    // 60-second timeout is sixteen minutes of a screen saying it is loading.
    const d = makeDevice({ route: () => null });
    const r = await hist(d).fillDaySignatures(
      PID, [preshiftText(), orientationText(), toolboxText()]);
    eq(d.requests.length, 1, 'ONE request before it stops');
    eq(r.failed, 1, 'one failure reported');
    eq(h0.deferredSignaturePaths(r.logs[0]).length, 2,
       'and every sheet keeps its flags, so each says "signed, image not here"');
  }
  {
    const d = makeDevice({ route });
    const r = await hist(d).fillDaySignatures(PID, [dailyText()]);
    eq(r.owed, 0, 'a tab whose sheets have no marks is owed nothing');
    eq(d.requests.length, 0, 'and issues no request at all');
    ok(r.logs[0] === undefined || r.logs[0].id === 'lb_dj', 'and the logs come back');
  }
  {
    const d = makeDevice({ route });
    const r = await hist(d).fillDaySignatures(PID, [preshiftText(), orientationText()],
                                              { shouldStop: () => true });
    eq(d.requests.length, 0, 'a stop token is honoured before the first request');
    eq(r.fetched, 0, 'and nothing is fetched');
  }
  {
    const d = makeDevice({ route });
    const yields = [];
    await hist(d).fillDaySignatures(PID, [preshiftText(), orientationText()],
                                    { beforeEach: async () => { yields.push(1); } });
    eq(yields.length, 2, 'the link is yielded BETWEEN sheets, not once');
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// G. THE OFFLINE GUARANTEE — moved, never removed
// ═══════════════════════════════════════════════════════════════════════════
section('G. the tablet still ends up holding the ink');
SECTIONS.push(async () => {
  const h0 = hist(makeDevice({}));
  if (!h0.fillDaySignatures) { console.log('  (protocol absent — G skipped)'); return; }

  const day = [preshiftText(), dailyText()];
  const route = (u) => {
    if (u.includes('/submitted?')) {
      return { dates: { [DAY]: day }, complete: false, next_before: null, view: 'text' };
    }
    const m = /\/api\/logbooks\/([^/]+)\/signature-images/.exec(u);
    if (!m) return null;
    const sigs = m[1] === 'lb_preshift'
      ? { 'data.workers.0.worker_signature': SIG,
          'data.workers.2.worker_signature': SIG }
      : {};
    return { logbook_id: m[1], version: STAMP, signatures: sigs, count: 0 };
  };

  {
    const d = makeDevice({ route });
    const r = await hist(d).backfillDayDetails(PID, [INDEX_ROW]);
    eq(r.held, 1, 'the day text landed');
    eq(r.inkTotal, 2, 'two records are named by the index');
    eq(r.inkHeld, 2,
       'THE INK LANDED TOO — the offline guarantee, moved and not removed');
    eq(r.inkFetched, 1, 'one record was actually downloaded for it');
    eq(r.complete, true, 'and the fill reports itself complete');
    // the day, then the owed record. The record with no mark got an empty file
    // and no request.
    eq(d.requests.length, 2, 'two requests: one day, one owed record');

    // RESUMABLE, AND A SECOND RUN IS FREE. This is #681's headline assertion,
    // held to for the ink as well.
    const before = d.requests.length;
    const again = await hist(d).backfillDayDetails(PID, [INDEX_ROW]);
    eq(d.requests.length - before, 0,
       'A SECOND RUN WITH NOTHING CHANGED COSTS ZERO REQUESTS');
    eq(again.complete, true, 'and still reports complete');
    eq(again.inkHeld, 2, 'off ONE directory read, with no day JSON re-opened');
  }
  {
    // A day whose TEXT is here and whose INK is not is NOT a complete offline
    // record. A `complete` counting only the text would tell a tablet that
    // cannot show a single mark in the dead zone that it had finished.
    const d = makeDevice({
      route: (u) => (u.includes('/submitted?') ? route(u) : null),
    });
    const r = await hist(d).backfillDayDetails(PID, [INDEX_ROW]);
    eq(r.held, 1, 'the text landed');
    ok(r.inkHeld < r.inkTotal, 'the ink did not');
    eq(r.complete, false,
       'SO THE FILL IS NOT COMPLETE — both halves are counted');
    eq(r.reason, 'unreachable', 'and it says why');
  }
  {
    const d = makeDevice({ route, noFs: true });
    const r = await hist(d).backfillDayDetails(PID, [INDEX_ROW]);
    eq(r.readable, false,
       'on a surface with no filesystem the report says so, rather than 0 of 2');
    eq(d.requests.length, 0, 'and nothing is attempted');
  }
  {
    const d = makeDevice({ route });
    const yields = [];
    await hist(d).backfillDayDetails(PID, [INDEX_ROW],
                                     { beforeEach: async () => { yields.push(1); } });
    ok(yields.length >= 2,
       'the link is yielded before the day AND before each owed record');
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// H. THE SCREEN SAYS THE THIRD THING
// ═══════════════════════════════════════════════════════════════════════════
section('H. the screen draws three states and counts the ink');
SECTIONS.push(async () => {
  const SCREEN = path.join(HERE, '..', '..', 'app', 'site', 'logbooks.jsx');
  const raw = fs.existsSync(SCREEN) ? fs.readFileSync(SCREEN, 'utf8') : '';
  // PROSE OUT FIRST. This repo has had source-text assertions pass on a
  // comment that MENTIONED the thing they were looking for.
  const src = raw
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').map((l) => l.replace(/\/\/.*$/, '')).join('\n');

  ok(src.includes('signatureMark'), 'the screen reads marks through signatureMark');
  ok(src.includes('SIG_FIELDS'), 'and takes the key precedence from the module');
  ok(!src.includes("'_deferred'"),
     'and does not spell the suffix itself — one definition, see the module');
  ok(src.includes('Signature on file'),
     'a deferred mark says SIGNED ON THE RECORD, not just "loading"');
  ok(src.includes('fillDaySignatures'), 'the sheet fills its own ink');
  ok(src.includes('dayHasDeferredSignatures'),
     'and asks before it starts, so a day with no marks issues no request');
  ok(/signatures \$\{inkHeld\} of \$\{inkTotal\}/.test(src)
     || src.includes('signatures ${inkHeld} of ${inkTotal}'),
     'the offline line COUNTS THE INK SEPARATELY — "43 of 43 days" would have '
     + 'called a tablet with no marks on it finished');

  // THE CENSUS. Every signed-ness test on this screen must go through
  // `signatureMark`; one that reads the field itself is the UNSIGNED list
  // telling an inspector that a man who signed did not.
  const direct = [];
  const re = /(\w+)\.(worker_signature|signature)\b(?!_)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    const frag = src.slice(Math.max(0, m.index - 80), m.index + m[0].length + 10);
    if (frag.includes('data.worker_signature') || frag.includes('cp_signature')) continue;
    direct.push(`${src.slice(0, m.index).split('\n').length}: ${m[0]}`);
  }
  eq(direct, [],
     'NO RENDERER STILL TESTS THE MARK DIRECTLY (the two legitimate reads are '
     + "mark.value and the orientation block's own fallthrough)");
});

// ═══════════════════════════════════════════════════════════════════════════
// THE RUNNER. Drains the queue in file order and prints the summary itself.
//
// AND IT REFUSES TO REPORT A RUN THAT DID NOT HAPPEN. The first version of
// this file queued its sections and left a `process.on('exit')` hook to print
// the summary — so nothing drained the queue and it printed `0 passed, 0
// failed` and EXITED 0. A suite that passes by running none of itself is the
// instrument this repo keeps finding; the floor below is what makes that
// outcome a failure instead of a green line.
(async () => {
  for (const run of SECTIONS) {
    // A SECTION THAT THROWS IS A FAILURE, NOT A SILENT STOP.
    try { await run(); } catch (e) {
      failed += 1;
      console.log(`  FAIL  a section threw: ${e && e.message}`);
    }
  }
  // Sized on the count this file actually makes, as a FLOOR and not an
  // equality: a new assertion must not have to edit a number, and a file that
  // stopped making most of them must not read as green.
  const FLOOR = 90;
  if (passed + failed < FLOOR) {
    failed += 1;
    console.log(`  FAIL  only ${passed + failed - 1} assertions ran, under the `
      + `floor of ${FLOOR} — this suite did not run`);
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed > 0 ? 1 : 0;
})();
