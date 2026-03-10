import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Dimensions } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Users,
  Building2,
  MapPin,
  LogOut,
  LayoutGrid,
  UserCog,
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
import { useTheme } from '../src/context/ThemeContext';
import { workersAPI, projectsAPI, checkinsAPI } from '../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

const adminActions = [
  { title: 'User Mgmt', subtitle: 'CPs & workers', path: '/admin/users', icon: UserCog },
  { title: 'Checklists', subtitle: 'Safety & inspection', path: '/admin/checklists', icon: ClipboardList },
  { title: 'Site Devices', subtitle: 'Kiosk credentials', path: '/admin/site-devices', icon: Smartphone },
  { title: 'Integrations', subtitle: 'Connect Dropbox', path: '/admin/integrations', icon: Cloud },
];

// 2-column grid tile
const ActionTile = ({ action, onPress, tileWidth }) => {
  const [isHovered, setIsHovered] = useState(false);
  const Icon = action.icon;
  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.actionTile,
        { width: tileWidth, backgroundColor: colors.glass.background, borderColor: colors.glass.border },
        isHovered && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.glass.borderHover },
      ]}
    >
      <IconPod size={40} style={styles.actionIcon}>
        <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
      </IconPod>
      <Text style={[styles.actionTitle, { color: colors.text.primary }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{action.title}</Text>
      <Text style={[styles.actionSubtitle, { color: colors.text.muted }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{action.subtitle}</Text>
    </Pressable>
  );
};

export default function DashboardScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark } = useTheme();
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
      const [workersData, projectsData, activeCheckInsData] = await Promise.all([
        workersAPI.getAll(),
        projectsAPI.getAll(),
        checkinsAPI.getByDate(new Date()),
      ]);
      setWorkers(Array.isArray(workersData) ? workersData : []);
      setProjects(Array.isArray(projectsData) ? projectsData : []);
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
    year: 'numeric',
  });

  const getUserFirstName = () => {
    if (user?.first_name) return user.first_name;
    if (user?.display_name) return user.display_name.split(' ')[0];
    if (user?.name) return user.name.split(' ')[0];
    if (user?.email) return user.email.split('@')[0];
    return 'User';
  };

  const getUserEmail = () => {
    return user?.email || '';
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const stats = {
    totalWorkers: activeCheckIns.length,
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

  // Stat labels differ between modes
  const statItems = [
    { icon: Users,     value: stats.totalWorkers,  label: isDark ? 'Workers' : 'Active Workers', path: '/workers'  },
    { icon: Building2, value: stats.activeProjects, label: isDark ? 'Projects' : 'Live Projects',  path: '/projects' },
    { icon: MapPin,    value: stats.onSiteNow,      label: isDark ? 'On Site' : 'On Site Now',    path: '/workers'  },
  ];

  const screenWidth = Dimensions.get('window').width;
  const tilePadding = spacing.lg * 2;
  const tileGap = spacing.sm;
  const tileWidth = Math.min((screenWidth - tilePadding - tileGap) / 2, 300);;

  // ── Shared admin tools block ────────────────────────────────────────────────
  const renderAdminTools = () => {
    if (user?.role !== 'admin' && user?.role !== 'owner') return null;
    return (
      <>
        <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>ADMIN TOOLS</Text>
        <View style={styles.adminGrid}>
          {adminActions.map((action) => (
            <ActionTile
              key={action.title}
              action={action}
              onPress={() => router.push(action.path)}
              tileWidth={tileWidth}
            />
          ))}
        </View>
      </>
    );
  };

  // ── Shared stats row ────────────────────────────────────────────────────────
  const renderStats = () => (
    <View style={styles.statsGrid}>
      {statItems.map((stat) => {
        const Icon = stat.icon;
        return (
          <Pressable key={stat.label} onPress={() => router.push(stat.path)} style={{ flex: 1 }}>
            <StatCard style={styles.statCard}>
              <IconPod size={44} style={styles.statIcon}>
                <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={[styles.statValue, { color: colors.text.primary }]}>{stat.value}</Text>
              <Text style={[styles.statLabel, { color: colors.text.muted }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{stat.label.toUpperCase()}</Text>
            </StatCard>
          </Pressable>
        );
      })}
    </View>
  );

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={[
              styles.logoIcon,
              { backgroundColor: isDark ? colors.glass.background : colors.iconPod.background },
            ]}>
              <LayoutGrid
                size={20}
                strokeWidth={1.5}
                color={isDark ? colors.text.primary : colors.primary}
                preserveColor
              />
            </View>
            <Text style={[styles.logoText, { color: colors.text.primary }]}>BLUEVIEW</Text>
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

        {/* ── Scroll content ──────────────────────────────────────────────── */}
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {loading ? (
            <DashboardSkeleton />
          ) : isDark ? (
            /* ══════════════════════════════════════════════════════════════
               DARK MODE — original flat layout (unchanged)
               ══════════════════════════════════════════════════════════════ */
            <>
              <View style={styles.greetingSection}>
                <Text style={[styles.greetingSmall, { color: colors.text.muted }]}>WELCOME BACK</Text>
                <Text style={[styles.greetingLarge, { color: colors.text.primary }]}>{getUserFirstName()}</Text>
                <View style={styles.dateRow}>
                  <Text style={styles.dayName}>{dayName}</Text>
                  <Text style={styles.dateDivider}>•</Text>
                  <Text style={styles.fullDate}>{fullDate}</Text>
                </View>
              </View>

              <GlassCard style={styles.darkStatsCard}>
                {renderStats()}
              </GlassCard>

              <SyncButton onSyncComplete={fetchData} />

              {renderAdminTools()}
            </>
          ) : (
            /* ══════════════════════════════════════════════════════════════
               LIGHT MODE — hero card layout (target design)
               ══════════════════════════════════════════════════════════════ */
            <>
              <GlassCard style={styles.heroCard}>
                {/* Date on top */}
                <Text style={[styles.heroDay, { color: colors.text.muted }]}>{dayName.toUpperCase()}</Text>
                <Text style={[styles.heroDate, { color: colors.text.secondary }]}>{fullDate}</Text>

                {/* Big name */}
                <Text style={[styles.heroName, { color: colors.text.primary }]}>{getUserFirstName()}</Text>

                {/* Email */}
                <Text style={[styles.heroEmail, { color: colors.text.muted }]}>{getUserEmail()}</Text>
                
                {/* Stats inside the card */}
                {renderStats()}
              </GlassCard>

              <SyncButton onSyncComplete={fetchData} />

              {renderAdminTools()}
            </>
          )}
        </ScrollView>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════
   STYLES
   ═══════════════════════════════════════════════════════════════════════════════ */
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

  /* ── Header: space-between, logo left / logout right ────────────────────── */
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
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
    alignItems: 'center',
    justifyContent: 'center',
    // backgroundColor set inline (isDark conditional)
  },
  logoText: {
    fontFamily: typography.semibold,
    fontSize: 16,
    color: colors.text.primary,
    letterSpacing: 1.5,
  },

  /* ── Scroll ─────────────────────────────────────────────────────────────── */
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 140,
    maxWidth: 1200,
    width: '100%',
    alignSelf: 'center',
  },

  /* ── Dark mode: original flat greeting ─────────────────────────────────── */
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

  /* ── Light mode: hero card ─────────────────────────────────────────────── */
  heroCard: {
    marginTop: spacing.md,
    marginBottom: spacing.xl,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.xl,
  },
  heroDay: {
    fontFamily: typography.medium,
    fontSize: 11,
    color: colors.text.muted,
    letterSpacing: 1.5,
    marginBottom: spacing.xs,
  },
  heroDate: {
    fontFamily: typography.regular,
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: spacing.lg,
  },
  heroName: {
    fontFamily: typography.semibold,
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
    marginBottom: spacing.xs,
  },
  heroEmail: {
    fontFamily: typography.regular,
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.xl,
  },

  /* ── Stats row ─────────────────────────────────────────────────────────── */
  statsGrid: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
    minHeight: 120,
    width: '100%',
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontFamily: typography.semibold,
    fontSize: 28,
    marginBottom: spacing.xs,
  },
  statLabel: {
    fontFamily: typography.medium,
    fontSize: 11,
    letterSpacing: 0.5,
    textAlign: 'center',
    paddingHorizontal: spacing.xs,
  },
  darkStatsCard: {
    marginTop: spacing.lg,
    marginBottom: spacing.xl,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.sm,
  },

  /* ── Section label ─────────────────────────────────────────────────────── */
  sectionLabel: {
    fontFamily: typography.medium,
    fontSize: 11,
    color: colors.text.muted,
    letterSpacing: 1.5,
    marginBottom: spacing.md,
    marginTop: spacing.md,
  },

  /* ── Admin grid ────────────────────────────────────────────────────────── */
  adminGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    rowGap: spacing.sm,
  },
  actionTile: {
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    borderWidth: 1,
  },
  actionIcon: {
    marginBottom: spacing.xs,
  },
  actionTitle: {
    fontFamily: typography.medium,
    fontSize: 14,
    textAlign: 'center',
  },
  actionSubtitle: {
    fontFamily: typography.regular,
    fontSize: 11,
    textAlign: 'center',
  },
});
