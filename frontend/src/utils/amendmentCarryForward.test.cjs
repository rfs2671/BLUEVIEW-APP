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
 * ── THE SEPARATE RULING CAME, AND ONE OF THE TWO CHANGED ────────────────────
 *
 * THIS FILE USED TO SAY, in this place and in these words:
 *
 *     "ONLY `progress` IS FIXED HERE. The other two are a separate ruling and
 *      are deliberately NOT asserted below: pinning today's behaviour would
 *      turn a finding into a promise."
 *
 * That was right while nobody had ruled. The operator has now ruled on one of
 * the two:
 *
 *     "daily_inspection.result: carry it forward, same as item 2."
 *     "...carry it. Your call is right -- the screen removed the field, not
 *      the amender."
 *
 * So the finding IS a promise now, and the line above that measured `result`
 * as TEXT LOST is kept as history rather than deleted: it is the baseline the
 * assertions below are inverted from, and a reader who only sees the green
 * cannot tell what the green replaced.
 *
 * `cs_activities.locations` IS STILL UNRULED, and the case below still asserts
 * exactly what it asserted before: THE TEXT SURVIVES, and nothing about the
 * SHAPE it survives in. The distinction is the whole point. The reason that
 * field needs no carry is a measurement -- `hydrate` folds its text into
 * `summary` and writes it back there -- and a reason nobody re-checks is a
 * reason that quietly stops being true. But "the sub-key is gone" is today's
 * implementation, not a promise anyone made, so it is printed and not asserted.
 * If a later change keeps his words under a different key this file stays green,
 * and if a change loses them it does not.
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

/** stored `data` -> hydrate -> state -> buildData -> the `data` that gets PUT.
 *
 * `edit` IS THE AMENDER TYPING. Pass `{inspectionLocation: ''}` and the value
 * is assigned through the screen's own setter AFTER hydrate and BEFORE
 * buildData -- which is the order the real screen runs in when he opens a
 * correction and changes a box. It is applied by state NAME, read off the
 * screen like every other name here, so an edit to a field that no longer
 * exists is a loud failure rather than a silent no-op.
 */
function roundTrip(stored, edit) {
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
  const known = new Set(STATE.map(({ get }) => get));
  for (const name of Object.keys(edit || {})) {
    if (!known.has(name)) {
      throw new Error(`roundTrip: no state named \`${name}\` on the screen -- `
        + 'the field was renamed or removed and this edit is measuring nothing');
    }
  }
  const edits = STATE.filter(({ get }) => edit && get in edit)
    .map(({ get, set }) => `${set}(__edit.${get});`).join('\n');
  // eslint-disable-next-line no-new-func
  const run = new Function(...names, '__stored', '__edit', `
    ${init}
    ${setters}
    const hydrate = (d) => { ${HYDRATE} };
    hydrate(__stored);
    ${edits}
    const buildData = () => { ${BUILD} };
    return buildData();
  `);
  return run(...names.map((n) => env[n]), stored, edit || {});
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

// THE SAME FIVE FOR ITEM 11, because a sub-key carry loses its value on the
// /consent trip in exactly the way a block carry does, and the round trip
// above cannot see that trip -- it runs hydrate and buildData back to back,
// while the real screen unmounts between them when he goes to sign.
ok('hydrate reads the result through the SAME shared rule, not a second one',
  /setCarriedInspectionResult\(readCarried\(g\('daily_inspection'\), 'result'\)\)/
    .test(SRC),
  'a second mechanism is a second set of edge cases to get the present-or-'
  + 'absent rule wrong in');
ok('buildData writes it through the shared rule',
  /\.\.\.writeCarried\('result', carriedInspectionResult\)/.test(SRC));
ok('it survives the trip to /consent',
  /carriedInspectionResult,/.test(SRC.slice(SRC.indexOf('const snapshot'),
    SRC.indexOf('const restore')))
  && /setCarriedInspectionResult\(v\.carriedInspectionResult\)/.test(SRC),
  'restore() would otherwise blank it and the next autosave would drop the '
  + 'sentence after all — signing goes through /consent');
ok('and restore does NOT default it to a value',
  !/setCarriedInspectionResult\(v\.carriedInspectionResult \?\? /.test(SRC),
  '`?? \'\'` would invent an empty result on every restored draft; a key that '
  + 'exists is a key `_cs_item_body` reaches');
ok('it is in buildData\'s dependency array',
  /carriedInspectionResult/.test(SRC.slice(SRC.indexOf('const buildData'),
    SRC.indexOf('const buildData') + 4000).split('}, [')[1] || ''),
  'a stale closure would file the sentence captured on a previous render');
ok('and item 11\'s input is still one box — the result is carried, not asked',
  !/setCarriedInspectionResult\(inspection/.test(SRC)
  && (SRC.match(/inspectionResult/g) || []).length === 0,
  'carrying the stored bytes must never turn back into asking him the '
  + 'question — there is no result input and there is not going to be one');

// ── ITEM 11'S `result`, THE SECOND OF THE THREE, NOW RULED ─────────────────
//
// A SUB-KEY CARRY, NOT A BLOCK CARRY, and that is the only difference from
// item 2. `progress` is a whole top-level block the screen never writes;
// `daily_inspection` is a block the screen DOES still write -- `location` is
// collected and current -- with one uncollected sub-key inside it. The same
// two functions do the job, because `readCarried` operates on a key WITHIN an
// object and `g('daily_inspection')` hands it that object.
//
// WHAT IT USED TO DO, MEASURED ON THE COMMIT BEFORE THIS ONE:
//
//     stored {"location":"Cellar and 1st","result":"All good here"}
//     filed  {"location":"Cellar and 1st"}
//
// Item 11 still read PRESENT off `location`, so the sheet kept the item and
// lost his sentence -- the quietest shape a loss can take, because the item
// number never goes missing to point at it.
console.log('\nitem 11: the result sentence survives the amendment');

const STORED_INSPECTION = { location: 'Cellar and 1st', result: 'All good here' };
const INSPECTION_PARENT = {
  presence: { printed_name: 'Michael Cespedes' },
  daily_inspection: STORED_INSPECTION,
};

const amended = roundTrip(INSPECTION_PARENT);

ok('the amended record still carries his result sentence',
  amended.daily_inspection && amended.daily_inspection.result === 'All good here',
  'was `{"location":"Cellar and 1st"}` before the ruling — the item survived '
  + 'on `location` and the sentence did not. The operator ruled: "carry it '
  + 'forward, same as item 2."');
ok('and carries it byte-for-byte, unnormalised',
  amended.daily_inspection.result === STORED_INSPECTION.result,
  `stored ${JSON.stringify(STORED_INSPECTION.result)} -> filed ${
    JSON.stringify(amended.daily_inspection.result)}`);
ok('alongside the location he is still asked for',
  amended.daily_inspection.location === 'Cellar and 1st',
  'the carry must ride BESIDE the live field, not replace the block — '
  + '`location` is collected and current and this screen still writes it');
ok('and the live location is his, not the parent\'s, when he retypes it',
  roundTrip(INSPECTION_PARENT, { inspectionLocation: '2nd floor' })
    .daily_inspection.location === '2nd floor',
  'a carry that overwrote the collected field would file the parent\'s answer '
  + 'over the amender\'s');

console.log('\nand a record with no result does not acquire one');

// THE NEGATIVE, AND IT IS THE HALF THAT IS EASY TO GET WRONG. `{result: ""}`
// and `{result: undefined}` both LOOK like nothing and are not: `_has_content`
// walks `item["fields"]` and `_cs_item_body` prints every field it finds, so a
// key that exists is a key the renderer reaches. See carriedForward.js.
for (const [label, stored] of [
  ['location only, no result ever stored', { daily_inspection: { location: 'Cellar and 1st' } }],
  ['an empty inspection block', { daily_inspection: {} }],
  ['no inspection block at all', { presence: { printed_name: 'Michael Cespedes' } }],
]) {
  const out = roundTrip(stored);
  ok(`no \`result\` key is invented — ${label}`,
    !Object.prototype.hasOwnProperty.call(out.daily_inspection || {}, 'result'),
    `filed ${JSON.stringify(out.daily_inspection)} — a present-but-empty`
    + ' answer is absence presented as a statement, and item 11 is a statutory'
    + ' item under 1 RCNY 3301-04(f)');
}
ok('a stored empty-string result is still carried as it was',
  roundTrip({ daily_inspection: { location: 'A', result: '' } })
    .daily_inspection.result === '',
  'faithful in both directions — this does not CREATE a value, it declines to '
  + 'edit one');

// ── THE EDGE CASE, RULED DELIBERATELY ──────────────────────────────────────
//
// He clears the location on the correction while a stored `result` remains.
// The block then holds a sentence and no location.
//
// CARRIED ANYWAY. `result` was never the amender's to delete -- the SCREEN
// removed that input, he did not, and a field he was never shown cannot be
// read as a field he chose to blank. Deleting his predecessor's sentence as a
// side effect of an edit to a different box is the exact shape this whole file
// exists to prevent.
//
// AND ITEM 11 STILL READS PRESENT IN THAT STATE, which is the fact that makes
// it safe: `_has_content` in superintendent_log.py walks ALL of
// `["inspected_on", "location", "result"]` and returns True on the first
// non-empty one, so a block holding only `result` is PRESENT, not NOT_REACHED.
// The sheet prints his sentence with no location line above it -- sparse, and
// exactly as sparse as what is stored.
console.log('\nthe cleared-location edge case');

const cleared = roundTrip(INSPECTION_PARENT, { inspectionLocation: '' });
ok('clearing the location does not delete his sentence',
  cleared.daily_inspection && cleared.daily_inspection.result === 'All good here',
  `filed ${JSON.stringify(cleared.daily_inspection)}`);
ok('and the cleared location is genuinely gone, not carried back',
  !Object.prototype.hasOwnProperty.call(cleared.daily_inspection, 'location'),
  'he cleared a field he WAS shown; that edit is his and must stand');

// ── THE THIRD NEIGHBOUR, MEASURED AND NOT PINNED ───────────────────────────
//
// `cs_activities.locations` is unruled. What is asserted here is the REASON it
// needs no ruling -- his words survive -- and NOT the shape they survive in.
// A future change that keeps his text under a different key must not turn this
// file red; one that loses it must.
console.log('\ncs_activities: unruled, and the text still survives');

const ACTIVITIES_PARENT = {
  cs_activities: { summary: 'Walked the deck', locations: 'Cellar and 1st' },
};
const act = roundTrip(ACTIVITIES_PARENT).cs_activities;
console.log(`       stored ${JSON.stringify(ACTIVITIES_PARENT.cs_activities)}`);
console.log(`       filed  ${JSON.stringify(act)}`);
ok('every word he wrote is still somewhere in the filed block',
  ['Walked the deck', 'Cellar and 1st']
    .every((s) => JSON.stringify(act).includes(s)),
  '`hydrate` folds summary+locations into one box and writes it back as '
  + '`summary`; if that fold ever stops happening this field needs the same '
  + 'carry item 2 and item 11 have');

if (failures) {
  console.error(`\namendmentCarryForward: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
