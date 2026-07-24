# UI Inventory & Structural Audit — 2026-07-23

Repo: BLUEVIEW-APP (Expo / React Native, RN-Web on Vercel). Router: expo-router
file-based, single `<Stack>` navigator ([app/_layout.jsx:262](../../frontend/app/_layout.jsx)).
Role gating is centralized in `RouteGuard` ([app/_layout.jsx:150-239](../../frontend/app/_layout.jsx)),
not per-screen. Facts and locations only; no recommendations.

Scope: 66 route files under `frontend/app/`. All paths below are relative to
`frontend/`.

---

## Summary table

`desktop-safe?` = No means: single-column-stack or card-list that renders on
web at ≥1024px with no width breakpoint. `missing` = which of loading/empty/error
states were not found.

| Screen | Layout primitive | Desktop-safe? | Missing states | Issues |
|---|---|---|---|---|
| index (home / project list) | single-column-stack | No | — | 3 |
| projects/index | single-column-stack + modal | No | — | 2 |
| project/[id] | single-column-stack + modal | No | — | 5 |
| project/[id]/dob-logs | single-column-stack (tabs) | No | — | 4 |
| project/[id]/defcon | single-column-stack | No | — | 1 |
| project/[id]/activity | single-column-stack | No | empty, error | 1 |
| project/[id]/audit | single-column-stack | No | — | 0 |
| project/[id]/notifications | single-column-stack | No | empty, error | 1 |
| project/[id]/permit-renewal | single-column-stack | No | — | 1 |
| project/[id]/trades | form | No | — | 1 |
| project/[id]/report-settings | form | No | — | 0 |
| projects/[id]/construction-plans | single-column-stack + form | No | — | 1 |
| projects/[id]/dropbox-settings | single-column-stack | No | — | 1 |
| projects/[id]/whatsapp-groups | list + modal + form | No | — | 1 |
| projects/[id]/whatsapp-checklists | single-column-stack | No | — | 0 |
| workers | single-column-stack | No | error | 1 |
| workers/[id] | single-column-stack + modal + form | No | — | 2 |
| checkin/index | single-column-stack | No | — | 1 |
| checkin/[project_id]/[tag_id] | form + modal | Both* | — | 1 |
| checklists | single-column-stack + modal + form | No | — | 1 |
| daily-log | single-column-stack + modal + form | No | — | 1 |
| documents | single-column-stack | No | — | 1 |
| reports | single-column-stack | No | — | 1 |
| logbooks/index | single-column-stack | No | — | 1 |
| logbooks/review | single-column-stack + modal | No | — | 0 |
| logbooks/* (10 form screens) | form | No | (2 missing empty) | 0 |
| settings | single-column-stack | No | — | 0 |
| settings/notifications | single-column-stack | Yes (breakpoint) | — | 0 |
| settings/notifications/project/[project_id] | single-column-stack | Yes (breakpoint) | — | 0 |
| admin/users | single-column-stack | No | — | 2 |
| admin/checklists/index | single-column-stack + modal + form | No | — | 1 |
| admin/safety-staff | single-column-stack + modal | No | — | 2 |
| admin/site-devices | single-column-stack + modal | No | — | 2 |
| admin/superintendent | single-column-stack + modal | No | — | 2 |
| admin/integrations | single-column-stack + form | No | — | 1 |
| admin/insurance | (redirect → /settings) | n/a | all three | 0 |
| owner/index | single-column-stack + modal | Partial (winHeight only) | — | 3 |
| owner/pending-deletion | single-column-stack + modal + form | No | — | 0 |
| onboarding | single-column-stack | Yes (breakpoint) | — | 0 |
| login / register / demo | single-column-stack | No | (register/demo no empty) | 0 |
| nfc/index | (stack) | No | empty | 1 |
| site/index | single-column-stack | No | empty | 1 |
| site/checkins | single-column-stack | No | — | 2 |
| site/daily-logs | single-column-stack + modal + form | No | — | 0 |
| site/documents | single-column-stack | No | — | 0 |
| site/logbooks | single-column-stack | No | — | 0 |
| help/* (7 screens) | single-column-stack (static) | No | (most static) | 0 |

\* `checkin/[project_id]/[tag_id]` is the in-app Expo mirror of the public
web check-in; the LIVE tag flow is served by `backend/checkin.html`, not this
screen — see "Screens not covered".

---

## PART 1 — Screen inventory

**Navigator:** one `<Stack>` ([_layout.jsx:262](../../frontend/app/_layout.jsx)),
`headerShown: false`. Every route is a stack screen; there is no tab navigator,
drawer, or nested navigator. "Which navigator" is the single root Stack for all
66 routes.

**Role reachability** — enforced centrally in `RouteGuard`
([_layout.jsx:171-236](../../frontend/app/_layout.jsx)):
- `site_device` / `siteMode`: **only** `/site/*` and `/login` ([:194-199](../../frontend/app/_layout.jsx)).
- `cp`: **only** `/logbooks/*`, `/documents`, `/settings`, `/login` ([:202-211](../../frontend/app/_layout.jsx)); a CP with no `company_id` is further contained to `/logbooks`, `/login`, `/settings` ([:216-235](../../frontend/app/_layout.jsx)).
- users mid-onboarding (`onboarding_step ∈ {1,2,3,4}`) are forced to `/onboarding` ([:182-191](../../frontend/app/_layout.jsx)).
- `admin` / `owner`: **no path restriction in RouteGuard** — every non-site, non-cp route is reachable.

**Per-screen gates found _inside_ screens** (secondary to RouteGuard) — 20 screens
run a local `isAdmin` / `isOwner` / `role` check:
`admin/*` (checklists, integrations, safety-staff, site-devices, superintendent, users),
`daily-log`, `documents`, `index`, `owner/pending-deletion`, `project/[id]`,
`project/[id]/dob-logs`, `project/[id]/report-settings`, `project/[id]/trades`,
`projects/[id]/construction-plans`, `projects/[id]/dropbox-settings`,
`projects/index`, `reports`, `settings`, `workers/[id]`.
- `owner/pending-deletion` renders an explicit "Owner access required" panel for non-owners ([owner/pending-deletion.jsx:107-128](../../frontend/app/owner/pending-deletion.jsx)); the endpoints behind it are `role:"owner"`-gated server-side.
- The `/admin/*` routes have **no RouteGuard path gate** — an authenticated `cp` is redirected away by the cp rule, but there is no admin-only allowlist; admin-only enforcement is the in-screen `isAdmin` check plus server-side 403s. **Flagged: admin route protection is server-trust + in-screen, not router-enforced.**

**Web/native:** all screens render on both (RN-Web). Platform branches are
cosmetic (`KeyboardAvoidingView behavior`, monospace font family, `window.confirm`
vs `Alert.alert`) — see Part 6. No screen is web-only or native-only except the
public check-in, which lives in `backend/checkin.html` (not in this app tree).

**Information density (distinct data fields in default viewport)** — approximate,
highest-density screens:
- `project/[id]` — ~15+: 3 stat tiles (ON SITE / NFC TAGS / DEVICES, [project/[id].jsx:642-662](../../frontend/app/project/[id].jsx)), DEFCON header, compliance forecast, WhatsApp group+message counts ([:737](../../frontend/app/project/[id].jsx)), file count ([:925](../../frontend/app/project/[id].jsx)), per-company worker counts ([:959](../../frontend/app/project/[id].jsx)), checklist progress rows ([:1023-1053](../../frontend/app/project/[id].jsx)), activity feed, notifications inline.
- `project/[id]/dob-logs` — 4 tab counts + per-record cards (~8 fields each): [dob-logs.jsx:173-176](../../frontend/app/project/[id]/dob-logs.jsx).
- `owner/index` — company list + admin list + filing-reps, multiple modals.
- `workers/[id]` — name/trade/company/OSHA#, OCR card fields (name/OSHA#/SST#/trade/expires/provider, [workers/[id].jsx:391-421](../../frontend/app/workers/[id].jsx)), safety orientations, certifications list.
- Lowest density: help/* (static prose), login/register, `admin/insurance` (redirect, 0 fields).

**Missing states** — from the sweep (Y=present, blank=missing):
- `admin/insurance` — redirect stub, none of the three ([admin/insurance.jsx:1-12](../../frontend/app/admin/insurance.jsx)).
- `project/[id]/activity` — no empty, no error ([project/[id]/activity.jsx](../../frontend/app/project/[id]/activity.jsx)).
- `project/[id]/notifications` — no empty, no error.
- `workers` — no explicit error state.
- `logbooks/scaffold_maintenance`, `logbooks/toolbox_talk` — no empty state.
- `nfc/index`, `site/index`, `login`, `register`, `demo` — no empty state (mostly action screens).

**Reachable from >1 entry point** — the router.push target frequency shows
duplicate entries for `/` (12 pushes), `/projects` (8), `/logbooks` (8),
`/site` (4), `/settings` (3), `/project` (3). Screens reachable from multiple
places include: `/logbooks` (from home, project page, and RouteGuard fallback),
`/settings` (home, RouteGuard cp-fallback, admin/insurance redirect),
project detail (home list + projects/index). Deep detail screens (`workers/[id]`,
`project/[id]/dob-logs`, `logbooks/*` forms) are single-entry.

---

## PART 2 — Layout primitives

**Every list in the app is a `.map()` inside a `ScrollView` — there is no
`FlatList`/`SectionList` anywhere** (grep for `FlatList|SectionList` across
`app/` = 0 matches). Consequently every list screen is a `single-column-stack`,
not a virtualized `list`. The only screens using `FlatList`-style semantics are
labeled "list" heuristically where a large `.map` dominates.

**Layout classification:** ~48 screens `single-column-stack`; 13 add a `modal`
(admin CRUD + owner + project + review); ~14 are primarily `form` (all 10 logbook
capture screens, trades, report-settings, construction-plans, check-in). **Zero
`table` primitives** — tabular data (users, devices, dob-logs, workers) is
rendered as stacked cards.

**Desktop breakpoint candidates (single-column-stack / card-list on web ≥1024px
with NO width logic):** essentially all non-settings screens. High-value ones:
`index`, `projects/index`, `project/[id]`, `project/[id]/dob-logs`, `workers`,
`workers/[id]`, `admin/users`, `admin/site-devices`, `admin/safety-staff`,
`admin/superintendent`, `reports`, `documents`, `owner/index`, `site/checkins`.

**Responsive logic that exists today** (the complete set):

| Kind | file:line | What it does |
|---|---|---|
| `useWindowDimensions` (width breakpoint) | [settings/notifications.jsx:323-324](../../frontend/app/settings/notifications.jsx) | `isMobile = winWidth < 720` (`MOBILE_BREAKPOINT` [:143](../../frontend/app/settings/notifications.jsx)) |
| `useWindowDimensions` (width breakpoint) | [settings/notifications/project/[project_id].jsx:244-245](../../frontend/app/settings/notifications/project/[project_id].jsx) | `isMobile = winWidth < 720` ([:117](../../frontend/app/settings/notifications/project/[project_id].jsx)) |
| `Dimensions.get().width` (width breakpoint) | [onboarding.jsx:139-140](../../frontend/app/onboarding.jsx) | `isMobile = screenWidth < 768` ([:77](../../frontend/app/onboarding.jsx)) |
| `useWindowDimensions` (height only) | [owner/index.jsx:140-152](../../frontend/app/owner/index.jsx) | modal scroll `maxHeight` from `winHeight`; `isWeb` gate [:141](../../frontend/app/owner/index.jsx); **no width breakpoint** |
| `useWindowDimensions` (width) | [src/components/ActivityFeed.jsx:501](../../frontend/src/components/ActivityFeed.jsx) | component-level width read |
| `Dimensions.get().width` | [index.jsx:219](../../frontend/app/index.jsx) | read once (non-reactive) |
| `Dimensions.get().width` | [src/components/InfoTooltip.jsx:54](../../frontend/src/components/InfoTooltip.jsx), [RiskScoreDrawer.jsx:270](../../frontend/src/components/RiskScoreDrawer.jsx), [Toast.js:7](../../frontend/src/components/Toast.js), [globalStyles.js:4](../../frontend/src/styles/globalStyles.js), [AnimatedBackground.js:7](../../frontend/src/components/AnimatedBackground.js) | tooltip/toast/gradient sizing |
| `Platform.OS === 'web'` (behavior branch) | 175 total `Platform`/`Dimensions`/`maxWidth` hits across `app` + `src` | mostly `KeyboardAvoidingView`, `window.confirm`, monospace font, download handling |

**Only 3 screens have a width-based responsive breakpoint** (both notification
settings + onboarding, all at 720/768px). `owner/index` adapts height only. Every
other screen is fixed single-column regardless of viewport width. `maxWidth` caps
exist on individual modals/cards (e.g. `maxWidth: 400/440/520`) but there is no
page-level max-width or multi-column reflow anywhere.

---

## PART 3 — Color taxonomy

**Semantic tokens** ([src/styles/theme.js:3-70](../../frontend/src/styles/theme.js)):
`success #4ade80`, `warning #fbbf24`, `error #f87171`, `primary #3b82f6`;
`status.{success,successBg,error,errorBg,warning,warningBg,caution #facc15,
elevated #fb923c}`. Light theme overrides these to darker variants
([theme.js:87-105](../../frontend/src/styles/theme.js)). The 5-tier hazard palette
maps green→success, yellow→caution, amber→warning, orange→elevated, red→error
([theme.js:56-67](../../frontend/src/styles/theme.js)).

**Hardcoded literal frequency (across `app/`):** `#4ade80` ×166, `#f59e0b` ×114,
`#3b82f6` ×98, `#ef4444` ×95, `#22c55e` ×39, `#f87171` ×18, `#8b5cf6` ×17,
`#60a5fa` ×16, `#10b981` ×11, `#dc2626` ×7, `#fbbf24` ×6, `#25d366` ×4 (WhatsApp),
`#0061ff` ×6 (Dropbox), `#f97316` ×4. **Note two greens (`#4ade80` token vs
`#22c55e` literal) and two reds (`#f87171` token, `#ef4444` literal, `#dc2626`
destructive) coexist for the same semantic families.**

**Color → usage → meaning:**

| Color | Used at (sample) | Meaning in context |
|---|---|---|
| `#ef4444` (red) | [admin/checklists/index.jsx:382](../../frontend/app/admin/checklists/index.jsx) Trash2 tint | static delete-icon tint (decorative) |
| `#ef4444` | [admin/safety-staff.jsx:38](../../frontend/app/admin/safety-staff.jsx), [superintendent.jsx:39](../../frontend/app/admin/superintendent.jsx) `major_b` badge | project-class classification "MAJOR B" |
| `#ef4444` | [safety-staff.jsx:294](../../frontend/app/admin/safety-staff.jsx), [safety-staff.jsx:841](../../frontend/app/admin/safety-staff.jsx) | SSM role badge tint |
| `#ef4444` | [daily-log.jsx:372](../../frontend/app/daily-log.jsx) | "unchecked" checklist item state |
| `#ef4444` | [safety-staff.jsx:396](../../frontend/app/admin/safety-staff.jsx), [superintendent.jsx:325](../../frontend/app/admin/superintendent.jsx) AlertTriangle | warning banner |
| `#dc2626` (darker red) | [owner/pending-deletion.jsx](../../frontend/app/owner/pending-deletion.jsx) confirm button | irreversible-delete CTA |
| `#4ade80` (green) | [admin/checklists/index.jsx:308](../../frontend/app/admin/checklists/index.jsx), [integrations.jsx:327](../../frontend/app/admin/integrations.jsx) icons | decorative icon tint |
| `#4ade80` | [checklists/index.jsx:712](../../frontend/app/admin/checklists/index.jsx) checkbox | "checked" state (semantic) |
| `#4ade80` | [site-devices.jsx:235](../../frontend/app/admin/site-devices.jsx) `device.is_active ? '#4ade80' : muted` | live device-active status |
| `#4ade80` | [safety-staff.jsx:291](../../frontend/app/admin/safety-staff.jsx) `let color = '#4ade80'` default | compliance-status default (semantic) |
| `#4ade80` | `RiskScoreCircle` BAND_GREEN | risk band ≤30 **AND null-score fallback** (see Part 4) |
| `#fbbf24`/`#facc15` (amber/yellow) | theme `warning`/`caution` + DOB staleness [CompliancePanel.jsx:616](../../frontend/src/components/CompliancePanel.jsx) | warning / soft-stale |
| `#3b82f6` (blue) | primary buttons, links, DEFCON, icons everywhere | brand/primary action + neutral icon tint |
| `#25d366` | WhatsApp surfaces | brand (decorative) |

**SAME color, different meanings — flagged:**
- **Red (`#ef4444`)** simultaneously encodes: (a) a static delete-icon tint that never changes with state ([checklists/index.jsx:382](../../frontend/app/admin/checklists/index.jsx)); (b) a live "MAJOR B" project-class classification ([safety-staff.jsx:38](../../frontend/app/admin/safety-staff.jsx)); (c) an "unchecked" item state ([daily-log.jsx:372](../../frontend/app/daily-log.jsx)); (d) a role badge (SSM); (e) a warning-severity AlertTriangle. Five distinct meanings, one literal.
- **Green (`#4ade80`)** simultaneously encodes: decorative icon tint, "checked" boolean, "device active" live status, and "compliant" default — plus the risk-band green that also fires when the score is `null` (Part 4).
- **Blue (`#3b82f6`)** is both the primary-action color and a neutral decorative icon tint on non-interactive icons.

**Applied statically regardless of state — flagged:** the Trash2/Delete icon tints
(`#ef4444`) at [checklists/index.jsx:382](../../frontend/app/admin/checklists/index.jsx),
[safety-staff.jsx:459](../../frontend/app/admin/safety-staff.jsx),
[site-devices.jsx:279](../../frontend/app/admin/site-devices.jsx),
[superintendent.jsx:392](../../frontend/app/admin/superintendent.jsx),
[users.jsx:395 region](../../frontend/app/admin/users.jsx) are red at all times —
red here is chrome, not a state signal, yet shares the literal used for live
severity elsewhere.

**Decorative colors also used semantically:** `#4ade80`, `#ef4444`, `#fbbf24`,
`#3b82f6` are each used as both a fixed icon tint (decorative) and as a
state-driven value (semantic) in different screens — the full overlap set is the
four theme status colors plus primary.

---

## PART 4 — State honesty

**CONFIRMED contradiction — RiskScoreCircle renders GREEN for a null score.**
`bandFor(score)`: `if (score == null) return BAND_GREEN`
([src/components/RiskScoreCircle.jsx:69-71](../../frontend/src/components/RiskScoreCircle.jsx)).
The component's own header documents the intent: "No-score-yet: greyed ring +
'—' placeholder … Fetch failure: silent (no scary error UI); falls back to '—'"
([RiskScoreCircle.jsx:17-19](../../frontend/src/components/RiskScoreCircle.jsx)) —
the numeric label is "—", **but the band/color returned for a null score is the
green (reassuring) band**, not a neutral grey token, because `bandFor` maps null
to `BAND_GREEN`. A project with **no computed risk score** and a project with a
**genuinely low (safe) score** resolve to the same green band word/color.

**CompliancePanel is state-honest** — it has 6 explicit states
([CompliancePanel.jsx:39-47, 312-381](../../frontend/src/components/CompliancePanel.jsx)):
flag-off→null, loading, error ("Forecast unavailable"), unavailable ("still being
prepared"), cold_start ("Not enough project history yet"), ready. It never colors
from raw probability (L6), reads the confidence badge server-side (never derives
its own, [:113-137](../../frontend/src/components/CompliancePanel.jsx)), and shows
soft/hard staleness chips when the forecast is >24h/>48h old
([:610-628](../../frontend/src/components/CompliancePanel.jsx)). This is the
counter-example: it cannot show a reassuring verdict while pending.

**Contradictions that can be on screen simultaneously:**
1. **project/[id]** — `RiskScoreCircle` green band (null score) can render in the same viewport as a `CompliancePanel` "Forecast unavailable / still being prepared" line, i.e. "green" next to "we have no data." ([project/[id].jsx] renders both regions.)
2. **project/[id]** — the `ON SITE` stat ([project/[id].jsx:646](../../frontend/app/project/[id].jsx)) reflects live worker count while DEFCON/forecast may be stale (>48h chip) — a "current" number beside an admittedly stale verdict.
3. **dob-logs** — a violation tab count >0 (open exposure) can coexist with a green/absent risk band on the parent project screen, because the risk band's null-fallback is green regardless of the child screen's violation count. The two screens are not cross-checked.
4. **Compliance "Below typical" / "Tracking normal" verdict** ([CompliancePanel.jsx:155,420](../../frontend/src/components/CompliancePanel.jsx)) is a **forecast of future enforcement probability**, not a statement about currently-open violations; it can read reassuring while `dob-logs` shows open violations, because they are independent data sources (prediction cache vs synced records).

**Can a positive state render while the underlying score is null/pending?**
Yes — RiskScoreCircle (null→green band). **While related data shows open
exposure?** Yes — the risk band and the DOB violation counts are independent;
neither gates the other.

---

## PART 5 — Count qualification

Every numeric count found renders a **lifetime, unfiltered total** with no
open/closed or time-window qualifier in the label.

| Count | Source | Open/closed filtered? | Time-window? | Label discloses filter? |
|---|---|---|---|---|
| Violations tab | `allLogs.filter(record_type==='violation'\|\|'swo').length` [dob-logs.jsx:174](../../frontend/app/project/[id]/dob-logs.jsx) | **No** | **No** | **No** — bare count on tab |
| Complaints tab | `.filter(record_type==='complaint').length` [dob-logs.jsx:175](../../frontend/app/project/[id]/dob-logs.jsx) | No | No | No |
| Permits tab | `.filter(record_type==='permit').length` [dob-logs.jsx:173](../../frontend/app/project/[id]/dob-logs.jsx) | No | No | No |
| Inspections tab | `.filter(record_type==='inspection').length` [dob-logs.jsx:176](../../frontend/app/project/[id]/dob-logs.jsx) | No | No | No |
| "N Permits Need Renewal" | `renewablePermits.length` [dob-logs.jsx:823-828](../../frontend/app/project/[id]/dob-logs.jsx) | partial (renewal-eligible) | expiring/expired sub-filters [:212-216](../../frontend/app/project/[id]/dob-logs.jsx) | partial — "Need Renewal" implies it |
| ON SITE workers | `workers.length` from active check-ins [project/[id].jsx:261,646](../../frontend/app/project/[id].jsx) | n/a (active only) | today (active check-ins) | No — label is just "ON SITE" |
| NFC TAGS | `nfcTags.length` [project/[id].jsx:653](../../frontend/app/project/[id].jsx) | No (incl. deactivated?) | No | No |
| DEVICES | `siteDevices.length` [project/[id].jsx:660](../../frontend/app/project/[id].jsx) | No | No | No |
| WhatsApp "N messages" | `reduce(message_count)` [project/[id].jsx:737](../../frontend/app/project/[id].jsx) | No | No | No |
| FILES (N) | `dropboxFiles.length` [project/[id].jsx:925](../../frontend/app/project/[id].jsx) | No | No | No |
| Per-company worker count | `company.workers.length` [project/[id].jsx:959](../../frontend/app/project/[id].jsx) | No | No | No |
| Checklist progress `completed/total` | assignment progress [project/[id].jsx:1032,1053](../../frontend/app/project/[id].jsx) | n/a | No | discloses (fraction) |
| site/checkins TOTAL / ON-SITE | `checkins.length` / `!check_out_time` [site/checkins.jsx](../../frontend/app/site/checkins.jsx) | ON-SITE yes | today | partial |

**Flagged — unfiltered and undisclosed:** the four DOB tab counts (violations,
complaints, permits, inspections) are **all-time totals of every synced record of
that type**, including closed/resolved/dismissed. A "Violations 12" tab does not
mean 12 open violations. `NFC TAGS`, `DEVICES`, `messages`, `FILES`, and
per-company worker counts are likewise raw array lengths with no state or window
qualifier in the label.

---

## PART 6 — Destructive actions

| Action | file:line | Confirmation | Soft/Hard | Audit record | Layout position |
|---|---|---|---|---|---|
| Delete checklist | [admin/checklists/index.jsx:268-271](../../frontend/app/admin/checklists/index.jsx) | Yes — custom modal ([:634-656](../../frontend/app/admin/checklists/index.jsx)) | server-defined | server-side | card trailing Trash icon [:379](../../frontend/app/admin/checklists/index.jsx) |
| Delete safety-staff reg | [admin/safety-staff.jsx:227-243](../../frontend/app/admin/safety-staff.jsx) | Yes — `window.confirm` (web) / `Alert.alert` (native) [:228-232](../../frontend/app/admin/safety-staff.jsx) | server | server | row Trash icon [:455](../../frontend/app/admin/safety-staff.jsx) |
| Delete site device | [admin/site-devices.jsx:149-162](../../frontend/app/admin/site-devices.jsx) | Yes — confirm/Alert [:151-154](../../frontend/app/admin/site-devices.jsx) | **hard** (`DELETE /api/admin/site-devices/{id}` [:57](../../frontend/app/admin/site-devices.jsx)) | server | card action [:280](../../frontend/app/admin/site-devices.jsx) |
| Delete superintendent reg | [admin/superintendent.jsx:229-247](../../frontend/app/admin/superintendent.jsx) | Yes — confirm/Alert [:231-236](../../frontend/app/admin/superintendent.jsx) | server | server | row Trash [:388](../../frontend/app/admin/superintendent.jsx) |
| Delete user | [admin/users.jsx:172-197](../../frontend/app/admin/users.jsx) | Yes — `window.confirm` / `Alert.alert` [:191-197](../../frontend/app/admin/users.jsx) | soft (server `is_deleted`) | server | card Trash [:395](../../frontend/app/admin/users.jsx) |
| Delete company (owner) | [owner/index.jsx:447-461](../../frontend/app/owner/index.jsx) | Yes — Alert [:403-459](../../frontend/app/owner/index.jsx) | server | server | modal/list action |
| Delete admin (owner) | [owner/index.jsx:70,473-478](../../frontend/app/owner/index.jsx) | Yes — Alert | server | server | list action |
| Delete filing-rep (owner) | [owner/index.jsx:94](../../frontend/app/owner/index.jsx) | (Alert path) | server | server | list action |
| **Mark project for deletion** | admin delete → `projectsAPI.delete` [projects/index.jsx:135](../../frontend/app/projects/index.jsx) | Alert confirm | **soft** (Tier 1 flag) + deactivates NFC tags | `project_mark_delete` audit | project card |
| **Hard-delete project** | `projectsAPI.hardDelete` [owner/pending-deletion.jsx](../../frontend/app/owner/pending-deletion.jsx) | Yes — **type-the-name** confirm modal | **hard** (owner-only cascade) | `project_hard_delete` audit | owner Pending-Deletion screen |
| Delete NFC tag | `projectsAPI.deleteNfcTag` [project/[id].jsx:383](../../frontend/app/project/[id].jsx) | (inline) | server | server | project detail |
| Delete worker | (workers/[id]) | modal | soft (server) | server | worker detail |
| Deactivate NFC tags (bulk) | side-effect of mark-delete (server `nfc_tags` → `project_closed`) | via mark confirm | soft (status flip) | in mark audit | n/a (server) |

**Observations:** every user-facing destructive action has a confirmation step.
Two confirmation idioms coexist (`window.confirm`/`Alert.alert` split on
`Platform.OS`, and custom modals). The strongest gate (type-the-project-name) is
only on the owner hard-delete. Audit records are written server-side for the
project mark/hard-delete and via `audit_log` on several endpoints; the audit
trail is **viewable** only at `project/[id]/audit` (see Part 8).

---

## PART 7 — Redundancy

**Same field rendered more than once in a viewport:**
- `project/[id]` — worker counts appear as the `ON SITE` stat tile ([:646](../../frontend/app/project/[id].jsx)) **and** again per-company as `company.workers.length` ([:959](../../frontend/app/project/[id].jsx)) in the same scroll; the on-site total and the sum of company rows represent the same underlying check-in set.
- `project/[id]` — `dob_link` "View on DOB BIS" button is rendered in **five** separate record-card branches ([dob-logs.jsx:392,496,614,664,706](../../frontend/app/project/[id]/dob-logs.jsx)) — same control repeated per record type rather than shared.

**Empty states communicating the same absence in >1 sentence:**
- `dob-logs` empty tab: "No records of this type. Tap another tab to see the rest." ([dob-logs.jsx:961](../../frontend/app/project/[id]/dob-logs.jsx)) — two clauses for one absence.
- `logbooks/index`: "All caught up! No logbooks needed right now." ([logbooks/index.jsx:404](../../frontend/app/logbooks/index.jsx)) — reassurance + absence in one line (two statements).

**Primary CTA is a manual refresh/sync:**
- `documents` — the header primary control is a manual `RefreshCw` button ([documents.jsx:351-352](../../frontend/app/documents.jsx), handler [:159](../../frontend/app/documents.jsx)).
- `admin/integrations` — `RefreshCw` action button ([integrations.jsx:528](../../frontend/app/admin/integrations.jsx)).
- `logbooks/review`, `owner/pending-deletion`, `admin/users`, `workers`, `site/checkins` — pull-to-refresh `RefreshControl` is the primary data-update affordance ([logbooks/review.jsx:29](../../frontend/app/logbooks/review.jsx), [owner/pending-deletion.jsx:23](../../frontend/app/owner/pending-deletion.jsx), [admin/users.jsx:107](../../frontend/app/admin/users.jsx)).
- `site/checkins` — a `RefreshCw` icon button is the title-row action.

---

## PART 8 — Missing admin surfaces

| Surface | Present? | Evidence |
|---|---|---|
| Audit log view | **Yes (per-project only)** | `project/[id]/audit.jsx` exists; no global/company-wide audit view found. |
| Bulk selection on any list | **No** | grep for `selectedIds\|selectAll\|multiSelect\|toggleSelect` across `app/` = 0 matches. No list supports multi-select. |
| System / sync health view | **Partial** | Per-integration sync status only: `projects/[id]/construction-plans` and `projects/[id]/dropbox-settings` show `last_sync`/health for that connector. No global sync-health / DOB-poller status screen. |
| Per-object permission visibility | **No** | No screen renders who-can-access an object; permissions are implicit in RouteGuard + server 403s. |
| Sort controls on any list | **No (user-facing)** | `sort` matches are `Array.sort()` in code (dob-logs, whatsapp-checklists, site/logbooks); no user-facing sort control (no sort dropdown/toggle) found. |
| Filter controls on any list | **Partial** | Tab filters on `dob-logs` (record-type tabs) and `reports`/`site/daily-logs`/`site/logbooks` (date/type). No status (open/closed) or free-text filter on any list. |

---

## Screens not covered / could not statically resolve

- **Public NFC check-in flow** — the LIVE worker check-in served on a tag tap is `backend/checkin.html` (a standalone HTML page served by the API), **not** an Expo route. `app/checkin/[project_id]/[tag_id].jsx` is an in-app mirror that is route-shadowed by the Vercel rewrite of `/checkin/*` to the API. Density/state analysis above is for the Expo screen only; the live HTML page is outside `frontend/app/`.
- **Feature-flagged components** — `CompliancePanel` and `RiskScoreCircle` gate on `useFeatureFlag('pr15d_prediction')` / `useFeatureFlag('v2_risk_score')` and return `null` when off ([CompliancePanel.jsx:264,313](../../frontend/src/components/CompliancePanel.jsx), [RiskScoreCircle.jsx:82](../../frontend/src/components/RiskScoreCircle.jsx)). Their on-screen presence depends on runtime flag state that cannot be resolved statically; the audit assumes flags ON.
- **Dynamic routes** — `project/[id]`, `projects/[id]/*`, `workers/[id]`, `checkin/[project_id]/[tag_id]`, `settings/notifications/project/[project_id]` render per-record; field counts are representative, not exhaustive per data instance.
- **`admin/insurance`** — resolves to a redirect to `/settings` ([admin/insurance.jsx:8](../../frontend/app/admin/insurance.jsx)); it has no UI of its own.
- **Information-density counts** are approximate (visual field counting from source), not measured against a rendered viewport at a fixed width.
- **Conditionally-mounted regions** on `project/[id]` (WhatsApp block, Dropbox files, checklist assignments, DEFCON header) render only when the corresponding data/integration is present; the density figure assumes all are active.

---

## Follow-ups (appended 2026-07-23)

Observations surfaced while fixing the risk-score band defaults. Recorded, not
fixed.

- **`score_band` has zero production callers.** The backend
  `lib/statistical_engine/schema.py::score_band` (green/yellow/orange/red band
  thresholds) is invoked only by tests; the frontend
  `RiskScoreCircle.bandFor` **independently reimplements the same [30, 60, 80]
  thresholds in JS**. One business rule, two implementations, neither aware of
  the other — they can silently drift.
- **Three parallel severity vocabularies exist, with no shared taxonomy:**
  `score_band` (`green` / `yellow` / `orange` / `red`), `defcon.py` tiers, and
  `hazard_ratio_to_color_tier` (`green` / `yellow` / `amber` / `orange` /
  `red` / `neutral`). **"orange" and "amber" both appear and mean different
  things in different systems.**
- **No JS test runner exists across the 66 frontend routes** (no jest/vitest,
  no `test` script, no `*.test.*` files). Component/logic changes cannot be
  unit-tested in the repo's normal flow; the risk-score band fix required a
  hand-rolled `node` harness that extracts and evals the real function.
- **`test_v2_2_schema_scaffolding.py` asserts on JS source text by regex** —
  pinning the `[30, 60, 80]` cutoffs and the presence of `useFeatureFlag()`
  inside `RiskScoreCircle.jsx` from a Python test. Fragile cross-language
  coupling: an unrelated frontend refactor (renaming a variable, reordering
  the guards, changing formatting) can turn CI red in a backend test file with
  no backend change.

## Follow-ups (appended 2026-07-24 — desktop projects table)

Surfaced while building the desktop `ProjectsTable`. Recorded, not fixed.

- **`dob_logs` has no DOB hazard-class field.** Violation records carry
  `violation_category`, `violation_type` and `violation_subtype`
  (`SWO_FULL` / `VACATE_*` / `COMM_ORDER` / `ECB` / `NOV`), but **none maps to
  DOB hazard class 1/2/3**. Any UI that wants to surface a "violation class"
  (e.g. a column reading `1 open — DOB cl.2`) needs that mapping resolved
  first — either a field derived at ingestion or a documented decision that
  `violation_subtype` is the closest available proxy.
- **No DOB sync timestamp is written to project docs.** There is no
  `last_dob_sync`-style field anywhere on `projects`; the only `last_synced`
  in the codebase belongs to `db.gc_licenses`. `bbl_last_synced` is a
  **creation-time address→BBL lookup**, not a sync, and `updated_at` changes
  on any write. A "last synced" column or freshness chip therefore requires a
  **new field written by the sync job** — it cannot be derived from the
  current project payload.
- **The desktop projects table fetches risk scores N+1.** `GET /api/projects`
  carries no score, so `ProjectsTable` issues one
  `GET /api/projects/{id}/risk-score` per row. Fine at single-digit project
  counts; past ~20 projects this needs the server-side **dob-summary
  aggregation** (one request returning score + open-violation +
  expiring-permit counts per project), which would also unblock the
  Violations and Permits columns deferred from that PR.
