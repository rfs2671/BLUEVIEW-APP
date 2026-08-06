# API 36 / Google Play — Path A (Legacy Architecture) Migration Runbook

**Goal:** ship `targetSdkVersion 36` (Android 16) to satisfy Google Play.

> ## 🚨 DEADLINE — VERIFY BEFORE PLANNING ANYTHING
> Google's hard date is **August 31, 2026**. The **November 1 date is NOT automatic** — it must be
> **actively requested and granted** via the Play Console → Policy status page. An earlier draft of
> this runbook recorded "Nov 1, extended from Aug 31" as settled fact; that was an assumption, not a
> verification. **Phase 0 task #1: confirm the extension was filed AND granted.** If it was not, this
> migration (8–10 days with the edge-to-edge work below) has essentially no slack against Play review.
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
