/**
 * A PHOTOGRAPH TAKEN IN A CELLAR — the offline half.
 *
 * THE RULING, and it is why this is not a follow-up: photographs are taken in
 * cellars, and a screen that only works online is the wrong shape for the only
 * place photographs come from. A photo that fails silently because there was
 * no signal is the same defect class as everything else this codebase has been
 * bitten by.
 *
 * THE CAUTIONARY TALE THIS FILE IS WRITTEN AGAINST is `sendPendingSignatures`:
 * it existed, it was correct, and NOTHING EVER CALLED IT, so nothing ever
 * drained. A test that calls the drain directly proves the body and leaves the
 * entire question open. So the WIRING is asserted here — the setup function is
 * EXECUTED against a fake NetInfo and a fake AppState and the drain is counted
 * — and app/_layout.jsx is read to confirm the setup itself is invoked.
 *
 * FOUR PROPERTIES, all of them load-bearing:
 *
 *   queue on unreachable-or-5xx ONLY   a 4xx names this photo; replaying a
 *                                      refusal never succeeds
 *   never claim it was FILED            the true sentence is about the DEVICE:
 *                                      held here, will upload. toast.warning.
 *   the drain is INVOKED                reconnect, foreground, and startup
 *   it survives an app restart          it is in AsyncStorage, not in state
 *
 * AND IDEMPOTENCY IS THE SERVER'S, NOT A SECOND MECHANISM. The R2 key is a
 * pure function of (project, activity, photo) and the document write carries an
 * $elemMatch precondition, so a replayed upload cannot double-post — PROVIDED
 * the photo id is minted ONCE, at queue time, and reused on every replay. That
 * is the client's only obligation and it is asserted below.
 *
 *   node frontend/src/utils/filedPhotoQueue.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}
function section(t) {
  console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 62 - t.length))}`);
}

const LF = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');
const strip = (src) => src
  .replace(/^import[\s\S]*?;\s*$/gm, '')
  .replace(/^export (async function|function|const|class) /gm, '$1 ')
  // `export default foo;` re-declares nothing and is not valid inside the
  // harness's function body — dropped rather than rewritten.
  .replace(/^export default .*;\s*$/gm, '');

const queueSrc = LF(path.join(UTILS, 'filedPhotoQueue.js'));

/**
 * ONE FAKE DEVICE. `store` is the AsyncStorage backing map and it is handed in
 * rather than created here, which is what makes the app-restart test possible:
 * the module is thrown away and rebuilt over the SAME store, exactly as a cold
 * launch rebuilds it over the same disk.
 */
function loadQueue({ store = new Map(), append, offlineNet = false } = {}) {
  const calls = [];
  const netListeners = [];
  const appListeners = [];
  const env = {
    AsyncStorage: {
      getItem: async (k) => (store.has(k) ? store.get(k) : null),
      setItem: async (k, v) => { store.set(k, v); },
      removeItem: async (k) => { store.delete(k); },
    },
    NetInfo: {
      fetch: async () => ({ isConnected: !offlineNet, isInternetReachable: !offlineNet }),
      addEventListener: (fn) => { netListeners.push(fn); return () => {}; },
    },
    AppState: {
      currentState: 'active',
      addEventListener: (_ev, fn) => { appListeners.push(fn); return { remove: () => {} }; },
    },
    appendPhotoToFiledLog: async (args) => {
      calls.push(args);
      if (!append) return { photo: { photo_id: args.photoId }, activity_index: 0, photo_index: 0 };
      return append(args, calls.length);
    },
    isOfflineError: (e) => Boolean(e && !e.response),
  };
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const NetInfo = __env.NetInfo;
    const AppState = __env.AppState;
    const appendPhotoToFiledLog = __env.appendPhotoToFiledLog;
    const isOfflineError = __env.isOfflineError;
    ${strip(queueSrc)}
    return {
      shouldQueueError, queueFiledPhoto, getQueuedFiledPhotos,
      clearQueuedFiledPhoto, drainFiledPhotoQueue, setupFiledPhotoAutoDrain,
      getRejectedFiledPhotos, clearRejectedFiledPhoto,
    };
  `)(env);
  return {
    ...mod, calls, store, netListeners, appListeners,
    fireNet: (online) => Promise.all(netListeners.map(
      (fn) => fn({ isConnected: online, isInternetReachable: online }))),
    fireApp: (state) => Promise.all(appListeners.map((fn) => fn(state))),
  };
}

const err = (status) => {
  const e = new Error(`status ${status}`);
  e.response = { status };
  return e;
};
const netErr = () => new Error('Network Error'); // no `response` -> offline

const PHOTO = {
  logbookId: 'lb1', activityId: 'act_1', photoId: 'cap_1',
  uri: 'file:///docs/logbook_photos/cap_1.jpg',
};

(async () => {
  // ══════════════════════════════════════════════════════════════════════════
  section('1. WHAT IS QUEUED, AND WHAT IS NOT');
  // ══════════════════════════════════════════════════════════════════════════

  {
    const Q = loadQueue();
    ok(typeof Q.shouldQueueError === 'function',
      'the rule is a NAMED predicate, so the screen and the drain cannot '
      + 'disagree about what "try again later" means');

    ok(Q.shouldQueueError(netErr()) === true,
      'UNREACHABLE is queued: nothing is wrong with the photograph');
    for (const s of [500, 502, 503, 504]) {
      ok(Q.shouldQueueError(err(s)) === true, `a ${s} is queued — storage is down, not the photo`);
    }
    for (const s of [400, 401, 403, 404, 409, 413, 422]) {
      ok(Q.shouldQueueError(err(s)) === false,
        `a ${s} is NOT queued: replaying a refusal never succeeds, and a queue `
        + 'that holds one retries it forever');
    }
    // POSITIVE CONTROL: a predicate stuck on `true` would pass every line
    // above except these, and a predicate stuck on `false` every line below.
    ok(Q.shouldQueueError(err(500)) === true && Q.shouldQueueError(err(409)) === false,
      'POSITIVE CONTROL: the predicate genuinely separates the two families');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('2. IT SURVIVES AN APP RESTART');
  // ══════════════════════════════════════════════════════════════════════════

  const disk = new Map();
  {
    const Q = loadQueue({ store: disk });
    await Q.queueFiledPhoto(PHOTO);
    const held = await Q.getQueuedFiledPhotos('lb1');
    ok(held.length === 1 && held[0]?.photoId === 'cap_1',
      'a queued photograph is readable back');
    ok(disk.size > 0,
      'and it is on the DEVICE, not in React state — this is the whole '
      + 'guarantee: the CP walks out of the cellar and the app has been killed');
  }
  {
    // A COLD LAUNCH. New module, new module-scope state, same disk.
    const Q2 = loadQueue({ store: disk });
    const held = await Q2.getQueuedFiledPhotos('lb1');
    ok(held.length === 1 && held[0]?.uri === PHOTO.uri,
      'AFTER A RESTART it is still there, with the persistent documentDirectory '
      + 'uri it was queued with — a cache uri would have been evicted');
    ok(held[0]?.photoId === 'cap_1',
      'AND THE SAME PHOTO ID. Minting a new one on replay is exactly how the '
      + 'server\'s R2-key idempotency would be defeated: a different id is a '
      + 'different key, and the record would carry two tiles of one photograph');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('3. THE DRAIN');
  // ══════════════════════════════════════════════════════════════════════════

  {
    const d = new Map();
    const Q = loadQueue({ store: d });
    await Q.queueFiledPhoto(PHOTO);
    await Q.queueFiledPhoto({ ...PHOTO, photoId: 'cap_2' });
    const out = await Q.drainFiledPhotoQueue();
    ok(out.uploaded === 2 && out.remaining === 0, 'both queued photographs go up');
    ok(Q.calls.length === 2
      && Q.calls[0]?.logbookId === 'lb1' && Q.calls[0]?.activityId === 'act_1'
      && Q.calls[0]?.photoId === 'cap_1',
    'through appendPhotoToFiledLog, addressed by logbook + row + photo id');
    ok((await Q.getQueuedFiledPhotos()).length === 0, 'and the queue is emptied');
  }

  {
    // OFFLINE MID-DRAIN: stop, keep everything, claim nothing.
    const d = new Map();
    const Q = loadQueue({ store: d, append: async () => { throw netErr(); } });
    await Q.queueFiledPhoto(PHOTO);
    await Q.queueFiledPhoto({ ...PHOTO, photoId: 'cap_2' });
    const out = await Q.drainFiledPhotoQueue();
    ok(out.uploaded === 0 && out.remaining === 2,
      'still unreachable: nothing uploaded, nothing dropped');
    ok(Q.calls.length === 1,
      'AND IT STOPPED AFTER ONE. There is one network — ninety-nine more '
      + 'attempts fail identically, and would do it on the CP\'s battery');
    ok((await Q.getQueuedFiledPhotos()).length === 2, 'both are still held');
  }

  {
    // A 4xx IN THE DRAIN: dropped from the queue, and REPORTED — a photo that
    // silently vanishes is the failure this whole feature exists to prevent.
    const d = new Map();
    const Q = loadQueue({ store: d, append: async () => { throw err(409); } });
    await Q.queueFiledPhoto(PHOTO);
    const out = await Q.drainFiledPhotoQueue();
    ok(out.rejected === 1 && out.remaining === 0,
      'a refused photograph leaves the queue rather than retrying forever');
    const rej = await Q.getRejectedFiledPhotos('lb1');
    ok(rej.length === 1 && rej[0]?.photoId === 'cap_1',
      'and it is RECORDED as refused, so the screen can say so. Dropping it '
      + 'silently would be the app losing evidence without telling anyone');
  }

  {
    // IDEMPOTENCY IS THE SERVER'S. A replay sends the SAME triple.
    const d = new Map();
    let first = true;
    const Q = loadQueue({
      store: d,
      append: async (args) => {
        if (first) { first = false; throw netErr(); }
        return { photo: { photo_id: args.photoId } };
      },
    });
    await Q.queueFiledPhoto(PHOTO);
    await Q.drainFiledPhotoQueue();          // fails, stays queued
    await Q.drainFiledPhotoQueue();          // replays, lands
    ok(Q.calls.length === 2
      && Q.calls[0]?.photoId === Q.calls[1]?.photoId
      && Q.calls[0]?.activityId === Q.calls[1]?.activityId
      && Q.calls[0]?.logbookId === Q.calls[1]?.logbookId,
    'THE REPLAY IS BYTE-FOR-BYTE THE SAME REQUEST. The R2 key is a pure '
      + 'function of those three ids, so the retry overwrites its own object '
      + 'instead of orphaning one');
    ok((await Q.getQueuedFiledPhotos()).length === 0, 'and it clears on success');
  }

  // No SECOND idempotency mechanism was invented on the client.
  // NO SECOND MECHANISM, asked as what it actually means rather than as a
  // word ban: the client neither hashes anything nor MINTS AN ID in the drain.
  // A re-minted id is a different R2 key, which is precisely how the server's
  // idempotency would be defeated by a client trying to help.
  ok(!/crypto|createHash|checksum|md5|sha1|sha256/i.test(queueSrc),
    'the client computes no digest of its own — the server already has two '
    + 'mechanisms (the R2 key and the $elemMatch precondition) and a third '
    + 'would be a thing to keep in agreement with them');
  const drainBody = (() => {
    const i = queueSrc.indexOf('export async function drainFiledPhotoQueue');
    const j = queueSrc.indexOf('\nexport function setupFiledPhotoAutoDrain', i);
    return i < 0 ? '' : queueSrc.slice(i, j < 0 ? undefined : j);
  })();
  ok(drainBody.length > 400, 'POSITIVE CONTROL: the drain body was extracted');
  ok(!/Math\.random|Date\.now\(\)\.toString|newPhotoId/.test(drainBody),
    'AND THE DRAIN MINTS NOTHING. It replays the ids the queue holds, which is '
    + 'the client\'s entire share of the idempotency contract');
  const serverSrc = LF(path.join(REPO, 'backend', 'server.py'));
  ok(/photos\.original_r2_key.*\$ne.*r2_key/s.test(
    serverSrc.slice(serverSrc.indexOf('async def append_activity_photo'),
      serverSrc.indexOf('async def append_activity_photo') + 9000)),
  'VERIFIED, NOT ASSUMED: the append route\'s update carries the $elemMatch '
    + 'precondition that refuses a photo already on the row');
  ok(/_logbook_capture_photo_r2_key\(project_id, activity_id, photo_id\)/.test(serverSrc),
    'and the R2 key is a pure function of (project, activity, photo)');

  // ══════════════════════════════════════════════════════════════════════════
  section('4. THE DRAIN IS INVOKED — the sendPendingSignatures lesson');
  // ══════════════════════════════════════════════════════════════════════════

  {
    const d = new Map();
    const Q = loadQueue({ store: d });
    await Q.queueFiledPhoto(PHOTO);

    const stop = Q.setupFiledPhotoAutoDrain();
    await new Promise((r) => setTimeout(r, 0));
    ok(Q.calls.length === 1,
      'AT STARTUP: the app may have been killed with a photograph held. '
      + 'Setting up a listener and waiting for a transition that already '
      + 'happened is how a queue stays full forever');

    ok(Q.netListeners.length === 1, 'it subscribes to NetInfo');
    ok(Q.appListeners.length === 1, 'and to AppState');

    // ON RECONNECT — and only on the TRANSITION, not on every event.
    await Q.queueFiledPhoto({ ...PHOTO, photoId: 'cap_3' });
    await Q.fireNet(true);
    await new Promise((r) => setTimeout(r, 0));
    const afterSameState = Q.calls.length;
    ok(afterSameState === 1,
      'an online->online event is not a reconnect and drains nothing');
    await Q.fireNet(false);
    await Q.fireNet(true);
    await new Promise((r) => setTimeout(r, 0));
    ok(Q.calls.length > afterSameState,
      'ON RECONNECT: offline -> online drains. This is the cellar case — he '
      + 'walks up the stairs and the photograph goes');

    // ON FOREGROUND.
    const beforeFg = Q.calls.length;
    await Q.queueFiledPhoto({ ...PHOTO, photoId: 'cap_4' });
    await Q.fireApp('background');
    await Q.fireApp('active');
    await new Promise((r) => setTimeout(r, 0));
    ok(Q.calls.length > beforeFg,
      'ON FOREGROUND: the phone was in his pocket with the screen off and the '
      + 'radio asleep; NetInfo may never report a transition at all');

    ok(typeof stop === 'function', 'and it hands back an unsubscribe');
    stop();
  }

  // AND THE SETUP IS ITSELF CALLED. The drain can be perfect and unreached.
  const layoutSrc = LF(path.join(FRONTEND, 'app', '_layout.jsx'));
  ok(/setupFiledPhotoAutoDrain/.test(layoutSrc),
    'app/_layout.jsx CALLS setupFiledPhotoAutoDrain — this is the exact line '
    + 'sendPendingSignatures never had');
  ok(/import \{ setupFiledPhotoAutoDrain \} from '\.\.\/src\/utils\/filedPhotoQueue'/
    .test(layoutSrc),
  'and imports it from the queue module');
  const effect = (() => {
    // lastIndexOf, not indexOf: the FIRST occurrence is the import at the top
    // of the file, and a window around that contains no useEffect at all — a
    // check that reads the wrong region and returns a well-formed "no" is the
    // exact failure shape this repo keeps hitting.
    const i = layoutSrc.lastIndexOf('setupFiledPhotoAutoDrain');
    return layoutSrc.slice(Math.max(0, i - 500), i + 300);
  })();
  ok(/useEffect\(/.test(effect) && /return \(\) =>/.test(effect),
    'inside a useEffect that unsubscribes — a listener per hot reload is a '
    + 'drain per hot reload');
  // POSITIVE CONTROL on the source read itself.
  ok(/setupDraftAutoSync/.test(layoutSrc),
    'POSITIVE CONTROL: _layout.jsx really was read (its existing draft drain '
    + 'is still there) — a bad path would have thrown, but an empty string '
    + 'would have failed the assertions above for the wrong reason');

  // ══════════════════════════════════════════════════════════════════════════
  section('5. THE SCREEN NEVER SAYS "FILED" WHEN IT MEANS "HELD"');
  // ══════════════════════════════════════════════════════════════════════════

  const screenSrc = LF(path.join(FRONTEND, 'app', 'logbooks', 'photos.jsx'));
  ok(screenSrc.length > 500, 'POSITIVE CONTROL: app/logbooks/photos.jsx was read');

  const addFn = (() => {
    const i = screenSrc.indexOf('const addPhotoToRow');
    if (i < 0) return '';
    const j = screenSrc.indexOf('\n  };', i);
    return j < 0 ? screenSrc.slice(i) : screenSrc.slice(i, j);
  })();
  ok(addFn.length > 200, 'POSITIVE CONTROL: the add handler was extracted');

  ok(/shouldQueueError/.test(addFn) && /queueFiledPhoto/.test(addFn),
    'the screen queues through the SAME named predicate the drain uses');
  ok(/toast\.warning\(/.test(addFn),
    'a queued photograph is reported with toast.WARNING');
  const queuedBranch = addFn.slice(addFn.indexOf('shouldQueueError'));
  ok(!/toast\.success/.test(queuedBranch),
    'and NEVER toast.success on that branch: "added to the log" is a claim '
    + 'about the RECORD, and the record has not changed');

  const en = LF(path.join(FRONTEND, 'src', 'i18n', 'en.js'));
  const ns = (() => {
    const i = en.indexOf('  logbookPhotos: {');
    return i < 0 ? '' : en.slice(i, en.indexOf('\n  },', i));
  })();
  ok(ns.length > 100, 'POSITIVE CONTROL: en.logbookPhotos was extracted');
  const queuedCopy = (ns.match(/queuedBody:\s*([\s\S]*?),\n/) || [])[1] || '';
  ok(queuedCopy.length > 0, 'POSITIVE CONTROL: the queued sentence was extracted');
  ok(/this (device|phone)|on this device/i.test(queuedCopy),
    'the sentence is about the DEVICE — held here — which is the only true '
    + 'thing that can be said while the server has never seen it');
  ok(!/added to the log|on the record|filed/i.test(queuedCopy),
    'and it never says the photograph is on the record');
  ok(/upload/i.test(queuedCopy),
    'and it says what will happen next, so it is not a dead end');

  // ══════════════════════════════════════════════════════════════════════════
  section('6. THE SCREEN READS THE SERVER\'S COPY, AND BOTH TYPES REACH IT');
  // ══════════════════════════════════════════════════════════════════════════

  ok(/logbooksAPI\.getById/.test(screenSrc),
    'the screen fetches the SERVER\'s document by logbook id');
  ok(/photographsSection/.test(screenSrc),
    'and derives its rows through the one photographs predicate — not from '
    + 'reconciled local state, where withActivityIds has minted ids the server '
    + 'has never seen and a photo aimed at one reaches nothing');
  ok(!/withActivityIds|activitiesRef|setActivities/.test(screenSrc),
    'it touches none of the editor\'s reconciled activity state');
  ok(!/\bLogbookStepper\b|StepHeaderBase|renderStep\d|onStepChange/.test(screenSrc),
    'NO STEPPER: adding a photograph is not editing a log, and it must not '
    + 'walk the CP through a five-step form he cannot edit');
  ok(!/logbooksAPI\.amend|amendment_reason/.test(screenSrc),
    'and NO AMENDMENT: amend stays for correcting the record');

  // A DRAFT REACHED BY URL IS REFUSED, and by the shared predicate. The append
  // route writes straight into the stored document, so a photograph put on a
  // DRAFT this way is overwritten by that editor's own next PUT — it appears,
  // and then quietly stops existing. A deep link, a back-stack entry and a
  // typed URL all reach this screen; only the entry points are filtered.
  ok(/isOpenForPhotoAppend/.test(screenSrc),
    'the screen refuses a log that is still OPEN, asking the shared predicate '
    + 'rather than re-deriving the rule from `status` as a second copy');
  ok(/notFiledTitle/.test(screenSrc) && /notFiledTitle:/.test(ns),
    'and says so in words that send him to the camera in the log itself, '
    + 'which is the way in on an open log');

  // fall_protection was the type the endpoint was DEAD on.
  const fpSrc = LF(path.join(FRONTEND, 'app', 'logbooks', 'fall_protection.jsx'));
  ok(fpSrc.length > 1000, 'POSITIVE CONTROL: fall_protection.jsx was read');
  const view = LF(path.join(
    FRONTEND, 'src', 'components', 'logbookStepper', 'FiledLogView.jsx',
  ));
  ok(/\/logbooks\/photos/.test(view),
    'the FILED VIEW — which fall_protection renders through LogbookStepper '
    + 'exactly as daily_jobsite does — routes to the photographs screen, so '
    + 'the endpoint is reachable on BOTH types from one wiring');
  const dj = LF(path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx'));
  ok(/LogbookStepper/.test(dj) && /LogbookStepper/.test(fpSrc),
    'and both editors render that stepper — which is what makes it one wiring '
    + 'rather than two that can drift');

  // The list screen offers it directly on a filed row.
  const listSrc = LF(path.join(FRONTEND, 'app', 'logbooks', 'index.jsx'));
  ok(/\/logbooks\/photos\?logbookId=/.test(listSrc),
    'the CP\'s logbook list offers the photographs screen DIRECTLY on a filed '
    + 'row — every other route on that screen goes to the editor');
  ok(/typeCarriesActivityPhotos/.test(listSrc),
    'and only for a type that can carry photographs, by the same schema rule');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
