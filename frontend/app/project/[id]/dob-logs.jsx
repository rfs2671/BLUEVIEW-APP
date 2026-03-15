import React, { useState, useEffect, useCallback } from 'react';
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
  Alert,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Shield,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Settings,
  ChevronDown,
  ChevronUp,
  Search,
  X,
  Building2,
  FileText,
  Zap,
  Clock,
  Filter,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { GlassSkeleton } from '../../../src/components/GlassSkeleton';
import FloatingNav from '../../../src/components/FloatingNav';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { dobAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

// Severity badge configuration
const SEVERITY_CONFIG = {
  Critical: { color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)', border: 'rgba(239, 68, 68, 0.3)', icon: AlertTriangle },
  Medium: { color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)', border: 'rgba(245, 158, 11, 0.3)', icon: AlertCircle },
  Low: { color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)', border: 'rgba(34, 197, 94, 0.3)', icon: CheckCircle },
};

// Record type labels
const RECORD_TYPE_LABELS = {
  violation: 'Violation',
  complaint: 'Complaint',
  job_status: 'Job Filing',
  swo: 'Stop Work Order',
  permit: 'Permit',
};

const RECORD_TYPE_COLORS = {
  violation: '#ef4444',
  complaint: '#f59e0b',
  job_status: '#3b82f6',
  swo: '#dc2626',
  permit: '#22c55e',
};

// Filter options
const SEVERITY_OPTIONS = ['All', 'Critical', 'Medium', 'Low'];
const TYPE_OPTIONS = ['All', 'violation', 'complaint', 'job_status', 'swo', 'permit'];

export default function DOBLogsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  // Data state
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [nycBin, setNycBin] = useState('');
  const [trackDobStatus, setTrackDobStatus] = useState(false);
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);

  // Filter state
  const [severityFilter, setSeverityFilter] = useState('All');
  const [typeFilter, setTypeFilter] = useState('All');
  const [showFilters, setShowFilters] = useState(false);

  // Config modal state
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configBin, setConfigBin] = useState('');
  const [configBbl, setConfigBbl] = useState('');
  const [configTracking, setConfigTracking] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);

  // Expanded log card
  const [expandedLogId, setExpandedLogId] = useState(null);

  // Auth guard - delay to ensure Root Layout has mounted
  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const timer = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated, authLoading]);
  
  // Fetch data
  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchLogs();
    }
  }, [isAuthenticated, projectId, severityFilter, typeFilter]);

  const fetchLogs = async () => {
    if (!loading) setRefreshing(true);
    try {
      const params = {};
      if (severityFilter !== 'All') params.severity = severityFilter;
      if (typeFilter !== 'All') params.record_type = typeFilter;
      params.limit = 100;

      const data = await dobAPI.getLogs(projectId, params);
      setProjectName(data.project_name || '');
      setNycBin(data.nyc_bin || '');
      setTrackDobStatus(data.track_dob_status || false);
      setLogs(data.logs || []);
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
      toast.success(
        'Sync Complete',
        result.new_records > 0
          ? `${result.new_records} new record(s) found. ${result.critical_count} critical.`
          : 'No new records found.'
      );
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

  const openConfigModal = () => {
    setConfigBin(nycBin || '');
    setConfigBbl('');
    setConfigTracking(trackDobStatus);
    setShowConfigModal(true);
  };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const config = {};
      if (configBin !== nycBin) config.nyc_bin = configBin;
      if (configBbl.trim()) config.nyc_bbl = configBbl.trim();
      config.track_dob_status = configTracking;

      const result = await dobAPI.updateConfig(projectId, config);
      setNycBin(result.nyc_bin || '');
      setTrackDobStatus(result.track_dob_status || false);
      setShowConfigModal(false);
      toast.success('Saved', 'DOB configuration updated');

      // Re-fetch if tracking was just enabled
      if (result.track_dob_status) {
        await fetchLogs();
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Could not save config';
      toast.error('Error', detail);
    } finally {
      setSavingConfig(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // Compute stats from current logs
  const criticalCount = logs.filter((l) => l.severity === 'Critical').length;
  const mediumCount = logs.filter((l) => l.severity === 'Medium').length;
  const lowCount = logs.filter((l) => l.severity === 'Low').length;

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

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
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <Text style={s.logoText}>BLUEVIEW</Text>
          </View>
          <View style={s.headerRight}>
            {isAdmin && (
              <GlassButton
                variant="icon"
                icon={<Settings size={20} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={openConfigModal}
              />
            )}
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={fetchLogs}
              tintColor={colors.text.muted}
            />
          }
        >
          {/* Title Section */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>DOB COMPLIANCE</Text>
            <Text style={s.titleText}>{projectName}</Text>
            {nycBin ? (
              <View style={s.binBadge}>
                <Building2 size={14} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.binText}>BIN: {nycBin}</Text>
                {trackDobStatus && (
                  <View style={s.trackingDot} />
                )}
              </View>
            ) : (
              <Pressable onPress={openConfigModal} style={s.noBinBadge}>
                <AlertCircle size={14} strokeWidth={1.5} color="#f59e0b" />
                <Text style={s.noBinText}>No BIN configured — tap to set up</Text>
              </Pressable>
            )}
          </View>

          {/* Stats Row */}
          <View style={s.statsRow}>
            <StatCard style={s.statCard}>
              <Text style={s.statLabel}>Critical</Text>
              <Text style={[s.statValue, { color: '#ef4444' }]}>{criticalCount}</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <Text style={s.statLabel}>Medium</Text>
              <Text style={[s.statValue, { color: '#f59e0b' }]}>{mediumCount}</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <Text style={s.statLabel}>Low</Text>
              <Text style={[s.statValue, { color: '#22c55e' }]}>{lowCount}</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <Text style={s.statLabel}>Total</Text>
              <Text style={[s.statValue, { color: colors.text.primary }]}>{total}</Text>
            </StatCard>
          </View>

          {/* Action Buttons */}
          <View style={s.actionsRow}>
            {isAdmin && (
              <GlassButton
                title={syncing ? 'Syncing...' : 'Sync Now'}
                icon={
                  syncing ? (
                    <ActivityIndicator size="small" color={colors.text.primary} />
                  ) : (
                    <RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />
                  )
                }
                onPress={handleSync}
                disabled={syncing || !nycBin}
                style={s.syncBtn}
              />
            )}
            <GlassButton
              title="Filters"
              icon={<Filter size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => setShowFilters(!showFilters)}
              style={s.filterBtn}
            />
          </View>

          {/* Filters Panel */}
          {showFilters && (
            <GlassCard style={s.filterPanel}>
              <Text style={s.filterTitle}>Severity</Text>
              <View style={s.filterChips}>
                {SEVERITY_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt}
                    onPress={() => setSeverityFilter(opt)}
                    style={[
                      s.chip,
                      severityFilter === opt && s.chipActive,
                      severityFilter === opt && opt !== 'All' && {
                        backgroundColor: SEVERITY_CONFIG[opt]?.bg,
                        borderColor: SEVERITY_CONFIG[opt]?.border,
                      },
                    ]}
                  >
                    <Text
                      style={[
                        s.chipText,
                        severityFilter === opt && s.chipTextActive,
                        severityFilter === opt && opt !== 'All' && {
                          color: SEVERITY_CONFIG[opt]?.color,
                        },
                      ]}
                    >
                      {opt}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={[s.filterTitle, { marginTop: spacing.md }]}>Record Type</Text>
              <View style={s.filterChips}>
                {TYPE_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt}
                    onPress={() => setTypeFilter(opt)}
                    style={[
                      s.chip,
                      typeFilter === opt && s.chipActive,
                    ]}
                  >
                    <Text style={[s.chipText, typeFilter === opt && s.chipTextActive]}>
                      {opt === 'All' ? 'All' : RECORD_TYPE_LABELS[opt] || opt}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </GlassCard>
          )}

          {/* Logs List */}
          {logs.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Shield size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyTitle}>
                {!nycBin
                  ? 'No BIN Configured'
                  : !trackDobStatus
                  ? 'DOB Tracking Disabled'
                  : 'All Clear'}
              </Text>
              <Text style={s.emptySubtitle}>
                {!nycBin
                  ? 'Configure a Building Identification Number to start monitoring.'
                  : !trackDobStatus
                  ? 'Enable DOB tracking in settings to monitor this project.'
                  : 'No violations, complaints, or filings detected for this project.'}
              </Text>
              {!nycBin && isAdmin && (
                <GlassButton
                  title="Configure BIN"
                  icon={<Settings size={16} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={openConfigModal}
                  style={{ marginTop: spacing.md }}
                />
              )}
            </GlassCard>
          ) : (
            <View style={s.logsList}>
              {logs.map((log) => {
                const sevConfig = SEVERITY_CONFIG[log.severity] || SEVERITY_CONFIG.Medium;
                const SevIcon = sevConfig.icon;
                const isExpanded = expandedLogId === log.id;
                const typeColor = RECORD_TYPE_COLORS[log.record_type] || '#6b7280';

                return (
                  <Pressable
                    key={log.id}
                    onPress={() => setExpandedLogId(isExpanded ? null : log.id)}
                  >
                    <GlassCard style={s.logCard}>
                      {/* Log Header */}
                      <View style={s.logHeader}>
                        <View style={s.logHeaderLeft}>
                          <View style={[s.severityBadge, { backgroundColor: sevConfig.bg, borderColor: sevConfig.border }]}>
                            <SevIcon size={12} strokeWidth={2} color={sevConfig.color} />
                            <Text style={[s.severityText, { color: sevConfig.color }]}>
                              {log.severity}
                            </Text>
                          </View>
                          <View style={[s.typeBadge, { borderColor: typeColor + '40' }]}>
                            <Text style={[s.typeText, { color: typeColor }]}>
                              {RECORD_TYPE_LABELS[log.record_type] || log.record_type}
                            </Text>
                          </View>
                        </View>
                        {isExpanded ? (
                          <ChevronUp size={16} strokeWidth={1.5} color={colors.text.muted} />
                        ) : (
                          <ChevronDown size={16} strokeWidth={1.5} color={colors.text.muted} />
                        )}
                      </View>

                      {/* Summary */}
                      <Text style={s.logSummary} numberOfLines={isExpanded ? undefined : 2}>
                        {log.ai_summary}
                      </Text>

                      {/* Expanded Details */}
                      {isExpanded && (
                        <View style={s.logExpanded}>
                          <View style={s.logDetailRow}>
                            <Zap size={14} strokeWidth={1.5} color={colors.text.muted} />
                            <View style={s.logDetailContent}>
                              <Text style={s.logDetailLabel}>Required Action</Text>
                              <Text style={s.logDetailValue}>{log.next_action}</Text>
                            </View>
                          </View>
                          <View style={s.logDetailRow}>
                            <Clock size={14} strokeWidth={1.5} color={colors.text.muted} />
                            <View style={s.logDetailContent}>
                              <Text style={s.logDetailLabel}>Detected</Text>
                              <Text style={s.logDetailValue}>{formatDate(log.detected_at)}</Text>
                            </View>
                          </View>
                          <View style={s.logDetailRow}>
                            <FileText size={14} strokeWidth={1.5} color={colors.text.muted} />
                            <View style={s.logDetailContent}>
                              <Text style={s.logDetailLabel}>DOB Record ID</Text>
                              <Text style={s.logDetailValue}>{log.raw_dob_id}</Text>
                            </View>
                          </View>
                        </View>
                      )}

                      {/* Footer */}
                      <Text style={s.logDate}>{formatDate(log.detected_at)}</Text>
                    </GlassCard>
                  </Pressable>
                );
              })}
            </View>
          )}
        </ScrollView>

        {/* Config Modal */}
        <Modal
          visible={showConfigModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowConfigModal(false)}
        >
          <Pressable style={s.modalOverlay} onPress={() => setShowConfigModal(false)}>
            <Pressable style={s.modalContent} onPress={(e) => e.stopPropagation()}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>DOB Configuration</Text>
                  <GlassButton
                    variant="icon"
                    icon={<X size={20} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={() => setShowConfigModal(false)}
                  />
                </View>

                <Text style={s.modalDescription}>
                  The Building Identification Number (BIN) is auto-detected from the project
                  address. Override it here if the auto-detection was incorrect.
                </Text>

                <View style={s.configField}>
                  <Text style={s.configLabel}>NYC BIN (7 digits)</Text>
                  <GlassInput
                    value={configBin}
                    onChangeText={setConfigBin}
                    placeholder="e.g. 1234567"
                    keyboardType="number-pad"
                    maxLength={7}
                  />
                </View>

                <View style={s.configField}>
                  <Text style={s.configLabel}>NYC BBL (optional)</Text>
                  <GlassInput
                    value={configBbl}
                    onChangeText={setConfigBbl}
                    placeholder="Borough-Block-Lot"
                  />
                </View>

                <Pressable
                  onPress={() => setConfigTracking(!configTracking)}
                  style={s.toggleRow}
                >
                  <View style={s.toggleInfo}>
                    <Text style={s.toggleLabel}>Enable DOB Tracking</Text>
                    <Text style={s.toggleDescription}>
                      Automatically scan NYC Open Data daily for violations and complaints
                    </Text>
                  </View>
                  <View style={[s.toggleSwitch, configTracking && s.toggleSwitchActive]}>
                    <View style={[s.toggleKnob, configTracking && s.toggleKnobActive]} />
                  </View>
                </Pressable>

                <GlassButton
                  title={savingConfig ? 'Saving...' : 'Save Configuration'}
                  onPress={handleSaveConfig}
                  disabled={savingConfig}
                  style={s.saveBtn}
                />
              </GlassCard>
            </Pressable>
          </Pressable>
        </Modal>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: {
      flex: 1,
    },
    loadingContainer: {
      flex: 1,
      justifyContent: 'center',
      alignItems: 'center',
      gap: spacing.md,
    },
    loadingText: {
      ...typography.body,
      color: colors.text.muted,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: 'rgba(255, 255, 255, 0.08)',
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    headerRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    logoText: {
      ...typography.label,
      color: colors.text.muted,
    },
    scrollView: {
      flex: 1,
    },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 120,
    },

    // Title
    titleSection: {
      marginBottom: spacing.xl,
    },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 32,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -0.5,
      marginBottom: spacing.sm,
    },
    binBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      marginTop: spacing.xs,
    },
    binText: {
      fontSize: 13,
      color: colors.text.muted,
      fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    },
    trackingDot: {
      width: 6,
      height: 6,
      borderRadius: 3,
      backgroundColor: '#22c55e',
      marginLeft: spacing.xs,
    },
    noBinBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      marginTop: spacing.xs,
      paddingVertical: spacing.xs,
    },
    noBinText: {
      fontSize: 13,
      color: '#f59e0b',
    },

    // Stats
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
    statLabel: {
      fontSize: 10,
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      marginBottom: spacing.xs,
    },
    statValue: {
      fontSize: 24,
      fontWeight: '600',
    },

    // Actions
    actionsRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginBottom: spacing.lg,
    },
    syncBtn: {
      flex: 1,
    },
    filterBtn: {
      flex: 0,
    },

    // Filters
    filterPanel: {
      marginBottom: spacing.lg,
      padding: spacing.lg,
    },
    filterTitle: {
      fontSize: 11,
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      marginBottom: spacing.sm,
    },
    filterChips: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: spacing.sm,
    },
    chip: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: 'transparent',
    },
    chipActive: {
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(59, 130, 246, 0.1)',
      borderColor: isDark ? 'rgba(255, 255, 255, 0.2)' : 'rgba(59, 130, 246, 0.3)',
    },
    chipText: {
      fontSize: 12,
      color: colors.text.muted,
    },
    chipTextActive: {
      color: colors.text.primary,
      fontWeight: '500',
    },

    // Empty state
    emptyCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
    },
    emptyTitle: {
      fontSize: 18,
      fontWeight: '500',
      color: colors.text.primary,
    },
    emptySubtitle: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      lineHeight: 20,
      maxWidth: 300,
    },

    // Logs
    logsList: {
      gap: spacing.md,
    },
    logCard: {
      padding: spacing.lg,
    },
    logHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.sm,
    },
    logHeaderLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    severityBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingHorizontal: spacing.sm,
      paddingVertical: 3,
      borderRadius: borderRadius.full,
      borderWidth: 1,
    },
    severityText: {
      fontSize: 11,
      fontWeight: '600',
      textTransform: 'uppercase',
      letterSpacing: 0.3,
    },
    typeBadge: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 3,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      backgroundColor: 'transparent',
    },
    typeText: {
      fontSize: 11,
      fontWeight: '500',
    },
    logSummary: {
      fontSize: 15,
      color: colors.text.primary,
      lineHeight: 22,
      marginBottom: spacing.sm,
    },
    logExpanded: {
      marginTop: spacing.sm,
      paddingTop: spacing.md,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      gap: spacing.md,
    },
    logDetailRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
    },
    logDetailContent: {
      flex: 1,
    },
    logDetailLabel: {
      fontSize: 11,
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.3,
      marginBottom: 2,
    },
    logDetailValue: {
      fontSize: 14,
      color: colors.text.primary,
      lineHeight: 20,
    },
    logDate: {
      fontSize: 12,
      color: colors.text.subtle,
      marginTop: spacing.xs,
    },

    // Modal
    modalOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      backgroundColor: 'rgba(0, 0, 0, 0.5)',
    },
    modalContent: {
      maxHeight: '80%',
    },
    modalCard: {
      borderTopLeftRadius: borderRadius.xxl,
      borderTopRightRadius: borderRadius.xxl,
      borderBottomLeftRadius: 0,
      borderBottomRightRadius: 0,
      padding: spacing.xl,
    },
    modalHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.lg,
    },
    modalTitle: {
      fontSize: 20,
      fontWeight: '600',
      color: colors.text.primary,
    },
    modalDescription: {
      fontSize: 14,
      color: colors.text.muted,
      lineHeight: 20,
      marginBottom: spacing.lg,
    },
    configField: {
      marginBottom: spacing.lg,
    },
    configLabel: {
      fontSize: 12,
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      marginBottom: spacing.sm,
    },
    toggleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.md,
      marginBottom: spacing.lg,
    },
    toggleInfo: {
      flex: 1,
      marginRight: spacing.lg,
    },
    toggleLabel: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
      marginBottom: 2,
    },
    toggleDescription: {
      fontSize: 13,
      color: colors.text.muted,
      lineHeight: 18,
    },
    toggleSwitch: {
      width: 48,
      height: 28,
      borderRadius: 14,
      backgroundColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
      justifyContent: 'center',
      paddingHorizontal: 2,
    },
    toggleSwitchActive: {
      backgroundColor: '#22c55e',
    },
    toggleKnob: {
      width: 24,
      height: 24,
      borderRadius: 12,
      backgroundColor: '#fff',
      ...(Platform.OS === 'web'
        ? { boxShadow: '0 1px 3px rgba(0,0,0,0.2)' }
        : { shadowColor: '#000', shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.2, shadowRadius: 3 }),
    },
    toggleKnobActive: {
      alignSelf: 'flex-end',
    },
    saveBtn: {
      marginTop: spacing.sm,
    },
  });
}
