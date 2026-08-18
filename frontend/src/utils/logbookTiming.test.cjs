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
  return { IMMEDIATE_LOG_TYPES, END_OF_DAY_LOG_TYPES, isImmediateLog,
           isBatchable, freezeIfImmediate };
`)();

// The server's own table, read rather than retyped.
const timingBlock = SERVER.slice(
  SERVER.indexOf('LOGBOOK_TIMING_CLASS = {'),
  SERVER.indexOf('def logbook_timing_class'),
);
const serverImmediate = [...timingBlock.matchAll(/"([a-z_]+)":\s*"immediate"/g)]
  .map((m) => m[1]);
const serverEndOfDay = [...timingBlock.matchAll(/"([a-z_]+)":\s*"end_of_day"/g)]
  .map((m) => m[1]);

console.log('\n-- the two lists agree, type for type --');
ok(serverImmediate.length > 0 && serverEndOfDay.length > 0,
  `the server table was located (${serverImmediate.length} immediate, `
  + `${serverEndOfDay.length} end-of-day)`);
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
ok(M.IMMEDIATE_LOG_TYPES.length + M.END_OF_DAY_LOG_TYPES.length
   === serverImmediate.length + serverEndOfDay.length,
  'every registered type is on exactly one of the two lists');

console.log('\n-- and the predicate follows the list --');
for (const t of serverImmediate) {
  ok(M.isImmediateLog(t) === true, `${t}: signature IS the freeze`);
  ok(M.isBatchable(t) === false, `${t}: and it is never swept into the EOD batch`);
}
for (const t of serverEndOfDay) {
  ok(M.isImmediateLog(t) === false, `${t}: stays open, frozen by the EOD sign`);
  ok(M.isBatchable(t) === true, `${t}: and it IS batchable`);
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
