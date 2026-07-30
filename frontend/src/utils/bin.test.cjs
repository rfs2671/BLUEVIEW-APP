/**
 * PR D — isValidBin (bin.js) mirrors the backend _is_placeholder_bin, and is
 * the ONE predicate shared by the project tile and the DOB tab (which used a
 * bare truthiness check, so a borough placeholder like 2000000 read as a real
 * BIN there while the tile said "No BIN"). The project screen also reads the
 * SERVER object first, with the local record as offline fallback only.
 *
 * Run:  node src/utils/bin.test.cjs
 */
const fs = require('fs');
const path = require('path');

function extractFn(file, name) {
  const src = fs.readFileSync(path.join(__dirname, file), 'utf8');
  const at = src.indexOf(`function ${name}(`);
  if (at < 0) throw new Error(`${name} not found`);
  const open = src.indexOf('{', at);
  let d = 0, i = open;
  for (; i < src.length; i += 1) {
    if (src[i] === '{') d += 1;
    else if (src[i] === '}') { d -= 1; if (d === 0) { i += 1; break; } }
  }
  return new Function(`${src.slice(at, i)}\nreturn ${name};`)();
}
const isValidBin = extractFn('bin.js', 'isValidBin');

const projectScreen = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'project', '[id].jsx'), 'utf8');
const dobTab = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'project', '[id]', 'dob-logs.jsx'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

ok(isValidBin('3255362') === true, 'real BIN valid (588 Boyland 3255362)');
ok(isValidBin('2000000') === false, 'borough placeholder X000000 invalid');
ok(isValidBin('') === false && isValidBin(null) === false && isValidBin(undefined) === false,
  'empty / null / undefined invalid');
ok(isValidBin('123456') === false && isValidBin('12345678') === false, 'wrong length invalid');
ok(isValidBin('6255362') === false && isValidBin('0255362') === false, 'borough digit must be 1-5');
ok(isValidBin('  3255362  ') === true, 'trims surrounding whitespace');

ok(projectScreen.indexOf('projectsAPI.getById(projectId)') <
   projectScreen.indexOf('getProjectById(projectId)'),
  'project screen: reads SERVER object BEFORE local fallback');
ok(/isValidBin\(project\?\.nyc_bin\)/.test(projectScreen), 'project tile: uses shared isValidBin');
ok(/isValidBin\(nycBin\)/.test(dobTab), 'DOB tab: uses shared isValidBin (was truthiness)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
