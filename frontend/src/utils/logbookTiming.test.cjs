/**
 * THE CLIENT'S FREEZE MIRROR MUST MATCH THE SERVER'S.
 *
 * logbookTiming.js writes down which log types freeze on SIGNATURE, and its own
 * header says "the server is authoritative — if the two ever disagree, the
 * server wins". That is true of every path except the one this file exists for:
 * freezeIfImmediate runs on the DEVICE, with no server to ask, because the logs
 * it covers are below-grade pre-work signed in holes with no signal. Offline,
 * the mirror IS the rule.
 *
 * It went stale the day a twelfth log type shipped. `fall_protection` was
 * `immediate` on the server and absent here, so a fall-protection log signed
 * with no signal did not freeze on the device — the server locked it when the
 * push eventually landed, which is the guarantee this function exists to not
 * depend on.
 *
 * Nothing compared the two lists. Every count in the suite was read from
 * server.py, so raising them all to ten left this file untouched and green.
 *
 * Run:  node src/utils/logbookTiming.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The real module, executed.
const MOD_SRC = fs.readFileSync(path.join(UTILS, 'logbookTiming.js'), 'utf8');
// eslint-disable-next-line no-new-func
const M = new Function(`
  const markFinalized = async () => true;
  ${MOD_SRC
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (async function|function|const) /gm, '$1 ')}
  return { IMMEDIATE_LOG_TYPES, END_OF_DAY_LOG_TYPES, VISIT_LOG_TYPES,
           isImmediateLog, isVisitLog, isBatchable, freezeIfImmediate };
`)();

// The server's own table, read rather than retyped.
const timingBlock = SERVER.slice(
  SERVER.indexOf('LOGBOOK_TIMING_CLASS = {'),
  SERVER.indexOf('def logbook_timing_class'),
);
/**
 * EVERY entry, with WHATEVER class it names — not two greps for two classes
 * this file already knew about.
 *
 * THE ORIGINAL SHAPE IS WHY THE THIRD CLASS SHIPPED UNMIRRORED. This read
 * `"immediate"` and `"end_of_day"` by name, so `site_superintendent_log:
 * "visit"` matched neither pattern and was invisible. The balance check below
 * then confirmed 10 + 2 === 10 + 2 and reported that every registered type was
 * accounted for, while a type the server had classified sat in no client list
 * at all and answered `isBatchable` with the two-way default.
 *
 * A test that enumerates the cases it expects cannot report a case it did not
 * expect. So: parse every "<key>": "<class>" pair, and let the SERVER decide
 * which classes exist.
 */
const serverClass = new Map(
  [...timingBlock.matchAll(/"([a-z_]+)":\s*"([a-z_]+)"/g)].map((m) => [m[1], m[2]]),
);
const byClass = (cls) => [...serverClass]
  .filter(([, c]) => c === cls).map(([k]) => k);
const serverImmediate = byClass('immediate');
const serverEndOfDay = byClass('end_of_day');
const serverVisit = byClass('visit');

console.log('\n-- the lists agree, type for type, class for class --');
ok(serverImmediate.length > 0 && serverEndOfDay.length > 0 && serverVisit.length > 0,
  `the server table was located (${serverImmediate.length} immediate, `
  + `${serverEndOfDay.length} end-of-day, ${serverVisit.length} visit)`);

// THE CLASSES THEMSELVES ARE THE ANCHOR. If the server grows a FOURTH class,
// this fails and names it — rather than the new class defaulting silently on
// the client the way `visit` did.
{
  const classes = [...new Set(serverClass.values())].sort();
  ok(JSON.stringify(classes) === JSON.stringify(['end_of_day', 'immediate', 'visit']),
    `ANCHOR: the server declares exactly these timing classes — ${JSON.stringify(classes)}. `
    + 'A new one means a new client list, not a wider comparison here');
}
{
  const missing = serverImmediate.filter((t) => !M.IMMEDIATE_LOG_TYPES.includes(t));
  ok(missing.length === 0,
    `every server IMMEDIATE type is mirrored on the client${missing.length ? ` — MISSING ${JSON.stringify(missing)}` : ''}`);
  const extra = M.IMMEDIATE_LOG_TYPES.filter((t) => !serverImmediate.includes(t));
  ok(extra.length === 0,
    `and the client claims none the server does not${extra.length ? ` — EXTRA ${JSON.stringify(extra)}` : ''}`);
}
{
  const missing = serverEndOfDay.filter((t) => !M.END_OF_DAY_LOG_TYPES.includes(t));
  const extra = M.END_OF_DAY_LOG_TYPES.filter((t) => !serverEndOfDay.includes(t));
  ok(missing.length === 0 && extra.length === 0,
    'and the END_OF_DAY lists agree too — a type in neither list would be '
    + 'batchable on the client and immediate on the server');
}
{
  const missing = serverVisit.filter((t) => !M.VISIT_LOG_TYPES.includes(t));
  const extra = M.VISIT_LOG_TYPES.filter((t) => !serverVisit.includes(t));
  ok(missing.length === 0 && extra.length === 0,
    'and the VISIT lists agree — the class that shipped mirrored nowhere'
    + `${missing.length ? ` — MISSING ${JSON.stringify(missing)}` : ''}`
    + `${extra.length ? ` — EXTRA ${JSON.stringify(extra)}` : ''}`);
}

// EVERY REGISTERED TYPE ON EXACTLY ONE LIST, counted against the WHOLE table
// rather than against the two classes this file used to know about. The old
// version summed two client lists and two server greps; a type in a third
// class was absent from both sides and the equation still balanced.
{
  const onAClient = [...M.IMMEDIATE_LOG_TYPES, ...M.END_OF_DAY_LOG_TYPES,
    ...M.VISIT_LOG_TYPES];
  const unmirrored = [...serverClass.keys()].filter((t) => !onAClient.includes(t));
  ok(unmirrored.length === 0,
    'every type in the server table is on exactly one client list'
    + `${unmirrored.length ? ` — UNMIRRORED ${JSON.stringify(unmirrored)}` : ''}`);
  ok(onAClient.length === new Set(onAClient).size,
    'and none is on two — a type in two lists makes the predicates disagree');
  ok(onAClient.length === serverClass.size,
    `client lists total ${onAClient.length}, server table has ${serverClass.size}`);
}

console.log('\n-- and the predicate follows the list --');
for (const t of serverImmediate) {
  ok(M.isImmediateLog(t) === true, `${t}: signature IS the freeze`);
  ok(M.isBatchable(t) === false, `${t}: and it is never swept into the EOD batch`);
}
for (const t of serverEndOfDay) {
  ok(M.isImmediateLog(t) === false, `${t}: stays open, frozen by the EOD sign`);
  ok(M.isBatchable(t) === true, `${t}: and it IS batchable`);
}
for (const t of serverVisit) {
  // THE THREE ANSWERS THAT MUST NOT COLLAPSE INTO TWO. A visit log is not
  // immediate (the signature alone does not lock it) and not batchable (the
  // overnight sweep must never freeze a visit its author had not finished).
  // Before VISIT_LOG_TYPES existed the second of these was TRUE on the client
  // and FALSE on the server.
  ok(M.isVisitLog(t) === true, `${t}: frozen by its author's finalize on departure`);
  ok(M.isImmediateLog(t) === false, `${t}: the signature alone does not freeze it`);
  ok(M.isBatchable(t) === false,
    `${t}: and it is NOT batchable — the EOD sweep must never touch it`);
}
// An UNKNOWN type must behave as end_of_day, matching logbook_timing_class's
// documented default — the safer one, because nothing is force-frozen by
// accident.
ok(M.isImmediateLog('something_new') === false,
  'an unregistered type is NOT force-frozen — the same default the server takes');

console.log('\n-- the offline freeze, which is the whole point --');
(async () => {
  for (const t of serverImmediate) {
    // eslint-disable-next-line no-await-in-loop
    ok(await M.freezeIfImmediate('logbook_draft:p1:x:2026-08-18', t) === true,
      `${t}: freezes the on-device draft with no server involved`);
  }
  for (const t of serverEndOfDay) {
    // eslint-disable-next-line no-await-in-loop
    ok(await M.freezeIfImmediate('logbook_draft:p1:x:2026-08-18', t) === false,
      `${t}: does NOT — it is frozen by the end-of-day sign instead`);
  }
  ok(await M.freezeIfImmediate('', 'osha_log') === false,
    'and a missing draft key freezes nothing rather than throwing');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
