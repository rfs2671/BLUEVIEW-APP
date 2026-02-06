import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ClipboardList,
  FolderOpen,
  UserCheck,
  Building2,
  LogOut,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dailyLogsAPI, checkinsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function SiteDeviceHomeScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
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

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleNavigate = (path) => {
    router.push(path);
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={styles.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={styles.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={styles.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        {/* Main Content */}
        <View style={styles.content}>
          {/* Top Row: Log Books + Documents */}
          <View style={styles.topRow}>
            {/* Log Books Button */}
            <Pressable
              style={styles.buttonCard}
              onPress={() => handleNavigate('/site/daily-logs')}
            >
              <GlassCard style={styles.buttonInner}>
                <View style={[styles.iconContainer, { backgroundColor: 'rgba(59, 130, 246, 0.2)' }]}>
                  <ClipboardList size={64} strokeWidth={1.5} color="#3b82f6" />
                </View>
                <Text style={styles.buttonLabel}>Log Books</Text>
                {!loading && todayLogsCount > 0 && (
                  <View style={styles.badge}>
                    <Text style={styles.badgeText}>{todayLogsCount} today</Text>
                  </View>
                )}
              </GlassCard>
            </Pressable>

            {/* Documents Button */}
            <Pressable
              style={styles.buttonCard}
              onPress={() => handleNavigate('/site/documents')}
            >
              <GlassCard style={styles.buttonInner}>
                <View style={[styles.iconContainer, { backgroundColor: 'rgba(245, 158, 11, 0.2)' }]}>
                  <FolderOpen size={64} strokeWidth={1.5} color="#f59e0b" />
                </View>
                <Text style={styles.buttonLabel}>Documents</Text>
              </GlassCard>
            </Pressable>
          </View>

          {/* Bottom Row: Worker Sign In (Larger) */}
          <Pressable
            style={styles.largeButtonCard}
            onPress={() => handleNavigate('/site/checkins')}
          >
            <GlassCard style={styles.largeButtonInner}>
              <View style={[styles.largeIconContainer, { backgroundColor: 'rgba(74, 222, 128, 0.2)' }]}>
                <UserCheck size={80} strokeWidth={1.5} color="#4ade80" />
              </View>
              <Text style={styles.largeButtonLabel}>Worker Sign In</Text>
              {!loading && workersOnSite > 0 && (
                <View style={styles.largeBadge}>
                  <Text style={styles.largeBadgeText}>{workersOnSite} on site</Text>
                </View>
              )}
            </GlassCard>
          </Pressable>
        </View>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
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
  topRow: {
    flexDirection: 'row',
    gap: spacing.xl,
    height: '45%',
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
  largeButtonCard: {
    flex: 1,
  },
  largeButtonInner: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xxl,
    position: 'relative',
  },
  largeIconContainer: {
    width: 160,
    height: 160,
    borderRadius: borderRadius.xxl,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  largeButtonLabel: {
    fontSize: 32,
    fontWeight: '300',
    color: colors.text.primary,
    textAlign: 'center',
  },
  largeBadge: {
    position: 'absolute',
    top: spacing.xl,
    right: spacing.xl,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: 'rgba(74, 222, 128, 0.2)',
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  largeBadgeText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#4ade80',
  },
});
