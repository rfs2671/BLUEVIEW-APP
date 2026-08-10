import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ClipboardList,
  FolderOpen,
  UserCheck,
  Building2,
  PenTool,
  LogOut,
  Lock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useAuth } from '../../src/context/AuthContext';
import { useInspectorLock } from '../../src/context/InspectorLockContext';
import { dailyLogsAPI, checkinsAPI } from '../../src/utils/api';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch } from '../../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import { easternToday } from '../../src/utils/dates';

export default function SiteDeviceHomeScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject, logout } = useAuth();
  const { isLocked, lock } = useInspectorLock();

  const [todayLogsCount, setTodayLogsCount] = useState(0);
  const [workersOnSite, setWorkersOnSite] = useState(0);
  const [loading, setLoading] = useState(true);
  // OFFLINE vs EMPTY. Both badges below are gated on `count > 0`, so a failed
  // fetch used to make them silently VANISH — on a kiosk that reads as "no logs
  // today / nobody on site", a confident zero the app never actually saw.
  // 'ok' | 'offline' | 'error', tracked per fetch.
  const [logsState, setLogsState] = useState('ok');
  const [workersState, setWorkersState] = useState('ok');

  // Redirect if not authenticated or not in site mode
  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (!siteMode) {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode]);

  // Fetch counts
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchCounts();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchCounts = async () => {
    if (!siteProject?.id) return;

    // Get today's date for filtering logs — the NEW YORK day, not the UTC one.
    const today = easternToday();

    // Each count settles INDEPENDENTLY — the old shared try meant a failed logs
    // read skipped the check-in read entirely, so one dead endpoint reported
    // BOTH counts as zero.
    const [logsR, checkinsR] = await Promise.all([
      settleFetch(() => dailyLogsAPI.getByProject(siteProject.id)),
      settleFetch(() => checkinsAPI.getActiveByProject(siteProject.id)),
    ]);

    setLogsState(logsR.status);
    if (logsR.status === 'ok') {
      const todayLogs = Array.isArray(logsR.data)
        ? logsR.data.filter(log => log.date === today)
        : [];
      setTodayLogsCount(todayLogs.length);
    } else {
      console.error('Failed to fetch today\'s logs:', logsR.error);
    }

    setWorkersState(checkinsR.status);
    if (checkinsR.status === 'ok') {
      setWorkersOnSite(Array.isArray(checkinsR.data) ? checkinsR.data.length : 0);
    } else {
      console.error('Failed to fetch active check-ins:', checkinsR.error);
    }

    setLoading(false);
  };

  // Badge copy for a count we could NOT read. Never a number.
  const unknownBadge = (state) => (state === 'offline' ? 'Offline' : 'Unavailable');

  const handleNavigate = (path) => {
    router.push(path);
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // Tier 1 ③ Inspector Mode — hand the device to an inspector. A plain
  // toggle: no PIN, no prerequisites. The tablet's own device lock is
  // the security control; this just confines the app to the read-only
  // logbooks tab until the super taps "Exit Inspector Mode" there.
  const handleLockPress = async () => {
    await lock();
    router.replace('/site/logbooks');
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <View style={s.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={s.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <Pressable
            onPress={handleLogout}
            style={s.logoutBtn}
            hitSlop={12}
          >
            <LogOut size={18} strokeWidth={1.5} color="#64748b" />
          </Pressable>
        </View>

        {/* Main Content */}
        <View style={s.content}>
          {/* One explicit banner when either count could not be read. The tiles
              still open — only the NUMBERS are unknown, and they say so. */}
          {!loading && (logsState !== 'ok' || workersState !== 'ok') && (
            <OfflineNotice
              mode={logsState === 'error' || workersState === 'error' ? 'error' : 'offline'}
              style={s.offlineBanner}
              detail={
                logsState === 'error' || workersState === 'error'
                  ? "Today's counts could not be read from the server. The badges show no number rather than a zero."
                  : "Today's counts are unavailable while this device is offline. The badges show no number rather than a zero."
              }
            />
          )}

          {/* Top Row: Log Books + Daily Logs */}
          <View style={s.gridRow}>
            <Pressable
              style={s.buttonCard}
              onPress={() => handleNavigate('/site/logbooks')}
            >
              <GlassCard style={s.buttonInner}>
                <View style={[s.iconContainer, { backgroundColor: 'rgba(59, 130, 246, 0.2)' }]}>
                  <ClipboardList size={64} strokeWidth={1.5} color="#3b82f6" />
                </View>
                <Text style={s.buttonLabel}>Log Books</Text>
                {!loading && logsState !== 'ok' ? (
                  <View style={[s.badge, s.badgeUnknown]}>
                    <Text style={[s.badgeText, s.badgeTextUnknown]}>{unknownBadge(logsState)}</Text>
                  </View>
                ) : !loading && todayLogsCount > 0 ? (
                  <View style={s.badge}>
                    <Text style={s.badgeText}>{todayLogsCount} today</Text>
                  </View>
                ) : null}
              </GlassCard>
            </Pressable>

            {!isLocked && (
              <Pressable
                style={s.buttonCard}
                onPress={() => handleNavigate('/site/daily-logs')}
              >
                <GlassCard style={s.buttonInner}>
                  <View style={[s.iconContainer, { backgroundColor: 'rgba(139, 92, 246, 0.2)' }]}>
                    <PenTool size={64} strokeWidth={1.5} color="#8b5cf6" />
                  </View>
                  <Text style={s.buttonLabel}>Daily Logs</Text>
                </GlassCard>
              </Pressable>
            )}
          </View>

          {/* Bottom Row: Documents + Worker Sign In */}
          <View style={s.gridRow}>
            <Pressable
              style={s.buttonCard}
              onPress={() => handleNavigate('/site/documents')}
            >
              <GlassCard style={s.buttonInner}>
                <View style={[s.iconContainer, { backgroundColor: semantic.attentionBg }]}>
                  <FolderOpen size={64} strokeWidth={1.5} color={semantic.neutral} />
                </View>
                <Text style={s.buttonLabel}>Documents</Text>
              </GlassCard>
            </Pressable>

            {!isLocked && (
              <Pressable
                style={s.buttonCard}
                onPress={() => handleNavigate('/site/checkins')}
              >
                <GlassCard style={s.buttonInner}>
                  <View style={[s.iconContainer, { backgroundColor: semantic.verifiedBg }]}>
                    <UserCheck size={64} strokeWidth={1.5} color={semantic.neutral} />
                  </View>
                  <Text style={s.buttonLabel}>Worker Sign In</Text>
                  {!loading && workersState !== 'ok' ? (
                    <View style={[s.badge, s.badgeUnknown]}>
                      <Text style={[s.badgeText, s.badgeTextUnknown]}>{unknownBadge(workersState)}</Text>
                    </View>
                  ) : !loading && workersOnSite > 0 ? (
                    <View style={s.badge}>
                      <Text style={s.badgeText}>{workersOnSite} on site</Text>
                    </View>
                  ) : null}
                </GlassCard>
              </Pressable>
            )}
          </View>

          {/* Tier 1 ③ Inspector Mode — hand-off toggle. This dashboard is
              site_device-only, so the control is always shown here. One
              tap confines the app to the read-only logbooks tab; the
              Exit control there releases it. */}
          <View style={s.lockBar}>
            <GlassButton
              title="Hand to Inspector (read-only)"
              icon={<Lock size={18} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLockPress}
              style={s.lockBtn}
            />
          </View>
        </View>
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
    },
    headerLeft: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    // 44 minimum - work gloves.
    logoutBtn: {
      width: 44,
      height: 44,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      backgroundColor: withAlpha('#ffffff', 0.05),
    },
    siteBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
      backgroundColor: withAlpha('#94a3b8', 0.15),
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: withAlpha('#94a3b8', 0.3),
    },
    siteBadgeText: {
      ...typography.label,
      fontSize: 14,
      color: '#4ade80',
      letterSpacing: 1,
    },
    projectName: {
      fontSize: 18,
      fontWeight: '400',
      color: colors.text.primary,
      flex: 1,
    },
    content: {
      flex: 1,
      padding: spacing.xl,
      gap: spacing.xl,
    },
    gridRow: {
      flexDirection: 'row',
      gap: spacing.xl,
      flex: 1,
    },
    buttonCard: {
      flex: 1,
    },
    buttonInner: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      padding: spacing.xl,
      position: 'relative',
    },
    iconContainer: {
      width: 120,
      height: 120,
      borderRadius: borderRadius.xxl,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: spacing.lg,
    },
    buttonLabel: {
      fontSize: 24,
      fontWeight: '300',
      color: colors.text.primary,
      textAlign: 'center',
    },
    badge: {
      position: 'absolute',
      top: spacing.lg,
      right: spacing.lg,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    badgeText: {
      fontSize: 15,
      fontWeight: '600',
      color: colors.text.primary,
    },
    // Count could not be read — visually distinct from a real count so nobody
    // reads it as data.
    badgeUnknown: {
      backgroundColor: withAlpha('#f59e0b', 0.12),
      borderColor: withAlpha('#f59e0b', 0.35),
    },
    badgeTextUnknown: {
      color: '#fbbf24',
    },
    offlineBanner: {
      marginTop: 0,
      marginBottom: 0,
    },
    // Inspector Mode lock bar (below the grid, not flex — fixed row).
    lockBar: {
      alignItems: 'center',
      gap: spacing.xs,
    },
    lockBtn: {
      alignSelf: 'stretch',
      backgroundColor: withAlpha('#f59e0b', 0.12),
      borderColor: withAlpha('#f59e0b', 0.35),
      minHeight: 56,
    },
  });
}
