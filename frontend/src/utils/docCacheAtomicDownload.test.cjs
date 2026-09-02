/**
 * A HALF-DOWNLOADED PLAN NEVER LANDS UNDER THE REAL FILENAME.
 *
 * The field reports are "a cached plan opens showing ZERO PAGES" and "a plan I
 * never opened says could not load document". Both are one defect, and its
 * trigger is an interrupted transfer on flaky wifi — a gate tablet's normal
 * state.
 *
 * WHAT THE NATIVE MODULE ACTUALLY DOES (expo-file-system 19.0.24, /legacy).
 * Android FileSystemLegacyModule.kt downloadAsync, the `"file" == uri.scheme`
 * branch, inside OkHttp's onResponse:
 *
 *     val file = uri.toFile()      // <- the path JS handed it
 *     file.delete()
 *     val sink = file.sink().buffer()
 *     sink.writeAll(response.body!!.source())
 *     sink.close()
 *
 * The bytes stream STRAIGHT INTO the destination path, flushed a segment at a
 * time. A connection dropped mid-body throws out of writeAll, `sink.close()`
 * never runs, and every segment already flushed is sitting on disk under
 * whatever name JS asked for. If that name was the real one, the cache now
 * holds a truncated PDF that `getCachedDocFile` happily serves for ever.
 *
 * So the device double below writes to WHATEVER PATH IT IS GIVEN before it
 * fails — because that is precisely what the real module does. The fix is not
 * to catch harder; it is to never give it the real name.
 *
 * Run:  node src/utils/docCacheAtomicDownload.test.cjs
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

const DIR = '/doc/documents/';

/**
 * A fake device whose FileSystem behaves like the real native module.
 *
 * `disk` is name -> byte count. `script` decides what the next downloadAsync
 * does; `downloads` records the paths it was handed, which is the whole point
 * of the first assertion.
 */
function makeDevice(opts) {
  const o = opts || {};
  const disk = new Map(Object.entries(o.files || {}));
  const downloads = [];
  const nameOf = (uri) => String(uri).split('/').pop();
  const script = Array.isArray(o.script) ? o.script.slice() : [];

  const FileSystem = {
    documentDirectory: '/doc/',
    downloads,
    getInfoAsync: async (uri) => {
      const name = nameOf(uri);
      if (String(uri).endsWith('/')) return { exists: true, isDirectory: true };
      if (!disk.has(name)) return { exists: false, isDirectory: false };
      return { exists: true, isDirectory: false, size: disk.get(name), uri: String(uri) };
    },
    makeDirectoryAsync: async () => {},
    readDirectoryAsync: async () => [...disk.keys()],
    deleteAsync: async (uri, options) => {
      const name = nameOf(uri);
      if (!disk.has(name) && !(options && options.idempotent)) throw new Error('ENOENT');
      disk.delete(name);
    },
    moveAsync: async ({ from, to }) => {
      const a = nameOf(from);
      const b = nameOf(to);
      if (!disk.has(a)) throw new Error(`cannot move missing ${a}`);
      // Android: File.renameTo on the same volume — one atomic rename that
      // replaces the destination. iOS: remove-then-move. Either way the
      // destination is only ever whole.
      disk.set(b, disk.get(a));
      disk.delete(a);
    },
    getFreeDiskStorageAsync: async () => 1e10,
    downloadAsync: async (url, dest, _options) => {
      const target = nameOf(dest);
      downloads.push(target);
      const step = script.length > 0 ? script.shift() : { kind: 'ok', bytes: 12 * 1024 * 1024 };
      if (step.kind === 'throw-mid') {
        // Segments already flushed are on disk under `target`, then the
        // connection dies. This is the real Android failure, verbatim.
        disk.set(target, step.bytes);
        throw new Error('unexpected end of stream');
      }
      if (step.kind === 'throw-early') {
        // Dropped before any body byte: onFailure -> promise.reject, and
        // nothing was ever opened.
        throw new Error('Unable to resolve host');
      }
      if (step.kind === 'status') {
        disk.set(target, step.bytes);   // an error body, written all the same
        return { status: step.status, uri: String(dest) };
      }
      disk.set(target, step.bytes);
      return { status: 200, uri: String(dest) };
    },
  };

  return {
    disk,
    downloads,
    FileSystem,
    AsyncStorage: {
      getAllKeys: async () => [],
      getItem: async () => null,
      setItem: async () => {},
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
    if (spec === 'react-native') return { Platform: { OS: 'android' } };
    if (spec === './api') {
      return { __esModule: true, default: { defaults: { baseURL: 'https://api.levelog.com' } }, getToken: async () => 't' };
    }
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', COMPILED)(m, { exports: m }, shim);
  return m;
}

const REAL = 'a1.7.pdf';
const URL = '/api/projects/p1/files/a1/content';
const FULL = 12 * 1024 * 1024;
const FRAGMENT = 300 * 1024;

// A path is "the real name" only if it is exactly it. A temp name derived from
// it (a1.7.pdf.part) is a DIFFERENT file and is not what any reader opens.
const isRealName = (n) => n === REAL;

async function main() {
  // ═════════════════════════════════════════════════════════════════════════
  // 1. THE DEFECT ITSELF: a transfer that dies mid-body must leave NOTHING
  //    under the real filename.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ script: [{ kind: 'throw-mid', bytes: FRAGMENT }] });
    const got = await load(d).cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });

    ok(got === null, 'a dropped transfer reports failure rather than a uri');
    ok(!d.disk.has(REAL),
      'NO TRUNCATED FILE IS LEFT UNDER THE REAL NAME when downloadAsync throws '
      + '— the outer catch used to return null without deleting anything, and '
      + `${FRAGMENT} bytes of a ${FULL}-byte plan stayed on the tablet for ever`);
    ok(!d.downloads.some(isRealName),
      'and the download was never even AIMED at the real name — a temporary '
      + 'name is what the native module gets handed');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 2. AND THE NEXT OPEN RE-DOWNLOADS, because nothing is there to skip.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      script: [{ kind: 'throw-mid', bytes: FRAGMENT }, { kind: 'ok', bytes: FULL }],
    });
    const M = load(d);
    await M.cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });
    const second = await M.cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });

    ok(second === DIR + REAL, 'the retry after a dropped transfer returns the real uri');
    ok(d.disk.get(REAL) === FULL,
      'and the WHOLE plan is what ends up on disk — the corruption was not '
      + 'permanent, which it was while the early-return protected it');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 3. LENGTH IS VERIFIED. A completed download of the wrong size is a
  //    truncation the transport did not report, and must be rejected.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FRAGMENT }] });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FULL,
    });
    ok(got === null, 'a 200 that delivered the wrong byte count is not accepted');
    ok(!d.disk.has(REAL),
      'and the short body is REMOVED, not kept — a plan the list says is 12MB '
      + 'and 300KB of bytes are not the same document');
  }
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FULL }] });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FULL,
    });
    ok(got === DIR + REAL && d.disk.get(REAL) === FULL,
      'and a download whose length MATCHES is kept');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 4. THE EXPECTED SIZE IS OPTIONAL. Callers that have one pass it; the
  //    logbook screens, which have no size on the record, must keep working.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FULL }] });
    const got = await load(d).cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });
    ok(got === DIR + REAL && d.disk.get(REAL) === FULL,
      'no expectedSize: the download still lands under the real name');
  }
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FULL }] });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: 0,
    });
    ok(got === DIR + REAL,
      'a size of 0 (the backend default for "unknown") is treated as no size, '
      + 'not as a length to enforce');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 5. A SHORT FILE ALREADY ON DISK IS NOT SERVED AS CACHED. Every tablet in
  //    the field already holds these; the sweep that would clear them is
  //    unreachable from /site/*, so the read path has to catch them.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ files: { [REAL]: FRAGMENT } });
    const M = load(d);
    const hit = await M.getCachedDocFile('a1', 7, 'pdf', { expectedSize: FULL });
    ok(hit === null,
      'a 300KB fragment of a 12MB plan is NOT handed back as the cached copy '
      + '— `info.size > 0` said yes to it, and the viewer drew zero pages');
    const good = await M.getCachedDocFile('a1', 7, 'pdf', { expectedSize: FRAGMENT });
    ok(good === DIR + REAL, 'a file of the right length still is');
    const noSize = await M.getCachedDocFile('a1', 7, 'pdf');
    ok(noSize === DIR + REAL, 'and with no expected size the old behaviour stands');
  }
  {
    const d = makeDevice({ files: { [REAL]: 0 } });
    const hit = await load(d).getCachedDocFile('a1', 7, 'pdf');
    ok(hit === null, 'an empty file is still never served');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 6. A FILE THAT FAILS VERIFICATION IS RE-DOWNLOADABLE. The early-return
  //    must not be what protects a corrupt file from ever being replaced.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      files: { [REAL]: FRAGMENT },
      script: [{ kind: 'ok', bytes: FULL }],
    });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FULL,
    });
    ok(d.downloads.length === 1,
      'a corrupt file on disk does NOT satisfy the "already saved, skip" check');
    ok(got === DIR + REAL && d.disk.get(REAL) === FULL,
      'and the good bytes replace it');
  }
  {
    const d = makeDevice({ files: { [REAL]: FULL }, script: [] });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FULL,
    });
    ok(d.downloads.length === 0 && got === DIR + REAL,
      'a file of the RIGHT length is still a pure local hit — no re-download');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 7. EVERY OTHER FAILURE PATH LEAVES THE REAL NAME ALONE TOO.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ script: [{ kind: 'status', status: 404, bytes: 87 }] });
    const got = await load(d).cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });
    ok(got === null && !d.disk.has(REAL),
      'a 404 error body never becomes a1.7.pdf');
  }
  {
    const d = makeDevice({ script: [{ kind: 'throw-early' }] });
    const got = await load(d).cacheDocFile({ fileId: 'a1', cacheVersion: 7, remoteUrl: URL });
    ok(got === null && d.disk.size === 0,
      'a connection that dies before the first byte leaves the cache empty');
  }
  {
    // The existing good copy must survive a failed refresh: a CP in a cellar
    // with an unreachable server keeps the plan he saved yesterday.
    const d = makeDevice({
      files: { [REAL]: FULL },
      script: [{ kind: 'throw-mid', bytes: FRAGMENT }],
    });
    const got = await load(d).cacheDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FRAGMENT + 1,
    });
    ok(got === null, 'the failed refresh reports failure');
    ok(d.disk.get(REAL) === FULL,
      'AND THE COPY ALREADY ON THE PHONE IS UNTOUCHED — a dropped retry must '
      + 'never cost a man the drawing he is standing on');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // 8. THE SIZE REACHES THE CACHE FROM THE CALLERS THAT HAVE ONE.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({ files: { [REAL]: FRAGMENT }, script: [{ kind: 'ok', bytes: FULL }] });
    const got = await load(d).ensureCachedDocFile({
      fileId: 'a1', cacheVersion: 7, remoteUrl: URL, expectedSize: FULL,
    });
    ok(got === DIR + REAL && d.disk.get(REAL) === FULL,
      'ensureCachedDocFile threads expectedSize through BOTH halves — the disk '
      + 'check and the download');
  }
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FRAGMENT }] });
    const n = await load(d).warmDocCache(
      [{ id: 'a1', cache_version: 7, r2_url: URL, size: FULL }],
      { limit: 5 },
    );
    ok(n === 0 && !d.disk.has(REAL),
      'warmDocCache reads `size` off the list record, so a warm that comes '
      + 'back short is discarded instead of cached');
  }
  {
    const d = makeDevice({ script: [{ kind: 'ok', bytes: FULL }] });
    const n = await load(d).warmDocCache(
      [{ id: 'a1', cache_version: 7, r2_url: URL }],
      { limit: 5 },
    );
    ok(n === 1 && d.disk.get(REAL) === FULL,
      'and a record with no size warms exactly as before');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
