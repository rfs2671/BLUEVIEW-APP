/**
 * Owner-ONLY "Pending Deletion" review screen.
 *
 * A company admin's "delete" only MARKS a project (Tier 1): the project
 * disappears from their list and its NFC tags are deactivated, but nothing is
 * removed. This screen is the owner's review queue and the only place the
 * irreversible purge (Tier 2) can be triggered.
 *
 * Company admins never see this screen and cannot reach the endpoints behind
 * it — both GET /projects/pending-deletion and
 * DELETE /projects/{id}/hard-delete are gated to role:"owner" and return 403
 * for everyone else.
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
  Modal,
  TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Trash2,
  AlertTriangle,
  ShieldAlert,
  Building2,
  Lock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { projectsAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

export default function PendingDeletionScreen() {
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [confirmText, setConfirmText] = useState('');
  const [purging, setPurging] = useState(false);
  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error'. "Nothing pending deletion"
  // is a clearance statement about an irreversible queue; it must never be
  // rendered off a failed read.
  const [fetchState, setFetchState] = useState('ok');

  const isOwner = user?.role === 'owner';
  const s = useMemo(() => buildStyles(colors), [colors]);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  const fetchItems = useCallback(async () => {
    if (!isOwner) { setLoading(false); return; }
    const res = await settleFetch(() => projectsAPI.pendingDeletion());
    setFetchState(res.status);
    if (res.status === 'ok') {
      setItems(res.data?.items || []);
    } else {
      setItems([]);
      if (res.status === 'error') {
        toast.error('Load failed', res.error?.response?.data?.detail || '');
      }
    }
    setLoading(false);
    setRefreshing(false);
  }, [isOwner]);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  const handlePurge = async () => {
    if (!confirmTarget) return;
    setPurging(true);
    try {
      const res = await projectsAPI.hardDelete(confirmTarget.id);
      setItems((prev) => prev.filter((p) => p.id !== confirmTarget.id));
      const n = Object.values(res?.deleted || {}).reduce(
        (a, b) => a + (typeof b === 'number' ? b : 0), 0,
      );
      toast.success('Permanently deleted', `${confirmTarget.name} — ${n} records removed`);
      setConfirmTarget(null);
      setConfirmText('');
    } catch (e) {
      // The purge is irreversible and server-side only — an offline failure
      // means NOTHING was deleted, and must not read as an ambiguous error.
      if (isOfflineError(e)) {
        toast.error('Offline', 'Permanent deletion needs a connection. Nothing was deleted.');
      } else if (e?.response?.status === 409) {
        // THE RETENTION BRAKE, from a list this screen loaded earlier. A hold
        // placed since the last refresh means the button was still live here
        // while the server had already stopped allowing it. Say what the
        // server said and re-read, rather than reporting a generic failure on
        // a record that is legally protected.
        toast.error('Deletion blocked', e?.response?.data?.detail || '');
        setConfirmTarget(null);
        setConfirmText('');
        fetchItems();
      } else {
        toast.error('Delete failed', e?.response?.data?.detail || '');
      }
    } finally {
      setPurging(false);
    }
  };

  const fmt = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleString();
  };

  // Non-owners get a plain refusal rather than an empty list, so the gate is
  // obvious rather than looking like "nothing pending".
  if (!authLoading && isAuthenticated && !isOwner) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.header}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <Text style={s.headerTitle}>Pending Deletion</Text>
          </View>
          <GlassCard style={s.emptyCard}>
            <ShieldAlert size={28} strokeWidth={1.5} color="#f87171" />
            <Text style={s.emptyText}>Owner access required</Text>
          </GlassCard>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.back()}
          />
          <Text style={s.headerTitle}>Pending Deletion</Text>
        </View>

        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); fetchItems(); }}
            />
          }
        >
          <Text style={s.subtitle}>
            Projects an admin has marked for deletion. Data is still intact
            until you permanently delete it here.
          </Text>

          {loading ? (
            <View style={s.centered}>
              <ActivityIndicator size="small" color={colors.text.secondary} />
            </View>
          ) : fetchState !== 'ok' ? (
            <OfflineNotice
              mode={fetchState}
              detail={fetchState === 'offline'
                ? 'The deletion queue could not be loaded. Do NOT read this as "nothing pending" — projects may be awaiting review. Purging also needs a connection.'
                : 'The deletion queue could not be loaded, so pending projects are unknown.'}
            />
          ) : items.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.emptyText}>Nothing pending deletion</Text>
            </GlassCard>
          ) : (
            items.map((p) => (
              <GlassCard key={p.id} style={s.itemCard}>
                <View style={s.itemHeader}>
                  <Building2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.projectName}>{p.name || 'Unnamed project'}</Text>
                </View>
                {!!p.address && <Text style={s.meta}>{p.address}</Text>}
                {!!p.nyc_bin && <Text style={s.meta}>BIN {p.nyc_bin}</Text>}
                <Text style={s.meta}>Marked {fmt(p.marked_at)}</Text>
                <Text style={s.counts}>
                  {p.dob_logs_count} DOB records · {p.checkins_count} check-ins
                </Text>

                {/* RETENTION. The counts above say how much a purge destroys;
                    this says whether the law still wants it kept. Rendered
                    off purge_blocked / purge_block_reason, which the server
                    computes with the SAME function the purge endpoint calls
                    — so this can never offer a button the server refuses. */}
                {p.purge_blocked ? (
                  <View style={s.holdBanner}>
                    <Lock size={14} strokeWidth={2} color={semantic.attention} />
                    <Text style={s.holdText}>{p.purge_block_reason}</Text>
                  </View>
                ) : p.job_completion_date ? (
                  <Text style={s.retentionOk}>
                    Completed {p.job_completion_date} · retention period ended
                    {p.purge_eligible_at ? ` ${p.purge_eligible_at}` : ''}
                  </Text>
                ) : (
                  /* NOT a clearance. No completion date was ever recorded, so
                     the seven-year period is not computable for this project
                     and nothing here has checked it. Saying "no retention
                     hold" would be a claim nobody verified. */
                  <Text style={s.retentionUnknown}>
                    No completion date recorded — retention period unknown
                  </Text>
                )}

                <Pressable
                  onPress={() => {
                    if (p.purge_blocked) return;
                    setConfirmTarget(p);
                    setConfirmText('');
                  }}
                  disabled={!!p.purge_blocked}
                  style={[s.purgeBtn, p.purge_blocked && s.purgeBtnBlocked]}
                >
                  <Trash2
                    size={15}
                    strokeWidth={2}
                    color={p.purge_blocked ? colors.text.subtle : '#f87171'}
                  />
                  <Text
                    style={[
                      s.purgeText,
                      p.purge_blocked && { color: colors.text.subtle },
                    ]}
                  >
                    {p.purge_blocked ? 'Deletion blocked' : 'Permanently Delete'}
                  </Text>
                </Pressable>
              </GlassCard>
            ))
          )}
        </ScrollView>

        {/* Type-to-confirm: this is irreversible and cascades to storage. */}
        <Modal visible={!!confirmTarget} transparent animationType="fade">
          <View style={s.modalBackdrop}>
            <GlassCard variant="modal" style={s.modalCard}>
              <View style={s.itemHeader}>
                <AlertTriangle size={18} strokeWidth={2} color="#f87171" />
                <Text style={s.modalTitle}>Permanently delete?</Text>
              </View>
              <Text style={s.modalBody}>
                This removes {confirmTarget?.name} and ALL of its data — DOB
                records, check-ins, logbooks, files and stored images. This
                cannot be undone.
              </Text>
              <Text style={s.modalPrompt}>
                Type the project name to confirm:
              </Text>
              <TextInput
                value={confirmText}
                onChangeText={setConfirmText}
                placeholder={confirmTarget?.name || ''}
                placeholderTextColor={colors.text.subtle}
                style={s.confirmInput}
                autoCapitalize="none"
              />
              <View style={s.modalActions}>
                <Pressable
                  onPress={() => { setConfirmTarget(null); setConfirmText(''); }}
                  style={s.cancelBtn}
                >
                  <Text style={s.cancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  onPress={handlePurge}
                  disabled={purging || confirmText !== (confirmTarget?.name || '')}
                  style={[
                    s.confirmBtn,
                    (purging || confirmText !== (confirmTarget?.name || '')) && s.btnDisabled,
                  ]}
                >
                  <Text style={s.confirmBtnText}>
                    {purging ? 'Deleting…' : 'Delete forever'}
                  </Text>
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
    header: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    },
    headerTitle: {
      ...typography.label, fontSize: 16, fontWeight: '600',
      color: colors.text.primary,
    },
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
    subtitle: {
      fontSize: 13, color: colors.text.muted, marginBottom: spacing.sm,
      lineHeight: 18,
    },
    centered: { padding: spacing.xl, alignItems: 'center' },
    emptyCard: {
      padding: spacing.lg, alignItems: 'center', gap: spacing.sm,
      margin: spacing.lg,
    },
    emptyText: { fontSize: 15, color: colors.text.primary },
    itemCard: { padding: spacing.md, gap: 4 },
    itemHeader: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    },
    projectName: {
      fontSize: 16, fontWeight: '600', color: colors.text.primary, flex: 1,
    },
    meta: { fontSize: 13, color: colors.text.secondary },
    counts: {
      fontSize: 12, color: colors.text.muted, marginTop: 2,
    },
    holdBanner: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs,
      marginTop: spacing.sm, padding: spacing.sm,
      borderRadius: borderRadius.md,
      backgroundColor: semantic.attentionBg,
      borderWidth: 1, borderColor: semantic.attentionBorder,
    },
    holdText: {
      flex: 1, fontSize: 12, lineHeight: 17, color: semantic.attention,
    },
    retentionOk: {
      fontSize: 12, color: colors.text.muted, marginTop: spacing.xs,
    },
    retentionUnknown: {
      fontSize: 12, color: colors.text.subtle, marginTop: spacing.xs,
      fontStyle: 'italic',
    },
    purgeBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.xs, marginTop: spacing.sm,
      paddingVertical: spacing.sm, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: semantic.criticalBorder,
      backgroundColor: semantic.criticalBg,
    },
    purgeText: { fontSize: 13, fontWeight: '600', color: '#f87171' },
    // Blocked reads as INERT, not as a red button that failed. The red
    // affordance is removed entirely so the control does not invite a tap
    // the server is going to refuse.
    purgeBtnBlocked: {
      borderColor: colors.border?.subtle || 'transparent',
      backgroundColor: 'transparent',
    },
    modalBackdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.7),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { padding: spacing.lg, gap: spacing.sm, width: '100%', maxWidth: 440 },
    modalTitle: { fontSize: 17, fontWeight: '700', color: '#f87171' },
    modalBody: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    modalPrompt: { fontSize: 13, color: colors.text.muted, marginTop: spacing.xs },
    confirmInput: {
      borderWidth: 1, borderColor: colors.glass.border,
      borderRadius: borderRadius.lg, padding: spacing.sm,
      color: colors.text.primary, fontSize: 15,
    },
    modalActions: {
      flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm,
    },
    cancelBtn: {
      flex: 1, paddingVertical: spacing.sm, alignItems: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: colors.glass.border,
    },
    cancelText: { fontSize: 14, color: colors.text.secondary },
    confirmBtn: {
      flex: 1, paddingVertical: spacing.sm, alignItems: 'center',
      borderRadius: borderRadius.lg, backgroundColor: '#dc2626',
    },
    btnDisabled: { opacity: 0.4 },
    confirmBtnText: { fontSize: 14, fontWeight: '700', color: '#fff' },
  });
}
