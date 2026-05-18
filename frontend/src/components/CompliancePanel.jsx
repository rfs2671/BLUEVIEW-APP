/**
 * PR #15D — Compliance Risk panel.
 *
 * Renders the Phase 1 Predictive Inference Engine output for a
 * single project: 3-horizon violation probabilities (7d / 14d / 30d)
 * with cohort-baseline comparisons, colour-coded by hazard ratio
 * (Lock L6 — 5-tier mapping via hazardRatioToColorTier).
 *
 * Hard rules pinned by Stage 5 spot-check spec + PR #15D locks:
 *   • Feature flag — useFeatureFlag('pr15d_prediction') is the
 *     FIRST hook in this component (rules-of-hooks pattern, same
 *     idiom as RiskScoreCircle / RiskScoreDrawer). Flag OFF →
 *     return null BEFORE any other state, effect, or fetch.
 *   • L6 — colour each horizon row from
 *     project_prob_<n>d / anchored_baseline.prob_<n>d via
 *     hazardRatioToColorTier. NEVER colour from the raw probability.
 *   • L7 — last_validated_timestamp older than 24h → soft-stale
 *     chip; > 48h → hard-stale chip. Panel always renders.
 *   • L8 / B-SERIALIZE — confidence.badge is computed server-side
 *     in serialize_prediction_cache_to_response. The client must
 *     NOT derive its own; just render what the API returns.
 *   • Q3 / Q5 cold-start UX — when badge === 'cold_start', the
 *     panel shows the educational disclaimer copy pinned by the
 *     PR #15D Stage 5 spec, NOT the standard "limited sample"
 *     treatment. Explains why prob_30d can be ~50% for cohorts
 *     like Bronx full_demo without alarming the operator.
 *   • F2 — no Jest/RNTL tests for this component (no FE test infra
 *     in this repo). Backend tests cover the API contract; manual
 *     visual smoke (Stage 9) validates the rendering.
 *
 * Render states:
 *   1. flag OFF       — returns null (no fetch, no render)
 *   2. loading        — ActivityIndicator inside GlassCard header
 *   3. error          — muted "couldn't load" line, no crash
 *   4. unavailable    — prediction_available=false (no fit yet)
 *   5. cold_start     — educational disclaimer, plus the 3 horizon
 *                       rows colored against the cohort baseline
 *   6. ready          — 3 horizon rows with 5-tier colored chips
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { Shield, AlertTriangle, Clock, Info } from 'lucide-react-native';
import { GlassCard, IconPod } from './GlassCard';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { projectsAPI } from '../utils/api';
import {
  hazardRatioToColorTier,
  tierToStatusColor,
} from '../utils/hazardRatioColor';

// ── Helpers ──────────────────────────────────────────────────────

function _formatPct(p) {
  if (p === null || p === undefined) return '—';
  const v = Number(p);
  if (!Number.isFinite(v)) return '—';
  // < 0.5% renders as "<0.5%" to avoid the misleading "0%" for
  // small-but-nonzero probabilities (op feedback in Stage 1 design).
  if (v > 0 && v < 0.005) return '<0.5%';
  return `${(v * 100).toFixed(1)}%`;
}

function _safeRatio(prob, baseline) {
  if (prob === null || prob === undefined) return null;
  if (baseline === null || baseline === undefined) return null;
  const b = Number(baseline);
  if (!Number.isFinite(b) || b <= 0) return null;
  const p = Number(prob);
  if (!Number.isFinite(p)) return null;
  return p / b;
}

function _hoursSince(isoOrDate) {
  if (!isoOrDate) return null;
  const t = new Date(isoOrDate).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3_600_000;
}

// Title-case helper for borough names ("BROOKLYN" → "Brooklyn")
// and project types ("full_demo" → "Full Demo"). Same idiom as
// RiskScoreDrawer._titleCase but inlined to avoid cross-component
// coupling.
function _titleCase(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .toLowerCase()
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

// anchored_baseline.label format from backend:
//   "<BOROUGH> <project_type> macro baseline"
//   e.g. "BROOKLYN full_demo macro baseline"
// Parse defensively — if the format changes, fall back to a
// generic disclaimer with no placeholders.
function _parseBaselineLabel(label) {
  if (!label || typeof label !== 'string') {
    return { borough: null, projectType: null };
  }
  const parts = label.trim().split(/\s+/);
  if (parts.length < 2) return { borough: null, projectType: null };
  return {
    borough:     _titleCase(parts[0]),
    projectType: _titleCase(parts[1]),
  };
}

// L8 — badge label localisation. Server returns the machine value;
// we display a short human label inline.
function _badgeLabel(badge) {
  if (badge === 'cold_start')         return 'COLD START';
  if (badge === 'limited_peer_sample') return 'LIMITED SAMPLE';
  return null;
}

// ── HorizonRow ───────────────────────────────────────────────────
// One row per horizon. Renders the project prob, baseline prob, and
// a hazard-ratio chip coloured via L6.

function HorizonRow({ label, prob, baseline, colors }) {
  const ratio = _safeRatio(prob, baseline);
  const tier = hazardRatioToColorTier(ratio);
  const { fg, bg } = tierToStatusColor(tier);
  const ratioLabel = ratio === null
    ? '—'
    : `${ratio.toFixed(2)}×`;

  return (
    <View style={styles.row}>
      <Text style={[styles.horizonLabel, { color: colors.text.secondary }]}>
        {label}
      </Text>
      <View style={styles.rowRight}>
        <Text style={[styles.probValue, { color: colors.text.primary }]}>
          {_formatPct(prob)}
        </Text>
        <Text style={[styles.baselineValue, { color: colors.text.muted }]}>
          vs {_formatPct(baseline)}
        </Text>
        <View style={[styles.ratioChip, { backgroundColor: bg }]}>
          <Text style={[styles.ratioChipText, { color: fg }]}>
            {ratioLabel}
          </Text>
        </View>
      </View>
    </View>
  );
}

// ── Cold-start educational disclaimer (Q3 / Q5 lock) ─────────────
// Pinned by the PR #15D Stage 5 spec. Two paragraphs:
//   1. Explains why no personalised prediction exists yet.
//   2. Explains why the cohort baseline can show high probabilities
//      without that meaning "this project is high risk".

function ColdStartDisclaimer({ borough, projectType, colors }) {
  const cohort = (borough && projectType)
    ? `${borough} ${projectType.toLowerCase()}`
    : 'similar';
  return (
    <View style={[
      styles.disclaimer,
      { backgroundColor: colors.glass.background,
        borderColor: colors.border.subtle },
    ]}>
      <View style={styles.disclaimerHeader}>
        <Info size={14} strokeWidth={1.5} color={colors.status.caution} />
        <Text style={[
          styles.disclaimerTitle,
          { color: colors.status.caution },
        ]}>
          Personalised forecast not yet available
        </Text>
      </View>
      <Text style={[styles.disclaimerBody, { color: colors.text.secondary }]}>
        The values below are the cohort baseline for {cohort}
        {' '}projects citywide. As this project accrues filings and
        time, a personalised forecast will replace these baseline
        values.
      </Text>
      <Text style={[styles.disclaimerBody, { color: colors.text.muted }]}>
        Note: the cohort baseline can show high probabilities when
        the underlying borough + project-type combination has
        historically high violation rates. A hazard ratio of 1.0
        means this project matches the cohort average — not that
        risk is low.
      </Text>
    </View>
  );
}

// ── Main component ───────────────────────────────────────────────

export default function CompliancePanel({ projectId }) {
  // Rules-of-hooks pinned: useFeatureFlag MUST be the FIRST hook in
  // this component. Same idiom as RiskScoreCircle. When the flag is
  // off we return null BEFORE useTheme / useState / useEffect run,
  // so v1 users never trigger the prediction fetch.
  const flagOn = useFeatureFlag('pr15d_prediction');
  const { colors } = useTheme();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!flagOn || !projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    projectsAPI.getPrediction(projectId)
      .then((resp) => {
        if (cancelled) return;
        setData(resp);
      })
      .catch((err) => {
        if (cancelled) return;
        // 404 / 403 / 5xx — the panel is non-critical, so we degrade
        // gracefully rather than poisoning the whole project page.
        setError(err?.response?.status || 'error');
        setData(null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [flagOn, projectId]);

  // ── State 1 — flag OFF (return null, no render, no fetch) ────
  if (!flagOn) return null;

  // ── State 2 — loading ────────────────────────────────────────
  if (loading) {
    return (
      <GlassCard style={styles.card}>
        <View style={styles.header}>
          <IconPod>
            <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
          </IconPod>
          <Text style={[styles.title, { color: colors.text.primary }]}>
            Compliance Risk
          </Text>
        </View>
        <View style={styles.center}>
          <ActivityIndicator color={colors.text.muted} />
        </View>
      </GlassCard>
    );
  }

  // ── State 3 — error ──────────────────────────────────────────
  if (error || !data) {
    return (
      <GlassCard style={styles.card}>
        <View style={styles.header}>
          <IconPod>
            <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
          </IconPod>
          <Text style={[styles.title, { color: colors.text.primary }]}>
            Compliance Risk
          </Text>
        </View>
        <Text style={[styles.muted, { color: colors.text.muted }]}>
          Forecast unavailable right now. Refresh the page or try again
          later.
        </Text>
      </GlassCard>
    );
  }

  const {
    prediction_available: predictionAvailable,
    horizons,
    anchored_baseline: anchoredBaseline,
    confidence,
    metadata,
  } = data;

  // ── State 4 — unavailable (no fit yet) ───────────────────────
  if (!predictionAvailable) {
    return (
      <GlassCard style={styles.card}>
        <View style={styles.header}>
          <IconPod>
            <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
          </IconPod>
          <Text style={[styles.title, { color: colors.text.primary }]}>
            Compliance Risk
          </Text>
        </View>
        <Text style={[styles.muted, { color: colors.text.muted }]}>
          A risk forecast for this project is still being prepared.
          New projects typically have a forecast within 24 hours of
          the first nightly refit cycle.
        </Text>
      </GlassCard>
    );
  }

  // ── Staleness — L7 ───────────────────────────────────────────
  const hoursStale = _hoursSince(metadata?.last_validated_timestamp);
  const isHardStale = hoursStale !== null && hoursStale > 48;
  const isSoftStale = hoursStale !== null && hoursStale > 24 && !isHardStale;

  const badge = _badgeLabel(confidence?.badge);
  const sampleSize = confidence?.sample_size;
  const baselineLabel = anchoredBaseline?.label;
  const isColdStart = confidence?.badge === 'cold_start';
  const parsedLabel = _parseBaselineLabel(baselineLabel);

  // ── State 5/6 — ready (cold_start OR standard) ───────────────
  return (
    <GlassCard style={styles.card}>
      <View style={styles.header}>
        <IconPod>
          <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
        </IconPod>
        <Text style={[styles.title, { color: colors.text.primary }]}>
          Compliance Risk
        </Text>
        {badge && (
          <View style={[
            styles.badge,
            { backgroundColor: colors.status.cautionBg },
          ]}>
            <Text style={[
              styles.badgeText,
              { color: colors.status.caution },
            ]}>
              {badge}
            </Text>
          </View>
        )}
      </View>

      {/* Q3/Q5 — cold-start gets the educational disclaimer above
          the horizon rows. Standard fits skip this. */}
      {isColdStart && (
        <ColdStartDisclaimer
          borough={parsedLabel.borough}
          projectType={parsedLabel.projectType}
          colors={colors}
        />
      )}

      {/* Three horizon rows */}
      <HorizonRow
        label="Next 7 days"
        prob={horizons?.prob_7d}
        baseline={anchoredBaseline?.prob_7d}
        colors={colors}
      />
      <HorizonRow
        label="Next 14 days"
        prob={horizons?.prob_14d}
        baseline={anchoredBaseline?.prob_14d}
        colors={colors}
      />
      <HorizonRow
        label="Next 30 days"
        prob={horizons?.prob_30d}
        baseline={anchoredBaseline?.prob_30d}
        colors={colors}
      />

      {/* Footer — baseline label + sample size + staleness chip */}
      <View style={[
        styles.footer,
        { borderTopColor: colors.border.subtle },
      ]}>
        {!!baselineLabel && (
          <Text style={[styles.footerLabel, { color: colors.text.muted }]}>
            Compared to: {baselineLabel}
            {typeof sampleSize === 'number' && sampleSize >= 0
              ? `  ·  n=${sampleSize}`
              : ''}
          </Text>
        )}
        {(isSoftStale || isHardStale) && (
          <View style={styles.staleRow}>
            {isHardStale
              ? <AlertTriangle size={12} strokeWidth={1.5}
                  color={colors.status.error} />
              : <Clock size={12} strokeWidth={1.5}
                  color={colors.status.caution} />
            }
            <Text style={[
              styles.staleText,
              { color: isHardStale
                  ? colors.status.error
                  : colors.status.caution },
            ]}>
              {isHardStale
                ? `Forecast last refreshed ${Math.round(hoursStale)}h ago — over 48h stale`
                : `Forecast last refreshed ${Math.round(hoursStale)}h ago`}
            </Text>
          </View>
        )}
      </View>
    </GlassCard>
  );
}

// ── Styles ───────────────────────────────────────────────────────

const styles = StyleSheet.create({
  card: {
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  title: {
    ...typography.h3,
    flex: 1,
  },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  badgeText: {
    ...typography.label,
    fontSize: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
  },
  horizonLabel: {
    ...typography.body,
    flexShrink: 1,
  },
  rowRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  probValue: {
    ...typography.body,
    fontWeight: '600',
    minWidth: 56,
    textAlign: 'right',
  },
  baselineValue: {
    ...typography.small,
    minWidth: 64,
    textAlign: 'right',
  },
  ratioChip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    minWidth: 56,
    alignItems: 'center',
  },
  ratioChipText: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 0.5,
    textTransform: 'none',
  },
  footer: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: spacing.xs,
  },
  footerLabel: {
    ...typography.small,
  },
  staleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  staleText: {
    ...typography.small,
    fontSize: 12,
  },
  center: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  muted: {
    ...typography.body,
    paddingVertical: spacing.sm,
  },
  disclaimer: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  disclaimerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: 2,
  },
  disclaimerTitle: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  disclaimerBody: {
    ...typography.small,
    fontSize: 12,
    lineHeight: 16,
  },
});
