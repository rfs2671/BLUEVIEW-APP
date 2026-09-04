/**
 * WHOSE NAME GOES UNDER A LICENSED SIGNATURE.
 *
 * The superintendent log prefilled its printed name from `useCpProfile` — a
 * cache written AFTER a successful signature. On a screen that has never been
 * signable, that is blank for everyone. Fixing the prop names alone would have
 * prefilled it for the one CP with a cached profile and left the next man with
 * an empty field on the control that gates filing.
 *
 * Run:  node src/utils/signerName.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const src = fs.readFileSync(path.join(__dirname, 'signerName.js'), 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export /gm, '');
const { resolveSignerName, sessionSignerName } = new Function(
  `${src}; return { resolveSignerName, sessionSignerName };`)();

const USER = { full_name: 'Michael Ruiz', name: 'mruiz' };

console.log('\n-- precedence --');
ok(resolveSignerName({ typed: 'Typed Name', stored: 'Stored', user: USER, profileName: 'Cached' })
   === 'Typed Name', '1. what he typed wins over everything');
ok(resolveSignerName({ typed: '', stored: 'Stored Draft', user: USER, profileName: 'Cached' })
   === 'Stored Draft', '2. a rehydrated draft beats the session');
ok(resolveSignerName({ typed: '', stored: '', user: USER, profileName: 'Cached' })
   === 'Michael Ruiz', '3. THE SESSION BEATS THE CACHED PROFILE');
ok(resolveSignerName({ typed: '', stored: '', user: null, profileName: 'Cached' })
   === 'Cached', '4. the profile is the last resort, not the first');

console.log('\n-- the case this exists for --');
ok(resolveSignerName({ user: USER, profileName: '' }) === 'Michael Ruiz',
  'a CP who has NEVER signed still gets his name — the whole point');
ok(resolveSignerName({}) === '', 'and nothing known yields empty, never a guess');

console.log('\n-- the fabrication rule --');
ok(resolveSignerName({ user: { full_name: 'Second User' }, profileName: 'Previous Device User' })
   === 'Second User',
  "on a SHARED device the session wins, never the previous user's cached name");

console.log('\n-- session name shape --');
ok(sessionSignerName({ full_name: 'A B' }) === 'A B', 'full_name first');
ok(sessionSignerName({ name: 'C D' }) === 'C D', 'then name');
ok(sessionSignerName({ full_name: '   ', name: 'C D' }) === 'C D',
  'a whitespace-only full_name is not a name');
for (const bad of [null, undefined, {}, 'string', 42]) {
  ok(sessionSignerName(bad) === '', `${JSON.stringify(bad)} yields ''`);
}

console.log('\n-- whitespace is trimmed, never stored raw --');
ok(resolveSignerName({ typed: '  Michael  ' }) === 'Michael', 'typed is trimmed');
ok(resolveSignerName({ typed: '   ', user: USER }) === 'Michael Ruiz',
  'a field holding only spaces is not an answer');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
