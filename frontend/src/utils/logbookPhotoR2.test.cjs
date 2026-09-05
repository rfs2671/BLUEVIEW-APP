/**
 * PHOTOS LEAVE THE DOCUMENT — the device half.
 *
 * A logbook is ONE MongoDB document with a 16MB ceiling. handleSave used to
 * re-encode every photo to base64 on the way out, which at the client's own
 * 150KB compression cap is ~200KB apiece: ten subcontractors at ten photos
 * each is over 20MB, so the END-OF-DAY save was rejected outright, on a signed
 * record, after the CP had done the whole day. Photos now go to R2 as they are
 * TAKEN and the row carries only the key.
 *
 * The three guarantees that make that acceptable on a jobsite with no signal,
 * each exercised below against the REAL shipped source:
 *
 *   CAPTURE NEVER BLOCKS ON THE NETWORK.
 *   A PHOTO TAKEN OFFLINE IS NEVER LOST — it is a file in documentDirectory
 *     whose uri is in the draft, so it survives an app kill; the draft stays
 *     pending, so the reconnect drain retries the upload.
 *   THE CP NEVER SEES A BLANK TILE IN HIS OWN LOG — a row carries BOTH the
 *     local uri and `upload_pending`, and every reader falls back to the file.
 *
 * And the write those guarantees rest on: persistPhoto used to CATCH a failed
 * copy and return the OS cache uri, so the draft recorded a photo the app did
 * not own, the cache was evicted, and the photo was gone with nothing anywhere
 * having reported it. That is asserted here as its own section.
 *
 * The repo has no JS test runner (see RiskScoreCircle.bandFor.test.cjs), so
 * the ESM modules are read, stripped and evaluated under bare node with tiny
 * stubs — the same technique dailyJobsiteFinalizeRefusal.test.cjs uses. What
 * runs is the shipped code, never a hand-copy.
 *
 * Run:  node src/utils/logbookPhotoR2.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const UTILS = __dirname;
const FRONTEND = path.join(__dirname, '..', '..');
const I18N = path.join(FRONTEND, 'src', 'i18n');
const EDITOR = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const KIOSK = path.join(FRONTEND, 'app', 'site', 'logbooks.jsx');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function section(title) { console.log(`\n── ${title} ${'─'.repeat(Math.max(0, 62 - title.length))}`); }

const LF = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');
const draftsSrc = LF(path.join(UTILS, 'logbookDrafts.js'));
const syncSrc = LF(path.join(UTILS, 'draftSync.js'));
const editorSrc = LF(EDITOR);
const kioskSrc = LF(KIOSK);

const strip = (src) => src
  .replace(/^import[\s\S]*?;\s*$/gm, '')
  .replace(/^export (async function|function|const|class) /gm, '$1 ');

// ════════════════════════════════════════════════════════════════════════════
//  logbookDrafts — the REAL module, over an in-memory device
// ════════════════════════════════════════════════════════════════════════════

/**
 * @param copyFails  make FileSystem.copyAsync reject (the eviction bug's cause)
 * @param upload     (url, form, cfg) => response | throws
 */
function loadDrafts({ copyFails = false, upload = null, store = {} } = {}) {
  const copies = [];
  const posts = [];
  const env = {
    AsyncStorage: {
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
    },
    Platform: { OS: 'ios' },
    FileSystem: {
      documentDirectory: 'file:///docs/',
      getInfoAsync: async () => ({ exists: true }),
      makeDirectoryAsync: async () => {},
      copyAsync: async ({ from, to }) => {
        copies.push({ from, to });
        if (copyFails) throw new Error('ENOSPC: no space left on device');
      },
    },
    apiClient: {
      post: async (url, form, cfg) => {
        posts.push({ url, form, cfg });
        if (!upload) throw new Error('no upload stub');
        return upload(url, form, cfg);
      },
    },
    // The app-wide predicate, real, so "offline" here is what it is elsewhere.
    isOfflineError: (e) => {
      if (!e) return false;
      if (e.response) return false;
      return Boolean(e.offline);
    },
    FormData: class {
      constructor() { this.parts = {}; }
      append(k, v) { this.parts[k] = v; }
    },
    fetch: async () => ({ blob: async () => 'BLOB' }),
  };
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const Platform = __env.Platform;
    const FileSystem = __env.FileSystem;
    const apiClient = __env.apiClient;
    const isOfflineError = __env.isOfflineError;
    const FormData = __env.FormData;
    const fetch = __env.fetch;
    ${strip(draftsSrc)}
    return {
      persistPhoto, persistActivityPhotos, hasDurableCopy, photoPersistError,
      photoNeedsUpload, uploadCapturePhoto, uploadPendingActivityPhotos,
      hasPendingPhotoUploads, draftKey, readDraft, writeDraft, markPending,
      getPendingKeys, clearPending,
    };
  `)(env);
  return { ...mod, copies, posts, store };
}

const okUpload = (key) => async (url, form) => ({
  data: { original_r2_key: key || `logbook-photos/proj1/${form.parts.activity_id}/${form.parts.photo_id}.jpg` },
});
const offlineUpload = () => { const e = new Error('Network Error'); e.offline = true; throw e; };
const statusUpload = (code) => () => {
  const e = new Error(`HTTP ${code}`);
  e.response = { status: code };
  throw e;
};

// ════════════════════════════════════════════════════════════════════════════
section('persistPhoto NO LONGER FAILS SILENTLY');
// ════════════════════════════════════════════════════════════════════════════

(async () => {
  {
    const D = loadDrafts();
    const out = await D.persistPhoto('file:///cache/IMG_1.jpg', 'cap_1');
    ok(out.startsWith('file:///docs/logbook_photos/'),
      'a capture is copied into documentDirectory and the PERSISTENT uri returned');
    ok(D.copies.length === 1, 'exactly one copy per source uri');
    const again = await D.persistPhoto('file:///cache/IMG_1.jpg', 'cap_1');
    ok(again === out && D.copies.length === 1,
      'the same source uri is not re-copied (the autosave latency fix stands)');
  }

  {
    const D = loadDrafts({ copyFails: true });
    let threw = null;
    try { await D.persistPhoto('file:///cache/IMG_1.jpg', 'cap_1'); } catch (e) { threw = e; }
    ok(threw !== null,
      'THE REGRESSION: a failed copy THROWS instead of returning the cache uri');
    ok(threw && threw.sourceUri === 'file:///cache/IMG_1.jpg' && threw.code === 'PHOTO_PERSIST_FAILED',
      'the failure names the photo it lost, so a caller can act on it');
    ok(!/return uri; \/\/ fall back to the original uri if the copy fails/.test(draftsSrc),
      'source: the swallow-and-return-the-cache-uri branch is gone entirely');
  }

  {
    const D = loadDrafts({ copyFails: true });
    const kept = await D.persistPhoto('file:///docs/logbook_photos/cap_1.jpg', 'cap_1');
    ok(kept === 'file:///docs/logbook_photos/cap_1.jpg' && D.copies.length === 0,
      'an already-persistent uri is returned untouched and never re-copied');
  }

  // ── the draft writer must never record a uri it cannot prove it owns ──────
  {
    const D = loadDrafts({ copyFails: true });
    const rows = [{
      activity_id: 'act_1',
      photos: [
        { id: 'cap_1', uri: 'file:///cache/IMG_1.jpg', base64: 'RlVMTA==' },
      ],
    }];
    const out = await D.persistActivityPhotos(rows);
    const p = out[0].photos[0];
    ok(p.uri === undefined,
      'a photo whose copy failed is NOT recorded with the cache uri');
    ok(p.persist_failed === true,
      'it is FLAGGED instead, so the editor can tell the CP to retake it');
    ok(p.base64 === undefined,
      'and base64 is still never written into the draft (AsyncStorage size cap)');
  }

  {
    const D = loadDrafts({ copyFails: true });
    const rows = [{
      activity_id: 'act_1',
      photos: [
        // A photo that round-tripped from the server: its uri is a path on a
        // DIFFERENT device, so the copy failing means nothing.
        { id: 'cap_9', uri: 'file:///other-phone/IMG_9.jpg', thumb_base64: 'VEhVTUI=' },
        { id: 'cap_8', uri: 'file:///other-phone/IMG_8.jpg', original_r2_key: 'logbook-photos/p/a/c.jpg' },
      ],
    }];
    const out = await D.persistActivityPhotos(rows);
    ok(out[0].photos.every((p) => p.persist_failed === undefined),
      'a photo with a DURABLE copy is not flagged — no false "photo not saved" alarm');
    ok(out[0].photos.every((p) => p.uri === undefined),
      'its dead foreign path is dropped rather than carried forward');
    ok(out[0].photos[0].thumb_base64 === 'VEhVTUI='
      && out[0].photos[1].original_r2_key === 'logbook-photos/p/a/c.jpg',
      'and the copies that DO exist are untouched');
  }

  {
    const D = loadDrafts({ copyFails: true });
    let threw = false;
    try {
      await D.persistActivityPhotos([{ photos: [{ id: 'c1', uri: 'file:///cache/a.jpg' }] }]);
    } catch (_e) { threw = true; }
    ok(!threw,
      'persistActivityPhotos never throws: one bad photo cannot take the draft write down');
  }

  // ── the CP is told, bilingually, and is not blocked ───────────────────────
  section('THE CP IS TOLD, AND IS NOT BLOCKED');

  ok(/toast\.error\(t\('photoNotSavedTitle'\), t\('photoNotSavedBody'\)\)/.test(editorSrc),
    'editor: a failed persist raises a toast naming the photo that did not save');
  ok(/setActivities\(\(prev\) => dropPhoto\(prev, id\)\)/.test(editorSrc),
    'editor: and the photo is REMOVED, so nothing on screen claims evidence that does not exist');
  {
    // The catch must fall through to a plain `return`, never a throw: a photo
    // that would not save must not stop the CP finishing his log.
    const at = editorSrc.indexOf('let localUri = photo.uri;');
    const block = editorSrc.slice(at, editorSrc.indexOf('try {', editorSrc.indexOf('if (localUri !== photo.uri)')));
    ok(!/throw /.test(block),
      'editor: it does not rethrow — the CP is informed, not blocked');
  }
  {
    const load = (f) => {
      const body = fs.readFileSync(path.join(I18N, f), 'utf8')
        .replace(/^import .*$/gm, '')
        .replace(/^export default /m, 'const __default = ');
      // eslint-disable-next-line no-new-func
      return new Function(`${body} return __default;`)();
    };
    const en = load('en.js').dailyJobsite;
    const es = load('es.js').dailyJobsite;
    ok(Boolean(en.photoNotSavedTitle && en.photoNotSavedBody),
      'copy: the retake message exists');
    // EN-ONLY BY RULING. A logbook is a legal record filed with the DOB and is
    // written in English; Spanish belongs where a WORKER must understand what
    // he is signing. This toast is CP-facing. Asserted as an absence rather
    // than dropped, so a translation cannot quietly reappear — and translate()
    // falls back to English, so a Spanish-locale CP still reads it.
    ok(es === undefined,
      'copy: the dailyJobsite namespace is absent from the ES catalogue');
    ok(/again/i.test(en.photoNotSavedBody),
      'copy: it tells the CP what to DO about it — take it again');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('THE UPLOAD, AND WHAT IT DOES WHEN THERE IS NO NETWORK');
  // ══════════════════════════════════════════════════════════════════════════

  const rows = () => ([
    { activity_id: 'act_1', photos: [
      { id: 'cap_1', uri: 'file:///docs/logbook_photos/1.jpg' },
      { id: 'cap_2', uri: 'file:///docs/logbook_photos/2.jpg' },
    ] },
    { activity_id: 'act_2', photos: [
      { id: 'cap_3', uri: 'file:///docs/logbook_photos/3.jpg' },
    ] },
  ]);

  {
    const D = loadDrafts();
    ok(D.photoNeedsUpload({ id: 'c', uri: 'file:///docs/1.jpg' }) === true,
      'a photo with only a local file needs uploading');
    ok(D.photoNeedsUpload({ original_r2_key: 'k', uri: 'file:///docs/1.jpg' }) === false,
      'a photo already in R2 does not');
    ok(D.photoNeedsUpload({ base64: 'RlVMTA==' }) === false
      && D.photoNeedsUpload({ thumb_base64: 'VEhVTUI=' }) === false,
      'nor does an existing inline photo the backfill has not moved yet');
    ok(D.photoNeedsUpload({ persist_failed: true }) === false,
      'nor one that never made it onto the device');
  }

  {
    const D = loadDrafts({ upload: okUpload() });
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(r.uploaded === 3 && r.remaining === 0 && r.offline === false,
      'online: every pending photo uploads');
    const all = r.activities.flatMap((a) => a.photos);
    ok(all.every((p) => p.original_r2_key) && all.every((p) => p.upload_pending === undefined),
      'each row gets its key and drops the pending marker');
    ok(all[0].original_r2_key === 'logbook-photos/proj1/act_1/cap_1.jpg',
      'the key is (project_id, activity_id, photo_id) — no logbook id, no position');
    ok(D.posts[0].url === '/api/projects/proj1/logbook-photo',
      'it posts to the project-scoped upload endpoint');
    ok(D.posts[0].form.parts.activity_id === 'act_1' && D.posts[0].form.parts.photo_id === 'cap_1',
      'and sends both ids the server needs to build the key');
  }

  {
    const D = loadDrafts({ upload: offlineUpload });
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(r.uploaded === 0 && r.offline === true && r.remaining === 3,
      'offline: nothing uploads and all three are reported still pending');
    ok(D.posts.length === 1,
      'THE LOOP STOPS at the first offline failure — the CP does not wait out 100 timeouts');
    const all = r.activities.flatMap((a) => a.photos);
    ok(all.every((p) => p.uri && p.uri.startsWith('file:///docs/')),
      'NEVER LOST: every photo keeps its documentDirectory uri');
    ok(all[0].upload_pending === true,
      'and the row carries the pending marker the readers fall back on');
  }

  {
    const D = loadDrafts({ upload: statusUpload(503) });
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(D.posts.length === 1 && r.remaining === 3,
      'a 5xx stops the loop too: storage is down for all of them, not for one');
    ok(r.activities[0].photos[0].upload_rejected === undefined,
      'and NOTHING is marked rejected — the photo is fine, the world is not');
  }

  {
    let n = 0;
    const D = loadDrafts({
      upload: (url, form) => {
        n += 1;
        if (n === 1) { const e = new Error('bad'); e.response = { status: 400 }; throw e; }
        return okUpload()(url, form);
      },
    });
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(r.uploaded === 2, 'a 4xx names ONE photo, so its siblings still upload');
    ok(r.activities[0].photos[0].upload_rejected === true,
      'the refused photo is marked so it is not retried forever');
    ok(r.activities[0].photos[0].uri === 'file:///docs/logbook_photos/1.jpg',
      'and it KEEPS its local file, so the CP still sees it in his own log');
  }

  {
    const D = loadDrafts({ upload: okUpload() });
    ok(D.hasPendingPhotoUploads(rows()) === true,
      'hasPendingPhotoUploads sees a photo with no key');
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(D.hasPendingPhotoUploads(r.activities) === false,
      'and stops once every photo has one');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('SURVIVES THE APP BEING KILLED, AND THE RECONNECT DRAIN');
  // ══════════════════════════════════════════════════════════════════════════

  {
    // The CP shoots three photos in a dead zone and saves. The device is the
    // AsyncStorage `store` below; killing the app is modelled by throwing the
    // module away and loading a fresh one over the SAME store.
    const device = {};
    const D1 = loadDrafts({ upload: offlineUpload, store: device });
    const key = D1.draftKey({ projectId: 'proj1', logType: 'daily_jobsite', date: '2026-08-07' });
    const persisted = await D1.persistActivityPhotos(rows());
    const offline = await D1.uploadPendingActivityPhotos('proj1', persisted);
    await D1.writeDraft(key, { data: { activities: offline.activities } });
    await D1.markPending(key);

    // ── app killed ──
    const D2 = loadDrafts({ upload: okUpload(), store: device });
    const back = await D2.readDraft(key);
    const photos = back.data.activities.flatMap((a) => a.photos);
    ok(photos.length === 3, 'after an app kill the draft still holds all three photos');
    ok(photos.every((p) => p.uri && p.uri.startsWith('file:///docs/')),
      'each still points at a real file in documentDirectory');
    ok(photos.every((p) => p.upload_pending === true),
      'and each still says its upload has not landed');
    ok((await D2.getPendingKeys()).includes(key),
      'the draft is in the pending index, so the reconnect drain will find it');

    // ── reconnect ──
    const drained = await D2.uploadPendingActivityPhotos('proj1', back.data.activities);
    ok(drained.uploaded === 3 && drained.remaining === 0,
      'RETRIED ON RECONNECT: the failed uploads go through on the next attempt');
    ok(drained.activities.flatMap((a) => a.photos).every((p) => p.original_r2_key),
      'and every photo taken offline now has its R2 key');
  }

  {
    // The retry must be idempotent, or every failed attempt leaks an object.
    const seen = [];
    const D = loadDrafts({ upload: (url, form) => { seen.push(form.parts.photo_id); return okUpload()(url, form); } });
    await D.uploadPendingActivityPhotos('proj1', rows());
    const D2 = loadDrafts({ upload: (url, form) => { seen.push(form.parts.photo_id); return okUpload()(url, form); } });
    await D2.uploadPendingActivityPhotos('proj1', rows());
    ok(seen.length === 6 && new Set(seen).size === 3,
      'a retry re-sends the SAME photo id, so the server overwrites one object rather than orphaning six');
  }

  // ── draftSync: the drain uploads before it pushes ─────────────────────────
  {
    const posted = [];
    const uploads = [];
    let pendingCleared = 0;
    const draft = {
      data: { activities: [{ activity_id: 'act_1', photos: [
        { id: 'cap_1', uri: 'file:///docs/1.jpg' },
      ] }] },
      cp_signature: null, cp_name: 'Casey', status: 'draft', backend_id: 'lb1', finalized: false,
    };
    // THE DRAIN, LOADED. This is the one draftSync harness that DID declare
    // writeDraft and uploadPendingActivityPhotos -- because the photo branch is
    // exactly what it exercises. The two gate harnesses declared neither and
    // passed only by not reaching them.
    const sync = loadEsm('src/utils/draftSync.js', {
      globals: { console: { log: () => {}, warn: () => {} } },
      stubs: {
        '@react-native-async-storage/async-storage': {
          getItem: async () => null, setItem: async () => {},
        },
        '@react-native-community/netinfo': { addEventListener: () => () => {} },
        './api': {
          logbooksAPI: {
            update: async (id, body) => { posted.push(body); }, finalize: async () => {},
          },
        },
        './logbookDrafts': {
          // draftSync -> logbookTiming (isVisitLog) -> markFinalized.
          markFinalized: async () => {},
          getPendingKeys: async () => ['logbook_draft:proj1:daily_jobsite:2026-08-07'],
          readDraft: async () => draft,
          setDraftBackendId: async () => {},
          clearPending: async () => { pendingCleared += 1; },
          writeDraft: async () => true,
          uploadPendingActivityPhotos: async (projectId, activities) => {
            uploads.push(projectId);
            return {
              activities: activities.map((a) => ({
                ...a, photos: a.photos.map((p) => ({ ...p, original_r2_key: `k/${p.id}` })),
              })),
              uploaded: 1, remaining: 0, offline: false,
            };
          },
        },
      },
    });

    const r = await sync.syncPendingDrafts();
    ok(uploads[0] === 'proj1',
      'drain: the photos are uploaded BEFORE the content push, for the project the key names');
    ok(posted[0].data.activities[0].photos[0].original_r2_key === 'k/cap_1',
      'drain: the document the server receives NAMES its photo instead of describing it as pending');
    ok(r.synced === 1 && pendingCleared === 1,
      'drain: with every photo uploaded the key leaves the pending index');
  }

  {
    // ...and does NOT leave it when a photo is still stuck.
    let pendingCleared = 0;
    const draft = {
      data: { activities: [{ activity_id: 'act_1', photos: [{ id: 'cap_1', uri: 'file:///docs/1.jpg' }] }] },
      cp_signature: null, cp_name: 'Casey', status: 'draft', backend_id: 'lb1', finalized: false,
    };
    const sync = loadEsm('src/utils/draftSync.js', {
      globals: { console: { log: () => {}, warn: () => {} } },
      stubs: {
        '@react-native-async-storage/async-storage': {
          getItem: async () => null, setItem: async () => {},
        },
        '@react-native-community/netinfo': { addEventListener: () => () => {} },
        './api': { logbooksAPI: { update: async () => {}, finalize: async () => {} } },
        './logbookDrafts': {
          // draftSync -> logbookTiming (isVisitLog) -> markFinalized.
          markFinalized: async () => {},
          getPendingKeys: async () => ['logbook_draft:proj1:daily_jobsite:2026-08-07'],
          readDraft: async () => draft,
          setDraftBackendId: async () => {},
          clearPending: async () => { pendingCleared += 1; },
          writeDraft: async () => true,
          uploadPendingActivityPhotos: async (p, acts) => ({
            activities: acts, uploaded: 0, remaining: 1, offline: true,
          }),
        },
      },
    });
    await sync.syncPendingDrafts();
    ok(pendingCleared === 0,
      'drain: a photo still waiting KEEPS the draft pending, so something tries again');
  }

  ok(/if \(hasPendingPhotoUploads\(_uploaded\.activities\)\) await markPending\(_key\)/.test(editorSrc),
    'editor: a save whose content pushed but whose photos did not stays pending too');

  // ══════════════════════════════════════════════════════════════════════════
  section('THE DOCUMENT: 10 SUBCONTRACTORS x 10 PHOTOS');
  // ══════════════════════════════════════════════════════════════════════════

  // The REAL payload mapper out of the shipped screen.
  function sliceDecl(src, name, terminator) {
    const at = src.indexOf(`const ${name} = `);
    if (at < 0) throw new Error(`${name} not found — this test is stale`);
    const end = src.indexOf(terminator, at);
    if (end < 0) throw new Error(`${name}: no terminator`);
    return src.slice(at, end + terminator.length);
  }
  // eslint-disable-next-line no-new-func
  const { photoForPayload } = new Function(`
    ${sliceDecl(editorSrc, 'isPurgedPhoto', '\n);\n')}
    ${sliceDecl(editorSrc, 'photoForPayload', '\n};\n')}
    return { photoForPayload };
  `)();

  const MONGO_MAX = 16 * 1024 * 1024;
  const SUBS = 10;
  const PER_SUB = 10;
  // compressPhoto.js caps a capture at 150KB of JPEG; base64 inflates by 4/3.
  const FULL_B64 = 'A'.repeat(Math.ceil((150 * 1024) / 3) * 4);

  const day = (inline) => Array.from({ length: SUBS }, (_, ai) => ({
    activity_id: `act_1754500000000_${ai}`,
    subcontractor_id: `srv_${ai}`,
    company: `Sub ${ai}`,
    num_workers: '4',
    work_description: 'shoring',
    work_locations: 'cellar',
    photos: Array.from({ length: PER_SUB }, (_, pi) => ({
      id: `cap_1754500000000_${ai}_${pi}`,
      pending: false,
      uri: `file:///docs/logbook_photos/${ai}_${pi}.jpg`,
      timestamp: '2026-08-07T13:00:00.000Z',
      ...(inline
        ? { base64: FULL_B64 }
        : { original_r2_key: `logbook-photos/proj1/act_1754500000000_${ai}/cap_1754500000000_${ai}_${pi}.jpg` }),
    })),
  }));

  const payloadOf = (acts) => ({
    project_id: 'proj1',
    log_type: 'daily_jobsite',
    date: '2026-08-07',
    data: {
      project_address: '1 Test Plaza, Brooklyn NY',
      weather: 'Sunny',
      general_description: 'Shoring and slab prep.',
      activities: acts.map((a) => ({ ...a, photos: a.photos.map(photoForPayload).filter(Boolean) })),
      equipment_on_site: { hoist: true },
      checklist_items: { fire_safety: true },
      observations: [],
      time_in: '07:00', time_out: '15:30', areas_visited: 'Cellar',
    },
    cp_signature: { paths: [[1, 2]] },
    cp_name: 'Casey CP',
    status: 'submitted',
  });

  const r2Bytes = Buffer.byteLength(JSON.stringify(payloadOf(day(false))), 'utf8');
  const inlineBytes = Buffer.byteLength(JSON.stringify(payloadOf(day(true))), 'utf8');

  ok(r2Bytes < MONGO_MAX,
    `THE SAVE THAT USED TO FAIL: 100 photos serialise to ${r2Bytes.toLocaleString()} bytes, under the ${MONGO_MAX.toLocaleString()} ceiling`);
  ok(r2Bytes < MONGO_MAX / 8,
    `and with room to spare for the retained thumbnails the enhance pass adds (${r2Bytes.toLocaleString()} bytes)`);
  ok(inlineBytes > MONGO_MAX,
    `CONTROL: the identical day with the base64 the client used to inline is ${inlineBytes.toLocaleString()} bytes — over the ceiling`);

  {
    const photos = payloadOf(day(false)).data.activities.flatMap((a) => a.photos);
    ok(photos.length === 100, 'all 100 photos are in the payload');
    ok(photos.every((p) => p.base64 === undefined),
      'and not one of them carries full-size image data');
    ok(photos.every((p) => p.original_r2_key),
      'every photo names its R2 object');
    ok(new Set(photos.map((p) => p.original_r2_key)).size === 100,
      'and no two photos share one object');
    ok(photos.every((p) => p.id === undefined && p.pending === undefined),
      'client-side bookkeeping does not reach the compliance record');
  }

  ok(!/uriToBase64/.test(editorSrc),
    'editor: the save-time base64 re-encode is gone from the screen entirely');

  // ══════════════════════════════════════════════════════════════════════════
  section('EVERY READER, WITH NO INLINE FULL-SIZE BASE64');
  // ══════════════════════════════════════════════════════════════════════════

  const API_STUB = {
    getLogbookPhotoUrl: (id, ai, pi, variant) => (
      (!id && id !== 0) ? null : `https://api.test/api/reports/logbook-photo/${id}/${ai}/${pi}?v=${variant}`
    ),
  };

  // ── the kiosk: an inspector on site with NO signal ────────────────────────
  // eslint-disable-next-line no-new-func
  const kiosk = new Function('logbooksAPI', `
    ${sliceDecl(kioskSrc, 'inlinePhoto', '\n);\n')}
    ${sliceDecl(kioskSrc, 'logbookPhotoUri', '\n};\n')}
    return logbookPhotoUri;
  `)(API_STUB);

  {
    // What the enhance pass leaves on a capture-uploaded photo once it has run:
    // the R2 keys and the RETAINED THUMBNAIL, which is the whole reason the
    // kiosk cache is worth having.
    const cached = {
      original_r2_key: 'logbook-photos/proj1/act_1/cap_1.jpg',
      enhanced_r2_key: 'logbook-photos/proj1/act_1/cap_1-enhanced.jpg',
      thumb_r2_key: 'logbook-photos/proj1/act_1/cap_1-thumb.jpg',
      thumb_base64: 'VEhVTUI=',
      enhance_status: 'done',
    };
    const uri = kiosk(cached, { id: 'lb1' }, 0, 0);
    ok(uri === 'data:image/jpeg;base64,VEhVTUI=',
      'KIOSK OFFLINE: a cached log renders its photos from the retained thumbnail, no network');
    ok(!/^https?:/.test(uri),
      'and it is not a URL — an inspector in a dead zone would get nothing from one');
    ok(kiosk({ base64: 'RlVMTA==', thumb_base64: 'VEhVTUI=' }, { id: 'lb1' }, 0, 0)
      === 'data:image/jpeg;base64,RlVMTA==',
      'the deliberate INLINE-FIRST ordering is unchanged: full-size still wins when present');
    ok(kiosk({ original_r2_key: 'k' }, { id: 'lb1' }, 3, 4)
      === 'https://api.test/api/reports/logbook-photo/lb1/3/4?v=thumb',
      'a photo with no inline copy yet falls through to the served thumbnail');
  }

  // ── the CP editor ─────────────────────────────────────────────────────────
  // eslint-disable-next-line no-new-func
  const editor = new Function('logbooksAPI', 'existingLogId', `
    ${sliceDecl(editorSrc, 'inlinePhotoData', '\n);\n')}
    ${sliceDecl(editorSrc, 'isPurgedPhoto', '\n);\n')}
    ${sliceDecl(editorSrc, 'photoTileUri', '\n  );\n')}
    return { photoTileUri };
  `);
  const savedEditor = editor(API_STUB, 'lb1');
  const freshEditor = editor(API_STUB, null);

  {
    const pendingPhoto = { id: 'cap_1', uri: 'file:///docs/logbook_photos/1.jpg', upload_pending: true };
    ok(freshEditor.photoTileUri(pendingPhoto, 0, 0) === 'file:///docs/logbook_photos/1.jpg',
      'NEVER A BLANK TILE: an offline CP sees his own photo from the local file');
    ok(savedEditor.photoTileUri(pendingPhoto, 0, 0) === 'file:///docs/logbook_photos/1.jpg',
      'even after the log has a server id, the local file still wins (nothing to fetch)');
    ok(savedEditor.photoTileUri({ original_r2_key: 'k', enhance_status: 'done' }, 2, 5)
      === 'https://api.test/api/reports/logbook-photo/lb1/2/5?v=thumb',
      'a photo off another device, with no inline copy at all, renders from the server');
    ok(savedEditor.photoTileUri({ thumb_base64: 'VEhVTUI=' }, 0, 0) === 'data:image/jpeg;base64,VEhVTUI=',
      'and the retained thumbnail still works when it is all there is');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('THE CAPTURE ROUTE IS TOLD WHICH LOG, WHENEVER THERE IS ONE');
  // ══════════════════════════════════════════════════════════════════════════
  //
  // WHAT WAS REPORTED AND LEFT UNFIXED. POST
  // /api/projects/{id}/logbook-photo took no logbook id and performed no
  // filed-state check of any kind. It parks bytes and writes no document, so it
  // was never a way INTO a filed record — but it was not the gate its name
  // suggests either, and it now checks the log whenever the client can name one.
  //
  // OPTIONAL BY DESIGN, NOT BY OMISSION. A photo taken before the log has ever
  // reached the server has no id to send: the editor holds `existingLogId` null
  // until the first push, and the drain uploads photos ahead of the create.
  // That caller must keep working, and the block below is what proves it does.

  {
    const D = loadDrafts({ upload: okUpload() });
    await D.uploadCapturePhoto({
      projectId: 'proj1', logbookId: 'lb1', activityId: 'act_1',
      photoId: 'cap_1', uri: 'file:///docs/1.jpg',
    });
    ok(D.posts[0].form.parts.logbook_id === 'lb1',
      'uploadCapturePhoto sends logbook_id when the caller has one');
  }

  {
    const D = loadDrafts({ upload: okUpload() });
    await D.uploadCapturePhoto({
      projectId: 'proj1', activityId: 'act_1', photoId: 'cap_1',
      uri: 'file:///docs/1.jpg',
    });
    ok(!('logbook_id' in D.posts[0].form.parts),
      'THE OFFLINE CREATE: with no id it sends NO logbook_id field at all — an '
      + "empty string would be a value, and the server's absence branch is what "
      + 'keeps a photo taken before the log exists');
  }

  {
    const D = loadDrafts({ upload: okUpload() });
    const r = await D.uploadPendingActivityPhotos('proj1', rows(), 'lb7');
    ok(r.uploaded === 3 && D.posts.every((p) => p.form.parts.logbook_id === 'lb7'),
      'uploadPendingActivityPhotos passes the log id down to every capture');
  }

  {
    const D = loadDrafts({ upload: okUpload() });
    const r = await D.uploadPendingActivityPhotos('proj1', rows());
    ok(r.uploaded === 3 && D.posts.every((p) => !('logbook_id' in p.form.parts)),
      '...and a two-argument call still works, and still sends nothing');
  }

  // THE THREE CALLERS THAT HAVE AN ID NOW SEND IT. Source assertions, because
  // each lives in a screen or a drain whose surrounding machinery is not what
  // is under test here — but a signature widened and never called with the new
  // argument is the shape that makes a check pass while changing nothing.
  ok(/uploadPendingActivityPhotos\(parsed\.projectId, data\.activities, draft\.backend_id\)/
    .test(syncSrc),
    'drain: syncPendingDrafts passes the draft\'s backend_id (null on an '
    + 'offline create, which is the whole reason the field is optional)');
  ok(/uploadPendingActivityPhotos\(projectId, persisted, existingLogId\)/.test(editorSrc),
    'editor: the save-path sweep passes existingLogId');
  ok(/uploadCapturePhoto\(\{ projectId, logbookId: existingLogId, activityId, photoId: id, uri: localUri \}\)/
    .test(editorSrc),
    'editor: the shutter-path capture passes it too');
  ok(/uploadPendingActivityPhotos\(projectId, filed, existingLogId\)/
    .test(LF(path.join(FRONTEND, 'app', 'logbooks', 'fall_protection.jsx'))),
    'fall_protection: the fourth and last caller passes it as well');

  // AND NOBODY ELSE CALLS EITHER FUNCTION. The enumeration is the check: a
  // caller nobody found is how this codebase has broken before.
  const CALLERS = [draftsSrc, syncSrc, editorSrc,
    LF(path.join(FRONTEND, 'app', 'logbooks', 'fall_protection.jsx'))];
  const totalCalls = CALLERS.join('\n').split('\n')
    .filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('//'))
    .join('\n')
    .match(/\buploadCapturePhoto\(|\buploadPendingActivityPhotos\(/g) || [];
  ok(totalCalls.length === 7,
    'exactly seven live references across the whole app — the enumeration, held '
    + 'as a count so an eighth appearing anywhere fails HERE rather than being '
    + 'shipped with no logbook id: the two definitions in logbookDrafts.js, '
    + "uploadCapturePhoto's two call sites (uploadPendingActivityPhotos and the "
    + "editor's shutter path), and uploadPendingActivityPhotos's three (the "
    + `drain, the editor's save sweep, fall_protection) (got ${totalCalls.length})`);

  ok(/const local = photo\.uri/.test(editorSrc),
    'editor: the lightbox also tries the local capture first');
  ok(/enhance_status === 'done'/.test(editorSrc)
    && /Original — enhancement \$\{photo\.enhance_status\}/.test(editorSrc),
    'editor: the enhance_status label is untouched by any of this');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
