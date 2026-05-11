# Runbook — V2.2.4 Path A: BIN→BBL peer-comparison migration

**Status:** Active. Deployed 2026-05-10.
**Owner:** On-call.
**Scope:** ONE incident. Single-commit ship + single migration run + initial backfill.

This runbook covers the post-deploy operational steps for V2.2.4 Path A — the migration that switches peer-comparison from BIN-keyed (broken since V2.2.3) to BBL-keyed (working).

## Background

V2.2.3 stopped populating `nyc_pluto.bin` (the Socrata payload at `64uk-42ks` has no `bin` column — verified by curl 2026-05-10). But the V2.2-era `nyc_pluto_bin_unique` index was keyed on `bin`. Effect:
- Every PLUTO insert past the first collided on `bin: null` → DKE storm in production logs.
- The single doc that DID land had no `bin` field → `_bins_matching` (consumer) projected `{"bin": 1}` and found nothing → peer-comparison subscore degraded to zero peer data on every risk score.

V2.2.4 Path A flips the key to BBL throughout:
- `nyc_pluto` unique index → `bbl`.
- `_bins_matching` → `_bbls_matching`, projects `bbl`.
- Event collections (`nyc_violations`, `nyc_inspections`, `nyc_complaints_311`) gain `(bbl, occurred_date)` indexes.
- `dob_violations` canonicalizer derives `bbl` from `boro`/`block`/`lot` since the Socrata payload has no pre-joined BBL.

## Pre-deploy checklist

- [ ] **Atlas backup is fresh.** Confirm via Atlas UI → Backups → Snapshots → last snapshot within ≤4 hours. Step 2 + 5 of the migration are destructive (delete_many on `nyc_pluto` + `statistical_baselines`).
- [ ] **Deploy hash matches commit.** Railway → backend service → latest deployment → confirm the commit SHA on `main` matches the deploy in service.
- [ ] **Boot logs clean.** Tail Railway logs for ≥2 minutes after deploy. Look for:
  - `Mongo indexes ensured for V2.2.4 collections` (or whatever the startup log message is)
  - No tracebacks from `lib.statistical_engine.*`
  - No `KeyError: 'peer_bins'` (the rename — `__init__.py` now exports `peer_bbls`)

If any check fails: STOP. Roll back the deploy. Do NOT proceed to migration.

## Step 1 — Dry-run the migration

Open a Railway shell (or any environment with the production write-MONGO_URL exported), then:

```bash
MONGO_URL='mongodb+srv://write_user:...@cluster.mongodb.net/?retryWrites=true&w=majority' \
DB_NAME='blueview' \
python -m backend.scripts.migrate_pluto_bbl_keyed_path_a
```

The script runs in **dry-run mode by default**. It prints:

1. PRE-MIGRATION STATE — doc counts + current indexes for each affected collection.
2. PLAN — every operation that WOULD happen, including which indexes will be dropped, what gets deleted, and what gets created.
3. DRY-RUN COMPLETE — explicit confirmation that no writes occurred.

**Paste the dry-run output to the operator for review** before proceeding. Expected pre-state (verified 2026-05-10):
- `nyc_pluto`: 1 doc; indexes include `nyc_pluto_bin_unique` (unique on bin) and `nyc_pluto_bbl` (non-unique on bbl).
- `nyc_violations`: ~hundreds of thousands of docs; no `(bbl, occurred_date)` index.
- `nyc_inspections`: similar; no `(bbl, occurred_date)` index.
- `nyc_complaints_311`: similar; `(bbl, occurred_date)` index ALREADY present from V2.2 era — script will skip its creation.
- `statistical_baselines`: 1 doc with `peer_sample_size: 0`.

If the dry-run output diverges meaningfully from the above expected state, STOP and re-investigate before executing.

## Step 2 — Execute the migration

After operator approval of the dry-run output:

```bash
MONGO_URL='...' DB_NAME='blueview' \
  python -m backend.scripts.migrate_pluto_bbl_keyed_path_a --execute
```

The script performs (in order):

1. Drop `nyc_pluto_bin_unique`.
2. Drop `nyc_pluto_bbl` (the non-unique placeholder).
3. `db.nyc_pluto.delete_many({})` (clears the 1 polluted doc).
4. Create `nyc_pluto_bbl_unique` (unique on bbl).
5. Create `nyc_violations_bbl_date` `(bbl, occurred_date)` background.
6. Create `nyc_inspections_bbl_date` `(bbl, occurred_date)` background.
7. (Skip `nyc_complaints_311` — already has the index.)
8. `db.statistical_baselines.delete_many({})` (clears the 1 zero-peer-sample doc).

Each step prints its own status line; failure during any step raises and aborts the run. POST-MIGRATION STATE is printed after success, with a `[verdict]` block showing ✓ / ✗ per condition.

If a step fails:
- DO NOT re-run with `--execute` blind. Inspect the error.
- The migration is partially-completable: index drops + creates are reversible by manually running the inverse in a Mongo shell. Document deletions are NOT reversible — restore from the Atlas backup taken in the pre-deploy checklist.
- Common failure mode: the unique-on-bbl index creation fails because PLUTO still has docs with duplicate-bbl values (shouldn't happen since `delete_many({})` runs first, but in case the deletion was partial). Verify the collection is empty and rerun the create_index step manually.

## Step 3 — Trigger the initial backfill

Note: there is no single-dataset backfill endpoint (verified in Investigation 1). The only on-demand path is the all-7-datasets bundled endpoint:

```bash
curl -X POST \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"max_pages_per_dataset": 1}' \
  https://api.levelog.com/api/admin/risk-score/backfill
```

This processes one page per dataset per request and updates `ingestion_state`. **Run repeatedly** — every ~10 seconds — until every dataset's response shows `finished: true`. Expect 100–200 invocations for PLUTO (~860k rows / 5000 per page).

Two operator scripting options:
- A loop in a Railway shell: `while true; do curl ...; sleep 10; done`. Stop when every dataset is `finished: true`.
- A long-lived Python script. Same shape as above but with `requests`.

## Step 4 — Monitor Railway logs during backfill

Watch for:
- `nyc_pluto` document count growing toward ~860k. Sample: `db.nyc_pluto.countDocuments({})` from a Mongo shell.
- DKE warnings on `nyc_pluto` should **STOP firing**. Pre-V2.2.4 you saw hundreds per backfill page; post-fix, zero.
- `nyc_violations`: every new row should have a populated `bbl` (the V2.2.4 `__derive_bbl__` sentinel synthesizes it from boro/block/lot). Sample: `db.nyc_violations.find({bbl: null}).count()` should drop from ~hundreds-of-thousands to near-zero as old rows are upserted-overwritten.
- No new ERROR logs mentioning `lib.statistical_engine.*`. (V2.2.3 visibility instrumentation is still in place — any new `dropped row` errors would be a surprise.)

If DKE warnings on `nyc_pluto` continue past the first 10 backfill pages: STOP. The unique-on-bbl index isn't holding — possibly the old unique-on-bin index wasn't dropped cleanly. Rerun the migration script's `--execute` step and check the POST-MIGRATION STATE verdict.

## Step 5 — Verify post-backfill state

Once every dataset is `finished: true`, verify in a Mongo shell:

```js
db.nyc_pluto.countDocuments({})              // expect ~860,000
db.nyc_pluto.findOne({bbl: null})            // expect null (no nulls)
db.nyc_violations.find({bbl: null}).count()  // expect near 0
db.nyc_inspections.find({bbl: null}).count() // expect ~3% of total
db.nyc_complaints_311.find({bbl: null}).count() // expect ~11% of total
```

The ~3% and ~11% null rates on inspections + complaints are EXPECTED — they're rows that genuinely don't map to a BBL (e.g., 311 complaints filed against street blockfaces with no tax lot reference). Verified empirically in Verification 1 (2026-05-10).

## Step 6 — Trigger baseline aggregator

Either:
- **Wait for cron**: `v2_2_baseline_aggregator` runs daily at 3:30 AM ET.
- **Manual**: From a Railway shell:
  ```python
  from server import db
  from lib.statistical_engine import run_baseline_aggregator
  import asyncio
  asyncio.run(run_baseline_aggregator(db))
  ```

Verify result:
```js
db.statistical_baselines.countDocuments({})     // expect ~hundreds-to-low-thousands
db.statistical_baselines.find({peer_sample_size: 0}).count()  // expect 0
db.statistical_baselines.findOne({}, {peer_sample_size: 1, year_month: 1})
// expect peer_sample_size > 0
```

If `peer_sample_size: 0` rows appear post-aggregator, the peer-comparison path is still broken. Roll back to investigate.

## Step 7 — Spot-check 3 project risk scores

Pick three projects from the operator's portfolio with known characteristics (one Manhattan major_b, one Queens regular, one Brooklyn major_a or whatever the operator has on file). For each:

```bash
curl -X POST -H "Authorization: Bearer <ADMIN_JWT>" \
  https://api.levelog.com/api/projects/{project_id}/risk-score/calculate
```

Inspect the response's `contributing_factors` block. The `peer_comparison` group should show **non-zero peer_sample_size** for at least one of the three sub-collections (violations/inspections/complaints). If all three show `peer_sample_size: 0`, peer-comparison is still degraded — STOP and investigate.

Expected shape (success):
```json
{
  "peer_comparison": {
    "violations":  {"percentile_rank": 47.2, "peer_sample_size": 24, ...},
    "inspections": {"percentile_rank": 31.8, "peer_sample_size": 24, ...},
    "complaints":  {"percentile_rank": 12.5, "peer_sample_size": 24, ...},
    "peer_set":    {"tier": "borough_class_use", "borough": "MANHATTAN", ...}
  }
}
```

## Rollback plan

If verification fails at any step:

1. **Schema rollback** (reversible — index drops + creates only):
   ```js
   db.nyc_pluto.dropIndex("nyc_pluto_bbl_unique")
   db.nyc_pluto.createIndex({bin: 1}, {unique: true, name: "nyc_pluto_bin_unique"})
   db.nyc_pluto.createIndex({bbl: 1}, {name: "nyc_pluto_bbl"})
   db.nyc_violations.dropIndex("nyc_violations_bbl_date")
   db.nyc_inspections.dropIndex("nyc_inspections_bbl_date")
   ```

2. **Code rollback**: `git revert` the V2.2.4 commit on main + redeploy. The `__derive_bbl__` sentinel + canonicalizer changes go back to V2.2.3 behavior.

3. **Data rollback** (only if migration step 3 — delete_many on nyc_pluto — has run): the pre-migration state had 1 polluted PLUTO doc. Re-running the V2.2.3 backfill would not repopulate without the V2.2.4 BBL canonicalizer, so there's nothing to recover. Skip data restoration; accept the small state regression.

Document the rollback in the on-call notes + open an incident ticket.

## Post-migration cleanup

After 7 days of clean operation (no DKE storms, baselines aggregator producing non-zero peer samples, risk-score peer-comparison subscores populated):
- Delete the migration script: `rm backend/scripts/migrate_pluto_bbl_keyed_path_a.py` in a follow-up commit. One-shot script, no use after first successful run (same convention as `cleanup_v21_inert_data.py` and `cleanup_pluto_polluted_record_ids.py`).
- Consider dropping the `nyc_*_bin_date` indexes on event collections. They were the legacy peer-comparison query path; post-V2.2.4 they only serve per-project BIN lookups (per the existing `score.py` per-project event-count query, which still uses `bin`). Out of scope for this migration — re-evaluate after the per-project query path is also migrated.
