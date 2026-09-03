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
 * The eleven editors this change covers.
 *
 * site_superintendent_log is EXCLUDED and stays excluded here: it is being
 * edited on two open branches (#363 fix/superintendent-local-first, #364
 * fix/superintendent-log-submit) and a twelfth simultaneous edit to the same
 * function is how a merge silently drops one of the three.
 */
const EDITORS = [
  'toolbox_talk', 'crane_operations', 'concrete_operations',
  'excavation_monitoring', 'hot_work', 'daily_jobsite', 'osha_log',
  'fall_protection', 'scaffold_maintenance', 'ssc_daily_safety_log',
  'preshift_signin',
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
    const call = src.indexOf('await compareDraftToServer(');
    const ret = src.indexOf('setLoading(false);');
    ok(call !== -1 && ret !== -1 && call < ret,
      `${name}: the server is asked BEFORE the draft path returns`);

    ok(/setDraftConflict\(/.test(src),
      `${name}: the verdict reaches component state rather than being dropped`);
    ok(/const \[draftConflict, setDraftConflict\] = useState\(null\);/.test(src),
      `${name}: and it owns the flag it reports`);

    // REFUSING THE SILENT OVERWRITE, and nothing richer. This is the whole of
    // the save-path change: no merge, no diff, no pick-a-side.
    ok(/if \(draftConflict\) return;/.test(src),
      `${name}: the save path refuses to PUT over a demonstrably newer server document`);
  }

  {
    // THE EXCLUSION IS ASSERTED, not merely intended. site_superintendent_log
    // is on two open PRs; a change to it here is a merge conflict waiting to
    // be resolved in the wrong direction.
    const src = screen('site_superintendent_log');
    ok(!/compareDraftToServer/.test(src),
      'site_superintendent_log is UNTOUCHED — it belongs to #363/#364');
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
  ok(/draftConflict/.test(footer),
    'Submit is blocked while the server is newer — the one save-path change in scope');

  for (const name of STEPPER_EDITORS) {
    ok(/draftConflict=\{draftConflict\}/.test(screen(name)),
      `${name}: hands the conflict to the stepper`);
  }
  ok(/<DraftConflictNotice/.test(screen('preshift_signin')),
    'preshift_signin owns no stepper, so it renders the same notice itself');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
