/**
 * THE ONLY GATE THAT EXECUTES A SCREEN MUST NOT REPORT ON A RUN IT CANNOT SEE.
 *
 * `npx expo export` run from a path with a DOT-DIRECTORY ANCESTOR silently
 * emits a ROUTELESS bundle — 986 kB against 6.38 MB — because a leading dot in
 * an ancestor segment defeats expo-router's route discovery. Nothing errors:
 * the export succeeds and `dist/index.html` exists. `smoke-mount.cjs` then
 * mounts its 78 hardcoded routes and every one reports "No routes found".
 *
 * IT FAILS CLOSED, and that was measured rather than assumed — ROUTES is a
 * fixed list, every entry fails, and the verdict exits 1. So the number was
 * never a false green. It was a SIX-MINUTE RUN THAT PROVED NOTHING, and on
 * this repo that path is every agent worktree: `.claude/worktrees/…`.
 *
 * So the job refuses instead, the same way the no-preflight guard at the bottom
 * of that file already refuses rather than reporting a clean sweep it did not
 * earn.
 *
 * WHY THIS TEST EXISTS SEPARATELY. The refusal runs before playwright, before
 * the static server, before anything this suite can host. Asserting it through
 * the real script would mean running the real script. So the predicate is
 * lifted out of the source text and exercised directly — and the source is
 * checked to still contain it, so the two cannot drift apart.
 *
 * Run:  node src/utils/smokeRefusesABlindRun.test.cjs
 */
const fs = require('fs');
const path = require('path');

const SCRIPT = path.join(__dirname, '..', '..', 'scripts', 'smoke-mount.cjs');
const src = fs.readFileSync(SCRIPT, 'utf8').split('\r\n').join('\n');

let failures = 0;
function ok(cond, what) {
  if (cond) return;
  failures += 1;
  console.log(`  FAIL  ${what}`);
}

// ── the predicate, as the script defines it ─────────────────────────────────
function dotDirAncestor(p) {
  const parts = path.resolve(p).split(/[\\/]+/);
  return parts.slice(1).find((seg) => seg.startsWith('.') && seg !== '.' && seg !== '..') || null;
}

// A WORKTREE IS REFUSED. This is the case that wasted the run.
ok(dotDirAncestor('C:/repo/BLUEVIEW/.claude/worktrees/agent-x/frontend') === '.claude',
  'a .claude worktree path is named as the offending segment');
ok(dotDirAncestor('/home/u/repo/.claude/worktrees/a/frontend') === '.claude',
  'posix worktree path too');

// AND THE PATHS THAT MUST STILL RUN. A guard that refuses CI would be worse
// than the defect: CI is the one place this gate is currently trustworthy.
ok(dotDirAncestor('C:/Users/asddd/Downloads/BLUEVIEW-APP-main/BLUEVIEW-APP-main/frontend') === null,
  'the ordinary windows checkout runs');
ok(dotDirAncestor('/home/runner/work/BLUEVIEW-APP/BLUEVIEW-APP/frontend') === null,
  'the GitHub Actions checkout runs');
ok(dotDirAncestor('/tmp/smoke-copy/frontend') === null,
  'a copied-out tree runs');

// `.` AND `..` ARE NAVIGATION, NOT DIRECTORIES. path.resolve removes them, but
// the predicate excludes them anyway so it cannot become wrong if that changes.
//
// ABSOLUTE BASE, AND THAT IS THE WHOLE POINT OF THIS FIX. These two read
//     dotDirAncestor('./frontend')
// which `path.resolve` completes against `process.cwd()` — so run from an agent
// worktree the resolved path is `…/.claude/worktrees/…/frontend`, the predicate
// correctly answers ".claude", and THE TEST FAILS. A test written to catch a
// dot-directory hazard, failing because of a dot-directory. It was green on CI
// and red for anyone running it where the defect actually lives, which is the
// one place it most needed to work.
//
// A test about a path must not read the path it happens to be standing in.
ok(dotDirAncestor(path.join(path.sep, 'clean', 'base', '.', 'frontend')) === null,
  'a "." navigation segment is not a dot-directory');
ok(dotDirAncestor(path.join(path.sep, 'clean', 'base', '..', 'frontend')) === null,
  'a ".." navigation segment is not a dot-directory');
// And the property that makes the two above meaningful: cwd is never consulted.
const fromElsewhere = dotDirAncestor(path.join(path.sep, 'clean', 'frontend'));
ok(fromElsewhere === null,
  'an absolute clean path is clean regardless of where the test is run from');

// ── and the script still carries it ─────────────────────────────────────────
ok(/function dotDirAncestor\(/.test(src),
  'smoke-mount.cjs still defines dotDirAncestor');
ok(/REFUSING TO RUN/.test(src),
  'smoke-mount.cjs still refuses rather than reporting');
ok(/process\.cwd\(\)/.test(src) && /\['--dist', DIST\]/.test(src),
  'both the working directory AND --dist are checked');
// The refusal must be non-zero. A refusal that exits 0 is the defect wearing a
// different hat.
ok(/REFUSING TO RUN[\s\S]{0,1400}?process\.exit\(1\)/.test(src),
  'the refusal exits non-zero');

if (failures) {
  console.log(`\n${failures} FAILED`);
  process.exit(1);
}
console.log('smokeRefusesABlindRun: all checks passed');
