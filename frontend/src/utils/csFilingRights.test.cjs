/**
 * THE TILE READS THE SAME FACT THE GATE READS.
 *
 * MEASURED ON PRODUCTION — 588 Thomas S Boyland Street, the one project with
 * `superintendent_log_active` on, registered CS Michael Cespedes:
 *
 *     accounts that see the tile: 9
 *        Roy Fishman       owner   REFUSED AT SUBMIT
 *        TEST              admin   REFUSED AT SUBMIT
 *        Meilich Friedman  admin   REFUSED AT SUBMIT
 *        Michael Cespedes  cp      (may file)
 *        test              admin   REFUSED AT SUBMIT
 *        Test              admin   REFUSED AT SUBMIT
 *        test              owner   REFUSED AT SUBMIT
 *        wilson peleaz     cp      REFUSED AT SUBMIT
 *        wilson@cp.comm    owner   REFUSED AT SUBMIT
 *
 * Eight of nine saw a tile they could not file, and learned it only after
 * filling the whole log — the gate runs on create and on PUT ONLY AT SUBMIT,
 * so every autosave succeeded first.
 *
 * ── WHAT IS ASSERTED HERE ───────────────────────────────────────────────────
 *
 * The module is EXECUTED: it is a pure reader over the server's `filing` block
 * and there is nothing to mock. The SCREEN half — that index.jsx renders this
 * rather than a second opinion of its own — is read out of the shipped source
 * with comments stripped, because the suite is plain node and cannot mount a
 * React component. Same technique as csFilingGuard.test.cjs, and for the same
 * reason: this screen explains itself at length in prose and a bare search
 * would match the explanation.
 *
 *   node frontend/src/utils/csFilingRights.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

let M = {};
let loadError = null;
try {
  M = loadEsm('src/utils/csFilingRights.js');
} catch (e) {
  loadError = e;
}

const CS = 'site_superintendent_log';
const NAME = 'Michael Cespedes';

/** The payload the endpoint returns for wilson peleaz on 588 Thomas. */
const REFUSED_PAYLOAD = {
  project_id: '6a5f63bc147407d3261df2c7',
  project_class: 'regular',
  classification_assessed: true,
  required_logbooks: ['daily_jobsite', 'preshift_signin', CS],
  activations: [{ log_type: CS, label: 'Construction Superintendent Log', field: 'superintendent_log_active', active: true, activated_by: 'admin' }],
  filing: [{
    log_type: CS, may_file: false, registered_name: NAME,
    reason: 'NOT_THE_REGISTERED_SUPERINTENDENT',
  }],
};

/** The same payload for Michael himself. */
const ALLOWED_PAYLOAD = {
  ...REFUSED_PAYLOAD,
  filing: [{ log_type: CS, may_file: true, registered_name: NAME, reason: null }],
};

/** A project that has registered nobody. The gate refuses NOBODY here. */
const NO_REGISTRATION_PAYLOAD = {
  ...REFUSED_PAYLOAD,
  filing: [{ log_type: CS, may_file: true, registered_name: null, reason: null }],
};

console.log('\n0. THE MODULE EXISTS');
{
  ok(!loadError, `src/utils/csFilingRights.js loads${loadError ? ` (${loadError.message})` : ''}`);
  for (const fn of ['filingRights', 'mayFile', 'ownerName', 'whoFilesLabel',
    'whoFilesTitle', 'whoFilesReason']) {
    ok(typeof M[fn] === 'function', `and exports ${fn}`);
  }
}

// Not a bail-out — the propositions below must REPORT rather than crash the
// run, or one missing export hides every remaining gap.
const F = {
  filingRights: M.filingRights || (() => ({})),
  mayFile: M.mayFile || (() => true),
  ownerName: M.ownerName || (() => null),
  whoFilesLabel: M.whoFilesLabel || (() => null),
  whoFilesTitle: M.whoFilesTitle || (() => ''),
  whoFilesReason: M.whoFilesReason || (() => null),
};

console.log('\n1. THE EIGHT ARE TOLD BEFORE THEY START');
{
  const r = F.filingRights(REFUSED_PAYLOAD);
  ok(F.mayFile(r, CS) === false, 'wilson peleaz may not file the CS log');
  ok(F.ownerName(r, CS) === NAME, 'and the answer names Michael Cespedes');
  const label = F.whoFilesLabel(r, CS);
  ok(typeof label === 'string' && label.includes(NAME),
    `the tile line names him: "${label}"`);
  ok(F.whoFilesTitle(r, CS).includes(NAME), 'and so does the tap title');
}

console.log('\n2. THE REGISTERED MAN SEES NOTHING SPECIAL');
{
  const r = F.filingRights(ALLOWED_PAYLOAD);
  ok(F.mayFile(r, CS) === true, 'Michael Cespedes may file it');
  ok(F.whoFilesLabel(r, CS) === null,
    'and gets no "whose log is this" line — his own tile must read as it '
    + 'always did');
  ok(F.ownerName(r, CS) === null,
    'ownerName answers only where the log is WITHHELD; his own name on his own '
    + 'tile would be noise');
}

console.log('\n3. NO REGISTRATION MEANS EVERYONE MAY FILE');
{
  // The server refuses only NOT_REGISTERED_CS. Blocking a log that must be
  // filed before a man leaves the site, over a field an admin never filled in,
  // is the worse failure — and a tile that claimed an owner the project has
  // not named would re-introduce that refusal one layer out.
  const r = F.filingRights(NO_REGISTRATION_PAYLOAD);
  ok(F.mayFile(r, CS) === true, 'an unregistered project withholds from nobody');
  ok(F.whoFilesLabel(r, CS) === null, 'and the tile claims no owner');
}

console.log('\n4. SILENCE IS PERMISSION, NOT REFUSAL');
{
  // An OTA bundle can meet an older server. Defaulting the other way would
  // switch off the superintendent log for everyone until the server caught up.
  for (const [what, payload] of [
    ['a server that sends no `filing` key', { required_logbooks: [CS] }],
    ['a null payload (first paint, offline)', null],
    ['a `filing` that is not an array', { filing: 'nope' }],
    ['a `filing` with no row for this type', { filing: [{ log_type: 'hot_work', may_file: false }] }],
    ['a row missing may_file entirely', { filing: [{ log_type: CS }] }],
  ]) {
    const r = F.filingRights(payload);
    ok(F.mayFile(r, CS) === true, `${what}: he may still file`);
    ok(F.whoFilesLabel(r, CS) === null, `${what}: and no owner is claimed`);
  }
  ok(F.mayFile(F.filingRights(REFUSED_PAYLOAD), 'daily_jobsite') === true,
    'and one withheld type never leaks onto another');
}

console.log('\n5. A WITHHELD LOG WITH NO NAME IS STILL NOT A DEAD END');
{
  // registered_name is `reg.get("full_name")`, which a row may legitimately
  // lack. "No" with no "who" leaves him nothing to do.
  const r = F.filingRights({
    filing: [{ log_type: CS, may_file: false, registered_name: null,
      reason: 'NOT_THE_REGISTERED_SUPERINTENDENT' }],
  });
  ok(F.mayFile(r, CS) === false, 'it is still withheld');
  const label = F.whoFilesLabel(r, CS);
  ok(typeof label === 'string' && label.length > 0
     && !/null|undefined/.test(label),
  `the line still says the project named somebody: "${label}"`);
  ok(F.whoFilesTitle(r, CS).length > 0 && !/null|undefined/.test(F.whoFilesTitle(r, CS)),
    'and so does the title');
}

console.log('\n6. THE REASON IS THE SUBMIT REFUSAL, WORD FOR WORD');
{
  // One condition must not be described two ways depending on whether the
  // client or the server noticed it. Both go through refusalCopy over the same
  // `finalize` copy, so this compares the tile's sentence with the toast the
  // submit path produces for the identical detail.
  function loadModule(rel) {
    const file = path.join(FRONTEND, rel);
    const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
      filename: file,
      plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
      configFile: false,
      babelrc: false,
    });
    const mod = { exports: {} };
    new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
    return mod.exports;
  }
  const en = loadModule('src/i18n/en.js').default;
  const { refusalCopy } = loadModule('src/utils/csRefusalCopy.js');
  const t = (k) => (Object.prototype.hasOwnProperty.call(en.finalize, k)
    ? en.finalize[k] : k);

  const r = F.filingRights(REFUSED_PAYLOAD);
  const onTile = F.whoFilesReason(r, CS, t);
  const onSubmit = refusalCopy('NOT_THE_REGISTERED_SUPERINTENDENT',
    { registered_name: NAME }, t);
  ok(onTile === onSubmit,
    'the tile and the submit refusal say the SAME sentence');
  ok(typeof onTile === 'string' && onTile.includes(NAME),
    'which names the man');
  ok(!/try again/i.test(String(onTile)),
    'and does not tell him to retry a refusal no retry can clear');
  ok(F.whoFilesReason(F.filingRights(ALLOWED_PAYLOAD), CS, t) === null,
    'and there is no reason to give the man whose log it is');
}

console.log('\n7. THE SCREEN RENDERS IT, AND DOES NOT HIDE THE TILE');
{
  const raw = read('app', 'logbooks', 'index.jsx');
  const SRC = raw
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');

  ok(/from '[^']*csFilingRights'/.test(SRC),
    'the list imports the shared reader rather than deriving a second opinion');

  // THE TILE IS STILL RENDERED. getVisibleLogTypes says why in its own
  // comment: "A required log the CP cannot open is worse than an ugly label."
  // A CP who cannot SEE the log cannot see that it exists or who owns it.
  // BRACE-MATCHED, not sliced to the next declaration. The first draft ran to
  // `const activations =` and went red the moment `const rights =` was declared
  // between the two — a slice that grows when a neighbour moves is an assertion
  // about the wrong text.
  const visible = (() => {
    const at = SRC.indexOf('const getVisibleLogTypes');
    if (at < 0) return '';
    let depth = 0;
    for (let i = SRC.indexOf('{', at); i < SRC.length; i += 1) {
      if (SRC[i] === '{') depth += 1;
      else if (SRC[i] === '}') { depth -= 1; if (depth === 0) return SRC.slice(at, i + 1); }
    }
    return '';
  })();
  ok(visible.length > 0, 'getVisibleLogTypes was found');
  ok(!/mayFile|may_file|filing/.test(visible),
    'and does NOT filter the list by who may file — the tile is not hidden');

  // The three-state precedent, applied: the row SAYS whose it is.
  ok(/whoFilesLabel\(/.test(SRC),
    'the tile row asks for the "whose log is this" line');

  // AND THE TAP DOES NOT OPEN AN EDITOR THAT WILL REFUSE HIM AT THE END OF THE
  // DAY. Asserted inside handleOpenLog rather than anywhere in the file: every
  // route into a fresh editor from this screen goes through that one function,
  // and a guard written on the row alone would be silent for the alert buttons
  // that call it with a log type of their own.
  const opener = (() => {
    const at = SRC.indexOf('const handleOpenLog');
    if (at < 0) return '';
    let depth = 0;
    for (let i = SRC.indexOf('{', at); i < SRC.length; i += 1) {
      if (SRC[i] === '{') depth += 1;
      else if (SRC[i] === '}') { depth -= 1; if (depth === 0) return SRC.slice(at, i + 1); }
    }
    return '';
  })();
  ok(opener.length > 0, 'handleOpenLog was found');
  ok(/if \(!filed && !mayFile\(rights, logType\)\)/.test(opener),
    'it asks the server\'s answer before routing — and only while there is '
    + 'still a log to fill in');
  // READING IS NOT FILING. A filed log opens to FiledLogView, and the eight
  // who may not FILE the superintendent's log (an owner, four admins, a second
  // CP) could read the filed one before this guard existed. Taking that away
  // would be a new defect wearing this one's clothes.
  ok(/const filed = logTypeStatus\(todayLogs\[logType\]\) === 'submitted';/
    .test(opener),
  'and a filed record is still openable — the guard closes the invitation to '
    + 'FILL a log he cannot file, not the ability to read one');
  ok(/whoFilesTitle\(/.test(opener) && /whoFilesReason\(/.test(opener),
    'and names the man and says why');
  // `search`, and asserted non-negative below: indexOf answers -1 for a guard
  // that is not there, and slice(-1) would hand back the last character of the
  // function — an assertion that then reports on nothing at all.
  const guardAt = opener.search(/if \(![A-Za-z]+ && !mayFile\(/);
  ok(guardAt >= 0, 'the guard was located');
  const guard = guardAt >= 0 ? opener.slice(guardAt) : '';
  ok(/\breturn;/.test(guard.slice(0, 400)),
    'and RETURNS — a toast that falls through to router.push would be the same '
    + 'defect with a warning on top');
  ok(guardAt >= 0 && guard.indexOf('router.push') > guard.indexOf('return;'),
    'the push is unreachable for a log that is not his');
  ok(/mayFile\(/.test(SRC), 'off the server\'s answer, not a role check');
  ok(!/role\s*===\s*'(cp|admin|owner)'[^\n]*(superintendent|site_super)/i.test(SRC),
    'and never off `role` — the registered CS on the live project holds `cp`, '
    + 'and NOBODY in production holds role "superintendent"');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
