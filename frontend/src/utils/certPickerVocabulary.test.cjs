/**
 * THE ADD-CERTIFICATION MENU IS THE BACKEND'S VOCABULARY, NOT A SECOND COPY.
 *
 * WHAT WAS WRONG. app/workers/[id].jsx built its own CERT_TYPES list with its
 * own hand-written labels:
 *
 *     { value: 'SST_FULL',       label: 'SST Full (62-hr)' }
 *     { value: 'SST_LIMITED',    label: 'SST Limited (10-hr)' }
 *     { value: 'SST_SUPERVISOR', label: 'SST Supervisor' }
 *     -- SST_TEMPORARY absent --
 *
 * Every SST line was wrong against the project's own constants:
 *
 *   SST_FULL is the 40-hour card. 62 is the SUPERVISOR's hours
 *            (backend/server.py, "THE HOURS EACH COLOUR'S CLASS CARRIES").
 *   SST_LIMITED was the 30-hour transitional card, dead since August 2020
 *            (server.py SST_DEAD_CLASSES). 10 is the TEMPORARY card's hours.
 *   SST_TEMPORARY is a member of SST_CLASS_TYPES (backend/lib/cert_vocab.py)
 *            and could not be chosen at all.
 *
 * And the labels disagreed with certLabel() -- the accessor THIS SAME SCREEN
 * uses to render the certs listed underneath the form. One screen, two names
 * for one class: 'SST Worker' in the list, 'SST Full (62-hr)' in the menu that
 * adds one.
 *
 * WHY IT MATTERS. There is no edit endpoint for a certification. Adding a
 * correct row and deleting the flagged one is the ONLY manual repair an admin
 * has for a worker stuck on CLASS_UNVERIFIED. That repair tool was the
 * mislabelled one -- and, worse, CERT_TYPES was never rendered at all, so
 * `newCertType` stayed at its 'OSHA_10' initial value and an SST row could not
 * be produced by any sequence of taps.
 *
 * HOW THIS FILE REFUSES THE NEXT COPY. It does not hold a list of its own.
 * SST_CLASS_TYPES is READ OUT OF backend/lib/cert_vocab.py, SST_DEAD_CLASSES
 * out of backend/server.py, and every label is compared against certLabel() --
 * the shipped renderer -- rather than against a second hardcoded table here.
 * A label typed into this test would be exactly the defect being fixed.
 *
 * Run:  node src/utils/certPickerVocabulary.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const REPO = path.join(FRONTEND, '..');
const SCREEN_PATH = path.join(FRONTEND, 'app', 'workers', '[id].jsx');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Comments stripped before any source assertion. This file's prose and the
 *  screen's both name the identifiers under test; a grep that matches the
 *  explanation instead of the code proves nothing. */
const strip = (text) => text
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const SCREEN_RAW = fs.readFileSync(SCREEN_PATH, 'utf8');
const SCREEN = strip(SCREEN_RAW);
ok(/CERT_TYPES/.test(SCREEN) && !/62 is the SUPERVISOR/.test(SCREEN),
  'the comment stripper removes prose but keeps code');

// ── THE CONSTANTS, READ FROM THE FILES THAT OWN THEM ────────────────────────

/** The members of a python `NAME = frozenset({...})` / `NAME = {...}` literal. */
function pySet(source, name) {
  const m = new RegExp(`${name}\\s*=\\s*(?:frozenset\\()?\\{([\\s\\S]*?)\\}`)
    .exec(source);
  if (!m) return null;
  return new Set([...m[1].matchAll(/"([A-Z_0-9]+)"/g)].map((x) => x[1]));
}

const CERT_VOCAB = fs.readFileSync(
  path.join(REPO, 'backend', 'lib', 'cert_vocab.py'), 'utf8');
const SERVER = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');

const BACKEND_CLASSES = pySet(CERT_VOCAB, 'SST_CLASS_TYPES');
const BACKEND_DEAD = pySet(SERVER, 'SST_DEAD_CLASSES');

console.log('\n-- the constants were found (a silent null would pass everything) --');
ok(BACKEND_CLASSES instanceof Set && BACKEND_CLASSES.size >= 4,
  `SST_CLASS_TYPES read out of backend/lib/cert_vocab.py: `
  + `${BACKEND_CLASSES ? [...BACKEND_CLASSES].join(', ') : 'NOT FOUND'}`);
ok(BACKEND_DEAD instanceof Set && BACKEND_DEAD.size >= 1,
  `SST_DEAD_CLASSES read out of backend/server.py: `
  + `${BACKEND_DEAD ? [...BACKEND_DEAD].join(', ') : 'NOT FOUND'}`);
ok(BACKEND_CLASSES && BACKEND_CLASSES.has('SST_TEMPORARY'),
  'and SST_TEMPORARY is one of them — the member the picker dropped');

// ── THE SHIPPED MODULE, EXECUTED ───────────────────────────────────────────
// oshaLogModel imports './dates', which a bare require cannot resolve under
// plain node. esmHarness resolves a RELATIVE import for real, so certLabel
// below is the shipped renderer and not a stub.
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/oshaLogModel.js');

const eqSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));

console.log('\n-- the frontend vocabulary IS the backend vocabulary --');
{
  ok(Array.isArray(M.SST_CLASS_TYPES),
    'oshaLogModel exports SST_CLASS_TYPES — one JS copy, in the module that '
    + 'already owns the labels');
  const front = new Set(M.SST_CLASS_TYPES || []);
  ok(BACKEND_CLASSES && eqSet(front, BACKEND_CLASSES),
    'and it is set-equal to cert_vocab.py SST_CLASS_TYPES — no member added '
    + `on one side only (frontend: ${[...front].join(', ') || 'NOTHING'})`);
  ok(M.SST_DEAD_CLASSES && BACKEND_DEAD
    && eqSet(new Set(M.SST_DEAD_CLASSES), BACKEND_DEAD),
    'SST_DEAD_CLASSES likewise, against server.py');
}

console.log('\n-- the picker offers EXACTLY those classes --');
{
  const options = M.SST_CLASS_OPTIONS || [];
  const offered = new Set(options.map((o) => o && o.value));
  ok(BACKEND_CLASSES && eqSet(offered, BACKEND_CLASSES),
    'SST_CLASS_OPTIONS offers exactly SST_CLASS_TYPES — nothing missing, '
    + `nothing invented (offered: ${[...offered].join(', ') || 'NOTHING'})`);
  ok(offered.has('SST_TEMPORARY'),
    'SST_TEMPORARY can be chosen. It is the SHORTEST-LIVED SST card, which is '
    + 'why cert_vocab.py calls dropping it the worst drop to make');
  ok(options.every((o) => o && o.value && o.label),
    'every option carries a value and a label');
}

console.log('\n-- every label is the product\'s own word for the class --');
{
  const options = M.SST_CLASS_OPTIONS || [];
  // THE INVARIANT, not a second table. The menu that ADDS a cert and the list
  // that RENDERS one must print the same string for the same class, so the
  // label is derived from certLabel() rather than compared to a literal.
  for (const o of options) {
    const rendered = M.certLabel({ type: o.value });
    ok(o.label === rendered,
      `${o.value}: menu says ${JSON.stringify(o.label)}, the cert list renders `
      + `${JSON.stringify(rendered)}`);
  }
  ok(options.length > 0, 'and there were options to check');

  // The specific wrongness that shipped: hours composed into a class name.
  const withHours = options.filter((o) => /\d\s*-?\s*(hr|hour)/i.test(o.label || ''));
  ok(withHours.length === 0,
    'no label states an hour count. Hours are a property of the CLASS, never '
    + 'a reading off the card (server.py), and both hand-written ones were '
    + `wrong (found: ${withHours.map((o) => o.label).join(', ') || 'none'})`);
}

console.log('\n-- the screen DERIVES its menu instead of keeping a copy --');
{
  const i = SCREEN.indexOf('const CERT_TYPES = [');
  ok(i > -1, 'the screen still builds CERT_TYPES');
  const block = SCREEN.slice(i, SCREEN.indexOf('];', i));

  ok(/\.\.\.SST_CLASS_OPTIONS/.test(block),
    'the SST rows are SPREAD from SST_CLASS_OPTIONS');
  ok(!/'SST_[A-Z]+'/.test(block),
    'and no SST constant is typed into the list — the copy that drifted is '
    + 'gone');
  ok(!/SST [A-Za-z]+ \(/.test(block),
    'nor any SST label with hours parenthesised after it');
  ok(/CERT_TYPE_LABELS\.OSHA_10/.test(block) && /CERT_TYPE_LABELS\.OSHA_30/.test(block),
    'the OSHA rows come from the same label map — they read "OSHA-10" here '
    + 'and "OSHA 10" everywhere else');
  ok(/SST_CLASS_OPTIONS/.test(SCREEN) && /from '\.\.\/\.\.\/src\/utils\/oshaLogModel'/.test(SCREEN),
    'imported from oshaLogModel, the module that owns the vocabulary');
}

console.log('\n-- the menu is actually rendered, and can be chosen from --');
{
  // CERT_TYPES was built and never used: `newCertType` was initialised to
  // 'OSHA_10' and no control wrote it, so every certification an admin added
  // was filed as an OSHA-10 regardless of what it was.
  ok(/CERT_TYPES\.map\(/.test(SCREEN),
    'CERT_TYPES is rendered — it used to be dead code');
  const writes = SCREEN.match(/setNewCertType\(/g) || [];
  ok(writes.length >= 2,
    'and something WRITES newCertType besides the post-save reset '
    + `(${writes.length} call sites)`);
  ok(/onPress=\{\(\) => setNewCertType\(t\.value\)\}/.test(SCREEN),
    'by tapping an option');
  ok(/type: newCertType/.test(SCREEN),
    'and the chosen type is what gets POSTed');
}

console.log('\n-- the dead class is offered, and said to be dead --');
{
  const options = M.SST_CLASS_OPTIONS || [];
  const limited = options.find((o) => o.value === 'SST_LIMITED');
  ok(!!limited,
    'SST_LIMITED is still offered. Historical rows carry it and an admin '
    + 'transcribing a worker\'s record must be able to say what it says');
  ok(limited && limited.deprecated === true,
    'but flagged deprecated, derived from SST_DEAD_CLASSES');
  ok(options.filter((o) => o.deprecated).length === (BACKEND_DEAD ? BACKEND_DEAD.size : -1),
    'exactly the classes server.py calls dead are flagged — not a hand-picked '
    + 'one');
  ok(/no longer issued/.test(SCREEN),
    'and the screen says so when one is selected');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
