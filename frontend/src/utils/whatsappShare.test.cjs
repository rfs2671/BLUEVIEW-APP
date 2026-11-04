/**
 * WHATSAPP SHARE FOR PLAN NOTES -- pure helper behaviour.
 * Run: node src/utils/whatsappShare.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0; const failed = [];
function ok(c, m) { if (c) passed++; else { failed.push(m); console.error('FAIL: ' + m); } }

const full = path.join(__dirname, 'whatsappShare.js');
const code = babel.transformSync(fs.readFileSync(full, 'utf8'), {
  filename: full, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false, babelrc: false,
}).code;
const mod = { exports: {} };
new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
const W = mod.exports;
const enc = encodeURIComponent;
const LONE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

(async () => {
  ok(W.WA_MAX_ENCODED_TEXT === 1800, 'budget is 1800 encoded chars');
  ok((W.WA_URL_PREFIX + 'x'.repeat(W.WA_MAX_ENCODED_TEXT)).length < 2000, 'whole wa.me URL stays under 2000');

  const link = W.annotationLink('64f0a1b2c3d4e5f607182930');
  ok(link === 'https://levelog.com/a/64f0a1b2c3d4e5f607182930', 'link reuses the email short-link shape');
  ok(!/token|\?/.test(link), 'link carries no token or query');
  ok(W.annotationLink('') === '' && W.annotationLink(null) === '', 'no id -> no link');

  ok(W.sheetLabelFor({ name: 'A-101.pdf' }, 1) === 'A-101', 'sheet label strips .pdf');
  ok(W.sheetLabelFor({ name: 'A-101.PDF' }, 3) === 'A-101 (p. 3)', 'page appended when > 1');
  ok(W.sheetLabelFor({ path: '/Plans/S-200.pdf' }, 1) === 'S-200', 'falls back to path basename');
  ok(W.sheetLabelFor(null, 1) === '', 'no file -> empty label');

  const t = W.buildShareText({ projectName: 'Boyland', sheetLabel: 'A-101', note: 'Check the lintel', link });
  ok(t.includes('Project: Boyland') && t.includes('Sheet: A-101') && t.includes('Check the lintel'), 'has project, sheet, note');
  ok(t.endsWith(link), 'link is last');
  ok(t.indexOf('Check the lintel') < t.indexOf(link), 'note precedes link');
  ok(/login required/.test(t), 'says login required');

  const e = W.buildShareText({ projectName: 'P', sheetLabel: 'S', note: '   ', link });
  ok(!e.includes('\n\n\n') && e.endsWith(link), 'empty note: clean text, link intact');
  ok(W.buildShareText({ projectName: 'P', sheetLabel: 'S', note: undefined, link }) === e, 'undefined note == blank note');

  const long = 'word '.repeat(2000);
  const lt = W.buildShareText({ projectName: 'Boyland', sheetLabel: 'A-101', note: long, link });
  ok(enc(lt).length <= W.WA_MAX_ENCODED_TEXT, 'long note fits budget (' + enc(lt).length + ')');
  ok(lt.endsWith(link), 'link never cut on long note');
  ok(lt.includes('…\n\n'), 'ellipsis sits right before the link block');
  ok(enc(lt).length > W.WA_MAX_ENCODED_TEXT - 40, 'truncation is not wildly over-aggressive');

  const em = W.buildShareText({ projectName: 'P', sheetLabel: 'S', note: '\u{1F3D7}️'.repeat(900), link });
  ok(enc(em).length <= W.WA_MAX_ENCODED_TEXT, 'emoji note fits budget');
  ok(!LONE.test(em), 'no split surrogate pair');
  ok(em.endsWith(link), 'link intact after emoji truncation');

  const sp = W.buildShareText({ projectName: 'A & B "Tower"', sheetLabel: 'S#1', note: 'line1\r\nline2\n\n100% <ok> & ?x=1#frag', link });
  ok(sp.includes('line1\nline2') && !sp.includes('\r'), 'CRLF normalised');
  const url = W.buildWaMeUrl(sp);
  ok(url.startsWith('https://wa.me/?text='), 'wa.me url');
  ok(decodeURIComponent(url.slice(W.WA_URL_PREFIX.length)) === sp, 'wa.me text round-trips exactly');
  ok(!/[&#<> "]/.test(url.slice(W.WA_URL_PREFIX.length)), 'no raw reserved chars in the text param');

  const pp = W.buildShareText({ projectName: 'X'.repeat(5000), sheetLabel: 'Y'.repeat(5000), note: long, link });
  ok(enc(pp).length <= W.WA_MAX_ENCODED_TEXT && pp.endsWith(link), 'huge labels clamped, link intact');
  const tb = W.buildShareText({ projectName: 'P', sheetLabel: 'S', note: long, link, maxEncoded: 300 });
  ok(enc(tb).length <= 300 && tb.endsWith(link), 'small budget honoured, link intact');

  // ---- shareViaWhatsApp ----
  const file = { name: 'x.jpg' };
  const calls = [];
  const navFull = { canShare: (d) => !!d.files, share: async (d) => { calls.push(d); } };
  let r = await W.shareViaWhatsApp({ text: 'hi', file, nav: navFull, openWindow: () => { throw new Error('no'); } });
  ok(r.status === 'shared' && r.withImage && calls[0].files[0] === file && calls[0].text === 'hi', 'shares text + image when supported');

  calls.length = 0;
  r = await W.shareViaWhatsApp({ text: 'hi', file, nav: { canShare: () => false, share: async (d) => { calls.push(d); } } });
  ok(r.status === 'shared' && !r.withImage && !('files' in calls[0]), 'canShare false -> text-only share');

  calls.length = 0;
  r = await W.shareViaWhatsApp({ text: 'hi', file: null, nav: navFull });
  ok(r.status === 'shared' && !r.withImage && !('files' in calls[0]), 'note without image -> text-only');

  calls.length = 0;
  r = await W.shareViaWhatsApp({ text: 'hi', file, nav: { share: async (d) => { calls.push(d); } } });
  ok(r.status === 'shared' && !r.withImage, 'no canShare -> text-only');

  const abort = () => Object.assign(new Error('x'), { name: 'AbortError' });
  let opened = 0;
  r = await W.shareViaWhatsApp({ text: 'hi', file, nav: { canShare: () => true, share: async () => { throw abort(); } }, openWindow: () => { opened++; return {}; } });
  ok(r.status === 'cancelled' && opened === 0, 'AbortError with image = cancelled, no wa.me opened');
  r = await W.shareViaWhatsApp({ text: 'hi', nav: { share: async () => { throw abort(); } }, openWindow: () => { opened++; return {}; } });
  ok(r.status === 'cancelled' && opened === 0, 'AbortError text-only = cancelled');

  let n = 0;
  r = await W.shareViaWhatsApp({ text: 'hi', file, nav: { canShare: () => true, share: async (d) => { n++; if (d.files) throw Object.assign(new Error('x'), { name: 'NotAllowedError' }); } } });
  ok(r.status === 'shared' && !r.withImage && n === 2, 'file share failure retries text-only');

  let openedUrl = null;
  r = await W.shareViaWhatsApp({ text: 'a b', nav: { share: async () => { throw new Error('boom'); } }, openWindow: (u) => { openedUrl = u; return {}; } });
  ok(r.status === 'opened' && openedUrl === 'https://wa.me/?text=a%20b', 'share failure falls back to wa.me');

  openedUrl = null;
  r = await W.shareViaWhatsApp({ text: 'a b', file, nav: {}, openWindow: (u) => { openedUrl = u; return {}; } });
  ok(r.status === 'opened' && openedUrl === 'https://wa.me/?text=a%20b', 'no navigator.share -> wa.me text only');
  r = await W.shareViaWhatsApp({ text: 'a', nav: null, openWindow: () => ({}) });
  ok(r.status === 'opened', 'null navigator -> wa.me');

  r = await W.shareViaWhatsApp({ text: 'a', nav: {}, openWindow: () => null });
  ok(r.status === 'blocked' && r.url.startsWith('https://wa.me/'), 'popup blocked reported with url');
  r = await W.shareViaWhatsApp({ text: 'a', nav: {}, openWindow: () => { throw new Error('x'); } });
  ok(r.status === 'blocked', 'window.open throwing = blocked');

  r = await W.shareViaWhatsApp({ text: 'a', file, nav: { canShare: () => { throw new Error('x'); }, share: async () => {} } });
  ok(r.status === 'shared' && !r.withImage, 'canShare throwing -> text-only');

  ok((await W.dataUrlToFile('http://x/y.jpg')) === null && (await W.dataUrlToFile(null)) === null, 'dataUrlToFile ignores non-data-image');

  console.log(`${passed} passed, ${failed.length} failed`);
  if (failed.length) process.exit(1);
})();
