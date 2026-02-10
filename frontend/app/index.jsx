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
import { useWorkers } from '../src/hooks/useWorkers';
import { useProjects } from '../src/hooks/useProjects';
import { useCheckIns } from '../src/hooks/useCheckIns';
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
  const Icon = action.icon || LayoutGrid;

  return (
    <Pressable
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      onPress={() => onPress(action.path)}
      style={({ pressed }) => [
        styles.tile,
        isHovered && styles.tileHovered,
        pressed && styles.tilePressed,
      ]}
    >
      <IconPod size={38} style={styles.tileIcon}>
        <Icon size={17} strokeWidth={1.5} color={colors.text.secondary} />
      </IconPod>
      <Text style={styles.tileTitle} numberOfLines={1}>{action.title}</Text>
      <Text style={styles.tileSubtitle} numberOfLines={1}>{action.subtitle}</Text>
    </Pressable>
  );
};

export default function DashboardScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const { workers, loading: workersLoading } = useWorkers();
  const { projects, loading: projectsLoading } = useProjects();
  const { checkIns, loading: checkInsLoading, getActiveCheckIns } = useCheckIns();

  const [activeCheckInsCount, setActiveCheckInsCount] = useState(0);

  const today = new Date();
  const dayName = today.toLocaleDateString('en-US', { weekday: 'long' }).toUpperCase();
  const fullDate = today.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    const countActiveCheckIns = async () => {
      const active = await getActiveCheckIns();
      setActiveCheckInsCount(active.length);
    };
    if (isAuthenticated) countActiveCheckIns();
  }, [isAuthenticated, checkIns]);

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

  const loading = workersLoading || projectsLoading || checkInsLoading;

  const stats = {
    totalWorkers: workers.length,
    activeProjects: projects.filter(p => p.status === 'active' || !p.status).length,
    onSiteNow: activeCheckInsCount,
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
                {loading ? (
                  <>
                    <StatCardSkeleton />
                    <StatCardSkeleton />
                    <StatCardSkeleton />
                  </>
                ) : (
                  statItems.map((stat) => {
                    const Icon = stat.icon;
                    return (
                      <StatCard
                        key={stat.label}
                        style={styles.statCard}
                        onPress={() => router.push(stat.path)}
                      >
                        <IconPod size={44} style={styles.statIcon}>
                          <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
                        </IconPod>
                        <Text style={styles.statValue}>{stat.value}</Text>
                        <Text style={styles.statLabel}>{stat.label.toUpperCase()}</Text>
                      </StatCard>
                    );
                  })
                )}
              </View>

              {/* Sync Button */}
              <View style={styles.syncSection}>
                <SyncButton showLabel={true} />
              </View>

              {/* Admin Tools — 2-column grid, admin only */}
              {user?.role === 'admin' && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>ADMIN TOOLS</Text>
                  <GlassCard style={styles.gridCard}>
                    <View style={styles.tileGrid}>
                      {adminActions.map((action) => (
                        <ActionTile
                          key={action.path}
                          action={action}
                          onPress={(path) => router.push(path)}
                        />
                      ))}
                    </View>
                  </GlassCard>
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
  container: { flex: 1 },
  loadingContainer: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  loadingText: { fontSize: 14, fontWeight: '600', color: colors.text.secondary, letterSpacing: 2 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  logoIcon: { width: 32, height: 32, borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.05)', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)' },
  logoText: { fontSize: 16, fontWeight: '700', color: colors.text.primary, letterSpacing: 1 },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: spacing.lg, paddingBottom: 100 },
  greetingSection: { marginBottom: spacing.xl },
  greetingSmall: { fontSize: 11, fontWeight: '600', color: colors.text.secondary, letterSpacing: 1.5, marginBottom: spacing.xs },
  greetingLarge: { fontSize: 32, fontWeight: '700', color: colors.text.primary, marginBottom: spacing.sm },
  dateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  dayName: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  dateDivider: { fontSize: 14, color: colors.text.subtle },
  fullDate: { fontSize: 14, color: colors.text.secondary },
  statsGrid: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.xl },
  statCard: { flex: 1 },
  statIcon: { marginBottom: spacing.sm },
  statValue: { fontSize: 28, fontWeight: '700', color: colors.text.primary, marginBottom: 2 },
  statLabel: { fontSize: 11, fontWeight: '600', color: colors.text.secondary, letterSpacing: 1 },
  syncSection: { marginBottom: spacing.xl },
  section: { marginBottom: spacing.xl },
  sectionTitle: { fontSize: 11, fontWeight: '600', color: colors.text.secondary, letterSpacing: 1.5, marginBottom: spacing.md },

  // Grid
  gridCard: { padding: spacing.md },
  tileGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },

  // Tile — mirrors listItemHovered / listItemPressed from GlassCard.js
  tile: {
    width: '48%',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    padding: spacing.md,
    alignItems: 'flex-start',
    gap: 4,
    transition: 'all 0.2s ease',
  },
  tileHovered: {
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderColor: 'rgba(255,255,255,0.3)',
    transform: [{ scale: 1.01 }, { translateY: -2 }],
  },
  tilePressed: {
    opacity: 0.85,
    transform: [{ scale: 0.99 }],
  },
  tileIcon: {
    marginBottom: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  tileTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
    letterSpacing: 0.2,
  },
  tileSubtitle: {
    fontSize: 11,
    color: colors.text.muted,
    letterSpacing: 0.1,
  },
});
