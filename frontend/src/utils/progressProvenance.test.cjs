/**
 * ITEM 2 SAYS WHERE ITS TEXT CAME FROM.
 *
 * The flag was declared in backend/lib/logbook/superintendent_log.py before
 * the client existed, on the argument that RETROFITTING PROVENANCE ONTO FILED
 * RECORDS IS IMPOSSIBLE. The client half never landed, so `item_provenance`
 * resolved every filed log to `unmarked` — the exact outcome the argument was
 * written to prevent, and one record (2026-09-04) is permanently in it.
 *
 * WHAT THE OPERATOR ASKED, AND WHY THE ANSWER IS ADOPTION RATHER THAN REMOVAL.
 * He types the day twice: "carpentry" on the CP's daily jobsite log at 13:55,
 * "First floor C joist framing" on the superintendent log at 22:07. BC
 * 3301.13.13 item 2 is required on a document HE signs, so removing it drops a
 * statutory item — but nothing requires him to have COMPOSED the sentence
 * (compare item 3, expressly "the construction superintendent's activities"),
 * so adopting the CP's and signing it satisfies the requirement.
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

const { chainHead } = loadEsm(
  fs.readFileSync(path.join(__dirname, 'amendmentChain.js'), 'utf8'));
const {
  progressSource, progressBlock, adoptedTextFromStored, adoptableSummary,
} = loadEsm(SRC, { chainHead });

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

console.log('\nthe screen is wired to it');

ok('the screen imports the shared rule',
  /from '\.\.\/\.\.\/src\/utils\/progressProvenance'/.test(SCREEN));
ok('buildData files the block through the one builder',
  /progress: progressBlock\(progress, adoptedText\)/.test(SCREEN),
  'a hand-rolled block here would be a second rule about what the document '
  + 'claims');
ok('the adopted text survives the trip to /consent',
  /adoptedText,/.test(SCREEN.slice(SCREEN.indexOf('const snapshot'),
    SCREEN.indexOf('const restore'))),
  'without it, restore() puts the text back with nothing offered and the '
  + 'document files an adopted summary as his own');
ok('and restore puts it back',
  /setAdoptedText\(v\.adoptedText \?\? ''\)/.test(SCREEN));
ok('hydrate re-derives it from the stored flag',
  /setAdoptedText\(adoptedTextFromStored\(g\('progress'\)\)\)/.test(SCREEN));
ok('adoptedText is in buildData\'s dependency array',
  /progress, adoptedText, activities,/.test(SCREEN),
  'a stale closure would file the flag computed against the previous value');

console.log('\nwhat the offer will not do');

const effect = SCREEN.slice(SCREEN.indexOf('const adoptAttemptedRef'),
  SCREEN.indexOf('const adoptAttemptedRef') + 1800);
ok('the offer is present to inspect', effect.length > 500);
ok('it never runs on a filed log', /if \(loading \|\| locked \|\|/.test(effect),
  'prefilling a locked document would be the app editing a statutory record');
ok('it never overwrites typed text',
  /if \(String\(progress \|\| ''\)\.trim\(\)\) return;/.test(effect));
ok('it runs once per mount', /adoptAttemptedRef\.current = true;/.test(effect),
  '`progress` is in the dependency array and the effect sets it — the ref is '
  + 'what stops the loop');
ok('it reads the daily jobsite log through the shared constant',
  /getByProject\(\s*projectId, SOURCE_LOG_TYPE, logDate\)/.test(effect));
ok('a failed read leaves the box his own',
  /catch \(_e\) \{/.test(effect),
  'offline must not block the log, and text typed after a failed read is '
  + 'genuinely his own');

console.log('\nthe note he reads');

ok('the note is driven by the same rule that writes the flag',
  /progressSource\(progress, adoptedText\) === PROVENANCE_ADOPTED/.test(SCREEN),
  'a separately-computed note could say "adopted" while the document said '
  + '"own"');
const EN = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
ok('the note exists', /progressAdoptedNote:/.test(EN));
ok('it says signing makes it his', /Signing makes it your account/.test(EN),
  'he is about to put his signature under a sentence the CP wrote; the note '
  + 'is the only place that is said');
ok('and it invites the edit without implying the CP was wrong',
  /edit it if the day looked different to you/.test(EN));

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

ok('the chain is collapsed through the existing rule, not a third picker',
  /import \{ chainHead \} from '\.\/amendmentChain'/.test(SRC),
  'rows[0] would adopt whichever link the server listed first');

if (failures) {
  console.error(`\nprogressProvenance: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
