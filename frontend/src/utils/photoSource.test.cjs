/**
 * Which copy of a photo a tile shows, and what the filed record claims.
 *
 * THE DEFECT. photoTileUri preferred `photo.uri` unconditionally:
 *
 *     photo?.uri || base64 || thumb_base64 || servedUrl
 *
 * `uri` is a device-local file:///data/user/0/... path, and photoForPayload
 * wrote it into the logbook document. On any device that did not take the
 * photo -- and on the same device after its app data was cleared -- that file
 * is gone. But a dead path is a NON-EMPTY STRING, and `||` advances on a falsy
 * value, never on a failed LOAD, so the chain stopped at the one copy that
 * could not work and never reached the served URL that could.
 *
 * AND THE MIDDLE OF THE CHAIN IS EMPTY FOR A MODERN PHOTO. `base64` is never
 * written once a photo is uploaded (re-encoding blew the 16MB document
 * ceiling: ten subs x ten photos measured 20,510,438 bytes), and
 * `thumb_base64` is written by the finalize purge, which has not run on a log
 * still being edited. So for an uploaded, unfinalized photo the served URL was
 * the ONLY readable copy, sitting last behind a dead path.
 *
 * WHY THE FIX IS A BRANCH AND NOT A REORDER. Putting the served URL first
 * unconditionally breaks the case the chain was built for: a CP offline with
 * an uploaded photo would get a URL that cannot load in front of a file on his
 * own phone. Same bug, different victim. The preference keys on whether the
 * photo has an `original_r2_key`, and `onError` turns it into a preference
 * rather than a commitment.
 *
 * Run:  node src/utils/photoSource.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
// Normalised: the screen is CRLF on disk and every marker below is written
// with a bare newline, so a raw read would silently match nothing and this
// whole file would pass vacuously.
const SRC = fs.readFileSync(SCREEN, 'utf8').split('\r\n').join('\n');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) { console.log(`  ok  ${msg}`); } else { failures += 1; console.log(`FAIL  ${msg}`); }
};

// ── extract the module-level helpers and run them for real ──────────────────
let seq = 0;
const START = 'const inlinePhotoData';
const END_MARK = 'return { ...stored, upload_pending: true };\n};';
const start = SRC.indexOf(START);
const end = SRC.indexOf(END_MARK);
if (start < 0 || end < 0) {
  console.log('FAIL  could not locate the helper block in daily_jobsite.jsx');
  process.exit(1);
}
const block = SRC.slice(start, end + END_MARK.length);

// eslint-disable-next-line no-eval
const M = eval(`(function () {
  const newActivityId = () => \`act_stub_\${(seq += 1)}\`;
  ${block}
  return {
    inlinePhotoData,
    isPurgedPhoto,
    photoForPayload,
    withActivityIds: typeof withActivityIds === 'function' ? withActivityIds : null,
    tileKey: typeof tileKey === 'function' ? tileKey : null,
  };
})()`);

console.log('\n1. THE FILED RECORD STOPS CLAIMING A PHONE PATH');
{
  const uploaded = {
    id: 'cap_1', uri: 'file:///data/user/0/com.levelog/cache/cap_1.jpg',
    original_r2_key: 'logbook-photos/p1/act_9/cap_1.jpg',
  };
  const out = M.photoForPayload({ ...uploaded });
  ok(out && out.original_r2_key === uploaded.original_r2_key,
    'an uploaded photo keeps its R2 key');
  ok(out && out.uri === undefined,
    'an uploaded photo is written WITHOUT the device-local uri');

  const pending = { id: 'cap_2', uri: 'file:///data/user/0/com.levelog/cache/cap_2.jpg' };
  const out2 = M.photoForPayload({ ...pending });
  ok(out2 && out2.uri === pending.uri,
    'an UN-uploaded photo KEEPS its uri -- it is the only handle on the file');
  ok(out2 && out2.upload_pending === true,
    'and is still marked for the upload drain');

  ok(M.photoForPayload({ id: 'x' }) === null,
    'a photo with neither key nor uri is dropped, not written empty');

  const purged = { id: 'cap_3', thumb_base64: 'abc', base64_purged_at: 'now' };
  ok(M.photoForPayload({ ...purged }) !== null,
    'a purged photo still survives the payload builder');
}

console.log('\n2. activity_id BACKFILL');
{
  ok(typeof M.withActivityIds === 'function', 'withActivityIds exists');
  if (typeof M.withActivityIds === 'function') {
    const rows = [
      { crew_id: 'C1', photos: [] },
      { crew_id: 'C2', activity_id: 'act_1788191515625_1', photos: [] },
    ];
    const out = M.withActivityIds(rows);
    ok(!!out[0].activity_id, 'a row with no activity_id is given one');
    ok(out[1].activity_id === 'act_1788191515625_1',
      'a row that ALREADY has one is left exactly as it was');
    ok(out[0].activity_id !== out[1].activity_id, 'the minted id is distinct');

    // THE ASSERTION THAT MATTERS: a backfill must not move a stored photo.
    const withPhotos = [{
      crew_id: 'C1',
      photos: [{ original_r2_key: 'logbook-photos/p1/cap_7/cap_7.jpg' }],
    }];
    const after = M.withActivityIds(withPhotos);
    ok(after[0].photos[0].original_r2_key === 'logbook-photos/p1/cap_7/cap_7.jpg',
      'BACKFILLING DOES NOT TOUCH original_r2_key -- the cap_ keys still resolve');
    ok(M.withActivityIds([]).length === 0, 'an empty list is fine');
    ok(M.withActivityIds(null).length === 0, 'a null list is fine');
  }
}

console.log('\n3. TILE IDENTITY');
{
  ok(typeof M.tileKey === 'function', 'tileKey exists');
  if (typeof M.tileKey === 'function') {
    ok(M.tileKey({ original_r2_key: 'k/1' }, 0, 0) === 'k/1',
      'the R2 key leads -- a saved photo has no id');
    ok(M.tileKey({ id: 'cap_9' }, 3, 2) === 'cap_9',
      'an un-uploaded photo falls back to its capture id');
    ok(M.tileKey({}, 3, 2) === '3-2',
      'position is the last resort, never the first');
  }
}

console.log('\n4. THE PREFERENCE IS CONDITIONAL, AND onError MAKES IT A PREFERENCE');
{
  const fn = SRC.slice(SRC.indexOf('const photoTileUri'),
    SRC.indexOf('const openPhotoLightbox'));
  ok(/original_r2_key\s*\n?\s*\?/.test(fn) || /photo\?\.original_r2_key$/m.test(fn)
     || fn.includes('original_r2_key'),
  'photoTileUri branches on original_r2_key');
  ok(/photo\?\.original_r2_key \? !retried : !!retried/.test(fn),
    'uploaded prefers the served URL; un-uploaded prefers the local file; a '
    + 'retry swaps whichever it was');
  ok(SRC.includes('tileRetry[tileKey(photo, i, pi)]'),
    'a failed load is remembered per tile and fed back in');
  ok(/const photoTileUri = \(photo, ai, pi, retried\) => \(/.test(fn),
    'photoTileUri stays an EXPRESSION taking retried as a PARAMETER -- two '
    + 'other suites slice it out of this file and eval it with only '
    + '(logbooksAPI, existingLogId) in scope');
  ok(!/^\s*photo\?\.uri\s*\n\s*\|\|/m.test(fn),
    'the old unconditional uri-first chain is gone');

  ok(SRC.includes('onError={'), 'the photo tile wires onError');
  ok(/onError=\{[\s\S]{0,400}setTileRetry/.test(SRC),
    'onError flips that tile to the other copy');
  ok(/onError=\{[\s\S]{0,400}prev\[k\] \? prev :/.test(SRC),
    'and does it once -- it must not loop between two broken copies');
}

console.log('\n5. THE OFFLINE CAPTURE PATH IS NOT BROKEN');
{
  ok(SRC.includes('persistPhoto'),
    'persistPhoto is still used -- the offline photo guarantee stands');
  const payload = SRC.slice(SRC.indexOf('const photoForPayload'),
    SRC.indexOf('export const WEATHER_OPTIONS'));
  ok(payload.includes('if (!stored.uri) return null;'),
    'a photo with no uri and no key is still dropped rather than written');
  ok(/const \{ upload_pending, upload_rejected, uri, \.\.\.done \} = stored/.test(payload),
    'uri is stripped ONLY inside the original_r2_key branch');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
