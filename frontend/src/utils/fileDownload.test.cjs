/**
 * DOWNLOAD NEVER PUTS A TOKEN IN A URL.
 *
 * Plans & Files' Download built `/content?token=` from window.localStorage.
 * A phone has no window.localStorage, so the token was empty and the browser
 * opened on {"detail":"Not authenticated"}; on the web the 30-day session
 * token went into the address bar. Asserted here:
 *
 *   1. no source file reads the session token out of window.localStorage;
 *   2. the web Download and the web viewer's open-in-browser go through the
 *      signed-url endpoint, and the tab is opened INSIDE the click;
 *   3. the native download sends the token in a HEADER, reports progress,
 *      can be cancelled, caches by content hash and hands the file to the
 *      share sheet;
 *   4. every error code it can raise has EN and ES copy;
 *   5. it touches no native module the 1.3.0 binary does not already carry.
 *
 * Run: node src/utils/fileDownload.test.cjs
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

const FRONTEND = path.join(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

function load(rel, stubs = {}) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  const req = (name) => {
    if (Object.prototype.hasOwnProperty.call(stubs, name)) return stubs[name];
    return require(name);
  };
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, req);
  return m;
}

// Comments say what was wrong, in words; strip them before any banned-token
// scan or the scan counts the sentence that says it was fixed.
function stripJs(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '');
}

const plan = load('src/utils/fileDownloadPlan.js');
const pdfSrc = load('src/utils/pdfSrc.js');
const en = load('src/i18n/en.js').default;
const es = load('src/i18n/es.js').default;

// ── 1. no session token out of window.localStorage, anywhere ──────────────
console.log('\nNo source reads the session token from window.localStorage');
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(js|jsx|ts|tsx)$/.test(e.name) && !/\.test\./.test(e.name)) out.push(p);
  }
  return out;
}
const sources = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))];
ok(sources.length > 100, `scanned the app (${sources.length} files)`);
const lsReaders = sources.filter((p) => /localStorage[\s\S]{0,80}blueview_token/.test(stripJs(fs.readFileSync(p, 'utf8'))));
ok(lsReaders.length === 0,
  `no window.localStorage read of blueview_token${lsReaders.length ? ` — ${lsReaders.map((p) => path.relative(FRONTEND, p)).join(', ')}` : ''}`);

// ── 2. the screens go through the signed link ─────────────────────────────
console.log('\nThe web Download and open-in-browser use the signed link');
const filesSrc = stripJs(read('app/projects/[id]/files.jsx'));
const dlStart = filesSrc.indexOf('const handleDownloadFile');
const dlBody = filesSrc.slice(dlStart, filesSrc.indexOf('const downloadMeta', dlStart));
ok(dlStart > 0 && dlBody.length > 200, 'files.jsx: handleDownloadFile found');
ok(!/token=/.test(dlBody), 'files.jsx: handleDownloadFile builds no token= url');
ok(!/blueview_token|getToken/.test(dlBody), 'files.jsx: handleDownloadFile reads no token at all');
ok(/openSignedDownload\(/.test(dlBody), 'files.jsx: web branch calls openSignedDownload');
ok(/startNativeDownload\(/.test(dlBody) && /shareDownloadedFile\(/.test(dlBody),
  'files.jsx: native branch downloads then shares');
ok(/visible=\{!!download\}/.test(filesSrc) && /download\?\.cancel\?\.\(\)/.test(filesSrc),
  'files.jsx: a progress sheet with Cancel is rendered while a download runs');

const webViewer = stripJs(read('src/components/PDFViewerWeb.jsx'));
ok(!/window\.open\(url/.test(webViewer.replace(/else if \(url && !\/\[\?&\]token=\/\.test\(url\)\) \{\s*window\.open\(url/, '')),
  'PDFViewerWeb: the iframe url (token-bearing for our proxy) is never opened as a page');
ok(/onPress=\{openInBrowser\}/.test(webViewer) && /openSignedDownload\(/.test(webViewer),
  'PDFViewerWeb: open-in-browser goes through openSignedDownload');

// ── openSignedDownload, driven ───────────────────────────────────────────
console.log('\nopenSignedDownload opens the tab inside the click');
function webHarness(signedUrl) {
  const events = [];
  const tab = { closed: false, location: { href: 'about:blank' }, opener: {}, close() { this.closed = true; events.push('close'); } };
  global.window = {
    open: (u) => { events.push(`open:${u}`); return tab; },
  };
  const mod = load('src/utils/fileDownload.js', {
    'expo-file-system/legacy': {},
    'expo-sharing': {},
    './api': { __esModule: true, default: {}, getToken: async () => 't', dropboxAPI: { signedUrl: signedUrl(events) } },
    './docCache': { getCachedDocFile: async () => null },
    './pdfSrc': pdfSrc,
    './fileDownloadPlan': plan,
  });
  return { mod, events, tab };
}

(async () => {
  {
    const { mod, events, tab } = webHarness((ev) => async (id) => {
      ev.push(`signed:${id}`);
      return { url: 'https://api.levelog.com/api/files/abc/download?k=u&u=1&e=2&s=3' };
    });
    await mod.openSignedDownload('abc', { attachment: true });
    ok(events[0] === 'open:about:blank' && events[1] === 'signed:abc',
      `the blank tab opens BEFORE the network call (${events.slice(0, 2).join(' → ')})`);
    ok(tab.location.href.endsWith('&dl=1') && !/token=/.test(tab.location.href),
      'the tab is pointed at the signed link with dl=1 and no token');
    ok(tab.opener === null, 'the opened tab cannot reach back into the app');
  }
  {
    const { mod, events, tab } = webHarness(() => async () => {
      const e = new Error('nope'); e.response = { status: 403 }; throw e;
    });
    let code = null;
    try { await mod.openSignedDownload('abc'); } catch (e) { code = e.code; }
    ok(code === 'noAccess', `a 403 from signed-url surfaces as noAccess (${code})`);
    ok(tab.closed && events.includes('close'), 'and the blank tab is closed, not left empty');
  }

  // ── 3. native download, driven ──────────────────────────────────────────
  console.log('\nThe native download: header, progress, cancel, cache, share');
  function nativeHarness({ status = 200, hang = false } = {}) {
    const disk = new Map();
    const calls = { downloads: [], shared: [], cancelled: 0 };
    let release = null;
    const FS = {
      cacheDirectory: 'file:///cache/',
      getInfoAsync: async (u) => (disk.has(u) ? { exists: true, size: disk.get(u) } : { exists: false }),
      makeDirectoryAsync: async () => {},
      deleteAsync: async (u) => { disk.delete(u); },
      copyAsync: async ({ from, to }) => { disk.set(to, disk.get(from)); },
      moveAsync: async ({ from, to }) => { disk.set(to, disk.get(from)); disk.delete(from); },
      createDownloadResumable: (url, dest, opts, onProgress) => {
        calls.downloads.push({ url, dest, headers: opts.headers });
        return {
          downloadAsync: () => new Promise((resolve) => {
            onProgress({ totalBytesWritten: 500, totalBytesExpectedToWrite: 1000 });
            const finish = () => {
              onProgress({ totalBytesWritten: 1000, totalBytesExpectedToWrite: 1000 });
              disk.set(dest, 1000);
              resolve({ status, uri: dest });
            };
            if (hang) release = () => resolve(undefined); else finish();
          }),
          cancelAsync: async () => { calls.cancelled += 1; if (release) release(); },
        };
      },
    };
    const mod = load('src/utils/fileDownload.js', {
      'expo-file-system/legacy': FS,
      'expo-sharing': {
        isAvailableAsync: async () => true,
        shareAsync: async (uri, opts) => { calls.shared.push({ uri, opts }); },
      },
      './api': {
        __esModule: true,
        default: { defaults: { baseURL: 'https://api.levelog.com' } },
        getToken: async () => 'SESSION-JWT',
        dropboxAPI: { getFileUrl: async () => ({ url: 'https://dl.dropboxusercontent.com/x' }) },
      },
      './docCache': { getCachedDocFile: async () => null },
      './pdfSrc': pdfSrc,
      './fileDownloadPlan': plan,
    });
    return { mod, calls, disk };
  }
  const FILE = {
    id: '6a90ebce1df3e1f2588018a2', name: 'A-101 Plan.pdf', size: 1000, cache_version: 2,
    content_hash: 'ab'.repeat(32),
    r2_url: '/api/projects/6a5f63bc147407d3261df2c7/files/6a90ebce1df3e1f2588018a2/content',
  };
  {
    const { mod, calls, disk } = nativeHarness();
    const progress = [];
    const job = mod.startNativeDownload({ file: FILE, projectId: 'p', onProgress: (w, e) => progress.push([w, e]) });
    const res = await job.promise;
    const d = calls.downloads[0];
    ok(d && d.headers.Authorization === 'Bearer SESSION-JWT', 'the token travels in the Authorization header');
    ok(d && !/token=/.test(d.url) && d.url.startsWith('https://api.levelog.com/api/projects/'),
      'and NOT in the url');
    ok(progress.length >= 2 && progress[0][0] === 500 && progress[0][1] === 1000, 'progress is reported as bytes land');
    ok(d.dest.endsWith('.part') && res.uri === d.dest.replace(/\.part$/, '') && !disk.has(d.dest),
      'bytes land in .part and are renamed into place');
    ok(res.uri.includes(`/downloads/h_${FILE.content_hash}/`) && res.uri.endsWith('/A-101 Plan.pdf'),
      'the copy is keyed by content hash and carries the real filename');
    const again = await mod.startNativeDownload({ file: FILE, projectId: 'p' }).promise;
    ok(again.cached === true && calls.downloads.length === 1, 'a second download of the same bytes is a cache hit');
    await mod.shareDownloadedFile(res.uri, FILE);
    ok(calls.shared[0] && calls.shared[0].opts.mimeType === 'application/pdf'
      && calls.shared[0].opts.UTI === 'com.adobe.pdf', 'the file is handed to the share sheet as a PDF');
  }
  {
    const { mod, calls } = nativeHarness({ hang: true });
    const job = mod.startNativeDownload({ file: FILE, projectId: 'p' });
    await new Promise((r) => setTimeout(r, 0));
    await job.cancel();
    let code = null;
    try { await job.promise; } catch (e) { code = e.code; }
    ok(calls.cancelled === 1 && code === 'cancelled', `Cancel stops the transfer (${code})`);
  }
  {
    const { mod } = nativeHarness({ status: 403 });
    let code = null;
    try { await mod.startNativeDownload({ file: FILE, projectId: 'p' }).promise; } catch (e) { code = e.code; }
    ok(code === 'noAccess', `a 403 from the proxy surfaces as noAccess (${code})`);
  }
  {
    const { mod, calls } = nativeHarness();
    const dbx = { name: 'spec.docx', path: '/jobs/tower/spec.docx', size: 1000, id: 'id:dropbox' };
    await mod.startNativeDownload({ file: dbx, projectId: 'p' }).promise;
    ok(calls.downloads[0].url.startsWith('https://dl.dropboxusercontent.com/')
      && !calls.downloads[0].headers.Authorization,
      'a Dropbox-only file is fetched from its temp link with NO token header');
  }

  // ── the pure rules ───────────────────────────────────────────────────────
  console.log('\nCache key, name and source rules');
  ok(plan.downloadCacheKey({ id: 'x', content_hash: 'ab'.repeat(32) }) === `h_${'ab'.repeat(32)}`,
    'the content hash wins when there is one');
  ok(plan.downloadCacheKey({ id: '6a90', cache_version: 3, size: 10 }) === 'f_6a90.3.10',
    'no hash: id, cache_version and size');
  ok(plan.downloadCacheKey({ id: '6a90', cache_version: 3, size: 10 })
    !== plan.downloadCacheKey({ id: '6a90', cache_version: 4, size: 10 }),
  'a re-synced file (cache_version bump) is a new key');
  ok(plan.downloadCacheKey({ id: 'x', content_hash: '../../etc' }).startsWith('f_'),
    'a hash that is not a hash is not trusted as a path');
  ok(plan.shareFileName({ name: '../../evil/name.pdf' }) === 'name.pdf', 'a filename cannot climb out of its folder');
  ok(plan.shareFileName({ name: '' }) === 'file', 'an empty name becomes "file"');
  ok(plan.downloadSource(FILE) === 'stored', 'a stored file goes through our proxy');
  ok(plan.downloadSource({ path: '/a/b.pdf' }) === 'dropbox', 'a Dropbox-only file goes through Dropbox');
  ok(plan.downloadFraction(5, 0) === null && plan.downloadFraction(5, 10) === 0.5, 'unknown total is indeterminate');

  // ── 4. EN/ES copy for every code ─────────────────────────────────────────
  console.log('\nEvery error code has EN and ES copy');
  const helperSrc = read('src/utils/fileDownload.js');
  const planSrc = read('src/utils/fileDownloadPlan.js');
  const codes = new Set([
    ...[...helperSrc.matchAll(/downloadError\('([A-Za-z]+)'\)/g)].map((m) => m[1]),
    ...[...planSrc.matchAll(/return '([A-Za-z]+)';/g)].map((m) => m[1]),
    ...[...stripJs(read('app/projects/[id]/files.jsx')).matchAll(/tDl\('([A-Za-z]+)'\)/g)].map((m) => m[1]),
    ...[...webViewer.matchAll(/tDl\('([A-Za-z]+)'\)/g)].map((m) => m[1]),
  ].filter((c) => !['stored', 'dropbox', 'none'].includes(c)));
  ok(codes.size >= 10, `found the codes and keys in use (${codes.size})`);
  const missing = [...codes].filter((c) => !(en.fileDownload && en.fileDownload[c]) || !(es.fileDownload && es.fileDownload[c]));
  ok(missing.length === 0, `each has en and es copy${missing.length ? ` — missing: ${missing.join(', ')}` : ''}`);

  // ── 5. OTA only ──────────────────────────────────────────────────────────
  console.log('\nOTA only: no native module the binary lacks');
  const imports = [...helperSrc.matchAll(/from '([^.][^']*)'/g)].map((m) => m[1]).sort();
  ok(JSON.stringify(imports) === JSON.stringify(['expo-file-system/legacy', 'expo-sharing']),
    `fileDownload.js imports only expo-file-system/legacy and expo-sharing (${imports.join(', ')})`);
  const pkg = JSON.parse(read('package.json'));
  ok(!!pkg.dependencies['expo-sharing'] && !!pkg.dependencies['expo-file-system'],
    'both are existing dependencies (in the binary since 1.1.2)');
  ok(!/from '/.test(planSrc), 'fileDownloadPlan.js imports nothing');

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
