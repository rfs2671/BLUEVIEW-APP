import { Home } from 'lucide-react-native';
import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  Users,
  Building2,
  Clock,
  MapPin,
  RefreshCw,
  LogOut,
  AlertTriangle,
  Check,
  X,
  CloudOff,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton, StatCardSkeleton } from '../../src/components/GlassSkeleton';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { checkinsAPI } from '../../src/utils/api';
import { settleFetch, isOfflineError, failureDetail } from '../../src/utils/offlineState';
import {
  queueCheckInReview,
  getQueuedCheckInReviews,
  clearQueuedCheckInReview,
} from '../../src/utils/offlineQueue';
import { useNetworkStatus } from '../../src/hooks/useNetworkStatus';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';

/**
 * Today's roster, cached on device.
 *
 * Same pure-AsyncStorage write-through / cache-first shape as
 * src/utils/projectCache.js — no native module, OTA-deliverable. Without it a
 * site tablet in a dead zone rendered "No Check-Ins Today" over 0/0 stats,
 * which asserts that nobody is on site.
 */
const CHECKINS_CACHE_PREFIX = 'bv_checkins_today:';

/** America/New_York calendar day — the same zone this screen formats times in. */
const todayKey = () => {
  try {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  } catch (_e) {
    return new Date().toISOString().slice(0, 10);
  }
};

async function cacheTodayCheckins(projectId, list) {
  if (!projectId || !Array.isArray(list)) return;
  try {
    await AsyncStorage.setItem(
      `${CHECKINS_CACHE_PREFIX}${projectId}`,
      JSON.stringify({ date: todayKey(), items: list }),
    );
  } catch (_e) { /* non-fatal — the read that produced this still succeeded */ }
}

async function readCachedTodayCheckins(projectId) {
  if (!projectId) return [];
  try {
    const raw = await AsyncStorage.getItem(`${CHECKINS_CACHE_PREFIX}${projectId}`);
    const parsed = raw ? JSON.parse(raw) : null;
    // Yesterday's roster is NOT today's roster — never present it as one.
    if (!parsed || parsed.date !== todayKey()) return [];
    return Array.isArray(parsed.items) ? parsed.items : [];
  } catch (_e) {
    return [];
  }
}

/**
 * Overlay decisions that are recorded on this device but not yet posted, and
 * clear the marker from anything the queue has since drained.
 */
const withPendingReviews = (list, pending) => list.map((c) => {
  const queued = pending && pending[c._id || c.id];
  if (queued) {
    return {
      ...c,
      review_decision: queued.decision,
      // No server attribution yet — it is derived from the token on sync.
      reviewed_by_name: null,
      reviewed_at: null,
      review_pending_sync: true,
    };
  }
  return c.review_pending_sync ? { ...c, review_pending_sync: false } : c;
});

export default function SiteCheckInsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject, logout } = useAuth();
  const toast = useToast();

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const { isOnline } = useNetworkStatus();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [checkins, setCheckins] = useState([]);
  const [stats, setStats] = useState({ total: 0, active: 0 });
  // Check-in id currently being reviewed (disables its buttons mid-request).
  const [reviewingId, setReviewingId] = useState(null);
  // 'ok' | 'offline' | 'error' — a failed load is NEVER an empty roster.
  const [fetchState, setFetchState] = useState('ok');
  // True when what's on screen came from the device cache, not the server.
  const [fromCache, setFromCache] = useState(false);
  const wasOfflineRef = useRef(false);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (!siteMode) {
      router.replace('/');
    }
  }, [isAuthenticated, authLoading, siteMode]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchData();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  // Write-through: whatever the roster is on screen (including decisions taken
  // offline) is what a restart in a dead zone should show.
  useEffect(() => {
    if (loading || !siteProject?.id) return;
    if (fetchState !== 'ok' && checkins.length === 0) return; // don't clobber a good cache
    cacheTodayCheckins(siteProject.id, checkins);
  }, [checkins, loading, fetchState, siteProject]);

  const applyList = (list) => {
    setCheckins(list);
    setStats({
      total: list.length,
      active: list.filter(c => !c.check_out_time).length,
    });
  };

  // Returns true only when the server actually answered.
  const fetchData = async ({ showSkeleton = true, notify = true } = {}) => {
    if (!siteProject?.id) return false;

    if (showSkeleton) setLoading(true);
    try {
      const pending = await getQueuedCheckInReviews();
      const result = await settleFetch(() => checkinsAPI.getTodayByProject(siteProject.id));

      if (result.status === 'ok') {
        const checkinList = Array.isArray(result.data) ? result.data : [];
        applyList(withPendingReviews(checkinList, pending));
        setFetchState('ok');
        setFromCache(false);
        return true;
      }

      // FAILED load. Serve the saved roster rather than an empty one, and let
      // the UI say it is a saved copy.
      console.error('Failed to fetch check-ins:', result.error);
      const cached = await readCachedTodayCheckins(siteProject.id);
      applyList(withPendingReviews(cached, pending));
      setFetchState(result.status);
      setFromCache(cached.length > 0);

      if (notify) {
        const title = result.status === 'offline' ? 'Offline' : 'Load Error';
        if (cached.length > 0) {
          toast.warning(title, 'Showing the roster saved on this device.');
        } else {
          // failureDetail, not fetchFailureMessage: the latter reads only the
          // STATUS and threw the error away, so a 500 and a 403 said the same
          // thing. The server's own detail is what names the cause.
          toast.error(title, failureDetail(result.status, result.error, "today's check-ins"));
        }
      }
      return false;
    } finally {
      setLoading(false);
    }
  };

  // Back online: the app-level drain (DatabaseContext / setupAutoQueueProcessing)
  // posts queued decisions a couple of seconds after the link stabilises. Re-read
  // once it has, so pending decisions come back as server-recorded.
  useEffect(() => {
    if (!isOnline) {
      wasOfflineRef.current = true;
      return undefined;
    }
    if (!wasOfflineRef.current) return undefined;
    wasOfflineRef.current = false;
    if (!isAuthenticated || !siteMode || !siteProject?.id) return undefined;

    const timer = setTimeout(() => {
      fetchData({ showSkeleton: false, notify: false });
    }, 4000);
    return () => clearTimeout(timer);
  }, [isOnline, isAuthenticated, siteMode, siteProject]);

  const handleRefresh = async () => {
    setRefreshing(true);
    const ok = await fetchData({ showSkeleton: false });
    setRefreshing(false);
    // Only claim success when the refresh actually reached the server. This
    // used to toast "Refreshed" unconditionally, on top of a failed load.
    if (ok) {
      toast.success('Refreshed', 'Check-in data updated');
    }
  };

  const formatTime = (dateStr) => {
    if (!dateStr) return '--:--';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '--:--';
    return d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York',
    });
  };

  // Patch one row in place. Stats are unaffected — a decision doesn't change
  // who is on site.
  const applyDecision = (id, patch) => {
    setCheckins((prev) => prev.map((c) =>
      (c._id || c.id) === id ? { ...c, ...patch } : c,
    ));
  };

  // Record an Approve / Send-home decision on an expired-SST check-in.
  // The worker is NOT blocked either way — "sent_home" records the decision
  // only. Attribution (reviewed_by) is derived server-side from the token.
  const handleReview = async (checkin, decision) => {
    const id = checkin._id || checkin.id;
    if (!id) return;
    setReviewingId(id);
    try {
      const res = await checkinsAPI.review(id, decision);
      // The server has it — drop anything still queued for this check-in.
      await clearQueuedCheckInReview(id);
      // Reflect the recorded decision immediately.
      applyDecision(id, {
        review_decision: res.review_decision,
        reviewed_by_name: res.reviewed_by_name,
        reviewed_at: res.reviewed_at,
        review_pending_sync: false,
      });
      toast.success(
        decision === 'approved' ? 'Approved' : 'Recorded',
        decision === 'approved'
          ? 'Worker approved to stay on site'
          : 'Sent-home decision recorded',
      );
    } catch (error) {
      // A compliance decision is NEVER dropped. If the request never reached a
      // server (dead zone), or the server failed on its own side, record it on
      // the device and let the offline queue post it on reconnect. A 4xx is a
      // real refusal — replaying that would never succeed, so it still errors.
      const status = error?.response?.status;
      if (isOfflineError(error) || status >= 500) {
        await queueCheckInReview(id, decision);
        applyDecision(id, {
          review_decision: decision,
          reviewed_by_name: null,
          reviewed_at: null,
          review_pending_sync: true,
        });
        toast.warning(
          'Saved on device',
          decision === 'approved'
            ? 'Approval saved — it will sync when you are back online.'
            : 'Sent-home decision saved — it will sync when you are back online.',
        );
        return;
      }
      const detail = error?.response?.data?.detail;
      toast.error('Review failed', detail || 'Could not record the decision');
    } finally {
      setReviewingId(null);
    }
  };

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      hour12: true, timeZone: 'America/New_York',
    });
  };

  const getWorkerInfo = (checkin) => ({
    name: checkin.worker_name || checkin.workerName || checkin.name || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.workerTrade || checkin.trade || 'General',
    company: checkin.worker_company || checkin.workerCompany || checkin.company || 'Unknown Company',
    project: checkin.project_name || checkin.projectName || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkInTime || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkOutTime || checkin.checkout_time,
  });

  // Decisions taken on this device that the server has not confirmed yet.
  const pendingCount = checkins.filter((c) => c.review_pending_sync).length;

  const renderPendingDecision = (label) => (
    <View style={s.pendingRow}>
      <CloudOff size={13} strokeWidth={1.8} color={semantic.attention} />
      <Text style={s.pendingText}>{label} — saved on device, will sync</Text>
    </View>
  );

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<Home size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/site')}
            />
            <View style={s.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={s.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <Pressable
            onPress={handleLogout}
            style={s.logoutBtn}
            hitSlop={12}
          >
            <LogOut size={18} strokeWidth={1.5} color="#64748b" />
          </Pressable>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <View style={s.titleRow}>
              <Text style={s.titleLabel}>TODAY'S</Text>
              <GlassButton
                variant="icon"
                icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.muted} />}
                onPress={handleRefresh}
                style={s.refreshBtn}
              />
            </View>
            <Text style={s.titleText}>Check-Ins</Text>
          </View>

          {/* Stats */}
          <View style={s.statsRow}>
            {loading ? (
              <>
                <StatCardSkeleton style={s.statCard} />
                <StatCardSkeleton style={s.statCard} />
              </>
            ) : (
              <>
                <StatCard style={s.statCard}>
                  <Text style={s.statLabel}>TOTAL TODAY</Text>
                  <Text style={s.statValue}>{stats.total}</Text>
                </StatCard>
                <StatCard style={s.statCard}>
                  <View style={s.activeIndicator}>
                    <View style={s.activeDot} />
                    <Text style={s.statLabel}>ON-SITE NOW</Text>
                  </View>
                  <Text style={[s.statValue, s.activeValue]}>{stats.active}</Text>
                </StatCard>
              </>
            )}
          </View>

          {/* A failed load says so — it never renders as an empty roster. */}
          {!loading && fetchState !== 'ok' && (
            <OfflineNotice
              mode={fetchState}
              cachedCount={fromCache ? checkins.length : 0}
              style={s.notice}
            />
          )}

          {/* Decisions held on this device until the queue drains. */}
          {!loading && pendingCount > 0 && (
            <View style={s.pendingBanner}>
              <CloudOff size={14} strokeWidth={1.8} color={semantic.attention} />
              <Text style={s.pendingBannerText}>
                {pendingCount} decision{pendingCount === 1 ? '' : 's'} saved on this device
                {pendingCount === 1 ? ' — it' : ' — they'} will sync automatically.
              </Text>
            </View>
          )}

          {/* Check-ins List */}
          {loading ? (
            <>
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </>
          ) : checkins.length > 0 ? (
            <View style={s.checkinsList}>
              {checkins.map((checkin, index) => {
                const workerInfo = getWorkerInfo(checkin);
                const initials = workerInfo.name
                  .split(' ')
                  .map((n) => n[0])
                  .join('')
                  .toUpperCase();

                // Expired-SST check-ins are allowed in (flag-but-allow) but
                // need an admin/CP decision recorded against them.
                const checkinId = checkin._id || checkin.id;
                const isExpiredSst = checkin.sst_status === 'expired';
                // PR B: an SST whose class/expiry we could not confirm. Its own
                // attention treatment — reuses the expired reviewCard rather
                // than inventing a new pattern — but never reads as expired.
                const isUnknownSst = checkin.sst_status === 'unknown';
                const reviewed = checkin.review_decision;

                return (
                  <View key={checkinId || index}>
                  <GlassListItem
                    style={s.checkinCard}
                  >
                    {/* Time */}
                    <View style={s.timeSection}>
                      <Text style={s.timeText}>{formatTime(workerInfo.checkInTime)}</Text>
                      {workerInfo.checkOutTime && (
                        <Text style={s.timeOutText}>Out: {formatTime(workerInfo.checkOutTime)}</Text>
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
                          <Text style={s.workerName}>{workerInfo.name}</Text>
                          <Text style={s.workerTrade}>{workerInfo.trade}</Text>
                        </View>
                      </View>
                      <View style={s.workerMeta}>
                        <View style={s.metaItem}>
                          <Building2 size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={s.metaText}>{workerInfo.company}</Text>
                        </View>
                      </View>
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
                          <Text style={s.statusText}>ON-SITE</Text>
                        </>
                      ) : (
                        <>
                          <Clock size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={[s.statusText, s.statusDone]}>DONE</Text>
                        </>
                      )}
                    </View>
                  </GlassListItem>

                  {isExpiredSst && (
                    <GlassCard style={s.reviewCard}>
                      <View style={s.reviewHeader}>
                        <AlertTriangle size={14} strokeWidth={1.5} color="#fbbf24" />
                        <Text style={s.reviewTitle}>
                          Expired SST
                          {checkin.sst_expiration
                            ? ` — expired ${String(checkin.sst_expiration).slice(0, 10)}`
                            : ''}
                        </Text>
                      </View>

                      {reviewed ? (
                        checkin.review_pending_sync ? (
                          renderPendingDecision(reviewed === 'approved' ? 'Approved' : 'Sent home')
                        ) : (
                        <Text style={s.reviewedText}>
                          {reviewed === 'approved' ? 'Approved' : 'Sent home'}
                          {checkin.reviewed_by_name ? ` by ${checkin.reviewed_by_name}` : ''}
                          {checkin.reviewed_at ? ` • ${formatDateTime(checkin.reviewed_at)}` : ''}
                        </Text>
                        )
                      ) : (
                        <View style={s.reviewActions}>
                          <Pressable
                            onPress={() => handleReview(checkin, 'approved')}
                            disabled={reviewingId === checkinId}
                            style={[s.reviewBtn, s.approveBtn,
                              reviewingId === checkinId && s.reviewBtnDisabled]}
                          >
                            <Check size={14} strokeWidth={2} color="#4ade80" />
                            <Text style={[s.reviewBtnText, s.approveText]}>Approve</Text>
                          </Pressable>
                          <Pressable
                            onPress={() => handleReview(checkin, 'sent_home')}
                            disabled={reviewingId === checkinId}
                            style={[s.reviewBtn, s.sendHomeBtn,
                              reviewingId === checkinId && s.reviewBtnDisabled]}
                          >
                            <X size={14} strokeWidth={2} color="#f87171" />
                            <Text style={[s.reviewBtnText, s.sendHomeText]}>Send home</Text>
                          </Pressable>
                        </View>
                      )}
                    </GlassCard>
                  )}

                  {isUnknownSst && (
                    <GlassCard style={s.reviewCard}>
                      <View style={s.reviewHeader}>
                        <AlertTriangle size={14} strokeWidth={1.5} color={semantic.attention} />
                        <Text style={s.reviewTitle}>
                          {'Unverified SST — '}
                          {checkin.sst_unknown_reason === 'CLASS'
                            ? 'class could not be read'
                            : checkin.sst_unknown_reason === 'EXPIRY'
                            ? 'expiration could not be confirmed'
                            : checkin.sst_unknown_reason === 'BOTH'
                            ? 'class and expiration could not be confirmed'
                            : 'credential could not be confirmed'}
                        </Text>
                      </View>
                      {/* Approve here ADMITS the worker; it does NOT verify the
                          card. The credential stays flagged for cert review. */}
                      <Text style={s.reviewHint}>
                        Ask the worker to re-scan the card. Approving admits them
                        but does not verify the credential.
                      </Text>

                      {reviewed ? (
                        checkin.review_pending_sync ? (
                          renderPendingDecision(
                            reviewed === 'approved'
                              ? 'Admitted — credential still unverified'
                              : 'Sent home',
                          )
                        ) : (
                        <Text style={s.reviewedText}>
                          {reviewed === 'approved'
                            ? 'Admitted — credential still unverified'
                            : 'Sent home'}
                          {checkin.reviewed_by_name ? ` by ${checkin.reviewed_by_name}` : ''}
                          {checkin.reviewed_at ? ` • ${formatDateTime(checkin.reviewed_at)}` : ''}
                        </Text>
                        )
                      ) : (
                        <View style={s.reviewActions}>
                          <Pressable
                            onPress={() => handleReview(checkin, 'approved')}
                            disabled={reviewingId === checkinId}
                            style={[s.reviewBtn, s.approveBtn,
                              reviewingId === checkinId && s.reviewBtnDisabled]}
                          >
                            <Check size={14} strokeWidth={2} color="#4ade80" />
                            <Text style={[s.reviewBtnText, s.approveText]}>Admit</Text>
                          </Pressable>
                          <Pressable
                            onPress={() => handleReview(checkin, 'sent_home')}
                            disabled={reviewingId === checkinId}
                            style={[s.reviewBtn, s.sendHomeBtn,
                              reviewingId === checkinId && s.reviewBtnDisabled]}
                          >
                            <X size={14} strokeWidth={2} color="#f87171" />
                            <Text style={[s.reviewBtnText, s.sendHomeText]}>Send home</Text>
                          </Pressable>
                        </View>
                      )}
                    </GlassCard>
                  )}
                  </View>
                );
              })}
            </View>
          ) : fetchState === 'ok' ? (
            // Only an answer FROM the server earns the empty state. A failed
            // load renders the notice above instead.
            <GlassCard style={s.emptyCard}>
              <IconPod size={64}>
                <Users size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={s.emptyTitle}>No Check-Ins Today</Text>
              <Text style={s.emptyText}>
                Workers will appear here when they check in to this project.
              </Text>
            </GlassCard>
          ) : null}
        </ScrollView>

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
    flex: 1,
  },
  // 44 minimum - work gloves.
  logoutBtn: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    backgroundColor: withAlpha('#ffffff', 0.05),
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: withAlpha('#94a3b8', 0.15),
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: withAlpha('#94a3b8', 0.3),
  },
  siteBadgeText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.lg,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  refreshBtn: {
    padding: spacing.xs,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
    padding: spacing.lg,
  },
  statLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  statValue: {
    fontSize: 36,
    fontWeight: '200',
    color: colors.text.primary,
  },
  activeIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  activeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#4ade80',
  },
  activeValue: {
    color: '#4ade80',
  },
  mb12: {
    marginBottom: spacing.sm + 4,
  },
  notice: {
    marginTop: 0,
    marginBottom: spacing.md,
  },
  pendingBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    backgroundColor: withAlpha(semantic.attention, 0.1),
    marginBottom: spacing.md,
  },
  pendingBannerText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
    color: colors.text.secondary,
  },
  pendingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  pendingText: {
    flex: 1,
    fontSize: 15,
    color: semantic.attention,
  },
  checkinsList: {
    gap: spacing.sm,
  },
  checkinCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  reviewCard: {
    marginTop: spacing.xs,
    padding: spacing.md,
    borderColor: semantic.attentionBorder,
    borderWidth: 1,
    gap: spacing.sm,
  },
  reviewHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  reviewTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fbbf24',
  },
  reviewedText: {
    fontSize: 15,
    color: colors.text.secondary,
  },
  reviewHint: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.xs,
    marginBottom: spacing.xs,
  },
  reviewActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  // Compliance-decision buttons. Were ~34px around a 14px icon, with no
  // hitSlop, on a wall-mounted tablet used with work gloves.
  reviewBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    minHeight: 48,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    flex: 1,
  },
  reviewBtnDisabled: {
    opacity: 0.5,
  },
  approveBtn: {
    borderColor: semantic.verifiedBorder,
    backgroundColor: semantic.verifiedBg,
  },
  sendHomeBtn: {
    borderColor: semantic.criticalBorder,
    backgroundColor: semantic.criticalBg,
  },
  reviewBtnText: {
    fontSize: 16,
    fontWeight: '600',
  },
  approveText: {
    color: '#4ade80',
  },
  sendHomeText: {
    color: '#f87171',
  },
  timeSection: {
    minWidth: 60,
    alignItems: 'center',
  },
  timeText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  timeOutText: {
    fontSize: 14,
    color: colors.text.muted,
    marginTop: 2,
  },
  divider: {
    width: 1,
    height: 40,
    backgroundColor: colors.glass.border,
  },
  workerInfo: {
    flex: 1,
    gap: spacing.xs,
  },
  workerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: withAlpha('#ffffff', 0.1),
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
  },
  workerDetails: {
    flex: 1,
  },
  workerName: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTrade: {
    fontSize: 15,
    color: colors.text.muted,
  },
  workerMeta: {
    flexDirection: 'row',
    gap: spacing.md,
    marginLeft: 44,
  },
  metaItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  metaText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: withAlpha('#64748b', 0.2),
    borderRadius: borderRadius.full,
  },
  statusActive: {
    backgroundColor: semantic.verifiedBg,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#4ade80',
  },
  statusText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  statusDone: {
    color: colors.text.muted,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 260,
  },
});
}
