/**
 * Every screen and module actually PARSES.
 *
 * WHY THIS EXISTS. A merge left conflict markers in daily_jobsite.jsx —
 * `<<<<<<< HEAD`, both sides, `>>>>>>> origin/main` — and the 247-assertion
 * stepper suite passed anyway. Every test in this repo reads source as TEXT
 * and greps it, so a file that cannot compile still satisfies them: the
 * markers sat between two style blocks and every pattern the suite looks for
 * was present on one side or the other.
 *
 * The mount smoke would have caught it, but only in CI, three minutes in, and
 * only for routes it visits. This catches it in under a second, locally, for
 * every file.
 *
 * It asserts nothing about behaviour. It asserts the source is source.
 *
 * Run:  node src/utils/sourceParses.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const ROOTS = ['app', 'src'];
const SKIP = new Set(['node_modules', '.expo', 'dist', 'build']);

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(jsx?|cjs)$/.test(entry.name)) out.push(full);
  }
  return out;
}

const files = ROOTS.flatMap((r) => walk(path.join(FRONTEND, r)));
console.log(`\n-- Parsing ${files.length} source files --`);

// A conflict marker is the specific failure that prompted this file, so it is
// named rather than left to surface as a generic syntax error.
const MARKER = /^(?:<{7}|={7}|>{7})(?:\s|$)/m;
for (const f of files) {
  const rel = path.relative(FRONTEND, f);
  const src = fs.readFileSync(f, 'utf8');
  ok(!MARKER.test(src), `${rel} has no unresolved merge conflict markers`);
  try {
    babel.transformSync(src, {
      filename: f,
      presets: [['@babel/preset-react', { runtime: 'automatic' }]],
      configFile: false,
      babelrc: false,
    });
    ok(true, rel);
  } catch (e) {
    ok(false, `${rel} parses — ${String(e.message).split('\n')[0]}`);
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
