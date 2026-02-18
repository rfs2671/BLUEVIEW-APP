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
  UserCog,
  Briefcase,
  Smartphone,
  Cloud,
  ClipboardList,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { DashboardSkeleton, StatCardSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import OfflineIndicator from '../src/components/OfflineIndicator';
import SyncButton from '../src/components/SyncButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { workersAPI, projectsAPI, checkinsAPI } from '../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

const adminActions = [
  { title: 'User Mgmt', subtitle: 'CPs & workers', path: '/admin/users', icon: UserCog },
  { title: 'Subcontractors', subtitle: 'Company accounts', path: '/admin/subcontractors', icon: Briefcase },
  { title: 'Checklists', subtitle: 'Safety & inspection', path: '/admin/checklists', icon: ClipboardList },
  { title: 'Site Devices', subtitle: 'Kiosk credentials', path: '/admin/site-devices', icon: Smartphone },
  { title: 'Integrations', subtitle: 'Connect Dropbox', path: '/admin/integrations', icon: Cloud },
];

// 2-column grid tile — hover/press matches GlassCard.js listItem pattern exactly
const ActionTile = ({ action, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const Icon = action.icon;
  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[styles.actionTile, isHovered && styles.actionTileHovered]}
    >
      <IconPod size={40} style={styles.actionIcon}>
        <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
      </IconPod>
      <View style={styles.actionText}>
        <Text style={styles.actionTitle}>{action.title}</Text>
        <Text style={styles.actionSubtitle}>{action.subtitle}</Text>
      </View>
    </Pressable>
  );
};

export default function DashboardScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [workers, setWorkers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [activeCheckIns, setActiveCheckIns] = useState([]);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    try {
      setLoading(true);
      
      // Fetch from API only
      const [workersData, projectsData, activeCheckInsData] = await Promise.all([
        workersAPI.getAll(),
        projectsAPI.getAll(),
        checkinsAPI.getAll(),
      ]);

      setWorkers(Array.isArray(workersData) ? workersData : []);
      setProjects(Array.isArray(projectsData) ? projectsData : []);
      
      // Filter for active (not checked out) check-ins
      const active = Array.isArray(activeCheckInsData) 
        ? activeCheckInsData.filter(c => !c.check_out_time && !c.checkout_time)
        : [];
      setActiveCheckIns(active);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      toast.error('Error', 'Could not load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  const dayName = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const fullDate = new Date().toLocaleDateString('en-US', { 
    month: 'long', 
    day: 'numeric', 
    year: 'numeric' 
  });

  const getUserFirstName = () => {
    if (user?.first_name) return user.first_name;
    if (user?.display_name) return user.display_name.split(' ')[0];
    if (user?.name) return user.name.split(' ')[0];
    if (user?.email) return user.email.split('@')[0];
    return 'User';
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const stats = {
    totalWorkers: workers.length,
    activeProjects: projects.filter(p => p.status === 'active' || !p.status).length,
    onSiteNow: activeCheckIns.length,
  };

  if (authLoading) {
    return (
      <View style={styles.loadingContainer}>
        <Text style={styles.loadingText}>LOADING</Text>
      </View>
    );
  }

  const statItems = [
    { icon: Users,     value: stats.totalWorkers,   label: 'Workers',  path: '/workers'  },
    { icon: Building2, value: stats.activeProjects, label: 'Projects', path: '/projects' },
    { icon: MapPin,    value: stats.onSiteNow,       label: 'On Site',  path: '/workers'  },
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
          <View style={styles.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {loading ? (
            <DashboardSkeleton />
          ) : (
            <>
              {/* Greeting */}
              <View style={styles.greetingSection}>
                <Text style={styles.greetingSmall}>WELCOME BACK</Text>
                <Text style={styles.greetingLarge}>{getUserFirstName()}</Text>
                <View style={styles.dateRow}>
                  <Text style={styles.dayName}>{dayName}</Text>
                  <Text style={styles.dateDivider}>•</Text>
                  <Text style={styles.fullDate}>{fullDate}</Text>
                </View>
              </View>

              {/* Stats — pressable, navigate on tap */}
              <View style={styles.statsGrid}>
                {loading ?
                  <>
                    <StatCardSkeleton />
                    <StatCardSkeleton />
                    <StatCardSkeleton />
                  </>
                :
                  statItems.map((stat) => {
                    const Icon = stat.icon;
                    return (
                      <Pressable key={stat.label} onPress={() => router.push(stat.path)}>
                        <StatCard style={styles.statCard}>
                          <IconPod size={44} style={styles.statIcon}>
                            <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
                          </IconPod>
                          <Text style={styles.statValue}>{stat.value}</Text>
                          <Text style={styles.statLabel}>{stat.label.toUpperCase()}</Text>
                        </StatCard>
                      </Pressable>
                    );
                  })
                }
              </View>

              {/* Sync Button */}
              <SyncButton onSyncComplete={fetchData} />

              {/* Admin Tools - Only show for admin/owner */}
              {(user?.role === 'admin' || user?.role === 'owner') && (
                <>
                  <Text style={styles.sectionLabel}>ADMIN TOOLS</Text>
                  <View style={styles.adminGrid}>
                    {adminActions.map((action) => (
                      <ActionTile
                        key={action.title}
                        action={action}
                        onPress={() => router.push(action.path)}
                      />
                    ))}
                  </View>
                </>
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background.primary,
  },
  loadingText: {
    fontFamily: typography.medium,
    fontSize: 14,
    color: colors.text.muted,
    letterSpacing: 2,
  },
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  logoIcon: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.light,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoText: {
    fontFamily: typography.semibold,
    fontSize: 16,
    color: colors.text.primary,
    letterSpacing: 1.5,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  greetingSection: {
    marginTop: spacing.lg,
    marginBottom: spacing.xl,
  },
  greetingSmall: {
    fontFamily: typography.regular,
    fontSize: 11,
    color: colors.text.muted,
    letterSpacing: 1.5,
    marginBottom: spacing.xs,
  },
  greetingLarge: {
    fontFamily: typography.semibold,
    fontSize: 32,
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  dateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dayName: {
    fontFamily: typography.medium,
    fontSize: 13,
    color: colors.text.secondary,
  },
  dateDivider: {
    fontFamily: typography.regular,
    fontSize: 13,
    color: colors.text.muted,
  },
  fullDate: {
    fontFamily: typography.regular,
    fontSize: 13,
    color: colors.text.muted,
  },
  statsGrid: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
    minHeight: 120,
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontFamily: typography.semibold,
    fontSize: 28,
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    fontFamily: typography.medium,
    fontSize: 10,
    color: colors.text.muted,
    letterSpacing: 1,
  },
  sectionLabel: {
    fontFamily: typography.medium,
    fontSize: 11,
    color: colors.text.muted,
    letterSpacing: 1.5,
    marginBottom: spacing.md,
    marginTop: spacing.md,
  },
  adminGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  actionTile: {
    flex: 1,
    minWidth: '47%',
    backgroundColor: colors.glass.card,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderWidth: 1,
    borderColor: colors.border.subtle,
  },
  actionTileHovered: {
    backgroundColor: colors.glass.cardHover,
    borderColor: colors.border.medium,
  },
  actionIcon: {
    flexShrink: 0,
  },
  actionText: {
    flex: 1,
  },
  actionTitle: {
    fontFamily: typography.medium,
    fontSize: 14,
    color: colors.text.primary,
    marginBottom: 2,
  },
  actionSubtitle: {
    fontFamily: typography.regular,
    fontSize: 11,
    color: colors.text.muted,
  },
});
