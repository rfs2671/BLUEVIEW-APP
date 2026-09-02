/**
 * THE `.catch` ON EVERY recordSignatureEvent CALL IS DEAD CODE.
 *
 * Thirteen call sites end the same way:
 *
 *     recordSignatureEvent({...}).catch(e =>
 *       console.warn('Signature audit failed (non-blocking):', e?.message));
 *
 * and not one of those handlers has ever run. recordSignatureEvent catches its
 * own error and RETURNS NULL, so the promise resolves. The handler reads like
 * the failure is being observed; the failure is discarded one frame earlier.
 *
 * What it discards is the only contemporaneous evidence there is. The line it
 * does print —
 *
 *     console.error('Failed to record signature event:', error)
 *
 * — names no document, no project, no date and no signer, so even on a device
 * whose console someone could read, it cannot be tied to a record.
 *
 * AND THE OFFLINE CASE IS NOT A FAILURE AT ALL, IT IS A SKIP. Every caller
 * guards on `if (docId)`. Offline there is no server id, the call never
 * happens, nothing is logged, and the log still files — the draft drains later
 * through draftSync, which pushes the signature and has never recorded an
 * event. That is a ledger gap with no failure anywhere to observe.
 *
 * This asserts the client half: that a failed or skipped ledger write says WHAT
 * IT WAS FOR, under the same tag the server uses, so one grep spans both.
 * (The durable half is server-side — sweep_signature_ledger_gaps and the
 * finalize check — because a console line on a CP's phone is not findable.)
 *
 * Run:  node src/utils/signatureLedgerObservability.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const audit = fs.readFileSync(
  path.join(FRONTEND, 'src', 'utils', 'signatureAudit.js'), 'utf8');
const supe = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'site_superintendent_log.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The failure path of recordSignatureEvent, from its catch to the return.
// Newline-agnostic on purpose: these files are CRLF and a \n-anchored regex
// matches nothing, which is a test that passes for the wrong reason.
const catchBlock = /\} catch \(error\) \{[\s\S]*?return null;\s*\}/.exec(
  audit.slice(audit.indexOf('export async function recordSignatureEvent')));
const failure = catchBlock ? catchBlock[0] : '';

console.log('\n-- a failed ledger write says what it was for --');

ok(!!failure, 'recordSignatureEvent still has a failure path to inspect');

ok(/\[signature-ledger\]/.test(failure),
  'the failure is tagged [signature-ledger] — the same tag the server writes, '
  + 'so one grep spans the device log and the server log');

ok(/documentId/.test(failure) && /documentType/.test(failure),
  'the failure names the DOCUMENT: "Failed to record signature event" with no '
  + 'id is indistinguishable from any other failure on any other record');

ok(/eventType/.test(failure) && /signerName/.test(failure),
  'the failure names the event type and the signer — who signed what, which is '
  + 'the pair an auditor reconciles against');

ok(!/console\.error\('Failed to record signature event:', error\);/.test(audit),
  'the identity-free line is GONE — it was the whole of the client-side record '
  + 'of a lost signature event');

console.log('\n-- and a write that never happens is not silence --');

ok(/if \(!documentId\)/.test(audit),
  'recordSignatureEvent itself notices a missing documentId: the callers guard '
  + 'on `if (docId)` and skip, so without this the offline case — the one that '
  + 'actually files a signed log with no ledger row — is reported by nothing');

const skip = /if \(!documentId\) \{[\s\S]*?return null;\s*\}/.exec(audit);
ok(!!skip && /\[signature-ledger\]/.test(skip[0]),
  'the skip is reported under the ledger tag too');

ok(!!skip && /return null;/.test(skip[0]),
  'and it still returns null rather than POSTing a null document_id — the '
  + 'contract stays fail-soft: a ledger write must never cost a CP his log');

console.log('\n-- the one caller whose ORDER matters awaits it --');

// site_superintendent_log is the only editor that finalizes in the same
// handler that signs. Fire-and-forget there means /finalize can reach the
// server before the ledger POST does, and the server-side gap check at
// finalize would then report a gap that is merely in flight.
const iSig = supe.indexOf('recordSignatureEvent({');
const iFin = supe.indexOf('logbooksAPI.finalize(');
ok(iSig > 0 && iFin > iSig,
  'the signature event is recorded before the finalize call (order unchanged)');

ok(/await recordSignatureEvent\(\{/.test(supe),
  'it is AWAITED: this handler finalizes in the same breath, so an un-awaited '
  + 'ledger POST races the seal and the server-side gap check at finalize would '
  + 'report a row that is merely in flight');

ok(!/recordSignatureEvent\(\{[\s\S]*?\}\)\.catch\(/.test(supe),
  'the dead `.catch` is gone — recordSignatureEvent resolves with null on '
  + 'failure and has never rejected, so that handler was never once called');

const observed = supe.slice(iSig - 200, iFin);
ok(/_evtId/.test(observed) && /\[signature-ledger\]/.test(observed),
  'the RETURN VALUE is observed: null is how this function reports a lost '
  + 'ledger write, and the caller that seals the record a few lines later is '
  + 'the one caller that must not throw it away');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
