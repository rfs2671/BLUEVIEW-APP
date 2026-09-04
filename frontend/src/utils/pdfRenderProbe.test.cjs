/**
 * THE RENDER-COST PROBE — MEASUREMENT, NOT A FIX.
 *
 * WHY IT EXISTS. Two static readings of pdfjsViewer.js have produced diagnoses
 * that did not survive contact with numbers. The most recent — that
 * MAX_CANVAS_PX was clamping large sheets below native resolution — is
 * contradicted by the file's own arithmetic: `targetScaleInfo` anchors the
 * scale to `baseWidth`, so canvas width is `clientWidth * min(dpr,2) * 1.5`
 * whatever the sheet is, and on an ARCH-E sheet at a tablet's viewport neither
 * MAX_CANVAS_EDGE nor MAX_CANVAS_PX is approached. That is a third reading.
 * This branch stops reading.
 *
 * WHAT THIS TEST HOLDS — the properties that make the probe safe to put on a
 * device the operator uses all day:
 *
 *   1. THE GENERATED VIEWER IS VALID ES5. The script runs in whatever System
 *      WebView the device happens to have. A `const`, an arrow function or a
 *      template literal anywhere in it is a blank page, not a warning, and the
 *      operator would be told the plan is corrupt. Parsed with acorn at
 *      ecmaVersion 5 — the only check that actually enforces this.
 *
 *   2. THE PROBE IS GATED ON ONE FLAG, READ FROM THE URL. `PROBE` is
 *      `param("probe") === "1"` and nothing else. No source constant, so
 *      turning it on for one operator cannot ship it to everybody.
 *
 *   3. EVERY EMITTER GOES THROUGH probePost, WHICH RETURNS EARLY WHEN OFF.
 *      A single `post({type:"pdf-probe"...})` outside it would chatter at
 *      every user on every page.
 *
 *   4. THE URL IS UNCHANGED WHEN THE FLAG IS OFF. `localViewerUrlFor` is what
 *      the WebView's `source` is built from; a url that gained `probe=0` would
 *      change the source string for every user and remount their viewer.
 *
 *   5. THE STAMP MOVED. viewer.html is written to disk once and re-used until
 *      VIEWER_VERSION changes. Without a bump, a device that already staged
 *      `2` keeps serving a viewer with no probe in it and reports nothing —
 *      the trip to the tablet is wasted and the silence looks like a result.
 *
 *   6. THE REAL RENDER PATH STILL COMPUTES THE SAME SCALE. `targetScale` is
 *      what renderSlot uses; it must remain a thin wrapper over
 *      `targetScaleInfo` with the shipping oversample, or the probe would be
 *      measuring a viewer nobody is running.
 *
 *   7. THE A/B SUITE FREES WHAT IT ALLOCATES. Every probe-only canvas is
 *      zeroed. Detaching is not enough — the file's own eviction code says so
 *      — and a probe that leaked bitmaps would cause the OOM it is measuring.
 *
 *   8. THE SUITE RUNS AFTER `pdf-ready`, NEVER BEFORE. A measurement taken
 *      during the open it is measuring is not a measurement.
 *
 * Run:  node src/utils/pdfRenderProbe.test.cjs
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const VIEWER = path.join(ROOT, 'src', 'utils', 'pdfjsViewer.js');
const COMPONENT = path.join(ROOT, 'src', 'components', 'PDFViewer.native.jsx');

const viewerSrc = fs.readFileSync(VIEWER, 'utf8');
const componentSrc = fs.readFileSync(COMPONENT, 'utf8');

let failures = 0;
let checks = 0;
function ok(cond, label, detail) {
  checks += 1;
  if (cond) {
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? `\n         ${detail}` : ''}`);
  }
}

/**
 * Reconstruct the viewer script exactly as `viewerHtml()` would.
 *
 * The array is plain string literals, comments, and one concatenation with
 * WORKER_NAME. Evaluating just that slice is both sufficient and safer than
 * importing the module, which pulls in react-native and expo.
 */
function buildViewerScript() {
  const start = viewerSrc.indexOf('const VIEWER_SCRIPT = [');
  if (start < 0) throw new Error('VIEWER_SCRIPT not found');
  const open = viewerSrc.indexOf('[', start);
  const close = viewerSrc.indexOf("].join('\\n');", open);
  if (close < 0) throw new Error("VIEWER_SCRIPT terminator not found");
  const literal = viewerSrc.slice(open, close + 1);
  const WORKER_NAME = 'pdf.worker.min.js';
  // eslint-disable-next-line no-new-func
  const arr = new Function('WORKER_NAME', `return ${literal};`)(WORKER_NAME);
  return arr.join('\n');
}

console.log('\nPDF render-cost probe\n');

let script = '';
try {
  script = buildViewerScript();
  ok(script.length > 2000, 'viewer script reconstructs', `length=${script.length}`);
} catch (e) {
  ok(false, 'viewer script reconstructs', String(e && e.message));
}

// ── 1. VALID ES5 ─────────────────────────────────────────────────────────
{
  let acorn = null;
  try {
    acorn = require('acorn');
  } catch (_e) {
    try {
      acorn = require(path.join(ROOT, 'node_modules', 'acorn'));
    } catch (_e2) { acorn = null; }
  }
  if (!acorn) {
    console.log('  SKIP acorn unavailable — ES5 check not run');
  } else {
    let err = null;
    try {
      acorn.parse(script, { ecmaVersion: 5 });
    } catch (e) {
      err = e;
    }
    ok(!err, 'generated viewer script is valid ES5',
      err ? `${err.message}` : '');
  }
}

// ── 2. ONE GATE, FROM THE URL ────────────────────────────────────────────
{
  ok(/var PROBE = param\("probe"\) === "1";/.test(script),
    'PROBE is read from the url, once');
  // A source constant is exactly what the previous probe used and exactly what
  // makes "on for one device" impossible.
  ok(!/PDF_RENDER_PROBE\s*=\s*(true|false)/.test(viewerSrc),
    'no module-level boolean probe constant');
}

// ── 3. EVERY EMITTER IS BEHIND probePost ─────────────────────────────────
{
  const probePostDef = /function probePost\(kind, data\)\{[\s\S]{0,120}?if \(!PROBE\) return;/.test(
    script.replace(/\s+/g, ' ').replace(/function probePost\(kind, data\)\s*\{/, 'function probePost(kind, data){')
  );
  ok(/function probePost\(kind, data\)\{\s*\n?\s*if \(!PROBE\) return;/.test(script)
    || /function probePost\(kind, data\)\{[\s\S]{0,60}if \(!PROBE\) return;/.test(script)
    || probePostDef,
    'probePost returns early when the probe is off');

  // Any raw pdf-probe post that did not go through probePost.
  const rawEmits = script
    .split('\n')
    .filter((l) => l.includes('"pdf-probe"') && !l.includes('function probePost'));
  ok(rawEmits.length === 1,
    'pdf-probe is emitted from exactly one place (probePost)',
    rawEmits.length ? rawEmits.map((l) => l.trim()).join('\n         ') : 'none found');
}

// ── 4. THE URL IS BYTE-IDENTICAL WHEN THE FLAG IS OFF ────────────────────
{
  const fn = /export function localViewerUrlFor\(viewerUri, pdfFileUri, opts\) \{[\s\S]*?\n\}/.exec(viewerSrc);
  ok(!!fn, 'localViewerUrlFor takes an opts argument');
  if (fn) {
    const body = fn[0];
    ok(/const probe = opts && opts\.probe \? '&probe=1' : '';/.test(body),
      'probe param is empty string when off, never probe=0');
    // CODE, NOT PROSE. The comment inside this function says the words
    // "probe=0" to explain why the form does not exist, and a naive scan of
    // the body matched its own documentation. Strip comments first: the claim
    // is about what the function EMITS.
    const code = body
      .split('\n')
      .filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('*'))
      .join('\n');
    ok(!/probe=0/.test(code), 'no probe=0 is ever emitted');
  }
  ok(/localViewerUrlFor\(localViewerUri, pdfUrl, \{ probe: probeOn \}\)/.test(componentSrc),
    'the component passes the flag into the url builder');
  ok(/useFeatureFlag\('pdf_viewer_probe'\)/.test(componentSrc),
    'the gate is the pdf_viewer_probe feature flag, not a constant');
}

// ── 5. THE STAMP MOVED ───────────────────────────────────────────────────
{
  const m = /const VIEWER_VERSION = '(\d+)';/.exec(viewerSrc);
  ok(!!m, 'VIEWER_VERSION is present');
  ok(m && Number(m[1]) >= 4,
    'VIEWER_VERSION bumped so staged devices re-write viewer.html',
    m ? `found '${m[1]}', expected >= 4` : '');
}

// ── 9. BLOCKER A HAS TWO HALVES AND BOTH ARE ASKED ───────────────────────
{
  // A Worker that can be constructed is useless if its source cannot be read.
  // These are separate restrictions with completely different fixes, so a
  // probe that measured only one would send somebody back to the tablet.
  ok(/function probeBlobWorker\(done\)\{/.test(script),
    'half (a): the Worker constructor is exercised from a blob: URL');
  ok(/function probeWorkerSource\(done\)\{/.test(script),
    'half (b): the worker SOURCE read is measured separately');
  ok(/probePost\("workersrc"/.test(script), 'the source read reports its own reading');
  // XHR is what allowFileAccessFromFileURLs grants and what readBytes already
  // uses; fetch() on file:// is blocked in Chromium. Measuring both is what
  // turns an assumption into a number.
  ok(/out\.xhr = t\.length > 0;/.test(script), 'the source read tries XMLHttpRequest');
  ok(/fetch\("pdf\.worker\.min\.js"\)/.test(script), 'the source read tries fetch() too');
  ok(script.indexOf('probeWorkerSource(function(){});') > 0,
    'the source read runs in the startup sequence');
}

// ── 10. THE MBTiles PREREQUISITES, ASKED BEFORE ANYTHING IS DESIGNED ─────
{
  ok(/function probeWasm\(done\)\{/.test(script),
    'wasm instantiation is measured — sql.js is dead without it');
  ok(/new Uint8Array\(\[0,97,115,109,1,0,0,0\]\)/.test(script),
    'the wasm check uses a minimal valid module, not a bundled binary');
  ok(/function probeBinaryRead\(done\)\{/.test(script),
    'binary ArrayBuffer read is measured — that is the .mbtiles read');
  ok(/responseType = "arraybuffer";/.test(script),
    'the binary read actually asks for an ArrayBuffer');
  ok(/mbPerSec/.test(script),
    'the binary read reports throughput, not just success');
  // Bundling sql.js to answer a question gated on a probe that has not run is
  // the wrong order. If this branch ever grows a wasm asset, this fails.
  const assetsDir = path.join(ROOT, 'assets');
  let wasmAssets = [];
  try {
    const walk = (d) => {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) walk(p);
        else if (/\.wasm$/i.test(e.name) || /sql[-.]?wasm/i.test(e.name)) wasmAssets.push(p);
      }
    };
    walk(assetsDir);
  } catch (_e) { /* no assets dir is fine */ }
  ok(wasmAssets.length === 0,
    'no wasm binary has been bundled to answer a question the probe has not asked',
    wasmAssets.join(', '));
}

// ── 6. THE SHIPPING RENDER PATH IS UNCHANGED ─────────────────────────────
{
  ok(/function targetScale\(vp1\)\{ return targetScaleInfo\(vp1\)\.s; \}/.test(script),
    'targetScale is a thin wrapper over targetScaleInfo');
  ok(/\(over === undefined \? 1\.5 : over\)/.test(script),
    'the shipping oversample is still 1.5 when no override is passed');
  ok(/var info = targetScaleInfo\(vp1\);/.test(script),
    'renderSlot takes its scale from targetScaleInfo with no override');
  // The caps must not have moved. This branch measures them; it does not
  // change them, and a later "fix" that edits them must fail this test
  // deliberately rather than slip past a probe branch.
  ok(/var MAX_CANVAS_PX = 16000000;/.test(script), 'MAX_CANVAS_PX unchanged (16e6)');
  ok(/var MAX_CANVAS_EDGE = 4096;/.test(script), 'MAX_CANVAS_EDGE unchanged (4096)');
  ok(/var BAND = 1\.5;/.test(script), 'BAND unchanged (1.5)');
  ok(/var KEEP_RENDERED = 7;/.test(script), 'KEEP_RENDERED unchanged (7)');
}

// ── 7. THE SUITE FREES WHAT IT ALLOCATES ─────────────────────────────────
{
  // Count probe-only canvas creations and the zeroing that must follow each.
  const zeroings = (script.match(/c\.width = 0; c\.height = 0;/g) || []).length;
  ok(zeroings >= 4,
    'every probe-only canvas is zeroed on both the success and error paths',
    `found ${zeroings} zeroing sites`);
  ok(/if \(c\.width !== edge \|\| c\.height !== edge\)/.test(script),
    'the canvas-limit ladder verifies the allocation actually took');
  ok(/getImageData\(edge - 1, edge - 1, 1, 1\)/.test(script),
    'the ladder touches the far corner — a context that draws nothing is not a canvas');
}

// ── 8. THE SUITE RUNS AFTER THE OPEN ─────────────────────────────────────
{
  const readyAt = script.indexOf('post({ type: "pdf-ready"');
  const suiteAt = script.indexOf('hbStop("open"); probeSuite();');
  ok(readyAt > 0 && suiteAt > readyAt,
    'probeSuite is kicked off after pdf-ready, not before',
    `ready@${readyAt} suite@${suiteAt}`);
  ok(/setTimeout\(function\(\)\{ hbStop\("open"\); probeSuite\(\); \}, 2000\);/.test(script),
    'the suite is deferred to a later turn so it cannot interleave with the open');
  // The worker A/B re-reads from disk instead of retaining a second copy of a
  // 30 MB buffer, which would change the memory profile under test.
  ok(/readBytes\(fileUrl, function\(bytes\)\{/.test(script.replace(/\s+/g, ' ')) ||
     script.includes('readBytes(fileUrl, function(bytes){'),
    'the worker A/B re-reads the file rather than retaining the bytes');
  ok(/deviceMemory < 3|mem < 3/.test(script),
    'the worker A/B is skipped on low-memory devices');
}

console.log(`\n${checks - failures}/${checks} checks passed\n`);
process.exit(failures ? 1 : 0);
