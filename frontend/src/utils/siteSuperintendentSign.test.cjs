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

/**
 * The balanced-brace body that follows an anchor.
 *
 * TEXTUAL ORDER IS NOT EXECUTION ORDER in a hooks component, and an ordering
 * claim about ONE function has to be asked of that function's body. Section 2
 * below compared indexes over the whole file until the screen became
 * local-first: the LOAD then began calling `setLocked(true)` when it finds a
 * frozen draft on the device — correct, unrelated to that rule, and ABOVE the
 * submit — so the file-wide index quietly started measuring a different
 * statement and the assertion inverted. Returns '' when the anchor is absent,
 * so a missing function fails by name instead of aborting the run.
 */
function braceBlock(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return '';
  const open = src.indexOf('{', at);
  if (open < 0) return '';
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(at, i + 1);
    }
  }
  return '';
}

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
  // ── THE CLOCK STAMP AT SIGNATURE IS GONE, AND THIS PAIR INVERTED ─────────
  //
  // These two used to read "departure is stamped when he signs" and "the stamp
  // is a FALLBACK — a time he typed wins over the app clock", asserting
  // `departedAt.trim() || nowHHMM()`. Both passed, and the thing they were
  // protecting was wrong:
  //
  //   IT IS THE APP ASSERTING AN OBSERVATION on a licensed signature. Section
  //   3 below is the rule — these times are HIS statement, not a measurement —
  //   and the stamp broke it in the one place he could not see. Arrival's
  //   prefill lands in a visible field he can correct all day; this one landed
  //   in the payload at the instant of filing.
  //
  //   IT WAS NOT THE TIME HE LEFT. 3301.13.13 wants the departure; the clock
  //   at signature is when he signed, and on a log he must complete BEFORE
  //   departing those differ by construction.
  //
  //   AND IT MADE DEPARTURE UNGATEABLE. A field that can never be blank at
  //   submit can never be reported missing, which is why the requirement had
  //   no enforcement to inherit.
  //
  // So the claim inverts: nothing writes a departure he did not choose.
  ok(!/nowHHMM/.test(CODE(SCREEN)),
    'no clock stamp writes departed_at behind him');
  ok(!/departedAt\.trim\(\) \|\| now/.test(CODE(SCREEN)),
    'and the fallback that made it unreachable is gone');
  ok(/if \(presenceMissing\.length > 0\) return;/.test(CODE(SCREEN)),
    'the handler REFUSES a blank arrival or departure instead of filling it in');

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
  //
  // AND AGAINST THE SUBMIT HANDLER, NOT THE WHOLE FILE. This was a whole-file
  // comparison until the screen became local-first: the LOAD now calls
  // `setLocked(true)` when it finds a frozen draft on the device, which is
  // correct and has nothing to do with this rule, and it sits above the submit
  // — so the file-wide index started measuring a different statement and the
  // assertion inverted. The claim is unchanged: on the path that FILES the
  // log, the server freeze precedes the screen's claim to be locked.
  const submitBody = braceBlock(CODE(SCREEN), 'const handleSubmit');
  ok(submitBody.indexOf('logbooksAPI.finalize') > 0
     && submitBody.indexOf('logbooksAPI.finalize') < submitBody.indexOf("toast.success(t('filed'))"),
  'and the freeze happens BEFORE the screen claims to be locked, so the '
    + 'claim is never made about a document the server refused');

  // AND THE SAME RULE ON THE PATH WITH NO SERVER. The screen became
  // local-first, so there is a second way to file: with no signal the log is
  // frozen on the DEVICE (`freezeLocally`, which marks the draft finalized so
  // draftSync re-applies the lock when it lands) and the screen says something
  // weaker than "filed and locked", because that would not be true yet. The
  // ordering rule is the one above, asked of the branch the server never sees.
  const offlinePath = braceBlock(submitBody, 'const reportHeldOnDevice');
  ok(offlinePath.indexOf('freezeLocally()') > 0
     && offlinePath.indexOf('freezeLocally()') < offlinePath.indexOf('setLocked(true)'),
  'the OFFLINE filing freezes the on-device draft before it claims to be '
    + 'locked — with no signal that draft IS the record');
  ok(/toast\.success\(t\('savedLocallyTitle'\)/.test(offlinePath)
     && !/t\('filed'\)/.test(offlinePath),
  'and it never says "filed and locked" about a log no server has seen');

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
  // RE-POINTED FROM `editable={!locked}` TO THE PICKERS. That assertion was
  // about the two TextInputs these fields used to be, and it kept passing
  // after they became TimeFields — because `editable={!locked}` lives inside
  // the `Field` component, which twelve OTHER call sites still use. It was
  // reporting on fields it no longer described. The claim it was making is
  // asked of the controls that are actually there.
  const csCode = CODE(SCREEN);
  const arrived = csCode.slice(csCode.indexOf("label={t('arrivedAt')}"));
  const departed = csCode.slice(csCode.indexOf("label={t('departedAt')}"));
  ok(csCode.indexOf("label={t('arrivedAt')}") > 0
     && /<TimeField[\s\S]{0,400}label=\{t\('arrivedAt'\)\}/.test(csCode),
  'ARRIVED is a TimeField');
  ok(/<TimeField[\s\S]{0,400}label=\{t\('departedAt'\)\}/.test(csCode),
    'DEPARTED is a TimeField');
  ok(/onChange=\{setArrivedAt\}/.test(arrived.slice(0, 400))
     && /onChange=\{setDepartedAt\}/.test(departed.slice(0, 400)),
  'and each one writes his choice straight back — no helper in between');
  // NO NATIVE MODULE. The whole reason TimeField is hand-built: a picker
  // package ends OTA delivery, and this screen is OTA-deliverable.
  const pkg = JSON.parse(read('package.json'));
  const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
  const pickers = deps.filter((d) => /datetimepicker|date-picker|time-picker|react-native-modal-datetime/i.test(d));
  ok(pickers.length === 0,
    `no picker package was added for this (${JSON.stringify(pickers)})`);
}

console.log('\n3b. A LOG CANNOT FILE WITH EITHER TIME BLANK');
{
  // ── THE STRUCTURAL PROBLEM, PROVED BY RUNNING THE MODEL ──────────────────
  //
  // Not asserted from the screen's comment about it: `csUnanswered` filters on
  // `i.attestable` and item 1 is declared `attestable: false`, so the existing
  // submit gate is INCAPABLE of naming presence however blank it is. A source
  // grep for the word "attestable" would pass on the prose explaining that.
  const M = loadEsm('src/utils/superintendentLogModel.js');
  const blankPresence = {
    presence: { printed_name: 'R. Sanchez', arrived_at: '', departed_at: '' },
    unsafe_conditions: { none_to_report: true },
    orders_given: { none_to_report: true },
    dob_actions: { none_to_report: true },
    incidents: { none_to_report: true },
  };
  ok(M.csUnanswered(blankPresence, '2026-09-03').length === 0,
    'csUnanswered names NOTHING for a log with both times blank — the gate '
    + 'that already exists structurally cannot require them');
  // AND THE ITEM READS AS ANSWERED. A printed name alone makes item 1 PRESENT
  // on every reader, which is absence rendered as a claim.
  ok(M.csItemState('presence', blankPresence, '2026-09-03') === 'present',
    'and item 1 reports PRESENT off the printed name alone');

  // ── SO THERE IS A SECOND GATE, AND IT NAMES THE FIELDS ───────────────────
  const csCode = CODE(SCREEN);
  ok(/const arrivalMissing = !arrivedAt\.trim\(\);/.test(csCode)
     && /const departureMissing = !departedAt\.trim\(\);/.test(csCode),
  'the screen asks the two fields directly');
  ok(/submitDisabled=\{[\s\S]{0,200}presenceMissing\.length > 0/.test(csCode),
    'a blank arrival or departure makes Submit UNREACHABLE, not warned about');
  ok(/submitHint=\{\s*presenceMissing\.length > 0/.test(csCode),
    'and the dead button names the presence gap FIRST — the other two gaps '
    + 'are on the step he is already looking at, these are four steps back');
  ok(/t\('presenceHint'\)\.replace\('\{fields\}', presenceMissing\.join\(' and '\)\)/
    .test(csCode),
  'the hint interpolates the MISSING FIELD LABELS, so he is told which one');
  ok(/required=\{arrivalMissing\}/.test(csCode)
     && /required=\{departureMissing\}/.test(csCode),
  'and each control is marked on step 1, with the same red outline the rest '
    + 'of the app uses');
  ok(/requiredLabel=\{t\('requiredField'\)\}/.test(csCode),
    'through the shared wording — one app must not mark a gap two ways');
  // NOT `nextDisabled`. toolbox_talk blocks Next on its required step-1
  // fields; this screen must not, because at 07:00 he does not yet know when
  // he will leave and the other four steps are filled during the day.
  ok(!/nextDisabled/.test(csCode),
    'but Next is NOT blocked — he cannot know his departure time in the morning');

  const en = read('src', 'i18n', 'en.js');
  ok(/presenceHint: 'Go back to step 1 and choose \{fields\}\./.test(en),
    'the copy sends him to the step the fields are on');
  ok(/requiredField: 'Required field'/.test(en),
    'and the field mark reads the same as everywhere else');
}

console.log('\n3d. STORED AS A WALL CLOCK, WITH THE NEXT DAY STATED');
{
  const csCode = CODE(SCREEN);
  // A STRING, NOT AN INSTANT. Seven readers echo these two keys raw and
  // convert nothing; a timestamp would force every one of them back to
  // Eastern, and the first that forgot would reprint the 20:00-check-in and
  // LL196 month-boundary bugs onto a licensed signature.
  ok(/arrived_at: arrivedAt\.trim\(\)/.test(csCode)
     && /departed_at: departedAt\.trim\(\)/.test(csCode),
  'the payload carries the wall-clock string the picker wrote');
  // SCOPED TO THE PRESENCE BLOCK. A whole-file sweep for `Date.now()` matches
  // EntryList's row ids and `new Date()` matches todayISO — neither has
  // anything to do with these two keys, and an assertion that cannot pass is
  // one somebody deletes.
  const presenceBlock = (() => {
    const at = csCode.indexOf('presence: {');
    return at < 0 ? '' : csCode.slice(at, csCode.indexOf('},', at));
  })();
  ok(presenceBlock.includes('arrived_at'),
    'the presence block was located (otherwise the next claim is vacuous)');
  ok(!/toISOString|Date\.now|getTime|new Date/.test(presenceBlock),
    'and nothing in it turns either time into a timestamp');
  // NEVER INFERRED. The tempting derivation is `departed < arrived`, and it is
  // wrong twice: a mistyped 07:00 would silently reclassify a day shift, and a
  // 20:00-to-20:30 night shift does not sort backwards at all.
  ok(/departed_next_day: departedNextDay === true/.test(csCode),
    'the next-day crossing is an EXPLICIT stored boolean');
  ok(!/departedAt\s*<\s*arrivedAt/.test(csCode)
     && !/arrivedAt\s*>\s*departedAt/.test(csCode),
    'and it is never derived by comparing the two times');
  ok(/setDepartedNextDay\(g\('presence'\)\.departed_next_day === true\)/.test(csCode),
    'a log filed before the flag existed hydrates FALSE, not undefined — it '
    + 'never told us it crossed midnight');
  // FORWARD-ONLY. Nothing pipes a stored value through a display helper on the
  // way in; a signed record must not change appearance because the control did.
  ok(/setArrivedAt\(g\('presence'\)\.arrived_at \|\| ''\)/.test(csCode)
     && /setDepartedAt\(g\('presence'\)\.departed_at \|\| ''\)/.test(csCode),
  'hydrate takes the stored strings AS STORED — no displayClock on the way in');
  ok(!/displayClock/.test(csCode),
    'and the screen never normalises a filed value at render time');

  // THE PREFILL IS IN THE PICKER'S OWN FORMAT AND ON ITS OWN GRID. A 24-hour
  // "07:17" would put a second shape in the same key and would select no chip.
  // THE REAL PARSER AND THE REAL GRID, not a copy of them. loadEsm cannot take
  // this file — it is JSX, and the harness compiles modules with the CommonJS
  // transform alone — so the component is dropped and its three PURE exports
  // are lifted, exactly as portedFormPayloads.test.cjs already lifts them for
  // hotWorkModel. A hand-typed grid here would be a second opinion about the
  // format, which is the whole thing this section is guarding against.
  const TF = (() => {
    const src = read('src', 'components', 'logbookStepper', 'TimeField.jsx')
      .replace(/^import .*$/gm, '')
      .replace(/^export default [\s\S]*$/m, '')
      .replace(/^export (const|function) /gm, '$1 ');
    // eslint-disable-next-line no-new-func
    return new Function(`${src}\nreturn { parseClock, toClock, timeOptions };`)();
  })();
  ok(/toClock\(p\.h24, p\.m - \(p\.m % 5\)\)/.test(csCode),
    'nowClock floors onto the five-minute grid the picker offers');
  const grid = TF.timeOptions().map((o) => TF.toClock(o.h24, o.m));
  for (const probe of ['07:17', '00:03', '23:59', '12:31']) {
    const p = TF.parseClock(probe);
    const out = TF.toClock(p.h24, p.m - (p.m % 5));
    ok(grid.includes(out),
      `a ${probe} prefill lands on a selectable row (${out})`);
  }
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
