// audit_company_values.js — READ ONLY. Writes nothing. Safe to run any time.
// Measures how many distinct company spellings exist and where they collide,
// so you know what backfill_worker_project_trades.js is actually working with.
//
//   mongosh "<ATLAS_URI>" --file audit_company_values.js

const norm = s => String(s || '').trim().toLowerCase().replace(/[.,]/g, '').replace(/\s+/g, ' ');

print('=== distinct company strings, by source ===');
for (const [label, coll, field] of [
  ['workers',  'workers',  'company'],
  ['checkins', 'checkins', 'worker_company'],
]) {
  const vals = db[coll].distinct(field).filter(v => String(v || '').trim() !== '');
  print(`  ${label}.${field}: ${vals.length} distinct non-blank`);
}

// Collision groups: different raw spellings that normalize to one company.
print('\n=== collision groups (same company, different spelling) ===');
const groups = {};
db.checkins.find({ worker_company: { $nin: [null, ''] } }, { worker_company: 1 })
  .forEach(d => {
    const k = norm(d.worker_company);
    if (!k) return;
    (groups[k] = groups[k] || new Set()).add(d.worker_company);
  });
let collisions = 0;
Object.entries(groups).forEach(([k, set]) => {
  if (set.size > 1) { collisions++; print(`  "${k}" <- ${JSON.stringify([...set])}`); }
});
print(`  ${collisions} group(s) with more than one spelling`);
print(`  ${Object.keys(groups).length} normalized companies total`);

// Blank company is its own bucket by operator ruling — count it, don't fix it.
const blank = db.checkins.countDocuments({
  $or: [{ worker_company: null }, { worker_company: '' }, { worker_company: { $exists: false } }],
});
print(`\n=== blank company on checkins: ${blank} row(s) ===`);
print('(Blank is a legitimate bucket, not an error. Do not backfill it.)');
