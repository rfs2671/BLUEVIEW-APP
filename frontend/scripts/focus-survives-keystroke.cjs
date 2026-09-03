#!/usr/bin/env node
/**
 * FOCUS SURVIVES A KEYSTROKE — the property, not a proxy for it.
 *
 * WHAT THIS IS FOR
 * The site superintendent reported that the keyboard closed after every single
 * character in every field of his BC 3301.13.13 log. Eleven items of statutory
 * prose, one character at a time, filled in the field before he departs.
 *
 * The cause was components declared inside the screen's render body and used
 * as JSX element types: a new function object per render is a new component
 * type to React, so the whole subtree — the `TextInput` and its focus — is
 * unmounted and remounted on every keystroke.
 *
 * THE SOURCE GUARD IS NOT THIS TEST. siteSuperintendentStableFields.test.cjs
 * asserts that no component is declared inside the screen function. That is a
 * statement about the CAUSE. A screen that dropped focus for a different reason
 * — a `key` that changes per render, a remount driven from a parent, a
 * `useEffect` that blurs — would pass it and still be unfillable. So this job
 * drives REAL keystrokes into a REAL input in the REAL production web build and
 * asks the only question that matters to him:
 *
 *   after typing one character, is the SAME DOM node still the focused element,
 *   and do the second and third characters land in it too?
 *
 * HOW THE IDENTITY IS PROVED. The target input is TAGGED with a data attribute
 * before the first keypress. A remount does not move the old node — it destroys
 * it and creates a new one, and the new one carries no tag. So
 * `document.querySelector('[data-focus-probe]')` returning null after a
 * keystroke IS the remount, observed directly rather than inferred.
 *
 * THE CONTROL IS PART OF THE RUN. daily_jobsite declares zero components in its
 * screen body and is the working contrast. It is probed with the identical code
 * on every run: if the superintendent screen passed while the control failed,
 * the harness would be broken, not the screen. A run where the control fails is
 * reported as a HARNESS failure, not a pass.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist
 *   node scripts/focus-survives-keystroke.cjs --dist dist
 *
 * PW_CORE   path to playwright-core (default: resolve 'playwright-core')
 * CHROME    path to a Chromium executable (default: playwright default)
 *
 * Exits 0 when every probe passes, 1 on a real failure, 2 on a harness fault.
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

// ── the same static server and API stub the mount smoke uses ────────────────
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
const USER = { id: 'u1', email: 'smoke@test.local', full_name: 'Smoke', name: 'Smoke', role: 'owner', company_name: 'Acme', company_id: 'c1', account_status: 'approved' };
const PROJECT = { id: 'p1', _id: 'p1', name: 'Smoke Site', address: '1 Test St, Brooklyn', company_id: 'c1', status: 'active', nyc_bin: '2115914' };

function stub(page) {
  return page.route('**://api.levelog.com/**', (route) => {
    const url = route.request().url();
    const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*', 'Content-Type': 'application/json' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });
    let body = {};
    if (url.includes('/api/auth/me')) body = USER;
    else if (url.includes('feature-flags')) body = { flags: {} };
    else if (url.match(/\/api\/projects\/p1(\?|$)/)) body = PROJECT;
    else if (url.match(/\/api\/projects(\?|\/|$)/)) body = [PROJECT];
    else if (/\/(logbooks|checkins|nfc|site-devices|documents|reports|notifications|workers|dob)/.test(url)) body = [];
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(body) });
  });
}

/**
 * Drive three characters into one field and report what actually happened.
 *
 * `nth` selects among the editable text inputs the screen renders at mount, in
 * DOM order. It is named at the call site rather than fixed here so a screen
 * whose first input is a date or a picker can still be probed on a prose field.
 */
async function probe(page, { route, nth, label, advance = 0, clickText = null }) {
  await stub(page);
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));

  await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(2000);

  // SOME STEPPERS OPEN ON A STEP WITH NO PROSE FIELD. The footer's primary
  // action carries aria-label="Next" (accessibilityLabel on the Pressable), so
  // paging is done through the control a CP would actually tap.
  for (let i = 0; i < advance; i += 1) {
    const btn = await page.$('[role="button"][aria-label="Next"]');
    if (!btn) return { label, route, harness: `no "Next" control to reach step ${i + 2}`, errors };
    // eslint-disable-next-line no-await-in-loop
    await btn.click();
    // eslint-disable-next-line no-await-in-loop
    await page.waitForTimeout(1200);
  }

  // A LIST WHOSE ROWS DO NOT EXIST UNTIL SOMETHING IS ADDED. EntryList renders
  // one TextInput per entry and the DOB feed is empty under this stub, so the
  // "add manually" control has to be pressed before there is a field to type
  // into at all.
  if (clickText) {
    const hit = await page.evaluate((needle) => {
      const el = [...document.querySelectorAll('[role="button"], div')]
        .find((n) => (n.innerText || '').trim() === needle);
      if (!el) return false;
      el.click();
      return true;
    }, clickText);
    if (!hit) return { label, route, harness: `no control reading "${clickText}"`, errors };
    await page.waitForTimeout(1200);
  }

  // ── TAG THE TARGET ────────────────────────────────────────────────────────
  // The tag is the identity. A React remount destroys this node and builds a
  // new one; the new one has no tag, so the tag's disappearance IS the remount.
  const setup = await page.evaluate((n) => {
    const all = [...document.querySelectorAll('input, textarea')]
      .filter((el) => !el.disabled && !el.readOnly && el.type !== 'hidden'
        && el.offsetParent !== null);
    if (all.length <= n) return { count: all.length, ok: false };
    const el = all[n];
    el.setAttribute('data-focus-probe', 'target');
    el.focus();
    if (el.setSelectionRange) {
      try { el.setSelectionRange(el.value.length, el.value.length); } catch { /* number/date inputs refuse */ }
    }
    return {
      count: all.length,
      ok: true,
      tag: el.tagName.toLowerCase(),
      before: el.value,
      focusedAtStart: document.activeElement === el,
    };
  }, nth);

  if (!setup.ok) {
    return { label, route, harness: `only ${setup.count} editable inputs on the screen; wanted index ${nth}`, errors };
  }
  if (!setup.focusedAtStart) {
    return { label, route, harness: 'the target input refused focus before any key was pressed', errors };
  }

  const read = () => page.evaluate(() => {
    const el = document.querySelector('[data-focus-probe="target"]');
    return {
      alive: !!el,                                  // the tagged NODE still exists
      focused: !!el && document.activeElement === el,
      value: el ? el.value : null,
      // A fresh node in the same slot is the remount's fingerprint: the input
      // is there, it just is not the one that had focus.
      replaced: !el && document.querySelectorAll('input, textarea').length > 0,
    };
  });

  // ── ONE CHARACTER ────────────────────────────────────────────────────────
  await page.keyboard.press('KeyA');
  await page.waitForTimeout(500);
  const after1 = await read();

  // ── AND THEN TWO MORE, WITHOUT TOUCHING THE FIELD AGAIN ──────────────────
  // This is his actual complaint: he does not get to type a word. Re-clicking
  // between characters would hide exactly the defect being measured, so the
  // probe deliberately never clicks again.
  await page.keyboard.press('KeyB');
  await page.waitForTimeout(300);
  await page.keyboard.press('KeyC');
  await page.waitForTimeout(500);
  const after3 = await read();

  // Unshifted key presses, so the characters that land are lower case.
  const expected = `${setup.before}abc`;
  return {
    label,
    route,
    before: setup.before,
    after1,
    after3,
    expected,
    pass: after1.alive && after1.focused
      && after3.alive && after3.focused && after3.value === expected,
    errors,
  };
}

const TARGETS = [
  {
    label: 'site_superintendent_log — printed name (step 1, first prose field)',
    route: '/logbooks/site_superintendent_log?projectId=p1',
    nth: 0,
    subject: true,
  },
  {
    // THE SECOND HOISTED COMPONENT THAT OWNS A TextInput. `Field` covers 15 of
    // the 18 call sites and is probed above; `EntryList` covers 2 more and had
    // exactly the same defect. (`CorrectionChoice`, the eighteenth, is chips —
    // there is no text field in it to lose focus.) Its rows do not exist until
    // one is added, hence the click.
    label: 'site_superintendent_log — a DOB entry row (step 4, EntryList)',
    route: '/logbooks/site_superintendent_log?projectId=p1',
    advance: 3,
    clickText: 'Add one the system does not have',
    nth: 0,
    subject: true,
  },
  {
    // THE CONTROL. Zero components declared in its screen body; its
    // renderStep1..renderStep5 are render FUNCTIONS that get CALLED, so its
    // inputs keep a stable identity across renders. If this fails, the harness
    // is wrong and nothing it says about the screen above can be believed.
    label: 'daily_jobsite — control, a screen with no inner components',
    route: '/logbooks/daily_jobsite?projectId=p1',
    // Steps 1 and 2 are crew/equipment chips, and with an empty gate roster
    // they render no crew rows and therefore no inputs at all. Step 3 is the
    // first step with a prose field under this stub.
    advance: 2,
    nth: 0,
    subject: false,
  },
];

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('blueview_token', t);
    localStorage.setItem('blueview_user', u);
    localStorage.setItem('blueview_theme', 'light');
  }, [JWT, JSON.stringify(USER)]);

  const results = [];
  for (const target of TARGETS) {
    const page = await ctx.newPage();
    // eslint-disable-next-line no-await-in-loop
    results.push({ ...await probe(page, target), subject: target.subject });
    // eslint-disable-next-line no-await-in-loop
    await page.close();
  }

  await ctx.close();
  await browser.close();
  server.close();

  let harnessFault = false;
  let failed = 0;
  console.log('');
  for (const r of results) {
    console.log(`${r.label}`);
    console.log(`  ${r.route}`);
    if (r.harness) {
      console.log(`  HARNESS FAULT: ${r.harness}`);
      harnessFault = true;
      continue;
    }
    const q = (v) => (v === null ? 'null' : JSON.stringify(v));
    console.log(`  value before typing        ${q(r.before)}`);
    console.log(`  after 1 key   node alive   ${r.after1.alive}   focused ${r.after1.focused}   value ${q(r.after1.value)}`);
    console.log(`  after 3 keys  node alive   ${r.after3.alive}   focused ${r.after3.focused}   value ${q(r.after3.value)}`);
    console.log(`  expected after 3 keys      ${q(r.expected)}`);
    if (!r.after1.alive && r.after1.replaced) {
      console.log('  -> the tagged input was DESTROYED by the first keystroke and a fresh');
      console.log('     one built in its place. That is the remount. The keyboard closes.');
    }
    if (r.errors.length) r.errors.slice(0, 3).forEach((e) => console.log(`  ${e}`));
    console.log(r.pass ? '  PASS' : '  FAIL');
    if (!r.pass) {
      failed += 1;
      if (!r.subject) harnessFault = true;   // the control must always pass
    }
    console.log('');
  }

  if (harnessFault) {
    console.log('HARNESS FAULT — the control did not behave, so this run proves nothing.');
    process.exit(2);
  }
  console.log(failed === 0
    ? 'PASS — focus survives a keystroke, and three characters land in one field.'
    : `${failed} FAILED — a character typed into this screen destroys the field it was typed into.`);
  process.exit(failed === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
