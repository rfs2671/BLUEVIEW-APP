/**
 * EVERY EDITOR ASKS THE SHARED RULE. NOBODY SPELLS IT AGAIN.
 *
 * `logbookEditable.js` was written after filed records were reopened and
 * overwritten, and it says so in its own docstring: three editors carried
 *
 *     const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
 *
 * which is the server's dedupe filter for IMMEDIATE types, copied without the
 * condition that makes it correct. An END_OF_DAY log is submitted and NOT
 * locked until the overnight sweep, so that predicate selects a filed record
 * and hands it to the editor as a draft.
 *
 * THE HELPER WAS WRITTEN AND THEN ADOPTED BY THREE OF TWELVE EDITORS. Nine
 * kept the inline copy for weeks afterwards. That is the defect this file
 * exists to make impossible to repeat, and it is the third instance of the
 * same shape in one week — a correct fix applied to the sibling someone was
 * reading and to none of the others (docs/audits/check-harness.md).
 *
 * A COUNT IS THE POINT, NOT THE SCAN. A checker that walks zero files passes,
 * and so does one whose glob went stale when a thirteenth editor arrived under
 * a new name. The editor count is asserted before anything else is, and the
 * forbidden pattern is proved to still match a specimen so a broken regex
 * cannot report a clean tree.
 *
 * COMMENTS ARE STRIPPED FIRST. The nine fixes each quote the predicate they
 * removed, in a comment, directly above the call that replaced it. A census
 * over raw source finds eight "violations" that are the explanations of the
 * fix. That is the same trap recorded four times over in the harness doc, and
 * it fired here on the first run.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const DIR = path.join(ROOT, 'app', 'logbooks');

/** Screens in app/logbooks that are not per-type editors. */
const NOT_EDITORS = new Set(['index.jsx', 'photos.jsx', 'review.jsx', '_layout.jsx']);

/** Block and line comments, and nothing else. Strings are left alone: the
 *  patterns below never appear inside one, and a real JS parser here would be
 *  a second thing to keep correct. */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/**
 * The one editor that does not choose ONE log to edit.
 *
 * `subcontractor_orientation` renders EVERY orientation for the project as its
 * own card, each with its own lock bar — there is no "which one is editable"
 * question for it to get wrong, which is why it never carried the inline
 * predicate. It still had the same underlying bug in a different place: its
 * lock bar read `is_locked` alone, so nine filed-but-unlocked orientations
 * showed no filed banner and no AMEND button.
 *
 * It is fixed with `isLocked || isSigned` rather than `isOpenForEditing`
 * ON PURPOSE: the shared rule would also close a SUBMITTED row carrying no
 * signature, and the sign panel directly above still offers to sign one.
 * Which of those two is right is a question about a filed record and it is
 * open, so the card does not pretend to have settled it.
 */
const EXEMPT = {
  'subcontractor_orientation.jsx':
    'renders every orientation as its own card rather than choosing one to '
    + 'edit; its lock bar uses isLocked || isSigned because isOpenForEditing '
    + 'would also close a submitted row that still needs a signature',
};

let failures = 0;
function check(name, ok, detail) {
  if (ok) return;
  failures += 1;
  console.error(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
}

const editors = fs.readdirSync(DIR)
  .filter((f) => f.endsWith('.jsx') && !NOT_EDITORS.has(f))
  .sort();

// ── THE NON-EMPTY GUARD, FIRST ──────────────────────────────────────────────
// Twelve editors exist today. `>=` so a thirteenth is welcome; a hard floor so
// a moved directory or a changed extension fails loudly instead of passing on
// an empty walk.
check('editor census is non-empty and complete',
  editors.length >= 12,
  `found ${editors.length} editors in app/logbooks: ${editors.join(', ')}`);

// ── THE FORBIDDEN PREDICATE ─────────────────────────────────────────────────
// Choosing which log to load by asking `is_locked` and nothing else. Written as
// "a .find() whose body mentions is_locked", which is the shape of every copy
// that has appeared so far, in either spelling (`!l.is_locked` and
// `l.is_locked !== true` were both live).
const INLINE_CHOICE = /\.find\(\s*\([^)]*\)\s*=>[^)]*is_locked[^)]*\)/;

// A SPECIMEN, so a regex that stopped matching cannot report a clean tree.
const SPECIMEN = 'const existing = arr.find((l) => !l.is_locked) || arr[0] || null;';
const SPECIMEN_2 = 'const existing = list.find((l) => l.is_locked !== true) || list[0] || null;';
check('the pattern still matches the code it was written for',
  INLINE_CHOICE.test(SPECIMEN) && INLINE_CHOICE.test(SPECIMEN_2),
  'the regex no longer matches either historical spelling');

let loaders = 0;
for (const file of editors) {
  const raw = fs.readFileSync(path.join(DIR, file), 'utf8');
  const code = stripComments(raw);

  check(`${file}: no inline editable predicate`,
    !INLINE_CHOICE.test(code),
    'chooses the log to load by is_locked alone — use chooseEditableLog');

  // An editor that loads the day's logs must route the choice through the
  // helper. One that does not load a list has nothing to choose between.
  if (/getByProject\s*\(/.test(code)) {
    loaders += 1;
    if (EXEMPT[file]) {
      // NAMED, NOT SILENT. A count cannot tell a deliberate exception from a
      // missed one — the lesson from the fourteenth signature call site — so
      // the exception carries its reason here and the reason is asserted to
      // exist. Removing the file from this map is what re-enables the check.
      check(`${file}: the exemption still states why`,
        typeof EXEMPT[file] === 'string' && EXEMPT[file].length > 40,
        'an exemption without a reason is a hole');
    } else {
      check(`${file}: imports the shared rule`,
        /from\s+'[^']*logbookEditable'/.test(code),
        'loads a list of logs but never asks logbookEditable');
    }
  }
}

check('list-loading editors were actually found',
  loaders >= 12,
  `only ${loaders} editors call getByProject — the detection is stale`);

if (failures) {
  console.error(`\nlogbookEditableAdoption: ${failures} failure(s)`);
  process.exit(1);
}
console.log(`logbookEditableAdoption: ${editors.length} editors, ${loaders} list-loaders, all routed through logbookEditable`);
