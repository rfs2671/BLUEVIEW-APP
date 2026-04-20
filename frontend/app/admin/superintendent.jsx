import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Switch,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Plus,
  Trash2,
  X,
  ChevronDown,
  AlertTriangle,
  Pencil,
  HardHat,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI, csRegistrationAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';

const CLASS_BADGES = {
  major_b: { label: 'MAJOR B', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
  major_a: { label: 'MAJOR A', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  regular: { label: 'REGULAR', color: null, bg: null }, // uses muted
};

export default function SuperintendentScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [registrations, setRegistrations] = useState([]);
  const [projects, setProjects] = useState([]);

  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingReg, setEditingReg] = useState(null);

  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    project_id: '',
    full_name: '',
    license_number: '',
    nyc_id_email: '',
    sst_number: '',
    phone: '',
  });

  const [conflictDialog, setConflictDialog] = useState(null);

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (!isAdmin) {
        router.replace('/');
        toast.error('Access Denied', 'Admin access required');
      }
    }
  }, [isAuthenticated, authLoading, isAdmin]);

  useEffect(() => {
    if (isAuthenticated && isAdmin) fetchData();
  }, [isAuthenticated, isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [regs, projs] = await Promise.all([
        csRegistrationAPI.getAll().catch(() => []),
        projectsAPI.getAll().catch(() => []),
      ]);
      setRegistrations(Array.isArray(regs) ? regs : (regs?.items || []));
      setProjects(Array.isArray(projs) ? projs : (projs?.items || []));
    } catch (e) {
      console.error('Load failed:', e);
      toast.error('Load Error', 'Could not load superintendent registrations');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setForm({
      project_id: '',
      full_name: '',
      license_number: '',
      nyc_id_email: '',
      sst_number: '',
      phone: '',
    });
  };

  const openRegister = () => {
    resetForm();
    setShowRegisterModal(true);
  };

  const openEdit = (reg) => {
    setEditingReg(reg);
    setForm({
      project_id: reg.project_id || '',
      full_name: reg.full_name || '',
      license_number: reg.license_number || '',
      nyc_id_email: reg.nyc_id_email || '',
      sst_number: reg.sst_number || '',
      phone: reg.phone || '',
    });
    setShowEditModal(true);
  };

  const handleRegister = async () => {
    if (!form.project_id || !form.full_name.trim() || !form.license_number.trim()) {
      toast.warning(
        'Missing Fields',
        'Project, full name, and license number are required'
      );
      return;
    }
    setSaving(true);
    try {
      const payload = {
        project_id: form.project_id,
        full_name: form.full_name.trim(),
        license_number: form.license_number.trim(),
        nyc_id_email: form.nyc_id_email.trim() || null,
        sst_number: form.sst_number.trim() || null,
        phone: form.phone.trim() || null,
      };
      const result = await csRegistrationAPI.create(payload);

      if (result?.conflict_warning) {
        // Conflict path — do NOT show success toast. Custom modal instead.
        setConflictDialog({ message: result.conflict_warning });
        setShowRegisterModal(false);
        resetForm();
        fetchData();
      } else {
        toast.success('Registered', 'Superintendent registered');
        setShowRegisterModal(false);
        resetForm();
        fetchData();
      }
    } catch (e) {
      console.error('Register CS failed:', e);
      toast.error(
        'Error',
        e.response?.data?.detail || 'Could not register superintendent'
      );
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingReg) return;
    setSaving(true);
    try {
      const changed = {};
      if (form.full_name.trim() !== (editingReg.full_name || ''))
        changed.full_name = form.full_name.trim();
      if (form.license_number.trim() !== (editingReg.license_number || ''))
        changed.license_number = form.license_number.trim();
      const emailNew = form.nyc_id_email.trim() || null;
      if (emailNew !== (editingReg.nyc_id_email || null))
        changed.nyc_id_email = emailNew;
      const sstNew = form.sst_number.trim() || null;
      if (sstNew !== (editingReg.sst_number || null))
        changed.sst_number = sstNew;
      const phoneNew = form.phone.trim() || null;
      if (phoneNew !== (editingReg.phone || null))
        changed.phone = phoneNew;

      if (Object.keys(changed).length === 0) {
        setShowEditModal(false);
        return;
      }
      await csRegistrationAPI.update(editingReg.id || editingReg._id, changed);
      toast.success('Saved', 'Registration updated');
      setShowEditModal(false);
      setEditingReg(null);
      fetchData();
    } catch (e) {
      console.error('Edit CS failed:', e);
      toast.error('Error', e.response?.data?.detail || 'Could not update');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (newActive) => {
    if (!editingReg) return;
    try {
      await csRegistrationAPI.update(editingReg.id || editingReg._id, {
        is_active: newActive,
      });
      setEditingReg({ ...editingReg, is_active: newActive });
      toast.success('Updated', newActive ? 'Marked active' : 'Marked inactive');
      fetchData();
    } catch (e) {
      toast.error('Error', 'Could not change active status');
    }
  };

  const handleDelete = async (reg) => {
    const confirmed = Platform.OS === 'web'
      ? window.confirm(
          'Remove this superintendent? License will be marked inactive on this project.'
        )
      : await new Promise((resolve) => {
          const { Alert } = require('react-native');
          Alert.alert(
            'Remove Superintendent',
            'Remove this superintendent? License will be marked inactive on this project.',
            [
              { text: 'Cancel', onPress: () => resolve(false), style: 'cancel' },
              { text: 'Remove', onPress: () => resolve(true), style: 'destructive' },
            ]
          );
        });
    if (!confirmed) return;
    try {
      await csRegistrationAPI.delete(reg.id || reg._id);
      toast.success('Removed', 'Superintendent registration removed');
      fetchData();
    } catch (e) {
      console.error('Delete CS failed:', e);
      toast.error('Error', 'Could not remove registration');
    }
  };

  const selectedProject = projects.find(
    (p) => (p._id || p.id) === form.project_id
  );
  const editingProjectName = editingReg
    ? (registrations.find((r) => (r.id || r._id) === (editingReg.id || editingReg._id))?.project_name
       || projects.find((p) => (p._id || p.id) === editingReg.project_id)?.name
       || editingReg.project_name
       || 'Project')
    : '';

  const anyConflict = registrations.some((r) => r.has_conflict);

  const renderClassBadge = (cls) => {
    const spec = CLASS_BADGES[cls] || CLASS_BADGES.regular;
    return (
      <View
        style={[
          s.classBadge,
          spec.bg ? { backgroundColor: spec.bg } : { backgroundColor: 'rgba(100,116,139,0.2)' },
        ]}
      >
        <Text
          style={[
            s.classBadgeText,
            { color: spec.color || colors.text.muted },
          ]}
        >
          {spec.label}
        </Text>
      </View>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
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
            <Text style={s.titleLabel}>ADMIN</Text>
            <Text style={s.titleText}>Superintendents</Text>
            <Text style={s.subtitle}>
              NYC DOB one-job rule — one CS license per active job (eff. Jan 2026)
            </Text>
          </View>

          <GlassButton
            title="Register Superintendent"
            icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={openRegister}
            style={s.addButton}
          />

          {anyConflict && (
            <View style={s.conflictBanner}>
              <AlertTriangle size={18} strokeWidth={1.5} color="#ef4444" />
              <Text style={s.conflictBannerText}>
                One or more superintendents are registered on multiple active projects.
                NYC DOB one-job rule violation — resolve before next inspection.
              </Text>
            </View>
          )}

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={110} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={110} borderRadiusValue={borderRadius.xl} />
            </>
          ) : registrations.length > 0 ? (
            <View style={s.list}>
              {registrations.map((reg) => (
                <GlassCard key={reg.id || reg._id} style={s.card}>
                  <View style={s.cardRow}>
                    <IconPod size={40}>
                      <HardHat size={18} strokeWidth={1.5} color={reg.is_active ? '#4ade80' : colors.text.muted} />
                    </IconPod>
                    <View style={s.cardInfo}>
                      <Text style={s.name}>{reg.full_name}</Text>
                    </View>
                    <View style={[s.statusBadge, reg.is_active && s.statusActive]}>
                      <Text
                        style={[
                          s.statusText,
                          reg.is_active && s.statusTextActive,
                        ]}
                      >
                        {reg.is_active ? 'ACTIVE' : 'INACTIVE'}
                      </Text>
                    </View>
                  </View>

                  {reg.has_conflict && (
                    <View style={s.conflictBadgeRow}>
                      <View style={s.conflictBadge}>
                        <Text style={s.conflictBadgeText}>⚠ ONE-JOB CONFLICT</Text>
                      </View>
                    </View>
                  )}

                  <Text style={s.licenseText}>{reg.license_number || '—'}</Text>
                  <Text style={s.projectText} numberOfLines={1}>
                    {reg.project_name || 'Project'}
                  </Text>
                  {reg.nyc_id_email ? (
                    <Text style={s.nycidText} numberOfLines={1}>
                      {reg.nyc_id_email}
                    </Text>
                  ) : null}

                  <View style={s.cardActions}>
                    <Pressable
                      onPress={() => openEdit(reg)}
                      hitSlop={10}
                      style={s.iconBtn}
                    >
                      <Pencil size={16} strokeWidth={1.5} color={colors.text.muted} />
                    </Pressable>
                    <Pressable
                      onPress={() => handleDelete(reg)}
                      hitSlop={10}
                      style={s.iconBtn}
                    >
                      <Trash2 size={16} strokeWidth={1.5} color="#ef4444" />
                    </Pressable>
                  </View>
                </GlassCard>
              ))}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <IconPod size={64}>
                <HardHat size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={s.emptyTitle}>No Superintendents Registered</Text>
              <Text style={s.emptyText}>
                Register a Construction Superintendent on each active project to comply
                with the NYC DOB one-job rule.
              </Text>
            </GlassCard>
          )}
        </ScrollView>

        <FloatingNav />

        {/* Register Modal */}
        <Modal
          visible={showRegisterModal}
          animationType="slide"
          transparent
          onRequestClose={() => setShowRegisterModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={s.modalOverlay}
          >
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Register Superintendent</Text>
                <Pressable onPress={() => setShowRegisterModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>
              <ScrollView style={s.modalScroll}>
                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PROJECT</Text>
                  <Pressable
                    style={s.selectorCard}
                    onPress={() => setShowProjectPicker(!showProjectPicker)}
                  >
                    <Text
                      style={[
                        s.selectorText,
                        !form.project_id && s.selectorPlaceholder,
                      ]}
                    >
                      {selectedProject?.name || 'Select a project'}
                    </Text>
                    <ChevronDown
                      size={20}
                      strokeWidth={1.5}
                      color={colors.text.muted}
                      style={showProjectPicker && s.iconRotated}
                    />
                  </Pressable>
                  {showProjectPicker && (
                    <View style={s.dropdown}>
                      {projects.map((p) => {
                        const pid = p._id || p.id;
                        const cls = (p.project_class || 'regular').toLowerCase();
                        return (
                          <Pressable
                            key={pid}
                            onPress={() => {
                              setForm({ ...form, project_id: pid });
                              setShowProjectPicker(false);
                            }}
                            style={[
                              s.dropdownItem,
                              form.project_id === pid && s.dropdownItemActive,
                            ]}
                          >
                            <Text style={s.dropdownText}>{p.name}</Text>
                            {renderClassBadge(cls)}
                          </Pressable>
                        );
                      })}
                    </View>
                  )}
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>FULL NAME</Text>
                  <GlassInput
                    value={form.full_name}
                    onChangeText={(v) => setForm({ ...form, full_name: v })}
                    placeholder="Construction Superintendent full name"
                    autoCapitalize="words"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE NUMBER</Text>
                  <GlassInput
                    value={form.license_number}
                    onChangeText={(v) => setForm({ ...form, license_number: v })}
                    placeholder="NYC DOB CS License #"
                    autoCapitalize="characters"
                  />
                  <Text style={s.helperText}>
                    Checked against all active projects for one-job rule compliance
                  </Text>
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>NYC.ID EMAIL</Text>
                  <GlassInput
                    value={form.nyc_id_email}
                    onChangeText={(v) => setForm({ ...form, nyc_id_email: v })}
                    placeholder="NYC.ID email for DOB filings (optional)"
                    keyboardType="email-address"
                    autoCapitalize="none"
                  />
                  <Text style={s.helperText}>
                    Used for DOB NOW filings and signature audit trail
                  </Text>
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>SST NUMBER</Text>
                  <GlassInput
                    value={form.sst_number}
                    onChangeText={(v) => setForm({ ...form, sst_number: v })}
                    placeholder="SST card number (optional)"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PHONE</Text>
                  <GlassInput
                    value={form.phone}
                    onChangeText={(v) => setForm({ ...form, phone: v })}
                    placeholder="Phone (optional)"
                    keyboardType="phone-pad"
                  />
                </View>
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowRegisterModal(false)}
                  style={s.cancelBtn}
                />
                <GlassButton
                  title={saving ? 'Registering...' : 'Register'}
                  onPress={handleRegister}
                  loading={saving}
                  style={s.createBtn}
                />
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        {/* Edit Modal */}
        <Modal
          visible={showEditModal}
          animationType="slide"
          transparent
          onRequestClose={() => setShowEditModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={s.modalOverlay}
          >
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Edit Superintendent</Text>
                <Pressable onPress={() => setShowEditModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>
              <ScrollView style={s.modalScroll}>
                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PROJECT</Text>
                  <View style={s.readonlyBox}>
                    <Text style={s.readonlyText}>{editingProjectName}</Text>
                  </View>
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>FULL NAME</Text>
                  <GlassInput
                    value={form.full_name}
                    onChangeText={(v) => setForm({ ...form, full_name: v })}
                    placeholder="Construction Superintendent full name"
                    autoCapitalize="words"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE NUMBER</Text>
                  <GlassInput
                    value={form.license_number}
                    onChangeText={(v) => setForm({ ...form, license_number: v })}
                    placeholder="NYC DOB CS License #"
                    autoCapitalize="characters"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>NYC.ID EMAIL</Text>
                  <GlassInput
                    value={form.nyc_id_email}
                    onChangeText={(v) => setForm({ ...form, nyc_id_email: v })}
                    placeholder="NYC.ID email for DOB filings (optional)"
                    keyboardType="email-address"
                    autoCapitalize="none"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>SST NUMBER</Text>
                  <GlassInput
                    value={form.sst_number}
                    onChangeText={(v) => setForm({ ...form, sst_number: v })}
                    placeholder="SST card number (optional)"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PHONE</Text>
                  <GlassInput
                    value={form.phone}
                    onChangeText={(v) => setForm({ ...form, phone: v })}
                    placeholder="Phone (optional)"
                    keyboardType="phone-pad"
                  />
                </View>

                <View style={s.toggleRow}>
                  <Text style={s.toggleLabel}>Active on this project</Text>
                  <Switch
                    value={!!editingReg?.is_active}
                    onValueChange={handleToggleActive}
                    trackColor={{ false: 'rgba(100,116,139,0.4)', true: 'rgba(74,222,128,0.6)' }}
                    thumbColor={editingReg?.is_active ? '#4ade80' : '#94a3b8'}
                  />
                </View>
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowEditModal(false)}
                  style={s.cancelBtn}
                />
                <GlassButton
                  title={saving ? 'Saving...' : 'Save'}
                  onPress={handleSaveEdit}
                  loading={saving}
                  style={s.createBtn}
                />
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        {/* Conflict Modal */}
        <Modal
          visible={!!conflictDialog}
          animationType="fade"
          transparent
          onRequestClose={() => setConflictDialog(null)}
        >
          <View style={s.modalOverlay}>
            <GlassCard style={s.conflictModal}>
              <View style={s.conflictIconRow}>
                <AlertTriangle size={28} strokeWidth={1.5} color="#ef4444" />
              </View>
              <Text style={s.conflictTitle}>⚠ One-Job Rule Conflict Detected</Text>
              <Text style={s.conflictBody}>
                {conflictDialog?.message || ''}
              </Text>
              <Text style={s.conflictSub}>
                Registration saved. A compliance alert has been filed. Resolve before
                the next DOB inspection.
              </Text>
              <GlassButton
                title="Understood"
                onPress={() => setConflictDialog(null)}
                style={s.doneBtn}
              />
            </GlassCard>
          </View>
        </Modal>
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
      borderBottomColor: 'rgba(255, 255, 255, 0.08)',
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    titleSection: { marginBottom: spacing.lg },
    titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
    titleText: {
      fontSize: 48,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -1,
    },
    subtitle: { fontSize: 14, color: colors.text.muted, marginTop: spacing.sm },
    addButton: { marginBottom: spacing.lg },
    mb12: { marginBottom: spacing.sm + 4 },
    conflictBanner: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      backgroundColor: 'rgba(239,68,68,0.1)',
      borderWidth: 1,
      borderColor: 'rgba(239,68,68,0.3)',
      borderRadius: 12,
      padding: 16,
      marginBottom: 16,
    },
    conflictBannerText: {
      flex: 1,
      fontSize: 13,
      color: '#ef4444',
      lineHeight: 18,
    },
    list: { gap: spacing.md },
    card: { padding: spacing.lg },
    cardRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      marginBottom: spacing.sm,
    },
    cardInfo: { flex: 1 },
    name: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    licenseText: {
      fontSize: 13,
      color: colors.text.muted,
      fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
      marginTop: 4,
    },
    projectText: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 2,
    },
    nycidText: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    statusBadge: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 4,
      borderRadius: borderRadius.full,
      backgroundColor: 'rgba(100,116,139,0.2)',
    },
    statusActive: { backgroundColor: 'rgba(74,222,128,0.15)' },
    statusText: {
      fontSize: 11,
      fontWeight: '600',
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    statusTextActive: { color: '#4ade80' },
    conflictBadgeRow: { marginBottom: spacing.sm },
    conflictBadge: {
      alignSelf: 'flex-start',
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 6,
      backgroundColor: 'rgba(239,68,68,0.15)',
    },
    conflictBadgeText: {
      fontSize: 11,
      fontWeight: '700',
      color: '#ef4444',
    },
    cardActions: {
      flexDirection: 'row',
      gap: spacing.md,
      marginTop: spacing.md,
      justifyContent: 'flex-end',
    },
    iconBtn: { padding: 6 },
    classBadge: {
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 6,
    },
    classBadgeText: {
      fontSize: 10,
      fontWeight: '700',
      letterSpacing: 0.3,
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
      maxWidth: 280,
      lineHeight: 20,
    },
    modalOverlay: {
      flex: 1,
      backgroundColor: 'rgba(0,0,0,0.7)',
      justifyContent: 'center',
      alignItems: 'center',
      padding: spacing.lg,
    },
    modalContent: {
      backgroundColor: '#1a1a2e',
      borderRadius: borderRadius.xxl,
      width: '100%',
      maxWidth: 500,
      maxHeight: '85%',
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    modalHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: spacing.lg,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    modalTitle: {
      fontSize: 20,
      fontWeight: '500',
      color: colors.text.primary,
    },
    modalScroll: { padding: spacing.lg },
    formGroup: { marginBottom: spacing.md },
    formLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    helperText: {
      fontSize: 11,
      color: colors.text.muted,
      marginTop: spacing.xs,
    },
    selectorCard: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.md,
    },
    selectorText: { fontSize: 15, color: colors.text.primary },
    selectorPlaceholder: { color: colors.text.muted },
    iconRotated: { transform: [{ rotate: '180deg' }] },
    dropdown: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      marginTop: spacing.sm,
      overflow: 'hidden',
    },
    dropdownItem: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: spacing.md,
      gap: spacing.sm,
    },
    dropdownItemActive: { backgroundColor: 'rgba(255,255,255,0.1)' },
    dropdownText: { fontSize: 15, color: colors.text.secondary, flex: 1 },
    readonlyBox: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.md,
    },
    readonlyText: { fontSize: 15, color: colors.text.secondary },
    toggleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginTop: spacing.md,
      paddingVertical: spacing.sm,
    },
    toggleLabel: { fontSize: 14, color: colors.text.primary },
    modalActions: {
      flexDirection: 'row',
      gap: spacing.sm,
      padding: spacing.lg,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    cancelBtn: { flex: 1 },
    createBtn: { flex: 2 },
    conflictModal: {
      padding: spacing.xl,
      width: '100%',
      maxWidth: 420,
      alignItems: 'center',
      borderWidth: 1,
      borderColor: 'rgba(239,68,68,0.3)',
      backgroundColor: '#1a1a2e',
    },
    conflictIconRow: { marginBottom: spacing.md },
    conflictTitle: {
      fontSize: 18,
      fontWeight: '600',
      color: '#ef4444',
      textAlign: 'center',
      marginBottom: spacing.md,
    },
    conflictBody: {
      fontSize: 14,
      color: colors.text.muted,
      lineHeight: 20,
      textAlign: 'center',
      marginBottom: spacing.md,
    },
    conflictSub: {
      fontSize: 12,
      color: colors.text.muted,
      textAlign: 'center',
      marginBottom: spacing.lg,
      lineHeight: 18,
    },
    doneBtn: { width: '100%' },
  });
}
