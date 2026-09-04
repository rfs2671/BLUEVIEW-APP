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
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

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

// ── THE API IS A REAL ORIGIN, NOT AN INTERCEPTED ONE ─────────────────────
//
// This job used to answer every API call with `page.route(...).fulfill()` and
// a header block containing `Access-Control-Allow-Headers: '*'`. It had an
// `if (method === 'OPTIONS')` branch, so it read as though it covered CORS.
//
// IT NEVER RAN. Playwright's route interception short-circuits BEFORE the
// browser issues a preflight: with interception on, the handler is asked for
// GET and the preflight does not happen at all. Measured, not assumed --
// handler saw ["GET"], the origin server saw []; with interception off the
// same page produced ["OPTIONS /api/probe", "GET /api/probe"]. The OPTIONS
// branch was dead code from the day it was written, and the '*' in it was
// never sent to anything.
//
// That is what cost seven days. X-Client-Version shipped on every request from
// 2026-08-28 and was missing from allow_headers, so the real server answered
// `400 Disallowed CORS headers` and Chrome refused to send the request at all
// -- every endpoint, including auth/login. Native sends no Origin and gets no
// preflight; /api/version is a simple GET and needs none; the post-deploy
// login check speaks urllib. This job is the only thing in CI that runs the
// real web bundle in a real browser, and it had removed the browser's CORS
// machinery from the picture entirely. It reported 37/37 clean while the web
// app could not sign in.
//
// So the stub is now a REAL HTTPS ORIGIN. Chromium resolves the hostname the
// production bundle is built against to a local server
// (--host-resolver-rules), which answers preflights from server.py's OWN
// allow_headers list. The browser does real CORS against it: a header the real
// server would refuse is refused here, the request is blocked, and the console
// error that follows is already a mount failure to this job.
const REPO = path.join(__dirname, '..', '..');
const SERVER_PY = path.join(REPO, 'backend', 'server.py');
const API_HOST = 'api.levelog.com';
const API_PORT = Number(arg('api-port', 5899));

function serverAllowHeaders() {
  const src = fs.readFileSync(SERVER_PY, 'utf8');
  const block = src.match(/allow_headers=\[([^\]]*)\]/);
  if (!block) throw new Error(`no allow_headers=[...] found in ${SERVER_PY}`);
  // Entries are string literals or module constants (CLIENT_REQUEST_ID_HEADER,
  // CLIENT_VERSION_HEADER). Resolve the constants out of the same file.
  const consts = {};
  for (const m of src.matchAll(/^([A-Z][A-Z0-9_]*)\s*=\s*["']([A-Za-z0-9-]+)["']/gm)) consts[m[1]] = m[2];
  const names = [];
  for (const raw of block[1].split(',')) {
    const tok = raw.replace(/#.*$/, '').trim();
    if (!tok) continue;
    const lit = tok.match(/^["']([A-Za-z0-9-]+)["']$/);
    if (lit) { names.push(lit[1]); continue; }
    if (consts[tok]) { names.push(consts[tok]); continue; }
    // NEVER FALL BACK TO PERMISSIVE. An entry this cannot resolve means the
    // derivation has rotted, and a stub that guesses wide is the original bug.
    throw new Error(`unresolved entry in allow_headers: ${tok} — add it to the resolver, do not widen the stub`);
  }
  if (!names.length) throw new Error('allow_headers parsed to an empty list');
  return names;
}

// Starlette unions the fetch-spec safelist onto whatever is configured, so the
// real preflight response carries these too.
const SAFELISTED = ['Accept', 'Accept-Language', 'Content-Language', 'Content-Type'];
const ALLOW_HEADERS = [...new Set([...SAFELISTED, ...serverAllowHeaders()])].sort();
const ALLOW_SET = new Set(ALLOW_HEADERS.map((h) => h.toLowerCase()));

// A throwaway cert for a hostname we are impersonating locally. Chromium is
// launched with --ignore-certificate-errors, so this only has to exist.
function selfSignedCert() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'smoke-tls-'));
  const key = path.join(dir, 'k.pem');
  const crt = path.join(dir, 'c.pem');
  try {
    execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes',
      '-keyout', key, '-out', crt, '-days', '1',
      '-subj', `/CN=${API_HOST}`, '-addext', `subjectAltName=DNS:${API_HOST}`],
      { stdio: 'ignore' });
  } catch (e) {
    // LOUD, NOT PERMISSIVE. Falling back to route interception here would
    // silently restore the blind spot this whole change exists to remove.
    throw new Error('openssl is required to serve the local API origin: ' + e.message);
  }
  return { key: fs.readFileSync(key), cert: fs.readFileSync(crt), dir };
}

// STRICTNESS THAT IS NEVER EXERCISED IS THE SAME BUG IN A DIFFERENT HAT — the
// counter below is what caught the dead OPTIONS branch. The run fails if it
// never saw a preflight.
const seen = { preflights: 0, refused: [] };

// What the API answers depends on which route is mounting (the gate tablet
// sees a different /auth/me; a filed route needs the filed by-project read).
// Pages are driven strictly one at a time, so a single mutable cell is enough.
const current = { me: null, filed: null };

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
  // ── THE PLAN LIST ────────────────────────────────────────────────────────
  //
  // Nothing in CI executed this screen, and it is the one the CP spends his
  // day in: it owns the file listing, the folder grouping and the PDF viewer
  // it launches. It earned a route the moment its rows started rendering an
  // <Image> per plan — a thumbnail component that throws takes the whole list
  // with it, and every static gate here would still be green.
  '/projects/p1/files',
  '/workers',
  '/workers/w1',                        // worker detail — cert/OSHA expiry
  '/logbooks',
  '/logbooks/daily_jobsite?projectId=p1',
  // ── THE FILED VIEW, WHICH IS A DIFFERENT SCREEN FROM THE EDITOR ───────────
  //
  // A locked log no longer renders its steps behind pointerEvents='none'; it
  // renders FiledLogView. Every route above mounts an UNFILED day (the stub
  // answers [] for the by-project read), so none of them executes that branch
  // at all — the filed view would have had zero executed coverage and this
  // job's whole claim is that it is the only thing that executes a screen.
  //
  // TWO TYPES, DELIBERATELY, because the branch that matters most is the one
  // that differs between them: daily_jobsite CARRIES activities[].photos and
  // must render the photographs section; toolbox_talk cannot and must render
  // NO such section. A single fixture would execute one side of that rule and
  // report clean while the other was broken.
  //
  // `filed=daily_jobsite` / `filed=toolbox_talk` is read by the stub below,
  // which answers the by-project read with a FILED document instead of [].
  '/logbooks/daily_jobsite?projectId=p1&filed=daily_jobsite',
  '/logbooks/toolbox_talk?projectId=p1&filed=toolbox_talk',
  // AND THE PHOTOGRAPHS SCREEN ITSELF — the dedicated screen a filed log
  // routes to. Nothing else in CI renders it, and it owns a camera, an
  // offline queue and the per-row refusal for a crew row with no identity.
  '/logbooks/photos?logbookId=lb1',
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
  // ── AND THE SEVEN THAT WERE NEVER EXECUTED BY ANYTHING ────────────────────
  //
  // Eleven editors share one load path and one save path, and until now four of
  // them could be mounted here while the other seven were only ever READ — by
  // the source sweeps, which cannot see a missing binding or a bad import.
  //
  // That gap was not theoretical. The fetch-and-compare change
  // (src/utils/draftFreshness.js) added an import, a hook and a new prop to all
  // eleven at once; a typo in any of the seven below would have mounted to an
  // error boundary and every other gate in this workflow would have stayed
  // green. The rule the file already states — this job is the ONLY thing that
  // executes a logbook screen — applies to all of them or to none.
  //
  // ~2s each. Cheap next to a CP meeting a blank screen at the gate.
  '/logbooks/crane_operations?projectId=p1',
  '/logbooks/concrete_operations?projectId=p1',
  '/logbooks/excavation_monitoring?projectId=p1',
  '/logbooks/hot_work?projectId=p1',
  '/logbooks/fall_protection?projectId=p1',
  '/logbooks/ssc_daily_safety_log?projectId=p1',
  // The one editor that owns no stepper — so it renders DraftConflictNotice
  // itself, and is the only place that wiring can be executed at all.
  '/logbooks/preshift_signin?projectId=p1',
  // THE CONSENT SCREEN. Reached only from a signing path, so nothing else in
  // CI would ever execute it — and it is the page a man reads before he signs
  // a statutory record. The stub returns {} for /api/esra-consent, so this
  // mounts the OUTAGE branch; the agreement branch is verified separately.
  //
  // AND THIS ENTRY WAS GREEN THROUGH A TWO-DAY TOTAL SIGNING OUTAGE. Every CP
  // signature on the platform was blocked from 2026-09-01 to 2026-09-03 because
  // RouteGuard's CP allowlist did not carry /consent, and this job never saw
  // it: it signs in as an OWNER, so the CP arm of the guard never runs, and it
  // asks only "did anything throw", which a redirect does not. The two
  // questions it cannot ask - does the agreement PAINT, and does the accept
  // POST fire, for the role the guard actually confines - are answered by
  // scripts/consent-paint.cjs.
  // THE CP'S DECISION SURFACE on flagged check-ins — approve, send home,
  // assign trade. It is not a logbook editor, so nothing above covers it, and
  // like every other screen here it is executed nowhere else in CI. It now
  // holds a decision on the device when the server is unreachable and overlays
  // the queue onto every refetch, so it has real work to do at mount.
  '/logbooks/review?projectId=p1',
  '/consent',
  '/admin/site-devices',
  '/admin/users',
  '/reports',
  '/settings',
  '/checkin',
  '/owner',
  // THE PURGE QUEUE. The only screen from which a project's entire compliance
  // history can be destroyed, and it had no executed coverage — nothing else
  // in CI renders it. It also now renders the retention brake (hold banner,
  // blocked purge control) off GET /projects/pending-deletion, and a screen
  // that silently failed to draw that would offer a live delete button on a
  // project the server is going to refuse.
  '/owner/pending-deletion',
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
// job_completion_date / purge_eligible_at are present so the retention card on
// /project/p1 mounts its POPULATED branch. Its empty branch is the default
// everywhere else in this file, so both get executed across the run.
const PROJECT = { id: 'p1', _id: 'p1', name: 'Smoke Site', address: '1 Test St, Brooklyn', company_id: 'c1', status: 'active', nyc_bin: '2115914', job_completion_date: '2020-03-01', job_completion_co_number: '121234567', completion_source: 'admin_attested', purge_eligible_at: '2027-03-01', legal_hold: false, no_completion_attested: false };
// FOUR rows, one per branch the retention block can take — each is reachable
// only from a row in that exact state and nothing else in the run renders it:
//
//   p9  BLOCKED by a legal hold
//   p8  BLOCKED for a missing completion — the state EVERY project in
//       production is in, and the branch this change added
//   p7  CLEARED by a never-completed attestation
//   p6  CLEARED by an elapsed retention period. The only row that renders the
//       completed line, and therefore the ONLY place the C of O number is ever
//       drawn on this screen: the blocked branch renders the refusal instead,
//       so p9's number never paints.
//
// p7 and p6 are also the only rows that draw a LIVE purge button, which keeps
// "Permanently Delete" present as a positive control — without one, "Deletion
// blocked" everywhere would be indistinguishable from a screen stuck blocked.
const PENDING_DELETION = {
  count: 4,
  items: [
    { id: 'p9', name: 'Held Site', address: '9 Hold St', company_id: 'c1', nyc_bin: '2115915', marked_by: 'u1', marked_at: '2026-08-01T00:00:00Z', dob_logs_count: 12, checkins_count: 340, job_completion_date: '2025-06-01', job_completion_co_number: '121234567', completion_source: 'admin_attested', legal_hold: true, legal_hold_reason: 'Kaplan v. 588 Boyland', legal_hold_by: 'u1', legal_hold_at: '2026-08-02T00:00:00Z', purge_eligible_at: '2032-06-01', no_completion_attested: false, no_completion_reason: null, no_completion_attested_by: null, purge_blocked: true, purge_block_reason: 'A legal hold is in force on this project: Kaplan v. 588 Boyland. Records cannot be deleted while the hold stands. A hold does not expire; an admin must lift it.' },
    { id: 'p8', name: 'Unrecorded Site', address: '8 Unknown St', company_id: 'c1', nyc_bin: '2115916', marked_by: 'u1', marked_at: '2026-08-01T00:00:00Z', dob_logs_count: 3, checkins_count: 11, job_completion_date: null, job_completion_co_number: null, completion_source: null, legal_hold: false, legal_hold_reason: null, legal_hold_by: null, legal_hold_at: null, purge_eligible_at: null, no_completion_attested: false, no_completion_reason: null, no_completion_attested_by: null, purge_blocked: true, purge_block_reason: 'This project has no recorded job completion, so the 7-year retention period cannot be computed and its records may not be destroyed. An admin must either record the final Certificate of Occupancy (number and date) or attest on the record that this project was never completed and may be purged.' },
    { id: 'p7', name: 'Attested Site', address: '7 Attested St', company_id: 'c1', nyc_bin: '2115917', marked_by: 'u1', marked_at: '2026-08-01T00:00:00Z', dob_logs_count: 1, checkins_count: 2, job_completion_date: null, job_completion_co_number: null, completion_source: null, legal_hold: false, legal_hold_reason: null, legal_hold_by: null, legal_hold_at: null, purge_eligible_at: null, no_completion_attested: true, no_completion_reason: 'Permit withdrawn; no work performed.', no_completion_attested_by: 'u1', no_completion_attested_at: '2026-08-03T00:00:00Z', purge_blocked: false, purge_block_reason: null },
    { id: 'p6', name: 'Elapsed Site', address: '6 Elapsed St', company_id: 'c1', nyc_bin: '2115918', marked_by: 'u1', marked_at: '2026-08-01T00:00:00Z', dob_logs_count: 7, checkins_count: 84, job_completion_date: '2010-01-01', job_completion_co_number: '121234567', completion_source: 'admin_attested', legal_hold: false, legal_hold_reason: null, legal_hold_by: null, legal_hold_at: null, purge_eligible_at: '2017-01-01', no_completion_attested: false, no_completion_reason: null, no_completion_attested_by: null, purge_blocked: false, purge_block_reason: null },
  ],
};
const WORKER = { id: 'w1', _id: 'w1', name: 'Test Worker', company_id: 'c1', trade: 'Carpenter', certifications: [] };

// ── FILED LOGS, so the filed view has something to render ───────────────────
//
// Both are `status: 'submitted'` + `is_locked` — which is what makes the
// editors set `locked` and the stepper take the FiledLogView branch instead of
// rendering steps.
//
// THE DAILY JOBSITE ONE CARRIES ROWS OF THREE KINDS ON PURPOSE, because each
// draws a different part of the photographs section and nothing else executes
// any of them: a row with a photograph (the thumbnail + the added-after-filing
// badge), a row with an identity and no photograph (the Add control), and a
// row with NO activity_id at all (the refusal, and the `remediable` sentence
// naming the backfill).
const FILED_DAILY = {
  id: 'lb1', _id: 'lb1', project_id: 'p1', log_type: 'daily_jobsite',
  date: '2026-08-25', status: 'submitted', is_locked: true,
  cp_name: 'Smoke CP', cp_signature: { ink: 'AAAA', affirmed: true },
  updated_at: '2026-08-25T22:10:00Z',
  data: {
    weather: 'Clear, 78F',
    general_description: 'Formwork on levels 3 and 4.',
    permits_posted: true,
    site_safety_orange: false,
    activities: [
      {
        activity_id: 'act_1', company: 'Acme Concrete', trade: 'Concrete',
        worker_count: 6, work_description: 'Deck pour',
        photos: [{ photo_id: 'p1', original_r2_key: 'k1', added_after_filing: true }],
      },
      { activity_id: 'act_2', company: 'Beta Steel', trade: 'Ironwork', photos: [] },
      { company: 'Legacy Co', trade: 'Demolition', photos: [] },
    ],
  },
};
// THE OTHER SIDE OF THE RULE. A toolbox talk has no activities[].photos
// concept, so the filed view must render NO photographs section — not an
// empty one. Mounting it is what executes that branch.
const FILED_TOOLBOX = {
  id: 'lb2', _id: 'lb2', project_id: 'p1', log_type: 'toolbox_talk',
  date: '2026-08-25', status: 'submitted', is_locked: true,
  cp_name: 'Smoke CP', cp_signature: { ink: 'AAAA', affirmed: true },
  updated_at: '2026-08-25T22:10:00Z',
  data: { topic: 'Ladder safety', location: 'Level 3', attendees_count: 12 },
};
// The gate tablet. AuthContext reads site_mode/project_id/project_name off
// /api/auth/me to set siteMode + siteProject; a user without them makes every
// /site/* screen router.replace() away before it renders anything.
const SITE_USER = { ...USER, id: 'sd1', email: 'site@test.local', full_name: 'Gate Tablet', name: 'Gate Tablet', role: 'site_device', site_mode: true, project_id: 'p1', project_name: 'Smoke Site', project: PROJECT };
// A /site/* route only reaches its own screen as a site device.
const siteRoute = (r) => r === '/site' || r.startsWith('/site/');

// Every API call resolves to a benign shape. The point is mounting, not data.
// Served over real HTTPS from the hostname the bundle was built against, so
// the browser performs real CORS against it — see the block above.
function apiHandler(req, res) {
  const url = req.url || '/';
  const origin = req.headers.origin || '*';
  const cors = { 'Access-Control-Allow-Origin': origin, 'Vary': 'Origin', 'Content-Type': 'application/json' };
  const me = current.me || USER;
  const filed = current.filed;
  if (req.method === 'OPTIONS') {
    seen.preflights += 1;
    const asked = (req.headers['access-control-request-headers'] || '')
      .split(',').map((h) => h.trim().toLowerCase()).filter(Boolean);
    const refused = asked.filter((h) => !ALLOW_SET.has(h));
    if (refused.length) {
      // EXACTLY WHAT STARLETTE SENDS: 400, and no Access-Control-Allow-Headers.
      // Chrome then blocks the real request and logs a CORS error, which this
      // job already treats as a mount failure.
      refused.forEach((h) => { if (!seen.refused.includes(h)) seen.refused.push(h); });
      res.writeHead(400, { 'Access-Control-Allow-Origin': origin, 'Content-Type': 'text/plain' });
      return res.end('Disallowed CORS headers');
    }
    res.writeHead(204, {
      ...cors,
      'Access-Control-Allow-Headers': ALLOW_HEADERS.join(', '),
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
      'Access-Control-Max-Age': '600',
    });
    return res.end();
  }
  let body = {};
  if (url.includes('/api/auth/me')) body = me;
  else if (url.includes('feature-flags')) body = { flags: {} };
  else if (url.includes('dob-summary')) body = { by_project: {}, totals: {} };
  // BEFORE the generic /api/projects match below, which would otherwise
  // swallow this literal path and hand back an ARRAY — the screen reads
  // `.items` off it, gets undefined, and renders "Nothing pending deletion".
  // That mounts green while executing none of the retention branches.
  else if (url.includes('/api/projects/pending-deletion')) body = PENDING_DELETION;
  else if (url.match(/\/api\/projects\/p1(\?|$)/)) body = PROJECT;
  else if (url.match(/\/api\/projects(\?|\/|$)/)) body = [PROJECT];
  else if (url.match(/\/api\/workers\/w1(\?|$)/)) body = WORKER;
  else if (url.match(/\/api\/workers(\?|$)/)) body = [WORKER];
  // THE FILED READS, BEFORE the generic /logbooks match below — which would
  // otherwise swallow them and hand back [], mounting the UNFILED branch and
  // reporting green while executing none of the filed view.
  else if (/\/api\/logbooks\/lb2(\?|$)/.test(url)) body = FILED_TOOLBOX;
  else if (/\/api\/logbooks\/lb[0-9]+(\?|$)/.test(url)) body = FILED_DAILY;
  else if (filed && /\/api\/logbooks\/project\//.test(url)) {
    body = filed === 'toolbox_talk' ? [FILED_TOOLBOX] : [FILED_DAILY];
  }
  else if (/\/(logbooks|checkins|nfc|site-devices|documents|reports|notifications|annotations|admins|companies)/.test(url)) body = [];
  res.writeHead(200, cors);
  res.end(JSON.stringify(body));
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

  // The API, as a real origin on the real hostname. --host-resolver-rules
  // points Chromium's DNS at it; --ignore-certificate-errors accepts the
  // throwaway cert. Nothing is intercepted, so the browser preflights for real.
  const tls = selfSignedCert();
  const apiServer = https.createServer({ key: tls.key, cert: tls.cert }, apiHandler);
  await new Promise((r) => apiServer.listen(API_PORT, '127.0.0.1', r));

  const launch = {
    headless: true,
    args: [
      '--no-sandbox',
      `--host-resolver-rules=MAP ${API_HOST} 127.0.0.1:${API_PORT}`,
      '--ignore-certificate-errors',
    ],
  };
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
      // The route says whether this mount is of a FILED log; the stub answers
      // the by-project read accordingly. Without it every logbook route mounts
      // an empty editable day and the filed view is never executed.
      current.filed = (route.match(/[?&]filed=([a-z_]+)/) || [])[1] || null;
      current.me = me;
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
  apiServer.close();

  console.log(`\n${checked - failures.length}/${checked} route-mounts clean`);
  console.log(`preflights answered from server.py allow_headers: ${seen.preflights}`
    + ` [${ALLOW_HEADERS.join(', ')}]`);
  if (seen.refused.length) console.log(`refused, as the server would: ${seen.refused.join(', ')}`);
  if (!seen.preflights) {
    console.log('\n\u2717 NOT ONE PREFLIGHT was intercepted, so the CORS half of'
      + ' this job proved nothing this run. Either the client stopped sending a'
      + ' non-safelisted header, or route interception stopped surfacing OPTIONS.'
      + ' Do not widen the stub to make this pass.');
    process.exit(1);
  }
  if (failures.length) {
    console.log(`\n${failures.length} FAILED:`);
    failures.forEach((f) => console.log(`  [${f.theme}] ${f.route}`));
    process.exit(1);
  }
})().catch((e) => { console.error(e); process.exit(2); });
