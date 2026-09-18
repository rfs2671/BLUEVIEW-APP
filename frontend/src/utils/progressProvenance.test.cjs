/**
 * ITEM 2 SAYS WHERE ITS TEXT CAME FROM.
 *
 * The flag was declared in backend/lib/logbook/superintendent_log.py before
 * the client existed, on the argument that RETROFITTING PROVENANCE ONTO FILED
 * RECORDS IS IMPOSSIBLE. The client half never landed, so `item_provenance`
 * resolved every filed log to `unmarked` — the exact outcome the argument was
 * written to prevent, and one record (2026-09-04) is permanently in it.
 *
 * WHAT THE OPERATOR ASKED, AND WHY THE ANSWER WAS ADOPTION RATHER THAN
 * REMOVAL. He types the day twice: "carpentry" on the CP's daily jobsite log
 * at 13:55, "First floor C joist framing" on the superintendent log at 22:07.
 * BC 3301.13.13 item 2 is required on a document HE signs, so removing it
 * drops a statutory item — but nothing requires him to have COMPOSED the
 * sentence (compare item 3, expressly "the construction superintendent's
 * activities"), so adopting the CP's and signing it satisfied the requirement.
 *
 * ── AND THE OPERATOR HAS SINCE REMOVED THE INPUT ANYWAY ────────────────────
 *
 * Adoption answered "may he copy it?" and the later question was "should he be
 * asked at all?". He was typing the same day twice and the second typing added
 * nothing the first had not already recorded, so item 2's box came off the
 * screen. The duplication the adoption machinery managed is the duplication
 * that has now been deleted.
 *
 * SO THIS FILE'S SUBJECT SPLIT IN TWO, and both halves are still live:
 *
 *   THE MODULE is unchanged and every rule in it still matters, because the
 *   six logs already FILED carry `source` and the sheet still prints the line
 *   that reads it. `progressSource`, `progressBlock` and `adoptedTextFromStored`
 *   are asserted below exactly as they were.
 *
 *   THE SCREEN no longer calls any of it, and the assertions that said it did
 *   are restated as the opposite — with the declaration checks that make the
 *   removal forward-only. See siteSuperintendentSign.test.cjs section 8b for
 *   the ruling and why item 3 was NOT removed alongside it.
 *
 * THE MODULE IS KEPT THOUGH THE APP NO LONGER IMPORTS IT. It is the only
 * written statement of what `adopted` and `own` mean on the client side, and
 * the backend still reads both off filed records. Deleting it would leave the
 * strings asserted against nothing.
 *
 * Run:  node src/utils/progressProvenance.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(__dirname, 'progressProvenance.js'), 'utf8');
const SCREEN = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'site_superintendent_log.jsx'), 'utf8',
).split('\r\n').join('\n');
const PY = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'lib', 'logbook', 'superintendent_log.py'),
  'utf8',
);

/**
 * Comments stripped, for every assertion about what the SCREEN does.
 *
 * THE SCREEN ASSERTIONS BELOW ARE NOW MOSTLY NEGATIVE, and that is exactly the
 * shape that reads its own explanation and reports it as code. The screen and
 * this file both have to NAME `progressBlock` and `adoptedText` in prose to
 * explain why they are gone, and a raw search cannot tell the removal from the
 * paragraph describing it. (Here the error lands the safe way round — a note
 * would make a negative assertion FAIL — but the next assertion added here
 * would not be guaranteed that courtesy, and this repo has twice shipped a
 * source test that passed on its own comment prose.)
 */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');
const SCREEN_CODE = CODE(SCREEN);

let failures = 0;
function ok(label, cond, hint) {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
}

// ── THE MODULE, EVALUATED WHOLE ─────────────────────────────────────────────
//
// ESM source, CommonJS runner. The first draft lifted the three pure functions
// out one at a time and `progressBlock` threw `ReferenceError: progressSource
// is not defined` — it CALLS its sibling, and a per-function lift puts each one
// in its own empty scope. That failure was worth having: it says the functions
// are not independent, and testing them as if they were would have tested
// something the app does not run.
//
// So the whole module body is evaluated with its imports stripped, and
// `chainHead` is supplied by evaluating THE REAL amendmentChain.js the same
// way. A hand-written stub of chainHead would be a second copy of the rule
// this file exists to keep single — the newest FILED link, withdrawn links out
// of the chain — and a stub that drifted would let `adoptableSummary` pass here
// while adopting the wrong document in the field.
function loadEsm(source, injected = {}) {
  const body = source
    .split('\n')
    .filter((l) => !/^\s*import\s/.test(l))
    .join('\n')
    .replace(/^export default[\s\S]*$/m, '')
    .replace(/^export /gm, '');
  const names = Object.keys(injected);
  const exported = [...source.matchAll(/^export (?:function|const) (\w+)/gm)]
    .map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(...names,
    `${body}\nreturn { ${exported.join(', ')} };`)(
    ...names.map((n) => injected[n]));
}

// TWO REAL MODULES DEEP, DELIBERATELY. `adoptableSummary` now goes through
// `filedDailyRecord`, which goes through `chainHead` — item 8's default asks
// the same question about the same document, so the rule moved into
// dailyLogRecord.js rather than being written twice. Both are loaded for real:
// a stub at either level would let this file pass while the screen adopted the
// wrong link of an amended chain.
const { chainHead } = loadEsm(
  fs.readFileSync(path.join(__dirname, 'amendmentChain.js'), 'utf8'));
const { filedDailyRecord } = loadEsm(
  fs.readFileSync(path.join(__dirname, 'dailyLogRecord.js'), 'utf8'),
  { chainHead });
const {
  progressSource, progressBlock, adoptedTextFromStored, adoptableSummary,
} = loadEsm(SRC, { filedDailyRecord });

console.log('\nthe rule');

ok('unedited adopted text is `adopted`',
  progressSource('carpentry', 'carpentry') === 'adopted');
ok('one edited character makes it his own',
  progressSource('carpentry and joists', 'carpentry') === 'own');
ok('deleting it and writing his own makes it his own',
  progressSource('First floor C joist framing', 'carpentry') === 'own');

// THE CASE THAT DECIDES THE SHAPE. Nothing was offered — the CP filed no daily
// log, or the read failed — so what he types is his own account. Not a guess:
// no text ever reached him.
ok('text with nothing offered is `own`, not unmarked',
  progressSource('First floor C joist framing', '') === 'own');
ok('and `own` when the offered text was whitespace',
  progressSource('something', '   ') === 'own');

// AN EMPTY BOX CLAIMS NOTHING. Stamping `own` on a blank would assert he wrote
// something, which is the absence-read-as-a-claim defect this whole log was
// rebuilt around.
ok('an empty summary has no source at all',
  progressSource('', 'carpentry') === null);
ok('and whitespace is empty',
  progressSource('   \n ', 'carpentry') === null);

// WHITESPACE MUST NOT FLIP THE FLAG. A trailing newline from the keyboard is
// not him rewriting the CP's account of the day.
ok('surrounding whitespace does not make it his own',
  progressSource('  carpentry \n', 'carpentry') === 'adopted');

console.log('\nthe block that is filed');

ok('an empty summary still files {}',
  JSON.stringify(progressBlock('', 'x')) === '{}',
  'a source key on an empty block would be a claim about nothing');
ok('an adopted summary carries both keys',
  JSON.stringify(progressBlock('carpentry', 'carpentry'))
    === JSON.stringify({ summary: 'carpentry', source: 'adopted' }));
ok('the stored summary is trimmed',
  progressBlock('  carpentry  ', '').summary === 'carpentry');

console.log('\nreopening a stored log');

ok('a stored `adopted` log re-adopts its own summary',
  adoptedTextFromStored({ summary: 'carpentry', source: 'adopted' }) === 'carpentry',
  'without this, reopening and changing nothing would file it as `own`');
ok('a stored `own` log adopts nothing',
  adoptedTextFromStored({ summary: 'mine', source: 'own' }) === '',
  'returning it would file a sentence he wrote as adopted from a record it '
  + 'never came from');
ok('a log filed before the flag existed adopts nothing',
  adoptedTextFromStored({ summary: 'carpentry' }) === '');
ok('and neither does an empty block', adoptedTextFromStored({}) === '');
ok('nor a missing one', adoptedTextFromStored(undefined) === '');

// THE ROUND TRIP, because the two functions above are only correct together.
const reopened = adoptedTextFromStored({ summary: 'carpentry', source: 'adopted' });
ok('reopen → no edit → still adopted',
  progressSource('carpentry', reopened) === 'adopted');
ok('reopen → edit → own',
  progressSource('carpentry and joists', reopened) === 'own');

console.log('\nthe strings match the server');

for (const [js, py] of [['adopted', 'PROVENANCE_ADOPTED'], ['own', 'PROVENANCE_OWN']]) {
  ok(`${py} is '${js}' on both sides`,
    new RegExp(`${py} = "${js}"`).test(PY) && SRC.includes(`= '${js}'`),
    'item_provenance treats an unrecognised value as `unmarked`, so a typo '
    + 'here does not error — it silently files an unmarked record, which is '
    + 'the failure that already happened once');
}

console.log('\nthe screen no longer writes item 2, and nothing else moved');

// ── WHAT THIS SECTION USED TO ASSERT ───────────────────────────────────────
//
// Six assertions that the screen was wired to this module: the import,
// `progress: progressBlock(progress, adoptedText)` in buildData, `adoptedText`
// in the /consent snapshot, its restore, hydrate re-deriving it from the
// stored flag, and its presence in buildData's dependency array. Each one is
// now the opposite, because item 2's input is gone.
//
// ASSERTED AS A GROUP RATHER THAN SIX NEGATIONS, because the failure worth
// catching is a PARTIAL removal. A screen that drops the field but keeps the
// state and the snapshot still files a `progress` block — one filled from
// whatever a restored draft happens to carry, with a provenance flag computed
// against a box that is no longer on screen. Every trace goes or none does.
const traces = ['progressProvenance', 'progressBlock', 'progressSource',
  'adoptedTextFromStored', 'PROVENANCE_ADOPTED', 'adoptedText',
  'setProgress', 'adoptableSummary', 'wantSummary'];
const left = traces.filter((n) => SCREEN_CODE.includes(n));
ok('the screen carries no trace of item 2\'s input',
  left.length === 0,
  `state, snapshot, restore, hydrate, buildData and the field go together — `
  + `a half-removed field files a block nobody saw (left: ${
    JSON.stringify(left)})`);
ok('and buildData does not file a `progress` key',
  !/progress:/.test(SCREEN_CODE),
  'an empty block would still be a claim about a document, and a restored '
  + 'draft would make it a non-empty one');

// ── THE READERS ARE UNTOUCHED, WHICH IS THE WHOLE SAFETY OF IT ─────────────
//
// `item_state` short-circuits on `collected` BEFORE it reads the stored block.
// Flipping item 2's flag would therefore not "stop collecting it going
// forward" — it would change what SIX ALREADY-FILED logs print, swapping the
// superintendent's own sentences for "This log does not record this item" on
// records nobody is entitled to rewrite. Forward-only means the writer stops
// and the declaration stays.
const item2 = PY.slice(PY.indexOf('"key": "progress"'),
  PY.indexOf('"key": "cs_activities"'));
ok('item 2 is still declared, and still COLLECTED', /"collected": True/.test(item2),
  'the six filed logs print their stored summary through this flag; flipping '
  + 'it rewrites them');
ok('and still declares the `summary` field it was filled through',
  /"fields": \["summary"\]/.test(item2));
ok('and still declares provenance, so a stored `source` still prints',
  /"provenance": True/.test(item2));
ok('the short-circuit this depends on is still there',
  /if not item\.get\("collected"\):\s*\n\s*return NOT_COLLECTED/.test(PY),
  'if `item_state` ever started reading the block first, `collected` would '
  + 'stop being the switch this reasoning rests on');

console.log('\nthe effect item 2 shared is still there, still serving the rest');

// ── THE TRAP THIS SECTION NOW EXISTS TO SET ────────────────────────────────
//
// ONE EFFECT SERVED ITEMS 2, 4/5 AND 8 off a single read of the CP's daily
// jobsite log -- fetching it twice would be two chances to disagree about
// which link of an amended chain is the record. Item 2's share of it has gone
// with item 2's input.
//
// WHICH LEAVES AN EFFECT THAT READS THE CP'S DAILY LOG AND IS EASY TO MISTAKE
// FOR "the item 2 autofill", now that the item it was named after is gone. It
// is also the competent-person default for item 8 and the findings offers for
// items 4/5. Removing it would silently take both.
const effect = SCREEN_CODE.slice(SCREEN_CODE.indexOf('const dailyOfferRef'),
  SCREEN_CODE.indexOf('const dailyOfferRef') + 2400);
ok('the effect is present to inspect', effect.length > 500,
  'items 4/5 and 8 are still fed from it; it did not go with item 2');
ok('it never runs on a filed log', /if \(loading \|\| locked \|\|/.test(effect),
  'prefilling a locked document would be the app editing a statutory record');
ok('item 2\'s offer is gone from it',
  !/wantSummary/.test(effect) && !/adoptableSummary/.test(effect),
  'an autofill with no field to fill writes a summary onto the payload that '
  + 'nobody ever saw');
ok('the other two offers still guard on their OWN fields',
  /const wantCp = /.test(effect) && /const wantFindings = /.test(effect),
  'one shared guard would let a man who answered findings lose item 8\'s '
  + 'default');
ok('it runs once per mount', /dailyOfferRef\.current = true;/.test(effect),
  'the values it reads are in the dependency array and the effect sets them '
  + '— the ref is what stops the loop');
ok('it reads the daily jobsite log through the shared constant',
  /getByProject\(projectId, SOURCE_LOG_TYPE, logDate\)/.test(effect));
ok('a failed read still costs neither survivor',
  /Promise\.allSettled/.test(effect)
  && /dayRes\.status === 'fulfilled' \? dayRes\.value : null/.test(effect),
  'Promise.all would let a 403 on the roster suppress the findings offers '
  + 'too, and offline must not block the log');

console.log('\nthe note he read, and the copy that went with it');

// THE ADOPTION NOTE WAS THE FIELD'S, AND WENT WITH THE FIELD. It said "these
// are not your words" over a box that no longer exists; left behind it would
// be a sentence about a control nobody can see, and the i18n test's job is to
// catch keys the screen stopped asking for.
const EN = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
const ES = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'es.js'), 'utf8');
ok('en.js drops item 2\'s field copy',
  !/progressAdoptedNote:/.test(EN) && !/progressLabel:/.test(EN)
  && !/progressPlaceholder:/.test(EN),
  'a string for a control nobody can reach is a promise the screen no longer '
  + 'keeps');
// ONE LOCALE, AND THE SECOND HALF OF THIS IS WHY. The first draft looped both
// files and asked each to have dropped the keys -- which es.js satisfied
// WITHOUT THE CHANGE, because `siteSuperintendent` is an EN-only namespace and
// es.js never carried a single one of its keys. An assertion no edit could
// break is not evidence. What is worth pinning is that the namespace really is
// EN-only, so "removed from en.js" is "removed", not half a removal.
ok('and there was no Spanish half to forget',
  !/siteSuperintendent/.test(ES) && /siteSuperintendent: \{/.test(EN),
  'if es.js ever gains this namespace, removals stop being one-sided and this '
  + 'file has to check both');

// AND THE SHEET'S OWN PROVENANCE LINE IS NOT THE NOTE AND DID NOT GO. It is
// printed server-side off a FILED record's stored `source`, for a reader of
// the document rather than the man filling it, and the six logs already filed
// still reach it.
ok('the filed sheet still says where an adopted item 2 came from',
  /_CS_PROVENANCE_LINES/.test(
    fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8')),
  'the screen-side note and the sheet-side line are different statements to '
  + 'different readers; only the first belonged to the input');

console.log('\nwhat is adoptable');

const filed = (over) => ({
  id: 'a', status: 'submitted', created_at: '2026-09-04T13:55:00Z',
  data: { general_description: 'carpentry' }, ...over,
});

ok('the CP\'s filed summary is adoptable',
  adoptableSummary([filed()]) === 'carpentry');
ok('an empty list offers nothing', adoptableSummary([]) === '');
ok('a non-array offers nothing', adoptableSummary(null) === '');

// A DRAFT IS NOT AN ACCOUNT OF THE DAY. The CP's unsigned draft is not
// something its own author has stood behind; adopting it would put text on a
// signed statutory record that nobody had filed.
ok('an unsigned draft is NOT adoptable',
  adoptableSummary([filed({ status: 'draft' })]) === '');
ok('a locked row is adoptable even without status submitted',
  adoptableSummary([filed({ status: undefined, is_locked: true })]) === 'carpentry');
ok('a filed log with no description offers nothing',
  adoptableSummary([filed({ data: {} })]) === '');
ok('and neither does a whitespace description',
  adoptableSummary([filed({ data: { general_description: '  ' } })]) === '');

// THE CHAIN. `GET /logbooks/project/...` returns every link, so `rows[0]`
// would adopt whichever the server happened to list first. chainHead takes the
// newest FILED link — the same rule `_filed_log` applies on the server.
const parent = filed({ id: 'p', created_at: '2026-09-04T13:55:00Z' });
const amend = filed({
  id: 'c', is_amendment: true, created_at: '2026-09-04T17:10:00Z',
  data: { general_description: 'carpentry, corrected to joist framing' },
});
ok('an amended daily log adopts the CORRECTION, not the original',
  adoptableSummary([parent, amend])
    === 'carpentry, corrected to joist framing');
ok('and the row order it arrives in does not matter',
  adoptableSummary([amend, parent])
    === 'carpentry, corrected to joist framing');

// A WITHDRAWN CORRECTION CORRECTED NOTHING. chainHead drops it from the chain
// entirely, so the record falls back to what is actually filed.
ok('a withdrawn amendment leaves the original standing',
  adoptableSummary([parent, filed({
    id: 'c', is_amendment: true, status: 'withdrawn',
    created_at: '2026-09-04T17:10:00Z',
    data: { general_description: 'taken back' },
  })]) === 'carpentry');

// AN UNSIGNED CORRECTION IS AN INTENTION, NOT THE RECORD.
ok('an unsigned amendment does not displace the filed original',
  adoptableSummary([parent, filed({
    id: 'c', is_amendment: true, status: 'draft',
    created_at: '2026-09-04T17:10:00Z',
    data: { general_description: 'not filed yet' },
  })]) === 'carpentry');

ok('the record is chosen through the shared rule, not a picker of its own',
  /import \{ filedDailyRecord \} from '\.\/dailyLogRecord'/.test(SRC),
  'rows[0] would adopt whichever link the server listed first, and item 8 '
  + 'asks the same question about the same document');

if (failures) {
  console.error(`\nprogressProvenance: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
