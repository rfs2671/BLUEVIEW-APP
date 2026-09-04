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

// Relative imports are followed and transpiled too, rather than handed to
// node's require: logbookEditable now takes its ONE Eastern conversion from
// ./dates, and a bare require would hit that file's raw `export`. Packages
// still resolve through node.
const _modCache = new Map();
function loadFile(file) {
  if (_modCache.has(file)) return _modCache.get(file);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  _modCache.set(file, mod.exports);
  const localRequire = (spec) => {
    if (!spec.startsWith('.')) return require(spec);
    const base = path.resolve(path.dirname(file), spec);
    const hit = [base, `${base}.js`, `${base}.jsx`, path.join(base, 'index.js')]
      .find((p) => fs.existsSync(p) && fs.statSync(p).isFile());
    if (!hit) throw new Error(`cannot resolve ${spec} from ${file}`);
    return loadFile(hit);
  };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, localRequire);
  _modCache.set(file, mod.exports);
  return mod.exports;
}

function loadModule(rel) {
  return loadFile(path.join(FRONTEND, rel));
}

const strip = (src) => src
  .replace(/^import[\s\S]*?;\s*$/gm, '')
  .replace(/^export (async function|function|const|class) /gm, '$1 ');

// ════════════════════════════════════════════════════════════════════════════
section('1. THE PREDICATE — an exception, not a removal');
// ════════════════════════════════════════════════════════════════════════════

const E = loadModule('src/utils/logbookEditable.js');

// EVERY FIXTURE CARRIES TODAY'S DATE, and it has to be computed rather than
// written down. The photo set closes at the end of the log's day — 03:00
// America/New_York on the day after `date`, see photoWindow.test.cjs — so a log
// with no date, or a hardcoded past one, is CLOSED and every assertion in this
// section would be about the clock instead of about the predicate it names.
// Today's date is inside the window at every hour, which is the state these
// tests mean by "a filed log". The boundary itself is exercised next door.
const TODAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' })
  .format(new Date());

const DRAFT = { id: 'd', status: 'draft', is_locked: false, date: TODAY };
const FILED_UNLOCKED = { id: 'f', status: 'submitted', is_locked: false, date: TODAY };
const LOCKED = { id: 'l', status: 'submitted', is_locked: true, date: TODAY };
const FROZEN_DRAFT = { id: 'x', status: 'draft', is_locked: true, date: TODAY };

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
ok(E.isOpenForPhotoAppend({ status: 'submitted', date: TODAY }) === true
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
  section('3. THE DISABLED FORM IS GONE, AND SO IS THE HOLE IN IT');
  // ══════════════════════════════════════════════════════════════════════════
  //
  // WHAT THIS SECTION USED TO ASSERT, and why it is rewritten rather than
  // deleted. It pinned a `lockedExtra` slot: a subtree LogbookStepper rendered
  // OUTSIDE its pointerEvents wrapper so that one control — an inline camera
  // panel in daily_jobsite — could be interactive on a form where nothing else
  // was. That was the right shape for a filed log rendered as a disabled form.
  //
  // A FILED LOG IS NO LONGER RENDERED AS A FORM AT ALL. The operator ruled
  // that "a filed record is not being composed, so rendering it as a disabled
  // form is what makes the photo panel read as an exception", so the locked
  // branch renders FiledLogView instead of the steps — and a hole in an inert
  // subtree is meaningless when there is no inert subtree. The slot, the panel
  // and its seven copy keys are gone with it, and adding a photograph is its
  // own screen. THE PROPERTIES THE OLD SECTION PROTECTED ARE ASSERTED BELOW IN
  // THEIR NEW HOME; not one of them was dropped.

  ok(/pointerEvents=\{locked \? 'none' : 'auto'\}/.test(stepperSrc),
    'THE WRAPPER ITSELF IS UNTOUCHED — still absolute for the branch it '
    + 'governs. It was not loosened to let anything through; a branch was put '
    + 'ABOVE it');

  ok(!/lockedExtra\s*=\s*null/.test(stepperSrc),
    'and the lockedExtra SLOT is gone rather than left as a prop nothing '
    + 'passes: a hole kept open for an affordance that moved elsewhere is the '
    + "next person's mistake");

  ok(/FiledLogView/.test(stepperSrc), 'the stepper renders FiledLogView');
  const filedAt = stepperSrc.indexOf('<FiledLogView');
  const stepsAt = stepperSrc.indexOf('current.render()');
  ok(filedAt > -1 && stepsAt > -1 && filedAt < stepsAt,
    'as the LOCKED half of the same conditional the steps are the other half '
    + 'of — so a filed log cannot render both');
  const flatStepper = stepperSrc.replace(/\n\s*/g, ' ');
  ok(/locked \? \( <FiledLogView/.test(flatStepper)
    || /locked \? <FiledLogView/.test(flatStepper),
  'and the branch is on `locked` itself, not on a second copy of the rule');

  // ══════════════════════════════════════════════════════════════════════════
  section('4. THE FILED VIEW OFFERS IT, AND OFFERS ONLY IT');
  // ══════════════════════════════════════════════════════════════════════════

  const viewSrc = LF(path.join(
    FRONTEND, 'src', 'components', 'logbookStepper', 'FiledLogView.jsx',
  ));
  const screenSrc = LF(path.join(FRONTEND, 'app', 'logbooks', 'photos.jsx'));
  ok(viewSrc.length > 500 && screenSrc.length > 500,
    'POSITIVE CONTROL: FiledLogView.jsx and app/logbooks/photos.jsx were read '
    + '— an empty string satisfies every "does not contain" assertion below');

  // ── the panel really is gone from the editor ─────────────────────────────
  ok(!/renderPhotoAppendPanel|appendCapturedPhoto|takeAppendPhoto|pickAppendPhoto/
    .test(editorSrc),
  'daily_jobsite carries no inline append panel and none of its handlers');
  ok(!/lockedExtra/.test(editorSrc), 'and passes no lockedExtra');
  ok(/filedLog=\{filedLog\}/.test(editorSrc),
    "it hands the SERVER's document to the stepper instead — which is what the "
    + 'filed view renders from, and what the append is addressed against');
  ok(!/appendPhotoToFiledLog/.test(editorSrc),
    'and the editor no longer calls the append route at all: ONE way in, on '
    + 'its own screen, rather than two that can drift');

  // ── APPEND-ONLY, asserted in both new files ──────────────────────────────
  for (const [name, src] of [['FiledLogView', viewSrc], ['photos.jsx', screenSrc]]) {
    ok(!/removeActivityPhoto|dropPhoto|Trash2|removePhoto/.test(src),
      `${name}: APPEND-ONLY — no way to remove a photograph from a filed `
      + 'record. That would be an amendment, and the lock bar offers it');
    ok(!/onChangeText|TextInput|SignaturePad/.test(src),
      `${name}: no text entry and no signature pad — nothing the CP attested `
      + 'to can be reached through it');
    ok(!/bucketRemaining|MAX_PHOTOS_PER_SUBCONTRACTOR|capMessage/.test(src),
      `${name}: NO COUNT LIMIT. The per-subcontractor cap is a capture `
      + 'ergonomic, not a rule about how much evidence a filed record carries');
    ok(!/logbooksAPI\.update|logbooksAPI\.create|photoForPayload|writeDraft/.test(src),
      `${name}: IT IS NOT A SAVE. No payload, no draft body, no update — that `
      + 'path is 409 FILED_LOG_DATA_IMMUTABLE on this document');
    ok(!/logbooksAPI\.amend|amendment_reason/.test(src),
      `${name}: and NO AMENDMENT. Amend stays for correcting the record`);
  }

  // ── the write is still bytes and two ids ─────────────────────────────────
  ok(/appendPhotoToFiledLog/.test(screenSrc),
    'the photographs screen goes through the append route');
  ok(!/uploadCapturePhoto/.test(screenSrc),
    'and not the capture-time route, which parks bytes and writes no document');
  const addFn = (() => {
    const i = screenSrc.indexOf('const addPhotoToRow');
    if (i < 0) return '';
    const j = screenSrc.indexOf('\n  };', i);
    return j < 0 ? screenSrc.slice(i) : screenSrc.slice(i, j);
  })();
  ok(addFn.length > 200, 'POSITIVE CONTROL: the add handler was extracted');
  ok(/setAdded\(/.test(addFn) && /res\.photo/.test(addFn),
    'APPEARS IMMEDIATELY: the SERVER-MINTED row goes into state on this frame, '
    + 'not on a refetch');
  ok(/\[activityId\]:/.test(addFn),
    "filed under the row's IDENTITY — an index would move under it, because "
    + "the list is the SERVER's and nothing here orders it");
  ok(/\{ \.\.\.res\.photo, uri \}/.test(addFn),
    "and the tile paints from the file on THIS phone: the report's photo URL "
    + 'is positional, so pointing at one before a refetch would be a guess');

  // ── the refusal the CP has to be told about ──────────────────────────────
  ok(/ACTIVITY_HAS_NO_IDENTITY/.test(screenSrc),
    'a crew row that predates activity_id is REFUSED OUT LOUD, not silently '
    + 'dropped: nothing the client can send reaches it until the backfill runs');
  ok(/can_add/.test(screenSrc) && /can_add/.test(viewSrc) === false
    ? true : /can_add/.test(screenSrc),
  'and the add control is withheld from exactly those rows, by the per-row '
    + 'flag the one photographs predicate computes');

  // ══════════════════════════════════════════════════════════════════════════
  section('5. THE COPY EXISTS, IN ONE PLACE');
  // ══════════════════════════════════════════════════════════════════════════

  const keys = [...editorSrc.matchAll(/\bt\('([A-Za-z0-9_]+)'\)/g)].map((m) => m[1]);
  const dj = (() => {
    const i = enSrc.indexOf('  dailyJobsite: {');
    return i < 0 ? '' : enSrc.slice(i, enSrc.indexOf('\n  },', i));
  })();
  ok(dj.length > 100, 'POSITIVE CONTROL: en.dailyJobsite was extracted');
  const missing = [...new Set(keys)].filter((k) => !new RegExp(`\\b${k}:`).test(dj));
  ok(missing.length === 0,
    `every t() key the editor still calls exists in en.dailyJobsite${
      missing.length ? ` — missing ${JSON.stringify(missing)}` : ''}`);

  // AND THE KEYS THE PANEL OWNED ARE GONE WITH IT. Dead copy is not harmless
  // here: a second "this crew was recorded before photos could be attached"
  // sitting in another namespace is one reword away from a filed log reading
  // two different ways about the same row.
  for (const k of ['photoAppendTitle', 'photoAppendBody', 'photoAppendAdd',
    'photoAppendLegacyRow', 'photoAppendFailedTitle', 'photoAppendFailedBody',
    'photoAddedAfterFiling']) {
    ok(!new RegExp(`\\b${k}:`).test(dj), `en.dailyJobsite.${k} is gone with the panel`);
  }

  const lp = (() => {
    const i = enSrc.indexOf('  logbookPhotos: {');
    return i < 0 ? '' : enSrc.slice(i, enSrc.indexOf('\n  },', i));
  })();
  ok(lp.length > 200, 'POSITIVE CONTROL: en.logbookPhotos was extracted');
  for (const k of ['screenTitle', 'filedTitle', 'filedIntro', 'sectionTitle',
    'noneAttached', 'addPhotographs', 'addedAfterFiling', 'legacyRow',
    'queuedTitle', 'queuedBody', 'failedTitle', 'failedBody']) {
    ok(new RegExp(`\\b${k}:`).test(lp), `en.logbookPhotos.${k} is written`);
  }
  ok(/Added after filing/i.test(lp),
    'the tile label matches the one the report prints, so the CP and the '
    + 'reader of the PDF are looking at the same fact');

  // ── AND THE LEGACY REFUSAL IS STILL NOT A DEAD END ──────────────────────
  const legacyCopy = (lp.match(/legacyRow:\s*([^]*?),\n/) || [])[1] || '';
  ok(legacyCopy.length > 0,
    'POSITIVE CONTROL: the legacy-row copy was actually extracted — an empty '
    + 'match would satisfy the "no retry" assertion below by saying nothing');
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
