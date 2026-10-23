/**
 * THE WEB VIEWER NEVER PUTS THE SESSION TOKEN IN A URL.
 *
 * Before: `<iframe src="https://api…/files/{id}/content?token=<30-day JWT>">`, so
 * the credential sat in the iframe url, the browser history and every proxy and
 * access log between the tab and the API.
 *
 * Now: our own proxy is fetched with `Authorization: Bearer` into a Blob and the
 * iframe is given a `blob:` url (utils/pdfSrc.js resolvePdfForIframe). A
 * presigned / foreign url is used bare. There is no query-token fallback.
 *
 * Runs the REAL module; the viewer component is read as source for the wiring.
 * Run:  node src/utils/pdfWebBlob.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const FRONTEND = path.join(__dirname, '..', '..');
function load(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}
const S = load('src/utils/pdfSrc.js');

const API = 'https://api.levelog.com';
const PROXY = '/api/projects/p1/files/f1/content';

class FakeBlob {
  constructor(parts, opts) { this.parts = parts; this.type = (opts && opts.type) || ''; }
}
function harness(response) {
  const calls = { fetch: [], created: [], revoked: [] };
  return {
    calls,
    deps: {
      fetchImpl: async (url, init) => { calls.fetch.push({ url, init }); return response; },
      createObjectURL: (b) => { calls.created.push(b); return `blob:https://app/${calls.created.length}`; },
      revokeObjectURL: (u) => calls.revoked.push(u),
      BlobImpl: FakeBlob,
    },
  };
}
const okResponse = (type) => ({ ok: true, status: 200, blob: async () => new FakeBlob(['%PDF'], { type }) });

(async () => {
  // our own proxy: header auth, blob url, no token anywhere in a url
  let h = harness(okResponse('application/pdf'));
  let r = await S.resolvePdfForIframe(PROXY, { apiBase: API, token: 'JWT.SECRET.VALUE', ...h.deps });
  ok(r && r.kind === 'blob' && r.src.startsWith('blob:'), 'our own proxy resolves to a blob: url');
  ok(h.calls.fetch.length === 1 && h.calls.fetch[0].url === `${API}${PROXY}`, 'it fetched the absolute proxy url, with no query string');
  ok(h.calls.fetch[0].init.headers.Authorization === 'Bearer JWT.SECRET.VALUE', 'the token travels in the Authorization header');
  ok(!/token/i.test(h.calls.fetch[0].url) && !r.src.includes('JWT'), 'the token is in no url, fetched or displayed');

  // a server that labels the bytes octet-stream still gets a pdf blob (an iframe will not render it otherwise)
  h = harness(okResponse('application/octet-stream'));
  r = await S.resolvePdfForIframe(PROXY, { apiBase: API, token: 't', ...h.deps });
  ok(h.calls.created[0].type === 'application/pdf', 'the blob is typed application/pdf whatever the server said');

  // revoke frees the blob once, and only once
  r.revoke(); r.revoke();
  ok(h.calls.revoked.length === 1, 'revoke frees the blob url exactly once');

  // presigned / foreign urls: no fetch, no token, returned bare
  h = harness(okResponse('application/pdf'));
  r = await S.resolvePdfForIframe('https://files.example.r2.cloudflarestorage.com/x.pdf?X-Amz-Signature=abc', { apiBase: API, token: 'T', ...h.deps });
  ok(r.kind === 'remote' && r.src.includes('X-Amz-Signature=abc') && !r.src.includes('token='), 'a presigned url is used bare');
  ok(h.calls.fetch.length === 0, 'a presigned url is never fetched through us');
  r = await S.resolvePdfForIframe(`https://evil.example.com${PROXY}`, { apiBase: API, token: 'T', ...h.deps });
  ok(r.kind === 'remote' && !r.src.includes('T') && h.calls.fetch.length === 0, 'a url merely SHAPED like ours, on another origin, gets nothing');

  // failures are errors, never silently retried with a query token
  for (const status of [401, 403, 404, 500]) {
    h = harness({ ok: false, status });
    let err = null;
    try { await S.resolvePdfForIframe(PROXY, { apiBase: API, token: 't', ...h.deps }); } catch (e) { err = e; }
    ok(err && err.name === 'PdfFetchError' && err.status === status, `a ${status} is a PdfFetchError carrying the status`);
    ok(h.calls.fetch.length === 1, `a ${status} is not retried with a token in the url`);
  }
  ok((await S.resolvePdfForIframe('', { apiBase: API })) === null, 'an empty url resolves to null');

  // the component: wired to the helper, and no token url is built anywhere
  const src = fs.readFileSync(path.join(FRONTEND, 'src/components/PDFViewerWeb.jsx'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  ok(/resolvePdfForIframe/.test(code), 'the Web viewer resolves its document through resolvePdfForIframe');
  ok(!/authorizedPdfUrl/.test(code), 'the Web viewer no longer imports authorizedPdfUrl');
  ok(!/encodeURIComponent\(\s*token/.test(code) && !/[?&]token=\$\{/.test(code), 'the Web viewer builds no token url');
  ok(/revoke\(\)/.test(code), 'the Web viewer revokes the blob url when it closes or reloads');
  ok(/<iframe[\s\S]*?src=\{url\}/.test(code), 'the iframe shows exactly the resolved src');

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
