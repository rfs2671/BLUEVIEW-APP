/**
 * Phase 1 Week 11-12 PR-B — Defcon detail screen.
 *
 * /project/{id}/defcon — opened from the "Why?" link on the
 * DefconHeader card inside CompliancePanel. Shows the full Defcon
 * status payload from /api/projects/{id}/defcon-status with six
 * sections per Stage 2.A L5:
 *
 *   1. Tier hero        — large colored badge + tier label
 *   2. Primary reason   — pre-rendered GC-voice headline
 *   3. Contributing factors — one row per backend factor
 *   4. Cohort context   — baseline rate / ratio / peer matches
 *   5. Last evaluated   — relative timestamp footer
 *   6. (back nav)       — header arrow ← back to /project/{id}
 *
 * F2 lock: no FE test infra in this repo. Manual smoke-test via the
 * device once a project has a non-NORMAL tier.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import {
  ArrowLeft,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Users,
  Activity,
  Clock,
  Target,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../../src/components/GlassCard';
import HeaderBrand from '../../../src/components/HeaderBrand';
import FloatingNav from '../../../src/components/FloatingNav';
import TacticalRecommendations from '../../../src/components/TacticalRecommendations';
import { useAuth } from '../../../src/context/AuthContext';
import { useTheme } from '../../../src/context/ThemeContext';
import { projectsAPI } from '../../../src/utils/api';
import {
  spacing,
  borderRadius,
  typography,
} from '../../../src/styles/theme';
import {
  tierToTheme,
  tierToLabel,
  formatTimeAgo,
} from '../../../src/utils/defconHelpers';

function _tierIcon(tier) {
  if (tier === 'IMMEDIATE') return AlertTriangle;
  if (tier === 'ELEVATED')  return ShieldAlert;
  return ShieldCheck;
}

function _formatPct(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (n > 0 && n < 0.005) return '<0.5%';
  return `${(n * 100).toFixed(1)}%`;
}

function _formatRatio(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(1)}× typical`;
}

export default function DefconScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
  const styles = useMemo(() => buildStyles(colors), [colors]);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const t = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(t);
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (!isAuthenticated || !projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    projectsAPI.getDefconStatus(projectId)
      .then((resp) => { if (!cancelled) setData(resp); })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.response?.status || 'error');
        setData(null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isAuthenticated, projectId]);

  if (authLoading || !isAuthenticated) return null;

  const tier = data?.tier || 'NORMAL';
  const { fg, bg } = tierToTheme(tier);
  const Icon = _tierIcon(tier);
  const timeAgo = formatTimeAgo(data?.last_evaluated_at);

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        {/* ── 6. Back nav header ── */}
        <View style={styles.headerBar}>
          <Pressable
            onPress={() => router.back()}
            style={({ pressed }) => [
              styles.backBtn,
              pressed && { opacity: 0.65 },
            ]}
            accessibilityLabel="Go back"
            accessibilityRole="button"
            hitSlop={8}
          >
            <ArrowLeft size={20} color={colors.text.primary} />
          </Pressable>
          <HeaderBrand />
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {loading && (
            <View style={styles.centerBox}>
              <ActivityIndicator color={colors.text.muted} />
            </View>
          )}

          {error && !loading && (
            <GlassCard style={styles.card}>
              <Text style={[styles.muted, { color: colors.text.muted }]}>
                Defcon status unavailable right now. Refresh the page or
                try again later.
              </Text>
            </GlassCard>
          )}

          {data && !loading && !error && (
            <>
              {/* ── 1. Tier hero ── */}
              <View
                style={[
                  styles.hero,
                  { backgroundColor: bg, borderColor: fg },
                ]}
                accessibilityRole="header"
              >
                <View style={styles.heroRow}>
                  <Icon size={28} strokeWidth={1.5} color={fg} />
                  <Text style={[styles.heroTier, { color: fg }]}>
                    {tierToLabel(tier).toUpperCase()}
                  </Text>
                </View>
                <Text style={[styles.heroSub, { color: colors.text.secondary }]}>
                  Defcon status
                </Text>
              </View>

              {/* ── 2. Primary reason ── */}
              {data.primary_reason ? (
                <GlassCard style={styles.card}>
                  <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>
                    PRIMARY REASON
                  </Text>
                  <Text style={[styles.reason, { color: colors.text.primary }]}>
                    {data.primary_reason}
                  </Text>
                </GlassCard>
              ) : null}

              {/* ── 3. Contributing factors ── */}
              <GlassCard style={styles.card}>
                <View style={styles.sectionHeader}>
                  <IconPod>
                    <Activity
                      size={18}
                      strokeWidth={1.5}
                      color={colors.iconPod.iconColor}
                    />
                  </IconPod>
                  <Text style={[styles.sectionTitle, { color: colors.text.primary }]}>
                    Contributing Factors
                  </Text>
                </View>
                {Array.isArray(data.contributing_factors)
                  && data.contributing_factors.length > 0 ? (
                  data.contributing_factors.map((f, i) => (
                    <View
                      key={`${f.factor || 'factor'}-${i}`}
                      style={[
                        styles.factorRow,
                        { borderTopColor: colors.border.subtle },
                      ]}
                    >
                      <View style={styles.factorRowTop}>
                        <Text style={[styles.factorName, { color: colors.text.primary }]}>
                          {(f.factor || '').replace(/_/g, ' ')}
                        </Text>
                        {typeof f.weight === 'number' && (
                          <View
                            style={[
                              styles.weightChip,
                              { backgroundColor: colors.glass.background },
                            ]}
                          >
                            <Text style={[styles.weightText, { color: colors.text.secondary }]}>
                              {f.weight > 0 ? '+' : ''}{f.weight.toFixed(1)}
                            </Text>
                          </View>
                        )}
                      </View>
                      {f.evidence ? (
                        <Text style={[styles.factorEvidence, { color: colors.text.secondary }]}>
                          {f.evidence}
                        </Text>
                      ) : null}
                    </View>
                  ))
                ) : (
                  <Text style={[styles.muted, { color: colors.text.muted }]}>
                    No contributing factors recorded. All indicators
                    within typical range.
                  </Text>
                )}
              </GlassCard>

              {/* ── 4. Cohort context ── */}
              <GlassCard style={styles.card}>
                <View style={styles.sectionHeader}>
                  <IconPod>
                    <Users
                      size={18}
                      strokeWidth={1.5}
                      color={colors.iconPod.iconColor}
                    />
                  </IconPod>
                  <Text style={[styles.sectionTitle, { color: colors.text.primary }]}>
                    Cohort Context
                  </Text>
                </View>
                <View style={styles.kvRow}>
                  <Text style={[styles.kvKey, { color: colors.text.muted }]}>
                    Cohort baseline (14d)
                  </Text>
                  <Text style={[styles.kvVal, { color: colors.text.primary }]}>
                    {_formatPct(data.cohort_context?.cohort_baseline_rate)}
                  </Text>
                </View>
                <View style={styles.kvRow}>
                  <Text style={[styles.kvKey, { color: colors.text.muted }]}>
                    Project rate vs cohort
                  </Text>
                  <Text style={[styles.kvVal, { color: colors.text.primary }]}>
                    {_formatRatio(data.cohort_context?.project_rate_ratio)}
                  </Text>
                </View>
                <View style={styles.kvRow}>
                  <Text style={[styles.kvKey, { color: colors.text.muted }]}>
                    Peer matches
                  </Text>
                  <Text style={[styles.kvVal, { color: colors.text.primary }]}>
                    {data.cohort_context?.n_peer_matches ?? '—'}
                  </Text>
                </View>
              </GlassCard>

              {/* ── 4b. Tactical Recommendations (Phase 1 Week 13-19 PR-B) ──
                  Fans out from the project's last-90-day complaint
                  buckets into per-bucket causal_lift_matrix queries.
                  Empty state when 0 recent complaints or 0 qualifying
                  recommendations — silent failure on network error. */}
              <GlassCard style={styles.card}>
                <View style={styles.sectionHeader}>
                  <IconPod>
                    <Target
                      size={18}
                      strokeWidth={1.5}
                      color={colors.iconPod.iconColor}
                    />
                  </IconPod>
                  <Text style={[styles.sectionTitle, { color: colors.text.primary }]}>
                    Tactical Recommendations
                  </Text>
                </View>
                <TacticalRecommendations projectId={projectId} />
              </GlassCard>

              {/* ── 5. Last evaluated ── */}
              <View style={styles.footerRow}>
                <Clock size={12} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={[styles.footerText, { color: colors.text.muted }]}>
                  Last evaluated {timeAgo || '—'}
                </Text>
              </View>
            </>
          )}
        </ScrollView>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    safe: {
      flex: 1,
      backgroundColor: 'transparent',
    },
    headerBar: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      backgroundColor: colors.glass.background,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
      gap: spacing.sm,
    },
    backBtn: {
      width: 36,
      height: 36,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 18,
    },
    scroll: {
      flex: 1,
    },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 120,
      gap: spacing.md,
    },
    centerBox: {
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: spacing.xxl,
    },
    hero: {
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      padding: spacing.lg,
      gap: spacing.xs,
    },
    heroRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    heroTier: {
      fontSize: 28,
      fontWeight: '700',
      letterSpacing: 1,
    },
    heroSub: {
      ...typography.small,
      letterSpacing: 1,
      textTransform: 'uppercase',
    },
    card: {
      padding: spacing.md,
      gap: spacing.sm,
    },
    sectionHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      marginBottom: spacing.xs,
    },
    sectionTitle: {
      ...typography.h3,
      flex: 1,
    },
    sectionLabel: {
      ...typography.label,
      fontSize: 11,
      letterSpacing: 1.5,
    },
    reason: {
      ...typography.body,
      fontSize: 16,
      lineHeight: 22,
    },
    factorRow: {
      borderTopWidth: StyleSheet.hairlineWidth,
      paddingVertical: spacing.sm,
      gap: spacing.xs,
    },
    factorRowTop: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    factorName: {
      ...typography.body,
      fontSize: 14,
      fontWeight: '600',
      textTransform: 'capitalize',
      flex: 1,
    },
    weightChip: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderRadius: borderRadius.sm,
    },
    weightText: {
      ...typography.label,
      fontSize: 10,
    },
    factorEvidence: {
      ...typography.small,
      fontSize: 13,
      lineHeight: 18,
    },
    kvRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.xs,
    },
    kvKey: {
      ...typography.small,
      fontSize: 13,
    },
    kvVal: {
      ...typography.body,
      fontSize: 14,
      fontWeight: '600',
    },
    muted: {
      ...typography.body,
      fontSize: 14,
    },
    footerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      justifyContent: 'center',
      paddingTop: spacing.sm,
    },
    footerText: {
      ...typography.small,
      fontSize: 12,
    },
  });
}
