/**
 * app/site/logbooks.jsx — the inspector screen's document renderers.
 *
 * WHAT WAS WRONG
 *   renderLogContent branched on three log types and returned the literal
 *   string "No data available" for everything else, and LOG_TABS listed the
 *   same three — while the tab filter is `l.log_type === activeTab`. So
 *   hot_work, crane_operations, excavation_monitoring, concrete_operations,
 *   scaffold_maintenance, ssc_daily_safety_log, osha_log and
 *   subcontractor_orientation were fetched, cached to the device, and had no
 *   tab that could show them at all.
 *
 * WHAT IS ASSERTED
 *   Every type has a tab; every type renders the REAL payload keys the editor
 *   writes; crew_id renders and crew_name does not.
 *
 *   ABSENCE, in the two forms it takes:
 *     (a) a FIELD missing from a section that IS rendered reads exactly
 *         "— Not recorded" — the words server.py generate_combined_report
 *         already prints for the same fact, so one record does not read
 *         differently on two compliance surfaces. NO OTHER placeholder may
 *         appear: every remaining "N/A" / bare dash / "undefined" is asserted
 *         absent, so an absence can never pass for a value.
 *     (b) a ROW missing from a repeating list is DROPPED. An untouched EMPTY_*
 *         seed row must NOT come back as a row of "— Not recorded" — that
 *         would invent a record of work nobody logged.
 *   And false / 0 are captured VALUES, never absences.
 *
 * HOW
 *   The repo has no JS test runner (see RiskScoreCircle.bandFor.test.cjs).
 *   The renderers are closures inside the screen component, so the REAL
 *   source block is sliced out, transpiled with the repo's own babel, and run
 *   against a tiny createElement that builds a plain tree — the text asserted
 *   below is the text the screen produces, never a hand-copy. The translator
 *   is the REAL one over the REAL src/i18n catalogue, so a renamed or missing
 *   key fails here.
 *
 * Run:  node src/utils/logbookViewRenderers.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'site', 'logbooks.jsx');
const I18N = path.join(FRONTEND, 'src', 'i18n');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The screens are CRLF in this repo; normalise so the slice boundaries hold.
const src = fs.readFileSync(SCREEN, 'utf8').split('\r\n').join('\n');

// ── The REAL English catalogue, loaded the way i18n.test.cjs loads it ────────
function loadCatalogue(file) {
  const stripped = fs.readFileSync(path.join(I18N, file), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  return new Function(`${stripped}; return __default;`)();
}
const EN = loadCatalogue('en.js');
const ES = loadCatalogue('es.js');
const t = (key) => (
  Object.prototype.hasOwnProperty.call(EN.logbookView, key) ? EN.logbookView[key] : key
);
// THE SECOND NAMESPACE THE SCREEN READS. renderFallProtection takes the
// standard notice and its Yes/No pair from `fallProtection` rather than
// re-wording them under `logbookView`, so the notice on the tablet is the same
// string fallProtectionModel.test.cjs holds equal to server.py's
// FALL_PROTECTION_NOTICE. Resolved through the REAL catalogue here too, so a
// renamed key fails in this file rather than rendering its own name.
const tFp = (key) => (
  Object.prototype.hasOwnProperty.call(EN.fallProtection, key) ? EN.fallProtection[key] : key
);

// ── Slice the renderer block out of the screen ──────────────────────────────
const START = '  const SignatureBlock = ({ signature, label }) => {';
const END = "    return <Text style={s.logField}>No data available</Text>;\n  };\n";
const from = src.indexOf(START);
const to = src.indexOf(END);
if (from < 0 || to < 0) {
  throw new Error('renderer block not found in app/site/logbooks.jsx — this test is stale');
}
const block = src.slice(from, to + END.length);

const compiled = babel.transformSync(block, {
  filename: 'logbooks-renderers.jsx',
  babelrc: false,
  configFile: false,
  presets: [],
  plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
    { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }]],
}).code;

// ── A createElement that builds a plain tree, and a text collector ──────────
const React = {
  Fragment: function Fragment(props) { return props.children; },
  createElement: (type, props, ...children) => ({
    __el: true, type, props: props || {}, children,
  }),
};

function collect(node, out) {
  if (node === null || node === undefined || node === false || node === true) return;
  if (Array.isArray(node)) { node.forEach((n) => collect(n, out)); return; }
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return; }
  if (!node.__el) return;
  const kids = node.children.length ? node.children : node.props.children;
  if (typeof node.type === 'function') {
    collect(node.type({ ...node.props, children: kids }), out);
    return;
  }
  collect(kids, out);
}

const text = (node) => {
  const out = [];
  collect(node, out);
  return out.join(' | ');
};

// ── The REAL headcount formatter, not a stub ───────────────────────────────
// This renderer prints a crew row an INSPECTOR reads off the gate tablet, and
// what it must print is the number AND who supplied it. Stubbing this would
// leave the file asserting that a headcount appears while staying blind to
// whether it is attributed, which is the whole point of the cell.
const MODEL = path.join(FRONTEND, 'src', 'utils', 'dailyJobsiteModel.js');
const _model = {};
// eslint-disable-next-line no-new-func
new Function('exports', 'module', 'require', babel.transformSync(
  fs.readFileSync(MODEL, 'utf8'),
  {
    filename: MODEL,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  },
).code)(_model, { exports: _model }, require);

// ── Stubs for everything the block closes over ──────────────────────────────
const styleProxy = new Proxy({}, { get: () => ({}) });
const Icon = function IconStub() { return null; };
const NAMES = ['View', 'Text', 'Image', 'React', 's', 't', 'tFp', 'colors', 'semantic',
  'spacing', 'withAlpha', 'rosterClock', 'logbookPhotoUri',
  'ShieldCheck', 'AlertTriangle', 'Truck', 'MapPin', 'ClipboardList', 'FileText',
  'Users', 'CheckCircle', 'BookOpen', 'Pen', 'CloudSun', 'Clock', 'Eye', 'Wrench',
  'headcountDisplay'];
const VALUES = {
  View: 'View', Text: 'Text', Image: 'Image', React,
  s: styleProxy, t, tFp,
  colors: { text: { primary: '#fff', secondary: '#eee', muted: '#999', subtle: '#666' } },
  semantic: { neutral: '#999', verified: '#0f0' },
  spacing: new Proxy({}, { get: () => 8 }),
  withAlpha: () => 'rgba(0,0,0,0.1)',
  rosterClock: (v) => (v ? String(v) : '—'),
  logbookPhotoUri: () => null,
  headcountDisplay: _model.headcountDisplay,
};
for (const n of NAMES) if (!(n in VALUES)) VALUES[n] = Icon;

// eslint-disable-next-line no-new-func
const R = new Function(...NAMES, `${compiled}\n return { renderLogContent };`)(
  ...NAMES.map((n) => VALUES[n]),
);
const render = (log) => text(R.renderLogContent(log));

const doc = (log_type, data, extra) => ({
  id: 'lb1', log_type, date: '2026-08-07', status: 'submitted',
  cp_name: 'Ada CP', data, ...(extra || {}),
});

// The ONE sanctioned way to say "the app has no value for this".
const NOT_RECORDED = t('fNotRecorded');
// An info-box field renders "Label: — Not recorded" in a single Text; a table
// cell is its own Text, so the collector joins it to its label with ' | '.
const fieldIsNotRecorded = (out, label) => out.includes(`${label}: ${NOT_RECORDED}`);
const rowIsNotRecorded = (out, label) => out.includes(`${label} | ${NOT_RECORDED}`);

// ════════════════════════════════════════════════════════════════════════════
//  0 — every REGISTERED type has a tab AND a render branch
// ════════════════════════════════════════════════════════════════════════════
// DERIVED FROM server.py, NOT HAND-COPIED — and that is the whole change.
// This block used to open on a hardcoded `ALL_TYPES` of eleven under the
// heading "every type has a tab, or the renderer is unreachable".
// `fall_protection`, the twelfth registered type, was missing from it for
// precisely the reason it was missing from LOG_TABS: nothing made adding a type
// update either list. So the check written to catch "a registered type with no
// tab" reported clean for the one type that had none — it could not see the
// thing it was for.
//
// submitSignatureGate.test.cjs derives LOGBOOK_TIMING_CLASS out of server.py
// for the same reason and did not drift. A list that CAN drift is not worth
// asserting against; this reads the registry itself.
const SERVER_SRC = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const REGISTRY_AT = SERVER_SRC.indexOf('LOGBOOK_TYPE_REGISTRY = [');
const REGISTRY = [...SERVER_SRC
  .slice(REGISTRY_AT, SERVER_SRC.indexOf('\n]\n', REGISTRY_AT))
  .matchAll(/^\s+"key": "([a-z_]+)",$/gm)].map((m) => m[1]);

// ── THE COUNT IS LOAD-BEARING, NOT DECORATION ──────────────────────────────
//
// Deriving on its own does not close the hole, it MOVES it. If server.py's
// registry formatting changes — a reordered key, a different quote style, the
// list rewritten as a dict — the regex above yields `[]`, and every assertion
// below then iterates an empty list and passes. That is the SAME vacuous pass
// that let the old hardcoded ALL_TYPES miss fall_protection, reappearing one
// level up and harder to see.
//
// This line is what fails instead. It is also the checkpoint that forces a
// THIRTEENTH type to be handled deliberately rather than inherited by
// omission: bump the number here only in the same change that gives the new
// type its tab, its label and its render branch. Bumping it on its own to get
// a red suite green is the bug this file exists to catch.
ok(REGISTRY.length === 12,
  `server.py registers 12 logbook types (got ${REGISTRY.length}: ${REGISTRY.join(', ') || 'NOTHING — the registry regex matched nothing'})`);

const tabKeys = [...src.matchAll(/\{ key: '([a-z_]+)', labelKey:/g)].map((m) => m[1]);
const noTab = REGISTRY.filter((k) => !tabKeys.includes(k));
ok(noTab.length === 0,
  `LOG_TABS covers every registered type — the tab filter is the only way in `
  + `(${tabKeys.length} tabs${noTab.length ? `, NO TAB FOR ${noTab.join(', ')}` : ''})`);
const strayTabs = tabKeys.filter((k) => !REGISTRY.includes(k));
ok(strayTabs.length === 0,
  `and no tab stands for a type the server does not register `
  + `(${strayTabs.join(', ') || 'none'}) — a tab that can never match `
  + `\`l.log_type === activeTab\` is an empty room with a door on it`);

// ── AND A BRANCH, WHICH IS THE HALF THE TAB CANNOT PROVE ───────────────────
//
// A tab with no renderLogContent branch is WORSE than no tab: the log opens
// and tells a DOB inspector "No data available" about a record the CP filed
// and signed. Both halves or neither.
//
// This RUNS the chain rather than reading it. "The branch exists" is exactly
// what was true of the eight types this file was originally written for while
// they rendered nothing, and it is what a source grep would have confirmed.
//
// ── WHAT THIS DOES **NOT** DO ──────────────────────────────────────────────
// It catches the DRIFT CLASS and nothing more: a registered type nobody wired
// up. A branch that reads the wrong payload keys, or half of them, or reads
// them off a shape no editor writes, passes here exactly as loudly as a
// correct one. The per-type assertions in section 1 below are hand-written,
// one set per type, and a new type still needs its own — this loop tells you
// the door opens, not that the right document is behind it.
for (const key of REGISTRY) {
  let out;
  try {
    out = render(doc(key, {}, { cp_name: null, cp_signature: null }));
  } catch (e) {
    out = `THREW ${e.message}`;
  }
  ok(out !== 'No data available' && !out.startsWith('THREW '),
    `renderLogContent has a branch for ${key} — it does not fall through to `
    + `the literal "No data available"${out.startsWith('THREW ') ? ` [${out}]` : ''}`);
}
ok(/l\.log_type === activeTab/.test(src),
  'the tab filter is still the single gate the tabs must satisfy (premise of the test above)');
const labelKeys = [...src.matchAll(/labelKey: '(\w+)'/g)].map((m) => m[1]);
// FLIPPED, not dropped. `logbookView` is EN-only by ruling: it renders FILED
// logs, read by a CP or a DOB inspector, and a DOB inspector reads English.
// The guard that matters is unchanged — every tab label must exist in the
// catalogue, so a renamed key still fails here. What is asserted about ES is
// now its ABSENCE, so a well-meant translation cannot quietly reappear.
ok(labelKeys.every((k) => k in EN.logbookView),
  `every tab label resolves in EN${labelKeys.filter((k) => !(k in EN.logbookView)).join(',')}`);
ok(ES.logbookView === undefined,
  'logbookView is absent from the ES catalogue — a filed log is an English record');

// ════════════════════════════════════════════════════════════════════════════
//  1 — each of the eight renders its REAL payload keys
// ════════════════════════════════════════════════════════════════════════════

// frontend/app/logbooks/hot_work.jsx:189-199 ; PRECAUTION_ITEMS :28-36
const hotWork = render(doc('hot_work', {
  work_type: 'Welding', location: 'west cellar', worker_name: 'bob welder',
  worker_cert_number: 'FDNY-P99-1234', start_time: '08:00', end_time: '12:00',
  fire_watch_end_time: '12:30', fire_watch_name: 'carl watch',
  precautions: { area_cleared: true, sprinklers_operational: false },
}));
ok(['Welding', 'west cellar', 'bob welder', 'FDNY-P99-1234', '08:00', '12:00',
  'carl watch', '12:30'].every((v) => hotWork.includes(v)),
  'hot_work: work_type / location / worker_name / worker_cert_number / times / fire_watch_name render');
ok(hotWork.includes(t('p_area_cleared')) && hotWork.includes(t('p_sprinklers_operational')),
  'hot_work: the precautions the document carries render, with their editor labels');
ok(rowIsNotRecorded(hotWork, t('p_permit_posted')),
  'hot_work: a precaution key the document does NOT carry reads "— Not recorded", never a silent ✕');
ok(hotWork.includes(t('hwFireWatchDefault')),
  'hot_work: fire_watch_end_time is labelled as the derived work-end + 30 min default');

// frontend/app/logbooks/crane_operations.jsx:174-181 ; :24-40 ; :42-47
const crane = render(doc('crane_operations', {
  crane_type: 'tower crane', crane_id: 'TC-14', operator_name: 'dana operator',
  operator_license: 'NYC-CO-8821',
  pre_operation_checklist: { wire_ropes: true, brakes: false },
  load_entries: [
    { time: '09:15', description: 'steel beam pick', load_weight: '4200', radius: '60' },
    { time: '', description: '', load_weight: '', radius: '' },
  ],
}));
ok(['tower crane', 'TC-14', 'dana operator', 'NYC-CO-8821', '09:15',
  'steel beam pick', '4200', '60'].every((v) => crane.includes(v)),
  'crane_operations: crane_type / crane_id / operator / license / load_entries render');
ok(crane.includes(`${t('c_wire_ropes')} | ✓`) && crane.includes(`${t('c_brakes')} | ✕`)
  && rowIsNotRecorded(crane, t('c_outriggers')),
  'crane_operations: a checked item, an explicit ✕, and an untouched one that reads "— Not recorded"');

// frontend/app/logbooks/excavation_monitoring.jsx:184-194 ; :27-31 ; :180-183
const exc = render(doc('excavation_monitoring', {
  excavation_depth: '14', soil_type: 'Hard Clay', protection_system: 'Shoring',
  groundwater_observed: true, atmospheric_testing: false,
  vibration_threshold: '0.50', vibration_current: '0.62',
  vibration_over_threshold: true,
  adjacent_buildings: [
    { address: '12 elm street', baseline_reading: '0.00', current_reading: '0.35', delta: '0.35' },
    { address: '', baseline_reading: '', current_reading: '' },
  ],
}));
ok(['14', 'Hard Clay', 'Shoring', '0.50', '0.62', '12 elm street', '0.35']
  .every((v) => exc.includes(v)),
  'excavation_monitoring: depth / soil / protection / vibration / adjacent_buildings render');
ok(exc.includes(t('exOver')),
  'excavation_monitoring: over-threshold status renders when BOTH readings are present');
ok(exc.includes(`${t('exGroundwater')}: ✓`) && exc.includes(`${t('exAtmospheric')}: ✕`),
  'excavation_monitoring: a captured FALSE boolean renders as ✕ (false is a value, not an absence)');

// frontend/app/logbooks/concrete_operations.jsx:171-179 ; :26-31 ; :33-37
const concrete = render(doc('concrete_operations', {
  pour_location: 'level 3 slab', concrete_supplier: 'ready mix co',
  mix_design: '4000PSI-A2', volume_ordered: '45', weather_conditions: 'Clear',
  temperature: '68',
  slump_tests: [
    { time: '10:05', value: '4.5', pass: true },
    { time: '13:40', value: '6.0', pass: false },
    { time: '', value: '', pass: null },
  ],
  formwork_checklist: { shores_plumb: true, no_gaps: false },
}));
ok(['level 3 slab', 'ready mix co', '4000PSI-A2', '45', 'Clear', '68',
  '10:05', '4.5', '13:40', '6.0'].every((v) => concrete.includes(v)),
  'concrete_operations: pour / supplier / mix / volume / weather / temp / slump_tests render');
ok(concrete.includes(t('coPass')) && concrete.includes(t('coFail')),
  'concrete_operations: slump pass and fail both render');
ok(concrete.includes(`${t('fw_shores_plumb')} | ✓`) && concrete.includes(`${t('fw_no_gaps')} | ✕`)
  && rowIsNotRecorded(concrete, t('fw_bracing_adequate')),
  'concrete_operations: a formwork key the document does NOT carry reads "— Not recorded", never a silent ✕');

// frontend/app/logbooks/scaffold_maintenance.jsx:194 ; :27-36 ; :41-61 ; :63
const scaffold = render(doc('scaffold_maintenance', {
  general_info: {
    scaffold_erector: 'ace scaffold', renters_name: 'hudson builders',
    permit_number: 'SH-2026-114', installation_date: '2026-05-01',
    expiration_date: '2027-05-01', phone: '212-555-0143',
    scaffold_height: '48', num_platforms: '3', shed_type: 'Heavy',
  },
  answers: { signs_on_parapets: 'YES', lights_working: 'NO', deck_clean: 'N/A' },
}));
ok(['ace scaffold', 'hudson builders', 'SH-2026-114', '2026-05-01', '2027-05-01',
  '212-555-0143', '48', 'Heavy'].every((v) => scaffold.includes(v)),
  'scaffold_maintenance: every general_info field the document carries renders');
ok(scaffold.includes(t('q_signs_on_parapets')) && scaffold.includes(t('q_lights_working')),
  'scaffold_maintenance: answered questions render with the DOB form wording');
ok(rowIsNotRecorded(scaffold, t('q_pipe_clamps_tight')),
  'scaffold_maintenance: an UNANSWERED question reads "— Not recorded", never a silent NO');
ok(scaffold.includes(`${t('q_deck_clean')} | N/A`),
  'scaffold_maintenance: an N/A the CP CHOSE is a real answer and survives as chosen');

// frontend/app/logbooks/ssc_daily_safety_log.jsx:192-206
const ssc = render(doc('ssc_daily_safety_log', {
  project_address: '1 test street', ssp_number: 'SSP-4471', weather: 'Clear',
  workers_on_site_count: '37',
  site_conditions: 'dry and clear.', safety_violations_observed: 'none observed.',
  corrective_actions_taken: 'reset the guardrail.',
  incidents_reported: true, incident_details: 'minor hand laceration.',
  safety_meetings_held: true, fire_protection_in_place: true,
  housekeeping_satisfactory: false, ppe_compliance: true,
}));
ok(['1 test street', 'SSP-4471', 'Clear', '37', 'dry and clear.', 'none observed.',
  'reset the guardrail.', 'minor hand laceration.'].every((v) => ssc.includes(v)),
  'ssc_daily_safety_log: address / SSP / weather / count / all four narratives render');
ok([t('s_incidents_reported'), t('s_safety_meetings_held'), t('s_ppe_compliance')]
  .every((v) => ssc.includes(v)),
  'ssc_daily_safety_log: the compliance toggles render');
ok(ssc.includes(t('sscDefaultNote')),
  'ssc_daily_safety_log: the "may be an untouched default" caveat rides with them');

// frontend/app/logbooks/osha_log.jsx:200 ; EMPTY_ENTRY :28-37
const osha = render(doc('osha_log', {
  entries: [
    { worker_name: 'juan perez', company: 'aaz concrete', certification_type: 'SST Supervisor',
      card_number: 'SST-88213', expiration: '2027-03-01', signed: true },
    { worker_name: '', company: '', certification_type: '', card_number: '', expiration: '' },
  ],
}));
ok(['juan perez', 'aaz concrete', 'SST Supervisor', 'SST-88213', '2027-03-01']
  .every((v) => osha.includes(v)),
  'osha_log: worker_name / company / certification_type / card_number / expiration render');

// subcontractor_orientation.jsx:472-483 ; :49-87 (and server.py:9900-9912)
const orientation = render(doc('subcontractor_orientation', {
  worker_id: 'manual_1', worker_name: 'ann worker', worker_company: 'hudson builders',
  worker_trade: 'carpenter', osha_number: 'SST-55110', orientation_number: 'OR-9',
  language_provided: 'en', completed_at: '2026-08-07T13:22:04.000Z',
  checklist: { hard_hats: true, housekeeping: false },
  worker_signature: null,
}));
ok(['ann worker', 'hudson builders', 'carpenter', 'SST-55110', 'OR-9',
  '2026-08-07 13:22:04'].every((v) => orientation.includes(v)),
  'subcontractor_orientation: worker fields and completed_at render');
ok(orientation.includes(`${t('o_hard_hats')} | ✓`)
  && orientation.includes(`${t('o_housekeeping')} | ✕`)
  && rowIsNotRecorded(orientation, t('o_harness_inspection')),
  'subcontractor_orientation: an untouched checklist key reads "— Not recorded", never a silent ✕');
ok(orientation.includes(t('orUnsigned')),
  'subcontractor_orientation: worker_signature present-and-null reads UNSIGNED, never complete');

// The kiosk writes {checked, checked_at} and keys the map by the item's FULL
// ENGLISH SENTENCE (backend/checkin.html:674-687, 1574-1579).
const SENTENCE = 'Site-specific hazards and hazardous activities have been reviewed';
const kioskOrientation = render(doc('subcontractor_orientation', {
  worker_name: 'kiosk worker',
  checklist: { [SENTENCE]: { checked: true, checked_at: '2026-08-07T08:00:00Z' } },
}));
ok(kioskOrientation.includes(SENTENCE)
  && !kioskOrientation.includes('Site-Specific Hazards And Hazardous'),
  'subcontractor_orientation: a kiosk sentence key renders VERBATIM, not title-cased into nonsense');
const ORIENT_LABELS = [...src.matchAll(/\['[a-z_]+', t\('(o_[a-z_]+)'\)\]/g)].map((m) => t(m[1]));
ok(ORIENT_LABELS.length === 18 && ORIENT_LABELS.every((l) => !kioskOrientation.includes(l)),
  `subcontractor_orientation: a kiosk-keyed map does not drag in the ${ORIENT_LABELS.length} in-app checklist items as fabricated "— Not recorded" rows for a form it never used`);

// ════════════════════════════════════════════════════════════════════════════
//  2 — an ABSENT FIELD says so, in the one sanctioned form
// ════════════════════════════════════════════════════════════════════════════
// "— Not recorded" states plainly that the app has no value, and it is what
// generate_combined_report already prints. Anything ELSE — a bare dash, an
// "N/A" the CP did not choose, an "undefined" — either invents a value or
// leaves an inspector unable to tell "never asked" from "asked and blank".
// So the sanctioned string is stripped out first and the rest of the render is
// held to the old rule: no placeholder survives.
const PLACEHOLDERS = ['N/A', 'Not recorded', 'No data available', '—', 'undefined', 'null'];
const residue = (out) => out.split(NOT_RECORDED).join('');

const SPARSE = {
  hot_work: { work_type: 'Cutting' },
  crane_operations: { crane_id: 'TC-14' },
  excavation_monitoring: { soil_type: 'Sand' },
  concrete_operations: { pour_location: 'pier 2' },
  scaffold_maintenance: { general_info: { permit_number: 'SH-1' } },
  ssc_daily_safety_log: { ssp_number: 'SSP-1' },
  osha_log: { entries: [{ worker_name: 'solo worker' }] },
  subcontractor_orientation: { worker_name: 'solo worker' },
};
const KEPT = {
  hot_work: 'Cutting', crane_operations: 'TC-14', excavation_monitoring: 'Sand',
  concrete_operations: 'pier 2', scaffold_maintenance: 'SH-1',
  ssc_daily_safety_log: 'SSP-1', osha_log: 'solo worker',
  subcontractor_orientation: 'solo worker',
};

// The field that is absent in each sparse payload and MUST say so. osha_log is
// not listed: it is rows only, so its absences are case (b), not case (a).
const ABSENT_FIELD = {
  hot_work: t('fLocation'),
  crane_operations: t('crOperator'),
  excavation_monitoring: t('exDepth'),
  concrete_operations: t('coSupplier'),
  scaffold_maintenance: t('scErector'),
  ssc_daily_safety_log: t('sscAddress'),
  subcontractor_orientation: t('orTrade'),
};

for (const [type, data] of Object.entries(SPARSE)) {
  const out = render(doc(type, data, { cp_name: null, cp_signature: null }));
  const found = PLACEHOLDERS.filter((p) => residue(out).includes(p));
  ok(found.length === 0,
    `${type}: no placeholder OTHER than the sanctioned "— Not recorded"${found.length ? ` — found ${JSON.stringify(found)} in ${JSON.stringify(out)}` : ''}`);
  ok(out.includes(KEPT[type]),
    `${type}: ...and the one key that WAS filled still renders (the rule is not "render nothing")`);
  if (ABSENT_FIELD[type]) {
    ok(fieldIsNotRecorded(out, ABSENT_FIELD[type]),
      `${type}: the absent "${ABSENT_FIELD[type]}" reads exactly "${NOT_RECORDED}" — not blank, not invented`);
  }
}
ok(!render(doc('osha_log', SPARSE.osha_log, { cp_name: null, cp_signature: null }))
  .includes(NOT_RECORDED),
  'osha_log: a row-only type has no fields to mark absent — its empty cells stay empty (case b)');

// An untouched EMPTY_* seed row is not a record line.
const seedOnly = [
  ['crane_operations', { load_entries: [{ time: '', description: '', load_weight: '', radius: '' }] }, 'crLiftLog'],
  ['concrete_operations', { slump_tests: [{ time: '', value: '', pass: null }] }, 'coSlumpTests'],
  ['excavation_monitoring', { adjacent_buildings: [{ address: '', baseline_reading: '', current_reading: '' }] }, 'exPoints'],
  ['osha_log', { entries: [{ worker_name: '', company: '', card_number: '' }] }, 'tabOsha'],
];
for (const [type, data, titleKey] of seedOnly) {
  const out = render(doc(type, data, { cp_name: null, cp_signature: null }));
  ok(!out.includes(t(titleKey)),
    `${type}: a table of nothing but untouched EMPTY_* seed rows is not rendered at all`);
  ok(!out.includes(NOT_RECORDED),
    `${type}: ...and the dropped seed row does NOT come back as a row of "— Not recorded" (case b, not case a)`);
}

// The excavation over-threshold flag is meaningless without a reading.
const noReading = render(doc('excavation_monitoring',
  { vibration_over_threshold: false, soil_type: 'Rock' },
  { cp_name: null, cp_signature: null }));
ok(!noReading.includes(t('exWithin')) && !noReading.includes(t('exOver')),
  'excavation_monitoring: over/within threshold is suppressed unless BOTH readings are there');
ok(!noReading.includes(t('exVibration')),
  'excavation_monitoring: with NEITHER reading the whole vibration section stays absent, not a block of "— Not recorded"');

// One reading IS a section — and the status it cannot support says so.
const oneReading = render(doc('excavation_monitoring',
  { vibration_threshold: '0.50', vibration_over_threshold: false },
  { cp_name: null, cp_signature: null }));
ok(oneReading.includes(`${t('exThreshold')}: 0.50`)
  && fieldIsNotRecorded(oneReading, t('exCurrent'))
  && fieldIsNotRecorded(oneReading, t('fStatus'))
  && !oneReading.includes(t('exWithin')),
  'excavation_monitoring: a half-recorded vibration reads "— Not recorded" for the rest, never a fabricated "within threshold"');

// Concrete slump `pass` is tri-state: null is not Fail.
const nullPass = render(doc('concrete_operations',
  { slump_tests: [{ time: '11:00', value: '5.0', pass: null }] },
  { cp_name: null, cp_signature: null }));
ok(nullPass.includes('11:00') && !nullPass.includes(t('coFail')) && !nullPass.includes(t('coPass')),
  'concrete_operations: a null slump `pass` renders as nothing, never as Fail');

// Present-and-empty is UNSIGNED; ABSENT is silence. Two different facts.
const noSigKey = render(doc('subcontractor_orientation', { worker_name: 'ann worker' },
  { cp_name: null, cp_signature: null }));
ok(!noSigKey.includes(t('orUnsigned')) && !noSigKey.includes(t('orAck')),
  'subcontractor_orientation: an ABSENT worker_signature key says nothing (not UNSIGNED)');

// ════════════════════════════════════════════════════════════════════════════
//  2b — false and 0 are ANSWERS, never absences
// ════════════════════════════════════════════════════════════════════════════
const falsy = render(doc('ssc_daily_safety_log', {
  workers_on_site_count: 0,
  incidents_reported: false,
  ppe_compliance: true,
  site_conditions: '',
  corrective_actions_taken: 'reset the guardrail.',
}, { cp_name: null, cp_signature: null }));
ok(falsy.includes(`${t('sscWorkers')}: 0`),
  '0 workers on site is a COUNT the CP recorded — it renders as 0, not as "— Not recorded"');
ok(falsy.includes(`${t('s_incidents_reported')} | ✕`)
  && falsy.includes(`${t('s_ppe_compliance')} | ✓`),
  'a captured false renders as an explicit ✕ and a captured true as ✓ — neither is an absence');
ok(rowIsNotRecorded(falsy, t('s_safety_meetings_held')),
  '...while the toggle the document never carried reads "— Not recorded" alongside them');
ok(fieldIsNotRecorded(falsy, t('sscSiteConditions')),
  'an empty-string narrative is still an absence, and says so');

// ════════════════════════════════════════════════════════════════════════════
//  3 — crew_id, not the phantom crew_name
// ════════════════════════════════════════════════════════════════════════════
const DAILY_ACT = {
  crew_id: 'C3', company: 'aaz concrete', num_workers: 6,
  work_description: 'poured slab', work_locations: 'cellar',
};
const daily = render(doc('daily_jobsite', { weather: 'Clear', activities: [DAILY_ACT] }));
ok(daily.includes('C3'), 'daily_jobsite: crew_id renders — the key the CP actually types');

const phantomAct = { ...DAILY_ACT };
delete phantomAct.crew_id;
phantomAct.crew_name = 'PHANTOM';
const phantom = render(doc('daily_jobsite', { weather: 'Clear', activities: [phantomAct] }));
ok(!phantom.includes('PHANTOM'),
  'daily_jobsite: crew_name is not read — it has no writer anywhere in the repo');
ok(!/act\.crew_name/.test(src),
  'app/site/logbooks.jsx: no reader of act.crew_name is left in the source');

// THE HEADCOUNT AN INSPECTOR READS OFF THE TABLET IS ATTRIBUTED.
// This is the FOURTH surface printing a daily-jobsite crew row (the other three
// are the combined report, the per-logbook PDF and the CP's own card). A number
// a person typed must not render identically to one a turnstile counted on any
// of them.
ok(daily.includes('6'), 'daily_jobsite: a plain gate headcount still renders bare');
ok(!daily.includes('(CP)'),
  'daily_jobsite: a gate headcount is NOT falsely attributed to the CP');

const overridden = render(doc('daily_jobsite', {
  weather: 'Clear',
  activities: [{ ...DAILY_ACT, num_workers: '4', num_workers_source: 'cp',
    gate_num_workers: '6' }],
}));
ok(overridden.includes('4 (CP)'),
  'daily_jobsite: a CP override says so on the tablet');
ok(overridden.includes('gate recorded 6'),
  'daily_jobsite: and what the turnstile counted is printed beside it');

// A row from before the field existed carries no marker and must stay bare.
const legacy = render(doc('daily_jobsite', {
  weather: 'Clear', activities: [{ crew_id: 'C9', company: 'aaz', num_workers: 6 }],
}));
ok(!legacy.includes('(CP)'),
  'daily_jobsite: a pre-existing row is not retroactively attributed');
ok(/act\.crew_id/.test(src),
  'app/site/logbooks.jsx: ...and crew_id is what it reads instead');

// ════════════════════════════════════════════════════════════════════════════
//  4 — the fallback still exists for a genuinely unknown type
// ════════════════════════════════════════════════════════════════════════════
ok(render(doc('some_future_type', { a: 1 })).includes('No data available'),
  'an unknown log type still degrades to the fallback rather than throwing');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
