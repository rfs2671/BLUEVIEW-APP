# API 36 / Google Play — Path A (Legacy Architecture) Migration Runbook

**Goal:** ship `targetSdkVersion 36` (Android 16) to satisfy Google Play (deadline **Nov 1**, extended from Aug 31).
**Route:** Expo SDK 52 → 54, **legacy architecture** (`newArchEnabled: false`), keeping every native module on a **stable, both-arch-supported** version. **NOT** New Architecture (that's Path B, deferred to the SDK-55 cycle).
**Deploy type:** **native AAB rebuild + Google Play submission.** This is NOT an OTA/EAS-Update — `targetSdk`/RN/SDK changes are compiled into the binary.
**Effort:** ~6–8 focused working days. Do it in one committed block with a device on hand.

> **Why Path A:** the only New-Arch blocker is `react-native-nfc-manager` — its New-Arch support exists only in `4.0.0-beta.7` (pre-release), and the Activity/intent fix that NFC foreground dispatch needs is beta-only. NFC is load-bearing for worker check-in, so shipping beta is unacceptable. Legacy arch lets every module stay on a stable release that supports RN 0.81. Trade-off: SDK 55 removes the legacy opt-out, so New Arch (Path B) is a fast-follow — by then nfc-manager should have a stable New-Arch release.

---

## ⚠️ The three callouts to read FIRST

1. **`newArchEnabled` is a REAL reversal.** The app currently ships `newArchEnabled: true` (`app.json:11`). Path A flips it to **`false`**. This is safe *today* because reanimated 3.16, vision-camera 4.7, and quick-crypto 0.7 all support both architectures — **but you must re-verify each actually works on legacy after the flip** (see Phase 4 smoke tests). Don't assume; test.
2. **Riskiest single step: patching `react-native-vision-camera` 4.7.3 for the RN 0.81 Android build error.** There is no 4.7.4. You will likely hit an Android build failure and need to apply the community patch (see Phase 4). Budget time for this; it's the most likely thing to eat a day.
3. **Version pins move.** Every exact pin below was read from `expo@sdk-54 bundledNativeModules.json` — **re-verify at execution time** with `npx expo install --fix`, which is the source of truth for the SDK you actually install.

---

## Target versions (verify with `npx expo install --fix`)

| Package | Current | Path A target (SDK 54) | Notes |
|---|---|---|---|
| expo | ~52.0.17 | ~54 | via 53 hop |
| react-native | 0.76.9 | 0.81.x | RN 0.81 drops built-in JSC |
| react / react-dom | 18.3.1 | 19.1.x | React 19 — type/peer fallout |
| react-native-nfc-manager | ^3.14.0 | **3.17.2** | stable, RN 0.81 **old-arch** support |
| react-native-vision-camera | ^4.7.3 | 4.7.3 **+ RN0.81 Android patch** | no 4.7.4; see Phase 4 |
| react-native-reanimated | ~3.16.1 | **stay ~3.16.x** | v3 supports legacy; do NOT go to v4 (v4 is new-arch-only) |
| react-native-quick-crypto | ^0.7.0 | **stay 0.7.x** | v0.7 supports legacy; v1 is Nitro/new-arch |
| react-native-gesture-handler | ~2.20.2 | ~2.28.0 | |
| react-native-screens | ~4.4.0 | ~4.16.0 | |
| react-native-safe-area-context | 4.12.0 | ~5.6.0 | major bump |
| @react-native-async-storage/async-storage | 1.23.1 | 2.2.0 | major bump — offline store, test carefully |
| @react-native-community/netinfo | 11.4.1 | 11.4.1 | unchanged |
| react-native-svg | 15.8.0 | 15.12.1 | |
| react-native-webview | 13.12.5 | 13.15.0 | |
| @nozbe/watermelondb | ^0.27.1 | **REMOVE** | JS already gone (Task 7 `e8bf396`); drop dep + simdjson pod here |
| expo-* (router, updates, file-system, image-picker, constants, build-properties, …) | SDK 52 pins | SDK 54 pins | lockstep via `expo install --fix` |

> On legacy arch you deliberately **hold reanimated at v3 and quick-crypto at v0.7** — upgrading them (v4 / v1) forces New Arch. That's Path B.

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
- [ ] **`expo-file-system` import change:** the `expo-file-system/next` API graduated — update imports from `expo-file-system/next` → `expo-file-system` (and check the legacy API usages). **This is used by the offline photo-persistence path (`logbookDrafts.persistPhoto`) — verify photo save/load still works.**
- [ ] Bump the SWM/core libs to their SDK 54 pins (gesture-handler, screens, safe-area-context, svg, webview, async-storage 2.x) via `expo install --fix`.
- [ ] **async-storage 1.x → 2.x is a major bump** and it's the backbone of ALL offline (drafts, project cache, offline queue) — regression-test offline drafts + check-in cache after this.
- [ ] RN 0.81 dropped bundled JSC — confirm you're on Hermes (default) or add the JSC package if anything depended on it.
- [ ] `npx expo-doctor` clean.

## Phase 3 — targetSdk 36 (~0.5 day)

- [ ] In `app.json` `expo-build-properties.android`: `compileSdkVersion: 36`, `targetSdkVersion: 36`, `buildToolsVersion: "36.0.0"` (currently all 35).
- [ ] Check Android 16 behavior changes that bite this app: **NFC pending-intent / foreground-dispatch flags** (Android tightened `PendingIntent` mutability), edge-to-edge display defaults, and any exact-alarm/notification changes. Review nfc-manager 3.17.2 issues for Android 16 specifically.

## Phase 4 — Legacy-arch config + native module pins (~1–2 days) ← RISKIEST PHASE

- [ ] **Flip `app.json:11` `newArchEnabled` → `false`.** (The reversal.)
- [ ] `npx expo install react-native-nfc-manager@3.17.2` (stable RN 0.81 old-arch).
- [ ] **vision-camera RN 0.81 Android build patch — the risky step.** vision-camera 4.7.3 hits an Android build error on RN 0.81 with no 4.7.4 released. Apply the community fix (see issue [mrousavy/react-native-vision-camera#3616](https://github.com/mrousavy/react-native-vision-camera/issues/3616) / PR [#3604](https://github.com/mrousavy/react-native-vision-camera/pull/3604)) via `patch-package` pinned to 4.7.3, OR bump to the smallest 4.7.x that builds if one has shipped by execution time. **Do this on a throwaway build first — expect iteration.**
- [ ] **Remove WatermelonDB natives** (Task 7 left these for here): drop `@nozbe/watermelondb` (+ `@nozbe/*`) from `package.json`, remove the `simdjson` `extraPod` from `app.json` (`plugins → expo-build-properties → ios.extraPods`), and delete the `@nozbe/watermelondb` exclusion in `metro.config.js`. Re-lock.
- [ ] Confirm reanimated is **held at ~3.16.x** and quick-crypto at **0.7.x** (NOT v4 / v1).
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
