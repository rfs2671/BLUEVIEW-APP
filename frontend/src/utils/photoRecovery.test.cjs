/**
 * RECOVERING PHOTOS FROM THE PHONE THAT TOOK THEM -- THE PROBE COMES FIRST.
 *
 * Operator's ruling, 2026-10-08: "The probe reports what's on the phone before
 * anything uploads." Two filed daily jobsite logs on 588 Thomas list photos
 * that exist only on the capturing phone. This loads the REAL photoRecovery.js
 * over a fake phone (a filesystem and a routed server) and asserts, above all,
 * the order: every presence report is sent before any byte is.
 *
 *   node src/utils/photoRecovery.test.cjs
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
  else { failed += 1; console.log(`  FAIL  ${label}\n          got  ${a}\n          want ${b}`); }
}

const SRC = path.join(__dirname, 'photoRecovery.js');
const CODE = babel.transformSync(fs.readFileSync(SRC, 'utf8'), {
  filename: SRC,
  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false,
  babelrc: false,
}).code;

const U0 = 'file:///data/user/0/com.levelog.app/files/logbook_photos/cap_1785935200722_1_19.jpg';
const U1 = 'file:///data/user/0/com.levelog.app/files/logbook_photos/1785935941873_0.jpeg';
const U2 = 'file:///data/user/0/com.levelog.app/files/logbook_photos/1787667899371_0.jpg';

const PENDING = [
  { logbook_id: 'lbA', date: '2026-08-05', activity_index: 0, photo_index: 0,
    uri: U0, timestamp: '2026-08-05T13:06:40.722Z', shares_file: false },
  { logbook_id: 'lbA', date: '2026-08-05', activity_index: 0, photo_index: 2,
    uri: U1, timestamp: '2026-08-05T13:18:58.747Z', shares_file: false },
  { logbook_id: 'lbB', date: '2026-08-24', activity_index: 0, photo_index: 0,
    uri: U2, timestamp: '2026-08-24T18:26:18.807Z', shares_file: true },
];

/** A phone. `files` maps uri -> {size, md5}; `route(method, url)` answers. */
function phone({ files = {}, web = false, route = null } = {}) {
  const calls = [];
  const env = {
    netinfo: { __esModule: true, default: { addEventListener: () => () => {} } },
    rn: {
      Platform: { OS: web ? 'web' : 'android' },
      AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) },
    },
    fsmod: {
      documentDirectory: web ? null : 'file:///data/user/0/com.levelog.app/files/',
      getInfoAsync: async (uri) => (uri in files
        ? { exists: true, size: files[uri].size, md5: files[uri].md5, modificationTime: 1785935201 }
        : { exists: false }),
    },
    api: {
      __esModule: true,
      default: {
        get: async (url) => {
          calls.push(['GET', url]);
          const a = route ? route('GET', url) : null;
          if (a instanceof Error) throw a;
          return { data: a };
        },
        post: async (url, body) => {
          calls.push(['POST', url, body]);
          const a = route ? route('POST', url, body) : { ok: true };
          if (a instanceof Error) throw a;
          return { data: a };
        },
      },
    },
  };
  global.FormData = class { constructor() { this.parts = {}; } append(k, v) { this.parts[k] = v; } };
  const m = {};
  const req = (spec) => {
    if (spec === '@react-native-community/netinfo') return env.netinfo;
    if (spec === 'react-native') return env.rn;
    if (spec === 'expo-file-system/legacy') return env.fsmod;
    if (spec === './api') return env.api;
    throw new Error(`unstubbed import: ${spec}`);
  };
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', CODE)(m, { exports: m }, req);
  return { mod: m, calls };
}

const serve = (overrides = {}) => (method, url, body) => {
  if (method === 'GET' && url === '/api/photo-recovery/pending') {
    return overrides.pending !== undefined ? overrides.pending : { items: PENDING };
  }
  if (method === 'POST' && url.endsWith('/presence')) {
    return overrides.presence !== undefined ? overrides.presence : { recorded: body.reports.length };
  }
  if (method === 'POST' && url.endsWith('/recover')) {
    const shares = body && body.parts && body.parts.uri === U2;
    return overrides.recover !== undefined ? overrides.recover
      : { status: shares ? 'held_for_review' : 'recovered' };
  }
  return null;
};

(async () => {
  console.log('\nA. the probe reports BEFORE any upload');
  {
    const { mod, calls } = phone({
      files: { [U0]: { size: 2_000_000, md5: 'aa' }, [U2]: { size: 1_500_000, md5: 'cc' } },
      route: serve(),
    });
    const r = await mod.runPhotoRecovery();
    const firstUpload = calls.findIndex((c) => c[0] === 'POST' && c[1].endsWith('/recover'));
    const lastReport = calls.map((c, i) => [c, i])
      .filter(([c]) => c[0] === 'POST' && c[1].endsWith('/presence')).pop()[1];
    ok(firstUpload > lastReport, 'every presence report is sent before the first upload');
    eq(calls.filter((c) => c[1].endsWith('/presence')).map((c) => c[1]),
      ['/api/photo-recovery/lbA/presence', '/api/photo-recovery/lbB/presence'],
      'one report per log');
    const reportA = calls.find((c) => c[1] === '/api/photo-recovery/lbA/presence')[2].reports;
    eq(reportA.map((x) => [x.photo_index, x.exists, x.size || null]),
      [[0, true, 2000000], [2, false, null]],
      'it reports the file that is there AND the one that is not');
    eq(reportA[0].md5, 'aa', 'with the md5 the operator can compare against');
    eq(r.pending, 3, 'three stranded entries were named');
    eq(r.present, 2, 'two of them were on the phone');
    eq(calls.filter((c) => c[1].endsWith('/recover')).length, 2,
      'only the files that exist are uploaded');
    eq([r.uploaded, r.held], [1, 1],
      'the shared 08-24 file is HELD for review, the other recovered');
    const up = calls.find((c) => c[1] === '/api/photo-recovery/lbA/recover')[2].parts;
    eq([up.activity_index, up.photo_index, up.uri, up.timestamp],
      ['0', '0', U0, '2026-08-05T13:06:40.722Z'],
      'the upload names the entry by its path and capture time');
  }

  console.log('\nB. no upload without a report');
  {
    const { mod, calls } = phone({
      files: { [U0]: { size: 1, md5: 'a' } },
      route: serve({ presence: new Error('network') }),
    });
    const r = await mod.runPhotoRecovery();
    eq(calls.filter((c) => c[1].endsWith('/recover')).length, 0,
      'a report that did not land means nothing uploads this pass');
    eq(r.phase, 'unreachable', 'and the pass says why it stopped');
  }

  console.log('\nC. quiet when there is nothing to do or no way to do it');
  {
    const { mod, calls } = phone({ route: serve({ pending: { items: [] } }) });
    const r = await mod.runPhotoRecovery();
    eq([r.pending, calls.length], [0, 1], 'nothing stranded: one GET and nothing else');
  }
  {
    const { mod, calls } = phone({ web: true, route: serve() });
    const r = await mod.runPhotoRecovery();
    eq([r.phase, calls.length], ['no-files', 0], 'web has no phone files: it asks nothing');
  }
  {
    const { mod } = phone({ route: () => new Error('offline') });
    const r = await mod.runPhotoRecovery();
    eq(r.phase, 'unreachable', 'an unreachable server is left for the next startup');
  }
  {
    const { mod, calls } = phone({ files: {}, route: serve() });
    const r = await mod.runPhotoRecovery();
    eq([r.present, r.reported, calls.filter((c) => c[1].endsWith('/recover')).length], [0, 3, 0],
      'IF THEY ARE GONE: all three reported missing, nothing uploaded');
  }

  console.log('\nD. one pass at a time');
  {
    const { mod, calls } = phone({ route: serve({ pending: { items: [] } }) });
    await Promise.all([mod.runPhotoRecoveryOnce(), mod.runPhotoRecoveryOnce()]);
    eq(calls.length, 1, 'two triggers at once share one pass');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed > 0 || passed < 15 ? 1 : 0;
})();
