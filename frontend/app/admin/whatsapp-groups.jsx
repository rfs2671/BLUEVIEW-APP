// ── CONNECTING A WHATSAPP GROUP TO A JOB ────────────────────────────────────
//
// Before this screen, connecting a group meant knowing that a six-digit code
// flow existed, opening the app, generating a code, pasting it into the chat,
// and confirming. Four steps that begin with knowing about step one — and a
// group nobody took through them sat there with the bot silent in it forever,
// with nothing anywhere recording that it was there.
//
// Now the bot writes down every group it can see, and this is where an admin
// says which job each one is. The group's name usually says so already
// (backend/lib/group_match.py), so the common row arrives pre-filled and the
// whole interaction is one tap.
//
// ── NOTHING HERE LINKS BY ITSELF, AND THAT IS NOT CAUTION ──────────────────
//
// A suggestion pre-fills a dropdown. It never submits. Getting this wrong does
// not produce an error — it produces one crew's daily log, roster and permit
// data appearing in another customer's chat, with nothing going red. The cost
// of a wrong guess is one tap to change it; the cost of a wrong auto-link is a
// customer seeing another customer's site.
//
// An unmatched row shows an EMPTY dropdown rather than a best effort, for the
// same reason: an unfilled row tells a person a decision is needed, and a
// confident wrong pre-fill gets confirmed.
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  MessageCircle,
  CheckCircle,
  ChevronDown,
  EyeOff,
  Sparkles,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { whatsappAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';
import { useT } from '../../src/i18n';

const WHATSAPP_GREEN = '#25D366'; // brand: WhatsApp - intentional, not a token

const LINK_ROLES = ['owner', 'admin', 'cp'];

export default function WhatsappPendingGroupsScreen() {
  const router = useRouter();
  // `t` arrives when this screen is reached from a link posted in the chat.
  // Same screen, same backend route, one group instead of the list.
  const { t: linkToken } = useLocalSearchParams();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const { colors, isDark } = useTheme();
  const s = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);
  const toast = useToast();
  // One namespace per screen, EN and ES key-identical — see src/i18n.
  // The brand name is NOT in the catalogue: a product name is the same in
  // both languages, and the catalogue's own test rejects a Spanish value
  // that is a copy of the English one, correctly.
  const t = useT('waGroups');

  const [loading, setLoading] = useState(true);
  // OFFLINE vs EMPTY. "No groups waiting" must only appear when the server
  // actually said so — the same rule every other list screen here follows.
  const [fetchState, setFetchState] = useState('ok');
  const [pending, setPending] = useState([]);
  const [projects, setProjects] = useState([]);
  // group_id -> project_id the admin has chosen (or the suggestion).
  const [choice, setChoice] = useState({});
  const [openPicker, setOpenPicker] = useState(null);
  const [busy, setBusy] = useState(null);
  const [confirmingAll, setConfirmingAll] = useState(false);

  const canLink = LINK_ROLES.includes((user?.role || '').toLowerCase());

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (!canLink) {
      router.replace('/');
      toast.error(t('deniedTitle'), t('deniedBody'));
    }
  }, [authLoading, isAuthenticated, canLink]);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await settleFetch(() =>
      linkToken
        ? whatsappAPI.getPendingGroupByToken(String(linkToken))
        : whatsappAPI.getPendingGroups(),
    );
    if (res.ok) {
      const data = res.value || {};
      const rows = data.pending || [];
      setPending(rows);
      setProjects(data.projects || []);
      // The suggestion is a starting VALUE, not a decision. It seeds the
      // dropdown and the admin can change it before confirming.
      const seeded = {};
      rows.forEach((r) => {
        if (r.suggested_project_id) seeded[r.group_id] = r.suggested_project_id;
      });
      setChoice(seeded);
      setFetchState('ok');
    } else {
      setFetchState(isOfflineError(res.error) ? 'offline' : 'error');
    }
    setLoading(false);
  }, [linkToken]);

  useEffect(() => {
    if (canLink) load();
  }, [canLink, load]);

  const projectLabel = (id) => {
    const p = projects.find((x) => x.id === id);
    if (!p) return t('choose');
    // name is required on every project, so this chain cannot fall through
    // to a literal — which is why there is no untranslated fallback here.
    return p.address || p.nickname || p.name;
  };

  const confirmOne = async (groupId) => {
    const projectId = choice[groupId];
    if (!projectId) return;
    setBusy(groupId);
    try {
      await whatsappAPI.linkPendingGroup(groupId, projectId);
      setPending((prev) => prev.filter((r) => r.group_id !== groupId));
      toast.success(t('connectedTitle'), projectLabel(projectId));
    } catch (error) {
      if (isOfflineError(error)) {
        toast.error(t('offlineTitle'), t('offlineConnect'));
      } else {
        toast.error(
          t('connectFailTitle'),
          error.response?.data?.detail || t('connectFailBody'),
        );
      }
    } finally {
      setBusy(null);
    }
  };

  // CONFIRM ALL SUBMITS ONLY THE ROWS THAT HAVE A PROJECT. An unmatched row is
  // one nobody has decided about; sweeping it into a bulk action would be the
  // auto-link this screen exists to avoid.
  const readyRows = pending.filter((r) => choice[r.group_id]);

  const confirmAll = async () => {
    if (!readyRows.length) return;
    setConfirmingAll(true);
    let done = 0;
    const failed = [];
    for (const row of readyRows) {
      try {
        await whatsappAPI.linkPendingGroup(row.group_id, choice[row.group_id]);
        done += 1;
      } catch (error) {
        failed.push(row.group_name || row.group_id);
      }
    }
    setConfirmingAll(false);
    await load();
    if (done) toast.success(t('connectedTitle'), String(done));
    // NAMED, NOT COUNTED. "2 failed" leaves the admin to work out which two.
    if (failed.length) toast.error(t('partialTitle'), failed.join(', '));
  };

  const ignoreOne = async (groupId) => {
    setBusy(groupId);
    try {
      await whatsappAPI.ignorePendingGroup(groupId);
      setPending((prev) => prev.filter((r) => r.group_id !== groupId));
    } catch (error) {
      toast.error(t('hideFailTitle'),
                  error.response?.data?.detail || t('connectFailBody'));
    } finally {
      setBusy(null);
    }
  };

  if (authLoading || !canLink) return null;

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/admin/integrations')}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>WHATSAPP</Text>
            <Text style={s.titleText}>{t('title')}</Text>
            <Text style={s.subtitle}>{t('subtitle')}</Text>
          </View>

          {fetchState === 'offline' && <OfflineNotice />}

          {loading ? (
            <GlassSkeleton height={120} />
          ) : fetchState !== 'ok' ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.emptyTitle}>{t('unavailableTitle')}</Text>
              <Text style={s.emptyDesc}>
                {fetchState === 'offline'
                  ? t('unavailableOffline')
                  : t('unavailableError')}
              </Text>
            </GlassCard>
          ) : pending.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <MessageCircle size={28} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.emptyTitle}>{t('emptyTitle')}</Text>
              <Text style={s.emptyDesc}>{t('emptyDesc')}</Text>
            </GlassCard>
          ) : (
            <>
              {readyRows.length > 1 && (
                <Pressable
                  onPress={confirmAll}
                  disabled={confirmingAll}
                  style={({ pressed }) => [
                    s.confirmAllBtn,
                    pressed && { opacity: 0.9 },
                    confirmingAll && { opacity: 0.6 },
                  ]}
                >
                  {confirmingAll ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <Text style={s.confirmAllText}>
                      {t('confirmAll')} ({readyRows.length})
                    </Text>
                  )}
                </Pressable>
              )}

              {pending.map((row) => {
                const selected = choice[row.group_id];
                const isOpen = openPicker === row.group_id;
                const isBusy = busy === row.group_id;
                const wasSuggested =
                  row.suggested_project_id && selected === row.suggested_project_id;
                return (
                  <GlassCard key={row.group_id} style={s.groupCard}>
                    <View style={s.groupHead}>
                      <MessageCircle size={18} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                      <Text style={s.groupName} numberOfLines={1}>
                        {row.group_name || t('unnamed')}
                      </Text>
                    </View>

                    {wasSuggested && (
                      <View style={s.suggestRow}>
                        <Sparkles size={13} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.suggestText}>{t('matched')}</Text>
                      </View>
                    )}

                    <Pressable
                      onPress={() => setOpenPicker(isOpen ? null : row.group_id)}
                      style={s.picker}
                    >
                      <Text
                        style={[s.pickerText, !selected && { color: colors.text.muted }]}
                        numberOfLines={1}
                      >
                        {selected ? projectLabel(selected) : t('choose')}
                      </Text>
                      <ChevronDown size={18} strokeWidth={1.5} color={colors.text.muted} />
                    </Pressable>

                    {isOpen && (
                      <View style={s.pickerList}>
                        {projects.map((p) => (
                          <Pressable
                            key={p.id}
                            onPress={() => {
                              setChoice((c) => ({ ...c, [row.group_id]: p.id }));
                              setOpenPicker(null);
                            }}
                            style={s.pickerOption}
                          >
                            <Text style={s.pickerOptionText} numberOfLines={1}>
                              {p.address || p.name}
                            </Text>
                            {p.nickname ? (
                              <Text style={s.pickerOptionSub}>{p.nickname}</Text>
                            ) : null}
                          </Pressable>
                        ))}
                      </View>
                    )}

                    <View style={s.actions}>
                      <Pressable
                        onPress={() => ignoreOne(row.group_id)}
                        disabled={isBusy}
                        style={s.ignoreBtn}
                      >
                        <EyeOff size={15} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.ignoreText}>{t('hide')}</Text>
                      </Pressable>
                      <Pressable
                        onPress={() => confirmOne(row.group_id)}
                        disabled={!selected || isBusy}
                        style={({ pressed }) => [
                          s.confirmBtn,
                          pressed && { opacity: 0.9 },
                          (!selected || isBusy) && { opacity: 0.5 },
                        ]}
                      >
                        {isBusy ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <>
                            <CheckCircle size={15} strokeWidth={2} color="#fff" />
                            <Text style={s.confirmText}>{t('confirm')}</Text>
                          </>
                        )}
                      </Pressable>
                    </View>
                  </GlassCard>
                );
              })}
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.08),
    },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: spacing.xxl },
    titleSection: { marginBottom: spacing.lg },
    titleLabel: {
      ...typography.caption,
      color: colors.text.muted,
      letterSpacing: 1.2,
      marginBottom: 4,
    },
    titleText: { ...typography.h1, color: colors.text.primary },
    subtitle: {
      ...typography.body,
      color: colors.text.secondary,
      marginTop: spacing.xs,
    },
    emptyCard: { alignItems: 'center', padding: spacing.xl, gap: spacing.sm },
    emptyTitle: { ...typography.h3, color: colors.text.primary },
    emptyDesc: {
      ...typography.body,
      color: colors.text.muted,
      textAlign: 'center',
    },
    confirmAllBtn: {
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.md,
      paddingVertical: spacing.md,
      alignItems: 'center',
      marginBottom: spacing.md,
    },
    confirmAllText: { ...typography.button, color: '#fff' },
    groupCard: { padding: spacing.md, marginBottom: spacing.md, gap: spacing.sm },
    groupHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    groupName: { ...typography.h3, color: colors.text.primary, flex: 1 },
    suggestRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
    suggestText: { ...typography.caption, color: colors.text.muted, flex: 1 },
    picker: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      borderWidth: 1,
      borderColor: withAlpha('#ffffff', 0.12),
      borderRadius: borderRadius.sm,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      gap: spacing.sm,
    },
    pickerText: { ...typography.body, color: colors.text.primary, flex: 1 },
    pickerList: {
      borderWidth: 1,
      borderColor: withAlpha('#ffffff', 0.12),
      borderRadius: borderRadius.sm,
      overflow: 'hidden',
    },
    pickerOption: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.06),
    },
    pickerOptionText: { ...typography.body, color: colors.text.primary },
    pickerOptionSub: { ...typography.caption, color: colors.text.muted },
    actions: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginTop: spacing.xs,
    },
    ignoreBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: spacing.xs },
    ignoreText: { ...typography.caption, color: colors.text.muted },
    confirmBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.sm,
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.sm,
    },
    confirmText: { ...typography.button, color: '#fff' },
  });
}
