import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Image } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Users,
  Building2,
  Briefcase,
  Clock,
  MapPin,
  ShieldAlert,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { WorkerCardSkeleton, StatCardSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useWorkers } from '../src/hooks/useWorkers';
import { useProjects } from '../src/hooks/useProjects';
import OfflineIndicator from '../src/components/OfflineIndicator';
import OfflineNotice from '../src/components/OfflineNotice';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';
import HeaderBrand from '../src/components/HeaderBrand';
import { semantic, withAlpha } from '../src/styles/semanticColors';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { checkinsAPI } from '../src/utils/api';
import { settleFetch } from '../src/utils/offlineState';

/**
 * OFFLINE SIGN-IN LOG.
 *
 * useCheckIns().getTodayCheckIns() catches its own error and returns [], so a
 * dead zone rendered "No check-ins recorded for this date" and "0 Workers" —
 * a confident, false claim about who was on site. The API call is made
 * directly here so the rejection is visible, then classified by settleFetch:
 *   ok      -> render + write through to AsyncStorage
 *   offline -> serve the saved roster for that date, labelled as saved
 *   error   -> say so; never an empty state
 */
const CHECKINS_PREFIX = 'bv_checkins:';

// Same New York calendar date the API is queried with (checkinsAPI.getByDate),
// so the cache key and the request can never disagree about "which day".
const dayKey = (date) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(date);

async function cacheCheckIns(date, list) {
  if (!Array.isArray(list)) return;
  try {
    await AsyncStorage.setItem(`${CHECKINS_PREFIX}${dayKey(date)}`, JSON.stringify(list));
  } catch (_e) { /* non-fatal — the network read still succeeded */ }
}

async function readCachedCheckIns(date) {
  try {
    const raw = await AsyncStorage.getItem(`${CHECKINS_PREFIX}${dayKey(date)}`);
    const list = raw ? JSON.parse(raw) : null;
    return Array.isArray(list) ? list : null;
  } catch (_e) {
    return null;
  }
}

/**
 * FIX 1 — the SPECIFIC reasons a worker was admitted with warnings.
 *
 * Reads fields that already exist on the check-in row GET /api/checkins
 * returns (sst_status and needs_trade_assignment are written at check-in;
 * review_decision by /checkins/{id}/review). Nothing new is stored and
 * nothing is derived that the server did not report.
 *
 * Never returns a generic "flagged" — an unnamed warning is not a warning.
 * BLOCKED workers (missing OSHA) are not represented here at all: they never
 * completed sign-in, so they have no check-in row on this screen.
 */
function checkinWarnings(checkin) {
  const reasons = [];
  if (checkin?.sst_status === 'expired') reasons.push('Expired SST card');
  if (checkin?.sst_status === 'unknown') reasons.push('Unknown SST card');
  if (checkin?.needs_trade_assignment) reasons.push('No trade assigned');
  return reasons;
}

export default function WorkersScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [selectedDate, setSelectedDate] = useState(() => new Date());

// Use hooks for data
  const [checkInsLoading, setCheckInsLoading] = useState(true);
  const loading = checkInsLoading;
  const { projects, loading: projectsLoading } = useProjects();
  const [todayCheckIns, setTodayCheckIns] = useState([]);
  // 'ok' | 'offline' | 'error' — 'ok' is the ONLY state allowed to render the
  // "No check-ins recorded" empty state.
  const [fetchState, setFetchState] = useState('ok');
  const [fromCache, setFromCache] = useState(false);

  const formatTime = (isoString) => {
    if (!isoString) return '--:--';
    return new Date(isoString).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York',
    });
  };

  const formatDate = (date) => {
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  };

  const isToday = selectedDate.toDateString() === new Date().toDateString();

  const goToPreviousDay = () => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() - 1);
    setSelectedDate(newDate);
  };

  const goToNextDay = () => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() + 1);
    if (newDate <= new Date()) setSelectedDate(newDate);
  };

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch the selected date's check-ins (cache-first fallback, write-through)
  const fetchCheckIns = async (date) => {
    setCheckInsLoading(true);
    const r = await settleFetch(() => checkinsAPI.getByDate(date));

    if (r.status === 'ok') {
      const list = Array.isArray(r.data) ? r.data : [];
      setTodayCheckIns(list);
      setFetchState('ok');
      setFromCache(false);
      cacheCheckIns(date, list); // write-through
    } else {
      console.error('Failed to fetch check-ins:', r.error);
      const cached = await readCachedCheckIns(date);
      setTodayCheckIns(cached || []);
      setFetchState(r.status);
      setFromCache(!!cached);
    }
    setCheckInsLoading(false);
  };

  useEffect(() => {
    if (isAuthenticated) {
      fetchCheckIns(selectedDate);
    }
  }, [isAuthenticated, selectedDate]);

  const uniqueProjects = new Set(todayCheckIns.map((c) => c.projectName || c.projectId)).size;
  const uniqueCompanies = new Set(todayCheckIns.map((c) => c.workerCompany)).size;

  const getWorkerInfo = (checkin) => ({
    name: checkin.worker_name || checkin.workerName || checkin.name || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.workerTrade || checkin.trade || 'General',
    company: checkin.worker_company || checkin.workerCompany || checkin.company || 'Unknown Company',
    project: checkin.project_name || checkin.projectName || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkInTime || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkOutTime || checkin.checkout_time,
  });

  const statItems = [
    { icon: Users, value: todayCheckIns.length, label: 'Workers' },
    { icon: Building2, value: uniqueProjects, label: 'Projects' },
    { icon: Briefcase, value: uniqueCompanies, label: 'Companies' },
  ];

  // FIX 1 — roll the per-row reasons up into one soft banner. It states what
  // is open; it gates nothing on this screen.
  const warningSummary = (() => {
    const tally = new Map();
    for (const c of todayCheckIns) {
      for (const r of checkinWarnings(c)) tally.set(r, (tally.get(r) || 0) + 1);
    }
    return [...tally.entries()].map(([reason, n]) => `${n} ${reason.toLowerCase()}`);
  })();

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <HeaderBrand />
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
          </View>
        </View>
          
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>DAILY</Text>
            <Text style={s.titleText}>Sign-In Log</Text>
          </View>

          {/* Date Selector */}
          <View style={s.dateSelector}>
            <GlassButton
              variant="icon"
              icon={<ChevronLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToPreviousDay}
            />
            <View style={s.dateDisplay}>
              <Calendar size={20} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.dateText}>{formatDate(selectedDate)}</Text>
              {isToday && (
                <View style={s.todayBadge}>
                  <Text style={s.todayText}>TODAY</Text>
                </View>
              )}
            </View>
            <GlassButton
              variant="icon"
              icon={<ChevronRight size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToNextDay}
              disabled={isToday}
              style={isToday && s.disabledButton}
            />
          </View>

          {/* Stats */}
          <View style={s.statsRow}>
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
                  <StatCard key={stat.label} style={s.statCard}>
                    <IconPod size={36} style={s.statIcon}>
                      <Icon size={16} strokeWidth={1.5} color={colors.text.secondary} />
                    </IconPod>
                    <Text style={s.statValue}>{stat.value}</Text>
                    <Text style={s.statLabel} numberOfLines={1}>{stat.label.toUpperCase()}</Text>
                  </StatCard>
                );
              })
            )}
          </View>

          {/* Offline / error banner — the stats above and the list below are
              only as honest as this fetch was. */}
          {!loading && fetchState !== 'ok' && (
            <OfflineNotice
              mode={fetchState}
              cachedCount={fromCache ? todayCheckIns.length : 0}
              detail={
                fetchState === 'error'
                  ? 'Could not load the sign-in log for this date. The counts above are not a record of who was on site.'
                  : fromCache
                    ? `Offline — showing the sign-in log saved on this device for ${formatDate(selectedDate)}. Anyone who signed in since then is not listed.`
                    : 'Offline — this date was never loaded on this device, so there is nothing saved. This is NOT a record that nobody signed in.'
              }
            />
          )}

          {/* FIX 1 — admitted-with-warnings summary. Soft and non-blocking:
              these workers ARE on site and stay listed below; the banner only
              names what is still open. Only rendered on an answered fetch, so
              it can never make a claim from a failed read. */}
          {!loading && fetchState === 'ok' && warningSummary.length > 0 && (
            <View style={s.warnBanner}>
              <ShieldAlert size={16} strokeWidth={2} color={semantic.attention} />
              <View style={{ flex: 1 }}>
                <Text style={s.warnTitle}>Admitted with warnings</Text>
                <Text style={s.warnBody}>{warningSummary.join(' · ')}</Text>
              </View>
            </View>
          )}

          {/* Checkins List */}
          <View style={s.checkinsList}>
            {loading ? (
              <>
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
              </>
            ) : todayCheckIns.length > 0 ? (
              Object.entries(
                todayCheckIns.reduce((acc, checkin) => {
                  const info = getWorkerInfo(checkin);
                  if (!acc[info.company]) acc[info.company] = [];
                  acc[info.company].push(checkin);
                  return acc;
                }, {})
              ).map(([company, companyCheckins]) => (
                <View key={company} style={s.companyGroup}>
                  <Text style={s.companyHeader}>{company}</Text>
                  {companyCheckins.map((checkin, index) => {
                    const workerInfo = getWorkerInfo(checkin);
                    const initials = workerInfo.name
                      .split(' ')
                      .map((n) => n[0])
                      .join('')
                      .toUpperCase();

                    return (
                      <GlassListItem
                        key={checkin._id || checkin.id || index}
                        style={s.checkinCard}
                        contentStyle={s.checkinCardContent}
                        onPress={() => {
                          const workerId = checkin.worker_id;
                          if (workerId) {
                            // THE PROJECT CONTEXT THIS ROW ALREADY HAD.
                            //
                            // The worker detail screen has no project in its
                            // route, so it rendered "No trade specified / No
                            // company" off the workers document -- fields
                            // nothing writes, because a trade belongs to the
                            // {worker, project} PAIR.
                            //
                            // This row is a CHECK-IN, and the server resolved
                            // that pairing through _get_worker_project_trade
                            // when it was written (server.py:12780) and stamped
                            // it on as worker_trade / worker_company. The
                            // context was in hand and only the worker id was
                            // forwarded.
                            router.push({
                              pathname: `/workers/${workerId}`,
                              params: {
                                projectId: checkin.project_id || '',
                                projectName: checkin.project_name || checkin.projectName || '',
                                trade: checkin.worker_trade || '',
                                company: checkin.worker_company || '',
                              },
                            });
                          }
                        }}
                      >
                        {/* Time */}
                        <View style={s.timeSection}>
                          <Text style={s.timeText} numberOfLines={1}>{formatTime(workerInfo.checkInTime)}</Text>
                          {workerInfo.checkOutTime && (
                            <Text style={s.timeOutText} numberOfLines={1}>Out: {formatTime(workerInfo.checkOutTime)}</Text>
                          )}
                        </View>

                        <View style={s.divider} />

                        {/* Worker Info */}
                        <View style={s.workerInfo}>
                          <View style={s.workerHeader}>
                            <View style={s.avatar}>
                              <Text style={s.avatarText}>{initials}</Text>
                            </View>
                            <View style={s.workerDetails}>
                              <Text style={s.workerName} numberOfLines={2} ellipsizeMode="tail">{workerInfo.name}</Text>
                              <Text style={s.workerTrade} numberOfLines={1} ellipsizeMode="tail">{workerInfo.trade}</Text>
                            </View>
                          </View>
                          <View style={s.workerMeta}>
                            <View style={s.metaItem}>
                              <MapPin size={12} strokeWidth={1.5} color={colors.text.subtle} />
                              <Text style={s.metaText} numberOfLines={1} ellipsizeMode="tail">{workerInfo.project}</Text>
                            </View>
                            <View style={s.metaItem}>
                              <Building2 size={12} strokeWidth={1.5} color={colors.text.subtle} />
                              <Text style={s.metaText} numberOfLines={1} ellipsizeMode="tail">{workerInfo.company}</Text>
                            </View>
                          </View>

                          {/* FIX 1 — the specific reason(s) this worker was
                              admitted with warnings, plus the CP's decision if
                              one has been recorded. Never the word "flagged". */}
                          {checkinWarnings(checkin).map((reason) => (
                            <View key={reason} style={s.warnRow}>
                              <ShieldAlert size={11} strokeWidth={2} color={semantic.attention} />
                              <Text style={s.warnRowText} numberOfLines={1}>{reason}</Text>
                            </View>
                          ))}
                          {checkinWarnings(checkin).length > 0 && checkin.review_decision ? (
                            <Text style={s.warnDecision} numberOfLines={1}>
                              {checkin.review_decision === 'approved'
                                ? 'Approved by CP'
                                : 'Denied — recorded as sent home'}
                            </Text>
                          ) : null}
                        </View>

                        {/* Status */}
                        <View
                          style={[
                            s.statusBadge,
                            !workerInfo.checkOutTime && s.statusActive,
                          ]}
                        >
                          {!workerInfo.checkOutTime ? (
                            <>
                              <View style={s.statusDot} />
                              <Text style={s.statusText} numberOfLines={1}>ON-SITE</Text>
                            </>
                          ) : (
                            <>
                              <Clock size={12} strokeWidth={1.5} color={colors.text.subtle} />
                              <Text style={[s.statusText, s.statusDone]} numberOfLines={1}>DONE</Text>
                            </>
                          )}
                        </View>
                      </GlassListItem>
                    );
                  })}
                </View>
              ))
            ) : fetchState === 'ok' ? (
              // Only an ANSWERED server response earns the empty state.
              <View style={s.emptyState}>
                <Users size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>No check-ins recorded for this date</Text>
              </View>
            ) : (
              <View style={s.emptyState}>
                <GlassButton title="Retry" onPress={() => fetchCheckIns(selectedDate)} />
              </View>
            )}
          </View>
        </ScrollView>

        <FloatingNav />
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
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
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
  titleSection: {
    marginBottom: spacing.xl,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  dateSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  dateDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dateText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  todayBadge: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  todayText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  disabledButton: {
    opacity: 0.3,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  statCard: {
    flex: 1,
    alignItems: 'center',
  },
  statIcon: {
    marginBottom: spacing.md,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    color: colors.text.muted,
    fontSize: 9,
    letterSpacing: 0.8,
  },
  checkinsList: {
    gap: spacing.sm,
  },
  // FIX 1 — admitted-with-warnings surfaces (soft; they gate nothing).
  warnBanner: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    backgroundColor: semantic.attentionBg,
  },
  warnTitle: { fontSize: 13, fontWeight: '700', color: semantic.attention },
  warnBody: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  warnRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
  warnRowText: { flex: 1, fontSize: 11, fontWeight: '600', color: semantic.attention },
  warnDecision: { fontSize: 11, color: colors.text.muted, marginTop: 2 },
  // Cards inside one company group used to be bare siblings with no gap, so
  // they visually touched. This gap is what separates card-from-card.
  companyGroup: {
    gap: spacing.sm + 2,
  },
  companyHeader: {
    color: colors.text.muted,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    paddingVertical: 8,
    paddingHorizontal: 4,
    marginTop: 8,
  },
  // NOTE: this is the OUTER Pressable of GlassListItem — it must NOT carry its
  // own padding, because GlassListItem already pads its inner content View
  // (see checkinCardContent). The previous `padding: spacing.md` here stacked on
  // top of that inner spacing.lg for 40px of inset per side, which is what
  // squeezed the name column down to a few px and forced 3-line wraps.
  checkinCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  // Row budget @ 375px: 375 − scrollContent (24×2) = 327 card width.
  //   327 − paddingHorizontal (16×2)                       = 295 content
  //   295 − timeSection (58) − divider (1 + 8×2 margin)    = 220
  //   220 − statusBadge (~74 incl. padding/dot/border)     = 146 for workerInfo
  //   146 − avatar (34) − gap (8)                          = 104 for the name
  // 104px @ 15px fits ~13 chars per line × 2 lines — long names ellipsise
  // instead of stacking to 3 lines.
  checkinCardContent: {
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.md,
  },
  timeSection: {
    width: 58,
    flexShrink: 0,
    alignItems: 'center',
  },
  timeText: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  timeOutText: {
    fontSize: 10,
    color: colors.text.subtle,
    marginTop: 2,
  },
  divider: {
    width: 1,
    height: 40,
    backgroundColor: colors.glass.border,
    marginHorizontal: spacing.sm,
  },
  workerInfo: {
    flex: 1,
    minWidth: 0,
  },
  workerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  avatar: {
    width: 34,
    height: 34,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarText: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  workerDetails: {
    flex: 1,
    minWidth: 0,
  },
  workerName: {
    fontSize: 15,
    lineHeight: 19,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTrade: {
    fontSize: 12,
    lineHeight: 15,
    color: colors.text.muted,
  },
  workerMeta: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  metaItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    flexShrink: 1,
    minWidth: 0,
  },
  metaText: {
    fontSize: 11,
    color: colors.text.subtle,
    flexShrink: 1,
  },
  // flexShrink:0 keeps the pill at its natural size — previously it was the
  // last flex child in a starved row and got crushed onto two lines.
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    flexShrink: 0,
    gap: spacing.xs,
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 5,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statusActive: {
    backgroundColor: withAlpha('#ffffff', 0.1),
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.text.secondary,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
  },
  statusDone: {
    color: colors.text.subtle,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: spacing.xxl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    color: colors.text.muted,
  },
  });
}
