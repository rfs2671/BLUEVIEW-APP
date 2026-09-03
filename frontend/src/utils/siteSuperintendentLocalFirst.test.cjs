/**
 * THE SUPERINTENDENT LOG IS LOCAL-FIRST, LIKE EVERY OTHER EDITOR.
 *
 * WHAT WAS WRONG. app/logbooks/site_superintendent_log.jsx imported NOTHING
 * from src/utils/logbookDrafts.js. Nine sibling editors autosave a draft to
 * AsyncStorage on every change, mark the key pending when a push fails, and
 * are drained by src/utils/draftSync.js on the next NetInfo transition. This
 * one held a five-step BC 3301.13.13 statutory log in React state and posted
 * it straight to the server. With no signal the post threw, a toast said
 * "Could not file this log", and NOTHING WAS WRITTEN ANYWHERE — the whole log
 * lived in component state until he navigated away, and then it was gone.
 *
 * The screen's own load handler said so in a comment while it was false:
 * "let him work offline; the draft is local-first like every other editor."
 * It was not. That comment is the shape this file exists to stop: a claim
 * about persistence with nothing persisting.
 *
 * IT IS THE WORST LOG TO LOSE. 3301.13.13 requires it completed BEFORE the
 * superintendent leaves the site, and cellars, shafts and below-grade decks
 * are exactly where there is no signal. The log is due in the place the app
 * could not save it.
 *
 * ── WHAT IS ASSERTED, AND HOW ───────────────────────────────────────────────
 *
 * Sections 1 and 3 EXECUTE the real shipped draftSync through esmHarness — the
 * drain is what has to accept this log type and re-apply its freeze, and a
 * grep cannot show that it does. Sections 2 and 4 read the screen's source
 * with comments STRIPPED, because this file's subject explains itself at
 * length and a bare search matches the explanation rather than the code (the
 * trap siteSuperintendentSign.test.cjs already records).
 *
 * Run:  node src/utils/siteSuperintendentLocalFirst.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const SCREEN_RAW = read('app', 'logbooks', 'site_superintendent_log.jsx');
const SIBLING_RAW = read('app', 'logbooks', 'fall_protection.jsx');
const SCRATCH_RAW = read('src', 'utils', 'logbookScratch.js');

/** Comments stripped — see the header note. */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const SCREEN = CODE(SCREEN_RAW);
const SIBLING = CODE(SIBLING_RAW);

/**
 * The balanced-brace block that follows an anchor — the extractor
 * draftSync.finalizeGate.test.cjs already uses.
 *
 * TEXTUAL ORDER IS NOT EXECUTION ORDER in a hooks component: a callback is
 * DECLARED above the effect that calls it and RUNS after it. Two assertions
 * below were written as `indexOf(a) < indexOf(b)` over the whole file and said
 * the wrong thing for exactly that reason. They ask about one function's body
 * now, which is the scope the claim is actually about.
 */
// RETURNS '' RATHER THAN THROWING when the anchor is absent, so a screen that
// does not have the function yet FAILS these assertions by name instead of
// aborting the run — a crash reports nothing about the other 30.
function block(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return '';
  const open = src.indexOf('{', at);
  if (open < 0) return '';
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(at, i + 1);
    }
  }
  return '';
}

let passed = 0; let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
};

const LOG_TYPE = 'site_superintendent_log';
const KEY = `logbook_draft:proj7:${LOG_TYPE}:2026-09-01`;

// ── the drain, under the harness ────────────────────────────────────────────
//
// Same construction drainAlreadyFiled.test.cjs uses: the REAL draftSync.js is
// compiled and run, with only the packages plain node cannot load stubbed.
function makeEnv(draft, { rejection } = {}) {
  const store = {};
  const calls = {
    created: [], updated: [], finalized: [], cleared: [],
  };
  return {
    calls,
    store,
    env: {
      console: { log: () => {}, warn: () => {} },
      NetInfo: { addEventListener: () => () => {} },
      AsyncStorage: {
        getItem: async (k) => (k in store ? store[k] : null),
        setItem: async (k, v) => { store[k] = v; },
      },
      getPendingKeys: async () => [KEY],
      readDraft: async () => draft,
      setDraftBackendId: async () => {},
      clearPending: async (k) => { calls.cleared.push(k); },
      logbooksAPI: {
        create: async (body) => {
          calls.created.push(body);
          if (rejection) throw rejection;
          return { id: 'cslog1' };
        },
        update: async (id, body) => {
          calls.updated.push({ id, body });
          if (rejection) throw rejection;
          return { id };
        },
        finalize: async (id) => { calls.finalized.push(id); return { id, is_locked: true }; },
      },
    },
  };
}

function loadDraftSync(env) {
  return loadEsm('src/utils/draftSync.js', {
    globals: { console: env.console },
    stubs: {
      '@react-native-async-storage/async-storage': env.AsyncStorage,
      '@react-native-community/netinfo': env.NetInfo,
      './api': { logbooksAPI: env.logbooksAPI },
      './logbookDrafts': {
        getPendingKeys: env.getPendingKeys,
        readDraft: env.readDraft,
        setDraftBackendId: env.setDraftBackendId,
        clearPending: env.clearPending,
        writeDraft: async () => true,
        uploadPendingActivityPhotos: async (_p, acts) => ({
          uploaded: 0, remaining: 0, activities: acts,
        }),
      },
    },
  });
}

const AFFIRMED = { affirmed: true, paths: [[{ x: 1, y: 1 }]] };
const FILLED = {
  presence: { printed_name: 'R. Sanchez', arrived_at: '07:10', departed_at: '16:40' },
  progress: { summary: 'Deck poured, 4th floor' },
  unsafe_conditions: { none_to_report: true },
  orders_given: { none_to_report: true },
};

(async () => {
  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n1. THE SHARED DRAIN ACCEPTS THIS LOG TYPE');
  // The whole fix rests on it. draftSync keeps a SKIP_LOG_TYPES set for the
  // daily-log types, whose payload shape is different enough that inventing
  // one is not worth the risk. If site_superintendent_log were in that set, a
  // draft written by the editor would sit pending forever and the local-first
  // change would be a different shape entirely. Executed, not grepped: the
  // guard is a `Set.has` inside pushOne and only running it proves the answer.
  {
    const drainSrc = read('src', 'utils', 'draftSync.js');
    ok(!new RegExp(`SKIP_LOG_TYPES[\\s\\S]{0,200}${LOG_TYPE}`).test(drainSrc),
      `${LOG_TYPE} is NOT in the drain's skip set`);

    const { calls, env } = makeEnv({
      data: FILLED,
      cp_signature: AFFIRMED,
      cp_name: 'R. Sanchez',
      status: 'submitted',
      backend_id: null,
      finalized: true,
    });
    const { syncPendingDrafts } = loadDraftSync(env);
    const out = await syncPendingDrafts();

    ok(calls.created.length === 1,
      'a superintendent draft queued while offline IS sent on reconnect');
    const body = calls.created[0] || {};
    ok(body.log_type === LOG_TYPE && body.project_id === 'proj7'
       && body.date === '2026-09-01',
    'and the key alone rebuilds project, type and date — nothing is guessed');
    ok(JSON.stringify(body.data) === JSON.stringify(FILLED)
       && body.cp_name === 'R. Sanchez' && body.status === 'submitted',
    'the document, the name and the status reach the server verbatim');
    ok(out.synced === 1 && calls.cleared.includes(KEY),
      'the push lands and the key stops being pending');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n2. THE DEPARTURE FREEZE SURVIVES THE TRIP');
  // This is a `visit`-class log: logbook_timing_meta publishes
  // freeze_on_sign=false / freeze_on_finalize=TRUE, and
  // sweep_stale_end_of_day_logs deliberately excludes VISIT_LOG_TYPES. So
  // NOTHING ELSE will ever lock it. A log signed in a cellar is frozen on the
  // device; the drain's applyRemoteFreeze is the only thing that can carry
  // that freeze to the server afterwards.
  {
    const { calls, env } = makeEnv({
      data: FILLED,
      cp_signature: AFFIRMED,
      cp_name: 'R. Sanchez',
      status: 'submitted',
      backend_id: null,
      finalized: true,
    });
    const { syncPendingDrafts } = loadDraftSync(env);
    await syncPendingDrafts();
    ok(calls.finalized.includes('cslog1'),
      'a draft frozen on departure with no signal is FINALIZED server-side '
      + 'when it lands — nothing else ever would');
  }
  {
    const { calls, env } = makeEnv({
      data: FILLED,
      cp_signature: AFFIRMED,
      cp_name: 'R. Sanchez',
      status: 'submitted',
      backend_id: null,
      finalized: false,
    });
    const { syncPendingDrafts } = loadDraftSync(env);
    await syncPendingDrafts();
    ok(calls.finalized.length === 0,
      'and a draft he has NOT signed off is never frozen behind him');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n3. A FROZEN DRAFT WITH AN UNEARNED SIGNATURE IS A TRAP');
  // Why the editor must never markFinalized on an unaffirmed signature.
  //
  // The drain refuses `status: submitted` without an AFFIRMED signature —
  // `{}` is truthy and production held exactly that — and leaves the key
  // pending so the CP can fix the draft and the next drain sends it. But
  // markFinalized makes the draft IMMUTABLE: writeDraft then refuses every
  // content edit. Freeze one of these and the log can never be corrected and
  // can never be sent, while the screen shows it as filed. Executed, because
  // the trap is the INTERACTION of two modules, not a line in either.
  {
    const { calls, store, env } = makeEnv({
      data: FILLED,
      cp_signature: {},              // truthy, and affirmed by nobody
      cp_name: 'R. Sanchez',
      status: 'submitted',
      backend_id: null,
      finalized: true,
    });
    const { syncPendingDrafts } = loadDraftSync(env);
    await syncPendingDrafts();
    ok(calls.created.length === 0,
      'the drain never sends a submit whose signature was not affirmed');
    ok(!calls.cleared.includes(KEY),
      'and the key stays pending forever — so a draft frozen in this state '
      + 'can never be sent AND can never be edited');
    const recorded = Object.values(JSON.parse(store.logbook_finalize_errors || '{}'));
    ok(recorded.length === 1 && recorded[0].code === 'SUBMIT_MISSING_CP_SIGNATURE',
      'it is refused by name, not silently');

    // THE EDITOR'S HALF OF THE SAME RULE. The freeze must be conditional on
    // the affirmation, at the call site, not merely implied by a guard two
    // hundred lines up the function.
    ok(/markFinalized\(_key\)/.test(SCREEN),
      'the screen freezes the draft on departure at all — nothing else will');

    // THE GUARD IS IN THE FREEZE ITSELF, not two hundred lines up the handler.
    const freeze = block(SCREEN, 'const freezeLocally', 'freezeLocally');
    ok(/isAffirmedSignature\(cpSignature\)/.test(freeze)
       && freeze.indexOf('isAffirmedSignature') < freeze.indexOf('markFinalized'),
    'and the departure freeze REFUSES an unaffirmed signature before it '
    + 'writes the lock — the trap above is unreachable by construction');

    // AND NOTHING ELSE IN THE SUBMIT PATH FREEZES. A second, unguarded
    // markFinalized would reopen the trap while this assertion still passed.
    const submit = block(SCREEN, 'const handleSubmit', 'handleSubmit');
    const freezesInSubmit = (submit.match(/markFinalized\(/g) || []).length;
    ok(freezesInSubmit === 1,
      'the submit path has exactly ONE call to markFinalized — the guarded '
      + `one (found ${freezesInSubmit})`);
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n4. THE EDITOR USES THE SHARED DRAFT STORE');
  // Reuse, not a parallel mechanism. The names are asserted individually
  // because a partial adoption is the failure that looks like success: an
  // editor that writes a draft but never marks it pending saves the log to the
  // device and then never sends it.
  {
    for (const fn of ['draftKey', 'readDraft', 'writeDraft', 'setDraftBackendId',
      'markPending', 'clearPending', 'markFinalized']) {
      ok(new RegExp(`\\b${fn}\\b`).test(SCREEN)
         && /from '\.\.\/\.\.\/src\/utils\/logbookDrafts'/.test(SCREEN),
      `the screen calls ${fn} from the shared logbookDrafts store`);
    }
    ok(new RegExp(`draftKey\\(\\{[^}]*logType: LOG_TYPE`).test(SCREEN),
      'the key is built from the declared LOG_TYPE, so it matches the key the '
      + 'drain parses back out');
    ok(!/AsyncStorage/.test(SCREEN),
      'and it never reaches for AsyncStorage directly — the store owns the '
      + 'key namespace, the finalize lock and the pending index');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n5. THE WORK IS ON THE DEVICE BEFORE IT IS SENT');
  {
    ok(/setTimeout\([\s\S]{0,400}writeDraft\(_key/.test(SCREEN),
      'a debounced autosave writes the draft as he types, like every sibling');

    const writeAt = SCREEN.indexOf('writeDraft(_key');
    const createAt = SCREEN.indexOf('logbooksAPI.create');
    ok(writeAt > 0 && createAt > 0 && writeAt < createAt,
      'and the local write happens BEFORE the push — the offline record is '
      + 'what the promise of a later sync rests on');

    ok(/readDraft\(_key\)/.test(SCREEN),
      'the load reads the local draft');
    const readDraftAt = SCREEN.indexOf('readDraft(_key)');
    const serverReadAt = SCREEN.indexOf('logbooksAPI.getByProject');
    ok(readDraftAt > 0 && serverReadAt > 0 && readDraftAt < serverReadAt,
      'and it reads the DEVICE before the server — that is what local-first '
      + 'means, and it is what lets him open the log in a cellar');

    ok(/markPending\(_key\)/.test(SCREEN),
      'a push that did not land leaves the key pending, so the drain retries');
    ok(/clearPending\(_key\)/.test(SCREEN),
      'and a push that DID land stops being retried');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n6. THE AUTOSAVE CANNOT MINT A SUBMIT');
  // The draft stores `status` and `cp_signature` independently, and the drain
  // replays whatever it finds. An autosave that wrote `status: 'submitted'`
  // would file a half-typed statutory log behind him. writeDraft preserves a
  // field left undefined, so the autosave simply must not name one.
  {
    const at = SCREEN.indexOf('setTimeout');
    const window = SCREEN.slice(at, at + 500);
    ok(at > 0 && !/status:/.test(window),
      'the debounced autosave passes no `status` — it can only ever write a '
      + 'draft, never a filing');
    ok(/status: 'submitted'/.test(SCREEN),
      'and the submit path names it explicitly, where the gate is');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n7. THE UNSYNCED BANNER CAN COME DOWN');
  // An offline CREATE has no server id, so the banner is recorded against the
  // DRAFT KEY — which means LogbookLockBar must be given that key or the
  // banner it renders can never be looked up, and a banner that cannot come
  // down is how a CP learns to read past all of them.
  {
    ok(/draftKey=\{_key\}/.test(SCREEN),
      'the stepper is handed the draft key, so the lock bar can find the '
      + 'record raised against an offline create');
    ok(/draftKey=\{_key\}/.test(SIBLING),
      '(the sibling does the same — this is the shared pattern, not a new one)');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n8. THE IN-MEMORY SCRATCH IS KEPT, AND IT STILL WINS');
  // logbookScratch.js holds the RAW entry across the push to /consent. It is
  // not draft persistence and must not be mistaken for it — but it is also
  // not made redundant by one, because the draft stores the DOCUMENT shape,
  // which is lossy by design: deriveConditionAndOrderBlocks drops a finding
  // row with a location typed and no condition yet, unticked DOB suggestions
  // never reach it, and the step he was on is not in it. The stash holds all
  // three. So it stays, and it is applied ON TOP of the draft.
  {
    ok(/from '\.\.\/\.\.\/src\/utils\/logbookScratch'/.test(SCREEN),
      'the scratch is still used — a persisted draft does not replace it');
    // AGAINST THE CODE, NOT THE FILE. logbookScratch's header explains at
    // length that it is "a module-level Map, NOT AsyncStorage" — so a raw
    // search for AsyncStorage matches the sentence promising it is absent.
    const scratchCode = CODE(SCRATCH_RAW);
    ok(!/AsyncStorage/.test(scratchCode) && /new Map\(\)/.test(scratchCode),
      'and it is still an in-memory Map: it was not quietly promoted into '
      + 'half of the persistence layer under another name');

    // ASKED OF THE LOAD FUNCTION, not of the file. `applyHeld` is DECLARED
    // above the load and RUNS inside it, so a whole-file index comparison
    // measures declaration order and answers the wrong question.
    const held = block(SCREEN, 'const applyHeld', 'applyHeld');
    ok(/take\(scratchId\)/.test(held) && /restore\(held\)/.test(held),
      'taking the stash and restoring it is one step, in one place');

    const load = block(SCREEN, 'const fetchData', 'fetchData');
    ok(load.indexOf('readDraft(_key)') > 0
       && load.indexOf('readDraft(_key)') < load.indexOf('applyHeld('),
    'and the load reads the draft BEFORE it applies the stash — the stash is '
    + 'the newer and the richer of the two, so it goes on top rather than '
    + 'under');
    ok(load.indexOf('applyHeld(') < load.indexOf('logbooksAPI.getByProject')
       || /applyHeld\(draft\.finalized === true\)/.test(load),
    'the local-first branch applies it too, so his entry is not lost on the '
    + 'one path that never reaches the server');
  }

  // ─────────────────────────────────────────────────────────────────────────
  console.log('\n9. AN EMPTY FROZEN DRAFT DOES NOT SWALLOW THE AMENDMENT');
  // The screen records the offline finalize lock by writing a draft that is
  // FINALIZED and holds nothing — that is how a log filed from another session
  // gets locked on this device. writeDraft then refuses every content edit for
  // that key. So when the amendment arrives, a load that gated its
  // adoptAmendment call on the draft having CONTENT would walk straight past
  // the empty frozen record, open the editable child from the server, and have
  // every autosave silently refused underneath it.
  {
    const load = block(SCREEN, 'const fetchData');
    ok(/adoptAmendment/.test(load),
      'the load asks the server whether a correction exists');
    ok(/draft && draft\.finalized\) && await adoptAmendment/.test(load),
      'and it asks on the strength of the FREEZE alone, not of the content');
    const askAt = load.indexOf('adoptAmendment');
    const contentAt = load.indexOf('hasLocalContent)');
    ok(askAt > 0 && contentAt > 0 && askAt < contentAt,
      'so the question is put BEFORE the content check, which is the only '
      + 'ordering under which an empty frozen draft can ever be discarded');
    ok(/const hasLocalContent/.test(load)
       && /Object\.keys\(draft\.data\)\.length > 0/.test(load),
    'and "the device holds this log" still means it holds CONTENT — an empty '
    + 'draft must not hydrate a blank form over a real record');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
  console.log('ALL PASSED');
})();
