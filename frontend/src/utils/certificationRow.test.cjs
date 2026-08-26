/**
 * The certification row says what the certification is, and the delete button
 * deletes.
 *
 * TWO DEFECTS ON ONE SCREEN, forty lines apart.
 *
 * THE ROW read `cert.name` and `cert.expiry`. A stored certification carries
 * NEITHER — the model is {type, card_number, expiration_date, verified,
 * needs_review, ...} and pydantic drops unknown keys, so even this screen's own
 * add form (which posts type/card_number/expiration_date, correctly) could not
 * produce a cert this screen could render. Result: an award icon, a blank line,
 * and a delete button.
 *
 * THE SCREEN ALREADY CONTRADICTED ITSELF. `flaggedCerts` reads `needs_review`
 * and `review_reason` — the right fields — and renders "⚠ Credential needs
 * review — Card class could not be read" in a banner directly above a row that
 * renders completely blank. One half knew about the certification; the other
 * did not.
 *
 * AND IT WAS INVISIBLE ONLY HERE. The same certification is read correctly by
 * validate_worker_certifications (the OSHA baseline — the one HARD BLOCK on
 * check-in), the LL196 attestation PDF, the nightly combined report, the risk
 * score, and the DOB-filed OSHA register. Blank on the one screen the CP would
 * use to check it, and load-bearing everywhere else.
 *
 * THE DELETE BUTTON was local state only: it filtered the row out, toasted
 * "Certification removed", and never called the endpoint. The record came back
 * on the next fetch — unless the CP then saved the edit form, which PUTs the
 * whole array and genuinely removes it. Either a lie or a delayed, unannounced
 * deletion, depending on what he did next.
 *
 *   node frontend/src/utils/certificationRow.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'workers', '[id].jsx');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

const raw = fs.readFileSync(SCREEN, 'utf8');
// COMMENTS STRIPPED. The screen's comments quote the old `cert.name` /
// `cert.expiry` lines so a reader knows what changed, and this file's own prose
// names them too. An unstripped source matches the explanation instead of the
// code — the trap this project has hit five times.
const src = raw
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

// Loaded through the shared harness (#222): oshaLogModel imports './dates',
// which a bare require cannot resolve under plain node. esmHarness resolves a
// RELATIVE import for real, so these are the shipped accessors and not stubs.
const { loadEsm } = require('./esmHarness.cjs');
const { certLabel, certExpiration } = loadEsm('src/utils/oshaLogModel.js');

// The shapes the backend actually writes (WorkerCertification, server.py:2090).
const OSHA = { type: 'OSHA_10', card_number: '12345678', expiration_date: null };
const SST = { type: 'SST_FULL', card_number: '99', expiration_date: '2027-03-01T00:00:00Z' };
const UNREADABLE = { type: 'SST_UNSPECIFIED', card_number: '77', needs_review: true,
  review_reason: 'CLASS_UNVERIFIED' };
const CARD_ONLY = { card_number: '4455', needs_review: true };
const NOTHING = { needs_review: true };

console.log('\n-- the row reads the keys the backend writes --');
{
  ok(!/\{cert\.name\}/.test(src),
    'cert.name is gone. Nothing in the backend has ever written it, and '
    + 'pydantic drops unknown keys so nothing ever could');
  ok(!/cert\.expiry/.test(src), 'and cert.expiry with it');
  ok(/certLabel\(/.test(src) && /certExpiration\(/.test(src),
    'it uses the shared accessors');
  ok(/from '\.\.\/\.\.\/src\/utils\/oshaLogModel'/.test(src),
    'imported from oshaLogModel — NOT a sixth copy of the label map');
}

console.log('\n-- the accessors resolve the real shapes --');
{
  ok(certLabel(OSHA) === 'OSHA 10', 'a stored OSHA_10 reads as "OSHA 10"');
  ok(certLabel(SST) === 'SST', 'SST_FULL reads as "SST"');
  ok(certLabel({ type: 'SST_TEMPORARY' }) === 'SST Temporary',
    'and a temporary card names itself — the class the LL196 attestation used '
    + 'to drop entirely');
  ok(certExpiration(SST) === '2027-03-01', 'expiration_date renders as a date');
  ok(certExpiration(OSHA) === '', 'and an absent expiry renders nothing, not "Invalid Date"');
  ok(certLabel({ name: 'Legacy Cert' }) === 'Legacy Cert',
    'the legacy `name` fallback still resolves — a hand-entered row keeps '
    + 'whatever it has');
}

console.log('\n-- render, never filter --');
{
  ok(/certDisplayName/.test(src), 'the screen has a display-name chain');
  ok(!/certifications\s*\.filter\([^)]*certLabel/.test(src)
    && !/\.filter\(\(c\) => certLabel/.test(src),
    'and nothing filters rows out on a missing label. A credential the app '
    + 'cannot describe is itself a finding, and a vanished row tells the CP '
    + 'nothing');
  ok(/certifications\.map\(/.test(src),
    'the list still maps every stored certification');

  // THE SHIPPED CHAIN, pinned structurally, because the mirror below is a
  // re-implementation: certDisplayName lives inside the component and cannot
  // be imported. Asserting its three arms here is what keeps the mirror honest.
  const chain = src.slice(src.indexOf('const certDisplayName'));
  const chainBody = chain.slice(0, chain.indexOf(');') + 2);
  ok(/certLabel\(cert\)/.test(chainBody), 'arm 1 is the type label');
  ok(/card_number \? `Card \$\{cert\.card_number\}`/.test(chainBody),
    'arm 2 is the card number');
  ok(/'Certification \(no type recorded\)'/.test(chainBody),
    'arm 3 is a sentence, not an empty string');
  ok(chainBody.indexOf('certLabel') < chainBody.indexOf('card_number')
    && chainBody.indexOf('card_number') < chainBody.indexOf('no type recorded'),
    'and in that order — the most specific answer the app has, first');

  // The chain, evaluated the way the screen evaluates it.
  const displayName = (cert) => (
    certLabel(cert)
    || (cert && cert.card_number ? `Card ${cert.card_number}` : '')
    || 'Certification (no type recorded)'
  );
  ok(displayName(OSHA) === 'OSHA 10', 'a typed cert shows its label');
  ok(displayName(CARD_ONLY) === 'Card 4455',
    'a cert with only a card number shows the number — better than a blank, '
    + 'and it is what the CP can match against the card in his hand');
  ok(displayName(NOTHING) === 'Certification (no type recorded)',
    'and one with neither says so in a sentence he can act on, rather than '
    + 'rendering empty');
  ok(displayName(UNREADABLE) === 'SST_UNSPECIFIED',
    'an unreadable CLASS passes through verbatim — ugly and true. It must not '
    + 'print as a class the OCR could not read');
}

console.log('\n-- the screen no longer contradicts itself --');
{
  ok(/needs_review \|\| c\.review_reason/.test(src),
    'the flagged-credential banner still reads the right fields — it always '
    + 'did, which is why it warned about a row that rendered blank');
  const flagged = certLabel(UNREADABLE) || `Card ${UNREADABLE.card_number}`;
  ok(flagged.length > 0,
    'and the row the banner warns about now renders something. The banner and '
    + 'the row finally describe the same certification');
}

console.log('\n-- the delete button deletes --');
{
  const i = src.indexOf('const handleDeleteCertification');
  ok(i > -1, 'the handler exists');
  const body = src.slice(i, src.indexOf('const handleUpdateSignature', i));

  ok(/apiClient\.delete\(/.test(body),
    'it calls the endpoint. It used to be local state only: filter the row '
    + 'out, toast "Certification removed", never call the server');
  ok(/\/certifications\/\$\{index\}/.test(body),
    'by INDEX, which is what DELETE /workers/{id}/certifications/{cert_index} '
    + 'takes — and the list is unfiltered, so the row index IS the stored index');
  ok(/toast\.error\(/.test(body),
    'a failure is ANNOUNCED. The old handler reported success unconditionally');
  ok(body.indexOf('apiClient.delete') < body.indexOf("toast.success"),
    'and success is claimed only AFTER the call — a control that reports '
    + 'success for something that did not happen is worse than no control');
  ok(/return;/.test(body),
    'the failure path returns rather than falling through to the success toast');
  ok(/getWorkerById\(/.test(body),
    're-reads from the server rather than splicing locally — a local filter is '
    + 'what made the old control look like it had worked');
}

console.log('\n-- the write path was always correct and is untouched --');
{
  const i = src.indexOf('const handleAddCertification');
  const body = src.slice(i, src.indexOf('const handleDeleteCertification', i));
  ok(/type: newCertType/.test(body) && /card_number: newCertName/.test(body)
    && /expiration_date: newCertExpiry/.test(body),
    'the add form still posts type / card_number / expiration_date — it was '
    + 'never the defect, and matches WorkerCertification exactly');
}

console.log('\n-- the other consumers are not touched --');
{
  // The same certification is load-bearing on surfaces this PR does not go
  // near. Pinned so a future "cleanup" of the model cannot be mistaken for
  // safe because one screen was fixed.
  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  ok(/def validate_worker_certifications/.test(server),
    'the gate validator still exists — it reads `type` for the OSHA baseline, '
    + 'the one HARD BLOCK on check-in');
  ok(/c\.get\("type", ""\)/.test(server),
    'and still reads the real key');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
