#!/usr/bin/env node
/**
 * EVERY TAP TARGET ON A LOGBOOK EDITOR CLEARS THE SCREEN'S OWN FLOOR.
 *
 * `touchTarget.min` is 56, and theme.js says why in its own words: "The CP
 * surfaces are used OUTDOORS, GLOVED, ONE-HANDED, by people who are older and
 * not technical. 44 is Apple's accessibility floor for a fingertip on a clean
 * screen indoors; none of those conditions hold on a jobsite."
 *
 * ── WHAT THIS EXISTS FOR, MEASURED ─────────────────────────────────────────
 *
 * The superintendent log's three collapsible rows shipped with the disclosure
 * control at the height of its own TEXT, because the Pressable set no minimum:
 *
 *     button    32pt   UNSAFE CONDITIONS AND THE ORDERS YOU GAVE
 *     checkbox  60pt   No unsafe conditions observed and no orders given
 *     button    18pt   INCIDENTS OR DAMAGE
 *     checkbox  56pt   No incidents or damage today
 *
 * An 18-point way IN sitting directly above a compliant 56-point attestation.
 * The superintendent reported he could tick "nothing to report" and could not
 * add a finding, which is exactly what those numbers describe. The chevron
 * worked the whole time -- and a source-text check asking "does the row have
 * an onToggle" would have said so.
 *
 * SO IT IS MEASURED IN A BROWSER, NOT READ. Height here is the product of
 * font size, line wrapping, flex rules and whatever the parent does; the
 * SHORTEST TITLE HAD THE SMALLEST TARGET, which is not a decision anybody
 * made and not a fact any grep can reach.
 *
 * ── IT WALKS THE STEPS, WHICH IS THE HALF smoke-mount CANNOT ───────────────
 *
 * The mount smoke proves every screen paints. It does not press Next, so
 * everything past step 1 of a four-step editor is unexecuted by CI -- and all
 * three of the rows above are on step 3.
 *
 * THE POPULATION IS DERIVED, NOT LISTED: every editor calling
 * `buildStepperStyles()`, the same predicate pinnedInkIsLegible.test.cjs uses.
 * A thirteenth editor is in the set the day it is written.
 *
 *   node scripts/touch-targets.cjs --dist dist
 *
 * Exit 1 if any target is under the floor, so it gates CI.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > -1 ? process.argv[i + 1] : d;
};
const DIST = path.resolve(arg('dist', 'dist'));
const PORT = Number(arg('port', 5903));
const ROOT = path.join(__dirname, '..');

let chromium;
try {
  ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
} catch (e) {
  console.error('playwright-core is not resolvable; set PW_CORE.');
  process.exit(1);
}

// THE FLOOR IS READ OUT OF theme.js, not retyped. A check carrying its own
// copy of the number it enforces goes on enforcing the old one.
const THEME = fs.readFileSync(path.join(ROOT, 'src', 'styles', 'theme.js'), 'utf8');
const FLOOR = Number(/export const touchTarget = \{[^}]*?min:\s*(\d+)/s.exec(THEME)?.[1]);

// THE EDITORS, DERIVED. Same predicate as pinnedInkIsLegible.test.cjs.
const LOGBOOKS = path.join(ROOT, 'app', 'logbooks');
const EDITORS = fs.readdirSync(LOGBOOKS)
  .filter((f) => /\.jsx$/.test(f))
  .filter((f) => fs.readFileSync(path.join(LOGBOOKS, f), 'utf8').includes('buildStepperStyles'))
  .map((f) => f.replace(/\.jsx$/, ''))
  // `photos` is not a stepper; it borrows the chrome only.
  .filter((f) => f !== 'photos');

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
  } catch (e) { res.writeHead(404); res.end('nf'); }
});

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const JWT = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ exp: 4102444800, sub: 'u1' })}.x`;
const USER = { id: 'u1', email: 'targets@test.local', full_name: 'Smoke', name: 'Smoke', role: 'owner', company_name: 'Acme', company_id: 'c1', account_status: 'approved' };
const PROJECT = { id: 'p1', _id: 'p1', name: 'Smoke Site', address: '1 Test St', company_id: 'c1', status: 'active' };

const MEASURE = (floor) => {
  const out = [];
  for (const el of document.querySelectorAll('[role="button"],[role="checkbox"],[role="radio"],[role="switch"]')) {
    const r = el.getBoundingClientRect();
    if (r.height === 0 || r.width === 0) continue;
    const label = (el.innerText || el.getAttribute('aria-label') || '')
      .replace(/\s+/g, ' ').trim();
    if (!label) continue;
    if (r.height < floor) {
      out.push({ h: Math.round(r.height), role: el.getAttribute('role'), label: label.slice(0, 54) });
    }
  }
  return out;
};

(async () => {
  if (!Number.isFinite(FLOOR) || FLOOR < 40) {
    console.error(`could not read touchTarget.min from theme.js (got ${FLOOR})`);
    process.exit(1);
  }
  if (EDITORS.length < 10) {
    console.error(`only ${EDITORS.length} editors found — the tree moved and `
      + 'this check is measuring nothing');
    process.exit(1);
  }
  console.log(`\nfloor ${FLOOR}pt, from theme.js · ${EDITORS.length} editors, derived\n`);

  await new Promise((r) => server.listen(PORT, r));
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 900, deviceScaleFactor: 2 },
    isMobile: true, hasTouch: true,
  });
  await ctx.route('**/api/**', (route) => {
    const u = route.request().url();
    const json = (b) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(b) });
    if (u.includes('/auth/me')) return json(USER);
    if (u.includes('/projects/p1')) return json(PROJECT);
    if (u.includes('/projects')) return json([PROJECT]);
    return json([]);
  });
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('token', t);
    localStorage.setItem('user', u);
  }, [JWT, JSON.stringify(USER)]);

  let bad = 0;
  let measured = 0;
  for (const editor of EDITORS) {
    const page = await ctx.newPage();
    await page.goto(`http://localhost:${PORT}/logbooks/${editor}?projectId=p1`,
      { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);

    // WALK THE STEPS. Next is never blocked on these editors — "Moving between
    // steps is never BLOCKED, it just writes what he has first" — so this
    // reaches every step without filling anything in.
    for (let step = 1; step <= 6; step += 1) {
      const under = await page.evaluate(MEASURE, FLOOR);
      measured += 1;
      for (const u of under) {
        bad += 1;
        console.log(`  UNDER  ${editor} step ${step}  ${String(u.h).padStart(3)}pt  `
          + `${u.role}  ${u.label}`);
      }
      // NEXT IS NOT ALWAYS LIVE. `toolbox_talk` blocks it on its required
      // step-1 fields, and the sign step has none at all. A blocked Next is
      // the end of the walk for that editor, not a failure -- the first draft
      // called `.click()` unconditionally and hung for 30 seconds on a
      // disabled control, which reports a timeout where the honest answer is
      // "this editor stops here".
      const next = page.getByText(/^Next$/).last();
      if (!(await next.count())) break;
      if (await next.isDisabled().catch(() => true)) break;
      await next.click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(900);
    }
    await page.close();
  }
  await browser.close();
  server.close();

  console.log(`\n${measured} step-views measured, ${bad} target(s) under ${FLOOR}pt`);
  if (bad) {
    console.error('\nA control the thumb cannot hit is not a control. These screens '
      + 'are used outdoors, gloved, one-handed — see touchTarget in theme.js.');
    process.exit(1);
  }
  console.log('Every tap target clears the floor.');
})().catch((e) => { console.error('FAILED:', e); process.exit(1); });
