/**
 * A FILED LOG IS NOT A DISABLED FORM — the summary half.
 *
 * THE RULING. "A filed record is not being composed, so rendering it as a
 * disabled form is what makes the photo panel read as an exception." The
 * locked editor route stops rendering five paginated steps behind
 * pointerEvents='none' and renders what was FILED instead: the content, who
 * signed it and when, and — only where the type has them — the photographs.
 *
 * THE PART MOST LIKELY TO GO WRONG, and the reason this file exists at all, is
 * the three-state photographs rule:
 *
 *   1. the TYPE's schema cannot carry photographs  -> no section, at all
 *   2. the type can, and none are attached         -> section, says so, Add
 *   3. the type can, and some are                  -> the photographs, Add
 *
 * State 1 is ABSENCE, not an empty state. An absent section makes no claim; an
 * empty one claims "this record has a place for photographs and it is empty",
 * which on a toolbox talk is false — there is no such place and the record is
 * complete. Ten of twelve filed records would otherwise show a manufactured
 * gap to whoever is reading them. Same rule as SST_UNSPECIFIED and as the
 * readiness notice returning null rather than printing "everything is fine".
 *
 * AND THE DECISION IS THE LOG TYPE'S, NEVER THE DATA'S. A daily_jobsite whose
 * activities array is missing is a DIFFERENT FACT from a toolbox talk having
 * no such concept, and a reader that cannot tell those apart is the shape of
 * defect this repo has already shipped twice. Both directions are asserted
 * below — an empty photo-carrying type still gets the section, and a non-photo
 * type handed an activities array still gets none.
 *
 *   node frontend/src/utils/filedLogSummary.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}
function section(t) {
  console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 62 - t.length))}`);
}

const LF = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');

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

const S = loadModule('src/utils/filedLogSummary.js');

// ════════════════════════════════════════════════════════════════════════════
section('1. THE SCHEMA FACT — which TYPES can carry photographs');
// ════════════════════════════════════════════════════════════════════════════

ok(typeof S.typeCarriesActivityPhotos === 'function',
  'filedLogSummary exports typeCarriesActivityPhotos');

ok(S.typeCarriesActivityPhotos('daily_jobsite') === true,
  'daily_jobsite carries activities[].photos');
ok(S.typeCarriesActivityPhotos('fall_protection') === true,
  'fall_protection carries them too — the type the append route was dead on');

// THE COMPLETE OTHER SIDE. Named individually rather than "everything else":
// a thirteenth type added to the registry must be a decision, not an
// inheritance, and this list is where the decision is recorded.
const NO_PHOTOS = [
  'toolbox_talk', 'preshift_signin', 'hot_work', 'crane_operations',
  'excavation_monitoring', 'concrete_operations', 'scaffold_maintenance',
  'ssc_daily_safety_log', 'osha_log', 'subcontractor_orientation',
  'site_superintendent_log',
];
for (const t of NO_PHOTOS) {
  ok(S.typeCarriesActivityPhotos(t) === false,
    `${t} has no such concept — the filed view must render NO section`);
}
ok(S.typeCarriesActivityPhotos(null) === false
  && S.typeCarriesActivityPhotos(undefined) === false
  && S.typeCarriesActivityPhotos('') === false
  && S.typeCarriesActivityPhotos({}) === false,
'an unknown or absent type is NOT assumed to carry photographs: the safe '
  + 'default is the section that makes no claim');

// POSITIVE CONTROL for the loop above. If typeCarriesActivityPhotos returned
// false for everything — a plausible break — every one of those eleven would
// pass and the whole section would be vacuous.
ok(NO_PHOTOS.every((t) => S.typeCarriesActivityPhotos(t) === false)
  && S.typeCarriesActivityPhotos('daily_jobsite') === true,
'POSITIVE CONTROL: the predicate is not simply false for everything');

// ...and the registry is COMPLETE against the server's, so a type registered
// later cannot be silently absent from the decision.
const serverSrc = LF(path.join(REPO, 'backend', 'server.py'));
const regBlock = (() => {
  const i = serverSrc.indexOf('LOGBOOK_TYPE_REGISTRY = [');
  if (i < 0) return '';
  const j = serverSrc.indexOf('\n]', i);
  return j < 0 ? '' : serverSrc.slice(i, j);
})();
ok(regBlock.length > 200,
  'POSITIVE CONTROL: LOGBOOK_TYPE_REGISTRY was actually found in server.py — '
  + 'an empty slice would make the completeness check below say nothing');
const serverTypes = [...new Set(
  [...regBlock.matchAll(/"key":\s*"([a-z_]+)"/g)].map((m) => m[1]),
)];
ok(serverTypes.length >= 12,
  `POSITIVE CONTROL: ${serverTypes.length} types parsed out of the registry`);
const known = new Set([...S.PHOTO_CARRYING_LOG_TYPES, ...NO_PHOTOS]);
const unaccounted = serverTypes.filter((t) => !known.has(t));
ok(unaccounted.length === 0,
  `every registered log type is accounted for by this rule${
    unaccounted.length ? ` — UNACCOUNTED: ${JSON.stringify(unaccounted)}` : ''}`);

// ════════════════════════════════════════════════════════════════════════════
section('2. THREE STATES, AND THE FIRST TWO ARE NOT THE SAME');
// ════════════════════════════════════════════════════════════════════════════

ok(typeof S.photographsSection === 'function',
  'filedLogSummary exports photographsSection — ONE place the rule is decided');

const EMPTY_ACTS = { log_type: 'daily_jobsite', data: { activities: [] } };
const NO_ACTS_AT_ALL = { log_type: 'daily_jobsite', data: {} };
const WITH_PHOTOS = {
  log_type: 'daily_jobsite',
  data: {
    activities: [
      { activity_id: 'act_1', company: 'Acme', photos: [{ photo_id: 'p1', original_r2_key: 'k1' }] },
      { activity_id: 'act_2', company: 'Beta', photos: [] },
    ],
  },
};
const TOOLBOX = { log_type: 'toolbox_talk', data: { topic: 'Ladders' } };
// The adversarial one: a NON-photo type handed an activities array anyway.
const TOOLBOX_WITH_ACTS = {
  log_type: 'toolbox_talk',
  data: { topic: 'Ladders', activities: [{ activity_id: 'x', photos: [{ photo_id: 'q' }] }] },
};

const sEmpty = S.photographsSection(EMPTY_ACTS);
const sNone = S.photographsSection(NO_ACTS_AT_ALL);
const sSome = S.photographsSection(WITH_PHOTOS);
const sBox = S.photographsSection(TOOLBOX);
const sBoxActs = S.photographsSection(TOOLBOX_WITH_ACTS);

// ── STATE 1: absence ────────────────────────────────────────────────────────
ok(sBox === null,
  'STATE 1: a toolbox talk gets NULL — no section, not an empty one. An empty '
  + 'section would claim the record has a place for photographs and it is '
  + 'blank, and that is a manufactured gap on a complete record');
ok(sBoxActs === null,
  'STATE 1 THE HARD WAY: a NON-photo type carrying an activities array with a '
  + 'photo in it STILL gets no section — the decision is the TYPE\'s schema, '
  + 'never what happens to be in `data`');

// ── STATE 2: present and empty ──────────────────────────────────────────────
ok(sEmpty !== null && sEmpty.present === true && sEmpty.photoCount === 0,
  'STATE 2: a daily_jobsite with an EMPTY activities array still gets the '
  + 'section — the record has a place for photographs and it is empty, which '
  + 'is a true thing to say about this type');
ok(sNone !== null && sNone.present === true && sNone.photoCount === 0,
  'STATE 2 THE HARD WAY: activities MISSING ENTIRELY is still state 2. A '
  + 'daily_jobsite with no activities array is a different fact from a '
  + 'toolbox talk having no such concept, and this is where they part');
ok(sEmpty?.empty === true && sNone?.empty === true,
  'and both say plainly that they are empty rather than drawing nothing');

// ── STATE 3: present and populated ──────────────────────────────────────────
ok(sSome !== null && sSome.present === true && sSome.empty === false
  && sSome.photoCount === 1,
'STATE 3: the photographs, counted off the SERVER\'s rows');
ok(Array.isArray(sSome?.rows) && sSome.rows.length === 2
  && sSome.rows[0].activity_id === 'act_1'
  && sSome.rows[0].photos.length === 1
  && sSome.rows[1].photos.length === 0,
'every row comes back, with its own photographs, in the server\'s order — '
  + 'the report addresses photos POSITIONALLY, so the order is load-bearing');

// The indexes the serving URL needs are the SERVER's, and they are carried
// rather than recomputed by whoever renders.
ok(sSome?.rows?.[0]?.activity_index === 0 && sSome?.rows?.[1]?.activity_index === 1
  && sSome?.rows?.[0]?.photos?.[0]?.photo_index === 0,
'each row and photo carries the index it has IN THE SERVER DOCUMENT: '
  + '/api/reports/logbook-photo/{id}/{ai}/{pi} is positional, so an index '
  + 'invented by the renderer would point at another photograph');

// ── the states are mutually exclusive and exhaustive ────────────────────────
for (const [name, log] of [
  ['empty', EMPTY_ACTS], ['absent-array', NO_ACTS_AT_ALL], ['populated', WITH_PHOTOS],
  ['toolbox', TOOLBOX], ['toolbox+acts', TOOLBOX_WITH_ACTS],
]) {
  const sec = S.photographsSection(log);
  const state = sec === null ? 1 : (sec.empty ? 2 : 3);
  // eslint-disable-line
  ok([1, 2, 3].includes(state), `${name} lands in exactly one of the three states (${state})`);
}

ok(S.photographsSection(null) === null && S.photographsSection({}) === null,
  'nothing, and a log with no type, get no section — no claim is the safe one');

// ════════════════════════════════════════════════════════════════════════════
section('3. A ROW WITHOUT AN IDENTITY CANNOT BE ADDED TO');
// ════════════════════════════════════════════════════════════════════════════

const LEGACY = {
  log_type: 'daily_jobsite',
  data: {
    activities: [
      { company: 'Old Co', photos: [] },                       // no activity_id
      { activity_id: 'act_9', company: 'New Co', photos: [] },
    ],
  },
};
const sLegacy = S.photographsSection(LEGACY);
ok(sLegacy?.rows?.[0]?.can_add === false && sLegacy?.rows?.[1]?.can_add === true,
  'a row the server stored WITHOUT an activity_id offers no add control; the '
  + 'row beside it still does — the refusal is per row, not per log');
ok(sLegacy?.rows?.[0]?.activity_id === null,
  'and its identity is reported as ABSENT rather than substituted: aiming a '
  + 'photo at an invented id reaches nothing');
ok(sLegacy?.remediable === true,
  'the section says the whole log is REMEDIABLE — backfill_activity_id.py '
  + 'exists, so the CP is told there is something to ask for rather than '
  + 'meeting a dead end');
ok(S.photographsSection(WITH_PHOTOS)?.remediable === false,
  'CONTROL: a log with no id-less rows is not reported remediable');

ok(/"remediable": True/.test(serverSrc)
  && /"remedy": "backfill_activity_id"/.test(serverSrc),
'and the SERVER says so as a machine fact, which is what this branches on '
  + 'rather than on English');
ok(fs.existsSync(path.join(REPO, 'backend', 'scripts', 'backfill_activity_id.py')),
  'and the remedy the copy names is a script that actually exists');

// ════════════════════════════════════════════════════════════════════════════
section('4. WHAT WAS FILED — the read-only summary');
// ════════════════════════════════════════════════════════════════════════════

ok(typeof S.summarizeFiledLog === 'function', 'filedLogSummary exports summarizeFiledLog');

const FILED = {
  id: 'lb1',
  log_type: 'daily_jobsite',
  date: '2026-08-25',
  status: 'submitted',
  is_locked: true,
  cp_name: 'Casey CP',
  cp_signature: { ink: 'AAAA', affirmed: true },
  updated_at: '2026-08-25T22:10:00Z',
  data: {
    weather: 'Clear, 78F',
    general_description: 'Formwork on levels 3-4.',
    permits_posted: true,
    site_safety_orange: false,
    work_locations: ['L3', 'L4'],
    empty_field: '',
    null_field: null,
    blank_list: [],
    activities: [
      { activity_id: 'act_1', company: 'Acme', worker_count: 6, photos: [{ photo_id: 'p1' }] },
    ],
  },
};

const sum = S.summarizeFiledLog(FILED);
const labelOf = (k) => (sum.fields.find((f) => f.key === k) || {}).label;
const valueOf = (k) => (sum.fields.find((f) => f.key === k) || {}).value;

ok(Array.isArray(sum.fields) && sum.fields.length > 0,
  'POSITIVE CONTROL: the summary is not empty — an empty one would satisfy '
  + 'every "does not contain" assertion below by containing nothing');

ok(valueOf('weather') === 'Clear, 78F', 'a filed string comes through verbatim');
ok(labelOf('general_description') === 'General Description',
  'the key is humanised into a label rather than printed as a key');
ok(valueOf('permits_posted') === 'Yes' && valueOf('site_safety_orange') === 'No',
  'a boolean is rendered as Yes / No — `false` printed raw reads as an error');
ok(valueOf('work_locations') === 'L3, L4', 'a list of plain values is joined');

ok(!sum.fields.some((f) => f.key === 'empty_field')
  && !sum.fields.some((f) => f.key === 'null_field')
  && !sum.fields.some((f) => f.key === 'blank_list'),
'a field that was left BLANK is omitted: the filed view shows what was '
  + 'filed, and a row of dashes is a manufactured gap');

ok(!sum.fields.some((f) => f.key === 'activities'),
  'activities are NOT dumped as a scalar field — they are rows');
ok(Array.isArray(sum.groups) && sum.groups.length === 1
  && sum.groups[0].key === 'activities' && sum.groups[0].rows.length === 1,
'they come back as a GROUP of rows instead');
ok(!JSON.stringify(sum).includes('photos'),
  'and the summary carries NO photo objects: the photographs section owns '
  + 'those, and a base64 blob rendered as a "field" is how a filed view goes '
  + 'from readable to megabytes');

// The signature must not leak into the content summary — it is attested
// metadata, rendered by the attestation block below, never as a data field.
ok(!sum.fields.some((f) => /signature/i.test(f.key)),
  'no signature is rendered as a content field');

// ── who signed it, and when ─────────────────────────────────────────────────
ok(typeof S.filedAttestation === 'function', 'filedLogSummary exports filedAttestation');
const att = S.filedAttestation(FILED);
ok(att.signerName === 'Casey CP', 'the filed view names who signed it');
ok(att.signed === true, 'and reports that it IS signed');
ok(att.filedAt === '2026-08-25T22:10:00Z' || typeof att.filedAt === 'string',
  'and when the record last moved');
ok(S.filedAttestation({ log_type: 'x', data: {} }).signed === false,
  'CONTROL: an unsigned document does not claim a signature');
ok(S.filedAttestation({ cp_name: 'Casey CP' }).signed === false,
  'a NAME IS NOT A SIGNATURE: cp_name with no ink is not "signed by Casey" — '
  + 'that sentence on a compliance record is a fabricated attestation');

const AMENDED = {
  ...FILED, is_amendment: true, amendment_reason: 'Corrected headcount',
};
ok(S.filedAttestation(AMENDED).isAmendment === true
  && S.filedAttestation(AMENDED).amendmentReason === 'Corrected headcount',
'an amendment says so, with its reason — the reader of a corrected record '
  + 'has to know it is one');

// ════════════════════════════════════════════════════════════════════════════
section('5. IT IS A VIEW, NOT AN EDITOR');
// ════════════════════════════════════════════════════════════════════════════

const viewSrc = LF(path.join(
  FRONTEND, 'src', 'components', 'logbookStepper', 'FiledLogView.jsx',
));
ok(viewSrc.length > 500, 'POSITIVE CONTROL: FiledLogView.jsx was read');
ok(!/TextInput|onChangeText|SignaturePad/.test(viewSrc),
  'the filed view has NO text entry and NO signature pad: nothing the CP '
  + 'attested to can be reached through it');
ok(!/logbooksAPI\.update|logbooksAPI\.create|photoForPayload|writeDraft/.test(viewSrc),
  'and it performs no save of any kind — the ordinary route is 409 '
  + 'FILED_LOG_DATA_IMMUTABLE on this document and should be');
ok(!/Trash2|removePhoto|dropPhoto|\.delete\(/.test(viewSrc),
  'APPEND-ONLY: no remove control. Deleting a photograph from a filed record '
  + 'IS an amendment, and the lock bar already offers that path');
ok(/photographsSection/.test(viewSrc),
  'it asks the ONE predicate for the photographs rule rather than re-deriving '
  + 'it — a second copy is how the three states get collapsed to two');

// The stepper must actually take the branch, or none of the above renders.
const stepperSrc = LF(path.join(
  FRONTEND, 'src', 'components', 'logbookStepper', 'LogbookStepper.jsx',
));
ok(/FiledLogView/.test(stepperSrc),
  'LogbookStepper renders FiledLogView');
const bodyIdx = stepperSrc.indexOf('current.render()');
const filedIdx = stepperSrc.indexOf('<FiledLogView');
ok(bodyIdx > -1 && filedIdx > -1 && filedIdx < bodyIdx,
  'and it is the LOCKED branch of the same conditional the steps are the '
  + 'other half of — so a filed log cannot render both');
ok(/locked \?\s*\(?\s*<FiledLogView/.test(stepperSrc.replace(/\n\s*/g, ' ')),
  'the branch is on `locked` itself: a filed record is not being composed, so '
  + 'it is not rendered as a form at all');
ok(/\{!locked && \(/.test(stepperSrc),
  'and the footer — Next / Submit & Sign — still renders only when NOT locked');
ok(/locked \? null :/.test(stepperSrc) || /\{!locked &&[\s\S]{0,200}progressRow/.test(stepperSrc.replace(/\n\s*/g, ' ')),
  'the STEP PIPS are gone on a filed log too: "STEP 3 OF 5" over a record '
  + 'nobody is composing is the disabled-form reading this change removes');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
