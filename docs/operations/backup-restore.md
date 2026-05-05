# LeveLog Backup & Restore — Operator Reference

> Internal-only document. Companion to `docs/operations/runbook.md`.
> Covers everything an operator needs to know to **(a)** trust that
> production data is backed up and **(b)** recover it when something
> goes catastrophically wrong.

**Last reviewed:** 2026-05-05 (Phase C3)
**Tested restore drill:** _pending — operator must perform per §3
                         and update this line with the actual date_

---

## Table of contents

1. [Backup state](#1-backup-state)
2. [What's protected](#2-whats-protected)
3. [Restore drill (operator action)](#3-restore-drill-operator-action)
4. [Disaster recovery — production restore](#4-disaster-recovery--production-restore)
5. [Migration safety pattern](#5-migration-safety-pattern)
6. [Backup freshness verification](#6-backup-freshness-verification)
7. [Notes for next operator](#notes-for-next-operator)

---

## 1. Backup state

> **Operator action:** before the next deploy review, fill in the
> "your cluster" column from the Atlas dashboard:
> Atlas → Database → cluster → Backup tab.

| Property | Default for v1 | Your cluster |
|---|---|---|
| Plan tier | Atlas M10 (recommended for prod) | _fill in_ |
| Backup capability | Continuous Cloud Backup (PITR) on M10+; snapshot-only on M0/M2/M5 | _fill in_ |
| Snapshot cadence | every 6 hours (M10 default) | _fill in_ |
| Snapshot retention | 7 days (M10 default; configurable) | _fill in_ |
| PITR window | 1 day (M10 default; up to 7 days configurable) | _fill in_ |
| Snapshot retention — weekly / monthly | varies; check Atlas → Backup → Schedule | _fill in_ |
| Recovery Point Objective (RPO) | ≤ 6 hours scheduled snapshot OR seconds via PITR (M10+) | _fill in_ |
| Recovery Time Objective (RTO) | 5–30 minutes for a small cluster (production: ~700 dob_logs / ~few hundred users) | _fill in after drill_ |

**M0 / M2 / M5 (free + shared tiers) DO NOT support continuous
backup.** They get snapshot-only, often with no schedule we
control. If the cluster is on a shared tier, the disaster scenario
"someone deleted a collection at 11:47 AM" loses everything since
the most recent snapshot. **For production, the cluster MUST be
M10 or higher.** This is non-negotiable; the rest of this doc
assumes it.

---

## 2. What's protected

Atlas backups capture **the entire database snapshot, all
collections, all indexes, all documents.** Specifically:

- All collections under the production `DB_NAME` (default:
  `levelog`).
- Indexes (re-built on restore — no manual `_ensure_index_resilient`
  needed).
- Document data including the recently-introduced fields:
  `users.onboarding_step` / `onboarding_completed_at` (Phase B3),
  `projects.first_poll_completed_at` / `first_poll_summary`
  (Phase B3), `companies.filing_reps[]` (MR.2 + B3),
  `notification_preferences.*` (Phase B1).

What's **NOT** in the Atlas backup:

- Cloudflare R2 file storage (project files, COI uploads, daily
  log photos). R2 has its own retention; we do not currently
  snapshot it. Loss of R2 = loss of attached files until they're
  re-uploaded by the customer. _Flagged for v1.1 work._
- Sentry events. Sentry retains 30 days on the free tier; older
  events are discarded by Sentry. We do not back up Sentry.
- Railway environment variables. They live in Railway's own
  secret store; if Railway loses them, the Atlas restore is
  useless until the env vars are reconfigured. _Operator should
  keep an offline copy in 1Password (or equivalent)._

---

## 3. Restore drill (operator action)

**Why:** continuous backup is only as good as the restore that's
been tested. An untested restore is a future incident. This drill
proves the entire Atlas → restore → verify flow works end to end,
gives us a measured RTO, and surfaces any operator-side gotchas
(connection-string formats, IP allowlist mismatches, etc.) BEFORE
they matter.

**When:** once now (Phase C3 acceptance), then quarterly.

**Time budget:** 15-30 minutes.

### 3.1 — Setup

1. Atlas → Project → Database. Note the production cluster name
   (e.g. `levelog-prod`).
2. Click **Build a Database** → choose **M0 Free** (or M2/M5 if
   you want a closer-to-prod baseline). Name it something obvious:
   `restore-drill-YYYYMMDD`.
3. Choose any region; doesn't matter for the drill.
4. **Wait for the cluster to provision.** ~5 minutes.

### 3.2 — Trigger the restore

1. Atlas → Database → click the **production** cluster → **Backup**
   tab.
2. Find the most recent snapshot under "Snapshots". Click the
   three-dot menu → **Restore**.
3. Restore target: **Restore to a new cluster** (NEVER "Restore
   in place" during a drill — that overwrites production).
4. Pick `restore-drill-YYYYMMDD` as the target cluster.
5. Confirm. Atlas displays an estimated completion time.
6. **Note the start time.** This is for measuring RTO.

### 3.3 — Verify

While Atlas restores (5–15 minutes), prepare a verification
checklist:

```python
# Connect to the drill cluster.
import os
from motor.motor_asyncio import AsyncIOMotorClient

drill_uri = "mongodb+srv://...drill cluster..."
client = AsyncIOMotorClient(drill_uri)
db = client[os.environ["DB_NAME"]]

# Smoke checks — adjust if your prod has different scale.
await db.users.count_documents({})              # expect: ≈ prod
await db.projects.count_documents({})           # expect: ≈ prod
await db.dob_logs.count_documents({})           # expect: ≈ prod
await db.companies.count_documents({})          # expect: ≈ prod
await db.notification_preferences.count_documents({})  # expect: ≈ prod

# Spot-check a known prod record.
await db.companies.find_one({"name": "BLUEVIEW CONSTRUCTION INC"})
# → returns the company doc with the right fields.

# Index sanity.
list(await db.dob_logs.list_indexes().to_list(50))
# → includes the (project_id, raw_dob_id) compound index, etc.
```

If counts and spot-checks match production, the restore worked.
**Note the completion time.** RTO = `completion - start`.

### 3.4 — Tear down

1. Atlas → drill cluster → … → **Terminate Cluster**. Free-tier
   clusters cost nothing to keep around but accumulate junk;
   tear down once verification's done.
2. Update the "Last reviewed" / "Tested restore drill" lines at
   the top of this doc with today's date and the measured RTO.

---

## 4. Disaster recovery — production restore

Use this only when production data has been corrupted or lost
and there's no in-flight fix path that's faster.

### 4.1 — When to use

- **Yes:** a migration script wiped a collection. A Mongo command
  injection deleted documents. Atlas itself reports cluster
  corruption.
- **No:** a customer says "my data looks wrong." That's a bug
  report, not a DR event. Investigate normally.
- **No:** you want to "roll back" to yesterday because today's
  release shipped a UI bug. Roll back the deploy, not the data.
  Restoring data invalidates every change every customer made
  today.

DR restore is **destructive** for any customer activity that
happened between the backup point and now. Treat it as a last
resort.

### 4.2 — The procedure

**Estimated downtime:** 15–60 minutes depending on cluster size.

1. **Communicate.** Post in #incident: "Production restore
   beginning at HH:MM. Site will be read-only / unavailable
   for ~30 min."
2. **Activate the kill switch.** Stop notifications going out
   during a restore — the data may include emails that were
   "in flight" at backup time.

   ```
   Railway → backend → Variables → NOTIFICATIONS_KILL_SWITCH=true
   → Save & redeploy
   ```

3. **Stop the backend.** Railway → backend service → **Pause**.
   This prevents new writes during the restore window.
4. **Atlas → production cluster → Backup tab.** Pick the snapshot
   to restore (or Point-in-Time, if PITR is configured).
5. **Restore in place** (the destructive option). Atlas will
   confirm: "This will replace cluster data with snapshot from
   <timestamp>." Type the cluster name to confirm.
6. **Wait for the restore to complete.** Atlas dashboard shows
   progress. Don't touch the cluster while it runs.
7. **Smoke test.** Connect via mongo shell or the drill-style
   verification queries from §3.3. Confirm collection counts
   match the snapshot.
8. **Resume the backend.** Railway → backend → **Resume**.
9. **Unset the kill switch.**

   ```
   Railway → NOTIFICATIONS_KILL_SWITCH=false → Save & redeploy
   ```

10. **Smoke the live site.** Open www.levelog.com, log in, walk
    through dashboard / activity feed / settings. Watch Sentry
    for errors.
11. **Communicate.** Post in #incident: "Restore complete at
    HH:MM. Investigating root cause of [original incident]."

### 4.3 — Required env vars / secrets to reconfigure

If the production Atlas cluster URI changes (e.g. you restored
to a new cluster instead of in-place):

- Railway → backend → Variables → **MONGO_URL** updated to
  point at the new cluster.
- All other secrets (`JWT_SECRET`, `RESEND_API_KEY`, `R2_*`,
  `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `RATE_LIMITS_DISABLED`,
  `NOTIFICATIONS_KILL_SWITCH`) survive the restore — they live
  on Railway, not in Mongo.

### 4.4 — Rollback if restore itself fails

If Atlas reports a restore failure:

1. The pre-restore cluster state is preserved (Atlas keeps a
   "before" snapshot automatically). Atlas → cluster → Backup
   → look for the auto-snapshot Atlas took at restore start.
2. Restore-in-place THAT snapshot.
3. Now you're back to the pre-DR state. The original incident
   isn't fixed, but you haven't lost more data.
4. Open a Sentry warning manually with `_default_sentry_capture`:
   "DR restore failed for cluster=<name>". This is a "page
   advisor immediately" event.

---

## 5. Migration safety pattern

> **Hard rule:** every script under `backend/scripts/migrate_*.py`
> requires an Atlas snapshot taken AFTER the previous migration
> and BEFORE the new one runs.

### 5.1 — Workflow

1. **Take an on-demand Atlas snapshot.**
   - Atlas → production cluster → Backup tab → **Take Snapshot
     Now**. Name it after the migration: `pre-mr14-foo-2026-05-05`.
   - Wait for the snapshot to complete (typically 1–3 minutes for
     small clusters). Don't run the migration until the snapshot
     row turns green.
2. **Dry-run the migration.**
   - Every script under `backend/scripts/migrate_*.py` accepts a
     `--dry-run` flag (or defaults to dry-run; check the script
     header). The dry-run prints what would change without
     touching the DB.
   - Inspect the dry-run output for unexpected matches. If the
     count is wildly higher or lower than you expected, STOP.
3. **Execute.**
   - Re-run with `--execute` (or whatever the script's "really do
     it" flag is).
   - Capture stdout to a file:
     `python -m scripts.migrate_foo --execute > logs/migrate-foo-$(date +%F).log`
4. **Verify.**
   - Run `audit_production.py` (Phase B2) against the post-
     migration database. Compare key counts to your dry-run's
     "would change" tally.
   - Spot-check a few of the affected records.

### 5.2 — If the migration corrupts data

1. **Stop further migration runs.** Don't try to "fix forward."
2. **Restore from the pre-migration snapshot you took in step 1.**
   - Atlas → cluster → Backup → find your `pre-mr14-foo-...`
     snapshot → Restore in place (per §4 procedure above).
3. **Investigate the migration script.**
   - Don't re-run until the bug is fixed AND you have a fresh
     pre-migration snapshot.

### 5.3 — When to use a local mongodump instead

For very small migrations (touching <100 documents) where waiting
for an Atlas snapshot is overkill:

```bash
mongodump --uri="$MONGO_URL" --db="$DB_NAME" \
  --collection="<the_collection>" \
  --out=/tmp/pre-mr14-foo-$(date +%F)
```

Restore via:

```bash
mongorestore --uri="$MONGO_URL" --db="$DB_NAME" \
  --drop /tmp/pre-mr14-foo-2026-05-05/$DB_NAME/
```

The `--drop` flag is destructive — it drops the collection before
restoring. Use only for narrowly-scoped collections.

`mongodump` works for any cluster tier (including M0 / shared);
Atlas snapshots are the right tool for full-cluster recovery,
but for a quick safety net before a 50-doc migration, local dump
is faster.

---

## 6. Backup freshness verification

### 6.1 — Why

Atlas does NOT alert when scheduled backups stall (e.g. quota
exhausted, cluster paused, billing suspended). The only way to
know is to check the snapshots list periodically. Phase C3
ships a script for that.

### 6.2 — How to run

```bash
ATLAS_PUBLIC_KEY=xxx \
ATLAS_PRIVATE_KEY=yyy \
ATLAS_GROUP_ID=<24-char-hex> \
ATLAS_CLUSTER_NAME=<cluster> \
ATLAS_BACKUP_MAX_AGE_HOURS=24 \
SENTRY_DSN=<frontend-or-backend-DSN> \
python -m scripts.verify_backup_freshness
```

Exit codes:

- `0` — most recent snapshot is within `ATLAS_BACKUP_MAX_AGE_HOURS`.
  Nothing to do.
- `1` — backup is stale OR Atlas API call failed. Sentry warning
  fired (if DSN configured). Investigate.
- `2` — bad invocation (missing required env var). Treat as
  operator config error.

### 6.3 — Cadence

- **Recommended:** once a week, via a Railway cron job or local
  cron on the operator's machine. Set `ATLAS_BACKUP_MAX_AGE_HOURS=168`
  (7 days) for weekly runs, or stick with `24` if running daily.
- **Minimum:** monthly, as a calendar reminder for the on-call
  operator.

If a stale-backup warning fires, the on-call operator should:

1. Atlas → production cluster → Backup tab → check the
   "Snapshots" list manually. Confirm what the script saw.
2. If snapshots actually stopped: Atlas → Project → Backup →
   check for an alert banner. Common causes:
   - Cluster was paused (free-tier auto-pause after 60 days
     idle).
   - Atlas billing card declined (Atlas → Billing).
   - Storage quota exceeded.
3. Resolve the underlying cause, then trigger an on-demand
   snapshot to confirm scheduled backups have resumed.

### 6.4 — Atlas API key setup

The script needs a Programmatic API key. Create it once:

1. Atlas → Project → Access Manager → API Keys → Create.
2. Name: `backup-freshness-cron`.
3. Permissions: **Project Read Only** (sufficient — we only
   list snapshots, never restore).
4. Copy the public + private key (private shown ONCE).
5. Add the Vercel/Railway IP allowlist if running from there;
   for operator-laptop runs, click "Allow Access from Anywhere"
   for the cron job's source.
6. Stash the keys in 1Password under `LeveLog → Atlas → backup-freshness-cron`.

---

## Notes for next operator

- The restore drill is the load-bearing piece of this doc. If
  you haven't done it, you don't actually have a tested backup
  — you have hope.
- Atlas's "in-place restore" is destructive. The drill (§3) uses
  "restore to new cluster" specifically to keep production safe
  while you practice.
- v1 ships single-region; if Atlas's primary region goes down,
  restore won't help until Atlas itself recovers. Multi-region
  failover is v1.1+ work.
- The `verify_backup_freshness.py` script exits non-zero on
  Atlas API failure (network blip, 5xx). That's by design — a
  blip every few weeks is acceptable noise; sustained blips
  dedup-stack in Sentry and become a real signal.
- R2 file backups are NOT in scope for v1. If a customer's COI
  upload is lost, they re-upload it. If the loss pattern is
  systematic, treat it as a v1.1 priority and budget for R2
  cross-region replication.
