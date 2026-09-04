/**
 * THE SHEET'S OWN SIZE HAD CANCELLED OUT OF THE SCALE, AND THIS RUNS THE MATH.
 *
 * `targetScaleInfo` computed `(baseWidth / vp1.width) * min(dpr,2) * 1.5`, so
 * the rendered pixel width was `baseWidth * min(dpr,2) * 1.5` WHATEVER the page
 * measured. The page cancels. Resolution therefore fell as the sheet grew,
 * which is backwards for the one document type this viewer exists to show:
 *
 *   36x48 sheet, phone at 390 CSS px, dpr 2+  ->  1170 px  ->  32.5 ppi
 *   36x48 sheet, tablet at 768                ->  2304 px  ->  64 ppi
 *   36x48 sheet, tablet at 1024               ->  3072 px  ->  85 ppi
 *
 * A ppi FLOOR fixes it without touching anything that was already sharp: take
 * `max(viewportAnchored, TARGET_PPI/72)`, and the three existing clamps still
 * run unconditionally afterwards.
 *
 * WHY THIS FILE EXECUTES THE FUNCTION INSTEAD OF GREPPING FOR IT. Fifteen
 * source-text tests were written this week against an R2 sweep, all passing,
 * while the code they described deleted nothing — they asserted the CALL and
 * never the EFFECT. A scale formula is arithmetic; arithmetic can be run. Every
 * number below comes from the real `targetScaleInfo` lifted out of the real
 * viewer source, not from a restatement of it.
 *
 * Run:  node src/utils/pdfScaleAnchor.test.cjs
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const VIEWER = path.join(ROOT, 'src', 'utils', 'pdfjsViewer.js');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/**
 * Reconstruct the viewer script exactly as `viewerHtml()` would — the same
 * slice-and-evaluate `pdfRenderProbe.test.cjs` uses, for the same reason:
 * importing the module pulls in react-native and expo.
 */
function viewerScript() {
  const src = fs.readFileSync(VIEWER, 'utf8').replace(/\r\n/g, '\n');
  const start = src.indexOf('const VIEWER_SCRIPT = [');
  if (start < 0) throw new Error('VIEWER_SCRIPT not found');
  const open = src.indexOf('[', start);
  const close = src.indexOf("].join('\\n');", open);
  if (close < 0) throw new Error('VIEWER_SCRIPT terminator not found');
  const WORKER_NAME = 'pdf.worker.min.js';
  // eslint-disable-next-line no-new-func
  const arr = new Function('WORKER_NAME', `return ${src.slice(open, close + 1)};`)(WORKER_NAME);
  return arr.join('\n');
}

/**
 * Lift `targetScaleInfo` and its two caps out of the generated script and run
 * them for real, with `baseWidth` and `devicePixelRatio` supplied per device.
 */
function makeScaler(js) {
  const grab = (name) => {
    const i = js.indexOf(`function ${name}(`);
    if (i < 0) throw new Error(`no ${name} in the viewer script`);
    // functions in this file end at a line that is exactly two spaces + '}'
    const end = js.indexOf('\n  }\n', i);
    if (end < 0) throw new Error(`could not slice ${name}`);
    return js.slice(i, end + 4);
  };
  const constOf = (name) => {
    const m = js.match(new RegExp(`var ${name} = (\\d+);`));
    if (!m) throw new Error(`no ${name} constant`);
    return Number(m[1]);
  };
  const body = [
    `var MAX_CANVAS_EDGE = ${constOf('MAX_CANVAS_EDGE')};`,
    `var MAX_CANVAS_PX = ${constOf('MAX_CANVAS_PX')};`,
    `var TARGET_PPI = ${constOf('TARGET_PPI')};`,
    grab('targetScaleInfo'),
    'return targetScaleInfo(vp1, over);',
  ].join('\n');
  // eslint-disable-next-line no-new-func
  const fn = new Function('vp1', 'over', 'baseWidth', 'window', body);
  return (widthIn, heightIn, cssPx, dpr, over) => fn(
    { width: widthIn * 72, height: heightIn * 72 },
    over,
    cssPx,
    { devicePixelRatio: dpr },
  );
}

/** What the OLD formula produced, for the never-fewer-pixels comparison. */
function oldScale(widthIn, cssPx, dpr, maxEdge, maxPx, heightIn) {
  const vw = widthIn * 72;
  const vh = heightIn * 72;
  let s = (cssPx / vw) * Math.min(dpr, 2) * 1.5;
  let w = vw * s; let h = vh * s;
  if (w > maxEdge) { s *= maxEdge / w; w = vw * s; h = vh * s; }
  if (h > maxEdge) { s *= maxEdge / h; w = vw * s; h = vh * s; }
  if (w * h > maxPx) { s *= Math.sqrt(maxPx / (w * h)); }
  return s;
}

const JS = viewerScript();
const scale = makeScaler(JS);
const EDGE = Number(JS.match(/var MAX_CANVAS_EDGE = (\d+);/)[1]);
const MAXPX = Number(JS.match(/var MAX_CANVAS_PX = (\d+);/)[1]);

const DEVICES = [
  ['phone       390 css, dpr 3', 390, 3],
  ['phone       360 css, dpr 3', 360, 3],
  ['tablet      768 css, dpr 2', 768, 2],
  ['tablet LS  1024 css, dpr 2', 1024, 2],
];

console.log('\n── ARCH-E 36x48: ppi before and after ───────────────────────');
let allAtLeast85 = true;
let neverFewer = true;
for (const [label, css, dpr] of DEVICES) {
  const after = scale(36, 48, css, dpr);
  const before = oldScale(36, css, dpr, EDGE, MAXPX, 48);
  const ppiBefore = 72 * before;
  const ppiAfter = 72 * after.s;
  console.log(
    `  ${label}   ${ppiBefore.toFixed(1).padStart(6)} ppi -> `
    + `${ppiAfter.toFixed(1).padStart(6)} ppi   `
    + `${(after.w * after.h / 1e6).toFixed(1)} MP  clamp=${after.clamp}`,
  );
  if (ppiAfter < 85) allAtLeast85 = false;
  if (after.s < before - 1e-9) neverFewer = false;
}

ok(allAtLeast85,
  'EVERY device now renders a 36x48 sheet at >= 85 ppi — the cap, and 2.6x what '
  + 'a phone got before');
ok(neverFewer,
  'and NO device renders it at fewer pixels than before — a floor, not a swap');

console.log('\n── the caps still bind, so the ceiling did not move ──────────');
{
  const a = scale(36, 48, 1024, 2);
  ok(Math.max(a.w, a.h) <= EDGE + 0.5,
    `the long edge is still clamped to MAX_CANVAS_EDGE (${EDGE})`);
  ok(a.w * a.h <= MAXPX + 1,
    `and the area to MAX_CANVAS_PX (${(MAXPX / 1e6).toFixed(0)} MP)`);
  ok(a.clamp !== 'none',
    'a sheet this size is clamped, which is why raising TARGET_PPI further '
    + 'changes nothing until the caps move');
  const higher = scale(36, 48, 1024, 2);
  ok(Math.abs(higher.s - a.s) < 1e-12,
    'and the clamped result is stable');
}

console.log('\n── small pages: what the floor actually does to them ─────────');
{
  // US Letter, 8.5x11. THE FIRST DRAFT OF THIS BLOCK ASSERTED "EXACTLY AS
  // BEFORE" AND FAILED, which is the point of running the arithmetic instead of
  // describing it. A phone was already BELOW 150 ppi on a letter page --
  // 390 * min(3,2) * 1.5 / 8.5in = 137.6 -- so the floor lifts it too. That is
  // the floor doing what it says rather than an accident, but it IS a change on
  // a page nobody complained about, and it is recorded here rather than
  // discovered later. Tablets are far above the floor and are untouched.
  for (const [label, css, dpr] of DEVICES) {
    const after = scale(8.5, 11, css, dpr);
    const before = oldScale(8.5, css, dpr, EDGE, MAXPX, 11);
    const ppiBefore = 72 * before;
    const ppiAfter = 72 * after.s;
    const lifted = after.s > before + 1e-9;
    console.log(
      `  letter on ${label.trim().padEnd(26)} ${ppiBefore.toFixed(1)} -> `
      + `${ppiAfter.toFixed(1)} ppi  (${lifted ? 'lifted to the floor' : 'unchanged'})`,
    );
    ok(after.s >= before - 1e-9,
      `  letter on ${label.trim()} never loses pixels`);
    ok(ppiAfter >= Math.min(ppiBefore, 150) - 0.01,
      '    ...and is never left below the floor');
  }
  const tablet = scale(8.5, 11, 1024, 2);
  ok(tablet.anchor === 'viewport',
    'a tablet is far above the floor, so the viewport term still wins there');
}

console.log('\n── the floor is what lifted the big sheet ───────────────────');
{
  const phone = scale(36, 48, 390, 3);
  ok(phone.anchor === 'ppi',
    'on a phone the ppi floor is the term that wins for a 36x48 sheet');
  ok(phone.targetPpi === Number(JS.match(/var TARGET_PPI = (\d+);/)[1]),
    'and the info object reports the constant, so the probe can see it');
}

console.log('\n── the probe A/B still means something ──────────────────────');
{
  // `over` must still change the viewport term on a page where it dominates.
  const a = scale(8.5, 11, 1024, 2, 1.0);
  const b = scale(8.5, 11, 1024, 2, 1.5);
  ok(b.s > a.s, 'over=1.5 still renders more than over=1.0 where viewport wins');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
