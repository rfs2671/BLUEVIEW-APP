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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { projectsAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';

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

  const isOwner = user?.role === 'owner';
  const s = useMemo(() => buildStyles(colors), [colors]);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  const fetchItems = useCallback(async () => {
    if (!isOwner) { setLoading(false); return; }
    try {
      const data = await projectsAPI.pendingDeletion();
      setItems(data?.items || []);
    } catch (e) {
      toast.error('Load failed', e?.response?.data?.detail || '');
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
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
      toast.error('Delete failed', e?.response?.data?.detail || '');
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

                <Pressable
                  onPress={() => { setConfirmTarget(p); setConfirmText(''); }}
                  style={s.purgeBtn}
                >
                  <Trash2 size={15} strokeWidth={2} color="#f87171" />
                  <Text style={s.purgeText}>Permanently Delete</Text>
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
    purgeBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.xs, marginTop: spacing.sm,
      paddingVertical: spacing.sm, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: 'rgba(248,113,113,0.4)',
      backgroundColor: 'rgba(248,113,113,0.08)',
    },
    purgeText: { fontSize: 13, fontWeight: '600', color: '#f87171' },
    modalBackdrop: {
      flex: 1, backgroundColor: 'rgba(0,0,0,0.7)',
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
