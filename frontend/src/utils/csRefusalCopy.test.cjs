/**
 * THE REFUSAL SAYS WHO MAY FILE, AND IT SAYS HIS NAME.
 *
 * THE DEFECT. `_refuse_if_not_the_superintendent` (backend/server.py) raises a
 * 403 that was written to be read by a man on a jobsite:
 *
 *     code             NOT_THE_REGISTERED_SUPERINTENDENT
 *     message          "This is the construction superintendent's own log
 *                       under BC 3301.13.13. Michael Cespedes is registered
 *                       on this project and is the person who signs it."
 *     registered_name  "Michael Cespedes"
 *
 * NONE OF IT REACHED HIM. site_superintendent_log.jsx routes every 4xx through
 * gateCopy, which looks up `code_${code}` in the `finalize` namespace and falls
 * back to genericError for a code it does not know — and this code had no
 * entry. So the sentence he actually read was:
 *
 *     "That could not be recorded just now. Your entry is kept — try again."
 *
 * A retry instruction for a refusal that will never succeed, with no name and
 * no remedy, delivered at the end of the day on a log BC 3301.13.13 requires
 * completed before he leaves the site. Measured on 588 Thomas S Boyland Street:
 * 9 accounts see the tile, 8 of them get this.
 *
 * ── WHY TWO KEYS AND NOT ONE INTERPOLATED SENTENCE ──────────────────────────
 *
 * The name comes off the ERROR DETAIL, which exists only where the response
 * does. LogbookLockBar renders the SAME namespace from a code STORED by
 * recordFinalizeError — code only, no detail — so a single `{name}` sentence
 * would paint a literal "{name}" onto that banner. The base key is therefore
 * nameless and safe for every renderer; `_NAMED` carries the placeholder and is
 * reachable only from a call site holding the detail. That is asserted below,
 * because it is the half a future edit would undo without noticing.
 *
 *   node frontend/src/utils/csRefusalCopy.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

function loadModule(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}

const en = loadModule('src/i18n/en.js').default;
const es = loadModule('src/i18n/es.js').default;
const F = en.finalize;

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

const CODE = 'NOT_THE_REGISTERED_SUPERINTENDENT';
const NAME = 'Michael Cespedes';
/** The 403 body FastAPI renders for the raise at server.py. Verbatim shape. */
const DETAIL = {
  code: CODE,
  message: `This is the construction superintendent's own log under BC 3301.13.13. ${NAME} is registered on this project and is the person who signs it.`,
  registered_name: NAME,
};

/**
 * The translator the screen holds: useT('finalize'), which returns the KEY on a
 * miss. Reproduced rather than imported because useT is a hook.
 */
const t = (key) => (Object.prototype.hasOwnProperty.call(F, key) ? F[key] : key);

/**
 * gateCopy as it shipped — code in, sentence out, no detail. Kept here as the
 * CONTROL: it is what LogbookLockBar still runs, so anything this returns must
 * be safe to paint on a banner.
 */
function shippedGateCopy(code) {
  if (!code) return F.genericError;
  const key = `code_${code}`;
  const copy = F[key];
  return copy && copy !== key ? copy : F.genericError;
}

// ── THE MODULE UNDER TEST ───────────────────────────────────────────────────
// Loaded defensively: a missing file must report as failures rather than kill
// the run before a single proposition is stated.
let M = {};
let loadError = null;
try {
  M = loadModule('src/utils/csRefusalCopy.js');
} catch (e) {
  loadError = e;
}

console.log('\n0. THE MODULE EXISTS');
{
  ok(!loadError, `src/utils/csRefusalCopy.js loads${loadError ? ` (${loadError.message})` : ''}`);
  ok(typeof M.refusalCopy === 'function', 'and exports refusalCopy(code, detail, t)');
}
const refusalCopy = typeof M.refusalCopy === 'function'
  ? M.refusalCopy
  : () => '<<no module>>';

console.log('\n1. THE CODE RESOLVES TO COPY, NOT TO "TRY AGAIN"');
{
  ok(typeof F[`code_${CODE}`] === 'string' && F[`code_${CODE}`].length > 0,
    `the finalize namespace declares code_${CODE}`);
  ok(shippedGateCopy(CODE) !== F.genericError,
    'and the SHIPPED gateCopy no longer falls through to genericError — this '
    + 'is the exact fall-through the superintendent met');
  ok(!/try again/i.test(String(F[`code_${CODE}`] || '')),
    'the copy does NOT tell him to try again. The refusal is a judgement about '
    + 'who he is; a retry cannot change it');
}

console.log('\n2. IT NAMES THE MAN WHO MAY FILE');
{
  const copy = refusalCopy(CODE, DETAIL, t);
  ok(copy.includes(NAME),
    "the server sent registered_name and the sentence he reads contains it. A "
    + 'nameless refusal leaves him with nothing to do');
  ok(/3301\.13\.13/.test(copy),
    'and cites the section, so the refusal reads as the law rather than as the '
    + 'app being difficult');
  ok(!/\{name\}/.test(copy), 'with the placeholder actually substituted');
  ok(!/try again/i.test(copy), 'and still no retry instruction');
}

console.log('\n3. NO NAME, NO PLACEHOLDER — AND STILL NOT THE GENERIC');
{
  // registered_name is `reg.get("full_name")`, which a registration row may
  // legitimately lack. The branch has to exist before it is met.
  for (const [what, detail] of [
    ['a detail with no registered_name', { code: CODE }],
    ['a null name', { code: CODE, registered_name: null }],
    ['a blank name', { code: CODE, registered_name: '   ' }],
    ['no detail at all', undefined],
  ]) {
    const copy = refusalCopy(CODE, detail, t);
    ok(!/\{name\}/.test(copy), `${what}: no literal "{name}" reaches the screen`);
    ok(copy !== F.genericError, `${what}: and it is not "try again" either`);
    ok(/3301\.13\.13/.test(copy), `${what}: the section is still cited`);
  }
}

console.log('\n4. THE BASE KEY IS SAFE ON A BANNER THAT HAS NO DETAIL');
{
  // LogbookLockBar reads a code recorded by recordFinalizeError — code only.
  // Its gateCopy is `shippedGateCopy` above and is deliberately NOT changed by
  // this PR, so whatever the base key holds is what it paints.
  ok(!/\{name\}/.test(String(F[`code_${CODE}`] || '')),
    'the base key carries no placeholder, so the lock bar cannot paint "{name}"');
  ok(!/\{[a-z_]+\}/i.test(shippedGateCopy(CODE)),
    'and neither can any other slot sneak into it');
}

console.log('\n5. THE NAMED VARIANT IS A SEPARATE KEY');
{
  const named = F[`code_${CODE}_NAMED`];
  ok(typeof named === 'string' && named.length > 0,
    `code_${CODE}_NAMED exists`);
  ok(/\{name\}/.test(String(named || '')),
    'and it is the one that carries the {name} slot');
  ok(String(named || '') !== String(F[`code_${CODE}`] || ''),
    'the two sentences differ — otherwise the split buys nothing');
}

console.log('\n6. EVERY OTHER CODE IS UNTOUCHED');
{
  // The resolver replaces gateCopy on this screen. It must agree with the
  // shipped one everywhere the name is not involved, or this PR quietly
  // rewords ten other refusals.
  const codes = Object.keys(F)
    .filter((k) => k.startsWith('code_'))
    .map((k) => k.slice('code_'.length))
    .filter((c) => !c.startsWith(CODE));
  ok(codes.length > 5, `there are ${codes.length} other codes to check against`);
  const drifted = codes.filter((c) => refusalCopy(c, DETAIL, t) !== shippedGateCopy(c));
  ok(drifted.length === 0,
    `none of them changes wording: ${drifted.join(', ') || 'clean'}`);
  ok(refusalCopy(null, undefined, t) === F.genericError,
    'and a missing code is still the generic message');
  ok(refusalCopy('INVENTED_CODE_NOBODY_SHIPS', undefined, t) === F.genericError,
    'as is an unmapped one — the fallback rule is unchanged');
}

console.log('\n7. THE SCREEN ACTUALLY HANDS OVER THE DETAIL');
{
  // Source text with comments stripped: this screen explains itself at length
  // in prose, and a bare search would match the explanation. Same technique as
  // csFilingGuard.test.cjs.
  const raw = fs.readFileSync(
    path.join(FRONTEND, 'app', 'logbooks', 'site_superintendent_log.jsx'), 'utf8',
  ).split('\r\n').join('\n');
  const SRC = raw
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');

  ok(/from '[^']*csRefusalCopy'/.test(SRC),
    'the screen imports the shared resolver rather than growing a second copy '
    + 'of the rule');
  ok(/gateCopy\s*=\s*useCallback\(\(code,\s*detail\)/.test(SRC),
    'its gateCopy takes the detail, not just the code');
  ok(/gateCopy\(code,\s*detail\)/.test(SRC),
    'and the submit-refusal path passes the detail it already read off the '
    + 'response — the one place the name exists');
}

console.log('\n8. THE SERVER STILL SENDS WHAT THE COPY INTERPOLATES');
{
  const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
  ok(server.includes(`"code": "${CODE}"`),
    'the server still raises this code');
  ok(server.includes('"registered_name": reg.get("full_name")'),
    'and still sends registered_name — the field {name} is filled from. If '
    + 'this line moves, the named sentence silently degrades to the nameless '
    + 'one and nobody is told');
}

console.log('\n9. EN-ONLY, BY THE RULE THE CATALOGUE ALREADY STATES');
{
  // i18n.test.cjs lists `finalize` in EN_ONLY_NAMESPACES and asserts it is
  // ABSENT from es.js; es.js's own header says why — a logbook is a legal
  // record filed with the DOB and read in English, and Spanish belongs where a
  // WORKER signs. draftSync.js:79 repeats the rule for these very codes. A
  // Spanish entry here would FAIL that test, so this pins the choice rather
  // than leaving the gap looking like an oversight.
  ok(es.finalize === undefined,
    'es.js still declares no finalize namespace — unchanged by this PR');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
