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
// NOT null. `null` came back from the Expo config pipeline as `{}`, which is
// TRUTHY, rendered as a React child, and crashed /settings — React error #31,
// caught by the mount smoke. An empty string is falsy and stays a string.
ok(appJson.expo.extra.jsCommit === '',
  'the slot is an empty STRING until a build injects one — never null, never a literal');
ok(/typeof _rawCommit === 'string'/.test(code),
  'and the reader accepts only a non-empty string, whatever the pipeline hands back');
ok(!/extra\?\.jsCommit \|\| null/.test(code),
  'the unguarded `|| null` that let an object through is gone');

console.log('\n-- The slot is actually FILLED at publish time --');

// DEVICE ROUND 4, finding 5. The card printed "Bundle commit not injected at
// build time" on every bundle ever published, because nothing wrote the slot.
// A card that exists to make a device test unambiguous could not answer the one
// question it was built for — the round-4 report spent a finding saying so.
//
// EXECUTED against a stubbed environment, because the whole failure was a
// config that was never wired: asserting the file's TEXT would have passed just
// as happily on a file Expo never calls.
const CONFIG = path.join(FRONTEND, 'app.config.js');
ok(fs.existsSync(CONFIG), 'app.config.js exists — app.json alone cannot compute a value');
const base = { ...appJson.expo };

const withEnv = (env) => {
  const keys = ['EAS_BUILD_GIT_COMMIT_HASH', 'JS_COMMIT', 'EXPO_PUBLIC_JS_COMMIT'];
  const saved = {};
  keys.forEach((k) => { saved[k] = process.env[k]; delete process.env[k]; });
  Object.entries(env).forEach(([k, v]) => { process.env[k] = v; });
  try {
    delete require.cache[require.resolve(CONFIG)];
    // eslint-disable-next-line global-require, import/no-dynamic-require
    return require(CONFIG)({ config: base });
  } finally {
    keys.forEach((k) => {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    });
  }
};

ok(withEnv({ JS_COMMIT: 'abc1234def5678' }).extra.jsCommit === 'abc1234def5678',
  'JS_COMMIT (the OTA workflow path) reaches extra.jsCommit');
ok(withEnv({ EAS_BUILD_GIT_COMMIT_HASH: 'eas9999' }).extra.jsCommit === 'eas9999',
  "EAS Build's own variable reaches it too — a native binary is identifiable as well");
ok(withEnv({ EAS_BUILD_GIT_COMMIT_HASH: 'fromEas', JS_COMMIT: 'fromCi' })
  .extra.jsCommit === 'fromEas',
  'EAS Build wins when both are set — it is the process actually producing the artifact');
// The honest default. A missing value must stay a falsy STRING, never null:
// `null` came back from the config pipeline as `{}`, which is truthy, and
// crashed /settings with React error #31.
const none = withEnv({});
ok(none.extra.jsCommit === '', 'with NO environment value the slot stays an empty string');
ok(typeof none.extra.jsCommit === 'string', 'and is still a string, never null or {}');
// COMMENTS STRIPPED: app.config.js explains in prose why it does NOT shell out
// to `git rev-parse`, and matching raw source made the file fail an assertion
// about its own explanation.
ok(!/rev-parse|execSync|child_process/.test(
  fs.readFileSync(CONFIG, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')),
  'it never reads the local git tree — a dirty checkout must not claim a clean commit');
// Everything else must survive the spread, or injecting a commit silently drops
// the EAS project id, the plugins, or the runtimeVersion policy.
ok(withEnv({ JS_COMMIT: 'x' }).extra.eas.projectId === appJson.expo.extra.eas.projectId,
  'the EAS project id survives the merge');
ok(JSON.stringify(withEnv({ JS_COMMIT: 'x' }).runtimeVersion)
   === JSON.stringify(appJson.expo.runtimeVersion),
  'and so does the runtimeVersion policy — an OTA must not change channel over this');

// The workflow has to SET it, and has to re-run when the injection changes.
const ota = fs.readFileSync(
  path.join(FRONTEND, '..', '.github', 'workflows', 'ota-update.yml'), 'utf8');
ok(/JS_COMMIT: \$\{\{ github\.sha \}\}/.test(ota),
  'the publish step exports the commit being published');
ok(/- 'frontend\/app\.config\.js'/.test(ota),
  'and a change to app.config.js triggers a publish — otherwise the fix sits on main unshipped');

// AND IT CAN BE PUBLISHED BY HAND. The path filter above does not match
// .github/**, so a fix to the publish pipeline itself cannot trigger the
// pipeline. Without a button the only recoveries are a no-op commit or a
// laptop publishing outside CI.
ok(/^  workflow_dispatch:/m.test(ota),
  'the publish can be invoked manually — a pipeline that only fires on a '
  + 'qualifying commit cannot recover from its own failure');

// The button has to WORK, which is a separate fact. github.event.head_commit
// is populated on push and empty on dispatch, and eas rejects an empty
// --message as a missing flag. The first manual dispatch died exactly here.
ok(/if \[ -z "\$MSG" \]; then/.test(ota),
  'and the publish step falls back when COMMIT_MSG is empty, which is every '
  + 'workflow_dispatch run');
ok(/git log -1 --pretty=%s/.test(ota),
  'to the checked-out commit subject — the same string a push supplies, so '
  + 'a dispatched publish is labelled identically to an automatic one');
ok(/\[ -n "\$MSG" \]/.test(ota),
  'with a final guard so nothing reaches eas with an empty message');

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
