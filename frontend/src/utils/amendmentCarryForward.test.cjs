/**
 * AN AMENDMENT MUST NOT SILENTLY DROP A STATUTORY ITEM.
 *
 * Item 2's input was removed from the superintendent log. The DECLARATION
 * stayed, so the logs already filed keep printing what he wrote -- but the
 * filed parent is not the only document that carries his words.
 *
 * ── THE PATH, WHICH IS WHY THIS FILE EXECUTES RATHER THAN GREPS ─────────────
 *
 *   1. `amend_logbook` seeds the correction from the parent:
 *      `"data": (data or {}).get("data", original.get("data"))`
 *   2. the editor opens that child and `hydrate`s it,
 *   3. the first autosave PUTs `buildData()` over `data` WHOLESALE --
 *      `update_logbook` writes `"data": data.data`, it does not merge.
 *
 * So the question "does an amendment keep item 2?" is a question about what
 * survives `hydrate` -> state -> `buildData`, and NO SOURCE-TEXT ASSERTION CAN
 * ANSWER IT. A screen can name `progress` in three places and still lose it,
 * or name it nowhere and keep it. This file runs the real two functions out of
 * the real screen and compares the block that comes out with the block that
 * went in.
 *
 * ── MEASURED, NOT ASSUMED, AND THE ANSWER WAS NOT UNIFORM ───────────────────
 *
 * Three fields on this screen are declared-but-no-longer-written. Run against
 * the commit before this fix, the round trip gave:
 *
 *   progress                    {summary, source}  ->  KEY GONE. Item 2 has no
 *                               other field, so the amended sheet prints
 *                               "-- Not recorded" against a required item.
 *   cs_activities.locations     sub-key gone, TEXT KEPT. `hydrate` joins
 *                               summary+locations into one box and writes it
 *                               back as `summary`, so nothing he wrote is lost.
 *   daily_inspection.result     sub-key gone, TEXT LOST. `location` survives,
 *                               so item 11 still reads PRESENT -- the item does
 *                               not disappear, but the result sentence does.
 *
 * ONLY `progress` IS FIXED HERE. The other two are a separate ruling and are
 * deliberately NOT asserted below: pinning today's behaviour would turn a
 * finding into a promise.
 *
 * Run:  node src/utils/amendmentCarryForward.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN_FILE = path.join(FRONTEND, 'app', 'logbooks',
  'site_superintendent_log.jsx');
const RAW = fs.readFileSync(SCREEN_FILE, 'utf8').split('\r\n').join('\n');
const SRC = RAW.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');

let failures = 0;
function ok(label, cond, hint) {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
}

// ── LIFTING TWO FUNCTIONS OUT OF A HOOKS COMPONENT ─────────────────────────
//
// The screen cannot be imported: it pulls in expo-router, react-native and a
// dozen native modules. But `hydrate` and `buildData` are both plain closures
// over `useState` values, so they can be re-hosted in a scope that declares
// those values as ordinary `let`s and the setters as ordinary assignments.
// That is what the component does at runtime; this is the same thing without
// React scheduling it.
//
// THE STATE NAMES ARE READ OFF THE SCREEN, not listed here. A hand-kept list
// would go stale the first time a field was added, and the failure would be a
// ReferenceError blamed on this file rather than on the drift.
function braceBody(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return null;
  const open = src.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') { depth -= 1; if (depth === 0) return src.slice(open + 1, i); }
  }
  return null;
}

const STATE = [...SRC.matchAll(/const \[(\w+), (set\w+)\] = useState\(/g)]
  .map((m) => ({ get: m[1], set: m[2] }));
const HYDRATE = braceBody(SRC, 'function hydrate(d)');
const BUILD = braceBody(SRC, 'const buildData = useCallback(()');

ok('the screen still has a hydrate and a buildData to run',
  !!HYDRATE && !!BUILD && STATE.length > 10,
  'if either anchor moves this file must be re-pointed, not deleted — it is '
  + 'the only thing that measures the amendment round trip');

// THE REAL MODULE, not a stub. A stubbed carry rule would let this file pass
// while the screen dropped the block in the field.
const { readCarried, writeCarried } = loadEsm('src/utils/carriedForward.js');

/** stored `data` -> hydrate -> state -> buildData -> the `data` that gets PUT. */
function roundTrip(stored) {
  const env = {
    readCarried,
    writeCarried,
    // The three helpers buildData calls before its return. Stubbed because
    // findings/DOB/incidents are not what this file is about, and each has its
    // own suite.
    deriveConditionAndOrderBlocks: () => ({}),
    chosenEntries: () => [],
    findingIsEmpty: () => true,
  };
  const names = Object.keys(env);
  const init = STATE.map(({ get }) => {
    const listy = ['findings', 'dobEntries', 'incidentEntries',
      'adoptedFindings', 'roster'].includes(get);
    return `let ${get} = ${listy ? '[]' : "''"};`;
  }).join('\n');
  const setters = STATE.map(({ get, set }) =>
    `const ${set} = (v) => { ${get} = typeof v === 'function' ? v(${get}) : v; };`)
    .join('\n');
  // eslint-disable-next-line no-new-func
  const run = new Function(...names, '__stored', `
    ${init}
    ${setters}
    const hydrate = (d) => { ${HYDRATE} };
    hydrate(__stored);
    const buildData = () => { ${BUILD} };
    return buildData();
  `);
  return run(...names.map((n) => env[n]), stored);
}

console.log('\nthe amendment round trip');

// THE REAL RECORD'S SHAPE. 2026-09-04 holds `{"summary": "First floor C joist
// framing"}`; `source` is added here because a log filed after the provenance
// flag landed carries one, and `source` is the half most easily lost.
const STORED_PROGRESS = {
  summary: 'First floor C joist framing',
  source: 'adopted',
};
const PARENT = {
  presence: {
    printed_name: 'Michael Cespedes', arrived_at: '07:00', departed_at: '16:00',
  },
  progress: STORED_PROGRESS,
  cs_activities: { summary: 'Walked the deck' },
  daily_inspection: { location: 'Cellar and 1st' },
  competent_person: { name: 'R. Sanchez' },
};

const filed = roundTrip(PARENT);

ok('the amended record still carries item 2',
  Object.prototype.hasOwnProperty.call(filed, 'progress'),
  'the child inherits the parent\'s data and the autosave PUTs this object '
  + 'over it wholesale — a missing key here DELETES a required BC 3301.13.13 '
  + 'item from the correction');
ok('and carries it byte-for-byte',
  JSON.stringify(filed.progress) === JSON.stringify(STORED_PROGRESS),
  `stored ${JSON.stringify(STORED_PROGRESS)} -> filed ${
    JSON.stringify(filed.progress)}`);
ok('including `source`, which cannot be re-derived later',
  filed.progress && filed.progress.source === 'adopted',
  'the sheet prints its provenance line off this flag; keeping the summary '
  + 'without it reprints his text under the wrong attribution');

// NOT A COPY THAT MERELY LOOKS THE SAME. Nothing is rebuilt, so the value that
// came out of storage is the value that goes back.
ok('and it is the stored object itself, not a rebuild',
  filed.progress === STORED_PROGRESS,
  'a reconstruction is a chance to normalise, reorder or trim — the record '
  + 'must not change appearance after it was signed');

console.log('\nand a record that never had one does not acquire one');

const fresh = roundTrip({ presence: { printed_name: 'Michael Cespedes' } });
ok('no `progress` key is invented',
  !Object.prototype.hasOwnProperty.call(fresh, 'progress'),
  '`{}` and a missing key are different documents to the renderer, and '
  + 'writing `{}` where there was nothing is absence presented as an answer');
ok('a stored empty block is still carried as it was',
  JSON.stringify(roundTrip({ progress: {} }).progress) === '{}',
  'faithful means faithful in both directions — this does not CREATE a block, '
  + 'it declines to edit one');

console.log('\nthe input is still gone — this is a carry, not a restoration');

ok('no item 2 field, label or placeholder is back',
  !/progressLabel/.test(SRC) && !/progressPlaceholder/.test(SRC)
  && !/progressAdoptedNote/.test(SRC),
  'carrying the stored bytes must never turn back into asking him the '
  + 'question');
ok('and nothing autofills or edits it',
  !/adoptableSummary/.test(SRC) && !/setProgress\(/.test(SRC)
  && !/progressBlock\(/.test(SRC),
  'a carried block is the previous author\'s statement; offering it for edit '
  + 'under a new signature is the thing the removal was for');

console.log('\nthe wiring, so the round trip above is the screen\'s and not this file\'s');

ok('hydrate reads it through the shared rule',
  /setCarriedProgress\(readCarried\(d, 'progress'\)\)/.test(SRC));
ok('buildData writes it through the shared rule',
  /\.\.\.writeCarried\('progress', carriedProgress\)/.test(SRC));
ok('it survives the trip to /consent',
  /carriedProgress,/.test(SRC.slice(SRC.indexOf('const snapshot'),
    SRC.indexOf('const restore')))
  && /setCarriedProgress\(v\.carriedProgress\)/.test(SRC),
  'restore() would otherwise blank it and the next autosave would drop the '
  + 'block after all — the /consent trip is not a rare path, it is how he '
  + 'signs');
ok('and restore does NOT default it to a value',
  !/setCarriedProgress\(v\.carriedProgress \?\? /.test(SRC),
  '`?? {}` would invent an empty block on every restored draft; `undefined` '
  + 'has to stay undefined');
ok('it is in buildData\'s dependency array',
  /carriedProgress/.test(SRC.slice(SRC.indexOf('const buildData'),
    SRC.indexOf('const buildData') + 4000).split('}, [')[1] || ''),
  'a stale closure would file the block captured on a previous render');

if (failures) {
  console.error(`\namendmentCarryForward: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
