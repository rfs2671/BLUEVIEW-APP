/**
 * Permit Renewal — "One-Tap Renewal" Screen
 * ═══════════════════════════════════════════
 * frontend/app/project/[id]/permit-renewal.jsx
 *
 * Flow:
 *   1. Shows expiring permits with eligibility details
 *   2. "Prepare Renewal" — triggers RPA to draft on DOB NOW
 *   3. "Sign & Pay on DOB NOW" — deep-links GC to their filing
 *   4. Status monitor detects completion automatically
 */

import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Linking,
  RefreshControl,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Shield,
  ShieldCheck,
  ShieldAlert,
  FileCheck,
  CheckCircle,
  AlertTriangle,
  Clock,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  XCircle,
  Building2,
  BadgeCheck,
  Loader,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { useTheme } from '../../../src/context/ThemeContext';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import apiClient from '../../../src/utils/api';

// ══════════════════════════════════════════════════════════════════════════════
// INLINE API (mirrors permitRenewalAPI.js)
// ══════════════════════════════════════════════════════════════════════════════

const renewalAPI = {
  list: async (projectId) => {
    const resp = await apiClient.get(
      `/api/permit-renewals?project_id=${projectId}&limit=50`
    );
    return resp.data;
  },
  prepare: async (permitDobLogId, projectId) => {
    const resp = await apiClient.post('/api/permit-renewals/prepare', {
      permit_dob_log_id: permitDobLogId,
      project_id: projectId,
    });
    return resp.data;
  },
};

// ══════════════════════════════════════════════════════════════════════════════
// HELPERS
// ══════════════════════════════════════════════════════════════════════════════

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) {
    if (typeof dateStr === 'string' && dateStr.includes('/')) return dateStr;
    return String(dateStr).slice(0, 10);
  }
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const STATUS_CONFIG = {
  eligible: {
    label: 'Renewal Ready',
    color: '#22c55e',
    bg: '#22c55e15',
    icon: ShieldCheck,
    description: 'This permit is eligible for automated renewal. Tap "Prepare Renewal" to create a draft on DOB NOW.',
  },
  ineligible_insurance: {
    label: 'Insurance Update Required',
    color: '#f59e0b',
    bg: '#f59e0b15',
    icon: ShieldAlert,
    description: 'Insurance must be updated before renewal can proceed. See details below.',
  },
  ineligible_license: {
    label: 'License Issue',
    color: '#ef4444',
    bg: '#ef444415',
    icon: XCircle,
    description: 'GC License issue prevents automated renewal.',
  },
  draft_ready: {
    label: 'Draft Ready',
    color: '#3b82f6',
    bg: '#3b82f615',
    icon: FileCheck,
    description: 'Renewal draft prepared on DOB NOW. Tap below to sign & pay on the DOB portal.',
  },
  awaiting_gc: {
    label: 'Awaiting GC',
    color: '#8b5cf6',
    bg: '#8b5cf615',
    icon: ExternalLink,
    description: 'Renewal draft is on DOB NOW. The GC needs to log in, sign, and pay to complete.',
  },
  completed: {
    label: 'Completed',
    color: '#22c55e',
    bg: '#22c55e15',
    icon: BadgeCheck,
    description: 'Permit renewed successfully.',
  },
  failed: {
    label: 'Failed',
    color: '#ef4444',
    bg: '#ef444415',
    icon: XCircle,
    description: 'Renewal failed. Manual action may be required on DOB NOW.',
  },
};

const getStatusConfig = (status) =>
  STATUS_CONFIG[status] || STATUS_CONFIG.eligible;

// ══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

export default function PermitRenewalScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [renewals, setRenewals] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  const [preparing, setPreparing] = useState(null);
  const [projectName, setProjectName] = useState('');

  // Auth guard
  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const timer = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) fetchRenewals();
  }, [isAuthenticated, projectId]);

  const fetchRenewals = async () => {
    if (!loading) setRefreshing(true);
    try {
      const data = await renewalAPI.list(projectId);
      setRenewals(data.renewals || []);
      if (data.renewals?.length > 0 && data.renewals[0].project_name) {
        setProjectName(data.renewals[0].project_name);
      }
    } catch (error) {
      console.error('Failed to fetch renewals:', error);
      toast.error('Error', 'Could not load permit renewals');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // ── Prepare Renewal (triggers RPA) ────────────────────────────────
  const handlePrepare = async (renewal) => {
    setPreparing(renewal.id);
    try {
      const result = await renewalAPI.prepare(
        renewal.permit_dob_log_id,
        renewal.project_id
      );
      toast.success(
        'Renewal Prepared',
        'Draft filed on DOB NOW. Tap "Sign & Pay on DOB NOW" to complete.'
      );
      await fetchRenewals();
    } catch (error) {
      const detail = error.response?.data?.detail;
      if (typeof detail === 'object' && detail.blocking_reasons) {
        toast.error('Not Eligible', detail.blocking_reasons.join('\n'));
      } else {
        toast.error(
          'Error',
          typeof detail === 'string'
            ? detail
            : 'Could not prepare renewal'
        );
      }
    } finally {
      setPreparing(null);
    }
  };

  // ── Open DOB NOW (deep-link) ──────────────────────────────────────
  const handleOpenDobNow = async (renewal) => {
    const url = renewal.dob_now_url;
    if (!url) {
      toast.error('Error', 'DOB NOW URL not available yet. Prepare the renewal first.');
      return;
    }

    try {
      const supported = await Linking.canOpenURL(url);
      if (supported) {
        await Linking.openURL(url);
        toast.info(
          'Opening DOB NOW',
          'Log in with your NYC.ID, sign the filing, and pay the DOB fee. Blueview will detect completion automatically.'
        );
      } else {
        toast.error('Error', 'Cannot open DOB NOW URL');
      }
    } catch (error) {
      toast.error('Error', 'Failed to open DOB NOW');
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // ── Stats ─────────────────────────────────────────────────────────
  const eligibleCount = renewals.filter(
    (r) => r.status === 'eligible'
  ).length;
  const awaitingCount = renewals.filter((r) =>
    ['draft_ready', 'awaiting_gc'].includes(r.status)
  ).length;
  const completedCount = renewals.filter(
    (r) => r.status === 'completed'
  ).length;
  const blockedCount = renewals.filter((r) =>
    ['ineligible_insurance', 'ineligible_license', 'failed'].includes(
      r.status
    )
  ).length;

  const renderStats = () => (
    <View style={s.statsRow}>
      <StatCard style={s.statCard}>
        <Text style={s.statValue}>{eligibleCount}</Text>
        <Text style={s.statLabel}>Ready</Text>
      </StatCard>
      <StatCard style={s.statCard}>
        <Text style={[s.statValue, { color: '#8b5cf6' }]}>
          {awaitingCount}
        </Text>
        <Text style={s.statLabel}>Awaiting GC</Text>
      </StatCard>
      <StatCard style={s.statCard}>
        <Text style={[s.statValue, { color: '#22c55e' }]}>
          {completedCount}
        </Text>
        <Text style={s.statLabel}>Done</Text>
      </StatCard>
      <StatCard style={s.statCard}>
        <Text style={[s.statValue, { color: '#f59e0b' }]}>
          {blockedCount}
        </Text>
        <Text style={s.statLabel}>Blocked</Text>
      </StatCard>
    </View>
  );

  // ── Renewal Card ──────────────────────────────────────────────────
  const renderRenewalCard = (renewal) => {
    const isExpanded = expandedId === renewal.id;
    const statusCfg = getStatusConfig(renewal.status);
    const StatusIcon = statusCfg.icon;
    const daysLeft = renewal.days_until_expiry;
    const isUrgent = daysLeft !== null && daysLeft <= 7;
    const canPrepare = renewal.status === 'eligible';
    const canOpenDob = ['draft_ready', 'awaiting_gc'].includes(
      renewal.status
    ) && renewal.dob_now_url;
    const isComplete = renewal.status === 'completed';

    return (
      <Pressable
        key={renewal.id}
        onPress={() =>
          setExpandedId(isExpanded ? null : renewal.id)
        }
      >
        <GlassCard style={s.renewalCard}>
          {/* Header */}
          <View style={s.cardHeader}>
            <View style={s.cardHeaderLeft}>
              <View
                style={[
                  s.statusDot,
                  { backgroundColor: statusCfg.color },
                ]}
              />
              <View
                style={[
                  s.statusBadge,
                  {
                    backgroundColor: statusCfg.bg,
                    borderColor: statusCfg.color + '40',
                  },
                ]}
              >
                <StatusIcon
                  size={14}
                  color={statusCfg.color}
                  strokeWidth={2}
                />
                <Text
                  style={[
                    s.statusLabel,
                    { color: statusCfg.color },
                  ]}
                >
                  {statusCfg.label}
                </Text>
              </View>
            </View>
            <View style={s.cardHeaderRight}>
              {daysLeft !== null && daysLeft >= 0 && (
                <View
                  style={[
                    s.daysChip,
                    isUrgent && s.daysChipUrgent,
                  ]}
                >
                  <Clock
                    size={12}
                    color={
                      isUrgent ? '#ef4444' : colors.text.muted
                    }
                  />
                  <Text
                    style={[
                      s.daysText,
                      isUrgent && {
                        color: '#ef4444',
                        fontWeight: '700',
                      },
                    ]}
                  >
                    {daysLeft}d
                  </Text>
                </View>
              )}
              {isExpanded ? (
                <ChevronUp
                  size={16}
                  color={colors.text.muted}
                />
              ) : (
                <ChevronDown
                  size={16}
                  color={colors.text.muted}
                />
              )}
            </View>
          </View>

          {/* Summary */}
          <View style={s.cardBody}>
            <Text style={s.jobNumber}>
              Job {renewal.job_number || '—'}
            </Text>
            <Text style={s.permitType}>
              {renewal.permit_type || 'Work Permit'} · Expires{' '}
              {formatDate(renewal.current_expiration)}
            </Text>
          </View>

          {/* Expanded Details */}
          {isExpanded && (
            <View style={s.expandedSection}>
              <Text style={s.statusDesc}>
                {statusCfg.description}
              </Text>

              {/* GC License */}
              {renewal.gc_license_number && (
                <View style={s.infoRow}>
                  <Building2
                    size={14}
                    color={colors.text.muted}
                  />
                  <Text style={s.infoText}>
                    License: {renewal.gc_license_number} —{' '}
                    {renewal.gc_license_status || 'Unknown'}
                  </Text>
                </View>
              )}

              {/* Insurance */}
              {(renewal.insurance_gl_expiry ||
                renewal.insurance_wc_expiry ||
                renewal.insurance_db_expiry) && (
                <View style={s.insuranceBlock}>
                  <Text style={s.insuranceTitle}>
                    Insurance Coverage
                  </Text>
                  {renewal.insurance_gl_expiry && (
                    <View style={s.insuranceRow}>
                      <Text style={s.insuranceLabel}>
                        General Liability
                      </Text>
                      <Text style={s.insuranceValue}>
                        {formatDate(renewal.insurance_gl_expiry)}
                      </Text>
                    </View>
                  )}
                  {renewal.insurance_wc_expiry && (
                    <View style={s.insuranceRow}>
                      <Text style={s.insuranceLabel}>
                        Workers' Comp
                      </Text>
                      <Text style={s.insuranceValue}>
                        {formatDate(renewal.insurance_wc_expiry)}
                      </Text>
                    </View>
                  )}
                  {renewal.insurance_db_expiry && (
                    <View style={s.insuranceRow}>
                      <Text style={s.insuranceLabel}>
                        Disability
                      </Text>
                      <Text style={s.insuranceValue}>
                        {formatDate(renewal.insurance_db_expiry)}
                      </Text>
                    </View>
                  )}
                </View>
              )}

              {/* Blocking Reasons */}
              {renewal.blocking_reasons?.length > 0 && (
                <View style={s.blockingBlock}>
                  <AlertTriangle size={14} color="#f59e0b" />
                  {renewal.blocking_reasons.map((reason, i) => (
                    <Text key={i} style={s.blockingText}>
                      {reason}
                    </Text>
                  ))}
                </View>
              )}

              {/* Action Buttons */}
              <View style={s.actionsRow}>
                {canPrepare && (
                  <GlassButton
                    title={
                      preparing === renewal.id
                        ? 'Preparing on DOB NOW...'
                        : 'Prepare Renewal'
                    }
                    icon={
                      preparing === renewal.id ? (
                        <ActivityIndicator
                          size="small"
                          color={colors.text.primary}
                        />
                      ) : (
                        <FileCheck
                          size={16}
                          color="#22c55e"
                        />
                      )
                    }
                    onPress={() => handlePrepare(renewal)}
                    disabled={preparing === renewal.id}
                    style={[
                      s.actionBtn,
                      { borderColor: '#22c55e40' },
                    ]}
                  />
                )}

                {canOpenDob && (
                  <GlassButton
                    title="Sign & Pay on DOB NOW"
                    icon={
                      <ExternalLink
                        size={16}
                        color="#8b5cf6"
                      />
                    }
                    onPress={() => handleOpenDobNow(renewal)}
                    style={[
                      s.actionBtn,
                      { borderColor: '#8b5cf640' },
                    ]}
                  />
                )}

                {isComplete && (
                  <View style={s.completedBadge}>
                    <BadgeCheck
                      size={16}
                      color="#22c55e"
                    />
                    <Text style={s.completedText}>
                      Permit renewed successfully
                    </Text>
                  </View>
                )}

                {renewal.status === 'failed' && (
                  <View style={s.completedBadge}>
                    <XCircle size={16} color="#ef4444" />
                    <Text
                      style={[
                        s.completedText,
                        { color: '#ef4444' },
                      ]}
                    >
                      Manual renewal required on DOB NOW
                    </Text>
                  </View>
                )}
              </View>
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  // ── Main Render ───────────────────────────────────────────────────
  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator
              size="large"
              color={colors.text.primary}
            />
            <Text style={s.loadingText}>LOADING RENEWALS</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <Pressable
              onPress={() => router.back()}
              style={s.backBtn}
            >
              <ArrowLeft
                size={20}
                color={colors.text.primary}
              />
            </Pressable>
            <View>
              <Text style={s.headerTitle}>
                Permit Renewals
              </Text>
              {projectName ? (
                <Text style={s.headerSubtitle}>
                  {projectName}
                </Text>
              ) : null}
            </View>
          </View>
          <Pressable
            onPress={handleLogout}
            style={s.logoutBtn}
          >
            <LogOut size={18} color={colors.text.muted} />
          </Pressable>
        </View>

        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={fetchRenewals}
              tintColor={colors.text.muted}
            />
          }
        >
          {renderStats()}

          {/* Info Banner */}
          <GlassCard style={s.infoBanner}>
            <View style={s.infoBannerContent}>
              <IconPod size={40}>
                <Shield
                  size={20}
                  color={colors.text.primary}
                  strokeWidth={1.5}
                />
              </IconPod>
              <View style={s.infoBannerText}>
                <Text style={s.infoBannerTitle}>
                  One-Tap Renewal
                </Text>
                <Text style={s.infoBannerDesc}>
                  Expiring permits appear here automatically.
                  Blueview prepares the draft — you just sign
                  and pay on DOB NOW.
                </Text>
              </View>
            </View>
          </GlassCard>

          {/* Cards */}
          {renewals.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <ShieldCheck
                size={48}
                strokeWidth={1}
                color={colors.text.subtle}
              />
              <Text style={s.emptyTitle}>
                No Renewals Pending
              </Text>
              <Text style={s.emptyDesc}>
                Permits expiring within 30 days will
                automatically appear here.
              </Text>
            </GlassCard>
          ) : (
            <View style={s.cardsList}>
              {renewals.map(renderRenewalCard)}
            </View>
          )}

          <View style={{ height: 100 }} />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// STYLES
// ══════════════════════════════════════════════════════════════════════════════

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingContainer: {
      flex: 1,
      justifyContent: 'center',
      alignItems: 'center',
      gap: spacing.md,
    },
    loadingText: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.muted,
      letterSpacing: 2,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    backBtn: {
      width: 40,
      height: 40,
      borderRadius: borderRadius.full,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerTitle: {
      fontFamily: typography.semibold,
      fontSize: 18,
      color: colors.text.primary,
    },
    headerSubtitle: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 1,
    },
    logoutBtn: {
      width: 40,
      height: 40,
      borderRadius: borderRadius.full,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    scroll: { flex: 1 },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingTop: spacing.sm,
      paddingBottom: 120,
    },
    statsRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginBottom: spacing.lg,
    },
    statCard: {
      flex: 1,
      alignItems: 'center',
      paddingVertical: spacing.md,
    },
    statValue: {
      fontFamily: typography.bold,
      fontSize: 22,
      color: colors.text.primary,
    },
    statLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      marginTop: 2,
      letterSpacing: 0.5,
    },
    infoBanner: { marginBottom: spacing.lg },
    infoBannerContent: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    infoBannerText: { flex: 1 },
    infoBannerTitle: {
      fontFamily: typography.semibold,
      fontSize: 15,
      color: colors.text.primary,
      marginBottom: 3,
    },
    infoBannerDesc: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 18,
    },
    cardsList: { gap: spacing.md },
    renewalCard: { marginBottom: 0 },
    cardHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.sm,
    },
    cardHeaderLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    cardHeaderRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    statusDot: {
      width: 8,
      height: 8,
      borderRadius: 4,
    },
    statusBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingHorizontal: spacing.sm,
      paddingVertical: 3,
      borderRadius: borderRadius.md,
      borderWidth: 1,
    },
    statusLabel: {
      fontFamily: typography.medium,
      fontSize: 11,
      letterSpacing: 0.3,
    },
    daysChip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 3,
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderRadius: borderRadius.sm,
      backgroundColor: colors.glass.background,
    },
    daysChipUrgent: { backgroundColor: '#ef444415' },
    daysText: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.muted,
    },
    cardBody: { marginBottom: spacing.xs },
    jobNumber: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
      marginBottom: 2,
    },
    permitType: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
    },
    expandedSection: {
      marginTop: spacing.md,
      paddingTop: spacing.md,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    statusDesc: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      marginBottom: spacing.md,
      lineHeight: 18,
    },
    infoRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      marginBottom: spacing.sm,
    },
    infoText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
    },
    insuranceBlock: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      padding: spacing.md,
      marginBottom: spacing.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    insuranceTitle: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: colors.text.muted,
      letterSpacing: 0.5,
      textTransform: 'uppercase',
      marginBottom: spacing.sm,
    },
    insuranceRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      paddingVertical: 4,
    },
    insuranceLabel: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
    },
    insuranceValue: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },
    blockingBlock: {
      backgroundColor: '#f59e0b10',
      borderRadius: borderRadius.lg,
      padding: spacing.md,
      marginBottom: spacing.md,
      gap: spacing.xs,
      borderWidth: 1,
      borderColor: '#f59e0b30',
    },
    blockingText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: '#f59e0b',
      lineHeight: 18,
    },
    actionsRow: { gap: spacing.sm },
    actionBtn: { marginBottom: 0 },
    completedBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingVertical: spacing.sm,
    },
    completedText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: '#22c55e',
    },
    emptyCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
    },
    emptyTitle: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
    },
    emptyDesc: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.muted,
      textAlign: 'center',
      lineHeight: 18,
      maxWidth: 280,
    },
  });
}
