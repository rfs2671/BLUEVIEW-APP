import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Platform,
  Linking,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Shield,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  Settings,
  ChevronDown,
  ChevronUp,
  X,
  Building2,
  Gavel,
  MessageSquare,
  ExternalLink,
  FileCheck,
  ShieldAlert,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import FloatingNav from '../../../src/components/FloatingNav';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import apiClient, { dobAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { semantic, chrome, border, surface, text, withAlpha } from '../../../src/styles/semanticColors';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import InfoTooltip from '../../../src/components/InfoTooltip';
// daysUntil moved to a shared util so workers/[id].jsx can use the SAME
// definition and threshold for credential expiry (it previously had none).
import { daysUntil } from '../../../src/utils/expiry';
import { isValidBin } from '../../../src/utils/bin';

// Severity: Action (red) vs Good (green)
const getSevConfig = (severity) => {
  if (severity === 'Action' || severity === 'Critical' || severity === 'Medium')
    return { color: semantic.critical, label: 'Action Needed' };
  return { color: semantic.verified, label: 'Good' };
};

const parseAnyDate = (dateStr) => {
  if (!dateStr) return null;
  // Handle YYYYMMDD format (no separators)
  if (typeof dateStr === 'string' && dateStr.length === 8 && /^\d{8}$/.test(dateStr)) {
    return new Date(`${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}T00:00:00Z`);
  }
  const d = new Date(dateStr);
  return isNaN(d.getTime()) ? null : d;
};

const formatDate = (dateStr) => {
  if (!dateStr) return '\u2014';
  const d = parseAnyDate(dateStr);
  if (!d) return String(dateStr).slice(0, 10);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};


export default function DOBLogsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [nycBin, setNycBin] = useState('');
  const [trackDobStatus, setTrackDobStatus] = useState(false);
  const [allLogs, setAllLogs] = useState([]);
  // Standing OPEN exposure from GET /projects/dob-summary (status-based, no
  // detected_at window) — drives the tile numbers so they don't decay.
  const [summary, setSummary] = useState(null);
  const [activeTab, setActiveTab] = useState('all');
  const [expandedLogId, setExpandedLogId] = useState(null);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configBin, setConfigBin] = useState('');
  const [configTracking, setConfigTracking] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [preparingId, setPreparingId] = useState(null);
  const [renewalResult, setRenewalResult] = useState(null); // result from prepare call

  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const timer = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) fetchLogs();
  }, [isAuthenticated, projectId]);

  const fetchLogs = async () => {
    if (!loading) setRefreshing(true);
    try {
      // date_range:'all' — the record LIST must not decay on detected_at either
      // (default '30d' empties the list ~30 days after the sync stamp). Tile
      // numbers come from dob-summary; both are fetched together.
      const [data, summaryData] = await Promise.all([
        dobAPI.getLogs(projectId, { limit: 200, date_range: 'all' }),
        dobAPI.getSummary(projectId).catch(() => null),
      ]);
      setProjectName(data.project_name || '');
      setNycBin(data.nyc_bin || '');
      setTrackDobStatus(data.track_dob_status || false);
      setAllLogs(data.logs || []);
      setSummary(summaryData?.by_project?.[projectId] || null);
    } catch (error) {
      console.error('Failed to fetch DOB logs:', error);
      toast.error('Error', 'Could not load DOB compliance data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const result = await dobAPI.syncNow(projectId);
      toast.success('Sync Complete', result.new_records > 0 ? `${result.new_records} new record(s) found.` : 'No new records found.');
      await fetchLogs();
    } catch (error) {
      const detail = error.response?.data?.detail || 'Sync failed';
      error.response?.status === 429 ? toast.warning('Rate Limited', detail) : toast.error('Sync Error', detail);
    } finally { setSyncing(false); }
  };

  const openConfigModal = () => { setConfigBin(nycBin || ''); setConfigTracking(trackDobStatus); setShowConfigModal(true); };
  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const config = {};
      config.nyc_bin = configBin;
      config.track_dob_status = configTracking;
      const result = await dobAPI.updateConfig(projectId, config);
      setNycBin(result.nyc_bin || '');
      setTrackDobStatus(result.track_dob_status || false);
      setShowConfigModal(false);
      toast.success('Saved', 'DOB configuration updated. Syncing records...');
      // Always re-fetch after config save — backend triggers auto-sync on BIN change
      await fetchLogs();
      // Poll once more after 8s to catch the background sync results
      setTimeout(async () => {
        try { await fetchLogs(); } catch (_) {}
      }, 8000);
    } catch (error) {
      toast.error('Error', error.response?.data?.detail || 'Could not save config');
    } finally { setSavingConfig(false); }
  };
  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  // Tile numbers = standing OPEN exposure from GET /projects/dob-summary
  // (status-based, deduped by raw_dob_id, NO detected_at window — so they do
  // not decay as the sync stamp ages). 0 until the summary loads. dob-summary
  // returns no inspections (ingest removed) and no active-permit / closed-
  // complaint counts, so the Permits tile shows permits_expiring and the
  // Inspections tile is dropped.
  const openViolations = summary?.open_violations ?? 0;
  const openComplaints = summary?.open_complaints ?? 0;
  const permitsExpiring = summary?.permits_expiring ?? 0;
  // Denominators for the "X of Y" tiles. total_permits = ACTIVE permits
  // (unexpired, REVOKED excluded); permits_no_expiry = permits with no expiry
  // date, excluded from the active denominator and disclosed below the tiles.
  const totalViolations = summary?.total_violations ?? 0;
  const totalComplaints = summary?.total_complaints ?? 0;
  const activePermits = summary?.total_permits ?? 0;
  const permitsNoExpiry = summary?.permits_no_expiry ?? 0;
  // Always "{open} of {total}" — the VERIFY acceptance shows "2 of 2" even when
  // equal, so the count always states the subset relationship explicitly.
  const ofText = (open, total) => `${open} of ${total}`;

  // Open/active status per record — drives the card badge and open-first sort,
  // mirroring dob-summary's open definitions.
  const isRecordOpen = (log) => {
    if (log.record_type === 'violation' || log.record_type === 'swo') {
      return !['certified', 'dismissed', 'paid', 'resolved'].includes(log.resolution_state);
    }
    if (log.record_type === 'complaint') {
      return !(log.closed_date || (log.complaint_status || '').toLowerCase().includes('closed'));
    }
    if (log.record_type === 'permit') {
      const d = parseAnyDate(log.expiration_date);
      const t0 = new Date(); t0.setHours(0, 0, 0, 0);
      return !!d && d.getTime() >= t0.getTime();
    }
    return true;
  };

  // Status pill: Open/Active (warm accent) vs Closed/Expired (neutral). Permits
  // with no expiry date get no pill (status unknown; disclosed at the tiles).
  const statusBadge = (log) => {
    if (log.record_type === 'permit') {
      if (!log.expiration_date) return null;
      return isRecordOpen(log)
        ? { label: 'Active', color: semantic.verified }
        : { label: 'Expired', color: colors.text.muted };
    }
    if (isRecordOpen(log)) {
      return { label: 'Open', color: log.record_type === 'complaint' ? semantic.attention : semantic.critical };
    }
    return { label: 'Closed', color: colors.text.muted };
  };
  const renderStatusPill = (log) => {
    const b = statusBadge(log);
    if (!b) return null;
    return (
      <View style={[s.statusPill, { borderColor: withAlpha(b.color, 0.3), backgroundColor: withAlpha(b.color, 0.12) }]}>
        <Text style={[s.statusPillText, { color: b.color }]}>{b.label}</Text>
      </View>
    );
  };

  // Get the real date for a record (actual issue/complaint/filing date, not sync date)
  const getRealDate = (log) => {
    if (log.record_type === 'violation' || log.record_type === 'swo') return log.violation_date || log.detected_at;
    if (log.record_type === 'complaint') return log.complaint_date || log.detected_at;
    if (log.record_type === 'permit') return log.expiration_date || log.issuance_date || log.filing_date || log.detected_at;
    if (log.record_type === 'inspection') return log.inspection_date || log.detected_at;
    return log.detected_at;
  };

  // OPEN records first, then newest real date — so a tile's open subset leads
  // the list while closed/resolved records stay visible below.
  const openFirstSort = (logs) => [...logs].sort((a, b) => {
    const oa = isRecordOpen(a) ? 0 : 1;
    const ob = isRecordOpen(b) ? 0 : 1;
    if (oa !== ob) return oa - ob;
    const da = parseAnyDate(getRealDate(a)) || new Date(0);
    const db = parseAnyDate(getRealDate(b)) || new Date(0);
    return db - da;
  });

  // Filtered logs for display. Inspections are excluded everywhere: their
  // ingest was removed (rodent-data mislabel) and dob-summary doesn't count
  // them, so there's no tile/tab — don't leave orphan inspection cards in "all".
  const filteredLogs = openFirstSort(
    activeTab === 'all' ? allLogs.filter(l => l.record_type !== 'inspection')
    : activeTab === 'violation' ? allLogs.filter(l => l.record_type === 'violation' || l.record_type === 'swo')
    : allLogs.filter(l => l.record_type === activeTab)
  );

  // Permits needing renewal: expiring within 30 days OR expired within 60 days
  const renewablePermits = allLogs.filter(l => {
    if (l.record_type !== 'permit') return false;
    if (l.expiration_date) {
      const days = daysUntil(l.expiration_date);
      if (days !== null) return days <= 30 && days >= -60;
    }
    const status = (l.permit_status || '').toLowerCase();
    return status.includes('expired');
  });
  const expiringPermits = renewablePermits.filter(l => {
    const days = daysUntil(l.expiration_date);
    return days !== null && days >= 0;
  });
  const expiredPermits = renewablePermits.filter(l => {
    const days = daysUntil(l.expiration_date);
    return days !== null && days < 0;
  });

  const handlePrepareRenewal = async (log) => {
    setPreparingId(log.id);
    try {
      // MR.1 fix: pre-flight eligibility before /prepare so manual-
      // renewal cases route to the detail page (where the MR.1 panel
      // lives) instead of issuing a guaranteed-400 /prepare call. The
      // 400 path was producing inline error toasts that operators
      // perceived as a dead end.
      //
      // Trade-off: this adds one round-trip per click for eligible
      // permits (check-eligibility + prepare = 2 calls instead of 1).
      // /check-eligibility is the dispatcher's pure eligibility
      // computation; /prepare also runs eligibility internally as
      // its first step (permit_renewal.py:~1366), so we're running
      // the dispatcher twice for the same permit on the eligible
      // path. Acceptable cost for the UX correctness gain. When
      // MR.6 wires the detail-page filing flow, this button can be
      // simplified to always route to the detail page.
      const eligibilityResp = await apiClient.post(
        '/api/permit-renewals/check-eligibility',
        { permit_dob_log_id: log.id, project_id: projectId }
      );
      const actionKind = eligibilityResp.data?.action?.kind;
      if (actionKind === 'manual_renewal_dob_now') {
        // Manual 1-year-ceiling case: route to the renewal detail
        // page where MR.1's Manual Renewal Required panel renders.
        // No /prepare call — that endpoint will 400 for this case.
        // Other manual kinds (manual_renewal_lapsed, shed_renewal)
        // are intentionally NOT routed here per MR.1 scope; they
        // continue to fall through to /prepare and produce the
        // existing error toast until their own panels ship.
        //
        // Pass the dob_log id as a query param so the list page can
        // auto-expand the specific permit's card on landing. Without
        // this the operator lands on a list of all renewals for the
        // project and has to find their specific permit by hand —
        // worse when one S1 filing has multiple work-permit children
        // (e.g. B00736930-S1-PL plumbing + B00736930-S1-SP sprinkler
        // + B00736930-S1 general). The list page reads permitId from
        // useLocalSearchParams and matches against
        // renewal.permit_dob_log_id.
        router.push(
          `/project/${projectId}/permit-renewal?permitId=${encodeURIComponent(log.id)}`
        );
        return;
      }

      const resp = await apiClient.post('/api/permit-renewals/prepare', {
        permit_dob_log_id: log.id,
        project_id: projectId,
      });
      setRenewalResult(resp.data);
      toast.success('Renewal Prepared', 'Review details below — complete on DOB NOW.');
    } catch (error) {
      const detail = error.response?.data?.detail;
      if (typeof detail === 'object' && detail.blocking_reasons) {
        toast.error('Not Eligible', detail.blocking_reasons.join('\n'));
      } else {
        toast.error('Error', typeof detail === 'string' ? detail : 'Could not prepare renewal');
      }
    } finally {
      setPreparingId(null);
    }
  };

  // ── Card renderers ──
  const renderPermitCard = (log) => {
    const isExpanded = expandedLogId === log.id;
    const sevConfig = getSevConfig(log.severity);
    const days = daysUntil(log.expiration_date);
    const isExpired = days !== null && days < 0;
    const isExpiring = days !== null && days >= 0 && days <= 30;
    const needsRenewal = isExpired || isExpiring;
    const isPreparing = preparingId === log.id;
    const jobNum = log.job_number || '';
    // Determine if this is a BIS legacy permit (numeric job number)
    const jobClean = jobNum.replace(/-/g, '').trim();
    const isBisLegacy = jobClean && /^\d+$/.test(jobClean);

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={s.logCard}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: sevConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: semantic.verifiedBorder }]}>
                <Text style={[s.typeText, { color: semantic.verified }]}>Permit</Text>
              </View>
              {renderStatusPill(log)}
            </View>
            <View style={s.logHeaderRight}>
              {needsRenewal && (
                <Pressable
                  onPress={(e) => {
                    e.stopPropagation();
                    if (isBisLegacy) {
                      Linking.openURL('https://a810-dobnow.nyc.gov/publish/');
                    } else {
                      handlePrepareRenewal(log);
                    }
                  }}
                  disabled={isPreparing}
                  style={[s.renewBubble, isExpired && s.renewBubbleUrgent]}
                >
                  {isPreparing ? (
                    <ActivityIndicator size={12} color="#fff" />
                  ) : (
                    <FileCheck size={12} strokeWidth={2} color="#fff" />
                  )}
                  <Text style={s.renewBubbleText}>
                    {isPreparing ? 'Preparing...' : 'Renew'}
                  </Text>
                </Pressable>
              )}
              {(log.issuance_date || log.filing_date || log.detected_at) && <Text style={s.dateText}>{formatDate(log.issuance_date || log.filing_date || log.detected_at)}</Text>}
              {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
            </View>
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2} ellipsizeMode="tail">{log.ai_summary}</Text>
          {(isExpired || isExpiring) && (
            <View style={[s.expirationBanner, isExpired ? s.expiredBanner : s.expiringBanner]}>
              <AlertTriangle size={14} color={isExpired ? semantic.critical : semantic.attention} />
              <Text style={[s.expirationText, { color: isExpired ? semantic.criticalText : semantic.attention }]}>
                {isExpired ? `EXPIRED ${Math.abs(days)} days ago` : `Expires in ${days} day${days !== 1 ? 's' : ''}`}
              </Text>
            </View>
          )}
          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              {log.job_number && <DetailRow label="Job #" value={log.job_number} colors={colors} />}
              {log.permit_type && <DetailRow label="Type" value={log.permit_type} colors={colors} />}
              {log.work_type && <DetailRow label="Work" value={log.work_type} colors={colors} />}
              {log.permit_status && <DetailRow label="Status" value={log.permit_status} colors={colors} />}
              {log.issuance_date && <DetailRow label="Issued" value={formatDate(log.issuance_date)} colors={colors} />}
              {log.expiration_date && <DetailRow label="Expires" value={formatDate(log.expiration_date)} colors={colors} />}
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>ACTION</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {isBisLegacy && needsRenewal && (
                <View style={s.bisLegacyBanner}>
                  <AlertTriangle size={14} color={semantic.attention} />
                  <Text style={s.bisLegacyText}>
                    BIS Legacy Permit — automated renewal unavailable. Contact your expediter for a PAA or re-file on DOB NOW.
                  </Text>
                </View>
              )}
              {needsRenewal && !isBisLegacy && (
                <GlassButton
                  title={isPreparing ? 'Preparing...' : 'Prepare Renewal'}
                  icon={isPreparing ? <ActivityIndicator size={14} color={semantic.verified} /> : <FileCheck size={16} strokeWidth={1.5} color={semantic.verified} />}
                  onPress={() => handlePrepareRenewal(log)}
                  disabled={isPreparing}
                  style={[s.dobLinkBtn, { borderColor: semantic.verifiedBorder }]}
                />
              )}
              {needsRenewal && (
                // MR.14 4c: This dob-logs view doesn't carry the
                // renewal record needed to drive the Start Renewal
                // panel (that lives on the permit-renewal page).
                // We render a disabled placeholder here so the row
                // looks coherent and users navigate to the renewal
                // page for the actual Start Renewal flow.
                <GlassButton
                  title="Automated filing — coming soon"
                  icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.muted} />}
                  onPress={() => {}}
                  disabled
                  style={[s.dobLinkBtn, { borderColor: colors.glass.border, opacity: 0.6 }]}
                />
              )}
              {log.dob_link && log.dob_link.trim().length > 0 && (
                <GlassButton title={log.dob_link.includes('dobnow') ? 'View on DOB NOW' : 'View on DOB BIS'} icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderViolationCard = (log) => {
    const isExpanded = expandedLogId === log.id;
    const sevConfig = getSevConfig(log.severity);
    const subtypeLabels = {
      SWO_FULL: 'STOP WORK ORDER',
      SWO_PARTIAL: 'PARTIAL SWO',
      VACATE_FULL: 'VACATE ORDER',
      VACATE_PARTIAL: 'PARTIAL VACATE',
      COMM_ORDER: "COMMISSIONER'S ORDER",
      ECB: 'ECB VIOLATION',
      NOV: 'VIOLATION',
    };
    const subtypeColors = {
      SWO_FULL: semantic.critical, SWO_PARTIAL: semantic.critical,
      VACATE_FULL: semantic.critical, VACATE_PARTIAL: semantic.critical,
      COMM_ORDER: semantic.critical,
      ECB: '#f97316',
      NOV: semantic.critical,
    };
    const subtype = log.violation_subtype || 'NOV';
    const headerLabel = subtypeLabels[subtype] || 'VIOLATION';
    const headerColor = subtypeColors[subtype] || semantic.critical;
    const isSWO = subtype.startsWith('SWO') || subtype.startsWith('VACATE');
    const displayDate = log.violation_date || log.detected_at;

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={[s.logCard, isSWO && s.swoCard]}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: sevConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: headerColor + '40' }]}>
                <Text style={[s.typeText, { color: semantic.criticalText }]}>{headerLabel}</Text>
              </View>
              {renderStatusPill(log)}
            </View>
            <View style={s.logHeaderRight}>
              {displayDate && <Text style={s.dateText}>{formatDate(displayDate)}</Text>}
              {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
            </View>
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2} ellipsizeMode="tail">{log.ai_summary}</Text>
          {log.penalty_amount && subtype === 'ECB' && (
            <View style={{ backgroundColor: semantic.criticalBg, borderRadius: 8, padding: 10, marginTop: 8, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Text style={{ fontSize: 18, fontWeight: '700', color: '#f97316' }}>${log.penalty_amount}</Text>
              <Text style={{ fontSize: 12, color: '#f97316', opacity: 0.8 }}>Penalty Amount</Text>
            </View>
          )}
          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              {log.notice_type && (
                <View style={[s.typeBadge, { borderColor: semantic.attentionBorder, marginTop: 4, alignSelf: 'flex-start' }]}>
                  <Text style={[s.typeText, { color: semantic.attention }]}>
                    {{'commissioners_order': "COMMISSIONER'S ORDER", 'padlock_order': 'PADLOCK ORDER', 'emergency_declaration': 'EMERGENCY DECLARATION', 'notice_of_deficiency': 'NOTICE OF DEFICIENCY', 'letter_of_deficiency': 'LETTER OF DEFICIENCY'}[log.notice_type] || log.notice_type}
                  </Text>
                </View>
              )}
              {log.compliance_deadline && (() => {
                const deadlineDays = daysUntil(log.compliance_deadline);
                if (deadlineDays === null) return null;
                const isOverdue = deadlineDays < 0;
                return (
                  <View style={[s.expirationBanner, { backgroundColor: isOverdue ? semantic.criticalBg : semantic.attentionBg }]}>
                    <AlertTriangle size={14} color={isOverdue ? semantic.critical : semantic.attention} />
                    <Text style={[s.expirationText, { color: isOverdue ? semantic.criticalText : semantic.attention, fontWeight: '600' }]}>
                      {isOverdue ? `OVERDUE by ${Math.abs(deadlineDays)} days` : `${deadlineDays} days to comply`}
                    </Text>
                  </View>
                );
              })()}
              {log.violation_number && <DetailRow label="Violation #" value={log.violation_number} colors={colors} />}
              {log.violation_date && <DetailRow label="Issue Date" value={formatDate(log.violation_date)} colors={colors} />}
              {log.violation_type && <DetailRow label="Type" value={log.violation_type} colors={colors} />}
              {log.violation_category && <DetailRow label="Category" value={log.violation_category} colors={colors} />}
              {log.description && <DetailRow label="Description" value={log.description} colors={colors} />}
              {log.penalty_amount && <DetailRow label="Penalty" value={`$${log.penalty_amount}`} colors={colors} />}
              {log.respondent && <DetailRow label="Respondent" value={log.respondent} colors={colors} />}
              {log.disposition_date && <DetailRow label="Disposition" value={formatDate(log.disposition_date)} colors={colors} />}
              {log.status && <DetailRow label="Status" value={log.status} colors={colors} />}
              {log.resolution_state && (
                <View style={{ marginTop: 8 }}>
                  <Text style={{ fontSize: 11, color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>RESOLUTION STATUS</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: ['certified','dismissed','paid','resolved'].includes(log.resolution_state) ? semantic.verified : ['hearing_scheduled','cure_pending'].includes(log.resolution_state) ? semantic.attention : semantic.critical }} />
                    <Text style={{ fontSize: 13, color: colors.text.primary, fontWeight: '600' }}>
                      {{'open':'Open — Unresolved','cure_pending':'Cure Submitted — Awaiting Certification','hearing_scheduled':'ECB Hearing Scheduled','hearing_past':'Hearing Occurred — Awaiting Result','certified':'Certified — Resolved','dismissed':'Dismissed','paid':'Penalty Paid','resolved':'Resolved'}[log.resolution_state] || log.resolution_state}
                    </Text>
                  </View>
                </View>
              )}
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>ACTION</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {log.dob_link && log.dob_link.trim().length > 0 && (
                <GlassButton title={log.dob_link.includes('dobnow') ? 'View on DOB NOW' : 'View on DOB BIS'} icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderComplaintCard = (log) => {
    const isExpanded = expandedLogId === log.id;

    // Risk level color mapping
    const riskColors = {
      CRITICAL: semantic.critical,
      HIGH: '#f97316',
      MEDIUM: semantic.attention,
      LOW: semantic.verified,
      RESOLVED: '#6b7280',
      PENDING: '#3b82f6',
    };
    const riskColor = riskColors[(log.risk_level || '').toUpperCase()] || '#3b82f6';
    const riskTextColor = (log.risk_level || '').toUpperCase() === 'CRITICAL' ? semantic.criticalText : riskColor;

    const complaintSource = log.complaint_source || '311 Complaint';
    const isResolved = !!log.closed_date || (log.complaint_status || '').toUpperCase().includes('CLOSE');
    const hasLinkedViolation = !!log.linked_violation_id;

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={s.logCard}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: riskColor }]} />
              <View style={[s.typeBadge, { borderColor: semantic.attentionBorder }]}>
                <Text style={[s.typeText, { color: semantic.attention }]}>{complaintSource}</Text>
              </View>
              {renderStatusPill(log)}
            </View>
            <View style={s.logHeaderRight}>
              {log.complaint_date && <Text style={s.dateText}>{formatDate(log.complaint_date)}</Text>}
              {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
            </View>
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2} ellipsizeMode="tail">{log.ai_summary}</Text>

          {/* Disposition badges */}
          {isResolved && (
            <View style={[s.expirationBanner, { backgroundColor: semantic.verifiedBg }]}>
              <CheckCircle size={14} color={semantic.verified} />
              <Text style={[s.expirationText, { color: semantic.verified, fontWeight: '500' }]}>Resolved</Text>
            </View>
          )}
          {hasLinkedViolation && (
            <View style={[s.expirationBanner, { backgroundColor: semantic.criticalBg }]}>
              <AlertTriangle size={14} color={semantic.critical} />
              <Text style={[s.expirationText, { color: semantic.criticalText, fontWeight: '600' }]}>Violation Issued</Text>
            </View>
          )}

          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />

              {/* What Happened */}
              {log.category_label && (
                <View style={s.nextActionBox}>
                  <Text style={s.nextActionLabel}>WHAT HAPPENED</Text>
                  <Text style={s.nextActionText}>{log.category_label}</Text>
                </View>
              )}

              {/* Current Status */}
              {log.disposition_label && (
                <View style={s.nextActionBox}>
                  <Text style={s.nextActionLabel}>CURRENT STATUS</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    <Text style={[s.nextActionText, { flex: 1 }]}>{log.disposition_label}</Text>
                    <View style={{ paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, backgroundColor: riskColor + '20' }}>
                      <Text style={{ fontSize: 10, fontWeight: '600', color: riskTextColor }}>{log.risk_level || 'PENDING'}</Text>
                    </View>
                  </View>
                </View>
              )}

              {/* What To Expect */}
              {log.what_to_expect && (
                <View style={s.nextActionBox}>
                  <Text style={s.nextActionLabel}>WHAT TO EXPECT</Text>
                  <Text style={s.nextActionText}>{log.what_to_expect}</Text>
                </View>
              )}

              {/* What To Do Now */}
              {log.next_action && (
                <View style={s.nextActionBox}>
                  <Text style={s.nextActionLabel}>WHAT TO DO NOW</Text>
                  <Text style={s.nextActionText}>{log.next_action}</Text>
                </View>
              )}

              {/* Inspector unit */}
              {log.inspector_unit && <DetailRow label="Inspector Unit" value={log.inspector_unit} colors={colors} />}

              {/* Assigned DOB unit — eabe-havv `unit` (e.g. "OBM"). A unit
                  code, not a named inspector. Hidden when absent (311 records,
                  or DOB complaints not yet re-polled after this change). */}
              {log.complaint_unit && <DetailRow label="ASSIGNED TO" value={log.complaint_unit} colors={colors} />}

              {/* Linked violation card */}
              {hasLinkedViolation && (
                <Pressable onPress={() => {
                  setActiveTab('violation');
                  const linked = allLogs.find(l => l.id === log.linked_violation_id || l.raw_dob_id === log.linked_violation_id);
                  if (linked) setExpandedLogId(linked.id);
                }}>
                  <View style={[s.nextActionBox, { backgroundColor: semantic.criticalBg }]}>
                    <Text style={[s.nextActionLabel, { color: semantic.criticalText }]}>VIOLATION ISSUED</Text>
                    <Text style={[s.nextActionText, { color: semantic.criticalText }]}>Violation issued from this complaint — tap to view</Text>
                  </View>
                </Pressable>
              )}

              {/* DOB link — only the working BIS complaint page. 311 records
                  carry a dead portal.311 link (NYC 311 exposes no public per-SR
                  URL), so render no button for them rather than a dead one. */}
              {log.dob_link && log.dob_link.includes('bisweb.nyc.gov') && (
                <GlassButton title="View on DOB BIS" icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderInspectionCard = (log) => {
    const isExpanded = expandedLogId === log.id;
    const result = (log.inspection_result || '').toUpperCase();
    const resultConfig = result.includes('FAIL')
      ? { color: semantic.critical, textColor: semantic.criticalText, label: 'Failed', bg: 'rgba(239,68,68,0.1)' }
      : result.includes('PARTIAL')
      ? { color: semantic.attention, label: 'Partial', bg: semantic.attentionBg }
      : { color: semantic.verified, label: 'Passed', bg: 'rgba(34,197,94,0.1)' };

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={s.logCard}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: resultConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: '#3b82f640' }]}>
                <Text style={[s.typeText, { color: '#3b82f6' }]}>Inspection</Text>
              </View>
              <View style={[s.typeBadge, { borderColor: resultConfig.color + '40', backgroundColor: resultConfig.bg }]}>
                <Text style={[s.typeText, { color: resultConfig.textColor || resultConfig.color }]}>{resultConfig.label}</Text>
              </View>
            </View>
            <View style={s.logHeaderRight}>
              <Text style={s.dateText}>{formatDate(log.inspection_date || log.detected_at)}</Text>
              {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
            </View>
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2} ellipsizeMode="tail">{log.ai_summary}</Text>
          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              {log.inspection_type && <DetailRow label="Type" value={log.inspection_type} colors={colors} />}
              {log.inspection_result && <DetailRow label="Result" value={log.inspection_result} colors={colors} />}
              {log.inspection_result_description && <DetailRow label="Details" value={log.inspection_result_description} colors={colors} />}
              {log.linked_job_number && <DetailRow label="Job #" value={log.linked_job_number} colors={colors} />}
              {log.inspection_date && <DetailRow label="Date" value={formatDate(log.inspection_date)} colors={colors} />}
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>ACTION</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {log.dob_link && log.dob_link.trim().length > 0 && (
                <GlassButton title="View on DOB BIS" icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderGenericCard = (log) => {
    const isExpanded = expandedLogId === log.id;
    const sevConfig = getSevConfig(log.severity);
    const typeLabel = log.record_type === 'job_status' ? 'Job Filing' : log.record_type;
    const typeColor = '#3b82f6';

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={s.logCard}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: sevConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: typeColor + '40' }]}>
                <Text style={[s.typeText, { color: typeColor }]}>{typeLabel}</Text>
              </View>
            </View>
            <View style={s.logHeaderRight}>
              {log.detected_at && <Text style={s.dateText}>{formatDate(log.detected_at)}</Text>}
              {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
            </View>
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2} ellipsizeMode="tail">{log.ai_summary}</Text>

          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              {log.status && <DetailRow label="Status" value={log.status} colors={colors} />}
              {log.description && <DetailRow label="Description" value={log.description} colors={colors} />}
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>STATUS</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {log.dob_link && (
                <GlassButton title={log.dob_link.includes('dobnow') ? 'View on DOB NOW' : 'View on DOB BIS'} icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
              <Text style={s.detectedText}>ID: {log.raw_dob_id}</Text>
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderLogCard = (log) => {
    if (log.record_type === 'permit') return renderPermitCard(log);
    if (log.record_type === 'violation' || log.record_type === 'swo') return renderViolationCard(log);
    if (log.record_type === 'complaint') return renderComplaintCard(log);
    if (log.record_type === 'inspection') return renderInspectionCard(log);
    return renderGenericCard(log);
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading compliance data...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton variant="icon" icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => router.back()} />
            <HeaderBrand />
          </View>
          <View style={s.headerRight}>
            {isAdmin && <GlassButton variant="icon" icon={<Settings size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={openConfigModal} />}
          </View>
        </View>

        {/* FlatList owns the scroll (virtualizes the DOB log rows). The
            title, nav cards, banners and Sync button move into
            ListHeaderComponent so they stay accessible while the list scrolls;
            the empty states become ListEmptyComponent. Row spacing that was
            logsList's `gap` is preserved via ItemSeparatorComponent. */}
        <FlatList
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={fetchLogs} tintColor={colors.text.muted} />}
          data={loading ? [] : filteredLogs}
          keyExtractor={(item) => String(item.id)}
          renderItem={({ item }) => renderLogCard(item)}
          ItemSeparatorComponent={() => <View style={{ height: spacing.md }} />}
          ListHeaderComponent={
            <>
          {/* Title. The refresh control lives up here as a quiet icon-button:
              DOB data syncs automatically, so a full-width primary button was
              overstating a fallback action. Sync is unchanged underneath. */}
          <View style={s.titleSection}>
            <View style={s.titleTopRow}>
              <Text style={s.titleLabel}>DOB COMPLIANCE</Text>
              <Pressable
                onPress={handleSync}
                disabled={syncing}
                hitSlop={10}
                accessibilityRole="button"
                accessibilityLabel={syncing ? 'Syncing with NYC DOB' : 'Sync now'}
                style={({ hovered }) => [s.syncChip, hovered && s.syncChipHover, syncing && s.syncChipDisabled]}
              >
                <RefreshCw size={13} strokeWidth={1.5} color={semantic.neutral} />
                <Text style={s.syncChipText}>{syncing ? 'Syncing…' : 'Synced automatically'}</Text>
              </Pressable>
            </View>
            <Text style={s.titleText}>{projectName}</Text>
            {isValidBin(nycBin) ? (
              <View style={s.binBadge}>
                <Building2 size={13} strokeWidth={1.5} color={semantic.neutral} />
                <Text style={s.binText}>BIN: {nycBin}</Text>
              </View>
            ) : (
              <Pressable onPress={isAdmin ? openConfigModal : undefined}>
                <View style={s.noBinBadge}>
                  <AlertTriangle size={13} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={s.noBinText}>No BIN — {isAdmin ? 'tap to configure' : 'address-based lookup active'}</Text>
                </View>
              </Pressable>
            )}
          </View>

          {/* ── 3 Glass Nav Cards — horizontal scroll on narrow viewports.
                Each shows "{open} of {total}" (open subset of the deduped total)
                so the count matches the list once you drill in. ── */}
          <View style={s.navRow}>
            <Pressable style={s.navCardWrap} onPress={() => { setActiveTab(activeTab === 'permit' ? 'all' : 'permit'); setExpandedLogId(null); }}>
              <GlassCard style={[s.navCard, activeTab === 'permit' && s.navCardActive]}>
                <FileCheck size={22} strokeWidth={1.5} color={activeTab === 'permit' ? chrome.brand : colors.text.muted} />
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navCount, activeTab === 'permit' && s.navCountActive]}>{ofText(permitsExpiring, activePermits)}</Text>
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navLabel, activeTab === 'permit' && s.navLabelActive]}>Expiring / Active Permits</Text>
              </GlassCard>
            </Pressable>
            <Pressable style={s.navCardWrap} onPress={() => { setActiveTab(activeTab === 'violation' ? 'all' : 'violation'); setExpandedLogId(null); }}>
              <GlassCard style={[s.navCard, activeTab === 'violation' && s.navCardActive]}>
                <Gavel size={22} strokeWidth={1.5} color={activeTab === 'violation' ? chrome.brand : (openViolations > 0 ? semantic.critical : colors.text.muted)} />
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navCount, openViolations > 0 && { color: semantic.criticalText }, activeTab === 'violation' && s.navCountActive]}>{ofText(openViolations, totalViolations)}</Text>
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navLabel, activeTab === 'violation' && s.navLabelActive]}>Open Violations</Text>
              </GlassCard>
            </Pressable>
            <Pressable style={s.navCardWrap} onPress={() => { setActiveTab(activeTab === 'complaint' ? 'all' : 'complaint'); setExpandedLogId(null); }}>
              <GlassCard style={[s.navCard, activeTab === 'complaint' && s.navCardActive]}>
                <MessageSquare size={22} strokeWidth={1.5} color={activeTab === 'complaint' ? chrome.brand : (openComplaints > 0 ? semantic.attention : colors.text.muted)} />
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navCount, openComplaints > 0 && { color: semantic.attention }, activeTab === 'complaint' && s.navCountActive]}>{ofText(openComplaints, totalComplaints)}</Text>
                <Text numberOfLines={1} adjustsFontSizeToFit style={[s.navLabel, activeTab === 'complaint' && s.navLabelActive]}>Open Complaints</Text>
              </GlassCard>
            </Pressable>
          </View>

          {/* Disclosure: permits with no expiry date are excluded from the
              "active" denominator — surface the gap so it's never silent. */}
          {permitsNoExpiry > 0 && (
            <Text style={s.disclosureText}>
              {permitsNoExpiry} permit{permitsNoExpiry === 1 ? '' : 's'} without expiry data not counted
            </Text>
          )}

          {/* Active filter indicator */}
          {activeTab !== 'all' && (
            <Pressable onPress={() => setActiveTab('all')}>
              <View style={s.filterBanner}>
                <Text style={s.filterText}>
                  Showing: {activeTab === 'permit' ? 'Permits' : activeTab === 'violation' ? 'Violations' : activeTab === 'inspection' ? 'Inspections' : 'Complaints'}
                </Text>
                <Text style={s.filterClear}>Show All</Text>
              </View>
            </Pressable>
          )}

          {/* Renewal status banner */}
          {renewablePermits.length > 0 && (
            <GlassCard style={s.renewalBanner}>
              <View style={s.renewalBannerHeader}>
                <ShieldAlert size={16} strokeWidth={2} color={semantic.attention} />
                <Text style={s.renewalBannerTitle}>
                  {renewablePermits.length} Permit{renewablePermits.length > 1 ? 's' : ''} Need Renewal
                </Text>
              </View>
              <View style={s.renewalStatsRow}>
                {expiringPermits.length > 0 && (
                  <View style={s.renewalStat}>
                    <Text style={[s.renewalStatNum, { color: semantic.attention }]}>{expiringPermits.length}</Text>
                    <Text style={s.renewalStatLabel}>Expiring</Text>
                  </View>
                )}
                {expiredPermits.length > 0 && (
                  <View style={s.renewalStat}>
                    <Text style={[s.renewalStatNum, { color: semantic.criticalText }]}>{expiredPermits.length}</Text>
                    <Text style={s.renewalStatLabel}>Expired</Text>
                  </View>
                )}
              </View>
              {renewablePermits.slice(0, 3).map((p) => {
                const d = daysUntil(p.expiration_date);
                return (
                  <View key={p.id} style={s.renewalItem}>
                    <Text style={s.renewalItemText} numberOfLines={1}>
                      {p.work_type || p.permit_type || 'Permit'} ({p.job_number || '—'})
                    </Text>
                    <Text style={[s.renewalItemDays, { color: d !== null && d < 0 ? semantic.criticalText : semantic.attention }]}>
                      {d !== null ? (d < 0 ? `${Math.abs(d)}d overdue` : `${d}d left`) : 'Expired'}
                    </Text>
                  </View>
                );
              })}
              {renewablePermits.length > 3 && (
                <Text style={s.renewalMore}>+{renewablePermits.length - 3} more — filter by Permits to see all</Text>
              )}
            </GlassCard>
          )}

            </>
          }
          ListEmptyComponent={(() => {
            // Rows render via data/renderItem above; this covers only the
            // no-rows case (three distinct empty states so the screen is never
            // ambiguous between "still loading", "BIN not configured", "BIN set
            // but no DOB records", and "filter excludes everything").
            if (loading) return null; // RefreshControl / spinner covers this

            // --- Empty states, most specific first ---

            // (1) No BIN on file — auto-lookup didn't resolve, OR a borough
            // placeholder (X000000) that returns zero DOB records. Same
            // isValidBin() predicate as the project tile, so they never
            // disagree. Admin needs a borough-specific address or a real BIN.
            if (!isValidBin(nycBin)) {
              return (
                <GlassCard style={s.emptyCard}>
                  <AlertTriangle size={40} strokeWidth={1} color={semantic.attention} />
                  <Text style={s.emptyTitle}>No BIN on File</Text>
                  <Text style={s.emptySubtitle}>
                    We couldn't auto-resolve this project's NYC Building Identification
                    Number (BIN). Addresses like "852 E 176" need a borough to match —
                    add the borough to the project address or enter the BIN manually
                    in DOB Config.
                  </Text>
                  {isAdmin ? (
                    <GlassButton
                      title="Open DOB Config"
                      icon={<Settings size={16} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={openConfigModal}
                      style={{ marginTop: spacing.sm }}
                    />
                  ) : null}
                </GlassCard>
              );
            }

            // (2) BIN set + sync has run + all four record types empty
            // across the whole feed (activeTab='all' shows nothing).
            // Could be a wrong BIN or a genuinely pre-filing project.
            if (activeTab === 'all' && allLogs.length === 0) {
              return (
                <GlassCard style={s.emptyCard}>
                  <Shield size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyTitle}>BIN Has No DOB Records</Text>
                  <Text style={s.emptySubtitle}>
                    Sync completed but NYC DOB returned zero permits, violations,
                    complaints, or inspections for BIN {nycBin}. Verify this BIN
                    at a810-bisweb.nyc.gov — if the BIN is wrong, open DOB Config
                    to correct it. If the BIN is right, the project is likely
                    pre-filing and records will appear once a job is filed.
                  </Text>
                  <Pressable
                    onPress={() =>
                      Linking.openURL(
                        `https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet?bin=${nycBin}`
                      )
                    }
                    style={{ marginTop: spacing.sm }}
                  >
                    <Text style={{ color: '#3b82f6', fontSize: 13 }}>
                      Open BIN {nycBin} on NYC BIS ↗
                    </Text>
                  </Pressable>
                </GlassCard>
              );
            }

            // (3) BIN set + records exist overall, but the active tab
            // filter hides them. Not a problem — just filtered.
            return (
              <GlassCard style={s.emptyCard}>
                <Shield size={40} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyTitle}>
                  {activeTab === 'all'
                    ? 'No Records Found'
                    : `No ${
                        activeTab === 'permit'
                          ? 'Permits'
                          : activeTab === 'violation'
                          ? 'Violations'
                          : activeTab === 'inspection'
                          ? 'Inspections'
                          : 'Complaints'
                      }`}
                </Text>
                <Text style={s.emptySubtitle}>
                  {!trackDobStatus
                    ? 'Enable DOB tracking to start monitoring.'
                    : allLogs.length > 0
                    ? 'No records of this type. Tap another tab to see the rest.'
                    : 'Hit Sync Now to check for new records.'}
                </Text>
              </GlassCard>
            );
          })()}
        />

        {/* Config Modal */}
        <Modal visible={showConfigModal} transparent animationType="fade" onRequestClose={() => setShowConfigModal(false)}>
          <Pressable style={s.modalOverlay} onPress={() => setShowConfigModal(false)}>
            <Pressable style={s.modalContent} onPress={(e) => e.stopPropagation()}>
              <GlassCard style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>DOB Configuration</Text>
                  <GlassButton variant="icon" icon={<X size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => setShowConfigModal(false)} />
                </View>
                <View style={s.modalForm}>
                  <Text style={s.inputLabel}>Building Identification Number (BIN)</Text>
                  <GlassInput value={configBin} onChangeText={setConfigBin} placeholder="7-digit BIN" keyboardType="number-pad" maxLength={7} />
                  <Text style={s.inputHint}>Find your BIN at a810-bisweb.nyc.gov</Text>
                </View>
                <Pressable style={s.toggleRow} onPress={() => setConfigTracking(!configTracking)}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <Text style={s.toggleLabel}>Enable DOB Tracking</Text>
                    {/* Phase B3: tooltip explaining what monitoring means. */}
                    <InfoTooltip
                      text="When enabled, LeveLog scans NYC DOB datasets every 15 minutes for permits, filings, violations, inspections, complaints, and stop-work orders linked to this project's BIN or address. New signals appear in the Activity feed; critical items trigger an email per your notification preferences."
                      size={14}
                    />
                  </View>
                  <View style={[s.toggle, configTracking && s.toggleOn]}>
                    <View style={[s.toggleDot, configTracking && s.toggleDotOn]} />
                  </View>
                </Pressable>
                <GlassButton title={savingConfig ? 'Saving...' : 'Save Configuration'} onPress={handleSaveConfig} disabled={savingConfig} style={s.saveBtn} />
              </GlassCard>
            </Pressable>
          </Pressable>
        </Modal>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const DetailRow = ({ label, value, colors }) => (
  <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6 }}>
    <Text style={{ fontSize: 12, color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5, flex: 0.4 }}>{label}</Text>
    <Text style={{ fontSize: 13, color: colors.text.primary, flex: 0.6, textAlign: 'right' }} numberOfLines={3}>{value}</Text>
  </View>
);

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: spacing.md },
    loadingText: { ...typography.body, color: colors.text.muted },
    header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.08) },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    headerRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    logoText: { ...typography.label, color: colors.text.muted },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    titleSection: { marginBottom: spacing.lg },
    titleLabel: { ...typography.label, color: colors.text.secondary, marginBottom: spacing.sm },
    titleText: { fontSize: 28, fontWeight: '200', color: colors.text.primary, letterSpacing: -0.5, marginBottom: spacing.xs },
    binBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    binText: { fontSize: 13, color: colors.text.muted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
    noBinBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    noBinText: { fontSize: 13, color: semantic.attention },

    // Nav cards (replaces pill tabs + stat row)
    navRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.lg },
    // Needs to fit the longest label ("Inspections") + two-digit count
    // inside GlassCard's built-in cardContent padding (spacing.xl each
    // side). 118px leaves ~70px usable which comfortably fits both.
    navCardWrap: { flexGrow: 1, flexBasis: 150, minWidth: 150 },
    navCard: { alignItems: 'center', paddingVertical: spacing.md, paddingHorizontal: spacing.xs, gap: 4 },
    navCardActive: { borderColor: semantic.verifiedBorder, backgroundColor: semantic.verifiedBg },
    navCount: { fontSize: 20, fontWeight: '700', color: colors.text.primary },
    navCountActive: { color: chrome.brand },
    navLabel: { fontSize: 11, color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
    navLabelActive: { color: chrome.brand },

    // Filter banner
    filterBanner: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, marginBottom: spacing.md, borderRadius: borderRadius.lg, backgroundColor: semantic.verifiedBg, borderWidth: 1, borderColor: semantic.verifiedBorder },
    filterText: { fontSize: 13, color: chrome.brand, fontWeight: '500' },
    disclosureText: { fontSize: 11, color: colors.text.muted, textAlign: 'center', marginBottom: spacing.md },
    filterClear: { fontSize: 12, color: colors.text.muted, textDecorationLine: 'underline' },

    // Renewal status banner
    renewalBanner: { backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder, marginBottom: spacing.lg },
    renewalBannerHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
    renewalBannerTitle: { fontSize: 14, fontWeight: '600', color: semantic.attention },
    renewalStatsRow: { flexDirection: 'row', gap: spacing.lg, marginBottom: spacing.sm },
    renewalStat: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
    renewalStatNum: { fontSize: 18, fontWeight: '700' },
    renewalStatLabel: { fontSize: 12, color: colors.text.muted },
    renewalItem: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 4, paddingLeft: spacing.lg + spacing.sm },
    renewalItemText: { fontSize: 13, color: colors.text.secondary, flex: 1 },
    renewalItemDays: { fontSize: 12, fontWeight: '600', marginLeft: spacing.sm },
    renewalMore: { fontSize: 11, color: colors.text.muted, marginTop: 4, marginLeft: spacing.lg + spacing.sm },

    // Renew bubble on permit cards
    renewBubble: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: semantic.verified, paddingHorizontal: 10, paddingVertical: 4, borderRadius: borderRadius.full },
    renewBubbleUrgent: { backgroundColor: semantic.critical },
    renewBubbleText: { fontSize: 11, fontWeight: '600', color: '#fff' },

    // BIS legacy banner
    bisLegacyBanner: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, backgroundColor: semantic.attentionBg, borderRadius: borderRadius.lg, padding: spacing.md, marginTop: spacing.sm, borderWidth: 1, borderColor: semantic.attentionBorder },
    bisLegacyText: { fontSize: 13, color: semantic.attention, flex: 1, lineHeight: 18 },

    // Full-width sync button
    titleTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm, marginBottom: spacing.sm },
    syncChip: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 4, paddingHorizontal: spacing.sm, borderRadius: borderRadius.sm, borderWidth: 1, borderColor: border.subtle },
    syncChipText: { color: text.secondary, fontSize: 11, fontWeight: '500' },
    syncChipHover: { borderColor: border.medium, backgroundColor: surface.glassHover },
    syncChipDisabled: { opacity: 0.6 },
    totalText: { fontSize: 12, color: colors.text.muted, textAlign: 'center', marginBottom: spacing.lg },

    logsList: { gap: spacing.md },
    logCard: { gap: spacing.sm },
    swoCard: { borderColor: semantic.criticalBorder, borderWidth: 1 },
    // Header wraps on narrow viewports so date chips drop below
    // badges instead of pushing them off-screen.
    logHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: spacing.xs,
    },
    logHeaderLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      flexWrap: 'wrap',
      flex: 1,
      minWidth: 0,
    },
    logHeaderRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      flexWrap: 'wrap',
    },
    severityDot: { width: 10, height: 10, borderRadius: 5 },
    typeBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: borderRadius.full, borderWidth: 1 },
    typeText: { fontSize: 11, fontWeight: '500' },
    statusPill: { marginLeft: 6, paddingHorizontal: 6, paddingVertical: 2, borderRadius: borderRadius.full, borderWidth: 1 },
    statusPillText: { fontSize: 10, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.3 },
    dateText: { fontSize: 11, color: colors.text.subtle },
    // Text containers must flex and clip at line limit — no maxWidth
    // so they can fill the available column on all viewports.
    logSummary: {
      fontSize: 14,
      color: colors.text.primary,
      lineHeight: 20,
      flex: 1,
      flexShrink: 1,
    },
    expirationBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.lg },
    expiredBanner: { backgroundColor: semantic.criticalBg },
    expiringBanner: { backgroundColor: semantic.attentionBg },
    expirationText: { fontSize: 12, fontWeight: '600' },
    expandedSection: { gap: spacing.xs },
    divider: { height: 1, backgroundColor: colors.glass.border, marginVertical: spacing.sm },
    nextActionBox: { backgroundColor: 'rgba(59,130,246,0.08)', borderRadius: borderRadius.lg, padding: spacing.md, marginTop: spacing.sm },
    nextActionLabel: { fontSize: 10, fontWeight: '600', color: '#3b82f6', letterSpacing: 1, marginBottom: 4 },
    nextActionText: { fontSize: 13, color: colors.text.primary, lineHeight: 18 },
    dobLinkBtn: { marginTop: spacing.sm },
    detectedText: { fontSize: 11, color: colors.text.subtle, marginTop: spacing.sm },
    emptyCard: { alignItems: 'center', gap: spacing.md, paddingVertical: spacing.xl },
    emptyTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
    emptySubtitle: { fontSize: 14, color: colors.text.muted, textAlign: 'center' },
    modalOverlay: { flex: 1, backgroundColor: withAlpha('#000000', 0.6), justifyContent: 'center', alignItems: 'center' },
    modalContent: { width: '90%', maxWidth: 400 },
    modalCard: { gap: spacing.md },
    modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
    modalTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
    modalForm: { gap: spacing.sm },
    inputLabel: { fontSize: 12, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
    inputHint: { fontSize: 11, color: colors.text.subtle },
    toggleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.sm },
    toggleLabel: { fontSize: 15, color: colors.text.primary },
    toggle: { width: 48, height: 28, borderRadius: 14, backgroundColor: withAlpha('#ffffff', 0.1), justifyContent: 'center', paddingHorizontal: 3 },
    toggleOn: { backgroundColor: semantic.verifiedBg },
    toggleDot: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.text.muted },
    toggleDotOn: { backgroundColor: '#4ade80', alignSelf: 'flex-end' },
    saveBtn: { marginTop: spacing.sm },
  });
}
