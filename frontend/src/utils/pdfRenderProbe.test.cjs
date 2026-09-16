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
  // MEASURE, not PROBE — caps mode has to be able to emit, and it carries no
  // feature flag. The property is unchanged: with neither mode on, nothing
  // is posted.
  ok(/function probePost\(kind, data\)\{[\s\S]{0,60}if \(!MEASURE\) return;/.test(script),
    'probePost returns early when neither probe nor caps mode is on');
  ok(/var MEASURE = PROBE \|\| CAPS;/.test(script),
    'MEASURE is exactly "probe mode or caps mode"');

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
  // The component now builds the DOCUMENT-FREE host url — the document arrives
  // by postMessage — but the property this check exists for is unchanged: the
  // flag, and only the flag, reaches the url builder.
  ok(/localViewerHostUrl\(localViewerUri, \{ probe: probeOn \}\)/.test(componentSrc),
    'the component passes the flag into the url builder');
  const hostFn = /export function localViewerHostUrl\(viewerUri, opts\) \{[\s\S]*?\n\}/.exec(viewerSrc);
  ok(!!hostFn, 'localViewerHostUrl takes an opts argument');
  if (hostFn) {
    const code = hostFn[0]
      .split('\n')
      .filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('*'))
      .join('\n');
    ok(/const probe = opts && opts\.probe \? '\?probe=1' : '';/.test(code),
      'the host url gains probe=1 only when the flag is on');
    ok(!/probe=0/.test(code), 'and never emits probe=0 on the host url either');
  }
  ok(/useFeatureFlag\('pdf_viewer_probe'\)/.test(componentSrc),
    'the gate is the pdf_viewer_probe feature flag, not a constant');
}

// ── 5. THE STAMP MOVED ───────────────────────────────────────────────────
{
  const m = /const VIEWER_VERSION = '(\d+)';/.exec(viewerSrc);
  ok(!!m, 'VIEWER_VERSION is present');
  ok(m && Number(m[1]) >= 5,
    'VIEWER_VERSION bumped so staged devices re-write viewer.html',
    m ? `found '${m[1]}', expected >= 5` : '');
}

// ── 11. THE ENGINE DECISION GETS A MEASUREMENT, NOT AN INFERENCE ─────────
{
  // JBIG2/CCITT is the strongest form of the PDFium argument; DCTDecode
  // collapses it. That distinction is not available from getOperatorList —
  // pdf.js resolves an image object to a DECODED bitmap with the source filter
  // already consumed — so it has to come from the file's own bytes.
  ok(/function probeImageFilters\(next\)\{/.test(script),
    'embedded image compression is measured');
  for (const f of ['JBIG2Decode', 'CCITTFaxDecode', 'DCTDecode', 'JPXDecode']) {
    ok(script.includes(`"${f}"`), `the image-only filter ${f} is scanned for`);
  }
  ok(/out\.verdict = out\.bilevel \?/.test(script),
    'the scan reports a verdict, not seven raw counts to re-derive');
  ok(/bytes = null;/.test(script.slice(script.indexOf('function probeImageFilters'))),
    'the scan drops the buffer it re-read');
  // The decoded-kind shadow is useful but must not be presented as the answer.
  ok(/decodedKinds/.test(script),
    'ImageKind is captured alongside, as the operator-list shadow of the filter');
  // Cheap measurement before the expensive one: a device that dies on the
  // worker A/B has still reported the compression.
  const filtersAt = script.indexOf('probeImageFilters(function()');
  const workerAt = script.indexOf('probeWorkerAB(function()');
  ok(filtersAt > 0 && workerAt > filtersAt,
    'the filter scan runs before the worker A/B',
    `filters@${filtersAt} worker@${workerAt}`);
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
  ok(/probeWorkerSource\(function\(\)\{/.test(script),
    'the source read runs inside the capability sequence');
}

// ── 12. CAPS MODE: ONE IMPLEMENTATION, AND IT CANNOT TOUCH A DOCUMENT ────
{
  // The site device is offline by design and may never take a flag refresh, so
  // the capability read cannot depend on the feature flag. A SECOND page would
  // drift from the viewer's copy and stop the two devices being comparable
  // line for line — hence a mode, not a page.
  ok(/var CAPS = param\("caps"\) === "1";/.test(script),
    'caps mode is its own url flag, independent of the feature flag');

  // WAS: "caps runs before the no-file guard". That guard is gone — the page
  // no longer takes its document from the url at all, because a url that
  // changed per document made every open a WebView NAVIGATION and re-parsed
  // 1.5 MB of pdf.js. The PROPERTY is unchanged and is what is asserted here:
  // caps mode returns before anything that touches a document can run.
  const capsAt = script.indexOf('if (CAPS) {');
  const libAt = script.indexOf('if (typeof pdfjsLib === "undefined")');
  const openAt = script.indexOf('function openDocument(url){');
  ok(capsAt > 0 && libAt > capsAt && openAt > capsAt,
    'the caps short-circuit runs BEFORE the library guard and before any '
    + 'document can be opened',
    `caps@${capsAt} lib@${libAt} open@${openAt}`);
  // The short-circuit is only a short-circuit if it returns.
  const capsBlock = script.slice(capsAt, capsAt + 400);
  ok(/\n\s*return;\n\s*\}/.test(capsBlock),
    'and it returns rather than falling through into the document path');
  ok(/probePost\("caps", \{ done: true \}\)/.test(script),
    'caps mode posts a completion marker — "still running" and "answered nothing" must differ');

  // The one guard that must NOT have been widened. probeSuite opens a page and
  // renders it; caps mode has no document and must never reach it.
  ok(/function probeSuite\(\)\{[\s\S]{0,40}if \(!PROBE\) return;/.test(script),
    'probeSuite is still PROBE-only, so caps mode cannot reach a render');
  ok(!/function probeSuite\(\)\{[\s\S]{0,40}if \(!MEASURE\)/.test(script),
    'probeSuite was not widened to MEASURE');

  // Three of the six issue an XHR; in viewer mode the document read starts in
  // the same breath. Firing them together would distort the throughput figure
  // and the open being measured.
  ok(/function capabilityRead\(after\)\{/.test(script),
    'the six run through one sequencer');
  const seq = script.slice(script.indexOf('function capabilityRead(after){'));
  const nested = /probeBlobWorker\(function\(\)\{[\s\S]{0,400}probeWorkerSource\(function\(\)\{[\s\S]{0,400}probeWasm\(function\(\)\{[\s\S]{0,400}probeBinaryRead\(function\(\)\{/.test(seq);
  ok(nested, 'the four async reads are sequenced, not fired in parallel');
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
  // ⚠️ DELIBERATELY RE-PINNED, NOT SLIPPED PAST. This block exists to force a
  // failure when a cap moves; two moved, and each is re-pinned WITH THE REASON
  // beside it so the next change has to argue with the reason and not just
  // with a number.
  //
  // MAX_CANVAS_EDGE stays 4096, and that is a decision and not an oversight.
  // An earlier draft of this branch raised it to a measured 16384 on the
  // argument that 11 of the 16 budgeted megapixels were never used. The
  // binding constraint has since changed: with a real worker the parse and the
  // image decode are off the UI thread and what is left on it is PAINT, which
  // is the one cost that does scale with pixels — and the acceptance criterion
  // now in play is a main-thread stall under 200 ms. There is no measurement
  // saying a 16 MP sheet paints inside that. 4096 is the value that has been
  // in the field for months and the one the operator's 11.2 MP / 701 ms
  // ceiling reading was taken at.
  ok(/var MAX_CANVAS_EDGE = 4096;/.test(script), 'MAX_CANVAS_EDGE unchanged (4096)');
  // BAND 1.5 -> 0.6. 1.5 spanned four viewport heights and was sized for a
  // viewer that drew a 1.2 MP sheet with the PPI floor off until someone
  // pinched. Every sheet is now drawn at the floor, so a band of five is 63 MP
  // queued before the reader has touched anything — work the budget would
  // immediately throw away. 0.6 is a viewport height either side: the reader's
  // sheet plus one, which is the depth the budget can hold.
  ok(/var BAND = 0\.6;/.test(script),
    'BAND is 0.6 — the reader\'s sheet plus one either side, matched to the budget');
  // KEEP_RENDERED is GONE, not retuned. It never bound anything: trim() skipped
  // any page marked `visible`, and `visible` was the BAND. The replacement is a
  // megapixel budget whose one protection rule is "on screen".
  ok(!/var KEEP_RENDERED/.test(script),
    'the page-count window is gone — it never bound anything');
  ok(/var CANVAS_BUDGET_MP = 32;/.test(script),
    'and the resident bitmap is bounded in megapixels instead (32 MP = 128 MB)');
  ok(/var MAX_CONCURRENT_RENDERS = 1;/.test(script),
    'and exactly one rasterisation may be in flight');
}

// ── 6b. THE WORKER IS BUILT BY THE PAGE, AND THE FALLBACK IS AUDIBLE ─────
//
// The probe measured `workerpath verdict: FAKE` on a device where a blob
// worker does page 1 in 618 ms, and the cause was a deliberate `<script
// src="pdf.worker.min.js">` in the page. These pin the shape of the fix so it
// cannot be reverted by accident: the tag stays out, the source is read with
// XHR (fetch is rejected on a file:// origin — measured), and every path out
// of the setup posts on the ORDINARY channel.
{
  const raw = viewerSrc;
  const html = raw.slice(raw.indexOf('function viewerHtml()'), raw.indexOf('const VIEWER_SCRIPT'));
  ok(!/<script src="' \+ WORKER_NAME/.test(html),
    'the page does not load pdf.worker.min.js as a <script> — that tag is what made '
    + 'pdf.js short-circuit to its main-thread handler');
  ok(/function ensureWorker\(done\)\{/.test(script),
    'the page sets its own worker up');
  ok(/GlobalWorkerOptions\.workerPort = w;/.test(script),
    'via workerPort — workerSrc would send pdf.js back through the blocked construction');
  ok(/readText\("pdf\.worker\.min\.js"/.test(script),
    'reading the source with XHR, which is what works on a file:// origin');
  ok(!/fetch\("pdf\.worker\.min\.js"\)[\s\S]{0,200}createObjectURL/.test(script),
    'and not with fetch(), which that origin rejects');
  // EVERY exit from settleWorker posts, probe or no probe. A silent fallback
  // is how the main-thread worker survived unnoticed.
  const settle = script.slice(script.indexOf('function settleWorker(mode, reason){'));
  ok(/post\(\{ type: "pdf-worker", mode: mode, reason: workerReason \}\);/.test(settle.slice(0, 700)),
    'and says which worker it ended up with on the ordinary channel, not behind the probe flag');
  ok(/if \(workerSettled\) return;/.test(settle.slice(0, 200)),
    'exactly once');
  // AND THE HOST HAS TO DO SOMETHING WITH IT. A message nothing handles is the
  // same silence in a different place.
  ok(/msg\?\.type === 'pdf-worker'/.test(componentSrc),
    'and the host handles pdf-worker rather than dropping it on the floor');
  ok(/\[pdfworker\] mode=/.test(componentSrc),
    'logging which worker is live');
  ok(/pdf-worker'\)[\s\S]{0,600}probeLines\.current\.push/.test(componentSrc),
    'and putting it in the shareable report, which is the artefact the operator '
    + 'actually sends back');
}

// ── 6c. THE EXPENSIVE PROBES CANNOT RUN FOR A READER WHO DID NOT ASK ─────
//
// ITEM 5, PINNED. `probeCanvasLimits` walks a ladder to 16384x16384 — about a
// gigabyte of allocation — and `probeImageFilters` scans every operator of
// page 1. Both are gated on `MEASURE = PROBE || CAPS`, both of which come from
// URL params, so neither can run in the shipping viewer. That was already true
// and nothing asserted it; this is what stops a later edit widening one of
// them without noticing.
{
  ok(/function probeCanvasLimits\(\)\{\s*if \(!MEASURE\) return;/.test(script),
    'the canvas-limit ladder refuses to run unless probe=1 or caps=1');
  ok(/function probeImageFilters\(next\)\{\s*if \(!PROBE\) \{ if \(next\) next\(\); return; \}/.test(script),
    'and the image-filter scan is narrower still — PROBE only');
  // AND NOTHING ELSE MAY CALL THEM. A guard is only as good as the set of
  // callers it covers, so the callers are counted rather than assumed.
  const ladderCalls = (script.match(/probeCanvasLimits\(\)/g) || []).length;
  ok(ladderCalls === 2,
    'the ladder has exactly one call site besides its declaration',
    `found ${ladderCalls} occurrences`);
  const capsBody = script.slice(script.indexOf('function capabilityRead(after){'),
    script.indexOf('function capabilityRead(after){') + 600);
  ok(/if \(!MEASURE\) \{ if \(after\) after\(\); return; \}/.test(capsBody)
    && /probeCanvasLimits\(\);/.test(capsBody),
    'and that call site is inside capabilityRead, behind the same MEASURE gate');
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
