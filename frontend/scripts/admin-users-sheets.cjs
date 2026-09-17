#!/usr/bin/env node
/**
 * THE FOUR FORMS ON /admin/users OPEN OVER THE VIEWPORT — measured, at 443px.
 *
 * ── WHAT WAS REPORTED ──────────────────────────────────────────────────────
 *
 * "Edit, Registration and Assign all work but render at the bottom of the
 * page, invisible on mobile." From the operator, on a phone.
 *
 * The screen had four states called `showAddModal`, `showEditModal`,
 * `showAssignModal` and `showCsModal` and opened no React Native Modal at all.
 * Each was a plain block appended to the TAIL of the page's ScrollView, below
 * the user list. The forms worked. They opened a screen-height below the fold.
 *
 * ── WHY THIS JOB EXISTS AND THE MOUNT SMOKE DOES NOT COVER IT ──────────────
 *
 * scripts/smoke-mount.cjs lists '/admin/users' and reports it green, and that
 * green is worth nothing here: it signs in as an OWNER (`role: 'owner'`) and
 * this screen gates on `user?.role === 'admin'`, so what mounts is the
 * "Admin Access Required" panel. The user list, the four openers and all four
 * forms are unexecuted by it. Nothing else in CI renders this screen at all.
 *
 * So this job signs in as an ADMIN, and the first thing it asserts is that it
 * really got the list — a run that silently landed on the access-denied panel
 * would find no openers, take every "not visible" branch, and could be read as
 * a subtle failure instead of what it is: a harness that never saw its
 * subject. That distinction is reported as a HARNESS fault, not a failure.
 *
 * ── 443 IS THE OPERATOR'S NUMBER ───────────────────────────────────────────
 *
 * It is the CSS width of the phone he filed the report from. The question is
 * not "does a dialog exist in the DOM" — it existed before, several thousand
 * pixels down — but whether the thing that opened is INSIDE the rectangle he
 * is looking at. So the assertion is geometric: the sheet's bounding box must
 * lie within the viewport, and the header's Close and the footer's primary
 * action must each be inside it too, because a form whose Save is below the
 * fold of its own sheet is the same bug one level down.
 *
 * FIVE PROPERTIES PER FORM, each of which fails differently:
 *
 *   PRESENTED   the sheet's rect is inside the 443x-viewport
 *   FOCUSED     document.activeElement is inside the sheet, not on the page
 *               behind it
 *   LOCKED      a wheel over the backdrop does not move the list underneath,
 *               and the page is put back exactly as it was on close
 *   ESCAPABLE   a Close control is present AND inside the viewport, the
 *               primary action is too, and Escape dismisses
 *   TYPEABLE    three characters land in the SAME DOM node (de2b330), on the
 *               two sheets that open on a text field
 *
 * ── WHAT IT SAID BEFORE THE FIX ────────────────────────────────────────────
 *
 * Run against a build of the four inline blocks, at the same 443x830, on the
 * same roster, scrolled to the same place:
 *
 *   8/8 FAIL "no dialog opened at all"   (4 forms x 2 themes), exit 1
 *
 * and after:
 *
 *   76/76 checks clean                                          exit 0
 *
 * The control matters more than usual here because every property below is
 * about POSITION. A gate for "is it on screen" that has never been shown a
 * build where it is not on screen has not been calibrated.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist
 *   node scripts/admin-users-sheets.cjs --dist dist
 *
 * PW_CORE   path to playwright-core (default: resolve 'playwright-core')
 * CHROME    path to a Chromium executable (default: playwright default)
 *
 * Exits 0 when every form passes in both themes, 1 on a real failure, 2 on a
 * harness fault.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const DIST = path.resolve(arg('dist', 'dist'));
const PORT = Number(arg('port', 5812));
const WIDTH = Number(arg('width', 443));
const HEIGHT = Number(arg('height', 830));

// The same refusal scripts/smoke-mount.cjs makes, for the same reason: an
// `npx expo export` run from a path with a dot-directory ancestor emits a
// ROUTELESS bundle, and every probe below would then fail for a reason that
// has nothing to do with the screen.
function dotDirAncestor(p) {
  const parts = path.resolve(p).split(/[\\/]+/);
  return parts.slice(1).find((seg) => seg.startsWith('.') && seg !== '.' && seg !== '..') || null;
}
for (const [label, target] of [['the working directory', process.cwd()], ['--dist', DIST]]) {
  const bad = dotDirAncestor(target);
  if (!bad) continue;
  console.error(`\nx REFUSING TO RUN: ${label} sits under a dot-directory ("${bad}").`
    + `\n    ${path.resolve(target)}\n\n`
    + '  expo export emits a ROUTELESS bundle from such a path. Copy the tree\n'
    + '  to a path with no dot-directory ancestor and run it there.\n');
  process.exit(2);
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

// ── the same static server the mount smoke uses ─────────────────────────────
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

// AN ADMIN, which is the whole difference from the mount smoke.
const ME = { id: 'u1', email: 'admin@test.local', full_name: 'Admin', name: 'Admin', role: 'admin', company_name: 'Acme', company_id: 'c1', account_status: 'approved' };

// ENOUGH ROWS TO PUSH THE OLD LAYOUT BELOW THE FOLD, which is the condition
// the bug needed: with two users the inline block landed near the bottom of a
// laptop window and read as working. At 443x830 these cards alone are several
// viewports tall.
const ROSTER = [
  { id: 'u2', name: 'Michael Reyes', email: 'm.reyes@acme.test', role: 'cp', assigned_projects: ['p1'] },
  { id: 'u3', name: 'Dana Whitfield', email: 'd.whitfield@acme.test', role: 'pm', assigned_projects: [] },
  // THE ROLE THAT HOLDS A REGISTRATION. Without one on the roster the
  // "Registration" opener is not rendered at all and that probe would be
  // vacuous — which is why the harness check below counts the openers.
  {
    id: 'u4', name: 'Sal Ferraro', email: 's.ferraro@acme.test', role: 'superintendent',
    assigned_projects: ['p1', 'p2'],
    dob_superintendent_number: 'SI-004821',
    dob_registration_expiry: '2027-04-01',
  },
  { id: 'u5', name: 'Ana Ortiz', email: 'a.ortiz@acme.test', role: 'cp', assigned_projects: ['p2'] },
  { id: 'u6', name: 'Tom Brennan', email: 't.brennan@acme.test', role: 'cp', assigned_projects: [] },
  { id: 'u7', name: 'Priya Raman', email: 'p.raman@acme.test', role: 'pm', assigned_projects: ['p3'] },
];
const PROJECTS = [
  { id: 'p1', _id: 'p1', name: '588 Boyland Street', company_id: 'c1', status: 'active' },
  { id: 'p2', _id: 'p2', name: '114 Prospect Avenue', company_id: 'c1', status: 'active' },
  { id: 'p3', _id: 'p3', name: 'Pier 17 Fit-Out', company_id: 'c1', status: 'active' },
];
const CS = {
  licence_number: 'SI-004821',
  registered_project_ids: ['p1'],
  selectable: [
    { project_id: 'p1', name: '588 Boyland Street' },
    { project_id: 'p2', name: '114 Prospect Avenue' },
  ],
  registered_elsewhere: [],
};

function stub(page) {
  return page.route('**://api.levelog.com/**', (route) => {
    const url = route.request().url();
    const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*', 'Content-Type': 'application/json' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });
    let body = {};
    if (url.includes('/api/auth/me')) body = ME;
    else if (url.includes('feature-flags')) body = { flags: {} };
    // Null is what every reader already treats as UNKNOWN, i.e. not behind —
    // so no row draws a stale-install badge and the cards keep one height.
    else if (url.includes('/api/version')) body = { client_minimum_supported: null };
    else if (/\/cs-registrations(\?|$)/.test(url)) body = CS;
    else if (/\/api\/admin\/users(\?|$)/.test(url)) body = ROSTER;
    else if (/\/api\/projects(\?|\/|$)/.test(url)) body = PROJECTS;
    else if (/\/(logbooks|checkins|nfc|site-devices|documents|reports|notifications|workers|dob)/.test(url)) body = [];
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(body) });
  });
}

/**
 * Click a control by its name.
 *
 * `[tabindex]` IS IN THE SELECTOR AND HAS TO BE. GlassButton renders a bare
 * `Pressable` with no accessibilityRole, so react-native-web emits a
 * `<div tabindex="0">` with no `role="button"` at all — every Cancel, Save and
 * Add User on this screen. A selector of `[role="button"], button` finds the
 * FormSheet's own Close (which sets the role explicitly) and none of them,
 * which reads as "the primary action is not rendered".
 */
const clickByText = (page, text) => page.evaluate((needle) => {
  const all = [...document.querySelectorAll('[role="button"], button, [tabindex]')];
  const hit = all.find((n) => ((n.getAttribute('aria-label') || n.innerText || '').trim() === needle));
  if (!hit) return false;
  hit.click();
  return true;
}, text);

/**
 * THE ADD OPENER HAS NO NAME TO CLICK BY, which is a finding rather than a
 * harness inconvenience: it is the "+" in the page header, a
 * `GlassButton variant="icon"`, and GlassButton accepts no accessibilityLabel
 * and forwards none — so to a screen reader the only way into the Add form is
 * an unlabelled button. (The empty-state card offers a labelled "Add User",
 * but that one is only rendered when there are no users.)
 *
 * So it is located structurally instead: in the header band, a focusable with
 * an icon and no text, rightmost of the two (the other is Back). Narrow on
 * purpose — if the header gains a third icon this stops finding it and says
 * so, rather than clicking something else.
 */
const clickAddOpener = (page) => page.evaluate(() => {
  const icons = [...document.querySelectorAll('[tabindex="0"]')]
    .filter((n) => !(n.innerText || '').trim() && n.querySelector('svg'))
    .map((n) => ({ n, r: n.getBoundingClientRect() }))
    .filter((x) => x.r.top >= 0 && x.r.top < 80 && x.r.width > 20);
  if (icons.length !== 2) return icons.length;
  icons.sort((a, b) => a.r.left - b.r.left);
  icons[icons.length - 1].n.click();
  return true;
});

/**
 * Everything worth knowing about the sheet that is currently up, read in one
 * pass so the four properties describe the SAME moment.
 *
 * The sheet is found by role, not by a test id: react-native-web's Modal sets
 * role="dialog" and aria-modal on the presented content
 * (exports/Modal/ModalContent.js), so "is there a dialog" is answered by the
 * same attribute a screen reader uses. A block appended to the page — which is
 * what these four were — carries neither.
 */
const readSheet = (page) => page.evaluate(() => {
  const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
  if (!dialog) return { present: false };
  // The dialog element itself is the full-viewport fixed overlay; the SHEET is
  // the card inside it, and the card is what has to be on screen.
  const close = dialog.querySelector('[aria-label="Close"]');
  const card = close ? close.closest('[tabindex="-1"]') : null;
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      top: Math.round(r.top), left: Math.round(r.left),
      bottom: Math.round(r.bottom), right: Math.round(r.right),
      w: Math.round(r.width), h: Math.round(r.height),
    };
  };
  const active = document.activeElement;
  return {
    present: true,
    card: box(card),
    close: box(close),
    viewport: { w: window.innerWidth, h: window.innerHeight },
    focusInside: !!(card && active && card.contains(active) && active !== document.body),
    focusTag: active ? `${active.tagName.toLowerCase()}${active.getAttribute('placeholder') ? `[${active.getAttribute('placeholder')}]` : ''}` : null,
    // ── WHAT ACTUALLY SCROLLS ON THIS PAGE ────────────────────────────────
    // NOT document.scrollingElement. The Expo web shell ships
    // `body { overflow: hidden }`, so the document never scrolls and a probe
    // that watched its scrollTop would report "the page did not move" on a
    // page that cannot move — an instrument that cannot fail. The real
    // scroller is the ScrollView's own div, found by the property that makes
    // it one.
    appScrollTops: [...document.querySelectorAll('*')]
      .filter((n) => n.scrollHeight > n.clientHeight + 4
        && /auto|scroll/.test(getComputedStyle(n).overflowY))
      .map((n) => n.scrollTop),
    bodyOverflow: getComputedStyle(document.body).overflow,
    rootOverflow: getComputedStyle(document.documentElement).overflow,
    title: (dialog.innerText || '').split('\n')[0] || '',
    // Every control the sheet offers, so "the primary action is reachable" is
    // measured rather than assumed. `[tabindex]` for the reason above: the
    // app's buttons carry no role.
    controls: [...dialog.querySelectorAll('[role="button"], button, [tabindex="0"]')]
      .map((n) => ({ name: (n.getAttribute('aria-label') || n.innerText || '').trim(), ...box(n) }))
      .filter((c) => c.name && !c.name.includes('\n')),
  };
});

const inside = (b, vp) => !!b && b.w > 40 && b.h > 40
  && b.top >= 0 && b.left >= 0 && b.bottom <= vp.h + 1 && b.right <= vp.w + 1;

/** The page's own scroll state with no sheet up — the baseline each probe is
 *  compared against, and the value the lock must RESTORE. */
const readPage = (page) => page.evaluate(() => ({
  appScrollTops: [...document.querySelectorAll('*')]
    .filter((n) => n.scrollHeight > n.clientHeight + 4
      && /auto|scroll/.test(getComputedStyle(n).overflowY))
    .map((n) => n.scrollTop),
  bodyOverflow: getComputedStyle(document.body).overflow,
  rootOverflow: getComputedStyle(document.documentElement).overflow,
}));

async function probe(page, form, baseline) {
  const opened = form.open === null ? await clickAddOpener(page) : await clickByText(page, form.open);
  if (opened !== true) {
    return {
      ...form,
      harness: form.open === null
        ? `expected exactly 2 unlabelled icon controls in the header, found ${opened}`
        : `no control reading "${form.open}"`,
    };
  }
  await page.waitForTimeout(900);

  const before = await readSheet(page);
  if (!before.present) return { ...form, harness: null, fail: 'no dialog opened at all' };

  // ── THE LOCK, DRIVEN RATHER THAN INSPECTED ────────────────────────────────
  // A computed `overflow: hidden` is the mechanism; whether the page moves is
  // the property. Wheel over the backdrop, well clear of the card.
  await page.mouse.move(Math.round(WIDTH / 2), 8);
  await page.mouse.wheel(0, 1200);
  await page.waitForTimeout(400);
  const after = await readSheet(page);

  const vp = before.viewport;
  const primary = (before.controls || []).find((c) => c.name === form.primary);

  const checks = [
    ['PRESENTED  the sheet is inside the viewport', inside(before.card, vp),
      `card ${JSON.stringify(before.card)} vs viewport ${JSON.stringify(vp)}`],
    ['            and it is the right form', before.title.includes(form.title),
      `first line read "${before.title}", wanted "${form.title}"`],
    ['FOCUSED    focus moved into the sheet', before.focusInside,
      `document.activeElement is ${before.focusTag || 'nothing'}`],
    // THE SCROLLER HAS TO BE OFF ZERO FOR THIS TO MEAN ANYTHING. The page is
    // deliberately scrolled down before the first probe, so "it did not move"
    // is a statement about a list that COULD have moved.
    ['LOCKED     the list behind it did not move under a wheel',
      JSON.stringify(after.appScrollTops) === JSON.stringify(before.appScrollTops)
        && before.appScrollTops.some((t) => t > 0),
      `app scrollTops ${JSON.stringify(before.appScrollTops)} -> `
      + `${JSON.stringify(after.appScrollTops)}`
      + `${before.appScrollTops.some((t) => t > 0) ? '' : ' (and the list was at the top, so this proved nothing)'}`],
    // The document pin, asserted where it is OBSERVABLE. On the Expo shell
    // body is already hidden at rest, so only documentElement changes — and
    // asserting "body is hidden" there would be a check that cannot fail.
    ['            and the document scroller is pinned too',
      before.rootOverflow === 'hidden' && baseline.rootOverflow !== 'hidden',
      `documentElement overflow ${baseline.rootOverflow} -> ${before.rootOverflow}`],
    ['ESCAPABLE  a Close control is on screen', inside(before.close, vp)
      || (!!before.close && before.close.w > 20 && before.close.top >= 0 && before.close.bottom <= vp.h + 1),
      `close ${JSON.stringify(before.close)}`],
    [`            and "${form.primary}" is reachable without scrolling the page`,
      !!primary && primary.top >= 0 && primary.bottom <= vp.h + 1
        && primary.left >= 0 && primary.right <= vp.w + 1,
      primary ? JSON.stringify(primary) : 'the primary action is not rendered'],
  ];

  // ── AND THE KEYBOARD STAYS OPEN ───────────────────────────────────────────
  //
  // de2b330 (#388) is why this is here and not only in a source test. A
  // component declared in a render body is a new function object every render;
  // React compares element types by reference, rebuilds the subtree and
  // destroys the TextInput — so the keyboard closes after every character. The
  // source guard (adminUsersFormsArePresented.test.cjs) asserts the CAUSE is
  // absent. This asserts the PROPERTY, which a different cause — a key that
  // changes per render, a parent-driven remount, an effect that blurs — would
  // break while the source guard stayed green.
  //
  // THE TAG IS THE IDENTITY, as in scripts/focus-survives-keystroke.cjs: a
  // remount does not move the old node, it destroys it, and the replacement
  // carries no tag. So the tag's disappearance IS the remount, observed.
  if (form.types) {
    const tagged = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || !/^(input|textarea)$/i.test(el.tagName)) return null;
      el.setAttribute('data-sheet-probe', '1');
      // The Edit sheet opens PREFILLED with the user's name, so the caret goes
      // to the end and the expectation is prefix+abc rather than 'abc'.
      if (el.setSelectionRange) {
        try { el.setSelectionRange(el.value.length, el.value.length); } catch { /* not a text input */ }
      }
      return el.value;
    });
    if (tagged === null) {
      checks.push(['TYPEABLE   focus landed on a text field to type into', false,
        'the focused element is not an input, so the keystroke probe could not run']);
    } else {
      await page.keyboard.press('KeyA');
      await page.waitForTimeout(250);
      await page.keyboard.press('KeyB');
      await page.waitForTimeout(250);
      await page.keyboard.press('KeyC');
      await page.waitForTimeout(350);
      const typed = await page.evaluate(() => {
        const el = document.querySelector('[data-sheet-probe="1"]');
        return {
          alive: !!el,
          focused: !!el && document.activeElement === el,
          value: el ? el.value : null,
        };
      });
      const want = `${tagged}abc`;
      checks.push(['TYPEABLE   three characters land in the SAME field',
        typed.alive && typed.focused && typed.value === want,
        `the tagged node is ${typed.alive ? 'alive' : 'GONE (remounted)'}, `
        + `focused=${typed.focused}, value=${JSON.stringify(typed.value)}, `
        + `wanted ${JSON.stringify(want)} — a destroyed input is not a focused `
        + 'input (de2b330)']);
    }
  }

  // Escape is one of the three exits; closing between probes also proves the
  // lock is RELEASED, which a lock that is never lifted would fail on the next
  // form's baseline.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(700);
  const closed = await readSheet(page);
  checks.push(['ESCAPABLE  Escape dismissed it', !closed.present,
    'the sheet is still up after Escape']);

  // RESTORED TO THE BASELINE, not cleared to ''. On this shell the body's
  // resting value IS `hidden`, so a cleanup that blanked it would hand the
  // page a scrollbar it never had — "the page scrolls again" would be the
  // wrong assertion and would fail on correct code.
  const unlocked = await readPage(page);
  checks.push(['            and the page is put back exactly as it was',
    unlocked.bodyOverflow === baseline.bodyOverflow
      && unlocked.rootOverflow === baseline.rootOverflow,
    `body ${baseline.bodyOverflow}->${unlocked.bodyOverflow}, `
    + `html ${baseline.rootOverflow}->${unlocked.rootOverflow}`]);

  return { ...form, checks };
}

const FORMS = [
  // `open: null` — the Add opener is the unlabelled "+" in the header; see
  // clickAddOpener.
  // `types` marks the two sheets whose first field is a TextInput — the ones
  // the keystroke probe can run on. Registration opens on a spinner and Assign
  // is a picker; neither has a field to type into.
  { label: 'Add', open: null, title: 'Add New User', primary: 'Add User', types: true },
  { label: 'Edit', open: 'Edit', title: 'Edit User', primary: 'Save', types: true },
  { label: 'Registration', open: 'Registration', title: 'CS Registration', primary: 'Save' },
  { label: 'Assign', open: 'Assign', title: 'Assign Projects', primary: 'Save' },
];

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);

  let failures = 0;
  let harnessFaults = 0;
  let checked = 0;

  for (const theme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
    await ctx.addInitScript(([t, u, th]) => {
      localStorage.setItem('blueview_token', t);
      localStorage.setItem('blueview_user', u);
      localStorage.setItem('blueview_theme', th);
    }, [JWT, JSON.stringify(ME), theme]);

    const page = await ctx.newPage();
    await stub(page);
    const consoleErrors = [];
    page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));
    await page.goto(`http://localhost:${PORT}/admin/users`, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(2200);

    // ── THE HARNESS CHECK ────────────────────────────────────────────────
    // This screen renders "Admin Access Required" to every role but admin, and
    // that panel has no openers on it. A run that landed there would find no
    // controls and could be mistaken for four subtle failures.
    const seen = await page.evaluate(() => ({
      denied: (document.body.innerText || '').includes('Admin Access Required'),
      roster: (document.body.innerText || '').includes('Sal Ferraro'),
    }));
    if (seen.denied || !seen.roster) {
      console.error(`\nx HARNESS [${theme}]: the probe never reached the user list`
        + `${seen.denied ? ' — it is on the "Admin Access Required" panel' : ''}.`
        + '\n  Nothing below was measured. This is not a pass and not a failure.');
      harnessFaults += 1;
      await ctx.close();
      continue; // eslint-disable-line no-continue
    }

    // SCROLL THE LIST DOWN FIRST. Two reasons, and both matter:
    //   - "the list behind did not move" is vacuous against a list already at
    //     the top, so the lock probe needs somewhere to have moved FROM;
    //   - it is also the operator's actual position. He was part-way down a
    //     roster when he tapped Edit, and the old inline block rendered
    //     relative to the page rather than the viewport.
    await page.mouse.move(Math.round(WIDTH / 2), Math.round(HEIGHT / 2));
    await page.mouse.wheel(0, 600);
    await page.waitForTimeout(500);
    const baseline = await readPage(page);

    console.log(`\n=== ${theme} · ${WIDTH}x${HEIGHT} ===`);
    console.log(`  page at rest: app scrollTops ${JSON.stringify(baseline.appScrollTops)}, `
      + `body:${baseline.bodyOverflow} html:${baseline.rootOverflow}`);
    for (const form of FORMS) {
      // eslint-disable-next-line no-await-in-loop
      const r = await probe(page, form, baseline);
      if (r.harness) {
        console.error(`  x HARNESS  ${r.label}: ${r.harness}`);
        harnessFaults += 1;
        continue; // eslint-disable-line no-continue
      }
      if (r.fail) {
        console.log(`  FAIL ${r.label} — ${r.fail}`);
        checked += 1;
        failures += 1;
        continue; // eslint-disable-line no-continue
      }
      console.log(`  ${r.label}`);
      for (const [name, pass, detail] of r.checks) {
        checked += 1;
        if (pass) { console.log(`    ok   ${name}`); } else {
          failures += 1;
          console.log(`    FAIL ${name}\n           ${detail}`);
        }
      }
    }
    if (consoleErrors.length) {
      console.log(`  page errors: ${consoleErrors.slice(0, 3).join(' | ')}`);
      failures += consoleErrors.length;
    }
    await ctx.close();
  }

  await browser.close();
  server.close();

  console.log(`\n${checked - failures}/${checked} checks clean across ${FORMS.length} forms x 2 themes at ${WIDTH}px`);
  if (harnessFaults) {
    console.error(`\nx ${harnessFaults} HARNESS fault(s) — this run did not measure its subject.`);
    process.exit(2);
  }
  if (failures) {
    console.error(`\nx ${failures} failure(s)`);
    process.exit(1);
  }
  console.log('ALL PASS');
})().catch((e) => { console.error(e); process.exit(2); });
