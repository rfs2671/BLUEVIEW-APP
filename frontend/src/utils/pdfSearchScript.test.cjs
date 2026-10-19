// Run: node src/utils/pdfSearchScript.test.cjs
//
// PDF search: the SAME string the staged viewer page runs (PDF_SEARCH_SCRIPT),
// evaluated in a sandbox, against pdf.js-shaped text items.
const vm = require('vm');
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/pdfSearchScript.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}
const near = (a, b) => Math.abs(a - b) < 1e-6;

const S = vm.runInNewContext(`${M.PDF_SEARCH_SCRIPT};
  ({ norm: pdfSearchNorm, build: pdfSearchBuildPage, find: pdfSearchFind, rects: pdfSearchRects })`);

// pdf.js Util.transform: the affine product m1 · m2.
const transform = (m1, m2) => [
  m1[0] * m2[0] + m1[2] * m2[1], m1[1] * m2[0] + m1[3] * m2[1],
  m1[0] * m2[2] + m1[2] * m2[3], m1[1] * m2[2] + m1[3] * m2[3],
  m1[0] * m2[4] + m1[2] * m2[5] + m1[4], m1[1] * m2[4] + m1[3] * m2[5] + m1[5],
];
// A 600 x 800 page at scale 1, as pdf.js gives it: y flipped.
const vp = { width: 600, height: 800, scale: 1, transform: [1, 0, 0, -1, 0, 800] };
// Text at (x, baseline y from the bottom), 10 pt, `w` wide.
const item = (str, x, y, w, extra) => ({ str, transform: [10, 0, 0, 10, x, y], width: w, ...extra });

const page = S.build([
  item('WINDOW PROTECTION', 60, 700, 170, { hasEOL: true }),
  item('See SSP-011.00 for', 60, 680, 180),
  item('window', 245, 680, 60),
  item('   ', 0, 0, 0),
  item('screens', 310, 680, 70),
], vp, transform);

ok(page.text === 'window protection see ssp-011.00 for window screens', 'the page text, lowercased, runs joined');
ok(page.spans.length === 4, 'blank runs carry no box');
ok(S.norm('  Window   Protection ') === 'window protection', 'the query: lowercased, spaces collapsed');

const hits = S.find(page, S.norm('Window'));
ok(hits.length === 2 && hits[0][0] === 0 && hits[1][0] === page.text.indexOf('window screens'),
   'both "window"s, any case');
ok(S.find(page, 'ssp-011').length === 1, 'a sheet number');
ok(S.find(page, 'for window').length === 1, 'across two runs');
ok(S.find(page, 'roof').length === 0 && S.find(page, '').length === 0 && S.find(null, 'x').length === 0,
   'nothing, an empty query, no page');
ok(S.find({ text: 'aaaa', spans: [] }, 'aa').length === 2, 'matches do not overlap');

// Where "WINDOW" sits: x 60..120 (6 of 17 chars of 170), the 10-pt line
// above the baseline at y 700 from the bottom = 100 from the top.
const [r] = S.rects(page, hits[0][0], hits[0][1]);
ok(near(r.x, 60 / 600) && near(r.w, (170 * 6 / 17) / 600), 'the box starts and ends at the word');
ok(near(r.y, 90 / 800) && near(r.h, 10 / 800), 'the box is the line the word is on');

const across = S.rects(page, page.text.indexOf('for window'), page.text.indexOf('for window') + 'for window'.length);
ok(across.length === 2, 'a match across two runs is two boxes');

// Measured, not counted: in a proportional font "WWW" is wider than "iii",
// so a word after them starts further along than its character index says.
// (The footer of the sample report was one run, and counting put the box a
// word early.)
const wide = S.build([item('WWWiii daily', 0, 700, 120, { fontName: 'f1' })], vp, transform,
  { f1: { fontFamily: 'sans-serif' } });
const widths = { W: 3, i: 1, ' ': 1, d: 2, a: 2, l: 1, y: 2 };
const fonts = [];
const measure = (str, font) => { fonts.push(font); return [...str].reduce((t, c) => t + (widths[c] || 2), 0); };
const at = wide.text.indexOf('daily');
const [counted] = S.rects(wide, at, at + 5);
const [measured] = S.rects(wide, at, at + 5, measure);
// "WWWiii " = 9+3+1 = 13 of 13+8 = 21 units; 120 * 13/21 ≈ 74.3 (counted: 120 * 7/12 = 70).
ok(near(counted.x, (120 * 7 / 12) / 600) && near(measured.x, (120 * 13 / 21) / 600),
   'a word inside a run starts where its measured width says');
ok(fonts.every((f) => f === 'sans-serif'), "measured in the run's own font family");
ok(near(S.rects(wide, at, at + 5, () => 0)[0].x, counted.x), 'nothing measurable: back to counting');

// Vertical text (rotated 90°): the box stands up.
const vpage = S.build([{ str: 'GRID A', transform: [0, 10, -10, 0, 500, 100], width: 60 }], vp, transform);
const [vr] = S.rects(vpage, 0, 6);
ok(vr && vr.h > vr.w && near(vr.h, 60 / 800), 'vertical text gives a standing box');

// A page with no text layer (a scan).
const scan = S.build([], vp, transform);
ok(scan.text === '' && S.find(scan, 'window').length === 0, 'a scanned page: nothing to find');

// The search bar's words.
ok(M.searchStatusLabel({ total: 12, current: 3, done: true }, 'window') === '3 of 12', 'n of total');
ok(M.searchStatusLabel({ total: 4, current: 1, done: false }, 'window') === '1 of 4+', 'still searching: more may come');
ok(M.searchStatusLabel({ total: 0, done: false }, 'window') === 'Searching…', 'searching');
ok(M.searchStatusLabel({ total: 0, done: true, hasText: true }, 'roof') === 'No matches', 'no matches');
ok(M.searchStatusLabel({ total: 0, done: true, hasText: false }, 'roof') === 'No searchable text in this PDF',
   'a scan says so, not "no matches"');
ok(M.searchStatusLabel(null, 'x') === '' && M.searchStatusLabel({ total: 1 }, '  ') === '', 'nothing asked');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
