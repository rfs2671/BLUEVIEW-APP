/**
 * Phase V2.0 — Compliance Logbook audit screen.
 *
 * Calendar view + drawer for the v2_logbook feature. Behind the
 * `v2_logbook` feature flag (E1). When the flag is OFF — for
 * every v1 customer at launch — this route renders nothing
 * (returns null). The route file still exists in the FE bundle
 * so v2 customers don't need a fresh deploy when the flag flips
 * on; the gating is purely the React render guard below.
 *
 * Hard rules pinned by tests:
 *   • useFeatureFlag('v2_logbook') is the FIRST hook in the
 *     component (so it never lands inside any conditional or
 *     after an early return — the C1.3 / hook-rules pattern).
 *   • If the flag returns false the screen returns null before
 *     fetching anything.
 *   • The fetch path uses /api/projects/{id}/logbook/audit.
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
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, Calendar, Download, X } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import HeaderBrand from '../../../src/components/HeaderBrand';
import { useTheme } from '../../../src/context/ThemeContext';
import { useAuth } from '../../../src/context/AuthContext';
import { useFeatureFlag } from '../../../src/hooks/useFeatureFlag';
import apiClient from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';

const COLOR_MAP = {
  green:  { bg: 'rgba(34, 197, 94, 0.18)',  border: 'rgba(34, 197, 94, 0.7)',  label: 'OK' },
  yellow: { bg: 'rgba(234, 179, 8, 0.18)',  border: 'rgba(234, 179, 8, 0.7)',  label: 'Deficient' },
  red:    { bg: 'rgba(239, 68, 68, 0.18)',  border: 'rgba(239, 68, 68, 0.7)',  label: 'Missing' },
  grey:   { bg: 'rgba(148, 163, 184, 0.10)', border: 'rgba(148, 163, 184, 0.4)', label: '—' },
};

export default function ComplianceAuditScreen() {
  // ── Flag check FIRST (rules-of-hooks: unconditional top-of-component).
  const v2LogbookEnabled = useFeatureFlag('v2_logbook');

  // Other hooks must also be called unconditionally — they all run
  // every render even when the flag is off; the return-null below
  // is the LAST step.
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  const [loading, setLoading] = useState(true);
  const [auditData, setAuditData] = useState(null);
  const [selectedDay, setSelectedDay] = useState(null);
  const [drawerEntries, setDrawerEntries] = useState([]);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);

  useEffect(() => {
    // Auth gate, identical to /project/[id]/activity.
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!v2LogbookEnabled || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await apiClient.get(
          `/api/projects/${projectId}/logbook/audit`,
        );
        if (!cancelled) setAuditData(r.data || null);
      } catch (_e) {
        if (!cancelled) setAuditData({ days: [] });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [v2LogbookEnabled, projectId]);

  // ── Fail-closed render: flag OFF → nothing. ───────────────────
  if (!v2LogbookEnabled) {
    return null;
  }

  const onDayPress = async (dayKey) => {
    setSelectedDay(dayKey);
    setDrawerEntries([]);
    setDrawerLoading(true);
    try {
      // Fetch missing + deficiencies + attestations and merge
      // by date — small N, three round-trips is fine for v0.
      const [missing, deficiencies, attestations] = await Promise.all([
        apiClient.get(`/api/projects/${projectId}/logbook/missing`),
        apiClient.get(`/api/projects/${projectId}/logbook/deficiencies`),
        apiClient.get(`/api/projects/${projectId}/logbook/attestations`),
      ]);
      const all = [
        ...(missing.data?.entries || []),
        ...(deficiencies.data?.entries || []),
        ...(attestations.data?.entries || []),
      ].filter((e) => (e.entry_date || '').slice(0, 10) === dayKey);
      setDrawerEntries(all);
    } catch (_e) {
      setDrawerEntries([]);
    } finally {
      setDrawerLoading(false);
    }
  };

  const onExport = async () => {
    setExportBusy(true);
    try {
      const r = await apiClient.get(
        `/api/projects/${projectId}/logbook/export?format=pdf`,
        { responseType: 'blob' },
      );
      // Blob URL → download. RN-Web supports document.createElement.
      if (typeof window !== 'undefined' && window.document) {
        const url = window.URL.createObjectURL(r.data);
        const a = window.document.createElement('a');
        a.href = url;
        a.download = `logbook-${projectId}.pdf`;
        a.click();
        window.URL.revokeObjectURL(url);
      }
    } catch (_e) {
      // Soft-fail; the user sees the button stop spinning.
    } finally {
      setExportBusy(false);
    }
  };

  const days = auditData?.days || [];
  // Group by week so the calendar wraps cleanly. The backend
  // returns days in chronological order; we just chunk by 7.
  const weeks = [];
  for (let i = 0; i < days.length; i += 7) {
    weeks.push(days.slice(i, i + 7));
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        {/* Header */}
        <View style={styles.headerBar}>
          <Pressable
            onPress={() => router.back()}
            style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.65 }]}
            accessibilityLabel="Go back"
          >
            <ArrowLeft size={20} color={colors.text.primary} />
          </Pressable>
          <HeaderBrand />
          <Pressable
            onPress={onExport}
            disabled={exportBusy}
            style={({ pressed }) => [styles.exportBtn, pressed && { opacity: 0.65 }]}
            accessibilityLabel="Export audit PDF"
          >
            {exportBusy ? (
              <ActivityIndicator size="small" color={colors.text.primary} />
            ) : (
              <Download size={18} color={colors.text.primary} />
            )}
          </Pressable>
        </View>

        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <Text style={styles.eyebrow}>COMPLIANCE LOGBOOK</Text>
          <Text style={styles.title}>Audit calendar</Text>
          <Text style={styles.subtitle}>
            Daily compliance status for the last 30 days. Tap a day for detail.
          </Text>

          <GlassCard style={styles.calendarCard} hoverEffect={false}>
            {loading ? (
              <View style={styles.loadingWrap}>
                <ActivityIndicator size="large" color={colors.text.primary} />
              </View>
            ) : (
              <View>
                {weeks.map((week, wi) => (
                  <View key={wi} style={styles.weekRow}>
                    {week.map((d) => {
                      const cfg = COLOR_MAP[d.color] || COLOR_MAP.grey;
                      const dayLabel = (d.date || '').slice(8, 10);
                      const isSelected = selectedDay === d.date;
                      return (
                        <Pressable
                          key={d.date}
                          onPress={() => onDayPress(d.date)}
                          style={({ pressed }) => [
                            styles.dayCell,
                            {
                              backgroundColor: cfg.bg,
                              borderColor: isSelected
                                ? colors.text.primary
                                : cfg.border,
                              borderWidth: isSelected ? 2 : 1,
                              opacity: pressed ? 0.7 : 1,
                            },
                          ]}
                        >
                          <Text style={[styles.dayNum, { color: colors.text.primary }]}>
                            {dayLabel}
                          </Text>
                          <Text style={[styles.dayLabel, { color: colors.text.muted }]}>
                            {cfg.label}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>
                ))}
              </View>
            )}
          </GlassCard>

          {/* Drawer = inline panel below the calendar */}
          {selectedDay ? (
            <GlassCard style={styles.drawerCard} hoverEffect={false}>
              <View style={styles.drawerHeader}>
                <View>
                  <Text style={styles.drawerEyebrow}>SELECTED DAY</Text>
                  <Text style={styles.drawerTitle}>{selectedDay}</Text>
                </View>
                <Pressable
                  onPress={() => setSelectedDay(null)}
                  accessibilityLabel="Close drawer"
                >
                  <X size={18} color={colors.text.muted} />
                </Pressable>
              </View>
              {drawerLoading ? (
                <ActivityIndicator size="small" color={colors.text.primary} />
              ) : drawerEntries.length === 0 ? (
                <Text style={styles.emptyText}>
                  No deficiencies or missing entries for this day.
                </Text>
              ) : (
                drawerEntries.map((e) => (
                  <View key={e.id || e._id || `${e.entry_date}-${e.category}`}
                        style={styles.entryRow}>
                    <Text style={styles.entryCategory}>
                      {(e.category || '').toUpperCase()}
                    </Text>
                    <Text style={styles.entryStatus}>
                      {(e.status || '').toUpperCase()}
                    </Text>
                    {e.deficiency_reason ? (
                      <Text style={styles.entryReason}>{e.deficiency_reason}</Text>
                    ) : null}
                  </View>
                ))
              )}
            </GlassCard>
          ) : null}

          <View style={{ height: 60 }} />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: 'transparent' },
    headerBar: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      backgroundColor: colors.glass.background,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    backBtn: {
      width: 36, height: 36, alignItems: 'center', justifyContent: 'center',
      borderRadius: 18,
    },
    exportBtn: {
      width: 36, height: 36, alignItems: 'center', justifyContent: 'center',
      borderRadius: 18,
    },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingTop: spacing.lg,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },
    eyebrow: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.xs,
    },
    title: {
      fontSize: 28, fontWeight: '600', color: colors.text.primary,
      letterSpacing: -0.5, marginBottom: spacing.xs,
    },
    subtitle: {
      fontSize: 14, lineHeight: 20, color: colors.text.secondary,
      marginBottom: spacing.lg,
    },
    calendarCard: { padding: spacing.md },
    loadingWrap: {
      paddingVertical: spacing.xl,
      alignItems: 'center', justifyContent: 'center',
    },
    weekRow: {
      flexDirection: 'row',
      gap: spacing.xs,
      marginBottom: spacing.xs,
    },
    dayCell: {
      flex: 1,
      aspectRatio: 1,
      borderRadius: borderRadius.md,
      alignItems: 'center', justifyContent: 'center',
      paddingVertical: spacing.xs,
    },
    dayNum: {
      fontSize: 16, fontWeight: '600',
    },
    dayLabel: {
      fontSize: 9, marginTop: 2, letterSpacing: 0.3,
      textTransform: 'uppercase',
    },
    drawerCard: { marginTop: spacing.md, padding: spacing.lg },
    drawerHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: spacing.md,
    },
    drawerEyebrow: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: 2,
    },
    drawerTitle: {
      fontSize: 17, fontWeight: '600', color: colors.text.primary,
    },
    emptyText: {
      fontSize: 13, color: colors.text.muted, paddingVertical: spacing.md,
    },
    entryRow: {
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    entryCategory: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: 2,
    },
    entryStatus: {
      fontSize: 13, fontWeight: '600', color: colors.text.primary,
    },
    entryReason: {
      fontSize: 12, lineHeight: 16, color: colors.text.secondary,
      marginTop: 4,
    },
  });
}
