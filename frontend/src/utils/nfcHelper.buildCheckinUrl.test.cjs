/**
 * Unit tests for CHECKIN_BASE_URL / buildCheckinUrl().
 *
 * THE REGRESSION THIS EXISTS TO CATCH does not throw, does not 404 and does
 * not log. The NFC tag encodes levelog.com; the API base is api.levelog.com;
 * vercel.json rewrites /checkin/* and /api/* from the first to the second, so
 * BOTH hosts serve a working gate and both API-resolve correctly. A QR built
 * off the API base would look right in every test you would think to write.
 *
 * What breaks is the ORIGIN. checkin.html keys the returning-worker skip on
 * localStorage (bv_worker_id / bv_worker_phone), which is per-origin, so a man
 * who enrolled by tapping on levelog.com and later scans a QR on
 * api.levelog.com re-does his OSHA card, his orientation and his signature at
 * the gate. Nothing anywhere reports it. So the assertion has to be made HERE,
 * on the host itself, since no downstream behaviour will make it for us.
 *
 * Same harness as RiskScoreCircle.bandFor.test.cjs and tokens.test.cjs: this
 * repo has no JS test runner, and nfcHelper.js cannot be imported under bare
 * node because it pulls in react-native and react-native-nfc-manager at module
 * top. So the REAL source is read, the two shipped declarations are extracted
 * verbatim and evaluated. Nothing here is a hand-copy of a value.
 *
 * Run:  node src/utils/nfcHelper.buildCheckinUrl.test.cjs
 */

const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, 'nfcHelper.js'), 'utf8');

const constMatch = src.match(/^export const CHECKIN_BASE_URL = .*;$/m);
if (!constMatch) throw new Error('CHECKIN_BASE_URL declaration not found in source');

const fnStart = src.indexOf('export function buildCheckinUrl(');
if (fnStart < 0) throw new Error('buildCheckinUrl declaration not found in source');
const fnEnd = src.indexOf('\n}', fnStart);
if (fnEnd < 0) throw new Error('buildCheckinUrl closing brace not found');
const fnSrc = src.slice(fnStart, fnEnd + 2);

// eslint-disable-next-line no-new-func
const { CHECKIN_BASE_URL, buildCheckinUrl } = new Function(
  `${constMatch[0].replace('export const', 'const')}
   ${fnSrc.replace('export function', 'function')}
   return { CHECKIN_BASE_URL, buildCheckinUrl };`,
)();

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The host itself ──────────────────────────────────────────────────────────
ok(CHECKIN_BASE_URL === 'https://levelog.com', 'gate host is the TAG host, levelog.com');
ok(
  !/api\.levelog\.com/.test(CHECKIN_BASE_URL),
  'gate host is NOT the API base (the silent-drift regression)',
);

// ── The tap and the scan must name the same host and the same gate ───────────
const tapped = buildCheckinUrl('proj1', 'tag1');
const scanned = buildCheckinUrl('proj1', 'tag1', { method: 'qr' });

ok(tapped === 'https://levelog.com/checkin/proj1/tag1', 'NFC URL shape is unchanged');
ok(
  scanned.split('?')[0] === tapped,
  'the QR and the tag resolve to the SAME gate URL, differing only by the marker',
);
ok(scanned === 'https://levelog.com/checkin/proj1/tag1?m=qr', 'QR carries the ?m=qr marker');

// ── The marker is opt-in, so tags already in the field keep reading as NFC ───
ok(!/[?&]m=/.test(tapped), 'the NFC URL carries NO marker — absent must keep meaning tapped');
ok(!/[?&]m=/.test(buildCheckinUrl('p', 't', {})), 'an empty options object adds no marker');
ok(
  !/[?&]m=/.test(buildCheckinUrl('p', 't', { method: 'nfc' })),
  'an explicit nfc method adds no marker',
);

// ── The path shape the gate parses ───────────────────────────────────────────
// checkin.html reads path segments after "checkin": [project_id, tag_id]. The
// ?m= marker must never land where that parse can see it.
const parts = new URL(scanned).pathname.split('/').filter(Boolean);
const at = parts.indexOf('checkin');
ok(at === 0 && parts.length === 3, 'path is /checkin/{project_id}/{tag_id} with nothing extra');
ok(parts[1] === 'proj1' && parts[2] === 'tag1', 'the marker does not leak into the path segments');

// ── The baseUrl override, which is what the NFC writers pass through ─────────
ok(
  buildCheckinUrl('p', 't', { baseUrl: 'https://staging.example.com' })
    === 'https://staging.example.com/checkin/p/t',
  'an explicit baseUrl overrides the default',
);
ok(
  buildCheckinUrl('p', 't', { baseUrl: undefined }) === 'https://levelog.com/checkin/p/t',
  'an undefined baseUrl falls back to the constant, never to "undefined"',
);

// ── The host is written in exactly one place ─────────────────────────────────
// Two literals is how the tag and the code drift apart in the first place.
const hostLiterals = (src.match(/'https:\/\/(?:www\.)?levelog\.com'/g) || []).length;
ok(hostLiterals === 1, `the gate host appears as a literal exactly once (got ${hostLiterals})`);

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
