import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Users,
  Building2,
  MapPin,
  LogOut,
  LayoutGrid,
  ChevronRight,
  Settings,
  UserCog,
  Briefcase,
  Smartphone,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { DashboardSkeleton, StatCardSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { workersAPI, projectsAPI, checkinsAPI } from '../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

const quickActions = [
  { title: 'Projects', subtitle: 'Manage job sites', path: '/projects' },
  { title: 'Workers', subtitle: 'Daily sign-in log', path: '/workers' },
  { title: 'Daily Log', subtitle: 'Create site report', path: '/daily-log' },
  { title: 'Reports', subtitle: 'View & download', path: '/reports' },
  { title: 'Integrations', subtitle: 'Dropbox & cloud sync', path: '/admin/integrations' },
];

const adminActions = [
  { title: 'User Management', subtitle: 'Manage CPs & workers', path: '/admin/users', icon: UserCog },
  { title: 'Subcontractors', subtitle: 'Company accounts', path: '/admin/subcontractors', icon: Briefcase },
  { title: 'Site Devices', subtitle: 'On-site device logins', path: '/admin/site-devices', icon: Smartphone },
];

export default function DashboardScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();
  
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({
    totalWorkers: 0,
    activeProjects: 0,
    onSiteNow: 0,
  });

  const today = new Date();
  const dayName = today.toLocaleDateString('en-US', { weekday: 'long' }).toUpperCase();
  const fullDate = today.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch dashboard data
  useEffect(() => {
    if (isAuthenticated) {
      fetchDashboardData();
    }
  }, [isAuthenticated]);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      const [workersData, projectsData] = await Promise.all([
        workersAPI.getAll().catch(() => []),
        projectsAPI.getAll().catch(() => []),
      ]);

      const totalWorkers = Array.isArray(workersData) ? workersData.length : 0;
      const activeProjects = Array.isArray(projectsData)
        ? projectsData.filter((p) => p.status === 'active' || !p.status).length
        : 0;

      let onSiteNow = 0;
      if (projectsData.length > 0) {
        try {
          const checkinsPromises = projectsData.slice(0, 3).map((project) =>
            checkinsAPI.getActiveByProject(project._id || project.id).catch(() => [])
          );
          const checkinsResults = await Promise.all(checkinsPromises);
          onSiteNow = checkinsResults.flat().length;
        } catch (e) {
          onSiteNow = Math.floor(totalWorkers * 0.7);
        }
      }

      setStats({ totalWorkers, activeProjects, onSiteNow });
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      toast.error('Data Load Error', 'Could not load dashboard statistics');
    } finally {
      setLoading(false);
    }
  };

  const getUserFirstName = () => {
    if (user?.full_name) return user.full_name.split(' ')[0];
    if (user?.name) return user.name.split(' ')[0];
    if (user?.email) return user.email.split('@')[0];
    return 'User';
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  if (authLoading) {
    return (
      <View style={styles.loadingContainer}>
        <Text style={styles.loadingText}>LOADING</Text>
      </View>
    );
  }

  const statItems = [
    { icon: Users, value: stats.totalWorkers, label: 'Total Workers' },
    { icon: Building2, value: stats.activeProjects, label: 'Active Projects' },
    { icon: MapPin, value: stats.onSiteNow, label: 'On Site Now' },
  ];

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={styles.logoIcon}>
              <LayoutGrid size={20} strokeWidth={1.5} color={colors.text.primary} />
            </View>
            <Text style={styles.logoText}>BLUEVIEW</Text>
          </View>
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
          {loading ? (
            <>
              <DashboardSkeleton />
              <View style={styles.quickActionsSection}>
                <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
                <View style={styles.quickActionsGrid}>
                  {[1, 2, 3, 4].map((i) => (
                    <View key={i} style={styles.quickActionSkeleton} />
                  ))}
                </View>
              </View>
            </>
          ) : (
            <>
              {/* Main Glass Card */}
              <GlassCard style={styles.mainCard}>
                {/* Date */}
                <View style={styles.dateSection}>
                  <Text style={styles.dayName}>{dayName}</Text>
                  <Text style={styles.fullDate}>{fullDate}</Text>
                </View>

                {/* Name */}
                <Text style={styles.userName}>{getUserFirstName()}</Text>
                <Text style={styles.userEmail}>{user?.email || 'user@blueview.com'}</Text>

                {/* Stats Grid */}
                <View style={styles.statsGrid}>
                  {statItems.map((stat, index) => {
                    const Icon = stat.icon;
                    return (
                      <StatCard key={stat.label} style={styles.statCard}>
                        <IconPod style={styles.statIconPod}>
                          <Icon size={20} strokeWidth={1.5} color={colors.text.secondary} />
                        </IconPod>
                        <Text style={styles.statValue}>{stat.value}</Text>
                        <Text style={styles.statLabel}>{stat.label.toUpperCase()}</Text>
                      </StatCard>
                    );
                  })}
                </View>
              </GlassCard>

              {/* Quick Actions */}
              <View style={styles.quickActionsSection}>
                <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
                <View style={styles.quickActionsGrid}>
                  {quickActions.map((action) => (
                    <GlassListItem
                      key={action.title}
                      onPress={() => router.push(action.path)}
                      style={styles.quickActionCard}
                    >
                      <View style={styles.quickActionContent}>
                        <Text style={styles.quickActionTitle}>{action.title}</Text>
                        <Text style={styles.quickActionSubtitle}>{action.subtitle}</Text>
                      </View>
                      <ChevronRight size={20} strokeWidth={1.5} color={colors.text.subtle} />
                    </GlassListItem>
                  ))}
                </View>
              </View>

              {/* Admin Section - Only for admin users */}
              {user?.role === 'admin' && (
                <View style={styles.quickActionsSection}>
                  <Text style={styles.sectionLabel}>ADMINISTRATION</Text>
                  <View style={styles.quickActionsGrid}>
                    {adminActions.map((action) => {
                      const Icon = action.icon;
                      return (
                        <GlassListItem
                          key={action.title}
                          onPress={() => router.push(action.path)}
                          style={[styles.quickActionCard, styles.adminActionCard]}
                        >
                          <View style={styles.quickActionContent}>
                            <View style={styles.adminIconRow}>
                              <Icon size={16} strokeWidth={1.5} color="#f59e0b" />
                              <Text style={styles.quickActionTitle}>{action.title}</Text>
                            </View>
                            <Text style={styles.quickActionSubtitle}>{action.subtitle}</Text>
                          </View>
                          <ChevronRight size={20} strokeWidth={1.5} color={colors.text.subtle} />
                        </GlassListItem>
                      );
                    })}
                  </View>
                </View>
              )}
            </>
          )}
        </ScrollView>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.start,
  },
  loadingText: {
    ...typography.label,
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
  logoIcon: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
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
  mainCard: {
    marginBottom: spacing.xl,
  },
  dateSection: {
    marginBottom: spacing.xl,
  },
  dayName: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  fullDate: {
    fontSize: 16,
    fontWeight: '300',
    color: colors.text.muted,
  },
  userName: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
    marginBottom: spacing.xs,
  },
  userEmail: {
    fontSize: 16,
    fontWeight: '300',
    color: colors.text.muted,
    marginBottom: spacing.xxl,
  },
  statsGrid: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  statCard: {
    flex: 1,
  },
  statIconPod: {
    marginBottom: spacing.lg,
  },
  statValue: {
    ...typography.stat,
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  quickActionsSection: {
    marginTop: spacing.md,
  },
  sectionLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  quickActionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  quickActionCard: {
    width: '48%',
    padding: spacing.lg,
  },
  quickActionContent: {
    flex: 1,
  },
  quickActionTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  quickActionSubtitle: {
    fontSize: 14,
    fontWeight: '300',
    color: colors.text.muted,
  },
  quickActionSkeleton: {
    width: '48%',
    height: 80,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  adminActionCard: {
    borderColor: 'rgba(245, 158, 11, 0.2)',
  },
  adminIconRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
});
