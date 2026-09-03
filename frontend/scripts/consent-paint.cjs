#!/usr/bin/env node
/**
 * THE CONSENT SCREEN, MOUNTED AS THE PERSON IT IS FOR — and made to paint.
 *
 * ── WHY THIS EXISTS AND WHY smoke-mount DID NOT CATCH IT ────────────────────
 *
 * Between 2026-09-01 and 2026-09-03 every CP signature on the platform was
 * blocked. He tapped Sign, waited about two seconds, and landed on his home
 * screen. He was never asked to consent — the screen never rendered. Eight
 * hours of server logs show 33 GETs of /api/esra-consent and ZERO POSTs: the
 * route mounted, read, and was unwound before it painted anything.
 *
 * The cause was RouteGuard in app/_layout.jsx. A CP may only be on /logbooks*,
 * /documents, /settings or /login; anything else is `router.replace('/logbooks')`.
 * `/consent` was never added to that list, so the consent gate pushed him onto
 * a route the guard immediately bounced him off.
 *
 * scripts/smoke-mount.cjs already mounts `/consent` and was green throughout.
 * TWO REASONS, AND BOTH ARE THE POINT OF THIS FILE:
 *
 *   1. IT SIGNS IN AS AN OWNER. The guard's CP arm never ran, so the one
 *      condition that breaks this route was never created.
 *   2. IT ASKS ONLY "DID ANYTHING THROW". A screen that is redirected away
 *      before it paints throws nothing, and a component returning null passes
 *      it. The bug is invisible to a no-crash gate by construction.
 *
 * So this asks the two questions smoke cannot: does the agreement PAINT for
 * the man who has not consented, and does tapping "I agree" actually POST.
 *
 * ── WHAT IT ASSERTS ─────────────────────────────────────────────────────────
 *
 *   1. a CP who lands on /consent is STILL on /consent afterwards
 *   2. all four paragraphs of the server's wording are on the page
 *   3. the "I agree" control is present
 *   4. tapping it sends POST /api/esra-consent carrying the current version
 *
 * GET returns the NO-ROW payload — has_consented false, is_current false,
 * current_text present. That is the state every one of the 33 blocked attempts
 * was in, and the state the screen has to handle to be worth having.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist --clear
 *   node scripts/consent-paint.cjs --dist dist
 *
 * Requires playwright-core and a Chromium binary, exactly as smoke-mount does.
 *   PW_CORE   path to playwright-core
 *   CHROME    path to a Chromium executable
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const DIST = path.resolve(arg('dist', 'dist'));
const PORT = Number(arg('port', 5811));

if (!fs.existsSync(path.join(DIST, 'index.html'))) {
  console.error(`x no index.html in ${DIST} - run: npx expo export --platform web --output-dir ${DIST}`);
  process.exit(1);
}

let chromium;
try {
  ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
} catch {
  console.error('x playwright-core not resolvable. Install it, or set PW_CORE=/path/to/playwright-core.');
  process.exit(1);
}

// ── The server's own wording, copied from backend/lib/esra_consent.py ────────
//
// VERBATIM ON PURPOSE. The screen renders only what the GET carried and has no
// fallback text, so a stub that paraphrased would be testing a different page
// than the one the CP reads. Four paragraphs separated by blank lines, which is
// also the split the screen makes.
const CONSENT_VERSION = '2026-08-30.1';
const CONSENT_PARAGRAPHS = [
  'I agree to do business electronically with LeveLog and with the company '
  + 'that gave me this account.',
  'I agree that the signature I draw or apply in this application is my '
  + 'signature, and I intend it to have the same effect as a signature I write '
  + 'by hand on paper.',
  'I understand that the records I sign here are kept as the record of the '
  + 'work they describe, that I cannot edit a record after I have signed it, '
  + 'and that I can be given a copy of anything I have signed.',
  'I can withdraw this agreement at any time by telling my company '
  + 'administrator. If I withdraw it, I will be asked to sign on paper instead.',
];
const CONSENT_TEXT = CONSENT_PARAGRAPHS.join('\n\n');

// NO ROW ON FILE. What GET /api/esra-consent returns for a user with nothing in
// `esra_consents`: has_consented false, verification MISSING, and the current
// wording sent anyway so the client needs no second round trip.
const NO_ROW = {
  current_version: CONSENT_VERSION,
  current_text: CONSENT_TEXT,
  has_consented: false,
  is_current: false,
  agreed_version: null,
  agreed_at: null,
  verification: 'MISSING',
  has_declined: false,
  declined_at: null,
  declined_version: null,
};

const AGREED = {
  ...NO_ROW,
  has_consented: true,
  is_current: true,
  agreed_version: CONSENT_VERSION,
  agreed_at: new Date().toISOString(),
  verification: null,
};

// THE ROLE IS THE WHOLE EXPERIMENT. 'cp' is the arm of RouteGuard that confines
// a signer to /logbooks*; smoke-mount signs in as an owner and never runs it.
const USER = {
  id: 'u1',
  email: 'cp@test.local',
  full_name: 'Test CP',
  name: 'Test CP',
  role: 'cp',
  company_name: 'Acme',
  company_id: 'c1',
  account_status: 'approved',
};

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.ico': 'image/x-icon', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff': 'font/woff', '.woff2': 'font/woff2', '.map': 'application/json' };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  let fp = path.join(DIST, p);
  if (!fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
    const h = path.join(DIST, `${p}.html`);
    fp = fs.existsSync(h) ? h : path.join(DIST, 'index.html');   // SPA fallback
  }
  try {
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(fs.readFileSync(fp));
  } catch { res.writeHead(404); res.end('nf'); }
});

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const JWT = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ exp: 4102444800, sub: 'u1' })}.x`;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) { console.log(`  ok  ${msg}`); } else { failures += 1; console.log(`FAIL  ${msg}`); }
};

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);
  const ctx = await browser.newContext({ viewport: { width: 900, height: 1200 } });
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('blueview_token', t);
    localStorage.setItem('blueview_user', u);
    localStorage.setItem('blueview_theme', 'dark');
  }, [JWT, JSON.stringify(USER)]);

  const page = await ctx.newPage();

  const gets = [];
  const posts = [];
  let agreed = false;

  await page.route('**://api.levelog.com/**', (route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': '*',
      'Access-Control-Allow-Methods': '*',
      'Content-Type': 'application/json',
    };
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });

    if (/\/api\/esra-consent(\?|$)/.test(url)) {
      if (method === 'POST') {
        let body = {};
        try { body = JSON.parse(req.postData() || '{}'); } catch { /* recorded as {} */ }
        posts.push(body);
        agreed = true;
        return route.fulfill({
          status: 200,
          headers: cors,
          body: JSON.stringify({
            recorded: true, already: false,
            consent_version: CONSENT_VERSION,
            agreed_at: new Date().toISOString(),
          }),
        });
      }
      gets.push(url);
      return route.fulfill({
        status: 200, headers: cors,
        body: JSON.stringify(agreed ? AGREED : NO_ROW),
      });
    }

    let body = {};
    if (url.includes('/api/auth/me')) body = USER;
    else if (url.includes('feature-flags')) body = { flags: {} };
    else if (/\/(logbooks|projects|workers|documents|notifications)/.test(url)) body = [];
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(body) });
  });

  await page.goto(`http://localhost:${PORT}/consent`, { waitUntil: 'load' });
  // Long enough for the auth bootstrap, the guard's effect and the screen's own
  // read to have all run. The live symptom was a ~2s spinner then a bounce.
  await page.waitForTimeout(5000);

  console.log('\nCONSENT SCREEN, AS A CP WITH NO CONSENT ON FILE');

  const where = await page.evaluate(() => window.location.pathname);
  ok(where === '/consent',
    `a CP who lands on /consent is still on /consent (was: ${where})`);

  const text = await page.evaluate(() => document.body.innerText || '');
  const norm = (s) => s.replace(/\s+/g, ' ').trim();
  const flat = norm(text);
  CONSENT_PARAGRAPHS.forEach((para, i) => {
    ok(flat.includes(norm(para)),
      `the agreement PAINTS - paragraph ${i + 1} of the server's wording is on the page`);
  });
  ok(flat.includes('Before you sign'),
    'the lede for a man who has not agreed is shown, not the outage lede');

  ok(gets.length > 0, `GET /api/esra-consent was made (${gets.length})`);

  // ── THE ACCEPT PATH ───────────────────────────────────────────────────────
  // Zero POSTs in eight hours of production logs. The button has to exist, and
  // pressing it has to reach the server.
  const buttons = await page.$$('[role="button"]');
  let agreeBtn = null;
  for (const b of buttons) {
    const label = norm(await b.evaluate((el) => el.innerText || ''));
    if (label === 'I agree') { agreeBtn = b; break; }
  }
  ok(!!agreeBtn, 'the "I agree" control is on the page');

  if (agreeBtn) {
    await agreeBtn.click();
    await page.waitForTimeout(3000);
  }

  ok(posts.length === 1,
    `tapping "I agree" sent exactly one POST /api/esra-consent (${posts.length})`);
  ok(posts.length > 0 && posts[0].consent_version === CONSENT_VERSION,
    `the POST carries the server's current version (${posts.length ? JSON.stringify(posts[0]) : 'no POST'})`);

  await browser.close();
  server.close();

  console.log(failures === 0
    ? '\nPASS  the agreement paints and the accept path reaches the server\n'
    : `\n${failures} FAILED\n`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
