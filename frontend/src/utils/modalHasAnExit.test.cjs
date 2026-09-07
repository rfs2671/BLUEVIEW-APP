/**
 * EVERY MODAL HAS A WAY OUT.
 *
 * THE REPORT. "Records & retention — Final certificate of occupancy": once
 * opened, no close button, no dismiss, and the page behind would not scroll.
 * On the admin project page, which somebody uses daily.
 *
 * WHAT WAS ACTUALLY WRONG, and it is more interesting than "no close button":
 * there WAS one. It was the LAST child of a ScrollView that also holds two
 * C of O inputs, an attestation paragraph, a save button, a divider, the
 * no-completion block, another divider, and the whole legal-hold block with
 * its own input and button. Inside an 85%-height card on a phone it sat well
 * below the fold. The other two exits did not exist: `onRequestClose` was
 * absent so Android's hardware back did nothing, and the backdrop was a plain
 * <View> so tapping outside did nothing.
 *
 * So the only exit was the one he could not see, and "the page cannot be
 * scrolled behind it" is what a modal looks like when the thing that scrolls
 * is the modal.
 *
 * ── THE CENSUS IS WHY THIS IS NARROW ────────────────────────────────────────
 *
 * 42 modals across the app. THIRTY-NINE already passed `onRequestClose`. This
 * was one component that got it wrong and two missing only the Android
 * affordance -- not a systemic pattern, and the count is what said so. A
 * sweeping "add a close button everywhere" change would have touched 39 files
 * that were already correct.
 *
 * Run:  node src/utils/modalHasAnExit.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
let failures = 0;
function ok(label, cond, hint) {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
}
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), 'utf8')
  .split('\r\n').join('\n');

// ── the census ─────────────────────────────────────────────────────────────
function walk(dir, out = []) {
  for (const e of fs.readdirSync(path.join(FRONTEND, dir), { withFileTypes: true })) {
    const rel = `${dir}/${e.name}`;
    if (e.isDirectory()) { if (e.name !== 'node_modules') walk(rel, out); }
    else if (/\.(jsx|js)$/.test(e.name) && !/\.test\.(cjs|js)$/.test(e.name)) out.push(rel);
  }
  return out;
}
const files = [...walk('app'), ...walk('src')];
const withModals = files
  .map((f) => ({ f, src: read(f) }))
  .filter((x) => x.src.includes('<Modal'));

console.log('\nthe census');

// A WALK THAT FOUND NOTHING WOULD SATISFY EVERY ASSERTION BELOW. The count is
// this file's whole value, so it is asserted before anything is judged.
ok(`the walk found the modals (${withModals.length} files)`,
  withModals.length >= 30,
  'the tree moved, or the glob is stale — this file is checking nothing');

const totalModals = withModals.reduce(
  (n, x) => n + (x.src.match(/<Modal[\s>]/g) || []).length, 0);
ok(`and counted the modals themselves (${totalModals})`, totalModals >= 40);

// ── EVERY MODAL ANSWERS THE HARDWARE BACK BUTTON ───────────────────────────
//
// ANDROID ONLY, AND THAT IS THE POINT. On iOS a missing onRequestClose costs
// nothing, so this is invisible to anyone testing on an iPhone — which is how
// three of them shipped.
console.log('\nevery modal answers the back button');

const missing = withModals
  .filter((x) => {
    const opens = (x.src.match(/<Modal[\s>]/g) || []).length;
    const handlers = (x.src.match(/onRequestClose/g) || []).length;
    return handlers < opens;
  })
  .map((x) => x.f);

ok('no modal is missing onRequestClose', missing.length === 0,
  `Android's hardware back does nothing on: ${missing.join(', ')}`);

// ── THE ONE THAT WAS REPORTED ──────────────────────────────────────────────
console.log('\nthe retention modal has all three exits');

const RET = read('src/components/ProjectRetentionCard.jsx');

ok('the hardware back button closes it',
  /onRequestClose=\{\(\) => !saving && setEditing\(false\)\}/.test(RET));

ok('the backdrop is a Pressable that dismisses',
  /<Pressable\s+style=\{s\.modalBackdrop\}\s+onPress=\{\(\) => !saving && setEditing\(false\)\}/
    .test(RET),
  'a plain <View> backdrop swallows the tap and teaches nothing');

// WITHOUT THIS, EVERY PRESS INSIDE THE FORM CLOSES THE MODAL. The backdrop
// dismiss is only safe in company with it.
ok('and the card stops the tap from reaching it',
  /onPress=\{\(e\) => e\.stopPropagation\(\)\}/.test(RET),
  'typing in the C of O field would otherwise dismiss the form mid-edit');

// THE ACTUAL FIX. The other two are affordances; this is the one that does not
// depend on the form's length, which is the thing that will keep growing.
const header = RET.slice(RET.indexOf('s.modalHeader'), RET.indexOf('fieldLabel'));
ok('there is a close control in the HEADER, above the fold',
  /accessibilityLabel="Close"/.test(RET) && /<X size=/.test(RET),
  'a Close at the foot of a scrolling form is only reachable by scrolling it');
ok('and it is a real button to a screen reader',
  /accessibilityRole="button"/.test(RET));

// NEITHER EXIT FIRES MID-SAVE. Dismissing while a write is in flight would
// leave the admin unable to see whether the C of O — which starts a seven-year
// retention period that blocks deletion — was recorded.
ok('no exit fires while saving',
  (RET.match(/!saving && setEditing\(false\)/g) || []).length >= 3,
  'backdrop, back button and the header X must all respect `saving`');

// ── AND THE OTHER TWO, WHICH NEEDED ONLY THE BACK HANDLER ──────────────────
console.log('\nthe two that already had a visible exit');

const REVIEW = read('app/logbooks/review.jsx');
ok('review.jsx: the backdrop already dismissed',
  /<Pressable style=\{s\.modalBackdrop\} onPress=\{\(\) => setZoomImage\(null\)\}>/
    .test(REVIEW));
ok('review.jsx: and now the back button does too',
  /onRequestClose=\{\(\) => setZoomImage\(null\)\}/.test(REVIEW));

const PEND = read('app/owner/pending-deletion.jsx');
ok('pending-deletion.jsx: Cancel was always visible',
  /cancelText/.test(PEND));
ok('pending-deletion.jsx: and the back button now cancels',
  /onRequestClose=\{\(\) => \{ setConfirmTarget\(null\); setConfirmText\(''\); \}\}/
    .test(PEND),
  'it must clear the typed confirmation too, or reopening prefills it');

if (failures) {
  console.error(`\nmodalHasAnExit: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
