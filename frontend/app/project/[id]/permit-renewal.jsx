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
import * as Clipboard from 'expo-clipboard';
import {
  ArrowLeft,
  Shield,
  ShieldCheck,
  ShieldAlert,
  FileCheck,
  CheckCircle,
  AlertTriangle,
  Clock,
  ExternalLink,
  Copy,
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
import { MANUAL_RENEWAL_RULE_CITATION } from '../../../src/constants/dobRules';

// ══════════════════════════════════════════════════════════════════════════════
// INLINE API (mirrors permitRenewalAPI.js)
// ══════════════════════════════════════════════════════════════════════════════

const renewalAPI = {
  list: async (projectId) => {
    // Try the dedicated renewals endpoint first, fall back to dob_logs permits
    try {
      const resp = await apiClient.get(
        `/api/permit-renewals?project_id=${projectId}&limit=50`
      );
      if (resp.data?.renewals?.length > 0) return resp.data;
    } catch (e) {
      console.log('Renewal endpoint unavailable, falling back to dob_logs');
    }
    // Fallback: build renewals from dob_logs permits
    const logsResp = await apiClient.get(
      `/api/projects/${projectId}/dob-logs?record_type=permit&limit=200`
    );
    const logs = logsResp.data?.logs || [];
    const now = new Date();
    const renewals = logs
      .filter(l => {
        // Show permits expiring within 30 days or already expired (up to 60 days past)
        if (l.expiration_date) {
          const exp = new Date(l.expiration_date);
          if (!isNaN(exp.getTime())) {
            const daysLeft = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
            return daysLeft <= 30 && daysLeft >= -60;
          }
        }
        // Also show permits with "expired" in their status even without a parseable date
        const status = (l.permit_status || l.status || '').toLowerCase();
        if (status.includes('expired') || status.includes('revoked')) return true;
        // Also show permits flagged as needing action (severity === "Action")
        if (l.severity === 'Action' && l.record_type === 'permit') return true;
        return false;
      })
      .map(l => {
        let daysLeft = null;
        if (l.expiration_date) {
          const exp = new Date(l.expiration_date);
          if (!isNaN(exp.getTime())) {
            daysLeft = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
          }
        }
        return {
          id: l.id,
          permit_dob_log_id: l.id,
          project_id: logsResp.data?.project_id,
          project_name: logsResp.data?.project_name,
          job_number: l.job_number,
          permit_type: l.permit_type || l.work_type,
          current_expiration: l.expiration_date,
          days_until_expiry: daysLeft,
          status: 'eligible',
          dob_now_url: null,
          gc_license_number: null,
          gc_license_status: null,
          insurance_gl_expiry: null,
          insurance_wc_expiry: null,
          insurance_db_expiry: null,
          blocking_reasons: [],
        };
      });
    // Deduplicate: group by full job number + work type since sub-permits
    // (e.g. X01180463-S6 Sprinklers vs X01180463-I1 General Construction)
    // are independent scopes of work with their own expiration dates
    const byPermit = {};
    for (const r of renewals) {
      const key = `${r.job_number || r.id}:${r.permit_type || ''}`;
      if (!byPermit[key] || new Date(r.current_expiration) > new Date(byPermit[key].current_expiration)) {
        byPermit[key] = r;
      }
    }
    const dedupedRenewals = Object.values(byPermit);
    return { renewals: dedupedRenewals, project_id: logsResp.data?.project_id, project_name: logsResp.data?.project_name };
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
  needs_insurance: {
    label: 'Insurance Required',
    color: '#f59e0b',
    bg: '#f59e0b15',
    icon: ShieldAlert,
    description: 'Enter your certificate of insurance dates in Settings to enable renewal eligibility.',
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

// Step 6.2.2: v2 enrichment field rendering.
// `renewal_strategy` enum values come from
// `backend/lib/eligibility_v2.py::RENEWAL_STRATEGIES`. The labels here
// are user-facing copy. If the backend adds a new strategy and this
// map doesn't have an entry, the raw enum value is shown as a fallback
// (still informative, not a crash).
const STRATEGY_LABELS = {
  AUTO_EXTEND_DOB_NOW:  'Auto-extend (DOB NOW)',
  AUTO_EXTEND_BIS_31D:  'Auto-extend (BIS 31-day)',
  AWAITING_EXTENSION:   'Awaiting extension',
  MANUAL_1YR_CEILING:   'Manual renewal — 1-yr ceiling',
  MANUAL_FEE_PAID:      'Manual renewal — fee paid',
  MANUAL_INSURANCE:     'Manual — insurance',
};

const formatStrategy = (s) => STRATEGY_LABELS[s] || (s ? String(s) : null);

// Action.kind comes from `backend/lib/eligibility_v2.py::_build_action`
// (snake_case enum-ish). Render as Title Case for the user-facing
// "Next Steps" header.
const formatActionKind = (k) => {
  if (!k) return null;
  return String(k)
    .split('_')
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
};

// ══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

export default function PermitRenewalScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [renewals, setRenewals] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  const [preparing, setPreparing] = useState(null);
  const [projectName, setProjectName] = useState('');
  const [renewalData, setRenewalData] = useState(null);

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
      setRenewalData(result);
      toast.success(
        'Renewal Prepared',
        'Review the details below and complete the renewal on DOB NOW.'
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
          'Log in with your NYC.ID, sign the filing, and pay the DOB fee. LeveLog will detect completion automatically.'
        );
      } else {
        toast.error('Error', 'Cannot open DOB NOW URL');
      }
    } catch (error) {
      toast.error('Error', 'Failed to open DOB NOW');
    }
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
    ['needs_insurance', 'ineligible_insurance', 'ineligible_license', 'failed'].includes(
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
    const canOpenDob = renewal.status === 'eligible' || (['draft_ready', 'awaiting_gc'].includes(renewal.status) && renewal.dob_now_url);
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
              {daysLeft !== null && (
                <View
                  style={[
                    s.daysChip,
                    (isUrgent || daysLeft < 0) && s.daysChipUrgent,
                  ]}
                >
                  <Clock
                    size={12}
                    color={
                      (isUrgent || daysLeft < 0) ? '#ef4444' : colors.text.muted
                    }
                  />
                  <Text
                    style={[
                      s.daysText,
                      (isUrgent || daysLeft < 0) && {
                        color: '#ef4444',
                        fontWeight: '700',
                      },
                    ]}
                  >
                    {daysLeft < 0 ? `${Math.abs(daysLeft)}d overdue` : `${daysLeft}d`}
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
            {/* v2 enrichment: when limiting_factor.label is present,
                the "why this date" reason becomes the primary expiry
                line. effective_expiry (post §1.1 ceilings) replaces
                the calendar expiration; the calendar date is demoted
                to a small caption when the two differ. Falls back to
                the legacy "Expires {current_expiration}" line when v2
                fields are absent — that's the deploy-window state
                between 6.2.1 ship and the dispatcher flip. */}
            {renewal.limiting_factor?.label ? (
              <>
                <Text style={s.permitType}>
                  {renewal.permit_type || 'Work Permit'} · Expires{' '}
                  {formatDate(renewal.effective_expiry || renewal.current_expiration)}
                  {' — '}
                  {renewal.limiting_factor.label}
                </Text>
                {renewal.effective_expiry &&
                 renewal.current_expiration &&
                 renewal.effective_expiry !== renewal.current_expiration && (
                  <Text style={s.expiryCalendarCaption}>
                    Calendar: {formatDate(renewal.current_expiration)}
                  </Text>
                )}
              </>
            ) : (
              <Text style={s.permitType}>
                {renewal.permit_type || 'Work Permit'} · Expires{' '}
                {formatDate(renewal.current_expiration)}
              </Text>
            )}
            {/* Strategy badge — only when the v2 dispatcher populated
                renewal_strategy. Absent means legacy/shadow mode and
                we render nothing here. */}
            {renewal.renewal_strategy && (
              <View style={s.strategyBadge}>
                <Text style={s.strategyText}>
                  {formatStrategy(renewal.renewal_strategy)}
                </Text>
              </View>
            )}
          </View>

          {/* Expanded Details */}
          {isExpanded && (
            <View style={s.expandedSection}>
              {/* MR.1 — manual renewal information panel.
                  Renders when the v2 dispatcher emits action.kind ===
                  "manual_renewal_dob_now" (the MANUAL_1YR_CEILING
                  branch in eligibility_v2.py:_build_action). For that
                  case the legacy ineligibility framing is misleading
                  ("Insurance Update Required" badge stays because
                  status === ineligible_insurance, which is the closest
                  bucket the writer can pick — see permit_renewal.py
                  ~line 1099-1104), so the panel below provides the
                  real reason and the next step.
                  TODO(MR.1.5+): replace this one-off conditional with
                  the actionRenderers map per the §14 plan.
                  TODO(data plumbing): renewal.issuance_date isn't on
                  the persisted record — RenewalEligibility doesn't
                  carry it, so the explanation copy is generic rather
                  than calling out the specific issuance date. Fix in
                  a small follow-up before MR.4.
              */}
              {renewal.action?.kind === 'manual_renewal_dob_now' ? (
                <View style={s.manualRenewalPanel}>
                  <Text style={s.manualRenewalHeader}>
                    Manual Renewal Required
                  </Text>
                  <Text style={s.manualRenewalExplanation}>
                    This permit has reached the one-year mark from
                    original issuance. NYC DOB requires work permits
                    older than one year to be renewed manually,
                    regardless of insurance status. Filing happens at
                    DOB NOW with the licensee's NYC.ID.
                  </Text>

                  <View style={s.manualRenewalFeeBlock}>
                    <Text style={s.manualRenewalFee}>$130</Text>
                    <Text style={s.manualRenewalFeeCaption}>
                      paid directly to NYC DOB
                    </Text>
                  </View>

                  <View style={s.manualRenewalDetails}>
                    <View style={s.manualRenewalDetailRow}>
                      <Text style={s.manualRenewalDetailLabel}>
                        Job Filing Number
                      </Text>
                      <Text style={s.manualRenewalDetailValue}>
                        {renewal.job_number || '—'}
                      </Text>
                    </View>
                    <View style={s.manualRenewalDetailRow}>
                      <Text style={s.manualRenewalDetailLabel}>
                        Work Type
                      </Text>
                      <Text style={s.manualRenewalDetailValue}>
                        {renewal.permit_type || '—'}
                      </Text>
                    </View>
                    <View style={s.manualRenewalDetailRow}>
                      <Text style={s.manualRenewalDetailLabel}>
                        Current Expiration
                      </Text>
                      <Text style={s.manualRenewalDetailValue}>
                        {formatDate(renewal.current_expiration)}
                      </Text>
                    </View>
                    <View style={s.manualRenewalDetailRow}>
                      <Text style={s.manualRenewalDetailLabel}>
                        Days Until Expiration
                      </Text>
                      <Text style={s.manualRenewalDetailValue}>
                        {typeof renewal.days_until_expiry === 'number'
                          ? `${renewal.days_until_expiry}d`
                          : '—'}
                      </Text>
                    </View>
                  </View>

                  <Pressable
                    disabled
                    style={[s.manualRenewalCta, s.manualRenewalCtaDisabled]}
                  >
                    <Text style={s.manualRenewalCtaText}>Prepare Filing</Text>
                  </Pressable>
                  <Text style={s.manualRenewalCtaCaption}>
                    Filing workflow coming soon — MR.2 through MR.6
                  </Text>

                  <Text style={s.manualRenewalCitation}>
                    Reference: {MANUAL_RENEWAL_RULE_CITATION}
                  </Text>
                </View>
              ) : (
                <Text style={s.statusDesc}>
                  {statusCfg.description}
                </Text>
              )}

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

              {/* needs_insurance: soft-prompt CTA sending the admin to Settings */}
              {renewal.status === 'needs_insurance' && (
                <GlassCard
                  style={{
                    backgroundColor: '#f59e0b15',
                    borderColor: '#f59e0b40',
                    borderWidth: 1,
                    marginBottom: 12,
                    padding: 14,
                  }}
                >
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
                    <ShieldAlert size={18} color="#f59e0b" style={{ marginTop: 2 }} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontFamily: typography.semibold, fontSize: 14, color: '#f59e0b', marginBottom: 4 }}>
                        Insurance Required
                      </Text>
                      <Text style={{ fontFamily: typography.regular, fontSize: 13, color: colors.text.secondary, lineHeight: 18 }}>
                        Your insurance expiry dates haven't been entered yet. This is required to verify renewal eligibility.
                      </Text>
                      <GlassButton
                        title="Go to Settings"
                        icon={<ExternalLink size={14} color={colors.text.primary} />}
                        onPress={() => router.push('/settings')}
                        style={{ marginTop: 12, alignSelf: 'flex-start' }}
                      />
                    </View>
                  </View>
                </GlassCard>
              )}

              {/* v2 Next Steps — populated by `_build_action` in
                  eligibility_v2.py when the dispatcher is in live
                  mode. Absent in shadow / legacy / off mode, in which
                  case this block doesn't render. action.instructions
                  is a string list; we number them for clarity.
                  Suppressed for manual_renewal_dob_now because the
                  MR.1 panel above already conveys the next step in a
                  more operator-friendly form. */}
              {renewal.action?.kind !== 'manual_renewal_dob_now' &&
               renewal.action && (renewal.action.kind || (renewal.action.instructions || []).length > 0) && (
                <View style={s.actionBlock}>
                  {renewal.action.kind && (
                    <Text style={s.actionTitle}>
                      Next Steps · {formatActionKind(renewal.action.kind)}
                      {typeof renewal.action.deadline_days === 'number'
                        ? ` (${renewal.action.deadline_days}d)`
                        : ''}
                    </Text>
                  )}
                  {(renewal.action.instructions || []).map((step, i) => (
                    <View key={i} style={s.actionStepRow}>
                      <Text style={s.actionStepNum}>{i + 1}.</Text>
                      <Text style={s.actionStepText}>{step}</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* Blocking Reasons — hidden for needs_insurance (CTA
                  card above covers it) and for manual_renewal_dob_now
                  (MR.1 panel above already explains the reason). */}
              {renewal.status !== 'needs_insurance' &&
               renewal.action?.kind !== 'manual_renewal_dob_now' &&
               renewal.blocking_reasons?.length > 0 && (
                <View style={s.blockingBlock}>
                  <AlertTriangle size={14} color="#f59e0b" />
                  {renewal.blocking_reasons.map((reason, i) => (
                    <Text key={i} style={s.blockingText}>
                      {reason}
                    </Text>
                  ))}
                </View>
              )}

              {/* BIS Legacy Banner */}
              {(renewalData?.renewal_path === 'bis_legacy' || renewal.renewal_path === 'bis_legacy') && (
                <GlassCard style={{ backgroundColor: '#f59e0b15', borderColor: '#f59e0b40', borderWidth: 1, marginBottom: 12, padding: 14 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
                    <AlertTriangle size={18} color="#f59e0b" style={{ marginTop: 2 }} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontFamily: typography.semibold, fontSize: 14, color: '#f59e0b', marginBottom: 4 }}>
                        BIS Legacy Permit
                      </Text>
                      <Text style={{ fontFamily: typography.regular, fontSize: 13, color: colors.text.secondary, lineHeight: 18 }}>
                        This permit was filed through the legacy BIS system. Automated renewal is not available. Contact your expediter to file a Post Approval Amendment (PAA) or re-file through DOB NOW.
                      </Text>
                      <Pressable
                        onPress={() => Linking.openURL('https://a810-dobnow.nyc.gov/publish/')}
                        style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 }}
                      >
                        <ExternalLink size={14} color="#3b82f6" />
                        <Text style={{ fontFamily: typography.medium, fontSize: 13, color: '#3b82f6' }}>
                          Open DOB NOW
                        </Text>
                      </Pressable>
                    </View>
                  </View>
                </GlassCard>
              )}

              {/* Copyable Fields */}
              {renewalData?.copyable_fields?.map((field, i) => (
                <Pressable key={i} onPress={async () => {
                  await Clipboard.setStringAsync(field.value);
                  toast.success('Copied', `${field.label} copied to clipboard`);
                }}>
                  <GlassCard style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 14, marginBottom: 8 }}>
                    <View>
                      <Text style={{ fontSize: 11, color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>{field.label}</Text>
                      <Text style={{ fontSize: 15, color: colors.text.primary, marginTop: 2 }}>{field.value || '\u2014'}</Text>
                    </View>
                    <Copy size={16} color={colors.text.muted} />
                  </GlassCard>
                </Pressable>
              ))}

              {/* Action Buttons */}
              <View style={s.actionsRow}>
                {canPrepare && !(renewalData?.renewal_path === 'bis_legacy' || renewal.renewal_path === 'bis_legacy') && (
                  <GlassButton
                    title={
                      preparing === renewal.id
                        ? 'Preparing...'
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

                {canOpenDob && !(renewalData?.renewal_path === 'bis_legacy' || renewal.renewal_path === 'bis_legacy') && (
                  <GlassButton
                    title="Renew on DOB NOW"
                    icon={
                      <ExternalLink
                        size={16}
                        color="#8b5cf6"
                      />
                    }
                    onPress={() => {
                      const jobNum = renewal.job_number || '';
                      const url = renewalData?.dob_now_url || (jobNum
                        ? `https://a810-dobnow.nyc.gov/publish/#!/service-worker-dashboard`
                        : 'https://a810-dobnow.nyc.gov/publish/');
                      Linking.openURL(url);
                    }}
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
                  LeveLog prepares the draft — you just sign
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
    expiryCalendarCaption: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      marginTop: 2,
    },
    strategyBadge: {
      alignSelf: 'flex-start',
      marginTop: 6,
      paddingHorizontal: spacing.sm,
      paddingVertical: 3,
      borderRadius: borderRadius.sm,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    strategyText: {
      fontFamily: typography.medium,
      fontSize: 11,
      letterSpacing: 0.3,
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
    actionBlock: {
      backgroundColor: '#3b82f610',
      borderRadius: borderRadius.lg,
      padding: spacing.md,
      marginBottom: spacing.md,
      borderWidth: 1,
      borderColor: '#3b82f630',
    },
    actionTitle: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#3b82f6',
      marginBottom: spacing.sm,
      letterSpacing: 0.3,
    },
    actionStepRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginBottom: 4,
    },
    actionStepNum: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#3b82f6',
      minWidth: 18,
    },
    actionStepText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 18,
      flex: 1,
    },
    // ── MR.1 manual renewal panel ────────────────────────────────
    manualRenewalPanel: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      padding: spacing.lg,
      marginBottom: spacing.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    manualRenewalHeader: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
      marginBottom: spacing.sm,
    },
    manualRenewalExplanation: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
      marginBottom: spacing.md,
    },
    manualRenewalFeeBlock: {
      flexDirection: 'row',
      alignItems: 'baseline',
      gap: spacing.sm,
      marginBottom: spacing.md,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    manualRenewalFee: {
      fontFamily: typography.semibold,
      fontSize: 22,
      color: colors.text.primary,
    },
    manualRenewalFeeCaption: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    manualRenewalDetails: {
      marginBottom: spacing.md,
      gap: 4,
    },
    manualRenewalDetailRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      paddingVertical: 4,
    },
    manualRenewalDetailLabel: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    manualRenewalDetailValue: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },
    manualRenewalCta: {
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      alignItems: 'center',
      marginTop: spacing.xs,
    },
    manualRenewalCtaDisabled: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      opacity: 0.6,
    },
    manualRenewalCtaText: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    manualRenewalCtaCaption: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      textAlign: 'center',
      marginTop: 6,
      marginBottom: spacing.sm,
    },
    manualRenewalCitation: {
      fontFamily: typography.regular,
      fontSize: 11,
      fontStyle: 'italic',
      color: colors.text.muted,
      marginTop: spacing.sm,
      paddingTop: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
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
