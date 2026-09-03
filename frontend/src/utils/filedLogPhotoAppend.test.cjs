/**
 * A PHOTOGRAPH MAY BE ADDED TO A FILED LOG — the device half.
 *
 * THE RULING. Photographs are not DOB-required daily log content, so treating
 * a photo addition as an amendment to a filed compliance record is wrong on
 * the merits. Append-only, no reason asked, no count limit, visible
 * immediately, and anyone who can already see the log may add one. The
 * statutory content he attested to — crews, headcounts, work performed,
 * weather — does not move.
 *
 * THE CLIENT PROBLEM. `isOpenForEditing` is false the moment a log is
 * submitted, and that is CORRECT: it is the fix for the two daily_jobsite
 * records at 588 Thomas that were silently overwritten by re-entry. `locked`
 * flows into LogbookStepper, which puts pointerEvents='none' over the entire
 * form — "EVERY control below non-interactive — no per-field flags to miss."
 * So the camera is unreachable on exactly the log this feature is for.
 *
 * THE EXCEPTION IS NOT A LOOSENING. The pointerEvents wrapper stays exactly as
 * it is. What is added is a SECOND subtree, rendered OUTSIDE it, that can
 * contain nothing but the photo affordance — so "no per-field flags to miss"
 * remains true by construction rather than by review. That is asserted below,
 * against the real source, in both directions:
 *
 *   the wrapper is untouched                (the guard did not move)
 *   the extra renders outside the wrapper   (or the affordance is dead)
 *   the extra is reachable ONLY when locked (or it is a second editor)
 *
 * AND THE WRITE IT PERFORMS IS NOT A SAVE. It posts image bytes and two ids to
 * POST /api/logbooks/{id}/activity-photo and never touches the draft payload
 * path — no `data`, no photoForPayload, no PUT. If it ever went through the
 * ordinary save the server would answer 409 FILED_LOG_DATA_IMMUTABLE, and on a
 * draft it would clobber the CP's own document.
 *
 *   node frontend/src/utils/filedLogPhotoAppend.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const UTILS = __dirname;
const FRONTEND = path.join(__dirname, '..', '..');
const EDITOR = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const STEPPER = path.join(
  FRONTEND, 'src', 'components', 'logbookStepper', 'LogbookStepper.jsx',
);

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}
function section(t) {
  console.log(`\n── ${t} ${'─'.repeat(Math.max(0, 62 - t.length))}`);
}

const LF = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');
const editorSrc = LF(EDITOR);
const stepperSrc = LF(STEPPER);
const draftsSrc = LF(path.join(UTILS, 'logbookDrafts.js'));
const enSrc = LF(path.join(FRONTEND, 'src', 'i18n', 'en.js'));

function loadModule(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}

const strip = (src) => src
  .replace(/^import[\s\S]*?;\s*$/gm, '')
  .replace(/^export (async function|function|const|class) /gm, '$1 ');

// ════════════════════════════════════════════════════════════════════════════
section('1. THE PREDICATE — an exception, not a removal');
// ════════════════════════════════════════════════════════════════════════════

const E = loadModule('src/utils/logbookEditable.js');

const DRAFT = { id: 'd', status: 'draft', is_locked: false };
const FILED_UNLOCKED = { id: 'f', status: 'submitted', is_locked: false };
const LOCKED = { id: 'l', status: 'submitted', is_locked: true };
const FROZEN_DRAFT = { id: 'x', status: 'draft', is_locked: true };

ok(typeof E.isOpenForPhotoAppend === 'function',
  'logbookEditable exports isOpenForPhotoAppend, beside the rule it excepts');

ok(E.isOpenForPhotoAppend(FILED_UNLOCKED) === true,
  'a filed, not-yet-frozen log accepts an appended photograph');
ok(E.isOpenForPhotoAppend(LOCKED) === true,
  'a finalized log accepts one too — the lock is about his attested content');
ok(E.isOpenForPhotoAppend(FROZEN_DRAFT) === true,
  'a frozen draft is closed to editing, so it is open to the append path');

ok(E.isOpenForPhotoAppend(DRAFT) === false,
  'a DRAFT does not: the ordinary camera is right there, and this route would '
  + 'be overwritten by the editor\'s own next PUT');
ok(E.isOpenForPhotoAppend(null) === false && E.isOpenForPhotoAppend(undefined) === false,
  'nothing is not a log');
ok(E.isOpenForPhotoAppend({ status: 'submitted' }) === true
  && E.isOpenForPhotoAppend('submitted') === false,
  'a non-object is refused rather than coerced');

ok(E.isOpenForEditing(FILED_UNLOCKED) === false
  && E.isOpenForEditing(LOCKED) === false
  && E.isOpenForEditing(DRAFT) === true,
  'THE CONTROL: isOpenForEditing is unchanged — the gate was excepted, not moved');

ok([DRAFT, FILED_UNLOCKED, LOCKED, FROZEN_DRAFT, null].every(
  (l) => !(E.isOpenForEditing(l) && E.isOpenForPhotoAppend(l))),
'the two predicates are never both true: exactly one path is open at a time');

ok(E.chooseEditableLog([LOCKED]).readOnly === true,
  'chooseEditableLog still reports a filed log read-only');

// ════════════════════════════════════════════════════════════════════════════
section('2. THE WRITE — bytes and two ids, never the document');
// ════════════════════════════════════════════════════════════════════════════

function loadDrafts({ post = null } = {}) {
  const posts = [];
  const env = {
    AsyncStorage: { getItem: async () => null, setItem: async () => {} },
    Platform: { OS: 'ios' },
    FileSystem: {
      documentDirectory: 'file:///docs/',
      getInfoAsync: async () => ({ exists: true }),
      makeDirectoryAsync: async () => {},
      copyAsync: async () => {},
    },
    apiClient: {
      post: async (url, form, cfg) => {
        posts.push({ url, form, cfg });
        if (!post) throw new Error('no stub');
        return post(url, form, cfg);
      },
    },
    isOfflineError: (e) => Boolean(e && !e.response && e.offline),
    FormData: class {
      constructor() { this.parts = {}; }

      append(k, v) { this.parts[k] = v; }
    },
    fetch: async () => ({ blob: async () => 'BLOB' }),
  };
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const AsyncStorage = __env.AsyncStorage;
    const Platform = __env.Platform;
    const FileSystem = __env.FileSystem;
    const apiClient = __env.apiClient;
    const isOfflineError = __env.isOfflineError;
    const FormData = __env.FormData;
    const fetch = __env.fetch;
    ${strip(draftsSrc)}
    return { appendPhotoToFiledLog, uploadCapturePhoto, photoNeedsUpload };
  `)(env);
  return { ...mod, posts };
}

const SERVER_ROW = {
  photo_id: 'cap_9', original_r2_key: 'logbook-photos/p1/act_2/cap_9.jpg',
  added_at: '2026-09-01T16:05:00+00:00', added_by: 'cp_1',
  added_by_name: 'Casey CP', added_after_filing: true,
};

(async () => {
  {
    const D = loadDrafts({
      post: async () => ({
        data: {
          original_r2_key: SERVER_ROW.original_r2_key,
          activity_id: 'act_2',
          activity_index: 1,
          photo_index: 3,
          photo: SERVER_ROW,
        },
      }),
    });
    const out = await D.appendPhotoToFiledLog({
      logbookId: 'lb1', activityId: 'act_2', photoId: 'cap_9',
      uri: 'file:///docs/logbook_photos/cap_9.jpg',
    });

    ok(D.posts.length === 1
      && D.posts[0].url === '/api/logbooks/lb1/activity-photo',
    'it posts to the append route, addressed by LOGBOOK id');

    const sent = Object.keys(D.posts[0].form.parts).sort();
    ok(JSON.stringify(sent) === JSON.stringify(['activity_id', 'file', 'photo_id']),
      'THE PAYLOAD IS EXACTLY bytes + two ids — no data blob, no photo object, '
      + `no index (sent: ${JSON.stringify(sent)})`);
    ok(D.posts[0].form.parts.activity_id === 'act_2'
      && D.posts[0].form.parts.photo_id === 'cap_9',
    'the row is named by IDENTITY, which is all the server is given to aim with');

    ok(out && out.photo && out.photo.added_after_filing === true
      && out.photo.original_r2_key === SERVER_ROW.original_r2_key,
    'the SERVER-MINTED row comes back, so nothing on the record is client-shaped');
    ok(out.activity_index === 1 && out.photo_index === 3,
      'and where it landed, so the tile can appear without a refetch');
  }

  {
    const D = loadDrafts();
    for (const bad of [
      { activityId: 'a', photoId: 'p', uri: 'u' },
      { logbookId: 'lb1', photoId: 'p', uri: 'u' },
      { logbookId: 'lb1', activityId: 'a', uri: 'u' },
      { logbookId: 'lb1', activityId: 'a', photoId: 'p' },
    ]) {
      let threw = false;
      try { await D.appendPhotoToFiledLog(bad); } catch (_e) { threw = true; }
      ok(threw, `a call missing ${Object.keys(bad).join('+')} throws before any post`);
    }
    ok(D.posts.length === 0, 'and none of those reached the network');
  }

  {
    const D = loadDrafts({
      post: async () => ({ data: { activity_index: 0, photo_index: 0 } }),
    });
    let threw = null;
    try {
      await D.appendPhotoToFiledLog({
        logbookId: 'lb1', activityId: 'a', photoId: 'p', uri: 'u',
      });
    } catch (e) { threw = e; }
    ok(threw !== null,
      'a 200 with no photo row is a FAILURE: nothing may be shown as filed '
      + 'evidence that the server did not confirm it stored');
  }

  {
    const D = loadDrafts();
    const e = new Error('refused');
    e.response = { status: 409, data: { detail: { code: 'ACTIVITY_HAS_NO_IDENTITY' } } };
    const D2 = loadDrafts({ post: async () => { throw e; } });
    let caught = null;
    try {
      await D2.appendPhotoToFiledLog({
        logbookId: 'lb1', activityId: 'a', photoId: 'p', uri: 'u',
      });
    } catch (err) { caught = err; }
    ok(caught && caught.code === 'ACTIVITY_HAS_NO_IDENTITY',
      'the server\'s refusal CODE survives to the caller — a legacy row must be '
      + 'able to say why, not just fail');
    ok(D.posts.length === 0, '(control: the untouched loader posted nothing)');
  }

  // ══════════════════════════════════════════════════════════════════════════
  section('3. THE GUARD DID NOT MOVE');
  // ══════════════════════════════════════════════════════════════════════════

  ok(/pointerEvents=\{locked \? 'none' : 'auto'\}/.test(stepperSrc),
    'LogbookStepper still puts pointerEvents=none over the WHOLE form when locked');

  const wrapper = stepperSrc.indexOf("pointerEvents={locked ? 'none' : 'auto'}");
  // The RENDER site, not the prop declaration at the top of the signature.
  const extra = stepperSrc.lastIndexOf('lockedExtra');
  const lockBar = stepperSrc.indexOf('<LogbookLockBar');
  ok(stepperSrc.indexOf('lockedExtra') > -1, 'the stepper accepts a lockedExtra slot');
  ok(extra > wrapper && stepperSrc.slice(wrapper, extra).includes('</View>'),
    'lockedExtra renders OUTSIDE the pointerEvents wrapper — the wrapper closes '
    + 'first. Inside it, it would be inert, which is the bug this whole '
    + 'exception exists to avoid');
  ok(extra < lockBar,
    'and above the lock bar, beside the amendment path it is an alternative to');
  ok(/\{locked && !!lockedExtra/.test(stepperSrc)
    || /locked \? lockedExtra/.test(stepperSrc),
  'it is rendered ONLY when locked: on an open log the ordinary camera is the '
    + 'one way in, and two would drift');

  // ══════════════════════════════════════════════════════════════════════════
  section('4. THE READ-ONLY FORM OFFERS IT, AND OFFERS ONLY IT');
  // ══════════════════════════════════════════════════════════════════════════

  ok(/lockedExtra=\{/.test(editorSrc),
    'daily_jobsite passes the panel to the stepper');
  ok(/isOpenForPhotoAppend/.test(editorSrc),
    'and gates it on the named exception, not on a second copy of the rule');

  const panel = (() => {
    const i = editorSrc.indexOf('const renderPhotoAppendPanel');
    if (i < 0) return '';
    const j = editorSrc.indexOf('\n  };', i);
    return j < 0 ? editorSrc.slice(i) : editorSrc.slice(i, j);
  })();
  ok(panel.length > 0, 'the panel is its own render function, so it can be read whole');

  ok(!/removeActivityPhoto|dropPhoto|Trash2|s\.photoRemove/.test(panel),
    'APPEND-ONLY: the panel offers no way to remove a photograph from a filed '
    + 'record — that would be an amendment');
  ok(!/onChangeText|TextInput/.test(panel),
    'and no text entry: nothing the CP attested to can be reached through it');
  ok(!/bucketRemaining|MAX_PHOTOS_PER_SUBCONTRACTOR|capMessage/.test(panel),
    'NO COUNT LIMIT: the per-subcontractor cap is a capture ergonomic, not a '
    + 'rule about how much evidence a filed record may carry');
  ok(!/reason|Reason/.test(panel),
    'and no reason is asked for — a photograph is not an assertion');

  ok(/appendPhotoToFiledLog/.test(editorSrc),
    'the append goes through the append route');
  const appendFn = (() => {
    const i = editorSrc.indexOf('const appendCapturedPhoto');
    if (i < 0) return '';
    const j = editorSrc.indexOf('\n  };', i);
    return j < 0 ? editorSrc.slice(i) : editorSrc.slice(i, j);
  })();
  ok(appendFn.length > 0, 'the append handler is its own function');
  ok(!/photoForPayload|payloadActivities|draftBody|logbooksAPI\.update|handleSave/
    .test(appendFn),
  'IT IS NOT A SAVE. It never builds a payload, never touches the draft body '
    + 'and never calls update — that path is 409 FILED_LOG_DATA_IMMUTABLE');
  ok(/uploadCapturePhoto/.test(editorSrc) && !/uploadCapturePhoto/.test(appendFn),
    'and it does not reuse the capture-time route, which writes no document');

  ok(/added_after_filing/.test(editorSrc),
    'the editor can tell an appended photograph from an original');

  // ── it appears immediately ───────────────────────────────────────────────
  ok(/setAppendedPhotos\(/.test(appendFn) && /res\.photo/.test(appendFn),
    'APPEARS IMMEDIATELY: the server-minted row goes into state on this frame, '
    + 'not on a refetch or a next render');
  ok(/\[activityId\]:/.test(appendFn),
    'and it is filed under the row\'s IDENTITY — an index would move under it, '
    + 'because the panel reads the SERVER\'s list and nothing here orders it');
  ok(/uri: null|uri,/.test(appendFn) && /\{ \.\.\.res\.photo, uri \}/.test(appendFn),
    'the tile paints from the file on THIS phone: the report\'s photo URL is '
    + 'positional and this screen\'s list is not the server\'s, so pointing at '
    + 'one would be a guess');
  ok(!/setActivities\(/.test(appendFn),
    'and the local activities list is NOT rewritten — it is the read-only '
    + 'form\'s view of what the server holds, and this did not change that');

  // ── the refusal the CP has to be told about ──────────────────────────────
  ok(/ACTIVITY_HAS_NO_IDENTITY/.test(editorSrc),
    'a crew row that predates activity_id is REFUSED OUT LOUD, not silently '
    + 'dropped: nothing backfills that field and no retry will ever work');

  // ══════════════════════════════════════════════════════════════════════════
  section('5. THE COPY EXISTS');
  // ══════════════════════════════════════════════════════════════════════════

  const keys = [...editorSrc.matchAll(/\bt\('([A-Za-z0-9_]+)'\)/g)].map((m) => m[1]);
  const dj = (() => {
    const i = enSrc.indexOf('  dailyJobsite: {');
    return i < 0 ? '' : enSrc.slice(i, enSrc.indexOf('\n  },', i));
  })();
  const missing = [...new Set(keys)].filter((k) => !new RegExp(`\\b${k}:`).test(dj));
  ok(missing.length === 0,
    `every t() key the editor calls exists in en.dailyJobsite${
      missing.length ? ` — missing ${JSON.stringify(missing)}` : ''}`);
  for (const k of ['photoAppendTitle', 'photoAppendBody', 'photoAppendAdd',
    'photoAppendLegacyRow', 'photoAppendFailedTitle', 'photoAppendFailedBody',
    'photoAddedAfterFiling']) {
    ok(new RegExp(`\\b${k}:`).test(dj), `en.dailyJobsite.${k} is written`);
  }
  ok(/Added after filing/i.test(dj),
    'the tile label matches the one the report prints, so the CP and the '
    + 'reader of the PDF are looking at the same fact');

  // ── AND THE LEGACY REFUSAL IS NO LONGER A DEAD END ──────────────────────
  //
  // It used to say only that a photo has to go on an amendment. That is true
  // and it is a dead end: an amendment costs the CP a full re-attestation of a
  // record he has already signed, to attach a photograph that is not part of
  // what he signed. backend/scripts/backfill_activity_id.py is the thing that
  // actually resolves it, so the copy has to name a remedy the CP can ask for.
  const legacyCopy = (dj.match(/photoAppendLegacyRow:\s*([\s\S]*?),\n/) || [])[1] || '';
  ok(legacyCopy.length > 0,
    'POSITIVE CONTROL: the legacy-row copy was actually extracted from en.js — '
    + 'an empty match would satisfy the "no retry" assertion below by saying '
    + 'nothing at all');
  ok(/administrator/i.test(legacyCopy),
    'the refusal tells the CP what to actually do: there is a remedy and it is '
    + 'somebody he can ask, not a script name he cannot run');
  ok(/amendment/i.test(legacyCopy),
    '...and keeps the amendment as the fallback rather than dropping it');
  ok(!/try again/i.test(legacyCopy),
    'and STILL never offers a retry — no id the client can send will reach '
    + 'that row until the backfill has run');

  const serverSrc = fs.readFileSync(
    path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  ok(/"remediable": True/.test(serverSrc)
    && /"remedy": "backfill_activity_id"/.test(serverSrc),
    'and the SERVER says it is remediable as a machine fact, so a client can '
    + 'branch on it rather than on English');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
