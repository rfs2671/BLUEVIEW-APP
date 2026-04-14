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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dailyLogsAPI, checkinsAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

export default function SiteDeviceHomeScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [todayLogsCount, setTodayLogsCount] = useState(0);
  const [workersOnSite, setWorkersOnSite] = useState(0);
  const [loading, setLoading] = useState(true);

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

    try {
      // Get today's date for filtering logs
      const today = new Date().toISOString().split('T')[0];

      // Fetch today's logs count
      const logs = await dailyLogsAPI.getByProject(siteProject.id);
      const todayLogs = Array.isArray(logs) ? logs.filter(log => log.date === today) : [];
      setTodayLogsCount(todayLogs.length);

      // Fetch active checkins (workers on site)
      const activeCheckins = await checkinsAPI.getActiveByProject(siteProject.id);
      setWorkersOnSite(Array.isArray(activeCheckins) ? activeCheckins.length : 0);
    } catch (error) {
      console.error('Failed to fetch counts:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleNavigate = (path) => {
    router.push(path);
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <View style={s.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={s.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
        </View>

        {/* Main Content */}
        <View style={s.content}>
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
                {!loading && todayLogsCount > 0 && (
                  <View style={s.badge}>
                    <Text style={s.badgeText}>{todayLogsCount} today</Text>
                  </View>
                )}
              </GlassCard>
            </Pressable>

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
          </View>

          {/* Bottom Row: Documents + Worker Sign In */}
          <View style={s.gridRow}>
            <Pressable
              style={s.buttonCard}
              onPress={() => handleNavigate('/site/documents')}
            >
              <GlassCard style={s.buttonInner}>
                <View style={[s.iconContainer, { backgroundColor: 'rgba(245, 158, 11, 0.2)' }]}>
                  <FolderOpen size={64} strokeWidth={1.5} color="#f59e0b" />
                </View>
                <Text style={s.buttonLabel}>Documents</Text>
              </GlassCard>
            </Pressable>

            <Pressable
              style={s.buttonCard}
              onPress={() => handleNavigate('/site/checkins')}
            >
              <GlassCard style={s.buttonInner}>
                <View style={[s.iconContainer, { backgroundColor: 'rgba(74, 222, 128, 0.2)' }]}>
                  <UserCheck size={64} strokeWidth={1.5} color="#4ade80" />
                </View>
                <Text style={s.buttonLabel}>Worker Sign In</Text>
                {!loading && workersOnSite > 0 && (
                  <View style={s.badge}>
                    <Text style={s.badgeText}>{workersOnSite} on site</Text>
                  </View>
                )}
              </GlassCard>
            </Pressable>
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
    siteBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
      backgroundColor: 'rgba(74, 222, 128, 0.15)',
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: 'rgba(74, 222, 128, 0.3)',
    },
    siteBadgeText: {
      ...typography.label,
      fontSize: 9,
      color: '#4ade80',
      letterSpacing: 1,
    },
    projectName: {
      fontSize: 16,
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
      fontSize: 12,
      fontWeight: '600',
      color: colors.text.primary,
    },
  });
}
