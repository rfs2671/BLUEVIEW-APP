// PR #15D — frontend port of backend.lib.statistical_engine.live_mutation
//   .hazard_ratio_to_color_tier(ratio) -> str
//
// F2 + T8' locks: this file mirrors the backend helper byte-for-byte.
// Backend is the canonical source of truth; this file exists because
// the CompliancePanel needs to colorise hazard ratios client-side
// without re-querying the API. If the backend logic changes, this
// file MUST be updated in the same PR — divergence is a contract
// break (see L6 in PR #15D Stage 1 design notes).
//
// Returns one of: 'green' | 'yellow' | 'amber' | 'orange' | 'red'
// | 'neutral'. Consumers map the tier name to theme.colors.status.*
// via tierToStatusColor() below.

import { colors } from '../styles/theme';

// ── L6 thresholds (must match backend live_mutation.py:223) ───────
//   ratio < 0.75       → 'green'    (below cohort risk)
//   0.75 <= r < 1.5    → 'yellow'   (around cohort risk)
//   1.5  <= r < 3.0    → 'amber'    (elevated risk)
//   3.0  <= r < 4.0    → 'orange'   (high risk)
//   ratio >= 4.0       → 'red'      (critical risk)
//   null / NaN / inf / negative → 'neutral'
export function hazardRatioToColorTier(ratio) {
  if (ratio === null || ratio === undefined) return 'neutral';
  const r = Number(ratio);
  if (Number.isNaN(r) || !Number.isFinite(r)) return 'neutral';
  if (r < 0) return 'neutral';   // mathematically impossible — defensive
  if (r < 0.75) return 'green';
  if (r < 1.5)  return 'yellow';
  if (r < 3.0)  return 'amber';
  if (r < 4.0)  return 'orange';
  return 'red';
}

// ── Tier → theme color (foreground + background) ─────────────────
// D1 lock — 5 risk tiers use 5 status colors. 'neutral' falls back
// to text.muted for the fg and transparent for the bg.
//
// Consumers do not need to import `colors` themselves; pass the tier
// string and get the styled pair back.
export function tierToStatusColor(tier) {
  switch (tier) {
    case 'green':
      return { fg: colors.status.success,  bg: colors.status.successBg  };
    case 'yellow':
      return { fg: colors.status.caution,  bg: colors.status.cautionBg  };
    case 'amber':
      return { fg: colors.status.warning,  bg: colors.status.warningBg  };
    case 'orange':
      return { fg: colors.status.elevated, bg: colors.status.elevatedBg };
    case 'red':
      return { fg: colors.status.error,    bg: colors.status.errorBg    };
    case 'neutral':
    default:
      return { fg: colors.text.muted,      bg: colors.transparent       };
  }
}

// Convenience: ratio → {fg, bg} in one call.
export function hazardRatioToStatusColor(ratio) {
  return tierToStatusColor(hazardRatioToColorTier(ratio));
}

export default {
  hazardRatioToColorTier,
  tierToStatusColor,
  hazardRatioToStatusColor,
};
