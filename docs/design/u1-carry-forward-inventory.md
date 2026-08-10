# U1 — carry-forward inventory (BEFORE layout)

Every row was read in the current working tree at `8bf621b`. Nothing here is
reported from the earlier `docs/plans/cp-rebuild-research.md`; where that
document and the code disagree, the code is recorded and the drift is noted.

Source unless stated: `frontend/app/logbooks/daily_jobsite.jsx` (1,924 lines).

## The three that must not regress

| # | Item | Today | Note |
|---|---|---|---|
| 1 | `persistPhoto` THROWS | `src/utils/logbookDrafts.js:50`; caught at `daily_jobsite.jsx:690` | The catch DROPS the photo from the row (`:699`) and tells the CP (`:701`). The throw is the offline guarantee. |
| 2 | Draft lifecycle | `logbookDrafts.js` — `draftKey:130`, `readDraft:136`, `writeDraft:165`, `setDraftBackendId:201`, `markFinalized:210`, `markPending:216`, `clearPending:227` | Autosave-per-step builds on these. `writeDraft` refuses content patches once finalized (`markFinalized` ordering matters — see `:1201`). |
| 3 | `compressUnderCap` | `src/utils/compressPhoto.js:25`; cap `MAX_BYTES = 150 * 1024` at `:21` | Sizes every R2 object and thumbnail. |

## The remaining 18

| # | Item | file:line |
|---|---|---|
| 4 | `MAX_PHOTOS_PER_SUBCONTRACTOR = 10` | `:74` |
| 5 | `photoBucketKey` | `:87` |
| 6 | `photosInBucket` | `:96` |
| 7 | `bucketRemaining` | `:106` |
| 8 | `activity_id` minting (`newActivityId`) | `:135`; used `:237`, `:522` |
| 9 | Roster id on rows (`subcontractor_id`) | `EMPTY_ACTIVITY:244`; seeded `:524`; re-resolved on company edit `:577-579`; map built `:463-477` |
| 10 | `isPurgedPhoto` | `:155` |
| 11 | `inlinePhotoData` | `:146` |
| 12 | `patchPhoto` | `:165` |
| 13 | `dropPhoto` | `:171` |
| 14 | `photoForPayload` | `:190` |
| 15 | R2 upload path + `upload_pending` | `uploadCapturePhoto` `logbookDrafts.js:283`, `uploadPendingActivityPhotos:331`, `photoNeedsUpload:271`, `hasPendingPhotoUploads:386`; driver effect `daily_jobsite.jsx:723-733`; marker set `:211`, `:719` |
| 16 | `gateCopy` | `:284` |
| 17 | `recordFinalizeError` + rejected banner | imported `:45`; called `:1302`; `clearFinalizeError` `:1254` |
| 18 | Address + weather auto-population (KEEP) | address `:456`; `fetchWeather` `:546`, called `:536` |
| 19 | Headcount-derived rows | `:510-533` off `logbooksAPI.getDailyHeadcount` `:451` |
| 20 | Signature client guard | `:1239-1242` |
| 21 | `persistActivityPhotos` | `logbookDrafts.js:82`; called `:387`, `:1021` |
| + | `CameraCaptureModal` / `useCameraPrewarmPermission` | imported `:25`; prewarm called `:345`; rendered `:1744` |
| + | `EMPTY_OBSERVATION` / `addObservation` / `updateObservation` | `:253`, `:997`, `:998` |
| + | `EQUIPMENT_ITEMS` / `CHECKLIST_ITEMS` / `WEATHER_OPTIONS` | `:214`, `:223`, `:213` |
| + | `removeActivityPhoto` / `addActivity` / `updateActivity` | `:936`, `:987`, `:566` |

Nothing in the list is un-carryable. Every item is either pure helper code
(4-14), a util import (2,3,15,21), or a constant (22) — none is coupled to the
current single-scroll layout.

## Corrections to the task brief

- `amend_logbook` is at **`backend/server.py:16250`**, not `:16146`. Route
  `POST /logbooks/{logbook_id}/amend`.
- Finding C's line is confirmed: `daily_jobsite.jsx:528` is
  `work_description: r.trade || ''`.
- The 12 chip hits in the current file ARE equipment/checklist toggles
  (`:1582-1610`), as stated. No activity-chip UI exists.

## AFTER — where each item now lives

`DJ` = `frontend/app/logbooks/daily_jobsite.jsx`,
`M` = `frontend/src/utils/dailyJobsiteModel.js` (new),
`LD` = `frontend/src/utils/logbookDrafts.js` (unchanged).

Nothing was dropped. Nothing needed to be.

| # | Item | Now at |
|---|---|---|
| 1 | `persistPhoto` THROWS | `LD:50`; caught + reported `DJ:806-816` |
| 2 | Draft lifecycle | `LD` unchanged; consumed `DJ:329` (`_key`), `:384` (`flushDraft`), `:404` (`fetchData`), `:897` (`persistAndPush`) |
| 3 | `compressUnderCap` | `compressPhoto.js:25`, cap `:21` — untouched; called `DJ:862` |
| 4-7 | Photo bucket (`MAX_PHOTOS_PER_SUBCONTRACTOR`, `photoBucketKey`, `photosInBucket`, `bucketRemaining`) | `DJ:108`, `:110`, `:119`, `:129` |
| 8 | `activity_id` minting | moved to `M:39-40`, used `M:52` |
| 9 | Roster id on rows | `M:55` (default null), `M:154` (seed bind), `M:238` (re-resolve on correction) |
| 10-14 | `isPurgedPhoto`, `inlinePhotoData`, `patchPhoto`, `dropPhoto`, `photoForPayload` | `DJ:151`, `:143`, `:159`, `:165`, `:181` |
| 15 | R2 upload + `upload_pending` | `DJ:770` (`uploadOneCapture`), `:824` (drain effect), `:930` (save-time sweep) |
| 16 | `gateCopy` | `DJ:262` |
| 17 | `recordFinalizeError` + banner | `DJ:1064`; `clearFinalizeError` `:1042` |
| 18 | Address + weather auto-population | `DJ:443` (address), `:450` + `:487` (weather) — **KEPT** |
| 19 | Headcount-derived rows | replaced by `M:113 buildCrewsFromRoster`, called `DJ:446`; `/daily-headcount` still supplies the roster ids via `M:178 rosterIdIndex` |
| 20 | Signature client guard | `DJ:1021` |
| 21 | `persistActivityPhotos` | `LD:82`; called `DJ:389`, `:411`, `:902` |
| + | `CameraCaptureModal` / prewarm | `DJ:1691`, prewarm `:322` |
| + | `EMPTY_OBSERVATION` / add / update | `M:83`, `DJ:524`, `:525` |
| + | `EQUIPMENT_ITEMS` / `CHECKLIST_ITEMS` / `WEATHER_OPTIONS` | `DJ:195`, `:204`, `:193` |
| + | `removeActivityPhoto` / `addActivity` / `updateActivity` | `DJ:865`, `:520`, `:516` |

### What moved, and why

Eight items moved from the screen into `dailyJobsiteModel.js`. The reason is
testability, not tidiness: each of them decides something that ends up inside a
signed record, and the frontend suite here has no renderer — logic inside a
component can only be asserted by grepping its source, logic in a module can be
EXECUTED. `dailyJobsiteModel.test.cjs` runs 70 assertions against the real
functions.

`activityIdentity.test.cjs` was re-pointed at the new address, preserving every
assertion it made.

### Three regressions the existing suite caught, and they were right to

1. the lightbox stopped labelling Enhanced vs Original — restored, `DJ:884`;
2. the per-subcontractor photo counter was dropped — restored, `DJ:1449`;
3. `handleSubmitAndSign` lost the `savedId === undefined` guard, so a FAILED
   save would still have frozen the log and announced success — restored,
   `DJ:1036`.

## Drift from `docs/plans/cp-rebuild-research.md`

That document says i18n does not exist (§4.4). It now does:
`frontend/src/i18n/en.js`, consumed here via `useT` at `daily_jobsite.jsx:20,270`.
It landed after the research was written (`12dc3a0`). The `dailyJobsite` and
`finalize` namespaces are live.
</content>
</invoke>
