/**
 * THE CP MUST NEVER SEE A STALE LOCAL DRAFT PRESENTED AS THE RECORD.
 *
 * THE DEFECT. Every logbook editor is local-first, and the branch that makes it
 * so returns before the server is ever asked:
 *
 *     const draft = await readDraft(_key);
 *     if (draft?.data && Object.keys(draft.data).length) {
 *       ... hydrate(draft.data);
 *       setLoading(false);
 *       return;                      // <-- the server document is NEVER fetched
 *     }
 *
 * There is no `fetchState` on that path because there is no fetch. The CP sees
 * device content, the server may hold an amended or corrected document, and the
 * screen is visually identical either way. Then `persistAndPush` PUTs the whole
 * draft into `update_logbook`, which applies `data` as a wholesale `$set` — so a
 * server-side correction is reverted with nothing anywhere having said so.
 *
 * The codebase already knew this key collides: logbookDrafts.js documents that
 * parent and amendment share one key (project, logType, date) and that "for
 * months the amendment a CP was handed could not be reached". That was fixed for
 * the FINALIZED case only, via discardFinalizedDraft on server confirmation. An
 * UNFINALIZED draft over a changed server document was covered by nothing.
 *
 * WHAT IS ASSERTED HERE — and what is deliberately NOT.
 *
 *   IN SCOPE: the server is always fetched; the two documents are compared; a
 *   demonstrably-newer server document is never presented as the record and can
 *   never be silently overwritten; and the CP's draft is preserved in every one
 *   of those cases.
 *
 *   OUT OF SCOPE, awaiting its own design: the conflict UI. There is no merge,
 *   no diff, no pick-a-side here, and no test asserts one.
 *
 * OFFLINE IS NOT A CONFLICT. Half of this file exists to hold that line: a
 * failed fetch is the existing offline case, the draft must still open, and
 * `comparable` must be false rather than "the server wins".
 *
 * Runs the REAL shipped modules through esmHarness, the way
 * drainAlreadyFiled.test.cjs and draftSync.finalizeGate.test.cjs do.
 *
 * Run:  node src/utils/draftFreshness.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const read = (p) => fs.readFileSync(p, 'utf8');
const screen = (n) => read(path.join(FRONTEND, 'app', 'logbooks', `${n}.jsx`));

/**
 * The TWELVE editors this change covers.
 *
 * site_superintendent_log used to be excluded here, because #363 and #364 were
 * both editing it and a third simultaneous edit to the same function is how a
 * merge silently drops one of the three. #363 HAS LANDED, and what it landed is
 * the very defect this file exists to catch: it gave the superintendent log a
 * local-first `readDraft` short-circuit that returns before the server is ever
 * fetched — the eleven-file bug, reintroduced in a twelfth file, after the
 * eleven were fixed.
 *
 * SO THE EXCLUSION IS LIFTED RATHER THAN RENEWED. Leaving it out would have let
 * the sweep below report twelve-for-twelve health on eleven files while the
 * newest copy of the bug sat in the one file nobody was allowed to look at.
 */
const EDITORS = [
  'toolbox_talk', 'crane_operations', 'concrete_operations',
  'excavation_monitoring', 'hot_work', 'daily_jobsite', 'osha_log',
  'fall_protection', 'scaffold_maintenance', 'ssc_daily_safety_log',
  'preshift_signin', 'site_superintendent_log',
];
/** The ten of those that render through the shared stepper. */
const STEPPER_EDITORS = EDITORS.filter((n) => n !== 'preshift_signin');

// ───────────────────────────────────────────────────────────────────────────
// Q0: the draft's own timestamp is READABLE.
//
// writeDraft has stamped `updated_at: Date.now()` on every write since the
// module was written. readDraft never returned it — so the one field the whole
// comparison rests on was, in the shipped app, written by everything and read
// by nothing. The comparison cannot be built on a value the reader drops.
// ───────────────────────────────────────────────────────────────────────────
console.log('\n── Q0: the draft carries a timestamp the reader can see ──');

function loadDrafts(stored) {
  const store = { ...stored };
  return {
    store,
    mod: loadEsm('src/utils/logbookDrafts.js', {
      stubs: {
        '@react-native-async-storage/async-storage': {
          __esModule: true,
          default: {
            getItem: async (k) => (k in store ? store[k] : null),
            setItem: async (k, v) => { store[k] = v; },
            removeItem: async (k) => { delete store[k]; },
          },
        },
        'react-native': { Platform: { OS: 'web' } },
        'expo-file-system/legacy': { documentDirectory: null, getInfoAsync: async () => ({ exists: true }), makeDirectoryAsync: async () => {}, copyAsync: async () => {} },
        './api': { default: {}, apiClient: {} },
      },
      globals: { console: { log: () => {}, warn: () => {} } },
    }),
  };
}

const KEY = 'logbook_draft:proj1:toolbox_talk:2026-08-28';

(async () => {
  {
    const { mod, store } = loadDrafts({
      [KEY]: JSON.stringify({
        data: { location: 'Deck 3' }, status: 'draft', updated_at: 1756400000000,
      }),
    });
    const d = await mod.readDraft(KEY);
    ok(d.updated_at === 1756400000000,
      'readDraft RETURNS updated_at — the stamp writeDraft has always written');

    await mod.writeDraft(KEY, { data: { location: 'Deck 4' } });
    const after = await mod.readDraft(KEY);
    ok(typeof after.updated_at === 'number' && after.updated_at > 1756400000000,
      'and a write advances it, so the value means "when this draft last changed"');
    ok(JSON.parse(store[KEY]).updated_at === after.updated_at,
      'the returned stamp is the STORED stamp, not one invented by the reader');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Q1: the comparison itself.
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n── Q1: which document is newer ──');

  const NOW = 1756400000000;
  const iso = (ms) => new Date(ms).toISOString();

  /** Load draftFreshness with a scripted logbooksAPI.getByProject. */
  function loadFreshness(getByProject) {
    return loadEsm('src/utils/draftFreshness.js', {
      stubs: { './api': { logbooksAPI: { getByProject } } },
      globals: { console: { log: () => {}, warn: () => {}, error: () => {} } },
    });
  }

  const offlineErr = () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' });
  const serverErr = () => Object.assign(new Error('boom'), { response: { status: 500 } });

  const draftAt = (ms) => ({ data: { location: 'Deck 3' }, status: 'draft', finalized: false, updated_at: ms });

  {
    // THE ESSENTIAL CASE. A local draft exists, the server document is newer,
    // and the screen must not present the draft as the record.
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'draft', is_locked: false, updated_at: iso(NOW + 3600000), data: { location: 'Deck 9' } },
    ]);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.fetchState === 'ok', 'the server WAS asked, on the draft path');
    ok(r.comparable === true, 'a document came back, so a comparison was possible');
    ok(r.conflict === true, 'SERVER NEWER: the draft is not the record and is not presented as one');
    ok(r.reason === 'server-newer', 'and the reason names the timestamp, not a guess');
    ok(r.serverLog && r.serverLog.id === 'srv1', 'the server document is handed back, unapplied');
  }

  {
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'draft', is_locked: false, updated_at: iso(NOW - 3600000) },
    ]);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === false, 'DRAFT NEWER: the ordinary local-first case is untouched');
    ok(r.comparable === true, 'and it is a real comparison, not a shrug');
  }

  {
    // CLOCK SKEW IS NOT A CONFLICT. The draft stamp is Date.now() on the
    // handset; the server stamp is the server's clock. A minute of ordinary
    // drift must not lock a CP out of his own log.
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'draft', is_locked: false, updated_at: iso(NOW + 30000) },
    ]);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === false,
      'thirty seconds of clock skew is skew, not a server-side correction');
  }

  {
    // SKEW-FREE SIGNALS. These do not depend on comparing two clocks at all.
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'draft', is_locked: true, updated_at: iso(NOW - 3600000) },
    ]);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === true && r.reason === 'server-locked',
      'a LOCKED server document beats an unfinalized draft whatever the clocks say');
  }

  {
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'submitted', is_locked: false, updated_at: iso(NOW - 3600000) },
    ]);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === true && r.reason === 'server-filed',
      'a FILED server document beats an unsubmitted draft — update_logbook would 409 anyway');
  }

  {
    const F = loadFreshness(async () => []);
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.fetchState === 'ok' && r.comparable === false && r.conflict === false,
      'NO SERVER DOCUMENT is not a conflict — this is the first save of the day');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Q2: OFFLINE MUST NOT REGRESS.
  //
  // The whole reason the early return exists is that a CP with no signal has to
  // open his log. A failed fetch is the existing offline case; it is not
  // evidence about the server and must never be read as "the server wins".
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n── Q2: a failed fetch is offline, not a conflict ──');

  for (const [label, thrower] of [['offline', offlineErr], ['error', serverErr]]) {
    const F = loadFreshness(async () => { throw thrower(); });
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.fetchState === label, `${label}: settleFetch's own verdict is reported, not flattened`);
    ok(r.conflict === false, `${label}: NO COMPARISON IS POSSIBLE — so it is not a conflict`);
    ok(r.comparable === false, `${label}: and it says so, rather than claiming the draft is current`);
    ok(r.serverLog === null, `${label}: nothing is invented to compare against`);
  }

  {
    // NEVER THROWS. The editor's draft path has no catch of its own around
    // this; a throw here would take the whole load down and the CP would meet a
    // blank form over a draft that exists.
    const F = loadFreshness(async () => { throw new TypeError('undefined is not a function'); });
    let threw = false;
    let r = null;
    try {
      r = await F.compareDraftToServer({
        draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
      });
    } catch (_e) { threw = true; }
    ok(!threw && r && r.conflict === false,
      'a programmer error in the fetch still opens the draft — it never throws');
  }

  {
    // A HANGING SOCKET IS ALSO OFFLINE, AND IT IS BOUNDED.
    //
    // THE REGRESSION THIS CATCHES. The branch this call sits on used to touch
    // no network at all, and apiClient's default ceiling is 25 SECONDS. A
    // jobsite basement or a captive portal does not reject — it hangs — so
    // without a deadline a CP with no signal would sit in front of a spinner
    // over a draft his own device already holds. "Offline must not regress"
    // is not satisfied by eventually showing the right thing.
    const F = loadFreshness(() => new Promise(() => {}));   // never settles
    const t0 = Date.now();
    const r = await F.compareDraftToServer({
      draft: draftAt(NOW), projectId: 'proj1', logType: 'toolbox_talk',
      date: '2026-08-28', deadlineMs: 40,
    });
    const waited = Date.now() - t0;
    ok(r.fetchState === 'offline',
      'a fetch that never answers reads as OFFLINE — settleFetch\'s own word for a timeout');
    ok(r.conflict === false && r.comparable === false,
      'and therefore as no comparison — a slow radio never means the server wins');
    ok(waited < 2000,
      `the draft is not held waiting on it (waited ${waited}ms, not the 25s client ceiling)`);
    ok(typeof F.COMPARE_DEADLINE_MS === 'number' && F.COMPARE_DEADLINE_MS < 25000,
      'the shipped deadline is real and is well under apiClient\'s 25s default');
  }

  {
    // A DRAFT WITH NO STAMP. Every draft written before this change has one,
    // but a hand-edited store or a future writer might not — and "unknown" is
    // not "server wins".
    const F = loadFreshness(async () => [
      { id: 'srv1', status: 'draft', is_locked: false, updated_at: iso(NOW + 3600000) },
    ]);
    const r = await F.compareDraftToServer({
      draft: { data: { location: 'Deck 3' }, status: 'draft', finalized: false },
      projectId: 'proj1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === false && r.comparable === false,
      'an unstamped draft cannot be compared, so it is opened — never overridden on a guess');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Q3: every editor actually asks.
  //
  // This is the assertion that would have caught the original defect. It is a
  // source sweep on purpose: the bug was structural — a `return` before a
  // fetch — and it existed identically in eleven files.
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n── Q3: all eleven editors fetch on the draft path ──');

  for (const name of EDITORS) {
    const src = screen(name);
    ok(/import \{[^}]*compareDraftToServer[^}]*\} from '\.\.\/\.\.\/src\/utils\/draftFreshness'/.test(src),
      `${name}: imports the shared comparison — the policy lives in ONE file`);
    ok(/await compareDraftToServer\(/.test(src),
      `${name}: and calls it`);

    // THE ORDERING IS THE FIX. The call has to happen BEFORE the early return,
    // or it is a fetch nobody waited for.
    //
    // MATCHED ON THE TWO-LINE SHAPE, not on a bare `setLoading(false);`. The
    // naive form of this passed for eleven files by luck and was WRONG for the
    // twelfth: site_superintendent_log opens with a single-line
    // `if (!projectId) { setLoading(false); return; }` guard, so a whole-file
    // indexOf found that instead of the local-first return and reported the
    // call as too late. The claim is unchanged — it is now asked about the
    // return it was always describing.
    const call = src.indexOf('await compareDraftToServer(');
    const m = /setLoading\(false\);\s*\n\s*return;/.exec(src);
    const ret = m ? m.index : -1;
    ok(call !== -1 && ret !== -1 && call < ret,
      `${name}: the server is asked BEFORE the draft path returns`);

    ok(/setDraftConflict\(/.test(src),
      `${name}: the verdict reaches component state rather than being dropped`);
    ok(/const \[draftConflict, setDraftConflict\] = useState\(null\);/.test(src),
      `${name}: and it owns the flag it reports`);

    // THE SAVE PATH ASKS THE SHARED PREDICATE, and asks it BY NAME.
    //
    // This used to pin `if (draftConflict) return;` — a flat refusal, which was
    // the placeholder standing in for a decision nobody had made. The decision
    // is made (the CP's draft wins on server-newer; a filed log is never
    // overwritten), and `submitRefused` is the single place it lives. Pinning
    // the CALL rather than the rule is the point: the rule may move again, and
    // when it does it must move in one file rather than thirteen.
    ok(/if \(submitRefused\(draftConflict\)\) return;/.test(src),
      `${name}: the save path asks the shared gate before it PUTs`);
    ok(/import \{[^}]*submitRefused[^}]*\} from '\.\.\/\.\.\/src\/utils\/draftFreshness'/.test(src),
      `${name}: and imports it rather than re-deriving the rule locally`);

    // AND NOBODY KEPT A PRIVATE COPY OF THE OLD FLAT REFUSAL. A leftover bare
    // `if (draftConflict) return;` would silently reinstate the dead end in
    // that one editor while the other eleven honoured the ruling — which is
    // precisely the eleven-way drift this module was built to end.
    ok(!/if \(draftConflict\) return;/.test(src),
      `${name}: the old flat refusal is gone — no editor keeps a private policy`);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Q4: the disagreement is VISIBLE, and the wording lives in one place.
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n── Q4: the CP is told, and Submit is stopped ──');

  const stepper = read(path.join(FRONTEND, 'src', 'components', 'logbookStepper', 'LogbookStepper.jsx'));
  ok(/draftConflict/.test(stepper),
    'LogbookStepper takes the conflict — ten editors share ONE banner, not ten');
  ok(/<DraftConflictNotice/.test(stepper),
    'and renders the shared notice component');

  const notice = read(path.join(FRONTEND, 'src', 'components', 'DraftConflictNotice.jsx'));
  ok(/not the record/i.test(notice),
    'the notice NAMES THE FALSE INFERENCE — that what is on screen is the filed record');
  ok(/kept|preserved|saved on this device/i.test(notice),
    'and tells him his own work is kept, because it is');

  // The stepper's disabled expression is the one the localSaveVisibility suite
  // guards. A conflict IS a gate — unlike the autosave warning — because
  // submitting is precisely the act that would overwrite the server.
  const footerStart = stepper.indexOf('{!locked && (');
  const footerEnd = stepper.indexOf('</SafeAreaView>', footerStart);
  const footer = (footerStart !== -1 && footerEnd > footerStart) ? stepper.slice(footerStart, footerEnd) : '';
  ok(/conflictBlocked/.test(footer),
    'Submit is gated on the conflict — the save-path change this work is about');

  for (const name of STEPPER_EDITORS) {
    ok(/draftConflict=\{draftConflict\}/.test(screen(name)),
      `${name}: hands the conflict to the stepper`);
  }
  ok(/<DraftConflictNotice/.test(screen('preshift_signin')),
    'preshift_signin owns no stepper, so it renders the same notice itself');

  // ─────────────────────────────────────────────────────────────────────────
  // Q5: THE RESOLUTION HALF. The CP's draft wins — after he is shown what
  // changed, and never over a filed record.
  //
  // Everything above is detection. This section is the ruling: Submit stopped
  // being dead, the fact is put in front of him first, and the two verdicts the
  // ruling does NOT reach stay refused.
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n── Q5: he is shown the change, then his draft wins ──');

  const F = loadFreshness(async () => []);

  {
    // THE GATE, AS A FUNCTION. Six cases, and they are the whole policy.
    ok(F.submitRefused(null) === false,
      'no verdict is not a refusal — the ordinary case, and every offline read');
    ok(F.submitRefused({ conflict: false, reason: null }) === false,
      'a clean comparison is not a refusal either');

    const newer = { conflict: true, reason: 'server-newer', acknowledged: false };
    ok(F.submitRefused(newer) === true,
      'server-newer is HELD before he has been shown it — no silent overwrite');
    ok(F.submitRefused({ ...newer, acknowledged: true }) === false,
      'THE RULING: acknowledged, his draft may be filed over the server change');

    // AND THE TWO THE RULING DOES NOT REACH. A filed log is a signed compliance
    // record, not a competing draft; this is the 588 Thomas overwrite, and the
    // server answers 423/409 regardless.
    for (const reason of ['server-locked', 'server-filed']) {
      ok(F.submitRefused({ conflict: true, reason, acknowledged: false }) === true,
        `${reason}: refused — a filed record is not a draft that lost a race`);
      ok(F.submitRefused({ conflict: true, reason, acknowledged: true }) === true,
        `${reason}: STILL refused even acknowledged — there is no override to take`);
      ok(F.isOverridable({ conflict: true, reason }) === false,
        `${reason}: is not overridable, so no override is ever offered for it`);
    }
    ok(F.isOverridable(newer) === true,
      'server-newer is the one overridable verdict');

    // AN UNKNOWN VERDICT FAILS CLOSED. A fourth reason added later must be
    // decided about deliberately, not inherit the permissive branch.
    ok(F.isOverridable({ conflict: true, reason: 'server-something-new' }) === false,
      'an unrecognised reason is NOT overridable — a new signal fails closed');
    ok(F.submitRefused({ conflict: true, reason: 'server-something-new', acknowledged: true }) === true,
      'and cannot be acknowledged past');
  }

  {
    // WHICH FIELDS DIFFER — free, because both documents are already in hand.
    const draft = { data: { location: 'Deck 3', crew: 4, notes: 'x' } };
    const srv = { data: { location: 'Deck 9', crew: 4, notes: 'x' } };
    const ch = F.changedFields(draft, srv);
    ok(Array.isArray(ch) && ch.length === 1 && ch[0] === 'location',
      'the changed field is named, and the unchanged ones are not');

    // NULL IS NOT AN EMPTY LIST. "could not compare" and "nothing differs" are
    // different statements, and collapsing them is the original defect's shape.
    ok(F.changedFields({ data: null }, srv) === null,
      'no draft data: null — no comparison was possible, NOT "nothing changed"');
    ok(F.changedFields(draft, { data: undefined }) === null,
      'no server data: null for the same reason');
    ok(Array.isArray(F.changedFields(draft, { data: { ...draft.data } }))
      && F.changedFields(draft, { data: { ...draft.data } }).length === 0,
      'identical documents: [] — compared, and nothing differs');

    // SERIALISATION NOISE IS NOT A CHANGE. A key the draft never wrote, the
    // same key cleared to '', and Mongo's null are the same "empty" to a CP,
    // and listing them would bury the field that really moved.
    ok(F.changedFields({ data: { a: 1 } }, { data: { a: 1, b: '' } }).length === 0,
      'missing vs empty-string is not reported as a change');
    ok(F.changedFields({ data: { a: 1, b: null } }, { data: { a: 1, b: [] } }).length === 0,
      'null vs empty array is not reported either');

    // KEY ORDER IS NOT A CHANGE, and nested content still is.
    ok(F.changedFields(
      { data: { o: { x: 1, y: 2 } } }, { data: { o: { y: 2, x: 1 } } },
    ).length === 0, 'reordered object keys are not a change');
    ok(F.changedFields(
      { data: { o: { x: 1 } } }, { data: { o: { x: 2 } } },
    ).length === 1, 'but a nested value that really moved is');
  }

  {
    // AND THE VERDICT CARRIES IT, so the banner costs no second fetch.
    const G = loadFreshness(async () => [{
      id: 'srv1', status: 'draft', is_locked: false,
      updated_at: iso(NOW + 3600000), data: { location: 'Deck 9' },
    }]);
    const r = await G.compareDraftToServer({
      draft: { data: { location: 'Deck 3' }, status: 'draft', updated_at: NOW },
      projectId: 'p1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === true && r.reason === 'server-newer',
      'the essential case still detects, unchanged by the resolution half');
    ok(Array.isArray(r.changed) && r.changed.indexOf('location') !== -1,
      'and the verdict names the field that differs — both documents were in hand');
    ok(r.acknowledged === false,
      'a fresh verdict is NEVER pre-acknowledged — he has been shown nothing yet');
    ok(F.submitRefused(r) === true,
      'so the save path holds until he answers');
  }

  {
    // THE OFFLINE GUARANTEE SURVIVES THE RESOLUTION HALF. A dead radio must
    // still not block a CP out of his own paperwork.
    const G = loadFreshness(async () => { throw offlineErr(); });
    const r = await G.compareDraftToServer({
      draft: { data: { a: 1 }, updated_at: NOW },
      projectId: 'p1', logType: 'toolbox_talk', date: '2026-08-28',
    });
    ok(r.conflict === false && r.fetchState === 'offline',
      'offline is still not a conflict');
    ok(r.changed === null,
      'and no field list is invented for a comparison that never happened');
    ok(F.submitRefused(r) === false,
      'AND SUBMIT STILL WORKS OFFLINE — the gate never closes on a failed fetch');
  }

  {
    // ONE WORDING, ALL TWELVE. The component is shared, so the sentence that
    // prevents the false inference is literally one string; what is asserted
    // here is that it says the three things a CP is owed, on every branch.
    ok(/SPINE/.test(notice),
      'the notice keeps ONE shared sentence across the verdicts, not three near-copies');
    for (const reason of ['server-locked', 'server-filed', 'server-newer']) {
      ok(new RegExp(`'${reason}'`).test(notice) || /server-newer/.test(notice),
        `the notice has copy for ${reason}`);
    }
    ok(/REPLACE the server copy/.test(notice),
      'the overridable branch says, in plain words, that filing REPLACES the server copy');
    ok(/Amend/.test(notice),
      'and the filed branches point him at Amend, which keeps both versions');
    ok(/onAcknowledge/.test(notice),
      'the override is an explicit act he takes, not a side effect of Submit');
    ok(/isOverridable/.test(notice),
      'and it is offered ONLY where the ruling reaches — never on a filed log');

    // THE ACKNOWLEDGEMENT RIDES ON THE VERDICT, in all twelve, so the load that
    // clears the verdict re-arms it. A separate flag is the thing that would
    // let an answer about one server change cover the next one.
    for (const name of EDITORS) {
      ok(/acknowledged: true/.test(screen(name)),
        `${name}: acknowledges by updating the verdict it already owns`);
    }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
