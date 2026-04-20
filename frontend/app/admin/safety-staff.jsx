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
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Plus,
  Trash2,
  X,
  AlertTriangle,
  Pencil,
  ShieldCheck,
  Shield,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI, safetyStaffAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';

const CLASS_BADGES = {
  major_b: { label: 'MAJOR B', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
  major_a: { label: 'MAJOR A', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
};

const ROLE_HELPER = {
  ssc: 'Required for Major A projects (10+ stories or 125+ ft). S-56 license.',
  ssm: 'Required for Major B projects (15+ stories, 200+ ft, or 100K+ sqft). S-57 license.',
};

function daysUntil(dateStr) {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return null;
    return Math.floor((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
}

export default function SafetyStaffScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [staffLoading, setStaffLoading] = useState(false);
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [staff, setStaff] = useState([]);

  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingStaff, setEditingStaff] = useState(null);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    role: 'ssc',
    name: '',
    license_number: '',
    license_expiration: '',
    phone: '',
    email: '',
  });

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
    if (isAuthenticated && isAdmin) fetchProjects();
  }, [isAuthenticated, isAdmin]);

  useEffect(() => {
    if (selectedProjectId) fetchStaff(selectedProjectId);
  }, [selectedProjectId]);

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const projs = await projectsAPI.getAll().catch(() => []);
      const arr = Array.isArray(projs) ? projs : (projs?.items || []);
      const major = arr.filter(
        (p) => p.project_class === 'major_a' || p.project_class === 'major_b'
      );
      setProjects(major);
      if (major.length && !selectedProjectId) {
        setSelectedProjectId(major[0]._id || major[0].id);
      }
    } catch (e) {
      console.error('Load projects failed:', e);
      toast.error('Load Error', 'Could not load projects');
    } finally {
      setLoading(false);
    }
  };

  const fetchStaff = async (projectId) => {
    setStaffLoading(true);
    try {
      const data = await safetyStaffAPI.getByProject(projectId).catch(() => []);
      setStaff(Array.isArray(data) ? data : (data?.items || []));
    } catch (e) {
      console.error('Load staff failed:', e);
      setStaff([]);
    } finally {
      setStaffLoading(false);
    }
  };

  const selectedProject = projects.find(
    (p) => (p._id || p.id) === selectedProjectId
  );

  const resetForm = () => {
    setForm({
      role: 'ssc',
      name: '',
      license_number: '',
      license_expiration: '',
      phone: '',
      email: '',
    });
  };

  const openAdd = () => {
    resetForm();
    setShowAddModal(true);
  };

  const openEdit = (st) => {
    setEditingStaff(st);
    setForm({
      role: st.role || 'ssc',
      name: st.name || '',
      license_number: st.license_number || '',
      license_expiration: st.license_expiration || '',
      phone: st.phone || '',
      email: st.email || '',
    });
    setShowEditModal(true);
  };

  const handleAdd = async () => {
    if (!selectedProjectId) {
      toast.warning('No Project', 'Select a project first');
      return;
    }
    if (!form.name.trim() || !form.license_number.trim()) {
      toast.warning('Missing Fields', 'Name and license number are required');
      return;
    }
    setSaving(true);
    try {
      await safetyStaffAPI.create(selectedProjectId, {
        project_id: selectedProjectId,
        role: form.role,
        name: form.name.trim(),
        license_number: form.license_number.trim(),
        license_expiration: form.license_expiration.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
      });
      toast.success('Registered', `${form.role.toUpperCase()} registered to project`);
      setShowAddModal(false);
      resetForm();
      fetchStaff(selectedProjectId);
    } catch (e) {
      console.error('Add safety staff failed:', e);
      toast.error('Error', e.response?.data?.detail || 'Could not register staff');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingStaff) return;
    setSaving(true);
    try {
      await safetyStaffAPI.update(editingStaff.id || editingStaff._id, {
        name: form.name.trim(),
        license_number: form.license_number.trim(),
        license_expiration: form.license_expiration.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
      });
      toast.success('Saved', 'Safety staff updated');
      setShowEditModal(false);
      setEditingStaff(null);
      fetchStaff(selectedProjectId);
    } catch (e) {
      console.error('Edit safety staff failed:', e);
      toast.error('Error', e.response?.data?.detail || 'Could not update');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (st) => {
    const confirmed = Platform.OS === 'web'
      ? window.confirm('Remove this safety staff registration from the project?')
      : await new Promise((resolve) => {
          const { Alert } = require('react-native');
          Alert.alert(
            'Remove Safety Staff',
            'Remove this safety staff registration from the project?',
            [
              { text: 'Cancel', onPress: () => resolve(false), style: 'cancel' },
              { text: 'Remove', onPress: () => resolve(true), style: 'destructive' },
            ]
          );
        });
    if (!confirmed) return;
    try {
      await safetyStaffAPI.delete(st.id || st._id);
      toast.success('Removed', 'Safety staff removed');
      fetchStaff(selectedProjectId);
    } catch (e) {
      console.error('Delete safety staff failed:', e);
      toast.error('Error', 'Could not remove');
    }
  };

  const hasSSC = staff.some((s) => s.role === 'ssc');
  const hasSSM = staff.some((s) => s.role === 'ssm');
  const needsSSC = selectedProject?.project_class === 'major_a' && !hasSSC;
  const needsSSM = selectedProject?.project_class === 'major_b' && !hasSSM;

  const renderRoleBadge = (role) => (
    <View
      style={[
        s.roleBadge,
        role === 'ssc' ? s.roleBadgeSSC : s.roleBadgeSSM,
      ]}
    >
      <Text
        style={[
          s.roleBadgeText,
          role === 'ssc' ? s.roleBadgeTextSSC : s.roleBadgeTextSSM,
        ]}
      >
        {role.toUpperCase()}
      </Text>
    </View>
  );

  const renderClassBadge = (cls) => {
    const spec = CLASS_BADGES[cls];
    if (!spec) return null;
    return (
      <View style={[s.classBadge, { backgroundColor: spec.bg }]}>
        <Text style={[s.classBadgeText, { color: spec.color }]}>
          {spec.label}
        </Text>
      </View>
    );
  };

  const renderExpiration = (dateStr) => {
    if (!dateStr) return null;
    const d = daysUntil(dateStr);
    if (d === null) return null;
    let color = '#4ade80';
    let prefix = '';
    if (d < 30) {
      color = '#ef4444';
      prefix = '🚨 ';
    } else if (d < 90) {
      color = '#f59e0b';
      prefix = '⚠ ';
    }
    return (
      <Text style={[s.expirationText, { color }]}>
        {prefix}Expires {dateStr}
      </Text>
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
            <Text style={s.titleText}>Safety Staff</Text>
            <Text style={s.subtitle}>
              Site Safety Coordinators (SSC) and Managers (SSM) for Major A/B projects
            </Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={60} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} />
            </>
          ) : projects.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <IconPod size={64}>
                <ShieldCheck size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={s.emptyTitle}>No Major A/B projects found</Text>
              <Text style={s.emptyText}>
                Safety staff is only required for Major A and Major B classifications
              </Text>
            </GlassCard>
          ) : (
            <>
              {/* Project pill selector */}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={s.pillRow}
                style={s.pillScroll}
              >
                {projects.map((p) => {
                  const pid = p._id || p.id;
                  const isSelected = pid === selectedProjectId;
                  const addr = (p.address || p.location || p.name || 'Project').slice(0, 20);
                  return (
                    <Pressable
                      key={pid}
                      onPress={() => setSelectedProjectId(pid)}
                      style={[
                        s.pill,
                        isSelected ? s.pillActive : s.pillInactive,
                      ]}
                    >
                      <Text
                        style={[
                          s.pillText,
                          isSelected ? s.pillTextActive : s.pillTextInactive,
                        ]}
                      >
                        {addr}
                      </Text>
                      {renderClassBadge(p.project_class)}
                    </Pressable>
                  );
                })}
              </ScrollView>

              {/* Compliance banners */}
              {needsSSC && (
                <View style={s.amberBanner}>
                  <AlertTriangle size={18} strokeWidth={1.5} color="#f59e0b" />
                  <Text style={s.amberBannerText}>
                    No SSC registered — required by NYC BC §3310.4 for Major A projects
                  </Text>
                </View>
              )}
              {needsSSM && (
                <View style={s.redBanner}>
                  <AlertTriangle size={18} strokeWidth={1.5} color="#ef4444" />
                  <Text style={s.redBannerText}>
                    No SSM registered — required by NYC BC §3310.5 for Major B projects
                  </Text>
                </View>
              )}

              <GlassButton
                title="Add Staff Member"
                icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={openAdd}
                style={s.addButton}
              />

              {staffLoading ? (
                <>
                  <GlassSkeleton width="100%" height={110} borderRadiusValue={borderRadius.xl} style={s.mb12} />
                  <GlassSkeleton width="100%" height={110} borderRadiusValue={borderRadius.xl} />
                </>
              ) : staff.length > 0 ? (
                <View style={s.list}>
                  {staff.map((st) => {
                    const licPrefix = st.role === 'ssc' ? 'S-56 · ' : 'S-57 · ';
                    return (
                      <GlassCard key={st.id || st._id} style={s.card}>
                        <View style={s.cardRow}>
                          {renderRoleBadge(st.role || 'ssc')}
                          <View style={s.cardInfo}>
                            <Text style={s.name}>{st.name}</Text>
                            <Text style={s.licenseText}>
                              {licPrefix}
                              {st.license_number || '—'}
                            </Text>
                          </View>
                        </View>

                        {(st.phone || st.email) && (
                          <View style={s.metaRow}>
                            {st.phone ? (
                              <Text style={s.metaText}>{st.phone}</Text>
                            ) : null}
                            {st.email ? (
                              <Text style={s.metaText} numberOfLines={1}>
                                {st.email}
                              </Text>
                            ) : null}
                          </View>
                        )}
                        {renderExpiration(st.license_expiration)}

                        <View style={s.cardActions}>
                          <Pressable
                            onPress={() => openEdit(st)}
                            hitSlop={10}
                            style={s.iconBtn}
                          >
                            <Pencil size={16} strokeWidth={1.5} color={colors.text.muted} />
                          </Pressable>
                          <Pressable
                            onPress={() => handleDelete(st)}
                            hitSlop={10}
                            style={s.iconBtn}
                          >
                            <Trash2 size={16} strokeWidth={1.5} color="#ef4444" />
                          </Pressable>
                        </View>
                      </GlassCard>
                    );
                  })}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <IconPod size={64}>
                    <Shield size={28} strokeWidth={1.5} color={colors.text.muted} />
                  </IconPod>
                  <Text style={s.emptyTitle}>No Safety Staff</Text>
                  <Text style={s.emptyText}>
                    Add an SSC or SSM registration for this project.
                  </Text>
                </GlassCard>
              )}
            </>
          )}
        </ScrollView>

        <FloatingNav />

        {/* Add Modal */}
        <Modal
          visible={showAddModal}
          animationType="slide"
          transparent
          onRequestClose={() => setShowAddModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={s.modalOverlay}
          >
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Add Safety Staff</Text>
                <Pressable onPress={() => setShowAddModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>
              <ScrollView style={s.modalScroll}>
                {/* Role selector */}
                <View style={s.formGroup}>
                  <Text style={s.formLabel}>ROLE</Text>
                  <View style={s.roleSelectorRow}>
                    <Pressable
                      onPress={() => setForm({ ...form, role: 'ssc' })}
                      style={[
                        s.roleOption,
                        form.role === 'ssc' && s.roleOptionActive,
                      ]}
                    >
                      <Text
                        style={[
                          s.roleOptionText,
                          form.role === 'ssc' && s.roleOptionTextActive,
                        ]}
                      >
                        SSC — Site Safety Coordinator (S-56)
                      </Text>
                    </Pressable>
                    <Pressable
                      onPress={() => setForm({ ...form, role: 'ssm' })}
                      style={[
                        s.roleOption,
                        form.role === 'ssm' && s.roleOptionActive,
                      ]}
                    >
                      <Text
                        style={[
                          s.roleOptionText,
                          form.role === 'ssm' && s.roleOptionTextActive,
                        ]}
                      >
                        SSM — Site Safety Manager (S-57)
                      </Text>
                    </Pressable>
                  </View>
                  <Text style={s.helperText}>{ROLE_HELPER[form.role]}</Text>
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>NAME</Text>
                  <GlassInput
                    value={form.name}
                    onChangeText={(v) => setForm({ ...form, name: v })}
                    placeholder="Full name"
                    autoCapitalize="words"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE NUMBER</Text>
                  <GlassInput
                    value={form.license_number}
                    onChangeText={(v) => setForm({ ...form, license_number: v })}
                    placeholder={form.role === 'ssc' ? 'S-56-XXXXX' : 'S-57-XXXXX'}
                    autoCapitalize="characters"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE EXPIRATION</Text>
                  <GlassInput
                    value={form.license_expiration}
                    onChangeText={(v) => setForm({ ...form, license_expiration: v })}
                    placeholder="YYYY-MM-DD"
                    autoCapitalize="none"
                  />
                  <Text style={s.helperText}>Used for compliance expiration alerts</Text>
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

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>EMAIL</Text>
                  <GlassInput
                    value={form.email}
                    onChangeText={(v) => setForm({ ...form, email: v })}
                    placeholder="Email (optional)"
                    keyboardType="email-address"
                    autoCapitalize="none"
                  />
                </View>
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowAddModal(false)}
                  style={s.cancelBtn}
                />
                <GlassButton
                  title={saving ? 'Adding...' : 'Add'}
                  onPress={handleAdd}
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
                <Text style={s.modalTitle}>Edit Safety Staff</Text>
                <Pressable onPress={() => setShowEditModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>
              <ScrollView style={s.modalScroll}>
                <View style={s.formGroup}>
                  <Text style={s.formLabel}>ROLE</Text>
                  <View style={s.readonlyBox}>
                    {renderRoleBadge(form.role || 'ssc')}
                    <Text style={[s.readonlyText, { marginLeft: spacing.sm }]}>
                      {form.role === 'ssc'
                        ? 'Site Safety Coordinator (S-56)'
                        : 'Site Safety Manager (S-57)'}
                    </Text>
                  </View>
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>NAME</Text>
                  <GlassInput
                    value={form.name}
                    onChangeText={(v) => setForm({ ...form, name: v })}
                    placeholder="Full name"
                    autoCapitalize="words"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE NUMBER</Text>
                  <GlassInput
                    value={form.license_number}
                    onChangeText={(v) => setForm({ ...form, license_number: v })}
                    placeholder={form.role === 'ssc' ? 'S-56-XXXXX' : 'S-57-XXXXX'}
                    autoCapitalize="characters"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>LICENSE EXPIRATION</Text>
                  <GlassInput
                    value={form.license_expiration}
                    onChangeText={(v) => setForm({ ...form, license_expiration: v })}
                    placeholder="YYYY-MM-DD"
                    autoCapitalize="none"
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

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>EMAIL</Text>
                  <GlassInput
                    value={form.email}
                    onChangeText={(v) => setForm({ ...form, email: v })}
                    placeholder="Email (optional)"
                    keyboardType="email-address"
                    autoCapitalize="none"
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
      borderBottomColor: 'rgba(255,255,255,0.08)',
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
    pillScroll: { marginBottom: spacing.md },
    pillRow: { gap: spacing.sm, paddingRight: spacing.md },
    pill: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      borderRadius: borderRadius.full,
      borderWidth: 1,
    },
    pillActive: {
      backgroundColor: colors.primary || '#3b82f6',
      borderColor: colors.primary || '#3b82f6',
    },
    pillInactive: {
      backgroundColor: colors.glass.background,
      borderColor: colors.glass.border,
    },
    pillText: { fontSize: 13, fontWeight: '500' },
    pillTextActive: { color: '#fff' },
    pillTextInactive: { color: colors.text.muted },
    amberBanner: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      backgroundColor: 'rgba(245,158,11,0.1)',
      borderWidth: 1,
      borderColor: 'rgba(245,158,11,0.3)',
      borderRadius: 12,
      padding: 16,
      marginBottom: 16,
    },
    amberBannerText: { flex: 1, fontSize: 13, color: '#f59e0b', lineHeight: 18 },
    redBanner: {
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
    redBannerText: { flex: 1, fontSize: 13, color: '#ef4444', lineHeight: 18 },
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
      marginTop: 2,
    },
    metaRow: {
      flexDirection: 'row',
      gap: spacing.md,
      marginTop: spacing.xs,
      flexWrap: 'wrap',
    },
    metaText: { fontSize: 12, color: colors.text.muted },
    expirationText: { fontSize: 13, marginTop: spacing.xs, fontWeight: '500' },
    cardActions: {
      flexDirection: 'row',
      gap: spacing.md,
      marginTop: spacing.md,
      justifyContent: 'flex-end',
    },
    iconBtn: { padding: 6 },
    roleBadge: {
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: 6,
      alignSelf: 'center',
    },
    roleBadgeSSC: { backgroundColor: 'rgba(245,158,11,0.15)' },
    roleBadgeSSM: { backgroundColor: 'rgba(239,68,68,0.15)' },
    roleBadgeText: {
      fontSize: 11,
      fontWeight: '700',
      letterSpacing: 0.4,
    },
    roleBadgeTextSSC: { color: '#f59e0b' },
    roleBadgeTextSSM: { color: '#ef4444' },
    classBadge: {
      paddingHorizontal: 6,
      paddingVertical: 2,
      borderRadius: 4,
    },
    classBadgeText: {
      fontSize: 9,
      fontWeight: '700',
      letterSpacing: 0.3,
    },
    emptyCard: { alignItems: 'center', paddingVertical: spacing.xxl },
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
      maxWidth: 300,
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
    modalTitle: { fontSize: 20, fontWeight: '500', color: colors.text.primary },
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
    roleSelectorRow: { gap: spacing.sm },
    roleOption: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderRadius: borderRadius.lg,
      padding: spacing.md,
    },
    roleOptionActive: {
      backgroundColor: 'rgba(59,130,246,0.15)',
      borderColor: colors.primary || '#3b82f6',
    },
    roleOptionText: { fontSize: 14, color: colors.text.muted },
    roleOptionTextActive: {
      color: colors.text.primary,
      fontWeight: '500',
    },
    readonlyBox: {
      flexDirection: 'row',
      alignItems: 'center',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.md,
    },
    readonlyText: { fontSize: 15, color: colors.text.secondary },
    modalActions: {
      flexDirection: 'row',
      gap: spacing.sm,
      padding: spacing.lg,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    cancelBtn: { flex: 1 },
    createBtn: { flex: 2 },
  });
}
