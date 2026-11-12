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
  Lock,
  ChevronRight,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { SoftBox, SoftPebble } from '../../src/components/SoftPanel';
import { useAuth } from '../../src/context/AuthContext';
import { useLogoutConfirm } from '../../src/hooks/useLogoutConfirm';
import { useInspectorLock } from '../../src/context/InspectorLockContext';
import { dailyLogsAPI, checkinsAPI } from '../../src/utils/api';
import OfflineNotice from '../../src/components/OfflineNotice';
import SiteReadinessNotice, { useSiteReadiness } from '../../src/components/SiteReadinessNotice';
import { SITE_READY_CURRENT } from '../../src/utils/siteDeviceReadiness';
import { settleFetch } from '../../src/utils/offlineState';
import { spacing, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import { easternToday } from '../../src/utils/dates';

export default function SiteDeviceHomeScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
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

  // A SECOND, ORTHOGONAL AXIS. The two states above answer "did the network
  // answer just now". This answers "does this tablet hold the complete
  // approved set" — a question nothing on any /site screen used to ask, and
  // the one that matters before somebody walks away from the signal with it.
  // Both can be true at once, and this screen states both.
  const readiness = useSiteReadiness(siteProject?.id);

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

  // WHAT THE TABLET HOLDS, AS A NUMBER IN THE PANEL. Only for the ordinary
  // states -- a device that is still filling, or is complete. Every state that
  // is a WARNING (never complete, ageing, out of room) still gets the full
  // SiteReadinessNotice above the panel, word for word as before.
  const savedValue = (() => {
    const r = readiness || {};
    if (r.state !== SITE_READY_CURRENT) return null;
    if (r.filling && Number.isFinite(r.saved) && Number.isFinite(r.expected)) return `${r.saved}/${r.expected}`;
    return 'All';
  })();
  const stillSaving = readiness?.state === SITE_READY_CURRENT && readiness?.filling;

  const countText = (state, n) => (loading ? '–' : state === 'ok' ? String(n) : unknownBadge(state));

  const handleNavigate = (path) => {
    router.push(path);
  };

  // Drains what is queued, asks before deleting what could not be sent.
  const { requestLogout: handleLogout, logoutDialog } = useLogoutConfirm({
    onLoggedOut: () => router.replace('/login'),
  });

  // Tier 1 ③ Inspector Mode — hand the device to an inspector. A plain
  // toggle: no PIN, no prerequisites. The tablet's own device lock is
  // the security control; this just confines the app to the read-only
  // logbooks tab until the super taps "Exit Inspector Mode" there.
  const handleLockPress = async () => {
    await lock();
    router.replace('/site/logbooks');
  };

  const TILES = [
    { key: 'logs', path: '/site/logbooks', Icon: ClipboardList, label: 'Log Books', tint: semantic.attention },
    { key: 'docs', path: '/site/documents', Icon: FolderOpen, label: 'Documents', tint: INK },
    ...(!isLocked ? [{ key: 'workers', path: '/site/checkins', Icon: UserCheck, label: 'Worker Sign In', tint: semantic.verified }] : []),
  ];

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top', 'bottom']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <SoftBox kind="slimw" style={s.siteBadge} contentStyle={s.siteBadgeInner}>
              <Building2 size={14} strokeWidth={1.8} color={semantic.verified} />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </SoftBox>
            <View style={s.headerText}>
              <Text style={s.projectName} numberOfLines={1}>
                {siteProject?.name || 'Project'}
              </Text>
              <Text style={s.headerDate}>{todayLabel()}</Text>
            </View>
          </View>
          <SoftPebble onPress={handleLogout} hitSlop={12} accessibilityLabel="Log out">
            <LogOut size={18} strokeWidth={1.8} color={INK} />
          </SoftPebble>
        </View>

        {/* Main Content */}
        <View style={s.content}>
          {/* WHAT THIS TABLET CAN BE TRUSTED TO HOLD, said first and said here.
              This is the screen somebody is on when he decides whether to take
              the device off the wifi, so the device-level fact goes above the
              tiles rather than being discovered inside one of them. Silent
              whenever the tablet is complete and current -- and, here only,
              while it is merely still filling: the panel below says that one. */}
          <SiteReadinessNotice readiness={readiness} hideFilling style={s.offlineBanner} />

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
          {/* TODAY ON SITE — the day at a glance for anyone walking past. */}
          <SoftBox kind="card" contentStyle={s.panel}>
            <Text style={s.panelTitle}>TODAY ON SITE</Text>
            <View style={s.statRow}>
              <View style={s.stat}>
                <Text style={[s.statValue, { color: semantic.verified }, workersState !== 'ok' && s.statUnknown]}>
                  {countText(workersState, workersOnSite)}
                </Text>
                <Text style={s.statLabel}>workers on site</Text>
              </View>
              <View style={s.stat}>
                <Text style={[s.statValue, { color: semantic.attention }, logsState !== 'ok' && s.statUnknown]}>
                  {countText(logsState, todayLogsCount)}
                </Text>
                <Text style={s.statLabel}>logs today</Text>
              </View>
              {savedValue ? (
                <View style={s.stat}>
                  <Text style={s.statValue}>{savedValue}</Text>
                  <Text style={s.statLabel}>saved to tablet</Text>
                </View>
              ) : null}
            </View>
            {stillSaving ? (
              <Text style={s.panelNote}>
                Still saving {Math.max(0, (readiness.expected || 0) - (readiness.saved || 0))} files — the tablet keeps going by itself while it has Wi-Fi. Anything not saved yet will not open without signal.
              </Text>
            ) : null}
          </SoftBox>

          <View style={s.tiles}>
            {TILES.map(({ key, path, Icon, label, tint }) => (
              <SoftBox
                key={key}
                kind="card"
                onPress={() => handleNavigate(path)}
                style={s.tile}
                contentStyle={s.tileInner}
                accessibilityRole="button"
                accessibilityLabel={label}
              >
                <SoftBox kind="well" style={s.iconWell} contentStyle={s.iconWellInner}>
                  <Icon size={48} strokeWidth={1.6} color={tint} />
                </SoftBox>
                <Text style={s.tileLabel} numberOfLines={1}>{label}</Text>
                <ChevronRight size={28} strokeWidth={1.8} color={MUTED} />
              </SoftBox>
            ))}
          </View>

          {/* Tier 1 ③ Inspector Mode — hand-off toggle. This dashboard is
              site_device-only, so the control is always shown here. One
              tap confines the app to the read-only logbooks tab; the
              Exit control there releases it. Full width, its own words on
              two lines, and never under the Android bar (SafeAreaView bottom). */}
          <SoftBox
            kind="slim"
            onPress={handleLockPress}
            style={s.lockBtn}
            contentStyle={s.lockInner}
            accessibilityRole="button"
            accessibilityLabel="Hand to Inspector, read-only"
          >
            <View style={s.lockIcon}>
              <Lock size={22} strokeWidth={2} color={semantic.attention} />
            </View>
            <View style={s.lockText}>
              <Text style={s.lockTitle}>Hand to Inspector</Text>
              <Text style={s.lockSub}>Locks this tablet to read-only Log Books</Text>
            </View>
            <ChevronRight size={26} strokeWidth={1.8} color={MUTED} />
          </SoftBox>
        </View>
      </SafeAreaView>
      {logoutDialog}
    </AnimatedBackground>
  );
}

// The site tablet is held to the light theme, so its ink is fixed.
const INK = '#1C2B38';
const MUTED = 'rgba(28,43,56,0.62)';

function todayLabel() {
  try {
    return new Date().toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/New_York',
    });
  } catch (_e) {
    return '';
  }
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.xl,
      paddingTop: spacing.md,
      paddingBottom: spacing.lg,
      gap: spacing.md,
    },
    headerLeft: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    headerText: { flex: 1 },
    siteBadge: { width: 150 },
    siteBadgeInner: { height: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
    siteBadgeText: { fontSize: 12, fontWeight: '700', letterSpacing: 1.5, color: semantic.verified },
    projectName: { fontSize: 20, fontWeight: '700', color: INK },
    headerDate: { fontSize: 13, color: MUTED, marginTop: 2 },
    content: { flex: 1, paddingHorizontal: spacing.xl, paddingBottom: spacing.lg, gap: spacing.lg },
    offlineBanner: { marginTop: 0, marginBottom: 0 },
    panel: { paddingHorizontal: spacing.xl, paddingVertical: spacing.lg, gap: spacing.md },
    panelTitle: { fontSize: 14, fontWeight: '700', letterSpacing: 2, color: MUTED },
    statRow: { flexDirection: 'row' },
    stat: { flex: 1, alignItems: 'center' },
    statValue: { fontFamily: typography.display, fontSize: 40, fontWeight: '800', color: INK },
    statUnknown: { fontSize: 20, color: semantic.attention, paddingVertical: 12 },
    statLabel: { fontSize: 14, color: MUTED, marginTop: 2 },
    panelNote: { fontSize: 14, color: MUTED, textAlign: 'center' },
    tiles: { flex: 1, gap: spacing.lg },
    tile: { flex: 1 },
    tileInner: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.xl,
      gap: spacing.xl,
    },
    iconWell: { width: 104, height: 104 },
    iconWellInner: { width: 104, height: 104, alignItems: 'center', justifyContent: 'center' },
    tileLabel: { flex: 1, fontFamily: typography.display, fontSize: 30, fontWeight: '800', color: INK },
    lockBtn: { minHeight: 84 },
    lockInner: {
      minHeight: 84,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.xl,
      gap: spacing.lg,
    },
    lockIcon: {
      width: 48,
      height: 48,
      borderRadius: 24,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: withAlpha(semantic.attention, 0.14),
    },
    lockText: { flex: 1 },
    lockTitle: { fontSize: 22, fontWeight: '800', color: INK },
    lockSub: { fontSize: 15, color: MUTED, marginTop: 2 },
  });
}
