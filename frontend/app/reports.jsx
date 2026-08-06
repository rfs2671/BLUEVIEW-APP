import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Linking,
  RefreshControl,
  Platform,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Download,
  FileText,
  Check,
  Building2,
  ChevronDown,
  Eye,
  Clock,
  Mail,
  Users,
  ClipboardList,
  AlertCircle,
  CheckCircle,
  Send,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Share2,
} from 'lucide-react-native';
import * as FileSystem from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { projectsAPI, dailyLogsAPI, reportsAPI, getToken } from '../src/utils/api';
import apiClient from '../src/utils/api';
import OfflineNotice from '../src/components/OfflineNotice';
import { settleFetch } from '../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic, withAlpha } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';
import HeaderBrand from '../src/components/HeaderBrand';

const TABS = [
  { key: 'today', label: "Today's Report" },
  { key: 'history', label: 'Sent History' },
];

const LOG_TYPE_LABELS = {
  daily_jobsite: 'Daily Jobsite Log',
  toolbox_talk: 'Tool Box Talk',
  scaffold_maintenance: 'Scaffold Maintenance',
  preshift_signin: 'Pre-Shift Sign-In',
  osha_log: 'OSHA Log',
};

export default function ReportsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('today');
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error' per fetch. A failed load must
  // never fall through to this screen's confident empty copy ("No Data
  // Available"), which asserts the day has no report.
  const [projectsState, setProjectsState] = useState('ok');

  // Today's preview
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewState, setPreviewState] = useState('ok');
  const [previewDate, setPreviewDate] = useState(new Date().toISOString().split('T')[0]);

  // History
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyState, setHistoryState] = useState('ok');

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchProjects();
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (selectedProject) {
      if (activeTab === 'today') {
        fetchPreview();
      } else {
        fetchHistory();
      }
    }
  }, [selectedProject, activeTab, previewDate]);

  const fetchProjects = async () => {
    setLoading(true);
    // The old `.catch(() => [])` made an unreachable server indistinguishable
    // from an account with no projects — the picker just read "Choose a
    // project" with an empty dropdown.
    const r = await settleFetch(() => projectsAPI.getAll());
    setProjectsState(r.status);
    if (r.status === 'ok') {
      const projectList = Array.isArray(r.data) ? r.data : [];
      setProjects(projectList);
      if (projectList.length > 0) {
        setSelectedProject(projectList[0]);
      }
    } else {
      console.error('Failed to fetch projects:', r.error);
    }
    setLoading(false);
  };

  const fetchPreview = async () => {
    if (!selectedProject) return;
    setPreviewLoading(true);
    const projectId = selectedProject._id || selectedProject.id;
    const r = await settleFetch(() => reportsAPI.getPreview(projectId, previewDate));
    setPreviewState(r.status);
    if (r.status === 'ok') {
      setPreview(r.data);
    } else {
      console.error('Failed to fetch preview:', r.error);
      // Clear the stale preview but DON'T let the empty state speak for it —
      // the render branches on previewState first.
      setPreview(null);
    }
    setPreviewLoading(false);
  };

  const fetchHistory = async () => {
    if (!selectedProject) return;
    setHistoryLoading(true);
    const projectId = selectedProject._id || selectedProject.id;
    const r = await settleFetch(() => reportsAPI.getHistory(projectId, 30, 0));
    setHistoryState(r.status);
    if (r.status === 'ok') {
      setHistory(r.data?.history || []);
      setHistoryTotal(r.data?.total || 0);
    } else {
      console.error('Failed to fetch history:', r.error);
      setHistory([]);
      setHistoryTotal(0);
    }
    setHistoryLoading(false);
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      if (activeTab === 'today') {
        await fetchPreview();
      } else {
        await fetchHistory();
      }
    } finally {
      setRefreshing(false);
    }
  };

  const handleProjectChange = (project) => {
    setSelectedProject(project);
    setShowProjectPicker(false);
  };

  const handleViewFullReport = async () => {
    if (!selectedProject) return;
    const projectId = selectedProject._id || selectedProject.id;
    try {
      if (Platform.OS === 'web') {
        const response = await apiClient.get(`/api/reports/project/${projectId}/date/${previewDate}`);
        const html = response.data;
        const newWindow = window.open('', '_blank');
        if (newWindow) {
          newWindow.document.write(html);
          newWindow.document.close();
        }
      } else {
        // On mobile, open report URL in device browser
        const baseURL = apiClient.defaults.baseURL || '';
        const token = await getToken();
        const url = `${baseURL}/api/reports/project/${projectId}/date/${previewDate}?token=${token || ''}`;
        await Linking.openURL(url);
      }
    } catch (err) {
      console.error('Failed to load report:', err);
      toast.error('Error', 'Could not load report');
    }
  };

  const handleDownloadPdf = async () => {
    if (!selectedProject) return;
    const projectId = selectedProject._id || selectedProject.id;
    try {
      if (Platform.OS === 'web') {
        const response = await apiClient.get(
          `/api/reports/project/${projectId}/date/${previewDate}/pdf`,
          { responseType: 'blob' }
        );
        const blob = new Blob([response.data], { type: 'application/pdf' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `LeveLog_Report_${selectedProject.name?.replace(/\s+/g, '_') || 'report'}_${previewDate}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast.success('Downloaded', 'PDF saved to your downloads');
      } else {
        // On mobile, open PDF URL in device browser (triggers native PDF viewer / download)
        const baseURL = apiClient.defaults.baseURL || '';
        const token = await getToken();
        const url = `${baseURL}/api/reports/project/${projectId}/date/${previewDate}/pdf?token=${token || ''}`;
        await Linking.openURL(url);
      }
    } catch (err) {
      console.error('Failed to download PDF:', err);
      toast.error('Error', 'Could not generate PDF');
    }
  };
  
  // Item 9 — native OS share sheet, token-safe. Downloads the PDF with the
  // auth token in the Authorization HEADER (never in the URL, so nothing
  // token-bearing is handed to the share sheet), then shares only the local
  // file. Requires expo-sharing's native module → active from the NEXT native
  // build, not an OTA update.
  const handleSharePdf = async () => {
    if (!selectedProject) return;
    const projectId = selectedProject._id || selectedProject.id;
    try {
      if (!(await Sharing.isAvailableAsync())) {
        toast.error('Unavailable', 'Sharing is not available on this device');
        return;
      }
      const baseURL = apiClient.defaults.baseURL || '';
      const token = await getToken();
      const safeName = selectedProject.name?.replace(/\s+/g, '_') || 'report';
      const target = `${FileSystem.cacheDirectory}LeveLog_Report_${safeName}_${previewDate}.pdf`;
      const { uri, status } = await FileSystem.downloadAsync(
        `${baseURL}/api/reports/project/${projectId}/date/${previewDate}/pdf`,
        target,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (status !== 200) {
        toast.error('Error', 'Could not generate PDF');
        return;
      }
      await Sharing.shareAsync(uri, {
        mimeType: 'application/pdf',
        UTI: 'com.adobe.pdf',
        dialogTitle: 'Share report',
      });
    } catch (err) {
      console.error('Failed to share PDF:', err);
      toast.error('Error', 'Could not share report');
    }
  };

  const navigateDate = (direction) => {
    const current = new Date(previewDate + 'T12:00:00');
    current.setDate(current.getDate() + direction);
    const newDate = current.toISOString().split('T')[0];
    // Don't go into the future
    const today = new Date().toISOString().split('T')[0];
    if (newDate > today) return;
    setPreviewDate(newDate);
  };

  const isToday = previewDate === new Date().toISOString().split('T')[0];

  const formatDate = (dateStr) => {
    const d = new Date(dateStr + 'T12:00:00');
    return d.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatDateTime = (isoStr) => {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'America/New_York',
    });
  };

  // ─── Render ──────────────────────────────────────────

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>DAILY FIELD</Text>
            <Text style={s.titleText}>Reports</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={60} borderRadiusValue={borderRadius.xxl} style={s.mb16} />
              <GlassSkeleton width="100%" height={280} borderRadiusValue={borderRadius.xxl} />
            </>
          ) : (
            <>
              {/* The project list failed to load — say so instead of showing an
                  empty picker that reads as "you have no projects". */}
              {projectsState !== 'ok' && (
                <OfflineNotice mode={projectsState} cachedCount={projects.length} />
              )}

              {/* Project Selector */}
              <Pressable
                style={s.selectorCard}
                onPress={() => setShowProjectPicker(!showProjectPicker)}
              >
                <View style={s.selectorContent}>
                  <IconPod size={44}>
                    <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>
                  <View>
                    <Text style={s.selectorLabel}>SELECT PROJECT</Text>
                    <Text style={s.selectorText}>
                      {selectedProject?.name || 'Choose a project'}
                    </Text>
                  </View>
                </View>
                <ChevronDown
                  size={20}
                  strokeWidth={1.5}
                  color={colors.text.muted}
                  style={showProjectPicker && s.iconRotated}
                />
              </Pressable>

              {showProjectPicker && (
                <View style={s.dropdown}>
                  {projects.map((project) => (
                    <Pressable
                      key={project._id || project.id}
                      style={[
                        s.dropdownItem,
                        (project._id || project.id) === (selectedProject?._id || selectedProject?.id) &&
                          s.dropdownItemActive,
                      ]}
                      onPress={() => handleProjectChange(project)}
                    >
                      <Text style={s.dropdownText}>{project.name}</Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* ════════════ TODAY'S PREVIEW TAB ════════════ */}
                <>
                  {/* Date Navigator */}
                  <View style={s.dateNav}>
                    <GlassButton
                      variant="icon"
                      icon={<ChevronLeft size={18} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={() => navigateDate(-1)}
                    />
                    <View style={s.dateCenter}>
                      <Calendar size={14} strokeWidth={1.5} color={colors.text.muted} />
                      <Text style={s.dateText}>{formatDate(previewDate)}</Text>
                      {isToday && (
                        <View style={s.liveBadge}>
                          <Text style={s.liveBadgeText}>LIVE</Text>
                        </View>
                      )}
                    </View>
                    <GlassButton
                      variant="icon"
                      icon={<ChevronRight size={18} strokeWidth={1.5} color={isToday ? colors.text.subtle : colors.text.primary} />}
                      onPress={() => navigateDate(1)}
                      disabled={isToday}
                    />
                  </View>

                  {previewLoading ? (
                    <View style={s.loadingBox}>
                      <ActivityIndicator size="small" color={colors.text.primary} />
                      <Text style={s.loadingLabel}>Loading preview...</Text>
                    </View>
                  ) : preview ? (
                    <>
                      {/* Summary Cards */}
                      <View style={s.summaryRow}>
                        <GlassCard style={s.summaryCard} contentStyle={s.summaryCardContent}>
                          <Users size={18} strokeWidth={1.5} color="#3b82f6" />
                          <Text style={s.summaryValue}>{preview.checkin_count}</Text>
                          <Text style={s.summaryLabel} numberOfLines={2}>Workers</Text>
                        </GlassCard>
                        <GlassCard style={s.summaryCard} contentStyle={s.summaryCardContent}>
                          <ClipboardList size={18} strokeWidth={1.5} color="#8b5cf6" />
                          <Text style={s.summaryValue}>{preview.logbooks?.length || 0}</Text>
                          <Text style={s.summaryLabel} numberOfLines={2}>Logbooks</Text>
                        </GlassCard>
                        <GlassCard style={s.summaryCard} contentStyle={s.summaryCardContent}>
                          <Building2 size={18} strokeWidth={1.5} color={semantic.neutral} />
                          <Text style={s.summaryValue}>{preview.subcontractor_count}</Text>
                          <Text style={s.summaryLabel} numberOfLines={2}>Subs</Text>
                        </GlassCard>
                      </View>

                      {/* Report Status */}
                      <GlassCard style={s.statusCard}>
                        <View style={s.statusHeader}>
                          <IconPod size={44}>
                            {preview.report_already_sent ? (
                              <CheckCircle size={20} strokeWidth={1.5} color={semantic.verified} />
                            ) : (
                              <Clock size={20} strokeWidth={1.5} color={semantic.attention} />
                            )}
                          </IconPod>
                          <View style={s.statusInfo}>
                            <Text style={s.statusTitle}>
                              {preview.report_already_sent ? 'Report Sent' : isToday ? 'Report Pending' : 'Report Status'}
                            </Text>
                            <Text style={s.statusSubtitle}>
                              {preview.report_already_sent
                                ? `Sent ${formatDateTime(preview.report_sent_at)}`
                                : isToday
                                  ? `Scheduled for ${preview.report_send_time || '18:00'} EST`
                                  : preview.report_already_sent === false ? 'Not sent' : 'No data'}
                            </Text>
                          </View>
                        </View>

                        {preview.report_email_list?.length > 0 && (
                          <View style={s.recipientsList}>
                            <View style={s.recipientsHeader}>
                              <Mail size={12} strokeWidth={1.5} color={colors.text.muted} />
                              <Text style={s.recipientsLabel}>
                                {preview.report_email_list.length} recipient{preview.report_email_list.length !== 1 ? 's' : ''}
                              </Text>
                            </View>
                            {preview.report_email_list.map((email, i) => (
                              <Text key={i} style={s.recipientEmail}>{email}</Text>
                            ))}
                          </View>
                        )}
                      </GlassCard>

                      {/* Logbook Details */}
                      <GlassCard style={s.logbooksCard}>
                        <Text style={s.sectionTitle}>Logbook Status</Text>
                        {preview.logbooks && preview.logbooks.length > 0 ? (
                          preview.logbooks.map((lb, i) => (
                            <View key={i} style={s.logbookRow}>
                              <View style={s.logbookInfo}>
                                <Text style={s.logbookType}>
                                  {LOG_TYPE_LABELS[lb.log_type] || lb.log_type}
                                </Text>
                                {lb.cp_name && (
                                  <Text style={s.logbookCp}>By {lb.cp_name}</Text>
                                )}
                              </View>
                              <View style={[
                                s.statusBadge,
                                lb.status === 'submitted' ? s.statusBadgeSubmitted : s.statusBadgeDraft,
                              ]}>
                                <Text style={[
                                  s.statusBadgeText,
                                  lb.status === 'submitted' ? s.statusBadgeTextSubmitted : s.statusBadgeTextDraft,
                                ]}>
                                  {lb.status === 'submitted' ? 'Submitted' : 'Draft'}
                                </Text>
                              </View>
                            </View>
                          ))
                        ) : (
                          <View style={s.emptyState}>
                            <AlertCircle size={20} strokeWidth={1.5} color={colors.text.subtle} />
                            <Text style={s.emptyText}>No logbooks filed yet for this date</Text>
                          </View>
                        )}

                        {/* Daily Log Status */}
                        <View style={[s.logbookRow, { marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: withAlpha('#ffffff', 0.06), paddingTop: spacing.sm }]}>
                          <View style={s.logbookInfo}>
                            <Text style={s.logbookType}>Daily Site Log</Text>
                            {preview.daily_log_weather && (
                              <Text style={s.logbookCp}>{preview.daily_log_weather} — {preview.daily_log_worker_count} workers</Text>
                            )}
                          </View>
                          <View style={[
                            s.statusBadge,
                            preview.has_daily_log ? s.statusBadgeSubmitted : s.statusBadgeDraft,
                          ]}>
                            <Text style={[
                              s.statusBadgeText,
                              preview.has_daily_log ? s.statusBadgeTextSubmitted : s.statusBadgeTextDraft,
                            ]}>
                              {preview.has_daily_log ? (preview.daily_log_status || 'Saved') : 'Not Started'}
                            </Text>
                          </View>
                        </View>
                      </GlassCard>

                      {/* View Full Report Button */}
                      <GlassButton
                        title={isToday ? 'Preview Full Report (So Far)' : 'View Full Report'}
                        icon={<Eye size={18} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={handleViewFullReport}
                        style={s.previewBtn}
                      />
                      <GlassButton
                        title="Download as PDF"
                        icon={<Download size={18} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={handleDownloadPdf}
                        style={s.previewBtn}
                      />
                      {Platform.OS !== 'web' && (
                        <GlassButton
                          title="Share Report"
                          icon={<Share2 size={18} strokeWidth={1.5} color={colors.text.primary} />}
                          onPress={handleSharePdf}
                          style={s.previewBtn}
                        />
                      )}
                    </>
                  ) : previewState !== 'ok' ? (
                    /* The preview FETCH failed. "No Data Available" would
                       assert the day has no report — the exact lie this
                       screen must not tell. */
                    <OfflineNotice
                      mode={previewState}
                      detail={
                        previewState === 'offline'
                          ? `Can't reach the server, so the report for ${formatDate(previewDate)} is unknown. Reconnect and pull to refresh.`
                          : `Could not read the report for ${formatDate(previewDate)}. Pull to refresh or try again.`
                      }
                    />
                  ) : (
                    <GlassCard style={s.emptyCard}>
                      <AlertCircle size={28} strokeWidth={1.5} color={colors.text.subtle} />
                      <Text style={s.emptyTitle}>No Data Available</Text>
                      <Text style={s.emptySubtitle}>
                        No report data found for {formatDate(previewDate)}
                      </Text>
                    </GlassCard>
                  )}
                </>
            </>
          )}
        </ScrollView>

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
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.08),
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
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
    titleSection: {
      marginBottom: spacing.xl,
    },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 48,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -1,
    },
    mb16: {
      marginBottom: spacing.md,
    },

    // ── Project Selector ──
    selectorCard: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: spacing.md,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
      marginBottom: spacing.sm,
    },
    selectorContent: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    selectorLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: 2,
    },
    selectorText: {
      fontSize: 16,
      color: colors.text.primary,
      fontWeight: '500',
    },
    iconRotated: {
      transform: [{ rotate: '180deg' }],
    },
    dropdown: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
      marginBottom: spacing.md,
      overflow: 'hidden',
    },
    dropdownItem: {
      padding: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.05),
    },
    dropdownItemActive: {
      backgroundColor: 'rgba(59, 130, 246, 0.15)',
    },
    dropdownText: {
      fontSize: 15,
      color: colors.text.primary,
    },

    // ── Tabs ──
    tabRow: {
      flexDirection: 'row',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: 4,
      marginBottom: spacing.lg,
    },
    tab: {
      flex: 1,
      paddingVertical: spacing.sm + 2,
      alignItems: 'center',
      borderRadius: borderRadius.lg,
    },
    tabActive: {
      backgroundColor: 'rgba(59, 130, 246, 0.2)',
      borderWidth: 1,
      borderColor: 'rgba(59, 130, 246, 0.3)',
    },
    tabText: {
      fontSize: 13,
      fontWeight: '600',
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    tabTextActive: {
      color: '#60a5fa',
    },

    // ── Date Navigator ──
    dateNav: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.md,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    dateCenter: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    dateText: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
    },
    liveBadge: {
      backgroundColor: semantic.verifiedBg,
      borderRadius: borderRadius.full,
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderWidth: 1,
      borderColor: semantic.verifiedBorder,
    },
    liveBadgeText: {
      fontSize: 10,
      fontWeight: '700',
      color: '#4ade80',
      letterSpacing: 1,
    },

    // ── Summary Row ──
    summaryRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginBottom: spacing.md,
    },
    summaryCard: {
      flex: 1,
    },
    // Summary bubble insets. Two separate causes were clipping the labels:
    //   1. GlassCard's default cardContent padding is spacing.xl (32) per side —
    //      64px of inset on a ~104px card, leaving ~40px of text box.
    //   2. `adjustsFontSizeToFit` + numberOfLines={1}: on Android RN measures the
    //      auto-shrunk line against a near-zero width and truncates to the first
    //      glyph, which is why even "Subs" (4 chars, trivially fits) rendered as
    //      "S…". Removed — the labels fit at their natural size, see math below.
    //
    // Width math @ 375px (iPhone SE2/12 mini/13 mini):
    //   375 − scrollContent padding (spacing.lg × 2 = 48)            = 327
    //   327 − summaryRow gaps (spacing.sm × 2 = 16)                  = 311
    //   311 ÷ 3 cards                                                = 103.6 per card
    //   103.6 − summaryCardContent paddingHorizontal (spacing.xs × 2 = 8) = 95.6 usable
    // Longest label "LOGBOOKS" = 8 caps @ 11px semibold ≈ 8 × 7.5 = 60px. Fits.
    // Worst case @ 320px (SE 1st gen): (320−48−16)/3 = 85.3 − 8 = 77.3 usable — still fits.
    // numberOfLines={2} is the safety net for large accessibility font scales:
    // the label wraps instead of ellipsising.
    summaryCardContent: {
      alignItems: 'center',
      paddingVertical: spacing.md,
      paddingHorizontal: spacing.xs,
      gap: spacing.xs,
    },
    summaryValue: {
      fontSize: 24,
      fontWeight: '300',
      color: colors.text.primary,
    },
    summaryLabel: {
      // alignSelf:'stretch' is deliberate — the parent is alignItems:'center',
      // so without it the Text box shrink-wraps; stretching gives the label the
      // FULL 95.6px content width to lay out in.
      alignSelf: 'stretch',
      fontSize: 11,
      lineHeight: 14,
      fontWeight: '600',
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0,
      textAlign: 'center',
    },

    // ── Status Card ──
    statusCard: {
      padding: spacing.lg,
      marginBottom: spacing.md,
    },
    statusHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      marginBottom: spacing.md,
    },
    statusInfo: {
      flex: 1,
    },
    statusTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    statusSubtitle: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 2,
    },
    recipientsList: {
      backgroundColor: withAlpha('#ffffff', 0.03),
      borderRadius: borderRadius.md,
      padding: spacing.sm,
    },
    recipientsHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      marginBottom: spacing.xs,
    },
    recipientsLabel: {
      fontSize: 11,
      fontWeight: '600',
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    recipientEmail: {
      fontSize: 13,
      color: colors.text.secondary,
      paddingVertical: 2,
      paddingLeft: spacing.md + spacing.xs,
    },

    // ── Logbooks Card ──
    logbooksCard: {
      padding: spacing.lg,
      marginBottom: spacing.md,
    },
    sectionTitle: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.text.primary,
      marginBottom: spacing.md,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    logbookRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.sm,
    },
    logbookInfo: {
      flex: 1,
    },
    logbookType: {
      fontSize: 14,
      color: colors.text.primary,
      fontWeight: '500',
    },
    logbookCp: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    statusBadge: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 3,
      borderRadius: borderRadius.sm,
    },
    statusBadgeSubmitted: {
      backgroundColor: semantic.verifiedBg,
    },
    statusBadgeDraft: {
      backgroundColor: semantic.attentionBg,
    },
    statusBadgeText: {
      fontSize: 11,
      fontWeight: '600',
    },
    statusBadgeTextSubmitted: {
      color: semantic.verified,
    },
    statusBadgeTextDraft: {
      color: '#fbbf24',
    },

    // ── Preview Button ──
    previewBtn: {
      marginBottom: spacing.md,
    },

    // ── Empty States ──
    emptyState: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingVertical: spacing.md,
    },
    emptyText: {
      fontSize: 13,
      color: colors.text.subtle,
    },
    emptyCard: {
      alignItems: 'center',
      padding: spacing.xl,
      gap: spacing.sm,
    },
    emptyTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    emptySubtitle: {
      fontSize: 13,
      color: colors.text.muted,
      textAlign: 'center',
      lineHeight: 18,
    },

    // ── Loading ──
    loadingBox: {
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.sm,
    },
    loadingLabel: {
      fontSize: 13,
      color: colors.text.muted,
    },

    // ── History Tab ──
    historyList: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
      overflow: 'hidden',
    },
    historyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      padding: spacing.lg,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.06),
    },
    historyTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    historySubtitle: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    historyItem: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: spacing.md,
      paddingLeft: spacing.lg,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.04),
    },
    historyItemLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      flex: 1,
    },
    historyDateBadge: {
      width: 44,
      height: 44,
      borderRadius: borderRadius.md,
      backgroundColor: 'rgba(59, 130, 246, 0.1)',
      borderWidth: 1,
      borderColor: 'rgba(59, 130, 246, 0.2)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    historyDateDay: {
      fontSize: 16,
      fontWeight: '600',
      color: '#60a5fa',
      lineHeight: 18,
    },
    historyDateMonth: {
      fontSize: 9,
      fontWeight: '700',
      color: '#60a5fa',
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    historyItemInfo: {
      flex: 1,
    },
    historyItemDate: {
      fontSize: 14,
      color: colors.text.primary,
      fontWeight: '500',
    },
    historyMeta: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      marginTop: 3,
    },
    historyMetaText: {
      fontSize: 11,
      color: colors.text.subtle,
    },
  });
}
