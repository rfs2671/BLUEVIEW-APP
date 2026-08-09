/**
 * app/reports.jsx — the admin-only line for photos whose enhancement failed.
 *
 * _enhance_logbook_photos stamps enhance_status="failed" + enhance_error on a
 * photo whose enhance/upload pass raised (backend/server.py:250-256). Nothing
 * read either field, so a photo that may be MISSING from that day's report was
 * a silent condition. get_report_preview now counts them and this panel says
 * so — softly, without gating anything.
 *
 * WHAT IS ASSERTED
 *   The line appears only for a NON-ZERO count, carries the count, and comes
 *   from the i18n catalogue in both locales. The surface stays where the
 *   operator put it: not on the CP editor, not on the kiosk/inspector screen.
 *
 * ALSO RECORDED HERE: on the client, /reports is NOT role-gated. `isAdmin` in
 * reports.jsx is declared and never used, and FloatingNav offers /reports to
 * every role. The ONLY gate is the backend 403 on get_report_preview — which
 * leaves `preview` null, so the whole panel (and this line with it) never
 * renders for a non-admin. That chain is asserted below so it cannot rot
 * silently into a leak.
 *
 * Run:  node src/utils/reportPreviewPhotoIssue.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const LF = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');

const reportsSrc = LF(path.join(FRONTEND, 'app', 'reports.jsx'));
const kioskSrc = LF(path.join(FRONTEND, 'app', 'site', 'logbooks.jsx'));
const editorSrc = LF(path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx'));
const navSrc = LF(path.join(FRONTEND, 'src', 'components', 'FloatingNav.js'));

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The REAL catalogues ─────────────────────────────────────────────────────
function loadCatalogue(file) {
  const stripped = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', file), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  return new Function(`${stripped}; return __default;`)();
}
const EN = loadCatalogue('en.js');
const ES = loadCatalogue('es.js');

// FLIPPED, not dropped. `reportPreview` is admin-only and EN-only by ruling.
// The placeholder guard — the thing that actually breaks the feature if it
// regresses — still runs against EN; the ES side is now asserted ABSENT so a
// well-meant translation cannot quietly reappear.
ok(!!EN.reportPreview, 'the reportPreview namespace exists in the EN catalogue');
ok(EN.reportPreview.failedPhotos.includes('{n}'),
  'EN carries the {n} placeholder the call site substitutes');
ok(ES.reportPreview === undefined,
  'reportPreview is absent from the ES catalogue — admin-only surface');

// ── Slice the REAL guarded block and run it ─────────────────────────────────
const MARK = '{preview.failed_photo_count > 0 && (';
const at = reportsSrc.indexOf(MARK);
if (at < 0) throw new Error('the failed-photo block is gone from app/reports.jsx — this test is stale');
// Brace-match the JSX expression container rather than scanning for a
// terminator: the block itself contains `'{n}'` and `))}`.
let depth = 0, end = -1;
for (let i = at; i < reportsSrc.length; i += 1) {
  if (reportsSrc[i] === '{') depth += 1;
  else if (reportsSrc[i] === '}') { depth -= 1; if (depth === 0) { end = i; break; } }
}
if (end < 0) throw new Error('failed-photo block: unbalanced braces');
const block = reportsSrc.slice(at, end + 1).trim();

const compiled = babel.transformSync(`const Panel = (preview, s, t) => <>${block}</>;`, {
  filename: 'reports-block.jsx',
  babelrc: false,
  configFile: false,
  plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
    { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }]],
}).code;

const React = {
  Fragment: function Fragment(props) { return props.children; },
  createElement: (type, props, ...children) => ({ __el: true, type, props: props || {}, children }),
};
function collect(node, out) {
  if (node === null || node === undefined || node === false || node === true) return;
  if (Array.isArray(node)) { node.forEach((n) => collect(n, out)); return; }
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return; }
  if (!node.__el) return;
  const kids = node.children.length ? node.children : node.props.children;
  if (typeof node.type === 'function') { collect(node.type({ ...node.props, children: kids }), out); return; }
  collect(kids, out);
}
// eslint-disable-next-line no-new-func
const Panel = new Function('React', 'Text', `${compiled}\n return Panel;`)(React, 'Text');

const t = (key) => (
  Object.prototype.hasOwnProperty.call(EN.reportPreview, key) ? EN.reportPreview[key] : key
);
const styleProxy = new Proxy({}, { get: () => ({}) });
const render = (preview) => {
  const out = [];
  collect(Panel(preview, styleProxy, t), out);
  return out.join(' | ');
};

ok(render({ failed_photo_count: 0 }) === '',
  'nothing is rendered when every photo enhanced');
ok(render({}) === '',
  'nothing is rendered when the field is absent (an older backend, a cached response)');
ok(render({ failed_photo_count: 3 }).includes('3')
  && render({ failed_photo_count: 3 }).includes('failed processing'),
  'a non-zero count renders the count and the message');
ok(!render({ failed_photo_count: 3 }).includes('{n}'),
  'the {n} placeholder is substituted, not shown to the admin');
ok(render({ failed_photo_count: 1 }).includes('1'),
  'a single failure still reports');

// ── Soft and non-blocking ───────────────────────────────────────────────────
ok(/photoIssueLine: \{[^}]*color: colors\.text\.muted/s.test(reportsSrc),
  'the line uses the muted theme token — no new colour literal, no alert styling');
ok(!/failed_photo_count[\s\S]{0,400}?disabled=/.test(reportsSrc),
  'nothing is disabled by the count — the preview, the PDF and the send are untouched');

// ── The surface stays where the operator put it ─────────────────────────────
ok(!/failed_photo_count|enhance_error/.test(kioskSrc),
  'the kiosk / inspector screen does not surface it — that is our plumbing, not an inspector`s business');
ok(!/failed_photo_count|enhance_error/.test(editorSrc),
  'the CP editor does not surface it either');

// ── The gate is the backend 403, and only the backend 403 ──────────────────
ok(/const isAdmin = user\?\.role === 'admin' \|\| user\?\.role === 'owner';/.test(reportsSrc)
  && (reportsSrc.match(/isAdmin/g) || []).length === 1,
  'RECORDED: reports.jsx declares isAdmin and never uses it — the client does not role-gate this screen');
ok(/\{ path: '\/reports'/.test(navSrc) && !/role/.test(navSrc.slice(navSrc.indexOf('const navItems'), navSrc.indexOf('];', navSrc.indexOf('const navItems')))),
  'RECORDED: FloatingNav offers /reports to every role');
ok(/setPreviewState\(r\.status\);[\s\S]{0,400}?setPreview\(null\)/.test(reportsSrc),
  'a non-ok preview fetch (the 403 a non-admin gets) clears preview to null');
ok(/\) : preview \? \(/.test(reportsSrc),
  '...and the whole panel, this line included, renders only when preview is truthy');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
