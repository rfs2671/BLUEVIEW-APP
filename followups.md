# Follow-ups

Known gaps and deferred work, newest first.

- **[MEDIUM] REBASE, NEVER MERGE, across branches that touch the same subsystem
  — and read the result. A merge tool resolves TEXT; nothing resolves an
  assumption that was true in both parents and false in the child.**
  Standing rule as of 2026-09-04. It has now paid on both of its first two
  applications, and **both times the defect was in neither branch**.

  **First (`test_absence_literals_are_specific`).** `backend/server.py`
  auto-merged cleanly and the combined tree still tripped the repo's own floor:
  415 unclassified `assertNotIn` haystacks against a cap of 410. The five over
  the line read a LOCAL `body` variable, which the auditor cannot prove is
  source text — so those assertions were never audited. Not wrong;
  **unexamined**, which is the state that file exists to prevent. Inlining the
  slice to make them visible then failed four MORE for a real reason: bare
  words instead of constructs (`_upload_to_r2` is satisfied by a comment
  mentioning it, when the assertion is that the reader does not WRITE).

  **Second (`docCache` keep-set) — the sharper one.** `collectKeepNames`
  rebuilds the sweep's keep-set from list records, which carry an id and a
  version but no extension, so it enumerates what the cache can write. Its
  comment said "keep every extension this cache can produce" and the code added
  exactly one:

      keep.add(safeName(id, v, 'pdf'));

  True enough to be invisible for as long as `pdf` was the only extension
  written. The instant plan thumbnails write `.jpg`, it is a silent deletion
  bug — and `sweepDocCache` runs from the plans screen on every successful list
  load, so the next sweep from ANY screen wipes every thumbnail.

  **IT WOULD HAVE BEEN UNFINDABLE IN THE FIELD.** No error, no failing test, no
  crash. It presents as "thumbnails don't work", intermittently, on a screen
  whose whole purpose is to be glanceable. Fixed with `CACHE_EXTS`; proved by a
  control run that fails three assertions with the keep-set reverted, one of
  them catching a thumbnail deleted between two runs.

  **THE SHAPE OF THE CLASS.** Both defects lived in an assumption each branch
  was individually entitled to make — "pdf is the only extension", "the auditor
  sees my haystack" — and that only became false when the other branch landed.
  A clean auto-merge is not evidence; it is the absence of a TEXT conflict, and
  these were not text conflicts. So: rebase the second branch onto the first,
  then READ the resolved files and run the gates against the combined tree,
  even when git reports no conflict at all.

- **[MEDIUM] A build that could not reach its subject passed as a build, and
  `tail -2` is what hid it. Twelfth instance of the class.**
  Running `expo export` in a second git worktree produced a **662-module,
  986 kB** bundle instead of the real **3498-module, 6.33 MB** one. Every route
  then failed mount-smoke with `pageerror: No routes found` — the app's own
  `app/` directory was not in the bundle at all.

  **The cause is the `node_modules` junction the worktree recipe depends on.**
  Worktrees have no `node_modules`, so the recipe junctions the main checkout's
  (see the mount-smoke note in memory). Metro's cache lives under the OS temp
  directory and is keyed on a project root that resolves THROUGH that junction,
  so two worktrees share one cache entry and the second one inherits a
  resolution built for the first. `TMPDIR`/`TEMP`/`TMP` pointed at a scratch
  directory fixes it:

      TMPDIR=<scratch> TEMP=<scratch> TMP=<scratch> npx expo export --platform web --output-dir dist

  **WHY IT SURVIVED A ROUND OF VERIFICATION.** The export and the smoke run were
  chained and piped through `tail -2`, which showed the last two ROUTE lines and
  not the summary. A 0/74 run and a 74/74 run look identical through that pipe.
  The failure was found only by a control run — stashing the change and
  re-exporting — which proved the broken bundle predated it.

  **THE RULE.** Never truncate the output of a gate. `tail` on a build or a test
  run is the same move as a green suite that never executed the file it names,
  and this codebase has now recorded twelve of those. If output volume is the
  problem, `grep` for the summary line — which asserts the summary EXISTS —
  rather than taking the last N lines, which asserts nothing.

- **[LOW] The 20 `index_version: 1` plan pages need a re-index before their
  projects go live — scheduled, not urgent.**
  Coverage measured 2026-09-04: `document_page_index` holds 267 v2 pages with
  100% `page_jpeg_r2_key` coverage (164 of them 588 Thomas), and **20 v1 pages
  on other projects with none**. Nothing migrates them; `index_version` is
  stamped and never swept, so they stay v1 until someone re-indexes those files.

  **They are slow, not broken.** Every reader that wants a page image degrades
  correctly: `_fetch_page_jpeg` falls back to rendering from the source PDF, the
  thumbnail and base-layer ladders bottom out on that same re-render, and the
  manifest's `t` flag is simply absent so a device does not prefetch a
  thumbnail it cannot get.

  **The scale argument, which is why this is recorded rather than ignored.** On
  a v1 file EVERY thumbnail and base-layer request pays a full poppler render of
  a 36x48 sheet at 250 DPI, with no cache in front of it. That is seconds of
  backend CPU per request. Fine for 20 pages on dormant projects; not fine if
  one of those projects goes live and a plan list requests a thumbnail per row.

  **Do it before those projects go live, not now.**

- **[LOW] Two folder-grouping implementations now exist, and the kiosk keeping
  its own was a decision, not drift.**
  `src/utils/dropboxTree.js` is the shared one, lifted out of
  `app/site/documents.jsx` during the Dropbox redesign and now used by
  `app/projects/[id]/files.jsx` and `app/documents.jsx`. The kiosk screen still
  carries its private original.

  **They do not agree, and that is the whole reason one was not deleted.**

  | | `site/documents.jsx`'s `folderOf` | `dropboxTree.js`'s `folderPathOf` |
  |---|---|---|
  | key | the immediate parent's NAME | the full path above the file |
  | `Approved/Plans/a.pdf` | `Plans` | `Approved/Plans` |
  | `Superseded/Plans/a.pdf` | `Plans` | `Superseded/Plans` |
  | result | both files in ONE group | two groups |

  So switching the kiosk to the shared helper is not a refactor — it changes
  what a superintendent sees on the tablet. Today two same-named folders under
  different parents merge into a single list; afterwards they separate, the
  group headers grow from `Plans` to `Approved/Plans`, and the group count on
  that screen goes up. On a narrow tablet the longer headers are the part most
  likely to look wrong.

  **Which behaviour is right is a question about the tablet, not about the
  code.** The full path is more honest — two folders named `Plans` are two
  folders, and merging them produces a list belonging to neither. But the kiosk
  is a glanceable screen used one-handed outdoors, and short headers may be
  worth more there than precision. Nobody has looked at a real project's folder
  layout on the device to decide, and the redesign that produced the shared
  helper was scoped to the CP/admin screens; changing kiosk output from inside
  it would have been an unreviewed behaviour change riding along with a rename.

  **To close this**, open a real project's Dropbox tree on the tablet and check
  whether any two folders share a name under different parents. If none do, the
  two implementations are behaviourally identical on live data and the kiosk can
  adopt the shared one for free. If some do, decide deliberately which grouping
  the kiosk wants, and if it wants the parent-name form, move THAT into
  `dropboxTree.js` as a named option rather than leaving a second copy.
- **[MED] `sst_status` can be set to "expiring_soon" by a certification that is
  not an SST card.**
  `register_and_checkin` derives the frozen per-check-in SST verdict from a set
  of warning TYPES:

  ```
  elif "CERT_EXPIRING_SOON" in _warning_types:
      sst_status = "expiring_soon"
  ```

  `CERT_EXPIRING_SOON` is raised by `validate_worker_certifications` for **any**
  certification carrying an expiry inside 30 days — check 3 loops `for c in
  certs`, not over the SST rows. Every other branch in that chain is
  SST-specific: `EXPIRED_SST` and `SST_UNKNOWN` come from the SST three-state
  verdict, and the `_sst_cert is None` branch reads the SST cert directly.

  So a worker whose SST is valid for another three years, holding any other
  dated credential expiring next week, has `sst_status="expiring_soon"` frozen
  onto his check-in row. That row is the immutable compliance record — the
  whole point of the snapshot is that "did worker X hold a valid SST on date Y"
  is answerable from `checkins` alone — and this makes it answer about a
  different card.

  **Why post-2020 OSHA does not save us.** The OSHA branch stores
  `expiration_date: None` (lifetime), so today the SST row is usually the only
  dated one and the mislabel is rare. It is not structural: `POST
  /workers/{id}/certifications` accepts a `WorkerCertification` with an
  arbitrary `type` and an `expiration_date`, so any admin-added dated
  credential reaches this branch.

  **The fix is narrowing, not reordering** — the branch needs the warning to
  have come from a cert in `RECOGNIZED_SST_TYPES`, which means
  `CERT_EXPIRING_SOON` warnings need to be filtered by `cert_type` at the point
  of use rather than tested for mere presence in a set of type strings. Held
  out of the expiry-sweep PR deliberately: it changes a value frozen onto
  `checkins`, so it wants its own change and its own backfill question (rows
  already written carry the wrong label and nothing rewrites them).

- **[LOW] The `worker_cert_expiry` index cannot be used by any query written in
  this codebase's own house style.**
  The index carries `partialFilterExpression={"is_deleted": {"$eq": False}}`.
  Mongo uses a partial index only when the query predicate *implies* that
  filter, and `{"is_deleted": {"$ne": True}}` does not — `$ne: True` also
  matches documents where the field is missing or null, which the index does
  not contain.

  Every other worker query in `server.py` uses `$ne: True`. So until section 5
  of `nightly_compliance_check` was added, the index was unread; and section 5
  can only read it by writing `{"is_deleted": False}`, which is the *one* place
  in the file that spells the filter that way. That is a comment-load-bearing
  inconsistency: the next person to "fix" it for consistency silently drops the
  index.

  **READ THIS BEFORE PLANNING THE FIX. `partialFilterExpression` DOES NOT
  ACCEPT `$ne`.** MongoDB restricts it to equality, `$exists: true`,
  `$gt`/`$gte`/`$lt`/`$lte`, `$type`, `$and`/`$or` and `$in`. `$ne` is not on
  that list and `createIndex` rejects it.

  So the obvious repair — "change the index to `{"is_deleted": {"$ne": True}}`
  so it matches how the codebase queries" — **is not an available option.** It
  is the first thing anyone will reach for, and it does not exist. There are
  exactly two:

  1. **Drop the `partialFilterExpression`.** The index then covers the whole
     collection and the house-style `$ne: True` predicate can use it. Cost:
     soft-deleted workers are indexed too.
  2. **Keep it.** Cost: this index has exactly one legal caller, and that
     caller is spelled differently from every other worker query in the file.
     Whoever "tidies" that spelling silently drops the index.

  There is no third choice where the index keeps a partial filter AND the
  house-style predicate can use it. Pick 1 or 2.

  Section 5 also logs a coverage probe on every run — it counts workers in the
  expiry window reachable by the loose predicate versus the indexed one, and
  warns when they differ. If that line never fires in production, the two sets
  are identical and dropping the partial filter costs nothing.

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

## A TEST DOUBLE WHOSE `sort()` DID NOTHING PASSED A DETERMINISM ASSERTION

**THIRD INSTANCE THIS WEEK of a check that ran and could not see the thing it
was for — and the FIRST where the blind spot was in the HARNESS rather than in
the search.**

`cs_attribution_for` was fixed to read the ACTIVE registration deterministically:

```python
_regs = await db_.cs_registrations.find({...}).sort(
    [("created_at", -1), ("_id", -1)]).to_list(20)
```

The test asserted the ordering — same input, two orders, same answer. It
passed. The fake cursor was:

```python
def sort(self, *a, **k):
    return self          # <-- accepts the call, ignores the spec
```

So `to_list` returned INSERTION order, the assertion compared insertion order
against itself, and **it would have passed just as well if the production code
had no `sort()` at all.** The assertion tested the fake.

**WHAT MAKES THIS ITS OWN FAILURE.** The other two were searches too narrow for
their claim: `git log -S` on two literals reported "the code did not change"
while `get_current_user` had; a `_filed_log` review read four functions and
never opened `_authorize_logbook_write`. Both were the *question* being
wrong. Here the question was exactly right — "does the order of the input
change the answer" is the correct test for a determinism fix — and the
INSTRUMENT could not measure it. A green assertion is evidence about the
harness first and the code second, and only the second if the harness models
the call.

**THE RULE.** *A double must model every call the code under test makes, or the
assertions that depend on that call are decoration.* A stub that accepts a
method and ignores its arguments is worse than one that raises: raising fails
loudly the moment the code starts using it, while `return self` silently
converts an assertion into a tautology.

**HOW TO CATCH IT, cheaply:** make the double's behaviour observable and assert
on it. If `sort()` is a no-op, feed it input whose insertion order is WRONG and
watch the test fail. The corrected fake applies the spec:

```python
def sort(self, spec, *a, **k):
    for field, direction in reversed(list(spec)):
        self.docs.sort(key=lambda d: d.get(field), reverse=(direction == -1))
    return self
```

and the hostile fixture — the deactivated registration FIRST, which is the
order an unsorted `find_one` is entitled to return — now fails against the old
code and passes against the new.

**AND THE SAME SHAPE ELSEWHERE.** `test_logbook_write_guards`' collection double
gained a `find()` the same week, because `amend_logbook` started calling one and
a double that cannot model a call fails on the fake rather than on the guard.
That one failed loudly (AttributeError) and was fixed in minutes. This one
passed quietly. **Prefer doubles that raise on an unmodelled call over doubles
that shrug.**

## A LOSING FORK HAS NO WAY OUT, AND ONE IS LIVE ON 588 THOMAS

**KNOWN PERMANENT STATE ON A PRODUCTION RECORD. One worker, one document, no
exit.**

Angel Lopez's orientation on 588 Thomas has two unsigned amendment children of
the same parent (`6a95b43e8392cee9e0c217f9`), filed 49 seconds apart on
2026-08-31 at 17:09:58 and 17:10:47. Michael signs the NEWER one -- `_filed_log`
takes the newest FILED row, so signing the older would leave the newer able to
supersede it the moment anyone signed that instead.

**WHAT HAPPENS TO THE LOSER, precisely:**

  * it stays `status: "draft"`, `is_locked: false`, `cp_signature: null`,
    **forever**. There is no state that means "this correction was abandoned";
  * `_filed_log` ignores it -- correctly, an unsigned amendment is an
    intention, not a correction -- so it never reaches a filed report;
  * the **stale-unsigned card lists it as "correction to sign" indefinitely**,
    nagging the CP about a correction he deliberately abandoned;
  * and after #333 it **blocks every future amendment of that orientation**: it
    is an open head, so `AMENDMENT_ALREADY_OPEN` refuses the next one and
    offers him the draft he has no intention of finishing.

**THE LAST POINT IS THE SHARP ONE.** #333's refusal is right and it turns a
stall into a dead end wherever a fork already exists. Refusing a second
amendment while the first can only be signed or abandoned leaves no move. The
refusal and the withdraw path are ONE change; only the refusal shipped, and
this entry is the debt.

**WHAT A WITHDRAW PATH NEEDS -- OPEN, NOT DESIGNED.**

**1. Who may withdraw.** The filer is not always the signer: on 2026-08-31 the
owner filed an amendment only the CP could sign. Candidates, none obviously
right -- the person who FILED it (they know it was a mistake, but cannot sign
so cannot be said to have judged the record), the person who would SIGN it
(they bear the attestation, but did not create the thing being withdrawn), or
either. The one clear rule: **not a background process.** Nothing that touches
a compliance record may withdraw an intention to correct it.

**2. What the withdrawn row says on a filed record.** It must remain a
document -- deleting it would erase evidence that somebody thought the record
was wrong, which is exactly the fact a later reader needs. So it needs a state
(`withdrawn_at`, `withdrawn_by`, and a REASON, subject to the same readability
rule as `amendment_reason` -- see "IS THERE A NUMBER"), and every reader has to
learn it: `_filed_log` (ignore, as now), the stale-unsigned card (stop
listing), `open_amendment_head` (stop blocking), and the chain display
(`amendmentChain.js` -- a withdrawn link is part of the history and must not
count toward "Corrected N times" as though it landed).

**3. IS WITHDRAWING ITSELF AN ATTESTED ACT? This is the question that decides
the shape, and it is not a detail.**

If withdrawing is attested -- signed, in the `signature_events` ledger, with an
`acting_capacity` -- then it is a statement on the record: *"I considered this
correction and decided the record did not need it."* That is meaningful to an
inspector, it is defensible at an OATH hearing, and it makes withdrawal a
deliberate act nobody performs by accident. It also means only somebody who can
SIGN may withdraw, which answers question 1 -- and it makes cleaning up a
mis-tap as heavy as filing the correction was.

If it is NOT attested -- a soft state, like discarding a draft -- then it is
cheap and fixes the mis-tap case, and it lets an unsigned intention vanish from
the record with nobody accountable for that decision. On a document that
already distinguishes an intention from a correction, that asymmetry needs an
argument.

**The answer decides everything else**, so it should be settled first and by
the operator, not inferred from whatever is easiest to build.

**THE OPERATOR'S LEANING, 2026-08-31 -- A LEANING, NOT A RULING.** Attested.
The reasoning, in his words: this app already distinguishes an intention from a
correction, and a withdrawal is a decision about a compliance record. It also
answers "who may withdraw" for free -- only somebody who can sign -- which is
the part with no obvious answer otherwise.

Recorded so whoever builds this starts from it rather than from scratch, and
recorded as a LEANING because it was reached without the cost being known.
What would argue against it: attested withdrawal makes cleaning up a mis-tap as
heavy as filing the correction was, and the 2026-08-31 fork was a mis-tap --
five amendments in eight minutes from a man who could not tell he already had
one open. If the common case turns out to be fumbles rather than judgements,
the weight lands in the wrong place. That is worth measuring before building,
not arguing about now.

**AND IT IS NOT URGENT.** One orphan on one worker is a smaller cost than a
lifecycle designed at midnight. Recorded so the next person meets a known
state rather than a mystery.

## AN AMENDMENT FILED AND NEVER SIGNED IS A CORRECTION THAT DID NOT HAPPEN

**Three of them had been sitting on 588 Thomas since 2026-08-14, and nothing in
the product said so until the card shipped on 2026-08-31.**

`amend_logbook` leaves the parent locked and creates an unsigned editable
child. `_filed_log` then prints the PARENT until the amendment is signed --
deliberately, and the reasoning is sound: "AN UNSIGNED AMENDMENT IS NOT A
CORRECTION, it is an intention to correct", and replacing a signed record with
an unattested one on a document that reaches lenders would assert a change
nobody made.

**THE CONSEQUENCE NOBODY CLOSED.** If the CP never signs, that intention never
becomes anything. The parent stands as the record, the correction has no
effect, and **no surface anywhere reported the gap**: not the logbooks list
(scoped to today), not the report (prints the parent, correctly), not the
admin. Somebody decided a filed record was wrong, said why, and the record
stayed wrong. Three times, over a week, on a live project.

**THE FIRST ACT OF THE NEW CARD WAS TO FIND REAL WORK.** The
`amendment_unsigned` state shipped the same evening and immediately surfaced
Aug 7, Aug 10 and Aug 14. It was read as a false alarm -- three rows for one
amendment filed that night -- and it was not: the 08-31 amendment is correctly
ABSENT (`date: {"$lt": eastern_date()}` excludes today), and the three it found
were genuine. **The instinct that a new detector firing immediately must be
broken is worth resisting for one query.**

**A LATENT DEFECT IN THAT STATE, SEPARATE AND STILL OPEN.** `_amend_meta` is
built from `stale_unsigned_docs` RAW, while the pre-existing path filters the
same list through `not _is_affirmed_signature(d.get("cp_signature"))`. The
amendment loop skips that filter and then ASSIGNS into `_gaps`
unconditionally, so it can ADD a row that was never a gap: **an amendment that
has been signed but not finalized will be listed as "correction to sign"
forever.** It did not fire here because these three are genuinely unsigned. One
line fixes it -- apply the same signature filter -- and it should be fixed
before anyone trusts the count.

**WHAT SHOULD CHASE AN UNSIGNED AMENDMENT -- OPEN QUESTION, NOT DECIDED.** The
card is necessary and is not sufficient: it reaches the CP only, only when he
opens that project, and it is the same surface that stayed silent for a week
before it existed. The options, with what each costs:

  * **A deficiency.** Strongest, and probably wrong: a deficiency asserts a
    site condition, and an unfinished correction is a paperwork state. It would
    put an administrative gap into a compliance channel that inspectors read.
  * **The nightly sweep.** `sweep_stale_end_of_day_logs` already walks unlocked
    end-of-day logs and declines to freeze the ones a person must finish. An
    amendment is exactly that shape and the sweep already sees it. Cheapest
    correct home for a count.
  * **The admin.** The person who FILED the amendment is not the person who can
    sign it, and today nothing tells the filer their correction stalled. Roy
    filed one tonight and would learn nothing if it sat until December. This is
    the real gap.
  * **Email.** Only if the above are exhausted -- another daily digest line is
    the easiest thing to stop reading.
  * **Nothing beyond the card.** Defensible ONLY if the card is made to reach
    the filer as well as the signer.

**AND THE HARD PART, WHICH IS NOT A NOTIFICATION.** An amendment nobody signs
should eventually be resolved, not accumulate: either signed, or withdrawn with
a reason, on the record. There is no withdraw path today, so the only ways out
are signing it or leaving it forever. That is the design question underneath
the alerting one and it should be answered first.

## "IS THERE A NUMBER" IS NOT "WHO PUT IT THERE"

**The week's recurring defect, which recurred inside its own fix and was caught
by a person, not a test.**

Two writers were added on 2026-08-31 to merge a gate crew into the CP's row.
Both decided authorship like this:

```js
const _cpTyped = String(row.num_workers ?? '').trim() !== '';   // reconcile
```
```python
cp_typed = _count(h) != ""                                      # dry-run script
```

Neither consulted `num_workers_source`. Both stamped `'cp'` on any row carrying
a count. The dry run printed "(cp)" for C1, C2, C3 and C4 alike; three of those
numbers came from gate seeding and **no CP ever typed them**. Only C4 was real
-- he typed 5 where the gate recorded 4. It was one approval from filing a
fabricated author onto a signed 3301.2 record, and it was caught only because
the operator said the CP had typed nothing all day.

**THE GENERAL RULE.** *A question about the data is not a question about
provenance.* "Is there a number here" is answerable from the row alone. "Who
put it there" is not: it needs a field recording an ACT, and when that field is
absent the honest answer is **unknown**, never a default.

**DEFAULTING IS THE FAILURE.** A two-state answer must invent the third. Every
instance of this family resolved the same way, by refusing to guess:

  * the manufactured `"0"` on a crew whose count was never typed;
  * the OSHA register's em dash printing one glyph for four meanings;
  * `PREDATES_CAPTURE`, which labels an unknowable rather than backfilling it;
  * and now `num_workers_source`, which is `cp`, `gate`, or ABSENT.

**AND THE RULE ABOUT READING AN INSTRUCTION.** *A rule stated in terms of a
human act must be implemented against the artifact of that act.* The operator
said "the CP typed a count". That was implemented as "a count exists" -- the
cheapest available proxy -- when the artifact of the typing already existed:
`num_workers_source`, written by `commitAddCrew` and `applyHeadcountEdit`
exactly when a number is entered, three commits old (#250, 2026-08-27).

When an instruction names something a person DID, find the field that records
them doing it. If there is none, say so before implementing -- do not
substitute a correlate and do not let the absence resolve silently.

**THE READER HAD ALREADY GOT THIS RIGHT AND BOTH WRITERS OVERRODE IT.**
`_headcount_cell` in server.py has carried this since it was written:

> ABSENCE MEANS GATE. Drafts written before num_workers_source existed carry no
> marker and hold numbers that came from the roster; labelling those "(CP)"
> would put a false attribution on records that are already filed.

Neither writer looked at it.

**THE RULE, AND IT IS NOT ABOUT READERS.** *Before adding a writer for a field,
read the reader AND EVERY OTHER WRITER.* The point is that the field already
has a governing decision somewhere, and a new writer's job is to FIND it -- not
to re-derive it from the field's name and hope the two agree.

**IT HAPPENED THREE TIMES IN ONE DAY, on the same field:**

  * `_headcount_cell` (the reader) had the rule and said so in its docstring.
  * #326 (the reconcile) rediscovered it the hard way and encoded it.
  * The dry-run script did neither, because its `gate_sourced = True` line was
    written in #323 -- before #326 existed -- and #326 never went back for it.

The third one is the instructive one: the script was not written by someone who
ignored the rule, it was written before the rule and then *left behind* by it.
So the sweep is both directions -- when a rule is established, find every
writer that predates it, and when a writer is added, find every rule that
precedes it. Neither half is optional and the first is the one that gets
skipped.

**WHAT IT WOULD HAVE COST.** The amendment written to REMOVE a fabricated
attribution would have flagged three unattributed rows as gate-confirmed, and
the next reconcile would have overwritten the very numbers it preserved:
4 -> 6, 8 -> 6, 3 -> 2, on the CP's screen, before he signed the correction.
Caught by the operator reading the dry-run output, not by any test.

## AN AMENDMENT IS A NEW EDITABLE CHILD, NOT A CLOSED DOCUMENT

**Assume the opposite and you will reason yourself into the dangerous
direction.** `POST /api/logbooks/{id}/amend` leaves the original locked and
intact and creates a CHILD carrying:

```python
"cp_signature": None,      # an amendment must be re-signed
"status": "draft",
"is_locked": False,
"is_amendment": True,
```

**So it gets edited, and it gets RECONCILED.** The CP opens the amendment to
sign it, `hydrate` runs, and `reconcileCrewsWithRoster` runs over its rows like
any other draft. Anything written into an amendment payload is an input to the
next reconcile, not a final value -- which is exactly how a corrected row can
be un-corrected between filing the amendment and signing it.

The original is the immutable half. `FILED_LOG_DATA_IMMUTABLE` (409) refuses a
data write to a `submitted` log in both `create_logbook` and `update_logbook`,
and that is the guard that makes an amendment necessary in the first place.
None of that immutability extends to the child.

**WHY THE ROWS HAD NO MARKER.** `gate_sourced` and `activity_id` were both
introduced 2026-08-10 (U1 stepper rebuild); `num_workers_source` arrived
2026-08-27 (#250). A row seeded from the roster before then carries the
turnstile's count, the turnstile's men, and none of the three fields. It is
gate data wearing no label -- and "no label" was being read as "the CP". That
also retires the separately-logged `activity_id` mystery: one old row shape,
missing two fields introduced the same day, for one reason.

## THERE IS NO HOLD. MERGING IS SHIPPING, ON BOTH HALVES.

**Standing fact, established twice in one day (2026-08-31).**

  * **Any merge touching `frontend/**` publishes an OTA immediately.**
    `.github/workflows/ota-update.yml` triggers on `push` to `main` for
    `frontend/app/**`, `frontend/src/**`, `frontend/App.js`, `frontend/app.json`,
    `frontend/app.config.js`, `frontend/package.json`. It lands on the
    `production` EAS branch, which is the one every store install listens on.
  * **Any merge at all deploys the backend.** Railway auto-deploys from `main`.
    A docs-only commit redeploys the API.

**IF A HOLD IS EVER NEEDED, THE BRANCH DOES NOT GET MERGED.** There is no
step between merge and release to intervene at. Not the OTA workflow, not
Railway, not CI.

**HOW IT WAS LEARNED, both times the same shape.** #294's client-version floor
was merged and deployed straight into a boot crash-loop. Later the same day,
#322's photo fix was merged while its OTA was explicitly held for evidence
reasons -- the merge published it at 20:10:15 and the hold was announced
afterwards, twice, by an agent that had not checked whether a hold was
available. No damage: the record was `submitted`, so
`FILED_LOG_DATA_IMMUTABLE` refused the write the backfill would have needed,
and the evidence was read from Mongo rather than the app. That was luck.

**WHAT TO SAY INSTEAD OF "I WILL HOLD THE OTA".** "This stays unmerged until
X." Anything else is a claim about a control that does not exist.

## RESOLVED — rows with no `activity_id` were a pre-2026-08-10 row shape

**RESOLVED 2026-08-31.** `gate_sourced` and `activity_id` were BOTH
introduced on 2026-08-10 in the U1 stepper rebuild. A row seeded from the
roster before that date has neither, which is exactly what C1-C4 showed --
one old row shape, not two separate losses, and not hand-typed rows at all.
The CP was right that he typed nothing. See "IS THERE A NUMBER" above for
what that misreading nearly cost. The AsyncStorage-draft hypothesis below
remains the likely carrier and is still unconfirmed.

**ORIGINAL ENTRY, KEPT BECAUSE FOUR EXPLANATIONS WERE WRONG BEFORE THIS ONE.** That
one was `reconcileCrewsWithRoster` short-circuiting hand-added rows before its
matcher, and it is fixed. The reconcile keys on `gate_sourced`, never on
`activity_id`, so this played no part in it.

**WHAT THE DOCUMENT SHOWS.** C1-C4, created 13:12, carry `crew_id`, `company`,
`num_workers`, a work description and photos -- and **no `activity_id`**.
C5-C8, appended by the gate, carry `act_1788191515625_1..4`.

**WHY THAT SHOULD BE IMPOSSIBLE.** `activity_id` has exactly ONE writer:
`EMPTY_ACTIVITY()` in `dailyJobsiteModel.js`, since `f49ddb5` (2026-08-10). All
three creation paths spread it -- `addActivity`, `commitAddCrew`,
`buildCrewsFromRoster` (both branches). Every transform preserves it:
`reconcileCrewsWithRoster` spreads `...row` in both merge branches and
`{...f}` in the append tail; `payloadActivities` spreads `...act`; `draftBody`
passes activities through; `create_logbook` stores `data.data` verbatim and
`_remember_other_activities` only reads. **Nothing backfills, and nothing
strips.**

**WHAT NARROWS IT.** `commitAddCrew` sets `gate_sourced: false` EXPLICITLY,
while `addActivity` spreads `EMPTY_ACTIVITY()`, which never mentions the field.
C1-C4 have the field ABSENT rather than false, which points at the Add-Crew
button rather than the modal. That path spreads `EMPTY_ACTIVITY()` too, so it
should still mint an id. **It does not resolve the contradiction.**

**THE HYPOTHESIS, LABELLED AS ONE.** The draft these rows came from was written
to AsyncStorage by a build older than 2026-08-10 and has sat there since;
updating the app does not rewrite existing drafts, and nothing backfills. That
would produce id-less rows on current JS with no stale bundle anywhere, which
matches the operator confirming every device is on the latest build. **It is
unverified.** Four earlier explanations for this were each contradicted by the
next query, so treat it as a lead and not an answer.

**WHAT IT COSTS TODAY.** Only the R2 key shape. A row with no `activity_id`
uploads its photos under `logbook-photos/{project}/{photo_id}/...` through the
`activityId || photoId` fallback in `logbookDrafts.js` -- addressable, resolves
forever, but the activity grouping is lost and one document ends up carrying
two key shapes. That is the documented coexistence (server.py:158), not
corruption.

**DO NOT "FIX" THE FALLBACK.** It is what keeps those eleven photos
addressable. The defect is upstream, in whatever produces a row without an id.

**AND NOTE THE BACKFILL HIDES IT.** `withActivityIds` in
`app/logbooks/daily_jobsite.jsx` mints an id for any loaded row lacking one, so
once that bundle is on the phones these rows stop being distinguishable from
normal ones. Anyone returning to this needs a document filed BEFORE that
shipped, or a device that has not updated.

## `serialize_id` MUTATES ITS ARGUMENT, and reads like a pure function

**This is the hazard. The 2026-08-31 outage was one instance of it.**

```python
def serialize_id(obj):
    if obj and '_id' in obj:
        obj['id'] = str(obj['_id'])
        del obj['_id']          # <-- the caller's dict
    ...
    return obj                  # <-- the SAME object
```

It takes a document, deletes a key from it, and returns it. At the call site,
`user_data = serialize_id(user)` looks like a conversion producing a new value.
It is not. `user_data is user`, and **`user["_id"]` raises KeyError from that
line onward.**

**WHAT IT COST.** `get_current_user` read `user["_id"]` eleven lines after
calling it. Every authenticated request returned 500 for any install sending
`X-Client-Version` -- the whole product, not one endpoint -- and it ran for a
day behind three green signals.

**THE REPAIR THAT WOULD HAVE BEEN WORSE, and the one that was made.** Swapping
in `user_data["id"]` -- the string the helper just produced -- stops the crash
and then silently never writes, because `_record_client_version` filters
`{"_id": user_id}` with no `to_query_id` and a string never matches an
ObjectId. The fix captures the ObjectId BEFORE the call
(`user_oid = user.get("_id")`) and `test_client_version_stamp.py` asserts the
TYPE for exactly that reason.

**THE MEASURED BLAST RADIUS**, by AST over `backend/` -- 49 `serialize_id(<name>)`
call sites:

  * **1 CRITICAL, NOW FIXED:** `list_cs_registrations()` --
    `serialize_id(reg)`, then `"_id": {"$ne": reg["_id"]}` eleven lines later.
    Guaranteed KeyError, gated behind `if reg.get("is_active")`, so it worked
    until the first active registration existed and then 500'd
    `GET /api/admin/cs-registrations` for the whole company. **It was live in
    production the entire time** and predates the client-version outage that
    surfaced the pattern. Fixed alongside it because two deploys for one defect
    class is worse than one wider PR. The audit above now reports 0 critical.
  * **19 SUSPECT reads across 8 call sites** -- `get_current_user` (device
    branch), `get_site_devices`, `get_site_device`, `get_flagged_project_checkins`,
    `get_checklists`, `get_checklist`, `finalize_logbook`,
    `list_cs_registrations`. All read keys `serialize_id` does not delete
    (`project_id`, `created_by`, `log_type`), so they work today. They are
    reading a document a previous line silently rewrote.

**THE SECOND-ORDER HAZARD NOBODY HAS HIT YET.** `serialize_id` also rewrites
every naive datetime to tz-aware in place. A value read from the document
*after* the call is aware; the same value read *before* is naive. Comparing one
to the other raises `TypeError: can't subtract offset-naive and offset-aware
datetimes`. `finalize_logbook` reads `.get("date")` after the call.

**WHAT TO DO.** Do not rename or "fix" the helper in place -- 49 call sites
depend on the mutation, and several read `id` off the object they passed in. The
safe shape is a non-mutating sibling (`serialised(obj)` returning a copy) and
migration site by site. Until then: **capture anything you need off a document
BEFORE handing it to `serialize_id`.**

## NO TEST SENDS `X-Client-Version`, so the suite is blind to that branch

**The CI gap that let the above run for a day.**

`get_current_user` stamps which client build is calling, guarded by

```python
reported = (request.headers.get("x-client-version") or "").strip()[:32]
if reported and _client_version_needs_stamp(user, reported):
```

Send the header and the branch runs. Omit it and nothing does. **Every test in
the suite omitted it**, so 4658 tests passed green while the branch they never
entered raised KeyError on every authenticated request in production.

`frontend/src/utils/api.js:92` sets the header on EVERY request, from
`Constants.expoConfig?.version` (`api.js:8`). So the split is per-install, not
per-account: a build that reports a version 500s on everything, a build that
does not works fine. That is why two accounts behaved differently on one
backend, and why Atlas showed nothing wrong with either.

**`test_client_version_stamp.py` now asserts BOTH halves** -- header present and
header absent -- because a test covering only one of them is what already
existed and it proved nothing.

**THE GENERAL RULE.** A request header that gates a code path is an input like
any other. If a branch is reachable only with a header set, a test must set it.
Grep for `request.headers.get(` before trusting a green suite: each one is a
branch the default test client does not take.

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

## The shared-device password path is CLOSED, not deferred

**WITHDRAWN FROM THE ROADMAP 2026-08-31. It will not be built.**

The idea was a per-project password on the shared site device, signing AS the
superintendent named on the project record -- a convenience door into his own
log rather than an anonymous kiosk entry.

**Two independent readings rejected it**, and the reason is not a preference:

  * it authenticates a DEVICE SESSION and then attributes the signature to a
    NAMED PERSON. Those are two different things by construction, and nothing
    in the record would distinguish a superintendent who signed on his own
    account from one signed for by whoever was holding the tablet;
  * Bulletin 2024-007 sec V.7 requires that "individuals who sign electronic
    records must be verified";
  * and the document is signed under a **DOB licence**. A signature that cannot
    be tied to the licensee is the one thing this log cannot afford.

**DO NOT REVIVE IT AS A "CONVENIENCE MODE".** The convenience it buys is not
having to log in on a tablet; the cost is a licensed signature nobody can
attribute. The superintendent signs on his own account -- `role:
"superintendent"`, shipped `ad4625b` -- on the site device or his own phone.

Recorded here as well as in docs/compliance/esra-bb2024-007-compliance.md,
because a roadmap item removed for a legal reason will otherwise come back as a
usability suggestion.

## The CS log's editor MUST send `superintendent_sign`

**NOTHING EMITS IT TODAY. This note has to survive until the editor is built.**

`deriveActingCapacity` (frontend/src/utils/signatureAudit.js) keys on the EVENT
TYPE first and the role only as a fallback:

```js
if (eventType === 'superintendent_sign') return 'Construction Superintendent';
if (eventType === 'cp_sign')             return 'Competent Person';
if (signerRole === 'superintendent')     return 'Construction Superintendent';
```

That design is what lets ONE ACCOUNT sign two statutory records in two
capacities -- the daily jobsite log as Competent Person, the BC 3301.13.13 log as
Construction Superintendent -- with one `user_id` and a ledger that says which
was which. It is better evidence than two accounts, which would put two ids on
one man with nothing saying they are the same person.

**THE TRAP.** `preshift_signin.jsx` and `osha_log.jsx` both send
`eventType: 'cp_sign'`. The CS log's editor does not exist yet, and whoever
builds it will start from one of those screens, because that is what every other
logbook editor did. **If it inherits `cp_sign`, the ledger records the
superintendent log as signed by a Competent Person.**

The `acting_capacity` field exists specifically so that BC 3301.13.13's "signed
as Superintendent" is provable -- server.py's own comment on it says so. Inherit
the wrong event type and the field built to prove it asserts the opposite, on
the one document where the capacity is the point.

**IT FAILS SILENTLY.** Nothing errors. The signature is recorded, the hash is
computed, the document renders. Only the capacity is wrong, and it is wrong in a
field nobody reads until somebody needs it.

**WHAT TO DO WHEN THE EDITOR IS BUILT:**

  * send `eventType: 'superintendent_sign'`;
  * assert it in that editor's test, by name, against the string -- not by
    "a signature event is recorded";
  * and consider asserting the pairing centrally: a signature event whose
    `document_type` resolves to `site_superintendent_log` must not carry
    `acting_capacity: "Competent Person"`. That check does not exist and would
    catch the mistake wherever it is made.

**AND THE GATE, WHILE THIS IS OPEN.** The CS log's access check must ask "is
this user the registered CS for this project" -- `lib/logbook/cs_attribution.py`
answers it -- and never `role == "superintendent"`, which would lock out the
dual-capacity user this product's first customer actually is.

## `POST /signature-events/public` gets no attestation injection

**NOT A DEFECT TODAY. Recorded because that is exactly the state in which it
becomes one.**

`POST /signature-events` (authenticated) resolves the log type off the document
and injects the attestation server-side, so a CP's signature records the
sentence printed above it. **The public endpoint does none of that.** It takes
`content_snapshot` from the request body and stores it verbatim.

**That is correct for what uses it now.** Its callers are the NFC gate paths,
and the affirmation writes its own event with its own server-held wording
(`PRESHIFT_AFFIRMATION_TEXTS`). No attested document routes through it.

**WHAT WOULD REOPEN IT** — any one of these, and none is far-fetched:

  * **A worker signs a document that carries an attestation.** The pre-shift
    sheet's Signature column is the worker's own signature, and if a future
    change has him sign the SHEET rather than affirming a stored stroke, that
    signature is a public-endpoint event on an attested document.
  * **The site device signs anything.** It authenticates as a device, and if a
    site-device flow is ever routed through the public endpoint for
    convenience, every logbook signature it makes loses its attestation.
  * **A fourth log type gains an attestation** and is signed anywhere other
    than the CP's phone. Three of twelve carry one today; the number is
    recorded in test_attestation_capture.py precisely so a fourth is noticed.
  * **The superintendent log's alternate-signer work.** Item 8's competent
    person and item 9's incoming CS both need a signature from someone who is
    not the document's author, and the obvious cheap route is the endpoint
    that needs no auth.

**THE FAILURE MODE IS SILENCE.** Nothing errors. The event is written, the hash
is computed, the ledger looks complete -- and the snapshot simply has no
attestation key, which reads as `PREDATES_CAPTURE`: the state reserved for
events written before capture existed. A 2027 signature would be
indistinguishable from a 2026 one, and the marker that was built to be honest
about old records would be quietly lying about new ones.

**THE FIX, IF IT IS EVER NEEDED,** is the same three lines the authenticated
endpoint uses: resolve the log type from the document, call
`attach_attestation`, pass the result instead of the body's snapshot. It is not
built now because building it would mean a public, unauthenticated endpoint
reading `db.logbooks` on every gate check-in to answer a question nothing asks.

**THE CHEAP GUARD, ALSO NOT BUILT:** the public endpoint could REFUSE a
`document_type` of `"logbook"` outright. Nothing legitimate sends one today, so
the refusal would cost nothing and would turn all four scenarios above from a
silent gap into a loud one. That is probably the right shape when someone
returns to this.

## A search narrower than the claim it supported — third instance

**CORRECTED. `cs_registrations` already stamped `deactivated_at`, and a report
said it did not.**

The claim was: *"is_active is a current-state boolean and only the delete path
stamps a timestamp, so switching a registration off erases when it was on."*
On that basis a permanent `UNDETERMINED` was documented on a compliance record,
written into `cs_attribution.py`'s docstring, entered in this file as a gap, and
a field was proposed that already existed.

**THE MECHANISM, WHICH IS THE PART WORTH KEEPING.** The writers were INFERRED
from two things that happened to be open — the Pydantic model and the delete
endpoint — rather than ENUMERATED by grepping the field. `grep -n '"is_active"'`
returns matches across the whole file, most of them `site_devices` and WhatsApp
config, so the answer looked thin and the inference filled the gap. Enumerating
the COLLECTION's writers instead —

    grep -n "db.cs_registrations.update_one\|...update_many\|...insert_one"

— returns exactly four lines and settles it in one read. **Two of the three
off-switches stamp `deactivated_at`:** supersession by a new CS (`:16014`) and
an admin setting `is_active` false (`:16165`). The third soft-deletes and
stamps `deleted_at` (`:16179`).

**SAME FAMILY AS TWO EARLIER MISSES:**

  * the `.cjs` sweep — one test file was run, the suite is a glob over every
    `*.test.cjs` under `src` and `app`, and CI caught two label assertions the
    single-file run could not see;
  * the `--include` allow-list — a grep restricted to `*.py` and `*.jsx` used to
    support a claim about the whole repository.

**THE RULE: enumerate the writers of the THING, not the occurrences of the WORD.**
A collection has a countable set of writers and they can be listed. A field name
appears wherever anyone typed it, and a search over it is wide in the wrong
dimension — noisy enough to look exhaustive, narrow enough to miss the two lines
that mattered.

### Where it stands now

`attribute_signer` reads `deactivated_at`, so the historical question is
answerable in every case a live build can produce: deactivated before the log's
date means it was not active then; deactivated on or after it means it was, and
the log is attributed normally.

`UNDETERMINED` survives for ONE case: a row switched off before either stamper
existed, carrying `is_active: false` and no `deactivated_at`. The moment was
never written down and cannot be recovered. **That set cannot grow** — every
live path stamps.

`backend/scripts/audit_cs_registration_history.js` counts it, and lists the rows
rather than reporting only a number, so the set is known rather than estimated.


## TWO DIFFERENT JANUARIES, and they will be conflated

**Write this down once so nobody has to work it out twice.**

| | rule | status |
|---|---|---|
| **the one-job rule** | a CS may hold **one active job** | **already in effect.** `register_construction_superintendent` warns on a second active registration for the same licence and writes a `cs_one_job_conflict` alert at `severity: high`. Its comment says "eff. Jan 2026". |
| **the competent-person sunset** | **2027-01-01** — the competent person role ceases to exist to be designated | **not yet.** `COMPETENT_PERSON_SUNSET` in `lib/logbook/superintendent_log.py`; item 8 stops applying and item 9 becomes the live item. |

They are unrelated rules about different things, four months apart, and both
are "the January change" in conversation. The one-job rule constrains WHERE a
superintendent may be registered. The sunset changes WHO may be designated as
competent person -- after it, nobody, because the CS must be present during all
active work and absence is covered by an **alternate licensed superintendent**.

**The trap:** a reader in December who finds `cs_one_job_conflict` will
reasonably assume it implements "the January rule" and that the sunset is
handled. It does not and it is not.

### What the sunset needs and does not have

**THE ALTERNATE LICENSED SUPERINTENDENT IS NOT A PRODUCT CONCEPT YET.** From
2027-01-01 the CS must be on site during all active work, and cover is provided
by an alternate -- another licensed superintendent, not a competent person.

  * `cs_registrations` CAN hold two rows for one project; nothing forbids it.
  * But **the one-job conflict check would fire on the alternate**, because it
    matches on licence across projects and knows nothing about a project having
    a primary and a deputy.
  * And **the signing path has no notion of who is on duty.** `cs_attribution`
    reads ONE registration per project (`find_one`) and would report the
    alternate as `NOT_REGISTERED_CS` on the days he actually covered.

So on 2027-01-01 the honest state of the product is: the sunset is handled for
ITEM RENDERING (items 8 and 9 swap, date-driven) and NOT handled for STAFFING.

### And the same-person case

A licensed CS may act as competent person for general site operations provided
he holds the specific OSHA certification for any specialised hazard; 3301.13.12
does not prohibit it. So item 8 naming the superintendent himself is a
legitimate project state.

**Do not build that as a permanent toggle.** It is live for four months and
then describes a role that no longer exists. If it is built at all it gates on
`item_applies("competent_person", log_date)` so it disappears with the item it
belongs to.

## CS licence expiry is not stored

`CSRegistrationCreate` carries `license_number`, `nyc_id_email`, `sst_number`
and `phone`. **There is no expiry.** A superintendent whose DOB licence lapses
mid-job is invisible: nothing warns, nothing flags, and the 3301.13.13 logs he
signs afterwards carry a licence number that has stopped meaning what it says.

Adding it is small -- one field, one input, and the expiry-plausibility shape
`build_worker_certifications` already applies to SST cards. What it needs first
is a decision about what a lapse DOES: a warning on the admin screen is
obviously right; whether the superintendent log should say anything is the same
question as the attribution sentence and should be answered the same way -- state
the fact, never block the filing.

## ~~`cs_registrations` cannot answer "was this active on a past date"~~ — WRONG, see the correction above

`is_active` is a **current-state boolean**. `created_at`, `updated_at` and
`deleted_at` (on soft-delete) are the only timestamps. So of the four
historical questions `attribute_signer` faces:

    registered AFTER the log date        answerable (created_at)
    registered before, still active      answerable
    registered before, since DELETED     answerable (deleted_at)
    registered before, since merely
      DEACTIVATED                        NOT ANSWERABLE

Only the delete path stamps a time; switching `is_active` to False erases when
it was True. The fourth case reports `UNDETERMINED` rather than guessing, which
is honest but is a gap a `deactivated_at` field would close outright.

## The 14 local failures: 13 need a mongod, 1 was mine

Reported on 2026-08-28 as "14 pre-existing local failures, green in CI, so
environment-dependent". **That was half right, and the wrong half mattered.**

### 13 of 14 — no mongod on localhost:27017

`test_start_renewal_clicked.py`, `test_dob_confirmation_endpoint.py` and
`test_filing_jobs_admin.py` drive the real app through Starlette's `TestClient`
and reach the real Motor/PyMongo driver. With no mongod listening they fail
with:

```
pymongo.errors.ServerSelectionTimeoutError: localhost:27017:
  [WinError 10061] No connection could be made ... Timeout: 30s
```

CI supplies a Mongo service container, so they pass there. Genuinely
environment-dependent, fully explained, and fixed by running a local mongod
(or a container) rather than by changing anything in the repo. The 30s
server-selection timeout on each is also why a local full-suite run takes ~4
minutes.

### 1 of 14 — `test_absence_literals_are_specific` was NOT environmental

**It was a new test file added in the same working tree, and it failed in CI
too.** The ratchet flagged `assertNotIn("3301", t)` in
`test_preshift_purpose_line.py`: a bare substring ban is satisfied -- or broken
-- by anything that happens to contain it. Correct catch. Fixed by folding the
section number into the already-anchored regex as `\b3301\b`.

Run against `main` with that one file moved aside, the ratchet is **6 passed**.
It runs green locally and always did.

### THE ACTUAL DEFECT WAS THE CONTROL METHOD

The claim "byte-identical with changes reverted, therefore not mine" came from
`git stash push backend/server.py` -- **which reverts only server.py**. The new
test file was untracked-then-committed and stayed present in BOTH runs. The
ratchet scans test files. So it flagged the same new file before and after,
produced identical output, and the identity was read as proof of innocence when
it was proof of nothing.

**A control run must revert EVERY file the change touches, not the one the fix
lives in.** For a change that adds a file, "stash the edited module" is not a
baseline -- check out the merge-base into a worktree, or move the added files
aside, and confirm the baseline is the count you expect rather than merely
unchanged. An unchanged number across a control is only meaningful if the
control actually changed something.

This is the same shape as the three text-search assertions that matched their
own prose: a check that cannot distinguish the thing being tested from the
tester. Here it was the control rather than the assertion.

### Why it is worth keeping the 13 runnable locally

A ratchet that only runs green in CI cannot be used to check your own work
before pushing, which is exactly when it is worth the most -- and this entry
exists because a ratchet's local result was misread rather than because it was
unavailable. The ratchet itself is fine locally. The 13 are not, and until a
local mongod is standard, `pytest backend/tests -q --ignore` of those three
files is the honest local run; anything wider reports 13 failures that mean
nothing about the change under test.

## After any direct push to main, run CI against main

**THE RULE: a direct push to `main` skips CI. Run it against `main` afterwards.
Three minutes.**

On 2026-08-29 production was 502ing on every path and the fix was pushed
straight to `main` to restore service. **That push was correct.** Opening a PR
and waiting for eight checks while the product is down is the wrong trade.

The blind spot is what came next: **nothing ran CI against `main` afterwards,
and `main` stayed red for a day with nobody knowing.** Two tests were broken by
that push and both would have been caught on the way in:

  * `test_absence_literals_are_specific` — the outage fix added
    `assertNotIn("_read_client_minimum_supported", SRC)`, a bare literal the
    ratchet forbids. It is a genuine whole-symbol ban, so it is now
    `_BARE_BY_DESIGN`; the point is that nothing told anyone for a day.
  * `clientVersion.test.cjs` — asserted "the server derives the floor from
    app.json", which is precisely the behaviour that crash-looped production.
    Inverted.

Both surfaced only because an unrelated PR ran the full suites two days later.

**The emergency push is not the thing to fix.** Restoring service first is
right, and a process that made that slower would be worse than the gap it
closed. What is missing is the three minutes afterwards:

    gh workflow run tests.yml --ref main     # or push an empty commit / re-run

Anything that makes CI evaluate `main` as it now stands. A red `main` that
nobody has looked at is worse than a red PR, because a PR is looked at by
definition and `main` is assumed.

## `git checkout -b` from wherever you are standing

**TWICE IN TWO DAYS, and the first one cost real time during an outage.**

A branch cut from the current branch rather than from `main` carries that
branch's commits. When it merges, its PR delivers the OTHER PR's content too,
and the other PR's squash commit is then **empty**.

  * **#294** (`client-version-floor`) merged as `e801846`, **zero files**. Its
    content had already arrived inside `b5aabe9` (#295), which was branched on
    top of it. So during the outage `git revert e801846` did nothing, and
    reverting #295 would have taken out the detector-scope fix and the 285
    correction pass. The revert had to be done by hand under time pressure —
    **which is the cost of this mistake, and it is not small.**
  * **#306** and **#307** were both absorbed by **#308** the same way. Caught
    before merging this time; both closed after verifying with
    `git hash-object` that `main` carried the files byte-identically.

**THE RULE: always branch from an updated `main`.**

    git checkout main && git pull && git checkout -b <name>

Never `git checkout -b` from a feature branch unless the dependency is
deliberate and stated in the PR body.

**And the tell, which is cheap to check before opening a PR:**

    git log --oneline main..HEAD

If that lists commits belonging to another PR, this branch will swallow it.

## One review slot, and a row can hold two findings

**NOT BUILT. Held pending a production count; recorded now so it survives the
session that found it.**

A certification carries ONE `review_reason`. A row with two problems shows one.

**THE COLLISION PREDATES `CARD_NUMBER_FORMAT`.** `EXPIRY_IMPLAUSIBLE` and
`DUPLICATE_SST` have always raced: `build_worker_certifications` assigns
`review_reason` as a scalar in several branches, and whichever is computed last
wins. This is not new. It is newly *visible*, because `CARD_NUMBER_FORMAT` is
the first finding that is EVALUATED rather than stored, and so visibly loses a
race it never entered.

**THE LOSER LEAVES NO TRACE, AND NO QUERY CAN PROVE IT HAPPENED.** Only the
surviving reason is stored. A tally of `review_reason` shows what won, never
what it beat. Anyone who reports "we checked and it has not happened" has
misread what the data can say.

What the data CAN show is EXPOSURE, and that is what the pending count is for:

  * `needs_review` true far more often than `review_reason` is non-empty means
    rows were flagged with the reason lost entirely.
  * two reasons appearing in comparable volume means collisions are likely
    rather than merely possible.

**THE DECISION RULE, agreed before the numbers came back so the numbers cannot
be read to suit a preference:** if the proportion is small, this is a real
defect with almost no live surface and it stays in this file. If it is not, it
becomes a PR.

### The shape, if it is built — ADDITIVE, NOT A MIGRATION

Return `findings: [...]` **alongside** the existing scalar `review_reason`,
which keeps its current meaning: the highest-ranked finding. Both
`get_worker_certifications` and `osha_review_index` gain the list.

  * Nothing STORED changes shape.
  * Every existing reader keeps working untouched, because the scalar is still
    there and still means what it meant.
  * New readers get the list. The register's Review cell can then show
    `⚠ Class unverified · Unexpected card format` instead of silently dropping
    one.
  * Precedence still decides the SCALAR, so `card_number_finding`'s rule --
    a claim about the CREDENTIAL outranks a claim about DATA ENTRY -- is
    unchanged and still the thing that picks what a one-slot reader sees.

**DO NOT MAKE `review_reason` A LIST.** Every reader assumes a scalar today:
the register's `OSHA_REVIEW_LABELS` lookup, the CP screen's
`CERT_REVIEW_REASON` map, the i18n `reason_*` keys, and
`build_worker_certifications`'s own comparisons. That is a migration across
stored documents and four readers, not a fix, and the additive shape gets the
whole benefit without it.

The cost of the additive shape, stated so it is not discovered later: two
representations coexist and someone eventually has to retire the scalar. That
is a smaller debt than a migration, and it can be paid when there is a reason
to.

## Template insertion, if a count ever has to be IN the AI sentence

**NOT BUILT. Written down so nobody reaches for vocabulary again.**

Numbers were removed from `allowed_vocabulary` because the check is **token
membership** and membership cannot say which fact a number states. With
`worker_count` 6 and `photo_count` 4 both admitted, this verified:

    "4 workers continuing formwork and rebar on the 3rd floor"

Wrong headcount, on a report read by a lender, passed by the checker.

**Do not solve this by adding numbers back, in digits or in words.** Every
version of that idea widens the same hole:

  * admitting `str(worker_count)` is what produced the transposition;
  * admitting number-WORDS ("six" beside "6") doubles the surface rather than
    closing it, because both spellings of both counts become legal tokens;
  * admitting only the ONE count that appears is still membership — a sentence
    can use a legal token to state the wrong fact, and a verifier that checks
    presence cannot check reference.

**THE RIGHT SHAPE IS TEMPLATE INSERTION.** The code writes the number; the
model writes the rest.

    line = f"{worker_count} workers " + model_clause

The count is then guaranteed BY CONSTRUCTION rather than checked by membership,
and the verifier's job stays what it is good at — refusing untraceable nouns in
the clause the model actually wrote.

**IT ALREADY WORKS, on the one line that needed it.** `plain_facts` is exactly
this: written by code, from the payload, on a fixed order, and it cannot
transpose two numbers because it never chooses between them. That is why the
fallback may still state the headcount when the model may not, and why
`test_the_fallback_traces_entirely_EXCEPT_for_the_number_it_writes` asserts the
fallback is refused for a number and for nothing else.

**And it is not needed today.** The crew table already prints the headcount in
its own column, from the record. A sentence that restates it adds nothing and
risks contradicting the column beside it — which is the shape of half the
defects in this file.

## The Review column on the per-logbook PDF: a flagged cert is invisible there

**NOT BUILT. Scope decision, recorded so it is not carried in someone's head.**

`generate_combined_report` renders the OSHA register with seven columns
including `Review`, joined against the worker's LIVE certifications.
`generate_single_logbook_html` renders **six** — no Review — with a deliberate
comment:

> that renderer adds a Review column by joining each row back to the worker's
> LIVE certifications. That is a database read, not a payload key, and this
> function renders one stored document.

**Consequence:** a cert flagged `CLASS_UNVERIFIED` shows ⚠ on the emailed
investor report and is **invisible on the PDF an inspector asks for by name.**

The reasoning was honest when written, and #296 has since settled the principle
the other way: live state may be overlaid on a filed document **when the
document says it is doing so**, resolved against the document's own date, with
the resolution visible on its face (the pre-shift sheet prints "Affirmed 11:13"
for exactly this reason).

Applying that here means the per-logbook PDF gains the Review column and the
`OSHA_LOG_ATTESTATION` gains a clause naming the overlay. Not done in the
three-state PR because it changes which columns a filed document has, which is
a bigger decision than fixing what one column says.

## Provenance on the OSHA register

**NOT BUILT. Recorded as its own item.**

`ENTRY_KEYS` is `worker_id, worker_name, company, certification_type,
card_number, expiration, signed, date`. **There is no provenance field**, so a
certification captured at the gate and one the CP typed by hand are
byte-identical on the filed register.

`toolbox_talk` solves exactly this with `added_from`, and its own comment
explains why it is worth the field:

> a signed attendance record that renders the two identically is the stronger
> one lending its authority to the weaker

The same argument applies with more force here, because the weaker claim is a
CP typing a card number from memory and the stronger is a card read at the gate.

`OSHA_LOG_ATTESTATION` currently states the gap on the document's face — "this
document does not distinguish which" — which is honest but is a workaround.
The fix is one field on the entry, one write at each of the two creation paths,
and a column; and, like `added_from`, **rows filed before the field existed must
read as unknown rather than being assigned a provenance nobody recorded.**

## generate_combined_report still reads db.daily_logs

**NOT BUILT. Found while working the Review column; recorded rather than
folded in.**

#299 fixed `get_report_preview`. The **emailed report** still opens with:

```python
daily_log = await db.daily_logs.find_one({...})
```

and the entire `Site Superintendent Log` section hangs off it — weather,
subcontractor activity, safety checklist, corrective actions, incident log,
work performed, and TWO signatures (superintendent and competent person).
`daily_log` is always `None`, so **that section never renders at all.**

**Lower severity than the preview panel, and the difference matters.** The
preview PRINTED `0` as a fact. Here nothing prints: the report simply has no
Site Superintendent Log section, and no false statement is made. It is an
unreachable branch, not a lie.

Two things to decide before touching it, and neither is obvious:

  1. **Does that section duplicate `Daily Jobsite Log (NYC DOB 3301-02)`,**
     which the same report already renders from the CP's filed logbook? If it
     does, the fix is to delete the dead section, not to feed it.
  2. **The two signatures have no source in the logbook world.**
     `superintendent_signature` and `competent_person_signature` are
     daily_logs-only fields; `as_daily_log_row` does not project them and could
     not. Pointing the section at daily_jobsite would render a signature block
     with nothing in it, which is worse than the section being absent.

## When a filed sheet needs a purpose line, and which kind

**THE TEST.** A filed sheet is self-describing when it prints the QUESTION next
to the ANSWER, or prose under a heading that names it. A reader who was not
there can then work out what the signature attests from the document alone.

All twelve types were surveyed against it on 2026-08-28. **Nine pass**, and for
one structural reason: they are checklists or narratives, so the check is on
the page.

| sheet | what carries the claim |
|---|---|
| `daily_jobsite` | narrative under named headings; §3301.2 in the title |
| `toolbox_talk` | `Topics:`; columns state who marked what (`Present` = CP, `Confirmed` = worker, `Added by`) |
| `subcontractor_orientation` | `Conducted By (CP)` + `Orientation Date` + `Worker Signature` |
| `hot_work` | "Permit"; `Precaution \| Confirmed`, precautions printed |
| `crane_operations` | `Item \| Confirmed`, items printed; `Lift Log` |
| `concrete_operations` | `Time \| Slump \| Result`; `Item \| Confirmed` |
| `excavation_monitoring` | `Baseline \| Current \| Movement (Δ)` — a stated comparison |
| `scaffold_maintenance` | `Question \| Answer`, questions printed |
| `ssc_daily_safety_log` | `Item \| Status` + named narrative headings |

`fall_protection` is the tenth: self-describing per row AND already carrying an
explicit line.

**TWO FAIL.**

  * **`preshift_signin`** — the only sheet in the twelve that prints an ANSWER
    WITHOUT ITS QUESTION. `Injury` and `PPE` are bare nouns over Yes/No; the
    questions actually asked ("Injury / Incident last time?", "Inspected PPE
    today?") live in `preshift_signin.jsx` and never reached the paper. Fixed:
    `PRESHIFT_ATTESTATION`.
  * **`osha_log`** — a signature over OTHER PEOPLE'S CREDENTIALS with no
    statement of what it covers. Whether the CP sighted each card, took the
    worker's word, or copied a prior record are three materially different
    claims under one signature. Lands with finding 4, in the PR that decides
    the `Review` column's wording, so that sheet gets one coherent pass.

## SCOPE vs ATTESTATION — the next person adding one needs to know which

Same mechanism, different sentence, **different placement**, and the placement
is not decoration.

  * **SCOPE** says what the log is NOT. `FALL_PROTECTION_NOTICE` — *"...is not
    a DOB or OSHA filing."* It goes **BELOW** the signature, as a footer
    qualifying a document the reader has already read.
  * **ATTESTATION** says what the signature CLAIMS. `PRESHIFT_ATTESTATION`. It
    goes **ABOVE** the signature, because a signer must see the claim before
    making it and a reader must know it before weighing the name underneath.

Both placements are asserted in both directions in
`test_preshift_purpose_line.py`, so neither drifts into the other's position.

**AN ATTESTATION MAY NAME ONLY QUESTIONS, NEVER ANSWERS**, unless the server
enforces the answer. The pre-shift draft first read "confirmed they inspected
their PPE", which is false on any row answered No — and `inspected_ppe` is a
three-state field whose whole point is that No is a legitimate answer. Worse,
the comment justifying that draft cited a server constant,
`SUBMIT_INCOMPLETE_WORKER_ANSWERS`, **that does not exist anywhere in the
repo**. The two-answer requirement is enforced by `answeredBoth` in
`preshift_signin.jsx` and by nothing on the server; `create_logbook` gates an
immediate submit on a CP signature, content and trade detail, and never reads
either answer field. A sheet filed by any other caller can carry nulls and
renders an em-dash. So the sentence says the answers *"appear in"* those
columns — true of a row that shows none — rather than that they were given.

Write the claim the code enforces, at the level the code enforces it, and check
which end enforces it before naming one.

## What the read-without-writer sweep does NOT see

#290 is a ratchet over **Mongo query filters**: it walks `db.<collection>.find`
and friends, pulls the literal keys out of the filter argument, and reports
fields read on a collection and never written to it.

**Five instances of read-a-field-nobody-writes surfaced on 2026-08-28. The
sweep would have caught two.**

| instance | seen? | why |
|---|---|---|
| `daily_logs.phase` (4 engines) | **yes** | a filter key: `{"phase": {"$nin": [None, ""]}}` |
| `dropbox_enabled` | **yes** | a filter key |
| `checklist_title` | no | it IS written — once, at creation, then goes stale. A different defect |
| `daily_logs` itself | no | the collection is written; the writer is simply idle since April |
| `signature_affirmed` on a filed pre-shift sheet | **no** | a `.get()` on a stored sub-document, not a query filter |

The last one is the sharpest miss and the reason this entry exists. The
pre-shift sheet's signature column read `w.get("signature_affirmed")` off a
worker row inside `logbooks.data.workers[]`, and `preshift_signin.jsx` has
never written that key. Every filed sheet printed NOT AFFIRMED against every
worker, for as long as the column has existed. Nothing about that read is a
query, so nothing about it is visible to a pass that scans queries.

**DO NOT WIDEN THE SWEEP TO CHASE IT.** A pass that tried to resolve
`.get("x")` calls against the shapes stored in a schemaless collection would
have to model what each document *should* contain, which is the thing Mongo
declines to know. It would report a large number of `.get()`s on optional keys
that are absent for good reasons, and a ratchet that cries wolf gets its
baseline padded until it means nothing — the failure the Resend boot check
already demonstrates elsewhere in this file.

What would actually catch the sub-document class is a different check with a
different shape, and it is worth naming rather than pretending the existing one
can grow into it:

  * **a stored-shape contract.** For the document types that are rendered onto
    a compliance record, assert that every key the renderer reads is a key the
    writer writes. That is per-document-type, needs both ends named, and is
    only worth building where the document is customer-facing.
  * **a render-time absence counter.** Cheaper and blunter: when a renderer
    falls to its "missing" branch for EVERY row of a document, say so. A
    column that is unanimous is usually a field, not a finding.

Neither is written. The sweep's limits are recorded here so the next person
reading its 33-row baseline knows what its silence does and does not mean.

## A stale bundle looked exactly like a server fault for a day

RESOLVED 2026-08-28 by clearing app data on the operator's phone. The log now
renders correctly — read-only, with Amend.

**The cause.** That device was running a JS bundle older than `2b157f6`
(2026-07-29), which unwraps the paginated `{items: [...]}` envelope in
`logbooksAPI.getByProject`. Without it the wrapper object reaches the editor,
`Array.isArray` fails, `arr` is `[]`, `existing` is null, `locked` stays false,
and the `else` branch rebuilds crews from the roster and fetches fresh weather.
Every symptom follows from that one line, including the two that made no sense
together: an editable form on a submitted row, and a screen that was empty of
saved content while full of roster content. The api.js comment for that fix had
already described it — *"the raw wrapper made existing=null, so they reopened
blank"* — a month before this happened.

**Nothing was wrong on the server.** The query was correct, authorization was
correct, the company scope was correct, the date was correct, the field types
matched, and the row was there the whole time.

### Read the bundle id first

Six source traces were built before anyone read it: the read path, the company
scope, `require_project_access`, the date normalisation, a BSON type mismatch,
and a missing `log_type` parameter. Each was a plausible reading of the source.
All six were about a system nobody could observe, and five of them were
disproved by a production query that took under a minute.

`BuildMarker` renders the running bundle id and its build time, selectable, at
the bottom of the CP logbook list — the screen the operator was standing on.
`app/settings.jsx` shows the same thing. **It existed the whole time and was
never captured.**

THE RULE, and it is cheap enough to have no exception: **when a screen
misbehaves on one device and not another, read the bundle id on both before
reading any source.** A stale bundle is indistinguishable from a server fault
from the outside, and it is the one hypothesis that source cannot rule out — the
code in front of you is not the code that ran. Everything else in this
investigation was answerable from a mongosh query or an access log; only this
was not.

The second-cheapest artifact was the access log, which is already on: the
Procfile runs uvicorn with no `--no-access-log`, so every request is logged with
its full path and query string. That, too, went unread for a day.

### A draft that shadows a failed read hides the failure permanently

The first visit rendered the blank form and the autosave wrote a local draft
800ms later — no tap required, because `locked` was false. From then on the
draft branch returned **before the server was ever asked**, so the fetch that
caused the problem could not be re-observed on that device. The condition
self-masked on every retry, including retries after the device had updated.

That is a general property of local-first loading and it is worth naming: a
draft written by a failed load looks exactly like a draft written by real work,
and it will keep answering in place of the read that failed. It also survives
sign-out — `clearAuth()` removes the token and the stored user, not drafts —
which is why clearing app data was what finally moved it.

Two consequences worth weighing separately, neither fixed here:

  * the editor cannot distinguish "no log exists" from "the response was a
    shape I did not understand". #285 made a FAILED read fail closed; a
    successful read of an unparseable body still lands in the same `else`
    branch as a genuinely unfiled day.
  * there is no in-app way to discard a draft. `discardFinalizedDraft` is a
    plain `AsyncStorage.removeItem` but its only caller is the amendment path,
    guarded on server confirmation. Clearing app data is the only route, and it
    takes every other draft on the device with it.

### What keeps a phone on an old bundle

Four mechanisms, and the first is silent by design:

  1. **The runtimeVersion cutoff.** `app.json` sets
     `runtimeVersion: {policy: "appVersion"}` and `version: 1.3.0`. A device
     whose NATIVE build is 1.2.x receives no 1.3.x update, ever, and is told
     nothing. It sits on its last compatible bundle until someone installs a new
     binary from the store. This is the policy working as designed, and it is
     the most likely explanation for a device months behind.
  2. **The app is never cold-started.** expo-updates defaults to
     `checkAutomatically: ON_LOAD` — the check happens at launch. A phone that
     is backgrounded and resumed for weeks never launches, so it never checks. A
     site phone lives exactly like this.
  3. **Apply-on-next-launch.** `fallbackToCacheTimeout: 3000` means the launch
     waits 3s for a new bundle, then boots the cached one and downloads in the
     background. The new bundle applies on the NEXT cold start, so moving one
     version takes two launches.
  4. **A failed download.** The 3s budget on site connectivity means the check
     often loses, and nothing retries until the next launch.

Nothing in the app calls `Updates.checkForUpdateAsync` or `fetchUpdateAsync`,
and neither `BuildMarker` nor the settings screen compares what it is running
to what is published — they report an id, not a verdict. **The app cannot
currently tell anyone it is behind.** What it would cost to change that, and
why the obvious version does not catch this case, is in the reply that
accompanied this entry.

## A fix for "the CP is told the wrong thing" shipped telling him the wrong thing

The sharpest instance of the family so far, and the one worth reading twice.

**The convention.** The server names a condition with a machine code and no
prose; the client owns the wording. `finalizeErrorCode` extracts the code,
`gateCopy` maps it to a sentence, and an unmapped code falls back to a generic
one. Two sides, and they only work as a pair.

**What happened.** #214 added `FILED_LOG_DATA_IMMUTABLE` and deliberately did
not give it the `SUBMIT_` prefix — its comment says why, in as many words:
*"this is not a submit gate, it fires on any data write to a filed log"*. That
reasoning was right. But `GATE_CODE` on the client was
`/^(?:FINALIZE|SUBMIT)_[A-Z_]+$/`, and nothing widened it. So:

    finalizeErrorCode(the 409)  ->  null
    gateCopy(null)              ->  "This log could not be finalized.
                                     Please try again."

A CP was told to **RETRY** a write the server refuses every time, and the one
remedy that works — amend — was never named. For weeks, on the exact refusal
#214 existed to deliver.

**And then #285 made it worse in the most literal way.** That PR's whole subject
was a filed log being written over, and part of the fix was adding the missing
copy for this code. The copy was **unreachable from the moment it landed**: it
sat in `en.js` keyed on a code the extractor could never produce. A fix for
"the CP is told the wrong thing" shipped telling him the wrong thing. It was
found while building #286, not by anything that was watching.

**Fixed in #286** — `FILED` added to the prefix set. But the prefix is not the
lesson.

### The durable form

    every gate code the server emits is one the client can hear

`drainAlreadyFiled.test.cjs` asserts exactly that: for each logbook gate code,
that `server.py` still emits it AND that `finalizeErrorCode` returns it. **It
would have failed the day #214 landed.** Nothing else could have — the code was
correct, the copy was correct, the extractor was correct, and the three did not
meet anywhere a test was looking.

Deliberately scoped to the LOGBOOK gates. `ACTIVATION_REQUIRES_ADMIN`,
`ACTIVATION_STATE_REQUIRED` and `LOGBOOK_NOT_ACTIVATABLE` also fail the pattern
today; they belong to endpoints that do not route through this extractor, and
widening it to them would change behaviour on screens that module knows nothing
about. **If any of those three is ever surfaced through `gateCopy`, it needs
this same pairing test first, or it arrives silent in the same way.**

The general shape, which is what to carry: **a two-sided convention needs a test
that runs both sides against each other.** Either side alone reviews as correct.

## 22 test files were silently skipped on the dev machine

`@babel/core` is a declared dependency and CI installs it with `npm ci`. It was
absent from `frontend/node_modules` locally, and 22 of the JS test files need
it: the execution harnesses (`esmHarness.cjs`) and all three parse-only sweeps
(`find-bare-jsx-text`, `find-unbound-identifiers`, `find-unpinned-palette-keys`).

They did not fail. Run one and it dies on `Cannot find module '@babel/core'`;
run the suite the way a person does — a loop over the glob, eyes on the tail —
and a run that never executed **22 of them** reported success. The three sweeps
that catch a crash-on-open were among the missing.

Found by installing it (`npm install --no-save @babel/core`) mid-session, which
immediately caught a real breakage: `orientationTradeGate.test.cjs` pinned the
`GATE_CODE` regex TEXT and failed on the widening above. That would otherwise
have gone to CI as a red build on a PR whose diff looked unrelated to it.

**Same family as the two already recorded**: a local run that covers less than
it appears to and reports success. The `src/utils` glob missed the files that
sorted after a failing one; the `--include=*.js` sweep missed `.jsx` entirely.
Each time the gap was invisible *because the command exited 0*.

The workflow already carries this scar and says so — its `npm ci` step exists
because two tests "had never executed in CI even once" and "passed on
developers' machines purely because node_modules happened to exist there".
**The inverse is now on record: they fail on a developer's machine because it
does not.** A `README` line, a `predev` check, or a first-line guard in the test
runner that refuses to report success when a file could not be loaded — none of
which is written yet.

## Nine logbook editors still read `.catch(() => [])`

The daily jobsite editor's existing-log read was fixed in #285: a request that
never came back was handing an empty array to everything downstream, so
`existing` came out null, `locked` stayed false, and the screen rendered an
EDITABLE EMPTY FORM for a day that may already be filed. On a second device
that is what the operator saw on 2026-08-28, one tap from writing over the
record.

**Nine other editors still have it**, on the same read:

| screen | hydration |
|---|---|
| `preshift_signin.jsx` | `chooseEditableLog` — the identical shape |
| `toolbox_talk.jsx` | `chooseEditableLog` — the identical shape |
| `concrete_operations.jsx` | own |
| `crane_operations.jsx` | own |
| `excavation_monitoring.jsx` | own |
| `fall_protection.jsx` | own |
| `osha_log.jsx` | own |
| `scaffold_maintenance.jsx` | own |
| `ssc_daily_safety_log.jsx` | own |

`hot_work.jsx` and `subcontractor_orientation.jsx` already use `settleFetch`
and are not in this list. `logbooks/index.jsx` swallows the same way but is the
LIST screen, not an editor — an empty list there is a different claim and wants
its own decision.

**Where they land: the `unavailable` prop on `LogbookStepper`** (#285). It
takes `{title, body, retryLabel, onRetry}` and renders a read-only notice
instead of the steps — no fields, no footer, and deliberately no
`LogbookLockBar`, because "FINALIZED — read-only" plus an Amend button would be
a claim about a document the device could not read. The copy keys and the
`failureDetail()` composition are in `dailyJobsite`; a shared namespace would
be the first thing to sort out.

**The blast radius is not equal across the nine, and that is the argument for
doing them deliberately rather than in one sweep.** For the two END_OF_DAY
types the empty form could reach a filed row — that is the daily-jobsite
defect. For the seven IMMEDIATE types a filed row is `is_locked` on submit, so
the create path's dedupe excludes it and an empty re-entry mints a NEW instance
rather than overwriting: a duplicate record, visible and recoverable, not a
silent loss. Both are wrong; only one destroys.

Not fixed in #285 deliberately. Each needs its own copy, its own read of what
that form does with an empty payload, and its own control run.

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
