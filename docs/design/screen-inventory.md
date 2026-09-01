# Screen inventory — Expo Router tree

Read-only audit of `frontend/app/`. **No source file was modified.**

## Method and limits

- **Scope:** every `.jsx`/`.tsx` under `frontend/app/`, excluding `_layout.jsx` and `+html.jsx` (not rendered screens). **64 screens.**
- **Reachability:** static trace. LIVE = some other file navigates to it (`router.push/replace/navigate`, `handleNavigate`, `<Link href>`, or a `path:`/`pathname:` nav-item literal), with `[id]` segments and `${...}` interpolations matched as wildcards, and component-mediated navigation resolved one hop (a screen rendering `<FloatingNav>` inherits its targets). **Every DEAD claim below was verified by reading the call sites.**
- **Tap count** = navigation hops from the role landing (BFS over the nav graph) **+1** for the tap performing the action. Landings come from the `RouteGuard` in `app/_layout.jsx`: office `/`, CP `/logbooks`, kiosk `/site`.
- **Primary action** is derived from the screen's **write calls**, not from button labels. Label extraction by regex proved unreliable here (icon children, arrow functions containing `>`, labels in `title=` props on shared wrappers), so the reported action is the mutation the screen performs — mechanically derivable and checkable against the endpoint column.
- **First-viewport words** is a PROXY, not a measurement: words of user-facing text within the first 15 rendered blocks of the return tree. A true first-viewport count needs a layout pass at 390x844. Use for ordering.
- **Touch targets:** numeric `width`/`height`/`minWidth`/`minHeight`/`size` literals below **56** on field screens and below **44** on office screens. Values from a style object only; runtime-computed sizes and `hitSlop` compensation are not resolved.
- **States** are detected by pattern (`ActivityIndicator`->loading, `OfflineNotice`/`isOfflineError`->offline, `offlineQueue`/`markPending`->offline-queued, etc). Detected means the code path exists, not that it is correct.
- **Offline** = the screen touches `AsyncStorage`/`projectCache`/`docCache`/`logbookDrafts`.

### Theme-audit method

Palettes are in `frontend/src/styles/theme.js`: dark background `#050a12`/`#0A1929` with `rgba(255,255,255,0.9)` text; light background `#d0dcf0`/`#D6E4F7` with `#0A1929` text. A literal is only called a **break** where the evidence supports it. Four categories are explicitly NOT counted as breaks:

1. `withAlpha('#ffffff', 0.05)` — the token helper in `src/styles/semanticColors.js`. A translucent overlay is the intended dark-theme surface/border idiom (it matches `_dark.border.subtle` `rgba(255,255,255,0.1)`). **260 literals.**
2. Literals inside an `isDark ? a : b` ternary — already branched. **6.**
3. Saturated hues (HSV S>0.35) — status/accent colours, not surfaces; they render in both themes. Reported separately as hardcoded status colours. **348.**
4. `color:` literals whose parent `backgroundColor` is not also hardcoded on the same style object — not statically judgeable. **74.**

Counting any of these as breakage inflates the result; an earlier pass of this audit did exactly that and reported 45 broken screens before the exclusions were applied.

## Totals

| Metric | Count |
|---|---:|
| Screens | 64 |
| Reachable | 49 |
| DEAD | 15 |
| Field-audience screens | 21 |
| Office-audience screens | 43 |
| Offline-capable | 29 |
| Screens using `useTheme()` | 58 |
| Colour literals (all) | 700 |
| — of which `withAlpha()` helper | 260 |
| — of which status/accent | 348 |
| **Confirmed dark-mode breaks** | 0 |
| **Confirmed light-mode breaks** | 0 |
| Inline theme branches | 7 |
| Screens with an i18n hook | 0 |

## Screen inventory

`Taps` launch->action. `FVW` first-viewport words (proxy). `Tgt` touch targets under the audience threshold. `Lit` colour literals. `Str` user-facing strings (none i18n-routed).

| Route | File | Status | Audience | Primary action | Taps | FVW | Offline | Missing states | Tgt | Lit | Str |
|---|---|---|---|---|---:|---:|---|---|---:|---:|---:|
| `/` | `app/index.jsx` | LIVE | office | `read / review (no write call)` | 1 | 3 | yes | queued, stale, unverified | 4 | 0 | 12 |
| `/admin/checklists` | `app/admin/checklists/index.jsx` | LIVE | office | `checklistsAPI.assign` | 2 | 12 | no | stale, unverified | 2 | 12 | 18 |
| `/admin/insurance` | `app/admin/insurance.jsx` | DEAD | office | `read / review (no write call)` | — | 0 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 0 |
| `/admin/integrations` | `app/admin/integrations.jsx` | LIVE | office | `read / review (no write call)` | 2 | 19 | no | queued, stale, unverified | 0 | 14 | 23 |
| `/admin/safety-staff` | `app/admin/safety-staff.jsx` | LIVE | office | `safetyStaffAPI.create` | 2 | 31 | no | queued, stale, unverified | 0 | 10 | 20 |
| `/admin/site-devices` | `app/admin/site-devices.jsx` | LIVE | office | `siteDevicesAPI.create` | 2 | 14 | no | empty, queued, stale, unverified | 0 | 4 | 15 |
| `/admin/superintendent` | `app/admin/superintendent.jsx` | LIVE | office | `csRegistrationAPI.create` | 2 | 4 | no | stale, unverified | 0 | 11 | 20 |
| `/admin/users` | `app/admin/users.jsx` | LIVE | office | `adminUsersAPI.create` | 2 | 15 | no | stale, unverified | 0 | 10 | 20 |
| `/checkin` | `app/checkin/index.jsx` | DEAD | field | `checkinsAPI.checkIn` | — | 5 | no | queued, stale, unverified | 6 | 13 | 14 |
| `/checkin/[project_id]/[tag_id]` | `app/checkin/[project_id]/[tag_id].jsx` | DEAD | field | `read / review (no write call)` | — | 22 | no | offline, queued, stale, unverified | 0 | 7 | 11 |
| `/checklists` | `app/checklists.jsx` | DEAD | office | `read / review (no write call)` | — | 10 | no | queued, unverified | 3 | 8 | 5 |
| `/daily-log` | `app/daily-log.jsx` | LIVE | office | `read / review (no write call)` | 3 | 5 | yes | stale, unverified | 2 | 26 | 34 |
| `/demo` | `app/demo.jsx` | LIVE | office | `read / review (no write call)` | 2 | 17 | no | empty, queued, stale, unverified | 0 | 2 | 7 |
| `/documents` | `app/documents.jsx` | DEAD | office | `read / review (no write call)` | — | 6 | yes | queued, stale, unverified | 0 | 10 | 4 |
| `/help` | `app/help/index.jsx` | DEAD | office | `read / review (no write call)` | — | 2 | no | empty, error, loading, offline, queued, stale, unverified | 2 | 0 | 1 |
| `/help/faq` | `app/help/faq.jsx` | DEAD | office | `read / review (no write call)` | — | 54 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 13 |
| `/help/getting-started` | `app/help/getting-started.jsx` | DEAD | office | `read / review (no write call)` | — | 31 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 8 |
| `/help/notifications` | `app/help/notifications.jsx` | DEAD | office | `read / review (no write call)` | — | 23 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 7 |
| `/help/permit-renewal` | `app/help/permit-renewal.jsx` | DEAD | office | `read / review (no write call)` | — | 38 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 6 |
| `/help/troubleshooting` | `app/help/troubleshooting.jsx` | DEAD | office | `read / review (no write call)` | — | 33 | no | empty, error, loading, offline, queued, stale, unverified | 0 | 0 | 4 |
| `/logbooks` | `app/logbooks/index.jsx` | LIVE | field | `read / review (no write call)` | 1 | 6 | yes | queued, unverified | 4 | 19 | 16 |
| `/logbooks/concrete_operations` | `app/logbooks/concrete_operations.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 24 | yes | stale, unverified | 2 | 9 | 23 |
| `/logbooks/crane_operations` | `app/logbooks/crane_operations.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 23 | yes | stale, unverified | 2 | 4 | 20 |
| `/logbooks/daily_jobsite` | `app/logbooks/daily_jobsite.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 12 | yes | stale, unverified | 3 | 24 | 33 |
| `/logbooks/excavation_monitoring` | `app/logbooks/excavation_monitoring.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 8 | yes | stale, unverified | 2 | 9 | 20 |
| `/logbooks/hot_work` | `app/logbooks/hot_work.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 10 | yes | stale, unverified | 2 | 5 | 18 |
| `/logbooks/osha_log` | `app/logbooks/osha_log.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 18 | yes | stale, unverified | 3 | 24 | 12 |
| `/logbooks/preshift_signin` | `app/logbooks/preshift_signin.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 6 | yes | empty, stale, unverified | 4 | 18 | 15 |
| `/logbooks/review` | `app/logbooks/review.jsx` | LIVE | field | `read / review (no write call)` | 2 | 0 | no | queued, stale | 0 | 21 | 0 |
| `/logbooks/scaffold_maintenance` | `app/logbooks/scaffold_maintenance.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 3 | yes | empty, stale, unverified | 0 | 21 | 7 |
| `/logbooks/ssc_daily_safety_log` | `app/logbooks/ssc_daily_safety_log.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 8 | yes | empty, stale, unverified | 2 | 9 | 22 |
| `/logbooks/subcontractor_orientation` | `app/logbooks/subcontractor_orientation.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 13 | yes | stale, unverified | 6 | 19 | 11 |
| `/logbooks/toolbox_talk` | `app/logbooks/toolbox_talk.jsx` | LIVE | field | `logbooksAPI.create` | 2 | 3 | yes | stale, unverified | 4 | 25 | 13 |
| `/login` | `app/login.jsx` | LIVE | office | `read / review (no write call)` | 2 | 10 | no | empty, offline, queued, stale, unverified | 0 | 0 | 8 |
| `/nfc` | `app/nfc/index.jsx` | DEAD | field | `read / review (no write call)` | — | 28 | yes | empty, queued, stale, unverified | 0 | 8 | 11 |
| `/onboarding` | `app/onboarding.jsx` | LIVE | office | `read / review (no write call)` | — | 12 | no | empty, offline, queued, stale, unverified | 4 | 1 | 23 |
| `/owner` | `app/owner/index.jsx` | DEAD | office | `read / review (no write call)` | — | 10 | no | stale | 0 | 17 | 39 |
| `/owner/pending-deletion` | `app/owner/pending-deletion.jsx` | DEAD | office | `read / review (no write call)` | — | 10 | no | queued, stale, unverified | 0 | 8 | 5 |
| `/project/[id]` | `app/project/[id].jsx` | LIVE | office | `siteDevicesAPI.create` | 2 | 2 | yes | queued, unverified | 7 | 29 | 65 |
| `/project/[id]/activity` | `app/project/[id]/activity.jsx` | LIVE | office | `read / review (no write call)` | 2 | 0 | no | empty, error, offline, queued, stale, unverified | 2 | 0 | 1 |
| `/project/[id]/audit` | `app/project/[id]/audit.jsx` | DEAD | office | `read / review (no write call)` | — | 17 | no | queued, stale, unverified | 4 | 8 | 7 |
| `/project/[id]/defcon` | `app/project/[id]/defcon.jsx` | LIVE | office | `read / review (no write call)` | 3 | 8 | no | empty, error, queued, stale, unverified | 2 | 0 | 6 |
| `/project/[id]/dob-logs` | `app/project/[id]/dob-logs.jsx` | LIVE | office | `read / review (no write call)` | 3 | 1 | no | queued, stale, unverified | 8 | 22 | 50 |
| `/project/[id]/notifications` | `app/project/[id]/notifications.jsx` | LIVE | office | `read / review (no write call)` | 3 | 0 | no | empty, error, offline, queued, stale, unverified | 2 | 0 | 1 |
| `/project/[id]/permit-renewal` | `app/project/[id]/permit-renewal.jsx` | LIVE | office | `read / review (no write call)` | 4 | 5 | no | stale, unverified | 5 | 11 | 20 |
| `/project/[id]/report-settings` | `app/project/[id]/report-settings.jsx` | LIVE | office | `read / review (no write call)` | 3 | 19 | yes | empty, unverified | 0 | 5 | 14 |
| `/project/[id]/trades` | `app/project/[id]/trades.jsx` | LIVE | office | `projectsAPI.update` | 3 | 18 | yes | stale, unverified | 0 | 9 | 14 |
| `/projects` | `app/projects/index.jsx` | LIVE | office | `projectsAPI.create` | 2 | 5 | yes | queued, stale, unverified | 4 | 16 | 8 |
| `/projects/[id]/construction-plans` | `app/projects/[id]/construction-plans.jsx` | LIVE | office | `read / review (no write call)` | 3 | 5 | yes | queued, unverified | 4 | 21 | 7 |
| `/projects/[id]/dropbox-settings` | `app/projects/[id]/dropbox-settings.jsx` | LIVE | office | `read / review (no write call)` | 3 | 25 | yes | queued, unverified | 4 | 10 | 19 |
| `/projects/[id]/whatsapp-checklists` | `app/projects/[id]/whatsapp-checklists.jsx` | LIVE | office | `read / review (no write call)` | 3 | 7 | no | offline, queued, stale, unverified | 4 | 6 | 3 |
| `/projects/[id]/whatsapp-groups` | `app/projects/[id]/whatsapp-groups.jsx` | LIVE | office | `read / review (no write call)` | 3 | 4 | yes | queued, stale, unverified | 8 | 7 | 10 |
| `/register` | `app/register.jsx` | LIVE | office | `authAPI.register` | 3 | 17 | no | empty, offline, queued, stale, unverified | 0 | 0 | 11 |
| `/reports` | `app/reports.jsx` | LIVE | office | `read / review (no write call)` | 2 | 5 | no | queued, unverified | 0 | 18 | 14 |
| `/settings` | `app/settings.jsx` | LIVE | office | `read / review (no write call)` | 2 | 3 | no | stale, unverified | 3 | 5 | 37 |
| `/settings/notifications` | `app/settings/notifications.jsx` | LIVE | office | `read / review (no write call)` | 3 | 0 | no | offline, queued, stale, unverified | 7 | 26 | 16 |
| `/settings/notifications/project/[project_id]` | `app/settings/notifications/project/[project_id].jsx` | LIVE | office | `read / review (no write call)` | 4 | 0 | no | empty, offline, queued, stale, unverified | 7 | 22 | 14 |
| `/site` | `app/site/index.jsx` | LIVE | field | `read / review (no write call)` | 1 | 4 | no | empty, error, queued, stale, unverified | 2 | 14 | 6 |
| `/site/checkins` | `app/site/checkins.jsx` | LIVE | field | `read / review (no write call)` | 2 | 4 | yes | — | 11 | 20 | 12 |
| `/site/daily-logs` | `app/site/daily-logs.jsx` | LIVE | field | `dailyLogsAPI.create` | 2 | 3 | yes | empty, unverified | 9 | 20 | 27 |
| `/site/documents` | `app/site/documents.jsx` | LIVE | field | `read / review (no write call)` | 2 | 8 | yes | empty, queued, stale, unverified | 7 | 7 | 6 |
| `/site/logbooks` | `app/site/logbooks.jsx` | LIVE | field | `read / review (no write call)` | 2 | 8 | yes | queued, unverified | 7 | 42 | 18 |
| `/workers` | `app/workers.jsx` | LIVE | office | `read / review (no write call)` | 2 | 4 | yes | queued, unverified | 6 | 2 | 7 |
| `/workers/[id]` | `app/workers/[id].jsx` | LIVE | office | `read / review (no write call)` | 3 | 3 | yes | empty, queued | 6 | 12 | 31 |

### Endpoints per screen

| Route | Endpoints |
|---|---|
| `/` | `checkinsAPI.getByDate`, `projectsAPI.getAll`, `workersAPI.getAll` |
| `/admin/checklists` | `adminUsersAPI.getAll`, `checklistsAPI.assign`, `checklistsAPI.create`, `checklistsAPI.delete`, `checklistsAPI.getAll`, `checklistsAPI.getAssignments`, `checklistsAPI.update`, `projectsAPI.getAll` |
| `/admin/insurance` | — none |
| `/admin/integrations` | `dropboxAPI.completeAuth`, `dropboxAPI.disconnect`, `dropboxAPI.getAuthUrl`, `dropboxAPI.getStatus`, `projectsAPI.getAll`, `whatsappAPI.activate`, `whatsappAPI.downloadVCard`, `whatsappAPI.getStatus` |
| `/admin/safety-staff` | `projectsAPI.getAll`, `safetyStaffAPI.create`, `safetyStaffAPI.delete`, `safetyStaffAPI.getByProject`, `safetyStaffAPI.update` |
| `/admin/site-devices` | `projectsAPI.getAll`, `siteDevicesAPI.create`, `siteDevicesAPI.delete`, `siteDevicesAPI.getAll`, `siteDevicesAPI.update` |
| `/admin/superintendent` | `csRegistrationAPI.create`, `csRegistrationAPI.delete`, `csRegistrationAPI.getAll`, `csRegistrationAPI.update`, `projectsAPI.getAll` |
| `/admin/users` | `adminUsersAPI.assignProjects`, `adminUsersAPI.create`, `adminUsersAPI.delete`, `adminUsersAPI.getAll`, `adminUsersAPI.update`, `projectsAPI.getAll` |
| `/checkin` | `checkinsAPI.checkIn`, `projectsAPI.getAll`, `workersAPI.getAll` |
| `/checkin/[project_id]/[tag_id]` | — none |
| `/checklists` | `checklistsAPI.getAssigned`, `checklistsAPI.getAssignmentDetails`, `checklistsAPI.updateCompletion` |
| `/daily-log` | `csRegistrationAPI.getForProject` |
| `/demo` | `demoAPI.getProject` |
| `/documents` | `dropboxAPI.getFileUrl`, `dropboxAPI.getProjectFiles`, `dropboxAPI.uploadFile`, `projectsAPI.getAll` |
| `/help` | — none |
| `/help/faq` | — none |
| `/help/getting-started` | — none |
| `/help/notifications` | — none |
| `/help/permit-renewal` | — none |
| `/help/troubleshooting` | — none |
| `/logbooks` | `checkinsAPI.getFlagged`, `cpProfileAPI.getProfile`, `logbooksAPI.getByProject`, `logbooksAPI.getNotifications`, `logbooksAPI.getScaffoldInfo`, `logbooksAPI.saveScaffoldInfo`, `projectsAPI.getAll`, `projectsAPI.getRequiredLogbooks` |
| `/logbooks/concrete_operations` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.update` |
| `/logbooks/crane_operations` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.update` |
| `/logbooks/daily_jobsite` | `logbooksAPI.create`, `logbooksAPI.finalize`, `logbooksAPI.getByProject`, `logbooksAPI.getDailyHeadcount`, `logbooksAPI.getLogbookPhotoUrl`, `logbooksAPI.update`, `projectsAPI.getById`, `weatherAPI.getCurrent` |
| `/logbooks/excavation_monitoring` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.update` |
| `/logbooks/hot_work` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.update` |
| `/logbooks/osha_log` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.getCheckinsForDate`, `logbooksAPI.update` |
| `/logbooks/preshift_signin` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.getCheckinsForDate`, `logbooksAPI.update`, `projectsAPI.getById` |
| `/logbooks/review` | `checkinsAPI.assignTrade`, `checkinsAPI.getFlagged`, `checkinsAPI.review`, `projectsAPI.getAll` |
| `/logbooks/scaffold_maintenance` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.getScaffoldInfo`, `logbooksAPI.saveScaffoldInfo`, `logbooksAPI.update` |
| `/logbooks/ssc_daily_safety_log` | `logbooksAPI.create`, `logbooksAPI.finalize`, `logbooksAPI.getByProject`, `logbooksAPI.update`, `projectsAPI.getById` |
| `/logbooks/subcontractor_orientation` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.update` |
| `/logbooks/toolbox_talk` | `logbooksAPI.create`, `logbooksAPI.getByProject`, `logbooksAPI.getCheckinsForDate`, `logbooksAPI.update`, `projectsAPI.getById` |
| `/login` | — none |
| `/nfc` | — none |
| `/onboarding` | `onboardingAPI.patchStep` |
| `/owner` | `ownerAPI.addFilingRep`, `ownerAPI.createAdmin`, `ownerAPI.createCompany`, `ownerAPI.deleteAdmin`, `ownerAPI.deleteFilingRep`, `ownerAPI.getAdmins`, `ownerAPI.getCompanies`, `ownerAPI.listFilingReps`, `ownerAPI.migrateData`, `ownerAPI.updateFilingRep` |
| `/owner/pending-deletion` | `projectsAPI.hardDelete`, `projectsAPI.pendingDeletion` |
| `/project/[id]` | `checklistsAPI.getByProject`, `dropboxAPI.getFiles`, `dropboxAPI.linkFolder`, `projectsAPI.addNfcTag`, `projectsAPI.deleteNfcTag`, `projectsAPI.getById`, `projectsAPI.getNfcTags`, `siteDevicesAPI.create`, `siteDevicesAPI.delete`, `siteDevicesAPI.getByProject`, `siteDevicesAPI.toggle`, `whatsappAPI.getGroups`, `whatsappAPI.getStatus` |
| `/project/[id]/activity` | — none |
| `/project/[id]/audit` | — none |
| `/project/[id]/defcon` | `projectsAPI.getDefconStatus` |
| `/project/[id]/dob-logs` | `dobAPI.getLogs`, `dobAPI.getSummary`, `dobAPI.syncNow`, `dobAPI.updateConfig` |
| `/project/[id]/notifications` | — none |
| `/project/[id]/permit-renewal` | `permitRenewalAPI.js`, `renewalAPI.list`, `renewalAPI.prepare` |
| `/project/[id]/report-settings` | `projectsAPI.getById`, `projectsAPI.updateReportSettings` |
| `/project/[id]/trades` | `projectsAPI.getById`, `projectsAPI.update` |
| `/projects` | `projectsAPI.create`, `projectsAPI.delete`, `projectsAPI.getAll` |
| `/projects/[id]/construction-plans` | `dropboxAPI.deleteFile`, `dropboxAPI.getFileUrl`, `dropboxAPI.getProjectFiles`, `dropboxAPI.syncProject`, `dropboxAPI.uploadFile`, `projectsAPI.getById` |
| `/projects/[id]/dropbox-settings` | `dropboxAPI.getFolders`, `dropboxAPI.getProjectFiles`, `dropboxAPI.getSiteDeviceSubfolders`, `dropboxAPI.getStatus`, `dropboxAPI.linkToProject`, `dropboxAPI.setSiteDeviceSubfolders`, `dropboxAPI.syncProject`, `projectsAPI.getById` |
| `/projects/[id]/whatsapp-checklists` | `checklistAPI.getForProject`, `checklistAPI.updateItem`, `whatsappAPI.getGroups` |
| `/projects/[id]/whatsapp-groups` | `documentsAPI.getIndexStatus`, `documentsAPI.reindexFile`, `projectsAPI.getById`, `whatsappAPI.getGroups`, `whatsappAPI.getStatus`, `whatsappAPI.initiateLink`, `whatsappAPI.unlinkGroup`, `whatsappAPI.verifyLink` |
| `/register` | `authAPI.register` |
| `/reports` | `projectsAPI.getAll`, `reportsAPI.getHistory`, `reportsAPI.getPreview` |
| `/settings` | `authAPI.changePassword`, `authAPI.updateProfile`, `projectsAPI.getAll` |
| `/settings/notifications` | — none |
| `/settings/notifications/project/[project_id]` | — none |
| `/site` | `checkinsAPI.getActiveByProject`, `dailyLogsAPI.getByProject` |
| `/site/checkins` | `checkinsAPI.getTodayByProject`, `checkinsAPI.review` |
| `/site/daily-logs` | `csRegistrationAPI.getForProject`, `dailyLogsAPI.create`, `dailyLogsAPI.getByProject`, `dailyLogsAPI.update` |
| `/site/documents` | `dropboxAPI.getProjectFiles` |
| `/site/logbooks` | `logbooksAPI.getSubmitted` |
| `/workers` | `checkinsAPI.getByDate` |
| `/workers/[id]` | `workersAPI.getById`, `workersAPI.getOshaCard` |

### Touch targets under threshold

| Route | Threshold | Line:value |
|---|---:|---|
| `/site/checkins` | 56pt | L655:44, L656:44, L739:8, L740:8, L828:48, L871:1, L872:40, L885:36, L886:36, L936:6, L937:6 |
| `/site/daily-logs` | 56pt | L803:44, L803:44, L836:50, L844:48, L855:44, L856:26, L856:26, L886:44, L886:44 |
| `/project/[id]/dob-logs` | 44pt | L617:8, L617:8, L1291:10, L1291:10, L1311:1, L1330:28, L1332:22, L1332:22 |
| `/projects/[id]/whatsapp-groups` | 44pt | L365:8, L366:8, L510:32, L510:32, L753:40, L754:40, L760:36, L761:36 |
| `/project/[id]` | 44pt | L1807:32, L1808:32, L1817:22, L1818:22, L2268:1, L2342:1, L2343:28 |
| `/settings/notifications` | 44pt | L1212:28, L1229:28, L1229:28, L1316:18, L1316:18, L1325:10, L1325:10 |
| `/settings/notifications/project/[project_id]` | 44pt | L874:28, L939:28, L939:28, L1042:18, L1042:18, L1047:10, L1047:10 |
| `/site/documents` | 56pt | L429:44, L430:44, L484:52, L500:44, L501:44, L563:48, L564:48 |
| `/site/logbooks` | 56pt | L844:48, L850:22, L850:22, L923:1, L942:36, L960:48, L993:40 |
| `/checkin` | 56pt | L504:40, L505:40, L560:44, L561:44, L650:40, L651:40 |
| `/logbooks/subcontractor_orientation` | 56pt | L1031:22, L1032:22, L1093:40, L1094:40, L1124:1, L1141:4 |
| `/workers` | 44pt | L542:1, L543:40, L558:34, L559:34, L622:6, L623:6 |
| `/workers/[id]` | 44pt | L962:28, L963:28, L1093:32, L1094:32, L1122:20, L1123:20 |
| `/project/[id]/permit-renewal` | 44pt | L1170:40, L1171:40, L1256:8, L1257:8, L1411:18 |
| `/` | 44pt | L125:24, L139:40, L1019:36, L1020:36 |
| `/logbooks` | 56pt | L637:1, L701:48, L701:48, L726:6 |
| `/logbooks/preshift_signin` | 56pt | L660:36, L697:36, L729:32, L730:26 |
| `/logbooks/toolbox_talk` | 56pt | L715:18, L716:18, L787:20, L788:20 |
| `/onboarding` | 44pt | L726:32, L727:4, L865:20, L866:20 |
| `/project/[id]/audit` | 44pt | L339:36, L339:36, L343:36, L343:36 |
| `/projects/[id]/construction-plans` | 44pt | L820:36, L821:36, L938:36, L939:36 |
| `/projects/[id]/dropbox-settings` | 44pt | L860:20, L861:20, L868:20, L869:20 |
| `/projects/[id]/whatsapp-checklists` | 44pt | L265:8, L265:8, L394:22, L395:22 |
| `/projects` | 44pt | L553:10, L554:10, L734:22, L735:22 |
| `/checklists` | 44pt | L413:6, L426:32, L426:32 |
| `/logbooks/daily_jobsite` | 56pt | L1442:26, L1442:26, L1476:6 |
| `/logbooks/osha_log` | 56pt | L607:22, L608:22, L619:1 |
| `/settings` | 44pt | L608:10, L608:10, L903:20 |
| `/admin/checklists` | 44pt | L784:20, L784:20 |
| `/daily-log` | 44pt | L1444:20, L1445:20 |
| `/help` | 44pt | L139:40, L140:40 |
| `/logbooks/concrete_operations` | 56pt | L517:22, L517:22 |
| `/logbooks/crane_operations` | 56pt | L510:22, L510:22 |
| `/logbooks/excavation_monitoring` | 56pt | L573:22, L573:22 |
| `/logbooks/hot_work` | 56pt | L522:22, L522:22 |
| `/logbooks/ssc_daily_safety_log` | 56pt | L609:22, L609:22 |
| `/project/[id]/activity` | 44pt | L96:36, L97:36 |
| `/project/[id]/defcon` | 44pt | L312:36, L313:36 |
| `/project/[id]/notifications` | 44pt | L96:36, L97:36 |
| `/site` | 56pt | L269:44, L270:44 |

### User-facing strings not routed through i18n

**No i18n infrastructure exists in this tree** — no i18n directory, and no file imports `useTranslation`, `i18next`, `react-i18next`, or a language context. Every user-facing string in all 64 screens is a literal. The bilingual EN/ES worker flow lives in `backend/checkin.html` (server-rendered en/es maps), not here.

Two screens carry inline hardcoded Spanish rather than a lookup:

| File | Line | String |
|---|---:|---|
| `app/logbooks/review.jsx` | 112 | `Trabajadores que requieren una decision` |
| `app/logbooks/review.jsx` | 134 | `Trabajador aprobado para permanecer en el sitio` |
| `app/logbooks/subcontractor_orientation.jsx` | 46 | `Espanol` |
| `app/logbooks/subcontractor_orientation.jsx` | 833 | `Espanol` |

Per-screen sample (first 12 literals each; full count in the `Str` column):

| Route | Strings |
|---|---|
| `/project/[id]` | `/Projects/Downtown Building`, `Action Items`, `Add NFC tag`, `Add NFC tags for worker check-in`, `Add Site Device`, `Add devices for on-site access`, `Add site device`, `Assigned`, `CHECKLISTS`, `Checklists will appear here when assigned to this project`, `Complete`, `Connected Folder` |
| `/project/[id]/dob-logs` | `7-digit BIN`, `ACTION`, `ASSIGNED TO`, `Automated filing — coming soon`, `BIN Has No DOB Records`, `Building Identification Number (BIN)`, `CURRENT STATUS`, `Category`, `DOB COMPLIANCE`, `DOB Configuration`, `Date`, `Description` |
| `/owner` | `ADMIN NAME`, `Add filing representative`, `Admin Accounts`, `Back to dashboard`, `COMPANY`, `COMPANY NAME (GC LICENSE LOOKUP)`, `Cancel`, `Companies`, `Create Admin`, `Create Admin Account`, `Create Company`, `Create a company first before adding admins` |
| `/settings` | `ACCOUNT`, `APPEARANCE`, `Cancel`, `Change Password`, `Confirm new password`, `Current password`, `DOB PERMIT RENEWAL`, `Disability / DB Expiry`, `Display Name`, `Effective`, `Email`, `Email address` |
| `/daily-log` | `COMPETENT PERSON SIGNATURE`, `CORRECTIVE ACTIONS`, `Close`, `Competent Person Sign-Off`, `Competent Person Signature`, `Corrective Actions`, `Daily Logs`, `Daily Notes`, `Daily logs for this project will appear here.`, `Describe any incidents, injuries, or near-misses...`, `Describe unsafe conditions and corrective measures taken...`, `Enter daily notes, progress updates, etc...` |
| `/logbooks/daily_jobsite` | `+ Add Activity`, `+ Add Observation`, `Activity Details`, `Address`, `Auto-populated from check-ins. Edit as needed.`, `COMPANY`, `CREW`, `Company`, `Competent Person Sign-Off`, `Competent Person Signature`, `Daily Jobsite Log`, `Describe observation...` |
| `/workers/[id]` | `Add`, `Add Signature`, `Cancel`, `Certification name`, `Certifications`, `Company`, `Completed during first NFC check-in at each site`, `Credential needs review`, `Digital Signature`, `Draw Signature`, `Expires`, `Expiry date (optional)` |
| `/site/daily-logs` | `COMPETENT PERSON`, `Close`, `Corrective Actions`, `DAILY`, `Daily notes...`, `Describe corrections...`, `Incident Log`, `Log Books`, `N/A - No incidents`, `NOTES`, `No Previous Logs`, `Notes` |
| `/admin/integrations` | `ADMIN`, `Activate WhatsApp`, `Add this number to WhatsApp groups from each project page.`, `Admin Access Required`, `All Projects`, `CONNECTED ACCOUNT`, `CONNECTED SINCE`, `Connect to Dropbox`, `Create Project`, `Disconnect Dropbox`, `Dropbox`, `Go to a project's settings to enable Dropbox sync` |
| `/logbooks/concrete_operations` | `+ Add Slump Test`, `CP Signature`, `Competent Person Sign-Off`, `Concrete Operations Log`, `Concrete Supplier`, `Fail`, `Formwork Inspection`, `HH:MM`, `Mix Design`, `Pass`, `Pour Details`, `Pour Location` |
| `/onboarding` | `(555) 555-5555`, `123 Front St, Brooklyn, NY 11201`, `123 Main St, Brooklyn, NY 11201`, `Add another rep`, `COMPANY NAME`, `Critical only`, `EMAIL`, `EXPECTED COMPLETION`, `EXPECTED START`, `Jane Doe`, `LICENSE NUMBER`, `NAME` |
| `/logbooks/ssc_daily_safety_log` | `Corrective Actions Taken`, `Describe any safety violations observed...`, `Describe corrective actions taken...`, `Describe current site conditions...`, `Fire Protection in Place`, `Housekeeping Satisfactory`, `Incidents`, `Incidents Reported`, `PPE Compliance`, `Project Address`, `Project Information`, `Provide incident details...` |
| `/admin/safety-staff` | `ADMIN`, `Add Safety Staff`, `Add Staff Member`, `Add an SSC or SSM registration for this project.`, `Cancel`, `EMAIL`, `Edit Safety Staff`, `Email (optional)`, `Full name`, `LICENSE EXPIRATION`, `LICENSE NUMBER`, `NAME` |
| `/admin/superintendent` | `ADMIN`, `Active on this project`, `Cancel`, `Construction Superintendent full name`, `Edit Superintendent`, `FULL NAME`, `LICENSE NUMBER`, `NYC DOB CS License #`, `NYC.ID EMAIL`, `NYC.ID email for DOB filings (optional)`, `No Superintendents Registered`, `PHONE` |
| `/admin/users` | `ADMIN`, `Add New User`, `Add User`, `Admin Access Required`, `Assign`, `Assign Projects`, `CP Manager`, `Cancel`, `Edit`, `Edit User`, `Email`, `Full Name` |
| `/logbooks/crane_operations` | `+ Add Load Entry`, `CP Signature`, `Competent Person Sign-Off`, `Crane ID / Serial Number`, `Crane Information`, `Crane Operations Log`, `Crane Type`, `Description`, `Equipment ID`, `Full name`, `HH:MM`, `License #` |
| `/logbooks/excavation_monitoring` | `+ Add Building`, `Address`, `Adjacent Building Monitoring`, `Atmospheric Testing Performed`, `Baseline`, `Building address`, `CP Signature`, `Competent Person Sign-Off`, `Current`, `Current Reading (in/s)`, `Delta`, `Environmental Conditions` |
| `/project/[id]/permit-renewal` | `Automated filing — coming soon`, `Awaiting GC`, `BIS Legacy Permit`, `Blocked`, `Disability`, `Done`, `General Liability`, `Go to Settings`, `Insurance Coverage`, `Insurance Required`, `LOADING RENEWALS`, `Manual renewal required on DOB NOW` |
| `/projects/[id]/dropbox-settings` | `Admin access required to modify settings`, `Back`, `Dropbox Not Connected`, `Enable Dropbox`, `Files`, `Go to Admin Settings`, `LINKED FOLDER`, `LINKED FOLDER (SAVED COPY)`, `Last Synced`, `No folder linked yet`, `No subfolders`, `PROJECT SETTINGS` |
| `/admin/checklists` | `ADMIN`, `Add Item`, `Assign Checklist`, `Assignments`, `Cancel`, `Checklists`, `Close`, `Create`, `Create your first checklist to get started`, `Describe the checklist...`, `Description (Optional)`, `ITEMS` |
| `/logbooks/hot_work` | `CP Signature`, `Cert #`, `Competent Person Sign-Off`, `End Time`, `Fire Watch Person Name`, `Floor, area, or room...`, `Full name`, `Full name of worker performing hot work`, `HH:MM`, `Hot Work Permit Log`, `Location`, `Precautions Checklist` |
| `/site/logbooks` | `Activity Details`, `Competent Person (CP)`, `Download Full Day Report`, `Equipment on Site`, `Exit Inspector Mode`, `General Description`, `Inspected`, `Loading logbooks...`, `Log Books`, `No Submitted Logs`, `No data available`, `None` |
| `/logbooks` | `COMPLIANCE`, `Check-In Review`, `Completed this week`, `Done`, `Draft`, `Loading log books...`, `Log Books`, `Open Tool Box Talk`, `PROJECT`, `Pending`, `Scaffolding / Overhead Shed`, `Signing as` |
| `/settings/notifications` | `Choose how we notify you`, `DELIVERY TIMING`, `Daily digest time`, `Delivery`, `Live preview`, `Notifications`, `PER-PROJECT OVERRIDES`, `Preview unavailable`, `Reset`, `Reset to last saved`, `Retry`, `Severity fallback routes` |
| `/admin/site-devices` | `ADMIN`, `Add Site Device`, `Cancel`, `Create a secure password`, `Done`, `LAST LOGIN`, `No Site Devices`, `PASSWORD`, `PROJECT`, `Password`, `Project`, `Site Devices` |

## Theme audit — per screen

| Route | Literals | withAlpha | status/accent | Dark breaks | Light breaks | isDark refs | Inline branches |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/site/logbooks` | 42 | 17 | 23 | 0 | 0 | 3 | 0 |
| `/project/[id]` | 29 | 5 | 24 | 0 | 0 | 3 | 0 |
| `/daily-log` | 26 | 12 | 11 | 0 | 0 | 3 | 0 |
| `/settings/notifications` | 26 | 2 | 18 | 0 | 0 | 0 | 0 |
| `/logbooks/toolbox_talk` | 25 | 12 | 11 | 0 | 0 | 3 | 0 |
| `/logbooks/daily_jobsite` | 24 | 14 | 4 | 0 | 0 | 4 | 0 |
| `/logbooks/osha_log` | 24 | 12 | 11 | 0 | 0 | 3 | 0 |
| `/project/[id]/dob-logs` | 22 | 3 | 15 | 0 | 0 | 3 | 0 |
| `/settings/notifications/project/[project_id]` | 22 | 2 | 14 | 0 | 0 | 0 | 0 |
| `/logbooks/review` | 21 | 3 | 17 | 0 | 0 | 0 | 0 |
| `/logbooks/scaffold_maintenance` | 21 | 9 | 9 | 0 | 0 | 3 | 0 |
| `/projects/[id]/construction-plans` | 21 | 8 | 13 | 0 | 0 | 3 | 0 |
| `/site/checkins` | 20 | 6 | 13 | 0 | 0 | 3 | 0 |
| `/site/daily-logs` | 20 | 11 | 5 | 0 | 0 | 3 | 0 |
| `/logbooks` | 19 | 8 | 11 | 0 | 0 | 7 | 4 |
| `/logbooks/subcontractor_orientation` | 19 | 8 | 10 | 0 | 0 | 5 | 0 |
| `/logbooks/preshift_signin` | 18 | 10 | 8 | 0 | 0 | 3 | 0 |
| `/reports` | 18 | 6 | 12 | 0 | 0 | 3 | 0 |
| `/owner` | 17 | 11 | 4 | 0 | 0 | 3 | 0 |
| `/projects` | 16 | 8 | 6 | 0 | 0 | 4 | 1 |
| `/admin/integrations` | 14 | 2 | 5 | 0 | 0 | 3 | 0 |
| `/site` | 14 | 7 | 6 | 0 | 0 | 3 | 0 |
| `/checkin` | 13 | 4 | 6 | 0 | 0 | 3 | 0 |
| `/admin/checklists` | 12 | 4 | 4 | 0 | 0 | 3 | 0 |
| `/workers/[id]` | 12 | 7 | 1 | 0 | 0 | 3 | 0 |
| `/admin/superintendent` | 11 | 7 | 3 | 0 | 0 | 3 | 0 |
| `/project/[id]/permit-renewal` | 11 | 0 | 11 | 0 | 0 | 3 | 0 |
| `/admin/safety-staff` | 10 | 4 | 5 | 0 | 0 | 3 | 0 |
| `/admin/users` | 10 | 2 | 6 | 0 | 0 | 3 | 0 |
| `/documents` | 10 | 2 | 7 | 0 | 0 | 3 | 0 |
| `/projects/[id]/dropbox-settings` | 10 | 3 | 5 | 0 | 0 | 3 | 0 |
| `/logbooks/concrete_operations` | 9 | 5 | 3 | 0 | 0 | 3 | 0 |
| `/logbooks/excavation_monitoring` | 9 | 5 | 3 | 0 | 0 | 3 | 0 |
| `/logbooks/ssc_daily_safety_log` | 9 | 4 | 4 | 0 | 0 | 3 | 0 |
| `/project/[id]/trades` | 9 | 4 | 1 | 0 | 0 | 4 | 1 |
| `/checklists` | 8 | 4 | 4 | 0 | 0 | 3 | 0 |
| `/nfc` | 8 | 1 | 7 | 0 | 0 | 3 | 0 |
| `/owner/pending-deletion` | 8 | 1 | 6 | 0 | 0 | 0 | 0 |
| `/project/[id]/audit` | 8 | 2 | 6 | 0 | 0 | 4 | 0 |
| `/checkin/[project_id]/[tag_id]` | 7 | 2 | 3 | 0 | 0 | 4 | 1 |
| `/projects/[id]/whatsapp-groups` | 7 | 2 | 2 | 0 | 0 | 3 | 0 |
| `/site/documents` | 7 | 3 | 2 | 0 | 0 | 4 | 0 |
| `/projects/[id]/whatsapp-checklists` | 6 | 1 | 3 | 0 | 0 | 0 | 0 |
| `/logbooks/hot_work` | 5 | 4 | 0 | 0 | 0 | 3 | 0 |
| `/project/[id]/report-settings` | 5 | 1 | 4 | 0 | 0 | 3 | 0 |
| `/settings` | 5 | 2 | 1 | 0 | 0 | 5 | 0 |
| `/admin/site-devices` | 4 | 4 | 0 | 0 | 0 | 3 | 0 |
| `/logbooks/crane_operations` | 4 | 3 | 0 | 0 | 0 | 3 | 0 |
| `/demo` | 2 | 1 | 1 | 0 | 0 | 3 | 0 |
| `/workers` | 2 | 2 | 0 | 0 | 0 | 3 | 0 |
| `/onboarding` | 1 | 0 | 0 | 0 | 0 | 4 | 0 |
| `/admin/insurance` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/help/faq` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/help/getting-started` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/help` | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| `/help/notifications` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/help/permit-renewal` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/help/troubleshooting` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/` | 0 | 0 | 0 | 0 | 0 | 7 | 0 |
| `/login` | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `/project/[id]/activity` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/project/[id]/defcon` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/project/[id]/notifications` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `/register` | 0 | 0 | 0 | 0 | 0 | 3 | 0 |

### Confirmed breaks, with line numbers

| File | Line | Value | Property | Mode | Reason |
|---|---:|---|---|---|---|

### Colour logic branching on theme inline instead of via a token

| File | Line | Code |
|---|---:|---|
| `app/checkin/[project_id]/[tag_id].jsx` | 547 | `backgroundColor: isDark ? '#1a1f2e' : '#ffffff',` |
| `app/logbooks/index.jsx` | 608 | `const divider = isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.06);` |
| `app/logbooks/index.jsx` | 668 | `backgroundColor: isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.04),` |
| `app/logbooks/index.jsx` | 713 | `badgePending: { backgroundColor: isDark ? withAlpha('#ffffff', 0.06) : withAlpha('#000000', 0.04) },` |
| `app/logbooks/index.jsx` | 727 | `backgroundColor: isDark ? withAlpha('#ffffff', 0.08) : withAlpha('#000000', 0.06),` |
| `app/project/[id]/trades.jsx` | 544 | `backgroundColor: isDark ? '#1a1f2e' : '#ffffff',` |
| `app/projects/index.jsx` | 674 | `backgroundColor: isDark ? '#121826' : '#ffffff',` |

### Screens with no code evidence of dark-mode handling

Criterion: has colour literals AND zero `isDark` references, so nothing in the file adapts those values per theme.

| Route | File | Literals | isDark refs |
|---|---|---:|---:|
| `/settings/notifications` | `app/settings/notifications.jsx` | 26 | 0 |
| `/settings/notifications/project/[project_id]` | `app/settings/notifications/project/[project_id].jsx` | 22 | 0 |
| `/logbooks/review` | `app/logbooks/review.jsx` | 21 | 0 |
| `/owner/pending-deletion` | `app/owner/pending-deletion.jsx` | 8 | 0 |
| `/projects/[id]/whatsapp-checklists` | `app/projects/[id]/whatsapp-checklists.jsx` | 6 | 0 |

## A. Every distinct value, with usage counts

### Colours — 91 distinct, 700 literals

`dark branch` / `light branch` = occurrences inside the two arms of an `isDark ? ... : ...` ternary. Everything else is unbranched (same value in both themes).

| Value | Total | dark branch | light branch |
|---|---:|---:|---:|
| `#ffffff` | 198 | 4 | 3 |
| `#3b82f6` | 91 | 0 | 0 |
| `#fff` | 65 | 0 | 0 |
| `#4ade80` | 36 | 0 | 0 |
| `#94a3b8` | 25 | 0 | 0 |
| `#000000` | 22 | 0 | 4 |
| `#60a5fa` | 16 | 0 | 0 |
| `#8b5cf6` | 16 | 0 | 0 |
| `#64748b` | 13 | 0 | 0 |
| `#f59e0b` | 13 | 0 | 0 |
| `#ef4444` | 11 | 0 | 0 |
| `#f87171` | 11 | 0 | 0 |
| `rgba(59,130,246,0.2)` | 10 | 0 | 0 |
| `#6b7280` | 10 | 0 | 0 |
| `#fbbf24` | 8 | 0 | 0 |
| `#1a1a2e` | 7 | 0 | 0 |
| `rgba(59,130,246,0.15)` | 7 | 0 | 0 |
| `#0061ff` | 6 | 0 | 0 |
| `rgba(59, 130, 246, 0.2)` | 6 | 0 | 0 |
| `rgba(59, 130, 246, 0.1)` | 6 | 0 | 0 |
| `#10b981` | 5 | 0 | 0 |
| `rgba(59,130,246,0.3)` | 5 | 0 | 0 |
| `#93c5fd` | 5 | 0 | 0 |
| `#25d366` | 4 | 0 | 0 |
| `rgba(59, 130, 246, 0.3)` | 4 | 0 | 0 |
| `rgba(59,130,246,0.5)` | 4 | 0 | 0 |
| `#06b6d4` | 4 | 0 | 0 |
| `rgba(59,130,246,0.08)` | 4 | 0 | 0 |
| `#f97316` | 4 | 0 | 0 |
| `rgba(0, 97, 255, 0.1)` | 3 | 0 | 0 |
| `rgba(59, 130, 246, 0.15)` | 3 | 0 | 0 |
| `rgba(59,130,246,0.4)` | 3 | 0 | 0 |
| `rgba(139,92,246,0.2)` | 3 | 0 | 0 |
| `rgba(37, 211, 102, 0.1)` | 2 | 0 | 0 |
| `#9ca3af` | 2 | 0 | 0 |
| `#1a1f2e` | 2 | 2 | 0 |
| `rgba(6,182,212,0.15)` | 2 | 0 | 0 |
| `rgba(6,182,212,0.3)` | 2 | 0 | 0 |
| `#22d3ee` | 2 | 0 | 0 |
| `rgba(59,130,246,0.10)` | 2 | 0 | 0 |
| `rgba(59,130,246,0.1)` | 2 | 0 | 0 |
| `rgba(139,92,246,0.4)` | 2 | 0 | 0 |
| `#3b82f615` | 2 | 0 | 0 |
| `rgba(59, 130, 246, 0.10)` | 2 | 0 | 0 |
| `rgba(59, 130, 246, 0.08)` | 2 | 0 | 0 |
| `rgba(59, 130, 246, 0.12)` | 2 | 0 | 0 |
| `#050a12` | 2 | 0 | 0 |
| `rgba(74,222,128,0.6)` | 1 | 0 | 0 |
| `#f472b6` | 1 | 0 | 0 |
| `rgba(0,0,0,0.92)` | 1 | 0 | 0 |
| `#ec4899` | 1 | 0 | 0 |
| `rgba(6,182,212,0.2)` | 1 | 0 | 0 |
| `rgba(96,165,250,0.15)` | 1 | 0 | 0 |
| `rgba(96,165,250,0.3)` | 1 | 0 | 0 |
| `rgba(96,165,250,0.1)` | 1 | 0 | 0 |
| `rgba(96,165,250,0.25)` | 1 | 0 | 0 |
| `rgba(147,197,253,0.35)` | 1 | 0 | 0 |
| `rgba(147,197,253,0.4)` | 1 | 0 | 0 |
| `rgba(147,197,253,0.3)` | 1 | 0 | 0 |
| `rgba(139,92,246,0.15)` | 1 | 0 | 0 |
| `rgba(139,92,246,0.3)` | 1 | 0 | 0 |
| `#3b82f680` | 1 | 0 | 0 |
| `#dc2626` | 1 | 0 | 0 |
| `#0ea5e9` | 1 | 0 | 0 |
| `#15d` | 1 | 0 | 0 |
| `rgba(37,211,102,0.08)` | 1 | 0 | 0 |
| `rgba(37,211,102,0.2)` | 1 | 0 | 0 |
| `rgba(96, 165, 250, 0.25)` | 1 | 0 | 0 |
| `rgba(96, 165, 250, 0.6)` | 1 | 0 | 0 |
| `rgba(34, 197, 94, 0.18)` | 1 | 0 | 0 |
| `rgba(34, 197, 94, 0.7)` | 1 | 0 | 0 |
| `rgba(234, 179, 8, 0.18)` | 1 | 0 | 0 |
| `rgba(234, 179, 8, 0.7)` | 1 | 0 | 0 |
| `rgba(239, 68, 68, 0.18)` | 1 | 0 | 0 |
| `rgba(239, 68, 68, 0.7)` | 1 | 0 | 0 |
| `rgba(239,68,68,0.1)` | 1 | 0 | 0 |
| `rgba(34,197,94,0.1)` | 1 | 0 | 0 |
| `#3b82f640` | 1 | 0 | 0 |
| `#8b5cf615` | 1 | 0 | 0 |
| `#3b82f610` | 1 | 0 | 0 |
| `#3b82f630` | 1 | 0 | 0 |
| `rgba(0, 97, 255, 0.2)` | 1 | 0 | 0 |
| `#a855f7` | 1 | 0 | 0 |
| `#121826` | 1 | 1 | 0 |
| `rgba(239, 68, 68, 0.10)` | 1 | 0 | 0 |
| `rgba(59, 130, 246, 0.4)` | 1 | 0 | 0 |
| `rgba(239,68,68,0.10)` | 1 | 0 | 0 |
| `rgba(139, 92, 246, 0.2)` | 1 | 0 | 0 |
| `rgba(139,92,246,0.1)` | 1 | 0 | 0 |
| `#c4b5fd` | 1 | 0 | 0 |
| `rgba(59,130,246,0.25)` | 1 | 0 | 0 |

### Font sizes — 21 distinct, 989 uses

| px | Uses |
|---:|---:|
| 9 | 8 |
| 10 | 38 |
| 11 | 110 |
| 12 | 131 |
| 13 | 188 |
| 14 | 199 |
| 15 | 81 |
| 16 | 71 |
| 17 | 17 |
| 18 | 42 |
| 20 | 31 |
| 22 | 16 |
| 24 | 10 |
| 28 | 11 |
| 32 | 10 |
| 36 | 5 |
| 38 | 1 |
| 40 | 1 |
| 42 | 4 |
| 44 | 1 |
| 48 | 14 |

### Border radii — 21 distinct, 88 uses

| px | Uses |
|---:|---:|
| 2 | 3 |
| 3 | 8 |
| 4 | 18 |
| 5 | 5 |
| 6 | 7 |
| 8 | 4 |
| 9 | 2 |
| 10 | 4 |
| 11 | 9 |
| 12 | 8 |
| 13 | 1 |
| 14 | 2 |
| 16 | 2 |
| 18 | 6 |
| 20 | 2 |
| 24 | 2 |
| 28 | 1 |
| 32 | 1 |
| 50 | 1 |
| 60 | 1 |
| 999 | 1 |

### Spacing — 19 distinct, 435 uses

| px | Uses |
|---:|---:|
| 0 | 24 |
| 1 | 8 |
| 2 | 105 |
| 3 | 19 |
| 4 | 102 |
| 5 | 2 |
| 6 | 61 |
| 8 | 36 |
| 10 | 13 |
| 12 | 5 |
| 14 | 6 |
| 16 | 7 |
| 20 | 1 |
| 44 | 1 |
| 60 | 1 |
| 80 | 1 |
| 100 | 4 |
| 120 | 37 |
| 140 | 2 |

### Shadow / elevation — 4 distinct, 4 uses

| Declaration | Uses |
|---|---:|
| `shadowColor: #000000` | 1 |
| `shadowOpacity: 0.35` | 1 |
| `shadowRadius: 12` | 1 |
| `elevation: 8` | 1 |

## B. DEAD screens and duplicates

### DEAD — 15 screens with no navigation path from the running app

| Route | File | Why |
|---|---|---|
| `/admin/insurance` | `app/admin/insurance.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/checkin` | `app/checkin/index.jsx` | appears only in DesktopShell chrome-hiding prefix list; live worker check-in is backend/checkin.html |
| `/checkin/[project_id]/[tag_id]` | `app/checkin/[project_id]/[tag_id].jsx` | same as /checkin; live flow is backend/checkin.html |
| `/checklists` | `app/checklists.jsx` | duplicate of /admin/checklists (only that one is linked) |
| `/documents` | `app/documents.jsx` | appears only in the CP route-guard allow-list (_layout.jsx:226), never navigated to |
| `/help` | `app/help/index.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/help/faq` | `app/help/faq.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/help/getting-started` | `app/help/getting-started.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/help/notifications` | `app/help/notifications.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/help/permit-renewal` | `app/help/permit-renewal.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/help/troubleshooting` | `app/help/troubleshooting.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/nfc` | `app/nfc/index.jsx` | appears only in DesktopShell chrome-hiding prefix list, not a link |
| `/owner` | `app/owner/index.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/owner/pending-deletion` | `app/owner/pending-deletion.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |
| `/project/[id]/audit` | `app/project/[id]/audit.jsx` | no `router.push`/`href`/nav-item reference in `app/` or `src/` |

The six `/help/*` entries are a closed subtree: each leaf is linked from `app/help/index.jsx`, but nothing outside `app/help/` or `src/components/HelpPageShell.jsx` links to `/help` itself, and HelpPageShell's only reference is a `router.replace('/help')` fallback (line 55) that can fire only from inside the subtree.

### Duplicate pairs

| Purpose | Reachable | Other file | Note |
|---|---|---|---|
| Checklists | `app/admin/checklists/index.jsx` | `app/checklists.jsx` | only `/admin/checklists` is linked (`app/index.jsx:46`); `/checklists` is DEAD |
| Documents | `app/site/documents.jsx` | `app/documents.jsx` | `/documents` appears only in the CP route-guard allow-list (`app/_layout.jsx:226`), never navigated to |
| Worker check-in | `backend/checkin.html` (live) | `app/checkin/index.jsx`, `app/checkin/[project_id]/[tag_id].jsx` | both RN screens DEAD; the two `/checkin` strings in `DesktopShell.jsx` are a chrome-hiding prefix list, not links |
| Daily log | `app/site/daily-logs.jsx` (field) | `app/daily-log.jsx` (office) | both reachable, different audiences |
| Logbook list | `app/logbooks/index.jsx` (CP) | `app/site/logbooks.jsx` (kiosk, read-only) | both reachable, different audiences |
| Project view | `app/project/[id].jsx` (detail) | `app/projects/index.jsx` (list) | different trees, both reachable |

## C. Screens ranked worst-first

Score = missing states + tap count + colour-literal count. DEAD excluded.

| # | Route | Score | Missing states | Taps | Literals |
|---:|---|---:|---:|---:|---:|
| 1 | `/site/logbooks` | 46 | 2 | 2 | 42 |
| 2 | `/project/[id]` | 33 | 2 | 2 | 29 |
| 3 | `/settings/notifications` | 33 | 4 | 3 | 26 |
| 4 | `/daily-log` | 31 | 2 | 3 | 26 |
| 5 | `/settings/notifications/project/[project_id]` | 31 | 5 | 4 | 22 |
| 6 | `/logbooks/toolbox_talk` | 29 | 2 | 2 | 25 |
| 7 | `/logbooks/daily_jobsite` | 28 | 2 | 2 | 24 |
| 8 | `/logbooks/osha_log` | 28 | 2 | 2 | 24 |
| 9 | `/project/[id]/dob-logs` | 28 | 3 | 3 | 22 |
| 10 | `/logbooks/scaffold_maintenance` | 26 | 3 | 2 | 21 |
| 11 | `/projects/[id]/construction-plans` | 26 | 2 | 3 | 21 |
| 12 | `/logbooks/review` | 25 | 2 | 2 | 21 |
| 13 | `/site/daily-logs` | 24 | 2 | 2 | 20 |
| 14 | `/logbooks/preshift_signin` | 23 | 3 | 2 | 18 |
| 15 | `/logbooks/subcontractor_orientation` | 23 | 2 | 2 | 19 |
| 16 | `/logbooks` | 22 | 2 | 1 | 19 |
| 17 | `/reports` | 22 | 2 | 2 | 18 |
| 18 | `/site/checkins` | 22 | 0 | 2 | 20 |
| 19 | `/projects` | 21 | 3 | 2 | 16 |
| 20 | `/site` | 20 | 5 | 1 | 14 |
| 21 | `/admin/integrations` | 19 | 3 | 2 | 14 |
| 22 | `/project/[id]/permit-renewal` | 17 | 2 | 4 | 11 |
| 23 | `/workers/[id]` | 17 | 2 | 3 | 12 |
| 24 | `/admin/checklists` | 16 | 2 | 2 | 12 |
| 25 | `/admin/safety-staff` | 15 | 3 | 2 | 10 |
| 26 | `/admin/superintendent` | 15 | 2 | 2 | 11 |
| 27 | `/projects/[id]/dropbox-settings` | 15 | 2 | 3 | 10 |
| 28 | `/admin/users` | 14 | 2 | 2 | 10 |
| 29 | `/logbooks/ssc_daily_safety_log` | 14 | 3 | 2 | 9 |
| 30 | `/project/[id]/trades` | 14 | 2 | 3 | 9 |
| 31 | `/logbooks/concrete_operations` | 13 | 2 | 2 | 9 |
| 32 | `/logbooks/excavation_monitoring` | 13 | 2 | 2 | 9 |
| 33 | `/projects/[id]/whatsapp-checklists` | 13 | 4 | 3 | 6 |
| 34 | `/projects/[id]/whatsapp-groups` | 13 | 3 | 3 | 7 |
| 35 | `/site/documents` | 13 | 4 | 2 | 7 |
| 36 | `/admin/site-devices` | 10 | 4 | 2 | 4 |
| 37 | `/project/[id]/report-settings` | 10 | 2 | 3 | 5 |
| 38 | `/logbooks/hot_work` | 9 | 2 | 2 | 5 |
| 39 | `/project/[id]/notifications` | 9 | 6 | 3 | 0 |
| 40 | `/settings` | 9 | 2 | 2 | 5 |
| 41 | `/demo` | 8 | 4 | 2 | 2 |
| 42 | `/logbooks/crane_operations` | 8 | 2 | 2 | 4 |
| 43 | `/project/[id]/activity` | 8 | 6 | 2 | 0 |
| 44 | `/project/[id]/defcon` | 8 | 5 | 3 | 0 |
| 45 | `/register` | 8 | 5 | 3 | 0 |
| 46 | `/login` | 7 | 5 | 2 | 0 |
| 47 | `/onboarding` | 6 | 5 | — | 1 |
| 48 | `/workers` | 6 | 2 | 2 | 2 |
| 49 | `/` | 4 | 3 | 1 | 0 |

## D. Dark-mode break list, worst first

Ranked by confirmed breaks, then by literals carrying no theme branch.

| # | Route | File | Dark breaks | Light breaks | Status/accent literals | isDark refs |
|---:|---|---|---:|---:|---:|---:|
| 1 | `/project/[id]` | `app/project/[id].jsx` | 0 | 0 | 24 | 3 |
| 2 | `/site/logbooks` | `app/site/logbooks.jsx` | 0 | 0 | 23 | 3 |
| 3 | `/settings/notifications` | `app/settings/notifications.jsx` | 0 | 0 | 18 | 0 |
| 4 | `/logbooks/review` | `app/logbooks/review.jsx` | 0 | 0 | 17 | 0 |
| 5 | `/project/[id]/dob-logs` | `app/project/[id]/dob-logs.jsx` | 0 | 0 | 15 | 3 |
| 6 | `/settings/notifications/project/[project_id]` | `app/settings/notifications/project/[project_id].jsx` | 0 | 0 | 14 | 0 |
| 7 | `/projects/[id]/construction-plans` | `app/projects/[id]/construction-plans.jsx` | 0 | 0 | 13 | 3 |
| 8 | `/site/checkins` | `app/site/checkins.jsx` | 0 | 0 | 13 | 3 |
| 9 | `/reports` | `app/reports.jsx` | 0 | 0 | 12 | 3 |
| 10 | `/daily-log` | `app/daily-log.jsx` | 0 | 0 | 11 | 3 |
| 11 | `/logbooks` | `app/logbooks/index.jsx` | 0 | 0 | 11 | 7 |
| 12 | `/logbooks/osha_log` | `app/logbooks/osha_log.jsx` | 0 | 0 | 11 | 3 |
| 13 | `/logbooks/toolbox_talk` | `app/logbooks/toolbox_talk.jsx` | 0 | 0 | 11 | 3 |
| 14 | `/project/[id]/permit-renewal` | `app/project/[id]/permit-renewal.jsx` | 0 | 0 | 11 | 3 |
| 15 | `/logbooks/subcontractor_orientation` | `app/logbooks/subcontractor_orientation.jsx` | 0 | 0 | 10 | 5 |
| 16 | `/logbooks/scaffold_maintenance` | `app/logbooks/scaffold_maintenance.jsx` | 0 | 0 | 9 | 3 |
| 17 | `/logbooks/preshift_signin` | `app/logbooks/preshift_signin.jsx` | 0 | 0 | 8 | 3 |
| 18 | `/documents` | `app/documents.jsx` | 0 | 0 | 7 | 3 |
| 19 | `/nfc` | `app/nfc/index.jsx` | 0 | 0 | 7 | 3 |
| 20 | `/admin/users` | `app/admin/users.jsx` | 0 | 0 | 6 | 3 |
| 21 | `/checkin` | `app/checkin/index.jsx` | 0 | 0 | 6 | 3 |
| 22 | `/owner/pending-deletion` | `app/owner/pending-deletion.jsx` | 0 | 0 | 6 | 0 |
| 23 | `/project/[id]/audit` | `app/project/[id]/audit.jsx` | 0 | 0 | 6 | 4 |
| 24 | `/projects` | `app/projects/index.jsx` | 0 | 0 | 6 | 4 |
| 25 | `/site` | `app/site/index.jsx` | 0 | 0 | 6 | 3 |
| 26 | `/admin/integrations` | `app/admin/integrations.jsx` | 0 | 0 | 5 | 3 |
| 27 | `/admin/safety-staff` | `app/admin/safety-staff.jsx` | 0 | 0 | 5 | 3 |
| 28 | `/projects/[id]/dropbox-settings` | `app/projects/[id]/dropbox-settings.jsx` | 0 | 0 | 5 | 3 |
| 29 | `/site/daily-logs` | `app/site/daily-logs.jsx` | 0 | 0 | 5 | 3 |
| 30 | `/admin/checklists` | `app/admin/checklists/index.jsx` | 0 | 0 | 4 | 3 |

**Zero literals in the tree are confirmed theme breaks.** Two candidates were examined against source and both were retracted:

- `app/logbooks/daily_jobsite.jsx:1427` `backgroundColor: rgba(0,0,0,0.92)` — the enclosing style key is `lightboxOverlay`, a full-screen photo scrim. Near-black is intended in both themes.
- `app/logbooks/daily_jobsite.jsx:1475` `shadowColor: #000000` — declared alongside `elevation: 8`, so Android still draws a system shadow. Only the iOS shadow loses contrast on the dark background.

The residual risk is entirely the **348 hardcoded status/accent colours**: they render in both themes, but their contrast against each theme background is unverified. Static analysis cannot settle that — it needs a visual pass. The table above ranks screens by how many such literals they carry, which is the order a visual check would follow.

