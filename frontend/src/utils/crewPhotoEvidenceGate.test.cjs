/**
 * app/logbooks/daily_jobsite.jsx — the camera gate must not hide the evidence.
 *
 * WHAT WAS WRONG
 *   A subcontractor crew IS a row in `data.activities[]`; its photos live at
 *   `data.activities[i].photos[j]`. The crew card rendered
 *
 *     {!ready ? <lockedHint/> : <View style={s.photoBlock}> ... </View>}
 *
 *   and the grid of ALREADY-TAKEN photos sat INSIDE that photoBlock. So
 *   `ready === false` did not gate the camera, it gated the whole block — the
 *   row's own photos vanished from the screen, silently, with no error and no
 *   empty state. Three investigations found nothing because nothing is logged
 *   and nothing renders: the failure is a branch not taken.
 *
 *   `cameraReady` (src/utils/dailyJobsiteModel.js) is asymmetric — `hasActivity`
 *   needs activity_ids AND a work_description, while `hasLocation` accepts
 *   location_ids OR work_locations — so a row carrying a description and no
 *   activity chips is un-ready. That is a legacy row, an amendment-copied row,
 *   or a row whose chips were deselected after the photos were taken. Each of
 *   them held photos the CP could no longer see.
 *
 * WHAT IS ASSERTED
 *   Photos that EXIST render whether or not the row is camera-ready, and the
 *   camera — and only the camera — stays behind the gate. The predicate itself
 *   is unchanged and is RECORDED below rather than fixed: it gates capture, and
 *   "no photo without its subject" is a deliberate rule.
 *
 * HOW
 *   No test runner in this repo (see RiskScoreCircle.bandFor.test.cjs). The
 *   REAL JSX block is sliced out of the screen, transpiled with the repo's own
 *   babel and executed against a createElement that builds a plain tree, so
 *   what is asserted below is what the screen renders. `cameraReady`,
 *   `photosInBucket`, `bucketRemaining`, `tileKey` and `photoTileUri` are the
 *   REAL ones, sliced or imported — a stub would let this file pass while the
 *   screen does something else.
 *
 * Run:  node src/utils/crewPhotoEvidenceGate.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const MODEL = path.join(FRONTEND, 'src', 'utils', 'dailyJobsiteModel.js');
const I18N = path.join(FRONTEND, 'src', 'i18n');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The screens are CRLF in this repo; normalise so the slice boundaries hold.
const src = fs.readFileSync(SCREEN, 'utf8').split('\r\n').join('\n');

// ── The REAL English catalogue ──────────────────────────────────────────────
function loadCatalogue(file) {
  const stripped = fs.readFileSync(path.join(I18N, file), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  return new Function(`${stripped}; return __default;`)();
}
const EN = loadCatalogue('en.js');
const t = (key) => (
  Object.prototype.hasOwnProperty.call(EN.dailyJobsite, key) ? EN.dailyJobsite[key] : key
);
const LOCKED_HINT = t('cameraLockedHint');
const CAP_HINT = t('photoCapRowHint');
const TAGGED_WITH = t('photoTaggedWith');
const PHOTO_LABEL = t('photoLabel');
const TAKE = t('photoTake');
const GALLERY = t('photoGallery');
for (const [k, v] of Object.entries({
  cameraLockedHint: LOCKED_HINT, photoCapRowHint: CAP_HINT, photoTaggedWith: TAGGED_WITH,
  photoLabel: PHOTO_LABEL, photoTake: TAKE, photoGallery: GALLERY,
})) {
  if (v === k) throw new Error(`dailyJobsite.${k} is missing from en.js — this test is stale`);
}

// ── The REAL model: cameraReady ─────────────────────────────────────────────
const _model = {};
// eslint-disable-next-line no-new-func
new Function('exports', 'module', 'require', babel.transformSync(
  fs.readFileSync(MODEL, 'utf8'),
  {
    filename: MODEL,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  },
).code)(_model, { exports: _model }, require);
const { cameraReady } = _model;

// ── The REAL bucket helpers, sliced out of the screen ───────────────────────
const sliceBetween = (from, to, what) => {
  const a = src.indexOf(from);
  if (a < 0) throw new Error(`${what}: start marker gone from daily_jobsite.jsx — this test is stale`);
  const b = src.indexOf(to, a);
  if (b < 0) throw new Error(`${what}: end marker gone from daily_jobsite.jsx — this test is stale`);
  return src.slice(a, b + to.length);
};

const bucketSrc = sliceBetween(
  'const MAX_PHOTOS_PER_SUBCONTRACTOR = 10;',
  '0, MAX_PHOTOS_PER_SUBCONTRACTOR - photosInBucket(rows, index),\n);',
  'bucket helpers',
);
const tileKeySrc = sliceBetween(
  'const tileKey = (photo, ai, pi) => String(',
  '\n);',
  'tileKey',
);
// eslint-disable-next-line no-new-func
const H = new Function(`
  ${bucketSrc}
  ${tileKeySrc}
  return { MAX_PHOTOS_PER_SUBCONTRACTOR, photosInBucket, bucketRemaining, tileKey };
`)();

// ── The REAL photoTileUri, sliced the way logbookPhotoR2.test.cjs slices it ──
const tileUriSrc = sliceBetween(
  '  const photoTileUri = (photo, ai, pi, retried) => (',
  '\n  );\n',
  'photoTileUri',
);
const logbooksAPI = {
  getLogbookPhotoUrl: (id, ai, pi, size) => `https://api.test/logbooks/${id}/photos/${ai}/${pi}/${size}`,
};
const existingLogId = 'lb-1';
// eslint-disable-next-line no-new-func
const photoTileUri = new Function('logbooksAPI', 'existingLogId',
  `${tileUriSrc}\n return photoTileUri;`)(logbooksAPI, existingLogId);

// ── Slice the camera / photo block out of the crew card ─────────────────────
const BLOCK_START = '            {/* CAMERA — only once crew, activity and location are all set.';
const BLOCK_END = '\n          </Card>';
const from = src.indexOf(BLOCK_START);
if (from < 0) throw new Error('the CAMERA block is gone from daily_jobsite.jsx — this test is stale');
const to = src.indexOf(BLOCK_END, from);
if (to < 0) throw new Error('the CAMERA block has no closing </Card> — this test is stale');
const block = src.slice(from, to);

const compiled = babel.transformSync(
  `const CameraBlock = (a, i, ready, activities) => <>${block}</>;`,
  {
    filename: 'daily-jobsite-camera-block.jsx',
    babelrc: false,
    configFile: false,
    plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
      { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }]],
  },
).code;

// ── A createElement that builds a plain tree ────────────────────────────────
const React = {
  Fragment: function Fragment(props) { return props.children; },
  createElement: (type, props, ...children) => ({
    __el: true, type, props: props || {}, children,
  }),
};

// Every element node in the rendered tree, function components expanded.
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
const nodes = (tree) => { const out = []; walk(tree, out); return out; };
// `photoLabel` is the bare word "Photo", which is a SUBSTRING of
// `photoTaggedWith` ("Photos will be labelled:"). Match the counter by its
// shape — "Photo 3/10" — or "no counter" silently means "no tagged-with line".
const COUNTER = new RegExp(`${PHOTO_LABEL} \\d+/${H.MAX_PHOTOS_PER_SUBCONTRACTOR}`);
const textOf = (tree) => nodes(tree).filter((n) => typeof n === 'string').join(' | ');
const elementsOf = (tree, type) => nodes(tree).filter((n) => n && n.__el && n.type === type);

// ── Stubs for everything the block closes over ──────────────────────────────
const styleProxy = new Proxy({}, { get: (_x, k) => ({ __style: String(k) }) });
const Icon = function IconStub() { return null; };
const noop = () => {};
const NAMES = [
  'React', 'View', 'Text', 'Image', 'Pressable', 'ActivityIndicator',
  's', 't', 'outdoor', 'crewName',
  'photosInBucket', 'bucketRemaining', 'MAX_PHOTOS_PER_SUBCONTRACTOR',
  'tileKey', 'photoTileUri', 'tileRetry', 'setTileRetry',
  'openPhotoLightbox', 'removeActivityPhoto', 'takeActivityPhoto', 'pickActivityPhoto',
  'X', 'Camera', 'ImageIcon',
];
const VALUES = {
  React, View: 'View', Text: 'Text', Image: 'Image', Pressable: 'Pressable',
  ActivityIndicator: 'ActivityIndicator',
  s: styleProxy,
  t,
  outdoor: new Proxy({}, { get: () => '#000' }),
  // The REAL fallback the screen uses for an unnamed crew.
  crewName: (a) => (String(a.company || '').trim() || t('noCrewWorker')),
  photosInBucket: H.photosInBucket,
  bucketRemaining: H.bucketRemaining,
  MAX_PHOTOS_PER_SUBCONTRACTOR: H.MAX_PHOTOS_PER_SUBCONTRACTOR,
  tileKey: H.tileKey,
  photoTileUri,
  tileRetry: {},
  setTileRetry: noop,
  openPhotoLightbox: noop,
  removeActivityPhoto: noop,
  takeActivityPhoto: noop,
  pickActivityPhoto: noop,
};
for (const n of NAMES) if (!(n in VALUES)) VALUES[n] = Icon;

// eslint-disable-next-line no-new-func
const CameraBlock = new Function(...NAMES, `${compiled}\n return CameraBlock;`)(
  ...NAMES.map((n) => VALUES[n]),
);

// `ready` is computed by the REAL predicate, exactly as the screen computes it.
const renderRow = (activities, i) => CameraBlock(
  activities[i], i, cameraReady(activities[i]), activities,
);

const photo = (n) => ({
  id: `cap_${n}`,
  original_r2_key: `logbook-photos/p/act_1/cap_${n}.jpg`,
  enhance_status: 'done',
});

// ════════════════════════════════════════════════════════════════════════════
//  A — A ROW THAT IS NOT CAMERA-READY STILL SHOWS THE PHOTOS IT HOLDS
// ════════════════════════════════════════════════════════════════════════════
// The shape that produced the report: a subcontractor row with a company, a
// typed work_description and work_locations, three photos already on it — and
// no activity_ids, because it predates the chips (or an amendment copied it,
// or the CP deselected them). `hasActivity` fails, so the row is un-ready.
const legacyRow = {
  activity_id: 'act_1',
  company: 'Acme Concrete',
  subcontractor_id: 'sub_1',
  work_description: 'Formwork, Rebar',
  work_locations: '3rd Floor',
  activity_ids: [],
  location_ids: [],
  photos: [photo(1), photo(2), photo(3)],
};

ok(cameraReady(legacyRow) === false,
  'the row under test is genuinely NOT camera-ready (the real predicate says so)');

const legacy = renderRow([legacyRow], 0);
const legacyImages = elementsOf(legacy, 'Image');
ok(legacyImages.length === 3,
  `all 3 photos the row already holds render as tiles — got ${legacyImages.length}`);
ok(legacyImages.every((el) => typeof el.props.source?.uri === 'string' && el.props.source.uri.length > 0),
  'each tile carries a real source uri from photoTileUri, not an empty square');
ok(textOf(legacy).includes(`${PHOTO_LABEL} 3/10`),
  'the bucket counter renders beside them — an inspector-facing count of what is on file');
ok(textOf(legacy).includes(LOCKED_HINT),
  'the CAMERA is still locked, and says why');
ok(!textOf(legacy).includes(TAKE) && !textOf(legacy).includes(GALLERY),
  'and the capture controls are NOT offered — the gate is on capture, not on evidence');
ok(!textOf(legacy).includes(TAGGED_WITH),
  'the "photos will be labelled" promise is not printed on a row with no labels to promise');

// ════════════════════════════════════════════════════════════════════════════
//  B — A CAMERA-READY ROW IS UNCHANGED
// ════════════════════════════════════════════════════════════════════════════
const readyRow = {
  ...legacyRow, activity_ids: ['formwork'], location_ids: ['floor_3'],
};
ok(cameraReady(readyRow) === true, 'the control row IS camera-ready');
const readyOut = renderRow([readyRow], 0);
ok(elementsOf(readyOut, 'Image').length === 3, 'a ready row renders its 3 photos');
ok(textOf(readyOut).includes(TAKE) && textOf(readyOut).includes(GALLERY),
  'a ready row offers both capture controls');
ok(!textOf(readyOut).includes(LOCKED_HINT), 'a ready row shows no locked hint');
ok(textOf(readyOut).includes(TAGGED_WITH) && textOf(readyOut).includes('Acme Concrete'),
  'a ready row prints what its photos will be labelled with');

// ════════════════════════════════════════════════════════════════════════════
//  C — NOTHING IS INVENTED FOR A ROW WITH NO PHOTOS
// ════════════════════════════════════════════════════════════════════════════
// An empty un-ready row must look exactly as it did: the hint, and nothing
// else. "Render the evidence" must not become "render an empty grid".
const emptyUnready = renderRow([{ ...legacyRow, photos: [] }], 0);
ok(elementsOf(emptyUnready, 'Image').length === 0,
  'an un-ready row with no photos renders no tiles');
ok(!COUNTER.test(textOf(emptyUnready)),
  '...and no bucket counter — there is nothing to count');
ok(textOf(emptyUnready).includes(LOCKED_HINT),
  '...only the locked hint, exactly as before');

const emptyReady = renderRow([{ ...readyRow, photos: [] }], 0);
ok(elementsOf(emptyReady, 'Image').length === 0 && !COUNTER.test(textOf(emptyReady)),
  'a ready row with no photos renders no tiles and no counter');
ok(textOf(emptyReady).includes(TAKE),
  '...but does offer the camera');

// ════════════════════════════════════════════════════════════════════════════
//  D — THE PER-SUBCONTRACTOR CAP STILL GATES CAPTURE, NOT DISPLAY
// ════════════════════════════════════════════════════════════════════════════
const cappedPhotos = Array.from({ length: 10 }, (_, n) => photo(n));
const cappedReady = renderRow([{ ...readyRow, photos: cappedPhotos }], 0);
ok(elementsOf(cappedReady, 'Image').length === 10 && textOf(cappedReady).includes(CAP_HINT),
  'a full bucket shows all 10 photos and the cap hint instead of the buttons');
ok(!textOf(cappedReady).includes(TAKE) && !textOf(cappedReady).includes(GALLERY),
  '...and no capture control');

const cappedUnready = renderRow([{ ...legacyRow, photos: cappedPhotos }], 0);
ok(elementsOf(cappedUnready, 'Image').length === 10,
  'a full bucket on an UN-ready row shows all 10 too — the two gates do not compound into a blackout');
ok(textOf(cappedUnready).includes(LOCKED_HINT) && !textOf(cappedUnready).includes(CAP_HINT),
  '...and the reason given is the camera gate, one reason, not two');

// ════════════════════════════════════════════════════════════════════════════
//  E — A PENDING TILE IS STILL A SPINNER, NOT AN IMAGE
// ════════════════════════════════════════════════════════════════════════════
const midCapture = renderRow([{
  ...legacyRow, photos: [photo(1), { id: 'cap_2', pending: true }],
}], 0);
ok(elementsOf(midCapture, 'Image').length === 1
  && elementsOf(midCapture, 'ActivityIndicator').length === 1,
  'an un-ready row mid-capture shows one tile and one spinner');

// ════════════════════════════════════════════════════════════════════════════
//  F — RECORDED, NOT FIXED: cameraReady is asymmetric on purpose
// ════════════════════════════════════════════════════════════════════════════
// This is what makes a row un-ready while holding photos. It is NOT changed
// here: it gates CAPTURE, and "no photo without its subject" is a deliberate
// rule — every frame must carry crew, activity, location and date. Pinned so
// the asymmetry is a decision on the record rather than an accident, and so
// that changing it is a deliberate act with a failing test attached.
const base = { company: 'Acme', activity_ids: ['x'], work_description: 'Formwork', location_ids: ['y'], work_locations: '3rd Floor' };
ok(cameraReady({ ...base, activity_ids: [] }) === false,
  'RECORDED: a typed work_description without activity chips is NOT camera-ready (AND)');
ok(cameraReady({ ...base, work_description: '' }) === false,
  'RECORDED: activity chips without a composed description are NOT camera-ready either (AND)');
ok(cameraReady({ ...base, location_ids: [] }) === true,
  'RECORDED: a typed work_locations without location chips IS camera-ready (OR)');
ok(cameraReady({ ...base, work_locations: '' }) === true,
  'RECORDED: location chips without a composed string are camera-ready too (OR)');

// ════════════════════════════════════════════════════════════════════════════
//  G — THE STRUCTURE, so the grid cannot be re-parented under the gate
// ════════════════════════════════════════════════════════════════════════════
ok(!/\{!ready \? \([\s\S]{0,200}?\) : \(\s*<View style=\{s\.photoBlock\}>/.test(src),
  'the photoBlock is no longer the ELSE branch of the ready gate');
ok(/s\.photoGrid/.test(src), 'the photo grid still exists on the screen');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
