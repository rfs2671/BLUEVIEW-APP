# Follow-ups

Known gaps and deferred work, newest first.

- **[HIGH] The check-in geofence does not run, and must never be cited as a
  presence control.**
  `geofence_radius_m` is on the project model and `compute_geofence` is
  implemented, so the geofence reads as a shipped feature. No check-in has ever
  been geofenced. Two independent reasons — **both** must be fixed before the
  field means anything, and fixing either alone changes nothing:

  1. **The enforcing route is shadowed.** Enforcement lives only in
     `backend/card_audit.py` (1264, 1380, 1557, 1909), on `gate_router`'s
     `GET /checkin/{project_id}/{gate_id}`. But `serve_checkin_page_full`
     (`server.py:21049`) declares `@app.get("/checkin/{project_id}/{tag_id}")`
     at module scope, and `app.include_router(gate_router)` runs at
     `server.py:34990` — later. (Symbol names given because these line numbers
     move; this entry's own numbers shifted by 25 when the QR change landed.)
     Module-scope decorators register at import, top to bottom, and FastAPI
     matches in registration order. server.py wins; card_audit's gate is
     unreachable. The live gate is `backend/checkin.html`, which contains no
     `geolocation` call at all.
  2. **There is no origin coordinate.** `project.lat` / `lng` are `Optional`
     and *nothing* populates them — no geocoding on create, no field in any
     frontend project form. `compute_geofence` returns `None` when either pair
     is missing, so even wiring path 1 up would yield `None` for every project
     on the platform.

  **What the live path actually records** (`register_and_checkin` →
  `db.checkins`): `source_ip`, `user_agent`, `device_fingerprint`, and now
  `checkin_method`. No coordinates. The code says what these are worth in its
  own comment — *"Detective, not preventive"* — and `source_ip` is weaker than
  it looks, because the per-IP rate limit was removed on the finding that
  workers are on their own phones behind one site WiFi.

  **Why this is HIGH now.** NFC required physical presence. QR check-in does
  not: a printed code is a permanent, silently-copyable credential — no expiry,
  no nonce, no rotation — and one photograph works from anywhere until an admin
  deletes the tag, which also locks out the men actually standing at the gate.
  `checkin_method` makes that exposure queryable; it does not close it.

  **If it is ever wired up: record, never block.** Populate project
  coordinates, have `checkin.html` request `navigator.geolocation`, and store
  `within_geofence` as `true` / `false` / `null`. GPS is denied, imprecise
  indoors and dead below grade, and this codebase has twice refused to let a
  control stop a man working — the removed per-IP rate limit, and
  `needs_trade_assignment` admitting and flagging rather than turning him away.
  A blocking geofence would be the first exception, and a config gap would
  become a man sent home.

- **[MEASURED, NOT FIXED] The bottom inset is a constant, and here is the number.**
  API 36 enforces edge-to-edge, so content draws under the navigation bar. The
  app handles the top with `SafeAreaView edges={['top']}` (67 usages) and the
  bottom with **scroll padding**, deliberately — no screen insets the bottom at
  the screen level except one.

  The measurement, so a future device with a larger inset has it in front of it:

  | | |
  |---|---|
  | `paddingBottom: 120` | 32 screens |
  | `paddingBottom: 140` | 2 screens |
  | `paddingBottom: 100 / 80 / 60` | 1 each |
  | gesture-navigation inset | —24dp |
  | 3-button navigation inset | —48dp |

  **120 clears both comfortably and nothing was reported clipped on a Pixel 10
  Pro XL**, which is why this is recorded rather than changed. Rewriting 32
  screens to chase a constant that is currently adequate is a larger risk than
  the thing it would fix.

  **What would make it wrong:** a device whose navigation inset exceeds —96dp
  (120 minus the —24dp of intended breathing room), or a screen whose last
  element is a control rather than text. Neither exists today.

  **The real exception was NOT scroll padding, and it is now FIXED.** `CpNav`
  and `FloatingNav` were `position: 'absolute', bottom: 24` with no inset —
  absolute positioning takes them out of the inset flow, so neither parent
  padding nor scroll padding reached them, and on 3-button navigation the nav
  sat under the system buttons on every CP screen. Both now render
  `{ bottom: insets.bottom + 24 }` inline; it has to be inline because a
  StyleSheet is built once at module load, before any inset exists.

  Same shape, smaller: `Toast.js` uses a fixed `top: 60` rather than
  `insets.top`, and three bottom-anchored modal sheets (`checklists.jsx`,
  `project/[id].jsx`, `projects/index.jsx`) have no bottom padding — and a
  Modal is a separate window, so no screen-level SafeAreaView reaches them.

- **[UNCONFIRMED] Why the 588 Thomas tags could be programmed before the write
  path could format a blank one.**
  The Android write path never had a format branch until 2026-08-23, and
  `nfcHelper.js` has not otherwise changed since 2026-02-04. So programming
  those tags from blanks should have been impossible, and it evidently was not.

  **Probable explanation, not a certainty: they were already NDEF-formatted.**
  NTAG213 and most ISO 14443A stock ships NDEF-formatted from the factory, so
  those tags would have offered `Ndef` on the first try and written fine. The
  blanks that fail today are **NfcV / ISO 15693**, a different chip family, and
  arrive unformatted — hence `[NfcV, NdefFormatable]` in the logcat.

  Two other readings fit and cannot be excluded from here: the tags were
  written with a third-party NFC app and only the ID typed into the manual
  entry field, or they arrived pre-formatted from a different supplier. The
  database cannot distinguish any of them — `nfc_tags` records no provenance,
  and the scan path and the manual-entry field post an identical row.

  **One scan settles it.** Next time anyone is on site, run Scan & Program
  against a 588 tag and read the `tech` now included in the result and in any
  error. `Ndef` confirms the tags were already formatted; `NdefFormatable`
  means they were not, and the explanation is wrong.

  **Nothing is built on this.** The fix branches on the tech actually acquired,
  so it handles both cases regardless of which reading is true — which is what
  makes it a fix rather than a workaround for one tag type. This entry exists
  so the question is not later mistaken for answered.

- **[LOW] Three of the four `variant` names passed to `GlassButton` do nothing.**
  The component special-cases exactly one: `if (variant === 'icon')`. Its own
  default is annotated `// 'default' | 'icon'`. Every other value falls straight
  through to the default branch.

  Counted across `app/` and `src/`:

  | value | uses | handled? |
  |---|---|---|
  | `"icon"` | 52 | yes |
  | `"modal"` | 21 | **no** |
  | `"secondary"` | 11 | **no** |
  | `"primary"` | 4 | **no** |

  So **36 call sites pass a variant name that is silently ignored**, and every
  one renders as the default button.

  Nothing is visibly broken: the default branch is a working button and the
  sites presumably look acceptable, or somebody would have said. What it costs
  is that the code reads as though three visual treatments exist when there is
  one — so a future change to "the secondary button" would edit something with
  no effect and appear to do nothing.

  Surfaced while fixing the two call sites that passed their LABEL as children
  (the React 19 sweep). `SyncButton` passes `variant="secondary"`, which is
  exactly why it took the default path and rendered an icon beside an empty
  text slot rather than the icon-only control it appeared to be. The dead
  variant name is what made the real defect look intentional.

  **Deliberately not chased.** Either implement the three variants or delete
  the names from all 36 sites — both are real changes to how buttons look
  across the app, and neither belongs inside an SDK migration.

- **[DATED 2026-08-22] SDK 55+ / New Architecture — do it in ONE migration, and
  the trigger is `react-native-nfc-manager@4.x` going stable.**
  Not "someday". The actual consideration, with the numbers as of today.

  Expo **57** is current; this repo is going to **54**. That is three majors
  behind on the day it ships, and 54's EAS Build support window will close.
  SDK 55 (RN 0.82) removes the `newArchEnabled: false` opt-out, so New
  Architecture stops being a choice — which means Path B is not optional, only
  deferred.

  **Why 54 and not 55 now.** `npm view react-native-nfc-manager dist-tags` on
  2026-08-22 returns `{latest: 3.17.2, beta: 4.0.0-beta.7}`. The whole 4.x line
  is beta.0 through beta.7 — eight pre-releases, no stable. Going to 55 today
  would force that beta onto the library that programs the gate tags every
  worker checks in against. Shipping a pre-release on the check-in path is not
  a trade worth making to save a migration.

  **The trigger to re-open this**, and it is one command:

  ```bash
  npm view react-native-nfc-manager dist-tags
  ```

  The moment `latest` reads `4.x`, Path B is available and 55/56/57 collapse
  into a single hop. Doing one migration then beats doing two.

  **What Path B additionally costs**, so it is not underestimated when it
  arrives: `expo-file-system/legacy` is REMOVED in 55, so the six import sites
  need a real API rewrite rather than the path swap Path A does; and reanimated
  returns to the 4.x line, which is correct on New Arch and impossible off it.

  Check this before starting Path A, not only after — if 4.x went stable in the
  interim, the whole legacy-architecture detour is avoidable.

- **[REQUIRED-BEFORE-PLAY] `eas submit -p android` has no service-account key
  and will fail the first time it is run.**
  `eas.json` already carries `submit.production.android: {"track": "alpha"}`, so
  the profile is not missing — what is missing is the credential behind it.
  Compare the iOS side, which names `ascAppId` and `appleTeamId`: the Android
  side names a track and nothing that can authenticate to it. EAS will either
  prompt for a Google Play service-account JSON interactively or fail outright,
  depending on how it is invoked.

  **Deliberately NOT built now.** Play cannot accept an upload at all until
  `targetSdkVersion 36` lands, so a submit profile written today would sit
  unused and untested across a six-to-eight-day migration that may change what
  it needs — SDK 54 ships a newer `eas-cli`, and credential handling is exactly
  the kind of thing that moves between majors. Build it when the AAB is
  actually going somewhere.

  **What it will need**, so the day it is built is not also the day it is
  discovered: a Google Cloud service account with the Play Developer API
  enabled, invited into the Play Console with release permissions, its JSON key
  downloaded, and either `serviceAccountKeyPath` pointed at it in `eas.json` or
  the key uploaded to EAS credentials. Google's own propagation delay on a
  newly-invited service account is measured in hours, not minutes, so the
  invitation is worth sending BEFORE the migration finishes rather than after.

  Related: the first Play upload also fixes `versionCode` forever as a
  monotonic floor. It is set explicitly to `1020001` (see the release notes on
  #188) rather than left to autoIncrement, precisely so that floor is a number
  someone chose.
- **[POST-RELEASE] Nothing records which bundle a device is running, and after
  release nobody will be able to work it out.**
  Today the installed population is KNOWN because it was hand-placed: the app has
  never shipped on either store, both submissions are rejected or blocked, and
  every device in the field was handed out by the operator — his own phone and
  the CP on 588 Thomas. So "who is stranded on the old runtime?" is answered by
  asking him, and the 1.1.3 to 1.2.0 OTA gap was shipped open on exactly that
  basis: no device had ever reached runtime 1.1.3, because a device cannot cross
  runtime versions by OTA (`expo-updates` applies an update only when its
  `runtimeVersion` equals the running binary's), and the only binary in
  existence was 1.1.0 (5).

  **Release is what breaks that.** The moment installs come from a store, the
  population stops being a list the operator holds in his head, and the same
  question becomes unanswerable:

  * The SERVER cannot answer it. No version header on any API request; the
    `getDeviceFingerprint` payload carries brand / model / OS / platform and no
    app version; no `app_version` field on any collection. `/api/version`
    reports the BACKEND's commit, and the settings BUILD card does its
    comparison client-side and sends nothing up.
  * EAS cannot answer it either. `expo-insights` is not a dependency, so there
    are no update-adoption metrics in the Expo dashboard.

  Why it matters, in the shape it has already taken once: an
  `expo.version` bump rolls the runtime version, and every device that does not
  take the new BINARY silently stops receiving updates — no error, no prompt,
  the device simply asks and is correctly told there is nothing for it. That is
  how a superintendent on a live site ran three weeks behind the fixes written
  for him and filed unsigned compliance logs the whole time.

  Two candidate mechanisms, neither scoped: send the running version on API
  requests so the server can report the spread, or add `expo-insights` and read
  adoption per update. The first also answers "is this device's JS current?" for
  support, which is the question the BUILD card exists to answer one phone at a
  time.

  **Not a gap now — do not build it before release.** The population is
  knowable by other means until then, and a telemetry field added early is a
  field nobody reads.

- **[HIGH] Full responsive-layout audit across the supported device-size range.**
  Verify EVERY screen at the smallest supported size (iPhone SE / 4.7") and the
  largest (Pro Max / 6.9"), on both iOS and Android: nothing clipped, truncated,
  or overflowing horizontally; headers, cards, tables, and modals reflow instead
  of pushing off-screen; and touch targets are large enough for **gloved hands**
  on a jobsite (min ~44–48pt, adequate spacing). Especially check the dense/new
  UIs — logbook editors (crane/excavation/scaffold checklists, slump-test rows),
  the worker sign-in table, the camera overlay chrome, and the reports screen.
  Not gated to any build; a standalone QA sweep. Separate from the camera work.

- **[HIGH] SSC daily-log compliance toggles are two-state (seeded false) — a value the human never affirmed.**
  In `ssc_daily_safety_log.jsx`, five compliance fields — `incidents_reported`,
  `safety_meetings_held`, `fire_protection_in_place`, `housekeeping_satisfactory`,
  `ppe_compliance` — are two-state `ToggleRow`s seeded `false`. There is no
  untouched-vs-explicit-No distinction, so an untouched toggle persists as `false`
  and, on the DOB report, a bare "No" on e.g. PPE Compliance / Fire Protection
  reads as an affirmative self-incriminating safety-violation finding the CP may
  never have made (and a false "Yes" would be a fabricated attestation). The
  report now qualifies this with a footnote, but the real fix is at the source:
  make these tri-state (unset / Yes / No) or required-before-submit so an
  untouched toggle can't masquerade as either a compliance finding or a
  violation. Rides the batched native build. Same class as the CP-signature
  replay and the orientation false-cover — a stored value asserting something the
  human never affirmed.

- **[HIGH] Orientation coverage matching is heuristic — can FALSE-cover and hide an LL196 gap.**
  The combined-report subcontractor-orientation coverage number ("X of N on-site
  workers with first-time orientation on file", `generate_combined_report`) matches
  on-site check-ins to orientation docs by `worker_id` OR normalized name. Manual
  orientations mint a synthetic `worker_id` (`manual_<ts>_...`), so a name fallback
  is required — but two on-site workers sharing a normalized name can mark an
  un-oriented worker as covered, HIDING a real LL196 first-timer violation on a
  compliance document (false-negative — the dangerous direction). Real fix: persist
  an orientation flag/link on the WORKER record, keyed to the real worker and
  resolved at orientation time (rides the batched native build), so coverage is a
  direct lookup, not a name heuristic. Caveat in the same area: the coverage
  denominator uses `status == "checked_in"` as the on-site proxy; on a PAST-date
  report that means "checked in that day and never checked out," not literally "was
  on site" — fine for the live daily report, a caveat for historical dates.

- **[MED] Compliance-packet capture gaps — new EDITOR fields (batch with next native build).**
  Surfaced while building the report renderers (item C). The renderers can only
  show what the editors persist; these fields an inspector needs are NOT captured
  today and must be ADDED to the editor `data:{}` blocks (`frontend/app/logbooks/*.jsx`),
  then ride the NEXT native build — do not ship piecemeal:
  - **hot_work.jsx** — FDNY hot-work permit #; Certificate of Fitness # for the
    operator AND the fire-watch holder. (Today: no permit/C.O.F. number at all.)
  - **crane_operations.jsx** — rigger name, signal-person name, lift-director name
    (OSHA 1926.1400 qualified roles); measured wind-speed VALUE (today only a
    `wind_speed_checked` bool exists — no reading).
  - **excavation_monitoring.jsx** — units on every reading (depth, vibration
    threshold/current, baseline/current building readings); a per-reading
    timestamp on each adjacent-building row (a monitoring log needs reading times).
  - **subcontractor_orientation.jsx** — worker signature. `handleCreateNew` writes
    `worker_signature: null` hardcoded; the orientation acknowledgment is
    UNATTESTED without it (same integrity class as the CP signature). Capture the
    worker's signature at orientation.

- **[LOW] Concrete special-inspection fields — only if it becomes a TR record.**
  `concrete_operations.jsx` captures no cylinder/sample IDs and no special-inspector
  / TR# reference. Only matters if the concrete log is used as a special-inspection
  (TR1) record rather than an internal QA/pour log. Deferred until that's required.

- **[HIGH] Compliance packet incomplete — several logbook types under-render.**
  Found while extending report capitalization (commit 16df52c). In the report
  renderers (`backend/server.py`):
  - **hot_work, concrete_operations, crane_operations, excavation_monitoring,
    ssc_daily_safety_log** render in `generate_combined_report` as a raw
    `data.items()` key-value dump with NO field map — every field emitted
    generically, per-field semantics unknown (which is why capitalization was
    excluded, not applied blindly).
  - **osha_log, scaffold_maintenance, subcontractor_orientation** render NO
    structured fields at all: `generate_single_logbook_html` shows a bare
    `Status:` stub and `generate_combined_report` skips them entirely.
  These are the documents an inspector asks for BY NAME, so the gap is
  **completeness of the compliance packet, not formatting**. Fixing it needs a
  per-type field map for each type in BOTH renderers
  (`generate_single_logbook_html` and `generate_combined_report`). Capitalization
  then falls out for free via the existing `_capitalize_first` / `_sentence_case`.

- **Exception-surface drift on the logbooks screen (`app/logbooks/index.jsx`).**
  Three exception signals now render three different ways: `unsigned_orientations`
  is an invisible list-visibility gate (no count shown), `missing_toolbox_talk` is
  a Bell card, and `unaffirmed_logbooks` is an AlertTriangle card. PR B added the
  unknown-SST badge but deliberately REUSED the expired `reviewCard` treatment on
  site/checkins rather than adding a fourth one-off. The logbooks screen still
  carries three treatments and should be unified into one exception-row pattern —
  the same drift the semantic color taxonomy overhaul was meant to end. Not fixed
  in PR B (out of scope); logged here.

- **Signature-audit hole — first-submit logbooks (pre-PR-F).** For `daily_jobsite`,
  `toolbox_talk`, `preshift_signin`, and `scaffold_maintenance`, a `const created`
  block-scope ReferenceError threw on the FIRST submit of a new log, before
  `recordSignatureEvent`. The record was written but no signature audit event was
  recorded on first submit. PR F fixed the scope going forward, but **nothing
  reconstructs the missing events** — the `signature_events` audit trail has a
  permanent hole for every first-submit logbook of those four types filed before
  the PR-F commit. Second-submits and other log types are unaffected. If a
  backfill is ever needed, source of truth is the `logbooks` rows themselves
  (created_at / cp_signature) — the events cannot be recovered, only approximated.

- **Free text where a picker belongs — company and trade.** Device round 6,
  finding 5, ruled STORED-NOT-RENDERED and deliberately not fixed as a string.
  An OSHA register row on 588 Thomas S Boyland reads `A AZ`; every other row on
  the same filed document reads `AAZ`. `_capitalize_first` (server.py:18274)
  upper-cases the first non-space character and preserves the rest exactly, so
  nothing in the renderers inserted that space — somebody typed it into a row he
  had added by hand, and it filed.

  SAME CLASS as `Concrete` vs `Concrete / Cement`: a field the app already knows
  the answers to, offered as free text. The gate holds the companies on site and
  the taxonomy holds the trades, and neither is offered at the point of entry, so
  every hand-added row is one typo away from a filed document that disagrees with
  itself.

  THE TRADE PICKER on the backlog closes both — one control, sourced from what
  the project already knows, replacing free text on the company and trade fields.
  Recorded here rather than patched: normalising the stored string would hide the
  entry gap that produced it, and the next row would read `AA Z`.

- **[MED] `daily_jobsite` activity rows have no emptiness gate on EITHER renderer.**
  Device round 6, reported not fixed. `render_logbook_html`'s daily_jobsite
  branch (`act_rows`, server.py:13084) iterates `data.activities` and emits a
  row for every entry, with no test for whether the entry says anything — an
  untouched crew row prints as a line on a filed §3301.2 record carrying a CP's
  count of 0 and nothing else. The report-side rendering, which the round-6
  notes recorded as NOT LOCATED, was located while writing this entry:
  `generate_combined_report` builds its own activity table the same way
  (server.py:19228) and has the same gap. Two renderers, one missing rule.
  The OSHA register, the pre-shift sheet and (as of this round) the toolbox
  attendee table all gate their rows; these two do not.

  NOT THE SAME RULE, which is why it was reported rather than patched with the
  others. Those three are PERSON-owned records — every row names a man, so "no
  name, no row" is the rule and it is the same rule in all three. An activity
  row is CREW-owned: it names a company and a crew id, and what makes it real
  is arguable in a way the others are not (a crew that showed up and did
  nothing recordable is a fact about the day). Deciding the minimum content for
  an activity row is the per-form ruling `finalize_logbook` still defers to the
  operator, and inventing one in the renderer would assert a minimum the form
  has never declared.

- **[MED] `preshift_signin` can STORE a nameless worker row, though it never prints one.**
  Device round 6, reported not fixed. Both renderers gate the row on
  `if w.get("name", "").strip()`, so a nameless row has never reached a
  document — but the sheet is deliberately absent from
  `_SUBMIT_ROW_CONTENT_RULES` (`_SUBMIT_ROW_CONTENT_RULES_DEFERRED`), so the
  row is accepted and stored. The STORED record and the FILED record therefore
  differ: an inspector reading the PDF and an auditor reading the collection
  see different sheets, and only the second one shows the row.

  THE DEFERRAL STANDS and its reason is unchanged: `preshift_signin.jsx` has no
  client gate, so turning the server rule on would create a refusal a live CP
  meets for the first time mid-shift, at the gate, on the one form where being
  stopped costs a man the start of his day. It comes back when that form is
  ported onto the shared stepper and has a client gate in front of it — exactly
  the sequence `osha_log` followed, and exactly what item 1 of this round added
  to `osha_log` at FINAL SUBMIT.

- **[LOW] Two surfaces were NOT traced in device round 6 and are unverified.**
  Stated so neither is mistaken for cleared:
  - **The kiosk inspector view** (`app/site/logbooks.jsx`) was not traced for
    `osha_log` or `toolbox_talk`. The nameless-row rule was applied to the two
    PDF renderers and to what is filed; whether the on-site kiosk shows such a
    row is unknown.
  - **`daily_jobsite`'s report-side activity rendering** was recorded as not
    located; it has since been found (server.py:19228) and folded into the
    activity-row item above. Nothing about it is outstanding except the ruling
    that item is waiting on.

---

## E4 — lookup-worker enumeration: OPEN, waiting on device provisioning

`POST /api/checkin/lookup-worker` (`server.py:11045`) is **public, unauthenticated
and unthrottled**. Given a phone number it returns `found`, and when found
`worker_id`, `name`, `osha_number`, `has_osha_card` — so it is both a membership
oracle over phone numbers and a PII read. The endpoint's own comment records the
question as pending: *"this endpoint's (absent) auth are untouched — the PII
question on them is a separate, still-pending operator decision."*

**Three routes considered; all three ruled out for now.**

1. **Rate limit** — attempted and reverted in `1953e24`. The limiter worked in
   isolation and produced 12 order-dependent 429s in the full suite. Both
   hypotheses (duplicate `server` module objects; autouse fixtures not reaching
   `unittest.TestCase`) were probed and **disproved**, and the mechanism is still
   unexplained. **Do not attempt a third time.** The blocker is shared
   in-process test state — a test-infrastructure problem worth solving on its
   own, not inside a security fix.
2. **Trim the response** — rejected. `checkin.html` consumes `name` and
   `osha_number` (it forwards `osha_number` back into the
   register-and-checkin payload at `checkin.html:1142`). Trimming breaks the
   gate, and the gate is the one surface that cannot degrade.
3. **Require the project's kiosk device token** — the correct answer, and
   blocked on deployment rather than on design.

**Why route 3 is blocked, stated precisely.** NOT "the gate page cannot hold a
token." The mechanism is fully built: `server.py:3780` documents SITE DEVICE as
the first legitimate principal — *"Authorized for exactly ONE project — the one
it was provisioned for. `get_current_user` resolves a site_mode token to its
`site_devices` row and derives `company_id` from that device's project doc
server-side, so nothing here is client-asserted"* — with admin CRUD and
per-project provisioning at `server.py:12608–12730`.

`backend/checkin.html` simply holds no token (grepped: no `Authorization`, no
`Bearer`, no `token`, no `site_mode`; its `localStorage` carries only language
and the returning worker's own phone/id/name). It scopes itself by reading
`project_id` from a **query parameter or the NFC tag's `/info` response**
(`checkin.html:900`, `912`) and passing it in the body — client-asserted, which
is what the site-device model exists to avoid.

**THE REASON THIS IS BLOCKED: wiring the gate to a provisioned device token
would stop check-ins on any unprovisioned tablet, and the gate cannot degrade.
Deployment risk, not a page limitation.**

**This becomes cheap and correct the day gate devices are provisioned for any
other reason.** The `site_devices` infrastructure is built and waiting; only the
provisioning of existing field tablets is missing. Revisit then.

## E3 — subcontractor_id: None is handled correctly on the client

Closed by inspection, no change needed. The server returns
`subcontractor_id: None` whenever the (sub, trade) pair has no roster row and
states the contract as a comment — *"callers must treat it as no roster
identity"* (`server.py:18570`). An unenforced contract in a comment is a shape
that has bitten this project repeatedly, so the client was traced.

**It is enforced where it matters.** `photoBucketKey`
(`app/logbooks/daily_jobsite.jsx:121`) degrades in order:
`sub:{subcontractor_id}` → `row:{activity_id}` → `row-index:{index}`. So an
unrostered row gets **its own bucket of 10, never shared** — two unrelated subs
cannot merge, and the CP is not punished for the admin's unfinished data entry.
`isUnboundCrew` (`dailyJobsiteModel.js:423`) names the state explicitly.

**Residual, LOW:** the third fallback `row-index:{index}` IS position-dependent
and would move under a re-order. It is only reachable when a row has neither a
`subcontractor_id` nor an `activity_id`, and every construction path mints an
`activity_id` — so it is a defensive last resort, not a live path. Worth
knowing it exists rather than assuming the key is always stable.

## The UNASSIGNED model, corrected

Recorded because the short form is wrong in a way that would cause damage.

**Wrong:** "UNASSIGNED must never be stored."

**Right:** the sentinel **IS persisted, deliberately, on the `checkins` row.**
`checkin_record` carries it in `worker_trade` / `worker_company` / `trade` /
`company` (`server.py:10802-10805` and its twin at `11315`), and
`db.checkins.insert_one` runs *before* the pairing store with the sentinel
intact. `_display_sub_company` and the headcount renderer translate it to
"Pending assignment" / "Not yet assigned" at read time.

**What must never persist is the `worker_project_trades` PAIRING** — and for
one specific reason (`server.py:10231`): storing it there *"would make the next
visit read UNASSIGNED back and silently skip the `needs_trade_assignment` flag
the CP still has to clear."* Guarded twice: callers check
`not needs_trade_assignment`, and `_store_worker_project_trade` independently
rejects `trade == "UNASSIGNED"`.

Someone applying the short form literally would strip the sentinel from
`checkin_record` and break every renderer that depends on it — a worse outcome
than the thing the model was guarding against.

**Do not conflate with `subcontractor_id: None`.** Two sentinels, adjacent code
(four lines apart in `dailyJobsiteModel.js:175-184`), opposite rules:

| | |
|---|---|
| `"UNASSIGNED"` | transport value; converted to `''` on arrival client-side, never stored as a pairing |
| `subcontractor_id: None` | a legitimate persisted answer meaning *no roster identity*, which the code is right to store and right to refuse to fabricate around |

`isUnassignedWorkerRow` reads the first, `isUnboundCrew` the second. No overlap.

**Survey result (device round 6, E5):** all 34 sites classified — 6 coerce in
flight, 5 defend the pairing, 6 translate at render, 6 frontend, 11 tests.
Every one sits cleanly on one side of the line. Nothing to build.
