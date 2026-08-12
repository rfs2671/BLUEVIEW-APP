/**
 * THE FOURTH SHAPE: an assertion that cannot fail.
 *
 * Three times this project has had a green suite proving the wrong thing —
 * conflict markers in a file that could not compile, a config value that only
 * becomes an object after a build step no test can see, and a field name a
 * test supplied to itself. Each was a different mechanism. This is the fourth,
 * and unlike the others it is systematic rather than incidental:
 *
 *   ok(!/pattern/.test(subject), '...')
 *
 * A NEGATIVE assertion passes when the pattern is absent — and it is also
 * absent when the SUBJECT is empty, or when the PATTERN is malformed and can
 * never match anything. Positive assertions fail loudly in both cases. Negative
 * ones go green and say nothing. There are 100 of them in this suite.
 *
 * Both failure modes have already happened here, in one session:
 *
 *   * `new RegExp(\`\b${name}\s*\(\`)` written in a template literal became
 *     a literal BACKSPACE character, so the pattern could not match — the
 *     mutation it guarded survived.
 *   * `stylesBody.slice(stylesBody.indexOf('summaryRow:'))` ran open-ended to
 *     the end of the stylesheet and matched a LATER minHeight; a sibling slice
 *     whose marker was missing would have yielded '' and passed everything.
 *
 * So this file asserts the tests themselves: every marker-derived subject is
 * non-empty, and no test source contains a control character where a regex
 * escape was intended.
 *
 * Run:  node src/utils/assertionsCanFail.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.test\.(cjs|js)$/.test(e.name)) out.push(p);
  }
  return out;
}
const tests = ['src', 'app'].flatMap((r) => {
  const d = path.join(FRONTEND, r);
  return fs.existsSync(d) ? walk(d) : [];
});

console.log(`\n-- Auditing ${tests.length} test files --`);

// 1. CONTROL CHARACTERS. `\b` `\f` `\v` inside a template literal are the
//    control characters, not the regex escapes. A pattern containing one
//    cannot match source code, so any negative assertion using it is
//    unconditionally true. This is not hypothetical — it shipped twice.
const CONTROL = /[\u0008\u000b\u000c]/;
for (const f of tests) {
  const rel = path.relative(FRONTEND, f);
  ok(!CONTROL.test(fs.readFileSync(f, 'utf8')),
    `${rel} has no control character where a regex escape was meant`);
}

// 2. MARKER-DERIVED SUBJECTS. `x.slice(x.indexOf('marker'))` yields the whole
//    tail when the marker is missing (indexOf -1 → slice(-1) → last char), so
//    the subject silently shrinks to nothing useful. Every marker a test
//    slices on must actually exist in the file it slices.
const SUBJECTS = [
  ['dailyJobsiteStepper.test.cjs', 'app/logbooks/daily_jobsite.jsx',
    ['function buildStyles()', 'const renderStep1', 'const renderStep2',
      'const renderStep3', 'const renderStep4', 'const renderStep5']],
  ['stepper.test.cjs', 'src/components/logbookStepper/LogbookStepper.jsx',
    ['<View style={s.footer}>', '</SafeAreaView>', 's.progressPip,']],
];
for (const [testName, subjectFile, markers] of SUBJECTS) {
  const src = fs.readFileSync(path.join(FRONTEND, subjectFile), 'utf8');
  for (const m of markers) {
    ok(src.includes(m), `${testName}: "${m}" still exists in ${subjectFile}`);
  }
}

// 3. THE SLICES THEMSELVES ARE NON-EMPTY. Asserted by executing the same
//    expression the tests use, rather than trusting the marker check above.
const screen = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
const stylesBody = screen.slice(screen.indexOf('function buildStyles()'));
ok(stylesBody.length > 500, 'the stylesBody slice is a real stylesheet, not a tail');
for (const n of [1, 2, 3, 4, 5]) {
  const a = screen.indexOf(`const renderStep${n}`);
  const b = n < 5 ? screen.indexOf(`const renderStep${n + 1}`) : screen.indexOf('const STEPS');
  ok(a > -1 && b > a && (b - a) > 100, `the renderStep${n} slice is non-empty`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
