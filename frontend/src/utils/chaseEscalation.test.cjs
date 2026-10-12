/**
 * "Gets chase escalation DMs": admins on by default, PMs off, nobody else;
 * the switch is in the Users edit sheet (an admin or a PM) and in Settings
 * (an admin's own). Mirrors the server's gets_chase_escalation.
 *
 * Run:  node src/utils/chaseEscalation.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8');
const V = loadEsm('src/utils/roleVocabulary.js');

let failures = 0;
const check = (name, fn) => {
  try { fn(); console.log(`  ok  ${name}`); } catch (e) {
    failures += 1; console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

console.log('\nchase escalation DMs\n');

check('defaults: admin on, PM off, others never', () => {
  ok(V.getsChaseEscalation({ role: 'admin' }) === true, 'admin');
  ok(V.getsChaseEscalation({ role: 'pm' }) === false, 'pm');
  ok(V.getsChaseEscalation({ role: 'pm', pm_access: 'full' }) === false, 'full pm');
  ok(V.getsChaseEscalation({ role: 'cp', chase_escalation_dms: true }) === false, 'cp never');
});

check('a stored choice wins', () => {
  ok(V.getsChaseEscalation({ role: 'pm', chase_escalation_dms: true }) === true, 'pm on');
  ok(V.getsChaseEscalation({ role: 'admin', chase_escalation_dms: false }) === false, 'admin off');
});

check('the switch is where an admin can reach it', () => {
  const users = read('app', 'admin', 'users.jsx');
  ok(/selectedUser && chaseEscalationEligible\(selectedUser\) \? \(\s*<ChaseEscalationToggle/.test(users),
    'Users edit sheet');
  ok(/isAccountAdmin\(user\) && \(user\?\.id \|\| user\?\._id\) \? \([\s\S]{0,200}<ChaseEscalationToggle userRow=\{user\}\s*onSaved=\{\(on\) => updateUser\(\{ chase_escalation_dms: on \}\)\} \/>/
    .test(read('app', 'settings.jsx')), 'Settings, an admin\'s own');
  ok(/\/chase-escalation`, \{ on: !!on \}/.test(read('src', 'utils', 'api.js')), 'the API call');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
