// Phase 1 Week 11-12 PR-B — Defcon 3-tier urgency UI helpers.
//
// Frontend mirror of backend lib.statistical_engine.defcon.TIER_TO_COLOR.
// The backend response already includes `tier_color`, so this mapping is
// presentational sugar — but keeping the lookup here means call sites
// don't walk the colors.status.* tree directly and the 3-bucket palette
// (success/warning/error) stays canonical across CompliancePanel,
// projects/index.jsx and the Defcon detail screen.
//
// Locked tier → theme mapping (Stage 2.A L2):
//   NORMAL    → status.success    (green)
//   ELEVATED  → status.warning    (amber)
//   IMMEDIATE → status.error      (red)
//
// Unknown / null tiers fall through to NORMAL so the UI never crashes
// on a partial backend response.

import { colors } from '../styles/theme';

export const DEFCON_TIERS = ['NORMAL', 'ELEVATED', 'IMMEDIATE'];

export function tierToTheme(tier) {
  switch (tier) {
    case 'IMMEDIATE':
      return { fg: colors.status.error,   bg: colors.status.errorBg   };
    case 'ELEVATED':
      return { fg: colors.status.warning, bg: colors.status.warningBg };
    case 'NORMAL':
    default:
      return { fg: colors.status.success, bg: colors.status.successBg };
  }
}

export function tierToLabel(tier) {
  switch (tier) {
    case 'IMMEDIATE': return 'Immediate';
    case 'ELEVATED':  return 'Elevated';
    case 'NORMAL':    return 'Normal';
    default:          return 'Normal';
  }
}

// Relative-time helper for the backend's last_evaluated_at ISO UTC string.
// Returns 'just now' / 'N minutes ago' / 'N hours ago' / 'N days ago'.
// null on parse failure.
export function formatTimeAgo(isoOrDate) {
  if (!isoOrDate) return null;
  const t = new Date(isoOrDate).getTime();
  if (!Number.isFinite(t)) return null;
  const ms = Date.now() - t;
  if (ms < 0) return 'just now';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
  const day = Math.floor(hr / 24);
  return `${day} day${day === 1 ? '' : 's'} ago`;
}

export default {
  DEFCON_TIERS,
  tierToTheme,
  tierToLabel,
  formatTimeAgo,
};
