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
import {
  checkinCompany, checkinProject, checkinWorker,
  distinctCompanies, distinctProjects,
} from '../src/utils/checkinFields';
import { sstFlagCopy } from '../src/utils/sstFlagCopy';

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
 * WHICH SST STATE THIS ROW IS JUDGED ON — the live cert, not the snapshot.
 *
 * `sst_status` is frozen onto the check-in at tap time and, by design, NEVER
 * refreshed: it is the durable compliance artifact, and the filed LL196
 * register freezes its UNVERIFIED marker off it. Angel Lopez's card was
 * repaired at 12:33 and his 06:57 row went on printing "Unknown SST card" for
 * the rest of the day. THAT ROW IS NOT WRONG — it is a truthful record of what
 * was known at 06:57, and nothing here rewrites it. The roster simply asks a
 * different question: not "what was known then" but "what needs doing now".
 *
 * `sst_status_live` / `sst_review_reason` are added beside the frozen fields
 * by GET /api/checkins (server.py `_live_sst_fields`), derived through the
 * gate's own rules.
 *
 * WHEN THEY ARE ABSENT there is no live answer — an old payload in the
 * AsyncStorage cache, written before this change, or an offline read. The
 * frozen pair is shown instead and DATED (`asOf`). It is never worn as
 * current: a reason from 06:57 that says the expiry is unknown may already be
 * false, and a stale sentence in today's voice is worse than an honestly
 * dated one.
 */
function sstBadge(checkin) {
  const live = checkin?.sst_status_live;
  if (live) {
    // THE FROZEN `sst_unknown_reason` IS DELIBERATELY NOT PASSED, and that
    // omission is half the repair. It is the coarse CLASS|EXPIRY|BOTH code
    // recorded at the gate; handing it to sstFlagCopy beside a live
    // review_reason re-asserts the half that has since been fixed. Juan
    // Lopez's row froze BOTH and his expiry is now on file — passing it would
    // print "the card class AND the expiry date could not be confirmed" about
    // a card of which only the class is open.
    return sstFlagCopy({ sstStatus: live, reviewReason: checkin?.sst_review_reason });
  }
  const frozen = sstFlagCopy({
    sstStatus: checkin?.sst_status,
    unknownReason: checkin?.sst_unknown_reason,
  });
  return frozen ? { ...frozen, asOf: 'as recorded at check-in' } : null;
}

/**
 * ADMITTED WITH A WARNING THAT HAS SINCE BEEN CLEARED.
 *
 * The roster stops WARNING about a card the cert row now supports — there is
 * nothing left for the CP to do about it, and a warning he cannot act on is
 * what trains him to ignore the ones he can. But "this man was let in on a
 * card the app could not read" is a compliance fact about this check-in, and
 * it must not simply vanish off the screen when the card is repaired. So it is
 * stated quietly, in the past tense, and it is NOT a warning: no attention
 * colour, no shield, no place in the banner tally above the list.
 *
 * REQUIRES BOTH READINGS. Without a live one we cannot know anything was
 * resolved; without a frozen one that actually raised something there is
 * nothing to have resolved. Rows where the two agree get no note — a note on
 * every clean row says nothing at all.
 *
 * NOT THE OTHER DIRECTION. Frozen-clean + live-flagged is a card that lapsed
 * or was re-read SINCE the tap; that is a live warning, handled above, and it
 * is emphatically not a resolution.
 */
function checkinResolvedNote(checkin) {
  if (!checkin?.sst_status_live) return null;
  const wasFlagged = !!sstFlagCopy({ sstStatus: checkin?.sst_status });
  const isFlagged = !!sstFlagCopy({ sstStatus: checkin.sst_status_live });
  if (!wasFlagged || isFlagged) return null;
  return 'SST card flagged at check-in — resolved since';
}

/**
 * FIX 1 — the SPECIFIC reasons a worker is still flagged.
 *
 * The two SST sentences used to be hardcoded here, read straight off the
 * frozen snapshot:
 *
 *     if (sst_status === 'expired') reasons.push('Expired SST card');
 *     if (sst_status === 'unknown') reasons.push('Unknown SST card');
 *
 * Both are gone. The words now come from src/utils/sstFlagCopy.js — the same
 * module the CP's pre-shift roster and the gate's check-in screen already
 * read, so one card is described one way wherever it is looked at. The copy
 * rules are decided there and are not restated here.
 *
 * `key` is the tally bucket for the banner above the list; `label` and
 * `detail` are what one row prints. They are separated because the banner
 * COUNTS rows and a row EXPLAINS one card, and a single string cannot do both
 * without the banner growing a sentence per worker.
 *
 * Never returns a generic "flagged" — an unnamed warning is not a warning.
 * BLOCKED workers (missing OSHA) are not represented here at all: they never
 * completed sign-in, so they have no check-in row on this screen.
 */
export function checkinWarnings(checkin) {
  const out = [];
  const sst = sstBadge(checkin);
  if (sst) {
    out.push({ key: sst.title, label: sst.title, detail: sst.detail, asOf: sst.asOf });
  }
  if (checkin?.needs_trade_assignment) {
    out.push({ key: 'No trade assigned', label: 'No trade assigned', detail: '', asOf: null });
  }
  return out;
}

// EXPORTED SO A TEST CAN RUN THEM, not because anything else imports them.
// src/utils/rosterBadgeReadsLiveCert.test.cjs executes these two against
// Angel's and Juan's real documents; a source scan can see that this file now
// imports sstFlagCopy but cannot see WHICH fields it hands over, and handing
// over the frozen reason is precisely the defect. Same reason
// preshift_signin.jsx exports SstFlagLines.
export { checkinResolvedNote };

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

  // BOTH OF THESE COUNTED ONE `undefined`. They read `c.projectName` and
  // `c.workerCompany` -- camelCase -- against an API that returns snake_case
  // (`project_name`, `worker_company`). Every row mapped to undefined, so
  // `new Set([undefined, ...]).size` was 1 for ANY non-empty roster, however
  // many companies were on site. Four lines below, getWorkerInfo read the
  // same fields correctly, so the ROWS named the right companies while the
  // COUNTER above them said 1.
  const uniqueProjects = distinctProjects(todayCheckIns);
  const uniqueCompanies = distinctCompanies(todayCheckIns);

  // The row renderer and the counters now read through ONE helper, so the
  // two cannot disagree about which field carries the company again.
  const getWorkerInfo = (checkin) => ({
    name: checkinWorker(checkin) || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.workerTrade || checkin.trade || 'General',
    company: checkinCompany(checkin) || 'Unknown Company',
    project: checkinProject(checkin) || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkInTime || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkOutTime || checkin.checkout_time,
  });

  const statItems = [
    { icon: Users, value: todayCheckIns.length, label: 'Workers' },
    { icon: Building2, value: uniqueProjects, label: 'Projects' },
    // "Companies on site", not "Subcontractors": the gate records no GC flag,
    // so the data cannot tell a general contractor's own crew from a sub's.
    // The number this can honestly produce is distinct companies at the gate.
    { icon: Briefcase, value: uniqueCompanies, label: 'Companies on site' },
  ];

  // FIX 1 — roll the per-row reasons up into one soft banner. It states what
  // is open; it gates nothing on this screen.
  //
  // KEYED ON `key`, NOT on the rendered label: the label can now carry an
  // "as recorded at check-in" tail on a cached row, and tallying that would
  // split one reason into two buckets purely because some rows were read
  // offline. The banner counts REASONS; how each row came to be read is the
  // row's business.
  //
  // A RESOLVED NOTE IS NOT COUNTED HERE. It is not open work, and putting it
  // in a banner headed "Admitted with warnings" would re-raise as a warning
  // the very thing this screen just stopped warning about.
  const warningSummary = (() => {
    const tally = new Map();
    for (const c of todayCheckIns) {
      for (const w of checkinWarnings(c)) tally.set(w.key, (tally.get(w.key) || 0) + 1);
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
                    // Computed ONCE per row. Both used to be called twice in
                    // the JSX below, so the list and the decision line each
                    // re-derived the same answer — and could have disagreed if
                    // either ever stopped being pure.
                    const warnings = checkinWarnings(checkin);
                    const resolvedNote = checkinResolvedNote(checkin);
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

                          {/* FIX 1 — the specific reason(s) this worker is
                              still flagged, plus the CP's decision if one has
                              been recorded. Never the word "flagged".

                              The title says WHAT is open and the detail line
                              says WHICH HALF of the card it is about; the CP
                              cannot act on "not confirmed" but can act on "the
                              class was read from the colour". Two lines
                              because they are two different facts — collapsing
                              them into one truncated row is how the detail
                              would be the part that gets cut. */}
                          {warnings.map((w) => (
                            <View key={w.key} style={s.warnRow}>
                              <ShieldAlert size={11} strokeWidth={2} color={semantic.attention} />
                              <View style={s.warnRowBody}>
                                <Text style={s.warnRowText} numberOfLines={1}>
                                  {w.asOf ? `${w.label} (${w.asOf})` : w.label}
                                </Text>
                                {w.detail ? (
                                  <Text style={s.warnRowDetail} numberOfLines={2}>{w.detail}</Text>
                                ) : null}
                              </View>
                            </View>
                          ))}
                          {/* MUTED, AND NOT A WARNING ROW. No shield and no
                              attention colour: the point of the note is that
                              there is nothing to do, while still recording on
                              screen that this man was admitted on a card the
                              app could not read at the time. */}
                          {resolvedNote ? (
                            <Text style={s.resolvedNote} numberOfLines={2}>{resolvedNote}</Text>
                          ) : null}
                          {/* THE DECISION OUTLIVES THE WARNING IT WAS MADE
                              ABOUT. Gating this on `warnings.length > 0`
                              alone would make the CP's recorded call disappear
                              from Angel's row the moment his card was
                              repaired — erasing who decided what, which is the
                              one thing a review is for. */}
                          {(warnings.length > 0 || resolvedNote) && checkin.review_decision ? (
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
  // `flex-start`, not `center`: the row is now two lines tall on a card that
  // has a reason to give, and centring would float the shield beside the gap
  // between them instead of beside the title it belongs to.
  warnRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 4, marginTop: 3 },
  warnRowBody: { flex: 1 },
  warnRowText: { fontSize: 11, fontWeight: '600', color: semantic.attention },
  // SECONDARY, NOT ATTENTION-COLOURED. The title already carries the alarm;
  // painting the explanation the same amber makes a two-line block that reads
  // as two warnings.
  warnRowDetail: { fontSize: 11, color: colors.text.secondary, marginTop: 1 },
  warnDecision: { fontSize: 11, color: colors.text.muted, marginTop: 2 },
  // Muted and unadorned — see checkinResolvedNote. This is a record, not a
  // request, and it must not compete with the rows above it.
  resolvedNote: { fontSize: 11, color: colors.text.muted, marginTop: 3, fontStyle: 'italic' },
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
