/**
 * THE CLIENT HALF OF A LEDGER ROW THAT SURVIVES HAVING NO SIGNAL.
 *
 * The durable half is server-side: ensure_signature_ledger_row DERIVES a
 * signature event from the document the server accepts, so a signature made in
 * a basement reaches the ledger when the draft drains, without a retry queue on
 * a device that can be lost. But three things on THIS side are now load-bearing
 * for that, and none of them looks load-bearing while you are editing it:
 *
 *   1. THE SIGNING INSTANT LIVES INSIDE THE SIGNATURE OBJECT. SignaturePad
 *      stamps `timestamp`, `affirmed` and `affirmedAt` at the moment of the
 *      stroke, and that object travels with the document. It is the ONLY reason
 *      a row derived five hours later can carry the time the person actually
 *      signed. Stop stamping it and every derived row silently falls back to
 *      recording no signing time at all.
 *
 *   2. THE SIGNATURE OBJECT IS WHAT recordSignatureEvent POSTS. The server
 *      computes one idempotency fingerprint per signing act from that object,
 *      on BOTH writers, so the client's row and the derived row recognise each
 *      other. Post a different shape and one signature lands in the ledger
 *      twice.
 *
 *   3. THE DRAIN'S /finalize IS THE DERIVATION TRIGGER. applyRemoteFreeze is
 *      gated on `draft.finalized`. Narrow that gate and the offline gap
 *      reopens with nothing failing anywhere to say so — which is exactly how
 *      it went unnoticed the first time.
 *
 *      THIS USED TO ADD "and every signed draft is locally finalized before it
 *      drains", AND THAT WAS FALSE WHEN IT WAS WRITTEN. It is contradicted by
 *      backend/tests/test_end_of_day_sweep.py, which asserts that
 *      daily_jobsite and ssc_daily_safety_log do NOT call markFinalized on the
 *      sign path — the END_OF_DAY class exists so a narrative signed at 9am is
 *      not frozen at 9am. LogbookLockBar reaches the same shape from the other
 *      side: it calls logbooksAPI.finalize(logId) and never markFinalized, so
 *      a log the SERVER has locked can still drain as an unfinalized draft.
 *
 *      So the gate is narrower than the population of signed drafts, and that
 *      is by design. What the gate must NOT do is report success for the
 *      drafts it skips: for the VISIT class there is no second actor — the
 *      end-of-day sweep excludes VISIT_LOG_TYPES — so a silently skipped
 *      freeze leaves a signed superintendent log editable and unlocked
 *      forever while the screen shows it signed. The assertions below pin the
 *      gate AND the three states it now returns.
 *
 * And the two end-of-day editors now AWAIT their ledger write before calling
 * /finalize. Not for tidiness: fired and forgotten it races the server's
 * derivation, and the derived row is the one that CANNOT carry the signing
 * device or the signing IP. Ordering them is what lets the accurate row win for
 * a CP who was online the whole time.
 *
 * Run:  node src/utils/signatureLedgerDurability.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8');

const pad = read('src', 'components', 'SignaturePad.js');
const audit = read('src', 'utils', 'signatureAudit.js');
const drain = read('src', 'utils', 'draftSync.js');
const daily = read('app', 'logbooks', 'daily_jobsite.jsx');
const ssc = read('app', 'logbooks', 'ssc_daily_safety_log.jsx');
const orientation = read('app', 'logbooks', 'subcontractor_orientation.jsx');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── 1. the signing instant is stamped into the signature ────────────────────

console.log('\n-- the signing instant survives the sync --');

// handleConfirm is the fresh-draw path; handleAffirm re-stamps an inherited
// credential. Both must carry the stamp, because both produce a signature that
// can be filed offline and derived from later.
const confirmBlock = /const handleConfirm = useCallback\(\(\) => \{[\s\S]*?\}, \[[^\]]*\]\);/
  .exec(pad);
const confirm = confirmBlock ? confirmBlock[0] : '';

ok(!!confirm, 'SignaturePad still has a handleConfirm to inspect');

ok(/affirmedAt:\s*now/.test(confirm),
  'the confirmed signature carries affirmedAt — the field a server-derived '
  + 'row reads for the time the person actually signed');

ok(/timestamp:\s*now/.test(confirm),
  'the confirmed signature carries timestamp — the fallback the derivation '
  + 'reads when affirmedAt is absent');

ok(/affirmed:\s*true/.test(confirm),
  'the confirmed signature carries affirmed:true — _is_affirmed_signature is '
  + 'what decides that there is a signing act here at all');

ok(/affirmedAt/.test(pad.slice(pad.indexOf('handleAffirm'))),
  'the AFFIRM path stamps affirmedAt too — an inherited credential affirmed '
  + 'offline is derived from exactly like a fresh draw');

// ── 2. the object the server fingerprints is the one that is posted ─────────

console.log('\n-- the posted payload is what the server keys on --');

const payloadBlock = /const payload = \{[\s\S]*?\};/.exec(
  audit.slice(audit.indexOf('export async function recordSignatureEvent')));
const payload = payloadBlock ? payloadBlock[0] : '';

ok(!!payload, 'recordSignatureEvent still builds a payload to inspect');

ok(/signature_data:\s*signatureData/.test(payload),
  'the POST still sends signature_data — the server computes ONE idempotency '
  + 'fingerprint per signing act from it, on both writers, and without it the '
  + 'client row and the derived row cannot recognise each other');

ok(/document_id:\s*documentId/.test(payload) && /event_type:\s*eventType/.test(payload),
  'the POST still sends document_id and event_type — the other two halves of '
  + 'the signing act the fingerprint is taken over');

// ── 3. the drain still reaches the derivation trigger ──────────────────────

console.log('\n-- the drain still calls the request that derives the row --');

const freeze = /const applyRemoteFreeze = async \(id\) => \{[\s\S]*?\n  \};/.exec(drain);
const freezeFn = freeze ? freeze[0] : '';

ok(!!freezeFn, 'draftSync still has applyRemoteFreeze to inspect');

ok(/logbooksAPI\.finalize\(id\)/.test(freezeFn),
  'the drain still calls /finalize — the request that carries no signature, '
  + 'which is how the server knows no client write is in flight and a missing '
  + 'ledger row is a real gap rather than one in transit');

// THE CLAIM THIS ASSERTION USED TO CARRY WAS FALSE, AND THE PIN WAS ITS
// LOAD-BEARING HALF. It read: "the freeze gate is still `draft.finalized` —
// every signed draft is locally finalized before it drains, so this is also
// the condition that decides whether the ledger ever hears about an offline
// signature." The second clause is contradicted by
// backend/tests/test_end_of_day_sweep.py (the end-of-day editors deliberately
// do NOT markFinalized on the sign path). The THIRD clause is true and is the
// reason to pin the gate at all, so it survives — separated from the false
// premise it was resting on, and with the regex loosened off `|| !id`, which
// is now a defect of its own handled at the create call site.
ok(/if \(!draft\.finalized\)/.test(freezeFn),
  'the freeze gate is still `draft.finalized` — NOT a synonym for "signed" '
  + '(the two end-of-day editors leave a signed draft unfinalized on purpose, '
  + 'and LogbookLockBar finalizes server-side without ever setting it), but '
  + 'still the condition that decides whether the ledger hears about an '
  + 'offline signature');

// ── AND A GATE THAT SKIPS MUST SAY SO ──────────────────────────────────────
//
// The gate being narrower than "signed" is fine. Reporting SUCCESS for the
// drafts it skips is not: both call sites read `ok` alone, so "I had nothing
// to do" cleared the pending key and took the banner down with exactly the
// confidence of "I locked it on the server".

ok(/skipped:\s*true/.test(freezeFn) && /skipped:\s*false/.test(freezeFn),
  'applyRemoteFreeze distinguishes "nothing to do" from "did it" — three '
  + 'states, not two');

ok(/isAffirmedSignature\(body\.cp_signature\)/.test(freezeFn),
  'the skip REASON is decided by the affirmed predicate, not by `!!signature` '
  + '— production held `cp_signature: {}`, truthy and attested by nobody, and '
  + 'a bare `skipped: true` would fire on every unsigned autosave in the '
  + 'queue and be tuned out');

ok(/isVisitLog\(parsed\.logType\)/.test(freezeFn),
  'and it separates a freeze somebody else will apply from one NOTHING will: '
  + 'sweep_stale_end_of_day_logs excludes VISIT_LOG_TYPES, so a signed '
  + 'superintendent visit log this drain skips is frozen by nobody, ever');

ok(/if \(held\) return held;/.test(drain)
  && (drain.match(/await handleSkippedFreeze\(/g) || []).length >= 2,
  'BOTH call sites handle the skipped state before clearPending — the update '
  + 'branch and the create branch, which is where the 33 came from');

// ── THE OTHER HALF OF THE OLD EARLY RETURN ─────────────────────────────────
//
// `!id` shared that `if` and is a different defect: on the create branch a 200
// with no id early-returned ok:true, clearPending ran, the banner came down,
// and the drain counted a success for a response that never proved a document
// exists. site_superintendent_log.jsx throws NO_RECORD_RETURNED for exactly
// this shape on the editor path; the drain must refuse rather than report it.
ok(/if \(!newId\) \{/.test(drain) && /reason: 'no-record-returned'/.test(drain),
  'a create that returns no id is REFUSED by the drain, not absorbed — the '
  + 'key stays pending and the refusal is recorded against the draft key, '
  + 'which is the only handle a create with no id leaves behind');

ok(!/if \(newId\) await setDraftBackendId/.test(drain),
  'and setDraftBackendId is no longer the thing guarding that response — the '
  + 'refusal above is, so the binding below it is unconditional');

// Both push branches must reach it: an update of a known log and a create of
// one the server has never seen. The offline case is overwhelmingly the second.
const freezeCalls = (drain.match(/await applyRemoteFreeze\(/g) || []).length;
ok(freezeCalls >= 2,
  'both drain branches (update and create) still apply the remote freeze — a '
  + 'create that skipped it would leave every first-time offline log with no '
  + 'ledger row, which is the exact shape of the 33');

// ── 4. the end-of-day editors do not race the derivation ───────────────────

console.log('\n-- the online row is allowed to win --');

for (const [name, src] of [['daily_jobsite', daily], ['ssc_daily_safety_log', ssc]]) {
  const call = /await recordSignatureEvent\(\{/.test(src);
  ok(call,
    `${name} AWAITS its ledger write — fired and forgotten it races the `
    + '/finalize a few lines later, and the server\'s derived row (which '
    + 'cannot carry the signing device or IP) can win for a CP who was '
    + 'online the whole time');

  ok(!/\}\)\.catch\(\(e\) => console\.warn\('Signature audit failed/.test(src),
    `${name} no longer ends the ledger write with the dead .catch — `
    + 'recordSignatureEvent resolves with null and has never rejected, so '
    + 'that handler has never once run');
}

// ── 5. the comment that was false is no longer making the claim ────────────

console.log('\n-- the comment that claimed the gap did not exist --');

ok(!/an offline sign is audited when it syncs\./.test(orientation)
   || /IT NOW IS/.test(orientation),
  'subcontractor_orientation no longer asserts flatly that an offline sign is '
  + 'audited when it syncs — it was false for as long as it stood, and it is '
  + 'true now for a reason that has nothing to do with the line it sat above');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
