/**
 * THE WORKER DETAIL SCREEN MUST NOT MANUFACTURE A SIGNATURE.
 *
 * app/workers/[id].jsx carried a stub signature pad whose "Save Signature"
 * button ran:
 *
 *   const handleUpdateSignature = () => {
 *     setSignature({ data: 'signature_data', signed_at: new Date().toISOString() });
 *     setShowSignaturePad(false);
 *     toast.success('Updated', 'Signature saved');
 *   };
 *
 * Not async. No await. No API call, no draft write, no storage of any kind.
 * The payload was the literal string 'signature_data'. The screen then rendered
 * "✍️ Signature on file" with signed_at formatted as a date — so an admin was
 * told "Signature saved" and shown a signature on file, dated today, for a
 * worker who has none. That is a fabricated compliance artifact.
 *
 * WHY THE AFFORDANCE IS REMOVED RATHER THAN IMPLEMENTED:
 *
 *   1. NO ENDPOINT ACCEPTS IT. PUT /workers/{id} filters the body through
 *      ALLOWED_WORKER_FIELDS = {name, phone, osha_number, certifications,
 *      emergency_contact, emergency_phone, notes}. `signature` is not in it,
 *      and no other route writes a worker signature. A pad left "visibly
 *      unimplemented" would advertise a capability the server has already
 *      declined to offer.
 *
 *   2. THE PROVENANCE MODEL FORBIDS IT. A real workers.signature is a base64
 *      PNG captured at the gate from the WORKER'S OWN device during
 *      register_and_checkin, alongside a device fingerprint and a language
 *      stamp. An admin drawing a worker's mark on a detail screen is a forged
 *      attestation. create_worker even hard-sets signature = None: a worker an
 *      admin creates starts with no signature BY DESIGN.
 *
 *   3. THE DATE ROW ONLY EVER SERVED THE FABRICATION. A stored signature is a
 *      bare string carrying no timestamp — server.py's own comment on
 *      _worker_signature_signed_at says so — and neither GET /workers/{id} nor
 *      /workers/{id}/osha-card returns a signed_at. So `signature.signed_at`
 *      could only ever be truthy when the fabricator had just set it.
 *
 * The READ path is legitimate and must survive: the screen displays a
 * signature the gate captured. This file pins the removal of the write and the
 * survival of the read.
 *
 * Run:  node src/utils/workerSignatureNotFabricated.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');
const SCREEN_PATH = path.join(FRONTEND, 'app', 'workers', '[id].jsx');
const raw = fs.readFileSync(SCREEN_PATH, 'utf8');

// Comments stripped, per workerPairingCopy.test.cjs. Every negative assertion
// below asks whether the screen DOES something, and prose explaining why it no
// longer does must not be able to answer that question either way — the
// explanation of a removed pad necessarily names the pad.
const screen = raw
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Guard against the empty-subject failure mode (see assertionsCanFail.test.cjs):
// every negative assertion below is meaningless if the file did not load, and
// meaningless again if the strip above ate the whole file.
ok(raw.length > 5000, 'the screen source loaded (negative assertions are meaningful)');
ok(screen.length > raw.length * 0.5,
  'the comment strip left the code behind (negative assertions are meaningful)');

// ── The fabrication itself ──────────────────────────────────────────────────
console.log('\napp/workers/[id].jsx — no fabricated signature record');

ok(!/signature_data/.test(screen),
  "the literal payload 'signature_data' is gone");
ok(!/handleUpdateSignature/.test(screen),
  'handleUpdateSignature no longer exists');
ok(!/setSignature\(\s*\{/.test(screen),
  'nothing constructs a signature OBJECT locally — signature state is only ever assigned from a server payload');
ok(!/signed_at:\s*new Date\(\)/.test(screen),
  'no locally minted signed_at timestamp');
ok(!/showSignaturePad/.test(screen),
  'the showSignaturePad state and its toggles are gone');

// The success toast is the part that made this a lie the user could read.
ok(!/Signature saved/.test(screen),
  'no toast claims a signature was saved');
ok(!/toast\.success\([^)]*Signature/i.test(screen),
  'no success toast mentions a signature at all');

// ── The stub UI that produced it ────────────────────────────────────────────
console.log('\napp/workers/[id].jsx — the stub pad and its affordance are gone');

ok(!/Signature pad would appear here/.test(screen),
  'the placeholder canvas is gone');
ok(!/Save Signature/.test(screen),
  'no "Save Signature" button');
ok(!/Add Signature/.test(screen),
  'no "Add Signature" affordance — there is no endpoint behind it');
ok(!/Draw Signature/.test(screen),
  'no "Draw Signature" pad title');
ok(!/signaturePad|signatureCanvas|signaturePadActions|signaturePadTitle|signatureCanvasPlaceholder/
  .test(screen),
  'the pad-only styles are removed with the pad');

// The stub pad wrapped its buttons in a raw <div>, which is not a React Native
// host component. It leaves with the pad.
ok(!/<div/.test(screen),
  'no raw <div> survives in a React Native screen');

// ── The date artifact ───────────────────────────────────────────────────────
console.log('\napp/workers/[id].jsx — no dated record for an undated signature');

ok(!/signature\?\.signed_at/.test(screen),
  'the screen no longer reads signed_at off the signature');
ok(!/signatureDate/.test(screen),
  'the "Updated: <date>" row and its style are gone');

// ── The READ path must survive ──────────────────────────────────────────────
console.log('\napp/workers/[id].jsx — the real signature is still displayed');

ok(/workerData\.signature/.test(screen),
  'the worker payload signature is still applied to state');
ok(/data\.signature/.test(screen),
  'the OSHA payload signature is still applied to state');
ok(/Signature on file/.test(screen),
  'a signature that EXISTS is still reported as on file');
ok(/No signature on file/.test(screen),
  'the absent case is still stated plainly');
ok(/resizeMode="contain"/.test(screen) && /signaturePreview/.test(screen),
  'the captured signature image is still rendered');

// The empty state must not read as a to-do the admin can action. It says where
// a signature actually comes from.
ok(/gate|check(-| )?in|register/i.test(
  screen.slice(screen.indexOf('No signature on file'),
    screen.indexOf('No signature on file') + 400)),
  'the empty state explains that a signature is captured at the gate, not here');

// ── The backend contract this fix rests on ──────────────────────────────────
// If someone later adds `signature` to the allowlist, the argument above stops
// holding and this test should be revisited deliberately, not silently.
console.log('\nbackend/server.py — the contract that makes the write impossible');

const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
const allowIdx = server.indexOf('ALLOWED_WORKER_FIELDS = {');
ok(allowIdx > -1, 'ALLOWED_WORKER_FIELDS still exists in update_worker');
const allowLine = server.slice(allowIdx, server.indexOf('}', allowIdx) + 1);
ok(allowLine.length > 40, 'the allowlist slice is non-empty');
ok(!/["']signature["']/.test(allowLine),
  'PUT /workers/{id} still refuses `signature` — there is no write path to build against');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
