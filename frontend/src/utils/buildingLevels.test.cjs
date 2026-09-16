/**
 * WHERE ON THE BUILDING — the chips, and the form that makes them possible.
 *
 * ── THE MEASURED STATE THIS ENDS ────────────────────────────────────────────
 *
 * The daily jobsite log asked "where on site?" and offered ONE chip:
 * "Somewhere else". Not a rendering fault — the chips were derived from
 * `building_stories`, and NOTHING IN THE APP HAS EVER WRITTEN THAT FIELD. It
 * appears in three backend models and in two reads on the log screen, and in
 * no form. On production, 588 Thomas and 857 Prescott both carry
 * building_stories = null, so `floorChips` correctly returned [] on every
 * project this product has.
 *
 * The old behaviour was honest and useless. Inventing a fixed list of jobsite
 * areas would have been neither — it would have put made-up terms into a legal
 * record. The answer is to ASK, so this file covers both halves: the question
 * (the project form) and the answer (the chips).
 *
 * ── WHY FOUR FLAGS AND NOT ARITHMETIC ───────────────────────────────────────
 *
 * A storey count cannot say whether there is a cellar under the building or a
 * bulkhead over it: a 4-storey building with a cellar and one without both say
 * 4. Sub-cellar, cellar, mezzanine and roof/bulkhead are therefore asked, and
 * an UNSET flag offers no chip rather than asserting the level does not exist.
 *
 * Run:  node src/utils/buildingLevels.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const eq = (a, b, label) => {
  const same = JSON.stringify(a) === JSON.stringify(b);
  ok(same, `${label}${same ? '' : ` — got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`}`);
};

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

// ── The model, EXECUTED ─────────────────────────────────────────────────────
const raw = read('src', 'utils', 'dailyJobsiteModel.js');
const body = raw
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (const|function|let) /gm, '$1 ');
// eslint-disable-next-line no-new-func
const M = new Function(`
  ${body}
  return { buildingLevelChips, floorOrdinal, MAX_FLOOR_CHIPS,
           DEFAULT_LEVEL_CHIPS, levelsAreDefault, locationChipsFor };
`)();

const labels = (project) => M.buildingLevelChips(project).map((c) => c.label);
const ids = (project) => M.buildingLevelChips(project).map((c) => c.id);

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── Nothing set: the DEFAULT four, and they say so ──');

// THE EMPTY LIST WAS THE HONEST ANSWER AND IT WAS USELESS. On a project with no
// storey count the CP's only chip was "Somewhere else", and that is every live
// project this product has. Operator ruling: default to these four.
const DEFAULTS = ['Foundation', '1st Floor', '2nd Floor', '3rd Floor'];

eq(labels({}), DEFAULTS, 'a project nobody has answered for gets the default four');
eq(labels(null), DEFAULTS, 'a null project does not throw');
eq(labels(undefined), DEFAULTS, 'an undefined project does not throw');
eq(labels('nonsense'), DEFAULTS, 'a non-object does not throw');
eq(labels({ building_stories: null }), DEFAULTS,
  'a null storey count is no answer, so it gets the default list');
eq(labels({ building_stories: 0 }), DEFAULTS,
  'zero storeys is not a building; the default list, not zero chips');
eq(labels({ building_stories: -3 }), DEFAULTS,
  'a negative storey count cannot render a negative list');
eq(labels({ building_stories: 'four' }), DEFAULTS,
  'a storey count that is not a number falls back rather than making NaN chips');

ok(M.buildingLevelChips({}).every((c) => c.isDefault === true),
  'every default chip SAYS it is a default, so the screen can tell the CP the '
  + 'app is offering a usual list rather than reading his drawings');
ok(M.levelsAreDefault(M.buildingLevelChips({})),
  'levelsAreDefault is true for an unanswered project');
ok(!M.levelsAreDefault(M.buildingLevelChips({ building_stories: 2 })),
  'and false the moment somebody answers');
ok(!M.levelsAreDefault([]), 'an empty list is not "a default list"');

eq(ids({}), ['foundation', 'floor_1', 'floor_2', 'floor_3'],
  'THE DEFAULT IDS ARE THE REAL IDS. floor_1 from the default set is the same '
  + 'chip as floor_1 from a confirmed building, so answering the question '
  + 'later does not orphan what was already logged against it');

// A DEFAULT IS NOT AN ANSWER, and the ruling is explicit that it must never
// become one: chips only, never building_stories, never the §3310 class.
ok(!/DEFAULT_LEVEL_CHIPS/.test(
  raw.slice(raw.indexOf('export function buildingLevelChips'),
    raw.indexOf('export const levelsAreDefault'))
    .replace(/return out\.length > 0[\s\S]*$/, '')),
'nothing upstream of the fallback reads the default set — it is the last '
  + 'line of the function and cannot leak into a stored field');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── An UNSET flag is "nobody said", never "there is no cellar" ──');

eq(labels({ building_stories: 2 }), ['1st Floor', '2nd Floor'],
  'storeys alone give floors alone');
ok(!ids({ building_stories: 2 }).includes('cellar'),
  'an unanswered cellar flag adds no cellar chip');
eq(labels({ building_stories: 2, has_cellar: false }), ['1st Floor', '2nd Floor'],
  'an explicit false is the same as unset ON SCREEN — no chip either way');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── Order is bottom to top, and it is the operator\'s order ──');

const ALL = {
  building_stories: 3,
  has_sub_cellar: true,
  has_cellar: true,
  has_mezzanine: true,
  has_roof_bulkhead: true,
};
eq(labels(ALL),
  ['Sub-cellar', 'Cellar', '1st Floor', '2nd Floor', '3rd Floor', 'Mezzanine', 'Roof'],
  'sub-cellar, cellar, 1st..Nth, mezzanine, roof');
eq(ids(ALL),
  ['sub_cellar', 'cellar', 'floor_1', 'floor_2', 'floor_3', 'mezzanine', 'roof'],
  'and the ids match the labels position for position');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── Only what is set, in every combination ──');

eq(labels({ has_cellar: true }), ['Cellar'],
  'A CELLAR WITH NO STOREY COUNT STILL GETS A CHIP. The levels are four '
  + 'independent facts; gating them on the number would have made the storey '
  + 'field a prerequisite for answering a different question');
eq(labels({ has_roof_bulkhead: true }), ['Roof'],
  'a roof on its own');
eq(labels({ has_sub_cellar: true, has_cellar: true }), ['Sub-cellar', 'Cellar'],
  'below-grade only, still bottom to top');
eq(labels({ building_stories: 1, has_mezzanine: true }),
  ['1st Floor', 'Mezzanine'],
  'a mezzanine sits above the numbered floors, as ruled');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── Ordinals: the teens are why this is a function ──');

eq([1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 100, 101, 111, 112]
  .map(M.floorOrdinal),
['1st', '2nd', '3rd', '4th', '10th', '11th', '12th', '13th', '14th',
  '20th', '21st', '22nd', '23rd', '100th', '101st', '111th', '112th'],
'11, 12 and 13 take "th" although they end in 1, 2 and 3');
eq(M.floorOrdinal('x'), '', 'a non-number ordinal is empty, not "NaNth"');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── The cap, and what it protects ──');

ok(M.buildingLevelChips({ building_stories: 5000 }).length === M.MAX_FLOOR_CHIPS,
  `a typo in the stories field cannot render more than ${M.MAX_FLOOR_CHIPS} floor chips onto a phone`);
eq(M.buildingLevelChips({ building_stories: M.MAX_FLOOR_CHIPS }).length,
  M.MAX_FLOOR_CHIPS, 'and a building exactly at the cap loses nothing');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── FILED RECORDS ARE NOT RE-INTERPRETED ──');

eq(ids({ building_stories: 3 }), ['floor_1', 'floor_2', 'floor_3'],
  'the floor ids are the SAME ids the storey-only version wrote. A filed log '
  + 'carrying location_ids: ["floor_3"] still means the third floor');

// The label DID change (`Floor 3` -> `3rd Floor`), and that is safe for one
// reason, asserted here so nobody removes it: the screen composes the LABEL
// into `work_locations` at selection time, so what a filed record says is the
// text as it stood on the day. Nothing re-renders an old record from its ids.
const SCREEN = read('app', 'logbooks', 'daily_jobsite.jsx');
ok(/work_locations: composeSelection\(ids, mergedLocationLabels\(a\)\)/.test(SCREEN),
  'the screen composes the label into work_locations at selection time, so a '
  + 'label change cannot rewrite a document that is already signed');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── The screen reads the PROJECT, not one integer ──');

ok(/buildingLevelChips/.test(SCREEN),
  'the log screen uses the shared derivation');
ok(!/floorChips/.test(SCREEN),
  'and the local storey-only deriver is gone, not shadowed');
ok(/const locationChips = useMemo\(\(\) => locationChipsFor\(buildingLevels\)/.test(SCREEN),
  'the chips are memoised off the whole level block');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── THE SUPER\'S OWN VOCABULARY, remembered like an activity ──');

const WITH_TYPED = {
  building_stories: 2,
  remembered_other_locations: ['Cellar', 'Shaft 3'],
};
eq(M.locationChipsFor(WITH_TYPED).map((c) => c.label),
  ['1st Floor', '2nd Floor', 'Cellar', 'Shaft 3'],
  'typed levels follow the building\'s own, they do not interleave with them');
ok(M.locationChipsFor(WITH_TYPED).slice(2).every((c) => c.remembered === true),
  'and they are marked, because a level somebody typed and a level read off '
  + 'the project record are different kinds of claim');
eq(M.locationChipsFor(WITH_TYPED).map((c) => c.id),
  ['floor_1', 'floor_2', 'other:Cellar', 'other:Shaft 3'],
  'a typed one keeps the other: prefix — the same id the log already writes, '
  + 'so a label typed today ranks as itself tomorrow');
eq(M.locationChipsFor({ has_cellar: true, remembered_other_locations: ['cellar'] })
  .map((c) => c.label), ['Cellar'],
'a typed level that DUPLICATES a stored one is dropped, case-insensitively — '
  + 'two Cellar chips on one card is the app arguing with itself');
eq(M.locationChipsFor({ remembered_other_locations: ['Pump room'] })
  .map((c) => c.label), [...DEFAULTS, 'Pump room'],
'typed levels sit alongside the DEFAULTS too, which is the whole point: the '
  + 'super fixes the list himself on a project the office never filled in');
eq(M.locationChipsFor({ remembered_other_locations: ['', '  ', null, 7] })
  .map((c) => c.label), DEFAULTS,
'blank and non-string entries are dropped rather than rendered as empty chips');
eq(M.locationChipsFor(null).map((c) => c.label), DEFAULTS,
  'and it never throws on a missing project');

// THE WRITE HALF. It rides the logbook save and cannot reach the project's
// classification inputs — asserted against the server, because that is the
// claim that matters and it is not visible from here.
const SERVER_SRC = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8',
).split('\r\n').join('\n');
ok(/PROJECT_OTHER_LOCATIONS_FIELD = "remembered_other_locations"/.test(SERVER_SRC),
  'the server names the field');
ok((SERVER_SRC.match(/await _remember_other_locations\(/g) || []).length === 3,
  'it is called on all THREE logbook write paths, exactly as '
  + '_remember_other_activities is — a create, a create-or-update and a PUT');
const REMEMBER_FN = SERVER_SRC.slice(
  SERVER_SRC.indexOf('async def _remember_other_locations'),
  SERVER_SRC.indexOf('async def _remember_other_activities'));
ok(!/building_stories|project_class|classify_project/.test(REMEMBER_FN),
  'A CP CANNOT CHANGE WHAT §3310 REQUIRES OF THE JOB BY NAMING A FLOOR. The '
  + 'write touches one $addToSet field and nothing else, which is the whole '
  + 'reason it is this mechanism and not a permission on the project');
ok(/\$addToSet/.test(REMEMBER_FN),
  'and it adds rather than replaces, so two CPs on one project do not '
  + 'overwrite each other');
ok(/setBuildingLevels\(projectData \|\| null\)/.test(SCREEN),
  'the full project load sets it');
ok(/if \(p\) setBuildingLevels\(p\)/.test(SCREEN),
  'AND SO DOES THE DRAFT PATH. loadProjectShell used to set the storey count '
  + 'only `if (p?.building_stories != null)`, which on a building with a '
  + 'cellar and no storey count would have withheld the cellar chip from every '
  + 'CP who reopened a draft');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── The question is ASKED, and it has an entry point ──');

const FORM = read('app', 'projects', 'index.jsx');
ok(/STORIES ABOVE GROUND/.test(FORM), 'the project form asks for a storey count');
['has_sub_cellar', 'has_cellar', 'has_mezzanine', 'has_roof_bulkhead']
  .forEach((k) => ok(FORM.includes(k), `the form carries ${k}`));
ok(/function LevelFields/.test(FORM),
  'ONE field block, used by create and by edit — two copies is how the edit '
  + 'form quietly stops matching the create form');
ok(/openLevelEditor\(project\)/.test(FORM),
  'the card list opens the editor — a form nothing opens is a field nobody fills in');
ok(/onEditLevels=\{openLevelEditor\}/.test(FORM),
  'and so does the desktop table, which is the surface the office actually uses');
const TABLE = read('src', 'components', 'ProjectsTable.jsx');
ok(/onEditLevels/.test(TABLE) && /Building levels/.test(TABLE),
  'the table menu carries the row');
ok(/onEditLevels \?/.test(TABLE),
  'and it is optional, so a caller that does not pass it renders the menu it always did');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── A TOGGLE THAT CANNOT BE TURNED OFF IS A TRAP ──');

// levelPatch is a module-scope function in the screen file; it is read out and
// executed rather than grepped, because its whole content is a decision about
// which keys reach the wire.
const patchSrc = FORM.slice(FORM.indexOf('function levelPatch'));
const patchBody = patchSrc.slice(0, patchSrc.indexOf('\n}\n') + 3);
const TOGGLES = "const LEVEL_TOGGLES = [{key:'has_sub_cellar'},{key:'has_cellar'},"
  + "{key:'has_mezzanine'},{key:'has_roof_bulkhead'}];";
// eslint-disable-next-line no-new-func
const levelPatch = new Function(`${TOGGLES}\n${patchBody}\nreturn levelPatch;`)();

eq(levelPatch({ building_stories: '', has_cellar: false }), {},
  'CREATE sends nothing for an untouched form. A false would record an answer '
  + 'nobody gave, and None is the only value update_project drops');
eq(levelPatch({ building_stories: '4', has_cellar: true }),
  { building_stories: 4, has_cellar: true },
  'create sends the number as a number and only the flags that are on');
eq(levelPatch({ building_stories: '', has_cellar: false }, true),
  {
    has_sub_cellar: false,
    has_cellar: false,
    has_mezzanine: false,
    has_roof_bulkhead: false,
  },
  'EDIT sends every flag including the off ones — otherwise a cellar switched '
  + 'on by mistake could never be switched off again');
eq(levelPatch({ building_stories: '0' }, true).building_stories, undefined,
  'a zero storey count is not sent; "nobody said" and "zero storeys" are '
  + 'different facts and only one of them is ever true of a building');
eq(levelPatch({ building_stories: 'abc' }, true).building_stories, undefined,
  'and neither is a non-number');

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── THE FOUR FLAGS ARE NOT §3310 INPUTS ──');

const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8',
).split('\r\n').join('\n');
const classLine = SERVER.split('\n').find((l) => l.includes('classification_fields = {'));
ok(Boolean(classLine), 'the re-classification field set is findable');
['has_sub_cellar', 'has_cellar', 'has_mezzanine', 'has_roof_bulkhead']
  .forEach((k) => ok(!classLine.includes(k),
    `${k} does not re-classify the project — a cellar does not make a building major`));
ok(classLine.includes('building_stories'),
  'but building_stories DOES, which is why the form says so under the field');
ok(/10 or more makes this Major A and adds two required daily/.test(FORM.replace(/\s+/g, ' ')),
  'and the form tells the admin, because a number that silently adds two '
  + 'required daily logs is not a number you let someone type blind');
ok(/If an admin set the class by hand, saving a number here replaces it with the measured one/
  .test(FORM.replace(/\s+/g, ' ')),
  'AND IT SAYS SO IN THE OTHER DIRECTION TOO. 8 Walworth Street is stored '
  + 'major_b on production with no storey count, no height and no footprint — '
  + 'set by hand. The edit form sends no project_class, so the server '
  + 're-derives from the measurement, which on that project DROPS two required '
  + 'daily logs. The form warns before the save, not after');

// ═══════════════════════════════════════════════════════════════════════════
console.log(`\n${failed === 0 ? 'ALL PASS' : 'FAILURES'} — ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
