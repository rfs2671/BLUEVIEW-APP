// PR #52 — canonical design-token surface for the app.
//
// IMPORTANT: this module does NOT fork the existing scales. 86 files
// already import { spacing, borderRadius, typography, colors } from
// '../styles/theme'; tokens.js re-exports those SAME objects so an
// import from here and an import from styles/theme resolve to identical
// values. Forking the spacing scale (e.g. md:16 vs md:12) would have
// produced two competing systems — the exact inconsistency this PR
// exists to remove.
//
// What tokens.js ADDS on top of the established theme:
//   • typeScale — a t-shirt typography scale WITH explicit lineHeights
//     (the existing named typography roles carried fontSize but not
//     lineHeight, which is what makes multi-line text read cleanly).
//   • text — named emphasis aliases (primary / secondary / tertiary /
//     disabled / inverse) mapped onto the existing colors.text
//     hierarchy. Implemented as getters so they track runtime theme
//     switches (applyTheme mutates `colors` in place).
//   • radius — a shorter alias of borderRadius.
//
// New screens/components should import from here. Existing imports from
// styles/theme stay valid — same source of truth, zero migration churn.

import {
  colors,
  spacing,
  borderRadius,
  typography,
  applyTheme,
} from '../styles/theme';

// Re-export the established scales unchanged (single source of truth).
export { colors, spacing, borderRadius, typography, applyTheme };

// Shorter alias for border radius.
export const radius = borderRadius;

// PR #52 — typography scale with explicit line-heights. Additive: does
// NOT replace the existing named roles (hero / h1 / h2 / h3 / body /
// small / label / stat). Spread one of these when you want size +
// line-height together, e.g. `style={[typeScale.lg, { color: ... }]}`.
export const typeScale = {
  xs:   { fontSize: 11, lineHeight: 14 },
  sm:   { fontSize: 13, lineHeight: 18 },
  md:   { fontSize: 15, lineHeight: 22 },
  lg:   { fontSize: 17, lineHeight: 24 },
  xl:   { fontSize: 20, lineHeight: 28 },
  xxl:  { fontSize: 24, lineHeight: 30 },
  xxxl: { fontSize: 28, lineHeight: 36 },
};

// PR #52 — named text-emphasis aliases over the existing colors.text
// hierarchy. Getters so a light/dark theme switch (applyTheme) is
// reflected immediately at access time.
export const text = {
  get primary()   { return colors.text.primary; },
  get secondary() { return colors.text.secondary; },
  get tertiary()  { return colors.text.muted; },
  get disabled()  { return colors.text.subtle; },
  get inverse()   { return colors.white; },
};

export default {
  colors,
  spacing,
  borderRadius,
  radius,
  typography,
  typeScale,
  text,
  applyTheme,
};
