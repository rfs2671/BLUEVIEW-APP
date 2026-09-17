#!/usr/bin/env node
/**
 * POST-DEPLOY GATE FOR THE WEB BUILD — the only check that would have caught
 * the CORS outage IN PRODUCTION rather than in a test.
 *
 * WHY IT EXISTS. On 2026-08-28 the web build began sending X-Client-Version on
 * every request; the API's allow_headers did not name it, so Chrome refused to
 * send any request at all and nobody could sign in. It ran for at least six
 * days and twenty-two hours behind four green signals:
 *
 *   * the backend suite — no test issued a preflight;
 *   * /api/version — 200 by curl, because curl sends no Origin;
 *   * postdeploy_login_check.py — sends the header, but over urllib: no
 *     Origin, no OPTIONS;
 *   * the mount smoke — Playwright route interception SHORT-CIRCUITS the
 *     preflight, so the browser never issues one.
 *
 * Every one of those is a check that cannot see a browser refusing to make a
 * request. This one is a real browser, on the real origin, against the real
 * API, after the real deploy.
 *
 * TWO HALVES, BOTH MANDATORY.
 *
 *   1. PROVENANCE — poll https://<site>/version.json until it reports the SHA
 *      that was pushed. Without this the check runs against whatever build is
 *      still live, which is exactly the state that hid a 33-commit deployment
 *      gap for three days.
 *   2. THE LIVE BUNDLE ACTUALLY TALKS TO THE LIVE API — load the site in
 *      Chromium and watch everything the shipped bundle sends, which cannot
 *      drift from the client the way a hand-built request would. Then issue
 *      ONE request of our own, with the header list spelled out, because
 *      watching alone has a floor of zero (see below).
 *
 * AND A COUNT, BECAUSE A CHECK THAT CAN BE SATISFIED WITHOUT RUNNING MUST
 * COUNT ITS OWN EXECUTIONS AND FAIL AT ZERO. A page that made no cross-origin
 * request at all would sail through "no CORS errors" while proving nothing —
 * which is precisely how the mount smoke passed for a week. At least one
 * request to the API must have SUCCEEDED, or this fails.
 *
 * THE HOST. This is app.levelog.com, the Expo web build. www.levelog.com is
 * the marketing site, a different project with its own SPA fallback: it
 * answers /version.json with index.html and never calls the API. This gate
 * spent its entire life pointed there and failed 20 runs out of 20 without
 * once describing the app — the site was healthy throughout. A gate naming the
 * wrong host is not a red build, it is no gate at all.
 *
 * USAGE
 *   SITE=https://app.levelog.com API=https://api.levelog.com \
 *   [EXPECT_SHA=<sha>] node scripts/postdeploy-web-check.cjs
 *
 * Exits 0 if every assertion holds, 1 otherwise.
 */
const SITE = (process.env.SITE || 'https://app.levelog.com').replace(/\/$/, '');
const API = (process.env.API || 'https://api.levelog.com').replace(/\/$/, '');
const EXPECT_SHA = (process.env.EXPECT_SHA || '').trim();
const POLL_SECONDS = Number(process.env.POLL_SECONDS || 600);
const POLL_EVERY_MS = Number(process.env.POLL_EVERY_MS || 15000);

// ── the part worth testing ─────────────────────────────────────────────────
// Kept pure so the gate's own logic is tested rather than trusted; the network
// and browser shell below is the only untested part, and it only observes.
function evaluate({ deployedSha, expectSha, corsErrors, apiOk, apiFailed, probeRefused }) {
  const out = [];

  if (!deployedSha) {
    out.push(
      'version.json reported no commit — the site is serving a build that '
      + 'predates the stamp, or the build ran without VERCEL_GIT_COMMIT_SHA. '
      + 'Nothing below can be attributed to a commit.',
    );
  } else if (expectSha && !shaMatches(deployedSha, expectSha)) {
    out.push(
      `version.json reports ${deployedSha.slice(0, 7)} but ${expectSha.slice(0, 7)} `
      + 'was pushed — the deploy has not landed, so this ran against the old build',
    );
  }

  if (corsErrors.length) {
    out.push(
      `the live site was blocked by CORS on ${corsErrors.length} request(s): `
      + `${corsErrors.slice(0, 3).join(' | ')}`,
    );
  }

  // THE PROBE'S OWN VERDICT, kept separate from the counter below. The
  // browser's error text ("Failed to fetch") is thin, so this says which of
  // the two questions failed: was the request refused, or never made at all.
  if (probeRefused) {
    out.push(
      `the preflighted probe to ${API} was refused by the browser: `
      + `${probeRefused}. The deployed build cannot reach its own API from `
      + 'its own origin -- this is the 2026-08-28 outage, live.',
    );
  }

  // THE VACUITY GUARD. "no CORS errors" is free if nothing was requested.
  // Since the probe issues a request unconditionally, reaching here with a
  // zero count no longer means "the app happened not to call the API" -- it
  // means the probe itself did not complete either.
  if (!apiOk) {
    out.push(
      `NOT ONE request to ${API} completed, so nothing here was actually `
      + `exercised -- not even the probe this check issues itself (${apiFailed} `
      + 'failed). Do not relax this to make it pass.',
    );
  }

  return out;
}

function shaMatches(deployed, expected) {
  const a = String(deployed).toLowerCase();
  const b = String(expected).toLowerCase();
  return a.startsWith(b) || b.startsWith(a);
}

// A console line that means the browser refused to make the request, as
// opposed to the server answering it badly. These are the words Chromium uses.
function isCorsFailure(text) {
  const t = String(text || '');
  return /blocked by CORS policy/i.test(t)
    || /Response to preflight request/i.test(t)
    || /has been blocked by CORS/i.test(t);
}

module.exports = { evaluate, shaMatches, isCorsFailure };

// ── the network + browser shell ────────────────────────────────────────────
if (require.main === module) main();

async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function waitForDeploy() {
  const deadline = Date.now() + POLL_SECONDS * 1000;
  let last = null;
  for (;;) {
    try {
      const body = await fetchJson(`${SITE}/version.json`);
      last = body.commit || '';
      if (!EXPECT_SHA || shaMatches(last, EXPECT_SHA)) return last;
      console.log(`  waiting: live=${(last || 'none').slice(0, 7)} want=${EXPECT_SHA.slice(0, 7)}`);
    } catch (e) {
      console.log(`  waiting: ${e.message}`);
    }
    if (Date.now() > deadline) return last;
    await new Promise((r) => setTimeout(r, POLL_EVERY_MS));
  }
}

async function main() {
  console.log(`post-deploy web check\n  site ${SITE}\n  api  ${API}`);
  const deployedSha = await waitForDeploy();
  console.log(`  live build: ${(deployedSha || 'unknown').slice(0, 7)}`);

  let chromium;
  try {
    ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
  } catch {
    console.error('✗ playwright-core not resolvable. Install it, or set PW_CORE.');
    process.exit(1);
  }

  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);
  const page = await browser.newPage();

  const corsErrors = [];
  let apiOk = 0;
  let apiFailed = 0;
  let probeRefused = null;

  page.on('console', (m) => {
    if (m.type() === 'error' && isCorsFailure(m.text())) {
      corsErrors.push(m.text().slice(0, 200));
    }
  });
  page.on('requestfailed', (r) => {
    if (r.url().startsWith(API)) apiFailed += 1;
  });
  page.on('response', (r) => {
    // A completed cross-origin response IS a preflight that passed, for any
    // request carrying a non-safelisted header — which every call from this
    // client does (Authorization, X-Client-Version, X-Request-Id).
    if (r.url().startsWith(API) && r.status() < 500) apiOk += 1;
  });

  // /login is deliberate: it is the route the outage was reported on and it
  // needs no session. It is NOT relied on to call the API -- see the probe.
  for (const route of ['/login', '/']) {
    try {
      await page.goto(`${SITE}${route}`, { waitUntil: 'networkidle', timeout: 45000 });
      await page.waitForTimeout(2500);
    } catch (e) {
      console.log(`  navigation ${route}: ${e.message.split('\n')[0]}`);
    }
  }

  // THE PROBE, AND WHY THE ROUTES ABOVE ARE NOT ENOUGH.
  //
  // This gate asserted "some request to the API completed" and left it to the
  // app to make one. On 2026-09-17 the login screen made ZERO calls to the API
  // on mount -- it polls its own origin with HEAD for reachability -- so the
  // assertion was unsatisfiable by the very route chosen to satisfy it. A gate
  // whose subject is incidental behaviour of a page measures whatever that
  // page happens to do this month.
  //
  // So issue the request here: from the loaded page, in the real browser, at
  // the real origin. X-Client-Version is the header whose absence from
  // allow_headers caused the outage, and sending it forces the preflight that
  // is the whole subject of this check. /api/version needs no session, so a
  // refusal here is CORS and nothing else.
  try {
    const probe = await page.evaluate(async (api) => {
      try {
        const r = await fetch(`${api}/api/version`, {
          cache: 'no-store',
          headers: {
            'X-Client-Version': 'postdeploy-web-check',
            'X-Request-Id': 'postdeploy-probe',
          },
        });
        // Reading the body is part of the proof: the browser only hands it
        // over when the preflight passed AND the origin was allowed.
        await r.text();
        return { ok: true, status: r.status };
      } catch (e) {
        return { ok: false, error: String((e && e.message) || e) };
      }
    }, API);
    console.log(`  preflighted probe: ${probe.ok ? `completed ${probe.status}` : `REFUSED (${probe.error})`}`);
    if (!probe.ok) probeRefused = probe.error;
  } catch (e) {
    probeRefused = `probe could not run: ${e.message.split('\n')[0]}`;
    console.log(`  ${probeRefused}`);
  }

  await browser.close();

  console.log(`  api responses ok: ${apiOk}   failed: ${apiFailed}   cors errors: ${corsErrors.length}`);

  const failures = evaluate({
    deployedSha, expectSha: EXPECT_SHA, corsErrors, apiOk: apiOk > 0, apiFailed,
    probeRefused,
  });
  if (failures.length) {
    console.log('\n✗ POST-DEPLOY WEB CHECK FAILED');
    failures.forEach((f) => console.log(`  - ${f}`));
    process.exit(1);
  }
  console.log('\n✓ the deployed web build reaches the API from its own origin');
}
