# LeveLog Branching & Staging — Operator Reference

> Internal-only. Companion to `runbook.md` and `feature-flags.md`.
> Covers the v2-development branching strategy, the staging
> environment, and the procedure for keeping staging's data fresh
> from production.

**Last reviewed:** 2026-05-06 (Phase E1)

---

## Table of contents

1. [Branch strategy](#1-branch-strategy)
2. [Releases & tags](#2-releases--tags)
3. [Staging environment](#3-staging-environment)
4. [Staging Mongo database](#4-staging-mongo-database)
5. [Refresh cadence](#5-refresh-cadence)

---

## 1. Branch strategy

```
                         ┌─────────────┐
                         │   main      │  production v1
                         │  (frozen)   │  bug fixes + small v1 enhancements
                         └─────┬───────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
        ┌──────────┐     ┌──────────┐      ┌──────────┐
        │ hotfix/* │     │  v1.x    │      │ develop  │  v2 active work
        │  (urg.)  │     │  bumps   │      │ → staging│
        └─────┬────┘     └────┬─────┘      └────┬─────┘
              │               │                 │
              │               │             ┌───┴────┐
              │               │             ▼        ▼
              │               │       ┌─────────┐ ┌─────────┐
              │               │       │feature/A│ │feature/B│  per-feature
              │               │       └────┬────┘ └────┬────┘  branches
              │               │            │           │
              │               │            └─────┬─────┘
              │               │                  │ (when ready)
              │               │                  ▼
              │               │            ┌──────────┐
              │               │            │ develop  │  ← merge target
              └───────────────┴────────────┴──────────┘
```

### `main` — production v1

- Receives **only** bug fixes and small v1 enhancements.
- Every commit on `main` deploys to production (Railway backend +
  Vercel frontend).
- Tagged at every release boundary (see §2).
- v2 work NEVER merges directly to `main`. v2 features land
  behind feature flags (default OFF) only after they've been
  validated on `develop` / staging.

### `develop` — v2 active work

- Default branch for all v2 development.
- Every push deploys to **staging** (see §3).
- Features assemble here as `feature/*` branches merge in.
- When a v2 feature is ready for production: merge `develop` → `main`
  with the feature flag default OFF, then ramp via the rollout
  patterns in `feature-flags.md`.

### `feature/<name>` — per-feature branches

- Branched **off `develop`**, NOT off `main`. Always the most
  current v2 baseline.
- One branch per feature. Naming: `feature/v2-dashboard`,
  `feature/v2-activity-feed`, etc.
- Each push gets a Vercel preview URL automatically — share it
  for design review without polluting staging.
- Merge back to `develop` when the feature's invariant tests
  pass and the static-source pins (per the patterns established
  in B0.1 / B3 / C1.1) are in place.

### `hotfix/<name>` — emergency v1 patches

- Branched **off `main`**. Used only when production is broken
  and `develop` carries v2 changes that aren't yet ship-ready.
- Merge back to `main` AND `develop` so the fix doesn't get
  lost when v2 eventually merges down.

### Merge rules

| From | To | When |
|---|---|---|
| `feature/*` | `develop` | Feature complete + tests pass |
| `develop` | `main` | v2 feature passed staging validation; flag added with default OFF |
| `hotfix/*` | `main` | Emergency fix |
| `hotfix/*` | `develop` | Same fix, propagated forward |

NEVER:

- Direct push to `main` (CI gating recommended; not yet wired).
- Merge `main` → `develop` (it's the wrong direction; bug fixes
  flow from hotfix into both, not main into develop).

---

## 2. Releases & tags

Every production release is tagged. Tags are annotated and pushed
to origin so anyone with repo access can `git checkout v1.0.0` and
build that exact baseline.

### 2.1 — Current tags

| Tag | Date | Phase content |
|---|---|---|
| `v1.0.0` | 2026-05-06 | Phase A–D + F1. BLUEVIEW launch baseline. Customer onboarding, activity feed, notification preferences, Sentry + rate limits + backups + voice ingestion. |

(Operator: append to this table at each release.)

### 2.2 — Cutting a release tag

```
git checkout main
git pull
# verify tests + smoke production
git tag -a v1.x.0 -m "Phase X.Y description"
git push origin v1.x.0
```

Update §2.1 in this doc as part of the same PR / commit so the
tag's content is documented alongside it.

### 2.3 — Reverting via tag

If a production deploy goes sideways and rolling forward isn't
fast enough:

```
git checkout v1.0.0    # the previous good tag
# Either: trigger a Railway redeploy from this commit
# Or:    git push -f origin main  (DESTRUCTIVE — coordinate)
```

Prefer Railway's "Redeploy this commit" button (no destructive
git ops, immediate).

---

## 3. Staging environment

### 3.1 — Frontend (Vercel)

- Vercel auto-creates a preview URL for every non-`main` branch.
- The latest `develop` deploy is **staging**.
- Operator action: in Vercel dashboard, alias
  `staging.levelog.com` → "latest deploy on `develop`". Vercel
  calls this "production branch override" or "promote to
  production" depending on UI version. Once aliased, every
  `develop` push auto-publishes to `staging.levelog.com` ~30
  seconds later.
- Sentry events from staging tag `environment=staging`
  (per `EXPO_PUBLIC_ENVIRONMENT` set on the Vercel project's
  develop deploys — see runbook §10 for the env-var wiring).

### 3.2 — Backend (Railway)

Two viable patterns. Pick one and stick with it:

**Pattern A: separate Railway service.**
- Create `levelog-backend-staging` as a clone of the production
  service.
- Point its `MONGO_URL` at the staging database (see §4).
- Set `RAILWAY_ENVIRONMENT=staging`.
- Set `SENTRY_ENVIRONMENT=staging` (so Sentry filters cleanly).
- Configure Railway → service → Source → "auto-deploy from
  branch: `develop`".
- Custom domain: `api-staging.levelog.com` → this service.

**Pattern B: same service, environment-aware MONGO_URL.**
- Single Railway service, but Production env reads `MONGO_URL_PROD`
  and Preview env reads `MONGO_URL_STAGING`. Code reads
  `os.environ["MONGO_URL"]` unchanged; Railway's per-environment
  variable mapping handles the routing.
- Less infra to maintain; harder to spot which env you're in
  from the dashboard.

Recommended: **Pattern A** for v1.x. Simpler mental model for
the on-call operator (production and staging are clearly
separate services with separate logs).

### 3.3 — What staging gives you

- A live system pointed at v2 code without risk to production.
- Works with the same auth tokens (you log in with production
  credentials; staging doesn't have its own user database
  unless you provision one).
- Same Sentry project on the back end with `environment=staging`
  — filter at issue triage time.
- Same Atlas API quota for backups (staging cluster is separate
  from production cluster).

### 3.4 — What staging isn't

- Not a load-test environment. Atlas Flex tier is fine for
  manual smoke testing; don't run synthetic traffic against
  staging unless you've discussed it with the team — it shares
  the same OpenAI / Whisper / WaAPI quotas and burning them on
  a smoke test affects production.
- Not a long-term sandbox. Refresh staging from production
  monthly (see §5) so testing reflects actual data shapes.
- Not a substitute for unit tests. v2 features ship to staging
  AFTER passing the test suite, not as a replacement for
  passing it.

---

## 4. Staging Mongo database

Atlas Flex supports multiple databases on the same cluster at no
extra cost — staging gets its own database in the production
cluster, NOT a separate cluster. (A separate cluster would
double the Atlas bill for marginal isolation benefit; the
database boundary is sufficient.)

### 4.1 — One-time setup

1. Atlas → production cluster → Connect → Connect to your
   application. Copy the URI template.
2. The URI ends with `/<database>`. For staging, rewrite the
   database segment to `blueview-v2`. Save it as
   `MONGO_URL_STAGING` somewhere safe (Railway vars, 1Password).
3. Mongo will auto-create the database on first write, but it's
   cleaner to seed it:

```
mongodump --uri="$MONGO_URL_PROD" --db=blueview \
  --out=/tmp/staging-seed-$(date +%F)

mongorestore --uri="$MONGO_URL_STAGING" \
  --nsFrom='blueview.*' --nsTo='blueview-v2.*' \
  /tmp/staging-seed-$(date +%F)
```

The `--nsFrom`/`--nsTo` rewrites the target database name during
restore so the same dump file can re-seed staging without a
production mongorestore.

4. Verify by connecting to the staging URI and running
   `db.users.count_documents({})` — count should match production
   (within a small margin if production saw writes mid-dump).

### 4.2 — Refresh from production

When staging data is stale or you want the latest production
shape:

```
# Always take a fresh dump for the refresh — don't reuse the
# original seed dump from §4.1.
mongodump --uri="$MONGO_URL_PROD" --db=blueview \
  --out=/tmp/staging-refresh-$(date +%F)

# Drop + restore. The --drop flag clears the target collections
# before restoring; without it you'd append to existing data.
mongorestore --uri="$MONGO_URL_STAGING" \
  --nsFrom='blueview.*' --nsTo='blueview-v2.*' \
  --drop \
  /tmp/staging-refresh-$(date +%F)
```

### 4.3 — Hard rules

- **NEVER mongodump from staging back to production.** The
  refresh flow is one-way: production → staging only. A
  reverse dump would overwrite real customer data with whatever
  v2 test artifacts have accumulated.
- **NEVER use `--drop` against the production URI.** Pin
  `MONGO_URL_PROD` and `MONGO_URL_STAGING` in shell history /
  scripts so an absentminded paste can't mix them up.
- **Refresh during low-traffic hours.** mongodump puts read
  load on the production cluster. Off-hours (early morning ET,
  weekend) is the right window.
- **Sanitize after refresh if needed.** If staging will be
  shared with engineers who shouldn't see customer PII, run a
  scrubber against `users.email`, `users.phone`,
  `whatsapp_messages.body`, etc. v1 doesn't have a scrubber
  script; build one if/when staging access expands.

---

## 5. Refresh cadence

| Trigger | Action |
|---|---|
| Monthly (calendar) | Refresh staging from production per §4.2. |
| Before major v2 feature work | Refresh so v2 development uses current data shapes. |
| After a production migration | Refresh so staging sees the post-migration shape too. |
| Staging weirdness ("worked yesterday, broken today") | Refresh and re-test before opening a bug report. |

When in doubt: refresh. `mongodump` + `mongorestore` against the
current production tier is fast (< 5 min for our scale) and
removes "stale staging data" as a possible cause when v2
features misbehave.
