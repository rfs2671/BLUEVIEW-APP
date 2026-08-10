/**
 * Check-in review area — the screen where a CP or admin acts on flagged
 * check-ins from THEIR OWN login.
 *
 * Why it lives under /logbooks:
 *   The route guard in app/_layout.jsx confines a CP to /logbooks/*,
 *   /documents, /settings and /login. Placing this screen at
 *   /logbooks/review makes it reachable by a CP with NO change to that
 *   allowlist — it does not widen CP access to anything else. Admins have no
 *   path restriction, so they reach it too. The site-device kiosk screen
 *   (app/site/checkins.jsx) cannot serve either role: site-mode is a separate
 *   identity backed by db.site_devices, never a real user.
 *
 * What it shows: check-ins where an expired SST is still unreviewed, or the
 * worker checked in with no trade because the project had none configured.
 *
 * ENGLISH ONLY, via src/i18n (namespace `review`). A logbook is a legal record
 * filed with the DOB and this is the CP's decision surface on it — approve,
 * send home, assign trade — so the copy is English and the ES catalogue
 * deliberately carries no `review` namespace at all (see src/i18n/es.js and the
 * EN_ONLY_NAMESPACES allowlist in src/i18n/i18n.test.cjs). translate() falls
 * back to English, so an es-locale CP reads it normally.
 *
 * The header used to carry a language toggle. It is gone: it controlled nothing
 * here once this screen became English-only, this screen renders no
 * SignaturePad, and the timestamps are unconditional en-US. Its one real effect
 * was remote — an app-wide setLocale that changed a signature pad on some other
 * screen. That choice now lives on SignaturePad itself, next to the sentence
 * being signed.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Image,
  Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams, useFocusEffect } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  AlertTriangle,
  Check,
  X,
  ChevronDown,
  ShieldAlert,
  Briefcase,
  RefreshCw,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { projectsAPI, checkinsAPI } from '../../src/utils/api';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useT } from '../../src/i18n';

export default function CheckInReviewScreen() {
  const { colors } = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams(); // Task A: land on the project passed by the banner
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();

  // No locale state here any more. This screen is English-only — it is a CP
  // decision surface on a legal record — and the one thing its old toggle
  // really controlled, the SignaturePad affirmation, now belongs to the pad
  // itself, next to the sentence being signed.
  const t = useT('review');

  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showPicker, setShowPicker] = useState(false);
  const [items, setItems] = useState([]);
  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error' per fetch. checkinsAPI.getFlagged
  // has no cache, so a failed read has nothing to fall back on; it must say so
  // rather than render the "Nothing to review" all-clear.
  const [projectsState, setProjectsState] = useState('ok');
  const [flaggedState, setFlaggedState] = useState('ok');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actingId, setActingId] = useState(null);
  const [zoomImage, setZoomImage] = useState(null);
  // Project's configured trade roster, returned alongside the flagged list.
  const [roster, setRoster] = useState([]);
  // Which row currently has its trade picker open.
  const [assignPickerId, setAssignPickerId] = useState(null);

  const s = useMemo(() => buildStyles(colors), [colors]);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  // Load the projects this user can act on. A CP only sees their assigned
  // projects — the same filter the logbooks index uses.
  useEffect(() => {
    if (!isAuthenticated) return;
    (async () => {
      // The old `.catch(() => [])` + `setProjects([])` rendered "No projects
      // assigned to you yet." on any offline load — a statement about the
      // user's account, made from a network failure.
      const r = await settleFetch(() => projectsAPI.getAll());
      setProjectsState(r.status);
      if (r.status === 'ok') {
        const data = r.data;
        const list = Array.isArray(data) ? data : (data?.items || []);
        const isCP = user?.role === 'cp';
        const visible = isCP
          ? list.filter((p) =>
              (user?.assigned_projects || []).includes(p.id || p._id))
          : list;
        setProjects(visible);
        if (visible.length && !selectedProject) {
          // Prefer the project the banner routed us to (the first with flagged
          // items) so the review list isn't empty on open; else fall back to first.
          const target = visible.find((p) => (p._id || p.id) === params.projectId) || visible[0];
          setSelectedProject(target);
        }
      } else {
        console.error('Failed to load projects for review:', r.error);
      }
      setLoading(false);
    })();
  }, [isAuthenticated, user]);

  const projectId = selectedProject?._id || selectedProject?.id;

  const fetchFlagged = useCallback(async () => {
    if (!projectId) { setItems([]); setFlaggedState('ok'); return; }
    const r = await settleFetch(() => checkinsAPI.getFlagged(projectId));
    setFlaggedState(r.status);
    if (r.status === 'ok') {
      setItems(r.data?.items || []);
      setRoster(r.data?.trade_assignments || []);
    } else {
      // Clear the previous project's rows — but the render branches on
      // flaggedState BEFORE the empty state, so this never reads as "all clear".
      setItems([]);
      setRoster([]);
      toast.error(
        t('loadError'),
        r.status === 'offline'
          ? t('offlineLoad')
          : (r.error?.response?.data?.detail || t('errorLoad')),
      );
    }
    setLoading(false);
    setRefreshing(false);
  }, [projectId, t]);

  useEffect(() => {
    if (projectId) { setLoading(true); fetchFlagged(); }
  }, [projectId, fetchFlagged]);

  // Refetch whenever this screen regains focus.
  //
  // WHY: resolving a worker updates the row IN PLACE (handleReview below stamps
  // review_decision onto it) but never removes it, and the server's flagged
  // list already excludes anything with a review_decision
  // (get_flagged_project_checkins, server.py — {"review_decision": {"$exists":
  // False}}). The effect above only fires on mount and on a projectId change,
  // and expo-router keeps this screen MOUNTED when the CP navigates away, so
  // nothing ever asked the server again. The resolved man stayed on the list
  // until a full app force-close, and a CP reading a still-present row
  // approves the same worker over and over believing it failed.
  //
  // No loading spinner here on purpose: this is a background reconcile of a
  // list the CP is already looking at, and flashing it to empty would read as
  // "everything vanished". Mirrors the pattern in app/logbooks/index.jsx.
  useFocusEffect(
    useCallback(() => {
      if (projectId) fetchFlagged();
    }, [projectId, fetchFlagged])
  );

  const onRefresh = () => { setRefreshing(true); fetchFlagged(); };

  const handleReview = async (item, decision) => {
    const id = item._id || item.id;
    if (!id) return;
    setActingId(id);
    try {
      const res = await checkinsAPI.review(id, decision);
      setItems((prev) => prev.map((c) =>
        (c._id || c.id) === id
          ? {
              ...c,
              review_decision: res.review_decision,
              reviewed_by_name: res.reviewed_by_name,
              reviewed_at: res.reviewed_at,
            }
          : c,
      ));
      toast.success(
        decision === 'approved' ? t('approved') : t('sentHome'),
        decision === 'approved' ? t('approvedToast') : t('sentHomeToast'),
      );
    } catch (e) {
      // No write queue here (out of scope) — so the ONLY honest outcome is to
      // leave the row untouched and say plainly that nothing was recorded.
      toast.error(
        isOfflineError(e) ? t('offlineWrite') : t('reviewFailed'),
        isOfflineError(e)
          ? t('offlineWriteHint')
          : (e?.response?.data?.detail || ''),
      );
    } finally {
      setActingId(null);
    }
  };

  // Assign a roster trade/company to a check-in that arrived without one.
  // The backend re-validates the pair against the project roster and clears
  // needs_trade_assignment.
  const handleAssign = async (item, assignment) => {
    const id = item._id || item.id;
    if (!id || !assignment) return;
    setActingId(id);
    try {
      const res = await checkinsAPI.assignTrade(
        id, assignment.trade, assignment.company,
      );
      setItems((prev) => prev.map((c) =>
        (c._id || c.id) === id
          ? {
              ...c,
              worker_trade: res.trade,
              worker_company: res.company,
              needs_trade_assignment: false,
              flag_reasons: (c.flag_reasons || [])
                .filter((r) => r !== 'needs_trade'),
              trade_assigned_by_name: res.trade_assigned_by_name,
              trade_assigned_at: res.trade_assigned_at,
            }
          : c,
      ));
      setAssignPickerId(null);
      toast.success(t('assigned'), t('assignedToast'));
    } catch (e) {
      // Same rule as handleReview: the picker stays open and the row keeps its
      // "no trade assigned" flag, because nothing reached the server.
      toast.error(
        isOfflineError(e) ? t('offlineWrite') : t('assignFailed'),
        isOfflineError(e)
          ? t('offlineWriteHint')
          : (e?.response?.data?.detail || ''),
      );
    } finally {
      setActingId(null);
    }
  };

  const fmt = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    // UNCONDITIONAL en-US. This screen is a CP decision surface on a legal
    // record, and a check-in timestamp is part of that record — es-US and en-US
    // differ visibly in month names and AM/PM placement, so a locale-dependent
    // timestamp would render the same filed fact two different ways.
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      hour12: true, timeZone: 'America/New_York',
    });
  };

  const fmtDate = (v) => (v ? String(v).slice(0, 10) : '');

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.back()}
          />
          <Text style={s.headerTitle}>{t('title')}</Text>
          {/* The language toggle that used to sit here is gone. It controlled
              nothing on this screen: review's copy is English-only (a CP
              decision surface on a legal record), this screen renders no
              SignaturePad, and the timestamp above is now unconditional en-US.
              Its one real effect was remote — app-wide setLocale changing a
              signature pad on some OTHER screen the CP opened later. That
              choice now lives on the pad itself, with the sentence being
              signed. */}
        </View>

        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          <Text style={s.subtitle}>{t('subtitle')}</Text>

          {/* Project picker */}
          {projects.length === 0 && !loading && projectsState !== 'ok' ? (
            /* The project LIST failed to load — "No projects assigned to you
               yet" would be a claim about the account, not the network. */
            <OfflineNotice
              mode={projectsState}
              detail={projectsState === 'offline' ? t('offlineProjects') : t('errorProjects')}
            />
          ) : projects.length === 0 && !loading ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.emptyText}>{t('noProjects')}</Text>
            </GlassCard>
          ) : (
            <Pressable onPress={() => setShowPicker((v) => !v)}>
              <GlassCard style={s.pickerCard}>
                <Text style={s.pickerText} numberOfLines={1}>
                  {selectedProject?.name || t('selectProject')}
                </Text>
                <ChevronDown size={18} color={colors.text.muted} />
              </GlassCard>
            </Pressable>
          )}

          {showPicker && projects.map((p) => (
            <Pressable
              key={p._id || p.id}
              onPress={() => { setSelectedProject(p); setShowPicker(false); }}
            >
              <GlassCard style={s.pickerOption}>
                <Text style={s.pickerOptionText}>{p.name}</Text>
              </GlassCard>
            </Pressable>
          ))}

          {loading ? (
            <View style={s.centered}>
              <ActivityIndicator size="small" color={colors.text.secondary} />
            </View>
          ) : flaggedState !== 'ok' ? (
            /* The flagged list FAILED to load. The green-check "Nothing to
               review" all-clear below is a compliance assertion — it may only
               render when the server actually answered with an empty list. */
            <OfflineNotice
              mode={flaggedState}
              detail={flaggedState === 'offline' ? t('offlineLoad') : t('errorLoad')}
            />
          ) : items.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Check size={28} strokeWidth={1.5} color="#4ade80" />
              <Text style={s.emptyText}>{t('empty')}</Text>
              <Text style={s.emptyHint}>{t('emptyHint')}</Text>
            </GlassCard>
          ) : (
            items.map((item) => {
              const id = item._id || item.id;
              const reasons = item.flag_reasons || [];
              const isExpired = reasons.includes('expired_sst');
              const isUnknown = reasons.includes('unknown_sst');
              const needsTrade = reasons.includes('needs_trade');
              const reviewed = item.review_decision;
              const busy = actingId === id;

              return (
                <GlassCard key={id} style={s.itemCard}>
                  <Text style={s.workerName}>{item.worker_name}</Text>
                  <Text style={s.workerMeta}>
                    {[item.worker_trade, item.worker_company]
                      .filter(Boolean).join(' • ')}
                  </Text>
                  <Text style={s.checkedIn}>
                    {t('checkedInAt')}: {fmt(item.check_in_time)}
                  </Text>

                  {/* Why it's flagged */}
                  {isExpired && (
                    <View style={[s.reasonRow, s.reasonExpired]}>
                      <ShieldAlert size={14} color="#fbbf24" />
                      <Text style={s.reasonText}>
                        {t('expiredSst')}
                        {item.sst_expiration
                          ? ` — ${t('expiredOn')} ${fmtDate(item.sst_expiration)}`
                          : ''}
                        {item.osha_number ? `  (#${item.osha_number})` : ''}
                      </Text>
                    </View>
                  )}
                  {isUnknown && (
                    <View style={[s.reasonRow, s.reasonExpired]}>
                      <ShieldAlert size={14} color="#fbbf24" />
                      <View style={{ flex: 1 }}>
                        <Text style={s.reasonText}>{t('unknownSst')}</Text>
                        {item.sst_review_reason && t(`reason_${item.sst_review_reason}`) !== `reason_${item.sst_review_reason}` ? (
                          <Text style={s.reasonHint}>{t(`reason_${item.sst_review_reason}`)}</Text>
                        ) : null}
                        <Text style={s.reasonHint}>{t('unknownAdmitHint')}</Text>
                      </View>
                    </View>
                  )}
                  {needsTrade && (
                    <View>
                      <View style={[s.reasonRow, s.reasonTrade]}>
                        <Briefcase size={14} color="#93c5fd" />
                        <View style={{ flex: 1 }}>
                          <Text style={s.reasonTextBlue}>{t('needsTrade')}</Text>
                          <Text style={s.reasonHint}>{t('needsTradeHint')}</Text>
                        </View>
                      </View>

                      {roster.length === 0 ? (
                        <Text style={s.reasonHint}>{t('noRoster')}</Text>
                      ) : assignPickerId === id ? (
                        <View style={s.assignBox}>
                          <Text style={s.assignPrompt}>{t('chooseTrade')}</Text>
                          {roster.map((a, i) => (
                            <Pressable
                              key={`${a.trade}-${a.company}-${i}`}
                              onPress={() => handleAssign(item, a)}
                              disabled={busy}
                              style={[s.rosterOption, busy && s.btnBusy]}
                            >
                              <Text style={s.rosterText}>
                                {a.trade} — {a.company}
                              </Text>
                            </Pressable>
                          ))}
                          <Pressable
                            onPress={() => setAssignPickerId(null)}
                            style={s.cancelBtn}
                          >
                            <Text style={s.cancelText}>{t('cancel')}</Text>
                          </Pressable>
                        </View>
                      ) : (
                        <Pressable
                          onPress={() => setAssignPickerId(id)}
                          disabled={busy}
                          style={[s.actionBtn, s.assignBtn, busy && s.btnBusy]}
                        >
                          <Briefcase size={15} strokeWidth={2} color="#93c5fd" />
                          <Text style={[s.actionText, s.assignText]}>
                            {t('assignTrade')}
                          </Text>
                        </Pressable>
                      )}
                    </View>
                  )}

                  {/* Trade just assigned — show the outcome + attribution. */}
                  {!needsTrade && item.trade_assigned_at && (
                    <Text style={s.reviewedText}>
                      {t('assigned')}: {item.worker_trade} — {item.worker_company}
                      {item.trade_assigned_by_name
                        ? ` ${t('by')} ${item.trade_assigned_by_name}` : ''}
                    </Text>
                  )}

                  {/* Card image for the decision */}
                  {item.osha_card_image ? (
                    <Pressable onPress={() => setZoomImage(item.osha_card_image)}>
                      <Image
                        source={{ uri: item.osha_card_image }}
                        style={s.cardImage}
                        resizeMode="contain"
                      />
                      <Text style={s.cardHint}>{t('viewCard')}</Text>
                    </Pressable>
                  ) : (
                    <Text style={s.cardHint}>{t('noCard')}</Text>
                  )}

                  {/* Decision — for the expired-SST OR unknown-SST flag. On
                      unknown, "approved" ADMITS the worker but does NOT verify
                      the card (the review endpoint only writes the check-in
                      decision), so the reviewed text says so explicitly. */}
                  {(isExpired || isUnknown) && (
                    reviewed ? (
                      <Text style={s.reviewedText}>
                        {reviewed === 'approved'
                          ? (isUnknown ? t('admittedUnverified') : t('approved'))
                          : t('sentHome')}
                        {item.reviewed_by_name
                          ? ` ${t('by')} ${item.reviewed_by_name}` : ''}
                        {item.reviewed_at ? ` • ${fmt(item.reviewed_at)}` : ''}
                      </Text>
                    ) : (
                      <View style={s.actions}>
                        <Pressable
                          onPress={() => handleReview(item, 'approved')}
                          disabled={busy}
                          style={[s.actionBtn, s.approveBtn, busy && s.btnBusy]}
                        >
                          <Check size={15} strokeWidth={2} color="#4ade80" />
                          <Text style={[s.actionText, s.approveText]}>
                            {isUnknown ? t('admit') : t('approve')}
                          </Text>
                        </Pressable>
                        <Pressable
                          onPress={() => handleReview(item, 'sent_home')}
                          disabled={busy}
                          style={[s.actionBtn, s.sendHomeBtn, busy && s.btnBusy]}
                        >
                          <X size={15} strokeWidth={2} color="#f87171" />
                          <Text style={[s.actionText, s.sendHomeText]}>
                            {t('sendHome')}
                          </Text>
                        </Pressable>
                      </View>
                    )
                  )}
                </GlassCard>
              );
            })
          )}
        </ScrollView>

        {/* Card zoom */}
        <Modal visible={!!zoomImage} transparent animationType="fade">
          <Pressable style={s.modalBackdrop} onPress={() => setZoomImage(null)}>
            {zoomImage && (
              <Image
                source={{ uri: zoomImage }}
                style={s.modalImage}
                resizeMode="contain"
              />
            )}
            <Text style={s.modalClose}>{t('close')}</Text>
          </Pressable>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    },
    headerTitle: {
      ...typography.label, flex: 1,
      fontSize: 16, fontWeight: '600', color: colors.text.primary,
    },
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
    subtitle: {
      ...typography.label, color: colors.text.muted, marginBottom: spacing.xs,
    },
    pickerCard: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      padding: spacing.md,
    },
    pickerText: { flex: 1, fontSize: 15, color: colors.text.primary },
    pickerOption: { padding: spacing.md, marginTop: spacing.xs },
    pickerOptionText: { fontSize: 15, color: colors.text.primary },
    centered: { padding: spacing.xl, alignItems: 'center' },
    emptyCard: {
      padding: spacing.lg, alignItems: 'center', gap: spacing.xs,
    },
    emptyText: { fontSize: 15, color: colors.text.primary },
    emptyHint: { fontSize: 13, color: colors.text.muted, textAlign: 'center' },
    itemCard: { padding: spacing.md, gap: spacing.xs },
    workerName: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    workerMeta: { fontSize: 13, color: colors.text.secondary },
    checkedIn: { fontSize: 12, color: colors.text.muted },
    reasonRow: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs,
      padding: spacing.sm, borderRadius: borderRadius.lg, borderWidth: 1,
      marginTop: spacing.xs,
    },
    reasonExpired: {
      borderColor: semantic.attentionBorder,
      backgroundColor: semantic.attentionBg,
    },
    reasonTrade: {
      borderColor: 'rgba(147,197,253,0.35)',
      backgroundColor: 'rgba(59,130,246,0.10)',
    },
    reasonText: { flex: 1, fontSize: 13, color: '#fbbf24', fontWeight: '600' },
    reasonTextBlue: { fontSize: 13, color: '#93c5fd', fontWeight: '600' },
    reasonHint: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    cardImage: {
      width: '100%', height: 150, borderRadius: borderRadius.lg,
      marginTop: spacing.xs, backgroundColor: withAlpha('#ffffff', 0.04),
    },
    cardHint: {
      fontSize: 11, color: colors.text.muted, textAlign: 'center',
      marginTop: 4,
    },
    reviewedText: {
      fontSize: 13, color: colors.text.secondary, marginTop: spacing.xs,
    },
    actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
    actionBtn: {
      flex: 1, flexDirection: 'row', alignItems: 'center',
      justifyContent: 'center', gap: spacing.xs,
      paddingVertical: spacing.sm, borderRadius: borderRadius.lg, borderWidth: 1,
    },
    btnBusy: { opacity: 0.5 },
    approveBtn: {
      borderColor: semantic.verifiedBorder,
      backgroundColor: semantic.verifiedBg,
    },
    sendHomeBtn: {
      borderColor: semantic.criticalBorder,
      backgroundColor: semantic.criticalBg,
    },
    actionText: { fontSize: 13, fontWeight: '600' },
    approveText: { color: '#4ade80' },
    sendHomeText: { color: '#f87171' },
    assignBtn: {
      marginTop: spacing.sm,
      borderColor: 'rgba(147,197,253,0.4)',
      backgroundColor: 'rgba(59,130,246,0.08)',
    },
    assignText: { color: '#93c5fd' },
    assignBox: {
      marginTop: spacing.sm, padding: spacing.sm,
      borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: 'rgba(147,197,253,0.3)',
      gap: spacing.xs,
    },
    assignPrompt: {
      fontSize: 12, color: colors.text.muted, marginBottom: 2,
    },
    rosterOption: {
      paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
      borderRadius: borderRadius.lg,
      backgroundColor: withAlpha('#ffffff', 0.05),
    },
    rosterText: { fontSize: 14, color: colors.text.primary },
    cancelBtn: { paddingVertical: spacing.xs, alignItems: 'center' },
    cancelText: { fontSize: 13, color: colors.text.muted },
    modalBackdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.9),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalImage: { width: '100%', height: '70%' },
    modalClose: {
      marginTop: spacing.lg, fontSize: 15, color: '#fff', fontWeight: '600',
    },
  });
}
