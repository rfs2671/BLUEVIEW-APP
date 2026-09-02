/**
 * HOW MANY CS REGISTRATIONS CANNOT SAY WHEN THEY WERE SWITCHED OFF.
 *
 * READ-ONLY. This script never writes. It counts; it does not touch anything.
 *
 *   mongosh "$MONGO_URL" backend/scripts/audit_cs_registration_history.js
 *
 * A FILE, NOT A --eval ONE-LINER. Three mongosh one-liners were handed over in
 * one session and all three arrived mangled: the shell ate the `$` operators,
 * quotes collapsed, the wrapper merged into the pipeline. Same argument PR #90
 * has been making since 2026-08-08 -- a script that runs against production
 * must not live only in a session that ends.
 *
 * ── WHAT THIS MEASURES ──────────────────────────────────────────────────────
 *
 * attribute_signer (backend/lib/logbook/cs_attribution.py) answers, for a filed
 * BC 3301.13.13 log, whether its signer was the registered construction
 * superintendent ON THE LOG'S OWN DATE. To do that for a PAST date it needs to
 * know when a registration stopped being active.
 *
 * All three off-switches stamp a time:
 *
 *     superseded by a new CS      is_active False + deactivated_at   (:16014)
 *     switched off by an admin    is_active False + deactivated_at   (:16165)
 *     soft-deleted                is_deleted True  + deleted_at      (:16179)
 *
 * SO ONE SET REMAINS UNANSWERABLE: rows switched off BEFORE those stampers
 * existed, which carry `is_active: false` and no `deactivated_at`. The moment
 * they were switched off was never written down, so nothing can recover it. A
 * log dated after such a row's creation reports UNDETERMINED forever.
 *
 * THAT SET CANNOT GROW. Every live path stamps. This counts what it is today.
 *
 * ── WHY THE SCRIPT EXISTS AT ALL ────────────────────────────────────────────
 *
 * An earlier report claimed only the DELETE path stamped a time, and proposed
 * building a field that already existed. The writers had been INFERRED from the
 * model and the delete endpoint rather than ENUMERATED by grepping the field,
 * and two of the three stampers were missed. This counts rather than reasons.
 */

/* eslint-disable no-undef */

const all = db.cs_registrations.countDocuments({});
const deleted = db.cs_registrations.countDocuments({ is_deleted: true });

// The unanswerable set: switched off, not deleted, and no timestamp saying when.
const orphaned = db.cs_registrations.countDocuments({
  is_active: false,
  is_deleted: { $ne: true },
  $or: [
    { deactivated_at: { $exists: false } },
    { deactivated_at: null },
  ],
});

// Switched off WITH a timestamp — these are fully answerable.
const stamped = db.cs_registrations.countDocuments({
  is_active: false,
  is_deleted: { $ne: true },
  deactivated_at: { $ne: null, $exists: true },
});

const active = db.cs_registrations.countDocuments({
  is_active: true,
  is_deleted: { $ne: true },
});

print('');
print('=== CS registrations: can we say when each was switched off? ===');
print('');
print(`  total rows                                  ${all}`);
print(`  active now                                  ${active}`);
print(`  soft-deleted (deleted_at answers it)        ${deleted}`);
print(`  deactivated WITH deactivated_at             ${stamped}`);
print(`  deactivated WITHOUT it  <-- UNDETERMINED    ${orphaned}`);
print('');

if (orphaned === 0) {
  print('  NOTHING IS UNANSWERABLE. Every registration that was switched off');
  print('  recorded when. UNDETERMINED cannot arise from existing data.');
} else {
  print(`  ${orphaned} row(s) predate the stampers. A superintendent log dated`);
  print('  after such a row was created reports UNDETERMINED, permanently --');
  print('  the moment was never written down and cannot be recovered.');
  print('');
  print('  Listing them, so the set is known rather than a number:');
  db.cs_registrations.find(
    {
      is_active: false,
      is_deleted: { $ne: true },
      $or: [{ deactivated_at: { $exists: false } }, { deactivated_at: null }],
    },
    // BOTH NAMES FOR THE NUMBER. Rows written before the rename carry
    // `license_number`; rows written after carry `registration_number`.
    // Projecting one name would blank the column for half the collection.
    {
      project_id: 1, full_name: 1, registration_number: 1, license_number: 1,
      created_at: 1, updated_at: 1,
    },
  ).forEach((r) => {
    const proj = db.projects.findOne(
      { _id: ObjectId.isValid(String(r.project_id)) ? ObjectId(String(r.project_id)) : r.project_id },
      { name: 1 },
    );
    print(`    ${String((proj && proj.name) || '(unknown project)').padEnd(30)}`
      + ` ${String(r.full_name || '').padEnd(22)} created ${r.created_at}`);
  });
}
print('');
