import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
  RefreshControl, TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldAlert, Search } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import OwnerNav from '../../src/components/OwnerNav';
import OfflineNotice from '../../src/components/OfflineNotice';
import MarkWrongForm from '../../src/components/MarkWrongForm';
import { useAuth, isPlatformOperator } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { ownerAPI } from '../../src/utils/api';
import { settleFetch } from '../../src/utils/offlineState';
import { answerRowView, searchParams, SURFACE_LABEL } from '../../src/utils/answerCorrections';
import { spacing, borderRadius } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

const PAGE = 25;
const SURFACES = [{ key: '', label: 'All' }].concat(
  Object.keys(SURFACE_LABEL).map((k) => ({ key: k, label: SURFACE_LABEL[k] })),
);

/**
 * OWNER PORTAL → ANSWERS. Every logged answer (the answer log), newest
 * first, across companies; search the question or the answer. An answer
 * opens with its question, answer, records, gates, model and code SHA, and
 * Mark wrong (MarkWrongForm): the correct answer (required) and a note,
 * saved as an append-only correction -- the self-learning feed. The server
 * is the gate: /api/owner/* is 404 to anyone else.
 */
export default function OwnerAnswersScreen() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const isOperator = isPlatformOperator(user);

  const [query, setQuery] = useState('');
  const [q, setQ] = useState('');
  const [surface, setSurface] = useState('');
  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [state, setState] = useState('loading');
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState(null);      // { row, data, state }

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated]);

  const load = useCallback(async (more = false) => {
    if (!isOperator) return;
    const offset = more ? items.length : 0;
    const res = await settleFetch(() => ownerAPI.answers(
      searchParams({ q, surface, offset, limit: PAGE })));
    setState(res.status);
    if (res.status === 'ok') {
      const got = Array.isArray(res.data?.items) ? res.data.items : [];
      setItems(more ? items.concat(got) : got);
      setHasMore(res.data?.has_more === true);
    }
    setRefreshing(false);
  }, [isOperator, q, surface, items]);

  useEffect(() => { load(false); }, [isOperator, q, surface]);

  const openRow = async (row) => {
    const v = answerRowView(row);
    setOpen({ row, data: null, state: 'loading' });
    const res = await settleFetch(() => ownerAPI.answer(v.id));
    setOpen((o) => (o && answerRowView(o.row).id === v.id
      ? { row, data: res.status === 'ok' ? res.data : null, state: res.status } : o));
  };

  if (!authLoading && isAuthenticated && !isOperator) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <OwnerNav />
          <GlassCard style={s.emptyCard}>
            <ShieldAlert size={28} strokeWidth={1.5} color={semantic.attention} />
            <Text style={s.line}>Platform operator access required.</Text>
          </GlassCard>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const chip = (key, label, on, onPress) => (
    <Pressable key={key} onPress={onPress} accessibilityRole="tab"
      accessibilityState={{ selected: on }}
      style={({ pressed }) => [s.chip, on && s.chipOn, pressed && s.pressed]}>
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </Pressable>
  );

  const ov = open ? answerRowView(open.data || open.row) : null;

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <OwnerNav title="Answers" />
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.content}
          refreshControl={(
            <RefreshControl refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(false); }} />
          )}
        >
          <View style={s.searchRow}>
            <Search size={16} strokeWidth={1.75} color={colors.text.secondary} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={() => setQ(query.trim())}
              placeholder="Search questions and answers"
              placeholderTextColor={colors.text.subtle}
              style={s.search}
              returnKeyType="search"
              accessibilityLabel="Search answers"
            />
            <Pressable onPress={() => setQ(query.trim())} accessibilityRole="button"
              style={({ pressed }) => [s.btn, pressed && s.pressed]}>
              <Text style={s.btnText}>Search</Text>
            </Pressable>
          </View>
          <View style={s.filters}>
            {SURFACES.map((f) => chip(f.key || 'all', f.label, f.key === surface,
              () => setSurface(f.key)))}
          </View>

          {state === 'loading' ? (
            <ActivityIndicator size="small" color={colors.text.secondary} />
          ) : state !== 'ok' ? (
            <OfflineNotice mode={state}
              detail="The answer log could not be loaded. Do not read this as no answers." />
          ) : items.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.line}>No answers found.</Text>
            </GlassCard>
          ) : items.map((row) => {
            const v = answerRowView(row);
            return (
              <Pressable key={v.key} onPress={() => openRow(row)} accessibilityRole="button"
                accessibilityLabel={`Open answer, ${v.company}`}>
                {({ pressed }) => (
                  <GlassCard style={[s.rowCard, pressed && s.pressed]}>
                    <View style={s.rowHead}>
                      <Text style={s.kind}>{v.surfaceLabel}</Text>
                      {v.correctionsLabel ? (
                        <Text style={s.badge}>{v.correctionsLabel}</Text>
                      ) : null}
                    </View>
                    <Text style={s.meta}>{v.company} · {v.when}</Text>
                    <Text style={s.name} numberOfLines={2}>Q: {v.question || '—'}</Text>
                    <Text style={s.meta} numberOfLines={2}>A: {v.answer || '—'}</Text>
                  </GlassCard>
                )}
              </Pressable>
            );
          })}
          {state === 'ok' && hasMore ? (
            <Pressable onPress={() => load(true)} accessibilityRole="button"
              style={({ pressed }) => [s.btn, s.more, pressed && s.pressed]}>
              <Text style={s.btnText}>Load more</Text>
            </Pressable>
          ) : null}
        </ScrollView>

        <Modal visible={!!open} transparent animationType="fade"
          onRequestClose={() => setOpen(null)}>
          <View style={s.backdrop}>
            <GlassCard variant="modal" style={s.modalCard} contentStyle={s.modalContent}>
              {ov ? (
                <ScrollView style={s.detailScroll} contentContainerStyle={s.detail}>
                  <Text style={s.kind}>{ov.surfaceLabel}</Text>
                  <Text style={s.meta}>{ov.company} · {ov.when}</Text>
                  {open.state === 'loading'
                    ? <ActivityIndicator size="small" color={colors.text.secondary} /> : null}
                  <Text style={s.section}>QUESTION</Text>
                  <Text style={s.line}>{ov.question || '—'}</Text>
                  <Text style={s.section}>ANSWER</Text>
                  <Text style={s.line}>{ov.answer || '—'}</Text>
                  <Text style={s.section}>RECORDS</Text>
                  {ov.records.length === 0 ? <Text style={s.meta}>None shown.</Text>
                    : ov.records.map((r) => (
                      <Text key={r.key} style={s.meta}>
                        {r.sheet ? `${r.sheet}: ` : ''}{r.text}
                      </Text>
                    ))}
                  {ov.recordsMore ? <Text style={s.meta}>+{ov.recordsMore} more</Text> : null}
                  <Text style={s.section}>GATES</Text>
                  {ov.gates.length === 0 ? <Text style={s.meta}>None recorded.</Text>
                    : ov.gates.map((g, i) => <Text key={`${g}-${i}`} style={s.meta}>{g}</Text>)}
                  {ov.build ? <Text style={s.pending}>{ov.build}</Text> : null}
                  {ov.id && open.state !== 'loading' ? (
                    <MarkWrongForm answerId={ov.id}
                      corrections={open.data?.corrections || []}
                      onSaved={(res) => {
                        const n = Array.isArray(res?.corrections) ? res.corrections.length : 0;
                        setItems((list) => list.map((r) => (answerRowView(r).id === ov.id
                          ? { ...r, corrections_count: n } : r)));
                      }} />
                  ) : null}
                </ScrollView>
              ) : null}
              {/* THE FOOTER: pinned below the scroll, always in view. */}
              <View style={s.footer}>
                <Pressable onPress={() => setOpen(null)} style={s.cancelBtn}
                  accessibilityRole="button">
                  <Text style={s.cancelText}>Close</Text>
                </Pressable>
              </View>
            </GlassCard>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    scroll: { flex: 1 },
    content: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
    searchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    search: {
      flex: 1, minHeight: 44, borderWidth: 1, borderColor: colors.glass.border,
      borderRadius: borderRadius.lg, paddingHorizontal: spacing.sm,
      color: colors.text.primary, fontSize: 15,
    },
    filters: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
    chip: {
      minHeight: 36, justifyContent: 'center', paddingHorizontal: spacing.md,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
    },
    chipOn: { backgroundColor: colors.glass.background, borderColor: colors.text.secondary },
    chipText: { fontSize: 13, color: colors.text.secondary },
    chipTextOn: { color: colors.text.primary, fontWeight: '600' },
    emptyCard: { padding: spacing.lg, alignItems: 'center', gap: spacing.sm, margin: spacing.lg },
    line: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    rowCard: { padding: spacing.md, gap: 4 },
    rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
    kind: {
      fontSize: 12, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      textTransform: 'uppercase', flexShrink: 1,
    },
    badge: { fontSize: 12, fontWeight: '600', color: semantic.attention },
    name: { fontSize: 15, fontWeight: '600', color: colors.text.primary, lineHeight: 20 },
    meta: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    section: {
      fontSize: 11, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      marginTop: spacing.sm,
    },
    btn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
      minHeight: 44, paddingHorizontal: spacing.md, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    more: { alignSelf: 'center' },
    btnText: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    pending: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    backdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.6),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { padding: spacing.lg, gap: spacing.sm, width: '100%', maxWidth: 560, maxHeight: '90%' },
    modalContent: { flexShrink: 1, minHeight: 0, gap: spacing.sm },
    detailScroll: { flexGrow: 0, flexShrink: 1, minHeight: 0 },
    detail: { gap: 4 },
    footer: {
      flexShrink: 0, gap: spacing.xs, paddingTop: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    cancelBtn: {
      minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border,
    },
    cancelText: { fontSize: 14, color: colors.text.secondary },
    pressed: { opacity: 0.8 },
  });
}
