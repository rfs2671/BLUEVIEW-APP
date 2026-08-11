/**
 * The BUILD card in settings.
 *
 * WHY IT EXISTS. A device test reported Step 1 as missing its equipment and
 * weather sections. Both were on main and had never been reverted — the phone
 * was running an older JS bundle than the backend. The defect did not exist
 * and the time spent finding that out was the real cost.
 *
 * The card shows the two identities TOGETHER, because the bundle alone does
 * not tell you whether it matches the server.
 *
 * Run:  node src/utils/buildIdentity.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const settings = fs.readFileSync(path.join(FRONTEND, 'app', 'settings.jsx'), 'utf8');
const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
const appJson = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8'));

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const code = settings
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');

console.log('\n-- Both identities, on one card --');

ok(/const response = await apiClient\.get\('\/api\/version'\)/.test(api),
  'the client can read the backend commit at all');
ok(/versionAPI/.test(code), 'settings consumes it');
ok(/Constants\.expoConfig\?\.extra\?\.jsCommit/.test(code),
  'and reads the JS-side commit from the build config');
ok(/Updates\.updateId/.test(code),
  'falling back to the OTA update id, which is what identifies a bundle today');
ok(/Updates\.createdAt/.test(code),
  'plus when that bundle was built — the only comparable value when no commit is injected');

// A slot EAS can fill. Present and null: the app must not claim a commit it
// was not given.
ok(Object.prototype.hasOwnProperty.call(appJson.expo.extra, 'jsCommit'),
  'app.json carries the jsCommit slot');
ok(appJson.expo.extra.jsCommit === null,
  'and it is null until a build injects one — never a stale literal');

console.log('\n-- It never claims a match it cannot make --');

ok(/Boolean\(jsCommit && backendCommit\)/.test(code),
  'a verdict of "same commit" requires BOTH commits to exist');
ok(/MISMATCH/.test(code), 'and a mismatch is stated in those words');
ok(/not injected at build time/.test(code),
  'with no injected commit it says so, rather than implying a comparison');
ok(!/buildMatches = true/.test(code), 'nothing hard-codes a pass');

console.log('\n-- Reachable, readable, copyable --');

ok(/sectionLabel}>BUILD</.test(settings), 'it is a labelled section in settings');
ok(/Clipboard\.setStringAsync/.test(code), 'tappable to copy');
ok(/minHeight: touchTarget\.min/.test(settings.slice(settings.indexOf('buildRow:'))),
  'the copy row carries the app-wide 56pt minimum');
ok(!/#[0-9a-fA-F]{6}/.test(settings.slice(settings.indexOf('buildRow:'),
  settings.indexOf('buildCopyText:'))),
  'and no colour literals — tokens only');

// It must NOT be on a compliance screen.
for (const screen of ['daily_jobsite.jsx', 'preshift_signin.jsx']) {
  const p = path.join(FRONTEND, 'app', 'logbooks', screen);
  const src = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
  ok(!/jsCommit|versionAPI/.test(src),
    `the build card stays out of ${screen}`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
