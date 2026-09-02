#!/usr/bin/env node
/**
 * MOUNT SMOKE TEST — loads real routes against the production web build and
 * fails on any console error or error-boundary render.
 *
 * WHY THIS EXISTS
 * Four shared components (IconPod, SiteNav, ToastProvider, FloatingNav) were
 * converted to per-render theming but each kept a reference to a `styles`
 * const that no longer existed. Every gate was green:
 *   - the frozen-theme-ref grep passed (the refs WERE rewired)
 *   - the wiring checker passed (it scanned to EOF and swallowed the last
 *     component in each file)
 *   - the backend suite passed (irrelevant)
 *   - the frontend suite passed (it parses source, it does not MOUNT)
 * and the app still crashed to "Something went wrong · styles is not defined"
 * on first paint. Nothing in CI executes a component. This does.
 *
 * It is deliberately cheap and dumb: no assertions about appearance, no
 * snapshots to rot. One question per route — did it mount without throwing.
 *
 * USAGE
 *   npx expo export --platform web --output-dir dist
 *   node scripts/smoke-mount.cjs --dist dist
 *
 * Requires playwright-core and a Chromium binary. See --help for env vars.
 * Exits 1 on the first route that errors, 0 if every route mounts clean.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
if (process.argv.includes('--help')) {
  console.log(`smoke-mount — mount every route, fail on console errors.

  --dist <dir>     production export dir (default: dist)
  --port <n>       static server port (default: 5810)
  --theme <t>      light | dark | both (default: both)
  PW_CORE          path to playwright-core (default: resolve 'playwright-core')
  CHROME           path to a Chromium executable (default: playwright default)`);
  process.exit(0);
}

const DIST = path.resolve(arg('dist', 'dist'));
const PORT = Number(arg('port', 5810));
const THEMES = arg('theme', 'both') === 'both' ? ['light', 'dark'] : [arg('theme', 'both')];

if (!fs.existsSync(path.join(DIST, 'index.html'))) {
  console.error(`✗ no index.html in ${DIST} — run: npx expo export --platform web --output-dir ${DIST}`);
  process.exit(1);
}

let chromium;
try {
  ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
} catch {
  console.error('✗ playwright-core not resolvable. Install it, or set PW_CORE=/path/to/playwright-core.');
  process.exit(1);
}

// Routes worth mounting: the main surfaces plus the screens that render the
// shared components which caused the original crash (nav, toasts, glass cards,
// icon pods). A route added here costs ~2s.
const ROUTES = [
  '/',                                  // dashboard — FloatingNav, SiteNav, IconPod, GlassCard
  '/login',
  '/projects',                          // ProjectsTable
  '/project/p1',                        // project detail — CompliancePanel, DefconHeader
  '/project/p1/dob-logs',               // DOB compliance
  '/workers',
  '/workers/w1',                        // worker detail — cert/OSHA expiry
  '/logbooks',
  '/logbooks/daily_jobsite?projectId=p1',
  // The two forms ported onto the shared stepper. They are here for the same
  // reason daily_jobsite is: this job is the ONLY thing that executes a logbook
  // screen, and the port moved every one of their constants into a model and
  // their whole chrome into a shared component. A bad import or a stale
  // reference in either would mount to an error boundary and nothing else in
  // the suite would notice.
  '/logbooks/osha_log?projectId=p1',
  '/logbooks/scaffold_maintenance?projectId=p1',
  // Ported onto the shared stepper in batch 1a. Same reason as the pair
  // above: this job is the only thing that executes a logbook screen.
  '/logbooks/toolbox_talk?projectId=p1',
  // THE ONLY NEW EDITOR SINCE THE PORT, and the one with the strongest claim
  // to a mount: every other route here was an existing screen moved onto the
  // stepper, whereas this one was written against it from nothing. It also
  // reaches for two things at mount that no other editor does — dobAPI for the
  // violation suggestions and useCpProfile before the log read returns — and
  // an error-boundary render is the only way either would surface, since the
  // rest of the suite reads this file's source without ever executing it.
  '/logbooks/site_superintendent_log?projectId=p1',
  // THE CP'S DAILY LOG, and the twin of /site/daily-logs below. Its
  // superintendent's copy was already mounted here and this one was not, so
  // half of a role-split pair was executed and half was only ever parsed —
  // exactly the gap that lets an edit land on the CP's screen unverified.
  // Both render a signature block, and a named import that binds to undefined
  // is a property read that every static sweep passes.
  '/daily-log',
  // THE CONSENT SCREEN. Reached only from a signing path, so nothing else in
  // CI would ever execute it — and it is the page a man reads before he signs
  // a statutory record. The stub returns {} for /api/esra-consent, so this
  // mounts the OUTAGE branch; the agreement branch is verified separately.
  '/consent',
  '/admin/site-devices',
  '/admin/users',
  '/reports',
  '/settings',
  '/checkin',
  '/owner',
  // THE SITE DEVICE — a fixed tablet at the gate, read by DOB inspectors, and
  // until now the only surface in the app with ZERO executed coverage. These
  // five need more than a URL: every one of them redirects away unless
  // useAuth() reports siteMode true AND a siteProject, which AuthContext only
  // sets when /api/auth/me (or the stored user) carries site_mode. So they run
  // against SITE_USER instead of USER — see siteRoute() below. Without that
  // the screens would bounce to '/' and report a vacuous green.
  '/site',
  '/site/logbooks',
  '/site/documents',
  '/site/daily-logs',
  '/site/checkins',
];

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
const USER = { id: 'u1', email: 'smoke@test.local', full_name: 'Smoke', name: 'Smoke', role: 'owner', company_name: 'Acme', company_id: 'c1', account_status: 'approved' };
const PROJECT = { id: 'p1', _id: 'p1', name: 'Smoke Site', address: '1 Test St, Brooklyn', company_id: 'c1', status: 'active', nyc_bin: '2115914' };
const WORKER = { id: 'w1', _id: 'w1', name: 'Test Worker', company_id: 'c1', trade: 'Carpenter', certifications: [] };
// The gate tablet. AuthContext reads site_mode/project_id/project_name off
// /api/auth/me to set siteMode + siteProject; a user without them makes every
// /site/* screen router.replace() away before it renders anything.
const SITE_USER = { ...USER, id: 'sd1', email: 'site@test.local', full_name: 'Gate Tablet', name: 'Gate Tablet', role: 'site_device', site_mode: true, project_id: 'p1', project_name: 'Smoke Site', project: PROJECT };
// A /site/* route only reaches its own screen as a site device.
const siteRoute = (r) => r === '/site' || r.startsWith('/site/');

// Every API call resolves to a benign shape. The point is mounting, not data.
function stub(page, me = USER) {
  return page.route('**://api.levelog.com/**', (route) => {
    const url = route.request().url();
    const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*', 'Content-Type': 'application/json' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors, body: '' });
    let body = {};
    if (url.includes('/api/auth/me')) body = me;
    else if (url.includes('feature-flags')) body = { flags: {} };
    else if (url.includes('dob-summary')) body = { by_project: {}, totals: {} };
    else if (url.match(/\/api\/projects\/p1(\?|$)/)) body = PROJECT;
    else if (url.match(/\/api\/projects(\?|\/|$)/)) body = [PROJECT];
    else if (url.match(/\/api\/workers\/w1(\?|$)/)) body = WORKER;
    else if (url.match(/\/api\/workers(\?|$)/)) body = [WORKER];
    else if (/\/(logbooks|checkins|nfc|site-devices|documents|reports|notifications|annotations|admins|companies)/.test(url)) body = [];
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(body) });
  });
}

// Console noise that is not a mount failure. Keep this list SHORT and specific —
// every entry is a class of bug this test can no longer see.
const IGNORE = [
  /Download the React DevTools/i,
  /useNativeDriver/i,
  /componentWillReceiveProps/i,
  /was not wrapped in act/i,
  /favicon\.ico/i,
  /Failed to load resource.*404/i,
];
const ignored = (t) => IGNORE.some((re) => re.test(t));

(async () => {
  await new Promise((r) => server.listen(PORT, r));
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);

  const failures = [];
  let checked = 0;

  for (const theme of THEMES) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await ctx.addInitScript(([t, u, th]) => {
      localStorage.setItem('blueview_token', t);
      localStorage.setItem('blueview_user', u);
      localStorage.setItem('blueview_theme', th);
    }, [JWT, JSON.stringify(USER), theme]);

    for (const route of ROUTES) {
      const page = await ctx.newPage();
      const me = siteRoute(route) ? SITE_USER : USER;
      // Page-level init scripts run after the context one, so this overwrites
      // the stored user for the gate tablet without disturbing the other routes.
      if (me !== USER) await page.addInitScript((u) => localStorage.setItem('blueview_user', u), JSON.stringify(me));
      await stub(page, me);
      const errors = [];
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
      page.on('console', (m) => {
        if (m.type() !== 'error') return;
        const t = m.text();
        if (!ignored(t)) errors.push(`console: ${t.slice(0, 300)}`);
      });

      try {
        await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: 'networkidle', timeout: 45000 });
        await page.waitForTimeout(1800);
        const boundary = await page.evaluate(() => {
          const body = document.body.innerText || '';
          const hit = ['Something went wrong', 'is not defined', 'is not a function', 'Unmatched Route']
            .find((s) => body.includes(s));
          return hit || null;
        });
        if (boundary) errors.push(`error-boundary/undefined-ref: "${boundary}"`);
      } catch (e) {
        errors.push(`navigation: ${e.message.split('\n')[0]}`);
      }

      checked += 1;
      if (errors.length) {
        failures.push({ theme, route, errors });
        console.log(`✗ [${theme}] ${route}`);
        errors.slice(0, 4).forEach((e) => console.log(`    ${e}`));
      } else {
        console.log(`✓ [${theme}] ${route}`);
      }
      await page.close();
    }
    await ctx.close();
  }

  await browser.close();
  server.close();

  console.log(`\n${checked - failures.length}/${checked} route-mounts clean`);
  if (failures.length) {
    console.log(`\n${failures.length} FAILED:`);
    failures.forEach((f) => console.log(`  [${f.theme}] ${f.route}`));
    process.exit(1);
  }
})().catch((e) => { console.error(e); process.exit(2); });
