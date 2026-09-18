/**
 * THE SCREEN ASKS FOR THE THING THE CP SIGNS FOR.
 *
 * The pre-shift sheet's two Y/N questions were subjectless fragments:
 *
 *     "Injury / Incident last time?"
 *     "Inspected PPE today?"
 *
 * The attestation the CP signs over those same two answers is not a fragment.
 * It asserts an ACT, performed by him, on each man:
 *
 *     "Each worker named below ... was asked, before starting work, whether
 *      there was an injury or incident on their last shift and whether they
 *      inspected their PPE for today."
 *
 * A fragment has no subject, so the reader supplies one, and the operator
 * supplied the wrong one: he read "Injury / Incident last time?" as the WORKER
 * self-reporting at the gate, which made the question look like a duplicate of
 * the gate affirmation and very nearly got it deleted. It is not a duplicate --
 * there are four YES answers in production and the attestation claims the
 * asking happened -- so the wording, not the question, was the defect.
 *
 * WHAT THIS FILE PINS, and it is one thing: the two labels speak the
 * attestation's own words, DERIVED FROM THE ATTESTATION rather than typed
 * twice here. If either sentence is reworded, this fails and the other has to
 * be looked at. That is the whole point -- a copy of a sentence is a second
 * sentence the moment one of them is edited, which is the reason
 * attestations.py gives for holding the text in one place to begin with.
 *
 * AND WHAT IT PINS ABOUT THE RECORD: nothing moved. `had_injury` and
 * `inspected_ppe` keep their names, the Required-field affordance and the
 * submit gate still read them, and attestations.py is untouched and NOT
 * re-versioned. This was a change to what the CP READS, never to what is
 * stored, filed or attested. Asserted here so "copy only" is a checked claim
 * rather than a sentence in a PR body.
 *
 * Source scan, the house pattern, comments stripped for the reason recorded in
 * fix1FlaggedWorkerSurfaces.test.cjs: this repo has three times had a source
 * assertion pass on the prose DESCRIBING the behaviour instead of the
 * behaviour, and the header above quotes both old labels in full -- so reading
 * this screen raw would let the quotes satisfy the assertions that the old
 * wording is gone.
 *
 * Run:  node src/utils/preshiftQuestionsAskWhatIsAttested.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

// Conservative, and the same shape the neighbouring guards use: block
// comments, JSX comment wrappers, and lines whose first non-space characters
// are `//` or `*`. It does not parse strings, so a URL inside code survives.
const stripComments = (src) => src
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n')
  .filter((l) => !/^\s*(\/\/|\*)/.test(l))
  .join('\n');

const SCREEN_PATH = path.join(FRONTEND, 'app', 'logbooks', 'preshift_signin.jsx');
const ATTEST_PATH = path.join(REPO, 'backend', 'lib', 'logbook', 'attestations.py');

const screenRaw = fs.readFileSync(SCREEN_PATH, 'utf8');
const screen = stripComments(screenRaw);
const attest = fs.readFileSync(ATTEST_PATH, 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── THE INSTRUMENT'S OWN GUARD ──────────────────────────────────────────────
// Every assertion below is a substring test against one of two files. An empty
// or truncated subject would make the NEGATIVE ones pass silently and the
// positive ones fail for the wrong reason, so both subjects are proved present
// first. See assertionsCanFail.test.cjs for why this is not optional here.
ok(screen.length > 1000, 'subject present: the pre-shift screen was read and stripped');
ok(attest.length > 1000, 'subject present: attestations.py was read');

// ── The attestation is the source, and it says an ASKING happened ───────────
console.log('\nthe attestation names an act of asking, and names it in three parts');

// Pulled out of the file rather than retyped, so a reworded attestation breaks
// this instead of quietly disagreeing with the screen.
const PRESHIFT_V1 = (/_PRESHIFT_V1 = \(([\s\S]*?)\n\)/.exec(attest) || [])[1] || '';
ok(PRESHIFT_V1.length > 200,
  'the pre-shift attestation was located in attestations.py (not retyped here)');
const attestText = PRESHIFT_V1.replace(/\s+/g, ' ');

ok(/was asked, before starting work/.test(attestText),
  'it claims the worker WAS ASKED -- the CP performs the act, the worker answers');

// The three phrases the screen has to be able to speak. Each is asserted to be
// IN the attestation first, so a typo here fails loudly rather than making the
// screen check vacuous.
const PHRASES = [
  ['injury or incident', 'the injury question\'s subject matter'],
  ['last shift', 'WHEN the injury question is about -- not "last time"'],
  ['PPE for today', 'WHEN the PPE question is about'],
];
for (const [phrase, what] of PHRASES) {
  ok(attestText.includes(phrase),
    `the attestation says "${phrase}" -- ${what}`);
}

// ── The screen speaks those words back ──────────────────────────────────────
console.log('\nthe two labels on the screen use the attestation\'s words');

// The labels, taken from the rendered elements rather than from anywhere else
// on the screen, so a match in an unrelated string cannot satisfy these.
const labels = (screen.match(/<Text style=\{styles\.ynLabel\}>([^<]*)<\/Text>/g) || [])
  .map((m) => /<Text style=\{styles\.ynLabel\}>([^<]*)<\/Text>/.exec(m)[1].trim());
ok(labels.length === 2,
  `both Y/N labels were found on the screen (${labels.length} of 2)`);
const bothLabels = labels.join(' | ');

// THE FRAGMENTS ARE GONE. A label with no subject is what let the question be
// read as the worker speaking for himself.
ok(/Ask the worker:/.test(labels[0] || '') && /Ask the worker:/.test(labels[1] || ''),
  'each label names WHO is asking and WHO answers -- the CP asks, the worker '
  + 'answers (this is the defect: the operator read the old fragment as the '
  + 'worker self-reporting at the gate, and so it looked duplicated)');
ok(!/Injury \/ Incident last time\?/.test(screen),
  'the old subjectless injury fragment is gone from the CODE (not merely from '
  + 'a comment -- see stripComments above)');
ok(!/Inspected PPE today\?/.test(screen),
  'and so is the old subjectless PPE fragment');

for (const [phrase, what] of PHRASES) {
  ok(bothLabels.includes(phrase),
    `the labels say "${phrase}", the attestation's own words -- ${what}`);
}

// "last time" was the word that did not match. It is the one the attestation
// never uses, and the one that made the question answerable about any past.
ok(!/last time/i.test(bothLabels),
  '"last time" is gone -- the attestation says "last shift" and the CP is now '
  + 'asked on screen for the thing he signs for');

// ── COPY ONLY. The record did not move. ─────────────────────────────────────
console.log('\nnothing but the words changed');

ok(/'had_injury'/.test(screen) && /'inspected_ppe'/.test(screen),
  'the two stored field names are unchanged');
ok(/const answeredBoth =/.test(screen),
  'the submit gate is still there and still named answeredBoth');
ok(/Required field/.test(screen),
  'the Required-field affordance is still rendered');
// The gate and the marker must keep reading the SAME two fields the labels ask
// about; submitSignatureGate.test.cjs owns the detail of how. Here it is only
// asserted that the rename did not happen, because a label change that quietly
// repointed the toggles would be the worst possible version of this PR.
ok(/updateWorker\(index, 'had_injury', v\)/.test(screen)
  && /updateWorker\(index, 'inspected_ppe', v\)/.test(screen),
  'each toggle still writes the field its label asks about');

// attestations.py is a stored, versioned, printed sentence. A copy change on a
// screen must not touch it, and must not mint a v2.
ok(/_PRESHIFT_V1/.test(attest) && !/_PRESHIFT_V2/.test(attest),
  'the attestation is NOT re-versioned -- the sentence the CP signs is '
  + 'unchanged, because nothing about what is claimed changed');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
