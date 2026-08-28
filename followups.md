# Follow-ups

Known gaps and deferred work, newest first.

- **[MED] FloatingNav's 18 screens still hardcode their clearance, and the
  sweep CANNOT be mechanical.**
  The three CpNav screens now derive it: `{ paddingBottom: insets.bottom +
  CP_NAV_CLEARANCE }`, from the nav's own style tokens. The same token would
  serve FloatingNav — measured side by side, **both pills are 58pt at the same
  24pt offset**, so one number covers both. What is not done is the other 18.

  **Why this is not a find-and-replace, and the finding that makes it hard:**

  `paddingBottom: 120` appears on **~34 screens**, and **most of them carry no
  nav at all** — `project/[id]/trades.jsx`, `site/checkins.jsx`,
  `workers/[id].jsx`, `admin/integrations.jsx`, `logbooks/*` step forms, and
  more. On those screens 120 is the app's house-wide bottom scroll padding and
  means nothing about a nav. On the ~18 that DO render one, the same literal is
  load-bearing.

  **The number is identical in both cases, and nothing in the source
  distinguishes them.** A sweep that replaces every `paddingBottom: 120` with
  the clearance token would over-pad twenty-odd screens that have no nav —
  adding 106pt of dead space to the bottom of lists that do not need it, which
  on a short list reads as a broken layout. A sweep that replaces none of them
  leaves the real defect in place.

  So it needs a **per-screen read**: does this screen render a nav, and is this
  number clearing it or padding a list? That is ~34 judgements, not one regex.
  Do not treat it as a rename.

  **Two screens at 140, neither justified.** `settings.jsx` was **110** until
  `37227ee` — *"Move insurance info to settings; fix settings scroll on web"* —
  bumped it to 140 as a side effect of a react-native-web scroll-height fix
  that had nothing to do with the nav. `app/index.jsx` carries 140 from an
  unexplained *"Update index.jsx"*. settings has been converted to the derived
  token and its 140 is gone; `app/index.jsx` still has it and is in scope for
  the sweep.

  **What the defect actually is,** so the sweep is not mistaken for tidying:
  the pill sits at `insets.bottom + 24`. On gesture navigation the inset is
  ~24, so it occupies ~106pt and a 120 clearance leaves ~14pt. On **3-button
  navigation** the inset is ~48, so it occupies ~130pt against 120 — already
  negative, and the pill covers the last row of the list. It does not look
  broken in a screenshot, because the pill is ~90% opaque and a covered row
  stays faintly visible. It is simply not tappable, which on a gloved hand
  outdoors reads as the app ignoring the press.

- **[MED] An admin holding the wrong sticker silently repoints a chip — the
  physical-layer sibling of the tag reassignment closed in #267.**
  Same shape, different layer, and it predates both changes.

  | | the API layer (#267, FIXED) | the physical layer (OPEN) |
  |---|---|---|
  | what moves | a tag row between projects | the URL burned into a chip |
  | trigger | an admin types an id already in use | an admin holds up a sticker already programmed |
  | old behaviour | `$pull` it off the other project, repoint the row | overwrite the NDEF record |
  | signal | an info-level log line | none at all |

  `writeNfcTag` requests `NdefFormatable` first and falls through to `Ndef`,
  which is correct and load-bearing — a blank tag only advertises the first, an
  already-written tag only the second. The consequence is that the write path
  cannot tell "blank sticker" from "a gate somebody is using": both are
  writable, and both get written. Hold up the wrong sticker and the chip at
  some other entrance quietly starts pointing at this project.

  **The old row is not deleted, which makes it worse, not better.** Nothing
  server-side changes: the other gate's `nfc_tags` row stays `active` and the
  admin screen still lists it. So the record says that entrance has a working
  tag, the tag exists, it is physically on the post — and it checks men in
  somewhere else. Nobody is turned away and nothing errors; the check-ins land
  on the wrong project, which is the same class of silent wrongness as a trade
  from another project (`test_no_cross_project_trade_bleed.py`).

  **Why it is not in scope of the change that surfaced it.** #269 wires
  `writeNfcTag` to a "program a tag for this" action on a provisional gate,
  which is the first UI that calls the write path with an explicit id. That
  makes the behaviour easier to reach; it does not create it. The existing
  registration flow has always been able to do this, and closing it means
  reading the chip's current NDEF before writing and refusing when it already
  carries a live gate for this company — a real change to the write path, on a
  flow an operator has device-tested. Worth doing deliberately, not as a rider.

  **What would fix it:** read the tag before writing (the tech is already
  acquired, so this is a read on a handle we hold), parse any existing
  `/checkin/{project}/{tag}` URL, and refuse when that tag_id resolves to an
  ACTIVE row — with the same discretion as #267's 409: name that the sticker is
  in use, never which project. An explicit "reprogram this tag" confirmation is
  the escape hatch, because a genuinely reused sticker is a real case.

- **[PRODUCT DECISION, NOT A DEFECT] A printed QR is a permanent,
  silently-copyable credential.**
  A printed check-in QR has **no expiry, no nonce and no rotation**. One
  screenshot works from anywhere, for anyone, indefinitely — until an admin
  deletes the tag, and deleting it also locks out the men actually standing at
  the gate. There is no revocation that costs nothing.

  **This gives away the only presence control the gate had.** An NFC tap
  requires the phone to be physically at the post; that physical-presence
  property was doing real work, and it was doing it alone. Scanning a code
  requires only line of sight to a photograph of it. Nothing else on the live
  path establishes location — see the geofence entry below, which does not run.

  `checkin_method` (added with the QR) makes the exposure **queryable, not
  controlled**: an admin can ask "show me every check-in on this project that
  came through a QR", which is worth having. It stops nothing.

  **Rotating tokens would fix it, and would destroy the printed-sign mode.**
  A QR encoding a short-lived signed token instead of a bare `tag_id` closes
  the sharing hole outright. It also means the code cannot be laminated and
  posted at the entrance, because a printed code is by definition static — the
  sign would be dead the moment its token expired. The gate is architecturally
  a static URL and the printed sign is the mode most sites will actually use.

  So this is a **decision about what the QR is for**, not a bug to be fixed:

  | | keeps | costs |
  |---|---|---|
  | static printed code | laminate it at the gate, works offline for the CP, zero admin involvement per worker | permanently shareable |
  | rotating token | sharing closed | no printed sign; the CP's screen becomes the only delivery, and it must be online to mint |

  **Recorded rather than chosen**, because the answer depends on whether QR
  check-in is a per-worker fallback (the CP holds up a phone when a radio is
  missing — rotation is affordable) or a posted alternative to the tag
  (rotation is not). Today it is built as the first and nothing stops it being
  used as the second.

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

## ~~The site device has no fall_protection tab~~ — FIXED

**Resolved in the fall-protection-tab PR.** Kept rather than deleted because
the *class* it belongs to is still open, and the entry below points at it.

`LOG_TABS` in `frontend/app/site/logbooks.jsx:40` listed **eleven** of the
twelve registered types. `fall_protection` was absent. The comment four lines
above it records the previous occurrence — five conditional types added to the
registry "and then had no tab that could show them", so "an inspector on the
site device could not reach a hot work permit, a crane log or an orientation
record at all." That fix added five and missed the sixth.

So a fall protection equipment log could be filed by the CP and not opened at
the kiosk. **Both halves were missing, not just the tab.** `renderLogContent`
was an eleven-branch if-chain on `log.log_type` with no `fall_protection` case
and no generic fallthrough — it returned the literal "No data available", so
adding the tab alone would have traded an unreachable log for one that opens
and claims to be empty. All three pieces landed together:

- `LOG_TABS` entry (`site/logbooks.jsx:66`)
- `tabFallProtection` (`src/i18n/en.js:1255`) plus ten `fp*` column labels (`:1448`)
- `renderFallProtection` and its branch (`site/logbooks.jsx`)

The renderer prints `FALL_PROTECTION_NOTICE` on the document, as this entry
asked. It does **not** re-word it: the string comes from
`fallProtection.standardNotice`, which `fallProtectionModel.test.cjs` already
holds equal to server.py's constant, so the tablet is the third surface
printing one wording rather than a fourth wording of the same sentence.
`fall_protection` remains the only registry entry with no `dob_reference`, on
purpose (`server.py:3545` explains why).

Two shape decisions a future reader will want the reasoning for, both recorded
in the renderer's own comments: the PDF's ten columns are split into a register
and a defects table because ten columns of a printed page do not fit a tablet
(`anchor_point` stays in the **register** — a Pass row that names its
anchorage is not a finding); and `impact_loaded` renders `Yes`/`No` rather
than this screen's ✓/✕, because everywhere else a ✓ is the good answer and here
`true` means the equipment *was* impact-loaded, which 1926.502(d)(19) makes
mandatory-removal.

## The checklist assignment feature serves flat and both clients read nested

**Parts 1, 3 and 4 are FIXED** — the four read endpoints now serve `checklist`
nested with a computed `completions` list, the title is derived per read, and
the re-assign path writes both copies of the roster. Pinned by
`backend/tests/test_checklist_read_shape.py` (29 cases; 24 of them fail against
the pre-fix handlers, and the five that pass are deliberate do-not-regress
pins). **Part 2 is OPEN by decision** — see below. `checklist-assign-hold` is
unblocked.

### 1. The break that held the route — FIXED

`app/checklists.jsx:101` called `details.checklist.items.forEach(...)` on the
payload from `/checklists/assignments/{id}`, which had no `checklist` key. It
threw, the surrounding catch swallowed it, and the CP saw "Could not load
checklist" — only on FIRST open, because once a completion record exists the
other branch runs. A newly assigned checklist could not be opened by the person
it was assigned to.

The fix covers **four** endpoints, not the three first recorded here:
`/projects/{id}/checklists`, `/checklists/assigned`,
`/checklists/assignments/{id}` and — for `completions` —
`/admin/checklists/{id}/assignments`, which serves `completion_stats` (a count)
while `admin/checklists/index.jsx:670` reads `completions[]`. Fixing only the
three would have left that screen blank next to every assignee.

Two things the original entry got wrong, both since verified against the code:

- **`user_name` DOES exist.** `complete_checklist` has always written it
  (`server.py:16715`); only `progress` was missing. The computed rows carry the
  stored name rather than re-deriving one.
- **`/checklists/assigned` needed more than the nest.** `checklists.jsx:198`
  reads `assignment.completion.progress` — *singular* `completion`, which was
  served, as the raw document, with no `progress`. So every CP's card read
  `0/0 items · 0%` and never turned green, including a CP who had just ticked
  every item. That progress is now computed too.

`completions` is computed, never stored: truthy `checked` flags over the
checklist's items. The count is **intersected with the live item ids**, so an
item deleted after someone ticked it cannot leave a stored completion reporting
5/4 — `completed <= total` always.

`/checklists/assignments/{id}` now 404s when the assignment's checklist is
gone. The list endpoints already skipped such an assignment, so this only
answers a stale deep link; serving `checklist: null` would have put the client
back on the same dereference.

### 2. Three response models that describe nothing — DELETED

`ChecklistResponse`, `ChecklistAssignmentResponse` and
`ChecklistCompletionResponse` (`server.py:3313-3345`) are declared and used
nowhere — no checklist endpoint carries a `response_model=`.

**Deliberately not folded into the shape fix.** Wiring `response_model` onto
these endpoints is how `ProjectResponse` silently stripped
`dropbox_folder_path` and cost three investigations: a model that omits a key
does not fail, it deletes. If these are ever wired up it is a change of its own
with its own tests, not a side effect of something else.

Two of the three are now actively misleading:
`ChecklistAssignmentResponse` documents `checklist_title` + `completion_stats`
— the flat shape, which nothing serves any more — and
`ChecklistCompletionResponse` declares `last_updated` where the writer stores
`updated_at`, so wiring it up as written would drop the timestamp.
`ChecklistResponse` alone still matches what `/admin/checklists` serves.

**All three are now deleted.** They validated nothing, stripped nothing and
documented a shape that no longer exists; the shape that does exist is pinned
by `tests/test_checklist_read_shape.py` and stated in the block comment above
the handlers. A note where they stood records why there are no response models
in this section, so the next person does not read the absence as an oversight.

`ChecklistItemCreate` and `ChecklistItemResponse` are equally dead — declared,
referenced nowhere, and `ChecklistCreate` types its items as
`List[Dict[str, Any]]` rather than using either. Left in place: they were not
in scope, and unlike the three deleted they describe nothing that has drifted.

### 3. `checklist_title` was frozen at creation — FIXED BY DERIVATION

The assign path copies `checklist.get("title")` onto the assignment document
and `update_checklist` never propagated a rename, so every existing assignment
kept printing the old name.

**The stale copy is still on every document. Nothing serves it.** The reads
join `db.checklists` for the title instead, and `_serialize_assignment` pops
`checklist_title` off the payload — which is what makes the frozen copy
invisible **without a backfill**. This is load-bearing, and the comment above
the handlers says so: re-adding the flat key (for a cheaper read, or because
the field looks unused) re-adds the bug. If the stored copy is ever wanted
again it needs a propagating write in `update_checklist` first, not a
restored read.

### 4. The re-assign path left the displayed names stale — FIXED

When an assignment already existed for a (checklist, project) pair, the assign
path `$set` `assigned_user_ids` and returned — changing the list the server
queries by and leaving `assigned_users`, the denormalized `[{id, name}]` list
both admin surfaces actually print, naming whoever was assigned before. The
roster is now built once per call (it does not vary by project) and written on
both the create and the re-assign path.

### Minor: keys served and read by nobody

Swept while fixing the above. None of these break anything today; each is a
place where the wire and the screen disagree and nothing says so.

| key | served by | read by |
|---|---|---|
| `is_completed` | `/checklists/assigned` | nobody — `checklists.jsx` derives completeness from `progress` |
| `completion_stats` | `/admin/checklists/{id}/assignments` | nobody — the screen reads `completions[]` |
| `assignment_count` | **nobody** | `admin/checklists/index.jsx:411`, which therefore prints `0 assignments` on every card, always |
| `last_updated` | nobody (the writer stores `updated_at`) | nobody — declared on `ChecklistCompletionResponse`, part 2 above |

`assignment_count` is the one with a user-visible consequence: the admin
checklist list states a fact about assignments that is never true. The other
three are dead weight. Both served keys were KEPT by the shape fix —
`completion_stats` still counts completion records, exactly as the
`count_documents` it replaced did — because removing a served key is its own
decision, not a side effect of changing a different one.

### The two `{assignment_id}` routes had no access check at all — FIXED

Recorded here first as a read-only leak on `get_assignment_details`. It was
worse than that: `complete_checklist` had no check either, so any
authenticated caller holding an assignment id could **file a completion**
against another tenant's checklist under their own name. The read exposed the
checklist body (project name, title, description, every item); the completion
each route returns was already caller-scoped, so no third party's answers were
ever exposed. Same class as the batch-1 read holes and the 25 company_id write
sites: the path parameter went straight into the query.

`_assert_assignment_access` is now the gate for both.

**Scoped through the PROJECT, not the assignment's own `company_id`.** An
assignment always names a project, so its tenancy resolves the way
`/projects/{id}/checklists` — the route that lists these very assignments —
already resolves it. That keeps the two answers consistent (what you can see
listed is what you can open), keeps the cross-company contractor branch
working, and means an assignment with a null or `""` company_id does **not**
become unreachable. `_same_company_or_403` is for a record with no project to
scope through; this is not one. An assignment with no `project_id` **is** fail
closed — there is nothing to scope through, so only the people it names may
read it.

**READ and WRITE are different rules.** Read: named on it, or project access —
an admin reviewing a checklist was never assigned it, and that is the entire
admin surface. Write: named on it and nothing else — a completion is one named
person's attestation that they did the work, and project access is never
grounds to file one. The owning company's admin may read an assignment and may
not complete it; that pair is tested against itself.

**A site device is EXCLUDED, explicitly, from both**, and refused *before* the
project branch it would otherwise satisfy on the `project_id` it carries. A
kiosk is a gate for workers tapping in and an inspector reading logs; a
checklist assignment is a task given to a named person and a site device is not
a person. It has no user id, so it can never appear in `assigned_user_ids`.
Stated in the code as an exclusion so nobody restores it as a fallthrough.

`test_checklist_assignment_access.py` — 23 cases. All 11 refusals and both
wiring pins fail against the pre-fix routes; the 10 allow cases pass before and
after, which is the half that proves the guard closed nothing that was
legitimately open.

### Production state when both fixes landed: the collection was EMPTY

Checked 2026-08-28, after the shape fix and the access gate:
`db.checklist_assignments.countDocuments({})` returned **0**.

**Both fixes are PREVENTION ONLY.** No row was ever served flat to a client, no
assignment was ever read across a tenancy boundary, and no completion was ever
filed against someone else's checklist — because there were no assignments. The
read leak and the write hole were both found *before the feature was ever
used*.

Three consequences worth stating, because each is a question somebody will ask
again:

- **Nothing became unreachable.** The fail-closed branch on an assignment with
  no `project_id` cannot strand a live row; there are none. Same shape as the
  `project_files` count before the double-permissive fix, and the same answer:
  the guard stops a shape being created, and answers it correctly if one ever
  is.
- **No migration and no backfill.** The frozen `checklist_title` copy that the
  derived read makes invisible does not exist on any document yet, so the
  question of what to do with stale copies is moot until an assignment is
  created — and after the fix, the copy that gets written is never read.
- **No disclosure to assess.** An `assignment_id` IDOR with an empty collection
  had nothing to disclose. This is not "we found no evidence of access"; there
  was nothing that could have been accessed.

The first real assignment will be created through the fixed assign path, so
every row the feature ever holds is written by code that denormalizes the
roster on both paths and read by code that derives the title.

## `checklist_items` means two unrelated things

**Do not grep-and-replace this key.** Two features use the name for different
shapes in different collections:

| | |
|---|---|
| `logbooks.data.checklist_items` | a DICT of safety-check booleans on the daily jobsite log — read at `server.py:15138`, `:21972`, `:22157`, plus `daily_jobsite.jsx:387/713` and `site/logbooks.jsx:459` |
| `checklist_assignments.checklist_items` | a LIST of checklist items on the assignment feature's read models — `server.py:15966`, `:16192`, `:16221` |

Renaming the second (as the nested-shape fix above would) with a blind
find-and-replace takes the first with it and breaks the investor page-one
renderer, which reads the daily jobsite dict to build its compliance line.
`test_investor_page_one.py:133` and `test_report_six_defects.py:649-679` seed
that dict and would be the ones to fail — but only if the tests are run, and
the two are far enough apart in the file that the connection is easy to miss.

The nested-shape fix has since landed **without a rename sweep**: it stopped
serving the assignment key rather than renaming it, and never touched the
logbook dict. Both tests above still pass. The warning stands for the next
person who greps.

## Ten places state a logbook's display name

Swept 2026-08-28, after the count moved three times in one session — reported
as five, then six, then "a seventh" — for want of a stated definition. So the
definition first.

**A copy is a place that independently states display names for two or more of
the twelve registered logbook types.** Not a place that mentions a type key
(that is the entry below); not a place that renders a name it was handed.

Method: `git ls-files`, **no `--include` allow-list**, filtered afterwards,
matching the twelve canonical names plus every shipped variant, longest-first
so `OSHA Log Book` is not eaten by `OSHA Log`. The allow-list is what hid a
copy the first time round.

### Shipped — five copies of one source

| Location | Coverage |
|---|---|
| `LOGBOOK_TYPE_REGISTRY` `server.py:3398` | 12/12 — **source of truth** |
| `type_title` chain `server.py:15104-15881` | 13 branches (12 + `.title()` fallback) |
| `section_title` chain `server.py:22203-23113` | 13 calls |
| `FALLBACK_LOG_TYPES` `logbooks/index.jsx:48` | 6/12 |
| **`screenTitle` set `i18n/en.js:227+`** | 10 per-form headers |
| **`tab*` set `i18n/en.js:1244+`** | 11/12 site-device tabs |

### Tests — four more restatements

`requiredLogbooksWiring.test.cjs` CATALOG (11/12), `test_investor_page_one.py`
(7/12, assertions on the page-1 compliance line), `test_logbook_renderers.py`
(6/12), `test_report_six_defects.py` (2/12).

**One source of truth, five shipped copies, four test restatements.** Earlier
counts said "five copies" because they counted only shipped ones AND missed
the finding below.

### i18n/en.js is TWO copies, not one

The part no previous count had. The file holds two independent name sets about
a thousand lines apart, and they disagree about the same types:

| key | `screenTitle` (per-form header) | `tab*` (site device) |
|---|---|---|
| `daily_jobsite` | Daily Jobsite Log | Daily Jobsite |
| `osha_log` | OSHA Log Book | OSHA / SST Log |
| `hot_work` | Hot Work Permit | Hot Work |
| `scaffold_maintenance` | Scaffold Maintenance Log | Scaffold Maintenance |
| `ssc_daily_safety_log` | SSC/SSM Daily Safety Log | SSC Daily Safety Log |

Treating them as one copy is why the shipped count read four. They are two,
they were maintained separately, and the distance between them in the file is
why nobody noticed they had drifted apart.

Copies 2 and 3 (server.py's two chains) are if/elif chains rendering per-type
BODIES, not lookup tables — collapsing them onto the registry means threading
the label through, which is a real refactor. `scaffold_maintenance` and
`osha_log` still disagree across all of them; `preshift_signin` was resolved
in #259.

## A new logbook type must be added to every list, and here are the lists

`fall_protection` was the last type registered and the enumerations were not
all updated with it. Recorded as a CLASS rather than as separate bugs, because
the failure is structural: nothing makes adding a type update the lists, so the
next type will land the same way.

**STATUS: all four absences are now closed, and one of the four was closed by
DELETING the list rather than adding to it.** The class is NOT closed — see
"What is still hardcoded" below. The four rows are kept with their original
finding so the next person can see what the failure looked like.

**Three real absences, verified one at a time. Two more looked like absences in
a bulk key-presence sweep and are not** — which is the reason each one needs
its own read rather than a grep result.

| List | Absent? | Consequence | Now |
|---|---|---|---|
| `LOG_TABS` `site/logbooks.jsx:40` | **YES** | no kiosk tab — unreachable to an inspector | **FIXED** — entry added |
| `renderLogContent` `site/logbooks.jsx:1302` | **YES** | no branch; returns the literal "No data available" | **FIXED** — `renderFallProtection` + branch |
| `ALL_TYPES` `logbookViewRenderers.test.cjs:177` | **YES** | **the guard for the two above, blind to the same type** | **GONE** — the list is deleted, not corrected; the keys are derived from `LOGBOOK_TYPE_REGISTRY` |
| `CATALOG` `requiredLogbooksWiring.test.cjs:76` | **YES** | fixture only; label assertions are shape-not-text, so nothing fails | **FIXED** — entry added; still a hardcoded fixture, and no assertion outcome changed (64 passed / 0 failed either way) |
| `tokens.js` | NO — false positive | every type key there sits inside a COMMENT narrating which form-port contributed which colour. There is no per-type map to be absent from, and nothing is styled by log type. |
| `submitSignatureGate.test.cjs` | NO — false positive, inverted | it does not hardcode a list. It DERIVES one from `LOGBOOK_TIMING_CLASS` in server.py by regex and asserts `IMMEDIATE.length === 10`, with a comment reading "TEN with the fall-protection log". The type is gated and tested. |

### The one that mattered, and what replaced it

`logbookViewRenderers.test.cjs:177` was headed *"every type has a tab, or the
renderer is unreachable"* and asserted `ALL_TYPES.every((k) => tabKeys.includes(k))`.
Its `ALL_TYPES` was a hardcoded eleven **with `fall_protection` missing**. So
the test written precisely to catch "a registered type with no tab" could not
catch it for this type — it passed vacuously, for the same reason the gap
existed.

Same family as the AST entry, the receiver-group entry and the `.cjs` grep: a
check that ran, reported clean, and could not see the thing it was for.

`ALL_TYPES` is now **deleted**. Section 0 of that file reads
`LOGBOOK_TYPE_REGISTRY` out of `server.py` — the file-path arithmetic
`submitSignatureGate.test.cjs:45` already uses — and holds three things
against it:

1. `ok(REGISTRY.length === 12)`
2. every registered key has a `LOG_TABS` entry (and no tab stands for an
   unregistered key)
3. `renderLogContent` is **executed** once per registered key and must not
   return the literal "No data available"

(3) runs the chain rather than grepping it, because "the branch exists" is
exactly what a source grep would have confirmed of the eight types that
rendered nothing.

**Verified by breaking it, four ways**, since a guard that cannot fail is the
thing this entry is about. Removing the branch → 1 failure. Removing the tab →
1 failure. Renaming `LOGBOOK_TYPE_REGISTRY` so the regex matches nothing → the
count fails (2 failures). Registering a 13th type with no tab and no branch →
3 failures. Restored: 94 passed, 0 failed.

**Two caveats, stated in the test file itself and not only here.** The count is
load-bearing, not decoration: without it a formatting change in server.py makes
the regex yield `[]` and every `.every()` passes over an empty list — the same
vacuous pass one level up, and harder to see. And it catches the DRIFT CLASS
only: a branch that reads the wrong payload keys passes it exactly as loudly as
a correct one. The per-type key assertions in section 1 are hand-written and a
new type still needs its own set.

### What is still hardcoded

Adding a logbook type means updating: `LOGBOOK_TYPE_REGISTRY`, the `type_title`
chain, the `section_title` chain, `FALLBACK_LOG_TYPES`, both `i18n/en.js` sets,
`LOG_TABS`, `renderLogContent`, and the fixture `CATALOG`. `ALL_TYPES` is off
this list because it no longer exists.

But note WHICH lists drifted. The ones that DERIVE their contents from server.py
at run time — submitSignatureGate's timing-class regex, and
logbookViewRenderers' own `tabKeys` extraction — cannot drift, and did not.
Every list that drifted was hardcoded. The durable fix is not a longer
checklist; it is deriving these lists from the registry the way those already
do, and keeping a COUNT assertion (`IMMEDIATE.length === 10`,
`REGISTRY.length === 12`) as the checkpoint that forces a new type to be
handled rather than inherited by omission. That has now been done for the
inspector-view surface. It has not been done for the `type_title` /
`section_title` chains (if/elif chains rendering per-type BODIES, so collapsing
them onto the registry means threading the label through — a real refactor),
for `FALLBACK_LOG_TYPES`, or for the i18n sets.

### Left deliberately: SPARSE / KEPT / ABSENT_FIELD

`logbookViewRenderers.test.cjs` carries three more hardcoded per-type maps —
`SPARSE`, `KEPT` and `ABSENT_FIELD` — feeding the "an absent field says so"
sweep. Same drift shape as `ALL_TYPES` on paper, and **not** changed with it.

They are **intentionally partial**: each entry is a hand-chosen sparse payload,
the one value that must survive it, and the one field that must read
"— Not recorded". There is no registry-derivable content to replace them with —
the registry knows a type's key, not which of its fields is the interesting
absence. A missing entry costs coverage of one type in one sweep; it does not
make a filed log unreachable. Weaker case, recorded so the next reader does not
mistake the omission for an oversight.

### Sweep caveat

The bulk key-presence pass counted `site/logbooks.jsx` as 12/12 because
`fall_protection` is a substring of `fall_protection_required`, an orientation
checklist item key at line 1229. Substring matching on type keys overstates
coverage wherever a longer key shares a prefix.
