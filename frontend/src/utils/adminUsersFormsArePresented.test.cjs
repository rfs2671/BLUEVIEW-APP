/**
 * A FORM CALLED A MODAL IS NOT A MODAL.
 *
 * ── THE REPORT ──────────────────────────────────────────────────────────────
 *
 * "Edit, Registration and Assign all work but render at the bottom of the
 * page, invisible on mobile." From the operator, on a phone, about
 * app/admin/users.jsx.
 *
 * ── WHAT WAS ACTUALLY WRONG ────────────────────────────────────────────────
 *
 * The screen had four states called `showAddModal`, `showEditModal`,
 * `showAssignModal` and `showCsModal`, and the file opened no React Native
 * Modal at all — a grep for the opening tag returned zero. All four rendered
 * as `{cond && <GlassCard>}` blocks at the TAIL of the page's ScrollView,
 * after the user list, styled with a `modal` rule whose entire content was
 * `marginTop: spacing.xl`.
 *
 * So the forms did work. They opened a screen-height below the fold, under a
 * list of user cards, and on a phone the admin tapped a button and nothing
 * appeared to happen. On a laptop with three users the block lands near the
 * fold, which is why this read as working for as long as it did.
 *
 * THE NAMING IS THE WHOLE LESSON. Nothing in the tree made those blocks
 * modals; only the identifiers said so, and identifiers are not a
 * presentation. Every static gate in this repo was green, and the mount smoke
 * — the only thing here that executes a screen — asks "did it throw", which a
 * form rendered in the wrong place does not.
 *
 * ── WHY THIS IS AN INVARIANT AND NOT A LIST OF FOUR ────────────────────────
 *
 * Asserting "these four names are wired to a FormSheet" would pass forever
 * while a FIFTH `showSomethingModal` is added the old way — which is exactly
 * how the fourth one got there. So the census is DERIVED: every `show*Modal`
 * state this screen declares must be presented, and the numbers are printed
 * so a walk that found nothing cannot report success.
 *
 * Run:  node frontend/src/utils/adminUsersFormsArePresented.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => {
  const f = path.join(FRONTEND, ...p);
  if (!fs.existsSync(f)) return null;
  return fs.readFileSync(f, 'utf8').split('\r\n').join('\n');
};

/**
 * Prose out, so an assertion is about what the file DOES.
 *
 * This is not optional here and the reason is in this very file: the screen's
 * own comment explains the bug by naming the tag it used to be missing, and a
 * scan that counted that sentence would find a modal in a paragraph about not
 * having one. src/utils/modalHasAnExit.test.cjs counts opening tags in raw
 * source and would do exactly that.
 */
const CODE = (s) => s
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const USERS_RAW = read('app', 'admin', 'users.jsx');
const SHEET_RAW = read('src', 'components', 'FormSheet.jsx');

let passed = 0;
let failed = 0;
function ok(cond, label, hint) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${hint ? `\n          ${hint}` : ''}`);
}

console.log('\n-- the subjects exist at all --');
ok(USERS_RAW !== null, 'ANCHOR: app/admin/users.jsx is readable');
ok(SHEET_RAW !== null, 'the shared sheet exists: src/components/FormSheet.jsx',
  'the four forms have nothing to be presented BY');

const USERS = USERS_RAW ? CODE(USERS_RAW) : '';
const SHEET = SHEET_RAW ? CODE(SHEET_RAW) : '';

// ── 1. THE DERIVED CENSUS ───────────────────────────────────────────────────
console.log('\n-- every form this screen opens is presented over the viewport --');
{
  const declared = [...USERS.matchAll(/const \[(show[A-Za-z]*Modal), set/g)]
    .map((m) => m[1]);
  const unique = [...new Set(declared)];

  // A WALK THAT FOUND NOTHING SATISFIES EVERY ASSERTION BELOW IT. The four
  // that were reported are the floor; the point of deriving is that a fifth
  // joins the rule automatically, not that the number is free to shrink.
  ok(unique.length >= 4,
    `ANCHOR: the screen declares its form states (${unique.length}: ${unique.join(', ')})`,
    'the states were renamed — this file is checking nothing');

  const unpresented = unique.filter(
    (name) => !new RegExp(`visible=\\{${name}\\}`).test(USERS),
  );
  ok(unpresented.length === 0,
    'each of them drives a FormSheet\'s `visible`',
    `still rendered inline, i.e. below the fold on a phone: ${unpresented.join(', ')}`);

  const sheets = (USERS.match(/<FormSheet[\s>]/g) || []).length;
  ok(sheets === unique.length,
    `and there is one sheet per form state (${sheets} sheets, ${unique.length} states)`,
    'a state with no sheet, or a sheet with no state');
}

// ── 2. OVER THE PAGE, NOT INSIDE IT ─────────────────────────────────────────
console.log('\n-- the sheets are siblings of the list, not children of it --');
{
  // THE ACTUAL DEFECT, stated positionally. A Modal nested in the scrolling
  // list is a modal whose mount point scrolls; every one of these used to be
  // the last child of that ScrollView.
  const closeScroll = USERS.lastIndexOf('</ScrollView>');
  ok(closeScroll > -1, 'ANCHOR: the page still has a ScrollView');
  const firstSheet = USERS.indexOf('<FormSheet');
  ok(firstSheet > closeScroll,
    'every sheet opens after </ScrollView> closes',
    'a form inside the scrolling list is a form the reader has to scroll to '
    + '— which is the bug');

  // And nothing was left behind in the old shape.
  ok(!/variant="modal"/.test(USERS),
    'no GlassCard variant="modal" block survives in the page body',
    'that was the old inline form; inside a real Modal it is a blur with '
    + 'nothing behind it to blur');
}

// ── 3. THE FOCUS ────────────────────────────────────────────────────────────
console.log('\n-- it focuses when it opens --');
{
  ok(/initialFocusRef/.test(SHEET) && /\.focus\(\)/.test(SHEET),
    'FormSheet focuses something when it becomes visible');
  ok(/cardRef\.current/.test(SHEET),
    'and falls back to the sheet itself when the caller names no field',
    'a sheet with no text input would otherwise leave focus on the page '
    + 'behind it, so the next Tab walks a list the user cannot see');

  // AFTER THE PRESENTATION, NOT DURING IT. On native the Modal is a window
  // that does not exist on the render that sets `visible`; focusing an input
  // that is not mounted is a no-op that fails silently.
  ok(/setTimeout\(/.test(SHEET),
    'the focus is deferred past the presentation, not fired on the same render');

  const withRef = (USERS.match(/initialFocusRef=\{/g) || []).length;
  ok(withRef >= 3,
    `and the screen names a first field on the sheets that have one (${withRef})`,
    'Add, Edit and Assign each have a first field; the CS sheet opens on a '
    + 'spinner and has none');
  ok(/ref=\{addNameRef\}/.test(USERS) && /ref=\{editNameRef\}/.test(USERS),
    'the Add and Edit sheets put the caret in the name field');
}

// ── 4. THE SCROLL LOCK ──────────────────────────────────────────────────────
console.log('\n-- the page behind it does not scroll --');
{
  ok(/overflow\s*=\s*'hidden'/.test(SHEET),
    'FormSheet pins the document scroller while a sheet is up');
  ok(/document\.documentElement/.test(SHEET),
    'both the body and the root element, since either can be the scroller');

  // A BOOLEAN WOULD BE WRONG HERE and it is worth a test rather than a
  // comment: two sheets can be mounted at once, and the first to close would
  // unlock the page underneath the second.
  ok(/pageLockCount/.test(SHEET),
    'a counter, not a flag, so one sheet closing does not unlock another');
  ok(/pageLockCount === 0\) return/.test(SHEET),
    'and the counter is never driven negative — a -1 would make the NEXT '
    + 'lock a silent no-op');

  // RESTORED, not hardcoded back to a guess.
  ok(/savedOverflow/.test(SHEET),
    'the previous overflow is restored rather than assumed');
}

// ── 5. THE EXITS, IN THE SPELLING THE HOUSE ALREADY USES ────────────────────
console.log('\n-- it dismisses the way the rest of the app dismisses things --');
{
  // Not a new convention: this is the set src/utils/modalHasAnExit.test.cjs
  // names as complete, in ProjectRetentionCard.jsx's spelling.
  ok(/onRequestClose=\{onClose\}/.test(SHEET),
    "Android's hardware back, and Escape on web");
  ok(/style=\{s\.backdrop\}\s*onPress=\{onClose\}/.test(SHEET),
    'a Pressable backdrop dismisses on a tap outside');
  ok(/onPress=\{\(e\) => e\.stopPropagation\(\)\}/.test(SHEET),
    'and the card stops the tap, or every press inside the form would dismiss it');
  ok(/accessibilityLabel="Close"/.test(SHEET) && /accessibilityRole="button"/.test(SHEET),
    'a real Close button to a screen reader');

  // THE ONE THAT DOES NOT ROT AS THE FORM GROWS. A Close under a scrolling
  // body is only reachable by scrolling to it.
  const header = SHEET.slice(SHEET.indexOf('s.header'), SHEET.indexOf('s.body'));
  ok(header.length > 100, 'ANCHOR: the header slice is non-empty');
  ok(/accessibilityLabel="Close"/.test(header),
    'and it is in the HEADER, above the scrolling body');
}

// ── 6. A REFUSAL RAISED FROM A SHEET IS STILL READABLE ──────────────────────
console.log('\n-- the sheets can still show their own refusals --');
{
  // Nothing in the app's view tree paints above a native Modal, toasts
  // included — src/utils/toastInsideModals.test.cjs is the argument in full.
  // These forms raise every refusal they have as a toast, so moving them into
  // a Modal without a second mount point would trade a form below the fold
  // for a form that refuses silently.
  ok(/<ToastHost \/>/.test(SHEET),
    'FormSheet mounts a ToastHost inside the sheet window');
  ok(/toast\.error\(/.test(USERS),
    'ANCHOR: the screen really does raise its refusals as toasts');
}

// ── 7. THE de2b330 GUARD ────────────────────────────────────────────────────
console.log('\n-- nothing declares a component inside the render body --');
{
  // de2b330 (#388), "the keyboard stopped closing after every character he
  // typed": Field, CorrectionChoice and EntryList were declared inside a
  // screen's function body and used as JSX element types. A function
  // expression in a render body is a NEW OBJECT every render; React compares
  // element types by reference, so the subtree unmounted and rebuilt on every
  // keystroke, destroying the TextInput. These sheets are full of text inputs.
  //
  // The check is by CAPITAL LETTER, because that is the same thing JSX uses to
  // tell an element type from a host tag.
  for (const [label, src] of [['users.jsx', USERS], ['FormSheet.jsx', SHEET]]) {
    const bodyStart = src.indexOf('export default function');
    const inner = bodyStart > -1 ? src.slice(bodyStart) : '';
    const declared = [...inner.matchAll(/^\s{2,}const ([A-Z][A-Za-z0-9]*)\s*=\s*(\(|function)/gm)]
      .map((m) => m[1]);
    const usedAsType = declared.filter((n) => new RegExp(`<${n}[\\s/>]`).test(inner));
    ok(usedAsType.length === 0,
      `${label}: no nested component is used as an element type`,
      `declared in a render body and rendered as <Name>: ${usedAsType.join(', ')} `
      + '— a new object every render, so the TextInputs underneath are destroyed '
      + 'on every keystroke (de2b330)');
  }

  // The two render helpers on this screen are CALLED, not used as types, and
  // that is the distinction the bug turns on. If either ever becomes a
  // component it must move to module scope.
  ok(/\{renderRolePicker\(\)\}/.test(USERS) && /\{renderLicenceFields\(\)\}/.test(USERS),
    'the role picker and licence block are called, not rendered as <Component>');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
