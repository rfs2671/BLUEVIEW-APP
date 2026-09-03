// backfill_worker_project_trades.js
// DRY RUN IS THE DEFAULT. Writes nothing unless you set EXECUTE = true below.
//
//   mongosh "<ATLAS_URI>" --file backfill_worker_project_trades.js
//
// Builds the per-worker-per-project {trade, company} pairing from check-in
// history, so a returning worker is not re-prompted for a trade the site
// already knows.
//
// THREE RULES, all operator decisions, all enforced below:
//   1. "UNASSIGNED" is never stored. A worker whose history is UNASSIGNED-only
//      gets NO pairing — writing one would make the gate stop flagging a trade
//      assignment the CP still owes.
//   2. Conflicts are LISTED, NOT RESOLVED. If a worker shows two different
//      trades on one project, this prints it and writes nothing for that pair.
//   3. Live data wins. Uses $setOnInsert, so a pairing already written by a
//      real check-in is never overwritten by inferred history.

const EXECUTE = false;   // <-- flip to true only after reading the dry run

const rows = db.checkins.aggregate([
  { $match: {
      is_deleted: { $ne: true },
      worker_id:  { $nin: [null, ''] },
      project_id: { $nin: [null, ''] },
      worker_trade: { $nin: [null, '', 'UNASSIGNED'] },
  }},
  { $group: {
      _id: { worker_id: '$worker_id', project_id: '$project_id' },
      trades:    { $addToSet: '$worker_trade' },
      companies: { $addToSet: '$worker_company' },
      last_seen: { $max: '$check_in_time' },
      n: { $sum: 1 },
  }},
], { allowDiskUse: true }).toArray();

let willWrite = 0, conflicts = 0, alreadyLive = 0, inserted = 0;
const conflictList = [];

for (const r of rows) {
  const { worker_id, project_id } = r._id;

  if (r.trades.length > 1) {
    conflicts++;
    conflictList.push(`  worker=${worker_id} project=${project_id} trades=${JSON.stringify(r.trades)}`);
    continue;                                   // rule 2 — never auto-resolve
  }

  const existing = db.worker_project_trades.findOne({
    worker_id: String(worker_id), project_id: String(project_id),
  });
  if (existing) { alreadyLive++; continue; }    // rule 3 — live data wins

  const companies = (r.companies || []).filter(c => String(c || '').trim() !== '');
  const company = companies.length === 1 ? companies[0] : '';   // ambiguous -> blank, its own bucket

  willWrite++;
  if (!EXECUTE) {
    print(`[DRY-RUN] worker=${worker_id} project=${project_id} trade="${r.trades[0]}" company="${company}"`);
    continue;
  }
  const res = db.worker_project_trades.updateOne(
    { worker_id: String(worker_id), project_id: String(project_id) },
    { $setOnInsert: {
        worker_id:  String(worker_id),
        project_id: String(project_id),
        trade:      r.trades[0],
        company:    company,
        updated_at: r.last_seen || new Date(),
    }},
    { upsert: true },
  );
  inserted += res.upsertedCount || 0;
}

print('\n================ SUMMARY ================');
print(`mode                : ${EXECUTE ? 'EXECUTE' : 'DRY-RUN (nothing written)'}`);
print(`worker/project pairs with a real trade : ${rows.length}`);
print(`  would write / wrote                  : ${EXECUTE ? inserted : willWrite}`);
print(`  skipped, pairing already exists      : ${alreadyLive}`);
print(`  skipped, CONFLICTING trades          : ${conflicts}`);
if (conflictList.length) {
  print('\n=== CONFLICTS — resolve by hand, nothing was written for these ===');
  conflictList.forEach(l => print(l));
}
print('\nNote: workers whose history is UNASSIGNED-only never appear above.');
print('That is intended — they still owe the CP a trade assignment.');
