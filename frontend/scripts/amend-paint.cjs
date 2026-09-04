#!/usr/bin/env node
/**
 * THE CORRECTION SHEET, DRIVEN AS THE MAN WHO OPENS IT — and made to answer.
 *
 * ── WHAT THIS ANSWERS ───────────────────────────────────────────────────────
 *
 * A CP taps Amend on a filed log, types a reason, taps Create Amendment, and
 * reports that "nothing happens". Two explanations were on the table and they
 * predict DIFFERENT screens:
 *
 *   (A) the server refused the reason and the refusal is painted INSIDE the
 *       app's tree while a native Modal is open, so he never sees it. The sheet
 *       STAYS OPEN.
 *   (B) something on the path navigates to a route RouteGuard does not allow a
 *       CP to occupy, and he is replaced onto /logbooks — his Dashboard. The
 *       sheet is GONE and so is the screen.
 *
 * A unit test on doAmend cannot tell those apart: it has no router and no
 * Modal. This drives the real bundle, under the real guard, signed in as a CP,
 * and reports WHERE THE APP ENDED UP and WHAT IS ON THE PAGE — which is the one
 * observation that separates them.
 *
 * ── AND IT ASSERTS THE FIX ──────────────────────────────────────────────────
 *
 * The refusal must be READABLE while the sheet is open. `<ToastHost />` mounted
 * inside the Modal's own tree is the sanctioned mechanism (app/settings.jsx,
 * app/project/[id].jsx); this asserts the SENTENCE is on the page, which is the
 * property the CP actually needs and the only one a later refactor cannot
 * satisfy by accident.
 *
 * NOTE ON WHAT WEB CAN AND CANNOT PROVE. react-native-web renders Modal into
 * the same document, so this harness cannot reproduce the native OS-window
 * layering that hides the toast on a phone. It proves the two things that ARE
 * platform-independent: the navigation (or absence of it), and whether the
 * refusal text is rendered inside the sheet's own subtree. toastInsideModals
 * .test.cjs carries the layering argument.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist --clear
 *   node scripts/amend-paint.cjs --dist dist
 *
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
const PORT = Number(arg('port', 5813));

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

// THE ROLE IS THE EXPERIMENT. smoke-mount signs in as an owner, so RouteGuard's
// CP arm — the one that produced the consent outage — never runs there.
const USER = {
  id: 'u1',
  email: 'cp@test.local',
  full_name: 'Test CP',
  name: 'Test CP',
  role: 'cp',
  company_name: 'Acme',
  company_id: 'c1',
  account_status: 'approved',
  assigned_projects: ['p1'],
};

const PROJECT_ID = 'p1';
const LOG_TYPE = 'concrete_operations';
const DATE = '2026-09-02';
const LOG_ID = 'L1';
const EDITOR_PATH = `/logbooks/${LOG_TYPE}`;

// A FILED, LOCKED LOG — the only state that renders the Amend control.
const FILED_LOG = {
  id: LOG_ID,
  _id: LOG_ID,
  project_id: PROJECT_ID,
  project_name: 'Acme Tower',
  company_id: 'c1',
  log_type: LOG_TYPE,
  date: DATE,
  status: 'submitted',
  is_locked: true,
  is_amendment: false,
  cp_name: 'Test CP',
  cp_signature: { data: 'data:image/png;base64,iVBORw0KGgo=', signed_at: '2026-09-02T12:00:00Z' },
  created_by_name: 'Test CP',
  created_at: '2026-09-02T12:00:00Z',
  data: {
    pour_location: 'Level 3 slab',
    concrete_supplier: 'Acme Ready Mix',
    slump_tests: [],
    formwork_checklist: {},
  },
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

const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();

/**
 * One run of the correction path.
 *
 * `amendResponse` is what POST /api/logbooks/{id}/amend answers with, so the
 * same driver exercises the refusal and the success without two copies of the
 * clicking.
 */
async function run(browser, label, amendResponse, reasonText) {
  const ctx = await browser.newContext({ viewport: { width: 900, height: 1200 } });
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('blueview_token', t);
    localStorage.setItem('blueview_user', u);
    localStorage.setItem('blueview_theme', 'dark');
  }, [JWT, JSON.stringify(USER)]);

  const amendPosts = [];
  const page = await ctx.newPage();

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

    if (/\/amend(\?|$)/.test(url) && method === 'POST') {
      let body = {};
      try { body = JSON.parse(req.postData() || '{}'); } catch { /* recorded as {} */ }
      amendPosts.push(body);
      return route.fulfill({
        status: amendResponse.status, headers: cors,
        body: JSON.stringify(amendResponse.body),
      });
    }

    // CONSENT ON FILE. This harness is about the correction sheet; a consent
    // gate firing here would be a different experiment.
    if (/\/api\/esra-consent(\?|$)/.test(url)) {
      return route.fulfill({
        status: 200, headers: cors,
        body: JSON.stringify({
          current_version: '2026-08-30.1', current_text: 'x', has_consented: true,
          is_current: true, agreed_version: '2026-08-30.1',
          agreed_at: '2026-09-01T00:00:00Z', verification: null,
          has_declined: false, declined_at: null, declined_version: null,
        }),
      });
    }

    let body = {};
    let status = 200;
    if (url.includes('/api/auth/me')) body = USER;
    else if (url.includes('feature-flags')) body = { flags: {} };
    else if (/\/api\/logbooks\/project\//.test(url)) body = [FILED_LOG];
    else if (new RegExp(`/api/logbooks/${LOG_ID}(\\?|$)`).test(url)) body = FILED_LOG;
    else if (/\/api\/projects(\?|$)/.test(url)) body = [{ id: PROJECT_ID, _id: PROJECT_ID, name: 'Acme Tower' }];
    else if (/\/(logbooks|projects|workers|documents|notifications|checkins)/.test(url)) body = [];
    return route.fulfill({ status, headers: cors, body: JSON.stringify(body) });
  });

  await page.goto(
    `http://localhost:${PORT}${EDITOR_PATH}?projectId=${PROJECT_ID}&date=${DATE}`,
    { waitUntil: 'load' },
  );
  await page.waitForTimeout(5000);

  console.log(`\n${label}`);

  const landed = await page.evaluate(() => window.location.pathname);
  ok(landed === EDITOR_PATH,
    `PRECONDITION: a CP opening the filed log is ON the editor (was: ${landed})`);

  const bodyText = () => page.evaluate(() => document.body.innerText || '');
  ok(norm(await bodyText()).includes('FINALIZED'),
    'PRECONDITION: the log renders as filed, so Amend is the only way to change it');

  // ── OPEN THE SHEET ────────────────────────────────────────────────────────
  // `div[tabindex="0"]` IS THE PRESSABLE. react-native-web renders a bare
  // Pressable as a focusable div and sets role="button" only when the element
  // declares accessibilityRole — the lock bar's controls do not, so a
  // role-only selector finds nothing and every assertion after it fails for
  // the wrong reason.
  const findButton = async (label_) => {
    const buttons = await page.$$('div[tabindex="0"], [role="button"], button');
    for (const b of buttons) {
      const txt = norm(await b.evaluate((el) => el.innerText || ''));
      if (txt === label_) return b;
    }
    return null;
  };

  const amendBtn = await findButton('Amend');
  ok(!!amendBtn, 'PRECONDITION: the Amend control is on the filed log');
  if (!amendBtn) { await ctx.close(); return { amendPosts, landedAfter: landed, text: '' }; }
  await amendBtn.click();
  await page.waitForTimeout(1200);

  ok(norm(await bodyText()).includes('Reason for Amendment'),
    'PRECONDITION: the correction sheet opens');

  // ── TYPE THE REASON AND SUBMIT ────────────────────────────────────────────
  const input = await page.$('textarea, input[type="text"]');
  ok(!!input, 'PRECONDITION: the reason field is in the sheet');
  if (input) { await input.click(); await page.keyboard.type(reasonText); }
  await page.waitForTimeout(400);

  const createBtn = await findButton('Create Amendment');
  ok(!!createBtn, 'PRECONDITION: Create Amendment is live once a reason is typed');
  if (createBtn) await createBtn.click();
  // Long enough for the POST, the catch, the toast and any navigation.
  await page.waitForTimeout(4000);

  const landedAfter = await page.evaluate(() => window.location.pathname);
  const text = norm(await bodyText());
  const sheetOpen = text.includes('Reason for Amendment');

  // ── IS THE REFUSAL ACTUALLY IN FRONT OF HIM ───────────────────────────────
  //
  // "The text is somewhere in the document" is the assertion that would have
  // passed while the CP saw nothing, so it is not the one asked. Two questions
  // are, and both are answered from the live page:
  //
  //   inSheetTree  is the toast inside the SHEET's own subtree? react-native-web
  //                renders a Modal into its own container appended to
  //                document.body, so a toast painted from the provider shares
  //                only <body> with the sheet. That separation is the web
  //                counterpart of the native OS window Toast.js describes, and
  //                it is what <ToastHost /> inside the Modal closes.
  //
  //   onTop        what does the browser hit-test at the toast's own centre? A
  //               toast underneath the sheet's overlay answers with the
  //               overlay. This is the property the CP has: not "is it in the
  //               DOM" but "is it the thing he is looking at".
  const paint = await page.evaluate((title) => {
    const t = (el) => (el.innerText || '').replace(/\s+/g, ' ').trim();
    const sheetRoot = Array.from(document.body.children)
      .find((c) => t(c).includes('Reason for Amendment')) || null;
    const cands = Array.from(document.querySelectorAll('*')).filter((el) => t(el) === title);
    if (cands.length === 0) return { present: false, inSheetTree: false, onTop: false };
    const inSheetTree = !!sheetRoot && cands.some((el) => sheetRoot.contains(el));
    const onTop = cands.some((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!hit && (el.contains(hit) || hit.contains(el));
    });
    return { present: true, inSheetTree, onTop, sheetRootFound: !!sheetRoot };
  }, 'Say what you are correcting');

  console.log(`     -> pathname after the tap : ${landedAfter}`);
  console.log(`     -> the sheet is           : ${sheetOpen ? 'STILL OPEN' : 'CLOSED'}`);
  console.log(`     -> POSTs to /amend        : ${amendPosts.length} ${JSON.stringify(amendPosts)}`);
  console.log(`     -> the refusal            : ${JSON.stringify(paint)}`);

  await ctx.close();
  return { amendPosts, landedAfter, text, sheetOpen, paint };
}

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);

  // ── 1. THE REFUSAL ────────────────────────────────────────────────────────
  // "photo" is six characters with no three-letter run of the shape the server
  // wants — it is the reason a CP actually types. amend_logbook answers 400
  // AMENDMENT_REASON_NOT_A_SENTENCE.
  const refused = await run(
    browser,
    'A REASON THE SERVER REFUSES (400 AMENDMENT_REASON_NOT_A_SENTENCE)',
    { status: 400, body: { detail: { code: 'AMENDMENT_REASON_NOT_A_SENTENCE', min_chars: 6 } } },
    'photo',
  );

  console.log('\n  WHICH HYPOTHESIS THE SCREEN SUPPORTS');
  ok(refused.landedAfter === EDITOR_PATH,
    `he is NOT bounced to the Dashboard — a route-guard bounce would leave him `
    + `on /logbooks (was: ${refused.landedAfter})`);
  ok(refused.sheetOpen === true,
    'the sheet STAYS OPEN over his text, which is what the refusal branch does '
    + 'on purpose — so "nothing happened" is a message he cannot read, not a '
    + 'screen he was moved off');

  // ── THE FIX ───────────────────────────────────────────────────────────────
  //
  // The refusal has to be READABLE while that sheet is up. The first assertion
  // below PASSED WITH THE BUG PRESENT and is kept as the anchor it is: the
  // toast was always raised and always in the document. Being in the document
  // is not being in front of him, and the two after it are the ones that
  // separate those.
  ok(refused.text.includes('Say what you are correcting'),
    'ANCHOR (passed before the fix too): the teaching title is raised at all');
  ok(/few words about what changed/.test(refused.text),
    'ANCHOR (passed before the fix too): and the sentence that says what a '
    + 'reason IS, with an example — a refusal that does not teach is what '
    + 'produced "1","1","1","1","0"');
  ok(refused.paint.inSheetTree === true,
    'THE REFUSAL IS IN THE SHEET\'S OWN TREE — a toast painted from the '
    + 'provider shares only <body> with the sheet, which is the web counterpart '
    + 'of the separate OS window a native Modal is');
  ok(refused.paint.onTop === true,
    'AND IT IS THE THING HE IS LOOKING AT — the browser hit-tests the toast at '
    + 'its own centre, not the sheet overlay covering it');

  // ── 2. THE ACCEPTED CORRECTION ────────────────────────────────────────────
  const accepted = await run(
    browser,
    'A REASON THE SERVER ACCEPTS (201, an editable child is returned)',
    {
      status: 200,
      body: {
        ...FILED_LOG,
        id: 'L2',
        _id: 'L2',
        is_locked: false,
        status: 'draft',
        is_amendment: true,
        parent_logbook_id: LOG_ID,
        amendment_reason: 'corrected worker count to 4',
        cp_signature: null,
        cp_name: null,
      },
    },
    'corrected worker count to 4',
  );

  ok(accepted.amendPosts.length === 1,
    `the accepted reason reached the server exactly once (${accepted.amendPosts.length})`);
  ok(accepted.landedAfter === EDITOR_PATH,
    `and a SUCCESSFUL correction does not move him either (was: ${accepted.landedAfter})`);
  ok(accepted.sheetOpen === false,
    'the sheet closes on success — the one outcome that should close it');

  await browser.close();
  server.close();

  console.log(failures === 0
    ? '\nPASS  the correction sheet keeps him in place and says why it refused\n'
    : `\n${failures} FAILED\n`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
