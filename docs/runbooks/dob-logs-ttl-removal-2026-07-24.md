# Runbook — remove the `dob_logs` TTL indexes (2026-07-24)

**Status:** not yet executed. Code removal is committed; the two live Atlas
indexes still exist until steps 3–4 are run by an operator.

## Why

`dob_logs` carried two TTL indexes, both keyed on `detected_at`
(added in MR.14 commit 2a, `2492070`, 2026-05-03):

| Index | Window | `partialFilterExpression` |
|---|---|---|
| `dob_logs_ttl_short` | 90 days (`7776000`s) | `record_type ∈ {permit, complaint, inspection, job_status}` |
| `dob_logs_ttl_long` | 365 days (`31536000`s) | `record_type ∈ {violation, swo}` |

`detected_at` is a **backfill / sync timestamp** — the moment the app first saw
a record — not the date the event occurred. Production verification confirmed
every record on both tracked projects is stamped `2026-07-21` (first sync), so
a 2019 violation and a 2026 violation shared one expiry. The TTL clock measured
*time since first sync*. Left in place it would have physically deleted every
`permit / complaint / inspection / job_status` row around **2026-10-19** and
every `violation / swo` row around **2027-07-21**.

Re-sync cannot restore deleted rows: each Socrata endpoint fetches `$limit=50`,
and a re-inserted row resets `previous_status` and can re-fire Action-severity
alerts.

The only documented justification for the windows was mechanical — `detected_at`
was already a BSON Date and "works without a backfill". There is no legal or
contractual rationale on record. This product's one deliberate retention
decision (`docs/coi-retention-guarantee.md`, 7 years, with a written argument)
points the other way: compliance history should be retained. A GC may need to
produce a violation record years later.

**Decision: option (a) — drop both TTL indexes, retain `dob_logs` indefinitely.**

## Ordering constraint — read before starting

> **Step 1 MUST precede step 3.**
>
> `_ensure_index_resilient` (`backend/server.py:579`) runs on every app startup.
> While the TTL-creating code is still deployed, dropping the indexes is
> temporary: the next deploy or restart re-creates them (and that helper
> explicitly drops-and-recreates on a spec mismatch). Deploy the code removal
> first, then drop.

Out of scope — **do not touch**:
- `db.dob_logs.create_index([("raw_dob_id", 1), ("detected_at", -1)])` — the
  diffing index (`server.py:26811`). Unrelated; still required.
- `detected_at` semantics anywhere. It remains correct for the activity feed
  (`date_range` filter) and the diffing sort.
- `renewal_alert_sent_ttl` (`server.py:26312`) — a different collection.

## Prerequisites

- A **read-write** Atlas connection string for the production cluster
  (steps 3 only; steps 2/4/5 work with read-only).
- Railway access to confirm the deploy and to restart the service.
- PowerShell. Set these once per session — they are never echoed by the
  scripts below:

```powershell
$env:MONGO_URL = '<production Atlas URI>'
$env:DB_NAME   = 'blueview'
```

---

## Step 1 — Confirm the code removal is deployed to Railway

The commit removes the two `_ensure_index_resilient(... expireAfterSeconds ...)`
calls from `backend/server.py` (the TTL block formerly at `26813-26838`).

1. In the Railway dashboard, open the backend service → **Deployments**.
   Confirm the most recent **successful** deployment's commit SHA matches the
   TTL-removal commit on `main`, and that its status is *Active*.

2. Confirm the service is actually serving that build:

```powershell
curl.exe -s https://<your-api-host>/api/health
```

3. Confirm no TTL index work happened at boot. In the Railway logs for that
   deployment, search for `dob_logs_ttl`. On a correct deploy there are **no**
   `Recreating index dob_logs.dob_logs_ttl_*` lines (that message comes from
   `_ensure_index_resilient`, `server.py:604`).

> Do not continue to step 3 until this step passes.

## Step 2 — Read-only: list current indexes and confirm both TTL indexes exist

Save as `check_dob_logs_indexes.py`, run it. **Read-only** — `list_indexes` and
counts only. It never prints the connection string.

```python
"""READ-ONLY. Lists every index on dob_logs with its TTL settings."""
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    print(f"db={os.environ['DB_NAME']}  collection=dob_logs\n")
    async for ix in db.dob_logs.list_indexes():
        ttl = ix.get("expireAfterSeconds")
        line = f"  {ix['name']:<32} key={dict(ix['key'])}"
        if ttl is not None:
            line += f"  TTL={ttl}s ({ttl/86400:.0f}d)"
        if "partialFilterExpression" in ix:
            line += f"  partial={ix['partialFilterExpression']}"
        print(line)
    print(f"\n  total docs: {await db.dob_logs.count_documents({})}")

asyncio.run(main())
```

```powershell
python check_dob_logs_indexes.py
```

**Expected before the drop:** both `dob_logs_ttl_short` (`7776000s`) and
`dob_logs_ttl_long` (`31536000s`) are listed, alongside `_id_`,
`raw_dob_id_1_detected_at_-1`, and the other non-TTL indexes.

Record the full output somewhere before proceeding — it is the rollback
reference.

## Step 3 — Drop `dob_logs_ttl_short` and `dob_logs_ttl_long`

Requires the read-write URI. Save as `drop_dob_logs_ttl.py`:

```python
"""Drops ONLY the two dob_logs TTL indexes. Touches no documents."""
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure

TARGETS = ["dob_logs_ttl_short", "dob_logs_ttl_long"]

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    existing = {ix["name"] async for ix in db.dob_logs.list_indexes()}
    for name in TARGETS:
        if name not in existing:
            print(f"  SKIP  {name} (not present)")
            continue
        try:
            await db.dob_logs.drop_index(name)
            print(f"  DROPPED  {name}")
        except OperationFailure as e:
            print(f"  FAILED   {name}: {e!r}")

asyncio.run(main())
```

```powershell
python drop_dob_logs_ttl.py
```

`dropIndex` is a metadata-only operation: it removes the index structure and
stops the TTL monitor from considering that key. **It does not read, rewrite,
or delete any documents.** It takes a brief collection-level lock to commit the
catalog change; in-flight queries fall back to another plan. Safe online on
Atlas.

## Step 4 — Verify both are gone

```powershell
python check_dob_logs_indexes.py
```

**Expected:** neither `dob_logs_ttl_short` nor `dob_logs_ttl_long` appears; no
index on `dob_logs` reports an `expireAfterSeconds`. `_id_` and
`raw_dob_id_1_detected_at_-1` are still present. Document count is unchanged
from step 2.

## Step 5 — Restart the service, then confirm they do NOT return

This is the step that proves the code removal actually took, and is the whole
reason step 1 comes first.

1. Restart the backend from the Railway dashboard (service → **Restart**), or
   trigger a redeploy of the same commit.
2. Wait for the service to report healthy:

```powershell
curl.exe -s https://<your-api-host>/api/health
```

3. Re-list the indexes:

```powershell
python check_dob_logs_indexes.py
```

**Expected:** still no `dob_logs_ttl_short` / `dob_logs_ttl_long`, still no
`expireAfterSeconds` on `dob_logs`. If either index reappeared, the deployed
build still contains the TTL-creating code — go back to step 1.

## Rollback

**If the drop fails partway** (e.g. `dob_logs_ttl_short` dropped,
`dob_logs_ttl_long` failed):

- **Nothing is lost.** Dropping an index never deletes documents. A partial
  drop leaves the collection in a valid state — one TTL still armed, one not.
- Re-run `drop_dob_logs_ttl.py`. It is idempotent: it skips indexes that are
  already gone and retries the ones that remain.
- If a drop keeps failing, capture the `OperationFailure` and stop. The
  remaining TTL is not an emergency — the earliest expiry is ~2026-10-19 for
  the 90-day bucket. There is runway to resolve it.

**If you need to restore the TTL indexes** (reversing this decision):

```python
# Recreates the exact prior specification. Requires a full index build.
await db.dob_logs.create_index(
    [("detected_at", 1)], name="dob_logs_ttl_short",
    expireAfterSeconds=90 * 24 * 60 * 60,
    partialFilterExpression={"record_type": {"$in": [
        "permit", "complaint", "inspection", "job_status"]}},
)
await db.dob_logs.create_index(
    [("detected_at", 1)], name="dob_logs_ttl_long",
    expireAfterSeconds=365 * 24 * 60 * 60,
    partialFilterExpression={"record_type": {"$in": ["violation", "swo"]}},
)
```

⚠️ Re-creating them re-arms deletion against a sync timestamp. Because every
current record is stamped `2026-07-21`, the TTL monitor (which runs roughly
every 60 seconds) would begin deleting the 90-day bucket as soon as that
threshold passes. **Do not restore these without first re-keying to a real
event date.** Any future retention policy must key on
`violation_date` / `complaint_date` / `expiration_date` / `inspection_date`
(currently stored as strings — a BSON-Date field plus a backfill is required)
and carry a documented legal rationale.

## Post-execution

Once step 5 passes, note the execution date and operator here:

| Date | Operator | Steps completed | Notes |
|---|---|---|---|
| _(pending)_ | | | |
