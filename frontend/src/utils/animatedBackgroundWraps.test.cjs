// Run: node src/utils/animatedBackgroundWraps.test.cjs
//
// AnimatedBackground WRAPS A SCREEN; IT IS NEVER A SIBLING OF ONE.
//
// Its root is `{ flex: 1 }` in normal flow (the gradient inside it is the
// absolutely-filled part). Rendered self-closed NEXT TO a screen's
// SafeAreaView, the two split the column: the background took the top half of
// the phone and the screen was pushed into the bottom half. That shipped on
// Project → Reports, Search, Upcoming and Voice log (Mon 3:47 PM, iPhone).
// Every screen renders `<AnimatedBackground> … </AnimatedBackground>`.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..', 'app');
let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}
function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) walk(p, out);
    else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}
const files = walk(ROOT, []);
const selfClosed = files.filter((f) => /<AnimatedBackground\b[^>]*\/>/.test(fs.readFileSync(f, 'utf8')));
ok(files.length > 50, `the app's screens were read (${files.length})`);
ok(selfClosed.length === 0,
   `no screen renders <AnimatedBackground /> beside its content (found: ${selfClosed.map((f) => path.relative(ROOT, f)).join(', ') || 'none'})`);
for (const f of ['reports', 'search', 'upcoming', 'voice-log']) {
  const src = fs.readFileSync(path.join(ROOT, 'projects', '[id]', `${f}.jsx`), 'utf8');
  ok(/<AnimatedBackground>\s*<SafeAreaView/.test(src), `projects/[id]/${f}: the screen sits inside the background`);
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
