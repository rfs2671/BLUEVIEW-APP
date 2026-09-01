/**
 * The two React Native readers of a logbook activity photo, against a photo
 * whose FULL-SIZE base64 has been purged.
 *
 * The backend drops `photo.base64` when a log is finalized, once R2 has been
 * proven to hold both derivatives (server.py _purge_finalized_photo_base64),
 * and writes the ~400px `thumb_base64` in its place. Both screens previously
 * resolved a photo as `photo.base64 || photo.uri`, which on a purged photo is
 * a blank tile on the CP's editor and a blank tile on the inspector kiosk —
 * on a signed record, in front of an inspector.
 *
 * The repo has no JS test runner (see RiskScoreCircle.bandFor.test.cjs), and
 * these are screen-local helpers inside JSX modules, so they are loaded the way
 * tokens.test.cjs already loads ESM under bare node: read the REAL source,
 * slice out the helper, evaluate it. The behaviour asserted is therefore the
 * shipped behaviour, never a hand-copy — and if a helper is renamed or
 * reshaped, the slice fails loudly instead of silently testing nothing.
 *
 * Run:  node src/utils/photoPurgeConsumers.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const KIOSK = path.join(FRONTEND, 'app', 'site', 'logbooks.jsx');
const EDITOR = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── slice one `const NAME = ...` declaration out of a screen ─────────────────
function slice(src, name, terminator) {
  const at = src.indexOf(`const ${name} = `);
  if (at < 0) throw new Error(`${name} not found — this test is stale`);
  const end = src.indexOf(terminator, at);
  if (end < 0) throw new Error(`${name}: no ${JSON.stringify(terminator)} terminator`);
  return src.slice(at, end + terminator.length);
}

// A photo the backend has purged: no full-size base64, the retained thumbnail,
// the two R2 keys, and a stale device uri left over from capture.
const PURGED = {
  thumb_base64: 'VEhVTUI=',
  base64_purged_at: '2026-08-07T18:00:00Z',
  enhance_status: 'done',
  enhanced_r2_key: 'logbook-photos/p/lb1/0-0-enhanced.jpg',
  thumb_r2_key: 'logbook-photos/p/lb1/0-0-thumb.jpg',
  uri: 'file:///data/user/0/cap_1.jpg',
};

const API_STUB = {
  getLogbookPhotoUrl: (id, ai, pi, variant) => (
    (!id && id !== 0) ? null : `https://api.test/api/reports/logbook-photo/${id}/${ai}/${pi}?v=${variant}`
  ),
};

// ════════════════════════════════════════════════════════════════════════════
//  KIOSK / INSPECTOR — app/site/logbooks.jsx
// ════════════════════════════════════════════════════════════════════════════
// The screens are CRLF in this repo; normalise so the slice terminators hold.
const LF = (s) => s.split('\r\n').join('\n');

const kioskSrc = LF(fs.readFileSync(KIOSK, 'utf8'));

const kiosk = new Function('logbooksAPI', `
  ${slice(kioskSrc, 'inlinePhoto', '\n);\n')}
  ${slice(kioskSrc, 'logbookPhotoUri', '\n};\n')}
  return logbookPhotoUri;
`)(API_STUB);

const LOG = { id: 'lb1' };

ok(kiosk(PURGED, LOG, 0, 0) === 'data:image/jpeg;base64,VEhVTUI=',
  'kiosk: a purged photo renders from the RETAINED THUMBNAIL, offline, no network');
ok(kiosk({ base64: 'RlVMTA==' }, LOG, 0, 0) === 'data:image/jpeg;base64,RlVMTA==',
  'kiosk: an unpurged photo still renders from its full-size copy');
ok(kiosk({ base64: 'data:image/png;base64,RlVMTA==' }, LOG, 0, 0)
  === 'data:image/png;base64,RlVMTA==',
  'kiosk: an already-prefixed data URI is not double-prefixed (unchanged)');
ok(kiosk({ enhance_status: 'done', thumb_r2_key: 'k' }, LOG, 0, 0)
  === 'https://api.test/api/reports/logbook-photo/lb1/0/0?v=thumb',
  'kiosk: with no inline copy at all it falls through to the served thumbnail');
ok(kiosk({ uri: 'file:///x.jpg' }, {}, 0, 0) === 'file:///x.jpg',
  'kiosk: an unsaved photo with no logbook id still falls back to its uri');
ok(kiosk({}, {}, 0, 0) === null && kiosk(null, LOG, 0, 0) === null,
  'kiosk: a photo with no copies at all yields null (caller renders nothing)');
ok(/logbookPhotoUri\(photo, log, i, pi\)/.test(kioskSrc),
  'kiosk: the activity photo row actually calls it (not dead code)');

// ════════════════════════════════════════════════════════════════════════════
//  CP EDITOR — app/logbooks/daily_jobsite.jsx
// ════════════════════════════════════════════════════════════════════════════
const editorSrc = LF(fs.readFileSync(EDITOR, 'utf8'));

const editor = new Function('logbooksAPI', 'existingLogId', `
  ${slice(editorSrc, 'inlinePhotoData', '\n);\n')}
  ${slice(editorSrc, 'isPurgedPhoto', '\n);\n')}
  ${slice(editorSrc, 'photoForPayload', '\n};\n')}
  ${slice(editorSrc, 'photoTileUri', '\n  );\n')}
  return { inlinePhotoData, isPurgedPhoto, photoForPayload, photoTileUri };
`);

const saved = editor(API_STUB, 'lb1');
const unsaved = editor(API_STUB, null);

// ── the grid tile ───────────────────────────────────────────────────────────
const { thumb_base64, base64_purged_at, enhance_status, enhanced_r2_key, thumb_r2_key } = PURGED;
const PURGED_NO_URI = { thumb_base64, base64_purged_at, enhance_status, enhanced_r2_key, thumb_r2_key };

// STILL TRUE, BUT NO LONGER UNCONDITIONAL — AND THAT REVERSAL IS DELIBERATE.
// "A local capture wins the tile (nothing to fetch)" now holds only for a
// photo with NO original_r2_key, which is what PURGED is: it carries
// enhanced_r2_key and thumb_r2_key but no original, so it takes the
// local-first branch and this assertion is unchanged.
//
// An UPLOADED photo now prefers the served copy. The old ordering saved a
// fetch on the capturing phone and cost every other device the photo
// entirely: `uri` is a file:///... path on one handset, and because a dead
// path is truthy the `||` chain stopped there and never reached a copy that
// worked. Thirteen photos on one filed log were invisible everywhere.
//
// The re-fetch on the capturing phone is a real cost and was accepted as one.
// `onError` on the tile flips it back to the local file when the fetch fails,
// so the offline CP is not stranded either. See photoSource.test.cjs.
ok(saved.photoTileUri(PURGED, 0, 0) === PURGED.uri,
  'editor: a local capture still wins the tile for an UN-uploaded photo');
ok(saved.photoTileUri(PURGED_NO_URI, 0, 0) === 'data:image/jpeg;base64,VEhVTUI=',
  'editor: a purged photo off another device renders from the retained thumbnail');
ok(saved.photoTileUri({ enhance_status: 'done', thumb_r2_key: 'k' }, 1, 2)
  === 'https://api.test/api/reports/logbook-photo/lb1/1/2?v=thumb',
  'editor: with no inline copy the tile falls through to the served thumbnail');
ok(saved.photoTileUri({ base64: 'RlVMTA==' }, 0, 0) === 'data:image/jpeg;base64,RlVMTA==',
  'editor: an unpurged photo still renders from its full-size copy');
ok(unsaved.photoTileUri({}, 0, 0) === undefined,
  'editor: nothing to show yields undefined, which <Image> accepts');
// The trailing `)` is deliberately NOT matched: the tile now passes a fourth
// argument, the per-tile retry flag that lets onError swap the preferred copy
// when the first one fails to LOAD (a `||` chain only advances on a falsy
// value, never on a failed load). The assertion's point is unchanged — the
// grid <Image> really calls this, with this photo and this position.
ok(/uri: photoTileUri\(photo, i, pi/.test(editorSrc),
  'editor: the grid <Image> actually calls it (not dead code)');

// ── the save path must not undo the purge ───────────────────────────────────
ok(saved.isPurgedPhoto(PURGED) === true,
  'editor: a photo carrying base64_purged_at is recognised as purged');
ok(saved.isPurgedPhoto({ thumb_base64: 'VEhVTUI=' }) === true,
  'editor: a retained thumbnail alone is enough to recognise a purged photo');
ok(saved.isPurgedPhoto({ uri: 'file:///x.jpg' }) === false
  && saved.isPurgedPhoto(null) === false,
  'editor: a fresh capture is NOT treated as purged — it must still be encoded');
// Photos now go to R2 as they are TAKEN and the document carries only the key,
// so the save path no longer re-encodes anything: photoForPayload replaced the
// base64 loop. The rule this pinned is unchanged, and is now RUN rather than
// pattern-matched - a purged photo passes through the payload mapper EXACTLY as
// it arrived, so a save can never push the full-size copy back into the
// document the purge just shrank.
ok(JSON.stringify(saved.photoForPayload(PURGED)) === JSON.stringify(PURGED),
  'editor: a purged photo goes into the payload untouched, no re-encode');
ok(saved.photoForPayload(PURGED).base64 === undefined
  && saved.photoForPayload(PURGED).upload_pending === undefined,
  'editor: and it gains neither a full-size copy nor a pending-upload marker');
ok(saved.photoForPayload({ original_r2_key: 'logbook-photos/p/act_1/cap_1.jpg', uri: 'file:///x.jpg' })
  .base64 === undefined,
  'editor: a photo already in R2 carries its key into the document, never its bytes');
ok(saved.photoForPayload({ id: 'cap_1', uri: 'file:///x.jpg' }).upload_pending === true
  && saved.photoForPayload({ id: 'cap_1', uri: 'file:///x.jpg' }).uri === 'file:///x.jpg',
  'editor: a photo whose upload has not landed says so AND keeps its local uri');
ok(saved.photoForPayload({ id: 'cap_1' }) === null,
  'editor: an entry with nothing local and nothing stored is dropped, not written');

// ── the lightbox label the enhance feature depends on is untouched ──────────
ok(/enhance_status === 'done'/.test(editorSrc)
  && /Original — enhancement \$\{photo\.enhance_status\}/.test(editorSrc),
  'editor: the Enhanced / Original-enhancing lightbox label still works');
ok(/inlinePhotoData\(photo\.thumb_base64\)/.test(editorSrc),
  'editor: the lightbox local fallback accepts the retained thumbnail');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
