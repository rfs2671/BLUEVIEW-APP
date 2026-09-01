/**
 * THE CONSENT GATE — and the four answers it must keep apart.
 *
 * BB 2024-007 § V.5 requires that a signer intends to sign electronically and
 * agrees to conduct business electronically. The backend has recorded that
 * since #308 and NOTHING EVER ASKED: `has_current_esra_consent` was called by
 * its own tests and by nothing else, and no screen mentioned consent.
 *
 * RETROFITTING CANNOT REACH BACKWARDS, which is why this ships before the
 * superintendent-log toggle is turned on and not after. A consent recorded
 * tomorrow does not describe a signature applied today.
 *
 * WHAT THIS FILE EXECUTES. esraConsentState.js is pure, so the rule is RUN
 * rather than read. The earlier version of the superintendent test grepped a
 * COMMENT that said the code did not manufacture an attestation, and a mutant
 * that made it do exactly that survived. The rule about what counts as consent
 * is not going to be asserted by reading it.
 *
 *   node src/utils/esraConsentGate.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

/** Comments stripped for anything asserting what the code DOES. */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const SCREEN = read('app', 'logbooks', 'site_superintendent_log.jsx');
const HOOK = read('src', 'hooks', 'useEsraConsent.js');
const SCREEN_CONSENT = read('app', 'consent.jsx');

const M = loadEsm('src/utils/esraConsentState.js');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. FOUR STATES, AND ABSENCE IS NOT A NO');
{
  ok(M.consentState({ has_consented: true, is_current: true }) === M.READY,
    'agreed to the current wording is READY');
  ok(M.consentState({ has_consented: false, is_current: false }) === M.NOT_AGREED,
    'a server answer of "has not agreed" is NOT_AGREED');
  ok(M.consentState({ has_consented: true, is_current: false }) === M.STALE,
    'agreed to EARLIER wording is STALE, not never-agreed — telling a man who '
    + 'agreed last year that he never did is false');

  // THE DISTINCTION THIS PROJECT KEEPS RELEARNING. cs_attribution keeps
  // NO_REGISTRATION apart from NOT_REGISTERED_CS for the same reason, and
  // collapsing that pair is what produced 285 false flags.
  ok(M.consentState(null) === M.UNKNOWN, 'a FAILED READ is UNKNOWN, not "has not agreed"');
  ok(M.consentState(undefined) === M.UNKNOWN, 'and so is no answer at all');
  ok(M.consentState({}) === M.UNKNOWN,
    'and so is a body that answers neither question — an endpoint returning a '
    + 'shape we do not recognise has told us nothing');
  ok(M.consentState('yes') === M.UNKNOWN && M.consentState(7) === M.UNKNOWN,
    'a non-object is never a consent');
}

console.log('\n1b. A REFUSAL IS ITS OWN STATE');
{
  ok(M.consentState({ has_consented: false, is_current: false, has_declined: true })
     === M.DECLINED,
  'asked and refused is DECLINED, not merely not-agreed — one asks a '
  + 'question, the other states a consequence');

  // ORDER IS THE RULE. A man who declined in March and agreed in April has
  // AGREED. A decline is a fact that was true when recorded, never a standing
  // veto over a later consent.
  ok(M.consentState({ has_consented: true, is_current: true, has_declined: true })
     === M.READY,
  'a CURRENT consent outranks an earlier decline');
  ok(M.canSign(M.DECLINED) === false, 'and a decline does not sign');
}

console.log('\n2. ONLY ONE STATE MAY SIGN');
{
  ok(M.canSign(M.READY) === true, 'READY signs');
  for (const s of [M.NOT_AGREED, M.STALE, M.UNKNOWN, undefined, null, 'ready ']) {
    ok(M.canSign(s) === false, `${JSON.stringify(s)} does NOT sign`);
  }
  // FAIL CLOSED, STATED AS A TEST because it is a decision with a cost: an
  // outage stops a statutory filing. It is bearable only while the editor is
  // online-only; when the log goes local-first this must be re-taken.
  ok(M.canSign(M.consentState(null)) === false,
    'a signature is NOT applied while we cannot tell whether consent exists');
}

console.log('\n3. THE VERSION SENT BACK IS THE SERVER\'S CURRENT ONE');
{
  ok(M.versionToAgree({ current_version: 'v2', agreed_version: 'v1' }) === 'v2',
    'the CURRENT wording, never the one previously agreed');
  // Echoing agreed_version would walk straight into the server's own refusal
  // (ESRA_CONSENT_VERSION_STALE) on the STALE path — the one path where
  // re-agreeing is the entire point.
  ok(M.versionToAgree({ current_version: 'v2', agreed_version: 'v1' }) !== 'v1',
    'so a re-agreement cannot be recorded against text he was never shown');
  ok(M.versionToAgree(null) === undefined, 'and a failed read yields no version to send');
}

console.log('\n4. THE SERVER NAMES THE CONDITION, THE CLIENT OWNS THE WORDING');
{
  const t = (k) => ({
    code_ESRA_CONSENT_VERSION_STALE: 'the wording changed',
    genericError: 'generic',
  }[k] || k);
  ok(M.consentGateCopy(t, 'ESRA_CONSENT_VERSION_STALE') === 'the wording changed',
    'a known code maps to its own copy');
  ok(M.consentGateCopy(t, 'SOMETHING_NEW') === 'generic',
    'an UNMAPPED code falls back to the generic — never `code_SOMETHING_NEW` '
    + 'rendered at a superintendent');
  ok(M.consentGateCopy(t, '') === '' && M.consentGateCopy(t, null) === '',
    'and no code is no message');
}

console.log('\n5. THE GATE IS ON THE SIGNATURE, IN THE SCREEN');
{
  const code = CODE(SCREEN);
  ok(/if \(!\(await consent\.ensure\(\)\)\) return;/.test(code),
    'the submit path stops on anything short of a recorded current consent');
  ok(code.indexOf('consent.ensure()') < code.indexOf('setSigning(true)'),
    'BEFORE any write — a refusal must not leave a half-created log');
  ok(code.indexOf('consent.ensure()') > code.indexOf('isAffirmedSignature(cpSignature)'),
    'and after the local guards, so he is not asked about consent on a submit '
    + 'that was going to be refused anyway');

  // NOT AT SCREEN OPEN. A consented user — everyone after the first time —
  // must not pay a round trip on a screen he opens daily, and an outage must
  // not present itself as a consent problem before he has typed anything.
  ok(!/useEffect\([^)]*\)\s*=>\s*\{[^}]*ensure\(/.test(CODE(HOOK)),
    'the hook does not fetch on mount');
  ok(/does not fetch on mount|NOT FETCH ON MOUNT|DOES NOT FETCH ON MOUNT/i.test(HOOK),
    'and says why, so the next reader does not "fix" it into an open-time gate');
}

console.log('\n6. A FIRST-CLASS SCREEN, AND NEVER A DEAD END BY ACCIDENT');
{
  const scr = CODE(SCREEN_CONSENT);

  // IT IS A ROUTE, NOT A SHEET. A legal act has to be readable at length, and
  // a modal invites the gesture that dismisses it.
  ok(/app[\\/]consent\.jsx/.test('app/consent.jsx'), 'ANCHOR: the file is a route');
  ok(!/from 'react-native'[\s\S]{0,200}\bModal\b/.test(scr),
    'and it renders no Modal');
  ok(/router\.push\('\/consent'\)/.test(CODE(HOOK)),
    'the gate PUSHES to it');

  // THE LINE THE WHOLE DESIGN RESTS ON. `replace` would discard the editor and
  // the half-filled log with it.
  ok(!/router\.replace\('\/consent'\)/.test(CODE(HOOK)),
    'and never REPLACES — push keeps the editor mounted, so his entry survives');
  ok(/router\.back\(\)/.test(scr),
    'and it returns him with back(), to the screen still underneath');

  ok(/isAskable\(state, text\)/.test(scr),
    'UNKNOWN offers RETRY and never Agree — recording a decision we could not '
    + 'first read back is how a contradiction gets written');

  const en = read('src', 'i18n', 'en.js');
  for (const k of ['consentNeededBody', 'consentChangedBody',
    'consentUnavailableBody', 'consentDeclinedBody', 'consentAlreadyBody']) {
    ok(new RegExp(`${k}:`).test(en), `${k} exists — every state says where he stands`);
  }
  ok(/entered is kept/.test(en),
    'the outage copy says his entry is KEPT — the difference between a wait '
    + 'and a wall');
  ok(/leave it unsigned/.test(en),
    'and the way out says what actually happens, rather than "Cancel"');
}

console.log('\n6b. DECLINING IS HONEST, RECORDED, AND NOT A TRAP');
{
  const scr = CODE(SCREEN_CONSENT);
  const en = read('src', 'i18n', 'en.js');
  const api = CODE(read('src', 'utils', 'api.js'));

  ok(/esraConsentAPI\.decline\(version\)/.test(scr), 'he can decline');
  ok(/'\/api\/esra-consent\/decline'/.test(api),
    'and it is RECORDED server-side, not just a client state');

  // THE DEAD END, STATED. Not softened, not re-asked in other words.
  ok(/cannot file this log electronically without accepting/.test(en),
    'the consequence is stated plainly');
  // JOINED FIRST. The copy is a multi-line string concatenation, so "Paper "
  // ends one line and "remains available" begins the next. A control run
  // replaced "Paper " with "No " and this assertion still passed on the
  // orphaned half — matching a fragment of a sentence is not matching the
  // sentence.
  const joined = en.replace(/'\s*\+\s*'/g, '').replace(/\s+/g, ' ');
  ok(/Paper remains available/.test(joined),
    'and the alternative is named IN FULL — never a silent block');
  ok(/cannot file this log electronically without accepting\. Paper remains available/
    .test(joined),
  'the consequence and the alternative are one sentence, in that order');
  ok(/declinedOn:/.test(en) && /\{date\}/.test(en),
    'the refusal is shown back with its date');

  // NOT A TRAP. The agreement stays on the page and the button says so.
  ok(/agreeAfterAll/.test(scr) && /agreeAfterAll:/.test(en),
    'he can still agree afterwards — a one-tap permanent lock would be a '
    + 'state with no exit, and the wording itself promises he may withdraw');
  ok(/state === DECLINED \? null : \(/.test(scr),
    'but he is not offered Decline a second time — the state already says it');
}

console.log('\n7. THE WORDING IS THE SERVER\'S, VERBATIM');
{
  // lib/esra_consent.py: a consent whose text the client chooses is evidence
  // of nothing. A client that invents wording when the real wording is missing
  // is exactly that, so there is no fallback text anywhere.
  const modal = CODE(SCREEN_CONSENT);
  ok(/\{String\(text\)\.split/.test(modal), 'it renders the text it was given');
  ok(!/I agree to do business electronically/.test(modal + CODE(HOOK) + CODE(SCREEN)),
    'and NO copy of the agreement exists on the client — not in the modal, '
    + 'the hook or the screen');
  const en = read('src', 'i18n', 'en.js');
  ok(!/I agree to do business electronically/.test(en),
    'nor in the translation catalogue, which is where a "helpful" copy would go');
  ok(/current_text/.test(CODE(SCREEN_CONSENT)),
    'the screen takes the wording from the response');
  ok(/setText\(''\)/.test(CODE(SCREEN_CONSENT)),
    'and CLEARS it on a failed read, so stale wording is never shown as though '
    + 'this response carried it');
}

console.log('\n7b. HIS ENTRY SURVIVES THE TRIP, WITHOUT TRUSTING THE NAVIGATOR');
{
  // WHY THIS EXISTS. The consent screen is a route, and the design rested on
  // "expo-router's Stack keeps the screen beneath a push mounted". THREE
  // ATTEMPTS TO VERIFY THAT IN A HEADLESS BROWSER WERE INCONCLUSIVE — the
  // first navigated the document instead of the navigator, the next two never
  // reached a control that navigates. Probably true is not the standard for
  // whether a man loses a filled compliance log, so the design stops
  // depending on it and this asserts the replacement.
  const S = loadEsm('src/utils/logbookScratch.js');
  const code = CODE(SCREEN);

  const k = S.scratchKey('site_superintendent_log', 'p1', '2026-09-02');
  ok(k.includes('p1') && k.includes('2026-09-02') && k.includes('site_superintendent_log'),
    'the key names the type, the project AND the date — one stash per document');
  ok(S.scratchKey('a', 'p1', 'd') !== S.scratchKey('b', 'p1', 'd'),
    'so two logs on one day cannot overwrite each other');

  S.stash(k, { arrivedAt: '07:00' });
  ok(S.take(k)?.arrivedAt === '07:00', 'what was stashed comes back');
  ok(S.take(k) === null,
    'and it is TAKEN, not read — a lingering stash would resurrect abandoned '
    + 'edits onto a later visit');
  ok(S.take('never-stashed') === null,
    'nothing held reads as null, never as an empty form — restoring {} over a '
    + 'loaded document would blank it');
  S.stash(k, null);
  ok(S.take(k) === null, 'a nullish value clears rather than storing nothing');

  ok(code.indexOf('stash(scratchId, snapshot());') < code.indexOf('consent.ensure()'),
    'the editor stashes BEFORE the gate can navigate');
  ok(/drop\(scratchId\);/.test(code),
    'and drops it when it did not navigate after all');
  ok(/const held = take\(scratchId\);/.test(code)
     && code.indexOf('hydrate(existing.data') < code.indexOf('const held = take(scratchId)'),
  'the restore runs AFTER the server hydrate — the stash is newer and wins');
  ok(/!\(existing && existing\.is_locked === true\)/.test(code),
    'but never onto a FROZEN document, which is read-only');
}

console.log('\n8. AGREEING DOES NOT SIGN FOR HIM');
{
  // CHECKED ON THE CONSENT SCREEN, which is where the chain would now be
  // written. This assertion used to read the EDITOR, and after the modal
  // became a route it was pointing at a file that could no longer contain the
  // defect — it passed for the wrong reason, and a control run said so by
  // chaining the submit and going undetected.
  const scr = CODE(SCREEN_CONSENT);
  ok(!/handleSubmit|onSubmit|\.submit\(/.test(scr),
    'the consent screen cannot reach a submit at all — a signature applied '
    + 'from a tap on a different button is not an intent to sign');
  ok(/router\.back\(\);/.test(scr) && !/router\.back\(\);\s*[a-zA-Z]/.test(scr),
    'agreeing returns him to the editor and stops there; he taps Sign himself');
  ok(!/onAgree=\{[^}]*handleSubmit/.test(CODE(SCREEN)),
    'and the editor wires nothing into the agreement either');
  ok(/RE-READ/.test(SCREEN_CONSENT) && /const after = await read\(\);/.test(CODE(SCREEN_CONSENT)),
    'and the screen re-reads the server rather than trusting the POST body, '
    + 'which reports what the request DID and not whether he may now sign');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
