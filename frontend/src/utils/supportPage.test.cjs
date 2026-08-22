/**
 * The support page is a compliance artefact with an uptime requirement.
 *
 * Apple checks the support URL during review AND at intervals afterwards. A
 * dead or broken support link is grounds for removal from the store, months
 * after approval, with no warning tied to a deploy anyone remembers making.
 *
 * So the two properties that matter are asserted here rather than assumed:
 *
 *   1. IT IS STATIC. No script, no framework, no fetch. levelog.com is a React
 *      Native Web SPA; a bundle error there takes down every in-app route at
 *      once. This page shares nothing with it and cannot be broken by a
 *      frontend deploy.
 *
 *   2. IT IS REACHABLE. The Vercel config ends in a catch-all that rewrites
 *      /:path* to /index.html — the SPA. A rewrite added AFTER that line is
 *      dead config, and /support would silently serve the app instead. Order
 *      is the whole thing.
 *
 *   node frontend/src/utils/supportPage.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const PAGE = fs.readFileSync(path.join(FRONTEND, 'public', 'support.html'), 'utf8');
const VERCEL = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'vercel.json'), 'utf8'));

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

console.log('\n-- it cannot be broken by a frontend deploy --');
{
  ok(!/<script/i.test(PAGE), 'no <script> tag anywhere');
  ok(!/fetch\(|XMLHttpRequest|onclick=/i.test(PAGE), 'nothing that runs or calls out');
  ok(!/src=["']https?:/i.test(PAGE), 'no remote assets — it renders with the network down');
  ok(/<style>/.test(PAGE), 'styling is inline, so there is no stylesheet to 404');
  ok(!/import |require\(/.test(PAGE), 'and it shares no code with the app');
}

console.log('\n-- it is actually reachable at /support --');
{
  const rw = VERCEL.rewrites;
  const support = rw.findIndex((r) => r.source === '/support');
  const catchAll = rw.findIndex((r) => r.source === '/:path*');
  ok(support > -1, 'a /support rewrite exists');
  ok(catchAll > -1, 'ANCHOR: the SPA catch-all is still there');
  // THE ORDERING RULE. Vercel evaluates in order; anything after the catch-all
  // never matches, so a correct-looking rewrite below it serves the SPA.
  ok(support < catchAll,
    `/support must come BEFORE the /:path* catch-all (found ${support} vs ${catchAll}) `
    + '— after it, the rewrite is dead config and Apple gets the app shell');
  ok(rw[support].destination === '/support.html', 'and it points at the static file');
}

console.log('\n-- Apple looks for these specifically --');
{
  // A support page with no way to contact support is the common rejection.
  ok(/mailto:support@levelog\.com/.test(PAGE), 'a working contact method');
  ok(/<title>/.test(PAGE) && /Support/.test(PAGE), 'it says what it is');
  ok(/viewport/.test(PAGE), 'it is legible on the phone a reviewer uses');

  // 5.1.1(v): the review team cross-checks that the deletion route described
  // in App Review Information matches what the app and the page say.
  ok(/Request account deletion/.test(PAGE),
    'the in-app deletion route is named, matching Settings');
  ok(/administrator/.test(PAGE),
    'and the created-account case says to ask an administrator');
  ok(/Department of Buildings/.test(PAGE),
    'with the retention reason stated — the same fact the app states');
}

console.log('\n-- it does not contradict the app --');
{
  // A support page claiming a permission the binary does not declare is a
  // worse problem than saying nothing: the two are read side by side.
  const APP = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8')).expo;
  const ip = APP.ios.infoPlist;
  ok(!ip.NSLocationWhenInUseUsageDescription && /does not use your location/.test(PAGE),
    'it says location is unused, and the binary agrees');
  ok(!ip.NSMicrophoneUsageDescription && /microphone/.test(PAGE),
    'same for the microphone');
  ok(!!ip.NSCameraUsageDescription && /Camera<\/strong>/.test(PAGE),
    'and the permissions it DOES claim are ones the binary declares');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
