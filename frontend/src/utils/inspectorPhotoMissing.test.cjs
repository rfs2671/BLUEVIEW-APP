/**
 * app/site/logbooks.jsx — a missing photo on a compliance record must LOOK
 * missing.
 *
 * WHAT WAS WRONG
 *   The daily-jobsite renderer drew each activity photo as
 *
 *     const uri = logbookPhotoUri(photo, log, i, pi);
 *     if (!uri) return null;
 *     return <Image key={pi} source={{ uri }} style={s.activityPhoto} ... />;
 *
 *   Two silent absences, on the screen a DOB inspector reads:
 *     1. `!uri` rendered NOTHING. The record says this crew filed three
 *        photos; the row showed two, or none, and said nothing about it.
 *     2. The <Image> had no `onError`. `logbookPhotoUri`'s `||` chain can only
 *        detect a FALSY value, never a failed LOAD — so a 404 (the finalize
 *        purge dropped base64 and R2 lost the object; a key that never
 *        uploaded; a `uri` that is a dead file:/// path from another phone)
 *        draws a blank square, forever, that reads exactly like a photo of
 *        nothing.
 *   The CP editor has carried an `onError` on its tiles all along
 *   (daily_jobsite.jsx, photoTileUri + tileRetry). The inspector screen — the
 *   one where being wrong is a compliance finding — did not.
 *
 * WHAT IS ASSERTED
 *   Every photo the record claims occupies a slot on the screen; a slot that
 *   cannot be filled SAYS SO; and a load failure moves a tile into that state
 *   rather than leaving a blank square. There is no fallback to try: unlike
 *   the CP screen, `logbookPhotoUri` has already spent inline base64, inline
 *   thumb, the served URL and the local path before it returns.
 *
 * HOW
 *   No test runner in this repo (see RiskScoreCircle.bandFor.test.cjs). The
 *   REAL DocPhoto component and the REAL renderer block are sliced out of the
 *   screen, transpiled with the repo's own babel and executed — against a
 *   useState that actually stores, so the onError -> re-render transition is
 *   exercised rather than asserted about. The translator is the REAL one over
 *   the REAL catalogue.
 *
 * Run:  node src/utils/inspectorPhotoMissing.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'site', 'logbooks.jsx');
const EDITOR = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const I18N = path.join(FRONTEND, 'src', 'i18n');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const src = fs.readFileSync(SCREEN, 'utf8').split('\r\n').join('\n');
const editorSrc = fs.readFileSync(EDITOR, 'utf8').split('\r\n').join('\n');

// ── The REAL catalogues ─────────────────────────────────────────────────────
function loadCatalogue(file) {
  const stripped = fs.readFileSync(path.join(I18N, file), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  return new Function(`${stripped}; return __default;`)();
}
const EN = loadCatalogue('en.js');
const ES = loadCatalogue('es.js');
const t = (key) => (
  Object.prototype.hasOwnProperty.call(EN.logbookView, key) ? EN.logbookView[key] : key
);

// ── 0 — the sentence exists, in the one catalogue this screen reads ─────────
ok(typeof EN.logbookView.fPhotoUnavailable === 'string'
  && EN.logbookView.fPhotoUnavailable.trim().length > 0,
  'logbookView.fPhotoUnavailable exists in the EN catalogue');
ok(ES.logbookView === undefined,
  'logbookView stays EN-only — a DOB inspector reads English (EN_ONLY_NAMESPACES)');
const UNAVAILABLE = t('fPhotoUnavailable');
// The screen has ONE sanctioned way to say "the app has no value for this"
// ("— Not recorded"). A photo that failed to load is a different fact — the
// record HAS the photo, this device cannot show it — and must not borrow that
// wording, or an inspector cannot tell "never taken" from "cannot display".
ok(UNAVAILABLE !== t('fNotRecorded'),
  '...and it is NOT the "— Not recorded" string: an unshowable photo is not an absent one');

// ── A hook runtime that actually stores ─────────────────────────────────────
// DocPhoto's whole job is the transition from "showing" to "could not load",
// and a useState stub that discards writes would let this file pass while the
// screen stays blank. Keyed by call order, reset before each walk.
const hookStore = new Map();
let hookSeq = 0;
const useState = (init) => {
  const key = hookSeq;
  hookSeq += 1;
  if (!hookStore.has(key)) hookStore.set(key, typeof init === 'function' ? init() : init);
  return [
    hookStore.get(key),
    (v) => hookStore.set(key, typeof v === 'function' ? v(hookStore.get(key)) : v),
  ];
};

// ── A createElement that builds a plain tree ────────────────────────────────
const React = {
  Fragment: function Fragment(props) { return props.children; },
  createElement: (type, props, ...children) => ({
    __el: true, type, props: props || {}, children,
  }),
};
function walk(node, out) {
  if (node === null || node === undefined || node === false || node === true) return;
  if (Array.isArray(node)) { node.forEach((n) => walk(n, out)); return; }
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return; }
  if (!node.__el) return;
  out.push(node);
  const kids = node.children.length ? node.children : node.props.children;
  if (typeof node.type === 'function') { walk(node.type({ ...node.props, children: kids }), out); return; }
  walk(kids, out);
}

const styleProxy = new Proxy({}, { get: (_x, k) => ({ __style: String(k) }) });
const Icon = function IconStub() { return null; };

// ── Slice the REAL DocPhoto out of the screen ───────────────────────────────
const DOC_PHOTO_START = 'function DocPhoto(';
const dpAt = src.indexOf(DOC_PHOTO_START);
ok(dpAt >= 0, 'app/site/logbooks.jsx defines a DocPhoto component for one filed photo');
let DocPhoto = function MissingDocPhoto() { return null; };
if (dpAt >= 0) {
  const dpEnd = src.indexOf('\n}\n', dpAt);
  if (dpEnd < 0) throw new Error('DocPhoto has no closing brace at column 0 — this test is stale');
  const dpSrc = src.slice(dpAt, dpEnd + 3);
  const dpCompiled = babel.transformSync(dpSrc, {
    filename: 'doc-photo.jsx',
    babelrc: false,
    configFile: false,
    plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
      { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }]],
  }).code;
  const DP_NAMES = ['React', 'View', 'Text', 'Image', 'ImageOff', 'useState', 'semantic', 'colors'];
  const DP_VALUES = {
    React, View: 'View', Text: 'Text', Image: 'Image', ImageOff: Icon, useState,
    semantic: new Proxy({}, { get: () => '#999' }),
    colors: { text: { primary: '#fff', secondary: '#eee', muted: '#999', subtle: '#666' } },
  };
  // eslint-disable-next-line no-new-func
  DocPhoto = new Function(...DP_NAMES, `${dpCompiled}\n return DocPhoto;`)(
    ...DP_NAMES.map((n) => DP_VALUES[n]),
  );
}

// ── Slice the renderer block, exactly as logbookViewRenderers.test.cjs does ──
const START = '  const SignatureBlock = ({ signature, label }) => {';
const END = "    return <Text style={s.logField}>No data available</Text>;\n  };\n";
const rFrom = src.indexOf(START);
const rTo = src.indexOf(END);
if (rFrom < 0 || rTo < 0) {
  throw new Error('renderer block not found in app/site/logbooks.jsx — this test is stale');
}
const compiled = babel.transformSync(src.slice(rFrom, rTo + END.length), {
  filename: 'logbooks-renderers.jsx',
  babelrc: false,
  configFile: false,
  plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
    { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }]],
}).code;

// `logbookPhotoUri` is swapped per case — that is the variable under test —
// so it lives in a cell the harness writes before each render.
let uriFor = () => null;
const NAMES = ['View', 'Text', 'Image', 'React', 's', 't', 'tFp', 'colors', 'semantic',
  'spacing', 'withAlpha', 'rosterClock', 'logbookPhotoUri', 'headcountDisplay',
  'DocPhoto', 'useState', 'ImageOff',
  'ShieldCheck', 'AlertTriangle', 'Truck', 'MapPin', 'ClipboardList', 'FileText',
  'Users', 'CheckCircle', 'BookOpen', 'Pen', 'CloudSun', 'Clock', 'Eye', 'Wrench',
  'csLogItems', 'csItemState', 'csItemSummary'];
const VALUES = {
  View: 'View', Text: 'Text', Image: 'Image', React,
  s: styleProxy, t, tFp: t,
  colors: { text: { primary: '#fff', secondary: '#eee', muted: '#999', subtle: '#666' } },
  semantic: new Proxy({}, { get: () => '#999' }),
  spacing: new Proxy({}, { get: () => 8 }),
  withAlpha: () => 'rgba(0,0,0,0.1)',
  rosterClock: (v) => (v ? String(v) : '—'),
  logbookPhotoUri: (...args) => uriFor(...args),
  headcountDisplay: (act, fallback) => String(act?.worker_count ?? fallback ?? ''),
  DocPhoto,
  useState,
  csLogItems: () => [],
  csItemState: () => 'empty',
  csItemSummary: () => '',
};
for (const n of NAMES) if (!(n in VALUES)) VALUES[n] = Icon;
// eslint-disable-next-line no-new-func
const R = new Function(...NAMES, `${compiled}\n return { renderDailyJobsite };`)(
  ...NAMES.map((n) => VALUES[n]),
);

const nodes = (tree) => { hookSeq = 0; const out = []; walk(tree, out); return out; };
const textOf = (tree) => nodes(tree).filter((n) => typeof n === 'string').join(' | ');
const imagesOf = (tree) => nodes(tree).filter((n) => n && n.__el && n.type === 'Image');
const countOf = (tree, str) => textOf(tree).split(str).length - 1;

const log = {
  id: 'lb1', log_type: 'daily_jobsite', date: '2026-08-07', status: 'submitted',
  cp_name: 'Ada CP',
  data: {
    weather: 'Clear',
    activities: [{
      crew_id: 'C3', company: 'Acme Concrete', worker_count: 6,
      work_description: 'Formwork', work_locations: '3rd Floor',
      photos: [{ original_r2_key: 'k1' }, { original_r2_key: 'k2' }, { original_r2_key: 'k3' }],
    }],
  },
};

// ════════════════════════════════════════════════════════════════════════════
//  1 — A PHOTO WITH NO RESOLVABLE URI IS SAID, NOT SKIPPED
// ════════════════════════════════════════════════════════════════════════════
// The finalize purge drops `base64`, `photoForPayload` drops `uri` once the R2
// key exists, and a log whose R2 object is gone resolves to nothing at all.
// Three photos on the record, three slots on the screen.
uriFor = () => null;
const tree = R.renderDailyJobsite(log);
ok(countOf(tree, UNAVAILABLE) === 3,
  `all 3 unresolvable photos say so — got ${countOf(tree, UNAVAILABLE)}`);
ok(imagesOf(tree).length === 0,
  '...and none of them is drawn as an <Image> with no source');

// ════════════════════════════════════════════════════════════════════════════
//  2 — A PHOTO THAT RESOLVES IS DRAWN, AND CARRIES AN ERROR SURFACE
// ════════════════════════════════════════════════════════════════════════════
hookStore.clear();
uriFor = (photo, l, i, pi) => `https://api.test/logbooks/${l.id}/photos/${i}/${pi}/thumb`;
const good = R.renderDailyJobsite(log);
const tiles = imagesOf(good);
ok(tiles.length === 3, `all 3 resolvable photos draw — got ${tiles.length}`);
ok(textOf(good).indexOf(UNAVAILABLE) === -1,
  '...and nothing claims a photo is unavailable while it is loading fine');
ok(tiles.every((el) => typeof el.props.onError === 'function'),
  'every tile carries an onError — the || chain cannot see a failed LOAD, only a falsy value');
ok(tiles.every((el) => el.props.source && typeof el.props.source.uri === 'string'),
  '...and every tile still carries its source uri');

// ════════════════════════════════════════════════════════════════════════════
//  3 — A 404 TURNS THAT TILE INTO A STATED ABSENCE, NOT A BLANK SQUARE
// ════════════════════════════════════════════════════════════════════════════
// The transition is EXECUTED: onError is invoked on the middle tile and the
// screen re-rendered against the same store.
if (tiles.length === 3 && typeof tiles[1].props.onError === 'function') {
  tiles[1].props.onError({ nativeEvent: { error: 'HTTP 404' } });
}
const after = R.renderDailyJobsite(log);
ok(imagesOf(after).length === 2,
  `the failed tile stops being an <Image> — ${imagesOf(after).length} of 3 remain`);
ok(countOf(after, UNAVAILABLE) === 1,
  `...and exactly that one says it is unavailable — got ${countOf(after, UNAVAILABLE)}`);

// ════════════════════════════════════════════════════════════════════════════
//  4 — NOTHING IS INVENTED FOR AN ACTIVITY WITH NO PHOTOS
// ════════════════════════════════════════════════════════════════════════════
hookStore.clear();
uriFor = () => null;
const noPhotos = R.renderDailyJobsite({
  ...log, data: { ...log.data, activities: [{ crew_id: 'C3', company: 'Acme Concrete' }] },
});
ok(textOf(noPhotos).indexOf(UNAVAILABLE) === -1,
  'a crew that filed no photos is not marked as having lost any');
ok(textOf(noPhotos).includes('Acme Concrete'),
  '...and the crew row itself still renders');

// ════════════════════════════════════════════════════════════════════════════
//  5 — THE SILENT RETURN IS GONE FROM THE SOURCE
// ════════════════════════════════════════════════════════════════════════════
// Pinned at the source too: an execution test can only see the branches it
// drives, and `if (!uri) return null` is the exact line that made three
// investigations come back empty.
const dailyBlockAt = src.indexOf('const renderDailyJobsite = (log) => {');
const dailyBlockEnd = src.indexOf('const renderToolboxTalk = (log) => {');
const dailyBlock = src.slice(dailyBlockAt, dailyBlockEnd);
ok(dailyBlockAt >= 0 && dailyBlockEnd > dailyBlockAt, 'renderDailyJobsite is still where it was');
ok(!/if \(!uri\) return null;/.test(dailyBlock),
  'renderDailyJobsite no longer drops an unresolvable photo on the floor');

// ════════════════════════════════════════════════════════════════════════════
//  6 — CONSISTENT WITH THE CP EDITOR, which had this all along
// ════════════════════════════════════════════════════════════════════════════
ok(/onError=\{/.test(editorSrc),
  'RECORDED: the CP editor puts onError on its photo tiles (the surface this borrows)');
// RECORDED, NOT FIXED — the same `if (!uri) return null;` runs a second time in
// renderFallProtection, on the row where the photo IS the evidence (cut
// webbing, a deployed impact indicator). Out of scope for this change; named
// here so it is a known open defect rather than an oversight.
const fpAt = src.indexOf('const renderFallProtection');
const fpBlock = fpAt >= 0 ? src.slice(fpAt, src.indexOf('\n  const render', fpAt + 10)) : '';
ok(/if \(!uri\) return null;/.test(fpBlock) || !/logbookPhotoUri/.test(fpBlock),
  'RECORDED: renderFallProtection still drops an unresolvable photo silently — same defect, not fixed here');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
