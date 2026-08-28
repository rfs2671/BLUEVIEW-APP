import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Switch,
  ActivityIndicator,
  Pressable,
  Modal,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  User,
  Phone,
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
  Edit3,
  CalendarDays,
  Bell,
  ChevronRight,
  Trash2,
  ShieldCheck,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import * as Clipboard from 'expo-clipboard';
import Constants from 'expo-constants';
import * as Updates from 'expo-updates';
import { bundleAgeLabel } from '../src/utils/bundleAge';
import { GlassCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import GlassInput from '../src/components/GlassInput';
import FloatingNav from '../src/components/FloatingNav';
import CpNav from '../src/components/CpNav';
import { CP_NAV_CLEARANCE } from '../src/components/CpNav';
import OfflineNotice from '../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../src/utils/offlineState';
import { useToast, ToastHost } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useTheme } from '../src/context/ThemeContext';
import { retentionSentence, drainWarning, accessRemovedSentence } from '../src/utils/retentionCopy';
import apiClient, { authAPI, versionAPI } from '../src/utils/api';
import { spacing, borderRadius, typography, touchTarget } from '../src/styles/theme';
import { semantic, chrome, withAlpha } from '../src/styles/semanticColors';

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
  if (daysLeft < 0) return semantic.critical;
  if (daysLeft <= 60) return semantic.attention;
  return semantic.verified;
};

const formatDate = (dateStr) => {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return typeof dateStr === 'string' ? dateStr : '--';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

export default function SettingsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode } = useAuth();
  const { isDark, toggleTheme, colors } = useTheme();
  const toast = useToast();

  // ── BUILD IDENTITY ──────────────────────────────────────────────────
  // `jsCommit` is a slot EAS fills at build time (app.json extra.jsCommit).
  // Until that is wired it is null, and the OTA update id is what identifies
  // the bundle — a UUID, not a SHA, so it cannot be COMPARED to the backend
  // commit. The card says which of the two it is showing rather than implying
  // a comparison it cannot make.
  // TYPE-GUARDED, and this is not defensive padding — it is a fix.
  // app.json carried `"jsCommit": null` and the Expo config pipeline handed it
  // back as `{}`. An empty object is TRUTHY, so it flowed straight into the
  // rendered value and crashed /settings with React error #31, "objects are
  // not valid as a React child". Caught by the mount smoke, not by any unit
  // test, because only a real render exercises it.
  //
  // Only a non-empty string is a commit. Anything else is "not injected".
  const _rawCommit = Constants.expoConfig?.extra?.jsCommit;
  const jsCommit = (typeof _rawCommit === 'string' && _rawCommit.trim())
    ? _rawCommit.trim()
    : null;
  const appVersion = Constants.expoConfig?.version || 'unknown';
  const jsBundle = jsCommit
    || (Updates.updateId ? `${Updates.updateId.slice(0, 8)} (OTA id)` : 'embedded in build');
  // AND HOW OLD THAT IS, in words that need no context. A timestamp asks the
  // reader to do the arithmetic and to know what current looks like; "34 days
  // ago" is the whole diagnosis. Absent for an embedded bundle, deliberately —
  // see src/utils/bundleAge.js.
  const _jsAge = bundleAgeLabel(Updates.createdAt);
  const jsBuiltAt = Updates.createdAt
    ? `${new Date(Updates.createdAt).toLocaleString()}${_jsAge ? ` — ${_jsAge}` : ''}`
    : 'shipped with the binary';

  // ── ACCOUNT DELETION (Apple 5.1.1(v)) ───────────────────────────────
  // Seeded from the user doc so a request survives a reinstall: it lives on
  // the server, not in component state.
  const [deletionRequestedAt, setDeletionRequestedAt] = useState(
    user?.deletion_requested_at || null,
  );
  const [deletionConfirmOpen, setDeletionConfirmOpen] = useState(false);
  const [deletionBusy, setDeletionBusy] = useState(false);

  const [backendCommit, setBackendCommit] = useState(null);
  const [backendLoading, setBackendLoading] = useState(true);
  const [buildCopied, setBuildCopied] = useState(false);

  const handleRequestDeletion = async () => {
    setDeletionBusy(true);
    try {
      const r = await authAPI.requestAccountDeletion();
      setDeletionRequestedAt(r?.deletion_requested_at || new Date().toISOString());
      setDeletionConfirmOpen(false);
      // NOT a toast. He has just asked for his account to be removed and needs
      // to see that it was received — a message gone in four seconds is what
      // makes a request feel like it went nowhere.
    } catch (e) {
      toast.error(
        'Not sent',
        isOfflineError(e)
          ? 'You are offline. Nothing was requested — try again on a connection.'
          : (e?.response?.data?.detail || 'Could not send the request.'),
      );
    } finally {
      setDeletionBusy(false);
    }
  };

  const handleWithdrawDeletion = async () => {
    setDeletionBusy(true);
    try {
      await authAPI.withdrawAccountDeletion();
      setDeletionRequestedAt(null);
      toast.success('Withdrawn', 'Your account will not be removed.');
    } catch (e) {
      toast.error('Not withdrawn', 'Could not withdraw the request.');
    } finally {
      setDeletionBusy(false);
    }
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const v = await versionAPI.get();
        if (alive) setBackendCommit(v?.short || v?.commit || null);
      } catch (_e) {
        if (alive) setBackendCommit(null);   // rendered as "unreachable"
      } finally {
        if (alive) setBackendLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Only a REAL comparison is offered. With no injected commit the two
  // identities are different kinds of thing, and claiming a match either way
  // would be the same false confidence this card exists to remove.
  const buildMatches = Boolean(jsCommit && backendCommit)
    && jsCommit.slice(0, 7) === String(backendCommit).slice(0, 7);
  const buildVerdict = !backendCommit
    ? null
    : jsCommit
      ? (buildMatches ? 'App and backend are on the same commit.'
        : 'MISMATCH — the app and the backend are on different commits.')
      : 'Bundle commit not injected at build time; compare the times above.';

  const copyBuild = async () => {
    await Clipboard.setStringAsync(
      `app ${appVersion} | js ${jsBundle} | built ${jsBuiltAt} | backend ${backendCommit || 'unreachable'}`,
    );
    setBuildCopied(true);
    setTimeout(() => setBuildCopied(false), 2000);
  };

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const isCp    = user?.role === 'cp';
  const insets  = useSafeAreaInsets();

  // Profile
  const [name, setName]             = useState('');
  const [email, setEmail]           = useState('');
  const [savingName, setSavingName] = useState(false);
  const [phone, setPhone]           = useState('');
  const [savingPhone, setSavingPhone] = useState(false);

  // Password
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw]         = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [savingPw, setSavingPw]   = useState(false);

  // GC Legal Name (admin only)
  const [projects, setProjects]                   = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [gcLegalName, setGcLegalName]             = useState('');
  const [savingGc, setSavingGc]                   = useState(false);
  const [loadingGc, setLoadingGc]                 = useState(false);

  // Insurance / GC License (admin only)
  const [insData, setInsData]             = useState(null);
  const [insLoading, setInsLoading]       = useState(false);
  const [insRefreshing, setInsRefreshing] = useState(false);

  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error' per read. A failed insurance
  // read left insData null, which rendered "Company not linked to a DOB
  // license"; a failed projects read rendered "No projects found". Both are
  // false statements about the company when the server never answered.
  const [insState, setInsState]           = useState('ok');
  const [projectsState, setProjectsState] = useState('ok');
  const [gcNameState, setGcNameState]     = useState('ok');

  // Manual insurance entry form
  const [showInsuranceForm, setShowInsuranceForm] = useState(false);
  const [insGL, setInsGL] = useState('');
  const [insWC, setInsWC] = useState('');
  const [insDB, setInsDB] = useState('');
  const [savingInsurance, setSavingInsurance] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (user) {
      setName(user.name || user.full_name || '');
      setEmail(user.email || '');
      setPhone(user.phone || '');
    }
  }, [user]);

  // Load projects (admin only)
  useEffect(() => {
    if (!isAuthenticated || authLoading || !isAdmin) return;
    (async () => {
      const res = await settleFetch(() => apiClient.get('/api/projects'));
      setProjectsState(res.status);
      if (res.status !== 'ok') {
        // NOT setProjects([]) — that produced the same "No projects found"
        // warning as a company that genuinely has none.
        console.error('Failed to load projects for GC name:', res.error);
        return;
      }
      // Backend `GET /api/projects` returns the paginated_query
      // shape `{items, total, limit, skip, has_more}`. Older callers
      // received a bare array; this loader was on the array path
      // and silently fell through to [] when the response shape
      // changed, producing the "No projects found" warning even
      // when projects existed. Mirror the defensive read in
      // src/utils/api.js (`projectsAPI.getAll`) so both shapes work.
      const data = res.data?.data;
      const p = Array.isArray(data) ? data : (data?.items || []);
      setProjects(p);
      const firstId = p[0]?.id || p[0]?._id || '';
      if (firstId) {
        setSelectedProjectId(firstId);
        fetchGcName(firstId);
      }
    })();
  }, [isAuthenticated, authLoading, isAdmin]);

  // Load insurance (admin only)
  useEffect(() => {
    if (!isAuthenticated || authLoading || !isAdmin) return;
    fetchInsurance();
  }, [isAuthenticated, authLoading, isAdmin]);

  const fetchInsurance = async () => {
    setInsLoading(true);
    const res = await settleFetch(() => apiClient.get('/api/admin/company/insurance'));
    setInsState(res.status);
    if (res.status === 'ok') {
      setInsData(res.data?.data);
    } else {
      console.error('Failed to load insurance:', res.error);
    }
    setInsLoading(false);
  };

  const handleRefreshInsurance = async () => {
    setInsRefreshing(true);
    try {
      const resp = await apiClient.post('/api/admin/company/insurance/refresh');
      setInsData(prev => ({
        ...prev,
        // Do NOT overwrite manually-entered records with the refresh response.
        // Backend preserves them; we mirror that behavior here.
        gc_insurance_records: resp.data.gc_insurance_records || prev?.gc_insurance_records || [],
        gc_license_status: resp.data.gc_license_status || prev?.gc_license_status,
        gc_license_expiration: resp.data.gc_license_expiration || prev?.gc_license_expiration,
        gc_last_verified: resp.data.gc_last_verified,
      }));
      if (resp.data.warning) toast.info('License refreshed', resp.data.warning);
      else toast.success('Refreshed', 'License data updated');
    } catch (e) {
      // The refresh hits DOB through our backend — offline nothing was checked.
      if (isOfflineError(e)) {
        toast.error('Offline', 'Refreshing the license needs a connection. Nothing was re-verified.');
      } else {
        toast.error('Error', e?.response?.data?.detail || 'Could not refresh license');
      }
    } finally {
      setInsRefreshing(false);
    }
  };

  const openInsuranceForm = () => {
    // Pre-fill from existing records if any
    const recs = insData?.gc_insurance_records || [];
    const find = (type) => (recs.find(r => r.insurance_type === type)?.expiration_date) || '';
    setInsGL(find('general_liability'));
    setInsWC(find('workers_comp'));
    setInsDB(find('disability'));
    setShowInsuranceForm(true);
  };

  const handleSaveInsurance = async () => {
    if (!insGL.trim() || !insWC.trim() || !insDB.trim()) {
      toast.error('Missing dates', 'All three insurance expiry dates are required.');
      return;
    }
    setSavingInsurance(true);
    try {
      const resp = await apiClient.put('/api/admin/company/insurance/manual', {
        general_liability_expiry: insGL.trim(),
        workers_comp_expiry:      insWC.trim(),
        disability_expiry:        insDB.trim(),
      });
      setInsData(resp.data);
      setShowInsuranceForm(false);
      toast.success('Saved', 'Insurance expiry dates updated.');
    } catch (e) {
      // "Invalid dates" is a server validation verdict — do not imply it when
      // the request never arrived.
      if (isOfflineError(e)) {
        toast.error('Offline', 'Saving insurance dates needs a connection. Nothing was saved.');
      } else {
        toast.error('Invalid dates', e?.response?.data?.detail || 'Could not save insurance.');
      }
    } finally {
      setSavingInsurance(false);
    }
  };

  const fetchGcName = async (projId) => {
    if (!projId) return;
    setLoadingGc(true);
    const res = await settleFetch(() => apiClient.get(`/api/projects/${projId}/dob-config`));
    setGcNameState(res.status);
    if (res.status === 'ok') {
      setGcLegalName(res.data?.data?.gc_legal_name || '');
    } else {
      // A blank field reads as "no GC name is set" — flag the failure instead
      // of letting the admin overwrite a value they never saw.
      setGcLegalName('');
    }
    setLoadingGc(false);
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
      toast.success('Saved', 'GC Legal Name updated — used for permit renewal eligibility checks.');
    } catch (e) {
      if (isOfflineError(e)) {
        toast.error('Offline', 'Saving the GC legal name needs a connection. Nothing was saved.');
      } else {
        toast.error('Error', e?.response?.data?.detail || 'Could not save GC name');
      }
    } finally {
      setSavingGc(false);
    }
  };

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
      // Profile edits are server-side only — nothing is queued offline.
      if (isOfflineError(e)) {
        toast.error('Offline', 'Saving your name needs a connection. Nothing was saved.');
      } else {
        toast.error('Error', e?.response?.data?.detail || 'Could not update name');
      }
    } finally {
      setSavingName(false);
    }
  };

  const handleSavePhone = async () => {
    const trimmed = (phone || '').trim();
    // Allow empty (explicit removal) OR 10-15 digits after stripping non-digit chars
    if (trimmed !== '') {
      const digits = trimmed.replace(/\D/g, '');
      if (digits.length < 10 || digits.length > 15) {
        toast.error('Invalid phone', 'Phone number must have 10-15 digits.');
        return;
      }
    }
    setSavingPhone(true);
    try {
      await authAPI.updateProfile({ phone: trimmed });
      toast.success(
        'Saved',
        trimmed ? 'Phone number updated' : 'Phone number removed'
      );
    } catch (e) {
      if (isOfflineError(e)) {
        toast.error('Offline', 'Saving your phone number needs a connection. Nothing was saved.');
        return;
      }
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      if (status === 409) {
        toast.error(
          'Phone already in use',
          detail || 'Another user in your company has this number.'
        );
      } else {
        toast.error('Error', detail || 'Could not update phone');
      }
    } finally {
      setSavingPhone(false);
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
    // Password min-length check removed (temporary regression — see backend).
    setSavingPw(true);
    try {
      await authAPI.changePassword({ current_password: currentPw, new_password: newPw });
      toast.success('Updated', 'Password changed successfully');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
    } catch (e) {
      // The current password is verified server-side — offline we did not even
      // get to check it, so this is not a wrong-password result.
      if (isOfflineError(e)) {
        toast.error('Offline', 'Changing your password needs a connection. Your password is unchanged.');
      } else {
        toast.error('Error', e?.response?.data?.detail || 'Could not change password');
      }
    } finally {
      setSavingPw(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

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

  // Insurance render helpers
  const gcResolved    = insData?.gc_resolved;
  const records       = insData?.gc_insurance_records || [];
  const licenseStatus = (insData?.gc_license_status || '').toUpperCase();
  const licenseActive = licenseStatus === 'ACTIVE';

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>

        {/* Header — no logout here; sign out lives at the bottom of the page */}
        <View style={s.header}>
          <Pressable onPress={() => router.back()} style={s.backBtn}>
            <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
          </Pressable>
          <Text style={s.headerTitle}>Settings</Text>
          <View style={s.headerSpacer} />
        </View>

        <ScrollView
          style={s.scroll}
          // ONE NUMBER FOR BOTH NAVS. This screen renders CpNav or
          // FloatingNav by role, and the two pills measure the same 58pt at
          // the same 24pt offset — FloatingNav sizes to content and scrolls
          // horizontally, CpNav shares its width and ellipsizes, and both land
          // on the same height. So the CP_NAV_ name is about where the
          // constant is defined, not about which nav is on screen.
          contentContainerStyle={[
            s.scrollContent,
            { paddingBottom: insets.bottom + CP_NAV_CLEARANCE },
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* ── APPEARANCE ─────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>APPEARANCE</Text>
          <GlassCard style={s.card}>
            <View style={s.settingRow}>
              <View style={s.settingLeft}>
                {isDark
                  ? <Moon size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  : <Sun  size={20} strokeWidth={1.5} color={colors.text.secondary} />}
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

          {/* ── NOTIFICATIONS ─────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>NOTIFICATIONS</Text>
          <Pressable
            onPress={() => router.push('/settings/notifications')}
            style={({ pressed }) => [
              { opacity: pressed ? 0.7 : 1 },
            ]}
          >
            <GlassCard style={s.card}>
              <View style={s.settingRow}>
                <View style={s.settingLeft}>
                  <Bell size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  <View>
                    <Text style={s.settingTitle}>Notification Preferences</Text>
                    <Text style={s.settingSubtitle}>
                      Tune which DOB compliance signals reach you and how
                    </Text>
                  </View>
                </View>
                <ChevronRight size={20} strokeWidth={1.5} color={colors.text.muted} />
              </View>
            </GlassCard>
          </Pressable>

          {/* ── PERSONAL DETAILS ───────────────────────────────────────── */}
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

            <GlassButton
              title={savingName ? 'Saving...' : 'Save Name'}
              onPress={handleSaveName}
              loading={savingName}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              style={s.saveBtn}
            />

            <View style={[s.fieldGroup, { marginTop: spacing.md }]}>
              <View style={s.fieldIconRow}>
                <Phone size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.fieldLabel}>Phone Number</Text>
              </View>
              <GlassInput
                value={phone}
                onChangeText={setPhone}
                placeholder="e.g. 917-555-0101"
                keyboardType="phone-pad"
                autoCapitalize="none"
              />
              <Text style={s.hintText}>
                Required for WhatsApp integration. Used to identify you when you message the Levelog Assistant.
              </Text>
            </View>

            <GlassButton
              title={savingPhone ? 'Saving...' : 'Save Phone'}
              onPress={handleSavePhone}
              loading={savingPhone}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              style={s.saveBtn}
            />

            <View style={[s.fieldGroup, { marginTop: spacing.md }]}>
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
          </GlassCard>

          {/* ── INSURANCE & LICENSE (admin only) ───────────────────────── */}
          {/* COMPANY SETUP - only when there is no company.

              THE WAY BACK OUT OF THE SKIP TRAP. Renders ONLY for an
              owner/admin with no company_id, so a finished account never sees
              it - the same discriminator _onboarding_in_flight uses
              server-side: the company is the FACT, the onboarding_step field
              is a CLAIM that can be wrong.

              Until this existed there was NO in-app path from company-less
              back to onboarding: the RouteGuard stops redirecting once the
              step is terminal, POST /onboarding/company 409'd, and
              ALLOWED_USER_FIELDS carries neither company_id nor
              onboarding_step, so no admin or platform operator could repair
              the account either.

              The copy states the CONSEQUENCE, not the mechanism. A user does
              not know what a company_id is; they know their projects are
              missing, and that is what brought them to Settings.
          */}
          {isAdmin && !user?.company_id && (
            <>
              <Text style={s.sectionLabel}>COMPANY</Text>
              <GlassCard
                style={[s.card, {
                  backgroundColor: semantic.attentionBg,
                  borderColor: semantic.attentionBorder,
                }]}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                  <AlertTriangle size={18} color={semantic.attention} />
                  <Text style={[s.fieldLabel, { color: semantic.attention }]}>
                    No company on your account
                  </Text>
                </View>
                <Text style={[s.hintText, { marginTop: spacing.sm }]}>
                  Projects, workers and reports all belong to a company, so none
                  of them will load until yours is set up. It takes one step.
                </Text>
                <GlassButton
                  title="Finish setting up"
                  onPress={() => router.push('/onboarding')}
                  style={{ marginTop: spacing.md, minHeight: touchTarget.min }}
                />
              </GlassCard>
            </>
          )}

          {isAdmin && (
            <>
              <Text style={s.sectionLabel}>INSURANCE & LICENSE</Text>

              {insLoading ? (
                <GlassCard style={s.card}>
                  <View style={{ alignItems: 'center', paddingVertical: spacing.md }}>
                    <ActivityIndicator size="small" color={colors.text.muted} />
                  </View>
                </GlassCard>
              ) : insState !== 'ok' ? (
                <OfflineNotice
                  mode={insState}
                  detail={insState === 'offline'
                    ? 'Insurance and DOB license details could not be loaded. This is NOT "company not linked" — reconnect to see the real license and coverage status.'
                    : 'Insurance and DOB license details could not be loaded, so coverage status is unknown.'}
                />
              ) : !gcResolved ? (
                <GlassCard style={[s.card, { backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder }]}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                    <AlertTriangle size={18} color={semantic.attention} />
                    <Text style={{ fontSize: 13, color: semantic.attention, flex: 1, lineHeight: 18 }}>
                      Company not linked to a DOB license. Contact your administrator.
                    </Text>
                  </View>
                </GlassCard>
              ) : (
                <>
                  {/* GC License card */}
                  <GlassCard style={s.card}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
                      <IconPod size={44}>
                        <Building2 size={20} strokeWidth={1.5} color={licenseActive ? semantic.verified : semantic.critical} />
                      </IconPod>
                      <View style={{ flex: 1 }}>
                        <Text style={{ fontSize: 16, fontWeight: '600', color: colors.text.primary }}>
                          GC-{insData?.gc_license_number || '--'}
                        </Text>
                        <Text style={{ fontSize: 12, fontWeight: '500', color: licenseActive ? semantic.verified : semantic.criticalText, marginTop: 2 }}>
                          {licenseStatus || 'Unknown'}
                        </Text>
                      </View>
                      {licenseActive
                        ? <CheckCircle size={20} color={semantic.verified} />
                        : <ShieldAlert size={20} color={semantic.critical} />}
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

                  {records.length === 0 ? (
                    <GlassCard style={[s.card, { alignItems: 'center', paddingVertical: spacing.lg }]}>
                      <Shield size={32} strokeWidth={1} color={colors.text.subtle} />
                      <Text style={{ fontSize: 14, fontWeight: '500', color: colors.text.primary, marginTop: spacing.sm }}>
                        No Insurance Records
                      </Text>
                      <Text style={{ fontSize: 12, color: colors.text.muted, marginTop: 4, textAlign: 'center', paddingHorizontal: spacing.md }}>
                        Enter your certificate of insurance expiry dates to enable permit renewal eligibility checks.
                      </Text>
                      <GlassButton
                        title="Enter Insurance"
                        icon={<Edit3 size={16} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={openInsuranceForm}
                        style={[s.saveBtn, { marginTop: spacing.md }]}
                      />
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
                              borderColor: isCur ? semantic.verifiedBorder : semantic.criticalBorder,
                              backgroundColor: isCur ? semantic.verifiedBg : semantic.criticalBg,
                            }}>
                              <Text style={{ fontSize: 10, fontWeight: '600', color: isCur ? semantic.verified : semantic.criticalText, textTransform: 'uppercase' }}>
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

                  {/* Inline manual-entry form */}
                  {showInsuranceForm && (
                    <GlassCard style={[s.card, { borderColor: semantic.attentionBorder }]}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md }}>
                        <CalendarDays size={18} strokeWidth={1.5} color={semantic.attention} />
                        <Text style={{ fontSize: 14, fontWeight: '600', color: colors.text.primary, flex: 1 }}>
                          Enter Certificate of Insurance Dates
                        </Text>
                      </View>
                      <Text style={{ fontSize: 12, color: colors.text.muted, marginBottom: spacing.md }}>
                        Use MM/DD/YYYY format. All three dates must be current.
                      </Text>

                      <View style={s.fieldGroup}>
                        <Text style={s.fieldLabel}>General Liability Expiry</Text>
                        <GlassInput
                          value={insGL}
                          onChangeText={setInsGL}
                          placeholder="MM/DD/YYYY"
                          keyboardType="numbers-and-punctuation"
                          autoCapitalize="none"
                        />
                      </View>

                      <View style={[s.fieldGroup, { marginTop: spacing.sm }]}>
                        <Text style={s.fieldLabel}>Workers' Comp Expiry</Text>
                        <GlassInput
                          value={insWC}
                          onChangeText={setInsWC}
                          placeholder="MM/DD/YYYY"
                          keyboardType="numbers-and-punctuation"
                          autoCapitalize="none"
                        />
                      </View>

                      <View style={[s.fieldGroup, { marginTop: spacing.sm }]}>
                        <Text style={s.fieldLabel}>Disability / DB Expiry</Text>
                        <GlassInput
                          value={insDB}
                          onChangeText={setInsDB}
                          placeholder="MM/DD/YYYY"
                          keyboardType="numbers-and-punctuation"
                          autoCapitalize="none"
                        />
                      </View>

                      <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
                        <GlassButton
                          title="Cancel"
                          variant="secondary"
                          onPress={() => setShowInsuranceForm(false)}
                          style={{ flex: 1 }}
                        />
                        <GlassButton
                          title={savingInsurance ? 'Saving...' : 'Save Insurance Dates'}
                          loading={savingInsurance}
                          icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
                          onPress={handleSaveInsurance}
                          style={{ flex: 2 }}
                        />
                      </View>
                    </GlassCard>
                  )}

                  {/* Actions row: Update Insurance (primary) + Refresh License (secondary) */}
                  {!showInsuranceForm && (
                    <>
                      {records.length > 0 && (
                        <GlassButton
                          title="Update Insurance"
                          icon={<Edit3 size={16} strokeWidth={1.5} color={colors.text.primary} />}
                          onPress={openInsuranceForm}
                          style={s.saveBtn}
                        />
                      )}

                      <GlassButton
                        title={insRefreshing ? 'Refreshing...' : 'Refresh License'}
                        variant="secondary"
                        icon={insRefreshing
                          ? <ActivityIndicator size={16} color={colors.text.primary} />
                          : <RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={handleRefreshInsurance}
                        disabled={insRefreshing}
                        style={[s.saveBtn, { marginTop: spacing.sm }]}
                      />
                    </>
                  )}

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

          {/* ── SECURITY (admin only) ──────────────────────────────────── */}
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
                    placeholder="New password"
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

          {/* ── DOB PERMIT RENEWAL (admin only) ────────────────────────── */}
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
                              backgroundColor: selectedProjectId === p.id ? semantic.verifiedBg : withAlpha('#ffffff', 0.05),
                              borderWidth: 1,
                              borderColor: selectedProjectId === p.id ? semantic.verifiedBorder : withAlpha('#ffffff', 0.1),
                            }}
                          >
                            <Text style={{ fontSize: 12, color: selectedProjectId === p.id ? chrome.brand : colors.text.muted }}>
                              {p.name || p.address || 'Project'}
                            </Text>
                          </Pressable>
                        ))}
                      </ScrollView>
                    </View>
                  )}

                  {projects.length === 0 && projectsState !== 'ok' ? (
                    <OfflineNotice
                      mode={projectsState}
                      detail={projectsState === 'offline'
                        ? 'Projects could not be loaded. This is not "no projects" — reconnect before setting the GC name.'
                        : 'Projects could not be loaded, so the GC name cannot be set right now.'}
                    />
                  ) : projects.length === 0 ? (
                    <Text style={[s.hintText, { color: semantic.attention, marginTop: 8 }]}>
                      No projects found. Create a project first, then set the GC name here.
                    </Text>
                  ) : (
                    <>
                      {gcNameState !== 'ok' && (
                        <OfflineNotice
                          mode={gcNameState}
                          detail={gcNameState === 'offline'
                            ? 'The saved GC legal name could not be loaded, so this field is blank — it is not necessarily unset. Saving now would overwrite the stored value.'
                            : 'The saved GC legal name could not be loaded, so this field may not reflect what is stored.'}
                        />
                      )}
                      <GlassInput
                        value={gcLegalName}
                        onChangeText={setGcLegalName}
                        placeholder="e.g. Blue Elm Construction Inc"
                        autoCapitalize="words"
                        editable={!loadingGc}
                      />
                    </>
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

          {/* ── SIGN OUT (only place logout lives now) ─────────────────── */}
          <Text style={s.sectionLabel}>ACCOUNT</Text>
          <GlassCard style={s.card}>
            <GlassButton
              title="Sign Out"
              onPress={handleLogout}
              icon={<LogOut size={16} strokeWidth={1.5} color="#f87171" />}
              style={s.signOutBtn}
            />
          </GlassCard>

          {/* ── ACCOUNT DELETION — Apple 5.1.1(v) ─────────────────────────
              An app that lets somebody create an account must let him remove
              it FROM INSIDE THE APP. A mailto or a "contact support" line is
              the thing the guideline was written to stop.

              A REQUEST, not a button, and the reason is his own records: a CP
              carries unsynced signed logbooks on this phone. End his access
              now and the reconnect drain takes a 401, which the client reads
              as a server refusal and banners as "your log was refused" — a
              compliance judgement the server never made. His work survives
              but is stranded on the handset and mislabelled. Drain first,
              delete second, and only a person can confirm the drain finished.

              NOT shown on a shared site device: a jobsite tablet is not
              somebody's personal account, and the server refuses it too. */}
          {/* SELF-REGISTERED ACCOUNTS ONLY. Apple 5.1.1(v) reaches accounts a
              PERSON CREATED FOR THEMSELVES; on this product nobody does. Owners
              are seeded, admins created by an owner, CPs by an admin, workers
              have no account. The one self-registration path in real use is the
              demo account Apple reviews with, so this control belongs there and
              on nothing else.

              Read from a STAMPED field, never derived. account_status
              "pending" would have worked until approval flipped it - and the
              demo account has to be approved to be reviewable, so the signal
              would vanish from the only account it exists for.

              The server refuses too (POST /auth/me/deletion-request). Hiding a
              control is presentation; the refusal is the rule. */}
          {!siteMode && user?.registration_source === 'self_registered' && (
            <>
              <Text style={s.sectionLabel}>DANGER ZONE</Text>
              <GlassCard style={s.card}>
                {deletionRequestedAt ? (
                  <>
                    <Text style={s.delRequestedTitle}>
                      Deletion requested{' '}
                      {new Date(deletionRequestedAt).toLocaleDateString(undefined, {
                        day: 'numeric', month: 'short', year: 'numeric',
                      })}
                    </Text>
                    <Text style={s.delBody}>
                      Your administrator has been notified. You can keep using
                      LeveLog until they action it.
                    </Text>
                    <GlassButton
                      title="Withdraw request"
                      onPress={handleWithdrawDeletion}
                      loading={deletionBusy}
                      style={s.delWithdrawBtn}
                    />
                  </>
                ) : (
                  <Pressable
                    onPress={() => setDeletionConfirmOpen(true)}
                    accessibilityRole="button"
                    accessibilityLabel="Request account deletion"
                    style={s.delRow}
                  >
                    <Trash2 size={16} strokeWidth={1.5} color="#f87171" />
                    <Text style={s.delRowText}>Request account deletion</Text>
                  </Pressable>
                )}
              </GlassCard>
            </>
          )}

          <Modal
            visible={deletionConfirmOpen}
            animationType="slide"
            transparent
            onRequestClose={() => setDeletionConfirmOpen(false)}
          >
            <View style={s.modalOverlay}>
              {/* THE ERROR HAS TO BE VISIBLE FROM INSIDE THE SHEET. A native
                  Modal is a separate OS window, so the app-wide toast stack
                  paints BEHIND it - a failed request would have shown the CP
                  nothing at all. ToastHost is the same stack, same component,
                  same styling, rendered in this window. */}
              <ToastHost />
              <View style={s.modalContent}>
                <Text style={s.delSheetTitle}>Request account deletion</Text>

                <Text style={s.delBody}>{accessRemovedSentence(null)}</Text>

                {/* THE TWO FACTS THAT MATTER GET CONTAINERS, and it is the same
                    container every other warning in this app uses — the
                    flagged-worker and unaffirmed-signature blocks on the CP's
                    logbook screen. GlassCard on semantic.attentionBg, an
                    AlertTriangle, an attention-coloured title.

                    They were five bare <Text> runs stacked in a modal, which
                    read as a wall of prose in which "your records are kept by
                    law" and "unsynced work is lost" carried no more weight than
                    the line about who actions the request. A destructive action
                    should look like one. */}

                {/* WHAT IS KEPT, AND WHY. "Kept by law" and not "kept for
                    compliance": the first names the reason, the second names a
                    category and leaves him to guess. */}
                <GlassCard style={s.delWarnCard}>
                  <View style={s.delWarnHeader}>
                    <ShieldCheck size={16} strokeWidth={1.5} color={semantic.attention} />
                    <Text style={s.delWarnTitle}>Your signed records stay</Text>
                  </View>
                  <Text style={s.delWarnBody}>{retentionSentence(null)}</Text>
                </GlassCard>

                {/* THE ONLY LINE HERE THAT CAN SAVE HIM SOMETHING. */}
                <GlassCard style={s.delWarnCard}>
                  <View style={s.delWarnHeader}>
                    <AlertTriangle size={16} strokeWidth={1.5} color={semantic.attention} />
                    <Text style={s.delWarnTitle}>Before you request this</Text>
                  </View>
                  <Text style={s.delWarnBody}>{drainWarning(null)}</Text>
                </GlassCard>

                <Text style={s.delBody}>
                  Your administrator will action this request and can contact
                  you first.
                </Text>

                <GlassButton
                  title="Request deletion"
                  onPress={handleRequestDeletion}
                  loading={deletionBusy}
                  style={s.delConfirmBtn}
                />
                <Pressable
                  onPress={() => setDeletionConfirmOpen(false)}
                  accessibilityRole="button"
                  style={s.delCancelRow}
                >
                  <Text style={s.delCancelText}>Cancel</Text>
                </Pressable>
              </View>
            </View>
          </Modal>

          {/* ── BUILD ────────────────────────────────────────────────────
              WHY THIS EXISTS. A device test reported Step 1 as missing its
              equipment and weather sections. They were on main and had never
              been reverted — the phone was simply running an older JS bundle
              than the backend. Time was spent diagnosing a defect that did
              not exist.

              The two identities are shown TOGETHER, because knowing the
              bundle alone does not tell you whether it matches the server.
              Not on a CP-facing compliance screen — settings only. */}
          <Text style={s.sectionLabel}>BUILD</Text>
          <GlassCard style={s.card}>
            <BuildInfoRow label="App version" value={appVersion} onCopy={copyBuild} />
            <BuildInfoRow label="JS bundle" value={jsBundle} onCopy={copyBuild} />
            <BuildInfoRow label="Bundle built" value={jsBuiltAt} onCopy={copyBuild} />
            <BuildInfoRow
              label="Backend"
              value={backendLoading ? 'checking…' : (backendCommit || 'unreachable')}
              onCopy={copyBuild}
            />
            {buildVerdict && (
              <Text style={[s.buildVerdict, buildMatches ? s.buildOk : s.buildWarn]}>
                {buildVerdict}
              </Text>
            )}
            <Pressable
              onPress={copyBuild}
              accessibilityRole="button"
              accessibilityLabel="Copy build information"
              style={s.buildCopy}
            >
              <Text style={s.buildCopyText}>
                {buildCopied ? 'Copied' : 'Tap to copy'}
              </Text>
            </Pressable>
          </GlassCard>

        </ScrollView>

        {isCp ? <CpNav /> : <FloatingNav />}

      </SafeAreaView>
    </AnimatedBackground>
  );
}

/** One label/value line. 56pt so the copy target is never smaller than the
 *  app's minimum, even though this is a read-only row. */
function BuildInfoRow({ label, value, onCopy }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  return (
    <Pressable style={s.buildRow} onPress={onCopy} accessibilityRole="button">
      <Text style={s.buildLabel}>{label}</Text>
      <Text style={s.buildValue} numberOfLines={1}>{value}</Text>
    </Pressable>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container:     { flex: 1 },
    loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    // Account deletion. 56pt row so the target is never below the app minimum.
    delRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      minHeight: 56, paddingHorizontal: spacing.xs,
    },
    delRowText:        { fontSize: 15, color: '#f87171', fontWeight: '500' },
    delRequestedTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.xs },
    delSheetTitle:     { fontSize: 18, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.md },
    // The app's warning-block treatment, not a variant of it. Identical to
    // notifCard / notifHeader / notifTitle / notifWorker on the CP's logbook
    // screen, so a destructive warning here reads the same as a compliance
    // warning there.
    delWarnCard: {
      marginBottom: spacing.md, padding: spacing.md,
      backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder,
    },
    delWarnHeader: {
      flexDirection: 'row', alignItems: 'center',
      gap: spacing.sm, marginBottom: spacing.sm,
    },
    delWarnTitle: { fontSize: 14, fontWeight: '500', color: semantic.attention, flex: 1 },
    delWarnBody:  { fontSize: 13, lineHeight: 19, color: colors.text.secondary },
    delBody:           { fontSize: 14, lineHeight: 20, color: colors.text.secondary, marginBottom: spacing.md },
    delBodyStrong:     { fontSize: 14, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.xs },
    delConfirmBtn:     { marginTop: spacing.sm },
    delWithdrawBtn:    { marginTop: spacing.sm },
    delCancelRow:      { minHeight: 56, alignItems: 'center', justifyContent: 'center' },
    delCancelText:     { fontSize: 15, color: colors.text.muted },

    backBtn:      { padding: spacing.xs },
    headerSpacer: { width: 20 + spacing.xs * 2 },
    headerTitle:  { fontSize: 17, fontWeight: '600', color: colors.text.primary },

    scroll:        { flex: 1 },
    scrollContent: {
      // paddingBottom is set INLINE at the ScrollView, from
      // insets.bottom + CP_NAV_CLEARANCE.
      //
      // IT WAS 140, AND NOTHING JUSTIFIED THAT. This screen was 110 until
      // 37227ee — "fix settings scroll on web" — bumped it to 140 as a side
      // effect of a react-native-web scroll-height fix that had nothing to do
      // with the nav. app/index.jsx carries 140 from an unexplained "Update
      // index.jsx". Two screens at 140, neither with a reason, and the other
      // ~34 uses of a bottom pad in this app are 120. The unexplained
      // difference is not preserved: one derived number, for every screen that
      // carries a floating nav.
      padding: spacing.lg,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },

    sectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
      marginTop: spacing.sm,
    },
    card: { padding: spacing.lg, marginBottom: spacing.md },

    settingRow:      { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    settingLeft:     { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
    settingTitle:    { fontSize: 15, fontWeight: '500', color: colors.text.primary },
    settingSubtitle: { fontSize: 12, color: colors.text.muted, marginTop: 1 },

    fieldGroup:   {},
    fieldIconRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
    fieldLabel:   { fontSize: 12, fontWeight: '500', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 1 },
    disabledInput:{ opacity: 0.5 },
    hintText:     { fontSize: 11, color: colors.text.subtle, marginTop: spacing.xs },

    saveBtn:    { marginTop: spacing.md },
    signOutBtn: { borderColor: semantic.criticalBorder },
    // BUILD card. touchTarget.min so the copy row is never a smaller target
    // than anything else in the app, read-only though it is.
    buildRow: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      minHeight: touchTarget.min, gap: spacing.md,
    },
    buildLabel: { color: colors.text.secondary, fontSize: typography.sizes.sm },
    buildValue: {
      color: colors.text.primary, fontSize: typography.sizes.sm,
      flexShrink: 1, textAlign: 'right',
    },
    buildVerdict: {
      fontSize: typography.sizes.sm, marginTop: spacing.sm,
    },
    buildOk: { color: semantic.verified },
    buildWarn: { color: semantic.criticalText },
    buildCopy: {
      minHeight: touchTarget.min, justifyContent: 'center', alignItems: 'center',
    },
    buildCopyText: { color: colors.text.secondary, fontSize: typography.sizes.sm },
  });
}
