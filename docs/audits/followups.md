# Audit follow-ups

Running log of deferred fixes surfaced during audits. Newest first.

---

## DROPBOX — 2026-08-27 — two bounds left standing by #242

Both are real, both were reported before merging, and neither is fixed. #242
made the displayed count come from the sync response instead of a mid-sync
re-read of `project_files`; these are what that did not reach.

### 1. `file_count` never paginates, so the displayed target undercounts

`sync_project_dropbox` gathers its "Quick count from Dropbox for immediate
response" with a single `list_folder` call:

    json={"path": api_path, "recursive": True}

and never checks `has_more` / `list_folder/continue`. Past roughly 500 entries
the returned `file_count` is short by everything after page one.

STORED ROWS STAY CORRECT. `_sync_project_to_r2` paginates properly, so the
files themselves all arrive; only the number the screen shows is low. That
asymmetry is why this was left: the bug is cosmetic today and becomes a
support call only on a project big enough to cross a page boundary.

Note the same missing pagination in `get_dropbox_folders`, where it is NOT
cosmetic -- a directory whose first page is all files returns an empty folder
list, and the picker renders "no folders" on a folder that plainly has some.

### 2. Pressing Sync caches a PARTIAL list for offline

`sync-dropbox` "returns immediately, runs sync in background". The plans screen
then re-reads the list -- it renders rows, so it must -- and hands the result to
`adoptFiles`, which runs `cacheDocList`. That write-through is therefore a
MID-SYNC snapshot: the saved-for-offline list can be a strict subset of what
the project holds, and it is the copy the CP gets in a cellar.

Fixing it needs a completion signal the endpoint does not offer. `sync-dropbox`
returns before the task starts writing, and nothing polls or pushes. Options
are a status endpoint, a job id, or having the task stamp a terminal marker the
client can wait on -- all of which are the redesign, not a patch.

FILE THIS WITH ITEM 12, the offline warm with no observable state. They are one
problem: `warmDocCache` is fire-and-forget, sequential, `limit: 15` with no
sort despite a docstring promising "newest first", swallowed by `.catch(() =>
{})`, and NOTHING on screen ever reports what is on disk -- `getCachedDocFile`
is never called in the render path. A partial cached list is invisible for the
same reason a failed warm is: the feature has no readable state, so the CP
cannot verify readiness while they still have signal, which is the only moment
verification is worth anything.

---

## PRACTICE — 2026-08-26 — source assertions must read the AST, never text

A test that greps source for a construct can be satisfied by an EXPLANATION of
that construct. Five instances this session, all in tests I wrote:

- `find-bare-jsx-text` matched its own comment
- `outdoorCanvasPin` matched the exemption comment
- `signatureAffirmedLang` matched the comment quoting the literal
- `str(route.dependant)` -- a repr is not an API. It passed locally and failed
  in CI on a different FastAPI build; the local pass was luck, not a weaker
  check
- the `company_id` sweep count matched the fixed helper's own docstring, which
  quotes the removed line so a reader knows what changed

THE LAST IS THE WORST SHAPE. A green test asserting a number that is silently
wrong, where the number is the entire mechanism -- the sweep exists so the
bypass count cannot drift while individual PRs each look like progress. It read
35 instead of 34 with the fix applied, and would have kept reading high as more
prose about the bug was written.

Skipping comments does not fix it: a docstring is not a comment. Neither does
slicing to a function body: the docstring is inside it.

    If an assertion can be satisfied by an explanation of the thing it checks,
    it is not checking it.

Read the AST. `ast.If.test` is a condition and prose cannot be one;
`dependant.dependencies[].call` is a dependency and a repr is not one. Where a
regex is unavoidable, prove it against a real instance AND a near-miss in the
same file, so an edit that quietly stops matching fails loudly instead of
letting the count drift to zero.

Related: the ``-written-as-0x08 defect -- an escaped byte is the same class,
a check that cannot match anything and reports success.

---

## ENHANCEMENT (FUTURE, LOW) — 2026-08-01 — optional per-worker signature on pre-shift sign-in

**Not a compliance gap — rigor only.** The pre-shift sign-in is compliant as-is:
each worker is documented by an SST-card-backed, timestamped NFC/QR check-in
(credentialed presence evidence, harder to forge than a handwritten mark) and the
Competent Person affirms the attendance record with an **affirmed CP signature**.
The OSHA/DOB documentation baseline (attendance record + responsible-person
certification) is met without a per-worker wet signature — confirmed by the
safety lead against the site-safety plan / GC contract (2026-08-01).

Optional rigor to consider later: capture a per-worker acknowledgment signature
**during the pre-shift meeting** — sign on the CP's device at meeting time
(`SignaturePad` is already imported in `app/logbooks/preshift_signin.jsx`, so it's
an **OTA-deliverable JS change**, no native build). **Timing note:** do NOT hang it
off NFC check-in — check-in is *arrival*, which precedes the meeting, so a
check-in signature wouldn't attest to the meeting. Render side (CP signature) is
already handled. Low priority.

## COMPLIANCE (MEDIUM) — 2026-08-01 — evaluate a worker acknowledgment signature on subcontractor orientation

**Distinct from pre-shift, and a real case — not optional rigor.** Orientation is
the **first-time worker attesting they RECEIVED and understood** site-specific
orientation (the worker's own sign-off), whereas pre-shift is the CP attesting to
attendance. Site-safety plans / GC contracts commonly expect a per-worker
orientation acknowledgment.

Current state: orientation already **captures + renders** the one-time
first-registration signature (with the honest UNSIGNED marker on manual rows).
**Open question for design:** does that first-registration signature count as the
orientation acknowledgment, or does a distinct "I was oriented on THIS project"
sign-off need to be captured?

Do NOT build yet — needs the capture-flow design: **where/how** the worker signs
(the orientation moment, on whose device), how it binds to the per-worker
orientation record (`data.worker_id` — see the name-match/worker_id followup), and
delivery (`SignaturePad` is already native/OTA-able). Scope deliberately when
prioritized. Separate from — and higher priority than — the pre-shift enhancement
above.

## CLEANUP (MEDIUM) — 2026-08-01 — dormant WatermelonDB still runs a background sync every launch

WatermelonDB is wired in but effectively abandoned as a data path: **no screen
reads or writes its local store.** The only offline wrapper built on it,
`src/utils/offlineapi.js` (imports `database` + `Q`), is imported by no screen;
the check-in UI calls `checkinsAPI` directly (`useCheckIns.js`,
`app/checkin/index.jsx`, `app/nfc/index.jsx`) with no local store. Logbook
offline (Phase A, 2026-08-01) deliberately uses AsyncStorage
(`src/utils/logbookDrafts.js`), not WatermelonDB.

**But it is not inert:** `DatabaseContext` still calls `setupAutoSync()` and
`syncDatabase()` on every launch (`src/context/DatabaseContext.jsx:30/72`), and
`offlineQueue.js:130` calls `syncDatabase()` after processing — so a WatermelonDB
`synchronize()` (pull/push to `/api/sync/*`) runs at startup doing no useful
work. This is the mechanism that historically caused the sync delays/collisions,
now pure dead-weight risk (startup cost + a chance of being accidentally
re-relied-on).

**Deferred, not done here** (per instruction — Phase A must not touch it). A
separate, dev-build-verified cleanup should: remove the `setupAutoSync()` /
`syncDatabase()` calls (DatabaseContext + offlineQueue), delete `offlineapi.js`,
and — once nothing references them — the WatermelonDB models/schema/migrations/
adapter (`src/database/*`) and the `@nozbe/watermelondb` deps. Verify check-ins
(direct API) and logbook drafts (AsyncStorage) are unaffected before/after.

---

## SECURITY (HIGH) — 2026-08-01 — NFC check-in proves a URL load, not physical presence

The worker check-in NFC tags encode a **STATIC** URL
(`/checkin/{project_id}/{tag_id}`). `tag_id` is a client-supplied value stored
verbatim in `nfc_tags` (`add_nfc_tag_to_project`, server.py ~9022) and validated
at POST only as `{tag_id, project_id, status:"active"}` — **no per-tap nonce, no
signature, no expiry, no rotation**. The two primary public creation endpoints,
`POST /api/checkin/register-and-checkin` (server.py:9298) and
`POST /api/checkin/submit` (server.py:9869), take no `request` object, so they
capture **no ip/user_agent/device** and have **no rate-limiting** (the
`checkin_rate_limiter`, server.py:574, is wired only to `/checkin` and
`upload-osha`). Same-worker+project+EST-day **dedupe** exists on every path; that
is the only abuse control.

**Impact:** anyone who ever holds the tag URL — from tapping the physical tag, a
screenshot/QR photo, browser history, or a shared link — can mint a real,
current-timestamped check-in for any roster-valid worker, from any device,
anywhere, unthrottled, with no origin recorded on the row. Confirmed live: a
false "on site" record for Mauro E Zumba at 588 Boyland (2026-08-01 12:24) was
created by opening the tag URL from a **desktop browser** during testing — no one
on site, no tag tapped. For a compliance product, "on site" today attests only
that the tag URL was loaded, not that a person was present.

**Fix BEFORE GCs rely on check-in data as presence evidence.** Ranked options
(effectiveness vs effort):
1. **FLOOR (very low effort):** add `request` + `checkin_rate_limiter` to
   register-and-checkin and submit; persist `ip`/`user_agent`/`device_info` on
   the check-in row. Ends silent, unattributable minting; enables forensics.
2. **Server-issued short-lived per-tap nonce (medium):** the tag GET mints a
   single-use, TTL-bound token bound to tag+project; POST must present it. Kills
   replay/bookmark reuse — the bare URL stops working. Best effectiveness-for-
   effort; the real presence fix.
3. **Signed tag payload / HMAC (medium):** stops URL forgery/guessing, but a
   static signed URL is still replayable unless paired with NFC SUN/SDM rotating
   counters (capable tags required).
4. **Geofence device GPS vs site (med-high):** rejects off-site check-ins;
   spoofable and coarse — a secondary signal.
5. **Device/selfie gate (high identity, high effort):** `selfie_image` is
   already captured (spot-check only) and could be surfaced for CP review cheaply
   before full liveness.

Recommended: ship #1 now as the floor, then #2 as the presence proof; keep #4/#5
as layered signals.

## DATA — 2026-07-29 — legacy subcontractor_orientation rows without `data.worker_id`

`POST /api/logbooks` now keys the upsert on `data.worker_id` for
`log_type == "subcontractor_orientation"` (per-worker, not the daily
`(project_id, log_type, date)` singleton) — the fix that stops a UI-created
orientation from `$set`-clobbering a DIFFERENT worker's check-in-created row.

Residual: any orientation row whose `data.worker_id` is **absent or null** —
legacy rows written before the check-in path stamped that field, or rows from
a client that never sent one — cannot be matched by a subsequent UI create for
that worker. The create mints a fresh `srv_<uuid>` id and inserts a SECOND row
rather than updating the legacy one. This is **harmless** (no clobber, no loss),
but produces a duplicate per affected worker.

Not shipped, because it needs production data to scope: a one-time backfill
could stamp `data.worker_id` onto legacy orientation rows (from the linked
check-in, or a synthesised `legacy_<uuid>` where no link exists), OR the
duplicate can be accepted as cosmetic. Decide against the real row count first —
run `db.logbooks.count_documents({"log_type":"subcontractor_orientation", "data.worker_id": {"$in": [None]}})`
plus the absent-field variant before choosing.

## RESILIENCE — 2026-07-29 — `data?.items ?? []` masks a malformed response as empty

The three unwrap clients shipped in `2b157f6` (`checkinsAPI.getByDate`,
`dailyLogsAPI.getByProject`, `logbooksAPI.getByProject`) return
`Array.isArray(data) ? data : (data?.items ?? [])`. That correctly handles the
`{items,...}` envelope and a bare array — but a **malformed or error-shaped**
body (`{error: ...}`, `null`, an HTML 500 page that slipped past the interceptor)
also collapses to `[]`, indistinguishable from a legitimately empty result. The
consumer renders an empty screen instead of surfacing the failure — the same
failure-masking class as the original wrapper bug, one layer down.

Deferred deliberately: the unwrap's job here was to stop the silent-empty and
the content loss, and it does. Hardening is a separate concern — distinguish
"no data" from "bad data" (e.g. treat a non-array, non-`{items:[]}` body as an
error: log it, surface a toast, or throw) so a broken endpoint is loud rather
than silently empty. Applies to these three and to any future client that
adopts the same `?? []` shape.

---

## PHOTO PIPELINE — 2026-07-29 — deblocking has hit its deterministic floor; ARCNN evaluation CANCELLED

Applies to `backend/lib/photo_enhance.py` (shipped in `5ddc56b`).

### The floor, and why it is a floor

Heavily-compressed dark CP photos — the ones that arrive via WhatsApp from the
CP's own camera roll, already re-compressed, never touching the app's capture
path — still show flat 8x8 tiles in lifted shadow. That is as good as it gets
deterministically, and the reason is worth writing down so nobody re-opens it.

JPEG blocking has two components:

1. **Boundary discontinuity** — the visible step between adjacent blocks. This
   is SOLVED. `_deblock_jpeg` removes it, and an ordering experiment on the
   basement photo (lift/deblock/denoise permuted four ways, everything else
   fixed) drove the blockiness metric from 1.278 down to 0.825 **with no
   visible difference between any of the four crops at 2x**. Below ~1.3 the
   metric is measuring boundary steps against ordinary image noise and has
   decoupled from what the image looks like. Do not tune against it further.

2. **Flat interiors** — the tiles themselves carry no texture. This is NOT an
   artefact that can be filtered out: JPEG quantisation zeroed the AC
   coefficients for those blocks. The information is destroyed, not degraded.
   Recovering it means SYNTHESISING plausible texture.

### ARCNN / FBCNN evaluation: cancelled, deliberately

Considered and rejected on 2026-07-29. The proposed success condition was
"visibly fills the flat block interiors" — which is synthesis by definition,
and this pipeline prohibits it: *"No generative/AI upscaling. Deterministic
image ops only; do not invent detail that wasn't in the frame."*

That constraint is not stylistic here. These photos are a DOB compliance
record. Invented texture on a concrete wall in a daily log is a defect with
legal weight, not a cosmetic nicety — the photo is evidence of site conditions
on a date, and a model's guess about what the wall looked like is not evidence.

Cost data gathered before cancelling, so it need not be re-derived:
  * no canonical ARCNN ONNX exists; weights ship as `.pth`
  * conversion would need PyTorch (~2.5 GB) as a one-time step
  * ARCNN weights are tiny (~100-200 KB, four conv layers); FBCNN ~70 MB
  * `cv2` itself is 112 MB installed (measured), and was already rejected for
    CLAHE on the same grounds
  * third-party ONNX mirrors exist but are unvetted; not used

### IF a presentation-grade derivative is ever wanted

It does NOT belong as a pipeline step. It belongs as a SEPARATE variant
alongside `enhanced` and `thumb` — generated on demand, stored under its own
R2 key, and CLEARLY LABELLED as enhanced-for-presentation wherever it renders.

Requirements if that is ever built:
  * outside the compliance path entirely — never substituted into the daily
    log, the DOB record, or anything a regulator reads
  * the original and the deterministic `enhanced` variant remain the record
  * the label travels with the image, not just the UI that happens to show it

That is the only context in which generative enhancement is appropriate here.

### Recommended stack IF the presentation variant is ever built

`onnxruntime` (CPU wheel ~20 MB) + Pillow + numpy. NOT `opencv-python-headless`
— 112 MB installed, and already rejected twice on this feature: once for CLAHE
(implemented in numpy instead, see photo_enhance._clahe_l_channel) and once for
ARCNN. Load the model once and run it on the existing photo threadpool rather
than per-request.

To be explicit, because the two decisions are easy to conflate: this stack note
does NOT reopen ARCNN for the compliance pipeline. Synthesis stays prohibited
there regardless of which runtime executes the model — the cancellation above
was about the PASS CONDITION (filling flat interiors is synthesis), not about
dependency size. A 20 MB runtime does not make invented detail acceptable on a
DOB record; it only makes the carve-out cheaper to build if the carve-out is
ever wanted.

---

## TENANT ISOLATION — 2026-07-28 — assigned_projects: stale-entry audit NOT RUN, + defense-in-depth

Both write vectors into `assigned_projects` are now gated (see the commit that
adds `validate_assignable_projects`). Two things remain OPEN.

### 1. Stale cross-company entries — audit NOT RUN, no production DB access

The gate is **prospective only**. It stops new foreign entries being written; it
does not revoke anything already stored. Any pre-existing cross-company entry is
a live key to another tenant's project and will keep passing
`require_project_access` branch 3.

This has NOT been checked. Nobody has run it against production. Read-only
query, no writes:

```javascript
db.users.aggregate([
  { $match: { assigned_projects: { $exists: true, $ne: [] }, is_deleted: { $ne: true } } },
  { $unwind: "$assigned_projects" },
  { $addFields: { pid: { $toObjectId: "$assigned_projects" } } },
  { $lookup: { from: "projects", localField: "pid", foreignField: "_id", as: "proj" } },
  { $unwind: { path: "$proj", preserveNullAndEmptyArrays: true } },
  { $match: { $expr: { $ne: ["$company_id", "$proj.company_id"] } } },
  { $project: { _id: 1, email: 1, role: 1, company_id: 1,
                project_id: "$assigned_projects", project_company: "$proj.company_id" } }
])
```

`$toObjectId` throws on a non-ObjectId id, so wrap it or run on a subset if the
collection has mixed id shapes. Rows returned are grants this fix does not
retroactively revoke — each needs a deliberate remediation decision (revoke, or
confirm as an intended contractor grant).

### 2. `require_project_access` trusts assigned_projects blindly

Branch 3 returns the project whenever its id appears in the caller's
`assigned_projects`, without re-checking the project's company. With both write
vectors gated, **the assignment guard is now the ONLY thing keeping that list
clean** — a single point of failure.

Re-verifying the project's company inside branch 3 would make a stale or bad
entry inert. The reason it was NOT done: that check would also kill the
legitimate cross-company contractor flow, which is the entire purpose of
branch 3 (a CP at another company granted access to a GC's project — see
`USER_C_ASSIGNED` in test_tenant_isolation_reads.py and
`test_assigned_contractor_allowed_cross_company` in
test_tenant_isolation_writes.py). That is a product decision, not a security
one, and needs an explicit answer: is cross-company assignment a supported
feature, or an accident that should be removed?

If it is NOT supported, branch 3 should verify company and this whole class of
bug disappears. If it IS supported, the assignment guard must stay the single
enforcement point and should be treated as security-critical code.

### Scope limit of the sweep

The vector list came from `grep -n "assigned_projects" backend/server.py` — complete
for that file. Direct DB writes, other services, and migration scripts were not
audited.

---

## TENANT ISOLATION — 2026-07-28 — Batch 2 tightened writes but did NOT complete isolation

25 project-scoped write endpoints now carry `require_approved` +
`require_project_access`. Four things remain open. **Isolation is TIGHTENED,
NOT COMPLETE** — do not treat the write batch as closing the multi-tenant story.

### 1. `POST /admin/users/{user_id}/assign-projects` — SEV-0, defeats the guards

`server.py:4880`. `get_admin_user` checks ROLE ONLY. The handler never loads the
target user to compare companies and never validates the submitted project ids:

```python
result = await db.users.update_one(
    {"_id": to_query_id(user_id)},
    {"$set": {"assigned_projects": project_ids.get("project_ids", []), ...}},
)
```

`require_project_access` branch 3 (`server.py:2819-2820`) treats
`assigned_projects` as sufficient authorization. So this one unscoped write
**manufactures** the membership that every guard added in Batch 1 and Batch 2
then honours. Until it is gated, cross-tenant access is still reachable on the
routes that look protected. Fix: scope the target user to the caller's company
AND validate every submitted project id belongs to that company.

Note the sibling `PUT /admin/users/{user_id}` (`server.py:4773+`) already has
this mitigation, commented "SEV-0 tenant scoping. get_admin_user checks ROLE
ONLY..." — assign-projects was missed.

### 2. Kiosk write path — `POST /daily-logs`, `PUT /daily-logs/{log_id}`

Not gated. A site device registered to project A can write a daily log to
project B. `require_project_access` cannot be applied as-written because
`project_id` arrives in the **body** (`DailyLogCreate`), not the path.

Device-auth shape is confirmed and the guard is a straight port, not new logic:
a kiosk authenticates against `db.site_devices` (`server.py:3092`) with a
`site_mode` JWT; `get_current_user` (`server.py:2431-2444`) resolves it to the
device row, sets `role="site_device"`, and re-derives `company_id` from the
device's project at request time. The device record carries `project_id`
(written at provisioning, `server.py:10769`). So the check is exactly
`require_project_access` branch 1 (`server.py:2806`) — device may write only to
its provisioned project — reading `body.project_id` instead of the path param.

Also fix while there: `create_daily_log` inserts even when the project lookup
returns `None` (`server.py:10540-10544`).

### 3. Per-endpoint route-level over-gate tests not written

`test_tenant_isolation_writes.py` asserts the three directions against the
SHARED guard, plus a source pin (ast) and a wiring pin (live FastAPI dependant
tree) proving all 25 routes declare and carry both dependencies. There is **no
route-level call** for any endpoint — in particular no per-endpoint
"own-company admin still works" mirror. A handler-local regression that breaks a
legitimate own-project write would not be caught.

The two 403 directions are cheap to add per route (the dependency raises before
body validation). The "works" direction is the expensive one: multipart for
`upload-file`, R2/Dropbox doubles for `sync-dropbox` and `reindex-*`, the stats
engine for `risk-score/calculate`.

### 4. Null-`company_id` deployment count — DO THIS BEFORE DEPLOYING

The hand-rolled checks these guards replace had the shape
`if company_id and project.get("company_id") != company_id:` — which **silently
passed** when the caller's `company_id` was falsy. `require_project_access`
fails closed instead. Any real admin/owner account with a null/missing
`company_id` therefore passed these 25 routes before and gets 403 now.

Count them first — `backend/scripts/audit_account_roles.py --mask` is the
natural place to add it. No production DB access from the dev environment.

### Also noticed, unrelated to this batch

`get_current_user`'s site-device branch looks the device up by `_id` only
(`server.py:2432`) and does **not** re-check `is_active` / `is_deleted`, though
the login endpoint does (`server.py:3092`). A deactivated kiosk's existing token
keeps working until it expires.

---

## CAMERA PERF — 2026-07-28 — daily-log camera is not fully pre-warmed; Android still cold-starts the device

Permission is now off the tap path (`4b712e3`), and the capture surface is
mounted-hidden rather than created on open (commit 2 of the same pair). What is
**not** done: the camera device is not held warm on every platform.

Read from VisionCamera 4.7.3's own native source, not assumed:

- **iOS** — `ios/Core/CameraSession.swift`: `configure()` acquires the device
  input and configures format/outputs in steps 1-9; `checkIsActive()` is step
  10 and only calls `captureSession.startRunning()`. The device **is** held
  from screen mount. iOS is genuinely pre-warmed.
- **Android** — `android/…/core/CameraSession.kt`: `configureOutputs` /
  `configureCamera` (CameraX `bindToLifecycle`) run first, `configureIsActive`
  runs fourth and only moves a `LifecycleRegistry` between `CREATED` and
  `RESUMED` (`CameraSession+Configuration.kt:341`). CameraX opens the physical
  camera on that transition, so **the device open is still on the tap**. The
  session graph is pre-built; the device is not held.

**The remaining lever, and why it wasn't pulled:** holding the Android
lifecycle at `STARTED` while idle would keep the camera device open, but that
means the camera hardware is held for the whole time the daily-log screen is
open — a real battery and thermal cost on a shift-long jobsite tablet, and it
lights the OS camera-in-use indicator while the user is only typing. Not worth
paying before device testing shows the open actually feels slow.

**Revisit if** device testing shows the Android open still lags noticeably
behind iOS. Until then this is a known, measured-by-source asymmetry, not a
defect.

**Unverified without a phone** (neither web nor emulator reproduces camera
cold-start; the production web export exercises the `.web.jsx` stub, not
VisionCamera): actual open time on either platform, and the four interaction
surfaces the overlay restructure introduced — Android hardware back dismissing
the camera, the overlay stacking above `FloatingNav`, full-bleed layout outside
the `SafeAreaView`, and AppState background/resume re-acquiring the preview
rather than returning black.

---

## TEST GAP — 2026-07-28 — nothing MOUNTS the shared components, so a crash ships green

While converting the shared components to per-render theming (`98e5577`), four
of them — `IconPod`, `SiteNav`, `ToastProvider`, `FloatingNav` — were left
referencing a module-scope `styles` that no longer existed. That is a hard
runtime crash: **"Something went wrong · styles is not defined"** on any screen
that raised a toast.

**Both gates passed anyway.**

- The frozen-ref grep reported 0 — it looks for `colors.*` inside a module
  `StyleSheet.create`, and the crash is a *missing binding*, not a frozen value.
- The wiring checker reported 0 unwired — it scanned from each component to
  end-of-file, swallowing the `buildStyles` definition, so every file's LAST
  component read as "already wired".
- Both CI suites were green: 2110 backend + 16 frontend, none of which render
  a React component.

It was caught only because the rendered screenshots were demanded in context —
the toast screenshot showed the error boundary instead of a toast.

**The gap:** the frontend suite is one Node harness that parses source text
(`RiskScoreCircle.bandFor.test.cjs`). Nothing in CI ever *mounts* a component,
so any render-time error — missing binding, bad hook order, undefined style,
a provider that throws — ships green.

**To close:** add a mount smoke test that renders each shared component (and
each provider) once and asserts it does not throw. It does not need assertions
about appearance; mounting is the assertion. Candidates, in dependency order:
`ToastProvider`, `ThemeProvider`, `AuthProvider`, `GlassCard`, `IconPod`,
`StatCard`, `GlassListItem`, `GlassSkeleton` (+ its four skeleton variants),
`Toast`, `OfflineIndicator`, `SyncButton`, `SiteNav`, `FloatingNav`.

Note this needs test infrastructure the repo does not have: there is no jest /
vitest / react-test-renderer, and `frontend/package.json` has no `test` script.
Adding one is the bulk of the work; the tests themselves are a few lines each.
Wire it into the existing `tests` workflow's `frontend-tests` job so it gates
like the rest.

**Cheaper interim option** if a runner is too much scope: extend the existing
Playwright verification into a committed script that loads a handful of routes
against a production build and fails on any console error or error-boundary
text. That would have caught this exact crash, without a component-test runner.

---

## OFFLINE CORRECTNESS — 2026-07-27 — offline "on site" count includes stale prior-day check-ins

`getActiveCheckIns` in `frontend/src/hooks/useCheckIns.js` falls back to a local
WatermelonDB query when the API call fails. That fallback filters **only** on
`check_out_time: null` — there is **no day boundary**:

```js
// useCheckIns.js:107 — the offline fallback
const queryConditions = [
  Q.where('is_deleted', false),
  Q.where('check_out_time', null),
];
if (projectId) {
  queryConditions.push(Q.where('project_id', projectId));
}
```

Offline, a worker who was never checked out on a **prior** day still satisfies
`check_out_time: null` and is counted as "on site today". The count silently
inflates with every un-checked-out worker, and nothing on screen indicates the
number came from the offline path.

Both surfaces share this: the dashboard **Active by site** section and the
project-detail **ON SITE** tile call the same hook (deliberately — one code
path so the two cannot disagree). They stay consistent with each other; both
are wrong together when offline.

**Online path is correct** and unaffected: `GET /checkins/project/{id}/active`
bounds the query with `get_today_range_est()` (the NYC-local day from the
check-in timezone fix). This is an offline-path-only defect.

**Second, related divergence found in the same file:** the sibling
`getTodayCheckIns` fallback (`useCheckIns.js:142`) *does* bound the day — but
with **device-local** midnight:

```js
const dayStart = new Date(date); dayStart.setHours(0, 0, 0, 0);
const dayEnd   = new Date(date); dayEnd.setHours(23, 59, 59, 999);
```

So a device outside America/New_York gets a different "today" offline than the
server's `get_day_range_est`. Two different day definitions now exist on the
offline path, and neither matches the server's.

**Why this matters beyond cosmetics:** "who was on site" is a compliance
record. An inflated on-site count offline is a false attendance statement, not
a display glitch.

**To close (offline audit):**
- Give the `getActiveCheckIns` fallback an NYC-local day bound so an
  un-checked-out prior-day record cannot count as present today.
- Derive the offline day boundary from a shared NYC-local helper rather than
  `setHours(0,0,0,0)`, so `getTodayCheckIns` and `getActiveCheckIns` agree with
  each other and with the server.
- Consider surfacing staleness in the UI when a count came from the local
  fallback — an offline number that looks identical to a live one is the part
  that makes this dangerous.

---

## COMPLIANCE GAP — 2026-07-27 — worker certification expiry renders with no warning state

**Priority: compliance, not polish.**

`frontend/app/workers/[id].jsx:558` renders a worker's certification expiry as

```jsx
<Text style={s.certExpiry}>Expires: {cert.expiry}</Text>
```

and `certExpiry` (line ~955) is `color: colors.text.muted` — **unconditionally**.
The date is printed as flat muted text whether it expires in a year, expires
tomorrow, or expired last month. There is no `daysUntil` / `isExpired`
evaluation anywhere in this file for certifications: the expiry is never
compared against today, so no code path can colour it.

On a NYC jobsite an expired SST or OSHA card means the worker **legally cannot
be on site**. A foreman scanning this screen gets no signal that a card has
lapsed, so this is a missing compliance warning, not a cosmetic gap.

The `Award` icon beside the row is a constant glyph for every certification and
was correctly routed to the neutral token in the amber sweep (`8b4830a`) — it
was never carrying the warning. That commit did not cause this gap; it surfaced
it.

**Second instance, same defect:** the OSHA card at
`frontend/app/workers/[id].jsx:414–417` renders `oshaData.expiration` with
`oshaFieldValue` (`colors.text.primary`) — also unconditional, also never
compared against today.

**To close:**
- Evaluate days-remaining for `cert.expiry` and `oshaData.expiration` (a
  `daysUntil` helper already exists at
  `frontend/app/project/[id]/dob-logs.jsx:72` — lift it into a shared util
  rather than re-implementing).
- Colour the expiry text `semantic.attention` when expiring soon (threshold to
  be agreed — the DOB permit surfaces use 30d, `settings.jsx` / safety-staff use
  60d/90d) and `semantic.criticalText` once expired.
- Consider surfacing an expired card at the worker-list level too, not only on
  the detail screen — an expired card is only actionable if someone sees it
  before the worker reaches the gate.

---

## 2026-07-27 — 85 hardcoded `#f59e0b` amber literals still bypass the token layer

The dual-theme contrast fix made the semantic state tokens per-theme, so
`semantic.attention` now resolves to a light-mode-safe amber. But **85
occurrences across 30 files** still hardcode the raw amber literal `#f59e0b`
(plus `rgba(245,158,11,…)` fills), which cannot follow the theme and therefore
still render at ~3.2:1 in light mode — below WCAG AA.

**Fixed in this pass (the screen named in the audit):**
`frontend/app/project/[id]/dob-logs.jsx` — all 22 amber literals routed to
`semantic.attention` / `semantic.attentionBg`.

**Still open:** the other 30 files, notably `app/admin/safety-staff.jsx`,
`app/admin/site-devices.jsx`, `app/daily-log.jsx`, `app/logbooks/*.jsx`,
`app/documents.jsx`, `app/demo.jsx`. Same class of bug exists for any
hardcoded red/green literal.

**To close:** sweep the remaining literals onto the semantic tokens (a
color-only change per site), then add a lint rule banning raw state-color hex
in `app/`/`src/` so the sprawl cannot reappear.

## 2026-07-27 — No per-project DOB-sync timestamp (Projects triage "Synced" column)

The desktop Projects triage table (`frontend/src/components/ProjectsTable.jsx`)
wants a **data-sync freshness** value per project, but no such field is written.
The only sync-ish project timestamp is `first_poll_completed_at`, stamped **once**
on the first DOB poll and never updated thereafter
(`backend/server.py:17395` — `if proj_doc and not proj_doc.get("first_poll_completed_at")`).
Rendering relative time off it ("synced 4m") would be a lie for any established
project — it's first-poll age, not last-sync freshness. (`last_synced_at`
[server.py:12419] is Dropbox files; `last_sync_at` [server.py:18383] is a global
rate-limit doc — neither is per-project DOB sync.)

**Interim (shipped):** the Synced column shows only the one truthful bit —
"Never" (attention) when `first_poll_completed_at` is null, "—" once synced. No
fake relative freshness.

**To close:** stamp a rolling `last_dob_sync_at` (UTC) on the project doc at the
end of each successful `run_dob_sync_for_project`, add it to `ProjectResponse`,
then render real relative freshness in the Synced column.

## 2026-07-26 — i18n gap on the DOB compliance screen (dob-logs.jsx)

`frontend/app/project/[id]/dob-logs.jsx` has **no i18n framework** — the
no-expiry permit disclosure ("N permit(s) without expiry data not counted") and
every other user-facing string on this screen (tile labels, "Sync Now", filter
banner, status badges, etc.) are **English-only**. This is against the app's
stated **bilingual EN/ES** principle for user-facing strings. The app has no
i18n library wired at all (no i18next/react-i18next; a few worker-facing screens
carry inline EN/ES strings, but the compliance screens do not).

**Interim:** English-only shipped honestly — commit `5e4a521`'s body records that
the disclosure is English because this screen lacks i18n.

**To close:** wire i18n on this screen (and the sibling compliance screens) so
its strings meet the bilingual convention — ideally via a shared translation
mechanism rather than per-string inline ternaries.

---

## 2026-07-26 — dob-summary active-permit boundary: UTC vs NYC-local (minor)

`GET /projects/dob-summary`'s `permits_expiring` facet uses **UTC midnight**
today (`server.py` ~7496), not NYC-local. The new `total_permits` (active)
facet deliberately reuses that **same UTC `today_start`** so `permits_expiring`
is always a subset of `active`. Immaterial for a 30-day permit window (a permit
sitting exactly on the UTC-vs-EDT boundary is a few hours' difference on a
month-scale horizon). Fully aligning to NYC-local would require changing
`permits_expiring` too (the open-count logic), which was explicitly out of
scope. Log-only; revisit if a day-boundary discrepancy is ever reported.

---

## 2026-07-26 — Violation-type code labels need an official DOB source

DOB violation-type codes (`JVIOS`, `JVCAT5`, `E`, `LBLVIO`, the `LL*` family,
and DOB NOW Safety `FTC-*/FTF-*` codes) are currently shown to customers as
`DOB code: {code}` — the honest raw code — because there is **no verified
official label** for them yet. The DOB Violations dataset (`3h2n-5cm9`) embeds a
description in its `violation_type` column, but that is dataset text, not a
dedicated authoritative DOB violation-type code list, so it is treated as
UNVERIFIED.

A transcribed-from-dataset map exists but is **quarantined** behind
`UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE` in
`backend/dob_complaint_codes.py`, with a comment that it must not be displayed;
`violation_type_display()` deliberately does not read it, and a test
(`test_display_never_returns_an_unverified_label`) enforces that.

**To close:** confirm each code→label against DOB's official published
violation-type reference (or the `855j-jady` data-dictionary xlsx for the
`FTC-*/FTF-*` family), then promote the verified entries into the display path.
Until then, violation types stay prefixed. (Complaint category + disposition
labels already have official sources and DO display.)

---

## 2026-07-26 — OverviewByBinServlet: code was already clean; risk is stored data + doc drift

**Finding.** A repoint of violation tier-3 links off the decommissioned
`OverviewByBinServlet` was requested, but the builder was **already** clean: every
BIN fallback (`_build_dob_link` violation/permit/job_status/inspection/final)
routes through `_bis_bin_overview_url` → `PropertyProfileOverviewServlet?bin=`
(the confirmed-live BIN profile), and there is **zero** `OverviewByBinServlet` URL
construction in the deployed tree. The only residue was **stale docstring text**
in `_build_dob_link` (three "→ BIS OverviewByBin" lines plus an outdated
permit/job_status routing summary) — corrected this pass. `_bis_property_profile_link`
does not exist. The `SourceInvariantTest` guard already forbade the dead URL; a
functional guard (`test_no_record_type_emits_overviewbybin`) was added so no
future branch can reintroduce it regardless of URL literal.

**Why links can still LOOK dead (data, not code):** `dob_link` is written at
ingest, but the dob-logs read path (`server.py` ~18085) rebuilds it from each
row's `raw_record` on every read — so a stale stored `OverviewByBin` value is
replaced with the live URL at read time **iff the row has a `raw_record`**. A row
with no `raw_record` keeps its stale stored link. Remedy for those is a re-poll
(`/projects/{id}/dob-sync`), not a code change. `backend/scripts/violation_link_check.py`
reports, per record, stored-vs-freshly-built link and whether a `raw_record`
exists (auto-heal) or is missing (genuinely stale).

**Lesson — BIS legacy servlets are being retired mid-lifecycle.** DOB has quietly
decommissioned `OverviewByBinServlet` (now BIS "Page not found") while
`PropertyProfileOverviewServlet` stays live. BIS-based deep links therefore need
**periodic** re-verification, not one-time confirmation; treat any BIS servlet as
"confirmed as of <date>", and keep all BIN links flowing through the single
`_bis_bin_overview_url` helper so a future swap is one edit.

---

## 2026-07-26 — Permit / job_status links repointed to BIN property profile

**Done.** DOB NOW permit/job_status filings had no public per-record URL (DOB NOW
is a login-walled Angular SPA whose Job-Number search does not encode the job in
the URL — confirmed by live fetch; its result URL is `…/Index.html#!/search`),
and the old `data.cityofnewyork.us/w9ak-ipjd.html?job_filing_number=` link landed
on a generic dataset page because Socrata's `.html` surface ignores the column
filter. All permit/job_status now resolve to the SAME confirmed-working BIS BIN
property profile used for the violation fallback
(`PropertyProfileOverviewServlet?bin=`, via `_bis_bin_overview_url`); legacy
BIS-numeric permits (previously `JobsQueryByNumberServlet`) share it too. No BIN
→ no link.

**Candidate to verify when BIS is reliably up: `JobsQueryByLocationServlet` for
I1/inspection-suffix filings.** This per-location servlet was *proposed as a
possible per-filing surface but never fetch-confirmed* — it did not appear as a
tested/working destination in the link diagnostic. It was therefore NOT adopted;
I1 filings fall back to the BIN property profile like the rest. If a live fetch
(when BIS is not throwing its intermittent high-traffic / Access-Denied errors)
returns a real per-filing page for a DOB NOW `…-I1` job, it could be adopted for
that subset. Until fetch-confirmed, do not build it.

Note: BIS (a810-bisweb) was intermittently Akamai Access-Denied during
verification — `PropertyProfileOverviewServlet?bin=` loaded live (twice) while
`JobsQueryByNumberServlet` and `OverviewByBinServlet?requestid=2&allbin=` both
errored (the latter a genuine "Page not found", confirming that shape is dead —
only `PropertyProfileOverviewServlet?bin=` is the working BIN form).

---

## 2026-07-25 — Check-in date handling fixed, but never tested via a real NFC tap

**Done.** Bucketing check-ins by NYC-local day was fixed across all six date
sites (4 backend UTC-midnight `strptime(...tzinfo=utc)` sites → `get_day_range_est`,
frontend `getByDate` → NYC-local date, dashboard `on_site_now` → EST-today to
match the project ON SITE tile). Verified against synthetic boundary records
(8:30pm EDT rollover + early-EST lower boundary) via
`backend/scripts/checkin_tz_verify.py`.

**Deferred — physical device test required before customer reliance.** The full
NFC-tap → kiosk write → display path has **never** been exercised on a real
device; verification to date is synthetic records only. Per the
device-test-before-production principle, run a real on-device check-in end to
end before relying on the feature with a customer. Note: zero real check-ins
exist on either live project today, so the write path is unproven in production.

---

## 2026-07-25 — Rodent-inspection (p937-wjvj) removal: deferred statistical-engine scope

**Context.** `p937-wjvj` is NYC **DOHMH Rodent Inspection** data (rat inspections),
which the app ingested and labeled as **DOB inspections**. The `PC` (Pest Control)
job prefix was additionally fabricated into a `"Plumbing"` trade category by
`DOB_JOB_PREFIX_CATEGORY` / `_decode_job_prefix`. Verified against live Socrata
(source result = "Failed for Rat Activity") and the dataset metadata API
(name = "Rodent Inspection", attribution = DOHMH).

**Done (COMMIT 1, 2026-07-25).** Removed the two `p937-wjvj` ingest endpoints and
the inspection-only composite raw-id fallback in `server.py:_query_dob_apis`;
removed the now-callerless `DOB_JOB_PREFIX_CATEGORY` map, `_decode_job_prefix`,
and its three call sites (`_extract_inspection_fields`, `_generate_summary`
inspection branch, the read-time re-enrichment block). No new `record_type=
"inspection"` rows enter `dob_logs`.

**Deferred — folded into the score rebuild (NOT patched now, because the risk
score is getting a full rebuild and patching its rat-fed dimensions now is
throwaway work the rebuild redoes correctly):**

`DATASET_DOB_INSPECTIONS = "p937-wjvj"` (`lib/statistical_engine/socrata_client.py:85`)
still feeds the risk model **live via Socrata** on four surfaces — all currently
ranking/predicting on DOHMH **rat** inspections:

- **Peer inspection dimension** — `lib/statistical_engine/baselines.py`
  (`compare_project_to_peers`, ~lines 880/900/1163/1273) → `peer_compare["inspections"]`
  → `inspections_percentile` → averaged into the peer subscore
  (`score.py:_normalize_peer_comparison`). Both the project and its peer set are
  ranked on rat-inspection counts.
- **Borough-sweep trigger** — `lib/statistical_engine/triggers.py:741–907`
  (`borough_inspection_counts_90d` / `last_7d_count`, `TRIGGER_BOROUGH_SWEEP`).
- **Inspection prediction** — `lib/statistical_engine/predictions.py`
  (`predict_inspection_from_complaint`, chunked `bbl IN (...)` against p937-wjvj).
- **Calibration** — `lib/statistical_engine/calibration.py:89`
  (`TRIGGER_BOROUGH_SWEEP → (DATASET_DOB_INSPECTIONS, "inspection_date")`).

**Required in the rebuild.** Redesign these against the CORRECT DOB inspection
source(s). Per-trade construction inspections are **not** in NYC Open Data (they
live only in the DOB NOW public portal, per job); the open-data DOB inspection
sources are the periodic safety programs — Boiler `52dp-yji6`, Elevator
`e5aq-a4j2`, Facade FISP `xubg-57si`, CO/TCO `pkdm-hqz6` — each BIN-keyed with
plain-English results. Until then, the peer/trigger/prediction inspection
dimensions are contaminated by rodent data and must not be trusted.

**Also deferred (harmless display/link cleanup, no data behind it):** the
`record_type=="inspection"` display/link/template/notification code in
`server.py` (`_build_dob_link` inspection branch ~16899, severity map entry,
`dob-logs.jsx` `renderInspectionCard`) and the existing `dob_logs` rodent rows
(deleted separately in COMMIT 2).

## Toast is foreign-looking on the ten pinned logbook editors

Logged 2026-08-25, alongside the outdoor canvas pin (PR #210).

The ten logbook editors are pinned to the `outdoor` palette - frozen light,
because a CP fills a compliance log in direct sun. With the canvas now pinned
too, a toast raised on one of those screens in dark mode is a DARK opaque box
on a light page.

NOT INVISIBLE, which is why it is logged rather than fixed. `Toast` paints an
opaque fill in both themes (`#2a1313` dark, a mixed light value otherwise), so
it is a self-contained surface and its text contrasts with its own background.
Nothing disappears; it simply does not match the page it floats over.

The fix, if it is ever wanted, is the same `pinned` prop AnimatedBackground and
SignaturePad now take - but it is more awkward here, because a toast is raised
through a CONTEXT from anywhere, not mounted by the screen, so the screen has
no natural place to declare the pin. That is a real design question and not a
colour swap, which is the other reason it is not in #210.
