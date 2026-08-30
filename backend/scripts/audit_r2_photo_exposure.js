/**
 * WHAT WOULD BE LOST IF A PROJECT WERE HARD-DELETED TODAY.
 *
 * READ-ONLY. This script never writes. It counts; it does not touch anything.
 *
 *   mongosh "$MONGO_URL" backend/scripts/audit_r2_photo_exposure.js
 *
 * A FILE, NOT A --eval ONE-LINER, and that is the point. Three mongosh
 * one-liners were handed over in a single session and all three arrived
 * mangled: the shell ate the `$` operators, quotes collapsed, the wrapper
 * merged into the pipeline. A script that runs against production must not
 * live only in a session that ends. Same argument as PR #90, which has been
 * open since 2026-08-08 making it.
 *
 * ── WHAT THE DEFECT IS ──────────────────────────────────────────────────────
 *
 * hard_delete_project (server.py:11171) sweeps R2 by PREFIX:
 *
 *     logbook-photos/{project_id}/          <- both key schemes live here
 *     plans/{project_id}/
 *     {company_id}/{project_id}/
 *
 * The logbook ROWS survive -- `logbooks` is in SOFT_DELETE_NEVER_PURGE -- but
 * the objects their photos reference do not. The endpoint is owner-only,
 * manual and irreversible; nothing schedules it. So this measures FORWARD
 * exposure: what a hard delete would take if one were run now.
 *
 * ── WHAT SURVIVES, AND WHY THE HEADLINE NUMBER OVERSTATES THE LOSS ──────────
 *
 * `thumb_base64` is stored INLINE on the photo and is NEVER purged, under any
 * condition -- _purge_finalized_photo_base64 (server.py:20411) says so in
 * terms: "a small photo beats no photo on a signed legal record, and this must
 * never remove the last copy."
 *
 * So a hard-deleted project's log photographs DEGRADE to a ~400px inline copy.
 * They do not vanish. The rows that genuinely go to nothing are those holding
 * an R2 key with NO inline copy of any kind, and that is the number that
 * matters. It is reported separately below.
 *
 * Signatures are unaffected either way: they are stored inline as base64 or as
 * vector strokes, never as R2 objects.
 */

/* eslint-disable no-undef */

const KEYS = ['original_r2_key', 'enhanced_r2_key', 'thumb_r2_key'];

function hasAnyR2(photo) {
  return KEYS.some((k) => photo && typeof photo[k] === 'string' && photo[k].length > 0);
}

function hasInline(photo) {
  if (!photo) return false;
  const t = photo.thumb_base64;
  const b = photo.base64;
  return (typeof t === 'string' && t.length > 0) || (typeof b === 'string' && b.length > 0);
}

const stats = {
  logbooks_scanned: 0,
  logbooks_with_photos: 0,
  logbooks_referencing_r2: 0,
  photos_total: 0,
  photos_referencing_r2: 0,
  photos_r2_with_inline_survivor: 0,
  photos_r2_WITH_NO_INLINE_COPY: 0,
  logbooks_WITH_AN_UNRECOVERABLE_PHOTO: 0,
};

const byProject = {};
const byLogType = {};

const cursor = db.logbooks.find(
  { 'data.activities': { $exists: true } },
  { project_id: 1, log_type: 1, date: 1, 'data.activities': 1 },
);

while (cursor.hasNext()) {
  const lb = cursor.next();
  stats.logbooks_scanned += 1;

  let lbPhotos = 0;
  let lbR2 = 0;
  let lbUnrecoverable = 0;

  const activities = (lb.data && lb.data.activities) || [];
  for (const act of activities) {
    const photos = (act && act.photos) || [];
    for (const p of photos) {
      lbPhotos += 1;
      stats.photos_total += 1;
      if (!hasAnyR2(p)) continue;
      lbR2 += 1;
      stats.photos_referencing_r2 += 1;
      if (hasInline(p)) {
        stats.photos_r2_with_inline_survivor += 1;
      } else {
        stats.photos_r2_WITH_NO_INLINE_COPY += 1;
        lbUnrecoverable += 1;
      }
    }
  }

  if (lbPhotos > 0) stats.logbooks_with_photos += 1;
  if (lbR2 > 0) {
    stats.logbooks_referencing_r2 += 1;
    const pid = String(lb.project_id || '(none)');
    byProject[pid] = (byProject[pid] || 0) + lbR2;
    const lt = String(lb.log_type || '(none)');
    byLogType[lt] = (byLogType[lt] || 0) + lbR2;
  }
  if (lbUnrecoverable > 0) stats.logbooks_WITH_AN_UNRECOVERABLE_PHOTO += 1;
}

print('');
print('=== R2 photo exposure under hard_delete_project ===');
print('');
for (const [k, v] of Object.entries(stats)) {
  print(`  ${k.padEnd(42)} ${v}`);
}

print('');
print('--- logbooks referencing R2, by project ---');
const projRows = Object.entries(byProject).sort((a, b) => b[1] - a[1]);
for (const [pid, n] of projRows.slice(0, 25)) {
  const proj = db.projects.findOne({ _id: ObjectId.isValid(pid) ? ObjectId(pid) : pid }, { name: 1 });
  print(`  ${String((proj && proj.name) || '(unknown)').padEnd(34)} ${pid}  ${n} photos`);
}
if (projRows.length > 25) print(`  ... and ${projRows.length - 25} more projects`);

print('');
print('--- by log type ---');
for (const [lt, n] of Object.entries(byLogType).sort((a, b) => b[1] - a[1])) {
  print(`  ${lt.padEnd(34)} ${n} photos`);
}

print('');
print('READ THE SECOND NUMBER, NOT THE FIRST.');
print('  photos_referencing_r2            = would lose their R2 objects');
print('  photos_r2_WITH_NO_INLINE_COPY    = would be lost ENTIRELY');
print('');
print('The gap between them is thumb_base64, which is never purged.');
print('');
