/**
 * A WITHDRAWN CORRECTION MUST NOT REACH ANY CLIENT RULE.
 *
 * ── WHAT HAPPENED ──────────────────────────────────────────────────────────
 * Seven unsigned amendment drafts on one project's daily narrative, two of them
 * FORKS — one parent, two children, sixty and twenty-six seconds apart. A
 * superintendent tapped Amend, nothing on the screen appeared to change, and he
 * tapped again. There was no way to take one back, so every one of them warns
 * on his compliance card forever.
 *
 * `POST /logbooks/{id}/withdraw` now sets `status: 'withdrawn'` on the child.
 * The document survives — its data, its reason, its author and its parent link
 * are untouched — but it is no longer a correction anybody is proposing.
 *
 * ── WHY THE CLIENT CHECKS AT ALL ───────────────────────────────────────────
 * `GET /logbooks/project/{id}` already excludes withdrawn children, and that
 * single clause fixes every one of the twelve editor pickers at once. These
 * three rules are hardened anyway, and neither reason is hypothetical:
 *
 *   THE CACHE.  subcontractor_orientation.jsx runs `collapseChains` over a
 *   CACHED roster when it is offline. That cache can be older than the
 *   withdrawal, and a CP with no signal would be told he has two competing
 *   corrections open on a record nobody is correcting.
 *
 *   THE BUNDLE. A phone in the field cannot take an OTA for weeks. This
 *   codebase's whole last incident turned on that fact.
 *
 * ── THREE RULES, THREE DIFFERENT HARMS ─────────────────────────────────────
 *   amendmentChain.chainHead      counts it as an open correction on the CP's
 *                                 orientation rows, and drags logTypeStatus
 *                                 down to "Draft" over a filed day
 *   logbookEditable.isOpenForEditing   opens it in the editor — he fills it in
 *                                 and is refused at the save (409)
 *   amendmentAdopt.isEditableChild     the worst: adoption DISCARDS his local
 *                                 copy of the filed parent, so it would delete
 *                                 his only offline record of a signed log to
 *                                 hand him a document the server will not take
 *
 * ── HOW THIS TEST WORKS ────────────────────────────────────────────────────
 * It does not grep. It loads the three REAL modules and executes their rules
 * against real document shapes. The loader is a few lines of string work rather
 * than @babel/core on purpose: everything asserted here is plain JavaScript, so
 * this file stays in the dependency-free majority of the suite and runs with no
 * node_modules at all.
 *
 * Run:  node src/utils/amendmentWithdrawn.test.cjs
 */
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const read = (f) => fs.readFileSync(path.join(HERE, f), 'utf8').split('\r\n').join('\n');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

/**
 * Load an ES module's plain-JS exports with no bundler.
 *
 * `import` lines are dropped — every rule under test is pure and touches none
 * of them — and the `export` keyword is stripped so the declarations land in
 * the function scope, where the trailing `return` picks them up by name.
 * If a rule ever starts depending on an import, it stops being loadable this
 * way and this file should be told rather than quietly passing.
 */
const load = (file, names) => {
  const src = read(file)
    .split('\n')
    .filter((l) => !/^\s*import\s/.test(l))
    .join('\n')
    .replace(/^export default .*;?$/gm, '')
    .replace(/^export /gm, '');
  // eslint-disable-next-line no-new-func
  return new Function(`${src}\nreturn { ${names.join(', ')} };`)();
};

const { chainHead, collapseChains, logTypeStatus } =
  load('amendmentChain.js', ['chainHead', 'collapseChains', 'logTypeStatus']);
const { isOpenForEditing, chooseEditableLog } =
  load('logbookEditable.js', ['isOpenForEditing', 'chooseEditableLog']);
const { isEditableChild, pickEditableChild } =
  load('amendmentAdopt.js', ['isEditableChild', 'pickEditableChild']);

// ── The documents, in the shapes the server actually returns ───────────────
const W = { worker_id: 'w-1', worker_name: 'Angel Lopez' };

const PARENT = {
  id: 'p1', data: W, is_locked: true, status: 'submitted',
  created_at: '2026-08-14T20:00:00Z',
};
// The Aug 14 fork: two children of ONE parent, 26 seconds apart.
const FORK_A = {
  id: 'c1', data: W, is_locked: false, status: 'draft', is_amendment: true,
  parent_logbook_id: 'p1', created_at: '2026-08-14T20:23:11Z',
};
const FORK_B = {
  id: 'c2', data: W, is_locked: false, status: 'draft', is_amendment: true,
  parent_logbook_id: 'p1', created_at: '2026-08-14T20:23:37Z',
};
const withdrawn = (o) => ({
  ...o,
  status: 'withdrawn',
  withdrawn_by: 'u-super',
  withdrawn_by_name: 'Michael Cespedes',
  withdrawn_at: '2026-09-02T14:00:00Z',
});

console.log('\n1. THE CONTROL — WITHOUT A WITHDRAWAL NOTHING CHANGES');
{
  const head = chainHead([PARENT, FORK_A, FORK_B]);
  ok(head.id === 'p1', 'the head is still the filed parent');
  ok(head._open_corrections.length === 2,
    'and BOTH forks are still reported open — the state this feature exists '
    + 'to give an exit from');
  ok(head._chain_length === 3, 'the chain is three documents long');
  ok(logTypeStatus([PARENT, FORK_A, FORK_B]) === 'submitted',
    'and the type pill ALREADY reads Done, because the worker’s current '
    + 'record is filed — `logTypeStatus` asks about heads, not about drafts, '
    + 'and was never the surface that counted corrections. Asserted so a '
    + 'later reading of the withdrawn rule cannot quietly turn it into '
    + '"any draft exists", which would tell a CP his signed day is unfinished');
}

console.log('\n2. WITHDRAWING ONE FORK LEAVES THE OTHER — UNTOUCHED AND OPEN');
{
  const head = chainHead([PARENT, withdrawn(FORK_A), FORK_B]);
  ok(head.id === 'p1', 'the record is still the filed parent');
  ok(head._open_corrections.length === 1,
    'exactly one correction is open now, not zero and not two');
  ok(head._open_corrections[0].id === 'c2',
    'and it is the OTHER fork — withdrawing one must never take its twin '
    + 'with it, or the CP loses the correction he still means to make');
  ok(head._chain_length === 2,
    'the withdrawn link leaves the chain count too: it corrected nothing, so '
    + '"corrected 2 times" would say the record changed shape when it did not');
}

console.log('\n3. WITHDRAWING BOTH CLEARS THE RECORD');
{
  const head = chainHead([PARENT, withdrawn(FORK_A), withdrawn(FORK_B)]);
  ok(head.id === 'p1', 'the filed parent stands, exactly as it was signed');
  ok(head._open_corrections.length === 0,
    'and nothing is outstanding — the seven drafts leave the card');
  ok(logTypeStatus([PARENT, withdrawn(FORK_A), withdrawn(FORK_B)]) === 'submitted',
    'and the pill is unmoved — it read Done before and reads Done after, '
    + 'which is what "nothing was destroyed" looks like from the list');
}

console.log('\n4. A WITHDRAWN LINK NEVER BECOMES THE HEAD');
{
  // A day whose original was never signed. Nothing is filed, so `chainHead`
  // falls back to the newest OPEN link — and a withdrawn one must not be it.
  const unsignedParent = {
    id: 'p2', data: W, is_locked: false, status: 'draft',
    created_at: '2026-08-14T19:00:00Z',
  };
  const head = chainHead([unsignedParent, withdrawn(FORK_B)]);
  ok(head.id === 'p2',
    'the unfiled original is the head, not the correction taken back');

  // And the degenerate case: a row must never vanish off a compliance screen.
  const onlyWithdrawn = chainHead([withdrawn(FORK_A)]);
  ok(onlyWithdrawn !== null,
    'a group that is entirely withdrawn still yields a row rather than '
    + 'disappearing — a dropped orientation is worse than an odd one');
  ok(onlyWithdrawn._open_corrections.length === 0,
    'and it reports nothing open');
  ok(collapseChains([withdrawn(FORK_A)]).length === 1,
    'collapseChains keeps it, for the same reason');
}

console.log('\n5. THE EDITOR DOES NOT OPEN ONE');
{
  ok(isOpenForEditing(FORK_A) === true,
    'the control: an ordinary unsigned amendment IS open for editing');
  ok(isOpenForEditing(withdrawn(FORK_A)) === false,
    'a withdrawn one is not — neither clause of the old rule said so, since '
    + 'its status is not "submitted" and nothing locked it');

  const { log, readOnly } = chooseEditableLog([PARENT, withdrawn(FORK_A)]);
  ok(log.id === 'p1' && readOnly === true,
    'so the editor loads the filed parent, read-only, with the Amend path — '
    + 'not a correction the server would refuse to save (409)');

  const both = chooseEditableLog([PARENT, withdrawn(FORK_A), FORK_B]);
  ok(both.log.id === 'c2' && both.readOnly === false,
    'and the surviving fork is still the one he lands in');
}

console.log('\n6. ADOPTION NEVER DISCARDS A FILED LOG FOR ONE');
{
  ok(isEditableChild(FORK_A) === true, 'the control: a live child is adoptable');
  ok(isEditableChild(withdrawn(FORK_A)) === false,
    'a withdrawn child is not');
  ok(isEditableChild(PARENT) === false, 'and a locked parent never was');
  ok(pickEditableChild([PARENT, withdrawn(FORK_A)]) === null,
    'so adoptAmendment finds nothing to adopt, and the CP’s local copy of '
    + 'his filed log — possibly the only offline copy — is left alone');
  ok((pickEditableChild([PARENT, withdrawn(FORK_A), FORK_B]) || {}).id === 'c2',
    'while a real open correction is still adopted');
}

console.log('\n7. THE BANNER OFFERS THE THIRD ANSWER');
{
  const BANNER = read('../components/AmendmentBanner.jsx');
  const STEPPER = read('../components/logbookStepper/LogbookStepper.jsx');
  const API = read('api.js');

  ok(/withdraw: async \(logbookId/.test(API),
    'api.js exposes logbooksAPI.withdraw');
  ok(/\/withdraw`/.test(API), 'and it posts to the withdraw route');

  ok(/logbooksAPI\.withdraw\(logId, /.test(BANNER),
    'the banner calls it with the id of the correction on screen AND the '
    + 'signature drawn for it');
  ok(/logId = null/.test(BANNER),
    'the control is opt-in: a caller that passes no id gets exactly the '
    + 'banner it always got');
  ok(/logId \?/.test(BANNER),
    'and the button renders only when there is something to act on — a '
    + 'control that cannot act must not be offered');
  ok(/clearPending\(draftKey\)/.test(BANNER) && /discardFinalizedDraft\(draftKey\)/.test(BANNER),
    'the local draft goes with it: parent and child share ONE draft key, so '
    + 'leaving it would let syncPendingDrafts PUT the withdrawn correction '
    + 'back at app startup with no user in the path');
  ok(BANNER.indexOf('logbooksAPI.withdraw') < BANNER.indexOf('clearPending(draftKey)'),
    'and only AFTER the server confirms — discardFinalizedDraft’s own rule');
  ok(/WITHDRAW_FILED_AMENDMENT/.test(BANNER),
    'a filed correction is refused, and the banner owns the wording');

  ok(/logId={logId}/.test(STEPPER) && /draftKey={draftKeyValue}/.test(STEPPER),
    'the stepper hands the banner what it needs');
  ok(/onWithdrawn={onAmended}/.test(STEPPER),
    'and reuses the reload callback the editors already pass for an amend');

  // EVERY NEW IMPORT RESOLVES TO A FILE THAT EXISTS.
  //
  // The banner gained four imports, and it renders on TWELVE logbook editors.
  // A path that does not resolve is a crash on first paint of all of them —
  // the class of defect the mount smoke exists for, and the one thing a parse
  // sweep cannot see. Checked on disk rather than by eye.
  const BANNER_DIR = path.join(HERE, '..', 'components');
  ['../utils/api', '../utils/logbookDrafts', './Toast',
    '../styles/semanticColors', '../styles/theme'].forEach((spec) => {
    const base = path.resolve(BANNER_DIR, spec);
    const hit = ['.js', '.jsx', '.ts', '.tsx', ''].some(
      (ext) => fs.existsSync(base + ext));
    ok(hit, `AmendmentBanner's import of '${spec}' resolves to a real file`);
  });
  ok(/export const useToast/.test(read('../components/Toast.js')),
    'and Toast really exports useToast — the named import the withdraw '
    + 'handler needs to report a refusal');
  ok(/export async function clearPending/.test(read('logbookDrafts.js'))
    && /export async function discardFinalizedDraft/.test(read('logbookDrafts.js')),
    'and logbookDrafts really exports both draft calls');
  ok(/toast\?\./.test(BANNER) && !/[^?]toast\.[a-z]/.test(BANNER),
    'every toast call is optional-chained: useToast returns NULL outside a '
    + 'provider by design, and a missing toast must not turn a successful '
    + 'withdrawal into a crash on the screen it just fixed');
}

console.log('\n8. IT IS AN ATTESTED ACT, SO THE PAD COMES FIRST');
{
  const BANNER = read('../components/AmendmentBanner.jsx');
  const API = read('api.js');
  const CHAIN = read('amendmentChain.js');
  const SERVER = read('../../../backend/server.py');

  // ── THE SENTENCE ABOVE THE PAD IS THE SAME SENTENCE THE SERVER STORES ──
  //
  // The server writes WITHDRAWAL_ATTESTATION_STATEMENT onto the document
  // beside the ink, because a signature with no recorded sentence above it
  // attests to nothing nameable. If the client shows a DIFFERENT sentence,
  // the record says a man was told something he was never told — which is
  // worse than storing no sentence at all.
  const clientStmt = (CHAIN.match(
    /export const WITHDRAWAL_ATTESTATION_STATEMENT\s*=\s*([\s\S]*?);\n/) || [])[1];
  ok(!!clientStmt, 'amendmentChain exports WITHDRAWAL_ATTESTATION_STATEMENT');
  const serverStmt = (SERVER.match(
    /WITHDRAWAL_ATTESTATION_STATEMENT = \(\n([\s\S]*?)\n\)\n/) || [])[1];
  ok(!!serverStmt, 'and server.py defines one to compare it against');
  const words = (s) => (s || '').replace(/["'\s+()]+/g, ' ').trim();
  ok(words(clientStmt) === words(serverStmt),
    'and the two are the SAME sentence, word for word');

  // ── THE PAD, AND THE REFUSAL TO SEND WITHOUT INK ──
  ok(/SignaturePad/.test(BANNER),
    'the banner presents the EXISTING signature pad — a withdrawal is signed '
    + 'for on the same control every other attested act uses');
  // THE CONFIRM BUTTON'S OWN GATE, not merely the name appearing somewhere in
  // the file. A mutation control that changed the button's `disabled` to
  // `!sig` left `hasSignatureInk` in doWithdraw, so an assertion that only
  // grepped the name stayed green while the button itself had stopped asking.
  ok(/disabled=\{busy \|\| !hasSignatureInk\(sig\)\}/.test(BANNER),
    'the CONFIRM BUTTON is gated on hasSignatureInk, not on presence: '
    + 'cp_signature {} satisfied every presence gate in this app while the '
    + 'documents it signed printed UNAFFIRMED');
  ok(/if \(!logId \|\| busy \|\| !hasSignatureInk\(sig\)\) return;/.test(BANNER),
    'and the handler asks again before it reaches the wire, so a refusal '
    + 'never arrives as a toast that reads like a fault');
  ok(/WITHDRAW_SIGNATURE_REQUIRED/.test(BANNER),
    'and it owns the wording for the server’s refusal, so a client that '
    + 'somehow sends none still teaches rather than saying "failed"');

  // A control that cannot act must not be offered — the same rule the
  // withdraw button already follows for logId.
  ok(BANNER.indexOf('SignaturePad') > 0
    && /signing \?|signing &&/.test(BANNER),
    'the pad is revealed by the withdraw button rather than sitting open on '
    + 'twelve editors under a log nobody is withdrawing');

  ok(/withdraw: async \(logbookId, signature/.test(API),
    'api.js takes the signature as a required-by-position argument, so a '
    + 'caller that forgets it cannot silently send a reason in its place');
  // THE BODY, NOT THE ARGUMENT LIST. `signature` appears in the function's
  // own signature, so a slice of the whole function matches even when the
  // POST omits it — which a mutation control confirmed by dropping it from
  // the body and watching this assertion stay green.
  ok(/\/withdraw`,\s*\{[^}]*\bsignature\b[^}]*\}/.test(API),
    'and puts it in the POST BODY, beside the optional reason');

  // EVERY NEW IMPORT RESOLVES. Same rule as section 7, same reason: the
  // banner renders on TWELVE editors and a bad path is a crash on first paint.
  const BANNER_DIR = path.join(HERE, '..', 'components');
  ['./SignaturePad', '../utils/signatureAffirmed', '../utils/amendmentChain']
    .forEach((spec) => {
      const base = path.resolve(BANNER_DIR, spec);
      const hit = ['.js', '.jsx', '.ts', '.tsx', ''].some(
        (ext) => fs.existsSync(base + ext));
      ok(hit, `AmendmentBanner's import of '${spec}' resolves to a real file`);
    });
  ok(/export default SignaturePad/.test(read('../components/SignaturePad.js')),
    'and SignaturePad really is a default export');
  ok(/export function hasSignatureInk/.test(read('signatureAffirmed.js')),
    'and signatureAffirmed really exports hasSignatureInk');
}

console.log(failures ? `\n${failures} FAILURE(S)\n` : '\nAll assertions passed.\n');
process.exit(failures ? 1 : 0);
