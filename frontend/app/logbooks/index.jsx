import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  LogOut,
  ClipboardList,
  HardHat,
  ShieldCheck,
  Users,
  BookOpen,
  Building2,
  ChevronRight,
  CheckCircle,
  ChevronDown,
  Calendar,
  Bell,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import CpNav from '../../src/components/CpNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { projectsAPI, logbooksAPI, cpProfileAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';

const LOG_TYPES = [
  {
    key: 'daily_jobsite',
    label: 'Daily Jobsite Log',
    subtitle: 'NYC DOB 3301-02 — Daily',
    icon: Building2,
    color: '#ef4444',
    bg: 'rgba(239, 68, 68, 0.15)',
    visibility: 'always',
  },
  {
    key: 'preshift_signin',
    label: 'Pre-Shift Safety Meeting',
    subtitle: 'Daily sign-in with all workers',
    icon: Users,
    color: '#4ade80',
    bg: 'rgba(74, 222, 128, 0.15)',
    visibility: 'always',
  },
  {
    key: 'scaffold_maintenance',
    label: 'Scaffold Maintenance Log',
    subtitle: 'NYC DOB — Daily while scaffold is up',
    icon: HardHat,
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.15)',
    visibility: 'scaffold',
  },
  {
    key: 'toolbox_talk',
    label: 'Tool Box Talk',
    subtitle: 'OSHA — Weekly per company',
    icon: BookOpen,
    color: '#3b82f6',
    bg: 'rgba(59, 130, 246, 0.15)',
    visibility: 'weekly',
  },
  {
    key: 'subcontractor_orientation',
    label: 'Subcontractor Safety Orientation',
    subtitle: 'First-time workers only',
    icon: ShieldCheck,
    color: '#8b5cf6',
    bg: 'rgba(139, 92, 246, 0.15)',
    visibility: 'first_time',
  },
  {
    key: 'osha_log',
    label: 'OSHA Log Book',
    subtitle: 'Worker certifications register',
    icon: ClipboardList,
    color: '#06b6d4',
    bg: 'rgba(6, 182, 212, 0.15)',
    visibility: 'always',
  },
];

export default function LogBooksScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, colors } = useTheme();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [todayLogs, setTodayLogs] = useState({});
  const [notifications, setNotifications] = useState({ missing_toolbox_talk: [], unsigned_orientations: 0 });
  const [cpName, setCpName] = useState('');
  const [scaffoldActive, setScaffoldActive] = useState(false);
  const [toolboxDoneThisWeek, setToolboxDoneThisWeek] = useState(false);

  const today = new Date().toISOString().split('T')[0];
  const todayFormatted = new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });

  const styles = buildStyles(colors, isDark);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) fetchInitial();
  }, [isAuthenticated]);

  const fetchInitial = async () => {
    setLoading(true);
    try {
      const projectsData = await projectsAPI.getAll().catch(() => []);
      const projectList = Array.isArray(projectsData) ? projectsData : [];
      setProjects(projectList);

      cpProfileAPI.getProfile()
        .then(p => { if (p?.cp_name) setCpName(p.cp_name); })
        .catch(() => {});

      const assigned = projectList.filter(p =>
        !user?.assigned_projects?.length ||
        user.assigned_projects.includes(p.id || p._id)
      );
      if (assigned.length > 0) {
        setSelectedProject(assigned[0]);
        await fetchProjectData(assigned[0]._id || assigned[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch logbooks data:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchProjectData = async (projectId) => {
    try {
      const [logs, notifs, scaffoldInfo] = await Promise.all([
        logbooksAPI.getByProject(projectId, null, today).catch(() => []),
        logbooksAPI.getNotifications(projectId).catch(() => ({ missing_toolbox_talk: [], unsigned_orientations: 0 })),
        logbooksAPI.getScaffoldInfo(projectId).catch(() => null),
      ]);

      const logMap = {};
      (Array.isArray(logs) ? logs : []).forEach(log => { logMap[log.log_type] = log; });
      setTodayLogs(logMap);
      setNotifications(notifs);

      const isScaffoldUp = scaffoldInfo?.scaffold_erected === true
        || (scaffoldInfo?.scaffold_erector && scaffoldInfo?.scaffold_erected !== false)
        || false;
      setScaffoldActive(isScaffoldUp);
      setToolboxDoneThisWeek(logMap['toolbox_talk']?.status === 'submitted');
    } catch (error) {
      console.error('Failed to fetch project logbooks:', error);
    }
  };

  const handleProjectSelect = async (project) => {
    setSelectedProject(project);
    setShowProjectPicker(false);
    setTodayLogs({});
    await fetchProjectData(project._id || project.id);
  };

  const handleOpenLog = (logType) => {
    if (!selectedProject) {
      toast.warning('Select Project', 'Please select a project first');
      return;
    }
    const projectId = selectedProject._id || selectedProject.id;
    router.push(`/logbooks/${logType}?projectId=${projectId}&date=${today}`);
  };

  const getLogStatus = (logTypeKey) => {
    const log = todayLogs[logTypeKey];
    if (!log) return 'pending';
    if (log.status === 'submitted') return 'submitted';
    return 'draft';
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleToggleScaffold = async () => {
    if (!selectedProject) return;
    const projectId = selectedProject._id || selectedProject.id;
    const next = !scaffoldActive;
    setScaffoldActive(next);
    try {
      await logbooksAPI.saveScaffoldInfo(projectId, { scaffold_erected: next });
      toast.success(
        next ? 'Scaffold Active' : 'Scaffold Removed',
        next ? 'Scaffold log will now appear daily' : 'Scaffold log hidden until re-activated',
      );
    } catch (e) {
      setScaffoldActive(!next);
      toast.error('Error', 'Could not update scaffold status');
    }
  };

  const getVisibleLogTypes = () => {
    return LOG_TYPES.filter((lt) => {
      switch (lt.visibility) {
        case 'always': return true;
        case 'scaffold': return scaffoldActive;
        case 'weekly': return !toolboxDoneThisWeek;
        case 'first_time': {
          const hasUnsigned = (notifications?.unsigned_orientations || 0) > 0;
          const notSubmittedToday = todayLogs['subcontractor_orientation']?.status !== 'submitted';
          return hasUnsigned || notSubmittedToday;
        }
        default: return true;
      }
    });
  };

  const missingToolbox = notifications?.missing_toolbox_talk || [];
  const visibleLogs = getVisibleLogTypes();

  const StatusBadge = ({ status }) => {
    if (status === 'submitted') {
      return (
        <View style={[styles.badge, styles.badgeSubmitted]}>
          <CheckCircle size={12} strokeWidth={2} color="#4ade80" />
          <Text style={[styles.badgeText, styles.badgeTextSubmitted]}>Done</Text>
        </View>
      );
    }
    if (status === 'draft') {
      return (
        <View style={[styles.badge, styles.badgeDraft]}>
          <Text style={[styles.badgeText, styles.badgeTextDraft]}>Draft</Text>
        </View>
      );
    }
    return (
      <View style={[styles.badge, styles.badgePending]}>
        <Text style={[styles.badgeText, styles.badgeTextPending]}>Pending</Text>
      </View>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.logoText}>BLUEVIEW</Text>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* ═══ SINGLE HERO CARD: title + CP banner + project + scaffold ═══ */}
          <GlassCard style={styles.heroCard}>
            {/* Title section */}
            <Text style={styles.titleLabel}>COMPLIANCE</Text>
            <Text style={styles.titleText}>Log Books</Text>
            <View style={styles.dateRow}>
              <Calendar size={14} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.dateText}>{todayFormatted}</Text>
            </View>

            {/* CP name banner */}
            {cpName ? (
              <View style={styles.cpBannerRow}>
                <ShieldCheck size={16} strokeWidth={1.5} color="#3b82f6" />
                <Text style={styles.cpBannerText}>
                  Signing as <Text style={styles.cpBannerName}>{cpName}</Text>
                </Text>
              </View>
            ) : null}

            {/* Divider */}
            <View style={styles.heroDivider} />

            {/* Project selector */}
            <Pressable
              style={styles.projectSelector}
              onPress={() => setShowProjectPicker(!showProjectPicker)}
            >
              <View style={styles.projectSelectorLeft}>
                <IconPod size={40}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                </IconPod>
                <View>
                  <Text style={styles.projectSelectorLabel}>PROJECT</Text>
                  <Text style={styles.projectSelectorName}>
                    {selectedProject?.name || 'Select a project'}
                  </Text>
                </View>
              </View>
              <ChevronDown
                size={18}
                strokeWidth={1.5}
                color={colors.text.muted}
                style={{ transform: [{ rotate: showProjectPicker ? '180deg' : '0deg' }] }}
              />
            </Pressable>

            {/* Project dropdown — inside the hero card */}
            {showProjectPicker && (
              <View style={styles.projectDropdown}>
                {projects.map((p) => (
                  <Pressable
                    key={p._id || p.id}
                    style={[
                      styles.projectOption,
                      (p._id || p.id) === (selectedProject?._id || selectedProject?.id) &&
                        styles.projectOptionActive,
                    ]}
                    onPress={() => handleProjectSelect(p)}
                  >
                    <Text style={styles.projectOptionText}>{p.name}</Text>
                    {(p._id || p.id) === (selectedProject?._id || selectedProject?.id) && (
                      <CheckCircle size={16} strokeWidth={1.5} color="#4ade80" />
                    )}
                  </Pressable>
                ))}
              </View>
            )}

            {/* Scaffold toggle — inside the hero card */}
            {selectedProject && (
              <>
                <View style={styles.heroDivider} />
                <View style={styles.scaffoldToggleRow}>
                  <HardHat size={18} strokeWidth={1.5} color="#f59e0b" />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.scaffoldToggleTitle}>Scaffolding / Overhead Shed</Text>
                    <Text style={styles.scaffoldToggleDesc}>
                      {scaffoldActive
                        ? 'Active — daily inspection required'
                        : 'Not active — toggle ON when erected'}
                    </Text>
                  </View>
                  <Pressable
                    onPress={handleToggleScaffold}
                    style={[styles.toggleBtn, scaffoldActive && styles.toggleBtnActive]}
                  >
                    <Text style={[styles.toggleBtnText, scaffoldActive && styles.toggleBtnTextActive]}>
                      {scaffoldActive ? 'ON' : 'N/A'}
                    </Text>
                  </Pressable>
                </View>
              </>
            )}
          </GlassCard>

          {/* Missing toolbox talk alert */}
          {missingToolbox.length > 0 && (
            <GlassCard style={styles.notifCard}>
              <View style={styles.notifHeader}>
                <Bell size={16} strokeWidth={1.5} color="#f59e0b" />
                <Text style={styles.notifTitle}>
                  {missingToolbox.length} worker{missingToolbox.length > 1 ? 's' : ''} missing Tool Box Talk this week
                </Text>
              </View>
              {missingToolbox.slice(0, 3).map((w, i) => (
                <Text key={i} style={styles.notifWorker}>• {w.worker_name} ({w.company})</Text>
              ))}
              {missingToolbox.length > 3 && (
                <Text style={styles.notifMore}>+{missingToolbox.length - 3} more</Text>
              )}
              <GlassButton
                title="Open Tool Box Talk"
                onPress={() => handleOpenLog('toolbox_talk')}
                style={styles.notifBtn}
              />
            </GlassCard>
          )}

          {/* Log book cards */}
          {loading ? (
            <View style={styles.loadingCenter}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={styles.loadingText}>Loading log books...</Text>
            </View>
          ) : (
            <View style={styles.logList}>
              <Text style={styles.sectionLabel}>TODAY'S LOG BOOKS</Text>

              {visibleLogs.length === 0 ? (
                <GlassCard style={styles.emptyCard}>
                  <CheckCircle size={32} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.emptyText}>All caught up! No logbooks needed right now.</Text>
                </GlassCard>
              ) : (
                visibleLogs.map((logType) => {
                  const Icon = logType.icon;
                  const status = getLogStatus(logType.key);
                  return (
                    <Pressable
                      key={logType.key}
                      onPress={() => handleOpenLog(logType.key)}
                      style={({ pressed }) => [styles.logCard, pressed && styles.logCardPressed]}
                    >
                      <View style={[styles.logIcon, { backgroundColor: logType.bg }]}>
                        <Icon size={22} strokeWidth={1.5} color={logType.color} />
                      </View>
                      <View style={styles.logInfo}>
                        <Text style={styles.logLabel}>{logType.label}</Text>
                        <Text style={styles.logSubtitle}>{logType.subtitle}</Text>
                      </View>
                      <View style={styles.logRight}>
                        <StatusBadge status={status} />
                        <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
                      </View>
                    </Pressable>
                  );
                })
              )}

              {toolboxDoneThisWeek && (
                <Pressable
                  onPress={() => handleOpenLog('toolbox_talk')}
                  style={({ pressed }) => [styles.logCard, styles.logCardDone, pressed && styles.logCardPressed]}
                >
                  <View style={[styles.logIcon, { backgroundColor: 'rgba(59, 130, 246, 0.15)' }]}>
                    <BookOpen size={22} strokeWidth={1.5} color="#3b82f6" />
                  </View>
                  <View style={styles.logInfo}>
                    <Text style={styles.logLabel}>Tool Box Talk</Text>
                    <Text style={styles.logSubtitle}>Completed this week</Text>
                  </View>
                  <View style={styles.logRight}>
                    <StatusBadge status="submitted" />
                    <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
                  </View>
                </Pressable>
              )}
            </View>
          )}

          {/* Completion bar */}
          {!loading && selectedProject && (
            <GlassCard style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>Today's Completion</Text>
              <View style={styles.summaryRow}>
                {(() => {
                  const submitted = LOG_TYPES.filter(lt => getLogStatus(lt.key) === 'submitted').length;
                  const total = visibleLogs.length;
                  const pct = total > 0 ? Math.round((submitted / total) * 100) : 0;
                  return (
                    <>
                      <View style={styles.summaryBar}>
                        <View style={[styles.summaryBarFill, { width: `${pct}%` }]} />
                      </View>
                      <Text style={styles.summaryCount}>{submitted}/{total}</Text>
                    </>
                  );
                })()}
              </View>
            </GlassCard>
          )}
        </ScrollView>

        <CpNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  const divider = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)';

  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    },
    logoText: {
      ...typography.label, fontSize: 18, color: colors.text.primary, letterSpacing: 6,
    },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },

    // ── Hero card (single merged card) ──
    heroCard: { marginBottom: spacing.md },
    titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
    titleText: { fontSize: 32, fontWeight: '200', color: colors.text.primary, marginBottom: spacing.xs },
    dateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    dateText: { fontSize: 13, color: colors.text.muted },

    cpBannerRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      marginTop: spacing.md,
    },
    cpBannerText: { fontSize: 14, color: colors.text.secondary },
    cpBannerName: { color: colors.text.primary, fontWeight: '500' },

    heroDivider: {
      height: 1, backgroundColor: divider,
      marginVertical: spacing.md,
    },

    projectSelector: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: spacing.sm,
    },
    projectSelectorLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    projectSelectorLabel: { ...typography.label, color: colors.text.muted, marginBottom: 2 },
    projectSelectorName: { fontSize: 15, color: colors.text.primary, fontWeight: '500' },
    projectDropdown: {
      marginTop: spacing.sm, borderRadius: borderRadius.lg, overflow: 'hidden',
      borderWidth: 1, borderColor: divider,
    },
    projectOption: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      padding: spacing.md,
      borderBottomWidth: 1, borderBottomColor: divider,
    },
    projectOptionActive: { backgroundColor: 'rgba(59, 130, 246, 0.1)' },
    projectOptionText: { fontSize: 15, color: colors.text.primary },

    // ── Scaffold toggle (inside hero card) ──
    scaffoldToggleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    scaffoldToggleTitle: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    scaffoldToggleDesc: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    toggleBtn: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: colors.border.medium,
      backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
    },
    toggleBtnActive: {
      backgroundColor: 'rgba(245, 158, 11, 0.2)',
      borderColor: 'rgba(245, 158, 11, 0.5)',
    },
    toggleBtnText: { fontSize: 12, fontWeight: '600', color: colors.text.muted },
    toggleBtnTextActive: { color: '#f59e0b' },

    notifCard: {
      marginBottom: spacing.md, padding: spacing.md,
      backgroundColor: 'rgba(245, 158, 11, 0.08)', borderColor: 'rgba(245, 158, 11, 0.25)',
    },
    notifHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
    notifTitle: { fontSize: 14, fontWeight: '500', color: '#f59e0b', flex: 1 },
    notifWorker: { fontSize: 13, color: colors.text.secondary, marginBottom: 2, paddingLeft: spacing.sm },
    notifMore: { fontSize: 12, color: colors.text.muted, paddingLeft: spacing.sm, marginBottom: spacing.sm },
    notifBtn: { marginTop: spacing.sm },

    loadingCenter: { alignItems: 'center', paddingVertical: spacing.xxl, gap: spacing.md },
    loadingText: { fontSize: 14, color: colors.text.muted },
    sectionLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.md, marginTop: spacing.sm },
    logList: { gap: spacing.sm, marginBottom: spacing.lg },

    logCard: {
      flexDirection: 'row', alignItems: 'center',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1, borderColor: colors.glass.border,
      padding: spacing.md, gap: spacing.md,
    },
    logCardDone: { opacity: 0.5 },
    logCardPressed: { opacity: 0.8 },
    logIcon: { width: 48, height: 48, borderRadius: borderRadius.lg, alignItems: 'center', justifyContent: 'center' },
    logInfo: { flex: 1 },
    logLabel: { fontSize: 15, fontWeight: '500', color: colors.text.primary, marginBottom: 2 },
    logSubtitle: { fontSize: 12, color: colors.text.muted },
    logRight: { alignItems: 'flex-end', gap: spacing.xs },

    badge: {
      flexDirection: 'row', alignItems: 'center', gap: 4,
      paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: borderRadius.full,
    },
    badgeSubmitted: { backgroundColor: 'rgba(74, 222, 128, 0.15)' },
    badgeDraft: { backgroundColor: 'rgba(251, 191, 36, 0.15)' },
    badgePending: { backgroundColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)' },
    badgeText: { fontSize: 11, fontWeight: '500' },
    badgeTextSubmitted: { color: '#4ade80' },
    badgeTextDraft: { color: '#fbbf24' },
    badgeTextPending: { color: colors.text.muted },

    emptyCard: { alignItems: 'center', padding: spacing.xl, gap: spacing.md },
    emptyText: { fontSize: 14, color: colors.text.muted, textAlign: 'center' },

    summaryCard: { padding: spacing.md },
    summaryTitle: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.sm },
    summaryRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    summaryBar: {
      flex: 1, height: 6,
      backgroundColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
      borderRadius: 3, overflow: 'hidden',
    },
    summaryBarFill: { height: '100%', backgroundColor: '#4ade80', borderRadius: 3 },
    summaryCount: { fontSize: 14, fontWeight: '500', color: colors.text.secondary },
  });
}
