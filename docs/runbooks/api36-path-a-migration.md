# API 36 / Google Play — Path A (Legacy Architecture) Migration Runbook

**Goal:** ship `targetSdkVersion 36` (Android 16) to satisfy Google Play.

> ## ✅ DEADLINE — CONFIRMED
> Google's hard date was **Aug 31, 2026**; the operator **confirmed the extension to Nov 1, 2026 was
> requested AND granted** in the Play Console (verified, not assumed — an earlier draft stated it as
> fact without checking). Run this as a **supervised block**, not a rush. Budget 8–10 days including
> the edge-to-edge phase, and leave room for Play review.

**Route:** Expo SDK 52 → 54, **legacy architecture** (`newArchEnabled: false`), keeping every native module on a **stable, both-arch-supported** version. **NOT** New Architecture (that's Path B, deferred to the SDK-55 cycle).
**Deploy type:** **native AAB rebuild + Google Play submission.** This is NOT an OTA/EAS-Update — `targetSdk`/RN/SDK changes are compiled into the binary.
**Effort:** ~6–8 focused working days. Do it in one committed block with a device on hand.

> **Why Path A:** the only New-Arch blocker is `react-native-nfc-manager` — its New-Arch support exists only in `4.0.0-beta.7` (pre-release), and the Activity/intent fix that NFC foreground dispatch needs is beta-only. NFC is load-bearing for worker check-in, so shipping beta is unacceptable. Legacy arch lets every module stay on a stable release that supports RN 0.81. Trade-off: SDK 55 removes the legacy opt-out, so New Arch (Path B) is a fast-follow — by then nfc-manager should have a stable New-Arch release.

---

## ⚠️ The three callouts to read FIRST

1. **`newArchEnabled` is a REAL reversal.** The app currently ships `newArchEnabled: true` (`app.json:11`). Path A flips it to **`false`**. This is safe *today* because reanimated 3.16, vision-camera 4.7, and quick-crypto 0.7 all support both architectures — **but you must re-verify each actually works on legacy after the flip** (see Phase 4 smoke tests). Don't assume; test.
2. ~~Riskiest step: patching vision-camera~~ **CORRECTED — NO PATCH NEEDED. Do not write one.** Verified by diffing the published tarballs: the RN 0.81 Android break (RN converted `MapBuilder` to Kotlin, so `build()` now returns an immutable `Map`) was fixed in **4.7.2**, and **4.7.3 already contains the fix** (`CameraViewManager.kt` takes `Map<String,Any>?`; `CameraViewModule.kt` uses `reactApplicationContext.currentActivity`). Issue #3616 was filed against **4.7.1**; PR #3604 was never merged but 4.7.2 fixed the same two files independently. **Keep `4.7.3`, no `patch-package`.**

3. **🔴 THE REAL TRAP — reanimated. `npx expo install --fix` WILL BREAK THIS BUILD.** SDK 54 pins `react-native-reanimated: ~4.1.1`, and **Reanimated 4 is New-Architecture-ONLY** — it cannot run on `newArchEnabled: false`. So the command this runbook tells you to trust will install a package incompatible with the chosen architecture. **Pin `3.19.5` explicitly and re-assert it after every `--fix`.** Note `3.16.x` does NOT support RN 0.81 — `3.19.x` is the only 3.x line that does. Expect a permanent `expo-doctor` version warning; that is correct here.

4. **🔴 NEW — edge-to-edge is mandatory and is its own work item (1–2 days).** SDK 54 + API 36 enforce edge-to-edge on all Android apps and it **cannot be disabled** (`windowOptOutEdgeToEdgeEnforcement` is deprecated *and* non-functional on API 36). This app is dark, full-bleed, has a WebView (`checkin.html`) and a full-screen camera modal — **every screen needs an inset audit.** This, not vision-camera, is now the most likely day-eater.
3. **Version pins move.** Every exact pin below was read from `expo@sdk-54 bundledNativeModules.json` — **re-verify at execution time** with `npx expo install --fix`, which is the source of truth for the SDK you actually install.

---

## Registry check, 2026-08-22 — THE BLOCKER HAS NOT LIFTED

This runbook was written when SDK 54 was current. It is not any more, and the
question of whether to jump straight to a newer SDK was raised. The answer is
decided by one package, and it was re-checked against the registry rather than
assumed:

| Package | Latest STABLE | Latest any |
|---|---|---|
| `react-native-nfc-manager` | **3.17.2** | `4.0.0-beta.7` |
| `react-native-vision-camera` | 5.2.3 | 5.2.3 |
| `react-native-reanimated` | 4.6.0 | 4.6.0 |
| `expo` | 57.x (55, 56, 57 all released) | 58 canary |

**nfc-manager still has NO stable New-Architecture release.** Checked
2026-08-22 via `npm view react-native-nfc-manager dist-tags`:

```json
{ "latest": "3.17.2", "beta": "4.0.0-beta.7" }
```

The entire 4.x line is `beta.0` through `beta.7` — eight pre-releases, no
stable. `latest` still points at 3.17.2. The note above hoping that "by then
nfc-manager should have a stable New-Arch release" has not come true.

### Why that rules out SDK 55 and later

SDK 55 (RN 0.82) **removes the `newArchEnabled: false` opt-out** — see the Path
B section below. So targeting 55+ does not merely permit New Architecture, it
**requires** it, which in turn requires nfc-manager `4.0.0-beta.7`. NFC programs
the gate tags every worker checks in against. Shipping a pre-release there is
the thing Path A exists to refuse.

Two further costs of 55+, both consequences of the same jump:

* `expo-file-system/legacy` is **removed** in SDK 55, so the six import sites
  need a full API rewrite rather than a path swap.
* reanimated has no maintained 3.x line left (4.6.0 is current, New-Arch-only),
  which is fine ON New Arch and impossible off it.

**SDK 54 remains the target**, and it is sufficient: `targetSdkVersion 36` is
what Play requires, and SDK 54 supports it. Being behind the current SDK line is
a debt to pay in the Path B cycle, not a reason to take the beta now.

### The one fact that would change this

`react-native-nfc-manager@4.x` reaching **stable**. Re-run the check before
starting; if 4.x has shipped, Path B becomes available and the whole
legacy-architecture detour can be skipped:

```bash
npm view react-native-nfc-manager versions --json
```

### Also noted, and deliberately NOT acted on

`react-native-vision-camera` is now **5.2.3**; this repo is on 4.7.3 and the
"keep 4.7.3, no patch" guidance above is now advice about a version two majors
old. It stands for the SDK 54 hop. It is not being changed here, because the
camera took six device rounds to get right and four of the wrong diagnoses came
from reasoning about source rather than observing hardware — moving the camera
library in the same change as an SDK bump would make the next camera defect
impossible to attribute.

---

## Target versions (verify with `npx expo install --fix`)

| Package | Current | Path A target (SDK 54) | Notes |
|---|---|---|---|
| expo | ~52.0.17 | ~54 | via 53 hop |
| react-native | 0.76.9 | 0.81.x | RN 0.81 drops built-in JSC |
| react / react-dom | 18.3.1 | 19.1.x | React 19 — type/peer fallout |
| react-native-nfc-manager | ^3.14.0 | **3.17.2** | stable, RN 0.81 **old-arch** support |
| react-native-vision-camera | ^4.7.3 | **4.7.3 — NO PATCH** | fix already in 4.7.2/4.7.3 (verified by tarball diff) |
| react-native-reanimated | ~3.16.1 | **PIN 3.19.5** ⚠️ | SDK54 pins 4.1.1 = NEW-ARCH-ONLY. 3.16.x does NOT support RN 0.81. Override `--fix` |
| react-native-quick-crypto | ^0.7.0 | **REMOVE** | unused — zero imports anywhere; a WatermelonDB leftover |
| react-native-gesture-handler | ~2.20.2 | ~2.28.0 | |
| react-native-screens | ~4.4.0 | ~4.16.0 | |
| react-native-safe-area-context | 4.12.0 | ~5.6.0 | major bump |
| @react-native-async-storage/async-storage | 1.23.1 | **2.2.0** (never 3.x) | verified near no-op: DB files byte-identical, data survives; app only uses get/set/removeItem |
| @react-native-community/netinfo | 11.4.1 | 11.4.1 | unchanged |
| react-native-svg | 15.8.0 | 15.12.1 | |
| react-native-webview | 13.12.5 | 13.15.0 | |
| @nozbe/watermelondb | ^0.27.1 | **REMOVE** | JS already gone (Task 7 `e8bf396`); drop dep + simdjson pod here |
| babel-preset-expo | ~12.0.0 | **~54.0.12** | | ⚠️ was missing |
| @expo/metro-runtime | ~4.0.0 | **~6.1.2** | | ⚠️ was missing |
| react-native-web | ~0.19.13 | **~0.21.0** | | ⚠️ was missing — you ship a web bundle |
| expo-* (router, updates, file-system, image-picker, constants, build-properties, …) | SDK 52 pins | SDK 54 pins | lockstep via `expo install --fix` |

> On legacy arch you deliberately **hold reanimated at 3.19.5** (v4 is New-Arch-only). **quick-crypto is REMOVED, not held** — it is unused. Also drop the two WatermelonDB babel plugins (`@babel/plugin-proposal-decorators`, `@babel/plugin-proposal-class-properties`) from `babel.config.js`: they existed only for Watermelon `@field` decorators, `class-properties` isn't even in devDependencies, and deprecated plugin names are a live break risk on `babel-preset-expo@54`. The explicit `react-native-reanimated/plugin` entry is also redundant (auto-injected since SDK 50).

---

## Phase 0 — Prep (~0.5 day)

- [ ] Cut a dedicated branch off `main` (do NOT do this on `main`).
- [ ] Confirm **Task 7 (WatermelonDB removal, `e8bf396`)** is merged and offline verified on-device — its JS is already removed; in Phase 4 you also drop the `@nozbe/*` deps + the `simdjson` extraPod (`app.json`) + the metro exclusion, which removes a native/build complication.
- [ ] Get a **green production build on SDK 52 first** (`eas build -p android --profile production`) so you have a known-good baseline to diff against.
- [ ] Have a physical **Android 16** device ready with NFC.
- [ ] Record current `expo.version` (1.1.3) — you'll bump it in Phase 5.

## Phase 1 — SDK 52 → 53 (~1–2 days)

- [ ] `npx expo install expo@^53 --fix` (installs SDK 53 pins; RN 0.76 → 0.79, React 18 → **19**).
- [ ] Resolve **React 19** fallout: peer-dep warnings, removed string-ref/legacy patterns, type changes. Grep for any deprecated React APIs.
- [ ] `npx expo-doctor` — fix everything it flags.
- [ ] Build a dev client (`eas build -p android --profile development` or local prebuild) and smoke-test the app boots + core flows.
- [ ] Keep `newArchEnabled` explicit in `app.json` (still `true` at this hop unless you flip early — cleaner to flip in Phase 4).

## Phase 2 — SDK 53 → 54 (~2–3 days)

- [ ] `npx expo install expo@^54 --fix` (RN 0.81, React 19.1).
- [ ] **🔴 `expo-file-system` — DIRECTION CORRECTED.** This repo has **no `/next` imports**; all 7 sites use the CLASSIC API. In SDK 54 the NEW api takes the bare `expo-file-system` path and the classic one moves to **`expo-file-system/legacy`**. So rewrite these 7 imports to **`expo-file-system/legacy`** (verified `19.0.23`'s legacy build exports everything used: `documentDirectory`, `cacheDirectory`, `getInfoAsync`, `readAsStringAsync`, `writeAsStringAsync`, `makeDirectoryAsync`, `downloadAsync`, `deleteAsync`, `copyAsync`, `EncodingType`): `src/utils/docCache.js`, `src/utils/logbookDrafts.js`, `src/utils/compressPhoto.js`, `src/utils/pdfjsViewer.js`, `src/utils/api.js`, `app/reports.jsx`, `app/logbooks/daily_jobsite.jsx`. Expect deprecation warnings. ⚠️ `/legacy` is REMOVED in SDK 55 — the real rewrite is Path B's bill.
- [ ] Bump the SWM/core libs to their SDK 54 pins (gesture-handler, screens, safe-area-context, svg, webview, async-storage 2.x) via `expo install --fix`.
- [ ] **async-storage 1.x → 2.2.0 — verified near no-op** (do NOT go to 3.x, which has real breaking changes). Tarball diff: the Android SQLite files (`ReactDatabaseSupplier`, `AsyncLocalStorageUtil`) are **byte-identical**, so on-device data survives; the only API change is a type widening; this app uses only `getItem`/`setItem`/`removeItem`. Still regression-test offline drafts — as confirmation, not as a budgeted risk.
- [ ] RN 0.81 dropped bundled JSC — confirm you're on Hermes (default) or add the JSC package if anything depended on it.
- [ ] `npx expo-doctor` clean.

## Phase 3 — targetSdk 36 (~0.5 day)

- [ ] In `app.json` `expo-build-properties.android`: `compileSdkVersion: 36`, `targetSdkVersion: 36`, `buildToolsVersion: "36.0.0"` (currently all 35).
- [ ] Check Android 16 behavior changes that bite this app: **NFC pending-intent / foreground-dispatch flags** (Android tightened `PendingIntent` mutability), edge-to-edge display defaults, and any exact-alarm/notification changes. Review nfc-manager 3.17.2 issues for Android 16 specifically.

## Phase 4 — Legacy-arch config + native module pins (~1–2 days) ← RISKIEST PHASE

- [ ] **Flip `app.json:11` `newArchEnabled` → `false`.** (The reversal.)
- [ ] `npx expo install react-native-nfc-manager@3.17.2` (stable RN 0.81 old-arch).
- [ ] ~~vision-camera patch~~ **NOT NEEDED** — 4.7.3 already contains the RN 0.81 Android fix (shipped in 4.7.2). Keep 4.7.3, write no patch. Just confirm the Android build succeeds.
- [ ] **Remove WatermelonDB natives** (Task 7 left these for here): drop `@nozbe/watermelondb` (+ `@nozbe/*`) from `package.json`, remove the `simdjson` `extraPod` from `app.json` (`plugins → expo-build-properties → ios.extraPods`), and delete the `@nozbe/watermelondb` exclusion in `metro.config.js`. Re-lock.
- [ ] ⚠️ Confirm reanimated is pinned to **3.19.5** (NOT 4.x — `--fix` will try to install 4.1.1, which cannot run on legacy arch) and that **quick-crypto + @nozbe/* + the 2 babel plugins are REMOVED**.
- [ ] **Legacy-arch verification (the whole point of the reversal) — build a dev client and confirm ON LEGACY ARCH:**
  - [ ] Reanimated animations run (any `useAnimatedStyle`/gesture screens — e.g. the camera pinch-zoom).
  - [ ] vision-camera opens, captures, and the take-snapshot path works (see `CameraCaptureModal`).
  - [ ] quick-crypto operations succeed (whatever uses it — signatures/hashing).
  - [ ] NFC read fires and launches the check-in URL.

## Phase 5 — Native rebuild, smoke test, submit (~1 day + review)

- [ ] **Bump `expo.version`** in `app.json` (1.1.3 → next) so the `runtimeVersion.policy: "appVersion"` rolls the RV — otherwise existing OTA bundles could misapply to the new native build.
- [ ] `eas build -p android --profile production` → AAB.
- [ ] **On-device smoke tests on a physical Android 16 device (non-negotiable):**
  - [ ] **NFC foreground dispatch** — tap a real/test tag, confirm it opens the check-in page (this is the module with the most Android-16 + legacy-arch risk).
  - [ ] **Camera** — jobsite photo capture + the OSHA/SST card capture in `checkin.html`.
  - [ ] **Offline** — the AsyncStorage draft flow (fill a logbook offline → reopen → persists → reconnect → pushes) now that WatermelonDB is gone.
  - [ ] Login, project select, a logbook submit, a report render.
- [ ] Submit the AAB to Google Play. Confirm the console shows `targetSdk 36` accepted.
- [ ] Tag the release; note the commit + version in this runbook.

---

## Staged rollout — the operator's phone first, never the CP's

Operator ruling, and it applies whichever SDK this lands on.

The CP on 588 Thomas is the only other install. He was two weeks stale for a
month and filed unsigned compliance logs the whole time. **Distributing a broken
build to him and having no way back is the failure to avoid** — worse than any
defect this migration might introduce, because it is the one with no undo.

1. Build.
2. **The operator installs it on HIS OWN phone.** Not the CP's.
3. He runs the list below in full.
4. It holds → the CP gets it.
5. It does not → **the CP stays on a working 1.2.0**, which is why the version
   bump and the handout must not be the same event for this build. Nothing is
   published to the CP until step 3 passes.

### The device list

Not a smoke test. Each of these has cost time before, and each exercises a
native path that an SDK bump can break silently:

- [ ] **Camera at ultra-wide.** Open it, switch lens, capture.
- [ ] **A photo actually saving** — capture, then confirm it survives to the
      logbook and uploads. The capture succeeding is not the test.
- [ ] **The gate check-in.** Tap a real tag, confirm the check-in page opens
      and a worker can complete it. This is the NFC path.
- [ ] **A full daily log**, start to submitted, including the signature.
- [ ] **The offline path**: fill a logbook with the network off, background the
      app, reopen, confirm the draft persists, reconnect, confirm it pushes.

### THE CAMERA IS THE ONE TO WATCH, AND IT HAS A STANDING ORDER

It took **six device rounds** to get right, and **four of the wrong diagnoses
came from reasoning about the source rather than observing the hardware**. An
SDK bump is the most likely thing in this entire change to break it.

**If the camera regresses: STOP and report BEFORE touching
`react-native-vision-camera`.** Moving the SDK and the camera library in the
same change makes the next camera defect impossible to attribute, and unwinding
that after the fact is precisely how six rounds became six rounds.

Note this cuts against a blanket `npx expo install --fix`, which is not
surgical: it moves community packages to the SDK's `bundledNativeModules` pins
and **will** touch vision-camera and nfc-manager whether or not you want it to.
To test the SDK alone, run `--fix`, then revert those two to their current
versions before building. That isolation is the whole point of the sequencing.


## Rollback

- The migration lives on its own branch; `main` stays shippable throughout.
- If a native build regresses, the last-good SDK-52 AAB (Phase 0 baseline) can be re-submitted while you debug.
- Because `expo.version` bumped, keep the OTA production channel pointed at whichever native build is actually live so bundles don't cross runtimes.

## After Path A — schedule Path B (New Architecture) for the SDK-55 cycle

- SDK 55 (RN 0.82) **removes** the `newArchEnabled: false` opt-out, so New Arch becomes mandatory.
- By then, `react-native-nfc-manager` should have a **stable** New-Arch release (currently only `4.0.0-beta.7`) — re-check before starting; that's what makes Path B far less risky than today.
- Path B adds: Reanimated 3→4 (+`react-native-worklets`), quick-crypto 0.7→1 (+`react-native-nitro-modules`, breaking API), vision-camera 4→5 (Nitro, breaking API), nfc-manager → stable New-Arch. WatermelonDB is already gone (Task 7), which pre-clears one blocker.

## Sources
- Expo [SDK 54](https://expo.dev/changelog/sdk-54) / [SDK 53](https://expo.dev/changelog/sdk-53) changelogs, [upgrade guide](https://expo.dev/blog/expo-sdk-upgrade-guide), [New Arch guide](https://docs.expo.dev/guides/new-architecture/)
- [nfc-manager releases](https://github.com/revtel/react-native-nfc-manager/releases) (latest = 3.17.2; new-arch only in 4.0.0-beta line)
- vision-camera RN 0.81 Android: [issue #3616](https://github.com/mrousavy/react-native-vision-camera/issues/3616), [PR #3604](https://github.com/mrousavy/react-native-vision-camera/pull/3604)
- [RN 0.81 / Android 16 release post](https://reactnative.dev/blog/2025/08/12/react-native-0.81)

---

# APPENDIX — Exact command sequence for the supervised block

Run on the build machine, in order. **Do not batch phases** — verify each before moving on.

## Phase 0 — branch + known-good baseline
```
git checkout -b sdk54-path-a
eas build --platform android --profile production   # SDK 52 baseline to diff against
```
Have a physical **Android 16** device with NFC on hand. Record current `expo.version` (1.1.3).

## Phase 1 — SDK 52 → 53
```
npx expo install expo@^53 --fix
npx expo-doctor
```
Resolve **React 18 → 19** fallout. Build a dev client and smoke-test that the app boots.

## Phase 2 — SDK 53 → 54
```
npx expo install expo@^54 --fix
```

### 🔴 ISOLATE THE SDK — revert the two native modules `--fix` moves for you

`--fix` is NOT surgical. It moves community packages to the SDK's
`bundledNativeModules` pins, so it will bump **vision-camera** and
**nfc-manager** whether or not you asked. Let it, then put them back:

```
npm install --save-exact react-native-vision-camera@4.7.3
npm install --save-exact react-native-nfc-manager@3.17.2
node -p "['react-native-vision-camera','react-native-nfc-manager'].map(k=>k+'='+require('./package.json').dependencies[k]).join('  ')"
```

**Why, and this is an operator ruling rather than a preference.** The camera
took **six device rounds** to diagnose, and four of the wrong diagnoses came
from reasoning about source instead of observing hardware. If the SDK and the
camera library move in the same build, the next camera defect cannot be
attributed to either, and unwinding that afterwards is how six rounds became
six rounds.

vision-camera 5.2.3 exists and this repo is on 4.7.3. **It moves on its own,
after this, with a device test in front of it.** Same for nfc-manager: 3.17.2 is
the RN 0.81 floor and also the current stable, so it lands as a floor rather
than as a speculative bump.

Re-pin only what the BUILD says is broken, one at a time.

### Checkpoint after every phase

```
node src/utils/api36MigrationInvariants.test.cjs
```

Inert on a correct tree; it fails the moment `--fix` clobbers the reanimated
pin, takes nfc-manager to the beta, or leaves targetSdk and the architecture
setting disagreeing. Cheaper than reading a Gradle log.

### 🔴 CRITICAL — THE ONE STEP THAT SILENTLY BREAKS THE BUILD
`--fix` installs **reanimated 4.1.1**, which is **New-Architecture-ONLY** and **cannot run on
`newArchEnabled: false`**. It will re-install 4.x after ANY later `expo install`. Re-pin every time:
```
npm install --save-exact react-native-reanimated@3.19.5
node -p "require('./package.json').dependencies['react-native-reanimated']"
```
The second command MUST print `3.19.5`. If it prints `4.x`, the build will fail or misbehave at
runtime. (`3.16.x` is also wrong — it does not support RN 0.81. `3.19.x` is the only 3.x line that does.)

### expo-file-system → /legacy (7 files)
The classic API moves to `/legacy` in SDK 54 (there are **no** `/next` imports in this repo):
```
grep -rl "from 'expo-file-system'" src app | xargs sed -i "s|from 'expo-file-system'|from 'expo-file-system/legacy'|g"
grep -rn "expo-file-system" src app | grep -v "/legacy"
```
The second command should return nothing. Files affected: `src/utils/docCache.js`,
`src/utils/logbookDrafts.js`, `src/utils/compressPhoto.js`, `src/utils/pdfjsViewer.js`,
`src/utils/api.js`, `app/reports.jsx`, `app/logbooks/daily_jobsite.jsx`.
⚠️ `/legacy` is REMOVED in SDK 55 — the real rewrite is Path B's bill.

## Phase 3 — remove dead native deps
```
npm uninstall @nozbe/watermelondb react-native-quick-crypto @babel/plugin-proposal-decorators
```
`react-native-quick-crypto` is **unused** (zero imports — a WatermelonDB leftover). Then edit by hand:
- `babel.config.js` — remove `@babel/plugin-proposal-decorators`, `@babel/plugin-proposal-class-properties`
  (Watermelon `@field` leftovers; deprecated names are a live break risk on `babel-preset-expo@54`) and the
  now-redundant explicit `react-native-reanimated/plugin` (auto-injected since SDK 50).
- `metro.config.js` — drop the `@nozbe/watermelondb` web exclusion.
- `app.json` — remove the `simdjson` entry from `expo-build-properties.ios.extraPods`.

## Phase 4 — app.json native config
- `newArchEnabled: true` → **`false`**  ← the reversal Path A depends on
- `compileSdkVersion: 36`, `targetSdkVersion: 36`, `buildToolsVersion: "36.0.0"`
- bump `expo.version` `1.1.3` → `1.1.4` (rolls runtimeVersion so old OTA bundles can't misapply)
- pin `react-native-nfc-manager@3.17.2` exactly

## Phase 5 — edge-to-edge inset audit (1–2 days — THE DAY-EATER)
Mandatory at SDK 54 / API 36 and **cannot be disabled**. Audit every screen; worst offenders:
the full-screen camera modal, the `checkin.html` WebView, and the dark full-bleed layouts.

## Phase 6 — verify + build
```
npx expo-doctor
npx expo export --platform web
eas build --platform android --profile production
```
⚠️ `expo-doctor` WILL warn that reanimated 3.19.5 ≠ the SDK's 4.1.1 pin. **That warning is correct
and expected — do not "fix" it.** The web export is in the sequence because
`react-native-web` 0.19→0.21 + React 19 + `@expo/metro-runtime` 4→6 will move the web bundle.

## Phase 7 — on-device smoke tests before submitting
- **NFC foreground dispatch** — tap a real tag, check-in page opens (highest legacy-arch risk)
- **Camera** — jobsite photo + the OSHA/SST card capture (vision-camera 4.7.3, unpatched)
- **Offline** — drafts persist, reconnect drain syncs (async-storage 2 regression)
- **Offline PDFs** — cached plan opens on Android (the bundled pdf.js)
- **Inspector Mode** — cached records, no false "No Submitted Logs"
- **Edge-to-edge** — no content under the status/nav bars on any screen

## Rollback
The migration lives on its own branch; `main` stays shippable. If a build regresses, re-submit the
Phase 0 baseline AAB while debugging. Keep the OTA production channel pointed at whichever native
build is actually live so bundles don't cross runtimes.
