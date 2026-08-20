/**
 * THE LOCAL SAVE, AND THE THREE PLACES IT WAS INVISIBLE.
 *
 * `writeDraft` returns false and never throws. For most of this app's life the
 * result was discarded at every one of its 46 call sites, so a device that had
 * stopped storing drafts — a full disk, a corrupt store — behaved exactly like
 * one that was working, right up until the moment it mattered.
 *
 * Three failures, one shape: an unconditional promise printed next to a
 * conditional fact.
 *
 *   SUBMIT   the deferred branches queued the key and announced the log as
 *            filed. The drain reads the DRAFT, not that scope, so it then
 *            filed a stale autosave as the signed record, or found nothing and
 *            cleared the key as `no-draft`.
 *   AUTOSAVE "Saved automatically as you go" is a constant string. It said
 *            that whether or not anything had been saved.
 *   DURABILITY the submit failure was a toast. He signs and walks — to the next
 *            floor, to his truck — and a message that removed itself four
 *            seconds later is the same as no message.
 *
 * The three rulings this file pins:
 *
 *   Q1  NO TOAST ON EVERY SAVE. A CP saving every few seconds ignores a message
 *       that fires constantly, and an ignored warning is worse than silence. It
 *       surfaces ONCE, at the submit gate, beside the reasons already there —
 *       and it WARNS rather than GATES, because a broken local store does not
 *       stop the log reaching the server and must not stop him filing it.
 *   Q2  A BANNER, NOT A TOAST, for the submit-time failure.
 *   Q3  BOTH FAILURE MODES. A false return and a thrown exception both mean the
 *       write did not happen. A caller handling one and not the other has fixed
 *       half of it, and the half it misses is the one nobody tested.
 *
 * ANCHORED SLICES, NON-EMPTY FIRST. Every marker-derived subject below is
 * asserted non-empty before its contents are asserted — an earlier version of
 * the Q3 check used an unanchored lazy `[\s\S]*?` across the whole file, and it
 * matched a DIFFERENT catch block hundreds of lines away. It passed while the
 * branch it claimed to guard was mutated out. See assertionsCanFail.test.cjs.
 *
 * Run:  node src/utils/localSaveVisibility.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const LOGBOOKS = path.join(FRONTEND, 'app', 'logbooks');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Comments are stripped everywhere below. Every screen now carries prose
// explaining these branches, and a bare grep for `localSaved` would pass on the
// explanation while the code went back to dropping the value.
const strip = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
const read = (p) => strip(fs.readFileSync(p, 'utf8'));
const screen = (n) => read(path.join(LOGBOOKS, `${n}.jsx`));
const count = (s, sub) => s.split(sub).length - 1;

// The ten editors driven by LogbookStepper.
const STEPPER = [
  'crane_operations', 'concrete_operations', 'hot_work', 'osha_log',
  'fall_protection', 'ssc_daily_safety_log', 'toolbox_talk',
  'excavation_monitoring', 'scaffold_maintenance', 'daily_jobsite',
];
// Plus the two that own their own footer and lock bar.
const ALL_LOGBOOKS = STEPPER.concat(['preshift_signin', 'subcontractor_orientation']);

console.log('\n── Q3: the submit save reports BOTH failure modes ──');

for (const name of ALL_LOGBOOKS) {
  const src = screen(name);
  ok(src.length > 0, `${name}: source read and non-empty`);

  // ANCHOR. One slice per submit save, from the assignment to the end of the
  // statement that consumes it. `subcontractor_orientation` has two (sign an
  // existing row; create a signed one), so every occurrence is checked rather
  // than the first.
  const starts = [];
  let i = src.indexOf('localSaved = await writeDraft(');
  while (i !== -1) { starts.push(i); i = src.indexOf('localSaved = await writeDraft(', i + 1); }
  ok(starts.length > 0, `${name}: found at least one captured submit save`);

  starts.forEach((start, n) => {
    // The slice ends at the close of the try/catch that wraps this save. Bounded
    // by the NEXT save if there is one, so two saves can never share a catch.
    const hardEnd = starts[n + 1] !== undefined ? starts[n + 1] : src.length;
    const closeAt = src.indexOf('localSaved = false;', start);
    const slice = (closeAt !== -1 && closeAt < hardEnd)
      ? src.slice(start, closeAt + 'localSaved = false;'.length)
      : '';
    ok(slice.length > 0,
      `${name}[${n}]: the save's own catch is inside its own slice`);
    ok(/^localSaved = await writeDraft\(/.test(slice),
      `${name}[${n}]: the slice really starts at the save`);
    // Both modes, in the SAME block: the boolean is captured, and a throw lands
    // on the same answer.
    ok(/\} catch \(_e\) \{/.test(slice),
      `${name}[${n}]: the submit save is wrapped so a THROW cannot escape`);
    ok(/\} catch \(_e\) \{[^}]*localSaved = false;/.test(slice),
      `${name}[${n}]: and that catch sets the SAME false a refused write returns`);
  });
}

console.log('\n── Q3: the autosave reports both modes too ──');

for (const name of STEPPER) {
  const src = screen(name);
  // Two shapes across these ten: a fire-and-forget promise chain (the debounced
  // autosave) and an awaited call (the step-change flush; daily_jobsite uses the
  // awaited shape for both). Asserted by PAIRING rather than by presence: an
  // editor with two write sites and one handler passes a presence test while
  // half its writes are silent again, which is the mutation this is here for.
  const nThen = count(src, '.then((_ok) => setAutosaveFailed(!_ok))');
  const nThenCatch = count(src, '.catch(() => setAutosaveFailed(true));');
  const nAwait = count(src, 'const _ok = await writeDraft(');
  const nAwaitSet = count(src, 'setAutosaveFailed(!_ok);');
  const nAwaitCatch = count(src, '} catch (_e) { setAutosaveFailed(true); }');

  ok(nThen + nAwait >= 2,
    `${name}: both draft-write paths report (debounced autosave + step flush) — got ${nThen + nAwait}`);
  ok(nThen === nThenCatch,
    `${name}: every promise-chain autosave catches a throw as well (${nThen} vs ${nThenCatch})`);
  ok(nAwait === nAwaitSet,
    `${name}: every awaited draft write reads its boolean (${nAwait} vs ${nAwaitSet})`);
  ok(nAwait === nAwaitCatch,
    `${name}: every awaited draft write catches a throw (${nAwait} vs ${nAwaitCatch})`);
  // THE EMPTY SWALLOW IS GONE FROM THE DRAFT WRITES, and from those ONLY.
  // Two other calls on these screens carry a deliberate `.catch(() => {})`:
  // `autoSave` (a CP-PROFILE failure must never report a failure on a log that
  // was already saved and frozen) and `saveScaffoldInfo`. Banning the pattern
  // outright flagged both, and a test that flags correct code gets edited until
  // it stops complaining — which is how it would have lost the writeDraft case
  // too. So the subject is the writeDraft STATEMENT: each call sliced to the
  // semicolon that ends it, which is exactly where its own handlers live.
  const stmts = src.split('writeDraft(').slice(1)
    .map((chunk) => chunk.slice(0, chunk.indexOf(';') + 1))
    .filter((st) => st.length > 0);
  ok(stmts.length > 0, `${name}: found writeDraft statements to check`);
  const swallowed = stmts.filter((st) => st.includes('.catch(() => {})'));
  ok(swallowed.length === 0,
    `${name}: no writeDraft swallows its own failure${swallowed.length ? ` — ${JSON.stringify(swallowed)}` : ''}`);
}

{
  const src = screen('preshift_signin');
  // SHAPE-INSENSITIVE. This pinned the single-expression arrow
  // `.then((_ok) => setAutosaveFailed(!_ok))`, and adding the row-snapshot
  // call turned it into a block body — which failed the test without
  // changing what it checks. The claim is that the autosave READS its
  // boolean, so that is what is asserted.
  ok(/\.then\(\(_ok\) =>[\s\S]{0,400}?setAutosaveFailed\(!_ok\)/.test(src),
    'preshift_signin: its own autosave reads the boolean');
  ok(/\.catch\(\(\) => setAutosaveFailed\(true\)\)/.test(src),
    'preshift_signin: and catches a throw — this is the sheet signed at the gate');
}

console.log('\n── Q1: the submit gate warns, and does not gate ──');

const stepper = read(path.join(FRONTEND, 'src', 'components', 'logbookStepper', 'LogbookStepper.jsx'));
ok(stepper.length > 0, 'LogbookStepper source read and non-empty');

// The footer is the anchored subject: submitWarning has to render THERE, next
// to the reasons a submit is blocked, not anywhere on the page.
const footerStart = stepper.indexOf('{!locked && (');
const footerEnd = stepper.indexOf('</SafeAreaView>', footerStart);
const footer = (footerStart !== -1 && footerEnd > footerStart)
  ? stepper.slice(footerStart, footerEnd) : '';
ok(footer.length > 0, 'located the stepper footer');
ok(/\{step === total && !!submitWarning && \(/.test(footer),
  'the warning renders on the submit step');
ok(/<Text style=\{s\.submitWarning\}>\{submitWarning\}<\/Text>/.test(footer),
  'and it renders the text, in its own louder style');
ok(footer.indexOf('submitWarning') < footer.indexOf('submitDisabled && !!submitHint'),
  'ABOVE the disabled-reason, so the two coexist without displacing it');

// THE WARN/GATE LINE. This is the ruling, and it is one character away from
// being broken: adding `|| !!submitWarning` to the disabled expression turns a
// device storage fault into an inability to file the log at all.
const disabledLine = (footer.match(/disabled=\{submitting[^}]*\}/) || [''])[0];
ok(disabledLine.length > 0, 'located the submit button disabled expression');
ok(!/submitWarning/.test(disabledLine),
  'a WARNING IS NOT A GATE — submitWarning must never disable Submit');
ok(!/submitWarning/.test((stepper.match(/submitDisabled = [^\n]*/) || [''])[0]),
  'and it does not sneak into submitDisabled either');

for (const name of STEPPER) {
  const src = screen(name);
  ok(/submitWarning=\{autosaveFailed \? tFinalize\('autosaveFailedWarning'\) : ''\}/.test(src),
    `${name}: hands the failed autosave to the submit gate`);
  ok(/const \[autosaveFailed, setAutosaveFailed\] = useState\(false\);/.test(src),
    `${name}: and owns the flag it reports`);
}
{
  const src = screen('preshift_signin');
  ok(/\{autosaveFailed && \(/.test(src)
    && /tFinalize\('autosaveFailedWarning'\)/.test(src),
    'preshift_signin: warns at its own submit footer');
  const dis = (src.match(/disabled=\{!isAffirmedSignature\(cpSignature\)[^}]*\}/) || [''])[0];
  ok(dis.length > 0, 'located preshift_signin submit disabled expression');
  ok(!/autosaveFailed/.test(dis),
    'preshift_signin: and it warns rather than gates, same rule');
}

console.log('\n── Q2: the failure is a BANNER, not only a toast ──');

for (const name of ALL_LOGBOOKS) {
  const src = screen(name);
  ok(/recordFinalizeError\(\s*[^;]*'LOCAL_SAVE_FAILED',[^;]*'local'\)/.test(src),
    `${name}: raises the durable banner when nothing was saved locally`);
}

// Every no-local-copy EXIT raises it — not just one of them. The 5xx branch and
// the offline branch are different exits and both leave the CP with nothing.
for (const name of STEPPER.filter((n) => n !== 'daily_jobsite')) {
  const src = screen(name);
  ok(count(src, "'LOCAL_SAVE_FAILED'") >= 2,
    `${name}: BOTH no-local-copy exits raise it (5xx and offline), not just one`);
}

const bar = read(path.join(FRONTEND, 'src', 'components', 'LogbookLockBar.jsx'));
ok(bar.length > 0, 'LogbookLockBar source read and non-empty');
ok(/const localSaveFailed = refusedSource === 'local';/.test(bar),
  "the bar recognises the 'local' source as its own case");

const bannerStart = bar.indexOf('const notLockedBanner =');
const bannerEnd = bar.indexOf('const doAmend', bannerStart);
const banner = (bannerStart !== -1 && bannerEnd > bannerStart)
  ? bar.slice(bannerStart, bannerEnd) : '';
ok(banner.length > 0, 'located the banner JSX');
ok(/localSaveFailed[\s\S]{0,80}notSavedLocalTitle/.test(banner),
  'it gets its OWN title');
ok(/localSaveFailed[\s\S]{0,120}notSavedLocalHint/.test(banner),
  'and its OWN hint');
// THE POINT OF A SEPARATE HINT. notLockedHint promises a queued retry;
// notPushedHint promises the work is still on the device. Both are false when
// the local write is what failed, and sending him away from the only copy on
// the strength of either is the failure this whole file exists to stop.
ok(banner.indexOf('notSavedLocalHint') < banner.indexOf('notPushedHint'),
  'the local case is decided BEFORE the two hints that would be false for it');

const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
const fzStart = en.indexOf('  finalize: {');
const fzEnd = en.indexOf('\n  },', fzStart);
const finalizeNs = (fzStart !== -1 && fzEnd > fzStart) ? en.slice(fzStart, fzEnd) : '';
ok(finalizeNs.length > 0, 'located the finalize i18n namespace');
for (const key of ['code_LOCAL_SAVE_FAILED', 'notSavedLocalTitle',
  'notSavedLocalHint', 'autosaveFailedWarning']) {
  ok(new RegExp(`\\n    ${key}: '`).test(finalizeNs),
    `finalize.${key} exists — an unmapped code renders the generic fallback instead`);
}
// The warning must not promise a retry either: nothing is queued.
const warnCopy = (finalizeNs.match(/autosaveFailedWarning: '([^']*)'/) || [, ''])[1];
ok(warnCopy.length > 0, 'the submit-gate warning has copy');
ok(!/will sync|queued|retry/i.test(warnCopy),
  'and it promises no sync, no queue and no retry — none of the three exist here');

console.log('\n── Q1: the phone wins ──');

// THE RULING: the CP was on that screen and typed those words; nothing else has
// a claim to them. This is already how every one of these screens behaves, and
// the comments say so out loud ("LOCAL-FIRST", "CACHE-FIRST", "the local draft
// is the NEWER, unsynced copy — it wins"). So this section does not change
// behaviour; it PINS it. A server-first load is a two-line edit that would look
// like a tidy-up and would silently overwrite a CP's unsynced work.
//
// Asserted on ORDER, not on presence: every one of these screens reads the
// draft AND calls the server somewhere, so "does it read the draft" passes even
// on a server-wins screen. What matters is which one reaches the form.
// `.getByProject(` rather than `logbooksAPI.getByProject(`: three of these
// screens break the call across lines, and a marker that misses the call
// entirely would have made the ORDER assertion below vacuous rather than
// failing loudly. It failed loudly, which is why this comment exists.
const SERVER_CALL = Object.fromEntries(
  ALL_LOGBOOKS.filter((n) => n !== 'subcontractor_orientation')
    .map((n) => [n, '.getByProject(']),
);
for (const [name, serverCall] of Object.entries(SERVER_CALL)) {
  const src = screen(name);
  const draftAt = src.indexOf('readDraft(');
  const serverAt = src.indexOf(serverCall);
  ok(draftAt !== -1, `${name}: reads the on-device draft`);
  ok(serverAt !== -1, `${name}: also asks the server (so ORDER is the question)`);
  ok(draftAt < serverAt,
    `${name}: the DRAFT is read before the server — the phone wins`);

  // And the draft branch RETURNS, or the server read below would overwrite the
  // form it just hydrated. This is the actual mechanism of "wins".
  const branch = src.slice(draftAt, serverAt);
  ok(branch.length > 0, `${name}: located the draft branch`);
  ok(/\breturn\b/.test(branch),
    `${name}: and the draft branch returns rather than falling into the server read`);
}

// The two daily-log screens keep their server read (they need the list and the
// id binding) and guard the FORM instead. Same ruling, different mechanism, so
// it is asserted differently rather than forced into the shape above.
{
  const dl = strip(fs.readFileSync(path.join(FRONTEND, 'app', 'daily-log.jsx'), 'utf8'));
  ok(dl.length > 0, 'daily-log.jsx read and non-empty');
  ok(/if \(!draft\) populateFormFromLog\(todayLog\);/.test(dl),
    'daily-log.jsx: the server hydrates the form ONLY when there is no local draft');
  const sdl = strip(fs.readFileSync(
    path.join(FRONTEND, 'app', 'site', 'daily-logs.jsx'), 'utf8'));
  ok(sdl.length > 0, 'site/daily-logs.jsx read and non-empty');
  ok(/hasDraftData/.test(sdl),
    'site/daily-logs.jsx: an empty server response does not wipe a draft-backed form');
}

console.log('\n── Q2: both reasons, one banner, two wordings ──');

// FIRE ON BOTH. He is signing a legal record, and a phone holding data the
// server does not is exactly what he needs to know before he attests to it —
// whether the local write failed OR the push did. Two reasons, two sentences.
// COUNTS, NOT PRESENCE, and the mutation run is why. Each of these screens has
// MORE THAN ONE exit where the push did not land, and a presence test passes
// while any one of them goes silent again — two mutations survived exactly
// that way. The expected number per screen is written down, so adding an exit
// without wiring it fails here rather than shipping quiet.
//
//   10 stepper editors : 2 — the 5xx branch and the offline fall-through
//   preshift_signin    : 1 — one push catch, it does not split 4xx/5xx
//   subcontractor_orient: 2 — sign-an-existing-row, and create-signed
const UNSYNCED_EXITS = Object.assign(
  Object.fromEntries(STEPPER.map((n) => [n, 2])),
  { preshift_signin: 1, subcontractor_orientation: 2 },
);
for (const name of ALL_LOGBOOKS) {
  const src = screen(name);
  const n = count(src, "'NOT_ON_SERVER'");
  ok(n === UNSYNCED_EXITS[name],
    `${name}: EVERY exit where the push did not land raises the banner `
    + `(expected ${UNSYNCED_EXITS[name]}, got ${n})`);
  ok(/recordFinalizeError\(\s*[^;]*'NOT_ON_SERVER',[^;]*'unsynced'\)/.test(src),
    `${name}: under the unsynced source`);
  // The two reasons must never be the same record, or the bar cannot tell him
  // WHICH problem he has — which is the point of surfacing it at all.
  ok(count(src, "'LOCAL_SAVE_FAILED'") > 0,
    `${name}: and the local-save failure keeps its own distinct code`);
}

// A BANNER THAT CANNOT COME DOWN trains him to read past every banner. The
// offline case is recorded against the DRAFT KEY (an offline create has no
// server id), so clearing by id alone would leave it up permanently.
for (const name of ALL_LOGBOOKS) {
  const src = screen(name);
  ok(/clearFinalizeError\((_key|key)\)/.test(src),
    `${name}: clears the banner by DRAFT KEY on a successful push, not only by id`);
}
{
  const ds = strip(fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'draftSync.js'), 'utf8'));
  ok(ds.length > 0, 'draftSync.js read and non-empty');
  ok(/async function clearUnsyncedBanner\(key, logId\) \{[\s\S]{0,200}?clearFinalizeError\(key\)/.test(ds),
    'the drain clears by draft key as well — it is what finally syncs an offline log');
  ok(count(ds, 'await clearUnsyncedBanner(') === 2,
    'and it does so on BOTH of its success paths (update and create)');
}

// THE WORDINGS ARE DIFFERENT, and the bar decides between them before it
// reaches the two hints that would be false.
ok(/const notOnServer = refusedSource === 'unsynced';/.test(bar),
  "the bar recognises 'unsynced' as its own case");
ok(/notOnServer[\s\S]{0,80}notOnServerTitle/.test(banner),
  'the unsynced case gets its OWN title');
ok(/notOnServer[\s\S]{0,140}notOnServerHint/.test(banner),
  'and its OWN hint');
ok(banner.indexOf('notSavedLocalHint') < banner.indexOf('notOnServerHint'),
  'the local-save failure is decided FIRST — it is the worse of the two');
ok(banner.indexOf('notOnServerHint') < banner.indexOf('notPushedHint'),
  'and both come before the generic hints');

for (const key of ['notOnServerTitle', 'notOnServerHint', 'code_NOT_ON_SERVER']) {
  ok(new RegExp(`\\n    ${key}: '`).test(finalizeNs),
    `finalize.${key} exists`);
}
// The two sentences must actually SAY different things. "Not saved on this
// device" and "on this device but not on the server" have opposite advice about
// whether his work is safe, so a copy edit that converged them would be a bug.
const localHint = (finalizeNs.match(/notSavedLocalHint: '([^']*)'/) || [, ''])[1];
const serverHint = (finalizeNs.match(/notOnServerHint: '([^']*)'/) || [, ''])[1];
ok(localHint.length > 0 && serverHint.length > 0, 'both hints have copy');
ok(localHint !== serverHint, 'and they are not the same sentence');
ok(/nothing (is queued|will retry)/i.test(localHint),
  'the local-save hint says nothing is queued — because nothing is');
ok(/queued|sync/i.test(serverHint),
  'the unsynced hint says it IS queued — because it is');
ok(/safe/i.test(serverHint) && !/safe/i.test(localHint),
  'only the unsynced hint calls his work safe, which is the difference between them');

console.log('\n── the two daily-log screens, in their own idiom ──');

// NEITHER HAS A STEPPER OR A LOCK BAR, so Q1's submit gate and Q2's banner have
// nowhere to live as built. What they DO have is a persistent in-page badge,
// which is the same instrument for the same reason — it survives him walking
// away. Both already carried the SECOND reason ("Saved on device", driven by
// the pending-push queue). Neither carried the first, and its absence was the
// gap: the local-save failure was a toast and nothing else.
for (const rel of ['daily-log.jsx', path.join('site', 'daily-logs.jsx')]) {
  const src = strip(fs.readFileSync(path.join(FRONTEND, 'app', rel), 'utf8'));
  ok(src.length > 0, `${rel}: source read and non-empty`);

  // Q3 — the autosave reports both modes. These two were missed by the first
  // pass, which only reached their SUBMIT saves.
  ok(/\.then\(\(_ok\) => setLocalSaveFailed\(!_ok\)\)/.test(src),
    `${rel}: the autosave reads its boolean`);
  ok(/\.catch\(\(\) => setLocalSaveFailed\(true\)\)/.test(src),
    `${rel}: and catches a throw as the same answer`);
  const stmts = src.split('writeDraft(').slice(1)
    .map((c) => c.slice(0, c.indexOf(';') + 1));
  ok(stmts.length > 0, `${rel}: found writeDraft statements`);
  ok(stmts.filter((st) => st.includes('.catch(() => {})')).length === 0,
    `${rel}: no writeDraft swallows its own failure`);

  // Q2/Q5 — a DURABLE state for the first reason, not just a toast.
  ok(/const \[localSaveFailed, setLocalSaveFailed\] = useState\(false\);/.test(src),
    `${rel}: owns a sticky not-saved-on-this-device state`);
  ok(/setLocalSaveFailed\(!localSaved\);/.test(src),
    `${rel}: which the submit path sets from the same result it branches on`);
  ok(/NOT saved on (this )?device/.test(src),
    `${rel}: and renders it in words, persistently`);

  // THE WORSE OF THE TWO WINS THE SLOT, and ORDER DOES NOT PROVE IT. The first
  // version of this asserted only that the failure branch appears first in the
  // source, and a mutation removing the `!localSaveFailed` guard from the
  // reassuring banner survived: both were then renderable at once, in source
  // order, with the CP reading "Saved on this device" underneath "NOT saved on
  // this device". What has to hold is MUTUAL EXCLUSION.
  //
  // The two screens express it differently and both are checked as written:
  // daily-log guards its sibling block, site/daily-logs makes it the else-arm
  // of the same ternary. Neither is refactored to match the other — each is the
  // shape that screen already had.
  const EXCLUSION = {
    'daily-log.jsx': /\{!localSaveFailed && draftPending && \(/,
    [['site', 'daily-logs.jsx'].join(path.sep)]:
      /\{localSaveFailed \? \([\s\S]*?\) : pendingSync \? \(/,
  };
  ok(EXCLUSION[rel] !== undefined, `${rel}: has a declared exclusion shape`);
  ok(EXCLUSION[rel].test(src),
    `${rel}: the reassuring badge is UNREACHABLE while the failure is set — not `
    + `merely rendered after it`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
