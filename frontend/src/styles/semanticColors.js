// ─── Semantic color taxonomy ─────────────────────────────────────────────────
//
// Single source of truth for STATE colors. Background: the 2026-07-23 UI audit
// (docs/audits/ui-inventory-2026-07-23.md, Part 3) found the same hardcoded
// literal carrying many unrelated meanings — red #ef4444 encoded delete-icon
// chrome, a "MAJOR B" classification, an SSM role badge, an "unchecked" input,
// a warning banner, AND live enforcement severity, all at once. Green #4ade80
// was likewise both a decorative icon tint and a live "verified" signal.
//
// This module collapses every STATE-encoding color to exactly FOUR tokens:
//
//   neutral   — default, NO state. Decorative chrome, "off"/inactive, and
//               identity badges (role, classification) resolve here.
//   attention — amber. Needs review / advisory (soft warnings, not-yet-passed).
//   critical  — red. Action required (live enforcement, errors, expiries).
//   verified  — green. Confirmed clear (complete, signed, active, resolved, pass).
//
// Plus non-state groupings (chrome / border / surface / text) re-exported from
// the theme so a call site can pull everything it needs from one module.
//
// ── THEME BEHAVIOR ────────────────────────────────────────────────────────────
// `neutral` follows the active theme — it IS the muted grey that decorative
// "off" states (`device.is_active ? green : colors.text.muted`) already use, so
// routing them here is a no-op. The three SATURATED state tokens
// (attention / critical / verified) are theme-INSENSITIVE and pinned to the
// exact values the hardcoded literals already rendered in BOTH themes. Those
// literals never adapted to light mode; preserving that exactly is what makes
// the semantic-site migration (commit 2) a zero-pixel change. Making them
// theme-aware later is a separate, intentional edit.
//
// ── criticalFill ──────────────────────────────────────────────────────────────
// `critical` (#ef4444) on white text = 3.76:1 — FAILS WCAG AA (4.5:1).
// `criticalFill` (#dc2626) on white text = 4.83:1 — PASSES AA. Use it for
// FILLED destructive controls that carry white label text (e.g. ConfirmDialog's
// confirm button); use `critical` for text/icons/borders on dark surfaces.

import { colors } from './theme';

// Theme-insensitive saturated state values — identical to the literals they
// replace, so semantic call-site migration produces no visual change.
const ATTENTION = '#fbbf24'; // amber-400  (matches theme warning / current literals)
const CRITICAL = '#ef4444'; // red-500    (dominant literal; matches RiskScoreCircle BAND_RED)
const CRITICAL_FILL = '#dc2626'; // red-600    (AA-contrast fill behind white text)
const VERIFIED = '#22c55e'; // green-500  (matches RiskScoreCircle BAND_GREEN post-fix)

// State tokens. `neutral` is a live getter so it tracks applyTheme(); the
// saturated tokens are constants (see THEME BEHAVIOR above).
export const semantic = {
  get neutral() { return colors.text.muted; },
  get attention() { return ATTENTION; },
  get critical() { return CRITICAL; },
  get criticalFill() { return CRITICAL_FILL; },
  get verified() { return VERIFIED; },
};

// ── Non-state groupings (theme-aware, re-exported for one-import ergonomics) ───

// Chrome: brand accent + neutral icon tints for decorative / non-state icons.
export const chrome = {
  get brand() { return colors.primary; }, // primary blue — nav, selected accent, links
  get icon() { return colors.text.secondary; }, // default neutral icon tint
  get iconMuted() { return colors.text.muted; }, // decorative / "off" icon tint
};

export const border = {
  get subtle() { return colors.border.subtle; },
  get medium() { return colors.border.medium; },
  get strong() { return colors.border.strong; },
};

export const surface = {
  get card() { return colors.glass.card; },
  get glass() { return colors.glass.background; },
  get glassHover() { return colors.glass.backgroundHover; },
};

export const text = {
  get primary() { return colors.text.primary; },
  get secondary() { return colors.text.secondary; },
  get muted() { return colors.text.muted; },
  get subtle() { return colors.text.subtle; },
};

export default { semantic, chrome, border, surface, text };
