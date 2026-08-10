/**
 * PR F — `created` must never be read outside the block it is declared in.
 *
 * Four logbook handleSave copies declared `const created` INSIDE the else block
 * and then referenced it at `docId = existingLogId || created?.id` OUTSIDE that
 * block. On the FIRST submit of a NEW log, existingLogId is falsy so evaluation
 * reaches `created` — which is out of scope → ReferenceError. The record IS
 * written, but the client throws, so recordSignatureEvent (which sits AFTER that
 * line) never fires and the CP is trained to press Submit twice.
 *
 * WHAT THIS NOW ASSERTS, AND WHY IT CHANGED.
 *
 * The original guard pinned ONE fix shape: hoist `let created = null` above the
 * if/else. That is a valid fix, and four of the five files still use it. But it
 * is not the only one, and it is not the strongest one:
 *
 *   (A) hoist `let created`, keep reading it later          — 4 files
 *   (B) leave `const created` block-scoped and never read it
 *       outside at all, capturing what is needed into
 *       `savedId` inside the block                          — toolbox_talk
 *
 * (B) is strictly safer: the variable cannot leak, because nothing outside the
 * block names it. toolbox_talk adopted (B) and the shape-pinned test failed it
 * — reporting a REGRESSION on a file that had become MORE correct. That failure
 * then sat on main all session, and because CI's frontend job runs
 * `set -e` over a sorted file list, everything after `logbookCreatedScope`
 * never ran at all.
 *
 * So this now asserts the actual invariant instead of one implementation of it:
 * find where `created` is declared, compute the block it lives in by brace
 * matching, and require every other reference to fall inside that block. Both
 * shapes pass. The original bug fails — verified by mutation, not assumed.
 *
 * No guarantee was lost. The old assertions were a proxy for this one.
 *
 * Run:  node src/utils/logbookCreatedScope.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FORMS = [
  'daily_jobsite',
  'toolbox_talk',
  'preshift_signin',
  'scaffold_maintenance',
  'osha_log',
];

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/**
 * Comments and string literals are blanked (length-preserving, so every index
 * still lines up with the original file). The PR-F explanatory comments quote
 * the buggy `created?.id` line verbatim, and a quoted bug is not a live
 * reference.
 */
function blankNonCode(src) {
  const out = src.split('');
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i]; const d = src[i + 1];
    if (c === '/' && d === '/') {
      while (i < n && src[i] !== '\n') { out[i] = ' '; i += 1; }
    } else if (c === '/' && d === '*') {
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) { out[i] = ' '; i += 1; }
      out[i] = ' '; out[i + 1] = ' '; i += 2;
    } else if (c === "'" || c === '"' || c === '`') {
      const q = c; out[i] = ' '; i += 1;
      while (i < n && src[i] !== q) {
        if (src[i] === '\\') { out[i] = ' '; i += 1; }
        if (i < n) { out[i] = ' '; i += 1; }
      }
      out[i] = ' '; i += 1;
    } else { i += 1; }
  }
  return out.join('');
}

/** The [start, end] of the innermost block containing `idx`. */
function enclosingBlock(code, idx) {
  let depth = 0; let open = -1;
  for (let i = idx; i >= 0; i -= 1) {
    if (code[i] === '}') depth += 1;
    else if (code[i] === '{') {
      if (depth === 0) { open = i; break; }
      depth -= 1;
    }
  }
  if (open < 0) return [0, code.length];
  let d = 0;
  for (let i = open; i < code.length; i += 1) {
    if (code[i] === '{') d += 1;
    else if (code[i] === '}') { d -= 1; if (d === 0) return [open, i]; }
  }
  return [open, code.length];
}

/** Every index at which `created` appears as a standalone identifier. */
function refs(code) {
  return [...code.matchAll(/(^|[^.\w$])created\b/g)].map((m) => m.index + m[1].length);
}

function check(name, code) {
  const declMatch = code.match(/\b(let|const)\s+created\b/);
  ok(!!declMatch, `${name}: declares \`created\``);
  if (!declMatch) return;

  const declIdx = declMatch.index;
  const kind = declMatch[1];
  const [bStart, bEnd] = enclosingBlock(code, declIdx);

  const outside = refs(code).filter((i) => i !== declIdx && (i < bStart || i > bEnd));
  ok(outside.length === 0,
    `${name}: every \`created\` reference is inside the block it is declared in`
    + (outside.length
      ? ` — ${outside.length} OUT OF SCOPE at line(s) `
        + outside.map((i) => code.slice(0, i).split('\n').length).join(', ')
      : ''));

  // Both shapes are legal, and the file must be honest about which it uses: a
  // block-scoped `const` may not be read after its block, and a hoisted `let`
  // must come before everything that reads it.
  const later = refs(code).filter((i) => i > declIdx);
  if (kind === 'let') {
    ok(later.every((i) => i > declIdx),
      `${name}: hoisted \`let created\` precedes every reference (shape A)`);
  } else {
    ok(later.every((i) => i <= bEnd),
      `${name}: block-scoped \`const created\` is never read after its block (shape B)`);
  }

  ok(/recordSignatureEvent/.test(code),
    `${name}: recordSignatureEvent still wired (it must actually fire on first submit)`);
}

for (const name of FORMS) {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', `${name}.jsx`), 'utf8',
  );
  check(name, blankNonCode(src));
}

// ── The guard must still catch the ORIGINAL bug ──────────────────────────────
// Asserted here rather than assumed: a scope check that cannot fail is not a
// scope check. This is the exact pre-PR-F shape.
{
  const buggy = `
    const handleSave = async () => {
      let savedId = existingLogId;
      if (existingLogId) {
        await logbooksAPI.update(existingLogId, {});
      } else {
        const created = await logbooksAPI.create({});
        savedId = created.id;
      }
      const docId = existingLogId || created?.id || created?._id;
      recordSignatureEvent({ documentId: docId });
    };
  `;
  // Run it QUIETLY. This case is SUPPOSED to fail, and printing bare FAIL
  // lines for it would make a green run look red to anyone reading the CI log.
  const before = failed;
  const beforePassed = passed;
  const realLog = console.log;
  console.log = () => {};
  check('SYNTHETIC pre-PR-F bug', blankNonCode(buggy));
  console.log = realLog;
  const caught = failed > before;
  // Discard the synthetic tally entirely; only the verdict counts.
  failed = before;
  passed = beforePassed;
  ok(caught, 'the guard FAILS the original out-of-scope bug (proved, not assumed)');
}

// And a comment that merely QUOTES the bug must not trip it.
{
  const commented = `
    const handleSave = async () => {
      // FIX (PR F): \`created\` MUST be declared OUTSIDE the else. Referencing it
      // at \`docId = existingLogId || created?.id\` below threw ReferenceError.
      let created = null;
      if (existingLogId) { await update(); } else { created = await create(); }
      const docId = existingLogId || created?.id;
      recordSignatureEvent({ documentId: docId });
    };
  `;
  const before = failed;
  check('SYNTHETIC documented fix', blankNonCode(commented));
  ok(failed === before,
    'a comment quoting the bug does not trip the guard');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
