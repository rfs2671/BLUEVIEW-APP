import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Platform,
  Linking,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Shield,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  Settings,
  ChevronDown,
  ChevronUp,
  X,
  Building2,
  FileCheck,
  Gavel,
  MessageSquare,
  Briefcase,
  ExternalLink,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import FloatingNav from '../../../src/components/FloatingNav';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { dobAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

const SEVERITY_CONFIG = {
  Action: { color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)', border: 'rgba(239, 68, 68, 0.3)', icon: AlertTriangle, label: 'Action Needed' },
  Good: { color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)', border: 'rgba(34, 197, 94, 0.3)', icon: CheckCircle, label: 'Good' },
};

const getSevConfig = (severity) => {
  if (severity === 'Action' || severity === 'Critical' || severity === 'Medium') return SEVERITY_CONFIG.Action;
  return SEVERITY_CONFIG.Good;
};

const TABS = [
  { key: 'all', label: 'All', icon: Shield },
  { key: 'permit', label: 'Permits', icon: FileCheck },
  { key: 'violation', label: 'Violations', icon: Gavel },
  { key: 'complaint', label: 'Complaints', icon: MessageSquare },
  { key: 'job_status', label: 'Filings', icon: Briefcase },
];

const formatDate = (dateStr) => {
  if (!dateStr) return '\u2014';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) {
    if (typeof dateStr === 'string' && dateStr.length === 8 && !dateStr.includes('-')) {
      return `${dateStr.slice(4, 6)}/${dateStr.slice(6, 8)}/${dateStr.slice(0, 4)}`;
    }
    return String(dateStr).slice(0, 10);
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

const daysUntil = (dateStr) => {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return null;
    return Math.ceil((d - new Date()) / (1000 * 60 * 60 * 24));
  } catch { return null; }
};

export default function DOBLogsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [nycBin, setNycBin] = useState('');
  const [trackDobStatus, setTrackDobStatus] = useState(false);
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [activeTab, setActiveTab] = useState('all');
  const [expandedLogId, setExpandedLogId] = useState(null);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configBin, setConfigBin] = useState('');
  const [configTracking, setConfigTracking] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);

  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const timer = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) fetchLogs();
  }, [isAuthenticated, projectId, activeTab]);

  const fetchLogs = async () => {
    if (!loading) setRefreshing(true);
    try {
      const params = { limit: 200 };
      const data = await dobAPI.getLogs(projectId, params);
      setProjectName(data.project_name || '');
      setNycBin(data.nyc_bin || '');
      setTrackDobStatus(data.track_dob_status || false);

      let filtered = data.logs || [];
      if (activeTab === 'violation') {
        filtered = filtered.filter(l => l.record_type === 'violation' || l.record_type === 'swo');
      } else if (activeTab !== 'all') {
        filtered = filtered.filter(l => l.record_type === activeTab);
      }
      setLogs(filtered);
      setTotal(data.total || 0);
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
      if (error.response?.status === 429) {
        toast.warning('Rate Limited', detail);
      } else {
        toast.error('Sync Error', detail);
      }
    } finally {
      setSyncing(false);
    }
  };

  const openConfigModal = () => { setConfigBin(nycBin || ''); setConfigTracking(trackDobStatus); setShowConfigModal(true); };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const config = {};
      if (configBin !== nycBin) config.nyc_bin = configBin;
      config.track_dob_status = configTracking;
      const result = await dobAPI.updateConfig(projectId, config);
      setNycBin(result.nyc_bin || '');
      setTrackDobStatus(result.track_dob_status || false);
      setShowConfigModal(false);
      toast.success('Saved', 'DOB configuration updated');
      if (result.track_dob_status) await fetchLogs();
    } catch (error) {
      toast.error('Error', error.response?.data?.detail || 'Could not save config');
    } finally { setSavingConfig(false); }
  };

  const handleLogout = async () => { await logout(); router.replace('/login'); };
  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  const actionCount = logs.filter(l => {
    const sev = l.severity;
    return sev === 'Action' || sev === 'Critical' || sev === 'Medium';
  }).length;
  const goodCount = logs.filter(l => {
    const sev = l.severity;
    return sev === 'Good' || sev === 'Low';
  }).length;
  const expiringPermits = logs.filter(l => {
    if (l.record_type !== 'permit') return false;
    const days = daysUntil(l.expiration_date);
    return days !== null && days >= 0 && days <= 30;
  });

  const renderPermitCard = (log) => {
    const isExpanded = expandedLogId === log.id;
    const sevConfig = getSevConfig(log.severity);
    const SevIcon = sevConfig.icon;
    const days = daysUntil(log.expiration_date);
    const isExpired = days !== null && days < 0;
    const isExpiring = days !== null && days >= 0 && days <= 30;

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={s.logCard}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: sevConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: '#22c55e40' }]}>
                <Text style={[s.typeText, { color: '#22c55e' }]}>Permit</Text>
              </View>
            </View>
            {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2}>{log.ai_summary}</Text>
          {(isExpired || isExpiring) && (
            <View style={[s.expirationBanner, isExpired ? s.expiredBanner : s.expiringBanner]}>
              <AlertTriangle size={14} color={isExpired ? '#ef4444' : '#f59e0b'} />
              <Text style={[s.expirationText, { color: isExpired ? '#ef4444' : '#f59e0b' }]}>
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
              {log.dob_link && (
                <GlassButton title="View on DOB BIS" icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
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
    const isSWO = log.record_type === 'swo';

    return (
      <Pressable key={log.id} onPress={() => setExpandedLogId(isExpanded ? null : log.id)}>
        <GlassCard style={[s.logCard, isSWO && s.swoCard]}>
          <View style={s.logHeader}>
            <View style={s.logHeaderLeft}>
              <View style={[s.severityDot, { backgroundColor: sevConfig.color }]} />
              <View style={[s.typeBadge, { borderColor: isSWO ? '#dc262640' : '#ef444440' }]}>
                <Text style={[s.typeText, { color: isSWO ? '#dc2626' : '#ef4444' }]}>{isSWO ? 'Stop Work' : 'Violation'}</Text>
              </View>
            </View>
            {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2}>{log.ai_summary}</Text>
          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              {log.violation_number && <DetailRow label="Violation #" value={log.violation_number} colors={colors} />}
              {log.violation_type && <DetailRow label="Type" value={log.violation_type} colors={colors} />}
              {log.violation_category && <DetailRow label="Category" value={log.violation_category} colors={colors} />}
              {log.description && <DetailRow label="Description" value={log.description} colors={colors} />}
              {log.penalty_amount && <DetailRow label="Penalty" value={`$${log.penalty_amount}`} colors={colors} />}
              {log.respondent && <DetailRow label="Respondent" value={log.respondent} colors={colors} />}
              {log.disposition_date && <DetailRow label="Disposition" value={formatDate(log.disposition_date)} colors={colors} />}
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>ACTION</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {log.dob_link && (
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
    const typeLabel = log.record_type === 'complaint' ? 'Complaint' : log.record_type === 'job_status' ? 'Job Filing' : log.record_type;
    const typeColor = log.record_type === 'complaint' ? '#f59e0b' : '#3b82f6';

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
            {isExpanded ? <ChevronUp size={16} color={colors.text.muted} /> : <ChevronDown size={16} color={colors.text.muted} />}
          </View>
          <Text style={s.logSummary} numberOfLines={isExpanded ? 10 : 2}>{log.ai_summary}</Text>
          {isExpanded && (
            <View style={s.expandedSection}>
              <View style={s.divider} />
              <View style={s.nextActionBox}>
                <Text style={s.nextActionLabel}>ACTION</Text>
                <Text style={s.nextActionText}>{log.next_action}</Text>
              </View>
              {log.dob_link && (
                <GlassButton title="View on DOB BIS" icon={<ExternalLink size={16} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => Linking.openURL(log.dob_link)} style={s.dobLinkBtn} />
              )}
              <Text style={s.detectedText}>ID: {log.raw_dob_id} • {formatDate(log.detected_at)}</Text>
            </View>
          )}
        </GlassCard>
      </Pressable>
    );
  };

  const renderLogCard = (log) => {
    if (log.record_type === 'permit') return renderPermitCard(log);
    if (log.record_type === 'violation' || log.record_type === 'swo') return renderViolationCard(log);
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
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton variant="icon" icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={() => router.back()} />
            <Text style={s.logoText}>BLUEVIEW</Text>
          </View>
          <View style={s.headerRight}>
            {isAdmin && <GlassButton variant="icon" icon={<Settings size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={openConfigModal} />}
            <GlassButton variant="icon" icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />} onPress={handleLogout} />
          </View>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.tabScroll} contentContainerStyle={s.tabRow}>
          {TABS.map((tab) => {
            const isActive = activeTab === tab.key;
            const TabIcon = tab.icon;
            return (
              <Pressable key={tab.key} onPress={() => { setActiveTab(tab.key); setExpandedLogId(null); }} style={[s.tab, isActive && s.tabActive]}>
                <TabIcon size={14} strokeWidth={1.5} color={isActive ? '#4ade80' : colors.text.muted} />
                <Text style={[s.tabText, isActive && s.tabTextActive]}>{tab.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={fetchLogs} tintColor={colors.text.muted} />}>
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>DOB COMPLIANCE</Text>
            <Text style={s.titleText}>{projectName}</Text>
            {nycBin ? (
              <View style={s.binBadge}>
                <Building2 size={13} strokeWidth={1.5} color="#4ade80" />
                <Text style={s.binText}>BIN: {nycBin}</Text>
              </View>
            ) : (
              <Pressable onPress={isAdmin ? openConfigModal : undefined}>
                <View style={s.noBinBadge}>
                  <AlertTriangle size={13} strokeWidth={1.5} color="#f59e0b" />
                  <Text style={s.noBinText}>No BIN — {isAdmin ? 'tap to configure' : 'address-based lookup active'}</Text>
                </View>
              </Pressable>
            )}
          </View>

          <View style={s.statsRow}>
            <GlassCard style={s.statBox}>
              <Text style={[s.statValue, actionCount > 0 && { color: '#ef4444' }]}>{actionCount}</Text>
              <Text style={s.statLabel}>Action Needed</Text>
            </GlassCard>
            <GlassCard style={s.statBox}>
              <Text style={[s.statValue, { color: '#22c55e' }]}>{goodCount}</Text>
              <Text style={s.statLabel}>Good</Text>
            </GlassCard>
            <GlassCard style={s.statBox}>
              <Text style={s.statValue}>{logs.length}</Text>
              <Text style={s.statLabel}>Total</Text>
            </GlassCard>
          </View>

          {expiringPermits.length > 0 && (
            <GlassCard style={s.expiringCard}>
              <View style={s.expiringHeader}>
                <AlertTriangle size={16} strokeWidth={2} color="#f59e0b" />
                <Text style={s.expiringTitle}>{expiringPermits.length} Permit{expiringPermits.length > 1 ? 's' : ''} Expiring Soon</Text>
              </View>
              {expiringPermits.map((p) => (
                <Text key={p.id} style={s.expiringItem}>
                  {p.job_number || 'Permit'}: expires {formatDate(p.expiration_date)} ({daysUntil(p.expiration_date)} days)
                </Text>
              ))}
            </GlassCard>
          )}

          <Pressable onPress={handleSync} disabled={syncing} style={[s.syncButton, syncing && s.syncButtonDisabled]}>
            <RefreshCw size={18} strokeWidth={1.5} color="#fff" />
            <Text style={s.syncButtonText}>{syncing ? 'Syncing with NYC DOB...' : 'Sync Now'}</Text>
          </Pressable>
          <Text style={s.totalText}>{total} total records</Text>

          {logs.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Shield size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyTitle}>
                {activeTab === 'all' ? 'No Records Found' : `No ${TABS.find(t => t.key === activeTab)?.label || 'Records'}`}
              </Text>
              <Text style={s.emptySubtitle}>
                {!trackDobStatus ? 'Enable DOB tracking to start monitoring.' : 'Hit Sync Now to check for new records.'}
              </Text>
            </GlassCard>
          ) : (
            <View style={s.logsList}>{logs.map(renderLogCard)}</View>
          )}
        </ScrollView>

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
                  <Text style={s.toggleLabel}>Enable DOB Tracking</Text>
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
    header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.08)' },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    headerRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    logoText: { ...typography.label, color: colors.text.muted },
    tabScroll: { flexGrow: 0 },
    tabRow: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
    tab: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border, backgroundColor: colors.glass.background },
    tabActive: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: 'rgba(74,222,128,0.3)' },
    tabText: { fontSize: 13, fontWeight: '500', color: colors.text.muted },
    tabTextActive: { color: '#4ade80' },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    titleSection: { marginBottom: spacing.lg },
    titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
    titleText: { fontSize: 28, fontWeight: '200', color: colors.text.primary, letterSpacing: -0.5, marginBottom: spacing.xs },
    binBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    binText: { fontSize: 13, color: colors.text.muted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
    noBinBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    noBinText: { fontSize: 13, color: '#f59e0b' },
    statsRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.lg },
    statBox: { flex: 1, alignItems: 'center', paddingVertical: spacing.md },
    statValue: { fontSize: 24, fontWeight: '600', color: colors.text.primary, marginBottom: 2 },
    statLabel: { fontSize: 10, color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
    expiringCard: { backgroundColor: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)', marginBottom: spacing.lg },
    expiringHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
    expiringTitle: { fontSize: 14, fontWeight: '600', color: '#f59e0b' },
    expiringItem: { fontSize: 13, color: colors.text.secondary, marginLeft: spacing.lg + spacing.sm, marginBottom: 4 },
    syncButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: '#1565C0', paddingVertical: 14, borderRadius: borderRadius.lg, marginBottom: spacing.sm },
    syncButtonDisabled: { opacity: 0.6 },
    syncButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
    totalText: { fontSize: 12, color: colors.text.muted, textAlign: 'center', marginBottom: spacing.lg },
    logsList: { gap: spacing.md },
    logCard: { gap: spacing.sm },
    swoCard: { borderColor: 'rgba(220, 38, 38, 0.3)', borderWidth: 1 },
    logHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    logHeaderLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    severityDot: { width: 10, height: 10, borderRadius: 5 },
    typeBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: borderRadius.full, borderWidth: 1 },
    typeText: { fontSize: 11, fontWeight: '500' },
    logSummary: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    expirationBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.lg },
    expiredBanner: { backgroundColor: 'rgba(239,68,68,0.1)' },
    expiringBanner: { backgroundColor: 'rgba(245,158,11,0.1)' },
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
    modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center' },
    modalContent: { width: '90%', maxWidth: 400 },
    modalCard: { gap: spacing.md },
    modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
    modalTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
    modalForm: { gap: spacing.sm },
    inputLabel: { fontSize: 12, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
    inputHint: { fontSize: 11, color: colors.text.subtle },
    toggleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.sm },
    toggleLabel: { fontSize: 15, color: colors.text.primary },
    toggle: { width: 48, height: 28, borderRadius: 14, backgroundColor: 'rgba(255,255,255,0.1)', justifyContent: 'center', paddingHorizontal: 3 },
    toggleOn: { backgroundColor: 'rgba(74,222,128,0.3)' },
    toggleDot: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.text.muted },
    toggleDotOn: { backgroundColor: '#4ade80', alignSelf: 'flex-end' },
    saveBtn: { marginTop: spacing.sm },
  });
}
