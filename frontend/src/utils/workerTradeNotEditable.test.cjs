/**
 * The worker screen does not offer to write a per-project fact.
 *
 * THE RULE. A worker's trade and company belong to the {worker, project} PAIR
 * and live in worker_project_trades. register_and_checkin says so where it
 * builds the document: "no `trade` / `company` here. Those are per-project and
 * live in worker_project_trades; a worker-level copy is what bled across jobs."
 *
 * WHAT THE SCREEN DID. It rendered "No trade specified" / "No company" -- both
 * structurally absent, because nothing populates them on the worker document --
 * and directly above that offered an admin two GlassInputs for exactly those
 * fields, wired into a PUT that the server accepted. So the screen invited the
 * forbidden write at the moment an admin was most motivated to make it, and the
 * value would have been global: overriding nothing, contradicting every
 * per-project pairing, and looking correct on the one screen that displayed it.
 *
 * REMOVED, NOT DISABLED. Leaving a field the server now ignores is worse than
 * the write it replaced -- the admin types a company, taps Save, and is told
 * "Worker information updated".
 *
 * THE CARD STILL SAYS "No company". That is the copy fix, sequenced after this
 * one, and a test below pins that it has NOT happened yet so the two are not
 * confused for each other.
 *
 *   node frontend/src/utils/workerTradeNotEditable.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'workers', '[id].jsx');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

const raw = fs.readFileSync(SCREEN, 'utf8');
// COMMENTS STRIPPED. This file's own prose names the fields it asserts are
// gone, and a JSX comment block explains why they were removed -- an unstripped
// source matches the explanation rather than the code.
const src = raw
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

console.log('\n-- the PUT carries neither field --');
{
  const i = src.indexOf('const handleSave');
  ok(i > -1, 'handleSave exists');
  const body = src.slice(i, src.indexOf('};', src.indexOf('setSaving(false)', i)));

  ok(!/^\s*trade,\s*$/m.test(body),
    'handleSave does not send `trade`. THE REPORTED PATH: an admin looking at '
    + '"No trade specified" typed one in and saved it');
  ok(!/^\s*company,\s*$/m.test(body),
    'nor `company`');
  ok(/name,/.test(body) && /osha_number: oshaNumber/.test(body)
    && /certifications,/.test(body),
    'and the rest of the edit still saves — certifications is what an admin '
    + 'actually needs this screen for');
}

console.log('\n-- the inputs are gone, not merely ignored --');
{
  ok(!/onChangeText=\{setTrade\}/.test(src),
    'no Trade input. A field the server ignores is WORSE than the write it '
    + 'replaced: the admin types, saves, and is told it worked');
  ok(!/onChangeText=\{setCompany\}/.test(src),
    'no Company input');
  ok(!/placeholder="Trade"/.test(src) && !/placeholder="Company"/.test(src),
    'and neither placeholder survives');
  ok(/onChangeText=\{setName\}/.test(src) && /placeholder="OSHA Number"/.test(src),
    'the inputs that write real worker-level facts are untouched');
}

console.log('\n-- no reset for a field that cannot change --');
{
  ok(!/setTrade\(worker\?\.trade/.test(src) && !/setCompany\(worker\?\.company/.test(src),
    'Cancel does not reset trade/company — resetting state no input can touch '
    + 'would imply the fields are still editable');
  ok(/setName\(worker\?\.name/.test(src), 'and it still resets the ones that are');
}

console.log('\n-- the READ path is untouched, deliberately --');
{
  ok(/setTrade\(workerData\.trade/.test(src) && /setCompany\(workerData\.company/.test(src),
    'applyWorker still reads both off the document. A legacy worker may carry '
    + 'them, and hiding a value that IS stored would be a different defect');
}

console.log('\n-- the copy fix HAS landed --');
{
  // INVERTED, AND IT DID ITS JOB. It read:
  //
  //   ok(/No trade specified/.test(src) && /No company/.test(src),
  //     'the card still reads ... INVERT THIS when the copy fix lands')
  //
  // pinning that closing the WRITE had not quietly changed what the card SAYS.
  // The two were sequenced apart on purpose: one closes a path that wrote a
  // per-project fact onto the worker document, the other stops the screen
  // reporting a designed absence as missing data. Both have landed, so the
  // assertion inverts rather than being deleted and the pairing stays visible.
  ok(!/No trade specified/.test(src) && !/No company/.test(src),
    'the card no longer asserts absence. "No company" is what sent an admin to '
    + 'the edit form to write the worker-level copy this file exists to forbid');
  ok(/pairingLine\(/.test(src),
    'it states the rule through the shared copy instead');
}

console.log('\n-- the server allowlist agrees --');
{
  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  const i = server.indexOf('ALLOWED_WORKER_FIELDS = {');
  const decl = server.slice(i, server.indexOf('}', i) + 1);
  ok(!/"trade"/.test(decl) && !/"company"/.test(decl),
    'ALLOWED_WORKER_FIELDS names neither. BOTH HALVES OR NEITHER: a client-only '
    + 'fix leaves the endpoint open to anything else that calls it');
  ok(/"certifications"/.test(decl) && /"name"/.test(decl),
    'and it still admits the fields the form does send');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
