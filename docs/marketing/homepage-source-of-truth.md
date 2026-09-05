# Homepage source of truth

Evidence document for a marketing homepage. Every factual line carries a
`path:LINE` citation. Lines without a citation are structural (headings, column
labels, method statements).

This is **not** copy. No adjective in this document describes the product.

---

## SECTION 0. TREE PROVENANCE

| Field | Value |
|---|---|
| Audited SHA | `94f89d9971c5891b0fc883206dcea6faac753b14` |
| Branch | `main`, equal to `origin/main` at audit time |
| Commit date | 2026-09-05 11:23:35 -0400 |
| Commit subject | the comment about break-inside was never true, and now a test says so (#438) |
| Worktree | clean (`git status --short` empty) |
| Audit date | 2026-09-05 |

`git fetch origin` was run; `git rev-parse HEAD` and `git rev-parse origin/main`
were identical, so no `git reset --hard` was performed and local `main` carried
no commits `origin/main` lacked.

### Excluded delta

`af67bcf474a2b24373b8b3ecadd888d00f1404a9` — branch
`fix/combined-report-shell-rows`, one commit ahead of the audited SHA.
**Excluded from this audit.**

```
commit af67bcf474a2b24373b8b3ecadd888d00f1404a9
Author: rfs2671 <rfs2671@gmail.com>
Date:   Sat Sep 5 04:00:13 2026 -0400

    the cover page was the roster rule applied to the whole document

 backend/server.py                               |  37 +++-
 backend/tests/test_report_cover_is_not_blank.py | 252 ++++++++++++++++++++++++
 2 files changed, 279 insertions(+), 10 deletions(-)
```

### Cross-reference: excluded-delta files cited in A, B, F, M

`backend/server.py` **is cited** in sections A, F and M.
`backend/tests/test_report_cover_is_not_blank.py` is not cited anywhere in this
document.

Because `af67bcf4` adds 37 lines and removes 10 in `backend/server.py`, **every
`backend/server.py:LINE` citation in this document is line-shifted if that commit
lands**, and the citations touching the combined report's print stylesheet are
also **content**-affected. Those are marked inline as `STALE-IF-af67bcf4-LANDS`.
Citations to other files are unaffected.

### Concurrent modification during the audit — disclosed

The working tree was **modified by another process while this audit was running**.
Two files that were clean at checkout became dirty mid-session:

| File | Change | Working-tree mtime |
|---|---|---|
| `backend/server.py` | one insertion of 84 lines at line 15820, plus an earlier ~17-line insertion in the combined-report region | 2026-09-05 12:00:33 |
| `backend/lib/logbook/ll196.py` | a refactor extracting `roster_for_window` out of `_roster_for_period` | 2026-09-05 12:01:31 |

Neither change was made by this audit, which is read-only on product code. Both
remain uncommitted and are **not** part of the commit that carries this document.

**Consequence, and what was done about it.** Some `backend/server.py` line numbers
were gathered before those edits landed and some after, so a subset of citations
initially recorded the dirty working tree rather than the audited SHA. **Every one
of the 209 distinct `backend/server.py` citations in this document was
subsequently re-resolved against `git show 94f89d99:backend/server.py`** and
corrected where it disagreed. 34 citations and 7 line ranges were corrected this
way. All citations in this document are line numbers **in the audited SHA**, not
in the current working tree.

Citations to every other file were unaffected — no other tracked file changed
during the audit.

### `origin/main` advanced during the audit — and the excluded delta has LANDED

By the time this document was committed, `origin/main` had moved three commits
past the audited SHA:

| Commit | Subject |
|---|---|
| `22d3f86a` | the cover page was the roster rule applied to the whole document (#442) |
| `a042a33b` | nine editors kept the predicate the shared rule was written to replace (#441) |
| `108c0612` | a mechanism is not an incident, and a count is not a description of a set (#443) |

**`22d3f86a` is `af67bcf4` — the excluded delta — squash-merged.** The eight
`STALE-IF-af67bcf4-LANDS` markers in this document are therefore no longer
hypothetical: that change is now on `main`.

This document's evidence basis remains `94f89d99`, because that is the tree that
was actually read and against which every citation was verified. It is not
retro-fitted to a SHA that was not audited.

**179 of the 209 `backend/server.py` citations are still valid verbatim at
`108c0612`.** The 30 that moved are all in the combined-report region those
commits touched, and they convert as follows:

| At `94f89d99` (as cited here) | At `108c0612` | | At `94f89d99` | At `108c0612` |
|---|---|---|---|---|
| 31060 | 31059 | | 35792 | 35809 |
| 31063 | 31062 | | 35794 | 35811 |
| 31070 | 31069 | | 35796 | 35813 |
| 31084 | 31083 | | 35805 | 35822 |
| 31129 | 31146 | | 35869 | 35886 |
| 31162 | 31179 | | 35885 | 35902 |
| 31171 | 31188 | | 36071 | 36088 |
| 31201 | 31218 | | 37199 | 37216 |
| 31213 | 31230 | | 40369 | 40386 |
| 32302 | 32319 | | 40750 | 40767 |
| 32321 | 32338 | | 41526 | 41543 |
| 32324 | 32341 | | 41533 | 41550 |
| 32325 | 32342 | | 42344 | 42361 |
| 32356 | 32373 | | 42744 | 42761 |
| 32889 | 32906 | | 44031 | 44048 |

The shift is uniform +17 except for the four lines inside the print stylesheet
itself (31060, 31063, 31070, 31084), which were edited in place and move −1.
Citations to files other than `backend/server.py` are unaffected by all three
commits except where noted: `a042a33b` also touched eleven
`frontend/app/logbooks/*.jsx` editors and
`frontend/app/logbooks/site_superintendent_log.jsx`, so the two line numbers
cited for that file in H.4 and D.2 should be re-checked before use.

---

## SECTION A. BRAND TOKEN EXTRACTION

### A.1 Method and scope

There is **no Tailwind or NativeWind config in the tree** — `git ls-files`
matching `tailwind|nativewind` returns nothing. Colour comes from three JS
modules plus four inline HTML stylesheets in the backend.

Colour literals were extracted from `frontend/src/styles/theme.js`,
`frontend/src/styles/tokens.js`, `frontend/src/styles/semanticColors.js`,
`frontend/app.json` and `backend/server.py`: **414 occurrences of 70 distinct
6-digit hexes**. Three-digit matches were discarded after inspection — `#15D`,
`#295`, `#252`, `#371` are PR references, not colours (`backend/server.py:8188`,
`:5633`, `:2794`, `:25303`).

### A.2 Application theme — the two palettes

`frontend/src/styles/theme.js` declares two complete palettes and mutates one
live `colors` object between them (`theme.js:231-236`). **Dark is the default**
(`theme.js:232`).

| Token | Dark hex | Light hex | file:line (dark / light) |
|---|---|---|---|
| `primary` | `#3b82f6` | `#1565C0` | theme.js:6 / theme.js:109 |
| `success` | `#4ade80` | `#2E7D32` | theme.js:3 / theme.js:106 |
| `warning` | `#fbbf24` | `#E65100` | theme.js:4 / theme.js:107 |
| `error` | `#f87171` | `#C62828` | theme.js:5 / theme.js:108 |
| `background.start` | `#050a12` | `#d0dcf0` | theme.js:9 / theme.js:112 |
| `background.middle` | `#0A1929` | `#D6E4F7` | theme.js:10 / theme.js:113 |
| `background.end` | `#050a12` | `#ccd8ee` | theme.js:11 / theme.js:114 |
| `text.primary` | `rgba(255,255,255,0.9)` | `#0A1929` | theme.js:37 / theme.js:141 |
| `state.attention` | `#fbbf24` | `#7A5300` | theme.js:55 / theme.js:161 |
| `state.critical` | `#ef4444` | `#C62828` | theme.js:56 / theme.js:162 |
| `state.criticalText` | `#f87171` | `#B91C1C` | theme.js:57 / theme.js:163 |
| `state.criticalFill` | `#dc2626` | `#B91C1C` | theme.js:58 / theme.js:164 |
| `state.verified` | `#22c55e` | `#166534` | theme.js:59 / theme.js:165 |
| `status.caution` | `#facc15` | `#FFD54F` | theme.js:83 / theme.js:186 |
| `status.elevated` | `#fb923c` | `#EF6C00` | theme.js:85 / theme.js:188 |
| `white` | `#ffffff` | `#ffffff` | theme.js:89 / theme.js:192 |
| `iconPod.iconColor` | `rgba(255,255,255,0.6)` | `#1565C0` | theme.js:65 / theme.js:171 |

The light palette is labelled **"Blueview — exact CSS spec"** (`theme.js:93`) —
see Section C.

Contrast ratios are recorded per token in the source and were not re-measured
here: dark `state.*` at `theme.js:55-59`, light at `theme.js:161-165`,
`text.muted` rationale at `theme.js:39-45`.

### A.3 The pinned "outdoor" palette

A third, non-switching palette exists for CP screens used in sunlight
(`theme.js:284-324`). It is a frozen copy of the light values, deliberately not
read from `colors` (`theme.js:265-274`), and the copy is asserted against
`_light` by `frontend/src/styles/outdoorMatchesLight.test.cjs` (`theme.js:278`).

| Token | Hex / value | file:line |
|---|---|---|
| `backgroundStart` | `#d0dcf0` | theme.js:286 |
| `backgroundMiddle` | `#D6E4F7` | theme.js:287 |
| `backgroundEnd` | `#ccd8ee` | theme.js:288 |
| `cardTop` | `rgba(255,255,255,0.92)` | theme.js:292 |
| `cardBottom` | `rgba(219,234,254,0.65)` | theme.js:293 |
| `surfaceSunk` | `rgba(219,234,254,0.45)` | theme.js:295 |
| `surface` | `rgba(255,255,255,0.85)` | theme.js:297 |
| `surfaceSelected` | `#1565C0` | theme.js:298 |
| `text` | `#0A1929` | theme.js:300 |
| `textSoft` | `rgba(10,25,41,0.75)` | theme.js:301 |
| `textDim` | `rgba(10,25,41,0.65)` | theme.js:302 |
| `line` | `rgba(191,219,254,0.60)` | theme.js:307 |
| `lineStrong` | `rgba(147,197,253,0.70)` | theme.js:308 |
| `accent` | `#60a5fa` | theme.js:311 |
| `warnBg` / `warnBorder` / `warn` | `#fef3c7` / `#d97706` / `#92400e` | theme.js:315-317 |
| `danger` | `#b91c1c` | theme.js:318 |
| `okBg` / `okBorder` / `ok` | `#dcfce7` / `#15803d` / `#166534` | theme.js:319-321 |
| `scrim` | `rgba(10,25,41,0.72)` | theme.js:323 |

### A.4 The measured CP palette

`frontend/src/styles/tokens.js` is a *measured* scale — every value is a literal
that ships, counted across 16 CP screens (`tokens.js:1-13`).

| Key | Hex | Uses / files | file:line |
|---|---|---|---|
| `blue500` | `#3b82f6` | 6 uses, 2 files | tokens.js:77 |
| `blue300` | `#93c5fd` | 8 uses, 2 files | tokens.js:78 |
| `white` | `#fff` | 2 uses, 2 files | tokens.js:79 |
| `blue400` | `#60a5fa` | 5 uses, 2 files | tokens.js:80 |
| `amber400` | `#fbbf24` | 4 uses, 2 files | tokens.js:81 |
| `green400` | `#4ade80` | 3 uses, 1 file | tokens.js:82 |
| `red400` | `#f87171` | 3 uses, 2 files | tokens.js:83 |
| `gray500` | `#6b7280` | 2 uses, 1 file | tokens.js:84 |
| `violet500` | `#8b5cf6` | 2 uses, 2 files | tokens.js:85 |
| `cyan500` | `#06b6d4` | 1 use, 1 file | tokens.js:86 |
| `emerald500` | `#10b981` | 1 use, 1 file | tokens.js:87 |
| `slate400` | `#94a3b8` | 1 use, 1 file | tokens.js:88 |
| `pink400` | `#f472b6` | 1 use, 1 file | tokens.js:89 |
| `amber500` | `#f59e0b` | 1 use, 1 file | tokens.js:90 |
| `black` | `#000000` | 0 standalone; tint base only | tokens.js:91 |

**`tokens.js:15` states "NOTHING IMPORTS THIS YET". That comment is stale.** Four
shipping modules import it, all of them importing only `opacity`:
`frontend/app/consent.jsx:64`, `frontend/app/logbooks/daily_jobsite.jsx:57`,
`frontend/src/components/CheckinQrModal.jsx:17`,
`frontend/src/components/logbookStepper/styles.js:6`.

Alpha steps in use — 15 distinct, from 34 `withAlpha()` calls plus 22
hand-written `rgba()` literals (`tokens.js:114-119`). The 22 literals are
themselves the drift the helper exists to prevent: `rgba(59,130,246,0.2)`,
`rgba(59, 130, 246, 0.1)` and `rgba(59,130,246,0.10)` are three spellings of two
colours (`tokens.js:121-126`).

### A.5 PDF / report generator styling

Four HTML generators exist in the backend, each with its own inline stylesheet.

| Generator | Function | Style block | Print block |
|---|---|---|---|
| Logbook export | `export_logbook` — server.py:7923 | server.py:7972 | none |
| Per-logbook PDF | `generate_single_logbook_html` — server.py:18770 | server.py:19853 | server.py:19863 |
| Daily-log PDF | `get_daily_log_pdf` — server.py:22815 | server.py:22871 | none |
| Combined report | `generate_combined_report` — server.py:29278 | server.py:31060 | server.py:31084 `STALE-IF-af67bcf4-LANDS` |

Report palette by frequency across `generate_combined_report`
(`server.py:29278-32400`) — `STALE-IF-af67bcf4-LANDS` for every line number in
this table:

| Hex | Occurrences | Role, where stated | file:line |
|---|---|---|---|
| `#0a1929` | 65 | report ink | server.py:31129 |
| `#ffffff` | 11 | content-cell background | server.py:31162 |
| `#f0f4f8` | 8 | email body background | server.py:31063 |
| `#e2e8f0` | 7 | rules / borders | server.py:31060+ |
| `#475569` | 7 | secondary text | server.py:31060+ |
| `#b91c1c` | 4 | critical | server.py:31060+ |
| `#15803d` | 3 | ok | server.py:31060+ |
| `#b45309` | 3 | attention | server.py:31060+ |
| `#1a2332` | 2 | content-cell text | server.py:31070, :31162 |

Fonts in the generated documents are declared inline and are all system stacks —
`Helvetica` (server.py:7972), `Arial` (server.py:19853, :22871),
`-apple-system,BlinkMacSystemFont,'Segoe UI'` (server.py:32321, :36069). Outlook
gets an `mso` override (server.py:31060).

### A.6 Duplicates and near-duplicates (drift)

Near-duplicate detection: Euclidean RGB distance as a percentage of the maximum
possible (441.67). Threshold 5%. The raw run produced 60 pairs; most are the
arithmetic consequence of six near-whites all sitting near one another. Listed
below are only pairs where two colours occupy the **same semantic role** in
different files.

**Exact duplicates across modules** — same hex, separately declared:

| Hex | Declared at |
|---|---|
| `#3b82f6` | theme.js:6, tokens.js:77 |
| `#fbbf24` | theme.js:4, theme.js:55, theme.js:73, tokens.js:81 |
| `#4ade80` | theme.js:3, theme.js:69, tokens.js:82 |
| `#f87171` | theme.js:5, theme.js:57, theme.js:71, tokens.js:83 |
| `#60a5fa` | theme.js:311, tokens.js:80, server.py:19897 |
| `#050a12` | theme.js:9, theme.js:11, app.json:22, app.json:112 |
| `#ffffff` | theme.js:89, theme.js:192, theme.js:303 |

`tokens.js:69-75` names five of these as exact string matches for a `theme.js`
hex and states they should resolve to the theme token instead.

**Undocumented near-duplicates:**

| Distance | Pair | Uses | Where |
|---|---|---|---|
| 1.66% | `#0a1929` vs `#111827` | 98 vs 1 | theme.js:10 / server.py:32325 |
| 2.10% | `#1a2332` vs `#1f2937` | 2 vs 1 | server.py:31070 / server.py:32321 |
| 2.61% | `#1a2332` vs `#1e293b` | 2 vs 8 | server.py:31070 / report body |
| 4.21% | `#0a0e1a` vs `#0a1929` | 1 vs 98 | server.py:20549 / theme.js:10 |
| 2.99% | `#64748b` vs `#6b7280` | 18 vs 4 | report body / server.py:32324 |
| 1.34% | `#e2e8f0` vs `#e5e7eb` | 16 vs 3 | report rules / server.py:7976, :32322 |
| 0.39% | `#f0f4f8` vs `#f1f5f9` | 8 vs 7 | server.py:31063 / report surfaces |
| 0.32% | `#f8fafc` vs `#f9fafb` | 13 vs 1 | report surfaces / server.py:7977 |
| 0.51% | `#f8f9fa` vs `#f8fafc` | 1 vs 13 | server.py:22875 / report surfaces |
| 1.50% | `#f2f2f2` vs `#f0f4f8` | 1 vs 8 | server.py:22879 / server.py:31063 |
| 2.37% | `#d6e4f7` vs `#dbeafe` | 3 vs 1 | theme.js:113 / theme.js:124 |
| 1.36% | `#ccd8ee` vs `#d0dcf0` | 3 vs 2 | theme.js:114 / theme.js:112 |

**The daily-log PDF is a wholly separate palette.** `get_daily_log_pdf`
(`server.py:22815`) uses `#1a5276` (server.py:22872, :22878), `#2c3e50`
(server.py:22873), `#f8f9fa` (server.py:22875) and `#f2f2f2` (server.py:22879).
**None of those four appear in `theme.js` or in either of the other two report
renderers.** `#2c3e50` sits 2.06% from `#334155`, the slate the other renderers
use 14 times.

**Documented, intentional pairs — not drift:**

- `#b91c1c` vs `#C62828` — the light/dark pair of `state.criticalText` and
  `state.critical` (theme.js:163, :162).
- `#facc15` vs `#fbbf24` — `status.caution` vs `status.warning`, distinct tiers
  of the 5-tier hazard ramp (theme.js:83, :4; mapping at theme.js:75-82).
- `#4ade80`/`#f87171` vs `#22c55e`/`#ef4444` — `semanticColors.js:108-112` states
  these are two generations, that `theme.status`'s bases are stale, and that
  migrating a call site shifts hue deliberately.
- Light `attention` is `#7A5300` rather than a browner amber, chosen to keep
  42.5 degrees of hue separation from critical red (theme.js:154-159).

### A.7 Typography

**No custom font is loaded anywhere.** Searching all 378 tracked
`frontend/**/*.{js,jsx,cjs}` files for `expo-font`, `useFonts`, font `loadAsync`
and `@font-face` returns no font loading. `expo-font` does not appear in
`frontend/package.json`. **The product has no brand typeface** — it renders in
platform system fonts, and the generated PDFs use system stacks (A.5).

Declared type scale — `frontend/src/styles/theme.js:353-368`:

| Token | Value | file:line |
|---|---|---|
| `sizes` | `{fine:12, dense:13, xs:11, sm:14, md:16, lg:18, xl:24}` | theme.js:359 |
| `hero` | 48 / weight 200 / tracking -1 | theme.js:360 |
| `h1` | 36 / 300 / -0.5 | theme.js:361 |
| `h2` | 24 / 400 | theme.js:362 |
| `h3` | 18 / 500 | theme.js:363 |
| `body` | 16 / 400 | theme.js:364 |
| `small` | 14 / 400 | theme.js:365 |
| `label` | 11 / 500 / tracking 2 / uppercase | theme.js:366 |
| `stat` | 36 / 200 | theme.js:367 |

Measured sizes actually in use on CP screens — 12 distinct, 120 occurrences
(`tokens.js:188-201`). `f12` (29 uses) and `f13` (26 uses) are jointly the most
common; both were added to `theme.js` as `fine` and `dense` (`theme.js:354-358`).

Measured weights — 5 distinct, 68 occurrences: `200` (3 uses), `500` (18), `600`
(31), `700` (15), `800` (1) — `tokens.js:206-212`.

Letter spacing — 5 distinct, 8 occurrences: `-1`, `0.5`, `0.8`, `1`, `6`
(`tokens.js:217-223`).

**Defect: 182 `fontFamily` references resolve to `undefined`.** The `typography`
export at `theme.js:353` declares no `medium`, `regular`, `semibold` or `bold`
key, but eleven shipping files read them:

| File | References |
|---|---|
| frontend/app/settings/notifications.jsx | 43 |
| frontend/app/settings/notifications/project/[project_id].jsx | 38 |
| frontend/app/project/[id]/permit-renewal.jsx | 30 |
| frontend/app/index.jsx | 22 |
| frontend/src/components/permit-renewal/StartRenewalPanel.jsx | 15 |
| frontend/src/components/permit-renewal/FilingStatusCard.jsx | 12 |
| frontend/src/components/permit-renewal/ManualRenewalPanel.jsx | 7 |
| frontend/src/components/permit-renewal/FilingHistorySection.jsx | 5 |
| frontend/app/owner/index.jsx | 4 |
| frontend/app/demo.jsx | 3 |
| frontend/src/components/RenewalAlertCard.js | 3 |

Sample sites: `frontend/app/index.jsx:1045` (`fontFamily: typography.medium`),
`:1081` (`typography.semibold`), `:1105` (`typography.regular`);
`frontend/app/demo.jsx:146`. Both files import `typography` from `theme.js`
(`frontend/app/index.jsx:38`, `frontend/app/demo.jsx:13`).

### A.8 Spacing, radius, elevation

A token file exists.

| Scale | Values | file:line |
|---|---|---|
| `spacing` | `xs:4, sm:8, md:16, lg:24, xl:32, xxl:48` | theme.js:239-246 |
| `borderRadius` | `sm:8, md:12, lg:16, xl:24, xxl:32, full:9999` | theme.js:248-255 |
| `touchTarget` | `min:56, primary:72` | theme.js:348-351 |
| `outdoorShadow` | offset 0/8, opacity 0.15, radius 24, elevation 6 | theme.js:328-334 |
| dark `shadow` | `rgba(0,0,0,0.3)`, offset 0/4, radius 12 | theme.js:23-28 |
| light `shadow` | `rgba(30,58,138,0.15)`, offset 0/8, radius 24 | theme.js:127-132 |

`touchTarget.min` is 56, not Apple's 44, with the reason stated at
`theme.js:336-347` (outdoor, gloved, one-handed use). It is a floor applied via
`minHeight`/`minWidth`, not a size (`theme.js:341-342`).

Measured space literals on CP screens are off-scale: 11 distinct values, 51
occurrences, of which only `s4` and `s8` match `spacing` (`tokens.js:270-281`).
Measured radii: 6 distinct, only `r8` on scale (`tokens.js:236-243`).
Border widths: 2 distinct, 42 occurrences, 41 of them `1` (`tokens.js:285-288`).

**No shadow exists across the 16 measured CP screens** — the export was removed
rather than kept unmeasured (`tokens.js:299-311`).

`frontend/src/theme/tokens.js` is a second, earlier token module with **zero
importers** anywhere in `frontend/`, confirmed by grep across all 378 tracked
JS/JSX/CJS files. It is dead.

### A.9 Dark mode

**Implemented.**

| Fact | file:line |
|---|---|
| Provider and toggle | frontend/src/context/ThemeContext.js:8-41 |
| Default is dark | ThemeContext.js:9 (`useState(true)`) |
| Persistence key `blueview_theme` | ThemeContext.js:5 |
| Applied by mutating `colors` in place | theme.js:234-236 |
| App-level declared style | frontend/app.json:10 (`"userInterfaceStyle": "dark"`) |

The toggle is **manual only** — `useColorScheme` / OS-preference following does
not appear in the theme layer. `_applyPalette` prunes keys absent from the
incoming palette before assigning (`theme.js:214-228`); the comment at
`theme.js:196-213` records that the previous helper leaked
`glass.cardGradientEnd` from light into dark for the rest of a session.

---

## SECTION B. LOGO + IMAGE ASSETS

### B.1 Inventory

**There is no SVG in the repository.** `git ls-files` matching `\.svg$` returns
zero. Every asset is PNG.

| File | Dimensions | Format | Alpha | Size | Referenced at |
|---|---|---|---|---|---|
| frontend/assets/icon.png | 1175×1175 | RGBA8 | yes | 559,608 B | frontend/app.json:8 |
| frontend/assets/adaptive-icon.png | 1175×1175 | RGBA8 | yes | 559,608 B | frontend/app.json:111 |
| frontend/assets/splash-icon.png | 1175×1175 | RGBA8 | yes | 559,608 B | frontend/app.json:20 |
| frontend/assets/favicon.png | 738×738 | RGBA8 | yes | 307,819 B | frontend/app.json:131 |
| frontend/assets/logo-header.png | 2103×1080 | RGBA8 | yes | 458,516 B | frontend/app/login.jsx:97, :131; frontend/app/register.jsx:77, :109 |
| frontend/assets/headicon.png | 450×450 | RGBA8 | yes | 94,923 B | **no references** |
| play-store-assets/play-store-icon-512.png | 512×512 | RGBA8 | yes | 154,222 B | not referenced in code |
| play-store-assets/icon-transparent.png | 1175×1175 | RGBA8 | yes | 357,801 B | not referenced in code |
| play-store-assets/feature-graphic-1024x500.png | 1024×500 | RGB8 | **no** | 40,123 B | not referenced in code |

24 store screenshots are also tracked — see Section M.

### B.2 Identical files

`icon.png`, `adaptive-icon.png` and `splash-icon.png` are **byte-identical** —
all three hash to SHA-256
`b606d9cf6dfbe77f0396a02dd8a528f5682709361633603415067546dd3f519e`. One
1175×1175 image is serving the app icon, the Android adaptive foreground and the
splash.

### B.3 Role assignment

| Role | File | Evidence |
|---|---|---|
| Wordmark | frontend/assets/logo-header.png | 2103×1080 aspect; rendered on login and register only (login.jsx:97, :131; register.jsx:77, :109) |
| App icon | frontend/assets/icon.png | frontend/app.json:8 |
| Android adaptive icon | frontend/assets/adaptive-icon.png | frontend/app.json:111, background `#050a12` at :112 |
| Splash | frontend/assets/splash-icon.png | frontend/app.json:20, `resizeMode: contain` :21, background `#050a12` :22 |
| Web favicon | frontend/assets/favicon.png | frontend/app.json:131 |
| Notification icon | **none declared** | no `notification` block in frontend/app.json |
| Play Store icon | play-store-assets/play-store-icon-512.png | filename only; not wired to any config |

### B.4 Highest-resolution source per asset

| Asset | Best available | Vector? |
|---|---|---|
| Wordmark | 2103×1080 PNG (logo-header.png) | **No vector** |
| Icon mark | 1175×1175 PNG (icon.png) | **No vector** |
| Favicon | 738×738 PNG | **No vector** |
| Feature graphic | 1024×500 PNG, no alpha | **No vector** |

**Blocker for web: there is no vector source for any brand asset.** The
wordmark's maximum usable width is 2103 px and the icon mark's is 1175 px. Any
homepage needing a scalable logo, a hero lockup wider than 2103 px, an SVG
favicon, or a monochrome/single-colour variant must have one produced — the
repository cannot supply it.

`headicon.png` (450×450) is tracked and referenced by nothing.

---

## SECTION C. BRAND NAME AUDIT

Case-insensitive grep across all 986 tracked files. Both names are live. This
section reports the conflict; it does not resolve it.

### C.1 "LeveLog" — user-facing surfaces

| Surface | Name shown | file:line |
|---|---|---|
| App display name | `LeveLog` | frontend/app.json:3 |
| Expo slug | `levelog` | frontend/app.json:4 |
| URL scheme | `levelog` | frontend/app.json:9 |
| iOS bundle id | `com.levelog.app` | frontend/app.json:34 |
| Android package | `com.levelog.app` | frontend/app.json:114 |
| npm package name | `levelog` | frontend/package.json:2 |
| API title | `Levelog API` | backend/server.py:941 |
| API root message | `Levelog API v2.0.0 - Sync Enabled` | backend/server.py:27064 |
| Per-logbook PDF filename | `Levelog_{type}_{project}_{date}.pdf` | backend/server.py:18761 |
| Per-logbook PDF header | `LEVELOG` | backend/server.py:19897 |
| Per-logbook PDF footer | `LEVELOG CONSTRUCTION MANAGEMENT` | backend/server.py:19911 |
| Combined report header | `LEVELOG` | backend/server.py:31129 `STALE-IF-af67bcf4-LANDS` |
| Combined report footer | `LEVELOG CONSTRUCTION MANAGEMENT` | backend/server.py:31171 `STALE-IF-af67bcf4-LANDS` |
| Combined report filename | `Levelog_Report_{project}_{date}.pdf` | backend/server.py:31213 `STALE-IF-af67bcf4-LANDS` |
| Daily-log PDF footer | `Generated by Levelog Construction Management` | backend/server.py:22917 |
| Emailed report attachment | `Levelog_Report_{name}_{today}.pdf` | backend/server.py:35885 |
| Client-side PDF filename | `LeveLog_{log_type}_{date}.pdf` | frontend/app/site/logbooks.jsx:383, :406 |
| Email sender | `Levelog <notifications@levelog.com>` | backend/lib/notifications.py:71 |
| Email signature | `— LeveLog Compliance` | backend/lib/email_templates.py:189, :233, :282, :327, :373, :487 |
| Email header block | `LEVELOG COMPLIANCE` | backend/lib/email_templates.py:85 |
| DOB-log alert email | `Levelog picked up a new {type}` / `— Levelog` | backend/server.py:32302, :32309 |
| DOB-log alert HTML wordmark | `Levelog` | backend/server.py:32324 |
| Permit-renewal email wordmark | `LEVELOG` | backend/server.py:36071, :36082, :36145, :36155 |
| WhatsApp bot persona | `Levelog Assistant` | backend/server.py:40369 |
| WhatsApp vCard | `FN:Levelog Assistant` | backend/server.py:42744 |
| WhatsApp group link message | `Levelog bot has been added ... paste this code in the Levelog app` | backend/server.py:41526 |
| WhatsApp digest CTA | `View in Levelog app` | backend/server.py:40750 |
| 311 poller User-Agent | `Levelog/1.0 (311 poller)` | backend/server.py:32889 |
| In-app copy (insurance) | `managed through DCWP, not LeveLog` | backend/server.py:11005 |
| Privacy policy title and body | `LeveLog Privacy Policy` | privacy-policy.html:6, :15, :18 |
| Support page | `levelog.com`, `support@levelog.com` | frontend/public/support.html:14, :86 |
| API domain | `api.levelog.com` | frontend/src/utils/api.js:16 |
| Gate host | `https://levelog.com` | frontend/src/utils/nfcHelper.js:27 |

**Casing is not consistent.** `LeveLog` (app.json:3, email_templates.py:189),
`Levelog` (server.py:941, notifications.py:71) and `LEVELOG` (server.py:19897,
email_templates.py:85) all ship. The two PDF filename builders disagree: the
backend writes `Levelog_` (server.py:18761) and the frontend writes `LeveLog_`
(site/logbooks.jsx:383) for the same artifact.

### C.2 "Blueview" — surfaces

Blueview occurrences fall into four distinct categories.

**(a) Legacy domain, redirected in config:**

| Surface | Value | file:line |
|---|---|---|
| Vercel redirect source | `blue-view.app` → `https://levelog.com` (301) | frontend/vercel.json:12, :15-16 |
| Vercel redirect source | `www.blue-view.app` → `https://levelog.com` (301) | frontend/vercel.json:23, :26-27 |

**(b) User-facing copy — the demo screen:**

| Surface | Name shown | file:line |
|---|---|---|
| Activation email address | `activate@blueviewbuilders.com` | frontend/app/demo.jsx:18 |
| Email subject the app composes | `Activate my Blueview account` | frontend/app/demo.jsx:49 |

**(c) Persisted client storage keys** — not rendered, but they are the on-device
contract and survive a rename:

| Key | file:line |
|---|---|
| `blueview_token` | frontend/src/utils/api.js:111, :119, :127; frontend/app/projects/[id]/files.jsx:141, :824; frontend/src/components/PDFViewerWeb.jsx:34; frontend/src/components/PDFViewer.native.jsx:62 |
| `blueview_user` | frontend/src/utils/api.js:136, :145, :153 |
| `blueview_offline_queue` | frontend/src/utils/offlineQueue.js:5 |
| `blueview_cp_profile` | frontend/src/hooks/useCpProfile.js:20 |
| `blueview_theme` | frontend/src/context/ThemeContext.js:5 |
| `blueview_worker_profile`, `blueview_worker_id` | frontend/app/nfc/index.jsx:36, :37 |
| `blueview_sync_lock` (inert) | frontend/src/utils/offlineQueue.js:12, :37 |

**(d) Not the product — a customer and an infrastructure name.** These are the
majority of backend hits and are **not** brand surfaces:

| Occurrence | What it is | file:line |
|---|---|---|
| `blueview` R2 bucket | Cloudflare R2 bucket name | backend/server.py:12644, :12647, :12660 |
| `blueview.workers` | a Mongo namespace inside a log line | backend/server.py:15653 |
| `michael@blueviewbuilders.com` | a named customer, in incident comments | backend/server.py:32356; backend/lib/notifications.py:260 |
| `"Blueview Construction Inc."` | a customer company name in DOB name matching | backend/permit_renewal.py:271, :293-294 |
| `Blueview — exact CSS spec` | design-source comment on the light palette | frontend/src/styles/theme.js:93 |

### C.3 The conflict, stated

- The **shipping product identity is LeveLog** across app name, bundle ids,
  domains, PDF headers and footers, email sender and WhatsApp persona.
- **`blue-view.app` is a legacy domain already 301-redirecting to `levelog.com`**
  (vercel.json:12-16, :23-27).
- **`frontend/app/demo.jsx:18, :49` is the one user-facing screen still saying
  Blueview**, and it directs a prospect to `blueviewbuilders.com`.
- `blueviewbuilders.com` is simultaneously an operator-facing address
  (demo.jsx:18) and a **customer's** domain (notifications.py:260).
- Seven `blueview_*` AsyncStorage keys are the installed-base contract
  (api.js:111 and others).

Not resolved here. See Section R, items 1 and 2.

---

## SECTION D. FEATURE INVENTORY (SHIPPED ONLY)

68 route files under `frontend/app/` (excluding `_layout.jsx` and `+html.jsx`).
284 backend routes (`@api_router` × 280, `@app` × 4), parsed from
`backend/server.py`.

### D.1 Role model and route confinement

Roles observed: `cp`, `superintendent`, `admin`, `owner`, `site_device`, plus the
non-role flag `is_platform_operator`.

| Persona | Allowed paths | Enforcement |
|---|---|---|
| CP / superintendent | `/logbooks/**`, `/documents`, `/settings/**`, `/login`, `/consent` | frontend/src/utils/cpConfinement.js:65-80; applied at frontend/app/_layout.jsx:251-253 |
| CP with no company | `/logbooks`, `/login`, `/settings`, `/consent` | cpConfinement.js:91; applied _layout.jsx:258-274 |
| Site device | `/site/**`, `/login`; Inspector Mode pins to `/site/logbooks` | frontend/src/utils/inspectorConfinement.js:36-75; applied _layout.jsx:227-239 |
| Admin / owner | everything not above; onboarding gate runs first | _layout.jsx:205-214 |

`superintendent` is held to the CP path set deliberately (`_layout.jsx:195-198`).

### D.2 CP / superintendent persona — logbook screens

The 13 logbook types are declared once, as data, in `LOGBOOK_TYPE_REGISTRY`
(`backend/server.py:4372`).

| Route | Screen file | Label | Frequency | Status |
|---|---|---|---|---|
| `/logbooks` | frontend/app/logbooks/index.jsx | log index and notifications | — | SHIPPED |
| `/logbooks/daily_jobsite` | frontend/app/logbooks/daily_jobsite.jsx | Daily Jobsite Log (server.py:4375) | daily (server.py:4377) | SHIPPED |
| `/logbooks/preshift_signin` | frontend/app/logbooks/preshift_signin.jsx | Pre-Shift Sign-In (server.py:4404) | daily (server.py:4405) | SHIPPED |
| `/logbooks/site_superintendent_log` | frontend/app/logbooks/site_superintendent_log.jsx | Construction Superintendent Log (server.py:4423) | daily (server.py:4425) | SHIPPED — conditional `superintendent_log_active`, admin-activated (server.py:4443-4444) |
| `/logbooks/toolbox_talk` | frontend/app/logbooks/toolbox_talk.jsx | Tool Box Talk (server.py:4448) | weekly (server.py:4450) | SHIPPED |
| `/logbooks/subcontractor_orientation` | frontend/app/logbooks/subcontractor_orientation.jsx | Subcontractor Safety Orientation (server.py:4458) | as needed (server.py:4460) | SHIPPED |
| `/logbooks/osha_log` | frontend/app/logbooks/osha_log.jsx | OSHA Log Book (server.py:4468) | daily (server.py:4470) | SHIPPED |
| `/logbooks/scaffold_maintenance` | frontend/app/logbooks/scaffold_maintenance.jsx | Scaffold Maintenance Log (server.py:4478) | daily (server.py:4480) | SHIPPED — conditional `scaffold_erected`, CP-activated (server.py:4485, :4487) |
| `/logbooks/ssc_daily_safety_log` | frontend/app/logbooks/ssc_daily_safety_log.jsx | SSC/SSM Daily Safety Log (server.py:4491) | daily (server.py:4493) | SHIPPED |
| `/logbooks/hot_work` | frontend/app/logbooks/hot_work.jsx | Hot Work Permit Log (server.py:4501) | as needed (server.py:4503) | SHIPPED — conditional `hot_work_permitted`, admin-activated (server.py:4510, :4516) |
| `/logbooks/concrete_operations` | frontend/app/logbooks/concrete_operations.jsx | Concrete Operations Log (server.py:4520) | daily (server.py:4522) | SHIPPED |
| `/logbooks/crane_operations` | frontend/app/logbooks/crane_operations.jsx | Crane Operations Log (server.py:4541) | daily (server.py:4543) | SHIPPED — conditional `crane_on_site`, CP-activated (server.py:4551-4552) |
| `/logbooks/excavation_monitoring` | frontend/app/logbooks/excavation_monitoring.jsx | Excavation Monitoring Log (server.py:4556) | daily (server.py:4558) | SHIPPED — conditional `excavation_active`, CP-activated (server.py:4566-4567) |
| `/logbooks/fall_protection` | frontend/app/logbooks/fall_protection.jsx | Fall Protection Equipment Log (server.py:4571) | daily (server.py:4574) | SHIPPED — **explicitly not DOB-required** (server.py:4573) |
| `/logbooks/photos` | frontend/app/logbooks/photos.jsx | photos for an already-filed log | — | SHIPPED |
| `/logbooks/review` | frontend/app/logbooks/review.jsx | flagged-worker review | — | SHIPPED |
| `/documents` | frontend/app/documents.jsx | document list | — | SHIPPED |
| `/consent` | frontend/app/consent.jsx | e-signature agreement | — | SHIPPED (cpConfinement.js:79) |
| `/settings` | frontend/app/settings.jsx | settings and build card | — | SHIPPED |

Conditional activation is enforced server-side, not merely hidden in the client
(`backend/server.py:26002`). The endpoint is
`PUT /api/logbooks/project/{project_id}/activation` (server.py:25980) and it
refuses a CP flipping an admin-gated type (server.py:26012-26016).

### D.3 Site-device persona (gate tablet)

| Route | Screen file | Status |
|---|---|---|
| `/site` | frontend/app/site/index.jsx | SHIPPED (inspectorConfinement.js:37) |
| `/site/logbooks` | frontend/app/site/logbooks.jsx | SHIPPED — the Inspector-Mode read-only tab (inspectorConfinement.js:36) |
| `/site/checkins` | frontend/app/site/checkins.jsx | SHIPPED |
| `/site/daily-logs` | frontend/app/site/daily-logs.jsx | SHIPPED |
| `/site/documents` | frontend/app/site/documents.jsx | SHIPPED |

### D.4 Admin / owner persona

| Route | Screen file | Status |
|---|---|---|
| `/` | frontend/app/index.jsx | SHIPPED |
| `/projects` | frontend/app/projects/index.jsx | SHIPPED |
| `/project/[id]` | frontend/app/project/[id].jsx | SHIPPED |
| `/project/[id]/activity` | frontend/app/project/[id]/activity.jsx | SHIPPED |
| `/project/[id]/audit` | frontend/app/project/[id]/audit.jsx | **BEHIND FLAG** — `v2_logbook` (backend/server.py:7766) |
| `/project/[id]/defcon` | frontend/app/project/[id]/defcon.jsx | SHIPPED |
| `/project/[id]/dob-logs` | frontend/app/project/[id]/dob-logs.jsx | SHIPPED |
| `/project/[id]/notifications` | frontend/app/project/[id]/notifications.jsx | SHIPPED |
| `/project/[id]/permit-renewal` | frontend/app/project/[id]/permit-renewal.jsx | SHIPPED |
| `/project/[id]/report-settings` | frontend/app/project/[id]/report-settings.jsx | SHIPPED |
| `/project/[id]/trades` | frontend/app/project/[id]/trades.jsx | SHIPPED |
| `/projects/[id]/files` | frontend/app/projects/[id]/files.jsx | SHIPPED |
| `/projects/[id]/whatsapp-groups` | frontend/app/projects/[id]/whatsapp-groups.jsx | SHIPPED |
| `/projects/[id]/whatsapp-checklists` | frontend/app/projects/[id]/whatsapp-checklists.jsx | SHIPPED |
| `/workers`, `/workers/[id]` | frontend/app/workers.jsx, frontend/app/workers/[id].jsx | SHIPPED |
| `/reports` | frontend/app/reports.jsx | SHIPPED |
| `/daily-log` | frontend/app/daily-log.jsx | SHIPPED |
| `/checklists` | frontend/app/checklists.jsx | SHIPPED |
| `/nfc` | frontend/app/nfc/index.jsx | SHIPPED |
| `/admin/users` | frontend/app/admin/users.jsx | SHIPPED |
| `/admin/site-devices` | frontend/app/admin/site-devices.jsx | SHIPPED |
| `/admin/safety-staff` | frontend/app/admin/safety-staff.jsx | SHIPPED |
| `/admin/superintendent` | frontend/app/admin/superintendent.jsx | SHIPPED |
| `/admin/insurance` | frontend/app/admin/insurance.jsx | SHIPPED |
| `/admin/integrations` | frontend/app/admin/integrations.jsx | SHIPPED |
| `/admin/checklists` | frontend/app/admin/checklists/index.jsx | SHIPPED |
| `/admin/device-capabilities` | frontend/app/admin/device-capabilities.jsx | SHIPPED |
| `/owner` | frontend/app/owner/index.jsx | SHIPPED |
| `/owner/pending-deletion` | frontend/app/owner/pending-deletion.jsx | SHIPPED |
| `/settings/notifications` | frontend/app/settings/notifications.jsx | SHIPPED |
| `/settings/notifications/project/[project_id]` | frontend/app/settings/notifications/project/[project_id].jsx | SHIPPED |
| `/onboarding` | frontend/app/onboarding.jsx | SHIPPED (gate at _layout.jsx:205-214) |
| `/demo` | frontend/app/demo.jsx | SHIPPED — carries the Blueview copy (demo.jsx:18, :49) |
| `/help`, `/help/*` | frontend/app/help/*.jsx (6 files) | SHIPPED |
| `/login`, `/register` | frontend/app/login.jsx, frontend/app/register.jsx | SHIPPED |
| `/checkin`, `/checkin/[project_id]/[tag_id]` | frontend/app/checkin/index.jsx, frontend/app/checkin/[project_id]/[tag_id].jsx | **DECOY** — the live gate is server-rendered `backend/checkin.html`, served at backend/server.py:27180 and :27215 |

### D.5 Feature flags

Flags fail closed: `is_feature_enabled` returns `False` when the flag row is
absent (`backend/lib/feature_flags.py:163-165`). Resolution order is global →
company → user (`feature_flags.py:167-177`). Cache TTL is 60 s
(`feature_flags.py:59`).

| Flag | Gates | file:line |
|---|---|---|
| `v2_logbook` | the logbook audit / missing / deficiencies / attestations / export endpoints | backend/server.py:7766, :17391 |
| `v2_dashboard`, `v2_activity_feed`, `v2_risk_score`, `v2_dashboard_redesign` | present in the flag vocabulary | referenced across the tree |
| `PLATFORM_GATES_ENFORCED` (env, not a DB flag) | the platform-operator gate; **defaults to `false`, i.e. shadow mode** | backend/server.py:6151-6153 |

**`PLATFORM_GATES_ENFORCED` defaulting to false means `require_platform_operator`
logs a warning and then allows the request** (server.py:6174-6180). See Section
G and J.6.

---

## SECTION E. STATUTORY CLAIM REGISTER

### E.1 Citations present in the tree

| Citation | Where it is declared | file:line |
|---|---|---|
| `BC 3301.13.13` | Construction Superintendent Log — module and 6 items | backend/lib/logbook/superintendent_log.py:1, :96, :110, :137, :167, :176, :200 |
| `BC 3301.13.9` | items 4 and 5 (unsafe conditions, orders given) | backend/lib/logbook/superintendent_log.py:146, :155 |
| `BC 3301.13.12` | item 8 (competent person) | backend/lib/logbook/superintendent_log.py:188 |
| `BC 3301.13.19` | item 10 (weekly safety meeting) | backend/lib/logbook/superintendent_log.py:219 |
| `1 RCNY 3301-04(f)` | item 11 (daily inspection) | backend/lib/logbook/superintendent_log.py:238 |
| `BC 3301.13.13` | attestation body text | backend/lib/logbook/attestations.py:89 |
| `§3301.2` / `NYC DOB 3301-02` | Daily Jobsite Log registry entry | backend/server.py:4380, :4376 |
| `OSHA 1926.21` | Pre-Shift Sign-In; Tool Box Talk | backend/server.py:4409, :4453 |
| `§3301.13.13` | Superintendent Log registry entry | backend/server.py:4428 |
| `LL196` | Subcontractor Safety Orientation registry entry | backend/server.py:4463 |
| `OSHA 1926` | OSHA Log Book registry entry | backend/server.py:4473 |
| `§3314` | Scaffold Maintenance registry entry | backend/server.py:4483 |
| `§3310.4/§3310.5` | SSC/SSM Daily Safety Log registry entry | backend/server.py:4496 |
| `FC §3504` | Hot Work Permit registry entry | backend/server.py:4506 |
| `§3310.10 / §3315` | Concrete Operations registry entry | backend/server.py:4528 |
| `§3319` | Crane Operations registry entry | backend/server.py:4546 |
| `§3304` | Excavation Monitoring registry entry | backend/server.py:4561 |
| LL196 / SST | attestation module | backend/lib/logbook/ll196.py:1, :3-5 |
| DCWP / HIC | insurance copy | backend/server.py:11005 |

### E.2 DEFENSIBLE

The platform demonstrably produces or enforces these today.

| Claim | What implements it | file:line |
|---|---|---|
| **BC 3301.13.13 Construction Superintendent Log — the eleven items are captured as a structured, signed record** | 11 items declared as data with per-item citation, `attestable` and `collected` flags | backend/lib/logbook/superintendent_log.py:91-243 |
| **Items 4–7 cannot be left ambiguously blank; an explicit "nothing to report" is required before signature** | `ATTESTABLE_KEYS` and `unanswered_attestable()` | superintendent_log.py:248, :389 |
| **Three distinct empty states are recorded and rendered differently** (`ATTESTED_NONE` / `NOT_REACHED` / `NOT_COLLECTED`) | `item_state()` | superintendent_log.py:324; states defined :38-44 |
| **The BC 3301.13.12 competent-person allowance sunsets 2027-01-01 and is resolved against the record's own date, never today's** | `COMPETENT_PERSON_SUNSET` and `item_applies(key, log_date)` | superintendent_log.py:77, :254-279 |
| **Item 2 records whether the superintendent adopted the CP's account or wrote his own** | `provenance: True` and `item_provenance()` | superintendent_log.py:130, :301 |
| **Access is gated on the CS registration, not on a `role` string** | `lib/logbook/cs_attribution.py` | superintendent_log.py:19-23; module backend/lib/logbook/cs_attribution.py |
| **Conditional logbooks (scaffold / crane / excavation / hot work) are switched on server-side, and a CP cannot flip an admin-gated one** | `set_logbook_activation` | backend/server.py:25980; refusal at :26012-26016 |
| **A daily compliance report is generated and emailed on a per-project schedule** | `check_and_send_reports`, ticking every minute, matching `report_send_time` in Eastern | backend/server.py:35792-35807 |
| **Filed logs are locked, and corrections are made by linked amendment rather than by edit** | `amend_logbook` | backend/server.py:25023-25109; lock check at :17417 |
| **Every signature is written to an append-only ledger carrying a content hash** | `signature_events` insert | backend/server.py:17841-17897; hash at `compute_content_hash` :17714 |
| **Fall Protection is labelled as an industry standard and NOT DOB-required** | the subtitle is the disclaimer; the `dob_reference` key is deliberately absent | backend/server.py:4573, :4577-4585 |
| **Worker SST/OSHA card status is computed per worker** | `_worker_sst_status` | backend/lib/logbook/ll196.py:91 |

### E.3 NOT DEFENSIBLE

**Copy on the homepage MUST NOT make these claims.** Each is a citation that
appears as a label or a scope statement with no enforcing logic behind it, or a
capability the code itself disclaims.

| Citation / claim | Why it is not defensible | file:line |
|---|---|---|
| **"Automatic monthly LL196 attestation"** | Nothing schedules it. `generate_ll196_attestation` has exactly one production caller — `POST /projects/{id}/logbook/attestations/generate` — and **no frontend file calls that endpoint**. Every attestation that exists was produced by an operator running a curl. | backend/lib/logbook/ll196.py:9-15; endpoint backend/server.py:7892-7910; frontend grep for `attestations/generate` returns nothing |
| **Any LL196 roster-completeness claim** | The module's own docstring records "the query that returned zero rows on every run since this module shipped". | backend/lib/logbook/ll196.py:21-25 |
| **"BC 3301.13.13 item 9 — superintendent changes"** | `collected: False`. Not captured in this release; it needs a per-entry second signature that no logbook in the system has. | backend/lib/logbook/superintendent_log.py:211, :202-207 |
| **"BC 3301.13.19 — weekly safety meeting"** | `collected: False`. It renders as a derived status line, not a captured record. | backend/lib/logbook/superintendent_log.py:230, :226-229 |
| **Every `dob_reference` value in `LOGBOOK_TYPE_REGISTRY`** | The field is **rendered nowhere**. Grep for `dob_reference` outside tests and docs returns only the registry's own declarations. Only `subtitle` reaches a screen. | backend/server.py:4380, :4409, :4428, :4453, :4463, :4473, :4483, :4496, :4506, :4561 |
| **"Files with the DOB" or any filing claim** | `README.md:9` states in bold: "LeveLog never files anything." The renewal flow tells an operator what to type into DOB NOW; the operator files manually. | README.md:5-9 |
| **"Geofenced check-in" or location-verified presence** | Not verified in this audit. See Section Q item 1. | see Q |
| **"OSHA 300 log" or injury-recordkeeping compliance** | `OSHA Log Book` is described in the registry as a "Worker certifications register", not an OSHA 300 injury log. | backend/server.py:4469 |
| **`§3310.10 / §3315`, `§3319`, `§3304`, `§3314`, `FC §3504`, `§3310.4/§3310.5`** | These exist only as unrendered `dob_reference` strings on registry entries. The forms capture fields; no logic in the tree tests a record against the cited section. | backend/server.py:4483, :4496, :4506, :4528, :4546, :4561 |

**Rule for the homepage: nothing in E.3 may appear as a capability claim.** The
defensible framing for the E.3 log types is that the product *provides the form
and the signed record*, not that it *enforces the cited code section*.

---

## SECTION F. GENERATED ARTIFACTS

| # | Artifact | Generator | Trigger | Format | Signed? | Immutable / amendable |
|---|---|---|---|---|---|---|
| 1 | Per-logbook PDF | `generate_single_logbook_html` backend/server.py:18770; handler `get_single_logbook_pdf` server.py:18730; weasyprint server.py:18748-18751 | user request | PDF, `Levelog_{type}_{project}_{date}.pdf` (server.py:18761) | renders `cp_signature` | source doc locked on finalize (server.py:17417); amendable (server.py:25023) |
| 2 | Combined daily report | `generate_combined_report` server.py:29278; weasyprint server.py:31201-31204 `STALE-IF-af67bcf4-LANDS` | user request and scheduled | PDF, `Levelog_Report_{project}_{date}.pdf` (server.py:31213) `STALE-IF-af67bcf4-LANDS` | renders signatures | derived; regenerable |
| 3 | Emailed daily report | `check_and_send_reports` server.py:35792 | **every minute**, fires when `report_send_time` matches Eastern now (server.py:35796-35807) | email plus PDF attachment `Levelog_Report_{name}_{today}.pdf` (server.py:35885) | as above | derived |
| 4 | Daily-log PDF | `get_daily_log_pdf` server.py:22815 | user request | HTML to PDF | — | derived |
| 5 | Logbook audit export | `export_logbook` server.py:7923; weasyprint server.py:7988-7996 | user request, **behind `v2_logbook`** (server.py:7766) | PDF (server.py:8009) | — | derived |
| 6 | LL196 monthly attestation | `generate_ll196_attestation` backend/lib/logbook/ll196.py:498; renderer `render_attestation_html` :251; weasyprint :615-619 | **operator curl only** (ll196.py:9-15) | PDF at R2 key `ll196/{company_id}/{project_id}/{year}-{month:02}.pdf` (ll196.py:16-17; key builder :335) | names the operator (ll196.py:34) | recorded in `logbook_entries` with `category=ll196_attestation` (ll196.py:18) |
| 7 | Signature ledger row | insert at backend/server.py:17897 | every signature | Mongo document in `signature_events` | is itself the signature record | append-only; carries `content_hash` (server.py:17857) |
| 8 | Check-in record | gate endpoints server.py:15336, :16516 | worker tap or scan at the gate | Mongo document in `checkins` | worker signature captured at the gate | — |

Fields on the LL196 attestation PDF: the attestation period (year and month), the
project and company, a worker roster with each worker's SST status (current /
expired / missing / not-required-for-trade), a summary line, and the operator's
name plus the generation timestamp — `backend/lib/logbook/ll196.py:27-34`.

Fields on a signature-ledger row: `document_type`, `document_id`, `event_type`,
`version`, `signer.{user_id, name, role, authenticated_role, acting_capacity}`,
`device`, `content_snapshot`, `content_hash`, `signature_data`, `timestamp`,
`ip_address`, `signature_key`, `is_deleted` — `backend/server.py:17841-17878`.

### F.1 Strongest visual proof for the site

Ranked on the principle that a filed PDF outweighs a UI screenshot.

1. **Per-logbook PDF of a Construction Superintendent Log** (#1). The only
   artifact that renders a named statutory item list with citations
   (`superintendent_log.py:91-243`) alongside a signature. Highest evidentiary
   density.
2. **Combined daily report PDF** (#2 / #3). The artifact a customer's
   distribution list actually receives, on a schedule (server.py:35792).
3. **LL196 monthly attestation PDF** (#6). Visually strong — a roster with
   per-worker SST status — but see E.3: it is not automatically produced, so it
   must not be captioned as though it were.
4. The signature ledger (#7) is the strongest *trust* artifact but has no
   rendered form; featuring it would require a purpose-built visualisation.

---

## SECTION G. ROLE + PERMISSION MATRIX

### G.1 Roles

| Role | Origin | Notes |
|---|---|---|
| `owner` | every self-serve signup receives it | backend/server.py:6123-6124 |
| `admin` | assignable; `role` is in `ALLOWED_USER_FIELDS`, so an admin can write it | backend/server.py:6125-6127 |
| `cp` | competent person | frontend/app/_layout.jsx:198 |
| `superintendent` | held to the CP path set | frontend/app/_layout.jsx:195-198 |
| `site_device` | kiosk / NFC tablet; the token resolves to a `site_devices` row | backend/server.py:6241-6247 |
| `is_platform_operator` | **not a role** — a DB-write-only boolean, in no API allow-list | backend/server.py:6129-6132, :6156-6163 |

`PLATFORM_OPERATOR_EMAILS` is the bootstrap and break-glass path, env-only,
requiring a redeploy to change (`backend/server.py:6134-6141`).

### G.2 Guards

| Guard | What it enforces | file:line |
|---|---|---|
| `get_current_user` | authentication | backend/server.py:5554 |
| `require_approved` | account activation | backend/server.py:5818 |
| `require_company_access` | caller has a `company_id` before minting tenant-owned documents | backend/server.py:6076-6116 |
| `require_platform_operator` | cross-tenant operations — **shadow mode by default** | backend/server.py:6166-6184 |
| `require_company_scope` | own company only, with an operator bypass | backend/server.py:6187-6210 |
| `require_project_access` | per-project tenancy | backend/server.py:6357-6361 |
| `require_worker_access` | per-worker READ | backend/server.py:6447-6452 |
| `require_worker_write_access` | per-worker WRITE, same company only | backend/server.py:6455-6460 |
| `_same_company` | absence is not authorization | backend/server.py:6213-6218 |

### G.3 Matrix

| Role | Can see | Can write | Enforcement |
|---|---|---|---|
| CP / superintendent | own project logbooks, documents, own settings, consent | logbook drafts, signatures, CP-activated conditionals | cpConfinement.js:65-80; backend/server.py:26012 |
| Site device | the one project it was provisioned for; a worker's card if that worker checked in on that project | check-ins | backend/server.py:6241-6247, :6428-6436 |
| Company member (any role) | any project owned by their company | per-endpoint | backend/server.py:6248-6252 |
| Assigned user | projects listed in `assigned_projects` | per-endpoint | backend/server.py:6253-6255 |
| Admin | company scope | the `role` field on users | backend/server.py:6125-6127 |
| Owner | company scope — **not** cross-tenant | — | backend/server.py:6123-6124 |
| Platform operator | all tenants | all tenants | backend/server.py:6156-6163; **the gate allows non-operators while `PLATFORM_GATES_ENFORCED=false`** — server.py:6151-6153, :6174-6180 |

### G.4 Endpoints with no tenant scoping — FLAGGED, NOT FIXED

**Method.** All 284 route decorators were parsed from `backend/server.py`,
collecting `Depends(...)` from **both** the decorator's `dependencies=[...]` list
and the function signature. A project-scoped route was flagged when it carried
none of the scope guards **and** its body contained none of: `company_id`,
`_same_company`, `is_platform_operator`, `user_can_act_on_project`,
`assigned_projects`, `_assert_project_access`, `_can_caller*`, `authoriz*`,
`403`. Every survivor below was then **read individually** to confirm.

94 routes take a `{project_id}`. Ten are authenticated and unscoped:

| Endpoint | Handler | Confirmed by |
|---|---|---|
| `GET /api/projects/{project_id}/logbook/audit` | `get_logbook_audit` server.py:7779 | `db.logbook_entries.find({"project_id": project_id, ...})` server.py:7801-7807 — the only gate is the `v2_logbook` flag (:7792) |
| `GET /api/projects/{project_id}/logbook/missing` | `get_logbook_missing` server.py:7845 | `db.logbook_entries.find({"project_id": project_id ...})` server.py:7852-7853 |
| `GET /api/projects/{project_id}/logbook/deficiencies` | `get_logbook_deficiencies` server.py:7859 | server.py:7866-7867 |
| `GET /api/projects/{project_id}/logbook/attestations` | `get_logbook_attestations` server.py:7873 | server.py:7880-7881 |
| `GET /api/projects/{project_id}/logbook/export` | `export_logbook` server.py:7922 | server.py:7943-7944 |
| `GET /api/projects/{project_id}/risk-score` | `get_project_risk_score` server.py:8031 | `db.risk_scores.find({"project_id": project_id, ...})` server.py:8046-8049 |
| `GET /api/projects/{project_id}/risk-score/history` | `get_project_risk_score_history` server.py:8078 | server.py:8094-8095 |
| `GET /api/projects/{project_id}/peer-cohort` | `get_project_peer_cohort` server.py:8123 | `db.projects.find_one({"_id": to_query_id(project_id)})` server.py:8131 |
| `GET /api/projects/{project_id}/defcon-status` | `get_project_defcon_status` server.py:8144 | server.py:8152 |
| `GET /api/projects/{project_id}/recent-complaint-buckets` | `get_project_recent_complaint_buckets` server.py:8165 | server.py:8173 |

**The contrast sits inside the same file.** The POST twins of two of these do
carry the guard: `POST /projects/{project_id}/logbook/attestations/generate` has
`dependencies=[Depends(require_approved), Depends(require_project_access)]`
(server.py:7892) and `POST /projects/{project_id}/risk-score/calculate` has the
same (server.py:8102). The write is gated; the read is not.

21 routes carry no `Depends()` at all. Most are intentionally public — the gate
and the webhooks:

| Endpoint | Handler | Nature |
|---|---|---|
| `GET /checkin/{tag_id}` | `serve_checkin_page` server.py:27180 | public gate page |
| `GET /checkin/{project_id}/{tag_id}` | `serve_checkin_page_full` server.py:27215 | public gate page |
| `GET /api/checkin/{project_id}/{tag_id}/info` | `get_checkin_info` server.py:13489 | public gate data |
| `GET /api/nfc-tags/{tag_id}/info` | `get_nfc_tag_info` server.py:13471 | public |
| `POST /api/checkin/lookup-worker` | `lookup_worker` server.py:15255 | public |
| `POST /api/checkin/submit` | `submit_checkin` server.py:15336 | public |
| `POST /api/checkin` | `check_in_worker` server.py:16516 | public |
| `POST /api/checkin/register-and-checkin` | `register_and_checkin` server.py:14392 | public |
| `POST /api/checkin/gate-failure` | `record_gate_failure` server.py:13855 | public |
| `POST /api/checkin/upload-osha` | `upload_osha_card` server.py:13635 | public — **calls a paid vision API**, see J.6 |
| `POST /api/signature-events/public` | `record_public_signature_event` server.py:18243 | public |
| `GET /api/dropbox/webhook`, `POST /api/dropbox/webhook` | server.py:22732, :22739 | webhook |
| `GET /api/dropbox/callback` | `dropbox_callback` server.py:20505 | OAuth callback |
| `POST /api/whatsapp/webhook` | `whatsapp_webhook` server.py:41533 | webhook |
| `GET /api/public/temp-media/{token}` | `public_temp_media_get` server.py:42344 | token-bearing |
| `GET /a/{annotation_id}` | `annotation_short_link` server.py:44031 | short link |
| `GET /api/reports/logbook-photo/{logbook_id}/{activity_index}/{photo_index}` | `get_logbook_activity_photo` server.py:22934 | serves a photo by id |
| `POST /api/projects/{project_id}/logbook-photo` | `upload_logbook_photo` server.py:23032 | photo upload |
| `GET /api/`, `GET /api/health`, `GET /api/version` | server.py:27062, :27066, :27127 | status |

---

## SECTION H. TOP WORKFLOWS / CLICK PATHS

**Method note.** Tap counts are counted from the code only where the code
enumerates discrete controls — the gate's screens and buttons are explicit DOM
nodes. Where a screen is a dynamic stepper whose step count depends on project
configuration, no number is given and the dependency is named. Nothing here is
estimated.

### H.1 Returning worker check-in (gate)

Server-rendered `backend/checkin.html`; the React `/checkin` screens are decoys.

| Step | Surface | file:line |
|---|---|---|
| 1 | tap the NFC tag or scan the QR, loading the gate | frontend/src/utils/nfcHelper.js:27 (host); backend/server.py:27215 (route) |
| 2 | `screenPhone` — type the phone number | backend/checkin.html:232; input :238 |
| 3 | tap **Continue**, calling `lookupWorker()` | backend/checkin.html:240; handler :1173 |
| 4 | `screenReturning` — tap **Check In Now**, calling `quickCheckIn()` | backend/checkin.html:245; button :284; handler :1262 |
| 5 | `screenSuccess` | backend/checkin.html:439; handler :2055 |

**2 taps plus phone entry**, across 3 screens. Two optional controls sit on step
4: a toolbox-talk confirmation (checkin.html:258) and an affirmation
(checkin.html:280).

### H.2 New worker enrolment (gate)

| Step | Surface | file:line |
|---|---|---|
| 1–3 | as H.1, through **Continue** | backend/checkin.html:240 |
| 4 | `screenRegister` | backend/checkin.html:291 |
| 5 | OSHA/SST card photo, calling `handleOshaPhoto()` | backend/checkin.html:303-308; handler :1363 |
| 6 | OCR runs server-side | backend/server.py:13635, :13756 |
| 7 | OCR results shown; a retake prompt appears if critical fields are blank | backend/checkin.html:1631; retake :1527; missing-field test :1518 |
| 8 | selfie, calling `handleSelfiePhoto()` | backend/checkin.html:1602 |
| 9 | safety-orientation items | backend/checkin.html:792 (`getSafetyItems()`); table :730 |
| 10 | signature and submit | backend/checkin.html:2055 |

Longer than H.1 by the card capture, the OCR round trip and the orientation, and
the OCR step can loop — `showRetakePrompt(missing, attemptsLeft)`
(checkin.html:1527).

**Long-path finding:** a first-time worker's path at a turnstile at shift start
includes a network round trip to a third-party vision API
(backend/server.py:13756). `frontend/src/utils/nfcHelper.js:14-21` records that
an origin mismatch between the tag and the QR forces a *returning* worker through
this entire path a second time, because the returning-worker skip is keyed on
per-origin `localStorage`.

### H.3 CP fills and signs a daily jobsite log

| Step | Surface | file:line |
|---|---|---|
| 1 | `/logbooks` index | frontend/app/logbooks/index.jsx |
| 2 | tap the log row | frontend/app/logbooks/index.jsx |
| 3 | stepper screen | frontend/app/logbooks/daily_jobsite.jsx (3,328 lines; header at :2883) |
| 4 | consent gate, on the first signature only, pushing to `/consent` | frontend/app/consent.jsx; allowlisted at cpConfinement.js:79 |
| 5 | sign | frontend/src/components/SignaturePad.js |
| 6 | submit, which locks the record | backend/server.py:23893, :23932 |

The step count *within* the stepper is configuration-dependent and is not a fixed
number in the code, so it is not counted here.

**Finding:** between 2026-09-01 and 2026-09-03 step 4 was a closed loop. `/consent`
was not on the CP allowlist, so the consent gate pushed the CP to a route the
guard immediately bounced him off — his own home screen — making every signature
on the platform impossible. Eight hours of logs carry 33 GETs of
`/api/esra-consent` and zero POSTs (`frontend/src/utils/cpConfinement.js:4-20`).
Fixed at cpConfinement.js:79.

### H.4 Superintendent files his BC 3301.13.13 log

| Step | Surface | file:line |
|---|---|---|
| 1 | `/logbooks` — the superintendent is held to the CP path set | frontend/app/_layout.jsx:195-198 |
| 2 | tap Construction Superintendent Log, visible only when `superintendent_log_active` | backend/server.py:4443 |
| 3 | editor | frontend/app/logbooks/site_superintendent_log.jsx (1,657 lines) |
| 4 | 11 items, of which 9 are collected | backend/lib/logbook/superintendent_log.py:91-243, :251 |
| 5 | the 4 attestable items must each be answered | superintendent_log.py:248, :389 |
| 6 | sign and submit | backend/server.py:23893 |

**A minimum of 4 explicit attestations** is required before a signature is
possible (`superintendent_log.py:248`).

### H.5 Admin receives the daily report

Zero taps — this is push, not pull.

| Step | Surface | file:line |
|---|---|---|
| 1 | scheduler tick, every minute | backend/server.py:35792-35793 |
| 2 | match `report_send_time` against Eastern now | backend/server.py:35796-35804 |
| 3 | require a non-empty `report_email_list` | backend/server.py:35805 |
| 4 | render and attach the PDF | backend/server.py:35869-35885 |
| 5 | send via Resend | backend/lib/notifications.py:431-433 |

Configured at `/project/[id]/report-settings`
(frontend/app/project/[id]/report-settings.jsx).

### H.6 CP corrects a filed log (amendment)

| Step | Surface | file:line |
|---|---|---|
| 1 | open the filed log | frontend/app/site/logbooks.jsx |
| 2 | request an amendment; a reason is mandatory | backend/server.py:25032; validation :25038-25044 |
| 3 | the server refuses a second open amendment and **returns the open one** | backend/server.py:25048-25083 |
| 4 | a child is created: unsigned, unlocked, `is_amendment: true` | backend/server.py:25089-25109 |
| 5 | re-sign and finalize | backend/server.py:24863 |

**Long-path finding:** the original is never edited, so a correction costs a full
re-sign and re-finalize cycle (server.py:25097-25100). That is the intended trust
property, and it is also the cost.

---

## SECTION I. FIELD-CONDITION BEHAVIOR

### I.1 Offline — what is queued locally

| Layer | What it queues | file:line |
|---|---|---|
| `offlineQueue` | `workers`, `projects`, `check_ins`, `daily_logs`, as `create` / `update` / `delete` / `review` | frontend/src/utils/offlineQueue.js:45-60; key `blueview_offline_queue` :5 |
| `logbookDrafts` | logbook drafts, local-first | frontend/src/utils/logbookDrafts.js:110 |
| `draftSync` | drains drafts to the server | frontend/src/utils/draftSync.js |
| `filedPhotoQueue` | photos appended to already-filed logs | frontend/src/utils/filedPhotoQueue.js |
| `docCache` | downloaded documents and plans | frontend/src/utils/docCache.js:155, :212 |
| `projectCache`, `consentCache` | project and consent state | frontend/src/utils/projectCache.js, frontend/src/utils/consentCache.js |
| `siteManifestStore` | the gate tablet's approved plans, documents and submitted logbooks | frontend/app/_layout.jsx:281-298 |

Retries cap at 3 (`offlineQueue.js:6`). Draining is serialised by a module-scope
flag rather than a storage lock; why the storage lock was never a lock is
recorded at `offlineQueue.js:8-39`.

### I.2 What is sync-only or hard-fails without network

| Behaviour | Evidence |
|---|---|
| **The check-in gate requires network.** It is a server-rendered page fetched per tap, and its OCR is a server call. | backend/server.py:27180, :27215; OCR backend/server.py:13635, :13756 |
| **Card OCR hard-fails when unconfigured**, returning a 4xx naming the missing key | backend/server.py:13667-13670 |
| **Signature ledger rows were silently skipped offline.** Every `recordSignatureEvent` call site guards on `if (docId)`, and offline there is no server id, so the call was *skipped, not failed*. Thirty-three signatures on the live project are in that state. | backend/lib/logbook/signature_provenance.py:3-9 |
| The durable fix derives the ledger row from the accepted document instead of queueing it on the device | backend/lib/logbook/signature_provenance.py:11-15 |
| **Derivation loses the device and the IP, and that loss is recorded on the row** rather than inferred | backend/lib/logbook/signature_provenance.py:19-37 |
| The report email send returns early with no API key | backend/server.py:35794-35795 |

### I.3 What may be claimed as "works offline"

Backed by the tree:

- Filling and saving a **logbook draft** offline — `logbookDrafts.js:110`, drained
  by `draftSync.js`.
- Appending **photos to an already-filed log** offline — `filedPhotoQueue.js`.
- **Reading cached plans and documents** offline on the gate tablet —
  `docCache.js:212`; manifest sync `_layout.jsx:281-298`.
- Queued **worker / project / daily-log** writes — `offlineQueue.js:45-60`.

**Must NOT be claimed:** that a **worker can check in offline**. The gate is
server-rendered and its card OCR is a server round trip (backend/server.py:27215,
:13635).

### I.4 Capture inputs and fallbacks

| Input | Implementation | Fallback |
|---|---|---|
| NFC | frontend/src/utils/nfcHelper.js:2 (`react-native-nfc-manager`); permission frontend/app.json:119; plugin frontend/app.json:136-142 | QR |
| QR | frontend/src/components/CheckinQrModal.jsx; used from frontend/app/logbooks/index.jsx and frontend/src/components/CpNav.js | manual URL |
| Camera | frontend/src/components/CameraCaptureModal.jsx and `.web.jsx`; `react-native-vision-camera` plugin frontend/app.json:155-164 | photo library (frontend/app.json:39) |
| OCR | server-side vision API, backend/server.py:13756 | manual entry after the retake prompt, backend/checkin.html:1527 |
| Manual | phone-number entry at the gate, backend/checkin.html:238 | — |

Both NFC and QR resolve their host through a single constant so the tag and the
code can never name different origins
(`frontend/src/utils/nfcHelper.js:26-27`).

---

## SECTION J. TRUST + SECURITY SURFACE

### J.1 Immutability and amendment

| Property | Implementation | file:line |
|---|---|---|
| Collection | `logbooks` | backend/server.py:25062 |
| Lock field | `is_locked` | backend/server.py:23893, :23932 |
| Lock set on submit for immediate types | `is_locked: (status == "submitted") and is_immediate_preshift(log_type)` | backend/server.py:23893 |
| Update refused on a locked document | `if existing.get("is_locked")` | backend/server.py:17417 |
| `is_locked` cannot be set by a client | popped from the update payload | backend/server.py:17454 |
| Amendment endpoint | `POST /api/logbooks/{logbook_id}/amend` | backend/server.py:25023 |
| Amendment child fields | `is_amendment`, `parent_logbook_id`, `amendment_reason`, `cp_signature: None`, `is_locked: False`, `status: "draft"` | backend/server.py:25097-25109 |
| The reason is mandatory | `amendment_reason_problem()` with a minimum length | backend/server.py:25038-25044 |
| One open amendment per record | `open_amendment_head()`; 409 `AMENDMENT_ALREADY_OPEN` returning the open child's id | backend/server.py:25062-25083 |
| Withdrawal | `withdraw_amendment` | backend/server.py:25201 |
| Finalize | `POST /api/logbooks/{logbook_id}/finalize` | backend/server.py:24863 |

The original is never mutated (`backend/server.py:25027-25030`).

`amends_logbook_id` **is written by nothing and read by nothing** in shipping
code. Grep across all 986 tracked files returns only two lines, both in
`docs/audits/check-harness.md:268, :276`. `parent_logbook_id` is the live link
(backend/server.py:25102).

### J.2 Audit trail — what is recorded on write

`signature_events`, inserted at `backend/server.py:17897`. The field list is at
`backend/server.py:17841-17878` and is reproduced in Section F.

| Property | file:line |
|---|---|
| Content hash over the snapshot | backend/server.py:17714 (`compute_content_hash`); stored :17857 |
| Server-set signer id kept separate from the client-claimed role | backend/server.py:17847, :17849, :17852 |
| `acting_capacity` derived from the event type, so one account yields two capacities | backend/lib/logbook/superintendent_log.py:13-17 |
| Soft delete only, so `signer.user_id` stays resolvable to a person | backend/server.py:8689, :5865, :5930 |
| Duplicate suppression before insert | backend/server.py:17823, :17833, :17906 |
| The row's own provenance is recorded, never inferred | backend/lib/logbook/signature_provenance.py:34-45 |

Additional audit surfaces: `feature_flag_audit_log` (backend/server.py:7576) and
a logbook audit endpoint (backend/server.py:7779, behind `v2_logbook`).

### J.3 Tenant isolation — the model

Tenancy is derived from the authenticated principal and never read from the
request body or query (`backend/server.py:6236-6237`). `require_project_access`
(server.py:6357) is the dependency for any route taking a `{project_id}`, and it
admits three principals in precedence order: a **site device**, authorised for
exactly the one project it was provisioned for, whose `company_id` is derived
server-side from that device's project document so nothing is client-asserted
(server.py:6241-6247); a member of the **same company** as the project's owner,
deliberately not restricted to admin or owner because CPs and workers
legitimately use these read endpoints (server.py:6248-6252); and a user
explicitly **assigned** to the project, which preserves the cross-company
contractor model (server.py:6253-6255). It answers 404 rather than 403 when a
project does not exist or is deleted, so ids are not confirmed to a prober, and
403 when the project exists but the caller has no claim to it
(server.py:6257-6259). The worker-level twin splits read from write: writes
require the same company on both sides, with a missing company on either side
treated as a refusal, while reads additionally allow a site device for a worker
who checked in on its project, and a company that holds a check-in for that
worker (server.py:6385-6407). The reason both gates exist is recorded in the
source — `user_can_act_on_project` was opt-in and applied to 4 of 76
project-scoped routes (server.py:6225-6227), and six worker routes were fully
open as of 2026-08-25 (server.py:6371-6377). **Ten project-scoped read endpoints
remain outside this model — see G.4.**

### J.4 Storage, transport, retention

| Property | Value | file:line |
|---|---|---|
| Object storage | Cloudflare R2 over the S3 API via boto3 | backend/server.py:103, :113-115; import :68 |
| Bucket | `blueview` | backend/server.py:12660 |
| Public URL construction | `R2_PUBLIC_URL`, else endpoint plus bucket plus key | backend/server.py:133-135 |
| Database | MongoDB via Motor | requirements.txt:59, :86 |
| Email transport | Resend | backend/lib/notifications.py:65, :430-433 |
| Transport security | HTTPS, asserted in policy | privacy-policy.html:58 |
| Password storage | hashed, asserted in policy | privacy-policy.html:58 |
| API host | `api.levelog.com` | frontend/src/utils/api.js:16 |

**Retention is not implemented.** `privacy-policy.html:55` states that records
"may be retained in read-only form for the legally mandated period." Searching
the tree for `expireAfterSeconds` finds exactly one TTL index, and it is a
30-minute ephemeral row unrelated to compliance records
(`backend/card_audit.py:2457-2460`). The other TTLs are a 90-day check-in cookie
(`backend/card_audit.py:102`) and a 60-second flag cache
(`backend/lib/feature_flags.py:59`). **No retention or deletion schedule for
compliance records exists in code.**

### J.5 Account deletion

Soft delete only, so the signature ledger stays resolvable to a person
(`backend/server.py:8689`, :5865, :5930). Self-service deletion request at
`POST /api/auth/me/deletion-request` (server.py:5941), withdrawal at the
corresponding `DELETE` (server.py:5972). A pending-deletion console exists at
`frontend/app/owner/pending-deletion.jsx`.

### J.6 Two items counsel will ask about

1. **`POST /api/checkin/upload-osha` (backend/server.py:13635) is public — it
   carries no `Depends()` — and it calls a paid third-party vision API**
   (server.py:13756). No rate limit is visible in the handler.
2. **`PLATFORM_GATES_ENFORCED` defaults to `false`** (server.py:6151-6153), so
   `require_platform_operator` logs a warning and **returns the user** rather
   than refusing (server.py:6174-6180). Cross-tenant platform routes are gated
   only by whatever role checks sit underneath until that environment variable is
   set. The source states the flag must be enabled only after the operator flag
   is bootstrapped, because enabling it first locks the operator out
   (server.py:6149-6150).

---

## SECTION K. LOCALIZATION + GLOSSARY

### K.1 Coverage — two independent systems

**System 1 — the app catalogue** (`frontend/src/i18n/`):

| Locale | Namespaces | String keys | File |
|---|---|---|---|
| EN | 18 | 1,027 | frontend/src/i18n/en.js |
| ES | 1 | 5 | frontend/src/i18n/es.js |

EN namespaces: `review`, `finalize`, `dailyJobsite`, `fallProtection`, `oshaLog`,
`toolboxTalk`, `scaffoldMaintenance`, `concreteOperations`, `craneOperations`,
`excavationMonitoring`, `hotWork`, `sscDailySafetyLog`, `esraConsent`,
`siteSuperintendent`, `signature`, `logbookView`, `logbookPhotos`,
`reportPreview`.

The ES catalogue declares only `signature`, with 5 keys
(`frontend/src/i18n/es.js:49-55`).

**The 17-namespace gap is a stated policy, not an omission.** A logbook is a legal
record filed with the DOB and is written in English; Spanish belongs where a
worker must understand what he is signing (`frontend/src/i18n/es.js:5-10`,
:16-35). The EN-only set is enumerated in `EN_ONLY_NAMESPACES`, and a test asserts
those namespaces are **absent** from `es.js` rather than merely tolerating the gap
(`frontend/src/i18n/i18n.test.cjs:99`; assertions at :183 and :190). `signature`
is deliberately excluded from that allowlist and held to strict parity
(`i18n.test.cjs:178`; rationale `es.js:39-48`). Missing keys fall back to EN
rather than rendering blank or a raw key (`frontend/src/i18n/index.js`, described
at `es.js:31-33`).

**System 2 — the check-in gate** (`backend/checkin.html`):

| Locale | Keys | file:line |
|---|---|---|
| EN | 93 | backend/checkin.html:491-598 |
| ES | 93 | backend/checkin.html:599-702 |

**Full parity — the key-set difference is empty in both directions.** The toggle
is at `backend/checkin.html:210-211`, `toggleLang()` at :761, applied by
`applyTranslations()` at :770. Safety-orientation items carry their own
per-locale table (`SAFETY_ITEMS_I18N`, backend/checkin.html:730; accessor :792).

**Net position for the site:** the surface a *worker* touches is fully bilingual;
the surfaces a *CP, admin or inspector* touches are English by policy.

### K.2 Canonical noun list

Terms exactly as the product uses them. The website must use these verbatim.

| EN (canonical) | ES (where the product provides one) | Source |
|---|---|---|
| Daily Jobsite Log | — (EN-only by policy) | backend/server.py:4375 |
| Pre-Shift Sign-In | — | backend/server.py:4404 |
| Construction Superintendent Log | — | backend/server.py:4423 |
| Tool Box Talk | — | backend/server.py:4448 |
| Subcontractor Safety Orientation | — | backend/server.py:4458 |
| OSHA Log Book | — | backend/server.py:4468 |
| Scaffold Maintenance Log | — | backend/server.py:4478 |
| SSC/SSM Daily Safety Log | — | backend/server.py:4491 |
| Hot Work Permit Log | — | backend/server.py:4501 |
| Concrete Operations Log | — | backend/server.py:4520 |
| Crane Operations Log | — | backend/server.py:4541 |
| Excavation Monitoring Log | — | backend/server.py:4556 |
| Fall Protection Equipment Log | — | backend/server.py:4571 |
| Worker Check-In | Registro de Trabajador | backend/checkin.html:492 / :600 |
| Enter Your Phone Number | Ingrese Su Número de Teléfono | backend/checkin.html:493 / :601 |
| Phone Number | Número de Teléfono | backend/checkin.html:495 / :603 |
| Continue | Continuar | backend/checkin.html:497 / :605 |
| Registered | Registrado | backend/checkin.html:498 / :606 |
| Check In Now | Registrarse Ahora | backend/checkin.html:499 / :607 |
| OSHA / SST Card | (key `oshaTitle` in the ES table) | backend/checkin.html:303 |
| VERIFIED | VERIFICADO | frontend/src/i18n/es.js:50 |
| UNAFFIRMED | SIN AFIRMAR | frontend/src/i18n/es.js:51 |
| Affirm for this document | Afirmar para este documento | frontend/src/i18n/es.js:52 |
| Clear and Re-sign | Borrar y Firmar de nuevo | frontend/src/i18n/es.js:53 |
| Competent Person (CP) | — | backend/lib/logbook/superintendent_log.py:15 |
| Construction Superintendent (CS) | — | backend/lib/logbook/superintendent_log.py:16 |
| Site device | — | backend/server.py:6241 |
| Amendment | — | backend/server.py:25101 |
| Reason for Amendment | — | backend/server.py:25028 |
| Attestation | — | backend/lib/logbook/ll196.py:1 |
| Inspector Mode | — | frontend/app/_layout.jsx:217 |

**Term collision to resolve:** the user-visible label is "Tool Box Talk", three
words (backend/server.py:4448), while the route file is named `toolbox_talk.jsx`
(frontend/app/logbooks/toolbox_talk.jsx) and the i18n namespace is `toolboxTalk`
(frontend/src/i18n/en.js). Pick one for the site.

---

## SECTION L. PLATFORM + AVAILABILITY FACTS

| Fact | Value | file:line |
|---|---|---|
| App display name | LeveLog | frontend/app.json:3 |
| Slug | levelog | frontend/app.json:4 |
| Expo owner | rfs2671 | frontend/app.json:5 |
| **Version** | **1.3.0** | frontend/app.json:6 |
| iOS bundle id | `com.levelog.app` | frontend/app.json:34 |
| iOS build number | 2 | frontend/app.json:35 |
| Android package | `com.levelog.app` | frontend/app.json:114 |
| Android versionCode | 1030001 | frontend/app.json:115 |
| Android minSdkVersion | **26** (Android 8.0) | frontend/app.json:147 |
| Android compileSdk / targetSdk | 36 / 36 | frontend/app.json:148-149 |
| Android buildToolsVersion | 36.0.0 | frontend/app.json:150 |
| iOS minimum | **not set in the repo** — no `deploymentTarget` in app.json or package.json; the Expo SDK 54 default applies | frontend/package.json:27 |
| iOS tablet support | true | frontend/app.json:33 |
| Orientation | portrait | frontend/app.json:7 |
| New Architecture | disabled | frontend/app.json:11 |
| OTA update URL | `https://u.expo.dev/818dd5ed-c372-4582-aea9-846381063a51` | frontend/app.json:13 |
| runtimeVersion policy | `appVersion` | frontend/app.json:16-18 |
| Minimum supported version | 1.3.0 | frontend/app.json:30 |
| EAS project id | `818dd5ed-c372-4582-aea9-846381063a51` | frontend/app.json:26 |
| Apple App Store id | `6780696817` | frontend/eas.json:59 |
| Apple team id | `VPF54Y69X9` | frontend/eas.json:60 |
| Play track / release status | `internal` / `draft` | frontend/eas.json:55-56 |
| Expo SDK | 54 | frontend/package.json:27 |
| npm package version | 1.0.0 — **does not match app.json's 1.3.0** | frontend/package.json:3 |
| Web bundler / output | metro / single | frontend/app.json:129-130 |
| Web output directory | `dist` | frontend/vercel.json:5 |
| API host | `api.levelog.com` | frontend/src/utils/api.js:16; rewrites frontend/vercel.json:33, :37, :41 |
| Gate host | `https://levelog.com` | frontend/src/utils/nfcHelper.js:27 |
| Legacy domain | `blue-view.app` → `levelog.com`, 301 permanent | frontend/vercel.json:12-16, :23-27 |
| Backend host | Railway | backend/server.py:27131 (`RAILWAY_GIT_COMMIT_SHA`); README.md:20 |
| Deploy verification | `GET /api/version` reports the commit the running backend was built from | backend/server.py:27127-27133 |
| Build-commit injection | `EAS_BUILD_GIT_COMMIT_HASH` → `JS_COMMIT` → `EXPO_PUBLIC_JS_COMMIT`, never `git rev-parse` | frontend/app.config.js:31-41; rationale :22-25 |

**The web deploy target is contradicted inside the tree.** `frontend/vercel.json`
is a Vercel config with Vercel-specific `redirects` and `rewrites`
(vercel.json:1-51), and `frontend/src/utils/nfcHelper.js:10-12` names Vercel.
`README.md:21` says "React Native Web on **Cloudflare Pages**". No CI workflow
deploys web — `.github/workflows/` contains no Vercel, Cloudflare or Pages step.

Android permissions requested: INTERNET, ACCESS_NETWORK_STATE, NFC, CAMERA,
READ_MEDIA_IMAGES, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE,
ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION — frontend/app.json:116-126.

iOS privacy manifest declares tracking `false` with no tracking domains, and
collects Name, PhoneNumber, EmailAddress, PhotosorVideos and UserContent (all
linked, none for tracking) plus CrashData and PerformanceData (unlinked) —
frontend/app.json:42-107. `ITSAppUsesNonExemptEncryption` is `false`
(frontend/app.json:40).

### L.1 Store metadata present in the repo

| Item | Present? | Path |
|---|---|---|
| Screenshots — phone | 8 × 1080×1920 | play-store-assets/screenshots/phone/ |
| Screenshots — 7-inch tablet | 8 × 1202×1924 | play-store-assets/screenshots/tablet-7/ |
| Screenshots — 10-inch tablet | 8 × 1600×2560 | play-store-assets/screenshots/tablet-10/ |
| Feature graphic | 1024×500 | play-store-assets/feature-graphic-1024x500.png |
| Store icon | 512×512 | play-store-assets/play-store-icon-512.png |
| **Store description, keywords, title** | **absent** | no non-image file exists under play-store-assets/ |

---

## SECTION M. SCREENSHOT INVENTORY

### M.1 The existing screenshots were captured against production

`capture_screenshots.py` drives Playwright against `https://www.levelog.com` and
`https://api.levelog.com` (`capture_screenshots.py:16-17`), signs in with a
hard-coded account (`:14-15`), and screenshots a **real production project id**,
`69dfe89f079abf2b78ee01e6`, labelled "432 Park Ave" (`:19`), at a fixed date
(`:20`). The eight routes captured are listed at `capture_screenshots.py:22-30`.

**The 24 committed PNGs were therefore rendered from live customer data.** I did
not open them, precisely because of that: this audit is forbidden to read
production data, and opening them would do so. Every one must be treated as
**PII-UNREVIEWED** until a human inspects it. On this evidence they are not
usable as marketing assets.

### M.2 Candidate screens for marketing capture

Ranked by visual density and clarity, judged from the screen files' content and
size.

| Rank | Screen | Route | File | Density signal | PII |
|---|---|---|---|---|---|
| 1 | Daily Jobsite Log editor | `/logbooks/daily_jobsite` | frontend/app/logbooks/daily_jobsite.jsx (3,328 lines) | largest CP screen; activity chips, photos, roster | **PII-PRESENT** — worker names, site photos |
| 2 | Project detail | `/project/[id]` | frontend/app/project/[id].jsx (2,351 lines) | risk score, DOB signals, permits | **PII-PRESENT** — real address, BIN, permit holders |
| 3 | Filed-log viewer | `/site/logbooks` | frontend/app/site/logbooks.jsx (2,177 lines) | rendered filed documents | **PII-PRESENT** — signatures, printed names |
| 4 | Owner console | `/owner` | frontend/app/owner/index.jsx (2,019 lines) | cross-company tables | **PII-PRESENT** — company and user rows |
| 5 | Plans and Files | `/projects/[id]/files` | frontend/app/projects/[id]/files.jsx (1,974 lines) | PDF viewer, page index | **NEEDS-SEED-DATA** — requires uploaded plans |
| 6 | Superintendent Log | `/logbooks/site_superintendent_log` | frontend/app/logbooks/site_superintendent_log.jsx (1,657 lines) | 11 statutory items | **PII-PRESENT** — printed name, signature |
| 7 | Notification settings | `/settings/notifications` | frontend/app/settings/notifications.jsx (1,814 lines) | dense toggle matrix | **PII-FREE** |
| 8 | Daily log | `/daily-log` | frontend/app/daily-log.jsx (1,680 lines) | — | **PII-PRESENT** |
| 9 | Dashboard | `/` | frontend/app/index.jsx | portfolio rollups, per-site counts | **PII-PRESENT** — project addresses |
| 10 | Logbook index | `/logbooks` | frontend/app/logbooks/index.jsx | 13 log rows plus notification chips | **NEEDS-SEED-DATA** — clean only without live rows |
| 11 | Check-in gate | `/checkin/{project_id}/{tag_id}` | backend/checkin.html | 5 screens, fully bilingual | **NEEDS-SEED-DATA** — clean if a fixture project is used |
| 12 | Help screens | `/help/*` | frontend/app/help/*.jsx | static copy | **PII-FREE** |
| 13 | Login / Register | `/login`, `/register` | frontend/app/login.jsx, frontend/app/register.jsx | carries the wordmark (login.jsx:97) | **PII-FREE** |

### M.3 Seed fixtures that would be needed

Described, not created.

| Screen | Fixture required |
|---|---|
| Daily Jobsite Log | one project; 6–10 workers with fictional names and trades; one day of check-ins; 2–3 non-identifying site photos; one activity per band |
| Project detail | one project with a fictional address and a BIN resolving to no real record; a `risk_scores` row whose `model_version` matches `_stat_engine.MODEL_VERSION` (backend/server.py:8048); 2–3 synthetic DOB signals |
| Filed-log viewer | one finalized logbook with `is_locked: true` and a synthetic signature |
| Superintendent Log | one `cs_registrations` row for a fictional CS; a log with all 4 attestable items answered (superintendent_log.py:248) and item 11 populated |
| Plans and Files | 2–3 non-client PDFs uploaded and page-indexed |
| Logbook index | one project with 3–4 conditional types activated — `scaffold_erected`, `crane_on_site` (backend/server.py:4485, :4551) |
| Check-in gate | one fixture project, one NFC tag row, and one enrolled fictional worker so the returning-worker path (H.1) renders |

Demo seeding scripts already exist — `seed_blueview_demo.py`,
`seed_blueview_history.py`, `seed_demo_data.py` — and were neither read nor run.

---

## SECTION N. NUMBERS THE OPERATOR MUST SUPPLY

**Not run. Not estimated.** One query per line. Collection names are taken from
`backend/server.py` usage; field names from the code cited beside each claim
elsewhere in this document.

Documents filed (finalized, non-amendment logbooks):
```
db.logbooks.countDocuments({ status: "submitted", is_deleted: { $ne: true }, is_amendment: { $ne: true } })
```

Documents filed, by log type:
```
db.logbooks.aggregate([{ $match: { status: "submitted", is_deleted: { $ne: true } } }, { $group: { _id: "$log_type", n: { $sum: 1 } } }, { $sort: { n: -1 } }])
```

Locked (immutable) documents:
```
db.logbooks.countDocuments({ is_locked: true, is_deleted: { $ne: true } })
```

Amendments raised:
```
db.logbooks.countDocuments({ is_amendment: true, is_deleted: { $ne: true } })
```

Projects active:
```
db.projects.countDocuments({ is_deleted: { $ne: true } })
```

Companies (tenants):
```
db.companies.countDocuments({ is_deleted: { $ne: true } })
```

Workers enrolled:
```
db.workers.countDocuments({ is_deleted: { $ne: true } })
```

Distinct workers with at least one check-in:
```
db.checkins.distinct("worker_id").length
```

Sign-ins processed, all time:
```
db.checkins.countDocuments({})
```

Sign-ins processed, last 90 days:
```
db.checkins.countDocuments({ created_at: { $gte: new Date(Date.now() - 7776000000) } })
```

Signatures in the ledger:
```
db.signature_events.countDocuments({ is_deleted: { $ne: true } })
```

Report emails sent:
```
db.report_emails.countDocuments({})
```

LL196 attestations produced:
```
db.logbook_entries.countDocuments({ category: "ll196_attestation" })
```

DOB signals ingested:
```
db.dob_logs.countDocuments({})
```

Date range covered, check-ins:
```
db.checkins.aggregate([{ $group: { _id: null, first: { $min: "$created_at" }, last: { $max: "$created_at" } } }])
```

Date range covered, filed logbooks:
```
db.logbooks.aggregate([{ $match: { status: "submitted" } }, { $group: { _id: null, first: { $min: "$created_at" }, last: { $max: "$created_at" } } }])
```

Projects with a scheduled report configured:
```
db.projects.countDocuments({ report_send_time: { $exists: true }, report_email_list: { $exists: true, $ne: [] } })
```

**Caveats the operator must apply before any of these becomes a public number.**
`db.logbooks` carries test rows — see Section Q item 14. `db.risk_scores` holds
both V2.1 and V2.2 documents, and V2.2 neither migrated nor deleted the V2.1 rows
(backend/server.py:8040-8044), so any risk-score count must filter on
`model_version`. Signature counts understate reality: 33 signatures on the live
project produced no ledger row at all
(backend/lib/logbook/signature_provenance.py:8-9).

---

## SECTION O. EXISTING COPY IN REPO

| Document | What it is | Path |
|---|---|---|
| **LEVELOG-BRIEF.md** | **A prior version of this document** — "factual build brief for marketing design", audited from source at commit `aee8c96`, 2026-08-25, 615 lines. Its §1a enumerates 67 route files with status verdicts. It records two caveats: no screenshots were captured, and the compliance-audit layer is behind a flag defaulting OFF. | LEVELOG-BRIEF.md:1-21 |
| README.md | Product description. Carries the load-bearing sentence, in bold: "LeveLog never files anything." | README.md:1-14 |
| Canonical product description | Named by the README as canonical | docs/architecture/v1-monitoring-architecture.md |
| Privacy policy | Live legal copy, effective April 14, 2026 | privacy-policy.html |
| Support page | Public support copy; `support@levelog.com` | frontend/public/support.html:86 |
| Email templates | Customer-facing prose, signed "LeveLog Compliance" | backend/lib/email_templates.py:189, :209, :233, :258 |
| WhatsApp assistant persona | A system prompt describing the product to users | backend/server.py:40369, :40418 |
| In-app help | Six screens of user-facing explanation | frontend/app/help/index.jsx, faq.jsx, getting-started.jsx, notifications.jsx, permit-renewal.jsx, troubleshooting.jsx |
| Authorization text | Customer-facing template | backend/templates/authorization_text.md |
| COI retention guarantee | Contains a retention commitment | docs/coi-retention-guarantee.md |
| Design narratives | 20 files of design rationale | docs/design/ |

`LEVELOG-BRIEF.md` and this document should be reviewed together. Where they
disagree, this document's SHA is `94f89d99` and the brief's is `aee8c96`.

---

## SECTION P. LEGAL PAGES

| Document | Exists? | Path |
|---|---|---|
| Privacy policy | **Yes** — effective April 14, 2026 | privacy-policy.html:16 |
| Terms of Service | **Absent** | no file matching `terms\|tos` in the tree |
| EULA | **Absent** | no match |
| Accessibility statement | **Absent** | no match |
| Cookie policy | **Absent** | no match |

Privacy policy contents: data collected (privacy-policy.html:20-28), use
(:30-36), permissions (:38-45), sharing (:47-52), retention (:54-55), security
(:57-58), children (:60-61), rights (:63-64), and contact `privacy@levelog.com`
(:69-70).

### P.1 Third-party data processors the code actually calls

| Processor | What it receives | file:line | Disclosed in the policy? |
|---|---|---|---|
| MongoDB Atlas | all application data | requirements.txt:59, :86 | **Yes** — privacy-policy.html:51 |
| Dropbox | project files | backend/server.py:20505, :22739 | **Yes** — privacy-policy.html:51 |
| Cloudflare R2 | photos, PDFs, COI uploads, plans | backend/server.py:68, :103, :113-115 | **No** |
| Resend | recipient email addresses, report PDFs | backend/lib/notifications.py:65, :430-433 | **No** |
| Alibaba Qwen (vision) | **worker OSHA/SST card images** | backend/server.py:13667, :13756 | **No** |
| OpenAI | audio for transcription; chat completions | backend/server.py:37199, :37257, :37476 | **No** |
| Google Gemini | project phase inference | backend/server.py:740, :17326 | **No** |
| Sentry | crash and error payloads | backend/server.py:769-771 | **No** — crash data is mentioned at privacy-policy.html:27, the processor is not |
| WAAPI (WhatsApp) | message content, group membership | backend/server.py:41533; env `WAAPI_TOKEN`, `WAAPI_INSTANCE_ID` | **No** |
| NYC Socrata / Open Data | project BIN and BBL in outbound queries | env `SOCRATA_APP_TOKEN`; backend/server.py:32889 | **No** |
| Railway | backend hosting | backend/server.py:27131 | **No** |
| Vercel | web hosting | frontend/vercel.json | **No** |

**The policy names three processors; the code calls at least thirteen.**
`privacy-policy.html:51` says "Render, MongoDB Atlas, Dropbox" — and **Render is
not one of them**: the backend reads `RAILWAY_GIT_COMMIT_SHA`
(backend/server.py:27131) and `README.md:20` says Railway.

The sharpest gap for counsel: **worker OSHA/SST card images are sent to a
third-party vision API** (backend/server.py:13756) from a **public,
unauthenticated endpoint** (backend/server.py:13635), and no processor of that
class is disclosed.

---

## SECTION Q. UNVERIFIED

Everything searched for and not confirmed. An empty result is reported as empty.

| # | What I looked for | Search performed | Result |
|---|---|---|---|
| 1 | Geofenced or location-verified check-in | grep for lat/lng predicates on the check-in gate endpoints (backend/server.py:15336, :16516) | **Not confirmed.** `ACCESS_FINE_LOCATION` and `ACCESS_COARSE_LOCATION` are requested (frontend/app.json:124-125) and geotagging is described in the policy (privacy-policy.html:42), but I did not trace a location check into a check-in acceptance decision. Do not claim location verification without tracing it. |
| 2 | Notification icon asset | grep of app.json for a `notification` block; grep for an `expo-notifications` icon config | **Empty.** No notification icon is configured. |
| 3 | Push notification sender identity | grep for FCM / APNs sender config | **Empty.** Email (Resend) and WhatsApp (WAAPI) senders were found; no push sender was. |
| 4 | Store description and keywords | `git ls-files play-store-assets` filtered to non-images | **Empty.** Images only. |
| 5 | iOS minimum deployment target | grep of app.json and package.json for `deploymentTarget` | **Empty.** Not pinned in the repo. |
| 6 | Web deploy pipeline | grep of `.github/workflows/*.yml` for vercel / cloudflare / pages | **Empty.** No web deploy step in CI, and README.md:21 and vercel.json disagree on the host. |
| 7 | Data retention implementation | grep for `expireAfterSeconds` across the tree | **Effectively empty.** One 30-minute TTL on an ephemeral row (backend/card_audit.py:2460). No compliance-record retention exists. |
| 8 | Payment and pricing | grep for `import stripe` | **Empty.** `stripe==14.1.0` is in requirements.txt:116 but is never imported. **No pricing exists anywhere in the repo.** |
| 9 | Terms of Service, EULA, accessibility statement | `git ls-files` matching `terms\|tos\|eula\|accessib\|legal` | **Empty.** |
| 10 | `amends_logbook_id` readers or writers | grep across all 986 tracked files | **Empty in shipping code** — only docs/audits/check-harness.md:268, :276. |
| 11 | Tap counts inside the logbook steppers | read of the stepper components | **Not countable.** The step count is configuration-dependent; no fixed number exists in the code. Reported as a dependency in H.3 rather than as a figure. |
| 12 | PII in the 24 committed screenshots | not opened | **Deliberately not verified.** They were captured against production (capture_screenshots.py:16-19), so opening them would read production data, which this audit is forbidden to do. Marked PII-UNREVIEWED in M.1. |
| 13 | Whether the ten unscoped endpoints in G.4 are reachable cross-tenant in practice | static read only | **Not exercised.** The code path is confirmed by reading; no request was made against any environment. |
| 14 | Test-data contamination of the counts in Section N | static read only | **Not verified.** `db.logbooks` is known to carry test rows; the split cannot be determined without a DB query, which is why Section N contains queries and not numbers. |
| 15 | Which of the 13 logbook types have ever actually been filed | requires a DB query | **Not verified.** The query is supplied in Section N. |
| 16 | Font licensing | no fonts are loaded | **Not applicable.** No custom font exists to license (A.7). |

**Unverified item count: 16.**

---

## SECTION R. DECISIONS REQUIRED FROM OPERATOR

Questions only. No recommendations.

1. **Brand name.** The product ships as LeveLog everywhere except
   `frontend/app/demo.jsx:18, :49`, which sends prospects to
   `blueviewbuilders.com` — a domain that is also a customer's
   (backend/lib/notifications.py:260). Which name does the homepage carry, and
   does `demo.jsx` change with it?
2. **Name casing.** `LeveLog`, `Levelog` and `LEVELOG` all ship, and the two PDF
   filename builders disagree — `Levelog_` at backend/server.py:18761 versus
   `LeveLog_` at frontend/app/site/logbooks.jsx:383. Which casing is canonical
   for the site?
3. **Legacy domain.** `blue-view.app` 301s to `levelog.com`
   (frontend/vercel.json:12-16). Does that redirect stay, and is the homepage
   served from `levelog.com` or elsewhere?
4. **Vector assets.** No SVG exists (B.1), and the largest wordmark is a 2103 px
   PNG. Who produces the vector logo, icon and favicon, and by when?
5. **Statutory claims to lead with.** E.2 lists what is defensible and E.3 lists
   what is not. Which E.2 claim leads the hero, and does the site cite
   BC 3301.13.13 explicitly?
6. **LL196.** It is the most visually compelling artifact and it is not
   automatically produced (backend/lib/logbook/ll196.py:9-15). Is it featured
   with an accurate "operator-generated" caption, or omitted?
7. **Featured artifact.** F.1 ranks the Construction Superintendent Log PDF first
   and the combined daily report second. Which goes on the homepage?
8. **Filing.** `README.md:9` states "LeveLog never files anything." Does the site
   say this explicitly, or stay silent on filing?
9. **Offline claim.** I.3 lists exactly what works offline and states that a
   worker cannot check in offline. Does the site make an offline claim at all?
10. **Target persona for the hero.** The product serves five distinct personas
    (G.3). Which one is the homepage addressed to?
11. **Pricing.** Absent from the repo entirely; Stripe is a dependency that is
    never imported (requirements.txt:116). Is there a price on the site?
12. **Screenshots.** The 24 committed PNGs came from production
    (capture_screenshots.py:16-19). Are they reviewed and cleared, or are fresh
    captures taken against the seed fixtures in M.3?
13. **Spanish.** The worker gate is fully bilingual at 93/93 keys; the CP and
    admin surfaces are English by policy (frontend/src/i18n/es.js:5-10). Is the
    homepage bilingual, and does it state which parts of the product are?
14. **Processor disclosure.** The privacy policy names three processors; the code
    calls at least thirteen, including a vision API that receives worker card
    images (P.1). Is the policy updated before the site ships?
15. **Terms of Service.** None exists (P). Does the site need one at launch?
16. **Open findings.** The ten unscoped read endpoints (G.4) and the two items in
    J.6 are unresolved. Does the site make a security or tenant-isolation claim
    before they are closed?
17. **Proof metrics.** Section N supplies the queries. Who runs them, and are the
    resulting numbers published with their date range attached?

---

## Document statistics

- **Line count: 1,693.**
- **Unverified items: 16** (Section Q).
- Evidence citations: 723, across 75 distinct source paths.
- All 209 distinct `backend/server.py` citations re-verified against
  `git show 94f89d99:backend/server.py`; none lands on a blank or out-of-range
  line. See Section 0, "Concurrent modification during the audit".
- `STALE-IF-af67bcf4-LANDS` markers: 8, all on `backend/server.py` citations, in
  sections A, C and F.
- Audited SHA: `94f89d9971c5891b0fc883206dcea6faac753b14`.
- Excluded delta: `af67bcf474a2b24373b8b3ecadd888d00f1404a9`.
