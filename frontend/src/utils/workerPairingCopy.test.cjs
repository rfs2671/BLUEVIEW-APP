/**
 * Absent by design does not read as missing data.
 *
 * THE DEFECT. Three surfaces rendered "No trade specified" / "No company" off
 * the WORKERS document, and nothing writes those fields — a worker's trade and
 * company belong to the {worker, project} PAIR and live in
 * worker_project_trades. WorkerResponse's docstring says why the endpoint
 * cannot fill them: "a worker with pairings on two projects has two companies,
 * and this endpoint has no project context to choose between them."
 *
 * So the fields are absent BY DESIGN, and the copy reported that as missing
 * data. An admin reading it went to fix it — and the edit form on that same
 * screen wrote a worker-level copy, the exact bleed the design forbids, until
 * that path was closed.
 *
 * THE CONTEXT WAS ALREADY IN HAND. app/workers.jsx navigates from a CHECK-IN
 * row, which carries project_id plus the pairing the server already resolved
 * through _get_worker_project_trade (server.py:12780) and stamped on as
 * worker_trade / worker_company. It forwarded the worker id and dropped the
 * rest.
 *
 *   node frontend/src/utils/workerPairingCopy.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const { loadEsm } = require('./esmHarness.cjs');
const { pairingLine, hasPairing } = loadEsm('src/utils/workerPairingCopy.js');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}
const strip = (p) => fs.readFileSync(path.join(FRONTEND, p), 'utf8')
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

console.log('\n-- it never says "No company" --');
{
  const everyShape = [
    {}, { trade: 'Framers' }, { company: 'Arkon' },
    { trade: 'Framers', company: 'Arkon' },
    { projectName: '588 Thomas' },
    { trade: 'Framers', company: 'Arkon', projectName: '588 Thomas' },
    { trade: '', company: '   ', projectName: '' },
    { trade: null, company: undefined, projectName: null },
  ];
  ok(everyShape.every((a) => !/No company/i.test(pairingLine(a))),
    'no input produces "No company" — the sentence that reported a designed '
    + 'absence as missing data');
  ok(everyShape.every((a) => !/No trade specified/i.test(pairingLine(a))),
    'nor "No trade specified"');
  ok(everyShape.every((a) => pairingLine(a).trim().length > 0),
    'and none produces an empty line — a blank reads as a rendering fault, '
    + 'not as an answer');
}

console.log('\n-- a resolved pairing is stated, and scoped to its project --');
{
  ok(pairingLine({ trade: 'Framers', company: 'Arkon Builders', projectName: '588 Thomas' })
    === 'Framers · Arkon Builders — on 588 Thomas',
    'both, with the project named. The pairing is only true THERE — an '
    + 'unqualified line is the same over-claim the worker-level copy made');
  ok(pairingLine({ trade: 'Framers', company: 'Arkon Builders' })
    === 'Framers · Arkon Builders',
    'and without a project name it states the pairing plainly rather than '
    + 'inventing one');
}

console.log('\n-- a half-pairing is a real stored shape --');
{
  // _get_worker_project_trade returns company as "" when unset, so trade
  // without company reaches the client.
  ok(pairingLine({ trade: 'Framers', projectName: '588 Thomas' })
    === 'Framers — on 588 Thomas',
    'a trade with no company renders the trade rather than collapsing to the '
    + 'absent case');
  ok(pairingLine({ company: 'Arkon Builders' }) === 'Arkon Builders',
    'and a company with no trade renders the company');
}

console.log('\n-- absent states the RULE, and names the project when it can --');
{
  ok(pairingLine({}) === 'Trade and company are set per project.',
    'with no context it states the rule. That is the fact — not a deficiency');
  ok(pairingLine({ projectName: '588 Thomas' })
    === 'Trade and company are set per project — none recorded for 588 Thomas.',
    'with a project it says which one, so the reader has something to act on');
  ok(!/not specified|unknown|missing/i.test(pairingLine({ projectName: 'X' })),
    'and it never uses the vocabulary of a defect');
}

console.log('\n-- whitespace and nullish are absence, not content --');
{
  ok(pairingLine({ trade: '   ', company: '\t' }) === pairingLine({}),
    'blank strings are absent — otherwise a stored "" renders as a pairing');
  ok(hasPairing({ trade: 'Framers' }) === true, 'hasPairing sees a trade');
  ok(hasPairing({}) === false && hasPairing() === false,
    'and nothing is not a pairing, called with no argument at all');
}

console.log('\n-- the roster row forwards what it was already holding --');
{
  const src = strip('app/workers.jsx');
  ok(/projectId: checkin\.project_id/.test(src),
    'the project id is forwarded. The row is a check-in and always had it');
  ok(/trade: checkin\.worker_trade/.test(src) && /company: checkin\.worker_company/.test(src),
    'and the pairing the SERVER resolved, so the screen neither guesses nor '
    + 'needs the endpoint widened');
  ok(/pathname: `\/workers\/\$\{workerId\}`/.test(src),
    'the route is unchanged — params only');
}

console.log('\n-- the worker screen reads the params, not the document --');
{
  const src = strip('app/workers/[id].jsx');
  ok(/projectId: routeProjectId/.test(src) && /trade: routeTrade/.test(src),
    'it takes the forwarded pairing off the route');
  ok(/pairingLine\(\{[\s\S]{0,120}trade: routeTrade/.test(src),
    'and renders it through the shared copy');
  ok(!/\{trade \|\| 'No trade specified'\}/.test(src)
    && !/\{company \|\| 'No company'\}/.test(src),
    'the two document reads are gone');

  ok(!/pairingLine\(\{[\s\S]{0,160}trade: trade\b/.test(src),
    'AND IT DOES NOT FALL BACK to the worker document. '
    + '_get_worker_project_trade refuses the same fallback: a value from '
    + 'another project is worse than no value, because it is silently wrong '
    + 'instead of visibly absent');
  ok(/setTrade\(workerData\.trade/.test(src),
    'the state is still READ off the document, deliberately — a legacy row may '
    + 'carry it and hiding a stored value is a different defect');
}

console.log('\n-- the check-in screen uses the project it already selected --');
{
  const src = strip('app/checkin/index.jsx');
  ok(!/selectedWorker\.company \|\| 'No company'/.test(src)
    && !/worker\.company \|\| 'No company'/.test(src),
    'both dead reads are gone. workersAPI.getAll returns raw worker documents '
    + 'with no pairing join, so both fields were structurally empty');
  ok(!/\{selectedWorker\.trade\} •/.test(src),
    'including the bare {selectedWorker.trade} with no fallback at all, which '
    + 'rendered a stray bullet');
  const uses = (src.match(/pairingLine\(\{ projectName: project\?\.name \}\)/g) || []);
  ok(uses.length === 2, `both sites use the shared copy (found ${uses.length})`);
  ok(/selectedProject/.test(src),
    'and the screen still tracks its selected project');
}

console.log('\n-- nothing here writes to the worker document --');
{
  // The rule this whole line of work exists to protect.
  for (const f of ['app/workers.jsx', 'app/workers/[id].jsx', 'app/checkin/index.jsx']) {
    const src = strip(f);
    ok(!/updateWorker\([^)]*\btrade\b/.test(src) && !/trade,\s*\n\s*company,/.test(src),
      `${f} sends no trade/company to the worker document`);
  }
  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  const i = server.indexOf('ALLOWED_WORKER_FIELDS = {');
  const decl = server.slice(i, server.indexOf('}', i) + 1);
  ok(!/"trade"/.test(decl) && !/"company"/.test(decl),
    'and the server still refuses them — closed in an earlier PR, pinned here '
    + 'because this one changes what an admin READS on the same screen');
}

console.log('\n-- no pairings endpoint was built --');
{
  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  ok(!/workers\/\{worker_id\}\/pairings/.test(server),
    'GET /workers/{id}/pairings does not exist. It is a new tenant-isolation '
    + 'surface and gets scoped on its own');
  const api = fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'api.js'), 'utf8');
  ok(!/pairings/.test(api), 'and no client reaches for one');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
