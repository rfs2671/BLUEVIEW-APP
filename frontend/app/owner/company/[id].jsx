import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldAlert, Trash2, UserPlus, ChevronDown, Check } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassInput from '../../../src/components/GlassInput';
import OwnerNav from '../../../src/components/OwnerNav';
import OfflineNotice from '../../../src/components/OfflineNotice';
import { useToast } from '../../../src/components/Toast';
import { useAuth, isPlatformOperator } from '../../../src/context/AuthContext';
import { useTheme } from '../../../src/context/ThemeContext';
import { ownerAPI } from '../../../src/utils/api';
import { settleFetch, isOfflineError } from '../../../src/utils/offlineState';
import {
  roleLabel, userActions, addAdminRequest, serverMessage,
} from '../../../src/utils/ownerPortal';
import { spacing, borderRadius } from '../../../src/styles/theme';
import { semantic, withAlpha } from '../../../src/styles/semanticColors';

/**
 * OWNER PORTAL → a company: its users with their roles. The operator adds an
 * admin (an existing user of this company, or a new account with a
 * password), changes a role, or removes a user. The company's only admin
 * cannot be demoted or removed; every change is an audit row (server side).
 */
export default function OwnerCompanyScreen() {
  const { id } = useLocalSearchParams();
  const companyId = Array.isArray(id) ? id[0] : id;
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const isOperator = isPlatformOperator(user);

  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | offline | error
  const [busy, setBusy] = useState(null);
  const [roleFor, setRoleFor] = useState(null); // user row whose role picker is open
  const [confirmRemove, setConfirmRemove] = useState(null);
  const [form, setForm] = useState({ email: '', name: '', password: '' });
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated]);

  const load = useCallback(async () => {
    if (!isOperator || !companyId) return;
    const res = await settleFetch(() => ownerAPI.companyUsers(companyId));
    setState(res.status);
    if (res.status === 'ok') setData(res.data);
  }, [isOperator, companyId]);

  useEffect(() => { load(); }, [load]);

  const users = data?.users || [];
  const roles = data?.assignable_roles || ['admin', 'pm', 'superintendent', 'cp'];

  const fail = (e, title) => {
    toast.error(title, isOfflineError(e)
      ? 'This needs a connection. Nothing changed.'
      : serverMessage(e));
  };

  const addAdmin = async () => {
    const req = addAdminRequest(form);
    if (req.error) { toast.error('Add admin', req.error); return; }
    setAdding(true);
    try {
      const res = await ownerAPI.addCompanyAdmin(companyId, req.body);
      toast.success(res.created ? 'Admin created' : 'Made admin',
        `${res.user?.name || res.user?.email || ''}`);
      setForm({ email: '', name: '', password: '' });
      await load();
    } catch (e) {
      fail(e, 'Could not add admin');
    } finally {
      setAdding(false);
    }
  };

  const changeRole = async (u, role) => {
    setRoleFor(null);
    if (role === u.role) return;
    setBusy(u.id);
    try {
      await ownerAPI.changeUserRole(companyId, u.id, role);
      toast.success('Role changed', `${u.name || u.email}: ${roleLabel(role)}`);
      await load();
    } catch (e) {
      fail(e, 'Role not changed');
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    const u = confirmRemove;
    setConfirmRemove(null);
    if (!u) return;
    setBusy(u.id);
    try {
      await ownerAPI.removeCompanyUser(companyId, u.id);
      toast.success('Removed', `${u.name || u.email} is on Deleted items and can be restored.`);
      await load();
    } catch (e) {
      fail(e, 'Not removed');
    } finally {
      setBusy(null);
    }
  };

  if (!authLoading && isAuthenticated && !isOperator) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <OwnerNav />
          <GlassCard style={s.card}>
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
        <OwnerNav title={data?.company?.name || 'Company'} />
        <ScrollView style={s.scroll} contentContainerStyle={s.content}>
          {state === 'loading' ? (
            <ActivityIndicator size="small" color={colors.text.secondary} />
          ) : state !== 'ok' ? (
            <OfflineNotice
              mode={state}
              detail="This company's users could not be loaded. Nothing below is known."
            />
          ) : (
            <>
              {data?.company?.is_deleted ? (
                <Text style={s.warn}>
                  This company is deleted. Restore it from Deleted items to change its admins.
                </Text>
              ) : null}

              <Text style={s.section}>
                Users ({users.length}) · {data?.admin_count || 0} admin
                {data?.admin_count === 1 ? '' : 's'}
              </Text>
              {users.length === 0 ? (
                <GlassCard style={s.card}>
                  <Text style={s.line}>No users in this company.</Text>
                </GlassCard>
              ) : users.map((u) => {
                const a = userActions(u, users);
                return (
                  <GlassCard key={u.id} style={s.userCard}>
                    <View style={s.userRow}>
                      <View style={s.userText}>
                        <Text style={s.userName}>{u.name || u.email}</Text>
                        <Text style={s.meta}>{u.email}</Text>
                        {a.lockedReason ? <Text style={s.metaMuted}>{a.lockedReason}</Text> : null}
                      </View>
                      {busy === u.id ? (
                        <ActivityIndicator size="small" color={colors.text.secondary} />
                      ) : (
                        <View style={s.actions}>
                          <Pressable
                            onPress={() => a.canChangeRole && setRoleFor(u)}
                            disabled={!a.canChangeRole || !!data?.company?.is_deleted}
                            accessibilityRole="button"
                            accessibilityLabel={`Role: ${roleLabel(u.role)}. Change role`}
                            style={({ pressed }) => [s.roleBtn,
                              (!a.canChangeRole || data?.company?.is_deleted) && s.disabled,
                              pressed && s.pressed]}
                          >
                            <Text style={s.roleText}>{roleLabel(u.role)}</Text>
                            {a.canChangeRole ? <ChevronDown size={14} color={colors.text.muted} /> : null}
                          </Pressable>
                          <Pressable
                            onPress={() => setConfirmRemove(u)}
                            disabled={!a.canRemove || !!data?.company?.is_deleted}
                            accessibilityRole="button"
                            accessibilityLabel={`Remove ${u.name || u.email}`}
                            style={({ pressed }) => [s.iconBtn,
                              (!a.canRemove || data?.company?.is_deleted) && s.disabled,
                              pressed && s.pressed]}
                          >
                            <Trash2 size={16} strokeWidth={1.75} color={semantic.neutral} />
                          </Pressable>
                        </View>
                      )}
                    </View>
                  </GlassCard>
                );
              })}

              {!data?.company?.is_deleted ? (
                <GlassCard style={s.formCard}>
                  <View style={s.formHead}>
                    <UserPlus size={18} strokeWidth={1.75} color={colors.text.primary} />
                    <Text style={s.formTitle}>Add admin</Text>
                  </View>
                  <Text style={s.metaMuted}>
                    Someone already in this company is made an admin. For a new
                    person, also enter a name and a password to give them.
                  </Text>
                  <GlassInput
                    value={form.email}
                    onChangeText={(v) => setForm((f) => ({ ...f, email: v }))}
                    placeholder="Email"
                    keyboardType="email-address"
                    autoCapitalize="none"
                  />
                  <GlassInput
                    value={form.name}
                    onChangeText={(v) => setForm((f) => ({ ...f, name: v }))}
                    placeholder="Name (new account only)"
                    autoCapitalize="words"
                  />
                  <GlassInput
                    value={form.password}
                    onChangeText={(v) => setForm((f) => ({ ...f, password: v }))}
                    placeholder="Password (new account only)"
                    secureTextEntry
                    autoCapitalize="none"
                  />
                  <Pressable
                    onPress={addAdmin}
                    disabled={adding}
                    accessibilityRole="button"
                    style={({ pressed }) => [s.primaryBtn, adding && s.disabled, pressed && s.pressed]}
                  >
                    {adding
                      ? <ActivityIndicator size="small" color="#fff" />
                      : <Text style={s.primaryText}>Add admin</Text>}
                  </Pressable>
                </GlassCard>
              ) : null}
            </>
          )}
        </ScrollView>

        <Modal visible={!!roleFor} transparent animationType="fade"
          onRequestClose={() => setRoleFor(null)}>
          <Pressable style={s.backdrop} onPress={() => setRoleFor(null)}>
            <GlassCard variant="modal" style={s.modalCard}>
              <Text style={s.formTitle}>Role for {roleFor?.name || roleFor?.email}</Text>
              {roles.map((r) => (
                <Pressable key={r} onPress={() => changeRole(roleFor, r)}
                  accessibilityRole="button"
                  style={({ pressed }) => [s.option, pressed && s.pressed]}>
                  <Text style={s.optionText}>{roleLabel(r)}</Text>
                  {roleFor?.role === r ? <Check size={16} color={semantic.verified} /> : null}
                </Pressable>
              ))}
              <Pressable onPress={() => setRoleFor(null)} style={s.cancelBtn}
                accessibilityRole="button">
                <Text style={s.cancelText}>Cancel</Text>
              </Pressable>
            </GlassCard>
          </Pressable>
        </Modal>

        <Modal visible={!!confirmRemove} transparent animationType="fade"
          onRequestClose={() => setConfirmRemove(null)}>
          <View style={s.backdrop}>
            <GlassCard variant="modal" style={s.modalCard}>
              <Text style={s.formTitle}>Remove {confirmRemove?.name || confirmRemove?.email}?</Text>
              <Text style={s.line}>
                They lose access to this company. The account moves to Deleted
                items, where it can be restored.
              </Text>
              <View style={s.modalActions}>
                <Pressable onPress={() => setConfirmRemove(null)} style={s.cancelBtn}
                  accessibilityRole="button">
                  <Text style={s.cancelText}>Cancel</Text>
                </Pressable>
                <Pressable onPress={remove} style={s.dangerBtn} accessibilityRole="button">
                  <Text style={s.primaryText}>Remove</Text>
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
    section: { fontSize: 13, fontWeight: '600', color: colors.text.muted, marginTop: spacing.xs },
    card: { padding: spacing.lg, alignItems: 'center', gap: spacing.sm },
    line: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    warn: { fontSize: 13, color: semantic.attention, lineHeight: 18 },
    userCard: { padding: spacing.md },
    // Wraps on a phone: the role and remove buttons go under the name.
    userRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
    userText: { flex: 1, minWidth: 180 },
    userName: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    meta: { fontSize: 13, color: colors.text.secondary },
    metaMuted: { fontSize: 12, color: colors.text.muted, lineHeight: 17 },
    actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginLeft: 'auto' },
    roleBtn: {
      flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 44,
      paddingHorizontal: spacing.sm, borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    roleText: { fontSize: 13, fontWeight: '500', color: colors.text.primary },
    iconBtn: {
      width: 44, height: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
    },
    formCard: { padding: spacing.md, gap: spacing.sm, marginTop: spacing.md },
    formHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    formTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    primaryBtn: {
      minHeight: 48, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, backgroundColor: colors.primary || '#2563eb',
    },
    primaryText: { fontSize: 15, fontWeight: '600', color: '#fff' },
    dangerBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, backgroundColor: '#dc2626',
    },
    backdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.6),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { padding: spacing.lg, gap: spacing.sm, width: '100%', maxWidth: 420 },
    option: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      minHeight: 44, paddingHorizontal: spacing.sm,
    },
    optionText: { fontSize: 15, color: colors.text.primary },
    modalActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
    cancelBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border,
    },
    cancelText: { fontSize: 14, color: colors.text.secondary },
    disabled: { opacity: 0.4 },
    pressed: { opacity: 0.8 },
  });
}
