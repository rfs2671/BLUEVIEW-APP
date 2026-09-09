/**
 * ITEMS 4 AND 5 ARE OFFERED FROM THE CP'S OBSERVATIONS, AND MOSTLY ARE NOT.
 *
 * THE OPERATOR'S RULING: an unsafe condition is a fact about the site, not
 * about him, so the superintendent may be offered what the competent person
 * recorded -- the same reasoning that lets item 2 adopt the CP's summary and
 * stops item 3 adopting anything.
 *
 * THIS FILE IS RUN, NOT READ, AND THE FIXTURES ARE PRODUCTION VERBATIM. Every
 * observation row below is copied out of a filed daily jobsite log, including
 * the blank one and including the two whose `remedy` is the word "Corrected".
 * A hand-written fixture here would be a second opinion about a shape the
 * database already settled -- and the shape is the entire argument for what
 * this module refuses to map.
 *
 * ── WHAT THE MEASUREMENT SAID, AND WHAT IT COSTS ────────────────────────────
 *
 * Across every observation row in production, filed and draft: FOUR KEYS, and
 * only ever four -- description, responsible_party, remedy,
 * corrected_immediately. THERE IS NO LOCATION. `findingGaps` requires one, so
 * an offered finding is NEVER complete and he must supply WHERE on every row.
 *
 * `corrected_immediately` is NULL ON FOUR OF THE FIVE ROWS -- the CP's toggle
 * only ever writes `true` -- so the correction state is almost never adoptable
 * either.
 *
 * AND `remedy` IS NOT AN ORDER. Two of the five rows hold the literal word
 * "Corrected": the men filling that box are recording the correction STATE, so
 * reading it as item 5's "orders and notices given" would file "Corrected" on
 * a BC 3301.13.13 record as something the superintendent directed.
 *
 * Run:  node src/utils/adoptedFindings.test.cjs
 */
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let failures = 0;
const ok = (label, cond, hint) => {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
};

const { adoptableFindings, anyFindingStillAdopted } = loadEsm('src/utils/adoptedFindings.js');
const { CORRECTED, findingIsEmpty, findingGaps } = loadEsm('src/utils/csFindings.js');

/** Production observation rows, verbatim. */
const OBS = {
  //                                       2026-03-10, project 698d2c17
  egress: {
    description: 'Missing egress safety ',
    responsible_party: 'Lubavits',
    remedy: 'Add safety ',
    corrected_immediately: null,
  },
  // THE BLANK ONE. It is on the same filed log as `egress`.
  blank: {
    description: '', responsible_party: '', remedy: '',
    corrected_immediately: null,
  },
  //                                       2026-03-18, project 69ba1c58
  hardHats: {
    description: 'No hard hats',
    responsible_party: 'ODD CONSTRUCTION ',
    remedy: 'Corrected',
    corrected_immediately: null,
  },
  //                                       2026-08-15, project 6a7a145e
  fireAlarm: {
    description: 'Fire alarm',
    responsible_party: 'Air Star Mechanical',
    remedy: '',
    corrected_immediately: true,
  },
};

/** A filed daily log, shaped as `logbooksAPI.getByProject` returns them. */
const filed = (observations) => ([{
  id: 'd1', log_type: 'daily_jobsite', date: '2026-09-08',
  status: 'submitted', is_locked: true,
  data: { observations },
}]);

console.log('\nthe offer');
{
  const out = adoptableFindings(filed([OBS.egress, OBS.blank]));
  ok(`the blank observation is dropped (${out.length} of 2 offered)`,
    out.length === 1,
    'offering it would put an empty finding on his screen that the gate then '
    + 'refuses, for a row the CP never filled in either');
  ok('the description becomes item 4\'s condition',
    out[0].condition === 'Missing egress safety',
    `got ${JSON.stringify(out[0] && out[0].condition)}`);
  ok('and it is trimmed — the stored value has a trailing space',
    !/\s$/.test(out[0].condition));
  ok('the responsible party becomes who an order would go to',
    out[0].order_to === 'Lubavits');
}

console.log('\nwhat is NOT mapped, and the production rows that say why');
{
  const [f] = adoptableFindings(filed([OBS.hardHats]));

  // ITEM 5 STAYS HIS. `remedy` on this row is the word "Corrected".
  ok('`remedy` never reaches order_given', f.order_given === '',
    `"${OBS.hardHats.remedy}" would have been filed as an order the `
    + 'superintendent gave');
  const remedies = Object.values(OBS).map((o) => o.remedy);
  ok('and the fixture still contains the row that proves it',
    remedies.includes('Corrected'),
    'if production ever stops using `remedy` for the correction state, this '
    + 'refusal is worth revisiting — but it is measured, not assumed');

  // THE CS LOG REFUSES A BOOLEAN. "Not corrected" and "not corrected YET" are
  // different statements, and `null` is not an answer to either.
  ok('a null corrected_immediately leaves the correction UNANSWERED',
    f.corrected === null,
    'defaulting it would file "he found it and left it standing" on his '
    + 'signature');
  const [fa] = adoptableFindings(filed([OBS.fireAlarm]));
  ok('and only `true` maps, to CORRECTED', fa.corrected === CORRECTED);

  // THERE IS NO LOCATION ANYWHERE IN THE SOURCE.
  ok('no location is invented', f.location === '' && fa.location === '');
  ok('nor an observed_at', f.observed_at === '' && fa.observed_at === '');
}

console.log('\nan offered finding is never complete, and that is the design');
{
  for (const [name, row] of [['egress', OBS.egress], ['fireAlarm', OBS.fireAlarm]]) {
    const [f] = adoptableFindings(filed([row]));
    ok(`${name}: it is not empty, so the row counts and the tick is withheld`,
      !findingIsEmpty(f));
    const gaps = findingGaps(f);
    ok(`${name}: the gate still asks for what only he knows (${gaps.join(', ')})`,
      gaps.includes('where'),
      'an observation carries no location; if this ever passes with no gaps, '
      + 'the offer has started filling in a statutory field for him');
  }
}

console.log('\nnothing is offered when there is nothing to adopt');
{
  const cases = [
    ['no rows at all', []],
    ['a failed read', null],
    ['a non-array', { items: [] }],
    ['a log with no observations key', [{
      id: 'd1', status: 'submitted', is_locked: true, data: {},
    }]],
    ['observations that are not an array', [{
      id: 'd1', status: 'submitted', is_locked: true,
      data: { observations: 'nope' },
    }]],
  ];
  for (const [label, rows] of cases) {
    ok(`${label} offers nothing`, adoptableFindings(rows).length === 0);
  }

  // AN UNSIGNED DRAFT IS NOT A RECORD. `filedDailyRecord`'s rule, asserted
  // here because this module is its third caller and the failure is silent:
  // it would put the CP's work-in-progress onto a signed statutory document.
  const draft = [{
    id: 'd1', log_type: 'daily_jobsite', date: '2026-09-08',
    status: 'draft', is_locked: false, data: { observations: [OBS.egress] },
  }];
  ok('an unsigned DRAFT daily log offers nothing',
    adoptableFindings(draft).length === 0,
    'he has not stood behind it and it can still change');
}

console.log('\nthe note says the rows are not his, and stops when they are');
{
  const offered = adoptableFindings(filed([OBS.egress, OBS.fireAlarm]));
  ok('it shows while the offered conditions are on screen',
    anyFindingStillAdopted(offered, offered));

  // EDITING THE LOCATION DOES NOT UN-ADOPT IT -- which matters, because he
  // MUST edit the location on every row. A whole-row comparison would have
  // cleared the note the moment he did the one thing the gate requires.
  const located = offered.map((f) => ({ ...f, location: '4th floor, north' }));
  ok('adding the location he is required to add keeps it',
    anyFindingStillAdopted(located, offered),
    'a row comparison would clear the note the instant he does the one thing '
    + 'the gate demands');

  // REWRITING WHAT WAS SEEN DOES.
  const rewritten = offered.map((f) => ({ ...f, condition: `${f.condition} (mine)` }));
  ok('rewriting every condition clears it',
    !anyFindingStillAdopted(rewritten, offered));
  ok('rewriting only one of two keeps it',
    anyFindingStillAdopted(
      [rewritten[0], offered[1]], offered,
    ));

  ok('nothing offered means no note, whatever he typed',
    !anyFindingStillAdopted(
      [{ condition: 'I saw a thing' }], [],
    ),
    'a superintendent who was offered nothing wrote his own findings');
  for (const junk of [null, undefined, 'x', 42]) {
    ok(`a ${typeof junk} for either side is not a crash`,
      anyFindingStillAdopted(junk, junk) === false);
  }
}

// ── THE SCREEN'S WIRING ────────────────────────────────────────────────────
console.log('\nthe screen offers it only into an untouched, unattested item');
{
  const fs = require('fs');
  const SCREEN = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'site_superintendent_log.jsx'),
    'utf8',
  ).split('\r\n').join('\n')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');

  ok('the offer is guarded on BOTH the entries and the tick',
    /const wantFindings = !noneBoth\s*&& findings\.filter\(\(f\) => !findingIsEmpty\(f\)\)\.length === 0;/
      .test(SCREEN),
    'a superintendent who already said there was nothing to report must not '
    + 'find conditions appearing underneath it');

  // ONE READ, NOW THREE ANSWERS. A second fetch would be a second chance to
  // disagree about which link of an amended chain is the record.
  // BOUNDED BY THE EFFECT'S OWN DEPENDENCY ARRAY, which is unique in the file.
  // The first attempt hunted for the NEXT `useEffect(` and landed inside this
  // one, because the DOB effect that follows opens identically — so the slice
  // held half an effect and the single-fetch count came out wrong. An anchor
  // that also matches the thing it is meant to stop at is not an anchor.
  const offerAt = SCREEN.indexOf('const dailyOfferRef');
  const offerEnd = SCREEN.indexOf('}, [loading, locked, progress,', offerAt);
  const offerEffect = offerAt < 0 || offerEnd < 0 ? ''
    : SCREEN.slice(offerAt, offerEnd);
  ok('the offer effect was located by its own dependency array',
    offerEffect.length > 400 && offerEffect.includes('designatedCpDefault'));
  ok('it reads the SAME document items 2 and 8 read',
    (offerEffect.match(/logbooksAPI\.getByProject\(/g) || []).length === 1
      && /adoptableFindings\(rows\)/.test(offerEffect),
    'a second fetch is a second chance to pick a different link of an '
    + 'amended chain');

  ok('and what was offered is held for the note',
    /setAdoptedFindings\(offered\)/.test(SCREEN));
  ok('the note is rendered from the shared rule, not a local comparison',
    /anyFindingStillAdopted\(findings, adoptedFindings\)/.test(SCREEN));
}

// ── THE COPY NAMES BOTH HALVES ─────────────────────────────────────────────
//
// THE OPERATOR: say plainly what arrived and what did not. A note that only
// says "these came from the CP's log" tells him the rows are not his and
// leaves him to discover, field by field, that three of the five are empty --
// on the screen where the gate then refuses the step without saying which
// half of the row it is refusing.
//
// ASSERTED AGAINST THE MODULE'S ACTUAL MAPPING, not against the sentence. The
// list of what arrives is derived by running `adoptableFindings` on a
// production row and reading which keys came back populated, so the copy
// cannot go on claiming a field after the mapping stops producing it -- the
// stale-prose failure this project keeps finding.
console.log('\nthe copy says what arrived and what did not');
{
  const fs = require('fs');
  const en = fs.readFileSync(
    path.join(__dirname, '..', 'i18n', 'en.js'), 'utf8',
  );
  const line = en.split('\n').find((l) => l.includes('findingsAdoptedNote:')) || '';
  // ARGUMENTS IN THE RIGHT ORDER. This file's `ok` is (label, cond, hint), and
  // the first draft of this line read `ok(line.length > 80, 'the note exists')`
  // -- so the LABEL was a boolean and the CONDITION was a non-empty string,
  // which is always true. It printed "ok true" and would have passed with no
  // note in the file at all, in the section about checks that pass on absence.
  ok('the note exists to read', line.length > 80,
    'findingsAdoptedNote is missing from en.js, and every phrase assertion '
    + 'below would otherwise be searching an empty string');

  const [row] = adoptableFindings(filed([OBS.egress]));
  const arrived = ['condition', 'order_to'].filter((k) => row[k]);
  const withheld = ['location', 'observed_at', 'order_given']
    .filter((k) => !row[k]).concat(row.corrected === null ? ['corrected'] : []);
  ok(`the mapping populates ${arrived.join(', ')} and withholds `
    + `${withheld.join(', ')}`,
    arrived.length === 2 && withheld.length === 4,
    'if this changed, the sentence below is now describing something else');

  for (const [phrase, why] of [
    [/what he saw/i, 'condition — what arrived'],
    [/who was responsible/i, 'order_to — what arrived'],
    [/where it was seen/i, 'location — withheld, and the gate demands it'],
    [/what you ordered/i, 'order_given — withheld on purpose, `remedy` is not '
      + 'an order'],
    [/whether it was corrected/i, 'corrected — withheld unless true'],
  ]) {
    ok(`it names ${why}`, phrase.test(line));
  }
  ok('and it says the rows are not his',
    /not from you/i.test(line));
}

if (failures) {
  console.error(`\nadoptedFindings: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
