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

              {/* ── 2. What this means (PR #50 — was "Primary reason") ── */}
              {data.primary_reason ? (
                <GlassCard style={styles.card}>
                  <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>
                    WHAT THIS MEANS
                  </Text>
                  <Text style={[styles.reason, { color: colors.text.primary }]}>
                    {data.primary_reason}
                  </Text>
                </GlassCard>
              ) : null}

              {/* ── 3. Why this matters (PR #50 — GC-voice sentences) ──
                  Renders backend-prerendered contributing_factors_text.
                  The raw {factor, weight, evidence} dicts are still in
                  the API response for engineering debug but no longer
                  surfaced. */}
              {Array.isArray(data.contributing_factors_text)
                && data.contributing_factors_text.length > 0 ? (
                <GlassCard style={styles.card}>
                  <View style={styles.sectionHeader}>
                    <IconPod>
                      <Activity
                        size={18}
                        strokeWidth={1.5}
                        color={colors.iconPod.iconColor}
                      />
                    </IconPod>
                    <Text style={[styles.sectionTitle, { color: colors.text.primary }]} numberOfLines={1} ellipsizeMode="tail">
                      Why this matters
                    </Text>
                  </View>
                  {data.contributing_factors_text.map((line, i) => (
                    <View
                      key={`cf-${i}`}
                      style={styles.bulletRow}
                    >
                      <Text style={[styles.bulletDot, { color: colors.text.muted }]}>
                        {'•'}
                      </Text>
                      <Text style={[styles.bulletText, { color: colors.text.primary }]}>
                        {line}
                      </Text>
                    </View>
                  ))}
                </GlassCard>
              ) : null}

              {/* ── 4. Compared to similar sites (PR #50 — was "Cohort
                  Context"). One GC-voice sentence; raw numbers
                  (baseline rate, ratio, peer count) no longer shown. */}
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
                    Compared to similar sites
                  </Text>
                </View>
                <Text style={[styles.reason, { color: colors.text.primary }]}>
                  {data.cohort_comparison_text || 'Comparison not yet available'}
                </Text>
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

              {/* ── 6. Last checked (PR #50 — GC voice) ── */}
              <View style={styles.footerRow}>
                <Clock size={12} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={[styles.footerText, { color: colors.text.muted }]}>
                  Last checked {timeAgo || '—'}
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
    // PR #50 — "Why this matters" GC-voice bullet list.
    bulletRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      paddingVertical: spacing.xs,
    },
    bulletDot: {
      ...typography.body,
      fontSize: 16,
      lineHeight: 22,
    },
    bulletText: {
      ...typography.body,
      fontSize: 15,
      lineHeight: 21,
      flex: 1,
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
