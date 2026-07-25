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
const CRITICAL_TEXT = '#f87171'; // red-400 — critical for TEXT. #ef4444 as text on
// glass cards is 4.03:1 (surface-1) / 3.33:1 (surface-2), below WCAG AA 4.5:1.
// #f87171 clears it — page 6.41:1, card 5.48:1, elevated 4.53:1 — same hue,
// one step lighter. Use for red TEXT; keep `critical` for icons/borders/dots
// (they only need 3:1 and pass).
const CRITICAL_FILL = '#dc2626'; // red-600    (AA-contrast fill behind white text)
const VERIFIED = '#22c55e'; // green-500  (matches RiskScoreCircle BAND_GREEN post-fix)

// State tokens. `neutral`/`neutralStrong` are live getters so they track
// applyTheme(); the saturated tokens are constants (see THEME BEHAVIOR above).
//
// `neutral` (muted grey, white@0.40 dark) is for decorative ICONS/borders — it
// clears the 3:1 non-text bar on all surfaces but only 3.6–3.8:1 as text, so it
// must not carry body text on cards. `neutralStrong` (white@0.60 dark =
// text.secondary) is the neutral for decorative TEXT: it clears WCAG AA 4.5:1
// on every dark surface — page 6.96:1, card(6%) 6.39:1, elevated(12%) 5.61:1.
// Use it wherever a former state COLOR was carrying text (e.g. MAJOR B class
// badges, role badges, delete/clear button labels).
// Neutral pill/chip background tint. Slate-400 (#94a3b8) at 18% — the same
// neutral family as the RiskScoreCircle "pending" band — so an identity badge
// (MAJOR B, role) reads as neutral chrome, not an alarm. Theme-insensitive
// (mirrors the theme-blind rgba() badge fills it replaces).
const NEUTRAL_BG = 'rgba(148, 163, 184, 0.18)';

// ── withAlpha — the anti-drift primitive ──────────────────────────────────────
// Derive an `rgba()` string from a hex base + opacity. The base is ALWAYS a
// canonical hex — a semantic state token (CRITICAL/ATTENTION/VERIFIED) for
// state tints, or a pinned neutral (#ffffff/#000000/#94a3b8/…) for decorative
// chrome. Because the tint is computed from the base, it can NEVER drift from
// it: change the token, every fill/border derived from it follows. This
// replaces hand-written `rgba(239,68,68,0.1)` literals that silently forked
// into 11 different reds at 14 different opacities (see the 2026-07-25 audit).
//
// Accepts #rgb, #rrggbb, or #rrggbbaa (any hex alpha is dropped; the `opacity`
// argument is authoritative). Returns e.g. 'rgba(239, 68, 68, 0.12)'.
export function withAlpha(hex, opacity) {
  let h = String(hex).replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  if (h.length === 8) h = h.slice(0, 6);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

// ── Canonical state-tint opacities ────────────────────────────────────────────
// The WHOLE app collapses its state fills/borders to exactly these two steps.
// Chosen as the modes of prior usage: fills clustered at 0.10–0.15 (0.12 is the
// balancing midpoint), borders were dominated by 0.30. A state card is a FILL
// (criticalBg) with a matching BORDER (criticalBorder) one step stronger.
const STATE_FILL = 0.12;
const STATE_BORDER = 0.3;

export const semantic = {
  get neutral() { return colors.text.muted; },
  get neutralStrong() { return colors.text.secondary; },
  get neutralBg() { return NEUTRAL_BG; },
  get attention() { return ATTENTION; },
  get critical() { return CRITICAL; },
  get criticalText() { return CRITICAL_TEXT; },
  get criticalFill() { return CRITICAL_FILL; },
  get verified() { return VERIFIED; },

  // ── Derived state tints (fill + border), from the base tokens above via
  //    withAlpha. These fix the theme drift the audit found: they are built on
  //    the SEMANTIC bases (#ef4444 / #fbbf24 / #22c55e), NOT theme.status's
  //    stale successBg/errorBg bases (#4ade80 / #f87171). Migrating a call site
  //    to these therefore shifts both hue (green #4ade80→#22c55e, red
  //    #f87171→#ef4444) and opacity to the canonical steps.
  get criticalBg() { return withAlpha(CRITICAL, STATE_FILL); },
  get criticalBorder() { return withAlpha(CRITICAL, STATE_BORDER); },
  get attentionBg() { return withAlpha(ATTENTION, STATE_FILL); },
  get attentionBorder() { return withAlpha(ATTENTION, STATE_BORDER); },
  get verifiedBg() { return withAlpha(VERIFIED, STATE_FILL); },
  get verifiedBorder() { return withAlpha(VERIFIED, STATE_BORDER); },
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
