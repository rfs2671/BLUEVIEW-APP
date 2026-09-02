/**
 * "LOG FILED AND LOCKED" IS A CLAIM, AND IT HAS TO BE TRUE.
 *
 * A construction superintendent filled the BC 3301.13.13 log on production,
 * submitted it, saw no error, and no document exists on any project.
 *
 * THE SHAPE OF THE SILENCE. handleSubmit did:
 *
 *     const savedId = saved?.id || saved?._id || existingLogId;
 *     if (savedId) { ...recordSignatureEvent... }
 *     if (savedId) await logbooksAPI.finalize(savedId);
 *     setLocked(true);
 *     toast.success(t('filed'));
 *     router.push('/logbooks');
 *
 * The two things that DEPEND on a record were guarded. The three things that
 * REPORT one were not. So a create that resolved without an id skipped the
 * ledger event and skipped the seal, and then told him "Log filed and locked"
 * — copy that asserts the seal by name — and navigated away from the screen
 * holding the only copy of what he typed.
 *
 * AND THE SERVER HAS THAT PATH. create_logbook re-reads the row it inserted and
 * returns serialize_id(of that read); a read that does not see its own write
 * makes that None, which FastAPI renders as HTTP 200 with the body `null`.
 * Reproduced in backend/tests/test_superintendent_log_files.py, which fixes the
 * server half. This file fixes the half that must hold anyway: ABSENCE OF AN
 * EXCEPTION IS NOT PROOF OF A WRITE.
 *
 * WHY IT MATTERS MORE HERE THAN ANYWHERE ELSE. This is the one editor that
 * seals in the same breath it signs. A visit log is excluded from
 * sweep_stale_end_of_day_logs by design, so if this screen does not finalize,
 * NOTHING EVER WILL — the document sits `submitted, is_locked: false`
 * indefinitely while every screen shows it as signed.
 *
 * ── WHAT IS ASSERTED FROM SOURCE, AND WHY ───────────────────────────────────
 *
 * The propositions here are about ORDER inside one async handler — that no
 * success is reported before the id is checked. That is a property of the
 * screen, and the screen is a React component this suite cannot mount (plain
 * node, no jest, no react-native preset; see esmHarness.cjs). So the ordering
 * assertions read the shipped source with its comments stripped, the same
 * technique siteSuperintendentSign.test.cjs uses and for the same reason: this
 * file's subject explains itself at length in prose, and a bare search would
 * match the explanation rather than the code.
 *
 * The LABEL half is executed against the real module, because it can be.
 *
 * Run:  node src/utils/csFilingGuard.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const SCREEN = read('app', 'logbooks', 'site_superintendent_log.jsx');

/** Comments stripped. See the note above about why. */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const SRC = CODE(SCREEN);

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

/**
 * The body of handleSubmit alone.
 *
 * SLICED, NOT SEARCHED WHOLE. `router.push('/logbooks')` also appears on the
 * stepper's onExit, and a whole-file search for it would be satisfied by the
 * Exit button — an assertion about the submit path passing because of a
 * different button is the kind of false green this file exists to prevent.
 */
const HANDLER = (() => {
  const start = SRC.indexOf('const handleSubmit');
  if (start < 0) return '';
  const after = SRC.indexOf('const Field =', start);
  return SRC.slice(start, after > 0 ? after : SRC.length);
})();

console.log('\n0. THE SLICE IS SANE');
{
  ok(HANDLER.length > 0, 'handleSubmit was found in the screen');
  ok(HANDLER.includes('toast.success'),
    'the slice contains the success report (otherwise every ordering test below is vacuous)');
  ok(HANDLER.includes('logbooksAPI.create') || HANDLER.includes('logbooksAPI.update'),
    'and the write it is supposed to be reporting on');
}

console.log('\n1. NO ID, NO FILING CLAIM');
{
  const idAt = HANDLER.indexOf('const savedId');
  const guardAt = HANDLER.search(/if \(!savedId\)/);

  ok(idAt >= 0, 'the handler resolves an id from the response');
  ok(guardAt >= 0,
    'and REFUSES when there is none — `if (!savedId)`');
  ok(guardAt > idAt,
    'the refusal comes after the id is resolved');

  // The refusal has to STOP the handler. A console.error or a toast that falls
  // through to the success below would be the same defect with logging on top.
  const refusal = HANDLER.slice(guardAt, guardAt + 220);
  ok(/if \(!savedId\)[\s\S]{0,80}?(throw|return)/.test(refusal),
    'the refusal throws or returns — it does not fall through to the success');

  // ── WHAT "BEFORE THE REFUSAL" MEANS, AND WHY IT WAS RESTATED ────────────
  //
  // THIS SECTION USED TO TAKE THE FIRST OCCURRENCE of each needle, and that
  // measurement broke when fix/superintendent-local-first landed. That branch
  // added `reportHeldOnDevice` — a helper whose body holds setLocked(true), a
  // toast.success and the same router.push, and which MUST be DEFINED above
  // the try, because the outer catch calls it. Its definition sits above the
  // refusal, so the first occurrence of all three moved above `guardAt` and
  // this section went red on code that is correct. A DEFINITION IS NOT AN
  // EXECUTION, and an ordering proxy that cannot tell them apart will fail
  // the next helper too.
  //
  // AND THE TWO SUCCESSES ARE NOT ONE CLAIM. `t('filed')` is "Log filed and
  // locked" — an assertion about a record ON THE SERVER, and precisely the
  // sentence a superintendent was shown over nothing. `t('savedLocallyTitle')`
  // is "Signed and frozen on this device", which is TRUE with no server id and
  // is the entire purpose of local-first. So the proposition is not "nothing
  // succeeds without an id" — an offline filing must — it is that the FILED
  // CLAIM, and the lock and the navigation that accompany it, are unreachable
  // without one. That is what the lost log actually needed.
  const FILED = "toast.success(t('filed'))";
  const filedAt = HANDLER.indexOf(FILED);
  ok(filedAt >= 0, `the server-filed claim is still in the handler (${FILED})`);
  // `guardAt >= 0` IS LOAD-BEARING. String.indexOf answers -1 for a refusal
  // that does not exist, and every position is greater than -1 — so without
  // it this reads "comes after the refusal" and passes on the very code that
  // has no refusal. That is the defect under test, passing its own test.
  ok(guardAt >= 0 && filedAt > guardAt,
    'the filed claim is unreachable without an id — it comes after the refusal');

  // The lock and the navigation that travel WITH that claim, taken from the
  // SUCCESS BLOCK (refusal → catch) rather than from the whole handler.
  const catchAt = HANDLER.search(/\} catch \(pushErr\)/);
  ok(catchAt > guardAt, 'the push is still wrapped in a catch below the refusal');
  const SUCCESS = HANDLER.slice(guardAt, catchAt);
  for (const [what, needle] of [
    ['the lock', 'setLocked(true)'],
    ['the navigation away', "router.push('/logbooks')"],
  ]) {
    ok(SUCCESS.includes(needle),
      `${what} sits on the filed path, after the refusal (${needle})`);
  }

  // AND NOTHING ABOVE THE REFUSAL MAY CLAIM A FILING. This is the half that
  // actually guards the defect now: code reachable without a server id may
  // report the ON-DEVICE freeze, and may not report the log as filed.
  const BEFORE = HANDLER.slice(0, guardAt);
  ok(!BEFORE.includes("t('filed')"),
    'nothing above the refusal reaches for the "filed and locked" copy');
  ok(!/toast\.success/.test(BEFORE) || /savedLocallyTitle/.test(BEFORE),
    'the only success reportable without a server id is the on-device one');
}

console.log('\n2. THE SEAL IS NOT OPTIONAL');
{
  // 3301.13.13 requires the log complete before departure, and this screen's
  // finalize is the only thing that ever freezes a visit log.
  ok(/logbooksAPI\.finalize\(/.test(HANDLER),
    'the handler still finalizes');
  ok(!/if \(savedId\) await logbooksAPI\.finalize/.test(HANDLER),
    'the finalize is NOT conditional on the id — the refusal above already '
    + 'guarantees one, and a conditional seal beside an unconditional '
    + '"filed and locked" is exactly the defect');
  ok(!/if \(savedId\) \{/.test(HANDLER),
    'and neither is the signature-ledger event: nothing in this handler is '
    + 'skipped for a missing id, because a missing id no longer gets this far');

  // AGAINST THE FILED CLAIM SPECIFICALLY, not the first toast.success in the
  // handler — reportHeldOnDevice's on-device success is defined above the try
  // and is not the claim this seal has to precede. Same reason as section 1.
  const finalizeAt = HANDLER.indexOf('logbooksAPI.finalize(');
  const toastAt = HANDLER.indexOf("toast.success(t('filed'))");
  ok(finalizeAt >= 0 && toastAt >= 0 && finalizeAt < toastAt,
    'and it is awaited BEFORE the screen claims the log is filed and locked');
}

console.log('\n3. A REFUSAL THE SUPERINTENDENT CAN ACT ON');
{
  const catchAt = HANDLER.indexOf('} catch');
  const tail = catchAt >= 0 ? HANDLER.slice(catchAt) : '';
  ok(catchAt >= 0, 'the handler still reports failures');

  // SUBMIT_UNATTESTED_ITEMS carries `items` precisely so the client can point
  // at the unanswered items. Printing the machine code at a man on a jobsite
  // wastes the only part of the refusal he could have used.
  ok(/detail\??\.items/.test(tail),
    'the failure report reads detail.items, not just detail.code');
  ok(/csItemLabels/.test(tail),
    'and renders them as the declared item labels, not raw keys');
  ok(/unansweredHint/.test(tail),
    'reusing the same wording as the hint on the disabled button, so the '
    + 'refusal and the hint do not say different things about one condition');
  // FROM THE MODEL, not a local copy. superintendentLogModel.js declares the
  // items; a second mapping beside it is how the OSHA register's row rule came
  // to print different things in two renderers.
  ok(/import \{[\s\S]*?csItemLabels[\s\S]*?\} from '[^']*superintendentLogModel'/.test(SRC),
    'csItemLabels is imported from the model that declares the items');
}

console.log('\n4. THE LABELS, EXECUTED');
{
  const M = loadEsm('src/utils/superintendentLogModel.js');

  const present = typeof M.csItemLabels === 'function';
  ok(present, 'superintendentLogModel exports csItemLabels');
  // Not a bail-out: the assertions below cannot RUN without it, and a run that
  // throws here hides the ones after it. Reported as failures instead, so one
  // control run shows the whole gap.
  if (!present) {
    for (const m of [
      'a key becomes the item label a superintendent reads',
      'several keys become several labels, in order',
      'every attestable key the server can return has a real label',
      'an unknown key falls back to the key rather than throwing inside catch',
      'and a missing list is an empty one, not a crash',
    ]) ok(false, m);
  } else {

  ok(JSON.stringify(M.csItemLabels(['orders_given']))
     === JSON.stringify(['Orders and notices given']),
    'a key becomes the item label a superintendent reads');

  ok(M.csItemLabels(['unsafe_conditions', 'incidents']).length === 2,
    'several keys become several labels, in order');

  // EVERY key the server can name. SUBMIT_UNATTESTED_ITEMS is built from the
  // attestable items, so any one of them can arrive and none may render as a
  // bare identifier.
  const attestable = M.CS_LOG_ITEMS.filter((i) => i.attestable).map((i) => i.key);
  ok(attestable.length > 0, 'there are attestable items to be refused for');
  ok(attestable.every((k) => {
    const [label] = M.csItemLabels([k]);
    return label && label !== k;
  }), 'every attestable key the server can return has a real label');

  // A key this build does not know about must not blow up the error path. The
  // error path is the last thing standing between him and a lost record.
  ok(JSON.stringify(M.csItemLabels(['a_key_from_a_newer_server']))
     === JSON.stringify(['a_key_from_a_newer_server']),
    'an unknown key falls back to the key rather than throwing inside catch');
  ok(JSON.stringify(M.csItemLabels(null)) === JSON.stringify([]),
    'and a missing list is an empty one, not a crash');
  }
}

console.log(failures === 0 ? '\nPASS\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
