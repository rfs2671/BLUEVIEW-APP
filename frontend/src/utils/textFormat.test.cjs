/**
 * PR G — display-time capitalization (textFormat.js). Two rules:
 *   capitalizeFirst — short entry: capitalize the first letter, preserve the
 *     rest EXACTLY (no lowercasing, no reformatting).
 *   sentenceCase — prose: capital after every terminal punctuation (. ! ?),
 *     rest preserved.
 * Must match the backend _capitalize_first / _sentence_case, and never mutate
 * stored data (applied at display only).
 *
 * Run:  node src/utils/textFormat.test.cjs
 */
const fs = require('fs');
const path = require('path');

function extractFn(name) {
  const src = fs.readFileSync(path.join(__dirname, 'textFormat.js'), 'utf8');
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
const capitalizeFirst = extractFn('capitalizeFirst');
const sentenceCase = extractFn('sentenceCase');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// capitalizeFirst
ok(capitalizeFirst('aaz concrete') === 'Aaz concrete', 'capFirst: first letter up');
ok(capitalizeFirst('aBC iNc') === 'ABC iNc', 'capFirst: rest preserved exactly (acronyms)');
ok(capitalizeFirst('3rd floor') === '3rd floor', 'capFirst: leading digit unchanged, rest kept');
ok(capitalizeFirst('  hi') === '  Hi', 'capFirst: leading whitespace preserved');
ok(capitalizeFirst('') === '' && capitalizeFirst(null) === '', 'capFirst: empty/null safe');

// sentenceCase
ok(sentenceCase('poured slab today') === 'Poured slab today', 'sentenceCase: first letter');
ok(sentenceCase('poured slab. cured overnight.') === 'Poured slab. Cured overnight.',
  'sentenceCase: capital after each terminal .');
ok(sentenceCase('done! next?') === 'Done! Next?', 'sentenceCase: ! and ?');
ok(sentenceCase('checked PPE. all OK.') === 'Checked PPE. All OK.',
  'sentenceCase: interior acronyms preserved');
ok(sentenceCase('') === '' && sentenceCase(null) === '', 'sentenceCase: empty/null safe');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
