import React, { useState, useEffect, useMemo } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Dimensions, Image } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Users,
  Building2,
  MapPin,
  UserCog,
  Smartphone,
  Cloud,
  ClipboardList,
  Shield,
  HardHat,
  Plus,
  Sparkles,
  X,
} from 'lucide-react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
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
import { spacing, borderRadius, typography } from '../src/styles/theme';
import HeaderBrand from '../src/components/HeaderBrand';

const adminActions = [
  { title: 'User Mgmt', subtitle: 'CPs & workers', path: '/admin/users', icon: UserCog },
  { title: 'Checklists', subtitle: 'Safety & inspection', path: '/admin/checklists', icon: ClipboardList },
  { title: 'Site Devices', subtitle: 'Kiosk credentials', path: '/admin/site-devices', icon: Smartphone },
  { title: 'Integrations', subtitle: 'Connect Dropbox', path: '/admin/integrations', icon: Cloud },
  { title: 'Superintendents', subtitle: 'CS one-job rule', path: '/admin/superintendent', icon: HardHat },
  { title: 'Safety Staff', subtitle: 'SSC / SSM registry', path: '/admin/safety-staff', icon: Shield },
];

// 2-column grid tile
const ActionTile = ({ action, onPress, tileWidth }) => {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const [isHovered, setIsHovered] = useState(false);
  const Icon = action.icon;
  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        s.actionTile,
        { width: tileWidth, backgroundColor: colors.glass.background, borderColor: colors.glass.border },
        isHovered && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.glass.borderHover },
      ]}
    >
      <IconPod size={40} style={s.actionIcon}>
        <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
      </IconPod>
      <Text style={[s.actionTitle, { color: colors.text.primary }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{action.title}</Text>
      <Text style={[s.actionSubtitle, { color: colors.text.muted }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{action.subtitle}</Text>
    </Pressable>
  );
};

export default function DashboardScreen() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, colors } = useTheme();
  const s = buildStyles(colors, isDark);
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [workers, setWorkers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [activeCheckIns, setActiveCheckIns] = useState([]);

  const [layoutReady, setLayoutReady] = useState(false);

  // Phase C1.3 — first-poll banner state (Phase B3) hoisted to the
  // top of the component alongside the rest of the hooks. Pre-C1.3
  // these lived ~150 lines down, AFTER the `if (authLoading) return …`
  // early-return block, which made them conditional. On the first
  // render with authLoading=true, the early return fired before
  // these ran (12 hooks); on the next render with authLoading=false
  // they DID run (14 hooks). Hook count divergence → React error
  // #310 in production. Sentry diagnosed this once C1.2.1 wired
  // source maps. The fix is purely structural: same hooks, same
  // semantics, just declared above the early return so they
  // ALWAYS run on every render.
  const [dismissedBanners, setDismissedBanners] = useState({});

  useEffect(() => {
    const timer = requestAnimationFrame(() => setLayoutReady(true));
    return () => cancelAnimationFrame(timer);
  }, []);

  useEffect(() => {
    if (!layoutReady) return;
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [layoutReady, isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  // Phase C1.3 — first-poll banner: AsyncStorage hydration on
  // mount. Hoisted alongside the other useEffects above the early
  // return.
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem('bv_first_poll_dismissed');
        if (raw) setDismissedBanners(JSON.parse(raw));
      } catch (_e) { /* noop */ }
    })();
  }, []);

  // Phase C1.3 — derive the banner project memo above the early
  // return too. Reads `projects` (state) + `dismissedBanners`
  // (state) so it must re-run on either state change.
  const firstPollBannerProject = useMemo(() => {
    if (!Array.isArray(projects) || projects.length === 0) return null;
    const now = Date.now();
    const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;
    for (const p of projects) {
      const pid = p.id || p._id;
      if (!pid) continue;
      if (dismissedBanners[pid]) continue;
      const completedAt = p.first_poll_completed_at;
      if (!completedAt) continue;
      const t = new Date(completedAt).getTime();
      if (Number.isNaN(t)) continue;
      if (now - t > TWENTY_FOUR_HOURS_MS) continue;
      return p;
    }
    return null;
  }, [projects, dismissedBanners]);

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

  const stats = {
    totalWorkers: workers.length,
    activeProjects: projects.filter(p => p.status === 'active' || !p.status).length,
    onSiteNow: activeCheckIns.length,
  };

  if (authLoading) {
    return (
      <View style={s.loadingContainer}>
        <Text style={s.loadingText}>LOADING</Text>
      </View>
    );
  }

  // PR #48 L9 — the 3-metric strip (Workers / Projects / On Site Now)
  // was removed from the dashboard. statItems + renderStats deleted.

  // ── Phase B3: empty state for owners/admins with no projects ────────
  // Surfaces a CTA + welcome copy when the dashboard has nothing to
  // show. Triggers when the user has admin/owner role AND projects
  // length is 0 AND we've finished loading. Skip-onboarding path
  // lands here (so does any authed user with zero projects).
  const showProjectsEmptyState =
    !loading &&
    (user?.role === 'admin' || user?.role === 'owner') &&
    Array.isArray(projects) &&
    projects.length === 0;

  const screenWidth = Dimensions.get('window').width;
  const tilePadding = spacing.lg * 2;
  const tileGap = spacing.sm;
  const tileWidth = Math.min((screenWidth - tilePadding - tileGap) / 2, 300);

  // ── Shared admin tools block ────────────────────────────────────────────────
  const renderAdminTools = () => {
    if (user?.role !== 'admin' && user?.role !== 'owner') return null;
    return (
      <>
        <Text style={[s.sectionLabel, { color: colors.text.muted }]}>ADMIN TOOLS</Text>
        <View style={s.adminGrid}>
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

  // ── Phase B3: empty state for fresh customers ──────────────────
  const renderProjectsEmptyState = () => {
    if (!showProjectsEmptyState) return null;
    return (
      <GlassCard style={s.emptyStateCard}>
        <IconPod size={48} style={{ marginBottom: spacing.md }}>
          <Sparkles size={24} strokeWidth={1.5} color={colors.text.primary} />
        </IconPod>
        <Text style={[s.emptyStateTitle, { color: colors.text.primary }]}>
          Welcome to LeveLog
        </Text>
        <Text style={[s.emptyStateBody, { color: colors.text.secondary }]}>
          Add your first project to start monitoring DOB activity. We'll
          pull permits, filings, violations, and inspections every 15
          minutes.
        </Text>
        <GlassButton
          title="Add Project"
          icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
          onPress={() => router.push('/projects')}
          style={s.emptyStateCta}
        />
      </GlassCard>
    );
  };

  // ── Phase B3: first-poll banner (24h) ──────────────────────────
  // Hooks for this banner (useState + useEffect + useMemo) live at
  // the top of the component now; the helpers below just consume
  // their values. See the C1.3 comment at the hoisted hooks above.
  const dismissBanner = async (projectId) => {
    const next = { ...dismissedBanners, [projectId]: Date.now() };
    setDismissedBanners(next);
    try {
      await AsyncStorage.setItem(
        'bv_first_poll_dismissed',
        JSON.stringify(next),
      );
    } catch (_e) { /* noop */ }
  };

  // (firstPollBannerProject useMemo lives at the top of the
  // component alongside the other hooks — see the hoisted block
  // above the early `if (authLoading) return` guard.)

  const renderFirstPollBanner = () => {
    if (!firstPollBannerProject) return null;
    const p = firstPollBannerProject;
    const summary = p.first_poll_summary || {};
    const permits = summary.permits || 0;
    const violations = summary.violations || 0;
    const inspections = summary.inspections || 0;
    const pid = p.id || p._id;
    return (
      <GlassCard style={s.firstPollBanner}>
        <View style={s.firstPollBannerRow}>
          <IconPod size={40}>
            <Sparkles size={18} strokeWidth={1.5} color={colors.text.primary} />
          </IconPod>
          <View style={{ flex: 1 }}>
            <Text style={[s.firstPollBannerTitle, { color: colors.text.primary }]}>
              Initial scan complete for {p.name || 'your project'}
            </Text>
            <Text style={[s.firstPollBannerBody, { color: colors.text.secondary }]}>
              Found {permits} permit{permits === 1 ? '' : 's'}, {violations}{' '}
              violation{violations === 1 ? '' : 's'}, {inspections} inspection
              {inspections === 1 ? '' : 's'}.
            </Text>
            <Pressable
              onPress={() => router.push(`/project/${pid}/activity`)}
              style={s.firstPollBannerCta}
            >
              <Text style={[s.firstPollBannerCtaText, { color: colors.primary }]}>
                View activity →
              </Text>
            </Pressable>
          </View>
          <Pressable
            onPress={() => dismissBanner(pid)}
            accessibilityLabel="Dismiss banner"
            style={s.firstPollBannerDismiss}
          >
            <X size={16} color={colors.text.muted} />
          </Pressable>
        </View>
      </GlassCard>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <HeaderBrand />
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
          </View>
        </View>

        {/* ── Scroll content ──────────────────────────────────────────────── */}
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {loading ? (
            <DashboardSkeleton />
          ) : isDark ? (
            /* ══════════════════════════════════════════════════════════════
               DARK MODE — original flat layout (unchanged)
               ══════════════════════════════════════════════════════════════ */
            <>
              <View style={s.greetingSection}>
                <Text style={[s.greetingSmall, { color: colors.text.muted }]}>WELCOME BACK</Text>
                <Text style={[s.greetingLarge, { color: colors.text.primary }]}>{getUserFirstName()}</Text>
                <View style={s.dateRow}>
                  <Text style={s.dayName}>{dayName}</Text>
                  <Text style={s.dateDivider}>•</Text>
                  <Text style={s.fullDate}>{fullDate}</Text>
                </View>
              </View>

              {/* B3: 24h first-poll banner */}
              {renderFirstPollBanner()}

              {/* PR #48 L9 — 3-metric strip removed. */}

              {/* B3: empty state when no projects */}
              {renderProjectsEmptyState()}

              <SyncButton onSyncComplete={fetchData} />

              {renderAdminTools()}
            </>
          ) : (
            /* ══════════════════════════════════════════════════════════════
               LIGHT MODE — hero card layout (target design)
               ══════════════════════════════════════════════════════════════ */
            <>
              {/* B3: 24h first-poll banner */}
              {renderFirstPollBanner()}

              <GlassCard style={s.heroCard}>
                {/* Date on top */}
                <Text style={[s.heroDay, { color: colors.text.muted }]}>{dayName.toUpperCase()}</Text>
                <Text style={[s.heroDate, { color: colors.text.secondary }]}>{fullDate}</Text>

                {/* PR #48 L9 — identity compressed to a single line
                    (name + muted email) and the 3-metric strip removed. */}
                <View style={s.heroIdentityRow}>
                  <Text style={[s.heroName, { color: colors.text.primary }]}>{getUserFirstName()}</Text>
                  {getUserEmail() ? (
                    <Text style={[s.heroEmailInline, { color: colors.text.muted }]} numberOfLines={1}>
                      {getUserEmail()}
                    </Text>
                  ) : null}
                </View>
              </GlassCard>

              {/* B3: empty state when no projects */}
              {renderProjectsEmptyState()}

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
function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
  // PR #48 L9 — compressed identity line. Name + email share one row,
  // baseline-aligned; email wraps to its own line on narrow widths.
  heroIdentityRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    flexWrap: 'wrap',
    columnGap: spacing.sm,
  },
  heroEmailInline: {
    fontFamily: typography.regular,
    fontSize: 14,
    color: colors.text.muted,
    flexShrink: 1,
  },

  /* ── Stats row ─────────────────────────────────────────────────────────── */
  statsGrid: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
    minHeight: 140,
    width: '100%',
    alignItems: 'center',
  },
  statIcon: {
    marginBottom: spacing.xs,
  },
  statValue: {
    fontFamily: typography.semibold,
    fontSize: 44,
    marginBottom: spacing.xs,
  },
  statLabel: {
    fontFamily: typography.medium,
    fontSize: 12,
    letterSpacing: 0.5,
    textAlign: 'center',
    paddingHorizontal: 0,
  },
  darkStatsCard: {
    marginTop: spacing.lg,
    marginBottom: spacing.xl,
    paddingVertical: spacing.xs,
    paddingHorizontal: 0,
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

  /* ── B3: empty state ──────────────────────────────────────────────────── */
  emptyStateCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.lg,
  },
  emptyStateTitle: {
    fontFamily: typography.semibold,
    fontSize: 22,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  emptyStateBody: {
    fontFamily: typography.regular,
    fontSize: 14,
    lineHeight: 20,
    color: colors.text.secondary,
    textAlign: 'center',
    maxWidth: 420,
    marginBottom: spacing.lg,
  },
  emptyStateCta: {
    minWidth: 180,
  },

  /* ── B3: first-poll banner ────────────────────────────────────────────── */
  firstPollBanner: {
    marginBottom: spacing.lg,
  },
  firstPollBannerRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  firstPollBannerTitle: {
    fontFamily: typography.semibold,
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 2,
  },
  firstPollBannerBody: {
    fontFamily: typography.regular,
    fontSize: 13,
    lineHeight: 18,
    color: colors.text.secondary,
    marginBottom: spacing.xs,
  },
  firstPollBannerCta: {
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  firstPollBannerCtaText: {
    fontFamily: typography.medium,
    fontSize: 13,
    fontWeight: '600',
  },
  firstPollBannerDismiss: {
    padding: spacing.xs,
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
}
