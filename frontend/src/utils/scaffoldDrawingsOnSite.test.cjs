/**
 * The app must not answer a DOB inspection question the CP never answered.
 *
 * `drawings_on_site` existed TWICE on the Scaffold Maintenance Log:
 *
 *   general_info.drawings_on_site   seeded 'YES', with NO control anywhere on
 *                                   the screen that could change it
 *   answers.drawings_on_site        question 19 of 19, "Drawings on site for
 *                                   inspection?", which the CP actually taps
 *
 * Two keys, one name, and one of them carried a value nobody entered — written
 * onto every scaffold log, and onto the project itself through
 * saveScaffoldInfo.
 *
 * IT NEVER REACHED A FILED DOCUMENT. Both PDF renderers read only the answers
 * one and say so in as many words — backend/server.py:13369 and :18801, "a
 * dead duplicate of the answers question of the same key". So this removes a
 * false assertion from stored data without changing a printed page: an
 * unanswered question renders "Not recorded", never a silent YES.
 *
 * Run:  node src/utils/scaffoldDrawingsOnSite.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const screen = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'scaffold_maintenance.jsx'), 'utf8');
// RE-POINTED. The question list and the general_info seed moved out of the
// screen and into src/utils/scaffoldMaintenanceModel.js when the form was
// ported onto the shared stepper. Every assertion below is the one it always
// made — only the address changed, and BOTH files are read so the seed cannot
// come back on either side of the move.
const model = fs.readFileSync(
  path.join(FRONTEND, 'src', 'utils', 'scaffoldMaintenanceModel.js'), 'utf8');
const server = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const strip = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
const screenCode = strip(screen);
const modelCode = strip(model);
// The two together are where a seed could hide.
const code = `${screenCode}\n${modelCode}`;

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

console.log('\n-- One key, and nothing seeds an answer --');

ok(!/drawings_on_site: 'YES'/.test(code),
  "general_info no longer seeds 'YES' for a question nobody answered");
// The seed now lives in EMPTY_GENERAL_INFO() rather than a useState literal.
// Both spellings are checked, so neither file can reintroduce it.
const giSeed = (modelCode.match(/EMPTY_GENERAL_INFO = \(\) => \(\{([\s\S]*?)\}\);/) || [, ''])[1]
  + (screenCode.match(/useState\(\{([\s\S]*?)\}\);/) || [, ''])[1];
ok(giSeed.length > 0 && !/drawings_on_site/.test(giSeed),
  'and it is not a general_info key at all any more');
// GENERAL_INFO_KEYS is what actually travels in the payload — assert the
// absence there too, which the old useState-literal check could not see.
const giKeys = (modelCode.match(/GENERAL_INFO_FIELDS = Object\.freeze\(\[([\s\S]*?)\]\);/) || [, ''])[1];
ok(giKeys.length > 0 && !/drawings_on_site/.test(giKeys),
  'and it is not one of the general_info FIELDS the form renders');

// It must still exist where the CP ANSWERS it.
ok(/\{ key: 'drawings_on_site', label: 'Drawings on site for inspection\?' \}/
  .test(code), 'it remains question 19, where the CP taps it');
ok((code.match(/drawings_on_site/g) || []).length === 1,
  'exactly ONE occurrence survives — the question, not the seed');

console.log('\n-- Nothing printed changes --');

ok(/general_info\.drawings_on_site is a dead duplicate/.test(server),
  'both renderers already ignored the general_info copy');
ok((server.match(/general_info\.drawings_on_site is a dead/g) || []).length === 2,
  'and both of them say so, so neither starts reading it');

console.log('\n-- The project value is left alone --');

// update_scaffold_info writes every key it is handed, so sending the key as
// undefined would store null over whatever the project already had.
ok(/Object\.entries\(generalInfo \|\| \{\}\)\.filter\(\(\[, v\]\) => v !== undefined\)/
  .test(modelCode), 'undefined keys are dropped before the project write');
// And the screen must actually USE that helper on the save path — the filter
// is worthless if the port sends generalInfo raw.
ok(/saveScaffoldInfo\(\s*projectId, scaffoldInfoForSave\(/.test(screenCode),
  'and the screen sends its project write through that helper');
ok(/"drawings_on_site": data\.get\("drawings_on_site"\)/.test(server),
  'which matters because the server writes the key unconditionally');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
