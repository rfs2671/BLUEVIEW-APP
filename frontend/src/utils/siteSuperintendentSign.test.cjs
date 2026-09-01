/**
 * The superintendent log signs as a SUPERINTENDENT.
 *
 * THE TRAP THIS EXISTS FOR, recorded in followups before the screen was built:
 * `deriveActingCapacity` keys on the EVENT TYPE first and the signer's role
 * only as a fallback. Nine logbook editors send `eventType: 'cp_sign'`, and
 * this screen's obvious starting point was one of them. If it inherits
 * `cp_sign`, the ledger records the BC 3301.13.13 construction superintendent
 * log as signed by a COMPETENT PERSON — the opposite of what `acting_capacity`
 * exists to prove, on the one document where the capacity is the point.
 *
 * IT FAILS SILENTLY: no error, the hash computes, the document renders. Only
 * the capacity is wrong, in a field nobody reads until somebody needs it. So
 * the string is asserted BY NAME, and the absence of the wrong one is asserted
 * too — a screen that sent both would pass a test that only looked for the
 * right one.
 *
 * Run:  node src/utils/siteSuperintendentSign.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const SCREEN = read('app', 'logbooks', 'site_superintendent_log.jsx');
const AUDIT = read('src', 'utils', 'signatureAudit.js');
const FINDINGS = read('src', 'utils', 'csFindings.js');

/**
 * Comments stripped. Several assertions here deliberately check that a REASON
 * is written down — those read the raw source. Anything checking what the code
 * DOES reads this instead, because this file's subjects explain themselves at
 * length and a bare search matches the explanation.
 */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. THE EVENT TYPE');
{
  // READ FROM CODE, NOT FROM THE FILE. The screen's header comment quotes
  //     eventType: 'superintendent_sign'
  // verbatim, because that is the whole warning it exists to give. A raw
  // search therefore matches the WARNING and passes even if the call below it
  // sends cp_sign — the exact failure this test was written to prevent,
  // reproduced inside the test. Strip the comments and ask the code.
  const src = CODE(SCREEN);
  ok(/eventType: 'superintendent_sign'/.test(src),
    'the screen sends superintendent_sign, by name');
  ok(!/eventType: 'cp_sign'/.test(src),
    'and NEVER cp_sign — a screen sending both would pass a one-sided test');
  ok(/deriveActingCapacity/.test(AUDIT) && /superintendent_sign/.test(AUDIT),
    'the capacity deriver still recognises the string the screen sends');
  ok(src.indexOf('recordSignatureEvent') > 0, 'it records an event at all');

  // And the warning is still on the file, because the next person to copy an
  // editor reads the top of it before they read this test.
  ok(/must not be copied|NEVER `cp_sign`|never `cp_sign`/i.test(SCREEN),
    'the trap is documented where someone would fall into it');
}

console.log('\n2. THE FREEZE IS AT DEPARTURE');
{
  ok(/prior to departing/i.test(SCREEN),
    'the statute is quoted where the timing decision lives');
  ok(/nowHHMM/.test(CODE(SCREEN)),
    'departure is stamped when he signs');
  ok(/departedAt\.trim\(\) \|\| nowHHMM\(\)/.test(CODE(SCREEN)),
    'and the stamp is a FALLBACK — a time he typed wins over the app clock');

  // THE FREEZE IS AN EXPLICIT FINALIZE, AND THAT IS THE CONTRACT.
  //
  // An earlier version of this comment called it a client-side stopgap and
  // said the freeze belonged in the server's lock predicate. That was WRONG,
  // and wrong by not reading far enough: logbook_timing_meta already
  // publishes, for class `visit`, freeze_on_sign=false and
  // freeze_on_finalize=TRUE, with the note "A VISIT LOG FREEZES WHEN ITS
  // AUTHOR SIGNS ON DEPARTURE. That is a finalize, not a sign-and-freeze."
  // create/update leaving it unlocked is the design, not a gap.
  //
  // WHAT MAKES IT LOAD-BEARING is that nothing else will ever do it:
  // sweep_stale_end_of_day_logs excludes VISIT_LOG_TYPES on purpose, because
  // an overnight sweep would freeze a visit its author had not finished. Drop
  // this call and the document stays editable indefinitely while showing as
  // signed. Asserted with the ordering so the pair cannot drift apart.
  ok(/logbooksAPI\.finalize\(savedId\)/.test(CODE(SCREEN)),
    'the log is FINALIZED after the submit — signing freezes it, per '
    + '3301.13.13 "prior to departing the job site"');
  // ORDER IS CHECKED AGAINST CODE, NOT PROSE. The screen's comment explains
  // this rule and names `setLocked(true)` while doing so, so a plain indexOf
  // over the raw source finds the EXPLANATION before the statement and reports
  // an order that is not the code's. Strip the comments first.
  ok(CODE(SCREEN).indexOf('logbooksAPI.finalize')
     < CODE(SCREEN).indexOf('setLocked(true)'),
  'and the freeze happens BEFORE the screen claims to be locked, so the '
    + 'claim is never made about a document the server refused');

  // THE MIRROR NOW MODELS THE CLASS, and this assertion is the reason the
  // wording above changed. It was written the other way round — "the mirror
  // still has no visit class... the reminder to delete the stopgap" — and it
  // FAILED the moment VISIT_LOG_TYPES landed, which is what sent me back to
  // logbook_timing_meta and showed the finalize was the contract all along.
  // Kept, inverted: the client must agree with the server about this class.
  const timing = read('src', 'utils', 'logbookTiming.js');
  ok(/VISIT_LOG_TYPES/.test(timing) && /site_superintendent_log/.test(timing),
    'the client timing mirror models the visit class');
  ok(/!isImmediateLog\(logType\) && !isVisitLog\(logType\)/.test(CODE(timing)),
    'and a visit log is NOT batchable — the two-way predicate is what made '
    + 'the client claim it was, contradicting the server contract');
}

console.log('\n3. ARRIVAL AND DEPARTURE ARE HIS STATEMENT, NOT AN OBSERVATION');
{
  ok(/presenceNote/.test(CODE(SCREEN)), 'the screen says so in words');
  const en = read('src', 'i18n', 'en.js');
  ok(/YOUR statement of when you arrived and left, not a measurement/.test(en),
    'and the words say it plainly — he may open the app in his truck');
  ok(/editable=\{!locked\}/.test(CODE(SCREEN)),
    'both fields stay editable, so the claim is his to correct');
}

/**
 * SECTION 4 IS RUN, NOT READ.
 *
 * It was written as source greps first, and the mutation control caught that:
 * a mutant that made the deriver stamp `none_to_report` on item 5 with no
 * order given SURVIVED — because the assertion matched the COMMENT saying it
 * does not, and the comment was still true-looking while the code below it had
 * changed. That is the defect family this project keeps hitting: a check on
 * presence standing in for a check on content.
 *
 * `csFindings.js` imports nothing, so the harness loads the shipped module and
 * the attestations are asserted by calling it.
 */
console.log('\n4. ITEMS 4 AND 5 ARE ONE ENTRY, TWO STATUTORY ITEMS');
{
  const {
    deriveConditionAndOrderBlocks, findingIsEmpty, findingGaps,
    CORRECTED, NOT_CORRECTED, NOT_YET, CORRECTION_STATES, isCorrectionState,
  } = loadEsm('src/utils/csFindings.js');
  const finding = (f) => ({
    location: '', observed_at: '', condition: '', order_given: '', order_to: '',
    corrected: null, ...f,
  });

  ok(/deriveConditionAndOrderBlocks/.test(CODE(SCREEN)),
    'the screen derives both blocks from one list of findings');

  // THE MUTANT THAT SURVIVED THE COMMENT GREP.
  {
    const r = deriveConditionAndOrderBlocks(
      [finding({ condition: 'Open riser, no guard', location: '4th fl east' })], false,
    );
    ok(r.unsafe_conditions.entries?.length === 1,
      'a condition he logged makes item 4 PRESENT');
    ok(r.orders_given.none_to_report !== true,
      'and item 5 is NOT auto-attested — "I saw something and ordered nothing" '
      + 'is a statement only he can make');
    ok(!r.orders_given.entries,
      'item 5 stays unanswered, so the submit gate names it rather than '
      + 'filing a blank as an answer');
  }

  {
    const r = deriveConditionAndOrderBlocks(
      [finding({ condition: 'Open riser', location: '4th fl', order_given: 'Guard installed', order_to: 'Acme' })],
      false,
    );
    ok(r.unsafe_conditions.entries?.length === 1 && r.orders_given.entries?.length === 1,
      'one finding with an order writes BOTH items from the one entry');
    ok(r.orders_given.entries?.[0]?.given_to === 'Acme'
       && r.orders_given.entries?.[0]?.location === '4th fl',
    'and item 5 carries WHO and WHERE — an order to nobody is not a record');
  }

  {
    const r = deriveConditionAndOrderBlocks([], true);
    ok(r.unsafe_conditions.none_to_report === true && r.orders_given.none_to_report === true,
      'the single affirmation attests BOTH items');
    ok(/noneBothNote/.test(CODE(SCREEN)),
      'and the screen NAMES both — one tap attesting twice is only defensible '
      + 'if the control says so');
  }

  {
    const r = deriveConditionAndOrderBlocks(
      [finding({ condition: 'Open riser', location: '4th fl' })], true,
    );
    ok(r.unsafe_conditions.none_to_report !== true,
      'a stale "nothing to report" tick does NOT survive a list with entries '
      + 'in it — the entries are the more specific statement');
    ok(r.unsafe_conditions.entries?.length === 1, 'and the entry is what gets filed');
  }

  {
    ok(findingIsEmpty(finding({})) === true, 'a blank row is not a finding');
    ok(findingIsEmpty(finding({ corrected: CORRECTED })) === false,
      'but a row he touched at all is, so it cannot be dropped silently');
    ok(deriveConditionAndOrderBlocks([finding({}), finding({})], false)
      .unsafe_conditions.entries === undefined,
    'blank rows never reach the document');
    ok(findingGaps(finding({ condition: 'Open riser' })).includes('where'),
      'a finding with no location is refused — 1 RCNY 3301-04(f) needs a '
      + 'reader to be able to return to it');
  }

  // ── "WAS IT CORRECTED" HAS THREE ANSWERS AND NO BLANK ─────────────────
  //
  // This was a yes/no toggle that returned to `null` on a second tap. Two
  // defects: "not corrected" and "not corrected YET" are different statements
  // about the site, and `null` renders identically to "no" on the filed
  // document — absence read as a claim, the family this project keeps hitting.
  {
    ok(CORRECTION_STATES.length === 3
       && CORRECTION_STATES.includes(CORRECTED)
       && CORRECTION_STATES.includes(NOT_CORRECTED)
       && CORRECTION_STATES.includes(NOT_YET),
    'three declared answers: corrected, not corrected, not yet');
    ok(!isCorrectionState(null) && !isCorrectionState(undefined)
       && !isCorrectionState('') && !isCorrectionState(false),
    'and NONE of null, undefined, empty or false is one of them — a blank '
    + 'can never be mistaken for an answer');
    ok(isCorrectionState(NOT_YET) === true,
      '"not yet" is a POSITIVE answer he chooses, not a softer no');

    const g = findingGaps(finding({ condition: 'Open riser', location: '4th fl' }));
    ok(g.includes('whether it was corrected'),
      'a row that answers everything EXCEPT this is refused — never filed '
      + 'with the one field a reader is actually asking about left open');
    ok(findingGaps(finding({
      condition: 'Open riser', location: '4th fl', corrected: NOT_YET,
    })).length === 0, 'and answering it clears the gate');

    const r = deriveConditionAndOrderBlocks([finding({
      condition: 'Open riser', location: '4th fl', corrected: NOT_YET,
    })], false);
    ok(r.unsafe_conditions.entries?.[0]?.corrected === NOT_YET,
      'the answer reaches the document as itself, not coerced to a boolean');

    ok(!/onChange\(value === v \? null : v\)/.test(CODE(SCREEN)),
      'and the control cannot untoggle back to unanswered');
    ok(/onPress=\{\(\) => onChange\(v\)\}/.test(CODE(SCREEN)),
      'every chip SETS a state; none clears one');
  }
}

console.log('\n5. THE INSPECTION CARRIES WHAT 3301-04(f) NEEDS');
{
  for (const k of ['inspectedOn', 'inspectionLocation', 'inspectionResult']) {
    ok(CODE(SCREEN).includes(k), `${k} is collected explicitly, not as one blank box`);
  }
  ok(/3301-04\(f\)/.test(read('src', 'i18n', 'en.js')),
    'and the rule is named on screen, so the three fields read as required '
    + 'rather than arbitrary');
}

console.log('\n6. THE DOB LIST IS A SUGGESTION, NOT A COPY');
{
  ok(/record_type: 'violation'/.test(CODE(SCREEN)),
    'it pulls what the system already holds');
  ok(/included: false/.test(CODE(SCREEN)),
    'NOTHING IS PRE-TICKED — the log is his statement, not a copy of a feed');
  ok(/dobAddManual/.test(CODE(SCREEN)),
    'and he can add what the system has not seen');
}

console.log('\n7. THE DECLARED ITEMS ARE THE SOURCE OF TRUTH');
{
  ok(/superintendentLogModel/.test(CODE(SCREEN)),
    'the screen reads the declared items rather than restating them');
  ok(/csUnanswered/.test(CODE(SCREEN)),
    'the submit gate mirrors the server rule');
  ok(/'not_collected'/.test(CODE(SCREEN)),
    'and items this release does not collect are NAMED as scope, not left '
    + 'blank for a reader to take as an omission');
  ok(!/number: 1[01]/.test(CODE(SCREEN)) && !/'weekly_meeting'/.test(CODE(SCREEN)),
    'the screen does not hardcode item numbers or keys the model owns');
}

console.log('\n8. THE NAV');
{
  // NOT FROM THE NAV. A slot was built there and removed: the QR is reached at
  // a gate with a worker in front of him, Settings is where he signs out, and a
  // once-a-day log read from a list outranks neither on a bar with three items
  // and one point of headroom.
  const nav = read('src', 'components', 'CpNav.js');
  ok(!/site_superintendent/.test(CODE(nav)), 'the log is NOT a nav item');
  ok(/WHY THERE IS NO SUPERINTENDENT SLOT/.test(nav),
    'and the nav records why, so the slot is not proposed again');

  // FROM THE LOGBOOKS LIST, which is now the only path and therefore has to
  // work. The tile routes by log type, so the registry key IS the filename.
  // requiredLogbooksWiring.test.cjs executes that resolution against the
  // server's registry, toggle on and toggle off; this asserts the half that
  // lives in what this screen is called.
  const screens = fs.readdirSync(path.join(FRONTEND, 'app', 'logbooks'))
    .filter((f) => f.endsWith('.jsx')).map((f) => f.replace(/\.jsx$/, ''));
  ok(screens.includes('site_superintendent_log'),
    'the screen is named for its registry key, so the list tile resolves');

  ok(/numberOfLines=\{1\}/.test(CODE(nav)), 'the nav label is still single-line');
  ok(/CP_NAV_PILL_HEIGHT =\n?\s*spacing\.sm \* 2/.test(nav),
    'and the pill height is still composed from padding and icon only');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
