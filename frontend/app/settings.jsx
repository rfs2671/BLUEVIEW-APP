import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Switch,
  ActivityIndicator,
  Pressable,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  User,
  Lock,
  Moon,
  Sun,
  Save,
  Shield,
  ShieldAlert,
  LogOut,
  Building2,
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  Clock,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import GlassInput from '../src/components/GlassInput';
import FloatingNav from '../src/components/FloatingNav';
import CpNav from '../src/components/CpNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useTheme } from '../src/context/ThemeContext';
import { authAPI, apiClient } from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';

const INSURANCE_LABELS = {
  general_liability: 'General Liability',
  workers_comp: "Workers' Compensation",
  disability: 'Disability Benefits',
};

const getExpirationColor = (dateStr) => {
  if (!dateStr) return '#6b7280';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '#6b7280';
  const daysLeft = Math.ceil((d - new Date()) / (1000 * 60 * 60 * 24));
  if (daysLeft < 0) return '#ef4444';
  if (daysLeft <= 60) return '#f59e0b';
  return '#22c55e';
};

const formatDate = (dateStr) => {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return typeof dateStr === 'string' ? dateStr : '--';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

export default function SettingsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, toggleTheme, colors } = useTheme();
  const toast = useToast();

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const isCp    = user?.role === 'cp';

  // --- Profile fields ---
  const [name,        setName]        = useState('');
  const [email,       setEmail]       = useState('');
  const [savingName,  setSavingName]  = useState(false);

  // --- GC Legal Name (admin only) ---
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [gcLegalName, setGcLegalName] = useState('');
  const [savingGc, setSavingGc] = useState(false);
  const [loadingGc, setLoadingGc] = useState(false);
  const [currentPw,   setCurrentPw]   = useState('');
  const [newPw,       setNewPw]       = useState('');
  const [confirmPw,   setConfirmPw]   = useState('');
  const [savingPw,    setSavingPw]    = useState(false);

  // --- Insurance / GC License (admin only) ---
  const [insData, setInsData]         = useState(null);
  const [insLoading, setInsLoading]   = useState(false);
  const [insRefreshing, setInsRefreshing] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  // Pre-fill from auth context
  useEffect(() => {
    if (user) {
      setName(user.name || user.full_name || '');
      setEmail(user.email || '');
    }
  }, [user]);

  // Fetch projects for GC name editing (admin only)
  useEffect(() => {
    if (!isAuthenticated || authLoading) return;
    if (!isAdmin) return;
    apiClient.get('/api/projects')
      .then(resp => {
        const p = Array.isArray(resp.data) ? resp.data : [];
        setProjects(p);
        const firstId = p[0]?.id || p[0]?._id || '';
        if (firstId) {
          setSelectedProjectId(firstId);
          fetchGcName(firstId);
        }
      })
      .catch((e) => {
        console.error('Failed to load projects for GC name:', e);
        setProjects([]);
      });
  }, [isAuthenticated, authLoading, isAdmin]);

  // Fetch insurance (admin only)
  useEffect(() => {
    if (!isAuthenticated || authLoading) return;
    if (!isAdmin) return;
    fetchInsurance();
  }, [isAuthenticated, authLoading, isAdmin]);

  const fetchInsurance = async () => {
    setInsLoading(true);
    try {
      const resp = await apiClient.get('/api/admin/company/insurance');
      setInsData(resp.data);
    } catch (e) {
      console.error('Failed to load insurance:', e);
    } finally {
      setInsLoading(false);
    }
  };

  const handleRefreshInsurance = async () => {
    setInsRefreshing(true);
    try {
      const resp = await apiClient.post('/api/admin/company/insurance/refresh');
      setInsData(prev => ({
        ...prev,
        gc_insurance_records: resp.data.gc_insurance_records,
        gc_license_status: resp.data.gc_license_status || prev?.gc_license_status,
        gc_license_expiration: resp.data.gc_license_expiration || prev?.gc_license_expiration,
        gc_last_verified: resp.data.gc_last_verified,
      }));
      if (resp.data.warning) toast.warning('Warning', resp.data.warning);
      else toast.success('Refreshed', 'Insurance data updated from DOB');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not refresh from DOB');
    } finally {
      setInsRefreshing(false);
    }
  };

  const fetchGcName = async (projId) => {
    if (!projId) return;
    setLoadingGc(true);
    try {
      const resp = await apiClient.get(`/api/projects/${projId}/dob-config`);
      setGcLegalName(resp.data?.gc_legal_name || '');
    } catch {
      setGcLegalName('');
    } finally {
      setLoadingGc(false);
    }
  };

  const handleSaveGcName = async () => {
    if (!selectedProjectId) return;
    if (!gcLegalName.trim()) {
      toast.error('Required', 'GC Legal Name cannot be empty');
      return;
    }
    setSavingGc(true);
    try {
      const resp = await apiClient.put(`/api/projects/${selectedProjectId}/dob-config`, {
        gc_legal_name: gcLegalName.trim(),
      });
      setGcLegalName(resp.data?.gc_legal_name || gcLegalName.trim());
      toast.success('Saved', 'GC Legal Name updated — will be used for permit renewal eligibility checks.');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not save GC name');
    } finally {
      setSavingGc(false);
    }
  };

  // -- Handlers --
  const handleSaveName = async () => {
    if (!name.trim()) {
      toast.error('Error', 'Name cannot be empty');
      return;
    }
    setSavingName(true);
    try {
      await authAPI.updateProfile({ name: name.trim() });
      toast.success('Saved', 'Your name has been updated');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not update name');
    } finally {
      setSavingName(false);
    }
  };

  const handleChangePassword = async () => {
    if (!currentPw || !newPw || !confirmPw) {
      toast.error('Error', 'Please fill in all password fields');
      return;
    }
    if (newPw !== confirmPw) {
      toast.error('Error', 'New passwords do not match');
      return;
    }
    if (newPw.length < 8) {
      toast.error('Error', 'Password must be at least 8 characters');
      return;
    }
    setSavingPw(true);
    try {
      await authAPI.changePassword({ current_password: currentPw, new_password: newPw });
      toast.success('Updated', 'Password changed successfully');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not change password');
    } finally {
      setSavingPw(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // -- Role badge label --------------------------------------------------------
  const roleLabel = {
    admin:  'Administrator',
    owner:  'Owner',
    cp:     'Competent Person',
    worker: 'Worker',
  }[user?.role] || user?.role || 'User';

  // -- Styles (theme-aware, built inline so colors update on toggle) -----------
  const s = buildStyles(colors);

  if (authLoading) {
    return (
      <AnimatedBackground>
        <View style={s.loadingCenter}>
          <ActivityIndicator size="large" color={colors.text.primary} />
        </View>
      </AnimatedBackground>
    );
  }

  // Insurance rendering data
  const gcResolved   = insData?.gc_resolved;
  const records      = insData?.gc_insurance_records || [];
  const licenseStatus = (insData?.gc_license_status || '').toUpperCase();
  const licenseActive = licenseStatus === 'ACTIVE';

  // ---- BODY CONTENT (shared between web <div> and native <ScrollView>) ----
  const bodyContent = (
    <>
      {/* -- Account info card -- */}
      <GlassCard style={s.accountCard}>
        <View style={s.avatarRow}>
          <View style={s.avatar}>
            <Text style={s.avatarLetter}>
              {(name || email || 'U')[0].toUpperCase()}
            </Text>
          </View>
          <View style={s.accountInfo}>
            <Text style={s.accountName}>{name || 'No name set'}</Text>
            <Text style={s.accountEmail}>{email}</Text>
            <View style={s.roleBadge}>
              <Shield size={11} strokeWidth={1.5} color={colors.primary} />
              <Text style={[s.roleText, { color: colors.primary }]}>{roleLabel}</Text>
            </View>
          </View>
        </View>
      </GlassCard>

      {/* ---- INSURANCE & LICENSE (admin only) ---- */}
      {isAdmin && (
        <>
          <Text style={s.sectionLabel}>INSURANCE & LICENSE</Text>

          {insLoading ? (
            <GlassCard style={s.card}>
              <View style={{ alignItems: 'center', paddingVertical: spacing.md }}>
                <ActivityIndicator size="small" color={colors.text.muted} />
              </View>
            </GlassCard>
          ) : !gcResolved ? (
            <GlassCard style={[s.card, { backgroundColor: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)' }]}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                <AlertTriangle size={18} color="#f59e0b" />
                <Text style={{ fontSize: 13, color: '#f59e0b', flex: 1, lineHeight: 18 }}>
                  Company not linked to a DOB license. Contact your administrator.
                </Text>
              </View>
            </GlassCard>
          ) : (
            <>
              {/* GC license card */}
              <GlassCard style={s.card}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
                  <IconPod size={44}>
                    <Building2 size={20} strokeWidth={1.5} color={licenseActive ? '#22c55e' : '#ef4444'} />
                  </IconPod>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: 16, fontWeight: '600', color: colors.text.primary }}>
                      GC-{insData?.gc_license_number || '--'}
                    </Text>
                    <Text style={{ fontSize: 12, fontWeight: '500', color: licenseActive ? '#22c55e' : '#ef4444', marginTop: 2 }}>
                      {licenseStatus || 'Unknown'}
                    </Text>
                  </View>
                  {licenseActive
                    ? <CheckCircle size={20} color="#22c55e" />
                    : <ShieldAlert size={20} color="#ef4444" />
                  }
                </View>
                {!!insData?.gc_business_name && (
                  <Text style={{ fontSize: 13, color: colors.text.muted, marginTop: spacing.sm }}>
                    {insData.gc_business_name}
                  </Text>
                )}
                {!!insData?.gc_license_expiration && (
                  <Text style={{ fontSize: 13, color: colors.text.muted, marginTop: 4 }}>
                    License expires: {formatDate(insData.gc_license_expiration)}
                  </Text>
                )}
              </GlassCard>

              {/* Insurance records */}
              {records.length === 0 ? (
                <GlassCard style={[s.card, { alignItems: 'center', paddingVertical: spacing.lg }]}>
                  <Shield size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={{ fontSize: 14, fontWeight: '500', color: colors.text.primary, marginTop: spacing.sm }}>
                    No Insurance Records
                  </Text>
                  <Text style={{ fontSize: 12, color: colors.text.muted, marginTop: 4, textAlign: 'center' }}>
                    Tap "Refresh from DOB" to pull insurance data.
                  </Text>
                </GlassCard>
              ) : (
                records.map((rec, idx) => {
                  const expColor = getExpirationColor(rec.expiration_date);
                  const label    = INSURANCE_LABELS[rec.insurance_type] || rec.insurance_type;
                  const isCur    = rec.is_current;
                  return (
                    <GlassCard key={`ins-${idx}`} style={s.card}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: expColor }} />
                        <Text style={{ fontSize: 14, fontWeight: '500', color: colors.text.primary, flex: 1 }}>
                          {label}
                        </Text>
                        <View style={{
                          paddingHorizontal: 8, paddingVertical: 2, borderRadius: borderRadius.full,
                          borderWidth: 1,
                          borderColor: isCur ? '#22c55e40' : '#ef444440',
                          backgroundColor: isCur ? '#22c55e10' : '#ef444410',
                        }}>
                          <Text style={{ fontSize: 10, fontWeight: '600', color: isCur ? '#22c55e' : '#ef4444', textTransform: 'uppercase' }}>
                            {isCur ? 'Current' : 'Expired'}
                          </Text>
                        </View>
                      </View>
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                        <Text style={{ fontSize: 12, color: colors.text.muted }}>Effective</Text>
                        <Text style={{ fontSize: 12, color: colors.text.primary }}>{formatDate(rec.effective_date)}</Text>
                      </View>
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
                        <Text style={{ fontSize: 12, color: colors.text.muted }}>Expiration</Text>
                        <Text style={{ fontSize: 12, color: expColor, fontWeight: '600' }}>
                          {formatDate(rec.expiration_date)}
                        </Text>
                      </View>
                    </GlassCard>
                  );
                })
              )}

              <GlassButton
                title={insRefreshing ? 'Refreshing...' : 'Refresh from DOB'}
                icon={insRefreshing
                  ? <ActivityIndicator size={16} color={colors.text.primary} />
                  : <RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />
                }
                onPress={handleRefreshInsurance}
                disabled={insRefreshing}
                style={s.saveBtn}
              />

              {!!insData?.gc_last_verified && (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, justifyContent: 'center', marginTop: spacing.sm }}>
                  <Clock size={11} color={colors.text.subtle} />
                  <Text style={{ fontSize: 11, color: colors.text.subtle }}>
                    Last verified: {formatDate(insData.gc_last_verified)}
                  </Text>
                </View>
              )}
            </>
          )}
        </>
      )}

      {/* -- Appearance -- */}
      <Text style={s.sectionLabel}>APPEARANCE</Text>
      <GlassCard style={s.card}>
        <View style={s.settingRow}>
          <View style={s.settingLeft}>
            {isDark
              ? <Moon size={20} strokeWidth={1.5} color={colors.text.secondary} />
              : <Sun  size={20} strokeWidth={1.5} color={colors.text.secondary} />
            }
            <View>
              <Text style={s.settingTitle}>{isDark ? 'Dark Mode' : 'Light Mode'}</Text>
              <Text style={s.settingSubtitle}>
                {isDark ? 'Switch to light theme' : 'Switch to dark theme'}
              </Text>
            </View>
          </View>
          <Switch
            value={isDark}
            onValueChange={toggleTheme}
            trackColor={{ false: colors.glass.border, true: colors.primary }}
            thumbColor={colors.white}
          />
        </View>
      </GlassCard>

      {/* -- Personal details -- */}
      <Text style={s.sectionLabel}>PERSONAL DETAILS</Text>
      <GlassCard style={s.card}>
        <View style={s.fieldGroup}>
          <View style={s.fieldIconRow}>
            <User size={16} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={s.fieldLabel}>Display Name</Text>
          </View>
          <GlassInput
            value={name}
            onChangeText={setName}
            placeholder="Your full name"
            autoCapitalize="words"
          />
        </View>

        <View style={[s.fieldGroup, { marginTop: spacing.sm }]}>
          <View style={s.fieldIconRow}>
            <Text style={s.fieldLabel}>Email</Text>
          </View>
          <GlassInput
            value={email}
            editable={false}
            placeholder="Email address"
            style={s.disabledInput}
          />
          <Text style={s.hintText}>Email cannot be changed here. Contact your administrator.</Text>
        </View>

        <GlassButton
          title={savingName ? 'Saving...' : 'Save Name'}
          onPress={handleSaveName}
          loading={savingName}
          icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
          style={s.saveBtn}
        />
      </GlassCard>

      {/* -- Password (admin only) -- */}
      {isAdmin && (
        <>
          <Text style={s.sectionLabel}>SECURITY</Text>
          <GlassCard style={s.card}>
            <View style={s.fieldGroup}>
              <View style={s.fieldIconRow}>
                <Lock size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.fieldLabel}>Change Password</Text>
              </View>
              <GlassInput
                value={currentPw}
                onChangeText={setCurrentPw}
                placeholder="Current password"
                secureTextEntry
              />
              <GlassInput
                value={newPw}
                onChangeText={setNewPw}
                placeholder="New password (min 8 chars)"
                secureTextEntry
                style={{ marginTop: spacing.sm }}
              />
              <GlassInput
                value={confirmPw}
                onChangeText={setConfirmPw}
                placeholder="Confirm new password"
                secureTextEntry
                style={{ marginTop: spacing.sm }}
              />
            </View>

            <GlassButton
              title={savingPw ? 'Updating...' : 'Change Password'}
              onPress={handleChangePassword}
              loading={savingPw}
              icon={<Lock size={16} strokeWidth={1.5} color={colors.text.primary} />}
              style={s.saveBtn}
            />
          </GlassCard>
        </>
      )}

      {/* ── GC Legal Name (admin only) ── */}
      {isAdmin && (
        <>
          <Text style={s.sectionLabel}>DOB PERMIT RENEWAL</Text>
          <GlassCard style={s.card}>
            <View style={s.fieldGroup}>
              <View style={s.fieldIconRow}>
                <Building2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.fieldLabel}>GC Legal Name (for DOB)</Text>
              </View>
              <Text style={s.hintText}>
                The GC legal name used to look up the license on DOB for permit renewals. Must match exactly as registered with DOB Licensing.
              </Text>

              {projects.length > 1 && (
                <View style={{ marginTop: spacing.sm }}>
                  <Text style={[s.fieldLabel, { fontSize: 11, marginBottom: 4 }]}>Select Project</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: spacing.sm }}>
                    {projects.map(p => (
                      <Pressable
                        key={p.id}
                        onPress={() => { setSelectedProjectId(p.id); fetchGcName(p.id); }}
                        style={{
                          paddingHorizontal: 12,
                          paddingVertical: 6,
                          borderRadius: 8,
                          marginRight: 8,
                          backgroundColor: selectedProjectId === p.id ? 'rgba(74,222,128,0.2)' : 'rgba(255,255,255,0.05)',
                          borderWidth: 1,
                          borderColor: selectedProjectId === p.id ? '#4ade8040' : 'rgba(255,255,255,0.1)',
                        }}
                      >
                        <Text style={{ fontSize: 12, color: selectedProjectId === p.id ? '#4ade80' : colors.text.muted }}>
                          {p.name || p.address || 'Project'}
                        </Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                </View>
              )}

              {projects.length === 0 ? (
                <Text style={[s.hintText, { color: '#f59e0b', marginTop: 8 }]}>
                  No projects found. Create a project first, then set the GC name here.
                </Text>
              ) : (
                <GlassInput
                  value={gcLegalName}
                  onChangeText={setGcLegalName}
                  placeholder="e.g. Blue Elm Construction Inc"
                  autoCapitalize="words"
                  editable={!loadingGc}
                />
              )}
            </View>

            {projects.length > 0 && (
              <GlassButton
                title={savingGc ? 'Saving...' : 'Save GC Name'}
                onPress={handleSaveGcName}
                loading={savingGc}
                icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
                style={s.saveBtn}
              />
            )}
          </GlassCard>
        </>
      )}

      {/* -- Sign out -- */}
      <Text style={s.sectionLabel}>ACCOUNT</Text>
      <GlassCard style={s.card}>
        <GlassButton
          title="Sign Out"
          onPress={handleLogout}
          icon={<LogOut size={16} strokeWidth={1.5} color="#f87171" />}
          style={s.signOutBtn}
        />
      </GlassCard>
    </>
  );

  // On web, render body inside a real <div> with forced overflow-y:auto.
  // The RN-Web ScrollView height-chain is unreliable here, so we bypass it.
  const scrollArea = Platform.OS === 'web' ? (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
        width: '100%',
      }}
    >
      <View style={s.scrollContent}>
        {bodyContent}
      </View>
    </div>
  ) : (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={s.scrollContent}
      showsVerticalScrollIndicator={true}
      nestedScrollEnabled
    >
      {bodyContent}
    </ScrollView>
  );

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>

        {/* Header */}
        <View style={s.header}>
          <Pressable onPress={() => router.back()} style={s.backBtn}>
            <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
          </Pressable>
          <Text style={s.headerTitle}>Settings</Text>
          <Pressable onPress={handleLogout} style={s.logoutBtn}>
            <LogOut size={20} strokeWidth={1.5} color={colors.text.muted} />
          </Pressable>
        </View>

        {scrollArea}

        {/* Bottom nav — CP gets CpNav, everyone else gets FloatingNav */}
        {isCp ? <CpNav /> : <FloatingNav />}

      </SafeAreaView>
    </AnimatedBackground>
  );
}

// Build styles using live theme colors so they re-render on toggle
function buildStyles(colors) {
  return StyleSheet.create({
    container:    {
      flex: 1,
      ...(Platform.OS === 'web' ? { height: '100vh', maxHeight: '100vh', overflow: 'hidden' } : {}),
    },
    loadingCenter:{ flex: 1, alignItems: 'center', justifyContent: 'center' },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    backBtn:     { padding: spacing.xs },
    logoutBtn:   { padding: spacing.xs },
    headerTitle: {
      fontSize: 17,
      fontWeight: '600',
      color: colors.text.primary,
    },
    scroll:       { flex: 1 },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 140,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },
    // Account card
    accountCard: { padding: spacing.lg, marginBottom: spacing.lg },
    avatarRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    avatar: {
      width: 56, height: 56, borderRadius: 28,
      backgroundColor: colors.primary,
      alignItems: 'center', justifyContent: 'center',
    },
    avatarLetter: { fontSize: 22, fontWeight: '600', color: '#fff' },
    accountInfo:  { flex: 1 },
    accountName:  { fontSize: 17, fontWeight: '600', color: colors.text.primary, marginBottom: 2 },
    accountEmail: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.xs },
    roleBadge: {
      flexDirection: 'row', alignItems: 'center', gap: 4,
      alignSelf: 'flex-start',
      paddingHorizontal: spacing.sm, paddingVertical: 3,
      borderRadius: borderRadius.full,
      backgroundColor: `${colors.primary}18`,
      borderWidth: 1, borderColor: `${colors.primary}35`,
    },
    roleText: { fontSize: 11, fontWeight: '600' },
    // Section label
    sectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
      marginTop: spacing.sm,
    },
    // Card
    card: { padding: spacing.lg, marginBottom: spacing.md },
    // Setting row (theme toggle)
    settingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    settingLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
    settingTitle:    { fontSize: 15, fontWeight: '500', color: colors.text.primary },
    settingSubtitle: { fontSize: 12, color: colors.text.muted, marginTop: 1 },
    // Field group
    fieldGroup:   {},
    fieldIconRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
    fieldLabel:   { fontSize: 12, fontWeight: '500', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 1 },
    disabledInput:{ opacity: 0.5 },
    hintText:     { fontSize: 11, color: colors.text.subtle, marginTop: spacing.xs },
    // Buttons
    saveBtn:    { marginTop: spacing.md },
    signOutBtn: { borderColor: 'rgba(248,113,113,0.3)' },
  });
}
