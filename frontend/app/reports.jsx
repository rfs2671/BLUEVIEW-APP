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
  LogOut,
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
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { projectsAPI, dailyLogsAPI, reportsAPI } from '../src/utils/api';
import apiClient from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

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
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('today');
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);

  // Today's preview
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewDate, setPreviewDate] = useState(new Date().toISOString().split('T')[0]);

  // History
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);

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
    try {
      const projectsData = await projectsAPI.getAll().catch(() => []);
      const projectList = Array.isArray(projectsData) ? projectsData : [];
      setProjects(projectList);
      if (projectList.length > 0) {
        setSelectedProject(projectList[0]);
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      toast.error('Load Error', 'Could not load projects');
    } finally {
      setLoading(false);
    }
  };

  const fetchPreview = async () => {
    if (!selectedProject) return;
    setPreviewLoading(true);
    try {
      const projectId = selectedProject._id || selectedProject.id;
      const data = await reportsAPI.getPreview(projectId, previewDate);
      setPreview(data);
    } catch (error) {
      console.error('Failed to fetch preview:', error);
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const fetchHistory = async () => {
    if (!selectedProject) return;
    setHistoryLoading(true);
    try {
      const projectId = selectedProject._id || selectedProject.id;
      const data = await reportsAPI.getHistory(projectId, 30, 0);
      setHistory(data.history || []);
      setHistoryTotal(data.total || 0);
    } catch (error) {
      console.error('Failed to fetch history:', error);
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
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
      const response = await apiClient.get(`/api/reports/project/${projectId}/date/${previewDate}`);
      const html = response.data;
      if (Platform.OS === 'web') {
        const newWindow = window.open('', '_blank');
        if (newWindow) {
          newWindow.document.write(html);
          newWindow.document.close();
        }
      } else {
        toast.success('Report Loaded', 'Use the browser to view full reports');
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
      const response = await apiClient.get(`/api/reports/project/${projectId}/date/${previewDate}`);
      const html = response.data;
      if (Platform.OS === 'web') {
        const printWindow = window.open('', '_blank');
        if (printWindow) {
          printWindow.document.write(html);
          printWindow.document.close();
          // Wait for content to load then trigger print (Save as PDF)
          printWindow.onload = () => printWindow.print();
          // Fallback if onload doesn't fire
          setTimeout(() => printWindow.print(), 1000);
        }
      } else {
        toast.info('PDF', 'Open the report in browser and use Print > Save as PDF');
      }
    } catch (err) {
      console.error('Failed to download PDF:', err);
      toast.error('Error', 'Could not generate PDF');
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

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

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
            <Text style={s.logoText}>BLUEVIEW</Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
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
                        <GlassCard style={s.summaryCard}>
                          <Users size={18} strokeWidth={1.5} color="#3b82f6" />
                          <Text style={s.summaryValue}>{preview.checkin_count}</Text>
                          <Text style={s.summaryLabel}>Workers On Site</Text>
                        </GlassCard>
                        <GlassCard style={s.summaryCard}>
                          <ClipboardList size={18} strokeWidth={1.5} color="#8b5cf6" />
                          <Text style={s.summaryValue}>{preview.logbooks?.length || 0}</Text>
                          <Text style={s.summaryLabel}>Logbooks Filed</Text>
                        </GlassCard>
                        <GlassCard style={s.summaryCard}>
                          <Building2 size={18} strokeWidth={1.5} color="#f59e0b" />
                          <Text style={s.summaryValue}>{preview.subcontractor_count}</Text>
                          <Text style={s.summaryLabel}>Subcontractors</Text>
                        </GlassCard>
                      </View>

                      {/* Report Status */}
                      <GlassCard style={s.statusCard}>
                        <View style={s.statusHeader}>
                          <IconPod size={44}>
                            {preview.report_already_sent ? (
                              <CheckCircle size={20} strokeWidth={1.5} color="#4ade80" />
                            ) : (
                              <Clock size={20} strokeWidth={1.5} color="#f59e0b" />
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
                        <View style={[s.logbookRow, { marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)', paddingTop: spacing.sm }]}>
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
                    </>
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
      borderBottomColor: 'rgba(255, 255, 255, 0.08)',
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
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
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
      borderBottomColor: 'rgba(255,255,255,0.05)',
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
      backgroundColor: 'rgba(74, 222, 128, 0.2)',
      borderRadius: borderRadius.full,
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderWidth: 1,
      borderColor: 'rgba(74, 222, 128, 0.3)',
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
      alignItems: 'center',
      padding: spacing.md,
      gap: spacing.xs,
    },
    summaryValue: {
      fontSize: 24,
      fontWeight: '300',
      color: colors.text.primary,
    },
    summaryLabel: {
      fontSize: 10,
      fontWeight: '600',
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
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
      backgroundColor: 'rgba(255,255,255,0.03)',
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
      backgroundColor: 'rgba(74, 222, 128, 0.15)',
    },
    statusBadgeDraft: {
      backgroundColor: 'rgba(251, 191, 36, 0.15)',
    },
    statusBadgeText: {
      fontSize: 11,
      fontWeight: '600',
    },
    statusBadgeTextSubmitted: {
      color: '#4ade80',
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
      borderBottomColor: 'rgba(255,255,255,0.06)',
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
      borderBottomColor: 'rgba(255,255,255,0.04)',
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
