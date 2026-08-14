// ─── CP-screen design tokens — MEASURED, not designed ────────────────────────
//
// WHAT THIS IS
//   A closed set of every literal style value in use today on the CP surfaces:
//     app/logbooks/*.jsx  (13 files)   app/login.jsx
//     app/settings.jsx                 app/documents.jsx
//
//   The scale below was built by COUNTING those files, not by picking a nice
//   ramp. Every value here is a value that ships right now. Nothing was
//   rounded, merged or "cleaned up", so adopting a token can never move a
//   pixel. Where the measured set is ugly (fontSize 17 and 22; borderRadius 11
//   and 13) the ugliness is preserved and annotated — the point of a measured
//   scale is that it tells the truth about the codebase.
//
// NOTHING IMPORTS THIS YET.
//   Creating the scale and migrating call sites are separate steps on purpose.
//   This file is inert until a later change starts consuming it.
//
// NAMING
//   Keys are MECHANICAL — derived from the value (`f13` = fontSize 13,
//   `r11` = borderRadius 11, `s120` = 120dp of space, `a12` = alpha 0.12).
//   They are deliberately NOT semantic. The source files do not state design
//   intent for these numbers, so inventing names like `caption` / `pill` /
//   `overlay` would be asserting intent that nobody wrote down. Mechanical
//   names also make migration a pure find-and-replace with no judgement calls.
//
//   The palette is the one exception: colour keys are hue/lightness family
//   names (`blue500`, `amber400`) because a hue IS readable off the hex. The
//   name carries no meaning beyond "this hex"; the SEMANTIC layer already
//   exists in ./semanticColors.js and stays the place to encode meaning.
//
// RELATIONSHIP TO THE OTHER SCALES
//   ./theme.js          — spacing / borderRadius / typography, the scale the
//                         CP screens already import. This file does NOT fork
//                         it; it catalogues what the screens use INSTEAD of
//                         it. Overlap is called out per-block below.
//   ./semanticColors.js — withAlpha() + the semantic state tokens. `tint`
//                         below is that same helper, re-exported so an alpha
//                         colour is always DERIVED from a base and can never
//                         drift from it.
//   ../theme/tokens.js  — an earlier token module (typeScale/text/radius). It
//                         has ZERO importers in app/ or src/ as of this
//                         commit; it is not wired to anything here.
//
// ─────────────────────────────────────────────────────────────────────────────

import { withAlpha } from './semanticColors';

// ─── Opaque colour bases ─────────────────────────────────────────────────────
//
// 15 distinct opaque literals, 57 occurrences, plus `black` which survives
// only as a tint base. Counts are occurrences across the 16 measured files.
//
// RE-MEASURED after the osha_log + scaffold_maintenance port onto the shared
// stepper, exactly as the U1 daily-jobsite rebuild required before it. Those
// two screens moved onto the token file and took their literals with them, so
// `cyan400` (#22d3ee) and `red500` (#ef4444) now have NO use anywhere in the
// measured set and are GONE from this palette. A measured scale may not keep
// shipping a value nothing measures — the same rule that removed `shadow`.
//
// NOT A CLAIM ABOUT THE WHOLE APP. Both colours are still written elsewhere
// (CameraOverlay, LogbookLockBar, RiskScoreCircle); this file measures the 16
// CP screens and says nothing about the rest.
//
// FIVE of these are an exact string match for a hex already defined in
// theme.js and should resolve to that token, not to this palette, when the
// migration happens: blue500 (theme colors.primary), amber400 (colors.warning
// / state.attention), green400 (colors.success), red400 (colors.error /
// state.criticalText), and blue400 (outdoor.accent). `white` is a SIXTH match
// by colour but not by string — the screens write '#fff', theme.js writes
// '#ffffff'.
export const palette = Object.freeze({
  blue500:   '#3b82f6', // 13 uses, 6 files — exact match: theme colors.primary
  blue300:   '#93c5fd', // 9 uses, 3 files
  white:     '#fff',    // 9 uses, 8 files — same COLOUR as theme colors.white ('#ffffff'), different literal
  blue400:   '#60a5fa', // 6 uses, 3 files — exact match: theme outdoor.accent
  amber400:  '#fbbf24', // 4 uses, 2 files — exact match: theme colors.warning / state.attention
  green400:  '#4ade80', // 3 uses, 1 file  — exact match: theme colors.success
  red400:    '#f87171', // 3 uses, 2 files — exact match: theme colors.error / state.criticalText
  gray500:   '#6b7280', // 2 uses, 1 file
  violet500: '#8b5cf6', // 2 uses, 2 files
  cyan500:   '#06b6d4', // 1 use,  1 file
  emerald500:'#10b981', // 1 use,  1 file
  slate400:  '#94a3b8', // 1 use,  1 file
  pink500:   '#ec4899', // 1 use,  1 file
  pink400:   '#f472b6', // 1 use,  1 file
  amber500:  '#f59e0b', // 1 use,  1 file
  black:     '#000000', // 0 standalone uses — survives as a TINT BASE only
});

// ─── Alpha steps ─────────────────────────────────────────────────────────────
//
// The union of every opacity in use on a colour: 55 withAlpha() calls plus 28
// hand-written rgba() literals = 16 distinct steps. This is NOT a designed
// ramp — 0.03/0.07 are one-offs, kept because they ship.
//
// RE-MEASURED after the toolbox_talk port. `a02` (0.02) was that screen's
// alone and now has NO use in the measured set, so it is gone — a measured
// scale may not keep shipping a value nothing measures.
//
// NOTE the overlap with semanticColors.js's canonical STATE steps (fill 0.12,
// border 0.3). Those two are the only steps with a stated meaning; every other
// step below is decorative chrome.
export const alpha = Object.freeze({
  a03: 0.03, a04: 0.04, a05: 0.05, a06: 0.06,
  a07: 0.07, a08: 0.08, a10: 0.1,  a15: 0.15,
  a20: 0.2,  a25: 0.25, a30: 0.3,  a35: 0.35, a40: 0.4,
  a50: 0.5,  a60: 0.6,  a90: 0.9,
});

// ─── tint(base, step) ────────────────────────────────────────────────────────
// withAlpha under a shorter name. Alpha colours are always DERIVED from a
// palette base so they cannot fork from it (the 44 hand-written rgba()
// literals measured above are exactly that fork: `rgba(59,130,246,0.2)`,
// `rgba(59, 130, 246, 0.1)` and `rgba(59,130,246,0.10)` are three spellings of
// two colours, all of them palette.blue500 at an `alpha` step).
export const tint = withAlpha;

// Every base+step pair actually in use, as data. Two purposes: it is the
// migration checklist, and a test can assert that `palette` × `alpha` still
// covers all of it. `uses` is the occurrence count.
//
// RE-MEASURED after the toolbox_talk port — the third screen onto the shared
// stepper, after U1's daily_jobsite and #123's osha_log + scaffold_maintenance.
// It took 12 withAlpha calls and 6 rgba() literals out of the measurement with
// it. These numbers are the CURRENT source, not the original audit snapshot.
//
// `via` records HOW the value is written today:
//   'withAlpha' — already the sanctioned helper idiom (55 occurrences).
//   'rgba'      — a hand-written rgba() string literal (28 occurrences).
// Keeping them apart matters: counting the withAlpha bases as raw colour
// literals inflates the apparent colour debt from 28 to 83.
export const MEASURED_TINTS = Object.freeze([
  { base: 'black',      step: 'a04',  uses: 2,   via: 'withAlpha' },
  { base: 'black',      step: 'a06',  uses: 2,   via: 'withAlpha' },
  { base: 'black',      step: 'a60',  uses: 1,   via: 'withAlpha' },
  { base: 'black',      step: 'a90',  uses: 1,   via: 'withAlpha' },
  { base: 'blue300',    step: 'a30',  uses: 1,   via: 'rgba' },
  { base: 'blue300',    step: 'a35',  uses: 1,   via: 'rgba' },
  { base: 'blue300',    step: 'a40',  uses: 1,   via: 'rgba' },
  { base: 'blue400',    step: 'a10',  uses: 1,   via: 'rgba' },
  { base: 'blue400',    step: 'a15',  uses: 1,   via: 'rgba' },
  { base: 'blue400',    step: 'a25',  uses: 1,   via: 'rgba' },
  { base: 'blue400',    step: 'a30',  uses: 1,   via: 'rgba' },
  { base: 'blue500',    step: 'a08',  uses: 1,   via: 'rgba' },
  { base: 'blue500',    step: 'a10',  uses: 4,   via: 'rgba' },
  { base: 'blue500',    step: 'a15',  uses: 2,   via: 'rgba' },
  { base: 'blue500',    step: 'a20',  uses: 4,   via: 'rgba' },
  { base: 'blue500',    step: 'a30',  uses: 1,   via: 'rgba' },
  { base: 'blue500',    step: 'a50',  uses: 3,   via: 'rgba' },
  { base: 'violet500',  step: 'a15',  uses: 1,   via: 'rgba' },
  { base: 'violet500',  step: 'a20',  uses: 2,   via: 'rgba' },
  { base: 'violet500',  step: 'a30',  uses: 1,   via: 'rgba' },
  { base: 'violet500',  step: 'a40',  uses: 2,   via: 'rgba' },
  { base: 'white',      step: 'a03',  uses: 1,   via: 'withAlpha' },
  { base: 'white',      step: 'a04',  uses: 11,  via: 'withAlpha' },
  { base: 'white',      step: 'a05',  uses: 14,  via: 'withAlpha' },
  { base: 'white',      step: 'a06',  uses: 4,   via: 'withAlpha' },
  { base: 'white',      step: 'a07',  uses: 1,   via: 'withAlpha' },
  { base: 'white',      step: 'a08',  uses: 5,   via: 'withAlpha' },
  { base: 'white',      step: 'a10',  uses: 12,  via: 'withAlpha' },
  { base: 'white',      step: 'a15',  uses: 1,   via: 'withAlpha' },
]);

// ─── Type sizes ──────────────────────────────────────────────────────────────
//
// 13 distinct fontSize literals, 192 occurrences.
//
// The headline finding: f12 (43 uses) and f13 (43 uses) are jointly the most
// common sizes on the CP screens and NEITHER has an entry in
// theme.js `typography.sizes` ({ xs:11, sm:14, md:16, lg:18, xl:24 }). 86 of
// the 192 fontSize literals — nearly half — are two sizes the scale does not
// name. Meanwhile `typography.sizes.xl` (24) is referenced ZERO times anywhere
// in app/ or src/, and `typography.sizes.md` (16) zero times as well.
export const fontSize = Object.freeze({
  f10: 10, // 8 uses,  6 files
  f11: 11, // 25 uses, 9 files  — theme typography.sizes.xs
  f12: 12, // 43 uses, 11 files — JOINT MOST-USED, no theme token
  f13: 13, // 43 uses, 15 files — JOINT MOST-USED, no theme token
  f14: 14, // 31 uses, 16 files — theme typography.sizes.sm
  f15: 15, // 20 uses, 10 files
  f16: 16, // 8 uses,  7 files  — theme typography.sizes.md (0 references app-wide)
  f17: 17, // 3 uses,  3 files
  f18: 18, // 2 uses,  2 files  — theme typography.sizes.lg
  f20: 20, // 5 uses,  5 files
  f22: 22, // 1 use,   1 file
  f32: 32, // 2 uses,  2 files
  f48: 48, // 1 use,   1 file
});

// ─── Font weights ────────────────────────────────────────────────────────────
// 5 distinct, 95 occurrences. Strings, because React Native's fontWeight is a
// string in every one of the measured call sites.
export const fontWeight = Object.freeze({
  w200: '200', // 3 uses,  3 files
  w500: '500', // 26 uses, 9 files
  w600: '600', // 50 uses, 15 files
  w700: '700', // 15 uses, 10 files
  w800: '800', // 1 use,   1 file
});

// ─── Letter spacing ──────────────────────────────────────────────────────────
// 6 distinct, 14 occurrences. `ls1` also appears via theme typography.label
// (letterSpacing 2) — that spread is NOT counted here, only literals are.
export const letterSpacing = Object.freeze({
  lsNeg1: -1,  // 1 use
  ls05:   0.5, // 7 uses, 5 files
  ls08:   0.8, // 1 use
  ls1:    1,   // 3 uses, 3 files
  ls6:    6,   // 1 use
});

// ─── Border radii ────────────────────────────────────────────────────────────
//
// 9 distinct numeric borderRadius literals, 17 occurrences. theme.js
// borderRadius ({ sm:8, md:12, lg:16, xl:24, xxl:32, full:9999 }) covers only
// r8 of them — every other literal below is off-scale.
//
// r11 and r13 are NOT design steps: they are half of a fixed box (22x22 and
// 26x26) written out to make a circle. They are catalogued because they ship,
// but the correct migration for those two is borderRadius.full, not a token.
export const radius = Object.freeze({
  r2:  2,  // 2 uses, 1 file
  r3:  3,  // 2 uses, 1 file
  r4:  4,  // 3 uses, 3 files
  r5:  5,  // 1 use   — half of a 10x10 dot
  r8:  8,  // 1 use   — theme borderRadius.sm
  r11: 11, // 5 uses, 5 files — half of a 22x22 toggle dot (circle, not a step)
  r20: 20, // 1 use
});

// ─── Space ───────────────────────────────────────────────────────────────────
//
// 12 distinct numeric padding / margin / gap literals, 81 occurrences.
// theme.js spacing is { xs:4, sm:8, md:16, lg:24, xl:32, xxl:48 }, so s4, s8
// and s16 duplicate existing tokens and the other nine are off-scale.
//
// s100 / s120 / s140 are all `paddingBottom` on a ScrollView content style —
// bottom clearance for the floating action bar, not a spacing step. s120 alone
// accounts for 8 of the 13 occurrences of the three.
export const space = Object.freeze({
  s0:   0,   // 4 uses,  4 files
  s1:   1,   // 3 uses,  2 files
  s2:   2,   // 16 uses, 8 files
  s3:   3,   // 6 uses,  4 files
  s4:   4,   // 28 uses, 13 files — theme spacing.xs
  s6:   6,   // 4 uses,  3 files
  s8:   8,   // 5 uses,  3 files  — theme spacing.sm
  s12:  12,  // 1 use
  s16:  16,  // 1 use            — theme spacing.md
  s100: 100, // 4 uses,  4 files — scroll bottom clearance
  s120: 120, // 8 uses,  8 files — scroll bottom clearance
  s140: 140, // 1 use            — scroll bottom clearance
});

// ─── Border widths ───────────────────────────────────────────────────────────
// 2 distinct, 82 occurrences. bw1 is 76 of them.
export const borderWidth = Object.freeze({
  bw1: 1, // 76 uses, 15 files
  bw2: 2, // 6 uses,  5 files
});

// ─── Standalone opacity ──────────────────────────────────────────────────────
// The `opacity:` style prop (distinct from a colour's alpha channel).
// 4 distinct, 9 occurrences.
export const opacity = Object.freeze({
  o50: 0.5,  // 4 uses, 4 files — the disabled/busy dim
  o80: 0.8,  // 2 uses, 2 files
  o90: 0.9,  // 1 use
});

// ─── Shadow ──────────────────────────────────────────────────────────────────
//
// NO shadow exists across the 16 measured files any more.
//
// There used to be exactly one (the old app/logbooks/daily_jobsite.jsx:1475-1476).
// The U1 rebuild of that screen does not use a shadow, so the single sample
// this scale was extrapolated from is gone. Rather than keep shipping a
// `shadow.elevated` that nothing measures — the exact dishonesty this file's
// test exists to catch — the export is removed. If a shadow is wanted again,
// it is a DESIGNED value and belongs in theme.js, not in a measured scale.
//
// The theme's own per-theme `colors.shadow` block is a SEPARATE thing and is
// untouched by this.

export default {
  palette,
  alpha,
  tint,
  MEASURED_TINTS,
  fontSize,
  fontWeight,
  letterSpacing,
  radius,
  space,
  borderWidth,
  opacity,
};
