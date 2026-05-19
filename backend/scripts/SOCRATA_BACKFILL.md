# Socrata 3-year backfill — operator runbook

Phase 1 Week 1 deliverable. Backfills three NYC Socrata datasets
into per-dataset `*_historical` Mongo collections for the curated
5,000-BIN target list:

| Dataset            | Socrata id   | Collection                            |
| ------------------ | ------------ | ------------------------------------- |
| ECB violations     | `6bgk-3dad`  | `socrata_ecb_violations_historical`   |
| DOB permits        | `rbx6-tga4`  | `socrata_permits_historical`          |
| DOB complaints     | `eabe-havv`  | `socrata_complaints_historical`       |

---

## Gate-by-gate workflow

This work runs through four operator-gated stages. Each gate is a
checkpoint with explicit authorization before proceeding.

### Gate 1 — Pre-merge code review (no Socrata, no Atlas)

Operator reviews all scripts + this README. The dry-run flag on each
script must run cleanly without making Socrata calls or Mongo writes:

```bash
# Lists planned indexes — no Atlas writes
python -m scripts._create_backfill_indexes --dry-run

# Reads db.projects, mocks Tier C, no file write
python -m scripts._select_backfill_target_bins --dry-run

# Prints query plan — no Socrata calls
python -m scripts.socrata_3year_backfill --dataset ecb-violations
python -m scripts.socrata_3year_backfill --dataset permits
python -m scripts.socrata_3year_backfill --dataset complaints
```

### Gate 2 — Atlas index creation

After Gate 1 passes, operator authorizes index creation against
Atlas production:

```bash
MONGO_URL='mongodb+srv://...' DB_NAME='blueview' \
    python -m scripts._create_backfill_indexes
```

This is **idempotent** — re-running is a no-op once the indexes exist.
Verify via `mongosh` or Atlas UI that all 11 indexes (4 + 4 + 3) are
present before Gate 3.

Capture pre-backfill collection sizes (likely 0):

```js
db.socrata_ecb_violations_historical.estimatedDocumentCount()
db.socrata_permits_historical.estimatedDocumentCount()
db.socrata_complaints_historical.estimatedDocumentCount()
```

### Gate 3 — Target BIN selection

```bash
MONGO_URL='...' DB_NAME='...' \
    python -m scripts._select_backfill_target_bins
```

Writes `_backfill_target_bins.json`. Operator must review the file
before Gate 4. Sanity-check:

- `total_count` is approximately 5,000 (less is OK if active+recent
  projects are below the cap and Tier C can't supplement enough).
- `active_projects` count looks right vs production project count.
- Spot-check a few BINs against `db.projects` to confirm they match
  expected building identifiers.
- Borough distribution of supplemental_random looks city-wide rather
  than concentrated in one borough.

### Gate 4 — Backfill execution (one dataset at a time)

Operator authorizes each dataset separately. Run smallest first:

```bash
# 1. ECB violations (smallest)
python -m scripts.socrata_3year_backfill \
    --dataset ecb-violations --execute

# 2. Permits
python -m scripts.socrata_3year_backfill \
    --dataset permits --execute

# 3. Complaints (largest — last)
python -m scripts.socrata_3year_backfill \
    --dataset complaints --execute
```

After each dataset, run the validation script before authorizing the next:

```bash
python -m scripts._validate_backfill_health \
    --collection socrata_ecb_violations_historical
```

---

## Resume & failure recovery

### Resume after interruption

The backfill writes `_backfill_cursor.json` after every batch. To
resume after a crash, network blip, or operator-initiated Ctrl-C:
**run the same command again.** The cursor's `bin_chunk_index`,
`last_offset`, and (for complaints) `window_start` track exactly where
the run was interrupted; the script picks up from there.

### Dataset cursor mismatch

If the cursor file is for a different dataset than `--dataset`
specifies, the script aborts. This is intentional — it prevents
accidentally resuming the wrong dataset. To start a new dataset:

```bash
# After completing one dataset, delete the cursor to start the next
rm backend/scripts/_backfill_cursor.json
python -m scripts.socrata_3year_backfill \
    --dataset permits --execute
```

(The validation script confirms `cursor.done=true` for the previous
dataset; you should only delete a cursor file with `done: true`.)

### Single-batch failures (transient)

A `SocrataQueryError` or transport exception on one batch is logged
with the full traceback + cursor state, then **the loop continues**.
The batch's rows are counted as failed; the next batch proceeds.

### Circuit breaker

If 10 consecutive batches fail, the script aborts with a runtime
error. This usually means Socrata is down or our token was revoked.
Investigate before re-running.

### Mongo `BulkWriteError` / write conflicts

The script uses `update_one(filter, upsert=True)` per row rather than
`bulk_write`, so a single bad row can't poison the whole batch. If
Mongo itself becomes unavailable mid-run, the circuit breaker trips
after 10 batches; resume after Mongo recovers.

---

## Estimated wall-clock times

These are rough — actual times depend on Socrata response latency,
batch sizes Socrata returns, and Atlas write throughput.

| Dataset            | Est. queries | Est. wall-clock |
| ------------------ | ------------ | --------------- |
| ECB violations     | 25–50        | 5–20 minutes    |
| Permits            | 50–250       | 15–60 minutes   |
| Complaints         | 1,500–3,000* | 3–8 hours       |

*Complaints sees `windows × bin_chunks` queries: 36 windows × 25 chunks ≈
900 minimum, multiplied by pagination depth for chunks with >1000 rows.

The Socrata App Token raises our rate ceiling to ~10,000 req/hr; the
backfill stays well below that, so we are NOT quota-limited under
normal operation.

---

## Index migration notes

All indexes use `create_index(spec, name=...)` with an explicit name.
This is so re-running `_create_backfill_indexes.py` is fully idempotent
(Mongo silently skips if a matching name+spec exists). If you ever need
to change an index's keys, you must drop it explicitly first:

```js
db.socrata_ecb_violations_historical.dropIndex("ecb_violation_number_unique")
```

then re-run `_create_backfill_indexes.py`.

Unique indexes are **sparse** so a row missing the natural key (which
the backfill logs + skips) doesn't trip the unique constraint.

---

## Atlas storage growth projections

For a 3-year × 5,000-BIN backfill (rough order-of-magnitude estimates):

| Collection              | Est. rows  | Est. size | Indexes |
| ----------------------- | ---------- | --------- | ------- |
| `..._ecb_violations...` | 10k–50k    | ~30 MB    | ~5 MB   |
| `..._permits...`        | 50k–200k   | ~150 MB   | ~25 MB  |
| `..._complaints...`     | 30k–100k   | ~80 MB    | ~15 MB  |
| **Total**               | ~100k–350k | ~250 MB   | ~50 MB  |

Budget ~500 MB Atlas storage growth as a safety margin. If the actual
counts come in well above this, the validation script will flag the
out-of-range count for review.

---

## Cleanup procedures

### Aborting a backfill mid-flight

There is no destructive abort. Stop the process (`Ctrl-C`); the cursor
file preserves state. To resume: re-run the same command. To start
over from scratch:

```bash
# 1. Stop the running backfill
# 2. Drop the in-progress collection
mongosh --eval 'db.socrata_ecb_violations_historical.drop()'
# 3. Delete the cursor
rm backend/scripts/_backfill_cursor.json
# 4. Re-run from scratch
python -m scripts.socrata_3year_backfill \
    --dataset ecb-violations --execute
```

### Reverting a completed backfill

```bash
mongosh --eval '
  db.socrata_ecb_violations_historical.drop();
  db.socrata_permits_historical.drop();
  db.socrata_complaints_historical.drop();
'
rm backend/scripts/_backfill_cursor.json
rm backend/scripts/_backfill_target_bins.json
```

This drops the indexes alongside the collections. Re-running Gates 2–4
recreates everything.

### Removing the cursor + target-list artifacts

After all three backfills land + validation passes, the cursor file
and target-BIN file can stay in place as forensic artifacts — they
document what was loaded. Delete them only when running a new backfill
cycle (e.g., expanding the BIN list to 10k).

---

## Files

| Path                                            | Purpose                       |
| ----------------------------------------------- | ----------------------------- |
| `socrata_3year_backfill.py`                     | Main backfill driver          |
| `_create_backfill_indexes.py`                   | Gate 2 index creation         |
| `_select_backfill_target_bins.py`               | Gate 3 BIN list selector      |
| `_validate_backfill_health.py`                  | Post-backfill validation      |
| `_backfill_cursor.json`                         | Resume state (auto-managed)   |
| `_backfill_target_bins.json`                    | 5k BIN list (Gate 3 output)   |
| `_backfill.log`                                 | Per-batch run log             |
| `SOCRATA_BACKFILL.md`                           | This document                 |

---

## Open questions (review before Gate 4)

1. **Permits natural key.** The script defaults to `permit_si_no` as
   the upsert key for `rbx6-tga4`. The directive flagged a composite
   `(job_filing_number, work_permit)` as an alternative. Decision
   pending: confirm against live data shape that `permit_si_no` is
   reliably unique + non-null before Gate 4. If switching to composite
   is needed, the natural-key constant in `DATASETS["permits"]` flips
   from a scalar to `"job_filing_number,work_permit"` + the unique
   index is dropped and re-created on the new fields.

2. **BIN chunk size (200).** Trades off WHERE clause length vs. number
   of paginated queries. 200 keeps WHERE well under Socrata's ~16KB
   limit and produces ~25 chunks for a 5k BIN list. If we see SoQL
   parse errors, lower to 100.

3. **3-year cutoff field per dataset.** Currently:
   - ECB: `issue_date`
   - Permits: `issued_date` (alternatives: `approved_date`, `filing_date`)
   - Complaints: `date_entered`

   `issued_date` is what production code already uses for permit
   actuarial queries; `approved_date` is indexed for downstream use
   but isn't the filter pivot. If we want approved-but-not-issued
   permits in scope, switch the filter to `approved_date`.

4. **Offset-based vs. keyset pagination.** Spec calls for offset
   pagination. Risk: if Socrata rows are added during a long backfill
   walk, the offset can drift (a new row inserted before the current
   offset causes a row to be visited twice or skipped). Mitigation in
   place: the unique index on natural keys means a re-visit is an
   idempotent upsert (no harm), and a skip is recoverable by re-running
   the dataset. If drift becomes a problem, switch to keyset pagination
   via `$where=natural_key > '<last>'`.
