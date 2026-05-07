# LeveLog Feature Flags — Operator Reference

> Internal-only. Companion to `runbook.md` and `branching.md`.
> Covers the runtime feature-flag system shipped in Phase E1:
> how to create flags, the rollout patterns, and the common
> mistakes that turn a flag into an incident.

**Last reviewed:** 2026-05-06 (Phase E1)

---

## Table of contents

1. [Mental model](#1-mental-model)
2. [Lifecycle of a feature flag](#2-lifecycle-of-a-feature-flag)
3. [Rollout patterns](#3-rollout-patterns)
4. [Reading a flag](#4-reading-a-flag)
5. [Common mistakes](#5-common-mistakes)
6. [Audit log](#6-audit-log)

---

## 1. Mental model

A feature flag is a **boolean switch** the runtime checks before
showing a v2 surface. The default — for both an unknown flag and
a flag with no rollout configured — is **false**. v1 customers
never see a v2 surface unless someone explicitly enabled the
flag for them.

**Resolution order** (in `lib/feature_flags.is_feature_enabled`):

1. Flag missing from DB → `false`. Fail closed.
2. `enabled_globally` true → `true`. Universal on.
3. `company_id` ∈ `enabled_for_companies` → `true`. Per-tenant.
4. `user_id` ∈ `enabled_for_users` → `true`. Per-user override
   (mostly for ourselves during dogfooding).
5. `enabled_percentage > 0` AND
   `hash(salt=flag, identifier) % 100 < pct` → `true`. Rollout.
6. Otherwise → `false`.

**Cache:** in-memory, 60s TTL per flag. Admin writes invalidate
the cache for that flag. Single-instance v1 — when we scale
horizontally, each instance gets its own cache and per-instance
state can drift up to 60s.

---

## 2. Lifecycle of a feature flag

### 2.1 — Create a flag (default OFF)

```bash
curl -X POST https://api.levelog.com/api/admin/feature-flags \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "flag": "v2_dashboard_redesign",
    "description": "Phase E2: redesigned dashboard with Sankey activity strip"
  }'
```

The flag is now in Mongo with `enabled_globally=false` and empty
allow-lists. Reading it via `useFeatureFlag('v2_dashboard_redesign')`
returns `false` for everyone.

**Always create the flag BEFORE the code that reads it.** A
missing flag is always false, but the negative-cache entry
expires every 60s — race conditions on first deploy are easier
to avoid than to debug.

### 2.2 — Wire the read

Backend:

```python
from lib import feature_flags

if await feature_flags.is_feature_enabled(
    db, "v2_dashboard_redesign",
    user_id=str(current_user["id"]),
    company_id=current_user.get("company_id"),
):
    # v2 path
else:
    # v1 path (unchanged)
```

Frontend:

```jsx
import { useFeatureFlag } from '../src/hooks/useFeatureFlag';

function Dashboard() {
  const showV2 = useFeatureFlag('v2_dashboard_redesign');
  return showV2 ? <V2Dashboard /> : <V1Dashboard />;
}
```

The hook returns `false` while the flag map is loading — this
is the **fail-closed during loading** invariant. v1 users never
see a flicker of v2 UI on every navigation.

### 2.3 — Roll out

Pick one of the patterns in §3. Start small. Observe.

### 2.4 — Clean up

Once a flag is at 100% globally for a sustained period (typically
2-4 weeks) AND the v1 code path has no remaining customers:

1. Delete the v1 code branch — leave only the v2 path.
2. Remove the `is_feature_enabled` / `useFeatureFlag` call.
3. DELETE the flag via `DELETE /api/admin/feature-flags/<flag>`.
   The audit log preserves the prior shape so the deletion is
   reversible.

Flag debt is real — every flag is a permanent branch in code
+ DB unless cleaned up. Schedule a quarterly "flag prune" review.

---

## 3. Rollout patterns

### 3.1 — Canary

Enable for ONE friendly customer. Watch for a week. Expand.

```bash
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled_for_companies": ["<friendly_company_id>"]}'
```

What to watch:

- **Sentry** — any new issues tagged with that company_id?
- **Customer feedback** — call them after 3 days, ask for
  unprompted reactions.
- **Activity feed** — usage patterns sane? No spike of error
  events? No drop in engagement?

If clean after a week, expand to 5–10 companies. If there's
even ONE bug, fix the bug AND wait another week before
expanding.

### 3.2 — Percentage rollout

For features that don't need per-customer control — UI
refreshes, performance optimizations, copy changes. Gradual
ramp.

```
Week 1:  enabled_percentage=10
Week 2:  enabled_percentage=50
Week 3:  enabled_percentage=100
```

Each step: PATCH the flag, wait. The percentage bucketing is
**deterministic** (hash of `flag + identifier`) — a customer
who's in at 10% stays in at 50% and 100%. They don't get
moved out as the percentage grows; new customers are added
to the in-bucket.

```bash
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
  -d '{"enabled_percentage": 50}'
```

If something breaks at any step, roll back to the last known
good percentage:

```bash
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
  -d '{"enabled_percentage": 10}'
```

The cache invalidates within 60s; the next /me read by an
affected user sees the new value.

### 3.3 — Kill switch

A feature is at 100% globally and production breaks. Disable
INSTANTLY:

```bash
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
  -d '{"enabled_globally": false, "enabled_percentage": 0,
       "enabled_for_companies": [], "enabled_for_users": []}'
```

This is the analog of `NOTIFICATIONS_KILL_SWITCH` (runbook §1)
but per-feature. Clears every rollout vector at once. Cache
invalidates within 60s.

After the kill: every reader returns `false` again. v1 path is
restored. Fix the bug. Re-enable carefully (back to canary or
small percentage; don't jump straight to 100%).

### 3.4 — Per-user override (for our own team)

Useful for dogfooding. Add specific user_ids to
`enabled_for_users`:

```bash
curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
  -d '{"enabled_for_users": ["<my-user-id>", "<teammate-user-id>"]}'
```

These override the percentage rollout — even if percentage is
0, listed users see the feature. Useful for "I want to test
this before we expose it to anyone".

---

## 4. Reading a flag

### 4.1 — Backend

```python
from lib import feature_flags

# Inside an async route handler
enabled = await feature_flags.is_feature_enabled(
    db, "v2_dashboard_redesign",
    user_id=str(current_user["id"]),
    company_id=current_user.get("company_id"),
)
```

Both `user_id` and `company_id` are optional — pass whichever
is available. With neither, only `enabled_globally` can return
true. (Percentage rollouts need an identifier to bucket.)

### 4.2 — Frontend

```jsx
import { useFeatureFlag } from '../src/hooks/useFeatureFlag';

const showV2Hero = useFeatureFlag('v2_dashboard_hero');
```

The hook reads from a per-session cache populated by
`GET /api/feature-flags/me` at app boot. The cache refreshes
on auth changes (login / logout / `validateSession`). Within
a session, flag reads are pure + synchronous — no async, no
fetch on every render.

### 4.3 — Reading the full map (debug)

```jsx
import { useFeatureFlagsContext } from '../src/context/FeatureFlagsContext';

function FlagsDebug() {
  const { flags, loaded, refresh } = useFeatureFlagsContext();
  return loaded ? <pre>{JSON.stringify(flags, null, 2)}</pre> : 'loading...';
}
```

Mostly for debug screens. Production code should prefer the
single-flag hook.

---

## 5. Common mistakes

### 5.1 — Forgetting to create the flag before deploying the code

**Symptom:** the v2 surface never appears, even after enabling
the flag.

**Cause:** the flag wasn't created via the admin endpoint;
`is_feature_enabled` always returns `false` for missing flags.
The negative cache entry has a 60s TTL, so creating the flag
NOW means readers see it within 60s.

**Fix:** POST `/api/admin/feature-flags` with the flag name.
The cache invalidate runs on POST so the next read sees the
new flag immediately.

### 5.2 — Default ON

**Don't.** New flags should default OFF. Even
`enabled_globally=true` at creation time should be a deliberate
choice (typically only for a feature that's already been
validated through some other rollout path and you're just
codifying it as a permanent on).

If you find yourself wanting "default ON" because it's "safer"
to ship the v2 path: that means v2 is ready to remove the v1
path entirely. Delete the flag, drop the v1 branch.

### 5.3 — Reading a flag without an identifier

```python
# Wrong — percentage rollouts can't bucket without an identifier.
enabled = await feature_flags.is_feature_enabled(db, "v2_x")

# Right — pass user_id or company_id (either or both).
enabled = await feature_flags.is_feature_enabled(
    db, "v2_x",
    user_id=str(user["id"]),
    company_id=user.get("company_id"),
)
```

If neither is available (e.g. an unauthenticated endpoint),
percentage rollouts will never match — the flag falls to
`enabled_globally` only. That's usually what you want for
public endpoints; document it as an explicit choice.

### 5.4 — Branching on a flag inside a hook

```jsx
// Wrong — hook order changes when the flag flips.
function MyComponent() {
  if (useFeatureFlag('v2_x')) {
    const [foo, setFoo] = useState(0);  // CONDITIONAL HOOK
  }
  // ...
}
```

This is React error #310 territory (see C1.1 / C1.3 history).
The fix: read the flag at the top of the component, then
branch on the boolean for the JSX render — never around hook
calls.

```jsx
// Right
function MyComponent() {
  const showV2 = useFeatureFlag('v2_x');
  const [foo, setFoo] = useState(0);  // unconditional
  // ...
  return showV2 ? <V2 /> : <V1 />;
}
```

The static-source pin in `test_c1_1_hook_rules.py` will catch
this if you re-introduce the pattern.

### 5.5 — Caching identity across users

Each authenticated session gets its own flag map. If you log
out as user A and back in as user B, the FeatureFlagsProvider
re-fetches automatically — its `useEffect` watches `user.id`.

**Don't** persist the flag map to AsyncStorage / localStorage.
A user's flag set should die with their session. Persisting
across sessions creates a "I logged out but still see v2"
class of bug that's hard to reproduce.

---

## 6. Audit log

Every admin write (create / update / delete) writes a row to
`feature_flag_audit_log`:

```
{
  flag: "v2_dashboard_redesign",
  action: "updated",
  before: { enabled_percentage: 10, ... },
  after:  { enabled_percentage: 50, ... },
  changed_by_user_id: "<admin user id>",
  changed_at: ISODate(...),
}
```

### 6.1 — "Who changed what when" query

```js
db.feature_flag_audit_log
  .find({flag: "v2_dashboard_redesign"})
  .sort({changed_at: -1})
  .limit(20)
  .pretty()
```

Use this when triaging an incident: "Did anyone touch
v2_dashboard_redesign between 14:00 and 15:00?"

### 6.2 — Reverting via audit log

The `before` field on an update / delete row carries the prior
shape. To revert a bad rollout:

```
> last_good = db.feature_flag_audit_log.findOne(
    {flag: "v2_dashboard_redesign", action: {$ne: "deleted"}},
    {sort: {changed_at: -1}}
  ).before

# PATCH the flag back to the prior shape
> curl -X PATCH https://api.levelog.com/api/admin/feature-flags/v2_dashboard_redesign \
    -d "$(echo $last_good | jq '{enabled_globally, enabled_for_companies, enabled_for_users, enabled_percentage}')"
```

Manual but auditable — preferable to ad-hoc Mongo writes.

### 6.3 — Retention

The audit log is append-only and not currently pruned. At our
scale (dozens of flags, occasional rollout changes) this is
fine for years. If the collection ever grows past 100k rows,
add a periodic prune of `action="updated"` rows older than
6 months — keep `created` and `deleted` indefinitely.
