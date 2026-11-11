/**
 * TWO OPERATOR REPORTS, 2026-11-11, both run against the real modules.
 *
 * 1. "When uploading documents manually or uploading photos from device for
 *    daily logs won't let me choose more than 1 at a time." The Files and
 *    Documents pickers asked for one PDF; the Photos and fall-protection
 *    library pickers asked for one image and used assets[0]. They now ask for
 *    several, and src/utils/multiUpload sends them one after another -- a
 *    failure never stops the rest, and the one summary names what did not go.
 *
 * 2. "Why is this warning on? No tablet connected anyway? Such big warning is
 *    too much." The office Files screen drew the GATE TABLET's red "This tablet
 *    is not ready to use offline" card on a phone that was never set up to
 *    hold the project offline (state NEVER), over a project with no files.
 *    readinessForFilesScreen keeps only what that screen's own small "saved on
 *    this device" line cannot say: full and stopped, or out of date with no
 *    server reply. The gate-tablet screens are untouched.
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
let passed = 0;
let failed = 0;
function ok(cond, msg) {
  if (cond) { passed += 1; console.log(`  PASS  ${msg}`); } else { failed += 1; console.log(`  FAIL  ${msg}`); }
}

function load(rel, stubs = {}) {
  const full = path.join(FRONTEND, rel);
  const code = babel.transformSync(fs.readFileSync(full, 'utf8'), {
    filename: full, babelrc: false, configFile: false,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  }).code;
  const m = {};
  const shim = (id) => {
    if (id in stubs) return stubs[id];
    throw new Error(`unexpected require ${id} from ${rel}`);
  };
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, shim);
  return m;
}

const src = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

async function main() {
  // ── 1. several files, one after another ─────────────────────────────────
  const MU = load('src/utils/multiUpload.js');
  const order = [];
  const res = await MU.uploadEach(['a.pdf', 'b.pdf', 'c.pdf'], async (name) => {
    order.push(name);
    if (name === 'b.pdf') throw Object.assign(new Error('x'), { response: { data: { detail: 'Too large' } } });
  });
  ok(order.join() === 'a.pdf,b.pdf,c.pdf', 'every picked file is sent, in the order picked');
  ok(res.ok.join() === 'a.pdf,c.pdf' && res.failed.length === 1 && res.failed[0].item === 'b.pdf',
    'a failure does not stop the files after it');
  ok(MU.errorDetail(res.failed[0].error, 'fallback') === 'Too large', "the server's own reason is kept");

  // Run them strictly one at a time.
  let inFlight = 0;
  let most = 0;
  await MU.uploadEach([1, 2, 3, 4], async () => {
    inFlight += 1; most = Math.max(most, inFlight);
    await new Promise((r) => setTimeout(r, 5));
    inFlight -= 1;
  });
  ok(most === 1, 'never two uploads at once (site signal)');

  const en = load('src/i18n/en.js').default.multiUpload;
  const es = load('src/i18n/es.js').default.multiUpload;
  const tOf = (table) => (k) => table[k];
  const some = MU.batchSummary(tOf(en), res, (n) => n);
  ok(some.kind === 'warning' && some.body === '2 of 3 uploaded. Not uploaded: b.pdf',
    `a partial batch names what did not go (${some.body})`);
  const all = MU.batchSummary(tOf(en), { ok: [1, 2], failed: [] }, String);
  ok(all.kind === 'success' && all.body === '2 files uploaded', 'a clean batch is one success line');
  const none = MU.batchSummary(tOf(es), { ok: [], failed: [{ item: 'a.pdf' }] }, (n) => n);
  ok(none.kind === 'error' && none.body === '0 de 1 subidos. No se subieron: a.pdf', 'Spanish too');
  ok(Object.keys(en).every((k) => typeof es[k] === 'string' && es[k] !== en[k]),
    'every new string has its own Spanish');

  // The pickers ask for several.
  ok(/getDocumentAsync\(\{[^}]*multiple: true/s.test(src('app/projects/[id]/files.jsx')),
    'project Files: the PDF picker takes several');
  ok(/getDocumentAsync\(\{[^}]*multiple: true/s.test(src('app/documents.jsx')),
    'Documents: the PDF picker takes several');
  ok(/launchImageLibraryAsync\(\{[^}]*allowsMultipleSelection: true/s.test(src('app/logbooks/photos.jsx')),
    'Photos log: the library takes several');
  ok(/launchImageLibraryAsync\(\{[^}]*allowsMultipleSelection: true/s.test(src('app/logbooks/fall_protection.jsx')),
    'Fall protection: the library takes several');
  ok(!/assets\?\.\[0\]|assets\[0\]/.test(src('app/logbooks/fall_protection.jsx')),
    'Fall protection: no longer keeps only the first picked photo');

  // ── 2. the office Files screen and the gate-tablet notice ────────────────
  const R = load('src/utils/siteDeviceReadiness.js', {
    './siteManifestStore': { manifestScopes: () => [], readManifestList: async () => null, readSpaceShortfall: async () => null },
    './docCache': { listCachedDocs: async () => [], cachedDocName: () => '', canCacheDocs: () => false },
  });
  const show = (r, fetchState = 'ok') => R.readinessForFilesScreen(r, fetchState);
  const never = R.readinessFrom({ files: { state: 'absent' }, logbooks: { state: 'absent' } });
  ok(never.state === R.SITE_READY_NEVER, 'a phone that never downloaded this project reads NEVER');
  ok(show(never) === null && show(never, 'offline') === null,
    'the office Files screen shows no tablet card for it (the screenshot)');
  ok(R.describeReadiness(never).heading === 'This tablet is not ready to use offline',
    'the gate-tablet wording itself is unchanged');
  const filling = { state: R.SITE_READY_CURRENT, filling: true, saved: 3, expected: 9 };
  ok(show(filling) === null, '"still saving" is left to the screen\'s own saved-on-this-device line');
  const full = { state: R.SITE_READY_NO_SPACE, shortBytes: 1e8 };
  ok(show(full) === full, 'a device that is full and has STOPPED saving is still shown');
  const stale = { state: R.SITE_READY_STALE };
  ok(show(stale, 'ok') === null && show(stale, 'offline') === stale,
    'out of date is shown only when the server could not be reached (as before)');
  ok(src('app/projects/[id]/files.jsx').includes('readinessForFilesScreen(held.readiness, fetchState)'),
    'the Files screen renders through that rule');
  for (const rel of ['app/site/index.jsx', 'app/site/documents.jsx', 'app/site/logbooks.jsx']) {
    ok(!src(rel).includes('readinessForFilesScreen'), `${rel}: the gate tablet still shows every state`);
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => {
  console.log(`  FAIL  ${e.stack || e.message}`);
  console.log(`\n${passed} passed, ${failed + 1} failed`);
  process.exit(1);
});
