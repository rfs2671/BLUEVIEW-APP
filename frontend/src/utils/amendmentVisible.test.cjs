/**
 * The CP is told a correction was filed, by whom, and why — and is not told
 * he failed to sign something he signed.
 *
 * TWO SURFACES, ONE FACT.
 *
 * 1. THE CARD on the logbooks screen. Its `unsigned` sentence is "never
 *    signed - still open and still yours to finish", and for an amendment that
 *    is FALSE: he signed that log, and a correction he did not make cleared the
 *    signature. The app was about to tell a man he failed to do a thing he did.
 *
 * 2. THE BANNER on the editor, ABOVE the form. LogbookStepper renders
 *    LogbookLockBar after the step content; a banner answering "why am I
 *    signing again" that sits below the thing he is being asked to sign has
 *    already failed.
 *
 * THREE STATES on both, because amend_logbook refuses a reasonless amendment
 * but a script or a direct write can create one — and this codebase spent
 * 2026-08-31 on exactly that class of row.
 *
 * NOTHING IS RELATIVE TO TODAY. Every value comes off the amendment document,
 * so an amendment filed in September for an August log reads the same in
 * December.
 *
 * Run:  node src/utils/amendmentVisible.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const INDEX = read('app', 'logbooks', 'index.jsx');
const BANNER = read('src', 'components', 'AmendmentBanner.jsx');
const STEPPER = read('src', 'components', 'logbookStepper', 'LogbookStepper.jsx');
const EDITOR = read('app', 'logbooks', 'daily_jobsite.jsx');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. THE CARD NO LONGER ACCUSES HIM');
{
  ok(/state === 'amendment_unsigned'/.test(INDEX),
    'the card knows the third state');
  ok(/gapsAmended/.test(INDEX), 'and separates those rows from the unsigned ones');

  // The false sentence must not be reachable for an amendment row.
  const unsignedBlock = INDEX.slice(INDEX.indexOf('gapsUnsigned.length > 0'),
    INDEX.indexOf('gapsUnaffirmed.length > 0'));
  ok(/never signed/.test(unsignedBlock),
    'the unsigned sentence still exists for genuinely unsigned logs');
  ok(!/never signed/.test(INDEX.slice(INDEX.indexOf('gapsAmended.map'),
    INDEX.indexOf('gapsOldestFirst.map'))),
  'and is NOT what an amendment row renders');

  ok(/correction to sign/.test(INDEX),
    'the row label reads "correction to sign", not "never signed"');
}

console.log('\n2. THE CARD SAYS WHO AND WHY');
{
  // THE RENDERER MOVED. The card built this sentence inline and produced
  // "…on 2026-08-14. Photo Review it and sign." — a stored fragment glued to
  // the next clause. It now delegates to amendmentSentence in the shared
  // module, so these assertions follow it there rather than re-testing a
  // template the screen no longer owns. The intent is unchanged: the card
  // names the author, branches on whether a reason was recorded, and says so
  // when none was.
  const fn = fs.readFileSync(
    path.join(FRONTEND, 'src', 'utils', 'amendmentChain.js'), 'utf8',
  ).split('\r\n').join('\n');
  ok(/amendmentSentence/.test(INDEX),
    'the card delegates to the shared renderer');
  ok(/a\.by/.test(fn) && /a\.at/.test(fn), 'it names the author and the date');
  ok(/has_reason/.test(fn), 'it branches on whether a reason was recorded');
  ok(/No reason was recorded/.test(fn),
    'and SAYS SO when none was, rather than printing an empty quotation');
  ok(!/today|yesterday|ago/i.test(fn),
    'nothing in it is relative to today');
}

console.log('\n3. THE BANNER IS ABOVE THE FORM');
{
  const i = STEPPER.indexOf('<AmendmentBanner');
  const j = STEPPER.indexOf('current.render()');
  const k = STEPPER.indexOf('<LogbookLockBar');
  ok(i > 0 && j > 0 && i < j,
    'the banner renders BEFORE the step content');
  ok(k > i, 'and the lock bar still renders after it, where it belongs');
  ok(/amendment = null,/.test(STEPPER),
    'the prop defaults to null so an ordinary log renders nothing');
  ok(STEPPER.indexOf('<AmendmentBanner') < STEPPER.indexOf("pointerEvents={locked"),
    'and it sits OUTSIDE the locked pointerEvents wrapper — an explanation '
    + 'a locked log makes non-interactive is not an explanation');
}

console.log('\n4. THE BANNER RENDERS NOTHING WHEN THERE IS NO AMENDMENT');
{
  ok(/if \(!amendment\) return null;/.test(BANNER),
    'no amendment, no banner — the third state');
  ok(/has_reason && amendment\.reason/.test(BANNER),
    'a reason is shown only when one was actually recorded');
  ok(/No reason was recorded for it/.test(BANNER),
    'and its absence is stated');
  ok(/signature was cleared by the correction/.test(BANNER),
    'it answers WHY HE IS SIGNING AGAIN, which is the question he will have');
  ok(/\$\{who\}\$\{when\}/.test(BANNER) || (/amendment\.by/.test(BANNER)
    && /amendment\.at/.test(BANNER)),
  'it names who filed it and when');
  ok(!/new Date\(\)|Date\.now|today/i.test(BANNER),
    'it never consults the clock');
}

console.log('\n5. THE EDITOR KEEPS WHAT THE LOAD USED TO THROW AWAY');
{
  ok(/const \[amendment, setAmendment\]/.test(EDITOR), 'it holds the facts');
  ok(/existing\.is_amendment === true/.test(EDITOR),
    'STRICTLY true: a truthy-but-not-true value is not a correction');
  ok(/existing\.amendment_reason/.test(EDITOR)
     && /existing\.created_by_name/.test(EDITOR)
     && /existing\.created_at/.test(EDITOR),
  'reason, author and date all survive the load');
  ok(/amendment=\{amendment\}/.test(EDITOR), 'and reach the stepper');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
