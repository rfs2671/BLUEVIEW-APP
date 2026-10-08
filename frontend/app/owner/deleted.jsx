import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
  RefreshControl,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldAlert, RotateCcw, Eye, Lock } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import OwnerNav from '../../src/components/OwnerNav';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth, isPlatformOperator } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { ownerAPI } from '../../src/utils/api';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import {
  DELETED_FILTERS, filterDeleted, deletedRowView, previewView,
  restoreSummary, serverMessage,
} from '../../src/utils/ownerPortal';
import { spacing, borderRadius } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

/**
 * OWNER PORTAL → DELETED ITEMS. Every soft-deleted company, project and user:
 * type, name/address, company, deleted by, deleted at.
 *
 *   Restore       works now; brings back what was deleted in the same action.
 *   Preview       a read-only count of what a hard delete would remove.
 *   Hard delete   shown, DISABLED, until the delete-service fix ships.
 */
export default function OwnerDeletedScreen() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const isOperator = isPlatformOperator(user);

  const [items, setItems] = useState([]);
  const [state, setState] = useState('loading');
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [busy, setBusy] = useState(null);
  const [confirm, setConfirm] = useState(null); // row to restore
  const [preview, setPreview] = useState(null); // { row, data | null, state }

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated]);

  const load = useCallback(async () => {
    if (!isOperator) return;
    const res = await settleFetch(() => ownerAPI.deletedItems());
    setState(res.status);
    if (res.status === 'ok') setItems(res.data?.items || []);
    setRefreshing(false);
  }, [isOperator]);

  useEffect(() => { load(); }, [load]);

  const restore = async () => {
    const row = confirm;
    setConfirm(null);
    if (!row) return;
    setBusy(`${row.kind}:${row.id}`);
    try {
      const res = await ownerAPI.restoreDeleted(row.kind, row.id);
      toast.success(`Restored ${row.name}`, restoreSummary(res));
      await load();
    } catch (e) {
      toast.error('Not restored', isOfflineError(e)
        ? 'Restoring needs a connection. Nothing changed.'
        : serverMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const openPreview = async (row) => {
    setPreview({ row, data: null, state: 'loading' });
    const res = await settleFetch(() => ownerAPI.previewHardDelete(row.kind, row.id));
    setPreview((p) => (p && p.row === row
      ? { row, data: res.status === 'ok' ? res.data : null, state: res.status }
      : p));
  };

  const shown = filterDeleted(items, filter);
  const pv = preview?.data ? previewView(preview.data) : null;

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

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <OwnerNav title="Deleted items" />
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.content}
          refreshControl={(
            <RefreshControl refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(); }} />
          )}
        >
          <View style={s.filters}>
            {DELETED_FILTERS.map((f) => {
              const on = f.key === filter;
              const n = filterDeleted(items, f.key).length;
              return (
                <Pressable key={f.key} onPress={() => setFilter(f.key)}
                  accessibilityRole="tab" accessibilityState={{ selected: on }}
                  style={({ pressed }) => [s.chip, on && s.chipOn, pressed && s.pressed]}>
                  <Text style={[s.chipText, on && s.chipTextOn]}>
                    {f.label} {state === 'ok' ? `(${n})` : ''}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {state === 'loading' ? (
            <ActivityIndicator size="small" color={colors.text.secondary} />
          ) : state !== 'ok' ? (
            <OfflineNotice
              mode={state}
              detail="Deleted items could not be loaded. Do not read this as nothing deleted."
            />
          ) : shown.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.line}>Nothing deleted here.</Text>
            </GlassCard>
          ) : shown.map((row) => {
            const v = deletedRowView(row);
            const isBusy = busy === v.key;
            return (
              <GlassCard key={v.key} style={s.rowCard}>
                <View style={s.rowHead}>
                  <Text style={s.kind}>{v.kind}</Text>
                  <Text style={[s.badge, row.state === 'marked' && s.badgeMarked]}>{v.badge}</Text>
                </View>
                <Text style={s.name}>{v.name}</Text>
                {v.role ? <Text style={s.meta}>{v.role}</Text> : null}
                {v.company ? <Text style={s.meta}>Company: {v.company}</Text> : null}
                <Text style={s.meta}>Deleted by {v.by} · {v.at}</Text>
                <View style={s.actions}>
                  <Pressable onPress={() => setConfirm(row)} disabled={isBusy}
                    accessibilityRole="button" accessibilityLabel={`Restore ${v.name}`}
                    style={({ pressed }) => [s.btn, pressed && s.pressed]}>
                    {isBusy
                      ? <ActivityIndicator size="small" color={colors.text.secondary} />
                      : <RotateCcw size={15} strokeWidth={1.75} color={colors.text.primary} />}
                    <Text style={s.btnText}>Restore</Text>
                  </Pressable>
                  <Pressable onPress={() => openPreview(row)}
                    accessibilityRole="button"
                    accessibilityLabel={`Preview hard delete of ${v.name}`}
                    style={({ pressed }) => [s.btn, pressed && s.pressed]}>
                    <Eye size={15} strokeWidth={1.75} color={colors.text.primary} />
                    <Text style={s.btnText}>Preview hard delete</Text>
                  </Pressable>
                  <Pressable disabled accessibilityRole="button"
                    accessibilityState={{ disabled: true }}
                    accessibilityLabel={`Hard delete — ${v.hardDeleteReason}`}
                    style={[s.btn, s.btnDisabled]}>
                    <Lock size={15} strokeWidth={1.75} color={colors.text.subtle} />
                    <Text style={[s.btnText, { color: colors.text.subtle }]}>Hard delete</Text>
                  </Pressable>
                </View>
                <Text style={s.pending}>{v.hardDeleteReason}</Text>
              </GlassCard>
            );
          })}
        </ScrollView>

        <Modal visible={!!confirm} transparent animationType="fade"
          onRequestClose={() => setConfirm(null)}>
          <View style={s.backdrop}>
            <GlassCard variant="modal" style={s.modalCard}>
              <Text style={s.modalTitle}>Restore {confirm?.name}?</Text>
              <Text style={s.line}>
                Anything deleted in the same action comes back with it.
                {confirm?.kind === 'project' ? ' Its check-in tags are switched back on.' : ''}
              </Text>
              <View style={s.modalActions}>
                <Pressable onPress={() => setConfirm(null)} style={s.cancelBtn}
                  accessibilityRole="button">
                  <Text style={s.cancelText}>Cancel</Text>
                </Pressable>
                <Pressable onPress={restore} style={s.okBtn} accessibilityRole="button">
                  <Text style={s.okText}>Restore</Text>
                </Pressable>
              </View>
            </GlassCard>
          </View>
        </Modal>

        <Modal visible={!!preview} transparent animationType="fade"
          onRequestClose={() => setPreview(null)}>
          <View style={s.backdrop}>
            <GlassCard variant="modal" style={s.modalCard}>
              <Text style={s.modalTitle}>Hard delete preview</Text>
              <Text style={s.meta}>{preview?.row?.name}</Text>
              {preview?.state === 'loading' ? (
                <ActivityIndicator size="small" color={colors.text.secondary} />
              ) : !pv ? (
                <OfflineNotice mode={preview?.state || 'error'}
                  detail="The preview could not be loaded." />
              ) : (
                <ScrollView style={s.previewScroll}>
                  {pv.empty ? (
                    <Text style={s.line}>No records counted.</Text>
                  ) : pv.counts.map((c) => (
                    <View key={c.key} style={s.countRow}>
                      <Text style={s.line}>{c.label}</Text>
                      <Text style={s.countValue}>{c.value}</Text>
                    </View>
                  ))}
                  {pv.r2.length ? (
                    <Text style={s.meta}>Stored files (R2): {pv.r2.join(' · ')}</Text>
                  ) : null}
                  {pv.blocking.map((b) => (
                    <Text key={b} style={s.blockText}>{b}</Text>
                  ))}
                  <Text style={s.pending}>{pv.note}</Text>
                </ScrollView>
              )}
              <Pressable onPress={() => setPreview(null)} style={s.cancelBtn}
                accessibilityRole="button">
                <Text style={s.cancelText}>Close</Text>
              </Pressable>
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
    filters: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginBottom: spacing.xs },
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
    rowHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    kind: {
      fontSize: 12, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      textTransform: 'uppercase',
    },
    badge: { fontSize: 12, fontWeight: '600', color: semantic.neutral },
    badgeMarked: { color: semantic.attention },
    name: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    meta: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm },
    btn: {
      flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44,
      paddingHorizontal: spacing.md, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    btnDisabled: { opacity: 0.55 },
    btnText: { fontSize: 13, fontWeight: '500', color: colors.text.primary },
    pending: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    backdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.6),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { padding: spacing.lg, gap: spacing.sm, width: '100%', maxWidth: 440, maxHeight: '85%' },
    modalTitle: { fontSize: 17, fontWeight: '700', color: colors.text.primary },
    previewScroll: { maxHeight: 360 },
    countRow: {
      flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4,
      borderBottomWidth: 1, borderBottomColor: colors.glass.border,
    },
    countValue: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
    blockText: { fontSize: 13, color: semantic.attention, lineHeight: 18, marginTop: spacing.xs },
    modalActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
    cancelBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border,
    },
    cancelText: { fontSize: 14, color: colors.text.secondary },
    okBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, backgroundColor: colors.primary || '#2563eb',
    },
    okText: { fontSize: 14, fontWeight: '700', color: '#fff' },
    pressed: { opacity: 0.8 },
  });
}
