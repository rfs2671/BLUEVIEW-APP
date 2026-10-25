// Run: node src/utils/keyboardAvoidPadding.test.cjs
//
// KeyboardAvoidingView USES behavior="padding" EVERYWHERE, ANDROID INCLUDED.
//
// 'height' sets the view's height to (initial height - keyboard overlap) and
// re-measures the overlap from the frame it just changed. Inside a Modal the
// Android dialog window is SOFT_INPUT_ADJUST_RESIZE as well, so the window and
// the view both made room and the layout bounced: Add New User flickered
// between the full sheet and a squashed one many times a second on an
// Android phone (Mon 4:49 PM). 'padding' leaves the view's frame alone, so
// the overlap it measures is stable whether or not the window resized.
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
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
const files = walk(path.join(FRONTEND, 'app'), walk(path.join(FRONTEND, 'src'), []));
ok(files.length > 100, `the app's sources were read (${files.length})`);

const height = [];
let kavCount = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  const re = /<KeyboardAvoidingView\b([^>]*)>/g;
  let m;
  while ((m = re.exec(src))) {
    kavCount++;
    if (/['"]height['"]/.test(m[1])) height.push(path.relative(FRONTEND, f));
  }
}
ok(kavCount >= 11, `every KeyboardAvoidingView was found (${kavCount})`);
ok(height.length === 0, `none uses behavior 'height' (found: ${height.join(', ') || 'none'})`);

const sheet = fs.readFileSync(path.join(FRONTEND, 'src', 'components', 'FormSheet.jsx'), 'utf8');
ok(/<KeyboardAvoidingView\s+behavior="padding"/.test(sheet), 'FormSheet (Add New User, Edit User, …) pads for the keyboard');
ok(/fill:\s*\{\s*flex: 1,\s*backgroundColor: withAlpha\('#020617', 0\.7\)/.test(sheet),
   'FormSheet dims the whole window, including the strip the keyboard padding opens');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
