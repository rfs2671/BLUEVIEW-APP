/**
 * THE COUNT HAS TO LEAVE THE SCREEN THAT ALREADY SHOWS IT.
 *
 * files.jsx renders "N files not on site tablets" in amber, and that card is
 * what makes the explicit-selection model safe — an admin can see the backlog
 * he now has to work through. But it is only visible to someone who opened
 * Plans & Files. The operator named the failure that leaves:
 *
 *   "An admin who never opens Plans & Files will never see the count, and then
 *    the tablet silently falls behind instead of silently running ahead."
 *
 * So the count goes on the project detail screen, and it goes on the row that
 * is ALREADY THERE — the admin-only FILES row that already deep-links to
 * /projects/{id}/files. A second row would be a second thing to scroll past;
 * the row that says "open the project files" is the one place a reader is
 * already being told the state of the files.
 *
 * WHAT THIS FILE PINS, and why each one is a bug that has shipped before:
 *
 *  1. The screen reads the count off the project it already fetched. If it
 *     grew its own dropboxAPI call it would download every file row on the
 *     project to compute one integer, on a screen that already makes seven
 *     requests.
 *
 *  2. Zero, unknown and N are three different answers. This codebase has an
 *     invariant, written down in four places, that a failed or pending read
 *     renders "—" and NEVER a fabricated 0 (index.jsx:622-626,
 *     project/[id].jsx:698-704). Here the safe shape is different but the
 *     rule is the same: the count only speaks when it has a number. An admin
 *     reading a cached project doc from before this shipped must not be told
 *     that nothing is waiting.
 *
 *  3. The screen refetches on focus. Without it the amber count is stale at
 *     the exact moment it matters most — the admin publishes the files, hits
 *     back, and the row still claims they are waiting. That is a lie the
 *     feature tells about its own subject.
 *
 *  4. The wording does not allege a fault. Files awaiting selection are the
 *     normal state of a correct system. "3 files missing from site tablets"
 *     and "3 files awaiting selection" are the same integer and only one of
 *     them is true.
 *
 *  5. The mount smoke executes /projects/{id}/files. The per-file branch
 *     rewrote that screen end to end and no gate in CI has ever mounted it —
 *     it is the one screen this whole feature points at.
 *
 * Run:  node src/utils/unpublishedCountSurfacing.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8');

const detail = read('app', 'project', '[id].jsx');
const smoke = read('scripts', 'smoke-mount.cjs');

const FIELD = 'files_awaiting_site_selection';

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The FILES block: from the section label to the end of its Pressable. Every
// assertion about placement is scoped to this slice, so a match somewhere
// else on a 2300-line screen cannot pass the test for the wrong reason.
function filesBlock() {
  const start = detail.indexOf('s.sectionLabel}>FILES<');
  if (start === -1) return '';
  const end = detail.indexOf('ON-SITE WORKERS', start);
  return detail.slice(start, end === -1 ? start + 4000 : end);
}

// Comments stripped BEFORE any copy assertion. A note explaining why the row
// must not read as an error contains the word "error", and a naive scan makes
// the explanation fail the rule it is explaining.
function renderedCopy(src) {
  return src
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, ' ');
}

console.log('\n1. The count rides on the project the screen already fetched');

ok(new RegExp(`\\b${FIELD}\\b`).test(detail),
  `project/[id].jsx reads ${FIELD} off the project document`);

ok(!/dropboxAPI/.test(detail),
  'no dropboxAPI import — the screen does not download every file row to count them');

console.log('\n2. The count is rendered on the existing FILES row');

const block = filesBlock();
ok(block.length > 0, 'the FILES section is still present on the screen');

ok(new RegExp(`${FIELD}|awaiting`).test(block),
  'the FILES row itself carries the count, not some new section elsewhere');

ok(/router\.push\(`\/projects\/\$\{projectId\}\/files`\)/.test(block),
  'the row still deep-links into Plans & Files');

console.log('\n3. Zero, unknown and N are three different answers');

// A count that only renders when it is a positive number cannot assert a
// fabricated zero. The guard has to test the NUMBER, not truthiness of the
// field alone — `project?.x && ...` renders the literal 0 in React Native.
ok(/awaitingSelection\s*>\s*0/.test(detail),
  'the badge is guarded on > 0, so a 0 is never rendered as a bare numeral');

ok(new RegExp(`typeof\\s+[\\w?.]*${FIELD}\\s*===\\s*'number'`).test(detail)
   || /Number\.isFinite\(/.test(detail),
  'an absent count (cached doc, non-admin) is distinguished from zero');

console.log('\n4. The screen refetches so a cleared backlog stops claiming');

ok(/useFocusEffect/.test(detail),
  'project/[id].jsx registers a focus effect');

ok(/from 'expo-router'/.test(detail) &&
   /import \{[^}]*\buseFocusEffect\b[^}]*\} from 'expo-router';/.test(detail),
  'useFocusEffect is imported from expo-router');

console.log('\n5. The wording does not allege a fault');

// Scoped to the strings the FILES row renders. 'unpublished' is deliberately
// NOT a fault word — it is the state's own name and the ruling's vocabulary.
const FAULT = ['missing', 'error', 'failed', 'problem', 'overdue', 'not synced',
  'broken', 'invalid'];
const copy = renderedCopy(block).toLowerCase().replace(/\s+/g, ' ');
FAULT.forEach((w) => ok(!copy.includes(w),
  `the FILES row copy does not call a normal state ${JSON.stringify(w)}`));

// Whitespace-collapsed: JSX wraps this sentence across source lines and
// renders it as one.
ok(/awaiting\s+selection|awaiting\s+a\s+choice|await\s+selection/i.test(block),
  'the row says the files are awaiting selection');

ok(/nothing\s+goes\s+to\s+site\s+tablets\s+until|never\s+published\s+automatic/i
  .test(renderedCopy(block).replace(/\s+/g, ' ')),
  'the row says selection is the designed behaviour, not a backlog it is scolding about');

console.log('\n6. The mount smoke executes the screen this all points at');

ok(/'\/projects\/p1\/files'/.test(smoke),
  'smoke-mount.cjs mounts /projects/p1/files');

ok(/dropbox-files/.test(smoke),
  'the stub answers GET /dropbox-files, or the files screen mounts against a 404 shape');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
