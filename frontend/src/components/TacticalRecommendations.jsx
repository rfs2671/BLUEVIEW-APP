/**
 * Phase 1 Week 13-19 PR-B — Tactical Recommendations component.
 *
 * Final UI of the Phase 1 19-week roadmap. Surfaces actionable GC-facing
 * recommendations derived from the causal_lift_matrix (PR-A #46) on the
 * Defcon detail screen.
 *
 * Flow (Stage 2.A L3):
 *   1. Fetch /api/projects/{id}/recent-complaint-buckets to learn which
 *      complaint buckets are active on this project in the last 90 days.
 *   2. For each of the top-3 buckets (or fewer if pool smaller), fire
 *      /api/causal-lift?complaint_bucket={X}&window_days=90 in parallel
 *      via Promise.all.
 *   3. Aggregate the responses, sort by lift_ratio DESC, render the top
 *      3 cards globally.
 *   4. Empty states:
 *        - 0 recent complaints → "No recent complaint patterns to analyze"
 *        - 0 qualifying recommendations → same empty state
 *        - fetch error → silent (component renders nothing)
 *
 * Each recommendation card (L4):
 *   • "Sites with {X} complaints typically face {Y} violations N.Nx more
 *     often within W days." (lift_ratio rounded to 1 decimal)
 *   • Confidence chip — HIGH (green) / MEDIUM (amber)
 *   • "Based on N similar sites" — derived from n_bins_with_complaint
 *
 * F2 lock: no FE tests. Babel parse + 3 spot-checks on bucketLabels +
 * derived recommendation key + empty-state branch.
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { projectsAPI, causalLiftAPI } from '../utils/api';
import { bucketLabel } from '../utils/bucketLabels';

// ── Constants ───────────────────────────────────────────────────────

// Number of top-N complaint buckets to fan out into causal-lift queries.
// 3 keeps the parallel request count bounded; cards are aggregated +
// re-sorted across all returns so the rendered set is the globally
// top-3 by lift_ratio regardless of which input bucket sourced them.
const MAX_INPUT_BUCKETS = 3;
const MAX_RECOMMENDATIONS = 3;
const WINDOW_DAYS = 90;

// L6 — confidence → theme color mapping. Reuses the existing PR #15D
// success/warning status palette; no new theme tokens. LOW
// recommendations are filtered out at the API layer (default filter)
// so the only render paths are HIGH and MEDIUM.
function _confidenceTheme(confidence, colors) {
  if (confidence === 'HIGH') {
    return { fg: colors.status.success, bg: colors.status.successBg };
  }
  if (confidence === 'MEDIUM') {
    return { fg: colors.status.warning, bg: colors.status.warningBg };
  }
  // LOW shouldn't surface here, but if it ever does → muted neutral.
  return { fg: colors.text.muted, bg: colors.glass.background };
}

// Stable React key per recommendation. Distinct from a database id
// because the recommendation set is computed at request time.
function _recKey(rec) {
  return [
    rec.complaint_bucket,
    rec.violation_bucket,
    rec.window_days,
  ].join('-');
}

// ── Card subcomponent ──────────────────────────────────────────────

function RecommendationCard({ recommendation }) {
  const { colors } = useTheme();
  const styles = _buildStyles(colors);
  const ratio = Number(recommendation.lift_ratio || 0).toFixed(1);
  const complaintText = bucketLabel(recommendation.complaint_bucket);
  const violationText = bucketLabel(recommendation.violation_bucket);
  const { fg, bg } = _confidenceTheme(recommendation.confidence, colors);
  const sentence = `Sites with ${complaintText} complaints typically face `
    + `${violationText} violations ${ratio}× more often within `
    + `${recommendation.window_days} days.`;

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: bg, borderColor: fg },
      ]}
      accessibilityRole="summary"
    >
      <Text style={[styles.cardText, { color: colors.text.primary }]}>
        {sentence}
      </Text>
      <View style={styles.cardFooter}>
        <View
          style={[
            styles.confidenceChip,
            { backgroundColor: colors.glass.background, borderColor: fg },
          ]}
        >
          <Text style={[styles.confidenceText, { color: fg }]}>
            {recommendation.confidence}
          </Text>
        </View>
        <Text
          style={[styles.sampleText, { color: colors.text.muted }]}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          Based on {recommendation.n_bins_with_complaint || 0} similar sites
        </Text>
      </View>
    </View>
  );
}

// ── Main component ─────────────────────────────────────────────────

export default function TacticalRecommendations({ projectId }) {
  const { colors } = useTheme();
  const styles = _buildStyles(colors);
  const [recommendations, setRecommendations] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) {
      setRecommendations([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        const resp = await projectsAPI.getRecentComplaintBuckets(projectId);
        const buckets = resp?.buckets || [];
        if (cancelled) return;
        if (!buckets.length) {
          setRecommendations([]);
          return;
        }
        // Top-N input buckets by count.
        const topBuckets = buckets.slice(0, MAX_INPUT_BUCKETS);

        // Parallel fan-out — one /causal-lift query per input bucket.
        // Each query returns at most 50 rows pre-filtered by the
        // backend (lift_ratio ≥ 1.5 AND confidence ∈ HIGH/MEDIUM).
        const liftResults = await Promise.all(
          topBuckets.map(({ bucket }) =>
            causalLiftAPI.getByBucket(bucket, { windowDays: WINDOW_DAYS })
              .catch(() => [])
          ),
        );
        if (cancelled) return;

        // Flatten + sort by lift_ratio DESC, dedupe by (X, Y, W) so
        // overlapping buckets don't double-count the same cell.
        const seen = new Set();
        const flat = [];
        for (const arr of liftResults) {
          for (const r of (arr || [])) {
            const k = _recKey(r);
            if (seen.has(k)) continue;
            seen.add(k);
            flat.push(r);
          }
        }
        flat.sort(
          (a, b) => Number(b.lift_ratio || 0) - Number(a.lift_ratio || 0),
        );
        setRecommendations(flat.slice(0, MAX_RECOMMENDATIONS));
      } catch (e) {
        if (!cancelled) {
          // Non-critical surface — silent failure so the rest of the
          // Defcon detail screen still renders.
          setRecommendations([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) {
    return (
      <View style={styles.centerBox}>
        <ActivityIndicator color={colors.text.muted} />
      </View>
    );
  }

  if (!recommendations || recommendations.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: colors.text.muted }]}>
        No recent complaint patterns to analyze.
      </Text>
    );
  }

  return (
    <View style={styles.list}>
      {recommendations.map((rec) => (
        <RecommendationCard key={_recKey(rec)} recommendation={rec} />
      ))}
    </View>
  );
}

// ── Styles ─────────────────────────────────────────────────────────

function _buildStyles(colors) {
  return StyleSheet.create({
    centerBox: {
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: spacing.md,
    },
    list: {
      gap: spacing.sm,
    },
    card: {
      borderRadius: borderRadius.md,
      borderWidth: 1,
      padding: spacing.sm,
      gap: spacing.sm,
    },
    cardText: {
      ...typography.body,
      fontSize: 14,
      lineHeight: 20,
    },
    cardFooter: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    confidenceChip: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
    },
    confidenceText: {
      ...typography.label,
      fontSize: 10,
      letterSpacing: 1,
    },
    sampleText: {
      ...typography.small,
      fontSize: 12,
      flex: 1,
    },
    emptyText: {
      ...typography.small,
      fontSize: 13,
      fontStyle: 'italic',
      paddingVertical: spacing.sm,
    },
  });
}
