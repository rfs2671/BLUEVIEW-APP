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
const MODAL = read('src', 'components', 'EsraConsentModal.jsx');

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

console.log('\n6. IT IS NEVER A DEAD END');
{
  const modal = CODE(MODAL);
  ok(/onRetry/.test(modal) && /onAgree/.test(modal),
    'every state offers a way forward — Agree, or Retry');
  ok(/const askable = !isUnknown && haveText;/.test(modal),
    'UNKNOWN offers RETRY and never Agree — recording an agreement we could '
    + 'not first read back is how a contradiction gets written');
  ok(/haveText/.test(modal),
    'and no wording means no Agree button, rather than a button over an empty box');
  ok(/onClose/.test(modal),
    'it can be dismissed — a consent that cannot be declined is not freely '
    + 'given, and the wording itself promises he can withdraw');

  const en = read('src', 'i18n', 'en.js');
  for (const k of ['consentNeededBody', 'consentChangedBody', 'consentUnavailableBody']) {
    ok(new RegExp(`${k}:`).test(en), `${k} exists — every state says what is missing`);
  }
  ok(/Everything you have \n?\s*'?\+?\s*'?entered is kept/.test(en.replace(/\s+/g, ' '))
     || /entered is kept/.test(en),
  'and the outage copy says his entry is KEPT — the difference between a '
    + 'wait and a wall');
  ok(/leave this unsigned/.test(en),
    'the dismiss says what actually happens, rather than "Cancel"');
}

console.log('\n7. THE WORDING IS THE SERVER\'S, VERBATIM');
{
  // lib/esra_consent.py: a consent whose text the client chooses is evidence
  // of nothing. A client that invents wording when the real wording is missing
  // is exactly that, so there is no fallback text anywhere.
  const modal = CODE(MODAL);
  ok(/\{String\(text\)\.split/.test(modal), 'it renders the text it was given');
  ok(!/I agree to do business electronically/.test(modal + CODE(HOOK) + CODE(SCREEN)),
    'and NO copy of the agreement exists on the client — not in the modal, '
    + 'the hook or the screen');
  const en = read('src', 'i18n', 'en.js');
  ok(!/I agree to do business electronically/.test(en),
    'nor in the translation catalogue, which is where a "helpful" copy would go');
  ok(/current_text/.test(CODE(HOOK)),
    'the hook takes the wording from the response');
  ok(/setText\(''\)/.test(CODE(HOOK)),
    'and CLEARS it on a failed read, so stale wording is never shown as though '
    + 'this response carried it');
}

console.log('\n8. AGREEING DOES NOT SIGN FOR HIM');
{
  ok(!/onAgree=\{[^}]*handleSubmit/.test(CODE(SCREEN)),
    'the Agree button never chains into the submit — a signature applied from '
    + 'a tap on a different button is not an intent to sign');
  ok(/re-read|RE-READ/.test(HOOK),
    'and the hook re-reads the server rather than trusting the POST body, '
    + 'which reports what the request DID and not whether he may now sign');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
