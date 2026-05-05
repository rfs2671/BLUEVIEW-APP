/**
 * Phase B1b.1 — notification preference presets.
 *
 * The settings page renders three radio cards (Critical only,
 * Standard, Everything) plus an Advanced section. Each preset
 * generates a complete prefs shape (signal_kind_overrides +
 * channel_routes_default) for ALL 26 signal_kinds; the backend
 * doesn't know about presets — it stores granular preferences
 * exactly as B1a defined.
 *
 * Detection: detectActivePreset(prefs) compares the supplied
 * prefs against each preset's canonical shape. Returns
 * 'critical_only' | 'standard' | 'everything' | 'custom'.
 *
 * SHAPE-MATCH GUARANTEE: the Critical only preset matches the
 * B1a.1 backend's default_signal_kind_overrides() +
 * default_channel_routes_default() exactly. A user without a
 * saved record sees the synthesized defaults from the GET
 * endpoint, detectActivePreset returns 'critical_only', and
 * the "Critical only" radio renders selected without any
 * shape-mismatch fallback to Custom.
 *
 * The 4 explicit warning kinds in the Standard preset
 * (permit_expired, inspection_scheduled, license_renewal_due,
 * complaint_dob) are the operator-curated "warnings most users
 * actually want digested." Other warning-severity kinds
 * (filing_withdrawn, cofo_pending, facade_fisp, etc.) ship as
 * feed_only under Standard — power users opt them in via the
 * Advanced section.
 */

// ── Canonical signal_kind list ────────────────────────────────────
//
// Order MUST match backend's ALL_DEFAULT_SIGNAL_KINDS in
// lib/notification_preferences.py. We hard-code rather than
// importing from constants/signalKinds.js so the preset shapes
// stay in lockstep with the backend's defaults via a single
// source of truth — adding a new signal_kind requires updating
// both the backend constant and this list, which is the right
// friction.

export const ALL_KINDS = [
  // permits
  'permit_issued', 'permit_expired', 'permit_revoked', 'permit_renewed',
  // filings
  'filing_approved', 'filing_disapproved', 'filing_withdrawn', 'filing_pending',
  // violations
  'violation_dob', 'violation_ecb', 'violation_resolved',
  // stop work orders
  'stop_work_full', 'stop_work_partial',
  // complaints
  'complaint_dob', 'complaint_311',
  // inspections
  'inspection_scheduled', 'inspection_passed', 'inspection_failed', 'final_signoff',
  // cofo
  'cofo_temporary', 'cofo_final', 'cofo_pending',
  // compliance filings
  'facade_fisp', 'boiler_inspection', 'elevator_inspection',
  // license renewals
  'license_renewal_due',
];

// 6 kinds that fire an immediate email under Critical only +
// Standard. Mirrors backend DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS.
export const CRITICAL_EMAIL_KINDS = [
  'violation_dob',
  'violation_ecb',
  'stop_work_full',
  'stop_work_partial',
  'inspection_failed',
  'filing_disapproved',
];

// 4 kinds that escalate from feed_only (Critical only) to
// digest_daily (Standard). Operator-curated: the warnings most
// users actually want batched, not the full warning-severity set.
export const STANDARD_DIGEST_KINDS = [
  'permit_expired',
  'inspection_scheduled',
  'license_renewal_due',
  'complaint_dob',
];

// ── Preset metadata (UI-facing) ───────────────────────────────────

export const PRESETS = {
  critical_only: {
    key: 'critical_only',
    label: 'Critical only',
    badge: 'Recommended',
    subtitle:
      "We'll only email you about urgent items. Everything else lives in the activity feed.",
    bodyHelp:
      'Six urgent signal types email you immediately (violations, stop-work orders, failed inspections, filing disapprovals). The other 20 stay in the activity feed only.',
  },
  standard: {
    key: 'standard',
    label: 'Standard',
    badge: null,
    subtitle:
      'Critical items immediately, warnings in a daily digest, info-only items in the feed.',
    bodyHelp:
      'Adds permit expirations, scheduled inspections, license renewals, and DOB complaints to a 7am daily digest.',
  },
  everything: {
    key: 'everything',
    label: 'Everything',
    badge: null,
    subtitle:
      'Every DOB signal triggers an email right away. For very active projects.',
    bodyHelp:
      'High volume: every signal type emails you immediately. Useful for jobsites where you need to react to every event.',
  },
};

export const PRESET_ORDER = ['critical_only', 'standard', 'everything'];

// ── Preset → prefs shape generators ───────────────────────────────

function _criticalOnlyOverrides() {
  const out = {};
  for (const k of CRITICAL_EMAIL_KINDS) {
    out[k] = {
      channels: ['email'],
      severity_threshold: 'any',
      delivery: 'immediate',
    };
  }
  for (const k of ALL_KINDS) {
    if (!out[k]) {
      out[k] = {
        channels: [],
        severity_threshold: 'any',
        delivery: 'feed_only',
      };
    }
  }
  return out;
}

function _standardOverrides() {
  const out = {};
  for (const k of CRITICAL_EMAIL_KINDS) {
    out[k] = {
      channels: ['email'],
      severity_threshold: 'any',
      delivery: 'immediate',
    };
  }
  for (const k of STANDARD_DIGEST_KINDS) {
    out[k] = {
      channels: ['email'],
      severity_threshold: 'any',
      delivery: 'digest_daily',
    };
  }
  for (const k of ALL_KINDS) {
    if (!out[k]) {
      out[k] = {
        channels: [],
        severity_threshold: 'any',
        delivery: 'feed_only',
      };
    }
  }
  return out;
}

function _everythingOverrides() {
  const out = {};
  for (const k of ALL_KINDS) {
    out[k] = {
      channels: ['email'],
      severity_threshold: 'any',
      delivery: 'immediate',
    };
  }
  return out;
}

export function buildPresetOverrides(presetKey) {
  if (presetKey === 'critical_only') return _criticalOnlyOverrides();
  if (presetKey === 'standard') return _standardOverrides();
  if (presetKey === 'everything') return _everythingOverrides();
  return null;
}

export function buildPresetChannelRoutes(presetKey) {
  if (presetKey === 'critical_only') {
    // Matches B1a.1 default_channel_routes_default() exactly.
    return { critical: ['email'], warning: [], info: [] };
  }
  if (presetKey === 'standard') {
    return { critical: ['email'], warning: ['email'], info: [] };
  }
  if (presetKey === 'everything') {
    return { critical: ['email'], warning: ['email'], info: ['email'] };
  }
  return null;
}

/**
 * Apply a preset's shape to a prefs document, preserving fields
 * that aren't preset-controlled (digest_window, user_id,
 * project_id, created_at, etc.). Returns a new object — does NOT
 * mutate the input.
 */
export function buildPresetPrefs(presetKey, basePrefs) {
  const overrides = buildPresetOverrides(presetKey);
  const routes = buildPresetChannelRoutes(presetKey);
  if (!overrides || !routes) return basePrefs;
  return {
    ...(basePrefs || {}),
    signal_kind_overrides: overrides,
    channel_routes_default: routes,
  };
}

// ── Detection ─────────────────────────────────────────────────────

function _normalizeOverrideEntry(entry) {
  if (!entry || typeof entry !== 'object') {
    return JSON.stringify({ channels: [], severity_threshold: 'any', delivery: 'feed_only' });
  }
  const channels = Array.isArray(entry.channels) ? [...entry.channels].sort() : [];
  return JSON.stringify({
    channels,
    severity_threshold: entry.severity_threshold || 'any',
    delivery: entry.delivery || 'feed_only',
  });
}

function _normalizeOverrideMap(map) {
  if (!map || typeof map !== 'object') return '{}';
  const sortedKeys = Object.keys(map).sort();
  const out = {};
  for (const k of sortedKeys) {
    out[k] = _normalizeOverrideEntry(map[k]);
  }
  return JSON.stringify(out);
}

function _normalizeRoutes(routes) {
  if (!routes || typeof routes !== 'object') return '{}';
  return JSON.stringify({
    critical: Array.isArray(routes.critical) ? [...routes.critical].sort() : [],
    warning: Array.isArray(routes.warning) ? [...routes.warning].sort() : [],
    info: Array.isArray(routes.info) ? [...routes.info].sort() : [],
  });
}

/**
 * Compare prefs against each preset shape; return the matching
 * preset key, or 'custom' for any deviation.
 *
 * Order of detection matters only for cosmetic reasons (the same
 * prefs document can only match ONE preset because their shapes
 * are mutually exclusive — Critical only has 6 immediate kinds,
 * Standard has 10 email kinds, Everything has 26 immediate kinds).
 */
export function detectActivePreset(prefs) {
  if (!prefs) return 'custom';
  const actualOverridesNorm = _normalizeOverrideMap(prefs.signal_kind_overrides || {});
  const actualRoutesNorm = _normalizeRoutes(prefs.channel_routes_default || {});

  for (const key of PRESET_ORDER) {
    const expectedOverridesNorm = _normalizeOverrideMap(buildPresetOverrides(key));
    const expectedRoutesNorm = _normalizeRoutes(buildPresetChannelRoutes(key));
    if (
      expectedOverridesNorm === actualOverridesNorm &&
      expectedRoutesNorm === actualRoutesNorm
    ) {
      return key;
    }
  }
  return 'custom';
}

// Exported for unit tests + the page's deep-equal dirty check.
export const _internals = {
  _normalizeOverrideMap,
  _normalizeRoutes,
};
