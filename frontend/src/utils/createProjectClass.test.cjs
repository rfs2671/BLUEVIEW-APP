/**
 * THE CREATE FORM DEFAULTS TO REGULAR — by ruling.
 *
 * THIS FILE REPLACES ITS OWN PREVIOUS PREMISE, and the old one is kept here
 * because the boundary is the point:
 *
 *   THEN: "the create form must not assert a classification." server.py treats
 *   ANY client-supplied project_class as an ADMIN OVERRIDE and stamps
 *   classification_source = "admin". The form defaulted to 'regular' and sent
 *   it on every create, so every project recorded a §3310 decision nobody made
 *   and the server's measure-and-classify path never ran.
 *
 *   NOW: the operator rules that a project STARTS regular and an admin changes
 *   it when the project changes — foundation complete, now Major A. Regular is
 *   a real starting value, and classification is editable at any time, so
 *   there is nothing to defer and no "not assessed" state to offer.
 *
 * ┌─ THE CONSEQUENCE THIS RULING CARRIES, recorded so it is not rediscovered ─┐
 * │ Sending a class on every create means the server's override branch always │
 * │ fires: project_class = regular, classification_source = "admin".          │
 * │                                                                            │
 * │ For a project entered WITH measurements that suggest major, that means:    │
 * │   • it is stored REGULAR, not major_a/major_b;                             │
 * │   • a `classification_override` compliance alert fires at creation.        │
 * │                                                                            │
 * │ classify_project(20 storeys) returns "major_b" — verified, not assumed.    │
 * │                                                                            │
 * │ NOTHING IS LOST: the measured answer is still computed and stored as       │
 * │ `suggested_class`, and the divergence raises an alert rather than passing  │
 * │ silently. But the effective default for a new project is now REGULAR       │
 * │ regardless of its storeys, and the alert volume rises accordingly.         │
 * │ Named for the operator; not a defect of this change.                       │
 * └────────────────────────────────────────────────────────────────────────────┘
 *
 * Run:  node src/utils/createProjectClass.test.cjs
 */
const fs = require('fs');
const path = require('path');

let p = 0; let f = 0;
const ok = (c, l) => { if (c) { p += 1; } else { f += 1; console.log('  FAIL ', l); } };
const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'projects', 'index.jsx'), 'utf8');
ok(src.length > 0, 'create screen source read and non-empty');

console.log('\n-- the field starts at regular --');
ok(/project_class: 'regular',/.test(src),
  "initial state is 'regular', the operator's stated default");
ok(!/project_class: null/.test(src),
  'no null initial state survives — there is no unset state any more');
ok(/setNewProject\(\{ address: '', project_class: 'regular' \}\)/.test(src),
  'and the reset after a successful create returns to regular, not to unset');

console.log('\n-- it is always sent --');
ok(/project_class: newProject\.project_class,/.test(src),
  'the class is sent on every create');
ok(!/\.\.\.\(newProject\.project_class \?/.test(src),
  'the conditional spread is gone — there is no longer an unset case to omit');

console.log('\n-- "not assessed" is not offered --');
// COMMENT-STRIPPED. The block still carries a comment explaining WHY the
// "Not assessed" option was withdrawn — that prose is worth keeping, and a raw
// substring test would read it as the option still being offered.
const stripComments = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
const optsStart = src.indexOf('PROJECT TYPE');
const optsEnd = src.indexOf('.map((opt) =>', optsStart);
const opts = (optsStart > -1 && optsEnd > optsStart)
  ? stripComments(src.slice(optsStart, optsEnd)) : '';
ok(opts.length > 0, 'located the classification option list');
ok(!/key: null/.test(opts), 'no explicit unset option');
ok(!/Not assessed/.test(opts), 'and no "Not assessed" label');
ok(/\{ key: 'regular'/.test(opts), 'regular is offered');
ok(opts.indexOf("{ key: 'regular'") < opts.indexOf("{ key: 'major_a'"),
  'and it is FIRST, so it is what the picker lands on');

console.log('\n-- the other three are still offered, and still say why --');
for (const k of ['major_a', 'major_b']) {
  ok(new RegExp(`\\{ key: '${k}'`).test(opts), `${k} is still selectable`);
}
ok(/10\+ stories/.test(opts) && /15\+ stories/.test(opts),
  'the thresholds are still on screen — an admin choosing regular for a '
  + '20-storey building must be able to see that it is the wrong answer');

console.log(`\n${p} passed, ${f} failed`);
if (f > 0) process.exit(1);
console.log('ALL PASSED');
