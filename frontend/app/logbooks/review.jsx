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
 * Bilingual (EN/ES) via a local TRANSLATIONS map — the Expo app has no i18n
 * framework, so this mirrors the pattern used in backend/checkin.html.
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
import { useRouter } from 'expo-router';
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
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

const TRANSLATIONS = {
  en: {
    title: 'Check-In Review',
    subtitle: 'Workers needing a decision',
    selectProject: 'Select a project',
    noProjects: 'No projects assigned to you yet.',
    empty: 'Nothing to review',
    emptyHint: 'No flagged check-ins on this project.',
    loadError: 'Could not load flagged check-ins',
    expiredSst: 'Expired SST',
    expiredOn: 'expired',
    needsTrade: 'No trade assigned',
    needsTradeHint: 'This project had no trades set up when they checked in.',
    approve: 'Approve',
    sendHome: 'Send home',
    approved: 'Approved',
    sentHome: 'Sent home',
    by: 'by',
    reviewFailed: 'Could not record the decision',
    approvedToast: 'Worker approved to stay on site',
    sentHomeToast: 'Sent-home decision recorded',
    viewCard: 'Tap card to enlarge',
    noCard: 'No card image on file',
    checkedInAt: 'Checked in',
    refresh: 'Refresh',
    close: 'Close',
    assignTrade: 'Assign trade',
    chooseTrade: 'Choose a trade & company',
    assign: 'Assign',
    cancel: 'Cancel',
    assigned: 'Trade assigned',
    assignedToast: 'Trade assigned to this check-in',
    assignFailed: 'Could not assign the trade',
    noRoster: 'This project has no trades configured yet — an admin must add them first.',
    // Cert-review reason codes (backend stores the CODE; text lives here).
    unknownSst: 'Unverified SST',
    admit: 'Admit',
    admittedUnverified: 'Admitted — credential still unverified',
    unknownAdmitHint: 'Admitting records entry only — it does not verify the card. The credential stays flagged for review.',
    reason_CLASS_UNVERIFIED: 'Card class could not be read — verify the card',
    reason_EXPIRY_IMPLAUSIBLE: 'Expiry date is implausible — re-scan or verify',
    reason_EXPIRY_UNPARSEABLE: 'Expiry date could not be read — verify the card',
    reason_EXPIRY_CONFLICT: 'Two scans disagree on the expiry — verify the card',
    reason_DUPLICATE_SST: 'Duplicate SST records — resolve to one',
  },
  es: {
    title: 'Revisión de Registros',
    subtitle: 'Trabajadores que requieren una decisión',
    selectProject: 'Seleccione un proyecto',
    noProjects: 'Aún no tiene proyectos asignados.',
    empty: 'Nada que revisar',
    emptyHint: 'No hay registros marcados en este proyecto.',
    loadError: 'No se pudieron cargar los registros marcados',
    expiredSst: 'SST vencida',
    expiredOn: 'venció',
    needsTrade: 'Sin oficio asignado',
    needsTradeHint: 'Este proyecto no tenía oficios configurados cuando se registró.',
    approve: 'Aprobar',
    sendHome: 'Enviar a casa',
    approved: 'Aprobado',
    sentHome: 'Enviado a casa',
    by: 'por',
    reviewFailed: 'No se pudo registrar la decisión',
    approvedToast: 'Trabajador aprobado para permanecer en el sitio',
    sentHomeToast: 'Decisión de enviar a casa registrada',
    viewCard: 'Toque la tarjeta para ampliar',
    noCard: 'No hay imagen de la tarjeta',
    checkedInAt: 'Registrado',
    refresh: 'Actualizar',
    close: 'Cerrar',
    assignTrade: 'Asignar oficio',
    chooseTrade: 'Elija un oficio y empresa',
    assign: 'Asignar',
    cancel: 'Cancelar',
    assigned: 'Oficio asignado',
    assignedToast: 'Oficio asignado a este registro',
    assignFailed: 'No se pudo asignar el oficio',
    noRoster: 'Este proyecto aún no tiene oficios configurados — un administrador debe agregarlos primero.',
    // Códigos de motivo de revisión (el backend guarda el CÓDIGO; el texto va aquí).
    unknownSst: 'SST sin verificar',
    admit: 'Admitir',
    admittedUnverified: 'Admitido — credencial aún sin verificar',
    unknownAdmitHint: 'Admitir registra solo la entrada — no verifica la tarjeta. La credencial permanece marcada para revisión.',
    reason_CLASS_UNVERIFIED: 'No se pudo leer la clase de la tarjeta — verifique la tarjeta',
    reason_EXPIRY_IMPLAUSIBLE: 'La fecha de vencimiento no es plausible — reescanee o verifique',
    reason_EXPIRY_UNPARSEABLE: 'No se pudo leer la fecha de vencimiento — verifique la tarjeta',
    reason_EXPIRY_CONFLICT: 'Dos escaneos no coinciden en el vencimiento — verifique la tarjeta',
    reason_DUPLICATE_SST: 'Registros SST duplicados — consolide en uno',
  },
};

export default function CheckInReviewScreen() {
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();

  const [lang, setLang] = useState('en');
  const t = useCallback(
    (key) => TRANSLATIONS[lang][key] || TRANSLATIONS.en[key] || key,
    [lang],
  );

  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showPicker, setShowPicker] = useState(false);
  const [items, setItems] = useState([]);
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
      try {
        const data = await projectsAPI.getAll().catch(() => []);
        const list = Array.isArray(data) ? data : (data?.items || []);
        const isCP = user?.role === 'cp';
        const visible = isCP
          ? list.filter((p) =>
              (user?.assigned_projects || []).includes(p.id || p._id))
          : list;
        setProjects(visible);
        if (visible.length && !selectedProject) setSelectedProject(visible[0]);
      } catch (e) {
        setProjects([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [isAuthenticated, user]);

  const projectId = selectedProject?._id || selectedProject?.id;

  const fetchFlagged = useCallback(async () => {
    if (!projectId) { setItems([]); return; }
    try {
      const data = await checkinsAPI.getFlagged(projectId);
      setItems(data?.items || []);
      setRoster(data?.trade_assignments || []);
    } catch (e) {
      toast.error(t('loadError'), e?.response?.data?.detail || '');
      setItems([]);
      setRoster([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    if (projectId) { setLoading(true); fetchFlagged(); }
  }, [projectId, fetchFlagged]);

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
      toast.error(t('reviewFailed'), e?.response?.data?.detail || '');
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
      toast.error(t('assignFailed'), e?.response?.data?.detail || '');
    } finally {
      setActingId(null);
    }
  };

  const fmt = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString(lang === 'es' ? 'es-US' : 'en-US', {
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
          <Pressable
            onPress={() => setLang((l) => (l === 'en' ? 'es' : 'en'))}
            style={s.langToggle}
            hitSlop={10}
          >
            <Text style={s.langText}>{lang === 'en' ? 'ES' : 'EN'}</Text>
          </Pressable>
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
          {projects.length === 0 && !loading ? (
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
    langToggle: {
      paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
      borderRadius: borderRadius.full, borderWidth: 1,
      borderColor: colors.glass.border,
    },
    langText: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },
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
