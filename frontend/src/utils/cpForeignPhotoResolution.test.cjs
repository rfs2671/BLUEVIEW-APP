/**
 * WHAT A CP's PHONE RESOLVES FOR A PHOTO IT DID NOT TAKE.
 *
 * NOT A THEORY. This file executes the SHIPPED resolver — photoTileUri, sliced
 * out of app/logbooks/daily_jobsite.jsx — and prints the exact string the
 * <Image source={{ uri }}> receives, for every shape a stored photo can have,
 * on a device that was not the capturer. It then answers, from the backend's
 * own serving ladder, whether that string can load.
 *
 * The stored shapes are not invented either: each one is produced by running
 * the shipped photoForPayload over a capture-time photo, because that function
 * is the ONLY writer of the photo rows that reach the server document.
 *
 * ── WHAT THE CP's DEVICE ACTUALLY RECEIVES ──────────────────────────────────
 *
 * The CP reads the log through GET /api/logbooks/project/{project_id}
 * (logbooksAPI.getByProject -> daily_jobsite.jsx fetchData). That route calls
 * paginated_query with NO projection argument, so `collection.find(query,
 * None)` returns the WHOLE document. Every photo field survives.
 *
 * That is a DIFFERENT endpoint from the site tablet's, which reads
 * GET /api/logbooks/project/{project_id}/submitted and is the only one that
 * applies SUBMITTED_LOGBOOK_EXCLUDED_FIELDS (server.py:27155), dropping
 * `data.activities.photos.base64`. So the CP receives MORE photo fields than
 * the tablet, never fewer. #357 cannot be starving the CP's tiles.
 *
 * ── THE DECISIVE CASE, AND WHERE `uri` SITS ─────────────────────────────────
 *
 * `uri` is a file:///…/logbook_photos/… path on the capturing phone and is
 * meaningless anywhere else. In the resolver it sits FIRST in one of the two
 * branches — the `!original_r2_key` branch. The question this file answers by
 * execution is whether a foreign file:/// can ever win over a SERVABLE source,
 * and the answer is no, for a structural reason: photoForPayload strips `uri`
 * from the payload exactly when `original_r2_key` exists. A stored row can
 * therefore carry a dead path only in the shapes that have nothing servable —
 * or, for legacy rows written before that strip, alongside an inline copy the
 * onError retry reaches on the second pass.
 *
 * Run:  node src/utils/cpForeignPhotoResolution.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function section(t) { console.log(`\n${t}\n${'─'.repeat(t.length)}`); }

const EDITOR = path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx');
const SERVER = path.join(__dirname, '..', '..', '..', 'backend', 'server.py');
// CRLF-normalised at the boundary. The slice terminators below are '\n);\n'
// shaped, and a Windows checkout (core.autocrlf) hands back '\r\n' — which
// made this file fail to LOAD rather than fail an assertion.
const read = (p) => fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n');
const editorSrc = read(EDITOR);
const serverSrc = read(SERVER);

function sliceDecl(src, name, terminator) {
  const at = src.indexOf(`const ${name} = `);
  if (at < 0) throw new Error(`${name} not found — this test is stale`);
  const end = src.indexOf(terminator, at);
  if (end < 0) throw new Error(`${name}: no terminator`);
  return src.slice(at, end + terminator.length);
}

// The real thing, twice: the writer of the stored row, and the reader of it.
// eslint-disable-next-line no-new-func
const { photoForPayload } = new Function(`
  ${sliceDecl(editorSrc, 'isPurgedPhoto', '\n);\n')}
  ${sliceDecl(editorSrc, 'photoForPayload', '\n};\n')}
  return { photoForPayload };
`)();

const API_BASE = 'https://api.levelog.com';
// getLogbookPhotoUrl, reproduced from src/utils/api.js and pinned to it below.
const logbooksAPI = {
  getLogbookPhotoUrl: (logbookId, ai, pi, variant = 'enhanced', bust = '') => {
    if (!logbookId && logbookId !== 0) return null;
    const q = `?v=${encodeURIComponent(variant)}${bust ? `&t=${encodeURIComponent(bust)}` : ''}`;
    return `${API_BASE}/api/reports/logbook-photo/${encodeURIComponent(logbookId)}/${ai}/${pi}${q}`;
  },
};

// eslint-disable-next-line no-new-func
const makeResolver = new Function('logbooksAPI', 'existingLogId', `
  ${sliceDecl(editorSrc, 'inlinePhotoData', '\n);\n')}
  ${sliceDecl(editorSrc, 'isPurgedPhoto', '\n);\n')}
  ${sliceDecl(editorSrc, 'photoTileUri', '\n  );\n')}
  return photoTileUri;
`);

// The CP has loaded the superintendent's filed log off the server, so the
// screen HAS a backend id. That is the only device state that matters here.
const LOG_ID = '68d2f1a4c9e0b71234abcd01';
const resolveOnCpPhone = makeResolver(logbooksAPI, LOG_ID);
// And the same screen with no server id yet — the local-draft load path,
// where fetchData returns early on `draft.backend_id || null`.
const resolveNoLogId = makeResolver(logbooksAPI, null);

// ── The backend's serving ladder, ported from _logbook_photo_sources ────────
// Pinned to server.py below so it cannot drift silently.
function serverCanServe(storedPhoto, v) {
  if (!storedPhoto || typeof storedPhoto !== 'object') return null;
  const enhanced = storedPhoto.enhanced_r2_key;
  const thumb = storedPhoto.thumb_r2_key;
  const original = storedPhoto.original_r2_key;
  const fullB64 = storedPhoto.base64;
  const thumbB64 = storedPhoto.thumb_base64;
  let order;
  if (v === 'thumb') {
    order = [['r2', thumb], ['r2', enhanced], ['r2', original], ['b64', fullB64], ['b64', thumbB64]];
  } else if (v === 'enhanced') {
    order = [['r2', enhanced], ['r2', thumb], ['r2', original], ['b64', fullB64], ['b64', thumbB64]];
  } else {
    order = [['b64', fullB64], ['r2', original], ['r2', enhanced], ['r2', thumb], ['b64', thumbB64]];
  }
  const first = order.find(([, val]) => val);
  return first ? `${first[0]}:${first[1]}` : null;  // null => the endpoint 404s
}

// ── The shapes, as they are CAPTURED (before photoForPayload) ───────────────
const FILE_ON_THE_SUPERS_PHONE = 'file:///data/user/0/com.levelog.app/files/logbook_photos/cap_7f3a.jpg';
const R2_KEY = 'logbook-photos/proj1/act_1/cap_7f3a.jpg';

const CAPTURED = [
  {
    name: 'A  uploaded at capture (the normal modern photo)',
    photo: { id: 'cap_7f3a', uri: FILE_ON_THE_SUPERS_PHONE, original_r2_key: R2_KEY, upload_pending: false },
  },
  {
    name: 'B  uploaded + enhance pass has run',
    photo: {
      id: 'cap_7f3a', uri: FILE_ON_THE_SUPERS_PHONE, original_r2_key: R2_KEY,
      enhanced_r2_key: `${R2_KEY.slice(0, -4)}-enhanced.jpg`,
      thumb_r2_key: `${R2_KEY.slice(0, -4)}-thumb.jpg`,
      enhance_status: 'done',
    },
  },
  {
    name: 'C  uploaded + enhanced + log FINALIZED (purge ran)',
    photo: {
      id: 'cap_7f3a', uri: FILE_ON_THE_SUPERS_PHONE, original_r2_key: R2_KEY,
      enhanced_r2_key: `${R2_KEY.slice(0, -4)}-enhanced.jpg`,
      thumb_r2_key: `${R2_KEY.slice(0, -4)}-thumb.jpg`,
      enhance_status: 'done', thumb_base64: 'VEhVTUI=', base64_purged_at: '2026-08-31T22:04:00Z',
    },
  },
  {
    name: 'D  UPLOAD NEVER COMPLETED (offline / 5xx / R2 unconfigured)',
    photo: { id: 'cap_7f3a', uri: FILE_ON_THE_SUPERS_PHONE, upload_pending: true },
  },
  {
    name: 'E  UPLOAD REJECTED 4xx (never retried by the drain)',
    photo: { id: 'cap_7f3a', uri: FILE_ON_THE_SUPERS_PHONE, upload_rejected: true },
  },
  {
    name: 'F  legacy inline base64, no uri (pre-R2 record)',
    photo: { base64: 'RlVMTA==' },
  },
  {
    name: 'G  legacy inline base64 WITH the capturer\'s uri still on it',
    photo: { uri: FILE_ON_THE_SUPERS_PHONE, base64: 'RlVMTA==' },
  },
  {
    name: 'H  legacy purged: retained thumbnail only',
    photo: { thumb_base64: 'VEhVTUI=', base64_purged_at: '2026-06-01T00:00:00Z' },
  },
  {
    name: 'I  legacy purged WITH the capturer\'s uri still on it',
    photo: { uri: FILE_ON_THE_SUPERS_PHONE, thumb_base64: 'VEhVTUI=' },
  },
];

const AI = 2;
const PI = 1;

section('THE STORED ROW — what photoForPayload writes to the server document');
const rows = CAPTURED.map((c) => {
  const stored = photoForPayload(c.photo);
  return { ...c, stored };
});
for (const r of rows) {
  console.log(`  ${r.name}`);
  console.log(`      stored: ${r.stored === null ? 'NULL — dropped by .filter(Boolean), the row never reaches the server' : JSON.stringify(r.stored)}`);
}

ok(rows.filter((r) => r.stored && r.stored.original_r2_key).every((r) => r.stored.uri === undefined),
  'DECISIVE: photoForPayload strips `uri` from EVERY row that names an R2 object — '
  + 'a dead foreign path can never sit in front of a servable key in the stored record');
ok(rows.filter((r) => r.stored && r.stored.uri).every((r) => !r.stored.original_r2_key),
  'and every stored row that still carries a file:/// path has NO original_r2_key');

section('THE RESOLVED URL ON A CP PHONE THAT DID NOT TAKE THE PHOTO');
console.log(`  (existingLogId = ${LOG_ID}, activityIndex = ${AI}, photoIndex = ${PI})\n`);

const LOCAL_FILE_IS_ABSENT = 'file:/// — DEAD on this device';
const table = [];
for (const r of rows) {
  if (r.stored === null) {
    table.push({ shape: r.name, first: '(row not stored)', retry: '(row not stored)', verdict: 'NOT ON THE RECORD' });
    continue;
  }
  const first = resolveOnCpPhone(r.stored, AI, PI, undefined);
  const retry = resolveOnCpPhone(r.stored, AI, PI, true);
  const describe = (u) => {
    if (u === undefined) return 'undefined  (blank tile, no request, no onError)';
    if (String(u).startsWith('file://')) return `${u}\n                    ^ ${LOCAL_FILE_IS_ABSENT}`;
    return u;
  };
  const loads = (u) => {
    if (u === undefined) return false;
    if (String(u).startsWith('file://')) return false;          // foreign device
    if (String(u).startsWith('data:')) return true;             // inline, always
    return serverCanServe(r.stored, 'thumb') !== null;          // the served URL
  };
  const firstLoads = loads(first);
  const retryLoads = loads(retry);
  console.log(`  ${r.name}`);
  console.log(`      first render : ${describe(first)}`);
  console.log(`      after onError: ${describe(retry)}`);
  console.log(`      server ladder for ?v=thumb: ${serverCanServe(r.stored, 'thumb') || '404 — no copy left to serve'}`);
  console.log(`      => ${firstLoads ? 'RENDERS' : (retryLoads ? 'RENDERS ON THE onError RETRY' : 'BLANK, PERMANENTLY')}\n`);
  table.push({
    shape: r.name, first, retry,
    verdict: firstLoads ? 'RENDERS' : (retryLoads ? 'RENDERS AFTER RETRY' : 'BLANK'),
  });
}

const served = `${API_BASE}/api/reports/logbook-photo/${LOG_ID}/${AI}/${PI}?v=thumb`;

ok(table[0].first === served, 'A: an uploaded photo resolves to the SERVED url on the FIRST render');
ok(table[1].first === `${served}&t=done`, 'B: an enhanced one adds the enhance_status cache-bust');
ok(table[2].first === `${served}&t=done`, 'C: a finalized one is served too — the retained thumbnail is the ladder\'s last rung, not the tile\'s first');
ok(table[3].first === FILE_ON_THE_SUPERS_PHONE && table[3].retry === served,
  'D: an UN-UPLOADED photo resolves to the capturer\'s dead file path, and the retry to a url the server cannot fill');
ok(table[3].verdict === 'BLANK' && table[4].verdict === 'BLANK',
  'D and E ARE THE ONLY PERMANENTLY BLANK SHAPES, and neither has anything servable behind it');
ok(serverCanServe(rows[3].stored, 'thumb') === null && serverCanServe(rows[4].stored, 'thumb') === null,
  'and the endpoint 404s for both: no r2 key, no base64, no thumb_base64 — the bytes never left the phone');
ok(table[5].verdict === 'RENDERS' && table[7].verdict === 'RENDERS',
  'F and H: a legacy inline copy with no uri renders inline, first try, no network');
ok(table[6].verdict === 'RENDERS AFTER RETRY' && table[8].verdict === 'RENDERS AFTER RETRY',
  'G and I: a legacy row that kept its file:/// path is dead on the first paint and RECOVERS via onError — '
  + 'one wasted paint, not a permanent blank');

section('THE DEVICE STATE THAT LOSES THE SERVED URL ENTIRELY — AND HOW A CP REACHES IT');
//
// THE REPORTED DEFECT, AND IT IS NOT A BRANCH ORDER.
//
// fetchData's local-draft branch sets the id from ONE place —
// `setExistingLogId(draft.backend_id || null)` — and then RETURNS, before any
// logbook is read from the server. daily_jobsite writes `backend_id` in ONE
// place: setDraftBackendId, after THIS DEVICE pushes.
//
// A CP who OPENS the superintendent's filed log has pushed nothing. The
// 800ms autosave writes a draft holding the server's activities and
// `backend_id: null`, and every later open takes the draft branch with
// existingLogId null. getLogbookPhotoUrl returns null without an id, the row
// carries no `uri` (photoForPayload stripped it) and no `base64` (it would
// blow the 16MB ceiling) — so the tile resolves to `undefined`.
//
// `undefined` is worse than a wrong url: no request is issued, so onError
// never fires and the retry built for exactly this cannot run.
{
  const uploaded = rows[0].stored;
  const first = resolveNoLogId(uploaded, AI, PI, undefined);
  const retry = resolveNoLogId(uploaded, AI, PI, true);
  console.log(`      first render : ${first}`);
  console.log(`      after onError: ${retry}`);
  ok(first === undefined && retry === undefined,
    'with existingLogId null an uploaded photo resolves to `undefined` on BOTH passes — '
    + 'no request, no onError, a blank tile forever');

  // So the screen must never sit in that state for a log the server holds.
  // Both load paths have to leave the day's server id behind them.
  const draftBranch = editorSrc.slice(
    editorSrc.indexOf('const draft = await readDraft(_key);'),
    editorSrc.indexOf('const [projectData, roster, headcount, existingLogsRes]'),
  );
  ok(/getByProject\(projectId, 'daily_jobsite', date\)/.test(draftBranch),
    'THE DRAFT BRANCH ASKS THE SERVER FOR THE DAY\'S ROW when the draft names no backend_id — '
    + 'the id, not the content: the draft still wins on content, offline included');
  ok(/setExistingLogId\(/.test(draftBranch.slice(draftBranch.indexOf('getByProject'))),
    'and adopts the id it finds, which is what puts a url back under every tile');
  ok(/setDraftBackendId\(_key, String\(existing\.id \|\| existing\._id\)\)/.test(editorSrc),
    'AND THE SERVER BRANCH BINDS IT TO THE DRAFT — without this the id is known only for the '
    + 'life of the mount, and the autosave 800ms later writes backend_id null all over again');
}

section('THE ACTIVITY INDEX IN THAT URL IS A POSITION, AND IT IS RESOLVED TWICE');
// The served url addresses data.activities[ai].photos[pi] on the SERVER
// document (server.py get_logbook_activity_photo). `ai` comes from the CP
// screen's map index over its RECONCILED activities. If the reconcile moves a
// row, the url names a different activity.
{
  const babel = require('@babel/core');
  const MODEL = path.join(__dirname, 'dailyJobsiteModel.js');
  const { code } = babel.transformSync(read(MODEL), {
    filename: MODEL,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(mod, { exports: mod }, require);
  const { reconcileCrewsWithRoster } = mod;

  const crew = (over) => ({
    crew_id: 'C?', company: 'Arkon', trade: 'concrete', num_workers: '6',
    gate_sourced: true, gate_num_workers: '6', worker_ids: ['w1'], worker_names: ['A'],
    work_description: 'Set forms', work_locations: 'cellar', photos: [], ...over,
  });
  // A worker who badged in with no company. buildCrewsFromRoster puts these
  // LAST when it builds the list — but the CP can add a crew by hand after
  // that, and then a loose row sits in the MIDDLE of the stored document.
  const loose = (over) => crew({
    company: '', trade: '', num_workers: '1', work_description: '', work_locations: '',
    worker_ids: ['w9'], worker_names: ['Unassigned Man'], ...over,
  });

  const stored = [
    crew({ crew_id: 'C1', company: 'Arkon', trade: 'concrete' }),
    crew({ crew_id: 'C2', company: 'Delta', trade: 'electrical' }),
    loose({ crew_id: 'C3' }),
    // the hand-added sub, with the photos in question on it
    crew({
      crew_id: 'C4', company: 'Nova Masonry', trade: '', gate_sourced: false,
      num_workers: '3', num_workers_source: 'cp', worker_ids: [], worker_names: [],
      photos: [{ original_r2_key: 'logbook-photos/proj1/act_nova/cap_1.jpg' }],
    }),
  ];
  const fresh = [
    crew({ crew_id: 'C1', company: 'Arkon', trade: 'concrete' }),
    crew({ crew_id: 'C2', company: 'Delta', trade: 'electrical' }),
    loose({ crew_id: 'C3' }),
  ];

  const storedIndex = stored.findIndex((a) => a.company === 'Nova Masonry');
  const out = reconcileCrewsWithRoster(stored, fresh);
  const uiIndex = out.findIndex((a) => a.company === 'Nova Masonry');
  console.log(`      Nova Masonry sits at data.activities[${storedIndex}] on the server`);
  console.log(`      and at index ${uiIndex} in the reconciled list the CP screen maps over`);
  ok(storedIndex !== uiIndex,
    'the reconcile DOES move a hand-added crew relative to the stored document '
    + '(it lifts every unassigned-worker row to the tail) — so the screen\'s index is not the server\'s');

  // The screen must therefore address the photo by where it sits in the
  // document the SERVER holds, not by where it sits in the list on screen.
  // eslint-disable-next-line no-new-func
  const coords = new Function(`
    ${sliceDecl(editorSrc, 'photoServeKey', '\n);\n')}
    ${sliceDecl(editorSrc, 'servedPhotoCoords', '\n};\n')}
    return { photoServeKey, servedPhotoCoords };
  `)();
  const map = coords.servedPhotoCoords(stored);
  const photo = out[uiIndex].photos[0];
  const pair = map.get(coords.photoServeKey(photo)) || [uiIndex, 0];
  console.log(`      resolved coordinates for its photo: [${pair}]`);
  console.log(`      => ${API_BASE}/api/reports/logbook-photo/${LOG_ID}/${pair[0]}/${pair[1]}?v=thumb`);
  ok(pair[0] === storedIndex && pair[1] === 0,
    'the tile addresses data.activities[3] — the row the server actually holds it under');
  ok(resolveOnCpPhone(photo, ...pair, undefined)
    === `${API_BASE}/api/reports/logbook-photo/${LOG_ID}/${storedIndex}/0?v=thumb`,
    'and the url it renders names that row, not the unassigned-worker row now standing at index 2');

  // A photo this screen cannot place is one the server has never seen. It
  // keeps the live position, which is what it had before and is the only
  // honest answer for a photo that exists nowhere but this device.
  const unplaceable = { uri: FILE_ON_THE_SUPERS_PHONE, upload_pending: true };
  ok((map.get(coords.photoServeKey(unplaceable)) || [7, 9])[0] === 7,
    'an un-uploaded photo has no serve key and falls back to the live index — unchanged');
}

section('THE SLICES ARE PINNED TO THE SHIPPED SOURCE');
ok(/uri: photoTileUri\(photo, \.\.\.servedIndex\(photo, i, pi\), tileRetry\[tileKey\(photo, i, pi\)\]\)/.test(editorSrc),
  'the tile really does hand photoTileUri the SERVED coordinates, not the list positions');
ok(/const \[ai, pi\] = servedIndex\(photo, uiAi, uiPi\);/.test(editorSrc),
  'and so does the lightbox — the full-size view is addressed the same way');
ok(/onError=\{\(\) => setTileRetry\(/.test(editorSrc),
  'and onError really does flip `retried` — which is the only reason G and I recover');
ok(/const photoTileUri = \(photo, ai, pi, retried\) => \(/.test(editorSrc),
  'photoTileUri is still the single-expression form these slices depend on');
{
  const api = read(path.join(__dirname, 'api.js'));
  ok(api.includes('/api/reports/logbook-photo/${encodeURIComponent(logbookId)}/${activityIndex}/${photoIndex}${q}'),
    'the url shape reproduced here is api.js\'s own');
  ok(/getByProject: async \(projectId, logType = null, date = null\)/.test(api)
    && api.includes('`/api/logbooks/project/${projectId}`'),
    'the CP reads /api/logbooks/project/{id} — NOT the tablet\'s /submitted');
}
ok(/async def get_project_logbooks\(/.test(serverSrc)
  && /result = await paginated_query\(db\.logbooks, query, sort_field="date", limit=limit, skip=skip\)/.test(serverSrc),
  'and that route calls paginated_query with NO projection — every photo field survives to the CP');
ok(serverSrc.includes('"data.activities.photos.base64": 0')
  && serverSrc.includes('SUBMITTED_LOGBOOK_EXCLUDED_FIELDS,\n        ).sort("date", -1)'),
  '#357\'s exclusion is applied ONLY on the /submitted read — the tablet gets fewer fields, the CP more');
ok(/order = \[\("r2", thumb\), \("r2", enhanced\), \("r2", original\),\s*\("b64", full_b64\), \("b64", thumb_b64\)\]/.test(serverSrc),
  'the ?v=thumb ladder ported into serverCanServe still matches _logbook_photo_sources');
ok(/Deliberately unauthenticated: the people reading an emailed daily report/.test(serverSrc),
  'the serving endpoint takes no Authorization header — an <Image> with no token CAN load it');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
