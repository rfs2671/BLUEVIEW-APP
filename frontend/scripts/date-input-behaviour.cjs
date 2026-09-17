#!/usr/bin/env node
/**
 * THE SHARED DATE FIELD, DRIVEN IN A BROWSER, ON THE RECORD THAT STARTED IT.
 *
 * Michael's `dob_registration_expiry` is literally '07/212029' in production.
 * The ruling: typed on a number pad as MM/DD/YYYY, stored ISO, impossible
 * dates refused inline before Save, and a stored legacy value PARSED and SHOWN
 * FOR CONFIRMATION with NO SILENT WRITE. This drives /admin/users as a company
 * admin at the operator's 443px, in both themes, and asserts each of those as
 * behaviour — requests counted, not source read.
 *
 * ── WHY A BROWSER AND NOT THE NODE SUITE ────────────────────────────────────
 *
 * "Opening the form writes nothing" is a property of effects, focus handlers
 * and a form's dirty tracking together. The node suite executes the rules
 * (dateEntry.test.cjs) and asserts the call sites (dateInputCensus.test.cjs);
 * neither mounts the sheet. The mount smoke mounts /admin/users as an OWNER and
 * sees the access-denied panel (see admin-users-sheets.cjs). So this is the
 * only thing that opens Michael's Edit sheet and watches the network.
 *
 * ── WHAT IT ASSERTS, IN ORDER ───────────────────────────────────────────────
 *
 *   BADGE     the row no longer says "re-enter it as YYYY-MM-DD", and says
 *             what Edit will read the stored value as
 *   READ      Edit opens with the field showing 07/21/2029, inputmode numeric,
 *             and a note quoting the stored "07/212029" in legible ink
 *   NO WRITE  opening, then closing, sends ZERO non-GET requests
 *   REFUSED   02292027 types as 02/29/2027, is named ("not a leap year")
 *             under the field, and Save sends nothing
 *   PASTE     a pasted 2029-07-21 lands as 07/21/2029
 *   BACKSPACE three backspaces leave 07/21/2, and 029 restores it
 *   SAVED     Save sends exactly one write, carrying 2029-07-21
 *   PINNED    on the scaffold stepper — a LIGHT card pinned whatever the
 *             phone's theme — a stored '07/212029' reads as 07/21/2029, and
 *             "month 13" is named in ink legible on that card in BOTH themes.
 *             This is the white-on-white failure the mount smoke cannot see.
 *
 * THE INSTRUMENT IS CHECKED BEFORE IT REPORTS: the harness demands the roster
 * rendered and the date field was found, and exits 2 rather than passing on a
 * page it never saw. And the write counter is proven live — the final Save
 * MUST be seen, so a counter that never counts cannot turn "no write" green.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist
 *   node scripts/date-input-behaviour.cjs --dist dist [--width 443]
 *
 * Exit 0 clean, 1 on a failure, 2 on a harness fault.
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
const WIDTH = Number(arg('width', 443));
const HEIGHT = Number(arg('height', 830));

// Same refusal as the mount smoke: an export from under a dot-directory is
// routeless, and every probe would fail for a reason unrelated to the field.
function dotDirAncestor(p) {
  const parts = path.resolve(p).split(/[\\/]+/);
  return parts.slice(1).find((seg) => seg.startsWith('.') && seg !== '.' && seg !== '..') || null;
}
for (const [label, target] of [['the working directory', process.cwd()], ['--dist', DIST]]) {
  const bad = dotDirAncestor(target);
  if (bad) {
    console.error(`x REFUSING TO RUN: ${label} sits under a dot-directory ("${bad}"). Copy the tree elsewhere.`);
    process.exit(2);
  }
}
if (!fs.existsSync(path.join(DIST, 'index.html'))) {
  console.error(`x no index.html in ${DIST} — run: npx expo export --platform web --output-dir ${DIST}`);
  process.exit(2);
}

let chromium;
try {
  ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
} catch {
  console.error('x playwright-core not resolvable. Install it, or set PW_CORE=/path/to/playwright-core.');
  process.exit(2);
}

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.ico': 'image/x-icon', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff': 'font/woff', '.woff2': 'font/woff2', '.map': 'application/json' };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  let fp = path.join(DIST, p);
  if (!fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
    const h = path.join(DIST, `${p}.html`);
    fp = fs.existsSync(h) ? h : path.join(DIST, 'index.html');
  }
  try {
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(fs.readFileSync(fp));
  } catch { res.writeHead(404); res.end('nf'); }
});

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const JWT = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ exp: 4102444800, sub: 'u1' })}.x`;
const ME = { id: 'u1', email: 'admin@test.local', full_name: 'Admin', name: 'Admin', role: 'admin', company_name: 'Acme', company_id: 'c1', account_status: 'approved' };

// THE PRODUCTION ROW, as the list endpoint returns it: the stored string, and
// the server's `unreadable` verdict carrying it back verbatim.
const MICHAEL = {
  id: 'su1', name: 'Michael Cespedes', email: 'michael@acme.test',
  role: 'superintendent', company_id: 'c1', assigned_projects: ['p1'],
  dob_superintendent_number: '32299',
  dob_registration_expiry: '07/212029',
  licence: {
    state: 'unreadable', expires_on: '07/212029', days_remaining: null,
    number: '32299', registered: true,
  },
};
const ROSTER = [
  MICHAEL,
  { id: 'cp1', name: 'Ana Ortiz', email: 'a.ortiz@acme.test', role: 'cp', assigned_projects: ['p1'] },
];
const PROJECTS = [{ id: 'p1', _id: 'p1', name: '588 Boyland Street', company_id: 'c1', status: 'active' }];

// --placeholder exists for the CONTROL RUN only: the pre-change field was
// 'Registration expiry (YYYY-MM-DD)', and a gate that cannot find the old field
// reports a harness fault instead of showing what the old field does wrong.
const PLACEHOLDER = arg('placeholder', 'Registration expiry (MM/DD/YYYY)');

function stub(page, writes) {
  return page.route('**://api.levelog.com/**', (route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*', 'Content-Type': 'application/json' };
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });
    if (method !== 'GET') {
      let body = null;
      try { body = JSON.parse(req.postData() || 'null'); } catch { body = req.postData(); }
      writes.push({ method, url, body });
      return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ ...MICHAEL, ...(body || {}) }) });
    }
    let body = {};
    if (url.includes('/api/auth/me')) body = ME;
    else if (url.includes('feature-flags')) body = { flags: {} };
    else if (url.includes('/api/version')) body = { client_minimum_supported: null };
    else if (/\/api\/admin\/users(\?|$)/.test(url)) body = ROSTER;
    else if (/\/api\/projects(\?|\/|$)/.test(url)) body = PROJECTS;
    else if (url.includes('/scaffold-info')) body = { installation_date: '07/212029' };
    else body = [];
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(body) });
  });
}

// Michael's Edit, not the first Edit on the page: walk up from each Edit to
// the smallest ancestor that names a person, and pick his.
const clickMichaelsEdit = (page) => page.evaluate(() => {
  const edits = [...document.querySelectorAll('[role="button"], button, [tabindex="0"]')]
    .filter((n) => (n.getAttribute('aria-label') || n.innerText || '').trim() === 'Edit');
  for (const e of edits) {
    let p = e.parentElement;
    while (p && !/@acme\.test/.test(p.innerText || '')) p = p.parentElement;
    if (p && (p.innerText || '').includes('michael@acme.test')
      && !(p.innerText || '').includes('a.ortiz@acme.test')) {
      e.click();
      return true;
    }
  }
  return false;
});

const clickInDialog = (page, name) => page.evaluate((needle) => {
  const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
  if (!dialog) return false;
  const hit = [...dialog.querySelectorAll('[role="button"], button, [tabindex]')]
    .find((n) => (n.getAttribute('aria-label') || n.innerText || '').trim() === needle);
  if (!hit) return false;
  hit.click();
  return true;
}, name);

/** The date field, its message, and whether the message can be read. */
const readField = (page, placeholder, scope = '[role="dialog"] ') => page.evaluate(([ph, sc]) => {
  const input = document.querySelector(`${sc}input[placeholder="${ph}"]`);
  if (!input) return { found: false };
  // The message is the Text rendered right after the input's own wrapper.
  let wrap = input;
  while (wrap.parentElement && wrap.parentElement.children.length === 1) wrap = wrap.parentElement;
  const holder = wrap.parentElement;
  const msgEl = holder ? [...holder.children].find((c) => c !== wrap && (c.innerText || '').trim()) : null;
  const rgb = (s) => (s.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // The first opaque background at or above the message: what it is read on.
  let bg = null;
  for (let n = msgEl; n; n = n.parentElement) {
    const c = rgb(getComputedStyle(n).backgroundColor);
    if (c.length >= 3 && (c.length < 4 || c[3] > 0.9)) { bg = c; break; }
  }
  let contrast = null;
  if (msgEl && bg) {
    const fg = rgb(getComputedStyle(msgEl).color);
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    contrast = Math.round(((a + 0.05) / (b + 0.05)) * 100) / 100;
  }
  return {
    found: true,
    value: input.value,
    inputMode: input.getAttribute('inputmode'),
    message: msgEl ? msgEl.innerText.trim() : '',
    contrast,
  };
}, [placeholder, scope]);

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);

  let failures = 0;
  let harness = 0;
  const check = (name, cond, detail) => {
    if (cond) console.log(`  ok    ${name}`);
    else { failures += 1; console.log(`  FAIL  ${name}\n        ${detail}`); }
  };

  for (const theme of ['light', 'dark']) {
    console.log(`\n=== ${theme} · ${WIDTH}x${HEIGHT} ===`);
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
    await ctx.addInitScript(([t, u, th]) => {
      localStorage.setItem('blueview_token', t);
      localStorage.setItem('blueview_user', u);
      localStorage.setItem('blueview_theme', th);
    }, [JWT, JSON.stringify(ME), theme]);
    const page = await ctx.newPage();
    const writes = [];
    await stub(page, writes);
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`http://localhost:${PORT}/admin/users`, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(2200);

    const body = await page.evaluate(() => document.body.innerText || '');
    if (!body.includes('Michael Cespedes')) {
      console.error(`x HARNESS [${theme}]: the roster never rendered. Nothing was measured.`);
      harness += 1;
      await ctx.close();
      continue; // eslint-disable-line no-continue
    }

    // BADGE
    check('BADGE     the row no longer tells anyone to type YYYY-MM-DD',
      !body.includes('YYYY-MM-DD'), 'the page still says YYYY-MM-DD');
    check('BADGE     it says what Edit will read the stored value as',
      body.includes('open Edit to confirm it as 07/21/2029'),
      `no such sentence; badge area reads: ${(body.match(/DOB registration[^\n]*/) || [''])[0]}`);

    // READ
    if (!(await clickMichaelsEdit(page))) {
      console.error(`x HARNESS [${theme}]: no Edit control on Michael's card.`);
      harness += 1;
      await ctx.close();
      continue; // eslint-disable-line no-continue
    }
    await page.waitForTimeout(900);
    let f = await readField(page, PLACEHOLDER);
    if (!f.found) {
      console.error(`x HARNESS [${theme}]: the Edit sheet has no "${PLACEHOLDER}" field.`);
      harness += 1;
      await ctx.close();
      continue; // eslint-disable-line no-continue
    }
    check('READ      the stored 07/212029 opens as 07/21/2029', f.value === '07/21/2029', `value is "${f.value}"`);
    check('READ      the field asks for the numeric keypad', f.inputMode === 'numeric', `inputmode is ${f.inputMode}`);
    check('READ      a note quotes what is stored', f.message.includes('"07/212029"') && f.message.includes('07/21/2029'),
      `message is "${f.message}"`);
    check('READ      and the note is legible on this theme (>= 4.5:1)', f.contrast !== null && f.contrast >= 4.5,
      `contrast ${f.contrast}`);

    // NO WRITE
    check('NO WRITE  opening the sheet sent nothing', writes.length === 0, JSON.stringify(writes));
    const closed = await clickInDialog(page, 'Close') || await clickInDialog(page, 'Cancel');
    await page.waitForTimeout(700);
    const stillOpen = await page.evaluate(() => !!document.querySelector('[role="dialog"][aria-modal="true"]'));
    check('NO WRITE  the sheet closed', closed && !stillOpen, `closed=${closed} stillOpen=${stillOpen}`);
    check('NO WRITE  closing it sent nothing', writes.length === 0, JSON.stringify(writes));

    // REFUSED
    await clickMichaelsEdit(page);
    await page.waitForTimeout(900);
    const input = page.locator(`[role="dialog"] input[placeholder="${PLACEHOLDER}"]`);
    await input.click();
    await input.press('Control+A');
    await input.press('Backspace');
    await input.pressSequentially('02292027', { delay: 25 });
    f = await readField(page, PLACEHOLDER);
    check('REFUSED   02292027 shows as 02/29/2027', f.value === '02/29/2027', `value is "${f.value}"`);
    check('REFUSED   and is named under the field', /leap year/.test(f.message), `message is "${f.message}"`);
    check('REFUSED   in legible ink (>= 4.5:1)', f.contrast !== null && f.contrast >= 4.5, `contrast ${f.contrast}`);
    await clickInDialog(page, 'Save');
    await page.waitForTimeout(700);
    check('REFUSED   Save sent nothing', writes.length === 0, JSON.stringify(writes));

    // PASTE
    await input.fill('2029-07-21');
    f = await readField(page, PLACEHOLDER);
    check('PASTE     2029-07-21 lands as 07/21/2029', f.value === '07/21/2029', `value is "${f.value}"`);

    // BACKSPACE
    await input.press('End');
    await input.press('Backspace');
    await input.press('Backspace');
    await input.press('Backspace');
    f = await readField(page, PLACEHOLDER);
    check('BACKSPACE three from the end leave 07/21/2', f.value === '07/21/2', `value is "${f.value}"`);
    await input.pressSequentially('029', { delay: 25 });
    f = await readField(page, PLACEHOLDER);
    check('BACKSPACE and 029 restores 07/21/2029', f.value === '07/21/2029', `value is "${f.value}"`);

    // SAVED
    await clickInDialog(page, 'Save');
    await page.waitForTimeout(1200);
    const saves = writes.filter((w) => /\/api\/admin\/users\/su1/.test(w.url));
    check('SAVED     Save sent exactly one write for Michael', saves.length === 1 && writes.length === 1,
      JSON.stringify(writes));
    const sent = saves[0] && saves[0].body && saves[0].body.dob_registration_expiry;
    check('SAVED     carrying the ISO date, not the typed text', sent === '2029-07-21', `sent ${JSON.stringify(sent)}`);

    // PINNED
    await page.goto(`http://localhost:${PORT}/logbooks/scaffold_maintenance?projectId=p1`,
      { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(2200);
    const STEP = 'MM/DD/YYYY';
    f = await readField(page, STEP, '');
    if (!f.found) {
      console.error(`x HARNESS [${theme}]: the scaffold stepper shows no ${STEP} field.`);
      harness += 1;
    } else {
      const before = writes.length;
      check('PINNED    the stored installation date reads as 07/21/2029', f.value === '07/21/2029',
        `value is "${f.value}"`);
      check('PINNED    with its note legible on the pinned card (>= 4.5:1)',
        f.message.includes('"07/212029"') && f.contrast !== null && f.contrast >= 4.5,
        `message "${f.message}", contrast ${f.contrast}`);
      // A stepper files an untouched value as written; the note must not say
      // that saving fixes it.
      check('PINNED    and it does not promise that saving converts it',
        !/until you save/i.test(f.message), `message "${f.message}"`);
      const step = page.locator(`input[placeholder="${STEP}"]`).first();
      await step.click();
      await step.press('Control+A');
      await step.press('Backspace');
      await step.pressSequentially('13', { delay: 25 });
      f = await readField(page, STEP, '');
      check('PINNED    month 13 is named at the second digit', /month 13/.test(f.message),
        `message is "${f.message}"`);
      check('PINNED    in ink legible on the pinned card (>= 4.5:1)', f.contrast !== null && f.contrast >= 4.5,
        `contrast ${f.contrast}`);
      check('PINNED    typing into a stepper sent nothing to the server',
        writes.length === before, JSON.stringify(writes.slice(before)));
    }

    check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
    await ctx.close();
  }

  await browser.close();
  server.close();
  if (harness) {
    console.error(`\n${harness} harness fault(s) — this run is not a result.`);
    process.exit(2);
  }
  console.log(`\n${failures === 0 ? 'all clean' : `${failures} failure(s)`} at ${WIDTH}px`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error('FAILED:', e); process.exit(2); });
